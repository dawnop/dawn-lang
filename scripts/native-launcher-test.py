#!/usr/bin/env python3
"""Exercise launcher boundaries without bootstrapping a compiler in each control.

The deployment cases execute the real shell with counting Java/Python shims.
Cache controls use real static ELF identities and an explicit builder fixture;
removing an owned guard must make its negative control fail.
"""

import copy
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from native_seed import builder, contract as c, inputs, launcher, probes, provenance, stat_cache, test_support, toolchain

ROOT = Path(__file__).resolve().parents[1]
MUTANT = sys.argv[2] if sys.argv[1:2] == ['--mutant'] else None
if MUTANT in ('marker', 'elf'):
    require = c.require
    disabled = {'generation-commit'} if MUTANT == 'marker' else {'chain-output', 'generation-output'}
    c.require = lambda ok, code, detail: None if code in disabled else require(ok, code, detail)
if MUTANT == 'locking':
    launcher.fcntl.flock = lambda *a: None
if MUTANT == 'ctime':
    original_key = stat_cache.key
    stat_cache.key = lambda value: [*original_key(value)[:4], 0, original_key(value)[5]]
if MUTANT == 'racy':
    stat_cache.DigestCache.racy = lambda *a: False
    original_load = stat_cache.DigestCache.load.__func__
    def unracy(cls, *args):
        loaded = original_load(cls, *args)
        for row in loaded.entries.values():
            row['racy'] = False
        return loaded
    stat_cache.DigestCache.load = classmethod(unracy)
if MUTANT in ('probe-clang', 'probe-gcc', 'probe-recipe'):
    ignored = MUTANT.removeprefix('probe-')
    probes.same_binding = lambda left, right: ({k: v for k, v in left.items() if k != ignored} ==
                                               {k: v for k, v in right.items() if k != ignored})
if MUTANT == 'probe-racy':
    probes.Queries.is_racy = lambda *args: False
    original_probe_load = stat_cache.DigestCache.load.__func__
    def clean_probes(cls, *args):
        loaded = original_probe_load(cls, *args)
        if loaded.probes is not None:
            loaded.probes['racy'] = False
        return loaded
    stat_cache.DigestCache.load = classmethod(clean_probes)
if MUTANT == 'cache-integrity':
    original_require = c.require
    c.require = lambda ok, code, detail: None if code == 'stat-cache' else original_require(ok, code, detail)


def deployments(work):
    root = work / 'deployed'
    (root / 'bin').mkdir(parents=True)
    (root / 'build').mkdir()
    shutil.copyfile(ROOT / 'bin/dawn', root / 'bin/dawn')
    if MUTANT == 'java':
        text = (root / 'bin/dawn').read_text()
        if text.count('DEPLOYED=0') != 1:
            raise AssertionError('deployment mutation anchor must match exactly once')
        (root / 'bin/dawn').write_text(text.replace('DEPLOYED=0', 'java\nDEPLOYED=0', 1))
    (root / 'bin/dawn').chmod(0o755)
    (root / 'build/dawn-selfhost.jar').write_bytes(b'PK fixture')
    shims = work / 'shims'
    shims.mkdir()
    calls = work / 'calls'
    for name in ('java', 'python3'):
        path = shims / name
        path.write_text('#!/bin/sh\necho ' + name + ' >> "$CALLS"\nexit 0\n')
        path.chmod(0o755)
    env = {'PATH': str(shims) + ':/usr/bin:/bin', 'HOME': str(work), 'CALLS': str(calls)}
    missed = []
    for choice in (None, '', 'native', 'unknown'):
        selected = dict(env)
        if choice is not None:
            selected['DAWN_SEED_CHAIN'] = choice
        run = subprocess.run([str(root / 'bin/dawn'), '--version'], env=selected, capture_output=True)
        if run.returncode == 0 or calls.exists():
            missed.append(repr(choice))
            calls.unlink(missing_ok=True)
    assert not missed, 'deployment silently ignored chain selection: ' + ', '.join(missed)
    for key in ('DAWN_SEED', 'DAWN_NATIVE_SEED', 'DAWN_NATIVE_SEED_LOCK', 'DAWN_NATIVE_SEED_TREE'):
        run = subprocess.run([str(root / 'bin/dawn')], env=dict(env, DAWN_SEED_CHAIN='jar', **{key: 'bad'}),
                             capture_output=True)
        assert run.returncode != 0 and not calls.exists(), key
    run = subprocess.run([str(root / 'bin/dawn'), 'arg with spaces', ''],
                         env=dict(env, DAWN_SEED_CHAIN='jar'), capture_output=True)
    assert run.returncode == 0 and calls.read_text() == 'java\n'
    print('OK deployment is explicitly JVM-only and never requires Python', flush=True)



