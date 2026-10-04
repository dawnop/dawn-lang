#!/usr/bin/env python3
"""Apply one mutation of the rename contract to a copy of the tree.

Each mutation breaks one decision of rename in selfhost/src/lsp/server.dawn
or selfhost/src/lsp/lsprename.dawn, and scripts/lsp-rename.py requires the
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
        (SERVER, '    match changed_name(id, before, mr2.refs, by_path, rs.target) {\n',
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
        (SERVER, '    if str.contains(text, "[`") && str.contains(text, "${rs.old}`]") {\n',
         '    if false && str.contains(text, "${rs.old}`]") {\n'),
    ],
    # a [deps] package's declaration is renamed like the project's own
    'dependencies-renamed': [
        (SERVER, '    if package_of(decl.cx) != PkgRoot || not path_in_root(tpath, root) {\n',
         '    if package_of(decl.cx) != PkgRoot && false {\n'),
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
