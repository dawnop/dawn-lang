#!/usr/bin/env python3
"""Documentation CI (TEST-04).

The audit's argument is its own evidence: README's front-page example had
the wrong interpolation syntax, the tutorial's install command did not run,
and the EBNF disagreed with the parser in several places -- all found by a
human reading, none by a test. This script is the part of that gap a script
can close.

Nine checks, each unambiguous on purpose (a doc lint with false positives
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
  pages     every program on the website's front page runs and prints exactly
            the output printed beside it (site/pages/*.dawn vs *.out)
  status    every document under docs/ opens with a `> 状态：…` line
  count     every claim about how many documents docs/ holds equals how many
            it holds, and every one of them is linked from docs/README.md
  transl    every translated document registers the digest of the original it
            was translated from, and that digest is still the original's

Blocks are opt-in rather than opt-out: most examples in the spec are
fragments -- a type declaration, three lines of a match -- and demanding
that they be whole modules would either mangle the prose or drown the check
in exemptions. A block whose correctness matters says so in its info string.

Pages are opt-out-less for the opposite reason: site/pages/ holds four whole
programs, they are the four most-read pieces of Dawn in the project, and
nothing compiled them until 2026-08-05. Being whole programs, they can be
held to their *output* as well -- which is the half that matters, because a
snippet that compiles and prints something other than what the page claims
is worse than one that does not compile.

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
  * status: the *presence* of the line, never its truth. Nothing here can
    tell `> 状态：current` from `> 状态：动工计划`, on a plan that shipped a
    week ago, and pretending otherwise would be worse than the gap.
  * transl: whether the marker was *earned*. Re-registering the digest
    without touching a word of the translation makes this green, and nothing
    here can tell that from a real re-translation -- the marker is a human
    assertion, and every scheme of this shape has that escape. What it does
    remove is the failure that actually happens: the original moving and
    nobody noticing. Note also the direction. English is the original and
    Chinese the translation, so rot lands on the Chinese side, whose reader is
    the author. The other arrangement puts the rot on the side everybody
    reads and nobody proofreads.
  * count: the number is read only off lines carrying the
    `<!-- doc-check: doc-count -->` marker, for the same reason version does
    not match a bare semver -- most numbers in this corpus are counts of
    something else. The coverage half needs no marker: docs/README.md is the
    index, and a document it does not link is a document with no status
    anybody can find.

Each check prints how many references it *resolved*, not just how many it
rejected: "0 rejected" reads the same whether the check is working or has
gone blind, and this repository has been bitten by that difference.

  ./scripts/doc-check.py
"""

import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAWN = ROOT / "bin" / "dawn"

# every tracked Markdown file, including the top-level ones. Globbed rather
# than listed: README.zh-CN.md joined the top level in 2026-08-05 and a
# hand-kept list is the thing that would not have noticed.
DOCS = sorted(
    [p for p in (ROOT / "docs").rglob("*.md")] + list(ROOT.glob("*.md"))
)

# --- translations ----------------------------------------------------------
# Which documents are translations, and of what. English is the original: the
# repository's outward-facing layer is read mostly by people who do not read
# Chinese, and a derived document rots. Putting the derived one on the side
# nobody proofreads is the arrangement where the rot is invisible; this way it
# lands on the Chinese text, whose reader is the author.
#
# The pairing lives here and not only in the marker, because a marker is the
# only thing the marker check reads: delete it and a check that exists only in
# the file it checks stops existing. With the registry, deleting the marker is
# a failure.
#
# Scope, decided rather than drifted into: the outward-facing layer only --
# the README and the website's front page. docs/ is 61 documents of design
# notes, plans and a specification whose reader is the author; translating
# them would produce 61 more documents to keep level, and a half-translated
# corpus is worse than an honestly monolingual one. Both faces of the site say
# so in their own closing paragraph.
TRANSLATIONS = {
    "README.zh-CN.md": "README.md",
    "site/pages/home.zh.md": "site/pages/home.md",
}

VERSION_SRC = ROOT / "selfhost" / "src" / "version.dawn"

