#!/usr/bin/env python3
"""One-time K2 acceptance: materialized inputs, explicit recipes and wire parity."""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import native_seed.contract as c
from native_seed import recipe

ROOT = Path(__file__).resolve().parents[1]
CASES = []


def red(label, code, action):
    try:
        action()
    except c.Rejected as exc:
        assert str(exc).startswith(code + ':'), (label, code, str(exc))
        CASES.append({'case': label, 'expected': code, 'actual': str(exc)})
    else:
        raise AssertionError(f'{label}: invalid input accepted')


def fixture_controls(work):
    k1 = runpy.run_path(str(ROOT / 'scripts/native-seed-contract-test.py'))
    repo = work / 'repo'
    repo.mkdir()
    commit = k1['fixture'](repo)
    c.git(repo, 'fetch', '--quiet', '--no-tags', str(ROOT), c.HISTORICAL_COMMIT)
    source, files = c.source_description(repo, commit)
    lock = c.read_lock(ROOT / 'scripts/native-seed-candidate-v0.104.0.json')
    _, historical = c.git_files(repo, lock['seed']['commit'])
    seed_files = {p: value for p, value in historical.items()
                  if p.startswith(('std/', 'runtime/c/'))}
    receipt = {'schema': 2, 'kind': 'native-bootstrap-inputs',
               'seed_lock_sha256': c.digest(c.canonical(lock)), 'source': source,
               'stages': c.stages(lock, source)}
    captured, seed_tree = work / 'source', work / 'seed'
    c.write_tree(captured, files, readonly=False)
    c.write_tree(seed_tree, seed_files, readonly=False)
    # These fixtures have synthetic embeds; the real generation contract is K1's.
    with patch.object(c, 'verify_generated', lambda _: None):
        def select(stage, std=None, runtime=None, value=receipt):
            base = seed_tree if stage == 'A' else captured
            return recipe.stage_inputs(repo, lock, value, captured, seed_tree, stage,
                                       std or base / 'std', runtime or base / 'runtime/c')
        for stage in ('A', 'B', 'C'):
            assert select(stage) == receipt['stages'][('A', 'B', 'C').index(stage)]
            other = captured if stage == 'A' else seed_tree
            red(stage + ' wrong runtime argument', 'runtime-pairing',
                lambda stage=stage, other=other: select(stage, runtime=other / 'runtime/c'))
            red(stage + ' wrong std argument', 'std-pairing',
                lambda stage=stage, other=other: select(stage, std=other / 'std'))
        red('unknown stage', 'stage-pairing', lambda: select('D'))
        bad = copy.deepcopy(receipt)
        bad['stages'].reverse()
        red('reordered stages', 'stage-pairing', lambda: select('A', value=bad))
        path = captured / 'packages/inflate/dawn.toml'
        saved = path.read_bytes()
        path.unlink()
        red('missing transitive manifest', 'source-inventory', lambda: select('B'))
        path.write_bytes(saved)
        path.unlink()
        path.symlink_to(repo / 'packages/inflate/dawn.toml')
        red('external symlink', 'source-type', lambda: select('B'))
        path.unlink()
        path.write_bytes(saved)
        header = seed_tree / 'runtime/c/dawn_rt.h'
        header.unlink()
        red('missing seed runtime header', 'runtime-pairing', lambda: select('A'))
        header.write_bytes(seed_files['runtime/c/dawn_rt.h'][1])
        runtime_file = seed_tree / 'runtime/c/dawn_rt.c'
        saved_runtime = runtime_file.read_bytes()
        runtime_file.write_bytes(saved_runtime + b'\n/* Forged fixture runtime. */\n')
        forged_lock = copy.deepcopy(lock)
        forged_lock['runtime']['sha256'] = c.inventory_sha(c.inventory(c.scan(seed_tree / 'runtime/c')))
        forged_receipt = copy.deepcopy(receipt)
        forged_receipt['seed_lock_sha256'] = c.digest(c.canonical(forged_lock))
        forged_receipt['stages'] = c.stages(forged_lock, source)
        red('self-consistent substituted seed runtime', 'runtime-pairing',
            lambda: recipe.stage_inputs(repo, forged_lock, forged_receipt, captured, seed_tree,
                                        'A', seed_tree / 'std', seed_tree / 'runtime/c'))
        runtime_file.write_bytes(saved_runtime)

    capture = runpy.run_path(str(ROOT / 'scripts/native-source-tree.py'))['capture']
    script = repo / 'scripts/native-source-tree.py'
    with patch.dict(capture.__globals__, {'__file__': str(script)}):
        entry = capture(work / 'live')
        assert not any(p.is_symlink() for p in entry.parents[2].rglob('*'))
        assert (entry.parents[2] / 'packages/inflate/dawn.toml').is_file()
        dep = repo / 'packages/inflate/dawn.toml'
        data = dep.read_bytes()
        dep.unlink()
        red('live capture missing transitive manifest', 'source-missing',
            lambda: capture(work / 'missing-live'))
        dep.symlink_to(captured / 'packages/inflate/dawn.toml')
        red('live capture external symlink', 'source-type',
            lambda: capture(work / 'linked-live'))
        dep.unlink()
        dep.write_bytes(data)

    # Record the actual shared shell recipe, including link order and flags.
    log = work / 'cc-argv.jsonl'
    cc = work / 'fixture-cc'
    cc.write_text('#!' + sys.executable + '\nimport json, pathlib, sys\n'
                  f'log = pathlib.Path({str(log)!r})\n'
                  'with log.open("a") as out: out.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                  'pathlib.Path(sys.argv[sys.argv.index("-o") + 1]).write_bytes(b"object")\n')
    cc.chmod(0o755)
    units = work / 'units'
    units.mkdir()
    for name, data in [('tu01.c', 'second'), ('tu00.c', 'first is longer')]:
        (units / name).write_text(data)
    info = work / 'info.c'
    info.write_text('info')
    env = {'PATH': '/usr/bin:/bin', 'CC': str(cc), 'CC_JOBS': '1'}
    runtime = seed_tree / 'runtime/c'
    result = subprocess.run([str(ROOT / 'scripts/cc-units.sh'), '--runtime', str(runtime),
                             '--static', '--inline-rc', '-o', str(work / 'binary'),
                             str(units), str(info)], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    compiles, link = commands[:-1], commands[-1]
    assert len(compiles) == 4 and '-static' in link and '-lm' == link[-1]
    for argv in commands:
        assert argv[argv.index('-I') + 1] == str(runtime)
        assert '-DDAWN_RT_INLINE_RC' in argv and '-ffp-contract=off' in argv
    by_source = {argv[argv.index('-c') + 1]: argv[argv.index('-o') + 1] for argv in compiles}
    expected = [by_source[str(path)] for path in
                (units / 'tu00.c', units / 'tu01.c', runtime / 'dawn_rt.c', info)]
    assert link[link.index('-o') + 2:-1] == expected
    log.unlink()
    result = subprocess.run([str(ROOT / 'scripts/cc-units.sh'), '--runtime', str(work / 'absent'),
                             '-o', str(work / 'bad'), str(units)], env=env, capture_output=True)
    assert result.returncode == 2 and b'runtime-input:' in result.stderr and not log.exists()
    CASES.append({'case': 'shared recipe missing runtime', 'expected': 'runtime-input',
                  'actual': result.stderr.decode().strip()})

    def compiler(version='18.1.3', triple='x86_64-unknown-linux-gnu'):
        cc.write_text('#!' + sys.executable + '\nimport pathlib, sys\n'
                      f'probes = {{"--version": "clang version {version}", '
                      f'"-dumpversion": {version!r}, "-dumpmachine": {triple!r}, '
                      f'"-print-resource-dir": {str(work)!r}}}\n'
                      'if sys.argv[1] in probes: print(probes[sys.argv[1]])\n'
                      'else:\n'
                      f' pathlib.Path(sys.argv[sys.argv.index("-o") + 1]).write_bytes({bytes(k1["elf"]())!r})\n')
        cc.chmod(0o755)

    compiler('18.1.4')
    red('wrong compiler version', 'cc-version', lambda: recipe.compiler_probe(cc, env))
    compiler(triple='aarch64-unknown-linux-gnu')
    red('wrong compiler target', 'cc-target', lambda: recipe.compiler_probe(cc, env))
    compiler()
    lock_path, receipt_path = work / 'lock.json', work / 'inputs.json'
    c.atomic_json(lock_path, lock)
    c.atomic_json(receipt_path, receipt)
    args = SimpleNamespace(repo=repo, lock=lock_path, receipt=receipt_path, source=captured,
                           seed_tree=seed_tree, stage='A', std=seed_tree / 'std', runtime=runtime,
                           jobs=1, out=work / 'stage-A', recipe_out=work / 'stage-A.json',
                           cc=cc, units=units, build_info=info)
    with patch.object(c, 'verify_generated', lambda _: None):
        result = recipe.compile_stage(args)
        assert result['stage'] == 'A' and result['selection'] == receipt['stages'][0]
        assert c.read_json(args.recipe_out) == result
        args.out, args.recipe_out = work / 'wrong-A', work / 'wrong-A.json'
        args.runtime = captured / 'runtime/c'
        red('compile boundary rejects wrong runtime', 'runtime-pairing',
            lambda: recipe.compile_stage(args))
        assert not args.out.exists() and not args.recipe_out.exists()


def java_execs(trace):
    events = []
    for line in trace.splitlines():
        match = re.search(r'execve(?:at)?\([^"\n]*"([^"]+)"', line)
        if match and Path(match[1]).name in ('java', 'java.real', 'javac', 'javac.real'):
            events.append(line)
    return events


def wire_controls(args, work):
    native = args.dawnc.resolve()
    java = args.java.resolve()
    jar = args.jvm_jar.resolve()
    base = work / 'wire'
    for name, deps in [('app', '[deps]\na = "../alpha"\nc = "../charlie"\n'),
                       ('alpha', '[deps]\ns = "../shared"\n'),
                       ('charlie', '[deps]\ns = "../shared"\n'), ('shared', '')]:
        project = base / name
        (project / 'src').mkdir(parents=True)
        (project / 'dawn.toml').write_text(f'schema = 1\nname = "{name}"\n' + deps)
        (project / 'src/main.dawn').write_text('pub fn main() -> Unit = ()\n')
    reports = []
    count = 0

    def pair(label, argv, expected_rc=0, error=None):
        nonlocal count
        trace = work / f'{label}.exec'
        env = {'PATH': '/nonexistent', 'LANG': 'C.UTF-8', 'HOME': str(work)}
        n = subprocess.run([shutil.which('strace'), '-f', '-e', 'trace=execve,execveat',
                            '-o', str(trace), str(native), *argv], env=env, capture_output=True)
        j = subprocess.run([str(java), '-XX:-UsePerfData', '-Xss512m', '-Xmx2g',
                            '-jar', str(jar), *argv], capture_output=True)
        assert (n.returncode, n.stdout, n.stderr) == (j.returncode, j.stdout, j.stderr), (
            label, n.returncode, n.stdout, n.stderr, j.returncode, j.stdout, j.stderr)
        assert n.returncode == expected_rc, (label, n.stderr)
        if error is not None:
            assert not n.stdout and error in n.stderr, (label, n.stderr)
        for side, result in [('native', n), ('jvm', j)]:
            (work / f'{label}.{side}.out').write_bytes(result.stdout)
            (work / f'{label}.{side}.err').write_bytes(result.stderr)
        events = java_execs(trace.read_text())
        assert not events, events
        count += len(events)
        reports.append({'case': label, 'wire_sha256': c.digest(n.stdout), 'bytes': len(n.stdout),
                        'exit': n.returncode, 'java_execs': len(events)})
        return n.stdout

    argv = ['__source-inputs', '--base', str(base), str(base / 'app')]
    original = pair('diamond', argv)
    assert original.startswith(b'dawn-source-inputs-v1\n')
    assert original.count(b'R\tF\tshared/dawn.toml\n') == 1
    assert b'R\tO\tapp/dawn.lock\n' in original
    moved = work / 'moved'
    shutil.copytree(base, moved)
    assert pair('relocated', ['__source-inputs', '--base', str(moved), str(moved / 'app')]) == original
    pair('compiler-project', ['__source-inputs', '--base', str(ROOT), str(ROOT / 'selfhost')])
    capture = runpy.run_path(str(ROOT / 'scripts/native-source-tree.py'))['capture']
    entry = capture(work / 'portable-compiler')
    pair('portable-compiler', ['__source-inputs', '--base', str(entry.parents[2]),
                               str(entry.parents[1])])
    pair('arity', ['__source-inputs'], 2, b'usage: dawn __source-inputs')
    pair('direct-file', ['__source-inputs', '--base', str(base), str(base / 'app/src/main.dawn')],
         2, b'requires a project directory:')
    link = base / 'app/src/link.dawn'
    link.symlink_to(base / 'shared/src/main.dawn')
    pair('external-link', argv, 1, b'source input path crosses a symbolic link:')
    link.unlink()
    missing = base / 'shared/dawn.toml'
    missing.unlink()
    pair('missing-transitive', argv, 1, b'error: dependency `s` has no dawn.toml (looked in ')
    # A canary proves the trace reader observes descendant Java-named execs.
    canary = work / 'java'
    canary.symlink_to('/bin/true')
    trace = work / 'trace-canary.exec'
    result = subprocess.run([shutil.which('strace'), '-f', '-e', 'trace=execve,execveat', '-o',
                             str(trace), sys.executable, '-c',
                             'import subprocess,sys; subprocess.run([sys.argv[1]],check=True)',
                             str(canary)], capture_output=True)
    assert result.returncode == 0 and len(java_execs(trace.read_text())) == 1
    return {'pairs': reports, 'native_java_execs': count, 'descendant_canary_java_execs': 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dawnc', type=Path)
    parser.add_argument('--java', type=Path)
    parser.add_argument('--jvm-jar', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    fixture_controls(args.out)
    wire = None
    if args.dawnc:
        assert args.java and args.jvm_jar and shutil.which('strace')
        wire = wire_controls(args, args.out)
    report = {'fixture_controls': CASES, 'wire': wire}
    (args.out / 'results.json').write_bytes(c.canonical(report))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
