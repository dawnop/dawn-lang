// The page's half of a reactor that runs in a worker (`worker.mjs`).
//
// `app.mjs` runs a turn inside the DOM event that caused it: the guest is
// called, the patches are applied, and the listener returns. That is the
// simplest loop there is, and on a page it puts every millisecond the guest
// spends on the thread that also has to paint and take the next keystroke.
// Here the guest runs on another thread and this module keeps the rest: the
// document, the listeners, and the order of turns.
//
// What being asynchronous costs, and how each cost is paid:
//
// - An address goes stale while a turn is in flight. A listener fires, its
//   turn is queued behind one whose patches have not arrived, and those
//   patches may move or remove the element it fired on. So a queued event
//   carries its element, not its address, and the address is recovered again
//   when the turn is sent -- against the document the guest's model now
//   describes, which is exactly the document a synchronous host would have
//   had by then. An element that has left the document by then has nothing
//   to say to the guest, and its event is dropped.
//
// - Turns are sent one at a time. The guest's model is a function of every
//   turn before it, so a second turn may not be sent until the first one's
//   patches are in the document (the address argument above needs that too).
//   Keystrokes typed meanwhile wait here, in order.
//
// - A patch can roll a field back. Typing `h` sends a turn; typing `e` before
//   it is answered queues one; the answer to the first sets the field to `h`,
//   over the `he` the reader can see. The guest is not wrong -- it has not
//   heard of `e` yet -- and it will set `he` one turn later, but the caret
//   has jumped in between. So while turns are still queued, the focused
//   control's live value and selection are put back after the patches: the
//   queued turn carries that value, and the guest is about to agree with it.
//
// Errors are the same policy as `app.mjs`: a reply that is not ok carries no
// patches, the document is left alone, and `onError` is told. A worker that
// fails outright (it could not load, or a turn threw on its side) rejects the
// turn's promise and every one after it: there is no reactor left to answer.

import { DomHost } from './dom.mjs';

export class Remote {
  /**
   * `worker` is a `Worker` running `worker.mjs` (as a module worker), or
   * anything with `postMessage` and an `onmessage`/`onerror` slot, which is
   * what lets a harness run the other side in the same thread.
   */
  constructor(worker) {
    this.worker = worker;
    this.next = 0;
    this.waiting = new Map();
    this.dead = null;
    worker.onmessage = (ev) => {
      const { id, reply, thrown } = ev.data;
      const w = this.waiting.get(id);
      if (!w) return;
      this.waiting.delete(id);
      if (thrown !== undefined) w.reject(new Error(thrown));
      else w.resolve(reply);
    };
    worker.onerror = (ev) => {
      if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
      this.#die(new Error(`the reactor's worker failed: ${(ev && ev.message) || 'it could not be loaded'}`));
    };
    worker.onmessageerror = () => this.#die(new Error("a message from the reactor's worker could not be read"));
  }

  #die(error) {
    if (!this.dead) this.dead = error;
    for (const w of this.waiting.values()) w.reject(this.dead);
    this.waiting.clear();
  }

  /** One request to the worker; the promise is its answer. */
  call(msg, transfer = []) {
    if (this.dead) return Promise.reject(this.dead);
    const id = this.next++;
    return new Promise((resolve, reject) => {
      this.waiting.set(id, { resolve, reject });
      this.worker.postMessage({ ...msg, id }, transfer);
    });
  }

  /**
   * Hand the worker the module: bytes, an `ArrayBuffer`, or a `Response`,
   * which is read here. The buffer is transferred rather than copied, so it
   * is unusable on this side afterwards. Compiling and instantiating happen
   * on the worker's thread; nothing is initialised yet, so this can be called
   * before the page knows what it will mount.
   */
  async load(source) {
    let buf;
    if (source instanceof ArrayBuffer) buf = source;
    else if (source instanceof Uint8Array) buf = source.slice().buffer;
    else buf = await source.arrayBuffer();
    await this.call({ op: 'load', wasm: buf }, [buf]);
    return this;
  }

  /**
   * Mount into `mountEl`, after `load`. The options are `app.mjs`'s
   * (`onError`, `doc`, `flags`) and one more: `onTurn(reply)`, called after
   * every ok reply has been applied, which is where a page that used to read
   * the document right after a synchronous turn now reads it.
   *
   * Resolves once init's patches are in the document, with `{ host, dispatch,
   * init, idle }`: `init(flags)` starts the guest again from new flags, queued
   * behind any turn already waiting, and resolves with its reply once that is
   * applied; `idle()` resolves once no turn is waiting or in flight, which is
   * when the document is the one a synchronous host would show by now.
   */
  async mount(mountEl, { onError = defaultOnError, onTurn, doc, flags } = {}) {
    const remote = this;
    const queue = [];
    let busy = false;
    let idlers = [];
    const host = new DomHost(mountEl, dispatch, doc);
    const document_ = host.doc;

    function dispatch(path, event, payload, el) {
      queue.push({ op: 'event', path, event, payload, el });
      pump();
    }

    function idle() {
      if (!busy && queue.length === 0) return Promise.resolve();
      return new Promise((resolve) => idlers.push(resolve));
    }

    function init(f) {
      return new Promise((resolve, reject) => {
        queue.push({ op: 'init', flags: f, resolve, reject });
        pump();
      });
    }

    // The focused control inside the mount, as the reader has it now.
    function live() {
      const el = document_ && document_.activeElement;
      if (!el || !mountEl.contains || !mountEl.contains(el) || typeof el.value !== 'string') return null;
      let start = null;
      let end = null;
      try {
        start = el.selectionStart;
        end = el.selectionEnd;
      } catch (e) {
        // a control with no selection (a checkbox, a select) keeps only its value
      }
      return { el, value: el.value, start, end };
    }

    function putBack(k) {
      if (!k || !k.el.isConnected || k.el.value === k.value) return;
      k.el.value = k.value;
      if (k.start !== null) {
        try {
          k.el.setSelectionRange(k.start, k.end);
        } catch (e) {
          // as above
        }
      }
    }

    function settle(reply) {
      if (!reply.ok) {
        onError(reply);
        return;
      }
      const keep = queue.some((j) => j.op === 'event') ? live() : null;
      host.apply(reply.patches);
      putBack(keep);
      if (onTurn) onTurn(reply);
    }

    async function pump() {
      if (busy) return;
      busy = true;
      while (queue.length) {
        const job = queue.shift();
        let request;
        if (job.op === 'event') {
          const path = job.el ? host.addressOf(job.el) : job.path;
          if (path === null) continue;
          request = { op: 'event', path, event: job.event };
          if (job.payload !== undefined) request.payload = job.payload;
        } else {
          request = { op: 'init' };
          if (job.flags !== undefined) request.flags = job.flags;
        }
        let reply;
        try {
          reply = await remote.call(request);
        } catch (e) {
          if (job.reject) job.reject(e);
          else onError({ ok: false, kind: 'worker', error: String((e && e.message) || e) });
          continue;
        }
        settle(reply);
        if (job.resolve) job.resolve(reply);
      }
      busy = false;
      const waiting = idlers;
      idlers = [];
      for (const resolve of waiting) resolve();
    }

    await init(flags);
    return { host, dispatch, init, idle };
  }
}

function defaultOnError(reply) {
  // eslint-disable-next-line no-console
  console.error(`[tea-dom] ${reply.kind}: ${reply.error}`);
}
