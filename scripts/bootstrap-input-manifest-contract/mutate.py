#!/usr/bin/env python3
"""Apply one bootstrap input-manifest contract mutation to Planner source."""

from pathlib import Path
import sys


if len(sys.argv) != 3:
    raise SystemExit("usage: mutate.py <mutation> <compiler-plan-source>")

mutation, filename = sys.argv[1:]
path = Path(filename)
text = path.read_text()

if mutation == "drop-deps-recursion":
    old = '''  for key in map.keys(pkg.deps) {
    let child = map.get(pkg.deps, key).expect("resolved package")
    let (next, visited) = collect_source_pkg_inputs(child, inputs, seen)
    inputs = next
    seen = visited
  }
  (inputs, seen)
'''
    new = '''  (inputs, seen)
'''
elif mutation == "drop-package-manifest":
    old = '''    SourceInput { kind: InputFile, path: parent ++ "/dawn.toml" },
    SourceInput { kind: InputTree, path: root }
'''
    new = '''    SourceInput { kind: InputTree, path: root }
'''
elif mutation == "persist-internal-absolute":
    old = '''      if str.starts_with(input.path, prefix) {
        ("R", str.drop(input.path, str.len(prefix)))
      } else {
        ("A", input.path)
      }
'''
    new = '''      if str.starts_with(input.path, prefix) {
        ("A", input.path)
      } else {
        ("A", input.path)
      }
'''
else:
    raise SystemExit(f"unknown mutation: {mutation}")

count = text.count(old)
if count != 1:
    raise SystemExit(f"{mutation} anchor occurs {count} times in {path}")
path.write_text(text.replace(old, new))
