#!/usr/bin/env python3
"""Apply one rounding-rule mutation to a copy of the repository tree.

    scripts/narrow-contract/mutate.py <mutation> <tree-root>

The anchors used to be arguments to run.sh's `patch_std` shell helper, which
refused a non-unique match. That made them self-once: correct, but checked
only when this contract ran, after a JVM and a native build of the corpus per
mutant. Declared here, in the registry shape mutation-anchor-preflight.py
already discovers, the same anchors have two consumers: run.sh applies one
mutation per private std tree, and the preflight proves every one of them
exactly-once before any build (#254).

`no-subnormal-clamp`'s anchor carries the two comment lines above the
statement it rewrites on purpose: the DIRECTED rounding function next to
`round_binary` decomposes the same way, and the statement alone matches twice.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes: run.sh
lays each mutant's std out as `<root>/std`, so the preflight can hand this
script the checkout.
"""

from pathlib import Path
import sys

NARROW = "std/narrow.dawn"

MUTATIONS = {
    # Ties away from zero instead of to even.
    "ties-away": ((
        NARROW,
        "let n = if r > 0.5 { fl + 1 } else if r < 0.5 { fl } else if fl % 2 == 0 { fl } else { fl + 1 }",
        "let n = if r > 0.5 { fl + 1 } else if r < 0.5 { fl } else { fl + 1 }",
    ),),
    # Below emin the quantum keeps shrinking with the exponent.
    "no-subnormal-clamp": ((
        NARROW,
        """      # the quantum: one unit in the last place at this exponent, clamped
      # to the subnormal grid below emin
      let qe = (if e < emin { emin } else { e }) - p + 1""",
        """      # the quantum: one unit in the last place at this exponent, clamped
      # to the subnormal grid below emin
      let qe = e - p + 1""",
    ),),
    # bf16's overflow threshold one binade too high.
    "emax-off-by-one": ((
        NARROW,
        "pub fn round_bf16(x: Float) -> Float = round_binary(x, 8, -126, 127)",
        "pub fn round_bf16(x: Float) -> Float = round_binary(x, 8, -126, 128)",
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
