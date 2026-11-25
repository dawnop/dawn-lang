"""Keep metadata shortcuts sensitive to timestamp races and damaged state.

These controls run with the launcher self-test, so no extra CI step or second
compiler bootstrap is needed. Filesystem cleanup is tested as an ordinary user.
"""

import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from native_seed import contract as c


def run(work):
    from native_seed.stat_cache import DigestCache, GRAIN_NS
    root = work / 'stat-controls'
    root.mkdir()
    source = root / 'source'
    source.write_bytes(b'before')
    old = source.stat()
    os.utime(source, ns=(old.st_atime_ns, old.st_mtime_ns - 3 * GRAIN_NS))
    cache_path = root / 'cache.json'
    cache = DigestCache()
    before = c.digest(cache.read(source))
    cache.save(cache_path, 'a' * 64)
    cache = DigestCache.load(cache_path, 'a' * 64)
    assert c.digest(cache.read(source)) == before and cache.hashes == 0
    saved = source.stat()
    source.write_bytes(b'after!')
    os.utime(source, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    assert c.digest(cache.read(source)) != before and cache.hashes == 1
    print('OK restored mtime with changed ctime invalidates')
    cache.save(cache_path, 'a' * 64)
    cache = DigestCache.load(cache_path, 'a' * 64)
    replacement = root / 'replacement'
    replacement.write_bytes(b'inode!')
    os.utime(replacement, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    os.replace(replacement, source)
    assert c.digest(cache.read(source)) == c.digest(b'inode!') and cache.hashes == 1
    print('OK replaced inode with restored mtime invalidates')
    # Even an exactly matching stat proxy is racy in the cache write bucket.
    now = source.stat().st_mtime_ns
    cache = DigestCache()
    cache.read(source)
    with patch('native_seed.stat_cache.time.time_ns', return_value=now):
        cache.save(cache_path, 'a' * 64)
    cache = DigestCache.load(cache_path, 'a' * 64)
    cache.read(source)
    assert cache.hashes == 1, 'same-granularity entry escaped hashing'
    print('OK same-granularity matching stat forces rehash')
    value = c.read_json(cache_path)
    value['payload']['entries'][str(source)]['sha256'] = 'f' * 64
    cache_path.chmod(0o644)
    cache_path.write_bytes(c.canonical(value))
    try:
        DigestCache.load(cache_path, 'a' * 64)
    except c.Rejected as exc:
        assert 'stat-cache' in str(exc)
    else:
        raise AssertionError('tampered cache accepted')
    print('OK damaged cache integrity rejected')
    # Toolchain headers use the same content reader and retain set enumeration.
    headers = root / 'include'
    headers.mkdir()
    header = headers / 'fixture.h'
    header.write_bytes(b'one')
    cache = DigestCache()
    first = c.inventory(c.scan(headers, digest_cache=cache))
    header.write_bytes(b'two')
    assert c.inventory(c.scan(headers, digest_cache=cache)) != first
    (headers / 'new.h').write_bytes(b'new')
    assert len(c.inventory(c.scan(headers, digest_cache=cache))) == 2
    print('OK changed and added toolchain headers invalidate')
    readonly = root / 'readonly'
    c.write_tree(readonly, {'nested/file': ('100644', b'owned')})
    assert not (readonly / 'nested/file').stat().st_mode & 0o222
    result = subprocess.run(['rm', '-rf', str(readonly)], capture_output=True)
    assert result.returncode == 0 and not readonly.exists(), result.stderr
    print('OK read-only files and writable directories allow rm -rf')
    repo = root / 'repo'
    repo.mkdir()
    (repo / '.gitignore').write_text('build/\n')
    for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture',
                 '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgSign=false',
                 'commit', '-qm', 'Create fixture']):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    checkout = root / 'checkout'
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(checkout)],
                   check=True, capture_output=True)
    c.write_tree(checkout / 'build/native-toolchain', {'source/nested/file': ('100644', b'owned')})
    subprocess.run(['git', '-C', str(repo), 'worktree', 'remove', str(checkout)],
                   check=True, capture_output=True)
    assert not checkout.exists()
    print('OK git worktree remove succeeds with a populated generation')
