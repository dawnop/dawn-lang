"""The one Python reader of scripts/repo.env.

Why a module and not a line in each script: repo.env is the single place the
repository's GitHub path and the site's origin are written, and three kinds of
reader parse it (POSIX sh sources it, systemd reads it as an EnvironmentFile,
and Python reads it here). One parser per language keeps them agreeing on the
format; a copy per script would be eight chances to disagree.

Precedence is a non-empty environment variable of the same name, then the
file. GITHUB_REPOSITORY is deliberately not consulted here: the seed
downloads read the repository through the same name, and in a fork's Actions
run GITHUB_REPOSITORY names a fork with no releases. A script that acts on
the repository a workflow runs in (nightly-issue.sh, the --repo flags in
nightly.yml and tile.yml) passes GITHUB_REPOSITORY itself.

The programs under playground/ that ship to the server run with `python3 -I`,
which keeps their own directory off sys.path, so they load this file by path
through importlib from the deployed root; playground/deploy/redeploy.sh
ships the two files to that root's scripts/.
"""

import os
import re
from pathlib import Path

ENV_FILE = Path(__file__).resolve().with_name("repo.env")

# What all three readers take the same way: no quoting, no expansion, no space.
_LINE = re.compile(r"([A-Z][A-Z0-9_]*)=([^\s\"'$`\\]+)")


def read(path=ENV_FILE):
    """Every KEY=VALUE in the file, refusing a line the readers would split."""
    values = {}
    for n, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.startswith("#"):
            continue
        m = _LINE.fullmatch(raw)
        if not m:
            raise SystemExit(f"{path}:{n}: not a plain KEY=VALUE line: {raw!r}")
        values[m.group(1)] = m.group(2)
    return values


def get(name, path=ENV_FILE):
    value = os.environ.get(name, "")
    if value:
        return value
    values = read(path)
    if name not in values:
        raise SystemExit(f"{path}: no {name}")
    return values[name]


def github_repo():
    """`owner/name` of the GitHub repository, e.g. for releases and the API."""
    return get("DAWN_GITHUB_REPO")


def site_origin():
    """The public site's origin, scheme and host, no trailing slash."""
    return get("DAWN_SITE_ORIGIN")

