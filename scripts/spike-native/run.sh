#!/usr/bin/env bash
# Differential harness: compile a Dawn program with both backends and check
# them against each other and against a written-down expectation.
#
#   ./scripts/spike-native/run.sh                  # every corpus file
#   ./scripts/spike-native/run.sh prog.dawn ...    # just these
#   ./scripts/spike-native/run.sh --shard 1/4      # one round-robin slice
#   SPIKE_JOBS=1 ./scripts/spike-native/run.sh     # one at a time
#
# There is no `--record`, on purpose, and the reason is the paragraph below
# about what `<name>.expect` is for: it is the one check in this harness not
# derived from a backend, so it is written by hand from what the program is
# supposed to print. A new corpus entry gets its `.expect` written the same
# way; if the diff surprises you, the diff is the finding.
#
# Corpus entries are independent -- each one compiles and runs a program of its
# own -- so they run in parallel, min(nproc, 4) at a time. That is scheduling
# only: every entry still runs every check it ran serially, the transcript is
# replayed in corpus order rather than completion order, and an entry that
# fails still fails the run by name. See the driver at the bottom for how the
# per-entry statuses are collected, and why a worker that is *killed* counts as
# a failure rather than as nothing.
#
# The same independence is what lets the corpus be dealt across CI jobs.
# `--shard I/N` runs every Nth entry of scripts/spike-native/matrix.txt, which
# lists the corpus in run order; the driver holds that file and the corpus on
# disk equal in both directions before it runs anything, so a new .dawn file
# nobody recorded and a recorded line with no file behind it are both red at
# startup rather than quietly out of the rotation. Sharding was not a
# preference: the job was 1119s against a 660s run pole on 2026-09-03, and the
# cost is the corpus growing (87 entries in August, 122 now) times a std every
# program pays for, not any one entry.
#
# What sharding cannot reach is a verdict. Every check an entry has is made
# inside the one shard that runs it, and known-red.txt is read per check by
# name, so a shard's ratchet is the same ratchet -- except for the one clause
# that is about the whole list rather than an entry: a *listed* check that
# starts passing is fatal, and a shard only sees its own quarter of the list,
# so an entry that got fixed is reported by whichever shard owns it. The new
# way to be wrong is a slice nobody ran, which a shard cannot notice about
# itself: each records what it ran (scripts/mutant-coverage/shard.sh) and
# scripts/mutant-coverage/check.py holds the union to matrix.txt.
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
# Every program answers for every byte, taken barriers included. There used
# to be a `<name>.leaks-on-catch` marker here -- a taken barrier leaked what
# the discarded C frames held, "the documented cost of the mechanism" -- and
# seven corpus files rode it. #193 made a raise a forced unwind that runs the
# discarded frames' cleanups (recover_live / recover_msg / recover_bracket
# are the corpora that hold the fix shut), and the marker mechanism went with
# the last marker: an exemption nobody uses is a hiding place for the next
# regression, nothing else.
#
# One marker says a program is *supposed* to die: `<name>.exits-nonzero`.
# Without it a non-zero JVM exit is a failed run, which blocks `diff`,
# `stderr` and `exit` -- and those three are exactly what a program about
# ending the run has to be checked on. The exit code itself is still compared
# between the backends, so the marker says "non-zero is expected here", never
# "any exit will do".
#
# The other marker says a program has no native half at all:
# `<name>.jvm-only`. What earns it is `use java`, which the native backend
# refuses as a decision (`emitc` says so in as many words), so a program whose
# subject *is* that boundary cannot be differentiated. Its C-side checks report
# `blocked`.
#
# The alternative was known-red.txt entries that nobody would ever be able to
# delete, which would make that file mean two different things. The marker is
# checked rather than believed: `emitc` still runs, and a marker on a program it
# compiles is a failure by that name. Measured by putting the marker on
# `effect_handler`, which compiles fine, and watching `effect_handler: jvm-only`
# go red.
#
# The `ctl_*` programs used to wear it for a second reason -- one-shot
# resumption had no native half -- and that is where the marker earned its
# keep: when the native backend grew a driving loop of its own
# (docs/oneshot-design.md 11.10), deleting the markers was the whole of making
# the differential start running, against .expect files written from the JVM's
# answers before there was anything to compare them to.
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
self="$here/run.sh"

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

