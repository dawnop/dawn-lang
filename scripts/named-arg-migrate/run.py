#!/usr/bin/env python3
"""Delete after knife 4. Hold the migration to syntax ownership, not text shape.

The exact expected rewrite protects annotations, Unicode offsets, comments,
strings and puns. The same source path is reused for both separators so AST,
checker and Core comparisons cannot hide a difference behind path scrubbing.
"""
import argparse
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile

from migrate import HERE, apply, probe, run

ROOT = HERE.parents[1]
SOURCE = '''# 😀 x: comment
type P = { x: Int, y: Int }
type K = K(x: Int)
fn f(a: Int, b: Int = a + 1) -> Int = a + b
fn g(p: P) -> Int = {
  let text = "x: ordinary text ${f(a: 1, b: 2)}"
  let x: Int = len(text)
  let q = P { ..p, x, y: f(b: # a comment before the value
    3, a: x) }
  match K(x: q.y) { K(x: n) -> n }
}
'''
EXPECTED = '''# 😀 x: comment
type P = { x: Int, y: Int }
type K = K(x: Int)
fn f(a: Int, b: Int = a + 1) -> Int = a + b
fn g(p: P) -> Int = {
  let text = "x: ordinary text ${f(a= 1, b= 2)}"
  let x: Int = len(text)
  let q = P { ..p, x, y= f(b= # a comment before the value
    3, a= x) }
  match K(x= q.y) { K(x= n) -> n }
}
'''


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print("OK: " + label)


def cli(dawn, *args):
    return run(dawn, *map(str, args), cwd=ROOT)


def source_hits(java, jar, work, path):
    return [{"kind": row[2], "offset": int(row[3])}
            for row in probe(java, jar, work, [path]) if row[0] in ("H", "R")]


def expect_red(assertion, label):
    try:
        assertion()
    except AssertionError as error:
        check(str(error) == label, "negative control fails at its owning assertion")
        print("RED: " + label)
    else:
        raise AssertionError("mutant stayed green: " + label)


