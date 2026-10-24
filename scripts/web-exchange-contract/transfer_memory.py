#!/usr/bin/env python3
"""Stream a file upload back as a file source, hashing both directions.

Each arm runs in a fresh process for a small and a 256 MiB transfer. Python
feeds and hashes bounded pieces and hashes the response incrementally. Peak
RSS must stay below an absolute bound and may grow by at most 32 MiB between
sizes, so a whole-file buffer cannot pass even with a large JVM baseline.
"""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading

MIB = 1 << 20
BLOCK = bytes(range(256)) * 256


def transfer(java, jar, native, mb, chunked):
    with tempfile.TemporaryDirectory(prefix="web-source-transfer.") as tmp:
        env = dict(os.environ, TMPDIR=tmp)
        if jar:
            p = subprocess.Popen([java, "-XX:-UsePerfData", "-Xms32m", "-Xmx32m", "-XX:+AlwaysPreTouch",
                                  "-XX:TieredStopAtLevel=1", "-XX:+UseSerialGC",
                                  f"-Djava.io.tmpdir={tmp}", "-jar", jar],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
            port = int(p.stdout.readline())
            conn = socket.create_connection(("127.0.0.1", port), timeout=120)
            reader, writer = conn.makefile("rb"), conn.makefile("wb")
        else:
            p = subprocess.Popen([native], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, env=env)
            reader, writer = p.stdout, p.stdin
        errors = []
        sent = hashlib.sha256()

        def upload():
            try:
                framing = "Transfer-Encoding: chunked" if chunked else f"Content-Length: {mb * MIB}"
                writer.write(f"PUT /spill-back HTTP/1.1\r\nHost: contract\r\nConnection: close\r\n{framing}\r\n\r\n".encode())
                for index in range(mb * MIB // len(BLOCK)):
                    block = index.to_bytes(8, "little") + BLOCK[8:]
                    if chunked:
                        writer.write(f"{len(BLOCK):x}\r\n".encode())
                    writer.write(block)
                    sent.update(block)
                    if chunked:
                        writer.write(b"\r\n")
                if chunked:
                    writer.write(b"0\r\n\r\n")
                writer.flush()
            except Exception as e:
                errors.append(e)
            finally:
                writer.close()

        sender = threading.Thread(target=upload, daemon=True)
        sender.start()
        try:
            status = reader.readline()
            headers = {}
            while True:
                line = reader.readline()
                if line in (b"\r\n", b""):
                    break
                k, v = line.decode().split(":", 1)
                headers[k.lower()] = v.strip()
            digest, size = hashlib.sha256(), 0
            while True:
                piece = reader.read(65536)
                if not piece:
                    break
                size += len(piece)
                digest.update(piece)
            sender.join(timeout=120)
            if sender.is_alive() or errors:
                raise AssertionError(f"upload failed: {errors}")
            assert status.startswith(b"HTTP/1.1 200"), status
            assert int(headers["content-length"]) == size == mb * MIB, (headers, size)
            assert digest.digest() == sent.digest(), "upload/download SHA-256 mismatch"
            if jar:
                rss = next(int(line.split()[1]) for line in Path(f"/proc/{p.pid}/status").read_text().splitlines() if line.startswith("VmHWM:")) / 1024
            else:
                _, status, usage = os.wait4(p.pid, 0)
                p.returncode = os.waitstatus_to_exitcode(status)
                assert p.returncode == 0, p.returncode
                rss = usage.ru_maxrss / 1024
            # The owned response file and original spill must both be gone.
            assert not list(Path(tmp).iterdir()), "temporary body/source file leaked"
            side = "jvm" if jar else "native"
            kind = "chunked" if chunked else "counted"
            print(f"OK   {side} {kind}: {mb} MiB uploaded and downloaded, sha256={digest.hexdigest()}, peak_rss_mib={rss:.1f}", flush=True)
            return rss
        finally:
            reader.close()
            if jar:
                conn.close()
            if p.poll() is None:
                p.kill()
            p.wait()
            sender.join(timeout=5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--java", required=True)
    ap.add_argument("--jvm", required=True)
    ap.add_argument("--native", required=True)
    ap.add_argument("--mb", type=int, default=256)
    a = ap.parse_args()
    for jar, native, bound in ((a.jvm, None, 160), (None, a.native, 32)):
        # Counted small, chunked large also proves both request framings reach
        # the same file source without changing the response's declared size.
        small = transfer(a.java, jar, native, 4, False)
        large = transfer(a.java, jar, native, a.mb, True)
        assert max(small, large) < bound, (small, large, bound)
        assert large - small < 32, (small, large)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
