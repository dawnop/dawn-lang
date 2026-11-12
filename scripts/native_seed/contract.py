"""Strict qualification inputs, independent of the JVM seed and release metadata."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import subprocess
import tempfile

TARGET = 'x86_64-unknown-linux-gnu'
ASSET = 'dawnc-linux-x86_64'
ALGORITHM = 'native-bootstrap-inputs-v1'
TRANSFORM = 'portable-selfhost-v1'
HISTORICAL_COMMIT = '8068f0ba3ffaaabfcf10e103e375da678dbb15b6'
HISTORICAL_SHA = 'e1506ef0aee7978a00fa07a0c2eebe565a2a35fc788128590d6106baeaf0186f'
HISTORICAL_SIZE = 13800672
HISTORICAL_BUILD_ID = 'b1:158ec8003d1d7a1b9d30943aad1d9f04440d65df96e9481d8ad73b16e8a6ebf1'


class Rejected(ValueError):
    pass


def require(ok, code, detail):
    if not ok:
        raise Rejected(f'{code}: {detail}')


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names.split()),
            'schema', f'{label}: expected fields {names}')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def sha(value, label):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value),
            'schema', f'{label}: invalid SHA-256')


def oid(value, label):
    require(type(value) is str and re.fullmatch('[0-9a-f]{40}', value),
            'schema', f'{label}: invalid full Git object ID')


def logical(path):
    require(type(path) is str and path and not path.startswith('/') and
            all(x not in ('', '.', '..') for x in path.split('/')) and
            '\\' not in path and not any(ord(x) < 32 or ord(x) == 127 for x in path),
            'source-path', f'unsafe logical path: {path!r}')
    path.encode('utf-8', errors='strict')
    return path


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'schema', f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(regular_bytes(path), object_pairs_hook=no_duplicates,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              Rejected(f'schema: invalid JSON constant {x}')))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Rejected(f'schema: invalid JSON: {exc}') from exc


def regular_bytes(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'source-type', f'symlink forbidden: {part.name}')
    require(path.is_file(), 'source-missing', f'regular file required: {path.name}')
    require(stat.S_ISREG(path.lstat().st_mode), 'source-type', f'not regular: {path.name}')
    return path.read_bytes()


def atomic_json(path, value):
    path = safe_destination(path)
    require(not path.exists() and not path.is_symlink(), 'destination', 'output already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            name = Path(out.name)
            out.write(canonical(value))
            out.flush()
            os.fsync(out.fileno())
        # link is an atomic create-if-absent commit point, never an overwrite.
        os.link(name, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def safe_destination(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)),
            'destination', 'output path contains a symlink')
    return path


def identity(commit, tree_sha):
    return {'commit': commit, 'algorithm': ALGORITHM, 'sha256': tree_sha}


def validate_identity(value, label):
    fields(value, 'commit algorithm sha256', label)
    oid(value['commit'], label)
    sha(value['sha256'], label)
    require(value['algorithm'] == ALGORITHM, 'schema', f'{label}: unknown tree algorithm')


def read_lock(path):
    value = read_json(path)
    validate_lock(value)
    return value


def validate_lock(value):
    fields(value, 'schema kind state sequence seed std runtime lineage registration', 'lock')
    require(type(value['schema']) is int and value['schema'] == 2 and
            value['kind'] == 'native-seed-lock', 'schema', 'expected native-seed-lock schema 2')
    # K1 cannot bless a candidate. Qualified locks need the later proof verifier.
    require(value['state'] == 'candidate' and type(value['sequence']) is int and
            value['sequence'] == 0, 'lineage', 'K1 accepts only the initial candidate')
    seed = value['seed']
    fields(seed, 'kind tag commit asset sha256 size target version build_id', 'seed')
    require(seed['kind'] == 'native-elf' and seed['asset'] == ASSET,
            'seed-kind', 'expected the native ELF asset')
    require(seed['target'] == TARGET, 'seed-target', 'unsupported seed target')
    require(type(seed['tag']) is str and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', seed['tag']) and
            seed['version'] == f'dawnc {seed["tag"][1:]} (native)',
            'seed-identity', 'seed tag/version mismatch')
    oid(seed['commit'], 'seed commit')
    sha(seed['sha256'], 'seed')
    require(type(seed['size']) is int and seed['size'] > 0, 'schema', 'invalid seed size')
    require(type(seed['build_id']) is str and
            re.fullmatch('b1:[0-9a-f]{64}', seed['build_id']), 'seed-identity', 'invalid full build ID')
    for key in ('std', 'runtime'):
        validate_identity(value[key], key)
        require(value[key]['commit'] == seed['commit'], f'{key}-pairing', 'seed commit mismatch')
    fields(value['lineage'], 'parent_lock_sha256 parent_receipt_sha256 qualification_sha256', 'lineage')
    require(all(x is None for x in value['lineage'].values()), 'lineage', 'candidate has no qualified parent')
    fields(value['registration'], 'kind metadata evidence_sha256', 'registration')
    require(value['registration']['kind'] == 'historical-v0.104.0' and
            value['registration']['metadata'] == 'absent', 'schema', 'not a historical registration')
    sha(value['registration']['evidence_sha256'], 'registration evidence')
    require(seed['tag'] == 'v0.104.0' and seed['commit'] == HISTORICAL_COMMIT and
            seed['build_id'] == HISTORICAL_BUILD_ID, 'seed-identity', 'candidate registration identity differs')
    require(seed['sha256'] == HISTORICAL_SHA and seed['size'] == HISTORICAL_SIZE,
            'seed-digest', 'candidate registration bytes differ')


def verify_elf(data):
    require(len(data) >= 64 and data[:7] == b'\x7fELF\x02\x01\x01',
            'seed-target', 'expected little-endian ELF64')
    h = struct.unpack_from('<HHIQQQIHHHHHH', data, 16)
    kind, machine, version, entry, phoff, shoff, _, ehsize, phsize, phnum, shsize, shnum, _ = h
    require(kind in (2, 3) and machine == 62 and version == 1 and ehsize == 64,
            'seed-target', 'expected Linux x86_64 ELF executable')
    require(phnum > 0 and phsize == 56 and phoff + phnum * phsize <= len(data),
            'seed-target', 'truncated program headers')
    require(shnum > 0 and shsize == 64 and shoff + shnum * shsize <= len(data),
            'seed-target', 'truncated section headers')
    executable_entry = False
    for index in range(phnum):
        kind, flags, offset, address, _, size, memsize, _ = struct.unpack_from(
            '<IIQQQQQQ', data, phoff + index * phsize)
        require(offset + size <= len(data) and size <= memsize,
                'seed-target', 'truncated ELF segment')
        require(kind != 3, 'seed-target', 'ELF interpreter forbidden')
        if kind == 1 and flags & 1 and address <= entry < address + memsize:
            executable_entry = True
        if kind == 2:
            require(size % 16 == 0, 'seed-target', 'invalid dynamic segment')
            for pos in range(offset, offset + size, 16):
                require(struct.unpack_from('<qQ', data, pos)[0] != 1,
                        'seed-target', 'shared library dependency forbidden')
    require(executable_entry, 'seed-target', 'entry point must be executable')
    for index in range(shnum):
        _, kind, _, _, offset, size, _, _, _, _ = struct.unpack_from(
            '<IIQQQQIIQQ', data, shoff + index * shsize)
        require(kind == 8 or offset + size <= len(data), 'seed-target', 'truncated ELF section')


def verify_seed(path, lock):
    validate_lock(lock)
    data = regular_bytes(path)
    seed = lock['seed']
    require(len(data) == seed['size'] and digest(data) == seed['sha256'],
            'seed-digest', 'seed bytes differ from lock; execution refused')
    verify_elf(data)
    return data


def probe_seed(data):
    # Execute a private copy of verified bytes, not a mutable caller path.
    with tempfile.TemporaryDirectory(prefix='native-seed-probe-') as work:
        executable = Path(work) / 'dawnc'
        executable.write_bytes(data)
        executable.chmod(0o500)
        env = {'PATH': '/nonexistent', 'HOME': work, 'LANG': 'C.UTF-8'}
        result = subprocess.run([str(executable), '--version'], cwd=work, timeout=20,
                                env=env,
                                capture_output=True)
        require(result.returncode == 0 and result.stderr == b'', 'seed-identity', 'version probe failed')
        try:
            text = result.stdout.decode('ascii')
        except UnicodeError as exc:
            raise Rejected('seed-identity: non-ASCII version') from exc
        match = re.fullmatch(r'(dawnc 0\.104\.0 \(native\)) (b1:[0-9a-f]{12})\n', text)
        require(match is not None, 'seed-identity', f'unexpected version transcript: {text!r}')
        listing = subprocess.run([str(executable), 'version', '-m', str(executable)],
                                 cwd=work, env=env, timeout=20, capture_output=True)
        builds = re.findall(rb'^\tbuild\t(b1:[0-9a-f]{64})$', listing.stdout, re.M)
        require(listing.returncode == 0 and not listing.stderr and len(builds) == 1,
                'seed-identity', 'expected exactly one full embedded build ID')
        build_id = builds[0].decode('ascii')
        require(match[2] == build_id[:15], 'seed-identity', 'short/full build ID mismatch')
        return match[1], build_id


def verify_seed_probe(path, lock):
    version, build_id = probe_seed(verify_seed(path, lock))
    require((version, build_id) == (lock['seed']['version'], lock['seed']['build_id']),
            'seed-identity', 'version/build ID differs from lock')


def record(path, data=None, executable=False):
    return {'path': logical(path), 'kind': 'missing' if data is None else 'file',
            'size': 0 if data is None else len(data),
            'sha256': None if data is None else digest(data), 'executable': executable}


def inventory(files):
    result = [record(path, data, mode == '100755') for path, (mode, data) in files.items()]
    for path in files:
        if PurePosixPath(path).name == 'dawn.toml':
            lock = str(PurePosixPath(path).with_name('dawn.lock'))
            if lock not in files:
                result.append(record(lock))
    return sorted(result, key=lambda x: x['path'].encode('utf-8'))


def inventory_sha(rows):
    require(type(rows) is list, 'schema', 'inventory must be a list')
    previous = b''
    h = hashlib.sha256(ALGORITHM.encode('ascii') + b'\0')
    for row in rows:
        fields(row, 'path kind size sha256 executable', 'inventory record')
        path = logical(row['path']).encode('utf-8')
        require(path > previous, 'source-inventory', 'paths must be sorted and unique')
        previous = path
        require(type(row['size']) is int and row['size'] >= 0 and type(row['executable']) is bool,
                'schema', 'invalid file size or executable bit')
        require(row['kind'] in ('file', 'missing'), 'schema', 'unknown inventory kind')
        if row['kind'] == 'file':
            sha(row['sha256'], 'inventory')
        else:
            require(row['size'] == 0 and row['sha256'] is None and not row['executable'],
                    'schema', 'invalid missing record')
        for field in (path, row['kind'].encode('ascii'), str(row['size']).encode('ascii'),
                      (row['sha256'] or '').encode('ascii'), b'1' if row['executable'] else b'0'):
            h.update(len(field).to_bytes(8, 'big'))
            h.update(field)
    return h.hexdigest()


def subtree(files, prefix):
    selected = {p[len(prefix) + 1:]: x for p, x in files.items() if p.startswith(prefix + '/')}
    require(selected, 'source-missing', f'missing input tree: {prefix}')
    return inventory_sha(inventory(selected))


def git(repo, *args, input_data=None):
    run = subprocess.run(['git', '-C', str(repo), *args], input=input_data, capture_output=True)
    require(run.returncode == 0, 'source-git', run.stderr.decode('utf-8', errors='replace').strip())
    return run.stdout


def git_files(repo, commit):
    oid(commit, 'source commit')
    require(git(repo, 'rev-parse', '--verify', commit + '^{commit}').decode().strip() == commit,
            'source-git', 'commit required')
    tree = git(repo, 'rev-parse', commit + '^{tree}').decode().strip()
    entries = []
    for entry in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not entry:
            continue
        head, raw_path = entry.split(b'\t', 1)
        mode, kind, obj = head.decode('ascii').split()
        path = logical(raw_path.decode('utf-8'))
        require(mode in ('100644', '100755') and kind == 'blob',
                'source-type', f'non-regular Git input: {path}')
        entries.append((path, mode, obj))
    request = ''.join(obj + '\n' for _, _, obj in entries).encode('ascii')
    stream = git(repo, 'cat-file', '--batch', input_data=request)
    pos, files = 0, {}
    for path, mode, obj in entries:
        end = stream.index(b'\n', pos)
        actual, kind, size = stream[pos:end].decode('ascii').split()
        size = int(size)
        require(actual == obj and kind == 'blob', 'source-git', 'unexpected blob response')
        pos = end + 1
        data = stream[pos:pos + size]
        require(len(data) == size and stream[pos + size:pos + size + 1] == b'\n',
                'source-git', 'truncated blob')
        files[path] = (mode, data)
        pos += size + 1
    require(pos == len(stream), 'source-git', 'extra blob data')
    return tree, files


def portable(files):
    # Parse TOML for structural local-path checks only. No Dawn source resolver.
    import posixpath
    import tomllib
    files = dict(files)
    root = 'selfhost/dawn.toml'
    require(root in files, 'source-missing', 'selfhost manifest missing')
    try:
        manifest = tomllib.loads(files[root][1].decode('utf-8'))
        require(set(manifest) == {'schema', 'name', 'java-deps', 'deps'} and
                manifest['schema'] == 1 and manifest['name'] == 'selfhost',
                'source-manifest', 'unexpected selfhost manifest shape')
        deps = manifest['deps']
        require(type(deps) is dict and deps, 'source-manifest', 'local deps required')
        lines = ['schema = 1', 'name = "selfhost"', '', '[deps]']
        for name, path in sorted(deps.items()):
            require(type(name) is str and re.fullmatch('[a-z][a-z0-9_]*', name),
                    'source-manifest', 'invalid dependency name')
            require(type(path) is str, 'source-manifest', 'remote dependency forbidden')
            lines.append(f'{name} = {json.dumps(path)}')
        files[root] = (files[root][0], ('\n'.join(lines) + '\n').encode('utf-8'))
        pending, seen = ['selfhost'], set()
        while pending:
            directory = pending.pop()
            if directory in seen:
                continue
            seen.add(directory)
            path = directory + '/dawn.toml'
            require(path in files, 'source-missing', f'dependency manifest missing: {path}')
            project = tomllib.loads(files[path][1].decode('utf-8'))
            require('java-deps' not in project, 'source-manifest', f'Java deps forbidden: {path}')
            require(type(project.get('deps', {})) is dict, 'source-manifest', 'invalid deps table')
            for dep in project.get('deps', {}).values():
                require(type(dep) is str and dep and not dep.startswith('/') and '\\' not in dep
                        and not any(ord(c) < 32 for c in dep),
                        'source-path', f'non-local dependency in {path}')
                resolved = posixpath.normpath(directory + '/' + dep)
                logical(resolved)
                require(':' not in resolved, 'source-path', 'remote dependency forbidden')
                pending.append(resolved)
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise Rejected(f'source-manifest: invalid TOML: {exc}') from exc
    return files


def transform_sha():
    return digest(Path(__file__).read_bytes())


def source_description(repo, commit):
    tree, raw = git_files(repo, commit)
    files = portable(raw)
    rows = inventory(files)
    original = inventory(raw)
    parts = {key: identity(commit, subtree(files, prefix)) for key, prefix in
             [('std', 'std'), ('runtime', 'runtime/c'), ('embed', 'selfhost/src/embed')]}
    source = {'commit': commit, 'tree': tree, 'algorithm': ALGORITHM,
              'original_sha256': inventory_sha(original), 'inventory_sha256': inventory_sha(rows),
              'inventory': rows, 'transform': {'version': TRANSFORM, 'sha256': transform_sha(),
              'manifest_before_sha256': digest(raw['selfhost/dawn.toml'][1]),
              'manifest_after_sha256': digest(files['selfhost/dawn.toml'][1])}, **parts}
    return source, files


def scan(root):
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink(), 'source-type', 'capture root must be a directory')
    for parent in root.parents:
        require(not parent.is_symlink(), 'source-type', 'capture parent is a symlink')
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(directory) / name
            require(stat.S_ISDIR(path.lstat().st_mode), 'source-type', 'symlink directory forbidden')
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            require(stat.S_ISREG(path.lstat().st_mode), 'source-type', f'not a regular file: {relative}')
            files[relative] = ('100755' if path.stat().st_mode & 0o111 else '100644', path.read_bytes())
    return files


def verify_tree(root, expected_rows, code='source-inventory'):
    actual = inventory(scan(root))
    require(actual == expected_rows, code, 'file set, missing state, type, mode or content differs')
    directories = {str(parent) for row in expected_rows if row['kind'] == 'file'
                   for parent in PurePosixPath(row['path']).parents if str(parent) != '.'}
    for directory, children, _ in os.walk(root):
        for child in children:
            relative = (Path(directory) / child).relative_to(root).as_posix()
            require(relative in directories, code, f'unexpected directory: {relative}')


def verify_generated(files):
    import sys
    with tempfile.TemporaryDirectory(prefix='native-input-generated-') as work:
        root = Path(work)
        prefixes = ('std/', 'runtime/c/', 'selfhost/src/embed/')
        scripts = ('scripts/gen-stdsrc.py', 'scripts/gen-rtsrc.py')
        for path, (_, data) in files.items():
            if path.startswith(prefixes) or path in scripts:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        for script, embed in zip(scripts, ('stdsrc', 'rtsrc')):
            run = subprocess.run([sys.executable, '-B', str(root / script)], cwd=root,
                                 env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                 capture_output=True, timeout=30)
            path = f'selfhost/src/embed/{embed}.dawn'
            require(run.returncode == 0 and path in files and
                    (root / path).read_bytes() == files[path][1],
                    'generated-pairing', f'{embed} does not match its source tree')


def stages(lock, source):
    return [{'stage': name, 'emitter': emitter, 'std': std, 'runtime': runtime}
            for name, emitter, std, runtime in
            [('A', 'seed', lock['std'], lock['runtime']),
             ('B', 'A', source['std'], source['runtime']),
             ('C', 'B', source['std'], source['runtime'])]]


def validate_receipt(receipt, lock):
    fields(receipt, 'schema kind seed_lock_sha256 source stages', 'receipt')
    require(type(receipt['schema']) is int and receipt['schema'] == 2 and
            receipt['kind'] == 'native-bootstrap-inputs', 'schema', 'expected input receipt schema 2')
    sha(receipt['seed_lock_sha256'], 'lock digest')
    require(receipt['seed_lock_sha256'] == digest(canonical(lock)), 'seed-lock', 'lock identity differs')
    source = receipt['source']
    fields(source, 'commit tree algorithm original_sha256 inventory_sha256 inventory transform std runtime embed', 'source')
    oid(source['commit'], 'source commit')
    oid(source['tree'], 'source tree')
    require(source['algorithm'] == ALGORITHM, 'schema', 'unknown source algorithm')
    sha(source['original_sha256'], 'original inventory')
    sha(source['inventory_sha256'], 'portable inventory')
    require(inventory_sha(source['inventory']) == source['inventory_sha256'],
            'source-inventory', 'inventory digest mismatch')
    fields(source['transform'], 'version sha256 manifest_before_sha256 manifest_after_sha256', 'transform')
    require(source['transform']['version'] == TRANSFORM, 'source-transform', 'unknown transform')
    for key in ('sha256', 'manifest_before_sha256', 'manifest_after_sha256'):
        sha(source['transform'][key], 'transform')
    require(source['transform']['sha256'] == transform_sha(), 'source-transform', 'transform implementation changed')
    for key in ('std', 'runtime', 'embed'):
        validate_identity(source[key], key)
        require(source[key]['commit'] == source['commit'], f'{key}-pairing', 'current commit differs')
    require(type(receipt['stages']) is list and len(receipt['stages']) == 3,
            'stage-pairing', 'expected exactly A/B/C')
    for actual, expected in zip(receipt['stages'], stages(lock, source)):
        fields(actual, 'stage emitter std runtime', 'stage')
        require(actual['stage'] == expected['stage'] and actual['emitter'] == expected['emitter'],
                'stage-pairing', 'stage order/emitter differs')
        for key in ('std', 'runtime'):
            validate_identity(actual[key], key)
            require(actual[key] == expected[key], f'{key}-pairing', f'{actual["stage"]} uses wrong {key}')


def verify_inputs(repo, root, lock, receipt, seed_path, seed_tree):
    validate_lock(lock)
    validate_receipt(receipt, lock)
    verify_seed_probe(seed_path, lock)
    _, seed_files = git_files(repo, lock['seed']['commit'])
    for key, prefix in [('std', 'std'), ('runtime', 'runtime/c')]:
        require(lock[key] == identity(lock['seed']['commit'], subtree(seed_files, prefix)),
                f'{key}-pairing', 'seed tree does not match locked commit')
        expected = {p[len(prefix) + 1:]: x for p, x in seed_files.items() if p.startswith(prefix + '/')}
        verify_tree(Path(seed_tree) / prefix, inventory(expected), f'{key}-pairing')
    verify_source(repo, root, receipt)
    return receipt


def verify_source(repo, root, receipt):
    source, files = source_description(repo, receipt['source']['commit'])
    require(source == receipt['source'], 'source-inventory', 'receipt differs from committed inputs')
    verify_tree(root, source['inventory'])
    verify_generated(files)


def write_tree(root, files, readonly=True):
    root = safe_destination(root)
    root.mkdir(parents=True, exist_ok=False)
    for path, (mode, data) in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod((0o555 if mode == '100755' else 0o444) if readonly else
                     (0o755 if mode == '100755' else 0o644))
    if readonly:
        for directory, _, _ in os.walk(root, topdown=False):
            Path(directory).chmod(0o555)
