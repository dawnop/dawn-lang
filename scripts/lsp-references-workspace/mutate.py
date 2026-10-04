#!/usr/bin/env python3
"""Apply one mutation of the workspace references contract to a copy of the tree.

Each mutation breaks one decision of the workspace search in
selfhost/src/lsp/server.dawn, of the index it reads (selfhost/src/lsp/lspref.dawn)
or of the walk that index is read from (selfhost/src/lsp/lspq.dawn), and
scripts/lsp-references-workspace.py requires the mutant to compile and turn
its owning case red. The registry lives here, not in that script, so that
scripts/mutation-anchor-preflight.py proves every anchor matches exactly once
before any compiler is built; an anchor that drifts is a red preflight rather
than a mutant that silently changes nothing. A mutation is a list of edits,
each applied exactly once.
"""
from pathlib import Path
import sys

SERVER = "selfhost/src/lsp/server.dawn"
LSPREF = "selfhost/src/lsp/lspref.dawn"
LSPQ = "selfhost/src/lsp/lspq.dawn"

# mutation -> [(file, anchor, replacement)]
MUTATIONS = {
    # the search reads only the modules of open documents (what a client-side
    # search over the open editors gives)
    'open-documents-only': [
        (SERVER, '    let id = map.get(ident, cm.path).expect("module identity")\n',
         '    let id = map.get(ident, cm.path).expect("module identity")\n'
         '    if not map.has(uri_of, id) { continue }\n'),
    ],
    # the names of a selective import resolve to nothing
    'import-list-unresolved': [
        (LSPQ, '              for imp in names { q = visit_selective(qc, q, e, imp) }\n',
         '              let _ = names\n'),
    ],
    # an index entry kept although its module was checked again
    'index-outlives-its-step': [
        (SERVER, '        if set.has(checked.reused, mod_path) { refs = map.insert(refs, mod_path, mr) }\n',
         '        refs = map.insert(refs, mod_path, mr)\n'),
    ],
    # the diagnostics build loads the whole tree, as the references program
    # does: every editor session pays for it, and publishes a module nothing
    # open imports
    'diagnostics-load-whole-tree': [
        (SERVER, '      let reusing = load_entries_reusing(ws0.plan, entries, overlay, ws0.parses)\n',
         '      let reusing = load_entries_reusing(ws0.plan, entries ++ project_seeds(ws0.plan), overlay, ws0.parses)\n'),
    ],
    # an entry whose module was reused keeps the sites it read in a file
    # edited since, instead of moving them with the edit
    'sites-not-moved': [
        (LSPREF, '          Some(d) -> { next = next ++ [Ref { ..r, def: d }] }\n',
         '          Some(_) -> { next = next ++ [r] }\n'),
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
