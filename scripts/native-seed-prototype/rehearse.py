#!/usr/bin/env python3
"""Rehearse release identities and local immutable publication; never contact a release service."""

import argparse
import copy
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_seed import cold, contract as c, package, qualification as q
import identity

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def compiler_identity(binary):
    with tempfile.TemporaryDirectory(prefix='native-prototype-probe-') as home:
        env = {'PATH': '/nonexistent', 'HOME': home, 'LANG': 'C.UTF-8'}
        version = subprocess.run([str(binary), '--version'], env=env, capture_output=True, timeout=30)
        listing = subprocess.run([str(binary), 'version', '-m', str(binary)],
                                 env=env, capture_output=True, timeout=30)
    ids = re.findall(rb'^\tbuild\t(b1:[0-9a-f]{64})$', listing.stdout, re.M)
    c.require(version.returncode == listing.returncode == 0 and not version.stderr and
              not listing.stderr and len(ids) == 1, 'prototype-version', 'identity probe failed')
    match = re.fullmatch(rb'dawnc ([0-9]+\.[0-9]+\.[0-9]+) \(native\) (b1:[0-9a-f]{12})\n', version.stdout)
    c.require(match and match[2] == ids[0][:15], 'prototype-version', 'short/full identity differs')
    return match[1].decode(), ids[0].decode()


def produce(qualification, destination):
    value = package.verify(ROOT, qualification)
    chain = c.read_json(qualification / 'cold/receipt.json')
    lock = c.read_lock(qualification / 'cold/seed-lock.json')
    a, b = (qualification / 'cold/root-1' / stage / 'dawnc' for stage in ('A', 'B'))
    version, b1 = compiler_identity(b)
    aversion, ab1 = compiler_identity(a)
    c.require(aversion == version, 'prototype-version', 'stage A is not the current source version')
    proof = {'schema': 2, 'kind': 'native-bootstrap-prototype', 'prototype_only': True,
             'source_commit': value['source_commit'], 'qualification_sha256': c.digest(c.canonical(value)),
             'cold_sha256': c.digest(c.canonical(chain)), 'builder_sha256': c.digest(a.read_bytes()),
             'native_sha256': c.digest(b.read_bytes())}
    info = {'schema': 2, 'release': {'tag': 'v' + version, 'version': version, 'commit': value['source_commit']},
            'native': {'kind': 'native-elf', 'name': c.ASSET, 'stage': 'B', 'sha256': c.digest(b.read_bytes()),
                       'size': b.stat().st_size, 'build_id': b1, 'target': c.TARGET},
            'builder': {'kind': 'native-elf', 'stage': 'A', 'name': 'dawnc-stage-a',
                        'sha256': c.digest(a.read_bytes()), 'version': aversion, 'build_id': ab1},
            'bootstrap': {'seed': lock['seed'], 'std': lock['std'], 'runtime': lock['runtime'],
                          'parent_receipt_sha256': lock['lineage']['parent_receipt_sha256']},
            'recipe': {name: chain[name] for name in ('inputs_sha256', 'toolchain_sha256', 'recipe_sha256')},
            'proof': {'name': 'native-bootstrap.json', 'sha256': c.digest(c.canonical(proof))},
            'jvm_reference': {'name': 'dawn-selfhost.jar', 'kind': 'jvm-jar',
                              'sha256': c.digest((qualification / 'jvm/jdk-21.jar').read_bytes()),
                              'commit': value['source_commit'],
                              'jdk_equivalence_sha256': value['components']['jvm']}}
    identity.metadata(info, 'v' + version, native_required=True)
    destination = cold.new_directory(destination)
    for name, source in ((c.ASSET, b), ('dawn-selfhost.jar', qualification / 'jvm/jdk-21.jar'),
                          ('install-native.py', HERE / 'install-native.py')):
        shutil.copyfile(source, destination / name)
    for name in (c.ASSET, 'dawn-selfhost.jar'):
        (destination / (name + '.sha256')).write_text(c.digest((destination / name).read_bytes()) + '  ' + name + '\n')
    c.atomic_json(destination / 'native-bootstrap.json', proof)
    c.atomic_json(destination / 'dawn-toolchain.json', info)
    # API reports are explicit placeholders: this rehearsal proves identity aggregation only.
    c.atomic_json(destination / 'dawn-pub-api.json', {'prototype_only': True})
    (destination / 'dawn-pub-api-diff.md').write_text('Isolated protocol rehearsal placeholder.\n')
    identity.aggregate(destination, 'v' + version)
    return info


