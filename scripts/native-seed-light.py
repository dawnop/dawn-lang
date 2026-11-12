#!/usr/bin/env python3
"""Push-only structural controls. No seed execution, compiler build or qualification claim."""

import argparse
import copy
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import native_seed.contract as c
import native_seed.qualification as q

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('K1', 'K2', 'K3', 'K4', 'K4-transactions')
STEPS = ('A-emit', 'A-link', 'A-plan', 'B-emit', 'B-link', 'B-plan', 'B-plan-post',
         'C-emit', 'C-link', 'C-plan', 'C-plan-post', 'smoke-build', 'smoke-run')


def check_inputs(lock, receipt, expected_source):
    c.validate_lock(lock)
    c.validate_receipt(receipt, lock)
    c.require(receipt['source'] == expected_source, 'light-input',
              'receipt does not describe the requested committed inputs')


def check_cold(receipt, chain):
    c.fields(chain, 'schema kind policy inputs_sha256 seed_lock_sha256 toolchain_sha256 source_commit source_tree recipe_sha256 orchestrator_sha256 auditor_sha256 isolation_tools roots', 'cold receipt')
    c.require(type(chain['schema']) is int and chain['schema'] == 1 and
              chain['kind'] == 'native-cold-chain' and chain['policy'] == 'native-cold-linux-x86_64-v1',
              'light-schema', 'unsupported cold receipt')
    c.require(chain['source_commit'] == receipt['source']['commit'] and
              chain['source_tree'] == receipt['source']['tree'] and
              chain['inputs_sha256'] == c.digest(c.canonical(receipt)) and
              chain['seed_lock_sha256'] == receipt['seed_lock_sha256'],
              'light-input', 'cold receipt input identity differs')
    for name in ('toolchain', 'recipe', 'orchestrator', 'auditor'):
        c.sha(chain[name + '_sha256'], name)
    inventory = {row['path']: row['sha256'] for row in receipt['source']['inventory']}
    for key, path in (('recipe', 'scripts/cc-units.sh'), ('orchestrator', 'scripts/native_seed/cold.py'),
                      ('auditor', 'scripts/native_seed/cold_audit.py')):
        c.require(chain[key + '_sha256'] == inventory.get(path),
                  'light-input', 'cold recipe or verifier implementation differs from source inputs')
    c.fields(chain['isolation_tools'], 'bwrap strace', 'isolation tools')
    for digest in chain['isolation_tools'].values():
        c.sha(digest, 'isolation tool')
    c.fields(chain['roots'], 'root-1 root-2', 'cold roots')
    for root in chain['roots'].values():
        c.fields(root, 'stages steps plan_sha256 smoke_elf_sha256', 'cold root')
        c.fields(root['stages'], 'A B C', 'stage coverage')
        c.sha(root['plan_sha256'], 'source plan')
        c.sha(root['smoke_elf_sha256'], 'smoke ELF')
        c.require(type(root['steps']) is list and
                  all(type(row) is dict for row in root['steps']) and
                  [row.get('name') for row in root['steps']] == list(STEPS),
                  'light-coverage', 'cold execution steps are missing, duplicated or reordered')
        for output in root['stages'].values():
            c.fields(output, 'whole_sha256 info_sha256 units elf_sha256', 'stage output')
            for name in ('whole', 'info', 'elf'):
                c.sha(output[name + '_sha256'], name)
            c.inventory_sha(output['units'])
            c.require(output['units'] and all(row['kind'] == 'file' for row in output['units']),
                      'light-coverage', 'stage units must be a nonempty file set')
        for step in root['steps']:
            c.fields(step, 'name request_sha256 audit stdout_sha256 stderr_sha256', 'cold step')
            for name in ('request', 'stdout', 'stderr'):
                c.sha(step[name + '_sha256'], name)
            c.fields(step['audit'], 'descendants execs java_execs successful_opens network_syscalls absent_local_nss_probes trace_files', 'audit')
            c.require(type(step['audit']['descendants']) is int and step['audit']['descendants'] > 0 and
                      step['audit']['java_execs'] == 0 and step['audit']['network_syscalls'] == 0 and
                      type(step['audit']['execs']) is list and step['audit']['execs'] and
                      type(step['audit']['trace_files']) is dict and step['audit']['trace_files'],
                      'light-coverage', 'audit execution coverage is missing')
            for digest in step['audit']['trace_files'].values():
                c.sha(digest, 'trace')
        c.require(root['stages']['B'] == root['stages']['C'], 'light-fixpoint', 'B/C identities differ')
    c.require(chain['roots']['root-1']['stages']['B'] == chain['roots']['root-2']['stages']['B'],
              'light-fixpoint', 'two-root identities differ')


