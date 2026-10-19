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
# Round robin assumes the items cost about the same, or at least that the
# dear ones are spread through the matrix. Where that stops being good enough
# a harness can be dealt by measured cost instead: `--plan <file>` names, for
# each item, the shard that runs it (scripts/mutant-coverage/deal.py writes
# such a file from per-item timings by longest-first greedy packing). The plan
# only moves items between shards; the coverage record and check.py's union
# are the same either way, so a plan that dropped an item would be refused
# there exactly as a wrong `--shard` is. An item the matrix has and the plan
# does not (a kernel added since the deal) falls back to its round-robin
# shard, and the run says how many did, so a stale plan costs balance and
# never coverage. A plan for another harness or another shard count, a shard
# index out of range, a name the matrix does not carry, or a name dealt twice
# is refused before anything runs.
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
shard_plan=""
shard_plan_names=()
declare -gA shard_plan_of=()

# Consume `--shard I/N` (and `--plan <file>`) from the caller's arguments; anything else is left in
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
      --plan)
        shift
        [[ $# -gt 0 ]] || { printf 'FAIL  --plan needs a file\n' >&2; exit 2; }
        shard_plan="$1"
        shift
        continue
        ;;
      --plan=*)
        shard_plan="${1#--plan=}"
        shift
        continue
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
  [[ -z "$shard_plan" ]] || shard_load_plan
  [[ -n "${MUTANT_COVERAGE_DIR:-}" ]] || return 0
  mkdir -p "$MUTANT_COVERAGE_DIR"
  shard_coverage_file="$MUTANT_COVERAGE_DIR/$shard_harness-$shard_index-of-$shard_total.coverage"
  {
    printf 'harness=%s\n' "$shard_harness"
    printf 'shard=%s/%s\n' "$shard_index" "$shard_total"
  } > "$shard_coverage_file"
}

# Read `--plan` for the harness shard_begin named. The matrix is read here,
# from scripts/<harness>/matrix.txt beside this file, because the runners call
# shard_skips with a position and the plan is keyed by name. Plan lines are
# `harness=<name>`, `shards=<N>` and `<item> <shard> [<seconds>]`; the seconds
# are deal.py's input and are not read here.
shard_plan_fail() {
  printf 'FAIL  --plan %s: %s\n' "$shard_plan" "$1" >&2
  exit 2
}
shard_load_plan() {
  local matrix name index rest plan_harness="" plan_shards="" fallback=0 i
  matrix="$(dirname "${BASH_SOURCE[0]}")/../$shard_harness/matrix.txt"
  [[ -f "$shard_plan" ]] || shard_plan_fail "no such file"
  [[ -f "$matrix" ]] || shard_plan_fail "harness $shard_harness has no matrix.txt"
  mapfile -t shard_plan_names < <(grep -v '^#' "$matrix" | grep -v '^[[:space:]]*$')
  declare -A in_matrix=()
  for name in "${shard_plan_names[@]}"; do in_matrix[$name]=1; done
  shard_plan_of=()
  while read -r name index rest; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    case "$name" in
      harness=*) plan_harness="${name#harness=}"; continue ;;
      shards=*) plan_shards="${name#shards=}"; continue ;;
    esac
    [[ "$index" =~ ^[0-9]+$ ]] || shard_plan_fail "$name has no shard index"
    [[ -n "${in_matrix[$name]:-}" ]] || shard_plan_fail "$name is not in $shard_harness's matrix"
    [[ -z "${shard_plan_of[$name]:-}" ]] || shard_plan_fail "$name is dealt twice"
    shard_plan_of[$name]="$index"
  done < "$shard_plan"
  [[ "$plan_harness" == "$shard_harness" ]] ||
    shard_plan_fail "it is a plan for harness '${plan_harness}', not $shard_harness"
  [[ "$plan_shards" == "$shard_total" ]] ||
    shard_plan_fail "it deals ${plan_shards:-no} shards, this run is one of $shard_total"
  for name in "${!shard_plan_of[@]}"; do
    index="${shard_plan_of[$name]}"
    (( index >= 1 && index <= shard_total )) ||
      shard_plan_fail "$name is dealt to shard $index of $shard_total"
  done
  for i in "${!shard_plan_names[@]}"; do
    [[ -n "${shard_plan_of[${shard_plan_names[$i]}]:-}" ]] || fallback=$(( fallback + 1 ))
  done
  if (( fallback > 0 )); then
    printf 'NOTE  %s: %s item(s) are not in %s and run on their round-robin shard; re-deal with scripts/mutant-coverage/deal.py\n' \
      "$shard_harness" "$fallback" "$shard_plan"
  fi
}

# True when this shard should skip the mutant at 0-based matrix position `$1`.
shard_skips() {
  (( shard_total > 1 )) || return 1
  if [[ -n "$shard_plan" ]]; then
    local name want
    (( ${#shard_plan_names[@]} > 0 )) ||
      shard_plan_fail "shard_skips ran before shard_begin read the plan"
    name="${shard_plan_names[$1]:-}"
    [[ -n "$name" ]] || shard_plan_fail "position $1 is past the end of the matrix"
    want="${shard_plan_of[$name]:-$(( $1 % shard_total + 1 ))}"
    (( want != shard_index ))
    return
  fi
  (( $1 % shard_total != shard_index - 1 ))
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
