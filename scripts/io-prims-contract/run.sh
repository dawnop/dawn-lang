#!/usr/bin/env bash
# The contract of the io primitives (docs/io-prims-design.md), run on both
# backends, with its negative controls.
#
# The batch adds stdout bytes with a flush, append, range read, file size, disk
# space and sleep, each a primitive the JVM runtime and the C runtime implement
# separately. Two implementations of one meaning drift, so this holds them to
# one answer:
#
#   probe.dawn     every primitive through std/io, errors included (a missing
#                  file, a directory, a range past the end, a negative range,
#                  an append under a file), and the order of stdout bytes
#                  against text and against a child process. Its transcript has
#                  to equal expected.txt on the JVM backend, on the native
#                  backend at -O2, and on the native backend under ASan, LSan
#                  and UBSan. expected.txt is written by hand from the design,
#                  not recorded from a run.
#   streams        a 256 MiB body appended in 64 KiB blocks from stdin, a 256 MiB
#                  file streamed out in 64 KiB range reads, and a program that
#                  flushes and then blocks. The first two are held to the bytes
#                  (SHA-256) and to a peak resident set that is a few blocks
#                  and not the file; the third to the bytes arriving while the
#                  program is still blocked and the unflushed tail arriving at
#                  exit (io_check.py has the claims).
#
# Then the controls. A contract that has only ever been green has not shown it
# can see, so each of these breaks something on a private copy and requires red:
#
#   no-flush            flush_stdout does nothing (native: ready never arrives)
#   append-truncates    an append replaces the file
#   range-off-by-one    a range read starts one byte late
#   std-append-truncates, std-range-off-by-one
#                       the same two one layer up, where the JVM backend sees
#                       them (run through `dawn run --std <copy>`)
#   slurp               not a mutation: the program that holds the whole body
#                       before writing it. Its peak resident set must exceed
#                       the bound the append program stays under (native), and
#                       it must die under a 64 MiB JVM heap, which is what shows
#                       the memory claims above could have failed.
#
# A mutation that does not apply fails the script rather than silently testing
# nothing, and mutation-anchor-preflight proves each anchor in mutate.py
# exactly-once before any build.
#
#   scripts/io-prims-contract/run.sh
#   IO_CONTRACT_MB=32 scripts/io-prims-contract/run.sh   # smaller body
#
# It needs a JVM toolchain (./bin/dawn, which also emits the C of the native
# side: `__emitc`, as mem-contract does) and a `cc`, with sanitizers for the
# ASan leg; no native driver.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
HERE=scripts/io-prims-contract

MB=${IO_CONTRACT_MB:-256}
CC_BIN=${CC:-cc}

OUT=$(mktemp -d "${TMPDIR:-/tmp}/io-prims-contract.XXXXXX")
trap 'rm -rf "$OUT"' EXIT

JAVA=$(DAWN_LAUNCHER_PRINT_JAVA=1 ./bin/dawn)
CHECK="python3 -I $HERE/io_check.py"

CFLAGS=(-std=c11 -fwrapv -fexceptions -fno-strict-aliasing -ffp-contract=off -pthread
  -Wall -Wextra -Werror
  -Wno-unused-variable -Wno-unused-but-set-variable
  -Wno-unused-parameter -Wno-unused-label -Wno-parentheses-equality)

# native <emitted.c> <runtime-dir> <out> [san]: the unit linked against the
# runtime in <runtime-dir>, optimised, or sanitized when a fourth argument is given
native() {
  local src=$1 rt=$2 out=$3 san=${4:-}
  if [ -n "$san" ]; then
    "$CC_BIN" "${CFLAGS[@]}" -I "$rt" -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=undefined \
      -o "$out" "$src" "$rt/dawn_rt.c" -lm
  else
    "$CC_BIN" "${CFLAGS[@]}" -I "$rt" -O1 -o "$out" "$src" "$rt/dawn_rt.c" -lm
  fi
}

