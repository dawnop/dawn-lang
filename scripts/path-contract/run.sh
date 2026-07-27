#!/usr/bin/env bash
# Differential test for std/fspath against java.nio.file.Paths.
#
#   ./scripts/path-contract/run.sh
#
# The oracle is the thing being replaced: the compiler spelled this logic as
# `Paths.get(p).toAbsolutePath().normalize().toString()` in two places, and the
# switch to std/fspath is only safe if the two agree. See probe.dawn for the
# table.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$("$root/bin/dawn" run "$root/scripts/path-contract/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: std/fspath disagrees with java.nio.file.Paths" >&2
  exit 1
fi

echo "PASS  std/fspath agrees with java.nio.file.Paths"
