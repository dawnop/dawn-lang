#!/usr/bin/env bash
# Contract test for `dawn_ctl_live`, the native runtime's memory oracle for
# dropped continuations (docs/oneshot-design.md 11.10).
#
#   ./scripts/ctl-live-contract/run.sh
#
# ## The debt this discharges
#
# One-shot resumption on the native backend runs every activation on a carrier
# thread, and a continuation nobody resumes is a thread nobody wakes. Reclaiming
# it is the runtime's job, and LeakSanitizer cannot check that job: a parked
# thread's stack is a root, so everything the abandoned frames hold stays
# reachable and a leak of that shape is reported as nothing at all (measured:
# 200 dropped continuations, 800 KB, zero reports -- 3.2, reproduced under this
# mechanism in 11.10). So the runtime counts instead. `dawn_ctl_live` goes up
# when a carrier is spawned and down when it is reclaimed, and a process that
# ends with it non-zero prints a line and exits 70.
#
# A correct program says nothing about that counter. `ctl_resume` and
# `ctl_nested` in the differential corpus run it every time and would go red if
# reclaiming broke -- but they would go equally green if the counter itself were
# deleted, and "never leaked" and "never looked" are the same transcript. Knife
# 5 pinned the counter with four hand-run mutations and wrote down that they
# were hand-run. This is the standing form of two of them.
#
# ## What it does
#
# One small Dawn program (live.dawn), compiled to C once, then built and run
# against four runtimes: the tree's own, and one copy per mutation in
# matrix.txt. Every build answers a roster of four assertions -- three off a
# plain build, one off a sanitized one -- and the red set is compared with the
# record in both directions. A recorded red that stays green fails, an
# unrecorded red fails, and a `counted` mutant that reddens nothing fails, which
# is what makes deleting the counter a red rather than a quieter gate.
#
# The two counted mutants are the pair the design argues about. Both lose the
# same memory on the same path; one is invisible to the sanitizer and visible to
# the counter, the other the other way round. Each is therefore the control for
# the other, and the matrix records the green as deliberately as the red.
#
# ## Cost
#
# One `dawn __emitc`, eight `cc` invocations and eight process runs; ~15s
# locally. It rides in the `contracts` job for the reason the atomic-write step
# does: it wants both a JVM compile and a `cc`, and that job is not the critical
# path.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/ctl-live-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The same three correctness flags the differential builds emitted C with
# (scripts/spike-native/run.sh says why each is correctness rather than tuning),
# and the same four -Wno- flags covering noise a code generator legitimately
# produces.
cflags=(-std=c11 -fwrapv -fexceptions -fno-strict-aliasing -pthread)
warn=(-Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-unused-parameter -Wno-unused-label)

# Every run of the program is bounded. A broken reclaim is a wait for a baton
# nobody will pass, and a gate that hangs is a gate somebody reruns rather than
# reads.
run_timeout=60

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

build_plain() { # runtime-dir output
  "$cc_bin" "${cflags[@]}" -O1 "${warn[@]}" -I "$1" \
    -o "$2" "$work/live.c" "$1/dawn_rt.c" -lm
}

# -O0 and frame pointers so a leak report names the Dawn function rather than
# whatever it was inlined into; the answers are read off the plain build.
build_asan() { # runtime-dir output
  "$cc_bin" "${cflags[@]}" -g -O0 -fno-omit-frame-pointer -fsanitize=address \
    "${warn[@]}" -I "$1" -o "$2" "$work/live.c" "$1/dawn_rt.c" -lm
}

# The roster, in the order matrix.txt names it. `dir` holds the two binaries and
# receives the transcripts; the verdicts go to $dir/observed.txt as the same
# `<name> PASS|FAIL` stream whichever build produced them.
observe() { # dir
  local dir="$1" rc=0 arc=0
  : > "$dir/observed.txt"
  set +e
  timeout "$run_timeout" "$dir/plain" > "$dir/out.txt" 2> "$dir/err.txt"
  rc=$?
  set -e
  [ "$rc" -ne 124 ] || fail "the plain build did not finish in ${run_timeout}s"
  [ "$rc" -lt 128 ] || fail "the plain build died on signal $((rc - 128))"

  verdict "$dir" answers "$(diff -q "$here/live.expect" "$dir/out.txt" >/dev/null && echo y)"
  verdict "$dir" exit_status "$([ "$rc" -eq 0 ] && echo y)"
  verdict "$dir" no_live_continuations_at_exit \
    "$(grep -q 'still live at exit' "$dir/err.txt" || echo y)"

  set +e
  ASAN_OPTIONS=detect_leaks=1 timeout "$run_timeout" "$dir/asan" \
    > /dev/null 2> "$dir/asan.err"
  arc=$?
  set -e
  [ "$arc" -ne 124 ] || fail "the sanitized build did not finish in ${run_timeout}s"
  # A death by signal is refused rather than read: the verdict below is the
  # sanitizer's report, and a process killed before it printed one has not
  # answered the question.
  [ "$arc" -lt 128 ] || fail "the sanitized build died on signal $((arc - 128))"
  verdict "$dir" no_leaks \
    "$(grep -Eq 'ERROR: (Address|Leak)Sanitizer' "$dir/asan.err" || echo y)"
}

