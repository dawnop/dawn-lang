#!/usr/bin/env bash
# Compile the translation units `__emitc --split` / `dawnc emitc --split`
# wrote, in parallel, and link them with the runtime into one native binary
# (docs/c-tu-split-design.md, knife 2).
#
# Why a script of its own rather than an `xargs` line in each caller: five
# places build the native driver from nmain.dawn (native-fixpoint, the
# release artifact, native-selfhost-tests, the wasm-target job and the wasm
# harnesses' fallback), and the one thing they must agree on is the flag row.
# Before the split it was one `cc` line copied five times, and copying it was
# harmless because a copy was the whole recipe; with a parallel compile and a
# separate link, a copy that drifted on one flag would build a different
# compiler in one gate only.
#
# Why not inside dawnc: `dawnc build` drives cc through `io.run`, which waits
# for each process before starting the next (Proc has no spawn/wait yet,
# ruling 4.f), so the driver compiles the same units in one cc command, one
# after another. The scripts are where the parallelism is available today.
#
# Two properties the callers rely on:
#
#   - the link order is fixed: the units by name (tu00.c, tu01.c, ...), then
#     the runtime, then any extra C file in the order given. Never completion
#     order, which is what keeps two links of the same units byte-identical
#     (release-native.sh compares two) whatever finished compiling first.
#   - the compile order is not: the largest file starts first, so the longest
#     compile is not the last one started. Without LTO the objects, and so the
#     binary, do not depend on it or on the job count (design §4.4).
#
#   scripts/cc-units.sh [--static] -o OUT UNITS_DIR [EXTRA.c ...]
#
# UNITS_DIR holds dawn_prog.h and tu*.c, or a single main.c for a text with
# no unit markers. CC picks the compiler (default cc), CC_JOBS the number of
# compiles at once (default: every core).
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)

static=()
out=
while [ $# -gt 0 ]; do
  case $1 in
    --static) static=(-static); shift ;;
    -o) out=$2; shift 2 ;;
    *) break ;;
  esac
done
if [ -z "$out" ] || [ $# -lt 1 ]; then
  echo "usage: $0 [--static] -o OUT UNITS_DIR [EXTRA.c ...]" >&2
  exit 2
fi
units=$1
shift

cc_bin="${CC:-cc}"
jobs="${CC_JOBS:-$(nproc 2>/dev/null || echo 4)}"
ccflags=(-std=c11 -Wno-parentheses-equality -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -I "$root/runtime/c")

srcs=()
while IFS= read -r f; do srcs+=("$f"); done < <(find "$units" -maxdepth 1 -name 'tu*.c' | LC_ALL=C sort)
if [ ${#srcs[@]} -eq 0 ]; then
  if [ -f "$units/main.c" ]; then
    srcs=("$units/main.c")
  else
    echo "FAIL: $units holds no translation unit (tu*.c or main.c)" >&2
    exit 1
  fi
fi
srcs+=("$root/runtime/c/dawn_rt.c" "$@")

objdir=$(mktemp -d "${TMPDIR:-/tmp}/cc-units.XXXXXX")
trap 'rm -rf "$objdir"' EXIT

# `size src obj` rows, largest first, then handed to xargs two at a time
objs=()
list="$objdir/list"
: > "$list.unsorted"
i=0
for src in "${srcs[@]}"; do
  obj="$objdir/$(printf '%03d' "$i").o"
  objs+=("$obj")
  printf '%s\t%s\t%s\n' "$(wc -c < "$src" | tr -d ' ')" "$src" "$obj" >> "$list.unsorted"
  i=$((i + 1))
done
sort -t "$(printf '\t')" -k1,1nr "$list.unsorted" | cut -f2,3 | tr '\t' '\n' > "$list"

# xargs appends each pair after the fixed compiler row, so the last two
# arguments are the source and the object. It exits non-zero when any compile
# failed, and cc has already said why on stderr; the script stops there,
# before a link of half the units.
xargs -d '\n' -n 2 -P "$jobs" bash -c \
  'n=$#; exec "${@:1:n-2}" -c "${@:n-1:1}" -o "${@:n:1}"' _ "$cc_bin" "${ccflags[@]}" < "$list" \
  || { echo "FAIL: compiling the units in $units" >&2; exit 1; }

"$cc_bin" "${ccflags[@]}" "${static[@]}" -o "$out" "${objs[@]}" -lm
