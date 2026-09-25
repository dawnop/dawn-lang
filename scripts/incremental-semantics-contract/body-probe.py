#!/usr/bin/env python3
"""Survey body state in an isolated compiler, preserving production header order.

Private adapters read the production ModuleHeaders stage product, not a second
copy of the header passes. No production source or emission contract is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from cold import ROOT, HERE, DAWN, install_probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--typed", action="store_true", help="compare the production typed-tree mapper against the cold bodies")
    # `local`, `capture` and `dynamic` stood at the front of this list and
    # turned off the identifier half of the tree projection. A binder is
    # `identity.pack` of its declaration and its slot now, so
    # `relocate.local_id` is deleted and `local_ids` answers with what it is
    # handed: none of the three could be told from the production code (K5).
    # What the same walk still decides -- that a recorded local names a symbol
    # this revision has, and spells it the way the symbol table does -- is
    # `check/body_admit`'s own inline tests and `relocate.py`'s controls.
    typed_variants = ["inferred-write", "test-state", "default-write", "default-dictionary",
                      "impl-owner", "impl-parameters", "impl-roles", "default-diagnostics",
                      "module-functions", "module-signatures", "module-method-boundary", "module-registered-tag",
                      # `header-adt` went with them: `relocate_header.adt` and the
                      # constructor projection under it relocate nothing but
                      # binders, and a binder does not move, so turning the
                      # projection off leaves the same exports (K5). The four
                      # remaining `header-*` controls went with the whole module
                      # in K7: a header product's references are the same
                      # integers in both revisions and its positions are offsets
                      # from the declaration that recorded them, so there was
                      # nothing left for a header projection to project.
                      "read-state"]
    parser.add_argument("--typed-mutant", choices=typed_variants)
    parser.add_argument("--typed-all", action="store_true", help="run the typed positive and its compiling mutations")
    # `skip-symbol` and `skip-captures` stood at the front of this list and
    # turned off the identifier half of the relocation. A binder is
    # `identity.pack` of its declaration and its slot now, so `Move.delta` is
    # zero in every trial the probe builds and the relocation's identifier
    # half is the identity: neither control could be told from the fixture it
    # mutated (K5). The source half below still moves, and still has six.
    variants = ["skip-spans", "skip-operator-spans", "ambiguous-key",
                "skip-cx-symbols", "skip-diagnostics", "skip-symbol-location"]
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mutant", choices=variants)
    modes.add_argument("--all", action="store_true", help="run the positive and all eight compiling negative controls")
    args = parser.parse_args()
    if args.typed_mutant and not args.typed:
        parser.error("--typed-mutant requires --typed")
    if args.typed_all and (not args.typed or args.typed_mutant):
        parser.error("--typed-all requires --typed and cannot select one mutant")
    if args.typed and (args.all or args.mutant):
        parser.error("typed projection has separate negative controls; do not reuse symbol-only mutations")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.typed_all:
        started = time.monotonic()
        for name in ["positive", *typed_variants]:
            command = [sys.executable, str(Path(__file__).resolve()), "--typed",
                       "--java-home", str(args.java_home.resolve()), "--output", str(output / name)]
            if name != "positive":
                command += ["--typed-mutant", name]
            subprocess.run(command, check=True, timeout=900)
        elapsed = time.monotonic() - started
        (output / "summary.json").write_text(json.dumps({"variants": ["positive", *typed_variants],
                                                         "elapsed_seconds": elapsed}, indent=2) + "\n")
        print(f"OK: complete typed-tree and source projection contract, {elapsed:.2f}s")
        return
    if args.all:
        started = time.monotonic()
        for name in ["positive", *variants]:
            command = [sys.executable, str(Path(__file__).resolve()), "--java-home", str(args.java_home.resolve()),
                       "--output", str(output / name)]
            if name != "positive":
                command += ["--mutant", name]
            subprocess.run(command, check=True, timeout=900)
        elapsed = time.monotonic() - started
        (output / "summary.json").write_text(json.dumps({"variants": ["positive", *variants],
                                                         "elapsed_seconds": elapsed}, indent=2) + "\n")
        print(f"OK: complete body identity/relocation prototype, {elapsed:.2f}s")
        return
    java = args.java_home.resolve() / "bin/java"
    javac = args.java_home.resolve() / "bin/javac"
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(ROOT / directory, output / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
    if args.typed_mutant and not args.typed_mutant.startswith("module-"):
        target = output / "selfhost/src/check" / ("checker.dawn" if args.typed_mutant in ("default-dictionary", "read-state") else
                    "allocation.dawn" if args.typed_mutant.startswith("impl-") else
                    "body_product.dawn" if args.typed_mutant in ("inferred-write", "test-state", "default-write", "default-diagnostics") else "body_admit.dawn")
        tree = target.read_text()
        replacements = {
            "read-state": ("Some(_) -> Cx { ..cx, function_reads: semantic_reads.candidates(cx.function_reads, names) }",
                           "Some(_) -> Cx { ..cx, in_test: not cx.in_test, function_reads: semantic_reads.candidates(cx.function_reads, names) }"),
            "default-diagnostics": ("diags: current.diags ++ product.diagnostics",
                                    'diags: if match product.frame.current_sig { Some(s) -> s.name == "sample\\$default\\$0", None -> false } { current.diags } else { current.diags ++ product.diagnostics }'),
            "default-dictionary": ("TDefault { body: dx, dict_syms: dsyms }", "TDefault { body: dx, dict_syms: [] }"),
            "default-write": ("syms: apply_changes(current.syms, product.symbols)",
                              'syms: if match product.frame.current_sig { Some(s) -> s.name == "sample\\$default\\$0", None -> false } { current.syms } else { apply_changes(current.syms, product.symbols) }'),
            "impl-owner": ("sig.name != method.name || sig.owner != cx.owner_class", "sig.name != method.name || false"),
            "impl-parameters": ("sig.tparams != info.tparams", "false"),
            "impl-roles": ("sig.is_builtin ||\n                  sig.trait_id != None || sig.op_of != None", "sig.is_builtin"),
            "inferred-write": ("fns: apply_changes(current.fns, product.signatures)", "fns: current.fns"),
            "test-state": ("in_test: product.in_test", "in_test: if product.frame.current_sig == None { true } else { product.in_test }"),
        }
        old, new = replacements[args.typed_mutant]
        if tree.count(old) != 1:
            raise RuntimeError("Typed mutation anchor drifted: " + args.typed_mutant)
        target.write_text(tree.replace(old, new))
    (output / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
    checker = output / "selfhost/src/check/checker.dawn"
    source = checker.read_text()
    checker.write_text(source + "\npub(pkg) fn headers_with_impls_for_body_probe(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, List[Sig], List[List[Option[Sig]]]) !io = {\n"
                       + "  let headers = check_module_headers(cx, m, env)\n  (headers.cx, headers.sigs, headers.impl_sigs)\n}\n"
                       + "\npub(pkg) fn headers_for_body_probe(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, List[Sig]) !io = {\n"
                       + "  let (next, sigs, _) = headers_with_impls_for_body_probe(cx, m, env)\n  (next, sigs)\n}\n")
    fixture = output / "scripts/body-probe"
    probe = (HERE / "body-probe.dawn.txt").read_text()
    if args.typed:
        # every use of `relocation` and of `check_fn` is replaced below, and an
        # import nothing uses is an error
        probe = probe.replace("use contract/relocation\n", "use contract/typed_projection\n")
        probe = probe.replace("{headers_for_body_probe, check_fn, check_module}",
                              "{headers_for_body_probe, check_module}")
        probe = probe.replace("use contract/typed_projection\n", "use contract/typed_projection\nuse check/body_product\n")
        for old, new in [
            ("pub(pkg) type Trial = { name: String,", "pub(pkg) type Trial = { assembled: Cx, raw: TFun, name: String,"),
            ("Trial { name: d.name,", 'Trial { assembled: body_product.assemble(before, body_product.capture(before, after, raw).expect("body product capture: " ++ d.name)).expect("body product assembly"), raw: raw, name: d.name,'),
        ]:
            if probe.count(old) != 1:
                raise RuntimeError("Body product capture anchor drifted")
            probe = probe.replace(old, new)
        probe += "\npub(pkg) fn header_sample() -> typed_projection.HeaderTrial !io = typed_projection.header_sample()\n"
        probe += "pub(pkg) fn metadata_sample() -> typed_projection.MetadataTrial !io = typed_projection.metadata_sample()\n"
        probe += "\npub(pkg) fn inferred_samples() -> List[typed_projection.StateTrial] !io = typed_projection.inferred_samples()\n"
        probe += "pub(pkg) fn module_samples() -> List[typed_projection.ModuleTrial] !io = typed_projection.module_samples()\n"
        probe += "pub(pkg) fn read_samples() -> List[typed_projection.ModuleTrial] !io = typed_projection.read_samples()\n"
        probe += "pub(pkg) fn module_count(xs: List[typed_projection.ModuleTrial]) -> Int = len(xs)\n"
        probe += "pub(pkg) fn module_at(xs: List[typed_projection.ModuleTrial], i: Int) -> typed_projection.ModuleTrial = xs[i]\n"
        probe += "pub(pkg) fn test_samples() -> List[typed_projection.StateTrial] !io = typed_projection.test_samples()\n"
        probe += "pub(pkg) fn default_samples() -> List[typed_projection.StateTrial] !io = typed_projection.default_samples()\n"
        probe += "pub(pkg) fn import_samples() -> List[typed_projection.StateTrial] !io = typed_projection.import_samples()\n"
        probe += "pub(pkg) fn state_count(xs: List[typed_projection.StateTrial]) -> Int = len(xs)\n"
        probe += "pub(pkg) fn state_at(xs: List[typed_projection.StateTrial], i: Int) -> typed_projection.StateTrial = xs[i]\n"
        old = "relocation.relocate(body, Move {\n        start: mint_cursor(before), limit: mint_cursor(after), delta: 0, span: 0 })"
        new = "typed_projection.body(raw, before, after, 0)"
        if probe.count(old) != 1:
            raise RuntimeError("Typed trial replacement anchor drifted")
        probe = probe.replace(old, new)
        old = "relocation.relocate(saved.body, movement)"
        if probe.count(old) != 1:
            raise RuntimeError("Typed edit replacement anchor drifted")
        probe = probe.replace(old, "typed_projection.body_in_source(saved.raw, saved.before, saved.after, id_delta, headers, new_ast, new_decls[index])")
        anchor = "    replayed_cx = unowned(relocation.replay(replayed_cx, saved.before, saved.after, movement))"
        if probe.count(anchor) != 1:
            raise RuntimeError("Source state replay anchor drifted")
        probe = probe.replace(anchor, "    replayed_cx = unowned(typed_projection.source_state(replayed_cx, saved.before, saved.after, saved.raw, id_delta))")
        # The scheduler owns the declaration boundary, and a body's captured
        # diagnostics are recorded against it. Drive check_fn the way the
        # scheduler does, or the projection refuses an unanchored diagnostic.
        for old, new in [
            ("let before = entered_decl(cx, m, d)",
             "let before = typed_projection.probe_decl(cx, m, d)"),
            ("let (after, body) = check_fn(before, d, signatures[index])",
             "let (after, raw) = typed_projection.checked_body(before, m, d, signatures[index])\n"
             "    let body = typed_projection.resolved_body(before, m, d, raw)"),
            ("let (shifted, shifted_body) = check_fn(with_slots(before, 12345, 1000), d, signatures[index])",
             "let (shifted, shifted_body) = typed_projection.checked_body(with_slots(before, 12345, 1000), m, d, signatures[index])"),
            ("let (first, _) = check_fn(first_cx, new_decls[0], signatures[0])",
             "let (first, _) = typed_projection.checked_body(first_cx, new_ast, new_decls[0], signatures[0])"),
            ("let (checked, _) = check_fn(cold_entered, new_decls[index], signatures[index])",
             "let (checked, _) = typed_projection.checked_body(cold_entered, new_ast, new_decls[index], signatures[index])"),
        ]:
            if probe.count(old) != 1:
                raise RuntimeError("Declaration boundary anchor drifted: " + old)
            probe = probe.replace(old, new)
        old = '"pub fn wrong() -> Int = false\\n"'
        if probe.count(old) != 1:
            raise RuntimeError("Typed corpus extension anchor drifted")
        probe = probe.replace(old, old + " ++\n" + (HERE / "typed-extra.dawn.txt").read_text().strip())
        probe = probe.replace('if d.name == "wrong" { 1 }', 'if d.name == "wrong" || d.name == "asserted" { 1 }')
        typed_source = (HERE / "typed-projection.dawn.txt").read_text()
        if args.typed_mutant and args.typed_mutant.startswith("module-"):
            # Corrupt only the replay-side assembly input/result. Changing the
            # common assembler would corrupt the cold oracle too and prove less.
            old, new = {
                "module-functions": ("functions = functions ++ [moved]", "functions = functions"),
                "module-signatures": (
                    "ModuleTrial { replayed_cx: assembled_cx, cold_cx: whole_cx, replayed: assembled, cold: whole, states: out }",
                    "ModuleTrial { replayed_cx: Cx { ..assembled_cx, fns: map.empty() }, cold_cx: whole_cx, replayed: assembled, cold: whole, states: out }"),
                "module-method-boundary": ("len(group.methods) > 0 && group.methods[0] == key",
                                           "group.key.path == list.take(key.path, 1)"),
                "module-registered-tag": ('impl_of: map.get(tags, key).expect("current impl tag")',
                                          'impl_of: Some((info.trait_id, info.subject))'),
            }[args.typed_mutant]
            if typed_source.count(old) != 1:
                raise RuntimeError("Module assembly mutation anchor drifted")
            typed_source = typed_source.replace(old, new)
            # a mutant that spells std/list brings the import it needs; the
            # unmutated module has no use for it, and an unused import is an error
            if "list." in new:
                typed_source = typed_source.replace("use check/cx.", "use std/list\nuse check/cx.", 1)
        install_probe(output, {"typed_projection": typed_source}, entry="bodyprobe", fixture=fixture)
    identity = (HERE / ("declaration-identity.dawn.txt" if args.typed else "body-identity.dawn.txt")).read_text()
    relocation = (HERE / "body-relocate.dawn.txt").read_text()
    mutations = {
        "skip-spans": ("p + m.span", "p"),
        "skip-operator-spans": ("moved, position(olo, m), position(ohi, m)", "moved, olo, ohi"),
        "skip-cx-symbols": ("..cx, syms: syms", "..cx, syms: cx.syms"),
        "skip-diagnostics": ("cx.diags ++ diagnostics", "cx.diags"),
        "skip-symbol-location": ("dlo: position(s.dlo, m), dhi: position(s.dhi, m)", "dlo: s.dlo, dhi: s.dhi"),
    }
    expected_failure = "relocated body differs from shifted cold check"
    if args.mutant in ("skip-cx-symbols", "skip-diagnostics", "skip-symbol-location"):
        expected_failure = "replayed Cx differs from cold body boundary"
    if args.mutant == "ambiguous-key":
        if identity.count("count == 1") != 1:
            raise RuntimeError("Identity mutation anchor drifted")
        identity = identity.replace("count == 1", "count > 0")
        expected_failure = "duplicate declarations received a reusable identity"
    elif args.mutant:
        old, new = mutations[args.mutant]
        if relocation.count(old) != 1:
            raise RuntimeError("Relocation mutation anchor drifted")
        relocation = relocation.replace(old, new)
    install_probe(output, {"bodyprobe": probe, "relocation": relocation, "identity": identity},
                  entry="bodyprobe", fixture=fixture)
    classes = output / "classes"
    classes.mkdir()
    subprocess.run([str(javac), "--release", "21", "-d", str(classes),
                    str(HERE / "SemanticSnapshot.java"), str(HERE / "BodyProbe.java")], check=True)
    with (output / "build.log").open("w") as log:
        subprocess.run([DAWN, "build", str(fixture), "-o", str(output / "subject.jar")],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    result = subprocess.run([str(java), "-Xss512m", "-cp", str(classes) + ":" + str(output / "subject.jar"),
                             "contract.BodyProbe", "23" if args.typed else "11"], cwd=ROOT, timeout=120,
                            text=True, capture_output=True)
    (output / "run.log").write_text(result.stdout + result.stderr)
    if args.typed_mutant:
        if args.typed_mutant == "default-diagnostics":
            if (result.returncode == 0 or "dawn.rt.PanicError: default boundary check failed" not in result.stderr
                    or "NoSuchMethodError" in result.stderr):
                raise RuntimeError("Default diagnostics mutation did not reach its owning assertion: " + result.stderr)
            print("OK: compiling default-diagnostics mutant rejected")
            return
        if args.typed_mutant == "default-dictionary":
            if (result.returncode == 0 or "dawn.rt.PanicError: default dictionary fixture missing its bound" not in result.stderr
                    or "NoSuchMethodError" in result.stderr):
                raise RuntimeError("Default dictionary mutation did not reach its owning assertion: " + result.stderr)
            print("OK: compiling default-dictionary mutant rejected")
            return
        if args.typed_mutant.startswith("impl-"):
            if (result.returncode == 0 or "dawn.rt.PanicError: invalid impl method metadata accepted" not in result.stderr
                    or "NoSuchMethodError" in result.stderr):
                raise RuntimeError("Impl mutation did not reach its owning guard: " + result.stderr)
            print("OK: compiling impl-header mutant rejected: " + args.typed_mutant)
            return
        expected_comparison = ({"inferred-write": "inferred state: replayed Cx differs from cold body boundary",
                                "read-state": "function reads: observed Cx differs from cold module state",
                                "module-functions": "module assembly: replayed module differs from cold module",
                                "module-signatures": "module assembly: replayed Cx differs from cold module state",
                                "module-method-boundary": "module assembly: replayed module differs from cold module",
                                "module-registered-tag": "module assembly: replayed module differs from cold module",
                                "constant-span": "module assembly: replayed module differs from cold module",
                                "default-write": "default state: replayed Cx differs from cold body boundary",
                                "test-state": "test state: replayed Cx differs from cold body boundary"}.get(args.typed_mutant)
                               or "relocated body differs from shifted cold check")
        if (result.returncode == 0 or "java.lang.AssertionError:" not in result.stderr
                or expected_comparison not in result.stderr
                or "NoSuchMethodError" in result.stderr):
            raise RuntimeError("Typed mutation did not reach its owning comparison: " + result.stderr)
        print("OK: compiling typed-tree mutant rejected: " + args.typed_mutant)
        return
    if args.mutant:
        if result.returncode == 0 or expected_failure not in result.stderr or "NoSuchMethodError" in result.stderr:
            raise RuntimeError("Mutation did not reach its owning semantic comparison: " + result.stderr)
        print("OK: compiling relocation mutant rejected: " + args.mutant)
        return
    if result.returncode != 0:
        raise RuntimeError("Body probe failed: " + result.stderr)
    (output / "state-writes.tsv").write_text(result.stdout)
    version = subprocess.run([str(java), "-version"], text=True, capture_output=True, check=True)
    (output / "metadata.json").write_text(json.dumps({
        "java": version.stdout + version.stderr,
        "production_checker_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "probe_sha256": hashlib.sha256(probe.encode()).hexdigest(),
        "relocation_sha256": hashlib.sha256(relocation.encode()).hexdigest(),
        "identity_sha256": hashlib.sha256(identity.encode()).hexdigest(),
        "typed_projection": args.typed,
        "body_product_sha256": hashlib.sha256((output / "selfhost/src/check/body_product.dawn").read_bytes()).hexdigest() if args.typed else None,
        "allocation_sha256": hashlib.sha256((output / "selfhost/src/check/allocation.dawn").read_bytes()).hexdigest() if args.typed else None,
        "typed_tree_sha256": hashlib.sha256((output / "selfhost/src/check/body_admit.dawn").read_bytes()).hexdigest() if args.typed else None,
        "typed_view_sha256": hashlib.sha256((output / "selfhost/src/contract/typed_projection.dawn").read_bytes()).hexdigest() if args.typed else None,
        "note": "Typed mode: 23 fixed-header bodies with production state capture/assembly, 22 nonuniform source edit replays through production product projection, one reversed effect-header tree case, two inferred body/caller states and one test block state; fixture-only ID/callee views are not production cache validity. Legacy mode: 11 fixed-header bodies and ten uniform-source replays.",
    }, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
