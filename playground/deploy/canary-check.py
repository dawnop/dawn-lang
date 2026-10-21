#!/usr/bin/env python3
"""The canary check for the Playground runner. redeploy.sh runs it on the
server twice: before the new binary replaces the live one, and after.

    canary-check.py --candidate BIN [--previous BIN] --unit UNIT --toolchain-id "V B"
                    [--accept-diff] [--slow-requests 20] [--slow-spacing 1.0]
                    [--inherit-env] [--set NAME=VALUE ...]
    canary-check.py --warm --candidate BIN --unit UNIT --toolchain-id "V B"
                    --samples DIR --stage DIR
    canary-check.py --live [--socket /run/dawn-play/http.sock] --toolchain-id "V B"
                    [--health-requests 100] [--samples DIR]
    canary-check.py --self-test

Before the swap (the default mode) it holds the candidate, the binary this
deploy ships, to the previous one, the binary that is live until the swap.
Both are started the way the socket unit starts them, one process per
request with the request on stdin and the answer on stdout, with the unit's
`Environment=` lines (`--unit`), the toolchain id this deploy writes, the
unit's working directory and the systemd default PATH. They run as the user
that runs this script (redeploy.sh: dawn-play), so their jobs go through the
real sudo wrapper, the real sandbox units and the live flock slots. Nothing is
put behind the socket until this passes.

1. Expectations. Every case has an answer the candidate must give whatever
   the previous one says: /health names the release and build being deployed,
   hello prints hello, a compile error is a diagnostic with no server path in
   it, the refusals have their statuses. And every request leaves one access
   line on stderr that names the toolchain and, for a program, its SHA-256,
   and never the program's text (ruling 4 of 2026-10-19).
2. Byte compare. The previous runner and the candidate answer the same
   requests with the same toolchain (redeploy.sh has synced it by then), so
   any difference in status or body, `ms` aside, is the runner's own change.
   That is a failure unless the deploy says it expects one (`--accept-diff`,
   DAWN_PLAY_CANARY_ACCEPT_DIFF=1 in redeploy.sh); the differences are printed
   either way.
3. The latency gate, the two binaries interleaved so a slow moment of the host
   hits both: on `/run` hello and `/check` hello, `--slow-requests` (20) each,
   spaced out so the production sandbox is not loaded, the candidate's p95 is
   at most SLOW_RATIO (1.15) x the previous one's + SLOW_SLACK_MS (100) ms.
   These are the numbers the K4 gate held native to JVM with, measured on the
   production host: /run is about 3.0 s and /check about 1.2 s, and 20
   samples carry about 100 ms of noise at p95.

Without a previous binary (a first install) 2 and 3 are skipped and say so.

Why the previous native runner and not the JVM runner any more: until K5 the
canary compared the native runner with the JVM runner of the same commit, which
checked that two entries of one tree answered alike. With one entry left the
question is whether this deploy's runner answers like the one it replaces, and
the one place both binaries and one toolchain exist side by side is the server
mid-deploy. Comparing against the previous release's recorded answers instead
was the other option and was not taken: a release that changes a diagnostic
or the compile view (Emit-Change) would differ from a record for reasons that
are not the runner's, and the live binary on the same toolchain does not.

Before the swap it also warms the sample answers (`--warm`): the candidate's
`warm` subcommand (play/warm.dawn) sends every sample through its own routes
into a staging directory, with the same environment, and the deploy then
installs that directory as the answer store the runner's unit names
(PLAY_ANSWERS, docs/playground-native-runner-design.md 4.4). The canary above
runs with the store switched off (`PLAY_ANSWERS=`), so a store left by the
last deploy can never turn the candidate's live answers into hits that the
previous runner, which has no store, would be compared against.

After the swap (`--live`) it asks the socket itself, so the real `Accept=yes`
start-up is in the numbers: /health answers this release and build, its p95
over `--health-requests` (100) new connections is at most HEALTH_CEILING_MS
(25) ms (measured 7.7 to 7.9 ms on the production host, almost all of it
systemd starting an instance per connection), and one /run hello prints hello. With `--samples DIR` it also holds the store
to its two promises through the socket: the hello sample, sent as it is on
disk, is answered from the store (`"cached":true`) with the output its `.out`
file records, and the same sample with one more byte at the end is not (the
program really compiles and runs, and the answer does not say it came from
the store).

Exit status 0 only when everything holds. Standard library only, because it
runs on the server under `python3 -I`.
"""
import argparse, json, os, re, shlex, socket, subprocess, sys, time

