#!/usr/bin/env python3
"""Documentation CI (TEST-04).

The audit's argument is its own evidence: README's front-page example had
the wrong interpolation syntax, the tutorial's install command did not run,
and the EBNF disagreed with the parser in several places -- all found by a
human reading, none by a test. This script is the part of that gap a script
can close.

Fourteen checks, each unambiguous on purpose (a doc lint with false positives
gets disabled, and then it protects nothing):

  links     every relative Markdown link resolves to a file in the repo
  anchors   every `#fragment` link -- same-file *and* cross-file -- matches a
            heading in the file it points at
  sections  every `§N` cross-reference whose target document is stated
            explicitly, plus every bare reference in the two normative specs,
            matches a numbered heading in that document; external RFC
            references are classified and skipped rather than treated as spec-local
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
  index     every lifecycle docs/README.md prints for a document is the one
            that document's own status line claims, which is where the index
            says the authority lives; and the sections listed in
            LIFECYCLE_TABULATED_SECTIONS print one per document they link,
            so a section cannot go back to prose and out of scope
  transl    every translated document registers the digest of the original it
            was translated from, that digest is still the original's, and its
            fenced blocks line up one-for-one with the original's
  audit     the current four-state audit registry exactly partitions all 99
            detail-heading IDs while the historical layer stays frozen at 97;
            counts, topic matrices and the frozen P1 mapping must agree
  evidence  every audit finding that carries an anchor agrees with the tree the
            anchor names: what an open finding describes is still there, and
            what a fixed one claims has arrived. An exact partition of wrong
            statuses is still wrong, and the partition check cannot see that
  contracts  settled semantic and repository-governance clauses remain present;
             this is a targeted pin, not full prose comparison

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
  * sections: outside the two normative specs, only references whose target document is written down --
    `[x](y.md) §3`, `y.md §3`, `本文 §3`, `§3 of y.md`, or a sibling in a
    `§3/§4` run.
    A bare `§3` is otherwise skipped, because in this corpus prose refers to other
    documents by nickname (`native 计划 §7`, `台账 §3.7`, `那份 §七`) far
    more often than one would guess: assuming "bare means this file" was
    measured against the whole corpus and misfired on 474 of the 1422 bare
    sites. Making that check sound is not a matter of a better regex, and
    a lint that is wrong one time in three gets switched off within a week.
    The normative specs are the deliberate exception: their bare references
    are same-file navigation, while cross-document references must name or link
    their `.md` target. The references that do name their target are checked;
    the rest outside the specs are counted as skipped, not silently counted as passing.
  * status: the *presence* of the document-lifecycle line, never its truth. Nothing here can
    tell `> 状态：current` from `> 状态：动工计划`, on a plan that shipped a
    week ago, and pretending otherwise would be worse than the gap. It does
    not even ask whether the line names a lifecycle at all: index does, for
    the documents the index prints a lifecycle for, and a document outside
    every lifecycle row is outside that too.
    Audit finding disposition is different: its finite ID universe and current
    registry are checked by the audit contract below. Free-form design-task
    progress remains authoritative only in each design document.
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
  * contracts: only the settled clauses in SPEC_CONTRACTS and the structural
    checks in repository_contract_problems. It
    deliberately does not compare whole paragraphs or infer translation
    quality; it catches known failure modes without turning prose into snapshots.
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

The corpus is what git tracks, not what the directory holds. Enumerating it by
walking the filesystem meant the gate read AGENTS.md and anything else a
developer had left in the root -- files this project keeps deliberately
untracked -- so "every document" named a different set on every machine, and a
broken link in somebody's scratch notes failed the build. See
markdown_documents.

Each check prints how many references it *resolved*, not just how many it
rejected: "0 rejected" reads the same whether the check is working or has
gone blind, and this repository has been bitten by that difference.

  ./scripts/doc-check.py
"""

import fnmatch
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


def tracked_markdown(root: pathlib.Path) -> set[pathlib.Path]:
    """Every Markdown file git tracks under `root`, as absolute paths.

    Raises rather than returning a guess. The caller turns that into an exit,
    and the reason it must not fall back to a filesystem walk is the reason
    this function exists at all: agent-collaboration notes (AGENTS.md and its
    kind) are deliberately untracked and globally gitignored here, so a walk
    reads documents that are not part of the repository. The gate's verdict
    then depends on which scratch files the developer happens to be carrying,
    and a stray broken link in one of them fails the build for everybody. A
    silent fallback would restore that on exactly the machines least able to
    notice it had happened.

    The index, not the commit: `git add`-ing a new document puts it in scope
    immediately, which is the point at which its author can be asked to fix it.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            capture_output=True, text=True)
    except OSError as why:
        raise RuntimeError(f"cannot run git to enumerate documents: {why}") from why
    if proc.returncode != 0:
        raise RuntimeError(
            f"`git ls-files` failed in {root} (exit {proc.returncode}): "
            f"{proc.stderr.strip() or 'no output'}")
    names = [name for name in proc.stdout.split("\0") if name]
    if not names:
        # A git that answers and reports nothing would leave every check below
        # with an empty corpus, which is green for the same reason a passing
        # run is green. Whatever produced it, it is not this repository.
        raise RuntimeError(f"`git ls-files` reports no Markdown at all under {root}")
    return {root / name for name in names}


def markdown_documents() -> list[pathlib.Path]:
    """The documents this file checks: docs/ and the top level, tracked only.

    The two globs state the subject -- docs/ at any depth plus the top level,
    which is what scripts/gate-map records this gate as watching. Membership is
    then settled by git, so "every document" means the same set here, in CI and
    in a fresh checkout. Globbed rather than listed because README.zh-CN.md
    joined the top level in 2026-08-05 and a hand-kept list is the thing that
    would not have noticed.
    """
    try:
        tracked = tracked_markdown(ROOT)
    except RuntimeError as why:
        sys.exit(f"doc-check: {why}")
    walked = [p for p in (ROOT / "docs").rglob("*.md")] + list(ROOT.glob("*.md"))
    return sorted(p for p in walked if p in tracked)


DOCS = markdown_documents()

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
# Scope, decided rather than drifted into: the documents a stranger reads. The
# rest of docs/ is design notes, plans and landing logs whose reader is the
# author; translating them would produce fifty-odd more documents to keep level,
# and a half-translated corpus is worse than an honestly monolingual one. Every
# face of the site says so in its own closing paragraph, so a reader is told
# rather than left to find out by clicking.
#
# That scope used to be written as "everything the website renders", which is a
# good proxy for it and was wrong in exactly one place. CONTRIBUTING.md is
# rendered by GitHub to every would-be contributor and by the website to nobody,
# so under the proxy it stayed Chinese-only while being, by the criterion the
# proxy stood for, squarely in the outward layer. It is registered below now,
# and the scope is stated as the criterion so the next document in that position
# is judged by it rather than by where it happens to be published.
#
# Not on this list and not an oversight: the standard library's entries. They
# are the compiler's doc comments, and this repository's code is English --
# both /stdlib.html and /zh/stdlib.html show the same English signatures under
# their own introductions.
TRANSLATIONS = {
    "CONTRIBUTING.zh-CN.md": "CONTRIBUTING.md",
    "README.zh-CN.md": "README.md",
    "docs/tutorial.zh-CN.md": "docs/tutorial.md",
    "docs/spec.en.md": "docs/spec.md",
    "docs/design.en.md": "docs/design.md",
    "site/pages/home.zh.md": "site/pages/home.md",
    "site/pages/stdlib.zh.md": "site/pages/stdlib.md",
}

SPEC_CONTRACTS = (
    (
        "failure payload contract",
        (
            ("docs/spec.md", "**载荷契约**（对每个后端）："),
            ("docs/spec.en.md", "**The payload contract** (on every backend):"),
        ),
    ),
    (
        "unbounded failure message",
        (
            ("docs/spec.md", "`message` **没有长度上限**"),
            ("docs/spec.en.md", "`message` has **no length limit**"),
        ),
    ),
    (
        "well-formed failure message",
        (
            ("docs/spec.md", "`message` 是良构 UTF-8"),
            ("docs/spec.en.md", "`message` is well-formed UTF-8"),
        ),
    ),
    (
        "failure payload ownership",
        (
            ("docs/spec.md", "一个失败的载荷属于**将要接住它的那个屏障**"),
            ("docs/spec.en.md", "A failure's payload belongs to **the barrier that "
             "is going to take it**"),
        ),
    ),
    (
        "observable panic-fault split",
        (
            ("docs/spec.md", "panic/fault 这个二分是**可观察的**——由哪个屏障收得下体现，"
             "不由 `kind` 字符串体现"),
            ("docs/spec.en.md", "The panic/fault split is **observable** — by which "
             "barrier takes the failure, not by the `kind` string"),
        ),
    ),
    (
        "the barriers' effect rows, which are no longer one row",
        (
            ("docs/spec.md", "这一对的效果行**不再是同一个**"),
            ("docs/spec.en.md", "This pair's effect row is **no longer one row**"),
        ),
    ),
    (
        "the three barriers in one line",
        (
            ("docs/spec.md", "于是**三个屏障排成一条线**"),
            ("docs/spec.en.md", "So **the three barriers line up**"),
        ),
    ),
    (
        "the fault-only-from-io invariant, without an exception",
        (
            ("docs/spec.md", "**这条线依赖一条不变式**：**fault 只从 io 来。**"),
            ("docs/spec.en.md", "**The line rests on an invariant**: **a fault only comes "
             "from io.**"),
        ),
    ),
    (
        "a continuation carries its remainder's io bit",
        (
            ("docs/spec.md", "**它的行是块剩余的行在基轴上的 io 位**"),
            ("docs/spec.en.md", "**Its row is the io bit of the rest of the block's row, on "
             "the base axis**"),
        ),
    ),
    (
        "release failure precedence",
        (
            ("docs/spec.md", "失败（raise 而不接）则顶掉原失败、无 suppressed 链"),
            ("docs/spec.en.md", "A failure that **escapes** the release itself (raised "
             "and not caught) replaces the original, with no suppressed chain"),
        ),
    ),
    (
        "effect-polymorphic bracket explanation",
        (
            ("docs/spec.md", "**效果行是变量 `!e`**"),
            ("docs/spec.en.md", "**The effect row is a variable `!e`**"),
        ),
    ),
)

SPEC_PATHS = {ROOT / "docs/spec.md", ROOT / "docs/spec.en.md"}

# These markers start machine-readable builtin function names in a
# normative-spec paragraph. A marked region extends to the next blank line, so
# normal Markdown wrapping cannot move names out of the check. The complete
# inventory must equal the public declaration mirror exactly; focused lists,
# such as the math-conversion row, may name a subset but cannot mint a function.
# Neither kind permits duplicate names within its region. Only lower-case
# identifier spans are function names, so adjacent types such as `Int` and
# `Float` stay ordinary prose.
SPEC_BUILTIN_INVENTORY_MARKER = "<!-- doc-check: builtin-inventory -->"
SPEC_BUILTIN_LIST_MARKER = "<!-- doc-check: builtin-list -->"
PUBLIC_BUILTIN_DECL = re.compile(r"(?m)^pub fn\s+([a-z][A-Za-z0-9_]*)\b")
BUILTIN_DECL_PATH = ROOT / "selfhost/builtins.dawn"

HISTORICAL_V01_MARKER = "<!-- doc-check: historical-v0-1 -->"

HISTORICAL_AUDIT_HEADING = "冻结后的历史状态层（截至 `76491bb`）"
CURRENT_AUDIT_HEADING = "机器权威的当前四状态层"
HISTORICAL_AUDIT_STATES = ("已修", "部分", "开放")
CURRENT_AUDIT_STATES = ("fixed", "partial", "open", "retracted")
HISTORICAL_AUDIT_STATUS = re.compile(r"^\*\*(已修|部分|开放)（(\d+)）\*\*$", re.M)
CURRENT_AUDIT_STATUS = re.compile(
    r"^#### 当前 (fixed|partial|open|retracted)（(\d+)）$", re.M)
HISTORICAL_AUDIT_SELF_CHECK = re.compile(
    r"计数自检：\*\*(\d+) 已修 \+ (\d+) 部分 \+ (\d+) 开放 = (\d+)\*\*")
CURRENT_AUDIT_SELF_CHECK = re.compile(
    r"当前计数自检：\*\*(\d+) fixed \+ (\d+) partial \+ (\d+) open \+ "
    r"(\d+) retracted = (\d+)\*\*")
AUDIT_P1_SELF_CHECK = re.compile(
    r"逐行重算结果：\*\*(\d+) fixed / (\d+) partial / (\d+) open / "
    r"(\d+) retracted = (\d+)\*\*")
AUDIT_FROZEN_TOTAL = 97
AUDIT_CURRENT_TOTAL = 99
AUDIT_FROZEN_TOPIC_TOTALS = (
    ("语法", 19),
    ("语义", 17),
    ("架构", 12),
    ("工具链", 17),
    ("库", 19),
    ("治理", 13),
)
AUDIT_CURRENT_TOPIC_TOTALS = (
    ("语法", 19),
    ("语义", 18),
    ("架构", 13),
    ("工具链", 17),
    ("库", 19),
    ("治理", 13),
)
AUDIT_FROZEN_PREFIX_TOTALS = {
    "SYN": 19,
    "SEM": 17,
    "ARC": 12,
    "TOOL": 17,
    "LIB": 19,
    "GOV": 13,
}
AUDIT_CURRENT_PREFIX_TOTALS = {
    "SYN": 19,
    "SEM": 18,
    "ARC": 13,
    "TOOL": 17,
    "LIB": 19,
    "GOV": 13,
}
AUDIT_TOPIC_PREFIX = {
    "语法": "SYN",
    "语义": "SEM",
    "架构": "ARC",
    "工具链": "TOOL",
    "库": "LIB",
    "治理": "GOV",
}
AUDIT_ID_RANGE = re.compile(
    r"`?(SYN|SEM|ARC|TOOL|LIB|GOV)-(\d{2})`?"
    r"(?:\s*–\s*`?(?:(SYN|SEM|ARC|TOOL|LIB|GOV)-)?(\d{2})`?)?")
AUDIT_ANY_ID = re.compile(r"`?([A-Z]+)-(\d{2})`?")
AUDIT_DETAIL_HEADING = re.compile(r"^##\s+([A-Z]+)-(\d{2})\b", re.M)
AUDIT_P1_DETAIL_HEADING = re.compile(
    r"^##\s+([A-Z]+)-(\d{2})\s+—\s+P1\b", re.M)
AUDIT_DETAIL_FILES = (
    ("SYN", "docs/codebase-audit-v2/01-syntax-and-formatting.md"),
    ("SEM", "docs/codebase-audit-v2/02-types-effects-and-semantics.md"),
    ("ARC", "docs/codebase-audit-v2/03-compiler-and-runtime-architecture.md"),
    ("TOOL", "docs/codebase-audit-v2/04-cli-lsp-build-and-release.md"),
    ("LIB", "docs/codebase-audit-v2/05-stdlib-and-packages.md"),
    ("GOV", "docs/codebase-audit-v2/06-docs-tests-and-governance.md"),
)

AUDIT_INDEX_TABLES = (
    ("docs/README.md", "旧审查设计材料（`docs/audit/`）",
     ("文档", "覆盖", "材料类型", "破坏性边界")),
    ("docs/audit/README.md", "一、材料索引：方案、台账、裁决与过程记录",
     ("文档", "覆盖", "破坏性", "材料类型")),
)
INDEX_TASK_STATUS = re.compile(
    r"\b(?:proposed|done|open|fixed|partial|retracted)\b|"
    r"(?:已|未)(?:落地|完成|关账|修复|裁决|驳回)|仍开放|活账|未动",
    re.I,
)

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
EXTERNAL_STANDARD = re.compile(
    r"\bRFC\s+\d+(?:\.\d+)?\s*(?:(?:" + GENITIVE + r")\s*)?$", re.I)
# `§10.1/§10.2`, `§1.5、§2.6、§11`, `§6.10–§6.12`: the later reference
# inherits the earlier one's document, because nothing but a separator stands
# between them.
REF_SEPARATOR = re.compile(r"[/、,，\-–—~至]")

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


def without_html_comments(text: str) -> str:
    """Blank comments while preserving every source offset and line ending."""
    return re.sub(r"<!--[\s\S]*?-->",
                  lambda match: re.sub(r"[^\r\n]", " ", match.group(0)), text)


MARKDOWN_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")


def markdown_structure(text: str) -> str:
    """Blank fenced blocks while preserving source offsets.

    Both CommonMark fence characters are recognized, including language/info
    strings. A closing fence uses the same character and at least the opener's
    width. Keeping offsets lets section extraction return the original text.
    """
    visible = without_html_comments(text)
    output: list[str] = []
    fence_char: str | None = None
    fence_width = 0
    for line in visible.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if fence_char is not None:
            close = re.match(
                rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_width},}}[ \t]*$", body)
            output.append(re.sub(r"[^\r\n]", " ", line))
            if close:
                fence_char = None
                fence_width = 0
            continue
        opener = MARKDOWN_FENCE_OPEN.match(body)
        if opener and not (opener.group(1).startswith("`") and
                           "`" in opener.group(2)):
            fence_char = opener.group(1)[0]
            fence_width = len(opener.group(1))
            output.append(re.sub(r"[^\r\n]", " ", line))
            continue
        output.append(line)
    return "".join(output)


def prose_only(text: str) -> str:
    """Human-visible prose with examples, comments and inline code removed."""
    return re.sub(r"`[^`\n]*`", "", markdown_structure(text))


def active_markdown(text: str) -> str:
    """Markdown outside fenced examples and HTML comments, with inline code intact."""
    return markdown_structure(text)


def policy_prose(text: str) -> str:
    """Human-visible prose only; comments, examples and inline code cannot satisfy policy."""
    return prose_only(text)


def normalize_prose(text: str) -> str:
    return " ".join(policy_prose(text).split())


def normalize_active_markdown(text: str) -> str:
    """Visible prose plus inline-code tokens, insensitive to ordinary wrapping."""
    return " ".join(active_markdown(text).split())


def markdown_list_items(text: str) -> list[str]:
    """Top-level list items from visible Markdown, returned as raw source slices."""
    structure = active_markdown(text)
    pattern = re.compile(r"^-\s+.*?(?=^-\s+|^#{1,6}\s+|\Z)", re.M | re.S)
    return [text[match.start():match.end()] for match in pattern.finditer(structure)]


def markdown_section(text: str, heading: str) -> str | None:
    """The raw body under one exact heading, through the next peer/parent heading."""
    structure = markdown_structure(text)
    match = re.search(
        r"^(#{2,6})\s+" + re.escape(heading) + r"[ \t]*\r?$", structure, re.M)
    if not match:
        return None
    level = len(match.group(1))
    next_heading = re.search(
        r"^#{1," + str(level) + r"}\s+", structure[match.end():], re.M)
    end = len(text) if next_heading is None else match.end() + next_heading.start()
    return text[match.end():end]


def markdown_section_lead(text: str, heading: str) -> str | None:
    body = markdown_section(text, heading)
    if body is None:
        return None
    child = re.search(r"^#{3,6}\s+", markdown_structure(body), re.M)
    return body if child is None else body[:child.start()]


def markdown_table(text: str, heading: str) -> tuple[tuple[str, ...],
                                                     list[tuple[str, ...]],
                                                     list[str]]:
    """Return the first pipe table in an exact section."""
    body = markdown_section(text, heading)
    if body is None:
        return (), [], [f"missing section {heading!r}"]
    lines = active_markdown(body).splitlines()
    for index in range(len(lines) - 1):
        header = markdown_table_row(lines[index])
        separator = markdown_table_row(lines[index + 1])
        if not header or len(separator) != len(header):
            continue
        if not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))
                   for cell in separator):
            continue
        rows: list[tuple[str, ...]] = []
        for line in lines[index + 2:]:
            row = markdown_table_row(line)
            if not row:
                break
            if len(row) != len(header):
                return header, rows, [f"table under {heading!r} has a row with "
                                      f"{len(row)} cells, expected {len(header)}"]
            rows.append(row)
        return header, rows, []
    return (), [], [f"section {heading!r} has no Markdown table"]


def markdown_table_row(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return ()
    return tuple(cell.strip() for cell in stripped[1:-1].split("|"))


def check_markdown_section_selftest() -> tuple[list[str], int]:
    """Fenced pseudo-headings stay inside a section; real headings terminate it."""
    sample = """# Test
