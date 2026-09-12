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
            ("header-inference-state", "cx: cx1, sigs: sigs, impl_sigs: impl_sigs", "cx: cx1, sigs: map(sigs, s => Sig { ..s, inferring: false }), impl_sigs: impl_sigs"),
            ("header-const-types", "impl_sigs: impl_sigs, const_tys: const_tys }", "impl_sigs: impl_sigs, const_tys: [] }"),
        ]),
        ("relocate_tree", "tree callee lookup preserves declaring owners across module aliases", [
            # The production lookup is the index, so these three mutate the
            # index. The linear scan they used to mutate is now only the
            # oracle `callee_answers_agree` compares against.
            ("callee-owner", "let key = (sig.owner, sig.name)",
             "let key: (Option[String], String) = (None, sig.name)"),
            ("callee-module-alias", "for (_, sig) in map.entries(cx.module_fn_sigs) { by_key = index_signature(by_key, sig) }", ""),
            ("callee-conflict", "if previous != sig { map.insert(into, key, CalleeConflict) } else { into }", "into"),
        ]),
        ("source_projection", "source projection ", [
            ("same-boundary-table", "ends: ends, old_text: old_text,", "ends: starts, old_text: old_text,"),
            ("changed-token", "a.kind != b.kind || str.slice(old_text, a.lo, a.hi) != str.slice(new_text, b.lo, b.hi)", "false"),
            ("stale-assertion", "Some(Some(str.slice(p.new_text, nlo, nhi)))", "Some(Some(text))"),
            ("unchecked-assertion-origin", "str.slice(p.old_text, start, hi) != text", "false"),
            ("indexed-source-domain", "let starts = map.fold(local.starts, empty, (out, key, value) =>\n      map.insert(out, key + old_lo, value + new_lo))",
             "let starts = map.fold(local.starts, empty, (out, key, value) =>\n      map.insert(out, key + new_lo, value + new_lo))"),
            ("indexed-target-domain", "let ends = map.fold(local.ends, empty, (out, key, value) =>\n      map.insert(out, key + old_lo, value + new_lo))",
             "let ends = map.fold(local.ends, empty, (out, key, value) =>\n      map.insert(out, key + old_lo, value + old_lo))"),
        ]),
        ("checker", "evidence reads preserve distinct origins behind the same runtime key", [
            ("lost-crossed-origin", "if crossed {\n        (cx1, Some(XEvRead(key, origin, lo, hi, ty)))",
             "if crossed {\n        (cx1, Some(XEvRead(key, VariableSlot(0), lo, hi, ty)))"),
            ("lost-missing-origin", "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, origin, lo, hi, ty)))",
             "if len(cx1.frame.lambda_stack) > 0 {\n        (cx1, Some(XEvRead(key, VariableSlot(0), lo, hi, ty)))"),
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
