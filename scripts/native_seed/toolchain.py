"""Materialize the single qualification C toolchain, without a host filesystem mount."""

import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from native_seed import contract as c
from native_seed.recipe import compiler_probe

RECIPE = 'ubuntu24-clang18.1.3-gcc13-static-v1'
SCAFFOLD = ('src', 'seed', 'emitter', 'out', 'home', 'tmp', 'dev', 'proc', 'etc', 'run')
TOOLS = ('bash', 'env', 'dirname', 'find', 'sort', 'mktemp', 'rm', 'wc', 'tr', 'cut', 'xargs')
FORBIDDEN = re.compile(r'^(?:java(?:c)?|jre|jdk|libjvm\.so|ccache|sccache)(?:[.-].*)?$')


def prepare(cc, destination):
    destination = c.safe_destination(destination)
    c.require(not destination.exists(), 'destination', 'new toolchain directory required')
    env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    probe = compiler_probe(cc, env)
    c.require(probe['executable'] == '/usr/lib/llvm-18/bin/clang' and
              probe['resource_dir'] == '/usr/lib/llvm-18/lib/clang/18' and
              Path('/usr/lib/gcc/x86_64-linux-gnu/13').is_dir(),
              'toolchain-recipe', 'the Ubuntu clang 18.1.3 and GCC 13 layout is required')
    files, origins, executables = {}, {}, {}

    def add(path, target=None, executable=False):
        path = Path(os.path.normpath(path))
        logical = (target or path.as_posix()).lstrip('/')
        c.logical(logical)
        c.require(path.is_file(), 'toolchain-input', f'missing toolchain file: {path}')
        data = path.read_bytes()
        if logical in files:
            c.require(files[logical][1] == data, 'toolchain-input', 'conflicting toolchain paths')
        files[logical] = ('100755' if executable else '100644', data)
        origins[logical] = str(path.resolve())
        if executable:
            executables['/' + logical] = c.digest(data)

    def tree(path):
        # Resolve input symlinks into ordinary snapshot files, never retain an external link.
        for directory, dirs, names in os.walk(path, followlinks=True):
            for name in names:
                add(Path(directory) / name)

    programs = [Path(probe['executable']), Path('/usr/bin/ld.bfd')]
    programs += [Path('/usr/bin') / name for name in TOOLS]
    programs += [Path('/bin/sh'), Path('/bin/bash')]
    for path in programs:
        add(path, executable=True)
        result = subprocess.run(['/usr/bin/ldd', str(path)], env=env,
                                capture_output=True, text=True, timeout=20)
        c.require(result.returncode == 0, 'toolchain-input', f'ldd failed: {path}')
        for dependency in re.findall(r'(?:=>\s+|^\s*)(/[^\s()]+)', result.stdout, re.M):
            add(dependency, executable=Path(dependency).name.startswith('ld-linux-'))
    add('/usr/bin/ld.bfd', '/usr/bin/ld', executable=True)
    tree('/usr/include')
    tree(probe['resource_dir'])
    tree('/usr/lib/gcc/x86_64-linux-gnu/13/include')
    gcc = Path('/usr/lib/gcc/x86_64-linux-gnu/13')
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
    result = {'schema': 1, 'kind': 'native-cold-toolchain', 'recipe': RECIPE,
              'compiler': probe, 'inventory': rows, 'inventory_sha256': c.inventory_sha(rows),
              'executables': executables, 'origins': origins, 'scaffold': list(SCAFFOLD)}
    destination.mkdir(parents=True)
    c.write_tree(destination / 'root', files, readonly=False)
    for name in SCAFFOLD:
        (destination / 'root' / name).mkdir(exist_ok=True)
    for directory, _, names in os.walk(destination / 'root', topdown=False):
        for name in names:
            path = Path(directory) / name
            path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
        Path(directory).chmod(0o555)
    c.atomic_json(destination / 'toolchain.json', result)
    return result


def verify(directory):
    directory = Path(directory).absolute()
    value = c.read_json(directory / 'toolchain.json')
    c.fields(value, 'schema kind recipe compiler inventory inventory_sha256 executables origins scaffold', 'toolchain')
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
    actual = {'/' + row['path']: row['sha256'] for row in rows if row['executable']}
    c.require(actual == value['executables'], 'toolchain-identity', 'executable inventory differs')
    c.require(actual.get(value['compiler']['executable']) == value['compiler']['sha256'],
              'toolchain-identity', 'compiler is not in executable inventory')
    return value
