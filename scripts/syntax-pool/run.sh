#!/usr/bin/env bash
# Three pieces retain every public fixture; all four run complete private oracles.
# The required union checks actual successful completions against all matrices.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"
# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
# shellcheck source=scripts/syntax-pool/pool.sh
source "$root/scripts/syntax-pool/pool.sh"
shard_parse "$@"
if [ "$shard_total" != 4 ] || [ -n "$shard_plan" ] || [ "${#shard_rest[@]}" -ne 2 ] ||
    [ "${shard_rest[0]:-}" != --plan-id ] || [[ ! "${shard_rest[1]:-}" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'usage: syntax-pool/run.sh --shard I/4 --plan-id SHA256' >&2
  exit 2
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/syntax-pool.XXXXXX")
cleanup() {
  local status=$?
  syntax_pool_cleanup "$status" || status=$?
  if [ "$status" -ne 0 ]; then
    echo "syntax failure artifacts: $work" >&2
  else
    rm -rf "$work"
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'syntax_pool_signal 129' HUP
trap 'syntax_pool_signal 130' INT
trap 'syntax_pool_signal 143' TERM
syntax_pool_prepare "$work" "${shard_rest[1]}"
if [ "$shard_index" -le 3 ]; then
printf 'BEGIN syntax public syntax-small-contract\n'
"$root/scripts/syntax-small-contract/run.sh" --fixtures-only
printf '%s\n' syntax-small-contract >> "$syntax_pool_dir/public"
printf 'END syntax public syntax-small-contract\n'
printf 'BEGIN syntax public pattern-or-contract\n'
"$root/scripts/pattern-or-contract/run.sh" --fixtures-only
printf '%s\n' pattern-or-contract >> "$syntax_pool_dir/public"
printf 'END syntax public pattern-or-contract\n'
printf 'BEGIN syntax public for-pattern-contract\n'
"$root/scripts/for-pattern-contract/run.sh" --fixtures-only
printf '%s\n' for-pattern-contract >> "$syntax_pool_dir/public"
printf 'END syntax public for-pattern-contract\n'
fi
syntax_pool_case() {
  case "$1" in
    syntax-small-contract) "$root/scripts/syntax-small-contract/run.sh" --case-only "$2" ;;
    pattern-or-contract) "$root/scripts/pattern-or-contract/run.sh" --case-only "$2" ;;
    for-pattern-contract) "$root/scripts/for-pattern-contract/run.sh" --case-only "$2" ;;
    *) echo 'FAIL: unknown complete syntax oracle' >&2; return 2 ;;
  esac
}
mkdir "$work/cases"
export TMPDIR="$work/cases"
syntax_pool_run syntax_pool_case
echo 'PASS  complete syntax piece'
