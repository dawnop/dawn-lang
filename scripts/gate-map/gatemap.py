#!/usr/bin/env python3
"""Which gates can see a change to this path.

    scripts/gate-map/gatemap.py selfhost/src/main.dawn
    scripts/gate-map/gatemap.py --changed origin/main
    scripts/gate-map/gatemap.py --compiler-inputs
    scripts/gate-map/gatemap.py --labels         # which differential owns which label
    scripts/gate-map/gatemap.py --check          # what CI runs

## Why this exists

Nobody had written down which gate sees which change, so every batch
re-derived it and two derived it wrong on the same day:

  * 3c51ae1 pinned a negative control to a whole sentence the std loader
    prints; 9e64179 rewrote that sentence. Each batch was green alone and the
    pair was red, because a contract script and a compiler module shared a
    string constant and nothing said so.
  * 98b9896 rewrote `dawn --help` and `dawnc --help`. It ran doc-check,
    site-dist-diff, run-diff, prev-diff and native-cli-diff; none of the five
    can see driver text, and the re-record it needed was the Core golden
    (1c29bea).

Prose about gate boundaries is what rotted into those two failures, so this is
not prose. Everything below is computed from the tree on every run: the gate
inventory from the workflow files, the exact records from the goldens they are
recorded in, the couplings from the source and the scripts themselves. There is
no list of paths in this file. The one thing that *is* a list (unseen.txt, the
paths no gate watches) is a ratchet checked in both directions.

## The four verdicts, and what each is worth

  exact    Something recorded or declared moves when this file changes: an
           `Emit-Change` label, or, on a tree whose workflow still ran the
           Core IR diff as a step, the Core golden. Editing the file forces a
           deliberate declaration, so no change of any kind passes silently.

  coupled  A gate somewhere else spells out a sentence this file builds. Only
           that sentence is watched, and only from a directory the author of
           either side has no reason to look in. This is the first failure
           above, and it is a verdict of its own because it is neither of the
           two below: `--help` text is coupled to nothing while `usage:` text
           is coupled to the native CLI differential, in the same file.

  coarse   A gate compiles, runs or reads this file, so a change in *behaviour*
           reds it. A benign change (a comment, a string nothing observes)
           does not. This is a claim about the gate's inputs, not about its
           assertions: the map says the gate looks here, never that it would
           notice whatever you did.

  blind    A gate people reach for cannot see this file at all, and the reason
           is structural rather than accidental. Printed rather than omitted,
           because both of today's failures were somebody assuming a gate was
           in a higher tier than this one.

  (none)   No gate. Reported as such, and ratcheted in unseen.txt. A harness
           file no step reaches is reported as `unread` and ratcheted under
           that kind, which plan.py reads as "selects no job".

## The rules, and the file each is derived from

  A  A gate runs a script, so the files that script reaches are exact for it:
     the script, the sibling modules it imports, the files it sources, and
     the files its code names inside its own directory, closed over whatever
     those reach in turn (an import reaches the module's top level and the
     functions taken from it). A script whose reads cannot be bounded that
     way (its directory used as a value, a computed name inside it, a file
     that does not parse, a language with no reader) falls back to the old
     rule for that script alone: its whole directory is exact for it. A file
     under scripts/ that no step reaches either way is `unread`. The block
     comment above HarnessReader gives the edges and the reasons (#169).
     A script outside scripts/ owns only itself.
     From: the `run:` commands in .github/workflows/*.yml, followed through
     the scripts those scripts run.
  B  A gate's script names a path, so that path is coarse for it. Read from
     the scripts rule A says the gate runs or imports, not from every file
     beside them, and never for the harness's own directory, which rule A
     already read file by file. A harness directory handed to the toolchain
     as a project (`./bin/dawn test scripts/x`) is its SourcePlan inputs,
     the manifest and src, not every harness beside them. Slash-bearing
     tokens, shell globs, and for Python gates the `ROOT / "a" / "b"` joins and
     `.glob()` patterns that a regular expression cannot tell from division.
     For JavaScript gates the `join(ROOT, "a", "b")` and
     `resolve(__dirname, "..")` calls, which are the same statement in the
     only other language a gate here is written in, under whichever name the
     file bound them to: `path` is a name a script chooses, not a keyword, so
     the binding is read from the `require`/`import` that made it and a
     spelling this cannot follow is reported rather than read as naming
     nothing. A gate started as `npm test`
     is followed through the `scripts` table of the package.json in its working
     directory, because the lifecycle name is not a path and the table that
     binds it to one is in the tree.
     Bare directory names count only where a word cannot be prose: handed to
     the toolchain, or appended to a list of units.
  C  A step that runs scripts/selfhost-core-diff.sh dumps the Core of every
     compiler module, so every module is exact for it. This is what 98b9896
     needed. From: the workflow, and the tree's own selfhost/src/**.dawn.
     Since 2026-09-25 no step runs it (it is an on-demand tool, see
     docs/recorded-numbers-design.md), so on today's tree the rule contributes
     nothing; it still speaks on the historical trees the fixtures replay.
  D  prev-diff compiles each corpus target's source in both output legs, so the
     target's own corpus content cancels: it is blind there. That is the general
     rule and the driver modules of 98b9896 are one case of it. std is the
     exception, because the N-1 side is pointed at the std it was released with.

     The selfhost project has a second role. It builds the HEAD compiler
     selected by `HEAD_BIN=(./bin/dawn)` from a SourcePlan input closure rooted
     at selfhost. The closure follows repo-local string `[deps]` recursively;
     each project contributes dawn.toml and src, while only the root contributes
     its optional dawn.lock. Paths are lexically normalized inside the
     historical Tree; unknown dependency forms, parse errors, missing inputs,
     escapes and cycles void the premise. A compiler semantic or build-input
     change can move the HEAD leg for any emit target, including selfhost
     itself, even though selfhost's own corpus content still cancels. Every path
     in that derived closure receives a separate compiler-input coarse verdict.
     `--compiler-inputs` serializes the same closure as a
     `dawn-source-inputs-v1` manifest. The source-plan contract compares that
     output byte for byte with `dawn __source-inputs`, so a schema, record,
     kind or ordering change cannot leave these two derivations silently split.
     From: the `emit <target>` labels in scripts/emit-labels.txt, taken from
     that script's own section, plus the exact output legs,
     `HEAD_BIN=(./bin/dawn)` assignment and HEAD_BIN invocation in
     scripts/selfhost-prev-diff.sh, whose continued presence is checked.
  E  A gate that spells out a string a source module builds is coupled to that
     module, and the coupling is invisible from either side. This is what
     3c51ae1 and 9e64179 needed.
     From: string literals in the Dawn sources against the gate scripts' text.
  F  std/modules.txt selects the bundled-module set printed by the unknown-std
     diagnostic. The checker corpus records that sorted set byte for byte, so
     the index itself and the module paths it names are exact for the corpus.
     A direct query reads the current index; `--changed` reads both the base
     and head indexes, so removal and rename paths remain attributable after
     they disappear. An unlisted std/*.dawn file is not part of this rule.
     From: the diagnostic expression in selfhost/src/check/passes.dawn, the
     recorded line in scripts/checker-corpus/cases/imports.expected, and the
     workflow step that runs scripts/checker-corpus/run.sh.
  G  Rule E for signatures. A mutation harness that rewrites a function has to
     quote that function's declaration verbatim to find it, so the declaration
     is a shared string exactly the way a printed sentence is, and moving it
     reds a script in another directory that names neither the file nor the
     change. This is what bd664890 needed: an effect row lost `!io` and two
     harnesses that had quoted the old row went red one push later.
     From: the signature text of each Dawn declaration, `fn name(` through the
     `=` that opens its body, against the gate scripts' text.
  H  A gate that compiles an example project also compiles its local package
     dependencies. Follow the example's dawn.toml string dependencies, including
     transitive ones, and attribute their manifests and src trees to the gates
     already watching the example manifest. A missing or invalid closure voids
     this attribution rather than guessing that all packages are inputs.

`--labels` answers the neighbouring question, from the same file: which
differential owns which declarable label. `scripts/emit-labels.txt` is
partitioned by `# ---- <script> ----`, so `doc --builtins` is a label of its
own that only the run/test transcript can see, and `prev-diff` is the name of a
job with four differentials in it rather than a synonym for
`scripts/selfhost-prev-diff.sh`. Both of those were prose until this read them.

Every rule can be wrong, in either direction. Over-claiming is the dangerous
one, because a map that says a file is watched when it is not is the failure
this exists to fix, one level up. So where a rule had to choose it under-claims
and the residue is written down in unseen.txt where somebody can read it.

## What checks the map

`--check` runs four things, in this order, and CI runs `--check`:

  selftest   the mutant matrix. Every rule is shown refusing a mutated tree
             before its silence counts as a pass, and every mutant is run
             against the *whole* assertion set so that ownership is measured
             rather than asserted: an assertion two mutants can redden is owned
             by neither. The record is mutants.txt and the rules are in the
             block comment above `Check`.
  structure  every path-shaped command in every workflow resolves; every label
             section names a differential some step runs; rule D's premises
             still hold. A rule whose premise moved is void, not stale.
  ratchet    the set of paths with no gate equals unseen.txt, in both
             directions, and each line's stated reason is one the map still
             supports. A new unwatched file reds this, so does a listed file
             that has since acquired a gate, and so does a reason that has
             stopped being true.
  fixtures   the two failures above, replayed from the trees they happened on.
             Not a restatement: fixtures.txt names commits, the trees are
             materialised from git, and the whole map is run on them. Each
             stanza also carries `ground` lines, which are claims about the
             history rather than about the map, measured with git, so a fixture
             cannot go on describing an event that never had this shape.
"""

import argparse
from functools import lru_cache
import json
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

WORKFLOWS = [
    "gates.yml",
    "ci.yml",
    "release.yml",
    "editor-grammar.yml",
    "tile.yml",
]

# Workflows that only run for a tag. Their gates are real, but they are not
# what a branch push is measured against, so the report says so.
TAG_ONLY = {"release.yml"}

# A literal shorter than this, or without a space or a backtick in it, is a
# token rather than a sentence: `Content-Length`, `DAWN_PKG_CACHE`,
# `java.lang.String`. Those collide across unrelated files and would bury rule
# E's real hits. Measured on this tree: 4056 literals and 217 pairs without the
# filter, 2684 and 72 with it, and the pair rule E exists for
# (driver/stdlib.dawn against pipe-contract) survives both.
MIN_LITERAL = 14

# `dawn test --stdlib` runs std's own test blocks. The flag names a target the
# way a path argument does, so it is resolved like one. This is CLI vocabulary,
# not a path list: every value is required to be a directory that exists.
CLI_TARGET_ALIASES = {"--stdlib": "std"}

# The tree files this checker reads as evidence, named once so that rules D
# and F, rule A/B's attribution and the structural checks all mean the same
# files.
CORE_DIFF = "scripts/selfhost-core-diff.sh"
# Read out of git history only, by the `golden-moved` ground verb: the golden
# left the tree on 2026-09-25, and the commits the fixtures cite still carry it.
HISTORICAL_CORE_GOLDEN = "scripts/core-golden/selfhost.sha"
EMIT_LABELS = "scripts/emit-labels.txt"
PREV_DIFF = "scripts/selfhost-prev-diff.sh"
STD_MODULE_INDEX = "std/modules.txt"
CHECKER_CORPUS = "scripts/checker-corpus/run.sh"
CHECKER_CORPUS_GOLDEN = "scripts/checker-corpus/cases/imports.expected"
BUNDLED_MODULE_DIAGNOSTIC = "selfhost/src/check/passes.dawn"
BUNDLED_MODULE_EXPRESSION = (
    '"bundled modules: " ++ join(sort(std_names), ", "))'
)
BUNDLED_MODULE_GOLDEN_TEXT = "\tbundled modules: "
SELFHOST_PROJECT = "selfhost"
SELFHOST_MANIFEST = "selfhost/dawn.toml"
SELFHOST_LOCK = "selfhost/dawn.lock"
# These are executable premises, not a package-to-gate roster. A script that
# merely reads example files (formatting, docs) does not compile their deps.
EXAMPLE_COMPILERS = {
    "scripts/example-tests.sh": './bin/dawn test "$u"',
    "scripts/example-main-contract/run.py":
        'command = [str(ROOT / "bin" / "dawn"), "run", target]',
}
SOURCE_INPUTS_HEADER = "dawn-source-inputs-v1"
COMPILER_CLOSURE_PROBLEM = "selfhost compiler input closure is void"
VALID_DAWN_NAME = re.compile(r"[a-z_][a-z0-9_]*")
HEAD_BIN_ASSIGNMENT = "HEAD_BIN=(./bin/dawn)"
PREV_EMIT_WORDS = (
    "${PREV[@]}",
    "__emit",
    "${PREV_STD[@]}",
    "$t",
    "-o",
    "$OUT/prev/$t",
    ">",
    "/dev/null",
)
HEAD_EMIT_TAIL = (
    "__emit",
    "$t",
    "-o",
    "$OUT/head/$t",
    ">",
    "/dev/null",
)
HEAD_EMIT_WORDS = ("${HEAD_BIN[@]}",) + HEAD_EMIT_TAIL
HEAD_EMIT_COMMAND = (
    '"${HEAD_BIN[@]}" __emit "$t" -o "$OUT/head/$t" > /dev/null'
)
HEAD_COMPILER_REASON = (
    "`HEAD_BIN=(./bin/dawn)` makes the HEAD leg run the compiler built from "
    "the SourcePlan input closure rooted at the selfhost project"
)

# This file, exempt from rules A and B. Every other gate script names a path in
# order to read it; this one names paths in order to describe them, in a usage
# line, in a comment about what a rule measured, in a mutant's probe. Scraping
# it made the map claim that this one step *runs* doc-check.py, emitchange.sh,
# lsp-liveness.py, seedjar.sh and both prev-diff scripts, because a mutant's
# edit dictionary has a script path in the position a shell command would put
# one, and every input of those six then counted as watched by this step. That
# is the failure this whole directory exists to fix, one level up.
#
# So what this file reads is declared instead of scraped. The declaration
# cannot describe files the checker stopped reading, because the rules below
# use these constants and nothing else: delete a use and the rule it belongs to
# stops working, loudly.
SELF = "scripts/gate-map/gatemap.py"
SELF_INPUTS = (
    EMIT_LABELS,
    PREV_DIFF,
    STD_MODULE_INDEX,
    BUNDLED_MODULE_DIAGNOSTIC,
    CHECKER_CORPUS_GOLDEN,
)

# plan.py, next to this file, is exempt for the same reason. It names paths
# in order to describe them (the prefixes that force the whole gate set) and
# reads nothing by path except through this file's Map, so scraping it would
# record the plan job as running scripts/build-release-jar.sh and reading
# every seed pin, and the ratchet would count those as watched.
PLAN = "scripts/gate-map/plan.py"
UNSCRAPED = (SELF, PLAN)


PATH_TOKEN = re.compile(r"[A-Za-z0-9_*][A-Za-z0-9_.$@+*-]*(?:/[A-Za-z0-9_.$@+*-]+)+")
BARE_TOKEN = re.compile(r"(?<![\w./-])([A-Za-z][\w-]*)(?![\w./-])")
DAWN_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')

# A line that only prints. `echo "... (selfhost)"` is not a gate reading
# selfhost, and bare directory names are common enough in prose that admitting
# them from message text would make every job look as if it watched everything.
PRINTS_ONLY = re.compile(r"^\s*(echo|printf)\b")

LEVELS = ("exact", "coupled", "coarse", "blind")

# Reporting order, which is not strength order. `blind` is the answer somebody
# is most likely to be wrong about, so it goes second rather than last: the
# batch that declared five labels no oracle could see would have had to scroll
# past every `coarse` line to reach it.
REPORT_ORDER = ("exact", "blind", "coupled", "coarse")


def std_module_paths(index_text):
    """The module paths selected by modules.txt, mirroring stdlib.index_names."""
    names = []
    for line in index_text.split("\n"):
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(f"std/{name}.dawn")
    return set(names)


