#!/usr/bin/env python3
"""Bind successful tile receipts and timings to the complete source matrix.

Small job outputs carry the receipts. Only the final union uploads evidence,
so the control path does not need an artifact transfer for every shard.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess as sp
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    return [s for s in path.read_text().splitlines() if s and not s.startswith('#')]


def contract(plan):
    sp.run(['git', 'diff', '--quiet', 'HEAD'], cwd=ROOT, check=True)
    golden = hashlib.sha256()
    for p in sorted((ROOT / 'scripts/tile-golden').iterdir()):
        if p.suffix in ('.mlir', '.tilebc', '.disasm', '.lines'):
            golden.update(p.name.encode() + b'\0' + p.read_bytes())
    checkout, tree = sp.check_output(['git', 'rev-parse', 'HEAD', 'HEAD^{tree}'],
                                    cwd=ROOT, text=True).splitlines()
    spec = importlib.util.spec_from_file_location('tile_gpu_inputs',
        ROOT / 'scripts/tile-gpu-diff/inputs.py')
    inputs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inputs)
    return dict(schema=1, checkout=checkout, tree=tree,
        repository=os.environ['GITHUB_REPOSITORY_ID'], run=os.environ['GITHUB_RUN_ID'],
        inputs=inputs.digest(),
        plan=sha(plan), matrix=sha(ROOT / 'scripts/tile-golden/matrix.txt'),
        golden=golden.hexdigest(), recipe=sha(Path(__file__)))


def selections(plan, total, matrix_path=None):
    matrix = lines(matrix_path or ROOT / 'scripts/tile-golden/matrix.txt')
    if not matrix or len(set(matrix)) != len(matrix):
        raise ValueError('empty matrix or duplicate matrix item')
    dealt = {}
    header = {}
    for line in lines(plan):
        if '=' in line.split()[0]:
            k, v = line.split('=', 1)
            if k in header:
                raise ValueError('duplicate plan header')
            header[k] = v
        else:
            name, index, *_ = line.split()
            index = int(index)
            if name in dealt or name not in matrix or not 1 <= index <= total:
                raise ValueError('duplicate, unknown or out of range plan item')
            dealt[name] = index
    if header != {'harness': 'tile-golden', 'shards': str(total)}:
        raise ValueError('wrong plan header')
    missing = set(matrix) - set(dealt)
    if missing:
        raise ValueError('plan has fallback items')
    result = {i: [] for i in range(1, total + 1)}
    for name in matrix:
        result[dealt[name]].append(name)
    if any(not values for values in result.values()):
        raise ValueError('empty shard')
    return result


def validate(receipts, expected, selected):
    expected_ran = [name for names in selected.values() for name in names]
    if not expected_ran or len(set(expected_ran)) != len(expected_ran):
        raise ValueError('empty or duplicate selected work')
    if len(receipts) != len(selected):
        raise ValueError('missing or duplicate shard')
    seen = set()
    ran = []
    for r in receipts:
        i = r['index']
        if i not in selected or i in seen or r['total'] != len(selected):
            raise ValueError('wrong or duplicate shard index')
        seen.add(i)
        if r['identity'] != expected:
            raise ValueError('wrong receipt inputs, plan, golden or source identity')
        if not str(r['attempt']).isdigit() or int(r['attempt']) < 1:
            raise ValueError('wrong consumer attempt')
        if r.get('prebuilt_unchanged') is not True:
            raise ValueError('consumer rebuilt or altered the preparation closure')
        if r['ran'] != selected[i] or set(r['times']) != set(r['ran']):
            raise ValueError('missing, duplicate or wrong selected work')
        if any(not math.isfinite(t) or t <= 0 for t in r['times'].values()):
            raise ValueError('invalid successful item timing')
        ran += r['ran']
    if sorted(ran) != sorted(expected_ran):
        raise ValueError('union misses or repeats work')


def verify_prebuilt(closure, build):
    expected = json.loads((closure / 'manifest.json').read_text())['selfhost']
    for name in ('dawn-selfhost.jar', 'dawn-selfhost.stamp', 'dawn-selfhost.inputs'):
        received = closure / 'repo/build' / name
        actual = build / name
        if (expected[name], received.stat().st_mtime_ns) != (sha(actual), actual.stat().st_mtime_ns):
            raise ValueError('consumer rebuilt or altered ' + name)
    native = closure / 'native'
    for name, digest in json.loads((native / 'native.json').read_text())['files'].items():
        if sha(native / name) != digest:
            raise ValueError('consumer altered ' + name)
    return True


def receipt(args):
    started = time.monotonic()
    selected = selections(args.plan, args.total)
    path = Path(os.environ['MUTANT_COVERAGE_DIR']) / f'tile-golden-{args.index}-of-{args.total}.coverage'
    data = lines(path)
    if data[:2] != ['harness=tile-golden', f'shard={args.index}/{args.total}']:
        raise ValueError('wrong coverage header')
    ran = [s.removeprefix('ran=') for s in data[2:]]
    if ran != selected[args.index]:
        raise ValueError('actual ran differs from selector')
    raw_bytes = Path(os.environ['ITEM_TIMES']).read_bytes()
    raw = [s for s in raw_bytes.decode().splitlines() if s and not s.startswith('#')]
    timings = {}
    for line in raw:
        name, value = line.split()
        if name in timings:
            raise ValueError('duplicate item clock')
        timings[name] = float(value)
    if set(timings) != set(lines(ROOT / 'scripts/tile-golden/matrix.txt')):
        raise ValueError('incomplete raw item clock')
    r = dict(identity=contract(args.plan), index=args.index, total=args.total,
        attempt=os.environ['GITHUB_RUN_ATTEMPT'], ran=ran,
        times={n: timings[n] for n in ran}, raw_times_sha256=hashlib.sha256(raw_bytes).hexdigest())
    closure = Path(os.environ['RUNNER_TEMP']) / 'execution-closure'
    r['prebuilt_unchanged'] = verify_prebuilt(closure, ROOT / 'build')
    # Coverage is emitted only by a successful previous harness step. Never
    # infer successful work from zero duration skip ticks or a partial log.
    if any(t <= 0 for t in r['times'].values()):
        raise ValueError('nonpositive successful item timing')
    r['control_seconds'] = time.monotonic() - started
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as stream:
        stream.write('receipt=' + json.dumps(r, separators=(',', ':')) + '\n')
    print('RAW_ITEM_TIMES_BEGIN\n' + '\n'.join(raw) + '\nRAW_ITEM_TIMES_END')
    print('RECEIPT_METRIC ' + json.dumps(r), flush=True)


def union(args):
    started = time.monotonic()
    needs = json.loads(os.environ['NEEDS_JSON'])
    receipts = []
    for i in range(1, args.total + 1):
        job = needs[f'{args.job_prefix}{i}']
        if job['result'] != 'success':
            raise ValueError(f'shard {i} did not succeed')
        receipts.append(json.loads(job['outputs']['receipt']))
    validate(receipts, contract(args.plan), selections(args.plan, args.total))
    args.out.mkdir(parents=True, exist_ok=True)
    # Preserve the original matrix and harness-set checker. The records come
    # from the already verified successful receipts, without another transfer.
    coverage = args.out / 'coverage'
    coverage.mkdir()
    for r in receipts:
        (coverage / f"tile-golden-{r['index']}-of-{r['total']}.coverage").write_text(
            'harness=tile-golden\n' + f"shard={r['index']}/{r['total']}\n" +
            ''.join(f'ran={name}\n' for name in r['ran']))
    sp.run(['python3', '-B', str(ROOT / 'scripts/mutant-coverage/check.py'),
            '--coverage-dir', str(coverage), '--only-harness', 'tile-golden'],
           cwd=ROOT, check=True)
    (args.out / 'receipts.json').write_text(json.dumps(receipts, indent=2) + '\n')
    costs = {n: t for r in receipts for n, t in r['times'].items()}
    (args.out / 'ITEM_TIMES.txt').write_text(''.join(f'{n} {costs[n]:.2f}\n' for n in lines(ROOT / 'scripts/tile-golden/matrix.txt')))
    elapsed = time.monotonic() - started
    print('UNION_METRIC ' + json.dumps(dict(items=len(costs), shards=len(receipts),
        seconds=elapsed, receipt_seconds=sum(r['control_seconds'] for r in receipts))), flush=True)


def selftest():
    # Independent small matrices catch accidental coupling to production size.
    # The real plan is checked too, without compiling or running any kernel.
    expected = dict(schema=1, checkout='checkout', tree='tree',
        repository='repository', run='run', inputs='input', plan='plan',
        matrix='matrix', golden='golden', recipe='recipe')

    def records(selected):
        return [dict(identity=expected.copy(), index=i, total=len(selected), attempt='1',
            ran=names.copy(), times={n: 1.0 for n in names}, prebuilt_unchanged=True)
            for i, names in selected.items()]

    def refuse(name, action):
        try:
            action()
        except ValueError:
            print('PASS coverage refusal: ' + name)
        else:
            raise AssertionError('accepted ' + name)

    plan = ROOT / 'scripts/mutant-coverage/plans/tile-golden.txt'
    selected = selections(plan, 20)
    validate(records(selected), expected, selected)
    matrix = lines(ROOT / 'scripts/tile-golden/matrix.txt')
    assert sorted(n for names in selected.values() for n in names) == sorted(matrix)
    print(f'PASS real matrix and plan: {len(matrix)} items, {len(selected)} shards')
    with tempfile.TemporaryDirectory() as tmp:
        matrix_path = Path(tmp) / 'matrix.txt'
        plan = Path(tmp) / 'plan.txt'
        for count, total in ((1, 1), (7, 3), (23, 4)):
            matrix = [f'item-{n}' for n in range(count)]
            matrix_path.write_text('\n'.join(matrix) + '\n')
            rows = [f'{name} {n % total + 1}' for n, name in enumerate(matrix)]
            header = f'harness=tile-golden\nshards={total}\n'
            plan.write_text(header + '\n'.join(reversed(rows)) + '\n')
            selected = selections(plan, total, matrix_path)
            assert selected == {i: matrix[i - 1::total] for i in range(1, total + 1)}
            validate(records(selected), expected, selected)
            print(f'PASS independent matrix: {count} items, {total} shards')

        # Keep item counts unchanged in substitutions: cardinality cannot
        # distinguish a complete plan from one with the wrong work identities.
        for name, changed in {
            'missing plan item': rows[:-1],
            'duplicate plan item': rows + rows[:1],
            'unknown plan item': rows + ['unknown 1'],
            'same count plan substitution': rows[:-1] + ['unknown 1'],
            'same count plan duplication': rows[:-1] + rows[:1],
            'out of range plan shard': rows[:-1] + [f'{matrix[-1]} {total + 1}'],
            'empty plan shard': [f'{n} 1' for n in matrix],
        }.items():
            plan.write_text(header + '\n'.join(changed) + '\n')
            refuse(name, lambda: selections(plan, total, matrix_path))
        plan.write_text(header + '\n'.join(rows) + '\n')
        for name, changed in (('empty matrix', []),
                              ('duplicate matrix item', matrix + matrix[:1])):
            matrix_path.write_text('\n'.join(changed) + '\n')
            refuse(name, lambda: selections(plan, total, matrix_path))

    receipts = records(selected)

    def exchange_work(r):
        r[0]['ran'][0], r[1]['ran'][0] = r[1]['ran'][0], r[0]['ran'][0]

    changes = {
        'missing shard': lambda r: r.pop(),
        'duplicate shard': lambda r: r.__setitem__(-1, copy.deepcopy(r[0])),
        'wrong index': lambda r: r[0].__setitem__('index', 0),
        'wrong total': lambda r: r[0].__setitem__('total', len(selected) + 1),
        'wrong attempt': lambda r: r[0].__setitem__('attempt', '0'),
        'missing mutant': lambda r: r[0]['ran'].pop(),
        'repeated mutant': lambda r: r[0]['ran'].append(r[0]['ran'][0]),
        'unknown mutant': lambda r: r[0]['ran'].append('unknown'),
        'same count substitution': lambda r: r[0]['ran'].__setitem__(0, 'unknown'),
        'same count duplication': lambda r: r[0]['ran'].__setitem__(0, r[0]['ran'][1]),
        'wrong shard work': lambda r: r[0]['ran'].__setitem__(0, r[1]['ran'][0]),
        'exchanged shard work': exchange_work,
        'reordered work': lambda r: r[0]['ran'].reverse(),
        'missing clock': lambda r: r[0]['times'].pop(r[0]['ran'][0]),
        'unknown clock': lambda r: r[0]['times'].__setitem__('unknown', 1.0),
        'consumer rebuild': lambda r: r[0].__setitem__('prebuilt_unchanged', False),
    }
    for key in expected:
        changes['wrong identity ' + key] = lambda r, key=key: r[0]['identity'].__setitem__(key, 'wrong')
    for value in (0.0, -1.0, math.nan, math.inf):
        changes[f'invalid clock {value}'] = lambda r, value=value: r[0]['times'].__setitem__(r[0]['ran'][0], value)
    for name, change in changes.items():
        candidate = copy.deepcopy(receipts)
        change(candidate)
        if name in ('missing mutant', 'repeated mutant', 'unknown mutant',
                    'same count substitution', 'same count duplication',
                    'wrong shard work', 'exchanged shard work', 'reordered work'):
            for r in candidate:
                r['times'] = {n: 1.0 for n in r['ran']}
        refuse(name, lambda: validate(candidate, expected, selected))
    duplicate = copy.deepcopy(selected)
    duplicate[1][0] = duplicate[2][0]
    refuse('duplicate selection union', lambda: validate(records(duplicate), expected, duplicate))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        closure = root / 'closure'
        source = closure / 'repo/build'
        source.mkdir(parents=True)
        build = root / 'build'
        build.mkdir()
        for name in ('dawn-selfhost.jar', 'dawn-selfhost.stamp', 'dawn-selfhost.inputs'):
            (source / name).write_bytes(name.encode())
            shutil.copy2(source / name, build / name)
        (closure / 'manifest.json').write_text(json.dumps(dict(selfhost={
            p.name: sha(p) for p in source.iterdir()})))
        native = closure / 'native'
        native.mkdir()
        for name in ('clean.bin', 'dawn_rt.o'):
            (native / name).write_bytes(name.encode())
        (native / 'native.json').write_text(json.dumps(dict(files={
            name: sha(native / name) for name in ('clean.bin', 'dawn_rt.o')})))
        verify_prebuilt(closure, build)
        for actual in build.iterdir():
            actual.write_bytes(b'altered compiler closure')
            refuse('altered ' + actual.name, lambda: verify_prebuilt(closure, build))
            shutil.copy2(source / actual.name, actual)
        jar = build / 'dawn-selfhost.jar'
        before = jar.stat()
        os.utime(jar, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        try:
            verify_prebuilt(closure, build)
        except ValueError:
            print('PASS closure refusal: identical bytes with rebuilt jar timestamp')
        else:
            raise AssertionError('accepted rebuilt jar timestamp')
        shutil.copy2(source / jar.name, jar)
        (native / 'dawn_rt.o').write_bytes(b'altered runtime')
        try:
            verify_prebuilt(closure, build)
        except ValueError:
            print('PASS closure refusal: altered runtime object')
        else:
            raise AssertionError('accepted altered runtime object')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['receipt', 'union', 'selftest'])
    ap.add_argument('--plan', type=Path, default=ROOT / 'scripts/mutant-coverage/plans/tile-golden.txt')
    ap.add_argument('--index', type=int)
    ap.add_argument('--total', type=int, default=20)
    ap.add_argument('--job-prefix', default='tile-golden-')
    ap.add_argument('--out', type=Path, default=Path('tile-evidence'))
    args = ap.parse_args()
    {'receipt': receipt, 'union': union, 'selftest': lambda _: selftest()}[args.command](args)
