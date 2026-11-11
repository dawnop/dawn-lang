#!/usr/bin/env python3
"""Select whole diagnostic cases and require their complete successful union."""
import argparse
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAN = HERE / 'case-plan.json'
BITWISE_MUTANTS = ['int-trait', 'amount-subject', 'opaque-inherit', 'effect-forward',
                   'narrow-logical', 'negative-count', 'unsigned-right', 'c-truncation']
BITWISE_VALUES = ['tileinterp: 28 shared rows, 2156 integer expectations, both UB modes',
                  'tileref: 28 shared rows, 2156 integer expectations'] + [
    f'{name} {cc} {opt} UBSan: exact oracle, empty stderr'
    for name in ['bitwise_fixed', 'int_edges']
    for cc in ['gcc', 'clang'] for opt in ['-O0', '-O2']]


def bitwise_result(text):
    result = dict(mutants=re.findall(r'^PASS mutant (\S+): compiler built, owning check red$', text, re.M),
                  values=[line[5:] for line in text.splitlines() if line.startswith(
                      ('PASS tileinterp:', 'PASS tileref:', 'PASS bitwise_fixed ', 'PASS int_edges '))])
    if (result != dict(mutants=BITWISE_MUTANTS, values=BITWISE_VALUES) or
            text.splitlines().count('OK: bitwise closeout contract') != 1):
        raise ValueError('Incomplete or repeated bitwise values, mutants or closeout')
    return result


def expected_bitwise(index):
    return dict(mutants=BITWISE_MUTANTS, values=BITWISE_VALUES) if index == 0 else None


def registry():
    targets = list(sorted((HERE / 'cases').glob('*.dawn')))
    for directory in sorted((HERE / 'cases').glob('*.d')):
        if not (directory / 'entry.dawn').is_file():
            raise ValueError(f'Multi-module case has no entry.dawn: {directory.name}')
        targets.append(directory / 'entry.dawn')
    result = {}
    for path in targets:
        name = path.parent.stem if path.name == 'entry.dawn' else path.stem
        if name in result or not (HERE / 'cases' / (name + '.expected')).is_file():
            raise ValueError(f'Duplicate case or missing golden: {name}')
        result[name] = str(path.relative_to(ROOT))
    if not result:
        raise ValueError('Empty checker corpus registry')
    return result


def read_plan(path, total):
    plan = json.loads(path.read_text())
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'shards'} or
            type(plan['schema']) is not int or plan['schema'] != 1):
        raise ValueError('Invalid checker selector plan schema')
    shards = plan['shards']
    if (type(total) is not int or total != 2 or not isinstance(shards, list) or
            len(shards) != total):
        raise ValueError('Checker plan requires exactly two selectors')
    if any(not isinstance(shard, list) or not shard or
           any(not isinstance(name, str) for name in shard) for shard in shards):
        raise ValueError('Checker selectors must be nonempty lists')
    if collections.Counter(name for shard in shards for name in shard) != collections.Counter(registry().keys()):
        raise ValueError('Checker selectors omit, repeat or invent cases')
    return shards


def input_identity(plan):
    # HEAD alone cannot authorize dirty inputs or a changed producer.
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    paths += [str(Path(__file__).relative_to(ROOT)), str(plan.resolve().relative_to(ROOT))]
    digest = hashlib.sha256()
    for name in sorted(set(filter(None, paths))):
        path = ROOT / name
        mode = b'120000' if path.is_symlink() else b'100755' if path.stat().st_mode & 0o111 else b'100644'
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        digest.update(name.encode() + b'\0' + mode + b'\0' + content + b'\0')
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'inputs': digest.hexdigest(), 'plan': hashlib.sha256(plan.read_bytes()).hexdigest()}


def receipt(index, total, ran, bitwise, identity):
    return dict(schema=2, shard=index, shards=total, ran=ran, bitwise=bitwise, identity=identity)


