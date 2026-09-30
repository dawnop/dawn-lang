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
CHECKER = "selfhost/src/check/checker.dawn"
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

    # lsp-configured.py, a benchmark builder: the policy entry takes the mode
    # and cache limit it is given, so its `new` here is the default form
    # (Legacy, 128) and the builder formats its own; the observation point
    # is applied as written.
    "lsp-configured/policy": ((SERVER, "run_lsp_configured(std_flag, host, legacy_analysis_config())",
                               "run_lsp_configured(std_flag, host, "
                               "LspAnalysisConfig { mode: Legacy, max_modules: 128 })"),),
    "lsp-configured/observe": ((SERVER, "      let prog = update.program\n      Workspace {",
                                '      benchmark_analysis_stats("project", Some(update.stats))\n'
                                "      let prog = update.program\n      Workspace {"),),

    # lsp-module-memo.py: the owner of the analysis is what the server
    # commits and discards, and a load reuses only unchanged parses.
    "lsp-module-memo/drop-session": ((SERVER, "        cache: update.session,", "        cache: ws0.cache,"),),
    "lsp-module-memo/bypass-cache": ((SERVER, WARM_ANALYZE, COLD_ANALYZE),),
    "lsp-module-memo/keep-conflict-cache": ((SERVER, "        cache: incremental.evict(ws0.cache),",
                                             "        cache: ws0.cache,"),),
    # A load that is handed nothing to reuse still answers correctly, so
    # only the counts can see it; a load that reuses a parse whose text
    # changed answers with the old syntax.
    "lsp-module-memo/drop-parses": ((SERVER, "        parses: retained_parses(st, reusing.parses),",
                                     "        parses: ws0.parses,"),),
    "lsp-module-memo/stale-parse": ((ANALYZE, "    Some(p) -> if p.text == text { (p, true) }",
                                     "    Some(p) -> if true { (p, true) }"),),
    # The line starts ride on the parse: a file parsed again has to get
    # its own, not the ones the previous parse of the path held.
    "lsp-module-memo/stale-line-starts": ((ANALYZE, "else { (fresh_parse(text), false) }",
                                           "else { (Parsed { ..fresh_parse(text), line_starts: p.line_starts }, false) }"),),
    # A body is checked with offsets relative to its own declaration, and
    # `tast_positions.symbols` is what adds the declaration's start back
    # on the way out. Its owner here is the LSP reader of those positions;
    # `a typed span cuts the source the declaration actually holds` in
    # check/checker is the same resolver's checker-side reader. Until
    # 2026-09-27 the owner was a replayed body's definition, which went
    # with the replay engine.
    "lsp-module-memo/resolver-drops-the-declaration": ((
        CHECKER,
        "syms: tast_positions.symbols(entered.resolver, after.syms, "
        "mint_cursor(entered.cx), mint_cursor(after))",
        "syms: tast_positions.symbols(tast_positions.unowned(after.src_path, after.line_starts), "
        "after.syms, mint_cursor(entered.cx), mint_cursor(after))"),),
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
