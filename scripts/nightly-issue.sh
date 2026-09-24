#!/usr/bin/env bash
# Turn a red scheduled check into an issue, once per title.
#
#   scripts/nightly-issue.sh "<fixed title>" <body file>
#
# Why: a scheduled run blocks nothing, so a red one that only paints the
# Actions page is a red nobody sees. Rust's reference repository runs its
# grammar check on the same arrangement -- the check runs on a schedule, and a
# failure opens "Daily Grammar Check Failed - <date>" (rust-lang/reference
# #2332, #2359). Here the title is fixed rather than
# dated: while an issue with the same title is open, a new failure is a
# comment on it, not a second issue, so a check that stays red for a week is
# one thread with seven entries rather than seven threads.
#
# The match is on the exact title among open issues. `gh issue list --search`
# is a full-text search and would also match a longer title that contains
# this one, so the listing is filtered again here.
#
# Needs GH_TOKEN with `issues: write`; the calling job declares it.
set -euo pipefail

if [ $# -ne 2 ] || [ ! -f "$2" ]; then
  echo "usage: $0 <title> <body file>" >&2
  exit 2
fi
# The title is spliced into a jq program below; gh's --jq takes no --arg.
case $1 in
  *\"* | *\\*) echo "error: the title may not contain \" or \\" >&2; exit 2 ;;
esac
title=$1
body=$2
repo=${GITHUB_REPOSITORY:-dawnop/dawn-lang}

number=$(gh issue list --repo "$repo" --state open --limit 100 \
  --search "in:title \"$title\"" --json number,title \
  --jq "map(select(.title == \"$title\")) | .[0].number // empty")

if [ -n "$number" ]; then
  gh issue comment "$number" --repo "$repo" --body-file "$body"
  echo "commented on #$number ($title)"
else
  gh issue create --repo "$repo" --title "$title" --body-file "$body"
fi
