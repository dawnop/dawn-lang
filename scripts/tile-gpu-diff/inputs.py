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
not a change to what ran), plus the GPU section of runtime/c/dawn_rt.c between
its markers; that is the set the commit rule compared.

    inputs.py [<rev>]   # print the digest of <rev> (default HEAD)
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TILE_PATHS = ["packages/tileir", "std/gpu.dawn", "std/narrow.dawn", "scripts/tile-golden",
              "scripts/tile-gpu-diff"]
LEDGER = re.compile(r"^scripts/tile-gpu-diff/ledger(-[^/]*)?\.txt$")
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
        if not LEDGER.match(path):
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
