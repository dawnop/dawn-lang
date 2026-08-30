// Replay one newline-delimited request session against one wasm instance.
// `Reactor.request` invokes `dawn_turn` once, so every adjacent output line is
// evidence that state survived a return all the way out of the guest's main.

import { readFile } from 'node:fs/promises';
import { Reactor } from '../../packages/tea-dom/js/reactor.mjs';

const [wasmPath, inputPath] = process.argv.slice(2);
if (!wasmPath || !inputPath) {
  console.error('usage: node retained.mjs <reactor.wasm> <requests.txt>');
  process.exit(2);
}

const reactor = await Reactor.load(new Uint8Array(await readFile(wasmPath)));
const lines = (await readFile(inputPath, 'utf8')).split('\n').filter(Boolean);
for (const line of lines) {
  const request = JSON.parse(line);
  const reply = reactor.request(request);
  process.stdout.write(JSON.stringify(reply) + '\n');
}
