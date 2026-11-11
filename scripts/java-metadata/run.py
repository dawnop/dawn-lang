#!/usr/bin/env python3
"""Exercise bounded metadata inputs through the existing JVM or native driver.

One probe process reads the same raw fixtures and complete locked JDK view.
Malformed bytes and directory mutations must return typed errors. The harness
keeps the independent fixture construction outside the production reader.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import tempfile

from prepare import prepare, LOCK

ROOT = Path(__file__).resolve().parents[2]
U2 = lambda value: struct.pack('>H', value)
U4 = lambda value: struct.pack('>I', value)
NATIVE_INLINE_TESTS = {
    'check/classmeta': [
        'bounded class reader retains fields descriptors throws and synthetic',
        'every truncated class prefix is an explicit error',
        'class reader refuses bad magic version preview CP and trailing bytes',
        'modified UTF-8 rejects malformed encodings and retains UTF-16 units',
        'descriptors preserve reference names arrays components and parameter slots',
    ],
    'driver/jmetadata': [
        'metadata graph rejects missing roots signatures parents and cycles',
        'manifest parser refuses ambiguous keys and canonicalizes object order',
        'signature construction rejects missing imports before enabling queries',
    ],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ClassBuilder:
    def __init__(self):
        self.pool = []

    def entry(self, data):
        self.pool.append(data)
        return len(self.pool)

    def utf(self, text):
        data = text.encode('utf-8')
        return self.entry(b'\x01' + U2(len(data)) + data)

    def cls(self, name):
        return self.entry(b'\x07' + U2(self.utf(name)))

    def attribute(self, name, payload):
        return U2(self.utf(name)) + U4(len(payload)) + payload


def class_bytes(name, parent='java/lang/Object', access=0x21, sample=False, returned=None):
    builder = ClassBuilder()
    this_index = builder.cls(name)
    super_index = builder.cls(parent) if parent else 0
    fields = b''
    methods = b''
    if sample:
        fields = U2(0x19) + U2(builder.utf('value')) + U2(builder.utf('J')) + U2(1)
        fields += builder.attribute('Synthetic', b'')
        methods = U2(0x401) + U2(builder.utf('read'))
        methods += U2(builder.utf(returned or '([B)I')) + U2(1)
        methods += builder.attribute('Exceptions', U2(1) + U2(builder.cls('java/io/IOException')))
    data = U4(0xCAFEBABE) + U2(0) + U2(65) + U2(len(builder.pool) + 1)
    data += b''.join(builder.pool)
    data += U2(access) + U2(this_index) + U2(super_index) + U2(0)
    return data + U2(bool(fields)) + fields + U2(bool(methods)) + methods + U2(0)


def fixture_classes():
    return {
        'java.lang.Object': class_bytes('java/lang/Object', parent=None),
        'java.lang.String': class_bytes('java/lang/String', access=0x31),
        'java.lang.Cloneable': class_bytes('java/lang/Cloneable', access=0x601),
        'java.io.Serializable': class_bytes('java/io/Serializable', access=0x601),
        'java.io.IOException': class_bytes('java/io/IOException'),
        'p.Sample': class_bytes('p/Sample', access=0x421, sample=True),
    }


def write_pack(path, classes):
    template = json.loads(LOCK.read_bytes())
    entries = []
    for name, data in sorted(classes.items()):
        relative = 'classes/fixture/' + name.replace('.', '/') + '.class'
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append(dict(name=name, module='fixture', path=relative, size=len(data), sha256=digest(data)))
    template['modules'] = [dict(name='fixture', sha256='0' * 64)]
    template['required_roots'] = ['p.Sample']
    template['classes'] = entries
    write_manifest(path, template)
    return template


def write_manifest(path, manifest):
    table = json.dumps(manifest['classes'], sort_keys=True, separators=(',', ':')).encode()
    manifest['classes_sha256'] = digest(table)
    (path / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n')


def fixtures(work, jdk):
    cases = []

    def case(name, path, expected, mode='context', pin=''):
        cases.append(dict(name=name, path=str(path), expected=expected, mode=mode, hash=pin))

    jdk_path = work / 'jdk'
    pin = prepare(jdk, jdk_path)
    case('locked-jdk', jdk_path / 'manifest.json', 'ok', pin=pin)
    case('wrong-manifest-pin', jdk_path / 'manifest.json', 'identity', pin='0' * 64)
    base = fixture_classes()
    write_pack(work / 'valid', base)
    case('hand-built-context', work / 'valid/manifest.json', 'ok')
    patched = write_pack(work / 'changed-jdk-patch', base)
    original_pin = digest((work / 'changed-jdk-patch/manifest.json').read_bytes())
    patched['platform']['runtime_version'] = '21.0.3+fixture'
    write_manifest(work / 'changed-jdk-patch', patched)
    case('changed-jdk-patch', work / 'changed-jdk-patch/manifest.json', 'identity', pin=original_pin)


    def variant(name, expected, mutate, classes=None):
        path = work / name
        manifest = write_pack(path, classes if classes is not None else base)
        mutate(path, manifest)
        case(name, path / 'manifest.json', expected)

    def manifest_variant(name, expected, mutate):
        def action(path, manifest):
            mutate(manifest)
            write_manifest(path, manifest)
        variant(name, expected, action)

    manifest_variant('wrong-schema', 'schema', lambda m: m.update(schema='unknown'))
    manifest_variant('wrong-view', 'schema', lambda m: m.update(view='unknown'))
    manifest_variant('preview-platform', 'version', lambda m: m['platform'].update(preview=True))
    manifest_variant('future-platform', 'version', lambda m: m['platform'].update(feature=22))
    manifest_variant('java-coordinates', 'schema', lambda m: m.update(java_coords=['x:y:1']))
    manifest_variant('unknown-module', 'schema', lambda m: m['classes'][0].update(module='absent'))
    manifest_variant('bad-hash-spelling', 'schema', lambda m: m['classes'][0].update(sha256='G' * 64))
    manifest_variant('duplicate-module', 'schema', lambda m: m['modules'].append(copy.deepcopy(m['modules'][0])))
    manifest_variant('duplicate-class', 'duplicate-class', lambda m: m['classes'].insert(1, copy.deepcopy(m['classes'][0])))
    manifest_variant('unsorted-classes', 'schema', lambda m: m['classes'].reverse())
    manifest_variant('duplicate-root', 'schema', lambda m: m['required_roots'].append('p.Sample'))
    manifest_variant('missing-root', 'missing-class', lambda m: m.update(required_roots=['Missing']))
    manifest_variant('path-escape', 'path', lambda m: m['classes'][0].update(path='../outside.class'))
    manifest_variant('absolute-path', 'path', lambda m: m['classes'][0].update(path='/outside.class'))
    manifest_variant('wrong-class-size', 'identity', lambda m: m['classes'][-1].update(size=m['classes'][-1]['size'] + 1))
    manifest_variant('class-size-limit', 'limit', lambda m: m['classes'][0].update(size=16777217))
    manifest_variant('negative-size', 'limit', lambda m: m['classes'][0].update(size=-1))
    manifest_variant('wrong-class-hash', 'identity', lambda m: m['classes'][0].update(sha256='0' * 64))
    manifest_variant('class-count-limit', 'limit', lambda m: m.update(classes=m['classes'][:1] * 8193))

    def table_hash(path, manifest):
        manifest['classes_sha256'] = '0' * 64
        (path / 'manifest.json').write_text(json.dumps(manifest))
    variant('wrong-table-hash', 'identity', table_hash)
    variant('unlisted-class', 'identity', lambda p, m: (p / 'classes/extra.class').write_bytes(b'x'))
    variant('changed-class-byte', 'identity', lambda p, m: (p / m['classes'][0]['path']).write_bytes(b'x' + (p / m['classes'][0]['path']).read_bytes()[1:]))
    variant('missing-file', 'path', lambda p, m: (p / m['classes'][0]['path']).unlink())
    variant('different-declared-name', 'identity', lambda p, m: None,
            {**base, 'p.Sample': class_bytes('p/Other', access=0x421, sample=True)})
    variant('missing-parent', 'missing-class', lambda p, m: None,
            {k: v for k, v in base.items() if k != 'java.lang.Object'})
    variant('missing-throws-class', 'missing-class', lambda p, m: None,
            {k: v for k, v in base.items() if k != 'java.io.IOException'})
    variant('missing-descriptor-class', 'missing-class', lambda p, m: None,
            {**base, 'p.Sample': class_bytes('p/Sample', access=0x421, sample=True, returned='()Lmissing/Returned;')})
    variant('inheritance-cycle', 'cycle', lambda p, m: None,
            {**base, 'p.A': class_bytes('p/A', parent='p/B'), 'p.B': class_bytes('p/B', parent='p/A')})

    def symlink_file(path, manifest):
        target = path / manifest['classes'][0]['path']
        original = path / 'outside.class'
        target.rename(original)
        target.symlink_to(original)
    variant('symlink-class', 'path', symlink_file)

    def symlink_directory(path, manifest):
        target = path / 'classes/fixture/java'
        original = path / 'outside-java'
        target.rename(original)
        target.symlink_to(original, target_is_directory=True)
    variant('symlink-directory', 'path', symlink_directory)
    (work / 'linked-manifest.json').symlink_to(work / 'valid/manifest.json')
    case('symlink-manifest', work / 'linked-manifest.json', 'path')
    (work / 'linked-root').symlink_to(work / 'valid', target_is_directory=True)
    (work / 'valid/child').mkdir()
    (work / 'valid/hop').symlink_to(work / 'valid/child', target_is_directory=True)
    case('symlink-before-parent', work / 'valid/hop/../manifest.json', 'path')
    case('ordinary-parent-segment', work / 'valid/child/../manifest.json', 'ok')

    case('symlink-manifest-parent', work / 'linked-root/manifest.json', 'path')
    for name, data in [('invalid-json', b'{'), ('invalid-utf8', b'\xff'),
                       ('duplicate-json-key', b'{"schema":1,"schema":2}'),
                       ('escaped-duplicate-key', b'{"schema":1,"\\u0073chema":2}')]:
        target = work / (name + '.json')
        target.write_bytes(data)
        case(name, target, 'schema')
    target = work / 'oversized-manifest.json'
    with target.open('wb') as stream:
        stream.truncate(16777217)
    case('manifest-size-limit', target, 'limit')

    raw = base['p.Sample']
    for name, at, value, expected in [
        ('bad-magic', 0, 0, 'class-format'), ('old-version', 7, 64, 'version'),
        ('future-version', 7, 66, 'version'), ('preview-class', 4, 255, 'version'),
        ('nonzero-minor', 5, 1, 'version'), ('unknown-cp-tag', 10, 99, 'class-format'),
        ('bad-utf8', 13, 0, 'class-format'), ('bad-cp-count', 8, 255, 'class-format'),
    ]:
        mutated = bytearray(raw)
        mutated[at] = value
        target = work / (name + '.class')
        target.write_bytes(mutated)
        case(name, target, expected, mode='class')
    for name, data in [('trailing-class', raw + b'x'), ('truncated-class', raw[:-1]),
                       ('wide-slot-overrun', U4(0xCAFEBABE) + U2(0) + U2(65) + U2(2) + b'\x05' + b'\0' * 8)]:
        target = work / (name + '.class')
        target.write_bytes(data)
        case(name, target, 'class-format', mode='class')
    path = work / 'cases.json'
    path.write_text(json.dumps(cases, indent=2) + '\n')
    structural_fixtures(work, cases)
    shared = work / 'shared-descriptor.class'
    shared.write_bytes(repeated_descriptor())
    case('shared-descriptor', shared, 'ok', mode='class')

    path.write_text(json.dumps(cases, indent=2) + '\n')
    return path, cases


def repeated_descriptor():
    builder = ClassBuilder()
    this_index = builder.cls('p/Repeated')
    super_index = builder.cls('java/lang/Object')
    descriptor = builder.utf('Lp/' + 'A' * 32760 + ';')
    fields = []
    for index in range(4096):
        fields.append(U2(1) + U2(builder.utf('field' + str(index))) + U2(descriptor) + U2(0))
    data = U4(0xCAFEBABE) + U2(0) + U2(65) + U2(len(builder.pool) + 1) + b''.join(builder.pool)
    data += U2(0x21) + U2(this_index) + U2(super_index) + U2(0)
    return data + U2(len(fields)) + b''.join(fields) + U2(0) + U2(0)

def structural_fixtures(work, cases):
    def emit(name, builder, this_index, super_index, methods=b'', attributes=b'', expected='class-format'):
        data = U4(0xCAFEBABE) + U2(0) + U2(65) + U2(len(builder.pool) + 1) + b''.join(builder.pool)
        data += U2(0x21) + U2(this_index) + U2(super_index) + U2(0) + U2(0)
        data += methods if methods else U2(0)
        data += attributes if attributes else U2(0)
        target = work / (name + '.class')
        target.write_bytes(data)
        cases.append(dict(name=name, path=str(target), expected=expected, mode='class', hash=''))

    for name, kind in [('valid-code', 'valid'), ('code-length-mismatch', 'length'),
                       ('bad-code-range', 'range'), ('bad-code-catch-index', 'catch'),
                       ('duplicate-code', 'duplicate'), ('abstract-code', 'abstract')]:
        builder = ClassBuilder()
        this_index, super_index = builder.cls('p/Code'), builder.cls('java/lang/Object')
        payload = U2(0) + U2(1) + U4(1) + b'\xb1'
        if kind in ('range', 'catch'):
            payload += U2(1) + U2(0) + U2(2 if kind == 'range' else 1) + U2(0)
            payload += U2(1 if kind == 'catch' else 0)
        else:
            payload += U2(0)
        payload += U2(0)
        if kind == 'length':
            payload += b'x'
        method_name, descriptor = builder.utf('f'), builder.utf('()V')
        attribute = builder.attribute('Code', payload)
        method = U2(0x401 if kind == 'abstract' else 1) + U2(method_name) + U2(descriptor)
        method += U2(2 if kind == 'duplicate' else 1) + attribute
        if kind == 'duplicate':
            method += attribute
        emit(name, builder, this_index, super_index, U2(1) + method, expected='ok' if kind == 'valid' else 'class-format')

    builder = ClassBuilder()
    this_index, super_index = builder.cls('p/Unknown'), builder.cls('java/lang/Object')
    unknown = builder.attribute('FutureAttribute', b'opaque')
    emit('unknown-attribute', builder, this_index, super_index, attributes=U2(1) + unknown, expected='ok')
    emit('bad-this-index', builder, 65535, super_index)
    builder = ClassBuilder()
    this_index, super_index = builder.cls('p/Wide'), builder.cls('java/lang/Object')
    builder.entry(b'\x05' + b'\0' * 8)
    builder.entry(b'')
    emit('valid-wide-constant', builder, this_index, super_index, expected='ok')
    builder = ClassBuilder()
    this_index, super_index = builder.cls('p/Utf16'), builder.cls('java/lang/Object')
    string_index = builder.entry(b'\x01' + U2(3) + b'\xed\xa0\x80')
    builder.entry(b'\x08' + U2(string_index))
    emit('unused-utf16-string-constant', builder, this_index, super_index, expected='ok')

    builder = ClassBuilder()
    this_index, super_index = builder.cls('p/Reference'), builder.cls('java/lang/Object')
    name, descriptor = builder.utf('f'), builder.utf('I')
    nt = builder.entry(b'\x0c' + U2(name) + U2(descriptor))
    builder.entry(b'\x0a' + U2(super_index) + U2(nt))
    emit('methodref-field-descriptor', builder, this_index, super_index)
    builder = ClassBuilder()
    this_index, super_index = builder.cls('p/Handle'), builder.cls('java/lang/Object')
    builder.entry(b'\x0f\0' + U2(super_index))
    emit('bad-method-handle-kind', builder, this_index, super_index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-host', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    work = args.out.resolve() if args.out else Path(tempfile.mkdtemp(prefix='java-metadata-contract-'))
    work.mkdir(parents=True, exist_ok=True)
    cases_path, cases = fixtures(work, os.environ['JAVA_HOME'])
    environment = dict(os.environ)
    if args.native_host:
        capture = runpy.run_path(str(ROOT / 'scripts/native-source-tree.py'))['capture']
        entry = capture(work / 'source')
        probe = entry.parent / 'contract/metadata.dawn'
        # One test binary contains both the existing inline tests and the
        # filesystem oracle, sharing its compilation with the inline assertions.
        with probe.open('a') as stream:
            stream.write('''

test "locked metadata directory contract" {
  with_env_real(() => {
    let path = io.getenv("DAWN_JAVA_METADATA_CASES").expect("metadata cases path")
    run_cases(path)
  })
}
''')
        environment['DAWN_JAVA_METADATA_CASES'] = str(cases_path)
        command = [str(args.native_host.resolve()), 'test', str(probe)]
    else:
        probe_jar = work / 'metadata-probe.jar'
        build = subprocess.run([str(ROOT / 'bin/dawn'), 'build', 'selfhost/src/contract/metadata.dawn',
                                '-o', str(probe_jar)], cwd=ROOT, capture_output=True)
        (work / 'build.stdout').write_bytes(build.stdout)
        (work / 'build.stderr').write_bytes(build.stderr)
        if build.returncode:
            raise RuntimeError('metadata probe build failed\n' + build.stderr.decode(errors='replace'))
        command = [str(Path(os.environ['JAVA_HOME']) / 'bin/java'), '-Xss64m', '-Xmx64m',
                   '-XX:+UseSerialGC', '-jar', str(probe_jar), str(cases_path)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, env=environment)
    (work / 'stdout').write_bytes(result.stdout)
    (work / 'stderr').write_bytes(result.stderr)
    expected = ''.join('PASS ' + case['name'] + '\n' for case in cases)
    expected += str(len(cases)) + ' metadata cases passed\n'
    stdout = result.stdout.decode(errors='replace')
    if args.native_host:
        labels = ['PASS  ' + module + ' :: ' + name + '\n'
                  for module, names in NATIVE_INLINE_TESTS.items() for name in names]
        labels.append('PASS  contract/metadata :: locked metadata directory contract\n')
        valid_output = stdout.count(expected) == 1 and all(stdout.count(label) == 1 for label in labels)
    else:
        valid_output = stdout == expected
    if result.returncode or not valid_output:
        raise RuntimeError('metadata probe failed\n' + result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace'))
    print(stdout, end='')
    if args.native_host:
        print('metadata native inline and directory cases passed')
    else:
        from semantic import qualify_jvm
        qualify_jvm(work / 'signatures', work / 'jdk')
    if not args.out:
        shutil.rmtree(work)


if __name__ == '__main__':
    main()
