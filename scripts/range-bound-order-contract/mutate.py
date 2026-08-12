#!/usr/bin/env python3
"""Restore the upper-first range CSLet list in a compiler tree copy."""

from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation != "restore-upper-first":
        raise SystemExit(f"unknown mutation: {mutation}")
    path = root / "selfhost/src/ir/lower.dawn"
    text = path.read_text(encoding="utf-8")
    old = (
        "            CSLet(isym, item_ty, lo_v),\n"
        "            CSLet(bsym, TyInt, hi_v),\n"
    )
    new = (
        "            CSLet(bsym, TyInt, hi_v),\n"
        "            CSLet(isym, item_ty, lo_v),\n"
    )
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"restore-upper-first: mutation anchor drifted ({count} matches)")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
