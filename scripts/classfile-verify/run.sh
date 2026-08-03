#!/usr/bin/env bash
# Classfile gate (TEST-01, docs/codebase-audit.md §14): the bytes the JVM
# backend emits for the in-repo corpus must be legal, checked here and now
# rather than lazily at whatever moment a test first touches them. The audit's
# argument: the differential system proves the two backends agree, never that
# either one is legal, and the three JSON bugs it opens with all lived under a
# green differential.
#
#   ./scripts/classfile-verify/run.sh
#
# What "legal" means here, stated so the number below is not read for more
# than it says. Three checks over the eight corpora:
#
#   1. every class links -- Class.forName(initialize=true), so the bytecode
#      verifier walks every method body of every emitted class;
#   2. every symbolic reference resolves and is reachable from the class that
#      names it -- Fieldref/Methodref/InterfaceMethodref and CONSTANT_Class,
#      checked against the real access rules (AccessCheck.java);
#   3. no method-handle constant sits in any pool -- the constant-pool gate
#      (K-A5, docs/jvm-base-plan.md §2.1.1), run here because the corpus is
#      already on disk and emitting it again for one struct-module scan would
#      double the slowest part. The verifier cannot stand in for it: a
#      method-handle constant is legal at version 61, so the question is what
#      the pool names, not whether the class links.
#
# Check 2 exists because check 1 does not imply it, which cost a day: linking
# is not resolution, so a private member reached from another class is
# invisible until the instruction runs (#129, and K-A3's closure lowering
# before it). Measured on this branch: the old gate reported "1946 classes,
# 0 illegal" over a mutant that dies with IllegalAccessError on its first
# call. selftest.sh keeps that mutant runnable.
#
# What it still does not cover, stated because a coverage claim that is only
# accurate about its strengths is the defect this gate keeps having:
#
#   * anything about the instruction that names a pool entry, since the entry
#     does not record it -- the IncompatibleClassChangeError family
#     (invokestatic on an instance method, putfield on a static) and the
#     receiver-type clause of protected access;
#   * a NoSuchMethodError from freight pruning that pruned too much: a missing
#     member of an emitted dawn/rt class is counted, not failed, because
#     reach.dawn drops those on purpose. scripts/table-freight owns it;
#   * wrong answers from legal bytes. Nothing emitted is executed here.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)

./bin/dawn --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

javac -d "$work" scripts/classfile-verify/Verify.java scripts/classfile-verify/AccessCheck.java

# Prove the gate can fail before believing that it did not.
scripts/classfile-verify/selftest.sh "$work"

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
  echo "FAIL: illegal bytecode emitted (see VERIFY/ACCESS/RESOLVE FAIL lines above)" >&2
  exit 1
fi
echo "OK: every emitted class links, and every reference it names resolves and is reachable"

scripts/constpool-scan.py "$work/emit"