def check_package(chain, value):
    c.fields(value, 'schema kind source_commit source_tree cold_receipt_sha256 seed_lock_sha256 coverage implementations components lineage', 'qualification package')
    c.require(type(value['schema']) is int and value['schema'] == 1 and value['kind'] == 'native-qualification-package',
              'light-schema', 'unsupported qualification package')
    c.require(value['source_commit'] == chain['source_commit'] and value['source_tree'] == chain['source_tree'] and
              value['seed_lock_sha256'] == chain['seed_lock_sha256'] and
              value['cold_receipt_sha256'] == c.digest(c.canonical(chain)),
              'light-input', 'qualification package input identity differs')
    c.require(value['coverage'] == ['Q' + str(i) for i in range(1, 11)],
              'light-coverage', 'qualification control coverage differs')
    c.fields(value['components'], 'real fixtures transactions jvm dual', 'package components')
    c.fields(value['implementations'], 'scripts/native-seed-k4-test.py scripts/native_seed/qualification.py scripts/native_seed/rehearsal.py scripts/native_seed/package.py', 'package implementations')
    c.fields(value['lineage'], ' '.join(phase + '-' + fault for phase in
              ('after-objects', 'before-commit', 'after-commit') for fault in ('exception', 'SIGTERM', 'SIGKILL')), 'transaction lineage')
    for table in ('components', 'implementations', 'lineage'):
        for digest in value[table].values():
            c.sha(digest, table)


def check_results(manifest, results):
    c.require(type(manifest) is dict and tuple(manifest) == SUITES and
              type(results) is dict and set(results) == set(SUITES),
              'light-coverage', 'missing or extra fixture suite')
    for name in SUITES:
        rows = results[name]
        c.require(type(rows) is list and rows and all(type(row) is dict for row in rows) and
                  len(rows) == len(manifest[name]),
                  'light-coverage', name + ': fixture count differs')
        actual = [{'name': row.get('case', row.get('name')), 'expected': row.get('expected')}
                  for row in rows]
        c.require(actual == manifest[name], 'light-coverage', name + ': fixture identity/order differs')
        for row in rows:
            if 'expected' in row:
                # The shared shell recipe owns a shell diagnostic, not a Python Rejected.
                prefix = ('FAIL: ' if name == 'K2' and
                          row.get('case') == 'shared recipe missing runtime' else '')
                c.require(type(row.get('actual')) is str and
                          row['actual'].startswith(prefix + row['expected'] + ':'),
                          'light-verdict', name + ': unowned rejection')
    states = [row for row in results['K4-transactions'] if 'final_sequence' in row]
    c.require(len(states) == 9 and all(row['final_sequence'] == 3 for row in states),
              'light-coverage', 'transaction recovery cases are incomplete')


def selftest(lock, receipt, source, manifest, results):
    controls = []
    for name, edit in (
            ('missing-stage', lambda x: x['stages'].pop()),
            ('duplicate-stage', lambda x: x['stages'].__setitem__(2, x['stages'][1]))):
        changed = copy.deepcopy(receipt)
        edit(changed)
        controls.append(q.refused(name, 'stage-pairing', lambda: check_inputs(lock, changed, source)))
    changed = copy.deepcopy(receipt)
    changed['source']['commit'] = '0' * 40
    for key in ('std', 'runtime', 'embed'):
        changed['source'][key]['commit'] = '0' * 40
    changed['stages'] = c.stages(lock, changed['source'])
    controls.append(q.refused('wrong-receipt-input', 'light-input',
                              lambda: check_inputs(lock, changed, source)))
    changed = copy.deepcopy(receipt)
    changed['seed_lock_sha256'] = '0' * 64
    controls.append(q.refused('wrong-lock-input', 'seed-lock', lambda: check_inputs(lock, changed, source)))
    for suite in SUITES:
        changed = copy.deepcopy(results)
        changed.pop(suite)
        controls.append(q.refused('missing-suite-' + suite, 'light-coverage',
                                  lambda: check_results(manifest, changed)))
        changed = copy.deepcopy(results)
        changed[suite].pop()
        controls.append(q.refused('lost-fixture-' + suite, 'light-coverage',
                                  lambda: check_results(manifest, changed)))
        changed = copy.deepcopy(results)
        changed[suite].append(changed[suite][0])
        controls.append(q.refused('duplicate-fixture-' + suite, 'light-coverage',
                                  lambda: check_results(manifest, changed)))
    return controls


