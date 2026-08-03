#!/usr/bin/env bash
# K-A7 (docs/jvm-base-plan.md §5.7): the `dawn/rt/Asm` the compiler emits must
# be a drop-in for the five `dawn.tool.AdtClassWriter` statics that used to be
# the last handwritten Java in the trusted base (BOOT-01).
#
#   ./scripts/asm-adapter-contract/run.sh
#
# In phase 1 nothing called the emitted class, so every other gate was green
# whatever `gen_asm_class` wrote, including nothing at all. Since phase 2 the
# call sites name it -- and the reason this gate still matters is the mirror
# image: the two adapters are interchangeable, so nothing else could tell a
# compiler that migrated from one that did not (scripts/adapter-callsites.py
# is the check for that half).
#
# The reference is compiled from the Java source in the `kotlin-final` tag,
# not read out of the toolchain jar. Phase 3 dropped `dawn/tool` from
# `--vendor`, so the class is no longer in any jar here -- and the tagged
# source is the better reference anyway: it is what the vendored binary was
# built from, and it does not vanish when the binary does.
#
# Red demo (2026-08-03): `iload_0` -> `iconst_0` in gen_asm_class's `plain`, so
# the flag is picked rather than forwarded. Three of the six checks go red, the
# other three stay green -- see the section in jvm-base-plan.md §5.7.
set -euo pipefail
cd "$(dirname "$0")/../.."
root=$(pwd)

REF_SRC=compiler/src/main/java/dawn/tool/AdtClassWriter.java
REF_TAG=kotlin-final

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

# The reference, rebuilt from the tagged Java source. A fresh CI checkout is
# shallow and tagless, so fetch the tag before asking archive for it (the same
# shape seedjar.sh uses for the seed's std).
git rev-parse -q --verify "refs/tags/$REF_TAG" > /dev/null ||
  git fetch -q --depth 1 origin tag "$REF_TAG"
mkdir -p "$work/ref"
git show "$REF_TAG:$REF_SRC" > "$work/ref/AdtClassWriter.java"

# The toolchain jar carries the vendored ASM the reference compiles against;
# the emitted directory comes first so `dawn.rt.Asm` resolves to what was just
# emitted even once a later seed also carries one.
javac -nowarn -cp "$root/build/dawn-selfhost.jar" -d "$work/ref" "$work/ref/AdtClassWriter.java"
javac -cp "$root/build/dawn-selfhost.jar" -d "$work" scripts/asm-adapter-contract/Diff.java
java -cp "$work:$work/emit:$work/ref:$root/build/dawn-selfhost.jar" Diff
