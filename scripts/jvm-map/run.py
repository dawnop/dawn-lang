#!/usr/bin/env python3
"""Each way of getting the JVM side table wrong turns its owning check red.

    ./scripts/jvm-map/run.py

check.py beside this file holds `__emit --map` to the classes it describes,
to javap's reading of them and to `__lower --sites`. A rule that has never
been seen red is a claim, so mutate.py puts back one defect per rule in a
private copy of the compiler, a jar is built from the copy, and the rule has
to fail on it in its own words:

  leak            check.py: "are not those written without it"
  no-compare      check.py: "without pcs (the labelled class differs)"
  inv-early       check.py: "not `invokestatic"
  hi-is-lo        check.py: "outside"
  absolute        check.py: "has no row"
  len-off         check.py: "its Code attribute"
  no-widen-check  check.py: "of main.trace:"

The mutants run check.py's corpus, kernels and dead cases (selfhost is the
slow one and adds no shape the three lack; kernels is the one with a method
ASM widened a jump in, which no-widen-check needs).

`check.py --self-test` runs first, then the positive control: a jar built
from an unmutated copy passes check.py, so a red mutant is not a harness that
is always red. Every mutant is also required to compile, since one that does
not proves nothing. One compiler build per mutant; it is not a push gate.
mutation-anchor-preflight.py proves every anchor in mutate.py matches exactly
once, on every push and without building anything.
"""

import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / "scripts" / "jvm-map"
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))

# (how the mutant is judged, the words its red has to say)
EXPECT = {
    "leak": ("check", "are not those written without it"),
    "no-compare": ("check", "without pcs (the labelled class differs)"),
    "inv-early": ("check", "not `invokestatic"),
    "hi-is-lo": ("check", "outside"),
    "absolute": ("check", "has no row"),
    "len-off": ("check", "its Code attribute"),
    "no-widen-check": ("check", "of main.trace:"),
}


def run(cmd, env=None, timeout=1800):
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)


def copy_tree(dest: Path) -> None:
    for directory in ("selfhost", "compiler-plan"):
        shutil.copytree(ROOT / directory, dest / directory,
                        ignore=shutil.ignore_patterns("build", ".dawn"))
    for link in ("packages", "std"):
        (dest / link).symlink_to(ROOT / link, target_is_directory=True)


def build(tree: Path, jar: Path) -> None:
    result = run([DAWN, "build", str(tree / "selfhost"), "-o", str(jar)])
    if result.returncode != 0:
        raise SystemExit(f"FAIL: could not build {jar.name}\n{result.stdout[-3000:]}")


def checked(jar: Path):
    env = dict(os.environ, DAWN_BIN=str(jar), DAWN_STD=str(ROOT / "std"))
    return run([sys.executable, str(HERE / "check.py"), "corpus", "kernels", "dead"], env=env)


def main() -> None:
    started = time.monotonic()
    mutations = runpy.run_path(str(HERE / "mutate.py"))
    registry, apply = mutations["MUTATIONS"], mutations["apply"]
    if set(registry) != set(EXPECT):
        raise SystemExit(f"FAIL: mutate.py and run.py disagree about {sorted(set(registry) ^ set(EXPECT))}")
    selftest = run([sys.executable, str(HERE / "check.py"), "--self-test"])
    if selftest.returncode != 0:
        raise SystemExit(f"FAIL: check.py --self-test\n{selftest.stdout[-3000:]}")
    print("OK: check.py --self-test, its bytecode rules red on hand-made wrong rows", flush=True)
    failures = []
    with tempfile.TemporaryDirectory(prefix="dawn-jvm-map-") as temp:
        temp = Path(temp)
        head = temp / "head"
        copy_tree(head)
        head_jar = temp / "head.jar"
        build(head, head_jar)
        positive = checked(head_jar)
        if positive.returncode != 0:
            raise SystemExit(f"FAIL: positive control: check.py is red on HEAD\n{positive.stdout[-3000:]}")
        print("OK: positive control, check.py passes on an unmutated compiler", flush=True)
        shutil.rmtree(head)
        for name, (how, words) in EXPECT.items():
            tree = temp / name
            copy_tree(tree)
            apply(name, tree)
            jar = temp / f"{name}.jar"
            build(tree, jar)
            result = checked(jar)
            if result.returncode != 0 and words in result.stdout:
                print(f"OK: {name} turns check.py red ({words})", flush=True)
            else:
                failures.append(f"{name}: did not fail with `{words}`\n{result.stdout[-3000:]}")
            shutil.rmtree(tree)
            jar.unlink()
    if failures:
        for f in failures:
            print("FAIL: " + f)
        sys.exit(1)
    print(f"OK: all {len(EXPECT)} mutants red ({time.monotonic() - started:.0f} s)")


if __name__ == "__main__":
    main()
