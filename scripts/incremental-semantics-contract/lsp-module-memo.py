#!/usr/bin/env python3
"""Prove that the LSP's answers come from the real producers.

The workspace cache mutants show that the analysis owner is the thing the
server commits and discards, and the parse mutants that the parses a load
reuses (and the line starts that ride on them) are the previous load's and
only for unchanged text; the resolver
mutant shows that a query's
positions are the ones the scheduler resolved against the declaration a body
was checked in. The owning tests use in-memory Fs/Env and can also run in the
native suite. Protocol-only comparisons would accept a server that silently
always checks.

`--shards N --shard I` runs the subjects (the positive first, then the
mutants in their mutate.py order) whose index is I modulo N. The no-flag
invocation is unchanged: the positive and every mutant. The subjects are
dealt with the positive among them, not added to every shard as in
module-memo.py, because here each subject is one `dawn check` plus one
`dawn test` of selfhost and they cost the same: 65s to 97s each on a runner
(the per-subject `OK:` timestamps of runs 39053565925 and 38576085599), so
before the source-snapshot controls, the eight subjects split 4 + 4 and a
positive in both shards would have been a ninth. A positive-less shard keeps
what module-memo.py's shard note lists:
every anchor is applied before anything is built, every mutant must compile,
and a mutant counts only when its owning assertion is the failure. That the
assertions are not stuck on FAIL is a property of the tree, shown once per
run by shard 0 over the same commit.
"""
import argparse
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

from cold import HERE, ROOT, apply, owned, run

CACHE = ("lsp/server", "workspace commits its module memo with its Program and drops it on conflict")
RESOLVER = ("lsp/server", "a handler state cell answers at every spelling of it")
PARSES = ("driver/analyze", "a reusing load parses only the files whose text changed")
SOURCE = ("contract/source_snapshot", "source snapshots reject another revision before consuming code points or line starts")
POSITIONS = ("lsp/server", "source snapshots preserve cold diagnostics positions and full and range tokens across revisions")

SERVER = "selfhost/src/lsp/server.dawn"
CHECKER = "selfhost/src/check/checker.dawn"
ANALYZE = "selfhost/src/driver/analyze.dawn"


def owner_line(verdict, owner):
    module, name = owner
    return r"^" + verdict + r"\s+" + re.escape(module) + " :: " + re.escape(name)


def check_cli():
    """Exercise the shard flags and the current partitions without a compiler."""
    group = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "lsp-module-memo")
    subjects = len(group) + 1
    empty_shards, empty_index = str(subjects + 1), str(subjects)
    cases = [
        (['--shards', '0'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '-1'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '2'], 2, 'require --shards >= 1'),
        (['--shards', empty_shards, '--shard', empty_index], 2, 'the selected shard has no mutants'),
        (['--shards', empty_shards, '--check-shards'], 2, 'every shard must contain a mutant'),
    ]
    for count in [1, 2]:
        cases.append((['--shards', str(count), '--check-shards'], 0, 'unique subjects; disjoint shard sizes'))
    for args, expected, message in cases:
        result = subprocess.run([sys.executable, __file__, *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != expected or message not in result.stdout:
            raise RuntimeError(f'CLI contract failed for {args}: {result.stdout}')
    print(f'OK: lsp module memo shard CLI contracts ({len(cases)} cases)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', type=int, default=1)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--check-shards', action='store_true',
                        help='validate mutation anchors and complete disjoint shard coverage without compiling')
    parser.add_argument('--self-test', action='store_true', help='check the shard flags without compiling')
    args = parser.parse_args()
    if args.self_test:
        check_cli()
        return
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error('require --shards >= 1 and 0 <= --shard < --shards')
    start = time.monotonic()
    paths = (SERVER, CHECKER, ANALYZE)
    originals = {path: (ROOT / path).read_text() for path in paths}
    # The mutants are the lsp-module-memo group of mutate.py, where the
    # preflight proves their anchors before any build; this is what each
    # one's failure must be owned by.
    owners = {"drop-session": CACHE, "bypass-cache": CACHE, "keep-conflict-cache": CACHE,
              "drop-parses": CACHE, "stale-parse": PARSES, "stale-line-starts": PARSES,
              "wrong-source-revision": SOURCE, "stale-source-code-points": POSITIONS,
              "stale-source-line-starts": POSITIONS,
              "resolver-drops-the-declaration": RESOLVER}
    group = owned(runpy.run_path(str(HERE / "mutate.py"))["MUTATIONS"], "lsp-module-memo")
    if list(group) != list(owners):
        raise RuntimeError(f"mutate.py's lsp-module-memo group is {list(group)}, not {list(owners)}")
    variants = [(name, owners[name], edits[0][0], edits) for name, edits in group.items()]
    subjects = [("positive", CACHE, SERVER, originals[SERVER])] + [
        (name, owner, path, apply(originals[path], edits, path)) for name, owner, path, edits in variants]
    # Every anchor was applied just above, in every shard, before the deal:
    # a drifted anchor is refused whichever shard runs.
    names = [name for name, _, _, _ in subjects]
    if len(set(names)) != len(names):
        raise RuntimeError('Duplicate LSP module memo subject identity')
    partitions = [names[index::args.shards] for index in range(args.shards)]
    mutants_in = [[name for name in partition if name != "positive"] for partition in partitions]
    if args.check_shards and not all(mutants_in):
        parser.error('every shard must contain a mutant')
    if not mutants_in[args.shard]:
        parser.error('the selected shard has no mutants')
    if args.check_shards:
        covered = [name for partition in partitions for name in partition]
        if len(covered) != len(names) or set(covered) != set(names):
            raise RuntimeError('Shard coverage is incomplete or duplicated')
        print(f'OK: {len(names)} unique subjects; disjoint shard sizes ' +
              ', '.join(str(len(partition)) for partition in partitions))
        return
    subjects = subjects[args.shard::args.shards]
    with tempfile.TemporaryDirectory(prefix="dawn-lsp-module-memo-") as temp:
        root = Path(temp)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        target = root / "selfhost"
        for name, owner, path, source in subjects:
            (root / path).write_text(source)
            status, output = run("check", target)
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            status, output = run("test", target)
            if name == "positive":
                if status or not all(re.search(owner_line("PASS", each), output, re.M)
                                     for each in (CACHE, RESOLVER, PARSES, SOURCE, POSITIONS)):
                    raise RuntimeError(f"positive failed\n{output}")
            elif not status or not re.search(
                    owner_line("FAIL", owner) + r"\n\s+assertion failed:", output, re.M):
                raise RuntimeError(f"{name} missed the owning assertion\n{output}")
            (root / path).write_text(originals[path])
            print(f"OK: lsp module memo, parses and resolver {name}", flush=True)
    if args.shards == 1:
        print(f"OK: {len(variants)} compiling LSP session, parse and resolver mutants; elapsed={time.monotonic()-start:.2f}s")
        return
    mutants = sum(1 for name, _, _, _ in subjects if name != "positive")
    print(f"OK: {mutants} of {len(variants)} compiling LSP session, parse and resolver mutants, "
          f"shard {args.shard}/{args.shards}, "
          f"{'with' if args.shard == 0 else 'without'} the positive; elapsed={time.monotonic()-start:.2f}s")


if __name__ == "__main__":
    main()
