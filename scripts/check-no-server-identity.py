#!/usr/bin/env python3
"""Guard: this public repo must not carry the deploy server's identity.

dawn-lang deploys to the same host as dawnop-site (dawnop.com). The redeploy
scripts once hardcoded the ssh login as `user@dawnop.com`; it lived in history
(and in the v0.1.0 tag) until a 2026-07-18 cleanup. The convention is that the
server's real IP and ssh login name stay in a private note — the tree writes
`<user>@<server>` and the scripts read `$DEPLOY_USER`. A convention nothing
checks decays, so this is a check now (CI `secrets` job + local pre-push hook).

Four checks, different in kind:

* ssh login name (genuinely private): the user@host in ssh/scp/rsync commands.
  Only the *username* is secret — a placeholder host (`<server>`) does NOT make
  it safe, so `ssh dawn@<server>` is still a leak. No network needed.
* server IP (not really secret): `dig dawnop.com` returns it. Kept only for
  consistency, not as a security boundary. Resolved live from the site's own
  domains instead of hardcoded, so the guard isn't itself the thing it guards.
* bypass-service identity: the dev proxy tunnel's host / component / port. Held
  base64-encoded below so this public file does not spell them out in plaintext
  (else GitHub search reads them straight off the guard). Decoded at runtime.
* repository and site coordinates (public, but named once): the GitHub path
  and the site's host are written in scripts/repo.env and nowhere else that a
  program reads them, so that moving either is one edit. A copy spelled out
  under scripts/, playground/, site/src, site/*.sh or .github/ is red unless
  COORDINATE_ALLOWED below lists that exact line with a reason; an allowance
  that no longer matches its line is red too, so the list cannot outlive what
  it excuses. The Dawn site generator keeps its own copies (site_origin() and
  repo_url() in site/src/html/page.dawn, it cannot read a shell file), and
  this holds them equal to repo.env. Public prose (README, docs/, site/pages,
  editors/vscode/package.json) keeps its links literal and is not scanned.
"""

import base64
import ipaddress
import re
import socket
import subprocess
import sys
import urllib.parse

import repo_env  # scripts/repo_env.py, the reader of scripts/repo.env

# The coordinates as the file has them, not as the environment may override
# them: the guard looks for the copies of what is checked in.
COORDINATES = repo_env.read()
GITHUB_REPO = COORDINATES["DAWN_GITHUB_REPO"]
SITE_ORIGIN = COORDINATES["DAWN_SITE_ORIGIN"]
SITE_HOST = urllib.parse.urlsplit(SITE_ORIGIN).hostname

# The site's own domains. Whatever they resolve to is what must not appear.
OWN_DOMAINS = ["dawnop.com", SITE_HOST]

# Where a program could read a copy of the coordinates.
COORDINATE_SCAN = ("scripts/", "playground/", "site/src/", ".github/")
COORDINATE_SCAN_SHELL = re.compile(r"site/[^/]+\.sh")

# (path, the exact line, why it stays). The line is matched after stripping
# surrounding whitespace, so an edit to it has to come back here.
COORDINATE_ALLOWED = [
    ("scripts/repo.env", f"DAWN_GITHUB_REPO={GITHUB_REPO}",
     "the definition"),
    ("scripts/repo.env", f"DAWN_SITE_ORIGIN={SITE_ORIGIN}",
     "the definition"),
    ("site/src/html/page.dawn",
     f'pub fn site_origin() -> String = "{SITE_ORIGIN}/"',
     "the Dawn generator's one copy of the origin, held equal below"),
    ("site/src/html/page.dawn",
     f'pub fn repo_url() -> String = "https://github.com/{GITHUB_REPO}"',
     "the Dawn generator's one copy of the repository, held equal below"),
    ("site/src/gen/home.dawn",
     f'fn release_base() -> String = "https://github.com/{GITHUB_REPO}/releases/latest/download"',
     "doc-check.py reads the install commands by spelling (SITE_INSTALL_SOURCES) and"
     " compares them with RELEASE_ASSET_BASE, itself built from repo.env"),
    ("playground/deploy/DEPLOY.md",
     f"`server {{ server_name {SITE_HOST}; … }}`, and all listed",
     "operator prose naming the nginx server block, which lives outside this repository"),
    ("playground/deploy/nginx-play.conf",
     f"# `server {{ server_name {SITE_HOST}; ... }}` block (the static site is",
     "a comment naming the nginx server block, which lives outside this repository"),
]

# Recorded measurements say which repository they measured; no program reads
# that back, and rewriting a record changes what it records.
COORDINATE_RECORDED = re.compile(r".*/baselines/[^/]+\.json")

IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

# user@host inside an ssh/scp/rsync command.
USER_AT_HOST = re.compile(
    r"\b(?:ssh|scp|rsync)\b[^\n]*?\b([a-z_][a-z0-9_-]{0,31})@([A-Za-z0-9.<>-]+)"
)

# Placeholders and generic account names that are fine in the open.
ALLOWED_USERS = {"user", "root", "git"}

# Bypass-service identity patterns, base64-encoded so this public file does not
# contain the literals it forbids. Each item: (base64(regex-source), ignorecase).
_ENCODED_TERMS = [
    (b"cHJveHlcLmRhd25vcFwuY29t", False),
    (b"XGJnb3N0XGI=", True),
    (b"XGJtaWhvbW9cYg==", True),
    (b"XGIxODQ0M1xi", False),
    (b"56m/5aKZfOe/u+WimQ==", False),
    (b"c3NsX3ByZXJlYWQ=", False),
]
FORBIDDEN_TERMS = [
    re.compile(base64.b64decode(b).decode(), re.IGNORECASE if ic else 0)
    for b, ic in _ENCODED_TERMS
]

