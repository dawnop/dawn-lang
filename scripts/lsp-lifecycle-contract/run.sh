#!/usr/bin/env bash
# Compile and execute lifecycle regressions against private selfhost copies.
# Every mutant reaches a normal LSP session and must fail only its target case.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
harness="$root/scripts/lsp-lifecycle.py"
work="$(mktemp -d "${TMPDIR:-/tmp}/lsp-lifecycle-contract.XXXXXX")"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The anchors live in mutate.py, one registered mutation per mutant name, so
# mutation-anchor-preflight.py proves each one matches exactly once before any
# build, not only when this script reaches that mutant.
mutate() {
  python3 "$root/scripts/lsp-lifecycle-contract/mutate.py" "$1" "$2"
}

expect_mutant_red() {
  local name=$1 case_name=$2 expected=$3
  local mutant="$work/mutant-$name"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  cp -R "$root/compiler-plan" "$mutant/compiler-plan"
  ln -s "$root/packages" "$mutant/packages"
  mutate "$name" "$mutant"
  if ! java -Xss512m -Xmx2g -jar "$root/build/dawn-selfhost.jar" build \
      "$mutant/selfhost" -o "$mutant/compiler.jar" --std "$root/std" \
      --vendor org/objectweb/asm --vendor coursierapi \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$name mutant did not compile"
  fi
  if "$harness" --case "$case_name" \
      java -Xss512m -Xmx2g -jar "$mutant/compiler.jar" lsp \
      > "$mutant/run.out" 2>&1; then
    fail "$name mutant stayed green"
  fi
  if ! grep -Fq "$expected" "$mutant/run.out"; then
    cat "$mutant/run.out" >&2
    fail "$name mutant missed its intended lifecycle boundary"
  fi
  echo "PASS  $name mutant compiles, runs, and turns $case_name red"
}

"$root/bin/dawn" --version > /dev/null
"$harness"

expect_mutant_red gate-after-update preinit-notification \
  'FAIL preinit-notification: unexpected server notification'
expect_mutant_red early-exit-zero early-exit \
  'FAIL early-exit: pre-init exit status: expected 1, got 0'
expect_mutant_red shutdown-continues post-shutdown \
  'FAIL post-shutdown: request after shutdown: expected error -32600'
expect_mutant_red shutdown-flushes pending-discard \
  'FAIL pending-discard: unexpected server notification'
expect_mutant_red repeat-initialize repeat-initialize \
  'FAIL repeat-initialize: repeat initialize: expected error -32600'
