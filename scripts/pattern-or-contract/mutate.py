#!/usr/bin/env python3
"""Create one compiling checker mutant for the or-pattern contract."""

from pathlib import Path
import sys


name, checker_path = sys.argv[1:]
path = Path(checker_path)
text = path.read_text()


def replace_once(old, new):
    global text
    if text.count(old) != 1:
        raise SystemExit(f"{name}: mutation anchor drifted: {old!r}")
    text = text.replace(old, new)


if name == "drop-binding-set":
    replace_once(
        """      None -> {
        cx1 = cerr_h(cx1, \"or-pattern alternative does not bind `\" ++ want.name ++ \"`\",
          pat_lo(alt), pat_hi(alt), \"every alternative must bind the same names as the first\")
      }
""",
        "      None -> ()\n",
    )
    replace_once(
        """    if pat_bind_named(canonical, got.name) == None {
      cx1 = cerr_h(cx1, \"or-pattern alternative binds extra name `\" ++ got.name ++ \"`\",
        got.lo, got.hi, \"every alternative must bind the same names as the first\")
    }
""",
        "    if false { cx1 = cx1 }\n",
    )
elif name == "drop-binding-type":
    replace_once("        if got.ty != want.ty {", "        if false {")
elif name == "drop-binding-mutability":
    replace_once("        if got.mutable != want.mutable {", "        if false {")
else:
    raise SystemExit(f"unknown mutant: {name}")

path.write_text(text)
