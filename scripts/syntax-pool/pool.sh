# shellcheck shell=bash
# Four fixed lanes run complete private oracles; three pieces retain public probes.
# A lane writes completion only after a plain successful callback. The owner
# always joins every child before reporting or cleaning the shared directory.
syntax_pool_pids=()
syntax_pool_starting=0
syntax_pool_pending_status=0
syntax_pool_logs_printed=0
syntax_pool_dir=

syntax_pool_prepare() {
  syntax_pool_dir="$1/pool"
  printf 'BEGIN syntax control prepare\n'
  python3 "$root/scripts/syntax-pool/plan.py" prepare --root "$root" \
    --shard "$shard_index" --out "$syntax_pool_dir" --plan-id "$2" > "$1/selection"
  local harness name lane extra
  IFS=$'\t' read -r harness syntax_pool_input syntax_pool_producers syntax_pool_plan < "$1/selection"
  [ "$harness" = context ] || { echo 'FAIL: missing syntax input context' >&2; return 1; }
  while IFS=$'\t' read -r harness name lane extra; do
    [ "$harness" != context ] || continue
    printf '%s\t%s\n' "$harness" "$name" >> "$syntax_pool_dir/queue-$lane"
  done < "$1/selection"
  printf 'END syntax control prepare\n'
}

syntax_pool_signal() {
  if [ "$syntax_pool_starting" = 1 ]; then
    [ "$syntax_pool_pending_status" -ne 0 ] || syntax_pool_pending_status=$1
  else
    exit "$1"
  fi
}

syntax_pool_collect() {
  local status=0 child_status pid
  for pid in "${syntax_pool_pids[@]}"; do
    child_status=0
    wait "$pid" || child_status=$?
    [ "$status" -ne 0 ] || status=$child_status
  done
  syntax_pool_pids=()
  return "$status"
}

syntax_pool_print_logs() {
  [ "$syntax_pool_logs_printed" = 0 ] || return 0
  syntax_pool_logs_printed=1
  local lane
  if [ -n "$syntax_pool_dir" ]; then
    for lane in 0 1 2 3; do
      if [ -f "$syntax_pool_dir/log-$lane" ]; then cat "$syntax_pool_dir/log-$lane"; fi
    done
  fi
}

syntax_pool_cleanup() {
  local status=$1 child_status=0
  if [ "${#syntax_pool_pids[@]}" -gt 0 ]; then
    trap '' HUP INT TERM
    syntax_pool_collect || child_status=$?
    [ "$status" -ne 0 ] || status=$child_status
  fi
  syntax_pool_print_logs || { [ "$status" -ne 0 ] || status=1; }
  return "$status"
}

syntax_pool_run() {
  local callback=$1 lane status=0 names="$syntax_pool_dir/verified"
  printf 'BEGIN syntax worker phase at=%s\n' "$(date +%s.%N)"
  trap 'syntax_pool_signal 129' HUP
  trap 'syntax_pool_signal 130' INT
  trap 'syntax_pool_signal 143' TERM
  for lane in 0 1 2 3; do
    [ -s "$syntax_pool_dir/queue-$lane" ] || continue
    syntax_pool_starting=1
    (
      trap - EXIT HUP INT TERM
      while IFS=$'\t' read -r harness name; do
        printf 'BEGIN syntax case %s %s lane=%s at=%s\n' "$harness" "$name" "$lane" "$(date +%s.%N)"
        # A tested function call would disable errexit inside its callback.
        "$callback" "$harness" "$name" >> "$syntax_pool_dir/log-$lane" 2>&1
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$syntax_pool_input" "$syntax_pool_producers" \
          "$syntax_pool_plan" "$lane" "$harness" "$name" >> "$syntax_pool_dir/complete-$lane"
        printf 'END syntax case %s %s lane=%s status=0 at=%s\n' "$harness" "$name" "$lane" "$(date +%s.%N)"
      done < "$syntax_pool_dir/queue-$lane"
    ) &
    syntax_pool_pids+=("$!")
    syntax_pool_starting=0
    if [ "$syntax_pool_pending_status" -ne 0 ]; then exit "$syntax_pool_pending_status"; fi
  done
  syntax_pool_collect || status=$?
  syntax_pool_print_logs || { [ "$status" -ne 0 ] || status=1; }
  printf 'END syntax worker phase status=%s at=%s\n' "$status" "$(date +%s.%N)"
  [ "$status" -eq 0 ] || return "$status"
  local coverage=()
  if [ -n "${MUTANT_COVERAGE_DIR:-}" ]; then coverage=(--coverage "$MUTANT_COVERAGE_DIR"); fi
  printf 'BEGIN syntax control complete\n'
  python3 "$root/scripts/syntax-pool/plan.py" complete --root "$root" \
    --shard "$shard_index" --out "$syntax_pool_dir" "${coverage[@]}" > "$names"
  for harness in syntax-small-contract pattern-or-contract for-pattern-contract; do
    shard_begin "$harness"
    while IFS=$'\t' read -r kind name; do
      if [ "$kind" = "$harness" ]; then shard_record "$name"; fi
    done < "$names"
    printf 'PASS  %s: completed %s mutant(s) (piece %s/%s)\n' "$harness" "$shard_ran" "$shard_index" "$shard_total"
  done
  printf 'END syntax control complete\n'
}
