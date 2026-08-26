#!/usr/bin/env bash
# The wasm32-wasi build variant, held to the native one byte for byte.
#
# `dawnc build --target wasm` compiles the same emitted C against the same
# runtime source with the wasi rows of dawn_rt.c's #ifdef __wasi__ block in
# place of the POSIX ones, plus the one C++ catch shim (dawn_rt_wasi_eh.cc).
# This script is what says those rows are load-bearing and honest: the
# corpus (hello, the RC-heavy stress leg, and the failure-runtime leg) is
# built for both targets from one driver, run under node's WASI, and stdout
# must match the native run exactly.
#
# The failure leg is the A1 shadow-stack landing (dawn_rt.c, "landing at a
# handler on wasm32-wasi"): catch/bracket/raise on wasm, same bytes as
# native, plus two oracles stdout cannot carry --
#
#   rc-balance   the runtime's own leak ledger (births minus deaths, wasi
#                only), printed to stderr under DAWN_RC_BALANCE. Zero after
#                every clean run is this target's LeakSanitizer: the raise
#                walk really ran the discarded frames' drops.
#   uncaught     an unhandled panic reports to stderr and exits 1 on both
#                targets, stdout up to that point identical.
#
# In CI on a pinned wasi-sdk (the wasm-target job in
# .github/workflows/gates.yml); by hand it takes whatever it is pointed at:
#
#   ./scripts/wasm-contract/run.sh
#   DAWN_WASM_CC=/path/to/wasi-sdk/bin/clang ./scripts/wasm-contract/run.sh
#   DAWNC_BIN=/path/to/dawnc ./scripts/wasm-contract/run.sh   # reuse a driver
#
# Needs: clang 20 or newer with a wasm32 sysroot + lld + wasi-libc + the
# wasm32 compiler-rt (Debian/Ubuntu: apt install clang-20 lld wasi-libc
# libclang-rt-20-dev-wasm32; the C++ shim uses no C++ runtime, so nothing
# more), and node >= 20 for node:wasi. clang 18 is too old: its assembler
# crashes on the exception tag in runtime/c/dawn_rt_wasi_tag.c.
#
# The triple is not hardcoded. wasi-sdk 31 deprecated wasm32-wasi and 34
# removed it; apt's wasi-libc has only wasm32-wasi and no wasm32-wasip1. The
# preflight below asks the compiler which one it has a sysroot for, and the
# driver asks the same question the same way, so both ends of that range stay
# buildable from one script.
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
  echo "  Debian/Ubuntu: apt install clang-20 lld wasi-libc libclang-rt-20-dev-wasm32" >&2
  exit 1
fi
# Which triple this compiler has a sysroot for, the same question and the
# same answer `cc_build_for` asks in the driver: wasi-sdk 34 removed
# wasm32-wasi, apt's wasi-libc has only wasm32-wasi, and the builds below
# must use whichever the driver picked or they would test a different link.
wasm_target=wasm32-wasi
crt1="$("$wasm_cc" --target=wasm32-wasip1 -print-file-name=crt1.o 2>/dev/null || true)"
[ -f "$crt1" ] && wasm_target=wasm32-wasip1
echo 'int main(void){return 0;}' >"$work/probe.c"
if ! "$wasm_cc" --target="$wasm_target" -o "$work/probe.wasm" "$work/probe.c" 2>"$work/probe.err"; then
  echo "MISSING: $wasm_cc cannot link a trivial $wasm_target program." >&2
  sed 's/^/  | /' "$work/probe.err" >&2
  echo "  Debian/Ubuntu: apt install lld wasi-libc libclang-rt-20-dev-wasm32" >&2
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

