#!/usr/bin/env python3
"""Run complete playground sessions and verify their successful coverage union.

The main HTTP sequence retains its own cold start, request order and cleanup.
Independent child contracts remain whole. Completion records come from the
shell after each group succeeds; receipts follow the shell's EXIT cleanup.
"""
import argparse
import collections
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PLAN = HERE / 'contract-plan.json'
GROUPS = ('lsp-session', 'c-http-sentinel', 'complete-c-mutant-matrix',
          'complete-tile-probe-session', 'main-http-session-including-cleanup')


def read_plan(path, total):
    plan = json.loads(path.read_text())
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'shards'} or
            type(plan['schema']) is not int or plan['schema'] != 1):
        raise ValueError('Invalid playground selector plan schema')
    shards = plan['shards']
    if type(total) is not int or total != 2 or not isinstance(shards, list) or len(shards) != total:
        raise ValueError('Playground plan requires exactly two selectors')
    if any(not isinstance(shard, list) or not shard or
           any(not isinstance(name, str) for name in shard) for shard in shards):
        raise ValueError('Playground selectors must be nonempty lists')
    if collections.Counter(name for shard in shards for name in shard) != collections.Counter(GROUPS):
        raise ValueError('Playground selectors omit, repeat or invent complete groups')
    return shards


def input_identity(plan):
    # Include actual tracked bytes, not just HEAD: a dirty producer cannot
    # donate a receipt to a clean checkout with the same commit name.
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    digest = hashlib.sha256()
    for name in sorted(filter(None, paths)):
        path = ROOT / name
        content = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        digest.update(name.encode() + b'\0' + content + b'\0')
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                             text=True).strip(),
            'inputs': digest.hexdigest(), 'plan': hashlib.sha256(plan.read_bytes()).hexdigest()}


def receipt(index, total, ran, identity):
    return dict(schema=1, shard=index, shards=total, ran=ran, identity=identity)


def record(directory, index, total, ran, identity):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f'playground-selector-{index}.json').open('x') as stream:
        json.dump(receipt(index, total, ran, identity), stream, indent=2)
        stream.write('\n')


def check(directory, shards, identity):
    records = [json.loads(path.read_text()) for path in sorted(
        directory.rglob('playground-selector-*.json'))]
    indices = []
    covered = []
    for row in records:
        if not isinstance(row, dict) or set(row) != {'schema', 'shard', 'shards', 'ran', 'identity'}:
            raise ValueError('Invalid playground coverage receipt schema')
        index = row['shard']
        if (type(row['schema']) is not int or row['schema'] != 1 or type(index) is not int or
                not 0 <= index < len(shards) or type(row['shards']) is not int or
                row['shards'] != len(shards)):
            raise ValueError('Wrong playground selector number or count')
        if row['identity'] != identity:
            raise ValueError('Wrong playground input, producer or plan identity')
        if row['ran'] != shards[index]:
            raise ValueError('Playground receipt differs from its complete selector')
        indices.append(index)
        covered.extend(row['ran'])
    if collections.Counter(indices) != collections.Counter(range(len(shards))):
        raise ValueError('Missing or repeated playground selector')
    if collections.Counter(covered) != collections.Counter(GROUPS):
        raise ValueError('Incomplete playground coverage union')
    print(f'OK: complete playground union, {len(shards)} selectors and {len(covered)} complete groups')


def run_groups(groups, index, total, plan, coverage):
    identity = input_identity(plan)
    with tempfile.TemporaryDirectory(prefix='playground-selector-') as temp:
        log = Path(temp) / 'completed'
        env = dict(os.environ, PLAY_CONTRACT_GROUPS=' '.join(groups),
                   PLAY_CONTRACT_GROUP_LOG=str(log))
        subprocess.run(['sh', str(HERE / 'contract.sh'), '--execute-selector'],
                       cwd=ROOT, env=env, check=True)
        ran = log.read_text().splitlines()
        if ran != groups:
            raise ValueError('Executed playground groups differ from the selector')
        if input_identity(plan) != identity:
            raise ValueError('Playground inputs changed during execution')
        if coverage is not None:
            record(coverage, index, total, ran, identity)
    print('OK: playground selector completed after session cleanup: ' + ', '.join(ran))


