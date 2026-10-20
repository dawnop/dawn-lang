#!/usr/bin/env python3
"""Run each compiler on the Playground's starter programs and keep what it said.

    python3 scripts/xmap-samples/record.py --samples DIR

The Playground's online compile view (docs/playground-compile-design.md)
pairs a visitor's code with the C and bytecode it compiles to, and a click on
a call lights the lines that call wrote. Two side tables know the answer, one
per backend, and each is its compiler's to say, never guessed here:

  - C: `dawn __emitc --map`, which says for each call of the Dawn source the
    lines of the C text it wrote and the columns on the last of them.
  - JVM: `dawn __emit --map`, which says the pc range of each call's bytecode;
    the listing is `javap -c -p -s` of the class, whose lines carry the pcs.

This script is the layer that *runs* them, and nothing else: the pairing is
packages/xmap's, so that the Playground's compile view, a Dawn process which
cannot start Python on a request, does it with the same code. What stays here
is what has to run a compiler and a JDK's `javap`: for each program one
directory holding `spec.txt` (what the program is: `packages/xmap`'s
`parse_spec` says the format), the C text (`out.c`), the two maps
(`c.dawnmap`, `jvm.dawnmap`) and the listing (`javap.txt`), plus
`programs.txt` naming the directories in order. scripts/xmap-samples/run.sh
holds each of them to a mapping with no gap.

This file began as site/explorer/record.py, the recorder of the static
explorer page, retired 2026-10-17 (docs/explorer-page-design.md); the page's
two programs and its Tile IR half went with it.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DAWN = os.environ.get("DAWN_BIN", str(ROOT / "bin" / "dawn"))

# The Playground's starter programs (site/play-ui/samples): the corpus the
# online compile view (docs/playground-compile-design.md) has to map with no
# gap.
#
# Every one of them. A sample that imports tileir is a project on the
# Playground (playground/src/play/exec.dawn's `wants_tileir` and
# `tile_manifest`): `src/main.dawn` beside a manifest whose only dependencies
# are packages/tileir, packages/tileref and packages/tileinterp, its module `main`. It is recorded
# the same way here, so the maps are the ones the Playground pairs. Until
# 2026-10-19 such a sample was left out, because xmap took the name of an
# infix operator on tiles (`a * b`, recorded as `impl mul` with its name at
# the `*`) for a gap (docs/playground-compile-design.md K8).
SAMPLES = [
    {"name": p.stem, "source": f"site/play-ui/samples/{p.name}"}
    for p in sorted((ROOT / "site" / "play-ui" / "samples").glob("*.dawn"))
]

# The text the Playground decides by, word for word (play/contract.dawn
# `wants_tileir`).
TILEIR_IMPORT = "use tileir/"


def fail(msg):
    print(f"scripts/xmap-samples/record.py: {msg}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=ROOT):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        fail(f"`{' '.join(str(c) for c in cmd)}` failed:\n" + (r.stderr + r.stdout)[-3000:])
    return r


def javap_binary():
    if os.environ.get("JAVAP"):
        return os.environ["JAVAP"]
    # the JDK bin/dawn runs on, found the way it finds it: an unmarked javap on
    # PATH may be another release, and its listing another format
    home = os.environ.get("JAVA_HOME", "")
    if not home:
        for pat in ("graalvm-*/Contents/Home", "graalvm-*"):
            hits = sorted((Path.home() / "tools").glob(pat))
            if hits:
                home = str(hits[0])
                break
    if home and (Path(home) / "bin" / "javap").exists():
        return str(Path(home) / "bin" / "javap")
    return "javap"


def target_of(prog, work):
    """The path `dawn __emitc/__emit` is given, and the module the code is in."""
    src = ROOT / prog["source"]
    if TILEIR_IMPORT in src.read_text(encoding="utf-8"):
        proj = work / "proj"
        (proj / "src").mkdir(parents=True)
        shutil.copy(src, proj / "src" / "main.dawn")
        packages = ROOT / "packages"
        (proj / "dawn.toml").write_text(
            f'schema = 1\nname = "tile"\nversion = "0.0.0"\n\n[deps]\n'
            f'tileir = "{packages}/tileir"\ntileref = "{packages}/tileref"\n'
            f'tileinterp = "{packages}/tileinterp"\n',
            encoding="utf-8",
        )
        return proj, "main"
    one = work / src.name
    shutil.copy(src, one)
    return one, src.stem


def write_raw(prog, outdir):
    """One program's directory: its spec and what the compilers said of it."""
    d = outdir / prog["name"]
    d.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="xmap-samples.") as w:
        work = Path(w)
        target, module = target_of(prog, work)
        run([DAWN, "__emitc", str(target), "-o", str(d / "out.c"), "--map", str(d / "c.dawnmap")])
        run([DAWN, "__emit", str(target), "-o", str(work / "classes"), "--map", str(d / "jvm.dawnmap")])
        listing = run([javap_binary(), "-c", "-p", "-s", str(work / "classes" / f"{module}.class")]).stdout
    (d / "javap.txt").write_text(listing, encoding="utf-8")
    spec = [f"source {prog['source']}", f"module {module}"]
    (d / "spec.txt").write_text("\n".join(spec) + "\n", encoding="utf-8")


def main_raw(out, progs):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    # each program is its own pair of compiler runs and its own directory, so
    # they go three at a time; the files and the order of programs.txt are the
    # same as one at a time
    with ThreadPoolExecutor(max_workers=3) as pool:
        for prog, _ in zip(progs, pool.map(lambda p: write_raw(p, out), progs)):
            print(f"xmap-samples: {prog['name']}: recorded")
    names = [p["name"] for p in progs]
    (out / "programs.txt").write_text("\n".join(names) + "\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--samples":
        main_raw(Path(args[1]), SAMPLES)
    else:
        fail("usage: record.py --samples DIR")


if __name__ == "__main__":
    main()
