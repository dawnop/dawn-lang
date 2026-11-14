#!/usr/bin/env python3
"""Bind successful tile receipts and timings to the complete source matrix.

Small job outputs carry the receipts. Only the final union uploads evidence,
so the control path does not need an artifact transfer for every shard.
"""
import argparse
import copy
import hashlib
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
    git = lambda rev: sp.check_output(['git', 'rev-parse', rev], cwd=ROOT, text=True).strip()
    return dict(schema=1, checkout=git('HEAD'), tree=git('HEAD^{tree}'),
        repository=os.environ['GITHUB_REPOSITORY_ID'], run=os.environ['GITHUB_RUN_ID'],
        inputs=sp.check_output(['python3', '-I', '-B', 'scripts/tile-gpu-diff/inputs.py'],
                               cwd=ROOT, text=True).strip(),
        plan=sha(plan), matrix=sha(ROOT / 'scripts/tile-golden/matrix.txt'),
        golden=golden.hexdigest(), recipe=sha(Path(__file__)))


def selections(plan, total):
    matrix = lines(ROOT / 'scripts/tile-golden/matrix.txt')
    if len(matrix) != 430 or len(set(matrix)) != len(matrix):
        raise ValueError('wrong matrix cardinality')
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
    if len(ran) != 430 or len(set(ran)) != 430:
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
    raw = lines(Path(os.environ['ITEM_TIMES']))
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
        times={n: timings[n] for n in ran}, raw_times_sha256=sha(Path(os.environ['ITEM_TIMES'])))
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
    # Fixed fixtures exercise the same verifier without compiling mutants.
    expected = dict(inputs='input', plan='plan', golden='golden')
    selected = {i: [f'item-{n}' for n in range(i - 1, 430, 19)] for i in range(1, 20)}
    receipts = [dict(identity=expected.copy(), index=i, total=19, attempt='1',
        ran=names.copy(), times={n: 1.0 for n in names}, prebuilt_unchanged=True)
        for i, names in selected.items()]
    validate(receipts, expected, selected)
    changes = {
        'missing shard': lambda r: r.pop(),
        'duplicate shard': lambda r: r.__setitem__(-1, copy.deepcopy(r[0])),
        'wrong index': lambda r: r[0].__setitem__('index', 0),
        'wrong inputs': lambda r: r[0]['identity'].__setitem__('inputs', 'wrong'),
        'changed golden': lambda r: r[0]['identity'].__setitem__('golden', 'wrong'),
        'changed plan': lambda r: r[0]['identity'].__setitem__('plan', 'wrong'),
        'missing mutant': lambda r: r[0]['ran'].pop(),
        'repeated mutant': lambda r: r[0]['ran'].append(r[0]['ran'][0]),
        'missing clock': lambda r: r[0]['times'].pop(r[0]['ran'][0]),
        'consumer rebuild': lambda r: r[0].__setitem__('prebuilt_unchanged', False),
    }
    for name, change in changes.items():
        candidate = copy.deepcopy(receipts)
        change(candidate)
        try:
            validate(candidate, expected, selected)
        except ValueError:
            print('PASS coverage refusal: ' + name)
        else:
            raise AssertionError('accepted ' + name)
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
    ap.add_argument('--total', type=int, default=19)
    ap.add_argument('--job-prefix', default='tile-golden-')
    ap.add_argument('--out', type=Path, default=Path('tile-evidence'))
    args = ap.parse_args()
    {'receipt': receipt, 'union': union, 'selftest': lambda _: selftest()}[args.command](args)
