#!/usr/bin/env python3

from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "background.pid"
READY_FILE = ROOT / "background.ready"


def child() -> int:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    READY_FILE.write_text("ready\n", encoding="ascii")
    time.sleep(600)
    return 0


def launcher() -> int:
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    PID_FILE.write_text(f"{process.pid}\n", encoding="ascii")
    deadline = time.monotonic() + 5
    while not READY_FILE.exists():
        if time.monotonic() >= deadline:
            print("background child did not start", file=sys.stderr)
            return 97
        time.sleep(0.01)
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(child() if sys.argv[1:] == ["--child"] else launcher())
