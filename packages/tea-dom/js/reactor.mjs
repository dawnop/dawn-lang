// The message-passing half of the bridge: instantiate the reactor, hand it
// one request, read one reply.
//
// The module is a reactor, so it is instantiated once and called into many
// times. `_initialize` runs wasi-libc's constructors; `dawn_turn` is the
// export `dawnc build --target wasm --reactor` appends, and it runs the
// program's `main`, which drains the one line on stdin and returns.
//
// Nothing but bytes crosses. There is no `externref`, no JS value reachable
// from the guest, and no handle the guest holds across a turn -- the model
// is opaque text this class carries between calls, which it never reads.
// The reason is lifetimes: a reference held across the boundary is owned by
// neither side's type system, and the one thing a wasm guest and a page
// share for free is a byte range.

import { Wasi, WasiExit } from './wasi.mjs';

export class Reactor {
  /**
   * `source` is anything `WebAssembly.compile` takes: bytes in node, or the
   * `Response` from `fetch` in a browser, which is read to completion here
   * and then compiled from that buffer.
   *
   * Not `compileStreaming`. Buffering costs one whole copy of the module at
   * load, and buys indifference to the mime type: a `.wasm` served as
   * `text/plain` mounts, because nothing here ever asks. Streaming reverses
   * both, so a server sending `application/wasm` is a precondition of that
   * change and not of this code.
   */
  static async load(source) {
    const bytes = source instanceof Uint8Array || source instanceof ArrayBuffer
      ? source
      : new Uint8Array(await source.arrayBuffer());
    const wasi = new Wasi();
    const module = await WebAssembly.compile(bytes);
    const instance = await WebAssembly.instantiate(module, wasi.importsFor(module));
    wasi.bind(instance);
    if (typeof instance.exports.dawn_turn !== 'function') {
      throw new Error(
        'this module exports no `dawn_turn`: build it with ' +
          '`dawnc build --target wasm --reactor`',
      );
    }
    instance.exports._initialize();
    return new Reactor(instance, wasi);
  }

  constructor(instance, wasi) {
    this.instance = instance;
    this.wasi = wasi;
    this.model = null;
  }

  /**
   * One turn. `request` is a plain object; the reply is a plain object.
   *
   * A guest that writes anything but exactly one line is a broken guest and
   * says so here rather than at the DOM, because a half-read reply applied
   * to a document is the failure that is hard to read backwards.
   */
  request(request) {
    this.wasi.writeStdin(JSON.stringify(request) + '\n');
    try {
      this.instance.exports.dawn_turn();
    } catch (e) {
      if (e instanceof WasiExit) {
        return { ok: false, kind: 'aborted', error: e.message };
      }
      throw e;
    }
    const out = this.wasi.takeStdout();
    const lines = out.split('\n').filter((l) => l !== '');
    if (lines.length !== 1) {
      throw new Error(`the guest answered ${lines.length} lines, expected 1: ${out}`);
    }
    return JSON.parse(lines[0]);
  }

  /** The first turn: no model yet, and the reply carries the whole document. */
  init() {
    return this.#keep(this.request({ op: 'init' }));
  }

  /**
   * A later turn: an address and an event name, against the model held here.
   *
   * `payload` is the one string the guest's listener asked to have brought
   * back, and is left off the request entirely when there is none. Absent and
   * empty are different answers on this wire -- the guest refuses a turn whose
   * payload does not match what the listener declared -- so an omitted field
   * has to stay omitted rather than become `""` or `null`.
   */
  event(path, event, payload) {
    const request = { op: 'event', model: this.model, path, event };
    if (payload !== undefined) request.payload = payload;
    return this.#keep(this.request(request));
  }

  // An error reply carries no model and no patches, so the one already held
  // stays valid: a failed turn leaves the page exactly as it was.
  #keep(reply) {
    if (reply.ok) this.model = reply.model;
    return reply;
  }
}
