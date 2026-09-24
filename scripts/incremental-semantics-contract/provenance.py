#!/usr/bin/env python3
"""Guard production provenance producers, not only table transformations.

Private source copies must reach the exact transition owning assertion. A
build failure, linker failure or unrelated test cannot stand in for the guard.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run

# The assertion each mutant has to reach. A mutant that only reddens some
# other test has said nothing about the guard it was written for.
CARRY = "module provenance carry keeps exporting owners across header reorder"
EFFECTS = "a consumer names a provider's effect without minting the provider's identity"
SPANS = "the program a render reads from carries this revision's declaration spans"


def main():
    started = time.monotonic()
    driver_path = "selfhost/src/driver/analyze.dawn"
    std_path = "selfhost/src/driver/stdlib.dawn"
    passes_path = "selfhost/src/check/passes.dawn"
    paths = (driver_path, std_path, passes_path)
    originals = {path: (ROOT / path).read_text() for path in paths}
    variants = [
        ("drop-local-origin", CARRY, driver_path, "local_provenance = allocation.table(entries ++ methods)", "local_provenance = None"),
        ("lose-provider-carry", CARRY, driver_path, "map.insert(origin.modules, mf.mod_path, local_provenance)", "map.from([(mf.mod_path, local_provenance)])"),
        ("admit-header-errors", CARRY, driver_path, "if len(headers.cx.diags) == 0 {", "if true {"),
        ("drop-std-origin", CARRY, std_path, "header_origin = allocation.table(entries ++ methods)", "header_origin = None"),
        ("skip-std-world", CARRY, driver_path, 'allocation.in_world(table, "std", world)', "Some(table)"),
        ("drop-compiler-origin", CARRY, driver_path, "intrinsics: allocation.compiler_headers(world)", "intrinsics: None"),
        # The intern table behind the derived nominal and trait ids travels on
        # the carry, and for the reason the carry exists: a digest
        # collision between two modules is as fatal as one inside a module and
        # only a program-wide table can see it.
        ("drop-identity-carry", CARRY, driver_path, "identities: cx.identities,", "identities: before.identities,"),
        ("drop-std-identity-carry", CARRY, std_path, "identities: interned,\n    mods: mods,",
         "identities: map.empty(),\n    mods: mods,"),
        ("drop-std-identity-step", CARRY, std_path, "interned = cx1.identities", "interned = interned"),
        # The carry's fourth field. `identity.absolute` keeps a diagnostic's
        # own offsets when the revision has no view of its owner, so a program
        # assembled without the views renders declaration-relative offsets as
        # absolute and says nothing about it.
        ("drop-render-view", SPANS, driver_path,
         "Program { modules: out, diags: diags, decl_spans: carry.decl_spans }",
         "Program { modules: out, diags: diags, decl_spans: map.empty() }"),
        # The consumer half, on the effect axis: a module that imports an
        # effect writes the provider's id into its own table, and this mutant
        # has it derive one from the name in the importing scope instead.
        # That is the shape the whole ledger exists to refuse, and it is the
        # only place left where a consumer could mint a provider's identity
        # without touching `identity` itself.
        ("mint-imported-effect", EFFECTS, passes_path,
         "cx1 = Cx { ..cx1, effects: map.insert(cx1.effects, local, eid) }",
         "let (own_cx, own) = mint(cx1, EffectDecl, name, lo, hi)\n"
         "      cx1 = Cx { ..own_cx, effects: map.insert(own_cx.effects, local, own),\n"
         "        effect_infos: map.insert(own_cx.effect_infos, own, effect_of(own_cx, eid)) }"),
        # Four consumer-side controls stood here and are gone with the
        # production code they mutated (K5). `module_references` and
        # `ModuleStep.references` were the ledger a consumer resolved a
        # provider's binder through; a binder is `identity.pack` of the
        # declaration that bound it now, so a consumer that reads one is
        # reading the provider's declaration and there is no ledger between
        # them to drop (`drop-provider-reference`). The other three mutated
        # the nominal/trait halves of `allocation` and the declaration path
        # `identity` derives from -- both still there, and both still held:
        # `mint-provider-identity` and `collide-same-domain` are
        # `binding-conflict` and `owner-conflict` in `allocation.py`, and
        # `rename-blind-identity` is `spelling-drops-kind` and
        # `spelling-drops-owner` in `identity.py`, which mutate the derived
        # spelling itself rather than one caller of it.
    ]
    with tempfile.TemporaryDirectory(prefix="dawn-provenance-carry-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        subjects = [("positive", CARRY, driver_path, originals[driver_path])] + [
            (name, owner, path, edit(originals[path], old, new)) for name, owner, path, old, new in variants]
        for name, owner, path, source in subjects:
            (root / path).write_text(source)
            status, output = run("test", root / driver_path)
            failure = re.search(r"^FAIL\s+driver/analyze :: " + re.escape(owner) +
                                r"[^\n]*\n\s+assertion failed:", output, re.M)
            if (status if name == "positive" else not status or not failure):
                raise RuntimeError(name + " did not satisfy its owning contract\n" + output)
            (root / path).write_text(originals[path])
            print("OK: provenance carry " + name, flush=True)
    print(f"OK: provenance producers and {len(variants)} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
