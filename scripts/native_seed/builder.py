"""One native S -> A -> B builder, with C requested by release callers.

There is no launcher cache here. A private materialized source and seed pair
make stage selection explicit. The shared shell recipe owns every C flag.
Receipts travel with A/B to a different job; that job verifies provenance and
uses the recorded compiler closure, rather than probing its own unrelated CC.
"""

import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from native_seed import contract as c, inputs, lockchain, provenance, recipe, toolchain

ENTRY = 'selfhost/src/nmain.dawn'
OUTPUT_FIELDS = 'whole_sha256 info_sha256 units_sha256 elf_sha256'
RECEIPT_FIELDS = ('schema kind source_commit source_tree source_sha256 lock_sha256 '
                  'compilation compilation_sha256 toolchain recipe_identity execution stages plan_sha256')


def load_lock(path, release=False):
    if release:
        return lockchain.release_lock(path)
    value = c.read_lock(path)
    if value['state'] == 'qualified':
        c.require(lockchain.release_lock(path) == value, 'seed-lock', 'qualified lock differs')
    return value


def prepare_pair(repo, lock, destination):
    _, files = c.git_files(repo, lock['seed']['commit'])
    paired = {p: value for p, value in files.items() if p.startswith(('std/', 'runtime/c/'))}
    for key, prefix in (('std', 'std'), ('runtime', 'runtime/c')):
        c.require(c.identity(lock['seed']['commit'], c.subtree(files, prefix)) == lock[key],
                  key + '-pairing', 'seed commit and pair identity differ')
    c.write_tree(destination, paired)
    c.verify_seed_tree(repo, lock, destination)
    return Path(destination)


def source_files(repo, commit, live=False, *, digest_cache=None, git_cache=None):
    tree, files = c.git_files(repo, commit, metadata_only=live, git_cache=git_cache)
    read = c.regular_bytes if digest_cache is None else digest_cache.read
    if live:
        files = {p: ('100755' if (Path(repo) / p).stat().st_mode & 0o111 else '100644',
                     read(Path(repo) / p)) for p in files
                 if (Path(repo) / p).exists() or (Path(repo) / p).is_symlink()}
        for raw in c.git(repo, 'ls-files', '-z', '--others', '--exclude-standard').split(b'\0'):
            if raw:
                path = c.logical(raw.decode('utf-8'))
                target = Path(repo) / path
                files[path] = ('100755' if target.stat().st_mode & 0o111 else '100644',
                               read(target))
        # Materialize a conservative project superset, including dirty and new
        # source files. Planner still owns the actual nmain dependency closure.
        projects = [Path(repo) / 'selfhost', Path(repo) / 'compiler-plan']
        projects += sorted((Path(repo) / 'packages').iterdir())
        for project in projects:
            prefix = project.relative_to(repo).as_posix()
            for name in ('dawn.toml', 'dawn.lock'):
                path = project / name
                if path.exists() or path.is_symlink():
                    files[prefix + '/' + name] = ('100644', read(path))
            for path, value in c.scan(project / 'src', digest_cache=digest_cache).items():
                files[prefix + '/src/' + path] = value
        for prefix in ('std', 'runtime/c'):
            for path in [p for p in files if p.startswith(prefix + '/')]:
                del files[path]
            files.update({prefix + '/' + p: v for p, v in c.scan(Path(repo) / prefix, digest_cache=digest_cache).items()})
    return tree, c.portable(files)


def output_identity(directory, digest_cache=None):
    directory = Path(directory)
    c.verify_elf(c.regular_bytes(directory / 'dawnc'))
    return {'whole_sha256': c.digest(digest_cache.read(directory / 'whole.c') if digest_cache is not None else c.regular_bytes(directory / 'whole.c')),
            'info_sha256': c.digest(digest_cache.read(directory / 'info.c') if digest_cache is not None else c.regular_bytes(directory / 'info.c')),
            'units_sha256': c.inventory_sha(c.inventory(c.scan(directory / 'units', digest_cache=digest_cache))),
            'elf_sha256': c.digest(c.regular_bytes(directory / 'dawnc'))}


def identity(binary):
    data = c.regular_bytes(binary)
    c.verify_elf(data)
    with tempfile.TemporaryDirectory(prefix='native-builder-probe-') as work:
        private = Path(work) / 'dawnc'
        private.write_bytes(data)
        private.chmod(0o500)
        version = source_version(private)
        return c.probe_seed(data, 'dawnc ' + version + ' (native)')


def source_version(binary):
    # The caller supplies a private verified ELF, never a mutable override.
    run = subprocess.run([str(Path(binary).absolute()), '--version'],
                         env={'PATH': '/nonexistent', 'LANG': 'C.UTF-8'},
                         capture_output=True, timeout=60)
    found = re.fullmatch(rb'dawnc ([0-9]+\.[0-9]+\.[0-9]+) \(native\) b1:[0-9a-f]{12}\n', run.stdout)
    c.require(run.returncode == 0 and not run.stderr and found,
              'stage-start', 'new native compiler cannot start; retain outputs and stop')
    return found[1].decode()


