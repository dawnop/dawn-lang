#!/usr/bin/env bash
# Golden diff for `selfhost run` / `selfhost test` / `selfhost doc`: stdout+
# stderr and exit codes must match the Kotlin CLI — including the failing-test
# report shape and the doc JSON byte for byte.
set -euo pipefail
cd "$(dirname "$0")/.."

DAWN=${DAWN_BIN:-./bin/dawn}
OUT=${TMPDIR:-/tmp}/selfhost-run-diff.$$
mkdir -p "$OUT"
trap 'rm -rf "$OUT"' EXIT

"$DAWN" build selfhost -o "$OUT/selfhost.jar" > /dev/null
SH=(java -Xss512m -cp "$OUT/selfhost.jar:compiler/build/libs/dawn.jar" main)

check() { # name kotlin-exit dawn-exit
  if [ "$2" != "$3" ]; then echo "FAIL: $1 exit codes differ ($2 vs $3)"; exit 1; fi
  if ! diff "$OUT/k.txt" "$OUT/d.txt"; then echo "FAIL: $1 output differs"; exit 1; fi
  echo "OK   $1"
}

# run: with and without args (the no-args calc usage path exits 1)
"$DAWN" run examples/calc.dawn "1 + 2 * 3" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" run examples/calc.dawn "1 + 2 * 3" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "run calc (args)" "$k" "$d"

"$DAWN" run examples/calc.dawn > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" run examples/calc.dawn > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "run calc (usage)" "$k" "$d"

# test: a green multi-module suite
"$DAWN" test site > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test site > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "test site" "$k" "$d"

# test: the failing path (report shape, message indentation, exit 1)
cat > "$OUT/failing.dawn" <<'EOF'
fn double(x: Int) -> Int = x * 2

test "doubling four" {
  assert double(4) == 8
}

test "a deliberate failure" {
  assert double(3) == 7
}
EOF
"$DAWN" test "$OUT/failing.dawn" > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" test "$OUT/failing.dawn" > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "test failing fixture" "$k" "$d"

# doc: the builtin reference and a project with types, traits and impls
"$DAWN" doc --builtins > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc --builtins > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc --builtins" "$k" "$d"

"$DAWN" doc site > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc site > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc site" "$k" "$d"

"$DAWN" doc examples/traits.dawn > "$OUT/k.txt" 2>&1 && k=0 || k=$?
"${SH[@]}" doc examples/traits.dawn > "$OUT/d.txt" 2>&1 && d=0 || d=$?
check "doc traits example" "$k" "$d"

echo "OK: selfhost run/test/doc agree with the Kotlin CLI"
