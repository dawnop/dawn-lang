#!/usr/bin/env bash
# Golden diff for the self-hosted codegen (P4): byte-compare every class both
# compilers emit for each corpus target. Strict: any difference or any class
# emitted by only one side fails.
set -euo pipefail
cd "$(dirname "$0")/.."

# the Kotlin reference CLI (bin/dawn runs selfhost since M8 phase 3)
DAWN=${DAWN_BIN:-./bin/dawn-kotlin}
OUT=${TMPDIR:-/tmp}/selfhost-emit-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

# Corpus: every example, plus directory projects. Extra targets may be passed
# as arguments (e.g. selfhost itself — slow, so CI opts in explicitly).
targets=(examples/*.dawn examples/m*/*.dawn)
if [ -d site/src ]; then targets+=(site); fi
if [ -d playground/src ]; then targets+=(playground); fi
targets+=("$@")

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null

fail=0
i=0
for t in "${targets[@]}"; do
  i=$((i + 1))
  k="$OUT/k$i"
  d="$OUT/d$i"
  mkdir -p "$k" "$d"
  "$DAWN" __emit "$t" -o "$k" > /dev/null
  # dawn.tool.AdtClassWriter (the shared frame writer) lives in the compiler jar
  java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main emit "$t" -o "$d" > /dev/null
  if diff -r "$k" "$d" > "$OUT/diff.txt" 2>&1; then
    n=$(find "$k" -name '*.class' | wc -l)
    echo "OK   $t ($n classes)"
  else
    fail=1
    echo "DIFF $t"
    head -20 "$OUT/diff.txt"
  fi
done

if [ "$fail" -ne 0 ]; then
  echo "FAIL: emitted classes differ"
  exit 1
fi
echo "OK: all targets byte-identical"
