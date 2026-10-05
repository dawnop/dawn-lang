#!/usr/bin/env bash
# The native bootstrap gate (docs/native-backend-plan.md Phase 6 exit):
#
#   A = the JVM toolchain emits C for the native driver (nmain), cc builds it
#   B = A compiles the native driver itself; its C must equal A's byte for byte
#   C = B compiles the native driver again; B == C is the fixed point
#
# Each generation also writes the build manifest unit (`--build-info`,
# docs/build-info-design.md §八) and links it in. The unit is a function of the
# sources, so it is held to the same A == B == C as the C; that is also the one
# place where the JVM and the native builds of buildinfo/sha2 are compared
# over a whole tree.
#
# One full pass costs a few minutes (the native compiler chews the whole
# compiler twice), so this is a milestone gate, not an every-push gate --
# run it whenever emitc/rc/lower or the runtime change shape.
#
#   ./scripts/native-fixpoint.sh
set -euo pipefail
cd "$(dirname "$0")/.."
root=$(pwd)

# Each generation's C is also written as translation units (`--split`), and
# the units compile in parallel (scripts/cc-units.sh; docs/c-tu-split-design.md).
# The whole text is still what A == B == C compares; the units are compared
# too, because generation B cuts them with the native build of the same
# `cdriver.split` the JVM ran for A.

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

runtime_input_stamp() {
  local paths="$work/runtime-inputs.paths"
  local manifest="$work/runtime-inputs.manifest"
  local path
  local relative_path
  local file_stamp

  if ! find "$root/runtime/c" -type f \( -name '*.c' -o -name '*.h' \) -print \
      | LC_ALL=C sort > "$paths"; then
    return 1
  fi
  if [ ! -s "$paths" ]; then
    return 1
  fi

  : > "$manifest"
  while IFS= read -r path; do
    relative_path="${path#"$root"/}"
    if ! file_stamp="$(digest_file "$path")"; then
      return 1
    fi
    printf '%s\0%s\n' "$relative_path" "$file_stamp" >> "$manifest"
  done < "$paths"
  digest_file "$manifest"
}

# The launcher's generation marker is the strict five-line v2 stamp; anything
# else (a legacy single digest, an error string, a truncated file) means the
# inputs are not guarded and the gate must not start.
stamp_is_v2() {
  local stamp="$1"
  [ "$(printf '%s\n' "$stamp" | wc -l | tr -d '[:space:]')" -eq 5 ] || return 1
  printf '%s\n' "$stamp" | sed -n '1p' | grep -x 'dawn-selfhost-stamp-v2' >/dev/null || return 1
  printf '%s\n' "$stamp" | sed -n '2p' | grep -xE 'source=[0-9a-f]{64}' >/dev/null || return 1
  printf '%s\n' "$stamp" | sed -n '3p' | grep -xE 'bootstrap=[0-9a-f]{64}' >/dev/null || return 1
  printf '%s\n' "$stamp" | sed -n '4p' | grep -xE 'inputs=[0-9a-f]{64}' >/dev/null || return 1
  printf '%s\n' "$stamp" | sed -n '5p' | grep -xE 'jar=[0-9a-f]{64}' >/dev/null || return 1
}

# generation A: the JVM toolchain emits the native driver
"$root/bin/dawn" --version > /dev/null   # rebuild build/dawn-selfhost.jar if stale
expected_source_stamp="$(DAWN_PRINT_STAMP=1 "$root/bin/dawn")"
if ! stamp_is_v2 "$expected_source_stamp"; then
  echo "FAIL: cannot guard native fixpoint inputs without a strict v2 generation stamp" >&2
  echo "  printed stamp: $expected_source_stamp" >&2
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
if ! expected_runtime_stamp="$(runtime_input_stamp)"; then
  echo "FAIL: cannot snapshot native runtime inputs before generation A" >&2
  exit 1
fi