# One corpus entry, start to finish.
#
# The driver runs these in parallel (see the worker branch below), so nothing
# in here may depend on another entry: every file it writes is keyed by $name
# under $work, and the two tallies it moves -- `fail` and `known_hit` -- are
# this process's own copies, handed back to the driver through $work/logs
# rather than shared. `continue` was a `for` body's early exit; it is `return`
# now, and means the same thing.
run_corpus() {
  local prog="$1" name expect jvm_rc jvm_ran fatal_ok nat_rc asan_rc c arg
  local -a prog_args=() jvm_tail=()
  name="$(basename "$prog" .dawn)"
  expect="$here/$name.expect"
  # One argument per line. The marker exists only when argv is part of the
  # corpus contract; without it the historical no-argument invocation remains
  # byte for byte the same. `--` belongs to dawn's driver namespace and is not
  # forwarded, while the native binary receives the same array directly.
  if [ -f "$here/$name.args" ]; then
    while IFS= read -r arg || [ -n "$arg" ]; do prog_args+=("$arg"); done \
      < "$here/$name.args"
    jvm_tail=(-- "${prog_args[@]}")
  fi
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
  "$root/bin/dawn" run --std "$stdcopy" "$prog" "${jvm_tail[@]}" \
    >"$work/$name.jvm" 2>"$work/$name.jvm.err" \
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

  # A program whose subject is the `use java` boundary has no native half to
  # differ from: `emitc` refuses `use java` by design ("cannot be compiled to
  # native; use `use c`"), which is a decision rather than a defect. Such a
  # program declares itself with a `<name>.jvm-only` marker and its C-side
  # checks report `blocked`, the same word every other "no evidence either way"
  # gets here. Without the marker the refusal would have to live in
  # known-red.txt, which is the list of things that are *meant* to be fixed.
  #
  # The marker is a ratchet the way known-red.txt is, and for the same reason:
  # an exemption nobody checks is a hiding place. So the refusal is *verified*
  # rather than assumed. A marker on a program the native backend would happily
  # compile silences six real checks, and this is what stops that from being
  # green -- the emitter has to actually say no.
  if [ -f "$here/$name.jvm-only" ]; then
    if "$root/bin/dawn" __emitc --std "$stdcopy" "$prog" -o "$work/$name.c" \
      >"$work/$name.emitc" 2>&1; then
      verdict "$name:jvm-only" bad \
        "$name.jvm-only says the native backend refuses this program, and it did not"
    fi
    for c in emitc cc native diff stderr exit asan; do blocked "$name:$c"; done
    return 0
  fi

  if "$root/bin/dawn" __emitc --std "$stdcopy" "$prog" -o "$work/$name.c" \
    >"$work/$name.emitc" 2>&1; then
    verdict "$name:emitc" ok
  else
    verdict "$name:emitc" bad "$(cat "$work/$name.emitc")"
    for c in cc native diff stderr exit; do blocked "$name:$c"; done
    return 0
  fi

  # -fwrapv: Dawn's Int wraps like the JVM's long, and signed overflow is
  # otherwise UB. -fno-strict-aliasing: same reason the real backend needs
  # it. -fexceptions: a raise unwinds (#193 ARC-05), and this is what makes
  # the cleanup landing pads real; without it recovery silently leaks again.
  # All three are correctness flags, not tuning.
  #
  # -Werror is a real gate: a Core type that reaches C wrong shows up first
  # as an int-from-pointer warning, long before it shows up as a wrong
  # answer. That is how the pattern-binding types were caught. The three
  # -Wno- flags cover noise a code generator legitimately produces.
  if "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
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
    return 0
  fi

  nat_rc=0
  "$work/$name.bin" "${prog_args[@]}" >"$work/$name.native" 2>"$work/$name.native.err" \
    </dev/null || nat_rc=$?

  # -O0 so the report names the Dawn function rather than whatever it was
  # inlined into; the answer is not being checked here, only the memory.
  if [ "$asan_ok" -eq 1 ]; then
    if "$cc_bin" -std=c11 -g -O0 -fno-omit-frame-pointer -fwrapv -fexceptions \
      -fno-strict-aliasing -fsanitize=address -pthread \
      -I "$root/runtime/c" \
      -o "$work/$name.asan" "$work/$name.c" "$root/runtime/c/dawn_rt.c" -lm \
      >"$work/$name.asan.cc" 2>&1; then
      asan_rc=0
      ASAN_OPTIONS=detect_leaks=1 "$work/$name.asan" "${prog_args[@]}" \
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
    return 0
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
  return 0
}

