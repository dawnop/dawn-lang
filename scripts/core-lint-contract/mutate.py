#!/usr/bin/env python3
"""Restore one historical ABI defect in a copy of the repository tree.

    scripts/core-lint-contract/mutate.py <mutation> <tree-root>

Each entry puts back the shape of a defect from the 2026-10 bug corpus
(agent-handoff research, docs/core-lint-design.md has the table) and nothing
else, so the check that is supposed to catch it can be shown red on it. run.py
beside this file is the reader: it applies every entry to a private copy,
builds or tests that copy, and requires the owning check to fail in its own
words. mutation-anchor-preflight.py proves every anchor here matches exactly
once before any build, which is the half run.py cannot do cheaply.

Two groups, by what has to run for the defect to show:

  static-*   a test or a script that needs no program: the owning check reads
             the compiler's own tables (cut 1 of the core-lint plan);
  lint-*     a defect only a program reaches, caught by `DAWN_CORE_LINT=1` on
             the Core lowering produced for a repro program (cut 2).

A mutation is an ordered tuple of edits, each applied to the text the previous
one left, with paths relative to the tree root.
"""

from pathlib import Path
import sys

LOWER = "selfhost/src/ir/lower.dawn"
INTERP = "selfhost/src/ir/interp.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
TYPES = "selfhost/src/check/types.dawn"
EMIT = "selfhost/src/jvm/emit.dawn"
EMITC = "selfhost/src/c/emitc.dawn"
RTCLASSES = "selfhost/src/jvm/rtclasses.dawn"

# The comptime chain's arm for a name lowering removes: #185's dead
# `parse_int` arm, spelled with the one such name left.
INTERP_ARM = (
    INTERP,
    """    Ok((st, env, VBool(value_eq(args[0], args[1]))))
  } else if name == "ev_get" {""",
    """    Ok((st, env, VBool(value_eq(args[0], args[1]))))
  } else if name == "parse_float" {
    Ok((st, env, VUnit))
  } else if name == "ev_get" {""",
)

MUTATIONS = {
    # 69691c36: scalar_rt answered Float with `dawn_hash_float` and
    # `dawn_cmp_float`, which the C runtime never defined.
    "static-69691c36": ((
        EMITC,
        """    # answer, and it is the same one Cursor gets.
    TyString -> "${prefix}_str\"""",
        """    # answer, and it is the same one Cursor gets.
    TyFloat -> "${prefix}_float"
    TyString -> "${prefix}_str\"""",
    ),),
    # #87: the function-value limit without the evidence slot, so the widest
    # admitted value needs an interface one past the table.
    "static-87": ((
        TYPES,
        """  widest - fn_arity(TyFn([], TyUnit, EPure))
}""",
        """  widest
}""",
    ),),
    # #182: the pairing guard without its length half.
    "static-182": ((
        EMIT,
        """  if len(lowered) != len(declared) {
    panic("codegen: module `" ++ module ++ "` declares " ++ to_string(len(declared)) ++
        " functions but lowering produced " ++ to_string(len(lowered)))
  }
  var i = 0
  for name in declared {""",
        """  var i = 0
  for name in declared {""",
    ),),
    # #185, the unlisted half: an arm the list does not name is dead, and only
    # intrinsic-parity.py can see it.
    "static-185-arm": (INTERP_ARM,),
    # #185, the listed half: the arm and the list entry together, which is the
    # shape `parse_int` had -- an arm for a name lowering always removes.
    "static-185-listed": (
        INTERP_ARM,
        (
            INTERP,
            """  "str_lower", "str_upper", "float_of_decimal"
]""",
            """  "str_lower", "str_upper", "float_of_decimal", "parse_float"
]""",
        ),
    ),
    # #205: the emitter calls a runtime method under a descriptor rtclasses
    # does not generate.
    "static-205": ((
        RTCLASSES,
        """  rt(STRINGS_CLASS, "cmp", "(" ++ string_desc() ++ string_desc() ++ ")I")""",
        """  rt(STRINGS_CLASS, "cmp", "(" ++ string_desc() ++ string_desc() ++ ")J")""",
    ),),
    # #283: a builtin taken as a value writes its intrinsic itself instead of
    # lowering the call it wraps.
    "static-283": ((
        LOWER,
        """  }, XCallBuiltin(name, args, no_wits, evid, 0, 0, ret))
  let f = CFun {
    name: lam,
    owner: st5.owner,
    captures: [],
    params: ps,
    dicts: [],
    evs: evps,
    ret: ret,
    body: body,""",
        """  }, XCallBuiltin(name, args, no_wits, evid, 0, 0, ret))
  var raw: List[CExpr] = []
  for p in ps { raw = raw ++ [CLocal(p.sym, p.ty)] }
  let f = CFun {
    name: lam,
    owner: st5.owner,
    captures: [],
    params: ps,
    dicts: [],
    evs: evps,
    ret: ret,
    body: if len(raw) < 0 { body } else { CIntrinsic(name, raw, ret) },""",
    ),),
    # #13: a zero-goal conditional impl's dictionary built as an application
    # of a def that records no arguments.
    "lint-13": ((
        LOWER,
        """        if len(goals) == 0 {
          dict_ref(st, tid, t)
        } else {""",
        """        if len(goals) < 0 {
          dict_ref(st, tid, t)
        } else {""",
    ),),
    # #43: a local fn's body resolves a label through the enclosing frame.
    "lint-43": ((
        CHECKER,
        """  if not cx1.frame.isolated {
    match local_fn_missing_evidence(cx1, nm, (row) => {""",
        """  if cx1.frame.isolated && not cx1.frame.isolated {
    match local_fn_missing_evidence(cx1, nm, (row) => {""",
    ),),
    # #54: the same, one axis over, for an effect variable.
    "lint-54": ((
        CHECKER,
        """    if not cx1.frame.isolated {
      match local_fn_missing_evidence(cx1, ev_var_local_name(svid), (row) => {""",
        """    if cx1.frame.isolated && not cx1.frame.isolated {
      match local_fn_missing_evidence(cx1, ev_var_local_name(svid), (row) => {""",
    ),),
    # #144: dictionary defs deduplicated by key without their arity.
    "lint-144": ((
        LOWER,
        "let key = dict_key(tid, subject) ++ dict_shape_suffix(nargs)",
        "let key = dict_key(tid, subject)",
    ),),
    # 5f91c188: a projection that reduced to a label hands over that label's
    # bare record, where the slot's readers walk a pack.
    "lint-5f91c188": ((
        CHECKER,
        """    if missing {
      out = out ++ [XError(owner_off(cx, lo), owner_off(cx, hi))]
    } else {
      let (cx2, pack, un) = evidence_pack(cx1, red, true, lo, hi)""",
        """    if missing {
      out = out ++ [XError(owner_off(cx, lo), owner_off(cx, hi))]
    } else if len(eff_labels(red)) > 0 {
      let (eid, _) = eff_labels(red)[0]
      let (cx2, tx, answered) = resolve_label_evidence(cx1, eid, lo, hi)
      cx1 = cx2
      if not answered { unanswered = unanswered ++ [eid] }
      out = out ++ [tx]
    } else {
      let (cx2, pack, un) = evidence_pack(cx1, red, true, lo, hi)""",
    ),),
}


def apply(mutation: str, root: Path) -> None:
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            raise SystemExit(f"{mutation}: mutation anchor in {rel} is not unique "
                             f"({count} matches)")
        path.write_text(text.replace(old, new))


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    apply(mutation, root)


if __name__ == "__main__":
    main()
