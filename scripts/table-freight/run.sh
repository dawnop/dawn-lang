#!/usr/bin/env bash
# The Unicode tables a jar carries must cover what the jar can run.
#
#   ./scripts/table-freight/run.sh
#
# selfhost/src/reach.dawn prunes the case and classification tables (#65/#66)
# down to what the user's modules can reach, which is worth 52KB of a hello
# world. It used to walk lower.LMod.m, and `m` has no test bodies in it -- but
# the JVM emitter writes test blocks into every artifact, `dawn build` and
# `dawn test` being one code path. So a program whose only `str.to_upper` sat
# in a test block shipped without the case table, and its own `dawn test` died
# with NoSuchMethodError on dawn.rt.Strings.str_upper.
#
# selfhost never noticed: its non-test code uses every table already. Neither
# does the native side, where emitc drops test functions and the question does
# not arise. It takes a program that is small and lopsided the way a user's
# first project is, which is what only_in_test.dawn is.
#
# Two checks, because either one alone can be satisfied by giving up:
#
#   * `dawn test only_in_test.dawn` passes -- the table rode along;
#   * no_tables.dawn, the same shape with nothing to carry, still emits a
#     small dawn/rt/Strings -- pruning was not simply switched off.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/table-freight"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if ! "$root/bin/dawn" test "$here/only_in_test.dawn" > "$work/test.out" 2>&1; then
  cat "$work/test.out" >&2
  echo "FAIL: a table reachable only from a test block was pruned" >&2
  exit 1
fi

mkdir -p "$work/with" "$work/without"
"$root/bin/dawn" __emit "$here/only_in_test.dawn" -o "$work/with" > /dev/null
"$root/bin/dawn" __emit "$here/no_tables.dawn" -o "$work/without" > /dev/null

with=$(wc -c < "$work/with/dawn/rt/Strings.class")
without=$(wc -c < "$work/without/dawn/rt/Strings.class")

# The tables are tens of KB against a couple of KB of method bodies (36K vs
# 2.8K when this was written), so a factor of two is far below the real gap
# and far above any incidental difference. The cap on the table-free program
# is the half that cannot be met by carrying everything.
if [ "$with" -le $((without * 2)) ]; then
  echo "FAIL: dawn/rt/Strings is $with bytes with the tables and $without without;" >&2
  echo "      the test block's tables do not look carried" >&2
  exit 1
fi

if [ "$without" -gt 8192 ]; then
  echo "FAIL: a program that needs no table still emits $without bytes of" >&2
  echo "      dawn/rt/Strings -- pruning has stopped working" >&2
  exit 1
fi

echo "PASS  table freight follows the emitted code ($with vs $without bytes)"
