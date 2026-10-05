#!/usr/bin/env bash
# `--map` never touches the classes (docs/source-span-map-design.md section 13.4).
#
#   scripts/jvm-map/same.sh
#
# For each input, one compiler writes the classes twice, once with `--map` and
# once without, and the two directories must be byte for byte the same. This
# is the regression net under a structural argument: the classes `--map`
# writes come from an emission with `mapping` false, which visits exactly what
# an emission without `--map` visits; the labelled emission is only compared.
# The comparison against the parent commit needs two compilers and lives in the
# gate runs (prev-diff), not here.
#
# The inputs: the compiler itself, the tile-golden kernels as
# scripts/core-sites compiles them, the call-shape corpus of scripts/core-sites,
# dead.dawn beside this file (whose labelled class does differ, so it is the
# input that shows the written classes do not follow it), the site generator,
# and every examples/ program and project `__emit` accepts. An input it refuses
# without `--map` (a module of a project, a fragment) is skipped.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
dawn="${DAWN_BIN:-$root/bin/dawn}"

work="$(mktemp -d "${TMPDIR:-/tmp}/jvm-map-same.XXXXXX")"
trap 'rm -rf "$work"' EXIT

proj="$work/kernels"
mkdir -p "$proj/src"
cp "$root/scripts/tile-golden/kernels.dawn" "$proj/src/main.dawn"
printf 'schema = 1\nname = "jvm_map"\n\n[deps]\ntileir = "%s"\ntileref = "%s"\n' \
  "$root/packages/tileir" "$root/packages/tileref" > "$proj/dawn.toml"

inputs=("$root/selfhost" "$proj" "$root/scripts/core-sites/corpus.dawn" "$root/scripts/jvm-map/dead.dawn" "$root/site")
while IFS= read -r f; do inputs+=("$f"); done < <(cd "$root" && find examples -name '*.dawn' | sort | sed "s|^|$root/|")
while IFS= read -r d; do inputs+=("$d"); done < <(cd "$root" && find examples/projects -mindepth 1 -maxdepth 1 -type d | sort | sed "s|^|$root/|")

same=0
skipped=0
n=0
for t in "${inputs[@]}"; do
  n=$((n + 1))
  d="$work/$n"
  mkdir -p "$d"
  if ! "$dawn" __emit "$t" -o "$d/plain" > "$d/plain.log" 2>&1; then
    skipped=$((skipped + 1))
    continue
  fi
  "$dawn" __emit "$t" -o "$d/mapped" --map "$d/jvm.dawnmap" > "$d/mapped.log"
  if ! diff -r "$d/plain" "$d/mapped" > "$d/classes.diff"; then
    echo "FAIL: --map changed the classes of $t" >&2
    sed -n '1,20p' "$d/classes.diff" >&2
    exit 1
  fi
  rm -rf "$d"
  same=$((same + 1))
done
echo "OK: $same input(s) emit the same classes with and without --map ($skipped skipped: no classes)"
