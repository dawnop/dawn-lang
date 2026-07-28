#!/usr/bin/env bash
# Ties both backends' case folding to one oracle.
#
#   ./scripts/case-contract/run.sh
#
# `str.lower`/`str.upper` are simple (1:1) Unicode case mapping. The JVM backend
# gets that from Character.toUpperCase/toLowerCase; the C runtime has no Unicode
# tables, so it carries runtime/c/dawn_case_table.h. Two implementations of one
# mapping only stays true if something checks, and the probe checks both against
# the oracle:
#
#   * the compiled `str.upper`/`str.lower` over every code point that has a
#     mapping, plus a spread of ones that do not;
#   * the committed header, parsed and walked code point by code point -- what
#     the C runtime actually compiles, rather than what a regeneration happens
#     to print. A JDK whose Unicode version has moved on fails here, naming the
#     code points, rather than silently in a native binary.
#
# To regenerate the header after such a move:
#
#   DAWN_CASE_EMIT=1 bin/dawn run scripts/case-contract/probe.dawn \
#     > runtime/c/dawn_case_table.h
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
probe="$root/scripts/case-contract/probe.dawn"

out="$(DAWN_CASE_HEADER="$root/runtime/c/dawn_case_table.h" "$root/bin/dawn" run "$probe")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: case folding disagrees with Character.toUpperCase/toLowerCase" >&2
  exit 1
fi

printf '%s\n' "$out" | sed -n 's/^/PASS  /p' | tail -n 4