# The website's front page: one whole program per card, and the stdout the page
# prints beside it. site/src/gen/pages.dawn reads both, so the pairing is not a
# convention this script invented -- a card without a recorded output fails the
# site build too.
SITE_PAGES = ROOT / "site" / "pages"

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
FENCE = re.compile(r"^```(dawn(?:\s+\w+)?)\s*$(.*?)^```\s*$", re.M | re.S)

# --- version ---------------------------------------------------------------
VERSION_DECL = re.compile(r'\bVERSION\s*:\s*String\s*=\s*"([^"]+)"')
VERSION_MARKER = "<!-- doc-check: version -->"
SEMVER = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")

# --- translation markers ---------------------------------------------------
# `<!-- doc-check: translation-of README.md @ 0123456789abcdef -->`
TRANSLATION_MARKER = re.compile(
    r"^[ \t]*<!--[ \t]*doc-check:[ \t]*translation-of[ \t]+(\S+)[ \t]*@"
    r"[ \t]*([0-9a-f]+)[ \t]*-->[ \t]*$")
FENCE_LINE = re.compile(r"^[ \t]*```")

# --- status line, and the count of documents carrying one -------------------
# Anchored on the blockquote a status line actually is. The substring `状态`
# alone matched a `## 状态总览` heading and a sentence with `状态` in the middle
# of it, and let three status-less documents through; see check_status.
STATUS_LINE = re.compile(r"^\s*>\s*\**\s*状态")
DOC_COUNT_MARKER = "<!-- doc-check: doc-count -->"
INTEGER = re.compile(r"\b(\d+)\b")
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


def check_status(path: pathlib.Path, text: str) -> tuple[list[str], int]:
    """DOC-10: a reader must be able to tell whether a document still applies
    without reading it. 28 documents had accumulated by the audit -- plans,
    surveys, landing logs, specs and runbooks in one pile -- and the fix is a
    status line, in the form this repository already uses (`> 状态：…` right
    under the H1) rather than YAML front matter the site renderer would print
    as prose. A convention nothing checks decays, so it is checked.

    The match is anchored on the blockquote, not on the substring: for the
    first three months this check only asked whether `状态` occurred anywhere
    in the first twelve lines, and three documents passed it without having a
    status line at all -- one on a heading called `## 状态总览`, one on the
    index's own `**状态取值**` legend, one on a sentence that happened to
    contain `被当日状态吞并`. All three were found by hand on 2026-08-04,
    which is the failure mode this file's own docstring warns about: a check
    that is running but not looking."""
    if "docs/" not in str(path):
        return [], 0
    if any(STATUS_LINE.match(line) for line in text.split("\n")[:12]):
        return [], 1
    return [f"{path.relative_to(ROOT)}: no `> 状态：…` line in the first 12 lines "
            f"(normative / current / historical / proposed -- see docs/README.md)"], 0


def check_doc_count(path: pathlib.Path, text: str, total: int) -> tuple[list[str], int]:
    """docs/README.md opens by saying how many documents docs/ holds. It said
    43 while the directory held 58, and there is no way for a reader to notice
    -- which is the same shape as the version claim this file already reads
    from source, so it is settled the same way: the number stays in the prose,
    the marker hands it to a machine, and adding a document turns the gate red
    until the sentence is corrected."""
    bad: list[str] = []
    claims = 0
    for n, line in enumerate(text.split("\n"), 1):
        if DOC_COUNT_MARKER not in line:
            continue
        for m in INTEGER.finditer(line.replace(DOC_COUNT_MARKER, "")):
            claims += 1
            if int(m.group(1)) != total:
                bad.append(f"{path.relative_to(ROOT)}:{n}: claims docs/ holds "
                           f"{m.group(1)} document(s), but it holds {total}")
    return bad, claims


def check_index_coverage(texts: dict) -> tuple[list[str], int]:
    """Every document under docs/ is linked from docs/README.md.

    The index is where this repository keeps each document's status, so a
    document missing from it has, in effect, no status: twelve were, when this
    was written, including three the index's own prose referred to. The count
    check alone would not have found them -- 58 documents and 46 index entries
    both read as "some number" to a human, and the number was 43."""
    index = ROOT / "docs" / "README.md"
    linked = set()
    for target in LINK.findall(prose_only(texts[index])):
        t = target.strip().split("#", 1)[0]
        if not t or t.startswith(("http://", "https://", "mailto:")):
            continue
        if re.search(r"[\s\[\]]", t):
            continue
        linked.add((index.parent / t).resolve())
    bad = []
    seen = 0
    for path in texts:
        if path == index or not path.is_relative_to(ROOT / "docs"):
            continue
        seen += 1
        if path not in linked:
            bad.append(f"{path.relative_to(ROOT)}: not linked from docs/README.md "
                       f"(the index is where a document's status is registered)")
    return bad, seen


