#!/usr/bin/env bash
# K-A7 phase 1 (docs/jvm-base-plan.md §5.7): the `dawn/rt/Asm` the compiler
# emits must be a drop-in for the five `dawn.tool.AdtClassWriter` statics that
# are the last handwritten Java in the trusted base (BOOT-01).
#
#   ./scripts/asm-adapter-contract/run.sh
#
# Nothing calls the emitted class in phase 1 -- the call sites move in phase 2,
# after a release and a seed advance. So every other gate is green whatever
# `gen_asm_class` writes, including nothing at all. This is the gate that can
# tell the difference, and it is the reason phase 1 is not "emit it and hope".
#
# Red demo (2026-08-03): `iload_0` -> `iconst_0` in gen_asm_class's `plain`, so
# the flag is picked rather than forwarded. Three of the six checks go red, the
# other three stay green -- see the section in jvm-base-plan.md §5.7.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)

./bin/dawn --version > /dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# The emitted class comes from the compiler's own emission, not from a copy
# checked in here: what is under test is what `dawn build selfhost` puts in the
# jar. `selfhost` is the corpus that has ASM on its class path, which is the
# condition main.dawn emits `dawn/rt/Asm` under.
mkdir -p "$work/emit"
./bin/dawn __emit selfhost -o "$work/emit" > /dev/null
if [ ! -f "$work/emit/dawn/rt/Asm.class" ]; then
  echo "FAIL: the compiler emitted no dawn/rt/Asm for the selfhost corpus" >&2
  exit 1
fi

# The toolchain jar carries the vendored ASM and the reference adapter; the
# emitted directory comes first so `dawn.rt.Asm` resolves to what was just
# emitted even once a later seed also carries one.
javac -cp "$root/build/dawn-selfhost.jar" -d "$work" scripts/asm-adapter-contract/Diff.java
java -cp "$work:$work/emit:$root/build/dawn-selfhost.jar" Diff
