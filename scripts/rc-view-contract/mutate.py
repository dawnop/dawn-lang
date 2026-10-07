#!/usr/bin/env python3
"""Apply one view mutation to a copy of the repository tree.

    scripts/rc-view-contract/mutate.py <mutation> <tree-root>

Each mutation takes away one of the four things that make a borrowed view safe
(selfhost/src/c/views.dawn), so each of them has to turn the contract red:

  views-of-owned-roots   a view may be read out of an owned parameter too. The
                         parameter is in the ledger and can be handed away
                         while the view is still read (`-blind`: with the
                         balance oracle off).
  views-in-the-ledger    the rewrite counts a view like an owned binding and
                         releases it, though it never took a reference.
  views-in-the-frame     the emitter parks a view in the frame's own-slot
                         array, so the frame's cleanup releases it.
  elements-uncounted     an element read is no longer copied where its value
                         is kept. The emitter used to do it for every read;
                         the rewrite owns it now. The emitter refuses the
                         result on its own too, so there is no blind variant.

The registry shape is the one mutation-anchor-preflight.py discovers, so every
anchor is proved to match exactly once before any compiler is built.
"""

from pathlib import Path
import sys

# The balance oracle (`rc.rc_check`, run on every module the rewrite touches)
# refuses most of these at compile time, std included, long before the probe is
# emitted. That is the first net and each mutation is measured against it; the
# `-blind` variant takes the oracle away as well, so the sanitizer and the
# emitted text are shown to catch the same defect on their own.
BLIND = (
    "selfhost/src/c/rc.dawn",
    "  let bad = rc_check(out, modes)",
    "  let bad = list.take(rc_check(out, modes), 0)",
)

MUTATIONS = {
    "views-of-owned-roots": ((
        "selfhost/src/c/views.dawn",
        "if is_ref_ty(p.ty) && not mode_owned(p.mode) && not set.has(dicts, p.sym) &&",
        "if is_ref_ty(p.ty) && (not mode_owned(p.mode) || true) && not set.has(dicts, p.sym) &&",
    ),),
    "views-of-owned-roots-blind": ((
        "selfhost/src/c/views.dawn",
        "if is_ref_ty(p.ty) && not mode_owned(p.mode) && not set.has(dicts, p.sym) &&",
        "if is_ref_ty(p.ty) && (not mode_owned(p.mode) || true) && not set.has(dicts, p.sym) &&",
    ), BLIND),
    "views-in-the-ledger": ((
        "selfhost/src/c/rc.dawn",
        """      if set.has(st.views, sym) {
        let (st1, i1) = rw(st, init, false, after)
        (st1, [CSLet(sym, ty, i1)])""",
        """      if set.has(st.views, sym) {
        let (st1, i1) = rw(st, init, false, after)
        (bind(st1, sym), [CSLet(sym, ty, i1)])""",
    ),),
    "views-in-the-frame": ((
        "selfhost/src/c/emitc.dawn",
        "let own = is_ref_ty(ty) && not emit_dictish(init) && not set.has(st.views, sym)",
        "let own = is_ref_ty(ty) && not emit_dictish(init)",
    ),),
    "elements-uncounted": ((
        "selfhost/src/c/rc.dawn",
        """let node = if consume && name == "array_get" && is_ref_ty(ity) { CDup(call, ity) } else { call }""",
        """let node = call""",
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
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


if __name__ == "__main__":
    main()
