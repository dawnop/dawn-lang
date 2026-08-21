#!/usr/bin/env python3
"""Apply one list-element mutation to a copy of the compiler tree.

Each mutation removes or inverts exactly one sentence of the list literal's two
element forms (spec §4.11), and the harness then asserts which contracts go
red. A mutant must still compile and still answer `--version`: "the mutant did
not build" is not evidence about a rule.

Every anchor is matched exactly once. A rewrite of `check_list_elem` moves all
of them at once, and that has to be a loud failure rather than a mutation that
silently does nothing -- a no-op mutant is a gate that has stopped looking, and
it prints the same PASS as a gate that is working.
"""
from pathlib import Path
import sys

CHECKER = "selfhost/src/check/checker.dawn"
PARSER = "selfhost/src/front/parser.dawn"
LOWER = "selfhost/src/ir/lower.dawn"

# ---- the sentences, quoted once so a drift in any of them fails loudly ----

# a spread contributes the *item* type of its operand
SPREAD_ITEM = "        TyList(item) -> (cx1, item, TLESpread(tx))\n"

# ... and the operand is a list at all
SPREAD_LIST_CHECK = """        _ ->
          if is_errorish(t) {
            (cx1, TyError, TLESpread(tx))
          } else {
            (cerr_h(cx1, "`..` spreads a list, but this is " ++ ty_show(cx1.adts, t), lo, hi,
              "drop the `..` to make it one element"), TyError, TLESpread(tx))
          }
"""

# the element type crosses the `..` as a list of itself
SPREAD_EXPECTATION = """      let list_exp: Option[Ty] = match el_exp {
        Some(t) -> Some(TyList(t))
        None -> None
      }
"""

# a conditional element's body is checked at the element type
COND_EXPECTATION = """        let body_exp: Option[Ty] =
          if t != TyNever && is_concrete(cx1, t) { Some(t) } else { el_exp }
"""

# a conditional element's condition is a Bool
COND_BOOL = """        if ct != TyBool && not is_errorish(ct) {
          cx1 = cerr(cx1, "if condition must be Bool, got " ++ ty_show(cx1.adts, ct),
            e_lo(a.cond), e_hi(a.cond))
        }
"""

# an element form that needs an expectation is checked in the second round
NEEDS_EXPECTED_SPREAD = "    LeSpread(e, _, _) -> needs_expected(cx, e)\n"
NEEDS_EXPECTED_COND = """    LeIf(arms, _, _) -> {
      for a in arms {
        if not needs_expected(cx, if_body_value(a.body)) { return false }
      }
      true
    }
"""

# an else-less chain is one element form all the way down
CHAIN_RECURSION = """        Some(inner) ->
          match if_chain_arms(inner) {
            Some(rest) -> Some([here] ++ rest)
            None -> None
          }
"""

# a conditional element appends only when its arm is taken
COND_APPEND = """    let thn = CBlock([append_seg(sym, ty, one)], None, TyUnit)
    let (st3, rest) = lower_if_seg(st2, sym, ty, arms, k + 1)
    let els: Option[CExpr] = if len(rest) == 0 { None } else { Some(CBlock(rest, None, TyUnit)) }
    (st3, [CSIf(c, thn, els)])
"""


