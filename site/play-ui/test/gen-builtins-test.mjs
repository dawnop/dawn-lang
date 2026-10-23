// Exercise the real generator in an isolated tree: launching a JVM wrapper,
// trusting stale JSON or accepting a failed compiler must fail independently
// of the editor's completion-content tests and the compiler's doc oracle.
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
// An optional source lets acceptance run these same assertions against the
// previous generator, with its actual JVM dispatch restored in the fixture.
const source = process.argv[2] ?? join(repo, 'site/play-ui/scripts/gen-builtins.mjs')
const root = mkdtempSync(join(tmpdir(), 'play-ui-builtins-'))
try {
  const ui = join(root, 'site/play-ui')
  for (const dir of ['bin', 'site/build', 'site/play-ui/scripts', 'site/play-ui/src', 'tools']) {
    mkdirSync(join(root, dir), { recursive: true })
  }
  copyFileSync(source, join(ui, 'scripts/gen-builtins.mjs'))
  copyFileSync(join(repo, 'site/dawnc.sh'), join(root, 'site/dawnc.sh'))
  copyFileSync(join(repo, 'site/play-ui/package.json'), join(ui, 'package.json'))
  const trace = join(root, 'trace.jsonl')
  const output = join(ui, 'src/builtins.generated.ts')
  const tool = "tools/native tool ' $(touch INJECTED);"
  const executable = (path, body) => {
    writeFileSync(path, `#!${process.execPath}\n${body}\n`)
    chmodSync(path, 0o755)
  }
  const record = `const fs = require('node:fs');
fs.appendFileSync(process.env.BUILTINS_TRACE, JSON.stringify({
  tool: require('node:path').basename(process.argv[1]),
  cwd: process.cwd(), args: process.argv.slice(2),
}) + '\\n');`
  for (const name of ['dawn', 'java']) {
    executable(join(root, 'bin', name), `${record}
console.error('JVM launcher was executed'); process.exit(91);`)
  }
  executable(join(root, tool), `${record}
if (process.env.BUILTINS_MODE === 'fail') { console.error('native doc failed'); process.exit(23); }
if (process.env.BUILTINS_MODE === 'invalid') process.stdout.write('{bad JSON');
else process.stdout.write(process.env.BUILTINS_INPUT);`)
  const table = (name) => JSON.stringify({ groups: [{ name: 'io', fns: [{ name, sig: 'fn x() -> Int', doc: '' }] }] })
  const env = {
    ...process.env,
    PATH: `${join(root, 'bin')}:${process.env.PATH}`,
    DAWNC_BIN: join(root, tool),
    BUILTINS_TRACE: trace,
    BUILTINS_INPUT: table('current_input'),
  }
  const calls = () => readFileSync(trace, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse)
  const run = (cwd = root, patch = {}, args = [join(ui, 'scripts/gen-builtins.mjs')], command = process.execPath) => {
    writeFileSync(trace, '')
    return spawnSync(command, args, { cwd, env: { ...env, ...patch }, encoding: 'utf8' })
  }
  const green = (result) => {
    assert.equal(result.status, 0, result.stderr)
    assert.deepEqual(calls(), [{ tool: tool.slice('tools/'.length), cwd: root, args: ['doc', '--builtins'] }])
    assert.equal(existsSync(join(root, 'INJECTED')), false)
  }
  green(run())
  const baseline = readFileSync(output, 'utf8')
  green(run(ui))
  assert.equal(readFileSync(output, 'utf8'), baseline)
  green(run(ui, { DAWNC_BIN: tool }))

  // These are npm's actual hooks, reached both via --prefix and from play-ui.
  // dev itself is intentionally not started, since it is a long-lived server.
  for (const cwd of [root, ui]) {
    for (const hook of ['gen-builtins', 'prebuild', 'predev', 'pretest']) {
      green(run(cwd, {}, ['--prefix', ui, 'run', hook, '--silent'], 'npm'))
    }
  }
  console.log('OK: repo/play-ui cwd, npm hooks, relative and special-character DAWNC_BIN; no JVM calls')

  writeFileSync(join(root, 'site/build/builtins.json'), table('stale_input'))
  green(run(ui))
  assert.equal(readFileSync(output, 'utf8'), baseline)
  green(run(root, { BUILTINS_INPUT: table('changed_input') }))
  assert.match(readFileSync(output, 'utf8'), /"name":"changed_input"/)
  assert.doesNotMatch(readFileSync(output, 'utf8'), /current_input|stale_input/)
  console.log('OK: stale JSON ignored and changed compiler output consumed')

  const nonexec = join(root, 'tools/not executable')
  writeFileSync(nonexec, 'not an executable')
  chmodSync(nonexec, 0o644)
  for (const [label, patch, diagnostic] of [
    ['missing', { DAWNC_BIN: join(root, 'tools/missing') }, /ENOENT/],
    ['non-executable', { DAWNC_BIN: nonexec }, /EACCES/],
    ['nonzero', { BUILTINS_MODE: 'fail' }, /native doc failed/],
    ['invalid JSON', { BUILTINS_MODE: 'invalid' }, /SyntaxError/],
  ]) {
    for (const previous of [null, baseline]) {
      if (previous === null) rmSync(output, { force: true })
      else writeFileSync(output, previous)
      const result = run(ui, patch)
      assert.notEqual(result.status, 0, label)
      assert.match(result.stderr, diagnostic, label)
      assert.equal(calls().some((call) => ['dawn', 'java'].includes(call.tool)), false)
      if (previous === null) assert.equal(existsSync(output), false)
      else assert.equal(readFileSync(output, 'utf8'), previous)
    }
  }
  green(run())
  assert.equal(readFileSync(output, 'utf8'), baseline)
  console.log('OK: missing/non-executable/nonzero/invalid JSON fail without partial output or JVM fallback; recovery succeeds')
} finally {
  rmSync(root, { recursive: true, force: true })
}
