#!/usr/bin/env python3
"""Documentation CI (TEST-04).

The audit's argument is its own evidence: README's front-page example had
the wrong interpolation syntax, the tutorial's install command did not run,
and the EBNF disagreed with the parser in several places -- all found by a
human reading, none by a test. This script is the part of that gap a script
can close.

Ten checks, each unambiguous on purpose (a doc lint with false positives
gets disabled, and then it protects nothing):

  links     every relative Markdown link resolves to a file in the repo
  anchors   every `#fragment` link -- same-file *and* cross-file -- matches a
            heading in the file it points at
  sections  every `§N` cross-reference whose target document is stated
            explicitly matches a numbered heading in that document
  version   every documented claim about the *current* toolchain version
            equals `selfhost/src/version.dawn`
  blocks    every fenced block marked ```dawn run / ```dawn compile is
            compiled (and run) by the toolchain, and wherever an ```output
            fence follows a ```dawn run block, stdout equals it byte for byte
  fences    every ```dawn fence in the tutorial declares which of the three
            kinds it is, and every exemption states its reason
  pages     every whole program the website ships runs and prints exactly the
            output recorded beside it (site/pages/ and site/play-ui/samples/,
            *.dawn vs *.out)
  status    every document under docs/ opens with a `> 状态：…` (or
            `> Status: …`) line
  count     every claim about how many documents docs/ holds equals how many
            it holds, and every one of them is linked from docs/README.md
  transl    every translated document registers the digest of the original it
            was translated from, that digest is still the original's, and its
            fenced blocks line up one-for-one with the original's

Blocks are opt-in rather than opt-out: most examples in the spec are
fragments -- a type declaration, three lines of a match -- and demanding
that they be whole modules would either mangle the prose or drown the check
in exemptions. A block whose correctness matters says so in its info string.

The tutorial is where that rule is inverted, and the three kinds are written
down here so that a second reader classifies a new block the way the first
one did. Without a written criterion "it is only illustrative" is an
exemption that grows to fit whatever stopped compiling, and a gate whose
exemption is unbounded is a gate with no lower bound on its coverage.

  ```dawn run        A whole program: it has a `pub fn main`, the toolchain
                     runs it, and the ```output fence immediately after it
                     records what it printed. The criterion is mechanical and
                     the obligation runs one way -- a block that CAN be a
                     whole program MUST be one, and MUST record its output.
                     29 of the tutorial's 31 dawn fences are this.
  ```dawn skip-check A block that cannot be a whole program for a reason in
                     the language rather than in the author's effort. Both of
                     today's two are one file of a two-file project, shown
                     because §13 explains `use` and a module example needs two
                     files to be an example at all. The reason is written in a
                     `<!-- doc-check: skip-check ... -->` marker above the
                     fence: the exemption costs a sentence, and the whole set
                     of exemptions can be audited by reading the markers.
  ```dawn            Not available in the tutorial. Elsewhere a bare fence
                     means "fragment, not checked", which is the right default
                     for a spec; in the one document a newcomer copies line by
                     line it would be the exemption with no name and no
                     reason, so a bare fence is rejected there.

Nothing marks "this block must FAIL to compile". The tutorial has no such
block -- measured rather than assumed: no ```output fence in it holds a
diagnostic. Adding the mode anyway would create a rule with zero call sites,
which is the one thing this file must not grow, since a check that matches
nothing is green for exactly the same reason a working check is green.

Pages are opt-out-less for the opposite reason: site/pages/ holds four whole
programs, site/play-ui/samples/ five more, and between them they are the
most-read Dawn in the project -- the front page and the Playground sidebar,
which is where a newcomer's first keystroke lands. Nothing compiled either
set until 2026-08-05. Being whole programs, they can be held to their
*output* as well -- which is the half that matters, because a snippet that
compiles and prints something other than what the page claims is worse than
one that does not compile.

The Playground's five arrived here having been TypeScript template literals,
which is why they went eight releases in a state no gate could see: `fn`
lambdas retired in v0.43.0, ~323 call sites were migrated, and the one inside
a `.ts` string was not -- so the sidebar offered a program the compiler
rejected. Being `.dawn` files is the load-bearing part of the fix; this check
is what makes the files mean something.

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
    Read the count this prints: it is *zero*, and it has been zero since
    the day the check was written. Measured, not inferred -- running the
    2026-07-30 check over the 2026-07-30 corpus finds 357 links and no
    fragment among them, and the same at 291e248, which added the cross-file
    half. Neither half has ever adjudicated anything.
    What that is NOT is a fact about the repository, which is what this
    paragraph claimed until 2026-08-05: the repository holds 281 fragment
    references. They are all in the generated site -- 272 same-page TOC
    links, 9 written by hand in site/pages/stdlib.md and
    site/src/gen/stdlib.dawn -- and DOCS globs docs/ plus the top level, so
    not one of them was ever in scope here. site/src/gen/links.dawn checks
    them now, against the built HTML, which is the artifact that has to be
    right; it also had both halves of this blind spot until then.
    So this check keeps running over docs/, where prose links to whole
    files and never to fragments. It is kept rather than deleted because it
    is the trap for the first docs/ link that does carry one, and the
    printed zero is what stops that being mistaken for coverage.
  * sections: only references whose target document is written down --
    `[x](y.md) §3`, `y.md §3`, `本文 §3`, `§3 of y.md`, or a sibling in a
    `§3/§4` run.
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
    nobody noticing. The direction is per pair rather than global, and the
    reasoning is at TRANSLATIONS: for the outward-facing documents English is
    the original, so rot lands on the Chinese side, whose reader is the
    author; the spec and the design notes are edited in Chinese by every
    language change, so there the Chinese is the original. Either way the
    digest is what makes drift a failing check rather than a thing somebody
    notices later.
    The fence half is a *shape* check, not a byte comparison, and the reason
    is measured: README.zh-CN.md translates the comments inside its ```dawn
    and ```bash blocks, which is the convention here -- the code is the same
    program, the prose wrapped around and inside it is translated. So what is
    compared is the sequence of info strings, which is what says the two
    documents show the same examples in the same order. A fence added, dropped
    or retyped on one side only is caught; a comment translated inside one is
    not, and must not be.
  * count: the number is read only off lines carrying the
    `<!-- doc-check: doc-count -->` marker, for the same reason version does
    not match a bare semver -- most numbers in this corpus are counts of
    something else. The coverage half needs no marker: docs/README.md is the
    index, and a document it does not link is a document with no status
    anybody can find.

Three of the checks read prose rather than syntax -- status, version and
sections -- and until 2026-08-07 the prose they read could only be Chinese.
That is a trap rather than a limitation: a document written in English would
either fail a check it satisfies (status: no `> 状态：` line, because it says
`> Status:`) or pass one it violates (version and sections: the phrase that
selects a claim never matches, so nothing is adjudicated and the count that
would have shown it goes up by zero). Both halves are silent. So each of the
three patterns names its English spelling beside its Chinese one, and the
Chinese side is left byte-identical -- measured, not asserted: every printed
count is the same over this corpus before and after.

Each check prints how many references it *resolved*, not just how many it
rejected: "0 rejected" reads the same whether the check is working or has
gone blind, and this repository has been bitten by that difference.

  ./scripts/doc-check.py
"""

