#!/usr/bin/env bash
#
# Run the whole incremental-semantics contract family locally, in parallel.
#
# Local tooling. gates.yml does not know this script exists and nothing in CI
# runs it; it exists because every change under selfhost/src/check/ has to be
# put in front of the whole family before it merges. The harnesses pin their
# mutants to literal source strings, those anchors drift when the subject moves,
# and a drifted anchor is invisible until the harness that owns it runs (main
# went red at ca33cdbe for exactly that). Hand-extracting the invocations out of
# gates.yml and running them one after another costs about 62 minutes.
#
# The invocation list is derived from .github/workflows/gates.yml at run time by
# sweep-plan.py, so a harness added to an existing incremental job is swept
# without editing anything here. --self-test cross-checks that parse against a
# plain grep of the same file, so the sweep cannot quietly run a subset.
#
# Harnesses start longest first, because the sweep is tail-bound rather than
# throughput-bound: the longest harness, if it starts in the last wave, is the
# wall clock by itself. Durations come from the previous run's log, and from a
# static table of the longest until there is one. Ordering is the only thing
# they affect.
#
# Measured 2026-09-13 on a 16 core / 15.6 GiB machine (WSL2, GraalVM 21), with
# the toolchain already built, 43 invocations after dedup, all passing:
#
#   jobs   order           wall clock   peak in use   headroom at that peak
#      5   gates.yml      1530s 25m30s     7.7 GiB           7.9 GiB
#      8   gates.yml      1483s 24m42s     9.4 GiB           6.2 GiB
#     12   gates.yml      1424s 23m44s    12.1 GiB           3.5 GiB
#      8   longest first  1413s 23m33s     9.8 GiB           5.8 GiB
#
# Baseline before each run was 3.7 to 4.0 GiB already in use, so the sweep's own
# share of those peaks is about 3.7, 5.4, 8.4 and 6.1 GiB.
#
# The default is 8, which is nproc/2. Wall clock is nearly flat in the job count
# from 5 upwards because a harness is not one process: it forks `dawn build` per
# mutant, and one harness alone measured 278% CPU, so 16 cores are already
# saturated at around 5 harnesses and the rest of the fan-out buys queueing
# rather than throughput. What does keep growing is memory, which is the real
# bound here: 12-way in gates.yml order paid 2.7 GiB for 58 seconds and left
# 3.5 GiB on a machine that is also being used for something else. Ordering
# bought 70 seconds at 8-way for nothing, which is more than the 12-way fan-out
# bought, and still leaves 5.8 GiB. Against roughly 62 minutes of serial
# hand-running that is a 2.6x speed-up, and the floor under it was one
# harness: prefix.py ran 771s in that sweep, half again the next longest. On
# 2026-09-13 it was given `--shards 3 --shard I` and gates.yml deals its three
# shards to three jobs, so the sweep now runs them as three harnesses and the
# floor is the longest of those, about 312s: the shard that keeps the positive
# subject. The table above is from before that split and was not remeasured.
#
# Usage:
#   sweep.sh [--jobs N] [--log PATH] [--only NAME[,NAME...]]
#   sweep.sh --list
#   sweep.sh --self-test
set -euo pipefail

