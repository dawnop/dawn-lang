#!/usr/bin/env bash
# Contract test for the C runtime's reference counting (perceus-design.md).
#
#   ./scripts/rc-contract/run.sh
#
# Two runs, because the two things worth checking need different settings:
#
#   * under AddressSanitizer, where a drop that does not recurse is a reported
#     leak and a drop that recurses twice is a double free. Neither is visible
#     from inside the program, which is why the oracle is the sanitizer rather
#     than printed output.
#   * under a small stack, where a drop that went back to C recursion crashes
#     on the 200k-node chain instead of quietly working until some larger
#     input. `ulimit -s` is the whole point of this second run.
#
# Strings and Bytes are counted like everything else (they joined the ledger
# 2026-07-29), so the sanitized run keeps leak detection on and a reported
# leak here is always a real one. Only the --rc=leak run turns it off: that
# mode leaks everything on purpose.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/rc-contract"
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

warn=(-Wall -Wextra -Werror -Wno-unused-parameter)

echo "== sanitized =="
"$cc_bin" -std=c11 -O1 -g -fsanitize=address -fwrapv -fno-strict-aliasing \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_asan" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
"$work/rc_asan"
ASAN_OPTIONS=detect_leaks=0 "$work/rc_asan" leak

# ASan replaces the allocator and grows stack frames, so the stack-depth check
# has to be a plain build.
echo "== small stack =="
"$cc_bin" -std=c11 -O1 -fwrapv -fno-strict-aliasing \
  "${warn[@]}" -I "$root/runtime/c" \
  -o "$work/rc_plain" "$here/rc_test.c" "$root/runtime/c/dawn_rt.c"
( ulimit -s 512 && "$work/rc_plain" )

echo "rc contract ok"
