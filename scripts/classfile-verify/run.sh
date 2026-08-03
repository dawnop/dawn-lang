#!/usr/bin/env bash
# Classfile verification gate (TEST-01, docs/codebase-audit.md §14): every
# class the JVM backend emits for the in-repo corpus must pass the JVM's
# bytecode verifier, now, in one place -- not lazily at whatever moment a
# test first touches it. The audit's argument: the differential system proves
# the backends agree, never that the bytes are legal, and the three JSON bugs
# it opens with all lived under a green differential.
#
# It also runs the constant-pool gate (K-A5, docs/jvm-base-plan.md §2.1.1)
# over the same emitted classes, because the corpus is already on disk here
# and emitting it a second time in a gate of its own would double the slowest
# part for one struct-module scan. The verifier cannot stand in for it: a
# method-handle constant is legal at version 61, so the check it needs is
# about what the pool names, not about whether the class links.
#
#   ./scripts/classfile-verify/run.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)

./bin/dawn --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

javac -d "$work" scripts/classfile-verify/Verify.java

fail=0
for t in selfhost site packages/json packages/web packages/sha2 packages/inflate \
    playground examples/calc.dawn; do
  out="$work/emit/${t//\//_}"
  mkdir -p "$out"
  ./bin/dawn __emit "$t" -o "$out" > /dev/null
  # the toolchain jar (and its lib/) sit on the parent class path: selfhost's
  # own classes reference the vendored ASM and coursier types
  if java -cp "$work:$root/build/dawn-selfhost.jar" Verify "$out" | sed "s|^|  $t: |"; then
    :
  else
    fail=1
  fi
done

if [ "$fail" != 0 ]; then
  echo "FAIL: illegal bytecode emitted (see VERIFY FAIL lines above)" >&2
  exit 1
fi
echo "OK: every emitted class passes the JVM verifier"

scripts/constpool-scan.py "$work/emit"
