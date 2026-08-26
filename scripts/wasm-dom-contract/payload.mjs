// The host half of an event payload, at the bridge, with no wasm and no
// browser.
//
// Why this exists separately from the two transcripts. A listener declares a
// kind and the bridge decides three things from it: what to read off the
// event, whether to cancel the event, and whether a listener already attached
// is still the right one. Neither demo application reaches most of that:
// `tea_dom_counter` declares no payload at all, `tea_dom_todo` declares
// `value` on two `<input>`s and nothing else, so `key`, a checkbox, a
// listener whose kind changed and the `preventDefault` decision are all
// unreachable from a transcript. This is the same argument keyed-ops.mjs
// makes about `insert`/`remove`/`move`.
//
// What it asserts, and why each needs saying:
//
//   1. a listener that asked for nothing dispatches no payload at all --
//      absent, not empty, because the guest refuses a turn that carries one
//   2. `value` reads the target's value, and a checkbox or a radio is folded
//      into the same slot as `"true"`/`"false"`
//   3. `key` reads `ev.key`, and does *not* cancel the event: cancelling a
//      keydown is how a page swallows the character
//   4. a listener whose kind changed is reattached, or the handler goes on
//      reading what the old kind said
//
// Run it through payload.sh, which adds the mutants; run.sh calls that.

import { DomHost } from '../../packages/tea-dom/js/dom.mjs';
import { Reactor } from '../../packages/tea-dom/js/reactor.mjs';
import { Recorder, StubDocument } from './domstub.mjs';

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

function elem(tag, props, on) {
  return { t: 'elem', tag, props, on, kids: [] };
}

// One element under a host that records every dispatch as `[path, event,
// payload]`. `payload` is left in whatever state the bridge passed it, so an
// omitted one shows up as a missing array element rather than as a null.
function mounted(node) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const sent = [];
  const host = new DomHost(
    doc.mountPoint(),
    (...args) => sent.push(args),
    doc,
  );
  host.apply([{ path: [], op: 'replace', node }]);
  rec.lines.length = 0;
  return { host, rec, el: host.root, sent };
}

// One request line, without a wasm module: `Reactor.event` is the only thing
// between a dispatch and the bytes, and what it does with an absent payload is
// the half of the contract `DomHost` cannot show.
function requestFor(path, event, payload) {
  // A real instance with no module behind it: the constructor only records
  // its two arguments, and `event` is being held to what it puts on the line
  // rather than to anything a guest would answer.
  const reactor = new Reactor(null, null);
  reactor.model = 'M';
  let seen = null;
  reactor.request = (req) => {
    seen = req;
    return { ok: false, kind: 'stub', error: '' };
  };
  reactor.event(path, event, payload);
  return seen;
}

// ---- 1. no kind, no payload ----------------------------------------------
{
  const { el, sent } = mounted(elem('button', [], ['click']));
  el.fire('click');
  check('a listener that asked for nothing dispatches no payload', sent, [[[], 'click', null]]);
  check('and the payload really is undefined, not a null', sent[0][2] === undefined, true);
  // The line that carries it has no `payload` field at all. Absent and empty
  // are different answers here: the guest refuses a turn whose payload does
  // not match what its listener declared, so `""` would be an error reply.
  //
  // The key list and not the object: `JSON.stringify` drops a key whose value
  // is `undefined`, so an object comparison here would report a request that
  // does carry the field as one that does not.
  check('so the request line omits the field', Object.keys(requestFor([], 'click', undefined)), [
    'op',
    'model',
    'path',
    'event',
  ]);
  check('and an empty payload is carried rather than dropped', requestFor([1], 'input', ''), {
    op: 'event',
    model: 'M',
    path: [1],
    event: 'input',
    payload: '',
  });
}

// ---- 2. value, and the slot a checkbox folds into -------------------------
{
  const { el, sent } = mounted(elem('input', [['value', 'buy']], [['input', 'value']]));
  el.typeInto('buy milk');
  el.fire('input');
  check('value reads what the element now holds', sent, [[[], 'input', 'buy milk']]);
}

{
  // The event's target and not the element the listener sits on, which is
  // what makes a listener on a container work.
  const { el, sent } = mounted(elem('input', [], [['input', 'value']]));
  el.fire('input', { target: { value: 'from the target' } });
  check('value reads the event target', sent, [[[], 'input', 'from the target']]);
}

{
  const { el, sent } = mounted(elem('input', [['type', 'checkbox']], [['change', 'value']]));
  el.check(true);
  el.fire('change');
  check('a ticked checkbox is "true" in the value slot', sent, [[[], 'change', 'true']]);
  el.check(false);
  el.fire('change');
  check('and an unticked one is "false", not an absent payload', sent[1], [[], 'change', 'false']);
}

{
  // A radio is the same fold, and an element with no value at all is the
  // empty string rather than `undefined` reaching the wire as `null`.
  const { el, sent } = mounted(elem('div', [], [['click', 'value']]));
  el.fire('click');
  check('an element with no value sends the empty string', sent, [[[], 'click', '']]);
}

// ---- 3. key, and the event that must not be cancelled ---------------------
{
  const { el, sent } = mounted(elem('input', [], [['keydown', 'key']]));
  let cancelled = false;
  el.fire('keydown', { key: 'a', preventDefault: () => { cancelled = true; } });
  check('key reads ev.key', sent, [[[], 'keydown', 'a']]);
  check('and the keystroke is not swallowed', cancelled, false);
}

{
  // Every other kind is cancelled, which is what the bridge did before there
  // were kinds at all.
  const { el } = mounted(elem('button', [], ['click']));
  let cancelled = false;
  el.fire('click', { preventDefault: () => { cancelled = true; } });
  check('a plain listener still cancels its event', cancelled, true);
}

{
  const { el } = mounted(elem('input', [], [['input', 'value']]));
  let cancelled = false;
  el.fire('input', { preventDefault: () => { cancelled = true; } });
  check('so does a value listener', cancelled, true);
}

// ---- 4. a listener whose kind changed is reattached ------------------------
{
  const { host, rec, el, sent } = mounted(elem('input', [], [['input', 'value']]));
  host.apply([{ path: [], op: 'set-self', node: elem('input', [], [['input', 'key']]) }]);
  check('the old handler goes and a new one arrives', rec.lines, [
    'unlisten <input> input',
    'listen <input> input',
  ]);
  el.typeInto('typed');
  el.fire('input', { key: 'x' });
  check('and it reads what the new kind says', sent, [[[], 'input', 'x']]);
}

{
  // The control: an unchanged listener is left alone, or every frame would
  // detach and reattach every handler in the document.
  const { host, rec } = mounted(elem('input', [], [['input', 'value']]));
  host.apply([
    { path: [], op: 'set-self', node: elem('input', [['class', 'x']], [['input', 'value']]) },
  ]);
  check('an unchanged listener is not touched', rec.lines, ['attr <input> class="x"']);
}

if (failures !== 0) {
  console.log(`FAIL: ${failures} assertion(s)`);
  process.exit(1);
}
console.log('tea-dom payloads ok');
