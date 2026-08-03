#!/usr/bin/env python3
"""Turn one reachable instruction of a class file into a verifier error.

    scripts/classfile-verify/mutate.py CLASSFILE

Rewrites the single `iadd; ireturn` (0x60 0xac) pair in the file to
`athrow; ireturn`: athrow wants a reference and the operand stack holds two
ints there, so the bytecode verifier rejects the method. That is the mutation
Verify.java's header describes -- one reachable instruction replaced by
athrow -- kept runnable instead of remembered, because the delegation bug it
found in the first place was invisible to reading.

A byte search rather than a Code-attribute walk, and it insists on exactly one
match: the input is scripts/classfile-verify/fixtures/legal/pkgB/Caller.java,
compiled two lines earlier, whose only addition is the one this targets. If
the fixture ever stops producing that pair the script fails loudly rather than
quietly mutating nothing -- a mutation harness that silently no-ops is the
failure mode this whole gate exists to rule out.
"""

import sys
from pathlib import Path

IADD_IRETURN = b"\x60\xac"
ATHROW_IRETURN = b"\xbf\xac"


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    p = Path(argv[1])
    b = p.read_bytes()
    if b[:4] != b"\xca\xfe\xba\xbe":
        print(f"{p}: not a class file", file=sys.stderr)
        return 1
    n = b.count(IADD_IRETURN)
    if n != 1:
        print(f"{p}: expected exactly one iadd/ireturn pair, found {n}", file=sys.stderr)
        return 1
    p.write_bytes(b.replace(IADD_IRETURN, ATHROW_IRETURN))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
