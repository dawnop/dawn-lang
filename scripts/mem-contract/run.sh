#!/usr/bin/env bash
# Contract test for the `I64Buf` and `F64Buf` primitives and their byte endpoints (docs/mem-buffer-design.md 5, 6).
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
java -XX:-UsePerfData -Xss512m -jar "$jar" run "$here/probe.dawn" > "$work/jvm_out.txt"
if ! diff -u "$here/expected.txt" "$work/jvm_out.txt"; then
  echo "FAIL: the JVM run of the I64Buf probe disagrees with expected.txt" >&2
  exit 1
fi
echo "PASS  JVM values, panics and workloads"

# ---- native ----------------------------------------------------------------
cc_bin="${CC:-cc}"
java -XX:-UsePerfData -Xss512m -jar "$jar" __emitc "$here/probe.dawn" -o "$work/probe.c"
cflags=(-std=c11 -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread
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
refs="$(grep -c 'dawn_\(i64\|f64\)buf_\(at\|set\|len\)' "$work/probe.s" || true)"
if [ "$refs" != "0" ]; then
  grep 'dawn_\(i64\|f64\)buf_\(at\|set\|len\)' "$work/probe.s" | head -5 >&2
  echo "FAIL: dawn_i64buf_at/set/len or the f64buf twin left a symbol behind in the probe's assembly ($refs lines)." >&2
  echo "      They are static inline in dawn_rt.h so a buffer loop pays no call per access;" >&2
  echo "      out of line they cost 1.7x on bcrypt (docs/mem-buffer-design.md 6.1)." >&2
  exit 1
fi
echo "PASS  at, set and len compile inline"

# ---- Core keeps the order of reads and writes ---------------------------------
# A `Mem` call is not a pure call. Core has no dead-code or common-subexpression
# pass today; if one arrives it must leave order.dawn's four calls alone: two
# reads of one slot with a write between them, and a read nobody uses.
java -XX:-UsePerfData -Xss512m -jar "$jar" __lower --dump "$work/core" "$here/order.dawn" > /dev/null
python3 - "$work/core/order.core" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
body = text.split("fn order.order", 1)[1].split("\nfn ", 1)[0]
calls = re.findall(r"call direct std/mem\.(\w+)", body)
want = ["at", "set", "at", "at"]
if calls != want:
    print(f"FAIL: Core for order.dawn calls {calls}, want {want}", file=sys.stderr)
    print("      a read or a write was merged, moved or dropped (docs/mem-buffer-design.md 9, K3)", file=sys.stderr)
    sys.exit(1)
PY
got="$(java -XX:-UsePerfData -Xss512m -jar "$jar" run "$here/order.dawn")"
if [ "$got" != "7" ]; then
  echo "FAIL: order.dawn printed '$got', want 7 (first read 0, second read 7)" >&2
  exit 1
fi
echo "PASS  Core keeps reads and writes in order"

# ---- effect evidence is passed by borrow ---------------------------------------
# Every `!Mem` function takes the handler's evidence as a hidden parameter. If
# the native backend passes it owned, each `mem.at` costs a dup, an own-frame
# and a drop, all out-of-line runtime calls: 6.3x a version without evidence on
# a bcrypt-shaped kernel (docs/mem-buffer-design.md 10, 2). The output stays
# right, so this reads the C. A borrowed parameter is spelled `v<N>` in a
# definition's header and an owned one `p<N>`; the evidence is the last
# parameter, and it must be borrowed, never named by a dup, a drop or an
# own-slot store. The buffer accessors and the Feistel helper, which have no
# reason to count anything, must have no counting at all. (The tail-recursive
# drivers do hold their buffer owned, for the self-jump's sake, and that is
# not what is pinned here.)
borrow_check() {
  python3 - "$1" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
want = [("dawn_std_2mem__at", True), ("dawn_std_2mem__set", True),
        ("dawn_kernel__feistel", True), ("dawn_kernel__rounds", False),
        ("dawn_kernel__schedule", False), ("dawn_kernel__init", False)]
bad = 0
for name, bare in want:
    m = re.search(r"^[^\n]*\b" + name + r"\(([^\n)]*)\) \{\n(.*?)^\}", text, re.S | re.M)
    if not m:
        print(f"FAIL: no definition of {name} in the emitted C", file=sys.stderr)
        bad = 1
        continue
    last = m.group(1).split(",")[-1].split()[-1]
    body = m.group(2)
    if not re.fullmatch(r"v\d+", last):
        print(f"FAIL: {name} takes its evidence as `{last}`: owned, not borrowed", file=sys.stderr)
        bad = 1
        continue
    if bare:
        hits = re.findall(r"dawn_dup|dawn_drop|DAWN_OWN_FRAME|dawn_own\[", body)
    else:
        hits = re.findall(r"dawn_(?:dup|drop|take)\([(\w*&\s]*\b" + last + r"\b|dawn_own\[\d+\] = [(\w*&\s]*\b" + last + r"\s*;", body)
    if hits:
        print(f"FAIL: {name} counts its evidence `{last}` ({len(hits)} operations)", file=sys.stderr)
        bad = 1
sys.exit(bad)
PY
}

java -XX:-UsePerfData -Xss512m -jar "$jar" __emitc "$here/kernel.dawn" -o "$work/kernel.c"
borrow_check "$work/kernel.c"
"$cc_bin" "${cflags[@]}" -O2 -o "$work/kernel_native" "$work/kernel.c" "$root/runtime/c/dawn_rt.c" -lm
want_k="$(java -XX:-UsePerfData -Xss512m -jar "$jar" run "$here/kernel.dawn")"
got_k="$("$work/kernel_native")"
if [ "$got_k" != "$want_k" ]; then
  echo "FAIL: the native kernel printed '$got_k', the JVM '$want_k'" >&2
  exit 1
fi
echo "PASS  Mem evidence is borrowed in the generated C"

# The negative control: force the kernel's own evidence parameter owned (the
# coherent flip of rc-mode-contract, `both`) and the same check has to go red,
# or a regex that stopped matching would pass this section for ever.
DAWN_RC_MODE_FLIPS="kernel:feistel:4:3=both" \
  java -XX:-UsePerfData -Xss512m -jar "$jar" __emitc "$here/kernel.dawn" -o "$work/kernel_owned.c"
if borrow_check "$work/kernel_owned.c" 2> "$work/borrow_neg.err"; then
  echo "FAIL: the evidence-borrow check passed on C that passes the evidence owned" >&2
  exit 1
fi
if ! grep -q 'dawn_kernel__feistel' "$work/borrow_neg.err"; then
  cat "$work/borrow_neg.err" >&2
  echo "FAIL: the negative control went red, but not on the flipped function" >&2
  exit 1
fi
echo "PASS  the evidence-borrow check goes red on owned evidence"

# Domain identity is observable independently of the allocation handlers' bodies.
python3 "$here/scope.py" --selftest
