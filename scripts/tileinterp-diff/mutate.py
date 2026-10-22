#!/usr/bin/env python3
"""Apply one of the interpreter's negative controls to a copy of the tree.

    scripts/tileinterp-diff/mutate.py <mutant> <tree-root>

Each mutant breaks packages/tileinterp the way the 2026-10-20 task sheet
names, and run.sh --selftest requires the named check to go red on it:

  mulf-adds            an element-wise operation computes the wrong thing
                       (`mulf` adds): the interpreter-against-tileref
                       comparison must fail.
  bounds-unchecked     the out-of-bounds check is gone: the package test that
                       stores past the end of a buffer must fail.
  unsupported-skipped  an instruction the interpreter does not model (a
                       fence) passes the static walk and execution skips it
                       silently: the package test that expects it refused by
                       name must fail, and so must the comparison.
  mma-drops-term       the f64 matrix product leaves the last term of k out:
                       the package test that checks every term must fail, and
                       so must the comparison.
  narrow-unrounded     a narrow-format result is not rounded into its format:
                       the package test of the rounded sums must fail, and so
                       must the comparison.
  fma-two-roundings    `fma` rounds the product before the add, in binary64 and
                       in the narrow formats: the package test of the fused
                       cases must fail.

Declared as a literal registry so mutation-anchor-preflight.py proves every
anchor matches exactly once before any build, as it does for every mutate.py
under scripts/.
"""

from pathlib import Path
import sys

INTERP = "packages/tileinterp/src/interp.dawn"
MMA = "packages/tileinterp/src/mma.dawn"
FORMATS = "packages/tileinterp/src/formats.dawn"

MUTATIONS = {
    "shift-ub-restored": ((
        INTERP,
        '  "shli" -> wrap(w, a << (b & (w - 1)))',
        '  "shli" -> if b < 0 || b >= w { if cx.ub { refuse_ub("shift_ub restored") } else { 0 } } else { wrap(w, a << b) }',
    ),),
    "mulf-adds": ((
        INTERP,
        '  "mulf" -> a * b\n',
        '  "mulf" -> a + b\n',
    ),),
    "bounds-unchecked": ((
        INTERP,
        'fn check_addr(cx: Cx, buf: Int, off: Int, what: String) -> Unit =\n  if off < 0 || off >= cx.lens[buf] {',
        'fn check_addr(cx: Cx, buf: Int, off: Int, what: String) -> Unit =\n  if false && (off < 0 || off >= cx.lens[buf]) {',
    ),),
    "mma-drops-term": ((
        MMA,
        '      list.fold(range(0, k), acc[idx], (s, p) => fma_f64(r[p], c[p], s))',
        '      list.fold(range(0, k - 1), acc[idx], (s, p) => fma_f64(r[p], c[p], s))',
    ),),
    "narrow-unrounded": ((
        FORMATS,
        'pub fn nearest(fmt: String, x: Float) -> Float = if fmt == "f64" { x } else { round_into(fmt, NearestEven, x) }',
        'pub fn nearest(fmt: String, x: Float) -> Float = x',
    ),),
    "fma-two-roundings": ((
        MMA,
        '    fma_f64(a, b, c)\n  } else {',
        '    a * b + c\n  } else {',
    ), (
        MMA,
        '    if is_finite(p) && is_finite(c) { nearest(fmt, add_odd(p, c)) } else { nearest(fmt, p + c) }',
        '    if is_finite(p) && is_finite(c) { nearest(fmt, add_odd(nearest(fmt, p), c)) } else { nearest(fmt, p + c) }',
    )),
    "unsupported-skipped": ((
        INTERP,
        '  TokenOnlyTile(_t, op, _ti) -> Some("${op} (fences and PDL are not interpreted: a sequential run cannot check them)")',
        '  TokenOnlyTile(_t, op, _ti) -> None',
    ), (
        INTERP,
        '  _ -> internal("instruction ${mnemonic(i)} passed the static walk")',
        '  _ -> (env, Fell)',
    )),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutant> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique ({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
