#!/usr/bin/env python3
"""Require each broken static contract to fail its owning executed test.

Each mutant compiler must build and start successfully. A parse, bootstrap
or test-compilation failure is not a semantic kill. Source strings keep the
new syntax outside the compiler's seed-readable bootstrap inputs.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

# mutate.py owns every exactly-once source edit below.
from mutate import MUTATIONS, apply

ROOT = Path(__file__).resolve().parents[2]
TEST = "selfhost/src/check/trait_capture_test.dawn"
PROBE = Path(__file__).with_name("subwitness.dawn")
OWNERS = {
    "erase-trait-binders": "trait Capture syntax retains arguments bounds and formatting",
    "erase-bound-arguments": "complete trait applications survive interface export and reload",
    "erase-projection-upper": "associated Item upper bounds are independent of subject captures",
    "erase-forwarded-application": "trait default forwards the declared complete application",
    "erase-default-environment": "trait default checks rigid environments at the definition",
    "ignore-subject-support": "impl application support and private Scope checks precede members",
    "ignore-item-upper": "associated Item upper bounds are independent of subject captures",
    "widen-invariant-arguments": "witness checking keeps Capture arguments invariant",
    "erase-associated-scope": "associated Mem bindings retain the impl Scope in exported metadata",
    "ignore-subwitness-support": "impl dependency checks retain subwitness and member type support",
}


def run(args, output, expected=0, env=None):
    start = time.monotonic()
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=900)
    output.write_text(result.stdout)
    if expected is not None and result.returncode != expected:
        raise RuntimeError(f"command exited {result.returncode}: {args}\n{result.stdout[-6000:]}")
    return result, time.monotonic() - start


def controls(out, names):
    env = {**os.environ, "DAWN_LAUNCHER_PRINT_JAVA": "1"}
    java = subprocess.check_output([ROOT / "bin/dawn"], cwd=ROOT, env=env, text=True).strip()
    jvm = [java, "-XX:-UsePerfData", "-Xss512m", "-Xmx2g", "-XX:+UseSerialGC", "-jar"]
    rows = []
    for name in names:
        work = out / name
        work.mkdir()
        tree = work / "tree"
        for part in ["selfhost", "compiler-plan", "std"]:
            shutil.copytree(ROOT / part, tree / part,
                ignore=shutil.ignore_patterns("build", ".dawn", "__pycache__"))
        (tree / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        apply(name, tree)
        jar = work / "compiler.jar"
        _, build_time = run([ROOT / "bin/dawn", "build", tree / "selfhost", "-o", jar], work / "build.log")
        run([*jvm, jar, "--version"], work / "version.log")
        if name == "ignore-subwitness-support":
            # This declaration has no other refusal. Removing the support
            # check must actually admit it, independently of diagnostic text.
            run([*jvm, jar, "check", PROBE], work / "subwitness.log")
        result, test_time = run([*jvm, jar, "test", tree / TEST], work / "test.log", expected=None)
        marker = "FAIL  check/trait_capture_test :: " + OWNERS[name]
        if result.returncode != 1 or marker not in result.stdout:
            raise RuntimeError(f"{name}: owning executed test did not fail:\n{result.stdout[-6000:]}")
        rows.append(dict(name=name, compiler_built=True, owning_test_failed=True,
            build_seconds=build_time, test_seconds=test_time))
        (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(f"PASS mutant {name}: compiler built, owning test red", flush=True)
        shutil.rmtree(tree)
    # Check the unmutated implementation after proving that the oracles fail.
    run([ROOT / "bin/dawn", "test", ROOT / TEST], out / "baseline.log")
    result, _ = run([ROOT / "bin/dawn", "check", PROBE], out / "subwitness-baseline.log", expected=1)
    if result.stdout.count("error:") != 1 or "impl subwitness support is not covered" not in result.stdout:
        raise RuntimeError("the subwitness probe must isolate exactly one contract refusal")
    print("PASS trait Capture contracts: unmutated tests green", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=tuple(MUTATIONS))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if set(OWNERS) != set(MUTATIONS):
        raise RuntimeError("each mutation must have exactly one owning test")
    with tempfile.TemporaryDirectory(prefix="trait-capture-contract-") as temporary:
        out = (args.out or Path(temporary)).resolve()
        out.mkdir(parents=True, exist_ok=True)
        controls(out, [args.only] if args.only else MUTATIONS)


if __name__ == "__main__":
    main()
