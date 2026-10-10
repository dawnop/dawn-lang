// The host half of a `Fetch` command, at the bridge, with no wasm and no
// browser.
//
// Why this exists separately from the transcripts. A fetch is the one thing a
// guest asks for that it cannot do and cannot wait for, so everything that
// matters happens on the host's side of the wire, in places no transcript of
// the counter or the todo list ever reaches: the request the host builds from
// the outcome, what a failed network call is turned into, the order in which
// the worker reports and the page applies, and whether a result that arrives
// while the reader's own event is in flight jumps ahead of it. Each of those
// is wrong without raising anything: a failure that rejects instead of
// answering leaves the guest waiting for a reply that will never come; a
// supply sent the moment it arrives is addressed against a document the
// in-flight event is about to change.
//
// What it asserts:
//
//   1. `runFetch` answers a 2xx as `{ok, body}`, a non-2xx as an error value
//      naming the status, and a thrown network error or unreadable body as an
//      error value too; it never rejects
//   2. `Reactor.supply` writes the `supply` line the guest's wire reads, for
//      both outcomes, against the model it holds
//   3. `worker.mjs` posts a reply before the fetches it names, reports each
//      outcome as `{fetched: {tag, outcome}}` and does not feed it to the
//      reactor itself, and a `supply` message reaches `Reactor.supply`
//   4. `Remote` queues a finished fetch as a turn behind an event already in
//      flight, and applies the supply's patches
//   5. `mount` of `app.mjs` supplies the guest after a reply that asked
//
// Run it through fetch.sh, which adds the mutants; run.sh calls that.

import { Reactor, runFetch } from '../../packages/tea-dom/js/reactor.mjs';
import { Remote } from '../../packages/tea-dom/js/remote.mjs';
import { mount } from '../../packages/tea-dom/js/app.mjs';
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

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

// ---- 1. runFetch ------------------------------------------------------------
{
  const reply = (status, body) => ({
    ok: status >= 200 && status < 300,
    status,
    text: async () => body,
  });
  check('a 2xx is its text', await runFetch('/a', async () => reply(200, 'hello')), { ok: true, body: 'hello' });
  check('an empty 2xx body is an empty string, not a failure',
    await runFetch('/a', async () => reply(204, '')), { ok: true, body: '' });
  check('a 404 is an error value naming the status',
    await runFetch('/a', async () => reply(404, 'nope')), { ok: false, error: 'HTTP 404' });
  check('a 500 likewise', await runFetch('/a', async () => reply(500, '')), { ok: false, error: 'HTTP 500' });
  check('a network failure is an error value, not a rejection',
    await runFetch('/a', async () => { throw new TypeError('Failed to fetch'); }),
    { ok: false, error: 'Failed to fetch' });
  check('a body that cannot be read is an error value',
    await runFetch('/a', async () => ({ ok: true, status: 200, text: async () => { throw new Error('aborted'); } })),
    { ok: false, error: 'aborted' });
  let asked = null;
  await runFetch('/some/url.json', async (u) => { asked = u; return reply(200, ''); });
  check('the url goes through untouched', asked, '/some/url.json');
  const seen = [];
  const saved = globalThis.fetch;
  globalThis.fetch = async (u) => { seen.push(u); return reply(200, 'g'); };
  check('with no implementation given it reads globalThis.fetch when called',
    await runFetch('/g'), { ok: true, body: 'g' });
  globalThis.fetch = saved;
  check('and that is the url it was asked for', seen, ['/g']);
}

// ---- 2. Reactor.supply --------------------------------------------------------
{
  const lines = [];
  const reactor = new Reactor(null, null);
  reactor.model = 'M0';
  reactor.request = (req) => {
    lines.push(req);
    return { ok: true, model: 'M1', patches: [] };
  };
  reactor.supply('data', { ok: true, body: '{"a":1}' });
  check('a success is written with its body, against the held model', lines[0],
    { op: 'supply', model: 'M0', tag: 'data', ok: true, body: '{"a":1}' });
  check('and the reply\'s model becomes the held one', reactor.model, 'M1');
  reactor.supply('data', { ok: false, error: 'HTTP 404' });
  check('a failure is written with its error and no body', lines[1],
    { op: 'supply', model: 'M1', tag: 'data', ok: false, error: 'HTTP 404' });
}

