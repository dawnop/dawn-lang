// The same loop as transcript.mjs, driven against the app one tier up:
// a list whose rows carry identity, a draft the user types, and a mode.
//
// Why a second transcript rather than more clicks in the first. The counter's
// child list varies only in *length*, so pairing children by index is always
// right for it and the two costs this file exists to pin cannot appear there:
//
//   middle deletion   deleting a row in the middle of five rewrites every
//                     row after it, because `diff` pairs by index and the
//                     row that was at 3 is now at 2. The patch lines count
//                     it; the `dom` lines show it happening to real nodes.
//   lifted local      the composer draft and the row editor's draft are
//   state             model fields, so one keystroke is a whole turn: a
//                     request, a reply carrying the entire model, and a
//                     patch. The transcript is what makes that per-character
//                     cost a number rather than a worry.
//
// The line kinds are transcript.mjs's, plus one. `state` is a focused
// serialization -- the root's class, the composer's text, the `<ul>` subtree
// and the status line -- because the whole document is 28 key buttons wide
// and printing it every turn would bury the rows. The one full `tree` line
// after init is what says the rest of the document is there at all, and the
// `dom` lines are unfiltered, so a mutation anywhere (including in the key
// palette, where there must never be one after init) still shows up.
//
// Determinism is transcript.mjs's: no timers, no environment, a fresh
// reactor per run, and every click aimed by walking the document rather than
// by naming an address.

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

/** Root class, composer text, the list subtree, and the status line. */
function state() {
  const app = document_();
  const list = elementsBy(app, (n) => n.tagName === 'ul')[0];
  const field = elementsBy(app, (n) => hasClass(n, 'field'))[0];
  const status = elementsBy(app, (n) => hasClass(n, 'status'))[0];
  return [
    `root=${JSON.stringify(app.getAttribute('class'))}`,
    `field=${JSON.stringify(textOf(field))}`,
    `status=${JSON.stringify(textOf(status))}`,
    serialize(list),
  ].join(' ');
}

// Every turn but the first prints its DOM mutations one per line. The first
// builds the whole document -- 28 key buttons among other things -- and its
// mutation list is a couple of hundred lines that say nothing the `tree`
// line below it does not, so it is counted instead. Every later turn must
// mutate nothing outside the region it changed, and that is only assertable
// if the later lines are unfiltered.
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
// transcript carries the first turn too. A reactor is a pure function of its
// request, so asking twice is not a second state.
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

// ---- five todos, one character each --------------------------------------
//
// A title is one letter so that a whole todo costs two turns; the point of
// this section is the *shape* of the list, and the per-keystroke cost is
// measured once below rather than five times here.
for (const letter of ['a', 'b', 'c', 'd', 'e']) {
  press(byClassAndText('key', letter), `key ${letter}`);
  press(byClassAndText('add', 'add'), `add (${letter})`);
}

// ---- the filter, which is a class change and a rebuilt list ---------------
press(byClassAndText('filter', 'done'), 'filter done');
press(byClassAndText('filter', 'all'), 'filter all');

// ---- state that lives on a row, in the tail of the deletion below ---------
press(inRow(1, 'box'), 'toggle row 1');
press(inRow(4, 'title'), 'edit row 4');
press(byClassAndText('key', 'z'), 'key z into the row draft');

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
