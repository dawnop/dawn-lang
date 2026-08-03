#!/usr/bin/env python3
"""Which ASM adapter the emitted compiler actually calls (K-A7 phase 2).

    scripts/adapter-callsites.py DIR [DIR ...]

Switching the 114 call sites from `dawn.tool.AdtClassWriter` to `dawn.rt.Asm`
is invisible to every other gate. Both classes carry the same five statics and
produce byte-identical class files (that is what scripts/asm-adapter-contract
proves), and while `dawn/tool` is still on the class path a compiler that never
moved a single call site builds, self-hosts and passes the whole suite. "It all
went green" therefore says nothing about whether the migration happened.

This reads the constant pool of the emitted classes and answers it directly.
Two assertions, because either one alone is satisfiable by something wrong:

  * no emitted class may name `dawn/tool/...`  -- passes trivially on an empty
    directory, or on a compiler that stopped writing bytecode altogether;
  * at least one emitted class must name `dawn/rt/Asm` -- passes on a compiler
    that calls both.

Together they say: the adapter surface is reached, and it is reached at the
in-tree class only.

The pool is parsed with `struct`, not with ASM: a scanner that used the
emitter's own library to check the emitter's own output would go blind exactly
where the library is wrong (same reasoning as constpool-scan.py).
"""

import struct
import sys
from pathlib import Path

OLD = "dawn/tool/"
NEW = "dawn/rt/Asm"

# tag -> bytes to skip after it (Utf8, Long and Double are handled separately)
FIXED = {
    3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
    15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2,
}


def class_names(path):
    """Every CONSTANT_Class name this class file's pool holds."""
    b = path.read_bytes()
    if len(b) < 10 or b[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    count = struct.unpack_from(">H", b, 8)[0]
    utf8 = {}
    class_refs = []
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
        elif tag == 7:
            class_refs.append(struct.unpack_from(">H", b, off)[0])
            off += 2
        elif tag in FIXED:
            off += FIXED[tag]
        else:
            raise ValueError(f"unknown constant pool tag {tag} at {off - 1}")
        i += 1
    return [utf8.get(ix, "") for ix in class_refs]


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    old_hits = []
    new_hits = []
    n = 0
    for d in argv[1:]:
        for p in sorted(Path(d).rglob("*.class")):
            n += 1
            for nm in class_names(p):
                if nm.startswith(OLD):
                    old_hits.append((p, nm))
                elif nm == NEW:
                    new_hits.append(p)
    print(f"scanned {n} class files in {len(argv) - 1} director"
          f"{'y' if len(argv) == 2 else 'ies'}")
    print(f"  name {NEW}:  {len(set(new_hits))} classes")
    print(f"  name {OLD}*: {len(old_hits)} references")
    bad = 0
    if old_hits:
        bad = 1
        print(f"FAIL: {len(old_hits)} reference(s) to the vendored adapter remain")
        for p, nm in old_hits[:20]:
            print(f"      {p}: {nm}")
    if not new_hits:
        bad = 1
        print(f"FAIL: nothing names {NEW} -- the adapters are not reached at all")
    if bad:
        return 1
    print(f"OK: the adapter surface is reached, and only at {NEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
