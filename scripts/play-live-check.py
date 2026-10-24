#!/usr/bin/env python3
"""Check a *deployed* Playground against the samples in the tree.

The documentation check, scripts/doc-check.py, already runs
`site/play-ui/samples/*.dawn` with the local compiler and compares stdout with
the `.out` beside each one. Nothing checked the same thing against the
*server*, and that gap is not hypothetical: the sidebar shipped a
`fn`-prefixed lambda the compiler had rejected for eight releases, and the
deployed runner sat thirteen days behind the tree, each half consistent with
the other and both wrong. Two things have to agree here that
`doc-check` cannot compare: the compiler the server runs, and the bundle nginx
serves.

Usage:

    scripts/play-live-check.py                  # the public deployment
    PLAY_BASE_URL=http://127.0.0.1:18087 scripts/play-live-check.py --runner-only

`PLAY_BASE_URL` points at the site root, for the static checks; a bare runner
with no nginx in front wants `--runner-only`, which skips the static checks and
talks to `PLAY_BASE_URL` with no `/api` prefix. Exit status is 0 only when
every check passed.

The page check reads the `data-endpoint` the live playground page hands the
editor and asserts that the origin it resolves to is `PLAY_EXPECT_ORIGIN`
(default `https://play.dawnop.com`), that this origin's `/api/health` answers
200, and that it allows the site origin by CORS. It exists because a deploy
built without DAWN_SITE_PLAY_ORIGIN (2026-10-08) shipped a page calling its own
CDN, and every other check here passed: they all talk to the API origin
directly and never look at what the page points at. `--page-file F` checks a
saved page instead of fetching one (the live health probe still runs).
`--page-only` runs just this group.

`--self-test` runs the offline cases of the sample comparison below and talks
to no server.

Runner checks also append a fresh harmless comment to flash_attn and send it
through /check, /run and all three /compile targets. These five cache misses
share a 120 second budget and print their added client wall clock. Call totals
come from the sidebar fixture's existing playground/test/contract.sh oracles.

`PLAY_API_URL` is where the runner checks go, while the static checks stay on
`PLAY_BASE_URL`. It is the `/api` base itself (no trailing `/run`). The public
pages are on a CDN and the Playground service is not (docs/site-cdn-design.md),
so it defaults to the service's own origin, `https://play.dawnop.com/api`,
whatever `PLAY_BASE_URL` says. Pointing `PLAY_BASE_URL` somewhere else (a local
static site, a staging origin) does not move the runner checks; set both. With
`--runner-only` the default is `PLAY_BASE_URL` itself, the bare runner.

No server identity here: the public hostname is public, the ssh login is not
(see scripts/check-no-server-identity.py) -- this script never needs to log in.
"""

import argparse
import json
import os
import pathlib
import re
import secrets
import shlex
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import repo_env  # scripts/repo_env.py, the reader of scripts/repo.env

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "site" / "play-ui" / "samples"
VERSION_DAWN = ROOT / "selfhost" / "src" / "version.dawn"
DEFAULT_BASE = repo_env.site_origin()
DEFAULT_API = "https://play.dawnop.com/api"
DEFAULT_PLAY_ORIGIN = "https://play.dawnop.com"

# Never route through a dev proxy: this box has http_proxy set, and urllib
# honours it, which turns a localhost check into a 502 from somebody else.
OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPRedirectHandler()
)

# The compiler version discriminant: a minimal pair differing only in how the
# lambda is spelled. `fn(c) =>` is the form retired in v0.43.0, which 0.8.0
# accepts and any current compiler refuses; the bare arrow is the replacement.
#
# Both directions are asserted, and the rejection is matched on its specific
# diagnostic. A runner that is simply broken rejects the old form too, and a
# runner whose `map` is undefined rejects both -- neither would prove the
# version moved, which is the only thing this pair exists to prove.
NEW_LAMBDA = "pub fn main() -> Unit !io = println(to_string(map([1, 2], c => c + 1)))"
OLD_LAMBDA = "pub fn main() -> Unit !io = println(to_string(map([1, 2], fn(c) => c + 1)))"
NEW_LAMBDA_OUT = "[2, 3]\n"
OLD_LAMBDA_DIAG = "a lambda has no `fn` prefix"