def replace_once(text: str, old: str, new: str, name: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{name}: mutation anchor drifted ({n} matches)")
    return text.replace(old, new)


# mutation -> (file, old, new)
MUTATIONS = {
    # 1: a spread's item type joins the element type.
    #
    # Aimed at the contribution alone, with the list check left standing. The
    # designed mutant dropped both, and that one also accepts `[1, ..5]` --
    # which is `spread-operand-list-check-dropped`'s owner, and an assertion
    # two counted mutants redden is owned by neither.
    "spread-item-type-not-joined": (
        CHECKER,
        SPREAD_ITEM,
        "        TyList(item) -> (cx1, TyNever, TLESpread(tx))\n",
    ),
    # 2: and the operand is a list at all.
    #
    # Aimed at the refusal alone, with the `TyList(item)` arm left standing.
    # Dropping the whole `match` -- the designed mutation -- makes every valid
    # spread contribute `List[T]` instead of `T`, which reddens
    # `spread_operand_gets_expectation` and `spread_defers_to_second_round`
    # too; the first of those is another mutant's owner.
    "spread-operand-list-check-dropped": (
        CHECKER,
        SPREAD_LIST_CHECK,
        """        _ -> {
          let _spans = lo + hi
          (cx1, t, TLESpread(tx))
        }
""",
    ),
    # 3: the element type crosses the `..` as the operand's expectation.
    "spread-operand-loses-expectation": (
        CHECKER,
        SPREAD_EXPECTATION,
        """      let list_exp: Option[Ty] = match el_exp {
        Some(_t) -> None
        None -> None
      }
""",
    ),
    # 4: the lever. A conditional element's body is checked *at* the element
    # type; hand it None and a call whose type parameter lives only in its
    # return type stops typing, even though its sibling settled the type. This
    # is the mutation the whole directory exists for.
    "cond-body-loses-expectation": (
        CHECKER,
        COND_EXPECTATION,
        """        let body_exp: Option[Ty] = no_expected()
""",
    ),
    # 5: half of the same line on its own -- an earlier arm of one chain
    # settles the type for a later arm, with the `el_exp` fallback left in
    # place. Recorded rather than counted: measured, its red set is a strict
    # subset of 4's, and the assertion it does redden is also reddened by
    # `else-if-chain-truncated`, which cannot leave a two-arm chain standing
    # by construction. It stays in the list because `mutate.py` refuses an
    # anchor that has drifted, so deleting the sentence is still a loud
    # failure rather than a green run.
    "cond-arm-does-not-settle-later-arms": (
        CHECKER,
        COND_EXPECTATION,
        """        let body_exp: Option[Ty] =
          if t != TyNever && is_concrete(cx1, t) { el_exp } else { el_exp }
""",
    ),
    # 6: a conditional element's condition is a Bool.
    "cond-condition-unchecked": (CHECKER, COND_BOOL, ""),
    # 7: an element form that cannot be typed alone is deferred to the second
    # round. Recorded rather than counted, and so is its conditional twin
    # below: deferral can only matter for an element that needs an
    # expectation, and an element that needs one is exactly the element the
    # push-down reaches -- so 3 and 4 subsume 7 and 8 structurally rather than
    # by accident. Measured both ways.
    "needs-expected-blind-to-spread": (
        CHECKER,
        NEEDS_EXPECTED_SPREAD,
        "    LeSpread(_e, _, _) -> false\n",
    ),
    # 8: the same sentence for a conditional element. See 7.
    "needs-expected-blind-to-cond": (
        CHECKER,
        NEEDS_EXPECTED_COND,
        """    LeIf(_arms, _, _) -> false
""",
    ),
    # 9: an `else if` chain with no final else is one element form as a whole,
    # not just its first arm. Returning None for a chain sends the whole thing
    # back to being an ordinary element, where the trailing else-less `if` has
    # to be Unit.
    "else-if-chain-truncated": (
        PARSER,
        CHAIN_RECURSION,
        """        Some(_inner) -> None
""",
    ),
    # 10: lowering. A conditional element appends only when its arm is taken.
    # The mutant appends unconditionally, so the condition is evaluated and
    # discarded and the list is one element too long -- a wrong length, not a
    # compile error, which is the failure mode a corpus of accepted programs
    # cannot see.
    "cond-always-contributes": (
        LOWER,
        COND_APPEND,
        """    let (st3, rest) = lower_if_seg(st2, sym, ty, arms, k + 1)
    (st3, [CSDiscard(c), append_seg(sym, ty, one)] ++ rest)
""",
    ),
}


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree>")
    name, tree = sys.argv[1], Path(sys.argv[2])
    if name not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {name}")
    rel, old, new = MUTATIONS[name]
    path = tree / rel
    text = path.read_text(encoding="utf-8")
    path.write_text(replace_once(text, old, new, name), encoding="utf-8")
    print(f"{name}: applied to {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
