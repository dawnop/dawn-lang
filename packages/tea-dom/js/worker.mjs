// The reactor in a worker: the same turns as `app.mjs`, off the page's thread.
//
// A turn is a function from one line to one line, so nothing about it needs
// the document, and everything it costs -- compiling the module, an init that
// parses a few hundred kilobytes of flags, every `dawn_turn` after that -- is
// time the page's own thread cannot spend answering the reader. Here it is
// spent on another thread, and the page keeps only what has to touch the
// document: applying the patches (`remote.mjs`).
//
// The protocol is the bridge's own wire with an id on it. In: `load` with the
// module's bytes, then `init` and `event` exactly as `Reactor` takes them. Out:
// `{id, reply}` with the reply object the guest wrote, or `{id, thrown}` when
// the host side of a turn threw (a guest that answered more than one line, a
// module with no `dawn_turn`). The model stays here, inside the `Reactor`, and
// never crosses to the page: the page has never read it, and a model that
// crossed twice per turn would be the largest thing on the wire.
//
// Fetches. A reply may carry `fetch: [{url, tag}]`, the guest naming what it
// wants (tea_core/cmd's `Fetch`). The worker posts the reply first, then does
// each fetch on its own time and posts `{fetched: {tag, outcome}}` for each.
// It does not feed the outcome to the reactor itself: a supply is a turn, and
// the page owns the order of turns (an event it already sent was addressed
// against a document the supply would change). So the page queues the supply
// like any event and sends it back as `supply`.
//
// Messages are handled strictly in arrival order, one at a time, because a
// turn is defined against the model the previous one left. `load` is the only
// asynchronous step and a chain of promises is what keeps a turn that arrives
// during it from running against no reactor at all.

import { Reactor, runFetch } from './reactor.mjs';

let reactor = null;
let queue = Promise.resolve();

async function handle(msg) {
  if (msg.op === 'load') {
    reactor = await Reactor.load(msg.wasm);
    return { ok: true };
  }
  if (!reactor) throw new Error('a turn arrived before the module was loaded');
  if (msg.op === 'init') return reactor.init(msg.flags);
  if (msg.op === 'event') return reactor.event(msg.path, msg.event, msg.payload);
  if (msg.op === 'supply') return reactor.supply(msg.tag, msg.outcome);
  throw new Error(`unknown request \`${msg.op}\``);
}

self.onmessage = (ev) => {
  const msg = ev.data;
  queue = queue.then(() => handle(msg)).then(
    (reply) => {
      self.postMessage({ id: msg.id, reply });
      for (const f of (reply && reply.fetch) || []) {
        runFetch(f.url).then((outcome) => self.postMessage({ fetched: { tag: f.tag, outcome } }));
      }
    },
    (e) => self.postMessage({ id: msg.id, thrown: String((e && e.message) || e) }),
  );
};
