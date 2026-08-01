#!/usr/bin/env bash
# Differential test for the `fspath` package against java.nio.file.Paths.
#
#   ./scripts/path-contract/run.sh
#
# The oracle is the thing being replaced: the compiler spelled this logic as
# `Paths.get(p).toAbsolutePath().normalize().toString()` in two places, and the
# switch to fspath is only safe if the two agree. See src/main.dawn for the
# table.
#
# A project directory rather than a single file: fspath is a package (audit
# RD-09), and a `[deps]` entry needs a manifest.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$("$root/bin/dawn" run "$root/scripts/path-contract")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: fspath disagrees with java.nio.file.Paths" >&2
  exit 1
fi

echo "PASS  fspath agrees with java.nio.file.Paths"