## 1. Kept
before
```dawn
## 88. Backtick pseudo-heading
````
between
~~~yaml
## 89. Tilde pseudo-heading
~~~~
after
## 2. Real
real body
"""
    first = markdown_section(sample, "1. Kept")
    if first is None or "after" not in first:
        return ["Markdown section self-test: a fenced heading truncated its section"], 0
    if "real body" in first:
        return ["Markdown section self-test: a real peer heading did not terminate a section"], 0
    if section_index(sample) != {"1", "2"}:
        return ["Markdown section self-test: fenced pseudo-headings entered the section index"], 0
    if markdown_section(sample, "88. Backtick pseudo-heading") is not None:
        return ["Markdown section self-test: a fenced pseudo-heading became addressable"], 0
    if markdown_section(sample, "3. Missing") is not None:
        return ["Markdown section self-test: a missing heading unexpectedly resolved"], 0
    return [], 5


def markdown_intro(text: str) -> str:
    """The active introduction after H1, before the first example or next heading."""
    text = without_html_comments(text)
    heading = re.search(r"^#\s+.+$", text, re.M)
    if not heading:
        return ""
    tail = text[heading.end():]
    stop = re.search(r"^(?: {0,3}(?:`{3,}|~{3,})|#{1,6}\s+)", tail, re.M)
    return tail if stop is None else tail[:stop.start()]


def inline_code_spans(text: str) -> set[str]:
    return set(re.findall(r"`([^`\n]+)`", active_markdown(text)))


def expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]+)\}", pattern)
    if not match:
        return [pattern]
    out: list[str] = []
    for choice in match.group(1).split(","):
        expanded = pattern[:match.start()] + choice + pattern[match.end():]
        out += expand_braces(expanded)
    return out


def editor_glob_matches(pattern: str, relative_path: str) -> bool:
    candidate = relative_path.replace(os.sep, "/")
    for expanded in expand_braces(pattern):
        if "/" in expanded:
            if fnmatch.fnmatchcase(candidate, expanded.lstrip("/")):
                return True
        elif fnmatch.fnmatchcase(pathlib.PurePosixPath(candidate).name, expanded):
            return True
    return False


def editorconfig_value(text: str, relative_path: str, key: str) -> str | None:
    """Minimal EditorConfig evaluator: ordered sections and last effective property."""
    section: str | None = None
    value: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if "=" not in line:
            continue
        name, candidate = (part.strip() for part in line.split("=", 1))
        if name.lower() != key.lower():
            continue
        if section is None or editor_glob_matches(section, relative_path):
            value = None if candidate.lower() == "unset" else candidate
    return value


def headings_of(text: str) -> list[str]:
    """The document's headings, with fenced blocks dropped first: `## 文档注释,
    ...` inside a fenced Dawn example is a comment, not a heading, and letting
    it into the anchor set makes the check accept fragments GitHub 404s on.

    Only *fenced* blocks go -- prose_only() would also blank inline spans, and
    a heading's inline code is part of its slug (spec.md's `### 6.5 具名效果与
    `with handle`` anchors as `65-具名效果与-with-handle`), so blanking it would
    silently compute the wrong anchor for 267 of this repository's 1410
    headings. That was written the wrong way round first."""
    return HEADING.findall(markdown_structure(text))


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


def resolve_section_document(path: pathlib.Path, name: str, sections: dict,
                             allow_unique_basename: bool) -> pathlib.Path:
    """Resolve explicit document spellings without inventing a missing target.

    Prose in docs/ uses both sibling paths and repository-root `docs/...`
    paths. A bare filename may also name the one indexed document with that
    basename; ambiguity deliberately falls back to the literal missing path.
    Markdown link targets never receive that basename fallback.
    """
    local = (path.parent / name).resolve()
    if local in sections:
        return local
    if name.startswith("docs/"):
        rooted = (ROOT / name).resolve()
        if rooted in sections:
            return rooted
    if allow_unique_basename and "/" not in name:
        candidates = [candidate for candidate in sections if candidate.name == name]
        if len(candidates) == 1:
            return candidates[0]
    return local


def check_sections(path: pathlib.Path, text: str, sections: dict) -> tuple[list[str], int]:
    """Check explicit `§N` targets and bare references in the normative specs.

    See the module docstring for why "a bare §N means this file" remains
    deliberately unsound everywhere else in the repository."""
    bad: list[str] = []
    checked = 0
    text = prose_only(text)
    # `None` as the carried target means an explicitly external standard.
    carry: tuple[pathlib.Path | None, int] | None = None
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
            reference = (link or name or of).group(1)
            hit = resolve_section_document(
                path, reference, sections, allow_unique_basename=link is None)
            if hit not in sections:
                checked += 1
                why = "does not exist" if not hit.exists() else "is not in the document index"
                bad.append(f"{path.relative_to(ROOT)}: explicit section target "
                           f"{hit.relative_to(ROOT) if hit.is_relative_to(ROOT) else hit} {why}")
                carry = None
                continue
            target = hit
        elif REF_VIA_SELF.search(line):
            target = path
        elif carry and REF_SEPARATOR.fullmatch(text[carry[1]:m.start()].strip() or "x"):
            if carry[0] is None:
                checked += 1
                carry = (None, m.end())
                continue
            target = carry[0]
        elif EXTERNAL_STANDARD.search(line):
            checked += 1
            carry = (None, m.end())
            continue
        elif path in SPEC_PATHS:
            target = path
        carry = (target, m.end()) if target else None
        if target is None or not sections[target]:
            continue
        checked += 1
        if label not in sections[target]:
            bad.append(f"{path.relative_to(ROOT)}: §{label} names no section of "
                       f"{target.relative_to(ROOT)}")
    return bad, checked


def check_sections_selftest() -> tuple[list[str], int]:
    """Exercise missing explicit targets, external standards and spec-local refs."""
    path = ROOT / "docs/spec.md"
    other = ROOT / "docs/spec.en.md"
    sections = {path: {"1"}, other: {"1", "2"}}
    missing, _ = check_sections(path, "missing.md §9\n", sections)
    if not any("explicit section target" in problem and "does not exist" in problem
               for problem in missing):
        return ["section self-test: an explicit missing.md target was silently skipped"], 0
    absent, _ = check_sections(path, "spec.en.md §9\n", sections)
    if not any("§9 names no section" in problem for problem in absent):
        return ["section self-test: an explicit missing section was silently skipped"], 0
    external, count = check_sections(path, "RFC 9110 §99\n", sections)
    if external or count != 1:
        return ["section self-test: RFC 9110 §N was misread as a spec-local section"], 0
    chained, count = check_sections(path, "RFC 9110 §9/§10\n", sections)
    if chained or count != 2:
        return ["section self-test: a chained RFC reference fell back to the local spec"], 0
    crossline, count = check_sections(path, "RFC 9110 §9/\n§10\n", sections)
    if crossline or count != 2:
        return ["section self-test: an external chain was not inherited across a separator line"], 0
    inherited, count = check_sections(path, "spec.en.md §1/\n§2\n", sections)
    if inherited or count != 2:
        return ["section self-test: an explicit document chain was not inherited across lines"], 0
    local, count = check_sections(path, "see §1\n", sections)
    if local or count != 1:
        return ["section self-test: a valid bare normative-spec reference failed"], 0
    return [], 7


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


def check_status(path: pathlib.Path, text: str,
                 root: pathlib.Path = ROOT) -> tuple[list[str], int]:
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
    language.

    Scope is a path relationship, not a substring. A clean worktree named
    `dawn-lsp-docs` once made its root README look like a docs/ document because
    the absolute path happened to contain `docs/`."""
    if not path.is_relative_to(root / "docs"):
        return [], 0
    if any(STATUS_LINE.match(line) for line in text.split("\n")[:12]):
        return [], 1
    display = path.relative_to(root) if path.is_relative_to(root) else path
    return [f"{display}: no `> 状态：…` / `> Status: …` line in the "
            f"first 12 lines "
            f"(normative / current / historical / proposed -- see docs/README.md)"], 0


def check_tracked_documents_selftest() -> tuple[list[str], int]:
    """An ignored document is out of scope, and a git that cannot answer is fatal.

    Both halves are assertions about the enumeration rather than about any
    document, and both go red the moment somebody restores the filesystem walk:
    the first because the ignored file comes back, the second because a
    fallback is precisely a refusal to raise. Run against a repository built
    here, so the control does not depend on what this worktree happens to
    contain.
    """
    with tempfile.TemporaryDirectory() as tmp:
        outside = pathlib.Path(tmp)
        (outside / "README.md").write_text("# not a repository\n", encoding="utf-8")
        try:
            tracked_markdown(outside)
        except RuntimeError:
            pass
        else:
            return ["tracked-document self-test: enumeration outside a git "
                    "repository answered instead of failing"], 0

    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp)
        (repo / ".gitignore").write_text("ignored.md\n", encoding="utf-8")
        (repo / "tracked.md").write_text("# tracked\n", encoding="utf-8")
        (repo / "ignored.md").write_text("# ignored\n", encoding="utf-8")
        for argv in (["init", "-q"], ["add", "-A"]):
            done = subprocess.run(["git", "-C", str(repo)] + argv,
                                  capture_output=True, text=True)
            if done.returncode != 0:
                return [f"tracked-document self-test: `git {argv[0]}` failed in a "
                        f"scratch repository: {done.stderr.strip()}"], 0
        got = tracked_markdown(repo)
        if got != {repo / "tracked.md"}:
            return [f"tracked-document self-test: an ignored Markdown file is in "
                    f"scope; enumeration returned "
                    f"{sorted(p.name for p in got)}"], 0
    return [], 2


def check_status_selftest() -> tuple[list[str], int]:
    """A parent name containing docs does not widen the docs/ subtree."""
    root = pathlib.Path("/tmp/dawn-lsp-docs")
    bad, seen = check_status(root / "README.md", "# Root\n", root)
    if bad or seen != 0:
        return ["status scope self-test: a root file under a docs-named worktree "
                "was treated as a docs/ document"], 0
    bad, seen = check_status(root / "docs" / "missing.md", "# Actual doc\n", root)
    if not bad or seen != 0:
        return ["status scope self-test: an actual docs/ file escaped the status check"], 0
    return [], 2


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

    The index is where this repository makes each document discoverable, so a
    document missing from it also hides its authoritative lifecycle header:
    twelve were missing when this was written. The count check alone would not
    have found them -- 58 documents and 46 index entries both read as "some
    number" to a human, and the number was 43."""
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
                       f"(the index is where a document and its lifecycle are discovered)")
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


def effect_contract_problems(rel: str, text: str) -> tuple[list[str], int]:
    """Check the checker's return/effect branches from visible normative structure."""
    heading = "3.1 函数" if rel == "docs/spec.md" else "3.1 Functions"
    section = markdown_section(text, heading)
    if section is None:
        return [f"{rel}: missing normative function section for effect contracts"], 0
    item = next((candidate for candidate in markdown_list_items(section)
                 if {"!Ask", "!(io | Ask)"}.issubset(inline_code_spans(candidate))), None)
    if item is None:
        return [f"{rel}: no visible function-policy item relates !Ask to !(io | Ask)"], 0

    prose = normalize_prose(item).replace("*", "")
    active = normalize_active_markdown(item).replace("*", "")
    spans = inline_code_spans(item)
    bad: list[str] = []
    seen = 0
    if rel == "docs/spec.md":
        joint_inference = (
            re.search(r"(?:只有|仅(?:当|在)?).{0,32}私有函数.{0,24}同时.{0,16}省略返回类型"
                      r".{0,20}(?:全部|所有|每个)效果(?:注记|标注)", prose)
            and re.search(r"(?:推断|推导).{0,16}返回类型.{0,24}(?:base effect|基础效果)", prose)
        )
        explicit_pure = (
            {"-> T", "pure"}.issubset(spans)
            and re.search(r"显式.{0,20}-> T.{0,24}省略.{0,16}效果(?:注记|标注)", active)
            and re.search(r"pure.{0,12}承诺", active, re.I)
            and re.search(r"IO.{0,20}(?:报错|错误|拒绝)", active, re.I)
        )
        named_never = re.search(
            r"具名效果.{0,24}(?:从不|永不|不会|不得|不能).{0,16}(?:推断|推导)", prose)
        fixed_row = (re.search(r"效果行.{0,32}(?:固定|钉死|承诺)", prose)
                     and re.search(r"(?:不会|不再|不得).{0,16}(?:自动)?补.{0,8}io", prose, re.I))
        combined = (re.search(r"同时.{0,16}(?:做|执行).{0,8}IO", active, re.I)
                    and re.search(r"(?:必须|需要|应当).{0,12}(?:写|声明)", active))
    else:
        folded = prose.casefold()
        active_folded = active.casefold()
        joint_inference = (
            re.search(r"\bonly\b.{0,24}private function.{0,24}omit(?:s|ted|ting)? both"
                      r".{0,20}return type.{0,24}every effect annotation", folded)
            and (re.search(r"infer.{0,24}return type.{0,24}base effect", folded)
                 or re.search(r"return type and base effect.{0,24}infer", folded))
        )
        explicit_pure = (
            {"-> T", "pure"}.issubset(spans)
            and re.search(r"writing.{0,16}-> t.{0,24}omitting.{0,20}effect annotation",
                          active_folded)
            and re.search(r"pure.{0,12}promise", active_folded)
            and re.search(r"performing io.{0,20}(?:error|rejected)", active_folded)
        )
        named_never = (re.search(r"named effects?.{0,24}(?:never|not).{0,16}infer", folded)
                       or re.search(r"named effects?.{0,24}must not be inferred", folded))
        fixed_row = (re.search(r"effect row.{0,32}(?:fixed|pinned|promise)", folded)
                     and (re.search(r"io.{0,24}not added automatically", folded)
                          or re.search(r"does not.{0,24}automatically.{0,12}io", folded)))
        combined = (re.search(r"also.{0,16}(?:perform|do).{0,8}io", active_folded)
                    and re.search(r"must.{0,12}(?:write|declare)", active_folded))

    for condition, name in (
        (joint_inference,
         "return and base effects are jointly inferred only after both annotations are omitted"),
        (explicit_pure,
         "an explicit return type with no effect annotation is a checked pure promise"),
        (named_never, "named effects are never inferred"),
        (fixed_row, "an explicit named-effect row is fixed and does not gain io"),
        (combined and {"!Ask", "!(io | Ask)", "!io"}.issubset(spans),
         "a !Ask function doing IO must explicitly write !(io | Ask)"),
    ):
        if condition:
            seen += 1
        else:
            bad.append(f"{rel}: effect contract does not establish that {name}")
    return bad, seen


def propagation_contract_problems(rel: str, text: str) -> tuple[list[str], int]:
    """Check `?` as propagation shorthand and keep explicit jumps distinct."""
    heading = ("8.1 可恢复：Result / Option + `?`" if rel == "docs/spec.md"
               else "8.1 Recoverable: Result / Option + `?`")
    section = markdown_section(text, heading)
    if section is None:
        return [f"{rel}: missing normative Result/Option propagation section"], 0
    required = {"?", "Option", "Result", "return", "break", "continue"}
    item = next((candidate for candidate in markdown_list_items(section)
                 if required.issubset(inline_code_spans(candidate))), None)
    if item is None:
        return [f"{rel}: no visible policy item distinguishes ? from explicit jumps"], 0
    prose = normalize_prose(item).replace("*", "")
    if rel == "docs/spec.md":
        propagation = ("表达式级" in prose and "传播" in prose
                       and re.search(r"(?:简写|缩写)", prose))
        jumps = (re.search(r"(?:独立|分开|单独).{0,24}(?:显式|明确).{0,12}(?:jump|跳转)",
                           prose, re.I))
    else:
        folded = prose.casefold()
        propagation = ("expression-level" in folded and "propagation" in folded
                       and "shorthand" in folded)
        jumps = re.search(r"separate.{0,24}explicit jumps", folded)
    bad: list[str] = []
    if not propagation:
        bad.append(f"{rel}: ? is not defined as expression-level Option/Result propagation shorthand")
    if not jumps:
        bad.append(f"{rel}: return/break/continue are not distinguished as explicit jumps")
    return bad, int(bool(propagation)) + int(bool(jumps))


