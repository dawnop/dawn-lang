#!/usr/bin/env python3
"""Each way of getting the C side table wrong turns its owning check red.

    ./scripts/c-map/run.py

check.py beside this file holds `__emitc --map` to the C it describes and to
`__lower --sites`. A rule that has never been seen red is a claim, so
mutate.py puts back one defect per rule in a private copy of the compiler, a
jar is built from the copy, and the rule has to fail on it in its own words:

  text-leak         check.py: "is not the C written without it"
  no-claim          check.py: "has no place in the C"
  head-shift        check.py: "holds no"
  col-pad           check.py: "holds no"
  unit-off          check.py: "by the unit table, and that is another line"
  same-line-twin    `dawn test selfhost`, the emitter's `claim` test:
                    "two identical call texts on one line are claimed left to right"
  prefix-enclosing  check.py: "has no place in the C"

The mutants checked by check.py run its corpus and kernels cases (nmain is
the slow one and adds no shape the two lack). same-line-twin is an
equivalent mutant on every program the emitter compiles today, since it never
writes two identical call texts on one line; its red comes from the unit
test that drives `claim` with such a line, and the checker's rule for the
same shape is held red by `check.py --self-test`, which this script runs
first.

The positive control runs before the mutants: a jar built from an unmutated
copy passes check.py, so a red mutant is not a harness that is always red.
Every mutant is also required to compile, since one that does not proves
nothing. Wall clock is a few minutes, one compiler build per mutant; it is not
a push gate. mutation-anchor-preflight.py proves every anchor in mutate.py
matches exactly once, on every push and without building anything.
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
HERE = ROOT / "scripts" / "c-map"
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))

# (how the mutant is judged, the words its red has to say)
EXPECT = {
    "text-leak": ("check", "is not the C written without it"),
    "no-claim": ("check", "has no place in the C"),
    "head-shift": ("check", "holds no"),
    "col-pad": ("check", "holds no"),
    "unit-off": ("check", "by the unit table, and that is another line"),
    "same-line-twin": ("test", "two identical call texts on one line are claimed left to right"),
    "prefix-enclosing": ("check", "has no place in the C"),
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
    return run([sys.executable, str(HERE / "check.py"), "corpus", "kernels"], env=env)


def tested(jar: Path, tree: Path):
    env = dict(os.environ, DAWN_STD=str(ROOT / "std"))
    return run(["java", "-Xss512m", "-Xmx4g", "-jar", str(jar), "test", str(tree / "selfhost")], env=env)


def main() -> None:
    started = time.monotonic()
    mutations = runpy.run_path(str(HERE / "mutate.py"))
    registry, apply = mutations["MUTATIONS"], mutations["apply"]
    if set(registry) != set(EXPECT):
        raise SystemExit(f"FAIL: mutate.py and run.py disagree about {sorted(set(registry) ^ set(EXPECT))}")
    selftest = run([sys.executable, str(HERE / "check.py"), "--self-test"])
    if selftest.returncode != 0:
        raise SystemExit(f"FAIL: check.py --self-test\n{selftest.stdout[-3000:]}")
    print("OK: check.py --self-test, its occurrence rules red on hand-made wrong claims", flush=True)
    failures = []
    with tempfile.TemporaryDirectory(prefix="dawn-c-map-") as temp:
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
            result = checked(jar) if how == "check" else tested(jar, tree)
            if result.returncode != 0 and words in result.stdout:
                print(f"OK: {name} turns {'check.py' if how == 'check' else 'dawn test selfhost'} red ({words})",
                      flush=True)
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
