#!/usr/bin/env bash
# Core lint over everything the tree compiles: zero violations is the claim.
#
#   ./scripts/core-lint-contract/corpus.sh            # spike-native corpus + selfhost
#   ./scripts/core-lint-contract/corpus.sh --jobs 4
#
# Why this exists beside run.py. run.py proves each rule can go red; this
# proves none of them goes red on a program that is right. A lint that flags
# good Core gets switched off, and then it proves nothing, so the false-positive
# count is measured on the widest inputs the tree has: every
# scripts/spike-native entry on both backends (std plus stdext/raw, the way
# spike-native/run.sh compiles them, `.jvm-only` entries on the JVM alone), and
# the compiler itself -- JVM `__emit selfhost` and native `__emitc` of
# selfhost/src/nmain.dawn.
#
# It only compiles. Running the programs is spike-native/run.sh's job, and the
# lint runs at compile time, so a compile is the whole of what it can say.
# DAWN_CORE_LINT=1 is set for every compile; a compile that fails for any
# other reason is reported too, because a lint that crashed is not a lint
# that passed.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sn="$root/scripts/spike-native"
jobs=4
if [ "${1:-}" = "--jobs" ]; then jobs=$2; fi

work=$(mktemp -d "${TMPDIR:-/tmp}/core-lint-corpus.XXXXXX")
trap 'rm -rf "$work"' EXIT

cd "$root"
"$root/bin/dawn" --version > /dev/null
std="$work/std"
mkdir -p "$std"
cp "$root"/std/*.dawn "$root/std/modules.txt" "$std/"
cp "$sn/stdext/raw.dawn" "$std/"
echo raw >> "$std/modules.txt"

export DAWN_CORE_LINT=1 root sn std work

one() {
  local name=$1 prog
  if [ -f "$sn/$name.dawn" ]; then prog="$sn/$name.dawn"; else prog="$sn/$name"; fi
  local rc=0
  "$root/bin/dawn" __emit --std "$std" "$prog" -o "$work/$name.classes" \
    > "$work/$name.jvm.log" 2>&1 || rc=$?
  [ "$rc" -eq 0 ] || echo "FAIL $name jvm" >> "$work/failures"
  if [ ! -f "$sn/$name.jvm-only" ]; then
    rc=0
    "$root/bin/dawn" __emitc --std "$std" "$prog" -o "$work/$name.c" \
      > "$work/$name.c.log" 2>&1 || rc=$?
    [ "$rc" -eq 0 ] || echo "FAIL $name c" >> "$work/failures"
  fi
}
export -f one
: > "$work/failures"

started=$(date +%s)
entries=$(grep -v '^#' "$sn/matrix.txt" | grep -v '^$')
count=$(printf '%s\n' "$entries" | wc -l | tr -d ' ')
printf '%s\n' "$entries" | xargs -P "$jobs" -I{} bash -c 'one "$@"' _ {}

rc=0
"$root/bin/dawn" __emit selfhost -o "$work/selfhost.classes" > "$work/selfhost.jvm.log" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || echo "FAIL selfhost jvm" >> "$work/failures"
rc=0
"$root/bin/dawn" __emitc selfhost/src/nmain.dawn -o "$work/nmain.c" > "$work/nmain.c.log" 2>&1 || rc=$?
[ "$rc" -eq 0 ] || echo "FAIL selfhost/src/nmain.dawn c" >> "$work/failures"

elapsed=$(( $(date +%s) - started ))
if [ -s "$work/failures" ]; then
  while read -r _ name backend; do
    base=${name##*/}
    case "$name" in
      selfhost) log="$work/selfhost.jvm.log" ;;
      selfhost/src/nmain.dawn) log="$work/nmain.c.log" ;;
      *) log="$work/$base.$backend.log" ;;
    esac
    echo "FAIL: $name ($backend)" >&2
    head -20 "$log" >&2
  done < "$work/failures"
  echo "FAIL: $(wc -l < "$work/failures" | tr -d ' ') compile(s) failed under DAWN_CORE_LINT=1" >&2
  exit 1
fi
echo "PASS  core lint: $count spike-native entries on both backends and the compiler itself, no violation (${elapsed}s)"
