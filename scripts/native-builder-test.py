#!/usr/bin/env python3
"""Receipt substitutions must fail before producer publication or seed promotion.

Tiny static compilers make byte identities real while stages and toolchain
inventories remain explicit fixtures. Disabling each owned refusal must make
its control fail; the same controls also run against the pre1 base producer.
"""

import copy
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import native_release as nr
from native_seed import builder, contract as c, inputs, lockchain, provenance, test_support, toolchain

ROOT = Path(__file__).resolve().parents[1]
BASE = '6af3d9d2ee983c18789f000d28ecb475ce937e05'


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / {
        'release-protocol-test': 'scripts/release-protocol-test.py',
        'native-seed': 'scripts/native-seed.py',
        'advance-native-seed': 'scripts/advance-native-seed.py'}[name])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refused(thunk, label):
    try:
        thunk()
    except (c.Rejected, ValueError) as exc:
        print('OK refusal ' + label + ': ' + str(exc).split(':')[0], flush=True)
        return
    raise AssertionError('control missed: ' + label)


def main():
    protocol = load_script('release-protocol-test')
    with tempfile.TemporaryDirectory(prefix='native-builder-control-') as work:
        work = Path(work)
        lock_path = protocol.fixture_lock(work / 'lock', 'native builder fixture')
        lock = lockchain.release_lock(lock_path)
        a = protocol.fake_compiler(work, 'A', nr.source_version(), 'b1:' + 'a' * 64)
        b = protocol.fake_compiler(work, 'B', nr.source_version(), 'b1:' + 'b' * 64)
        receipt = test_support.chain_record(ROOT, lock, a, b)
        path = work / 'chain.json'
        path.write_bytes(c.canonical(receipt))
        verify = lambda: builder.verify_receipt(path, ROOT, lock, b, a)
        verify()
        captured = builder.source_files(ROOT, receipt['source_commit'])
        source_patch = patch.object(builder, 'source_files', return_value=captured)
        source_patch.start()
        mutations = [
            ('wrong source commit', lambda v: v.update(source_commit='0' * 40)),
            ('wrong source tree', lambda v: v.update(source_tree='0' * 40)),
            ('wrong source bytes', lambda v: v.update(source_sha256='0' * 64)),
            ('wrong lock', lambda v: v.update(lock_sha256='0' * 64)),
            ('wrong seed', lambda v: v['stages']['A'].update(emitter_sha256='0' * 64)),
            ('wrong std', lambda v: v['stages']['A']['std'].update(sha256='0' * 64)),
            ('wrong runtime', lambda v: v['stages']['B']['runtime'].update(sha256='0' * 64)),
            ('wrong CC bytes', lambda v: v['toolchain']['compiler'].update(sha256='0' * 64)),
            ('wrong CC target', lambda v: v['toolchain']['compiler'].update(triple='aarch64-linux-gnu')),
            ('wrong recipe clang version', lambda v: v['recipe_identity']['clang'].update(version='changed')),
            ('wrong recipe clang bytes', lambda v: v['recipe_identity']['clang'].update(sha256='0' * 64)),
            ('wrong recipe target', lambda v: v['recipe_identity']['clang'].update(triple='aarch64-linux-gnu')),
            ('wrong recipe selected input', lambda v: v['recipe_identity']['inputs']['libgcc.a'].update(sha256='0' * 64)),
            ('wrong recipe input path', lambda v: v['recipe_identity']['inputs']['libc.a'].update(path='/wrong/libc.a')),
            ('wrong recipe flags', lambda v: v['recipe_identity'].update(flags=[])),
            ('wrong recipe script', lambda v: v['recipe_identity'].update(recipe_sha256='0' * 64)),
            ('wrong ld version', lambda v: v['recipe_identity'].update(ld_version='GNU ld changed')),
            ('changed captured ld version', lambda v: v['toolchain']['linker'].update(version='GNU ld changed')),
            ('wrong linker bytes', lambda v: v['toolchain']['executables'].update({'/usr/bin/ld': '0' * 64})),
            ('wrong GCC driver path', lambda v: v['toolchain']['driver']['files'].update({'libgcc.a': '/usr/lib/gcc/x86_64-linux-gnu/14/libgcc.a'})),
            ('wrong crt path', lambda v: v['toolchain']['driver']['files'].update({'crtbeginT.o': '/usr/lib/gcc/x86_64-linux-gnu/14/crtbeginT.o'})),
            ('missing GCC selection flag', lambda v: v['toolchain']['driver'].update(flags=[])),
            ('wrong libc closure', lambda v: v['toolchain']['inventory'].pop()),
            ('development CC', lambda v: v['toolchain'].update(recipe='development-clang-gcc13-static-v1')),
            ('missing A', lambda v: v['stages'].pop('A')),
            ('missing B', lambda v: v['stages'].pop('B')),
            ('missing C', lambda v: v['stages'].pop('C')),
            ('changed A', lambda v: v['stages']['A']['output'].update(elf_sha256='0' * 64)),
            ('changed B and C', lambda v: [v['stages'][s]['output'].update(elf_sha256='0' * 64) for s in ('B', 'C')]),
            ('B C mismatch', lambda v: v['stages']['C']['output'].update(whole_sha256='0' * 64)),
            ('changed recipe', lambda v: v['compilation'].update(recipe_sha256='0' * 64)),
            ('changed compilation', lambda v: v.update(compilation_sha256='0' * 64)),
        ]
        for label, edit in mutations:
            changed = copy.deepcopy(receipt)
            edit(changed)
            path.write_bytes(c.canonical(changed))
            refused(verify, label)
        path.write_bytes(c.canonical(receipt))
        refused(lambda: builder.verify_receipt(path, ROOT, lock, a, b), 'swapped A/B')
        path.write_bytes(c.canonical(receipt) + b'\n')
        refused(verify, 'reformatted receipt')
        path.unlink()
        refused(verify, 'missing receipt')
        path.write_bytes(c.canonical(receipt))
        # Sensitivity: make every check disappear. Every negative fixture must
        # then fail its own assertion, instead of reporting a false green.
        for label, edit in mutations:
            changed = copy.deepcopy(receipt)
            edit(changed)
            path.write_bytes(c.canonical(changed))
            try:
                with patch.object(c, 'require', lambda *_: None):
                    refused(verify, label)
            except (AssertionError, KeyError, TypeError):
                pass
            else:
                raise AssertionError('disabled guards escaped the control: ' + label)
        path.write_bytes(c.canonical(receipt))
        _, files = builder.source_files(ROOT, receipt['source_commit'])
        tc = test_support.compiler_record()
        # Full snapshots remain factual. A self-consistent non-recipe change
        # may differ across hosts, while the recipe and B must stay identical.
        changed = copy.deepcopy(receipt)
        for row in changed['toolchain']['inventory']:
            if row['path'] in ('usr/bin/ld', 'usr/bin/ld.bfd'):
                row['sha256'] = 'f' * 64
                changed['toolchain']['executables']['/' + row['path']] = row['sha256']
        changed['toolchain']['inventory_sha256'] = c.inventory_sha(changed['toolchain']['inventory'])
        changed['compilation'] = inputs.compilation(files, lock, changed['toolchain'])
        changed['compilation_sha256'] = c.digest(c.canonical(changed['compilation']))
        assert changed['compilation_sha256'] != receipt['compilation_sha256']
        assert changed['recipe_identity'] == toolchain.recipe_identity(changed['toolchain'], changed['compilation']['recipe_sha256'])
        path.write_bytes(c.canonical(changed))
        builder.verify_receipt(path, ROOT, lock, b, a, hosted=True)
        builder.compare_hosts(receipt, changed)
        changed['execution'] = provenance.development(receipt['source_commit'])
        path.write_bytes(c.canonical(changed))
        verify()
        refused(lambda: builder.verify_receipt(path, ROOT, lock, b, a, hosted=True), 'development stamp as release evidence')
        mismatch = copy.deepcopy(receipt)
        mismatch['stages']['B']['output']['elf_sha256'] = '0' * 64
        refused(lambda: builder.compare_hosts(receipt, mismatch), 'same recipe different B')
        for key in ('clang', 'inputs', 'flags', 'ld_version', 'recipe_sha256'):
            mismatch = copy.deepcopy(receipt)
            mismatch['recipe_identity'][key] = None
            refused(lambda: builder.compare_hosts(receipt, mismatch), 'cross-host recipe ' + key)
        with patch.dict('os.environ', test_support.hosted_environment(receipt['source_commit'])):
            provenance.current(receipt['execution'], receipt['source_commit'], release=True)
            mismatch = dict(receipt['execution'], run_id='456')
            refused(lambda: provenance.current(mismatch, receipt['source_commit'], release=True), 'another hosted run')
        path.write_bytes(c.canonical(receipt))
        print('OK distinct environment snapshots retain recipe equality and development scope')
        diagnostics = io.StringIO()

        def wrong_driver(argv, **kwargs):
            name = argv[-1].split('=', 1)[1]
            path = tc['driver']['files'][name]
            if name == 'libgcc.a':
                path = '/usr/lib/gcc/x86_64-linux-gnu/14/libgcc.a'
            return subprocess.CompletedProcess(argv, 0, stdout=path + '\n', stderr='')

        with patch.object(toolchain, 'qualification_flags', return_value=tc['driver']['flags']), \
             patch.object(toolchain.subprocess, 'run', side_effect=wrong_driver), \
             patch.object(sys, 'stderr', diagnostics):
            refused(lambda: toolchain.driver_inputs('/fixture/clang', {'CANARY': 'private-value'}),
                    'actual GCC resolution outside capture')
        diagnostic_paths = diagnostics.getvalue().splitlines()
        assert len(diagnostic_paths) == len(toolchain.DRIVER_INPUTS)
        assert all(path.startswith('/') for path in diagnostic_paths)
        assert '/usr/lib/gcc/x86_64-linux-gnu/14/libgcc.a' in diagnostic_paths
        assert 'CANARY' not in diagnostics.getvalue() and 'private-value' not in diagnostics.getvalue()
        print('OK toolchain rejection prints only actual resolved paths')
        baseline = inputs.compilation_sha(files, lock, tc)
        changed = dict(files)
        for name in inputs.CONTROL_FILES | {'scripts/native-seed-history/0.json'}:
            changed[name] = ('100644', b'changed control record\n')
        assert inputs.compilation_sha(changed, lock, tc) == baseline, 'control records invalidated compilation'
        altered_lock = copy.deepcopy(lock)
        altered_lock['lineage']['qualification_sha256'] = 'd' * 64
        altered_lock['chain'] = 'native'
        assert inputs.compilation_sha(files, altered_lock, tc) == baseline, 'lock transition invalidated compilation'
        print('OK control records and qualification reference do not change compilation inputs')
        for name in ('selfhost/src/nmain.dawn', 'std/str.dawn', 'runtime/c/dawn_rt.c',
                     'scripts/cc-units.sh', 'compiler-plan/dawn.toml', 'selfhost/src/embed/stdsrc.dawn'):
            changed = dict(files)
            mode, data = changed[name]
            changed[name] = (mode, data + b'\n')
            assert inputs.compilation_sha(changed, lock, tc) != baseline, name + ' failed to invalidate'
        changed = copy.deepcopy(tc)
        changed['compiler']['sha256'] = 'e' * 64
        assert inputs.compilation_sha(files, lock, changed) != baseline
        print('OK source, std, runtime, recipe, dependency, embed and CC changes invalidate compilation')
        # A new proposed ELF is accepted all the way through capture, seed
        # probing and promotion binding. No historical candidate is substituted.
        path.write_bytes(c.canonical(receipt))
        proposed_path = work / 'proposed.json'
        subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/native-seed-chain.py'),
            'describe-seed', '--seed-elf', str(b), '--seed-commit', receipt['source_commit'],
            '--out', str(proposed_path), '--chain-receipt', str(path),
            '--origin-lock', str(lock_path), '--origin-builder', str(a)], check=True, capture_output=True)
        proposed = builder.load_lock(proposed_path)
        c.verify_seed_probe(b, proposed)
        cap = load_script('native-seed').capture(ROOT, receipt['source_commit'], work / 'capture', proposed)
        assert cap['seed_lock_sha256'] == c.digest(c.canonical(proposed))
        evidence = work / 'qualification'
        (evidence / 'cold/toolchain').mkdir(parents=True)
        (evidence / 'cold/seed-lock.json').write_bytes(c.canonical(proposed))
        (evidence / 'cold/toolchain/toolchain.json').write_bytes(c.canonical(tc))
        compiled = inputs.compilation(files, proposed, tc)
        package = {'kind': 'native-qualification-package', 'source_commit': receipt['source_commit'],
                   'execution': receipt['execution'],
                   'coverage': ['Q' + str(i) for i in range(1, 11)], 'compilation': compiled,
                   'compilation_sha256': c.digest(c.canonical(compiled)),
                   'seed_lock_sha256': cap['seed_lock_sha256'], 'qualified_seed_sha256': proposed['seed']['sha256']}
        adv = load_script('advance-native-seed')
        request = {'schema': 1, 'kind': 'native-qualification-request', 'commit': receipt['source_commit'],
                   'execution': receipt['execution'],
                   'reason': 'seed-promotion', 'entry_sha256': c.digest(b'fixture entry'),
                   'seed_lock_sha256': cap['seed_lock_sha256']}
        (evidence / 'request.json').write_bytes(c.canonical(request))

        def seal_fixture(value):
            raw = c.canonical(value)
            (evidence / 'receipt.json').write_bytes(raw)
            for name, steps in (('completed.json', adv.RUN_STEPS), ('verified.json', adv.VERIFY_STEPS)):
                (evidence / name).write_bytes(c.canonical({'source_commit': request['commit'],
                    'receipt_sha256': c.digest(raw), 'checks': [{'name': n, 'exit_code': 0} for n in steps],
                    'production_authorized': False}))

        seal_fixture(package)
        adv.qualification_receipt(evidence, 'seed-promotion')
        check_subject = lambda: adv.verify_subject(evidence, ROOT, request['commit'],
                                   proposed['seed'], proposed['std'], proposed['runtime'])
        check_subject()
        for key in ('seed_lock_sha256', 'qualified_seed_sha256'):
            seal_fixture(dict(package, **{key: '0' * 64}))
            refused(lambda: adv.qualification_receipt(evidence, 'seed-promotion'), 'qualification ' + key)
        seal_fixture(dict(package, compilation_sha256='0' * 64))
        refused(check_subject, 'qualification compilation digest')
        seal_fixture(package)
        with patch.object(builder, 'source_files', return_value=(captured[0],
                {**files, 'scripts/native-seed-history/999.json': ('100644', b'control change')})):
            check_subject()
        with patch.object(builder, 'source_files', return_value=(captured[0],
                {**files, 'selfhost/src/nmain.dawn': ('100644', files['selfhost/src/nmain.dawn'][1] + b'\n')})):
            refused(check_subject, 'qualification changed compilation source')
        print('OK actual proposed lock and ELF survive capture and nonrecursive promotion binding')
        # The old producer accepts each substitution because it never reads
        # the full receipt. This is a saved, intentionally red baseline run.
        if '--baseline' in sys.argv:
            source = c.git(ROOT, 'show', BASE + ':scripts/native_release.py').decode()
            scope = {'__file__': str(ROOT / 'scripts/native_release.py'), '__name__': 'pre1_baseline'}
            exec(compile(source, 'pre1-base-producer', 'exec'), scope)
            jar, api, diff = work / 'ref.jar', work / 'api.json', work / 'diff.md'
            jar.write_bytes(b'PK fixture\n')
            api.write_text('{}\n')
            diff.write_text('fixture\n')
            missed = []
            for index, (label, edit) in enumerate(mutations):
                changed = copy.deepcopy(receipt)
                edit(changed)
                path.write_bytes(c.canonical(changed))
                args = SimpleNamespace(lock=lock_path, native=b, builder=a, chain_receipt=path,
                    jdk21_jar=jar, jdk26_jar=jar, pub_api=api, pub_api_diff=diff,
                    expect_tag='v' + nr.source_version(), skip_smoke=True,
                    cold_sha256=c.digest(c.canonical(changed)), out=work / ('base-' + str(index)))
                scope['produce'](args)
                missed.append(label)
            print('RED baseline accepted ' + ', '.join(missed), flush=True)
            return 1
        # Removing the nonrecursive filter must turn the control-only test red.
        try:
            with patch.object(inputs, 'compilation_files', lambda f: f):
                assert inputs.compilation_sha({**files, 'scripts/native-seed-history/999.json': ('100644', b'x')}, lock, tc) == baseline
        except AssertionError:
            print('OK controls detect loss of the nonrecursive filter')
        else:
            raise AssertionError('control missed: nonrecursive filter removed')
        source_patch.stop()
    print('OK native builder receipt and compilation controls')
    return 0


if __name__ == '__main__':
    sys.exit(main())
