#!/usr/bin/env bash
# Can this gate go red? (#129)
#
#   scripts/classfile-verify/selftest.sh CLASSPATH_DIR_HOLDING_Verify.class
#
# run.sh calls this before it looks at a single emitted class, because the two
# defects this gate has had were both "it reported a number that meant
# nothing". The first: parent-first delegation made the selfhost corpus resolve
# out of the toolchain jar, so the directory under test was never read and no
# emitted byte could fail. The second: Class.forName links classes and linking
# is not resolution, so the K-A3 IllegalAccessError sat inside a corpus the
# gate called clean. Neither was found by reading; both were found by a mutant.
#
# So the mutants ride with the gate. Four fixtures, each pinning one claim:
#
#   legal          green, and it must report a non-zero reference count --
#                  "found nothing" and "looked at nothing" print the same
#                  verdict otherwise;
#   mutant-private red on pass 2, and *green on pass 1* -- the assertion that
#                  the blind spot is real, not a story about it;
#   mutant-package red on pass 2 via the CONSTANT_Class path;
#   athrow         red on pass 1 -- the bytecode-verifier demo Verify.java's
#                  header requires be re-run whenever the gate changes.
#
# Cost is about a second against the several minutes the corpora take, so
# there is no version of this gate that runs without proving it can fail.
set -euo pipefail

vcp="${1:?usage: selftest.sh CLASSPATH_DIR}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fx="$here/fixtures"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

javac -d "$work/legal" "$fx/legal/pkgA/Target.java" "$fx/legal/pkgB/Caller.java"

for m in private package; do
  javac -d "$work/tgt-$m" "$fx/mutant-$m/pkgA/Target.java"
  mkdir -p "$work/mutant-$m"
  cp -r "$work/legal/." "$work/mutant-$m/"
  cp "$work/tgt-$m/pkgA/Target.class" "$work/mutant-$m/pkgA/Target.class"
done

mkdir -p "$work/athrow"
cp -r "$work/legal/." "$work/athrow/"
"$here/mutate.py" "$work/athrow/pkgB/Caller.class"

fail=0

# $1 fixture, $2 expected exit (0 green / 1 red), $3 pattern the output must hold
expect() {
  local name=$1 want=$2 pat=$3 got=0
  # the same option run.sh puts on the gate's own Verify runs, so the mutants
  # below prove the command shape the corpora are checked with, not a variant
  # of it. These fixtures name no jdk.internal class; the flag is inert here.
  java --add-exports java.base/jdk.internal.vm=ALL-UNNAMED -cp "$vcp" Verify \
    "$work/$name" > "$work/$name.out" 2> "$work/$name.err" || got=$?
  if [ "$got" != "$want" ]; then
    echo "SELFTEST FAIL $name: exit $got, expected $want" >&2
    cat "$work/$name.out" "$work/$name.err" >&2
    fail=1
    return
  fi
  if ! grep -qE "$pat" "$work/$name.out" "$work/$name.err"; then
    echo "SELFTEST FAIL $name: output does not match /$pat/" >&2
    cat "$work/$name.out" "$work/$name.err" >&2
    fail=1
    return
  fi
  echo "  selftest $name: $(tail -n 1 "$work/$name.out")"
}

expect legal 0 '[1-9][0-9]* references resolved'
expect mutant-private 1 'ACCESS FAIL pkgB\.Caller -> pkgA/Target\.f\(\)I'
expect mutant-package 1 'ACCESS FAIL pkgB\.Caller -> class pkgA/Target'
expect athrow 1 'VERIFY FAIL pkgB\.Caller'

# The blind spot itself, asserted rather than described: pass 1 saw the private
# mutant and called it legal. If this ever stops holding, the paragraph above
# about why pass 2 exists has gone stale and should be rewritten, not deleted.
if ! grep -q '0 illegal' "$work/mutant-private.out"; then
  echo "SELFTEST FAIL mutant-private: pass 1 was expected to miss it" >&2
  fail=1
fi

if [ "$fail" != 0 ]; then
  echo "FAIL: the gate cannot demonstrate it goes red" >&2
  exit 1
fi
echo "OK: selftest -- the gate reds on a private reference, an inaccessible class and bad bytecode"
