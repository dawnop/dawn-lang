#!/usr/bin/env bash
# The Tile IR goldens: packages/tileir's recording handler, renderer and
# bytecode writer against the .mlir and .tilebc files beside this script, on
# both backends, then the bytecode through `tileiras`, with a live mutant per
# claim the goldens make.
#
#   ./scripts/tile-golden/run.sh                     # compare; tileiras from $TILEIRAS or PATH
#   ./scripts/tile-golden/run.sh --tileiras <bin>    # compare with this assembler
#   ./scripts/tile-golden/run.sh --without-tileiras  # layers 0 only; every layer-1 line says SKIP
#   ./scripts/tile-golden/run.sh --record            # re-record the .mlir and .tilebc files
#
# Layers, as docs/tile-backend-design.md 6.2 numbers them:
#
#   0  the text and the bytes. They say whether the handler, the lowering,
#      the renderer and the writer changed, not whether what they emit is
#      right: both backends compile one Dawn source, so their agreement says
#      nothing about the spelling, and a golden re-recorded after a wrong
#      change is a wrong golden.
#   1  `tileiras --gpu-name <toolchain.txt gpu-name>` assembles each recorded
#      .tilebc into a cubin. Its exit code is the one verdict from outside
#      this repository: a misencoded operation, a type that is not a tile of
#      floats where addf wants one, an operand the flags promised and the
#      body did not carry, are all refused there and nowhere here. It is an
#      offline assembler (no GPU, no driver); install-tileiras.sh installs the
#      pinned one.
#
# Checks:
#
#   trace     -- kernels.dawn traces every kernel twice and panics if the two
#                records differ, before printing anything. The program
#                finishing is the assertion "a kernel traced twice is the same
#                program"; the goldens never see a non-deterministic trace.
#   golden    -- the rendered text of each kernel, on the JVM and natively,
#                equals <kernel>.mlir byte for byte.
#   bytecode  -- the encoded bytes of each kernel, on the JVM and natively,
#                equal <kernel>.tilebc byte for byte, and the version the
#                program writes into the header is toolchain.txt's.
#   assemble  -- tileiras is the version toolchain.txt pins and turns each
#                <kernel>.tilebc into an ELF cubin.
#   mutant    -- one rule removed from a copy of the package, the kernels run
#                against that copy on both backends, and one named kernel
#                required to go red in the way the rule predicts:
#
#     drop-store-token       the renderer omits the store's token operand
#                            -> vadd's text differs from its golden, exit 0
#     load-dtype-f64         `load` hands the handler "f64" instead of the
#                            parameter's format -> vadd_f32 is refused at
#                            trace time, vadd is untouched
#     make-token-as-iota     the writer encodes make_token with iota's opcode
#                            -> the text is untouched, the bytes differ, and
#                            tileiras refuses them: a token is not a tile
#     store-token-unwritten  the writer's store still flags a token operand
#                            but no longer writes it -> the text is untouched,
#                            the bytes are one byte short, and tileiras
#                            refuses them. The text golden cannot see this
#                            and the byte golden would be re-recorded over
#                            it; only layer 1 says it is wrong
#     f64-tag-as-i64         the writer's type table gives f64 the i64 tag
#                            -> the text is untouched, the bytes are the same
#                            length and differ, and tileiras refuses them:
#                            addf wants a float tile
#
# The anchor each mutant rewrites must match exactly once, so a refactor that
# moves it fails here instead of silently un-mutating (scripts/narrow-contract
# is the precedent for the whole shape). Without tileiras the three writer
# mutants still assert their byte-level halves and print SKIP for the verdict.
# shellcheck disable=SC2016  # the mutant anchors and the refusal are Dawn source, quoted verbatim on purpose
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/tile-golden"
kernels=(vadd vadd_f32)
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

mode=check
tileiras="${TILEIRAS:-}"
without_tileiras=no
while [ $# -gt 0 ]; do
  case "$1" in
    --record) mode=record ;;
    --tileiras) tileiras="$2"; shift ;;
    --without-tileiras) without_tileiras=yes ;;
    *) echo "usage: run.sh [--record] [--tileiras <bin> | --without-tileiras]" >&2; exit 2 ;;
  esac
  shift
done

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if command -v md5sum > /dev/null 2>&1; then
  digest() { md5sum "$1" | cut -d' ' -f1; }
else
  digest() { md5 -q "$1"; }
fi

