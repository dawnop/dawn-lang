#!/usr/bin/env python3
"""Run each compiler on the explorer page's programs and keep what it said.

    python3 site/explorer/record.py                  # write site/build/explorer/
    python3 site/explorer/record.py --out DIR        # write DIR (site-dist-diff's snapshot)
    python3 site/explorer/record.py --samples DIR     # the Playground's starter programs instead

The explorer page (site/src/gen/explorer.dawn, docs/explorer-page-design.md)
puts a program's Dawn source beside the output it compiles to, and a click on
a call lights the lines that call wrote. Three side tables know the answer,
one per backend, and each is its compiler's to say, never guessed here:

  - Tile IR: packages/tileir's recording of the kernel's calls, already
    checked into site/gpu-map/flash_attn.map (site/gpu-map/record.py keeps it
    honest). The page reads it directly, with the golden Tile IR text.
  - C: `dawn __emitc --map`, which says for each call of the Dawn source the
    lines of the C text it wrote and the columns on the last of them.
  - JVM: `dawn __emit --map`, which says the pc range of each call's bytecode;
    the listing is `javap -c -p -s` of the class, whose lines carry the pcs.

This script is the layer that *runs* them, and nothing else. It used to turn
the three into the page's own format and check the result (a Python
assembly, 648 lines, retired by the commit that wrote this); that job is
packages/xmap's now, so that the Playground's online compile view, a Dawn
process which cannot start Python on a request, does the same pairing with
the same code. What stays here is what has to run a compiler and a JDK's
`javap`: for each program one directory holding `spec.txt` (what the program
is: `packages/xmap`'s `parse_spec` says the format), the C text (`out.c`), the
two maps (`c.dawnmap`, `jvm.dawnmap`) and the listing (`javap.txt`), plus
`programs.txt` naming the directories in the order the page shows them.

It writes into site/build/explorer/, which is generated and not tracked: the C
and the bytecode are the compiler's function, so a checked-in copy would go
stale at the next change to the compiler, and a page showing the C of last
week's compiler is worse than a build that fails. site/build.sh runs this on
every build; scripts/site-dist-diff.sh runs it into its snapshot.
`--samples DIR` records the Playground's starter programs instead of the
page's, the same way: not for the page but for scripts/xmap-samples/run.sh,
which holds each of them to a mapping with no gap.
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
OUT = ROOT / "site" / "build" / "explorer"
TILE_MAP = ROOT / "site" / "gpu-map" / "flash_attn.map"
GOLDEN = ROOT / "scripts" / "tile-golden" / "flash_attn.mlir"

# One entry per program on the page, in the order the page shows them.
#   name    the page's section and the program's directory
#   source  the Dawn file shown, relative to the repository root
#   fn      the function the page shows (None: the whole file)
#   kernel  True: scripts/tile-golden/kernels.dawn's project (its tileir and
#           tileref deps, module `main`) with a Tile IR recording; False: a
#           single file whose module is its stem
PROGRAMS = [
    {"name": "flash_attn", "source": "scripts/tile-golden/kernels.dawn", "fn": "flash_attn", "kernel": True},
    {"name": "attend", "source": "site/explorer/attend.dawn", "fn": None, "kernel": False},
]

# The Playground's starter programs (site/play-ui/samples): not on the page,
# but the corpus the online compile view (docs/playground-compile-design.md)
# has to map with no gap.
SAMPLES = [
    {"name": p.stem, "source": f"site/play-ui/samples/{p.name}", "fn": None, "kernel": False}
    for p in sorted((ROOT / "site" / "play-ui" / "samples").glob("*.dawn"))
]


def fail(msg):
    print(f"site/explorer/record.py: {msg}", file=sys.stderr)
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
    """The path `dawn __emitc/__emit` is given, and the module the page's code is in."""
    src = ROOT / prog["source"]
    if prog["kernel"]:
        proj = work / "project"
        (proj / "src").mkdir(parents=True)
        shutil.copy(src, proj / "src" / "main.dawn")
        (proj / "dawn.toml").write_text(
            "schema = 1\nname = \"xp_kernels\"\n\n[deps]\n"
            f"tileir = \"{ROOT / 'packages' / 'tileir'}\"\n"
            f"tileref = \"{ROOT / 'packages' / 'tileref'}\"\n", encoding="utf-8")
        return proj, "main"
    one = work / src.name
    shutil.copy(src, one)
    return one, src.stem


def write_raw(prog, outdir):
    """One program's directory: its spec and what the compilers said of it."""
    d = outdir / prog["name"]
    d.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="explorer.") as w:
        work = Path(w)
        target, module = target_of(prog, work)
        run([DAWN, "__emitc", str(target), "-o", str(d / "out.c"), "--map", str(d / "c.dawnmap")])
        run([DAWN, "__emit", str(target), "-o", str(work / "classes"), "--map", str(d / "jvm.dawnmap")])
        listing = run([javap_binary(), "-c", "-p", "-s", str(work / "classes" / f"{module}.class")]).stdout
    (d / "javap.txt").write_text(listing, encoding="utf-8")
    spec = [f"source {prog['source']}", f"module {module}"]
    if prog["fn"]:
        spec.append(f"fn {prog['fn']}")
    if prog["kernel"]:
        spec += [f"tile-map {TILE_MAP.relative_to(ROOT)}", f"tile-golden {GOLDEN.relative_to(ROOT)}"]
    (d / "spec.txt").write_text("\n".join(spec) + "\n", encoding="utf-8")


def main_raw(out, programs=None):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    progs = programs or PROGRAMS
    # each program is its own pair of compiler runs and its own directory, so
    # they go three at a time; the files and the order of programs.txt are the
    # same as one at a time
    with ThreadPoolExecutor(max_workers=3) as pool:
        for prog, _ in zip(progs, pool.map(lambda p: write_raw(p, out), progs)):
            print(f"explorer: {prog['name']}: recorded")
    names = [p["name"] for p in progs]
    (out / "programs.txt").write_text("\n".join(names) + "\n", encoding="utf-8")


def main():
    args = sys.argv[1:]
    if args == []:
        main_raw(OUT)
    elif len(args) == 2 and args[0] == "--out":
        main_raw(Path(args[1]))
    elif len(args) == 2 and args[0] == "--samples":
        main_raw(Path(args[1]), SAMPLES)
    else:
        fail("usage: record.py [--out DIR | --samples DIR]")


if __name__ == "__main__":
    main()