# The Playground compiles its buffer as `prog.dawn` (playground/src/play/
# exec.dawn), while each sample's `.out` is recorded by running the sample
# under its own name. Since a failure carries `at <file>:<line>:<col>` (L2,
# #425), a sample whose output names a position differs in the file name
# alone. Only that sample's own name, directly followed by `:<line>`, becomes
# `prog.dawn`; the line and column stay, and nothing else is rewritten.
PLAYGROUND_FILE = b"prog.dawn"


def playground_expected(sample_name, expected):
    """`expected` as the Playground prints it: the sample's file name is prog.dawn."""
    own = re.escape(sample_name.encode())
    return re.sub(
        rb"(?<![\w./-])" + own + rb"(?=:[0-9])", PLAYGROUND_FILE, expected
    )


def sample_matches(sample_name, expected, actual, rewrite=playground_expected):
    return actual == rewrite(sample_name, expected)


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, ok, name, detail=""):
        if ok:
            self.passed += 1
            print(f"  ok   {name}")
        else:
            self.failed += 1
            print(f"FAIL   {name}")
            if detail:
                for line in str(detail).splitlines():
                    print(f"         {line}")


# nginx rate-limits /api/run to 12r/m with burst=4 (playground/deploy/
# nginx-play.conf), i.e. one token every five seconds. A gate that fires its
# requests as fast as it can writes them off as failures -- the first run of
# this script reported two, and neither was the deployment's fault. So pace the
# calls and treat 429 as backpressure to wait out, never as a result.
RUN_PACE_SECS = 5.5
RUN_429_RETRIES = 6
# Five sequential cold requests, including pacing and 429 backoff, share this
# budget. A failed or saturated deployment must not add five long timeouts.
FLASH_MISS_BUDGET_SECS = 120
FLASH_MISS_REQUEST_SECS = 30


def post_run(api, code, timeout=120):
    """POST one program to /run, waiting out rate limiting. Returns decoded JSON."""
    return post_json(api, "run", {"code": code}, timeout)


