#!/usr/bin/env bash
# The ADT reset/reuse contract (docs/perceus-reuse-design.md 4.2, 6.3).
#
#   ./scripts/adt-reuse-contract/run.sh
#
# Reuse is invisible from the program: it prints the same bytes with or
# without it, and a stale read of a reused block is not an AddressSanitizer
# report because the block stays allocated. So this reads three different
# things, and each of them needs its own oracle.
#
#   answers      stdout against expected.txt, recorded from the compiler before
#                reuse existed. The shared-tree witness lives here: an old tree
#                is kept alive across `incr`, and a reuse that rebuilt a node
#                somebody else still held changes its sum.
#   finished     exit status, AddressSanitizer and LeakSanitizer over the same
#                runs, which include a suspension between a reset and its reuse
#                (`ask`, an effect handler) and a caught panic between them
#                (`boom`). The token is an ordinary owned local, and these are
#                the paths that make sure the frame's cleanup agrees.
#   rates        the runtime's counters, read as a difference between two sizes
#                of one workload so that setup cancels: a steady state of
#                `update` allocates no node at all, and `incr` over a tree or a
#                list reuses the node it visits (95% budget).
#
# The runtime is built with DAWN_REUSE_POISON, which fills a reset node's slots
# with a non-canonical word, so a field read that should have come before the
# reset faults instead of reading what the next owner has not written yet.
#
# Then one private compiler per mutation (mutate.py) and one private runtime
# (rc-contract/mutate.py), each taking away one thing; the red set each one
# produces has to be the one matrix.txt records, owner included. The green of
# a gate that has never seen a red is not evidence.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/adt-reuse-contract"
cc_bin="${CC:-cc}"
rate_budget=95

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

observed="$work/observed.txt"
: > "$observed"

# The runs, in the order expected.txt has their stdout. Every run is a
# separate process so each counter line belongs to one workload.
runs=("update 10000" "update 20000" "tree 2000 2" "tree 2000 12" "list 2000 2" "list 2000 12"
      "shared" "ask 200" "boom 200" "loopy")

# stat <err-file> <field>: taken, missed or allocs of one run.
stat() {
  case "$2" in
    taken) sed -n 's/^rc-stats:.*adt reuse taken \([0-9]*\), missed [0-9]*$/\1/p' "$1" ;;
    missed) sed -n 's/^rc-stats:.*adt reuse taken [0-9]*, missed \([0-9]*\)$/\1/p' "$1" ;;
    allocs) sed -n 's/^rc-contract: adt allocs \([0-9]*\)$/\1/p' "$1" ;;
  esac
}

# judge <label> <compiler> <runtime-dir> <outdir>: one leg. Appends
# `red <label> <assertion>` lines for a mutant and fails the script on a red
# clean leg.
judge() {
  local label="$1" compiler="$2" rt="$3" dir="$4"
  mkdir -p "$dir"
  red_or_fail() {
    local assertion="$1" detail="$2"
    if [ -z "$label" ]; then
      echo "     $assertion  FAIL"
      [ -z "$detail" ] || printf '%s\n' "$detail" | sed -n '1,15p' >&2
      fail "$assertion is red on the production build"
    fi
    echo "     $assertion  red"
    printf 'red\t%s\t%s\n' "$label" "$assertion" >> "$observed"
  }

  if ! "$compiler" __emitc "$here/probe.dawn" -o "$dir/probe.c" > "$dir/emit.out" 2>&1; then
    red_or_fail emits "$(tail -5 "$dir/emit.out")"
    return 0
  fi
  echo "     emits  ok"
  if ! "$cc_bin" -std=c11 -g -O1 -fno-omit-frame-pointer -fwrapv -fexceptions \
      -fno-strict-aliasing -fsanitize=address -pthread -w \
      -DDAWN_RC_CONTRACT -DDAWN_REUSE_POISON -I "$rt" \
      -o "$dir/probe" "$dir/probe.c" "$rt/dawn_rt.c" -lm > "$dir/cc.out" 2>&1; then
    red_or_fail emits "$(tail -5 "$dir/cc.out")"
    return 0
  fi

  local i=0 bad="" a
  : > "$dir/stdout.txt"
  for a in "${runs[@]}"; do
    i=$((i + 1))
    local rc=0
    # shellcheck disable=SC2086
    ( ASAN_OPTIONS=detect_leaks=1 DAWN_RC_STATS=1 timeout 300 "$dir/probe" $a \
        >> "$dir/stdout.txt" 2> "$dir/err$i.txt" < /dev/null ) || rc=$?
    if [ "$rc" -ne 0 ] || grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$dir/err$i.txt"; then
      bad="$bad
run '$a': exit $rc: $(grep -m1 -E 'ERROR|SUMMARY' "$dir/err$i.txt" || true)"
    fi
  done
  if [ -z "$bad" ]; then echo "     finished  ok"; else red_or_fail finished "$bad"; fi
  if diff -q "$here/expected.txt" "$dir/stdout.txt" > /dev/null; then
    echo "     answers  ok"
  else
    red_or_fail answers "$(diff "$here/expected.txt" "$dir/stdout.txt" | head -8)"
  fi

  # rates, as differences of two sizes of one workload (runs 1..2, 3..4, 5..6)
  local t1 t2 a1 a2 want got dalloc
  t1=$(stat "$dir/err1.txt" taken); t2=$(stat "$dir/err2.txt" taken)
  a1=$(stat "$dir/err1.txt" allocs); a2=$(stat "$dir/err2.txt" allocs)
  if [ -n "$t1$t2$a1$a2" ] && [ "$a2" -eq "$a1" ] && [ "$((t2 - t1))" -eq 50000 ]; then
    echo "     update_zero_alloc  ok    +10000 steps: +$((t2 - t1)) reuses, +$((a2 - a1)) allocations"
  else
    red_or_fail update_zero_alloc "reuses ${t1:-?}->${t2:-?}, allocations ${a1:-?}->${a2:-?}"
  fi
  local pair name
  for pair in "3:4:tree_reuse_rate:2000:10" "5:6:list_reuse_rate:2000:10"; do
    IFS=: read -r i1 i2 name n reps <<< "$pair"
    t1=$(stat "$dir/err$i1.txt" taken); t2=$(stat "$dir/err$i2.txt" taken)
    a1=$(stat "$dir/err$i1.txt" allocs); a2=$(stat "$dir/err$i2.txt" allocs)
    want=$((n * reps))
    if [ -n "$t1$t2$a1$a2" ] && [ "$(((t2 - t1) * 100))" -ge "$((want * rate_budget))" ] &&
        [ "$(((a2 - a1) * 100))" -le "$((want * (100 - rate_budget)))" ]; then
      echo "     $name  ok    $((t2 - t1))/$want visits reused, $((a2 - a1)) allocated"
    else
      red_or_fail "$name" "reuses ${t1:-?}->${t2:-?}, allocations ${a1:-?}->${a2:-?}, visits $want"
    fi
  done
  t1=$(stat "$dir/err8.txt" taken)
  if [ -n "$t1" ] && [ "$((t1 * 100))" -ge "$((200 * rate_budget))" ]; then
    echo "     ask_reuse  ok    $t1/200 reused across a suspension"
  else
    red_or_fail ask_reuse "reuses ${t1:-?} of 200"
  fi
}

