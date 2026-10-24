#!/usr/bin/env bash
# Contract test for dawn_ffi.h, the public header of the C extern surface
# (docs/ffi-extern-design.md), with its negative controls.
#
#   scripts/ffi-header-contract/run.sh
#
# Before there is a `extern` in the language, the header is held to what it
# promises by a C program that needs no Dawn syntax:
#
#   stub.c   written like a package's stub: includes dawn_ffi.h and nothing else
#            Dawn, defines `dawn_x_*` functions that read each kind of argument
#            and build each kind of answer
#   host.c   what emitted code does around such a call, written against
#            dawn_rt.h: borrowed arguments, owned answers dropped once, and the
#            shape of every value checked with the runtime's own view of it
#
# linked with the real runtime (dawn_rt.c) in three builds, and the transcript
# has to equal expected.txt (written by hand from the design, not recorded):
#
#   plain        -O1
#   inline       -O2 -DDAWN_RT_INLINE_RC, the other definition of dup and drop
#   sanitized    ASan with leak detection, and UBSan: a constructor that does not
#                copy, or a mask that hides a field from the drop, is a leak
#
# The panic is its own drive: `host --panic` must exit 1 and say the message,
# `host --panic-ok` must exit 0.
#
# Then the controls (mutate.py has the anchors, and mutation-anchor-preflight
# proves each exactly-once before any build). A contract that has only ever been
# green has not shown it can see:
#
#   abi-mismatch      the header's ABI number moves; the stub's compile must fail
#   cstr-truncates    a string with an embedded NUL is truncated, not refused
#   err-mask-short    the ForeignError hides two of its references from the drop
#   bytes-cut-at-nul  bytes copied from C stop at the first zero byte
#   fence-open        dawn_fault leaves the poison list; fault_stub.c, which fails
#                     to compile against the real header, must then compile
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
HERE=scripts/ffi-header-contract
CC_BIN=${CC:-cc}

OUT=$(mktemp -d "${TMPDIR:-/tmp}/ffi-header-contract.XXXXXX")
trap 'rm -rf "$OUT"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

CFLAGS=(-std=c11 -g -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread
  -Wall -Wextra -Werror -Wno-unused-parameter -Wno-unused-function)

# the sanitizers must exist, or the leg below is green about nothing
printf 'int main(void) { return 0; }\n' > "$OUT/san_probe.c"
if ! "$CC_BIN" -fsanitize=address,undefined -o "$OUT/san_probe" "$OUT/san_probe.c" \
  > "$OUT/san_probe.err" 2>&1 || ! "$OUT/san_probe"; then
  cat "$OUT/san_probe.err" >&2
  fail "$CC_BIN cannot build and run with -fsanitize=address,undefined"
fi

# build <variant> <runtime-dir> <out> [extra cc flags for stub.c's ABI request]
build() {
  local variant=$1 rt=$2 out=$3
  shift 3
  local flags=()
  case "$variant" in
    plain) flags=(-O1) ;;
    inline) flags=(-O2 -DDAWN_RT_INLINE_RC) ;;
    san) flags=(-O1 -fno-omit-frame-pointer -fsanitize=address,undefined -fno-sanitize-recover=undefined) ;;
    *) fail "unknown build variant $variant" ;;
  esac
  "$CC_BIN" "${CFLAGS[@]}" "${flags[@]}" "$@" -I "$rt" \
    -o "$out" "$HERE/host.c" "$HERE/stub.c" "$rt/dawn_rt.c" -lm
}

# run_host <binary>: the transcript on stdout
run_host() {
  ASAN_OPTIONS=detect_leaks=1 timeout 120 "$1"
}