def run_git(args, cwd=ROOT, check=True):
    proc = subprocess.run(
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def file_at_revision(revision, path):
    """A file at a revision, or empty text when that revision lacks it."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{revision}:{path}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return proc.stdout
    valid = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{revision}^{{tree}}"],
        capture_output=True,
        text=True,
    )
    if valid.returncode != 0:
        raise RuntimeError(
            f"git cannot resolve revision {revision}: {valid.stderr.strip()}"
        )
    return ""


def std_modules_at_revision(revision):
    return std_module_paths(file_at_revision(revision, STD_MODULE_INDEX))


def changed_paths(revision, end=None):
    """Paths changed from revision, keeping both sides of every rename."""
    args = ["diff", "--no-renames", "--name-only", revision]
    if end is not None:
        args.append(end)
    return [path for path in run_git(args).split("\n") if path]


class Tree:
    """One checked-out tree, and the questions the rules ask of it.

    `overrides` replaces a file's text without touching the disk, and `cache`
    is shared with the tree it was derived from. Together they are what makes a
    mutant cheap: the selftest builds a dozen trees that differ from this one in
    a single file, and materialising each of them cost more than every rule in
    here put together.
    """

    def __init__(self, root, files=None, overrides=None, cache=None):
        self.root = Path(root)
        if files is None:
            files = [p for p in run_git(["ls-files"], cwd=self.root).split("\n") if p]
        self.files = sorted(files)
        self.fileset = set(self.files)
        self.overrides = dict(overrides or {})
        self._cache = cache if cache is not None else {}
        # keyed by token, and per tree because the file list is what a token
        # resolves against
        self.resolved = {}
        self.dirs = set()
        for f in self.files:
            parts = f.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))

    def mutate(self, files=None, overrides=None):
        """A sibling tree differing in a file list and/or some file contents."""
        merged = dict(self.overrides)
        merged.update(overrides or {})
        return Tree(
            self.root,
            self.files if files is None else files,
            overrides=merged,
            cache=self._cache,
        )

    def read(self, rel):
        if rel in self.overrides:
            return self.overrides[rel]
        if rel in self._cache:
            return self._cache[rel]
        try:
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        self._cache[rel] = text
        return text

    def exists(self, rel):
        return rel in self.fileset or rel in self.dirs

    def under(self, prefix):
        if prefix in self.fileset:
            return [prefix]
        return [f for f in self.files if f.startswith(prefix + "/")]


class Gate:
    def __init__(self, workflow, job, name, line):
        self.workflow = workflow
        self.job = job
        self.name = name
        self.line = line
        self.commands = []
        self.workdir = None

    @property
    def id(self):
        return f"{self.job} / {self.name}"

    @property
    def tag_only(self):
        return self.workflow in TAG_ONLY

    def where(self):
        return f"{self.workflow}:{self.line}"


JOB_RE = re.compile(r"^  ([A-Za-z][\w-]*):\s*$")
STEP_NAME_RE = re.compile(r"^(\s+)- name:\s*(.+?)\s*$")
STEP_START_RE = re.compile(r"^(\s+)- \S")
RUN_INLINE_RE = re.compile(r"^(\s+)run:\s*(?!\|)(\S.*)$")
RUN_BLOCK_RE = re.compile(r"^(\s+)run:\s*\|\s*$")
WORKDIR_RE = re.compile(r"^\s+working-directory:\s*(\S+)\s*$")


def parse_workflow(text, name):
    """Gates out of one workflow file.

    A hand-rolled scanner rather than PyYAML, for the reason
    check-gate-budgets.py gives: this must run wherever the repository does,
    and the subset of YAML the workflows use is regular.
    """
    lines = text.splitlines()
    gates = []
    job = None
    current = None
    i = 0
    while i < len(lines):
        line = lines[i]
        job_match = JOB_RE.match(line)
        if job_match:
            job = job_match.group(1)
            current = None
            i += 1
            continue
        name_match = STEP_NAME_RE.match(line)
        if name_match:
            current = Gate(name, job or "?", name_match.group(2), i + 1)
            gates.append(current)
            i += 1
            continue
        if STEP_START_RE.match(line) and not name_match:
            # a step with no `name:` (checkout, the toolchain action)
            current = None
        workdir = WORKDIR_RE.match(line)
        if workdir and current is not None:
            current.workdir = workdir.group(1).strip("\"'")
            i += 1
            continue
        inline = RUN_INLINE_RE.match(line)
        if inline and current is not None:
            current.commands.append(inline.group(2))
            i += 1
            continue
        block = RUN_BLOCK_RE.match(line)
        if block and current is not None:
            indent = len(block.group(1))
            i += 1
            while i < len(lines):
                body = lines[i]
                if body.strip() and (len(body) - len(body.lstrip())) <= indent:
                    break
                current.commands.append(body.strip())
                i += 1
            continue
        i += 1
    return [g for g in gates if g.commands]


def gates_of(tree):
    gates = []
    for wf in WORKFLOWS:
        rel = f".github/workflows/{wf}"
        if tree.exists(rel):
            gates.extend(parse_workflow(tree.read(rel), wf))
    return gates


def strip_comments(text):
    """Whole-line comments only.

    Rule B reads path tokens out of scripts, and a prose paragraph naming
    `docs/spec.md` while explaining something else is not an input. Trailing
    comments are left alone because stripping them needs a lexer per language
    and would cut through string literals.

    `//` for the same reason in the one gate written in JavaScript. No tracked
    shell or Python file has a line starting with it, so the two comment
    markers do not have to be told apart by language.
    """
    return "\n".join(
        ln
        for ln in text.splitlines()
        if not ln.lstrip().startswith("#") and not ln.lstrip().startswith("//")
    )


def shell_words(line):
    """One shell line as tokens, with real comments removed by a shell lexer."""
    try:
        return tuple(shlex.split(line, comments=True, posix=True))
    except ValueError:
        return ()


def compiler_project_closure(tree, root=SELFHOST_PROJECT,
                             problem_prefix=COMPILER_CLOSURE_PROBLEM):
    """Repo-local SourcePlan projects reachable through string `[deps]` paths.

    This is lexical and tree-backed so historical fixture Trees and in-memory
    mutants receive the same answer as the checked-out tree. SourcePlan also
    accepts fetched URL dependencies, but this bootstrap compiler closure is
    required to stay repo-local: an unfamiliar dependency form voids the map
    instead of being guessed into coverage.
    """
    projects = []
    problems = []
    visited = set()
    visiting = []
    names = {}

    def problem(detail):
        problems.append(f"{problem_prefix}: {detail}")

    def dependency_path(project, alias, raw):
        if not raw or any(ord(char) < 32 for char in raw):
            problem(f"{project}/dawn.toml dependency `{alias}` has an invalid path")
            return None
        if posixpath.isabs(raw):
            problem(
                f"{project}/dawn.toml dependency `{alias}` uses absolute path "
                f"`{raw}` rather than a repo-local path"
            )
            return None
        resolved = posixpath.normpath(posixpath.join(project, raw))
        if resolved == ".." or resolved.startswith("../"):
            problem(
                f"{project}/dawn.toml dependency `{alias}` escapes the repo "
                f"after lexical normalization: `{raw}` -> `{resolved}`"
            )
            return None
        return resolved

    def visit(project):
        if project in visiting:
            start = visiting.index(project)
            cycle = visiting[start:] + [project]
            problem("local dependency cycle: " + " -> ".join(cycle))
            return
        if project in visited:
            return

        manifest = f"{project}/dawn.toml"
        source = f"{project}/src"
        if manifest not in tree.fileset:
            problem(f"local dependency project `{project}` has no dawn.toml")
            return
        if source not in tree.dirs:
            problem(f"local dependency project `{project}` has no tracked src tree")
            return
        try:
            document = tomllib.loads(tree.read(manifest))
        except (tomllib.TOMLDecodeError, ValueError) as error:
            problem(f"cannot parse {manifest}: {error}")
            return
        if document.get("schema") != 1:
            problem(f"{manifest} does not declare supported schema 1")
            return
        name = document.get("name")
        if not isinstance(name, str) or VALID_DAWN_NAME.fullmatch(name) is None:
            problem(f"{manifest} does not declare a valid package name")
            return
        owner = names.get(name)
        if owner is not None and owner != project:
            problem(
                f"package `{name}` is reached from both `{owner}` and `{project}`"
            )
            return
        names[name] = project

        deps = document.get("deps", {})
        if not isinstance(deps, dict):
            problem(f"{manifest} has an unknown `[deps]` shape")
            return

        visiting.append(project)
        projects.append(project)
        for alias, raw in deps.items():
            if VALID_DAWN_NAME.fullmatch(alias) is None:
                problem(f"{manifest} has invalid dependency alias `{alias}`")
                continue
            if not isinstance(raw, str):
                problem(
                    f"{manifest} dependency `{alias}` is not a local path string"
                )
                continue
            child = dependency_path(project, alias, raw)
            if child is not None:
                visit(child)
        visiting.pop()
        visited.add(project)

    visit(root)
    return projects, problems


def compiler_input_records(tree, root=SELFHOST_PROJECT):
    """The tracked SourcePlan records that build the selfhost compiler.

    SourcePlan sorts records by kind and path. Every project contributes its
    required manifest and source tree, while the root lock remains an optional
    file record even when the Tree does not currently contain it. Keeping the
    record shape here lets rule D and `--compiler-inputs` consume one result.
    """
    projects, problems = compiler_project_closure(tree, root)
    if problems:
        return [], problems
    records = [("R", "F", f"{project}/dawn.toml") for project in projects]
    records.append(("R", "O", f"{root}/dawn.lock"))
    records.extend(("R", "T", f"{project}/src") for project in projects)
    return sorted(records), []


def compiler_inputs_text(tree):
    """A complete `dawn-source-inputs-v1` manifest, or closure problems."""
    records, problems = compiler_input_records(tree)
    if problems:
        return "", problems
    lines = [SOURCE_INPUTS_HEADER]
    lines.extend("\t".join(record) for record in records)
    return "\n".join(lines) + "\n", []


def resolve(cand, tree):
    """One token to the paths it names, expanding a glob against the tree."""
    hit = tree.resolved.get(cand)
    if hit is None:
        hit = tree.resolved[cand] = _resolve(cand, tree)
    return hit


def _resolve(cand, tree):
    cand = re.sub(r"^\./", "", cand.strip("\"'")).rstrip("/.,;:\"'")
    if not cand:
        return set()
    if "*" in cand:
        # A pattern whose first segment is all wildcard is not a gate stating
        # its input; it is shell syntax that happens to contain slashes. `*/.`
        # out of a case pattern in bootstrap-guards, and `**/*` out of a
        # `dest.glob()` call, each matched every top-level path in the
        # repository and briefly emptied the unwatched set. A map that says
        # everything is covered says nothing.
        head = cand.split("/")[0]
        if not head.strip("*"):
            return set()
        # `packages/*/dawn.toml`, `examples/*/`: a shell glob is how several gates state their input, so expand it
        # rather than dropping it.
        hit = {f for f in tree.files if fnmatch_path(f, cand)}
        hit |= {d for d in tree.dirs if fnmatch_path(d, cand)}
        return hit
    return {cand} if tree.exists(cand) else set()


def fnmatch_path(path, pattern):
    """`*` matches within one segment; the segment counts must line up."""
    p = path.split("/")
    q = pattern.split("/")
    if len(p) != len(q):
        return False
    import fnmatch as _fn

    return all(_fn.fnmatchcase(a, b) for a, b in zip(p, q))


def path_tokens(text, tree, bare=False):
    """Every token in `text` that names a file or directory in `tree`.

    `bare` also admits slash-free top-level directory names. Gates state their
    inputs that way often enough to matter (`dawn fmt compiler-plan std site
    selfhost packages examples --check` names seven roots with no slash between
    them, and package-tests.sh appends `playground` to its unit list the same
    way), but a word like `site` also occurs as ordinary English, so it is
    admitted only from lines that are not pure output.
    """
    found = set()
    for line in text.splitlines():
        # `"$root/scripts/delete-contract/run.sh"` names a path; the variable
        # in front of it is how a shell script spells "the repository". Without
        # this, three gates that call another gate's script through $root
        # looked as if they called nothing, and the scripts they call were
        # recorded as watched by nobody.
        line = re.sub(r"\$\{?\w+\}?/", "", line)
        for token in PATH_TOKEN.findall(line):
            found |= resolve(token, tree)
        if not bare or PRINTS_ONLY.match(line):
            continue
        for word in BARE_TOKEN.findall(line):
            if word in tree.dirs and "/" not in word:
                found.add(word)
        for flag, target in CLI_TARGET_ALIASES.items():
            if re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", line):
                found |= resolve(target, tree)
    return found


def shell_targets(text, tree):
    """Slash-free targets a shell gate names in the two places it can mean one.

    A bare word like `site` is ordinary English, so it is not admitted from
    running text; doing that put every file in the repository under some gate,
    which is the wrong direction to be wrong in. These two contexts are
    not English: a word handed to the toolchain, and a word appended to a list
    of units. `package-tests.sh` is the reason for the second; its whole
    exemption list is the line `units+=(playground)`.
    """
    found = set()
    for line in text.splitlines():
        if PRINTS_ONLY.match(line):
            continue
        contexts = []
        if re.search(r"(bin/dawn|\$\{?dawn\}?|\$\{?DAWN\w*\}?)", line):
            contexts.append(line)
        contexts += re.findall(r"\+?=\(([^)]*)\)", line)
        for context in contexts:
            for word in BARE_TOKEN.findall(context):
                if word in tree.dirs and "/" not in word:
                    found.add(word)
        for flag, target in CLI_TARGET_ALIASES.items():
            if contexts and re.search(
                r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", line
            ):
                found |= resolve(target, tree)
    return found


def python_inputs(text, tree):
    """Paths a Python gate script builds out of `ROOT / "a" / "b"` and reads
    with `.glob(...)` / `.rglob(...)`.

    doc-check.py states its whole subject that way (`(ROOT / "docs").rglob(
    "*.md")` and `ROOT.glob("*.md")`), so without this the documentation gate
    looks as if it watched nothing, and README.md would be recorded as a file
    no gate reads. Parsed rather than pattern-matched, because a regular
    expression over `/` operators cannot tell a path join from a division.
    """
    found = set()
    for kind, prefix, pattern in python_input_patterns(text):
        if kind == "rglob":
            found |= {
                f for f in tree.files if f.startswith(prefix)
                and fnmatch_path(f.rsplit("/", 1)[-1], pattern)
            }
        else:
            found |= resolve(prefix, tree)
    return found


@lru_cache(maxsize=256)
def python_input_patterns(text):
    """Parse once per script body; resolve paths against each Tree separately.

    A mutant may add or remove files without editing the glob's source. Only
    syntax is reusable across those trees, never the expanded input paths.
    """
    import ast

    try:
        tree_ast = ast.parse(text)
    except SyntaxError:
        return ()

    def joined(node):
        """`ROOT / "a" / "b"` -> "a/b"; a bare ROOT-like name -> "".

        A chain that ends in a variable (`ROOT / ".github" / "workflows" /
        name`) yields the constant prefix, because the directory is what the
        script declared and the file inside it is what it computed.
        """
        if isinstance(node, ast.Name):
            return ("", True) if node.id.lower().endswith("root") else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left = joined(node.left)
            if left is None:
                return None
            prefix, exact = left
            if isinstance(node.right, ast.Constant) and isinstance(
                node.right.value, str
            ):
                seg = node.right.value.strip("/")
                return (
                    (f"{prefix}/{seg}".lstrip("/"), exact) if seg else (prefix, exact)
                )
            return (prefix, False)
        return None

    # Only the longest chain in each expression. Reporting the intermediate
    # `ROOT / ".github"` of `ROOT / ".github" / "workflows" / name` put
    # .github/actions/dawn-toolchain/action.yml under the timeout checker,
    # which does not read it: over-claiming coverage is the failure this
    # directory exists to fix, so the inner joins are dropped.
    inner = set()
    for node in ast.walk(tree_ast):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            inner.add(id(node.left))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("glob", "rglob"):
                inner.discard(id(node.func.value))

    patterns = set()
    for node in ast.walk(tree_ast):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if id(node) in inner:
                continue
            base = joined(node)
            if base and base[0]:
                patterns.add(("path", base[0], ""))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr not in ("glob", "rglob"):
                continue
            base = joined(node.func.value)
            # `(ROOT / root).rglob("*.dawn")` walks whatever `root` is bound to
            # this iteration. A glob whose directory is a variable is not a
            # declared input, and reading it as one put every .dawn file in the
            # repository under the documentation job.
            if base is None or not base[1] or not node.args:
                continue
            arg = node.args[0]
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            pattern = arg.value
            prefix = base[0] + "/" if base[0] else ""
            if node.func.attr == "rglob":
                patterns.add(("rglob", prefix, pattern))
            else:
                patterns.add(("path", prefix + pattern, ""))
    return tuple(sorted(patterns))


# A gate is written in one of three languages, and the third one arrived as a
# blind spot rather than as a decision: the VS Code grammar contract is
# JavaScript, so `is_script` did not recognise it, rule B never read it, and the
# one gate that scrapes the compiler's lexer and token tables was absent from
# every answer this map gave about them. A lexer batch ran every gate listed for
# it, all green, and reddened one this map had never mentioned.
#
# `.mjs` and `.cjs` are the same language under Node's two module systems, and
# a gate is free to migrate between them: a rename that this tuple did not
# recognise would take the gate out of every answer, which is the failure
# above with a different spelling.
JS_SUFFIXES = (".js", ".mjs", ".cjs")
SCRIPT_SUFFIXES = (".sh", ".py") + JS_SUFFIXES


def is_script(path, tree):
    return path in tree.fileset and Path(path).suffix in SCRIPT_SUFFIXES


JS_STRING = re.compile(r"^\"((?:[^\"\\]|\\.)*)\"$|^'((?:[^'\\]|\\.)*)'$")

# The path module, under either module system and either of Node's two
# spellings of its name.
_JS_PATH_MODULE = r"""["'](?:node:)?path["']"""
JS_NAMESPACE_BIND = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*"
    + _JS_PATH_MODULE
    + r"\s*\)"
    r"|import\s+([A-Za-z_$][\w$]*)\s+from\s*" + _JS_PATH_MODULE
)
JS_MEMBER_BIND = re.compile(
    r"(?:const|let|var)\s*\{([^{}]*)\}\s*=\s*require\(\s*" + _JS_PATH_MODULE + r"\s*\)"
    r"|import\s*\{([^{}]*)\}\s*from\s*" + _JS_PATH_MODULE
)
JS_PATH_MENTION = re.compile(r"(?:require\(\s*|from\s*)" + _JS_PATH_MODULE)
JS_JOINERS = ("join", "resolve")

# The needle `js_binding_readable` watches for. A gate that reaches for this
# module in a spelling the reader below cannot follow has to say so: silence
# there is indistinguishable from a gate that names no paths at all, which is
# the state this map was in about the editor grammar contract for as long as it
# existed.
JS_UNREADABLE_BINDING = "reaches for the path module under a name this reader"


def js_path_callees(text):
    """-> the spellings of `join`/`resolve` this file bound, or an empty set.

    Read from the declaration rather than matched at the call, because `join(`
    on its own is a name any file may have its own function for, while
    `require("node:path")` says what it is. Both module systems and both
    binding forms are the same declared input:

        const path = require("node:path")      -> path.join, path.resolve
        const { join } = require("node:path")  -> join
        import path from "node:path"           -> path.join, path.resolve
        import { join } from "node:path"       -> join

    A binding that renames what it takes (`{ join: pjoin }`) is deliberately
    not followed. The caller turns an empty answer on a file that mentions the
    module into a problem, so the unfollowed spelling is loud rather than
    silently unread.
    """
    callees = set()
    for match in JS_NAMESPACE_BIND.finditer(text):
        name = match.group(1) or match.group(2)
        callees |= {f"{name}.{fn}" for fn in JS_JOINERS}
    for match in JS_MEMBER_BIND.finditer(text):
        for part in (match.group(1) or match.group(2)).split(","):
            if part.strip() in JS_JOINERS:
                callees.add(part.strip())
    return callees


def js_inputs(text, tree, script):
    """-> (paths a JavaScript gate builds out of path joins, problems).

    The same statement `ROOT / "a" / "b"` is in a Python gate, and read for the
    same reason: scope-contract.js names its whole subject that way, so without
    this the editor grammar job looks as if it read only its own directory and
    the compiler's lexer looks as if no editor gate watched it. Regular
    expressions are enough here where the Python side needed a parse: `/` is
    ambiguous with division and a declared join call is not.

    `__dirname` (`import.meta.dirname` under ESM) is the script's own
    directory, and a name bound to one of these calls is usable as the base of
    the next, which is how `ROOT` is spelled: `resolve(__dirname, "../../..")`.
    A base this cannot follow, or one that normalizes outside the repository,
    contributes nothing rather than contributing a guess.
    """

    def literal(arg):
        match = JS_STRING.match(arg.strip())
        if not match:
            return None
        return match.group(1) if match.group(1) is not None else match.group(2)

    callees = js_path_callees(text)
    if not callees:
        if JS_PATH_MENTION.search(text):
            return set(), [
                f"{script} {JS_UNREADABLE_BINDING} can follow, so every path it "
                "builds out of that module is missing from this map. Bind it as "
                "`const path = require(\"node:path\")` or "
                "`const { join } = require(\"node:path\")`, or teach "
                "js_path_callees the spelling"
            ]
        return set(), []
    call = re.compile(
        r"(?:(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*)?"
        r"(?:"
        + "|".join(re.escape(c) for c in sorted(callees, key=lambda c: (-len(c), c)))
        + r")\(([^()]*)\)"
    )
    script_dir = posixpath.dirname(script)
    env = {"__dirname": script_dir, "import.meta.dirname": script_dir}
    found = set()
    for match in call.finditer(text):
        name, raw = match.group(1), match.group(2)
        args = [a for a in raw.split(",") if a.strip()]
        if not args:
            continue
        base = env.get(args[0].strip())
        if base is None:
            continue
        # A chain that ends in a variable yields the constant prefix, for the
        # reason the Python reader gives: the directory is what the script
        # declared and the file inside it is what it computed.
        exact = True
        parts = [base] if base else []
        for arg in args[1:]:
            segment = literal(arg)
            if segment is None:
                exact = False
                break
            parts.append(segment)
        joined = posixpath.normpath("/".join(parts)) if parts else ""
        if joined in (".", "/"):
            joined = ""
        if joined.startswith("..") or joined.startswith("/"):
            continue
        if name and exact:
            env[name] = joined
        if joined:
            found |= resolve(joined, tree)
    return found, []


SEGMENT_SPLIT = re.compile(r"[\n;|&]+|\$\(|`|\(\s")
COMMAND_PREFIX = re.compile(
    r"^\s*(?:(?:if|then|else|elif|while|until|do|!|time|exec|command|bash|sh|"
    r"python3?|node|env|sudo|source|\.|\w+=\S*)\s+)*"
)

# The lifecycle names `npm <name>` accepts without `run`, which is the whole of
# what the gates here use.
NPM_LIFECYCLE = ("test", "start")
NPM_RUN = ("run", "run-script")


def npm_script(words, tree, workdir):
    """-> the command `npm test` in `workdir` is bound to, or None.

    A step whose command is `npm test` names no file, and the editor grammar
    contract is started exactly that way. The mapping from the lifecycle name
    to a command is in package.json, which is in the tree, so it is read rather
    than guessed. When it cannot be read the gate keeps only the coverage its
    working directory gives it, which is the under-claim this file prefers.
    `npm-run-stops-naming-the-contract` is the negative control for that
    boundary.
    """
    if not workdir or not words or words[0] != "npm":
        return None
    if len(words) > 1 and words[1] in NPM_LIFECYCLE:
        name = words[1]
    elif len(words) > 2 and words[1] in NPM_RUN:
        name = words[2]
    else:
        return None
    manifest = posixpath.join(workdir, "package.json")
    if manifest not in tree.fileset:
        return None
    try:
        scripts = json.loads(tree.read(manifest)).get("scripts")
    except (ValueError, AttributeError):
        return None
    if not isinstance(scripts, dict):
        return None
    body = scripts.get(name)
    return body if isinstance(body, str) else None


def executed_scripts(text, tree, workdir=None, seen=None):
    """Scripts this text *runs*, as opposed to ones it mentions.

    doc-check.py's docstring names scripts/native-cli-diff.sh while explaining
    a process-group rule. Reading that as "the documentation job runs the
    native CLI differential" put thirteen of the driver's usage strings under
    the wrong gate, so the token has to be in command position: first word of a
    segment, after the words that can precede a command.

    `workdir` is the step's `working-directory`, which is where a relative
    command resolves from and where the package.json an `npm` script goes
    through is. `seen` stops a package.json whose scripts call each other from
    recurring.
    """
    found = set()
    seen = set() if seen is None else seen
    for segment in SEGMENT_SPLIT.split(text):
        segment = re.sub(r"\$\{?\w+\}?/", "", segment)
        rest = COMMAND_PREFIX.sub("", segment)
        words = rest.strip().split()
        if not words:
            continue
        body = npm_script(words, tree, workdir)
        if body is not None:
            if body in seen:
                continue
            found |= executed_scripts(body, tree, workdir, seen | {body})
            continue
        cands = {words[0]}
        if workdir:
            cands.add(posixpath.join(workdir, words[0]))
        for cand in cands:
            for path in resolve(cand, tree):
                if is_script(path, tree):
                    found.add(path)
    return found


def unresolved_commands(text, tree):
    """First words that name a repository file and are not one.

    The discriminator between "this step runs nothing from the tree", which
    several release steps legitimately do while working on downloaded
    artifacts, and "this parser could not follow the step", which must never
    pass silently. A bare program name is on PATH; a word with a slash in it is a
    path, and a path that resolves to nothing is news.
    """
    bad = []
    for segment in SEGMENT_SPLIT.split(text):
        segment = re.sub(r"\$\{?\w+\}?/", "", segment)
        rest = COMMAND_PREFIX.sub("", segment).strip()
        word = rest.split()[:1]
        if not word:
            continue
        first = word[0].strip("\"'")
        # `JDK21_JAR=release-candidates/jdk-21/dawn-selfhost.jar` on a line of
        # its own is an assignment, not a command, and the path in it is a
        # build artifact rather than a tracked file.
        if re.match(r"^\w+=", first):
            continue
        if "/" not in first or "$" in first or first.startswith("-"):
            continue
        if not resolve(first, tree):
            bad.append(first)
    return bad


def gate_scripts(gate, tree, transitive=True):
    """The repository files a gate's commands execute, transitively.

    One gate's step calls another gate's directory: spike-native runs
    delete-contract/run.sh, lsp-lifecycle-contract runs lsp-lifecycle.py. A
    gate that stops at its own command line records those as watched by nobody,
    so the set is closed over the scripts each script runs.
    """
    direct = set()
    for command in gate.commands:
        direct |= executed_scripts(command, tree, gate.workdir)
    if not transitive:
        return direct
    scripts = set()
    frontier = set(direct)
    while frontier:
        script = frontier.pop()
        if script in scripts:
            continue
        scripts.add(script)
        if script in UNSCRAPED:
            continue
        body = strip_comments(tree.read(script))
        frontier |= {
            s for s in executed_scripts(body, tree) if s.startswith("scripts/")
        }
    return scripts


# ---- rule A, file by file --------------------------------------------------
#
# Rule A used to give a gate the whole directory of every script it runs. For
# a directory that is one gate's code that is the right answer, and for
# scripts/incremental-semantics-contract/, which holds 56 harnesses run by 69
# steps in 29 jobs, it made every file in it look like every job's code: #164
# touched four files that one job reads and the pull-request tier ran 30 of
# 39 jobs (#169).
#
# So a step now owns the files its scripts reach, read from the scripts:
#
#   * the script it runs, and every script that runs;
#   * the sibling modules they import (`import x`, `from x import y`, looked
#     up next to the importer and on any `sys.path` entry it adds) and the
#     files they `source`. An import executes the module's top level and the
#     functions the importer takes from it, so those are what it reaches:
#     cold.py copies the whole directory in its `main`, and the 39
#     harnesses that take `ROOT, edit, run` from it never call `main`;
#   * the files their code names inside the directory: `HERE / "x.dawn.txt"`,
#     `Path(__file__).with_name("x")`, `"$here/x"`, or a literal that is a
#     path relative to the directory (`("A.java", "B.java")`, a sibling
#     script handed to a subprocess). A named script is followed too, since
#     naming a sibling script is how a harness runs it.
#
# Whatever the reader cannot bound falls back to the old answer for that
# script, the whole directory: the directory used as a value (`copytree(HERE,
# ...)`, `cwd=HERE`, `HERE.glob(...)`, `cd "$here"`), a join whose name is
# computed (`HERE / f"{name}.txt"`, `"$here/$x"`), a file that does not parse,
# or a language this has no reader for. The fallback is per script, so one
# harness that walks its directory does not widen the forty that do not.
#
# A file in a harness directory that no step reaches after all of that is
# `unread`: every script that runs from that directory has been read and none
# of them names it. That is a README, a benchmark nobody runs in CI, or the
# template only that benchmark reads. It is still recorded in unseen.txt,
# under its own kind, and plan.py lets it select no job rather than every job,
# because here the empty answer is the measured one rather than a gap.

HARNESS_PARENT = "scripts/"
_PY_ALL = "*"


def harness_dir(path):
    """The directory under scripts/ a harness file lives in, or None."""
    parent = posixpath.dirname(path)
    return parent if parent.startswith(HARNESS_PARENT) else None


def _inside(path, directory):
    return path.startswith(directory + "/")


def _up(path, levels):
    parts = path.split("/") if path else []
    if levels > len(parts):
        return None
    return "/".join(parts[: len(parts) - levels])


def _join(base, segment):
    segment = segment.strip()
    if not segment or segment.startswith("/") or "\n" in segment:
        return None
    joined = posixpath.normpath(posixpath.join(base, segment) if base else segment)
    if joined == ".":
        return ""
    if joined == ".." or joined.startswith("../"):
        return None
    return joined


@lru_cache(maxsize=512)
def _py_parse(text):
    import ast

    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


class _Reach:
    """What one harness file reaches: files it reads, directories it reads as
    a whole (with the reason), and the script files whose text is its code."""

    def __init__(self):
        self.reads = {}
        self.whole = {}
        self.code = set()

    def merge(self, other, how=None):
        for path, why in other.reads.items():
            self.reads.setdefault(path, why if how is None else how)
        for path, why in other.whole.items():
            self.whole.setdefault(path, why)
        self.code |= other.code


class _PyModule:
    """One Python harness file, split into the units an importer can reach."""

    def __init__(self, reader, script):
        import ast

        self.script = script
        self.dir = posixpath.dirname(script)
        self.error = None
        self.env = {}
        self.defs = set()
        self.units = {}
        text = reader.tree.read(script)
        tree_ast = _py_parse(text)
        if tree_ast is None:
            self.error = "does not parse as Python"
            return
        self.ast = tree_ast
        parents = {}
        for node in ast.walk(tree_ast):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        self.parents = parents
        # Top-level units: each def or class, the `__main__` guard, and the
        # rest of the module, which an import always executes.
        self.unit_of = {}
        for stmt in tree_ast.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                unit = stmt.name
                self.defs.add(stmt.name)
            elif (
                isinstance(stmt, ast.If)
                and isinstance(stmt.test, ast.Compare)
                and isinstance(stmt.test.left, ast.Name)
                and stmt.test.left.id == "__name__"
            ):
                unit = "<main>"
            else:
                unit = "<module>"
            for node in ast.walk(stmt):
                self.unit_of[id(node)] = unit
            self.units.setdefault(unit, []).append(stmt)
        self.imports = []
        self.syspath_nodes = set()
        for node in ast.walk(tree_ast):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append((self.unit_of.get(id(node)), alias.name,
                                         None, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [a.name for a in node.names]
                self.imports.append((self.unit_of.get(id(node)), node.module,
                                     None if "*" in names else names, node.lineno))
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("insert", "append")
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "path"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "sys"
            ):
                for arg in node.args:
                    for sub in ast.walk(arg):
                        self.syspath_nodes.add(id(sub))
        # Loop variables over a literal tuple, so `HERE / n for n in ("A",
        # "B")` names A and B rather than reading as a computed join.
        self.loop_literals = {}
        for node in ast.walk(tree_ast):
            gens = []
            if isinstance(node, ast.For):
                gens.append((node.target, node.iter))
            elif isinstance(node, ast.comprehension):
                gens.append((node.target, node.iter))
            for target, it in gens:
                if (
                    isinstance(target, ast.Name)
                    and isinstance(it, (ast.Tuple, ast.List))
                    and it.elts
                    and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in it.elts
                    )
                ):
                    self.loop_literals.setdefault(target.id, set()).update(
                        e.value for e in it.elts
                    )
        # Top-level functions whose every `return` is a string literal (or a
        # conditional between two), so `HERE / matrix_name(scope)` names
        # what matrix_name can return rather than reading as computed.
        self.literal_returns = {}
        for stmt in tree_ast.body:
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            values = set()
            returns = [n for n in ast.walk(stmt) if isinstance(n, ast.Return)]
            for ret in returns:
                options = (
                    [ret.value.body, ret.value.orelse]
                    if isinstance(ret.value, ast.IfExp) else [ret.value]
                )
                if not all(
                    isinstance(o, ast.Constant) and isinstance(o.value, str)
                    for o in options
                ):
                    values = None
                    break
                values |= {o.value for o in options}
            if returns and values:
                self.literal_returns[stmt.name] = values
        self.module_files = {}

    def resolve_imports(self, reader):
        """Bind imported names, then this module's own path names."""
        import ast

        if self.error:
            return
        search = [self.dir]
        # sys.path entries need the env, and the env needs the imports; a
        # first pass over local bindings is enough for every spelling here.
        self._bind()
        for node in ast.walk(self.ast):
            if id(node) in self.syspath_nodes and isinstance(node, ast.expr):
                for path in self.value(node) or ():
                    if path in reader.tree.dirs and path not in search:
                        search.append(path)
        for unit, module, names, _line in self.imports:
            rel = module.replace(".", "/") + ".py"
            target = next(
                (f"{d}/{rel}" for d in search if f"{d}/{rel}" in reader.tree.fileset),
                None,
            )
            if target is None:
                continue
            self.module_files[module] = target
            other = reader.py_module(target)
            if other.error:
                continue
            for name in names or ():
                if name in other.env:
                    self.env[name] = self.env.get(name, frozenset()) | other.env[name]
        self._bind()

    def _bind(self):
        import ast

        for _ in range(3):
            for node in ast.walk(self.ast):
                if isinstance(node, ast.Assign):
                    targets, value = node.targets, node.value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    targets, value = [node.target], node.value
                else:
                    continue
                paths = self.value(value)
                if not paths:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.env[target.id] = self.env.get(target.id, frozenset()) | paths

    def value(self, node):
        """-> the repository paths an expression can denote, or None."""
        import ast

        if isinstance(node, ast.Name):
            if node.id == "__file__":
                return frozenset([self.script])
            return self.env.get(node.id)
        if isinstance(node, ast.Attribute):
            if node.attr == "parent":
                base = self.value(node.value)
                return self._each(base, lambda p: _up(p, 1))
            return None
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            if node.value.attr == "parents" and isinstance(node.slice, ast.Constant):
                k = node.slice.value
                if isinstance(k, int):
                    base = self.value(node.value.value)
                    return self._each(base, lambda p: _up(p, k + 1))
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            base = self.value(node.left)
            if not base:
                return None
            right = node.right
            if isinstance(right, ast.Constant) and isinstance(right.value, str):
                return self._each(base, lambda p: _join(p, right.value))
            if (
                isinstance(right, ast.IfExp)
                and all(
                    isinstance(b, ast.Constant) and isinstance(b.value, str)
                    for b in (right.body, right.orelse)
                )
            ):
                return frozenset(
                    j for p in base for b in (right.body, right.orelse)
                    if (j := _join(p, b.value)) is not None
                ) or None
            literals = None
            if isinstance(right, ast.Name) and right.id in self.loop_literals:
                literals = self.loop_literals[right.id]
            elif (
                isinstance(right, ast.Call)
                and isinstance(right.func, ast.Name)
                and right.func.id in self.literal_returns
            ):
                literals = self.literal_returns[right.func.id]
            if literals:
                return frozenset(
                    j for p in base for s in literals
                    if (j := _join(p, s)) is not None
                ) or None
            return None
        if isinstance(node, ast.Call):
            func = node.func
            args = node.args
            if isinstance(func, ast.Name) and func.id in ("Path", "PurePath", "str"):
                if len(args) == 1 and not node.keywords:
                    return self.value(args[0])
                return None
            if not isinstance(func, ast.Attribute):
                return None
            if (
                func.attr in ("Path", "PurePath")
                and isinstance(func.value, ast.Name)
                and func.value.id == "pathlib"
                and len(args) == 1
            ):
                return self.value(args[0])
            if func.attr in ("resolve", "absolute", "expanduser") and not args:
                return self.value(func.value)
            literal = (
                args[0].value
                if len(args) == 1
                and isinstance(args[0], ast.Constant)
                and isinstance(args[0].value, str)
                else None
            )
            if func.attr == "with_name" and literal is not None:
                base = self.value(func.value)
                return self._each(base, lambda p: _join(_up(p, 1) or "", literal))
            if func.attr == "with_suffix" and literal is not None:
                base = self.value(func.value)
                return self._each(
                    base, lambda p: posixpath.splitext(p)[0] + literal if p else None
                )
            if func.attr == "joinpath" and args and all(
                isinstance(a, ast.Constant) and isinstance(a.value, str) for a in args
            ):
                base = self.value(func.value)
                return self._each(base, lambda p: _join(p, "/".join(a.value for a in args)))
            is_os_path = (
                isinstance(func.value, ast.Attribute)
                and func.value.attr == "path"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            )
            if is_os_path and len(args) >= 1:
                if func.attr in ("abspath", "realpath", "normpath") and len(args) == 1:
                    return self.value(args[0])
                if func.attr == "dirname" and len(args) == 1:
                    return self._each(self.value(args[0]), lambda p: _up(p, 1))
                if func.attr == "join" and all(
                    isinstance(a, ast.Constant) and isinstance(a.value, str)
                    for a in args[1:]
                ):
                    base = self.value(args[0])
                    return self._each(
                        base, lambda p: _join(p, "/".join(a.value for a in args[1:]))
                    )
        return None

    @staticmethod
    def _each(base, step):
        if not base:
            return None
        out = frozenset(r for p in base if (r := step(p)) is not None)
        return out or None

    def facts(self, reader, unit):
        """-> (reads {path: line}, whole {dir: reason}, refs) for one unit."""
        import ast

        reads, whole, refs = {}, {}, set()
        tree = reader.tree
        stmts = self.units.get(unit, [])
        for stmt in stmts:
            for node in ast.walk(stmt):
                line = getattr(node, "lineno", 0)
                if isinstance(node, ast.Name) and node.id in self.defs:
                    refs.add(node.id)
                if not isinstance(node, ast.expr):
                    continue
                parent = self.parents.get(id(node))
                if isinstance(node, ast.JoinedStr):
                    self._computed(node, line, reads, whole, tree)
                    continue
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and not isinstance(parent, ast.JoinedStr)
                ):
                    # A literal used as a join segment is the join's business.
                    joined = isinstance(parent, ast.BinOp) and parent.right is node
                    called = isinstance(parent, ast.Call) and isinstance(
                        parent.func, ast.Attribute
                    ) and parent.func.attr in ("with_name", "with_suffix", "joinpath", "join")
                    if not joined and not called:
                        self._literal(node.value, line, reads, whole, tree)
                    continue
                if id(node) in self.syspath_nodes:
                    continue
                if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
                    continue
                paths = self.value(node)
                if not paths:
                    continue
                # Only the outermost expression that is still a path counts:
                # `HERE` inside `HERE / "x"` is the join's base, and
                # `Path(__file__)` inside `.with_name("x")` is the call's.
                if self._inner(node):
                    continue
                binding = isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is node
                walker = (
                    isinstance(parent, ast.Attribute)
                    and parent.attr in ("glob", "rglob", "iterdir", "walk", "with_name",
                                        "with_suffix", "joinpath")
                )
                for path in paths:
                    if path == self.dir or (walker and path == self.script):
                        if binding and path == self.dir:
                            continue
                        whole.setdefault(
                            self.dir,
                            f"{self.script}:{line} uses its directory as a value "
                            f"(`{ast.unparse(parent if walker else node)[:60]}`)",
                        )
                    elif _inside(path, self.dir) and tree.exists(path):
                        reads.setdefault(path, line)
        return reads, whole, refs

    def _inner(self, node):
        """Whether an enclosing expression is still a path, so `node` is a
        base rather than the thing read: `HERE` in `HERE / "x"`, in
        `HERE.parents[1]`, and `Path(__file__)` in `.with_name("x")`."""
        import ast

        child = node
        parent = self.parents.get(id(node))
        while isinstance(parent, ast.expr):
            if self.value(parent):
                return True
            chained = (
                (isinstance(parent, ast.Attribute) and parent.value is child)
                or (isinstance(parent, ast.Subscript) and parent.value is child)
                or (isinstance(parent, ast.Call) and parent.func is child)
            )
            if not chained:
                return False
            child, parent = parent, self.parents.get(id(parent))
        return False

    def _computed(self, node, line, reads, whole, tree):
        """`ROOT / f"scripts/x/sam_{name}.dawn"`: a name computed under a
        constant prefix reads the directory that prefix ends in."""
        import ast

        prefix = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                prefix += part.value
            else:
                break
        parent = self.parents.get(id(node))
        head = prefix.rsplit("/", 1)[0] if "/" in prefix else ""
        if isinstance(parent, ast.BinOp) and parent.right is node:
            bases = self.value(parent.left) or ()
        elif head and _join("", head):
            # Standalone, it is a path only if its constant head is one.
            bases = ("", self.dir)
        else:
            return
        for base in bases:
            where = _join(base, head) if head else base
            if where is None:
                continue
            if where == self.dir:
                whole.setdefault(
                    self.dir, f"{self.script}:{line} computes a name in its "
                    f"directory (`{ast.unparse(node)[:60]}`)"
                )
            elif _inside(where, self.dir) and tree.exists(where):
                reads.setdefault(where, line)

    def _literal(self, text, line, reads, whole, tree):
        text = text.strip()
        if not text or len(text) > 200 or "\n" in text:
            return
        for cand in (_join(self.dir, text), _join("", text)):
            if cand is None:
                continue
            if cand == self.dir and cand == _join("", text):
                whole.setdefault(
                    self.dir, f"{self.script}:{line} names its own directory, "
                    f"`{text}`, as a value"
                )
            elif _inside(cand, self.dir) and tree.exists(cand):
                reads.setdefault(cand, line)


