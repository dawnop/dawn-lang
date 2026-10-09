#!/usr/bin/env bash
# Contract test for the `I64Buf` primitives (docs/mem-buffer-design.md 5, 6).
#
#   ./scripts/mem-contract/run.sh
#
# There is no `--record`. `expected.txt` is the answer the design gives, written
# down before either backend was asked; recording it from a run would make it a
# report of what the compiler does rather than a check on it. Change what the
# probe prints and hand-edit the file to match.
#
# Unlike `Array`, a buffer is a type user code may name, so probe.dawn is an
# ordinary program over std/mem and needs no copy of std. It is held to
# expected.txt three ways:
#
#   * the JVM backend, where the buffer is a `long[]` and the access methods
#     are static methods of dawn/rt/Mem;
#   * the native backend, where it is a counted C object, compiled at -O2;
#   * the native backend again under AddressSanitizer, LeakSanitizer and
#     UndefinedBehaviorSanitizer, which is what notices a copy that runs one
#     element past a buffer or a buffer nothing frees.
#
# All three have to print the same bytes, panic wording included: a panic
# message is a value once `catch_panic` hands it back, so the backends may not
# disagree on it. The index lines include 2^32 + 5, which a check made after
# truncating to 32 bits would read as slot 5.
#
# A fourth check is not about output. The native `at`/`set`/`len` are
# `static inline` so that a loop over a buffer costs a compare and a load and
# not a call per access (1.7x a JVM bcrypt out of line, 1.0x inlined; design
# 6.1), and a call that went back out of line would still print the right
# lines. So the probe's assembly must not mention them at all: an inlined
# function leaves no symbol behind.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/mem-contract"

"$root/bin/dawn" --version > /dev/null
jar="$root/build/dawn-selfhost.jar"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# ---- JVM -------------------------------------------------------------------
java -Xss512m -jar "$jar" run "$here/probe.dawn" > "$work/jvm_out.txt"
if ! diff -u "$here/expected.txt" "$work/jvm_out.txt"; then
  echo "FAIL: the JVM run of the I64Buf probe disagrees with expected.txt" >&2
  exit 1
fi
echo "PASS  JVM values, panics and workloads"

# ---- native ----------------------------------------------------------------
cc_bin="${CC:-cc}"
java -Xss512m -jar "$jar" __emitc "$here/probe.dawn" -o "$work/probe.c"
cflags=(-std=c11 -fwrapv -fexceptions -fno-strict-aliasing -pthread
  -Wall -Wextra -Werror
  -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-unused-parameter -Wno-unused-label -Wno-parentheses-equality
  -I "$root/runtime/c")

"$cc_bin" "${cflags[@]}" -O2 -o "$work/probe_native" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm
if ! timeout 60 "$work/probe_native" > "$work/native_out.txt"; then
  echo "FAIL: the native I64Buf probe failed or took over 60s" >&2
  exit 1
fi
if ! diff -u "$here/expected.txt" "$work/native_out.txt"; then
  echo "FAIL: the native build of the I64Buf probe disagrees with expected.txt" >&2
  exit 1
fi
echo "PASS  native values, panics and workloads"

# ---- native under the sanitizers -------------------------------------------
# fail closed on a compiler that cannot sanitize: a leg that silently built
# without them would be green about nothing
printf 'int main(void) { return 0; }\n' > "$work/san_probe.c"
if ! "$cc_bin" -fsanitize=address,undefined -o "$work/san_probe" "$work/san_probe.c" \
  > "$work/san_probe.err" 2>&1 || ! "$work/san_probe"; then
  cat "$work/san_probe.err" >&2
  echo "FAIL: $cc_bin cannot build and run with -fsanitize=address,undefined" >&2
  exit 1
fi
"$cc_bin" "${cflags[@]}" -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined \
  -o "$work/probe_asan" "$work/probe.c" "$root/runtime/c/dawn_rt.c" -lm
if ! ASAN_OPTIONS=detect_leaks=1 timeout 120 "$work/probe_asan" \
    > "$work/asan_out.txt" 2> "$work/asan_err.txt"; then
  cat "$work/asan_err.txt" >&2
  echo "FAIL: the sanitized native I64Buf probe reported an error" >&2
  exit 1
fi
if ! diff -u "$here/expected.txt" "$work/asan_out.txt"; then
  echo "FAIL: the sanitized native I64Buf probe disagrees with expected.txt" >&2
  exit 1
fi
echo "PASS  native under ASan, LeakSanitizer and UBSan"

# ---- the hot path stays inline ----------------------------------------------
"$cc_bin" "${cflags[@]}" -O2 -S -o "$work/probe.s" "$work/probe.c"
refs="$(grep -c 'dawn_i64buf_\(at\|set\|len\)' "$work/probe.s" || true)"
if [ "$refs" != "0" ]; then
  grep 'dawn_i64buf_\(at\|set\|len\)' "$work/probe.s" | head -5 >&2
  echo "FAIL: dawn_i64buf_at/set/len left a symbol behind in the probe's assembly ($refs lines)." >&2
  echo "      They are static inline in dawn_rt.h so a buffer loop pays no call per access;" >&2
  echo "      out of line they cost 1.7x on bcrypt (docs/mem-buffer-design.md 6.1)." >&2
  exit 1
fi
echo "PASS  at, set and len compile inline"
