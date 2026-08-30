// The same loop as transcript.mjs, driven against the app one tier up:
// a list whose rows carry identity, two fields the user types into, and a
// mode.
//
// Why a second transcript rather than more clicks in the first. The counter's
// child list varies only in *length*, so pairing children by index is always
// right for it and the three things this file exists to pin cannot appear
// there:
//
//   middle deletion   deleting a row in the middle of five rewrites every
//                     row after it, because `diff` pairs by index and the
//                     row that was at 3 is now at 2. The patch lines count
//                     it; the `dom` lines show it happening to real nodes.
//   lifted local      the composer's draft and the row editor's draft are
//   state             model fields, so an edit to either is a whole turn: a
//                     request, a reply carrying the entire model, and a
//                     patch. The transcript is what makes that a number
//                     rather than a worry.
//   event payloads    a listener that asked for the element's value, the
//                     `payload` on the request line that carries it, and the
//                     `prop <input> value=` mutation that writes the model
//                     back into the controlled field. The counter has no
//                     field and declares no payload.
//
// The line kinds are transcript.mjs's, plus one. `state` is a focused
// serialization -- the root's class, the composer's value, the `<ul>` subtree
// and the status line -- because those are what a turn here is about, and a
// full serialization every turn would repeat the heading and the filter bar
// twelve times over the rows that changed. The one full `tree` line after
// init is what says the rest of the document is there at all, and the `dom`
// lines are unfiltered, so a mutation anywhere still shows up.
//
// Determinism is transcript.mjs's: no timers, no environment, a fresh
// reactor per run, and every click aimed by walking the document rather than
// by naming an address. Typing is the same: a case types into the element it
// found, exactly as a user would, and what reaches the boundary is whatever
// the bridge then read off it.

import { readFile } from 'node:fs/promises';
import { mount } from '../../packages/tea-dom/js/app.mjs';
import { Recorder, StubDocument, serialize } from './domstub.mjs';

const wasmPath = process.argv[2];
if (!wasmPath) {
  console.error('usage: node transcript-todo.mjs <todo.wasm>');
  process.exit(2);
}

const rec = new Recorder();
const doc = new StubDocument(rec);
const root = doc.mountPoint();
const out = [];

// ---- reading the stub document -------------------------------------------

function textOf(node) {
  if (!node) return '';
  if (node.nodeType === 3) return node.nodeValue;
  return node.childNodes.map(textOf).join('');
}

function elementsBy(node, pred, found = []) {
  if (node && node.nodeType === 1) {
    if (pred(node)) found.push(node);
    for (const kid of node.childNodes) elementsBy(kid, pred, found);
  }
  return found;
}

function hasClass(node, cls) {
  const value = node.getAttribute('class');
  return value !== null && value.split(' ').includes(cls);
}

function document_() {
  return root.childNodes[0];
}

function rows() {
  return elementsBy(document_(), (n) => n.tagName === 'li');
}

/** The button whose class is `cls` inside row `i` (0-based, as displayed). */
function inRow(i, cls) {
  const row = rows()[i];
  if (!row) throw new Error(`no row ${i}`);
  const hit = elementsBy(row, (n) => hasClass(n, cls))[0];
  if (!hit) throw new Error(`row ${i} has no .${cls}`);
  return hit;
}

function byClassAndText(cls, label) {
  const hit = elementsBy(document_(), (n) => hasClass(n, cls) && textOf(n) === label)[0];
  if (!hit) throw new Error(`no .${cls} labelled ${label}`);
  return hit;
}

/** Root class, composer value, the list subtree, and the status line. */
function state() {
  const app = document_();
  const list = elementsBy(app, (n) => n.tagName === 'ul')[0];
  const field = elementsBy(app, (n) => hasClass(n, 'field'))[0];
  const status = elementsBy(app, (n) => hasClass(n, 'status'))[0];
  return [
    `root=${JSON.stringify(app.getAttribute('class'))}`,
    // The composer's text is its live `value`, not its children: it is an
    // `<input>`, so what the user sees is a property and the model reaches it
    // as one. Reading `textContent` here would report the empty string
    // however the field was written, which is the failure this whole line
    // exists to make visible.
    `field=${JSON.stringify(field.value)}`,
    `status=${JSON.stringify(textOf(status))}`,
    serialize(list),
  ].join(' ');
}

