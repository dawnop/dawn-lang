#!/usr/bin/env python3
"""Two guards on gates that locate code by spelling it (ruling 9(a), 2026-09-24).

Several gates find the code they judge by quoting it: a mutator replaces a
literal line, an audit finding says "this text is still in that file". Such an
anchor has two ways to lie without going red, and this file holds one guard
against each. The third way, a literal that matches twice and so points at the
wrong copy, is held where each anchor is read: mutation-anchor-preflight.py for
the mutators, doc-check.py (`anchor_present_once`) for the audit anchors.

1. THE FLIP. An audit anchor says which way a literal reads while its finding
   is open (`present` or `absent`, docs/codebase-audit-v2/*). A fixer who
   turns `present` into `absent`, or rewrites the literal into something that
   happens to hold, keeps doc-check green and the finding's status wrong
   (L-02). So an anchor that exists at the base may not change kind, path or
   literal unless a commit in the window says so, one line per finding:

       Anchor-Change(<ID>): <why>

   The language is scripts/emitchange.sh's, for the same reasons: one ID per
   line, no globs, a reason is required, and a line that starts like a
   declaration and does not parse is an error rather than something read
   generously. The window is also Emit-Change's: the commits after the release
   in scripts/seed-release.txt. Comparing with origin/main instead would see a
   pull request and miss a direct push to main, where origin/main is HEAD.
   Recording a NEW anchor needs no declaration; anchors are written once, when
   the finding is.

2. THE UNSEEN READER. Proving anchors exactly-once only helps for the readers
   somebody enrolled. mutation-anchor-preflight.py fails closed on a new
   mutate.py; this extends the same idea to every script. A tracked script
   under scripts/ that names a source file (selfhost/src, compiler-plan/src,
   std, runtime/c, packages) and contains a text-matching operation must be
   listed in scripts/anchor-readers.txt with what it is:

       preflight   its anchors are proven exactly-once by
                   mutation-anchor-preflight.py before any build (checked
                   against that script's own inventory)
       self-once   it refuses a literal that does not match exactly once
                   itself (checked: the file must contain such a test)
       unproven    it reads source text by spelling and nothing proves its
                   literals unique. The ledger is the debt, in the open.
       not-anchor  the rule matches, but it does not locate code by a
                   literal; the reason says why

   The rule over-approximates on purpose: a false entry costs one ledger line,
   a missed reader is the silent gap this exists to close. It fails both ways,
   like scripts/gate-map/unseen.txt: an unregistered reader is red, and a line
   whose script is gone or no longer matches is red.

Long term the direction is the one cargo-mutants, Stryker and PIT took: locate
by syntax tree or compiler output, not by text. Exactly-once is the interim.
"""

import argparse
import importlib.util
import pathlib
import re
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = "scripts/anchor-readers.txt"
KINDS = ("preflight", "self-once", "unproven", "not-anchor")

# A source file named by path. `packages/<name>/src/` is where package code
# lives; the other four roots are the compiler, the planner, std and the C
# runtime.
SOURCE_PATH = re.compile(
    r"(?:selfhost/src|compiler-plan/src|std|runtime/c|packages/[a-z0-9_-]+/src)"
    r"/[A-Za-z0-9_/.-]+\.(?:dawn|c|h)\b")
# An operation that finds or rewrites text by its spelling.
MATCH_OP = re.compile(
    r"\.count\(|\.replace\(|\.find\(|\.index\(|re\.search\(|re\.sub\("
    r"|\bin (?:text|src|source|original|body)\b|grep -[A-Za-z]*F|sed -i")
# What `self-once` has to show: a comparison of a match count with one, or the
# wording scripts in this repository use when they refuse a non-unique anchor.
SELF_ONCE = re.compile(
    r"count\([^()]*(?:\([^()]*\))?[^()]*\)\s*!=\s*1|!= 1\b.*match"
    r"|not unique|expected (?:exactly )?(?:one|1) match|matches, expected 1")

ANCHOR_CHANGE_LINE = re.compile(r"^\s*Anchor-Change\b")
ANCHOR_CHANGE = re.compile(r"^\s*Anchor-Change\(([A-Z]+-\d{2})\):\s*(\S.*)$")


