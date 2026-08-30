// What one turn costs when the model is the thing that grew.
//
// The todo application uses the legacy `serve` boundary, which carries its
// whole model as opaque text in both directions every turn. This instrument
// prices that mode's decode, encode, view and diff separately at 10, 100 and
// 1000 todos, on the wasm build of examples/projects/tea_dom_todo. A reactor
// using `serve_with_state` may keep a separate read-only init value; its
// mutable model still has this wire cost.
//
// The decomposition is arithmetic on three requests that differ in what the
// reactor is made to do with the same model:
//
//   parse   a malformed line. `decode_request` fails before the model is
//           read, so this is the fixed cost of a turn: one line in, one line
//           out, and nothing else.
//   decode  an event at an address that listens for nothing. `turn` runs
//           `decode(model)` and one `view`, then answers `no-handler` -- no
//           second view, no diff, no `encode`.
//   full    an event that resolves. Everything above plus `update`, a second
//           `view`, `diff` and `encode`.
//
// The view is held small for those three by parking the model on the `done`
// filter with every todo active: `visible` answers the empty list, so the
// document is the chrome and nothing else and the arithmetic is about the
// model rather than about the rows. `rows` repeats the `full` measurement
// with the filter on `all`, which is the same model with N rows in the view,
// and the difference between them is what view-plus-diff costs.
//
// Only `dawn_turn` is timed. The JSON the host itself parses is timed
// separately and reported beside it, because a reader deciding whether the
// opaque-text model is affordable needs to know which side of the boundary
// the milliseconds are on.
//
//   node scripts/wasm-dom-contract/bench-model.mjs <todo.wasm> [reps] [n,n,...]
//
// Wall-clock numbers, so they are machine-bound and nothing compares them
// with anything: this is a measuring instrument, not a gate.

import { readFile } from 'node:fs/promises';
import { Reactor } from '../../packages/tea-dom/js/reactor.mjs';

const wasmPath = process.argv[2];
const reps = Number(process.argv[3] || 25);
// The sizes are an argument because the interesting one moves: where a turn
// crosses a frame budget is a question about a particular build, and answering
// it by hand means editing the instrument.
const sizes = (process.argv[4] || '0,10,100,1000').split(',').map(Number);
if (!wasmPath || sizes.some((n) => !Number.isInteger(n) || n < 0)) {
  console.error('usage: node bench-model.mjs <todo.wasm> [reps] [n,n,...]');
  process.exit(2);
}

// The encoding is codec.dawn's, written out here rather than obtained from a
// turn, so the model at each size is built without first paying for it.
function model(n, filter) {
  const todos = [];
  for (let i = 1; i <= n; i++) {
    todos.push({ id: i, title: `task number ${i}`, done: false });
  }
  return JSON.stringify({
    todos,
    next: n + 1,
    filter,
    draft: '',
    edit: '',
    editing: null,
  });
}

/** One turn, timing the guest and nothing around it. */
function rawTurn(reactor, line) {
  reactor.wasi.writeStdin(line + '\n');
  const t0 = process.hrtime.bigint();
  reactor.instance.exports.dawn_turn();
  const t1 = process.hrtime.bigint();
  const out = reactor.wasi.takeStdout();
  return { ns: Number(t1 - t0), out };
}

function median(xs) {
  const sorted = xs.slice().sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

function ms(ns) {
  return (ns / 1e6).toFixed(3);
}

function measure(reactor, line) {
  for (let i = 0; i < 3; i++) rawTurn(reactor, line);
  const times = [];
  let out = '';
  for (let i = 0; i < reps; i++) {
    const turn = rawTurn(reactor, line);
    times.push(turn.ns);
    out = turn.out;
  }
  return { ns: median(times), bytes: { in: line.length, out: out.trim().length }, out };
}

const reactor = await Reactor.load(new Uint8Array(await readFile(wasmPath)));

// The addresses are the view's, and they do not move with the model: [0] is
// the heading, which listens for nothing; [2,2] is the `done` filter button
// and [2,0] is the `all` one, and clicking the filter already selected is
// the turn that changes the model not at all.
const NOWHERE = [0];
const DONE_FILTER = [2, 2];
const ALL_FILTER = [2, 0];

const req = (m, path) =>
  JSON.stringify({ op: 'event', model: m, path, event: 'click' });

console.log('n        parse     decode      full       rows | model B  request B  reply B');
for (const n of sizes) {
  const small = model(n, 'done');
  const large = model(n, 'all');

  const parse = measure(reactor, '{"op":"event"}');
  const decode = measure(reactor, req(small, NOWHERE));
  const full = measure(reactor, req(small, DONE_FILTER));
  const rows = measure(reactor, req(large, ALL_FILTER));

  console.log(
    [
      String(n).padEnd(6),
      ms(parse.ns).padStart(8),
      ms(decode.ns).padStart(10),
      ms(full.ns).padStart(10),
      ms(rows.ns).padStart(10),
      '|',
      String(small.length).padStart(7),
      String(full.bytes.in).padStart(10),
      String(full.bytes.out).padStart(8),
      `rows-reply=${rows.bytes.out}`,
    ].join(' '),
  );
}

// The host's own share of the same bytes, for scale: whatever the guest
// costs, the page pays this on top of it every turn.
console.log('');
console.log('host-side JSON on the same payloads (stringify + parse), median of the same reps:');
for (const n of sizes.filter((x) => x > 0)) {
  const line = req(model(n, 'done'), DONE_FILTER);
  const parsed = JSON.parse(line);
  const times = [];
  for (let i = 0; i < reps; i++) {
    const t0 = process.hrtime.bigint();
    JSON.parse(JSON.stringify(parsed));
    times.push(Number(process.hrtime.bigint() - t0));
  }
  console.log(`n=${String(n).padEnd(5)} ${ms(median(times)).padStart(8)} ms  (${line.length} B)`);
}
