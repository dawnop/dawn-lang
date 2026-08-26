#!/usr/bin/env bash
# The Int.MIN literal crosses three seams that a backend differential alone
# cannot isolate: the lexer marker, comptime's VInt, and C's spelling of the
# boundary constant. This probe checks both backends against a written answer
# and then inspects the generated translation unit for both CInt and VInt.
#
#   ./scripts/int-min-contract/run.sh
#
# No `--record`: `expected.txt` is the written oracle this contract exists to
# hold both backends to, so it is edited by hand and never taken from a run.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/int-min-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

"$root/bin/dawn" --version >/dev/null

"$root/bin/dawn" run "$here/probe.dawn" >"$work/jvm.out"
if ! diff -u "$here/expected.txt" "$work/jvm.out"; then
  echo "FAIL: Int.MIN JVM output disagrees with the written oracle" >&2
  exit 1
fi

"$root/bin/dawn" __emitc "$here/probe.dawn" -o "$work/probe.c"

if ! grep -Fq 'return INT64_MIN;' "$work/probe.c"; then
  echo "FAIL: live CInt did not use INT64_MIN" >&2
  exit 1
fi
if ! grep -Fq 'dawn_str_of_int(INT64_MIN)' "$work/probe.c"; then
  echo "FAIL: folded VInt did not use INT64_MIN" >&2
  exit 1
fi
if grep -Fq 'INT64_C(-9223372036854775808)' "$work/probe.c"; then
  echo "FAIL: generated C constructs the unrepresentable positive magnitude" >&2
  exit 1
fi

"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror \
  -Wno-unused-variable -Wno-unused-but-set-variable \
  -Wno-unused-parameter -Wno-unused-label \
  -I "$root/runtime/c" \
  -o "$work/probe" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm
"$work/probe" >"$work/native.out"

if ! diff -u "$here/expected.txt" "$work/native.out"; then
  echo "FAIL: Int.MIN native output disagrees with the written oracle" >&2
  exit 1
fi
if ! diff -u "$work/jvm.out" "$work/native.out"; then
  echo "FAIL: Int.MIN JVM and native outputs differ" >&2
  exit 1
fi

echo "Int.MIN contract ok (JVM, native, CInt, VInt)"
