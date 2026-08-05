#!/usr/bin/env python3
"""Check a *deployed* Playground against the samples in the tree.

`scripts/doc-check.py` already runs `site/play-ui/samples/*.dawn` with the local
compiler and compares stdout with the `.out` beside each one. Nothing checked
the same thing against the *server*, and that gap is not hypothetical: the
sidebar shipped a `fn`-prefixed lambda the compiler had rejected for eight
releases, and the deployed runner sat thirteen days behind the tree, each half
consistent with the other and both wrong. Two things have to agree here that
`doc-check` cannot compare: the compiler the server runs, and the bundle nginx
serves.

Usage:

    scripts/play-live-check.py                  # the public deployment
    PLAY_BASE_URL=http://127.0.0.1:18087 scripts/play-live-check.py --runner-only

`PLAY_BASE_URL` points at the site root (`/api/run` is appended); a bare runner
with no nginx in front wants `--runner-only`, which skips the static checks and
drops the `/api` prefix. Exit status is 0 only when every check passed.

No server identity here: the public hostname is public, the ssh login is not
(see scripts/check-no-server-identity.py) -- this script never needs to log in.
"""

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "site" / "play-ui" / "samples"
DEFAULT_BASE = "https://dawn-lang.dawnop.com"

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


def post_run(api, code, timeout=120):
    """POST one program to /run, waiting out rate limiting. Returns decoded JSON."""
    req = urllib.request.Request(
        f"{api}/run",
        data=json.dumps({"code": code}).encode(),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(RUN_429_RETRIES):
        try:
            with OPENER.open(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == RUN_429_RETRIES - 1:
                raise
            time.sleep(RUN_PACE_SECS * (attempt + 1))
    raise RuntimeError("unreachable")


def get(url, timeout=30):
    """GET a URL. Returns (status, body-bytes, final-url); never raises on HTTP error."""
    try:
        with OPENER.open(urllib.request.Request(url), timeout=timeout) as resp:
            return resp.status, resp.read(), resp.url
    except urllib.error.HTTPError as e:
        return e.code, e.read(), url


def check_runner(api, r, pace):
    print(f"== runner: {api} ==")

    status, body, _ = get(f"{api}/health")
    r.check(status == 200 and body.strip() == b"ok", "/health -> ok", f"{status} {body!r}")

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
        r.check(
            actual == expected,
            name,
            "" if actual == expected else f"expected {expected!r}\ngot      {actual!r}",
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
        r.check(
            "fn(c) => c.name" not in text,
            "bundle no longer carries the retired `fn(c) =>` spelling",
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--runner-only",
        action="store_true",
        help="check only the runner, and talk to it directly (no /api prefix, no static site)",
    )
    args = ap.parse_args()

    base = os.environ.get("PLAY_BASE_URL", DEFAULT_BASE).rstrip("/")
    api = base if args.runner_only else base + "/api"

    # A bare runner has no nginx in front of it, so nothing to pace for.
    r = Results()
    check_runner(api, r, 0.0 if args.runner_only else RUN_PACE_SECS)
    if not args.runner_only:
        check_site(base, r)

    print(f"\n{r.passed} passed, {r.failed} failed")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
