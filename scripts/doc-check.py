#!/usr/bin/env python3
"""Documentation CI (TEST-04).

The audit's argument is its own evidence: README's front-page example had
the wrong interpolation syntax, the tutorial's install command did not run,
and the EBNF disagreed with the parser in several places -- all found by a
human reading, none by a test. This script is the part of that gap a script
can close.

Six checks, each unambiguous on purpose (a doc lint with false positives
gets disabled, and then it protects nothing):

  links     every relative Markdown link resolves to a file in the repo
  anchors   every `#fragment` link -- same-file *and* cross-file -- matches a
            heading in the file it points at
  sections  every `§N` cross-reference whose target document is stated
            explicitly matches a numbered heading in that document
  version   every documented claim about the *current* toolchain version
            equals `selfhost/src/version.dawn`
  blocks    every fenced block marked ```dawn run / ```dawn compile is
            compiled (and run) by the toolchain
  status    every document under docs/ declares its status near the top

Blocks are opt-in rather than opt-out: most examples in the spec are
fragments -- a type declaration, three lines of a match -- and demanding
that they be whole modules would either mangle the prose or drown the check
in exemptions. A block whose correctness matters says so in its info string.

Three of these exist because a human found, on 2026-08-04, three documents
whose numbers nothing was reading: README claimed toolchain 0.11.0 while
version.dawn said 0.49.0; a cross-file anchor could be broken without the
anchor check noticing (it only ever looked inside one file); and
native-driver-plan.md cited section ranges that did not exist. Every one of
them was caught by eye or by a throwaway script, which is the same as not
being caught.

What each of the three deliberately does NOT cover -- stated here because a
check whose blind spot is undocumented gets mistaken for a check:

  * version: only the phrases in CURRENCY_PHRASES, plus lines carrying the
    `<!-- doc-check: version -->` marker. Most version literals in this
    repository are deliberately historical (release notes, `git tag v0.9.0`
    examples, a third-party `1.0.29`), so equality cannot be demanded of a
    bare `\\d+\\.\\d+\\.\\d+`.
  * anchors: heading slugs follow github-slugger, but a heading whose text
    differs from its slug only in runs of hyphens (this repository's titles
    are full of `——`, which GitHub turns into consecutive hyphens) is
    accepted leniently -- see anchor_index. Errs toward accepting.
    Read the count this prints: as of 2026-08-04 it is *zero*. Not one of
    the 519 Markdown links in this repository carries a `#fragment`, so
    both halves of the anchor check are guarding a door nobody uses yet.
    That is a fact about the corpus, not about the check.
  * sections: only references whose target document is written down --
    `[x](y.md) §3`, `y.md §3`, `本文 §3`, or a sibling in a `§3/§4` run.
    A bare `§3` is skipped, because in this corpus prose refers to other
    documents by nickname (`native 计划 §7`, `台账 §3.7`, `那份 §七`) far
    more often than one would guess: assuming "bare means this file" was
    measured against the whole corpus and misfired on 474 of the 1422 bare
    sites. Making that check sound is not a matter of a better regex, and
    a lint that is wrong one time in three gets switched off within a week.
    The 119 references that do name their target are checked; the rest are
    counted as skipped, not silently counted as passing.

Each check prints how many references it *resolved*, not just how many it
rejected: "0 rejected" reads the same whether the check is working or has
gone blind, and this repository has been bitten by that difference.

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

VERSION_SRC = ROOT / "selfhost" / "src" / "version.dawn"

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
FENCE = re.compile(r"^```(dawn(?:\s+\w+)?)\s*$(.*?)^```\s*$", re.M | re.S)

# --- version ---------------------------------------------------------------
VERSION_DECL = re.compile(r'\bVERSION\s*:\s*String\s*=\s*"([^"]+)"')
VERSION_MARKER = "<!-- doc-check: version -->"
SEMVER = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")
# Phrases that assert *the current toolchain version*, as opposed to naming a
# release in a landing log or a tag in an example command. Measured over the
# whole repository before being written down: they match one site, and that
# site was the wrong one. A bare \d+\.\d+\.\d+ cannot be used -- 261 of them
# live under docs/ and nearly all are deliberately historical.
CURRENCY_PHRASES = "当前工具链|当前版本|最新版本|当前发布|目前版本|工具链版本"
VERSION_CLAIM = re.compile(
    "(?:" + CURRENCY_PHRASES + r")[^\n]{0,14}?\bv?(\d+\.\d+\.\d+)\b")

# --- section cross-references ----------------------------------------------
# A heading's own number: "## 3. 声明", "### 9.5.1 ...", "## 一、问题".
HEADING_NUM = re.compile(r"^(\d+(?:\.\d+)*)\s*[.、,)]?(?:\s|$)")
HEADING_CJK = re.compile(r"^([一二三四五六七八九十]+)\s*[、.]")
# `§3`, `§9.5.1`, `§六`. Not `§3.A`: a label with a non-numeric tail names an
# item inside a section, not a heading, so it is skipped, not truncated.
SECTION_REF = re.compile(r"§\s*(\d+(?:\.\d+)*|[一二三四五六七八九十]+)(?!\d)")
# The three ways this corpus writes down which document a `§N` belongs to.
REF_VIA_LINK = re.compile(r"\]\(([^)\s]+\.md)\)\s*(?:的\s*)?$")
REF_VIA_NAME = re.compile(r"(?:^|[\s（(【「』」，。、|>*])([\w./-]+\.md)\s*(?:的\s*)?$")
REF_VIA_SELF = re.compile(r"(?:本文|本节|本篇)\s*(?:的\s*)?$")
# `§10.1/§10.2`, `§1.5、§2.6、§11`: the later reference inherits the earlier
# one's document, because nothing but a separator stands between them.
REF_SEPARATOR = re.compile(r"[/、,，]")

CJK_DIGITS = "一二三四五六七八九"
CJK_NUMERALS = {c: str(i + 1) for i, c in enumerate(CJK_DIGITS)}
CJK_NUMERALS["十"] = "10"
CJK_NUMERALS.update({"十" + c: str(11 + i) for i, c in enumerate(CJK_DIGITS)})


def slug(heading: str) -> str:
    """github-slugger, which is what GitHub's rendered anchors actually use:
    strip inline code, links and emphasis markers, lowercase, drop everything
    that is neither word character nor hyphen nor space, then turn *each*
    space into a hyphen. CJK survives -- it is word text, not punctuation.

    Note the "each": github-slugger does not collapse runs. `A —— B` loses the
    dashes and keeps both spaces, so GitHub's anchor is `a--b`, not `a-b`.
    anchor_index registers the collapsed spelling as well, because being
    strict in the wrong direction here would reject a correct link, and a doc
    lint that rejects correct input gets switched off."""
    h = re.sub(r"`([^`]*)`", r"\1", heading)
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    # `*` only: every underscore in this repository's 37 underscore-bearing
    # headings is inside an identifier (`unsafe_pure`, `char_is_*`), never
    # emphasis, and GitHub keeps underscores.
    h = h.replace("*", "")
    h = h.strip().lower()
    h = re.sub(r"[^\w\s-]", "", h)
    return h.replace(" ", "-")


def prose_only(text: str) -> str:
    """Markdown with code removed. Dawn's own syntax collides with the link
    form -- `map[T](xs: List[T])` reads as a link to a file called
    "xs: List[T]" -- so fenced blocks and inline spans are blanked (newlines
    kept, so nothing downstream needs to care about offsets)."""
    out = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"), text,
                 flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", out)


def headings_of(text: str) -> list[str]:
    """The document's headings, with fenced blocks dropped first: `## 文档注释,
    ...` inside a fenced Dawn example is a comment, not a heading, and letting
    it into the anchor set makes the check accept fragments GitHub 404s on.

    Only *fenced* blocks go -- prose_only() would also blank inline spans, and
    a heading's inline code is part of its slug (spec.md's `### 6.5 具名效果与
    `with handle`` anchors as `65-具名效果与-with-handle`), so blanking it would
    silently compute the wrong anchor for 267 of this repository's 1410
    headings. That was written the wrong way round first."""
    unfenced = re.sub(r"^```.*?^```", lambda m: "\n" * m.group(0).count("\n"),
                      text, flags=re.M | re.S)
    return HEADING.findall(unfenced)


def anchor_index(text: str) -> set[str]:
    """Every fragment GitHub would accept for this document.

    Duplicate heading text gets `-1`, `-2` (github-slugger's counter), and
    four files here have duplicate headings. The hyphen-collapsed spelling of
    each slug goes in too: see slug() for why leniency is the safe direction."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    for h in headings_of(text):
        s = slug(h)
        n = seen.get(s, 0)
        seen[s] = n + 1
        for base in (s, re.sub(r"-+", "-", s).strip("-")):
            out.add(base if n == 0 else f"{base}-{n}")
    return out


def section_index(text: str) -> set[str]:
    """The numbers a `§N` in this document could name. Headings here are
    numbered two ways at once -- `## 一、问题` beside `### 1.1 ...` -- so a CJK
    numeral is registered under both spellings."""
    out: set[str] = set()
    for h in headings_of(text):
        h = re.sub(r"[`*_]", "", h).strip()
        m = HEADING_NUM.match(h)
        if m:
            out.add(m.group(1))
        m = HEADING_CJK.match(h)
        if m:
            out.add(m.group(1))
            if m.group(1) in CJK_NUMERALS:
                out.add(CJK_NUMERALS[m.group(1)])
    return out


def check_links(path: pathlib.Path, text: str, anchors: dict) -> list[str]:
    bad = []
    text = prose_only(text)
    for target in LINK.findall(text):
        t = target.strip()
        if t.startswith(("http://", "https://", "mailto:")):
            continue
        if t.startswith("#"):
            if t[1:] not in anchors[path]:
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
            continue
        # The half the anchor check could not see until now: `other.md#frag`
        # was parsed, the file half was verified, and the fragment was thrown
        # away. Breaking one stayed green while breaking a same-file anchor
        # went red, which is exactly the shape of a check that is running but
        # not looking.
        frag = t.split("#", 1)[1] if "#" in t else ""
        if frag and resolved in anchors:
            if frag not in anchors[resolved]:
                bad.append(f"{path.relative_to(ROOT)}: anchor #{frag} in link {t} "
                           f"matches no heading in {resolved.relative_to(ROOT)}")
    return bad


def count_anchor_refs(path: pathlib.Path, text: str, anchors: dict) -> int:
    """How many fragments check_links actually adjudicated. Printed, because
    "0 rejected" looks identical whether the check is sound or asleep."""
    n = 0
    for target in LINK.findall(prose_only(text)):
        t = target.strip()
        if t.startswith(("http://", "https://", "mailto:")) or "#" not in t:
            continue
        head, frag = t.split("#", 1)
        if not frag:
            continue
        if not head:
            n += 1
        elif not re.search(r"[\s\[\]]", head) and (path.parent / head).resolve() in anchors:
            n += 1
    return n


def check_sections(path: pathlib.Path, text: str, sections: dict) -> tuple[list[str], int]:
    """`§N` cross-references, for the subset whose target document is stated.

    See the module docstring for what is deliberately not checked and why the
    obvious wider rule ("a bare §N means this file") is unsound here."""
    bad: list[str] = []
    checked = 0
    text = prose_only(text)
    carry: tuple[pathlib.Path, int] | None = None
    for m in SECTION_REF.finditer(text):
        label = m.group(1)
        if re.match(r"\.\D", text[m.end():m.end() + 2]):
            carry = None          # `§2.A` names an item, not a heading
            continue
        line = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        target = None
        link = REF_VIA_LINK.search(line)
        name = None if link else REF_VIA_NAME.search(line)
        if link or name:
            hit = (path.parent / (link or name).group(1)).resolve()
            target = hit if hit in sections else None
        elif REF_VIA_SELF.search(line):
            target = path
        elif carry and REF_SEPARATOR.fullmatch(text[carry[1]:m.start()].strip() or "x"):
            target = carry[0]
        carry = (target, m.end()) if target else None
        if target is None or not sections[target]:
            continue
        checked += 1
        if label not in sections[target]:
            bad.append(f"{path.relative_to(ROOT)}: §{label} names no section of "
                       f"{target.relative_to(ROOT)}")
    return bad, checked


def toolchain_version() -> str:
    """The one number the documents are checked against. A missing or
    unparseable source is fatal rather than skipped: a guard that quietly
    stops guarding is the failure this check exists to prevent."""
    m = VERSION_DECL.search(VERSION_SRC.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"doc-check: no VERSION declaration in {VERSION_SRC.relative_to(ROOT)}")
    return m.group(1)


def check_version(path: pathlib.Path, text: str, version: str) -> tuple[list[str], int]:
    """README said "当前工具链 0.11.0" while version.dawn said 0.49.0, and had
    said so across enough releases that nobody could date the drift. Editing
    the token would only reset the clock, so the number is read from source."""
    bad: list[str] = []
    claims = 0
    for n, line in enumerate(text.split("\n"), 1):
        found = [m.group(1) for m in VERSION_CLAIM.finditer(line)]
        if VERSION_MARKER in line:
            found += [m.group(1) for m in SEMVER.finditer(line.replace(VERSION_MARKER, ""))]
        for got in found:
            claims += 1
            if got != version:
                bad.append(f"{path.relative_to(ROOT)}:{n}: claims current version "
                           f"{got}, but selfhost/src/version.dawn says {version}")
    return bad, claims


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
    blocks = anchors_seen = sections_seen = claims_seen = 0
    version = toolchain_version()

    # Both cross-document checks need every document's headings before any
    # document can be judged, so the indexes are built in one pass first.
    texts = {p: p.read_text(encoding="utf-8") for p in DOCS}
    anchors = {p: anchor_index(t) for p, t in texts.items()}
    sections = {p: section_index(t) for p, t in texts.items()}

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        for path in DOCS:
            text = texts[path]
            problems += check_links(path, text, anchors)
            anchors_seen += count_anchor_refs(path, text, anchors)
            bad, n = check_sections(path, text, sections)
            problems += bad
            sections_seen += n
            bad, n = check_version(path, text, version)
            problems += bad
            claims_seen += n
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
    print(f"OK: {len(DOCS)} documents, {blocks} checked block(s); "
          f"{anchors_seen} anchor(s), {sections_seen} § reference(s) and "
          f"{claims_seen} version claim(s) resolved, 0 unknown")


if __name__ == "__main__":
    main()
