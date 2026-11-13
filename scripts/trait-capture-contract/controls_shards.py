#!/usr/bin/env python3
"""Validate complete, input bound private and JVM source unions."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRODUCERS = ['run.py', 'controls_shards.py', 'mutate.py', 'summary_cases.py', 'cases.json']


def plan():
    import run as harness
    names = list(harness.MUTATIONS)
    groups = [names[i::3] for i in range(3)]
    if not all(groups) or Counter(n for group in groups for n in group) != Counter(names):
        raise ValueError('Empty, missing or repeated Capture selector')
    if set(names) != set(harness.OWNERS):
        raise ValueError('Every Capture mutant needs its original owner')
    return groups


def calls_plan():
    from summary_cases import CASES
    names = list(CASES)
    groups = [names[i::2] for i in range(2)]
    if not all(groups) or Counter(n for g in groups for n in g) != Counter(names):
        raise ValueError('Empty, missing or repeated JVM source selector')
    return groups


def baseline_cases(names):
    import run as harness
    cases, embedded = set(), set()
    for name in names:
        needed = (set(harness.BASELINE_CASES.get(name, [])) |
                  {case for case, _, _ in harness.CASE_OWNERS.get(name, [])} |
                  set(harness.EXTRA_CASES.get(name, [])) |
                  {case for case, _, _ in harness.EXTRA_ASSERTIONS.get(name, [])})
        cases.update(needed)
        if not any(path.startswith('std/') for path, _, _ in harness.MUTATIONS[name]):
            embedded.update(needed)
    return sorted(cases), sorted(embedded)


def baseline_tests():
    import run as harness
    return [harness.TEST, 'selfhost/src/check/data_capture_test.dawn',
            'selfhost/src/ir/lower.dawn']


def framed(digest, parts):
    for part in parts:
        digest.update(len(part).to_bytes(8, 'big'))
        digest.update(part)


def input_identity(root=ROOT):
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    if root == ROOT:
        paths += [str((HERE / name).relative_to(ROOT)) for name in PRODUCERS]
    inputs, producer = hashlib.sha256(), hashlib.sha256()
    for name in sorted(set(filter(None, paths))):
        path = root / name
        mode = b'120000' if path.is_symlink() else b'100755' if path.stat().st_mode & 0o111 else b'100644'
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        parts = (name.encode(), mode, content)
        framed(inputs, parts)
        if path.name in PRODUCERS:
            framed(producer, parts)
    return dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                inputs=inputs.hexdigest(), producer=producer.hexdigest(),
                plan=hashlib.sha256(json.dumps(dict(controls=plan(), jvm=calls_plan()),
                                              separators=(',', ':')).encode()).hexdigest())


def receipt(index, completed, identity):
    return dict(schema=1, shard=index, shards=3, identity=identity, **completed)


def validate(row, groups, identity):
    keys = {'schema', 'shard', 'shards', 'identity', 'mutants', 'tests', 'subwitness', 'cases', 'embedded'}
    if not isinstance(row, dict) or set(row) != keys:
        raise ValueError('Invalid Capture receipt schema')
    index = row['shard']
    if (type(row['schema']) is not int or row['schema'] != 1 or type(index) is not int or
            not 1 <= index <= 3 or type(row['shards']) is not int or row['shards'] != 3):
        raise ValueError('Wrong Capture selector number or count')
    if row['identity'] != identity:
        raise ValueError('Wrong Capture input, producer or plan identity')
    expected = groups[index - 1]
    mutants = row['mutants']
    if (not isinstance(mutants, list) or
            any(not isinstance(r, dict) or set(r) != {'name', 'compiler_built', 'owning_test_failed'} or
                r['compiler_built'] is not True or r['owning_test_failed'] is not True for r in mutants) or
            [r['name'] for r in mutants] != expected):
        raise ValueError('Incomplete, repeated or unproven Capture mutants')
    cases, embedded = baseline_cases(expected)
    if (row['tests'] != baseline_tests() or row['subwitness'] is not True or
            row['cases'] != cases or row['embedded'] != embedded):
        raise ValueError('Incomplete Capture ordinary baselines or subwitness refusal')


def record(directory, index, completed, identity):
    current = input_identity()
    if current != identity:
        raise ValueError('Capture inputs changed during execution or cleanup')
    row = receipt(index, completed, current)
    validate(row, plan(), current)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'capture-controls-{index}.json').open('x') as stream:
        json.dump(row, stream, indent=2)
        stream.write('\n')


def check(directory, identity=None):
    identity = input_identity() if identity is None else identity
    groups = plan()
    rows = [json.loads(path.read_text()) for path in sorted(directory.rglob('capture-controls-*.json'))]
    for row in rows:
        validate(row, groups, identity)
    if Counter(row['shard'] for row in rows) != Counter([1, 2, 3]):
        raise ValueError('Missing or repeated Capture selector')
    if Counter(r['name'] for row in rows for r in row['mutants']) != Counter(n for group in groups for n in group):
        raise ValueError('Incomplete Capture mutant union')
    print(f'OK: Capture union, three selectors and {sum(map(len, groups))} complete private mutants')


def calls_receipt(index, completed, identity):
    return dict(schema=1, backend='jvm', shard=index, shards=2, identity=identity, **completed)


def validate_calls(row, groups, identity):
    from summary_cases import CASES
    keys = {'schema', 'backend', 'shard', 'shards', 'identity',
            'baseline_checked', 'baseline_ran', 'cases'}
    if not isinstance(row, dict) or set(row) != keys:
        raise ValueError('Invalid JVM source receipt schema')
    index = row['shard']
    if (type(row['schema']) is not int or row['schema'] != 1 or row['backend'] != 'jvm' or
            type(index) is not int or not 1 <= index <= 2 or
            type(row['shards']) is not int or row['shards'] != 2):
        raise ValueError('Wrong JVM source selector number, backend or count')
    if row['identity'] != identity:
        raise ValueError('Wrong JVM source input, producer or plan identity')
    if row['baseline_checked'] is not True or row['baseline_ran'] is not True:
        raise ValueError('Incomplete JVM ordinary call fixture')
    cases = row['cases']
    if (not isinstance(cases, list) or
            any(not isinstance(r, dict) or set(r) != {'case', 'checked', 'ran', 'exit'} or
                r['checked'] is not True or r['ran'] is not True or
                type(r['exit']) is not int for r in cases) or
            [r['case'] for r in cases] != groups[index - 1] or
            any(r['exit'] != CASES[r['case']]['exit'] for r in cases)):
        raise ValueError('Incomplete, repeated or unproven JVM source cases')


def record_calls(directory, index, completed, identity):
    current = input_identity()
    if current != identity:
        raise ValueError('JVM inputs changed during execution or cleanup')
    row = calls_receipt(index, completed, current)
    validate_calls(row, calls_plan(), current)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'capture-calls-jvm-{index}.json').open('x') as stream:
        json.dump(row, stream, indent=2)
        stream.write('\n')


def check_calls(directory, identity=None):
    identity = input_identity() if identity is None else identity
    groups = calls_plan()
    rows = [json.loads(path.read_text()) for path in sorted(directory.rglob('capture-calls-jvm-*.json'))]
    for row in rows:
        validate_calls(row, groups, identity)
    if Counter(row['shard'] for row in rows) != Counter([1, 2]):
        raise ValueError('Missing or repeated JVM source selector')
    if Counter(r['case'] for row in rows for r in row['cases']) != Counter(n for g in groups for n in g):
        raise ValueError('Incomplete JVM source union')
    print(f'OK: JVM source union, two selectors and {sum(map(len, groups))} complete check and run cases')


def selftest():
    import run as harness
    groups = plan()
    identity = dict(commit='a' * 40, inputs='b' * 64, producer='c' * 64, plan='d' * 64)
    rows = []
    for index, names in enumerate(groups, 1):
        cases, embedded = baseline_cases(names)
        completed = dict(mutants=[dict(name=n, compiler_built=True, owning_test_failed=True) for n in names],
                         tests=baseline_tests(), subwitness=True, cases=cases, embedded=embedded)
        rows.append(receipt(index, completed, identity))
    for kind, position in [('cases', 0), ('embedded', 1)]:
        old = [baseline_cases(list(harness.MUTATIONS)[i::2])[position] for i in range(2)]
        assert Counter(c for r in rows for c in r[kind]) == Counter(c for group in old for c in group)
    controls = [
        ('schema', lambda r: r[0].update(schema=0)),
        ('number', lambda r: r[0].update(shard=3)),
        ('count', lambda r: r[0].update(shards=2)),
        ('input', lambda r: r[0]['identity'].update(inputs='x' * 64)),
        ('producer', lambda r: r[0]['identity'].update(producer='x' * 64)),
        ('plan', lambda r: r[0]['identity'].update(plan='x' * 64)),
        ('missing mutant', lambda r: r[0]['mutants'].pop()),
        ('duplicate mutant', lambda r: r[0]['mutants'].append(r[0]['mutants'][0])),
        ('unbuilt mutant', lambda r: r[0]['mutants'][0].update(compiler_built=False)),
        ('missing owner', lambda r: r[0]['mutants'][0].update(owning_test_failed=False)),
        ('ordinary tests', lambda r: r[0]['tests'].pop()),
        ('subwitness', lambda r: r[0].update(subwitness=False)),
        ('case baseline', lambda r: r[0]['cases'].pop()),
        ('embedded baseline', lambda r: r[0]['embedded'].pop()),
        ('missing selector', lambda r: r.pop()),
        ('duplicate selector', lambda r: r.append(r[0])),
    ]
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        def write(values):
            for path in directory.glob('capture-controls-*.json'):
                path.unlink()
            for i, row in enumerate(values):
                (directory / f'capture-controls-{i}.json').write_text(json.dumps(row))
        write(rows)
        check(directory, identity)
        for label, mutate in controls:
            broken = copy.deepcopy(rows)
            mutate(broken)
            write(broken)
            try:
                check(directory, identity)
            except ValueError:
                print('PASS rejected ' + label)
            else:
                raise AssertionError('Accepted ' + label)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        for name in ['run.py', 'golden.expected']:
            (root / name).write_text('original\n')
        for args in [['init', '-q'], ['add', '.'],
                     ['-c', 'core.hooksPath=/dev/null', '-c', 'user.name=Fixture',
                      '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                      'commit', '-qm', 'Fixture']]:
            subprocess.run(['git', *args], cwd=root, capture_output=True, check=True)
        original = input_identity(root)
        for name in ['run.py', 'golden.expected']:
            (root / name).write_text('changed\n')
            changed = input_identity(root)
            assert original['commit'] == changed['commit'] and original['inputs'] != changed['inputs']
            (root / name).write_text('original\n')
        (root / 'run.py').chmod(0o755)
        assert input_identity(root)['inputs'] != original['inputs']
    print('OK: Capture selectors, 16 receipt refusals and three dirty input controls, no compiler builds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--self-test', action='store_true')
    mode.add_argument('--check-coverage', action='store_true')
    mode.add_argument('--check-calls', action='store_true')
    parser.add_argument('--coverage-dir', type=Path)
    args = parser.parse_args()
    if args.self_test:
        selftest()
    else:
        if args.coverage_dir is None:
            parser.error('--coverage-dir is required')
        start = time.monotonic()
        if args.check_calls:
            check_calls(args.coverage_dir)
        else:
            check(args.coverage_dir)
        print('CAPTURE_CONTROL ' + json.dumps(dict(phase='union', seconds=time.monotonic() - start)))


if __name__ == '__main__':
    main()
