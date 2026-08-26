// The three keyed ops, at the bridge, with no wasm and no browser.
//
// Why this exists separately from scripts/wasm-dom-contract. That gate drives
// two real applications end to end, and neither of them keys its children, so
// `insert`/`remove`/`move` never appear in either transcript. Rather than key
// an application to reach three lines of JavaScript, this feeds the bridge the
// patch lists a keyed application would produce and asserts on what the
// document then did.
//
// What it asserts, and why each one needs a test of its own:
//
//   1. the recorded mutations -- that the ops touch what they say and nothing
//      else, which is the count `remove` exists to make small
//   2. node identity across a move -- that the element in the new slot is the
//      *same object*, since the entire value of `move` is the state a browser
//      keeps inside an element that a rebuilt one would not have
//   3. the reference child a move inserts before -- the off-by-one that only
//      shows up when a node travels to the right, and which raises nothing
//
// Run it through keyed-ops.sh, which adds the mutants; run.sh calls that.

import { DomHost } from '../../packages/tea-dom/js/dom.mjs';
import { Recorder, StubDocument, serialize } from './domstub.mjs';

let failures = 0;

function check(what, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) {
    console.log(`OK   ${what}`);
  } else {
    console.log(`FAIL ${what}\n  got  ${g}\n  want ${w}`);
    failures += 1;
  }
}

function li(label) {
  return { t: 'elem', tag: 'li', props: [], on: [], kids: [{ t: 'text', s: label }] };
}

// A `<ul>` holding the labelled rows, mounted, with the build noise dropped
// so that what a case records is only what its own patches did.
function mounted(labels) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const mount = doc.createElement('body');
  const host = new DomHost(mount, () => {}, doc);
  host.apply([
    { path: [], op: 'replace', node: { t: 'elem', tag: 'ul', props: [], on: [], kids: labels.map(li) } },
  ]);
  rec.lines.length = 0;
  return { host, rec, ul: host.root };
}

// ---- remove ---------------------------------------------------------------
{
  const { host, rec, ul } = mounted(['a', 'b', 'c', 'd']);
  const survivors = [ul.childNodes[0], ul.childNodes[2], ul.childNodes[3]];
  host.apply([{ path: [], op: 'remove', at: 1 }]);
  check('remove: one mutation and no rebuild', rec.lines, ['remove <li> from <ul>']);
  check('remove: the document is what is left', serialize(ul), '<ul><li>a</li><li>c</li><li>d</li></ul>');
  check(
    'remove: every surviving element is the element it was',
    ul.childNodes.map((n, i) => n === survivors[i]),
    [true, true, true],
  );
}

// ---- insert ---------------------------------------------------------------
{
  const { host, rec, ul } = mounted(['a', 'c']);
  const neighbours = [ul.childNodes[0], ul.childNodes[1]];
  host.apply([{ path: [], op: 'insert', at: 1, node: li('b') }]);
  check('insert: the new row lands between its neighbours', serialize(ul), '<ul><li>a</li><li>b</li><li>c</li></ul>');
  check('insert: the neighbours are untouched', [ul.childNodes[0] === neighbours[0], ul.childNodes[2] === neighbours[1]], [true, true]);
  check('insert: it builds one row and inserts it', rec.lines, [
    'create <li>',
    'create text "b"',
    'append text \"b\" to <li>',
    'insert <li> into <ul> before <li>',
  ]);
}

{
  // Past the end is a position a list has, and `insertBefore(node, null)` is
  // what the DOM calls it. A bridge that read `at` as an index into the list
  // it already has would throw here or put the row in the wrong place.
  const { host, ul } = mounted(['a', 'b']);
  host.apply([{ path: [], op: 'insert', at: 2, node: li('c') }]);
  check('insert: at the end is the end', serialize(ul), '<ul><li>a</li><li>b</li><li>c</li></ul>');
}

// ---- move -----------------------------------------------------------------
{
  const { host, rec, ul } = mounted(['a', 'b', 'c']);
  const moving = ul.childNodes[2];
  host.apply([{ path: [], op: 'move', from: 2, to: 0 }]);
  check('move left: one mutation, no create', rec.lines, ['insert <li> into <ul> before <li>']);
  check('move left: the order is the new order', serialize(ul), '<ul><li>c</li><li>a</li><li>b</li></ul>');
  check('move left: the element that moved is the element that was there', ul.childNodes[0] === moving, true);
}

{
  // The off-by-one. `to` counts positions in the list as it will be, while
  // the reference child is read from the list as it is, with the moving node
  // still in it. A bridge that forgets that puts the row one place short and
  // raises nothing.
  const { host, rec, ul } = mounted(['a', 'b', 'c', 'd']);
  const moving = ul.childNodes[0];
  host.apply([{ path: [], op: 'move', from: 0, to: 2 }]);
  check('move right: the row lands at `to`, counted in the new list', serialize(ul), '<ul><li>b</li><li>c</li><li>a</li><li>d</li></ul>');
  check('move right: still one mutation and no create', rec.lines, ['insert <li> into <ul> before <li>']);
  check('move right: the same element made the trip', ul.childNodes[2] === moving, true);
}

{
  // To the very end there is no reference child at all.
  const { host, rec, ul } = mounted(['a', 'b', 'c']);
  const moving = ul.childNodes[0];
  host.apply([{ path: [], op: 'move', from: 0, to: 2 }]);
  check('move to the end: the reference is null', rec.lines, ['insert <li> into <ul> at the end']);
  check('move to the end: the order is the new order', serialize(ul), '<ul><li>b</li><li>c</li><li>a</li></ul>');
  check('move to the end: the same element made the trip', ul.childNodes[2] === moving, true);
}

// ---- the ops apply in the order `diff` emitted them ------------------------
{
  // A removal at 3 and a removal at 1, highest first, which is the order the
  // reconciler emits and the reason it emits that order: applied the other way
  // round the second index names a different child.
  const { host, ul } = mounted(['a', 'b', 'c', 'd']);
  host.apply([
    { path: [], op: 'remove', at: 3 },
    { path: [], op: 'remove', at: 1 },
  ]);
  check('descending removals leave the right rows', serialize(ul), '<ul><li>a</li><li>c</li></ul>');
}

// ---- the table is the contract --------------------------------------------
{
  const { host } = mounted(['a']);
  let threw = '';
  try {
    host.apply([{ path: [], op: 'reorder' }]);
  } catch (e) {
    threw = e.message;
  }
  check('an op the table does not have is named, not ignored', threw, 'unknown patch op `reorder`');
}

if (failures !== 0) {
  console.log(`FAIL: ${failures} assertion(s)`);
  process.exit(1);
}
console.log('tea-dom keyed ops ok');
