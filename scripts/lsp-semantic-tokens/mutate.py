#!/usr/bin/env python3
"""Apply one mutation of the LSP semantic-tokens contract to a copy of the tree.

Each mutation breaks one decision of selfhost/src/lsp/lsptok.dawn, of the
server arm that encodes its tokens, or of the query context they read, and scripts/lsp-semantic-tokens.py
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
QUERY = "selfhost/src/lsp/lspq.dawn"

# mutation -> (file, anchor, replacement)
MUTATIONS = {
    'no-selective-alias': (QUERY,
        '  match map.get(exp.aliases, imp.name) {\n',
        '  match map.get(exp.aliases, "") {\n'),
    'selective-value-priority': (QUERY,
        '  offer_at(q, imp.lo, imp.hi, text, type_site)\n',
        '  offer_at(q, imp.lo, imp.hi, text, if map.has(exp.consts, imp.name) {\n'
        '    site_of_const_in(qc, exp.mod_path, imp.name)\n'
        '  } else { type_site })\n'),
    'drop-selective-value-reference': (QUERY,
        '      q = collect_also(q, imp.lo, imp.hi, site_of_const_in(qc, exp.mod_path, imp.name), ImportValueUse)\n',
        '      q = q\n'),
    'std-no-bundled-resolutions': (QUERY,
        'fn offer_target(q: Q, t: Target) -> Q = {\n',
        'fn offer_target(q: Q, t: Target) -> Q = {\n'
        '  let unfiled = match t.def_path { Some(FileSource(_)) -> false, Some(_) -> true, None -> false }\n'
        '  if unfiled && q.found != None { return q }\n'),
    'std-values-prefer-types': (QUERY,
        'fn site_of_const_in(qc: QCx, mod_path: String, name: String) -> Site = {\n',
        'fn site_of_const_in(qc: QCx, mod_path: String, name: String) -> Site = {\n'
        '  match holder_by_path(qc, mod_path) {\n'
        '    Some(h) -> { for d in h.m.decls {\n'
        '      match d { DType(t) -> if t.name == name { return site_in(h, t.nlo, t.nhi, t.lo) }, _ -> () }\n'
        '    } }\n'
        '    None -> ()\n'
        '  }\n'),
    'std-no-content-registration': ('selfhost/src/lsp/lspsource.dawn',
        '  match map.get(lib.uris, uri) {\n',
        '  match map.get(lib.uris, "") {\n'),
    'std-planned-entry': (SERVER,
        '        entry_by_uri = checked_entries(ws0.path_by_uri, prog),\n',
        '        entry_by_uri = entry_by_uri,\n'),
    'std-forged-source': (SERVER,
        '  match document_at(st0.library, uri) {\n',
        '  match map.get(st0.library.modules, "std/cursor") {\n'),
    'std-wrong-snapshot': (SERVER,
        '("text", JStr(doc.snapshot.text))',
        '("text", JStr("# wrong 🎈\\n" ++ doc.snapshot.text))'),
    'std-builtin-in-buffer': (QUERY,
        '    Some(t) -> Some(Target { ..t, def_path = match t.def {\n'
        '      Some(_) -> Some(t.def_path.unwrap_or(qc.source))\n'
        '      None -> None\n'
        '    } })\n',
        '    Some(t) -> Some(Target { ..t, def = Some(t.def.unwrap_or((0, 0))),\n'
        '      def_path = Some(t.def_path.unwrap_or(qc.source)) })\n'),
    'std-library-as-file': ('selfhost/src/lsp/lspsource.dawn',
        '    Some(doc) -> if cm.path == doc.checked.path { return doc.id }\n',
        '    Some(doc) -> if cm.path == doc.checked.path { return FileSource(cm.path) }\n'),
    'std-reference-without-source': ('selfhost/src/lsp/lspref.dawn',
        'r.def_path == def_path && r.def == def\n',
        'r.def == def\n'),
    # a constant painted as the type its case resembles
    'const-as-type': (LSPTOK,
        '      DConst(_, _, _, _, _, _, nlo, _) -> { ix = map.insert(ix, nlo, kind(T_VARIABLE, M_READONLY)) }\n',
        '      DConst(_, _, _, _, _, _, nlo, _) -> { ix = map.insert(ix, nlo, kind(T_TYPE, 0)) }\n'),
    # a `var` that reads like a `let`
    'drop-mutable': (LSPTOK,
        '    Some(MutableRole) -> Some(kind(T_VARIABLE, decl + lib + M_MUTABLE))\n',
        '    Some(MutableRole) -> Some(kind(T_VARIABLE, decl + lib))\n'),
    # a range request answered with every token the walked declarations hold
    'range-unclipped': (LSPTOK,
        'fn in_range(r: Resolution, lo: Int, hi: Int) -> Bool = r.lo >= lo && r.lo < hi\n',
        'fn in_range(r: Resolution, lo: Int, hi: Int) -> Bool = r.lo >= 0 || lo + hi >= 0\n'),
    # a query context built on an unchecked entry's own tables, which hold
    # none of the types its `use` lines name (#788)
    'no-import-graft': (SERVER,
        '    entry = with_import_tables(e, seen),\n',
        '    entry = e,\n'),
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
