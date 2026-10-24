#!/usr/bin/env python3
"""Observe source offsets and ownership, independently of wire normalization.

A source returns six bytes at a time from an immutable payload. Each server
must supply the exact accumulated offset and close once, including HEAD,
no-body status, short/long streams and failed reads. Both arms must meet the
oracle, so two equally broken servers cannot make the comparison green.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import time

from contract import F, exchange_jvm, normalize, req

PAYLOAD = b"alpha-beta-\x00\xff\nomega"
READS = ["read 0", "read 6", "read 12", "read 18", "read 19"]
CASES = {
    "offset-advances": ("GET", "/stream-sized", READS, PAYLOAD),
    "offset-starts-at-zero": ("GET", "/stream-sized", READS, PAYLOAD),
    "close-success": ("GET", "/stream-sized", READS, PAYLOAD),
    "offset-chunked": ("GET", "/stream-chunked", READS, PAYLOAD),
    "offset-file": ("GET", "/source-file", READS, PAYLOAD),
    "close-short": ("GET", "/stream-short", READS, None),
    "close-long": ("GET", "/stream-long", READS[:3], None),
    "close-read-failure": ("GET", "/source-failure", READS[:1], None),
    "head-never-reads": ("HEAD", "/stream-sized", [], b""),
    "head-file-never-reads": ("HEAD", "/source-file", [], b""),
    "status-never-reads": ("GET", "/stream-204", [], b""),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--java", required=True)
    ap.add_argument("--jvm", required=True)
    ap.add_argument("--native", required=True)
    ap.add_argument("--only")
    a = ap.parse_args()
    names = a.only.split(",") if a.only else list(CASES)
    if set(names) - CASES.keys():
        ap.error("unknown position fixture")
    failures = 0
    with tempfile.TemporaryDirectory(prefix="web-source-positions.") as tmp:
        trace = Path(tmp) / "jvm-trace"
        native_trace = Path(tmp) / "native-trace"
        env = dict(os.environ, TMPDIR=tmp, WEB_SOURCE_TRACE=str(trace))
        jvm = subprocess.Popen([a.java, "-XX:-UsePerfData", "-jar", a.jvm], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, env=env)
        try:
            port = int(jvm.stdout.readline())
            for name in names:
                method, target, reads, body = CASES[name]
                fixture = F(name, req(method, target), 200)
                for side in ("jvm", "native"):
                    observed = trace if side == "jvm" else native_trace
                    observed.unlink(missing_ok=True)
                    if side == "jvm":
                        raw = exchange_jvm(port, fixture)
                    else:
                        # exchange_native supplies TMPDIR; add the observation
                        # path only for this child, without changing our env.
                        p = subprocess.run([a.native], input=fixture.raw,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           env=dict(env, WEB_SOURCE_TRACE=str(native_trace)), timeout=20)
                        raw = p.stdout
                    # JDK sendResponseHeaders(-1) can close the socket before
                    # drop_body completes. Wait for the server-side event,
                    # with distinct files so an arm cannot see the other's close.
                    deadline = time.monotonic() + 2
                    while True:
                        events = observed.read_text().splitlines() if observed.exists() else []
                        if "close" in events or time.monotonic() >= deadline:
                            break
                        time.sleep(0.005)
                    expected = reads + ["close"]
                    got = normalize(raw)
                    ok = events == expected
                    if body is not None:
                        ok = ok and got.get("body") == body
                    else:
                        if "body" in got:
                            hs = dict(got["headers"])
                            if "content-length" in hs:
                                ok = ok and len(got["body"]) < int(hs["content-length"])
                            else:
                                ok = ok and got.get("terminated") is False
                        else:
                            ok = ok and got.get("raw") == b""
                    if not ok:
                        print(f"FAIL {name}: {side} events={events!r}, expected={expected!r}, body={got.get('body', b'')[:40]!r}")
                        failures += 1
                if not failures:
                    print(f"OK   {name}: both servers meet the offset and close oracle")
            leftovers = list(Path(tmp).glob("contract-source-*"))
            if leftovers:
                print(f"FAIL close-file: {len(leftovers)} source files leaked")
                failures += 1
        finally:
            jvm.kill()
            jvm.wait()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
