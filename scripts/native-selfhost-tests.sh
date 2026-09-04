#!/usr/bin/env bash
# The compiler's own inline tests, on the native backend.
#
# `gates.yml`'s `test` job runs `./bin/dawn test selfhost`, which is the JVM
# and only the JVM, so every inline test in the compiler was read by one
# backend. That was tolerable while those tests were about data structures. It
# stopped being tolerable on 2026-09-04, when `Console` and `Exit` became
# effects and twenty-four CLI cases moved out of scripts/native-cli-diff.sh
# into selfhost/src/main.dawn and nmain.dawn (docs/effects-design.md §8.1): an
# inline test runs on whichever backend runs `dawn test`, so without this leg
# each moved case would have traded two backends for one.
#
# The target is the native driver's own module graph, not the `selfhost`
# project. This backend refuses `use java` (jsig_refused) and main.dawn,
# jvm/emit, jvm/codegen and jvm/jreflect are built on it, so `dawnc test
# selfhost` is 768 errors -- all of them that refusal, none of them a bug.
# nmain.dawn's graph is the half of selfhost this backend compiles at all, and
# it is the half the moved cases' native halves live in. The JVM half stays
# covered by `./bin/dawn test selfhost`, which is the only place main.dawn's
# parsers can run.
#
# The binary is built the plain way (emitc + cc), which is what
# native-cli-diff.sh does when DAWNC_BIN is unset: this leg's subject is the
# tests, not the release artifact.
#
#   ./scripts/native-selfhost-tests.sh              # builds the native driver
#   DAWNC_BIN=/path/to/dawnc ./scripts/native-selfhost-tests.sh   # reuse one
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

OUT=${TMPDIR:-/tmp}/native-selfhost-tests.$$
mkdir -p "$OUT"
if [ -z "${KEEP:-}" ]; then trap 'rm -rf "$OUT"' EXIT; fi

DAWNC=${DAWNC_BIN:-}
if [ -z "$DAWNC" ]; then
  # keep the toolchain's rebuild chatter out of the build below
  ./bin/dawn --version > /dev/null
  echo "building the native driver from selfhost/src/nmain.dawn..."
  ./bin/dawn __emitc selfhost/src/nmain.dawn -o "$OUT/nmain.c"
  "${CC:-cc}" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$ROOT/runtime/c" \
    -o "$OUT/dawnc" "$OUT/nmain.c" "$ROOT/runtime/c/dawn_rt.c" -lm
  DAWNC="$OUT/dawnc"
fi
case "$DAWNC" in /*) ;; *) DAWNC="$ROOT/$DAWNC" ;; esac

# `dawnc test` emits C for the target, builds it with cc and runs it
# (nmain.dawn, build_and_exec), so this needs a C compiler as much as the
# build above does. It runs from the repo root because a handful of these
# tests load the standard library through a relative `--std`, the way
# driver/stdlib's own tests do.
echo "== selfhost tests, native backend =="
"$DAWNC" test selfhost/src/nmain.dawn
