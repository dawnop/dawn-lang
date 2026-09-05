#!/usr/bin/env python3
"""Apply one SYN-05 mutation to a copy of the compiler tree.

Each mutation removes or inverts exactly one sentence of the general pipe, and
the harness then asserts that exactly one contract goes red. A mutant must
still compile and run: "the mutant did not build" proves nothing about the
rule, so `negative-control-*` entries are recorded separately rather than
counted.

Every anchor is matched exactly once. A rewrite of `pipe_expr` moves all of
them, and that has to be a hard failure rather than a mutation that silently
does nothing; a no-op mutant is a gate that has stopped looking.
"""
from pathlib import Path
import sys

PARSER = "selfhost/src/front/parser.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
LSPQ = "selfhost/src/lsp/lspq.dawn"

# the three arms the pipe desugar is made of, quoted here once so a drift in
# any of them fails loudly instead of leaving a mutation unapplied
APPLY_ARM = (
    "      EApply(t, args, _, rhi) -> EApply(t, [pos_arg(left)] ++ args, e_lo(left), rhi)\n"
)
METHOD_ARM = (
    "      EMethod(t, mname, args, mnlo, mnhi, _, rhi) ->\n"
    "        EMethod(t, mname, [pos_arg(left)] ++ args, mnlo, mnhi, e_lo(left), rhi)\n"
)
OTHER_ARM = "      other -> EApply(other, [pos_arg(left)], e_lo(left), e_hi(other))\n"

# the parse error the pipe used to own, restored verbatim (spans aside) by the
# mutant that puts a rulebook back into the parser
OLD_REFUSAL = (
    "      ECtor(_, _, _, _, _, _, elo, ehi) -> return Err((st3, pd_h(\n"
    '        "the right side of `|>` must be a call, a function name, or a lambda",\n'
    '        elo, ehi, "x |> f(a) is equivalent to f(x, a)")))\n'
)