def post_json(api, route, payload, timeout=120, deadline=None):
    """POST JSON, with optional shared deadline for requests and 429 backoff."""
    req = urllib.request.Request(
        f"{api}/{route}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(RUN_429_RETRIES):
        remaining = deadline - time.monotonic() if deadline is not None else timeout
        if remaining <= 0:
            raise TimeoutError("flash cache-miss budget exhausted")
        try:
            with OPENER.open(req, timeout=min(timeout, remaining)) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RUN_429_RETRIES - 1:
                raise
            delay = RUN_PACE_SECS * (attempt + 1)
            if deadline is not None and delay >= deadline - time.monotonic():
                raise TimeoutError("flash cache-miss budget exhausted during 429 backoff") from e
            time.sleep(delay)
    raise RuntimeError("unreachable")


def get(url, timeout=30, headers=None):
    """GET a URL. Returns (status, body-bytes, final-url); never raises on HTTP error."""
    return get_full(url, timeout, headers)[:3]


def get_full(url, timeout=30, headers=None):
    """Like get, plus the response headers as a fourth element."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.url, resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), url, e.headers


def page_play_origin(html, page_url):
    """The origin the playground page's editor will call, or None if no mount.

    The mount is `<div id="dawn-playground" data-endpoint="...">`; the value is
    `/api/run` (same origin as the page) or `https://host/api/run`. Resolved
    against the page URL exactly as site/play-ui/src/endpoints.ts does.
    """
    m = re.search(
        r'<div[^>]*\bid="dawn-playground"[^>]*\bdata-endpoint="([^"]*)"', html
    ) or re.search(
        r'<div[^>]*\bdata-endpoint="([^"]*)"[^>]*\bid="dawn-playground"', html
    )
    if not m:
        return None
    u = urllib.parse.urlsplit(urllib.parse.urljoin(page_url, m.group(1)))
    return f"{u.scheme}://{u.netloc}"


def tree_version():
    """The `VERSION` constant of the local tree's compiler, e.g. "0.81.0"."""
    text = VERSION_DAWN.read_text()
    m = re.search(r'^pub const VERSION: String = "([^"]*)"', text, re.M)
    if not m:
        sys.exit(f"cannot find VERSION in {VERSION_DAWN}")
    return m.group(1)


def check_health(api, r):
    """/health answers {"ok": true, "version": "<release>", "build": "b1:..."},
    and the release is the one in the tree.

    The lambda pair below only proves the runner is newer than v0.43; the
    version field pins it to the release this tree is about to ship, which is
    the comparison the samples already assume.
    """
    status, body, _ = get(f"{api}/health")
    if status == 200 and body.strip() == b"ok":
        r.check(
            False,
            "/health -> {ok: true, version}",
            "got bare `ok`: the runner predates the versioned health (PR #328), redeploy it",
        )
        return
    try:
        health = json.loads(body)
    except ValueError:
        health = None
    if not isinstance(health, dict):
        health = {}
    version = health.get("version")
    shaped = (
        status == 200
        and health.get("ok") is True
        and isinstance(version, str)
        and version != ""
    )
    r.check(shaped, "/health -> {ok: true, version}", f"{status} {body!r}")
    if not shaped:
        return
    want = tree_version()
    r.check(
        version == want,
        f"/health version is the tree's VERSION ({want})",
        f"runner reports {version!r}, selfhost/src/version.dawn says {want!r}",
    )
    # The short build-manifest digest of the runner's compiler. Only its shape
    # is checked: which main commit a deployment was built from is not this
    # tree's to know, and the version above already pins the release.
    build = health.get("build")
    r.check(
        isinstance(build, str) and re.fullmatch(r"b1:[0-9a-f]{12}", build) is not None,
        "/health build is a short build-manifest digest (b1: and 12 hex digits)",
        f"runner reports build {build!r}: its compiler predates build manifests, redeploy it",
    )


def check_runner(api, r, pace):
    print(f"== runner: {api} ==")

    check_health(api, r)

    # The samples, byte for byte. `output` is the runner's captured stdout
    # (stderr is merged into it by redirectErrorStream), and the .out files are
    # what doc-check compares the local compiler against.
    for dawn in sorted(SAMPLES.glob("*.dawn")):
        expected = dawn.with_suffix(".out").read_bytes()
        name = f"sample {dawn.name}"
        time.sleep(pace)
        try:
            got = post_run(api, dawn.read_text())
        except Exception as e:  # noqa: BLE001 - any transport failure is a failure
            r.check(False, name, f"request failed: {e}")
            continue
        if not got.get("ok"):
            r.check(False, name, f"phase={got.get('phase')} output={got.get('output')!r}")
            continue
        actual = got.get("output", "").encode()
        want = playground_expected(dawn.name, expected)
        r.check(
            actual == want,
            name,
            "" if actual == want else f"expected {want!r}\ngot      {actual!r}",
        )

    # Version discriminants, both directions.
    time.sleep(pace)
    try:
        old = post_run(api, OLD_LAMBDA)
        r.check(
            not old.get("ok")
            and old.get("phase") == "compile"
            and OLD_LAMBDA_DIAG in old.get("output", ""),
            "retired `fn(c) =>` lambda is REJECTED (runner is not pre-v0.43)",
            f"got ok={old.get('ok')} phase={old.get('phase')} output={old.get('output')!r}",
        )
    except Exception as e:  # noqa: BLE001
        r.check(False, "retired `fn(c) =>` lambda is REJECTED", f"request failed: {e}")

    time.sleep(pace)
    try:
        new = post_run(api, NEW_LAMBDA)
        r.check(
            new.get("ok") and new.get("output") == NEW_LAMBDA_OUT,
            "bare arrow lambda is ACCEPTED and runs",
            f"got {new!r}",
        )
    except Exception as e:  # noqa: BLE001
        r.check(False, "bare arrow lambda is ACCEPTED and runs", f"request failed: {e}")

    check_flash_miss(api, r, pace)


def flash_call_counts():
    """Read the real sidebar fixture's contract oracles, without a local build.

    The static GPU map covers a different recording. The runner contract owns
    the sidebar's C and Tile totals; its JVM oracle requires the same calls as
    C. Fail closed if those assertions disappear or become ambiguous.
    """
    contract = (ROOT / "playground" / "test" / "contract.sh").read_text()
    counts = {}
    paired_jvm = False
    for line in contract.replace("\\\n", " ").splitlines():
        if not line.startswith(("ccheck ", "tile_ccheck ")):
            continue
        args = shlex.split(line)
        if args[2] != "$CASES/tile_attn.dawn":
            continue
        target = "tile" if args[0] == "tile_ccheck" else args[3]
        oracle = args[-1]
        if target == "jvm":
            paired_jvm = 'd["calls"]==prev["calls"]' in oracle
            continue
        matches = re.findall(r'd\["calls_total"\]\s*==\s*([0-9]+)\b', oracle)
        if len(matches) != 1 or target in counts or int(matches[0]) <= 0:
            raise ValueError(f"ambiguous flash {target} call-count oracle")
        counts[target] = int(matches[0])
    if set(counts) != {"c", "tile"} or not paired_jvm:
        raise ValueError("missing flash C/Tile totals or paired JVM oracle")
    return {"c": counts["c"], "jvm": counts["c"], "tile": counts["tile"]}


def flash_miss_response(got, route, expected, counts, target=None):
    """Validate the cold response itself; used unchanged by negative controls."""
    if not isinstance(got, dict) or got.get("ok") is not True:
        return False, f"unsuccessful response: {got!r}"
    # /check and a live /run omit cached; compile views explicitly emit false.
    if got.get("cached", False) is not False:
        return False, "response is a cache hit"
    if route == "check":
        ok = got.get("phase") == "check"
    elif route == "run":
        ok = (got.get("phase") == "run" and got.get("exit") == 0
              and got.get("truncated") is False
              and isinstance(got.get("output"), str)
              and got["output"].encode() == expected)
    else:
        pane = got.get("pane", {})
        calls = got.get("calls", [])
        ok = (got.get("phase") == "compile-view" and got.get("target") == target
              and got.get("cached") is False and pane.get("kind") == target
              and got.get("calls_total") == counts[target]
              and len(calls) == counts[target]
              and got.get("calls_truncated") is False
              and len(pane.get("outs", [])) == counts[target]
              and "unmapped" not in got
              and got.get("gaps", {}).get("count") == 0
              and got["gaps"].get("first") == [])
    return ok, "" if ok else f"unexpected {route}/{target or ''} response: {got!r}"[:2000]


def check_flash_miss(api, r, pace):
    """Exercise the compile path hidden by the sidebar's precomputed answers."""
    started = time.monotonic()
    deadline = started + FLASH_MISS_BUDGET_SECS
    try:
        counts = flash_call_counts()
        source = (SAMPLES / "flash_attn.dawn").read_text()
        # A fresh suffix on every invocation also misses an on-demand store.
        # Appending preserves every original source span and stdout position.
        code = source + ("" if source.endswith("\n") else "\n") + f"# live-check cache miss {secrets.token_hex(16)}\n"
        expected = (SAMPLES / "flash_attn.out").read_bytes()
        for route, target in [("check", None), ("run", None),
                              ("compile", "c"), ("compile", "jvm"), ("compile", "tile")]:
            name = f"flash cache miss /{route}" + (f" {target} ({counts[target]} calls)" if target else "")
            try:
                if route == "run":
                    time.sleep(min(pace, max(0, deadline - time.monotonic())))
                payload = {"code": code}
                if target:
                    payload["target"] = target
                got = post_json(api, route, payload, FLASH_MISS_REQUEST_SECS, deadline)
                ok, detail = flash_miss_response(got, route, expected, counts, target)
                r.check(ok, name, detail)
            except Exception as e:  # noqa: BLE001
                r.check(False, name, f"request failed: {e}")
    except Exception as e:  # noqa: BLE001
        r.check(False, "flash cache-miss setup", e)
    finally:
        print(f"  flash cache-miss wall clock: {time.monotonic() - started:.2f}s "
              f"(budget {FLASH_MISS_BUDGET_SECS}s)")


def check_site(base, r):
    print(f"== site: {base} ==")

    for path in ["/", "/zh/", "/spec.html", "/stdlib.html", "/playground.html"]:
        status, _, _ = get(base + path)
        r.check(status == 200, f"GET {path} -> 200", f"got {status}")

    status, _, _ = get(base + "/no-such-page-9f3c")
    r.check(status == 404, "unknown path -> 404", f"got {status}")

    # `absolute_redirect off` (fixed 2026-08-05): /zh must redirect to a
    # relative /zh/ and land on 200, not bounce to an internal port.
    status, _, final = get(base + "/zh")
    r.check(
        status == 200 and final.rstrip("/").endswith("/zh"),
        "/zh (no slash) redirects and lands 200",
        f"got {status} at {final}",
    )

    # The served bundle must carry the current sample spelling. If the runner is
    # new and the bundle is old, the sidebar hands users a program its own
    # runner refuses -- which is exactly the state this task had to unwind.
    status, body, _ = get(base + "/assets/playground.js")
    if status != 200:
        r.check(False, "bundle /assets/playground.js served", f"got {status}")
    else:
        text = body.decode("utf-8", "replace")
        r.check("c => c.name" in text, "bundle carries the arrow-lambda sample spelling")
        r.check(current_flash_in_bundle(text),
                "bundle carries the exact current BF16 flash attention sample")
        r.check(
            "fn(c) => c.name" not in text,
            "bundle no longer carries the retired `fn(c) =>` spelling",
        )


def current_flash_in_bundle(text):
    """Match the complete raw-import string, including its JS delimiters.

    The bundler can choose quotes or a template literal. Compare exact
    spellings without evaluating the bundle or accepting a source prefix.
    """
    sample = (SAMPLES / "flash_attn.dawn").read_text()
    single = sample.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    template = sample.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return any(literal in text for literal in [
        json.dumps(sample, ensure_ascii=False), "'" + single + "'", "`" + template + "`",
    ])


def check_page(base, expect, r, page_file=None):
    """What the live playground page points at, and that target is healthy."""
    page_url = base + "/playground.html"
    print(f"== page: {page_url} -> {expect} ==")
    if page_file:
        html = pathlib.Path(page_file).read_text(encoding="utf-8", errors="replace")
    else:
        status, body, _ = get(page_url)
        if status != 200:
            r.check(False, "playground page served", f"got {status}")
            return
        html = body.decode("utf-8", "replace")
    got = page_play_origin(html, page_url)
    r.check(
        got == expect,
        f"playground page calls the Playground origin ({expect})",
        f"the page points at {got!r}; was it built without DAWN_SITE_PLAY_ORIGIN?",
    )
    status, body, _, hdrs = get_full(
        f"{expect}/api/health", headers={"Origin": base}
    )
    r.check(status == 200, f"{expect}/api/health -> 200", f"got {status}")
    allow = hdrs.get("Access-Control-Allow-Origin")
    r.check(
        allow == base,
        f"{expect}/api/health allows the site origin by CORS",
        f"Access-Control-Allow-Origin is {allow!r}, want {base!r}",
    )


def self_test_page():
    """page_play_origin offline: the incident's page and the right one."""
    base = "https://site.example.test"
    page = base + "/playground.html"
    good = '<div id="dawn-playground" data-endpoint="https://play.example.test/api/run"></div>'
    bad = '<div id="dawn-playground" data-endpoint="/api/run"></div>'
    flipped = '<div data-endpoint="https://play.example.test/api/run" id="dawn-playground"></div>'
    cases = (
        ("absolute endpoint gives its origin", good, "https://play.example.test"),
        ("attribute order does not matter", flipped, "https://play.example.test"),
        ("relative endpoint (the incident) resolves to the site", bad, base),
        ("no mount gives None", "<p>hi</p>", None),
    )
    failed = 0
    for label, html, want in cases:
        if page_play_origin(html, page) == want:
            print(f"  ok   {label}")
        else:
            failed += 1
            print(f"FAIL   {label}")
    # The incident page must be red against the expected origin.
    if page_play_origin(bad, page) != "https://play.example.test":
        print("  ok   the incident page differs from the expected origin")
    else:
        failed += 1
        print("FAIL   the incident page differs from the expected origin")
    return failed


def self_test_flash_miss():
    """Drive the real five-request check, proving each corrupt answer is red."""
    import copy
    import io
    from contextlib import redirect_stdout
    from unittest.mock import patch

    counts = flash_call_counts()
    expected = (SAMPLES / "flash_attn.out").read_text()
    source = (SAMPLES / "flash_attn.dawn").read_text()
    good = {
        ("check", None): {"ok": True, "phase": "check"},
        ("run", None): {"ok": True, "phase": "run", "exit": 0,
                        "output": expected, "truncated": False},
    }
    for target, count in counts.items():
        good["compile", target] = {
            "ok": True, "phase": "compile-view", "target": target, "cached": False,
            "calls_total": count, "calls": [{}] * count, "calls_truncated": False,
            "pane": {"kind": target, "outs": [{}] * count},
            "gaps": {"count": 0, "first": []},
        }
    cases = [("cold flash responses pass", None, {})]
    cases += [
        ("stale stdout fails", ("run", None), {"output": expected + "stale\n"}),
        ("nonzero exit fails", ("run", None), {"exit": 1}),
    ]
    for key in good:
        cases.append((f"cached {key} fails", key, {"cached": True}))
    for target in counts:
        key = ("compile", target)
        cases += [
            (f"wrong {target} call count fails", key, {"calls_total": counts[target] + 1}),
            (f"truncated {target} calls fail", key, {"calls": good[key]["calls"][:-1]}),
            (f"unmapped {target} spans fail", key, {"unmapped": "unmapped source spans"}),
            (f"{target} gaps fail", key, {"gaps": {"count": 1, "first": ["lost span"]}}),
        ]
    failed = 0
    for label, key, change in cases:
        responses = copy.deepcopy(good)
        if key:
            responses[key].update(change)
        requests = []

        def post(api, route, payload, timeout, deadline):
            requests.append((api, route, payload, timeout, deadline))
            return responses[route, payload.get("target")]

        result = Results()
        with patch(__name__ + ".post_json", post), redirect_stdout(io.StringIO()):
            check_flash_miss("http://runner.example.test", result, 0)
        codes = {req[2]["code"] for req in requests}
        coherent = ([(req[1], req[2].get("target")) for req in requests] == list(good)
                    and len(codes) == 1
                    and all(req[0] == "http://runner.example.test" for req in requests)
                    and all(req[3] == FLASH_MISS_REQUEST_SECS for req in requests)
                    and len({req[4] for req in requests}) == 1)
        if coherent:
            code = codes.pop()
            suffix = code[len(source):]
            coherent = (code.startswith(source) and suffix.startswith("# live-check cache miss ")
                        and len(suffix.splitlines()) == 1)
        ok = coherent and result.failed == (1 if key else 0) and result.passed + result.failed == 5
        print(f"  ok   {label}" if ok else f"FAIL   {label}")
        failed += not ok

    # No real wait or network: an expired budget must stop before opening a
    # connection, and a 429 must not sleep past the remaining shared budget.
    for label, remaining in [("expired miss budget fails", -1),
                             ("429 cannot outwait miss budget", 1)]:
        busy = urllib.error.HTTPError("http://runner.example.test/check", 429, "busy", {}, None)
        with patch.object(OPENER, "open", side_effect=busy) as opening, patch("time.sleep") as sleeping:
            try:
                post_json("http://runner.example.test", "check", {}, FLASH_MISS_REQUEST_SECS,
                          time.monotonic() + remaining)
                ok = False
            except TimeoutError:
                ok = (opening.call_count == (0 if remaining < 0 else 1)
                      and not sleeping.called)
        print(f"  ok   {label}" if ok else f"FAIL   {label}")
        failed += not ok
    return failed


def self_test():
    """The sample comparison, offline: what it forgives and what it still catches."""
    out = b"caught: boom at barriers.dawn:50:46\n"
    cases = (
        # (label, sample name, expected, actual, should match)
        ("own name becomes prog.dawn", "barriers.dawn", out,
         b"caught: boom at prog.dawn:50:46\n", True),
        ("no position, no rewrite", "hello.dawn", b"hello\n", b"hello\n", True),
        ("a different line stays red", "barriers.dawn", out,
         b"caught: boom at prog.dawn:51:46\n", False),
        ("a different column stays red", "barriers.dawn", out,
         b"caught: boom at prog.dawn:50:47\n", False),
        ("the sample's own name in the output stays red", "barriers.dawn", out,
         out, False),
        ("another sample's name is not rewritten", "hello.dawn", out,
         b"caught: boom at prog.dawn:50:46\n", False),
        ("a longer name ending in it is not rewritten", "barriers.dawn",
         b"at my_barriers.dawn:50:46\n", b"at my_prog.dawn:50:46\n", False),
        ("the name without a position is not rewritten", "barriers.dawn",
         b"see barriers.dawn\n", b"see prog.dawn\n", False),
        ("the name before a colon but no line is not rewritten", "barriers.dawn",
         b"barriers.dawn: done\n", b"prog.dawn: done\n", False),
        ("other text still differs", "barriers.dawn", out,
         b"caught: bang at prog.dawn:50:46\n", False),
    )
    failed = 0
    for label, name, expected, actual, should in cases:
        if sample_matches(name, expected, actual) != should:
            failed += 1
            print(f"FAIL   {label}")
        else:
            print(f"  ok   {label}")
    # Negative control: the byte-for-byte comparison this replaced fails the
    # first case, which is the failure the deploy of 2026-10-04 saw.
    label, name, expected, actual, _ = cases[0]
    if sample_matches(name, expected, actual, rewrite=lambda _n, e: e):
        failed += 1
        print("FAIL   the comparison without the rewrite turns the first case red")
    else:
        print("  ok   the comparison without the rewrite turns the first case red")
    # The tree's own sample that names a position, so a renamed sample or
    # a re-recorded .out cannot leave the cases above about nothing.
    barriers = (SAMPLES / "barriers.out").read_bytes()
    rewritten = playground_expected("barriers.dawn", barriers)
    if rewritten == barriers or b"barriers.dawn:" in rewritten:
        failed += 1
        print("FAIL   barriers.out names its own file and every mention is rewritten")
    else:
        print("  ok   barriers.out names its own file and every mention is rewritten")
    flash = (SAMPLES / "flash_attn.dawn").read_text()
    stale = flash.replace("fa_kernel(BF16, fa_bf16_math())", "fa_kernel(F64, fa64_math())")
    for label, text, should in [
        ("template current flash sample", "`" + flash.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${") + "`", True),
        ("escaped current flash sample", json.dumps(flash, ensure_ascii=False), True),
        ("old reader wiring in bundle", json.dumps(stale), False),
        ("current source prefix in changed bundle", json.dumps(flash + "# drift"), False),
        ("changed flash source in bundle", json.dumps(flash.replace("plain attention mixed precision check passed", "old stdout")), False),
    ]:
        if current_flash_in_bundle(text) != should:
            failed += 1
            print(f"FAIL   {label}")
        else:
            print(f"  ok   {label}")
    failed += self_test_page()
    failed += self_test_flash_miss()
    print(f"\nself-test: {failed} failed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="run the sample comparison's offline cases and exit",
    )
    ap.add_argument(
        "--runner-only",
        action="store_true",
        help="check only the runner, and talk to it directly (no /api prefix, no static site)",
    )
    ap.add_argument(
        "--page-file",
        help="check this saved playground page instead of fetching one (implies --page-only)",
    )
    ap.add_argument(
        "--page-only",
        action="store_true",
        help="run only the check of what the playground page points at",
    )
    args = ap.parse_args()
    if args.self_test:
        return self_test()

    base = os.environ.get("PLAY_BASE_URL", DEFAULT_BASE).rstrip("/")
    api = base if args.runner_only else DEFAULT_API
    api = os.environ.get("PLAY_API_URL", api).rstrip("/")

    r = Results()
    if args.page_file or args.page_only:
        expect = os.environ.get("PLAY_EXPECT_ORIGIN", DEFAULT_PLAY_ORIGIN).rstrip("/")
        check_page(base, expect, r, args.page_file)
        print(f"\n{r.passed} passed, {r.failed} failed")
        return 1 if r.failed else 0

    # A bare runner has no nginx in front of it, so nothing to pace for.
    check_runner(api, r, 0.0 if args.runner_only else RUN_PACE_SECS)
    if not args.runner_only:
        check_site(base, r)
        expect = os.environ.get("PLAY_EXPECT_ORIGIN", DEFAULT_PLAY_ORIGIN).rstrip("/")
        check_page(base, expect, r)

    print(f"\n{r.passed} passed, {r.failed} failed")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
