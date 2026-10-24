#!/usr/bin/env python3
"""Answers of two runner binaries compared byte for byte, and the flock gate's
behavior under load (docs/playground-native-runner-design.md).

    serve-compare.py <dawn-play binary> --previous <dawn-play binary> [--gate] [--bench]

Each binary runs behind test/inetd.py (what `systemd-socket-activate -a
--inetd` does) on a unix socket of its own, so every request is a fresh process exactly as in production. Both
run unsandboxed (PLAY_UNSAFE_LOCAL=1) against the same toolchain and work root
layout. It is the local, longer form of the deploy's canary
(deploy/canary-check.py): it adds the cases that are not safe to send to a
production sandbox (a program that runs until its timeout, 20000 lines of
output, the Tile IR view), the gate's concurrency cases and a latency table.

Until K5 the reference was the long-lived JVM runner (`dawn run playground`);
it is gone, and the reference is now the binary a change is measured against,
typically one built from the commit before it:
`git worktree add /tmp/base <base>` and `dawnc build /tmp/base/playground`.

Only `ms`, a timing, is normalized before comparing. Everything else, status
line included, must be identical.

Environment: JAVA_HOME (as bin/dawn needs), PLAY_TEST_DAWNC (the native dawnc
of this release).
"""
import json, os, re, signal, socket, statistics, subprocess, sys, tempfile, threading, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def http_bytes(method, path, body):
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


def unix(sockpath):
    def go(method, path, body):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(120)
        s.connect(sockpath if "/" in sockpath else "\0" + sockpath)
        try:
            return exchange(s, http_bytes(method, path, body))
        finally:
            s.close()
    return go


def split(resp):
    head, _, body = resp.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode()
    return status, head, body


def norm(body):
    t = body.decode("utf-8", "replace")
    return re.sub(r'"ms":\d+', '"ms":0', t)


def j(code, **kw):
    d = {"code": code}
    d.update(kw)
    return json.dumps(d).encode()


HELLO = 'pub fn main() -> Unit !io = println("hello")\n'
CASES = [
    ("health", "GET", "/health", None),
    ("run ok", "POST", "/run", j(HELLO)),
    ("run compile error", "POST", "/run", j("pub fn main() -> Unit !io = nope\n")),
    ("run exit status", "POST", "/run", j('pub fn main() -> Unit !io = { println("x")\n panic("boom") }\n')),
    ("run timeout", "POST", "/run", j("pub fn main() -> Unit !io = { var i = 0\n while true { i = i + 1 } }\n")),
    ("run truncated", "POST", "/run", j('pub fn main() -> Unit !io = { var i = 0\n while i < 20000 { println("0123456789012345678901234567890123456789")\n i = i + 1 } }\n')),
    ("check ok", "POST", "/check", j(HELLO)),
    ("check error", "POST", "/check", j("pub fn main() -> Unit !io = nope\n")),
    ("compile c", "POST", "/compile", j(HELLO, target="c")),
    ("compile jvm", "POST", "/compile", j(HELLO, target="jvm")),
    ("compile tile", "POST", "/compile", j("use tileir/dev.{Dev}\npub fn main() -> Unit !io = println(\"x\")\n", target="tile")),
    ("bad json", "POST", "/run", b"{nope"),
    ("bad utf8", "POST", "/run", b'{"code":"\xff\xfe"}'),
    ("oversize", "POST", "/run", j("x" * 70000)),
    ("empty body", "POST", "/run", b""),
    ("404", "GET", "/nope", None),
    ("405", "GET", "/run", None),
]


def env_for(work, slots):
    e = dict(os.environ)
    dawnc = os.environ.get("PLAY_TEST_DAWNC", os.path.join(ROOT, "dawnc-linux-x86_64"))
    e.update({
        "DAWN_BIN": os.path.join(ROOT, "bin", "dawn"),
        "DAWNC_BIN": dawnc,
        "PLAY_UNSAFE_LOCAL": "1",
        "PLAY_WORK_ROOT": work,
        "PLAY_SLOT_DIR": slots,
        "PLAY_PACKAGES": os.path.join(ROOT, "packages"),
        "PLAY_TIMEOUT": "3",
        "PLAY_COMPILE_TIMEOUT": "60",
    })
    jh = e.get("JAVA_HOME", "")
    e["PLAY_JAVA"] = os.path.join(ROOT, "playground/test/java-no-perf.sh")
    e["PLAY_JAVAP"] = os.path.join(ROOT, "playground/test/javap-no-perf.sh")
    if jh:
        e["PATH"] = os.path.join(jh, "bin") + ":" + e["PATH"]
    return e


def rss_kb(pid):
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


