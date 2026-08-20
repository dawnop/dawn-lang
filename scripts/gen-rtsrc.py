#!/usr/bin/env python3
"""Generate selfhost/src/embed/rtsrc.dawn from runtime/c/.

The native driver's `build` writes the C runtime next to the C it emits and
hands both to cc, so a standalone native toolchain needs the runtime the same
way it needs std: embedded, not discovered (native-backend-plan §14.1, and the
mode-C verdict in docs/std-audit.md §2). Same shape as gen-stdsrc.py: one
ordinary Dawn module of string constants, checked in, with a round-trip test
(in cdriver.dawn) that fails when a runtime edit forgot to regenerate.

The JVM constant pool caps one string literal at 64KB of modified UTF-8; the
runtime is ASCII, so bytes == UTF-8 length. A file past the budget is split at
line boundaries into several literals joined by `++` -- a runtime concat in an
ordinary `fn`, not a `const`, so comptime folding never puts it back together.
dawn_rt.c crossed the budget on 2026-08-01; the cap itself was not raised.
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RT = ROOT / "runtime" / "c"
OUT = ROOT / "selfhost" / "src" / "embed" / "rtsrc.dawn"
FILES = ["dawn_rt.c", "dawn_rt.h", "dawn_rt_wasi_eh.cc"]
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


def split(text: str, limit: int) -> list[str]:
    """`text` in as few pieces of at most `limit` bytes as it takes, cut at
    line boundaries and balanced so the pieces come out about even."""
    raw = len(text.encode("utf-8"))
    parts = max(1, -(-raw // limit))
    target = -(-raw // parts)
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for line in text.splitlines(keepends=True):
        w = len(line.encode("utf-8"))
        if n > 0 and n + w > target and len(out) < parts - 1:
            out.append("".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += w
    out.append("".join(cur))
    for piece in out:
        if len(piece.encode("utf-8")) > limit:
            sys.exit(f"a single line exceeds the {limit}-byte literal budget")
    return out


def main() -> None:
    lines = [
        "## GENERATED FILE -- do not edit. Regenerate with `python3 scripts/gen-rtsrc.py`",
        "## after any edit under runtime/c/; the round-trip test in cdriver.dawn fails",
        "## when stale.",
        "##",
        "## The embedded C runtime: what the native driver's `build` writes beside the",
        "## emitted C so a standalone toolchain needs no runtime directory on disk.",
        "##",
        "## A file arrives in several literals joined by `++` once it outgrows what one",
        "## JVM constant-pool entry holds. This is a `fn`, so that is a runtime concat.",
        "",
        "## The file's text, or None for a name that is not part of the runtime.",
        "pub fn source(name: String) -> Option[String] =",
    ]
    first = True
    for f in FILES:
        text = (RT / f).read_text(encoding="utf-8")
        kw = "if" if first else "} else if"
        first = False
        body = " ++ ".join(f'"{esc(piece)}"' for piece in split(text, LIMIT))
        lines.append(f"  {kw} name == \"{f}\" {{")
        lines.append(f"    Some({body})")
    lines.append("  } else {")
    lines.append("    None")
    lines.append("  }")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes, {len(FILES)} files)")


if __name__ == "__main__":
    main()
