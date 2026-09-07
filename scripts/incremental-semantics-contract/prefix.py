#!/usr/bin/env python3
"""Compare warm sessions with the frozen cold loop and prove real cache hits.

Each mutation is built before either owning assertion is evaluated. Runtime
linkage errors and timeouts never substitute for a cache-contract failure.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from cold import ROOT, HERE, OWNER, edit, run


def owning_assertion(output):
    return bool(re.search(
        r"^FAIL\s+prefix :: prefix cache [^\n]*\n\s+assertion failed:", output, re.M))


def main():
    assert owning_assertion("FAIL  prefix :: prefix cache control\n      assertion failed: expected hit\n")
    assert not owning_assertion("FAIL  prefix :: prefix cache control\n      NoSuchMethodError\n")
    assert not owning_assertion("FAIL  elsewhere :: prefix cache control\n      assertion failed: x\n")
    reference = (HERE / "reference-tests.dawn.txt").read_text()
    reference = edit(reference, "use std/io\n",
                     "use std/io\nuse compiler/driver/incremental\n")
    reference = edit(reference, "use compiler/check/jsig.{jsig_refused}",
                     "use compiler/check/jsig.{jsig_refused, refused_probe}")
    reference = edit(reference, "    for loaded in cases {\n      for opts in [ct_default(), ct_fuel(0)] {",
                     "    for opts in [ct_default(), ct_fuel(0)] {\n"
                     "      var owner = incremental.new(std, opts, jsig_refused(), refused_probe, 100, 100000)\n"
                     "      for loaded in cases {")
    reference = edit(reference,
                     "        let current = analyze_program(loaded, std, opts, jsig_refused())",
                     "        let first = incremental.analyze(owner, loaded)\n"
                     "        let warm = incremental.analyze(first.session, loaded)\n"
                     "        owner = warm.session\n"
                     "        let current = warm.program")
    reference = edit(reference,
                     "    let current = analyze_program(loaded, std, ct_default(), jsig_refused())",
                     "    let owner = incremental.new(std, ct_default(), jsig_refused(), refused_probe, 100, 100000)\n"
                     "    let first = incremental.analyze(owner, loaded)\n"
                     "    let current = incremental.analyze(first.session, loaded).program")
    original = (ROOT / "selfhost/src/driver/incremental.dawn").read_text()
    variants = [
        ("always-cold", "    let hit = matching &&", "    let hit = false &&"),
        ("text-only", "a == b", "a.text == b.text"),
        ("resume-suffix", "      matching = false\n", "      ()\n"),
        ("cache-errors", "len(computed.diags) != 0 || ", ""),
        ("cache-java", " || probe.queries() != queries_before", ""),
        ("ignore-loader", "len(loaded.diags) == 0 && ", ""),
        ("ignore-ffi", "not session.opts.ffi", "true"),
        ("ignore-eviction", "  State { ..session, prefix: [] }", "  session"),
        ("ignore-module-budget", "len(prefix) < session.max_modules", "true"),
        ("ignore-text-budget", "units <= session.max_text_units - text_units", "true"),
        ("ignore-std-identity", "identity == session.prefix[index].std_identity", "true"),
        ("allow-negative-budget",
         '  if max_modules < 0 || max_text_units < 0 { panic("negative analysis cache limit") }',
         "  ()"),
    ]
    subjects = [("positive", original)] + [(name, edit(original, old, new)) for name, old, new in variants]
    with tempfile.TemporaryDirectory(prefix="dawn-prefix-reference-") as temp:
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
        (fixture / "src/reference.dawn").write_text(reference)
        driver = root / "selfhost/src/driver/analyze.dawn"
        driver.write_text(driver.read_text() + "\n" + (HERE / "reference-loop.dawn.txt").read_text())
        for name, source in subjects:
            (root / "selfhost/src/driver/incremental.dawn").write_text(source)
            status, output = run("build", fixture, "-o", root / "subject.jar")
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                     str(oracle) + os.pathsep + str(root / "subject.jar"),
                                     "contract.SemanticSnapshot"], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            semantic_failure = result.returncode and re.search(
                r"^FAIL\s+reference :: " + re.escape(OWNER), result.stdout, re.M)
            if result.returncode and not semantic_failure:
                raise RuntimeError(f"{name} oracle execution failed\n{result.stdout}")
            status, output = run("test", fixture)
            count_failure = status and owning_assertion(output)
            if name == "positive":
                if result.returncode or status:
                    raise RuntimeError(f"positive failed\n{result.stdout}\n{output}")
            elif not semantic_failure and not count_failure:
                raise RuntimeError(f"{name} missed both owning assertions\n{result.stdout}\n{output}")
            print(f"OK: prefix {name}", flush=True)
    print(f"OK: full-product warm/cold reference and {len(variants)} compiling cache mutants")


if __name__ == "__main__":
    main()
