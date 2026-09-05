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

javac -d "$work" scripts/classfile-verify/Verify.java scripts/classfile-verify/AccessCheck.java \
  scripts/classfile-verify/ControlFreightCheck.java

# Every `java` below that loads emitted classes carries the export the runtime
# carries. Programs reaching a `ctl` handler or operation link
# dawn/rt/Ctl, CtlCont and CtlK (selfhost/src/jvm/rtclasses.dawn), and CtlCont
# extends jdk.internal.vm.Continuation, which java.base does not export to the
# unnamed module. A real run always has the export: `dawn run` puts this exact
# option on every JVM it spawns (selfhost/src/main.dawn, child_java_cmd) and
# every jar carries it as `Add-Exports` (selfhost/src/jvm/jarw.dawn,
# manifest_text). Without it here the harness dies of IllegalAccessError while
# reading CtlCont's fields -- it would be verifying under conditions no program
# ever runs under. Granting the export is the fix rather than skipping
# jdk.internal classes: the access check then passes because access is really
# granted, which is what the check is for.
add_exports=(--add-exports java.base/jdk.internal.vm=ALL-UNNAMED)


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
generic_fn_value_fixture=scripts/classfile-verify/generic_fn_value.dawn
loop_operand_fixture=scripts/spike-native/loop_operand.dawn
loop_operand_java_fixture=scripts/classfile-verify/loop_operand_java.dawn
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
# effect_poly_evidence.dawn is here for the same reason interop.dawn is, on the
# other axis: rule 丁 gives every effect variable an *erased* hidden parameter,
# and `Object` accepts anything, so a caller and a callee that disagree about
# how many words cross link happily and read the slot next door. The arity is
# the one part of that a verifier does check, and this fixture puts it on every
# boundary at once -- a variable forwarded through two frames, the same slot on
# a dictionary interface, an exact label slot beside an erased one, and a
# function value crossing both directions of a widened row. The differential
# cannot stand in for it: a miscount is legal bytes with a wrong answer.
# generic_fn_value.dawn is the third of that family, on the erasure axis: a
# generic function used as a value gets a wrapper sized by the instantiation
# and calls a callee sized by the declaration, and a type parameter is an
# erased slot. Handing a long to a slot spelled `Ljava/lang/Object;` is a link
# failure and nothing a type check or a differential can see, since both
# backends emitted the same wrong shape.
# An array rather than a `for t in ...` word list so that the slash-free
# entries state an input the way scripts/gate-map/gatemap.py reads one (rule B,
# `+=(...)` context): `selfhost`, `site` and `playground` are three of the
# largest corpora this gate emits, and until they were written here the map
# reported that no file under selfhost/src was watched by this gate.
corpus=(selfhost site playground)
corpus+=(packages/json packages/web packages/sha2 packages/inflate)
corpus+=(examples/projects/calc.dawn examples/interop/interop.dawn)
corpus+=(examples/effects/handlers.dawn examples/text/chars.dawn)
corpus+=(examples/errors/barriers.dawn)
corpus+=(scripts/classfile-verify/effect_poly_evidence.dawn)
corpus+=(scripts/classfile-verify/control_unused.dawn scripts/spike-native/ctl_resume.dawn)
corpus+=(scripts/classfile-verify/control_foreign.dawn scripts/classfile-verify/control_adt.dawn)
corpus+=(scripts/classfile-verify/control_erased.dawn scripts/classfile-verify/control_trait.dawn)
corpus+=("$generic_fn_value_fixture" "$java_tail_fixture")
corpus+=("$loop_operand_fixture" "$loop_operand_java_fixture")
for t in "${corpus[@]}"; do
  out="$work/emit/${t//\//_}"
  mkdir -p "$out"
  ./bin/dawn __emit "$t" -o "$out" > /dev/null
  # the toolchain jar (and its lib/) sit on the parent class path: selfhost's
  # own classes reference the vendored ASM and coursier types
  if java "${add_exports[@]}" -cp "$work:$root/build/dawn-selfhost.jar" Verify "$out" \
      | sed "s|^|  $t: |"; then
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

