#!/usr/bin/env python3
"""Explicit K4 fixtures, real controls, temporary transactions and independent dual-chain probes."""

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from native_seed import cold, cold_audit, contract as c, qualification as q, rehearsal as t
from native_seed import package


def transactions(destination, first, second, evidence, rollback_check=None):
    destination = cold.new_directory(destination)
    rows = []
    # Tags are simulated versions, intentionally distinct from the actual artifacts' version.
    for checkpoint in ('after-objects', 'before-commit', 'after-commit'):
        for fault in ('exception', 'SIGTERM', 'SIGKILL'):
            directory = destination / (checkpoint + '-' + fault)
            initial = t.initialize(directory, first, evidence, 'v1.0.0')
            parent = c.digest(c.canonical(initial))
            pid = os.fork()
            if pid == 0:
                def inject(at):
                    if at == checkpoint:
                        if fault == 'exception':
                            raise RuntimeError('injected transaction interruption')
                        os.kill(os.getpid(), getattr(signal, fault))
                try:
                    t.transition(directory, parent, 'advance', second, evidence, 'v1.1.0',
                                 'simulated release advancement', inject)
                except RuntimeError:
                    os._exit(73)
                os._exit(0)
            observed = set()
            while True:
                observed.add(t.read(directory)['sequence'])
                ended, status = os.waitpid(pid, os.WNOHANG)
                if ended:
                    break
                time.sleep(0.001)
            c.require(observed <= {0, 1}, 'transaction-test', 'reader observed a partial lock')
            expected_status = 73 if fault == 'exception' else -getattr(signal, fault)
            c.require(os.waitstatus_to_exitcode(status) == expected_status,
                      'transaction-test', 'worker failed for an unowned reason')
            current = t.read(directory)
            committed = checkpoint == 'after-commit'
            c.require(current['sequence'] == int(committed) and
                      t.select(directory, current['active']['artifact_sha256']) == (second if committed else first),
                      'transaction-test', 'partial or incorrect commit observed')
            if not committed:
                current = t.transition(directory, parent, 'advance', second, evidence, 'v1.1.0', 'explicit retry')
            rows.append(q.refused(f'{checkpoint}-{fault}-stale-retry', 'transaction-parent',
                        lambda: t.transition(directory, parent, 'advance', second, evidence, 'v1.1.0', 'stale retry')))
            c.require(current['sequence'] == 1, 'transaction-test', 'retry advanced twice')
            parent = c.digest(c.canonical(current))
            rows.append(q.refused('normal-version-regression', 'transaction-version',
                        lambda: t.transition(directory, parent, 'advance', first, evidence, 'v1.0.0', 'regression')))
            compat = dict(evidence, compatible_artifact_sha256=c.digest(first))
            rows.append(q.refused('rollback-without-compatibility', 'transaction-compatibility',
                        lambda: t.transition(directory, parent, 'rollback', first, evidence, 'v1.0.0', 'reviewed')))
            rows.append(q.refused('rollback-without-reason', 'transaction-reason',
                        lambda: t.transition(directory, parent, 'rollback', first, compat, 'v1.0.0', '')))
            current = t.transition(directory, parent, 'rollback', first, compat, 'v1.0.0',
                                   'reviewed rollback with current-source compatibility')
            c.require(t.select(directory, c.digest(first)) == first and current['high_water'] == 'v1.1.0',
                      'transaction-test', 'rollback lost old bytes or lowered high water')
            if rollback_check:
                rollback_check(t.select(directory, c.digest(first)))
            current = t.transition(directory, c.digest(c.canonical(current)), 'revoke', second,
                                   evidence, 'v1.1.0', 'revoke the suspect retained identity')
            rows.append(q.refused('revoked-cache-selection', 'transaction-revoked',
                                  lambda: t.select(directory, c.digest(second))))
            parent = c.digest(c.canonical(current))
            rows.append(q.refused('revoked-reentry', 'transaction-revoked',
                        lambda: t.transition(directory, parent, 'advance', second, evidence, 'v1.2.0', 'reentry')))
            rows.append(q.refused('rehearsal-is-not-product-lock', 'schema',
                                  lambda: c.read_lock(directory / 'lock.json')))
            rows.append({'name': checkpoint + '-' + fault, 'interruption_exit': expected_status,
                         'committed_before_interruption': committed, 'final_sequence': current['sequence'],
                         'observed_sequences': sorted(observed),
                         'lineage_sha256': c.digest(c.canonical(current)),
                         'active_sha256': c.digest(first), 'revoked_sha256': c.digest(second)})
    c.atomic_json(destination / 'results.json', {'schema': 1, 'kind': 'native-transaction-controls',
                  'simulated_versions': True, 'source_commit': evidence['source_commit'], 'controls': rows})
    return rows


