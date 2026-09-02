#!/usr/bin/env bash
# The Tile IR text golden: packages/tileir's recording handler and renderer
# against the .mlir files beside this script, on both backends, with a live
# mutant per claim the golden makes.
#
#   ./scripts/tile-golden/run.sh             # compare
#   ./scripts/tile-golden/run.sh --record    # re-record the .mlir files
#
# This is layer 0 of docs/tile-backend-design.md 6.2: it says whether the
# handler and the renderer changed, not whether what they emit is right. The
# spelling was checked against the specification's text and the dialect's own
# round-trip tests when the goldens were first recorded; `cuda-tile-translate`
# is not on this machine (it is not on pip), so a round trip through the real
# parser waits for the `tileiras` layer of knife 3.
#
# Three kinds of check:
#
#   trace     -- kernels.dawn traces every kernel twice and panics if the two
#                records differ, before printing anything. The program
#                finishing is the assertion "a kernel traced twice is the same
#                program"; the goldens never see a non-deterministic trace.
#   golden    -- the rendered text of each kernel, on the JVM and natively,
#                equals <kernel>.mlir byte for byte. Both backends compile one
#                Dawn source, so their agreement says nothing about the
#                spelling; the golden is the outside record. --record writes
#                the JVM's text and still requires native to match it.
#   mutant    -- one rule removed from a copy of the package, the kernels run
#                against that copy on both backends, and one named kernel
#                required to go red on both, in the way the rule predicts:
#
#     drop-store-token  the renderer omits the store's token operand
#                       -> vadd's text differs from its golden, exit 0
#     load-dtype-f64    `load` hands the handler "f64" instead of the
#                       parameter's format -> vadd_f32 is refused at trace
#                       time (the entry says f32, the load says f64), so the
#                       run exits non-zero with the handler's refusal, and
#                       vadd is untouched
#
# The anchor each mutant rewrites must match exactly once, so a refactor that
# moves it fails here instead of silently un-mutating (scripts/narrow-contract
# is the precedent for the whole shape).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/tile-golden"
kernels=(vadd vadd_f32)
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mode=check
[ "${1:-}" = "--record" ] && mode=record

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if command -v md5sum > /dev/null 2>&1; then
  digest() { md5sum "$1" | cut -d' ' -f1; }
else
  digest() { md5 -q "$1"; }
fi

"$root/bin/dawn" --version > /dev/null

# The runtime is compiled once; every native build below links this object.
rt_obj="$work/dawn_rt.o"
"$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
  -I "$root/runtime/c" -c -o "$rt_obj" "$root/runtime/c/dawn_rt.c" ||
  fail "the C runtime does not compile"

# A project whose only dependency is a copy of (or the real) packages/tileir.
project() { # dir, package-dir
  mkdir -p "$1/src"
  cp "$here/kernels.dawn" "$1/src/main.dawn"
  cat > "$1/dawn.toml" <<TOML
schema = 1
name = "tile_golden"

[deps]
tileir = "$2"
TOML
}

fork_pkg() { # dst
  rm -rf "$1"
  cp -r "$root/packages/tileir" "$1"
}

# Rewrite exactly one anchor in a forked package module, or fail.
patch_pkg() { # pkgdir, module, label, old, new
  python3 - "$1/src/$2" "$3" "$4" "$5" <<'PY'
import pathlib
import sys

path, label, old, new = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
p = pathlib.Path(path)
text = p.read_text()
if text.count(old) != 1:
    raise SystemExit(f"{label}: anchor is not unique in {p.name} ({text.count(old)} matches)")
p.write_text(text.replace(old, new))
PY
}

run_jvm() { # project, kernel, out ; returns the program's exit code
  "$root/bin/dawn" run "$1" -- "$2" > "$3" 2> "$3.err"
}

