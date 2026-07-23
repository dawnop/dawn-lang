#!/usr/bin/env bash
# The self-hosting proof, seed-driven (M8 phase 5): the previous release
# builds HEAD (jar A), A rebuilds HEAD (jar B — HEAD compiled by HEAD), and B
# rebuilds HEAD again (jar C). B and C must be byte-identical: the compiler
# reproduces itself exactly from its own output. A is allowed to differ from
# B (codegen changes between releases land through exactly this gap; the
# N vs N-1 differential guards it with declarations). A quick emit smoke
# proves B works alone with nothing else on the class path.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. scripts/seedjar.sh

OUT=${TMPDIR:-/tmp}/selfhost-fixpoint.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

VENDOR=(--std std --embed-std std
  --vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi)

SEED="$(seed_jar)"
java -Xss512m -jar "$SEED" build selfhost -o "$OUT/a.jar" "${VENDOR[@]}" > /dev/null
java -Xss512m -jar "$OUT/a.jar" build selfhost -o "$OUT/b.jar" "${VENDOR[@]}" > /dev/null
java -Xss512m -jar "$OUT/b.jar" build selfhost -o "$OUT/c.jar" "${VENDOR[@]}" > /dev/null
cmp "$OUT/b.jar" "$OUT/c.jar"
echo "OK: fixed point — HEAD rebuilt itself byte-identically (B == C)"

mkdir -p "$OUT/e"
java -Xss512m -jar "$OUT/b.jar" emit examples/calc.dawn -o "$OUT/e" > /dev/null
n=$(find "$OUT/e" -name '*.class' | wc -l)
echo "OK: standalone smoke — B emitted calc alone ($n classes)"
