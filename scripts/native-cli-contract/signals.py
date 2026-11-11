"""Check cancellation of real compiler descendants using the supplied driver."""
import argparse
import ctypes
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def descendants(pid):
    found = []
    pending = [pid]
    while pending:
        parent = pending.pop()
        try:
            tasks = list(Path(f"/proc/{parent}/task").iterdir())
        except FileNotFoundError:
            continue
        for task in tasks:
            try:
                children = (task / "children").read_text().split()
            except FileNotFoundError:
                continue
            for child in map(int, children):
                if child not in found:
                    found.append(child)
                    pending.append(child)
    return found


def cleanup(proc, children):
    children = list(dict.fromkeys([*children, *descendants(proc.pid)]))
    for pid in reversed(children):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    for _ in range(100):
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            return
        time.sleep(.01)
    raise AssertionError("probe could not reap an adopted descendant")


def terminate(proc):
    """Let the driver forward shutdown, with descendant cleanup on failure."""
    children = descendants(proc.pid)
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        cleanup(proc, children)


def until(predicate):
    for _ in range(400):
        result = predicate()
        if result:
            return result
        time.sleep(.025)
    raise AssertionError("compiler readiness deadline exceeded")


def compiler_blocked(proc, started):
    if proc.poll() is not None:
        out, err = proc.communicate(timeout=5)
        raise AssertionError(f"driver exited before starting its compiler: {proc.returncode}, {out!r}, {err!r}")
    try:
        pid = int(started.read_text())
        state = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0]
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, ValueError):
        return False
    return state == "S" and b"-include\0" in command


def check(binary):
    cc = shutil.which(os.environ.get("CC", "cc"))
    assert cc, "the native signal contract needs a C compiler"
    libc = ctypes.CDLL(None, use_errno=True)
    assert libc.prctl(36, 1, 0, 0, 0) == 0, "set child subreaper"
    failures = []
    with tempfile.TemporaryDirectory(prefix="native-signals-") as temporary:
        root = Path(temporary)
        fifo = root / "compiler.h"
        os.mkfifo(fifo)
        started = root / "compiler.pid"
        wrapper = root / "cc-wrapper"
        wrapper.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, signal, subprocess, sys\n"
            "signal.signal(signal.SIGINT, signal.SIG_DFL)\n"
            f"child = subprocess.Popen([{cc!r}, '-include', {str(fifo)!r}, *sys.argv[1:]])\n"
            f"pathlib.Path({str(started)!r}).write_text(str(child.pid))\n"
            "sys.exit(child.wait())\n"
        )
        wrapper.chmod(0o755)
        source = root / "main.dawn"
        source.write_text('pub fn main() -> Unit !io = println("signal child")\n')
        tests = root / "tests.dawn"
        tests.write_text('test "signal child" { assert true }\n')
        nested = root / "nested.dawn"
        nested.write_text('use std/io\npub fn main() -> Unit !io = io.with_proc_real(() => {\n'
                          '  let code = match io.run(args(), "", "") {\n'
                          '    Ok(code) -> code\n'
                          '    Err(_) -> 93\n'
                          '  }\n'
                          '  io.with_exit_real(() => io.exit(code))\n})\n')
        c_source = root / "child.c"
        c_source.write_text("int main(void) { return 0; }\n")
        cases = [(command, tests if command == "test" else source, False)
                 for command in ("run", "build", "test")]
        cases.append(("run", nested, True))
        for sig in (signal.SIGINT, signal.SIGTERM):
            for command, target, executing in cases:
                started.unlink(missing_ok=True)
                argv = [str(binary), command, str(target)]
                env = {**os.environ, "CC": str(wrapper), "TMPDIR": str(root)}
                phase = "compiler"
                expected = 2
                if executing:
                    env["CC"] = cc
                    argv += ["--", str(wrapper), str(c_source), "-o", str(root / "child")]
                    phase = "program"
                    expected = 128 + sig
                proc = subprocess.Popen(argv, cwd=root, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, start_new_session=True)
                children = []
                label = f"{command} {phase} descendants receive {signal.Signals(sig).name}"
                try:
                    until(lambda: compiler_blocked(proc, started))
                    children = descendants(proc.pid)
                    groups = {pid: os.getpgid(pid) for pid in children}
                    os.kill(proc.pid, sig)
                    proc.wait(timeout=10)
                    out, err = proc.communicate(timeout=5)
                    assert proc.returncode == expected and out == b"", (proc.returncode, out, err)
                    if not executing:
                        assert b"failed (exit code" in err, err
                    alive = []
                    for pid in children:
                        try:
                            state = Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0]
                        except FileNotFoundError:
                            continue
                        if state != "Z":
                            alive.append(pid)
                    assert not alive, f"live descendants after driver exit: {alive}"
                    assert proc.pid not in groups.values(), groups
                    if executing:
                        assert len(set(groups.values())) >= 2, groups
                    else:
                        assert len(set(groups.values())) == 1, groups
                    print("PASS " + label, flush=True)
                except (AssertionError, subprocess.TimeoutExpired) as error:
                    failures.append(label + ": " + str(error))
                    print("FAIL " + failures[-1], flush=True)
                finally:
                    cleanup(proc, children)
        if not failures:
            import terminal
            terminal.check(binary, root)
    assert not failures, f"{len(failures)} descendant signal cases failed"
    print("OK native signal contract: 8 descendant and 4 terminal cases", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dawnc", type=Path, required=True)
    args = parser.parse_args()
    check(args.dawnc.resolve())
