#!/usr/bin/env bash
# Differential harness: compile a Dawn program with both backends and check
# them against each other and against a written-down expectation.
#
#   ./scripts/spike-native/run.sh                  # every corpus file
#   ./scripts/spike-native/run.sh prog.dawn ...    # just these
#
# This is the first of the three acceptance gates in
# docs/native-backend-plan.md 5.
#
# Each corpus yields up to seven named checks:
#
#   emitc   `dawn __emitc` produced C
#   cc      that C compiles
#   jvm     the JVM's stdout matches <name>.expect
#   native  the native binary's stdout matches <name>.expect
#   diff    the two backends' stdout agree
#   stderr  the two backends' stderr agree
#   exit    the two backends' exit codes agree
#
# `jvm` and `native` only run when <name>.expect exists. They are the answer
# to codebase-audit.md TEST-01: a differential test alone certifies whatever
# the JVM already does, and a defect the two backends share -- anything
# folded at compile time, for instance -- makes them agree on the wrong
# answer. The .expect file is the only check that was not derived from a
# backend.
#
# A check listed in known-red.txt is allowed to fail. That file is a ratchet,
# not a mute button: an unlisted failure is fatal, and so is a *listed* check
# that starts passing -- fix the defect and the line has to go with it.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/spike-native"
cc_bin="${CC:-cc}"
known="$here/known-red.txt"

if [ "$#" -gt 0 ]; then
  progs=("$@")
else
  progs=("$here"/*.dawn)
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# warm the toolchain before any output is captured: bin/dawn announces a
# rebuild on stderr, and stderr is compared now
"$root/bin/dawn" --version > /dev/null

fail=0
known_hit=0

is_known() {
  [ -f "$known" ] || return 1
  grep -qE "^[[:space:]]*$1([[:space:]]|#|\$)" "$known"
}

# verdict <corpus:check> <ok|bad> [detail...]
verdict() {
  local id="$1" state="$2"
  shift 2
  if [ "$state" = ok ]; then
    if is_known "$id"; then
      printf '  %-28s FIXED -- delete it from known-red.txt\n' "$id"
      fail=1
    fi
    return
  fi
  if is_known "$id"; then
    printf '  %-28s known-red\n' "$id"
    known_hit=$((known_hit + 1))
  else
    printf '  %-28s FAIL\n' "$id"
    if [ "$#" -gt 0 ]; then printf '%s\n' "$@" | head -30; fi
    fail=1
  fi
}

# a check that could not run because an earlier stage failed. Never fatal and
# never a ratchet trip: there is no evidence either way.
blocked() { printf '  %-28s blocked\n' "$1"; }

for prog in "${progs[@]}"; do
  name="$(basename "$prog" .dawn)"
  expect="$here/$name.expect"
  echo "$name"

  jvm_rc=0
  "$root/bin/dawn" run "$prog" >"$work/$name.jvm" 2>"$work/$name.jvm.err" || jvm_rc=$?
  if [ "$jvm_rc" -ne 0 ]; then
    verdict "$name:jvm-run" bad "$(cat "$work/$name.jvm.err")"
    for c in emitc cc jvm native diff stderr exit; do blocked "$name:$c"; done
    continue
  fi

  if [ -f "$expect" ]; then
    if diff -q "$expect" "$work/$name.jvm" >/dev/null; then
      verdict "$name:jvm" ok
    else
      verdict "$name:jvm" bad "$(diff -u "$expect" "$work/$name.jvm")"
    fi
  fi

  if "$root/bin/dawn" __emitc "$prog" -o "$work/$name.c" >"$work/$name.emitc" 2>&1; then
    verdict "$name:emitc" ok
  else
    verdict "$name:emitc" bad "$(cat "$work/$name.emitc")"
    for c in cc native diff stderr exit; do blocked "$name:$c"; done
    continue
  fi

  # -fwrapv: Dawn's Int wraps like the JVM's long, and signed overflow is
  # otherwise UB. -fno-strict-aliasing: same reason the real backend needs
  # it. Both are correctness flags, not tuning.
  #
  # -Werror is a real gate: a Core type that reaches C wrong shows up first
  # as an int-from-pointer warning, long before it shows up as a wrong
  # answer. That is how the pattern-binding types were caught. The three
  # -Wno- flags cover noise a code generator legitimately produces.
  if "$cc_bin" -std=c11 -O2 -fwrapv -fno-strict-aliasing \
    -Wall -Wextra -Werror \
    -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label \
    -I "$root/runtime/c" \
    -o "$work/$name.bin" "$work/$name.c" "$root/runtime/c/dawn_rt.c" \
    >"$work/$name.cc" 2>&1; then
    verdict "$name:cc" ok
  else
    verdict "$name:cc" bad "$(cat "$work/$name.cc")"
    for c in native diff stderr exit; do blocked "$name:$c"; done
    continue
  fi

  nat_rc=0
  "$work/$name.bin" >"$work/$name.native" 2>"$work/$name.native.err" || nat_rc=$?

  if [ -f "$expect" ]; then
    if diff -q "$expect" "$work/$name.native" >/dev/null; then
      verdict "$name:native" ok
    else
      verdict "$name:native" bad "$(diff -u "$expect" "$work/$name.native")"
    fi
  fi

  if diff -q "$work/$name.jvm" "$work/$name.native" >/dev/null; then
    verdict "$name:diff" ok
  else
    verdict "$name:diff" bad \
      "$(diff -u --label jvm "$work/$name.jvm" --label native "$work/$name.native")"
  fi

  if diff -q "$work/$name.jvm.err" "$work/$name.native.err" >/dev/null; then
    verdict "$name:stderr" ok
  else
    verdict "$name:stderr" bad \
      "$(diff -u --label jvm "$work/$name.jvm.err" --label native "$work/$name.native.err")"
  fi

  if [ "$jvm_rc" -eq "$nat_rc" ]; then
    verdict "$name:exit" ok
  else
    verdict "$name:exit" bad "jvm exit $jvm_rc, native exit $nat_rc"
  fi
done

echo
if [ "$fail" -ne 0 ]; then
  echo "differential FAILED"
elif [ "$known_hit" -gt 0 ]; then
  echo "no new failures ($known_hit known-red, see known-red.txt)"
else
  echo "differential ok"
fi

exit "$fail"