HELLO = 'pub fn main() -> Unit !io = println("hello")\n'
SYSTEMD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
SERVER_PATHS = ("/var/lib/dawn-play", "/opt/dawn", "dawn-play-")


def j(code, **kw):
    d = {"code": code}
    d.update(kw)
    return json.dumps(d).encode()


def no_server_path(d):
    text = json.dumps(d)
    return not any(p in text for p in SERVER_PATHS)


# name, method, path, body, the program's text (None: the body names none),
# expectation on (status, parsed body, toolchain (version, build))
CASES = [
    ("health", "GET", "/health", None, None,
     lambda st, d, tc: st == "200" and d.get("ok") is True and (d.get("version"), d.get("build")) == tc),
    ("run ok", "POST", "/run", j(HELLO), HELLO,
     lambda st, d, tc: st == "200" and d.get("ok") is True and d.get("phase") == "run"
     and d.get("exit") == 0 and d.get("output") == "hello\n"),
    ("run compile error", "POST", "/run", j("pub fn main() -> Unit !io = nope\n"), "pub fn main() -> Unit !io = nope\n",
     lambda st, d, tc: st == "200" and d.get("ok") is False and d.get("phase") == "compile"
     and "prog.dawn" in d.get("output", "") and no_server_path(d)),
    ("run exit status", "POST", "/run", j('pub fn main() -> Unit !io = { println("x")\n panic("boom") }\n'),
     'pub fn main() -> Unit !io = { println("x")\n panic("boom") }\n',
     lambda st, d, tc: st == "200" and d.get("phase") == "run" and d.get("exit") == 1
     and d.get("output", "").startswith("x\n") and "panic: boom" in d.get("output", "") and no_server_path(d)),
    ("check ok", "POST", "/check", j(HELLO), HELLO,
     lambda st, d, tc: st == "200" and d.get("ok") is True and d.get("phase") == "check"),
    ("check error", "POST", "/check", j("pub fn main() -> Unit !io = nope\n"), "pub fn main() -> Unit !io = nope\n",
     lambda st, d, tc: st == "200" and d.get("ok") is False and d.get("phase") == "compile"
     and "prog.dawn" in d.get("output", "") and no_server_path(d)),
    ("compile c", "POST", "/compile", j(HELLO, target="c"), HELLO,
     lambda st, d, tc: st == "200" and d.get("ok") is True and d.get("phase") == "compile-view"
     and d.get("target") == "c" and d.get("build") == tc[1] and no_server_path(d)),
    ("compile jvm", "POST", "/compile", j(HELLO, target="jvm"), HELLO,
     lambda st, d, tc: st == "200" and d.get("ok") is True and d.get("phase") == "compile-view"
     and d.get("target") == "jvm" and d.get("build") == tc[1] and no_server_path(d)),
    ("bad json", "POST", "/run", b"{nope", None,
     lambda st, d, tc: st == "400" and d.get("phase") == "error"),
    ("bad utf8", "POST", "/run", b'{"code":"\xff\xfe"}', None,
     lambda st, d, tc: st == "400" and "UTF-8" in d.get("output", "")),
    ("oversize", "POST", "/run", j("x" * 70000), None,
     lambda st, d, tc: st == "413"),
    ("empty body", "POST", "/run", b"", None,
     lambda st, d, tc: st == "400" and d.get("phase") == "error"),
    ("404", "GET", "/nope", None, None,
     lambda st, d, tc: st == "404"),
    ("405", "GET", "/run", None, None,
     lambda st, d, tc: st == "405"),
]


