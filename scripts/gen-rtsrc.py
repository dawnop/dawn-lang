#!/usr/bin/env python3
"""Generate selfhost/src/rtsrc.dawn from runtime/c/.

The native driver's `build` writes the C runtime next to the C it emits and
hands both to cc, so a standalone native toolchain needs the runtime the same
way it needs std: embedded, not discovered (native-backend-plan §14.1, and the
mode-C verdict in docs/std-audit.md §2). Same shape as gen-stdsrc.py: one
ordinary Dawn module of string constants, checked in, with a round-trip test
(in cdriver.dawn) that fails when a runtime edit forgot to regenerate.

The JVM constant pool caps one string literal at 64KB of modified UTF-8; the
runtime is ASCII, so bytes == UTF-8 length. The guard leaves headroom -- when
dawn_rt.c outgrows it, teach this generator to chunk before raising the cap.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RT = ROOT / "runtime" / "c"
OUT = ROOT / "selfhost" / "src" / "rtsrc.dawn"
FILES = ["dawn_rt.c", "dawn_rt.h"]
LIMIT = 60000


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
            sys.exit(f"runtime source contains an unescapable control char U+{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def main() -> None:
    lines = [
        "## GENERATED FILE -- do not edit. Regenerate with `python3 scripts/gen-rtsrc.py`",
        "## after any edit under runtime/c/; the round-trip test in cdriver.dawn fails",
        "## when stale.",
        "##",
        "## The embedded C runtime: what the native driver's `build` writes beside the",
        "## emitted C so a standalone toolchain needs no runtime directory on disk.",
        "",
        "## The file's text, or None for a name that is not part of the runtime.",
        "pub fn source(name: String) -> Option[String] =",
    ]
    first = True
    for f in FILES:
        text = (RT / f).read_text(encoding="utf-8")
        raw = len(text.encode("utf-8"))
        if raw > LIMIT:
            sys.exit(
                f"{f} is {raw} bytes; the single-literal budget is {LIMIT} "
                "(JVM constant-pool cap with headroom). Teach gen-rtsrc.py to chunk."
            )
        kw = "if" if first else "} else if"
        first = False
        lines.append(f"  {kw} name == \"{f}\" {{")
        lines.append(f"    Some(\"{esc(text)}\")")
    lines.append("  } else {")
    lines.append("    None")
    lines.append("  }")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes, {len(FILES)} files)")


if __name__ == "__main__":
    main()
