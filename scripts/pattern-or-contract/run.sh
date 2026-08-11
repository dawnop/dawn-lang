#!/usr/bin/env bash
# Or-patterns have one arm, one environment and three independent binder rules.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/pattern-or-contract"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
fixture="$root/scripts/checker-corpus/cases/or_pattern.dawn"
work=$(mktemp -d "${TMPDIR:-/tmp}/pattern-or-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "pattern-or-contract: $*" >&2
  exit 1
}

for command in java python3; do
  command -v "$command" > /dev/null || fail "missing required command: $command"
done

build_compiler() {
  local source=$1 output=$2 label=$3
  if ! "$dawn" build "$source" -o "$output" > "$work/$label-build.out" 2>&1; then
    cat "$work/$label-build.out" >&2
    fail "$label compiler did not compile"
  fi
  java -Xss512m -Xmx2g -jar "$output" --version > /dev/null ||
    fail "$label compiler did not initialize"
}

capture_checker() {
  local jar=$1 output=$2
  java -Xss512m -Xmx2g -jar "$jar" __check "$fixture" |
    grep '^D' > "$output"
}

ASSERT_SET='or-pattern alternatives bind the same name set'
ASSERT_TYPE='or-pattern alternatives bind each name at one type'

checker_assertions() {
  local output=$1
  if ! grep -Fq 'or-pattern alternative does not bind `x`' "$output" ||
      ! grep -Fq 'or-pattern alternative binds extra name `y`' "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_SET"
  fi
  if ! grep -Fq 'or-pattern binding `x` has type String, but the first alternative binds Int' \
      "$output"; then
    printf 'ASSERT: %s\n' "$ASSERT_TYPE"
  fi
}

observed="$work/observed.jar"
build_compiler "$root/selfhost" "$observed" observed
capture_checker "$observed" "$work/observed.check"
checker_assertions "$work/observed.check" > "$work/observed.assert"
if [ -s "$work/observed.assert" ]; then
  cat "$work/observed.assert" >&2
  cat "$work/observed.check" >&2
  fail "observed checker contract failed"
fi
python3 "$here/lsp.py" java "$observed" "$root" || fail "observed LSP contract failed"
echo "PASS  observed or-pattern compiler satisfies binding and LSP contracts"

expect_checker_mutant_red() {
  local name=$1 expected=$2
  local mutant="$work/$name"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
  python3 "$here/mutate.py" "$name" "$mutant/selfhost/src/check/checker.dawn"
  build_compiler "$mutant/selfhost" "$mutant/compiler.jar" "$name"
  capture_checker "$mutant/compiler.jar" "$mutant/check.out"
  checker_assertions "$mutant/check.out" > "$mutant/assert.out"
  printf 'ASSERT: %s\n' "$expected" > "$mutant/assert.expected"
  if ! cmp -s "$mutant/assert.expected" "$mutant/assert.out"; then
    cat "$mutant/assert.out" >&2
    cat "$mutant/check.out" >&2
    fail "$name mutant missed its owning assertion"
  fi
  echo "PASS  $name mutant compiles, initializes, then turns only its owning assertion red"
}

expect_checker_mutant_red drop-binding-set "$ASSERT_SET"
expect_checker_mutant_red drop-binding-type "$ASSERT_TYPE"

mutant="$work/drop-binding-mutability"
mkdir -p "$mutant"
cp -R "$root/selfhost" "$mutant/selfhost"
cp -R "$root/compiler-plan" "$mutant/compiler-plan"
ln -s "$root/packages" "$mutant/packages"
python3 "$here/mutate.py" drop-binding-mutability \
  "$mutant/selfhost/src/check/checker.dawn"
build_compiler "$mutant/selfhost" "$mutant/compiler.jar" drop-binding-mutability
if "$dawn" test "$mutant/selfhost" > "$mutant/test.out" 2>&1; then
  fail "drop-binding-mutability mutant stayed green"
fi
grep '^FAIL  ' "$mutant/test.out" > "$mutant/fail.out" || true
printf '%s\n' \
  'FAIL  check/checker :: or-patterns reject binding mutability mismatches' \
  > "$mutant/fail.expected"
if ! cmp -s "$mutant/fail.expected" "$mutant/fail.out"; then
  cat "$mutant/test.out" >&2
  fail "drop-binding-mutability mutant missed its owning test"
fi
echo "PASS  drop-binding-mutability compiles, initializes, then turns only its owning test red"

echo "pattern-or-contract: OK"
