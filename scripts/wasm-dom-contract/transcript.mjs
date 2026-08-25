// Drive the whole loop -- wasm reactor, message boundary, DOM bridge -- with
// no browser and no clock, and print every observable step.
//
// The transcript has four kinds of line and they answer four questions:
//
//   request/reply   what crossed the boundary, verbatim
//   patch           which ops the guest emitted and at which addresses; this
//                   is the diff contract's locality, made assertable
//   dom             what the bridge did to the document for those patches
//   tree            what the document then was
//
// A turn is driven by *clicking a button found by its label*, not by naming
// an address, so the address in the request is one the bridge recovered by
// walking the document. A mutant that reverses that walk changes the request
// line, which is what makes wrong routing visible here.
//
// Determinism: no timers, no environment (the WASI shim serves an empty
// environ), and a fresh reactor instance per run. The same bytes come out of
// node, out of a browser, and -- for the request/reply lines -- out of
// `dawn run` on the JVM.

import { readFile } from 'node:fs/promises';
import { mount } from '../../packages/tea-dom/js/app.mjs';
import { Recorder, StubDocument, serialize, findByText } from './domstub.mjs';

const wasmPath = process.argv[2];
if (!wasmPath) {
  console.error('usage: node transcript.mjs <counter.wasm>');
  process.exit(2);
}

const rec = new Recorder();
const doc = new StubDocument(rec);
const root = doc.mountPoint();
const out = [];

function flush(label) {
  out.push(`--- ${label}`);
  for (const line of rec.lines) out.push(`dom      ${line}`);
  rec.lines = [];
  out.push(`tree     ${serialize(root.childNodes[0])}`);
}

// The bridge's own request/reply pair is not exposed by `mount`, so wrap the
// reactor's `request` once it exists. Wrapping rather than reimplementing is
// the point: the transcript must see what the page sees.
let app = null;
function instrument() {
  const inner = app.reactor.request.bind(app.reactor);
  app.reactor.request = (req) => {
    out.push(`request  ${JSON.stringify(req)}`);
    const reply = inner(req);
    out.push(`reply    ${JSON.stringify(reply)}`);
    if (reply.ok) {
      for (const p of reply.patches) out.push(`patch    ${p.op} [${p.path}]`);
    }
    return reply;
  };
}

const errors = [];
app = await mount(new Uint8Array(await readFile(wasmPath)), root, {
  doc,
  onError: (reply) => {
    out.push(`error    ${reply.kind}: ${reply.error}`);
    errors.push(reply);
  },
});

// `mount` already ran init; re-run it through the instrumented path so the
// transcript carries the first turn too. A reactor is a pure function of its
// request, so asking twice is not a second state.
rec.lines = [];
root.childNodes.length = 0;
app.host.root = null;
instrument();
app.host.apply(app.reactor.init().patches);
flush('init');

function click(label) {
  const button = findByText(root.childNodes[0], 'button', label);
  if (!button) throw new Error(`no button labelled ${label}`);
  out.push(`click    ${label}`);
  button.fire('click');
  flush(`after click ${label}`);
}

// (a) a full init -> render -> event -> update -> re-render turn
click('+');
click('+');

// (c) the diff-shaped case: crossing zero changes the root's class *and* the
// count, so the turn is exactly one `set-self` at [] and one `replace` at
// [1,0]. The set-self must not carry the subtree, the replace must not be a
// replace of the whole document, and the four buttons must not be rebuilt.
click('-');
click('-');
click('-');

// All four ops have now crossed: `replace` at the root (init) and deep in the
// tree (the count), `append` and `truncate` at the bar (counting up and back
// down), and `set-self` at the root (crossing zero). There is no fifth op in
// `tea_core/diff`, so this is the whole table.

// (b) the guest's `update` panics. The failure runtime lands it, the guest
// answers with an error, the document is untouched, and the next turn works.
click('boom');
click('+');

// The desync case the bridge refuses to paper over: an address that no longer
// listens for what the host claims. Nothing in a real page produces it, so it
// is driven directly.
out.push('direct   an event at an address that listens for nothing');
const bad = app.reactor.event([0], 'click');
out.push(`ok       ${bad.ok}`);
flush('after a stray event');

out.push(`errors   ${errors.length}`);
process.stdout.write(out.join('\n') + '\n');
