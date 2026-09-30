#!/usr/bin/env python3
"""Apply one gzip-framing mutation to a copy of the repository tree.

    scripts/inflate-contract/mutate.py <mutation> <tree-root>

The anchors used to be arguments to run.sh's `mutate` shell helper, which
refused a non-unique match. That made them self-once: correct, but checked
only when this contract ran, and every mutant is a full `dawn run` of the
member-framing corpus. Declared here, in the registry shape
mutation-anchor-preflight.py already discovers, the same anchors have two
consumers: run.sh applies one mutation per mutant package, and the preflight
proves every one of them exactly-once before any build (#254).

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes: run.sh
lays each mutant package out as `<root>/packages/inflate`, so the preflight can
hand this script the checkout.
"""

from pathlib import Path
import sys

GZIP = "packages/inflate/src/gzip.dawn"

MUTATIONS = {
    # Only the first member is read.
    "member-loop": ((GZIP, "while cursor < n {", "if cursor < n {"),),
    # The trailer is taken from the end of the input, not of this member.
    "final-trailer": ((GZIP, "let trailer = deflate_end", "let trailer = bytes.len(src) - 8"),),
    # The output cap is not shared across members.
    "aggregate-cap": ((GZIP, "Some(lim - bytes.size(out))", "Some(lim)"),),
    # Reserved header flags are accepted.
    "reserved-flags": ((GZIP, "if flags & RESERVED != 0 {", "if false {"),),
    # A bad header CRC is accepted.
    "fhcrc": ((GZIP, "if got != want {", "if false {"),),
    # The header CRC covers the input from its start, not from this member's.
    "fhcrc-origin": ((GZIP, "bytes.slice(src, start, i)", "bytes.slice(src, 0, i)"),),
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
