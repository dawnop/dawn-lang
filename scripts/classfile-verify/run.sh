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
# call.
#
# Two mutants ride along, and they answer different questions. selftest.sh
# (before anything is emitted) asks whether the checks can fail at all.
# The corpus mutant (after the loop) asks whether they are looking at the
# emitted directory -- its fixtures deliberately carry names the toolchain jar
# also holds, which is the only way to catch a return to parent-first
# delegation. Neither is optional: this gate has been vacuous twice, once per
# question.
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
#   * wrong answers from legal bytes. The dedicated Java-tail fixture below is
#     executed for its side effects; the general corpus is only verified.
#
# Modes, for CI scheduling and nothing else (the 2026-08-20 job split):
#
#   run.sh                          # everything, the local default
#   run.sh --never-mutants-only     # the 13 compiling Never mutants + probe
#   run.sh --without-never-mutants  # selftest, corpus verify, corpus mutant,
#                                   # constant-pool scan
#
# The Never block is ~180s of compiling mutants and shares nothing with the
# corpus loop but the javac'd Verify classes (both modes compile those, ~2s),
# so it runs as its own gates.yml job. The two modes partition the full run:
# nothing is conditional on anything but which job carries it, and the local
# no-flag run still does the whole thing in one process.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)

mode=all
case "${1:-}" in
  '') ;;
  --never-mutants-only) mode=never ;;
  --without-never-mutants) mode=verify ;;
  *)
    echo "usage: $0 [--never-mutants-only | --without-never-mutants]" >&2
    exit 2
    ;;
esac

./bin/dawn --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

javac -d "$work" scripts/classfile-verify/Verify.java scripts/classfile-verify/AccessCheck.java

if [ "$mode" != never ]; then
  # Prove the gate can fail before believing that it did not.
  scripts/classfile-verify/selftest.sh "$work"
fi

never_probe=scripts/classfile-verify/never_probe.py

never_die() {
  echo "FAIL: $*" >&2
  exit 1
}

new_never_mutant() {
  never_mutant="$work/never-mutants/$1"
  mkdir -p "$never_mutant"
  cp -R "$root/selfhost" "$never_mutant/selfhost"
  cp -R "$root/compiler-plan" "$never_mutant/compiler-plan"
  ln -s "$root/packages" "$never_mutant/packages"
}

build_never_mutant() {
  if ! ./bin/dawn build "$never_mutant/selfhost" -o "$never_mutant/compiler.jar" \
      > "$never_mutant/build.out" 2>&1; then
    cat "$never_mutant/build.out" >&2
    never_die "$1 mutant did not compile"
  fi
  if ! java -jar "$never_mutant/compiler.jar" --version \
      > "$never_mutant/version.out" 2>&1; then
    cat "$never_mutant/version.out" >&2
    never_die "$1 mutant jar did not answer --version"
  fi
}

replace_never_once() {
  python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
old = sys.argv[2]
new = sys.argv[3]
text = path.read_text()
if text.count(old) != 1:
    raise SystemExit(f"mutation anchor drifted in {path}: expected one, found {text.count(old)}")
path.write_text(text.replace(old, new))
PY
}

expect_never_marker() {
  local name=$1
  local marker=$2
  local mode=${3:---mutant}
  if python3 "$never_probe" "$never_mutant/compiler.jar" "$work" "$mode" \
      > "$never_mutant/probe.out" 2>&1; then
    never_die "$name mutant stayed green"
  fi
  grep '^ASSERT: ' "$never_mutant/probe.out" > "$never_mutant/assertions.out" || true
  printf 'ASSERT: %s\n' "$marker" > "$never_mutant/assertions.expected"
  if ! cmp -s "$never_mutant/assertions.expected" "$never_mutant/assertions.out"; then
    cat "$never_mutant/probe.out" >&2
    never_die "$name mutant missed its unique owning assertion"
  fi
  echo "PASS  $name compiles, then turns only $marker red"
}

