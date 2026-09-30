#!/usr/bin/env python3
"""Apply one classfile-verify compiler mutation to a copy of the repository tree.

    scripts/classfile-verify/mutate.py <mutation> <tree-root>

The anchors used to be arguments to a `replace_never_once` shell helper in
run.sh, about twenty of them, each refused unless it matched exactly once. That
made them self-once: correct, but checked only by whoever ran this contract,
which builds seventeen mutant compilers. They quote the two files this
repository edits most (jvm/emit.dawn and check/checker.dawn), so a rewrite
there went unnoticed until the next full run (#254, after #249 found the same
gap in delete-contract). Declared here, in the registry shape
mutation-anchor-preflight.py already discovers, the same anchors have two
consumers: run.sh applies one mutation per mutant compiler, and the preflight
proves every one of them exactly-once before any build.

A mutation is an ordered tuple of edits, applied one after another to the text
the previous edit left, which is how run.sh applied the two-edit mutants. The
paths are relative to the tree root the caller passes: run.sh lays each mutant
out as `<root>/selfhost`, so the preflight can hand this script the checkout.

The byte-level mutators this contract also carries, athrow.py and
privatise.py, rewrite emitted class files rather than source, and live apart
from this registry for that reason.
"""

from pathlib import Path
import sys

EMIT = "selfhost/src/jvm/emit.dawn"
CHECKER = "selfhost/src/check/checker.dawn"


def call_bottom(invoke):
    # The direct, impl, default and trait call sites share one tail: the
    # instruction, then finish_call. The mutant drops finish_call, so a call
    # whose result is Never no longer terminates the path.
    return ((
        EMIT,
        f"""{invoke}
      finish_call(g1, ty, call_result_of_desc(d))""",
        f"""{invoke}
      (g1, true)""",
    ),)


def adapter_returns(sam_ret, pop, value, ret):
    # A bottom SAM adapter that returns a default value on a path the verifier
    # accepts instead of throwing: legal bytes, wrong semantics.
    return ((
        EMIT,
        """  if s.bottom {
    terminate_bottom(m, call_result_of_desc(rd))
  } else {""",
        f"""  if s.bottom {{
    if s.sam_ret == "{sam_ret}" {{
      let terminate = Label.new()
      m.visitInsn({pop})
      m.visitInsn(OP_ICONST_1)
      m.visitJumpInsn(OP_IFEQ, terminate)
      {value}
      m.visitInsn({ret})
      m.visitLabel(terminate)
      m.visitInsn(OP_ACONST_NULL)
      m.visitInsn(OP_ATHROW)
    }} else {{
      terminate_bottom(m, call_result_of_desc(rd))
    }}
  }} else {{""",
    ),)


MUTATIONS = {
    # The Never block (run.sh --never-mutants-only), in run order.
    "omit-statement-fallthrough": ((
        EMIT,
        "        if not stmt_falls { return (g1, false) }",
        "        if false { return (g1, false) }",
    ),),
    "reject-wide-sam-bottom": ((
        CHECKER,
        "    r == TyInt || r == TyNever",
        "    r == TyInt",
    ),),
    "use-pop-for-wide-bottom": (
        (EMIT,
         "    CallTwo -> { m.visitInsn(OP_POP2) }",
         "    CallTwo -> { m.visitInsn(OP_POP) }"),
        # OP_POP2's import goes with its only use: an unused import is an error
        (EMIT,
         "OP_NEW, OP_POP, OP_POP2, OP_PUTFIELD",
         "OP_NEW, OP_POP, OP_PUTFIELD"),
    ),
    "omit-direct-bottom": call_bottom(
        "      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner, name, d, false)"),
    "omit-dynamic-bottom": ((
        EMIT,
        "  if is_bottom(ret_static) {",
        "  if false {",
    ),),
    "omit-impl-bottom": call_bottom(
        """      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        impl_method_name(gx, tr.name, subject, method), d, false)"""),
    "omit-default-bottom": call_bottom(
        """      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        default_method_name(tr.name, method), d, false)"""),
    "omit-trait-bottom": call_bottom(
        """      g1.mv.visitMethodInsn(OP_INVOKEINTERFACE, tr_iface(tr.owner, tr.name), method,
        d, true)"""),
    "omit-dictionary-bottom": ((
        EMIT,
        "    if is_bottom(ms.sig.ret) {",
        "    if false {",
    ),),
    "omit-closure-bottom": ((
        EMIT,
        "  if is_bottom(b.fret) {",
        "  if false {",
    ),),
    "omit-sam-bridge-bottom": ((
        EMIT,
        "  if b.bottom {",
        "  if false {",
    ),),
    "omit-sam-adapter-bottom": ((
        EMIT,
        "  if s.bottom {",
        '  if s.bottom && s.sam_ret != "java.lang.Object" {',
    ),),
    "return-from-object-sam-adapter": adapter_returns(
        "java.lang.Object", "OP_POP", "m.visitInsn(OP_ACONST_NULL)", "OP_ARETURN"),
    "return-from-wide-sam-adapter": adapter_returns(
        "long", "OP_POP2", "ldc_long(m, 0)", "OP_LRETURN"),
    # The loop-operand and constructor mutants (run.sh --without-never-mutants).
    "unspilled-loop-operands": ((
        EMIT,
        "operands.prepare(cf.body, gx.next_sym)",
        "cf.body",
    ),),
    "unspilled-java-operands": (
        (EMIT, "if operands.foreign_jumps(jc) {", "if false {"),
        (EMIT, "let spill = operands.foreign_jumps(jc)", "let spill = false"),
    ),
    "late-java-constructor-init": (
        (EMIT,
         """g.mv.visitTypeInsn(OP_NEW, owner)
    let (g0, receiver) = spill_java_value(g, "Ljava/lang/Object;")""",
         """g.mv.visitInsn(OP_ACONST_NULL)
    let (g0, receiver) = spill_java_value(g, "Ljava/lang/Object;")"""),
        (EMIT,
         "reload_java_values(g1, [receiver])",
         "g1.mv.visitTypeInsn(OP_NEW, owner)"),
    ),
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
