#!/usr/bin/env python3
"""Apply one registered production-source mutation for the or-pattern contract."""

from pathlib import Path
import sys


MUTATIONS = {
    "drop-binding-set": (
        "src/check/checker.dawn",
        (
            (
                """      None -> {
        cx1 = cerr_h(cx1, \"or-pattern alternative does not bind `\" ++ want.name ++ \"`\",
          pat_lo(alt), pat_hi(alt), \"every alternative must bind the same names as the first\")
      }
""",
                "      None -> ()\n",
            ),
            (
                """    if pat_bind_named(canonical, got.name) == None {
      cx1 = cerr_h(cx1, \"or-pattern alternative binds extra name `\" ++ got.name ++ \"`\",
        got.lo, got.hi, \"every alternative must bind the same names as the first\")
    }
""",
                "    if false { cx1 = cx1 }\n",
            ),
        ),
    ),
    "drop-binding-type": (
        "src/check/checker.dawn",
        (("        if got.ty != want.ty {", "        if false {"),),
    ),
    "restore-derived-binding-check": (
        "src/check/checker.dawn",
        (("    if first_ok && len(cx1.diags) == alt_diag_count {", "    if true {"),),
    ),
    "skip-qualified-let-dispatch": (
        "src/front/parser.dawn",
        ((
            """  let qualified_ctor = k == IDENT && kind_ahead(p, st1, 1) == DOT &&
    kind_ahead(p, st1, 2) == TYPEIDENT
""",
            "  let qualified_ctor = false\n",
        ),),
    ),
    "disable-leading-pattern-pipe": (
        "src/front/parser.dawn",
        ((
            """  while true {
    let sta = lead1(p, st2, PIPE)
    if not at_kind(p, sta, PIPE) { break }
    saw_pipe = true
""",
            """  while true {
    let sta = st2
    if not at_kind(p, sta, PIPE) { break }
    saw_pipe = true
""",
        ),),
    ),
    "break-list-rest-definition": (
        "src/lsp/lspq.dawn",
        ((
            """                      q = offer(q, rlo, rhi, sym.name ++ ": " ++ show_ty(qc, sym.ty),
                        Some((sym.dlo, sym.dhi)), None)
""",
            """                      q = offer(q, rlo, rhi, sym.name ++ ": " ++ show_ty(qc, sym.ty),
                        Some((rlo, rhi)), None)
""",
        ),),
    ),
    "collect-all-or-completions": (
        (
            "src/lsp/lspq.dawn",
            ((
                "    TPOr(alts) -> if len(alts) > 0 { acc = collect_tpat(qc, acc, alts[0]) }",
                "    TPOr(alts) -> { for alt in alts { acc = collect_tpat(qc, acc, alt) } }",
            ),),
        ),
        (
            "src/lsp/lspc.dawn",
            ((
                '  if name == "_" || set.has(it.seen, name) { return it }',
                '  if name == "_" || (kind != 6 && set.has(it.seen, name)) { return it }',
            ),),
        ),
    ),
    "drop-qualified-pattern-queries": (
        "src/lsp/lspq.dawn",
        ((
            """    PQual(_, _, args, _, _, nlo, nhi, _, _) -> {
      q = visit_ctor_pat(qc, q, args, nlo, nhi, tp)
    }
""",
            "    PQual(_, _, _, _, _, _, _, _, _) -> ()\n",
        ),),
    ),
    "duplicate-arm-test": (
        "src/ir/lower.dawn",
        ((
            "    body = body ++ setup ++ [CSIf(cond, inner, None)]",
            "    body = body ++ setup ++ [CSIf(cond, inner, None), CSIf(cond, inner, None)]",
        ),),
    ),
    "duplicate-arm-body": (
        "src/ir/lower.dawn",
        ((
            "        CBlock([CSAssign(rsym, armb)], Some(CBreak(lid)), TyNever)",
            "        CBlock([CSDiscard(armb), CSAssign(rsym, armb)], Some(CBreak(lid)), TyNever)",
        ),),
    ),
    "prefer-last-alternative": (
        "src/ir/lower.dawn",
        ((
            "        let available = CUnary(CNot, CLocal(selector, TyBool), TyBool)",
            "        let available = CBool(true)",
        ),),
    ),
    "truncate-nested-list-or": (
        "src/ir/lower.dawn",
        ((
            """    let (st2, c, bs) = pat_test_slots(st1, elem, p, et, slots)
    st1 = st2
    cond = and_of(cond, c)
    binds = binds ++ bs
    i = i + 1
""",
            """    let effective = match p {
      TPOr(alts) -> if len(alts) > 0 { alts[0] } else { p }
      _ -> p
    }
    let (st2, c, bs) = pat_test_slots(st1, elem, effective, et, slots)
    st1 = st2
    cond = and_of(cond, c)
    binds = binds ++ bs
    i = i + 1
""",
        ),),
    ),
    "skip-complete-or-reduction": (
        "src/check/exhaustive.dawn",
        ((
            "  let normalized_matrix = simplify_matrix(adts, matrix, types_)",
            "  let normalized_matrix = matrix",
        ),),
    ),
    "drop-usefulness-budget-diagnostic": (
        "src/check/checker.dawn",
        ((
            """fn usefulness_too_complex(cx: Cx, lo: Int, hi: Int) -> Cx =
  cerr_h(cx, \"pattern analysis exceeded its complexity budget\", lo, hi,
    \"simplify nested alternatives or split the pattern into smaller matches\")
""",
            "fn usefulness_too_complex(cx: Cx, _lo: Int, _hi: Int) -> Cx = cx\n",
        ),),
    ),
}


def main() -> None:
    if sys.argv[1:] == ["--list"]:
        for name in MUTATIONS:
            print(name)
        return
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        names = " | ".join(MUTATIONS)
        raise SystemExit(f"usage: mutate.py <{names}> <production-source>")

    name, raw_path = sys.argv[1:]
    entry = MUTATIONS[name]
    specs = (entry,) if isinstance(entry[0], str) else entry
    target = Path(raw_path)
    if len(specs) > 1 and not target.is_dir():
        raise SystemExit(f"{name}: multiple production targets require the selfhost source root")
    for expected_path, replacements in specs:
        path = target / expected_path if target.is_dir() else target
        if not path.as_posix().endswith("/" + expected_path):
            raise SystemExit(f"{name}: expected target {expected_path}, got {path}")
        source = path.read_text(encoding="utf-8")
        mutated = source
        for old, new in replacements:
            count = mutated.count(old)
            if count != 1:
                raise SystemExit(
                    f"{name}: mutation anchor drifted ({count} matches): {old!r}")
            mutated = mutated.replace(old, new)
        if mutated == source:
            raise SystemExit(f"{name}: mutation did not change {expected_path}")
        path.write_text(mutated, encoding="utf-8")
        print(expected_path)


if __name__ == "__main__":
    main()
