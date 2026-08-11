#!/usr/bin/env python3
"""Apply one compiling source mutation to the compiler-weight sampler."""

from pathlib import Path
import sys


MUTATIONS = {
    "descendants-one-hop": (
        "DESCENDANT_DEPTH_LIMIT: int | None = None",
        "DESCENDANT_DEPTH_LIMIT: int | None = 1",
    ),
    "heap-mismatch-passes": (
        "def heap_matches_expected(actual: int, expected: int) -> bool:\n"
        "    return actual == expected",
        "def heap_matches_expected(actual: int, expected: int) -> bool:\n"
        "    return True",
    ),
}


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        names = " | ".join(MUTATIONS)
        raise SystemExit(f"usage: mutate.py <{names}> <selfhost-bench.py>")
    mutation, raw_path = sys.argv[1:]
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    old, new = MUTATIONS[mutation]
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
