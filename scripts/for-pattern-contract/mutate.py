#!/usr/bin/env python3
"""Apply one registered production-source mutation for the for-pattern contract."""

from pathlib import Path
import sys


MUTATIONS = {
    "reject-record-for-head": (
        "src/front/parser.dawn",
        ((
            '''fn for_stmt(p: P, st: St) -> PR[Stmt] = {
  let (st1, kw) = adv(p, st)
  let (st2, pat) = pattern_p(p, st1)?
''',
            '''fn for_stmt(p: P, st: St) -> PR[Stmt] = {
  let (st1, kw) = adv(p, st)
  if at_kind(p, st1, TYPEIDENT) && kind_ahead(p, st1, 1) == LBRACE {
    return Err((st1, perr(p, st1, "expected a non-record pattern")))
  }
  let (st2, pat) = pattern_p(p, st1)?
''',
        ),),
    ),
    "skip-irrefutability": (
        "src/check/checker.dawn",
        ((
            '''          Some(true) -> {
            let (plo, phi) = match refutable_span(cx1, pat) {
              Some(sp) -> sp
              None -> (pat_lo(pat), pat_hi(pat))
            }
            cx1 = cerr_h(cx1, "for pattern must match every item", plo, phi,
              "use match or filter before the loop to handle items this pattern does not match")
          }
''',
            "          Some(true) -> ()\n",
        ),),
    ),
    "drop-bindings": (
        "src/ir/lower.dawn",
        ((
            "  let (st10, pattern_stmts) = lower_irrefutable_pattern(st9, item, pat, item_ty)\n",
            '''  let (st10, pattern_stmts) = match pat {
    TPBind(_, _) -> lower_irrefutable_pattern(st9, item, pat, item_ty)
    _ -> (st9, [])
  }
''',
        ),),
    ),
    "inline-iter-get": (
        "src/ir/lower.dawn",
        ((
            "  let item = CLocal(item_sym, item_ty)\n",
            '''  let item = match pat {
    TPBind(_, _) -> CLocal(item_sym, item_ty)
    _ -> get_v
  }
''',
        ),),
    ),
    "reuse-source-expression": (
        "src/ir/lower.dawn",
        ((
            '  let cv: TExpr = XLocal(csym, "for$" ++ "xs", 0, 0, ct)\n',
            '''  let cv: TExpr = match pat {
    TPBind(_, _) -> XLocal(csym, "for$" ++ "xs", 0, 0, ct)
    _ -> from
  }
''',
        ),),
    ),
    "leak-scope": (
        "src/check/checker.dawn",
        ((
            '''      cx1 = pop_scope(cx1)
      (cx1, TSFor(tp, loop_t, fx, tx_to, wit, bx, hj, lo, hi))
''',
            "      (cx1, TSFor(tp, loop_t, fx, tx_to, wit, bx, hj, lo, hi))\n",
        ),),
    ),
    "skip-LSP-visit": (
        "src/lsp/lspq.dawn",
        ((
            '''        Some(TSFor(tpat, _, tfrom, tto, _, tbody, _, _, _)) -> {
          q = visit_pat(qc, q, pat, Some(tpat))
''',
            '''        Some(TSFor(tpat, _, tfrom, tto, _, tbody, _, _, _)) -> {
          q = q
''',
        ),),
    ),
    "restore-range-dot-block": (
        "src/lsp/lspc.dawn",
        ((
            "  if nb > 0 && before[nb - 1] == '.' && (nb < 2 || before[nb - 2] != '.') {\n",
            "  if nb > 0 && before[nb - 1] == '.' {\n",
        ),),
    ),
    "restore-wide-completion": (
        "src/lsp/lspq.dawn",
        ((
            "      if e_lo(body) <= before && before <= e_hi(body) {\n",
            "      if true {\n",
        ),),
    ),
    "drop-derived-diagnostic-suppression": (
        "src/check/checker.dawn",
        ((
            "      if not is_errorish(loop_t) && len(cx1.diags) == pat_diag_count {\n",
            "      if not is_errorish(loop_t) {\n",
        ),),
    ),
    "repeat-iter-start": (
        "src/ir/lower.dawn",
        ((
            "    CSLet(isym, cur_t, start_v),\n",
            '''    CSLet(isym, cur_t, match pat {
      TPBind(_, _) -> start_v
      _ -> CBlock([CSDiscard(start_v)], Some(start_v), cur_t)
    }),
''',
        ),),
    ),
    "move-source-into-loop": (
        "src/ir/lower.dawn",
        ((
            '''  (LSt { ..st11, cur_loop: st.cur_loop }, [
    CSLet(csym, ct, coll),
    CSLet(isym, cur_t, start_v),
    CSLoop(lid, inner, Some(CBlock([step], None, TyUnit)))
  ])
''',
            '''  let statements = match pat {
    TPCtor(_, _, _) -> [
      CSLet(isym, cur_t, start_v),
      CSLoop(lid, CBlock([CSLet(csym, ct, coll)] ++ inner_stmts, None, TyUnit),
        Some(CBlock([step], None, TyUnit)))
    ]
    _ -> [
      CSLet(csym, ct, coll),
      CSLet(isym, cur_t, start_v),
      CSLoop(lid, inner, Some(CBlock([step], None, TyUnit)))
    ]
  }
  (LSt { ..st11, cur_loop: st.cur_loop }, statements)
''',
        ),),
    ),
    "move-iter-start-into-loop": (
        "src/ir/lower.dawn",
        ((
            '''  (LSt { ..st11, cur_loop: st.cur_loop }, [
    CSLet(csym, ct, coll),
    CSLet(isym, cur_t, start_v),
    CSLoop(lid, inner, Some(CBlock([step], None, TyUnit)))
  ])
''',
            '''  let statements = match pat {
    TPCtor(_, _, _) -> [
      CSLet(csym, ct, coll),
      CSLoop(lid, CBlock([CSLet(isym, cur_t, start_v)] ++ inner_stmts, None, TyUnit),
        Some(CBlock([step], None, TyUnit)))
    ]
    _ -> [
      CSLet(csym, ct, coll),
      CSLet(isym, cur_t, start_v),
      CSLoop(lid, inner, Some(CBlock([step], None, TyUnit)))
    ]
  }
  (LSt { ..st11, cur_loop: st.cur_loop }, statements)
''',
        ),),
    ),
    "move-iter-get-after-pattern": (
        "src/ir/lower.dawn",
        ((
            '''  let inner_stmts = [
    CSIf(done_v, CBreak(lid), None),
    CSLet(item_sym, item_ty, get_v)
  ] ++ pattern_stmts ++ [CSDiscard(b)]
''',
            '''  let inner_stmts = match pat {
    TPCtor(_, _, _) ->
      [CSIf(done_v, CBreak(lid), None)] ++ pattern_stmts ++
        [CSLet(item_sym, item_ty, get_v), CSDiscard(b)]
    _ -> [
      CSIf(done_v, CBreak(lid), None),
      CSLet(item_sym, item_ty, get_v)
    ] ++ pattern_stmts ++ [CSDiscard(b)]
  }
''',
        ),),
    ),
    "drop-complexity-diagnostic": (
        "src/check/checker.dawn",
        ((
            '''          Some(false) -> ()
          None -> { cx1 = usefulness_too_complex(cx1, pat_lo(pat), pat_hi(pat)) }
        }
      }
      let d = len(cx1.frame.loop_stack)
''',
            '''          Some(false) -> ()
          None -> ()
        }
      }
      let d = len(cx1.frame.loop_stack)
''',
        ),),
    ),
    "reuse-pattern-binder-as-induction": (
        "src/ir/lower.dawn",
        ((
            '''          let (st4, isym) = fresh_sym(st3)
          let (st5, bsym) = fresh_sym(st4)
''',
            '''          let (st4, hidden_isym) = fresh_sym(st3)
          let isym = match pat {
            TPBind(sid, _) -> sid
            TPOr(alts) -> match alts[0] {
              TPBind(sid, _) -> sid
              _ -> hidden_isym
            }
            _ -> hidden_isym
          }
          let (st5, bsym) = fresh_sym(st4)
''',
        ),),
    ),
    "drop-never-source-lowering": (
        "src/ir/lower.dawn",
        ((
            "          if item_ty == TyNever {\n",
            "          if item_ty == TyError {\n",
        ),),
    ),
    "skip-pattern-context-completion": (
        "src/lsp/lspc.dawn",
        ((
            "  if in_for_pattern(qc, pos) {\n",
            "  if false {\n",
        ),),
    ),
    "choose-earliest-incomplete-for": (
        "src/lsp/lspc.dawn",
        ((
            "fn remember_latest_for(latest: Option[Int], found: Int) -> Option[Int] = Some(found)\n",
            '''fn remember_latest_for(latest: Option[Int], found: Int) -> Option[Int] =
  match latest {
    Some(_) -> latest
    None -> Some(found)
  }
''',
        ),),
    ),
    "cross-ordinary-newline": (
        "src/lsp/lspc.dawn",
        ((
            '''fn for_header_newline_continues(previous_pipe: Bool, next_kind: TokKind) -> Bool =
  previous_pipe || next_kind == PIPE
''',
            '''fn for_header_newline_continues(previous_pipe: Bool, next_kind: TokKind) -> Bool =
  true
''',
        ),),
    ),
    "drop-nested-recovery-depth": (
        "src/lsp/lspc.dawn",
        ((
            '''  while i < before {
    let kind = toks[i].kind
    if kind == LPAREN {
      parens = parens + 1
    } else if kind == RPAREN {
      parens = parens - 1
    } else if kind == LBRACKET {
      brackets = brackets + 1
    } else if kind == RBRACKET {
      brackets = brackets - 1
''',
            '''  while i < before {
    let kind = toks[i].kind
    if kind == LPAREN {
      parens = parens
    } else if kind == RPAREN {
      parens = parens
    } else if kind == LBRACKET {
      brackets = brackets
    } else if kind == RBRACKET {
      brackets = brackets
''',
        ),),
    ),
    "drop-record-recovery-depth": (
        "src/lsp/lspc.dawn",
        ((
            '''fn pattern_depth_before(toks: List[Token], at: Int, before: Int) -> (Int, Int, Int) = {
  var parens = 0
  var brackets = 0
  var braces = 0
  var i = at
  while i < before {
    let kind = toks[i].kind
    if kind == LPAREN {
      parens = parens + 1
    } else if kind == RPAREN {
      parens = parens - 1
    } else if kind == LBRACKET {
      brackets = brackets + 1
    } else if kind == RBRACKET {
      brackets = brackets - 1
    } else if kind == LBRACE {
      braces = braces + 1
    } else if kind == RBRACE {
      braces = braces - 1
    }
    i = i + 1
  }
  (parens, brackets, braces)
}
''',
            '''fn pattern_depth_before(toks: List[Token], at: Int, before: Int) -> (Int, Int, Int) = {
  var parens = 0
  var brackets = 0
  var braces = 0
  var i = at
  while i < before {
    let kind = toks[i].kind
    if kind == LPAREN {
      parens = parens + 1
    } else if kind == RPAREN {
      parens = parens - 1
    } else if kind == LBRACKET {
      brackets = brackets + 1
    } else if kind == RBRACKET {
      brackets = brackets - 1
    } else if kind == LBRACE {
      braces = braces
    } else if kind == RBRACE {
      braces = braces
    }
    i = i + 1
  }
  (parens, brackets, braces)
}
''',
        ),),
    ),
    "accept-nested-header-in": (
        "src/lsp/lspc.dawn",
        ((
            '''fn pattern_top(parens: Int, brackets: Int, braces: Int) -> Bool =
  parens == 0 && brackets == 0 && braces == 0
''',
            '''fn pattern_top(parens: Int, brackets: Int, braces: Int) -> Bool =
  true
''',
        ),),
    ),
    "ignore-incomplete-pattern-pipe": (
        "src/lsp/lspc.dawn",
        ((
            '''  if not previous_is_pipe(toks, previous) { return false }
  let (parens, brackets, braces) = pattern_depth_before(toks, at, previous)
''',
            '''  if false { return false }
  let (parens, brackets, braces) = pattern_depth_before(toks, at, previous + 1)
''',
        ),),
    ),
    "accept-nonboundary-alternative": (
        "src/lsp/lspc.dawn",
        ((
            '''  } else if boundary == RBRACE {
    braces > 0
  } else {
    false
  }
''',
            '''  } else if boundary == RBRACE {
    braces > 0
  } else {
    true
  }
''',
        ),),
    ),
    "skip-qualified-pattern-constructors": (
        "src/lsp/lspc.dawn",
        ((
            '''        if in_for_pattern(qc, pos) || in_incomplete_qualified_for_pattern(text, alias_lo, pos) {
          return qualified_pattern_constructors(qc, module_alias)
        }
''',
            '''        if false {
          return qualified_pattern_constructors(qc, module_alias)
        }
''',
        ),),
    ),
    "escape-incomplete-header-interval": (
        "src/lsp/lspc.dawn",
        ((
            '''      Some(header_in) ->
        pos <= toks[header_in].lo &&
        missing_for_alternative_at(toks, for_at + 1, header_in, header_in, pos)
''',
            '''      Some(header_in) ->
        true &&
        missing_for_alternative_at(toks, for_at + 1, header_in, len(toks) - 1, pos)
''',
        ),),
    ),
    "admit-rejected-source-constructor": (
        "src/lsp/lspc.dawn",
        ((
            "      if type_ok && source_constructor_name_available(qc, d.name, c.name, seen_ctors) {\n",
            "      if true {\n",
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
        raise SystemExit(f"usage: mutate.py <{names}> <selfhost-source-root>")

    name, raw_root = sys.argv[1:]
    relative, replacements = MUTATIONS[name]
    root = Path(raw_root)
    path = root / relative
    source = path.read_text(encoding="utf-8")
    mutated = source
    for old, new in replacements:
        count = mutated.count(old)
        if count != 1:
            raise SystemExit(
                f"{name}: mutation anchor drifted ({count} matches): {old!r}"
            )
        mutated = mutated.replace(old, new)
    if mutated == source:
        raise SystemExit(f"{name}: mutation did not change {relative}")
    path.write_text(mutated, encoding="utf-8")
    print(relative)


if __name__ == "__main__":
    main()
