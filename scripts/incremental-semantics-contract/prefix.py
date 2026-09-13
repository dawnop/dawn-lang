#!/usr/bin/env python3
"""Compare warm sessions with the frozen cold loop and prove real cache hits.

Each mutation is built before either owning assertion is evaluated. Runtime
linkage errors and timeouts never substitute for a cache-contract failure.

`--shards N --shard I` splits the twelve engine mutants by index modulo N, the
same convention diagnostic-reads.py uses. The no-flag invocation is unchanged:
one positive subject and all twelve mutants, in this file's order.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from cold import ROOT, HERE, OWNER, edit, run


def owning_assertion(output):
    return bool(re.search(
        r"^FAIL\s+prefix :: prefix cache [^\n]*\n\s+assertion failed:", output, re.M))


def check_cli():
    """Exercise actual CLI parsing and current-source partitions without a compiler."""
    cases = [
        (['--shards', '0'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '-1'], 2, 'require --shards >= 1'),
        (['--shards', '2', '--shard', '2'], 2, 'require --shards >= 1'),
        (['--shards', '13', '--shard', '12'], 2, 'selected shard has no engine mutants'),
        (['--shards', '13', '--check-shards'], 2, 'every shard must contain engine mutants'),
    ]
    for count in [1, 2, 3]:
        cases.append((['--shards', str(count), '--check-shards'], 0, 'unique mutants; disjoint shard sizes'))
    for args, expected, message in cases:
        result = subprocess.run([sys.executable, __file__, *args], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if result.returncode != expected or message not in result.stdout:
            raise RuntimeError(f'CLI contract failed for {args}: {result.stdout}')
    print(f'OK: prefix shard CLI contracts ({len(cases)} cases)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shards', type=int, default=1)
    parser.add_argument('--shard', type=int, default=0)
    parser.add_argument('--check-shards', action='store_true',
                        help='validate mutation anchors and complete disjoint shard coverage without compiling')
    parser.add_argument('--self-test', action='store_true', help='check shard CLI contracts without compiling')
    args = parser.parse_args()
    if args.self_test:
        check_cli()
        return
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error('require --shards >= 1 and 0 <= --shard < --shards')
    started = time.monotonic()
    assert owning_assertion("FAIL  prefix :: prefix cache control\n      assertion failed: expected hit\n")
    assert not owning_assertion("FAIL  prefix :: prefix cache control\n      NoSuchMethodError\n")
    assert not owning_assertion("FAIL  elsewhere :: prefix cache control\n      assertion failed: x\n")
    reference = (HERE / "reference-tests.dawn.txt").read_text()
    reference = edit(reference, "use std/io\n",
                     "use std/io\nuse compiler/driver/incremental\n")
    reference = edit(reference, "use compiler/check/jsig.{jsig_refused}",
                     "use compiler/check/jsig.{jsig_refused, refused_probe}")
    reference = edit(reference, "    for loaded in cases {\n      for opts in [ct_default(), ct_fuel(0)] {",
                     "    for opts in [ct_default(), ct_fuel(0)] {\n"
                     "      var owner = incremental.new(std, opts, jsig_refused(), refused_probe, 100, 100000)\n"
                     "      for loaded in cases {")
    reference = edit(reference,
                     "        let current = analyze_program(loaded, std, opts, jsig_refused())",
                     "        let first = incremental.analyze(owner, loaded)\n"
                     "        let warm = incremental.analyze(first.session, loaded)\n"
                     "        owner = warm.session\n"
                     "        let current = warm.program")
    reference = edit(reference,
                     "    let current = analyze_program(loaded, std, ct_default(), jsig_refused())",
                     "    let owner = incremental.new(std, ct_default(), jsig_refused(), refused_probe, 100, 100000)\n"
                     "    let first = incremental.analyze(owner, loaded)\n"
                     "    let current = incremental.analyze(first.session, loaded).program")
    original = (ROOT / "selfhost/src/driver/incremental.dawn").read_text()
    variants = [
        ("always-cold", "    let hit = matching &&", "    let hit = false &&"),
        ("text-only", "a == b", "a.text == b.text"),
        ("resume-suffix", "      matching = false\n", "      ()\n"),
        ("cache-errors", "len(computed.diags) != 0 || ", ""),
        ("cache-java", " || probe.queries() != queries_before", ""),
        ("ignore-loader", "len(loaded.diags) == 0 && ", ""),
        ("ignore-ffi", "not session.opts.ffi", "true"),
        ("ignore-eviction", "  State { ..session, prefix: [] }", "  session"),
        ("ignore-module-budget", "len(prefix) < session.max_modules", "true"),
        ("ignore-text-budget", "units <= session.max_text_units - text_units", "true"),
        ("ignore-std-identity", "identity == session.prefix[index].std_identity", "true"),
        ("allow-negative-budget",
         '  if max_modules < 0 || max_text_units < 0 { panic("negative analysis cache limit") }',
         "  ()"),
    ]
    # Every anchor is applied in every shard, before anything is built. The edits
    # are string replacements and cost nothing, so a shard that builds four
    # mutants still refuses a subject whose anchor has drifted under it, which is
    # the failure this family exists to catch and the one a partial run would
    # otherwise hide until some other shard happened to run.
    mutants = [(name, edit(original, old, new)) for name, old, new in variants]
    names = [name for name, _ in mutants]
    if len(set(names)) != len(names):
        raise RuntimeError('Duplicate engine mutant identity')
    if args.check_shards:
        partitions = [names[index::args.shards] for index in range(args.shards)]
        if any(not partition for partition in partitions):
            parser.error('every shard must contain engine mutants')
        covered = [name for partition in partitions for name in partition]
        if len(covered) != len(names) or set(covered) != set(names):
            raise RuntimeError('Shard coverage is incomplete or duplicated')
        print(f'OK: {len(names)} unique mutants; disjoint shard sizes ' +
              ', '.join(str(len(partition)) for partition in partitions))
        return
    selected = [mutant for index, mutant in enumerate(mutants) if index % args.shards == args.shard]
    if not selected:
        parser.error('the selected shard has no engine mutants')
    # The positive subject runs in shard 0 only, and that is a measurement
    # rather than a preference. The subjects cost the same as each other
    # (24.3 to 24.4s each of shard 0's 122.52s, measured locally at loadavg
    # 3.5 to 4.9 on 2026-09-13, and 67s each under a loaded sweep), so on a
    # runner a subject is prefix's observed 497s over thirteen, about 38s.
    # Rerunning the positive in each shard would take the other two shards
    # from 153s to 191s, and the only two jobs with room for a shard at all
    # sit at 758s and 736s: 949s and 927s, both past the 920s of the longest
    # job in that run and one of them within a second of the 950s pole.
    #
    # What a positive-less shard still has: its own acceptance predicate is
    # self-tested above (a named assertion is accepted, a linkage error and a
    # foreign owner are not), every subject in it must still build or the
    # shard raises, and a mutant that dies any way other than the two named
    # assertions is refused by the `oracle execution failed` branch below
    # rather than counted, so a broken oracle has to be broken into reporting
    # one specific assertion to be invisible. What it does not have is the one
    # thing only an unmutated subject can show, that those assertions are not
    # stuck on FAIL. That is a property of the tree and not of the shard: it is
    # established once per run by shard 0, over the same commit, and a run
    # whose oracle is broken goes red there.
    subjects = ([("positive", original)] if args.shard == 0 else []) + selected
    with tempfile.TemporaryDirectory(prefix="dawn-prefix-reference-") as temp:
        root = Path(temp)
        classes = root / "classes"
        classes.mkdir()
        subprocess.run(["javac", "--release", "21", "-d", str(classes),
                        str(HERE / "SemanticSnapshot.java")], check=True)
        oracle = root / "snapshot.jar"
        subprocess.run(["jar", "cf", str(oracle), "-C", str(classes), "."], check=True)
        for directory in ("selfhost", "compiler-plan"):
            shutil.copytree(ROOT / directory, root / directory, ignore=shutil.ignore_patterns("build", ".dawn"))
        (root / "packages").symlink_to(ROOT / "packages", target_is_directory=True)
        fixture = root / "scripts/incremental-semantics-contract"
        shutil.copytree(HERE, fixture)
        (fixture / "src/reference.dawn").write_text(reference)
        driver = root / "selfhost/src/driver/analyze.dawn"
        driver.write_text(driver.read_text() + "\n" + (HERE / "reference-loop.dawn.txt").read_text())
        for name, source in subjects:
            subject_started = time.monotonic()
            (root / "selfhost/src/driver/incremental.dawn").write_text(source)
            status, output = run("build", fixture, "-o", root / "subject.jar")
            if status:
                raise RuntimeError(f"{name} did not compile\n{output}")
            result = subprocess.run(["java", "-Xss64m", "-Xmx2g", "-cp",
                                     str(oracle) + os.pathsep + str(root / "subject.jar"),
                                     "contract.SemanticSnapshot"], cwd=ROOT, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
            semantic_failure = result.returncode and re.search(
                r"^FAIL\s+reference :: " + re.escape(OWNER), result.stdout, re.M)
            if result.returncode and not semantic_failure:
                raise RuntimeError(f"{name} oracle execution failed\n{result.stdout}")
            status, output = run("test", fixture)
            count_failure = status and owning_assertion(output)
            if name == "positive":
                if result.returncode or status:
                    raise RuntimeError(f"positive failed\n{result.stdout}\n{output}")
            elif not semantic_failure and not count_failure:
                raise RuntimeError(f"{name} missed both owning assertions\n{result.stdout}\n{output}")
            print(f"OK: prefix {name} {time.monotonic() - subject_started:.1f}s", flush=True)
    if args.shards == 1:
        print(f"OK: full-product warm/cold reference and {len(variants)} compiling cache mutants")
        return
    print(f"OK: prefix {len(selected)} of {len(variants)} compiling cache mutants, "
          f"shard {args.shard}/{args.shards}, "
          f"{'with' if args.shard == 0 else 'without'} the warm/cold reference, "
          f"{time.monotonic() - started:.2f}s")


if __name__ == "__main__":
    main()
