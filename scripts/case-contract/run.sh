#!/usr/bin/env bash
# Ties the two backends' case folding to one oracle.
#
#   ./scripts/case-contract/run.sh
#
# `str.lower`/`str.upper` are simple (1:1) Unicode case mapping. The JVM backend
# gets that from Character.toUpperCase/toLowerCase; the C runtime has no Unicode
# tables, so it carries runtime/c/dawn_case_table.h, generated from that same
# oracle. Two implementations of one mapping only stays true if something checks,
# and this is that something:
#
#   1. every code point the oracle maps somewhere, plus a spread of ones it
#      should leave alone, run through the compiled `str.upper`/`str.lower`;
#   2. the table regenerated and diffed against the checked-in header, so a JDK
#      whose Unicode version has moved on fails here rather than silently in a
#      native binary.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
probe="$root/scripts/case-contract/probe.dawn"
header="$root/runtime/c/dawn_case_table.h"

out="$("$root/bin/dawn" run "$probe")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: str.upper/str.lower disagree with Character.toUpperCase/toLowerCase" >&2
  exit 1
fi

fresh="$(mktemp)"
trap 'rm -f "$fresh"' EXIT
DAWN_CASE_EMIT=1 "$root/bin/dawn" run "$probe" > "$fresh"

if ! diff -u "$header" "$fresh"; then
  echo "FAIL: runtime/c/dawn_case_table.h is not what the oracle generates" >&2
  echo "      regenerate with: DAWN_CASE_EMIT=1 bin/dawn run $probe > $header" >&2
  exit 1
fi

checked="$(printf '%s\n' "$out" | grep '^checked ' | cut -d' ' -f2)"
ranges="$(grep -c '^    {' "$header")"
echo "PASS  $checked code points agree with the oracle; $ranges ranges in the C table"
