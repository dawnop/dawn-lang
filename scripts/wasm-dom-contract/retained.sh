#!/usr/bin/env bash
# Guest-retained init state, at both execution boundaries.
#
# One JVM process consumes all nine lines. One wasm module instance consumes
# them through nine independent `dawn_turn` calls. The transcript covers an
# event before init, a successful install, an event reading it, a panicking
# init attempt followed by an event that still reads the old state, a new init
# replacing it, and a decoder refusal that likewise leaves it untouched.
#
# The one production mutant makes std/reactor forget the installed root before
# every turn. It must still compile and run on both backends, and both sessions
# must differ from the golden; a compile failure is not credited as coverage.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/wasm-dom-contract"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

dawn="${DAWN_BIN:-$root/bin/dawn}"
dawnc="${DAWNC_BIN:-}"
if [ ! -x "$dawn" ]; then
  echo "MISSING: $dawn is not executable (the JVM leg needs bin/dawn)." >&2
  exit 1
fi
if [ -z "$dawnc" ] || [ ! -x "$dawnc" ]; then
  echo "MISSING: DAWNC_BIN must name the executable native driver." >&2
  exit 1
fi
if ! command -v node >/dev/null; then
  echo "MISSING: node is not on PATH (it hosts the wasm reactor)." >&2
  exit 1
fi

cc_bin="${CC:-cc}"
if ! command -v "$cc_bin" >/dev/null; then
  echo "MISSING: $cc_bin is not on PATH (the retained-root RC probe is C)." >&2
  exit 1
fi

input="$here/retained-input.txt"
expected="$here/retained-expected.txt"
project="$here/retained"

# The root's native ownership is tested at the ABI itself: set takes its own
# reference, get answers an owned reference, replace drops the old root once,
# alias replacement is safe, and atexit clears the last root before observers.
"$cc_bin" -std=c11 -O1 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror -I "$root/runtime/c" \
  -o "$work/retained-rc" "$here/retained-rc.c" "$root/runtime/c/dawn_rt.c" -lm
if ! "$work/retained-rc" >"$work/retained-rc.txt"; then
  echo "FAIL: retained-root C ownership probe failed" >&2
  exit 1
fi
if [ "$(cat "$work/retained-rc.txt")" != $'retained_rc_replace PASS\nretained_rc_exit PASS' ]; then
  echo "FAIL: retained-root C ownership probe changed:" >&2
  cat "$work/retained-rc.txt" >&2
  exit 1
fi
echo "OK   retained C root: get/set/replace/exit ownership"

run_jvm() { # <tree-root> <output>
  "$dawn" run --std "$1/std" "$1/scripts/wasm-dom-contract/retained" \
    <"$input" >"$2" 2>"$work/jvm.err"
}

build_wasm() { # <tree-root> <output>
  "$dawnc" build --std "$1/std" --target wasm --reactor \
    "$1/scripts/wasm-dom-contract/retained" -o "$2" 2>"$work/wasm-build.err"
}

run_wasm() { # <tree-root> <wasm> <output>
  node --no-warnings "$1/scripts/wasm-dom-contract/retained.mjs" \
    "$2" "$input" >"$3" 2>"$work/wasm.err"
}

if ! run_jvm "$root" "$work/jvm.txt"; then
  echo "FAIL: retained JVM session did not run:" >&2
  cat "$work/jvm.err" >&2
  exit 1
fi
if ! cmp -s "$expected" "$work/jvm.txt"; then
  echo "FAIL: retained JVM session changed:" >&2
  diff -u "$expected" "$work/jvm.txt" | head -40 >&2
  exit 1
fi
echo "OK   retained JVM: 9 lines in one process, byte for byte"

if ! build_wasm "$root" "$work/base.wasm"; then
  echo "FAIL: retained wasm fixture did not build:" >&2
  cat "$work/wasm-build.err" >&2
  exit 1
fi
if ! run_wasm "$root" "$work/base.wasm" "$work/wasm.txt"; then
  echo "FAIL: retained wasm session did not run:" >&2
  cat "$work/wasm.err" >&2
  exit 1
fi
if ! cmp -s "$expected" "$work/wasm.txt"; then
  echo "FAIL: retained wasm session changed:" >&2
  diff -u "$expected" "$work/wasm.txt" | head -40 >&2
  exit 1
fi
echo "OK   retained wasm: 9 separate dawn_turn calls, byte for byte"

# Copy only what this project and its compiler-visible std read. The driver is
# outside the tree on purpose: the mutation is in production std source, not
# in a rebuilt harness or a second implementation of the slot.
mkdir -p "$work/mutant/scripts/wasm-dom-contract"
cp -r "$root/std" "$root/packages" "$work/mutant/"
cp -r "$project" "$work/mutant/scripts/wasm-dom-contract/retained"
cp "$here/retained.mjs" "$work/mutant/scripts/wasm-dom-contract/retained.mjs"
slot="$work/mutant/std/reactor.dawn"
before="$(md5sum "$slot")"
sed -i \
  's/        if reactor_state_has() { Some(reactor_state_get()) } else { None }/        None/' \
  "$slot"
if [ "$before" = "$(md5sum "$slot")" ]; then
  echo "FAIL: drop-retained-state mutant did not apply" >&2
  exit 1
fi

if ! run_jvm "$work/mutant" "$work/mutant-jvm.txt"; then
  echo "FAIL: drop-retained-state mutant did not run on the JVM:" >&2
  cat "$work/jvm.err" >&2
  exit 1
fi
if cmp -s "$expected" "$work/mutant-jvm.txt"; then
  echo "FAIL: drop-retained-state mutant survived the JVM session" >&2
  exit 1
fi
echo "OK   mutant drop-retained-state goes red on the JVM"

if ! build_wasm "$work/mutant" "$work/mutant.wasm"; then
  echo "FAIL: drop-retained-state mutant did not build for wasm:" >&2
  cat "$work/wasm-build.err" >&2
  exit 1
fi
if ! run_wasm "$work/mutant" "$work/mutant.wasm" "$work/mutant-wasm.txt"; then
  echo "FAIL: drop-retained-state mutant did not run on wasm:" >&2
  cat "$work/wasm.err" >&2
  exit 1
fi
if cmp -s "$expected" "$work/mutant-wasm.txt"; then
  echo "FAIL: drop-retained-state mutant survived the wasm session" >&2
  exit 1
fi
echo "OK   mutant drop-retained-state goes red on wasm"

echo "retained state ok (JVM process + wasm instance, 1/1 production mutant killed)"