def refused(action, code):
    try:
        action()
    except (c.Rejected, OSError) as exc:
        codes = (code,) if isinstance(code, str) else code
        assert any(value in str(exc) for value in codes), str(exc)
        print('OK refusal ' + '/'.join(codes), flush=True)
        return
    raise AssertionError('control missed: ' + code)



def live_inputs(work):
    repo = work / 'live-repo'
    repo.mkdir()
    for name in ('packages', 'compiler-plan/src'):
        (repo / name).mkdir(parents=True)
    files = {'selfhost/dawn.toml': b'schema=1\nname="selfhost"\n[java-deps]\n[deps]\nlocal="../local"\n',
             'selfhost/src/nmain.dawn': b'entry\n', 'local/dawn.toml': b'schema=1\nname="local"\n',
             'local/src/main.dawn': b'local\n', 'std/str.dawn': b'std\n',
             'runtime/c/dawn_rt.c': b'runtime\n', 'scripts/cc-units.sh': b'recipe\n'}
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for args in (['init', '-q'], ['add', '.'],
                 ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                  '-c', 'commit.gpgSign=false', 'commit', '-qm', 'Create fixture']):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    commit = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
    _, before = builder.source_files(repo, commit, live=True)
    cache = stat_cache.DigestCache()
    cached_before = c.inventory(builder.source_files(repo, commit, live=True, digest_cache=cache)[1])
    new = repo / 'local/src/new.dawn'
    new.write_bytes(b'untracked local dependency\n')
    _, added = builder.source_files(repo, commit, live=True)
    assert added['local/src/new.dawn'][1] == new.read_bytes() and added != before
    assert c.inventory(builder.source_files(repo, commit, live=True, digest_cache=cache)[1]) != cached_before
    subprocess.run(['git', '-C', str(repo), 'add', 'local/src/new.dawn'], check=True)
    assert 'local/src/new.dawn' in builder.source_files(repo, commit, live=True, digest_cache=cache)[1]
    subprocess.run(['git', '-C', str(repo), 'reset', '-q', '--', 'local/src/new.dawn'], check=True)
    new.unlink()
    path = repo / 'local/src/main.dawn'
    path.write_bytes(path.read_bytes() + b'dirty\n')
    assert builder.source_files(repo, commit, live=True)[1] != before
    print('OK live capture includes dirty and new transitive dependency files outside fixed project directories')

