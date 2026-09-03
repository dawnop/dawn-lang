#!/usr/bin/env python3
"""Hold the sharded mutation runs to the full matrix.

Sharding the mutation harnesses across CI jobs took the run's wall clock off
one 1100s step, and it introduced exactly one new way to be wrong: a mutant
that no shard runs. Nothing else notices. Each shard prints its own PASS lines
and exits 0 whether it covered its slice or skipped it, the job goes green,
and the matrix silently shrinks. That is the failure this file exists for, and
it is worse here than usual because the thing being skipped is the check.

So the shards do not get to vouch for themselves. Each writes down the mutants
it actually executed (scripts/mutant-coverage/shard.sh), and this reassembles
them and compares the union with the harness's own matrix file -- the same
file its runner iterates. A missing shard, a wrong `--shard I/N`, a matrix
entry nobody picked up, or a shard that ran a mutant twice all show up here as
a named difference.

The set of harnesses is asked of the tree too, not inferred from which
coverage files turned up. Inferring it would be the same bug one level up: a
shard job deleted from gates.yml contributes no coverage file, so it would be
absent from the reassembly and nothing would miss it. Every scripts/<harness>/
directory holding a matrix.txt or matrix.tsv whose run.sh sources
scripts/mutant-coverage/shard.sh is expected to report, by name. The second
half of that test exists because several unsharded harnesses (pipe-contract,
source-loop-label-contract, ...) keep a matrix.txt of their own and run whole
inside one job step; sourcing the shard library is what marks a harness as
split across jobs, which is the only arrangement where a slice can go missing
without its own job noticing. Removing the source line to shrink this set is
not a quiet move: gates.yml passes `--shard I/N`, which only the shard
library consumes, so the de-sharded runner refuses the flag and the job goes
red.

Shard indices are 1-based (`--shard 1/3` .. `3/3`), matching the spelling
export-surface-contract established in this repository.

"Mutant" is the word throughout, because mutants were all the matrices held
when this was written. scripts/tile-golden's does not: it lists the kernels
its golden loop iterates and then its mutants, one list in run order, because
both halves cost minutes there and a split by kind would have left one shard
carrying the slower one. Nothing here changes for that. This compares names
against a matrix file and knows nothing about what a name denotes, so read
"mutant" below as "work item": a kernel absent from the union is refused
exactly as a mutant absent from it is.

Usage:
    check.py --coverage-dir DIR [--root REPO_ROOT]
    check.py --self-test
"""

import argparse
import pathlib
import tempfile
from collections import defaultdict


def parse_coverage_file(path):
    """One shard's record: (harness, index, total, [mutant, ...])."""
    harness = None
    shard = None
    ran = []
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        key, _, value = line.partition("=")
        if key == "harness":
            harness = value
        elif key == "shard":
            index, _, total = value.partition("/")
            shard = (int(index), int(total))
        elif key == "ran":
            ran.append(value)
        else:
            raise SystemExit(f"{path}:{lineno}: unknown key {key!r}")
    if harness is None or shard is None:
        raise SystemExit(f"{path}: missing harness= or shard= header")
    return harness, shard[0], shard[1], ran


def matrix_path(root, harness):
    """The harness's matrix file, refusing a harness that carries both forms.

    Paths are spelled with joinpath rather than `/` chains: gatemap's
    python_inputs reads a `root / "scripts" / <variable>` chain as a claim on
    all of scripts/, and this script's declared inputs are exactly the two
    globs in expected_harnesses, not that directory.
    """
    here = root.joinpath("scripts", harness)
    txt = here / "matrix.txt"
    tsv = here / "matrix.tsv"
    if txt.is_file() and tsv.is_file():
        raise SystemExit(
            f"{here} holds both matrix.txt and matrix.tsv; "
            "one harness gets one matrix"
        )
    if tsv.is_file():
        return tsv
    if txt.is_file():
        return txt
    raise SystemExit(f"no matrix.txt or matrix.tsv for harness {harness} at {here}")


