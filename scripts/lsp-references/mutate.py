#!/usr/bin/env python3
"""Apply one mutation of the LSP references contract to a copy of the tree.

Each mutation breaks one decision of selfhost/src/lsp/lspref.dawn or of the
walk in selfhost/src/lsp/lspq.dawn it reads, and scripts/lsp-references.py
requires the mutant to compile and turn its owning case red. The registry
lives here, not in that script, so that scripts/mutation-anchor-preflight.py
proves every anchor matches exactly once before any compiler is built; an
anchor that drifts is a red preflight rather than a mutant that silently
changes nothing. A mutation is a list of edits, each applied exactly once.
"""
from pathlib import Path
import sys

LSPREF = "selfhost/src/lsp/lspref.dawn"
LSPQ = "selfhost/src/lsp/lspq.dawn"

# mutation -> [(file, anchor, replacement)]
MUTATIONS = {
    # a text search: every resolved name spelled like the asked one
    'match-by-name': [
        (LSPREF, 'use lsp/lsptok.{name_runs}\n', 'use lsp/lsptok.{name_runs}\nuse front/lexer.{slice_cps}\n'),
        (LSPREF, '    if same_decl(r, t.def_path, def) {\n',
         '    if slice_cps(qc.cps, r.lo, r.hi) == slice_cps(qc.cps, t.lo, t.hi) {\n'),
    ],
    # includeDeclaration read as false whatever the client asked
    'drop-declaration': [
        (LSPREF, '      if with_decl || not o.decl { found = found ++ [o] }\n',
         '      if not o.decl { found = found ++ [o] }\n'),
    ],
    # a pun counted as the local only: the field it names loses it
    'pun-one-way': [
        (LSPQ, '    Some(_) -> collect_also(q, lo, hi, site_of_ctor_field(qc, aid, ci, fi), PunUse)\n',
         '    Some(_) -> q\n'),
    ],
    # a call of a parameter answered by the top-level function of its name
    'local-call-by-name': [
        (LSPQ, '      q = offer_local_use(qc, q, sid, clo, chi)\n      q = walk_call_args(qc, q, args, targs)\n',
         '      match sig_of(qc, callee) {\n'
         '        Some(s) -> { q = offer_sig_at(qc, q, clo, chi, s, site_of_sig(qc, s)) }\n'
         '        None -> ()\n'
         '      }\n'
         '      q = walk_call_args(qc, q, args, targs)\n'),
    ],
}


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: mutation anchor occurs {count} times")
    return text.replace(old, new)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: mutate.py <mutation> <tree-root>")
    mutation, root = sys.argv[1], Path(sys.argv[2])
    if mutation not in MUTATIONS:
        raise SystemExit(f"unknown mutation: {mutation}")
    for rel, old, new in MUTATIONS[mutation]:
        path = root / rel
        path.write_text(replace_once(path.read_text(), old, new, mutation))


if __name__ == "__main__":
    main()
