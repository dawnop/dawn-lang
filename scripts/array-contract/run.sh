#!/usr/bin/env bash
# Contract test for the `Array` primitive (docs/native-backend-plan.md D1).
#
#   ./scripts/array-contract/run.sh
#
# There is no `--record`. `expected.txt` is the answer value semantics has to
# give, written down before either backend was asked; recording it from a run
# would make it a report of what the compiler does rather than a check on it.
# Change what the probe prints and hand-edit the file to match.
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

# ---- native leg: the slot-steal transfer rate -------------------------------
#
# `array_steal`'s whole yield -- push_tail's descent reusing the trie path in
# place -- is a count, so like the push fast path above it is unobservable
# from Dawn and needs its own oracle. The clock cannot be it here (both the
# stolen and the copied descent are O(log n) per push); the counters can:
# DAWN_RC_STATS prints how often array_with wrote in place against copying,
# and how often array_steal transferred against duping. This is the one gate
# a std/pvec regression from `array_steal` back to `array_get` turns red --
# every value-semantics check is built not to see the difference.
#
# Budgets against the measured cliff, same style as the clock budget above:
# with the steal the 200k-append run measures 11241/11241 in-place stores and
# 11241/0 taken/dup steals; reverted to `array_get` it measures 6180/11241
# in-place (45% copied) and no steal calls at all. 80%/20% sits between the
# two by a wide margin on both sides.
steal_bin="$work/steal_native"
"$root/bin/dawn" __emitc "$here/steal_native.dawn" -o "$work/steal_native.c"
cc_bin="${CC:-cc}"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror \
  -Wno-unused-variable -Wno-unused-but-set-variable \
  -Wno-unused-parameter -Wno-unused-label \
  -I "$root/runtime/c" \
  -o "$steal_bin" "$work/steal_native.c" "$root/runtime/c/dawn_rt.c" -lm

# a native binary has no -Xmx to fall back on, so cap it before trusting it
( ulimit -v 4000000 && DAWN_RC_STATS=1 timeout 120 "$steal_bin" \
    > "$work/steal.out" 2> "$work/steal.err" )
if ! grep -q '^done 200000$' "$work/steal.out"; then
  echo "FAIL: the steal workload did not finish" >&2
  cat "$work/steal.out" "$work/steal.err" >&2
  exit 1
fi

stats="$(grep '^rc-stats:' "$work/steal.err" || true)"
read -r with_in with_cp steal_tk steal_dp <<EOF2
$(printf '%s\n' "$stats" | sed -n \
  's/^rc-stats: array_with in-place \([0-9]*\), copied \([0-9]*\), array_steal taken \([0-9]*\), dup \([0-9]*\), adt0 singleton hits [0-9]*, missed [0-9]*$/\1 \2 \3 \4/p')
EOF2
if [ -z "${steal_tk:-}" ]; then
  echo "FAIL: no rc-stats line in the steal run's stderr" >&2
  cat "$work/steal.err" >&2
  exit 1
fi

# taken/(taken+dup) >= 80%: the descent transfers rather than dups -- and it
# runs at all, which is what a revert to array_get silently stops
if [ $((steal_tk * 5)) -lt $(((steal_tk + steal_dp) * 4)) ] || [ "$steal_tk" -eq 0 ]; then
  echo "FAIL: array_steal transferred ${steal_tk} vs duped ${steal_dp} (budget: 80% taken)." >&2
  echo "      Either std/pvec's deep branch stopped stealing or uniqueness" >&2
  echo "      stopped holding down the descent." >&2
  exit 1
fi
# copied/(in-place+copied) <= 20%: the write-backs land in place
if [ $((with_cp * 5)) -gt $((with_in + with_cp)) ]; then
  echo "FAIL: array_with copied ${with_cp} of $((with_in + with_cp)) (budget: 20% copied)." >&2
  echo "      The accumulator's trie descent lost in-place reuse; see the" >&2
  echo "      steal note in std/pvec.push_tail." >&2
  exit 1
fi

echo "PASS  steal rate: with ${with_in}/$((with_in + with_cp)) in place, steal ${steal_tk}/$((steal_tk + steal_dp)) taken"