import hashlib
import os
import pathlib
import re
import signal
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
# Which documents are translations, and of what. For the outward-facing layer
# English is the original: it is read mostly by people who do not read Chinese,
# and a derived document rots. Putting the derived one on the side nobody
# proofreads is the arrangement where the rot is invisible; that way it lands
# on the Chinese text, whose reader is the author.
#
# The spec and the design notes run the other way, and the direction is a
# decision rather than an accident. They are *living* documents: every batch
# that changes the language edits them, in Chinese, because that is the
# language the rest of docs/ is written in. Making English their original
# would mean writing each language change in English first -- and a rule that
# expensive is a rule that gets skipped, which puts the rot back where it
# cannot be seen. So the Chinese half is the original, the English half is the
# translation, and the digest below is what turns drift into a red build
# either way round.
#
# The pairing lives here and not only in the marker, because a marker is the
# only thing the marker check reads: delete it and a check that exists only in
# the file it checks stops existing. With the registry, deleting the marker is
# a failure.
#
# Scope, decided rather than drifted into: everything the website renders --
# the README, the front page, the tutorial, the standard library's
# introduction, the specification and the design notes. Those are the
# documents a stranger reads. The rest of docs/ is design notes, plans and
# landing logs whose reader is the author; translating them would produce
# fifty-odd more documents to keep level, and a half-translated corpus is
# worse than an honestly monolingual one. Every face of the site says so in
# its own closing paragraph, so a reader is told rather than left to find out
# by clicking.
#
# Not on this list and not an oversight: the standard library's entries. They
# are the compiler's doc comments, and this repository's code is English --
# both /stdlib.html and /zh/stdlib.html show the same English signatures under
# their own introductions.
TRANSLATIONS = {
    "README.zh-CN.md": "README.md",
    "docs/tutorial.zh-CN.md": "docs/tutorial.md",
    "docs/spec.en.md": "docs/spec.md",
    "docs/design.en.md": "docs/design.md",
    "site/pages/home.zh.md": "site/pages/home.md",
    "site/pages/stdlib.zh.md": "site/pages/stdlib.md",
}

