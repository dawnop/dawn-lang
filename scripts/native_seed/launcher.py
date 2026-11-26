"""Cache the shared S -> A -> B builder, then replace the launcher with B.

A generation has a private build directory, an immutable receipt and a final
commit marker. One advisory lock covers preparation, verification and commit;
waiters always recompute their inputs. A failed or incomplete generation is
never permission to execute another generation. This is development evidence,
not a qualification receipt or a release artifact.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile

from native_seed import builder, contract as c, inputs, lockchain, toolchain
from native_seed.stat_cache import DigestCache, replace_json
from native_seed.probes import Queries

try:
    import fcntl
except ImportError:
    fcntl = None

OVERRIDES = ('DAWN_NATIVE_SEED', 'DAWN_NATIVE_SEED_LOCK', 'DAWN_NATIVE_SEED_TREE')


def controls(repo):
    scripts = Path(repo) / 'scripts'
    if not lockchain.present(scripts):
        return None, {'chain': [], 'revoked': {}}
    loaded = lockchain.load(scripts)
    return loaded.lock, {'chain': [c.digest(raw) for _, raw in loaded.chain], 'revoked': loaded.revoked}


def select(repo, fetch, *, git_cache=None, digest_cache=None, probe_cache=None):
    locked, control = controls(repo)
    values = [os.environ.get(name) for name in OVERRIDES]
    c.require(not any(values) or all(values), 'seed-override',
              'DAWN_NATIVE_SEED, DAWN_NATIVE_SEED_LOCK and DAWN_NATIVE_SEED_TREE are required together')
    if all(values):
        seed, lock_path, pair = (Path(value).absolute() for value in values)
        lock = builder.load_lock(lock_path)
        c.require(lock['seed']['sha256'] not in control['revoked'], 'revoked', 'override seed is revoked')
        # regular_bytes plus verify_seed_bytes cover the override type and ELF
        # checks in the same read as the required digest and identity probes.
        lockchain.verify_seed_bytes(c.regular_bytes(seed), lock, probe_cache=probe_cache)
        c.verify_seed_tree(repo, lock, pair, git_cache=git_cache, digest_cache=digest_cache)
        frame = {'selection': 'override', 'lock_sha256': c.digest(c.regular_bytes(lock_path)),
                 'seed_path': str(seed), 'lock_path': str(lock_path), 'pair_path': str(pair)}
    else:
        c.require(locked is not None, 'lock-missing', 'native requires a qualified lock or a complete paired override')
        lock = locked
        lock_path = Path(repo) / 'scripts' / lockchain.LOCK_NAME
        seed = lockchain.cached_seed(lock, Path(repo) / '.dawn/native-seeds', fetch, probe_cache=probe_cache)
        pair = None
        frame = {'selection': 'default', 'lock_sha256': c.digest(c.regular_bytes(lock_path))}
    return lock, lock_path, seed, pair, dict(frame, controls=control)


def snapshot(repo, lock, frame, cc, development_cc, *, digest_cache=None, git_cache=None, live_paths=None, baseline=None):
    commit = c.git(repo, 'rev-parse', 'HEAD').decode().strip()
    tree, files = builder.source_files(repo, commit, live=True, digest_cache=digest_cache,
                                       git_cache=git_cache, live_paths=live_paths)
    tc = toolchain.prepare(cc, pinned=not development_cc, digest_cache=digest_cache,
                           **({'baseline': baseline['toolchain'], 'dependencies': baseline['dependencies']}
                              if baseline is not None else {}))
    toolchain.verify_record(tc, pinned=not development_cc)
    compilation = inputs.compilation(files, lock, tc)
    value = {'schema': 1, 'kind': 'native-launcher-inputs', 'chain': 'native', 'stage': 'B',
             'execution': 'development', 'frame': frame, 'commit': commit, 'tree': tree,
             'source_sha256': c.inventory_sha(c.inventory(files)),
             'compilation_sha256': c.digest(c.canonical(compilation)),
             'development_cc': development_cc}
    return value, files, tc, compilation


def verify(directory, expected, files, tc, repo, lock, marker=None, *, digest_cache=None, git_cache=None, compilation=None, probe_cache=None):
    marker = c.read_json(directory / 'committed.json') if marker is None else marker
    c.fields(marker, 'schema kind inputs_sha256 receipt_sha256 chain_sha256', 'generation commit')
    c.require(marker['schema'] == 1 and marker['kind'] == 'native-launcher-commit' and
              marker['inputs_sha256'] == c.digest(c.canonical(expected)),
              'generation-commit', 'missing, foreign or incomplete native generation')
    receipt = c.read_json(directory / 'generation.json')
    c.fields(receipt, 'schema kind inputs chain_sha256 binary stage build_id elf_sha256', 'generation receipt')
    c.require(c.regular_bytes(directory / 'generation.json') == c.canonical(receipt) and
              marker['receipt_sha256'] == c.digest(c.canonical(receipt)) and
              receipt['schema'] == 1 and receipt['kind'] == 'native-launcher-generation' and
              receipt['inputs'] == expected and receipt['binary'] == 'B/dawnc' and receipt['stage'] == 'B',
              'generation-receipt', 'native generation receipt differs')
    chain_path = directory / 'chain-receipt.json'
    chain_raw = c.regular_bytes(chain_path)
    c.require(receipt['chain_sha256'] == marker['chain_sha256'] == c.digest(chain_raw),
              'generation-receipt', 'chain receipt differs')
    chain_value = c.read_json(chain_path, raw=chain_raw)
    with ThreadPoolExecutor(max_workers=2) as pool:
        checking = pool.submit(copy_context().run, builder.verify_receipt, chain_path, repo, lock,
                               directory / 'B/dawnc', directory / 'A/dawnc', require_c=False, live=True,
                               development_cc=expected['development_cc'],
                               snapshot={'commit': expected['commit'], 'tree': expected['tree'], 'files': files,
                                         'toolchain': tc, 'source_sha256': expected['source_sha256'],
                                         'compilation': compilation if compilation is not None else inputs.compilation(files, lock, tc)},
                               receipt_data=(chain_raw, chain_value))
        c.verify_tree(directory / 'source', c.inventory(files), digest_cache=digest_cache)
        c.verify_seed_tree(repo, lock, directory / 'seed', git_cache=git_cache, digest_cache=digest_cache)
        lockchain.verify_seed_bytes(c.regular_bytes(directory / 'seed-elf'), lock, probe_cache=probe_cache)
        for stage in ('A', 'B'):
            c.require(builder.output_identity(directory / stage, digest_cache=digest_cache) == chain_value['stages'][stage]['output'],
                      'generation-output', 'stage bytes differ from the builder receipt')
        chain = checking.result()
    c.require(chain['execution']['kind'] == 'development' and chain['toolchain'] == tc,
              'generation-toolchain', 'actual toolchain or development scope differs')
    c.require(builder.plan(directory / 'B/dawnc', directory / 'source') == chain['plan_sha256'],
              'generation-plan', 'B source plan differs')
    c.require(receipt['elf_sha256'] == chain['stages']['B']['output']['elf_sha256'] and
              receipt['build_id'] == chain['stages']['B']['build_id'],
              'generation-output', 'B digest or full build ID differs')
    return receipt


def sync_tree(directory):
    # The marker is a durable commit, so all files and renamed directories must
    # reach storage first. A killed builder can leave staging, never a marker.
    for parent, _, names in os.walk(directory, topdown=False):
        for name in names:
            fd = os.open(Path(parent) / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_directory(Path(parent))


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def generation(repo, fetch, cache=None):
    c.require(platform.system() == 'Linux' and platform.machine() == 'x86_64',
              'native-platform', 'native source launcher requires Linux x86_64')
    c.require(sys.version_info >= (3, 11), 'native-python', 'native source launcher requires Python 3.11+')
    c.require(not os.environ.get('DAWN_SEED'), 'seed-override', 'native rejects DAWN_SEED')
    cache = c.safe_destination(cache or Path(repo) / 'build/native-toolchain')
    cache.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(c.safe_destination(cache / 'build.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'r+') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        git_cache = {}
        probe_cache = {}
        digests = DigestCache()
        hint = cache / 'last-generation.json'
        baseline = None
        last = None
        if hint.exists():
            last = c.read_json(hint)
            c.fields(last, 'generation sha256', 'generation hint')
            c.require(last['sha256'] == c.digest(c.canonical(last['generation'])),
                      'stat-cache', 'generation hint integrity differs')
            c.sha(last['generation'], 'generation hint')
            previous = cache / 'generations' / last['generation'] / 'stat-cache.json'
            if previous.exists():
                digests = DigestCache.load(previous, last['generation'])
                chain_raw = c.regular_bytes(previous.with_name('chain-receipt.json'))
                old_generation = c.read_json(previous.with_name('generation.json'))
                old_marker = c.read_json(previous.with_name('committed.json'))
                c.require(c.digest(chain_raw) == old_generation.get('chain_sha256') == old_marker.get('chain_sha256'),
                          'generation-receipt', 'chain receipt differs before dependency reuse')
                baseline = c.read_json(previous.with_name('chain-receipt.json'), raw=chain_raw)
                if 'dependencies' not in baseline:
                    baseline = None
        lock, lock_path, seed, pair, frame = select(repo, fetch, git_cache=git_cache, digest_cache=digests, probe_cache=probe_cache)
        cc = os.environ.get('CC', '/usr/lib/llvm-18/bin/clang')
        cc = shutil.which(cc) or cc
        # Alternate clang is allowed only as a development recipe. All source
        # launcher generations, including pinned clang, remain development.
        development_cc = str(Path(cc).resolve()) != '/usr/lib/llvm-18/bin/clang'
        live_paths = c.git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard')
        queries = Queries(digests, cc, pinned=not development_cc,
                          allow_reuse=hint.exists(),
                          driver_paths=[directory + '/' + name for name, directory in toolchain.DRIVER_INPUTS.items()])
        with queries.activate():
            expected, files, tc, compilation = snapshot(repo, lock, frame, cc, development_cc, digest_cache=digests, git_cache=git_cache, live_paths=live_paths, baseline=baseline)
        key = c.digest(c.canonical(expected))
        generations = c.safe_destination(cache / 'generations')
        generations.mkdir(exist_ok=True)
        directory = c.safe_destination(generations / key)
        cold = not directory.exists()
        if cold:
            # A cold path always captures full bytes, irrespective of a hint.
            expected, files, tc, compilation = snapshot(repo, lock, frame, cc, development_cc, git_cache=git_cache)
            key = c.digest(c.canonical(expected))
            directory = c.safe_destination(generations / key)
            cold = not directory.exists()
        if cold:
            staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=cache))
            output = staging / 'generation'
            # Preserve a failed staging tree for diagnosis; never consult it
            # when choosing a subsequent generation.
            chain = builder.build(repo, lock_path, seed, pair, output, cc, jobs=1,
                                  live=True, development_cc=development_cc)
            c.require(select(repo, fetch)[-1] == frame, 'generation-inputs', 'seed controls changed during build')
            c.require(snapshot(repo, lock, frame, cc, development_cc)[0] == expected,
                      'generation-inputs', 'inputs changed during build')
            receipt = {'schema': 1, 'kind': 'native-launcher-generation', 'inputs': expected,
                       'chain_sha256': c.digest(c.regular_bytes(output / 'chain-receipt.json')),
                       'binary': 'B/dawnc', 'stage': 'B', 'build_id': chain['stages']['B']['build_id'],
                       'elf_sha256': chain['stages']['B']['output']['elf_sha256']}
            c.atomic_json(output / 'generation.json', receipt)
            marker = {'schema': 1, 'kind': 'native-launcher-commit', 'inputs_sha256': key,
                      'receipt_sha256': c.digest(c.canonical(receipt)), 'chain_sha256': receipt['chain_sha256']}
            verify(output, expected, files, tc, repo, lock, marker=marker, git_cache=git_cache, compilation=compilation, probe_cache=probe_cache)
            for parent, _, names in os.walk(output):
                for name in names:
                    path = Path(parent) / name
                    path.chmod(0o555 if path.stat().st_mode & 0o111 else 0o444)
            sync_tree(output)
            os.rename(output, directory)
            sync_directory(generations)
            c.atomic_json(directory / 'committed.json', marker)
            (directory / 'committed.json').chmod(0o444)
            staging.rmdir()
        if cold:
            receipt = verify(directory, expected, files, tc, repo, lock, digest_cache=digests, git_cache=git_cache, compilation=compilation, probe_cache=probe_cache)
        else:
            with queries.activate():
                receipt = verify(directory, expected, files, tc, repo, lock, digest_cache=digests, git_cache=git_cache, compilation=compilation, probe_cache=probe_cache)
        queries.recheck()
        # Re-read control records and the external paired override immediately
        # before handing the verified executable to the caller.
        c.require(select(repo, fetch, git_cache=git_cache, digest_cache=digests, probe_cache=probe_cache)[-1] == frame, 'generation-inputs', 'seed controls changed during verification')
        c.require(c.git(repo, 'rev-parse', 'HEAD').decode().strip() == expected['commit'] and
                  c.git(repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard') == live_paths,
                  'generation-inputs', 'source provenance or live file set changed during verification')
        digests.recheck()
        stat_path = directory / 'stat-cache.json'
        if digests.changed or not stat_path.exists():
            digests.save(stat_path, key)
        if last is None or last['generation'] != key:
            replace_json(hint, {'generation': key, 'sha256': c.digest(c.canonical(key))})
        stamp = 'native-v1:development:' + frame['selection'] + ':' + key + ':' + receipt['elf_sha256']
        return {'stamp': stamp, 'executable': str(directory / 'B/dawnc'),
                'receipt': str(directory / 'generation.json')}


def launch(repo, argv, fetch):
    selected = generation(repo, fetch)
    if os.environ.get('DAWN_PRINT_STAMP') == '1':
        print(selected['stamp'])
        return 0
    if os.environ.get('DAWN_NATIVE_PRINT_GENERATION') == '1':
        sys.stdout.buffer.write(c.canonical(selected))
        return 0
    # No child process remains: argv/cwd, exit status and signal delivery are
    # the native compiler's own contract, as for the shell's JVM exec.
    os.execv(selected['executable'], [selected['executable'], *argv])
