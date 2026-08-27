#!/usr/bin/env bash
# Contract test for the C runtime's reference counting (perceus-design.md).
#
#   ./scripts/rc-contract/run.sh
#
# Two runs, because the two things worth checking need different settings:
#
#   * under AddressSanitizer, where a drop that does not recurse is a reported
#     leak and a drop that recurses twice is a double free. Neither is visible
#     from inside the program, which is why the oracle is the sanitizer rather
#     than printed output.
#   * under a small stack, where a drop that went back to C recursion crashes
#     on the 200k-node chain instead of quietly working until some larger
#     input. `ulimit -s` is the whole point of this second run.
#
# Strings and Bytes are counted like everything else (they joined the ledger
# 2026-07-29), so the sanitized run keeps leak detection on and a reported
# leak here is always a real one. Only the --rc=leak run turns it off: that
# mode leaks everything on purpose.
#
# A third run mutates the runtime instead of the test. The green of a gate
# that has never seen a red is not evidence, and the properties the singleton
# knife added -- two constructions of one field-less tag are one object, and
# that object is out of the ledger -- are invisible from Dawn, so nothing else
# in the tree can go red when they stop holding. matrix.txt records which
# assertions each mutant reddens; this compares that record with what the
# mutated runtime actually does. The mutant is compiled without the
# sanitizers: it leaks the objects it no longer shares, on purpose, and a
# leak report would drown the per-assertion answer this run exists to read.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/rc-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

warn=(-Wall -Wextra -Werror -Wno-unused-parameter)

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

python3 "$here/matrix_check.py" --self-test
python3 "$here/matrix_check.py" "$here/matrix.txt"

echo "== sanitized =="
"$cc_bin" -std=c11 -O1 -g -fsanitize=address -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_asan" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
"$work/rc_asan"
ASAN_OPTIONS=detect_leaks=0 "$work/rc_asan" leak

# ASan replaces the allocator and grows stack frames, so the stack-depth check
# has to be a plain build.
echo "== small stack =="
"$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_plain" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
( ulimit -s 512 && "$work/rc_plain" )

# The roster the matrix names has to be the roster the binary runs, or the
# comparison below is between two different questions.
"$work/rc_plain" > "$work/baseline.out"
awk -F '\t' '$1 == "assert" { print $2 }' "$here/matrix.txt" > "$work/roster.txt"
sed '/^ok$/d' "$work/baseline.out" | awk '{ print $1 }' > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different assertion roster than rc_test.c runs"
if grep -q ' FAIL$' "$work/baseline.out"; then
  fail "the unmutated runtime does not satisfy the contract"
fi

echo "== mutants =="
build_plain() { # runtime-dir output
  "$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    "${warn[@]}" -I "$1" -o "$2" "$here/rc_test.c" "$1/dawn_rt.c"
}

observed="$work/observed.txt"
: > "$observed"
while IFS= read -r mutation; do
  dir="$work/$mutation"
  mkdir -p "$dir"
  cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$dir/"
  python3 "$here/mutate.py" "$mutation" "$dir"
  cmp -s "$root/runtime/c/dawn_rt.h" "$dir/dawn_rt.h" &&
    cmp -s "$root/runtime/c/dawn_rt.c" "$dir/dawn_rt.c" &&
    fail "$mutation changed nothing"
  build_plain "$dir" "$dir/rc_test" > "$dir/cc.out" 2>&1 ||
    { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
  # A mutant is expected to exit nonzero; what must not happen is a crash or a
  # signal, which would mean the red set was never fully observed.
  set +e
  "$dir/rc_test" > "$dir/out.txt" 2> "$dir/err.txt"
  status=$?
  set -e
  [ "$status" -lt 128 ] || fail "$mutation died on signal $((status - 128))"
  [ "$status" -ne 0 ] || fail "$mutation passed every assertion"
  awk -v m="$mutation" '$2 == "FAIL" { printf "red\t%s\t%s\n", m, $1 }' \
    "$dir/out.txt" >> "$observed"
  echo "OK   $mutation"
done < <(awk -F '\t' '$1 == "role" { print $2 }' "$here/matrix.txt")

expected="$work/expected.txt"
awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$expected"
LC_ALL=C sort -o "$observed" "$observed"
diff -u "$expected" "$observed" || fail "the observed red set differs from matrix.txt"

# The owner has to be red under its own mutant and under no other, which is
# what "owns" means; matrix_check.py has already refused a file where two
# counted mutants claim one assertion.
while IFS=$'\t' read -r _ mutation owner; do
  [ "$(grep -Fxc "$(printf 'red\t%s\t%s' "$mutation" "$owner")" "$observed")" -eq 1 ] ||
    fail "$mutation does not redden the assertion it owns"
done < <(awk -F '\t' '$1 == "owner" { print }' "$here/matrix.txt")

echo "rc contract ok"
