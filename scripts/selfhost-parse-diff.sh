#!/usr/bin/env bash
# Golden diff for the self-hosted parser (P3): parse every .dawn file in the
# repo with both the Kotlin parser (`dawn __parse`) and the Dawn one
# (selfhost/), and require byte-identical AST+diagnostic dumps. Extra corpus
# directories may be passed as arguments.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-parse-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

mapfile -t files < <(find compiler/src/main/resources/std compiler/src/test/resources \
  examples site playground selfhost "$@" -name '*.dawn' -type f 2>/dev/null | sort)
echo "corpus: ${#files[@]} files"

"$DAWN" __parse "${files[@]}" > "$OUT/kotlin.dump"

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
java -jar "$OUT/selfhost.jar" parse "${files[@]}" > "$OUT/dawn.dump"

if diff -u "$OUT/kotlin.dump" "$OUT/dawn.dump" > "$OUT/diff.txt"; then
  echo "OK: AST dumps are byte-identical"
else
  head -40 "$OUT/diff.txt"
  total=$(grep -c '^[+-]' "$OUT/diff.txt" || true)
  echo "FAIL: dumps differ ($total diff lines; full diff was at $OUT/diff.txt)"
  exit 1
fi
