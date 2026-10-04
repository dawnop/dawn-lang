#!/usr/bin/env python3
"""Every historical defect core lint answers for turns its owning check red.

    ./scripts/core-lint-contract/run.py                 # both groups
    ./scripts/core-lint-contract/run.py --only static   # or --only lint

Why this harness exists. The core-lint plan (docs/core-lint-design.md) names
eleven defects from the 2026-10 bug corpus and says which check catches each.
A check that has never been seen red is a claim, not a check, so every one is
put back by mutate.py beside this file, in a private copy of the tree, and the
named check has to fail on it in its own words:

  static-*  the owning Dawn test (`dawn test <file>`, `FAIL <module> :: <test>`)
            or scripts/intrinsic-parity.py run inside the copy. No program.
  lint-*    a compiler built from the copy compiles the defect's repro program
            with DAWN_CORE_LINT=1 on both backends (`__emit` and `__emitc`) and
            panics naming the rule. The same compiler without the switch has to
            accept the program, which is what makes the defect a defect: it is
            the checker's acceptance the lint moves from run time to compile
            time.

The positive controls run first, on an unmutated copy: every owning test
passes, the parity script passes, and the unmutated compiler compiles every
repro that is a valid program with the lint on and reports nothing. Without
them a red mutant could be a harness that is always red.

Wall clock is a few minutes (one compiler build per lint mutant, about ten
seconds each here, and one `dawn test` per static owner); it is not a push
gate. The anchors are proven exactly-once by mutation-anchor-preflight.py,
which is cheap and runs in tree-policy.
"""

import argparse
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts/core-lint-contract"
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin/dawn"))
SPIKE = ROOT / "scripts/spike-native"

# static mutant -> (kind, file or script, owner test name or expected text)
STATIC = {
    "static-69691c36": ("test", "selfhost/src/c/emitc.dawn",
                        "every scalar relation the emitter names is one the runtime defines"),
    "static-87": ("test", "selfhost/src/check/types.dawn",
                  "every function value the checker admits has an interface to be called through"),
    "static-182": ("test", "selfhost/src/jvm/emit.dawn",
                   "a lowered list longer than the declared one is reported, not dropped"),
    "static-185-arm": ("parity", "scripts/intrinsic-parity.py",
                       "call_builtin has an arm for `parse_float`, which interp_arms() does not list"),
    "static-185-listed": ("test", "selfhost/src/ir/interp.dawn",
                          "the comptime interpreter covers every intrinsic, removes it in lowering, or refuses it"),
    "static-205": ("test", "selfhost/src/jvm/emit.dawn",
                   "every runtime method the JVM emitter can call is one rtclasses generates"),
    "static-283": ("test", "selfhost/src/ir/lower.dawn",
                   "a builtin taken as a value lowers as the call it wraps"),
}

# lint mutant -> (repro program, the rule the lint has to name)
LINT = {
    "lint-13": (SPIKE / "cond_impl_module", "dict-arity"),
    "lint-43": (HERE / "local_label.dawn", "evidence-row"),
    "lint-54": (HERE / "local_variable.dawn", "evidence-row"),
    "lint-144": (HERE / "nested_list_eq.dawn", "dict-arity"),
    "lint-5f91c188": (SPIKE / "effect_assoc_row.dawn", "evidence-slot"),
}

# repros that are refused by the unmutated checker: the defect they show is
# the checker accepting them, so the positive control expects the refusal
REFUSED_ON_HEAD = {"lint-43", "lint-54"}


def run(cmd, cwd=ROOT, env=None, timeout=900):
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)


