#!/usr/bin/env python3
"""Exercise the kernel allowance through real execs and inherited children.

These checks keep the resource stopper distinct from scheduler waits, and
hold exit status, byte streams and stricter caller limits across the wrapper.
"""

import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time

LIMIT = Path(__file__).with_name('cpu-limit.py')


def command(code, seconds=1):
    return [sys.executable, str(LIMIT), str(seconds), '--', sys.executable, '-c', code]


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    result = subprocess.run(command(
        'import sys; sys.stdout.buffer.write(b"out\\x00"); '
        'sys.stderr.buffer.write(b"err\\x00"); sys.exit(7)'), capture_output=True)
    assert (result.returncode, result.stdout, result.stderr) == (7, b'out\0', b'err\0')

    proc = subprocess.Popen(command(
        'import os, signal; print("ready", flush=True); '
        'os.kill(os.getpid(), signal.SIGSTOP); print("resumed")'),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert proc.stdout.readline() == b'ready\n'
        _, status = os.waitpid(proc.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(status)
        time.sleep(1.1)
        os.kill(proc.pid, signal.SIGCONT)
        stdout, stderr = proc.communicate()
        assert (proc.returncode, stdout, stderr) == (0, b'resumed\n', b'')
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    spin = subprocess.run(command('while True: pass'), capture_output=True)
    assert spin.returncode in (-signal.SIGXCPU, -signal.SIGKILL), spin
    hard = subprocess.run(command(
        'import signal; signal.signal(signal.SIGXCPU, signal.SIG_IGN)\nwhile True: pass'),
        capture_output=True)
    assert hard.returncode == -signal.SIGKILL, hard

    child = subprocess.run(command(
        'import subprocess, sys; '
        'p=subprocess.run([sys.executable,"-c","while True: pass"]); '
        'print(p.returncode)'), capture_output=True)
    assert child.returncode == 0 and int(child.stdout) in (
        -signal.SIGXCPU, -signal.SIGKILL), child
    strict = subprocess.run(command(
        'import subprocess, sys; '
        f'p=subprocess.run([sys.executable,{str(LIMIT)!r},"5","--",sys.executable,"-c",'
        '"import resource; print(resource.getrlimit(resource.RLIMIT_CPU))"]); '
        'sys.exit(p.returncode)'), capture_output=True)
    assert strict.returncode == 0 and strict.stdout == b'(1, 2)\n', strict
    print('OK: CPU allowance preserves bytes/status, excludes suspension, '
          'stops spins and descendants, and retains stricter limits')


if __name__ == '__main__':
    main()
