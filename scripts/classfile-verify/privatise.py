#!/usr/bin/env python3
"""Turn one public method of an emitted class private, in place.

    scripts/classfile-verify/privatise.py CLASSFILE METHOD_NAME

This is the K-A3 defect injected into the real corpus rather than into a toy
fixture, and the distinction is the whole reason the script exists.

selftest.sh's fixtures live in pkgA/pkgB, packages the toolchain jar does not
carry. That makes them blind to the bug this gate actually had: parent-first
delegation, under which every class of the selfhost corpus resolved out of the
jar and the directory under test was never read. The fixtures would have
stayed red through all of it, because their classes are only ever found in the
directory. A mutant that reds only on names the jar also holds -- dawn/rt/*,
std.*, emit, main -- is the one that can tell the two apart, so run.sh flips a
method of an emitted `dawn/rt/Strings` and requires the gate to fail.

Rewrites the method_info access flags after walking the constant pool, the
interface list and the field table, because those are what stand between the
header and the methods. Insists on exactly one public method of that name: a
mutation harness that silently mutates nothing is the failure mode this gate
exists to rule out.
"""

import struct
import sys
from pathlib import Path

ACC_PUBLIC = 0x0001
ACC_PRIVATE = 0x0002

# tag -> bytes to skip after it (Utf8, Long and Double are handled separately)
FIXED = {
    3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
    15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2,
}


def parse_pool(b):
    """Return (utf8 by index, offset just past the pool)."""
    count = struct.unpack_from(">H", b, 8)[0]
    utf8 = {}
    off = 10
    i = 1
    while i < count:
        tag = b[off]
        off += 1
        if tag == 1:
            n = struct.unpack_from(">H", b, off)[0]
            utf8[i] = b[off + 2:off + 2 + n].decode("utf-8", "replace")
            off += 2 + n
        elif tag in (5, 6):
            off += 8
            i += 1
        elif tag in FIXED:
            off += FIXED[tag]
        else:
            raise ValueError(f"unknown constant pool tag {tag} at index {i}")
        i += 1
    return utf8, off


def skip_members(b, off):
    """Skip a field_info or method_info table, attributes and all."""
    n = struct.unpack_from(">H", b, off)[0]
    off += 2
    for _ in range(n):
        off = skip_attrs(b, off + 6)
    return off


def skip_attrs(b, off):
    n = struct.unpack_from(">H", b, off)[0]
    off += 2
    for _ in range(n):
        off += 6 + struct.unpack_from(">I", b, off + 2)[0]
    return off


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path, want = Path(argv[1]), argv[2]
    b = bytearray(path.read_bytes())
    if b[:4] != b"\xca\xfe\xba\xbe":
        print(f"{path}: not a class file", file=sys.stderr)
        return 1
    utf8, off = parse_pool(b)
    off += 6                                                 # access, this, super
    off += 2 + 2 * struct.unpack_from(">H", b, off)[0]       # interfaces
    off = skip_members(b, off)                               # fields
    nmethods = struct.unpack_from(">H", b, off)[0]
    off += 2
    hits = 0
    for _ in range(nmethods):
        flags = struct.unpack_from(">H", b, off)[0]
        name = utf8[struct.unpack_from(">H", b, off + 2)[0]]
        if name == want and flags & ACC_PUBLIC:
            struct.pack_into(">H", b, off, (flags & ~ACC_PUBLIC) | ACC_PRIVATE)
            hits += 1
        off = skip_attrs(b, off + 6)
    if hits != 1:
        print(f"{path}: expected exactly one public method named {want}, found {hits}",
              file=sys.stderr)
        return 1
    path.write_bytes(bytes(b))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