def fixtures(destination):
    destination = cold.new_directory(destination)
    directory = cold.new_directory(destination / 'observer')
    (directory / 'trace.10').write_text(
        'execve("/probe", ["/probe"], 0x1 /* 0 vars */) = 0\n'
        'openat(AT_FDCWD</out>, "/outside/cache.o", O_RDONLY) = 3</outside/cache.o>\n'
        '+++ exited with 0 +++\n')

    def audit():
        return cold_audit.audit(directory, ['/probe'], {'/probe': '0' * 64}, ('/out',))

    rows = [q.refused('outside-cache-read', 'audit-read', audit)]
    original = c.require

    def disabled_read_guard(ok, code, detail):
        if code != 'audit-read':
            original(ok, code, detail)

    # Disable the owned rule deliberately. The outer harness must catch the lost refusal.
    c.require = disabled_read_guard
    try:
        rows.append(q.refused('removed-rule-is-detected', 'control-missed',
                              lambda: q.refused('cache-canary', 'audit-read', audit)))
    finally:
        c.require = original
    (directory / 'trace.10').write_text(
        'execve("/probe/java", ["/probe/java"], 0x1 /* 0 vars */) = 0\n'
        '+++ exited with 0 +++\n')
    def java_audit():
        return cold_audit.audit(directory, ['/probe/java'], {'/probe/java': '0' * 64}, ('/out',))
    rows.append(q.refused('java-exec', 'audit-java', java_audit))
    def disabled_java_guard(ok, code, detail):
        if code != 'audit-java':
            original(ok, code, detail)
    c.require = disabled_java_guard
    try:
        rows.append(q.refused('removed-java-rule-is-detected', 'control-missed',
                              lambda: q.refused('java-canary', 'audit-java', java_audit)))
    finally:
        c.require = original
    for name, mutate in (('schema', lambda x: x.update(schema=999)),
                         ('native-kind', lambda x: x['seed'].update(kind='jvm-jar'))):
        lock = c.read_lock(Path(__file__).parent / 'native-seed-candidate-v0.104.0.json')
        mutate(lock)
        rows.append(q.refused(name, 'schema' if name == 'schema' else 'seed-kind', lambda: c.validate_lock(lock)))
    transactions(destination / 'transactions', b'fixture seed one\n', b'fixture seed two\n',
                 {'source_commit': '1' * 40, 'kind': 'fixed-transaction-fixture'})
    c.atomic_json(destination / 'results.json', {'schema': 1, 'kind': 'native-verifier-fixtures', 'controls': rows})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('fixtures', 'real-controls', 'transactions', 'dual',
                                           'jvm-chain', 'seal', 'verify-package'))
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cold', type=Path)
    parser.add_argument('--java', type=Path)
    parser.add_argument('--jar', type=Path)
    parser.add_argument('--java26', type=Path)
    parser.add_argument('--seed-cache', type=Path)
    parser.add_argument('--commit')
    args = parser.parse_args()
    try:
        if args.command == 'fixtures':
            fixtures(args.out)
        elif args.command in ('seal', 'verify-package'):
            (package.seal if args.command == 'seal' else package.verify)(args.repo, args.out)
        elif args.command == 'jvm-chain':
            c.require(all((args.java, args.java26, args.seed_cache, args.commit)),
                      'arguments', 'both JDKs, --seed-cache and full --commit required')
            c.oid(args.commit, 'JVM source')
            package.jvm_chain(args.repo, args.out, args.java, args.java26, args.seed_cache, args.commit)
        else:
            c.require(args.cold is not None, 'arguments', '--cold is required')
            value = cold.verify(args.repo, args.cold)
            if args.command == 'real-controls':
                q.real_controls(args.repo, args.cold, args.out)
            elif args.command == 'dual':
                c.require(args.java and args.jar, 'arguments', '--java and --jar are required')
                q.dual(args.repo, args.cold, args.out, args.java, args.jar)
            else:
                lock = c.read_lock(args.cold / 'seed-lock.json')
                first = c.verify_seed(args.cold / 'inputs/seed/dawnc', lock)
                second = (args.cold / 'root-1/B/dawnc').read_bytes()
                restored_checks = []
                def rollback_check(data):
                    c.require(data == first, 'transaction-test', 'restored bytes differ')
                    c.require(c.probe_seed(data) == (lock['seed']['version'], lock['seed']['build_id']),
                              'transaction-test', 'restored seed no longer answers its exact identity')
                    restored_checks.append(c.digest(data))
                transactions(args.out, first, second,
                             {'kind': 'real-artifacts-simulated-release-transaction',
                              'source_commit': value['source_commit'],
                              'cold_receipt_sha256': c.digest(c.canonical(value)),
                              'actual_seed': lock['seed'],
                              'actual_B_sha256': c.digest(second)}, rollback_check)
                # Execute the retained bytes after rollback with the retained seed's paired std.
                restored = args.out / 'restored-seed'
                c.write_tree(restored, dict(c.scan(args.cold / 'inputs/seed'), dawnc=('100755', first)))
                output = cold.new_directory(args.out / 'rollback-smoke')
                (output / 'probe.dawn').write_text(cold.SMOKE)
                from native_seed import toolchain
                tcdir = args.cold / 'toolchain'
                tc = toolchain.verify(tcdir)
                result = cold.run_step(args.out, 'rollback-emission', tcdir, tc,
                    args.cold / 'inputs/source', restored, None, output,
                    ['/seed/dawnc', 'emitc', '--std', '/seed/std', '/out/probe.dawn', '-o', '/out/probe.c'])
                c.require(len(restored_checks) == 9 and (output / 'probe.c').stat().st_size > 0,
                          'transaction-test', 'rollback compiler emission is missing')
                c.atomic_json(args.out / 'rollback-usability.json', result)
        print('OK requested K4 qualification controls; product seed unchanged')
        return 0
    except (c.Rejected, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
