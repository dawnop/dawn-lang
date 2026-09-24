#!/usr/bin/env python3
"""Compare the factored ordinary-function prologue with its frozen old loop.

Temporary proof contexts are generated and discarded in a private checker and
at the existing candidate seam. Neither production admission nor its counts
are changed. Full Cx/tree equality is independent of generated Dawn Eq.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, edit, run


def main():
    started = time.monotonic()
    checker = (ROOT / "selfhost/src/check/checker.dawn").read_text()
    for name in ("check_fn", "check_fn_inferred", "check_const_init", "check_trait_default", "check_test"):
        checker, count = re.subn(r"(pub fn " + name + r"\([^{}]*?!io = \{\n)",
                                 r"\1  GenericTrace.enter()\n", checker)
        if count != 1:
            raise RuntimeError("Function entry counter anchor drifted: " + name)
    checker = ('use java "contract.GenericTrace"\n' + checker + "\n"
               + (HERE / "function-entry-reference.dawn.txt").read_text())
    replay = (ROOT / "selfhost/src/check/scalar_replay.dawn").read_text()
    anchor = "fn candidate(prepared: Prepared, cx: Cx, d: FnDecl, sig: Sig) -> (Prepared, Verdict) = {\n"
    replay = 'use check/cx as entry_probe_cx\n' + edit(replay, anchor, anchor + """  let original_slots = entry_probe_cx.slot_of(cx)
  let original_symbols = map.len(cx.syms)
  let detached = checker.function_entry(cx, d, sig)
  if entry_probe_cx.slot_of(cx) != original_slots || map.len(cx.syms) != original_symbols ||
    entry_probe_cx.slot_of(detached.cx) < original_slots {
    panic("function entry candidate proof advanced live input")
  }
""")
    with tempfile.TemporaryDirectory(prefix="dawn-function-entry-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes),
                        *[str(HERE / file) for file in
                          ("SemanticSnapshot.java", "GenericTrace.java", "FunctionEntryTrace.java")]], check=True)
        oracle = root / "trace.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        (root / "selfhost/src/check/checker.dawn").write_text(checker)
        (root / "selfhost/src/check/scalar_replay.dawn").write_text(replay)
        fixture = root / "scripts/incremental-semantics-contract"
        (fixture / "src").mkdir(parents=True)
        shutil.copyfile(HERE / "dawn.toml", fixture / "dawn.toml")
        subject = (HERE / "generic-trace.dawn.txt").read_text()
        subject = edit(subject, "use compiler/check/checker.{ModuleBodies}",
                       "use compiler/check/checker.{ModuleBodies, ModuleHeaders, BodyExecutor}")
        subject = edit(subject, "use compiler/check/cx.{cx_new, slots_of}",
                       "use compiler/check/cx.{Cx, cx_new, slots_of}")
        subject = edit(subject, "use compiler/check/types.{TyVar, Sym}",
                       "use compiler/check/types.{TyVar, Sym, Sig}")
        (fixture / "src/reference.dawn").write_text(
            'use compiler/check/cx as compiler_cx\nuse compiler/check/tast.{TFun}\n'
            'use compiler/front/ast.{FnDecl}\n' + subject + "\n"
            + (HERE / "function-entry-cases.dawn.txt").read_text())
        # a project's entry module is src/main.dawn (spec §10.5); the fixture's own
        # `main` is an ordinary function now, so a two-line entry forwards to it
        (fixture / "src/main.dawn").write_text("use reference\n\npub fn main() -> Unit !io = reference.main()\n")
        status, output = run("build", "--cp", oracle, fixture, "-o", root / "subject.jar")
        if status:
            raise RuntimeError("Function entry fixture failed to compile\n" + output)
        result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                 str(oracle) + os.pathsep + str(root / "subject.jar"),
                                 "contract.FunctionEntryTrace"], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        print(result.stdout, end="", flush=True)
        if result.returncode or not re.search(r"^PASS: function entry \d+ complete frozen Cx/tree comparisons, "
                                             r"2 detached candidate proof histories with real replay hits$", result.stdout, re.M):
            raise RuntimeError("Function entry missed its frozen full-product oracle")
    print(f"OK: canonical function entry extraction, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