class HarnessReader:
    """File-level rule A over one Tree. Memoised per tree, because a mutant
    Tree is a different tree even where its text is the same."""

    def __init__(self, tree):
        self.tree = tree
        self._py = {}
        self._reach = {}

    def py_module(self, script):
        mod = self._py.get(script)
        if mod is None:
            mod = self._py[script] = _PyModule(self, script)
            mod.resolve_imports(self)
        return mod

    def reach(self, script, units=_PY_ALL, stack=()):
        key = (script, units if units == _PY_ALL else frozenset(units))
        if key in self._reach:
            return self._reach[key]
        out = _Reach()
        if script in stack:
            return out
        stack = stack + (script,)
        out.code.add(script)
        directory = posixpath.dirname(script)
        suffix = Path(script).suffix
        if suffix == ".py":
            self._reach_py(script, units, out, stack)
        elif suffix == ".sh":
            self._reach_sh(script, out, stack)
        else:
            out.whole.setdefault(
                directory, f"{script} is `{suffix or 'extensionless'}`, which "
                "this map has no reader for"
            )
        self._reach[key] = out
        return out

    C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)

    def _follow(self, path, out, stack, how):
        """A named file: read it, run it if it is a script, and take the
        headers a C file includes by quoted name."""
        if path in out.reads:
            return
        out.reads[path] = how
        if path not in self.tree.fileset:
            return
        suffix = Path(path).suffix
        if suffix in SCRIPT_SUFFIXES:
            out.merge(self.reach(path, _PY_ALL, stack), how)
        elif suffix in (".c", ".h"):
            base = posixpath.dirname(path)
            for header in self.C_INCLUDE.findall(self.tree.read(path)):
                target = _join(base, header)
                if target and target in self.tree.fileset:
                    self._follow(
                        target, out, stack,
                        f"{posixpath.basename(path)} includes it",
                    )

    def _reach_py(self, script, units, out, stack):
        mod = self.py_module(script)
        name = posixpath.basename(script)
        if mod.error:
            out.whole.setdefault(mod.dir, f"{script} {mod.error}")
            return
        if units == _PY_ALL:
            todo = set(mod.units)
        else:
            todo = {"<module>"} | {u for u in units if u in mod.units}
        done = set()
        while todo:
            unit = todo.pop()
            if unit in done:
                continue
            done.add(unit)
            reads, whole, refs = mod.facts(self, unit)
            for path, line in reads.items():
                self._follow(path, out, stack, f"{name}:{line} names it")
            for path, why in whole.items():
                out.whole.setdefault(path, why)
            todo |= {r for r in refs if r in mod.units} - done
        for unit, module, names, _line in mod.imports:
            if unit not in done:
                continue
            target = mod.module_files.get(module)
            if target is None:
                continue
            out.reads.setdefault(target, f"{name} imports `{module}`")
            other = self.py_module(target)
            take = _PY_ALL if names is None else (
                [n for n in names if n in other.defs] or ["<module>"]
            )
            out.merge(self.reach(target, take, stack), f"{name} imports `{module}`")

    SH_ASSIGN = re.compile(
        r"^\s*(?:local\s+|readonly\s+|export\s+|declare\s+(?:-\w+\s+)?)?(\w+)=(.*)$"
    )
    SH_SELF_DIR = re.compile(
        r"dirname\s+\$\{?(?:BASH_SOURCE(?:\[0\])?|0)\}?\s*\)((?:/\.\.)*)"
    )
    SH_USE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
    SH_SEGMENT = re.compile(r"/([\w.@+,=-]+(?:/[\w.@+,=-]+)*)(/?)(.?)")

    def _reach_sh(self, script, out, stack):
        tree = self.tree
        directory = posixpath.dirname(script)
        name = posixpath.basename(script)
        text = strip_comments(tree.read(script))
        lines = [ln.replace('"', "").replace("'", "") for ln in text.splitlines()]
        env = {}
        binding_lines = set()
        for _ in range(2):
            for n, ln in enumerate(lines):
                m = self.SH_ASSIGN.match(ln)
                if not m:
                    continue
                var, rhs = m.group(1), m.group(2).strip()
                value = None
                self_dir = self.SH_SELF_DIR.search(rhs)
                if self_dir:
                    value = _up(directory, self_dir.group(1).count("/.."))
                else:
                    ref = re.match(r"^\$\{?(\w+)\}?(?:/([\w.@+/-]+))?/?$", rhs)
                    if ref and ref.group(1) in env:
                        value = next(iter(env[ref.group(1)]))
                        if ref.group(2):
                            value = _join(value, ref.group(2))
                    elif re.fullmatch(r"(?:\./)?[\w.@+-]+(?:/[\w.@+-]+)*/?", rhs):
                        literal = _join("", rhs)
                        if literal is not None and literal in tree.dirs:
                            value = literal
                if value is not None:
                    env[var] = env.get(var, frozenset()) | {value}
                    binding_lines.add(n)
        for n, ln in enumerate(lines):
            line_no = n + 1
            spans = []
            for m in self.SH_USE.finditer(ln):
                var = m.group(1) or m.group(2)
                if var in env:
                    spans.append((m.end(), env[var]))
            for m in re.finditer(
                r"\$\(dirname\s+\$\{?(?:BASH_SOURCE(?:\[0\])?|0)\}?\)|\$\{BASH_SOURCE(?:\[0\])?%/\*\}",
                ln,
            ):
                spans.append((m.end(), frozenset([directory])))
            for end, values in spans:
                seg = self.SH_SEGMENT.match(ln, end)
                for base in values:
                    if seg:
                        path = _join(base, seg.group(1))
                        dynamic = seg.group(3) in ("$", "*", "?", "[", "{") or (
                            seg.group(2) == "/" and seg.group(3) in ("$", "*", "?", "[", "{")
                        )
                    else:
                        path, dynamic = base, False
                    if path is None:
                        continue
                    if path == directory:
                        if n in binding_lines:
                            continue
                        out.whole.setdefault(
                            directory,
                            f"{script}:{line_no} uses its directory as a value "
                            f"(`{ln.strip()[:60]}`)",
                        )
                    elif _inside(path, directory) and tree.exists(path):
                        if dynamic and path in tree.fileset:
                            path = posixpath.dirname(path)
                            if path == directory:
                                out.whole.setdefault(
                                    directory,
                                    f"{script}:{line_no} computes a name in its "
                                    f"directory (`{ln.strip()[:60]}`)",
                                )
                                continue
                        self._follow(path, out, stack, f"{name}:{line_no} names it")
                    elif (
                        re.match(r"^\s*(?:source|\.)\s", ln)
                        and path in tree.fileset
                        and Path(path).suffix == ".sh"
                    ):
                        self._follow(path, out, stack, f"{name}:{line_no} sources it")
            # Literal paths: repository-relative tokens, and words that are a
            # path relative to this directory.
            for word in re.findall(r"[\w.@+-]+(?:/[\w.@+-]+)*", SH_VAR_PREFIX.sub("", ln)):
                for cand in (_join(directory, word), _join("", word)):
                    if cand is None:
                        continue
                    if cand == directory and cand == _join("", word):
                        if n not in binding_lines:
                            out.whole.setdefault(
                                directory,
                                f"{script}:{line_no} names its own directory "
                                f"as a value (`{ln.strip()[:60]}`)",
                            )
                    elif _inside(cand, directory) and tree.exists(cand):
                        self._follow(cand, out, stack, f"{name}:{line_no} names it")


