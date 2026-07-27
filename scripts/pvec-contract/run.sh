#!/usr/bin/env bash
# Differential test for std/pvec against the builtin List.
#
#   ./scripts/pvec-contract/run.sh
#
# The builtin persistent list is the oracle: std/pvec is going to take its
# place, so the contract is "same answers on the same operation sequence".
# See probe.dawn for the shapes, which are chosen around the 32-way blocking
# rather than at random.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$("$root/bin/dawn" run "$root/scripts/pvec-contract/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: std/pvec disagrees with the builtin List" >&2
  exit 1
fi

echo "PASS  std/pvec agrees with the builtin List"
