#!/usr/bin/env python3
"""Every top-level public declaration of std and of packages/* has a `##` doc.

    scripts/pub-doc-check.py                  # run ./bin/dawn doc, then check
    scripts/pub-doc-check.py --json L=F ...   # check dumps already on disk
    scripts/pub-doc-check.py --self-test

`dawn doc` already says which declarations are undocumented: a pub fn, type,
const, trait or effect with no `##` block directly above it is written with
`"doc": null`. Nothing read that field. std reached 100% by discipline alone
and packages/* sat at 96.5% (22 undocumented, research-doc-comments-report
2026-10-03 section 1.5), so the rule existed and nothing held it. This holds
it: one null `doc` on a top-level public declaration fails the run, and the
message lists each one as `<package>/<module>.<name>`.

## Why a script reading the JSON, and not a compiler lint

In Dawn a lint inside the compiler is a compile error: there is no warning
tier. `dawn run` on a draft would then refuse a file for a missing comment,
and every language with tiered diagnostics ships `missing_docs` off or as a
warning for that reason. The rule belongs to the published surface, and the
published surface is what `dawn doc` writes, so the check reads exactly that.

## What is checked, and what is not

  * Top-level pub declarations only. Members (constructors, trait methods,
    effect operations, associated types) are not checked yet; the doc
    comment ruling defers them to after the D2 rendering work.
  * selfhost/, compiler-plan/, site/ are not checked. Their `pub` is
    package-internal API (selfhost sits at 57%), and forcing a sentence onto
    each would buy filler, not documentation.
  * Module docs are not required of packages. Their modules open with the
    `#` header comment CLAUDE.md asks of every file (why the file exists),
    and only 6 of 39 package modules also open with a `##` module doc, so a
    required module doc would be a second header paragraph on 33 files
    written to satisfy a gate. std's module docs are held by the test in
    selfhost/src/doc.dawn, not here.
  * A package's dump also carries the modules of its dependencies (tea-dom
    documents `json2/lexer`). Only the modules whose source is under the
    package's own src/ are checked, so a dependency's gap is reported once,
    under the package that owns it.

Cost: eleven `dawn doc` runs, up to four at once, on a toolchain already
built. The measured wall clock is in the comment above the step in gates.yml.
"""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KINDS = ("fns", "types", "consts", "traits", "effects")
# Each `dawn doc` is a JVM that type-checks std plus one package and exits in
# about two seconds, so most of its CPU is the C2 compiler warming code it
# never gets to use: tileir measured 9.3s of CPU for 3.3s of wall clock with
# bin/dawn's flags, 3.4s of CPU for the same wall clock at C1 only. C1 is set
# here and not in bin/dawn, whose header gives the reasons it stays out of
# the default (10% slower at selfhost scale, an unverified -Xss interaction);
# neither applies to a dump this script parses and rejects if it is not JSON.
# Concurrency is capped because eleven 2g-heap JVMs at once on a 16-core,
# 15GB machine took 87s where one after another took 28s.
JVM_OPTS = "-Xss512m -Xmx2g -XX:+UseSerialGC -XX:TieredStopAtLevel=1"
JOBS = min(4, os.cpu_count() or 1)


def own_modules(pkg_dir):
    """Module paths whose source lives under `pkg_dir/src`."""
    src = os.path.join(pkg_dir, "src")
    out = set()
    for dirpath, _dirs, files in os.walk(src):
        for f in files:
            if f.endswith(".dawn"):
                rel = os.path.relpath(os.path.join(dirpath, f), src)
                out.add(rel[: -len(".dawn")].replace(os.sep, "/"))
    return out


def missing(label, dump, owned):
    """`label/module.name` for every top-level pub declaration without a doc.

    `owned` is None to check every module in the dump."""
    found = []
    modules = dump.get("modules")
    if not isinstance(modules, list):
        raise ValueError(f"{label}: no `modules` list in the dump")
    for m in modules:
        path = m["path"]
        if owned is not None and path not in owned:
            continue
        for kind in KINDS:
            if kind not in m:
                raise ValueError(f"{label}/{path}: no `{kind}` list in the dump")
            for decl in m[kind]:
                if decl.get("doc") is None:
                    found.append(f"{label}/{path}.{decl['name']}")
    return found


def packages():
    base = os.path.join(ROOT, "packages")
    return sorted(
        d for d in os.listdir(base)
        if os.path.isfile(os.path.join(base, d, "dawn.toml"))
    )


def run_doc(args):
    p = subprocess.run(
        [os.path.join(ROOT, "bin", "dawn"), "doc", *args],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "DAWN_JVM_OPTS": os.environ.get("DAWN_JVM_OPTS", JVM_OPTS)},
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"`dawn doc {' '.join(args)}` exited {p.returncode}:\n{p.stderr}")
    return json.loads(p.stdout)