SELF=$(cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")
HERE=$(dirname -- "$SELF")
ROOT=$(cd -- "$HERE/../.." && pwd)
PLAN_TOOL="$HERE/sweep-plan.py"
GATES="$ROOT/.github/workflows/gates.yml"

# Spelled by sweep-plan.py, which also reads it as the fallback hint source, so
# the two cannot drift into writing and reading different files.
DEFAULT_LOG=$(python3 "$HERE/sweep-plan.py" --default-log)

# The header above, to the first line that is not a comment. Derived rather
# than a line range, because a line range goes stale the first time the
# measurements below are re-taken.
usage() {
  awk 'NR > 1 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "$SELF"
}

# nproc/2 rather than nproc: see the header. Halved again if the machine is
# small, because each job wants roughly a gigabyte while its mutants build.
default_jobs() {
  local cores
  cores=$(nproc 2>/dev/null || echo 4)
  echo $(((cores + 1) / 2))
}

# Where the durations that order the plan are read from. The log a sweep is
# about to write is snapshotted here before it is truncated, so a run always
# orders itself by the previous run's timings even when --log moved; with no
# snapshot, sweep-plan.py falls back to the default log path and then to its
# static table.
hint_file() {
  printf '%s/hints.prev\n' "$(dirname -- "$1")"
}

plan_line() {
  # The plan for one name, as `name<TAB>command`.
  python3 "$PLAN_TOOL" --hints "$2" |
    awk -v want="$1" -F '\t' '$1 == want { print; found = 1 }
    END { if (!found) exit 1 }'
}

# ---------------------------------------------------------------- one harness

run_one() {
  local name=$1 log=$2 dir command out runner_temp started status elapsed
  dir=$(dirname -- "$log")
  command=$(plan_line "$name" "$(hint_file "$log")" | cut -f2-)
  out="$dir/out-$name.txt"
  runner_temp="$dir/runner-temp/$name"
  rm -rf -- "$runner_temp"
  mkdir -p -- "$runner_temp"

  started=$(date +%s.%N)
  status=PASS
  # RUNNER_TEMP and JAVA_HOME are the two variables gates.yml spells in these
  # commands; exporting them here is the substitution. Each harness gets its own
  # RUNNER_TEMP so the two body-probe trees cannot land on each other.
  if ! (cd "$ROOT" && RUNNER_TEMP="$runner_temp" bash -c "$command") >"$out" 2>&1; then
    status=FAIL
  fi
  elapsed=$(awk -v a="$started" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }')

  local line
  line=$(printf '%-4s  %-34s %8ss' "$status" "$name" "$elapsed")
  # One short append per harness. Line-buffered appends under this size are
  # atomic on Linux, and flock removes even that assumption where it exists.
  if command -v flock >/dev/null 2>&1; then
    flock "$log" bash -c "printf '%s\n' \"\$1\" >> \"\$2\"" _ "$line" "$log"
  else
    printf '%s\n' "$line" >>"$log"
  fi
  printf '%s\n' "$line"
  [ "$status" = PASS ]
}

# ------------------------------------------------------------------ self-test

self_test() {
  local failures=0 parsed_jobs grep_jobs parsed_count grep_count plan_count

  # The Python side checks itself against its own regexes. This half is the
  # independent one: plain grep over the same file, no YAML parser involved.
  parsed_jobs=$(python3 "$PLAN_TOOL" --jobs | sort)
  grep_jobs=$(grep -oE '^  incremental[-a-z0-9]*:$' "$GATES" | tr -d ' :' | sort)
  if [ "$parsed_jobs" != "$grep_jobs" ]; then
    printf 'FAIL sweep self-test: jobs differ\n  parser: %s\n  grep:   %s\n' \
      "$(echo "$parsed_jobs" | tr '\n' ' ')" "$(echo "$grep_jobs" | tr '\n' ' ')" >&2
    failures=$((failures + 1))
  fi

  parsed_count=$(python3 "$PLAN_TOOL" --raw-count)
  grep_count=$(grep -cE \
    '^ +(run: )?(python3 scripts/incremental-semantics-contract/|\./bin/dawn test scripts/incremental-semantics-contract)' \
    "$GATES")
  if [ "$parsed_count" != "$grep_count" ]; then
    printf 'FAIL sweep self-test: parser found %s invocations, grep found %s\n' \
      "$parsed_count" "$grep_count" >&2
    failures=$((failures + 1))
  fi

  plan_count=$(python3 "$PLAN_TOOL" | wc -l | tr -d ' ')
  if [ "$plan_count" -gt "$parsed_count" ]; then
    printf 'FAIL sweep self-test: dedup grew the plan, %s from %s\n' \
      "$plan_count" "$parsed_count" >&2
    failures=$((failures + 1))
  fi

  python3 "$PLAN_TOOL" --self-test || failures=$((failures + 1))

  if [ "$failures" -ne 0 ]; then
    return 1
  fi
  printf 'OK: sweep self-test, %s jobs, %s invocations, %s after dedup\n' \
    "$(echo "$grep_jobs" | wc -l | tr -d ' ')" "$grep_count" "$plan_count"
}

# ------------------------------------------------------------ memory sampling

sample_memory() {
  local out=$1 peak=0 used
  while :; do
    used=$(awk '/^MemTotal:/ { total = $2 } /^MemAvailable:/ { free = $2 }
      END { print total - free }' /proc/meminfo)
    if [ "$used" -gt "$peak" ]; then
      peak=$used
      printf '%s\n' "$peak" >"$out"
    fi
    sleep 2
  done
}

# ----------------------------------------------------------------------- main

JOBS=$(default_jobs)
LOG=$DEFAULT_LOG
ONLY=
MODE=sweep
RUN_ONE_NAME=

while [ $# -gt 0 ]; do
  case $1 in
    -j | --jobs)
      JOBS=$2
      shift 2
      ;;
    --log)
      LOG=$2
      shift 2
      ;;
    --only)
      ONLY=$2
      shift 2
      ;;
    --list)
      MODE=list
      shift
      ;;
    --self-test)
      MODE=self-test
      shift
      ;;
    --run-one) # internal: one harness, invoked by xargs below
      MODE=run-one
      RUN_ONE_NAME=$2
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'sweep.sh: unknown argument %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

case $MODE in
  self-test)
    self_test
    exit $?
    ;;
  list)
    python3 "$PLAN_TOOL" --hints "$(hint_file "$LOG")" --show-hints |
      awk -F '\t' 'NF == 1 { print; next } { printf "%8.1fs  %-34s %s\n", $1, $2, $3 }'
    exit 0
    ;;
  run-one)
    run_one "$RUN_ONE_NAME" "$LOG"
    exit $?
    ;;
esac

case $JOBS in
  '' | *[!0-9]*)
    printf 'sweep.sh: --jobs wants a positive integer, got %s\n' "$JOBS" >&2
    exit 2
    ;;
