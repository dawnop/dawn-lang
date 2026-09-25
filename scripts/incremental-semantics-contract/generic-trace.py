#!/usr/bin/env python3
"""Trace actual replay of the original bounded generic class.

Instrument only a private checker copy to measure actual cold entries, and use
the existing independent structural oracle for every body/context comparison.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from cold import ROOT, HERE, install_probe, run


def main():
    started = time.monotonic()
    checker = (ROOT / "selfhost/src/check/checker.dawn").read_text()
    for name in ("check_fn", "check_fn_inferred", "check_const_init", "check_trait_default", "check_test"):
        checker, count = re.subn(r"(pub\(pkg\) fn " + name + r"\([^{}]*?!io = \{\n)",
                                 r"\1  GenericTrace.enter()\n", checker)
        if count != 1:
            raise RuntimeError("Generic trace canonical entry anchor drifted: " + name)
    checker = 'use java "contract.GenericTrace"\n' + checker
    with tempfile.TemporaryDirectory(prefix="dawn-generic-trace-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes),
                        str(HERE / "SemanticSnapshot.java"), str(HERE / "GenericTrace.java")], check=True)
        oracle = root / "trace.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory,
                            ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        (root / "selfhost/src/check/checker.dawn").write_text(checker)
        fixture = install_probe(root, {"reference": (HERE / "generic-trace.dawn.txt").read_text()})
        status, output = run("build", "--cp", oracle, fixture, "-o", root / "subject.jar")
        if status:
            raise RuntimeError("Generic trace failed to compile\n" + output)
        result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                 str(oracle) + os.pathsep + str(root / "subject.jar"),
                                 "contract.GenericTrace"], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        print(result.stdout, end="", flush=True)
        if result.returncode or "PASS: generic trace 4 bounded products, 12 full-body/context pairs" not in result.stdout:
            raise RuntimeError("Generic trace missed its original bounded workload oracle")
    print(f"OK: bounded generic production trace, {time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
