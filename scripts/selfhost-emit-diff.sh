#!/usr/bin/env bash
# Golden diff for the self-hosted codegen (P4): byte-compare every class the
# Dawn side can emit so far against the Kotlin emission. Subset mode while the
# port grows — prints coverage; goes strict (full diff -r) once complete.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-emit-diff.$$
mkdir -p "$OUT/k" "$OUT/d"
trap 'rm -rf "$OUT"' EXIT

"$DAWN" __emit examples/calc.dawn -o "$OUT/k" > /dev/null

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
# dawn.tool.AdtClassWriter (the shared frame writer) lives in the compiler jar
java -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main emitrt -o "$OUT/d" > /dev/null

total=0
bad=0
while IFS= read -r f; do
  total=$((total + 1))
  if ! cmp -s "$OUT/k/$f" "$OUT/d/$f"; then
    bad=$((bad + 1))
    echo "DIFF $f"
  fi
done < <(cd "$OUT/d" && find . -name '*.class' | sort)
kotlin_total=$(cd "$OUT/k" && find . -name '*.class' | wc -l)
echo "coverage: $total/$kotlin_total classes, $bad differ"
if [ "$bad" -ne 0 ]; then exit 1; fi
echo "OK: emitted classes are byte-identical"
