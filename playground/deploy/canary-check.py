#!/usr/bin/env python3
"""The canary check for the native Playground runner (K4 of
docs/playground-native-runner-design.md). redeploy.sh runs it on the server
after both runners are installed; nginx is not pointed at the native one until
it passes.

    canary-check.py [--jvm-url http://127.0.0.1:8087] [--socket /run/dawn-play/http.sock]
                    [--health-requests 100] [--slow-requests 20]
    canary-check.py --self-test

Two checks, both against the live units:

1. Byte compare. The same requests go to the JVM runner (TCP) and to the native
   one (unix socket, a fresh `dawn-play-native@` instance per connection), and
   the status code and the body must be identical. Only the two fields that
   differ by design are normalized: `ms`, a timing, and `cached`, which the
   native runner (no cache, ruling 4) always reports false. The reason phrase
   and the headers are the framework's own and are not compared, as in
   playground/test/serve-compare.py, whose cases these are a subset of: the
   ones that are quick and safe to send to a production sandbox (no program
   that runs until its timeout, no 20000-line output).

2. The latency gate, with the real `Accept=yes` start-up cost included, every
   request on a new connection, the two runners interleaved:
   - `/run` hello and `/check` hello, `--slow-requests` (20) each, spaced out so
     the production sandbox is not loaded: native p95 must be at most
     SLOW_RATIO (1.15) x the JVM p95 + SLOW_SLACK_MS (100) ms.
   - `/health`, `--health-requests` (100): native p95 at most HEALTH_CEILING_MS
     (25) ms. An absolute ceiling, not a ratio.
   Why these numbers: measured on the production host, native `/health` is
   7.7 to 7.9 ms against 1.4 to 1.6 ms for the JVM runner (5x), and ~90% of
   that is systemd starting a service instance per connection, a fixed cost.
   Users never see a `/health`; they see `/run` (~3.0 s) and `/check`
   (~1.2 s), where the same cost is 0.2% to 0.5% and the measured native/JVM
   p95 ratios are 0.98 to 1.06 with about 100 ms of noise at 20 samples. So
   the ratio gate sits on the endpoints users hit, and `/health` only guards
   against a start-up regression to whole seconds (25 ms is 3x today's value).

Exit status 0 only when both hold. Standard library only, because it runs on the
server under `python3 -I`; it needs to be able to open the unix socket, so run
it as a user the socket admits (redeploy.sh uses the dawn-play user).
"""
import argparse, json, re, socket, sys, time
from urllib.parse import urlsplit

HELLO = 'pub fn main() -> Unit !io = println("hello")\n'


def j(code, **kw):
    d = {"code": code}
    d.update(kw)
    return json.dumps(d).encode()


CASES = [
    ("health", "GET", "/health", None),
    ("run ok", "POST", "/run", j(HELLO)),
    ("run compile error", "POST", "/run", j("pub fn main() -> Unit !io = nope\n")),
    ("run exit status", "POST", "/run", j('pub fn main() -> Unit !io = { println("x")\n panic("boom") }\n')),
    ("check ok", "POST", "/check", j(HELLO)),
    ("check error", "POST", "/check", j("pub fn main() -> Unit !io = nope\n")),
    ("compile c", "POST", "/compile", j(HELLO, target="c")),
    ("compile jvm", "POST", "/compile", j(HELLO, target="jvm")),
    ("bad json", "POST", "/run", b"{nope"),
    ("bad utf8", "POST", "/run", b'{"code":"\xff\xfe"}'),
    ("oversize", "POST", "/run", j("x" * 70000)),
    ("empty body", "POST", "/run", b""),
    ("404", "GET", "/nope", None),
    ("405", "GET", "/run", None),
]


def request_bytes(method, path, body):
    head = f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n"
    if body is not None:
        head += f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n"
    return head.encode() + b"\r\n" + (body or b"")


def exchange(sock, data):
    sock.sendall(data)
    chunks = []
    while True:
        c = sock.recv(65536)
        if not c:
            break
        chunks.append(c)
    return b"".join(chunks)


def over_tcp(url):
    u = urlsplit(url)
    host, port = u.hostname, u.port or 80

    def go(method, path, body):
        s = socket.create_connection((host, port), timeout=60)
        try:
            return exchange(s, request_bytes(method, path, body))
        finally:
            s.close()
    return go


def over_unix(path):
    def go(method, path_, body):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(60)
        s.connect(path)
        try:
            return exchange(s, request_bytes(method, path_, body))
        finally:
            s.close()
    return go


def split(resp):
    head, _, body = resp.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode("latin-1")
    parts = status.split(" ")
    code = parts[1] if len(parts) > 1 else ""
    return code, body


def normalize(body):
    t = body.decode("utf-8", "replace")
    t = re.sub(r'"ms":\d+', '"ms":0', t)
    t = re.sub(r'"cached":(true|false),?', "", t)
    return t


def p95(samples):
    s = sorted(samples)
    return s[max(0, int(len(s) * 0.95 + 0.999999) - 1)]


