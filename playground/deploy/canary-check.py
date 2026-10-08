#!/usr/bin/env python3
"""The canary check for the native Playground runner (K4 of
docs/playground-native-runner-design.md). redeploy.sh runs it on the server
after both runners are installed; nginx is not pointed at the native one until
it passes.

    canary-check.py [--jvm-url http://127.0.0.1:8087] [--socket /run/dawn-play/http.sock]
                    [--health-requests 100] [--ratio 2.0]
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

2. The ruling's gate (agent-handoff/ruling-native-runner-20261008.md, item 5):
   with the real `Accept=yes` start-up cost included, p95 of the native
   `/health` is at most `--ratio` (2.0) times the p95 of the JVM `/health`,
   each over `--health-requests` requests on a new connection every time.

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


def gate_ok(native_p95, jvm_p95, ratio):
    return native_p95 <= ratio * jvm_p95


def timed_health(call, n):
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        code, _ = split(call("GET", "/health", None))
        out.append((time.perf_counter() - t0) * 1000)
        if code != "200":
            raise RuntimeError(f"/health answered {code}")
    return out


def self_test():
    assert p95(list(range(1, 101))) == 95
    assert p95([5]) == 5
    assert p95([3, 1, 2]) == 3
    assert gate_ok(2.0, 1.0, 2.0) and not gate_ok(2.01, 1.0, 2.0)
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
    ap.add_argument("--ratio", type=float, default=2.0)
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

    # Interleaved so a slow moment of the host hits both samples alike.
    n = a.health_requests
    jt, nt = [], []
    for _ in range(n):
        jt += timed_health(jvm, 1)
        nt += timed_health(nat, 1)
    jp, np_ = p95(jt), p95(nt)
    ok = gate_ok(np_, jp, a.ratio)
    print(f"/health over {n} new connections each: jvm p95 {jp:.2f} ms, native p95 {np_:.2f} ms "
          f"(limit {a.ratio:g} x = {a.ratio * jp:.2f} ms)")
    print(f"  {'ok  ' if ok else 'FAIL'} native /health p95 <= {a.ratio:g} x jvm /health p95")
    if not ok:
        bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
