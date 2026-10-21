#!/usr/bin/env python3
"""The wire contract of the web package's two servers.

web_jvm/server (jdk.httpserver) and web/exchange (the single-exchange adapter
the native backend builds) serve the same application, scripts/web-exchange-
contract/app, and every fixture below is one raw HTTP request sent to both. What
comes back is compared byte for byte after the differences that are the JDK's
own are removed, and those are the whole list below (NORMALIZED). Each fixture
also carries the status both must answer: two servers can agree on a wrong
answer, and the status is what says it is the right one.

    contract.py --jvm <contract_jvm.jar> --native <contract_native binary>
                [--java <java>] [--only <name,...>] [--list]

The JVM server is started once and answers every fixture on its port; the native
binary is started once per fixture, with the request on stdin and the response
read from stdout, which is how it runs in production.

Exit status 0 when every fixture agrees, 1 otherwise. `--mutate` is not here:
the negative controls are in run.sh, which builds a broken copy of web/exchange
and requires this script to go red on it.
"""
import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time

# ---------------------------------------------------------------------------
# The differences that are not differences. Anything not on this list is a
# byte that must match.
#
#   Date            jdk.httpserver always adds one; the native adapter does not
#                   (the proxy in front supplies it), so it is dropped on both.
#   Connection      the JDK sends it only when asked to close; the adapter sends
#                   `Connection: close` on every response. Dropped on both; the
#                   fixtures all ask for close, and the adapter's is checked
#                   separately below (every native response must carry it).
#   header names    the JDK writes `Content-type`; the adapter writes
#                   `Content-Type`. Names are lowercased on both.
#   header order    the JDK's header map has its own order. Header lines are
#                   compared as a sorted list.
#   chunk bounds    a chunked body is compared decoded; where the chunk
#                   boundaries fall is the transport's, not the application's.
#                   Whether the terminating chunk arrived is compared.
# ---------------------------------------------------------------------------
NORMALIZED = ["date", "connection"]

CRLF = b"\r\n"


def req(method, target, headers=(), body=b"", close=True, version="HTTP/1.1"):
    lines = [f"{method} {target} {version}", "Host: contract"]
    lines += [f"{k}: {v}" for k, v in headers]
    if close:
        lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


def chunked(*pieces, ext="", trailer=b""):
    out = b""
    for p in pieces:
        out += (format(len(p), "x") + ext).encode() + CRLF + p + CRLF
    return out + b"0" + CRLF + trailer + CRLF


def post(target, body, extra=(), method="POST"):
    return req(method, target, [("Content-Length", str(len(body)))] + list(extra), body)


def post_chunked(target, body_bytes, extra=(), method="POST"):
    return req(method, target, [("Transfer-Encoding", "chunked")] + list(extra), body_bytes)


class F:
    """One fixture. `status` is what the adapter must answer. `jvm` is what the
    JDK server answers when that is a different status (a KNOWN_DIFFERENCES
    entry, named in the design doc: the JDK refuses what the RFC allows, or the
    other way round); such a fixture checks both statuses and compares nothing
    else. `compare`: "full" is byte equality after normalization, "status"
    checks the status only (the JDK answers before any Dawn runs, with a body of
    its own), "short" is for a response that fails after its head is out: the
    adapter delivers the head and the part of the body that was sent, the JDK
    drops what it had not flushed, so the check is that neither delivers its
    full promised length."""

    def __init__(self, name, raw, status, half_close=False, compare="full", note="", jvm=None):
        self.name, self.raw, self.status = name, raw, status
        self.half_close, self.compare, self.note, self.jvm = half_close, compare, note, jvm


BIN = bytes([0, 255, 10, 13, 128])
X64 = b"x" * 64
X65 = b"x" * 65