# The manual builds below (negative controls) must be the same compile
# `dawnc build --target wasm` runs, or they would test a pipeline nobody
# ships. One spelling, used everywhere -- including the exception tag's own
# translation unit (runtime/c/dawn_rt_wasi_tag.c), which is a link input on
# both sides and whose absence here would red the mutants for the wrong
# reason on any wasi-sdk from 31 up.
wasm_shim_build() { # <src.cc> <out.o>
  "$wasm_cc" --target="$wasm_target" -x c++ -std=c++14 -O2 -fno-rtti \
    -fwasm-exceptions -c "$1" -o "$2"
}
wasm_tag_build() { # <src.c> <out.o>
  "$wasm_cc" --target="$wasm_target" -std=c11 -O2 -c "$1" -o "$2"
}
wasm_c_build() { # <out.wasm> <main.c> <dawn_rt.c> <shim.o> <include-dir> <tag.o>
  "$wasm_cc" --target="$wasm_target" -std=c11 -O2 -fwrapv -fwasm-exceptions \
    -fno-strict-aliasing -Wno-parentheses-equality -I "$5" \
    -o "$1" "$2" "$3" "$4" "$6" -lm
}

# ---- both targets, one oracle: the native run's bytes ----------------------
# Every wasm run also reports the leak ledger; zero is the only green.
for prog in hello stress failure; do
  "$DAWNC" build "$here/$prog.dawn" -o "$work/$prog.native" 2>"$work/$prog.cc-err" ||
    { echo "FAIL: native build of $prog broke:" >&2; cat "$work/$prog.cc-err" >&2; exit 1; }
  "$work/$prog.native" >"$work/$prog.native.out"

  "$DAWNC" build --target wasm "$here/$prog.dawn" -o "$work/$prog.wasm" 2>"$work/$prog.wasm-err" ||
    { echo "FAIL: wasm build of $prog broke:" >&2; cat "$work/$prog.wasm-err" >&2; exit 1; }
  DAWN_RC_BALANCE=1 node --no-warnings "$here/runwasi.mjs" "$work/$prog.wasm" \
    >"$work/$prog.wasm.out" 2>"$work/$prog.wasm.err"

  if cmp -s "$work/$prog.native.out" "$work/$prog.wasm.out"; then
    echo "OK   $prog: wasm stdout == native stdout ($(wc -c <"$work/$prog.wasm.out") bytes)"
  else
    echo "FAIL: $prog stdout differs between native and wasm" >&2
    diff "$work/$prog.native.out" "$work/$prog.wasm.out" | head -20 >&2
    fail=1
  fi
  if grep -q '^rc-balance: 0$' "$work/$prog.wasm.err"; then
    echo "OK   $prog: rc-balance 0 (every counted object released)"
  else
    echo "FAIL: $prog leaked on wasm: $(grep '^rc-balance:' "$work/$prog.wasm.err" || echo 'no ledger line at all')" >&2
    fail=1
  fi
done

# ---- the uncaught leg: report, exit 1, no landing machinery involved -------
prog=failure_uncaught
"$DAWNC" build "$here/$prog.dawn" -o "$work/$prog.native" 2>"$work/$prog.cc-err" ||
  { echo "FAIL: native build of $prog broke:" >&2; cat "$work/$prog.cc-err" >&2; exit 1; }
set +e
"$work/$prog.native" >"$work/$prog.native.out" 2>"$work/$prog.native.err"
native_rc=$?
set -e
"$DAWNC" build --target wasm "$here/$prog.dawn" -o "$work/$prog.wasm" 2>"$work/$prog.wasm-err" ||
  { echo "FAIL: wasm build of $prog broke:" >&2; cat "$work/$prog.wasm-err" >&2; exit 1; }
set +e
node --no-warnings "$here/runwasi.mjs" "$work/$prog.wasm" \
  >"$work/$prog.wasm.out" 2>"$work/$prog.wasm.err"
wasm_rc=$?
set -e
if [ "$native_rc" = 1 ] && [ "$wasm_rc" = 1 ] &&
  cmp -s "$work/$prog.native.out" "$work/$prog.wasm.out" &&
  grep -q '^panic: UNCAUGHT-' "$work/$prog.native.err" &&
  grep -q '^panic: UNCAUGHT-' "$work/$prog.wasm.err"; then
  echo "OK   $prog: both targets report the panic and exit 1, same stdout"
else
  echo "FAIL: $prog diverged (native exit $native_rc, wasm exit $wasm_rc)" >&2
  fail=1
fi

