#!/usr/bin/env python3
"""Pin opaque session ownership with compiling mutations of the real driver.

Each deterministic partition starts with its own positive. Private copies keep
the shared workspace untouched; only a named assertion failure kills a mutant.
"""
import argparse
import re
import shlex
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def variants():
    generation = 'session body cache revalidates after prefix divergence and replaces generations'
    capacity = 'session body cache shares capacity with prefix representations'
    barrier = 'session body cache respects Java barriers and nonparse error recovery'
    identity = 'session body cache refuses ambiguous identities and clears errors'
    return [
        ('always-cold', 'let result = if body_allowed {', 'let result = if false {', generation),
        ('keep-old-body-map', 'var bodies: Map[BodyKey, ModuleBodyCache] = map.empty()',
         'var bodies: Map[BodyKey, ModuleBodyCache] = session.bodies', generation),
        ('ignore-canonical-prefix', '(not session.body_enabled || key.canonical_path == session.prefix[index].canonical_path)',
         'true', identity),
        ('ignore-duplicates', 'if session.body_enabled && not unambiguous(session.std, loaded) { matching = false }',
         'if false { matching = false }', identity),
        ('evict-keeps-bodies', 'State { ..session, prefix: [], bodies: map.empty() }',
         'State { ..session, prefix: [] }', generation),
        ('nonpersistent-disable', 'State { ..session, prefix: [], bodies: map.empty(), body_enabled: false,\n'
         '    max_modules: 0, max_text_units: 0, max_products: 0 }',
         'State { ..session, prefix: [], bodies: map.empty() }', generation),
        ('omit-body-module-charge', '          len(prefix) + map.len(bodies) < session.max_modules &&',
         '          len(prefix) < session.max_modules &&', capacity),
        ('omit-prefix-module-charge', '    if retaining && len(prefix) + map.len(bodies) < session.max_modules &&',
         '    if retaining && len(prefix) < session.max_modules &&', capacity),
        ('omit-body-text-charge', '          units <= session.max_text_units - text_units - body_text_units {',
         '          units <= session.max_text_units - text_units {', capacity),
        ('omit-prefix-text-charge', '      units <= session.max_text_units - text_units - body_text_units {\n'
         '        prefix = prefix ++', '      units <= session.max_text_units - body_text_units {\n'
         '        prefix = prefix ++', capacity),
        ('omit-product-budget', 'count <= session.max_products - products &&', 'true &&', capacity),
        ('ignore-error-barrier', 'if len(computed.diags) != 0 || probe.queries() != queries_before {',
         'if probe.queries() != queries_before {', barrier),
        ('ignore-java-barrier', 'if len(computed.diags) != 0 || probe.queries() != queries_before {',
         'if len(computed.diags) != 0 {', barrier),
    ]


def partition(items, count, index):
    if count < 1 or count > len(items) or index < 0 or index >= count:
        raise ValueError('require 1 <= shards <= selected controls and 0 <= shard < shards')
    return [item for position, item in enumerate(items) if position % count == index]


def subjects(source, controls):
    return [('positive', source, None)] + controls


def owning_failure(status, output, owner):
    failure = re.search(r'^FAIL\s+contract/session_bodies :: ' + re.escape(owner) +
                        r'\n\s+assertion failed:', output, re.M)
    invalid = re.search(r'^error:|Exception in thread|LinkageError|NoSuchMethodError|'
                        r'NoClassDefFoundError|VerifyError|\bpanic:', output, re.M)
    return bool(status and failure and not invalid)


def workflow_inventory(controls, parser, text):
    names = []
    for flags in re.findall(
            r'^\s*(?:run:\s*)?python3 scripts/incremental-semantics-contract/session-bodies\.py([^\n]*)$',
            text, re.M):
        args = parser.parse_args(shlex.split(flags))
        if args.self_test:
            continue
        selected = [item for item in controls if not args.only or item[0] in args.only]
        names.extend(item[0] for item in partition(selected, args.shards, args.shard))
    assert sorted(names) == sorted(item[0] for item in controls), 'workflow loses or duplicates session controls'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=[v[0] for v in variants()], action='append')
    parser.add_argument('--shards', type=int, default=1)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    source = (ROOT / 'selfhost/src/driver/incremental.dawn').read_text()
    controls = [(name, edit(source, old, new), owner) for name, old, new, owner in variants()]
    selected = [control for control in controls if not args.only or control[0] in args.only]
    try:
        selected = partition(selected, args.shards, args.shard)
    except ValueError as error:
        parser.error(str(error))
    if args.self_test:
        parts = [partition(controls, 3, i) for i in range(3)]
        names = [item[0] for part in parts for item in part]
        assert len(names) == len(set(names)) == len(controls)
        assert set(names) == {item[0] for item in controls}
        for part in parts:
            assert subjects(source, part) == [('positive', source, None)] + part
        for count, index in [(0, 0), (-1, 0), (len(controls) + 1, 0), (3, -1), (3, 3)]:
            try:
                partition(controls, count, index)
            except ValueError:
                pass
            else:
                raise AssertionError('invalid partition accepted')
        good = 'FAIL  contract/session_bodies :: owner\n  assertion failed: expected\n'
        assert owning_failure(1, good, 'owner')
        assert not owning_failure(0, good, 'owner')
        assert not owning_failure(1, good, 'other')
        for error in ['error: failed', 'panic: failed', 'LinkageError', 'NoSuchMethodError',
                      'NoClassDefFoundError', 'VerifyError', 'Exception in thread']:
            assert not owning_failure(1, good + error, 'owner')
        workflow_inventory(controls, parser, (ROOT / '.github/workflows/gates.yml').read_text())
        command = 'python3 scripts/incremental-semantics-contract/session-bodies.py'
        workflow_inventory(controls, parser, command + '\n')
        for broken in ['', command + '\n' + command + '\n', command + ' --shards 3 --shard 0\n']:
            try:
                workflow_inventory(controls, parser, broken)
            except AssertionError:
                pass
            else:
                raise AssertionError('accepted missing or duplicate workflow controls')
        print(f'OK: {len(controls)} session anchors, exact shard coverage and strict failure evidence')
        return
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='dawn-session-bodies-') as temp:
        root = Path(temp)
        for directory in ('selfhost', 'compiler-plan'):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns('build', '.dawn'))
        (root / 'packages').symlink_to(ROOT / 'packages', target_is_directory=True)
        # The tests are a module of the compiler package, copied with it.
        target = root / 'selfhost/src/contract/session_bodies.dawn'
        for name, text, owner in subjects(source, selected):
            (root / 'selfhost/src/driver/incremental.dawn').write_text(text)
            before = time.monotonic()
            status, output = run('test', target)
            if owner is None:
                if status or 'test(s) passed' not in output or not all(
                        re.search(r'^PASS\s+contract/session_bodies :: ' + re.escape(item[2]) + r'$', output, re.M)
                        for item in selected):
                    raise RuntimeError('Session positive failed\n' + output)
            elif not owning_failure(status, output, owner):
                raise RuntimeError(name + ' did not compile and reach its owning assertion\n' + output)
            print(f'OK: session-bodies {name}; elapsed={time.monotonic()-before:.2f}s', flush=True)
    print(f'OK: {len(selected)} compiling session controls; shard={args.shard}/{args.shards}; '
          f'elapsed={time.monotonic()-started:.2f}s')


if __name__ == '__main__':
    main()
