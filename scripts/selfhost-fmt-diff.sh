#!/usr/bin/env bash
# Differential for the formatter against the previous release (the N-1 oracle
# since kotlin-final): HEAD `dawn fmt` must agree byte for byte — over the
# already-formatted corpus (the fixed point) and over mangled copies (leading
# indentation stripped, intra-line space runs squeezed), which exercise real
# reflow work. An intentional formatter change lands with an `Emit-Change:`
# line in its commit message.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
. scripts/seedjar.sh

OUT=${TMPDIR:-/tmp}/selfhost-fmt-diff.$$
mkdir -p "$OUT/k" "$OUT/d"
trap 'rm -rf "$OUT"' EXIT

SEEDJAR="$(seed_jar)"
printf '#!/bin/sh\nexec java -Xss512m -jar "%s" "$@"\n' "$SEEDJAR" > "$OUT/seed-cli"
chmod +x "$OUT/seed-cli"
DAWN=${DAWN_BIN:-"$OUT/seed-cli"}
./bin/dawn --version > /dev/null

i=0
while IFS= read -r f; do
  i=$((i + 1))
  cp "$f" "$OUT/k/$i.dawn"
  sed -e 's/^[[:space:]]*//' -e 's/   */ /g' "$f" > "$OUT/k/m$i.dawn"
  cp "$OUT/k/$i.dawn" "$OUT/d/$i.dawn"
  cp "$OUT/k/m$i.dawn" "$OUT/d/m$i.dawn"
done < <(git ls-files '*.dawn')

"$DAWN" fmt "$OUT/k" > /dev/null
./bin/dawn fmt "$OUT/d" > /dev/null

if ! diff -r "$OUT/k" "$OUT/d" > "$OUT/diff.txt" 2>&1; then
  decls=$(git log "$(tr -d ' \n' < scripts/seed-release.txt)..HEAD" --format=%B 2>/dev/null \
    | grep -E '^Emit-Change:' || true)
  if [ -n "$decls" ]; then
    echo "NOTE formatter differs vs the seed — declared since the tag:"
    echo "$decls" | sed 's/^/       /'
  else
    head -40 "$OUT/diff.txt"
    echo "FAIL: formatter output differs vs the seed and no commit declares it"
    exit 1
  fi
fi
echo "OK: formatter agrees with the previous release over $i files (plus mangled copies)"