def validate(row, shards, identity):
    if not isinstance(row, dict) or set(row) != {'schema', 'shard', 'shards', 'ran', 'bitwise', 'identity'}:
        raise ValueError('Invalid checker coverage receipt schema')
    index = row['shard']
    if (type(row['schema']) is not int or row['schema'] != 2 or type(index) is not int or
            not 0 <= index < len(shards) or type(row['shards']) is not int or
            row['shards'] != len(shards)):
        raise ValueError('Wrong checker selector number or count')
    if row['identity'] != identity:
        raise ValueError('Wrong checker input, producer or plan identity')
    if row['ran'] != shards[index]:
        raise ValueError('Checker completion differs from its complete selector')
    if row['bitwise'] != expected_bitwise(index):
        raise ValueError('Missing or repeated bitwise values or compiling mutants')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def check(directory, shards, identity):
    records = [json.loads(path.read_text()) for path in sorted(directory.rglob('checker-selector-*.json'))]
    for row in records:
        validate(row, shards, identity)
    if collections.Counter(row['shard'] for row in records) != collections.Counter(range(len(shards))):
        raise ValueError('Missing or repeated checker selector')
    if collections.Counter(name for row in records for name in row['ran']) != collections.Counter(registry().keys()):
        raise ValueError('Incomplete checker corpus union')
    print(f'OK: complete checker union, {len(shards)} selectors, {len(registry())} cases and one complete bitwise contract')


def prepare(index, shards, plan, state):
    write_json(state / 'prepared.json', receipt(index, len(shards), shards[index], expected_bitwise(index), input_identity(plan)))
    print(f'OK: checker selector {index} prepared, {len(shards[index])} complete cases and current input identity')


def run(index, shards, plan, state):
    prepared = json.loads((state / 'prepared.json').read_text())
    # Full input hashing belongs to the explicit prepare and receipt steps.
    validate(prepared, shards, prepared['identity'])
    if prepared['shard'] != index:
        raise ValueError('Prepared checker selector differs from the requested selector')
    targets = registry()
    with tempfile.TemporaryDirectory(prefix='checker-selector-') as temp:
        directory = Path(temp)
        cases = directory / 'cases'
        completed = directory / 'completed'
        bitwise_log = directory / 'bitwise.log'
        cases.write_text(''.join(targets[name] + '\n' for name in shards[index]))
        env = dict(os.environ, CHECKER_CORPUS_CASES=str(cases), CHECKER_CORPUS_COMPLETED=str(completed),
                   CHECKER_CORPUS_SELECTOR=str(index), CHECKER_CORPUS_BITWISE_LOG=str(bitwise_log))
        print(f'CONTROL checker selector {index} entry verified', flush=True)
        subprocess.run(['bash', str(HERE / 'run.sh'), '--execute-selector'], cwd=ROOT, env=env, check=True)
        actual = completed.read_text().splitlines()
        expected = shards[index] + (['@bitwise'] if index == 0 else [])
        if actual != expected:
            raise ValueError('Executed checker cases or bitwise contract differ from the selector')
        bitwise = bitwise_result(bitwise_log.read_text()) if index == 0 else None
        write_json(state / 'completed.json', receipt(index, len(shards), actual[:len(shards[index])],
                                                   bitwise, prepared['identity']))
    print(f'OK: checker selector {index} completed after cleanup, {len(shards[index])} cases', flush=True)


def record(index, shards, plan, state, coverage):
    row = json.loads((state / 'completed.json').read_text())
    validate(row, shards, input_identity(plan))
    if row['shard'] != index:
        raise ValueError('Completed checker selector differs from the requested selector')
    write_json(coverage / f'checker-selector-{index}.json', row)
    print(f'OK: checker selector {index} receipt verified against current inputs')


