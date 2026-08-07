#!/usr/bin/env bash
# Differential test for packages/inflate against java.util.zip.
#
#   ./scripts/inflate-contract/run.sh
#
# Java compresses, Dawn decompresses. That direction is the point: a round
# trip through one implementation proves only that it agrees with itself, and
# what has to hold is that this reads archives someone else wrote.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/inflate-contract"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src"
cp "$here/probe.dawn" "$work/src/main.dawn"
cat > "$work/dawn.toml" <<TOML
schema = 1
name = "inflate_contract"

[deps]
inflate = "$root/packages/inflate"
TOML

# a real source file: hundreds of KB of text, which is what makes the level
# 6/9 cases dynamic-Huffman rather than a toy
out="$("$root/bin/dawn" run "$work" "$root/selfhost/src/check/types.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: packages/inflate disagrees with java.util.zip" >&2
  exit 1
fi

echo "PASS  packages/inflate reads what java.util.zip writes"
