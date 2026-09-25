#!/usr/bin/env python3
"""Require actual bounded-generic hits, complete cold products and precise refusals."""
import argparse
import os
import re
import runpy
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, edit, install_probe, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-only", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    classifier = runpy.run_path(str(HERE / "bounded-entry-proof.py"))
    classifier["classifier_selftest"]()
    bounded = (ROOT / "selfhost/src/check/bounded_replay.dawn").read_text()
    replay = (ROOT / "selfhost/src/check/scalar_replay.dawn").read_text()
    variants = [
        # A trailing list is further edits to the same module: a mutant that
        # removes the last use of an import removes the import too, because an
        # import nothing uses is an error and a mutant that does not compile
        # proves nothing.
        ("root-result", "replay", "saved.bounded && tex_ty(p.tree.body) != sig.ret", "false", "bounded replay rejected root result",
         [("use check/tast.{TFun, tex_ty}", "use check/tast.{TFun}")]),
        ("witness-role", "bounded", "witnesses == expected", "true", "bounded replay rejected witness role"),
        ("argument-unification", "bounded", "not matched || map.len(next_effects) != 0", "map.len(next_effects) != 0", "bounded replay rejected argument unification"),
        ("argument-role", "bounded", "symbol.ty != ty || ", "", "bounded replay rejected argument role"),
        ("callee-owner", "bounded", "found.owner != owner || ", "", "bounded replay rejected callee owner"),
        ("unification-fact", "replay", "checker.revalidate_read(scoped, read) != Some(true)", "false", "bounded replay rejected unification fact"),
        ("trait-signature", "replay", "checker.revalidate_read(scoped, read) != Some(true)",
         "(match read { semantic_reads.FunctionAnswer(_) -> Some(true), _ -> checker.revalidate_read(scoped, read) }) != Some(true)",
         "bounded replay real dependency transition"),
        ("entry-frame", "replay", """match function_entry_proof.prove(cx, d, sig, p) {
      Some(proof) -> function_entry_proof.context(proof)
      None -> return (prepared, Rejected)
    }""", "checker.function_entry(cx, d, sig).cx", "bounded replay rejected entry frame",
         [("use check/function_entry_proof\n", "")]),
        ("unknown-fact", "bounded", "semantic_reads.AssignableType(_, _, _) -> true\n  _ -> false",
         "semantic_reads.AssignableType(_, _, _) -> true\n  semantic_reads.StdModuleMode(_) -> true\n  _ -> false", "bounded replay rejected unknown fact"),
        ("disguised-cold", "replay", "Some(after) -> (reused(stepped), after, product.tree)\n          None -> cold.function",
         "Some(after) -> if len(sig.constraints) != 0 { cold.function(reused(stepped), cx, d, sig) } else { (reused(stepped), after, product.tree) }\n          None -> cold.function",
         "generic trace actual bounded replay count"),
        ("lost-renewal", "replay", "ready: ready(data.scope, next, source, captured.entries, captured.bodies.cx)",
         "ready: ready(data.scope, next, source, [], captured.bodies.cx)", "generic trace actual bounded renewal count"),
    ]
    subjects = [("positive", bounded, replay, None)]
    if not args.positive_only:
        for name, target, before, after, owner, *also in variants:
            edits = [(before, after)] + (also[0] if also else [])
            def mutated(text):
                for old, new in edits:
                    text = edit(text, old, new)
                return text
            subjects.append((name, mutated(bounded) if target == "bounded" else bounded,
                             mutated(replay) if target == "replay" else replay, owner))
    checker = (ROOT / "selfhost/src/check/checker.dawn").read_text()
    for name in ("check_fn", "check_fn_inferred", "check_const_init", "check_trait_default", "check_test"):
        checker, count = re.subn(r"(pub\(pkg\) fn " + name + r"\([^{}]*?!io = \{\n)", r"\1  GenericTrace.enter()\n", checker)
        if count != 1:
            raise RuntimeError("Bounded replay actual counter anchor drifted: " + name)
    with tempfile.TemporaryDirectory(prefix="dawn-bounded-replay-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes), *[str(HERE / name) for name in
            ("SemanticSnapshot.java", "GenericTrace.java", "FunctionEntryTrace.java", "BoundedReplayTrace.java")]], check=True)
        oracle = root / "trace.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        (root / "selfhost/src/check/checker.dawn").write_text('use java "contract.GenericTrace"\n' + checker)
        text = (HERE / "generic-trace.dawn.txt").read_text()
        for before, after in [
            (".{ModuleBodies}", ".{ModuleBodies, ModuleHeaders}"),
            (".{cx_new, slots_of}", ".{Cx, Frame, cx_new, slots_of}"),
            (".{Product}", ".{Product, BodyProduct}"),
            (".{SavedFunction, FunctionInput}", ".{SavedFunction, FunctionInput, Recorded}"),
            (".{Key, BoundsKey, SymbolKey}", ".{Key, BoundsKey, SymbolKey, SignatureKey}"),
        ]:
            text = edit(text, before, after)
        fixture = install_probe(root, {"reference": text + "\n" + (HERE / "bounded-replay-cases.dawn.txt").read_text()})
        for name, bounded_source, replay_source, owner in subjects:
            (root / "selfhost/src/check/bounded_replay.dawn").write_text(bounded_source)
            (root / "selfhost/src/check/scalar_replay.dawn").write_text(replay_source)
            status, output = run("build", "--cp", oracle, fixture, "-o", root / "subject.jar")
            if status:
                raise RuntimeError(f"Bounded replay {name} failed to compile\n{output}")
            result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp", str(oracle) + os.pathsep + str(root / "subject.jar"),
                "contract.BoundedReplayTrace"], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            if owner is None:
                if result.returncode or "PASS: bounded replay 15 full-body histories and 12 complete prepared Programs" not in result.stdout:
                    raise RuntimeError("Bounded replay positive failed\n" + result.stdout)
            elif not classifier["owning_failure"](result.returncode, result.stdout, owner):
                raise RuntimeError(f"Bounded replay {name} missed sole owner {owner}\n{result.stdout}")
            print(f"OK: bounded replay {name}" + (f" -> {owner}" if owner else ""), flush=True)
    print(f"OK: bounded replay {len(subjects) - 1} compiling controls; elapsed={time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
