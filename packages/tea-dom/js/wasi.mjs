// A WASI preview1 host for one thing: handing a reactor a line and reading
// the line it answers with.
//
// Why not node:wasi. The browser has no such module, and the whole point of
// this bridge is that the same JavaScript runs in both places -- if the
// harness ran on a different host than the page, the harness would be
// testing something the page does not do. The module imports eight
// functions (`node -e` over the built .wasm will list them), all of them
// stdio or environment, so the shim is small enough to read in one sitting
// and has no dependency of any kind.
//
// Stdin is a byte queue the caller refills before each turn, and end of the
// queue is end of input: the guest's `read_line` reads until a newline and
// then reads again, sees zero bytes, and returns. That is what makes one
// call into the reactor answer exactly one message.
//
// The four errno values used below are from the preview1 table:
// 0 success, 8 badf, 28 inval, 70 spipe.

const ERRNO_SUCCESS = 0;
const ERRNO_BADF = 8;
const ERRNO_SPIPE = 70;

// preview1 filetype 2 is a character device, which is what a pipe-less
// stdio stream should look like to a libc deciding how to buffer.
const FILETYPE_CHARACTER_DEVICE = 2;

export class Wasi {
  constructor() {
    this.memory = null;
    this.stdin = new Uint8Array(0);
    this.stdinPos = 0;
    this.stdout = [];
    this.stderr = [];
    this.exitCode = null;
  }

  /** The import object to instantiate the module with. */
  get imports() {
    return { wasi_snapshot_preview1: this.#preview1() };
  }

  /** Call once, after instantiation, before anything else. */
  bind(instance) {
    this.memory = instance.exports.memory;
  }

  /** Queue the bytes the guest's next reads will see, and nothing after. */
  writeStdin(text) {
    this.stdin = new TextEncoder().encode(text);
    this.stdinPos = 0;
  }

  /** Everything the guest has written to fd 1 since the last take. */
  takeStdout() {
    const s = this.stdout.join('');
    this.stdout = [];
    return s;
  }

  /** Everything the guest has written to fd 2 since the last take. */
  takeStderr() {
    const s = this.stderr.join('');
    this.stderr = [];
    return s;
  }

  #view() {
    return new DataView(this.memory.buffer);
  }

  #bytes() {
    return new Uint8Array(this.memory.buffer);
  }

  // An iovec array is (ptr, len) pairs of u32, which is the only pointer
  // shape any of these calls uses.
  #iovs(ptr, count) {
    const view = this.#view();
    const out = [];
    for (let i = 0; i < count; i++) {
      out.push({
        ptr: view.getUint32(ptr + i * 8, true),
        len: view.getUint32(ptr + i * 8 + 4, true),
      });
    }
    return out;
  }

  #preview1() {
    const decoder = new TextDecoder('utf-8', { fatal: false });
    return {
      // No environment at all. The guest's `getenv` therefore answers null
      // for everything, which is the determinism this harness wants: a run
      // cannot pick up a DAWN_* switch from whatever shell started node.
      environ_sizes_get: (countPtr, sizePtr) => {
        const view = this.#view();
        view.setUint32(countPtr, 0, true);
        view.setUint32(sizePtr, 0, true);
        return ERRNO_SUCCESS;
      },
      environ_get: () => ERRNO_SUCCESS,

      fd_close: () => ERRNO_SUCCESS,

      fd_fdstat_get: (fd, statPtr) => {
        if (fd > 2) return ERRNO_BADF;
        const view = this.#view();
        view.setUint8(statPtr, FILETYPE_CHARACTER_DEVICE);
        view.setUint16(statPtr + 2, 0, true);
        view.setBigUint64(statPtr + 8, 0n, true);
        view.setBigUint64(statPtr + 16, 0n, true);
        return ERRNO_SUCCESS;
      },

      // Not seekable, and saying so is what makes libc treat the stream as a
      // pipe rather than trying to rewind it.
      fd_seek: () => ERRNO_SPIPE,

      fd_read: (fd, iovsPtr, iovsLen, nreadPtr) => {
        if (fd !== 0) return ERRNO_BADF;
        const mem = this.#bytes();
        let read = 0;
        for (const iov of this.#iovs(iovsPtr, iovsLen)) {
          const left = this.stdin.length - this.stdinPos;
          if (left <= 0) break;
          const n = Math.min(iov.len, left);
          mem.set(this.stdin.subarray(this.stdinPos, this.stdinPos + n), iov.ptr);
          this.stdinPos += n;
          read += n;
          if (n < iov.len) break;
        }
        this.#view().setUint32(nreadPtr, read, true);
        return ERRNO_SUCCESS;
      },

      fd_write: (fd, iovsPtr, iovsLen, nwrittenPtr) => {
        if (fd !== 1 && fd !== 2) return ERRNO_BADF;
        const mem = this.#bytes();
        const sink = fd === 1 ? this.stdout : this.stderr;
        let written = 0;
        for (const iov of this.#iovs(iovsPtr, iovsLen)) {
          sink.push(decoder.decode(mem.subarray(iov.ptr, iov.ptr + iov.len)));
          written += iov.len;
        }
        this.#view().setUint32(nwrittenPtr, written, true);
        return ERRNO_SUCCESS;
      },

      // A reactor that calls this has aborted: there is no way back into a
      // module whose libc has torn itself down, so the exception unwinds out
      // through the guest frames and the caller decides what to tell the
      // user. `tea_dom`'s `serve` catches an application's panic before it
      // gets here, so reaching this is a runtime failure, not a bug in the
      // app being demonstrated.
      proc_exit: (code) => {
        this.exitCode = code;
        throw new WasiExit(code);
      },
    };
  }
}

/** Thrown out of a guest call by `proc_exit`. */
export class WasiExit extends Error {
  constructor(code) {
    super(`the wasm guest called proc_exit(${code})`);
    this.name = 'WasiExit';
    this.code = code;
  }
}