def caches(work):
    repo = work / 'repo'
    fixture = repo / 'fixture'
    source = fixture / 'source'
    pair = fixture / 'pair'
    files = {p: ('100644', b'fixture\n') for p in
             ('selfhost/src/nmain.dawn', 'std/str.dawn', 'runtime/c/dawn_rt.c',
              'scripts/cc-units.sh', 'compiler-plan/src/source.dawn',
              'selfhost/src/embed/stdsrc.dawn')}
    c.write_tree(source, files, readonly=False)
    c.write_tree(pair, {p: v for p, v in files.items() if p.startswith(('std/', 'runtime/'))}, readonly=False)
    program = work / 'fixture.c'
    program.write_text(r'''
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
int main(int n, char **v) {
  if (n == 2 && !strcmp(v[1], "--version")) { puts("dawnc 0.106.0 (native) b1:aaaaaaaaaaaa"); return 0; }
  if (n == 4 && !strcmp(v[1], "version") && !strcmp(v[2], "-m")) {
    puts("\tbuild\tb1:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"); return 0;
  }
  if (n > 1 && !strcmp(v[1], "__source-inputs")) { puts("dawn-source-inputs-v1"); return 0; }
  if (n > 1 && !strcmp(v[1], "signal")) { raise(SIGTERM); return 1; }
  char cwd[4096]; puts(getcwd(cwd, sizeof(cwd)));
  for (int i = 1; i < n; i++) printf("[%s]\n", v[i]);
  return 37;
}
''')
    binary = fixture / 'seed-elf'
    subprocess.run(['cc', '-static', '-O0', str(program), '-o', str(binary)], check=True, capture_output=True)
    commit, tree = 'a' * 40, 'b' * 40
    lock = {'schema': 2, 'kind': 'native-seed-lock', 'state': 'proposed', 'sequence': 0,
            'seed': {'kind': 'native-elf', 'tag': 'v0.106.0', 'commit': commit, 'asset': c.ASSET,
                     'sha256': c.digest(binary.read_bytes()), 'size': binary.stat().st_size,
                     'target': c.TARGET, 'version': 'dawnc 0.106.0 (native)', 'build_id': 'b1:' + 'a' * 64},
            'std': c.identity(commit, c.subtree(files, 'std')),
            'runtime': c.identity(commit, c.subtree(files, 'runtime/c')),
            'lineage': {'parent_lock_sha256': None, 'parent_receipt_sha256': None, 'qualification_sha256': None},
            'registration': {'kind': 'local-development', 'metadata': 'absent', 'evidence_sha256': c.digest(b'fixture')}}
    lock_path = fixture / 'seed.json'
    lock_path.write_bytes(c.canonical(lock))
    tc = test_support.compiler_record()
    calls, fail = fixture / 'calls', fixture / 'fail'

    def capture(*args, **kwargs):
        return tree, files if MUTANT == 'dirty' else c.scan(source)

    def paired(repo, selected, path, **kwargs):
        for key, prefix in (('std', 'std'), ('runtime', 'runtime/c')):
            c.require(c.identity(commit, c.inventory_sha(c.inventory(c.scan(Path(path) / prefix)))) == selected[key],
                      key + '-pairing', 'fixture pair differs')

    def build(repo, locked, seed, seed_tree, out, cc, **kwargs):
        with calls.open('a') as log:
            log.write('build\n')
        out.mkdir()
        if fail.exists():
            (out / 'partial').write_text('interrupted stage A')
            if fail.read_text() == 'wait':
                time.sleep(60)
            raise c.Rejected('fixture-build: failed after partial output')
        time.sleep(0.05)
        current = capture()[1]
        c.write_tree(out / 'source', current)
        c.write_tree(out / 'seed', c.scan(pair))
        shutil.copyfile(seed, out / 'seed-elf')
        compilation = inputs.compilation(current, lock, tc)
        stages = {}
        emitter = lock['seed']['sha256']
        for stage in ('A', 'B'):
            base = out / stage
            (base / 'units').mkdir(parents=True)
            for path in ('whole.c', 'info.c', 'units/unit.c'):
                (base / path).write_text(stage + path)
            shutil.copyfile(binary, base / 'dawnc')
            (base / 'dawnc').chmod(0o555)
            output = builder.output_identity(base)
            stages[stage] = {'emitter_sha256': emitter,
                             'std': lock['std'] if stage == 'A' else c.identity(commit, c.subtree(current, 'std')),
                             'runtime': lock['runtime'] if stage == 'A' else c.identity(commit, c.subtree(current, 'runtime/c')),
                             'output': output, 'build_id': lock['seed']['build_id']}
            emitter = output['elf_sha256']
        receipt = {'schema': 1, 'kind': 'native-builder-chain', 'source_commit': commit, 'source_tree': tree,
                   'source_sha256': c.inventory_sha(c.inventory(current)), 'lock_sha256': c.digest(c.canonical(lock)),
                   'compilation': compilation, 'compilation_sha256': c.digest(c.canonical(compilation)),
                   'toolchain': tc, 'recipe_identity': toolchain.recipe_identity(tc, compilation['recipe_sha256']),
                   'execution': provenance.development(commit), 'stages': stages,
                   'plan_sha256': builder.plan(out / 'B/dawnc', out / 'source')}
        c.atomic_json(out / 'chain-receipt.json', receipt)
        return receipt

    env = {'DAWN_NATIVE_SEED': str(binary), 'DAWN_NATIVE_SEED_LOCK': str(lock_path),
           'DAWN_NATIVE_SEED_TREE': str(pair), 'CC': '/usr/lib/llvm-18/bin/clang'}
    with patch.dict(os.environ, env, clear=True), \
         patch.object(builder, 'source_files', side_effect=capture), \
         patch.object(c, 'git', return_value=(commit + '\n').encode()), \
         patch.object(c, 'verify_seed_tree', side_effect=paired), \
         patch.object(toolchain, 'prepare', side_effect=lambda *a, **kw: copy.deepcopy(tc)), \
         patch.object(builder, 'build', side_effect=build):
        def get():
            try:
                return launcher.generation(repo, lambda _: (_ for _ in ()).throw(AssertionError('network')))
            except c.Rejected:
                if MUTANT == 'fallback':
                    return first
                raise
        first = get()
        directory = Path(first['receipt']).parent
        assert first['stamp'].startswith('native-v1:development:override:')
        assert get() == first and calls.read_text() == 'build\n', 'hot launch compiled'
        print('OK cold B and verified hot hit use one native generation')
        default_lock = repo / 'scripts/native-seed-lock.json'
        default_lock.parent.mkdir()
        default_lock.write_bytes(c.canonical(lock))
        cached = repo / '.dawn/native-seeds/v0.106.0' / c.ASSET
        cached.parent.mkdir(parents=True)
        shutil.copyfile(binary, cached)
        # The lock reader has independent transition controls. This fixture
        # substitutes its verified result only to exercise the default frame.
        with patch.object(launcher, 'controls', return_value=(lock, {'chain': ['fixture'], 'revoked': {}})), \
             patch.dict(os.environ, {'CC': '/usr/lib/llvm-18/bin/clang'}, clear=True):
            default = get()
            assert default['stamp'].startswith('native-v1:development:default:')
            assert default['stamp'] != first['stamp'] and default['receipt'] != first['receipt']
        default_lock.unlink()
        default_lock.parent.rmdir()
        print('OK default and override frames never share a native generation')
        for name in files:
            target = source / name
            before = target.read_bytes()
            target.write_bytes(before + b'dirty\n')
            changed = get()
            assert changed['stamp'] != first['stamp'], 'dirty input failed to invalidate: ' + name
            target.write_bytes(before)
            assert get() == first
        before = tc['linker']['version']
        tc['linker']['version'] += ' changed'
        assert get()['stamp'] != first['stamp'], 'toolchain failed to invalidate'
        tc['linker']['version'] = before
        assert get() == first
        print('OK dirty source, dependency, std, runtime, embed, recipe and toolchain invalidate')
        tc['recipe'] = 'development-clang-gcc13-static-v1'
        with patch.dict(os.environ, {'CC': '/fixture/alternate-clang'}):
            alternate = get()
            record = c.read_json(Path(alternate['receipt']).with_name('chain-receipt.json'))
            assert alternate['stamp'].startswith('native-v1:development:override:')
            assert record['execution']['kind'] == 'development'
            refused(lambda: toolchain.verify_record(record['toolchain']), 'toolchain-recipe')
        tc['recipe'] = toolchain.RECIPE
        assert get() == first
        print('OK alternate CC generations retain development scope and cannot qualify')
        # Inputs change while a usable old B still exists. A failed build must
        # fail this command and preserve, rather than execute, that old B.
        target = source / 'selfhost/src/nmain.dawn'
        target.write_bytes(target.read_bytes() + b'failure\n')
        fail.write_text('fail')
        refused(get, 'fixture-build')
        assert (directory / 'committed.json').exists()
        fail.unlink()
        target.write_bytes(files['selfhost/src/nmain.dawn'][1])
        assert get() == first
        print('OK failed build leaves old bytes without falling back')
        for path in ('committed.json', 'generation.json', 'chain-receipt.json', 'B/dawnc', 'A/info.c'):
            target = directory / path
            before = target.read_bytes()
            target.chmod(0o644)
            target.write_bytes(before + b'polluted')
            refused(get, ('generation-receipt' if path == 'chain-receipt.json' else 'schema') if path.endswith('.json') else (('chain-output', 'generation-output') if path == 'B/dawnc' else 'generation-output'))
            target.write_bytes(before)
            target.chmod(0o555 if path == 'B/dawnc' else 0o444)
        marker = directory / 'committed.json'
        before = marker.read_bytes()
        marker.unlink()
        refused(get, 'source-missing')
        marker.write_bytes(before)
        # A foreign cache type cannot become a native hit even if it occupies
        # the expected pathname; the JAR cache beside it is left untouched.
        jar = repo / 'build/dawn-selfhost.jar'
        jar.write_bytes(b'PK unrelated JAR generation')
        value = c.read_json(marker)
        marker.write_bytes(c.canonical(dict(value, kind='jar-commit')))
        refused(get, 'generation-commit')
        marker.write_bytes(before)
        assert jar.read_bytes() == b'PK unrelated JAR generation'
        print('OK marker, receipt, ELF, intermediate pollution and cross-chain cache mixing refused')
        with patch.dict(os.environ, {'DAWN_NATIVE_SEED_TREE': ''}):
            refused(get, 'seed-override')
        target = pair / 'std/str.dawn'
        before = target.read_bytes()
        target.write_bytes(before + b'wrong pair')
        refused(get, 'std-pairing')
        target.write_bytes(before)
        before = binary.read_bytes()
        binary.write_bytes(before + b'wrong seed')
        refused(get, 'seed-digest')
        binary.write_bytes(before)
        # Forked callers inherit only fixture substitutions. Production lock,
        # staging, marker and verification code execute in every child.
        target = source / 'selfhost/src/nmain.dawn'
        target.write_bytes(target.read_bytes() + b'concurrent\n')
        count = len(calls.read_text().splitlines())
        context = multiprocessing.get_context('fork')
        queue = context.Queue()
        children = [context.Process(target=lambda: queue.put(get())) for _ in range(3)]
        for child in children:
            child.start()
        for child in children:
            child.join(20)
            assert child.exitcode == 0
        results = [queue.get(timeout=2) for _ in children]
        assert results[0] == results[1] == results[2]
        assert len(calls.read_text().splitlines()) == count + 1, 'concurrent callers built more than once'
        print('OK three concurrent cold callers serialize and build once')
        target.write_bytes(target.read_bytes() + b'interrupted\n')
        fail.write_text('wait')
        partials = set((repo / 'build/native-toolchain').glob('.staging-*/generation/partial'))
        child = context.Process(target=get)
        child.start()
        deadline = time.monotonic() + 10
        while not (set((repo / 'build/native-toolchain').glob('.staging-*/generation/partial')) - partials) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert set((repo / 'build/native-toolchain').glob('.staging-*/generation/partial')) - partials, 'builder never reached partial output'
        child.terminate()
        child.join(10)
        assert child.exitcode != 0
        fail.unlink()
        recovered = get()
        assert recovered != results[0] and Path(recovered['receipt']).with_name('committed.json').exists()
        print('OK killed builder leaves private staging and the next caller builds a complete B')
        # The actual launch function replaces the process. Its fixture B shows
        # opaque argv, inherited cwd, signal and exit status at the boundary.
        def execute(args):
            context = multiprocessing.get_context('fork')
            transcript = fixture / 'exec.stdout'
            def run():
                fd = os.open(transcript, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
                os.dup2(fd, 1)
                os.close(fd)
                launcher.launch(repo, args, lambda _: None)
            child = context.Process(target=run)
            child.start()
            child.join(20)
            return child.exitcode, transcript.read_bytes()
        assert execute(['signal'])[0] == -15
        status, transcript = execute(['arg with spaces', '', '--cp'])
        assert status == 37 and transcript == (os.getcwd() + '\n[arg with spaces]\n[]\n[--cp]\n').encode()
        print('OK final exec retains signal and exit status; opaque argv and cwd match exactly')


def main():
    with tempfile.TemporaryDirectory(prefix='native-launcher-test-') as work:
        work = Path(work)
        deployments(work)
        live_inputs(work)
        from native_seed.stat_cache_test import run as stat_controls
        stat_controls(work)
        from native_seed.probes_test import run as probe_controls
        probe_controls(work)
        caches(work)
    if '--selftest' in sys.argv:
        for mutant in ('java', 'dirty', 'fallback', 'marker', 'elf', 'locking', 'ctime', 'racy', 'cache-integrity', 'probe-clang', 'probe-gcc', 'probe-recipe', 'probe-racy'):
            run = subprocess.run([sys.executable, '-B', __file__, '--mutant', mutant],
                                 capture_output=True, text=True, timeout=60)
            assert run.returncode != 0 and ('AssertionError' in run.stderr), mutant + ' survived\n' + run.stdout + run.stderr
            print('OK RED mutant ' + mutant, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
