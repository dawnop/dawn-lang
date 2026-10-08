#!/usr/bin/env python3
"""Apply one reuse mutation to a copy of the repository tree.

    scripts/adt-reuse-contract/mutate.py <mutation> <tree-root>

Each mutation takes away one thing that makes reset/reuse correct or useful
(selfhost/src/c/rc.dawn, emitc.dawn):

  pairing-off           the sweep never turns a release into a reset. Every
                        answer is unchanged; only the allocation count moves.
  reuse-leaks-the-token the emitter hands the reuse a second reference to the
                        token, so the built node is never released.
  reset-keeps-the-slot  the emitter reads the binding instead of taking it, so
                        the frame still releases a node the reset consumed.
  reuse-across-loops    a token made outside a loop may be spent inside it,
                        which the oracle's loop rule refuses.

`reset-ignores-sharing` is a runtime mutation and lives in
scripts/rc-contract/mutate.py, which run.sh applies to a copy of runtime/c.

The registry shape is the one mutation-anchor-preflight.py discovers.
"""

from pathlib import Path
import sys

MUTATIONS = {
    "pairing-off": ((
        "selfhost/src/c/rc.dawn",
        "Some(ty) -> if map.get(want, adt_id(ty)).unwrap_or(0) > 0 { Some(ty) } else { None }",
        "Some(ty) -> if false { Some(ty) } else { None }",
    ),),
    "reuse-leaks-the-token": ((
        "selfhost/src/c/emitc.dawn",
        """(stt, "dawn_adt_reuse(" ++ tv ++ ", " """,
        """(stt, "dawn_adt_reuse(dawn_dup(" ++ tv ++ "), " """,
    ),),
    "reset-keeps-the-slot": ((
        "selfhost/src/c/emitc.dawn",
        """    CReset(inner, _) -> {
      let (st1, v) = emit_expr(st, inner, true)""",
        """    CReset(inner, _) -> {
      let (st1, v) = emit_expr(st, inner, false)""",
    ),),
    "reuse-across-loops": ((
        "selfhost/src/c/rc.dawn",
        "Some(aid) -> if aid == adt && transferable(st, sym, after) { return Some(sym) }",
        "Some(aid) -> if aid == adt { return Some(sym) }",
    ),),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor drifted ({count} matches in {rel})")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
