#!/usr/bin/env bash
# Contract tests for reuse on the hash-trie write path and through a record
# update that owns it (perceus-design.md 6.4 and 6.6).
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
# The direct leg's original budget sat between the rebuild-shape rule's
# 249,936 in-place / 432,416 copied (36.6%) and a borrowed `std/hamt.assoc`'s
# 0/682,352 (0.0%). After node_put began stealing its descent child (#31), the
# clean workload is 682,352/682,352 (100%) and the borrowed mutant remains 0%;
# 95% holds that independently measured gain with room for small workload
# drift.
#
# A second workload puts the same accumulator in `State { ..st, values:
# map.insert(st.values, ...) }`. After the #30 scheduling fix it measures
# 199,968/566,176 (35.3%) before #31 and 566,176/566,176 (100%) after it; a
# private compiler with the scheduling call removed measures 0/566,176 while
# still printing the same answer. Its 95% budget and source mutant make the
# record lifetime independently observable. The direct leg stays green under
# that mutant, proving the failure is not manufactured by breaking hamt itself.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/map-reuse-contract"
cc_bin="${CC:-cc}"

# in-place/(in-place+copied), in percent. The original direct-hamt assertion
# keeps its measured cliff; the record-spread leg has its own post-fix band.
hamt_rate_budget=95
record_rate_budget=95

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Emit, compile and run the direct-hamt workload, appending one
# `red <mutation> <assert>` line per failed assertion to $observed. $1 is the
# label ("" for the clean run), $2 the DAWN_RC_MODE_FLIPS spec ("" for none),
# and $3 the compiler CLI (the production compiler unless a source mutant is
# under test).
observed="$work/observed.txt"
: > "$observed"
run_leg() { # label flips compiler [std-dir]
  local label="$1" flips="$2" compiler="$3" std_dir="${4:-}"
  local std_args=()
  [ -z "$std_dir" ] || std_args=(--std "$std_dir")
  local dir="$work/${label:-clean}/direct"
  mkdir -p "$dir"
  DAWN_RC_MODE_FLIPS="$flips" "$compiler" __emitc "${std_args[@]}" "$here/insert_native.dawn" \
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

  local stats in_place copied stolen steal_dup total pct steal_total steal_pct
  stats="$(grep '^rc-stats:' "$dir/err.txt" || true)"
  read -r in_place copied stolen steal_dup <<EOF
$(printf '%s\n' "$stats" | sed -n \
  's/^rc-stats: array_with in-place \([0-9]*\), copied \([0-9]*\), array_steal taken \([0-9]*\), dup \([0-9]*\),.*$/\1 \2 \3 \4/p')
EOF
  [ -n "${copied:-}" ] || fail "no rc-stats line in ${label:-the clean run}'s stderr"
  total=$((in_place + copied))
  [ "$total" -gt 0 ] || fail "${label:-the clean run} made no array_with calls at all"
  pct=$((in_place * 100 / total))

  # `hamt_in_place`: the descent writes into the node it owns.
  if [ "$((in_place * 100))" -ge "$((total * hamt_rate_budget))" ]; then
    echo "     hamt_in_place  ok    ${in_place}/${total} in place (${pct}%)"
  else
    echo "     hamt_in_place  FAIL  ${in_place}/${total} in place (${pct}%, budget ${hamt_rate_budget}%)"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" hamt_in_place >> "$observed"
    [ -n "$label" ] ||
      fail "the map/set write path lost in-place reuse. See c/infer.proj_demands
      and docs/perceus-design.md 6.4; scripts/array-contract cannot see this."
  fi

  steal_total=$((stolen + steal_dup))
  steal_pct=$((stolen * 100 / (steal_total == 0 ? 1 : steal_total)))
  if [ "$steal_total" -gt 0 ] &&
      [ "$((stolen * 100))" -ge "$((steal_total * hamt_rate_budget))" ]; then
    echo "     child_steal_taken  ok    ${stolen}/${steal_total} taken (${steal_pct}%)"
  else
    echo "     child_steal_taken  FAIL  ${stolen}/${steal_total} taken (${steal_pct}%, budget ${hamt_rate_budget}%)"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" child_steal_taken >> "$observed"
    [ -n "$label" ] ||
      fail "hamt.node_put stopped stealing its descent child"
  fi
}

