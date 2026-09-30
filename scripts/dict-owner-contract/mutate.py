#!/usr/bin/env python3
"""Apply one dict-owner shape mutation to a copy of the repository tree.

    scripts/dict-owner-contract/mutate.py <mutation> <tree-root>

The anchors used to be built inline in shapes.py, which refused a non-unique
match only when it ran: after copying the compiler and before its first
`dawn test`, so a rewrite of ir/lower.dawn went unnoticed until contracts-1
next reached this contract (#254, after #249 found the same gap in
delete-contract). Declared here, in the registry shape
mutation-anchor-preflight.py discovers, they have two readers: shapes.py
takes them from MUTATIONS and applies them in memory, as it did before, and
the preflight proves every one exactly-once before any build.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, with paths relative to the tree root.
"""

from pathlib import Path
import sys

LOWER = "selfhost/src/ir/lower.dawn"


def drop_shape_suffix(kind):
    # The bridge and prim dictionaries mangle their name the same way; the
    # mutant keeps the name and drops the shape suffix on the next line.
    old = ('let name = "' + kind + '$" ++ to_string(tid) ++ "$" ++ ty_key_inst(subject) ++ "$" ++ method ++\n'
           '    dict_shape_suffix(if param { len(goals) } else { 0 })')
    return (LOWER, old, old.split(' ++\n')[0])


MUTATIONS = {
    # The dictionary key forgets how many arguments the constructor takes.
    "dictionary-shape": ((
        LOWER,
        "let key = dict_key(tid, subject) ++ dict_shape_suffix(nargs)",
        "let key = dict_key(tid, subject)",
    ),),
    # The constructor records no arguments at all.
    "constructor-arity": ((LOWER, "nargs: nargs,", "nargs: 0,"),),
    "bridge-shape": (drop_shape_suffix("bridge"),),
    "prim-shape": (drop_shape_suffix("prim"),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