# The export above is needed by the corpora that reach the control runtime,
# not by merely importing a declaration from std. Both directions are held
# against emitted program references, independently of reach.Live's answer.
java -cp "$work" ControlFreightCheck "$work"/emit/*
quiet="$work/emit/examples_text_chars.dawn"
unused="$work/emit/scripts_classfile-verify_control_unused.dawn"
suspends="$work/emit/scripts_spike-native_ctl_resume.dawn"
for name in 'std/io$ev$Exit' 'std/io$ev$Console'; do
  if [ -f "$quiet/$name.class" ]; then
    echo "CONTROL_EVIDENCE FAIL: chars retained unused $name" >&2
    exit 1
  fi
done
if [ -f "$unused/"'control_unused$ev$Unused.class' ]; then
  echo "CONTROL_EVIDENCE FAIL: an unused effect declaration retained its record" >&2
  exit 1
fi
for name in Ctl CtlCont CtlK; do
  test -f "$suspends/dawn/rt/$name.class"
  test ! -f "$quiet/dawn/rt/$name.class"
  test ! -f "$unused/dawn/rt/$name.class"
  test -f "$work/emit/scripts_classfile-verify_control_foreign.dawn/dawn/rt/$name.class"
  test -f "$work/emit/scripts_classfile-verify_control_adt.dawn/dawn/rt/$name.class"
  test ! -f "$work/emit/scripts_classfile-verify_control_erased.dawn/dawn/rt/$name.class"
done
test -f "$work/emit/scripts_classfile-verify_control_trait.dawn/"'control_trait$ev$Ask.class'
echo "CONTROL_EVIDENCE PASS: unused declarations add neither records nor runtime"

# Artifact mutants reproduce both mistakes in the emitted directory: turning
# pruning off, and removing the runtime a real suspension still calls. The
# same named assertion must reject both, rather than trusting source spelling.
extra_ctl="$work/control-extra"
missing_ctl="$work/control-missing"
cp -R "$quiet" "$extra_ctl"
cp -R "$suspends" "$missing_ctl"
for name in Ctl CtlCont CtlK; do
  cp "$suspends/dawn/rt/$name.class" "$extra_ctl/dawn/rt/$name.class"
  rm "$missing_ctl/dawn/rt/$name.class"
done
for mutant in "$extra_ctl" "$missing_ctl"; do
  if java -cp "$work" ControlFreightCheck "$mutant" > "$mutant.log" 2>&1; then
    echo "FAIL: CONTROL_FREIGHT accepted artifact mutant $mutant" >&2
    exit 1
  fi
  grep -q '^CONTROL_FREIGHT FAIL:' "$mutant.log"
done
# Declaration descriptors have no obligatory CONSTANT_Class. Conversely an
# arbitrary string containing the same bytes is not a dependency. Check both
# against the oracle itself so neither a CP-only walk nor a UTF8 grep passes.
signature_ctl="$work/control-signature"
string_ctl="$work/control-string"
mkdir -p "$signature_ctl" "$string_ctl"
javac -cp "$suspends" -d "$signature_ctl" scripts/classfile-verify/ControlSignatureFixture.java
javac -d "$string_ctl" scripts/classfile-verify/ControlStringFixture.java
if java -cp "$work" ControlFreightCheck "$signature_ctl" > "$signature_ctl.log" 2>&1; then
  echo "FAIL: CONTROL_FREIGHT ignored declaration-only runtime descriptors" >&2
  exit 1
fi
grep -q '^CONTROL_FREIGHT FAIL:' "$signature_ctl.log"
java -cp "$work" ControlFreightCheck "$string_ctl"
mkdir -p "$signature_ctl/dawn/rt" "$string_ctl/dawn/rt"
for name in Ctl CtlCont CtlK; do
  cp "$suspends/dawn/rt/$name.class" "$signature_ctl/dawn/rt/$name.class"
  cp "$suspends/dawn/rt/$name.class" "$string_ctl/dawn/rt/$name.class"
done
java -cp "$work" ControlFreightCheck "$signature_ctl"
if java -cp "$work" ControlFreightCheck "$string_ctl" > "$string_ctl.log" 2>&1; then
  echo "FAIL: CONTROL_FREIGHT treated an ordinary string as a runtime reference" >&2
  exit 1
fi
grep -q '^CONTROL_FREIGHT FAIL:' "$string_ctl.log"
./bin/dawn run scripts/spike-native/ctl_resume.dawn > "$work/control.out"
cmp scripts/spike-native/ctl_resume.expect "$work/control.out"
./bin/dawn run scripts/classfile-verify/control_foreign.dawn > "$work/control-foreign.out"
test "$(cat "$work/control-foreign.out")" = ok
echo "OK: both control freight mutants rejected; live suspensions still run"

./bin/dawn test "$java_tail_fixture"
echo "OK: Java Unit-tail results are evaluated, discarded, and runnable"

# Executed as well as verified: the return crossing has an answer. A wrapper
# that verifies but unboxes the wrong slot is legal bytes, so the link check
# above is not the whole of what this fixture claims.
./bin/dawn test "$generic_fn_value_fixture"
echo "OK: a generic function value crosses erasure with the right answers"

./bin/dawn run "$loop_operand_fixture" > "$work/loop-operand.out"
diff -u scripts/spike-native/loop_operand.expect "$work/loop-operand.out"
./bin/dawn test "$loop_operand_java_fixture"
echo "OK: loop operands preserve pending values, conversions and evaluation order"

# The previous emitter must fail on the same programs, and specifically at
# ASM frame merging: an unrelated checker/build error is not this regression.
build_operand_mutant() {
  local operand_started
  operand_started=$(date +%s)
  build_never_mutant "$1"
  echo "TIME: $1 compiler build $(( $(date +%s) - operand_started ))s"
}
new_never_mutant unspilled-loop-operands
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  'operands.prepare(cf.body, gx.next_sym)' 'cf.body'
build_operand_mutant unspilled-loop-operands

expect_operand_frame_failure() {
  local fixture="$1"
  local output="$never_mutant/$(basename "$fixture").out"
  if java -Xss512m -jar "$never_mutant/compiler.jar" __emit \
      --std "$root/std" "$fixture" -o "$never_mutant/emit" > "$output" 2>&1; then
    never_die "LOOP_OPERAND_STACK: the unspilled emitter accepted $fixture"
  fi
  if ! grep -q 'java.lang.ArrayIndexOutOfBoundsException' "$output" || \
      ! grep -q 'org.objectweb.asm.Frame.merge' "$output"; then
    cat "$output" >&2
    never_die "LOOP_OPERAND_STACK: $fixture failed for a different reason"
  fi
}
expect_operand_frame_failure "$loop_operand_fixture"

# The Java path is a separate obligation: keep Core preparation enabled so
# the pure-call snapshot test cannot be what turns this mutant red.
new_never_mutant unspilled-java-operands
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  'if operands.foreign_jumps(jc) {' 'if false {'
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  'let spill = operands.foreign_jumps(jc)' 'let spill = false'
build_operand_mutant unspilled-java-operands
expect_operand_frame_failure "$loop_operand_java_fixture"
echo "OK: LOOP_OPERAND_STACK mutant reproduces the original ASM frame failure"

# NEW is an observable class-initialization boundary, not only a stack value.
# Keep the uninitialized receiver in a local across real continue/break paths,
# and ask both the verifier and an independent Java initializer about it.
javac --release 21 -d "$work/operand-probe" scripts/classfile-verify/InitOrder.java
jar cf "$work/operand-probe.jar" -C "$work/operand-probe" .
init_fixture=scripts/classfile-verify/constructor_init.dawn
java -Xss512m "${add_exports[@]}" -cp "$root/build/dawn-selfhost.jar:$work/operand-probe.jar" main \
  __emit --std "$root/std" "$init_fixture" -o "$work/init-classes" > /dev/null
java "${add_exports[@]}" -cp "$work:$root/build/dawn-selfhost.jar:$work/operand-probe.jar" \
  Verify "$work/init-classes"
./bin/dawn run --cp "$work/operand-probe.jar" "$init_fixture" -- control > "$work/init-control.out"
diff -u scripts/classfile-verify/constructor_init_control.expect "$work/init-control.out"
./bin/dawn run --cp "$work/operand-probe.jar" "$init_fixture" > "$work/init-jumps.out"
diff -u scripts/classfile-verify/constructor_init.expect "$work/init-jumps.out"

new_never_mutant late-java-constructor-init
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  'g.mv.visitTypeInsn(OP_NEW, owner)
    let (g0, receiver) = spill_java_value(g, "Ljava/lang/Object;")' \
  'g.mv.visitInsn(OP_ACONST_NULL)
    let (g0, receiver) = spill_java_value(g, "Ljava/lang/Object;")'
replace_never_once "$never_mutant/selfhost/src/jvm/emit.dawn" \
  'reload_java_values(g1, [receiver])' 'g1.mv.visitTypeInsn(OP_NEW, owner)'
build_operand_mutant late-java-constructor-init
java -Xss512m -jar "$never_mutant/compiler.jar" run --cp "$work/operand-probe.jar" \
  "$init_fixture" > "$work/init-mutant.out"
if diff -q scripts/classfile-verify/constructor_init.expect "$work/init-mutant.out" > /dev/null; then
  never_die "JAVA_NEW_ORDER: the delayed NEW mutant preserved initialization order"
fi
if [ "$(head -n 1 "$work/init-mutant.out")" != 'argument -1' ]; then
  cat "$work/init-mutant.out" >&2
  never_die "JAVA_NEW_ORDER: the mutant failed for a different reason"
fi
echo "OK: JAVA_NEW_ORDER preserves initialization before escaping argument effects"

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
if java "${add_exports[@]}" -cp "$work:$root/build/dawn-selfhost.jar" Verify "$mut" \
    > /dev/null 2>&1; then
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
