#!/usr/bin/env bash
# The measurement behind docs/tileir-k4-design.md 1.2: one kernel spelled
# three ways (a scalar parameter, a one-element buffer, a host constant), its
# tileiras compile time and its host-observed launch time on this machine's
# GPU. Prints the raw runs and the medians; touches nothing in the tree.
#
#   scripts/scalar-bench/run.sh [--tileiras <bin>] [--gpu-name sm_NN] [--launches N] [--reps R]
#
# `--tileiras` defaults to $TILEIRAS, which a machine without pip carries (the
# bin/tileiras, bin/ptxas and lib/libnvvm.so.4 tree install-tileiras.sh makes).
# Compile time is the wall time of one `tileiras` run on the bytecode, three
# runs each; launch time is bench.dawn's, `--reps` repetitions of `--launches`
# launches, three by default. The medians are of those three, and the spread
# is min and max.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
tileiras="${TILEIRAS:-}"
gpu_name=sm_86
launches=2000
reps=3
while [ $# -gt 0 ]; do
  case "$1" in
    --tileiras) tileiras="$2"; shift ;;
    --gpu-name) gpu_name="$2"; shift ;;
    --launches) launches="$2"; shift ;;
    --reps) reps="$2"; shift ;;
    *) echo "usage: run.sh [--tileiras <bin>] [--gpu-name sm_NN] [--launches N] [--reps R]" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$tileiras" ] || { echo "run.sh: no tileiras (pass --tileiras or set TILEIRAS)" >&2; exit 2; }
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cc_bin="${CC:-cc}"

# The asm arguments are packages/tileir's: --opt-level 0 on sm_90 and sm_100.
asm=(--gpu-name "$gpu_name")
case "$gpu_name" in sm_90|sm_100) asm+=(--opt-level 0) ;; esac

mkdir -p "$work/k/src" "$work/b/src"
cp "$here/kernels.dawn" "$work/k/src/main.dawn"
cat > "$work/k/dawn.toml" <<TOML
schema = 1
name = "scalar_bench_kernels"

[deps]
tileir = "$root/packages/tileir"
TOML
cp "$here/bench.dawn" "$work/b/src/main.dawn"
printf 'schema = 1\nname = "scalar_bench"\n' > "$work/b/dawn.toml"

"$root/bin/dawn" --version > /dev/null
echo "tileiras: $("$tileiras" --version | sed -n 's/.*release \([0-9.]*\), V\([0-9.]*\).*/\1 V\2/p')  target: $gpu_name"
for v in param buffer const; do
  "$root/bin/dawn" run "$work/k" -- "$v" --bytecode "$work/bench_$v.tilebc" > /dev/null
  cp "$work/bench_$v.tilebc" "$work/b_$v.tilebc"
done

now_ns() { python3 -c 'import time; print(time.monotonic_ns())'; }
median3() { python3 -c 'import sys; v=sorted(int(x) for x in sys.argv[1:]); print(v[len(v)//2], v[0], v[-1])' "$@"; }

echo "-- tileiras compile time (ms), 3 runs each: median min max"
for v in param buffer const; do
  ts=()
  for _ in 1 2 3; do
    t0=$(now_ns)
    "$tileiras" "${asm[@]}" -o "$work/bench_$v.cubin" "$work/bench_$v.tilebc"
    t1=$(now_ns)
    ts+=($(( (t1 - t0) / 1000000 )))
  done
  echo "compile bench_$v ms=$(median3 "${ts[@]}") runs=${ts[*]} bytes=$(wc -c < "$work/bench_$v.tilebc") cubin=$(wc -c < "$work/bench_$v.cubin")"
done

echo "-- launch time"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -I "$root/runtime/c" -c -o "$work/rt.o" "$root/runtime/c/dawn_rt.c"
"$root/bin/dawn" __emitc --std "$root/std" "$work/b" -o "$work/b.c" > /dev/null
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread -I "$root/runtime/c" -o "$work/b.bin" "$work/b.c" "$work/rt.o" -lm
"$work/b.bin" "$work/bench_param.cubin" "$work/bench_buffer.cubin" "$work/bench_const.cubin" "$launches" "$reps" | tee "$work/bench.out"
echo "-- launch time (ns per launch): median min max"
sed -n 's/^bench \([a-z_]*\) grid=\([0-9]*\) launches=[0-9]* ns_per_launch=\[\(.*\)\]$/\1 \2 \3/p' "$work/bench.out" |
  while read -r name grid vals; do
    echo "launch $name grid=$grid ns=$(median3 ${vals//,/ }) runs=[$vals]"
  done