# Thresholds. See the header for the measurements behind them.
SLOW_RATIO = 1.15        # native p95 vs JVM p95 on /run and /check
SLOW_SLACK_MS = 100.0    # absolute allowance on top: p95 of 20 samples is noisy
HEALTH_CEILING_MS = 25.0  # native /health p95, absolute (3x the measured 7.9 ms)
SLOW_REQUESTS = 20
SLOW_SPACING_S = 1.0     # pause between request pairs on the slow endpoints


def gate_ok(native_p95, jvm_p95, ratio=SLOW_RATIO, slack_ms=SLOW_SLACK_MS):
    return native_p95 <= ratio * jvm_p95 + slack_ms


def ceiling_ok(native_p95, ceiling_ms=HEALTH_CEILING_MS):
    return native_p95 <= ceiling_ms


def timed(call, method, path, body):
    t0 = time.perf_counter()
    code, _ = split(call(method, path, body))
    ms = (time.perf_counter() - t0) * 1000
    if code != "200":
        raise RuntimeError(f"{path} answered {code}")
    return ms


def sample(jvm, nat, method, path, body, n, spacing_s):
    """n interleaved timings per runner, so a slow moment of the host hits both."""
    jt, nt = [], []
    for i in range(n):
        jt.append(timed(jvm, method, path, body))
        nt.append(timed(nat, method, path, body))
        if spacing_s and i + 1 < n:
            time.sleep(spacing_s)
    return jt, nt


def self_test():
    assert p95(list(range(1, 101))) == 95
    assert p95([5]) == 5
    assert p95([3, 1, 2]) == 3
    # ratio gate: limit = 1.15 x jvm + 100 ms
    assert gate_ok(3194, 3257) and gate_ok(1349, 1267)  # measured: both pass
    assert gate_ok(1.15 * 1000 + 100, 1000) and not gate_ok(1.15 * 1000 + 100.5, 1000)
    assert gate_ok(100, 0) and not gate_ok(100.1, 0)
    assert not gate_ok(2000, 1267)  # a real regression fails
    assert gate_ok(2.0, 1.0, 2.0, 0.0) and not gate_ok(2.01, 1.0, 2.0, 0.0)
    # absolute ceiling: 25 ms
    assert ceiling_ok(7.9) and ceiling_ok(25.0) and not ceiling_ok(25.01)
    a = b'{"ok":true,"ms":12,"cached":true,"x":1}'
    b = b'{"ok":true,"ms":9,"cached":false,"x":1}'
    assert normalize(a) == normalize(b)
    assert normalize(b'{"ok":true,"ms":1,"x":1}') != normalize(b'{"ok":true,"ms":1,"x":2}')
    assert split(b"HTTP/1.1 429 Too Many Requests\r\nA: b\r\n\r\nbody") == ("429", b"body")
    assert split(b"") == ("", b"")
    print("canary-check self-test ok")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jvm-url", default="http://127.0.0.1:8087")
    ap.add_argument("--socket", default="/run/dawn-play/http.sock")
    ap.add_argument("--health-requests", type=int, default=100)
    ap.add_argument("--slow-requests", type=int, default=SLOW_REQUESTS)
    ap.add_argument("--slow-spacing", type=float, default=SLOW_SPACING_S)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    jvm, nat = over_tcp(a.jvm_url), over_unix(a.socket)
    bad = 0
    for name, m, p, b in CASES:
        c1, b1 = split(jvm(m, p, b))
        c2, b2 = split(nat(m, p, b))
        same = c1 != "" and c1 == c2 and normalize(b1) == normalize(b2)
        print(f"  {'ok  ' if same else 'FAIL'} {name}: jvm {c1} / native {c2}")
        if not same:
            bad += 1
            print("    jvm   :", normalize(b1)[:300])
            print("    native:", normalize(b2)[:300])
    print(f"{len(CASES) - bad} of {len(CASES)} responses identical")

    n = a.health_requests
    jt, nt = sample(jvm, nat, "GET", "/health", None, n, 0)
    jp, np_ = p95(jt), p95(nt)
    ok = ceiling_ok(np_)
    print(f"/health over {n} new connections each: jvm p95 {jp:.2f} ms, native p95 {np_:.2f} ms "
          f"(ceiling {HEALTH_CEILING_MS:g} ms)")
    print(f"  {'ok  ' if ok else 'FAIL'} native /health p95 <= {HEALTH_CEILING_MS:g} ms")
    if not ok:
        bad += 1

    n = a.slow_requests
    for name, path in (("/run hello", "/run"), ("/check hello", "/check")):
        jt, nt = sample(jvm, nat, "POST", path, j(HELLO), n, a.slow_spacing)
        jp, np_ = p95(jt), p95(nt)
        limit = SLOW_RATIO * jp + SLOW_SLACK_MS
        ok = gate_ok(np_, jp)
        print(f"{name} over {n} new connections each: jvm p95 {jp:.0f} ms, native p95 {np_:.0f} ms "
              f"(limit {SLOW_RATIO:g} x jvm + {SLOW_SLACK_MS:g} = {limit:.0f} ms)")
        print(f"  {'ok  ' if ok else 'FAIL'} native {path} p95 within the limit")
        if not ok:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
