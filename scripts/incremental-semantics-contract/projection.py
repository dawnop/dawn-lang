#!/usr/bin/env python3
"""Exercise source and evidence provenance guards in private compiler copies.

Compiling mutants must fail the exact owning inline assertion; linker errors,
timeouts and unrelated test failures are not evidence for these guards.
"""
import re
import shutil
import tempfile
import time
from pathlib import Path

from cold import ROOT, edit, run


def owning(output, module, title):
    return bool(re.search(r"^FAIL\s+" + re.escape(module + " :: " + title)
                          + r"[^\n]*\n\s+assertion failed:", output, re.M))


def main():
    started = time.monotonic()
    jobs = [
        ("checker", "impl body tags read the entry scope without publishing lookup diagnostics", [
            ("impl-entry-scope", "let (_, subj) = resolve_type(cx, subject)",
             "let (_, subj) = resolve_type(Cx { ..cx, current_tparams: map.empty() }, subject)"),
            ("impl-entry-trait", "match map.get(cx.traits_by_name, trait_name) {\n    Some(t) -> {\n      let (_, subj) = resolve_type(cx, subject)",
             "match Some(77) {\n    Some(t) -> {\n      let (_, subj) = resolve_type(cx, subject)"),
        ]),
        ("checker", "module body assembly preserves roles and synthesized default registration", [
            ("assembly-role-order", "fns_out ++ synth ++ products.impl_methods ++ products.trait_defaults",
             "fns_out ++ synth ++ products.trait_defaults ++ products.impl_methods"),
            ("assembly-constants", "consts: products.constants, tests: products.tests", "consts: [], tests: products.tests"),
            ("assembly-tests", "consts: products.constants, tests: products.tests", "consts: products.constants, tests: []"),
            ("assembly-default-signature", "cx1 = write_signature(cx1, ds.name, ds)", "cx1 = cx1"),
            ("assembly-default-dictionary", "dict_syms: dd.dict_syms,", "dict_syms: [],"),
        ]),
        ("checker", "check_module: a whole module checks end to end", [
            ("header-inference-state", "cx: cx1, sigs: sigs, impl_sigs: impl_sigs",
             "cx: cx1, sigs: PathTable { ..sigs, first: map.from(map(map.entries(sigs.first), e => {\n"
             "    let (k, s) = e\n    (k, Sig { ..s, inferring: false })\n  })) }, impl_sigs: impl_sigs"),
            ("header-const-types", "impl_sigs: impl_sigs, const_tys: const_tys }", "impl_sigs: impl_sigs, const_tys: identity.path_table() }"),
        ]),
        # These two moved here from body-probe.py's typed mutants when nominal
        # and trait ids started deriving from their declarations. Their old
        # owner was the reordered-header sample, and a declaration reorder can
        # no longer permute an evidence pack: a ground label is a derived
        # identity and stays put, and a declaration's own binders are minted in
        # one lexical sweep so they keep their order among themselves. The
        # inline test below is where the behaviour still has a judgment,
        # because it hands the relocation two type variables that do swap.
        ("body_admit", "body admission lays out ground packs and associated environment order", [
            ("pack-order", "Some(parts) -> ordered_parts(parts) != None", "Some(parts) -> true"),
            # `evidence-origin` used to turn the projected origin back into
            # the recorded one. Projecting it is the identity now, so what is
            # left at this call site to get wrong is the refusal beside it:
            # the key a read carries and the origin it carries are two
            # records of the same slot, and a pair that disagrees is a
            # product this compiler did not write (K5).
            ("crossed-evidence-origin",
             "    XEvRead(key, origin, _, _, _) -> key == evidence_role_key(origin)",
             "    XEvRead(key, origin, _, _, _) -> true"),
        ]),
        ("body_admit", "body admission checks defaults symbols and entry call evidence", [
            # `constant-type` stood here, moved from body-probe's typed
            # mutants in K4 because the value sample's constants are declared
            # at types with no binders in them. It is gone for the reason the
            # whole table went: `relocate.ty` answers with what it is handed
            # (K5). What this assembly still decides is arity -- a recorded
            # function's evidence symbols against the ABI row its signature
            # describes -- and that is what the control below turns off. The
            # anchor moved in K6 with the permutation it used to read a length
            # off; the judgment and its owning assertion did not.
            ("evidence-arity", "if nev(sig_abi_eff(f.sig)) != len(f.ev_syms) { return false }",
             "if false { return false }"),
        ]),
        ("callee_index", "callee lookup preserves declaring owners across module aliases", [
            # The production lookup is the index, so these three mutate the
            # index. The linear scan they used to mutate is now only the
            # oracle `callee_answers_agree` compares against. The module moved
            # out of the tree visitor in K7: finding a callee is a lookup, not
            # a translation.
            ("callee-owner", "let key = (sig.owner, sig.name)",
             "let key: (Option[String], String) = (None, sig.name)"),
            ("callee-module-alias", "for (_, sig) in map.entries(cx.module_fn_sigs) { by_key = index_signature(by_key, sig) }", ""),
            ("callee-conflict", "if previous != sig { map.insert(into, key, CalleeConflict) } else { into }", "into"),
        ]),
        # The two code-point tables, and the assertion text they re-sliced, are
        # gone with the positions they answered for. What is left is the
        # question a saved body actually asks: are these two declarations the
        # same tokens, and are they the same bytes.
        ("source_projection", "source projection ", [
            ("changed-spelling", "x.kinds == y.kinds && x.texts == y.texts", "x.kinds == y.kinds"),
            ("unchecked-range", "x.lo == old_lo && x.hi == old_hi && y.lo == new_lo && y.hi == new_hi &&\n      ", ""),
            ("misaligned-slice", "if t.lo < lo || t.hi > hi { aligned = false }", ""),
        ]),
        # Declaration-aligned examples now hit the exact raw cache. This
        # mutant changes only the arbitrary-range fallback, so its owner is
        # the independent range-product oracle. source-equality.py separately
        # mutates cached equality and owns the equal-width trivia assertion.
        ("source_projection", "source text equality matches the raw oracle over code point ranges", [
            ("byte-identity", "str.slice(a.text, old_lo, old_hi) == str.slice(b.text, new_lo, new_hi)", "true"),
        ]),
        ("checker", "evidence reads preserve distinct origins behind the same runtime key", [
            ("lost-crossed-origin",
             "if crossed {\n        (cx1, Some(XEvRead(key, origin, owner_off(cx, lo), owner_off(cx, hi), ty)))",
             "if crossed {\n        (cx1, Some(XEvRead(key, VariableSlot(0), owner_off(cx, lo), owner_off(cx, hi), ty)))"),
            ("lost-missing-origin",
             "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, origin, owner_off(cx, lo), owner_off(cx, hi), ty)))",
             "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, VariableSlot(0), owner_off(cx, lo), owner_off(cx, hi), ty)))"),
        ]),
    ]
    assert owning("FAIL  check/source_projection :: source projection control\n assertion failed: expected\n",
                  "check/source_projection", "source projection ")
    assert not owning("FAIL  check/source_projection :: source projection control\n NoSuchMethodError\n",
                      "check/source_projection", "source projection ")
    with tempfile.TemporaryDirectory(prefix="dawn-projection-contract-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        for module, title, mutations in jobs:
            target = root / "selfhost/src/check" / (module + ".dawn")
            original = target.read_text()
            subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in mutations]
            for name, source in subjects:
                target.write_text(source)
                status, output = run("test", target)
                if name == "positive":
                    if status:
                        raise RuntimeError("Positive projection subject failed\n" + output)
                elif not status or not owning(output, "check/" + module, title):
                    raise RuntimeError(name + " did not reach its owning assertion\n" + output)
                print("OK: projection " + module + " " + name, flush=True)
            target.write_text(original)
    count = sum(len(mutations) for _, _, mutations in jobs)
    print(f"OK: source/evidence/callee/header/assembly projection and {count} compiling mutants, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