def load_doc_check():
    spec = importlib.util.spec_from_file_location(
        "doc_check", ROOT / "scripts" / "doc-check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ the flip

def anchors_by_id(dc, detail_texts: dict[str, str]) -> dict[str, tuple]:
    """Each anchored finding's anchors, as a sorted tuple of (kind, path, literal)."""
    return {audit_id: tuple(sorted(dc.AUDIT_ANCHOR.findall(entry)))
            for audit_id, entry in dc.audit_detail_entries(detail_texts).items()
            if dc.AUDIT_ANCHOR.search(entry)}


def git(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *argv],
                          capture_output=True, text=True)


def base_details(dc, base: str) -> dict[str, str]:
    texts = {}
    for _prefix, rel in dc.AUDIT_DETAIL_FILES:
        done = git("show", f"{base}:{rel}")
        # A detail file that did not exist at the base holds no anchor there.
        texts[rel] = done.stdout if done.returncode == 0 else ""
    return texts


def parse_declarations(messages: str) -> tuple[dict[str, str], list[str]]:
    declared: dict[str, str] = {}
    bad: list[str] = []
    for line in messages.split("\n"):
        if not ANCHOR_CHANGE_LINE.match(line):
            continue
        m = ANCHOR_CHANGE.match(line)
        if m is None:
            bad.append(f"unparseable declaration {line.strip()!r}: the form is "
                       f"`Anchor-Change(<ID>): <why>`, one audit ID per line, "
                       f"no globs, no bare `Anchor-Change:` [declaration_parses]")
            continue
        declared.setdefault(m.group(1), line.strip())
    return declared, bad


def flip_problems(base: dict[str, tuple], head: dict[str, tuple],
                  messages: str) -> tuple[list[str], list[str]]:
    """(problems, notes). A changed anchor needs a declaration naming its ID."""
    declared, bad = parse_declarations(messages)
    notes: list[str] = []
    for audit_id in sorted(declared):
        if audit_id not in base and audit_id not in head:
            bad.append(f"{declared[audit_id]!r} names {audit_id}, which carries "
                       f"no audit anchor at the base or now [declaration_known]")
    for audit_id in sorted(base):
        was, now = base[audit_id], head.get(audit_id)
        if now == was:
            if audit_id in declared:
                notes.append(f"NOTE: {audit_id} is declared but its anchor did "
                             f"not change")
            continue
        if audit_id in declared:
            notes.append(f"NOTE: {audit_id} anchor changed, declared by "
                         f"{declared[audit_id]!r}")
            continue
        shown = "removed" if now is None else f"now {list(now)}"
        bad.append(f"{audit_id}: its audit anchor was {list(was)} at the base "
                   f"and is {shown}. An anchor is written once, when the "
                   f"finding is recorded; turning `present` into `absent` or "
                   f"rewriting the literal is how a fix stays green without "
                   f"the tree agreeing. Re-judge the finding, or add "
                   f"`Anchor-Change({audit_id}): <why>` to the commit message "
                   f"[anchor_unchanged]")
    return bad, notes


def release_tag() -> str:
    return "v" + (ROOT / "scripts/seed-release.txt").read_text().strip().lstrip("v")


def check_flip(dc, base: str | None, messages_file: str | None) -> tuple[list[str], list[str]]:
    base = base or release_tag()
    if git("rev-parse", "--verify", "-q", f"{base}^{{commit}}").returncode != 0:
        return [f"anchor flip guard: base {base} is not in this clone; the "
                f"window cannot be read, so nothing can be approved (CI needs "
                f"fetch-depth: 0) [base_resolves]"], []
    if messages_file is not None:
        messages = pathlib.Path(messages_file).read_text(encoding="utf-8")
    else:
        done = git("log", f"{base}..HEAD", "--format=%B")
        if done.returncode != 0:
            return [f"anchor flip guard: git log {base}..HEAD failed: "
                    f"{done.stderr.strip()}"], []
        messages = done.stdout
    head = anchors_by_id(dc, dc.read_audit_details())
    return flip_problems(anchors_by_id(dc, base_details(dc, base)), head, messages)


# ------------------------------------------------------- the unseen reader

def detect(files: dict[str, str]) -> set[str]:
    return {rel for rel, text in files.items()
            if SOURCE_PATH.search(text) and MATCH_OP.search(text)}