def selftest():
    shards = read_plan(PLAN, 2)
    identity = {'commit': 'a' * 40, 'inputs': 'b' * 64, 'plan': 'c' * 64}
    base = [receipt(i, len(shards), group, identity) for i, group in enumerate(shards)]
    with tempfile.TemporaryDirectory(prefix='playground-coverage-test-') as temp:
        root = Path(temp)
        def verify(records):
            for path in root.glob('*.json'):
                path.unlink()
            for i, row in enumerate(records):
                (root / f'playground-selector-{i}.json').write_text(json.dumps(row))
            check(root, shards, identity)
        verify(base)
        controls = {'missing selector': base[:-1], 'repeated selector': [*base, base[0]]}
        for label, field, value in [
                ('wrong number', 'shard', 2), ('wrong count', 'shards', 3),
                ('boolean number', 'shard', True), ('boolean count', 'shards', True),
                ('wrong input', 'identity', dict(identity, commit='d' * 40)),
                ('wrong producer', 'identity', dict(identity, inputs='e' * 64)),
                ('wrong plan', 'identity', dict(identity, plan='f' * 64)),
                ('missing mutant matrix', 'ran', [g for g in base[0]['ran'] if g != 'complete-c-mutant-matrix']),
                ('repeated group', 'ran', [*base[0]['ran'], base[0]['ran'][0]]),
                ('wrong group order', 'ran', list(reversed(base[0]['ran'])))]:
            rows = copy.deepcopy(base)
            rows[0][field] = value
            controls[label] = rows
        for label, rows in controls.items():
            try:
                verify(rows)
            except ValueError:
                continue
            raise RuntimeError('Playground coverage accepted ' + label)
        bad_plans = [shards[:-1], [[], *shards[1:]],
                     [[*shards[0], shards[1][0]], *shards[1:]],
                     [shards[0][:-1], *shards[1:]], [['unknown'], *shards[1:]]]
        plan = root / 'plan.json'
        for bad in bad_plans:
            plan.write_text(json.dumps(dict(schema=1, shards=bad)))
            try:
                read_plan(plan, 2)
            except ValueError:
                continue
            raise RuntimeError('Playground selector accepted an invalid plan')
        # A second producer must never overwrite an already successful receipt.
        for path in root.glob('*.json'):
            path.unlink()
        record(root, 0, 2, shards[0], identity)
        try:
            record(root, 0, 2, shards[0], identity)
        except FileExistsError:
            pass
        else:
            raise RuntimeError('Playground receipt allowed a second producer')
    print(f'OK: playground coverage refused {len(controls)} receipt and {len(bad_plans)} plan controls; duplicate write refused')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', type=int, default=2)
    parser.add_argument('--shard', type=int)
    parser.add_argument('--plan', type=Path, default=PLAN)
    parser.add_argument('--check-shards', action='store_true')
    parser.add_argument('--check-coverage', action='store_true')
    parser.add_argument('--coverage-dir', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    try:
        if args.self_test:
            selftest()
            return
        shards = read_plan(args.plan, args.shards)
        if args.check_shards:
            for i, groups in enumerate(shards):
                print(f'playground selector {i}: ' + ', '.join(groups))
            return
        if args.check_coverage:
            if args.coverage_dir is None:
                parser.error('--check-coverage requires --coverage-dir')
            check(args.coverage_dir, shards, input_identity(args.plan))
            return
        if args.shard is None:
            if args.coverage_dir is not None or os.environ.get('PLAY_CONTRACT_COVERAGE_DIR'):
                parser.error('a coverage receipt requires --shard')
            run_groups(list(GROUPS), None, None, args.plan, None)
        else:
            if not 0 <= args.shard < len(shards):
                parser.error('playground selector number outside plan')
            coverage = args.coverage_dir or os.environ.get('PLAY_CONTRACT_COVERAGE_DIR')
            run_groups(shards[args.shard], args.shard, len(shards), args.plan,
                       Path(coverage) if coverage else None)
    except (ValueError, TypeError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