# The rosters the matrix names have to be the ones checked here.
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
printf 'emits\nfinished\nanswers\nupdate_zero_alloc\ntree_reuse_rate\nlist_reuse_rate\nask_reuse\n' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than run.sh checks"
mutations=(pairing-off reuse-leaks-the-token reset-keeps-the-slot reuse-across-loops)
awk -F '\t' '$1 == "role" && $3 == "counted" { print $2 }' "$here/matrix.txt" > "$work/mutants.txt"
printf '%s\n' "${mutations[@]}" > "$work/mutants.ran.txt"
diff -u "$work/mutants.txt" "$work/mutants.ran.txt" ||
  fail "matrix.txt names a different mutant roster than run.sh executes"

# Every private compiler is built first, side by side: one copy of the
# compiler's own sources with one anchor edited.
for m in "${mutations[@]}"; do
  mdir="$work/$m/compiler"
  mkdir -p "$mdir"
  cp -R "$root/selfhost" "$mdir/selfhost"
  cp -R "$root/compiler-plan" "$mdir/compiler-plan"
  ln -s "$root/packages" "$mdir/packages"
  python3 "$here/mutate.py" "$m" "$mdir"
done
build_one() {
  local m="$1" mdir="$2/$1/compiler"
  if ! "$3/bin/dawn" build "$mdir/selfhost" -o "$mdir/compiler.jar" > "$mdir/build.out" 2>&1; then
    cat "$mdir/build.out" >&2
    echo "FAIL: $m did not compile" >&2
    return 1
  fi
}
export -f build_one
printf '%s\n' "${mutations[@]}" | xargs -P 4 -I{} bash -c 'build_one "$1" "$2" "$3"' _ {} "$work" "$root" ||
  fail "a mutant compiler did not build"
for m in "${mutations[@]}"; do
  mdir="$work/$m/compiler"
  printf '#!/bin/sh\nexec java -Xss512m -Xmx2g -jar "%s" "$@"\n' "$mdir/compiler.jar" > "$mdir/dawn"
  chmod +x "$mdir/dawn"
done

echo "== clean =="
judge "" "$root/bin/dawn" "$root/runtime/c" "$work/clean"

echo "== mutants =="
for m in "${mutations[@]}"; do
  echo "  $m"
  judge "$m" "$work/$m/compiler/dawn" "$root/runtime/c" "$work/$m/out"
  if [ -f "$work/$m/out/probe.c" ] && cmp -s "$work/clean/probe.c" "$work/$m/out/probe.c"; then
    fail "$m changed no emitted C: the mutation never engaged"
  fi
done

m=reset-ignores-sharing
echo "  $m"
mkdir -p "$work/$m/rt"
cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$work/$m/rt/"
python3 "$root/scripts/rc-contract/mutate.py" "$m" "$work/$m/rt"
cmp -s "$root/runtime/c/dawn_rt.c" "$work/$m/rt/dawn_rt.c" && fail "$m changed nothing"
judge "$m" "$root/bin/dawn" "$work/$m/rt" "$work/$m/out"

awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$work/expected.txt"
LC_ALL=C sort -o "$observed" "$observed"
diff -u "$work/expected.txt" "$observed" || fail "the observed red set differs from matrix.txt"

while IFS=$'\t' read -r _ mutation owner; do
  [ "$(grep -Fxc "$(printf 'red\t%s\t%s' "$mutation" "$owner")" "$observed")" -eq 1 ] ||
    fail "$mutation does not redden the assertion it owns"
done < <(awk -F '\t' '$1 == "owner" { print }' "$here/matrix.txt")

echo "adt reuse contract ok"