SH_VAR_PREFIX = re.compile(r"\$\{?\w+\}?/")


class Observation:
    def __init__(self, level, gate_id, why, tag_only=False):
        self.level = level
        self.gate_id = gate_id
        self.why = why
        self.tag_only = tag_only

    def key(self):
        return (LEVELS.index(self.level), self.gate_id, self.why)


class Map:
    def __init__(self, tree):
        self.tree = tree
        self.gates = gates_of(tree)
        self.by_path = {}
        self.owned = {}
        self.direct = {}
        self.problems = []
        self.std_modules = std_module_paths(tree.read(STD_MODULE_INDEX))
        self.std_module_observation = None
        self.harness = HarnessReader(tree)
        # harness directory -> the steps that run a script from it
        self.harness_users = {}
        # harness directory -> {script: why it fell back to the whole directory}
        self.fallback = {}
        # files some step's scripts reach, and the harness files none does
        self.reached = set()
        self.unread = {}
        self._build()

    def add(self, path, obs):
        self.by_path.setdefault(path, []).append(obs)

    def add_under(self, prefix, obs):
        for f in self.tree.under(prefix):
            self.add(f, obs)

    def project_inputs(self, token, command):
        """The SourcePlan inputs of a harness directory the toolchain is
        handed as a project, or None to read the whole path.

        `./bin/dawn test scripts/incremental-semantics-contract` compiles that
        directory's manifest and src tree and the local projects they reach,
        which is what `compiler_input_records` says a SourcePlan project
        contributes; the fifty Python harnesses beside them are not its input.
        Limited to directories under scripts/, where the directory is also a
        harness's own; anywhere else the old whole-path answer stands. A
        closure that cannot be derived keeps the whole path too.
        """
        tree = self.tree
        if (
            not token.startswith(HARNESS_PARENT)
            or token not in tree.dirs
            or f"{token}/{MANIFEST}" not in tree.fileset
            or not re.search(r"(^|[\s/])bin/dawn\b", command)
        ):
            return None
        projects, problems = compiler_project_closure(
            tree, token, f"project inputs of {token}"
        )
        if problems:
            return None
        inputs = []
        for project in projects:
            inputs += [f"{project}/{MANIFEST}", f"{project}/src"]
            if f"{project}/dawn.lock" in tree.fileset:
                inputs.append(f"{project}/dawn.lock")
        return inputs

    # ---- rule A + B ---------------------------------------------------
    def _rule_ab(self):
        tree = self.tree
        for gate in self.gates:
            scripts = gate_scripts(gate, tree)
            self.owned[gate.id] = set()
            self.direct[gate.id] = {
                str(Path(s).parent)
                if str(Path(s).parent).startswith("scripts/")
                else s
                for s in gate_scripts(gate, tree, transitive=False)
            }
            for command in gate.commands:
                for bad in unresolved_commands(command, tree):
                    self.problems.append(
                        f"{gate.where()} ({gate.id}): `{bad}` looks like a path "
                        "into this repository and names nothing in it. Either "
                        "the file moved or this parser cannot read the step"
                    )
            for script in sorted(scripts):
                # A: the gate runs this script. Outside scripts/ it owns only
                # itself: `site/build.sh` is not site/'s code, and marking the
                # whole directory exact would say a page's text is recorded
                # byte for byte somewhere. Under scripts/ it owns what the
                # script reaches, file by file (see HarnessReader), and the
                # whole directory only where the reader cannot bound that.
                owner = str(Path(script).parent)
                harness = owner.startswith(HARNESS_PARENT)
                self.owned[gate.id].add(owner if harness else script)
                runs = f"{gate.where()} runs {script}"
                if harness:
                    reach = self.harness.reach(script)
                    self.harness_users.setdefault(owner, set()).add(gate.id)
                    exact = {script: runs}
                    for path, how in sorted(reach.reads.items()):
                        for f in tree.under(path):
                            exact.setdefault(f, f"{runs}; {how}")
                    for directory, why in sorted(reach.whole.items()):
                        self.fallback.setdefault(directory, {}).setdefault(script, why)
                        for f in tree.under(directory):
                            exact.setdefault(
                                f, f"{runs}; {why}, so the whole directory is "
                                "its code"
                            )
                    code = set(reach.code)
                    for directory in reach.whole:
                        code |= {
                            f for f in tree.under(directory)
                            if Path(f).suffix in SCRIPT_SUFFIXES
                        }
                    # A harness's own directory is read by the reader above;
                    # rule B below must not hand it back whole.
                    own = {posixpath.dirname(c) for c in code if harness_dir(c)}
                else:
                    exact = {script: runs}
                    code = {script}
                    own = set()
                for path, why in exact.items():
                    self.reached.add(path)
                    self.add(path, Observation("exact", gate.id, why, gate.tag_only))
                # B: whatever that code names.
                body = "".join(
                    strip_comments(tree.read(c)) + "\n"
                    for c in sorted(code)
                    if c not in UNSCRAPED and Path(c).suffix in SCRIPT_SUFFIXES
                )
                names = path_tokens(body, tree) | shell_targets(body, tree)
                for c in sorted(code):
                    if Path(c).suffix == ".py" and c not in UNSCRAPED:
                        names |= python_inputs(tree.read(c), tree)
                if Path(script).suffix in JS_SUFFIXES:
                    named, unreadable = js_inputs(tree.read(script), tree, script)
                    names |= named
                    self.problems += unreadable
                for token in sorted(names):
                    if any(token == d or _inside(token, d) for d in own):
                        continue
                    self.add_under(
                        token,
                        Observation(
                            "coarse",
                            gate.id,
                            f"{script} names {token}",
                            gate.tag_only,
                        ),
                    )
            for command in gate.commands:
                named = path_tokens(command, tree) | shell_targets(command, tree)
                for token in sorted(named):
                    if token in tree.fileset and Path(token).suffix in SCRIPT_SUFFIXES:
                        continue
                    obs = Observation(
                        "coarse",
                        gate.id,
                        f"{gate.where()} runs `{command.strip()}`",
                        gate.tag_only,
                    )
                    inputs = self.project_inputs(token, command)
                    if inputs is None:
                        self.add_under(token, obs)
                    else:
                        for path in inputs:
                            self.add_under(path, obs)
                            self.reached.update(tree.under(path))
            if SELF in scripts:
                # Rule B cannot read this file (see SELF), so the evidence it
                # does read is attributed from the declaration instead.
                for rel in SELF_INPUTS + tuple(
                    f".github/workflows/{w}" for w in WORKFLOWS
                ):
                    if not tree.exists(rel):
                        continue
                    self.add(
                        rel,
                        Observation(
                            "coarse",
                            gate.id,
                            f"{SELF} reads {rel} to derive its rules",
                            gate.tag_only,
                        ),
                    )
            if gate.workdir and tree.exists(gate.workdir):
                self.add_under(
                    gate.workdir,
                    Observation(
                        "coarse",
                        gate.id,
                        f"{gate.where()} runs in {gate.workdir}",
                        gate.tag_only,
                    ),
                )

    # ---- rule C -------------------------------------------------------
    def core_gate(self):
        for gate in self.gates:
            if any(CORE_DIFF in c for c in gate.commands):
                return gate
        return None

    def compiler_modules(self):
        """Module name -> source path, for every compiler module in the tree.

        Derived from the tree's own files. It used to be read out of the Core
        golden, which made the golden the list of compiler modules and every
        module added or removed a re-record; the tree already says which
        modules there are.
        """
        out = {}
        for f in self.tree.files:
            if f.startswith("selfhost/src/") and f.endswith(".dawn"):
                out[f[len("selfhost/src/"):-len(".dawn")].replace("/", ".")] = f
        return out

    def _rule_c(self):
        # No step runs the Core diff on a tree after 2026-09-25, and that is not
        # a void premise: the diff became an on-demand tool, and a compiler
        # module having no `exact` gate is what the map should then say.
        gate = self.core_gate()
        if gate is None:
            return
        for module, path in sorted(self.compiler_modules().items()):
            self.add(
                path,
                Observation(
                    "exact",
                    gate.id,
                    f"the Core IR diff dumps compiler module `{module}`",
                ),
            )

    # ---- rule D -------------------------------------------------------
    def gate_running(self, script):
        """The first gate step whose own command line runs this script."""
        for gate in self.gates:
            if any(script in c for c in gate.commands):
                return gate
        return None

    def label_owners(self):
        """-> [(script, gate or None, [label, ...])].

        The table that says which differential can see which declared change.
        `prev-diff` names a job with four differentials in it, so the gate is
        reported as the step rather than the job.
        """
        out = []
        for script, labels in label_sections(self.tree.read(EMIT_LABELS)):
            out.append((script, self.gate_running(script), labels))
        return out

    def _rule_d(self):
        tree = self.tree
        script = PREV_DIFF
        labels = tree.read(EMIT_LABELS)
        body = tree.read(script)
        gate = self.gate_running(script)
        if gate is None or not labels or not body:
            self.problems.append(
                f"rule D's inputs are missing: it needs {EMIT_LABELS}, "
                f"{script}, and a workflow step that runs it"
            )
            return

        # The premises. Each is a sentence rule D depends on; if one stops
        # being true in the tree the rule is wrong rather than merely old.
        #
        # The first is why a corpus target is blind: exactly one prev output
        # leg and one head output leg emit the same `$t`, out of the same
        # working tree, into their respective directories. The executable on
        # the head output leg is deliberately not part of this premise. Even
        # if that leg accidentally ran PREV, the corpus's own content would
        # still occur on both sides and cancel.
        commands = [shell_words(ln) for ln in body.splitlines()]
        prev_output_legs = [words for words in commands if words == PREV_EMIT_WORDS]
        head_output_legs = [
            words
            for words in commands
            if len(words) == len(HEAD_EMIT_TAIL) + 1
            and words[1:] == HEAD_EMIT_TAIL
        ]
        if len(prev_output_legs) != 1 or len(head_output_legs) != 1:
            self.problems.append(
                f"{script} no longer has exactly one prev output leg and one "
                "head output leg that each emit the same `$t` into "
                "`$OUT/prev/$t` and `$OUT/head/$t`; a corpus target's own "
                "content no longer provably cancels, so rule D's blind "
                "conclusion is void"
            )
            return

        head_bins = [
            ln.strip()
            for ln in body.splitlines()
            if ln.strip().startswith("HEAD_BIN=")
        ]
        head_compiler_legs = [words for words in commands if words == HEAD_EMIT_WORDS]
        head_is_current = (
            head_bins == [HEAD_BIN_ASSIGNMENT] and len(head_compiler_legs) == 1
        )
        if not head_is_current:
            self.problems.append(
                f"{script} must assign `{HEAD_BIN_ASSIGNMENT}` exactly once "
                "and its head output leg must exactly call "
                "`\"${HEAD_BIN[@]}\" __emit \"$t\"`; comments and variable "
                "names are not evidence that the selfhost compiler runs, so "
                "rule D's HEAD compiler premise is void"
            )

        if "PREV_STD" not in body or "--std" not in body:
            self.problems.append(
                f"{script} no longer points the N-1 toolchain at its own std "
                "(PREV_STD / --std), so 'std is visible to prev-diff' is no "
                "longer derivable; rule D is void"
            )
            return

        targets = emit_targets(labels)
        if not targets:
            self.problems.append(
                f"{EMIT_LABELS} lists no `emit <target>` label under "
                f"`# ---- {script} ----`, so rule D has no corpus. Either the "
                "section header moved or the differential stopped naming its "
                "targets"
            )
            return
        if "std" in targets:
            self.problems.append(
                "`emit std` is now a label: std is compiled as a corpus target, "
                "so rule D's exception for it no longer follows; re-derive it"
            )
            return

        compiler_inputs, closure_problems = compiler_input_records(tree)
        self.problems.extend(closure_problems)

        for target in targets:
            if not tree.exists(target):
                self.problems.append(
                    f"emit-labels.txt names corpus target `{target}`, which is "
                    "not in the tree"
                )
                continue
            if target == "selfhost":
                blind_why = (
                    "`emit selfhost` compiles this same source in both output "
                    "legs, so selfhost's own corpus source content cancels "
                    "between them"
                )
            else:
                blind_why = (
                    f"`emit {target}` compiles this same source in both output "
                    f"legs, so {target}'s own corpus source content cancels "
                    "between them"
                )
            self.add_under(
                target,
                Observation(
                    "blind",
                    gate.id,
                    blind_why,
                ),
            )
        if head_is_current and not closure_problems:
            compiler_why = (
                HEAD_COMPILER_REASON + ". Local string `[deps]` are followed "
                "recursively; each project contributes dawn.toml and src, "
                "and only the root contributes dawn.lock. Changes in this "
                "derived closure can move any `emit ...` label, including "
                "`emit selfhost`; decide declarations from the real "
                "differential or an unmasked true-parent control"
            )
            for _, kind, path in compiler_inputs:
                if kind == "T":
                    self.add_under(
                        path,
                        Observation("coarse", gate.id, compiler_why),
                    )
                elif path in tree.fileset:
                    self.add(
                        path,
                        Observation("coarse", gate.id, compiler_why),
                    )
        self.add_under(
            "std",
            Observation(
                "exact",
                gate.id,
                "the N-1 side compiles the std it was released with "
                f"({script} PREV_STD), so std source moves the emitted bytes "
                "and needs an Emit-Change declaration",
            ),
        )

    # ---- rule E -------------------------------------------------------
    def gate_owning(self, script):
        """The gate whose own code a script is, by rule A's ownership.

        A gate that runs the script from its own step wins over one that
        reaches it through another script.
        """
        for direct_only in (True, False):
            for gate in self.gates:
                pool = self.direct if direct_only else self.owned
                for owned in pool.get(gate.id, ()):
                    if script == owned or script.startswith(owned + "/"):
                        return gate
        return None

    def _rule_e(self):
        for src, script, literal in couplings(self.tree):
            gate = self.gate_owning(script)
            self.add(
                src,
                Observation(
                    "coupled",
                    gate.id if gate else f"(no gate runs) {script}",
                    f"{script} spells out {literal!r}, which this file builds. "
                    "Rewrite the sentence here and that assertion reds, from "
                    "another directory.",
                    gate.tag_only if gate else False,
                ),
            )

    # ---- rule F -------------------------------------------------------
    def _rule_f(self):
        """The checker golden records the modules selected by modules.txt.

        Rule B cannot derive this edge: the checker script names its golden,
        but it has no reason to name the index that built the compiler's env.
        A removed path is also absent from Tree.files. Keep the observations
        only while all three parts of the evidence remain readable.
        """
        gate = self.gate_running(CHECKER_CORPUS)
        if gate is None:
            self.problems.append(
                f"no workflow step runs {CHECKER_CORPUS}, so the bundled std "
                "module-set rule has no gate to attribute; rule F is void"
            )

        source_lines = [
            n
            for n, line in enumerate(
                self.tree.read(BUNDLED_MODULE_DIAGNOSTIC).splitlines(), 1
            )
            if BUNDLED_MODULE_EXPRESSION in line
        ]
        if len(source_lines) != 1:
            self.problems.append(
                f"{BUNDLED_MODULE_DIAGNOSTIC} has {len(source_lines)} copies "
                "of the sorted bundled-module diagnostic expression, not "
                "one; rule F is void"
            )

        golden_lines = [
            n
            for n, line in enumerate(
                self.tree.read(CHECKER_CORPUS_GOLDEN).splitlines(), 1
            )
            if BUNDLED_MODULE_GOLDEN_TEXT in line
        ]
        if len(golden_lines) != 1:
            self.problems.append(
                f"{CHECKER_CORPUS_GOLDEN} has {len(golden_lines)} recorded "
                "bundled-module diagnostics, not one; rule F is void"
            )

        if gate is None or len(source_lines) != 1 or len(golden_lines) != 1:
            return

        module_observation = Observation(
            "exact",
            gate.id,
            f"{STD_MODULE_INDEX} lists this path in the relevant tree's "
            f"bundled-module set; {BUNDLED_MODULE_DIAGNOSTIC}:"
            f"{source_lines[0]} prints that sorted set into a diagnostic that "
            f"{CHECKER_CORPUS_GOLDEN}:{golden_lines[0]} records",
            gate.tag_only,
        )
        index_observation = Observation(
            "exact",
            gate.id,
            f"{STD_MODULE_INDEX} selects the bundled-module set that "
            f"{BUNDLED_MODULE_DIAGNOSTIC}:{source_lines[0]} prints into a "
            f"diagnostic and {CHECKER_CORPUS_GOLDEN}:{golden_lines[0]} records",
            gate.tag_only,
        )
        self.std_module_observation = module_observation
        self.add(STD_MODULE_INDEX, index_observation)
        for path in self.std_modules:
            self.add(path, module_observation)

    # ---- rule G -------------------------------------------------------
    def _rule_g(self):
        for src, script, sig in signature_couplings(self.tree):
            gate = self.gate_owning(script)
            one_line = " ".join(sig.split())
            self.add(
                src,
                Observation(
                    "coupled",
                    gate.id if gate else f"(no gate runs) {script}",
                    f"{script} spells out {one_line!r}, which is this file's "
                    "own declaration. Change the row here and that harness "
                    "stops finding what it rewrites, from another directory.",
                    gate.tag_only if gate else False,
                ),
            )

    def _build(self):
        self._rule_ab()
        self._harness_unread()
        self._rule_c()
        self._rule_d()
        self._rule_e()
        self._rule_f()
        self._rule_g()
        self._rule_h()

    def _harness_unread(self):
        """Files in a harness directory that no step's scripts reach.

        Every script a step runs from that directory has been read, and none
        of them names these. They are not attributed to anybody: a README, a
        benchmark CI does not run, the template only that benchmark reads.
        """
        for directory, users in sorted(self.harness_users.items()):
            for path in self.tree.under(directory):
                if path in self.reached or path in self.unread:
                    continue
                self.unread[path] = (
                    f"{len(users)} step(s) run scripts from {directory}, and "
                    "no script they run imports, sources or names this file"
                )

    def _rule_h(self):
        """Propagate observed example inputs through their manifest closure.

        Only manifest/src are compiled inputs of a dependency; attributing its
        whole directory would falsely claim its own tests and docs are run.
        Read from Tree so mutants and historical fixtures see their own deps.
        """
        compiling = set()
        for script, invocation in EXAMPLE_COMPILERS.items():
            gate = self.gate_running(script)
            if gate is None:
                continue
            if invocation not in strip_comments(self.tree.read(script)):
                self.problems.append(
                    f"example input closure is void: {script} no longer "
                    f"contains its compilation premise {invocation!r}"
                )
                continue
            compiling.add(gate.id)
        for manifest in self.tree.files:
            parts = manifest.split("/")
            if (len(parts) != 4 or parts[0] != "examples"
                    or parts[-1] != "dawn.toml"):
                continue
            observed = {
                (obs.gate_id, obs.tag_only)
                for obs in self.by_path.get(manifest, ())
                if obs.level == "coarse" and obs.gate_id in compiling
            }
            if not observed:
                continue
            root = posixpath.dirname(manifest)
            projects, problems = compiler_project_closure(
                self.tree, root, f"example input closure is void for {root}"
            )
            self.problems.extend(problems)
            if problems:
                continue
            for project in projects:
                if project == root:
                    continue
                for gate_id, tag_only in sorted(observed):
                    obs = Observation(
                        "coarse", gate_id,
                        f"{manifest} reaches {project} through local `[deps]`; "
                        "the example gate compiles its manifest and src inputs",
                        tag_only,
                    )
                    self.add(f"{project}/dawn.toml", obs)
                    self.add_under(f"{project}/src", obs)

    # ---- queries ------------------------------------------------------
    def verdict(self, path, additional_std_modules=None):
        obs = list(self.by_path.get(path, []))
        # `--changed` supplies the base index as additional context. That is
        # how an old module path keeps its verdict after a removal or rename;
        # direct queries deliberately use only the current index.
        if (
            additional_std_modules is not None
            and path in additional_std_modules
            and self.std_module_observation is not None
        ):
            obs.append(self.std_module_observation)
        obs.sort(key=lambda o: o.key())
        # deduplicate: one line per (level, gate, why)
        seen = set()
        out = []
        for o in obs:
            k = o.key()
            if k in seen:
                continue
            seen.add(k)
            out.append(o)
        return out

    def unseen(self):
        out = []
        for f in self.tree.files:
            watched = [
                o
                for o in self.by_path.get(f, [])
                if o.level in ("exact", "coarse") and not o.tag_only
            ]
            if not watched:
                out.append(f)
        return out