def translation_digest(text: str) -> str:
    """What a translation has to be kept level with.

    Not the file's bytes. A digest over raw bytes goes red when a paragraph is
    re-wrapped, and a check that is wrong about a third of the time is switched
    off inside a week -- this file argues that about three other checks and it
    applies here too. So the boundary is drawn at what a translator would have
    to mirror:

      * outside fenced code, a paragraph is unwrapped to one line and interior
        whitespace runs collapse. Re-flowing English prose is invisible;
        Chinese wraps at different columns anyway, so a line break is not
        something a translation mirrors.
      * inside fenced code, lines are kept verbatim. Whitespace is the program
        there, and a code sample IS mirrored line for line.
      * doc-check's own markers are stripped, so that re-registering a digest
        does not change the digest.
      * `1.2.3` and `v1.2.3` are masked. This is the only exclusion that is
        about frequency rather than about meaning: README states the current
        toolchain version, so every release would otherwise force a
        re-registration -- for a fact check_version already holds both
        documents to independently, off version.dawn. The residual hole is
        named rather than papered over: an edit that changes *only* a
        historical version number in the original (`git tag v0.9.0` in an
        example) will not ask for the translation to follow.

    What is deliberately NOT excluded: wording, punctuation, links, headings,
    list items, code. All of those are content a translation is answerable
    for, and all of them turn the digest over."""
    out: list[str] = []
    para: list[str] = []
    in_fence = False

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            para.clear()

    for line in text.split("\n"):
        if FENCE_LINE.match(line):
            flush()
            in_fence = not in_fence
            out.append(line.rstrip())
            continue
        if in_fence:
            out.append(line.rstrip())
            continue
        if TRANSLATION_MARKER.match(line):
            continue
        stripped = " ".join(line.replace(VERSION_MARKER, "").split())
        if not stripped:
            flush()
            continue
        para.append(stripped)
    flush()
    body = SEMVER.sub("<version>", "\n".join(out))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def check_translations() -> tuple[list[str], int]:
    """Every translation carries the digest of the original it was made from.

    The failure this exists for is not mistranslation, it is drift: a document
    that is a copy of another one goes stale for free, because nothing builds
    from it and nothing runs it. On 2026-08-04 an audit of this repository
    found 21 of 58 documents carrying a status line that had stopped being
    true, a spec claiming to describe 0.11.0 while the toolchain was at 0.49.0,
    and a README advertising a release artifact that no release carried -- and
    those are documents somebody at least reads. A translation is worse: it can
    be wrong in a way that is invisible to every reader of the original.

    So the original's digest is written into the translation, and moving the
    original turns this red until a human re-registers it.

    Files are read here rather than taken from the DOCS index: a translated
    document is not necessarily a document under docs/ -- the front page's copy
    lives in site/pages/ -- and a check that could only see one directory would
    have to be extended every time the scope moved."""
    bad: list[str] = []
    seen = 0
    for rel_tr, rel_src in sorted(TRANSLATIONS.items()):
        tr, src = ROOT / rel_tr, ROOT / rel_src
        if not tr.exists():
            bad.append(f"{rel_tr}: registered in doc-check.py as a translation "
                       f"of {rel_src}, but does not exist")
            continue
        if not src.exists():
            bad.append(f"{rel_tr}: translates {rel_src}, which does not exist")
            continue
        tr_text = tr.read_text(encoding="utf-8")
        src_text = src.read_text(encoding="utf-8")
        marks = [m for m in map(TRANSLATION_MARKER.match, tr_text.split("\n")) if m]
        if not marks:
            bad.append(f"{rel_tr}: no `<!-- doc-check: translation-of {rel_src} @ "
                       f"{translation_digest(src_text)} -->` marker "
                       f"(it is what says which revision of {rel_src} this was "
                       f"translated from)")
            continue
        if len(marks) > 1:
            bad.append(f"{rel_tr}: {len(marks)} translation-of markers; "
                       f"a document translates one original")
            continue
        seen += 1
        named, got = marks[0].group(1), marks[0].group(2)
        if named != rel_src:
            bad.append(f"{rel_tr}: marker says it translates {named}, but "
                       f"doc-check.py registers it against {rel_src}")
            continue
        want = translation_digest(src_text)
        if got != want:
            bad.append(
                f"{rel_tr}: registered against {rel_src} @ {got}, but {rel_src} "
                f"is now @ {want}. {rel_src} is the original: update the "
                f"translation to match it, then re-register the digest.")
    return bad, seen


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


