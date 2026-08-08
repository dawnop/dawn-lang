#!/usr/bin/env bash
# The native bootstrap gate (docs/native-backend-plan.md Phase 6 exit):
#
#   A = the JVM toolchain emits C for the native driver (nmain), cc builds it
#   B = A compiles the native driver itself; its C must equal A's byte for byte
#   C = B compiles the native driver again; B == C is the fixed point
#
# One full pass costs a few minutes (the native compiler chews the whole
# compiler twice), so this is a milestone gate, not an every-push gate --
# run it whenever emitc/rc/lower or the runtime change shape.
#
#   ./scripts/native-fixpoint.sh
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)

cc_bin="${CC:-cc}"
ccflags=(-std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -I "$root/runtime/c")

if command -v sha256sum >/dev/null 2>&1; then
  digest_file() { sha256sum "$1" | cut -d' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
  digest_file() { shasum -a 256 "$1" | cut -d' ' -f1; }
else
  echo "FAIL: cannot guard native fixpoint inputs without a SHA-256 tool" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# generation A: the JVM toolchain emits the native driver
"$root/bin/dawn" --version > /dev/null   # rebuild build/dawn-selfhost.jar if stale
expected_source_stamp="$(DAWN_PRINT_STAMP=1 "$root/bin/dawn")"
if [ -z "$expected_source_stamp" ] || [ "$expected_source_stamp" = "no-sha256" ]; then
  echo "FAIL: cannot guard native fixpoint inputs without a content stamp" >&2
  exit 1
fi
if [ ! -f "$root/build/dawn-selfhost.stamp" ]; then
  echo "FAIL: inputs changed/stale baseline before generation A" >&2
  echo "  build stamp: missing" >&2
  echo "  source stamp: $expected_source_stamp" >&2
  exit 1
fi
built_source_stamp="$(cat "$root/build/dawn-selfhost.stamp")"
if [ "$built_source_stamp" != "$expected_source_stamp" ]; then
  echo "FAIL: inputs changed/stale baseline before generation A" >&2
  echo "  build stamp:  $built_source_stamp" >&2
  echo "  source stamp: $expected_source_stamp" >&2
  exit 1
fi
expected_runtime_stamp="$(digest_file "$root/runtime/c/dawn_rt.c")"
expected_input_stamp="$expected_source_stamp:$expected_runtime_stamp"

gate_input_stamp() {
  local source_stamp
  local runtime_stamp
  source_stamp="$(DAWN_PRINT_STAMP=1 "$root/bin/dawn")" || return 1
  runtime_stamp="$(digest_file "$root/runtime/c/dawn_rt.c")" || return 1
  printf '%s:%s\n' "$source_stamp" "$runtime_stamp"
}

assert_inputs_unchanged() {
  local stage="$1"
  local actual_input_stamp
  if ! actual_input_stamp="$(gate_input_stamp)"; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  expected stamp: $expected_input_stamp" >&2
    echo "  actual stamp:   unavailable" >&2
    exit 1
  fi
  if [ "$actual_input_stamp" != "$expected_input_stamp" ]; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  expected stamp: $expected_input_stamp" >&2
    echo "  actual stamp:   $actual_input_stamp" >&2
    exit 1
  fi
}

java -Xss512m -jar "$root/build/dawn-selfhost.jar" __emitc \
  "$root/selfhost/src/nmain.dawn" -o "$work/A.c"
assert_inputs_unchanged "after generation A"
"$cc_bin" "${ccflags[@]}" -o "$work/dawnc-A" "$work/A.c" "$root/runtime/c/dawn_rt.c" -lm

# generation B: A compiles the driver itself; the C must match A's exactly
assert_inputs_unchanged "before generation B"
"$work/dawnc-A" emitc "$root/selfhost/src/nmain.dawn" -o "$work/B.c"
assert_inputs_unchanged "after generation B"
if ! cmp -s "$work/A.c" "$work/B.c"; then
  echo "FAIL: the native compiler emits different C than the JVM toolchain (A != B)" >&2
  diff "$work/A.c" "$work/B.c" | head -40 >&2
  exit 1
fi
"$cc_bin" "${ccflags[@]}" -o "$work/dawnc-B" "$work/B.c" "$root/runtime/c/dawn_rt.c" -lm

# generation C: B compiles the driver; B == C is the fixed point
"$work/dawnc-B" emitc "$root/selfhost/src/nmain.dawn" -o "$work/C.c"
assert_inputs_unchanged "after generation C"
if ! cmp -s "$work/B.c" "$work/C.c"; then
  echo "FAIL: no fixed point (B != C)" >&2
  diff "$work/B.c" "$work/C.c" | head -40 >&2
  exit 1
fi

# smoke: the fixed-point compiler builds and runs a program from a bare
# directory -- embedded std and embedded runtime, no repo files
smoke="$work/smoke"
mkdir -p "$smoke"
cat > "$smoke/hello.dawn" <<'EOF'
use std/str

pub fn main() -> Unit !io = {
  println(join(map(sort([3, 1, 2]), x => "${x}"), ","))
  println(str.to_upper("fixpoint"))
}
EOF
(cd "$smoke" && "$work/dawnc-B" run hello.dawn) > "$work/smoke.out"
printf '1,2,3\nFIXPOINT\n' > "$work/smoke.expect"
if ! cmp -s "$work/smoke.expect" "$work/smoke.out"; then
  echo "FAIL: fixed-point compiler ran the smoke program wrong" >&2
  diff "$work/smoke.expect" "$work/smoke.out" >&2
  exit 1
fi

echo "OK: native fixed point -- the native compiler rebuilt itself byte-identically (B == C)"
echo "OK: standalone smoke -- built and ran hello with embedded std + runtime"