# ---- negative control 1: the wasi failure runtime is load-bearing ----------
# Remove the shadow-stack registration from the runtime source and the wasm
# link must go red (every emitted frame with owned locals calls it) --
# otherwise this script would also pass over a runtime whose wasi block
# quietly stopped being compiled at all.
"$root/bin/dawn" __emitc "$here/failure.dawn" -o "$work/failure.c"
wasm_shim_build "$root/runtime/c/dawn_rt_wasi_eh.cc" "$work/eh.o"
wasm_tag_build "$root/runtime/c/dawn_rt_wasi_tag.c" "$work/tag.o"
sed '/^void dawn_wasi_own_push(void \*frame) {$/,/^}$/d' \
  "$root/runtime/c/dawn_rt.c" >"$work/dawn_rt_maimed.c"
if ! grep -q dawn_wasi_own_push "$root/runtime/c/dawn_rt.c"; then
  echo "FAIL: negative control is stale -- dawn_wasi_own_push is gone from dawn_rt.c" >&2
  fail=1
elif wasm_c_build "$work/maimed.wasm" "$work/failure.c" "$work/dawn_rt_maimed.c" \
  "$work/eh.o" "$root/runtime/c" "$work/tag.o" 2>/dev/null; then
  echo "FAIL: a runtime missing the shadow-stack push still linked -- the contract is blind" >&2
  fail=1
else
  echo "OK   negative control: removing the shadow-stack push reds the wasm link"
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

# ---- production mutants: the failure checks must be able to go red ---------
# Each mutant is a real wrong runtime, built with the shipping pipeline and
# held against the same three checks the ordinary leg uses (stdout bytes,
# exit code, rc-balance). A mutant that passes all three means the contract
# has no teeth and this script must say so.
run_mutant() { # <name> <maimed dawn_rt.c>
  local name="$1" rt="$2" mrc
  wasm_c_build "$work/$name.wasm" "$work/failure.c" "$rt" \
    "$work/eh.o" "$root/runtime/c" "$work/tag.o" 2>"$work/$name.cc-err" ||
    { echo "FAIL: mutant $name did not even compile:" >&2
      head -5 "$work/$name.cc-err" >&2; fail=1; return; }
  set +e
  DAWN_RC_BALANCE=1 node --no-warnings "$here/runwasi.mjs" "$work/$name.wasm" \
    >"$work/$name.out" 2>"$work/$name.err"
  mrc=$?
  set -e
  if [ "$mrc" = 0 ] && cmp -s "$work/failure.native.out" "$work/$name.out" &&
    grep -q '^rc-balance: 0$' "$work/$name.err"; then
    echo "FAIL: mutant $name passed every check -- the failure contract is toothless" >&2
    fail=1
  else
    echo "OK   negative control: mutant $name goes red" \
      "(exit $mrc; $(grep '^rc-balance:' "$work/$name.err" || echo 'stdout/ledger diverged'))"
  fi
}

# Mutant A: the raise walk stops releasing what the discarded frames held.
# The program still answers correctly -- this is precisely the leak stdout
# cannot see, and rc-balance is the check that must catch it.
sed 's/if (fr\[i\] != NULL) dawn_drop(fr\[i\]);/(void)fr[i];/' \
  "$root/runtime/c/dawn_rt.c" >"$work/dawn_rt_noclean.c"
if cmp -s "$root/runtime/c/dawn_rt.c" "$work/dawn_rt_noclean.c"; then
  echo "FAIL: mutant A is stale -- the raise walk's drop line moved" >&2
  fail=1
else
  run_mutant noclean "$work/dawn_rt_noclean.c"
fi

# Mutant B: no landing ever matches its handler. Every caught failure is
# thrown onward past its target; the run cannot end well, and stdout or the
# exit code is the check that must catch it.
sed 's/dawn_unwind_target != \&h/1/' \
  "$root/runtime/c/dawn_rt.c" >"$work/dawn_rt_nomatch.c"
if cmp -s "$root/runtime/c/dawn_rt.c" "$work/dawn_rt_nomatch.c"; then
  echo "FAIL: mutant B is stale -- the landing identity test moved" >&2
  fail=1
else
  run_mutant nomatch "$work/dawn_rt_nomatch.c"
fi

if [ "$fail" != 0 ]; then exit 1; fi
echo "wasm contract ok (hello, stress, failure, failure_uncaught, 4 negative controls)"
