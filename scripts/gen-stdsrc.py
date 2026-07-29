#!/usr/bin/env python3
"""Generate selfhost/src/stdsrc.dawn from std/.

The embedded std used to ride as jar resources read back through
ClassLoader.getSystemResourceAsStream -- a host-specific acquisition path the
native backend cannot share. This generator turns std/modules.txt plus every
module it lists into one ordinary Dawn module of string constants, so both
backends carry the embedded std the same way they carry any other compiled
code (docs/std-audit.md §2, native-backend-plan §14.20).

Deterministic: output is a pure function of the std/ files. The round-trip
test in stdlib.dawn ("the embedded std matches std/ on disk") fails when this
file is stale, so CI catches a std edit that forgot to regenerate.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STD = ROOT / "std"
OUT = ROOT / "selfhost" / "src" / "stdsrc.dawn"


def index_names(text: str) -> list[str]:
    # mirror stdlib.read_index: one name per line, '#' comments, blanks skipped
    names = []
    for line in text.split("\n"):
        cut = line.split("#", 1)[0].strip()
        if cut:
            names.append(cut)
    return names


def esc(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "$":
            out.append("\\$")
        elif ord(ch) < 0x20:
            sys.exit(f"std source contains an unescapable control char U+{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def main() -> None:
    idx_text = (STD / "modules.txt").read_text(encoding="utf-8")
    files = ["modules.txt"] + [n + ".dawn" for n in index_names(idx_text)]

    lines = [
        "## GENERATED FILE -- do not edit. Regenerate with `python3 scripts/gen-stdsrc.py`",
        "## after any edit under std/; the round-trip test in stdlib.dawn fails when stale.",
        "##",
        "## The embedded standard library: std/modules.txt and every module it lists,",
        "## verbatim, as string constants. stdlib.std_read falls back to this when the",
        "## --std directory is absent, which is what makes a standalone toolchain",
        "## self-contained on every backend without a host resource API",
        "## (docs/std-audit.md §2, native-backend-plan §14.20).",
        "",
        "## The file's text, or None for a name that is not part of the embedded std.",
        "pub fn source(name: String) -> Option[String] =",
    ]
    first = True
    for f in files:
        text = (STD / f).read_text(encoding="utf-8")
        kw = "if" if first else "} else if"
        first = False
        lines.append(f"  {kw} name == \"{f}\" {{")
        lines.append(f"    Some(\"{esc(text)}\")")
    lines.append("  } else {")
    lines.append("    None")
    lines.append("  }")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes, {len(files)} files)")


if __name__ == "__main__":
    main()
