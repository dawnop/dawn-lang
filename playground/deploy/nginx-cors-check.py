#!/usr/bin/env python3
"""Checks that every runner route in nginx-play.conf sends the CORS headers
the live Playground sends.

    nginx-cors-check.py [nginx-play.conf ...]   # default: the shipped snippet; - reads stdin
    nginx-cors-check.py --self-test

Why this exists: the site pages are on a CDN and call the Playground API on
another origin, so a runner route without CORS is a route the site cannot
use, and the browser reports it as a bare network error, not as a 4xx anyone
would notice. The snippet repeats the headers in every location on purpose
(add_header is not inherited into a location that sets its own, and the
preflight `if` replaces the location's set), and a copied block is exactly
where a new route arrives without them. An `include` of one shared file would
remove the copies, but it adds a second file the operator has to install on
the server beside the hand-kept vhost, for a five-line block; this check keeps
the copies equal instead.

What is asserted is what production answered on 2026-10-12 (recorded in
playground/deploy/DEPLOY.md):

- Every location that proxies to the runner (its unix socket; the JVM
  runner's loopback port is gone since K5 and no longer counts as one)
  carries, at location level,
  exactly `Access-Control-Allow-Origin $play_cors always` and
  `Vary Origin always`, and an `if ($request_method = OPTIONS)` block holding
  exactly the five preflight headers below and `return 204`.
- /api/lsp, the WebSocket gateway, carries no add_header at all: it checks
  Origin itself.
- Every route the runner answers (`allowed` in playground/src/play/serve.dawn) has a
  `location = /api/<route>` here, so a new runner route cannot ship without
  an nginx location (and so without CORS).

Origin filtering is not asserted here: it is the `$play_cors` map in the http
block, which lives outside this snippet. Standard library only.
"""

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CONF = HERE / "nginx-play.conf"
RUNNER_MAIN = HERE.parent / "src" / "play" / "serve.dawn"

SIMPLE = {
    ("Access-Control-Allow-Origin", "$play_cors", "always"),
    ("Vary", "Origin", "always"),
}
PREFLIGHT = SIMPLE | {
    ("Access-Control-Allow-Methods", '"POST, GET, OPTIONS"', "always"),
    ("Access-Control-Allow-Headers", '"Content-Type"', "always"),
    ("Access-Control-Max-Age", "600", "always"),
}
RUNNER_UPSTREAM = re.compile(r"proxy_pass\s+http://unix:[^:;]+:/")
GATEWAY = "/api/lsp"


def strip_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def blocks(text, opener):
    """(header, body) for every `opener` match, which must end at its `{`."""
    out = []
    for m in re.finditer(opener, text):
        start = m.end() - 1
        depth, i = 0, start
        while True:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append((m.group(1), text[start + 1 : i]))
    return out


def add_headers(body):
    """Each add_header as a tuple of its arguments, a quoted argument kept whole."""
    return [
        tuple(re.findall(r'"[^"]*"|\S+', m.group(1)))
        for m in re.finditer(r"\badd_header\s+([^;]+);", body)
    ]


def runner_routes(serve_text):
    """The paths of serve.dawn's `allowed`: `"/run" -> Some("POST")` lines."""
    return set(re.findall(r'^\s*"(/[^"]*)" -> Some\("(?:GET|POST)"\)', serve_text, re.M))


def check(conf_text, main_text):
    """Returns a list of problems; empty means the snippet is as production is."""
    problems = []
    text = strip_comments(conf_text)
    locations = blocks(text, r"\blocation\s+=\s+(\S+)\s*\{")
    seen = {path for path, _ in locations}
    for route in sorted(runner_routes(main_text)):
        if "/api" + route not in seen:
            problems.append(f"runner route {route} has no `location = /api{route}`")
    if not locations:
        problems.append("no `location = ...` blocks found")
    for path, body in locations:
        ifs = blocks(body, r"\bif\s+(\(\$request_method\s*=\s*OPTIONS\))\s*\{")
        outer = body
        for _, inner in ifs:
            outer = outer.replace(inner, "")
        if path == GATEWAY:
            if add_headers(body):
                problems.append(f"{path}: the WebSocket gateway must carry no add_header")
            continue
        if not RUNNER_UPSTREAM.search(body):
            problems.append(f"{path}: neither the runner nor the gateway; classify it here")
            continue
        got = add_headers(outer)
        if set(got) != SIMPLE or len(got) != len(SIMPLE):
            problems.append(f"{path}: location-level CORS headers are {sorted(got)}, want {sorted(SIMPLE)}")
        if len(ifs) != 1:
            problems.append(f"{path}: want exactly one `if ($request_method = OPTIONS)` preflight block, found {len(ifs)}")
            continue
        inner = ifs[0][1]
        got = add_headers(inner)
        if set(got) != PREFLIGHT or len(got) != len(PREFLIGHT):
            problems.append(f"{path}: preflight headers are {sorted(got)}, want {sorted(PREFLIGHT)}")
        if not re.search(r"\breturn\s+204\s*;", inner):
            problems.append(f"{path}: preflight does not `return 204`")
    return problems


def self_test():
    conf = CONF.read_text()
    main = RUNNER_MAIN.read_text()
    assert check(conf, main) == [], check(conf, main)
    compile_at = conf.index("location = /api/compile")
    health_at = conf.index("location = /api/health")
    lsp_at = conf.index("location = /api/lsp")
    run_at = conf.index("location = /api/run")

    def after(at, old, new):
        return conf[:at] + conf[at:].replace(old, new, 1)

    acao = "    add_header Access-Control-Allow-Origin $play_cors always;\n"
    mutants = {
        "simple ACAO dropped on /api/compile": after(
            compile_at, acao + "    add_header Vary", "    add_header Vary"),
        "preflight Max-Age dropped on /api/health": after(
            health_at, "        add_header Access-Control-Max-Age 600 always;\n", ""),
        "`always` dropped on /api/compile": after(
            compile_at, "$play_cors always;", "$play_cors;"),
        "preflight returns 200 on /api/health": after(health_at, "return 204;", "return 200;"),
        "preflight block removed from /api/compile": re.sub(
            r"(location = /api/compile \{\n).*?return 204;\n    \}\n", r"\1", conf, count=1, flags=re.S),
        "CORS added to the gateway": after(
            lsp_at, "    limit_req zone=playlsp", acao + "    limit_req zone=playlsp"),
        "location for /api/health removed": conf[:health_at],
        "/api/run sent back to the JVM runner's port": after(
            run_at, "http://unix:/run/dawn-play/http.sock:/run;", "http://127.0.0.1:8087/run;"),
    }
    for name, mutant in mutants.items():
        assert mutant != conf, f"mutant did not apply: {name}"
        assert check(mutant, main), f"mutant passed: {name}"
    assert runner_routes(main) == {"/run", "/check", "/compile", "/health"}, runner_routes(main)
    new_route = main.replace('    "/health" -> Some("GET")', '    "/version" -> Some("GET")\n    "/health" -> Some("GET")', 1)
    assert new_route != main, "the new-route mutant did not apply"
    assert check(conf, new_route), "a new runner route without a location passed"
    print(f"nginx-cors-check self-test: shipped snippet passes, {len(mutants) + 1} mutants fail")


def main(argv):
    if argv == ["--self-test"]:
        self_test()
        return 0
    main_text = RUNNER_MAIN.read_text()
    bad = 0
    for p in argv or [str(CONF)]:
        text = sys.stdin.read() if p == "-" else pathlib.Path(p).read_text()
        for problem in check(text, main_text):
            print(f"{p}: {problem}", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