echo "== the stub and the host, three builds =="
for variant in plain inline san; do
  build "$variant" "$ROOT/runtime/c" "$OUT/host-$variant"
  if ! run_host "$OUT/host-$variant" > "$OUT/transcript-$variant.txt" 2> "$OUT/host-$variant.err"; then
    cat "$OUT/host-$variant.err" >&2
    cat "$OUT/transcript-$variant.txt" >&2
    fail "the $variant build reported a failure"
  fi
  if ! diff -u "$HERE/expected.txt" "$OUT/transcript-$variant.txt"; then
    fail "the $variant transcript disagrees with expected.txt"
  fi
  echo "OK   $variant"
done

echo "== the panic =="
set +e
ASAN_OPTIONS=detect_leaks=0 "$OUT/host-plain" --panic > /dev/null 2> "$OUT/panic.err"
rc=$?
set -e
[ "$rc" -eq 1 ] || { cat "$OUT/panic.err" >&2; fail "--panic exited $rc, not 1"; }
grep -qx 'panic: t.checked: index below zero' "$OUT/panic.err" \
  || { cat "$OUT/panic.err" >&2; fail "--panic did not say its message"; }
"$OUT/host-plain" --panic-ok > /dev/null || fail "--panic-ok failed"
echo "OK   dawn_ffi_panic exits 1 with its message; a legal call exits 0"

echo "== the fence: dawn_fault is not reachable from a stub =="
if "$CC_BIN" "${CFLAGS[@]}" -O1 -I "$ROOT/runtime/c" -c -o "$OUT/fault.o" "$HERE/fault_stub.c" \
  > "$OUT/fault.err" 2>&1; then
  fail "fault_stub.c compiled against the real header: dawn_fault is not poisoned"
fi
grep -q "dawn_fault" "$OUT/fault.err" || { cat "$OUT/fault.err" >&2; fail "fault_stub.c failed, but not on dawn_fault"; }
echo "OK   fault_stub.c does not compile"

# A private copy of the runtime directory with one mutation applied. $1 is the
# mutation; the path of the copy's runtime/c is printed.
mutant() {
  local t="$OUT/ctl-$1"
  mkdir -p "$t/runtime"
  cp -R runtime/c "$t/runtime/c"
  python3 -I "$HERE/mutate.py" "$1" "$t"
  echo "$t/runtime/c"
}

echo "== negative controls =="

# abi-mismatch: the stub asks for ABI 1 and the header says 2
rt=$(mutant abi-mismatch)
if build plain "$rt" "$OUT/bin-abi" > "$OUT/ctl-abi.err" 2>&1; then
  fail "control abi-mismatch: the stub built against a header with another ABI number"
fi
grep -q "different dawn_ffi.h ABI" "$OUT/ctl-abi.err" \
  || { cat "$OUT/ctl-abi.err" >&2; fail "control abi-mismatch failed, but not on the ABI check"; }
echo "OK   control: abi-mismatch stops the stub's build"

# the other three: the host must go red under the sanitized build
for m in cstr-truncates err-mask-short bytes-cut-at-nul; do
  rt=$(mutant "$m")
  build san "$rt" "$OUT/bin-$m" || fail "control $m: the mutant did not build"
  set +e
  run_host "$OUT/bin-$m" > "$OUT/ctl-$m.txt" 2> "$OUT/ctl-$m.err"
  rc=$?
  set -e
  if [ "$rc" -eq 0 ] && diff -q "$HERE/expected.txt" "$OUT/ctl-$m.txt" > /dev/null; then
    fail "control $m: the contract stayed green"
  fi
  echo "OK   control: $m turns the contract red (exit $rc)"
done

# fence-open: with dawn_fault out of the list, the same stub must compile, so
# the red above was the fence
rt=$(mutant fence-open)
"$CC_BIN" "${CFLAGS[@]}" -O1 -I "$rt" -c -o "$OUT/fault-open.o" "$HERE/fault_stub.c" \
  > "$OUT/fault-open.err" 2>&1 || { cat "$OUT/fault-open.err" >&2; fail "control fence-open: fault_stub.c still fails with dawn_fault out of the fence, so its red was not the fence"; }
echo "OK   control: fence-open lets fault_stub.c compile"

echo "ffi header contract: OK"