def mutants(args, work):
    for name in ("migrator-rewrites-type", "label-as-assignment", "formatter-rewrites-separator"):
        tree = work / name
        shutil.copytree(HERE, tree / "scripts/named-arg-migrate", ignore=shutil.ignore_patterns("__pycache__"))
        if name != "migrator-rewrites-type":
            shutil.copytree(ROOT / "selfhost", tree / "selfhost")
            for dep in ("compiler-plan", "packages"):
                (tree / dep).symlink_to(ROOT / dep, target_is_directory=True)
        run(sys.executable, str(HERE / "mutate.py"), name, str(tree))
        path = tree / "probe.dawn"
        if name == "migrator-rewrites-type":
            modified = runpy.run_path(str(tree / "scripts/named-arg-migrate/migrate.py"))["apply"]
            expect_red(lambda: check(modified(SOURCE, []) == SOURCE, "migrator protects type colons"),
                       "migrator protects type colons")
            continue
        jar = tree / "compiler.jar"
        cli(args.dawn, "build", tree / "selfhost", "-o", jar)
        # An unsuccessful compiler build is an error, never a red control.
        if name == "label-as-assignment":
            path.write_text("fn probe() = { var a = 0\n f(a = 2) }\n")
            output = run(args.java, "-Xss64m", "-Xmx2g", "-jar", str(jar), "__parse", str(path))
            check("!\t" not in output, "assignment mutant parses successfully")
            expect_red(lambda: check("Arg name=a" in output and "Assign" not in output,
                                     "call equals is a label, never assignment"),
                       "call equals is a label, never assignment")
        else:
            path.write_text("fn probe() = f(a=1)\n")
            run(args.java, "-Xss64m", "-Xmx2g", "-jar", str(jar), "fmt", str(path))
            expect_red(lambda: check(path.read_text() == "fn probe() = f(a = 1)\n",
                                     "formatter preserves equals separators"),
                       "formatter preserves equals separators")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dawn", default=str(ROOT / "bin/dawn"))
    parser.add_argument("--jar", type=Path, default=ROOT / "build/dawn-selfhost.jar")
    parser.add_argument("--java", default="java")
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--mutants", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="named-arg-contract-") as temporary:
        work = Path(temporary)
        if args.mutants:
            mutants(args, work)
        run(args.javac, "-cp", str(args.jar), "-d", str(work), str(HERE / "SpanProbe.java"))
        path = work / "probe.dawn"
        path.write_text(SOURCE)
        hits = source_hits(args.java, args.jar, work, path)
        check(apply(SOURCE, hits) == EXPECTED, "migration changes only seven parser-owned value colons")
        path.write_bytes(SOURCE.replace("\n", "\r\n").encode())
        crlf_hits = source_hits(args.java, args.jar, work, path)
        check(apply(SOURCE.replace("\n", "\r\n"), crlf_hits) == EXPECTED.replace("\n", "\r\n"),
              "CRLF and supplementary Unicode retain code point offsets")
        # First make the oracle red by feeding the actual edit function a type
        # colon. Its exact-source assertion must reject that result.
        bad_hits = hits + [{"offset": SOURCE.index("x: Int") + 1}]
        check(apply(SOURCE, bad_hits) != EXPECTED, "negative control: migrating a type colon is rejected")
        path.write_text(EXPECTED)
        check(source_hits(args.java, args.jar, work, path) == [], "second migration has no source edits")
        outputs = []
        for text in (SOURCE, EXPECTED):
            path.write_text(text)
            parsed = cli(args.dawn, "__parse", path)
            check("!\t" not in parsed, "fixture parses")
            checked = cli(args.dawn, "__check", path)
            check("D\t" not in checked, "fixture checks")
            dump = work / "core"
            cli(args.dawn, "__lower", path, "--dump", dump)
            outputs.append((parsed, checked, {p.name: p.read_bytes() for p in dump.glob("*.core")}))
        check(outputs[0] == outputs[1], "both separators produce identical AST, checker and Core dumps")
        check("Arg name=a" in outputs[1][0], "equals in a call remains a label")
        for name in ("named_args", "java_named_arg", "tail_block_named"):
            source = (ROOT / "scripts/checker-corpus/cases" / f"{name}.dawn").read_text()
            path.write_text(source)
            old = cli(args.dawn, "__check", path)
            hits = source_hits(args.java, args.jar, work, path)
            path.write_text(apply(source, hits))
            check(old == cli(args.dawn, "__check", path), f"{name}: diagnostics are separator-independent")
        for name, recovered in (("match_arm_recovery", 1), ("stmt_recovery_nested_brace", 2)):
            source = (ROOT / "scripts/grammar-corpus/reject" / f"{name}.dawn").read_text()
            path.write_text(source)
            rows = probe(args.java, args.jar, work, [path])
            check(len({int(row[3]) for row in rows if row[0] == "R"}) == recovered,
                  f"{name}: diagnostic spans recover the research omissions")
            old = cli(args.dawn, "__parse", path)
            hits = source_hits(args.java, args.jar, work, path)
            path.write_text(apply(source, hits))
            check(old == cli(args.dawn, "__parse", path), f"{name}: recovery diagnostics are unchanged")
        for old, fresh in (("f(a:1)", "f(a: 1)"), ("f(a=1)", "f(a = 1)")):
            path.write_text("fn g() = " + old + "\n")
            cli(args.dawn, "fmt", path)
            expected = "fn g() = " + fresh + "\n"
            check(path.read_text() == expected, "formatter preserves the input separator")
            rewritten = expected.replace(":", "=") if ":" in expected else expected.replace(" = 1", ": 1")
            check(rewritten != expected, "negative control: separator rewriting is rejected")
    print("OK: named argument migration contract")


if __name__ == "__main__":
    main()