def parse_ledger(text: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    entries: dict[str, tuple[str, str]] = {}
    bad: list[str] = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        m = re.match(r"^(\S+)\s+([a-z-]+):\s*(\S.*)$", line)
        if m is None or m.group(2) not in KINDS:
            bad.append(f"{LEDGER}:{n}: not `<path>  <kind>: <why>` with kind in "
                       f"{', '.join(KINDS)} [ledger_parses]")
            continue
        if m.group(1) in entries:
            bad.append(f"{LEDGER}:{n}: {m.group(1)} is listed twice [ledger_parses]")
            continue
        entries[m.group(1)] = (m.group(2), m.group(3))
    return entries, bad


def preflight_covered(root: pathlib.Path) -> set[str]:
    """The scripts mutation-anchor-preflight.py exercises, read from its own tables."""
    spec = importlib.util.spec_from_file_location(
        "preflight", root / "scripts" / "mutation-anchor-preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    covered = {f"scripts/{name}/mutate.py" for name in module.ADAPTERS}
    covered |= {f"scripts/{name}/run.sh" for name in module.SHELL_ADAPTERS}
    # Called by name in check(), outside the three tables.
    covered |= {"scripts/gate-map/gatemap.py", "scripts/builtin-decl-contract/check.py"}
    return covered


def inventory_problems(files: dict[str, str], ledger_text: str,
                       covered: set[str]) -> list[str]:
    entries, bad = parse_ledger(ledger_text)
    found = detect(files)
    for rel in sorted(found - entries.keys()):
        kind = "preflight" if rel in covered else "unproven"
        bad.append(f"{rel}: names a source file and matches text, and "
                   f"{LEDGER} does not say what it is. Add "
                   f"`{rel}  {kind}: <why>` (kinds: {', '.join(KINDS)}) "
                   f"[reader_registered]")
    for rel in sorted(entries.keys() - found):
        why = "is not a tracked script" if rel not in files else \
            "no longer matches the rule"
        bad.append(f"{LEDGER}: {rel} {why}; drop the line [reader_stale]")
    for rel in sorted(entries.keys() & found):
        kind, _why = entries[rel]
        if kind == "preflight" and rel not in covered:
            bad.append(f"{LEDGER}: {rel} is marked preflight, but "
                       f"mutation-anchor-preflight.py does not exercise it "
                       f"[preflight_is_real]")
        elif kind != "preflight" and rel in covered:
            bad.append(f"{LEDGER}: {rel} is exercised by "
                       f"mutation-anchor-preflight.py; mark it preflight "
                       f"[preflight_is_real]")
        elif kind == "self-once" and not SELF_ONCE.search(files[rel]):
            bad.append(f"{LEDGER}: {rel} is marked self-once, but contains no "
                       f"exactly-once test [self_once_is_real]")
    return bad


def tracked_scripts(root: pathlib.Path) -> dict[str, str]:
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "scripts"],
                          capture_output=True, check=True)
    files = {}
    for rel in done.stdout.decode().split("\0"):
        if rel.endswith((".py", ".sh")) and (root / rel).is_file():
            files[rel] = (root / rel).read_text(encoding="utf-8", errors="replace")
    return files


def check_inventory() -> list[str]:
    return inventory_problems(tracked_scripts(ROOT),
                              (ROOT / LEDGER).read_text(encoding="utf-8"),
                              preflight_covered(ROOT))


# ------------------------------------------------------------- self-test

def labels(problems: list[str]) -> set[str]:
    return {label for p in problems for label in re.findall(r"\[(\w+)\]", p)}