def chain_selftest(receipt):
    output = {'whole_sha256': '1' * 64, 'info_sha256': '2' * 64,
              'elf_sha256': '3' * 64, 'units': [c.record('tu00.c', b'fixed unit')]}
    audit = {'descendants': 1, 'execs': [{'path': '/fixture'}], 'java_execs': 0,
             'network_syscalls': 0, 'successful_opens': [], 'absent_local_nss_probes': 0,
             'trace_files': {'trace.1': '4' * 64}}
    root = {'stages': {name: copy.deepcopy(output) for name in ('A', 'B', 'C')},
            'steps': [dict(name=name, audit=audit, request_sha256='5' * 64,
                           stdout_sha256='6' * 64, stderr_sha256='7' * 64) for name in STEPS],
            'plan_sha256': '8' * 64, 'smoke_elf_sha256': '9' * 64}
    chain = dict(schema=1, kind='native-cold-chain', policy='native-cold-linux-x86_64-v1',
                 inputs_sha256=c.digest(c.canonical(receipt)), seed_lock_sha256=receipt['seed_lock_sha256'],
                 source_commit=receipt['source']['commit'], source_tree=receipt['source']['tree'],
                 isolation_tools={'bwrap': 'a' * 64, 'strace': 'b' * 64},
                 roots={name: copy.deepcopy(root) for name in ('root-1', 'root-2')},
                 **{name + '_sha256': 'c' * 64 for name in ('toolchain', 'recipe', 'orchestrator', 'auditor')})
    inventory = {row['path']: row['sha256'] for row in receipt['source']['inventory']}
    for key, path in (('recipe', 'scripts/cc-units.sh'), ('orchestrator', 'scripts/native_seed/cold.py'),
                      ('auditor', 'scripts/native_seed/cold_audit.py')):
        chain[key + '_sha256'] = inventory[path]
    check_cold(receipt, chain)
    value = dict(schema=1, kind='native-qualification-package', source_commit=chain['source_commit'],
                 source_tree=chain['source_tree'], cold_receipt_sha256=c.digest(c.canonical(chain)),
                 seed_lock_sha256=chain['seed_lock_sha256'], coverage=['Q' + str(i) for i in range(1, 11)],
                 components={name: 'd' * 64 for name in ('real', 'fixtures', 'transactions', 'jvm', 'dual')},
                 implementations={name: 'e' * 64 for name in ('scripts/native-seed-k4-test.py',
                     'scripts/native_seed/qualification.py', 'scripts/native_seed/rehearsal.py', 'scripts/native_seed/package.py')},
                 lineage={phase + '-' + fault: 'f' * 64 for phase in ('after-objects', 'before-commit', 'after-commit')
                          for fault in ('exception', 'SIGTERM', 'SIGKILL')})
    check_package(chain, value)
    controls = []
    for name, code, mutate in (
            ('missing-cold-stage', 'schema', lambda x: x['roots']['root-1']['stages'].pop('C')),
            ('missing-cold-step', 'light-coverage', lambda x: x['roots']['root-1']['steps'].pop()),
            ('duplicate-cold-step', 'light-coverage', lambda x: x['roots']['root-1']['steps'].append(x['roots']['root-1']['steps'][0])),
            ('wrong-cold-input', 'light-input', lambda x: x.update(inputs_sha256='0' * 64))):
        changed = copy.deepcopy(chain)
        mutate(changed)
        controls.append(q.refused(name, code, lambda: check_cold(receipt, changed)))
    for name, code, mutate in (
            ('missing-package-control', 'light-coverage', lambda x: x['coverage'].pop()),
            ('wrong-package-input', 'light-input', lambda x: x.update(cold_receipt_sha256='0' * 64))):
        changed = copy.deepcopy(value)
        mutate(changed)
        controls.append(q.refused(name, code, lambda: check_package(chain, changed)))
    return controls