def request_bytes(method, path, body):
    head = f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n"
    if body is not None:
        head += f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n"
    return head.encode() + b"\r\n" + (body or b"")


def split(resp):
    head, _, body = resp.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode("latin-1")
    parts = status.split(" ")
    code = parts[1] if len(parts) > 1 else ""
    return code, body


def parsed(body):
    try:
        d = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def normalize(body):
    return re.sub(r'"ms":\d+', '"ms":0', body.decode("utf-8", "replace"))


def p95(samples):
    s = sorted(samples)
    return s[max(0, int(len(s) * 0.95 + 0.999999) - 1)]


# Thresholds. See the header for the measurements behind them.
SLOW_RATIO = 1.15        # candidate p95 vs previous p95 on /run and /check
SLOW_SLACK_MS = 100.0    # absolute allowance on top: p95 of 20 samples is noisy
HEALTH_CEILING_MS = 25.0  # /health p95 through the socket, absolute (3x the measured 7.9 ms)
SLOW_REQUESTS = 20
SLOW_SPACING_S = 1.0     # pause between request pairs on the slow endpoints


def gate_ok(candidate_p95, previous_p95, ratio=SLOW_RATIO, slack_ms=SLOW_SLACK_MS):
    return candidate_p95 <= ratio * previous_p95 + slack_ms


def ceiling_ok(p95_ms, ceiling_ms=HEALTH_CEILING_MS):
    return p95_ms <= ceiling_ms


def unit_environment(text):
    """The `Environment=` assignments of a unit file, in order, quotes as systemd reads them."""
    env = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("Environment="):
            continue
        for word in shlex.split(line[len("Environment="):]):
            name, eq, value = word.partition("=")
            if eq:
                env[name] = value
    return env


def unit_setting(text, key):
    for line in text.splitlines():
        if line.strip().startswith(key + "="):
            return line.strip()[len(key) + 1:]
    return ""


def access_line_ok(stderr, method, path, status, toolchain, code):
    """One line `<status> <method> <path> toolchain=<v>/<b>[ src_sha256=...]`, no program text."""
    tc = f"{toolchain[0]}/{toolchain[1]}"
    if code is not None and code.strip() and code.strip() in stderr:
        return False
    want = f"{status} {method} {path} toolchain={tc}"
    for line in stderr.splitlines():
        if line == want or line.startswith(want + " "):
            rest = line[len(want):]
            if method == "POST" and path in ("/run", "/check", "/compile"):
                return re.fullmatch(r" src_sha256=([0-9a-f]{64}|-)( target=\w+)?", rest) is not None
            return rest == ""
        if re.match(r"^\d{3} \(unreadable request\)$", line) and status in ("413", "400"):
            return True
    return False


def direct(binary, env, cwd):
    def go(method, path, body):
        r = subprocess.run([binary, "serve"], input=request_bytes(method, path, body),
                           capture_output=True, env=env, cwd=cwd, timeout=120)
        return r.stdout, r.stderr.decode("utf-8", "replace")
    return go


def over_unix(sock_path):
    def go(method, path, body):
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(60)
        s.connect(sock_path)
        try:
            s.sendall(request_bytes(method, path, body))
            chunks = []
            while True:
                c = s.recv(65536)
                if not c:
                    break
                chunks.append(c)
            return b"".join(chunks), ""
        finally:
            s.close()
    return go


def timed(call, method, path, body):
    t0 = time.perf_counter()
    code, _ = split(call(method, path, body)[0])
    ms = (time.perf_counter() - t0) * 1000
    if code != "200":
        raise RuntimeError(f"{path} answered {code}")
    return ms


def toolchain_of(tid):
    words = tid.split()
    if len(words) != 2:
        raise SystemExit(f"--toolchain-id must be '<version> <build>', got {tid!r}")
    return words[0], words[1]