def selftest() -> tuple[list[str], int]:
    """Each mutant must redden exactly its own label; controls redden nothing."""
    fail: list[str] = []
    ran = []

    def expect(name, problems, want):
        ran.append(name)
        got = labels(problems)
        if got != want:
            fail.append(f"self-test {name}: reddened {sorted(got) or 'nothing'}, "
                        f"expected {sorted(want) or 'nothing'}")

    lit = ("present", "selfhost/src/check/passes.dawn", "a literal line")
    base = {"SEM-10": (lit,), "ARC-10": (("present", "bin/dawn", "-Xss512m"),)}
    flipped = dict(base, **{"SEM-10": (("absent",) + lit[1:],)})
    reworded = dict(base, **{"SEM-10": ((lit[0], lit[1], "a literal lime"),)})
    removed = {k: v for k, v in base.items() if k != "SEM-10"}
    added = dict(base, **{"SEM-99": (lit,)})
    why = "Anchor-Change(SEM-10): the finding moved to a new function\n"
    expect("control-unchanged", flip_problems(base, dict(base), "")[0], set())
    expect("control-new-anchor", flip_problems(base, added, "")[0], set())
    expect("kind-flipped", flip_problems(base, flipped, "")[0], {"anchor_unchanged"})
    expect("literal-reworded", flip_problems(base, reworded, "")[0], {"anchor_unchanged"})
    expect("anchor-removed", flip_problems(base, removed, "")[0], {"anchor_unchanged"})
    expect("declared-flip", flip_problems(base, flipped, why)[0], set())
    expect("other-id-declared", flip_problems(
        base, flipped, "Anchor-Change(ARC-10): unrelated\n")[0], {"anchor_unchanged"})
    for spelling in ("Anchor-Change: SEM-10", "Anchor-Change(SEM-*): glob",
                     "Anchor-Change(SEM-10):", "Anchor-Change(SEM-10, ARC-10): two"):
        expect(f"malformed {spelling!r}",
               flip_problems(base, flipped, why + spelling + "\n")[0],
               {"declaration_parses"})
    expect("unknown-id", flip_problems(
        base, dict(base), "Anchor-Change(GOV-77): nothing\n")[0], {"declaration_known"})

    reader = "open(p).read().count('fn main') == 0 and 'selfhost/src/main.dawn'"
    once = reader + "\nif text.count(old) != 1: raise SystemExit"
    files = {"scripts/a/mutate.py": reader, "scripts/b.py": reader,
             "scripts/c.py": once, "scripts/quiet.py": "print('selfhost/src/x.dawn')"}
    covered = {"scripts/a/mutate.py"}
    ledger = ("scripts/a/mutate.py  preflight: exercised\n"
              "scripts/b.py  unproven: debt\n"
              "scripts/c.py  self-once: refuses a second match\n")
    expect("control-ledger", inventory_problems(files, ledger, covered), set())
    expect("new-reader", inventory_problems(
        dict(files, **{"scripts/d.py": reader}), ledger, covered), {"reader_registered"})
    expect("reader-gone", inventory_problems(
        {k: v for k, v in files.items() if k != "scripts/b.py"}, ledger, covered),
        {"reader_stale"})
    expect("reader-stopped-matching", inventory_problems(
        dict(files, **{"scripts/b.py": "print(1)"}), ledger, covered), {"reader_stale"})
    expect("preflight-claimed", inventory_problems(
        files, ledger.replace("b.py  unproven", "b.py  preflight"), covered),
        {"preflight_is_real"})
    expect("preflight-unclaimed", inventory_problems(
        files, ledger.replace("mutate.py  preflight", "mutate.py  unproven"), covered),
        {"preflight_is_real"})
    expect("self-once-claimed", inventory_problems(
        files, ledger.replace("b.py  unproven", "b.py  self-once"), covered),
        {"self_once_is_real"})
    expect("bad-kind", inventory_problems(
        files, ledger.replace("b.py  unproven", "b.py  maybe"), covered),
        {"ledger_parses", "reader_registered"})
    return fail, len(ran)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", help="revision the anchors are compared "
                        "with (default: the tag of scripts/seed-release.txt)")
    parser.add_argument("--messages", help="read declarations from this file "
                        "instead of `git log <base>..HEAD`")
    parser.add_argument("--selftest", action="store_true",
                        help="run the negative controls instead of the guards")
    args = parser.parse_args()
    if args.selftest:
        fail, ran = selftest()
        for line in fail:
            print(f"FAIL: {line}", file=sys.stderr)
        if fail:
            return 1
        print(f"OK: anchor-guard self-test, {ran} mutants and controls")
        return 0
    dc = load_doc_check()
    bad, notes = check_flip(dc, args.base, args.messages)
    bad += check_inventory()
    for line in notes:
        print(line)
    for line in bad:
        print(f"FAIL: {line}", file=sys.stderr)
    if bad:
        return 1
    entries, _ = parse_ledger((ROOT / LEDGER).read_text(encoding="utf-8"))
    counts = {kind: sum(1 for k, _ in entries.values() if k == kind) for kind in KINDS}
    print(f"OK: no audit anchor changed undeclared since "
          f"{args.base or release_tag()}; {len(entries)} source-text readers "
          f"registered ({', '.join(f'{v} {k}' for k, v in counts.items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
