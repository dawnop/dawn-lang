#!/usr/bin/env python3
"""The identity of what a layer-2 run tested: a digest of the tile inputs at a
revision, which run.sh writes into its ledger line as `inputs=<12 hex>` and
`run.sh --check` recomputes at HEAD.

Why a digest and not a commit. The ledger used to name the commit it ran and
the gate asked that commit to be an ancestor of HEAD with no tile path changed
since. main is linear now and every pull request is rebase-merged on GitHub,
which rewrites every SHA on the branch, so a recorded commit is never an
ancestor of what lands and that rule can only ever go red. What the gate
actually wants to know is "was this exact tile input run on a device", and the
content answers it on any history.

Read from git objects (`git ls-tree`, `git show <rev>:`) and never from the
working tree, so a CI checkout and the recording machine compute the same
answer for the same commit. The paths are TILE_PATHS below, every ledger in
scripts/tile-gpu-diff excluded (a line appended to one is a record of a run,
not a change to what ran), every Markdown file excluded (see DOC below), plus
the GPU section of runtime/c/dawn_rt.c between its markers.

    inputs.py [<rev>]   # print the digest of <rev> (default HEAD)
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# std/bytes.dawn is here because packages/tileir/src/bytecode.dawn builds every
# .tilebc with it: a change to its Buf is a change to the bytes the device is
# handed, whether or not any tile file moved (#493 measured the outputs the
# same when it last changed, which is a fact about that change, not a rule).
TILE_PATHS = ["packages/tileir", "packages/tileref", "std/bytes.dawn", "std/gpu.dawn", "std/narrow.dawn",
              "scripts/tile-golden", "scripts/tile-gpu-diff"]
LEDGER = re.compile(r"^scripts/tile-gpu-diff/ledger(-[^/]*)?\.txt$")
# Documentation is not a tile input. No build, golden or layer-2 program reads
# a `.md` file under TILE_PATHS (today packages/tileir/README.md and
# packages/tileref/README.md), so a README edit changes nothing a device ran,
# yet it used to move the digest and turn `run.sh --check` red until someone
# re-ran layer 2 on a GPU. PR #365 was the case: a README-only rewrite of
# packages/tileir's module table left CI green and the tile workflow red.
# Everything else under TILE_PATHS, toolchain.txt included, still counts.
DOC = re.compile(r"\.md$")
BEGIN, END = "=== DAWN_RT_GPU_BEGIN ===", "=== DAWN_RT_GPU_END ==="


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def gpu_section(rev):
    text = git("show", f"{rev}:runtime/c/dawn_rt.c")
    if BEGIN not in text or END not in text:
        raise SystemExit(f"inputs.py: runtime/c/dawn_rt.c at {rev} lacks the GPU section markers")
    return text[text.index(BEGIN):text.index(END)]


def digest(rev="HEAD"):
    entries = []
    for line in git("ls-tree", "-r", "--full-tree", rev, "--", *TILE_PATHS).splitlines():
        meta, path = line.split("\t", 1)
        if not LEDGER.match(path) and not DOC.search(path):
            entries.append(f"{meta}\t{path}")
    if not entries:
        raise SystemExit(f"inputs.py: no tile path exists at {rev}")
    h = hashlib.sha256()
    h.update("\n".join(sorted(entries)).encode())
    h.update(b"\n--- runtime/c/dawn_rt.c GPU section ---\n")
    h.update(gpu_section(rev).encode())
    return h.hexdigest()[:12]


if __name__ == "__main__":
    print(digest(sys.argv[1] if len(sys.argv) > 1 else "HEAD"))