def candidate_env(a):
    """The environment and working directory a request process of the unit gets,
    with the answer store switched off (see the header)."""
    unit = open(a.unit, encoding="utf-8").read()
    env = dict(os.environ) if a.inherit_env else {"PATH": SYSTEMD_PATH}
    env.update(unit_environment(unit))
    for kv in a.set:
        name, _, value = kv.partition("=")
        env[name] = value
    env["PLAY_TOOLCHAIN_ID"] = a.toolchain_id
    env["PLAY_ANSWERS"] = ""
    wd = unit_setting(unit, "WorkingDirectory")
    return env, (wd if wd and os.path.isdir(wd) else None)


def warm(a):
    """Run the candidate's `warm` over the samples into the staging directory."""
    toolchain_of(a.toolchain_id)
    if not a.candidate or not a.unit or not a.samples or not a.stage:
        raise SystemExit("--warm needs --candidate, --unit, --samples and --stage")
    env, cwd = candidate_env(a)
    r = subprocess.run([a.candidate, "warm", a.samples, a.stage], env=env, cwd=cwd, timeout=1800)
    kept = len(os.listdir(a.stage)) if os.path.isdir(a.stage) else 0
    print(f"warm: exit {r.returncode}, {kept} answers in {a.stage}")
    return 0 if r.returncode == 0 and kept > 0 else 1


def pre_swap(a):
    tc = toolchain_of(a.toolchain_id)
    env, cwd = candidate_env(a)
    cand = direct(a.candidate, env, cwd)
    prev = direct(a.previous, env, cwd) if a.previous and os.access(a.previous, os.X_OK) else None
    if prev is None:
        print(f"note: no previous runner at {a.previous!r}; checking the candidate's own answers only")
    bad = differ = 0
    for name, m, p, b, code, expect in CASES:
        out, err = cand(m, p, b)
        st, body = split(out)
        good = expect(st, parsed(body), tc)
        logged = access_line_ok(err, m, p, st, tc, code)
        print(f"  {'ok  ' if good and logged else 'FAIL'} {name}: candidate {st}"
              + ("" if logged else " (access line: " + err.strip()[:200] + ")"))
        if not good:
            print("    candidate:", normalize(body)[:300])
        bad += 0 if good and logged else 1
        if prev is not None:
            pst, pbody = split(prev(m, p, b)[0])
            if (pst, normalize(pbody)) != (st, normalize(body)):
                differ += 1
                print(f"  {'note' if a.accept_diff else 'FAIL'} {name}: previous {pst} / candidate {st} differ")
                print("    previous :", normalize(pbody)[:300])
                print("    candidate:", normalize(body)[:300])
    if prev is not None:
        print(f"{len(CASES) - differ} of {len(CASES)} answers identical to the previous runner"
              + (" (differences accepted)" if differ and a.accept_diff else ""))
        if differ and not a.accept_diff:
            bad += 1
        n = a.slow_requests
        for name, path in (("/run hello", "/run"), ("/check hello", "/check")):
            pt, ct = [], []
            for i in range(n):
                pt.append(timed(prev, "POST", path, j(HELLO)))
                ct.append(timed(cand, "POST", path, j(HELLO)))
                if a.slow_spacing and i + 1 < n:
                    time.sleep(a.slow_spacing)
            pp, cp = p95(pt), p95(ct)
            limit = SLOW_RATIO * pp + SLOW_SLACK_MS
            ok = gate_ok(cp, pp)
            print(f"{name} over {n} requests each: previous p95 {pp:.0f} ms, candidate p95 {cp:.0f} ms "
                  f"(limit {SLOW_RATIO:g} x previous + {SLOW_SLACK_MS:g} = {limit:.0f} ms)")
            print(f"  {'ok  ' if ok else 'FAIL'} candidate {path} p95 within the limit")
            bad += 0 if ok else 1
    return 1 if bad else 0