toolchain_value() { # key
  awk -v k="$1" '$1 == k { print $2; exit }' "$here/toolchain.txt"
}
want_bytecode="$(toolchain_value bytecode)"
want_tileiras="$(toolchain_value tileiras)"
gpu_name="$(toolchain_value gpu-name)"
if [ -z "$want_bytecode" ] || [ -z "$want_tileiras" ] || [ -z "$gpu_name" ]; then
  fail "toolchain.txt must name bytecode, tileiras and gpu-name"
fi

# ---------------------------------------------------------------- tileiras

if [ "$without_tileiras" = yes ]; then
  tileiras=""
else
  [ -n "$tileiras" ] || tileiras="$(command -v tileiras || true)"
  [ -n "$tileiras" ] ||
    fail "no tileiras: run scripts/tile-golden/install-tileiras.sh <dir> and pass --tileiras <path> (or set TILEIRAS), or pass --without-tileiras to skip layer 1"
  [ -x "$tileiras" ] || fail "tileiras is not executable: $tileiras"
  "$tileiras" --version > "$work/tileiras.version" 2>&1 ||
    { cat "$work/tileiras.version" >&2; fail "tileiras --version failed"; }
  grep -q "V${want_tileiras}\b" "$work/tileiras.version" ||
    { cat "$work/tileiras.version" >&2; fail "tileiras is not the pinned ${want_tileiras} (toolchain.txt)"; }
  echo "PASS  tileiras: $tileiras is V${want_tileiras}"
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

run_jvm() { # project, out, args... ; returns the program's exit code
  local project="$1" out="$2"
  shift 2
  "$root/bin/dawn" run "$project" -- "$@" > "$out" 2> "$out.err"
}

build_native() { # project, bin
  "$root/bin/dawn" __emitc "$1" -o "$2.c" > "$2.emit" 2>&1 ||
    { cat "$2.emit" >&2; fail "native emit failed for $1"; }
  "$cc_bin" -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread \
    -I "$root/runtime/c" -o "$2" "$2.c" "$rt_obj" -lm > "$2.cc" 2>&1 ||
    { cat "$2.cc" >&2; fail "native compile failed for $1"; }
}

run_native() { # bin, out, args... ; returns the program's exit code
  local bin="$1" out="$2"
  shift 2
  "$bin" "$@" > "$out" 2> "$out.err"
}

is_elf() { # file
  [ "$(head -c 4 "$1" | od -An -tx1 | tr -d ' \n')" = 7f454c46 ]
}

# Assemble one bytecode file; the exit code is tileiras's, its output is in
# <out>.log and the cubin (if any) in <out>.
assemble() { # tilebc, out
  "$tileiras" --gpu-name "$gpu_name" -o "$2" "$1" > "$2.log" 2>&1
}

# ---------------------------------------------------------------- trace + golden

project "$work/clean" "$root/packages/tileir"
build_native "$work/clean" "$work/clean.bin"

run_jvm "$work/clean" "$work/version.jvm" --bytecode-version ||
  { cat "$work/version.jvm.err" >&2; fail "kernels --bytecode-version failed on the JVM"; }
[ "$(cat "$work/version.jvm")" = "$want_bytecode" ] ||
  fail "the writer says bytecode $(cat "$work/version.jvm") but toolchain.txt says $want_bytecode; the two move together"
echo "PASS  version: the writer and toolchain.txt agree on bytecode $want_bytecode"

