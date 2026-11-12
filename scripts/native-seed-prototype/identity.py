"""Isolated schema 2 rehearsal. No production release or installation caller."""

from pathlib import Path
import re

from native_seed import contract as c

ASSETS = ('dawn-selfhost.jar', 'dawn-selfhost.jar.sha256', c.ASSET, c.ASSET + '.sha256',
          'dawn-toolchain.json', 'install-native.py', 'dawn-pub-api.json',
          'dawn-pub-api-diff.md', 'native-bootstrap.json')


def build_id(value):
    c.require(type(value) is str and re.fullmatch('b1:[0-9a-f]{64}', value),
              'prototype-identity', 'full build ID required')


def metadata(value, tag, native_required=False):
    c.fields(value, 'schema release native builder bootstrap recipe proof jvm_reference', 'metadata')
    c.require(type(value['schema']) is int and value['schema'] == 2,
              'prototype-schema', 'schema 2 required; no historical compatibility')
    release = value['release']
    c.fields(release, 'tag version commit', 'release')
    c.require(type(tag) is str and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) and
              release['tag'] == tag and release['version'] == tag[1:],
              'prototype-identity', 'release tag/version differs')
    c.oid(release['commit'], 'release commit')
    native = value['native']
    c.fields(native, 'name kind stage sha256 size build_id target', 'native')
    c.require((native['name'], native['kind'], native['stage'], native['target']) ==
              (c.ASSET, 'native-elf', 'B', c.TARGET), 'prototype-type', 'native identity differs')
    c.sha(native['sha256'], 'native')
    c.require(type(native['size']) is int and native['size'] > 0, 'prototype-identity', 'invalid size')
    build_id(native['build_id'])
    builder = value['builder']
    c.fields(builder, 'name kind stage sha256 version build_id', 'builder')
    c.require((builder['kind'], builder['name'], builder['stage']) in
              (('native-elf', 'dawnc-stage-a', 'A'), ('jvm-jar', 'dawn-selfhost.jar', 'JVM')),
              'prototype-type', 'builder kind/name/stage differs')
    c.require(not native_required or builder['kind'] == 'native-elf',
              'prototype-type', 'native qualification requires the native builder arm')
    c.require(builder['version'] == release['version'], 'prototype-identity', 'builder version differs')
    c.sha(builder['sha256'], 'builder')
    build_id(builder['build_id'])
    bootstrap = value['bootstrap']
    c.fields(bootstrap, 'seed std runtime parent_receipt_sha256', 'bootstrap')
    seed = bootstrap['seed']
    c.fields(seed, 'kind tag commit asset sha256 size target version build_id', 'bootstrap seed')
    c.require(seed['kind'] == 'native-elf' and seed['asset'] == c.ASSET and seed['target'] == c.TARGET and
              type(seed['tag']) is str and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', seed['tag']) and
              seed['version'] == 'dawnc ' + seed['tag'][1:] + ' (native)' and
              tuple(map(int, seed['tag'][1:].split('.'))) <= tuple(map(int, tag[1:].split('.'))),
              'prototype-lineage', 'invalid bootstrap seed identity')
    c.oid(seed['commit'], 'bootstrap commit')
    c.sha(seed['sha256'], 'bootstrap seed')
    c.require(type(seed['size']) is int and seed['size'] > 0, 'prototype-lineage', 'invalid seed size')
    build_id(seed['build_id'])
    for name in ('std', 'runtime'):
        c.validate_identity(bootstrap[name], name)
        c.require(bootstrap[name]['commit'] == seed['commit'], 'prototype-lineage', 'seed pair differs')
    if bootstrap['parent_receipt_sha256'] is not None:
        c.sha(bootstrap['parent_receipt_sha256'], 'parent receipt')
    c.fields(value['recipe'], 'inputs_sha256 toolchain_sha256 recipe_sha256', 'recipe')
    for key, digest in value['recipe'].items():
        c.sha(digest, key)
    c.fields(value['proof'], 'name sha256', 'proof')
    c.require(value['proof']['name'] == 'native-bootstrap.json', 'prototype-type', 'wrong proof name')
    c.sha(value['proof']['sha256'], 'proof')
    reference = value['jvm_reference']
    c.fields(reference, 'name kind sha256 commit jdk_equivalence_sha256', 'JVM reference')
    c.require(reference['name'] == 'dawn-selfhost.jar' and reference['kind'] == 'jvm-jar' and
              reference['commit'] == release['commit'], 'prototype-identity', 'JVM reference differs')
    c.sha(reference['sha256'], 'JVM reference')
    c.sha(reference['jdk_equivalence_sha256'], 'JDK equivalence')
    return value


def payload(directory, value):
    data = c.regular_bytes(directory / c.ASSET)
    native = value['native']
    c.require(len(data) == native['size'] and c.digest(data) == native['sha256'] and
              c.regular_bytes(directory / (c.ASSET + '.sha256')) ==
              (native['sha256'] + '  ' + c.ASSET + '\n').encode(),
              'prototype-digest', 'native payload or sidecar differs')
    c.verify_elf(data)
    return data


def aggregate(directory, tag):
    directory = Path(directory)
    c.require(sorted(p.name for p in directory.iterdir()) == sorted(ASSETS),
              'prototype-assets', 'isolated nine-asset contract differs')
    value = metadata(c.read_json(directory / 'dawn-toolchain.json'), tag, native_required=True)
    payload(directory, value)
    proof = c.read_json(directory / 'native-bootstrap.json')
    c.fields(proof, 'schema kind prototype_only source_commit qualification_sha256 cold_sha256 builder_sha256 native_sha256', 'proof')
    c.require(proof['schema'] == 2 and proof['kind'] == 'native-bootstrap-prototype' and
              proof['prototype_only'] is True and proof['source_commit'] == value['release']['commit'] and
              proof['builder_sha256'] == value['builder']['sha256'] and
              proof['native_sha256'] == value['native']['sha256'] and
              c.digest(c.regular_bytes(directory / 'native-bootstrap.json')) == value['proof']['sha256'],
              'prototype-proof', 'proof identity differs')
    for name in ('qualification_sha256', 'cold_sha256', 'builder_sha256', 'native_sha256'):
        c.sha(proof[name], name)
    jar = c.regular_bytes(directory / 'dawn-selfhost.jar')
    c.require(c.digest(jar) == value['jvm_reference']['sha256'] and
              c.regular_bytes(directory / 'dawn-selfhost.jar.sha256') ==
              (c.digest(jar) + '  dawn-selfhost.jar\n').encode(), 'prototype-digest', 'JVM bytes differ')
    return value