def publish(directory, store, tag):
    identity.aggregate(directory, tag)
    store = c.safe_destination(store)
    store.mkdir(parents=True, exist_ok=True)
    destination = store / tag
    c.require(not destination.exists(), 'prototype-immutable', 'tag already exists; choose a new release tag')
    with tempfile.TemporaryDirectory(prefix='pending-', dir=store) as temporary:
        staged = Path(temporary) / 'assets'
        shutil.copytree(directory, staged)
        identity.aggregate(staged, tag)
        # A no-replace directory commit rejects an existing nonempty immutable release.
        os.rename(staged, destination)
    return destination


def rehearse(qualification, destination):
    destination = cold.new_directory(destination)
    production = ('scripts/release-native.sh', 'scripts/install-native.py', '.github/workflows/release.yml')
    before = {name: c.digest((ROOT / name).read_bytes()) for name in production}
    staging = destination / 'staging'
    # Exercise the shell producer, rather than a separate in-memory metadata constructor.
    result = subprocess.run(['bash', str(HERE / 'release-native.sh'), '--package', str(qualification),
                             '--out', str(staging)], capture_output=True)
    (destination / 'producer.stdout').write_bytes(result.stdout)
    (destination / 'producer.stderr').write_bytes(result.stderr)
    c.require(result.returncode == 0, 'prototype-producer', 'isolated shell producer failed')
    info = c.read_json(staging / 'dawn-toolchain.json')
    tag = info['release']['tag']
    published = publish(staging, destination / 'releases', tag)
    baseline = {p.name: c.digest(p.read_bytes()) for p in published.iterdir()}
    rows = [q.refused('immutable-tag-reupload', 'prototype-immutable',
                     lambda: publish(staging, destination / 'releases', tag))]
    spec = importlib.util.spec_from_file_location('prototype_installer', HERE / 'install-native.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    prefix = destination / 'prefix'
    target = installer.install(staging, prefix, tag)
    old = target.read_bytes()
    c.require(c.digest(old) == info['native']['sha256'], 'prototype-install', 'installed different B')
    cases = (
        ('schema1', 'prototype-schema', lambda x: x.update(schema=1)),
        ('unknown-schema', 'prototype-schema', lambda x: x.update(schema=999)),
        ('bool-schema', 'prototype-schema', lambda x: x.update(schema=True)),
        ('native-is-jar', 'prototype-type', lambda x: x['native'].update(kind='jvm-jar')),
        ('builder-is-jar-name', 'prototype-type', lambda x: x['builder'].update(name='dawn-selfhost.jar')),
        ('unknown-builder', 'prototype-type', lambda x: x['builder'].update(kind='unknown')),
        ('wrong-builder-stage', 'prototype-type', lambda x: x['builder'].update(stage='S')),
        ('wrong-native-stage', 'prototype-type', lambda x: x['native'].update(stage='C')),
        ('wrong-target', 'prototype-type', lambda x: x['native'].update(target='aarch64-unknown-linux-gnu')),
        ('wrong-parent', 'schema', lambda x: x['bootstrap'].update(parent_receipt_sha256='bad')),
        ('wrong-pair', 'prototype-lineage', lambda x: x['bootstrap']['std'].update(commit='0' * 40)),
        ('wrong-reference', 'prototype-identity', lambda x: x['jvm_reference'].update(commit='0' * 40)),
        ('wrong-size', 'prototype-digest', lambda x: x['native'].update(size=x['native']['size'] + 1)),
        ('wrong-native-hash', 'prototype-digest', lambda x: x['native'].update(sha256='0' * 64)),
        ('wrong-full-b1', 'prototype-version', lambda x: x['native'].update(build_id='b1:' + '0' * 64)))
    metadata_path = staging / 'dawn-toolchain.json'
    original = metadata_path.read_bytes()
    for name, code, mutate in cases:
        changed = copy.deepcopy(info)
        mutate(changed)
        metadata_path.write_bytes(c.canonical(changed))
        rows.append(q.refused(name, code, lambda: installer.install(staging, prefix, tag)))
        c.require(target.read_bytes() == old, 'prototype-install', 'failed install changed the old binary')
    metadata_path.write_bytes(original[:-2] + b',"schema":2}\n')
    rows.append(q.refused('duplicate-json-key', 'schema', lambda: installer.install(staging, prefix, tag)))
    metadata_path.write_bytes(original)
    for name in (c.ASSET, c.ASSET + '.sha256'):
        path = staging / name
        saved = path.read_bytes()
        path.write_bytes(saved + b'changed')
        rows.append(q.refused('wrong-' + name, 'prototype-digest', lambda: installer.install(staging, prefix, tag)))
        path.write_bytes(saved)
    proof = staging / 'native-bootstrap.json'
    saved = proof.read_bytes()
    proof.write_bytes(saved + b' ')
    rows.append(q.refused('wrong-proof', 'prototype-proof', lambda: identity.aggregate(staging, tag)))
    proof.write_bytes(saved)
    (staging / 'dawn-pub-api-diff.md').unlink()
    rows.append(q.refused('missing-asset', 'prototype-assets', lambda: identity.aggregate(staging, tag)))
    shutil.copyfile(published / 'dawn-pub-api-diff.md', staging / 'dawn-pub-api-diff.md')
    jvm_arm = copy.deepcopy(info)
    jvm = c.read_json(qualification / 'jvm/summary.json')
    listing = subprocess.run([jvm['arms'][0]['java'], '-XX:-UsePerfData', '-jar',
                              str(qualification / 'jvm/jdk-21.jar'), 'version', '-m',
                              str(qualification / 'jvm/jdk-21.jar')], capture_output=True)
    ids = re.findall(rb'^\tbuild\t(b1:[0-9a-f]{64})$', listing.stdout, re.M)
    c.require(listing.returncode == 0 and not listing.stderr and len(ids) == 1,
              'prototype-version', 'JVM arm identity probe failed')
    jvm_arm['builder'].update(kind='jvm-jar', name='dawn-selfhost.jar', stage='JVM',
                              sha256=info['jvm_reference']['sha256'], build_id=ids[0].decode())
    identity.metadata(jvm_arm, tag)
    rows.append(q.refused('jvm-arm-is-not-native-qualification', 'prototype-type',
                          lambda: identity.metadata(jvm_arm, tag, native_required=True)))
    identity.aggregate(staging, tag)
    c.require(target.read_bytes() == old and baseline == {p.name: c.digest(p.read_bytes()) for p in published.iterdir()},
              'prototype-immutable', 'failed control changed installation or published assets')
    c.require(before == {name: c.digest((ROOT / name).read_bytes()) for name in production},
              'prototype-production', 'production files changed')
    summary = {'schema': 1, 'kind': 'native-schema2-rehearsal', 'prototype_only': True,
               'source_commit': info['release']['commit'], 'production_files': before,
               'isolated_assets': baseline, 'metadata': info, 'controls': rows,
               'installation_inputs': [c.ASSET, c.ASSET + '.sha256', 'dawn-toolchain.json'],
               'installer_proves_bootstrap': False, 'production_asset_count': 8,
               'prototype_asset_count': 9, 'jvm_type_arm_validated': True,
               'standalone_installer_packaging_pending': True}
    c.atomic_json(destination / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('produce', 'publish', 'rehearse'))
    parser.add_argument('--package', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--from-dir', type=Path)
    parser.add_argument('--store', type=Path)
    parser.add_argument('--tag')
    args = parser.parse_args()
    try:
        if args.command == 'publish':
            c.require(all((args.from_dir, args.store, args.tag)), 'arguments', 'local staging, store and tag required')
            publish(args.from_dir, args.store, args.tag)
        else:
            c.require(args.package and args.out, 'arguments', 'qualification package and new output required')
            (produce if args.command == 'produce' else rehearse)(args.package.absolute(), args.out.absolute())
        print('OK isolated schema 2 protocol rehearsal; no release service used')
    except (c.Rejected, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f'REJECT {exc}', file=sys.stderr)
        sys.exit(1)
