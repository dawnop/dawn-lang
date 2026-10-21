#!/usr/bin/env python3
"""Drive one of the io-primitives streaming programs and judge what it did.

    io_check.py ready  -- <cmd...>
    io_check.py append|slurp [--mb N] [--max-rss-mb M] [--min-rss-mb M] [--expect-fail] -- <cmd...>
    io_check.py range  [--mb N] [--max-rss-mb M] -- <cmd...>

`<cmd...>` is the program up to, and not including, its mode word: the driver
appends the mode and the path itself, so the JVM jar and the native binary are
driven by one script. Exit status 0 means every claim held; the first claim
that did not prints a line starting `FAIL` and exits 1.

ready    The program writes "ready\\n", flushes, and blocks on one byte of
         stdin. The driver requires "ready\\n" within 5 s while the program is
         still blocked (a flush that does not flush shows up as a timeout),
         then sends one byte and requires the program to end having delivered
         it, with no flush of its own (the end of the process delivers).
append   N MiB of a repeating random pattern go in on stdin; the program
         appends them to a file in 64 KiB blocks. The file must be N MiB with
         the same SHA-256 as what was sent, and the peak resident set size
         (wait4's ru_maxrss for that one child) must stay under --max-rss-mb,
         the figure that is a few blocks and not the file. `--min-rss-mb` is
         the other direction, for the control that reads the whole body first:
         its peak has to be at least that large, which is what shows the
         bound above can be exceeded and so means something. `--expect-fail`
         is for that control under a small JVM heap: the program must die.
range    The driver writes an N MiB file; the program streams it to stdout in
         64 KiB range reads; stdout must hash to the file, within the bound.
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time

BLOCK = 1 << 20


def fail(msg):
    print("FAIL " + msg)
    sys.exit(1)


def pattern():
    # one random MiB repeated: cheap to generate, and a block copied to the
    # wrong offset still changes the hash, because the pattern is not periodic
    # in any smaller unit
    return os.urandom(BLOCK)


def reap(p):
    pid, status, usage = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    return p.returncode, usage.ru_maxrss  # KiB on Linux


def run_ready(cmd):
    p = subprocess.Popen(cmd + ["ready"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    got = bytearray()
    done = threading.Event()

    def pump():
        while True:
            b = os.read(p.stdout.fileno(), 4096)
            if not b:
                break
            got.extend(b)
            if got.startswith(b"ready\n"):
                done.set()

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    if not done.wait(5.0):
        p.kill()
        reap(p)
        fail("ready: the flushed bytes did not reach the reader within 5 s (flush_stdout did not flush)")
    p.stdin.write(b"x")
    p.stdin.close()
    t.join(10.0)
    code, _ = reap(p)
    if code != 0:
        fail(f"ready: exit status {code}")
    if bytes(got) != b"ready\nx\n":
        fail(f"ready: stdout was {bytes(got)!r}, want b'ready\\nx\\n' (the end of the process has to deliver)")
    print("OK   ready: flushed bytes arrive while the program blocks, the unflushed tail at exit")


def run_append(cmd, word, mb, max_rss, min_rss, expect_fail):
    t0 = time.monotonic()
    d = tempfile.mkdtemp(prefix="io-append-")
    path = os.path.join(d, "out", "body.bin")
    p = subprocess.Popen(cmd + [word, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL if expect_fail else None)
    h = hashlib.sha256()
    blk = pattern()
    try:
        for _ in range(mb):
            p.stdin.write(blk)
            h.update(blk)
        p.stdin.close()
    except BrokenPipeError:
        pass
    out = p.stdout.read()
    code, rss_kib = reap(p)
    rss_mb = rss_kib / 1024.0
    if expect_fail:
        if code == 0:
            fail(f"append: expected the program to die under its memory limit, it exited 0 (rss {rss_mb:.0f} MiB)")
        print(f"OK   append control: died as expected (exit {code}, peak {rss_mb:.0f} MiB)")
        return
    if code != 0:
        fail(f"append: exit status {code}")
    if not os.path.exists(path):
        fail("append: no file was written")
    size = os.path.getsize(path)
    if size != mb * BLOCK or out.strip() != str(mb * BLOCK).encode():
        fail(f"append: file is {size} bytes, program said {out.strip()!r}, want {mb * BLOCK}")
    g = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(BLOCK)
            if not b:
                break
            g.update(b)
    if g.digest() != h.digest():
        fail("append: the file's SHA-256 differs from what was sent")
    os.remove(path)
    os.rmdir(os.path.dirname(path))
    os.rmdir(d)
    if max_rss is not None and rss_mb > max_rss:
        fail(f"append: peak resident set {rss_mb:.1f} MiB is over the {max_rss} MiB bound for a {mb} MiB body")
    if min_rss is not None and rss_mb < min_rss:
        fail(f"append: peak resident set {rss_mb:.1f} MiB is under {min_rss} MiB, so the control did not hold the body")
    print(f"OK   append: {mb} MiB landed byte for byte, peak resident set {rss_mb:.1f} MiB, {time.monotonic() - t0:.1f} s")


def run_range(cmd, mb, max_rss):
    t0 = time.monotonic()
    d = tempfile.mkdtemp(prefix="io-range-")
    path = os.path.join(d, "src.bin")
    h = hashlib.sha256()
    blk = pattern()
    with open(path, "wb") as f:
        for _ in range(mb):
            f.write(blk)
            h.update(blk)
    p = subprocess.Popen(cmd + ["range", path], stdout=subprocess.PIPE)
    g = hashlib.sha256()
    n = 0
    while True:
        b = p.stdout.read(1 << 16)
        if not b:
            break
        g.update(b)
        n += len(b)
    code, rss_kib = reap(p)
    rss_mb = rss_kib / 1024.0
    os.remove(path)
    os.rmdir(d)
    if code != 0:
        fail(f"range: exit status {code}")
    if n != mb * BLOCK:
        fail(f"range: {n} bytes came out, want {mb * BLOCK}")
    if g.digest() != h.digest():
        fail("range: the streamed bytes differ from the file")
    if max_rss is not None and rss_mb > max_rss:
        fail(f"range: peak resident set {rss_mb:.1f} MiB is over the {max_rss} MiB bound for a {mb} MiB file")
    print(f"OK   range: {mb} MiB streamed byte for byte, peak resident set {rss_mb:.1f} MiB, {time.monotonic() - t0:.1f} s")


def main():
    argv = sys.argv[1:]
    if "--" not in argv:
        raise SystemExit(__doc__)
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["ready", "append", "range", "slurp"])
    ap.add_argument("--mb", type=int, default=256)
    ap.add_argument("--max-rss-mb", type=float)
    ap.add_argument("--min-rss-mb", type=float)
    ap.add_argument("--expect-fail", action="store_true")
    a = ap.parse_args(argv[:i])
    cmd = argv[i + 1:]
    if a.mode == "ready":
        run_ready(cmd)
    elif a.mode in ("append", "slurp"):
        # slurp is the control: the program holds the whole body before it writes
        run_append(cmd, a.mode, a.mb, a.max_rss_mb, a.min_rss_mb, a.expect_fail)
    else:
        run_range(cmd, a.mb, a.max_rss_mb)


if __name__ == "__main__":
    main()
