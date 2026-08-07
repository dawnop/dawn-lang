#!/usr/bin/env bash
# Ties both backends' Unicode answers to the compiler's tables.
#
#   ./scripts/unicode-contract/run.sh
#
# Two operations have no derivation -- their answer is a table: simple (1:1)
# case mapping (`str.lower`/`str.upper`) and classification (the six
# `char_is_*`). Those tables are the compiler's -- selfhost/src/case_table.dawn
# and selfhost/src/class_table.dawn -- and each backend receives them: codegen
# writes them into dawn/rt/Strings, `__emitc` writes them into the generated C.
# It used to be `Character.toUpperCase`/`Character.isLetter` on one side and a
# generated header (or a panic above U+007F) on the other, which is one answer
# only while the two JDKs' Unicode releases agree.
#
# The probe checks:
#
#   * the compiled `str.upper`/`str.lower`/`char_is_*` against the committed
#     tables, over every code point they say anything about plus a spread of
#     ones they do not;
#   * the tables against `Character`, the oracle they were generated from --
#     only when the running JDK carries the same Unicode release, since
#     otherwise the disagreement is between two JDKs and says nothing about us.
#
# To regenerate after moving to a JDK with newer Unicode data (both, from the
# same JDK -- the probe refuses a mismatched pair):
#
#   DAWN_UNICODE_EMIT=case  bin/dawn run scripts/unicode-contract/probe.dawn \
#     > selfhost/src/embed/unicode_case.dawn
#   DAWN_UNICODE_EMIT=class bin/dawn run scripts/unicode-contract/probe.dawn \
#     > selfhost/src/embed/unicode_class.dawn
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
probe="$root/scripts/unicode-contract/probe.dawn"

out="$(DAWN_UNICODE_DIR="$root/selfhost/src/embed" "$root/bin/dawn" run "$probe")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: a backend disagrees with the compiler's Unicode tables" >&2
  exit 1
fi

printf '%s\n' "$out" | sed -n 's/^/PASS  /p' | tail -n 4
