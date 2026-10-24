#!/usr/bin/env python3
"""Lock the next JVM's real perf-data file before exec, then compare its bytes.

A synthetic warning alone would only test a filter. The positive control here
makes HotSpot emit the warning itself; the deployed launcher must suppress its
cause while preserving both application streams. Pipes pause a Python launcher
at its final PID until the parent owns both kinds of advisory lock. No PID
prediction, scheduling assumption, or changes to another process's file.
This is a local fault probe, outside the external gates: HotSpot fixes the
file under /tmp even when TMPDIR is private to a gate prefix. The gate
check-launcher-jvm-opts.py holds the launch shape without touching that path.
"""

import fcntl
import os
from pathlib import Path
import pwd
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
FLAG = "-XX:-UsePerfData"
WARNING = b"[warning][perf,memops]"
HELPER = '''import os, sys
os.write(int(os.environ["PERF_READY"]), str(os.getpid()).encode() + b"\\n")
os.close(int(os.environ["PERF_READY"]))
assert os.read(int(os.environ["PERF_GO"]), 1) == b"x"
os.close(int(os.environ["PERF_GO"]))
os.execv(sys.argv[1], sys.argv[1:])
'''


def locked_run(command, env):
    ready_r, ready_w = os.pipe()
    go_r, go_w = os.pipe()
    try:
        child_env = dict(env, PERF_READY=str(ready_w), PERF_GO=str(go_r))
        proc = subprocess.Popen(command, env=child_env, pass_fds=(ready_w, go_r),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(ready_w)
        ready_w = -1
        os.close(go_r)
        go_r = -1
        with os.fdopen(os.dup(ready_r), "rb") as ready:
            # A launcher that never reaches java must fail instead of hanging.
            if not select.select([ready], [], [], 15)[0]:
                raise AssertionError("the launcher did not reach the JVM within 15 seconds")
            pid = int(ready.readline())
        directory = Path("/tmp") / ("hsperfdata_" + pwd.getpwuid(os.getuid()).pw_name)
        directory.mkdir(mode=0o700, exist_ok=True)
        path = directory / str(pid)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(fd, 32768)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(go_w, b"x")
            out, err = proc.communicate(timeout=15)
            assert proc.returncode == 0, "the probe JVM failed"
            return out, err
        finally:
            os.close(fd)
            path.unlink(missing_ok=True)
    finally:
        if "proc" in locals() and proc.poll() is None:
            proc.kill()
            proc.communicate()
        for fd in (ready_r, ready_w, go_r, go_w):
            if fd >= 0:
                os.close(fd)


def main():
    start = time.monotonic()
    java = subprocess.check_output([str(ROOT / "bin/dawn")],
                                  env=dict(os.environ, DAWN_LAUNCHER_PRINT_JAVA="1"), text=True).strip()
    jdk = Path(java).parent
    with tempfile.TemporaryDirectory(prefix="perf-data.") as tmp:
        work = Path(tmp)
        (work / "Probe.java").write_text(
            'public class Probe { public static void main(String[] args) {\n'
            '  System.out.println("application stdout");\n'
            '  System.err.println("application stderr");\n'
            '} }\n')
        subprocess.run([str(jdk / "javac"), "-J-XX:-UsePerfData", str(work / "Probe.java")], check=True)
        (work / "build").mkdir()
        jar = work / "build/dawn-selfhost.jar"
        subprocess.run([str(jdk / "jar"), "-J-XX:-UsePerfData", "--create", "--file", str(jar),
                        "--main-class", "Probe", "-C", str(work), "Probe.class"], check=True)
        helper = work / "java.py"
        helper.write_text(HELPER)
        prefix = [sys.executable, str(helper), java]
        env = dict(os.environ)
        # The positive control also overrides the external prefix's shim flag.
        out, err = locked_run(prefix + ["-XX:+UsePerfData", "-jar", str(jar)], env)
        assert WARNING in out + err, "the locked-file control did not produce a HotSpot warning"
        assert b"application stdout\n" in out and err.endswith(b"application stderr\n")
        print("PASS  a locked perf-data file produces the original HotSpot warning")
        out, err = locked_run(prefix + [FLAG, "-jar", str(jar)], env)
        assert (out, err) == (b"application stdout\n", b"application stderr\n")
        print("PASS  disabling perf data preserves both application streams byte for byte")
        (work / "bin").mkdir()
        shutil.copy2(ROOT / "bin/dawn", work / "bin/dawn")
        (work / "jdk/bin").mkdir(parents=True)
        shim = work / "jdk/bin/java"
        shim.write_text("#!/bin/sh\nexec " + shlex.join(prefix) + ' "$@"\n')
        shim.chmod(0o755)
        env.update(JAVA_HOME=str(work / "jdk"), DAWN_JVM_OPTS="-Xmx64m -XX:+UsePerfData")
        env.pop("DAWN_LAUNCHER_PRINT_JAVA", None)
        for subcommand in ("check", "lsp", "run"):
            out, err = locked_run([str(work / "bin/dawn"), subcommand], env)
            assert (out, err) == (b"application stdout\n", b"application stderr\n"), subcommand
        print("PASS  compiler, LSP and run launches stay clean even with a perf-data override")
        out, err = locked_run([str(ROOT / "playground/test/java-no-perf.sh"), "-jar", str(jar)], env)
        assert (out, err) == (b"application stdout\n", b"application stderr\n")
        javap = work / "jdk/bin/javap"
        javap.write_text("#!/bin/sh\nexec " + shlex.join(
            [sys.executable, str(helper), str(jdk / "javap")]) + ' "$@"\n')
        javap.chmod(0o755)
        listing = ["-c", str(work / "Probe.class")]
        expected = subprocess.run([str(jdk / "javap"), "-J-XX:-UsePerfData", *listing],
                                  capture_output=True, check=True)
        actual = locked_run([str(ROOT / "playground/test/javap-no-perf.sh"), *listing], env)
        assert actual == (expected.stdout, expected.stderr)
        print("PASS  paired playground tools preserve Java and javap bytes under the same file lock")
    print(f"OK: perf-data lock fault injection ({time.monotonic() - start:.2f}s)")


if __name__ == "__main__":
    main()
