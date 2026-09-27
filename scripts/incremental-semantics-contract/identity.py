#!/usr/bin/env python3
"""Require declaration identity admission to survive compiling negative controls.

The private subject keeps its parser and declaration index together; only
production identity admission changes, never the owning test assertions.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def main():
    started = time.monotonic()
    original = (ROOT / "selfhost/src/check/identity.dawn").read_text()
    variants = [
        ("duplicate-parent", "if unique { out = out ++ [e] }", "out = out ++ [e]"),
        # The derived id: what it is a function of, and what it must not be a
        # function of. The spelling is the whole input, so dropping the kind
        # letter or the owner from it merges two declarations, and skipping
        # the finalizer leaves the low bits -- the only ones a 47-bit band
        # keeps, and the only ones `Map[Int, _]` buckets on -- correlated
        # across two names that differ in one character.
        ("spelling-drops-kind", 'Named(kind, name) -> "N" ++ kind_text(kind) ++ atom(name)',
         'Named(kind, name) -> "N" ++ atom(name)'),
        ("spelling-drops-owner", "pub fn minted_text(m: Minted) -> String = atom(m.owner) ++ path_text",
         "pub fn minted_text(m: Minted) -> String = atom(\"\") ++ path_text"),
        ("derive-skips-finalizer", "derived_floor() + (fmix64(fnv1a64(spelling)) & derived_width())",
         "derived_floor() + (fnv1a64(spelling) & derived_width())"),
        ("derive-leaves-the-band", "pub fn derived_floor() -> Int = 4294967296",
         "pub fn derived_floor() -> Int = 7"),
        ("derive-overflows-the-label-key", "pub fn derived_width() -> Int = 140737488355327",
         "pub fn derived_width() -> Int = 9223372036854775807"),
        # The packed key: what it is made of, what it refuses, and the two
        # things it has to stay clear of. A slot outside the span folded back
        # into the key is two bindings of one declaration sharing a row; a
        # pool shared by the whole program is two modules sharing one; and a
        # temporary floor inside the packed band is lowering numbering over a
        # binding the checker minted.
        ("pack-truncates-the-slot", "if slot < 0 || slot >= slot_span() { return None }",
         "if slot < 0 { return None }"),
        ("pack-drops-the-declaration", "Some(declaration * slot_span() + slot)", "Some(slot)"),
        ("pool-is-one-for-the-program", 'pub fn free_pool(owner: String) -> Int = derive_text(atom(owner) ++ "P")',
         'pub fn free_pool(owner: String) -> Int = derive_text("P")'),
        ("temporary-floor-inside-the-band",
         "pub fn temporary_floor() -> Int = (derived_floor() + derived_width() + 1) * slot_span()",
         "pub fn temporary_floor() -> Int = derived_floor()"),
        ("parent-not-checked", "var depth = 1", "var depth = len(e.entry.key.path)"),
        ("binder-spelling", "return BoundType(i)", "return NamedType(name, [], [])"),
        ("default-ambiguity", "if same == 1 {", "if same >= 1 {"),
        ("world-erased", "DeclKey { scope: scope, path: path }",
         'DeclKey { scope: ModuleKey { ..scope, world: "shared" }, path: path }'),
        ("effect-binder-spelling", "return ProjectedEffect(i, parts[1])", "return NamedEffect(name)"),
        ("effect-member-erased", "return ProjectedEffect(i, parts[1])", 'return ProjectedEffect(i, "")'),
        ("effect-binder-slot", "return ProjectedEffect(i, parts[1])", "return ProjectedEffect(0, parts[1])"),
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-declaration-identity-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost/src/check/identity.dawn"
        for name, source in [("positive", original)] + [(n, edit(original, a, b)) for n, a, b in variants]:
            target.write_text(source)
            status, output = run("test", target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive identity subject failed\n" + output)
            elif not status or not re.search(r"^FAIL\s+check/identity :: identity [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: declaration identity " + name, flush=True)
        target.write_text(original)
        # The other end of the same numbering. A packed key means nothing
        # below the checker, so lowering renumbers every one of them into one
        # run of small integers per module, in the order `ir/coredump` names
        # them. Both consumers are outside Core's own meaning -- `emitc`
        # prints a local as `v<id>`, the JVM emitter looks its type up in one
        # module-wide table -- and neither can tell a wrong order from a right
        # one, so the order is held here.
        #
        # A lifted body refers to its captures by the ids the enclosing
        # function gave them, so a pass that stops visiting them does not
        # crash: it numbers them at their first appearance in the body, which
        # is why these are assertions about an order rather than a missing key.
        lower_target = root / "selfhost/src/ir/lower.dawn"
        lower_original = lower_target.read_text()
        lower_variants = [
            ("densify-skips-the-captures",
             "  dense_expr(dense_params(dense_params(dense_params(dense_params(d, f.captures),\n"
             "    f.params), f.dicts), f.evs), f.body)",
             "  dense_expr(dense_params(dense_params(dense_params(d,\n"
             "    f.params), f.dicts), f.evs), f.body)"),
            ("densify-numbers-the-captures-last",
             "  dense_expr(dense_params(dense_params(dense_params(dense_params(d, f.captures),\n"
             "    f.params), f.dicts), f.evs), f.body)",
             "  dense_expr(dense_params(dense_params(dense_params(dense_params(d,\n"
             "    f.params), f.dicts), f.evs), f.captures), f.body)"),
            ("symbol-table-keeps-the-packed-keys",
             "      Some(next) -> { moved_syms = map.insert(moved_syms, next, s) }",
             "      Some(next) -> { moved_syms = map.insert(moved_syms, id, s) }"),
            ("symbol-table-carries-what-the-module-never-names",
             "      Some(next) -> { moved_syms = map.insert(moved_syms, next, s) }\n      None -> ()",
             "      Some(next) -> { moved_syms = map.insert(moved_syms, next, s) }\n"
             "      None -> { moved_syms = map.insert(moved_syms, id, s) }"),
        ]
        for name, source in ([("positive", lower_original)] +
                             [(n, edit(lower_original, a, b)) for n, a, b in lower_variants]):
            lower_target.write_text(source)
            status, output = run("test", lower_target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive densify subject failed\n" + output)
            elif not status or not re.search(
                    r"^FAIL\s+ir/lower :: lowering numbers [^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: dense numbering " + name, flush=True)
        lower_target.write_text(lower_original)
        # The minting end of the same identities: `cx.mint` interns a derived
        # id and refuses a collision, and `enter_decl` opens the declaration
        # whose slots its bindings take. These controls lived in allocation.py
        # beside the provenance ledger until that ledger went with the replay
        # engine (2026-09-27); the code they hold is on every cold check.
        cx_target = root / "selfhost/src/check/cx.dawn"
        cx_original = cx_target.read_text()
        cx_variants = [
            ("intern-collision-ignored", "Some(other) -> if other != decl {", "Some(other) -> if false {"),
            ("intern-not-recorded", "(Cx { ..cx, identities: map.insert(cx.identities, id, decl) }, id)", "(cx, id)"),
            ("mint-takes-a-slot", "(Cx { ..cx, identities: map.insert(cx.identities, id, decl) }, id)",
             "(Cx { ..cx, decl_slots: map.insert(cx.decl_slots, cx.owner_decl, slot_of(cx) + 1),\n"
             "    identities: map.insert(cx.identities, id, decl) }, id)"),
            # A declaration that does not open one numbers its bindings in
            # whatever declaration the previous pass left open; one that
            # reissues slot zero puts its body's locals on its signature's
            # binders; and a pool shared by the program puts two modules'
            # unowned bindings on one key.
            ("enter-keeps-the-previous-declaration", "Cx { ..interned_cx, owner_decl: id }", "interned_cx"),
            ("slots-restart-at-zero", "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = slot_of(cx)",
             "pub(pkg) fn fresh(cx: Cx) -> (Cx, Int) = {\n  let slot = 0"),
            ("module-pool-is-one-for-the-program",
             'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool(cx.owner_class.unwrap_or(""))',
             'pub(pkg) fn module_pool(cx: Cx) -> Int = free_pool("")'),
            ("mint-reads-the-source-path",
             'interned(cx, minted(cx.owner_class.unwrap_or(""), kind, name), lo, hi)',
             'interned(cx, minted(cx.owner_class.unwrap_or("") ++ cx.src_path.unwrap_or(""), kind, name), lo, hi)'),
            ("mint-ignores-the-kind",
             'interned(cx, minted(cx.owner_class.unwrap_or(""), kind, name), lo, hi)',
             'interned(cx, minted(cx.owner_class.unwrap_or(""), identity.TypeDecl, name), lo, hi)'),
        ]
        for name, source in [("positive", cx_original)] + [(n, edit(cx_original, a, b)) for n, a, b in cx_variants]:
            cx_target.write_text(source)
            status, output = run("test", cx_target)
            if name == "positive":
                if status:
                    raise RuntimeError("Positive mint subject failed\n" + output)
            elif not status or not re.search(
                    r"^FAIL\s+check/cx :: (a minted id|two declarations|identifiers are numbered|the free pool) "
                    r"[^\n]*\n\s+assertion failed:", output, re.M):
                raise RuntimeError(name + " did not reach its owning assertion\n" + output)
            print("OK: derived identity " + name, flush=True)
        cx_target.write_text(cx_original)
        # The carry between modules. The intern table travels on it for the
        # reason the carry exists: a digest collision between two modules is
        # as fatal as one inside a module, and only a program-wide table can
        # see it. These controls lived in provenance.py until the provenance
        # half of the carry went with the replay engine (2026-09-27).
        carry = "module identity carry keeps exporting owners across header reorder"
        effects = "a consumer names a provider's effect without minting the provider's identity"
        spans = "the program a render reads from carries this revision's declaration spans"
        driver_path = "selfhost/src/driver/analyze.dawn"
        std_path = "selfhost/src/driver/stdlib.dawn"
        passes_path = "selfhost/src/check/passes.dawn"
        carry_originals = {path: (root / path).read_text() for path in (driver_path, std_path, passes_path)}
        carry_variants = [
            ("drop-identity-carry", carry, driver_path, "identities: cx.identities,", "identities: before.identities,"),
            ("drop-std-identity-carry", carry, std_path, "identities: interned,\n    mods: mods,",
             "identities: map.empty(),\n    mods: mods,"),
            ("drop-std-identity-step", carry, std_path, "interned = cx1.identities", "interned = interned"),
            # `identity.absolute` keeps a diagnostic's own offsets when the
            # revision has no view of its owner, so a program assembled
            # without the views renders declaration-relative offsets as
            # absolute and says nothing about it.
            ("drop-render-view", spans, driver_path,
             "Program { modules: out, diags: diags, decl_spans: carry.decl_spans }",
             "Program { modules: out, diags: diags, decl_spans: map.empty() }"),
            # A module that imports an effect writes the provider's id into its
            # own table; this has it derive one from the name in the importing
            # scope instead.
            ("mint-imported-effect", effects, passes_path,
             "cx1 = Cx { ..cx1, effects: map.insert(cx1.effects, local, eid) }",
             "let (own_cx, own) = mint(cx1, EffectDecl, name, lo, hi)\n"
             "      cx1 = Cx { ..own_cx, effects: map.insert(own_cx.effects, local, own),\n"
             "        effect_infos: map.insert(own_cx.effect_infos, own, effect_of(own_cx, eid)) }"),
        ]
        carry_subjects = [("positive", carry, driver_path, carry_originals[driver_path])] + [
            (name, owner, path, edit(carry_originals[path], old, new))
            for name, owner, path, old, new in carry_variants]
        for name, owner, path, source in carry_subjects:
            (root / path).write_text(source)
            status, output = run("test", root / driver_path)
            (root / path).write_text(carry_originals[path])
            failure = re.search(r"^FAIL\s+driver/analyze :: " + re.escape(owner) +
                                r"[^\n]*\n\s+assertion failed:", output, re.M)
            if (status if name == "positive" else not status or not failure):
                raise RuntimeError(name + " did not satisfy its owning contract\n" + output)
            print("OK: identity carry " + name, flush=True)
    total = len(variants) + len(lower_variants) + len(cx_variants) + len(carry_variants)
    print(f"OK: declaration identity and {total} compiling mutants, "
          f"{time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