run_never_mutants() {

python3 "$never_probe" "$root/build/dawn-selfhost.jar" "$work"

new_never_mutant reject-wide-sam-bottom
replace_never_once "$never_mutant/selfhost/src/check/checker.dawn" \
  '    r == TyInt || r == TyNever' \
  '    r == TyInt'
build_never_mutant reject-wide-sam-bottom
expect_never_marker reject-wide-sam-bottom NEVER_WIDE_SAM_ACCEPTANCE

new_never_mutant use-pop-for-wide-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '    CallTwo -> { m.visitInsn(OP_POP2) }' \
  '    CallTwo -> { m.visitInsn(OP_POP) }'
build_never_mutant use-pop-for-wide-bottom
expect_never_marker use-pop-for-wide-bottom NEVER_WIDE_SAM_ADAPTER_TERMINATION

new_never_mutant omit-direct-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner, name, d, false)
      finish_call(g1, ty, call_result_of_desc(d))' \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner, name, d, false)
      (g1, true)'
build_never_mutant omit-direct-bottom
expect_never_marker omit-direct-bottom NEVER_DIRECT_CALL_TERMINATION

new_never_mutant omit-dynamic-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '  if is_bottom(ret_static) {' \
  '  if false {'
build_never_mutant omit-dynamic-bottom
expect_never_marker omit-dynamic-bottom NEVER_DYNAMIC_CALL_TERMINATION

new_never_mutant omit-impl-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        impl_method_name(gx, tr.name, subject, method), d, false)
      finish_call(g1, ty, call_result_of_desc(d))' \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        impl_method_name(gx, tr.name, subject, method), d, false)
      (g1, true)'
build_never_mutant omit-impl-bottom
expect_never_marker omit-impl-bottom NEVER_IMPL_CALL_TERMINATION

new_never_mutant omit-default-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        default_method_name(tr.name, method), d, false)
      finish_call(g1, ty, call_result_of_desc(d))' \
'      g1.mv.visitMethodInsn(OP_INVOKESTATIC, owner,
        default_method_name(tr.name, method), d, false)
      (g1, true)'
build_never_mutant omit-default-bottom
expect_never_marker omit-default-bottom NEVER_DEFAULT_CALL_TERMINATION

new_never_mutant omit-trait-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'      g1.mv.visitMethodInsn(OP_INVOKEINTERFACE, tr_iface(tr.owner, tr.name), method,
        d, true)
      finish_call(g1, ty, call_result_of_desc(d))' \
'      g1.mv.visitMethodInsn(OP_INVOKEINTERFACE, tr_iface(tr.owner, tr.name), method,
        d, true)
      (g1, true)'
build_never_mutant omit-trait-bottom
expect_never_marker omit-trait-bottom NEVER_TRAIT_CALL_TERMINATION

new_never_mutant omit-dictionary-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '    if is_bottom(ms.sig.ret) {' \
  '    if false {'
build_never_mutant omit-dictionary-bottom
expect_never_marker omit-dictionary-bottom NEVER_DICTIONARY_TERMINATION

new_never_mutant omit-closure-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '  if is_bottom(b.fret) {' \
  '  if false {'
build_never_mutant omit-closure-bottom
expect_never_marker omit-closure-bottom NEVER_CLOSURE_TERMINATION

new_never_mutant omit-sam-bridge-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '  if b.bottom {' \
  '  if false {'
build_never_mutant omit-sam-bridge-bottom
expect_never_marker omit-sam-bridge-bottom NEVER_SAM_BRIDGE_TERMINATION

new_never_mutant omit-sam-adapter-bottom
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  '  if s.bottom {' \
  '  if s.bottom && s.sam_ret != "java.lang.Object" {'
build_never_mutant omit-sam-adapter-bottom
expect_never_marker omit-sam-adapter-bottom NEVER_SAM_ADAPTER_TERMINATION