def run(work):
    lock = c.read_lock(ROOT / 'scripts/native-seed-candidate-v0.104.0.json')
    commit = c.git(ROOT, 'rev-parse', 'HEAD').decode().strip()
    source, _ = c.source_description(ROOT, commit)
    receipt = {'schema': 2, 'kind': 'native-bootstrap-inputs',
               'seed_lock_sha256': c.digest(c.canonical(lock)), 'source': source,
               'stages': c.stages(lock, source)}
    check_inputs(lock, receipt, source)
    commands = (
        ('K1', ['scripts/native-seed-contract-test.py']),
        ('K2', ['scripts/native-seed-k2-test.py', '--out', str(work / 'k2')]),
        ('K3', ['scripts/native-seed-k3-test.py', '--out', str(work / 'k3')]),
        ('K4', ['scripts/native-seed-k4-test.py', 'fixtures', '--out', str(work / 'k4')]))
    for name, arguments in commands:
        result = subprocess.run([sys.executable, '-B', *arguments], cwd=ROOT,
                                capture_output=True, timeout=20)
        (work / (name + '.stdout')).write_bytes(result.stdout)
        (work / (name + '.stderr')).write_bytes(result.stderr)
        c.require(result.returncode == 0, 'light-fixture', name + ': see saved stdout/stderr')
    results = {
        'K1': c.read_json(work / 'K1.stdout')['negative'],
        'K2': c.read_json(work / 'k2/results.json')['fixture_controls'],
        'K3': c.read_json(work / 'k3/fixtures/results.json'),
        'K4': c.read_json(work / 'k4/results.json')['controls'],
        'K4-transactions': c.read_json(work / 'k4/transactions/results.json')['controls']}
    manifest_path = ROOT / 'scripts/native-seed-light-fixtures.json'
    manifest = c.read_json(manifest_path)
    check_results(manifest, results)
    controls = selftest(lock, receipt, source, manifest, results) + chain_selftest(receipt)
    summary = {'schema': 1, 'kind': 'native-light-controls', 'qualification': False,
               'source_commit': commit, 'source_tree': source['tree'],
               'inputs_sha256': c.digest(c.canonical(receipt)),
               'fixtures_sha256': c.digest(manifest_path.read_bytes()),
               'suites': {name: len(rows) for name, rows in results.items()}, 'controls': controls}
    c.atomic_json(work / 'inputs.json', receipt)
    c.atomic_json(work / 'summary.json', summary)
    print('OK native light controls: ' + ', '.join(f'{k}={v}' for k, v in summary['suites'].items()) +
          f'; coverage/input negatives={len(controls)}; qualification=false', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--receipt', type=Path, help='check an external input receipt without executing it')
    parser.add_argument('--commit', help='required full commit identity for --receipt')
    parser.add_argument('--cold-receipt', type=Path)
    parser.add_argument('--package-receipt', type=Path)
    args = parser.parse_args()
    def deadline(signum, frame):
        raise c.Rejected('light-deadline: total structural control budget exceeded 30 seconds')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(30)
    try:
        c.require(args.receipt is not None or not (args.cold_receipt or args.package_receipt or args.commit),
                  'arguments', 'external receipt checks require --receipt and --commit')
        if args.receipt:
            c.oid(args.commit, 'expected source')
            source, _ = c.source_description(ROOT, args.commit)
            receipt = c.read_json(args.receipt)
            check_inputs(c.read_lock(ROOT / 'scripts/native-seed-candidate-v0.104.0.json'), receipt, source)
            if args.cold_receipt:
                chain = c.read_json(args.cold_receipt)
                check_cold(receipt, chain)
                if args.package_receipt:
                    check_package(chain, c.read_json(args.package_receipt))
            else:
                c.require(args.package_receipt is None, 'arguments', '--package-receipt requires --cold-receipt')
            print('OK input receipt structure and committed identity; qualification=false')
        elif args.out:
            c.require(not args.out.exists(), 'destination', 'new light control output required')
            args.out.mkdir(parents=True)
            run(args.out.absolute())
        else:
            with tempfile.TemporaryDirectory(prefix='native-light-') as directory:
                run(Path(directory))
    except (c.Rejected, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
