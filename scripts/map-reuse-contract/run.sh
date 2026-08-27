#!/usr/bin/env bash
# Contract test for reuse on the hash-trie write path (perceus-design.md 6.4).
#
#   ./scripts/map-reuse-contract/run.sh
#
# `scripts/array-contract` already budgets an `array_with` in-place rate, and
# it cannot see this one. Its workload accumulates with `++`, so every
# `array_with` call it counts comes from `std/pvec.push_tail`; `map.insert`
# and `set.insert` reach the same primitive through `std/hamt.node_put`, and
# the two rates move independently. They did: the borrowed-parameter
# inference took the hamt rate from 43% to 14% across a self-compile and
# array-contract measured the identical 11241/11241 on both sides of it. A
# gate that has never seen a red is not evidence, and that one had never been
# pointed at this axis at all.
#
# What the rate is about. Perceus reuse on a persistent structure works by
# letting the container die early so the child it was holding becomes unique,
# which is what lets the trie descent write into a node instead of copying it.
# A borrowed parameter is never released in the callee, so borrowing the map
# in `std/hamt.assoc` keeps the whole spine at rc >= 2 and every level of the
# descent copies. Nothing about the program's answer changes -- which is why
# the `finished` control below has to stay green under the mutant, and why
# this needs a counter for an oracle rather than an output.
#
# Budgets against the measured cliff, array-contract's style: with the
# rebuild-shape rule in `c/infer.proj_demands` the workload measures 249,936
# in-place stores against 432,416 copies (36.6%), and with `std/hamt.assoc`'s
# map borrowed again it measures 0 in-place against 682,352 copies (0.0%).
# 25% sits between the two with room on both sides, and the direction of any
# future improvement (reuse deeper in the descent) is up.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/map-reuse-contract"
cc_bin="${CC:-cc}"

# in-place/(in-place+copied), in percent
rate_budget=25

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Emit, compile and run the workload, appending one `red <mutation> <assert>`
# line per failed assertion to $observed. $1 is the label ("" for the clean
# run), $2 the DAWN_RC_MODE_FLIPS spec ("" for none).
observed="$work/observed.txt"
: > "$observed"
run_leg() { # label flips
  local label="$1" flips="$2"
  local dir="$work/${label:-clean}"
  mkdir -p "$dir"
  DAWN_RC_MODE_FLIPS="$flips" "$root/bin/dawn" __emitc "$here/insert_native.dawn" \
    -o "$dir/insert.c"
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror \
    -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label \
    -I "$root/runtime/c" \
    -o "$dir/insert" "$dir/insert.c" "$root/runtime/c/dawn_rt.c" -lm

  # a native binary has no -Xmx to fall back on, so cap it before trusting it
  ( ulimit -v 4000000 && DAWN_RC_STATS=1 timeout 300 "$dir/insert" \
      > "$dir/out.txt" 2> "$dir/err.txt" ) || true

  # `finished`: the workload computed its answer. A mode decision may not
  # touch this, mutated or not.
  if grep -q '^done 200000 50000$' "$dir/out.txt"; then
    echo "     finished       ok"
  else
    echo "     finished       FAIL"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" finished >> "$observed"
  fi

  local stats in_place copied total pct
  stats="$(grep '^rc-stats:' "$dir/err.txt" || true)"
  read -r in_place copied <<EOF
$(printf '%s\n' "$stats" | sed -n \
  's/^rc-stats: array_with in-place \([0-9]*\), copied \([0-9]*\),.*$/\1 \2/p')
EOF
  [ -n "${copied:-}" ] || fail "no rc-stats line in ${label:-the clean run}'s stderr"
  total=$((in_place + copied))
  [ "$total" -gt 0 ] || fail "${label:-the clean run} made no array_with calls at all"
  pct=$((in_place * 100 / total))

  # `hamt_in_place`: the descent writes into the node it owns.
  if [ "$((in_place * 100))" -ge "$((total * rate_budget))" ]; then
    echo "     hamt_in_place  ok    ${in_place}/${total} in place (${pct}%)"
  else
    echo "     hamt_in_place  FAIL  ${in_place}/${total} in place (${pct}%, budget ${rate_budget}%)"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" hamt_in_place >> "$observed"
    [ -n "$label" ] ||
      fail "the map/set write path lost in-place reuse. See c/infer.proj_demands
      and docs/perceus-design.md 6.4; scripts/array-contract cannot see this."
  fi
}

# The roster the matrix names has to be the roster this script checks, or the
# comparison below is between two different questions.
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
printf 'finished\nhamt_in_place\n' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than run.sh checks"

echo "== clean =="
run_leg "" ""

# The mutant. `DAWN_RC_MODE_FLIPS` (parsed in c/cdriver.dawn, the same channel
# scripts/rc-mode-contract injects through) re-runs the whole fixpoint with
# `std/hamt.assoc`'s map held at the opposite of what the inference decided --
# a coherent other-world propagated to every caller, not an edit to a finished
# table. With the rebuild-shape rule in force the inference says owned, so the
# flip says borrowed: this is the pre-rule world, restored at the one position
# the whole loss was traced to.
#
# Delete the rule itself and this gate reds without the mutant, because the
# clean leg is then already the borrowed world.
echo "== mutants =="
while IFS= read -r mutation; do
  case "$mutation" in
    borrow-hamt-assoc-again) spec='std/hamt:assoc:3:0=both' ;;
    *) fail "matrix.txt names a mutant this script cannot spell: $mutation" ;;
  esac
  echo "  $mutation"
  run_leg "$mutation" "$spec"
  cmp -s "$work/clean/insert.c" "$work/$mutation/insert.c" &&
    fail "$mutation changed nothing"
done < <(awk -F '\t' '$1 == "role" { print $2 }' "$here/matrix.txt")

expected="$work/expected.txt"
awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$expected"
LC_ALL=C sort -o "$observed" "$observed"
diff -u "$expected" "$observed" || fail "the observed red set differs from matrix.txt"

# A control may not be red under any mutant, and an owner has to be red under
# its own and no other -- which is what "owns" means.
while IFS=$'\t' read -r _ assertion; do
  grep -q "	${assertion}\$" "$observed" &&
    fail "a mutant reddened the control $assertion"
done < <(awk -F '\t' '$1 == "control" { print }' "$here/matrix.txt")
while IFS=$'\t' read -r _ mutation owner; do
  [ "$(grep -Fxc "$(printf 'red\t%s\t%s' "$mutation" "$owner")" "$observed")" -eq 1 ] ||
    fail "$mutation does not redden the assertion it owns"
done < <(awk -F '\t' '$1 == "owner" { print }' "$here/matrix.txt")

echo "map reuse contract ok"