FIXTURES = [
    # framing and the verbs
    F("get-hello", req("GET", "/hello"), 200),
    F("get-empty-body", req("GET", "/empty"), 200),
    F("get-204-no-body", req("GET", "/nocontent"), 204),
    F("head-hello", req("HEAD", "/hello"), 200),
    F("head-empty", req("HEAD", "/empty"), 200),
    F("head-204", req("HEAD", "/nocontent"), 204),
    F("head-404", req("HEAD", "/nope"), 404),
    F("head-stream-sized", req("HEAD", "/stream-sized"), 200),
    F("head-stream-chunked", req("HEAD", "/stream-chunked"), 200),
    F("not-found", req("GET", "/nope"), 404),
    F("wrong-method", req("POST", "/hello", [("Content-Length", "0")]), 405),
    F("handler-panic", req("GET", "/boom"), 500),
    # what a path and a query mean
    F("query-multimap", req("GET", "/q?a=1&a=2%263&b=&c=%E4%B8%AD&a=x+y", [("X-Multi", "one"), ("X-Multi", "two")]), 200),
    F("query-none", req("GET", "/q"), 200),
    F("path-encoded-slash", req("GET", "/u/a%2Fb"), 200),
    F("path-utf8", req("GET", "/u/caf%C3%A9"), 200),
    F("path-plus-literal", req("GET", "/u/a+b"), 200),
    F("path-bad-escape", req("GET", "/u/%zz"), 400, compare="status"),
    F("path-truncated-escape", req("GET", "/u/ab%4"), 400, compare="status"),
    F("path-signed-escape", req("GET", "/u/%+1"), 400, compare="status"),
    F("path-illegal-char", req("GET", "/u/a|b"), 400, compare="status"),
    F("path-illegal-bracket", req("GET", "/u/a[b"), 400, compare="status"),
    F("query-bad-escape", req("GET", "/q?a=%zz"), 400, compare="status"),
    F("query-illegal-char", req("GET", "/q?a=b|c"), 400, compare="status"),
    F("path-tail-capture", req("GET", "/files/x/y%20z/w"), 200),
    F("path-interior-empty", req("GET", "/files/a//b"), 200),
    # dot segments are refused on every route, through the middleware
    F("dot-segment-plain", req("GET", "/a/../b"), 400),
    F("dot-segment-single", req("GET", "/u/./x"), 400),
    F("dot-segment-encoded", req("GET", "/%2e%2e/x"), 400),
    F("dot-segment-on-a-route", req("GET", "/files/%2E%2e/x"), 400),
    F("dot-segment-with-body", post("/echo", b"hello", [], method="POST").replace(b"POST /echo", b"POST /a/../echo"), 400),
    # request bodies
    F("body-content-length", post("/echo", b"hello"), 200),
    F("body-binary", post("/echo", BIN), 200),
    F("body-empty", post("/echo", b""), 200),
    F("body-absent", req("POST", "/echo"), 200),
    F("body-exact-ceiling", post("/echo", X64), 200),
    F("body-over-ceiling", post("/echo", X65), 413),
    F("body-over-ceiling-declared-only", req("POST", "/echo", [("Content-Length", "1000000")]), 413, half_close=True,
      note="declared length over the ceiling is refused before a byte is read"),
    F("body-route-ceiling-ok", post("/small", b"x" * 16), 200),
    F("body-route-ceiling-over", post("/small", b"x" * 17), 413),
    # chunked request bodies
    F("chunked-two-chunks", post_chunked("/echo", chunked(b"hello ", b"world")), 200),
    F("chunked-binary", post_chunked("/echo", chunked(BIN, BIN)), 200),
    F("chunked-empty", post_chunked("/echo", chunked()), 200),
    F("chunked-extension", post_chunked("/echo", chunked(b"abc", ext=";name=value")), 200),
    F("chunked-trailer", post_chunked("/echo", chunked(b"abc", trailer=b"X-T: 1\r\n")), 200, jvm=400,
      note="RFC 9112 7.1.2 allows a trailer section; the JDK's chunked stream fails on one"),
    F("chunked-upper-hex", post_chunked("/echo", chunked(b"x" * 26)), 200),
    F("chunked-exact-ceiling", post_chunked("/echo", chunked(X64)), 200),
    F("chunked-over-ceiling", post_chunked("/echo", chunked(X65)), 413),
    F("chunked-over-ceiling-split", post_chunked("/echo", chunked(b"x" * 40, b"x" * 40)), 413),
    F("chunked-route-ceiling-over", post_chunked("/small", chunked(b"x" * 10, b"x" * 10)), 413),
    # malformed chunked: the JDK's own answers are compared by status only,
    # since it fails inside a read and the adapter refuses before any handler
    F("chunked-bad-size", post_chunked("/echo", b"zz\r\nhello\r\n0\r\n\r\n"), 400, compare="status"),
    F("chunked-empty-size", post_chunked("/echo", b"\r\nhello\r\n0\r\n\r\n"), 400, compare="status"),
    F("chunked-missing-data-crlf", post_chunked("/echo", b"5\r\nhelloXX0\r\n\r\n"), 400, compare="status"),
    F("chunked-cut-short", post_chunked("/echo", b"a\r\nabc"), 400, half_close=True, compare="status"),
    F("chunked-no-terminator", post_chunked("/echo", b"5\r\nhello\r\n"), 400, half_close=True, compare="status"),
    F("chunked-bare-lf", post_chunked("/echo", b"5\nhello\r\n0\r\n\r\n"), 400, compare="status"),
    F("chunked-size-overflow", post_chunked("/echo", b"fffffffffffffffff\r\nx\r\n0\r\n\r\n"), 400, compare="status"),
    F("body-short-of-length", req("POST", "/echo", [("Content-Length", "10")], b"abc"), 400, half_close=True, compare="status"),
    # guards run before the body, and refusals go through the middleware
    F("guard-refuses", post("/guarded", b"hello"), 401),
    F("guard-refuses-without-reading", req("POST", "/guarded", [("Content-Length", "1000000")]), 401, half_close=True),
    F("guard-passes", post("/guarded", b"hello", [("X-Token", "ok")]), 200),
    F("guard-passes-chunked", post_chunked("/guarded", chunked(b"hello", b"!"), [("X-Token", "ok")]), 200),
    F("guard-passes-then-ceiling", post("/guarded", X65, [("X-Token", "ok")]), 413),
    # stream-body routes
    F("spill-content-length", post("/spill", b"0123456789", method="PUT"), 200),
    F("spill-chunked", post_chunked("/spill", chunked(b"01234", b"56789"), method="PUT"), 200),
    F("spill-empty", post("/spill", b"", method="PUT"), 200),
    F("spill-over-route-ceiling", post("/spill-small", b"x" * 17, method="PUT"), 413),
    F("spill-chunked-over-route-ceiling", post_chunked("/spill-small", chunked(b"x" * 9, b"x" * 9), method="PUT"), 413),
    F("spill-no-server-ceiling", post("/spill", X65, method="PUT"), 200),
    # streaming response bodies
    F("stream-chunked", req("GET", "/stream-chunked"), 200),
    F("stream-sized", req("GET", "/stream-sized"), 200),
    F("stream-short-of-its-length", req("GET", "/stream-short"), 200, compare="short"),
    F("stream-past-its-length", req("GET", "/stream-long"), 200, compare="short"),
    F("stream-on-a-no-body-status", req("GET", "/stream-204"), 204),
    # what the JDK answers before any Dawn runs: status only
    F("head-garbage-request-line", b"BLAH\r\n\r\n", 400, compare="status"),
    F("head-http-2", req("GET", "/hello", version="HTTP/2.0"), 505, jvm=200,
      note="the JDK serves any version token as 1.1; the adapter refuses what it cannot speak"),
    F("head-absolute-form", req("GET", "http://contract/hello"), 400, jvm=200,
      note="the adapter takes origin-form only; the proxy in front never sends absolute-form"),
    F("head-te-gzip", post_chunked("/echo", b"5\r\nhello\r\n0\r\n\r\n", [("Transfer-Encoding", "gzip")]), 501, compare="status"),
]


