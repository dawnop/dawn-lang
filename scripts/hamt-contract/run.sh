#!/usr/bin/env bash
# Differential test for std/hamt against the builtin Map.
#
#   ./scripts/hamt-contract/run.sh
#
# The builtin persistent map is the oracle: std/hamt is going to take its
# place, so the contract is "same answers on the same operation sequence",
# insertion order included. See hamtcheck.dawn for what is compared.
#
# The comparisons cannot live in a user module: `use std/hamt` is a compile
# error outside std (audit RD-06), because the trie is Map and Set's
# representation rather than a container of its own. So the harness builds a
# copy of std/ with hamtcheck.dawn dropped in and runs probe.dawn -- an
# ordinary user module -- against it. Same arrangement as
# scripts/array-contract, which reaches the `array_*` primitives this way.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/hamt-contract"

# warm the toolchain first: bin/dawn announces a rebuild on stderr
"$root/bin/dawn" --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$root"/std/*.dawn "$root/std/modules.txt" "$work/"
cp "$here/hamtcheck.dawn" "$work/"
echo hamtcheck >> "$work/modules.txt"

out="$("$root/bin/dawn" run --std "$work" "$here/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: std/hamt disagrees with the builtin Map" >&2
  exit 1
fi

echo "PASS  std/hamt agrees with the builtin Map"
