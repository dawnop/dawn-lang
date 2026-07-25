#!/usr/bin/env bash
# Contract test for the `Array` primitive (docs/native-backend-plan.md D1).
#
#   ./scripts/array-contract/run.sh
#
# `Array` and `array_*` are std-internal, so this cannot be an examples/
# program: the harness builds a copy of std/ with array.dawn dropped in and
# compiles probe.dawn against it. It checks two things a second backend also
# has to satisfy:
#
#   * value semantics -- no operation is observably destructive, including
#     when two versions push onto the same base;
#   * `array_push` extends in place when the version owns the frontier. That
#     one is deliberately unobservable from Dawn, so it is checked by the
#     clock: the accumulation shape is O(n) with it and O(n^2) without, which
#     at these sizes is milliseconds against minutes.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/array-contract"

# the in-place path must beat this by ~3 orders of magnitude; a copying
# backend misses it by ~2 in the other direction, so the gap is not a race
linear_budget_ms=3000

# rebuild the toolchain if sources moved, then drive the jar directly: only it
# takes --std, and the point here is to override the embedded std
"$root/bin/dawn" --version > /dev/null
jar="$root/build/dawn-selfhost.jar"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$root"/std/*.dawn "$root/std/modules.txt" "$work/"
cp "$here/array.dawn" "$work/"
echo array >> "$work/modules.txt"

out="$work/out.txt"
java -Xss512m -jar "$jar" run --std "$work" "$here/probe.dawn" > "$out"

if ! diff -u "$here/expected.txt" <(grep -v '^linear\|^forked' "$out"); then
  echo "FAIL: Array value semantics changed" >&2
  exit 1
fi

linear_ms="$(sed -n 's/^linear .* in \([0-9]*\)ms$/\1/p' "$out")"
forked_ms="$(sed -n 's/^forked .* in \([0-9]*\)ms$/\1/p' "$out")"
if [ -z "$linear_ms" ] || [ -z "$forked_ms" ]; then
  echo "FAIL: no timings in output" >&2
  cat "$out" >&2
  exit 1
fi

if [ "$linear_ms" -gt "$linear_budget_ms" ]; then
  echo "FAIL: 200k pushes took ${linear_ms}ms (budget ${linear_budget_ms}ms)." >&2
  echo "      array_push stopped extending in place -- the accumulation loop is" >&2
  echo "      quadratic again. See docs/collections-dejava-research.md 9.3." >&2
  exit 1
fi

echo "PASS  values, bounds; 200k linear ${linear_ms}ms vs 20k forked ${forked_ms}ms"