def expected_mutants(root, harness):
    """The harness's own list, asked of the harness rather than of the shards.

    Read from the matrix file rather than a runner flag, because the matrix is
    what the runners actually iterate (and, for the .tsv pair, what their own
    startup validation holds `mutate.py --list` to). An oracle should be the
    thing the code under test reads, not a second list that happens to agree
    today.

    Two shapes. matrix.txt is one mutant name per line. matrix.tsv is the
    pattern-or/for-pattern record form: a `schema\t1` line, then
    `mutant\t<name>\t<files>\t<owner>` records; the name is the second field.
    """
    matrix = matrix_path(root, harness)
    names = []
    for raw in matrix.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if matrix.suffix == ".tsv":
            fields = line.split("\t")
            if fields[0] == "schema":
                continue
            if fields[0] != "mutant" or len(fields) < 2 or not fields[1]:
                raise SystemExit(f"{matrix}: unreadable record {line!r}")
            names.append(fields[1])
        else:
            names.append(line.strip())
    if not names:
        raise SystemExit(f"{matrix} lists no mutants")
    return names


def expected_harnesses(root):
    """Which harnesses are supposed to report, asked of the tree.

    Membership is "the directory has a matrix file, and its run.sh sources
    the shard library". The first half is the promise (a matrix *is* a list
    of mutants somebody promised to run); the second half is what marks the
    promise as split across CI jobs, the only arrangement where a slice can
    go missing without its own job turning red. Harnesses that keep a
    matrix.txt but run whole inside one step (pipe-contract and the other
    single-job matrices) are not members: their completeness is their own
    step's exit code.

    Deliberately not derived from gates.yml's job list, though that is what
    actually dispatches the shards: checking gates.yml against gates.yml
    cannot notice a shard job deleted from gates.yml. The tree is the
    independent witness, so a deleted job surfaces here as a named absence.
    And de-sharding a runner to leave this set is loud on its own, because
    gates.yml passes `--shard I/N` and only the shard library consumes it.
    """
    matrices = list(root.glob("scripts/*/matrix.txt"))
    matrices += list(root.glob("scripts/*/matrix.tsv"))
    names = []
    for matrix in matrices:
        runner = matrix.parent / "run.sh"
        if not runner.is_file():
            continue
        if "mutant-coverage/shard.sh" not in runner.read_text(encoding="utf-8"):
            continue
        names.append(matrix.parent.name)
    names = sorted(set(names))
    if not names:
        raise SystemExit(
            f"no sharded harness under {root} (matrix file plus a run.sh that "
            "sources mutant-coverage/shard.sh); refusing to conclude anything "
            "about coverage from a tree with no sharded harnesses in it"
        )
    return names


def check_harness_set(expected, reported):
    """Return the problems with *which* harnesses reported, before what they ran.

    Kept separate from check() because check() only ever sees a harness that
    turned up. This is the half that can see one that did not.
    """
    problems = []

    missing = sorted(set(expected) - set(reported))
    if missing:
        problems.append(
            f"no shard reported any coverage for harness(es): {missing} -- "
            "each has a matrix file, so each is expected from gates.yml's shard jobs"
        )
    unknown = sorted(set(reported) - set(expected))
    if unknown:
        problems.append(
            f"coverage from harness(es) with no matrix file in the tree: {unknown}"
        )

    return problems


def check(harness, shards, expected):
    """Return the problems with one harness's reassembled coverage."""
    problems = []

    totals = {total for _index, total, _ran in shards}
    if len(totals) != 1:
        problems.append(f"shards disagree on the shard count: {sorted(totals)}")
        return problems
    total = totals.pop()

    seen_indices = sorted(index for index, _total, _ran in shards)
    if seen_indices != list(range(1, total + 1)):
        missing = sorted(set(range(1, total + 1)) - set(seen_indices))
        extra = sorted(set(seen_indices) - set(range(1, total + 1)))
        if missing:
            problems.append(f"no coverage file from shard(s) {missing} of {total}")
        if extra:
            problems.append(f"coverage from out-of-range shard(s) {extra}")
        duplicated = sorted({i for i in seen_indices if seen_indices.count(i) > 1})
        if duplicated:
            problems.append(f"more than one coverage file for shard(s) {duplicated}")

    ran = [mutant for _index, _total, mutants in shards for mutant in mutants]
    dupes = sorted({m for m in ran if ran.count(m) > 1})
    if dupes:
        problems.append(f"run by more than one shard: {dupes}")

    missing = sorted(set(expected) - set(ran))
    if missing:
        problems.append(f"no shard ran: {missing}")
    unknown = sorted(set(ran) - set(expected))
    if unknown:
        problems.append(f"ran a mutant the harness does not list: {unknown}")

    return problems


