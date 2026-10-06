#!/usr/bin/env python3
"""Each way of getting a call site wrong turns its owning check red.

    ./scripts/core-sites/run.py

check.py beside this file holds Core's call sites to the parser's call nodes.
A rule that has never been seen red is a claim, so mutate.py puts back one
defect per rule in a private copy of the compiler, a jar is built from the
copy, and the rule has to fail on it in its own words:

  absolute       check.py fails with "is no call the parser sees" or "fall in
                 no function of the file" (doubled offsets land either inside
                 a checked kernel, which is the first, or past every function,
                 which is the second; which one shows depends on how large the
                 kernels are, so either one proves the mutant was detected)
  nlo            check.py fails with "has its name at"
  rc-drops-site  check.py fails with "has no site"
  dump-prints    the Core dump of the corpus (`__lower --dump`) differs from the
                 unmutated compiler's. This is the negative control for the
                 design's first hard criterion: a dump that printed sites is
                 what selfhost-core-diff.sh would report on every pure move.

The positive control runs first: a jar built from an unmutated copy passes
check.py, so a red mutant is not a harness that is always red. Every mutant
is also required to compile, since one that does not proves nothing.

Wall clock is a few minutes, one compiler build per mutant; it is not a push
gate. mutation-anchor-preflight.py proves every anchor in mutate.py matches
exactly once, on every push and without building anything.
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
HERE = ROOT / "scripts" / "core-sites"
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))

EXPECT = {
    "absolute": ("is no call the parser sees", "fall in no function of the file"),
    "nlo": ("has its name at",),
    "rc-drops-site": ("has no site",),
    "dump-prints": None,
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
    return run([sys.executable, str(HERE / "check.py")], env=env)


def dumped(jar: Path, out: Path) -> str:
    out.mkdir()
    result = run(["java", "-Xss512m", "-Xmx2g", "-jar", str(jar), "__lower", "--dump", str(out),
                  str(HERE / "corpus.dawn")], env=dict(os.environ, DAWN_STD=str(ROOT / "std")))
    if result.returncode != 0:
        raise SystemExit(f"FAIL: `__lower --dump` failed with {jar.name}\n{result.stdout[-3000:]}")
    return "".join(p.read_text(encoding="utf-8") for p in sorted(out.glob("*.core")))


def main() -> None:
    started = time.monotonic()
    mutations = runpy.run_path(str(HERE / "mutate.py"))
    registry, apply = mutations["MUTATIONS"], mutations["apply"]
    if set(registry) != set(EXPECT):
        raise SystemExit(f"FAIL: mutate.py and run.py disagree about {sorted(set(registry) ^ set(EXPECT))}")
    failures = []
    with tempfile.TemporaryDirectory(prefix="dawn-core-sites-") as temp:
        temp = Path(temp)
        head = temp / "head"
        copy_tree(head)
        head_jar = temp / "head.jar"
        build(head, head_jar)
        positive = checked(head_jar)
        if positive.returncode != 0:
            raise SystemExit(f"FAIL: positive control: check.py is red on HEAD\n{positive.stdout[-3000:]}")
        print("OK: positive control, check.py passes on an unmutated compiler", flush=True)
        head_dump = dumped(head_jar, temp / "head-dump")
        shutil.rmtree(head)
        for name, words in EXPECT.items():
            tree = temp / name
            copy_tree(tree)
            apply(name, tree)
            jar = temp / f"{name}.jar"
            build(tree, jar)
            if words is None:
                if dumped(jar, temp / f"{name}-dump") != head_dump:
                    print(f"OK: {name} changes the Core dump of the corpus", flush=True)
                else:
                    failures.append(f"{name}: the Core dump did not change")
            else:
                result = checked(jar)
                if result.returncode != 0 and any(w in result.stdout for w in words):
                    print(f"OK: {name} turns check.py red ({' | '.join(words)})", flush=True)
                else:
                    failures.append(f"{name}: check.py did not fail with `{' | '.join(words)}`\n{result.stdout[-3000:]}")
            shutil.rmtree(tree)
    if failures:
        for f in failures:
            print("FAIL: " + f)
        sys.exit(1)
    print(f"OK: all {len(EXPECT)} mutants red ({time.monotonic() - started:.0f} s)")


if __name__ == "__main__":
    main()
