#!/usr/bin/env python3
"""Exercise receipt refusals without rebuilding a compiler for each mutation.

These fixtures test the consumer boundary, not compiler semantics. Every case
starts from accepted byte identities, changes one input, and must name the
broken identity rather than silently accepting a cache or an empty document.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

spec = importlib.util.spec_from_file_location('site_inputs', Path(__file__).with_name('inputs.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def main():
    original = m.ROOT
    with tempfile.TemporaryDirectory(prefix='site-input-controls-') as work:
        m.ROOT = Path(work)
        m.NATIVE = m.ROOT / 'site/build/native'
        m.TOOL = m.NATIVE / 'dawnc.tool.json'
        m.PREPARED = m.ROOT / 'site/build/prepared.json'
        m.DATA = m.ROOT / 'site/build/java-metadata/manifest.json'
        m.LOCK = m.ROOT / 'site/java-metadata.lock.json'
        m.NATIVE.mkdir(parents=True)
        shutil.copytree(original / 'site/build/java-metadata', m.DATA.parent)
        shutil.copy(original / 'site/java-metadata.lock.json', m.LOCK)
        for name in [*m.RECIPE, 'std/prelude.dawn', 'runtime/c/test.c',
                     'app/dawn.toml', 'app/src/main.dawn', 'dep/dawn.toml',
                     'dep/src/api.dawn']:
            path = m.ROOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n')
        (m.NATIVE / 'dawnc').write_bytes(b'native fixture')
        (m.NATIVE / 'site_source_inputs').write_bytes(b'planner fixture')
        (m.NATIVE / 'dawnc').chmod(0o755)
        (m.NATIVE / 'site_source_inputs').chmod(0o755)
        records = sorted(['R\tF\tapp/dawn.toml', 'R\tO\tapp/dawn.lock',
                          'R\tT\tapp/src', 'R\tF\tdep/dawn.toml', 'R\tT\tdep/src'])
        manifest = 'dawn-source-inputs-v1\n' + '\n'.join(records) + '\n'
        capture = {
            'source_inputs_sha256': m.source_state(manifest),
            'planner_inputs_sha256': m.source_state(manifest),
            'embedded_std_sha256': m.identity(m.tree_records(m.ROOT / 'std')),
            'runtime_inputs_sha256': m.identity(m.tree_records(m.ROOT / 'runtime/c')),
            'recipe_sha256': m.recipe_sha(),
        }
        tool = dict(capture, schema='dawn-doc-tool-v1', backend='native',
                    source_commit='1' * 40, source_inputs=manifest, planner_inputs=manifest,
                    binary_sha256=m.sha((m.NATIVE / 'dawnc').read_bytes()),
                    planner_binary_sha256=m.sha((m.NATIVE / 'site_source_inputs').read_bytes()),
                    capture_before=capture)
        m.write_json(m.TOOL, tool)
        prepared = {'schema': 'dawn-site-prepared-v1',
                    'tool_identity_sha256': m.sha(m.TOOL.read_bytes()),
                    'java_manifest_sha256': m.sha(m.DATA.read_bytes()),
                    'java_lock_sha256': m.sha(m.LOCK.read_bytes())}
        m.write_json(m.PREPARED, prepared)
        m.check_prepared()
        passed = []
        check = m.check_prepared

        def refused(label, change, restore, expected):
            try:
                change()
                try:
                    check()
                except (ValueError, OSError, KeyError) as error:
                    m.require(expected in str(error), label + ': wrong diagnostic: ' + str(error))
                else:
                    raise AssertionError(label + ': mutation was accepted')
            finally:
                restore()
            check()
            passed.append(label)

        def mutate_file(label, path, raw, expected):
            before = path.read_bytes() if path.exists() else None
            refused(label, lambda: path.write_bytes(raw),
                    lambda: path.write_bytes(before) if before is not None else path.unlink(), expected)

        mutate_file('compiler bytes', m.NATIVE / 'dawnc', b'old compiler', 'binary_sha256')
        mutate_file('planner bytes', m.NATIVE / 'site_source_inputs', b'old planner', 'planner_binary')
        refused('nonexecutable tool', lambda: (m.NATIVE / 'dawnc').chmod(0o644),
                lambda: (m.NATIVE / 'dawnc').chmod(0o755), 'not executable')
        mutate_file('source content', m.ROOT / 'app/src/main.dawn', b'changed', 'source_inputs')
        mutate_file('new source', m.ROOT / 'app/src/new.dawn', b'new', 'source_inputs')
        mutate_file('dependency source', m.ROOT / 'dep/src/api.dawn', b'changed', 'source_inputs')
        mutate_file('missing root lock', m.ROOT / 'app/dawn.lock', b'lock', 'source_inputs')
        mutate_file('missing dependency lock', m.ROOT / 'dep/dawn.lock', b'lock', 'source_inputs')
        mutate_file('embedded std', m.ROOT / 'std/prelude.dawn', b'changed', 'embedded_std')
        mutate_file('C runtime', m.ROOT / 'runtime/c/test.c', b'changed', 'runtime_inputs')
        mutate_file('compiler recipe', m.ROOT / m.RECIPE[0], b'changed', 'recipe_sha256')
        link = m.ROOT / 'app/src/link'
        refused('source symlink', lambda: link.symlink_to(m.ROOT / 'dep/src/api.dawn'),
                link.unlink, 'symbolic input')
        data = m.read_json(m.DATA)
        entry = data['classes'][0]
        class_path = m.DATA.parent / entry['path']
        raw = class_path.read_bytes()
        mutate_file('class bytes', class_path, raw + b'X', 'class identity')
        refused('missing class', class_path.unlink, lambda: class_path.write_bytes(raw),
                'missing regular input')
        def class_link():
            class_path.unlink()
            class_path.symlink_to(original / 'site/build/java-metadata' / entry['path'])
        def restore_class():
            class_path.unlink()
            class_path.write_bytes(raw)
        refused('class symlink', class_link, restore_class, 'symbolic input')
        mutate_file('extra class', m.DATA.parent / 'extra.class', b'X', 'directory inventory')
        manifest_raw = m.DATA.read_bytes()
        prepared_raw = m.PREPARED.read_bytes()
        def forged_manifest():
            forged = copy.deepcopy(data)
            class_path.write_bytes(raw + b'X')
            forged['classes'][0]['size'] = len(raw) + 1
            forged['classes'][0]['sha256'] = m.sha(raw + b'X')
            forged['classes_sha256'] = m.identity(forged['classes'])
            encoded = (json.dumps(forged, indent=2, sort_keys=True) + '\n').encode()
            m.require(len(encoded) == len(manifest_raw), 'forgery must preserve manifest size')
            m.DATA.write_bytes(encoded)
            changed = dict(prepared, java_manifest_sha256=m.sha(m.DATA.read_bytes()))
            m.write_json(m.PREPARED, changed)
        def restore_manifest():
            class_path.write_bytes(raw)
            m.DATA.write_bytes(manifest_raw)
            m.PREPARED.write_bytes(prepared_raw)
        refused('manifest self-hash forgery', forged_manifest, restore_manifest, 'site lock')
        mutate_file('missing preparation', m.PREPARED, b'{}', 'schema')

        # SourcePlan execution is covered by the real build and JVM manifest
        # comparison. These receipt fixtures supply one deterministic plan.
        m.plan = lambda project: manifest
        m.commit = lambda: '1' * 40
        lock = m.check_prepared()
        for name in lock['packages']:
            directory = m.ROOT / 'packages' / name
            directory.mkdir(parents=True)
            shutil.copy(original / 'packages' / name / 'dawn.toml', directory / 'dawn.toml')
        bundle = m.ROOT / 'bundle'
        (bundle / 'packages').mkdir(parents=True)
        m.write_json(bundle / 'stdlib.json', {'groups': [], 'traits': [], 'modules': []})
        items = m.targets(lock)
        for item in items:
            item['doc_schema'] = 'dawn-doc-project-v1'
            m.write_json(bundle / item['output'], {'modules': []})
        receipt = {
            'schema': 'dawn-doc-bundle-v1', 'source_commit': m.commit(),
            'tool_identity_sha256': m.sha(m.TOOL.read_bytes()),
            'java_manifest_sha256': m.sha(m.DATA.read_bytes()),
            'stdlib_sha256': m.identity(m.tree_records(m.ROOT / 'std')),
            'stdlib_argv': ['doc', '--stdlib'], 'stdlib_doc_schema': 'dawn-doc-stdlib-v1',
            'package_inventory_sha256': m.identity(lock['packages']),
            'targets': items, 'outputs': m.tree_records(bundle),
        }
        m.write_json(bundle / 'receipt.json', receipt)
        m.check_bundle(bundle)
        check = lambda: m.check_bundle(bundle)
        mutate_file('extra JSON', bundle / 'packages/old.json', b'{}', 'output inventory')
        first = bundle / items[0]['output']
        mutate_file('changed JSON', first, b'{"modules":[]}', 'output bytes')
        saved = first.read_bytes()
        refused('missing JSON', first.unlink, lambda: first.write_bytes(saved), 'output inventory')
        def mutate_receipt(label, field, value, expected):
            changed = copy.deepcopy(receipt)
            changed[field] = value
            mutate_file(label, bundle / 'receipt.json', m.canonical(changed) + b'\n', expected)
        mutate_receipt('old commit', 'source_commit', '2' * 40, 'source commit')
        changed = copy.deepcopy(items)
        changed[0]['argv'] += ['--java-signatures', 'other.json']
        mutate_receipt('wrong doc argv', 'targets', changed, 'target identity')
        changed = copy.deepcopy(items)
        changed[0]['source_inputs'] = 'dawn-source-inputs-v1\nR\tF\tapp/dawn.toml\n'
        mutate_receipt('truncated source plan', 'targets', changed, 'target identity')
        def invalid_schema():
            m.write_json(first, {'modules': {}})
            changed = copy.deepcopy(receipt)
            changed['outputs'] = [m.file_record(bundle / record['path'], record['path'])
                                  for record in receipt['outputs']]
            m.write_json(bundle / 'receipt.json', changed)
        def restore_schema():
            first.write_bytes(saved)
            m.write_json(bundle / 'receipt.json', receipt)
        refused('JSON schema with matching hash', invalid_schema, restore_schema, 'documentation schema')
        for label in passed:
            print('PASS: ' + label)
        print('OK: ' + str(len(passed)) + ' site input refusal controls')


if __name__ == '__main__':
    main()
