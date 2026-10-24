#!/usr/bin/env bash
# Contract test for the tagged immediates (docs/native-immediates-design.md).
#
#   ./scripts/imm-contract/run.sh
#
# An erased Int or Bool is a word with its low bit set that points at nothing.
# Every place in the runtime that reads a header or a box has to ask before it
# dereferences, and a place that forgets does not compute a wrong answer, it
# segfaults -- on a program that holds an immediate, and on no other. So the
# gate that the points are all covered cannot be a corpus run: the corpus is
# green exactly when nothing forgot, and "nothing forgot" and "nothing looked"
# are the same transcript. This script holds the other half. It builds the
# runtime once per point with that point's question removed (mutate.py) and
# requires the case that owns the point to go red -- by exit status, because
# the interesting reds are signals and sanitizer reports, not assertions.
#
# Five builds of the unmutated runtime have to be green first, and the same
# builds run each mutant:
#
#   plain        -O1
#   inline       -O2 -DDAWN_RT_INLINE_RC (dup and drop's hot paths in the header)
#   asan         AddressSanitizer with leak detection: a heap fallback box that
#                leaks, or an immediate that is freed, is a report
#   imm31        plain with DAWN_IMM_BITS=31, the immediate range of a wasm32
#                build on a 64-bit host: values between 2^30 and 2^62 take the
#                fallback path that the 63-bit range reaches only at the edges
#   inline-asan  the inline build under AddressSanitizer
#
# matrix.txt names the roster (`assert`) and, per mutant and build, the cases
# that must be red (`red`). A mutant with no red row is a mutant nobody ran.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/imm-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

warn=(-Wall -Wextra -Werror -Wno-unused-parameter -Wno-unused-function)
common=(-std=c11 -g -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread "${warn[@]}")
run_timeout=60

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# build <variant> <runtime-dir> <output>
build() {
  local variant="$1" dir="$2" out="$3"
  local flags=()
  case "$variant" in
    plain) flags=(-O1) ;;
    inline) flags=(-O2 -DDAWN_RT_INLINE_RC) ;;
    asan) flags=(-O1 -fno-omit-frame-pointer -fsanitize=address) ;;
    imm31) flags=(-O1 -DDAWN_IMM_BITS=31) ;;
    inline-asan) flags=(-O1 -DDAWN_RT_INLINE_RC -fno-omit-frame-pointer -fsanitize=address) ;;
    *) fail "unknown build variant $variant" ;;
  esac
  # a mutant dereferences what the compiler can see is a bad address, and
  # says so; that is the point of it, so its warnings are not errors
  [ -z "${MUTANT_BUILD:-}" ] || flags+=(-w)
  "$cc_bin" "${common[@]}" "${flags[@]}" -I "$dir" -o "$out" "$here/imm_test.c" -lm
}

# status <binary> <case> -> 0 when the case passed, 1 when it did not (any
# nonzero exit, a signal, a timeout, a sanitizer report)
status() {
  set +e
  (ASAN_OPTIONS=detect_leaks=1 timeout "$run_timeout" "$1" --case "$2" > /dev/null 2>&1) 2> /dev/null
  local rc=$?
  set -e
  [ "$rc" -eq 0 ] && return 0
  return 1
}

field() { awk -F '\t' -v k="$1" '$1 == k { print }' "$here/matrix.txt"; }

echo "== roster =="
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"

echo "== baseline =="
for variant in plain inline asan imm31 inline-asan; do
  build "$variant" "$root/runtime/c" "$work/base-$variant"
  "$work/base-$variant" --list | diff -u "$work/roster.txt" - ||
    fail "matrix.txt names a different roster than imm_test.c runs"
  set +e
  ASAN_OPTIONS=detect_leaks=1 timeout $((run_timeout * 4)) "$work/base-$variant" > "$work/base-$variant.out" 2>&1
  rc=$?
  set -e
  cat "$work/base-$variant.out" | sed "s/^/  $variant: /"
  [ "$rc" -eq 0 ] && ! grep -q ' FAIL$' "$work/base-$variant.out" ||
    fail "the unmutated runtime does not satisfy the contract in the $variant build"
done