esac
[ "$JOBS" -ge 1 ] || {
  printf 'sweep.sh: --jobs wants a positive integer, got %s\n' "$JOBS" >&2
  exit 2
}

LOG_DIR=$(dirname -- "$LOG")
mkdir -p -- "$LOG_DIR"

# The previous run's timings, before this run truncates the log they are in.
# Only a complete run is promoted to hints: a log from --only names a handful of
# harnesses, and sweep-plan.py reads a log as a census of everything that ran,
# so keeping one would tell the next full sweep that forty of its harnesses are
# brand new.
HINTS=$(hint_file "$LOG")
if [ -z "$ONLY" ] && [ -s "$LOG" ]; then
  cp -- "$LOG" "$HINTS"
fi

# Longest first. The sweep is tail-bound, so a slow harness that starts in the
# last wave is the whole wall clock; see the header.
mapfile -t ALL_NAMES < <(python3 "$PLAN_TOOL" --hints "$HINTS" | cut -f1)
if [ "${#ALL_NAMES[@]}" -eq 0 ]; then
  printf 'sweep.sh: the plan is empty\n' >&2
  exit 1
fi

NAMES=()
if [ -n "$ONLY" ]; then
  IFS=, read -r -a WANTED <<<"$ONLY"
  for want in "${WANTED[@]}"; do
    found=
    for name in "${ALL_NAMES[@]}"; do
      if [ "$name" = "$want" ]; then
        found=yes
        NAMES+=("$name")
      fi
    done
    if [ -z "$found" ]; then
      printf 'sweep.sh: no such harness %s (see --list)\n' "$want" >&2
      exit 2
    fi
  done
else
  NAMES=("${ALL_NAMES[@]}")
fi

: >"$LOG"
rm -f -- "$LOG_DIR"/out-*.txt

printf 'sweep: %s harnesses, %s at a time, log %s\n' "${#NAMES[@]}" "$JOBS" "$LOG"
printf 'sweep: longest first, %s\n' \
  "$(python3 "$PLAN_TOOL" --hints "$HINTS" --show-hints | sed -n '1s/^# hints from //p')"

# Warm the toolchain before fanning out. bin/dawn rebuilds build/dawn-selfhost.jar
# in the checkout whenever its input hash moved, and that output is shared: N
# harnesses starting cold would race to write the same jar.
printf 'sweep: warming the toolchain\n'
(cd "$ROOT" && ./bin/dawn --version)

PEAK_FILE="$LOG_DIR/peak-kb"
BASELINE_KB=$(awk '/^MemTotal:/ { total = $2 } /^MemAvailable:/ { free = $2 }
  END { print total - free }' /proc/meminfo)
printf '%s\n' "$BASELINE_KB" >"$PEAK_FILE"
sample_memory "$PEAK_FILE" &
SAMPLER=$!
trap 'kill "$SAMPLER" 2>/dev/null || true' EXIT

STARTED=$(date +%s.%N)
set +e
printf '%s\0' "${NAMES[@]}" |
  xargs -0 -P "$JOBS" -I {} "$SELF" --run-one {} --log "$LOG"
set -e
WALL=$(awk -v a="$STARTED" -v b="$(date +%s.%N)" 'BEGIN { printf "%.1f", b - a }')

kill "$SAMPLER" 2>/dev/null || true
trap - EXIT
PEAK_KB=$(cat "$PEAK_FILE")

FAILED=$(awk '$1 == "FAIL" { print $2 }' "$LOG")
RAN=$(wc -l <"$LOG" | tr -d ' ')

printf '\n---- sweep summary ----\n'
sort -k3 -n -r "$LOG"
printf '\nharnesses: %s of %s reported\n' "$RAN" "${#NAMES[@]}"
printf 'wall clock: %ss (%s)\n' "$WALL" \
  "$(awk -v s="$WALL" 'BEGIN { printf "%dm %02ds", s / 60, s % 60 }')"
printf 'peak memory in use: %.1f GiB (%.1f GiB before the sweep)\n' \
  "$(awk -v k="$PEAK_KB" 'BEGIN { print k / 1048576 }')" \
  "$(awk -v k="$BASELINE_KB" 'BEGIN { print k / 1048576 }')"

if [ -z "$FAILED" ] && [ "$RAN" -eq "${#NAMES[@]}" ]; then
  printf 'all %s harnesses passed\n' "${#NAMES[@]}"
  exit 0
fi

if [ "$RAN" -ne "${#NAMES[@]}" ]; then
  printf 'WARNING: %s harnesses did not report; the sweep was cut short\n' \
    $((${#NAMES[@]} - RAN)) >&2
fi

for name in $FAILED; do
  printf '\n==== FAIL %s ====\n' "$name"
  python3 "$PLAN_TOOL" --anchor-report "$name" "$LOG_DIR/out-$name.txt" || true
  printf '  last 5 lines of out-%s.txt:\n' "$name"
  tail -n 5 -- "$LOG_DIR/out-$name.txt" | sed 's/^/    /'
done
exit 1