assert_inputs_unchanged() {
  local stage="$1"
  local actual_source_stamp
  local actual_runtime_stamp
  if ! actual_source_stamp="$(DAWN_PRINT_STAMP=1 "$root/bin/dawn")"; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  source stamp: unavailable" >&2
    exit 1
  fi
  if ! actual_runtime_stamp="$(runtime_input_stamp)"; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  runtime/c stamp: unavailable" >&2
    exit 1
  fi
  if [ "$actual_source_stamp" != "$expected_source_stamp" ]; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  expected source stamp: $expected_source_stamp" >&2
    echo "  actual source stamp:   $actual_source_stamp" >&2
    exit 1
  fi
  if [ "$actual_runtime_stamp" != "$expected_runtime_stamp" ]; then
    echo "FAIL: inputs changed during gate ($stage)" >&2
    echo "  expected runtime/c stamp: $expected_runtime_stamp" >&2
    echo "  actual runtime/c stamp:   $actual_runtime_stamp" >&2
    exit 1
  fi
}

java -Xss512m -jar "$root/build/dawn-selfhost.jar" __emitc \
  "$root/selfhost/src/nmain.dawn" -o "$work/A.c" --build-info "$work/A.info.c" \
  --split "$work/A.units"
assert_inputs_unchanged "after generation A"
"$root/scripts/cc-units.sh" -o "$work/dawnc-A" "$work/A.units" "$work/A.info.c"

# generation B: A compiles the driver itself; the C must match A's exactly
assert_inputs_unchanged "before generation B"
"$work/dawnc-A" emitc "$root/selfhost/src/nmain.dawn" -o "$work/B.c" \
  --build-info "$work/B.info.c" --split "$work/B.units"
assert_inputs_unchanged "after generation B"
if ! cmp -s "$work/A.c" "$work/B.c"; then
  echo "FAIL: the native compiler emits different C than the JVM toolchain (A != B)" >&2
  diff "$work/A.c" "$work/B.c" | sed -n '1,40p' >&2
  exit 1
fi
if ! cmp -s "$work/A.info.c" "$work/B.info.c"; then
  echo "FAIL: the native compiler writes a different build manifest than the JVM toolchain (A != B)" >&2
  diff "$work/A.info.c" "$work/B.info.c" | sed -n '1,40p' >&2
  exit 1
fi
if ! diff -r "$work/A.units" "$work/B.units" > "$work/units.diff"; then
  echo "FAIL: the native compiler cuts its C into different units than the JVM toolchain (A != B)" >&2
  sed -n '1,40p' "$work/units.diff" >&2
  exit 1
fi
"$root/scripts/cc-units.sh" -o "$work/dawnc-B" "$work/B.units" "$work/B.info.c"

# generation C: B compiles the driver; B == C is the fixed point
"$work/dawnc-B" emitc "$root/selfhost/src/nmain.dawn" -o "$work/C.c" \
  --build-info "$work/C.info.c"
assert_inputs_unchanged "after generation C"
if ! cmp -s "$work/B.c" "$work/C.c"; then
  echo "FAIL: no fixed point (B != C)" >&2
  diff "$work/B.c" "$work/C.c" | sed -n '1,40p' >&2
  exit 1
fi
if ! cmp -s "$work/B.info.c" "$work/C.info.c"; then
  echo "FAIL: no fixed point for the build manifest (B != C)" >&2
  diff "$work/B.info.c" "$work/C.info.c" | sed -n '1,40p' >&2
  exit 1
fi

# the fixed-point compiler reads the manifest it was linked with, and the JVM
# reader finds the same one in the file without running it
self_line="$("$work/dawnc-B" --version)"
listed="$(java -Xss512m -jar "$root/build/dawn-selfhost.jar" version -m "$work/dawnc-B" \
  | sed -n 's/^\tbuild\tb1:\([0-9a-f]\{12\}\).*$/\1/p')"
if [ -z "$listed" ] || [ "$self_line" != "${self_line% b1:*} b1:$listed" ]; then
  echo "FAIL: dawnc-B says '$self_line', its manifest lists b1:${listed:-<none>}" >&2
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
echo "OK: build manifest -- A == B == C, and dawnc-B reports b1:$listed"
echo "OK: standalone smoke -- built and ran hello with embedded std + runtime"