TEXT_SUFFIXES = (
    ".md",
    ".txt",
    ".sh",
    ".py",
    ".kt",
    ".kts",
    ".java",
    ".gradle",
    ".dawn",
    ".ts",
    ".js",
    ".mjs",
    ".vue",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".conf",
    ".service",
    ".properties",
    ".html",
    ".css",
    ".example",
)

SELF = "check-no-server-identity"


def own_ips(*, require_network: bool) -> set[str]:
    """Resolve the site's domains to their IPs.

    On failure: strict mode (CI / pre-push, already online) aborts — silently
    skipping would turn the check off without anyone noticing. Lenient mode
    (pre-commit, possibly offline) warns and skips only the IP check, returning
    an empty set so the username + bypass-term checks still run. The IP is
    DNS-discoverable and pre-push catches it anyway, so missing it offline is
    fine."""
    socket.setdefaulttimeout(3)  # commit-time hook: don't let a flaky net hang commits
    found: set[str] = set()
    errors: list[str] = []
    for d in OWN_DOMAINS:
        try:
            for info in socket.getaddrinfo(d, None, socket.AF_INET):
                ip = info[4][0]
                if not ipaddress.IPv4Address(ip).is_private:
                    found.add(ip)
        except OSError as e:
            errors.append(f"{d}: {e}")
    if not found:
        msg = "none of the site's domains resolved, IP check cannot run:\n  " + "\n  ".join(errors)
        if require_network:
            print("error: " + msg, file=sys.stderr)
            sys.exit(2)
        print(
            "warning: " + msg + "\n  -- offline mode, skipping IP check; username + bypass terms still run.",
            file=sys.stderr,
        )
    return found


def tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.split("\0") if f and f.endswith(TEXT_SUFFIXES)]


def coordinate_hits(paths: list[str]) -> list[str]:
    """Copies of the repository or site coordinates outside repo.env."""
    needles = (GITHUB_REPO, SITE_HOST)
    allowed: dict[tuple[str, str], bool] = {
        (path, line): False for path, line, _why in COORDINATE_ALLOWED}
    hits: list[str] = []
    for path in paths:
        if not (path.startswith(COORDINATE_SCAN) or COORDINATE_SCAN_SHELL.fullmatch(path)):
            continue
        if COORDINATE_RECORDED.fullmatch(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            if not any(needle in line for needle in needles):
                continue
            key = (path, line.strip())
            if key in allowed:
                allowed[key] = True
                continue
            hits.append(f"{path}:{n}: the repository or site coordinate spelled out --"
                        " read DAWN_GITHUB_REPO / DAWN_SITE_ORIGIN (scripts/repo.env)")
    for (path, line), seen in allowed.items():
        if not seen:
            hits.append(f"{path}: COORDINATE_ALLOWED excuses a line that is not there"
                        f" any more: {line!r}")

    # The Dawn generator's copies say what repo.env says.
    page = "site/src/html/page.dawn"
    try:
        text = open(page, encoding="utf-8").read()
    except OSError:
        text = ""
    for fn, want in (("site_origin", f"{SITE_ORIGIN}/"),
                     ("repo_url", f"https://github.com/{GITHUB_REPO}")):
        got = re.findall(rf'^pub fn {fn}\(\) -> String = "([^"]*)"$', text, re.M)
        if got != [want]:
            hits.append(f"{page}: {fn}() should be {want!r} as scripts/repo.env"
                        f" says, found {got}")
    return hits


def main() -> int:
    # pre-commit passes --allow-offline: skip the IP check when offline instead
    # of blocking the commit. Default is strict (CI / pre-push / manual runs):
    # abort if resolution fails.
    require_network = "--allow-offline" not in sys.argv
    ips = own_ips(require_network=require_network)
    hits: list[str] = []
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout.split("\0")
    coordinates = coordinate_hits([f for f in tracked if f])

    for path in tracked_text_files():
        if SELF in path:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue

        for n, line in enumerate(lines, 1):
            if SELF in line:
                continue
            for m in IPV4.finditer(line):
                if m.group(0) in ips:
                    hits.append(f"{path}:{n}: server IP `{m.group(0)}` -- use <server>")
            for m in USER_AT_HOST.finditer(line):
                user, host = m.group(1), m.group(2)
                # Only the username matters: a placeholder host does not exempt
                # it. `dawn@<server>` leaks the username even with a fake host.
                if user in ALLOWED_USERS or "example" in host:
                    continue
                hits.append(
                    f"{path}:{n}: ssh login `{user}@{host}` -- username should be <user>"
                )
            for pat in FORBIDDEN_TERMS:
                if pat.search(line):
                    hits.append(
                        f"{path}:{n}: bypass-service identity -- keep it in the "
                        "private note, not this repo"
                    )

    if coordinates:
        print("repository or site coordinates outside scripts/repo.env:\n", file=sys.stderr)
        for h in coordinates:
            print(f"  {h}", file=sys.stderr)
        print(
            "\nThe repository's GitHub path and the site's origin are named once, in"
            " scripts/repo.env;\nscripts source it (sh) or import scripts/repo_env.py"
            " (Python). A line that must stay\nliteral goes in COORDINATE_ALLOWED with"
            " its reason.",
            file=sys.stderr,
        )
        if not hits:
            return 1

    if hits:
        print("server identity leaked into the public repo:\n", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        print(
            "\nConvention: real IP / ssh username / bypass identity live only in a "
            "private note; write <user>@<server> and read $DEPLOY_USER in scripts.",
            file=sys.stderr,
        )
        return 1

    if coordinates:
        return 1
    print(f"ok: compared against {len(ips)} site address(es), no server identity found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
