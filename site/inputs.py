#!/usr/bin/env python3
"""Keep site consumption separate from compiler and raw metadata preparation.

Receipts bind bytes and complete SourcePlan input trees rather than mtimes or
versions. Documentation is always regenerated in fresh staging; its receipt
is a sidecar, so the compiler's JSON contract remains the only document schema.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / 'site/build/native'
TOOL = NATIVE / 'dawnc.tool.json'
PREPARED = ROOT / 'site/build/prepared.json'
DATA = ROOT / 'site/build/java-metadata/manifest.json'
LOCK = ROOT / 'site/java-metadata.lock.json'
RECIPE = ['bin/dawn', 'scripts/cc-units.sh', 'scripts/pinned-cc.sh',
          'scripts/seedjar.sh', 'scripts/seed-release.txt',
          'scripts/seed-checksums.txt', 'scripts/seed-std-checksums.txt']


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode()


def identity(value):
    return sha(canonical(value))


def write_json(path, value):
    path.write_bytes(canonical(value) + b'\n')


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def run(argv, **kwargs):
    return subprocess.run([str(x) for x in argv], cwd=ROOT, check=True, **kwargs)


def commit():
    return run(['git', 'rev-parse', 'HEAD'], capture_output=True,
               text=True).stdout.strip()


def safe(path):
    require(path.is_absolute(), 'input path must be absolute')
    for part in [path, *path.parents]:
        require(not part.is_symlink(), 'symbolic input: ' + str(part))
    return path


def file_record(path, label):
    safe(path)
    require(path.is_file(), 'missing regular input: ' + str(path))
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while chunk := stream.read(256 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {'path': label, 'size': size, 'sha256': digest.hexdigest()}


def file_sha(path):
    return file_record(path, '')['sha256']


def tree_records(path):
    safe(path)
    require(path.is_dir(), 'missing input tree: ' + str(path))
    result = []
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in sorted(dirs + files):
            entry = Path(base) / name
            safe(entry)
            if not entry.is_dir():
                result.append(file_record(entry, entry.relative_to(path).as_posix()))
    return sorted(result, key=lambda item: item['path'])


def source_state(manifest):
    require(manifest.startswith('dawn-source-inputs-v1\n') and manifest.endswith('\n'),
            'invalid SourcePlan input manifest')
    lines = manifest.splitlines()[1:]
    require(lines and lines == sorted(set(lines)), 'invalid SourcePlan record order')
    states = []
    for line in lines:
        scope, kind, spelling = line.split('\t')
        require(scope in ('R', 'A') and kind in ('F', 'O', 'T'),
                'invalid SourcePlan input record')
        path = Path(spelling)
        require(str(path) == spelling and '..' not in path.parts,
                'noncanonical SourcePlan input path')
        require(path.is_absolute() == (scope == 'A'), 'invalid SourcePlan scope')
        path = path if scope == 'A' else ROOT / path
        safe(path)
        if kind == 'T':
            value = tree_records(path)
        elif kind == 'O' and not path.exists():
            value = None
        else:
            value = file_record(path, spelling)
        states.append({'record': line, 'value': value})
    # SourcePlan records dependency manifests and trees. Bind each optional
    # dependency lock too, including absence, without resolving dependencies.
    locks = []
    for line in lines:
        scope, kind, spelling = line.split('\t')
        if kind == 'F' and Path(spelling).name == 'dawn.toml':
            path = Path(spelling).with_name('dawn.lock')
            path = path if scope == 'A' else ROOT / path
            safe(path)
            locks.append({'path': str(path), 'value':
                          file_record(path, str(path)) if path.exists() else None})
    return identity({'manifest': manifest, 'inputs': states, 'locks': locks})


def plan(project):
    return run([NATIVE / 'site_source_inputs', ROOT, project],
               capture_output=True, text=True).stdout


def recipe_sha():
    return identity([file_record(ROOT / name, name) for name in RECIPE])


def check_tool():
    tool = read_json(TOOL)
    require(tool['schema'] == 'dawn-doc-tool-v1' and tool['backend'] == 'native',
            'unsupported site tool receipt')
    require(re.fullmatch('[0-9a-f]{40}', tool['source_commit']), 'invalid tool source commit')
    require(all(os.access(NATIVE / name, os.X_OK) for name in ('dawnc', 'site_source_inputs')),
            'prepared native tools are not executable')
    checks = {
        'binary_sha256': file_sha(NATIVE / 'dawnc'),
        'source_inputs_sha256': source_state(tool['source_inputs']),
        'embedded_std_sha256': identity(tree_records(ROOT / 'std')),
        'runtime_inputs_sha256': identity(tree_records(ROOT / 'runtime/c')),
        'recipe_sha256': recipe_sha(),
        'planner_binary_sha256': file_sha(NATIVE / 'site_source_inputs'),
        'planner_inputs_sha256': source_state(tool['planner_inputs']),
    }
    for key, value in checks.items():
        require(tool[key] == value, 'stale site tool receipt: ' + key)
    require(tool['capture_before'] == {k: checks[k] for k in (
        'source_inputs_sha256', 'planner_inputs_sha256', 'embedded_std_sha256',
        'runtime_inputs_sha256', 'recipe_sha256')}, 'tool inputs moved during preparation')
    return tool


def check_data(manifest=None):
    manifest = DATA if manifest is None else manifest
    lock = read_json(LOCK)
    safe(manifest)
    require(manifest.stat().st_size == lock['manifest_size'],
            'Java manifest does not match site lock')
    raw = safe(manifest).read_bytes()
    require(sha(raw) == lock['manifest_sha256'], 'Java manifest does not match site lock')
    data = read_json(manifest)
    for key in ('platform', 'modules', 'required_roots'):
        require(data[key] == lock[key], 'Java site lock mismatch: ' + key)
    expected = set()
    for entry in data['classes']:
        name = entry['path']
        require(name not in expected, 'duplicate class input: ' + name)
        expected.add(name)
        path = safe(manifest.parent / name)
        require(path.is_file(), 'missing regular input: ' + str(path))
        require(path.stat().st_size == entry['size'], 'Java class identity mismatch: ' + name)
        record = file_record(path, name)
        require(record['size'] == entry['size'] and record['sha256'] == entry['sha256'],
                'Java class identity mismatch: ' + name)
    actual = {record['path'] for record in tree_records(manifest.parent)}
    require(actual == expected | {manifest.name}, 'Java class directory inventory mismatch')
    return lock


def check_prepared():
    prepared = read_json(PREPARED)
    require(prepared['schema'] == 'dawn-site-prepared-v1', 'unsupported preparation receipt')
    require(prepared['tool_identity_sha256'] == file_sha(TOOL),
            'prepared tool receipt changed')
    require(prepared['java_manifest_sha256'] == file_sha(DATA),
            'prepared Java manifest changed')
    require(prepared['java_lock_sha256'] == file_sha(LOCK), 'prepared Java lock changed')
    check_tool()
    return check_data()


def prepare(jdk):
    NATIVE.mkdir(parents=True, exist_ok=True)
    try:
        check_tool()
    except (OSError, ValueError, KeyError, TypeError):
        # Without a matching receipt a cache entry is not an attested compiler.
        # Bootstrap here, never in build.sh or its children.
        (NATIVE / 'dawnc.stamp').unlink(missing_ok=True)
        env = dict(os.environ)
        env.pop('DAWNC_BIN', None)
        def bootstrap_plan(project):
            return run([ROOT / 'bin/dawn', '__source-inputs', '--base', ROOT, project],
                       env=env, capture_output=True, text=True).stdout
        inputs = bootstrap_plan('selfhost')
        planner_inputs = bootstrap_plan('site/source-inputs')
        capture = {
            'source_inputs_sha256': source_state(inputs),
            'planner_inputs_sha256': source_state(planner_inputs),
            'embedded_std_sha256': identity(tree_records(ROOT / 'std')),
            'runtime_inputs_sha256': identity(tree_records(ROOT / 'runtime/c')),
            'recipe_sha256': recipe_sha(),
        }
        run(['bash', '-euc', '. site/dawnc.sh; site_dawnc'], env=env,
            stdout=subprocess.DEVNULL)
        run([NATIVE / 'dawnc', 'build', 'site/source-inputs',
             '-o', NATIVE / 'site_source_inputs'])
        require(plan('selfhost') == inputs and plan('site/source-inputs') == planner_inputs,
                'bootstrap and native SourcePlan manifests differ')
        tool = {
            'schema': 'dawn-doc-tool-v1', 'backend': 'native',
            'binary_sha256': sha((NATIVE / 'dawnc').read_bytes()),
            'source_commit': commit(), 'source_inputs': inputs,
            'source_inputs_sha256': source_state(inputs),
            'embedded_std_sha256': identity(tree_records(ROOT / 'std')),
            'runtime_inputs_sha256': identity(tree_records(ROOT / 'runtime/c')),
            'recipe_sha256': recipe_sha(),
            'planner_binary_sha256': sha((NATIVE / 'site_source_inputs').read_bytes()),
            'planner_inputs': planner_inputs,
            'planner_inputs_sha256': source_state(planner_inputs),
            'capture_before': capture,
        }
        write_json(TOOL, tool)
        check_tool()
    if DATA.parent.exists():
        check_data()
    else:
        require(jdk is not None, 'metadata preparation requires --jdk or JAVA_HOME')
        spec = importlib.util.spec_from_file_location(
            'java_prepare', ROOT / 'scripts/java-metadata/prepare.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.prepare(jdk, DATA.parent)
        check_data()
    write_json(PREPARED, {
        'schema': 'dawn-site-prepared-v1',
        'tool_identity_sha256': file_sha(TOOL),
        'java_manifest_sha256': file_sha(DATA),
        'java_lock_sha256': file_sha(LOCK),
    })
    print('OK: native site tool and locked raw Java metadata prepared')


def targets(lock):
    actual = sorted(path.parent.name for path in (ROOT / 'packages').glob('*/dawn.toml'))
    require(actual == lock['packages'], 'site package inventory differs from reviewed lock')
    require(set(lock['java_targets']) <= set(actual), 'unknown Java documentation target')
    result = []
    for name in actual:
        directory = 'packages/' + name
        manifest = tomllib.loads((ROOT / directory / 'dawn.toml').read_text())
        inputs = plan(directory)
        argv = ['doc']
        if name in lock['java_targets']:
            argv += ['--java-signatures', str(DATA)]
        argv += [directory]
        result.append({
            'directory': directory, 'name': manifest['name'],
            'version': manifest.get('version'), 'use_as': name.replace('-', '_'),
            'argv': argv, 'source_inputs': inputs,
            'source_inputs_sha256': source_state(inputs),
            'output': 'packages/' + name + '.json',
        })
    return result


def doc(argv, path):
    with path.open('wb') as out:
        run([NATIVE / 'dawnc', *argv], stdout=out)
    value = read_json(path)
    schema = 'dawn-doc-stdlib-v1' if argv == ['doc', '--stdlib'] else 'dawn-doc-project-v1'
    check_doc(value, schema)
    return schema


def check_doc(value, schema):
    keys = {'modules'} if schema == 'dawn-doc-project-v1' else {'groups', 'traits', 'modules'}
    require(schema in ('dawn-doc-project-v1', 'dawn-doc-stdlib-v1'), 'unknown doc schema')
    require(isinstance(value, dict) and set(value) == keys
            and all(isinstance(value[k], list) for k in keys), 'invalid documentation schema')


def generate_packages(items, directory):
    directory.mkdir(parents=True, exist_ok=False)
    def generate(item):
        item['doc_schema'] = doc(item['argv'], directory / Path(item['output']).name)
    jobs = int(os.environ.get('SITE_DOC_JOBS', '2'))
    require(1 <= jobs <= 2, 'SITE_DOC_JOBS must be 1 or 2')
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        list(executor.map(generate, items))


def check_bundle(directory):
    lock = check_prepared()
    receipt = read_json(directory / 'receipt.json')
    require(receipt['schema'] == 'dawn-doc-bundle-v1', 'unsupported doc bundle receipt')
    require(receipt['source_commit'] == commit(), 'doc bundle source commit changed')
    require(receipt['tool_identity_sha256'] == file_sha(TOOL), 'doc tool identity changed')
    require(receipt['java_manifest_sha256'] == file_sha(DATA), 'doc Java identity changed')
    require(receipt['stdlib_sha256'] == identity(tree_records(ROOT / 'std')), 'doc stdlib changed')
    require(receipt['package_inventory_sha256'] == identity(lock['packages']),
            'doc package inventory changed')
    items = receipt['targets']
    require([item['directory'] for item in items] == ['packages/' + n for n in lock['packages']],
            'doc target inventory mismatch')
    for item, actual in zip(items, targets(lock)):
        require(item == dict(actual, doc_schema='dawn-doc-project-v1'),
                'doc target identity mismatch: ' + item['directory'])
    expected = {'stdlib.json'} | {'packages/' + n + '.json' for n in lock['packages']}
    actual = {r['path'] for r in tree_records(directory)}
    require(actual == expected | {'receipt.json'}, 'doc output inventory mismatch')
    records = [file_record(directory / name, name) for name in sorted(expected)]
    require(receipt['outputs'] == records, 'doc output bytes changed')
    require(receipt['stdlib_argv'] == ['doc', '--stdlib']
            and receipt['stdlib_doc_schema'] == 'dawn-doc-stdlib-v1', 'doc stdlib identity mismatch')
    for record in records:
        schema = 'dawn-doc-stdlib-v1' if record['path'] == 'stdlib.json' else 'dawn-doc-project-v1'
        check_doc(read_json(directory / record['path']), schema)


def bundle(destination):
    lock = check_prepared()
    require(not destination.exists(), 'doc destination must be fresh: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.docs-', dir=destination.parent))
    try:
        items = targets(lock)
        source_commit = commit()
        std_schema = doc(['doc', '--stdlib'], staging / 'stdlib.json')
        generate_packages(items, staging / 'packages')
        outputs = sorted(tree_records(staging), key=lambda item: item['path'])
        write_json(staging / 'receipt.json', {
            'schema': 'dawn-doc-bundle-v1', 'source_commit': source_commit,
            'tool_identity_sha256': file_sha(TOOL),
            'java_manifest_sha256': file_sha(DATA),
            'stdlib_sha256': identity(tree_records(ROOT / 'std')),
            'stdlib_argv': ['doc', '--stdlib'], 'stdlib_doc_schema': std_schema,
            'package_inventory_sha256': identity(lock['packages']),
            'targets': items, 'outputs': outputs,
        })
        check_bundle(staging)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--jdk', default=os.environ.get('JAVA_HOME'))
    sub.add_parser('check')
    for name in ('bundle', 'check-bundle', 'packages'):
        sub.add_parser(name).add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.command == 'prepare':
            prepare(args.jdk)
        elif args.command == 'check':
            check_prepared()
            print(NATIVE / 'dawnc')
        elif args.command == 'bundle':
            bundle(args.out.absolute())
        elif args.command == 'check-bundle':
            check_bundle(args.out.absolute())
        elif args.command == 'packages':
            items = targets(check_prepared())
            generate_packages(items, args.out.absolute())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print('error: site inputs: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
