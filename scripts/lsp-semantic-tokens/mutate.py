#!/usr/bin/env python3
"""Apply one mutation of the LSP semantic-tokens contract to a copy of the tree.

Each mutation breaks one decision of selfhost/src/lsp/lsptok.dawn or of the
server arm that encodes its tokens, and scripts/lsp-semantic-tokens.py
requires the mutant to compile and turn its owning case red. The registry
lives here, not in that script, so that scripts/mutation-anchor-preflight.py
proves every anchor matches exactly once before any compiler is built; an
anchor that drifts is a red preflight rather than a mutant that silently
changes nothing.
"""
from pathlib import Path
import sys

LSPTOK = "selfhost/src/lsp/lsptok.dawn"
SERVER = "selfhost/src/lsp/server.dawn"

# mutation -> (file, anchor, replacement)
MUTATIONS = {
    # a constant painted as the type its case resembles
    'const-as-type': (LSPTOK,
        '      DConst(_, _, _, _, _, _, nlo, _) -> { ix = map.insert(ix, nlo, kind(T_VARIABLE, M_READONLY)) }\n',
        '      DConst(_, _, _, _, _, _, nlo, _) -> { ix = map.insert(ix, nlo, kind(T_TYPE, 0)) }\n'),
    # a `var` that reads like a `let`
    'drop-mutable': (LSPTOK,
        '    Some(MutableRole) -> Some(kind(T_VARIABLE, decl + M_MUTABLE))\n',
        '    Some(MutableRole) -> Some(kind(T_VARIABLE, decl))\n'),
    # a range request answered with every token the walked declarations hold
    'range-unclipped': (LSPTOK,
        'fn in_range(r: Resolution, lo: Int, hi: Int) -> Bool = r.lo >= lo && r.lo < hi\n',
        'fn in_range(r: Resolution, lo: Int, hi: Int) -> Bool = r.lo >= 0 || lo + hi >= 0\n'),
    # columns counted in UTF-8 bytes from the line start instead of UTF-16 units
    'columns-in-bytes': (SERVER,
        '                let (line, col) = lsp_position(d.view, d.ls, t.lo)\n'
        '                let (eline, ecol) = lsp_position(d.view, d.ls, t.hi)\n',
        '                let line = line_of(d.ls, t.lo)\n'
        '                var col = 0\n'
        '                var i = d.ls[line]\n'
        '                while i < t.lo {\n'
        '                  let cp = char.code(d.view.cps[i])\n'
        '                  col = col + if cp < 128 { 1 } else if cp < 2048 { 2 } else if cp < 65536 { 3 } else { 4 }\n'
        '                  i = i + 1\n'
        '                }\n'
        '                let eline = line\n'
        '                let ecol = col + t.hi - t.lo\n'),
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
    rel, old, new = MUTATIONS[mutation]
    path = root / rel
    path.write_text(replace_once(path.read_text(), old, new, mutation))


if __name__ == "__main__":
    main()
