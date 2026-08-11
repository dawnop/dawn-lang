#!/usr/bin/env bash
# Keep source-loop jump targets through the native-only RC pass, while retaining
# the match once-loop optimization. Every compiler runs the same assertion set.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/source-loop-label-contract"
probe="$root/scripts/spike-native/source_loop_targets.dawn"
expect="$root/scripts/spike-native/source_loop_targets.expect"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
cc_bin=${CC:-cc}
work=$(mktemp -d "${TMPDIR:-/tmp}/source-loop-label-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mutation=drop-terminal-loop-jump-guard
owner_assertion=source_loop_target_is_retained
control_assertion=match_unloop_is_retained
python3 "$here/matrix_check.py" --self-test
python3 "$here/matrix_check.py" "$here/matrix.txt"

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

cat > "$work/continue_only.dawn" <<'EOF'
# This function is compiled but never called: executing it would not terminate.
pub fn spin() -> Unit = {
  while true {
    continue
  }
}

pub fn main() -> Unit = ()
EOF

cat > "$work/match_unloop.dawn" <<'EOF'
fn classify(n: Int) -> Int = match n {
  0 -> 10
  _ -> 20
}

pub fn main() -> Unit = {
  let _a = classify(0)
  let _b = classify(1)
  ()
}
EOF

compile_c() { # compiler source output-c output-bin
  local compiler=$1 source=$2 c_out=$3 bin_out=$4
  "$compiler" __emitc --std "$root/std" "$source" -o "$c_out" > "$c_out.emit" 2>&1 &&
    "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
      -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
      -Wno-unused-parameter -Wno-unused-label -I "$root/runtime/c" \
      -o "$bin_out" "$c_out" "$root/runtime/c/dawn_rt.c" -lm \
      > "$c_out.cc" 2>&1
}

assess() { # compiler tag
  local compiler=$1 tag=$2 dir ok core
  dir="$work/assess-$tag"
  mkdir -p "$dir"

  ok=1
  "$compiler" run --std "$root/std" "$probe" > "$dir/jvm.out" 2> "$dir/jvm.err" || ok=0
  cmp -s "$expect" "$dir/jvm.out" || ok=0
  if compile_c "$compiler" "$probe" "$dir/probe.c" "$dir/probe.bin"; then
    "$dir/probe.bin" > "$dir/native.out" 2> "$dir/native.err" || ok=0
    cmp -s "$expect" "$dir/native.out" || ok=0
    cmp -s "$dir/jvm.err" "$dir/native.err" || ok=0
  else
    ok=0
  fi
  compile_c "$compiler" "$work/continue_only.dawn" \
    "$dir/continue.c" "$dir/continue.bin" || ok=0
  if [ "$ok" -eq 1 ]; then
    echo "source_loop_target_is_retained PASS"
  else
    echo "source_loop_target_is_retained FAIL"
  fi

  ok=1
  mkdir -p "$dir/core"
  "$compiler" __lower --std "$root/std" --dump "$dir/core" \
    "$work/match_unloop.dawn" > "$dir/lower.out" 2> "$dir/lower.err" || ok=0
  core="$dir/core/match_unloop.core"
  [ -f "$core" ] || ok=0
  if [ -f "$core" ]; then
    grep -q 'sif' "$core" || ok=0
    if grep -q 'loop L' "$core"; then ok=0; fi
  fi
  if compile_c "$compiler" "$work/match_unloop.dawn" \
    "$dir/match.c" "$dir/match.bin"; then
    "$dir/match.bin" > "$dir/match.out" 2> "$dir/match.err" || ok=0
  else
    ok=0
  fi
  if [ "$ok" -eq 1 ]; then
    echo "match_unloop_is_retained PASS"
  else
    echo "match_unloop_is_retained FAIL"
  fi
}

reds_of() { # compiler mutation
  local name state
  assess "$1" "$2" | while read -r name state; do
    if [ "$state" = FAIL ]; then printf 'red\t%s\t%s\n' "$2" "$name"; fi
  done
}

"$dawn" --version > /dev/null
baseline=$(assess "$dawn" baseline)
printf '%s\n' "$baseline" | while read -r name state; do
  [ "$state" = PASS ] || fail "$name: the real compiler does not satisfy the contract"
done
printf '%s\n' "$baseline" | sed 's/ PASS$//;s/^/OK   /'

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

observed="$work/observed.txt"
reds_of "$mutant/dawn" "$mutation" > "$observed"
expected="$work/expected.txt"
awk -F '\t' '$1 == "red" { print }' "$here/matrix.txt" > "$expected"
if ! diff -u "$expected" "$observed"; then
  fail "$mutation red set differs from matrix.txt"
fi
owner=$(awk -F '\t' '$1 == "owner" { print $3 }' "$here/matrix.txt")
[ "$owner" = "$owner_assertion" ] || fail "the mutant owner changed"
needle=$'red\t'"$mutation"$'\t'"$owner"
[ "$(grep -Fxc "$needle" "$observed")" -eq 1 ] ||
  fail "the owning assertion is not uniquely red"
control=$(awk -F '\t' '$1 == "control" { print $2 }' "$here/matrix.txt")
[ "$control" = "$control_assertion" ] || fail "the match-unloop control changed"
if grep -Fq $'\t'"$control" "$observed"; then
  fail "the counted mutant reddened the match-unloop control"
fi

echo "PASS  $mutation builds, answers --version, and turns only $owner red"
echo "source loop label contract ok"
