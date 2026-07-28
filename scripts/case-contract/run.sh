#!/usr/bin/env bash
# Ties both backends' case folding to the compiler's table.
#
#   ./scripts/case-contract/run.sh
#
# `str.lower`/`str.upper` are simple (1:1) Unicode case mapping, the one string
# operation whose answer is a table rather than a walk. That table is the
# compiler's -- selfhost/src/case_table.dawn -- and each backend receives it:
# codegen writes it into dawn/rt/Strings, `__emitc` writes it into the
# generated C. It used to be `Character.toUpperCase` on one side and a
# generated C header on the other, which is one mapping only while the two
# JDKs' Unicode releases agree.
#
# The probe checks:
#
#   * the compiled `str.upper`/`str.lower` against the committed table, over
#     every code point it maps plus a spread of ones it does not;
#   * the table against `Character.toUpperCase`, the oracle it was generated
#     from -- only when the running JDK carries the same Unicode release, since
#     otherwise the disagreement is between two JDKs and says nothing about us.
#
# To regenerate the table after moving to a JDK with newer Unicode data:
#
#   DAWN_CASE_EMIT=1 bin/dawn run scripts/case-contract/probe.dawn \
#     > selfhost/src/case_table.dawn
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
probe="$root/scripts/case-contract/probe.dawn"

out="$(DAWN_CASE_TABLE="$root/selfhost/src/case_table.dawn" "$root/bin/dawn" run "$probe")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: case folding disagrees with the compiler's table" >&2
  exit 1
fi

printf '%s\n' "$out" | sed -n 's/^/PASS  /p' | tail -n 4
