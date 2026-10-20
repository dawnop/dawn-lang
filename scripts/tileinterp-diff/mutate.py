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
  unsupported-skipped  an instruction outside the subset (`mmaf`) passes the
                       static walk and execution skips it silently: the
                       package test that expects it refused by name must
                       fail, and so must the comparison.

Declared as a literal registry so mutation-anchor-preflight.py proves every
anchor matches exactly once before any build, as it does for every mutate.py
under scripts/.
"""

from pathlib import Path
import sys

INTERP = "packages/tileinterp/src/interp.dawn"

MUTATIONS = {
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
    "unsupported-skipped": ((
        INTERP,
        '  FloatMma(_d, _t, _lt, _rt, _l, _r, _a) -> Some("mmaf (matrix product is I2)")',
        '  FloatMma(_d, _t, _lt, _rt, _l, _r, _a) -> None',
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
