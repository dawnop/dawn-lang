#!/usr/bin/env python3
"""Apply one compiling source mutation to dependency re-exec heap handling."""

from pathlib import Path
import sys


MUTATIONS = {
    "drop-inherited-max-heap": (
        '    "-Xmx" ++ to_string(max_heap),\n',
        "",
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