VERSION_SRC = ROOT / "selfhost" / "src" / "version.dawn"

# The whole programs the website ships, each with the stdout recorded beside it.
#
#   site/pages/          one program per front-page card. site/src/gen/pages.dawn
#                        reads both halves, so the pairing is not a convention
#                        this script invented -- a card without a recorded
#                        output fails the site build too.
#   site/play-ui/samples/ the Playground sidebar's starter files, inlined into
#                        the editor bundle by samples.ts via Vite's `?raw`.
#                        Here the pairing IS this script's: nothing in the npm
#                        build cares whether a sample compiles.
SITE_PROGRAMS = [
    ROOT / "site" / "pages",
    ROOT / "site" / "play-ui" / "samples",
]

# --- running an example ----------------------------------------------------
# Every example here is a whole program somebody wrote, and a program that
# loops or reads stdin does not fail -- it waits. Unbounded, the gate waits
# with it until the CI job's own limit kills the runner, and the transcript
# ends mid-check saying nothing about which document did it. A bound turns that
# into a named failing check.
#
# 120s is a hang detector, not a performance budget: the slowest example
# measured is a couple of seconds, and the toolchain is already built by the
# time this runs (gates.yml builds it first, and bin/dawn caches).
EXAMPLE_TIMEOUT = 120


