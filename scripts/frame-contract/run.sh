#!/usr/bin/env bash
# Mutant harness for the native backend's unwind frames (docs/frame-slim-design.md).
#
#   ./scripts/frame-contract/run.sh
#
# Two things stop a function's owned slots from being released by the frame
# cleanup, and each is a way to leak that nothing in a program's output shows:
#
#   * the compiler judges a function *quiet* (selfhost/src/c/quiet.dawn) and
#     gives it a frame with no cleanup. If the judgement is wrong, the first
#     caught panic through that function leaks what its slots held;
#   * every ordinary `return` zeroes the frame's count first (`DAWN_RETURN`,
#     dawn_rt.h) so the cleanup's scan is dead on that path. If a slot is
#     still set at that point it is leaked; the DAWN_OWN_CHECK build aborts
#     on exactly that, and the clean run below uses it.
#
# LeakSanitizer is the oracle, so this harness proves the oracle goes red for
# each way of being wrong, on the one program (frame_raise.dawn) that holds an
# owned value across each source of raising:
#
#   clean      the program as compiled: output equals the record, no
#              sanitizer report, and again with DAWN_OWN_CHECK, which aborts
#              if any ordinary return leaves a slot set (the invariant the
#              disarm rests on).
#   engaged    the clean C gives `calm` the cleanup-free frame and every
#              function that can raise the ordinary one. Without this a
#              compiler that never judged anything quiet passes every line
#              below for free.
#   mutants    `DAWN_FRAME_QUIET_MUTANT=<name>` (cdriver.dawn) stops the
#              analysis counting one source of raising; the function for that
#              source must then be judged quiet, the C must differ from the
#              clean C, and the sanitizer must report a leak.
#
# A mutant that survives, or that changes nothing, fails the run: the green of
# a gate that has never seen a red is not evidence.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/frame-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
unset DAWN_FRAME_QUIET_MUTANT

fail=0
verdict() {
  local id="$1" state="$2"
  shift 2
  if [ "$state" = ok ]; then
    printf '  %-28s ok\n' "$id"
  else
    printf '  %-28s FAIL\n' "$id"
    if [ "$#" -gt 0 ]; then printf '%s\n' "$@" | sed -n '1,20p'; fi
    fail=1
  fi
}

probe="$work/asan_probe"
printf 'int main(void){return 0;}\n' > "$probe.c"
if ! "$cc_bin" -fsanitize=address -o "$probe" "$probe.c" 2>/dev/null; then
  echo "error: $cc_bin cannot build with AddressSanitizer; this harness has no oracle without it" >&2
  exit 1
fi

prog="$here/frame_raise.dawn"

# emit <out.c> [mutant]
emit() {
  if [ -n "${2:-}" ]; then
    DAWN_FRAME_QUIET_MUTANT="$2" "$root/bin/dawn" __emitc "$prog" -o "$1" >"$1.err" 2>&1
  else
    "$root/bin/dawn" __emitc "$prog" -o "$1" >"$1.err" 2>&1
  fi
}

# build <c-file> <bin> <runtime-dir> [extra flags...] -- spike-native's asan
# leg: -O0 so a report names the Dawn function, the -f flags are correctness
# flags for this code generator.
build() {
  local c="$1" bin="$2" rt="$3"
  shift 3
  "$cc_bin" -std=c11 -g -O0 -fno-omit-frame-pointer -fwrapv -fexceptions \
    -fno-strict-aliasing -ffp-contract=off -fsanitize=address -pthread "$@" \
    -I "$rt" -o "$bin" "$c" "$rt/dawn_rt.c" -lm >"$bin.cc" 2>&1
}

# run <bin> <stdout> <stderr>; echoes the exit code
run() {
  local rc=0
  ASAN_OPTIONS=detect_leaks=1 "$1" >"$2" 2>"$3" </dev/null || rc=$?
  echo "$rc"
}

