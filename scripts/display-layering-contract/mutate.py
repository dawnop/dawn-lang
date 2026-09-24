#!/usr/bin/env python3
"""Break one Display layering rule in a compiler tree copy.

Two mutations, one per rule `to_str` holds:

  drop-display-question  the Display question is not asked at all, so every
                         value renders through its Show.

  inherit-display        an opaque type with no Display of its own borrows one
                         from any layer below it, which is what the peel did
                         before 2026-09-24, when an opaque type still inherited
                         its target's rendering. It is the plausible wrong
                         answer now: the value renders, just not as its own
                         `Show` says.

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

TO_STR_MATCH = """    match t {
      TyVar(_, _) ->
        match wit {"""

# The old peel, as an arm of `to_str`: an opaque type asks every layer below
# it for a Display before it falls back to its own Show.
TO_STR_MATCH_INHERITING = """    match t {
      TyOpaque(_, _, _, _, tgt) ->
        if has_display_below(st, tgt) { to_str(st, e, tgt, wit) } else { show_at(st, e, t) }
      TyVar(_, _) ->
        match wit {"""

HAS_OWN_DISPLAY_DOC = "## Does `t` have a `Display` impl written on `t` itself?"

HAS_DISPLAY_BELOW = """fn has_display_below(st: LSt, t: Ty) -> Bool =
  if has_own_display(st, t) {
    true
  } else {
    match t {
      TyOpaque(_, _, _, _, tgt) -> has_display_below(st, tgt)
      _ -> false
    }
  }

"""


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
    elif mutation == "inherit-display":
        text = replace_once(
            text, TO_STR_MATCH, TO_STR_MATCH_INHERITING, mutation, "to_str match"
        )
        text = replace_once(
            text, HAS_OWN_DISPLAY_DOC, HAS_DISPLAY_BELOW + HAS_OWN_DISPLAY_DOC, mutation,
            "has_own_display doc comment"
        )
    else:
        raise SystemExit(f"unknown mutation: {mutation}")
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
