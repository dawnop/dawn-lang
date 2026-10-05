#!/usr/bin/env bash
# `--map` never touches the C (docs/source-span-map-design.md section 12.4).
#
#   scripts/c-map/same.sh [--dawnc <native dawnc>]
#
# For each input, one compiler writes the C twice, once with `--map` and
# `--split` and once with neither, and the two must be byte for byte the same,
# the split units included. This is the hard criterion's second leg; the first
# is structural (`line` builds its text the same way either way) and the third
# is the comparison against the parent commit, which needs two compilers and
# lives in the gate runs, not here.
#
# The inputs are every program the C backend takes: the native driver itself
# (nmain.dawn, sixteen units), the tile-golden kernels as scripts/core-sites
# compiles them, the call-shape corpus beside this file, and every examples/
# program `__emitc` accepts. An example the C backend refuses (`use java`) is
# skipped by name, and only when the plain run refuses it too.
#
# With `--dawnc`, the native compiler built from this tree is also asked for
# nmain.dawn's map, and it has to be the JVM-hosted compiler's map exactly:
# the C of the two is held equal by the native fixpoint (A == B), and the map
# is a function of the same emission.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
dawn="${DAWN_BIN:-$root/bin/dawn}"
dawnc=""
if [ "${1:-}" = "--dawnc" ]; then dawnc="$2"; fi

work="$(mktemp -d "${TMPDIR:-/tmp}/c-map-same.XXXXXX")"
trap 'rm -rf "$work"' EXIT

proj="$work/kernels"
mkdir -p "$proj/src"
cp "$root/scripts/tile-golden/kernels.dawn" "$proj/src/main.dawn"
printf 'schema = 1\nname = "c_map"\n\n[deps]\ntileir = "%s"\ntileref = "%s"\n' \
  "$root/packages/tileir" "$root/packages/tileref" > "$proj/dawn.toml"

inputs=("$root/selfhost/src/nmain.dawn" "$proj" "$root/scripts/c-map/corpus.dawn")
while IFS= read -r f; do inputs+=("$f"); done < <(cd "$root" && find examples -name '*.dawn' -path '*/*' | sort | sed "s|^|$root/|")
while IFS= read -r d; do inputs+=("$d"); done < <(cd "$root" && find examples/projects -mindepth 1 -maxdepth 1 -type d | sort | sed "s|^|$root/|")

same=0
skipped=0
n=0
for t in "${inputs[@]}"; do
  n=$((n + 1))
  d="$work/$n"
  mkdir -p "$d"
  if ! "$dawn" __emitc "$t" -o "$d/plain.c" > "$d/plain.log" 2>&1; then
    # a module of a project, or a program the C backend refuses: no C to compare
    skipped=$((skipped + 1))
    continue
  fi
  "$dawn" __emitc "$t" -o "$d/mapped.c" --map "$d/c.dawnmap" --split "$d/units"
  "$dawn" __emitc "$t" --split "$d/units-plain"
  if ! cmp -s "$d/plain.c" "$d/mapped.c"; then
    echo "FAIL: --map changed the C of $t" >&2
    diff "$d/plain.c" "$d/mapped.c" | sed -n '1,20p' >&2
    exit 1
  fi
  if ! diff -r "$d/units-plain" "$d/units" > "$d/units.diff"; then
    echo "FAIL: --map changed the --split units of $t" >&2
    sed -n '1,20p' "$d/units.diff" >&2
    exit 1
  fi
  same=$((same + 1))
done
echo "OK: $same input(s) emit the same C and units with and without --map ($skipped skipped: no C)"

if [ -n "$dawnc" ]; then
  "$dawn" __emitc "$root/selfhost/src/nmain.dawn" -o "$work/jvm.c" --map "$work/jvm.dawnmap"
  "$dawnc" emitc "$root/selfhost/src/nmain.dawn" -o "$work/native.c" --map "$work/native.dawnmap"
  cmp "$work/jvm.c" "$work/native.c"
  if ! cmp -s "$work/jvm.dawnmap" "$work/native.dawnmap"; then
    echo "FAIL: the native compiler writes a different map of nmain.dawn than the JVM-hosted one" >&2
    diff "$work/jvm.dawnmap" "$work/native.dawnmap" | sed -n '1,20p' >&2
    exit 1
  fi
  echo "OK: dawnc emitc --map and __emitc --map write the same map of nmain.dawn"
fi
