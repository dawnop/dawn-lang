#!/usr/bin/env bash
# Differential harness: run a Dawn program on both backends and diff stdout.
#
#   ./scripts/spike-native/run.sh                  # every corpus file
#   ./scripts/spike-native/run.sh prog.dawn ...    # just these
#
# This is the first of the three acceptance gates in
# docs/native-backend-plan.md 5. The corpus grows with each feature the
# native backend learns; a program only belongs here once both backends can
# compile it, so a failure is always a regression, never a gap.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/spike-native"
cc_bin="${CC:-cc}"

if [ "$#" -gt 0 ]; then
  progs=("$@")
else
  progs=("$here"/*.dawn)
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail=0
for prog in "${progs[@]}"; do
  name="$(basename "$prog" .dawn)"
  printf '%-12s ' "$name"

  "$root/bin/dawn" run "$prog" >"$work/$name.jvm" 2>"$work/$name.jvmerr" || {
    echo "FAIL (jvm backend)"; cat "$work/$name.jvmerr"; fail=1; continue
  }

  "$root/bin/dawn" __emitc "$prog" -o "$work/$name.c" || {
    echo "FAIL (emitc)"; fail=1; continue
  }

  # -fwrapv: Dawn's Int wraps like the JVM's long, and signed overflow is
  # otherwise UB. -fno-strict-aliasing: same reason the real backend needs
  # it. Both are correctness flags, not tuning.
  #
  # -Werror is a real gate: a Core type that reaches C wrong shows up first
  # as an int-from-pointer warning, long before it shows up as a wrong
  # answer. That is how the pattern-binding types were caught. The three
  # -Wno- flags cover noise a code generator legitimately produces.
  "$cc_bin" -std=c11 -O2 -fwrapv -fno-strict-aliasing \
    -Wall -Wextra -Werror \
    -Wno-unused-variable -Wno-unused-but-set-variable \
    -Wno-unused-parameter -Wno-unused-label \
    -I "$root/runtime/c" \
    -o "$work/$name.bin" "$work/$name.c" "$root/runtime/c/dawn_rt.c" || {
    echo "FAIL (cc)"; fail=1; continue
  }

  "$work/$name.bin" >"$work/$name.native" || {
    echo "FAIL (native run)"; fail=1; continue
  }

  if diff -q "$work/$name.jvm" "$work/$name.native" >/dev/null; then
    echo "ok ($(wc -l <"$work/$name.jvm" | tr -d ' ') lines identical)"
  else
    echo "DIFFER"
    diff -u "$work/$name.jvm" "$work/$name.native" | head -40
    fail=1
  fi
done

exit "$fail"