def run_example(cmd: list[str], **kw):
    """Run one example under EXAMPLE_TIMEOUT. `None` means it timed out; the
    caller reports it, because only the caller knows which document it came
    from.

    Spawned as its own session and killed as one. `dawn run` does not run the
    program: it emits classes to a temp directory, spawns a child JVM over them
    and waits (selfhost/src/main.dawn, spawn_java). subprocess.run's timeout
    handling kills the direct child only -- so the looping example this bound
    exists to catch would keep looping after the gate had named it and exited,
    one orphan per hang, each burning a core until somebody noticed. The bound
    has to reap what it bounded; same rule as scripts/native-cli-diff.sh and
    scripts/lsp-liveness.py."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True, **kw)
    try:
        out, err = p.communicate(timeout=EXAMPLE_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except OSError:
            p.kill()
        p.communicate()
        return None
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
# Every fenced block, in order, not just the dawn ones: the tutorial's contract
# is a *pair* -- a ```dawn run block and the ```output fence right after it --
# and "right after" can only be decided by something that sees the blocks in
# between. Info strings are compared word by word, never as whole strings, so
# that a new verb does not silently fall through to "not checked".
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.M | re.S)

# The tutorial holds every ```output fence in the repository, and is the only
# document a reader is expected to retype rather than consult. That is what
# earns it the stricter rule; a set rather than a constant so that adding a
# second such document is a one-line change with a visible diff.
#
# Its translation is held to the same rule rather than riding on the original's
# compliance: the two files' fences are the same *shape* (check_translations
# says so) but not the same bytes -- the comments inside them are translated --
# so the translation's blocks are its own to get right, and check_blocks runs
# them as its own.
STRICT_FENCE_DOCS = {"docs/tutorial.md", "docs/tutorial.zh-CN.md"}
# `<!-- doc-check: skip-check 多文件项目的一半，单独编不了 -->`
SKIP_REASON = re.compile(
    r"^[ \t]*<!--[ \t]*doc-check:[ \t]*skip-check[ \t]+(\S[^>]*?)[ \t]*-->[ \t]*$")

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
#
# `Status` carries a \b and `状态` does not: the English word is a prefix of
# ordinary words (`Statuses`), the Chinese one is not a prefix of anything the
# blockquote anchor would let through.
STATUS_LINE = re.compile(r"^\s*>\s*\**\s*(?:状态|Status\b)")
DOC_COUNT_MARKER = "<!-- doc-check: doc-count -->"
INTEGER = re.compile(r"\b(\d+)\b")
# Phrases that assert *the current toolchain version*, as opposed to naming a
# release in a landing log or a tag in an example command. Measured over the
# whole repository before being written down: they match one site, and that
# site was the wrong one. A bare \d+\.\d+\.\d+ cannot be used -- 261 of them
# live under docs/ and nearly all are deliberately historical.
#
# The English list is the Chinese one word for word, not a wider net: a phrase
# that means something slightly different in only one language would make the
# check's coverage depend on which language a document happens to be in, which
# is the failure this whole widening exists to remove. Case-folded through a
# scoped (?i:) group rather than a flag on the whole pattern, so that the `v?`
# below keeps rejecting `V1.2.3` exactly as it did.
CURRENCY_PHRASES_ZH = "当前工具链|当前版本|最新版本|当前发布|目前版本|工具链版本"
CURRENCY_PHRASES_EN = (
    "current toolchain|current version|latest version|current release"
    "|toolchain version")
CURRENCY_PHRASES = CURRENCY_PHRASES_ZH + "|(?i:" + CURRENCY_PHRASES_EN + ")"
VERSION_CLAIM = re.compile(
    "(?:" + CURRENCY_PHRASES + r")[^\n]{0,14}?\bv?(\d+\.\d+\.\d+)\b")

# --- section cross-references ----------------------------------------------
# A heading's own number: "## 3. 声明", "### 9.5.1 ...", "## 一、问题".
HEADING_NUM = re.compile(r"^(\d+(?:\.\d+)*)\s*[.、,)]?(?:\s|$)")
HEADING_CJK = re.compile(r"^([一二三四五六七八九十]+)\s*[、.]")
# `§3`, `§9.5.1`, `§六`. Not `§3.A`: a label with a non-numeric tail names an
# item inside a section, not a heading, so it is skipped, not truncated.
SECTION_REF = re.compile(r"§\s*(\d+(?:\.\d+)*|[一二三四五六七八九十]+)(?!\d)")
# The ways this corpus writes down which document a `§N` belongs to. All but
# the last look at the text *before* the reference; GENITIVE is the connector
# that sits between the document and the `§` there (`spec.md 的 §3`,
# `spec.md's §3`).
#
# REF_VIA_OF looks *after* it instead, because that is where English puts the
# document: the of-genitive reverses the order (`§3 of spec.md`), so no amount
# of widening the leading patterns can reach it. Only the `.md` spelling is
# accepted -- `§11 of design doc` names a document by nickname, and this file
# already argues at length (see `sections` above) why guessing at nicknames is
# how a lint earns being switched off.
GENITIVE = r"(?:的|'s|’s)"
REF_VIA_LINK = re.compile(r"\]\(([^)\s]+\.md)\)\s*(?:" + GENITIVE + r"\s*)?$")
REF_VIA_NAME = re.compile(
    r"(?:^|[\s（(【「』」，。、,;:\"'|>*])([\w./-]+\.md)\s*(?:" + GENITIVE + r"\s*)?$")
REF_VIA_SELF = re.compile(
    r"(?:本文|本节|本篇|(?i:this document|this section|this doc))"
    r"\s*(?:" + GENITIVE + r"\s*)?$")
REF_VIA_OF = re.compile(r"^\s*of\s+(?:\[[^\]]*\]\()?([\w./-]+\.md)", re.I)
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
        nl = text.find("\n", m.end())
        rest = text[m.end():] if nl < 0 else text[m.end():nl]
        target = None
        link = REF_VIA_LINK.search(line)
        name = None if link else REF_VIA_NAME.search(line)
        of = None if (link or name) else REF_VIA_OF.match(rest)
        if link or name or of:
            hit = (path.parent / (link or name or of).group(1)).resolve()
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
        # The marker already claims every semver on its line, so a line that
        # carries one is read that way and not also through the phrase list --
        # otherwise README's "Current toolchain 0.57.0 <!-- doc-check: version
        # -->" would be one claim counted twice, and the printed count is the
        # only thing that says this check is awake.
        if VERSION_MARKER in line:
            found = [m.group(1)
                     for m in SEMVER.finditer(line.replace(VERSION_MARKER, ""))]
        else:
            found = [m.group(1) for m in VERSION_CLAIM.finditer(line)]
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
    that is running but not looking.

    `> Status: …` counts too. Everything under docs/ is Chinese today, so that
    branch adjudicates nothing yet -- it is here so that the first English
    document under docs/ fails for the reason it deserves rather than for its
    language."""
    if "docs/" not in str(path):
        return [], 0
    if any(STATUS_LINE.match(line) for line in text.split("\n")[:12]):
        return [], 1
    return [f"{path.relative_to(ROOT)}: no `> 状态：…` / `> Status: …` line in the "
            f"first 12 lines "
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
            continue
        bad += fence_shape_mismatch(rel_tr, tr_text, rel_src, src_text)
    return bad, seen


def fence_shape_mismatch(rel_tr: str, tr_text: str,
                         rel_src: str, src_text: str) -> list[str]:
    """The two documents show the same examples, in the same order.

    The digest above is computed over the *original* alone: it says which
    revision the translator worked from and nothing at all about what came out.
    So a fence dropped from the translation, or a ```dawn run block that lost
    its ```output fence on one side only, is invisible to it -- and in the
    tutorial, where two thirds of the page is fenced, that is most of the
    document.

    Info strings, not bodies. README.zh-CN.md translates the comments inside
    its blocks and that is the convention this repository already had before
    the tutorial joined it: the same program, with the prose in it translated.
    Demanding equal bytes would forbid that, and a lint that forbids the
    correct thing gets switched off. What the info strings pin down is the one
    property a reader can be hurt by -- the two pages showing a different
    number of examples, or a different kind of example in the same place."""
    src_fences = [info for info, _body, _line in fences(src_text)]
    tr_fences = [info for info, _body, _line in fences(tr_text)]
    if src_fences == tr_fences:
        return []
    if len(src_fences) != len(tr_fences):
        return [f"{rel_tr}: {len(tr_fences)} fenced block(s), but {rel_src} has "
                f"{len(src_fences)}. A translation shows the same examples as "
                f"the original, in the same order."]
    for i, (want, got) in enumerate(zip(src_fences, tr_fences)):
        if want != got:
            return [f"{rel_tr}: fenced block #{i + 1} is ```{got}, but the one in "
                    f"the same place in {rel_src} is ```{want}."]
    return []


def fences(text: str) -> list[tuple[str, str, int]]:
    """(info string, body, 1-based line the opening fence sits on)."""
    return [(m.group(1).strip(), m.group(2), text[:m.start()].count("\n") + 1)
            for m in FENCE.finditer(text)]


def check_blocks(path: pathlib.Path, text: str,
                 work: pathlib.Path) -> tuple[list[str], int, int]:
    """Compile (and run) the marked blocks, and hold the run ones to the output
    the document prints beside them.

    Exit code alone was the whole check until 2026-08-05, and it is the half
    that matters least: a tutorial whose example still compiles while printing
    something other than what the page below it claims teaches the reader a
    falsehood and passes the gate. All 29 of the tutorial's recorded outputs
    were correct when the comparison was added -- which is the expected result
    and not evidence the comparison is unnecessary, since nothing had been
    reading them and nothing would have said so if they had drifted."""
    bad: list[str] = []
    checked = recorded = 0
    blocks = fences(text)
    rel = path.relative_to(ROOT)
    # A block goes to disk under a directory of its document's own, named by
    # position rather than after the document: a source file's name IS its
    # module path, and a module path segment is `[a-z_][a-z0-9_]*`, which
    # `README.zh-CN_3` is not. Directory names above the entry never reach the
    # module path, so the document stays visible in the temp path.
    doc_dir = work / rel.as_posix().replace("/", "_")
    doc_dir.mkdir(parents=True, exist_ok=True)
    for i, (info, body, line) in enumerate(blocks):
        words = info.split()
        if not words or words[0] != "dawn":
            continue
        mode = words[1] if len(words) > 1 else None
        if mode not in ("run", "compile"):
            continue
        checked += 1
        src = doc_dir / f"block_{i}.dawn"
        src.write_text(body, encoding="utf-8")
        cmd = [str(DAWN), "run" if mode == "run" else "check", str(src)]
        r = run_example(cmd)
        if r is None:
            bad.append(f"{rel}:{line}: ```{info} block did not finish within "
                       f"{EXAMPLE_TIMEOUT}s (an example that loops or waits on "
                       f"stdin hangs this gate rather than failing it)")
            continue
        if r.returncode != 0:
            head = (r.stderr or r.stdout).strip().splitlines()
            detail = head[0] if head else f"exit {r.returncode}"
            bad.append(f"{rel}:{line}: ```{info} block does not {mode}: {detail}")
            continue
        # `dawn check` is a dump command, not a compiler front end: it prints
        # every diagnostic as a `D\t...` line and exits 0 regardless, because
        # the diff scripts that consume it compare dumps rather than statuses.
        # So exit code alone made `compile` a check that could not fail. Found
        # 2026-08-07 by marking the spec's associated-type example: the block
        # passed while a hand-run `dawn run` on the same source reported four
        # errors. There were no compile blocks at the time, so the mode had
        # never been exercised.
        if mode == "compile":
            diags = [ln for ln in r.stdout.splitlines() if ln.startswith("D\t")]
            if diags:
                parts = diags[0].split("\t")
                detail = parts[4] if len(parts) > 4 else diags[0]
                bad.append(f"{rel}:{line}: ```{info} block does not compile: "
                           f"{detail} ({len(diags)} diagnostic(s))")
                continue
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if mode != "run" or nxt is None or nxt[0] != "output":
            continue
        recorded += 1
        if r.stdout != nxt[1]:
            bad.append(f"{rel}:{line}: ```dawn run block printed {r.stdout!r}, "
                       f"but the ```output fence at line {nxt[2]} (which the "
                       f"reader is shown) says {nxt[1]!r}")
    return bad, checked, recorded


def check_fence_policy(path: pathlib.Path, text: str) -> tuple[list[str], int]:
    """In the tutorial, every dawn fence declares its kind and every exemption
    states its reason. See the module docstring for the three kinds."""
    rel = path.relative_to(ROOT).as_posix()
    if rel not in STRICT_FENCE_DOCS:
        return [], 0
    lines = text.split("\n")
    bad: list[str] = []
    seen = 0
    blocks = fences(text)
    for i, (info, _body, line) in enumerate(blocks):
        words = info.split()
        if words[:1] == ["output"]:
            prev = blocks[i - 1][0].split() if i else []
            if prev[:2] != ["dawn", "run"]:
                bad.append(f"{rel}:{line}: ```output fence records the output of "
                           f"nothing -- it must follow a ```dawn run block")
            continue
        if words[:1] != ["dawn"]:
            continue
        seen += 1
        mode = words[1] if len(words) > 1 else None
        if mode == "run":
            nxt = blocks[i + 1][0] if i + 1 < len(blocks) else None
            if nxt != "output":
                bad.append(f"{rel}:{line}: ```dawn run block has no ```output "
                           f"fence after it -- a runnable example in the tutorial "
                           f"records what it prints, so the two can be compared")
            continue
        if mode != "skip-check":
            bad.append(f"{rel}:{line}: ```{info} -- a dawn fence in the tutorial "
                       f"is either ```dawn run (a whole program, with its output "
                       f"recorded beside it) or ```dawn skip-check with a written "
                       f"reason. A bare fence is an exemption with no name.")
            continue
        j = line - 2
        while j >= 0 and lines[j].strip() == "":
            j -= 1
        if j < 0 or not SKIP_REASON.match(lines[j]):
            bad.append(f"{rel}:{line}: ```dawn skip-check with no reason above it. "
                       f"Write `<!-- doc-check: skip-check <why it cannot be a "
                       f"whole program> -->`, so the exemption costs a sentence "
                       f"and the set of them can be audited by reading markers.")
    return bad, seen


def check_site_pages() -> tuple[list[str], int]:
    """The website's whole programs, run and held to the output recorded beside
    them.

    Nine of them: the hero and three feature cards a reader meets on the front
    page, and the five starter files the Playground opens with. They are the
    first Dawn anybody sees, and until 2026-08-05 nothing in this repository
    compiled any of them -- the Playground's `traits` sample had been rejected
    by the compiler since v0.43.0 without one gate noticing.

    `dawn run` alone would only be half the check: these programs print their
    result, and one that still compiles while quietly answering something else
    is exactly the failure a reader cannot detect and a compiler gate would not
    either. stdout is compared byte for byte.

    stderr is deliberately not compared. None of these programs writes to it,
    and a non-zero exit is reported with the first line of whatever they did
    write, which is the diagnostic a reader needs."""
    bad: list[str] = []
    seen = 0
    for directory in SITE_PROGRAMS:
        for src in sorted(directory.glob("*.dawn")):
            seen += 1
            rel = src.relative_to(ROOT)
            expected_file = src.with_suffix(".out")
            if not expected_file.exists():
                bad.append(f"{rel}: no {expected_file.name} beside it (a program "
                           f"the website ships records the output it prints)")
                continue
            r = run_example([str(DAWN), "run", str(src)], cwd=ROOT)
            if r is None:
                bad.append(f"{rel}: did not finish within {EXAMPLE_TIMEOUT}s "
                           f"(a program the website ships must terminate)")
                continue
            if r.returncode != 0:
                head = (r.stderr or r.stdout).strip().splitlines()
                detail = head[0] if head else f"exit {r.returncode}"
                bad.append(f"{rel}: does not run: {detail}")
                continue
            expected = expected_file.read_text(encoding="utf-8")
            if r.stdout != expected:
                bad.append(f"{rel}: printed {r.stdout!r}, but "
                           f"{expected_file.relative_to(ROOT)} (which the site "
                           f"shows) says {expected!r}")
    return bad, seen


def main() -> None:
    problems: list[str] = []
    blocks = anchors_seen = sections_seen = claims_seen = recorded = 0
    status_seen = counts_seen = indexed_seen = pages_seen = transl_seen = 0
    fences_seen = 0
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
            bad, n = check_fence_policy(path, text)
            problems += bad
            fences_seen += n
            bad, n, m = check_blocks(path, text, work)
            problems += bad
            blocks += n
            recorded += m

    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print(f"FAIL: {len(problems)} documentation problem(s)", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {len(DOCS)} documents, {blocks} checked block(s) "
          f"({recorded} held to a recorded output), {fences_seen} tutorial "
          f"fence(s), {pages_seen} site program(s); "
          f"{anchors_seen} anchor(s), {sections_seen} § reference(s), "
          f"{claims_seen} version claim(s), {status_seen} status line(s), "
          f"{indexed_seen} index entr(ies), {counts_seen} document count(s) "
          f"and {transl_seen} translation(s) resolved, 0 unknown")


if __name__ == "__main__":
    main()
