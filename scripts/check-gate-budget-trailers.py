#!/usr/bin/env python3
"""Hold a raised gate total, and a lost gate step, to a line that says so.

scripts/check-gate-budgets.py holds each gate workflow's `3x` claims under a
total its file carries (`# push-total:` in gates.yml, `# path-total:` in
tile.yml). A total nobody may raise is a total the next real gate cannot get
past, and a total anybody may raise in silence holds nothing: the pole was
meant to be redone "when the job set changes" and, measured 2026-09-25, sat
130s under the queue floor it was derived from, with every gate green. So the
line may go up, and the push that takes it up has to say so in its commit
messages, one line per total:

    Gate-Budget(push-total): 29319s -> 30100s <why>
    Gate-Budget(path-total): 5484s -> 5600s <why>

The numbers are checked against the two trees. A push that raises a total in
two commits may declare each step (29319 -> 29700 and 29700 -> 30100); what
is required is a chain of declared steps from the total at the base of the
push to the total at its tip. The reason is required and is not read.

Going down needs no line, with one exception, and the exception is the point
of reading steps.lock.json here as well. A total that drops because a job got
faster is the outcome everybody wants; a total that drops because a job lost
its steps is lost coverage wearing the same number (GHC holds its own
performance ratchet to `Metric Decrease:` for this reason). So when
push-total goes down and scripts/gates-external/steps.lock.json lost a step
between the same two trees, every job family that lost one owes

    Gate-Retire(<family>): <why>

where the family is the lock's (a job id less one trailing `-<digits>`), and
a Gate-Retire line that names a family which lost nothing is refused, since
it is a declaration about the wrong coverage. A step moved to another family
counts as lost from the first one: steps_lock.py itself treats that as more
than a reshard. tile.yml has no lock, so its total has no retire rule.

Why this is its own script and not a mode of check-gate-budgets.py: that one
reads a tree and runs in tree-policy, where a push's commits are not the
question; this one reads the commits of a push and runs in ci.yml's secrets
job beside check-no-claude-trailer.py, the job that already has the history
(`fetch-depth: 0`) and the push range. It imports the other script's reader
for the total line and steps_lock.py's reader for the lock, so there is one
parser of each.

Why the lines are not Emit-Change lines, and not in scripts/emit-labels.txt:
emitchange.sh reads declarations across a whole release window, so a label
declared once shields every later change carrying it; a second family of
declarations under the same reader would be shielded the same way. These are
read per push, at the push's two ends, by their own parser. The syntax rules
are Emit-Change's: one name per line, no globs, a reason, and a line that
starts like a declaration and does not parse is an error rather than
something read generously.

    check-gate-budget-trailers.py --range A..B     a push: base A, tip B
    check-gate-budget-trailers.py --range A...B    a pull request: base is
                                                   the merge base
    check-gate-budget-trailers.py --range HEAD     no base (a force-push
                                                   orphaned it): every commit
                                                   that touched a total or the
                                                   lock, against its parent
    check-gate-budget-trailers.py --selftest       build throwaway repositories
                                                   and require each case red
                                                   or green as it should be

A tree with no total line at the base (the push that introduces one, or a
range older than 2026-09-25) is reported and passed: there is no earlier
figure to have raised.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


budgets = _load("check_gate_budgets", ROOT / "scripts" / "check-gate-budgets.py")
# steps_lock.py imports gatesplan.py from its own directory. The file is named
# here and not the directory, so that gatemap reads this script as reading
# that file, which is true, and not the whole external runner, which is not.
STEPS_LOCK = ROOT / "scripts" / "gates-external" / "steps_lock.py"
sys.path.insert(0, str(STEPS_LOCK.parent))
steps_lock = _load("steps_lock", STEPS_LOCK)

WORKFLOWS = ".github/workflows/"
LOCK_PATH = "scripts/gates-external/steps.lock.json"
LOCK_TOTAL = "push-total"

# What "starts like a declaration" means: the keyword followed by `(` or `:`.
# The keyword alone is not enough, because a message explaining the rule
# wraps onto a line that begins with the word (this commit's own did).
DECL_START = re.compile(r"^Gate-(?:Budget|Retire)\s*[(:]", re.I)
BUDGET_DECL = re.compile(
    r"^Gate-Budget\((push-total|path-total)\):[ \t]*(\d+)s[ \t]*->[ \t]*(\d+)s"
    r"[ \t]+\S")
RETIRE_DECL = re.compile(r"^Gate-Retire\(([a-z0-9][a-z0-9-]*)\):[ \t]+\S")


def git(repo, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc


def file_at(repo, rev, path):
    proc = git(repo, "show", f"{rev}:{path}", check=False)
    return proc.stdout if proc.returncode == 0 else None


def totals_at(repo, rev):
    """{total name: seconds or None} as the tree at rev declares them."""
    out = {}
    for total, name in budgets.TOTAL_FILES.items():
        text = file_at(repo, rev, WORKFLOWS + name)
        out[total] = None if text is None else budgets.read_total(text, name, total)[1]
    return out


def lock_at(repo, rev):
    text = file_at(repo, rev, LOCK_PATH)
    if text is None:
        return None
    return steps_lock.from_lock(json.loads(text))


def declarations(messages):
    """-> (budget edges {total: [(old, new, sha)]}, retires {family: [sha]}, problems)."""
    edges, retires, problems = {}, {}, []
    for sha, message in messages:
        for line in message.splitlines():
            line = line.strip()
            if not DECL_START.match(line):
                continue
            budget = BUDGET_DECL.match(line)
            retire = RETIRE_DECL.match(line)
            if budget:
                edges.setdefault(budget.group(1), []).append(
                    (int(budget.group(2)), int(budget.group(3)), sha))
            elif retire:
                retires.setdefault(retire.group(1), []).append(sha)
            else:
                problems.append(
                    f"{sha[:8]}: `{line}` starts like a declaration and does not"
                    " parse; the forms are `Gate-Budget(push-total|path-total):"
                    " <old>s -> <new>s <why>` and `Gate-Retire(<family>): <why>`"
                )
    return edges, retires, problems


def chained(edges, start, end):
    """Is there a path of declared (old, new) steps from start to end?"""
    seen, frontier = {start}, [start]
    while frontier:
        here = frontier.pop()
        for old, new, _sha in edges:
            if old == here and new not in seen:
                if new == end:
                    return True
                seen.add(new)
                frontier.append(new)
    return False


def lost_families(before, after):
    """{family: number of run steps the lock lost} between two locks."""
    lost = {}
    for family in before:
        gone = before[family] - after.get(family, Counter())
        if gone:
            lost[family] = sum(gone.values())
    return lost


def judge(repo, base, tip, messages, where):
    """-> (problems, notes) for one base..tip interval and its messages."""
    edges, retires, problems = declarations(messages)
    notes = []
    before, after = totals_at(repo, base), totals_at(repo, tip)
    for total in sorted(budgets.TOTAL_FILES):
        old, new = before[total], after[total]
        if old is None or new is None:
            notes.append(f"{where}: {total} is not read at both ends"
                         f" ({old} -> {new}); nothing to compare")
            continue
        if new > old:
            if chained(edges.get(total, []), old, new):
                notes.append(f"{where}: {total} {old}s -> {new}s, declared")
            else:
                said = ", ".join(f"{a}s -> {b}s ({sha[:8]})"
                                 for a, b, sha in edges.get(total, [])) or "none"
                problems.append(
                    f"{where}: {total} went up, {old}s -> {new}s, and no"
                    f" declared chain covers it (declared: {said}); a commit"
                    f" in the push says `Gate-Budget({total}): {old}s ->"
                    f" {new}s <why>`"
                )
            continue
        if new == old:
            notes.append(f"{where}: {total} unchanged at {new}s")
            continue
        if total != LOCK_TOTAL:
            notes.append(f"{where}: {total} {old}s -> {new}s, lowered")
            continue
        lock_before, lock_after = lock_at(repo, base), lock_at(repo, tip)
        if lock_before is None or lock_after is None:
            notes.append(f"{where}: {total} {old}s -> {new}s, lowered; the"
                         " steps lock is not at both ends")
            continue
        lost = lost_families(lock_before, lock_after)
        for family, count in sorted(lost.items()):
            if family not in retires:
                problems.append(
                    f"{where}: {total} went down, {old}s -> {new}s, and the"
                    f" steps lock lost {count} step(s) of family `{family}`;"
                    " that is coverage leaving, not a job getting faster, so"
                    f" a commit in the push says `Gate-Retire({family}): <why>`"
                )
        for family in sorted(set(retires) - set(lost)):
            problems.append(
                f"{where}: `Gate-Retire({family})` names a family that lost"
                " no step between the push's two trees"
                + (f" (the ones that did: {', '.join(sorted(lost))})" if lost
                   else " (none did)")
            )
        if not lost:
            notes.append(f"{where}: {total} {old}s -> {new}s, lowered with"
                         " every locked step still there")
        elif not problems:
            notes.append(f"{where}: {total} {old}s -> {new}s, lowered;"
                         f" retired: {', '.join(sorted(lost))}")
    return problems, notes


def messages_in(repo, rev_range):
    out = git(repo, "log", "--format=%H%x1f%B%x00", rev_range).stdout
    found = []
    for record in out.split("\x00"):
        record = record.strip("\n")
        if record:
            sha, _, message = record.partition("\x1f")
            found.append((sha, message))
    return found


def check_range(repo, rev_range):
    if "..." in rev_range:
        left, right = rev_range.split("...", 1)
        base = git(repo, "merge-base", left or "HEAD", right or "HEAD").stdout.strip()
        return judge(repo, base, right or "HEAD", messages_in(repo, rev_range),
                     rev_range)
    if ".." in rev_range:
        left, right = rev_range.split("..", 1)
        return judge(repo, left, right or "HEAD", messages_in(repo, rev_range),
                     rev_range)
    # No base: every commit that could have moved a total or the lock, each
    # against its first parent and held to its own message. Stricter than a
    # push, which may declare in any of its commits, and it has to be: there
    # is no push to speak of.
    paths = [WORKFLOWS + name for name in budgets.TOTAL_FILES.values()] + [LOCK_PATH]
    shas = git(repo, "log", "--format=%H", rev_range, "--", *paths).stdout.split()
    problems, notes = [], []
    for sha in shas:
        if git(repo, "rev-parse", "-q", "--verify", f"{sha}^", check=False).returncode:
            continue
        found, said = judge(repo, f"{sha}^", sha, messages_in(repo, f"{sha}^!"),
                            sha[:8])
        problems.extend(found)
        notes.extend(n for n in said if "unchanged" not in n and "not read" not in n)
    notes.append(f"{rev_range}: {len(shas)} commit(s) that touch a total or the"
                 " lock, each checked against its parent")
    return problems, notes


# --- self-test -------------------------------------------------------------

def _gates(cap, claims):
    body = "".join(f"  job{i}:\n    # budget: 3x {n}s worst observed\n"
                   f"    timeout-minutes: {-(-3 * n // 60)}\n"
                   for i, n in enumerate(claims))
    return f"# push-total: {cap}s\njobs:\n{body}"


def _tile(cap):
    return (f"# path-total: {cap}s\njobs:\n  shard:\n"
            "    # budget: 3x 100s worst observed\n    timeout-minutes: 5\n")


def _lock(families):
    return json.dumps({"note": "self-test", "families": families}, indent=1) + "\n"


class Scratch:
    """A throwaway repository whose commits the cases are made of."""

    def __init__(self, where):
        self.dir = Path(where)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="selftest",
                        GIT_AUTHOR_EMAIL="selftest@example.invalid",
                        GIT_COMMITTER_NAME="selftest",
                        GIT_COMMITTER_EMAIL="selftest@example.invalid")
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
             *args], cwd=self.dir, env=self.env, capture_output=True, text=True,
            check=True).stdout.strip()

    def commit(self, message, gates=None, tile=None, lock=None):
        for rel, text in ((WORKFLOWS + "gates.yml", gates),
                          (WORKFLOWS + "tile.yml", tile), (LOCK_PATH, lock)):
            if text is not None:
                path = self.dir / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


FAMILIES = {"contracts": ["run a", "run b"], "docs": ["run c"]}
FEWER = {"contracts": ["run a"], "docs": ["run c"]}


def selftest():
    cases = []  # (label, want_red, build(scratch) -> rev_range)

    def case(label, red):
        def register(build):
            cases.append((label, red, build))
            return build
        return register

    def base(s):
        return s.commit("base", _gates(1000, [600, 400]), _tile(100), _lock(FAMILIES))

    @case("raised with a declaration", False)
    def _(s):
        b = base(s)
        s.commit("Add a gate\n\nGate-Budget(push-total): 1000s -> 1200s a new gate",
                 _gates(1200, [600, 400, 200]))
        return f"{b}..HEAD"

    @case("raised without a declaration", True)
    def _(s):
        b = base(s)
        s.commit("Add a gate", _gates(1200, [600, 400, 200]))
        return f"{b}..HEAD"

    @case("lowered, a step deleted, no declaration", True)
    def _(s):
        b = base(s)
        s.commit("Drop a step", _gates(800, [600, 200]), lock=_lock(FEWER))
        return f"{b}..HEAD"

    @case("lowered, a step deleted, declared for its family", False)
    def _(s):
        b = base(s)
        s.commit("Drop a step\n\nGate-Retire(contracts): covered elsewhere",
                 _gates(800, [600, 200]), lock=_lock(FEWER))
        return f"{b}..HEAD"

    @case("lowered by slimming, every step kept", False)
    def _(s):
        b = base(s)
        s.commit("Slim a job", _gates(900, [600, 300]))
        return f"{b}..HEAD"

    @case("raised, declared with the wrong numbers", True)
    def _(s):
        b = base(s)
        s.commit("Add a gate\n\nGate-Budget(push-total): 1000s -> 1100s a new gate",
                 _gates(1200, [600, 400, 200]))
        return f"{b}..HEAD"

    @case("raised in two commits, each declared", False)
    def _(s):
        b = base(s)
        s.commit("One\n\nGate-Budget(push-total): 1000s -> 1100s one",
                 _gates(1100, [600, 400, 100]))
        s.commit("Two\n\nGate-Budget(push-total): 1100s -> 1200s two",
                 _gates(1200, [600, 400, 200]))
        return f"{b}..HEAD"

    @case("lowered, a step deleted, the wrong family declared", True)
    def _(s):
        b = base(s)
        s.commit("Drop a step\n\nGate-Retire(docs): wrong one",
                 _gates(800, [600, 200]), lock=_lock(FEWER))
        return f"{b}..HEAD"

    @case("a declaration that does not parse", True)
    def _(s):
        b = base(s)
        s.commit("Slim\n\nGate-Budget(push-total): up a bit", _gates(900, [600, 300]))
        return f"{b}..HEAD"

    @case("a bare declaration with no name", True)
    def _(s):
        b = base(s)
        s.commit("Slim\n\nGate-Retire: gone", _gates(900, [600, 300]))
        return f"{b}..HEAD"

    @case("prose that wraps onto the keyword", False)
    def _(s):
        b = base(s)
        s.commit("Slim\n\nexplains that a\nGate-Retire line is needed when",
                 _gates(900, [600, 300]))
        return f"{b}..HEAD"

    @case("the path total raised without a declaration", True)
    def _(s):
        b = base(s)
        s.commit("Grow tile", tile=_tile(150))
        return f"{b}..HEAD"

    @case("a pull request range, raised and declared", False)
    def _(s):
        base(s)
        s.git("checkout", "-q", "-b", "topic")
        s.commit("Add\n\nGate-Budget(push-total): 1000s -> 1200s a gate",
                 _gates(1200, [600, 400, 200]))
        s.git("checkout", "-q", "main")
        s.commit("Unrelated on main", tile=_tile(90))
        s.git("checkout", "-q", "topic")
        return "main...topic"

    @case("no base: an undeclared raise anywhere in history", True)
    def _(s):
        base(s)
        s.commit("Add a gate", _gates(1200, [600, 400, 200]))
        s.commit("Later work", tile=_tile(100))
        return "HEAD"

    @case("no base: the commit that introduces the totals", False)
    def _(s):
        s.commit("Before totals", "jobs: {}\n", "jobs: {}\n", _lock(FAMILIES))
        s.commit("Introduce", _gates(1000, [600, 400]), _tile(100))
        return "HEAD"

    failures = []
    tmp_root = os.environ.get("TMPDIR") or None
    for label, want_red, build in cases:
        with tempfile.TemporaryDirectory(prefix="gate-budget-trailers-",
                                         dir=tmp_root) as where:
            scratch = Scratch(where)
            rev_range = build(scratch)
            problems, _notes = check_range(scratch.dir, rev_range)
        if bool(problems) != want_red:
            failures.append(f"{label}: expected {'red' if want_red else 'green'},"
                            f" got {problems or 'green'}")
        else:
            print(f"  {'refused' if want_red else 'accepted'}: {label}")
    for failure in failures:
        print(f"SELFTEST FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(f"selftest: {len(cases)} cases, each red or green as it should be")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--range", metavar="A..B")
    group.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    problems, notes = check_range(ROOT, args.range)
    for note in notes:
        print(f"note: {note}")
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(f"OK: gate totals over {args.range} are declared where they rose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
