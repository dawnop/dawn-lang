#!/usr/bin/env python3
"""How many golden kernels the interpreter can cover in principle, and how many it does.

    scripts/tileinterp-diff/scan.py            # print the table
    scripts/tileinterp-diff/scan.py --check    # also fail if covered.txt names a kernel the scan says is out

The ceiling is read off scripts/tile-golden/*.mlir, the text of every recorded
kernel: a kernel is OUT when its text holds an instruction or a format the
interpreter refuses by name (the same list packages/tileinterp/src/interp.dawn
refuses: atomics, fences and PDL, alloca, globals, pointer casts, assert and
print, strided and gather views, f8E5M3FNU). Everything else is IN: the ceiling
the covered set is measured against.

Why this replaces the 2026-10-20 research scan. That scan decided "uses a narrow
format" with `\\b(f32|bf16|...)\\b`, and `tile<128xf32>` has no word boundary
between `x` and `f32` (both are word characters), so seven f32 kernels
slipped into the f64-and-integer subset (docs/tileinterp-design.md 5). Here the
element type is read from inside `tile<...>` and `ptr<...>` with a pattern
that anchors on the angle bracket and the `x` separator, and a self-test pins
the case that broke the old one.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "scripts" / "tile-golden"
HERE = Path(__file__).resolve().parent

# Instructions the interpreter refuses, by their dialect spelling.
OUT_OPS = [
    "atomic_rmw_tko", "atomic_cas_tko", "atomic_red_view_tko", "memory_fence", "gdc_wait", "gdc_launch_dependents",
    "alloca", "get_global", "ptr_to_int", "int_to_ptr", "ptr_to_ptr", "assert", "print_tko", "make_strided_view",
    "make_gather_scatter_view",
]
# Formats it refuses.
OUT_FORMATS = ["f8E5M3FNU"]

OP = re.compile(r"=\s*([a-z_0-9]+)\b|^\s*([a-z_0-9]+)\b", re.M)
ELEM = re.compile(r"(?:tile|ptr|tensor_view|partition_view)<(?:[0-9?]+x)*([A-Za-z0-9]+)")


def elems_in(text: str) -> set:
    """Element formats named in `tile<..>`, `ptr<..>`: the name after the last `x` of the dims."""
    out = set()
    for m in re.finditer(r"(?=(?:tile|ptr)<(?:[0-9?]+x)*([A-Za-z][A-Za-z0-9]*))", text):
        out.add(m.group(1))
    return out


def ops_in(text: str) -> set:
    ops = set()
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?:%[\w, %]+=\s*)?([a-z_][a-z_0-9]*)\b", line)
        if m:
            ops.add(m.group(1))
    return ops


def classify(name: str):
    text = (GOLDEN / f"{name}.mlir").read_text()
    ops = ops_in(text)
    why = sorted(o for o in OUT_OPS if any(op == o or op.startswith(o) for op in ops))
    why += sorted(f for f in OUT_FORMATS if f in elems_in(text))
    return why


def selftest() -> None:
    assert elems_in("%1 = ftof %0 : tile<128xf64> -> tile<128xf32>") == {"f64", "f32"}, "x-separated element"
    assert elems_in("entry @k(%a: tile<ptr<f8E5M3FNU>>, %b: tile<i32>)") == {"ptr", "f8E5M3FNU", "i32"}
    assert "f32" in elems_in("tile<32x1xf32>")
    assert ops_in("    %5 = atomic_rmw_tko x\n    return") >= {"atomic_rmw_tko", "return"}


def main() -> None:
    selftest()
    names = sorted(p.stem for p in GOLDEN.glob("*.mlir"))
    out, inn = {}, []
    for n in names:
        why = classify(n)
        if why:
            out[n] = why
        else:
            inn.append(n)
    covered = {ln.split()[0] for ln in (HERE / "covered.txt").read_text().splitlines()
               if ln.strip() and not ln.startswith("#")}
    ub = {ln.split()[0] for ln in (HERE / "expected-ub.txt").read_text().splitlines()
          if ln.strip() and not ln.startswith("#")}
    print(f"golden kernels {len(names)}")
    print(f"out of reach by construction {len(out)}: " + " ".join(sorted(out)))
    print(f"ceiling (everything else) {len(inn)}")
    print(f"covered {len(covered)}; expected UB {len(ub)}")
    rest = sorted(set(inn) - covered - ub)
    print(f"in the ceiling but not covered {len(rest)}: " + " ".join(rest))
    wrong = sorted(covered & set(out))
    print(f"covered but out by construction {len(wrong)}: " + " ".join(wrong))
    if "--check" in sys.argv and wrong:
        sys.exit(1)


if __name__ == "__main__":
    main()