def builtin_list_contract_problems(
        texts: dict[pathlib.Path, str]) -> tuple[list[str], int]:
    """Hold the exact inventory and focused builtin claims to the mirror."""
    declared = set(PUBLIC_BUILTIN_DECL.findall(
        BUILTIN_DECL_PATH.read_text(encoding="utf-8")))
    if not declared:
        return [f"{BUILTIN_DECL_PATH.relative_to(ROOT)}: no public builtin declarations found"], 0

    bad: list[str] = []
    seen = 0
    for path in sorted(SPEC_PATHS):
        rel = str(path.relative_to(ROOT))
        text = texts.get(path)
        if text is None:
            bad.append(f"{rel}: cannot check builtin list; document missing")
            continue
        for label, marker, exact in (
                ("builtin inventory", SPEC_BUILTIN_INVENTORY_MARKER, True),
                ("builtin list", SPEC_BUILTIN_LIST_MARKER, False)):
            marker_count = text.count(marker)
            if marker_count != 1:
                bad.append(f"{rel}: expected one {marker}, found {marker_count}")
                continue
            marker_at = text.index(marker)
            start = marker_at + len(marker)
            region = text[start:].split("\n\n", 1)[0]
            names = [name for name in re.findall(
                     r"`([^`\n]+)`", active_markdown(region))
                     if re.fullmatch(r"[a-z][A-Za-z0-9_]*", name)]
            if not names:
                bad.append(f"{rel}: {label} names no builtin functions")
                continue
            duplicates = sorted({name for name in names if names.count(name) > 1})
            if duplicates:
                bad.append(f"{rel}: {label} repeats function(s): "
                           f"{', '.join(duplicates)}")
            unknown = sorted(set(names) - declared)
            if unknown:
                bad.append(f"{rel}: {label} names function(s) absent from "
                           f"selfhost/builtins.dawn: {', '.join(unknown)}")
            if exact:
                missing = sorted(declared - set(names))
                if missing:
                    bad.append(f"{rel}: builtin inventory omits declared function(s): "
                               f"{', '.join(missing)}")
            seen += len(names)
    return bad, seen


def spec_contract_problems(texts: dict[pathlib.Path, str]) -> tuple[list[str], int]:
    normalized = {path: normalize_prose(text) for path, text in texts.items()}
    bad: list[str] = []
    seen = 0
    for name, clauses in SPEC_CONTRACTS:
        for rel, fragment in clauses:
            path = ROOT / rel
            text = normalized.get(path)
            if text is None:
                bad.append(f"{rel}: cannot check settled spec contract {name!r}; "
                           "the document is not in the documentation index")
                continue
            expected = normalize_prose(fragment)
            if not expected:
                bad.append(f"{rel}: spec contract {name!r} has no prose to check")
                continue
            if expected not in text:
                bad.append(f"{rel}: missing settled spec contract {name!r}")
                continue
            seen += 1
    for rel in ("docs/spec.md", "docs/spec.en.md"):
        path = ROOT / rel
        text = texts.get(path)
        if text is None:
            bad.append(f"{rel}: cannot check structured semantic contracts; document missing")
            continue
        problems, count = effect_contract_problems(rel, text)
        bad += problems
        seen += count
        problems, count = propagation_contract_problems(rel, text)
        bad += problems
        seen += count
    problems, count = builtin_list_contract_problems(texts)
    bad += problems
    seen += count
    return bad, seen


def check_spec_contracts(texts: dict[pathlib.Path, str]) -> tuple[list[str], int]:
    return spec_contract_problems(texts)


def check_spec_contracts_selftest(texts: dict[pathlib.Path, str]) -> tuple[list[str], int]:
    """Each language independently rejects wrong effect and `?` semantics."""
    zh = ROOT / "docs/spec.md"
    baseline, _ = spec_contract_problems(texts)
    if baseline:
        return [f"spec contract self-test baseline is invalid: {baseline[0]}"], 0

    mutated = dict(texts)
    clause = "失败（raise 而不接）则顶掉原失败、无 suppressed 链"
    if clause not in mutated[zh]:
        return ["spec contract self-test: release precedence fixture is absent"], 0
    mutated[zh] = mutated[zh].replace(clause, "release 失败时保留原失败", 1)
    mutated[zh] += f"\n<!-- {clause} -->\n"
    bad, _ = spec_contract_problems(mutated)
    if not any("release failure precedence" in problem for problem in bad):
        return ["spec contract self-test: an HTML comment falsely satisfied a clause"], 0

    false_builtin = dict(texts)
    if SPEC_BUILTIN_LIST_MARKER not in false_builtin[zh]:
        return ["spec contract self-test: builtin-list fixture is absent"], 0
    false_builtin[zh] = false_builtin[zh].replace(
        SPEC_BUILTIN_LIST_MARKER,
        SPEC_BUILTIN_LIST_MARKER + "\n`sqrt`、", 1)
    bad, _ = spec_contract_problems(false_builtin)
    if not any("builtin list names function(s) absent" in problem for problem in bad):
        return ["spec contract self-test: a nonexistent builtin passed the prose mirror"], 0

    missing_builtin = dict(texts)
    if "`len`/" not in missing_builtin[zh]:
        return ["spec contract self-test: exact builtin fixture is absent"], 0
    missing_builtin[zh] = missing_builtin[zh].replace("`len`/", "", 1)
    bad, _ = spec_contract_problems(missing_builtin)
    if not any("builtin inventory omits declared function(s): len" in problem
               for problem in bad):
        return ["spec contract self-test: an omitted builtin passed the inventory"], 0

    duplicate_builtin = dict(texts)
    duplicate_builtin[zh] = duplicate_builtin[zh].replace(
        "`len`/", "`len`/`len`/", 1)
    bad, _ = spec_contract_problems(duplicate_builtin)
    if not any("builtin inventory repeats function(s): len" in problem
               for problem in bad):
        return ["spec contract self-test: a duplicate builtin passed the inventory"], 0

    fixtures = (
        (ROOT / "docs/spec.md", "3.1 函数",
         "同时省略返回类型和全部效果注记", "只省略全部效果注记",
         "8.1 可恢复：Result / Option + `?`", "表达式级传播简写", "唯一的非局部控制流"),
        (ROOT / "docs/spec.en.md", "3.1 Functions",
         "omits both its return type and every effect annotation",
         "omits every effect annotation",
         "8.1 Recoverable: Result / Option + `?`",
         "expression-level propagation shorthand", "only non-local control flow"),
    )
    for path, function_heading, condition, wrong, propagation_heading, phrase, obsolete in fixtures:
        rel = str(path.relative_to(ROOT))

        wrong_condition = dict(texts)
        function_section = markdown_section(wrong_condition[path], function_heading)
        if function_section is None or condition not in function_section:
            return [f"spec contract self-test: {rel} inference-condition fixture is absent"], 0
        changed = function_section.replace(condition, wrong, 1)
        wrong_condition[path] = wrong_condition[path].replace(function_section, changed, 1)
        wrong_condition[path] += f"\n<!-- {condition} -->\n"
        bad, _ = spec_contract_problems(wrong_condition)
        if not any(problem.startswith(rel + ":") and "jointly inferred only" in problem
                   for problem in bad):
            return [f"spec contract self-test: {rel} accepted the wrong inference condition"], 0

        missing_row = dict(texts)
        function_section = markdown_section(missing_row[path], function_heading)
        if function_section is None or "`!(io | Ask)`" not in function_section:
            return [f"spec contract self-test: {rel} named-effect union fixture is absent"], 0
        changed = function_section.replace("`!(io | Ask)`", "`!Ask`", 1)
        missing_row[path] = missing_row[path].replace(function_section, changed, 1)
        missing_row[path] += "\n```dawn\n# fake policy: `!(io | Ask)`\n```\n"
        bad, _ = spec_contract_problems(missing_row)
        if not any(problem.startswith(rel + ":") and "relates !Ask to !(io | Ask)" in problem
                   for problem in bad):
            return [f"spec contract self-test: {rel} accepted a missing named-effect union"], 0

        wrong_propagation = dict(texts)
        propagation_section = markdown_section(wrong_propagation[path], propagation_heading)
        if propagation_section is None or phrase not in propagation_section:
            return [f"spec contract self-test: {rel} propagation fixture is absent"], 0
        changed = propagation_section.replace(phrase, obsolete, 1)
        wrong_propagation[path] = wrong_propagation[path].replace(
            propagation_section, changed, 1)
        wrong_propagation[path] += f"\n<!-- {phrase} -->\n"
        bad, _ = spec_contract_problems(wrong_propagation)
        if not any(problem.startswith(rel + ":")
                   and "expression-level Option/Result propagation" in problem for problem in bad):
            return [f"spec contract self-test: {rel} accepted obsolete ? semantics"], 0
    return [], 10