verdict() { # dir name ok-or-empty
  if [ -n "$3" ]; then
    printf '%s PASS\n' "$2" >> "$1/observed.txt"
  else
    printf '%s FAIL\n' "$2" >> "$1/observed.txt"
  fi
}

field() { # kind [key]
  if [ "$#" -eq 1 ]; then
    awk -F '\t' -v k="$1" '$1 == k { print $2 }' "$here/matrix.txt"
  else
    awk -F '\t' -v k="$1" -v m="$2" '$1 == k && $2 == m { print $3 }' "$here/matrix.txt"
  fi
}

# ---- the roster the matrix names has to be the roster the harness runs ----
field assert > "$work/roster.txt"
[ -s "$work/roster.txt" ] || fail "matrix.txt names no assertions"

echo "== emit =="
"$root/bin/dawn" __emitc "$here/live.dawn" -o "$work/live.c"

echo "== baseline =="
mkdir -p "$work/base"
build_plain "$root/runtime/c" "$work/base/plain"
build_asan "$root/runtime/c" "$work/base/asan"
observe "$work/base"
cat "$work/base/observed.txt"
awk '{ print $1 }' "$work/base/observed.txt" > "$work/ran.txt"
diff -u "$work/roster.txt" "$work/ran.txt" ||
  fail "matrix.txt names a different roster than run.sh observes"
if grep -q ' FAIL$' "$work/base/observed.txt"; then
  cat "$work/base/err.txt" "$work/base/asan.err" >&2
  fail "the unmutated runtime does not satisfy the contract"
fi

# ---- the mutants ----------------------------------------------------------
echo "== mutants =="
observed="$work/observed.txt"
: > "$observed"
while IFS=$'\t' read -r _ mutation role; do
  [ -n "$mutation" ] || continue
  dir="$work/$mutation"
  mkdir -p "$dir"
  cp "$root/runtime/c/dawn_rt.c" "$root/runtime/c/dawn_rt.h" "$dir/"
  python3 "$here/mutate.py" "$mutation" "$dir"
  cmp -s "$root/runtime/c/dawn_rt.c" "$dir/dawn_rt.c" &&
    fail "$mutation changed nothing"

  build_plain "$dir" "$dir/plain" > "$dir/cc.out" 2>&1 ||
    { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
  build_asan "$dir" "$dir/asan" >> "$dir/cc.out" 2>&1 ||
    { cat "$dir/cc.out" >&2; fail "$mutation did not compile"; }
  observe "$dir"

  reds="$(awk '$2 == "FAIL" { print $1 }' "$dir/observed.txt")"
  if [ "$role" = benign ]; then
    # The whole claim is a green, so both halves are checked: no assertion
    # reddens, and the program's output is what the unmutated runtime printed.
    [ -z "$reds" ] || { echo "$reds" >&2; fail "$mutation is not benign"; }
    diff -u "$work/base/out.txt" "$dir/out.txt" ||
      fail "$mutation changed an answer nothing here is entitled to move"
    echo "OK   $mutation (benign)"
    continue
  fi
  [ "$role" = counted ] || fail "$mutation has an unknown role '$role'"
  [ -n "$reds" ] || fail "$mutation reddened no assertion"

  # The control may not be the way a mutant reddens: a mutant that stopped the
  # program printing its four lines has broken something other than the
  # property it is named for.
  for c in $(field control); do
    if grep -qx "$c" <<< "$reds"; then fail "$mutation reddened the control $c"; fi
  done
  owner="$(field owner "$mutation")"
  [ -n "$owner" ] || fail "$mutation is counted and owns no assertion"
  grep -qx "$owner" <<< "$reds" ||
    fail "$mutation does not redden the assertion it owns ($owner)"

  # The sentence the counter reaches, where the matrix records one. Without
  # this the roster only says the report stayed quiet, which a runtime that had
  # stopped counting would satisfy just as well.
  says="$(field says "$mutation")"
  if [ -n "$says" ]; then
    grep -qxF "$says" "$dir/err.txt" ||
      { cat "$dir/err.txt" >&2
        fail "$mutation did not print the recorded line: $says"; }
  fi

  while read -r a; do printf 'red\t%s\t%s\n' "$mutation" "$a" >> "$observed"; done \
    <<< "$reds"
  echo "OK   $mutation"
done < <(awk -F '\t' '$1 == "role"' "$here/matrix.txt")

# Both directions, in roster order so the diff is stable: a recorded red that
# stayed green is as much a finding as an unrecorded one.
awk -F '\t' '$1 == "red" { printf "red\t%s\t%s\n", $2, $3 }' "$here/matrix.txt" |
  sort > "$work/recorded.txt"
[ -s "$work/recorded.txt" ] || fail "matrix.txt records no red set at all"
sort "$observed" > "$work/observed.sorted"
diff -u "$work/recorded.txt" "$work/observed.sorted" ||
  fail "the recorded red sets are not the ones observed"

echo "ctl-live contract ok"
