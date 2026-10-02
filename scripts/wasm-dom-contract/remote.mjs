// The worker host (`remote.mjs` and `worker.mjs`), at the bridge, with no
// browser.
//
// Why this exists separately from the transcripts. Every transcript drives
// `app.mjs`, where a turn is finished before the event that caused it
// returns, so nothing in them can be out of order, stale or rolled back. The
// worker host is where all three become possible, and each is a bug that
// raises nothing: a turn sent with the address an element had before the
// previous turn's patches moved it dispatches the wrong message; a turn for
// an element the previous patches removed names a node in a tree that no
// longer exists; a reply that lands while the reader is still typing puts the
// field back to what it was a keystroke ago. The guest here is a script of
// replies, because what is under test is what the page side does with them
// and when, not what a guest would compute.
//
// What it asserts:
//
//   1. one turn at a time: a second event waits until the first reply is in
//      the document
//   2. a queued event's address is recovered when it is sent, not when it
//      fired
//   3. a queued event whose element has left the document is dropped
//   4. while turns are queued, a reply does not roll the focused field back
//   5. `init` queues behind a turn in flight and resolves once applied
//   6. an error reply leaves the document alone and the next turn goes on
//   7. a worker that fails rejects the turn waiting on it and every later one
//   8. the worker side handles its messages in arrival order: a turn sent
//      right behind `load` waits for the module
//   9. `idle()` waits for every turn already asked for, so a page can ask
//      "is the panel still open" of the document a synchronous host would
//      have by then
//
// Run it through remote.sh, which adds the mutants; run.sh calls that.

import { Remote } from '../../packages/tea-dom/js/remote.mjs';
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

// The three things a browser element has and the recording stub does not
// model, because nothing synchronous ever asked: whether it is in the
// document, whether a node is inside it, and a selection.
Object.defineProperty(StubElement.prototype, 'isConnected', {
  get() {
    return this._connected;
  },
});
StubElement.prototype.contains = function (node) {
  for (let n = node; n; n = n.parentNode) if (n === this) return true;
  return false;
};
StubElement.prototype.setSelectionRange = function (start, end) {
  this.selectionStart = start;
  this.selectionEnd = end;
};

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// A worker whose replies are held until the case releases them: `answer` is
// the scripted guest, `sent` is every request in the order it was posted, and
// `deliver()` lets the oldest held reply through.
class FakeWorker {
  constructor(answer) {
    this.answer = answer;
    this.sent = [];
    this.held = [];
  }

  postMessage(msg) {
    this.sent.push(msg);
    const { id, ...req } = msg;
    this.held.push({ id, reply: req.op === 'load' ? { ok: true } : this.answer(req) });
  }

  async deliver() {
    const next = this.held.shift();
    if (!next) throw new Error('nothing to deliver');
    this.onmessage({ data: next });
    await settle();
  }

  turns() {
    return this.sent.filter((m) => m.op !== 'load').map(({ id, ...req }) => req);
  }
}

const elem = (tag, props, on, kids = []) => ({ t: 'elem', tag, props, on, kids });
const text = (s) => ({ t: 'text', s });
const item = (s) => elem('li', [], ['click'], [text(s)]);

async function mounted(tree, answer) {
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const worker = new FakeWorker((req) =>
    req.op === 'init' ? { ok: true, patches: [{ path: [], op: 'replace', node: tree }] } : answer(req),
  );
  const errors = [];
  const turns = [];
  const remote = new Remote(worker);
  const loading = remote.load(new ArrayBuffer(8));
  await settle();
  await worker.deliver();
  await loading;
  const mount = doc.mountPoint();
  const done = remote.mount(mount, {
    doc,
    onError: (reply) => errors.push(reply.kind),
    onTurn: () => turns.push(worker.turns().length),
  });
  await settle();
  await worker.deliver();
  const app = await done;
  return { app, doc, worker, errors, turns, root: app.host.root };
}

// 1 and 2: a click on `b` inserts `z` at the front, so the second click on
// `b`, fired before the first was answered, has to say [0,2] and not [0,1].
{
  const tree = elem('div', [], [], [elem('ul', [], [], [item('a'), item('b')])]);
  const m = await mounted(tree, () => ({ ok: true, patches: [{ path: [0], op: 'insert', at: 0, node: item('z') }] }));
  const b = m.root.childNodes[0].childNodes[1];
  b.fire('click');
  b.fire('click');
  await settle();
  check('a second event waits for the first reply', m.worker.turns().length, 2);
  await m.worker.deliver();
  check('then it is sent, at the address its element has now',
    m.worker.turns().slice(1).map((r) => [r.op, r.path, r.event]),
    [['event', [0, 1], 'click'], ['event', [0, 2], 'click']]);
  check('onTurn runs once a reply is applied, before the next turn is sent', m.turns, [1, 2]);
}

// 3: a click removes the item; the second click on it, queued behind the
// first, has nothing left to say.
{
  const tree = elem('div', [], [], [elem('ul', [], [], [item('a'), item('b')])]);
  const m = await mounted(tree, (req) => ({ ok: true, patches: [{ path: [0], op: 'remove', at: req.path[1] }] }));
  const a = m.root.childNodes[0].childNodes[0];
  a.fire('click');
  a.fire('click');
  await settle();
  await m.worker.deliver();
  check('an event whose element left the document is dropped',
    m.worker.turns().slice(1).map((r) => r.path), [[0, 0]]);
}

