#!/usr/bin/env bash
# The borrowed-view contract: what makes a view safe, and that it is cheap.
#
#   ./scripts/rc-view-contract/run.sh
#
# A view (selfhost/src/c/views.dawn) is a local with no count of its own, read
# out of a borrowed parameter. Taking the count away is the whole saving --
# `sum`'s children and `std/pvec.leaf_for`'s trie walk go from a dup and a drop
# per step to none -- and it is also the whole risk: a view that outlives what
# it reads, or one that is released though it never took a reference, prints
# the right bytes until the allocator reuses the block.
#
# Two kinds of assertion, because the two failures look different:
#
#   output          the probe runs under AddressSanitizer and LeakSanitizer
#                   and prints the expected lines. The oracle for every way
#                   a view can be wrong at run time.
#   sum_bare, leaf_for_bare, wrap_counted
#                   the emitted C of three functions. The saving is not
#                   observable in the output, so it is pinned in the text:
#                   `sum` and the trie walk carry no dup, drop or own-slot,
#                   and a projection of an OWNED parameter is still copied.
#
# Then one private compiler per mutation (mutate.py), each taking away one of
# the four things that keep a view safe, and the red set each one produces has
# to be exactly the one matrix.txt records, with the owner red under its own
# mutant. "The green of a gate that has never seen a red is not evidence".
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/rc-view-contract"
cc_bin="${CC:-cc}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

observed="$work/observed.txt"
: > "$observed"

# The three emitted symbols. Module `probe`, and std/pvec's `leaf_for`, whose
# `_` is escaped to `_1` by the emitter's mangling.
SUM_SYM=dawn_probe__sum
WRAP_SYM=dawn_probe__read_1wrap
LEAF_SYM=dawn_std_2pvec__leaf_1for

# judge <label> <compiler> <outdir>: one leg. Appends `red <label> <assertion>`
# lines to $observed for the mutants, and fails the script on a red clean leg.
judge() {
  local label="$1" compiler="$2" dir="$3"
  mkdir -p "$dir"
  local red_or_fail
  red_or_fail() {
    local assertion="$1" detail="$2"
    if [ -z "$label" ]; then
      echo "     $assertion  FAIL"
      [ -z "$detail" ] || printf '%s\n' "$detail" | sed -n '1,15p' >&2
      fail "$assertion is red on the production compiler"
    fi
    echo "     $assertion  red"
    printf 'red\t%s\t%s\n' "$label" "$assertion" >> "$observed"
  }

  if ! "$compiler" __emitc "$here/probe.dawn" -o "$dir/probe.c" > "$dir/emit.out" 2>&1; then
    red_or_fail emits "$(tail -5 "$dir/emit.out")"
    return 0
  fi
  echo "     emits  ok"

  if ! "$cc_bin" -std=c11 -g -O0 -fno-omit-frame-pointer -fwrapv -fexceptions \
      -fno-strict-aliasing -fsanitize=address -pthread -w \
      -I "$root/runtime/c" -o "$dir/probe" "$dir/probe.c" "$root/runtime/c/dawn_rt.c" -lm \
      > "$dir/cc.out" 2>&1; then
    red_or_fail output "$(tail -5 "$dir/cc.out")"
  else
    local rc=0
    ( ASAN_OPTIONS=detect_leaks=1 timeout 300 "$dir/probe" \
        > "$dir/out.txt" 2> "$dir/err.txt" < /dev/null ) || rc=$?
    if [ "$rc" -eq 0 ] && ! grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$dir/err.txt" &&
        diff -q "$here/expected.txt" "$dir/out.txt" > /dev/null; then
      echo "     output  ok"
    else
      red_or_fail output "exit $rc: $(head -12 "$dir/err.txt")"
    fi
  fi

  local rule sym why
  for spec in "sum_bare:$SUM_SYM:bare" "leaf_for_bare:$LEAF_SYM:leaf_for" "wrap_counted:$WRAP_SYM:counted"; do
    IFS=: read -r rule sym why <<< "$spec"
    local rc=0
    why="$(python3 "$here/check_c.py" "$dir/probe.c" "$sym" "$why")" || rc=$?
    if [ "$rc" -eq 0 ]; then
      echo "     $rule  ok"
    elif [ "$rc" -eq 1 ]; then
      red_or_fail "$rule" "$why"
    else
      fail "check_c.py could not judge $rule: $why"
    fi
  done
}

# The roster the matrix names has to be the roster this script checks.
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
printf 'emits\noutput\nsum_bare\nleaf_for_bare\nwrap_counted\n' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than run.sh checks"
mutations=(
  views-of-owned-roots views-of-owned-roots-blind views-in-the-ledger
  views-in-the-frame elements-uncounted
)
awk -F '\t' '$1 == "role" { print $2 }' "$here/matrix.txt" > "$work/mutants.txt"
printf '%s\n' "${mutations[@]}" > "$work/mutants.ran.txt"
diff -u "$work/mutants.txt" "$work/mutants.ran.txt" ||
  fail "matrix.txt names a different mutant roster than run.sh executes"

# Every private compiler is built first, side by side: each is one copy of the
# compiler's own sources with one anchor edited, and a build is the slow part.
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
printf '%s\n' "${mutations[@]}" | xargs -P 5 -I{} bash -c 'build_one "$1" "$2" "$3"' _ {} "$work" "$root" ||
  fail "a mutant compiler did not build"
for m in "${mutations[@]}"; do
  mdir="$work/$m/compiler"
  printf '#!/bin/sh\nexec java -Xss512m -Xmx2g -jar "%s" "$@"\n' "$mdir/compiler.jar" > "$mdir/dawn"
  chmod +x "$mdir/dawn"
done

echo "== clean =="
judge "" "$root/bin/dawn" "$work/clean"

echo "== mutants =="
for m in "${mutations[@]}"; do
  echo "  $m"
  judge "$m" "$work/$m/compiler/dawn" "$work/$m/out"
  # a mutant that emitted C must have emitted different C
  if [ -f "$work/$m/out/probe.c" ] && cmp -s "$work/clean/probe.c" "$work/$m/out/probe.c"; then
    fail "$m changed no emitted C: the mutation never engaged"
  fi
done

awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$work/expected.txt"
LC_ALL=C sort -o "$observed" "$observed"
diff -u "$work/expected.txt" "$observed" || fail "the observed red set differs from matrix.txt"

# an owner has to be red under its own mutant
while IFS=$'\t' read -r _ mutation owner; do
  [ "$(grep -Fxc "$(printf 'red\t%s\t%s' "$mutation" "$owner")" "$observed")" -eq 1 ] ||
    fail "$mutation does not redden the assertion it owns"
done < <(awk -F '\t' '$1 == "owner" { print }' "$here/matrix.txt")

echo "rc view contract ok"