def live(a):
    tc = toolchain_of(a.toolchain_id)
    call = over_unix(a.socket)
    bad = 0
    st, body = split(call("GET", "/health", None)[0])
    d = parsed(body)
    ok = st == "200" and d.get("ok") is True and (d.get("version"), d.get("build")) == tc
    print(f"  {'ok  ' if ok else 'FAIL'} /health through {a.socket}: {st} {normalize(body)[:120]}")
    bad += 0 if ok else 1
    ts = [timed(call, "GET", "/health", None) for _ in range(a.health_requests)]
    hp = p95(ts)
    ok = ceiling_ok(hp)
    print(f"/health over {a.health_requests} new connections: p95 {hp:.2f} ms (ceiling {HEALTH_CEILING_MS:g} ms)")
    print(f"  {'ok  ' if ok else 'FAIL'} /health p95 <= {HEALTH_CEILING_MS:g} ms")
    bad += 0 if ok else 1
    st, body = split(call("POST", "/run", j(HELLO))[0])
    d = parsed(body)
    ok = st == "200" and d.get("ok") is True and d.get("output") == "hello\n"
    print(f"  {'ok  ' if ok else 'FAIL'} /run hello through the socket: {st} {normalize(body)[:120]}")
    bad += 0 if ok else 1
    if a.samples:
        bad += live_store(call, a.samples)
    return 1 if bad else 0


def live_store(call, samples):
    """The sample answer store, through the socket: a hit is the recorded
    answer marked cached, one more byte is a real compile and run."""
    bad = 0
    code = open(os.path.join(samples, "hello.dawn"), encoding="utf-8").read()
    want = open(os.path.join(samples, "hello.out"), encoding="utf-8").read()
    t0 = time.perf_counter()
    st, body = split(call("POST", "/run", j(code))[0])
    ms = (time.perf_counter() - t0) * 1000
    d = parsed(body)
    ok = st == "200" and d.get("ok") is True and d.get("output") == want and d.get("cached") is True
    print(f"  {'ok  ' if ok else 'FAIL'} /run of the hello sample is answered from the store: {st} cached={d.get('cached')} {ms:.0f} ms")
    bad += 0 if ok else 1
    t0 = time.perf_counter()
    st, body = split(call("POST", "/run", j(code + "\n"))[0])
    ms = (time.perf_counter() - t0) * 1000
    d = parsed(body)
    ok = st == "200" and d.get("ok") is True and d.get("output") == want and not d.get("cached")
    print(f"  {'ok  ' if ok else 'FAIL'} /run of the sample plus one byte is compiled, not served from the store: {st} {ms:.0f} ms")
    bad += 0 if ok else 1
    return bad


