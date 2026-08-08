#!/usr/bin/env bash
# Ties std/fmt's Float rendering to its oracle: the shortest-round-trip
# rules spec §4.3 pins, whose shape was taken from JDK 19+ Double.toString
# (Schubfach). Both backends run one probe over an exhaustive boundary set
# plus seeded random bit patterns, byte-comparing fmt.dtoa against the
# running JDK and closing parse_float(to_string(v)) == v on every sample.
#
#   ./scripts/dtoa-contract/run.sh          # 200_000 random samples
#   ./scripts/dtoa-contract/run.sh 20000    # quicker
#
# The default is what CI runs (.github/workflows/gates.yml): the seed is fixed
# in the source, so the corpus is the same on every machine and every run.
#
# The JDK is a valid oracle only from 19 up (older ones carry the pre-2022
# FloatingDecimal, whose output is NOT shortest); the script refuses rather
# than reports a meaningless disagreement. Unlike the Unicode tables this
# needs no regeneration story: the spec owns the rules, and a future JDK
# changing its algorithm would fail *as the JDK's* divergence -- see the
# spec's "宿主换算法也不跟" note. If that ever happens, the oracle here
# pins to a fixed corpus instead of the live JDK.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/dtoa-contract"
n="${1:-200000}"
cc_bin="${CC:-cc}"

# A missing oracle fails. It used to `exit 0` with a SKIP line, which was
# defensible while nothing ran this script; as a gate it would mean the one
# check that can see a wrong dtoa rule reports success by not running. The
# repository's own toolchain is JDK 21, so there is no supported configuration
# in which this branch is reached by accident.
feature=$(java -version 2>&1 | sed -n 's/.*version "\([0-9]*\).*/\1/p' | head -1)
if [ -z "$feature" ] || [ "$feature" -lt 19 ]; then
  echo "FAIL: JDK ${feature:-?} has the pre-2022 FloatingDecimal (or no java at" >&2
  echo "      all); the oracle needs 19+. Run this under the repository's JDK." >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

javac -d "$work" "$here/Oracle.java"
java -cp "$work" Oracle "$n" 20260731 > "$work/oracle.tsv"

"$root/bin/dawn" --version > /dev/null

check() { # label, output
  if [ "$(printf '%s\n' "$2" | tail -n 1 | sed 's/^[0-9]* samples, //')" \
    != "0 dtoa mismatches, 0 rebuild mismatches, 0 open roundtrips" ]; then
    printf '%s\n' "$2" | tail -20 >&2
    echo "FAIL: $1 disagrees with Double.toString or leaves a roundtrip open" >&2
    exit 1
  fi
  echo "OK   $1 ($(printf '%s\n' "$2" | tail -n 1))"
}

out_jvm="$("$root/bin/dawn" run "$here/probe.dawn" "$work/oracle.tsv")"
check jvm "$out_jvm"

"$root/bin/dawn" __emitc "$here/probe.dawn" -o "$work/probe.c"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$root/runtime/c" \
  -o "$work/probe" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm
out_native="$("$work/probe" "$work/oracle.tsv")"
check native "$out_native"

echo "dtoa contract ok"
