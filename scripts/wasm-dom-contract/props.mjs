// The attribute/property split at the bridge, with no wasm and no browser.
//
// Why this exists separately from the two transcripts. A prop is a pair of
// strings in the tree and reaches the element as an attribute -- except for
// `value` and `checked`, where a browser keeps a live value beside the content
// attribute and stops writing the attribute through the moment the user has
// touched the control (WHATWG HTML's dirty value flag). A bridge that misses
// that renders a model into a field exactly once and then silently loses the
// ability to correct it, and no exception, no patch and no ordering assertion
// can see it: the patch stream is right, the document object is right, and the
// only thing that is wrong is what the user is looking at.
//
// So this drives `setSelf` straight at a stub that has the flag, in the four
// situations where the two spellings differ:
//
//   1. a fresh field gets the model's text
//   2. a field the user has typed into still tracks the model afterwards --
//      this is the whole bug, and the only case the attribute spelling fails
//   3. `checked` is a boolean the tree spells as a string
//   4. a prop that leaves the list leaves the element, property half included
//
// Plus the control that says the split is a split and not a rewrite: every
// other prop still travels as an attribute.
//
// Run it through props.sh, which adds the mutant; run.sh calls that.

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

function elem(tag, props) {
  return { t: 'elem', tag, props, on: [], kids: [] };
}

// One element under a host, with the build noise dropped so that what a case
// records is only what its own `set-self` did.
function mounted(node) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const host = new DomHost(doc.mountPoint(), () => {}, doc);
  host.apply([{ path: [], op: 'replace', node }]);
  const built = rec.lines.slice();
  rec.lines.length = 0;
  return { host, rec, el: host.root, built };
}

// ---- 1. a fresh field carries the model's text ----------------------------
{
  const { el, built } = mounted(elem('input', [['class', 'field'], ['value', 'buy milk']]));
  check('a fresh input shows the model', el.value, 'buy milk');
  check('the class travelled as an attribute, the value as a property', built, [
    'create <input>',
    'attr <input> class="field"',
    'prop <input> value="buy milk"',
    'append <input> to <main>',
  ]);
}

// ---- 2. the dirty value flag, which is the bug -----------------------------
{
  const { host, rec, el } = mounted(elem('input', [['value', 'buy']]));
  // The user types. From here a browser ignores the content attribute.
  el.type('buy milk and eggs');
  check('the user typed', el.value, 'buy milk and eggs');

  // The model corrects the field: an add committed the draft and cleared it.
  host.apply([{ path: [], op: 'set-self', node: elem('input', [['value', '']]) }]);
  check('a cleared model clears the field', el.value, '');
  check('and it took one mutation', rec.lines, ['prop <input> value=""']);

  // And the model can still write into it afterwards.
  host.apply([{ path: [], op: 'set-self', node: elem('input', [['value', 'ship tea']]) }]);
  check('the model still owns the field after the user typed', el.value, 'ship tea');
}

// ---- 3. checked, which the tree spells as a string -------------------------
{
  const { host, el } = mounted(elem('input', [['type', 'checkbox'], ['checked', 'true']]));
  check('a checked box is checked', el.checked, true);
  el.check(false); // the user unticks it
  host.apply([
    { path: [], op: 'set-self', node: elem('input', [['type', 'checkbox'], ['checked', 'true']]) },
  ]);
  check('the model can re-tick a box the user unticked', el.checked, true);
  host.apply([
    { path: [], op: 'set-self', node: elem('input', [['type', 'checkbox'], ['checked', 'false']]) },
  ]);
  check('"false" is not a present attribute, it is unchecked', el.checked, false);
}

// ---- 4. a prop that leaves the list leaves the element ---------------------
{
  const { host, el } = mounted(elem('input', [['class', 'field'], ['value', 'draft']]));
  host.apply([{ path: [], op: 'set-self', node: elem('input', [['class', 'field']]) }]);
  check('a dropped value prop empties the field', el.value, '');
  check('and the attribute half still works', serialize(el), '<input class="field" value=""></input>');
}

{
  // The reset must not invent a property on an element that has none: a
  // `<div>` answers `'value' in el` false, and a bridge that assigned anyway
  // would leave an expando behind on every element in the document.
  const { el } = mounted(elem('div', [['class', 'row']]));
  check('a div is given no value property', Object.hasOwn(el, 'value'), false);
}

// ---- the control: everything else is still an attribute --------------------
{
  const { rec, host, el } = mounted(elem('div', [['class', 'a']]));
  host.apply([{ path: [], op: 'set-self', node: elem('div', [['class', 'b'], ['id', 'x']]) }]);
  check('ordinary props travel as attributes', rec.lines, [
    'attr <div> class="b"',
    'attr <div> id="x"',
  ]);
  check('and the document says so', serialize(el), '<div class="b" id="x"></div>');
}

if (failures !== 0) {
  console.log(`FAIL: ${failures} assertion(s)`);
  process.exit(1);
}
console.log('tea-dom props ok');