def selftest():
    shards = read_plan(PLAN, 2)
    identity = {'commit': 'a' * 40, 'inputs': 'b' * 64, 'plan': 'c' * 64}
    base = [receipt(i, 2, names, expected_bitwise(i), identity) for i, names in enumerate(shards)]
    with tempfile.TemporaryDirectory(prefix='checker-coverage-test-') as temp:
        root = Path(temp)
        def verify(records):
            for path in root.glob('*.json'):
                path.unlink()
            for i, row in enumerate(records):
                (root / f'checker-selector-{i}.json').write_text(json.dumps(row))
            check(root, shards, identity)
        verify(base)
        controls = {'missing selector': base[:-1], 'repeated selector': [*base, base[0]]}
        for label, field, value in [
                ('wrong number', 'shard', 2), ('wrong count', 'shards', 3),
                ('boolean number', 'shard', True), ('boolean count', 'shards', True),
                ('wrong input', 'identity', dict(identity, commit='d' * 40)),
                ('wrong producer', 'identity', dict(identity, inputs='e' * 64)),
                ('wrong plan', 'identity', dict(identity, plan='f' * 64)),
                ('missing case', 'ran', base[0]['ran'][:-1]),
                ('repeated case', 'ran', [*base[0]['ran'], base[0]['ran'][0]]),
                ('wrong order', 'ran', list(reversed(base[0]['ran']))),
                ('missing bitwise', 'bitwise', None), ('boolean bitwise', 'bitwise', True),
                ('missing mutant', 'bitwise', dict(mutants=BITWISE_MUTANTS[:-1], values=BITWISE_VALUES)),
                ('repeated mutant', 'bitwise', dict(mutants=BITWISE_MUTANTS + BITWISE_MUTANTS[:1], values=BITWISE_VALUES)),
                ('missing values', 'bitwise', dict(mutants=BITWISE_MUTANTS, values=BITWISE_VALUES[:-1]))]:
            rows = copy.deepcopy(base)
            rows[0][field] = value
            controls[label] = rows
        rows = copy.deepcopy(base)
        rows[1]['bitwise'] = expected_bitwise(0)
        controls['repeated bitwise'] = rows
        for label, rows in controls.items():
            try:
                verify(rows)
            except ValueError:
                continue
            raise RuntimeError('Checker coverage accepted ' + label)
        bad_plans = [shards[:-1], [[], shards[1]],
                     [[*shards[0], shards[1][0]], shards[1]],
                     [shards[0][:-1], shards[1]], [['unknown'], shards[1]]]
        path = root / 'plan.json'
        for bad in bad_plans:
            path.write_text(json.dumps(dict(schema=1, shards=bad)))
            try:
                read_plan(path, 2)
            except ValueError:
                continue
            raise RuntimeError('Checker selector accepted an invalid plan')
        written = root / 'exclusive.json'
        write_json(written, base[0])
        try:
            write_json(written, base[0])
        except FileExistsError:
            pass
        else:
            raise RuntimeError('Checker receipt allowed a second producer')
    fixture = ['PASS ' + value for value in BITWISE_VALUES] + [
        f'PASS mutant {name}: compiler built, owning check red' for name in BITWISE_MUTANTS]
    fixture.append('OK: bitwise closeout contract')
    bitwise_result('\n'.join(fixture))
    for bad in [fixture[:-1], fixture[1:], fixture[:-2] + fixture[-1:], fixture + fixture[-2:-1]]:
        try:
            bitwise_result('\n'.join(bad))
        except ValueError:
            continue
        raise RuntimeError('Checker coverage accepted an incomplete bitwise transcript fixture')
    print(f'OK: checker coverage refused {len(controls)} receipt and {len(bad_plans)} plan controls; duplicate write and four transcript controls refused; no compiler executed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', type=int, default=2)
    parser.add_argument('--shard', type=int)
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--state-dir', type=Path)
    parser.add_argument('--coverage-dir', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--check-shards', action='store_true')
    modes.add_argument('--check-coverage', action='store_true')
    modes.add_argument('--prepare-selector', action='store_true')
    modes.add_argument('--write-receipt', action='store_true')
    modes.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    try:
        if args.self_test:
            selftest()
            return
        shards = read_plan(args.plan, args.shards)
        if args.check_shards:
            for i, names in enumerate(shards):
                print(f'checker selector {i}: ' + ', '.join(names))
            return
        if args.check_coverage:
            if args.coverage_dir is None:
                parser.error('--check-coverage requires --coverage-dir')
            check(args.coverage_dir, shards, input_identity(args.plan))
            return
        if args.shard is None or not 0 <= args.shard < len(shards) or args.state_dir is None:
            parser.error('execution requires an in-range --shard and --state-dir')
        if args.prepare_selector:
            prepare(args.shard, shards, args.plan, args.state_dir)
        elif args.write_receipt:
            if args.coverage_dir is None:
                parser.error('--write-receipt requires --coverage-dir')
            record(args.shard, shards, args.plan, args.state_dir, args.coverage_dir)
        else:
            run(args.shard, shards, args.plan, args.state_dir)
    except (ValueError, TypeError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
