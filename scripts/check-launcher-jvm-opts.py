#!/usr/bin/env python3
"""The JVM options bin/dawn starts each kind of process with, and their copies.

Why this file exists: the launcher picks the collector by process shape (the
2026-10-20 ruling). Short-lived compiles keep SerialGC, whose resident set G1
inflated; the language server, which lives as long as the editor and answers
each keystroke, runs ParallelGC, because SerialGC's young pauses landed inside
the edited file's diagnostics often enough to put L-edit's p90 over 100 ms
(numbers in bin/dawn and docs/audit/lsp-robustness-design.md section 2.2.7).
Nothing a green build shows depends on that choice: a server that silently
went back to SerialGC answers every request the same, only later. So the
choice is held here, together with the copies the launcher's comment says must
move with it:

- the compile options are written three times (bin/dawn, child_java_cmd() in
  selfhost/src/main.dawn, TOOLCHAIN_JVM_OPTS in scripts/selfhost-bench.py),
  and that rule was prose until now;
- scripts/lsp-sync-bench/bench.py starts servers without the launcher and must
  start them the way the launcher does, or the release measurement judges a
  configuration no editor runs.

The launcher half is driven, not only read: a copy of bin/dawn in its deployed
form (no scripts/seedjar.sh beside it, so it execs the shipped jar at once) runs
against a fake `java` that writes down its options. The repo form's exec is held
to the same variable by reading it, since that path needs a seed and a build.

`--selftest` builds one regression per assertion and requires each to turn the
check red, so a check that stopped looking would be caught too.

Exit status: 0 holds, 1 a copy or the launcher disagrees, 2 a line it reads is
missing or not unique (it locates them by spelling; scripts/anchor-readers.txt).
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = "bin/dawn"
MAIN = "selfhost/src/main.dawn"
SELFHOST_BENCH = "scripts/selfhost-bench.py"
LSP_BENCH = "scripts/lsp-sync-bench/bench.py"
FILES = (LAUNCHER, MAIN, SELFHOST_BENCH, LSP_BENCH)

COMPILE_GC = "-XX:+UseSerialGC"
LSP_GC = "-XX:+UseParallelGC"
GC_FLAG = re.compile(r"^-XX:\+Use\w+GC$")

FAKE_JAVA = """#!/bin/sh
# Writes the options before -jar, one per line, then the subcommand.
while [ "$#" -gt 0 ] && [ "$1" != -jar ]; do
  printf 'opt %s\\n' "$1" >> "$FAKE_JAVA_LOG"
  shift
