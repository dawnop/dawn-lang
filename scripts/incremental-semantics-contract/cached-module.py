#!/usr/bin/env python3
"""Pin the real cached driver transition with compiling assertion controls.

Mutations touch private copies only. A linkage failure, panic, or failed
compilation is never accepted as evidence that the owning assertion fired.
"""
import argparse
import re
import shlex
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def owning_failure(status, output, module, owner):
    failure = re.compile(r'^FAIL\s+' + re.escape(module) + ' :: ' + re.escape(owner) +
                         r'\n\s+assertion failed:', re.M)
    invalid = re.search(r'^error:|Exception in thread|LinkageError|NoSuchMethodError|'
                        r'NoClassDefFoundError|VerifyError|\bpanic:', output, re.M)
    return bool(status and failure.search(output) and not invalid)


def partition(controls, shards, shard):
    if shards < 1 or shards > len(controls) or shard < 0 or shard >= shards:
        raise ValueError('require 1 <= shards <= selected controls and 0 <= shard < shards')
    return [control for index, control in enumerate(controls) if index % shards == shard]


def with_positive(source, controls, name='positive'):
    return [(name, source, None)] + controls


def variants():
    transition = 'cached module transitions renew bodies and publish the current carry'
    comptime = 'cached module transitions recompute comptime and recover from evaluation errors'
    return [
        ('disable-reuse', 'if data.scope == scope { Some(data.admitted) } else { None }',
         'if false { Some(data.admitted) } else { None }', transition),
        ('ignore-owner', 'if data.scope == scope { Some(data.admitted) } else { None }',
         'if true { Some(data.admitted) } else { None }', transition),
        ('ignore-source-binding', 'Some(parsed) -> source_snapshot.resolved(parsed, mf.m)',
         'Some(parsed) -> Some(parsed)', transition),
        ('retain-error-cache', 'if diags != [] {\n    body_cache = None',
         'if false {\n    body_cache = None', comptime),
        ('skip-warm-comptime', 'if len(cx.diags) == 0 {\n      analysis_event',
         'if len(cx.diags) == 0 && previous == None {\n      analysis_event', comptime),
        ('stale-export-carry', 'after: AnalysisCarry { exports: exports, impls: impls,',
         'after: AnalysisCarry { exports: if cache_bodies { before.exports } else { exports }, impls: impls,', transition),
    ]


