// Foreign elements at the bridge: the custom-element boundary, with no wasm
// and no browser.
//
// A foreign element is a custom element the page registered; third-party
// JavaScript owns everything inside it, and the guest describes only its
// attributes and listeners (`dsl.foreign`, and the "Third-party mounts"
// section of packages/tea-dom/README.md). Neither demo application mounts
// one, so nothing about the boundary is reachable from the transcripts; this
// feeds the bridge the patch lists such an application would produce, against
// a document stub whose custom element registry dispatches
// `connectedCallback`/`disconnectedCallback` in tree order, and asserts on
// what fired and on what the library's private DOM then was.
//
// What it asserts, and why each needs saying:
//
//   1. mounting the element fires connected exactly once, and a child the
//      library builds during its own connect fires after its parent --
//      lifecycle is the browser's, so the bridge must reach it through real
//      DOM insertion and nothing else
//   2. `set-self` reaches the element as attributes and touches nothing
//      else: no lifecycle fires, and the library's private children are the
//      same objects afterwards -- the "attributes in" half of the boundary
//   3. patches aimed at siblings never touch the inside -- the reason
//      `foreign` has no kids parameter is that an empty guest-side list
//      keeps every address out of the element
//   4. `remove`, `truncate` and `replace` each fire disconnected, parent
//      before child -- the cleanup notification a library's editor instance,
//      observers and workers hang off, and the thing a bridge that edits
//      structure behind the DOM's back would lose
//   5. `move` keeps the object and crosses the lifecycle: disconnected then
//      connected, which is what `insertBefore` does to a connected custom
//      element and what a widget must be written to survive
//   6. an event the element dispatches on itself comes out with the right
//      recovered address and the value the element chose to expose -- the
//      "events out" half of the boundary
//
// Run it through foreign.sh, which adds the mutants; run.sh calls that.

import { DomHost } from '../../packages/tea-dom/js/dom.mjs';
import { Recorder, StubDocument, StubElement } from './domstub.mjs';

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

// The widget, as a library would write it: private DOM built on connect
// (guarded, because a move disconnects and reconnects and a rebuild would
// duplicate it), state kept inside the element, a `value` the guest's
// `Value` listener reads, and not one attribute written onto its own tag.
function defineWidgets(doc) {
  class XInner extends StubElement {
    connectedCallback() {}

    disconnectedCallback() {}
  }
  class XWidget extends StubElement {
    connectedCallback() {
      if (this._built) return;
      this._built = true;
      this.appendChild(this.doc.createElement('x-inner'));
      this.appendChild(this.doc.createTextNode('library text'));
    }

    disconnectedCallback() {}

    get value() {
      return `${this.getAttribute('doc')}!`;
    }
  }
  doc.customElements.define('x-inner', XInner);
  doc.customElements.define('x-widget', XWidget);
}

function widget() {
  return { t: 'elem', tag: 'x-widget', props: [['doc', 'v1']], on: [['change', 'value']], kids: [] };
}

function p(label) {
  return { t: 'elem', tag: 'p', props: [], on: [], kids: [{ t: 'text', s: label }] };
}

// A `<div>` holding the widget first and `extra` after it, mounted under a
// connected mount point. The recorder keeps the mount lines, since the first
// case is about them; later cases clear it.
function mounted(extra = []) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  defineWidgets(doc);
  const dispatched = [];
  const host = new DomHost(
    doc.mountPoint(),
    (path, event, payload) => dispatched.push({ path, event, payload }),
    doc,
  );
  host.apply([
    { path: [], op: 'replace', node: { t: 'elem', tag: 'div', props: [], on: [], kids: [widget(), ...extra] } },
  ]);
  const div = host.root;
  return { host, rec, doc, div, w: div.childNodes[0], dispatched };
}

const lifecycle = (rec) => rec.lines.filter((l) => l.startsWith('connected') || l.startsWith('disconnected'));

// ---- 1. mount: connected once, parent before the library's child ----------
{
  const { rec, w } = mounted();
  check('mount: connect fires once each, parent first', lifecycle(rec), [
    'connected <x-widget>',
    'connected <x-inner>',
  ]);
  check(
    'mount: the library DOM is inside the element',
    w.childNodes.map((n) => n.nodeName),
    ['x-inner', '#text'],
  );
  check('mount: the declared attribute is on the element', w.getAttribute('doc'), 'v1');
}

// ---- 2. set-self: attributes in, nothing else touched ---------------------
{
  const { host, rec, w } = mounted();
  const inside = [...w.childNodes];
  rec.lines.length = 0;
  host.apply([
    { path: [0], op: 'set-self', node: { t: 'elem', tag: 'x-widget', props: [['doc', 'v2']], on: [['change', 'value']] } },
  ]);
  check('set-self: the new attribute value arrives', w.getAttribute('doc'), 'v2');
  check('set-self: no lifecycle fires for an in-place update', lifecycle(rec), []);
  check(
    'set-self: the library DOM is the same objects',
    w.childNodes.map((n, i) => n === inside[i]),
    [true, true],
  );
}