def run(coverage_dir, root):
    harnesses = expected_harnesses(root)
    print(
        f"      expecting {len(harnesses)} harness(es) under {root}: {harnesses}"
    )

    files = sorted(coverage_dir.rglob("*.coverage"))
    if not files:
        raise SystemExit(
            f"no *.coverage files under {coverage_dir}; the shards recorded nothing, "
            "which is indistinguishable from having run nothing"
        )

    by_harness = defaultdict(list)
    for path in files:
        harness, index, total, ran = parse_coverage_file(path)
        by_harness[harness].append((index, total, ran))

    failed = False
    for problem in check_harness_set(harnesses, by_harness):
        failed = True
        print(f"FAIL  {problem}")

    for harness in harnesses:
        if harness not in by_harness:
            continue  # already named by check_harness_set
        expected = expected_mutants(root, harness)
        problems = check(harness, by_harness[harness], expected)
        if problems:
            failed = True
            for problem in problems:
                print(f"FAIL  {harness}: {problem}")
        else:
            shards = len(by_harness[harness])
            print(
                f"PASS  {harness}: {len(expected)} mutant(s) covered "
                f"across {shards} shard(s)"
            )
    if failed:
        raise SystemExit(1)
    print(f"PASS  every mutation harness fully covered ({len(harnesses)} harness(es))")