def copy_tree(dest: Path) -> None:
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(ROOT / directory, dest / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
    for link in ("packages", "std"):
        (dest / link).symlink_to(ROOT / link, target_is_directory=True)
    (dest / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/intrinsic-parity.py", dest / "scripts/intrinsic-parity.py")


def module_of(rel: str) -> str:
    return rel.removeprefix("selfhost/src/").removesuffix(".dawn")


def probe_static(tree: Path, kind: str, target: str):
    if kind == "parity":
        return run([sys.executable, str(tree / target)])
    return run([DAWN, "test", str(tree / target)])


def static_red(name: str, kind: str, target: str, owner: str, result) -> bool:
    if result.returncode == 0:
        return False
    if kind == "parity":
        return owner in result.stdout
    if re.search(r"^error:", result.stdout, re.M):
        return False  # a mutant that does not compile proves nothing
    # a single-module run prints the bare test name, a run that tested its
    # imports too prefixes the module
    return re.search(r"^FAIL\s+(?:" + re.escape(module_of(target)) + r" :: )?" + re.escape(owner) + r"$",
                     result.stdout, re.M) is not None


def build(tree: Path, jar: Path) -> None:
    result = run([DAWN, "build", str(tree / "selfhost"), "-o", str(jar)])
    if result.returncode != 0:
        raise SystemExit(f"FAIL: could not build {jar.name}\n{result.stdout}")


def compile_with(jar: Path, backend: str, prog: Path, out: Path, lint: bool):
    env = dict(os.environ)
    env.pop("DAWN_CORE_LINT", None)
    if lint:
        env["DAWN_CORE_LINT"] = "1"
    mode = "__emit" if backend == "jvm" else "__emitc"
    target = out / (prog.name + (".classes" if backend == "jvm" else ".c"))
    return run(["java", "-Xss512m", "-Xmx2g", "-jar", str(jar), mode, str(prog), "-o", str(target)],
               env=env, timeout=300)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=["static", "lint"])
    args = parser.parse_args()
    started = time.monotonic()
    mutations = runpy.run_path(str(HERE / "mutate.py"))
    registry = mutations["MUTATIONS"]
    apply = mutations["apply"]
    missing = set(registry) ^ (set(STATIC) | set(LINT))
    if missing:
        raise SystemExit(f"FAIL: mutate.py and run.py disagree about {sorted(missing)}")
    failures = []
    with tempfile.TemporaryDirectory(prefix="dawn-core-lint-") as temp:
        temp = Path(temp)
        head = temp / "head"
        copy_tree(head)
        if args.only in (None, "static"):
            for probe in sorted({(k, t) for k, t, _ in STATIC.values()}):
                result = probe_static(head, *probe)
                if result.returncode != 0:
                    raise SystemExit(f"FAIL: positive control {probe} is red on HEAD\n{result.stdout}")
                print(f"OK: positive control {probe[1]}", flush=True)
            for name, (kind, target, owner) in STATIC.items():
                tree = temp / name
                copy_tree(tree)
                apply(name, tree)
                result = probe_static(tree, kind, target)
                if static_red(name, kind, target, owner, result):
                    print(f"OK: {name} turns `{owner}` red", flush=True)
                else:
                    failures.append(f"{name}: `{owner}` did not go red\n{result.stdout[-3000:]}")
                shutil.rmtree(tree)
        if args.only in (None, "lint"):
            out = temp / "out"
            out.mkdir()
            head_jar = temp / "head.jar"
            build(head, head_jar)
            for name, (prog, rule) in LINT.items():
                for backend in ("jvm", "c"):
                    result = compile_with(head_jar, backend, prog, out, True)
                    refused = name in REFUSED_ON_HEAD
                    ok = (result.returncode != 0 and "error:" in result.stdout) if refused \
                        else result.returncode == 0
                    if not ok or "core lint:" in result.stdout:
                        raise SystemExit(f"FAIL: positive control {prog.name} ({backend}) on HEAD\n"
                                         f"{result.stdout}")
                print(f"OK: positive control {prog.name} compiles lint-clean on HEAD"
                      + (" (refused by the checker, as fixed)" if name in REFUSED_ON_HEAD else ""),
                      flush=True)
            for name, (prog, rule) in LINT.items():
                tree = temp / name
                copy_tree(tree)
                apply(name, tree)
                jar = temp / f"{name}.jar"
                build(tree, jar)
                for backend in ("jvm", "c"):
                    plain = compile_with(jar, backend, prog, out, False)
                    linted = compile_with(jar, backend, prog, out, True)
                    accepted = "error:" not in plain.stdout and "core lint:" not in plain.stdout
                    named = linted.returncode != 0 and f"[{rule}]" in linted.stdout \
                        and "core lint:" in linted.stdout
                    if accepted and named:
                        print(f"OK: {name} ({backend}) compiles without the lint and is "
                              f"refused with it, naming [{rule}]", flush=True)
                    else:
                        failures.append(f"{name} ({backend}): accepted without lint={accepted}, "
                                        f"lint named [{rule}]={named}\n--- without\n"
                                        f"{plain.stdout[-2000:]}\n--- with\n{linted.stdout[-2000:]}")
                shutil.rmtree(tree)
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if failures:
        sys.exit(1)
    print(f"PASS  core-lint contract: {len(registry)} restored defects each red in their "
          f"owning check, {time.monotonic() - started:.0f}s")


if __name__ == "__main__":
    main()
