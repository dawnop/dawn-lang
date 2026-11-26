"""Keep process-local reuse sensitive to bytes and independent stage probes.

Different dictionary objects with equal canonical contents should share work;
mutating one object must not reuse its earlier answer. Each stage still starts
a real private ELF even when the test deliberately supplies equal stage bytes.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from unittest.mock import patch

from native_seed import contract as c
from native_seed.memo import validation_scope


def run(binary):
    rows = c.inventory({'entry': ('100644', b'entry')})
    with validation_scope(), patch.object(c, '_inventory_sha', wraps=c._inventory_sha) as calculation:
        first = c.inventory_sha(rows)
        equivalent = [dict(reversed(list(rows[0].items())))]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, c.inventory_sha, equivalent) for _ in range(2)]
            assert all(future.result() == first for future in futures)
        assert calculation.call_count == 1, 'equal canonical inventories were recalculated'
        rows[0]['size'] += 1
        second = c.inventory_sha(rows)
        assert second != first and calculation.call_count == 2, 'mutable inventory reused an old answer'
        previous = c.canonical(rows)
        digest = rows[0]['sha256']
        rows[0]['sha256'] = digest[:20] + ('f' if digest[20] != 'f' else 'e') + digest[21:]
        changed = c.canonical(rows)
        assert previous[:32] == changed[:32] and previous[-32:] == changed[-32:]
        third = c.inventory_sha(rows)
        assert third != second and calculation.call_count == 3, 'memo lookup trusted a partial byte match'
    with validation_scope(), patch.object(c, '_inventory_sha', wraps=c._inventory_sha) as calculation:
        assert c.inventory_sha(rows) == third
        assert calculation.call_count == 1, 'inventory memo escaped its startup'
    print('OK canonical inventory work runs once and changed contents invalidate it')
    data = b'x' * (1024 * 1024)
    with validation_scope(), patch.object(c.hashlib, 'sha256', wraps=c.hashlib.sha256) as hashing:
        first = c.digest(data)
        assert c.digest(bytes(bytearray(data))) == first and hashing.call_count == 1
        changed = data[:len(data) // 2] + b'y' + data[len(data) // 2 + 1:]
        assert c.digest(changed) != first and hashing.call_count == 2
    print('OK large digest reuse compares complete bytes')
    data = c.regular_bytes(binary)
    with validation_scope(), patch.object(c.subprocess, 'run', wraps=c.subprocess.run) as actual:
        for scope in ('S', 'A', 'B'):
            for _ in range(2):
                c.probe_seed(data, version='dawnc 0.106.0 (native)', scope=scope)
        assert actual.call_count == 6, 'S/A/B must each probe version and full build ID once'
    print('OK S/A/B each execute real version and full build ID probes once')