new_never_mutant return-from-object-sam-adapter
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'  if s.bottom {
    terminate_bottom(m, call_result_of_desc(rd))
  } else {' \
'  if s.bottom {
    if s.sam_ret == "java.lang.Object" {
      let terminate = Label.new()
      m.visitInsn(OP_POP)
      m.visitInsn(OP_ICONST_1)
      m.visitJumpInsn(OP_IFEQ, terminate)
      m.visitInsn(OP_ACONST_NULL)
      m.visitInsn(OP_ARETURN)
      m.visitLabel(terminate)
      m.visitInsn(OP_ACONST_NULL)
      m.visitInsn(OP_ATHROW)
    } else {
      terminate_bottom(m, call_result_of_desc(rd))
    }
  } else {'
build_never_mutant return-from-object-sam-adapter
expect_never_marker return-from-object-sam-adapter \
  NEVER_SAM_ADAPTER_TERMINATION --verified-mutant

new_never_mutant return-from-wide-sam-adapter
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
'  if s.bottom {
    terminate_bottom(m, call_result_of_desc(rd))
  } else {' \
'  if s.bottom {
    if s.sam_ret == "long" {
      let terminate = Label.new()
      m.visitInsn(OP_POP2)
      m.visitInsn(OP_ICONST_1)
      m.visitJumpInsn(OP_IFEQ, terminate)
      ldc_long(m, 0)
      m.visitInsn(OP_LRETURN)
      m.visitLabel(terminate)
      m.visitInsn(OP_ACONST_NULL)
      m.visitInsn(OP_ATHROW)
    } else {
      terminate_bottom(m, call_result_of_desc(rd))
    }
  } else {'
build_never_mutant return-from-wide-sam-adapter
expect_never_marker return-from-wide-sam-adapter \
  NEVER_WIDE_SAM_ADAPTER_TERMINATION --verified-mutant

}

run_corpus_checks() {

fail=0
java_tail_fixture=scripts/classfile-verify/java_tail_unit.dawn
# examples/interop/interop.dawn is here for check 1, and it is the only corpus entry
# that exercises it in this direction: `Path.of` and `List.of` are static
# methods declared on JDK *interfaces*, so the call sites emit `invokestatic`
# against an `InterfaceMethodref`, which is illegal below class-file version 52
# and was therefore unreachable for the whole K-A4 era. This file emits five
# such instructions; selfhost, site and calc.dawn emit none (measured
# 2026-08-07 with `javap -c` over their emitted class files). The failure lands
# at class *load* rather than at type check, so a corpus entry that is only
# compiled would not see it -- which is why it is registered here and not only
# in the emit differential.
for t in selfhost site packages/json packages/web packages/sha2 packages/inflate \
    playground examples/projects/calc.dawn examples/interop/interop.dawn \
    examples/effects/handlers.dawn examples/text/chars.dawn \
    examples/errors/barriers.dawn "$java_tail_fixture"; do
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

./bin/dawn test "$java_tail_fixture"
echo "OK: Java Unit-tail results are evaluated, discarded, and runnable"

# The second mutant, and the one selftest.sh cannot be. Its fixtures live in
# pkgA/pkgB, names the toolchain jar does not carry, so they would have stayed
# red right through this gate's actual bug -- parent-first delegation, under
# which the whole selfhost corpus resolved out of the jar and the directory
# under test was never opened. Only a mutant on a name the jar ALSO holds
# separates "found nothing" from "read nothing", so flip a method of the
# emitted dawn/rt/Strings and require a red. Costs one more pass over a corpus
# that is already on disk.
mut="$work/corpus-mutant"
cp -r "$work/emit/selfhost" "$mut"
scripts/classfile-verify/privatise.py "$mut/dawn/rt/Strings.class" join
if java -cp "$work:$root/build/dawn-selfhost.jar" Verify "$mut" > /dev/null 2>&1; then
  echo "FAIL: the gate passed a corpus with a private dawn/rt/Strings.join in it," >&2
  echo "      so its verdict on the real corpora carries no information" >&2
  exit 1
fi
echo "OK: corpus mutant -- the gate reds on a private reference in the emitted selfhost corpus"

scripts/constpool-scan.py "$work/emit"

}

if [ "$mode" != verify ]; then
  run_never_mutants
fi
if [ "$mode" != never ]; then
  run_corpus_checks
fi