def check_effect_inference_probe() -> tuple[list[str], int]:
    """Pin the checker's annotated-pure and double-omission branches end to end."""
    sources = {
        "explicit_return.dawn": """fn writes_io() -> Unit = {
  println("explicit")
}

pub fn main() -> Unit !io = writes_io()
""",
        "double_omission.dawn": """fn infers_io() = {
  println("inferred")
}

pub fn main() -> Unit !io = infers_io()
""",
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        for name, source in sources.items():
            (work / name).write_text(source, encoding="utf-8")
        explicit = run_example([str(DAWN), "check", str(work / "explicit_return.dawn")],
                               cwd=ROOT)
        inferred = run_example([str(DAWN), "check", str(work / "double_omission.dawn")],
                               cwd=ROOT)
    if explicit is None or inferred is None:
        return ["effect inference probe did not finish within the example timeout"], 0
    if explicit.returncode == 0 or "not declared !io" not in explicit.stderr:
        return ["effect inference probe: explicit -> Unit without an effect was not checked pure"], 0
    if inferred.returncode != 0:
        detail = (inferred.stderr or inferred.stdout).strip().splitlines()
        return ["effect inference probe: double omission did not infer io: " +
                (detail[0] if detail else f"exit {inferred.returncode}")], 0
    return [], 2


# --- the named-effect tier's status ----------------------------------------
# The README and the front page both say, in both languages, who the
# named-effect tier's internal consumers are. For a long time the answer was
# "nobody", and that is exactly the shape of sentence that stops being true
# without anybody noticing; today the answer is a list, `std/io` with `Fs` and
# `Proc` and `std/gpu` with `Gpu`, and a list is the same shape of sentence
# several times over: another declaration can appear without the documents
# hearing of it, and any of these can disappear the same way.
#
# So the list is held from both sides, at file granularity, the way
# builtin-decl-mirror and opaque-twin hold theirs. NAMED_EFFECT_EXPECTED names
# every file under the roots that declares an effect. A declaration anywhere
# else is red, which keeps the property the original check was worth: the
# next person to declare an effect in std or the compiler is named, and has to
# put it on the list and in the documents. A listed file that stops declaring
# is red. A listed file that does not exist is red: an exemption has to prove
# itself (the jvm-only marker taught that one). And every registered document
# has to carry its sentence about the consumer that exists.
#
# Deliberately not covered: whether a consumer is more than a token, and
# whether the compiler ought to be a declarer as well as a consumer. This
# counts declarations against a list.
NAMED_EFFECT_ROOTS = ("std", "selfhost/src")
NAMED_EFFECT_DECL = re.compile(r"(?m)^(?:pub\s+)?(?:ctl\s+)?effect\s+[A-Za-z_]")
NAMED_EFFECT_EXPECTED = ("std/gpu.dawn", "std/io.dawn")
NAMED_EFFECT_STATUS = (
    ("README.md", "the tier's internal consumers are in this repository"),
    ("README.zh-CN.md", "内部使用者就在本仓"),
    ("site/pages/home.md", "the tier's internal consumers are in this repository"),
    ("site/pages/home.zh.md", "内部使用者就在本仓"),
)
# Sentences the documents used to carry, each with what it was true about.
# Half an edit leaves the old phrase in the paragraph beside the new one, and
# the new phrase alone would pass the check below; so every retired wording
# stays listed here rather than being deleted along with the prose.
#
# The list is not only about the consumer count. A paragraph this narrow goes
# stale in whatever direction the language moved, so a claim retired for any
# reason is registered here: the resumption sentence was retired by control
# arms, not by a new declaration.
NAMED_EFFECT_STALE = (
    ("no internal consumer", "the tier had no consumer at all"),
    ("没有内部使用者", "the tier had no consumer at all"),
    ("its first internal consumer", "std/io was the only declarer"),
    ("第一个内部使用者", "std/io was the only declarer"),
    ("not yet a real program", "no program ran on the tier"),
    ("还没扛过一个真实程序", "no program ran on the tier"),
    ("multi-shot and non-tail resumption are not supported",
     "every arm was tail-resumptive"),
    ("不支持多次恢复与非尾恢复", "every arm was tail-resumptive"),
)


def named_effect_users(sources: dict[str, str]) -> list[str]:
    return sorted(rel for rel, text in sources.items()
                  if NAMED_EFFECT_DECL.search(text))


def named_effect_status_problems(sources: dict[str, str],
                                 docs: dict[str, str],
                                 expected: tuple[str, ...] = NAMED_EFFECT_EXPECTED
                                 ) -> tuple[list[str], int]:
    users = set(named_effect_users(sources))
    roots = ", ".join(f"{root}/" for root in NAMED_EFFECT_ROOTS)
    bad: list[str] = []
    seen = 0
    for rel in expected:
        if rel not in sources:
            bad.append(f"{rel}: listed in NAMED_EFFECT_EXPECTED as a named-effect "
                       f"declarer, but no such file exists under {roots}; an "
                       f"exemption has to name a real file")
        elif rel not in users:
            bad.append(f"{rel}: listed in NAMED_EFFECT_EXPECTED as a named-effect "
                       f"declarer, but declares no effect. Either the declaration "
                       f"moved (list its new file) or the tier lost its consumer "
                       f"(say so in the four outward documents)")
        else:
            seen += 1
    for rel in sorted(users - set(expected)):
        bad.append(f"{rel}: declares an effect, and is not in NAMED_EFFECT_EXPECTED. "
                   f"The named-effect tier's internal consumers are enumerated: "
                   f"add the file to the list and the outward documents")
    for rel, fragment in NAMED_EFFECT_STATUS:
        text = docs.get(rel)
        if text is None:
            bad.append(f"{rel}: registered for the named-effect status claim, "
                       f"but does not exist")
            continue
        stale = [(old, why) for old, why in NAMED_EFFECT_STALE if old in text]
        if stale:
            phrase, why = stale[0]
            bad.append(f"{rel}: still says {phrase!r}, which was true when "
                       f"{why}. It is not true today; the paragraph the four "
                       f"outward documents carry has to be rewritten in all "
                       f"four, not half-edited.")
        elif fragment not in text:
            bad.append(f"{rel}: {', '.join(expected)} declares the named-effect "
                       f"tier's internal consumer, so this document has to say so; "
                       f"expected the phrase {fragment!r}")
        else:
            seen += 1
    return bad, seen


def read_named_effect_sources() -> dict[str, str]:
    sources: dict[str, str] = {}
    for root in NAMED_EFFECT_ROOTS:
        for path in sorted((ROOT / root).rglob("*.dawn")):
            sources[path.relative_to(ROOT).as_posix()] = \
                path.read_text(encoding="utf-8")
    return sources


def read_named_effect_docs() -> dict[str, str]:
    return {rel: (ROOT / rel).read_text(encoding="utf-8")
            for rel, _fragment in NAMED_EFFECT_STATUS if (ROOT / rel).exists()}


def check_named_effect_status() -> tuple[list[str], int]:
    return named_effect_status_problems(read_named_effect_sources(),
                                        read_named_effect_docs())


def check_named_effect_status_selftest() -> tuple[list[str], int]:
    sources = read_named_effect_sources()
    docs = read_named_effect_docs()
    baseline, _ = named_effect_status_problems(sources, docs)
    if baseline:
        return [f"named-effect status self-test baseline is invalid: {baseline[0]}"], 0

    # Prose about effects is not adoption; a file that only talks about them
    # must stay green, or the check reddens on its own documentation.
    mention = dict(sources)
    mention["std/mention.dawn"] = "## an effect declaration would go here\nfn f() = 1\n"
    bad, _ = named_effect_status_problems(mention, docs)
    if bad:
        return ["named-effect status self-test: prose about effects was read as "
                f"adoption: {bad[0]}"], 0

    # A declaration outside the list is the case the original check existed
    # for, and the list must not have weakened it: one stray declaration, in
    # either root, reddens and is named.
    #
    # Both spellings, because a control effect is a declaration too. `ctl
    # effect` has been accepted since the one-shot resume work (spec 6.5), and
    # the pattern above did not match it until #67: a `pub ctl effect` in std
    # was counted as nothing at all, and the status paragraph was not held to
    # it. A control that plants only the plain spelling cannot tell.
    for stray, decl in (("std/ask.dawn", "pub effect Ask"),
                        ("selfhost/src/check/ask.dawn", "pub effect Ask"),
                        ("std/ctlask.dawn", "pub ctl effect Ask"),
                        ("selfhost/src/check/ctlask.dawn", "ctl effect Ask")):
        adopted = dict(sources)
        adopted[stray] = f"{decl} {{\n  fn ask() -> Int\n}}\n"
        bad, _ = named_effect_status_problems(adopted, docs)
        if not any(problem.startswith(f"{stray}: declares an effect") for problem in bad):
            return ["named-effect status self-test: a declaration outside "
                    f"NAMED_EFFECT_EXPECTED ({stray}, spelled {decl!r}) "
                    "stayed green"], 0

    # The listed file losing its declaration is the reverse direction, and the
    # documents would go on naming a consumer that is gone.
    lost = dict(sources)
    for rel in NAMED_EFFECT_EXPECTED:
        lost[rel] = NAMED_EFFECT_DECL.sub("# effect gone", lost[rel])
    bad, _ = named_effect_status_problems(lost, docs)
    if not any("declares no effect" in problem for problem in bad):
        return ["named-effect status self-test: removing the listed declaration "
                "stayed green"], 0

    # An exemption has to prove itself: a listed file that does not exist is
    # not a consumer, it is a typo with the power to silence the check.
    bad, _ = named_effect_status_problems(sources, docs,
                                          NAMED_EFFECT_EXPECTED + ("std/ghost.dawn",))
    if not any(problem.startswith("std/ghost.dawn: listed") for problem in bad):
        return ["named-effect status self-test: a listed file that does not exist "
                "stayed green"], 0

    # And the documents. Four copies of one paragraph is four chances to edit
    # three of them, so each copy is dropped in turn rather than only the
    # README's: a control that names one file measures one file.
    for rel, fragment in NAMED_EFFECT_STATUS:
        silent = dict(docs)
        silent[rel] = silent[rel].replace(fragment, "a consumer somewhere", 1)
        bad, _ = named_effect_status_problems(sources, silent)
        if not any(problem.startswith(f"{rel}: ") and "has to say so" in problem
                   for problem in bad):
            return ["named-effect status self-test: dropping the claim from "
                    f"{rel} stayed green"], 0

    # A retired wording reappearing is the other half, and it is the half a
    # rewrite actually risks: the phrases below were all true once, so a
    # revert, a bad merge or a copy from an older paragraph puts one back
    # while the new sentence stays in place and satisfies the fragment above.
    # Each is planted in each copy, because the stale list is shared and a
    # phrase that only reddened README.md would leave the other three open.
    for phrase, _why in NAMED_EFFECT_STALE:
        for rel, _fragment in NAMED_EFFECT_STATUS:
            regressed = dict(docs)
            regressed[rel] = regressed[rel] + f"\n{phrase}\n"
            bad, _ = named_effect_status_problems(sources, regressed)
            if not any(problem.startswith(f"{rel}: still says") for problem in bad):
                return ["named-effect status self-test: "
                        f"{rel} carrying the retired wording {phrase!r} beside "
                        "the new one stayed green"], 0

    # Positive control for the two loops above: the real documents, unedited,
    # are green. Without it a `named_effect_status_problems` that reddened on
    # everything would pass every control in this function.
    bad, _ = named_effect_status_problems(sources, docs)
    if bad:
        return ["named-effect status self-test: the unedited documents went "
                f"red: {bad[0]}"], 0
    return [], 7 + len(NAMED_EFFECT_STATUS) * (1 + len(NAMED_EFFECT_STALE)) + 1


# --- the analyze tests' handler rows ----------------------------------------
# `driver/analyze`'s test block answers all three named effects from tables:
# `driver/fsmem` for `Fs`, `procmem` for `Proc` where a test scripts one, and
# `envmem` for `Env`. That is what lets the block say "no host behind it" and
# what lets one test declare a working directory and assert a relative target
# resolved against it.
#
# Neither half of that is visible in a test's own output. A body that quietly
# went back to `io.with_env_real` would still pass every assertion it makes,
# because the assertions are about paths and the host answers with a path
# too; only the declared row and the absence of the real handler say which
# one answered. So both are held from outside the file, the way
# NAMED_EFFECT_EXPECTED holds the declarer list.
#
# The rows still end in `!io`, and that is a pinned decision rather than an
# omission: stage 1 of the bootstrap compiles this tree against the std the
# seed shipped with, where `io.cwd` and `io.getenv` are `!io` and not `Env`
# (docs/bootstrap.md, feature discipline 4), so every production function
# these tests call declares it. Pinning the row exactly means the backfill a
# seed round from now has to come here and say so, and means neither atom can
# be added or dropped quietly in the meantime.
ANALYZE_ENV_SOURCE = "selfhost/src/driver/analyze.dawn"
ANALYZE_ENV_ROW = "body: fn() -> T !Fs !Proc !Env !io"
ANALYZE_ENV_WRAPPERS = ("in_mem", "in_mem_env", "in_mem_proc")
# Every `with_env_real` the file is allowed to spell, and what each is for.
# Anything else is a test that went back to the host.
ANALYZE_ENV_REAL_ANCHORS = (
    ("io.with_fs_real(() => io.with_proc_real(() => io.with_env_real(() => {",
     "the production install point in analyze_document"),
    ("io.with_fs_real(() => io.with_env_real(() => {",
     "the deliberate host query that says the declared directory is not this one"),
)
ANALYZE_ENV_DOC = "docs/effects-design.md"
ANALYZE_ENV_DOC_CLAUSES = (
    "no host behind it",
    "`driver/analyze` 的 21 条测试侧安装点",
)


def analyze_env_table_problems(source: str, doc: str) -> tuple[list[str], int]:
    bad: list[str] = []
    seen = 0

    for name in ANALYZE_ENV_WRAPPERS:
        declaration = re.search(rf"(?m)^fn {name}\[T\]\((.*?)^\) ->",
                                source, re.S)
        head = declaration.group(1) if declaration else None
        if head is None:
            single = re.search(rf"(?m)^fn {name}\[T\]\((.*)\) ->", source)
            head = single.group(1) if single else None
        if head is None:
            bad.append(f"{ANALYZE_ENV_SOURCE}: no test-side handler wrapper "
                       f"`{name}` to hold a row on; the analyze tests' effect "
                       f"boundary moved and this check has to move with it")
        elif ANALYZE_ENV_ROW not in head:
            bad.append(f"{ANALYZE_ENV_SOURCE}: `{name}` does not declare its body "
                       f"row as `{ANALYZE_ENV_ROW}`. `Env` missing means the tests "
                       f"under it answer the environment from the host; `!io` "
                       f"missing or extra is a decision (see the comment above "
                       f"`in_mem`), so say it in both places or in neither")
        else:
            seen += 1

    spelled = source.count("with_env_real")
    accounted = 0
    for literal, why in ANALYZE_ENV_REAL_ANCHORS:
        count = source.count(literal)
        if count != 1:
            bad.append(f"{ANALYZE_ENV_SOURCE}: expected exactly one "
                       f"{why} ({literal!r}), found {count}")
        else:
            accounted += 1
            seen += 1
    # the comment above `in_mem` names the check, so it spells the identifier
    # too; that mention is a `with_env_real` the count has to allow for
    mentions = len(re.findall(r"`with_env_real`", source))
    if spelled != accounted + mentions:
        bad.append(f"{ANALYZE_ENV_SOURCE}: spells `with_env_real` {spelled} times, "
                   f"but only {accounted} production install(s) and {mentions} "
                   f"prose mention(s) are registered. A test that installs the real "
                   f"handler answers the environment from the machine it runs on, "
                   f"which is the thing the tables exist to stop")
    else:
        seen += 1

    for clause in ANALYZE_ENV_DOC_CLAUSES:
        if clause not in doc:
            bad.append(f"{ANALYZE_ENV_DOC}: the effect-design record does not carry "
                       f"{clause!r}; the analyze tables' verdict is stated in the "
                       f"source and has to be stated here too")
        else:
            seen += 1
    return bad, seen


def read_analyze_env_inputs() -> tuple[str, str]:
    return ((ROOT / ANALYZE_ENV_SOURCE).read_text(encoding="utf-8"),
            (ROOT / ANALYZE_ENV_DOC).read_text(encoding="utf-8"))


def check_analyze_env_table() -> tuple[list[str], int]:
    return analyze_env_table_problems(*read_analyze_env_inputs())


def check_analyze_env_table_selftest() -> tuple[list[str], int]:
    source, doc = read_analyze_env_inputs()
    baseline, _ = analyze_env_table_problems(source, doc)
    if baseline:
        return [f"analyze env-table self-test baseline is invalid: {baseline[0]}"], 0

    # Dropping the named effect is the case that matters: the tests go on
    # passing, and the environment behind them is the machine's again.
    for atom in ("!Env ", "!io"):
        weakened = source.replace(ANALYZE_ENV_ROW,
                                  ANALYZE_ENV_ROW.replace(atom, "", 1))
        bad, _ = analyze_env_table_problems(weakened, doc)
        if not any("does not declare its body row" in problem for problem in bad):
            return ["analyze env-table self-test: a wrapper row without "
                    f"{atom.strip()!r} stayed green"], 0

    # And putting the real handler back on a test, which is the same regression
    # spelled the other way and leaves every assertion in the file passing.
    restored = source.replace("  in_mem(() => {",
                              "  in_mem(() => io.with_env_real(() => {", 1)
    bad, _ = analyze_env_table_problems(restored, doc)
    if not any("only" in problem and "registered" in problem for problem in bad):
        return ["analyze env-table self-test: a test that reinstalled "
                "`with_env_real` stayed green"], 0

    # The production install point disappearing is the opposite failure: the
    # tests would be fine and the compiler would answer `Env` nowhere.
    for literal, why in ANALYZE_ENV_REAL_ANCHORS:
        gone = source.replace(literal, "HANDLER_REMOVED", 1)
        bad, _ = analyze_env_table_problems(gone, doc)
        if not any("expected exactly one" in problem for problem in bad):
            return ["analyze env-table self-test: losing "
                    f"{why} stayed green"], 0

    for clause in ANALYZE_ENV_DOC_CLAUSES:
        silent = doc.replace(clause, "something else", 1)
        bad, _ = analyze_env_table_problems(source, silent)
        if not any("does not carry" in problem for problem in bad):
            return ["analyze env-table self-test: dropping "
                    f"{clause!r} from the record stayed green"], 0

    # Positive control: the unedited pair is green, so the controls above
    # measured the mutation rather than a checker that reddens on everything.
    bad, _ = analyze_env_table_problems(source, doc)
    if bad:
        return ["analyze env-table self-test: the unedited pair went red: "
                f"{bad[0]}"], 0
    return [], 4 + len(ANALYZE_ENV_REAL_ANCHORS) + len(ANALYZE_ENV_DOC_CLAUSES)


REPOSITORY_POLICY_FILES = (
    ".editorconfig",
    ".github/workflows/release.yml",
    "CONTRIBUTING.md",
    "README.md",
    "README.zh-CN.md",
    "docs/package-design.md",
    "docs/spec.md",
    "docs/spec.en.md",
    "site/pages/home.md",
    "site/pages/home.zh.md",
)

# Exact corpus and artifact sizes in outward copy decay without changing any
# decision a reader makes. The README's native differential grew from 59 to
# more than a hundred entries while still advertising 59 in four places, and
# the released native binary outgrew both size figures in the toolchain
# walkthrough. GOV-11 already removed this class of volatile scale metric from
# the introduction; keep it out of the other outward surfaces too rather than
# making every corpus addition or toolchain build a translation edit.
OUTWARD_CORPUS_COUNTS = (
    ("README.md", re.compile(
        r"(?:\b\d+\s+(?:differential\s+)?corpus (?:programs|entries)\b|"
        r"\bThe \d+ programs under `scripts/spike-native/`)", re.I)),
    ("site/pages/home.md", re.compile(
        r"\b\d+\s+(?:differential\s+)?corpus (?:programs|entries)\b", re.I)),
    ("README.zh-CN.md", re.compile(
        r"(?:\d+\s*个(?:差分|对拍)?语料(?:程序|入口)|"
        r"下的\s*\d+\s*个程序)")),
    ("site/pages/home.zh.md", re.compile(
        r"\d+\s*个(?:差分|对拍)?语料(?:程序|入口)")),
)

BINARY_SIZE_LITERAL = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:KiB|MiB|GiB|KB|MB|GB)\b", re.I)
TOOLCHAIN_ARTIFACT_SECTIONS = (
    ("README.md", "Two different things are called \"native\""),
    ("README.md", "The road without a JVM"),
    ("README.zh-CN.md", "两样东西都叫「native」"),
    ("README.zh-CN.md", "不装 JVM 的那条路"),
)

# The install instructions download release assets by name, and the release
# workflow decides what those names are. Nothing connected the two, which is
# how a README comes to advertise an artifact no release carries (it already
# happened once here, in 2026-08). So the set of assets README fetches is
# compared against the set release.yml requires itself to have published, in
# both directions: an asset renamed in the workflow reds the README, and an
# asset dropped from the README reds too.
#
# The comparison is on `$base/<name>`, the shell variable the install block
# assigns the release URL to, rather than on bare names: `dawnc-linux-x86_64`
# is a word README uses in prose as well, and a check that a word occurs
# somewhere in a 300-line document is not a check.
#
# A release carries two kinds of asset and they answer to different sentences.
# `INSTALL_ASSETS` is what an install step fetches, and that set is what the
# `$base/<name>` comparison above is about. `REPORT_ASSETS` (the pub-API
# snapshot and its diff, issue #29) describe a release rather than being one:
# telling a reader to `curl` a Markdown report before running `hello.dawn`
# would be wrong, so they are held to a weaker rule -- each must be *named*, in
# inline code, in every install document. An asset no document mentions is an
# asset nobody knows to look for, which is the same failure the fetch check
# exists for, one step milder.
#
# `EXPECTED_ASSETS`, the list the publish step actually uploads and then
# requires exactly once, is pinned to the concatenation of the two. Without
# that pin the workflow could keep both lists honest and upload only one of
# them, and both checks here would stay green.
RELEASE_ASSET_BASE = "https://github.com/dawnop/dawn-lang/releases/latest/download"
RELEASE_ASSET_FETCH = re.compile(r"\$base/([A-Za-z0-9._\-]+)")
RELEASE_ASSET_DECL = re.compile(r"INSTALL_ASSETS=\(\s*(.*?)\)", re.S)
RELEASE_REPORT_DECL = re.compile(r"REPORT_ASSETS=\(\s*(.*?)\)", re.S)
RELEASE_ASSET_UNION = 'EXPECTED_ASSETS=("${INSTALL_ASSETS[@]}" "${REPORT_ASSETS[@]}")'
INSTALL_DOCS = ("README.md", "README.zh-CN.md")


def release_assets(workflow: str) -> list[str]:
    m = RELEASE_ASSET_DECL.search(workflow)
    return sorted(m.group(1).split()) if m else []


def release_report_assets(workflow: str) -> list[str]:
    m = RELEASE_REPORT_DECL.search(workflow)
    return sorted(m.group(1).split()) if m else []


