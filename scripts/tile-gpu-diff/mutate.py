#!/usr/bin/env python3
"""Rewrite exactly one anchor in a file, or fail.

    mutate.py <file> <label> <old> <new>

The anchor must match exactly once, so a refactor that moves it fails here
instead of silently leaving the mutant un-mutated (the rule every mutant in
scripts/ follows; scripts/narrow-contract is the precedent).
"""

import pathlib
import sys


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__, file=sys.stderr)
        return 2
    path, label, old, new = sys.argv[1:]
    p = pathlib.Path(path)
    text = p.read_text()
    if text.count(old) != 1:
        print(f"mutant {label}: anchor is not unique in {p.name} ({text.count(old)} matches)", file=sys.stderr)
        return 1
    p.write_text(text.replace(old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
