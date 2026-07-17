#!/usr/bin/env python3
"""Guard: this public repo must not carry the deploy server's identity.

dawn-lang deploys to the same host as dawnop-site (dawnop.com). The redeploy
scripts once hardcoded the ssh login as `user@dawnop.com`; it lived in history
(and in the v0.1.0 tag) until a 2026-07-18 cleanup. The convention is that the
server's real IP and ssh login name stay in a private note — the tree writes
`<user>@<server>` and the scripts read `$DEPLOY_USER`. A convention nothing
checks decays, so this is a check now (CI `secrets` job + local pre-push hook).

Three checks, different in kind:

* ssh login name (genuinely private): the user@host in ssh/scp/rsync commands.
  Only the *username* is secret — a placeholder host (`<server>`) does NOT make
  it safe, so `ssh dawn@<server>` is still a leak. No network needed.
* server IP (not really secret): `dig dawnop.com` returns it. Kept only for
  consistency, not as a security boundary. Resolved live from the site's own
  domains instead of hardcoded, so the guard isn't itself the thing it guards.
* bypass-service identity: the dev proxy tunnel's host / component / port. Held
  base64-encoded below so this public file does not spell them out in plaintext
  (else GitHub search reads them straight off the guard). Decoded at runtime.
"""

import base64
import ipaddress
import re
import socket
import subprocess
import sys

# The site's own domains. Whatever they resolve to is what must not appear.
OWN_DOMAINS = ["dawnop.com", "dawn-lang.dawnop.com"]

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


def own_ips() -> set[str]:
    """Resolve the site's domains. Abort if none resolve — silently skipping
    would turn the check off without anyone noticing."""
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
        print(
            "error: none of the site's domains resolved, IP check cannot run:\n  "
            + "\n  ".join(errors),
            file=sys.stderr,
        )
        sys.exit(2)
    return found


def tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    return [f for f in out.split("\0") if f and f.endswith(TEXT_SUFFIXES)]


def main() -> int:
    ips = own_ips()
    hits: list[str] = []

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

    print(f"ok: compared against {len(ips)} site address(es), no server identity found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