def main():
    binary = os.path.abspath(sys.argv[1])
    if "--previous" not in sys.argv:
        print("usage: serve-compare.py <dawn-play binary> --previous <dawn-play binary> [--gate] [--bench]")
        return 2
    previous = os.path.abspath(sys.argv[sys.argv.index("--previous") + 1])
    gate = "--gate" in sys.argv
    bench = "--bench" in sys.argv
    tmp = tempfile.mkdtemp(prefix="serve-compare.")
    procs = []

    def start(argv, e, **kw):
        p = subprocess.Popen(argv, env=e, preexec_fn=os.setsid, **kw)
        procs.append(p)
        return p

    def runner(name, exe):
        work = os.path.join(tmp, name + "-work")
        os.makedirs(work)
        env = env_for(work, os.path.join(tmp, name + "-slots"))
        env["PLAY_TOOLCHAIN_ID"] = subprocess.run(
            [os.path.join(ROOT, "bin", "dawn"), "--version"], capture_output=True, text=True, env=env
        ).stdout.strip().split("\n")[-1].split(" ", 1)[1].replace(" (selfhost)", "")
        sockpath = f"serve-compare-{os.getpid()}-{name}"  # abstract (inetd.py): no path length limit
        inetd = [sys.executable, "-I", "-B", os.path.join(ROOT, "playground", "test", "inetd.py"), sockpath]
        start(inetd + [exe, "serve"], env,
              stdout=open(os.path.join(tmp, name + ".log"), "w"), stderr=subprocess.STDOUT)
        call = unix(sockpath)
        for _ in range(240):
            try:
                call("GET", "/health", None)
                return call, sockpath
            except OSError:
                time.sleep(0.25)
        raise RuntimeError(f"the {name} runner did not come up")

    try:
        ref, _ = runner("previous", previous)
        nat, sockpath = runner("candidate", binary)

        bad = 0
        for name, m, p, b in CASES:
            r1 = split(ref(m, p, b))
            r2 = split(nat(m, p, b))
            same = r1[0] == r2[0] and norm(r1[2]) == norm(r2[2])
            print(f"  {'ok  ' if same else 'FAIL'} {name}: {r1[0]} / {r2[0]}")
            if not same:
                bad += 1
                print("    previous :", norm(r1[2])[:300])
                print("    candidate:", norm(r2[2])[:300])
        print(f"{len(CASES) - bad} of {len(CASES)} responses identical")

        if gate:
            bad += gate_test(nat, tmp)
        if bench:
            bench_test(ref, nat)
        return 1 if bad else 0
    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
        time.sleep(0.5)
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
        subprocess.run(["rm", "-rf", tmp])


def gate_test(nat, tmp):
    """Two slots, three concurrent slow /run requests: the third waits for a slot
    (the long-lived server's contract: /run queues up to 15 s, /check and
    /compile fail fast with 429 after 2 s)."""
    print("gate:")
    bad = 0
    # a /run that holds its slot for about 3 s: the program runs until PLAY_TIMEOUT
    slow = j("pub fn main() -> Unit !io = { var i = 0\n while true { i = i + 1 } }\n")
    results = {}

    def go(k, path, body):
        t0 = time.time()
        r = split(nat("POST", path, body))
        results[k] = (r[0], time.time() - t0, r[2])

    ths = [threading.Thread(target=go, args=(k, "/run", slow)) for k in range(3)]
    t0 = time.time()
    for t in ths:
        t.start()
        time.sleep(0.4)
    for t in ths:
        t.join()
    for k in range(3):
        st, dt, body = results[k]
        print(f"    /run #{k}: {st} after {dt:.1f}s ({norm(body)[:60]})")
    waits = sorted(v[1] for v in results.values())
    ok = all(v[0].endswith("200 OK") for v in results.values()) and waits[2] > waits[0] + 2.0
    print(f"  {'ok  ' if ok else 'FAIL'} three /run on two slots: all answer 200, the third waited for a slot")
    bad += 0 if ok else 1

    # /check is advisory: with both slots held a third gets 429 after about 2 s
    results.clear()
    ths = [threading.Thread(target=go, args=(k, "/run", slow)) for k in range(2)]
    for t in ths:
        t.start()
    time.sleep(1.0)
    t1 = time.time()
    st, _, body = split(nat("POST", "/check", j(HELLO)))
    dt = time.time() - t1
    for t in ths:
        t.join()
    ok = st.endswith("429 Too Many Requests") or " 429" in st
    ok = ok and 1.5 < dt < 4.5 and b"server busy" in body
    print(f"  {'ok  ' if ok else 'FAIL'} /check with both slots held: {st} after {dt:.1f}s")
    bad += 0 if ok else 1

    # the permit is back afterwards
    st, _, _ = split(nat("POST", "/check", j(HELLO)))
    ok = st.endswith("200 OK")
    print(f"  {'ok  ' if ok else 'FAIL'} the slots come back: /check -> {st}")
    bad += 0 if ok else 1

    # a SIGKILLed job gives its slot back (the kernel drops the lock)
    ths = [threading.Thread(target=go, args=(k, "/run", slow)) for k in range(2)]
    for t in ths:
        t.start()
    time.sleep(1.0)
    subprocess.run(["pkill", "-KILL", "-f", "dawn-play.* job "], check=False)
    time.sleep(0.5)
    t1 = time.time()
    st, _, _ = split(nat("POST", "/check", j(HELLO)))
    dt = time.time() - t1
    for t in ths:
        t.join()
    ok = st.endswith("200 OK") and dt < 1.9
    print(f"  {'ok  ' if ok else 'FAIL'} after SIGKILL of both jobs the next /check gets a slot at once: {st} after {dt:.1f}s")
    bad += 0 if ok else 1
    return bad


def bench_test(ref, nat):
    print("latency (ms), a new connection every time:")
    for name, call, m, p, b in [
        ("candidate /health", nat, "GET", "/health", None),
        ("previous  /health", ref, "GET", "/health", None),
        ("candidate /check ", nat, "POST", "/check", j(HELLO)),
        ("previous  /check ", ref, "POST", "/check", j(HELLO)),
    ]:
        n = 100 if "health" in name else 40
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            call(m, p, b)
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort()
        print(f"  {name}: p50 {statistics.median(ts):.1f}  p95 {ts[int(len(ts) * 0.95) - 1]:.1f}  max {ts[-1]:.1f}")


if __name__ == "__main__":
    sys.exit(main())