def workflow_inventory(controls, observers, parser, text):
    names = []
    for flags in re.findall(
            r'^\s*(?:run:\s*)?python3 scripts/incremental-semantics-contract/cached-module\.py([^\n]*)$',
            text, re.M):
        args = parser.parse_args(shlex.split(flags))
        if args.self_test:
            continue
        assert (args.shards is None) == (args.shard is None)
        assert args.shards is None or args.suite == 'driver'
        assert not args.only or args.suite != 'observer'
        if args.suite in ('driver', 'all'):
            selected = [item for item in controls if not args.only or item[0] in args.only]
            if args.shards is not None:
                selected = partition(selected, args.shards, args.shard)
            names.extend(item[0] for item in selected)
        if args.suite in ('observer', 'all'):
            names.extend(item[0] for item in observers)
    assert sorted(names) == sorted(item[0] for item in controls + observers), 'workflow loses or duplicates module controls'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=[v[0] for v in variants()], action='append')
    parser.add_argument('--suite', choices=['driver', 'observer', 'all'], default='all')
    parser.add_argument('--shards', type=int)
    parser.add_argument('--shard', type=int)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.only and args.suite == 'observer':
        parser.error('--only selects driver controls, not observer controls')
    if (args.shards is None) != (args.shard is None):
        parser.error('--shards and --shard must be supplied together')
    if args.shards is not None and args.suite != 'driver':
        parser.error('sharding requires --suite driver; run the observer suite independently')
    source = (ROOT / 'selfhost/src/driver/analyze.dawn').read_text()
    controls = [(name, edit(source, old, new), owner) for name, old, new, owner in variants()]
    observer_owner = 'cached module observer order and current Java oracle survive warm hits'
    observers = [
        ('omit-check-exit', edit(source,
         '    analysis_event(observer, mf.mod_path, AnalyzeCheck, false)',
         '    analysis_event(None, mf.mod_path, AnalyzeCheck, false)'), observer_owner),
        ('replace-host-oracle', edit(source, '    jsig: js\n',
         '    jsig: jsig_refused()\n'), observer_owner),
    ]
    if args.self_test:
        parts = [partition(controls, 3, shard) for shard in range(3)]
        assert [len(part) for part in parts] == [2, 2, 2]
        names = [item[0] for part in parts for item in part] + [item[0] for item in observers]
        assert len(names) == len(set(names)) == 8
        assert set(names) == {item[0] for item in controls + observers}
        for part in parts + [observers]:
            subjects = with_positive(source, part)
            assert subjects[0] == ('positive', source, None)
            assert subjects[1:] == part and len(subjects) == len(part) + 1
        for shards, shard in [(0, 0), (-1, 0), (8, 0), (3, -1), (3, 3)]:
            try:
                partition(controls, shards, shard)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid or empty shard accepted')
        good = 'FAIL  driver/analyze :: owner\n  assertion failed: expected\n'
        assert owning_failure(1, good, 'driver/analyze', 'owner')
        for status, output in [(0, good), (1, good.replace('owner', 'another')),
                               (1, good.replace('assertion failed:', 'panic:'))] + [
                                   (1, good + text) for text in
                                   ['error: compile failure', 'java.lang.LinkageError',
                                    'NoSuchMethodError', 'NoClassDefFoundError',
                                    'VerifyError', 'Exception in thread', 'panic: failed']]:
            assert not owning_failure(status, output, 'driver/analyze', 'owner')
        workflow_inventory(controls, observers, parser, (ROOT / '.github/workflows/gates.yml').read_text())
        command = 'python3 scripts/incremental-semantics-contract/cached-module.py'
        workflow_inventory(controls, observers, parser, command + '\n')
        for broken in ['', command + '\n' + command + '\n', command + ' --suite driver\n',
                       command + ' --suite observer\n']:
            try:
                workflow_inventory(controls, observers, parser, broken)
            except AssertionError:
                pass
            else:
                raise AssertionError('accepted missing or duplicate workflow controls')
        print(f'OK: {len(controls) + len(observers)} unique cached-module mutation anchors and exact workflow coverage')
        return
    selected = [c for c in controls if not args.only or c[0] in args.only]
    if args.shards is not None:
        try:
            selected = partition(selected, args.shards, args.shard)
        except ValueError as error:
            parser.error(str(error))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dawn-cached-module-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        target = root / 'selfhost/src/driver/analyze.dawn'
        # The observer tests are a module of the compiler package, copied with it.
        observer_target = root / 'selfhost/src/contract/cached_module_observer.dawn'
        subjects = []
        if args.suite in ('driver', 'all'):
            subjects += [(name, text, owner, target, 'driver/analyze')
                         for name, text, owner in with_positive(source, selected)]
        if args.suite in ('observer', 'all'):
            subjects += [(name, text, owner, observer_target, 'contract/cached_module_observer')
                         for name, text, owner in with_positive(source, observers, 'observer-positive')]
        for name, text, owner, test_target, module in subjects:
            target.write_text(text)
            before = time.monotonic()
            status, output = run('test', test_target)
            if owner is None:
                expected = ({control[2] for control in selected} if module == 'driver/analyze'
                            else {observer_owner})
                if status or 'test(s) passed' not in output or not all(
                        re.search(r'^PASS\s+' + re.escape(module) + r' :: ' + re.escape(test) + r'$',
                                  output, re.M) for test in expected):
                    raise RuntimeError('Cached-module positive failed\n' + output)
            else:
                if not owning_failure(status, output, module, owner):
                    raise RuntimeError(name + ' did not compile and reach its owning assertion\n' + output)
            print(f'OK: cached-module {name}; elapsed={time.monotonic()-before:.2f}s', flush=True)
    count = sum(owner is not None for _, _, owner, _, _ in subjects)
    print(f'OK: {count} compiling cached-module controls; elapsed={time.monotonic()-started:.2f}s')


if __name__ == '__main__':
    main()
