#!/usr/bin/env python3
"""Remove the allocation guard or literal payload in an isolated compiler.

The preflight owns exactly-once matching; executable controls prove that each
edited path is reached by the public contract, not merely present in source.
"""
from pathlib import Path
import sys

MUTATIONS = {
    "allocation-guard": ((
        "selfhost/src/ir/interp.dawn",
        "  if n < 0 || n > left {",
        "  if n < 0 {",
    ),),
    "byte-emitter": ((
        "selfhost/src/jvm/emit.dawn",
        "        ldc_str(m, bytes.to_hex(bytes.slice(b, k * 16384, (k + 1) * 16384)))",
        '        ldc_str(m, bytes.to_hex(bytes.slice(b, 0, 0)))',
    ),),
}


def main():
    mode, root = sys.argv[1:]
    for rel, old, new in MUTATIONS[mode]:
        path = Path(root) / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mode}: {rel}: {count} matches, expected 1")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
