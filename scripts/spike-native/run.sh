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
#   asan    the same program, under AddressSanitizer, is clean
#
# `asan` exists because reference counting arrived (docs/perceus-design.md
# knife 3): a drop too many is a use-after-free, and a use-after-free reads
# memory that usually still holds the right bytes. It passes the diff, and it
# passes it until the day the allocator reuses the block. The sanitizer is the
# only thing here that sees it at the moment it happens rather than at the
# moment it matters.
#
# Leak detection is ON. It could not be while strings went uncounted (every
# concatenation leaked by design); strings joined the ledger on 2026-07-29,
# and since then a reported leak is a real hole in the counting -- a drop the
# pass forgot, or a runtime function flooring a reference. This is the other
# half of the memory oracle: double-free and use-after-free produce wrong
# answers, leaks only ever produce this report.
#
# One decided exception rides as a marker file: a program that *takes* a
# fault barrier (`catch_fault` with the fault actually raised) leaks what
# the discarded C frames held -- longjmp cannot release them, and that is
# the documented cost of the mechanism, not a counting hole. Such a corpus
# file has `<name>.leaks-on-catch` next to it and runs with leak detection
# off; every other program answers for every byte.
#
# A second marker says a program is *supposed* to die: `<name>.exits-nonzero`.
# Without it a non-zero JVM exit is a failed run, which blocks `diff`,
# `stderr` and `exit` -- and those three are exactly what a program about
# ending the run has to be checked on. The exit code itself is still compared
# between the backends, so the marker says "non-zero is expected here", never
# "any exit will do".
#
# `jvm` and `native` only run when <name>.expect exists. They are the answer
# to codebase-audit.md TEST-01: a differential test alone certifies whatever
# the JVM already does, and a defect the two backends share -- anything
# folded at compile time, for instance -- makes them agree on the wrong
# answer. The .expect file is the only check that was not derived from a
# backend.
#
# A stage only blocks what reads its output. A failed JVM run blocks `diff`,
# `stderr` and `exit` -- the three that compare the backends against each
# other -- and nothing else: `emitc` and `cc` never run the program, and
# `native` is checked against .expect rather than against the JVM. This used
# to block all seven, which meant a program the JVM rejects could never reach
# the C compiler; the Unit descriptor family (#51) hid a C-side defect behind
# a JVM crash for exactly that reason.
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
  # A corpus entry is a single file, or a project directory when it needs a
  # dependency -- `dawn run` and `__emitc` both take either, and a project is
  # the only way to drive a real package (see json_lib).
  progs=("$here"/*.dawn)
  # written as an `if` rather than `[ -f ] && progs+=`: under `set -e` a
  # failing test as the body's last command takes the script with it
  for d in "$here"/*/; do
    if [ -f "$d/dawn.toml" ]; then progs+=("${d%/}"); fi
  done
fi

work="$(mktemp -d)"

# Whether this machine's cc can build with AddressSanitizer. Probed once,
# because a corpus of 23 programs would otherwise ask 23 times, and reported
# as `blocked` rather than as a failure: a missing sanitizer is no evidence
# either way.
asan_ok=1
printf 'int main(void){return 0;}\n' >"$work/asan_probe.c"
if ! "$cc_bin" -fsanitize=address -o "$work/asan_probe" "$work/asan_probe.c" \
  >/dev/null 2>&1; then
  asan_ok=0
  echo "note: $cc_bin cannot build with -fsanitize=address; asan checks skipped"
fi
trap 'rm -rf "$work"' EXIT

# warm the toolchain before any output is captured: bin/dawn announces a
# rebuild on stderr, and stderr is compared now
"$root/bin/dawn" --version > /dev/null

# std, plus stdext/raw.dawn -- the backend primitives std wraps, under names a
# corpus program may write. `io_*`, `bytes_at` and the decoders are std-only
# (types.dawn's `internal` set), and this corpus is the one caller that wants
# the primitive rather than the wrapper: `catch_kinds` asks which barrier takes
# a *fault*, and with `use java` refused on native nothing else can raise one.
# Same arrangement as scripts/array-contract, which reaches `array_*` this way.
# It costs nothing: `--std` reads from disk what the embedded copy would have
# supplied, so a corpus run is no slower for it.
stdcopy="$work/std"
mkdir -p "$stdcopy"
cp "$root"/std/*.dawn "$root/std/modules.txt" "$stdcopy/"
cp "$here/stdext/raw.dawn" "$stdcopy/"
echo raw >> "$stdcopy/modules.txt"

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

  # A failed JVM run blocks only the checks that read its output. `emitc`,
  # `cc` and `native` do not: the first two never run the program, and
  # `native` compares against the written expectation rather than against the
  # JVM. Blocking all seven meant a program the JVM rejects could never reach
  # the C compiler at all -- and in the Unit descriptor family (#51) the JVM
  # was the one that died first, so a whole C-side defect stayed invisible
  # behind it until 2026-07-27.
  jvm_rc=0
  jvm_ran=1
  # a program whose subject is the end of the run declares itself; see the
  # header. This only stops a non-zero code from being read as a broken run --
  # `jvm_rc` keeps the real code, and the `exit` check below still compares it
  # against native's.
  fatal_ok=0
  [ -f "$here/$name.exits-nonzero" ] && fatal_ok=1
  # stdin is /dev/null, not the terminal: a corpus program that reads stdin
  # would otherwise hang the developer's shell and read something different in
  # CI. At /dev/null both backends see end of input, which is itself a case
  # worth agreeing on.
  "$root/bin/dawn" run --std "$stdcopy" "$prog" >"$work/$name.jvm" 2>"$work/$name.jvm.err" \
    </dev/null || jvm_rc=$?
  if [ "$jvm_rc" -ne 0 ] && [ "$fatal_ok" -eq 0 ]; then
    verdict "$name:jvm-run" bad "$(cat "$work/$name.jvm.err")"
    jvm_ran=0
  fi

  if [ "$jvm_ran" -eq 1 ] && [ -f "$expect" ]; then
    if diff -q "$expect" "$work/$name.jvm" >/dev/null; then
      verdict "$name:jvm" ok
    else
      verdict "$name:jvm" bad "$(diff -u "$expect" "$work/$name.jvm")"
    fi
  fi

  if "$root/bin/dawn" __emitc --std "$stdcopy" "$prog" -o "$work/$name.c" \
    >"$work/$name.emitc" 2>&1; then
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
  if "$cc_bin" -std=c11 -O2 -fwrapv -fno-strict-aliasing -pthread \
    -Wall -Wextra -Werror \
    -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label \
    -I "$root/runtime/c" \
    -o "$work/$name.bin" "$work/$name.c" "$root/runtime/c/dawn_rt.c" -lm \
    >"$work/$name.cc" 2>&1; then
    verdict "$name:cc" ok
  else
    verdict "$name:cc" bad "$(cat "$work/$name.cc")"
    for c in native diff stderr exit; do blocked "$name:$c"; done
    continue
  fi

  nat_rc=0
  "$work/$name.bin" >"$work/$name.native" 2>"$work/$name.native.err" \
    </dev/null || nat_rc=$?

  # -O0 so the report names the Dawn function rather than whatever it was
  # inlined into; the answer is not being checked here, only the memory.
  if [ "$asan_ok" -eq 1 ]; then
    if "$cc_bin" -std=c11 -g -O0 -fno-omit-frame-pointer -fwrapv \
      -fno-strict-aliasing -fsanitize=address -pthread \
      -I "$root/runtime/c" \
      -o "$work/$name.asan" "$work/$name.c" "$root/runtime/c/dawn_rt.c" -lm \
      >"$work/$name.asan.cc" 2>&1; then
      asan_rc=0
      leaks=1
      # a taken fault barrier leaks its discarded frames by design -- see
      # the header note; the marker is the opt-out, not a default
      if [ -f "$here/$name.leaks-on-catch" ]; then leaks=0; fi
      ASAN_OPTIONS=detect_leaks=$leaks "$work/$name.asan" \
        >/dev/null 2>"$work/$name.asan.err" </dev/null || asan_rc=$?
      # LeakSanitizer prints its own banner, and a program that already
      # exits 1 (the panic corpus) would hide a leak behind a matching code
      if [ "$asan_rc" -eq "$nat_rc" ] &&
        ! grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$work/$name.asan.err"; then
        verdict "$name:asan" ok
      else
        verdict "$name:asan" bad "$(head -25 "$work/$name.asan.err")"
      fi
    else
      verdict "$name:asan" bad "$(cat "$work/$name.asan.cc")"
    fi
  else
    blocked "$name:asan"
  fi

  if [ -f "$expect" ]; then
    if diff -q "$expect" "$work/$name.native" >/dev/null; then
      verdict "$name:native" ok
    else
      verdict "$name:native" bad "$(diff -u "$expect" "$work/$name.native")"
    fi
  fi

  # the three that compare the two backends against each other, and so are
  # the only ones a failed JVM run has anything to say about
  if [ "$jvm_ran" -eq 0 ]; then
    for c in diff stderr exit; do blocked "$name:$c"; done
    continue
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
