"""Content identities exclude the records that will later name their evidence.

The conservative source inventory includes scripts and the prototype so their
removal before the freeze is visible. Only the enumerated seed control records
are excluded. Commit/tree remain provenance, never a recursive compilation key.
"""

from native_seed import contract as c

CONTROL_FILES = {'scripts/native-seed-lock.json', 'scripts/native-seed-revoked.txt',
                 'scripts/native-seed-candidate-v0.104.0.json', 'scripts/seed-release.txt',
                 'scripts/seed-checksums.txt', 'scripts/seed-std-checksums.txt'}
CONTROL_PREFIXES = ('scripts/native-seed-history/',)
COMPILE_PREFIXES = ('selfhost/', 'compiler-plan/', 'packages/', 'std/', 'runtime/',
                    'scripts/', '.github/', 'bin/')


def compilation_files(files):
    return {p: value for p, value in files.items()
            if p.startswith(COMPILE_PREFIXES) and p not in CONTROL_FILES and not p.startswith(CONTROL_PREFIXES)}


def seed_identity(lock):
    c.validate_lock(lock)
    return {'seed': {key: lock['seed'][key] for key in
                     ('kind', 'asset', 'sha256', 'size', 'target', 'version', 'build_id')},
            'std': {key: lock['std'][key] for key in ('algorithm', 'sha256')},
            'runtime': {key: lock['runtime'][key] for key in ('algorithm', 'sha256')}}


def toolchain_identity(value):
    # Origin paths are preparation diagnostics, not executable inputs.
    return c.digest(c.canonical({key: value[key] for key in
                    ('recipe', 'compiler', 'inventory_sha256', 'executables')}))


def compilation(files, lock, tc):
    selected = compilation_files(files)
    c.require('selfhost/src/nmain.dawn' in selected, 'source-missing', 'native entry missing')
    return {'schema': 1, 'kind': 'native-compilation-inputs',
            'source_sha256': c.inventory_sha(c.inventory(selected)),
            'transform_sha256': c.transform_sha(),
            'seed': seed_identity(lock),
            'recipe_sha256': c.digest(selected['scripts/cc-units.sh'][1]),
            'toolchain_sha256': toolchain_identity(tc)}


def compilation_sha(files, lock, tc):
    return c.digest(c.canonical(compilation(files, lock, tc)))