done
printf 'cmd %s\\n' "${3:-}" >> "$FAKE_JAVA_LOG"
"""


class Missing(Exception):
    """A line this check locates by spelling is gone or not unique (status 2)."""


def one(pattern: str, text: str, where: str, flags: int = 0) -> re.Match:
    found = list(re.finditer(pattern, text, flags))
    if len(found) != 1:
        raise Missing(f"{where}: expected exactly one match of {pattern!r}, found {len(found)}")
    return found[0]


def launcher_opts(text: str) -> tuple[list[str], list[str]]:
    """The compile default and the language server default written in bin/dawn."""
    compile_ = one(r'^DAWN_JVM_OPTS="\$\{DAWN_JVM_OPTS:-([^}"]*)\}"$', text, LAUNCHER, re.M)
    lsp = one(r'^DAWN_LSP_JVM_OPTS="([^"$]*)"$', text, LAUNCHER, re.M)
    return compile_.group(1).split(), lsp.group(1).split()


def python_strings(text: str, name: str, where: str) -> list[str]:
    m = one(rf"^{name} = [\[(]([^\])]*)[\])]$", text, where, re.M)
    return re.findall(r'"([^"]*)"', m.group(1))


def child_java_cmd(text: str) -> list[str]:
    m = one(r"^fn child_java_cmd\(\) -> List\[String\] !io =\n((?:  .*\n)+)", text, MAIN, re.M)
    body = m.group(1)
    return re.findall(r'"([^"]*)"', body) + (["own_xmx()"] if "own_xmx()" in body else [])


def gc_of(opts: list[str]) -> list[str]:
    return [o for o in opts if GC_FLAG.match(o)]


def static_problems(texts: dict[str, str]) -> list[str]:
    bad = []
    compile_, lsp = launcher_opts(texts[LAUNCHER])
    if gc_of(compile_) != [COMPILE_GC]:
        bad.append(f"{LAUNCHER}: the compile default names {gc_of(compile_)}, not [{COMPILE_GC}]")
    if gc_of(lsp) != [LSP_GC]:
        bad.append(f"{LAUNCHER}: the language server default names {gc_of(lsp)}, not [{LSP_GC}]")
    rest = lambda opts: [o for o in opts if not GC_FLAG.match(o)]  # noqa: E731
    if rest(lsp) != rest(compile_):
        bad.append(f"{LAUNCHER}: the language server default {lsp} differs from the compile "
                   f"default {compile_} in more than the collector")
    # Every exec of the toolchain jar runs with the per-subcommand choice; every
    # other java call (the rebuild's seed, stage 1 and producer) is a compile.
    for n, line in enumerate(texts[LAUNCHER].splitlines(), 1):
        if '"$JAVA"' not in line or "-jar" not in line:
            continue
        want = "$DAWN_RUN_JVM_OPTS" if '-jar "$SJAR"' in line else "$DAWN_JVM_OPTS"
        if f'"$JAVA" {want} -XX:-UsePerfData -jar' not in line:
            bad.append(f"{LAUNCHER}:{n}: expected {want} on: {line.strip()}")
    child = child_java_cmd(texts[MAIN])
    xss = [o for o in compile_ if o.startswith("-Xss")]
    for o in xss + [COMPILE_GC, "own_xmx()"]:
        if o not in child:
            bad.append(f"{MAIN}: child_java_cmd() lacks {o} (bin/dawn's compile default is {compile_})")
    if gc_of(child) != [COMPILE_GC]:
        bad.append(f"{MAIN}: child_java_cmd() names {gc_of(child)}, not [{COMPILE_GC}]")
    tool = python_strings(texts[SELFHOST_BENCH], "TOOLCHAIN_JVM_OPTS", SELFHOST_BENCH)
    if tool != compile_:
        bad.append(f"{SELFHOST_BENCH}: TOOLCHAIN_JVM_OPTS {tool} != bin/dawn's compile default {compile_}")
    bench = python_strings(texts[LSP_BENCH], "JVM_OPTS", LSP_BENCH)
    if bench != lsp:
        bad.append(f"{LSP_BENCH}: JVM_OPTS {bench} != bin/dawn's language server default {lsp}")
    return bad


def launched(launcher: str, args: list[str], env_opts: str | None) -> tuple[list[str], str]:
    """Run a deployed-form copy of the launcher; return the options java got and the subcommand."""
    with tempfile.TemporaryDirectory(prefix="launcher-jvm-opts.") as d:
        root = Path(d)
        (root / "bin").mkdir()
        (root / "build").mkdir()
        (root / "jdk/bin").mkdir(parents=True)
        (root / "bin/dawn").write_text(launcher)
        (root / "bin/dawn").chmod(0o755)
        (root / "build/dawn-selfhost.jar").write_text("not a jar\n")
        (root / "jdk/bin/java").write_text(FAKE_JAVA)
        (root / "jdk/bin/java").chmod(0o755)
        log = root / "java.log"
        env = {k: v for k, v in os.environ.items() if not k.startswith("DAWN_")}
        env.update(JAVA_HOME=str(root / "jdk"), FAKE_JAVA_LOG=str(log))
        if env_opts is not None:
            env["DAWN_JVM_OPTS"] = env_opts
        done = subprocess.run(["sh", str(root / "bin/dawn"), *args], env=env,
                              capture_output=True, text=True, timeout=30)
        if done.returncode != 0 or not log.exists():
            return [], f"<launcher exited {done.returncode}: {done.stderr.strip()[-300:]}>"
        opts, cmd = [], ""
        for line in log.read_text().splitlines():
            kind, _, value = line.partition(" ")
            if kind == "opt":
                opts.append(value)
            else:
                cmd = value
        return opts, cmd


def behaviour_problems(texts: dict[str, str]) -> list[str]:
    compile_, lsp = launcher_opts(texts[LAUNCHER])
    cases = [
        (["lsp"], None, lsp, "an editor's `dawn lsp`"),
        (["lsp", "--std", "x"], "", lsp, "`dawn lsp` with DAWN_JVM_OPTS empty (the launcher's :- reads it as unset)"),
        (["check", "x.dawn"], None, compile_, "`dawn check`"),
        (["test", "lsp"], None, compile_, "`dawn test lsp` (lsp is an argument, not the subcommand)"),
        (["lsp"], "-Xss64m -Xmx64m", ["-Xss64m", "-Xmx64m"], "`dawn lsp` with DAWN_JVM_OPTS given"),
        (["check", "x.dawn"], "-Xmx64m", ["-Xmx64m"], "`dawn check` with DAWN_JVM_OPTS given"),
        (["check", "x.dawn"], "-Xmx64m -XX:+UsePerfData",
         ["-Xmx64m", "-XX:+UsePerfData"], "an explicit perf-data override"),
    ]
    bad = []
    for args, env_opts, want, what in cases:
        got, cmd = launched(texts[LAUNCHER], args, env_opts)
        want = want + ["-XX:-UsePerfData"]
        if got != want or cmd != args[0]:
            bad.append(f"{what}: java got {got} for {cmd!r}, expected {want} for {args[0]!r}")
    return bad


def problems(texts: dict[str, str]) -> list[str]:
    bad = static_problems(texts)
    return bad + (behaviour_problems(texts) if not bad else [])


def read_tree() -> dict[str, str]:
    return {f: (ROOT / f).read_text() for f in FILES}


def swap(texts: dict[str, str], path: str, old: str, new: str) -> dict[str, str]:
    if texts[path].count(old) != 1:
        raise Missing(f"self-test regression anchor in {path} matched {texts[path].count(old)} times: {old!r}")
    return {**texts, path: texts[path].replace(old, new, 1)}


def self_test() -> None:
    texts = read_tree()
    assert problems(texts) == [], problems(texts)
    lsp_line = one(r'^DAWN_LSP_JVM_OPTS="[^"$]*"$', texts[LAUNCHER], LAUNCHER, re.M).group(0)
    regressions = {
        "the launcher permits HotSpot warnings in compared output":
            (LAUNCHER, '\nexec "$JAVA" $DAWN_RUN_JVM_OPTS -XX:-UsePerfData -jar',
             '\nexec "$JAVA" $DAWN_RUN_JVM_OPTS -jar'),
        "the language server default names SerialGC":
            (LAUNCHER, lsp_line, lsp_line.replace(LSP_GC, COMPILE_GC)),
        "the language server default drops -Xss":
            (LAUNCHER, lsp_line, lsp_line.replace("-Xss512m ", "")),
        "the lsp branch is never taken":
            (LAUNCHER, '  lsp) DAWN_RUN_JVM_OPTS=', '  __never) DAWN_RUN_JVM_OPTS='),
        "an explicit DAWN_JVM_OPTS is overridden for lsp":
            (LAUNCHER, 'if [ -z "$DAWN_JVM_OPTS_GIVEN" ]; then', 'if true; then'),
        "the repo form's exec runs the compile options":
            (LAUNCHER, '\nexec "$JAVA" $DAWN_RUN_JVM_OPTS -XX:-UsePerfData -jar "$SJAR" "$@"\n',
             '\nexec "$JAVA" $DAWN_JVM_OPTS -XX:-UsePerfData -jar "$SJAR" "$@"\n'),
        "the deployed form's exec runs the compile options":
            (LAUNCHER, '\n  exec "$JAVA" $DAWN_RUN_JVM_OPTS -XX:-UsePerfData -jar "$SJAR" "$@"\n',
             '\n  exec "$JAVA" $DAWN_JVM_OPTS -XX:-UsePerfData -jar "$SJAR" "$@"\n'),
        "a rebuild compiles with the language server's options":
            (LAUNCHER, '"$JAVA" $DAWN_JVM_OPTS -XX:-UsePerfData -jar "$SEED" build',
             '"$JAVA" $DAWN_RUN_JVM_OPTS -XX:-UsePerfData -jar "$SEED" build'),
        "child_java_cmd() drifts from the compile collector":
            (MAIN, '"-XX:+UseSerialGC", "-XX:-UsePerfData"', '"-XX:+UseG1GC", "-XX:-UsePerfData"'),
        "selfhost-bench drifts from the compile default":
            (SELFHOST_BENCH, 'TOOLCHAIN_JVM_OPTS = ("-Xss512m", "-Xmx2g",',
             'TOOLCHAIN_JVM_OPTS = ("-Xss512m", "-Xmx4g",'),
        "lsp-sync-bench measures SerialGC":
            (LSP_BENCH, f'JVM_OPTS = ["-Xss512m", "-Xmx2g", "{LSP_GC}"]',
             'JVM_OPTS = ["-Xss512m", "-Xmx2g", "-XX:+UseSerialGC"]'),
    }
    for name, (path, old, new) in regressions.items():
        found = problems(swap(texts, path, old, new))
        if not found:
            raise AssertionError(f"regression not caught: {name}")
        print(f"PASS  {name}: {found[0]}")
    print(f"OK: launcher JVM options self-test ({len(regressions)} regressions caught)")


def main(argv: list[str]) -> int:
    try:
        if argv == ["--selftest"]:
            self_test()
            return 0
        if argv:
            print("usage: check-launcher-jvm-opts.py [--selftest]", file=sys.stderr)
            return 2
        bad = problems(read_tree())
    except Missing as e:
        print(f"check-launcher-jvm-opts: {e}", file=sys.stderr)
        return 2
    for b in bad:
        print(f"FAIL: {b}", file=sys.stderr)
    if bad:
        return 1
    _, lsp = launcher_opts(read_tree()[LAUNCHER])
    print(f"OK: dawn lsp runs {shlex.join(lsp)}; compiles and the three copies agree")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