MANIFEST = "dawn.toml"


LABEL_SECTION_RE = re.compile(r"^#\s*-{2,}\s*(\S+?)\s*-{2,}\s*$")


def label_sections(labels_text):
    """-> [(script, [label, ...])], in file order.

    scripts/emit-labels.txt is partitioned by `# ---- <script> ----` headers,
    one per differential. Which differential owns a label is the difference
    between "run the gate" and "run the right gate": `doc --builtins` is a
    label of its own and only the run/test transcript can see it, and
    `scripts/selfhost-prev-diff.sh` is one step of a four-step job that is also
    called prev-diff. Both of those were prose until this read them.
    """
    sections = []
    current = None
    for raw in labels_text.splitlines():
        header = LABEL_SECTION_RE.match(raw)
        if header:
            current = (header.group(1), [])
            sections.append(current)
            continue
        line = raw.strip()
        if not line or line.startswith("#") or current is None:
            continue
        current[1].append(line)
    return sections


def emit_targets(labels_text, script=PREV_DIFF):
    """The `emit <target>` corpus of one differential.

    Restricted to that script's own section: rule D's conclusion is about what
    prev-diff compiles twice, so reading a label another differential printed
    would attribute a corpus to the wrong gate.
    """
    targets = []
    for owner, labels in label_sections(labels_text):
        if owner != script:
            continue
        for line in labels:
            if line.startswith("emit "):
                targets.append(line[len("emit "):].strip())
    return targets


def source_roots(tree):
    roots = ["selfhost/src", "std", "compiler-plan/src"]
    roots += sorted({f.rsplit("/src/", 1)[0] + "/src"
                     for f in tree.files
                     if f.startswith("packages/") and "/src/" in f})
    return roots


def interesting_literal(s):
    if len(s) < MIN_LITERAL or "\\" in s:
        return False
    return " " in s or "`" in s


# A declaration with an empty parameter list is vocabulary, not an anchor:
# `pub fn main() -> Unit !io =` is how every harness writes a fixture entry
# point, and admitting it pairs selfhost/src/main.dawn with eighteen scripts
# that have never read it. Measured on this tree: 64 pairs without the filter
# and 30 with it, and the pair rule G exists for (analyze.dawn against
# java-target-classpath-contract) survives both.
DAWN_SIGNATURE = re.compile(
    r"^(?:pub(?:\(pkg\))? )?fn (?P<name>[a-z_][A-Za-z_0-9]*)(?:\[[^\]]*\])?\(", re.M
)

# The same name, anywhere in a gate script. A `sig in blob` test walks a
# multi-megabyte haystack, and this tree declares thousands of functions while
# the scripts name a few dozen; sieving on the name first turns the scan from
# every declaration into the handful that could possibly match.
SCRIPT_FN_NAME = re.compile(r"\bfn ([a-z_][A-Za-z_0-9]*)\s*[(\[]")


def signature_text(text, at):
    """The declaration starting at `at`: `fn name(` through the `=` that opens
    the body, or None if no such `=` is in reach.

    Bracket depth rather than a line regex, because a signature wraps: the row
    rule G was written for spans three lines and its `=` is on the third.
    """
    depth = 0
    closed = False
    for i in range(at, min(len(text), at + 3000)):
        c = text[i]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                closed = True
            elif depth < 0:
                return None
        elif c == "=" and depth == 0 and closed:
            if text[i - 1] in "<>!=" or text[i + 1 : i + 2] == "=":
                continue
            return text[at : i + 1]
    return None


def has_parameters(sig):
    return ":" in sig[sig.find("(") + 1 : sig.find(")")]


def signature_couplings(tree):
    """(source, gate script, signature) for every declaration a gate script
    spells out in full."""
    scripts = {}
    for f in tree.files:
        if f.startswith("scripts/") and Path(f).suffix in (".sh", ".py"):
            scripts[f] = tree.read(f)
    roots = tuple(r + "/" for r in source_roots(tree))
    blob = "\n".join(scripts.values())
    named = set(SCRIPT_FN_NAME.findall(blob))
    out = []
    for f in tree.files:
        if not f.endswith(".dawn") or not f.startswith(roots):
            continue
        text = tree.read(f)
        sigs = set()
        for m in DAWN_SIGNATURE.finditer(text):
            if m.group("name") not in named:
                continue
            sig = signature_text(text, m.start())
            if sig is not None and has_parameters(sig):
                sigs.add(sig)
        for sig in sorted(sigs):
            if sig not in blob:
                continue
            for script, body in scripts.items():
                if sig in body:
                    out.append((f, script, sig))
    return out


@lru_cache(maxsize=1024)
def literal_matches(body, literals):
    """Reuse a script's matches across sibling mutant trees by content.

    Paths alone are not cache keys: a mutant changes the body at the same
    path, and a source edit changes the candidate literals. Neither may reuse
    the clean answer. The bounded cache lives only for this checker process.
    """
    return frozenset(lit for lit in literals if lit in body)


def couplings(tree):
    """(source, gate script, literal) for every string constant a Dawn module
    builds that a gate script also spells out."""
    scripts = {}
    for f in tree.files:
        if f.startswith("scripts/") and Path(f).suffix in (".sh", ".py"):
            scripts[f] = tree.read(f)
    roots = tuple(r + "/" for r in source_roots(tree))
    sources = {}
    for f in tree.files:
        if not f.endswith(".dawn") or not f.startswith(roots):
            continue
        text = tree.read(f)
        sources[f] = sorted({m.group(1) for m in DAWN_LITERAL.finditer(text)
                             if interesting_literal(m.group(1))})
    literals = tuple(sorted({lit for lits in sources.values() for lit in lits}))
    owners = {}
    for script, body in scripts.items():
        for lit in literal_matches(body, literals):
            owners.setdefault(lit, []).append(script)
    out = []
    for f, lits in sources.items():
        for lit in lits:
            for script in owners.get(lit, ()):
                out.append((f, script, lit))
    return out


# ---------------------------------------------------------------------------
# reporting


def report(gm, paths, additional_std_modules=None, stream=sys.stdout):
    for path in paths:
        path = path.rstrip("/")
        members = gm.tree.under(path)
        if not members:
            obs = gm.verdict(path, additional_std_modules)
            if not obs:
                print(f"{path}\n  ?       not a tracked path in this tree\n", file=stream)
                continue
            print(f"{path}  (not tracked in this tree)", file=stream)
        elif members != [path]:
            print(f"{path}  ({len(members)} tracked files)", file=stream)
            obs = []
            for member in members:
                obs.extend(gm.verdict(member, additional_std_modules))
        else:
            print(path, file=stream)
            obs = gm.verdict(path, additional_std_modules)
        if not obs and path in gm.unread:
            print(f"  unread  {gm.unread[path]}", file=stream)
        elif not obs:
            print("  none    no gate reads, runs or records this file", file=stream)
        # One line per (level, gate). A driver module can share a dozen usage
        # strings with one differential; twelve identical verdicts is a wall,
        # so the longest reason stands for the group and the rest are counted.
        groups = {}
        for o in obs:
            groups.setdefault((o.level, o.gate_id, o.tag_only), []).append(o.why)
        for (level, gate_id, tag_only), whys in sorted(
            groups.items(), key=lambda kv: (REPORT_ORDER.index(kv[0][0]), kv[0][1])
        ):
            tag = " [tag only]" if tag_only else ""
            more = f"  (+{len(whys) - 1} more)" if len(whys) > 1 else ""
            print(f"  {level:<7} {gate_id}{tag}{more}", file=stream)
            print(f"          {max(whys, key=len)}", file=stream)
        # The same gate can be `coarse` on a path and blind to it, and that
        # combination is exactly how somebody talks themselves into a
        # declaration: prev-diff does read packages/web, and reads it on both
        # sides. Printing the contradiction rather than leaving it to be
        # spotted between two lines twelve apart.
        contradicted = {
            (o.gate_id, o.level) for o in obs if o.level in ("exact", "coarse")
        }
        for gate_id in sorted({o.gate_id for o in obs if o.level == "blind"}):
            if any(gid == gate_id for gid, _ in contradicted):
                compiler_role = any(
                    o.gate_id == gate_id
                    and o.level == "coarse"
                    and "HEAD_BIN=(./bin/dawn)" in o.why
                    for o in obs
                )
                if compiler_role:
                    why = (
                        "the selfhost project has two roles: its own corpus "
                        "content cancels, while its HEAD compiler inputs are "
                        "coarsely observed. Measure the declaration with the "
                        "real differential or an unmasked true-parent control."
                    )
                else:
                    why = (
                        "the blind verdict covers only the same corpus's own "
                        "content. Read the coarse reason separately; it does "
                        "not turn own-content cancellation into exact coverage."
                    )
                print(f"  note    {gate_id} {why}", file=stream)
        print(file=stream)


def declared_window(root):
    """Labels already declared between the N-1 tag and HEAD.

    A declaration in the window shields every later difference carrying the
    same label (CONTRIBUTING §5), so prev-diff cannot answer a question about a
    label somebody has already declared. Advisory: it needs the tag, and says
    so when it cannot read it.
    """
    tag_file = root / "scripts" / "seed-release.txt"
    if not tag_file.exists():
        return None, "scripts/seed-release.txt is missing"
    tag = tag_file.read_text().strip()
    proc = subprocess.run(
        ["git", "-C", str(root), "log", "--format=%B", f"{tag}..HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None, f"cannot read the window since {tag} (shallow clone?)"
    labels = set(re.findall(r"Emit-Change\(([^)]*)\)", proc.stdout))
    return labels, tag


# ---------------------------------------------------------------------------
# checks


def check_structure(gm):
    problems = list(gm.problems)
    tree = gm.tree

    # The label table. Every declarable label belongs to exactly one
    # differential, and that differential is one step of some job: `prev-diff`
    # is the name of a job with four of them in it, and a label under one
    # section is invisible to the other three.
    owners = gm.label_owners()
    if not owners:
        problems.append(
            f"{EMIT_LABELS} has no `# ---- <script> ----` section header, so "
            "no label can be attributed to the differential that prints it"
        )
    seen = {}
    for script, gate, labels in owners:
        if not tree.exists(script):
            problems.append(
                f"{EMIT_LABELS} heads a section with `{script}`, which names "
                "no file in the tree; the labels under it belong to nothing"
            )
        elif gate is None:
            problems.append(
                f"{EMIT_LABELS} heads a section with `{script}`, which no "
                "workflow step runs. Every label under it would be declarable "
                "and unmeasured"
            )
        if not labels:
            problems.append(
                f"{EMIT_LABELS}: the `{script}` section is empty, so that "
                "differential's labels are recorded nowhere"
            )
        if script in seen:
            problems.append(
                f"{EMIT_LABELS} heads two sections with `{script}`, so which "
                "differential owns a label under either is no longer readable"
            )
        seen[script] = True

    if not gm.gates:
        problems.append("no gates parsed out of the workflow files")
    return problems


# The reasons a path can be unwatched, and the shape of each reason as a
# question about the map. A free-text note would be a comment; these are
# checked, so a line cannot go on claiming a reason the tree stopped having.
#
# Each test is asked (map, path, observations). `unread` and `no-gate` are
# disjoint on purpose: plan.py lets an `unread` path select no job, so a line
# that says `unread` about a path the harness reader never cleared, or
# `no-gate` about one it did, is refused rather than trusted.
UNSEEN_KINDS = {
    # a file in a harness directory that no script run from it reaches
    "unread": lambda gm, path, obs: not obs and path in gm.unread,
    # nothing in any workflow, at any strength, reaches this path
    "no-gate": lambda gm, path, obs: not obs and path not in gm.unread,
    # gates reach it, but rule D says each of them cancels its content out
    "blind-only": lambda gm, path, obs: bool(obs)
    and all(o.level == "blind" for o in obs),
    # watched, but only by a workflow that runs on a tag rather than on a push
    "tag-only": lambda gm, path, obs: bool(obs)
    and any(o.tag_only for o in obs)
    and all(o.tag_only for o in obs if o.level in ("exact", "coarse")),
}

UNSEEN_LINE = re.compile(r"^(\S+)\s+([a-z-]+):\s*(\S.*)$")


def parse_unseen(text):
    """-> ({path: (kind, why)}, [malformed line, ...])

    One path per line: `<path>  <kind>: <why>`. The kind is from UNSEEN_KINDS
    and is checked against the map; the rest is for a person.
    """
    entries = {}
    malformed = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = UNSEEN_LINE.match(line)
        if not match:
            malformed.append(line.split()[0] if line.split() else line)
            continue
        entries[match.group(1)] = (match.group(2), match.group(3))
    return entries, malformed


def ratchet_problems(gm, record_text):
    """The unwatched set against its record, in both directions and by reason."""
    computed = set(gm.unseen())
    entries, malformed = parse_unseen(record_text)
    problems = []
    for path in sorted(malformed):
        problems.append(
            f"unseen.txt lists `{path}` and says no reason for it. Every line "
            "is `<path>  <kind>: <why>` with a kind from "
            f"{sorted(UNSEEN_KINDS)}; a gap nobody explained is the prose this "
            "directory exists to replace"
        )
    # A malformed line still *mentions* its path, so it does not also count as
    # a path nobody recorded. Otherwise one bad line reddens two assertions
    # and neither of them is owned by anything.
    for path in sorted(computed - set(entries) - set(malformed)):
        problems.append(
            f"no gate watches {path}, and it is not listed in unseen.txt. "
            "Give it a gate, or record it as unwatched with a reason."
        )
    for path in sorted(set(entries) - computed):
        problems.append(
            f"unseen.txt lists {path} as unwatched, but a gate now sees it "
            "(or the file is gone). Remove the line."
        )
    for path in sorted(set(entries) & computed):
        kind, _ = entries[path]
        test = UNSEEN_KINDS.get(kind)
        if test is None:
            problems.append(
                f"unseen.txt gives {path} the kind `{kind}`, which is not one "
                f"of {sorted(UNSEEN_KINDS)}"
            )
        elif not test(gm, path, gm.by_path.get(path, [])):
            problems.append(
                f"unseen.txt calls {path} `{kind}`, and the map contradicts "
                "it. The reason is checked, not decorative; re-derive it"
            )
    return problems


# ---------------------------------------------------------------------------
# fixtures: the two failures, replayed on the trees they happened on


def parse_fixtures(path):
    """One fixture per stanza. Keys, all required except `overlay`:

        name:     what it is
        tree:     a commit whose tree the map is run on
        changed:  a base revision; every query must occur in its no-renames
                  diff to `tree`, and rule F reads both revisions' std indexes
        overlay:  <commit> <path>   (repeatable) files taken from another commit,
                  for a batch whose tree never landed as one commit
        ground:   a sentence about what happened, checked against git (below)
        query:    a path to ask about
        expect:   <level> <substring of the gate id or of the reason>
        reject:   <level> <substring>   (must not appear for the query)
        only:     <level> <substring>   (every verdict at that level matches)

    `ground` is what keeps a fixture from being a memory. The rest of a stanza
    asserts what the *map* says about a tree; that can be true of a map that
    has drifted away from the events it claims to be about. Each `ground` line
    is a claim about the repository's own history, measured from git:

        touched <commit> <path>          the commit's diff includes that path
        added <commit> <path>            the commit adds that path from nothing
        contains <rev>:<path> <text>     the file at that rev has that text
        lacks <rev>:<path> <text>        it does not
        golden-moved <commit> <module>   the commit rewrote that module's line
                                         in the Core golden (a file that left
                                         the tree on 2026-09-25; the verb
                                         reads history, which still has it)

    A fixture with no `ground` line is rejected: a fixture nobody measured is
    exactly the rot this directory exists to kill.
    """
    fixtures = []
    current = None
    keys = ("overlay", "expect", "reject", "query", "only", "ground")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key == "name":
            current = {"name": value}
            current.update({k: [] for k in keys})
            fixtures.append(current)
        elif current is None:
            raise SystemExit(f"{path}: `{key}` before any `name:`")
        elif key in keys:
            current[key].append(value)
        else:
            current[key] = value
    return fixtures


def check_ground(fixture):
    """Every `ground` line of one fixture, measured against git."""
    problems = []
    lines = fixture["ground"]
    if not lines:
        return [
            f"{fixture['name']}: no `ground` line. A fixture that only says "
            "what the map answers is a memory; say what happened and let git "
            "check it"
        ]
    for line in lines:
        verb, _, rest = line.partition(" ")
        rest = rest.strip()
        if verb == "touched":
            commit, _, path = rest.partition(" ")
            names = run_git(
                ["diff-tree", "--no-commit-id", "--name-only", "-r", commit]
            ).split("\n")
            if path.strip() not in names:
                problems.append(
                    f"{fixture['name']}: `{line}` is not true; {commit} does "
                    f"not touch {path.strip()}"
                )
        elif verb == "added":
            commit, _, path = rest.partition(" ")
            names = run_git(
                [
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "--diff-filter=A",
                    "-r",
                    commit,
                ]
            ).split("\n")
            if path.strip() not in names:
                problems.append(
                    f"{fixture['name']}: `{line}` is not true; {commit} does "
                    f"not add {path.strip()}"
                )
        elif verb in ("contains", "lacks"):
            where, _, needle = rest.partition(" ")
            rev, _, path = where.partition(":")
            blob = run_git(["show", f"{rev}:{path}"], check=False)
            if not blob:
                problems.append(
                    f"{fixture['name']}: `{line}` cannot be measured; "
                    f"{where} is empty or missing"
                )
            elif (needle in blob) != (verb == "contains"):
                problems.append(f"{fixture['name']}: `{line}` is not true")
        elif verb == "golden-moved":
            commit, _, module = rest.partition(" ")
            module = module.strip()
            diff = run_git(["show", "--format=", commit, "--", HISTORICAL_CORE_GOLDEN])
            sides = {
                side
                for side in "-+"
                for ln in diff.splitlines()
                if ln.startswith(side)
                and not ln.startswith(side * 3)
                and ln.rstrip().endswith(f"./{module}.core")
            }
            if sides != {"-", "+"}:
                problems.append(
                    f"{fixture['name']}: `{line}` is not true; {commit} does "
                    f"not rewrite `{module}`'s line in {HISTORICAL_CORE_GOLDEN}"
                )
        else:
            problems.append(
                f"{fixture['name']}: unknown ground verb `{verb}`. See "
                "parse_fixtures()"
            )
    return problems


def materialise(commit, overlays, dest):
    dest.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", commit],
        capture_output=True,
    )
    if archive.returncode != 0:
        raise SystemExit(
            f"cannot materialise {commit}: {archive.stderr.decode(errors='replace').strip()}\n"
            "  The fixtures replay real commits, so this check needs their objects.\n"
            "  In CI that means fetch-depth: 0."
        )
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive.stdout, check=True)
    files = set(
        p for p in run_git(["ls-tree", "-r", "--name-only", commit]).split("\n") if p
    )
    for spec in overlays:
        other, _, rel = spec.partition(" ")
        rel = rel.strip()
        for existing in list(dest.glob(rel + "/**/*")) + list(dest.glob(rel)):
            if existing.is_file():
                existing.unlink()
        sub = subprocess.run(
            ["git", "-C", str(ROOT), "archive", other, rel], capture_output=True
        )
        if sub.returncode != 0:
            raise SystemExit(f"cannot overlay {rel} from {other}")
        subprocess.run(["tar", "-x", "-C", str(dest)], input=sub.stdout, check=True)
        files = {f for f in files if not (f == rel or f.startswith(rel + "/"))}
        files |= {
            p
            for p in run_git(["ls-tree", "-r", "--name-only", other, "--", rel]).split(
                "\n"
            )
            if p
        }
    return sorted(files)


def run_fixtures(path, verbose=True):
    problems = []
    for fx in parse_fixtures(path):
        problems += check_ground(fx)
        with tempfile.TemporaryDirectory(prefix="gatemap-fx-") as tmp:
            files = materialise(fx["tree"], fx["overlay"], Path(tmp))
            gm = Map(Tree(tmp, files))
            additional_std_modules = None
            if "changed" in fx:
                if fx["overlay"]:
                    problems.append(
                        f"{fx['name']}: `changed` cannot be combined with an "
                        "overlay, because the overlay is not a Git tree the "
                        "diff can measure"
                    )
                changed = set(changed_paths(fx["changed"], fx["tree"]))
                additional_std_modules = std_modules_at_revision(fx["changed"])
                for query in fx["query"]:
                    if query not in changed:
                        problems.append(
                            f"{fx['name']}: `{query}` is not changed from "
                            f"{fx['changed']} to {fx['tree']}, so the "
                            "--changed fixture would never query it"
                        )
            lines = []
            for query in fx["query"]:
                for o in gm.verdict(query, additional_std_modules):
                    lines.append((query, o.level, f"{o.gate_id} :: {o.why}"))
            for want in fx["expect"]:
                level, _, needle = want.partition(" ")
                if not any(
                    lv == level and needle in text for _, lv, text in lines
                ):
                    problems.append(
                        f"{fx['name']}: expected a `{level}` verdict matching "
                        f"{needle!r} and got none.\n"
                        + "".join(
                            f"      {q}: {lv} {t}\n" for q, lv, t in lines
                        )
                    )
            for want in fx["only"]:
                level, _, needle = want.partition(" ")
                at_level = [t for _, lv, t in lines if lv == level]
                stray = [t for t in at_level if needle not in t]
                if not at_level:
                    problems.append(
                        f"{fx['name']}: `only {level} {needle}` matched nothing "
                        "at all, so it asserts nothing"
                    )
                for t in stray:
                    problems.append(
                        f"{fx['name']}: `only {level} {needle}`, but this is "
                        f"also {level}: {t}"
                    )
            for nope in fx["reject"]:
                level, _, needle = nope.partition(" ")
                bad = [t for _, lv, t in lines if lv == level and needle in t]
                if bad:
                    problems.append(
                        f"{fx['name']}: a `{level}` verdict matching {needle!r} "
                        f"appeared, and the fixture says it must not: {bad[0]}"
                    )
            if verbose and not problems:
                print(f"  replayed: {fx['name']}")
    return problems


