#!/usr/bin/env bash
# Differential test for std/hamt against the builtin Map.
#
#   ./scripts/hamt-contract/run.sh
#
# The builtin persistent map is the oracle: std/hamt is going to take its
# place, so the contract is "same answers on the same operation sequence",
# insertion order included. See probe.dawn for what is compared.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$("$root/bin/dawn" run "$root/scripts/hamt-contract/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: std/hamt disagrees with the builtin Map" >&2
  exit 1
fi

echo "PASS  std/hamt agrees with the builtin Map"
