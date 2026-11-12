#!/usr/bin/env python3
"""Prove that overlap preserves complete results, failures and cleanup."""
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile

HELPER = Path(__file__).with_name("parallel.sh").resolve()
CLI = Path(__file__).resolve().parents[1] / "native-cli-diff.sh"
HEADER = '''set -euo pipefail
OUT="$FIXTURE/work"
mkdir -p "$OUT"
source "$HELPER"
native_parallel_enable
'''


def run(script, expected=0, keep=False, delayed=False, terminate=False, remove_output=False):
    with tempfile.TemporaryDirectory(prefix="native-parallel-fixture-") as temporary:
        root = Path(temporary)
        env = dict(os.environ, FIXTURE=str(root), HELPER=str(HELPER))
        if keep:
            env["KEEP"] = "1"
        else:
            env.pop("KEEP", None)
        allow = None
        if delayed:
            os.mkfifo(root / "ready")
            os.mkfifo(root / "allow")
            ready = os.open(root / "ready", os.O_RDWR | os.O_NONBLOCK)
            allow = os.open(root / "allow", os.O_RDWR | os.O_NONBLOCK)
        header = HEADER.replace("native_parallel_enable\n", "KEEP= native_parallel_enable\n") if remove_output else HEADER
        process = subprocess.Popen(["bash", "-c", header + script], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if delayed:
                assert select.select([ready], [], [], 5)[0], "child never became ready"
                assert os.read(ready, 64) == b"ready\n"
                if terminate:
                    process.send_signal(signal.SIGTERM)
                assert process.poll() is None, "caller left its complete child behind"
                os.write(allow, b"finish\n")
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            if delayed:
                os.close(ready)
                os.close(allow)
        assert process.returncode == expected, (expected, process.returncode, stdout, stderr)
        assert (root / "work").exists() == (keep and not remove_output), "output cleanup or KEEP changed"
        return stdout.decode(), stderr.decode(), (root / "trace").read_text() if (root / "trace").exists() else ""


def main():
    completed = 0
    success = '''native_parallel_start fixture bash -c 'echo child-output; echo child >> "$FIXTURE/trace"'
echo foreground >> "$FIXTURE/trace"
native_parallel_finish
'''
    for keep in (False, True):
        stdout, stderr, trace = run(success, keep=keep)
        assert not stderr and stdout.count("child-output") == 1
        assert sorted(trace.splitlines()) == ["child", "foreground"]
        assert stdout.count("RESUME native parallel fixture status=0") == 1
        completed += 1
    stdout, stderr, trace = run(success, keep=True, remove_output=True)
    assert not stderr and stdout.count("child-output") == 1
    completed += 1
    for joined in (False, True):
        stdout, stderr, _ = run("native_parallel_start fixture bash -c 'echo child-error; exit 41'\n" +
                                ("native_parallel_finish\n" if joined else "exit 0\n"), 41)
        assert stdout.count("child-error") == 1 and not stderr
        completed += 1
    stdout, stderr, _ = run('''fixture_command() { bash -c 'echo callback-error; exit 41'; }
native_parallel_start fixture fixture_command
native_parallel_finish
''', 41)
    assert stdout.count("callback-error") == 1 and not stderr
    completed += 1
    stdout, stderr, _ = run('''fixture_command() { echo callback-before; false; echo callback-after; }
native_parallel_start fixture fixture_command
native_parallel_finish
''', 1)
    assert stdout.count("callback-before") == 1 and "callback-after" not in stdout and not stderr
    completed += 1
    delayed = '''native_parallel_start fixture bash -c 'echo ready > "$FIXTURE/ready"; read -r _ < "$FIXTURE/allow"; echo child-output; echo child >> "$FIXTURE/trace"'
exit 23
'''
    stdout, stderr, trace = run(delayed, 23, delayed=True)
    assert trace == "child\n" and stdout.count("child-output") == 1 and not stderr
    completed += 1
    interrupted = delayed.replace("exit 23", 'read -r _ < "$FIXTURE/foreground"')
    # An unconnected FIFO blocks the foreground without a timing assumption.
    interrupted = 'mkfifo "$FIXTURE/foreground"\n' + interrupted
    stdout, stderr, trace = run(interrupted, 143, delayed=True, terminate=True)
    assert trace == "child\n" and stdout.count("child-output") == 1 and not stderr
    completed += 1
    stdout, stderr, trace = run('''native_parallel_starting=1
native_parallel_signal 143
test "$native_parallel_pending_status" = 143
native_parallel_start fixture bash -c 'echo child-output; echo child >> "$FIXTURE/trace"'
''', 143)
    assert trace == "child\n" and stdout.count("child-output") == 1 and not stderr
    completed += 1
    stdout, stderr, trace = run("native_parallel_start first bash -c 'echo child >> \"$FIXTURE/trace\"'\n"
                                "native_parallel_start second true\n", 2)
    assert trace == "child\n" and "one complete child" in stderr
    completed += 1
    _, stderr, _ = run("native_parallel_finish\n", 2)
    assert "not started" in stderr
    completed += 1
    _, stderr, _ = run("native_parallel_start ../escape true\n", 2)
    assert "one complete child" in stderr
    completed += 1
    # Exercise the real argument guard with a launcher that can never compile.
    with tempfile.TemporaryDirectory(prefix="native-parallel-arguments-") as temporary:
        root = Path(temporary)
        (root / "scripts/native-cli-contract").mkdir(parents=True)
        (root / "bin").mkdir()
        (root / "tmp").mkdir()
        (root / "scripts/native-cli-diff.sh").symlink_to(CLI)
        (root / "scripts/native-cli-contract/parallel.sh").symlink_to(HELPER)
        launcher = root / "bin/dawn"
        launcher.write_text('#!/bin/sh\necho launched > "$FIXTURE/launcher"\nexit 99\n')
        launcher.chmod(0o755)
        cases = [(["--unknown"], {}, 2), ([], {}, 99), (["--parallel"], {}, 99)]
        for variable in ("NATIVE_CLI_ARITY_ONLY", "NATIVE_CLI_RUN_ONLY", "NATIVE_CLI_STD_ONLY"):
            cases.append((["--parallel"], {variable: "1"}, 2))
        for args, flags, expected in cases:
            env = dict(os.environ, FIXTURE=str(root), TMPDIR=str(root / "tmp"))
            for variable in ("NATIVE_CLI_ARITY_ONLY", "NATIVE_CLI_RUN_ONLY", "NATIVE_CLI_STD_ONLY", "KEEP"):
                env.pop(variable, None)
            env.update(flags)
            (root / "launcher").unlink(missing_ok=True)
            result = subprocess.run(["bash", str(root / "scripts/native-cli-diff.sh"), *args],
                                    env=env, capture_output=True, timeout=5)
            assert result.returncode == expected, (args, flags, result)
            assert (root / "launcher").exists() == (expected == 99)
            completed += 1
    print(f"OK: native parallel control, {completed} complete-result and recovery fixtures")


if __name__ == "__main__":
    main()