# ---------------------------------------------------------------- worker mode
#
# `SPIKE_WORKER=1 run.sh <entry>`: one corpus entry, in its own process, for
# the xargs pool below. Not a user-facing mode -- the setup a corpus run needs
# (the std copy, the AddressSanitizer probe, the toolchain warm) has already
# happened in the driver and arrives in the environment, so invoking this by
# hand does not work and is not meant to.
#
# Everything it has to say goes to $work/logs/<name>.log, and the two numbers
# the driver has to add up go to <name>.rc and <name>.known. .rc is written
# last, and only by a worker that got to the end; its *absence* is a failure to
# the driver, which is what makes a worker killed outright -- the OOM killer, a
# signal, `set -e` on a bug in this harness -- fail the run rather than vanish
# from the tally.
if [ "${SPIKE_WORKER:-}" = 1 ]; then
  work="$SPIKE_WORK"
  stdcopy="$work/std"
  asan_ok="$SPIKE_ASAN"
  wname="$(basename "$1" .dawn)"
  exec >"$work/logs/$wname.log" 2>&1
  run_corpus "$1"
  printf '%s\n' "$known_hit" >"$work/logs/$wname.known"
  printf '%s\n' "$fail" >"$work/logs/$wname.rc"
  exit "$fail"
fi

# -------------------------------------------------------------- driver
# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
if [ "${#shard_rest[@]}" -gt 0 ]; then set -- "${shard_rest[@]}"; else set --; fi

