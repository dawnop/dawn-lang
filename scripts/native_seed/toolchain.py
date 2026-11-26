"""Materialize the single qualification C toolchain, without a host filesystem mount."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

from native_seed import contract as c
from native_seed.probes import ACTIVE, runner, same_binding
from native_seed.recipe import STAGE_OPTIONS, compiler_probe, qualification_flags

RECIPE = 'ubuntu24-clang18.1.3-gcc13-static-v2'
SCAFFOLD = ('src', 'seed', 'emitter', 'out', 'home', 'tmp', 'dev', 'proc', 'etc', 'run')
TOOLS = ('bash', 'env', 'dirname', 'find', 'sort', 'mktemp', 'rm', 'wc', 'tr', 'cut', 'xargs')
FORBIDDEN = re.compile(r'^(?:java(?:c)?|jre|jdk|libjvm\.so|ccache|sccache)(?:[.-].*)?$')

GCC_DIRECTORY = '/usr/lib/gcc/x86_64-linux-gnu/13'
LIBC_DIRECTORY = '/usr/lib/x86_64-linux-gnu'
DRIVER_INPUTS = {
    'libgcc.a': GCC_DIRECTORY, 'libgcc_eh.a': GCC_DIRECTORY,
    'crtbeginT.o': GCC_DIRECTORY, 'crtend.o': GCC_DIRECTORY,
    'crt1.o': LIBC_DIRECTORY, 'crti.o': LIBC_DIRECTORY, 'crtn.o': LIBC_DIRECTORY,
    'libc.a': LIBC_DIRECTORY, 'libm.a': LIBC_DIRECTORY,
}


def driver_inputs(cc, env):
    flags = qualification_flags()
    selected = {}
    run_query = runner()
    def query(name):
        result = run_query([str(cc), *flags, '-print-file-name=' + name], env=env,
                                capture_output=True, text=True, timeout=20)
        path = result.stdout.strip()
        valid = result.returncode == 0 and not result.stderr and path and '\n' not in path
        return name, path, valid

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(query, DRIVER_INPUTS))
    for name, path, valid_probe in results:
        if not valid_probe:
            for selected_path in selected.values():
                print(selected_path, file=sys.stderr)
            print(path if path and '\n' not in path else name, file=sys.stderr)
        c.require(valid_probe, 'toolchain-recipe', 'compiler input path probe failed')
        selected[name] = str(Path(path).resolve()) if Path(path).is_absolute() else path
    valid = all(Path(path).is_absolute() and Path(path).parent == Path(DRIVER_INPUTS[name]) and
                Path(path).name == name and Path(path).is_file() for name, path in selected.items())
    if not valid:
        for path in selected.values():
            print(path, file=sys.stderr)
    c.require(valid, 'toolchain-recipe', 'compiler inputs must resolve inside the captured GCC 13 and libc directories')
    return {'flags': flags, 'files': selected}


def verify_driver(value, rows):
    c.fields(value, 'flags files', 'compiler driver')
    c.require(value['flags'] == qualification_flags(), 'toolchain-recipe', 'qualification flags differ')
    c.fields(value['files'], ' '.join(DRIVER_INPUTS), 'compiler input paths')
    inventory = {row['path'] for row in rows if row['kind'] == 'file'}
    for name, directory in DRIVER_INPUTS.items():
        path = value['files'][name]
        c.require(type(path) is str and path == directory + '/' + name and path[1:] in inventory,
                  'toolchain-identity', 'selected compiler input is outside the captured closure')


def recipe_identity(value, recipe_sha256):
    """Portable recipe equality; the complete byte snapshot is bound separately."""
    c.sha(recipe_sha256, 'C recipe')
    rows = {row['path']: row['sha256'] for row in value['inventory']}
    return {'recipe': value['recipe'], 'recipe_sha256': recipe_sha256,
            'clang': {key: value['compiler'][key] for key in ('sha256', 'version', 'triple')},
            'inputs': {name: {'path': path, 'sha256': rows[path.lstrip('/')]}
                       for name, path in value['driver']['files'].items()},
            'flags': [*STAGE_OPTIONS, *value['driver']['flags']],
            'ld_version': value['linker']['version']}


def verify_linker(value):
    c.fields(value, 'executable version', 'linker probe')
    c.require(value['executable'] == '/usr/bin/ld.bfd' and type(value['version']) is str and
              value['version'].startswith('GNU ld ') and '\n' not in value['version'],
              'toolchain-identity', 'invalid linker version probe')


def prepare(cc, destination=None, pinned=True, digest_cache=None):
    c.require(digest_cache is None or destination is None, 'stat-cache-scope', 'materialized toolchains require full bytes')
    if destination is not None:
        destination = c.safe_destination(destination)
        c.require(not destination.exists(), 'destination', 'new toolchain directory required')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    probe = compiler_probe(cc, env, pinned=pinned)
    driver = driver_inputs(probe['executable'], env)
    run_query = runner()
    ld = run_query(['/usr/bin/ld.bfd', '--version'], env=env,
                        capture_output=True, text=True, timeout=20)
    c.require(ld.returncode == 0 and not ld.stderr and ld.stdout.splitlines(),
              'toolchain-identity', 'linker version probe failed')
    linker = {'executable': '/usr/bin/ld.bfd', 'version': ld.stdout.splitlines()[0]}
    verify_linker(linker)
    c.require(not pinned or (probe['executable'] == '/usr/lib/llvm-18/bin/clang' and
              probe['resource_dir'] == '/usr/lib/llvm-18/lib/clang/18' and
              Path('/usr/lib/gcc/x86_64-linux-gnu/13').is_dir()),
              'toolchain-recipe', 'the Ubuntu clang 18.1.3 and GCC 13 layout is required')
    files, origins, executables = {}, {}, {}

    def add(path, target=None, executable=False):
        path = os.path.normpath(path)
        logical = (target or path).lstrip('/')
        c.logical(logical)
        if digest_cache is None:
            path = Path(path)
            c.require(path.is_file(), 'toolchain-input', f'missing toolchain file: {path}')
            origin = str(path.resolve())
            data = path.read_bytes()
        else:
            origin = digest_cache.resolve(path)
            data = digest_cache.read(origin, status=digest_cache.resolved_status.get(origin))
        if logical in files:
            c.require(c.digest(files[logical][1]) == c.digest(data), 'toolchain-input', 'conflicting toolchain paths')
        files[logical] = ('100755' if executable else '100644', data)
        origins[logical] = origin
        if executable:
            executables['/' + logical] = c.digest(data)

    def tree(path):
        # Resolve input symlinks into ordinary snapshot files, never retain an external link.
        for directory, dirs, names in os.walk(path, followlinks=True):
            if digest_cache is not None:
                digest_cache.watch_directory(digest_cache.resolve(directory))
            for name in names:
                add(os.path.join(directory, name))

    programs = [Path(probe['executable']), Path('/usr/bin/ld.bfd')]
    programs += [Path('/usr/bin') / name for name in TOOLS]
    programs += [Path('/bin/sh'), Path('/bin/bash')]
    def dependencies(path):
        result = run_query(['/usr/bin/ldd', str(path)], env=env,
                                capture_output=True, text=True, timeout=20)
        c.require(result.returncode == 0, 'toolchain-input', f'ldd failed: {path}')
        return re.findall(r'(?:=>\s+|^\s*)(/[^\s()]+)', result.stdout, re.M)

    with ThreadPoolExecutor(max_workers=8) as pool:
        closures = list(pool.map(dependencies, programs))
    for path, closure in zip(programs, closures):
        add(path, executable=True)
        for dependency in closure:
            add(dependency, executable=Path(dependency).name.startswith('ld-linux-'))
    add('/usr/bin/ld.bfd', '/usr/bin/ld', executable=True)
    tree('/usr/include')
    tree(probe['resource_dir'])
    tree('/usr/lib/gcc/x86_64-linux-gnu/13/include')
    gcc = Path('/usr/lib/gcc/x86_64-linux-gnu/13')
    if digest_cache is not None:
        digest_cache.watch_directory(gcc)
        digest_cache.watch_directory('/usr/lib/x86_64-linux-gnu')
    for path in sorted(gcc.iterdir()):
        if path.suffix in ('.a', '.o') or path.name == 'libgcc_s.so':
            add(path)
    libc = Path('/usr/lib/x86_64-linux-gnu')
    for pattern in ('crt*.o', 'Scrt1.o', 'libc.a', 'libc_nonshared.a', 'libm.a',
                    'libm-*.a', 'libmvec.a', 'libpthread.a', 'libdl.a', 'librt.a',
                    'libc.so', 'libm.so', 'libmvec.so.1'):
        matches = sorted(libc.glob(pattern))
        c.require(matches, 'toolchain-input', f'missing sysroot component: {pattern}')
        for path in matches:
            add(path)
    # GNU libm.so names this absolute path even on merged-/usr systems.
    add('/lib/x86_64-linux-gnu/libmvec.so.1')
    for path in files:
        c.require(not any(FORBIDDEN.fullmatch(part) for part in path.split('/')),
                  'toolchain-forbidden', f'Java or cache tool in snapshot: {path}')
    # A read-only root needs an existing file on which to mount each current emitter.
    files['emitter/dawnc'] = ('100644', b'')
    origins['emitter/dawnc'] = 'generated-mount-point-v1'
    rows = c.inventory(files)
    result = {'schema': 1, 'kind': 'native-cold-toolchain', 'recipe': RECIPE if pinned else 'development-clang-gcc13-static-v1',
              'compiler': probe, 'driver': driver, 'linker': linker, 'inventory': rows, 'inventory_sha256': c.inventory_sha(rows),
              'executables': executables, 'origins': origins, 'scaffold': list(SCAFFOLD)}
    session = ACTIVE.get()
    if digest_cache is not None and session is not None:
        paths = [*programs, '/usr/bin/ldd', '/etc/ld.so.cache', '/etc/ld.so.preload',
                 *driver['files'].values(), *(path for closure in closures for path in closure)]
        directories = [str(Path(path).parent) for path in paths]
        directories += [str(Path(probe['executable']).parent.parent / 'lib'),
                        '/usr/lib/gcc/x86_64-linux-gnu']
        if session.reuse and not same_binding(session.binding(paths, directories), session.expected):
            # Fresh ldd may discover a new dependency despite unchanged known
            # files. Re-probe all answers against that new resolution closure.
            session.restart()
            return prepare(cc, destination=destination, pinned=pinned, digest_cache=digest_cache)
        session.finish(paths, directories)
    if destination is None:
        return result
    destination.mkdir(parents=True)
    c.write_tree(destination / 'root', files, readonly=False)
    for name in SCAFFOLD:
        (destination / 'root' / name).mkdir(exist_ok=True)
    for directory, _, names in os.walk(destination / 'root', topdown=False):
        for name in names:
            path = Path(directory) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        Path(directory).chmod(0o755)
    c.atomic_json(destination / 'toolchain.json', result)
    return result


def verify(directory):
    directory = Path(directory).absolute()
    value = c.read_json(directory / 'toolchain.json')
    verify_record(value)
    c.require(type(value['schema']) is int and value['schema'] == 1 and
              value['kind'] == 'native-cold-toolchain' and value['recipe'] == RECIPE and
              value['scaffold'] == list(SCAFFOLD), 'toolchain-recipe', 'unknown toolchain recipe')
    probe = value['compiler']
    c.fields(probe, 'executable sha256 version triple resource_dir', 'toolchain compiler')
    c.require(probe['executable'] == '/usr/lib/llvm-18/bin/clang' and
              probe['resource_dir'] == '/usr/lib/llvm-18/lib/clang/18' and
              re.search(r'\bclang version 18\.1\.3\b', probe['version']) and
              re.fullmatch(r'x86_64-(?:[a-z0-9_]+-)?linux-gnu', probe['triple']),
              'toolchain-recipe', 'compiler probe differs from the qualification recipe')
    rows = c.inventory(c.scan(directory / 'root'))
    c.require(rows == value['inventory'] and c.inventory_sha(rows) == value['inventory_sha256'],
              'toolchain-identity', 'toolchain bytes, names or modes changed')
    expected_dirs = set(SCAFFOLD)
    expected_dirs.update(str(parent) for row in rows for parent in PurePosixPath(row['path']).parents
                         if str(parent) != '.')
    actual_dirs = {p.relative_to(directory / 'root').as_posix()
                   for p in (directory / 'root').rglob('*') if p.is_dir()}
    c.require(actual_dirs == expected_dirs, 'toolchain-identity', 'toolchain directory set changed')
    for row in rows:
        c.require(not any(FORBIDDEN.fullmatch(p) for p in row['path'].split('/')),
                  'toolchain-forbidden', 'Java or cache tool in toolchain')
    verify_driver(value['driver'], rows)
    actual = {'/' + row['path']: row['sha256'] for row in rows if row['executable']}
    c.require(actual == value['executables'], 'toolchain-identity', 'executable inventory differs')
    c.require(actual.get(value['compiler']['executable']) == value['compiler']['sha256'],
              'toolchain-identity', 'compiler is not in executable inventory')
    return value


def verify_record(value, pinned=True):
    c.fields(value, 'schema kind recipe compiler driver linker inventory inventory_sha256 executables origins scaffold', 'toolchain')
    c.require(type(value['schema']) is int and value['schema'] == 1 and
              value['kind'] == 'native-cold-toolchain' and value['scaffold'] == list(SCAFFOLD),
              'toolchain-recipe', 'unknown toolchain record')
    c.require(value['recipe'] == RECIPE if pinned else value['recipe'] in
              (RECIPE, 'development-clang-gcc13-static-v1'),
              'toolchain-recipe', 'development toolchains cannot be released or qualified')
    probe = value['compiler']
    c.fields(probe, 'executable sha256 version triple resource_dir', 'toolchain compiler')
    if pinned:
        c.require(probe['executable'] == '/usr/lib/llvm-18/bin/clang' and
                  probe['resource_dir'] == '/usr/lib/llvm-18/lib/clang/18' and
                  re.search(r'\bclang version 18\.1\.3\b', probe['version']),
                  'toolchain-recipe', 'compiler differs from the qualification recipe')
    rows = value['inventory']
    c.require(c.inventory_sha(rows) == value['inventory_sha256'],
              'toolchain-identity', 'toolchain inventory digest differs')
    verify_driver(value['driver'], rows)
    verify_linker(value['linker'])
    actual = {'/' + row['path']: row['sha256'] for row in rows if row['executable']}
    c.require(actual == value['executables'] and actual.get(probe['executable']) == probe['sha256'] and
              '/usr/bin/ld' in actual and '/usr/bin/ld.bfd' in actual and
              re.fullmatch(r'x86_64-(?:[a-z0-9_]+-)?linux-gnu', probe['triple']),
              'toolchain-identity', 'compiler/linker executable identity differs')
    paths = {row['path'] for row in rows}
    c.require({'usr/lib/x86_64-linux-gnu/libc.a', 'usr/lib/gcc/x86_64-linux-gnu/13/libgcc.a'} <= paths and
              all(not any(FORBIDDEN.fullmatch(p) for p in path.split('/')) for path in paths),
              'toolchain-identity', 'static library closure is missing or forbidden')
    return value
