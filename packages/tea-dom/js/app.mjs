// The loop, in one function: init, render, wait, dispatch, patch, wait.
//
//   init  ->  reply.patches          ->  DOM
//   event ->  address+event+payload  ->  reply.patches  ->  DOM
//
// Everything either side of the arrows is in `reactor.mjs` and `dom.mjs`;
// what is here is the wiring and the one policy decision the wiring owns:
// what to do with a reply that is not ok. The answer is "leave the document
// alone and tell the page", because an error reply carries no patches by
// construction, so there is no half-applied frame to undo.

import { Reactor } from './reactor.mjs';
import { DomHost } from './dom.mjs';

/**
 * Mount a reactor built by `dawnc build --target wasm --reactor` into `mount`.
 *
 * `onError(reply)` is called for every reply that is not ok; the default
 * reports to the console. `doc` is the document to build nodes with, and
 * exists so a harness can hand in a recording stub. `flags` is the one string
 * the page hands the guest's `init`, and is omitted from the request when it
 * is left out here; a guest built on `serve` ignores it.
 *
 * Returns the pieces, so a page can drive a turn itself (a test, a keyboard
 * shortcut, a replayed transcript).
 */
export async function mount(wasm, mountEl, { onError = defaultOnError, doc, flags } = {}) {
  const reactor = await Reactor.load(wasm);
  const host = new DomHost(mountEl, dispatch, doc);

  function settle(reply) {
    if (reply.ok) host.apply(reply.patches);
    else onError(reply);
    return reply;
  }

  function dispatch(path, event, payload) {
    settle(reactor.event(path, event, payload));
  }

  settle(reactor.init(flags));
  return { reactor, host, dispatch };
}

function defaultOnError(reply) {
  // eslint-disable-next-line no-console
  console.error(`[tea-dom] ${reply.kind}: ${reply.error}`);
}
