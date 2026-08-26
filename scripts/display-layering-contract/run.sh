#!/usr/bin/env bash
# Hold the two Display layering rules with a mutant apiece, and prove each one
# reddens the rule it is about and nothing else.
#
#   ./scripts/display-layering-contract/run.sh
#
# Two tracked files and no `--record` for either. `probe.expect` is the labelled
# answer the rules require; `matrix.txt` is the declaration of which mutant
# reddens which label, which run.sh then checks against what actually happened.
# Both are edited by hand: a recording of either would be the harness agreeing
# with itself.
#
# The rules, both in `to_str` (selfhost/src/ir/lower.dawn):
#   - a `Display` impl decides the top-level rendering, in place of the `Show`
#     the value would otherwise render through;
#   - the question is asked at every peel layer of an opaque stack rather than
#     once on the type as written.
#
# Why a mutant harness and not just an expectation: `probe.expect` being green
# says the compiler agrees with it today, not that anything would notice if the
# rules were dropped. Both mutants below compile, run, and print an answer -- a
# plausible wrong one -- which is the shape of defect an expectation alone
# cannot distinguish from an absent check.
#
# JVM only, deliberately. Both rules live in shared Core, so the two backends
# would agree on a broken answer and comparing them proves nothing here; the
# two-backend claim is scripts/spike-native/display_layers.dawn, which says the
# same things without labels. What this harness buys instead is the assertion
# partition: a labelled probe so two mutants can be told apart by which rule
# they broke.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/display-layering-contract"
probe="$here/probe.dawn"
expect="$here/probe.expect"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
work=$(mktemp -d "${TMPDIR:-/tmp}/display-layering-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

control=show_stays_the_nested_rendering

python3 "$here/matrix_check.py" --self-test
python3 "$here/matrix_check.py" "$here/matrix.txt"
python3 "$here/probe_check.py" --self-test

mapfile -t assertions < <(python3 "$here/probe_check.py" --labels)
[ "${#assertions[@]}" -eq 3 ] || fail "expected three assertions, got ${#assertions[@]}"

mapfile -t mutations < <(awk -F '\t' '$1 == "role" { print $2 }' "$here/matrix.txt")
[ "${#mutations[@]}" -eq 2 ] || fail "expected two mutations, got ${#mutations[@]}"

version_answers() { # output-file
  local output=$1 lines
  lines=$(wc -l < "$output" | tr -d ' ')
  [ "$lines" -eq 1 ] && grep -Eq '^dawn [^[:space:]].*$' "$output"
}
printf 'dawn self-test\n' > "$work/version-good"
: > "$work/version-empty"
printf 'compiler self-test\n' > "$work/version-wrong"
version_answers "$work/version-good" || fail "version output shape rejects dawn output"
if version_answers "$work/version-empty"; then
  fail "version output shape accepts empty output"
fi
if version_answers "$work/version-wrong"; then
  fail "version output shape accepts an unrelated line"
fi

# Run the probe with one compiler and print `<assertion> PASS|FAIL` per line.
# A compiler that cannot run the probe at all fails every assertion, which is
# what makes "the mutant broke the build" impossible to read as evidence: the
# caller checks the red set against the matrix, and all-red matches neither row.
assess() { # compiler tag
  local compiler=$1 tag=$2 dir rc a
  dir="$work/assess-$tag"
  mkdir -p "$dir"
  rc=0
  "$compiler" run --std "$root/std" "$probe" > "$dir/out" 2> "$dir/err" || rc=$?
  for a in "${assertions[@]}"; do
    if [ "$rc" -ne 0 ]; then
      echo "$a FAIL"
    elif python3 "$here/probe_check.py" "$a" "$expect" "$dir/out" \
        > "$dir/$a.out" 2> "$dir/$a.err"; then
      echo "$a PASS"
    else
      echo "$a FAIL"
    fi
  done
}

"$dawn" --version > /dev/null
baseline=$(assess "$dawn" baseline)
printf '%s\n' "$baseline" | while read -r name state; do
  [ "$state" = PASS ] || fail "$name: the real compiler does not satisfy the contract"
done
printf '%s\n' "$baseline" | sed 's/ PASS$//;s/^/OK   /'

observed="$work/observed.txt"
: > "$observed"
for mutation in "${mutations[@]}"; do
  mutant="$work/$mutation"
  mkdir -p "$mutant"
  cp -R "$root/selfhost" "$mutant/selfhost"
  ln -s "$root/packages" "$mutant/packages"
  ln -s "$root/compiler-plan" "$mutant/compiler-plan"
  python3 "$here/mutate.py" "$mutation" "$mutant"

  if ! "$dawn" build "$mutant/selfhost" -o "$mutant/compiler.jar" \
      > "$mutant/build.out" 2>&1; then
    cat "$mutant/build.out" >&2
    fail "$mutation mutant did not compile"
  fi
  if ! java -Xss512m -Xmx2g -jar "$mutant/compiler.jar" --version \
      > "$mutant/version.out" 2>&1; then
    cat "$mutant/version.out" >&2
    fail "$mutation mutant compiled but --version exited nonzero"
  fi
  if ! version_answers "$mutant/version.out"; then
    cat "$mutant/version.out" >&2
    fail "$mutation mutant --version did not print one dawn version line"
  fi
  cat > "$mutant/dawn" <<EOF
#!/bin/sh
exec java -Xss512m -Xmx2g -jar "$mutant/compiler.jar" "\$@"
EOF
  chmod +x "$mutant/dawn"

  assess "$mutant/dawn" "$mutation" | while read -r name state; do
    if [ "$state" = FAIL ]; then printf 'red\t%s\t%s\n' "$mutation" "$name"; fi
  done >> "$observed"

  owner=$(awk -F '\t' -v m="$mutation" '$1 == "owner" && $2 == m { print $3 }' \
    "$here/matrix.txt")
  [ -n "$owner" ] || fail "$mutation has no owner row in matrix.txt"
  needle=$'red\t'"$mutation"$'\t'"$owner"
  [ "$(grep -Fxc "$needle" "$observed")" -eq 1 ] ||
    fail "$mutation did not redden the assertion it owns ($owner)"
  if grep -Fq $'red\t'"$mutation"$'\t'"$control" "$observed"; then
    fail "$mutation reddened the static control ($control)"
  fi
  echo "PASS  $mutation builds, answers --version, and turns $owner red"
done

expected="$work/expected.txt"
awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" | LC_ALL=C sort > "$expected"
LC_ALL=C sort "$observed" > "$work/observed-sorted.txt"
if ! diff -u "$expected" "$work/observed-sorted.txt"; then
  fail "the observed red set differs from matrix.txt"
fi

echo "display layering contract ok"
