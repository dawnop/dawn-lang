#!/usr/bin/env python3
"""Apply one compiling source mutation to dependency re-exec heap handling."""

from pathlib import Path
import sys


MUTATIONS = {
    # Drop the ceiling from the argv every child JVM is spawned with, leaving
    # the child to JVM ergonomics -- a heap sized from the host's RAM rather
    # than from what this run was given. That is the defect
    # heap.inherits_parent_max exists to catch.
    "drop-inherited-max-heap": (
        '"-Xss512m", own_xmx(), ',
        '"-Xss512m", ',
    ),
}


def main() -> None:
    if sys.argv[1:] == ["--list"]:
        for name in MUTATIONS:
            print(name)
        return
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        names = " | ".join(MUTATIONS)
        raise SystemExit(f"usage: mutate.py <{names}> <selfhost/src/main.dawn>")
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
