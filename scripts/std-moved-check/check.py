#!/usr/bin/env python3
"""Every pub std function the previous release had and this tree has not must
be accounted for in std/moved.txt (issue #211, docs/std-moved-design.md §3).

    scripts/std-moved-check/check.py --old <previous release's std> [--new std]
    scripts/std-moved-check/check.py --self-test

A removal is accounted for by a line whose scope is its module and whose old
name is its name: a hint, or the literal `no-hint` for a removal made on
purpose with nothing to say. Either way somebody decided; what this refuses is
the removal nobody thought about, which is how the checker's old hand-kept
table went years without a new entry.

Why a script of its own and not a section of api-diff.py: that one is a report
over two published `dawn doc` snapshots, run once per release, and says in its
header that it gates nothing. This has to run on every push against the tree,
with no compiler, so it reads the sources.

What counts as a pub std function: a top-level `pub fn <name>` (column 0) in a
module modules.txt lists. `pub(pkg) fn` is not public, and an indented `pub fn`
is an impl or trait member, which the hint path (`check_module_call`) never
asks about. A `replacement` written `<module>.<fn>` must itself be a pub
function of this tree, so a hint cannot point at a name that is gone too.

The baseline comes from run.sh, which asks scripts/seedjar.sh for the seed's
released std: verified against seed-std-checksums.txt, and by construction the
previous release, since a release advances the seed to itself.
"""

import argparse
import os
import re
import sys
import tempfile

PUB_FN = re.compile(r"^pub fn ([A-Za-z_][A-Za-z0-9_]*)", re.M)
RELEASE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class CheckError(Exception):
    """A std this script cannot read. Never a pass."""


def index_names(text: str) -> list:
    # mirror stdlib.index_names: one name per line, `#` comments, blanks skipped
    names = []
    for line in text.split("\n"):
        cut = line.split("#", 1)[0].strip()
        if cut:
            names.append(cut)
    return names


def pub_fns(std_dir: str) -> set:
    """{(module path, name)} for every top-level pub fn modules.txt reaches."""
    index = os.path.join(std_dir, "modules.txt")
    try:
        with open(index, encoding="utf-8") as fh:
            names = index_names(fh.read())
    except OSError as exc:
        raise CheckError(f"{index}: {exc}") from exc
    if not names:
        raise CheckError(f"{index}: lists no modules")
    out = set()
    for n in names:
        path = os.path.join(std_dir, n + ".dawn")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise CheckError(f"{path}: {exc}") from exc
        for m in PUB_FN.finditer(text):
            out.add((f"std/{n}", m.group(1)))
    return out


def parse_moved(text: str, where: str) -> list:
    """The entries of a moved.txt, as (line, scope, old, replacement, hint).

    The loader (stdlib.parse_moved) is the authority on the format and refuses
    a malformed file at every compiler start; this only needs the fields, and
    refuses what it cannot split rather than skipping it.
    """
    out = []
    for n, raw in enumerate(text.split("\n"), 1):
        line = raw.split("#", 1)[0].replace("\t", " ").strip()
        if not line:
            continue
        parts = line.split(None, 5)
        if len(parts) < 6:
            raise CheckError(f"{where}:{n}: expected `scope old new since until hint`")
        scope, old, replacement, since, until, hint = parts
        if not RELEASE.match(since) or not RELEASE.match(until):
            raise CheckError(f"{where}:{n}: since and until must be releases written X.Y.Z")
        out.append((n, scope, old, replacement, hint))
    return out


def read_moved(std_dir: str) -> list:
    path = os.path.join(std_dir, "moved.txt")
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise CheckError(f"{path}: {exc}") from exc
    return parse_moved(text, path)


def problems(old_dir: str, new_dir: str) -> list:
    old, new = pub_fns(old_dir), pub_fns(new_dir)
    entries = read_moved(new_dir)
    listed = {(scope, name) for _, scope, name, _, _ in entries}
    out = []
    for mod, name in sorted(old - new):
        if (mod, name) not in listed:
            out.append(f"`{mod}` `pub fn {name}` is gone since the previous release and "
                       f"std/moved.txt says nothing about it: add `{mod} {name} <new> "
                       f"<since> <until> <hint>`, or `no-hint` as the hint")
    new_by_short = {(mod[len("std/"):], name) for mod, name in new}
    for n, scope, name, replacement, _ in entries:
        if "." in replacement and replacement != "-":
            short, _, fn = replacement.partition(".")
            if (short, fn) not in new_by_short:
                out.append(f"std/moved.txt:{n}: `{name}` of `{scope}` points at "
                           f"`{replacement}`, which is not a pub fn of this std")
    return out


