#!/usr/bin/env bash
# What the JVM backend writes into `ForeignError.kind`, in exact text.
#
#   ./scripts/error-contract/run.sh
#
# One backend on purpose. `kind` is the backend's own name for a failure class
# and matching on it is backend-specific by design, so the differential corpus
# (scripts/spike-native/foreign_error.dawn) can only ask whether it *is* a name
# -- both backends are checked against one expectation there, and the names
# differ. This script is where the names themselves are written down.
#
# See probe.dawn for what each line asserts and why the three renderings of a
# Java class are worth telling apart. A failed reclaim (`cast`) is
# checked here too, for the same reason and with a second one: on the other
# backend a cast cannot fail at all, so what a failed one says is a JVM
# question by construction.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

out="$("$root/bin/dawn" run "$root/scripts/error-contract/probe.dawn")"

if [ "$(printf '%s\n' "$out" | tail -n 1)" != "mismatches 0" ]; then
  printf '%s\n' "$out" >&2
  echo "FAIL: ForeignError.kind is not what the JVM backend promises" >&2
  exit 1
fi

echo "PASS  ForeignError carries the JVM's binary names"