def run_stage(emitter, source, std, runtime, out, cc, jobs):
    out.mkdir()
    with tempfile.TemporaryDirectory(prefix='native-stage-', dir=out.parent) as work:
        env = {'PATH': str(Path(cc).parent) + ':/usr/bin:/bin', 'HOME': work, 'TMPDIR': work,
               'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC', 'CC': cc, 'CC_JOBS': str(jobs)}
        start = time.monotonic()
        subprocess.run(recipe.emission_command(emitter, source / ENTRY, std, out),
                       env=env, cwd=source, check=True, stdout=sys.stderr)
        emitted = time.monotonic()
        subprocess.run(recipe.compilation_command(source / 'scripts/cc-units.sh', runtime, out),
                       env=env, cwd=source, check=True, stdout=sys.stderr)
        print(f'timing emit {emitted - start:.1f}s cc {time.monotonic() - emitted:.1f}s', flush=True, file=sys.stderr)
    identity(out / 'dawnc')
    return output_identity(out)


def plan(binary, source):
    run = subprocess.run([str(binary), '__source-inputs', '--base', str(source), str(source / 'selfhost')],
                         env={'PATH': '/nonexistent', 'LANG': 'C.UTF-8'},
                         cwd=source, capture_output=True, timeout=60)
    c.require(run.returncode == 0 and not run.stderr and run.stdout.startswith(b'dawn-source-inputs-v1\n'),
              'source-plan', 'current compiler cannot describe the captured source')
    return c.digest(run.stdout)


def build(repo, lock_path, seed, seed_tree, out, cc, jobs=1, final_stage='B', release=False, live=False, development_cc=False):
    repo, out, seed = Path(repo).absolute(), c.safe_destination(out), Path(seed).absolute()
    c.require(final_stage in ('B', 'C') and jobs == 1, 'stage-pairing', 'B or C and CC_JOBS=1 required')
    c.require(not out.exists(), 'destination', 'native builder requires a new output directory')
    if release:
        c.require(not live and not development_cc, 'release-source', 'release requires committed inputs and pinned CC')
        c.require(not any(name in os.environ for name in
                          ('DAWN_SEED', 'DAWN_NATIVE_SEED', 'DAWN_SEED_CHAIN', 'DAWN_NATIVE_SEED_LOCK')),
                  'seed-override', 'release forbids all seed overrides')
    lock = load_lock(lock_path, release)
    lockchain.verify_seed_bytes(c.regular_bytes(seed), lock)
    commit = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
    execution = provenance.hosted(commit, release=True) if release else provenance.development(commit)
    tree, files = source_files(repo, commit, live)
    c.verify_generated(files)
    tc = toolchain.prepare(cc, pinned=not development_cc)
    toolchain.verify_record(tc, pinned=not development_cc)
    compilation = inputs.compilation(files, lock, tc)
    out.mkdir(parents=True)
    source = out / 'source'
    c.write_tree(source, files)
    paired = out / 'seed'
    if seed_tree is None:
        prepare_pair(repo, lock, paired)
    else:
        c.verify_seed_tree(repo, lock, seed_tree)
        c.write_tree(paired, {p: item for p, item in c.scan(seed_tree).items()
                             if p.startswith(('std/', 'runtime/c/'))})
    private_seed = out / 'seed-elf'
    private_seed.write_bytes(c.regular_bytes(seed))
    private_seed.chmod(0o500)
    lockchain.verify_seed_bytes(private_seed.read_bytes(), lock)
    stages, plans = {}, []
    for name, previous in (('A', None), ('B', 'A'), ('C', 'B')):
        if name == 'C' and final_stage == 'B':
            break
        emitter = private_seed if previous is None else out / previous / 'dawnc'
        base = paired if name == 'A' else source
        print('stage ' + name, flush=True, file=sys.stderr)
        output = run_stage(emitter, source, base / 'std', base / 'runtime/c',
                           out / name, tc['compiler']['executable'], jobs)
        _, build_id = identity(out / name / 'dawnc')
        stages[name] = {'emitter_sha256': c.digest(c.regular_bytes(emitter)),
                        'std': lock['std'] if name == 'A' else c.identity(commit, c.subtree(files, 'std')),
                        'runtime': lock['runtime'] if name == 'A' else c.identity(commit, c.subtree(files, 'runtime/c')),
                        'output': output, 'build_id': build_id}
        plans.append(plan(out / name / 'dawnc', source))
        if previous:
            c.require(plan(emitter, source) == plans[0], 'source-plan', 'emitter plan changed across emission')
        c.require(all(p == plans[0] for p in plans), 'source-plan', 'current stage plans differ')
        if name == 'C':
            c.require(stages['B']['output'] == output and stages['B']['build_id'] == build_id,
                      'fixpoint', 'B/C differ; retain outputs and stop')
    # Recheck the caller, snapshot and actual host compiler closure after all work.
    c.require(source_files(repo, commit, live) == (tree, files), 'source-inventory', 'source changed during build')
    c.verify_tree(source, c.inventory(files))
    c.verify_seed_tree(repo, lock, paired)
    c.require(c.regular_bytes(seed) == private_seed.read_bytes() and load_lock(lock_path, release) == lock,
              'seed-lock', 'seed or control records changed during build')
    c.require(toolchain.prepare(cc, pinned=not development_cc) == tc,
              'cc-identity', 'actual compiler/linker/library closure changed during build')
    receipt = {'schema': 1, 'kind': 'native-builder-chain', 'source_commit': commit, 'source_tree': tree,
               'source_sha256': c.inventory_sha(c.inventory(files)), 'lock_sha256': c.digest(c.canonical(lock)),
               'compilation': compilation, 'compilation_sha256': c.digest(c.canonical(compilation)),
               'toolchain': tc, 'recipe_identity': toolchain.recipe_identity(tc, compilation['recipe_sha256']),
               'execution': execution, 'stages': stages, 'plan_sha256': plans[0]}
    c.atomic_json(out / 'chain-receipt.json', receipt)
    return receipt


