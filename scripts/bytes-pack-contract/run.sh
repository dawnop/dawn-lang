#!/usr/bin/env bash
# Contract test for the integer pack/unpack primitives, `bytes_pack_int` and
# `bytes_unpack_int` (docs/bulk-array-bytes-design.md, section 3).
#
#   ./scripts/bytes-pack-contract/run.sh
#
# There is no `--record`. `expected.txt` is the answer the written semantics
# give (byte order is the argument's, packing wraps to the low bits, unpacking
# sign- or zero-extends, a bad width or a ragged length panics with a fixed
# sentence), worked out by hand from the design rather than taken from a run:
# a recording would be a report of what a backend does, and the point is a
# check on it. Change what the probe prints and edit the file to match.
#
# The primitives name `Array`, which only std can, so as in
# scripts/array-contract the harness builds a copy of std/ with bytespack.dawn
# dropped in and compiles probe.dawn, an ordinary user module, against it. The
# same probe runs on both backends and both must equal expected.txt, which
# also makes them equal to each other: the JVM runtime (rtclasses.dawn, a
# ByteBuffer loop) and the native one (dawn_rt.c) share no code.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/bytes-pack-contract"
cc_bin="${CC:-cc}"
# the runtime the native leg links; overridable so a negative control can hand
# it a deliberately broken copy without touching the tree
rt_dir="${BYTES_PACK_RT_DIR:-$root/runtime/c}"

# warm the toolchain first: bin/dawn announces a rebuild on stderr
"$root/bin/dawn" --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$root"/std/*.dawn "$root/std/modules.txt" "$work/"
for d in "$root"/std/*/; do if [ -d "$d" ]; then cp -r "$d" "$work/"; fi; done
cp "$here/bytespack.dawn" "$work/"
echo bytespack >> "$work/modules.txt"

"$root/bin/dawn" run --std "$work" "$here/probe.dawn" > "$work/jvm.out"
if ! diff -u "$here/expected.txt" "$work/jvm.out"; then
  echo "FAIL: the JVM backend disagrees with the written semantics" >&2
  exit 1
fi

"$root/bin/dawn" __emitc --std "$work" "$here/probe.dawn" -o "$work/probe.c"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -Wall -Wextra -Werror \
  -Wno-unused-variable -Wno-unused-but-set-variable \
  -Wno-unused-parameter -Wno-unused-label -Wno-parentheses-equality \
  -I "$rt_dir" \
  -o "$work/probe" "$work/probe.c" "$rt_dir/dawn_rt.c" -lm
"$work/probe" > "$work/native.out"
if ! diff -u "$here/expected.txt" "$work/native.out"; then
  echo "FAIL: the native backend disagrees with the written semantics" >&2
  exit 1
fi

echo "PASS  bytes_pack_int/bytes_unpack_int: $(wc -l < "$here/expected.txt") lines, JVM and native"
