// Minimal wasm32-wasi host: node's built-in WASI preview1, stdout/stderr
// inherited, no preopens (the contract corpus does no file io). The exit
// status is the program's own, so run.sh can compare it too. The runtime's
// own DAWN_* switches pass through -- DAWN_RC_BALANCE is how run.sh reads
// the leak ledger -- and nothing else does, so the guest env stays as
// deterministic as the empty one this started with.
import { readFile } from 'node:fs/promises';
import { WASI } from 'node:wasi';

const env = {};
for (const k of Object.keys(process.env)) {
  if (k.startsWith('DAWN_')) env[k] = process.env[k];
}
const wasi = new WASI({ version: 'preview1', args: process.argv.slice(2), env });
const wasm = await WebAssembly.compile(await readFile(process.argv[2]));
const inst = await WebAssembly.instantiate(wasm, wasi.getImportObject());
process.exit(wasi.start(inst));
