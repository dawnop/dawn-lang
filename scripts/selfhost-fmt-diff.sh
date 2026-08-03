#!/usr/bin/env bash
# Differential for the formatter against the previous release (the N-1 oracle
# since kotlin-final): HEAD `dawn fmt` must agree byte for byte — over the
# already-formatted corpus (the fixed point) and over mangled copies (leading
# indentation stripped, intra-line space runs squeezed), which exercise real
# reflow work. An intentional formatter change lands with an `Emit-Change:`
# line in its commit message.
#
# `DAWN_SELF` names the toolchain under test; it defaulted to ./bin/dawn with
# no way to say otherwise, so this gate only ever saw the JVM backend. The
# native driver grew `fmt` in K-B2 and scripts/native-cli-diff.sh runs this
# same script with DAWN_SELF pointed at the native binary — which is what
# makes the oracle cover both backends rather than one.
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
SELF=${DAWN_SELF:-./bin/dawn}
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
"$SELF" fmt "$OUT/d" > /dev/null

. scripts/emitchange.sh
emitchange_load
if diff -r "$OUT/k" "$OUT/d" > "$OUT/diff.txt" 2>&1; then
  emit_gate "fmt" 0
else
  emit_gate "fmt" 1 || { head -40 "$OUT/diff.txt"; exit 1; }
fi
echo "OK: $SELF agrees with the previous release over $i files (plus mangled copies)"
