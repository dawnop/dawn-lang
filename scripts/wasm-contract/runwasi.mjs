// Minimal wasm32-wasi host: node's built-in WASI preview1, stdout/stderr
// inherited, no preopens (the contract corpus does no file io). The exit
// status is the program's own, so run.sh can compare it too.
import { readFile } from 'node:fs/promises';
import { WASI } from 'node:wasi';

const wasi = new WASI({ version: 'preview1', args: process.argv.slice(2), env: {} });
const wasm = await WebAssembly.compile(await readFile(process.argv[2]));
const inst = await WebAssembly.instantiate(wasm, wasi.getImportObject());
process.exit(wasi.start(inst));
