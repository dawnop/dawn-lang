#!/usr/bin/env bash
# The wasm32-wasi build variant, held to the native one byte for byte.
#
# `dawnc build --target wasm` compiles the same emitted C against the same
# runtime source with the wasi rows of dawn_rt.c's #ifdef __wasi__ block in
# place of the POSIX ones. This script is what says those rows are load-
# bearing and honest: two programs (hello, and the RC-heavy stress leg) are
# built for both targets from one driver, run under node's WASI, and their
# stdout must match the native run exactly.
#
# Not in CI yet: the toolchain below is whatever apt shipped, not a pinned
# wasi-sdk with a recorded sha256, and the .dawn-version discipline says a
# gate must pin what it downloads before it gates anyone. Until then this
# runs by hand:
#
#   ./scripts/wasm-contract/run.sh
#   DAWNC_BIN=/path/to/dawnc ./scripts/wasm-contract/run.sh   # reuse a driver
#
# Needs: clang with wasm32-wasi support + lld + wasi-libc + the wasm32
# compiler-rt (Debian/Ubuntu: apt install clang lld wasi-libc
# libclang-rt-18-dev-wasm32), and node >= 20 for node:wasi.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail=0

# ---- toolchain preflight: missing pieces are named, never silent ----------
wasm_cc="${DAWN_WASM_CC:-clang}"
if ! command -v "$wasm_cc" >/dev/null; then
  echo "MISSING: $wasm_cc is not on PATH." >&2
  echo "  Debian/Ubuntu: apt install clang lld wasi-libc libclang-rt-18-dev-wasm32" >&2
  exit 1
fi
echo 'int main(void){return 0;}' >"$work/probe.c"
if ! "$wasm_cc" --target=wasm32-wasi -o "$work/probe.wasm" "$work/probe.c" 2>"$work/probe.err"; then
  echo "MISSING: $wasm_cc cannot link a trivial wasm32-wasi program." >&2
  sed 's/^/  | /' "$work/probe.err" >&2
  echo "  Debian/Ubuntu: apt install lld wasi-libc libclang-rt-18-dev-wasm32" >&2
  echo "  (or point DAWN_WASM_CC at a wasi-sdk clang)" >&2
  exit 1
fi
if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (node:wasi is the runner here)." >&2
  exit 1
fi

# ---- the driver under test ------------------------------------------------
"$root/bin/dawn" --version >/dev/null
DAWNC="${DAWNC_BIN:-}"
if [ -z "$DAWNC" ]; then
  echo "building the native driver from selfhost/src/nmain.dawn..."
  "$root/bin/dawn" __emitc "$root/selfhost/src/nmain.dawn" -o "$work/nmain.c"
  "${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" \
    -o "$work/dawnc" "$work/nmain.c" "$root/runtime/c/dawn_rt.c" -lm
  DAWNC="$work/dawnc"
fi
case "$DAWNC" in /*) ;; *) DAWNC="$root/$DAWNC" ;; esac

# ---- both targets, one oracle: the native run's bytes ----------------------
for prog in hello stress; do
  "$DAWNC" build "$here/$prog.dawn" -o "$work/$prog.native" 2>"$work/$prog.cc-err" ||
    { echo "FAIL: native build of $prog broke:" >&2; cat "$work/$prog.cc-err" >&2; exit 1; }
  "$work/$prog.native" >"$work/$prog.native.out"

  "$DAWNC" build --target wasm "$here/$prog.dawn" -o "$work/$prog.wasm" 2>"$work/$prog.wasm-err" ||
    { echo "FAIL: wasm build of $prog broke:" >&2; cat "$work/$prog.wasm-err" >&2; exit 1; }
  node --no-warnings "$here/runwasi.mjs" "$work/$prog.wasm" >"$work/$prog.wasm.out"

  if cmp -s "$work/$prog.native.out" "$work/$prog.wasm.out"; then
    echo "OK   $prog: wasm stdout == native stdout ($(wc -c <"$work/$prog.wasm.out") bytes)"
  else
    echo "FAIL: $prog stdout differs between native and wasm" >&2
    diff "$work/$prog.native.out" "$work/$prog.wasm.out" | head -20 >&2
    fail=1
  fi
done

# ---- negative control 1: the wasi shim block is load-bearing ----------------
# Remove one shim function from the runtime source and the wasm compile must
# go red -- otherwise this script would also pass over a runtime whose wasi
# block quietly stopped being compiled at all.
"$root/bin/dawn" __emitc "$here/hello.dawn" -o "$work/hello.c"
sed '/^static _Noreturn void dawn_wasi_no_unwinder(void) {$/,/^}$/d' \
  "$root/runtime/c/dawn_rt.c" >"$work/dawn_rt_maimed.c"
if ! grep -q dawn_wasi_no_unwinder "$root/runtime/c/dawn_rt.c"; then
  echo "FAIL: negative control is stale -- dawn_wasi_no_unwinder is gone from dawn_rt.c" >&2
  fail=1
elif "$wasm_cc" --target=wasm32-wasi -std=c11 -O2 -fwrapv -fno-strict-aliasing \
  -Wno-parentheses-equality -I "$root/runtime/c" \
  -o "$work/maimed.wasm" "$work/hello.c" "$work/dawn_rt_maimed.c" -lm 2>/dev/null; then
  echo "FAIL: a runtime missing a wasi shim function still compiled -- the contract is blind" >&2
  fail=1
else
  echo "OK   negative control: removing a wasi shim function reds the wasm compile"
fi

# ---- negative control 2: a missing toolchain is diagnosed, not mumbled ------
if DAWN_WASM_CC=/nonexistent/clang "$DAWNC" build --target wasm "$here/hello.dawn" \
  -o "$work/never.wasm" >"$work/diag.out" 2>"$work/diag.err"; then
  echo "FAIL: --target wasm with a nonexistent compiler exited 0" >&2
  fail=1
elif ! grep -q "wasi-sdk" "$work/diag.err"; then
  echo "FAIL: the missing-toolchain failure did not print the install hint:" >&2
  sed 's/^/  | /' "$work/diag.err" >&2
  fail=1
else
  echo "OK   negative control: a missing wasm toolchain names what to install"
fi

if [ "$fail" != 0 ]; then exit 1; fi
echo "wasm contract ok (hello, stress, 2 negative controls)"
