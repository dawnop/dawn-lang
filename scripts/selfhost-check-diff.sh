#!/usr/bin/env bash
# Golden diff for the self-hosted checker (P3b): run every .dawn file in the
# repo through both `dawn __check` and `selfhost check` (file mode pulls each
# file's use-closure) and require byte-identical dumps: diagnostics, pub fn
# signatures, and comptime const values. Extra corpus directories may be
# passed as arguments. The selfhost JVM gets -Xss512m: the comptime
# interpreter recurses on the host stack (the Kotlin one uses a 64MB thread).
set -euo pipefail
cd "$(dirname "$0")/.."

# the Kotlin reference CLI (bin/dawn runs selfhost since M8 phase 3)
DAWN=${DAWN_BIN:-./bin/dawn-kotlin}
OUT=${TMPDIR:-/tmp}/selfhost-check-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

mapfile -t files < <(find compiler/src/main/resources/std compiler/src/test/resources \
  examples site playground selfhost "$@" -name '*.dawn' -type f 2>/dev/null | sort)
echo "corpus: ${#files[@]} files"

"$DAWN" __check "${files[@]}" > "$OUT/kotlin.dump"

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
# The compiler jar rides along: the corpus includes selfhost's own codegen,
# whose `use java "dawn.tool.AdtClassWriter"` must reflect for both checkers.
java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main check "${files[@]}" > "$OUT/dawn.dump"

if diff -u "$OUT/kotlin.dump" "$OUT/dawn.dump" > "$OUT/diff.txt"; then
  echo "OK: check dumps are byte-identical"
else
  head -40 "$OUT/diff.txt"
  total=$(grep -c '^[+-]' "$OUT/diff.txt" || true)
  echo "FAIL: dumps differ ($total diff lines; full diff was at $OUT/diff.txt)"
  cp "$OUT/diff.txt" /tmp/selfhost-check-diff-last.txt
  exit 1
fi
