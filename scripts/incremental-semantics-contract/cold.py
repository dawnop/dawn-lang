#!/usr/bin/env python3
"""Check the extracted transition against the frozen pre-extraction loop.

Both receive the same loaded inputs and StdCtx in a private subject. The
reference shares unchanged low-level checker/stdlib helpers, but never calls
ModuleStep or the observed fold. Each mutant changes only the new path.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin/dawn"))
OWNER = "cold transition agrees with the frozen loop on full semantic products"


def run(*args):
    result = subprocess.run([DAWN, *map(str, args)], cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    return result.returncode, result.stdout


def edit(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"cold mutation anchor drifted: {old!r}")
    return text.replace(old, new)


def main():
    started = time.monotonic()
    original = (ROOT / "selfhost/src/driver/analyze.dawn").read_text()
    reference = (HERE / "reference-loop.dawn.txt").read_text()
    variants = [
        ("next-id", "    next_id: before.next_id,", "    next_id: std.next_id,"),
        ("impl-carry", "  var base_impls = before.impls\n", "  var base_impls = std.impls\n"),
        ("diagnostic-order", "    diags = diags ++ step.diags\n", "    diags = step.diags ++ diags\n"),
        ("skip-check", "  if not parse_failed {\n", "  if false {\n"),
        ("skip-comptime", "    if len(cx.diags) == 0 {\n", "    if false {\n"),
        ("std-baseline", "      Some(before) -> { base_impls = before }", "      Some(before) -> ()"),
    ]
    subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-cold-reference-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes),
                        str(HERE / "SemanticSnapshot.java")], check=True)
        oracle = root / "snapshot.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        fixture = root / "scripts/incremental-semantics-contract"
        shutil.copytree(HERE, fixture)
        (fixture / "src/reference.dawn").write_text((HERE / "reference-tests.dawn.txt").read_text())
        driver = root / "selfhost/src/driver/analyze.dawn"
        for name, source in subjects:
            driver.write_text(source + "\n" + reference)
            status, output = run("build", "--cp", oracle, fixture, "-o", root / "subject.jar")
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                     str(oracle) + os.pathsep + str(root / "subject.jar"),
                                     "contract.SemanticSnapshot"], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            status, output = result.returncode, result.stdout
            if name == "positive":
                if status or not re.search(r"^PASS\s+.*" + re.escape(OWNER), output, re.M):
                    raise RuntimeError(f"frozen-loop positive failed\n{output}")
            elif not status or not re.search(r"^FAIL\s+.*" + re.escape(OWNER), output, re.M):
                raise RuntimeError(f"{name} missed the frozen-loop assertion\n{output}")
            print(f"OK: frozen-loop {name}", flush=True)
    print(f"OK: full-product cold reference, 6 compiling mutants; elapsed={time.monotonic()-started:.2f}s")


if __name__ == "__main__":
    main()