def replace_once(text: str, old: str, new: str, name: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{name}: mutation anchor drifted ({n} matches)")
    return text.replace(old, new)


# mutation -> (file, old, new)
MUTATIONS = {
    # 1: the right side is not a shape the pipe gets to approve.
    #
    # Aimed at the constructor arm alone. The designed mutant restored the
    # whole whitelist, and that one refuses every newly admitted shape at once
    # (measured: bare constructor, applied constructor, qualified call, method,
    # function field and nested call all stop parsing), so it reddens the
    # assertions that own `drop-method-prepend` and `wrap-nested-call` as well;
    # an assertion two mutants can redden is owned by neither. Same
    # correction as 2d5f19a's retarget of drop-lsp-children at the XJava arm.
    "refuse-constructor-rhs": (
        PARSER,
        OTHER_ARM,
        OLD_REFUSAL + OTHER_ARM,
    ),
    # 2: a call on the right takes the left side even when it is a method
    # call. Dropping the arm sends `1 |> xs.get()` to the `other` arm, which
    # applies the method's *result* to the left side.
    "drop-method-prepend": (
        PARSER,
        METHOD_ARM,
        "",
    ),
    # 3: and it takes it *in front of* the written arguments
    "append-left-argument": (
        PARSER,
        APPLY_ARM,
        "      EApply(t, args, _, rhi) -> EApply(t, args ++ [pos_arg(left)], e_lo(left), rhi)\n",
    ),
    # 4: inserting into the call, not wrapping the call.
    #
    # Aimed at the nested shape (`x |> make()(a)`), where "wrap" and "insert"
    # differ without breaking anything else. The general form (wrap every
    # EApply) also stops the evaluation-order fixture from compiling, which
    # would redden `hoist-left-before-callee`'s owning assertion (measured).
    "wrap-nested-call": (
        PARSER,
        APPLY_ARM,
        "      EApply(EApply(it, iargs, ilo, ihi), args, _, rhi) ->\n"
        "        EApply(EApply(EApply(it, iargs, ilo, ihi), args, ilo, rhi),\n"
        "          [pos_arg(left)], e_lo(left), rhi)\n" + APPLY_ARM,
    ),
    # 5: the written arguments are spliced in as they were written. Rebuilding
    # them positionally drops the names, and a name the author wrote is the only
    # thing standing between `n |> f(a: 2)` and a call that quietly means
    # something else.
    "rebuild-arguments-positionally": (
        PARSER,
        APPLY_ARM,
        "      EApply(t, args, _, rhi) ->\n"
        "        EApply(t, [pos_arg(left)] ++ list.map(args, a => pos_arg(a.e)),\n"
        "          e_lo(left), rhi)\n",
    ),
    # 6: `pipe_expr = or_expr { \"|>\" or_expr }`: the right side is one
    # or_expr, so the pipe associates to the left. Parsing it at pipe level
    # makes it associate to the right.
    "parse-rhs-at-pipe-level": (
        PARSER,
        "    let (st3, rhs) = or_expr(p, st2, nb)?\n",
        "    let (st3, rhs) = pipe_expr(p, st2, nb)?\n",
    ),
    # 7: and it is a whole or_expr, not the tighter and_expr: `b |> f() || c`
    # pipes into `f() || c`, which is not a function.
    "parse-rhs-one-level-tighter": (
        PARSER,
        "    let (st3, rhs) = or_expr(p, st2, nb)?\n",
        "    let (st3, rhs) = and_expr(p, st2, nb)?\n",
    ),
    # 8: the left side is an argument, not something hoisted in front of the
    # callee. The pipe invents no node, so the call happens in the order the
    # written-out call happens in: target first, then arguments left to right.
    "hoist-left-before-callee": (
        PARSER,
        APPLY_ARM,
        "      EApply(t, args, _, rhi) -> {\n"
        "        let plo = e_lo(left)\n"
        "        let phi = e_hi(left)\n"
        "        let pann: Option[TypeRef] = None\n"
        "        EBlock([SLet(\"pipe_lhs_tmp\", false, pann, left, plo, phi)],\n"
        "          Some(EApply(t, [pos_arg(EVar(\"pipe_lhs_tmp\", plo, phi))] ++ args,\n"
        "            plo, rhi)), plo, rhi)\n"
        "      }\n",
    ),
    # 9: a record is built with braces however the application was spelled
    # (spec §2.4). Before CtorUse the parenthesised spelling was
    # indistinguishable from the braced one here, and `Rec(1, 2)` compiled.
    "allow-record-apply": (
        CHECKER,
        "  if spelling == CApply && ad.is_record {\n",
        "  if false && ad.is_record {\n",
    ),
    # 10: a bare `m.f` on the right is a *value* the pipe applies, not a call
    # it builds. Routing it into a call would make `n |> str.starts_with` mean
    # `str.starts_with(n)`: its diagnostic names the declaration instead of
    # reporting the arity of the function value (#66).
    "route-qualified-name-into-call": (
        PARSER,
        OTHER_ARM,
        "      EFieldAcc(t, fname, flo, fhi, _, fhi2) ->\n"
        "        EMethod(t, fname, [pos_arg(left)], flo, fhi, e_lo(left), fhi2)\n" + OTHER_ARM,
    ),
    # 11: the editor maps the typed children of a module-qualified call. Its
    # typed argument list carries no receiver, so it is the same length as the
    # written one; without that branch every argument inside `m.f(a)` walks
    # parse-only and hover answers with the enclosing call's type.
    "drop-lsp-qualified-call-children": (
        LSPQ,
        "  } else if len(targs) == len(args) {\n"
        "    q = walk_e(qc, q, target, None)\n"
        "    var j = 0\n"
        "    for a in args {\n"
        "      q = walk_e(qc, q, a, get(targs, j))\n"
        "      j = j + 1\n"
        "    }\n"
        "  } else {\n",
        "  } else {\n",
    ),
    # 12: and the typed children of a module-qualified *construction*, which
    # is an XCtor rather than an XApply. Split from #11 because one arm each is
    # what 2d5f19a's anchor drift showed: a single "drop the LSP mappings"
    # mutant is reddened by either hover probe and therefore owned by neither.
    "drop-lsp-qualified-ctor": (
        LSPQ,
        "            Some(XCtor(_, _, _, _, _, _, _, _)) -> {\n"
        "              q = walk_ctor_call(qc, q, args0, None, flo, fhi, te)\n"
        "            }\n",
        "",
    ),
    # negative control: the pipe's *left* side is a whole or_expr too. Making
    # it bind tighter than `||` is the one designed mutant with no compiling
    # form: every `a || b` in the tree stops parsing, so the mutant cannot
    # compile the standard library and proves nothing about the pipe. Recorded
    # rather than counted (design: a mutant only counts if it runs first).
    "negative-control-tighter-than-or": (
        PARSER,
        "  var (st1, left) = or_expr(p, st, nb)?\n",
        "  var (st1, left) = and_expr(p, st, nb)?\n",
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    rel, old, new = MUTATIONS[mutation]
    path = root / rel
    path.write_text(replace_once(path.read_text(), old, new, mutation))


if __name__ == "__main__":
    main()
