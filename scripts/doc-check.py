#!/usr/bin/env python3
"""Documentation CI (TEST-04).

The audit's argument is its own evidence: README's front-page example had
the wrong interpolation syntax, the tutorial's install command did not run,
and the EBNF disagreed with the parser in several places -- all found by a
human reading, none by a test. This script is the part of that gap a script
can close.

Three checks, each unambiguous on purpose (a doc lint with false positives
gets disabled, and then it protects nothing):

  links     every relative Markdown link resolves to a file in the repo
  anchors   every same-file `#fragment` link matches a heading in that file
  blocks    every fenced block marked ```dawn run / ```dawn compile is
            compiled (and run) by the toolchain
  status    every document under docs/ declares its status near the top

Blocks are opt-in rather than opt-out: most examples in the spec are
fragments -- a type declaration, three lines of a match -- and demanding
that they be whole modules would either mangle the prose or drown the check
in exemptions. A block whose correctness matters says so in its info string.

  ./scripts/doc-check.py
"""

import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAWN = ROOT / "bin" / "dawn"

# every tracked Markdown file, including the top-level ones
DOCS = sorted(
    [p for p in (ROOT / "docs").rglob("*.md")]
    + [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "CONTRIBUTING.md"]
)

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
FENCE = re.compile(r"^```(dawn(?:\s+\w+)?)\s*$(.*?)^```\s*$", re.M | re.S)


def slug(heading: str) -> str:
    """GitHub's heading slug, as far as this repo's headings exercise it:
    inline code/emphasis markers dropped, spaces to hyphens, punctuation
    removed, lowercased. CJK is kept -- it is word text, not punctuation."""
    h = re.sub(r"`([^`]*)`", r"\1", heading)
    h = re.sub(r"[*_]", "", h)
    h = h.strip().lower()
    h = re.sub(r"[^\w-￿\s-]", "", h)
    return re.sub(r"\s+", "-", h)


def prose_only(text: str) -> str:
    """Markdown with code removed. Dawn's own syntax collides with the link
    form -- `map[T](xs: List[T])` reads as a link to a file called
    "xs: List[T]" -- so fenced blocks and inline spans are blanked (newlines
    kept, so nothing downstream needs to care about offsets)."""
    out = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"), text,
                 flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", out)


def check_links(path: pathlib.Path, text: str) -> list[str]:
    bad = []
    anchors = {slug(m) for m in HEADING.findall(text)}
    text = prose_only(text)
    for target in LINK.findall(text):
        t = target.strip()
        if t.startswith(("http://", "https://", "mailto:")):
            continue
        if t.startswith("#"):
            if t[1:] not in anchors:
                bad.append(f"{path.relative_to(ROOT)}: anchor {t} matches no heading")
            continue
        file_part = t.split("#", 1)[0]
        if not file_part:
            continue
        # Not a path, so not a link: Dawn's type syntax has the same shape as
        # a Markdown link (`same2[T](x: Option[T], y: Option[T])`), and code
        # is not always fenced or backticked -- an indented line inside a
        # blockquote is code too. No path in this repository has a space or a
        # bracket in it, so that is the discriminator; a genuinely broken link
        # with a space in it would be missed, and none exists.
        if re.search(r"[\s\[\]]", file_part):
            continue
        resolved = (path.parent / file_part).resolve()
        if not resolved.exists():
            bad.append(f"{path.relative_to(ROOT)}: link {t} points at nothing")
    return bad


def check_status(path: pathlib.Path, text: str) -> list[str]:
    """DOC-10: a reader must be able to tell whether a document still applies
    without reading it. 28 documents had accumulated by the audit -- plans,
    surveys, landing logs, specs and runbooks in one pile -- and the fix is a
    status line, in the form this repository already uses (`> 状态：…` right
    under the H1) rather than YAML front matter the site renderer would print
    as prose. A convention nothing checks decays, so it is checked."""
    if "docs/" not in str(path):
        return []
    if "状态" in "\n".join(text.split("\n")[:12]):
        return []
    return [f"{path.relative_to(ROOT)}: no `> 状态：…` line in the first 12 lines "
            f"(normative / current / historical / proposed -- see docs/README.md)"]


def check_blocks(path: pathlib.Path, text: str, work: pathlib.Path) -> list[str]:
    bad = []
    for i, (info, body) in enumerate(FENCE.findall(text)):
        mode = info.split()[1] if len(info.split()) > 1 else None
        if mode not in ("run", "compile"):
            continue
        src = work / f"{path.stem}_{i}.dawn"
        src.write_text(body, encoding="utf-8")
        cmd = [str(DAWN), "run" if mode == "run" else "check", str(src)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            head = (r.stderr or r.stdout).strip().splitlines()
            detail = head[0] if head else f"exit {r.returncode}"
            bad.append(f"{path.relative_to(ROOT)}: ```{info} block does not {mode}: {detail}")
    return bad


def main() -> None:
    problems: list[str] = []
    blocks = 0
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        for path in DOCS:
            text = path.read_text(encoding="utf-8")
            problems += check_links(path, text)
            problems += check_status(path, text)
            for info, _ in FENCE.findall(text):
                if len(info.split()) > 1 and info.split()[1] in ("run", "compile"):
                    blocks += 1
            problems += check_blocks(path, text, work)

    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f"FAIL: {len(problems)} documentation problem(s)", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {len(DOCS)} documents -- links, anchors and status lines resolve, "
          f"{blocks} checked block(s)")


if __name__ == "__main__":
    main()
