#!/usr/bin/env python3
"""Which gates can see a change to this path.

    scripts/gate-map/gatemap.py selfhost/src/main.dawn
    scripts/gate-map/gatemap.py --changed origin/main
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

  exact    Something recorded in the repository moves when this file changes:
           a Core golden hash, or an `Emit-Change` label. Editing the file
           forces a deliberate re-record or declaration, so no change of any
           kind passes silently.

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

  (none)   No gate. Reported as such, and ratcheted in unseen.txt.

## The rules, and the file each is derived from

  A  A gate runs a script, so that script's own directory under scripts/ is
     exact for it, fixtures included, since the directory is one gate's code.
     From: the `run:` commands in .github/workflows/*.yml, followed through
     the scripts those scripts run.
  B  A gate's script names a path, so that path is coarse for it. Slash-bearing
     tokens, shell globs, and for Python gates the `ROOT / "a" / "b"` joins and
     `.glob()` patterns that a regular expression cannot tell from division.
     Bare directory names count only where a word cannot be prose: handed to
     the toolchain, or appended to a list of units.
  C  The Core golden records one hash per compiler module, so every module it
     names is exact for the Core IR golden step. This is what 98b9896 needed.
     From: scripts/core-golden/selfhost.sha.
  D  prev-diff compiles each corpus target's source with *both* toolchains, so
     the target's own content cancels: it is blind there. std is the exception,
     because the N-1 side is pointed at the std it was released with.
     From: the `emit <target>` labels in scripts/emit-labels.txt, taken from
     that script's own section, and the `--std "$(seed_std_dir)"` in
     scripts/selfhost-prev-diff.sh, whose continued presence is checked.
  E  A gate that spells out a string a source module builds is coupled to that
     module, and the coupling is invisible from either side. This is what
     3c51ae1 and 9e64179 needed.
     From: string literals in the Dawn sources against the gate scripts' text.

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
  structure  every path-shaped command in every workflow resolves; every module
             in the Core golden resolves to a file that exists; every compiler
             module has a golden entry; every label section names a
             differential some step runs; rule D's premises still hold. A rule
             whose premise moved is void, not stale.
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
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

WORKFLOWS = ["gates.yml", "ci.yml", "release.yml"]

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

# The three tree files this checker reads as evidence, named once so that rules
# C and D, rule A/B's attribution and the structural checks all mean the same
# files.
CORE_GOLDEN = "scripts/core-golden/selfhost.sha"
EMIT_LABELS = "scripts/emit-labels.txt"
PREV_DIFF = "scripts/selfhost-prev-diff.sh"

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
SELF_INPUTS = (CORE_GOLDEN, EMIT_LABELS, PREV_DIFF)


PATH_TOKEN = re.compile(r"[A-Za-z0-9_*][A-Za-z0-9_.$@+*-]*(?:/[A-Za-z0-9_.$@+*-]+)+")
BARE_TOKEN = re.compile(r"(?<![\w./-])([A-Za-z][\w-]*)(?![\w./-])")
DAWN_LITERAL = re.compile(r'"((?:[^"\\\n]|\\.)*)"')

# A line that only prints. `echo "... (selfhost)"` is not a gate reading
# selfhost, and bare directory names are common enough in prose that admitting
# them from message text would make every job look as if it watched everything.
PRINTS_ONLY = re.compile(r"^\s*(echo|printf)\b")

LEVELS = ("exact", "coupled", "coarse", "blind")


def run_git(args, cwd=ROOT, check=True):
    proc = subprocess.run(
        ["git", "-C", str(cwd)] + args, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


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
    """
    return "\n".join(
        ln for ln in text.splitlines() if not ln.lstrip().startswith("#")
    )


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
        # `packages/*/dawn.toml`, `examples/*/`, `scripts/core-golden/*.core`:
        # a shell glob is how several gates state their input, so expand it
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
    import ast

    try:
        tree_ast = ast.parse(text)
    except SyntaxError:
        return set()

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

    found = set()
    for node in ast.walk(tree_ast):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if id(node) in inner:
                continue
            base = joined(node)
            if base and base[0]:
                found |= resolve(base[0], tree)
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
                found |= {
                    f
                    for f in tree.files
                    if f.startswith(prefix)
                    and fnmatch_path(f.rsplit("/", 1)[-1], pattern)
                }
            else:
                found |= resolve(prefix + pattern, tree)
    return found