def repository_contract_problems(files: dict[str, str]) -> tuple[list[str], int]:
    """Validate repository policy by Markdown structure and configuration semantics."""
    bad: list[str] = []
    seen = 0

    missing = [rel for rel in REPOSITORY_POLICY_FILES if rel not in files]
    if missing:
        return [f"{rel}: repository policy file is missing" for rel in missing], 0

    contributing_spans = inline_code_spans(files["CONTRIBUTING.md"])
    for literal, name in (
        ("./bin/dawn fmt compiler-plan std site selfhost packages examples --check",
         "complete formatter scope"),
        ("docs/history/m<N>-progress.md", "milestone progress path"),
        ("docs/history/m<N>-retro.md", "milestone retro path"),
    ):
        if literal not in contributing_spans:
            bad.append(f"CONTRIBUTING.md: missing active inline-code policy {name!r}")
        else:
            seen += 1

    workflow = files[".github/workflows/release.yml"]
    published = release_assets(workflow)
    reports = release_report_assets(workflow)
    if not published:
        bad.append(".github/workflows/release.yml: no INSTALL_ASSETS list to "
                   "check the install instructions against")
    else:
        for rel in INSTALL_DOCS:
            text = files[rel]
            if RELEASE_ASSET_BASE not in text:
                bad.append(f"{rel}: install instructions do not point at "
                           f"{RELEASE_ASSET_BASE}")
                continue
            fetched = sorted(set(RELEASE_ASSET_FETCH.findall(text)))
            if fetched != published:
                bad.append(f"{rel}: install instructions fetch {fetched}, but "
                           f"release.yml publishes {published}")
            else:
                seen += 1

    if not reports:
        bad.append(".github/workflows/release.yml: no REPORT_ASSETS list; the "
                   "pub-API snapshot and its diff would be published unnamed")
    elif RELEASE_ASSET_UNION not in workflow:
        bad.append(".github/workflows/release.yml: EXPECTED_ASSETS is not the "
                   "two declared lists concatenated, so an asset both lists "
                   "agree on need not be uploaded at all")
    else:
        for rel in INSTALL_DOCS:
            spans = inline_code_spans(files[rel])
            unnamed = [name for name in reports if name not in spans]
            if unnamed:
                bad.append(f"{rel}: release asset(s) {unnamed} are published but "
                           f"named in no document")
            else:
                seen += 1

    editor = files[".editorconfig"]
    for sample, expected in (
        ("src/sample.dawn", "2"),
        ("config/sample.yml", "2"),
        ("config/sample.yaml", "2"),
        ("scripts/sample.py", "4"),
        ("src/Sample.java", "4"),
    ):
        got = editorconfig_value(editor, sample, "indent_size")
        if got != expected:
            bad.append(f".editorconfig: {sample} resolves indent_size={got!r}, expected {expected}")
        else:
            seen += 1

    for rel, module_pattern, line_pattern in (
        ("README.md", r"\b\d+\s+modules\b", r"\b[\d,]+\s+lines\b"),
        ("README.zh-CN.md", r"\d+\s*个模块", r"(?:[\d.]+\s*万|[\d,]+)\s*行"),
    ):
        intro = markdown_intro(files[rel])
        for pattern, name in ((module_pattern, "volatile module count"),
                              (line_pattern, "volatile line count")):
            if re.search(pattern, intro, re.I):
                bad.append(f"{rel}: active introduction contains {name}")
            else:
                seen += 1

    for rel, pattern in OUTWARD_CORPUS_COUNTS:
        if pattern.search(files[rel]):
            bad.append(f"{rel}: outward copy contains a volatile differential-corpus count")
        else:
            seen += 1

    for rel, heading in TOOLCHAIN_ARTIFACT_SECTIONS:
        section = markdown_section(files[rel], heading)
        if section is None:
            bad.append(f"{rel}: missing toolchain section {heading!r}")
        elif BINARY_SIZE_LITERAL.search(normalize_prose(section)):
            bad.append(f"{rel}: {heading} contains a volatile binary size")
        else:
            seen += 1

    package = files["docs/package-design.md"]
    lock = markdown_section(package, "4.6 `dawn.lock` schema 1 冻结 Java 依赖闭包")
    if lock is None:
        bad.append("docs/package-design.md: missing current 4.6 dawn.lock policy section")
    else:
        lock_prose = normalize_prose(lock)
        for fragment, name in (
            ("前两行是生成注释，首个非注释数据行是", "lock header shape"),
            ("只冻结 Maven/Java 依赖闭包", "lock scope"),
        ):
            if fragment not in lock_prose:
                bad.append(f"docs/package-design.md: missing current {name}")
            else:
                seen += 1
        for pattern in (r"项目 A 不做 lockfile", r"不需要 lock 也可复现"):
            if re.search(pattern, lock_prose, re.I):
                bad.append("docs/package-design.md: current lock policy restored an obsolete no-lock claim")
            else:
                seen += 1
    schema = markdown_section(package, "2. 每个文件第一行写 schema 版本")
    if schema is None or "将来的 lock" in normalize_prose(schema):
        bad.append("docs/package-design.md: schema policy still describes dawn.lock as future work")
    else:
        seen += 1

    for rel, source_heading, module_clause in (
        ("docs/spec.md", "1.1 源文件", "一个文件即一个模块（见 §10）"),
        ("docs/spec.en.md", "1.1 Source files", "One file is one module (see §10)"),
    ):
        source = markdown_section(files[rel], source_heading)
        if source is None or module_clause not in normalize_prose(source):
            bad.append(f"{rel}: source-file policy does not point at module-system §10")
        else:
            seen += 1

    for rel, declaration_heading, keyword_heading, visibility_headings, quick_heading in (
        ("docs/spec.md", "3. 声明", "1.4 关键字", ("3.3 可见性", "10.4 可见性"),
         "13. 语法速查"),
        ("docs/spec.en.md", "3. Declarations", "1.4 Keywords",
         ("3.3 Visibility", "10.4 Visibility"), "13. Syntax cheat sheet"),
    ):
        spec = files[rel]
        lead = markdown_section_lead(spec, declaration_heading)
        declared = inline_code_spans(lead or "")
        required = {"use", "type", "opaque type", "alias", "const", "fn", "test",
                    "trait", "impl", "effect"}
        if lead is None or not required.issubset(declared):
            bad.append(f"{rel}: top-level declaration inventory is incomplete")
        else:
            seen += 1
        keywords = markdown_section(spec, keyword_heading)
        if keywords is None or "opaque" not in inline_code_spans(keywords):
            bad.append(f"{rel}: contextual keyword inventory omits opaque")
        else:
            seen += 1
        for heading in visibility_headings:
            visibility = markdown_section(spec, heading)
            spans = inline_code_spans(visibility or "")
            if visibility is None or not {"pub", "trait", "effect"}.issubset(spans):
                bad.append(f"{rel}: {heading} omits pub trait/effect visibility")
            else:
                seen += 1
        quick = markdown_section(spec, quick_heading)
        dawn_fences = [body for info, body, _ in fences(quick or "") if info == "dawn"]
        quick_body = dawn_fences[0] if dawn_fences else ""
        for pattern, name in (
            (r"(?m)^pub opaque type\s+", "opaque type"),
            (r"(?m)^pub trait\s+", "pub trait"),
            (r"(?m)^impl\s+", "impl"),
            (r"(?m)^pub effect\s+", "pub effect"),
        ):
            if not re.search(pattern, quick_body):
                bad.append(f"{rel}: syntax cheat sheet omits {name}")
            else:
                seen += 1

    for rel in ("docs/spec.md", "docs/spec.en.md"):
        text = files[rel]
        marked_lines = [line for line in text.splitlines() if HISTORICAL_V01_MARKER in line]
        occurrences = [(number, line) for number, line in enumerate(text.splitlines(), 1)
                       if re.search(r"v0\.1", line, re.I)]
        if len(marked_lines) != 1 or len(occurrences) != 1 or \
                HISTORICAL_V01_MARKER not in occurrences[0][1]:
            bad.append(f"{rel}: every v0.1 occurrence must be the one explicitly marked history")
        elif re.search(r"^##\s+14\.", text, re.M):
            bad.append(f"{rel}: stale normative roadmap section returned")
        else:
            seen += 1
    return bad, seen


def check_repository_contracts() -> tuple[list[str], int]:
    files = {rel: (ROOT / rel).read_text(encoding="utf-8")
             for rel in REPOSITORY_POLICY_FILES if (ROOT / rel).exists()}
    return repository_contract_problems(files)


def check_repository_contracts_selftest() -> tuple[list[str], int]:
    files = {rel: (ROOT / rel).read_text(encoding="utf-8")
             for rel in REPOSITORY_POLICY_FILES}
    baseline, _ = repository_contract_problems(files)
    if baseline:
        return [f"repository policy self-test baseline is invalid: {baseline[0]}"], 0

    editor = dict(files)
    editor[".editorconfig"] = editor[".editorconfig"].replace(
        "[*.{dawn,yml,yaml}]\nindent_size = 2",
        "[*.{dawn,yml,yaml}]\nindent_size = 8\n# indent_size = 2",
        1,
    )
    if editor[".editorconfig"] == files[".editorconfig"]:
        return ["repository policy self-test: EditorConfig fixture was not mutated"], 0
    bad, _ = repository_contract_problems(editor)
    if not any("sample.dawn resolves indent_size='8'" in problem for problem in bad):
        return ["repository policy self-test: indent 8 plus a fake comment stayed green"], 0
    restored = dict(editor)
    restored[".editorconfig"] = restored[".editorconfig"].replace(
        "indent_size = 8\n# indent_size = 2",
        "indent_size = 2\n# indent_size = 2",
        1,
    )
    bad, _ = repository_contract_problems(restored)
    if bad:
        return [f"repository policy self-test: restoring the real indent stayed red: {bad[0]}"], 0

    renamed = dict(files)
    renamed[".github/workflows/release.yml"] = \
        renamed[".github/workflows/release.yml"].replace(
            "dawnc-linux-x86_64", "dawnc-linux-amd64")
    if renamed[".github/workflows/release.yml"] == files[".github/workflows/release.yml"]:
        return ["repository policy self-test: release asset fixture was not mutated"], 0
    bad, _ = repository_contract_problems(renamed)
    if not any("install instructions fetch" in problem for problem in bad):
        return ["repository policy self-test: renaming a release asset left the "
                "install instructions green"], 0

    dropped = dict(files)
    dropped["README.md"] = dropped["README.md"].replace(
        "curl -fsSLO $base/dawn-selfhost.jar.sha256\n", "", 1)
    if dropped["README.md"] == files["README.md"]:
        return ["repository policy self-test: install fixture was not mutated"], 0
    bad, _ = repository_contract_problems(dropped)
    if not any("install instructions fetch" in problem for problem in bad):
        return ["repository policy self-test: dropping a checksum download from "
                "the install instructions stayed green"], 0

    report_renamed = dict(files)
    report_renamed[".github/workflows/release.yml"] = \
        report_renamed[".github/workflows/release.yml"].replace(
            "dawn-pub-api-diff.md", "dawn-api-report.md")
    if report_renamed[".github/workflows/release.yml"] == \
            files[".github/workflows/release.yml"]:
        return ["repository policy self-test: report asset fixture was not mutated"], 0
    bad, _ = repository_contract_problems(report_renamed)
    if not any("named in no document" in problem for problem in bad):
        return ["repository policy self-test: renaming a report asset left the "
                "documents that name it green"], 0

    union_broken = dict(files)
    union_broken[".github/workflows/release.yml"] = \
        union_broken[".github/workflows/release.yml"].replace(
            RELEASE_ASSET_UNION, 'EXPECTED_ASSETS=("${INSTALL_ASSETS[@]}")')
    if union_broken[".github/workflows/release.yml"] == \
            files[".github/workflows/release.yml"]:
        return ["repository policy self-test: asset union fixture was not mutated"], 0
    bad, _ = repository_contract_problems(union_broken)
    if not any("two declared lists concatenated" in problem for problem in bad):
        return ["repository policy self-test: publishing only the install list "
                "while both lists stayed correct went unnoticed"], 0

    reports_gone = dict(files)
    reports_gone[".github/workflows/release.yml"] = \
        RELEASE_REPORT_DECL.sub("REMOVED=()", reports_gone[".github/workflows/release.yml"])
    bad, _ = repository_contract_problems(reports_gone)
    if not any("no REPORT_ASSETS list" in problem for problem in bad):
        return ["repository policy self-test: a release with no declared report "
                "assets stayed green"], 0

    comment = dict(files)
    command = "./bin/dawn fmt compiler-plan std site selfhost packages examples --check"
    comment["CONTRIBUTING.md"] = comment["CONTRIBUTING.md"].replace(
        command, "./bin/dawn fmt std site selfhost packages examples --check", 1)
    comment["CONTRIBUTING.md"] += f"\n<!-- `{command}` -->\n"
    bad, _ = repository_contract_problems(comment)
    if not any("complete formatter scope" in problem for problem in bad):
        return ["repository policy self-test: an HTML comment satisfied formatter scope"], 0

    fenced = dict(files)
    fact = "前两行是生成注释，首个非注释数据行是"
    fenced["docs/package-design.md"] = fenced["docs/package-design.md"].replace(
        fact, "文件第一行就是", 1)
    fenced["docs/package-design.md"] += f"\n```text\n{fact}\n```\n"
    bad, _ = repository_contract_problems(fenced)
    if not any("lock header shape" in problem for problem in bad):
        return ["repository policy self-test: a fenced example satisfied lock policy"], 0

    active_readme = dict(files)
    active_readme["README.md"] = active_readme["README.md"].replace(
        "# Dawn\n", "# Dawn\n\nThe compiler has 10 modules and 3,300 lines.\n", 1)
    bad, _ = repository_contract_problems(active_readme)
    if not any("active introduction contains volatile" in problem for problem in bad):
        return ["repository policy self-test: a volatile metric in the active intro stayed green"], 0

    corpus_count = dict(files)
    corpus_count["README.md"] += "\n59 corpus programs are compiled on both backends.\n"
    bad, _ = repository_contract_problems(corpus_count)
    if not any("volatile differential-corpus count" in problem for problem in bad):
        return ["repository policy self-test: a volatile corpus count stayed green"], 0

    binary_size = dict(files)
    toolchain_heading = "The road without a JVM"
    toolchain_section = markdown_section(binary_size["README.md"], toolchain_heading)
    if toolchain_section is None:
        return ["repository policy self-test: binary-size section fixture is absent"], 0
    changed = toolchain_section + "\nThe native compiler is about 3.6 MB.\n"
    binary_size["README.md"] = binary_size["README.md"].replace(
        toolchain_section, changed, 1)
    bad, _ = repository_contract_problems(binary_size)
    if not any("volatile binary size" in problem for problem in bad):
        return ["repository policy self-test: a volatile binary size stayed green"], 0

    active_lock = dict(files)
    lock_heading = "4.6 `dawn.lock` schema 1 冻结 Java 依赖闭包"
    lock_section = markdown_section(active_lock["docs/package-design.md"], lock_heading)
    if lock_section is None:
        return ["repository policy self-test: current lock section fixture is absent"], 0
    changed = lock_section + "\n项目 A 不做 lockfile。\n"
    active_lock["docs/package-design.md"] = active_lock["docs/package-design.md"].replace(
        lock_section, changed, 1)
    bad, _ = repository_contract_problems(active_lock)
    if not any("obsolete no-lock claim" in problem for problem in bad):
        return ["repository policy self-test: a no-lock claim in active policy stayed green"], 0

    active_v01 = dict(files)
    active_v01["docs/spec.md"] = active_v01["docs/spec.md"].replace(
        "本文是语法与语义的权威定义。", "active v0.1 roadmap。\n\n本文是语法与语义的权威定义。", 1)
    bad, _ = repository_contract_problems(active_v01)
    if not any("explicitly marked history" in problem for problem in bad):
        return ["repository policy self-test: an unmarked active v0.1 claim stayed green"], 0

    historical = dict(files)
    for rel in ("docs/spec.md", "docs/spec.en.md"):
        historical[rel] = historical[rel].replace(
            HISTORICAL_V01_MARKER,
            "historical denial: the roadmap is retired; " + HISTORICAL_V01_MARKER,
            1,
        )
    history_heading = "落地记录：项目 B v1（2026-07-22）"
    history_section = markdown_section(historical["docs/package-design.md"], history_heading)
    if history_section is None:
        return ["repository policy self-test: package history section fixture is absent"], 0
    changed = "\n历史否定：项目 A 不做 lockfile 是旧方案。\n" + history_section
    historical["docs/package-design.md"] = historical["docs/package-design.md"].replace(
        history_section, changed, 1)
    bad, _ = repository_contract_problems(historical)
    if bad:
        return [f"repository policy self-test: scoped historical prose was rejected: {bad[0]}"], 0
    return [], 12


def read_audit_details() -> dict[str, str]:
    return {rel: (ROOT / rel).read_text(encoding="utf-8")
            for _prefix, rel in AUDIT_DETAIL_FILES}


def expected_audit_universe(prefix_totals: dict[str, int]) -> set[str]:
    """Build the contiguous ID universe owned by one audit layer."""
    return {f"{prefix}-{number:02d}"
            for prefix, maximum in prefix_totals.items()
            for number in range(1, maximum + 1)}


def audit_detail_universe(detail_texts: dict[str, str]) -> tuple[set[str], list[str]]:
    """Derive the finding universe from the six detailed audit heading sets."""
    universe: set[str] = set()
    owners: dict[str, str] = {}
    bad: list[str] = []
    for expected_prefix, rel in AUDIT_DETAIL_FILES:
        text = detail_texts.get(rel)
        if text is None:
            bad.append(f"audit detail {rel} is missing")
            continue
        family_count = 0
        for prefix, number in AUDIT_DETAIL_HEADING.findall(text):
            audit_id = f"{prefix}-{number}"
            if prefix != expected_prefix:
                bad.append(f"audit detail {rel} contains wrong-family heading {audit_id}")
                continue
            family_count += 1
            if audit_id in owners:
                bad.append(f"audit finding {audit_id} is duplicated in {owners[audit_id]} and {rel}")
                continue
            owners[audit_id] = rel
            universe.add(audit_id)
        expected_total = AUDIT_CURRENT_PREFIX_TOTALS[expected_prefix]
        if family_count != expected_total:
            bad.append(f"audit detail {rel} contains {family_count} {expected_prefix} headings, "
                       f"expected current total {expected_total}")
    if len(universe) != AUDIT_CURRENT_TOTAL:
        bad.append(f"audit details contain {len(universe)} unique finding IDs, "
                   f"expected {AUDIT_CURRENT_TOTAL}")
    return universe, bad


def audit_p1_universe(detail_texts: dict[str, str]) -> tuple[set[str], list[str]]:
    """Derive the frozen P1 set from detail-heading severities, not the index."""
    p1_ids: set[str] = set()
    bad: list[str] = []
    for _expected_prefix, rel in AUDIT_DETAIL_FILES:
        text = detail_texts.get(rel)
        if text is None:
            continue
        for prefix, number in AUDIT_P1_DETAIL_HEADING.findall(text):
            audit_id = f"{prefix}-{number}"
            if audit_id in p1_ids:
                bad.append(f"frozen P1 detail heading {audit_id} is duplicated")
            p1_ids.add(audit_id)
    if len(p1_ids) != 29:
        bad.append(f"audit details contain {len(p1_ids)} P1 headings, expected frozen 29")
    return p1_ids, bad


def audit_status_blocks(text: str, status_pattern: re.Pattern,
                        state_order: tuple[str, ...],
                        layer: str) -> tuple[dict[str, tuple[int, int, str]], list[str]]:
    """Return each state block through its last list line, before explanatory prose."""
    matches = list(status_pattern.finditer(text))
    bad: list[str] = []
    if [match.group(1) for match in matches] != list(state_order):
        return {}, [f"{layer} status headings must appear once in "
                    f"{'/'.join(state_order)} order"]
    blocks: dict[str, tuple[int, int, str]] = {}
    for index, match in enumerate(matches):
        limit = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        tail = text[match.end():limit]
        offset = 0
        seen_list = False
        end = len(tail)
        for line in tail.splitlines(keepends=True):
            stripped = line.rstrip("\r\n")
            if stripped.startswith("- "):
                seen_list = True
            elif seen_list and stripped and not stripped.startswith("  "):
                end = offset
                break
            offset += len(line)
        if not seen_list:
            bad.append(f"{layer} status {match.group(1)} has no ID list")
        body_end = match.end() + end
        blocks[match.group(1)] = (match.start(), body_end, text[match.end():body_end])
    return blocks, bad


def expand_audit_ids(body: str,
                     prefix_totals: dict[str, int]) -> tuple[set[str], list[str]]:
    ids: set[str] = set()
    bad: list[str] = []
    for prefix, number in AUDIT_ANY_ID.findall(body):
        if prefix not in prefix_totals:
            bad.append(f"unknown audit ID family {prefix}-{number}")
    for match in AUDIT_ID_RANGE.finditer(body):
        prefix, start_text, end_prefix, end_text = match.groups()
        if end_prefix and end_prefix != prefix:
            bad.append(f"cross-family audit range {match.group(0)}")
            continue
        start = int(start_text)
        end = start if end_text is None else int(end_text)
        if start > end:
            bad.append(f"descending audit range {match.group(0)}")
            continue
        maximum = prefix_totals[prefix]
        if start < 1 or end > maximum:
            bad.append(f"out-of-range audit ID {match.group(0)}")
            continue
        for number in range(start, end + 1):
            audit_id = f"{prefix}-{number:02d}"
            if audit_id in ids:
                bad.append(f"duplicate audit ID {audit_id} inside one status")
            ids.add(audit_id)
    return ids, bad