# the sanitizers must exist, or the leg below is green about nothing
printf 'int main(void) { return 0; }\n' > "$OUT/san_probe.c"
if ! "$CC_BIN" -fsanitize=address,undefined -o "$OUT/san_probe" "$OUT/san_probe.c" \
  > "$OUT/san_probe.err" 2>&1 || ! "$OUT/san_probe"; then
  cat "$OUT/san_probe.err" >&2
  echo "FAIL: $CC_BIN cannot build and run with -fsanitize=address,undefined"
  exit 1
fi

# ---- the probe, three ways --------------------------------------------------
echo "== probe: expected.txt on the JVM, on native, on native under sanitizers =="
./bin/dawn run "$HERE/probe.dawn" > "$OUT/probe-jvm.txt"
if ! diff -u "$HERE/expected.txt" "$OUT/probe-jvm.txt"; then
  echo "FAIL: the JVM run of the probe disagrees with expected.txt"
  exit 1
fi
echo "OK   probe on the JVM"
./bin/dawn __emitc "$HERE/probe.dawn" -o "$OUT/probe.c"
native "$OUT/probe.c" "$ROOT/runtime/c" "$OUT/probe-native"
"$OUT/probe-native" > "$OUT/probe-native.txt"
if ! diff -u "$HERE/expected.txt" "$OUT/probe-native.txt"; then
  echo "FAIL: the native run of the probe disagrees with expected.txt"
  exit 1
fi
echo "OK   probe on native"
native "$OUT/probe.c" "$ROOT/runtime/c" "$OUT/probe-asan" san
if ! ASAN_OPTIONS=detect_leaks=1 "$OUT/probe-asan" > "$OUT/probe-asan.txt" 2> "$OUT/probe-asan.err"; then
  cat "$OUT/probe-asan.err"
  echo "FAIL: the sanitized native probe reported an error"
  exit 1
fi
if ! diff -u "$HERE/expected.txt" "$OUT/probe-asan.txt"; then
  echo "FAIL: the sanitized native probe disagrees with expected.txt"
  exit 1
fi
echo "OK   probe on native under ASan, LSan and UBSan"

# ---- the streams ------------------------------------------------------------
echo "== streams: ${MB} MiB bodies, in 64 KiB blocks =="
./bin/dawn build "$HERE/streams" -o "$OUT/streams.jar" > "$OUT/streams-jvm-build.txt" 2>&1 || { cat "$OUT/streams-jvm-build.txt"; echo "FAIL: the JVM streams program did not build"; exit 1; }
./bin/dawn __emitc "$HERE/streams" -o "$OUT/streams.c"
native "$OUT/streams.c" "$ROOT/runtime/c" "$OUT/streams-native"
native "$OUT/streams.c" "$ROOT/runtime/c" "$OUT/streams-asan" san
# The JVM runs under a 64 MiB heap: a body held whole would not fit, so a pass
# is the claim. Its resident set is the JVM's own (78 MiB on one JDK, 274 MiB on
# the GraalVM one CI uses, with the heap capped the same) and is reported, not
# bounded.
JVM_PROG=("$JAVA" -XX:-UsePerfData -Xmx64m -jar "$OUT/streams.jar")
$CHECK ready -- "${JVM_PROG[@]}"
$CHECK append --mb "$MB" -- "${JVM_PROG[@]}"
$CHECK range --mb "$MB" -- "${JVM_PROG[@]}"
$CHECK ready -- "$OUT/streams-native"
$CHECK append --mb "$MB" --max-rss-mb 32 -- "$OUT/streams-native"
$CHECK range --mb "$MB" --max-rss-mb 32 -- "$OUT/streams-native"
# under the sanitizers the quarantine inflates the resident set, so only the bytes are held
ASAN_OPTIONS=detect_leaks=1 $CHECK ready -- "$OUT/streams-asan"
ASAN_OPTIONS=detect_leaks=1 $CHECK append --mb 32 -- "$OUT/streams-asan"
ASAN_OPTIONS=detect_leaks=1 $CHECK range --mb 32 -- "$OUT/streams-asan"

