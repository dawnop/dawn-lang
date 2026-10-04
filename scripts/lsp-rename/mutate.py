#!/usr/bin/env python3
"""Apply one mutation of the rename contract to a copy of the tree.

Each mutation breaks one decision of rename in selfhost/src/lsp/server.dawn
or selfhost/src/lsp/lsprename.dawn, or of the references walk it reads
(selfhost/src/lsp/lspq.dawn, lsptok.dawn, selfhost/src/front/docs.dawn), and scripts/lsp-rename.py requires the
mutant to compile and turn its owning case red. The registry lives here, not
in that script, so that scripts/mutation-anchor-preflight.py proves every
anchor matches exactly once before any compiler is built; an anchor that
drifts is a red preflight rather than a mutant that silently changes nothing.
A mutation is a list of edits, each applied exactly once.
"""
from pathlib import Path
import sys

SERVER = "selfhost/src/lsp/server.dawn"
LSPRENAME = "selfhost/src/lsp/lsprename.dawn"
LSPQ = "selfhost/src/lsp/lspq.dawn"
LSPTOK = "selfhost/src/lsp/lsptok.dawn"
DOCS = "selfhost/src/front/docs.dawn"

# mutation -> [(file, anchor, replacement)]
MUTATIONS = {
    # a new name of the other case class is let through to the compiler,
    # which refuses it with a message about the program, not the name
    'case-class-unchecked': [
        (LSPRENAME, '  if upper != was {\n', '  if upper != was && false {\n'),
    ],
    # the edited module is compared against itself: a name that now resolves
    # to the renamed declaration (a builtin it shadows) goes unnoticed
    'resolutions-unchecked': [
        (SERVER, '    match changed_name(id, before, mr2.refs, ixs, rs.target) {\n',
         '    match changed_name(id, mr2.refs, mr2.refs, map.empty(), rs.target) {\n'),
    ],
    # an error the edit introduces does not refuse it
    'diagnostics-unchecked': [
        (SERVER, '    if n > map.get(before_counts, id).unwrap_or(0) {\n',
         '    if false && n > map.get(before_counts, id).unwrap_or(0) {\n'),
    ],
    # a record pun is renamed in place, so its other half is renamed too
    'puns-not-spelled-out': [
        (SERVER, 'name_edit(id, r.lo, r.hi, r.pun, rs.old, new)',
         'name_edit(id, r.lo, r.hi, NotPun, rs.old, new)'),
    ],
    # a name an import list's `as` bound is renamed with the declaration
    'as-names-renamed': [
        (SERVER, '      if slice_cps(cs, r.lo, r.hi) == rs.old {',
         '      if slice_cps(cs, r.lo, r.hi) != "" {'),
    ],
    # doc links keep the old name, and `dawn doc` fails on them
    'doc-links-skipped': [
        (SERVER, '    if str.contains(text, "[`") && str.contains(text, rs.old) {\n',
         '    if false && str.contains(text, rs.old) {\n'),
    ],
    # a [deps] package's declaration is renamed like the project's own
    'dependencies-renamed': [
        (SERVER, '    if package_of(decl.cx) != PkgRoot || not path_in_root(tpath, root) {\n',
         '    if package_of(decl.cx) != PkgRoot && false {\n'),
    ],
    # a parameter's default is not read: the call in it keeps the old name,
    # and the builtin it now reaches answers it
    'defaults-unread': [
        (LSPQ, '      Some(dx) -> { q = walk_e(qc, q, dx, tdefault_body(tf, k)) }\n',
         '      Some(dx) -> ()\n'),
    ],
    # rename trusts the references program it already holds, and a file
    # edited on disk with no notification is read as it was
    'disk-unread': [
        (SERVER, '      if w.current && not (verify && world_stale(ws, w)) { return Some(w) }\n',
         '      if w.current { return Some(w) }\n'),
    ],
    # the tree is the one walked when the workspace was planned, and a
    # module created since is never read
    'tree-not-rewalked': [
        (SERVER, '  for f in project_files_now(plan) {\n',
         '  for f in (if true { plan.modules.project_files } else { project_files_now(plan) }) {\n'),
    ],
    # a watched-file notification for a module leaves the references
    # program as it was
    'watch-ignored': [
        (SERVER, '    st = sources_changed(st, params)\n', ''),
    ],
    # a name is cut at its first letter outside ASCII, and `café` renamed
    # leaves `grow` + `é`
    'names-ascii-only': [
        (LSPTOK, "fn is_name_char(c: Char) -> Bool = char_is_alnum(c) || c == '_'\n",
         "fn is_name_char(c: Char) -> Bool = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'\n"),
    ],
    # a name spelled like an `as` import is taken for it, even qualified
    'as-name-by-spelling': [
        (SERVER, '  let as_name = import_alias(entry.m, old) && declared != Some(old)\n',
         '  let as_name = import_alias(entry.m, old) || declared == Some("")\n'),
    ],
    # a constant's `as` name is looked up under itself in its module
    'const-alias-unrenamed': [
        (LSPQ, '    Some(mp) -> site_of_const_in(qc, mp, unwrap_or(map.get(qc.entry.cx.import_renames, name), name))\n',
         '    Some(mp) -> site_of_const_in(qc, mp, name)\n'),
    ],
    # `C.Item` names nothing
    'projection-subject-skipped': [
        (LSPQ, '    TAssoc(subject, _, lo, _) -> { q = offer_type_name(qc, q, subject, lo, lo + str.len(subject)) }\n',
         '    TAssoc(_, _, _, _) -> ()\n'),
    ],
    # `effect E = !Ask` names nothing
    'effect-binding-skipped': [
        (LSPQ, '      for eb in eff_binds { q = offer_row(qc, q, past_eq(qc.cps, eb.nhi, eb.hi), eb.hi) }\n',
         '      for eb in eff_binds { q = offer_row(qc, q, past_eq(qc.cps, eb.hi, eb.hi), eb.hi) }\n'),
    ],
    # `test f` names nothing
    'example-title-skipped': [
        (LSPQ, '        Some(of) -> { q = offer_example(qc, q, of, nlo) }\n',
         '        Some(of) -> { q = if false { offer_example(qc, q, of, nlo) } else { q } }\n'),
    ],
    # a trait default method's parameters are not declared anywhere
    'trait-default-params-skipped': [
        (LSPQ, '            q = offer_params(qc, q, m.params, tf)\n',
         '            q = offer_params(qc, q, [], tf)\n'),
    ],
    # a qualified type's member is found by counting one dot past its module
    'qualified-member-by-length': [
        (LSPQ, '  let nlo = member_start(qc.cps, lo + str.len(qual))\n',
         '  let nlo = lo + str.len(qual) + 1\n'),
    ],
    # a comment in a type's parameter list is read for binders
    'binders-read-comments': [
        (LSPQ, "    if c == '#' {\n      # a comment inside the list: its words are not binders\n",
         "    if false {\n      # a comment inside the list: its words are not binders\n"),
    ],
    # only a doc link's last segment is renamed, never its owner
    'link-owner-skipped': [
        (SERVER, '          if slice_cps(cs, alo, ahi) != rs.old { continue }\n',
         '          if slice_cps(cs, alo, ahi) != rs.old || prefix != ltext { continue }\n'),
    ],
    # any fence closes any fence, so the inner one ends the outer
    'fences-by-prefix': [
        (DOCS, '        if n > 0 && c == oc && n >= on && str.trim(str.drop(t, n)) == "" { fence = None }\n',
         '        if n > 0 || (c == oc && on < 0) { fence = None }\n'),
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