# ---------------------------------------------------------------------------
# negative controls
#
# The house rule is that a green gate carries no information until something
# has been seen reddening it, and the shape this repository settled on last
# week is scripts/pipe-contract/matrix.py: run every mutant against the *whole*
# assertion set, record the red sets, and require each mutant to be owned by an
# assertion no other mutant reddens. Ownership asserted in prose enforces
# nothing, because a later change can quietly give a second mutant the same
# red.
#
# Five rules, all machine-checked against mutants.txt:
#
#   1. every counted mutant has an owning assertion, in its own red set;
#   2. no other counted mutant reddens that assertion, which is what "owns"
#      means;
#   3. the observed red set equals the recorded one, in both directions;
#   4. every assertion is either some counted mutant's owner or declared a
#      `control`, so no assertion sits here unreddenable and unremarked;
#   5. a control is in no counted mutant's red set. It is the assertion every
#      mutant has to keep green.
#
# Rule 3 is what makes a mutant with an *empty* red set worth having.
# `glob-with-a-wildcard-head` is recorded rather than counted for exactly that
# reason: with the guard in resolve() present it changes nothing, so it can
# own nothing, and if the guard ever goes away it starts reddening the control
# and the record disagrees. Its companion `glob-with-a-literal-head` edits the
# same file and must stay counted, which is what stops the pair from going
# vacuous when that file is renamed.


class Check:
    """One run of everything, on one tree, against one unseen record."""

    def __init__(self, gm, record_text):
        self.map = gm
        self.problems = check_structure(gm)
        self.ratchet = ratchet_problems(gm, record_text)


class Baseline:
    """What the clean tree answers, for the assertions stated as a difference."""

    def __init__(self, tree):
        self.tree = tree
        gm = Map(tree)
        self.unwatched = len(gm.unseen())
        self.coupling = choose_coupling(tree)
        self.signature_coupling = choose_signature_coupling(tree)
        self.js_gate = choose_js_gate(gm)
        self.import_edge = choose_import_edge(gm)
        self.read_edge = choose_read_edge(gm)
        self.step_harness = choose_step_harness(gm)


def _gate_sees(gm, gate_id, path):
    return any(
        o.level == "exact" and o.gate_id == gate_id for o in gm.verdict(path)
    )


def _harness_candidates(gm):
    """-> [(gate, script, its reach)] for every harness script a step runs,
    in a stable order, with the directories that step reads whole."""
    out = []
    for gate in sorted(gm.gates, key=lambda g: (g.workflow, g.id)):
        scripts = sorted(s for s in gate_scripts(gate, gm.tree) if harness_dir(s))
        reaches = {s: gm.harness.reach(s) for s in scripts}
        whole = set().union(*(set(r.whole) for r in reaches.values())) if reaches else set()
        out.append((gate, scripts, reaches, whole))
    return out


def choose_import_edge(gm):
    """-> (gate id, importer, module, the import line) for the mutant that
    drops an import, or None.

    Read from the tree for the reason `choose_coupling` is. The edge has to be
    the only way that step reaches the module, so dropping it has something to
    take away: the step does not run the module itself, reads no directory
    whole, and no other script it runs imports or names the module. The first
    such edge is checked by building the mutated map once, so a choice that
    would leave the mutant silent is refused here rather than recorded.
    """
    tree = gm.tree
    for gate, scripts, reaches, whole in _harness_candidates(gm):
        for importer in scripts:
            if Path(importer).suffix != ".py":
                continue
            mod = gm.harness.py_module(importer)
            if mod.error:
                continue
            lines = tree.read(importer).splitlines()
            for unit, module, names, line in mod.imports:
                target = mod.module_files.get(module)
                if unit != "<module>" or target is None or target in scripts:
                    continue
                if posixpath.dirname(target) in whole:
                    continue
                others = [s for s in scripts if s != importer
                          and target in reaches[s].reads]
                if others or not _gate_sees(gm, gate.id, target):
                    continue
                text = lines[line - 1]
                if sum(1 for ln in lines if text in ln) != 1:
                    continue
                dropped = Map(tree.mutate(overrides={
                    importer: drop_line(text)(tree.read(importer), importer)
                }))
                if not _gate_sees(dropped, gate.id, target):
                    return gate.id, importer, target, text
    return None


def choose_read_edge(gm):
    """-> (gate id, script, file, the quoted name) for the mutant that
    renames a template a harness reads, or None. Chosen the way
    `choose_import_edge` is: a non-script file that step reaches only because
    this script names it, once, in quotes."""
    tree = gm.tree
    for gate, scripts, reaches, whole in _harness_candidates(gm):
        for script in scripts:
            text = tree.read(script)
            for path, how in sorted(reaches[script].reads.items()):
                if (
                    path not in tree.fileset
                    or Path(path).suffix in SCRIPT_SUFFIXES
                    or posixpath.dirname(path) in whole
                    or not how.startswith(posixpath.basename(script) + ":")
                    or not _inside(path, posixpath.dirname(script))
                ):
                    continue
                others = [s for s in scripts if s != script
                          and path in reaches[s].reads]
                if others or not _gate_sees(gm, gate.id, path):
                    continue
                name = path[len(posixpath.dirname(script)) + 1:]
                quoted = next(
                    (q for q in (f'"{name}"', f"'{name}'") if text.count(q) == 1),
                    None,
                )
                if quoted is None:
                    continue
                renamed = quoted[0] + name + RENAMED + quoted[0]
                moved = Map(tree.mutate(overrides={
                    script: swap(quoted, renamed)(text, script)
                }))
                if not _gate_sees(moved, gate.id, path):
                    return gate.id, script, path, quoted
    return None


def choose_step_harness(gm):
    """-> (the gates.yml run line, the harness it runs) for the recorded
    mutant that takes a harness out of its step, or None.

    A harness run by one inline `run:` line and reached by nothing else, in a
    directory no step reads whole: without that line it is run by no step,
    so it has to surface as a path the ratchet has not recorded.
    """
    tree = gm.tree
    workflow = ".github/workflows/gates.yml"
    text = tree.read(workflow)
    reached_by = {}
    for gate, scripts, reaches, whole in _harness_candidates(gm):
        for script, reach in reaches.items():
            for path in [script] + list(reach.reads):
                reached_by.setdefault(path, set()).add(gate.id)
            for directory in whole:
                for path in tree.under(directory):
                    reached_by.setdefault(path, set()).add(gate.id)
    for gate in sorted(gm.gates, key=lambda g: g.id):
        if gate.workflow != "gates.yml" or len(gate.commands) != 1:
            continue
        line = f"run: {gate.commands[0]}"
        scripts = [s for s in gate_scripts(gate, tree) if harness_dir(s)]
        if len(scripts) != 1 or text.count(line) != 1:
            continue
        script = scripts[0]
        if reached_by.get(script) != {gate.id}:
            continue
        if gm.fallback.get(posixpath.dirname(script)):
            continue
        return line, script
    return None


def js_gate_script(gm):
    """-> the JavaScript gate's entry script in this tree, or None."""
    found = {
        script
        for gate in gm.gates
        for script in gate_scripts(gate, gm.tree)
        if Path(script).suffix in JS_SUFFIXES
    }
    return sorted(found)[0] if found else None


def js_gate_manifest(tree, script):
    """-> the package.json whose `scripts` table names this script, or None."""
    parts = posixpath.dirname(script).split("/")
    while parts:
        where = "/".join(parts)
        manifest = f"{where}/package.json"
        if manifest in tree.fileset and posixpath.relpath(script, where) in tree.read(
            manifest
        ):
            return manifest
        parts.pop()
    return None


def choose_js_gate(gm):
    """-> (the JavaScript gate's script, a compiler module it names,
    the package.json that binds it to `npm test`), or None.

    Derived from the tree rather than written down, for the reason
    `choose_coupling` gives. `js_join_probe` is about
    whichever file the JavaScript gate is; with the name spelled out here, a
    mutant that renames it to `.cjs` would redden that probe by renaming its
    subject, and a rename is exactly what has to stay invisible.
    """
    script = js_gate_script(gm)
    if script is None:
        return None
    manifest = js_gate_manifest(gm.tree, script)
    named, _ = js_inputs(gm.tree.read(script), gm.tree, script)
    modules = sorted(p for p in named if p.startswith("selfhost/src/"))
    if not modules or manifest is None:
        return None
    return script, modules[0], manifest


def choose_coupling(tree):
    """The rule E pair `rewrite-a-shared-sentence` rewrites.

    The first pair whose literal occurs exactly once in its source, so that the
    rewrite has an anchor it can assert. Chosen from the tree rather than named
    here: rule E's subject is whichever sentences the sources and the gates
    happen to share, and a hard-coded pair would be a fixture of its own that
    nobody re-measures.
    """
    for src, script, literal in sorted(couplings(tree)):
        if tree.read(src).count(literal) == 1:
            return (src, script, literal)
    return None


def choose_signature_coupling(tree):
    """The rule G pair `rewrite-a-shared-signature` rewrites.

    Read from the tree for the reason `choose_coupling` is read from it: rule
    G's subject is whichever declarations the sources and the harnesses happen
    to share, and a hard-coded pair would be a fixture nobody re-measures. The
    signature has to occur once in its source so the rewrite has an anchor, and
    once in the script so the mutated tree cannot keep the coupling through a
    second copy of the same row.
    """
    for src, script, sig in sorted(signature_couplings(tree)):
        if tree.read(src).count(sig) == 1 and tree.read(script).count(sig) == 1:
            return (src, script, sig)
    return None


def _clean(problems, needle):
    return not any(needle in p for p in problems)


def _cites(check, path, script):
    return any(script in obs.why for obs in check.map.verdict(path))


def _js_join_probe(check, base):
    """The JavaScript half of rule B, with its subject read from each tree.

    The gate's script is looked up in the tree under test and the compiler
    module in the clean one: the coupling that has to survive is "whatever the
    JavaScript gate is called, it is still why that module is watched", so a
    rename passes and a reader that lost the joins does not.
    """
    if base.js_gate is None:
        return False
    script = js_gate_script(check.map)
    return script is not None and _cites(check, base.js_gate[1], script)


def _has_head_compiler_coarse(gm, path="selfhost/dawn.toml"):
    return any(
        obs.level == "coarse" and obs.why.startswith(HEAD_COMPILER_REASON)
        for obs in gm.verdict(path)
    )


# Each entry is (name, what it asserts, predicate). The predicate is true when
# the assertion is green, so a mutant "reddens" one by making it false.
ASSERTIONS = [
    (
        "commands_resolve",
        "every path-shaped command in a workflow step names a file",
        lambda c, b: _clean(c.problems, "names nothing in it"),
    ),
    (
        "prev_diff_std_premise",
        "prev-diff still points the N-1 toolchain at its own std",
        lambda c, b: _clean(c.problems, "rule D is void"),
    ),
    (
        "prev_diff_head_compiler_premise",
        "prev-diff still runs the compiler built from the selfhost project "
        "on its HEAD leg",
        lambda c, b: _clean(c.problems, "HEAD compiler premise is void"),
    ),
    (
        "selfhost_compiler_closure_premise",
        "the HEAD compiler input closure is a complete repo-local SourcePlan "
        "graph rooted at selfhost",
        lambda c, b: _clean(c.problems, COMPILER_CLOSURE_PROBLEM),
    ),
    (
        "emit_cancels_the_corpus",
        "the differential still emits the same target through both output "
        "legs, which is why a corpus target's own source is blind to its own "
        "label",
        lambda c, b: _clean(c.problems, "blind conclusion is void"),
    ),
    (
        "std_not_corpus",
        "std is not itself an emit corpus target",
        lambda c, b: _clean(c.problems, "re-derive it"),
    ),
    (
        "corpus_target_exists",
        "every emit corpus target is a path in the tree",
        lambda c, b: _clean(c.problems, "names corpus target"),
    ),
    (
        "label_section_resolves",
        "every emit-labels section header names a file in the tree",
        lambda c, b: _clean(c.problems, "which names no file in the tree"),
    ),
    (
        "label_section_has_a_gate",
        "every emit-labels section is a differential some workflow step runs",
        lambda c, b: _clean(c.problems, "which no workflow step runs"),
    ),
    (
        "label_section_unique",
        "no two emit-labels sections name the same differential",
        lambda c, b: _clean(c.problems, "heads two sections with"),
    ),
    (
        "unseen_no_new",
        "a path no gate watches is recorded in unseen.txt",
        lambda c, b: _clean(c.ratchet, "is not listed in unseen.txt"),
    ),
    (
        "unseen_no_stale",
        "a gap that has been closed does not sit on in unseen.txt",
        lambda c, b: _clean(c.ratchet, "Remove the line"),
    ),
    (
        "unseen_reason_present",
        "every line of unseen.txt says why that path is unwatched",
        lambda c, b: _clean(c.ratchet, "says no reason for it"),
    ),
    (
        "unseen_reason_true",
        "and the reason it says is one the map still supports",
        lambda c, b: _clean(c.ratchet, "the map contradicts"),
    ),
    (
        "coupling_probe",
        "rule E follows the shared sentence rather than the file name",
        lambda c, b: b.coupling is not None
        and any(
            repr(b.coupling[2]) in obs.why for obs in c.map.verdict(b.coupling[0])
        ),
    ),
    (
        "signature_probe",
        "rule G follows the declaration a harness quotes, so an effect row "
        "that moves is visible from the file that owns it",
        lambda c, b: b.signature_coupling is not None
        and any(
            " ".join(b.signature_coupling[2].split()) in obs.why
            for obs in c.map.verdict(b.signature_coupling[0])
        ),
    ),
    (
        "python_join_probe",
        "rule B reads `ROOT / \"a\" / \"b\"` joins, which is the only reason "
        "anything watches the workflow files",
        lambda c, b: _cites(
            c, ".github/workflows/release.yml", "scripts/check-gate-budgets.py"
        ),
    ),
    (
        "js_join_probe",
        "rule B reaches a JavaScript gate started as `npm test`, and reads the "
        "path joins in it, which is the only reason anything says the editor "
        "grammar contract watches the compiler's lexer",
        _js_join_probe,
    ),
    (
        "js_binding_readable",
        "a JavaScript gate that reaches for the path module in a spelling the "
        "reader cannot follow is reported, not read as naming nothing",
        lambda c, b: _clean(c.problems, JS_UNREADABLE_BINDING),
    ),
    (
        "glob_literal_probe",
        "a glob with a literal head is expanded against the tree",
        lambda c, b: not _cites(
            c, "scripts/pipe-contract/matrix.txt", "scripts/doc-check.py"
        ),
    ),
    (
        "harness_import_probe",
        "a module a harness imports is its step's code, so a change to the "
        "shared module selects every step that runs an importer (#169)",
        lambda c, b: b.import_edge is not None
        and _gate_sees(c.map, b.import_edge[0], b.import_edge[2]),
    ),
    (
        "harness_read_probe",
        "a template a harness names inside its directory is its step's input, "
        "file by file rather than through the whole directory (#169)",
        lambda c, b: b.read_edge is not None
        and _gate_sees(c.map, b.read_edge[0], b.read_edge[2]),
    ),
    (
        "unwatched_floor",
        "the unwatched set never collapses; a map that says everything is "
        "covered says nothing",
        lambda c, b: len(c.map.unseen()) >= b.unwatched,
    ),
]


def unseen_prefix(text, path):
    """The `<path><padding><kind>:` prefix, as unseen.txt currently pads it.

    The padding is a column derived from the longest path in the file, so a
    literal spelling of it here goes stale the day a gate closes and the
    longest path leaves: the two mutants below then anchor on nothing, and
    `swap` says so rather than passing. Closing a gap is the ordinary
    outcome of adding a gate, so the anchor is computed instead.
    """
    for line in text.splitlines():
        if line.startswith(path + " "):
            return line[: line.index(":") + 1]
    raise SystemExit(
        f"gate-map selftest: {path} is not in unseen.txt any more. "
        "Repoint the two ratchet mutants at a path that is still recorded"
    )


def swap(old, new):
    """A string replacement that refuses to happen twice, or not at all.

    A mutant whose anchor drifted is a mutant that tests nothing, and it
    passes silently: the tree comes out unmutated and every assertion stays
    green. So the anchor is asserted unique before anything is replaced.
    """

    def apply(text, where):
        hits = text.count(old)
        if hits != 1:
            raise SystemExit(
                f"gate-map selftest: mutation anchor drifted in {where}: "
                f"{old!r} appears {hits} time(s), not once. Repoint the mutant; "
                "a mutation that does not happen is a green nobody earned"
            )
        return text.replace(old, new)

    return apply


def swap_all(old, new):
    """A replacement that is meant to hit every occurrence, and at least one.

    The stricter `swap` is wrong where the mutation is a rename across a
    file: a JavaScript gate calls `path.join` as often as it has inputs, and
    pinning the count would make the selftest brittle about how many it has. What must still fail loudly is the anchor going away entirely.
    """

    def apply(text, where):
        if old not in text:
            raise SystemExit(
                f"gate-map selftest: mutation anchor drifted in {where}: "
                f"{old!r} appears nowhere. Repoint the mutant; a mutation that "
                "does not happen is a green nobody earned"
            )
        return text.replace(old, new)

    return apply


def provide(content):
    """The content of a file the mutant adds. No anchor, so nothing can drift,
    but it must really be new: a mutant that quietly overwrites something is
    testing whatever that was."""

    def apply(text, where):
        if text:
            raise SystemExit(
                f"gate-map selftest: {where} already exists, so the mutant "
                "that adds it is testing something else"
            )
        return content

    return apply


def then(*steps):
    """Several edits to one file, applied in order."""

    def apply(text, where):
        for step in steps:
            text = step(text, where)
        return text

    return apply


def append(tail):
    """Append, having checked there is something to append to."""

    def apply(text, where):
        if not text.strip():
            raise SystemExit(
                f"gate-map selftest: {where} is empty, so appending to it "
                "tests nothing"
            )
        return text + tail
    return apply


def drop_line(needle):
    """Delete the one line containing `needle`."""

    def apply(text, where):
        lines = text.splitlines()
        hits = [ln for ln in lines if needle in ln]
        if len(hits) != 1:
            raise SystemExit(
                f"gate-map selftest: mutation anchor drifted in {where}: "
                f"{len(hits)} line(s) contain {needle!r}, not one"
            )
        return "\n".join(ln for ln in lines if ln != hits[0]) + "\n"

    return apply


def rewrite_coupling(base):
    def apply(text, where):
        return swap(base.coupling[2], "a sentence nobody greps")(text, where)

    return apply


def rewrite_signature_coupling(base):
    """Widen the chosen declaration's effect row, which is bd664890 in one
    edit: the body is untouched and the harness that quotes the old row can no
    longer find it."""

    def apply(text, where):
        sig = base.signature_coupling[2]
        return swap(sig, sig[:-1] + "!Never =")(text, where)

    return apply


def kind_for(gm, path):
    for kind, test in UNSEEN_KINDS.items():
        if test(gm, path, gm.by_path.get(path, [])):
            return kind
    return None


def regenerate_record(gm, note="regenerated by the selftest"):
    """An unseen record that matches this tree by construction.

    Every mutant that is not *about* the ratchet gets one. A mutant that
    legitimately moves coverage would otherwise redden the ratchet as a side
    effect, and an assertion two mutants can redden is owned by neither.
    """
    lines = []
    for path in gm.unseen():
        kind = kind_for(gm, path) or "no-gate"
        lines.append(f"{path}  {kind}: {note}")
    return "\n".join(lines) + "\n"


# A suffix and a path the tree never has, so a mutant that plants one is
# planting something and not colliding with something.
RENAMED = "_renamed_by_the_selftest"
COMPILER_PROBE_PROJECT = "gate-map-selftest/compiler-dep"
COMPILER_PROBE_MANIFEST = f"{COMPILER_PROBE_PROJECT}/dawn.toml"
COMPILER_PROBE_SOURCE = f"{COMPILER_PROBE_PROJECT}/src/value.dawn"


class Mutant:
    """One otherwise-valid tree (or record) with one thing wrong with it."""

    def __init__(self, name, why, files=None, edits=None, record=None):
        self.name = name
        self.why = why
        self.files = files
        self.edits = edits or {}
        self.record = record


def js_renamed(base, suffix, body=None):
    """The mutant pair for a JavaScript gate that changes file extension.

    Node's module systems are chosen by extension, so this is a rename a real
    gate makes; both halves have to move together, since the package.json entry
    is the only thing that binds the lifecycle name to a file.
    """
    script, _, manifest = base.js_gate
    target = script[: -len(Path(script).suffix)] + suffix
    directory = posixpath.dirname(manifest)
    return (
        lambda files: [f for f in files if f != script] + [target],
        {
            target: provide(base.tree.read(script) if body is None else body),
            manifest: swap(
                posixpath.relpath(script, directory),
                posixpath.relpath(target, directory),
            ),
        },
    )


