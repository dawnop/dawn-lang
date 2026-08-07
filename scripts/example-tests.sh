#!/usr/bin/env bash
# Run the test blocks of every example.
#
# Discovery, not a list. The gate this replaced named two files by hand, so the
# other eleven examples carried assertions nothing ever executed -- and a new
# example joined them by default, silently, because forgetting to extend a list
# looks exactly like not having written one. Here a file that exists is a file
# that runs, and the only way to leave an example untested is to delete it.
#
# The unit rule is the site generator's (site/src/gen/examples.dawn): under
# examples/<group>/, a directory with a src/ in it is one multi-module project,
# and any other .dawn file is one program.
#
# `dawn test` errors on a file with no test blocks rather than passing
# vacuously, which is the behaviour this script wants: an example with nothing
# to assert is a gap, and it reds here instead of being skipped.
set -euo pipefail

cd "$(dirname "$0")/.."

units=()
for group in examples/*/; do
  for entry in "$group"*; do
    if [ -d "$entry" ]; then
      if [ -d "$entry/src" ]; then units+=("${entry%/}"); fi
    elif [ "${entry##*.}" = dawn ]; then
      units+=("$entry")
    fi
  done
done

if [ "${#units[@]}" -lt 10 ]; then
  echo "FAIL: found only ${#units[@]} example unit(s); the tree cannot have shrunk that far" >&2
  exit 1
fi

fail=0
for u in "${units[@]}"; do
  echo "== $u"
  if ! ./bin/dawn test "$u"; then
    fail=1
  fi
done

if [ "$fail" != 0 ]; then
  echo "FAIL: an example's test blocks did not pass" >&2
  exit 1
fi
echo "OK: ${#units[@]} example unit(s), every test block run"