for k in "${kernels[@]}"; do
  golden="$here/$k.mlir"
  bc_golden="$here/$k.tilebc"
  run_jvm "$work/clean" "$work/$k.jvm" "$k" ||
    { cat "$work/$k.jvm.err" >&2; fail "$k did not trace and render on the JVM"; }
  run_native "$work/clean.bin" "$work/$k.native" "$k" ||
    { cat "$work/$k.native.err" >&2; fail "$k did not trace and render natively"; }
  [ -s "$work/$k.jvm" ] || fail "$k rendered nothing on the JVM"
  run_jvm "$work/clean" "$work/$k.jvm.out" "$k" --bytecode "$work/$k.jvm.tilebc" ||
    { cat "$work/$k.jvm.out.err" >&2; fail "$k did not trace and encode on the JVM"; }
  run_native "$work/clean.bin" "$work/$k.native.out" "$k" --bytecode "$work/$k.native.tilebc" ||
    { cat "$work/$k.native.out.err" >&2; fail "$k did not trace and encode natively"; }
  [ -s "$work/$k.jvm.tilebc" ] || fail "$k encoded nothing on the JVM"
  echo "PASS  trace: $k traced twice is one program (both backends, text and bytecode)"

  if [ "$mode" = record ]; then
    cp "$work/$k.jvm" "$golden"
    cp "$work/$k.jvm.tilebc" "$bc_golden"
    echo "      recorded $k.mlir ($(wc -l < "$golden") lines) and $k.tilebc ($(wc -c < "$bc_golden") bytes)"
  fi
  [ -f "$golden" ] || fail "$k has no golden at $golden; run --record"
  [ -f "$bc_golden" ] || fail "$k has no bytecode golden at $bc_golden; run --record"
  cmp -s "$golden" "$work/$k.jvm" ||
    { diff -u "$golden" "$work/$k.jvm" >&2 || true; fail "$k: JVM text differs from $k.mlir"; }
  cmp -s "$golden" "$work/$k.native" ||
    { diff -u "$golden" "$work/$k.native" >&2 || true; fail "$k: native text differs from $k.mlir"; }
  echo "PASS  golden: $k.mlir matches on the JVM and natively ($(wc -l < "$golden") lines)"
  cmp -s "$bc_golden" "$work/$k.jvm.tilebc" ||
    { cmp "$bc_golden" "$work/$k.jvm.tilebc" >&2 || true; fail "$k: JVM bytecode differs from $k.tilebc"; }
  cmp -s "$bc_golden" "$work/$k.native.tilebc" ||
    { cmp "$bc_golden" "$work/$k.native.tilebc" >&2 || true; fail "$k: native bytecode differs from $k.tilebc"; }
  echo "PASS  bytecode: $k.tilebc matches on the JVM and natively ($(wc -c < "$bc_golden") bytes)"

  if [ -n "$tileiras" ]; then
    assemble "$bc_golden" "$work/$k.cubin" ||
      { cat "$work/$k.cubin.log" >&2; fail "$k: tileiras refused $k.tilebc"; }
    if ! [ -s "$work/$k.cubin" ] || ! is_elf "$work/$k.cubin"; then
      fail "$k: tileiras exited 0 but wrote no ELF cubin"
    fi
    echo "PASS  assemble: $k.tilebc -> cubin ($(wc -c < "$work/$k.cubin") bytes, tileiras V$want_tileiras, $gpu_name)"
  else
    echo "SKIP  assemble: $k.tilebc not handed to tileiras (--without-tileiras)"
  fi
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

# Run one kernel's text under a mutant on both backends into
# $work/m-<name>.<kernel>.<backend>, recording each backend's exit code in
# $work/m-<name>.<kernel>.<backend>.rc.
mutant_run() { # name, kernel
  local name="$1" k="$2" rc
  rc=0; run_jvm "$work/m-$name" "$work/m-$name.$k.jvm" "$k" || rc=$?
  echo "$rc" > "$work/m-$name.$k.jvm.rc"
  rc=0; run_native "$work/m-$name.bin" "$work/m-$name.$k.native" "$k" || rc=$?
  echo "$rc" > "$work/m-$name.$k.native.rc"
}

# The same for the bytecode, into $work/m-<name>.<kernel>.<backend>.tilebc.
mutant_run_bytecode() { # name, kernel
  local name="$1" k="$2" rc
  rc=0; run_jvm "$work/m-$name" "$work/m-$name.$k.jvm.out" "$k" --bytecode "$work/m-$name.$k.jvm.tilebc" || rc=$?
  echo "$rc" > "$work/m-$name.$k.jvm.tilebc.rc"
  rc=0; run_native "$work/m-$name.bin" "$work/m-$name.$k.native.out" "$k" --bytecode "$work/m-$name.$k.native.tilebc" || rc=$?
  echo "$rc" > "$work/m-$name.$k.native.tilebc.rc"
}

# 1. The renderer drops the store's token operand. The kernel still traces
#    and renders (exit 0), and vadd's text differs from its golden on both
#    backends, in the store line and nowhere else.
mutant_project drop-store-token render.dawn \
  ', ${name(value)} token=${name(tok_in)} : ${ty(ptr_ty)}, ${ty(val_ty)} -> token' \
  ', ${name(value)} : ${ty(ptr_ty)}, ${ty(val_ty)} -> token'
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

# The length varint of the Func section: byte 13, after the 12-byte header
# and the section id. One byte while the section is under 128 bytes, which
# the two kernels' are; a bigger kernel would need the varint decoded.
func_len() { # tilebc
  od -An -tu1 -j 13 -N 1 "$1" | tr -d ' \n'
}

