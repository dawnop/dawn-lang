#!/usr/bin/env python3
"""Apply one Object-narrowing mutation to a copy of the selfhost tree.

    scripts/java-narrowing-contract/mutate.py <mutation> <selfhost-root>

The anchors used to live in two Python heredocs inside run.sh, each refusing
a non-unique match. That made them self-once: correct, but checked only when
this contract ran, and each mutant is a `dawn test` of a whole private
selfhost copy. They quote selfhost/src/check/checker.dawn and
selfhost/src/jvm/help.dawn. Declared here, in the registry shape
mutation-anchor-preflight.py already discovers, the same anchors have two
consumers: run.sh applies one mutation per private copy, and the preflight
proves every one of them exactly-once before any build (#254).

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the selfhost root the caller passes, which
is how run.sh lays each mutant out (a copy of selfhost/ beside shared
packages/ and compiler-plan/); the preflight hands this script selfhost/.
"""

from pathlib import Path
import sys

CHECKER = "src/check/checker.dawn"
HELP = "src/jvm/help.dawn"

MUTATIONS = {
    # The Java overload scorer accepts Object for any reference parameter
    # again, the exception the checker's unit test forbids.
    "object-scorer-exception": ((
        CHECKER,
        '''          } else if cx.jsig.is_assignable(p, fq) {
            Some(1)
          } else {
            None
          }''',
        '''          } else if cx.jsig.is_assignable(p, fq) {
            Some(1)
          } else if fq == "java.lang.Object" && not is_prim_name(p) {
            Some(1)
          } else {
            None
          }''',
    ),),
    # adapt_java_arg regains a hidden CHECKCAST from Object; it still
    # compiles, and only the structural half of run.sh can see it.
    "backend-checkcast": (
        (HELP,
         "use check/types.{Ty, TyInt, TyFloat, TyBool, TyString, TyBytes}",
         "use check/types.{Ty, TyInt, TyFloat, TyBool, TyString, TyBytes, TyJava}"),
        (HELP,
         "OP_ANEWARRAY, OP_ASTORE, OP_ATHROW, OP_BIPUSH, OP_D2F",
         "OP_ANEWARRAY, OP_ASTORE, OP_ATHROW, OP_BIPUSH, OP_CHECKCAST, OP_D2F"),
        (HELP,
         '''  } else if dawn_ty == TyFloat && param_cls == "float" {
    m.visitInsn(OP_D2F)
  }
  ()''',
         '''  } else if dawn_ty == TyFloat && param_cls == "float" {
    m.visitInsn(OP_D2F)
  } else {
    match dawn_ty {
      TyJava(fqcn, _) ->
        if fqcn == "java.lang.Object" && not is_prim_name(param_cls) {
          m.visitTypeInsn(OP_CHECKCAST, internal_of(param_cls))
        }
      _ -> ()
    }
  }
  ()'''),
    ),
}


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <selfhost-root>")
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