def self_test():
    assert p95(list(range(1, 101))) == 95
    assert p95([5]) == 5
    assert p95([3, 1, 2]) == 3
    # ratio gate: limit = 1.15 x previous + 100 ms
    assert gate_ok(3194, 3257) and gate_ok(1349, 1267)  # the K4 measurements: both pass
    assert gate_ok(1.15 * 1000 + 100, 1000) and not gate_ok(1.15 * 1000 + 100.5, 1000)
    assert gate_ok(100, 0) and not gate_ok(100.1, 0)
    assert not gate_ok(2000, 1267)  # a real regression fails
    assert ceiling_ok(7.9) and ceiling_ok(25.0) and not ceiling_ok(25.01)
    assert normalize(b'{"ok":true,"ms":12,"x":1}') == normalize(b'{"ok":true,"ms":9,"x":1}')
    assert normalize(b'{"ok":true,"ms":1,"x":1}') != normalize(b'{"ok":true,"ms":1,"x":2}')
    assert split(b"HTTP/1.1 429 Too Many Requests\r\nA: b\r\n\r\nbody") == ("429", b"body")
    assert split(b"") == ("", b"")
    unit = ('[Service]\nEnvironment=A=1\nEnvironment="B=two words" C=3\n'
            '# Environment=D=commented\nWorkingDirectory=/opt/dawn\n')
    assert unit_environment(unit) == {"A": "1", "B": "two words", "C": "3"}, unit_environment(unit)
    assert unit_setting(unit, "WorkingDirectory") == "/opt/dawn"
    tc = ("0.94.0", "b1:96af8ed9c5f2")
    expect = {name: e for name, _, _, _, _, e in CASES}
    assert expect["health"]("200", {"ok": True, "version": "0.94.0", "build": "b1:96af8ed9c5f2"}, tc)
    assert not expect["health"]("200", {"ok": True, "version": "0.93.0", "build": "b1:96af8ed9c5f2"}, tc)
    assert expect["run ok"]("200", {"ok": True, "phase": "run", "exit": 0, "output": "hello\n"}, tc)
    assert not expect["run ok"]("200", {"ok": True, "phase": "run", "exit": 0, "output": "hi\n"}, tc)
    leak = {"ok": False, "phase": "compile", "output": "/var/lib/dawn-play/work/dawn-play-1/prog.dawn:1"}
    assert not expect["run compile error"]("200", leak, tc)
    assert expect["404"]("404", {}, tc) and not expect["404"]("200", {}, tc)
    digest = "6c18de180764abc1fd49ffb69213b99c8519525409db100d52d29be7aad93404"
    line = f"200 POST /run toolchain=0.94.0/b1:96af8ed9c5f2 src_sha256={digest}\n"
    assert access_line_ok(line, "POST", "/run", "200", tc, "secret-marker")
    assert not access_line_ok(line + "secret-marker\n", "POST", "/run", "200", tc, "secret-marker")
    assert not access_line_ok("200 POST /run\n", "POST", "/run", "200", tc, "x")  # the K4 line
    assert not access_line_ok(line.replace("0.94.0", "0.93.0"), "POST", "/run", "200", tc, "x")
    assert access_line_ok("200 POST /compile toolchain=0.94.0/b1:96af8ed9c5f2 src_sha256=- \n".strip(),
                          "POST", "/compile", "200", tc, None)
    assert access_line_ok("200 GET /health toolchain=0.94.0/b1:96af8ed9c5f2\n", "GET", "/health", "200", tc, None)
    assert access_line_ok("413 (unreadable request)\n", "POST", "/run", "413", tc, None)
    # the candidate's environment never carries a store, whatever the unit says
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".service") as f:
        f.write("[Service]\nEnvironment=PLAY_ANSWERS=/opt/dawn/playground/answers\nEnvironment=PLAY_JDK=/x\n")
        f.flush()
        args = argparse.Namespace(unit=f.name, inherit_env=False, set=[], toolchain_id="0.94.0 b1:96af8ed9c5f2")
        env, _ = candidate_env(args)
    assert env["PLAY_ANSWERS"] == "" and env["PLAY_JDK"] == "/x" and env["PLAY_TOOLCHAIN_ID"] == args.toolchain_id, env
    print("canary-check self-test ok")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--candidate")
    ap.add_argument("--previous", default="")
    ap.add_argument("--unit")
    ap.add_argument("--toolchain-id")
    ap.add_argument("--accept-diff", action="store_true")
    ap.add_argument("--inherit-env", action="store_true")
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--warm", action="store_true")
    ap.add_argument("--samples", default="")
    ap.add_argument("--stage", default="")
    ap.add_argument("--socket", default="/run/dawn-play/http.sock")
    ap.add_argument("--health-requests", type=int, default=100)
    ap.add_argument("--slow-requests", type=int, default=SLOW_REQUESTS)
    ap.add_argument("--slow-spacing", type=float, default=SLOW_SPACING_S)
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if not a.toolchain_id:
        ap.error("--toolchain-id is required")
    if a.live:
        return live(a)
    if a.warm:
        return warm(a)
    if not a.candidate or not a.unit:
        ap.error("--candidate and --unit are required before the swap")
    return pre_swap(a)


if __name__ == "__main__":
    sys.exit(main())
