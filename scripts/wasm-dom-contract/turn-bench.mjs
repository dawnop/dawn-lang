// What one reactor turn costs, stage by stage (#361).
//
//   node scripts/wasm-dom-contract/turn-bench.mjs <turn-bench.wasm> [reps] [best-of]
//
// The guest is turn-bench/, built as an ordinary wasm32-wasi command (not a
// reactor): it reads `<stage> <reps> <scenario>`, prepares every input a turn
// has, and runs one stage `reps` times. A stage's price is
// (T(reps) - T(0)) / reps, each T the best of several fresh instances, so the
// instance start, the preparation and the final print all cancel. Nothing
// inside the guest is a clock; std has none, and the turn being priced is a
// pure function that an in-guest timer would have to break open.
//
// The stages are the pieces `tea_dom/reactor.turn_with_state` is made of, in
// the order a turn runs them: parse the request line, decode the model text,
// view the model the host holds, route the event, update, view the result,
// diff, encode the new model, and serialise the reply. `view` is listed twice
// because a turn runs it twice (the old tree to route through, the new one to
// diff against); the guest prices one call. `compare` is the string equality a
// cached old tree needs to decide whether it is still the host's tree.
// `turn` is the whole public turn and `turn_cached` the retained-tree turn,
// so the sum of the parts can be checked against the whole.
//
// Wall-clock numbers, machine-bound: an instrument, not a gate.
import { WASI } from 'node:wasi';
import { readFileSync, writeFileSync, openSync, closeSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , wasmPath, repsArg = '100', bestArg = '5'] = process.argv;
if (!wasmPath) {
  console.error('usage: node turn-bench.mjs <turn-bench.wasm> [reps] [best-of]');
  process.exit(2);
}
const reps = Number(repsArg);
const best = Number(bestArg);
const mod = await WebAssembly.compile(readFileSync(wasmPath));
const dir = mkdtempSync(join(tmpdir(), 'turn-bench-'));
const input = join(dir, 'in');
const output = join(dir, 'out');

async function run(stage, n, scenario) {
  writeFileSync(input, `${stage} ${n} ${scenario}\n`);
  let fastest = Infinity;
  let said = '';
  for (let k = 0; k < best; k++) {
    const fdIn = openSync(input, 'r');
    const fdOut = openSync(output, 'w');
    const wasi = new WASI({ version: 'preview1', args: ['turn-bench'], stdin: fdIn, stdout: fdOut });
    const inst = await WebAssembly.instantiate(mod, wasi.getImportObject());
    const t0 = performance.now();
    wasi.start(inst);
    fastest = Math.min(fastest, performance.now() - t0);
    closeSync(fdIn);
    closeSync(fdOut);
    said = readFileSync(output, 'utf8').trim();
  }
  return { ms: fastest, said };
}

const stages = ['parse', 'decode', 'view', 'route', 'update', 'diff', 'encode', 'reply', 'compare', 'turn', 'turn_cached'];
const scenarios = ['empty', 'rows'];
const table = {};
for (const scenario of scenarios) {
  const zero = await run('none', 0, scenario);
  console.log(`# ${scenario}: ${zero.said}`);
  for (const stage of stages) {
    const full = await run(stage, reps, scenario);
    // A stage this build of the guest does not have (an older build has no
    // `turn_cached`) is left out of the table rather than priced at zero.
    if (full.said.startsWith('unknown stage')) continue;
    (table[stage] ??= {})[scenario] = (full.ms - zero.ms) / reps;
  }
}
rmSync(dir, { recursive: true, force: true });

console.log(`stage          ${scenarios.map((s) => s.padStart(9)).join(' ')}   (ms per call, reps=${reps}, best of ${best})`);
for (const stage of stages) {
  if (!table[stage]) continue;
  console.log(`${stage.padEnd(14)} ${scenarios.map((s) => table[stage][s].toFixed(3).padStart(9)).join(' ')}`);
}
const parts = ['parse', 'decode', 'view', 'route', 'update', 'view', 'diff', 'encode', 'reply'];
const sum = (s) => parts.reduce((a, p) => a + table[p][s], 0);
console.log(`${'sum of parts'.padEnd(14)} ${scenarios.map((s) => sum(s).toFixed(3).padStart(9)).join(' ')}   (view counted twice)`);
