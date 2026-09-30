#!/usr/bin/env python3
"""Apply one of cold.py's driver mutations to a copy of the repository tree.

    scripts/incremental-semantics-contract/mutate.py <mutation> <tree-root>

cold.py used to spell these six driver/analyze.dawn anchors in its own main
and refuse a stale one only when it ran, which is one incremental-memo
shard; driver/analyze.dawn is rewritten by most incremental-engine changes,
so drift surfaced as a red shard long after the edit (#254, after #249 found the same gap in delete-contract). Declared
here, in the registry shape mutation-anchor-preflight.py discovers, they are
proven exactly-once before any build, and cold.py reads them from here.

Every harness of this directory reads the one registry, so each key carries
its owner as a prefix (`cold/intern-table`): a harness takes its own group
with cold.owned, which strips the prefix, and never iterates the others'.
The preflight runs every key, whatever its owner. One file rather than one per
harness because mutation-anchor-preflight.py keys its adapters by directory.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, with paths relative to the tree root.
"""

from pathlib import Path
import sys

ANALYZE = "selfhost/src/driver/analyze.dawn"
SERVER = "selfhost/src/lsp/server.dawn"

# Anchors two groups quote, spelled once.
WARM_ANALYZE = "incremental.analyze(ws0.cache, loaded)"
COLD_ANALYZE = "incremental.analyze(incremental.evict(ws0.cache), loaded)"
LOADED = "      let loaded = reusing.loaded"
PREFIX_ANALYZE = "      let update = " + WARM_ANALYZE

MUTATIONS = {
    # The step starts from an empty intern table instead of the one before it.
    "cold/intern-table": ((ANALYZE, "    identities: before.identities,", "    identities: map.empty(),"),),
    # Impls are carried from the std baseline, not from the module before.
    "cold/impl-carry": ((ANALYZE, "  var base_impls = before.impls\n", "  var base_impls = std.impls\n"),),
    # A module's diagnostics are prepended instead of appended.
    "cold/diagnostic-order": ((ANALYZE, "    diags = diags ++ step.diags\n", "    diags = step.diags ++ diags\n"),),
    # The checker never runs.
    "cold/skip-check": ((ANALYZE, "  if not parse_failed {\n", "  if false {\n"),),
    # Comptime evaluation never runs.
    "cold/skip-comptime": ((ANALYZE, "    if len(cx.diags) == 0 {\n", "    if false {\n"),),
    # The std baseline's impls are not taken over.
    "cold/std-baseline": ((ANALYZE, "      Some(before) -> { base_impls = before }", "      Some(before) -> ()"),),

    # lsp-observe.py, a tool run by hand: not mutants but the probes of a
    # private LSP. It applies inputs always, prefix-stats only when the
    # source has an incremental workspace (it may point at a frozen older
    # tree), and cold on --cold.
    # Each module's path, in the order the load hands them to the analysis.
    "lsp-observe/inputs": ((SERVER, LOADED, LOADED + '''
      var trace_paths: List[String] = []
      for input in loaded.modules { trace_paths = trace_paths ++ [input.path] }
      io.eprintln("LSP_INPUTS\\t" ++ join(trace_paths, "\\t"))'''),),
    # How many modules the session reused, checked and retained.
    "lsp-observe/prefix-stats": ((SERVER, PREFIX_ANALYZE, PREFIX_ANALYZE + '''
      io.eprintln("LSP_PREFIX_STATS\\t" ++ to_string(update.stats.reused_modules) ++ "\\t" ++
        to_string(update.stats.checked_modules) ++ "\\t" ++ to_string(update.stats.retained_modules))'''),),
    # Every analysis starts from an evicted session.
    "lsp-observe/cold": ((SERVER, WARM_ANALYZE, COLD_ANALYZE),),
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
