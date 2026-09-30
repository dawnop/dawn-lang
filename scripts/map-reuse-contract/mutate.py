#!/usr/bin/env python3
"""Apply one reuse mutation to a copy of the repository tree.

    scripts/map-reuse-contract/mutate.py <mutation> <tree-root>

The two source anchors used to live in two Python heredocs inside run.sh,
each refusing a non-unique match. That made them self-once: correct, but
checked only when this contract ran, one of them behind a private compiler
build. They quote c/rc.dawn and std/hamt.dawn. Declared here, in the registry
shape mutation-anchor-preflight.py already discovers, the same anchors have
two consumers: run.sh applies one mutation per private tree, and the preflight
proves every one of them exactly-once before any build (#254). The third
mutant, borrow-hamt-assoc-again, is a DAWN_RC_MODE_FLIPS spec, not a source
edit, and stays in run.sh.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes: run.sh
lays the compiler mutant out as `<root>/selfhost` and the std mutant as
`<root>/std`, so the preflight can hand this script the checkout.
"""

from pathlib import Path
import sys

MUTATIONS = {
    # The pre-#30 RC walk: the record update's spread source stays alive
    # across map.insert.
    "keep-record-spread-source": ((
        "selfhost/src/c/rc.dawn",
        "let (st0, stmts0, tail0) = schedule_record_update(st, stmts, tail)",
        "let (st0, stmts0, tail0) = (st, stmts, tail)",
    ),),
    # The pre-#31 node_put: get the descent child instead of stealing it.
    "get-hamt-child-again": ((
        "std/hamt.dawn",
        """        let child = array_steal(kids, pos)
        let sub = node_put(child, shift + BITS, h, k, v, seq)""",
        """        let sub = node_put(array_get(kids, pos), shift + BITS, h, k, v, seq)""",
    ),),
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
