#!/usr/bin/env bash
# The wire contract of the web package's two servers, built and run, with its
# negative controls.
#
# packages/web has two servers: web_jvm/server on jdk.httpserver, and
# web/exchange, the single-exchange adapter the native backend builds. They
# parse HTTP differently (the JDK parses before any Dawn runs; the adapter is
# Dawn all the way down) and are meant to answer every request the same. That is
# a property of two programs, and two programs drift: a fix to one that nobody
# makes in the other, a chunked-body rule one of them reads differently. This
# builds both sides of one application (contract_app), sends the same raw
# requests to both, and compares the responses byte for byte after the
# differences that belong to the JDK are named and removed (contract.py has
# the list and the reason for each).
#
# Then the controls. A contract that has only ever been green has not shown it
# can see, so this breaks the adapter four ways, on a copy, and requires the
# comparison to go red on the fixture that exists for that rule:
#
#   chunked decoding gone      the chunked request fixtures
#   HEAD writes its body       head-hello
#   dot-segment check gone     dot-segment-plain
#   guard never consulted      guard-refuses
#
# A mutation that does not apply (the line it rewrites has moved) fails the
# script rather than silently testing nothing, and mutation-anchor-preflight
# proves each anchor in mutate.py exactly-once before any build.
#
#   scripts/web-exchange-contract/run.sh <path to dawnc>
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
HERE=scripts/web-exchange-contract

DAWNC=${1:?usage: run.sh <dawnc>}
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

OUT=$(mktemp -d "${TMPDIR:-/tmp}/web-exchange-contract.XXXXXX")
trap 'rm -rf "$OUT"' EXIT

JAVA=$(DAWN_LAUNCHER_PRINT_JAVA=1 ./bin/dawn)

echo "== build both sides of the contract application =="
./bin/dawn build "$HERE/jvm" -o "$OUT/jvm.jar" > "$OUT/jvm-build.txt" 2>&1 || { cat "$OUT/jvm-build.txt"; echo "FAIL: JVM side did not build"; exit 1; }
"$DAWNC" build "$HERE/native" -o "$OUT/native" > "$OUT/native-build.txt" 2>&1 || { cat "$OUT/native-build.txt"; echo "FAIL: native side did not build"; exit 1; }

echo "== the contract: one set of raw requests, both servers =="
python3 -I "$HERE/contract.py" --java "$JAVA" --jvm "$OUT/jvm.jar" --native "$OUT/native"

# A copy of the tree the native side builds from, with one rule of the adapter
# broken by mutate.py (whose anchors the preflight proves exactly-once before any
# build). $1 is the mutation, $2 the fixtures that must go red.
control() {
  local mutation=$1 expect=$2
  local t="$OUT/ctl-$mutation"
  mkdir -p "$t/packages" "$t/scripts/web-exchange-contract"
  cp -R packages/web packages/json "$t/packages/"
  cp -R "$HERE/app" "$HERE/native" "$t/scripts/web-exchange-contract/"
  python3 -I "$HERE/mutate.py" "$mutation" "$t"
  "$DAWNC" build "$t/scripts/web-exchange-contract/native" -o "$t/native" > "$t/build.txt" 2>&1 || { cat "$t/build.txt"; echo "FAIL: control $mutation did not build"; exit 1; }
  if python3 -I "$HERE/contract.py" --java "$JAVA" --jvm "$OUT/jvm.jar" --native "$t/native" --only "$expect" > "$t/run.txt" 2>&1; then
    cat "$t/run.txt"
    echo "FAIL: control $mutation: the contract stayed green with the adapter broken"
    exit 1
  fi
  local name
  for name in ${expect//,/ }; do
    grep -q "^FAIL $name:" "$t/run.txt" || { cat "$t/run.txt"; echo "FAIL: control $mutation: fixture $name did not go red"; exit 1; }
  done
  echo "OK   control: $mutation turns the contract red ($expect)"
}

echo "== negative controls =="
control no-chunked-decoding "chunked-two-chunks,chunked-binary,chunked-over-ceiling"
control head-writes-its-body "head-hello,head-stream-sized"
control no-dot-segment-check "dot-segment-plain,dot-segment-encoded"
control guard-not-consulted "guard-refuses,guard-refuses-without-reading"
echo "web exchange contract: OK"