def check_site_pages() -> tuple[list[str], int]:
    """The front page's programs, run and held to the output printed beside
    them.

    These four snippets -- the hero and the three feature cards -- are the
    first Dawn anybody sees, and until 2026-08-05 nothing in this repository
    compiled them. `dawn run` alone would only be half the check: the cards
    now print their result, so a snippet that still compiles while quietly
    answering something else is exactly the failure a reader cannot detect and
    a compiler gate would not either. stdout is compared byte for byte.

    stderr is deliberately not compared. None of these programs writes to it,
    and a non-zero exit is reported with the first line of whatever they did
    write, which is the diagnostic a reader needs."""
    bad: list[str] = []
    seen = 0
    for src in sorted(SITE_PAGES.glob("*.dawn")):
        seen += 1
        rel = src.relative_to(ROOT)
        expected_file = src.with_suffix(".out")
        if not expected_file.exists():
            bad.append(f"{rel}: no {expected_file.name} beside it (a front-page "
                       f"program records the output the page shows)")
            continue
        r = subprocess.run([str(DAWN), "run", str(src)], capture_output=True,
                           text=True, cwd=ROOT)
        if r.returncode != 0:
            head = (r.stderr or r.stdout).strip().splitlines()
            detail = head[0] if head else f"exit {r.returncode}"
            bad.append(f"{rel}: does not run: {detail}")
            continue
        expected = expected_file.read_text(encoding="utf-8")
        if r.stdout != expected:
            bad.append(f"{rel}: printed {r.stdout!r}, but "
                       f"{expected_file.relative_to(ROOT)} (which the front page "
                       f"shows) says {expected!r}")
    return bad, seen


def main() -> None:
    problems: list[str] = []
    blocks = anchors_seen = sections_seen = claims_seen = 0
    status_seen = counts_seen = indexed_seen = pages_seen = transl_seen = 0
    version = toolchain_version()
    # What docs/README.md's opening sentence counts: the Markdown documents
    # under docs/, which is DOCS minus the top-level files it does not index
    # (README, README.zh-CN, CLAUDE, CONTRIBUTING).
    doc_total = sum(1 for p in DOCS if p.is_relative_to(ROOT / "docs"))

    # Both cross-document checks need every document's headings before any
    # document can be judged, so the indexes are built in one pass first.
    texts = {p: p.read_text(encoding="utf-8") for p in DOCS}
    anchors = {p: anchor_index(t) for p, t in texts.items()}
    sections = {p: section_index(t) for p, t in texts.items()}
    bad, indexed_seen = check_index_coverage(texts)
    problems += bad
    bad, pages_seen = check_site_pages()
    problems += bad
    bad, transl_seen = check_translations()
    problems += bad

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
            bad, n = check_status(path, text)
            problems += bad
            status_seen += n
            bad, n = check_doc_count(path, text, doc_total)
            problems += bad
            counts_seen += n
            for info, _ in FENCE.findall(text):
                if len(info.split()) > 1 and info.split()[1] in ("run", "compile"):
                    blocks += 1
            problems += check_blocks(path, text, work)

    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f"FAIL: {len(problems)} documentation problem(s)", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {len(DOCS)} documents, {blocks} checked block(s), "
          f"{pages_seen} front-page program(s); "
          f"{anchors_seen} anchor(s), {sections_seen} § reference(s), "
          f"{claims_seen} version claim(s), {status_seen} status line(s), "
          f"{indexed_seen} index entr(ies), {counts_seen} document count(s) "
          f"and {transl_seen} translation(s) resolved, 0 unknown")


if __name__ == "__main__":
    main()
