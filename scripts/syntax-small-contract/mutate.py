#!/usr/bin/env python3
"""Apply one syntax-small compiler mutation to a copy of the repository tree.

    scripts/syntax-small-contract/mutate.py <mutation> <tree-root>

The anchors used to live in five Python heredocs inside run.sh, each refusing
a non-unique match. That made them self-once: correct, but checked only by
whoever ran this contract, and each mutant is a whole compiler build. They
quote front/parser.dawn and check/passes.dawn, two of the files this
repository edits most, so a rewrite there went unnoticed until a syntax shard
next built that mutant (#254, after #249 found the same gap in
delete-contract). Declared here, in the registry shape
mutation-anchor-preflight.py already discovers, the same anchors have two
consumers: run.sh applies one mutation per mutant compiler, and the preflight
proves every one of them exactly-once before any build.

A mutation is an ordered tuple of edits, each applied to the text the previous
one left. The paths are relative to the tree root the caller passes: run.sh
lays each mutant out as `<root>/selfhost`, so the preflight can hand this
script the checkout.
"""

from pathlib import Path
import sys

PARSER = "selfhost/src/front/parser.dawn"
PASSES = "selfhost/src/check/passes.dawn"

# The checker's singleton/nullary test, which two mutants replace differently.
BUILTIN_ALIAS = "        let builtin_alias = len(d.ctors) == 1 && len(c.fields) == 0\n"

TYPE_DECL = "fn type_decl(p: P, st: St, vis: Vis) -> PR[Decl] = {\n"

MUTATIONS = {
    # The declaration-recovery anchor stops at contextual `opaque type`.
    "drop-opaque-anchor": ((
        PARSER,
        """    Some(head) -> match head.kind {
      HBadOpaque -> false
      HBadCtl -> false
      _ -> true
    }
""",
        """    Some(head) -> match head.kind {
      HBadOpaque -> false
      HBadCtl -> false
      HOpaqueType -> false
      _ -> true
    }
""",
    ),),
    # A bare `return` no longer stops at `]`.
    "drop-rbracket-return-boundary": ((
        PARSER,
        "  k == NEWLINE || k == RBRACE || k == RPAREN || k == RBRACKET || k == COMMA || k == EOF\n",
        "  k == NEWLINE || k == RBRACE || k == RPAREN || k == COMMA || k == EOF\n",
    ),),
    # The parser decides builtin scalar aliases again, ahead of the checker.
    "restore-parser-builtin-branch": (
        (PARSER,
         TYPE_DECL,
         """fn is_builtin_scalar(name: String) -> Bool =
  match name {
    "Int" | "Float" | "Bool" | "String" | "Unit" -> true
    _ -> false
  }

""" + TYPE_DECL),
        (PARSER,
         """  let aliasish = at_kind(p, st4, FN) || at_kind(p, st4, LPAREN) ||
    (at_kind(p, st4, TYPEIDENT) && kind_ahead(p, st4, 1) == LBRACKET)
""",
         """  let builtin_scalar = at_kind(p, st4, TYPEIDENT) && is_builtin_scalar(cur(p, st4).text) &&
    kind_ahead(p, st4, 1) != LPAREN
  let aliasish = at_kind(p, st4, FN) || at_kind(p, st4, LPAREN) ||
    (at_kind(p, st4, TYPEIDENT) && kind_ahead(p, st4, 1) == LBRACKET) || builtin_scalar
"""),
    ),
    # Two builtin aliases lose the shared checker hint.
    "narrow-checker-builtin-hint": ((
        PASSES,
        BUILTIN_ALIAS,
        """        let builtin_alias = len(d.ctors) == 1 && len(c.fields) == 0 &&
          c.name != "Char" && c.name != "Bytes"
""",
    ),),
    # Every builtin constructor gets the alias hint, nullary or not.
    "drop-builtin-alias-boundary": ((
        PASSES,
        BUILTIN_ALIAS,
        "        let builtin_alias = true\n",
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
