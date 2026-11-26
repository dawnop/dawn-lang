"""Keep the hot projection sealed to the full cache in one atomic publication.

Resealing just one side must not disguise a mixed pair. The unused entry stays
in the full cache but must not be decoded into the hot reader's entry map.
"""

import copy
import os
from unittest.mock import patch

from native_seed import contract as c


def run(work):
    from native_seed.stat_cache import DigestCache, GRAIN_NS
    root = work / 'compact-controls'
    root.mkdir()
    needed, unused = root / 'needed', root / 'unused'
    for path in (needed, unused):
        path.write_bytes(path.name.encode())
        before = path.stat()
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns - 3 * GRAIN_NS))
    path = root / 'cache.json'
    cache = DigestCache()
    cache.read(needed)
    cache.read(unused)
    cache.save(path, 'a' * 64, compact_paths={str(needed)})
    original = path.read_bytes()
    assert len(DigestCache.load(path, 'a' * 64).entries) == 2
    hot = DigestCache.load_hot(path, 'a' * 64)
    assert set(hot.entries) == {str(needed)}, 'hot load decoded unused full-cache rows'
    assert c.digest(hot.read(needed)) == c.digest(b'needed') and hot.hashes == 0
    print('OK the compact reader loads only its selected rows')
    def refused(value, label):
        path.chmod(0o644)
        path.write_bytes(c.canonical(value))
        try:
            DigestCache.load_hot(path, 'a' * 64)
        except c.Rejected as exc:
            assert 'stat-cache' in str(exc), str(exc)
        else:
            raise AssertionError(label)
    value = c.read_json(path)
    changed = copy.deepcopy(value)
    changed['index']['payload']['entries'][str(needed)]['sha256'] = 'f' * 64
    refused(changed, 'tampered compact index accepted')
    print('OK compact index corruption is rejected')
    changed['index']['sha256'] = c.digest(c.canonical(changed['index']['payload']))
    refused(changed, 'compact index inconsistent with the full cache accepted')
    print('OK a resealed compact index still fails its full-cache link')
    changed = copy.deepcopy(value)
    changed['payload']['entries'][str(unused)]['sha256'] = 'e' * 64
    changed['sha256'] = c.digest(c.canonical(changed['payload']))
    refused(changed, 'full cache inconsistent with the compact index accepted')
    print('OK a changed full cache fails the reverse link')
    path.write_bytes(original)
    from native_seed import stat_cache
    with patch.object(stat_cache, 'replace_json', wraps=stat_cache.replace_json) as writer:
        cache.save(path, 'a' * 64, compact_paths={str(needed)})
        assert writer.call_count == 1, 'full cache and compact index were published separately'
    assert DigestCache.load_hot(path, 'a' * 64).entries == hot.entries
    print('OK one atomic publication contains both sealed cache views')