def is_script(path, tree):
    return path in tree.fileset and Path(path).suffix in (".sh", ".py")


SEGMENT_SPLIT = re.compile(r"[\n;|&]+|\$\(|`|\(\s")
COMMAND_PREFIX = re.compile(
    r"^\s*(?:(?:if|then|else|elif|while|until|do|!|time|exec|command|bash|sh|"
    r"python3?|env|sudo|source|\.|\w+=\S*)\s+)*"
)


def executed_scripts(text, tree):
    """Scripts this text *runs*, as opposed to ones it mentions.

    doc-check.py's docstring names scripts/native-cli-diff.sh while explaining
    a process-group rule. Reading that as "the documentation job runs the
    native CLI differential" put thirteen of the driver's usage strings under
    the wrong gate, so the token has to be in command position: first word of a
    segment, after the words that can precede a command.
    """
    found = set()
    for segment in SEGMENT_SPLIT.split(text):
        segment = re.sub(r"\$\{?\w+\}?/", "", segment)
        rest = COMMAND_PREFIX.sub("", segment)
        word = rest.strip().split()[:1]
        if not word:
            continue
        for cand in resolve(word[0], tree):
            if is_script(cand, tree):
                found.add(cand)
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
        direct |= executed_scripts(command, tree)
    if not transitive:
        return direct
    scripts = set()
    frontier = set(direct)
    while frontier:
        script = frontier.pop()
        if script in scripts:
            continue
        scripts.add(script)
        if script == SELF:
            continue
        body = strip_comments(tree.read(script))
        frontier |= {
            s for s in executed_scripts(body, tree) if s.startswith("scripts/")
        }
    return scripts


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
        self.manifests = manifests(tree)
        self.gates = gates_of(tree)
        self.by_path = {}
        self.owned = {}
        self.direct = {}
        self.problems = []
        self._build()

    def add(self, path, obs):
        self.by_path.setdefault(path, []).append(obs)

    def add_under(self, prefix, obs):
        for f in self.tree.under(prefix):
            self.add(f, obs)

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
                # A: the gate runs this script, so the script's own directory
                # is the gate's code. `scripts/foo/run.sh` owns `scripts/foo`;
                # `scripts/doc-check.py` owns only itself.
                # `scripts/foo/run.sh` owns `scripts/foo`, fixtures included:
                # that directory is one gate's code and nothing else's.
                # `site/build.sh` owns only itself; site/ is the subject it
                # builds, not the gate, and marking the whole directory exact
                # would say a page's text is recorded byte for byte somewhere.
                owner = str(Path(script).parent)
                target = owner if owner.startswith("scripts/") else script
                self.owned[gate.id].add(target)
                self.add_under(
                    target,
                    Observation(
                        "exact",
                        gate.id,
                        f"{gate.where()} runs {script}",
                        gate.tag_only,
                    ),
                )
                # B: whatever that script names. Helpers it calls are inside
                # its own directory, so reading them is reading the gate.
                body = ""
                for sibling in tree.under(target):
                    if sibling == SELF:
                        continue
                    if Path(sibling).suffix in (".sh", ".py"):
                        body += strip_comments(tree.read(sibling)) + "\n"
                names = path_tokens(body, tree) | shell_targets(body, tree)
                if Path(script).suffix == ".py":
                    names |= python_inputs(tree.read(script), tree)
                for token in sorted(names):
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
                    if token in tree.fileset and Path(token).suffix in (".sh", ".py"):
                        continue
                    self.add_under(
                        token,
                        Observation(
                            "coarse",
                            gate.id,
                            f"{gate.where()} runs `{command.strip()}`",
                            gate.tag_only,
                        ),
                    )
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
            if any("selfhost-core-diff.sh" in c for c in gate.commands):
                return gate
        return None

    def core_modules(self):
        """Module name -> source path, from the golden that records them.

        A module whose package no name declares is left out and reported
        separately: "this package is not declared anywhere" and "this file is
        missing" are two different pieces of news, and folding them together
        would let one mutant redden both.
        """
        record = self.tree.read(CORE_GOLDEN)
        packages, _ = self.manifests
        out = {}
        for line in record.splitlines():
            parts = line.split()
            if len(parts) != 2 or not parts[1].endswith(".core"):
                continue
            module = parts[1][2:-len(".core")] if parts[1].startswith("./") else parts[1][:-len(".core")]
            path, unknown = module_source(module, self.tree, packages)
            if unknown is None:
                out[module] = path
        return out

    def undeclared_packages(self):
        """Golden modules whose package name no manifest declares."""
        packages, _ = self.manifests
        out = []
        for line in self.tree.read(CORE_GOLDEN).splitlines():
            parts = line.split()
            if len(parts) != 2 or not parts[1].endswith(".core"):
                continue
            module = parts[1][2:-len(".core")] if parts[1].startswith("./") else parts[1][:-len(".core")]
            if module_source(module, self.tree, packages)[1] is not None:
                out.append(module)
        return out

    def _rule_c(self):
        gate = self.core_gate()
        if gate is None:
            self.problems.append(
                "no workflow step runs scripts/selfhost-core-diff.sh, so the "
                "Core golden rule has no gate to attribute; rule C is void"
            )
            return
        for module, path in self.core_modules().items():
            if path is None:
                self.problems.append(
                    f"{CORE_GOLDEN} records module `{module}`, "
                    f"which resolves to no file in the tree"
                )
                continue
            self.add(
                path,
                Observation(
                    "exact",
                    gate.id,
                    f"core-golden/selfhost.sha records module `{module}`",
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

        for target in targets:
            if not tree.exists(target):
                self.problems.append(
                    f"emit-labels.txt names corpus target `{target}`, which is "
                    "not in the tree"
                )
                continue
            self.add_under(
                target,
                Observation(
                    "blind",
                    gate.id,
                    f"`emit {target}` compiles this same source with both "
                    "toolchains, so its content cancels",
                ),
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

    def _build(self):
        self._rule_ab()
        self._rule_c()
        self._rule_d()
        self._rule_e()

    # ---- queries ------------------------------------------------------
    def verdict(self, path):
        obs = sorted(self.by_path.get(path, []), key=lambda o: o.key())
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


PKG_PREFIX = "dawn$pkg$"
MANIFEST = "dawn.toml"
MANIFEST_NAME = re.compile(r'^\s*name\s*=\s*"([^"]+)"\s*$')


def manifests(tree):
    """-> ({package name: its directory}, [problem]).

    A package's directory is not its name, and reading it as one is how this
    file's own rule C broke: `dawn$pkg$compiler_plan` was resolved by turning
    the `_` back into a `-` and looking for a directory of that name, which
    happened to work and was two guesses stacked. Neither holds.
    `compiler-plan/dawn.toml` declares `name = "compiler_plan"` with the
    underscore, so there is no mangling to undo; and `packages/web/dawn.toml`
    already declares `name = "web2"` under the repository's v2-in-name rule,
    in a directory still called `web`. The moment that package enters the Core
    golden the guess reds on a correct tree.

    So the name comes from the manifest that declares it, which is the only
    thing that ever knew it. `analyze.dawn` builds the class name as
    `dawn$pkg$` ++ the manifest's `name`, verbatim.

    The scan stops at the first `[section]` header: `name` inside `[deps]` is
    a dependency alias, not this package's name.
    """
    by_name, source, problems = {}, {}, []
    for f in tree.files:
        if f != MANIFEST and not f.endswith("/" + MANIFEST):
            continue
        directory = f[: -(len(MANIFEST) + 1)] if "/" in f else "."
        name = None
        for line in tree.read(f).splitlines():
            if line.lstrip().startswith("["):
                break
            match = MANIFEST_NAME.match(line)
            if match:
                name = match.group(1)
                break
        if name is None:
            problems.append(
                f"{f} declares no `name` before its first section, so the "
                "package in that directory cannot be named by anything that "
                "reads the golden"
            )
            continue
        if name in by_name:
            problems.append(
                f"the package name `{name}` is declared by two manifests, "
                f"{source[name]} and {f}, so a module recorded as "
                f"`{PKG_PREFIX}{name}.<module>` names two directories"
            )
            continue
        by_name[name] = directory
        source[name] = f
    return by_name, problems


def module_source(module, tree, packages):
    """`check.checker` -> selfhost/src/check/checker.dawn, and the two other
    shapes the golden uses: `std.str` for the bundled std, and
    `dawn$pkg$<name>.<module>` for a source package.

    -> (path, None) when it resolves, (None, None) when the file is missing,
    and (None, module) when no declared package name begins it.
    """
    if module.startswith(PKG_PREFIX):
        rest = module[len(PKG_PREFIX):]
        # the longest declared name this module begins with. Longest because a
        # package may be named as a prefix of another, and the manifest set is
        # what decides where the name ends; splitting on the first `.` would
        # be a guess about the name's shape.
        owner = None
        for name in packages:
            if rest.startswith(name + ".") and (owner is None or len(name) > len(owner)):
                owner = name
        if owner is None:
            return None, module
        inner = rest[len(owner) + 1:].replace(".", "/")
        cand = f"{packages[owner]}/src/{inner}.dawn"
        return (cand if cand in tree.fileset else None), None
    if module.startswith("std."):
        cand = f"std/{module[len('std.'):].replace('.', '/')}.dawn"
        return (cand if cand in tree.fileset else None), None
    cand = f"selfhost/src/{module.replace('.', '/')}.dawn"
    return (cand if cand in tree.fileset else None), None


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


def couplings(tree):
    """(source, gate script, literal) for every string constant a Dawn module
    builds that a gate script also spells out."""
    scripts = {}
    for f in tree.files:
        if f.startswith("scripts/") and Path(f).suffix in (".sh", ".py"):
            scripts[f] = tree.read(f)
    roots = tuple(r + "/" for r in source_roots(tree))
    # One haystack first. The pairwise scan is literals times scripts, which is
    # most of a run of this file; almost every literal is in no script at all,
    # so the join answers that in one pass and the loop below only runs for the
    # handful that survive.
    blob = "\n".join(scripts.values())
    out = []
    for f in tree.files:
        if not f.endswith(".dawn") or not f.startswith(roots):
            continue
        text = tree.read(f)
        lits = {m.group(1) for m in DAWN_LITERAL.finditer(text)}
        for lit in sorted(lits):
            if not interesting_literal(lit) or lit not in blob:
                continue
            for script, body in scripts.items():
                if lit in body:
                    out.append((f, script, lit))
    return out


# ---------------------------------------------------------------------------
# reporting


def report(gm, paths, stream=sys.stdout):
    for path in paths:
        path = path.rstrip("/")
        members = gm.tree.under(path)
        if not members:
            print(f"{path}\n  ?       not a tracked path in this tree\n", file=stream)
            continue
        if members != [path]:
            print(f"{path}  ({len(members)} tracked files)", file=stream)
            obs = []
            for member in members:
                obs.extend(gm.verdict(member))
        else:
            print(path, file=stream)
            obs = gm.verdict(path)
        if not obs:
            print("  none    no gate reads, runs or records this file", file=stream)
        # One line per (level, gate). A driver module can share a dozen usage
        # strings with one differential; twelve identical verdicts is a wall,
        # so the longest reason stands for the group and the rest are counted.
        groups = {}
        for o in obs:
            groups.setdefault((o.level, o.gate_id, o.tag_only), []).append(o.why)
        for (level, gate_id, tag_only), whys in sorted(
            groups.items(), key=lambda kv: (LEVELS.index(kv[0][0]), kv[0][1])
        ):
            tag = " [tag only]" if tag_only else ""
            more = f"  (+{len(whys) - 1} more)" if len(whys) > 1 else ""
            print(f"  {level:<7} {gate_id}{tag}{more}", file=stream)
            print(f"          {max(whys, key=len)}", file=stream)
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

    # the manifest map rule C resolves package modules through. A name that is
    # declared twice, or not at all, is reported here and nowhere else, so that
    # "the package is not named" and "the file is missing" stay two answers.
    problems += gm.manifests[1]
    for module in gm.undeclared_packages():
        problems.append(
            f"{CORE_GOLDEN} records module `{module}`, and no manifest "
            "declares a package whose name begins it. A package's directory "
            "is not its name; read dawn.toml"
        )

    # every compiler module has a golden entry (rule C, the other direction)
    recorded = set()
    for module, path in gm.core_modules().items():
        if path:
            recorded.add(path)
    for f in tree.files:
        if f.startswith("selfhost/src/") and f.endswith(".dawn") and f not in recorded:
            problems.append(
                f"{f} is a compiler module with no entry in "
                "scripts/core-golden/selfhost.sha. Either the golden is "
                "stale or the module is unreachable, and both are news"
            )

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
UNSEEN_KINDS = {
    # nothing in any workflow, at any strength, reaches this path
    "no-gate": lambda obs: not obs,
    # gates reach it, but rule D says each of them cancels its content out
    "blind-only": lambda obs: bool(obs) and all(o.level == "blind" for o in obs),
    # watched, but only by a workflow that runs on a tag rather than on a push
    "tag-only": lambda obs: bool(obs)
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
        elif not test(gm.by_path.get(path, [])):
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
        contains <rev>:<path> <text>     the file at that rev has that text
        lacks <rev>:<path> <text>        it does not
        golden-moved <commit> <module>   the commit rewrote that module's line
                                         in the Core golden

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
            diff = run_git(["show", "--format=", commit, "--", CORE_GOLDEN])
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
                    f"not rewrite `{module}`'s line in {CORE_GOLDEN}"
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
            lines = []
            for query in fx["query"]:
                for o in gm.verdict(query):
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
        self.unwatched = len(Map(tree).unseen())
        self.coupling = choose_coupling(tree)
        self.package = choose_package(tree)


def choose_package(tree):
    """-> (name, its manifest) for a package the Core golden records.

    Chosen from the tree for the reason `choose_coupling` is: a hard-coded
    package is a fixture nobody re-measures, and this one was caught being
    exactly that. The mutants below named `json`, which is right here and
    wrong on the branch that renames it to `json2` while keeping the
    directory, so `--check` could not run there at all.
    """
    packages, _ = manifests(tree)
    golden = tree.read(CORE_GOLDEN)
    for name in sorted(packages):
        manifest = f"{packages[name]}/{MANIFEST}"
        if f"{PKG_PREFIX}{name}." not in golden:
            continue
        if tree.read(manifest).count(f'name = "{name}"') != 1:
            continue
        return name, manifest
    raise SystemExit(
        "gate-map selftest: no package in the Core golden has a manifest "
        "declaring its name exactly once, so rule C's package half has "
        "nothing to mutate"
    )


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


def _clean(problems, needle):
    return not any(needle in p for p in problems)


def _cites(check, path, script):
    return any(script in obs.why for obs in check.map.verdict(path))


# Each entry is (name, what it asserts, predicate). The predicate is true when
# the assertion is green, so a mutant "reddens" one by making it false.
ASSERTIONS = [
    (
        "golden_module_resolves",
        "every module the Core golden records names a file in the tree",
        lambda c, b: _clean(c.problems, "resolves to no file in the tree"),
    ),
    (
        "golden_covers_selfhost",
        "every compiler module has an entry in the Core golden",
        lambda c, b: _clean(c.problems, "with no entry in"),
    ),
    (
        "package_name_declared",
        "every package the Core golden names is declared by a manifest, "
        "which is the only thing that knows a package's name",
        lambda c, b: _clean(c.problems, "no manifest declares a package"),
    ),
    (
        "package_name_unambiguous",
        "no package name is declared by two manifests",
        lambda c, b: _clean(c.problems, "is declared by two manifests"),
    ),
    (
        "manifest_names_its_package",
        "every manifest names the package in its directory",
        lambda c, b: _clean(c.problems, "declares no `name` before"),
    ),
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
        "python_join_probe",
        "rule B reads `ROOT / \"a\" / \"b\"` joins, which is the only reason "
        "anything watches the workflow files",
        lambda c, b: _cites(
            c, ".github/workflows/release.yml", "scripts/check-gate-budgets.py"
        ),
    ),
    (
        "glob_literal_probe",
        "a glob with a literal head is expanded against the tree",
        lambda c, b: not _cites(
            c, "scripts/pipe-contract/matrix.txt", "scripts/doc-check.py"
        ),
    ),
    (
        "unwatched_floor",
        "the unwatched set never collapses; a map that says everything is "
        "covered says nothing",
        lambda c, b: len(c.map.unseen()) >= b.unwatched,
    ),
]


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
    record: a package's golden entries are one line per module, and pinning
    the count would make the selftest brittle about how many modules a package
    has. What must still fail loudly is the anchor going away entirely.
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


def kind_for(obs):
    for kind, test in UNSEEN_KINDS.items():
        if test(obs):
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
        kind = kind_for(gm.by_path.get(path, [])) or "no-gate"
        lines.append(f"{path}  {kind}: {note}")
    return "\n".join(lines) + "\n"


# A suffix and a path the tree never has, so a mutant that plants one is
# planting something and not colliding with something.
RENAMED = "_renamed_by_the_selftest"
PROBE_MANIFEST = "scripts/gate-map/selftest-probe/dawn.toml"


class Mutant:
    """One otherwise-valid tree (or record) with one thing wrong with it."""

    def __init__(self, name, why, files=None, edits=None, record=None):
        self.name = name
        self.why = why
        self.files = files
        self.edits = edits or {}
        self.record = record


def mutants(base):
    """The mutant set, built against the clean tree's baseline."""
    return [
        Mutant(
            "golden-names-a-ghost-module",
            "rule C, forwards: a golden entry for a module that is not there",
            edits={CORE_GOLDEN: append("0" * 64 + "  ./front.ghost.core\n")},
        ),
        Mutant(
            "golden-forgets-a-module",
            "rule C, backwards: a compiler module the golden does not record",
            edits={CORE_GOLDEN: drop_line("./main.core")},
        ),
        Mutant(
            "package-renamed-in-its-manifest",
            "rule C's package half. The manifest is the only thing that knows "
            "a package's name, and while rule C guessed the name from the "
            "directory this mutant was silent: nothing read the file it edits",
            edits={
                base.package[1]: swap(
                    f'name = "{base.package[0]}"',
                    f'name = "{base.package[0]}{RENAMED}"',
                )
            },
        ),
        Mutant(
            "two-manifests-one-package-name",
            "a package name that names two directories, so a golden module "
            "under it would resolve to either. It adds a manifest rather than "
            "editing one, which keeps it away from `package_name_declared`: "
            "the added file sorts after the real one, so the golden still "
            "resolves and only the ambiguity is news",
            files=lambda fs: fs + [PROBE_MANIFEST],
            edits={
                PROBE_MANIFEST: provide(
                    f'schema = 1\nname = "{base.package[0]}"\n'
                )
            },
        ),
        Mutant(
            "a-manifest-that-names-nothing",
            "a package with no name at all, added the same way and for the "
            "same reason",
            files=lambda fs: fs + [PROBE_MANIFEST],
            edits={PROBE_MANIFEST: provide("schema = 1\n")},
        ),
        Mutant(
            "package-whose-name-is-not-its-directory",
            "the shape the lib-web3-json2 branch has, where a major bump "
            "renames the package and keeps the directory. Recorded with an "
            "empty red set: a manifest-driven rule C is unmoved by it, and a "
            "rule C that resolved names to directories reddened "
            "golden_module_resolves on a perfectly good tree, which is how "
            "this was found. `package-renamed-in-its-manifest` edits the same "
            "manifest and is counted, so the pair cannot go vacuous",
            edits={
                base.package[1]: swap(
                    f'name = "{base.package[0]}"',
                    f'name = "{base.package[0]}{RENAMED}"',
                ),
                CORE_GOLDEN: swap_all(
                    f"{PKG_PREFIX}{base.package[0]}.",
                    f"{PKG_PREFIX}{base.package[0]}{RENAMED}.",
                ),
            },
        ),
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
            record=lambda text: swap(
                "LICENSE                                    no-gate:", "LICENSE  #"
            )(text, "unseen.txt"),
        ),
        Mutant(
            "a-recorded-gap-with-the-wrong-reason",
            "a reason the map contradicts. The kind is checked, so it cannot "
            "go on claiming something the tree stopped supporting",
            record=lambda text: swap(
                "LICENSE                                    no-gate:",
                "LICENSE                                    tag-only:",
            )(text, "unseen.txt"),
        ),
        Mutant(
            "rewrite-a-shared-sentence",
            "rule E run backwards: rewrite the sentence a gate spells out and "
            "the coupling has to go, which is the first of the two failures",
            edits={base.coupling[0]: rewrite_coupling(base)},
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

    clean = Check(Map(base_tree), base_record)
    for name, what, test in ASSERTIONS:
        if not test(clean, base):
            problems.append(
                f"the unmutated tree fails `{name}` ({what}). Every assertion "
                "has to be green before a mutant's red means anything"
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


def selftest(record_path=None, record_mode=False):
    record_path = record_path or (HERE / "mutants.txt")
    failures = selftest_matrix()
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
        kind, why = entries.get(rel, (kind_for(gm.by_path.get(rel, [])) or "no-gate",
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
    if args.changed:
        paths += [
            p
            for p in run_git(["diff", "--name-only", args.changed]).split("\n")
            if p
        ]
    if not paths:
        ap.error("give at least one path, or --changed REV, or --check")

    report(gm, paths)

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