def parse_audit_state(text: str, status_pattern: re.Pattern,
                      state_order: tuple[str, ...],
                      layer: str,
                      prefix_totals: dict[str, int]) -> tuple[dict[str, set[str]], dict[str, int], list[str]]:
    blocks, bad = audit_status_blocks(text, status_pattern, state_order, layer)
    states: dict[str, set[str]] = {}
    headings = {name: int(value) for name, value in status_pattern.findall(text)}
    for name in state_order:
        if name not in blocks:
            states[name] = set()
            continue
        ids, problems = expand_audit_ids(blocks[name][2], prefix_totals)
        states[name] = ids
        bad += [f"{name}: {problem}" for problem in problems]
    return states, headings, bad


def audit_partition_problems(text: str, universe: set[str],
                             status_pattern: re.Pattern,
                             state_order: tuple[str, ...],
                             self_check_pattern: re.Pattern,
                             layer: str, expected_total: int,
                             topic_totals: tuple[tuple[str, int], ...],
                             prefix_totals: dict[str, int]) -> tuple[dict[str, set[str]], list[str]]:
    """Validate one historical or current layer as an exact finding partition."""
    states, headings, bad = parse_audit_state(
        text, status_pattern, state_order, layer, prefix_totals)
    if set(headings) != set(state_order):
        bad.append(f"{layer} status layer must contain one "
                   f"{'/'.join(state_order)} heading")
        return states, bad

    owner: dict[str, str] = {}
    for status in state_order:
        ids = states[status]
        if len(ids) != headings[status]:
            bad.append(f"{layer} status {status} heading says {headings[status]}, "
                       f"but its ID list contains {len(ids)}")
        for audit_id in ids:
            if audit_id in owner:
                bad.append(f"{layer} audit ID {audit_id} appears in both "
                           f"{owner[audit_id]} and {status}")
            else:
                owner[audit_id] = status
    actual = set(owner)
    missing = sorted(universe - actual)
    extra = sorted(actual - universe)
    if missing:
        bad.append(f"{layer} status layer omits {', '.join(missing)}")
    if extra:
        bad.append(f"{layer} status layer contains invalid IDs {', '.join(extra)}")
    if len(actual) != len(universe):
        bad.append(f"{layer} status layer contains {len(actual)} unique IDs, "
                   f"but details define {len(universe)}")

    checks = self_check_pattern.findall(text)
    if len(checks) != 1:
        bad.append(f"{layer} status layer must contain one machine-readable count self-check")
    else:
        values = tuple(map(int, checks[0]))
        stated = dict(zip(state_order, values[:-1]))
        total = values[-1]
        if stated != headings:
            bad.append(f"{layer} self-check {stated} disagrees with "
                       f"status headings {headings}")
        if sum(values[:-1]) != total or total != expected_total:
            bad.append(f"{layer} status counts must add up to "
                       f"{expected_total} findings")

    for topic, expected_topic_total in topic_totals:
        prefix = AUDIT_TOPIC_PREFIX[topic]
        actual_counts = tuple(sum(1 for audit_id in states[status]
                                  if audit_id.startswith(prefix + "-"))
                              for status in state_order)
        groups = "/".join(r"(\d+)" for _status in state_order)
        pattern = re.compile(re.escape(topic) + r" \*\*" + groups + r"\*\*")
        matches = pattern.findall(text)
        if len(matches) != 1:
            bad.append(f"{layer} audit topic {topic} must have one "
                       f"{'/'.join(state_order)} tuple")
            continue
        stated_counts = tuple(map(int, matches[0]))
        if stated_counts != actual_counts:
            bad.append(f"{layer} audit topic {topic} says {stated_counts}, "
                       f"ID lists say {actual_counts}")
        if sum(actual_counts) != expected_topic_total:
            bad.append(f"{layer} audit topic {topic} must cover "
                       f"{expected_topic_total} findings")
    return states, bad


def audit_p1_mapping_problems(text: str, current_states: dict[str, set[str]],
                              detail_texts: dict[str, str]) -> list[str]:
    """The frozen P1 index and its current mapping remain a checked bijection."""
    bad: list[str] = []
    p1_universe, p1_bad = audit_p1_universe(detail_texts)
    bad += p1_bad
    frozen_header, frozen_rows, problems = markdown_table(text, "5. 全部 P1 索引")
    bad += [f"frozen P1 index: {problem}" for problem in problems]
    if frozen_header and frozen_header != ("ID", "摘要", "专题"):
        bad.append(f"frozen P1 index has columns {frozen_header}, expected ID/摘要/专题")
    frozen_ids = audit_table_ids(frozen_rows, "frozen P1 index", bad)
    if len(frozen_rows) != 29:
        bad.append(f"frozen P1 index has {len(frozen_rows)} rows, expected 29")
    if frozen_ids != p1_universe:
        missing = sorted(p1_universe - frozen_ids)
        extra = sorted(frozen_ids - p1_universe)
        if missing:
            bad.append(f"frozen P1 index omits {', '.join(missing)}")
        if extra:
            bad.append(f"frozen P1 index contains non-P1 IDs {', '.join(extra)}")

    mapping_heading = "5.1 冻结 P1 的当前逐项映射"
    mapping_header, mapping_rows, problems = markdown_table(text, mapping_heading)
    bad += [f"current P1 mapping: {problem}" for problem in problems]
    if mapping_header and mapping_header != ("ID", "当前状态", "复核结果"):
        bad.append(f"current P1 mapping has columns {mapping_header}, "
                   "expected ID/当前状态/复核结果")
    mapping_ids = audit_table_ids(mapping_rows, "current P1 mapping", bad)
    if len(mapping_rows) != 29:
        bad.append(f"current P1 mapping has {len(mapping_rows)} rows, expected 29")
    if mapping_ids != frozen_ids:
        missing = sorted(frozen_ids - mapping_ids)
        extra = sorted(mapping_ids - frozen_ids)
        if missing:
            bad.append(f"current P1 mapping omits {', '.join(missing)}")
        if extra:
            bad.append(f"current P1 mapping contains non-frozen IDs {', '.join(extra)}")

    owner = {audit_id: status for status, ids in current_states.items()
             for audit_id in ids}
    mapping_counts = {status: 0 for status in CURRENT_AUDIT_STATES}
    for row in mapping_rows:
        audit_id = parse_audit_table_id(row[0])
        status = row[1].strip()
        if status not in CURRENT_AUDIT_STATES:
            bad.append(f"current P1 mapping {audit_id or row[0]} has unknown state {status!r}")
            continue
        mapping_counts[status] += 1
        if audit_id in owner and owner[audit_id] != status:
            bad.append(f"current P1 mapping {audit_id} says {status}, "
                       f"current registry says {owner[audit_id]}")

    mapping_section = markdown_section(text, mapping_heading)
    checks = [] if mapping_section is None else AUDIT_P1_SELF_CHECK.findall(mapping_section)
    if len(checks) != 1:
        bad.append("current P1 mapping must contain one machine-readable count self-check")
    else:
        values = tuple(map(int, checks[0]))
        stated = dict(zip(CURRENT_AUDIT_STATES, values[:-1]))
        if stated != mapping_counts:
            bad.append(f"current P1 self-check {stated} disagrees with rows {mapping_counts}")
        if sum(values[:-1]) != values[-1] or values[-1] != 29:
            bad.append("current P1 counts must add up to the frozen 29 rows")
    return bad


def parse_audit_table_id(cell: str) -> str | None:
    match = re.fullmatch(r"`([A-Z]+-\d{2})`", cell.strip())
    return None if match is None else match.group(1)


def audit_table_ids(rows: list[tuple[str, ...]], label: str,
                    bad: list[str]) -> set[str]:
    ids: set[str] = set()
    for row in rows:
        audit_id = parse_audit_table_id(row[0])
        if audit_id is None:
            bad.append(f"{label} has invalid ID cell {row[0]!r}")
            continue
        if audit_id in ids:
            bad.append(f"{label} duplicates {audit_id}")
        ids.add(audit_id)
    return ids


def audit_status_problems(text: str,
                          detail_texts: dict[str, str] | None = None) -> list[str]:
    """Validate historical evidence and the machine-authoritative current registry."""
    details = read_audit_details() if detail_texts is None else detail_texts
    current_universe, bad = audit_detail_universe(details)
    frozen_universe = expected_audit_universe(AUDIT_FROZEN_PREFIX_TOTALS)

    historical = markdown_section(text, HISTORICAL_AUDIT_HEADING)
    if historical is None:
        bad.append("historical audit status section is missing")
    else:
        _historical_states, problems = audit_partition_problems(
            historical, frozen_universe, HISTORICAL_AUDIT_STATUS,
            HISTORICAL_AUDIT_STATES, HISTORICAL_AUDIT_SELF_CHECK, "historical",
            AUDIT_FROZEN_TOTAL, AUDIT_FROZEN_TOPIC_TOTALS,
            AUDIT_FROZEN_PREFIX_TOTALS)
        bad += problems

    current = markdown_section(text, CURRENT_AUDIT_HEADING)
    current_states = {status: set() for status in CURRENT_AUDIT_STATES}
    if current is None:
        bad.append("machine-authoritative current audit status section is missing")
    else:
        current_states, problems = audit_partition_problems(
            current, current_universe, CURRENT_AUDIT_STATUS, CURRENT_AUDIT_STATES,
            CURRENT_AUDIT_SELF_CHECK, "current", AUDIT_CURRENT_TOTAL,
            AUDIT_CURRENT_TOPIC_TOTALS, AUDIT_CURRENT_PREFIX_TOTALS)
        bad += problems
    bad += audit_p1_mapping_problems(text, current_states, details)
    return bad


def check_audit_status() -> tuple[list[str], int]:
    path = ROOT / "docs/codebase-audit-v2.md"
    text = path.read_text(encoding="utf-8")
    bad = [f"{path.relative_to(ROOT)}: {problem}"
           for problem in audit_status_problems(text, read_audit_details())]
    return bad, 0 if bad else 3


def audit_index_status_problems(index_texts: dict[str, str] | None = None) -> list[str]:
    """Audit indexes navigate material; they never mirror design-task progress."""
    texts = ({rel: (ROOT / rel).read_text(encoding="utf-8")
              for rel, _heading, _columns in AUDIT_INDEX_TABLES}
             if index_texts is None else index_texts)
    bad: list[str] = []
    forbidden_columns = {"状态", "任务状态", "进度", "任务进度"}
    for rel, heading, expected_columns in AUDIT_INDEX_TABLES:
        text = texts.get(rel)
        if text is None:
            bad.append(f"audit index {rel} is missing")
            continue
        columns, rows, problems = markdown_table(text, heading)
        bad += [f"{rel}: {problem}" for problem in problems]
        copied = forbidden_columns.intersection(columns)
        if copied:
            bad.append(f"{rel}: audit material table copies task-status column(s) "
                       f"{', '.join(sorted(copied))}")
        if columns and columns != expected_columns:
            bad.append(f"{rel}: audit material table has columns {columns}, "
                       f"expected {expected_columns}")
        for row_number, row in enumerate(rows, 1):
            for cell in row:
                if INDEX_TASK_STATUS.search(normalize_active_markdown(cell)):
                    bad.append(f"{rel}: audit material table row {row_number} "
                               f"copies task status in cell {cell!r}")
    return bad


def check_audit_indexes() -> tuple[list[str], int]:
    bad = audit_index_status_problems()
    return bad, 0 if bad else len(AUDIT_INDEX_TABLES)


# The registry above is an exact partition, and an exact partition of the wrong
# statuses is still wrong. `SEM-07` and `TOOL-13` sat at `open` for days after
# both were implemented and shipped, and every check in this file was green the
# whole time: the partition was exact, the counts added up, the topic matrix
# agreed. Nothing read the tree, so nothing could tell.
#
# The fix is the shape `check_named_effect_status` already uses here: state the
# claim, derive the fact from the tree, and fail in both directions. A finding
# carries one anchor, which names a file and a literal and says which way that
# literal reads *while the finding is open*:
#
#   <!-- audit-anchor: present <path> | <literal> -->
#       the code the finding describes; the fix deletes or rewrites it
#   <!-- audit-anchor: absent <path> | <literal> -->
#       the code the finding asks for; the fix creates it
#
# The status then decides which way it must read now:
#
#   open, partial  the condition holds. It stops holding when the fix lands,
#                  and the finding is named as the thing to re-judge.
#   fixed          the condition is inverted. It goes back when the fix is
#                  reverted or refactored away, and the finding is named again.
#   retracted      no anchor at all: nothing was implemented, so there is
#                  nothing for one to point at.
#
# So the anchor is written once, when the finding is recorded, and never
# maintained: what moves is the tree, and the pair (status, tree) is what is
# checked. That is deliberate -- hand-maintained metadata is what rotted here,
# and a scheme that needed somebody to remember to update it would be the same
# defect one level up.
#
# The literal is drawn from the finding's own text: `present` anchors quote the
# evidence, `absent` anchors quote the name the recommendation asks for. That
# rule is what keeps an anchor from drifting into an unrelated file that
# happens to be stable.
#
# What this does not promise: an anchor can be vacuous. `absent` fails silent
# if the fix arrives under a different name, and the check cannot know that.
# Under-claiming is the tolerable direction -- a false red gets a gate
# disabled, and a gate nobody trusts protects nothing -- so the rules refuse to
# guess, and the residue is that a fix can still land unnoticed if it renames
# what the finding asked for. Only the anchored half of the registry is
# covered: `fixed` findings recorded before this existed carry no anchor, and
# for those the check has nothing to say.
AUDIT_ANCHOR = re.compile(
    r"<!--\s*audit-anchor:\s*(present|absent)\s+(\S+)\s*\|\s*(.+?)\s*-->")
AUDIT_ANCHOR_STATES = ("open", "partial", "fixed", "retracted")
AUDIT_ANCHOR_MIN_LITERAL = 4


def audit_detail_entries(detail_texts: dict[str, str]) -> dict[str, str]:
    """Each finding's section of its detail document, keyed by ID."""
    entries: dict[str, str] = {}
    for _prefix, rel in AUDIT_DETAIL_FILES:
        text = detail_texts.get(rel)
        if text is None:
            continue
        for match in re.finditer(r"^## ([A-Z]+-\d{2})\b.*?(?=^## |\Z)",
                                 text, re.S | re.M):
            entries[match.group(1)] = match.group(0)
    return entries


def audit_anchor_problems(detail_texts: dict[str, str],
                          states: dict[str, set[str]],
                          sources: dict[str, str]) -> tuple[list[str], int]:
    """Cross-check every anchored finding's status against the tree.

    `sources` is the tree the anchors are read against, as path -> text. It is
    a parameter so the self-test below can hand this function a tree with one
    thing changed; nothing else in the check knows where the tree came from."""
    entries = audit_detail_entries(detail_texts)
    owner = {audit_id: status for status, ids in states.items()
             for audit_id in ids}
    bad: list[str] = []
    resolved = 0
    for audit_id in sorted(entries):
        status = owner.get(audit_id)
        if status is None:
            continue
        anchors = AUDIT_ANCHOR.findall(entries[audit_id])
        if len(anchors) > 1:
            bad.append(f"{audit_id}: carries {len(anchors)} audit-anchors; one "
                       f"finding has one, or its status answers to two trees "
                       f"[anchor_one]")
            continue
        if not anchors:
            if status in ("open", "partial"):
                bad.append(f"{audit_id} is {status} and carries no audit-anchor. "
                           f"Name the file and literal its status depends on, so "
                           f"the tree can contradict it [anchor_required]")
            continue
        if status == "retracted":
            bad.append(f"{audit_id} is retracted and carries an audit-anchor. A "
                       f"retraction says the original finding was not a defect, "
                       f"so nothing was implemented for an anchor to point at "
                       f"[anchor_forbidden]")
            continue
        kind, rel, literal = anchors[0]
        if len(literal) < AUDIT_ANCHOR_MIN_LITERAL:
            bad.append(f"{audit_id}: audit-anchor literal {literal!r} is shorter "
                       f"than {AUDIT_ANCHOR_MIN_LITERAL} characters, which is "
                       f"short enough to match by accident "
                       f"[anchor_literal_nonvacuous]")
            continue
        text = sources.get(rel)
        if text is None:
            bad.append(f"{audit_id}: audit-anchor names {rel}, which is not a "
                       f"file in this repository. A status backed by a pointer "
                       f"that does not resolve is a status nothing checks "
                       f"[anchor_path_resolves]")
            continue
        resolved += 1
        found = literal in text
        holds = found if kind == "present" else not found
        if status in ("open", "partial") and not holds:
            was = "is gone from" if kind == "present" else "has arrived in"
            bad.append(f"{audit_id} is {status}, but `{literal}` {was} {rel}. "
                       f"The code the finding describes has moved; re-judge the "
                       f"finding rather than the anchor [open_still_true]")
        elif status == "fixed" and holds:
            still = "is still in" if kind == "present" else "is still missing from"
            bad.append(f"{audit_id} is fixed, but `{literal}` {still} {rel}. The "
                       f"fix this status claims is not in the tree "
                       f"[fixed_took_effect]")
    return bad, resolved


def read_audit_anchor_sources(detail_texts: dict[str, str]) -> dict[str, str]:
    """Read exactly the files the anchors name, and nothing else.

    Scope is the point: an anchor's literal is looked for in one named file, so
    the same words written in prose -- in this very registry, or in a design
    document that quotes the code -- cannot satisfy or break it."""
    sources: dict[str, str] = {}
    for entry in audit_detail_entries(detail_texts).values():
        for _kind, rel, _literal in AUDIT_ANCHOR.findall(entry):
            if rel in sources:
                continue
            path = ROOT / rel
            if path.is_file():
                sources[rel] = path.read_text(encoding="utf-8")
    return sources


