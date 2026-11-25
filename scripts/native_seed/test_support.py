"""Synthetic records for protocol controls, never used by a release workflow.

These fixtures describe fake stage outputs. They exercise the same strict
consumer without running a complete native chain inside every protocol test.
The workflow has its own fixed qualified-lock path and only uploads builder
output, not these fixtures.
"""

from pathlib import Path

from native_seed import builder, contract as c, inputs, toolchain


def compiler_record():
    cc = '/usr/lib/llvm-18/bin/clang'
    files = {p: ('100755' if executable else '100644', b'fixture ' + p.encode())
             for p, executable in ((cc[1:], True), ('usr/bin/ld', True), ('usr/bin/ld.bfd', True),
                                   ('usr/lib/x86_64-linux-gnu/libc.a', False),
                                   ('usr/lib/gcc/x86_64-linux-gnu/13/libgcc.a', False))}
    rows = c.inventory(files)
    return {'schema': 1, 'kind': 'native-cold-toolchain', 'recipe': toolchain.RECIPE,
            'compiler': {'executable': cc, 'sha256': c.digest(files[cc[1:]][1]),
                         'version': 'Ubuntu clang version 18.1.3 (fixture)',
                         'triple': 'x86_64-pc-linux-gnu', 'resource_dir': '/usr/lib/llvm-18/lib/clang/18'},
            'inventory': rows, 'inventory_sha256': c.inventory_sha(rows),
            'executables': {'/' + row['path']: row['sha256'] for row in rows if row['executable']},
            'origins': {p: 'fixture' for p in files}, 'scaffold': list(toolchain.SCAFFOLD)}


def chain_record(repo, lock, a, b):
    commit = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
    tree, files = builder.source_files(repo, commit)
    tc = compiler_record()
    compilation = inputs.compilation(files, lock, tc)
    stages, emitter = {}, lock['seed']['sha256']
    for name, binary in (('A', a), ('B', b), ('C', b)):
        stage = {'emitter_sha256': emitter,
                 'std': lock['std'] if name == 'A' else c.identity(commit, c.subtree(files, 'std')),
                 'runtime': lock['runtime'] if name == 'A' else c.identity(commit, c.subtree(files, 'runtime/c')),
                 'output': {key: c.digest((name if name == 'A' else 'B').encode())
                            for key in builder.OUTPUT_FIELDS.split()},
                 'build_id': builder.identity(binary)[1]}
        stage['output']['elf_sha256'] = c.digest(c.regular_bytes(binary))
        stages[name] = stage
        emitter = stage['output']['elf_sha256']
    return {'schema': 1, 'kind': 'native-builder-chain', 'source_commit': commit, 'source_tree': tree,
            'source_sha256': c.inventory_sha(c.inventory(files)), 'lock_sha256': c.digest(c.canonical(lock)),
            'compilation': compilation, 'compilation_sha256': c.digest(c.canonical(compilation)),
            'toolchain': tc, 'stages': stages, 'plan_sha256': c.digest(b'fixture plan')}
