#!/usr/bin/env bash
# Differential test for std/pvec against the builtin List.
#
#   ./scripts/pvec-contract/run.sh
#
# The builtin persistent list is the oracle: std/pvec is going to take its
# place, so the contract is "same answers on the same operation sequence".
# See pveccheck.dawn for the shapes, which are chosen around the 32-way
# blocking rather than at random.
#
# The comparisons cannot live in a user module: `use std/pvec` is a compile
# error outside std (audit RD-06), because the trie is List's representation
# rather than a container of its own. So the harness builds a copy of std/ with
# pveccheck.dawn dropped in and runs probe.dawn -- an ordinary user module --
# against it. Same arrangement as scripts/array-contract, which reaches the
# `array_*` primitives this way.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/pvec-contract"

# warm the toolchain first: bin/dawn announces a rebuild on stderr
"$root/bin/dawn" --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$root"/std/*.dawn "$root/std/modules.txt" "$work/"
cp "$here/pveccheck.dawn" "$work/"
echo pveccheck >> "$work/modules.txt"

out="$("$root/bin/dawn" run --std "$work" "$here/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: std/pvec disagrees with the builtin List" >&2
  exit 1
fi

echo "PASS  std/pvec agrees with the builtin List"
