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

from cold import ROOT, HERE, DAWN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--java-home", required=True, type=Path)
    parser.add_argument("--typed", action="store_true", help="compare the production typed-tree mapper against the cold bodies")
    typed_variants = ["local", "capture", "dynamic", "position", "assertion", "pack-order", "evidence-origin",
                      "inferred-write", "test-state", "symbol-order", "default-write", "default-dictionary",
                      "impl-owner", "impl-parameters", "impl-roles", "default-diagnostics",
                      "module-functions", "module-signatures", "module-method-boundary", "module-registered-tag"]
    parser.add_argument("--typed-mutant", choices=typed_variants)
    parser.add_argument("--typed-all", action="store_true", help="run the typed positive and its twenty compiling mutations")
    variants = ["skip-symbol", "skip-captures", "skip-spans", "skip-operator-spans", "ambiguous-key",
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
        target = output / "selfhost/src/check" / ("checker.dawn" if args.typed_mutant == "default-dictionary" else
                    "allocation.dawn" if args.typed_mutant.startswith("impl-") else
                    "body_product.dawn" if args.typed_mutant in ("inferred-write", "test-state", "symbol-order", "default-write", "default-diagnostics") else "relocate_tree.dawn")
        tree = target.read_text()
        replacements = {
            "default-diagnostics": ("diags: current.diags ++ product.diagnostics",
                                    'diags: if product.function.name == "sample\\$default\\$0" { current.diags } else { current.diags ++ product.diagnostics }'),
            "default-dictionary": ("TDefault { body: dx, dict_syms: dsyms }", "TDefault { body: dx, dict_syms: [] }"),
            "default-write": ("syms: apply_changes(current.syms, product.symbols)",
                              'syms: if product.function.name == "sample\\$default\\$0" { current.syms } else { apply_changes(current.syms, product.symbols) }'),
            "impl-owner": ("sig.name != method.name || sig.owner != cx.owner_class", "sig.name != method.name || false"),
            "impl-parameters": ("sig.tparams != info.tparams", "false"),
            "impl-roles": ("sig.is_builtin ||\n                  sig.trait_id != None || sig.op_of != None", "sig.is_builtin"),
            "symbol-order": ("sort_by(moved_symbols, (a, b) => cmp(a.key, b.key))", "moved_symbols"),
            "inferred-write": ("fns: apply_changes(current.fns, product.signatures)", "fns: current.fns"),
            "test-state": ("in_test: product.in_test", "in_test: if product.function.is_test { true } else { product.in_test }"),
            "local": ("Some(XLocal(relocate.local_id(v.ids, id)?,", "Some(XLocal(id,"),
            "capture": ("names, expression(v, body)?, local_ids(v, captures)?,", "names, expression(v, body)?, captures,"),
            "dynamic": ("Some(XCallDyn(relocate.local_id(v.ids, id)?,", "Some(XCallDyn(id,"),
            "position": ("= map.get(v.positions, old)", "= Some(old)"),
            "assertion": ("v.assertion(src, lo, hi)?", "src"),
            "pack-order": ("let parts = ordered_parts(pack_parts(v, x)?)?", "let parts = pack_parts(v, x)?"),
            "evidence-origin": ("Some(XEvRead(relocate.evidence_key(v.ids, key)?, moved,",
                                "Some(XEvRead(relocate.evidence_key(v.ids, key)?, origin,"),
        }
        old, new = replacements[args.typed_mutant]
        if tree.count(old) != 1:
            raise RuntimeError("Typed mutation anchor drifted: " + args.typed_mutant)
        target.write_text(tree.replace(old, new))
    (output / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
    checker = output / "selfhost/src/check/checker.dawn"
    source = checker.read_text()
    checker.write_text(source + "\npub fn headers_with_impls_for_body_probe(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, List[Sig], List[List[Option[Sig]]]) !io = {\n"
                       + "  let headers = check_module_headers(cx, m, env)\n  (headers.cx, headers.sigs, headers.impl_sigs)\n}\n"
                       + "\npub fn headers_for_body_probe(cx: Cx, m: Module, env: Map[String, ModExports]) -> (Cx, List[Sig]) !io = {\n"
                       + "  let (next, sigs, _) = headers_with_impls_for_body_probe(cx, m, env)\n  (next, sigs)\n}\n")
    fixture = output / "scripts/body-probe"
    (fixture / "src").mkdir(parents=True)
    (fixture / "dawn.toml").write_text((HERE / "dawn.toml").read_text())
    probe = (HERE / "body-probe.dawn.txt").read_text()
    if args.typed:
        probe = probe.replace("use relocation\n", "use relocation\nuse typed_projection\n")
        probe = probe.replace("use typed_projection\n", "use typed_projection\nuse compiler/check/body_product\n")
        for old, new in [
            ("pub type Trial = { name: String,", "pub type Trial = { assembled: Cx, name: String,"),
            ("Trial { name: d.name,", 'Trial { assembled: body_product.assemble(before, body_product.capture(before, after, body).expect("body product capture: " ++ d.name)).expect("body product assembly"), name: d.name,'),
        ]:
            if probe.count(old) != 1:
                raise RuntimeError("Body product capture anchor drifted")
            probe = probe.replace(old, new)
        probe += "\npub fn header_sample() -> typed_projection.HeaderTrial !io = typed_projection.header_sample()\n"
        probe += "\npub fn inferred_samples() -> List[typed_projection.StateTrial] !io = typed_projection.inferred_samples()\n"
        probe += "pub fn module_samples() -> List[typed_projection.ModuleTrial] !io = typed_projection.module_samples()\n"
        probe += "pub fn module_count(xs: List[typed_projection.ModuleTrial]) -> Int = len(xs)\n"
        probe += "pub fn module_at(xs: List[typed_projection.ModuleTrial], i: Int) -> typed_projection.ModuleTrial = xs[i]\n"
        probe += "pub fn test_samples() -> List[typed_projection.StateTrial] !io = typed_projection.test_samples()\n"
        probe += "pub fn default_samples() -> List[typed_projection.StateTrial] !io = typed_projection.default_samples()\n"
        probe += "pub fn import_samples() -> List[typed_projection.StateTrial] !io = typed_projection.import_samples()\n"
        probe += "pub fn state_count(xs: List[typed_projection.StateTrial]) -> Int = len(xs)\n"
        probe += "pub fn state_at(xs: List[typed_projection.StateTrial], i: Int) -> typed_projection.StateTrial = xs[i]\n"
        old = "relocation.relocate(body, Move {\n        start: before.next_id, limit: after.next_id, delta: 1000, span: 0 })"
        new = "typed_projection.body(body, before, after, 1000, 0, str.len(text))"
        if probe.count(old) != 1:
            raise RuntimeError("Typed trial replacement anchor drifted")
        probe = probe.replace(old, new)
        old = "relocation.relocate(saved.body, movement)"
        if probe.count(old) != 1:
            raise RuntimeError("Typed edit replacement anchor drifted")
        probe = probe.replace(old, "typed_projection.body_in_source(saved.body, saved.before, saved.after, id_delta, fixture_text(), edited, old_decls[index].lo, old_decls[index].hi, new_decls[index].lo, new_decls[index].hi)")
        probe = probe.replace("let edited =", "let edited0 =")
        probe = probe.replace("  let (new_ast, pd)", '  let edited = str.replace(edited0, "x > 0", "x  >  0")\n  let (new_ast, pd)')
        anchor = "    replayed_cx = relocation.replay(replayed_cx, saved.before, saved.after, movement)"
        if probe.count(anchor) != 1:
            raise RuntimeError("Source state replay anchor drifted")
        probe = probe.replace(anchor, "    replayed_cx = typed_projection.source_state(replayed_cx, saved.before, saved.after, saved.body, id_delta, fixture_text(), edited, old_decls[index].lo, old_decls[index].hi, new_decls[index].lo, new_decls[index].hi)")
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
        (fixture / "src/typed_projection.dawn").write_text(typed_source)
    (fixture / "src/bodyprobe.dawn").write_text(probe)
    identity = (HERE / ("declaration-identity.dawn.txt" if args.typed else "body-identity.dawn.txt")).read_text()
    relocation = (HERE / "body-relocate.dawn.txt").read_text()
    mutations = {
        "skip-symbol": ("{ id + m.delta }", "{ id }"),
        "skip-captures": ("ids(captures, m), position(lo, m), position(hi, m), ty)", "captures, position(lo, m), position(hi, m), ty)"),
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
    (fixture / "src/relocation.dawn").write_text(relocation)
    (fixture / "src/identity.dawn").write_text(identity)
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
                                "module-functions": "module assembly: replayed module differs from cold module",
                                "module-signatures": "module assembly: replayed Cx differs from cold module state",
                                "module-method-boundary": "module assembly: replayed module differs from cold module",
                                "module-registered-tag": "module assembly: replayed module differs from cold module",
                                "default-write": "default state: replayed Cx differs from cold body boundary",
                                "symbol-order": "reordered header: replayed Cx differs from cold body boundary",
                                "test-state": "test state: replayed Cx differs from cold body boundary"}.get(args.typed_mutant)
                               or ("reordered header: relocated body differs from cold check"
                               if args.typed_mutant in ("pack-order", "evidence-origin")
                               else "relocated body differs from shifted cold check"))
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
        "typed_tree_sha256": hashlib.sha256((output / "selfhost/src/check/relocate_tree.dawn").read_bytes()).hexdigest() if args.typed else None,
        "typed_view_sha256": hashlib.sha256((fixture / "src/typed_projection.dawn").read_bytes()).hexdigest() if args.typed else None,
        "note": "Typed mode: 23 fixed-header bodies with production state capture/assembly, 22 nonuniform source edit replays through production product projection, one reversed effect-header tree case, two inferred body/caller states and one test block state; fixture-only ID/callee views are not production cache validity. Legacy mode: 11 fixed-header bodies and ten uniform-source replays.",
    }, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