// ---- 2b. `value` on a foreign element is the library's, not the bridge's --
{
  // On a form control `value` travels as a live property (props.mjs is that
  // contract); on anything else it is an attribute like every other prop.
  // The distinction is load-bearing here: the widget's `value` property is
  // how it answers a `Value` listener, it is getter-only, and a bridge that
  // wrote or reset it would clobber library state or throw.
  const { host, w } = mounted();
  host.apply([
    {
      path: [0],
      op: 'set-self',
      node: { t: 'elem', tag: 'x-widget', props: [['doc', 'v1'], ['value', 'from-guest']], on: [['change', 'value']] },
    },
  ]);
  check('value prop: reaches a foreign element as an attribute', w.getAttribute('value'), 'from-guest');
  check('value prop: the library-owned property is untouched', w.value, 'v1!');
  host.apply([
    { path: [0], op: 'set-self', node: { t: 'elem', tag: 'x-widget', props: [['doc', 'v1']], on: [['change', 'value']] } },
  ]);
  check(
    'value prop: undeclared sweeps the attribute and never the property',
    [w.getAttribute('value'), w.value],
    [null, 'v1!'],
  );
}

// ---- 3. sibling churn never reaches the inside ----------------------------
{
  const { host, rec, w, div } = mounted([p('one')]);
  const inside = [...w.childNodes];
  rec.lines.length = 0;
  host.apply([
    { path: [], op: 'append', nodes: [p('two')] },
    { path: [1, 0], op: 'replace', node: { t: 'text', s: 'edited' } },
    { path: [], op: 'insert', at: 0, node: p('zero') },
  ]);
  check('siblings: the guest tree around the widget moved on', div.childNodes.length, 4);
  check(
    'siblings: the library DOM is untouched by any of it',
    w.childNodes.map((n, i) => n === inside[i]),
    [true, true],
  );
  check('siblings: the widget itself never crossed the lifecycle', lifecycle(rec), []);
}

// ---- 4. remove / truncate / replace all reach disconnected ----------------
{
  const { host, rec } = mounted();
  rec.lines.length = 0;
  host.apply([{ path: [], op: 'remove', at: 0 }]);
  check('remove: disconnect fires once each, parent first', lifecycle(rec), [
    'disconnected <x-widget>',
    'disconnected <x-inner>',
  ]);
}

{
  const { host, rec } = mounted();
  rec.lines.length = 0;
  host.apply([{ path: [], op: 'truncate', keep: 0 }]);
  check('truncate: disconnect fires, parent first', lifecycle(rec), [
    'disconnected <x-widget>',
    'disconnected <x-inner>',
  ]);
}

{
  const { host, rec, div } = mounted();
  rec.lines.length = 0;
  host.apply([{ path: [0], op: 'replace', node: p('plain') }]);
  check('replace: the old widget disconnects, and its plain successor has no lifecycle', lifecycle(rec), [
    'disconnected <x-widget>',
    'disconnected <x-inner>',
  ]);
  check('replace: the slot now holds the plain element', div.childNodes[0].nodeName, 'p');
}

// ---- 5. move keeps the object and crosses the lifecycle -------------------
{
  const { host, rec, w, div } = mounted([p('one'), p('two')]);
  rec.lines.length = 0;
  host.apply([{ path: [], op: 'move', from: 0, to: 2 }]);
  check('move: the element in the new slot is the same object', div.childNodes[2] === w, true);
  check('move: it disconnected and reconnected, in that order', lifecycle(rec), [
    'disconnected <x-widget>',
    'disconnected <x-inner>',
    'connected <x-widget>',
    'connected <x-inner>',
  ]);
  check(
    'move: the guarded build did not duplicate the library DOM',
    w.childNodes.map((n) => n.nodeName),
    ['x-inner', '#text'],
  );
}

// ---- 6. an event out: recovered address, exposed value --------------------
{
  const { host, w, dispatched } = mounted([p('one')]);
  host.apply([
    { path: [0], op: 'set-self', node: { t: 'elem', tag: 'x-widget', props: [['doc', 'v3']], on: [['change', 'value']] } },
  ]);
  w.fire('change');
  check('event: one dispatch, at the widget address, with its exposed value', dispatched, [
    { path: [0], event: 'change', payload: 'v3!' },
  ]);
}

if (failures !== 0) {
  console.log(`FAIL: ${failures} assertion(s)`);
  process.exit(1);
}
console.log('tea-dom foreign elements ok');