leak_red() { grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$1"; }

# frame_of <c-file> <function> -> the frame macro the function opens with
frame_of() {
  awk -v fn="dawn_frame_1raise__$2(" '
    index($0, fn) && /\{$/ { getline nxt; if (match(nxt, /DAWN_(QUIET|OWN)_FRAME/)) print substr(nxt, RSTART, RLENGTH); exit }
  ' "$1"
}

# ---------------------------------------------------------------- clean
if ! emit "$work/clean.c"; then
  verdict clean bad "$(cat "$work/clean.c.err")"
  exit 1
fi
for variant in plain own-check; do
  extra=()
  [ "$variant" = own-check ] && extra=(-DDAWN_OWN_CHECK)
  if ! build "$work/clean.c" "$work/clean.$variant" "$root/runtime/c" "${extra[@]}"; then
    verdict "clean:$variant" bad "$(head -15 "$work/clean.$variant.cc")"
    continue
  fi
  rc="$(run "$work/clean.$variant" "$work/clean.$variant.out" "$work/clean.$variant.err")"
  if [ "$rc" -ne 0 ] || leak_red "$work/clean.$variant.err" ||
    ! diff -q "$here/frame_raise.expect" "$work/clean.$variant.out" >/dev/null; then
    verdict "clean:$variant" bad "exit $rc" "$(head -15 "$work/clean.$variant.err")" \
      "$(diff -u "$here/frame_raise.expect" "$work/clean.$variant.out" 2>/dev/null | sed -n '1,10p')"
  else
    verdict "clean:$variant" ok
  fi
done

# ---------------------------------------------------------------- engaged
engaged=ok
detail=()
if [ "$(frame_of "$work/clean.c" calm)" != DAWN_QUIET_FRAME ]; then
  engaged=bad
  detail+=("calm should have the cleanup-free frame, got '$(frame_of "$work/clean.c" calm)'")
fi
for f in hold via nest quot asker; do
  if [ "$(frame_of "$work/clean.c" "$f")" != DAWN_OWN_FRAME ]; then
    engaged=bad
    detail+=("$f can raise and should keep the cleanup, got '$(frame_of "$work/clean.c" "$f")'")
  fi
done
verdict engaged "$engaged" "${detail[@]:-}"

# ---------------------------------------------------------------- mutants
# <mutant> <function the mutant must wrongly judge quiet>
for spec in intrinsics:hold dynamic:via callees:nest division:quot dynamic:asker; do
  m="${spec%%:*}" f="${spec##*:}"
  id="$m:$f"
  tag="${m}_${f}"
  if ! emit "$work/$tag.c" "$m"; then
    verdict "$id" bad "$(head -5 "$work/$tag.c.err")"
    continue
  fi
  if cmp -s "$work/clean.c" "$work/$tag.c"; then
    verdict "$id" bad "the mutant produced byte-identical C: it never engaged"
    continue
  fi
  if [ "$(frame_of "$work/$tag.c" "$f")" != DAWN_QUIET_FRAME ]; then
    verdict "$id" bad "$f was not judged quiet under the $m mutant"
    continue
  fi
  if ! build "$work/$tag.c" "$work/$tag.bin" "$root/runtime/c"; then
    verdict "$id" bad "$(head -10 "$work/$tag.bin.cc")"
    continue
  fi
  rc="$(run "$work/$tag.bin" "$work/$tag.out" "$work/$tag.err")"
  # the report has to name the function the mutant made quiet: a leak from
  # some other function would be a different bug answering for this mutant
  if leak_red "$work/$tag.err" && grep -q "dawn_frame_1raise__$f" "$work/$tag.err"; then
    verdict "$id" ok
    printf '      %s\n' "$(grep -m1 'SUMMARY' "$work/$tag.err" || echo "exit $rc, no sanitizer summary")"
  else
    verdict "$id" bad "the mutant SURVIVED: no leak report naming $f" "$(head -5 "$work/$tag.err")"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "frame-contract: FAILED" >&2
  exit 1
fi
echo "frame-contract: ok"