JS_ESM = then(
    swap(
        'const assert = require("node:assert/strict");\n'
        'const fs = require("node:fs");\n'
        'const path = require("node:path");\n',
        'import assert from "node:assert/strict";\n'
        'import fs from "node:fs";\n'
        'import path from "node:path";\n'
        'import { createRequire } from "node:module";\n'
        "\nconst require = createRequire(import.meta.url);\n",
    ),
    swap_all("__dirname", "import.meta.dirname"),
)


def mutants(base):
    """The mutant set, built against the clean tree's baseline."""
    js_script = base.js_gate[0]
    # The literal, spelled one segment per argument. Both JavaScript mutants
    # that are about the reader start here: with the path in one string it is
    # also a slash-bearing token, so `path_tokens` answers and the reader could
    # be missing entirely without either of them noticing.
    js_segment = swap(
        f'path.join(ROOT, "{base.js_gate[1]}")',
        "path.join(ROOT, "
        + ", ".join(f'"{part}"' for part in base.js_gate[1].split("/"))
        + ")",
    )
    cjs_files, cjs_edits = js_renamed(base, ".cjs")
    mjs_files, mjs_edits = js_renamed(
        base, ".mjs", then(js_segment, JS_ESM)(base.tree.read(js_script), js_script)
    )
    return [
        Mutant(
            "workflow-runs-a-missing-script",
            "a step whose command names a path into this repository and is "
            "not one, which is indistinguishable from a step this parser "
            "cannot read",
            edits={
                ".github/workflows/gates.yml": append(
                    "\n"
                    "  gate-map-selftest-mutant:\n"
                    "    runs-on: ubuntu-latest\n"
                    "    # budget: floor (seconds-scale job)\n"
                    "    timeout-minutes: 10\n"
                    "    steps:\n"
                    "      - name: a step whose script is not in this tree\n"
                    "        run: ./scripts/no-such-gate.sh\n"
                )
            },
        ),
        Mutant(
            "prev-diff-drops-its-own-std",
            "rule D's premise: with the N-1 side compiling today's std, "
            "'std source moves the emitted bytes' stops following",
            edits={PREV_DIFF: swap('--std "$(seed_std_dir)"', '"$(seed_std_dir)"')},
        ),
        Mutant(
            "prev-diff-head-leg-uses-prev",
            "rule D's compiler-behaviour premise. The script remains valid, "
            "keeps the HEAD_BIN assignment and even names it in a comment, "
            "but the real head output command runs PREV. The selfhost project "
            "therefore no longer defines a compiler observed by that leg",
            edits={
                PREV_DIFF: swap(
                    HEAD_EMIT_COMMAND,
                    '"${PREV[@]}" __emit "$t" -o "$OUT/head/$t" '
                    '> /dev/null # HEAD_BIN',
                )
            },
        ),
        Mutant(
            "selfhost-dependency-escapes-repo",
            "the compiler closure premise. The manifest remains valid TOML, "
            "but one local dependency normalizes outside the repository and "
            "must void every HEAD-compiler coarse claim",
            edits={
                SELFHOST_MANIFEST: swap(
                    'compiler_plan = "../compiler-plan"',
                    'compiler_plan = "../../gate-map-outside"',
                )
            },
        ),
        Mutant(
            "the-two-emit-legs-stop-agreeing",
            "rule D's blind premise. If the two sides ever emit different "
            "trees, a corpus target's own content stops cancelling and every "
            "`blind` verdict here becomes an over-claim in the direction that "
            "matters",
            edits={
                PREV_DIFF: swap(
                    '"${HEAD_BIN[@]}" __emit "$t"',
                    '"${HEAD_BIN[@]}" __emit selfhost',
                )
            },
        ),
        Mutant(
            "std-becomes-a-corpus-target",
            "rule D's exception: std compiled as a corpus target would cancel "
            "like every other target, and the rule says the opposite",
            edits={EMIT_LABELS: swap("emit site\n", "emit site\nemit std\n")},
        ),
        Mutant(
            "corpus-target-that-is-not-here",
            "a declared corpus the tree does not contain",
            edits={
                EMIT_LABELS: swap("emit site\n", "emit site\nemit no/such/corpus\n")
            },
        ),
        Mutant(
            "label-section-heads-a-missing-script",
            "labels attributed to a differential that is not in the tree",
            edits={
                EMIT_LABELS: swap(
                    "# ---- scripts/selfhost-fmt-diff.sh ----",
                    "# ---- scripts/selfhost-fmt-diff-renamed.sh ----",
                )
            },
        ),
        Mutant(
            "label-section-nobody-runs",
            "labels attributed to a script that exists and that no workflow "
            "step runs, so they would be declarable and never measured",
            edits={
                EMIT_LABELS: swap(
                    "# ---- scripts/selfhost-fmt-diff.sh ----",
                    "# ---- scripts/bench.sh ----",
                )
            },
        ),
        Mutant(
            "two-sections-one-differential",
            "two sections headed by the same differential, so which gate owns "
            "a label under either stops being readable",
            edits={
                EMIT_LABELS: swap(
                    "# ---- scripts/selfhost-lsp-diff.sh ----",
                    "# ---- scripts/selfhost-fmt-diff.sh ----",
                )
            },
        ),
        Mutant(
            "a-new-file-nobody-watches",
            "the ratchet, forwards. It goes under .githooks, which this map "
            "reports as watched by nothing, so the mutant tests the ratchet "
            "rather than that directory's coverage",
            files=lambda fs: fs + [".githooks/gate-map-mutant"],
            record=lambda text: text,
        ),
        Mutant(
            "a-closed-gap-still-recorded",
            "the ratchet, backwards. A one-way ratchet is how known-red lists "
            "come to describe a tree that no longer exists",
            record=lambda text: text + "README.md  no-gate: planted by the selftest\n",
        ),
        Mutant(
            "a-recorded-gap-with-no-reason",
            "a recorded gap with no reason beside it, which is the prose this "
            "file exists to replace",
            record=lambda text: swap(unseen_prefix(text, "LICENSE"), "LICENSE  #")(
                text, "unseen.txt"
            ),
        ),
        Mutant(
            "a-recorded-gap-with-the-wrong-reason",
            "a reason the map contradicts. The kind is checked, so it cannot "
            "go on claiming something the tree stopped supporting",
            record=lambda text: swap(
                unseen_prefix(text, "LICENSE"),
                unseen_prefix(text, "LICENSE").replace("no-gate:", "tag-only:"),
            )(text, "unseen.txt"),
        ),
        Mutant(
            "rewrite-a-shared-sentence",
            "rule E run backwards: rewrite the sentence a gate spells out and "
            "the coupling has to go, which is the first of the two failures",
            edits={base.coupling[0]: rewrite_coupling(base)},
        ),
        Mutant(
            "rewrite-a-shared-signature",
            "rule G run backwards: widen the effect row of the declaration a "
            "mutation harness quotes and the coupling has to go, which is the "
            "shape bd664890 shipped and two harnesses paid for",
            edits={base.signature_coupling[0]: rewrite_signature_coupling(base)},
        ),
        Mutant(
            "drop-the-one-path-join",
            "rule B through its Python reader. check-gate-budgets.py names its "
            "whole subject once, as a path join no regular expression over `/` "
            "can tell from a division, and it is the only reason anything "
            "watches the workflow files",
            edits={
                "scripts/check-gate-budgets.py": swap(
                    'root / ".github" / "workflows" / name', "root"
                )
            },
        ),
        Mutant(
            "npm-run-stops-naming-the-contract",
            "rule B through the npm indirection. A gate whose command is `npm "
            "test` names no file, so the package.json script is what connects "
            "it to one; with the lifecycle name bound to something else the "
            "editor grammar job has to stop watching the compiler's lexer, "
            "which is the state this map was silently in",
            edits={
                base.js_gate[2]: swap(
                    "node "
                    + posixpath.relpath(js_script, posixpath.dirname(base.js_gate[2])),
                    "node --test",
                )
            },
        ),
        Mutant(
            "js-path-in-segments",
            "the JavaScript reader, run against the other spelling of the same "
            "join. Recorded with an empty red set: a segmented "
            "`path.join(ROOT, \"a\", \"b\")` is the same declared input as the "
            "one-literal form and coverage may not move, while a map that only "
            "scraped slash-bearing tokens loses it. Rule 3 is what makes the "
            "silence mean something, and `npm-run-stops-naming-the-contract` "
            "is counted on the same coupling so the pair cannot go vacuous",
            edits={js_script: js_segment},
        ),
        Mutant(
            "js-path-destructured",
            "the same join, taken off the module by name instead of through "
            "it. `const { join } = require(\"node:path\")` is the same declared "
            "input as `const path = ...`, so coverage may not move; recorded "
            "with an empty red set. Segmented as well, because that is what "
            "takes `path_tokens` out of the answer: a reader that matched "
            "`path.` as a literal prefix finds nothing here",
            edits={
                js_script: then(
                    js_segment,
                    swap(
                        'const path = require("node:path");',
                        'const { join, resolve } = require("node:path");',
                    ),
                    swap_all("path.join(", "join("),
                    swap_all("path.resolve(", "resolve("),
                )
            },
        ),
        Mutant(
            "js-gate-renamed-cjs",
            "the gate, renamed to the extension that spells out the module "
            "system it already uses. Nothing about it changes but the name, so "
            "its red set is empty; a suffix tuple that did not list `.cjs` "
            "stops seeing the gate at all, which is #302 again",
            files=cjs_files,
            edits=cjs_edits,
        ),
        Mutant(
            "js-gate-migrated-to-esm",
            "and the migration that goes with the other extension: `import` "
            "for the declarations, `import.meta.dirname` for the directory, "
            "`createRequire` for what is left. A real change to make and none "
            "of it moves a path, so the red set is empty. Segmented too, "
            "because that is what the directory seed is measured by: with the "
            "path in one string, dropping `import.meta.dirname` left this "
            "silent and the seed was carrying nothing",
            files=mjs_files,
            edits=mjs_edits,
        ),
        Mutant(
            "js-path-bound-under-another-name",
            "the spelling the reader is not going to follow: a binding that "
            "renames what it takes. This one is counted, because the answer is "
            "not to read it but to say so. Silence here is the #302 failure "
            "exactly, and the assertion it owns is what makes it a report",
            edits={
                js_script: then(
                    swap(
                        'const path = require("node:path");',
                        "const { join: pjoin, resolve: presolve } = "
                        'require("node:path");',
                    ),
                    swap_all("path.join(", "pjoin("),
                    swap_all("path.resolve(", "presolve("),
                )
            },
        ),
        Mutant(
            "drop-an-import-edge",
            "file-level rule A through its import edge: the harness stops "
            "importing the shared module, and the step that runs it has to "
            "stop being selected by a change to that module. With the edge "
            "unread, a shared helper would look like nobody's code",
            edits={
                base.import_edge[1]: drop_line(base.import_edge[3]),
            },
        ),
        Mutant(
            "rename-a-template-read",
            "file-level rule A through a named read: the harness asks for a "
            "template under another name, and the file it used to read stops "
            "being that step's input",
            edits={
                base.read_edge[1]: swap(
                    base.read_edge[3],
                    base.read_edge[3][0]
                    + base.read_edge[3][1:-1]
                    + RENAMED
                    + base.read_edge[3][0],
                ),
            },
        ),
        Mutant(
            "harness-leaves-its-step",
            "the negative control the file-level rule owes the ratchet: take "
            "a harness out of the one step that runs it and it is run by "
            "nothing, so it has to arrive as a path unseen.txt does not "
            "record. Recorded rather than counted, because that assertion is "
            "`a-new-file-nobody-watches`'s to own; rule 3 is what keeps it "
            "red",
            edits={
                ".github/workflows/gates.yml": drop_line(base.step_harness[0]),
            },
            record=lambda text: text,
        ),
        Mutant(
            "glob-with-a-literal-head",
            "rule B's other half: a glob whose head is literal is a gate "
            "stating its input, and has to be expanded. Also the vacuity "
            "guard for the mutant below, which edits the same file",
            edits={
                "scripts/doc-check.py": append(
                    '\nGATE_MAP_PROBE = ["scripts/pipe-contract/*.txt"]\n'
                )
            },
        ),
        Mutant(
            "glob-with-a-wildcard-head",
            "and the appetite that goes with it. `*/.` out of a case pattern "
            "and `**/*` out of a glob call each matched every top-level path "
            "in the repository while this file was being written. Recorded "
            "with an empty red set: its silence is the assertion, and rule 3 "
            "is what makes the silence mean something",
            edits={
                "scripts/doc-check.py": append(
                    '\nGATE_MAP_PROBE = ["**/*", "*/.", "*/..", "*"]\n'
                )
            },
        ),
    ]


def observe(base_tree, base_record):
    """-> ({mutant: red set}, [problem]). Every mutant against every assertion."""
    base = Baseline(base_tree)
    problems = []
    if base.coupling is None:
        return {}, ["rule E finds no coupling in this tree, so it has no mutant"]
    if base.js_gate is None:
        return {}, [
            "no JavaScript gate in this tree names a compiler module through a "
            "path join and a package.json, so rule B's JavaScript half has "
            "nothing to mutate"
        ]
    for edge, what in (
        (base.import_edge, "a harness import that is its step's only way to a "
                           "shared module"),
        (base.read_edge, "a template a harness names once and is its step's "
                         "only way to it"),
        (base.step_harness, "a harness run by one gates.yml line and reached "
                            "by nothing else"),
    ):
        if edge is None:
            return {}, [f"file-level rule A finds no {what} in this tree, so "
                        "it has nothing to mutate"]

    clean = Check(Map(base_tree), base_record)
    for name, what, test in ASSERTIONS:
        if not test(clean, base):
            problems.append(
                f"the unmutated tree fails `{name}` ({what}). Every assertion "
                "has to be green before a mutant's red means anything"
            )
    if problems:
        return {}, problems

    def check_closure_rejection(label, overrides):
        rejected = Map(base_tree.mutate(overrides=overrides))
        if not any(
            COMPILER_CLOSURE_PROBLEM in problem for problem in rejected.problems
        ):
            problems.append(
                f"the {label} compiler closure probe produced no structure problem"
            )
        if _has_head_compiler_coarse(rejected):
            problems.append(
                f"the {label} compiler closure probe still received "
                "HEAD-compiler coarse coverage"
            )

    root_manifest = base_tree.read(SELFHOST_MANIFEST)
    check_closure_rejection(
        "unknown dependency form",
        {
            SELFHOST_MANIFEST: swap(
                'compiler_plan = "../compiler-plan"',
                'compiler_plan = { path = "../compiler-plan" }',
            )(root_manifest, SELFHOST_MANIFEST)
        },
    )
    check_closure_rejection(
        "missing manifest",
        {
            SELFHOST_MANIFEST: swap(
                'compiler_plan = "../compiler-plan"',
                'compiler_plan = "../gate-map-selftest/missing"',
            )(root_manifest, SELFHOST_MANIFEST)
        },
    )
    check_closure_rejection(
        "dependency cycle",
        {
            "compiler-plan/dawn.toml": swap(
                "[deps]\n", '[deps]\nback = "../selfhost"\n'
            )(
                base_tree.read("compiler-plan/dawn.toml"),
                "compiler-plan/dawn.toml",
            )
        },
    )
    check_closure_rejection(
        "manifest parse failure",
        {SELFHOST_MANIFEST: root_manifest + "\n[\n"},
    )

    probe_manifest = swap(
        "[deps]\n",
        '[deps]\ngate_map_probe = "../gate-map-selftest/./compiler-dep"\n',
    )(root_manifest, SELFHOST_MANIFEST)
    probe_tree = base_tree.mutate(
        files=base_tree.files + [COMPILER_PROBE_MANIFEST, COMPILER_PROBE_SOURCE],
        overrides={
            SELFHOST_MANIFEST: probe_manifest,
            COMPILER_PROBE_MANIFEST: (
                'schema = 1\nname = "gate_map_compiler_probe"\n'
            ),
            COMPILER_PROBE_SOURCE: "pub fn value() -> Int = 1\n",
        },
    )
    probe_map = Map(probe_tree)
    probe_closure_problems = [
        problem
        for problem in probe_map.problems
        if COMPILER_CLOSURE_PROBLEM in problem
    ]
    if probe_closure_problems:
        problems.append(
            "the valid local dependency probe broke the compiler closure: "
            + "; ".join(probe_closure_problems)
        )
    for path in (COMPILER_PROBE_MANIFEST, COMPILER_PROBE_SOURCE):
        if not _has_head_compiler_coarse(probe_map, path):
            problems.append(
                f"the valid local dependency probe did not give `{path}` "
                "HEAD-compiler coarse coverage"
            )
    if problems:
        return {}, problems

    reds = {}
    for mutant in mutants(base):
        overrides = {
            rel: edit(base_tree.read(rel), rel) for rel, edit in mutant.edits.items()
        }
        files = mutant.files(base_tree.files) if mutant.files else None
        gm = Map(base_tree.mutate(files=files, overrides=overrides))
        if mutant.name == "prev-diff-head-leg-uses-prev":
            head_problem = any(
                "HEAD compiler premise is void" in problem
                for problem in gm.problems
            )
            cancellation_problem = any(
                "blind conclusion is void" in problem for problem in gm.problems
            )
            has_blind = any(
                obs.level == "blind"
                for obs in gm.verdict("selfhost/dawn.toml")
            )
            if not head_problem:
                problems.append(
                    "prev-diff-head-leg-uses-prev: the reviewer bypass did not "
                    "produce a HEAD compiler structure problem"
                )
            if cancellation_problem or not has_blind:
                problems.append(
                    "prev-diff-head-leg-uses-prev: changing only the compiler "
                    "on the head output leg must preserve own-content "
                    "cancellation and its blind verdict"
                )
            if _has_head_compiler_coarse(gm):
                problems.append(
                    "prev-diff-head-leg-uses-prev: the reviewer bypass still "
                    "receives selfhost HEAD-compiler coarse coverage"
                )
        if mutant.name == "selfhost-dependency-escapes-repo":
            closure_problem = any(
                COMPILER_CLOSURE_PROBLEM in problem for problem in gm.problems
            )
            if not closure_problem:
                problems.append(
                    "selfhost-dependency-escapes-repo: the normalized escape "
                    "did not produce a compiler closure structure problem"
                )
            if _has_head_compiler_coarse(gm):
                problems.append(
                    "selfhost-dependency-escapes-repo: an invalid compiler "
                    "closure still receives HEAD-compiler coarse coverage"
                )
        record = mutant.record(base_record) if mutant.record else regenerate_record(gm)
        check = Check(gm, record)
        reds[mutant.name] = {
            name for name, _, test in ASSERTIONS if not test(check, base)
        }
    return reds, problems


# ---- the record ----------------------------------------------------------

ROLES = ("counted", "recorded")


def parse_matrix(text, name):
    """-> (roles, owners, controls, reds)."""
    roles, owners, controls, reds = {}, {}, set(), {}
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "control" and len(parts) == 2:
            controls.add(parts[1])
            continue
        if len(parts) != 3:
            raise SystemExit(
                f"{name}:{n}: expected `<kind> <mutant> <value>` or "
                f"`control <assertion>`, got: {raw}"
            )
        kind, mutant, value = parts
        if kind == "role":
            if value not in ROLES:
                raise SystemExit(f"{name}:{n}: role must be one of {ROLES}")
            roles[mutant] = value
        elif kind == "owner":
            if mutant in owners:
                raise SystemExit(f"{name}:{n}: `{mutant}` already has an owner")
            owners[mutant] = value
        elif kind == "red":
            reds.setdefault(mutant, set()).add(value)
        else:
            raise SystemExit(f"{name}:{n}: unknown kind `{kind}`")
    for mutant in set(owners) | set(reds) | set(roles):
        roles.setdefault(mutant, "counted")
        reds.setdefault(mutant, set())
    return roles, owners, controls, reds


def validate_matrix(record, known_assertions):
    """Rules 1, 2, 4 and 5, read out of the record alone."""
    roles, owners, controls, reds = record
    problems = []
    counted = [m for m in sorted(roles) if roles[m] == "counted"]

    for mutant in counted:
        owner = owners.get(mutant)
        if owner is None:
            problems.append(f"{mutant}: counted but has no owning assertion")
            continue
        if owner not in reds[mutant]:
            problems.append(f"{mutant}: its owner `{owner}` is not in its red set")
        others = [m for m in counted if m != mutant and owner in reds[m]]
        if others:
            problems.append(
                f"{mutant}: its owner `{owner}` is also reddened by "
                + ", ".join(others)
                + ". An assertion two mutants can redden is owned by neither"
            )
    for mutant in sorted(roles):
        if roles[mutant] == "recorded" and mutant in owners:
            problems.append(
                f"{mutant}: recorded rather than counted, so it may not own "
                "an assertion"
            )

    owned = {owners[m] for m in counted if m in owners}
    reddened = set().union(set(), *reds.values())
    for assertion in sorted(known_assertions):
        if assertion in controls:
            if assertion in owned:
                problems.append(
                    f"{assertion}: declared a control and also owns a mutant; "
                    "it is one or the other"
                )
            continue
        if assertion not in owned and assertion not in reddened:
            problems.append(
                f"{assertion}: nothing here reddens it, no mutant is owned by "
                "it, and it is not declared a `control`. An assertion nothing "
                "can redden is a green nobody earned"
            )
    for assertion in sorted(controls):
        holders = [m for m in counted if assertion in reds[m]]
        if holders:
            problems.append(
                f"{assertion}: declared a control, so every counted mutant "
                "must keep it green, and these redden it: "
                + ", ".join(holders)
            )
    return problems