# A writer mutant: the text of vadd is untouched on both backends (the
# renderer was not edited), the bytes differ from vadd.tilebc on both and
# agree with each other, and tileiras refuses them with the given fragment
# in its output. <shape> says how the mutant's file relates to the golden's:
# `same-size` (a value changed in place) or `func-one-short` (the function
# section lost one byte; the file itself need not shrink, the next section's
# alignment padding absorbs it).
writer_mutant_checks() { # name, shape, fragment
  local name="$1" shape="$2" fragment="$3" backend out golden_size mutant_size golden_func
  mutant_run "$name" vadd
  mutant_run_bytecode "$name" vadd
  golden_size=$(wc -c < "$here/vadd.tilebc")
  golden_func=$(func_len "$here/vadd.tilebc")
  for backend in jvm native; do
    out="$work/m-$name.vadd.$backend"
    if [ "$(cat "$out.rc")" != 0 ] || ! cmp -s "$here/vadd.mlir" "$out"; then
      cat "$out.err" >&2
      fail "$name: the renderer was not edited, so vadd.mlir should still match on $backend"
    fi
    out="$work/m-$name.vadd.$backend.tilebc"
    [ "$(cat "$out.rc")" = 0 ] || { cat "$work/m-$name.vadd.$backend.out.err" >&2; fail "$name: vadd did not encode on $backend"; }
    cmp -s "$here/vadd.tilebc" "$out" && fail "$name mutant stayed green on $backend: vadd.tilebc still matches"
    mutant_size=$(wc -c < "$out")
    case "$shape" in
      same-size)
        [ "$mutant_size" = "$golden_size" ] ||
          fail "$name: vadd.tilebc is $golden_size bytes and the mutant's is $mutant_size on $backend; expected the same size" ;;
      func-one-short)
        [ "$(func_len "$out")" = "$((golden_func - 1))" ] ||
          fail "$name: the golden's Func section is $golden_func bytes and the mutant's is $(func_len "$out") on $backend; expected one byte fewer" ;;
      *) fail "writer_mutant_checks: unknown shape $shape" ;;
    esac
  done
  cmp -s "$work/m-$name.vadd.jvm.tilebc" "$work/m-$name.vadd.native.tilebc" ||
    fail "$name: the two backends disagree on the mutant's bytes"
  if [ -n "$tileiras" ]; then
    if assemble "$work/m-$name.vadd.jvm.tilebc" "$work/m-$name.cubin"; then
      fail "$name mutant stayed green: tileiras accepted the mutant's bytecode"
    fi
    grep -Fq "$fragment" "$work/m-$name.cubin.log" ||
      { cat "$work/m-$name.cubin.log" >&2; fail "$name: tileiras refused the bytecode for something other than: $fragment"; }
    echo "PASS  mutant: $name (vadd.mlir untouched, vadd.tilebc red on both backends; tileiras: $fragment)"
  else
    echo "PASS  mutant: $name (vadd.mlir untouched, vadd.tilebc red on both backends)"
    echo "SKIP  mutant: $name not handed to tileiras (--without-tileiras)"
  fi
}

# 3. The writer encodes make_token with iota's opcode. Same length, one byte
#    differs, and the verifier behind the reader says a token is not a tile.
mutant_project make-token-as-iota bytecode.dawn \
  'const OP_MAKE_TOKEN: Int = 0x44' \
  'const OP_MAKE_TOKEN: Int = 0x3A'
writer_mutant_checks make-token-as-iota same-size \
  "'cuda_tile.iota' op result #0 must be tile of"

# 4. The writer's store still sets the token-present flag but no longer
#    writes the operand. vadd has one store and its token index is one
#    varint byte, so the function section is one byte short (the file is
#    not: the constant section's alignment padding grows by one); the reader
#    takes the next byte, `return`'s opcode 0x5C, for the token's value index
#    and refuses it: 92 is past the 27 values (3 parameters, 24 results).
mutant_project store-token-unwritten bytecode.dawn \
  'emit_ref(emit_ref(emit_ref(w1, ptrs), value), tok_in)' \
  'emit_ref(emit_ref(w1, ptrs), value)'
writer_mutant_checks store-token-unwritten func-one-short \
  "operand index 92 out of bounds (size=27) for token segment"

# 5. The writer's type table gives f64 the i64 tag. Same length, the type
#    section differs, and the verifier refuses addf over an integer tile.
mutant_project f64-tag-as-i64 bytecode.dawn \
  '  "f64" -> 9' \
  '  "f64" -> 4'
writer_mutant_checks f64-tag-as-i64 same-size \
  "'cuda_tile.addf' op operand #0 must be tile of f16 or bf16 or f32 or f64 values, but got '!cuda_tile.tile<128xi64>'"

echo "tile golden ok"
