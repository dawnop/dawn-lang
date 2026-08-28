// A reactor's memory reaches a plateau and stays on it.
//
//   node plateau.mjs <counter.wasm>
//
// Three gates measured memory and all three were green while the runtime
// leaked a dictionary per relation per turn. Each was green for a good
// reason and none of the reasons was "there is no leak":
//
//   * LeakSanitizer was told not to look. Dictionaries are outside reference
//     counting by design and never freed, so dawn_dict_new marks them owned
//     (dawn_rt.c, DAWN_LSAN_OWN) -- otherwise every corpus run would drown
//     in reports about a decided design.
//   * DAWN_RC_BALANCE counts what enters the ledger, and a dictionary never
//     does. Its balance was exactly zero the whole time.
//   * scripts/rc-contract asks about counting, the allocator and the
//     poisoning. Dictionaries were not on its roster at all.
//
// What none of them asks is whether a program that never exits settles.
// That is this leg's question, and the property is not "small" and not
// "under N bytes", it is *flat*: whatever the module has grown to after the
// warm-up, ten times as many turns after that may not grow it by a single
// page. A per-turn cost of even one machine word fails this; a bounded cache
// paid once passes it. That is exactly the line between a leak and a cache.
//
// Three shapes, because they leak at three different rates and the cheapest
// is the easiest to leave uncovered: a turn that changes the model, a turn
// that answers with no patches at all, and a turn the guest refuses. On the
// leaking runtime those were +4030, +3047 and +164 bytes per turn, so a leg
// that measured only the first would have let an order of magnitude through.
import { readFile } from 'node:fs/promises';
import { Reactor } from '../../packages/tea-dom/js/reactor.mjs';

const WARM = 200;
const RUN = 2000;

// tea_dom_counter's document: [3, 1] is `+`, [3, 0] is `-`, [3, 2] is
// `reset`. A payload on a listener that declared none is a bad request.
const shapes = {
  flip: (i) =>
    i % 2 === 0
      ? { op: 'event', model: '0', path: [3, 1], event: 'click' }
      : { op: 'event', model: '1', path: [3, 0], event: 'click' },
  noop: () => ({ op: 'event', model: '0', path: [3, 2], event: 'click' }),
  refused: () => ({ op: 'event', model: '0', path: [3, 1], event: 'click', payload: 'x' }),
};

const wasmPath = process.argv[2];
if (!wasmPath) {
  console.error('usage: node plateau.mjs <counter.wasm>');
  process.exit(2);
}

const bytes = await readFile(wasmPath);
let bad = 0;

for (const [name, req] of Object.entries(shapes)) {
  // A fresh instance per shape: the plateau one shape settles on says nothing
  // about another, and sharing one would let a later shape ride an earlier
  // one's headroom.
  const reactor = await Reactor.load(bytes);
  const pages = () => reactor.instance.exports.memory.buffer.byteLength / 65536;
  for (let i = 0; i < WARM; i++) reactor.request(req(i));
  const settled = pages();
  for (let i = 0; i < RUN; i++) reactor.request(req(i));
  const after = pages();
  if (after === settled) {
    console.log(
      `OK   plateau ${name}: ${settled} pages after ${WARM} turns, ` +
        `still ${settled} after ${WARM + RUN}`,
    );
  } else {
    const perTurn = (((after - settled) * 65536) / RUN).toFixed(1);
    console.log(
      `FAIL plateau ${name}: ${settled} pages after ${WARM} turns, ${after} after ` +
        `${WARM + RUN} (+${perTurn} B/turn: the reactor keeps something every turn)`,
    );
    bad++;
  }
}

process.exit(bad === 0 ? 0 : 1);
