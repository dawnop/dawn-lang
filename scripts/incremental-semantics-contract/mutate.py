#!/usr/bin/env python3
"""Apply one of this directory's source mutations to a copy of the repository tree.

    scripts/incremental-semantics-contract/mutate.py <mutation> <tree-root>

cold.py, identity.py, module-memo.py, lsp-module-memo.py and body-executor.py
used to spell their mutant anchors in their own mains, and lsp-observe.py and
lsp-configured.py their probe anchors, each refusing a stale one only when it
ran: an incremental-memo shard, or a hand-run build. The files they edit are
rewritten by most incremental-engine changes, so drift surfaced as a red
shard long after the edit (#254 for cold.py, after #249 found the same gap in
delete-contract; #277 for the rest). Declared here, in the registry shape
mutation-anchor-preflight.py discovers, they are proven exactly-once before
any build, and each harness reads them from here.

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
ENGINE = "selfhost/src/driver/incremental.dawn"
IDENTITY = "selfhost/src/check/identity.dawn"
LOWER = "selfhost/src/ir/lower.dawn"
CX = "selfhost/src/check/cx.dawn"
STDLIB = "selfhost/src/driver/stdlib.dawn"
PASSES = "selfhost/src/check/passes.dawn"
SERVER = "selfhost/src/lsp/server.dawn"

# Anchors two groups quote, spelled once.
WARM_ANALYZE = "incremental.analyze(ws0.cache, loaded)"
COLD_ANALYZE = "incremental.analyze(incremental.evict(ws0.cache), loaded)"
LOADED = "      let loaded = reusing.loaded"
PREFIX_ANALYZE = "      let update = " + WARM_ANALYZE
SAME_INPUT = "-> Bool = LoadedModule { ..a, line_starts: b.line_starts } == b\n"
SAME_SURFACE = "-> Bool =\n  a == b &&\n"
CUTOFF = "              Some(before) -> if same_surface(own, before) {"
PROJECTED = "return ProjectedEffect(i, parts[1])"
DENSIFY = ("  dense_expr(dense_params(dense_params(dense_params(dense_params(d, f.captures),\n"
           "    f.params), f.dicts), f.evs), f.body)")
MOVED = "      Some(next) -> { moved_syms = map.insert(moved_syms, next, s) }"
INTERN = "(Cx { ..cx, identities: map.insert(cx.identities, id, decl) }, id)"
MINT = 'interned(cx, minted(cx.owner_class.unwrap_or(""), kind, name), lo, hi)'

# body-executor.py: each role's executor call, and a body that bypasses the
# executor, returning the state it was handed.
BODY_CALLS = {
    "inferred": ("executor.inferred_body(state, owner.cx, d, sigs[idx])",
                 "{ let (next, _, tree) = check_fn_inferred(owner.cx, d, sigs[idx])\n (state, next, tree) }"),
    "constant": ("executor.constant(state, owner.cx, d, declared, visible)",
                 "{ let (next, tree) = check_const_init(owner.cx, d, declared, visible)\n (state, next, tree) }"),
    "function": ("executor.function(state, owner.cx, d, sigs[i])",
                 "{ let (next, tree) = check_fn(owner.cx, d, sigs[i])\n (state, next, tree) }"),
    "method": ("executor.method(state, owner.cx, imd.trait_name, imd.subject, strip_param_defaults(me), ms)",
               "{ let (next, tree) = check_fn(owner.cx, strip_param_defaults(me), ms)\n (state, next, tree) }"),
    "default": ("executor.default_body(state, owner.cx, t, me, s2, b)",
                "{ let (next, tree) = check_trait_default(owner.cx, me, s2, b)\n (state, next, tree) }"),
    "test": ("executor.test_body(state, owner.cx, t.name, t.body)",
             "{ let (next, tree) = check_test(owner.cx, t.name, t.body)\n (state, next, tree) }"),
}
# The inferred role runs inside attempt_inferred_group, one group at a
# time, where the module's initial state and header context are not in
# scope and the group's entry state equals the current one for every
# group of one. So its reset and its stale context are applied where the
# scheduler hands a group its state and context: every group then starts
# from the module's initial state, or from the header context rather than
# from the context the passes before it left.
GROUP_ENTRY = "attempt_inferred_group(state, cx1, inferred, settled,"


def bypass(role):
    call, body = BODY_CALLS[role]
    return ((CHECKER, call, body),)


def reset_state(role):
    anchor = GROUP_ENTRY if role == "inferred" else BODY_CALLS[role][0]
    return ((CHECKER, anchor, anchor.replace("(state,", "(initial,")),)


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
        "syms: tast_positions.symbols(tast_positions.unowned(after.src_path, after.line_starts, after.source), "
        "after.syms, mint_cursor(entered.cx), mint_cursor(after))"),),

    # body-executor.py: the scheduler consumes every role's executor result.
    # Each role is bypassed, and each role starts from the module's initial
    # state instead of the current one; the keys are spelled out because the
    # preflight reads them as literals.
    "body-executor/bypass-inferred": bypass("inferred"),
    "body-executor/reset-state-inferred": reset_state("inferred"),
    "body-executor/bypass-constant": bypass("constant"),
    "body-executor/reset-state-constant": reset_state("constant"),
    "body-executor/bypass-function": bypass("function"),
    "body-executor/reset-state-function": reset_state("function"),
    "body-executor/bypass-method": bypass("method"),
    "body-executor/reset-state-method": reset_state("method"),
    "body-executor/bypass-default": bypass("default"),
    "body-executor/reset-state-default": reset_state("default"),
    "body-executor/bypass-test": bypass("test"),
    "body-executor/reset-state-test": reset_state("test"),
    "body-executor/stale-inferred-context": ((CHECKER, GROUP_ENTRY, GROUP_ENTRY.replace("cx1,", "headers.cx,")),),

    # module-memo.py: each weakens one part of the session's reuse rule
    # (docs/lsp-module-memo-design.md). module-memo.py deals them to its
    # shards by index, so their order here is its shard assignment.
    "module-memo/always-cold": ((ENGINE,
        "  if not (same_input(raw, e.raw) && identity == e.std_identity) { return None }",
        "  if true || not (same_input(raw, e.raw) && identity == e.std_identity) { return None }"),),
    # The input half of the rule.
    "module-memo/text-only": ((ENGINE, SAME_INPUT, "-> Bool = a.text == b.text\n"),),
    "module-memo/ignore-input": ((ENGINE, SAME_INPUT, "-> Bool = true\n"),),
    "module-memo/ignore-std-identity": ((ENGINE, "same_input(raw, e.raw) && identity == e.std_identity)",
                                         "same_input(raw, e.raw) && true)"),),
    # What the step read of the carry: the surfaces its `use` lines name,
    # including what those surfaces grafted from their own imports, the
    # program-wide impl table, and the intern table for collisions.
    "module-memo/ignore-reads": ((ENGINE, "  if not reads_hold(e, carry.exports, seen, fresh) { return None }\n", ""),),
    "module-memo/reexport-blind": ((ENGINE, SAME_SURFACE,
        "-> Bool =\n  ModExports { ..a, adt_infos: b.adt_infos, trait_infos: b.trait_infos, "
        "effect_infos: b.effect_infos } == b &&\n"),),
    "module-memo/ignore-impls": ((ENGINE,
        "  if not (impls_is == Some(e.pred) || same_rows(carry.impls, e.impls_in)) { return None }\n", ""),),
    "module-memo/drop-identities": ((ENGINE, "  Some(Kept { identities: ids, minted: Some(rows) })",
                                     "  Some(Kept { identities: carry.identities, minted: Some(rows) })"),),
    "module-memo/skip-collision": ((ENGINE, "      Some(other) -> if other != v { return None }",
                                    "      Some(other) -> ()"),),
    "module-memo/keep-diagnosed": ((ENGINE, "  if len(e.step.diags) > 0 { return None }\n", ""),),
    # The early cutoff: a re-checked module whose surface comes out as it was.
    "module-memo/skip-cutoff": ((ENGINE, CUTOFF,
                                 "              Some(before) -> if false && same_surface(own, before) {"),),
    "module-memo/false-cutoff": ((ENGINE, CUTOFF, "              Some(before) -> if true {"),),
    "module-memo/unordered-surface": ((ENGINE, SAME_SURFACE, "-> Bool =\n  a == b ||\n"),),
    # The position view around a reused step.
    "module-memo/stale-spans": ((ENGINE,
        "decl_spans: map.insert(carry.decl_spans, step.checked.mod_path, own_spans)",
        "decl_spans: map.insert(step.after.decl_spans, step.checked.mod_path, own_spans)"),),
    # The export surface the carry comparison reads.
    "module-memo/alias-positions": ((CHECKER, "  AliasE { ..al, target: no_target, nlo: 0, nhi: 0 }\n",
        "  if true { al } else { AliasE { ..al, target: no_target, nlo: 0, nhi: 0 } }\n"),),
    "module-memo/impl-positions": ((CHECKER,
        "  if im.lo == 0 && im.hi == 0 { im } else { ImplI { ..im, lo: 0, hi: 0 } }\n",
        "  if true { im } else { ImplI { ..im, lo: 0, hi: 0 } }\n"),),
    # What the owner remembers.
    "module-memo/ignore-eviction": ((ENGINE,
        "  let none: Map[String, Entry] = map.empty()\n  State { ..session, memo: none }\n}",
        "  session\n}"),),
    "module-memo/ignore-module-budget": ((ENGINE, "    if retained < session.max_modules {", "    if true {"),),
    "module-memo/allow-negative-budget": ((ENGINE,
        '  if max_modules < 0 { panic("negative analysis cache limit") }', "  ()"),),

    # identity.py: production identity admission, check/identity.dawn.
    "identity/duplicate-parent": ((IDENTITY, "if unique { out = out ++ [e] }", "out = out ++ [e]"),),
    # The derived id: what it is a function of, and what it must not be a
    # function of. The spelling is the whole input, so dropping the kind
    # letter or the owner from it merges two declarations, and skipping
    # the finalizer leaves the low bits -- the only ones a 47-bit band
    # keeps, and the only ones `Map[Int, _]` buckets on -- correlated
    # across two names that differ in one character.
    "identity/spelling-drops-kind": ((IDENTITY, 'Named(kind, name) -> "N" ++ kind_text(kind) ++ atom(name)',
                                      'Named(kind, name) -> "N" ++ atom(name)'),),
    "identity/spelling-drops-owner": ((IDENTITY,
        "pub fn minted_text(m: Minted) -> String = atom(m.owner) ++ path_text",
        "pub fn minted_text(m: Minted) -> String = atom(\"\") ++ path_text"),),
    "identity/derive-skips-finalizer": ((IDENTITY,
        "derived_floor() + (fmix64(fnv1a64(spelling)) & derived_width())",
        "derived_floor() + (fnv1a64(spelling) & derived_width())"),),
    "identity/derive-leaves-the-band": ((IDENTITY, "pub fn derived_floor() -> Int = 4294967296",
                                         "pub fn derived_floor() -> Int = 7"),),
    "identity/derive-overflows-the-label-key": ((IDENTITY, "pub fn derived_width() -> Int = 140737488355327",
                                                 "pub fn derived_width() -> Int = 9223372036854775807"),),
    # The packed key: what it is made of, what it refuses, and the two
    # things it has to stay clear of. A slot outside the span folded back
    # into the key is two bindings of one declaration sharing a row; a
    # pool shared by the whole program is two modules sharing one; and a
    # temporary floor inside the packed band is lowering numbering over a
    # binding the checker minted.
    "identity/pack-truncates-the-slot": ((IDENTITY, "if slot < 0 || slot >= slot_span() { return None }",
                                          "if slot < 0 { return None }"),),
    "identity/pack-drops-the-declaration": ((IDENTITY, "Some(declaration * slot_span() + slot)", "Some(slot)"),),
    "identity/pool-is-one-for-the-program": ((IDENTITY,
        'pub fn free_pool(owner: String) -> Int = derive_text(atom(owner) ++ "P")',
        'pub fn free_pool(owner: String) -> Int = derive_text("P")'),),
    "identity/temporary-floor-inside-the-band": ((IDENTITY,
        "pub fn temporary_floor() -> Int = (derived_floor() + derived_width() + 1) * slot_span()",
        "pub fn temporary_floor() -> Int = derived_floor()"),),
    "identity/parent-not-checked": ((IDENTITY, "var depth = 1", "var depth = len(e.entry.key.path)"),),
    "identity/binder-spelling": ((IDENTITY, "return BoundType(i)", "return NamedType(name, [], [])"),),
    "identity/default-ambiguity": ((IDENTITY, "if same == 1 {", "if same >= 1 {"),),
    "identity/effect-binder-spelling": ((IDENTITY, PROJECTED, "return NamedEffect(name)"),),
    "identity/effect-member-erased": ((IDENTITY, PROJECTED, 'return ProjectedEffect(i, "")'),),
    "identity/effect-binder-slot": ((IDENTITY, PROJECTED, "return ProjectedEffect(0, parts[1])"),),
    # identity.py: lowering's dense renumbering of the packed keys, the
    # other end of the same numbering (ir/lower.dawn).
    "identity/densify-skips-the-captures": ((LOWER, DENSIFY,
        "  dense_expr(dense_params(dense_params(dense_params(d,\n"
        "    f.params), f.dicts), f.evs), f.body)"),),
    "identity/densify-numbers-the-captures-last": ((LOWER, DENSIFY,
        "  dense_expr(dense_params(dense_params(dense_params(dense_params(d,\n"
        "    f.params), f.dicts), f.evs), f.captures), f.body)"),),
    "identity/symbol-table-keeps-the-packed-keys": ((LOWER, MOVED,
        "      Some(next) -> { moved_syms = map.insert(moved_syms, id, s) }"),),
    "identity/symbol-table-carries-what-the-module-never-names": ((LOWER, MOVED + "\n      None -> ()",
        MOVED + "\n      None -> { moved_syms = map.insert(moved_syms, id, s) }"),),
    # identity.py: the minting end, `cx.mint` and `enter_decl` (check/cx.dawn).
    "identity/intern-collision-ignored": ((CX, "Some(other) -> if other != decl {", "Some(other) -> if false {"),),
    "identity/intern-not-recorded": ((CX, INTERN, "(cx, id)"),),
    "identity/mint-takes-a-slot": ((CX, INTERN,
        "(Cx { ..cx, decl_slots: map.insert(cx.decl_slots, cx.owner_decl, slot_of(cx) + 1),\n"
        "    identities: map.insert(cx.identities, id, decl) }, id)"),),
    # A declaration that does not open one numbers its bindings in
    # whatever declaration the previous pass left open; one that
    # reissues slot zero puts its body's locals on its signature's
    # binders; and a pool shared by the program puts two modules'
    # unowned bindings on one key.
    "identity/enter-keeps-the-previous-declaration": ((CX, "Cx { ..interned_cx, owner_decl: id }", "interned_cx"),),
    "identity/slots-restart-at-zero": ((CX, "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = slot_of(cx)",
                                        "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = 0"),),
    "identity/module-pool-is-one-for-the-program": ((CX,
        'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool(cx.owner_class.unwrap_or(""))',
        'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool("")'),),
    "identity/mint-reads-the-source-path": ((CX, MINT,
        'interned(cx, minted(cx.owner_class.unwrap_or("") ++ cx.src_path.unwrap_or(""), kind, name), lo, hi)'),),
    "identity/mint-ignores-the-kind": ((CX, MINT,
        'interned(cx, minted(cx.owner_class.unwrap_or(""), identity.TypeDecl, name), lo, hi)'),),
    # identity.py: the intern table on the carry between modules.
    "identity/drop-identity-carry": ((ANALYZE, "identities: cx.identities,", "identities: before.identities,"),),
    "identity/drop-std-identity-carry": ((STDLIB, "identities: interned,\n    mods: mods,",
                                          "identities: map.empty(),\n    mods: mods,"),),
    "identity/drop-std-identity-step": ((STDLIB, "interned = cx1.identities", "interned = interned"),),
    # `identity.absolute` keeps a diagnostic's own offsets when the
    # revision has no view of its owner, so a program assembled
    # without the views renders declaration-relative offsets as
    # absolute and says nothing about it.
    "identity/drop-render-view": ((ANALYZE,
        "Program { modules: out, diags: diags, decl_spans: carry.decl_spans, ct_world: carry.ct_world }",
        "Program { modules: out, diags: diags, decl_spans: map.empty(), ct_world: carry.ct_world }"),),
    # A module that imports an effect writes the provider's id into its
    # own table; this has it derive one from the name in the importing
    # scope instead.
    "identity/mint-imported-effect": ((PASSES,
        "cx1 = Cx { ..cx1, effects: map.insert(cx1.effects, local, eid) }",
        "let (own_cx, own) = mint(cx1, EffectDecl, name, lo, hi)\n"
        "      cx1 = Cx { ..own_cx, effects: map.insert(own_cx.effects, local, own),\n"
        "        effect_infos: map.insert(own_cx.effect_infos, own, effect_of(own_cx, eid)) }"),),
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