build_native() { # project, bin
  "$root/bin/dawn" __emitc "$1" -o "$2.c" > "$2.emit" 2>&1 ||
    { cat "$2.emit" >&2; fail "native emit failed for $1"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" -o "$2" "$2.c" "$rt_obj" -lm > "$2.cc" 2>&1 ||
    { cat "$2.cc" >&2; fail "native compile failed for $1"; }
}

run_native() { # bin, kernel, out ; returns the program's exit code
  "$1" "$2" > "$3" 2> "$3.err"
}

# ---------------------------------------------------------------- trace + golden

project "$work/clean" "$root/packages/tileir"
build_native "$work/clean" "$work/clean.bin"

for k in "${kernels[@]}"; do
  golden="$here/$k.mlir"
  run_jvm "$work/clean" "$k" "$work/$k.jvm" ||
    { cat "$work/$k.jvm.err" >&2; fail "$k did not trace and render on the JVM"; }
  run_native "$work/clean.bin" "$k" "$work/$k.native" ||
    { cat "$work/$k.native.err" >&2; fail "$k did not trace and render natively"; }
  [ -s "$work/$k.jvm" ] || fail "$k rendered nothing on the JVM"
  echo "PASS  trace: $k traced twice is one program (both backends)"

  if [ "$mode" = record ]; then
    cp "$work/$k.jvm" "$golden"
    echo "      recorded $k.mlir ($(wc -l < "$golden") lines)"
  fi
  [ -f "$golden" ] || fail "$k has no golden at $golden; run --record"
  cmp -s "$golden" "$work/$k.jvm" ||
    { diff -u "$golden" "$work/$k.jvm" >&2 || true; fail "$k: JVM text differs from $k.mlir"; }
  cmp -s "$golden" "$work/$k.native" ||
    { diff -u "$golden" "$work/$k.native" >&2 || true; fail "$k: native text differs from $k.mlir"; }
  echo "PASS  golden: $k.mlir matches on the JVM and natively ($(wc -l < "$golden") lines)"
done

# ---------------------------------------------------------------- mutants

# A mutant is a forked package with one anchor rewritten, built into its own
# project on both backends.
mutant_project() { # name, module, old, new
  local name="$1" module="$2" old="$3" new="$4"
  local pkg="$work/pkg-$name"
  fork_pkg "$pkg"
  local before after
  before=$(digest "$pkg/src/$module")
  patch_pkg "$pkg" "$module" "mutant $name" "$old" "$new"
  after=$(digest "$pkg/src/$module")
  echo "      $name: packages/tileir/src/$module md5 $before -> $after"
  project "$work/m-$name" "$pkg"
  build_native "$work/m-$name" "$work/m-$name.bin"
}

# Run one kernel under a mutant on both backends into $work/m-<name>.<kernel>.<backend>,
# recording each backend's exit code in $work/m-<name>.<kernel>.<backend>.rc.
mutant_run() { # name, kernel
  local name="$1" k="$2" rc
  rc=0; run_jvm "$work/m-$name" "$k" "$work/m-$name.$k.jvm" || rc=$?
  echo "$rc" > "$work/m-$name.$k.jvm.rc"
  rc=0; run_native "$work/m-$name.bin" "$k" "$work/m-$name.$k.native" || rc=$?
  echo "$rc" > "$work/m-$name.$k.native.rc"
}

# 1. The renderer drops the store's token operand. The kernel still traces
#    and renders (exit 0), and vadd's text differs from its golden on both
#    backends, in the store line and nowhere else.
mutant_project drop-store-token render.dawn \
  ', ${v} token=${tin} : ${vec(n, ptr_of(dtype))}, ${vec(n, dtype)} -> token' \
  ', ${v} : ${vec(n, ptr_of(dtype))}, ${vec(n, dtype)} -> token'
mutant_run drop-store-token vadd
for backend in jvm native; do
  out="$work/m-drop-store-token.vadd.$backend"
  [ "$(cat "$out.rc")" = 0 ] || { cat "$out.err" >&2; fail "drop-store-token: vadd did not run to completion on $backend"; }
  cmp -s "$here/vadd.mlir" "$out" && fail "drop-store-token mutant stayed green on $backend: vadd.mlir still matches"
  changed=$(diff "$here/vadd.mlir" "$out" | grep -c '^[<>]' || true)
  [ "$changed" = 2 ] || { diff "$here/vadd.mlir" "$out" >&2 || true; fail "drop-store-token: expected exactly the store line to move on $backend, got $changed changed line(s)"; }
  grep -q '^> .*store_ptr_tko weak' <(diff "$here/vadd.mlir" "$out") ||
    { diff "$here/vadd.mlir" "$out" >&2 || true; fail "drop-store-token: the moved line is not the store on $backend"; }
done
echo "PASS  mutant: drop-store-token (vadd.mlir red on both backends; exactly the store line moved)"

# 2. `load` hands the handler a fixed "f64" instead of its parameter's format.
#    The f32 kernel's entry declares f32 and its first load now claims f64, so
#    trace_kernel refuses it: non-zero exit, the refusal on stderr, nothing
#    rendered. vadd, whose parameters are f64, is untouched on both backends.
mutant_project load-dtype-f64 dev.dawn \
  't_load(position(p), param_dtype(p), i, n)' \
  't_load(position(p), "f64", i, n)'
mutant_run load-dtype-f64 vadd_f32
mutant_run load-dtype-f64 vadd
refusal='tileir: kernel `vadd_f32`: parameter 0 is declared f32, but a load reads it as f64'
for backend in jvm native; do
  out="$work/m-load-dtype-f64.vadd_f32.$backend"
  [ "$(cat "$out.rc")" != 0 ] || { cat "$out" >&2; fail "load-dtype-f64 mutant stayed green on $backend: vadd_f32 still renders (exit 0)"; }
  grep -Fq "$refusal" "$out.err" ||
    { cat "$out.err" >&2; fail "load-dtype-f64: vadd_f32 failed on $backend for something other than the dtype refusal"; }
  [ ! -s "$out" ] || fail "load-dtype-f64: vadd_f32 printed text before being refused on $backend"
  ctrl="$work/m-load-dtype-f64.vadd.$backend"
  if [ "$(cat "$ctrl.rc")" != 0 ] || ! cmp -s "$here/vadd.mlir" "$ctrl"; then
    cat "$ctrl.err" >&2
    fail "load-dtype-f64: vadd (all f64) should be untouched on $backend"
  fi
done
echo "PASS  mutant: load-dtype-f64 (vadd_f32 refused at trace time on both backends; vadd untouched)"

echo "tile golden ok"
