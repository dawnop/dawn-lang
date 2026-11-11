#!/usr/bin/env python3
"""Compare the class-data host against the candidate's real reflection host.

The candidate JAR already contains the white-box entries, so a tiny Java
launcher can reuse it. Native analysis runs inside the existing compiler test
compilation. Raw oracle files stay local; ordinary gate logs contain summaries.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import zipfile

from prepare import prepare as prepare_jdk

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def run(command, work, label):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True)
    (work / (label + '.stdout')).write_bytes(result.stdout)
    (work / (label + '.stderr')).write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError(label + ' failed\n' + result.stdout.decode(errors='replace')
                           + result.stderr.decode(errors='replace'))


def query(name, *arguments):
    return dict(query=name, args=list(arguments))


def queries(names):
    result = []
    for name in names:
        result.extend(query(operation, name) for operation in [
            'find_class', 'class_info', 'methods_of', 'ctors_of',
            'static_fields_of', 'sam_of', 'component_of'])
        result.append(query('is_assignable', 'java.lang.Object', name))
    arrays = ['[Z', '[B', '[C', '[S', '[I', '[J', '[F', '[D', '[[I', '[[[I',
              '[Ljava.lang.String;', '[[Ljava.lang.String;', '[Ljava.lang.Object;',
              '[Ljava.util.Map$Entry;']
    arrays += [prefix + name + ';' for name in names if name.startswith('fixture.')
               for prefix in ['[L', '[[L']]
    for name in arrays:
        result.extend(query(operation, name) for operation in [
            'find_class', 'class_info', 'methods_of', 'ctors_of',
            'static_fields_of', 'sam_of', 'component_of'])
        for parent in ['java.lang.Object', 'java.lang.Cloneable', 'java.io.Serializable',
                       '[Ljava.lang.Object;', '[I', '[[I']:
            result.append(query('is_assignable', parent, name))
    result += [query('find_class', 'java.util.Map.Entry'), query('find_class', 'no.such.Type'),
               query('find_class', 'int'), query('find_class', '[V'),
               query('find_class', '[' * 256 + 'I'),
               query('is_assignable', 'int', 'int'),
               query('is_assignable', 'java.lang.Object', 'no.such.Type')]
    return result


def patch_synthetic(data):
    raw = bytearray(data)
    at = 8
    count = struct.unpack_from('>H', raw, at)[0]
    at += 2
    strings = {}
    index = 1
    while index < count:
        tag = raw[at]
        at += 1
        if tag == 1:
            size = struct.unpack_from('>H', raw, at)[0]
            at += 2
            strings[index] = bytes(raw[at:at + size]).decode()
            at += size
        elif tag in (5, 6):
            at += 8
            index += 1
        else:
            at += {3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4,
                   12: 4, 15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2}[tag]
        index += 1
    at += 6
    interfaces = struct.unpack_from('>H', raw, at)[0]
    at += 2 + 2 * interfaces
    for kind in ['fields', 'methods']:
        count = struct.unpack_from('>H', raw, at)[0]
        at += 2
        for _ in range(count):
            access, name, descriptor, attributes = struct.unpack_from('>HHHH', raw, at)
            if kind == 'methods' and (strings[name] == 'syntheticOnly' or
                                     (strings[name] == '<init>' and strings[descriptor] == '(I)V')):
                struct.pack_into('>H', raw, at, access | 0x1000)
            at += 8
            for _ in range(attributes):
                size = struct.unpack_from('>I', raw, at + 2)[0]
                at += 6 + size
    return bytes(raw)


def fixture_pack(work, jdk_data, variant):
    classes = work / ('classes-' + variant)
    classes.mkdir()
    isolated = work / ('source-' + variant) / 'fixture/Isolated.java'
    isolated.parent.mkdir(parents=True)
    returned = 'int' if variant == 'a' else 'String'
    value = '1' if variant == 'a' else '"other"'
    isolated.write_text('package fixture; public final class Isolated { public '
                        + returned + ' value() { return ' + value + '; } }\n')
    jdk = Path(os.environ['JAVA_HOME'])
    run([jdk / 'bin/javac', '--release', '21', '-g:none', '-d', classes,
         HERE / 'Signatures.java', isolated], work, 'compile-fixture-' + variant)
    fixture_bytes = {}
    for path in sorted(classes.rglob('*.class')):
        data = patch_synthetic(path.read_bytes())
        path.write_bytes(data)
        fixture_bytes[path.relative_to(classes).as_posix()] = data
    jar = work / ('fixture-' + variant + '.jar')
    with zipfile.ZipFile(jar, 'w') as archive:
        for name, data in fixture_bytes.items():
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(entry, data)
    jar_hash = hashlib.sha256(jar.read_bytes()).hexdigest()
    manifest = json.loads((jdk_data / 'manifest.json').read_bytes())
    pack = work / ('pack-' + variant)
    pack.mkdir()
    for entry in manifest['classes']:
        target = pack / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(jdk_data / entry['path'], target)
    names = []
    for relative, data in fixture_bytes.items():
        name = relative[:-6].replace('/', '.')
        path = 'classes/fixture/' + relative
        target = pack / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest['classes'].append(dict(name=name, module='fixture', path=path,
                                       size=len(data), sha256=hashlib.sha256(data).hexdigest()))
        names.append(name)
    manifest['classes'].sort(key=lambda x: x['name'])
    manifest['modules'].append(dict(name='fixture', sha256=jar_hash))
    manifest['modules'].sort(key=lambda x: x['name'])
    manifest['required_roots'] = sorted(set(manifest['required_roots'] + names))
    table = json.dumps(manifest['classes'], sort_keys=True, separators=(',', ':')).encode()
    manifest['classes_sha256'] = hashlib.sha256(table).hexdigest()
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    (pack / 'manifest.json').write_bytes(raw)
    return dict(name='fixture-' + variant, manifest=str(pack / 'manifest.json'),
                hash=hashlib.sha256(raw).hexdigest(), jars=[str(jar)], imports=names,
                queries=queries(names), analyses=[])


def source_cases(work):
    result = []
    sources = {
        'bridges': ('ok', '', '''use java "fixture.Signatures.Facade"
use java "fixture.Signatures.Child"
pub fn exposing(x: Facade) -> Int !io = x.length()
pub fn generic(x: Child) -> Int !io = x.compare("value")
pub fn covariant(x: Child) -> Option[String] !io = x.value()
'''),
        'arrays': ('ok', '', '''use java "fixture.Signatures.Utilities"
pub fn arrays() -> Unit !io = {
  Utilities.integers(Utilities.ints().expect("ints"))
  Utilities.objects(Utilities.strings().expect("strings"))
  Utilities.objects(Utilities.matrix().expect("matrix"))
}
'''),
        'sam': ('ok', '', '''use java "fixture.Signatures.Utilities"
pub fn sam() -> Unit !io = Utilities.stringSam((s: String) => println(s))
'''),
        'bad-member': ('source-error', 'no method', '''use java "java.io.InputStream"
pub fn visible() -> Int = 1
fn hidden(s: InputStream) -> Unit !io = {
  let _ = s.missingMember()
  ()
}
'''),
        'private-body': ('source-error', 'constructor', '''use java "java.net.URI"
pub fn visible() -> Int = 1
fn hidden() -> Unit !io = {
  let _ = URI.new(true)
  ()
}
'''),
        'bad-overload': ('source-error', 'read', '''use java "java.io.InputStream"
pub fn visible() -> Int = 1
fn hidden(s: InputStream) -> Unit !io = {
  let _ = s.read("bad")
  ()
}
'''),
        'bad-array': ('source-error', 'objects', '''use java "fixture.Signatures.Utilities"
pub fn arrays() -> Unit !io = Utilities.objects(Utilities.ints().expect("ints"))
'''),
        'bad-sam': ('source-error', 'stringSam', '''use java "fixture.Signatures.Utilities"
pub fn sam() -> Unit !io = Utilities.stringSam((n: Int) => println(n))
'''),
        'erased-return': ('ok', '', '''use java "java.net.http.HttpResponse"
use java "java.lang.Object"
pub fn body(response: HttpResponse) -> Option[Object] !io = response.body()
'''),
        'bad-generic-return': ('source-error', 'InputStream', '''use java "java.net.http.HttpResponse"
use java "java.io.InputStream"
pub fn body(response: HttpResponse) -> Option[InputStream] !io = response.body()
'''),
        'bad-doc-link': ('doc-error', 'missing_link', '''## [`missing_link`] must resolve.
pub fn visible() -> Int = 1
'''),
        'bad-private-leak': ('source-error', 'Hidden', '''type Hidden = { value: Int }
pub fn expose(x: Hidden) -> Int = x.value
'''),
        'bad-effect': ('source-error', 'io', '''use java "java.io.InputStream"
pub fn read(s: InputStream) -> Int = s.read()
'''),
    }
    for name, (expected, contains, source) in sources.items():
        path = work / 'sources' / (name.replace('-', '_') + '.dawn')
        path.parent.mkdir(exist_ok=True)
        path.write_text(source)
        result.append(dict(name=name, path=str(path), expected=expected, contains=contains))
    dependency = work / 'dependency'
    (dependency / 'src').mkdir(parents=True)
    (dependency / 'dawn.toml').write_text('schema = 1\nname = "signature_dep"\n')
    (dependency / 'src/lib.dawn').write_text('''use java "java.lang.String"
pub fn value() -> Int = 1
test "dependency body is checked" {
  let _ = String.missingDependencyMember()
}
''')
    app = work / 'app'
    (app / 'src').mkdir(parents=True)
    (app / 'dawn.toml').write_text('schema = 1\nname = "signature_app"\n[deps]\ndep = "../dependency"\n')
    (app / 'src/main.dawn').write_text('use dep/lib\npub fn visible() -> Int = lib.value()\n')
    result.append(dict(name='bad-dependency-test', path=str(app), expected='source-error', contains='missingDependencyMember'))
    return result


def prepare(work, jdk_data=None):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if jdk_data is None:
        jdk_data = work / 'jdk'
        prepare_jdk(os.environ['JAVA_HOME'], jdk_data)
    jdk_data = Path(jdk_data).resolve()
    raw = (jdk_data / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    requests = [dict(name='locked-jdk', manifest=str(jdk_data / 'manifest.json'),
                     hash=hashlib.sha256(raw).hexdigest(), jars=[],
                     imports=manifest['required_roots'],
                     queries=queries([c['name'] for c in manifest['classes']]),
                     analyses=[dict(name='web-jvm', path=str(ROOT / 'packages/web-jvm'), expected='ok', contains='')])]
    a = fixture_pack(work, jdk_data, 'a')
    b = fixture_pack(work, jdk_data, 'b')
    a['analyses'] = source_cases(work)
    repeat = dict(a, name='fixture-a-repeat', analyses=[])
    requests.extend([a, b, repeat])
    (work / 'requests.json').write_text(json.dumps(requests, indent=2) + '\n')
    return work


def snapshot(work, backend, output):
    jdk = Path(os.environ['JAVA_HOME'])
    classes = work / 'launcher'
    classes.mkdir(exist_ok=True)
    run([jdk / 'bin/javac', '--release', '21', '-d', classes, HERE / 'Snapshot.java'],
        work, 'compile-launcher')
    classpath = str(classes) + os.pathsep + str(ROOT / 'build/dawn-selfhost.jar')
    run([jdk / 'bin/java', '-Xss64m', '-Xmx2g', '-XX:+UseSerialGC',
         '--add-exports', 'java.base/jdk.internal.vm=ALL-UNNAMED',
         '-cp', classpath, 'Snapshot', backend, work / 'requests.json', output],
        work, backend + '-snapshot')


def canonical(value):
    result = json.loads(json.dumps(value))
    for group in result:
        for row in group['queries']:
            if row['query'] in ['methods_of', 'ctors_of', 'static_fields_of']:
                row['result'].sort(key=lambda x: json.dumps(x, sort_keys=True))
    return result


def validate_expected(work, output):
    expected = json.loads((work / 'requests.json').read_text())
    actual = json.loads(output.read_text())
    if len(expected) != len(actual):
        raise AssertionError('signature context count differs')
    cases = 0
    for group, result in zip(expected, actual):
        if len(group['analyses']) != len(result['analyses']):
            raise AssertionError('analysis case count differs')
        for request, answer in zip(group['analyses'], result['analyses']):
            if answer['name'] != request['name'] or answer['status'] != request['expected']:
                (work / 'analysis-mismatch.json').write_text(json.dumps(dict(request=request, actual=answer), indent=2) + '\n')
                raise AssertionError('unexpected analysis result: ' + request['name'] + ': ' + answer['status'])
            diagnostic_messages = '\n'.join(line for line in answer['diagnostics'].splitlines()
                                            if line.startswith(('error:', 'note:')) or 'doc link' in line)
            if request['contains'] not in diagnostic_messages:
                raise AssertionError('wrong analysis failure: ' + request['name'])
            if (answer['doc'] is not None) != (request['expected'] == 'ok'):
                raise AssertionError('partial or missing documentation: ' + request['name'])
            cases += 1
        for answer in result['queries']:
            operation = answer['query']
            value = answer['result']
            fields = {'find_class': {'fqcn', 'simple', 'display', 'is_interface', 'is_primitive', 'is_array'},
                      'class_info': {'fqcn', 'simple', 'display', 'is_interface', 'is_primitive', 'is_array'},
                      'methods_of': {'name', 'param_cls', 'ret_cls', 'is_static', 'is_varargs', 'is_abstract', 'desc', 'decl_cls'},
                      'ctors_of': {'param_cls', 'is_varargs', 'desc'},
                      'static_fields_of': {'name', 'type_cls', 'decl_cls'},
                      'sam_of': {'name', 'param_cls', 'ret_cls', 'is_static', 'is_varargs', 'is_abstract', 'desc', 'decl_cls'}}
            if operation in fields and value is not None:
                values = value if isinstance(value, list) else [value]
                if any(set(v) != fields[operation] for v in values):
                    raise AssertionError('signature record field coverage differs: ' + operation)
    return cases


def compare(work):
    cases = validate_expected(work, work / 'reflection.json')
    validate_expected(work, work / 'native.json')
    expected = canonical(json.loads((work / 'reflection.json').read_text()))
    actual = canonical(json.loads((work / 'native.json').read_text()))
    if len(expected) != len(actual):
        raise AssertionError('signature context count differs')
    count = 0
    for left, right in zip(expected, actual):
        if left['name'] != right['name'] or len(left['queries']) != len(right['queries']):
            raise AssertionError('signature request identity differs')
        for a, b in zip(left['queries'], right['queries']):
            if a != b:
                (work / 'mismatch.json').write_text(json.dumps(dict(expected=a, actual=b), indent=2) + '\n')
                raise AssertionError('signature mismatch: ' + a['query'] + ' ' + str(a['args']))
            count += 1
        if left['analyses'] != right['analyses']:
            raise AssertionError('complete Java analysis differs: ' + left['name'])
    print('PASS Java signature oracle: ' + str(count) + ' queries, ' + str(cases) + ' complete analyses')
    (work / 'summary.json').write_text(json.dumps(dict(queries=count, contexts=len(actual), analyses=cases), indent=2) + '\n')


def qualify_jvm(work, jdk_data=None):
    work = prepare(work, jdk_data)
    snapshot(work, 'reflection', work / 'reflection.json')
    validate_expected(work, work / 'reflection.json')
    snapshot(work, 'native', work / 'native.json')
    compare(work)


def prepare_native(work):
    from run import fixtures
    work = Path(work).resolve()
    structure = work / 'structure'
    structure.mkdir(parents=True)
    path, _ = fixtures(structure, os.environ['JAVA_HOME'])
    shutil.copyfile(path, work / 'structure.json')
    prepare(work, structure / 'jdk')
    print('Java signature fixtures prepared')


def augment_entry(entry):
    # Append a test to the explicit captured file; no production command is
    # patched and no existing source text is located by a mutation anchor.
    original = entry.read_text()
    prefix = ('# Share the existing compiler test compilation with metadata analysis.\n'
              'use java_signature_probe as javasig\nuse contract/metadata\n')
    entry.write_text(prefix + original + '''

test "locked Java signatures and complete analysis" {
  io.with_env_real(() => {
    let work = io.getenv("DAWN_JAVA_SIGNATURE_WORK").expect("signature fixture directory")
    metadata.run_cases(work ++ "/structure.json")
    javasig.native_to_file(work ++ "/requests.json", work ++ "/native.json")
  })
}
''')


def compare_native(work, log):
    from run import NATIVE_INLINE_TESTS
    text = log.read_text()
    labels = ['PASS  ' + module + ' :: ' + name + '\n'
              for module, names in NATIVE_INLINE_TESTS.items() for name in names]
    labels += ['PASS  check/jclasssig :: ' + name + '\n' for name in [
        'metadata signatures retain exposing bridges and remove covered bridges',
        'metadata signatures exclude Object and static interface inheritance from SAM',
        'metadata assignability distinguishes reference and primitive array components',
        'metadata signature indexes isolate same names and bound retained rows',
        'metadata signature text bounds shared long member names before rendering']]
    labels.append('PASS  nmain :: locked Java signatures and complete analysis\n')
    if any(text.count(label) != 1 for label in labels) or text.count('67 metadata cases passed\n') != 1:
        raise AssertionError('native metadata test ownership or directory cases differ')
    snapshot(work, 'reflection', work / 'reflection.json')
    compare(work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--prepare-native', action='store_true')
    parser.add_argument('--entry', type=Path)
    parser.add_argument('--native-log', type=Path)
    args = parser.parse_args()
    if args.entry:
        augment_entry(args.entry)
    elif args.prepare_native:
        prepare_native(args.out)
    elif args.native_log:
        compare_native(args.out, args.native_log)
    else:
        qualify_jvm(args.out)


if __name__ == '__main__':
    main()
