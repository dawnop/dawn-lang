#!/usr/bin/env python3
"""Generate selfhost/src/embed/stdsrc.dawn from std/.

The embedded std used to ride as jar resources read back through
ClassLoader.getSystemResourceAsStream -- a host-specific acquisition path the
native backend cannot share. This generator turns std/modules.txt plus every
module it lists into one ordinary Dawn
module of string constants, so both
backends carry the embedded std the same way they carry any other compiled
code (docs/std-audit.md §2, native-backend-plan §14.20).

Deterministic: output is a pure function of the std/ files. The round-trip
test in stdlib.dawn ("the embedded std matches std/ on disk") fails when this
file is stale, so CI catches a std edit that forgot to regenerate.

std/VERSION is deliberately not embedded. The embedded std's version is the
version of the compiler it is compiled into, by construction, and a second
copy of that number inside the binary would be one more thing that can drift
without being one more thing that can be checked. stdlib.load_std reads the
stamp from the directory only, for the same reason.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STD = ROOT / "std"
OUT = ROOT / "selfhost" / "src" / "embed" / "stdsrc.dawn"


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


# What a module exports as a function: a top-level `pub fn` / `pub(pkg) fn`, and
# the methods of a `pub` trait and the operations of a `pub` effect (indented
# two spaces inside the block, which closes at a `}` in column 0). The loader
# builds StdCtx.moved (the "use std/X, then X.f(...)" hint for a bare name that
# is nobody's) from these, and a pruned load cannot, because it does not parse
# the modules it leaves out. The test in driver/stdlib.dawn holds the rows
# equal to a full load's table, so a std edit this misreads fails there.
EXPORTED_FN = re.compile(r"^pub(?:\(pkg\))? fn ([a-z_][A-Za-z0-9_]*)")
EXPORTED_BLOCK = re.compile(r"^pub(?:\(pkg\))? (?:ctl )?(?:trait|effect) ")
BLOCK_FN = re.compile(r"^  fn ([a-z_][A-Za-z0-9_]*)")


def moved_rows(names: list[str]) -> str:
    rows = []
    for n in names:
        in_block = False
        for line in (STD / (n + ".dawn")).read_text(encoding="utf-8").split("\n"):
            if in_block:
                if line.startswith("}"):
                    in_block = False
                else:
                    m = BLOCK_FN.match(line)
                    if m:
                        rows.append(f"{m.group(1)}\t{n}")
                continue
            m = EXPORTED_FN.match(line)
            if m:
                rows.append(f"{m.group(1)}\t{n}")
            elif EXPORTED_BLOCK.match(line) and line.rstrip().endswith("{"):
                in_block = True
    return "\n".join(rows)


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
    lines.append("## Every exported function of the embedded std as `name<TAB>module` rows, in")
    lines.append("## modules.txt order: what a load that leaves modules out cannot read back out")
    lines.append("## of them (stdlib.moved_table).")
    lines.append("pub fn moved_rows() -> String =")
    lines.append(f"  \"{esc(moved_rows(index_names(idx_text)))}\"")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes, {len(files)} files)")


if __name__ == "__main__":
    main()
