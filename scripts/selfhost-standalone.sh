#!/usr/bin/env bash
# Standalone selfhost jar (the last P5 leftover): `selfhost build` packs the
# program classes together with the two compiler-jar residents it needs at
# runtime (the dawn.tool frame-writer shim and ASM), so the self-hosted
# compiler runs with no Kotlin artifact on the class path. Two checks:
#   independence — the standalone jar alone re-emits a corpus target
#                  byte-identically to `dawn __emit`
#   closure      — the standalone jar rebuilds itself and the two jars are
#                  byte-identical (the jar writer is deterministic)
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-standalone.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# coursierapi rides along so the standalone jar can resolve [java-deps]
# (it is fully shaded — coursierapi/ and coursierapi/shaded/ cover all of it)
VENDOR=(--vendor dawn/tool --vendor org/objectweb/asm --vendor coursierapi)

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null

# stage A: the Kotlin-built selfhost builds the standalone jar (the compiler
# jar is still on the class path here — that is where the vendored packages
# are copied from)
java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main \
  build selfhost -o "$OUT/a.jar" "${VENDOR[@]}" > /dev/null

# independence: nothing but the standalone jar on the class path
mkdir -p "$OUT/k" "$OUT/d"
"$DAWN" __emit examples/calc.dawn -o "$OUT/k" > /dev/null
java -Xss512m -jar "$OUT/a.jar" emit examples/calc.dawn -o "$OUT/d" > /dev/null
diff -r "$OUT/k" "$OUT/d"
echo "OK: standalone jar re-emits calc byte-identically (no compiler jar)"

# closure: the standalone jar rebuilds itself (vendored packages now come out
# of the standalone jar's own class path), byte for byte
java -Xss512m -jar "$OUT/a.jar" build selfhost -o "$OUT/b.jar" "${VENDOR[@]}" > /dev/null
cmp "$OUT/a.jar" "$OUT/b.jar"
echo "OK: standalone closure — the jar rebuilt itself byte-identically"