# The corpus on disk, in run order. A corpus entry is a single file, or a
# project directory when it needs a dependency -- `dawn run` and `__emitc`
# both take either, and a project is the only way to drive a real package
# (see json_lib).
corpus=("$here"/*.dawn)
# written as an `if` rather than `[ -f ] && corpus+=`: under `set -e` a
# failing test as the body's last command takes the script with it
for d in "$here"/*/; do
  if [ -f "$d/dawn.toml" ]; then corpus+=("${d%/}"); fi
done
corpus_names=()
for prog in "${corpus[@]}"; do corpus_names+=("$(basename "$prog" .dawn)"); done

# matrix.txt is the persistent record scripts/mutant-coverage/check.py reads,
# and it can only mean anything if it is the same list this script iterates.
# Held equal in both directions, and before any work: a .dawn file added
# without a line here would be out of the shard rotation and nothing would
# print differently, while a line here with no file behind it would make the
# coverage union unsatisfiable in every future run. Both are startup failures
# instead. This runs on a targeted invocation too -- the disagreement is about
# the tree, not about which entries this particular run picked.
matrix_recorded="$(grep -v '^[[:space:]]*#' "$here/matrix.txt" | grep -v '^[[:space:]]*$' || true)"
matrix_executable="$(printf '%s\n' "${corpus_names[@]}")"
if [ "$matrix_recorded" != "$matrix_executable" ]; then
  diff -u --label matrix.txt <(printf '%s\n' "$matrix_recorded") \
    --label "corpus on disk" <(printf '%s\n' "$matrix_executable") >&2 || true
  echo "matrix.txt and the corpus on disk disagree" >&2
  exit 1
fi

full_corpus=0
if [ "$#" -gt 0 ]; then
  # A targeted run is not a slice of the matrix and must not be filed as one:
  # its coverage record would claim a shard's worth of work from an arbitrary
  # list. Same reason tile-golden's --only clears it.
  if [ "$shard_total" != 1 ]; then
    echo "FAIL  --shard runs the whole corpus in slices; it cannot be combined with an entry list" >&2
    exit 2
  fi
  MUTANT_COVERAGE_DIR=
  progs=("$@")
else
  full_corpus=1
  progs=()
  position=0
  for prog in "${corpus[@]}"; do
    if ! shard_skips "$position"; then progs+=("$prog"); fi
    position=$((position + 1))
  done
fi

shard_begin spike-native
for prog in "${progs[@]}"; do
  if [ "$full_corpus" -eq 1 ]; then shard_record "$(basename "$prog" .dawn)"; fi
done

work="$(mktemp -d)"
mkdir -p "$work/logs"

# Whether this machine's cc can build with AddressSanitizer. Probed once,
# because a full run would otherwise ask once per corpus entry, and reported as
# `blocked` rather than as a failure: a missing sanitizer is no evidence either
# way.
asan_ok=1
printf 'int main(void){return 0;}\n' >"$work/asan_probe.c"
if ! "$cc_bin" -fsanitize=address -o "$work/asan_probe" "$work/asan_probe.c" \
  >/dev/null 2>&1; then
  asan_ok=0
  echo "note: $cc_bin cannot build with -fsanitize=address; asan checks skipped"
fi
trap 'rm -rf "$work"' EXIT

# warm the toolchain before any output is captured: bin/dawn announces a
# rebuild on stderr, and stderr is compared now. It is also what keeps the
# pool below from racing: `bin/dawn` rebuilds when the source stamp moved, and
# N workers starting on a cold build/ would all rebuild into the same jar.
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

# How wide to run. A ceiling, written down, rather than however many cores the
# host happens to have: each worker forks a JVM that bin/dawn gives a 2 GiB
# heap ceiling, and peak RSS tracks that ceiling rather than the workload (see
# bin/dawn's note), so the memory bill is jobs x ~1.2 GiB and nothing else
# caps it. Four is the public runner's width and about 5 GiB here; a 16-core
# laptop asking for 16 would be asking for ~19 GiB. SPIKE_JOBS overrides, and
# SPIKE_JOBS=1 is the serial harness this used to be -- useful when a failure
# has to be read without other workers' output around it.
jobs="${SPIKE_JOBS:-}"
if [ -z "$jobs" ]; then
  jobs="$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1) )"
  # an `if`, not `[ ... ] && jobs=4`: as the last command of this block a
  # false test would be the block's status, and `set -e` would take the script
  if [ "$jobs" -gt 4 ]; then jobs=4; fi
fi
if [ "$shard_total" -gt 1 ]; then
  echo "corpus: ${#progs[@]} entries, $jobs at a time (shard $shard_index/$shard_total of ${#corpus[@]})"
else
  echo "corpus: ${#progs[@]} entries, $jobs at a time"
fi

# Order is restored below, so this only has to finish; it does not have to
# finish in sequence. xargs' own status is a second net under the per-entry
# .rc files -- 123 when a worker exited 1-125, 125 when one was killed by a
# signal -- and neither replaces the other: xargs cannot say *which* entry,
# and the .rc scan cannot see a worker that never started.
export SPIKE_WORKER=1 SPIKE_WORK="$work" SPIKE_ASAN="$asan_ok"
xargs_rc=0
printf '%s\0' "${progs[@]}" |
  xargs -0 -n1 -P "$jobs" "$self" || xargs_rc=$?
unset SPIKE_WORKER SPIKE_WORK SPIKE_ASAN

# Replay in corpus order: the transcript a reader compares against the last one
# must not depend on which worker finished first.
for prog in "${progs[@]}"; do
  name="$(basename "$prog" .dawn)"
  if [ -f "$work/logs/$name.log" ]; then cat "$work/logs/$name.log"; fi
  if [ -f "$work/logs/$name.rc" ] && [ -f "$work/logs/$name.known" ]; then
    [ "$(cat "$work/logs/$name.rc")" = 0 ] || fail=1
    known_hit=$((known_hit + $(cat "$work/logs/$name.known")))
  else
    printf '  %-28s FAIL -- worker did not finish (killed?)\n' "$name"
    fail=1
  fi
done

if [ "$xargs_rc" -ne 0 ] && [ "$fail" -eq 0 ]; then
  echo "xargs exited $xargs_rc but every entry reported success -- treating as a failure"
  fail=1
fi

if [ "$full_corpus" -eq 1 ]; then shard_report "${#corpus[@]}"; fi

# The corpus holds the written positive delete outcomes in io_files. A full CI
# run also rebuilds both historical runtime regressions and requires their
# behavior to go red; targeted corpus runs stay targeted rather than paying for
# another selfhost build.
#
# Sharded, it belongs to shard 1 and to no other: it is one selfhost rebuild
# and it is not divisible, so running it in each shard would pay for it N
# times, and running it nowhere would drop a gate. It stays inside this script
# rather than becoming a step of shard 1's job so that `run.sh --shard 1/4` is
# the same thing CI runs. The `fail` clause now reads shard 1's own slice
# rather than the whole corpus, which is the one behavioural difference
# sharding makes here: the contract is independent of the corpus, so what it
# was ever waiting for was a run worth reading the output of.
if [ "$full_corpus" -eq 1 ] && [ "$shard_index" -eq 1 ] && [ "$fail" -eq 0 ]; then
  echo
  if ! "$root/scripts/delete-contract/run.sh"; then fail=1; fi
fi

echo
if [ "$fail" -ne 0 ]; then
  echo "differential FAILED"
elif [ "$known_hit" -gt 0 ]; then
  echo "no new failures ($known_hit known-red, see known-red.txt)"
else
  echo "differential ok"
fi

exit "$fail"
