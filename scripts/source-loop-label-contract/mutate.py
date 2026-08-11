#!/usr/bin/env python3
"""Restore the broad match-unloop recognizer in a compiler tree copy."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation != "drop-terminal-loop-jump-guard":
        raise SystemExit(f"unknown mutation: {mutation}")
    path = root / "selfhost/src/c/rc.dawn"
    text = path.read_text()
    old = "        CSDiscard(x) -> not yields(x) && not jumps(x, lid, true, true)\n"
    new = "        CSDiscard(x) -> not yields(x)\n"
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"drop-terminal-loop-jump-guard: mutation anchor drifted ({count} matches)"
        )
    path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