# --------------------------------------------------------------------------
# self-test: each refusal the gate exists for, fed to it, must be refused.


def _std(root: str, name: str, modules: dict, moved=None) -> str:
    d = os.path.join(root, name)
    os.makedirs(d)
    with open(os.path.join(d, "modules.txt"), "w", encoding="utf-8") as fh:
        fh.write("".join(f"{m}\n" for m in modules))
    for m, text in modules.items():
        with open(os.path.join(d, m + ".dawn"), "w", encoding="utf-8") as fh:
            fh.write(text)
    if moved is not None:
        with open(os.path.join(d, "moved.txt"), "w", encoding="utf-8") as fh:
            fh.write(moved)
    return d


def self_test() -> int:
    base = {"s": "pub fn keep() -> Int = 1\npub fn gone() -> Int = 2\n"
                 "pub(pkg) fn inner() -> Int = 3\nimpl Show[X] {\n  pub fn show() = 1\n}\n"}
    dropped = {"s": "pub fn keep() -> Int = 1\n"}
    cases = (
        # (label, new modules, moved.txt, expected problem count)
        ("unchanged", base, None, 0),
        ("removed with no line", dropped, None, 1),
        ("removed with a hint", dropped,
         "std/s gone s.keep 0.1.0 0.11.0 renamed: write `s.keep()`\n", 0),
        ("removed with no-hint", dropped, "std/s gone - 0.1.0 0.11.0 no-hint\n", 0),
        ("a line for another module does not count", dropped,
         "std/t gone - 0.1.0 0.11.0 no-hint\n", 1),
        ("a whole module removed", {"t": "pub fn other() -> Int = 1\n"}, None, 2),
        ("pub(pkg) and impl members are not surface",
         {"s": "pub fn keep() -> Int = 1\npub fn gone() -> Int = 2\n"}, None, 0),
        ("a hint that points at a missing name", dropped,
         "std/s gone s.nowhere 0.1.0 0.11.0 hint\n", 1),
    )
    failures = []
    with tempfile.TemporaryDirectory() as root:
        old = _std(root, "old", base)
        for i, (label, mods, moved, want) in enumerate(cases):
            new = _std(root, f"new{i}", mods, moved)
            got = len(problems(old, new))
            if got != want:
                failures.append(f"{label}: expected {want} problem(s), got {got}")
            else:
                print(f"  {'refused' if want else 'accepted'}: {label}")
        for i, (label, moved) in enumerate((
            ("a line short of fields", "std/s gone - 0.1.0 0.11.0\n"),
            ("a since that is not a release", "std/s gone - 0.1 0.11.0 hint\n"),
        )):
            bad = _std(root, f"bad{i}", dropped, moved)
            try:
                problems(old, bad)
            except CheckError:
                print(f"  refused: {label}")
            else:
                failures.append(f"malformed moved.txt accepted: {label}")
        empty = _std(root, "empty", {})
        try:
            problems(old, empty)
        except CheckError:
            print("  refused: a std whose modules.txt lists nothing")
        else:
            failures.append("a std with no modules was read as one with no functions")
    if failures:
        for f in failures:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print(f"selftest: {len(cases)} case(s) and 3 malformed input(s) as expected")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", help="the previous release's std directory")
    ap.add_argument("--new", default="std", help="this tree's std directory (default std)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.old:
        ap.error("--old is required")
    try:
        found = problems(args.old, args.new)
        old_n, new_n = len(pub_fns(args.old)), len(pub_fns(args.new))
    except CheckError as exc:
        print(f"std-moved-check: {exc}", file=sys.stderr)
        return 1
    for p in found:
        print(f"FAIL: {p}", file=sys.stderr)
    if found:
        print(f"std-moved-check: {len(found)} unaccounted change(s); "
              "see docs/std-moved-design.md", file=sys.stderr)
        return 1
    print(f"OK: {old_n} pub std fn(s) before, {new_n} now; every removal is in std/moved.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
