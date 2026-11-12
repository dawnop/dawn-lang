"""Qualify the actual doc CLI without another compiler build or a Java consumer.

The JVM is the same checkout's byte oracle. Only preparation and that oracle
may use the JDK; the native subprocesses get a closed tool environment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/java-metadata'))
from prepare import prepare
from semantic import source_cases

PACKAGES = ('fspath', 'inflate', 'json', 'sha2', 'sqlite', 'tea-core',
            'tea-dom', 'tea-term', 'tileinterp', 'tileir', 'tileref',
            'web', 'web-jvm', 'xmap')


def cpu_command(command):
    return [sys.executable, str(ROOT / 'scripts/cpu-limit.py'), '30', '--', *command]


def check(binary, work):
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    # Keep launcher rebuild messages outside the oracle's diagnostic channel.
    subprocess.run([str(ROOT / 'bin/dawn'), '--version'], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    metadata = work / 'metadata'
    prepare(os.environ['JAVA_HOME'], metadata)
    manifest = metadata / 'manifest.json'
    tools = work / 'tools'
    tools.mkdir()
    log = work / 'tool-calls'
    for name in ('java', 'javac', 'native-image', 'cc', 'clang', 'curl'):
        tool = tools / name
        tool.write_text('#!/bin/sh\nprintf "%s\\n" "$0" >> "$TOOL_LOG"\nexit 97\n')
        tool.chmod(0o755)
    env = {'HOME': str(work), 'PATH': str(tools), 'LANG': 'C.UTF-8',
           'TOOL_LOG': str(log), 'JAVA_HOME': str(tools),
           'CLASSPATH': str(work / 'absent.jar')}
    control = subprocess.run([str(tools / 'java')], env=env, check=False)
    assert control.returncode == 97 and log.exists()
    log.unlink()
    count = 0
    comparisons = []

    def native(label, args, code=0, fragment=None):
        nonlocal count
        result = subprocess.run(cpu_command([
            str(binary), 'doc', '--std', str(ROOT / 'std'), *map(str, args)]),
            cwd=work, env=env, capture_output=True)
        (work / (label + '.native.stdout')).write_bytes(result.stdout)
        (work / (label + '.native.stderr')).write_bytes(result.stderr)
        (work / (label + '.native.rc')).write_text(str(result.returncode) + '\n')
        assert result.returncode == code, (label, result)
        if code:
            assert not result.stdout and fragment.encode() in result.stderr, (label, result)
            if result.stderr.startswith(b'error: Java metadata '):
                assert result.stderr.count(b'\n') == 1, (label, result)
        else:
            assert not result.stderr, (label, result)
        assert not log.exists(), label
        count += 1
        return result

    def compare(label, target, args, code=0, fragment=None):
        result = native(label, args, code, fragment)
        oracle = subprocess.run(cpu_command([
            str(ROOT / 'bin/dawn'), 'doc', '--std', str(ROOT / 'std'), str(target)]),
            cwd=ROOT, capture_output=True)
        (work / (label + '.jvm.stdout')).write_bytes(oracle.stdout)
        (work / (label + '.jvm.stderr')).write_bytes(oracle.stderr)
        (work / (label + '.jvm.rc')).write_text(str(oracle.returncode) + '\n')
        assert (result.returncode, result.stdout, result.stderr) == (
            oracle.returncode, oracle.stdout, oracle.stderr), (label, result, oracle)
        comparisons.append(dict(label=label, code=code, size=len(result.stdout),
                                sha256=hashlib.sha256(result.stdout).hexdigest()))

    inventory = sorted(path.parent.name for path in (ROOT / 'packages').glob('*/dawn.toml'))
    assert inventory == list(PACKAGES), inventory
    for name in inventory:
        target = ROOT / 'packages' / name
        # Only the Java package needs a signature context. Pure packages keep
        # exercising normal doc; the relative-path case below also grants one
        # to a pure package and compares its already captured byte oracle.
        args = [target, '--java-signatures', manifest] if name == 'web-jvm' else [target]
        compare(name, target, args)
    web = json.loads((work / 'web-jvm.native.stdout').read_bytes())['modules']
    assert len(web) == 1 and web[0]['path'] == 'server', web
    functions = {item['name']: item for item in web[0]['fns']}
    assert set(functions) == {'input_source', 'handle_port', 'start', 'join',
                              'stop', 'serve_app', 'serve_app_with'}, functions
    assert functions['input_source']['sig'] == 'fn input_source(s: InputStream) -> BodySource'
    assert functions['handle_port']['sig'] == 'fn handle_port(h: ServerHandle) -> Int'
    types = {item['name']: item for item in web[0]['types']}
    assert set(types) == {'ServerConfig', 'ServerHandle'}, types
    assert [field['name'] for field in types['ServerConfig']['ctors'][0]['fields']] == [
        'host', 'port', 'max_body', 'errors']
    assert types['ServerHandle']['ctors'] == [], types['ServerHandle']
    compare('stdlib', '--stdlib', ['--stdlib'])
    # Caller-relative manifest; its class paths still resolve from its directory.
    relative = native('relative', ['--java-signatures', 'metadata/manifest.json',
                                   ROOT / 'packages/sha2'])
    assert relative.stdout == (work / 'sha2.jvm.stdout').read_bytes()
    native('missing-value', ['--java-signatures'], 2, '--java-signatures needs a path')
    native('duplicate', ['--java-signatures', manifest, '--java-signatures', manifest],
           2, '--java-signatures may only be specified once')
    for mode in ('--stdlib', '--builtins'):
        native(mode[2:] + '-conflict', [mode, '--java-signatures', manifest],
               2, '--java-signatures requires a source target')
    source = work / 'plain.dawn'
    source.write_text('pub fn visible() -> Int = 1\n')
    for label, value in [('empty', ''), ('absent', 'absent.json'), ('help-value', '--help')]:
        native(label, ['--java-signatures', value, source], 2, 'error: Java metadata path:')
    invalid = work / 'invalid.json'
    invalid.write_text('{')
    native('invalid-json', ['--java-signatures', invalid, source], 2,
           'error: Java metadata schema:')
    changed = work / 'changed'
    shutil.copytree(metadata, changed)
    table = json.loads((changed / 'manifest.json').read_bytes())
    class_file = changed / table['classes'][0]['path']
    class_file.write_bytes(b'bad')
    native('changed-class', ['--java-signatures', changed / 'manifest.json', source],
           2, 'error: Java metadata identity:')
    source.write_text('use java "absent.NotInTheManifest"\npub fn visible() -> Int = 1\n')
    native('missing-import', ['--java-signatures', manifest, source], 2,
           'reference absent.NotInTheManifest')
    source.write_text('use java "java.lang.String"\npub fn visible() -> Int = 1\n')
    native('implicit-refusal', [source], 1, '`use java` is not available in this compiler')
    for flag in ('--cp', '--closure', '--native', '--vendor'):
        args = ['--java-signatures', manifest, flag]
        if flag == '--cp':
            args.append(str(metadata))
        native(flag[2:] + '-refusal', args + [source], 2,
               flag + ' is not supported by the native compiler')
    cases = source_cases(work)
    # The platform pack suffices for these cases; custom Java fixtures remain
    # in the existing semantic-host gate rather than being compiled again here.
    grouped = []
    app = work / 'app'
    for case in cases:
        if case['name'] in ('bridges', 'arrays', 'sam', 'bad-array', 'bad-sam'):
            continue
        target = Path(case['path'])
        if case['expected'] == 'doc-error':
            # Writer failures need a program without checker errors.
            compare(case['name'], target, [target], 1, case['contains'])
        elif case['name'] == 'bad-dependency-test':
            grouped.append({**case, 'path': str(work / 'dependency/src/lib.dawn')})
        else:
            destination = app / 'src' / target.name
            shutil.copyfile(target, destination)
            grouped.append({**case, 'path': str(destination)})
    compare('source-analysis', app, ['--java-signatures', manifest, app],
            1, 'missingDependencyMember')
    diagnostics = (work / 'source-analysis.native.stderr').read_bytes()
    for case in grouped:
        path = case['path'].encode()
        if case['expected'] == 'ok':
            assert path not in diagnostics, case
        else:
            assert path in diagnostics and case['contains'].encode() in diagnostics, case
    app = work / 'coordinate_app'
    dep = work / 'coordinate_dep'
    (app / 'src').mkdir(parents=True)
    (dep / 'src').mkdir(parents=True)
    (app / 'src/main.dawn').write_text('pub fn main() -> Unit !io = ()\n')
    (dep / 'src/lib.dawn').write_text('pub fn value() -> Int = 1\n')
    header = 'schema = 1\nname = "app"\n'
    java = '[java-deps]\napi = "fixture:api:1"\n'
    for transitive in (False, True):
        (app / 'dawn.toml').write_text(header + (
            '[deps]\ndep = "../coordinate_dep"\n' if transitive else java))
        (dep / 'dawn.toml').write_text('schema = 1\nname = "dep"\n' + java)
        native('coordinates-' + str(transitive), ['--java-signatures', invalid, app],
               2, 'fixture:api:1')
    (app / 'dawn.toml').write_text('schema = 1\nname = "Bad-Name"\n' + java)
    native('plan-priority', ['--java-signatures', invalid, app],
           1, 'invalid package name `Bad-Name`')
    (work / 'summary.json').write_text(json.dumps(dict(
        packages=inventory, comparisons=comparisons,
        native_assertions=count + len(grouped) - 1, native_invocations=count,
        grouped_source_cases=grouped,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        external_tool_calls=0), indent=2) + '\n')
    print(f'OK native doc metadata: {len(inventory)} packages and stdlib byte-identical; '
          f'{count + len(grouped) - 1} case assertions in {count} CLI invocations; '
          'no external tool calls', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dawnc', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    arguments = parser.parse_args()
    check(arguments.dawnc.resolve(), arguments.out)
