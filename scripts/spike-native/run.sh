#!/usr/bin/env bash
# Phase -1 seam spike: run the corpus on both backends and diff the output.
#
#   ./scripts/spike-native/run.sh [program.dawn]
#
# Proves the whole chain: TAST -> C (dawn __emitc) -> cc -> a binary whose
# stdout matches the JVM backend's byte for byte.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
prog="${1:-$root/scripts/spike-native/hello.dawn}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cc_bin="${CC:-cc}"

echo "== JVM backend =="
"$root/bin/dawn" run "$prog" >"$work/jvm.out"
cat "$work/jvm.out"

echo
echo "== native backend =="
"$root/bin/dawn" __emitc "$prog" -o "$work/prog.c"
# -fwrapv: Dawn's Int wraps like the JVM's long, and signed overflow is
# otherwise UB. -fno-strict-aliasing: same reason the real backend will need
# it. Both are correctness flags, not tuning.
"$cc_bin" -std=c11 -O2 -fwrapv -fno-strict-aliasing \
  -I "$root/runtime/c" \
  -o "$work/prog" "$work/prog.c" "$root/runtime/c/dawn_rt.c"
"$work/prog" >"$work/native.out"
cat "$work/native.out"

echo
if diff -u "$work/jvm.out" "$work/native.out"; then
  echo "== identical =="
else
  echo "== DIFFER =="
  exit 1
fi