def verify_receipt(receipt_path, repo, lock, native, builder, require_c=True, hosted=False, current_run=False,
                   live=False, development_cc=False, snapshot=None):
    c.require(snapshot is None or (live and not hosted and not current_run and not require_c),
              'stat-cache-scope', 'snapshots are only allowed for development launcher verification')
    raw = c.regular_bytes(receipt_path)
    value = c.read_json(receipt_path)
    c.fields(value, RECEIPT_FIELDS, 'chain receipt')
    c.require(raw == c.canonical(value) and type(value['schema']) is int and value['schema'] == 1 and
              value['kind'] == 'native-builder-chain', 'chain-receipt', 'unknown or noncanonical chain receipt')
    if snapshot is None:
        commit = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
        tree, files = source_files(repo, commit, live=live)
    else:
        commit, tree, files = snapshot['commit'], snapshot['tree'], snapshot['files']
    c.require(value['source_commit'] == commit and value['source_tree'] == tree and
              value['source_sha256'] == (c.inventory_sha(c.inventory(files)) if snapshot is None else snapshot['source_sha256']),
              'chain-source', 'chain provenance differs from the producer checkout')
    if snapshot is None:
        toolchain.verify_record(value['toolchain'], pinned=not development_cc)
        compilation = inputs.compilation(files, lock, value['toolchain'])
    else:
        c.require(value['toolchain'] == snapshot['toolchain'], 'chain-inputs', 'actual toolchain differs')
        compilation = snapshot['compilation']
    provenance.verify(value['execution'], commit, hosted=hosted, release=hosted)
    if current_run:
        provenance.current(value['execution'], commit, release=True)
    c.require(value['recipe_identity'] == toolchain.recipe_identity(value['toolchain'], compilation['recipe_sha256']),
              'recipe-identity', 'clang, selected inputs, recipe, flags or linker version differ')
    c.require(value['lock_sha256'] == c.digest(c.canonical(lock)) and
              value['compilation'] == compilation and
              value['compilation_sha256'] == c.digest(c.canonical(compilation)),
              'chain-inputs', 'chain lock, source, recipe or actual CC identity differs')
    c.sha(value['plan_sha256'], 'source plan')
    c.fields(value['stages'], 'A B C' if require_c else 'A B', 'chain stages')
    emitter = lock['seed']['sha256']
    for name in ('A', 'B', 'C') if require_c else ('A', 'B'):
        row = value['stages'][name]
        c.fields(row, 'emitter_sha256 std runtime output build_id', 'chain stage')
        base_std = lock['std'] if name == 'A' else c.identity(commit, c.subtree(files, 'std'))
        base_rt = lock['runtime'] if name == 'A' else c.identity(commit, c.subtree(files, 'runtime/c'))
        c.require(row['emitter_sha256'] == emitter and row['std'] == base_std and row['runtime'] == base_rt,
                  'chain-pairing', 'stage emitter/std/runtime pairing differs')
        c.fields(row['output'], OUTPUT_FIELDS, 'stage output')
        for digest in row['output'].values():
            c.sha(digest, 'stage output')
        c.require(type(row['build_id']) is str and re.fullmatch('b1:[0-9a-f]{64}', row['build_id']),
                  'chain-identity', 'full stage build ID missing')
        emitter = row['output']['elf_sha256']
    stages = value['stages']
    if require_c:
        c.require(stages['B']['output'] == stages['C']['output'] and
                  stages['B']['build_id'] == stages['C']['build_id'], 'fixpoint', 'B/C differ')
    for name, binary in (('A', builder), ('B', native)):
        data = c.regular_bytes(binary)
        c.verify_elf(data)
        c.require(c.digest(data) == stages[name]['output']['elf_sha256'] and
                  identity(binary)[1] == stages[name]['build_id'],
                  'chain-output', 'A/B bytes or full build ID differ from the chain receipt')
    return value


def compare_hosts(left, right):
    """Call after verifying both receipts and their actual B binaries."""
    c.require(left['recipe_identity'] == right['recipe_identity'],
              'recipe-identity', 'cross-host recipes differ; retain evidence and stop')
    c.require(left['stages']['B']['output']['elf_sha256'] == right['stages']['B']['output']['elf_sha256'],
              'host-equivalence', 'same recipe produced different B bytes; retain evidence and stop')
