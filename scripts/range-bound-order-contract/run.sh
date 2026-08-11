#!/usr/bin/env bash
# Hold range bound order in shared Core and against one absolute runtime oracle.
# Every compiler runs the same assertions before its red set is classified.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/range-bound-order-contract"
probe="$root/scripts/spike-native/eval_order.dawn"
expect="$root/scripts/spike-native/eval_order.expect"
dawn=${DAWN_BIN:-"$root/bin/dawn"}
cc_bin=${CC:-cc}
work=$(mktemp -d "${TMPDIR:-/tmp}/range-bound-order-contract.XXXXXX")
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

mutation=restore-upper-first
owner_assertion=range_bound_order_is_lower_first
control_assertion=range_bounds_are_once_before_loop
python3 "$here/matrix_check.py" --self-test
python3 "$here/matrix_check.py" "$here/matrix.txt"
python3 "$here/core_check.py" --self-test

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

compile_c() { # compiler output-c output-bin
  local compiler=$1 c_out=$2 bin_out=$3
  "$compiler" __emitc --std "$root/std" "$probe" -o "$c_out" > "$c_out.emit" 2>&1 &&
    "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
      -Wall -Wextra -Werror -Wno-unused-variable -Wno-unused-but-set-variable \
      -Wno-unused-parameter -Wno-unused-label -I "$root/runtime/c" \
      -o "$bin_out" "$c_out" "$root/runtime/c/dawn_rt.c" -lm \
      > "$c_out.cc" 2>&1
}

assess() { # compiler tag
  local compiler=$1 tag=$2 dir core order_ok control_ok jvm_rc native_rc
  dir="$work/assess-$tag"
  mkdir -p "$dir/core"
  order_ok=1
  control_ok=1

  if "$compiler" __lower --std "$root/std" --dump "$dir/core" "$probe" \
      > "$dir/lower.out" 2> "$dir/lower.err"; then
    core="$dir/core/eval_order.core"
    [ -f "$core" ] || { order_ok=0; control_ok=0; }
    if [ -f "$core" ]; then
      python3 "$here/core_check.py" order "$core" \
        > "$dir/core-order.out" 2> "$dir/core-order.err" || order_ok=0
      python3 "$here/core_check.py" control "$core" \
        > "$dir/core-control.out" 2> "$dir/core-control.err" || control_ok=0
    fi
  else
    order_ok=0
    control_ok=0
  fi

  jvm_rc=0
  "$compiler" run --std "$root/std" "$probe" \
    > "$dir/jvm.out" 2> "$dir/jvm.err" || jvm_rc=$?
  [ "$jvm_rc" -eq 0 ] || order_ok=0
  cmp -s "$expect" "$dir/jvm.out" || order_ok=0

  if compile_c "$compiler" "$dir/probe.c" "$dir/probe.bin"; then
    native_rc=0
    "$dir/probe.bin" > "$dir/native.out" 2> "$dir/native.err" || native_rc=$?
    [ "$native_rc" -eq 0 ] || order_ok=0
    cmp -s "$expect" "$dir/native.out" || order_ok=0
    cmp -s "$dir/jvm.out" "$dir/native.out" || order_ok=0
    cmp -s "$dir/jvm.err" "$dir/native.err" || order_ok=0
    [ "$jvm_rc" -eq "$native_rc" ] || order_ok=0
  else
    order_ok=0
  fi

  if [ "$order_ok" -eq 1 ]; then
    echo "$owner_assertion PASS"
  else
    echo "$owner_assertion FAIL"
  fi
  if [ "$control_ok" -eq 1 ]; then
    echo "$control_assertion PASS"
  else
    echo "$control_assertion FAIL"
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
[ "$control" = "$control_assertion" ] || fail "the control changed"
if grep -Fq $'\t'"$control" "$observed"; then
  fail "the counted mutant reddened the static control"
fi

echo "PASS  $mutation builds, answers --version, and turns only $owner red"
echo "range bound order contract ok"
