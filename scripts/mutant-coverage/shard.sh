# shellcheck shell=bash
# Shared sharding and coverage bookkeeping for the mutation harnesses.
# Sourced, never executed. Callers must have set `set -euo pipefail`.
#
# Why sharding exists: a compiling mutant costs one whole compiler build, and
# the matrices outgrew the jobs that carried them. The syntax family (47
# mutants across three harnesses) was 926~1111s of the checker-corpus job on
# five consecutive main runs, which made that one step the whole run's wall
# clock. Splitting across jobs buys the factor back; export-surface-contract
# proved the shape here first.
#
# Selection is round-robin (`position % shard_total == shard_index - 1`, with
# 1-based shard indices, matching export-surface's `--shard 1/3` spelling),
# not contiguous blocks: mutants are not equal cost and the expensive ones
# cluster in matrix order, so blocks would leave one shard carrying the run.
#
# The coverage file is the part that matters. A shard that silently skipped
# half its mutants prints the same PASS lines and exits 0 exactly like one
# that did the work, so nothing downstream could tell them apart. Every run
# therefore writes down which mutants it actually executed, and
# scripts/mutant-coverage/check.py reassembles the shards in CI and holds
# their union against the harness's own matrix file. That comparison is
# against the source of truth, not against a count the shards report about
# themselves -- a shard cannot vouch for its own completeness.
#
# The output lands in $MUTANT_COVERAGE_DIR (one file per harness, shard index
# in the name) rather than a single $MUTANT_COVERAGE_OUT path, because one CI
# job here runs up to three harnesses in one process chain
# (syntax-small-contract forwards its shard to pattern-or and for-pattern)
# and they must not clobber each other's records.

shard_index=1
shard_total=1
shard_ran=0
shard_harness=""
shard_coverage_file=""

# Consume `--shard I/N` from the caller's arguments; anything else is left in
# the global `shard_rest` for the caller to handle.
#
# Deliberately not `mapfile -t rest < <(shard_parse "$@")`: process
# substitution puts the function in a subshell, where a bad `--shard` would
# print its complaint, `exit 2` only the subshell, and the run would carry on
# with a silently unsharded matrix. Setting a global in the caller's own
# shell is the only shape where the refusal actually refuses.
shard_rest=()
shard_parse() {
  local spec
  shard_rest=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --shard)
        shift
        [[ $# -gt 0 ]] || { printf 'FAIL  --shard needs I/N\n' >&2; exit 2; }
        spec="$1"
        shift
        ;;
      --shard=*)
        spec="${1#--shard=}"
        shift
        ;;
      *)
        shard_rest+=("$1")
        shift
        continue
        ;;
    esac
    if [[ ! "$spec" =~ ^[0-9]+/[0-9]+$ ]]; then
      printf 'FAIL  --shard wants I/N, got %s\n' "$spec" >&2
      exit 2
    fi
    shard_index="${spec%/*}"
    shard_total="${spec#*/}"
    if (( shard_total < 1 )); then
      printf 'FAIL  --shard total must be at least 1, got %s\n' "$shard_total" >&2
      exit 2
    fi
    if (( shard_index < 1 || shard_index > shard_total )); then
      printf 'FAIL  --shard index %s is out of range for %s shard(s)\n' \
        "$shard_index" "$shard_total" >&2
      exit 2
    fi
  done
}

# Start recording. `$1` is the harness directory name, which is how the
# aggregator pairs a coverage file with the matrix that owns it.
shard_begin() {
  shard_harness="$1"
  shard_ran=0
  shard_coverage_file=""
  [[ -n "${MUTANT_COVERAGE_DIR:-}" ]] || return 0
  mkdir -p "$MUTANT_COVERAGE_DIR"
  shard_coverage_file="$MUTANT_COVERAGE_DIR/$shard_harness-$shard_index-of-$shard_total.coverage"
  {
    printf 'harness=%s\n' "$shard_harness"
    printf 'shard=%s/%s\n' "$shard_index" "$shard_total"
  } > "$shard_coverage_file"
}

# True when this shard should skip the mutant at 0-based matrix position `$1`.
shard_skips() {
  (( shard_total > 1 )) && (( $1 % shard_total != shard_index - 1 ))
}

# Record a mutant this shard is about to run. Called after the skip check, so
# the file holds what was executed rather than what was considered.
shard_record() {
  shard_ran=$(( shard_ran + 1 ))
  [[ -n "$shard_coverage_file" ]] || return 0
  printf 'ran=%s\n' "$1" >> "$shard_coverage_file"
}

# Final line. `$1` is the matrix size, so a shard that ran nothing still says
# so out loud rather than exiting silently green.
shard_report() {
  printf 'PASS  %s: ran %s of %s mutant(s) (shard %s/%s)\n' \
    "$shard_harness" "$shard_ran" "$1" "$shard_index" "$shard_total"
}