def check(jobs, workers=JOBS):
    """jobs: (label, thunk producing the dump, owned modules or None)."""
    failures = []
    workers = max(1, min(len(jobs), workers))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [(label, owned, ex.submit(thunk)) for label, thunk, owned in jobs]
        for label, owned, fut in futs:
            failures += missing(label, fut.result(), owned)
    return failures


def report(failures, n):
    if failures:
        print(f"FAIL {len(failures)} top-level pub declaration(s) without a `##` doc:")
        for f in failures:
            print(f"  {f}")
        print("Write a `##` block directly above each (see docs/spec.md on doc comments).")
        return 1
    print(f"ok: every top-level pub declaration in {n} doc dump(s) is documented")
    return 0


def self_test():
    documented = {"modules": [{
        "path": "m", "fns": [{"name": "f", "doc": "F."}], "types": [],
        "consts": [{"name": "C", "doc": "C."}], "traits": [], "effects": [],
    }]}
    bare = {"modules": [
        {"path": "m", "fns": [{"name": "f", "doc": None}, {"name": "g", "doc": "G."}],
         "types": [{"name": "T", "doc": None}], "consts": [], "traits": [],
         "effects": [{"name": "E", "doc": None}]},
        # a dependency's module: not this package's to document
        {"path": "dep2/x", "fns": [{"name": "h", "doc": None}], "types": [],
         "consts": [], "traits": [], "effects": []},
    ]}
    fails = 0

    def expect(name, got, want):
        nonlocal fails
        if got != want:
            print(f"self-test FAIL {name}: got {got!r}, want {want!r}")
            fails += 1

    expect("documented passes", missing("p", documented, {"m"}), [])
    expect("missing docs are named",
           missing("p", bare, {"m"}), ["p/m.f", "p/m.T", "p/m.E"])
    expect("unowned check sees dependency modules",
           missing("p", bare, None), ["p/m.f", "p/m.T", "p/m.E", "p/dep2/x.h"])
    try:
        missing("p", {"modules": [{"path": "m", "fns": []}]}, None)
        expect("a dump without a kind is refused", "accepted", "refused")
    except ValueError:
        pass

    # end to end through the CLI, the way CI calls it: a dump with a gap reds
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good.json")
        bad = os.path.join(d, "bad.json")
        with open(good, "w") as f:
            json.dump(documented, f)
        with open(bad, "w") as f:
            json.dump(bare, f)
        me = os.path.abspath(__file__)
        g = subprocess.run([sys.executable, me, "--json", f"p={good}"],
                           capture_output=True, text=True)
        b = subprocess.run([sys.executable, me, "--json", f"p={bad}"],
                           capture_output=True, text=True)
        expect("cli: documented dump exits 0", g.returncode, 0)
        expect("cli: dump with a gap exits 1", b.returncode, 1)
        expect("cli: the gap is named", "p/m.T" in b.stdout, True)

    # the owned-module set is read from the tree, so test it on the tree
    expect("json owns its lexer",
           "lexer" in own_modules(os.path.join(ROOT, "packages", "json")), True)
    expect("tea-dom does not own json2/lexer",
           "json2/lexer" in own_modules(os.path.join(ROOT, "packages", "tea-dom")),
           False)

    if fails:
        return 1
    print("self-test ok: each rule refused its mutated input")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--json", action="append", default=[], metavar="LABEL=FILE",
                    help="check a dump on disk (every module in it) instead of running dawn doc")
    ap.add_argument("--jobs", type=int, default=JOBS,
                    help=f"dawn doc runs at once (default {JOBS})")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.json:
        jobs = []
        for spec in a.json:
            label, _, path = spec.partition("=")
            if not path:
                ap.error(f"--json wants LABEL=FILE, got {spec!r}")
            jobs.append((label, (lambda p=path: json.load(open(p))), None))
        return report(check(jobs, a.jobs), len(jobs))
    # bin/dawn rebuilds a stale toolchain before it runs anything, and four
    # launchers finding it stale at once would rebuild it four times over
    # (measured: 63s instead of 8s after a std edit). One run first, alone.
    subprocess.run([os.path.join(ROOT, "bin", "dawn"), "--version"],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    jobs = [("std", lambda: run_doc(["--stdlib"]), None)]
    for pkg in packages():
        d = os.path.join(ROOT, "packages", pkg)
        jobs.append((pkg, (lambda d=d: run_doc([os.path.relpath(d, ROOT)])),
                     own_modules(d)))
    return report(check(jobs, a.jobs), len(jobs))


if __name__ == "__main__":
    sys.exit(main())
