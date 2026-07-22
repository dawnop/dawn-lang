#!/usr/bin/env bash
# Golden diff for the self-hosted formatter: `selfhost fmt` must agree with
# `dawn fmt` byte for byte — over the already-formatted corpus (the fixed
# point) and over mangled copies (leading indentation stripped, intra-line
# space runs squeezed), which exercise real reflow work.
set -euo pipefail
cd "$(dirname "$0")/.."

# the Kotlin reference CLI (bin/dawn runs selfhost since M8 phase 3)
DAWN=${DAWN_BIN:-./bin/dawn-kotlin}
OUT=${TMPDIR:-/tmp}/selfhost-fmt-diff.$$
mkdir -p "$OUT/k" "$OUT/d"
trap 'rm -rf "$OUT"' EXIT

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null

i=0
while IFS= read -r f; do
  i=$((i + 1))
  cp "$f" "$OUT/k/$i.dawn"
  sed -e 's/^[[:space:]]*//' -e 's/   */ /g' "$f" > "$OUT/k/m$i.dawn"
  cp "$OUT/k/$i.dawn" "$OUT/d/$i.dawn"
  cp "$OUT/k/m$i.dawn" "$OUT/d/m$i.dawn"
done < <(git ls-files '*.dawn')

"$DAWN" fmt "$OUT/k" > /dev/null
java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main fmt "$OUT/d" > /dev/null

if ! diff -r "$OUT/k" "$OUT/d" > "$OUT/diff.txt" 2>&1; then
  head -40 "$OUT/diff.txt"
  echo "FAIL: formatter output differs"
  exit 1
fi
echo "OK: formatter agrees with dawn fmt over $i files (plus mangled copies)"