# ---- the controls -----------------------------------------------------------
echo "== negative controls =="
# the program that holds the whole body: it has to be seen to
$CHECK slurp --mb "$MB" --min-rss-mb 200 -- "$OUT/streams-native"
$CHECK slurp --mb "$MB" --expect-fail -- "${JVM_PROG[@]}"
echo "OK   control: slurp holds the body (native peak over 200 MiB, JVM dies under 64 MiB)"

# A private copy of what a mutation touches. $1 is the mutation.
mutant() {
  local t="$OUT/ctl-$1"
  mkdir -p "$t/runtime"
  cp -R runtime/c "$t/runtime/c"
  cp -R std "$t/std"
  python3 -I "$HERE/mutate.py" "$1" "$t"
  echo "$t"
}

# the native leg of a control: build the probe and streams against the broken
# runtime and require `$2` (a driver mode and its arguments) to go red
control_native() {
  local name=$1 t
  t=$(mutant "$name")
  native "$OUT/streams.c" "$t/runtime/c" "$t/streams"
  native "$OUT/probe.c" "$t/runtime/c" "$t/probe"
  echo "$t"
}

t=$(control_native no-flush)
if $CHECK ready -- "$t/streams" > "$OUT/ctl-no-flush.txt" 2>&1; then
  cat "$OUT/ctl-no-flush.txt"
  echo "FAIL: control no-flush: ready stayed green with flush_stdout doing nothing"
  exit 1
fi
grep -q "^FAIL ready" "$OUT/ctl-no-flush.txt" || { cat "$OUT/ctl-no-flush.txt"; echo "FAIL: control no-flush did not fail on the ready claim"; exit 1; }
echo "OK   control: no-flush turns ready red"

t=$(control_native append-truncates)
"$t/probe" > "$t/probe.txt" 2>/dev/null || true
if diff -q "$HERE/expected.txt" "$t/probe.txt" > /dev/null; then
  echo "FAIL: control append-truncates: the probe stayed green with append replacing the file"
  exit 1
fi
if $CHECK append --mb 16 -- "$t/streams" > "$t/append.txt" 2>&1; then
  cat "$t/append.txt"
  echo "FAIL: control append-truncates: the append drive stayed green"
  exit 1
fi
grep -q "^FAIL append" "$t/append.txt" || { cat "$t/append.txt"; echo "FAIL: control append-truncates did not fail on the append claim"; exit 1; }
echo "OK   control: append-truncates turns the probe and the append drive red"

t=$(control_native range-off-by-one)
"$t/probe" > "$t/probe.txt" 2>/dev/null || true
if diff -q "$HERE/expected.txt" "$t/probe.txt" > /dev/null; then
  echo "FAIL: control range-off-by-one: the probe stayed green with every range one byte late"
  exit 1
fi
if $CHECK range --mb 16 -- "$t/streams" > "$t/range.txt" 2>&1; then
  cat "$t/range.txt"
  echo "FAIL: control range-off-by-one: the range drive stayed green"
  exit 1
fi
grep -q "^FAIL range" "$t/range.txt" || { cat "$t/range.txt"; echo "FAIL: control range-off-by-one did not fail on the range claim"; exit 1; }
echo "OK   control: range-off-by-one turns the probe and the range drive red"

# one layer up, on the JVM backend (and native, through --std)
for m in std-append-truncates std-range-off-by-one; do
  t=$(mutant "$m")
  ./bin/dawn run --std "$t/std" "$HERE/probe.dawn" > "$t/probe-jvm.txt" 2>"$t/probe-jvm.err" || true
  if diff -q "$HERE/expected.txt" "$t/probe-jvm.txt" > /dev/null; then
    echo "FAIL: control $m: the JVM probe stayed green"
    exit 1
  fi
  ./bin/dawn __emitc --std "$t/std" "$HERE/probe.dawn" -o "$t/probe.c"
  native "$t/probe.c" "$ROOT/runtime/c" "$t/probe-native"
  "$t/probe-native" > "$t/probe-native.txt" 2>/dev/null || true
  if diff -q "$HERE/expected.txt" "$t/probe-native.txt" > /dev/null; then
    echo "FAIL: control $m: the native probe stayed green"
    exit 1
  fi
  echo "OK   control: $m turns the probe red on both backends"
done
echo "io primitives contract: OK"
