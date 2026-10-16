#!/usr/bin/env python3
"""Apply one loader-listdir mutant's edit to a copy of the repository tree.

    scripts/loader-listdir-contract/mutate.py <mutation> <tree-root>

The mutant puts back the silence #759 took out of the loader's walk, so the
contract can show that its assertions are what notice. Declared in the
registry shape mutation-anchor-preflight.py discovers, so every anchor is
proved to match exactly once before any build. Paths are relative to the tree
root the caller passes; run.sh lays each private compiler out as `<root>/selfhost`.
"""

from pathlib import Path
import sys

ANALYZE = "selfhost/src/driver/analyze.dawn"

MUTATIONS = {
    # The walk answers an unlistable directory with nothing, as `return []` did.
    "walk-silent": ((
        ANALYZE,
        "    Err(e) -> { unlisted = [(dir, e.message)] }",
        "    Err(_) -> { unlisted = [] }",
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
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique ({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