# The focused #30 leg. Its only difference from the direct accumulator is one
# record owner around the map; without c/rc.dawn's projection scheduling the
# answer stays correct but every hamt root arrives shared. Keeping the two
# programs separate makes `hamt_in_place` a negative control for the record
# mutant instead of letting one aggregate percentage hide which layer moved.
run_record_leg() { # label flips compiler [std-dir]
  local label="$1" flips="$2" compiler="$3" std_dir="${4:-}"
  local std_args=()
  [ -z "$std_dir" ] || std_args=(--std "$std_dir")
  local dir="$work/${label:-clean}/record"
  mkdir -p "$dir"
  DAWN_RC_MODE_FLIPS="$flips" "$compiler" __emitc "${std_args[@]}" "$here/record_update_native.dawn" \
    -o "$dir/record.c"
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror \
    -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label \
    -I "$root/runtime/c" \
    -o "$dir/record" "$dir/record.c" "$root/runtime/c/dawn_rt.c" -lm

  ( ulimit -v 4000000 && DAWN_RC_STATS=1 timeout 300 "$dir/record" \
      > "$dir/out.txt" 2> "$dir/err.txt" ) || true

  if grep -q '^done 200000 7$' "$dir/out.txt"; then
    echo "     record_finished  ok"
  else
    echo "     record_finished  FAIL"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" record_finished >> "$observed"
  fi

  local stats in_place copied total pct
  stats="$(grep '^rc-stats:' "$dir/err.txt" || true)"
  read -r in_place copied <<EOF
$(printf '%s\n' "$stats" | sed -n \
  's/^rc-stats: array_with in-place \([0-9]*\), copied \([0-9]*\),.*$/\1 \2/p')
EOF
  [ -n "${copied:-}" ] || fail "no rc-stats line in ${label:-the clean run}'s record stderr"
  total=$((in_place + copied))
  [ "$total" -gt 0 ] || fail "${label:-the clean run}'s record made no array_with calls"
  pct=$((in_place * 100 / total))
  if [ "$((in_place * 100))" -ge "$((total * record_rate_budget))" ]; then
    echo "     record_spread_in_place  ok    ${in_place}/${total} in place (${pct}%)"
  else
    echo "     record_spread_in_place  FAIL  ${in_place}/${total} in place (${pct}%, budget ${record_rate_budget}%)"
    [ -z "$label" ] || printf 'red\t%s\t%s\n' "$label" record_spread_in_place >> "$observed"
    [ -n "$label" ] ||
      fail "record-update lowering kept the spread owner alive across map.insert"
  fi
}

# The roster the matrix names has to be the roster this script checks, or the
# comparison below is between two different questions.
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
printf 'finished\nhamt_in_place\nchild_steal_taken\nrecord_finished\nrecord_spread_in_place\n' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than run.sh checks"
awk -F '\t' '$1 == "role" { print $2 }' "$here/matrix.txt" > "$work/mutants.txt"
printf 'borrow-hamt-assoc-again\nkeep-record-spread-source\nget-hamt-child-again\n' > "$work/mutants.ran.txt"
diff -u "$work/mutants.txt" "$work/mutants.ran.txt" ||
  fail "matrix.txt names a different mutant roster than run.sh executes"

echo "== clean =="
run_leg "" "" "$root/bin/dawn"
run_record_leg "" "" "$root/bin/dawn"

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
mutation=borrow-hamt-assoc-again
spec='std/hamt:assoc:3:0=both'
echo "  $mutation"
run_leg "$mutation" "$spec" "$root/bin/dawn"
run_record_leg "$mutation" "$spec" "$root/bin/dawn"
cmp -s "$work/clean/direct/insert.c" "$work/$mutation/direct/insert.c" &&
  fail "$mutation changed nothing"

# A source-level production mutant restores the pre-#30 RC walk in a private
# compiler. It is deliberately not an environment branch in production code:
# the exact scheduling call is replaced once, the mutant compiler is built,
# and both workloads are judged with that compiler. The direct accumulator
# remains the negative control while the record leg falls to zero reuse.
mutation=keep-record-spread-source
echo "  $mutation"
mdir="$work/$mutation/compiler"
mkdir -p "$mdir"
cp -R "$root/selfhost" "$mdir/selfhost"
cp -R "$root/compiler-plan" "$mdir/compiler-plan"
ln -s "$root/packages" "$mdir/packages"
python3 - "$mdir/selfhost/src/c/rc.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "let (st0, stmts0, tail0) = schedule_record_update(st, stmts, tail)"
new = "let (st0, stmts0, tail0) = (st, stmts, tail)"
if text.count(old) != 1:
    raise SystemExit("keep-record-spread-source: mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
if ! "$root/bin/dawn" build "$mdir/selfhost" -o "$mdir/compiler.jar" \
    > "$mdir/build.out" 2>&1; then
  cat "$mdir/build.out" >&2
  fail "$mutation did not compile"
fi
printf '#!/bin/sh\nexec java -Xss512m -Xmx2g -jar "%s" "$@"\n' "$mdir/compiler.jar" > "$mdir/dawn"
chmod +x "$mdir/dawn"
run_leg "$mutation" "" "$mdir/dawn"
run_record_leg "$mutation" "" "$mdir/dawn"
cmp -s "$work/clean/record/record.c" "$work/$mutation/record/record.c" &&
  fail "$mutation changed no record-update C"

# The #31 N-1 mutant restores node_put's old get+recursive-call pair in a
# private std tree. It needs no mutant compiler: --std is the normal input
# boundary, and using the production compiler here keeps the mutation to the
# one source line whose ownership contract the new assertion names.
mutation=get-hamt-child-again
echo "  $mutation"
sdir="$work/$mutation/source"
mkdir -p "$work/$mutation"
cp -R "$root/std" "$sdir"
python3 - "$sdir/hamt.dawn" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = """        let child = array_steal(kids, pos)
        let sub = node_put(child, shift + BITS, h, k, v, seq)"""
new = """        let sub = node_put(array_get(kids, pos), shift + BITS, h, k, v, seq)"""
if text.count(old) != 1:
    raise SystemExit("get-hamt-child-again: mutation anchor drifted")
path.write_text(text.replace(old, new))
PY
run_leg "$mutation" "" "$root/bin/dawn" "$sdir"
run_record_leg "$mutation" "" "$root/bin/dawn" "$sdir"
cmp -s "$work/clean/direct/insert.c" "$work/$mutation/direct/insert.c" &&
  fail "$mutation changed no hamt C"

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
