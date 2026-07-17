#!/usr/bin/env python3
"""Guard: commit messages must not carry Claude attribution.

The convention (CLAUDE.md, 重要约定) is that neither `Co-Authored-By: Claude`
nor `Claude-Session: <url>` trailers belong in this open-source repo. Claude Code
suppresses them at the settings source (attribution.commit=""), but that is
per-machine and per-session: a different machine, or a session whose system
prompt insists, will slip them back in. A batch of such trailers once had to be
force-pushed out of history. This is the backstop that does not depend on who
committed — the `commit-msg` hook catches it locally, CI catches it once pushed
(the hook is opt-in per machine, so the CI half is not redundant).

Two entry points:
  check-no-claude-trailer.py --commit-msg <file>   # one prospective message (commit-msg hook)
  check-no-claude-trailer.py --range <A..B>        # every message in a git rev-range (CI)
"""

import argparse
import re
import subprocess
import sys

# Only Claude/Anthropic Co-Authored-By lines are rejected — a real human
# co-author is legitimate and left alone. Anchored at line start so a message
# body that merely mentions the phrase is not a false positive.
PATTERNS = [
    re.compile(r"^\s*Claude-Session\s*:", re.I),
    re.compile(r"^\s*Co-authored-by\s*:.*(claude|anthropic)", re.I),
]


def offenders(msg: str) -> list[str]:
    """Return the offending lines (stripped) found in a message."""
    hits = []
    for line in msg.splitlines():
        if any(p.search(line) for p in PATTERNS):
            hits.append(line.strip())
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--commit-msg", metavar="FILE", help="prospective message file (from the commit-msg hook)")
    src.add_argument("--range", metavar="A..B", help="git rev-range; check every commit message in it")
    args = ap.parse_args()

    problems = []  # (label, offending line)
    if args.commit_msg:
        with open(args.commit_msg, encoding="utf-8") as f:
            for line in offenders(f.read()):
                problems.append(("staged", line))
    else:
        # %x1f separates sha from body, %x00 separates commits — neither can occur
        # inside a commit message.
        out = subprocess.run(
            ["git", "log", "--format=%H%x1f%B%x00", args.range],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for rec in out.split("\x00"):
            rec = rec.strip("\n")
            if not rec:
                continue
            sha, _, msg = rec.partition("\x1f")
            for line in offenders(msg):
                problems.append((sha[:8], line))

    if problems:
        sys.stderr.write("Claude attribution in commit message (CLAUDE.md 重要约定: never add it):\n")
        for label, line in problems:
            sys.stderr.write(f"  {label}: {line}\n")
        sys.stderr.write("\nRemove these trailers before committing; for history already written, rebase them out.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
