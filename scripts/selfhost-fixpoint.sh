#!/usr/bin/env bash
# P5 fixed point: stage1 (Kotlin emits selfhost), stage2 (that selfhost emits
# selfhost), stage3 (the self-emitted compiler emits selfhost). All three must
# be byte-identical — the self-hosting proof.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-fixpoint.$$
mkdir -p "$OUT/s1" "$OUT/s2" "$OUT/s3"
trap 'rm -rf "$OUT"' EXIT

"$DAWN" __emit selfhost -o "$OUT/s1" > /dev/null
"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null

CP_TAIL="compiler/build/libs/dawn.jar"
java -Xss512m -cp "$OUT/selfhost.jar:$CP_TAIL" main emit selfhost -o "$OUT/s2" > /dev/null
diff -r "$OUT/s1" "$OUT/s2" > /dev/null || { echo "FAIL: stage2 != stage1"; exit 1; }
echo "stage2 == stage1 (kotlin)"

# stage3 runs the compiler from its own emitted classes (the compiler jar
# supplies ASM and dawn.tool.AdtClassWriter)
java -Xss512m -cp "$OUT/s2:$CP_TAIL" main emit selfhost -o "$OUT/s3" > /dev/null
diff -r "$OUT/s2" "$OUT/s3" > /dev/null || { echo "FAIL: stage3 != stage2"; exit 1; }
n=$(find "$OUT/s3" -name '*.class' | wc -l)
echo "OK: fixed point — stage2 == stage3 ($n classes)"