def check_audit_anchors() -> tuple[list[str], int]:
    path = ROOT / "docs/codebase-audit-v2.md"
    text = path.read_text(encoding="utf-8")
    details = read_audit_details()
    current = markdown_section(text, CURRENT_AUDIT_HEADING)
    if current is None:
        return [f"{path.relative_to(ROOT)}: machine-authoritative current audit "
                f"status section is missing"], 0
    states, _headings, problems = parse_audit_state(
        current, CURRENT_AUDIT_STATUS, CURRENT_AUDIT_STATES, "current",
        AUDIT_CURRENT_PREFIX_TOTALS)
    if problems:
        return [], 0
    bad, resolved = audit_anchor_problems(
        details, states, read_audit_anchor_sources(details))
    return [f"docs/codebase-audit-v2/: {problem}" for problem in bad], resolved


# Which mutant reddens which assertion, and which one owns it. The `owner`
# column is the whole point: a mutant that reddens two assertions proves
# neither, so each one below names the single assertion that is allowed to see
# it, and the self-test fails if a mutant reddens something else as well. This
# copies the discipline in scripts/gate-map/mutants.txt.
#
# `an-open-finding-whose-code-was-fixed` is the event this whole section exists
# for, replayed on a probe rather than remembered. It happened eight times at
# once: with the anchors written and the registry as it stood, the check named
# `SEM-07`, `TOOL-13`, `LIB-08`, `LIB-10`, `LIB-12`, `LIB-14`, `LIB-15` and
# `LIB-17` as statuses the tree contradicted, and every other check in this
# file was green on that same tree.
#
# `prose-that-quotes-a-literal` is the control. Nothing owns it and nothing may
# redden it: it is the sentence the whole scheme depends on -- that an anchor
# reads one named file rather than the repository, so writing the code out in
# the audit document does not answer the question the anchor asks.
AUDIT_ANCHOR_MUTANTS = (
    ("an-open-finding-whose-code-was-fixed", "open_still_true"),
    ("a-fixed-finding-whose-fix-is-gone", "fixed_took_effect"),
    ("an-open-finding-with-no-anchor", "anchor_required"),
    ("a-retracted-finding-with-an-anchor", "anchor_forbidden"),
    ("an-anchor-naming-a-path-that-is-gone", "anchor_path_resolves"),
    ("an-anchor-on-a-literal-too-short-to-mean-anything",
     "anchor_literal_nonvacuous"),
    ("a-second-anchor-on-one-finding", "anchor_one"),
    ("prose-that-quotes-a-literal", None),
)


def audit_anchor_mutant(name: str, details: dict[str, str],
                        states: dict[str, set[str]],
                        sources: dict[str, str]) -> tuple:
    """Apply one mutation to an otherwise valid registry/tree pair."""
    details = dict(details)
    states = {status: set(ids) for status, ids in states.items()}
    sources = dict(sources)
    rel = "docs/codebase-audit-v2/02-types-effects-and-semantics.md"
    probe = "\n## SEM-99 — P2 — self-test probe\n\n" \
            "<!-- audit-anchor: absent std/cursor.dawn | dawn_selftest_probe -->\n"
    if name == "an-open-finding-whose-code-was-fixed":
        details[rel] += probe
        states["open"].add("SEM-99")
        sources["std/cursor.dawn"] += "\nfn dawn_selftest_probe() = 1\n"
    elif name == "a-fixed-finding-whose-fix-is-gone":
        details[rel] += probe
        states["fixed"].add("SEM-99")
    elif name == "an-open-finding-with-no-anchor":
        details[rel] += "\n## SEM-99 — P2 — self-test probe\n\nno anchor here.\n"
        states["open"].add("SEM-99")
    elif name == "a-retracted-finding-with-an-anchor":
        details[rel] += probe
        states["retracted"].add("SEM-99")
    elif name == "an-anchor-naming-a-path-that-is-gone":
        details[rel] += "\n## SEM-99 — P2 — self-test probe\n\n" \
                        "<!-- audit-anchor: absent std/deleted.dawn | probe -->\n"
        states["open"].add("SEM-99")
    elif name == "an-anchor-on-a-literal-too-short-to-mean-anything":
        details[rel] += "\n## SEM-99 — P2 — self-test probe\n\n" \
                        "<!-- audit-anchor: present std/cursor.dawn | fn -->\n"
        states["open"].add("SEM-99")
    elif name == "a-second-anchor-on-one-finding":
        details[rel] += probe.rstrip("\n") + \
            "\n<!-- audit-anchor: present std/cursor.dawn | Cursor -->\n"
        states["open"].add("SEM-99")
    elif name == "prose-that-quotes-a-literal":
        details[rel] += probe
        states["open"].add("SEM-99")
        details[rel] += "\nThe fix would add `dawn_selftest_probe` to the cursor.\n"
    else:
        raise AssertionError(f"unknown mutant {name}")
    return details, states, sources


def check_audit_anchors_selftest() -> tuple[list[str], int]:
    text = (ROOT / "docs/codebase-audit-v2.md").read_text(encoding="utf-8")
    details = read_audit_details()
    current = markdown_section(text, CURRENT_AUDIT_HEADING)
    if current is None:
        return ["audit-anchor self-test: current status section is missing"], 0
    states, _headings, problems = parse_audit_state(
        current, CURRENT_AUDIT_STATUS, CURRENT_AUDIT_STATES, "current",
        AUDIT_CURRENT_PREFIX_TOTALS)
    if problems:
        return ["audit-anchor self-test: current status layer does not parse"], 0
    sources = read_audit_anchor_sources(details)
    baseline, resolved = audit_anchor_problems(details, states, sources)
    if baseline:
        return [f"audit-anchor self-test baseline is invalid: {baseline[0]}"], 0
    if not resolved:
        return ["audit-anchor self-test: no anchor resolved, so every mutant "
                "below would pass for the wrong reason"], 0
    for name, expected in AUDIT_ANCHOR_MUTANTS:
        bad, _ = audit_anchor_problems(
            *audit_anchor_mutant(name, details, states, sources))
        seen = {label for problem in bad
                for label in re.findall(r"\[(\w+)\]", problem)}
        if expected is None:
            if bad:
                return [f"audit-anchor self-test: control mutant {name} reddened "
                        f"{sorted(seen)}; it must redden nothing"], 0
            continue
        if seen != {expected}:
            return [f"audit-anchor self-test: mutant {name} reddened "
                    f"{sorted(seen) or 'nothing'}, expected exactly "
                    f"[{expected}]"], 0
    return [], len(AUDIT_ANCHOR_MUTANTS)


# docs/README.md opens by saying that a document's authoritative lifecycle is in
# its own header and that the index only helps you find things. Then it prints a
# lifecycle for every document in a column, and nothing compared the two. That is
# the same defect as the audit registry one screen up: a claim about state, kept
# by hand, in a second place.
#
# So the column is derived, in both directions. Where a document's status line
# names one of the four lifecycles, the index cell must be that word: a document
# retired to `historical` reds the index until the index follows, and an index
# cell edited away from the header reds too.
#
# Six documents state progress instead of a lifecycle ("done", "七刀已结",
# "设计已定"), which is a sentence a reader wants and not a lifecycle a machine
# can read. Rather than rewrite six headers to fit a checker, they are recorded
# below with the reason, and the record is itself checked both ways: a seventh
# document that stops naming its lifecycle cannot arrive quietly, and a line
# here cannot outlive the header that earned it. This is the ratchet in
# scripts/gate-map/unseen.txt, at one tenth the size.
INDEX_LIFECYCLE_ROW = re.compile(
    r"^\|\s*\[[^\]]+\]\(([^)#]+)[^)]*\)\s*\|\s*"
    r"\*{0,2}(normative|current|historical|proposed)\*{0,2}\s*\|", re.M)
INDEX_LIFECYCLE_WORD = re.compile(
    r"\b(normative|current|historical|proposed)\b", re.I)
INDEX_LIFECYCLE_UNSTATED = {
    "package-design.md": "状态 names the two projects that landed, not a lifecycle",
    "trait.md": "状态 is 已实现, which answers a different question",
    "native-driver-plan.md": "状态 counts the knives closed on the B line",
    "jvm-base-plan.md": "状态 is done, and then a paragraph of what done means",
    "atomic-write-design.md": "状态 is 已落地（两刀齐）, a landing note",
    "std-audit.md": "状态 says S5 is mostly done and the document is now a ledger",
}


def document_lifecycle(text: str) -> str | None:
    """The lifecycle a document claims for itself, or None if it claims none.

    Only the status line is read. A document that discusses `historical` EBNF in
    its prose is not thereby historical, and a check that searched the whole
    file would say it was."""
    head = text.split("\n")[:12]
    line = next((one for one in head if STATUS_LINE.match(one)), None)
    if line is None:
        # grammar.ebnf carries its status in an EBNF comment; it is a document
        # in the index like any other, and it is not Markdown.
        line = next((one for one in head
                     if "状态" in one or "Status" in one), None)
    if line is None:
        return None
    match = INDEX_LIFECYCLE_WORD.search(line)
    return None if match is None else match.group(1).lower()


def index_lifecycle_problems(index_text: str,
                             documents: dict[str, str]) -> tuple[list[str], int]:
    bad: list[str] = []
    checked = 0
    unstated: set[str] = set()
    for target, cell in INDEX_LIFECYCLE_ROW.findall(index_text):
        text = documents.get(target)
        if text is None:
            bad.append(f"docs/README.md: lifecycle row for {target}, which is "
                       f"not a document under docs/ [index_lifecycle_agrees]")
            continue
        claimed = document_lifecycle(text)
        if claimed is None:
            unstated.add(target)
            if target not in INDEX_LIFECYCLE_UNSTATED:
                bad.append(
                    f"docs/{target}: the index calls it {cell}, but its own "
                    f"status line names no lifecycle, and docs/README.md says "
                    f"the header is the authority. Name one, or record why not "
                    f"in INDEX_LIFECYCLE_UNSTATED "
                    f"[index_lifecycle_unstated_recorded]")
            continue
        checked += 1
        if claimed != cell:
            bad.append(f"docs/README.md: calls docs/{target} {cell}, but that "
                       f"document's own status line says {claimed}. The header "
                       f"is the authority; the index follows it "
                       f"[index_lifecycle_agrees]")
    for target in sorted(set(INDEX_LIFECYCLE_UNSTATED) - unstated):
        bad.append(f"docs/{target}: recorded as naming no lifecycle, but it now "
                   f"names one. Drop the line "
                   f"[index_lifecycle_unstated_stale]")
    return bad, checked


def read_index_lifecycle_documents() -> dict[str, str]:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    documents: dict[str, str] = {}
    for target, _cell in INDEX_LIFECYCLE_ROW.findall(index):
        path = ROOT / "docs" / target
        if path.is_file():
            documents[target] = path.read_text(encoding="utf-8")
    return documents


def check_index_lifecycle() -> tuple[list[str], int]:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    return index_lifecycle_problems(index, read_index_lifecycle_documents())


# The three predicates above read *rows*, so a section that lists its documents
# as prose is invisible to all three. `特性设计与实现理由` was such a section for
# months: eighteen documents behind one sentence saying they were all
# historical, which no machine read and which two of them had already stopped
# being. Deleting the lifecycle word from any of their headers left the gate
# green. That is not a bug in the row predicates -- they were never shown the
# documents -- so the fix is to require that this section hand every document
# it links to a row of its own, and to say so where a future edit will trip
# over it. A section listed here cannot go back to prose quietly.
LIFECYCLE_TABULATED_SECTIONS = ("特性设计与实现理由",)
# Relative links to a docs/ Markdown file, which is what a lifecycle row can
# name. Anchors and external URLs are not documents to be tabulated.
INDEX_SECTION_DOC_LINK = re.compile(r"\[[^\]]+\]\((?!\w+:)([^)#\s]+\.md)[^)]*\)")


def index_block_tabulated_problems(index_text: str) -> tuple[list[str], int]:
    bad: list[str] = []
    checked = 0
    for heading in LIFECYCLE_TABULATED_SECTIONS:
        section = markdown_section(index_text, heading)
        if section is None:
            bad.append(f"docs/README.md: section 「{heading}」 is gone, and its "
                       f"per-document lifecycle rows with it. Rename the entry "
                       f"in LIFECYCLE_TABULATED_SECTIONS along with the heading "
                       f"[index_lifecycle_block_tabulated]")
            continue
        rows = {target for target, _cell in INDEX_LIFECYCLE_ROW.findall(section)}
        for target in dict.fromkeys(INDEX_SECTION_DOC_LINK.findall(section)):
            checked += 1
            if target not in rows:
                bad.append(
                    f"docs/README.md: 「{heading}」 links docs/{target} but gives "
                    f"it no lifecycle row, so nothing compares it with that "
                    f"document's own status line. Every document this section "
                    f"lists needs a `| [{target}]({target}) | <lifecycle> | … |` "
                    f"row [index_lifecycle_block_tabulated]")
    return bad, checked


def check_index_lifecycle_block() -> tuple[list[str], int]:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    return index_block_tabulated_problems(index)


INDEX_LIFECYCLE_BLOCK_MUTANTS = (
    "a-row-demoted-to-a-prose-link",
    "the-whole-block-back-to-prose",
    "the-section-heading-renamed",
)


def check_index_lifecycle_block_selftest() -> tuple[list[str], int]:
    """Each mutant is a way the section stops being read per document.

    The control matters as much as the three: a link in a *different* section
    must redden nothing, or this check would be demanding rows from the whole
    index and would be turned off the first time somebody added a `参见`."""
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    baseline, checked = index_block_tabulated_problems(index)
    if baseline:
        return [f"index block self-test baseline is invalid: {baseline[0]}"], 0
    if checked < 2:
        return [f"index block self-test: only {checked} link(s) in scope, so a "
                f"section reverting to prose would prove nothing"], 0

    heading = LIFECYCLE_TABULATED_SECTIONS[0]
    section = markdown_section(index, heading)
    row = re.search(INDEX_LIFECYCLE_ROW.pattern + r"[^\n]*\n", section, re.M)
    for name in INDEX_LIFECYCLE_BLOCK_MUTANTS:
        if name == "a-row-demoted-to-a-prose-link":
            target = row.group(1)
            mutant = index.replace(
                row.group(0), f"[{target}]({target})（本篇改回散文）\n")
        elif name == "the-whole-block-back-to-prose":
            prose = "\n".join(
                f"[{target}]({target}) ·"
                for target, _cell in INDEX_LIFECYCLE_ROW.findall(section))
            mutant = index.replace(section, f"\n{prose}\n\n状态一律 historical。\n")
        else:
            mutant = index.replace(f"## {heading}\n", "## 特性设计\n")
        bad, _ = index_block_tabulated_problems(mutant)
        seen = {label for problem in bad
                for label in re.findall(r"\[(\w+)\]", problem)}
        if seen != {"index_lifecycle_block_tabulated"}:
            return [f"index block self-test: mutant {name} reddened "
                    f"{sorted(seen) or 'nothing'}, expected exactly "
                    f"[index_lifecycle_block_tabulated]"], 0

    control = index.replace(
        "## 调研\n", "## 调研\n\n参见 [spec.md](spec.md)。\n")
    bad, _ = index_block_tabulated_problems(control)
    if bad:
        return [f"index block self-test: a prose link outside the tabulated "
                f"sections reddened {bad[0]}"], 0
    return [], len(INDEX_LIFECYCLE_BLOCK_MUTANTS) + 1


INDEX_LIFECYCLE_MUTANTS = (
    ("a-document-retired-without-telling-the-index", "index_lifecycle_agrees"),
    ("a-header-that-stops-naming-a-lifecycle",
     "index_lifecycle_unstated_recorded"),
    ("a-recorded-header-that-starts-naming-one",
     "index_lifecycle_unstated_stale"),
    ("prose-about-a-historical-file", None),
)


def check_index_lifecycle_selftest() -> tuple[list[str], int]:
    index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
    documents = read_index_lifecycle_documents()
    baseline, checked = index_lifecycle_problems(index, documents)
    if baseline:
        return [f"index lifecycle self-test baseline is invalid: {baseline[0]}"], 0
    if not checked:
        return ["index lifecycle self-test: no row was verifiable, so every "
                "mutant below would pass for the wrong reason"], 0
    # A row the mutation can actually move: retiring a document the index
    # already calls historical changes nothing, and a mutant that changes
    # nothing proves nothing.
    cells = dict(INDEX_LIFECYCLE_ROW.findall(index))
    stated = next(rel for rel, text in sorted(documents.items())
                  if document_lifecycle(text) is not None
                  and cells.get(rel) != "historical")
    recorded = sorted(INDEX_LIFECYCLE_UNSTATED)[0]
    for name, expected in INDEX_LIFECYCLE_MUTANTS:
        mutated = dict(documents)
        if name == "a-document-retired-without-telling-the-index":
            mutated[stated] = "# T\n\n> 状态：**historical** —— retired.\n"
        elif name == "a-header-that-stops-naming-a-lifecycle":
            mutated[stated] = "# T\n\n> 状态：**已落地**，两刀齐。\n"
        elif name == "a-recorded-header-that-starts-naming-one":
            mutated[recorded] = "# T\n\n> 状态：**current** —— still applies.\n"
        elif name == "prose-about-a-historical-file":
            mutated[stated] = mutated[stated] + \
                "\n本文讨论 historical 的 EBNF 与 proposed 的方案。\n"
        bad, _ = index_lifecycle_problems(index, mutated)
        seen = {label for problem in bad
                for label in re.findall(r"\[(\w+)\]", problem)}
        if expected is None:
            if bad:
                return [f"index lifecycle self-test: control mutant {name} "
                        f"reddened {sorted(seen)}; it must redden nothing"], 0
            continue
        if seen != {expected}:
            return [f"index lifecycle self-test: mutant {name} reddened "
                    f"{sorted(seen) or 'nothing'}, expected exactly "
                    f"[{expected}]"], 0
    return [], len(INDEX_LIFECYCLE_MUTANTS)