def compare_matrix(observed, record, name):
    """Rule 3: the observed red sets against the recorded ones."""
    _, _, _, rec = record
    problems = []
    for mutant in sorted(observed):
        if mutant not in rec:
            problems.append(f"{mutant}: ran, but {name} has no record of it")
            continue
        for assertion in sorted(observed[mutant] - rec[mutant]):
            problems.append(
                f"{mutant}: newly reddens `{assertion}`, which {name} does not "
                "record"
            )
        for assertion in sorted(rec[mutant] - observed[mutant]):
            problems.append(
                f"{mutant}: no longer reddens `{assertion}`, which {name} "
                "records"
            )
    for mutant in sorted(set(rec) - set(observed)):
        problems.append(f"{name} records `{mutant}`, which did not run")
    return problems


def write_matrix(path, observed, record):
    """Rewrite the red sets and nothing else.

    Which assertion owns a mutant is a design decision, so `owner` and
    `control` stay hand edits: a recorder that could reassign owners would
    launder the collision it exists to catch.
    """
    roles, owners, controls, _ = record
    old = path.read_text(encoding="utf-8").splitlines()
    header = []
    for raw in old:
        if raw.startswith("#") or not raw.strip():
            header.append(raw)
        else:
            break
    while header and not header[-1].strip():
        header.pop()

    lines = list(header) + [""]
    for assertion in sorted(controls):
        lines.append(f"control\t{assertion}")
    lines.append("")
    for mutant in sorted(set(roles) | set(observed)):
        lines.append(f"role\t{mutant}\t{roles.get(mutant, 'counted')}")
        if mutant in owners:
            lines.append(f"owner\t{mutant}\t{owners[mutant]}")
        for assertion in sorted(observed.get(mutant, ())):
            lines.append(f"red\t{mutant}\t{assertion}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


# ---- the validator's own negative controls -------------------------------

MATRIX_SAMPLE = """
control keep_green
role  alpha    counted
owner alpha    a_owner
red   alpha    a_owner
red   alpha    shared
role  beta     counted
owner beta     b_owner
red   beta     b_owner
red   beta     shared
role  gamma    recorded
red   gamma    a_owner
"""
MATRIX_SAMPLE_ASSERTIONS = {"a_owner", "b_owner", "shared", "keep_green"}


def selftest_matrix():
    """The ownership rules, each seen refusing a perturbed record.

    matrix.py's own argument: a checker whose red has never been observed is a
    checker nobody can rely on, and that applies to this one too.
    """
    good = parse_matrix(MATRIX_SAMPLE, "sample")
    failures = []
    problems = validate_matrix(good, MATRIX_SAMPLE_ASSERTIONS)
    if problems:
        failures.append("the clean sample was refused: " + "; ".join(problems))
    if compare_matrix(good[3], good, "sample"):
        failures.append("the clean sample disagreed with itself")

    perturbations = [
        (
            "an owner the mutant does not redden",
            MATRIX_SAMPLE.replace("red   alpha    a_owner\n", ""),
            None,
        ),
        (
            "an owner two counted mutants redden",
            MATRIX_SAMPLE.replace("owner beta     b_owner", "owner beta     a_owner"),
            None,
        ),
        (
            "a counted mutant with no owner",
            MATRIX_SAMPLE.replace("owner alpha    a_owner\n", ""),
            None,
        ),
        (
            "a recorded mutant that claims an owner",
            MATRIX_SAMPLE.replace("role  gamma    recorded", "role  gamma    recorded\nowner gamma    shared"),
            None,
        ),
        (
            "an assertion no mutant owns and nothing declares a control",
            MATRIX_SAMPLE,
            MATRIX_SAMPLE_ASSERTIONS | {"orphan"},
        ),
        (
            "a control a counted mutant reddens",
            MATRIX_SAMPLE.replace("control keep_green", "control shared"),
            None,
        ),
    ]
    for label, text, assertions in perturbations:
        record = parse_matrix(text, "perturbed")
        if validate_matrix(record, assertions or MATRIX_SAMPLE_ASSERTIONS):
            print(f"  refused: {label}")
        else:
            failures.append(f"perturbation not caught: {label}")

    drifts = [
        (
            "an owner that stopped going red",
            MATRIX_SAMPLE.replace("red   alpha    a_owner\n", ""),
        ),
        (
            "a collision the record does not have",
            MATRIX_SAMPLE.replace(
                "red   beta     shared", "red   beta     shared\nred   beta     a_owner"
            ),
        ),
    ]
    for label, text in drifts:
        if compare_matrix(parse_matrix(text, "perturbed")[3], good, "sample"):
            print(f"  refused: {label}")
        else:
            failures.append(f"drift not caught: {label}")

    for problem in failures:
        print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
    return failures


MUTANTS_HEADER = """\
# Which assertion each mutant reddens, and which one of them owns it.
#
# Regenerate the `red` lines with `gatemap.py --record-mutants`. The `owner`
# and `control` lines are a hand edit, because which assertion owns a mutant is
# a design decision and a recorder that could reassign owners would launder the
# collision it exists to catch.
#
# Overlaps are recorded, not forbidden; what may not overlap is an owner. See
# the block comment above `Check` in gatemap.py for the five rules, and
# scripts/pipe-contract/matrix.txt for the precedent this copies.
"""


def selftest_content_caches():
    """Warm answers must not survive script, candidate or file-list changes."""
    failures = []
    candidates = ("a watched sentence", "another watched sentence")
    if literal_matches(candidates[0], candidates) != frozenset(candidates[:1]):
        failures.append("clean literal cache probe failed")
    if literal_matches(candidates[1], candidates) != frozenset(candidates[1:]):
        failures.append("literal cache reused a different script body")
    if literal_matches(candidates[0], candidates[1:]):
        failures.append("literal cache reused removed source candidates")
    script = '(ROOT / "probe").rglob("*.dawn")'
    before = Tree(ROOT, files=["probe/old.dawn", "elsewhere/value.dawn"])
    after = before.mutate(files=["probe/new.dawn", "elsewhere/value.dawn"])
    if python_inputs(script, before) != {"probe", "probe/old.dawn"}:
        failures.append("clean Python pattern cache probe failed")
    if python_inputs(script, after) != {"probe", "probe/new.dawn"}:
        failures.append("Python pattern cache reused another tree's file list")
    if python_inputs(script.replace('"probe"', '"elsewhere"'), after) != {"elsewhere", "elsewhere/value.dawn"}:
        failures.append("Python pattern cache reused a different script body")
    for failure in failures:
        print(f"SELFTEST FAIL: {failure}", file=sys.stderr)
    if not failures:
        print("  content caches: script, candidate and file-list changes remain visible")
    return failures


def selftest_example_dependencies():
    """A new example must bring its deps into the map without editing a list.

    Both the example and package names are synthetic. Removal of either edge
    must remove just that reachability; unrelated package tests stay unwatched.
    """
    example = "examples/probe/client"
    package = "packages/probe_direct"
    leaf = "packages/probe_leaf"
    manifest = f"{example}/dawn.toml"
    source = f"{package}/src/value.dawn"
    leaf_source = f"{leaf}/src/value.dawn"
    text = {
        ".github/workflows/gates.yml": (
            "jobs:\n  probe:\n    steps:\n"
            "      - name: compile an example\n"
            "        run: ./scripts/example-tests.sh\n"
        ),
        "scripts/example-tests.sh": (
            f"units+=({example})\n" + './bin/dawn test "$u"\n'
        ),
        "bin/dawn": "#!/bin/sh\n",
        manifest: ('schema = 1\nname = "probe_client"\n[deps]\n'
                   'different_alias = "../../../packages/./probe_direct"\n'),
        f"{example}/src/main.dawn": "pub fn main() -> Unit = ()\n",
        f"{package}/dawn.toml": ('schema = 1\nname = "probe_direct"\n'
                                  '[deps]\nleaf = "../probe_leaf"\n'),
        source: "pub fn value() -> Int = 1\n",
        f"{package}/tests/separate.dawn": "test { assert(true) }\n",
        f"{leaf}/dawn.toml": 'schema = 1\nname = "probe_leaf"\n',
        leaf_source: "pub fn value() -> Int = 2\n",
    }
    tree = Tree(ROOT, files=list(text), overrides=text)
    problems = []

    def watched(gm, path):
        return any(o.level == "coarse" and o.gate_id == "probe / compile an example"
                   for o in gm.verdict(path))

    good = Map(tree)
    for path in (source, leaf_source, f"{package}/dawn.toml", f"{leaf}/dawn.toml"):
        if not watched(good, path):
            problems.append(f"example dependency probe: missing coverage for {path}")
    if watched(good, f"{package}/tests/separate.dawn"):
        problems.append("example dependency probe: unrelated tests claimed as inputs")
    removed = Map(tree.mutate(overrides={
        manifest: 'schema = 1\nname = "probe_client"\n',
    }))
    if watched(removed, source) or watched(removed, leaf_source):
        problems.append("example dependency probe: removed dependency still watched")
    shallow = Map(tree.mutate(overrides={
        f"{package}/dawn.toml": 'schema = 1\nname = "probe_direct"\n',
    }))
    if not watched(shallow, source) or watched(shallow, leaf_source):
        problems.append("example dependency probe: transitive edge removal misattributed")
    invalid = Map(tree.mutate(overrides={manifest: text[manifest] + 'missing = "../absent"\n'}))
    if (watched(invalid, source) or not any(
            "example input closure is void" in p for p in invalid.problems)):
        problems.append("example dependency probe: broken closure did not fail closed")
    no_compiler = Map(tree.mutate(overrides={
        "scripts/example-tests.sh": f"units+=({example})\n",
    }))
    if (watched(no_compiler, source) or not any(
            "compilation premise" in p for p in no_compiler.problems)):
        problems.append("example dependency probe: removed compilation still propagated")
    for problem in problems:
        print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
    if not problems:
        print("  example dependencies: direct/transitive inputs, removal, isolation, fail-closed OK")
    return problems


def selftest_harness_reader():
    """File-level rule A on a synthetic tree small enough to read whole.

    Every edge kind the reader follows, the per-script fallback, the project
    handed to the toolchain, and `unread`; then the same tree with one import
    removed, which must take the shared module away from exactly that step.
    """
    text = {
        ".github/workflows/gates.yml": (
            "jobs:\n"
            "  one:\n    steps:\n      - name: a\n        run: python3 scripts/h/a.py\n"
            "  two:\n    steps:\n      - name: b\n        run: python3 scripts/h/b.py\n"
            "  three:\n    steps:\n      - name: c\n        run: bash scripts/h/c.sh\n"
            "  four:\n    steps:\n      - name: d\n        run: ./bin/dawn test scripts/h\n"
            "  five:\n    steps:\n      - name: w\n        run: python3 scripts/w/walk.py\n"
        ),
        "bin/dawn": "#!/bin/sh\n",
        "scripts/h/a.py": (
            "from pathlib import Path\nfrom common import helper\n"
            "HERE = Path(__file__).resolve().parent\n"
            "TEXT = (HERE / \"only-a.txt\").read_text()\n"
        ),
        "scripts/h/b.py": "from common import SHARED\nprint(SHARED.read_text())\n",
        "scripts/h/common.py": (
            "import shutil\nfrom pathlib import Path\n"
            "HERE = Path(__file__).resolve().parent\n"
            "SHARED = HERE / \"shared.dawn.txt\"\n"
            "def helper():\n    return 1\n"
            "def main():\n    shutil.copytree(HERE, \"elsewhere\")\n"
        ),
        "scripts/h/c.sh": (
            "here=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"\n"
            "source \"$here/lib.sh\"\ncc -o probe \"$here/probe.c\"\n"
        ),
        "scripts/h/lib.sh": "echo lib\n",
        "scripts/h/probe.c": "#include \"probe.h\"\nint main(void) { return 0; }\n",
        "scripts/h/probe.h": "#define PROBE 1\n",
        "scripts/h/only-a.txt": "a\n",
        "scripts/h/shared.dawn.txt": "fn shared() -> Int = 1\n",
        "scripts/h/dawn.toml": 'schema = 1\nname = "h"\n',
        "scripts/h/src/main.dawn": "pub fn main() -> Unit = ()\n",
        "scripts/h/README.md": "# h\n",
        "scripts/w/walk.py": (
            "import shutil\nfrom pathlib import Path\n"
            "shutil.copytree(Path(__file__).parent, \"elsewhere\")\n"
        ),
        "scripts/w/README.md": "# w\n",
    }
    tree = Tree(ROOT, files=list(text), overrides=text)

    def jobs(gm, path):
        return sorted({o.gate_id.split(" / ")[0] for o in gm.verdict(path)
                       if o.level in ("exact", "coarse")})

    want = {
        "scripts/h/common.py": ["one", "two"],
        "scripts/h/shared.dawn.txt": ["one", "two"],
        "scripts/h/only-a.txt": ["one"],
        "scripts/h/a.py": ["one"],
        "scripts/h/lib.sh": ["three"],
        "scripts/h/probe.c": ["three"],
        "scripts/h/probe.h": ["three"],
        "scripts/h/dawn.toml": ["four"],
        "scripts/h/src/main.dawn": ["four"],
        "scripts/h/README.md": [],
        "scripts/w/README.md": ["five"],
    }
    problems = []
    good = Map(tree)
    for path, expected in want.items():
        got = jobs(good, path)
        if got != expected:
            problems.append(f"harness reader probe: {path} is seen by {got}, "
                            f"expected {expected}")
    if sorted(good.unread) != ["scripts/h/README.md"]:
        problems.append(f"harness reader probe: unread is {sorted(good.unread)}, "
                        "expected only scripts/h/README.md")
    if set(good.fallback) != {"scripts/w"}:
        problems.append(f"harness reader probe: fell back for {sorted(good.fallback)}, "
                        "expected only scripts/w (walk.py copies its directory; "
                        "common.main does too, but nobody imports main)")
    dropped = Map(tree.mutate(overrides={
        "scripts/h/a.py": text["scripts/h/a.py"].replace("from common import helper\n", ""),
    }))
    for path, expected in (("scripts/h/common.py", ["two"]),
                           ("scripts/h/shared.dawn.txt", ["two"]),
                           ("scripts/h/only-a.txt", ["one"])):
        got = jobs(dropped, path)
        if got != expected:
            problems.append(f"harness reader probe, import dropped: {path} is "
                            f"seen by {got}, expected {expected}")
    for problem in problems:
        print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
    if not problems:
        print("  harness reader: imports, templates, source, includes, project, "
              "per-script fallback, unread and a dropped import OK")
    return problems


def selftest(record_path=None, record_mode=False):
    record_path = record_path or (HERE / "mutants.txt")
    failures = (selftest_matrix() + selftest_content_caches()
                + selftest_example_dependencies() + selftest_harness_reader())
    if failures:
        return 1

    base_tree = Tree(ROOT)
    base_record = (HERE / "unseen.txt").read_text(encoding="utf-8")
    observed, problems = observe(base_tree, base_record)
    for problem in problems:
        print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1

    if not record_path.exists():
        if not record_mode:
            raise SystemExit(f"{record_path} is missing; run --record-mutants")
        record_path.write_text(MUTANTS_HEADER, encoding="utf-8")
    record = parse_matrix(record_path.read_text(encoding="utf-8"), str(record_path))

    if record_mode:
        write_matrix(record_path, observed, record)
        print(f"recorded {record_path}")
        return 0

    known = {name for name, _, _ in ASSERTIONS}
    problems = validate_matrix(record, known) + compare_matrix(
        observed, record, record_path.name
    )
    for problem in problems:
        print(f"SELFTEST FAIL: {problem}", file=sys.stderr)
    if problems:
        return 1
    for mutant in sorted(observed):
        reds = sorted(observed[mutant])
        print(f"  {mutant}: {', '.join(reds) if reds else '(silent, by record)'}")
    print(
        f"selftest: {len(observed)} mutant(s) against {len(ASSERTIONS)} "
        "assertion(s), ownership intact"
    )
    return 0


# ---------------------------------------------------------------------------


UNSEEN_HEADER = """\
# Paths in this repository that no gate watches, and why each one is not
# watched.
#
# A ratchet, not a to-do list: `gatemap.py --check` compares it with what the
# rules compute and fails in both directions, so a new unwatched file cannot
# arrive quietly and a line here cannot outlive the gap it records.
#
# Each line is `<path>  <kind>: <why>`. The kind is checked against the map, so
# a reason cannot go on claiming something the tree stopped supporting:
#
#   no-gate     nothing in any workflow reaches this path at any strength
#   unread      a file in a harness directory that no script run from there
#               imports, sources or names (plan.py selects no job for it)
#   blind-only  gates reach it, and rule D says each of them cancels it out
#   tag-only    watched, but only by a workflow that runs on a tag
#
# The prose after the kind is for a person, and it is the part that says
# whether the gap is deliberate. Regenerate the path list with
# `--record-unseen`, which keeps the reasons it already has and marks a new
# line for you to write; read the diff, because a line appearing is the news.
"""

NEEDS_A_REASON = "TODO, say why nothing watches this and delete this word"


def record_unseen(gm, path):
    """Rewrite the path list, keeping every reason already written."""
    entries, _ = parse_unseen(path.read_text(encoding="utf-8") if path.exists() else "")
    computed = gm.unseen()
    width = max((len(p) for p in computed), default=0) + 2
    lines = []
    for rel in computed:
        kind, why = entries.get(rel, (kind_for(gm, rel) or "no-gate",
                                      NEEDS_A_REASON))
        lines.append(f"{rel.ljust(width)}{kind}: {why}")
    path.write_text(UNSEEN_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    fresh = [p for p in computed if p not in entries]
    print(f"recorded {len(computed)} unwatched path(s), {len(fresh)} new")
    for rel in fresh:
        print(f"  needs a reason: {rel}")
    return 0


def print_labels(gm):
    """Which differential owns which declarable label.

    `prev-diff` names a job with four differentials in it, and a label under
    one of them is invisible to the other three. Both of those were prose.
    """
    for script, gate, labels in gm.label_owners():
        where = gate.id if gate else "(no workflow step runs this)"
        print(f"{script}\n  {where}")
        for label in labels:
            print(f"    {label}")
        print()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="which gates can see a change to these paths"
    )
    ap.add_argument("paths", nargs="*", help="repository-relative paths")
    ap.add_argument("--changed", metavar="REV",
                    help="ask about the files changed since REV")
    ap.add_argument("--compiler-inputs", action="store_true",
                    help="print the selfhost compiler's SourcePlan input manifest")
    ap.add_argument("--check", action="store_true",
                    help="the CI check: selftest, structure, ratchet, fixtures")
    ap.add_argument("--selftest", action="store_true",
                    help="the mutant matrix alone")
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--labels", action="store_true",
                    help="which differential owns which Emit-Change label")
    ap.add_argument("--unseen", action="store_true",
                    help="print every path no gate watches")
    ap.add_argument("--record-unseen", action="store_true")
    ap.add_argument("--record-mutants", action="store_true",
                    help="rewrite the red sets in mutants.txt; owners stay a "
                         "hand edit")
    args = ap.parse_args(argv)

    if args.compiler_inputs:
        incompatible = (
            args.paths
            or args.changed
            or args.check
            or args.selftest
            or args.fixtures
            or args.labels
            or args.unseen
            or args.record_unseen
            or args.record_mutants
        )
        if incompatible:
            ap.error("--compiler-inputs cannot be combined with another action")
        output, problems = compiler_inputs_text(Tree(ROOT))
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        if problems:
            return 1
        sys.stdout.write(output)
        return 0

    if args.selftest or args.record_mutants:
        return selftest(record_mode=args.record_mutants)

    if args.fixtures:
        problems = run_fixtures(HERE / "fixtures.txt")
        for p in problems:
            print(f"FIXTURE FAIL: {p}", file=sys.stderr)
        return 1 if problems else 0

    gm = Map(Tree(ROOT))

    if args.record_unseen:
        return record_unseen(gm, HERE / "unseen.txt")

    if args.labels:
        print_labels(gm)
        return 0

    if args.unseen:
        for f in gm.unseen():
            print(f)
        return 0

    if args.check:
        rc = 0
        print("selftest:")
        if selftest():
            return 1
        record = (HERE / "unseen.txt").read_text(encoding="utf-8")
        problems = check_structure(gm) + ratchet_problems(gm, record)
        for p in problems:
            print(f"FAIL: {p}", file=sys.stderr)
            rc = 1
        print("fixtures:")
        fx = run_fixtures(HERE / "fixtures.txt")
        for p in fx:
            print(f"FIXTURE FAIL: {p}", file=sys.stderr)
            rc = 1
        if rc == 0:
            unwatched = len(gm.unseen())
            print(
                f"OK: {len(gm.gates)} gate(s), "
                f"{len(gm.tree.files) - unwatched} of "
                f"{len(gm.tree.files)} tracked path(s) watched, "
                f"{unwatched} recorded as unwatched with a reason"
            )
        return rc

    paths = list(args.paths)
    additional_std_modules = None
    if args.changed:
        # The head modules are already in gm. Supplying the base modules lets
        # rule F recognise a registered path removed or renamed since REV.
        additional_std_modules = std_modules_at_revision(args.changed)
        paths += changed_paths(args.changed)
    if not paths:
        ap.error("give at least one path, or --changed REV, or --check")

    report(gm, paths, additional_std_modules)

    labels, tag = declared_window(ROOT)
    if labels is None:
        print(f"note: {tag}, so the declaration window could not be read")
    elif labels:
        print(
            f"note: these labels are already declared since {tag}. A "
            "declaration anywhere in the window shields every later difference "
            "carrying it (CONTRIBUTING §5), so the seed oracle cannot answer a "
            "question about one of them. Measuring a change under a declared "
            "label needs an unmasked control built from its true parent "
            "commit, never from the seed jar:"
        )
        for label in sorted(labels):
            print(f"        {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
