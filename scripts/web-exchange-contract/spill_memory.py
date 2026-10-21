#!/usr/bin/env python3
"""The resident set of a streamed upload through web/exchange on stdin and stdout.

    spill_memory.py <native binary> [--mb N] [--max-rss-mb M] [--min-rss-mb M]
                    [--route /spill-size] [--chunked]

Sends one PUT of N MiB (default 256) to the process and reads its answer to the
end. `--route /spill-size` is the "stream-body" route: the body is appended to a
temp file in pieces, and the answer says how many bytes landed, which must be
the N MiB. `--route /hold-size` is the control, a "raw-body" route that holds
the body in memory: its peak resident set has to be at least `--min-rss-mb`,
which is what shows the bound on the first can be broken.

The peak is wait4's ru_maxrss for this one child. `--chunked` sends the body as
1 MiB chunks of Transfer-Encoding: chunked, the way a proxy with request
buffering off forwards a PUT of unknown length.
"""

import argparse
import os
import subprocess
import sys

MIB = 1 << 20


def fail(msg):
    print("FAIL " + msg)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("binary")
    ap.add_argument("--mb", type=int, default=256)
    ap.add_argument("--route", default="/spill-size")
    ap.add_argument("--chunked", action="store_true")
    ap.add_argument("--max-rss-mb", type=float)
    ap.add_argument("--min-rss-mb", type=float)
    a = ap.parse_args()

    block = os.urandom(MIB)
    if a.chunked:
        head = (f"PUT {a.route} HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n").encode()
    else:
        head = (f"PUT {a.route} HTTP/1.1\r\nHost: x\r\nContent-Length: {a.mb * MIB}\r\n\r\n").encode()
    p = subprocess.Popen([a.binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        p.stdin.write(head)
        for _ in range(a.mb):
            if a.chunked:
                p.stdin.write(b"%x\r\n" % MIB + block + b"\r\n")
            else:
                p.stdin.write(block)
        if a.chunked:
            p.stdin.write(b"0\r\n\r\n")
        p.stdin.close()
    except BrokenPipeError:
        pass
    out = p.stdout.read()
    pid, status, usage = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    rss = usage.ru_maxrss / 1024.0
    if p.returncode != 0:
        fail(f"exit status {p.returncode}")
    if not out.startswith(b"HTTP/1.1 200"):
        fail(f"answer was {out[:80]!r}")
    want = f"{a.mb * MIB} bytes".encode()
    if want not in out:
        fail(f"answer does not say {want!r}: {out[-80:]!r}")
    kind = "chunked" if a.chunked else "counted"
    if a.max_rss_mb is not None and rss > a.max_rss_mb:
        fail(f"{a.route} {kind}: peak resident set {rss:.1f} MiB is over the {a.max_rss_mb} MiB bound for {a.mb} MiB")
    if a.min_rss_mb is not None and rss < a.min_rss_mb:
        fail(f"{a.route} {kind}: peak resident set {rss:.1f} MiB is under {a.min_rss_mb} MiB, so the control did not hold the body")
    print(f"OK   {a.route} {kind}: {a.mb} MiB through the exchange, peak resident set {rss:.1f} MiB")


if __name__ == "__main__":
    main()
