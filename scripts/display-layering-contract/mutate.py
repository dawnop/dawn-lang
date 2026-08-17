#!/usr/bin/env python3
"""Break one Display layering rule in a compiler tree copy.

Two mutations, one per rule the batch added to `to_str`:

  drop-display-question  the Display question is not asked at all, so every
                         value renders through the Show it did before.

  ask-display-once       the question is asked on the type as written and never
                         again while an opaque stack is peeled, which is the
                         `to_str` shape the design rejected (asking inside the
                         opaque arm instead of above it).

Both are anchored on exact text and refuse to run when the anchor drifts: a
mutation that silently applied to nothing would report a green mutant, which is
the failure mode a mutant harness exists to avoid.
"""

from pathlib import Path
import sys


LOWER = "selfhost/src/ir/lower.dawn"

DISPLAY_QUESTION = """  if has_own_display(st, t) {
    display_at(st, e, t)
  } else if t == TyString {
"""

NO_DISPLAY_QUESTION = """  if t == TyString {
"""

# `has_own_display` and `display_at` are left in place and become unreachable.
# Deleting them too would be a second, independent edit, and the rule under test
# is where the question is asked rather than whether the helpers exist.

OPAQUE_ARM = (
    "        if has_own_show(st, t) { show_at(st, e, t) }"
    " else { to_str(st, e, tgt, wit) }\n"
)

OPAQUE_ARM_ONCE = (
    "        if has_own_show(st, t) { show_at(st, e, t) }"
    " else { to_str_once(st, e, tgt, wit) }\n"
)

# `to_str` with the Display question removed, recursing into itself: reached only
# from the opaque arm, so the question is asked exactly once, on the type the
# call site wrote.
TO_STR_ONCE = """fn to_str_once(st: LSt, e: CExpr, t: Ty, wit: Option[WitRef]) -> (LSt, CExpr) =
  if t == TyString {
    (st, e)
  } else if t == TyUnit {
    (st, CStr("()"))
  } else {
    match t {
      TyOpaque(_, _, _, _, tgt) ->
        if has_own_show(st, t) { show_at(st, e, t) } else { to_str_once(st, e, tgt, wit) }
      TyVar(_, _) ->
        match wit {
          Some(w) -> {
            let (st1, d) = witness_value(st, w)
            show_through_dict(st1, d, e, t)
          }
          None -> show_at(st, e, t)
        }
      _ -> show_at(st, e, t)
    }
  }

"""

HAS_OWN_SHOW_DOC = "## Does `t` have a `Show` impl written on `t` itself"


def replace_once(text: str, old: str, new: str, mutation: str, what: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{mutation}: {what} anchor drifted ({count} matches)")
    return text.replace(old, new)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    path = root / LOWER
    text = path.read_text(encoding="utf-8")
    if mutation == "drop-display-question":
        text = replace_once(
            text, DISPLAY_QUESTION, NO_DISPLAY_QUESTION, mutation, "display question"
        )
    elif mutation == "ask-display-once":
        text = replace_once(
            text, OPAQUE_ARM, OPAQUE_ARM_ONCE, mutation, "opaque arm"
        )
        text = replace_once(
            text, HAS_OWN_SHOW_DOC, TO_STR_ONCE + HAS_OWN_SHOW_DOC, mutation,
            "has_own_show doc comment"
        )
    else:
        raise SystemExit(f"unknown mutation: {mutation}")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