echo "== mutants =="
mutants="$(field red | cut -f2 | awk '!seen[$0]++')"
[ -n "$mutants" ] || fail "matrix.txt names no mutant"
nmut=0
while IFS= read -r mutation; do
  [ -n "$mutation" ] || continue
  dir="$work/m-$mutation"
  mkdir -p "$dir"
  cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$dir/"
  python3 "$here/mutate.py" "$mutation" "$dir"
  cmp -s "$root/runtime/c/dawn_rt.h" "$dir/dawn_rt.h" &&
    cmp -s "$root/runtime/c/dawn_rt.c" "$dir/dawn_rt.c" &&
    fail "$mutation changed nothing"
  # one build per (variant the matrix names) x (its sanitized twin)
  for build_name in $(field red | awk -F '\t' -v m="$mutation" '$2 == m { print $3 }' | sort -u); do
    for variant in "$build_name" "$([ "$build_name" = inline ] && echo inline-asan || echo asan)"; do
      bin="$dir/bin-$variant"
      MUTANT_BUILD=1 build "$variant" "$dir" "$bin" > "$dir/cc-$variant.out" 2>&1 ||
        { cat "$dir/cc-$variant.out" >&2; fail "$mutation did not compile in the $variant build"; }
      for c in $(field red | awk -F '\t' -v m="$mutation" -v b="$build_name" '$2 == m && $3 == b { print $4 }'); do
        if status "$bin" "$c"; then
          fail "$mutation: case $c stayed green in the $variant build"
        fi
        printf 'red   %-34s %-12s %s\n' "$mutation" "$variant" "$c"
      done
    done
  done
  nmut=$((nmut + 1))
done <<< "$mutants"

# ---- the emitter ---------------------------------------------------------
#
# The same points, one level up: the C the compiler writes for an erased read
# has to ask the tag as well (emitc.dawn `unbox_expr`). imm.dawn puts Ints and
# Bools into every erased position at the values where the scheme changes
# form, and the JVM backend's transcript (imm.expect) is the oracle. The
# emitter mutant is applied to the emitted C instead of to the compiler, which
# is the same edit one step later: `dawn_peek_int(x)` back to a direct read of
# the box, and a rebuilt compiler is not needed to see it fall over.
echo "== emitted C =="
"$root/bin/dawn" __emitc "$here/imm.dawn" -o "$work/imm.c"
grep -q 'dawn_peek_int(' "$work/imm.c" || fail "imm.dawn's C has no dawn_peek_int: the emitter stopped asking"
cat > "$work/direct.h" <<'DIRECT'
#define dawn_direct_int(x) (((dawn_box *)(x))->val.i)
#define dawn_direct_bool(x) (((dawn_box *)(x))->val.b)
DIRECT
build_c() { # variant runtime-dir csource output [extra flags...]
  local variant="$1" dir="$2" src="$3" out="$4"
  shift 4
  local flags=()
  case "$variant" in
    plain) flags=(-O1) ;;
    inline) flags=(-O2 -DDAWN_RT_INLINE_RC) ;;
    asan) flags=(-O1 -fno-omit-frame-pointer -fsanitize=address) ;;
    imm31) flags=(-O1 -DDAWN_IMM_BITS=31) ;;
  esac
  "$cc_bin" -std=c11 -g -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread \
    -w "${flags[@]}" "$@" -I "$dir" -o "$out" "$src" "$dir/dawn_rt.c" -lm
}
for variant in plain inline asan imm31; do
  build_c "$variant" "$root/runtime/c" "$work/imm.c" "$work/imm-$variant"
  (ASAN_OPTIONS=detect_leaks=1 timeout "$run_timeout" "$work/imm-$variant" > "$work/imm-$variant.out" 2> "$work/imm-$variant.err") ||
    { cat "$work/imm-$variant.err" >&2; fail "imm.dawn failed in the $variant build"; }
  diff -u "$here/imm.expect" "$work/imm-$variant.out" ||
    fail "imm.dawn's native transcript differs from the JVM one ($variant)"
  echo "  $variant: 28 lines, equal to the JVM transcript"
done
sed -e 's/dawn_peek_int(/dawn_direct_int(/g' -e 's/dawn_peek_bool(/dawn_direct_bool(/g' "$work/imm.c" > "$work/imm-direct.c"
cmp -s "$work/imm.c" "$work/imm-direct.c" && fail "the emitter mutant changed nothing"
for variant in plain asan; do
  build_c "$variant" "$root/runtime/c" "$work/imm-direct.c" "$work/imm-direct-$variant" -include "$work/direct.h"
  if (ASAN_OPTIONS=detect_leaks=1 timeout "$run_timeout" "$work/imm-direct-$variant" > "$work/imm-direct.out" 2> /dev/null) 2> /dev/null &&
     diff -q "$here/imm.expect" "$work/imm-direct.out" > /dev/null; then
    fail "emit-reads-the-box stayed green in the $variant build"
  fi
  printf 'red   %-34s %-12s %s\n' emit-reads-the-box "$variant" imm.dawn
done

echo "imm contract ok ($nmut runtime mutants, 1 emitter mutant)"