// 4: the reader types `h`, then `he` before `h` is answered. The answer to
// `h` sets the field to `h`; the field has to stay `he`, with its caret.
{
  const field = () => elem('input', [['value', '']], [['input', 'value']]);
  const tree = elem('div', [], [], [field()]);
  const m = await mounted(tree, (req) => ({
    ok: true,
    patches: [{ path: [0], op: 'set-self', node: { t: 'elem', tag: 'input', props: [['value', req.payload]], on: [['input', 'value']] } }],
  }));
  const input = m.root.childNodes[0];
  m.doc.activeElement = input;
  input.typeInto('h');
  input.fire('input');
  input.typeInto('he');
  input.setSelectionRange(2, 2);
  input.fire('input');
  await settle();
  await m.worker.deliver();
  check('a reply does not roll the focused field back while a turn is queued',
    [input.value, input.selectionStart], ['he', 2]);
  check('and the queued turn carries what the field holds',
    m.worker.turns().slice(1).map((r) => r.payload), ['h', 'he']);
  await m.worker.deliver();
  check('the last reply is applied as it is', input.value, 'he');
}

// 5: init behind a turn in flight.
{
  const tree = elem('div', [], [], [elem('ul', [], [], [item('a')])]);
  const m = await mounted(tree, () => ({ ok: true, patches: [] }));
  m.root.childNodes[0].childNodes[0].fire('click');
  let resolved = false;
  const again = m.app.init('{"q":"x"}').then((reply) => {
    resolved = true;
    return reply;
  });
  await settle();
  check('init waits behind the turn in flight', m.worker.turns().map((r) => r.op), ['init', 'event']);
  await m.worker.deliver();
  check('and is sent after it, with its flags',
    m.worker.turns().slice(2).map((r) => [r.op, r.flags]), [['init', '{"q":"x"}']]);
  check('it has not resolved before its reply', resolved, false);
  await m.worker.deliver();
  await again;
  check('it resolves once applied', [resolved, m.app.host.root !== m.root], [true, true]);
}

// 9: idle.
{
  const tree = elem('div', [], [], [elem('ul', [], [], [item('a')])]);
  const m = await mounted(tree, () => ({ ok: true, patches: [] }));
  let done = false;
  await m.app.idle();
  m.root.childNodes[0].childNodes[0].fire('click');
  m.root.childNodes[0].childNodes[0].fire('click');
  const waited = m.app.idle().then(() => {
    done = true;
  });
  await settle();
  await m.worker.deliver();
  check('idle waits while a turn is still queued', done, false);
  await m.worker.deliver();
  await waited;
  check('and resolves once the last one is applied', done, true);
}

// 6: an error reply.
{
  const tree = elem('div', [], [], [elem('ul', [], [], [item('a')])]);
  let n = 0;
  const m = await mounted(tree, () =>
    n++ === 0 ? { ok: false, kind: 'panic', error: 'boom' } : { ok: true, patches: [{ path: [0, 0, 0], op: 'replace', node: text('A') }] },
  );
  const a = m.root.childNodes[0].childNodes[0];
  a.fire('click');
  await settle();
  await m.worker.deliver();
  check('an error reply reaches onError and leaves the document alone', [m.errors, a.childNodes[0].nodeValue], [['panic'], 'a']);
  a.fire('click');
  await settle();
  await m.worker.deliver();
  check('and the next turn goes on', a.childNodes[0].nodeValue, 'A');
}

// 7: the worker fails.
{
  const worker = new FakeWorker(() => ({ ok: true, patches: [] }));
  const remote = new Remote(worker);
  const waiting = remote.load(new ArrayBuffer(8));
  await settle();
  worker.onerror({ message: 'gone' });
  const outcome = (p) =>
    Promise.race([
      p.then(() => 'resolved', (e) => `rejected: ${e.message}`),
      new Promise((resolve) => setTimeout(() => resolve('still waiting'), 50)),
    ]);
  check('a failed worker rejects the call waiting on it', await outcome(waiting), "rejected: the reactor's worker failed: gone");
  check('and every later call', await outcome(remote.call({ op: 'init' })), "rejected: the reactor's worker failed: gone");
}

// 8: worker.mjs itself, on a module with nothing in it: `_initialize` and
// `dawn_turn` that do nothing, and a memory. A turn against it answers no
// line, which the reactor reports as thrown; a turn that ran before the load
// had finished would report that instead.
{
  const bytes = new Uint8Array([
    0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00,
    0x01, 0x04, 0x01, 0x60, 0x00, 0x00,
    0x03, 0x03, 0x02, 0x00, 0x00,
    0x05, 0x03, 0x01, 0x00, 0x01,
    0x07, 0x24, 0x03,
    0x06, ...Buffer.from('memory'), 0x02, 0x00,
    0x0b, ...Buffer.from('_initialize'), 0x00, 0x00,
    0x09, ...Buffer.from('dawn_turn'), 0x00, 0x01,
    0x0a, 0x07, 0x02, 0x02, 0x00, 0x0b, 0x02, 0x00, 0x0b,
  ]);
  const out = [];
  globalThis.self = { postMessage: (m) => out.push(m) };
  await import('../../packages/tea-dom/js/worker.mjs');
  self.onmessage({ data: { id: 0, op: 'load', wasm: bytes.buffer } });
  self.onmessage({ data: { id: 1, op: 'init' } });
  for (let i = 0; i < 20 && out.length < 2; i++) await settle();
  check('the worker answers in order, a turn after the load it followed', out, [
    { id: 0, reply: { ok: true } },
    { id: 1, thrown: 'the guest answered 0 lines, expected 1: ' },
  ]);
}

if (failures > 0) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
