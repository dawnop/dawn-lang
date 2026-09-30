#!/usr/bin/env python3
"""Apply one of cold.py's driver mutations to a copy of the repository tree.

    scripts/incremental-semantics-contract/mutate.py <mutation> <tree-root>

cold.py used to spell these six driver/analyze.dawn anchors in its own main
and refuse a stale one only when it ran, which is one incremental-memo
shard; driver/analyze.dawn is rewritten by most incremental-engine changes,
so drift surfaced as a red shard long after the edit (#254, after #249 found the same gap in delete-contract). Declared
here, in the registry shape mutation-anchor-preflight.py discovers, they are
proven exactly-once before any build, and cold.py reads them from here.

Only cold.py's own mutants are here. The harnesses that import `edit` from
cold.py quote their own anchors, and their ledger lines say what holds them.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, with paths relative to the tree root.
"""

from pathlib import Path
import sys

ANALYZE = "selfhost/src/driver/analyze.dawn"

MUTATIONS = {
    # The step starts from an empty intern table instead of the one before it.
    "intern-table": ((ANALYZE, "    identities: before.identities,", "    identities: map.empty(),"),),
    # Impls are carried from the std baseline, not from the module before.
    "impl-carry": ((ANALYZE, "  var base_impls = before.impls\n", "  var base_impls = std.impls\n"),),
    # A module's diagnostics are prepended instead of appended.
    "diagnostic-order": ((ANALYZE, "    diags = diags ++ step.diags\n", "    diags = step.diags ++ diags\n"),),
    # The checker never runs.
    "skip-check": ((ANALYZE, "  if not parse_failed {\n", "  if false {\n"),),
    # Comptime evaluation never runs.
    "skip-comptime": ((ANALYZE, "    if len(cx.diags) == 0 {\n", "    if false {\n"),),
    # The std baseline's impls are not taken over.
    "std-baseline": ((ANALYZE, "      Some(before) -> { base_impls = before }", "      Some(before) -> ()"),),
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
