#!/usr/bin/env python3
"""Build the "interpreter against tileref" program: every layer-2 family of
scripts/tile-gpu-diff, copied into one Dawn project with the device swapped.

Why one project and not one per family. Each family program is a few hundred
lines, but each one pulls in packages/tileir, packages/tileref,
packages/tileinterp and scripts/tile-golden/kernels.dawn (about 40,000 lines
together). Compiled once, the whole run is one compile and one JVM per family;
compiled per family it would be two dozen compiles of the same 40,000 lines.

Why text substitution and not a fork of the programs. The point of the
comparison is that the interpreter is judged by the corpus, the reference and
the tier the GPU is judged by. A fork would drift; three mechanical
substitutions per file cannot:

  * `with_gpu_real(` becomes `interp_gpu_real(` (glue.dawn), and the name
    leaves the `std/gpu` import;
  * `args()` becomes `placeholder_args(N)`, N being the number of cubins
    scripts/tile-gpu-diff/run.sh hands that family (read from run.sh's own
    arrays, so a kernel added there is a path added here);
  * `pub fn main()` becomes `pub fn family_main()`, called by a generated
    dispatcher `main` that takes the family's name.

Families whose every kernel is outside subset A are not built (atomics,
module globals with symbol lookup, the architecture-gated fp8/fp4 family):
they would run nothing but refusals.

    build.py --out <dir> [--interp <packages/tileinterp copy>]

prints one line per family, `<family> <module> <cubin count>`, which run.sh
reads.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIFF = ROOT / "scripts" / "tile-gpu-diff"
GOLDEN = ROOT / "scripts" / "tile-golden"
HERE = Path(__file__).resolve().parent

# family name, harness file, the run.sh array whose length is its cubin count
# (or a literal count)
FAMILIES = [
    ("vadd", "vadd_diff.dawn", "usage"),
    ("mask", "mask_diff.dawn", "masked"),
    ("red", "red_diff.dawn", "reduced"),
    ("mm", "mm_diff.dawn", "twod"),
    ("stride", "stride_diff.dawn", "strided"),
    ("int", "int_diff.dawn", "integers"),
    ("wide", "wide_diff.dawn", "wide"),
    ("gath", "gath_diff.dawn", "gathered"),
    ("scan", "scan_diff.dawn", "scanned"),
    ("erf", "erf_diff.dawn", "erfs"),
    ("trig", "trig_diff.dawn", "trigs"),
    ("dtype", "dtype_diff.dawn", "dtypes"),
    ("bitwise", "bitwise_diff.dawn", "bitwise_kernels"),
    ("shift", "shift_diff.dawn", "shift_kernels"),
    ("staged", "staged_if_diff.dawn", "staged_kernels"),
    ("loop", "loop_diff.dawn", "loops"),
    ("assert", "assert_diff.dawn", "dbg"),
    ("shape", "shape_diff.dawn", "shaped"),
    ("attr", "attr_diff.dawn", "attrs"),
    ("global", "global_diff.dawn", "globals_"),
    ("alloca", "alloca_diff.dawn", "allocas"),
    ("view", "view_diff.dawn", "view_order"),
    ("dyn", "dyn_diff.dawn", "dyn_order"),
    ("gsview", "gsview_diff.dawn", "gsview_order"),
    ("hint", "hint_diff.dawn", "hint_order"),
    ("seq", "seq_diff.dawn", "seq_order"),
    ("scalar", "scalar_diff.dawn", "scalars"),
    # architecture-gated kernels (fp8, fp4, scaled mma): the card decides which
    # a cubin run can try, the interpreter has no card and tries all of them
    ("arch", "arch_diff.dawn", "arch_kernels"),
]

# families whose program takes `<kernel> <cubin>` pairs: the placeholder
# arguments name the run.sh array's kernels, each with a cubin path
NAMED = {"arch"}


def run_sh_arrays():
    """The `name=(...)` arrays of run.sh, `"${x[@]}"` references expanded."""
    text = (DIFF / "run.sh").read_text()
    arrays = {}
    for m in re.finditer(r"^([a-z_]+)=\((.*?)\)\s*$", text, re.M | re.S):
        name, body = m.group(1), m.group(2)
        body = re.sub(r"#[^\n]*", "", body)
        items = []
        for tok in body.split():
            ref = re.fullmatch(r'"\$\{([a-z_]+)\[@\]\}"', tok)
            if ref:
                items += arrays.get(ref.group(1), [])
            else:
                items.append(tok)
        arrays.setdefault(name, items)
    return arrays


def transform(src: str, n, path: str) -> str:
    out = src
    placeholder = f"named_args({json.dumps(n)})" if isinstance(n, list) else f"placeholder_args({n})"
    for old, new in (("with_gpu_real(", "interp_gpu_real("), ("args()", placeholder),
                     ("pub fn main() -> Unit !io", "pub fn family_main() -> Unit !io")):
        if old not in out:
            sys.exit(f"build.py: {path} has no `{old}`; the substitution it relies on is gone")
        out = out.replace(old, new)
    # the import of the real handler, now unused
    out = re.sub(r"(use std/gpu\.\{[^}]*?)\bwith_gpu_real,\s*", r"\1", out, count=1)
    if re.search(r"use std/gpu\.\{[^}]*\bwith_gpu_real\b", out):
        sys.exit(f"build.py: could not drop `with_gpu_real` from {path}'s std/gpu import")
    lines = out.split("\n")
    first_use = next(i for i, ln in enumerate(lines) if ln.startswith("use "))
    helper = "named_args" if "named_args(" in out else "placeholder_args"
    lines.insert(first_use, f"use glue.{{interp_gpu_real, {helper}}}")
    return "\n".join(lines)


def kernels_module() -> str:
    src = (GOLDEN / "kernels.dawn").read_text()
    for old, new in (("\nfn trace(name: String) -> TileProg", "\npub fn trace(name: String) -> TileProg"),
                     ("\npub fn main() -> Unit !io", "\npub fn golden_main() -> Unit !io")):
        if old not in src:
            sys.exit(f"build.py: scripts/tile-golden/kernels.dawn has no `{old.strip()}`")
        src = src.replace(old, new, 1)
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--interp", default=str(ROOT / "packages" / "tileinterp"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "src").mkdir(parents=True)
    arrays = run_sh_arrays()
    mods = []
    for fam, file, count in FAMILIES:
        if count == "usage":
            # the cubin count is whatever the driver's own usage line names
            # (vadd_diff grew a third when f32 buffers arrived; a literal here
            # went stale and the family died on its argument check)
            usage = re.search(r'usage: vadd_diff ([^"]*)"', (DIFF / file).read_text())
            n = len(re.findall(r"<[^>]*\.cubin>", usage.group(1))) if usage else 0
        else:
            n = count if isinstance(count, int) else len(arrays.get(count, []))
        if n == 0:
            sys.exit(f"build.py: run.sh has no array `{count}` for family {fam}")
        mod = file[:-len(".dawn")]
        arg = arrays[count] if fam in NAMED else n
        (out / "src" / file).write_text(transform((DIFF / file).read_text(), arg, str(DIFF / file)))
        mods.append((fam, mod, n))
    (out / "src" / "kernels.dawn").write_text(kernels_module())
    shutil.copy(HERE / "glue.dawn", out / "src" / "glue.dawn")
    uses = "\n".join(f"use {m}" for _f, m, _n in mods)
    arms = "\n".join(f'    ["{f}"] -> {m}.family_main()' for f, m, _n in mods)
    names = "|".join(f for f, _m, _n in mods)
    (out / "src" / "main.dawn").write_text(f"""# Generated by scripts/tileinterp-diff/build.py: one layer-2 family a run.
{uses}

pub fn main() -> Unit !io =
  match args() {{
{arms}
    _ -> panic("usage: tileinterp-diff <{names}>")
  }}
""")
    (out / "dawn.toml").write_text(f"""schema = 1
name = "tileinterp_diff"

[deps]
tileir = "{ROOT / 'packages' / 'tileir'}"
tileref = "{ROOT / 'packages' / 'tileref'}"
tileinterp = "{Path(a.interp).resolve()}"
""")
    for f, m, n in mods:
        print(f"{f} {m} {n}")


if __name__ == "__main__":
    main()