def audit_counts(states: dict[str, set[str]]) -> dict[str, int]:
    return {status: len(ids) for status, ids in states.items()}


def rewrite_audit_summaries(text: str, states: dict[str, set[str]],
                            status_pattern: re.Pattern,
                            state_order: tuple[str, ...],
                            self_check_pattern: re.Pattern,
                            status_line, self_check_line,
                            topic_totals: tuple[tuple[str, int], ...]) -> str:
    counts = audit_counts(states)
    text = status_pattern.sub(
        lambda match: status_line(match.group(1), counts[match.group(1)]), text)
    text = self_check_pattern.sub(self_check_line(counts), text, count=1)
    for topic, _ in topic_totals:
        prefix = AUDIT_TOPIC_PREFIX[topic]
        topic_counts = tuple(sum(1 for audit_id in states[status]
                                 if audit_id.startswith(prefix + "-"))
                             for status in state_order)
        old_counts = "/".join(r"\d+" for _status in state_order)
        rendered = "/".join(str(value) for value in topic_counts)
        text = re.sub(re.escape(topic) + r" \*\*" + old_counts + r"\*\*",
                      f"{topic} **{rendered}**", text, count=1)
    return text


def render_audit_statuses(text: str, states: dict[str, set[str]],
                          status_pattern: re.Pattern,
                          state_order: tuple[str, ...], layer: str,
                          status_line, self_check_pattern: re.Pattern,
                          self_check_line,
                          topic_totals: tuple[tuple[str, int], ...],
                          prefix_totals: dict[str, int]) -> str:
    blocks, problems = audit_status_blocks(text, status_pattern, state_order, layer)
    if problems:
        return text
    topic_name = {prefix: topic for topic, prefix in AUDIT_TOPIC_PREFIX.items()}
    rendered: list[str] = []
    for status in state_order:
        rendered.append(status_line(status, len(states[status])) + "\n")
        prefixes = list(prefix_totals)
        prefixes += sorted({audit_id.split("-", 1)[0] for audit_id in states[status]}
                           - set(prefixes))
        for prefix in prefixes:
            ids = sorted(audit_id for audit_id in states[status]
                         if audit_id.startswith(prefix + "-"))
            if ids:
                rendered.append(f"- {topic_name.get(prefix, prefix)}（{len(ids)}）：" +
                                "、".join(f"`{audit_id}`" for audit_id in ids) + ".\n")
        rendered.append("\n")
    start = blocks[state_order[0]][0]
    end = blocks[state_order[-1]][1]
    updated = text[:start] + "\n".join(rendered).rstrip() + "\n\n" + text[end:].lstrip("\n")
    return rewrite_audit_summaries(
        updated, states, status_pattern, state_order, self_check_pattern,
        status_line, self_check_line, topic_totals)


def historical_status_line(status: str, count: int) -> str:
    return f"**{status}（{count}）**"


def historical_self_check_line(counts: dict[str, int]) -> str:
    return (f"计数自检：**{counts['已修']} 已修 + {counts['部分']} 部分 + "
            f"{counts['开放']} 开放 = {AUDIT_FROZEN_TOTAL}**")


def current_status_line(status: str, count: int) -> str:
    return f"#### 当前 {status}（{count}）"


def current_self_check_line(counts: dict[str, int]) -> str:
    return (f"当前计数自检：**{counts['fixed']} fixed + {counts['partial']} partial + "
            f"{counts['open']} open + {counts['retracted']} retracted = "
            f"{AUDIT_CURRENT_TOTAL}**")


def rewrite_historical_audit_summaries(text: str,
                                       states: dict[str, set[str]]) -> str:
    return rewrite_audit_summaries(
        text, states, HISTORICAL_AUDIT_STATUS, HISTORICAL_AUDIT_STATES,
        HISTORICAL_AUDIT_SELF_CHECK, historical_status_line,
        historical_self_check_line, AUDIT_FROZEN_TOPIC_TOTALS)


def render_historical_audit_statuses(text: str,
                                     states: dict[str, set[str]]) -> str:
    return render_audit_statuses(
        text, states, HISTORICAL_AUDIT_STATUS, HISTORICAL_AUDIT_STATES,
        "historical", historical_status_line, HISTORICAL_AUDIT_SELF_CHECK,
        historical_self_check_line, AUDIT_FROZEN_TOPIC_TOTALS,
        AUDIT_FROZEN_PREFIX_TOTALS)


def render_current_audit_statuses(text: str,
                                  states: dict[str, set[str]]) -> str:
    return render_audit_statuses(
        text, states, CURRENT_AUDIT_STATUS, CURRENT_AUDIT_STATES, "current",
        current_status_line, CURRENT_AUDIT_SELF_CHECK, current_self_check_line,
        AUDIT_CURRENT_TOPIC_TOTALS, AUDIT_CURRENT_PREFIX_TOTALS)


def check_historical_audit_status_selftest() -> tuple[list[str], int]:
    """The old three-state evidence remains checked, but never supplies current state."""
    path = ROOT / "docs/codebase-audit-v2.md"
    text = path.read_text(encoding="utf-8")
    details = read_audit_details()
    baseline = audit_status_problems(text, details)
    if baseline:
        return [f"audit status self-test baseline is invalid: {baseline[0]}"], 0
    states, _, _ = parse_audit_state(
        text, HISTORICAL_AUDIT_STATUS, HISTORICAL_AUDIT_STATES, "historical",
        AUDIT_FROZEN_PREFIX_TOTALS)
    if not states["开放"]:
        return ["audit status self-test: no open finding available for migration"], 0
    moved = sorted(states["开放"])[0]
    claimed = {status: set(ids) for status, ids in states.items()}
    claimed["开放"].remove(moved)
    claimed["已修"].add(moved)
    numbers_only = rewrite_historical_audit_summaries(text, claimed)
    if not audit_status_problems(numbers_only, details):
        return ["audit status self-test: changing only counts without moving an ID stayed green"], 0
    migrated = render_historical_audit_statuses(text, claimed)
    problems = audit_status_problems(migrated, details)
    if problems:
        return [f"audit status self-test: a coherent open-to-fixed migration failed: "
                f"{problems[0]}"], 0

    duplicated = {status: set(ids) for status, ids in states.items()}
    duplicated["已修"].add(moved)
    problems = audit_status_problems(render_historical_audit_statuses(text, duplicated), details)
    if not any(f"audit ID {moved} appears in both" in problem for problem in problems):
        return ["audit status self-test: a duplicate ID across statuses stayed green"], 0

    omitted = {status: set(ids) for status, ids in states.items()}
    omitted["开放"].remove(moved)
    problems = audit_status_problems(render_historical_audit_statuses(text, omitted), details)
    if not any(f"omits {moved}" in problem for problem in problems):
        return ["audit status self-test: an omitted ID stayed green"], 0

    detail_path = AUDIT_DETAIL_FILES[0][1]
    added_detail = dict(details)
    added_detail[detail_path] += "\n## SYN-20 — P3 — detail-universe self-test\n"
    problems = audit_status_problems(text, added_detail)
    if not any("contains 20 SYN headings" in problem for problem in problems):
        return ["audit status self-test: a finding added to a detail stayed green"], 0

    duplicate_detail = dict(details)
    duplicate_detail[detail_path] += "\n## SYN-01 — P1 — duplicate self-test\n"
    problems = audit_status_problems(text, duplicate_detail)
    if not any("audit finding SYN-01 is duplicated" in problem for problem in problems):
        return ["audit status self-test: a duplicate detail finding stayed green"], 0

    missing_detail = dict(details)
    missing_detail[detail_path], changed = re.subn(
        r"^## SYN-19\b[^\n]*\n", "", missing_detail[detail_path], count=1, flags=re.M)
    if changed != 1:
        return ["audit status self-test: missing-detail fixture was not mutated"], 0
    problems = audit_status_problems(text, missing_detail)
    if not any("contains 18 SYN headings" in problem for problem in problems):
        return ["audit status self-test: a finding omitted from a detail stayed green"], 0

    current_universe, universe_problems = audit_detail_universe(details)
    if universe_problems:
        return [f"audit status self-test: current universe is invalid: "
                f"{universe_problems[0]}"], 0
    frozen_universe = expected_audit_universe(AUDIT_FROZEN_PREFIX_TOTALS)
    post_frozen = sorted(current_universe - frozen_universe)
    if not post_frozen:
        return ["audit status self-test: no post-freeze finding exercises the split"], 0
    leaked = {status: set(ids) for status, ids in states.items()}
    leaked["已修"].add(post_frozen[0])
    problems = audit_status_problems(
        render_historical_audit_statuses(text, leaked), details)
    if not any(f"out-of-range audit ID `{post_frozen[0]}`" in problem
               for problem in problems):
        return ["audit status self-test: a post-freeze finding entered the "
                "historical universe without turning red"], 0
    return [], 8


def check_current_audit_status_selftest() -> tuple[list[str], int]:
    """Current counts, IDs, P1 states and coherent migrations move together."""
    path = ROOT / "docs/codebase-audit-v2.md"
    text = path.read_text(encoding="utf-8")
    details = read_audit_details()
    baseline = audit_status_problems(text, details)
    if baseline:
        return [f"current audit status self-test baseline is invalid: {baseline[0]}"], 0
    states, _, _ = parse_audit_state(
        text, CURRENT_AUDIT_STATUS, CURRENT_AUDIT_STATES, "current",
        AUDIT_CURRENT_PREFIX_TOTALS)
    p1_ids, _ = audit_p1_universe(details)
    candidates = sorted(states["open"] - p1_ids)
    if not candidates:
        return ["current audit status self-test: no non-P1 open finding is available"], 0
    moved = candidates[0]

    wrong_count = re.sub(r"^#### 当前 fixed（\d+）$",
                         "#### 当前 fixed（999）", text, count=1, flags=re.M)
    problems = audit_status_problems(wrong_count, details)
    if not any("current status fixed heading says 999" in problem for problem in problems):
        return ["current audit status self-test: a wrong declared count stayed green"], 0

    migrated = {status: set(ids) for status, ids in states.items()}
    migrated["open"].remove(moved)
    migrated["fixed"].add(moved)
    problems = audit_status_problems(render_current_audit_statuses(text, migrated), details)
    if problems:
        return [f"current audit status self-test: a coherent migration failed: "
                f"{problems[0]}"], 0

    duplicated = {status: set(ids) for status, ids in states.items()}
    duplicated["fixed"].add(moved)
    problems = audit_status_problems(render_current_audit_statuses(text, duplicated), details)
    if not any(f"audit ID {moved} appears in both" in problem for problem in problems):
        return ["current audit status self-test: a duplicate current ID stayed green"], 0

    omitted = {status: set(ids) for status, ids in states.items()}
    omitted["open"].remove(moved)
    problems = audit_status_problems(render_current_audit_statuses(text, omitted), details)
    if not any(f"omits {moved}" in problem for problem in problems):
        return ["current audit status self-test: an omitted current ID stayed green"], 0

    unknown = {status: set(ids) for status, ids in states.items()}
    unknown["fixed"].add("NOPE-01")
    problems = audit_status_problems(render_current_audit_statuses(text, unknown), details)
    if not any("unknown audit ID family NOPE-01" in problem for problem in problems):
        return ["current audit status self-test: an unknown current ID stayed green"], 0

    p1_mismatch, changed = re.subn(
        r"^(\| `SYN-01` \|) fixed (\| formatter 词法失败不再写回。 \|)$",
        r"\1 open \2", text, count=1, flags=re.M)
    if changed != 1:
        return ["current audit status self-test: P1 mapping fixture was not mutated"], 0
    problems = audit_status_problems(p1_mismatch, details)
    if not any("current P1 mapping SYN-01 says open, current registry says fixed" in problem
               for problem in problems):
        return ["current audit status self-test: a P1/current-state mismatch stayed green"], 0
    return [], 6


def check_audit_index_status_selftest() -> tuple[list[str], int]:
    """Both audit indexes reject task-status columns and task-status cells."""
    texts = {rel: (ROOT / rel).read_text(encoding="utf-8")
             for rel, _heading, _columns in AUDIT_INDEX_TABLES}
    baseline = audit_index_status_problems(texts)
    if baseline:
        return [f"audit index status self-test baseline is invalid: {baseline[0]}"], 0
    seen = 0
    for rel, heading, expected_columns in AUDIT_INDEX_TABLES:
        columns, rows, problems = markdown_table(texts[rel], heading)
        if problems or not rows:
            return [f"audit index status self-test: {rel} fixture table is missing"], 0
        material_index = columns.index("材料类型")
        header_line = "| " + " | ".join(expected_columns) + " |"
        status_columns = list(expected_columns)
        status_columns[material_index] = "状态"
        mutated_header = texts[rel].replace(
            header_line, "| " + " | ".join(status_columns) + " |", 1)
        mutated = dict(texts)
        mutated[rel] = mutated_header
        problems = audit_index_status_problems(mutated)
        if not any(f"{rel}: audit material table copies task-status column" in problem
                   for problem in problems):
            return [f"audit index status self-test: {rel} accepted a task-status column"], 0
        seen += 1

        first_row = list(rows[0])
        source_line = "| " + " | ".join(first_row) + " |"
        first_row[material_index] += " proposed"
        mutated = dict(texts)
        mutated[rel] = texts[rel].replace(
            source_line, "| " + " | ".join(first_row) + " |", 1)
        problems = audit_index_status_problems(mutated)
        if not any(f"{rel}: audit material table row 1 copies task status" in problem
                   for problem in problems):
            return [f"audit index status self-test: {rel} accepted a task-status cell"], 0
        seen += 1
    return [], seen


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
        # The exit code above is the whole verdict for `compile` blocks. It was
        # not always: `dawn check` used to print every diagnostic as a `D\t...`
        # dump line and exit 0 regardless, so this gate had to parse the dump,
        # and anyone who followed the spec's "point CI at dawn check" advice got
        # a green build on a type error. Found 2026-08-07 by marking the spec's
        # associated-type example: the block passed while a hand-run `dawn run`
        # on the same source reported four errors. `check` exits 1 on any
        # diagnostic since #189 (TOOL-01); the dump moved to `dawn __check`.
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


def warm_toolchain() -> list[str]:
    """Build the toolchain once, outside the per-example bound.

    EXAMPLE_TIMEOUT is a hang detector sized for examples that take a couple
    of seconds, and it assumes the toolchain is already built -- which holds
    in CI, where gates.yml builds it first. It does not hold in a fresh
    checkout or worktree, and there the assumption fails in the worst
    available way: the first example pays for the whole build (measured 3m32s
    on a cold worktree, most of it resolving java-deps), the bound kills it
    partway, `build/dawn-selfhost.jar` is therefore never published, and the
    next example starts the same build from nothing. Every document times out
    in turn and the report names ~140 hangs, none of which are hangs.

    So the build gets its own step with no bound on it, and a toolchain that
    will not build is one named failure instead of a cascade of wrong ones.
    """
    p = subprocess.run([str(ROOT / "bin" / "dawn"), "--version"],
                       capture_output=True, text=True, cwd=ROOT)
    if p.returncode == 0:
        return []
    detail = (p.stderr or p.stdout).strip() or f"exit status {p.returncode}"
    return ["the toolchain would not build, so no example could have run:\n"
            + detail]


def main() -> None:
    problems: list[str] = []

    # Before anything that spawns `bin/dawn` -- the examples, the tutorial
    # fences, the site programs and the effect-inference probe all do.
    if bad := warm_toolchain():
        for p in bad:
            print(p, file=sys.stderr)
        print(f"FAIL: {len(bad)} documentation problem(s)", file=sys.stderr)
        sys.exit(1)
    blocks = anchors_seen = sections_seen = claims_seen = recorded = 0
    status_seen = counts_seen = indexed_seen = pages_seen = transl_seen = 0
    contracts_seen = policies_seen = audit_seen = fences_seen = selftests_seen = 0
    version = toolchain_version()
    # What docs/README.md's opening sentence counts: the Markdown documents
    # under docs/, which is DOCS minus the top-level files it does not index
    # (README, README.zh-CN, CLAUDE, CONTRIBUTING, CONTRIBUTING.zh-CN).
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
    bad, contracts_seen = check_spec_contracts(texts)
    problems += bad
    bad, n = check_spec_contracts_selftest(texts)
    problems += bad
    selftests_seen += n
    bad, n = check_effect_inference_probe()
    problems += bad
    selftests_seen += n
    bad, policies_seen = check_repository_contracts()
    problems += bad
    bad, n = check_repository_contracts_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_named_effect_status()
    problems += bad
    policies_seen += n
    bad, n = check_named_effect_status_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_analyze_env_table()
    problems += bad
    policies_seen += n
    bad, n = check_analyze_env_table_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_markdown_section_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_sections_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_status_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_tracked_documents_selftest()
    problems += bad
    selftests_seen += n
    bad, audit_seen = check_audit_status()
    problems += bad
    bad, n = check_audit_indexes()
    problems += bad
    audit_seen += n
    bad, n = check_audit_anchors()
    problems += bad
    audit_seen += n
    bad, n = check_audit_anchors_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_index_lifecycle()
    problems += bad
    indexed_seen += n
    bad, n = check_index_lifecycle_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_index_lifecycle_block()
    problems += bad
    indexed_seen += n
    bad, n = check_index_lifecycle_block_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_historical_audit_status_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_current_audit_status_selftest()
    problems += bad
    selftests_seen += n
    bad, n = check_audit_index_status_selftest()
    problems += bad
    selftests_seen += n

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
          f"and {transl_seen} translation(s) resolved; {contracts_seen} pinned "
          f"spec contract clause(s), {policies_seen} repository policy check(s) and "
          f"{audit_seen} audit status check(s), {selftests_seen} negative-control "
          f"self-test(s), "
          f"0 unknown")


if __name__ == "__main__":
    main()