// Every turn but the first prints its DOM mutations one per line. The first
// builds the whole document and its mutation list says nothing the `tree`
// line below it does not, so it is counted instead -- and the count is the
// number the keyboard used to dominate, which is why it stays a number.
// Every later turn must mutate nothing outside the region it changed, and
// that is only assertable if the later lines are unfiltered.
function flush(label, full = false) {
  out.push(`--- ${label}`);
  if (full) {
    out.push(`dom      ${rec.lines.length} mutations built the document`);
  } else {
    for (const line of rec.lines) out.push(`dom      ${line}`);
  }
  rec.lines = [];
  out.push(full ? `tree     ${serialize(document_())}` : `state    ${state()}`);
}

// ---- the boundary, instrumented ------------------------------------------

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
// transcript carries the first turn too. This todo app uses the stateless
// `serve` entry point, so asking twice does not create hidden guest state.
rec.lines = [];
root.childNodes.length = 0;
app.host.root = null;
instrument();
app.host.apply(app.reactor.init().patches);
flush('init', true);

function press(element, what) {
  out.push(`click    ${what}`);
  element.fire('click');
  flush(`after ${what}`);
}

// The user types into a field: the whole value it now holds, once, which is
// what a browser reports on an `input` event. The bridge decides what to read
// off the element and what to put on the request line, so a case supplies no
// payload of its own -- it changes the document and fires, and the request
// line is the evidence of what the bridge made of that.
function typeInto(element, value, what) {
  out.push(`type     ${what} <- ${JSON.stringify(value)}`);
  element.typeInto(value);
  element.fire('input');
  flush(`after ${what}`);
}

function field() {
  return elementsBy(document_(), (n) => hasClass(n, 'field'))[0];
}

// ---- five todos, two turns each ------------------------------------------
//
// A title is one letter here because the point of this section is the *shape*
// of the list; the length of a title costs nothing now, which is what the
// section after the filters says with a word instead.
for (const letter of ['a', 'b', 'c', 'd', 'e']) {
  typeInto(field(), letter, `title ${letter}`);
  press(byClassAndText('add', 'add'), `add (${letter})`);
}

// ---- the filter, which is a class change and a rebuilt list ---------------
press(byClassAndText('filter', 'done'), 'filter done');
press(byClassAndText('filter', 'all'), 'filter all');

// ---- state that lives on a row, in the tail of the deletion below ---------
//
// The word typed into the row's editor is four characters and costs one turn,
// which is the whole of what the payload bought: the palette this replaced
// spent a turn, a request carrying the entire model and a patch on each of
// them. The request line below is where the four characters cross.
press(inRow(1, 'box'), 'toggle row 1');
press(inRow(4, 'title'), 'edit row 4');
typeInto(inRow(4, 'draft'), 'milk', 'retitle row 4');

// ---- the measurement: delete a row in the middle -------------------------
//
// Row 1 goes. Rows 2, 3 and 4 keep their identity to the user and lose it to
// the reconciler: every one of them is paired against the row that used to
// be its neighbour, so the patch lines below are the tail rewrite, and the
// `dom` lines are it happening to nodes a browser would have focus inside.
// The edited row is the last one on purpose: it is the node whose element
// state a keyed diff would have kept.
press(inRow(1, 'kill'), 'delete row 1 (the middle)');

// ---- the guest panics, and the page survives it --------------------------
press(byClassAndText('boom', 'boom'), 'boom');

// ---- and the edit still commits, at its new index -------------------------
press(inRow(3, 'save'), 'save the edited row');

// ---- the desync the bridge refuses to paper over -------------------------
out.push('direct   an event at an address that listens for nothing');
const bad = app.reactor.event([0], 'click');
out.push(`ok       ${bad.ok}`);
out.push(`kind     ${bad.kind}`);
flush('after a stray event');

out.push(`errors   ${errors.length}`);
process.stdout.write(out.join('\n') + '\n');