def self_test():
    """The checker has to fail on the shapes it exists to catch."""
    full = ["a", "b", "c", "d"]

    cases = [
        (
            "complete two-shard split",
            [(1, 2, ["a", "c"]), (2, 2, ["b", "d"])],
            full,
            0,
        ),
        (
            "a shard's job never ran",
            [(1, 2, ["a", "c"])],
            full,
            2,  # missing shard 2, and its mutants uncovered
        ),
        (
            "one mutant dropped from an otherwise complete split",
            [(1, 2, ["a", "c"]), (2, 2, ["b"])],
            full,
            1,
        ),
        (
            "shards disagree about how many there are",
            [(1, 2, ["a", "c"]), (2, 3, ["b", "d"])],
            full,
            1,
        ),
        (
            "the same mutant run twice",
            [(1, 2, ["a", "b", "c"]), (2, 2, ["b", "d"])],
            full,
            1,
        ),
        (
            "a mutant the harness does not list",
            [(1, 1, ["a", "b", "c", "d", "e"])],
            full,
            1,
        ),
        (
            "matrix grew but the shards are from before it did",
            [(1, 2, ["a", "c"]), (2, 2, ["b", "d"])],
            full + ["e"],
            1,
        ),
        (
            "a zero-based shard index from the convention next door",
            [(0, 2, ["a", "c"]), (1, 2, ["b", "d"])],
            full,
            2,  # shard 2 missing, and shard 0 out of range
        ),
    ]

    # The other half: which harnesses reported at all. check() cannot see a
    # harness that contributed nothing, because it is only ever called with
    # one that did -- so this block owns the "three harnesses instead of four"
    # case.
    four = [f"h{i}" for i in range(4)]

    set_cases = [
        ("every harness reported", four, list(four), 0),
        ("a harness's shard jobs dropped from gates.yml", four, four[:-1], 1),
        ("only one harness's jobs ran at all", four, four[:1], 1),
        ("coverage from a harness with no matrix file", four, four + ["ghost"], 1),
        (
            "a harness swapped for one the tree does not know",
            four,
            four[:-1] + ["x"],
            2,
        ),
    ]

    bad = 0
    for name, shards, expected, want in cases:
        problems = check("demo", shards, expected)
        got = len(problems)
        if got != want:
            bad += 1
            print(f"FAIL  self-test {name!r}: expected {want} problem(s), got {got}")
            for problem in problems:
                print(f"          {problem}")
        else:
            print(f"PASS  self-test: {name}")

    for name, expected, reported, want in set_cases:
        problems = check_harness_set(expected, reported)
        got = len(problems)
        if got != want:
            bad += 1
            print(f"FAIL  self-test {name!r}: expected {want} problem(s), got {got}")
            for problem in problems:
                print(f"          {problem}")
        else:
            print(f"PASS  self-test: {name}")

    # And the derivation feeding it, since "expected" is only trustworthy if
    # the glob finds harnesses in both matrix shapes and skips directories
    # that merely sit next to them. Built in a temp tree: a self-test that
    # reads the real checkout would pass for as long as the checkout happens
    # to agree. The tsv fixture uses the pattern-or record form so the field
    # extraction is exercised, not just the glob.
    sourced = '#!/bin/sh\n. "$root/scripts/mutant-coverage/shard.sh"\n'
    with tempfile.TemporaryDirectory() as tmp:
        scripts = pathlib.Path(tmp) / "scripts"
        (scripts / "alpha-contract").mkdir(parents=True)
        (scripts / "alpha-contract" / "matrix.txt").write_text(
            "# comment\nm1\nm2\n", encoding="utf-8"
        )
        (scripts / "alpha-contract" / "run.sh").write_text(sourced, encoding="utf-8")
        (scripts / "beta-contract").mkdir()
        (scripts / "beta-contract" / "matrix.tsv").write_text(
            "schema\t1\n# comment\nmutant\tm3\tsrc/x.dawn\towner three\n",
            encoding="utf-8",
        )
        (scripts / "beta-contract" / "run.sh").write_text(sourced, encoding="utf-8")
        # a single-job matrix harness (the pipe-contract shape): matrix.txt,
        # run.sh, no shard library -- must stay out of the expected set
        (scripts / "whole-contract").mkdir()
        (scripts / "whole-contract" / "matrix.txt").write_text(
            "m9\n", encoding="utf-8"
        )
        (scripts / "whole-contract" / "run.sh").write_text(
            "#!/bin/sh\n", encoding="utf-8"
        )
        (scripts / "plain-contract").mkdir()
        (scripts / "plain-contract" / "run.sh").write_text(
            "#!/bin/sh\n", encoding="utf-8"
        )
        (scripts / "__pycache__").mkdir()

        root = pathlib.Path(tmp)
        got = expected_harnesses(root)
        want_names = ["alpha-contract", "beta-contract"]
        if got != want_names:
            bad += 1
            print(f"FAIL  self-test 'harnesses derived from the tree': {got}")
        else:
            print(
                "PASS  self-test: harnesses derived from the tree, not from "
                "reports, and single-job matrices stay out"
            )

        got_tsv = expected_mutants(root, "beta-contract")
        if got_tsv != ["m3"]:
            bad += 1
            print(f"FAIL  self-test 'tsv names from the second field': {got_tsv}")
        else:
            print("PASS  self-test: tsv names come from the record's second field")

        got_txt = expected_mutants(root, "alpha-contract")
        if got_txt != ["m1", "m2"]:
            bad += 1
            print(f"FAIL  self-test 'txt names one per line': {got_txt}")
        else:
            print("PASS  self-test: txt names are one per line, comments skipped")

    total = len(cases) + len(set_cases) + 3
    if bad:
        raise SystemExit(1)
    print(f"PASS  coverage checker self-test ({total} cases)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--coverage-dir", type=pathlib.Path)
    ap.add_argument(
        "--root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[2],
        help="repository root (holds scripts/<harness>/matrix.{txt,tsv})",
    )
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if args.coverage_dir is None:
        ap.error("--coverage-dir is required unless --self-test")
    run(args.coverage_dir, args.root)


if __name__ == "__main__":
    main()