# ---------------------------------------------------------------------------


def exchange_jvm(port, f, timeout=10):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(f.raw)
        if f.half_close:
            s.shutdown(socket.SHUT_WR)
        out = b""
        while True:
            try:
                d = s.recv(65536)
            except (socket.timeout, ConnectionResetError):
                break
            if not d:
                break
            out += d
        return out
    finally:
        s.close()


def exchange_native(binary, f, tmp, timeout=20):
    env = dict(os.environ, TMPDIR=tmp)
    p = subprocess.run([binary], input=f.raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
    return p.stdout, p.stderr


def split_head(raw):
    i = raw.find(b"\r\n\r\n")
    if i < 0:
        return raw, b"", False
    return raw[:i], raw[i + 4:], True


def decode_chunked(body):
    """Decode as far as the bytes go: (data, terminated)."""
    out, pos = b"", 0
    while True:
        j = body.find(CRLF, pos)
        if j < 0:
            return out, False
        try:
            n = int(body[pos:j].split(b";")[0], 16)
        except ValueError:
            return out, False
        pos = j + 2
        if n == 0:
            return out, True
        if pos + n > len(body):
            return out + body[pos:], False
        out += body[pos:pos + n]
        pos += n + 2


def normalize(raw):
    head, body, complete = split_head(raw)
    if not complete:
        return {"raw": raw}
    lines = head.split(CRLF)
    status = lines[0].decode("latin-1")
    hs = []
    for l in lines[1:]:
        k, _, v = l.decode("latin-1").partition(":")
        k = k.strip().lower()
        if k in NORMALIZED:
            continue
        hs.append((k, v.strip()))
    hs.sort()
    terminated = None
    if ("transfer-encoding", "chunked") in hs:
        body, terminated = decode_chunked(body)
    return {"status": status, "headers": hs, "body": body, "terminated": terminated}


def status_of(raw):
    return raw.split(CRLF, 1)[0].decode("latin-1")


def show(n):
    if "raw" in n:
        return repr(n["raw"][:300])
    return f"{n['status']} {n['headers']} body={n['body'][:200]!r} terminated={n['terminated']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jvm")
    ap.add_argument("--native")
    ap.add_argument("--java", default="java")
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.list:
        for f in FIXTURES:
            print(f.name)
        return 0
    fixtures = FIXTURES
    if a.only:
        want = set(a.only.split(","))
        fixtures = [f for f in FIXTURES if f.name in want]
    tmp = tempfile.mkdtemp(prefix="web-exchange-contract.")
    jvm = subprocess.Popen([a.java, "-jar", a.jvm], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=dict(os.environ, TMPDIR=tmp))
    try:
        port = int(jvm.stdout.readline().decode().strip())
        failures, agreed, exact = [], 0, 0
        for f in fixtures:
            j_raw = exchange_jvm(port, f)
            n_raw, n_err = exchange_native(a.native, f, tmp)
            jn, nn = normalize(j_raw), normalize(n_raw)
            ok = True
            why = []
            for side, raw, want in (("jvm", j_raw, f.jvm or f.status), ("native", n_raw, f.status)):
                if status_of(raw) != f"HTTP/1.1 {want}" and not status_of(raw).startswith(f"HTTP/1.1 {want} "):
                    if not (f.compare == "short" and side == "jvm" and raw == b""):
                        ok = False
                        why.append(f"{side} status {status_of(raw)!r}, wanted {want}")
            if b"\r\nConnection: close\r\n" not in n_raw and f.compare == "full":
                ok = False
                why.append("native response has no Connection: close")
            if f.compare == "short":
                for side, n in (("jvm", jn), ("native", nn)):
                    if "raw" in n:
                        if n["raw"] != b"":
                            ok = False
                            why.append(f"{side} sent a partial head")
                        continue
                    declared = dict(n["headers"]).get("content-length")
                    if declared is None or len(n["body"]) >= int(declared):
                        ok = False
                        why.append(f"{side} delivered its whole promised length")
            if f.compare == "full" and f.jvm is None and jn != nn:
                ok = False
                why.append("responses differ")
            if ok:
                agreed += 1
                if j_raw == n_raw:
                    exact += 1
                if a.verbose:
                    print(f"ok   {f.name}")
            else:
                failures.append(f.name)
                print(f"FAIL {f.name}: {'; '.join(why)}")
                print(f"     jvm    : {show(jn)}")
                print(f"     native : {show(nn)}")
                if n_err:
                    print(f"     native stderr: {n_err.decode('utf-8', 'replace')[:300]!r}")
        print(f"{agreed}/{len(fixtures)} fixtures agree ({exact} of them to the raw byte, the rest after the normalized differences: {', '.join(NORMALIZED)}, header-name case, header order, chunk boundaries)")
        return 1 if failures else 0
    finally:
        jvm.kill()
        jvm.wait()
        for n in os.listdir(tmp):
            try:
                os.unlink(os.path.join(tmp, n))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
