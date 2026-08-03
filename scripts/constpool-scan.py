#!/usr/bin/env python3
"""Constant-pool gate (K-A5, docs/jvm-base-plan.md §2.1.1).

No emitted class may carry a MethodHandle, MethodType, Dynamic or
InvokeDynamic constant -- tags 15, 16, 17, 18.

The reason is a JVM parse-time rule, not a style preference: the class file
version gate on these tags is checked while the constant pool is read, before
anything asks whether an entry is reachable. A class that no longer executes
an `invokedynamic` but still names one in its pool is a hard ClassFormatError
under a version that predates them, so "drop the instruction now, clean the
pool later" is not a state the repo can pass through. This gate is what keeps
the pool clean once the closures stop going through LambdaMetafactory.

Reads the constant pool with the struct module rather than through ASM: a
scanner that used the emitter's own library to check the emitter's own output
would go blind exactly where the library is wrong.

    scripts/constpool-scan.py DIR [DIR ...]
"""

import struct
import sys
from pathlib import Path

BANNED = {
    15: "MethodHandle",
    16: "MethodType",
    17: "Dynamic",
    18: "InvokeDynamic",
}

# tag -> bytes to skip after it; None means a variable-width or wide entry
FIXED = {
    3: 4, 4: 4, 7: 2, 8: 2, 9: 4, 10: 4, 11: 4, 12: 4,
    15: 3, 16: 2, 17: 4, 18: 4, 19: 2, 20: 2,
}


def scan(path):
    """Return the sorted set of banned tags this class file names."""
    b = path.read_bytes()
    if len(b) < 10 or b[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a class file")
    count = struct.unpack_from(">H", b, 8)[0]
    off = 10
    found = set()
    i = 1
    while i < count:
        tag = b[off]
        off += 1
        if tag == 1:                       # Utf8
            off += 2 + struct.unpack_from(">H", b, off)[0]
        elif tag in (5, 6):                # Long, Double take two slots
            off += 8
            i += 1
        elif tag in FIXED:
            if tag in BANNED:
                found.add(tag)
            off += FIXED[tag]
        else:
            raise ValueError(f"unknown constant tag {tag} at pool index {i}")
        i += 1
    return found


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    n = 0
    bad = []
    for d in argv[1:]:
        for f in sorted(Path(d).rglob("*.class")):
            n += 1
            hits = scan(f)
            if hits:
                bad.append((f, hits))
    for f, hits in bad:
        names = ", ".join(f"{t} ({BANNED[t]})" for t in sorted(hits))
        print(f"CONSTPOOL FAIL {f}: tag {names}", file=sys.stderr)
    if bad:
        print(
            f"FAIL: {len(bad)} of {n} emitted classes name a method-handle "
            f"constant (see docs/jvm-base-plan.md §2.1.1)",
            file=sys.stderr,
        )
        return 1
    print(f"OK: {n} emitted classes, no constant-pool tag 15/16/17/18")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
