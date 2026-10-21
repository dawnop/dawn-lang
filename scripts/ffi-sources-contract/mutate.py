#!/usr/bin/env python3
"""Omit the transitive leaf from the actual loaded package collection.

The harness first builds this compiler successfully, then requires its
package build to fail for the missing leaf stub. Preflight owns this anchor.
"""
from pathlib import Path
import sys

MUTATIONS = {
    "omit-transitive": (("selfhost/src/c/natives.dawn",
        "if not list.contains(dirs, dir) { dirs = dirs ++ [dir] }",
        'if pkg.name != "leaf" && not list.contains(dirs, dir) { dirs = dirs ++ [dir] }'),),
}


def main():
    name, root = sys.argv[1], Path(sys.argv[2])
    for rel, old, new in MUTATIONS[name]:
        path = root / rel
        source = path.read_text()
        assert source.count(old) == 1, (name, rel, source.count(old))
        path.write_text(source.replace(old, new))


if __name__ == "__main__":
    main()