// ---- 3. worker.mjs --------------------------------------------------------------
{
  const out = [];
  globalThis.self = { postMessage: (m) => out.push(m) };
  const supplied = [];
  const fake = {
    init: () => ({ ok: true, model: 'M', patches: [] }),
    event: () => ({
      ok: true, model: 'M', patches: [],
      fetch: [{ url: '/good', tag: 'g' }, { url: '/bad', tag: 'b' }],
    }),
    supply: (tag, outcome) => {
      supplied.push([tag, outcome]);
      return { ok: true, model: 'M2', patches: [] };
    },
  };
  Reactor.load = async () => fake;
  const saved = globalThis.fetch;
  globalThis.fetch = async (u) =>
    u === '/good'
      ? { ok: true, status: 200, text: async () => 'yes' }
      : { ok: false, status: 503, text: async () => '' };
  await import('../../packages/tea-dom/js/worker.mjs');
  self.onmessage({ data: { id: 0, op: 'load', wasm: new ArrayBuffer(0) } });
  self.onmessage({ data: { id: 1, op: 'event', path: [], event: 'click' } });
  for (let i = 0; i < 20 && out.length < 4; i++) await settle();
  // Outcomes are posted as they finish, so only the reply's place is fixed.
  const byTag = (a, b) => (a.fetched.tag < b.fetched.tag ? -1 : 1);
  check('the reply is posted first, then each fetch\'s outcome as a value',
    [out[1], ...out.slice(2).sort(byTag)], [
    { id: 1, reply: { ok: true, model: 'M', patches: [], fetch: [{ url: '/good', tag: 'g' }, { url: '/bad', tag: 'b' }] } },
    { fetched: { tag: 'b', outcome: { ok: false, error: 'HTTP 503' } } },
    { fetched: { tag: 'g', outcome: { ok: true, body: 'yes' } } },
  ]);
  check('the worker does not feed an outcome to the reactor itself', supplied, []);
  out.length = 0;
  self.onmessage({ data: { id: 2, op: 'supply', tag: 'g', outcome: { ok: true, body: 'yes' } } });
  for (let i = 0; i < 20 && out.length < 1; i++) await settle();
  check('a supply message is a turn of the reactor', [supplied, out], [
    [['g', { ok: true, body: 'yes' }]],
    [{ id: 2, reply: { ok: true, model: 'M2', patches: [] } }],
  ]);
  globalThis.fetch = saved;
}

// ---- 4. Remote --------------------------------------------------------------------
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

{
  const tree = elem('div', [], [], [elem('button', [], ['click'], [text('go')]), elem('p', [], [], [text('idle')])]);
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const worker = new FakeWorker((req) => {
    if (req.op === 'init') return { ok: true, patches: [{ path: [], op: 'replace', node: tree }] };
    if (req.op === 'event') return { ok: true, patches: [{ path: [1, 0], op: 'replace', node: text('loading') }], fetch: [{ url: '/d', tag: 'd' }] };
    return { ok: true, patches: [{ path: [1, 0], op: 'replace', node: text('got ' + req.outcome.body) }] };
  });
  const remote = new Remote(worker);
  const loading = remote.load(new ArrayBuffer(8));
  await settle();
  await worker.deliver();
  await loading;
  const turns = [];
  const done = remote.mount(doc.mountPoint(), { doc, onTurn: (r) => turns.push(r.patches[0].node.s || 'tree') });
  await settle();
  await worker.deliver();
  const app = await done;
  const button = app.host.root.childNodes[0];
  button.fire('click');
  button.fire('click');
  await settle();
  // A fetch finishes while the first click is still in flight and the second
  // is queued behind it.
  worker.onmessage({ data: { fetched: { tag: 'd', outcome: { ok: true, body: 'X' } } } });
  await settle();
  check('a finished fetch does not jump the queue',
    worker.turns().map((r) => r.op), ['init', 'event']);
  await worker.deliver();
  check('the queued event goes next, then the supply, in arrival order',
    worker.turns().map((r) => r.op), ['init', 'event', 'event']);
  await worker.deliver();
  check('the supply is sent with the tag and the outcome as a value',
    worker.turns()[3], { op: 'supply', tag: 'd', outcome: { ok: true, body: 'X' } });
  await worker.deliver();
  await app.idle();
  check('its patches reach the document', turns[turns.length - 1], 'got X');
}

// ---- 5. app.mjs ---------------------------------------------------------------------
{
  const rec = new Recorder();
  const doc = new StubDocument(rec);
  const calls = [];
  const saved = Reactor.load;
  Reactor.load = async () => ({
    init: () => ({ ok: true, patches: [{ path: [], op: 'replace', node: elem('div', [], [], [text('a')]) }] }),
    event: () => ({ ok: true, patches: [], fetch: [{ url: '/q', tag: 'q' }] }),
    supply: (tag, outcome) => {
      calls.push([tag, outcome]);
      return { ok: true, patches: [{ path: [0], op: 'replace', node: text('done') }] };
    },
  });
  const saveFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 404, text: async () => '' });
  const app = await mount(new Uint8Array(0), doc.mountPoint(), { doc });
  app.dispatch([], 'click');
  for (let i = 0; i < 20 && calls.length < 1; i++) await settle();
  check('the synchronous host supplies the guest after the reply that asked, failure included',
    calls, [['q', { ok: false, error: 'HTTP 404' }]]);
  globalThis.fetch = saveFetch;
  Reactor.load = saved;
}

if (failures > 0) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
