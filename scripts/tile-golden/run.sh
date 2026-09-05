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
#   ./scripts/tile-golden/run.sh --shard 1/3         # one round-robin slice of matrix.txt
#   ./scripts/tile-golden/run.sh --only <item>       # one kernel or one mutant, nothing else
#
#   ITEM_TIMES=<file> ./scripts/tile-golden/run.sh   # also append `<item> <seconds>`
#                                                    # per work item, for balancing the
#                                                    # shards (matrix.txt says how)
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
#                <kernel>.tilebc into an ELF cubin whose symbol table has a
#                global function named after the kernel.
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
#     loop-token-not-carried the handler no longer continues from the loop's
#                            token result after the loop, so the store after
#                            sum's loop names the token of a load inside it
#                            -> sum is refused when lowered (a loop body's
#                            value is not visible after the loop), nothing
#                            rendered; vadd, which has no loop, is untouched
#     region-stack-pop       the handler pops the region stack the wrong way
#                            round: what the loop body issued stays outside
#                            and what came before it goes inside -> sum is
#                            refused when lowered (the body's load names the
#                            loop's carried token before the loop defines
#                            it), nothing rendered; vadd untouched
#     for-results-not-rolled-back
#                            the writer keeps counting after a loop's block
#                            instead of rolling the value index back before
#                            numbering the loop's results -> sum's text is
#                            untouched, its bytes are the same length and
#                            differ, and tileiras refuses them: the store
#                            after the loop names an index past the last
#                            value
#     addf-no-rounding       the renderer drops addf's `rounding<nearest_even>`
#                            -> vadd_bf16's text differs from its golden in
#                            the addf line and nowhere else, exit 0. The
#                            attribute is the theorem's precondition (docs
#                            3.2): without it the device's bf16 sum need not
#                            be narrow.round_bf16's. The writer's half of the
#                            same claim (the rounding flag) is not a mutant
#                            here: tileiras accepts every mode, so only the
#                            device (scripts/tile-gpu-diff) could see it
#     load-pad-flag-as-token the writer gives a masked load's padding value
#                            the token's flag bit, so the flags promise one
#                            operand and the body carries another -> the text
#                            is untouched, the bytes are the same length and
#                            differ, and tileiras loses the stream. The flag
#                            bits are the whole of what says which optional
#                            operands a memory operation carries
#     ftoi-rounds-instead-of-truncates
#                            the writer gives `ftoi` the nearest-even
#                            rounding mode -> int_ops's text is untouched,
#                            its bytes are the same length and differ, and
#                            tileiras names the operation: only
#                            `nearest_int_to_zero` is supported. Written as
#                            a layer-2 mutant and measured its way here
#     bf16-tag-as-i16        the writer's type table gives bf16 the i16 tag
#                            -> vadd_bf16's text is untouched, its bytes are
#                            the same length and differ, and tileiras refuses
#                            them: addf wants a float tile. The bf16 twin of
#                            f64-tag-as-i64; a tag one off the other way
#                            (f16, 5) would assemble and only the device
#                            could tell
#     trig-extra-flags       the writer gives `sin` a flags varint, which is
#                            one byte none of knife T1's seven operations
#                            has -> trig_sweep's text is untouched, its
#                            bytes are one byte LONGER, and tileiras cannot
#                            parse the body: every operand index after the
#                            extra byte is read one place out of step. This
#                            is the whole reason those seven are on
#                            `float_op_has_flags`'s exclusion list, and
#                            nothing below layer 1 can see the difference
#     i16-tag-as-bf16        the writer's type table gives i16 the bf16 tag
#                            -> dtype_i16's text is untouched, its bytes are
#                            the same length and differ, and tileiras
#                            refuses them: addi wants an integer tile. The
#                            i16 twin of f64-tag-as-i64 and bf16-tag-as-i16,
#                            and the tag it takes is the OTHER two-byte one,
#                            so the file cannot be refused for its length
#     i64-payload-four-bytes the writer lays an i64 constant down four bytes
#                            wide instead of eight -> dtype_i64's text is
#                            untouched (the renderer prints the value, not
#                            the blob) and the constant section is SHORT, so
#                            the reader measures the blob against the type
#                            and refuses it. This is the type table's other
#                            half: a tag says what a tile holds and a
#                            payload has to be that wide
#     e4m3-tag-as-i8         the writer's type table gives f8E4M3FN the i8
#                            tag, which is the same one byte -> dtype_e4m3's
#                            text is untouched, its bytes are the same
#                            length and differ, and tileiras refuses them:
#                            ftof wants a float tile. It is the one mutant
#                            of the three fp8 tags, and what it shows is
#                            that the tag table is load-bearing for them at
#                            all; f8E5M2's own tag cannot be told from
#                            f8E4M3FN's below layer 2 (measured: swapping
#                            the two assembles clean), and no device this
#                            tree can reach accepts either
#     e8m0-rounding-as-nearest-even
#                            the writer stops keying ftof's rounding mode on
#                            its target and writes nearest_even everywhere
#                            -> dtype_e8m0's bytes are the same length and
#                            differ, and tileiras names the format: only
#                            `zero` and `positive_inf` are supported for
#                            f8E8M0FNU
#     e8m0-tag-as-f8e5m2     the same sentence from the other side: the
#                            writer gives f8E8M0FNU the f8E5M2 tag, so a
#                            `rounding<zero>` that was legal for the one
#                            target is illegal for the other and tileiras
#                            says `Only 'nearest_even' is supported`. The
#                            two together are what makes ftof_rounding a
#                            claim rather than a table
#     loop-carried-not-rolled-back
#                            the writer keeps counting after a `loop`'s
#                            block instead of rolling the value index back
#                            before numbering the loop's results ->
#                            loop_count's text is untouched, its bytes are
#                            the same length and differ, and tileiras
#                            refuses them: the store after the loop names
#                            an index past the last value. The `loop` twin
#                            of for-results-not-rolled-back, and a SEPARATE
#                            anchor rather than the same one: the two
#                            regions are written by two arms, and a reader
#                            who copied `for`'s arm without its last line
#                            would pass that mutant and fail this one
#     break-values-missing   the writer gives `break` an operand count of
#                            zero and writes none -> loop_count's text is
#                            untouched, the file is the same length (the
#                            Func section lost two operand indices and the
#                            padding after it took them back) and tileiras
#                            refuses it by TYPE: a break's operands must
#                            correspond to the parent loop's results. What
#                            `break` carries IS the loop's answer, and this
#                            is the layer at which that is checkable
#     scan-result-drops-the-dim
#                            the writer gives a `scan` the result types a
#                            `reduce` would have, the scanned dimension
#                            dropped -> prefix_sum's text is untouched, its
#                            bytes are the same length and differ, and
#                            tileiras refuses them: a scan's result has the
#                            shape of its operand. That is the one thing
#                            that separates the two operations' encodings
#                            beyond the opcode and the `reverse` byte, and
#                            layer 0 cannot see it (the renderer prints the
#                            types it was handed)
#
#     atomic-rmw-claims-weak-ordering
#                            the writer gives an `atomic_rmw_tko` the `weak`
#                            memory ordering (0) instead of `relaxed` (1)
#                            -> histogram's text is untouched (the renderer
#                            spells `relaxed` from its own table), its bytes
#                            are the same length and differ, and tileiras
#                            refuses them: `weak` is the ONE variant the
#                            atomics do not accept (Ops.td's OnlyVariants).
#                            `weak` means "assume nobody else touches this
#                            location", which is the negation of what an
#                            atomic is for, and the dialect refuses to let a
#                            kernel say both
#     overflow-attr-not-written
#                            the writer stops writing the `overflow`
#                            attribute of the three assumptions knife T4
#                            added, so the reader takes the first operand
#                            index for the enum -> attr_overflow's text is
#                            untouched, its Func section is three bytes
#                            short, and tileiras answers `invalid integer
#                            value for enum type: 18`. The three values
#                            are assumptions the COMPILER may make and no
#                            corpus can see them, so this is where they
#                            are covered and the ledger says so
#     atomic-memory-attrs-swapped
#                            the writer swaps the memory ordering and the
#                            memory scope of the three suffixed atomic
#                            modes, which is the copy-paste error a table
#                            of triples invites -> attr_memsem's text is
#                            untouched (the renderer has its own table),
#                            its bytes are the same length and differ, and
#                            tileiras refuses them: 3 is not a memory
#                            scope. The same anchor carries all six values
#                            (three orderings, three scopes)
#     rmw-addf-as-add        the writer gives the `addf` atomic mode the
#                            integer `add`'s enum value -> attr_addf's
#                            text is untouched, its bytes are the same
#                            length and differ, and tileiras refuses them:
#                            `add` works only with i32 and i64. The two
#                            modes are one enum and neighbours in it, so
#                            this is the one byte between an integer sum
#                            and a float one
#     atomic-cas-writes-an-rmw-mode
#                            the writer gives `atomic_cas_tko` a `mode`
#                            byte, which is the copy of the read-modify-write
#                            block above that a reader of these two
#                            operations is one keystroke away from ->
#                            cas_swap's text is untouched, its bytes are ONE
#                            LONGER, and tileiras loses the stream: every
#                            operand after the mode is read one place out of
#                            step. The two atomics differ in exactly this
#                            attribute and in the operand count, and this is
#                            the half of that a byte golden would simply be
#                            re-recorded over
#
# Sharding: the work items are the kernels and the mutants in one list, which
# matrix.txt records. Both halves cost real time -- one local run measured
# 204s for 51 kernels (102 JVM starts, and nothing else) against 175s for
# the 12 mutants (a native rebuild each) -- so splitting by kind would leave
# one job carrying the slower half. `--shard I/N` takes every Nth item of the
# mixed list instead, which also spreads the outliers (`reverse` alone costs
# five average kernels).
#
# What is divided is the items, never a verdict. A kernel's four runs, its
# two goldens and its assembly all happen inside one shard, and a mutant's
# comparisons are against the recorded goldens on disk rather than against
# this shard's own kernel output -- so a mutant and the clean kernel it names
# may land in different shards and the conjunction still holds, as long as
# every item runs somewhere. That last clause is the one new way to be wrong,
# and it is the only thing a shard cannot vouch for about itself: each writes
# down what it ran and scripts/mutant-coverage/check.py holds the union to
# matrix.txt.
#
# The anchor each mutant rewrites must match exactly once, so a refactor that
# moves it fails here instead of silently un-mutating (scripts/narrow-contract
# is the precedent for the whole shape). Without tileiras the three writer
# mutants still assert their byte-level halves and print SKIP for the verdict.
# shellcheck disable=SC2016  # the mutant anchors and the refusal are Dawn source, quoted verbatim on purpose
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
here="$root/scripts/tile-golden"
kernels=(
  dot_f16 lora_out ssm_scan geglu
  token_embed attn_scores sum_diff matmul_i8
  erf_sweep gae seg_scan compact
  sort_rank histogram scatter_perm f16_ops
  matmul_f16 lora_base reverse batched_matmul_f16
  max_subarray prefix_sum merge_rank lin_attn_s
  attn_bwd_mmt silu lora_hidden mse
  argmax lin_attn_out cas_swap conv2d
  reduce_sum softmax linrec vadd_tail
  xattn_scores matmul xattn_context ppo_loss
  monte_carlo jacobi rms_norm dot
  vadd_bf16 elemops dpo_loss copy
  mathops gqa_context matpow_step swiglu_down
  sigmoid relu kv_context kv_scores
  attn_bwd_ds invert grpo_row foldif
  ols_gram int_ops vadd fused_rms_norm
  kmeans_assign ols_beta gqa_scores ols_elim
  max_pool grpo_adv vadd_f32 leaky_relu
  subarray_sum layer_norm sum count_eq
  clip rgb_gray kmeans_centroid group_norm
  gaussian_blur transpose_tail attn_softmax conv3d
  depthwise_conv1d batched_matmul attn_context nearest_idx
  swiglu_proj batch_norm transpose rainbow
  swiglu_act agent_step matvec interleave
  attn_decay mha_context conv1d attn_causal
  cce_row cce_mean apsp_step mha_scores
  dequant attn_alibi subarray_sum2d attn_sinks
  swiglu_half subarray_sum3d attn_window
  gpt_ln gpt_qkv gpt_scores gpt_context
  gpt_dense gpt_fc gpt_gelu gpt_down
  llama_rms llama_qkv llama_rope llama_scores
  llama_out llama_ffn llama_down
  trig_sweep rope shape_ops grid_stride
  token_join ptr_roundtrip ptr_recast
  dtype_i16 dtype_i64 dtype_tf32 dtype_e4m3
  dtype_e5m2 dtype_e8m0
  loop_count loop_bound loop_until loop_none
  attr_round attr_nan attr_ftz attr_approx
  attr_overflow attr_memsem attr_addf attr_ucmp)
cc_bin="${CC:-cc}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# shellcheck source=scripts/mutant-coverage/shard.sh
source "$root/scripts/mutant-coverage/shard.sh"
shard_parse "$@"
if [ "${#shard_rest[@]}" -gt 0 ]; then set -- "${shard_rest[@]}"; else set --; fi

mode=check
tileiras="${TILEIRAS:-}"
without_tileiras=no
only=
while [ $# -gt 0 ]; do
  case "$1" in
    --record) mode=record ;;
    --tileiras) tileiras="$2"; shift ;;
    --without-tileiras) without_tileiras=yes ;;
    --only) only="$2"; shift ;;
    *) echo "usage: run.sh [--record] [--shard I/N] [--only <item>] [--tileiras <bin> | --without-tileiras]" >&2; exit 2 ;;
  esac
  shift
done

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# The executable work items, in run order: the kernels above, then the mutants
# in the order their blocks appear below. matrix.txt is the persistent record
# scripts/mutant-coverage/check.py reads; the two are held equal in both
# directions here, so an item added to one place cannot go missing from the
# other, and run_item holds the running order to it as well.
mutants=(
  drop-store-token
  load-dtype-f64
  make-token-as-iota
  store-token-unwritten
  f64-tag-as-i64
  loop-token-not-carried
  region-stack-pop
  for-results-not-rolled-back
  addf-no-rounding
  bf16-tag-as-i16
  load-pad-flag-as-token
  ftoi-rounds-instead-of-truncates
  scan-result-drops-the-dim
  atomic-rmw-claims-weak-ordering
  atomic-cas-writes-an-rmw-mode
  trig-extra-flags
  join-tokens-operand-count-wrong
  cat-dim-swapped
  int-to-ptr-as-ptr-to-int
  ptr-to-int-as-int-to-ptr
  ptr-to-ptr-as-bitcast
  i16-tag-as-bf16
  i64-payload-four-bytes
  e4m3-tag-as-i8
  e8m0-rounding-as-nearest-even
  e8m0-tag-as-f8e5m2
  loop-carried-not-rolled-back
  break-values-missing
  overflow-attr-not-written
  atomic-memory-attrs-swapped
  rmw-addf-as-add
)
items=("${kernels[@]}" "${mutants[@]}")

printf '%s\n' "${items[@]}" > "$work/matrix.executable"
grep -v '^#' "$here/matrix.txt" | grep -v '^$' > "$work/matrix.recorded" || true
cmp -s "$work/matrix.executable" "$work/matrix.recorded" || {
  diff -u "$work/matrix.recorded" "$work/matrix.executable" >&2 || true
  fail "matrix.txt and the runner's executable item list disagree"
}

if [ -n "$only" ]; then
  printf '%s\n' "${items[@]}" | grep -qxF "$only" || fail "no kernel or mutant named $only"
  # One item is not a shard's worth of coverage, so it must not be filed as one.
  MUTANT_COVERAGE_DIR=
fi
if [ "$mode" = record ] && [ "$shard_total" != 1 ]; then
  fail "--record re-records every golden, so it cannot run on one shard of the matrix"
fi

shard_begin tile-golden

# True when this shard -- and --only, if given -- is the one to run the named
# item. Called once per item in run order, which is also how the running order
# is held to matrix.txt: round-robin reads positions off that file, so a block
# moved without the list moving with it would silently change which shard runs
# it, and no PASS line would look any different.
item_position=0

# Per-item wall clock, when ITEM_TIMES names a file: the deal in matrix.txt is
# only as good as the costs it was computed from, and the last two knives
# balanced that table by eye and got it wrong. One tick per run_item plus one
# at the end, so each item's line is the time from its own start to the next
# one's. Off by default and free when off.
_last_item=""
_last_time=0
_item_tick() { # name-just-finished-or-empty
  [ -n "${ITEM_TIMES:-}" ] || return 0
  local now=${EPOCHREALTIME/,/.}
  if [ -n "$_last_item" ]; then
    awk -v n="$_last_item" -v a="$_last_time" -v b="$now" 'BEGIN{printf "%s %.2f\n", n, b-a}' >> "$ITEM_TIMES"
  fi
  _last_item="$1"
  _last_time=$now
}
run_item() { # name
  local name="$1" position=$item_position
  _item_tick "$name"
  item_position=$(( item_position + 1 ))
  [ "${items[$position]}" = "$name" ] ||
    fail "run order: matrix position $position is ${items[$position]}, the runner reached $name"
  if [ -n "$only" ]; then
    [ "$name" = "$only" ] || return 1
  elif shard_skips "$position"; then
    return 1
  fi
  shard_record "$name"
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

# The cubin's symbol table has a GLOBAL FUNC named <name>: the kernel came
# out the other end under its own name. ELF64 little-endian, read directly
# so the check does not depend on binutils being installed.
has_global_func() { # cubin, name
  python3 - "$1" "$2" <<'PY'
import struct
import sys

data = open(sys.argv[1], "rb").read()
want = sys.argv[2].encode()
shoff = struct.unpack_from("<Q", data, 0x28)[0]
shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
for _name, kind, _flags, _addr, off, size, link, _info, _align, entsize in sections:
    if kind != 2:  # SHT_SYMTAB
        continue
    strtab_off = sections[link][4]
    for j in range(size // entsize):
        st_name, st_info, _other, _shndx, _value, _size = struct.unpack_from("<IBBHQQ", data, off + j * entsize)
        end = data.index(b"\0", strtab_off + st_name)
        if data[strtab_off + st_name:end] == want and st_info & 0xF == 2 and st_info >> 4 == 1:
            raise SystemExit(0)
raise SystemExit(1)
PY
}

# The --gpu-name a kernel is assembled for. toolchain.txt's `gpu-name` is
# the machine's own (sm_86) and every kernel but three uses it.
#
# The three are knife T3's fp8 kernels, and the number here is a
# MEASUREMENT: tileiras 13.3.36 refuses all three fp8 types at sm_86 AND at
# sm_89 with
#
#   error: Incompatibility with architecture 'sm_86': unsupported type
#     'f8E4M3FN'
#   error: failed to compile Tile IR program
#
# and takes them from sm_100. So layer 1 for those three is
#
#   tileiras --gpu-name sm_100 -o <out> scripts/tile-golden/dtype_e4m3.tilebc
#
# which is what runs below, and layer 2 for them is impossible on this
# machine's RTX 3080 (scripts/tileir-features/types.txt carries the named
# exemption). Nothing about the BYTES differs: the .tilebc goldens are
# recorded and compared exactly as every other kernel's are, and only the
# assembler's target changes.
kernel_arch() { # kernel
  case "$1" in
    dtype_e4m3|dtype_e5m2|dtype_e8m0) echo sm_100 ;;
    *) echo "$gpu_name" ;;
  esac
}

# Assemble one bytecode file; its output is in <out>.log and the cubin (if
# any) in <out>.
#
# The verdict is the exit code AND an empty error stream. tileiras can exit
# 0 while refusing something: measured on knife 7b, a `tanh` carrying
# `rounding<nearest_even>` (a mode an f64 tanh does not accept) writes a
# cubin, exits 0 and prints `'cuda_tile.tanh' op invalid rounding mode
# specified, expect one of [approx, full]`. Reading only the exit code would
# have let that through, and layer 1 is the only place it could be seen.
assemble() { # tilebc, out, gpu-name
  "$tileiras" --gpu-name "$3" -o "$2" "$1" > "$2.log" 2>&1 || return 1
  ! grep -q '^error:' "$2.log"
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
  run_item "$k" || continue
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
    arch="$(kernel_arch "$k")"
    assemble "$bc_golden" "$work/$k.cubin" "$arch" ||
      { cat "$work/$k.cubin.log" >&2; fail "$k: tileiras refused $k.tilebc at $arch"; }
    if ! [ -s "$work/$k.cubin" ] || ! is_elf "$work/$k.cubin"; then
      fail "$k: tileiras exited 0 but wrote no ELF cubin"
    fi
    has_global_func "$work/$k.cubin" "$k" || fail "$k: the cubin has no GLOBAL FUNC named $k"
    echo "PASS  assemble: $k.tilebc -> cubin ($(wc -c < "$work/$k.cubin") bytes, FUNC GLOBAL $k, tileiras V$want_tileiras, $arch)"
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
if run_item drop-store-token; then
  mutant_project drop-store-token render.dawn \
    ' token=${name(tok_in)} : ${ty(ptr_ty)}, ${ty(val_ty)}${opt_ty(mask, mask_ty)} -> token' \
    ' : ${ty(ptr_ty)}, ${ty(val_ty)}${opt_ty(mask, mask_ty)} -> token'
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
fi

# 2. `load` hands the handler a fixed "f64" instead of its parameter's format.
#    The f32 kernel's entry declares f32 and its first load now claims f64, so
#    trace_kernel refuses it: non-zero exit, the refusal on stderr, nothing
#    rendered. vadd, whose parameters are f64, is untouched on both backends.
if run_item load-dtype-f64; then
  mutant_project load-dtype-f64 dev.dawn \
    't_load(position(p), param_dtype(p), i, shape, strides, none, none)' \
    't_load(position(p), "f64", i, shape, strides, none, none)'
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
fi

# The length varint of the Func section: it starts at byte 13, after the
# 12-byte header and the section id, and it is LEB128. One byte while the
# section is under 128 bytes, which the first kernels to use this were;
# knife T4's attr_overflow is 200 bytes of function, so the varint is
# decoded properly rather than read as one byte.
func_len() { # tilebc
  python3 - "$1" <<'PY'
import sys

data = open(sys.argv[1], "rb").read()
value = 0
shift = 0
i = 13
while True:
    byte = data[i]
    value |= (byte & 0x7F) << shift
    if byte < 0x80:
        break
    shift += 7
    i += 1
print(value)
PY
}

# A writer mutant: the text of <kernel> is untouched on both backends (the
# renderer was not edited), the bytes differ from <kernel>.tilebc on both
# and agree with each other, and tileiras refuses them with the given
# fragment in its output. <shape> says how the mutant's file relates to the
# golden's: `same-size` (the file is the same length: a value changed in
# place, or a Func section that lost bytes the padding after it took back),
# `func-<n>-short` / `func-<n>-long` (the function section lost or gained
# exactly n bytes; the file itself need not change by the same amount
# either way, the next section's alignment padding absorbs part of it) or
# `file-shorter` (the whole file lost bytes, which is what a constant BLOB
# written too narrow does: its section shrinks and no padding puts it
# back).
writer_mutant_checks() { # name, kernel, shape, fragment
  local name="$1" k="$2" shape="$3" fragment="$4" backend out golden_size mutant_size golden_func delta want
  mutant_run "$name" "$k"
  mutant_run_bytecode "$name" "$k"
  golden_size=$(wc -c < "$here/$k.tilebc")
  golden_func=$(func_len "$here/$k.tilebc")
  for backend in jvm native; do
    out="$work/m-$name.$k.$backend"
    if [ "$(cat "$out.rc")" != 0 ] || ! cmp -s "$here/$k.mlir" "$out"; then
      cat "$out.err" >&2
      fail "$name: the renderer was not edited, so $k.mlir should still match on $backend"
    fi
    out="$work/m-$name.$k.$backend.tilebc"
    [ "$(cat "$out.rc")" = 0 ] || { cat "$work/m-$name.$k.$backend.out.err" >&2; fail "$name: $k did not encode on $backend"; }
    cmp -s "$here/$k.tilebc" "$out" && fail "$name mutant stayed green on $backend: $k.tilebc still matches"
    mutant_size=$(wc -c < "$out")
    case "$shape" in
      same-size)
        [ "$mutant_size" = "$golden_size" ] ||
          fail "$name: $k.tilebc is $golden_size bytes and the mutant's is $mutant_size on $backend; expected the same size" ;;
      func-*-short | func-*-long)
        delta="${shape#func-}"
        delta="${delta%-short}"
        delta="${delta%-long}"
        case "$delta" in
          one) delta=1 ;;
          two) delta=2 ;;
          three) delta=3 ;;
          *) fail "writer_mutant_checks: unknown byte count $delta in shape $shape" ;;
        esac
        case "$shape" in
          *-short) want=$((golden_func - delta)) ;;
          *) want=$((golden_func + delta)) ;;
        esac
        [ "$(func_len "$out")" = "$want" ] ||
          fail "$name: the golden's Func section is $golden_func bytes and the mutant's is $(func_len "$out") on $backend; expected $want" ;;
      file-shorter)
        [ "$mutant_size" -lt "$golden_size" ] ||
          fail "$name: $k.tilebc is $golden_size bytes and the mutant's is $mutant_size on $backend; expected a shorter file" ;;
      *) fail "writer_mutant_checks: unknown shape $shape" ;;
    esac
  done
  cmp -s "$work/m-$name.$k.jvm.tilebc" "$work/m-$name.$k.native.tilebc" ||
    fail "$name: the two backends disagree on the mutant's bytes"
  if [ -n "$tileiras" ]; then
    if assemble "$work/m-$name.$k.jvm.tilebc" "$work/m-$name.cubin" "$(kernel_arch "$k")"; then
      fail "$name mutant stayed green: tileiras accepted the mutant's bytecode"
    fi
    grep -Fq "$fragment" "$work/m-$name.cubin.log" ||
      { cat "$work/m-$name.cubin.log" >&2; fail "$name: tileiras refused the bytecode for something other than: $fragment"; }
    echo "PASS  mutant: $name ($k.mlir untouched, $k.tilebc red on both backends; tileiras: $fragment)"
  else
    echo "PASS  mutant: $name ($k.mlir untouched, $k.tilebc red on both backends)"
    echo "SKIP  mutant: $name not handed to tileiras (--without-tileiras)"
  fi
}

# A handler or lowering mutant that a loop kernel trips over before any text
# is rendered: <kernel> exits non-zero on both backends with <fragment> on
# stderr and nothing on stdout, while vadd, which has no loop, still renders
# its golden.
refused_mutant_checks() { # name, kernel, fragment
  local name="$1" k="$2" fragment="$3" backend out ctrl
  mutant_run "$name" "$k"
  mutant_run "$name" vadd
  for backend in jvm native; do
    out="$work/m-$name.$k.$backend"
    [ "$(cat "$out.rc")" != 0 ] || { cat "$out" >&2; fail "$name mutant stayed green on $backend: $k still renders (exit 0)"; }
    grep -Fq "$fragment" "$out.err" ||
      { cat "$out.err" >&2; fail "$name: $k failed on $backend for something other than: $fragment"; }
    [ ! -s "$out" ] || fail "$name: $k printed text before being refused on $backend"
    ctrl="$work/m-$name.vadd.$backend"
    if [ "$(cat "$ctrl.rc")" != 0 ] || ! cmp -s "$here/vadd.mlir" "$ctrl"; then
      cat "$ctrl.err" >&2
      fail "$name: vadd (no loop) should be untouched on $backend"
    fi
  done
  echo "PASS  mutant: $name ($k refused before rendering on both backends: $fragment; vadd untouched)"
}

# 3. The writer encodes make_token with iota's opcode. Same length, one byte
#    differs, and the verifier behind the reader says a token is not a tile.
if run_item make-token-as-iota; then
  mutant_project make-token-as-iota bytecode.dawn \
    'const OP_MAKE_TOKEN: Int = 0x44' \
    'const OP_MAKE_TOKEN: Int = 0x3A'
  writer_mutant_checks make-token-as-iota vadd same-size \
    "'cuda_tile.iota' op result #0 must be tile of"
fi

# 4. The writer's store still sets the token-present flag but no longer
#    writes the operand. vadd has one store and its token index is one
#    varint byte, so the function section is one byte short (the file is
#    not: the constant section's alignment padding grows by one); the reader
#    takes the next byte, `return`'s opcode 0x5C, for the token's value index
#    and refuses it: 92 is past the 27 values (3 parameters, 24 results).
if run_item store-token-unwritten; then
  mutant_project store-token-unwritten bytecode.dawn \
    'emit_ref(emit_opt_ref(emit_ref(emit_ref(w1, ptrs), value), mask), tok_in)' \
    'emit_opt_ref(emit_ref(emit_ref(w1, ptrs), value), mask)'
  writer_mutant_checks store-token-unwritten vadd func-one-short \
    "operand index 92 out of bounds (size=27) for token segment"
fi

# 5. The writer's type table gives f64 the i64 tag. Same length, the type
#    section differs, and the verifier refuses addf over an integer tile.
if run_item f64-tag-as-i64; then
  mutant_project f64-tag-as-i64 bytecode.dawn \
    '  "f64" -> 9' \
    '  "f64" -> 4'
  writer_mutant_checks f64-tag-as-i64 vadd same-size \
    "'cuda_tile.addf' op operand #0 must be tile of f16 or bf16 or f32 or f64 values, but got '!cuda_tile.tile<128xi64>'"
fi

# 6. The handler stops carrying the token out of a loop: after `t_loop_end`
#    the token cell keeps the body's last token instead of taking the loop's
#    token result. sum's store after the loop then names a load token from
#    inside it, and the lowering, which closes a body's names when the loop
#    ends, refuses it by name. Nothing is rendered; the text golden never
#    sees a file.
if run_item loop-token-not-carried; then
  mutant_project loop-token-not-carried prog.dawn \
    '        tok = last(results)
' \
    '        ()
'
  refused_mutant_checks loop-token-not-carried sum \
    'tileir: `store token` refers to handle 17, which a loop body defined and which is not visible after the loop'
fi

# 7. The handler pops the region stack the wrong way round: the operations
#    the loop body issued stay in the enclosing region and the ones issued
#    before the loop become the body. sum's first operation is then the
#    body's own index arithmetic, over the induction variable, which
#    nothing outside the loop has defined.
if run_item region-stack-pop; then
  mutant_project region-stack-pop prog.dawn \
    'let (outer, inner) = (saved, ops)' \
    'let (outer, inner) = (ops, saved)'
  refused_mutant_checks region-stack-pop sum \
    'tileir: `index mul lhs` refers to handle 11, which no earlier operation defined'
fi

# 8. The writer forgets the reader's rule that a block's value indices roll
#    back before the loop's own results are numbered. sum's results take the
#    indices after its body instead of the body's first two, and everything
#    after the loop shifts with them; the file is the same length (every
#    index is one varint byte either way), the text is untouched, and the
#    reader stops at the first operand past the values it has: 39 where it
#    knows 25 (2 parameters, 20 values before the loop, its 2 results and
#    the constant after it).
if run_item for-results-not-rolled-back; then
  mutant_project for-results-not-rolled-back bytecode.dawn \
    'fn roll_back(before: W, after: W) -> W = W { ..after, index: before.index, nvals: before.nvals }' \
    'fn roll_back(before: W, after: W) -> W = after'
  writer_mutant_checks for-results-not-rolled-back sum same-size \
    "operand index 39 out of bounds (size=25) for operand 1"
fi

# 9. The renderer forgets addf's rounding attribute. Every kernel with an
#    addf moves, but the claim is bf16's: `rounding<nearest_even>` is what
#    makes the device's bf16 sum narrow.round_bf16's (docs 3.2). vadd_bf16
#    still renders (exit 0) and differs from its golden in the addf line
#    and nowhere else, on both backends.
if run_item addf-no-rounding; then
  mutant_project addf-no-rounding render.dawn \
    '  "addf" | "subf" | "mulf" | "divf" | "addf_ftz" | "mulf_ftz" -> " rounding<nearest_even>"' \
    '  "addf" | "subf" | "mulf" | "divf" | "addf_ftz" | "mulf_ftz" -> ""'
  mutant_run addf-no-rounding vadd_bf16
  for backend in jvm native; do
    out="$work/m-addf-no-rounding.vadd_bf16.$backend"
    [ "$(cat "$out.rc")" = 0 ] || { cat "$out.err" >&2; fail "addf-no-rounding: vadd_bf16 did not run to completion on $backend"; }
    cmp -s "$here/vadd_bf16.mlir" "$out" && fail "addf-no-rounding mutant stayed green on $backend: vadd_bf16.mlir still matches"
    changed=$(diff "$here/vadd_bf16.mlir" "$out" | grep -c '^[<>]' || true)
    [ "$changed" = 2 ] || { diff "$here/vadd_bf16.mlir" "$out" >&2 || true; fail "addf-no-rounding: expected exactly the addf line to move on $backend, got $changed changed line(s)"; }
    grep -q '^< .*addf .* rounding<nearest_even> : tile<128xbf16>$' <(diff "$here/vadd_bf16.mlir" "$out") ||
      { diff "$here/vadd_bf16.mlir" "$out" >&2 || true; fail "addf-no-rounding: the moved line is not the bf16 addf on $backend"; }
  done
  echo "PASS  mutant: addf-no-rounding (vadd_bf16.mlir red on both backends; exactly the addf line moved)"
fi

# 10. The writer's type table gives bf16 the i16 tag. Same length, the type
#     section differs, and the verifier refuses addf over an integer tile:
#     the bf16 twin of f64-tag-as-i64.
if run_item bf16-tag-as-i16; then
  mutant_project bf16-tag-as-i16 bytecode.dawn \
    '  "bf16" -> 6' \
    '  "bf16" -> 2'
  writer_mutant_checks bf16-tag-as-i16 vadd_bf16 same-size \
    "'cuda_tile.addf' op operand #0 must be tile of f16 or bf16 or f32 or f64 values, but got '!cuda_tile.tile<128xi16>'"
fi

# 11. The writer gives the padding value the token's flag bit, so a masked
#     load says "mask and token, no padding value" while its operand list
#     still carries all three. The flags are the only thing that says how
#     many operands follow, so the reader takes the padding value for the
#     token and then reads the rest of the function one operand out of step.
#     The text is untouched (the renderer prints the operand it was given,
#     not the flag) and the file is the same length: a flag bit is a flag
#     bit either way. Only layer 1 sees it.
if run_item load-pad-flag-as-token; then
  mutant_project load-pad-flag-as-token bytecode.dawn \
    'const LOAD_FLAG_PAD: Int = 8' \
    'const LOAD_FLAG_PAD: Int = 16'
  writer_mutant_checks load-pad-flag-as-token vadd_tail same-size \
    "failed to get result type 0 for"
fi

# 12. The writer gives `ftoi` the nearest-even rounding mode where the
#     dialect accepts only `nearest_int_to_zero`. The text is untouched
#     (the renderer prints the mode from its own table) and the file is
#     the same length -- one enum value for another -- and the verifier
#     names the operation and the mode it wanted.
#
#     This one was written as a LAYER 2 mutant (the coverage memo's plan
#     for knife 10: a rounding mode is a semantic choice, and `int_ops`
#     converts `a / 2` on odd lanes where the two modes disagree) and
#     measured its way here instead: tileiras refuses it outright, so the
#     device never sees it. Recorded where it actually lands. The
#     conversion mutant that does reach layer 2 is
#     scripts/tile-gpu-diff's exti-sign-extends.
if run_item ftoi-rounds-instead-of-truncates; then
  mutant_project ftoi-rounds-instead-of-truncates bytecode.dawn \
    '  "ftoi" -> [SIGNED, ROUND_INT_TO_ZERO]' \
    '  "ftoi" -> [SIGNED, ROUND_NEAREST_EVEN]'
  writer_mutant_checks ftoi-rounds-instead-of-truncates int_ops same-size \
    "'cuda_tile.ftoi' op invalid rounding mode specified. Only 'nearest_int_to_zero' is supported"
fi

# 13. The writer gives a `scan` a `reduce`'s result types: the operand's
#     shape with the scanned dimension dropped. Every other byte is the
#     same -- a type index is one varint either way, and prefix_sum's type
#     table already holds the rank-0 f64 its region arguments use -- so the
#     file is the same length, the text is untouched, and the verifier says
#     what a scan's result is: the type of its operand.
#
#     The claim is the whole difference between `reduce` and `scan` below
#     the opcode: `lower_reduce` drops `dim` from the result types and
#     `lower_scan` keeps every dimension. Nothing under layer 1 knows which
#     is right -- the renderer prints the types it was handed either way.
if run_item scan-result-drops-the-dim; then
  mutant_project scan-result-drops-the-dim bytecode.dawn \
    '    let w1 = emit(emit(w0, OP_SCAN), len(tys))
    let w2 = list.fold(tys, w1, (w, t) => {' \
    '    let w1 = emit(emit(w0, OP_SCAN), len(tys))
    let w2 = list.fold(list.map(tys, rank0_of), w1, (w, t) => {'
  writer_mutant_checks scan-result-drops-the-dim prefix_sum same-size \
    "'cuda_tile.scan' op expect same type for operand at index: 0 and result at index: 0"
fi

# 14. The writer claims `weak` memory ordering on a read-modify-write. The
#     renderer prints `relaxed` from its own spelling table, so the text is
#     untouched and the file is the same length -- one enum value for
#     another -- and the verifier names the attribute: the atomics take
#     every ordering but that one.
if run_item atomic-rmw-claims-weak-ordering; then
  mutant_project atomic-rmw-claims-weak-ordering bytecode.dawn \
    '  _ -> (mode, ORDER_RELAXED, SCOPE_DEVICE)' \
    '  _ -> (mode, ORDER_WEAK, SCOPE_DEVICE)'
  writer_mutant_checks atomic-rmw-claims-weak-ordering histogram same-size \
    "'cuda_tile.atomic_rmw_tko' op memory ordering semantics must be one of: relaxed, acquire, release, acq_rel"
fi

# 15. The writer gives a compare-and-swap the read-modify-write's `mode`
#     byte. That is one attribute the operation does not have, so the file
#     is one byte LONGER and every operand after it is read one place out
#     of step. The text cannot see it and the byte golden would be
#     re-recorded over it.
if run_item atomic-cas-writes-an-rmw-mode; then
  mutant_project atomic-cas-writes-an-rmw-mode bytecode.dawn \
    '    let w3 = emit(emit(emit(emit(w2, tok), flags), ORDER_RELAXED), SCOPE_DEVICE)
    emit_ref(emit_opt_ref(emit_ref(emit_ref(emit_ref(w3, ptrs), cmp), val), mask), tok_in)' \
    '    let w3 = emit(emit(emit(emit(emit(w2, tok), flags), ORDER_RELAXED), SCOPE_DEVICE), rmw_mode_value("add"))
    emit_ref(emit_opt_ref(emit_ref(emit_ref(emit_ref(w3, ptrs), cmp), val), mask), tok_in)'
  writer_mutant_checks atomic-cas-writes-an-rmw-mode cas_swap func-one-long \
    "failed to parse function body for function 'cas_swap'"
fi

# 16. The writer gives `sin` a flags varint. None of knife T1's seven
#     operations has an optional field, so none of them writes one
#     (BytecodeGen.cpp only emits the varint where
#     getVersionOrderedBitAssignments found a bit to assign), and a byte
#     written anyway is one byte the reader takes for the operand index.
#     So the file is one byte LONGER and everything after the extra byte is
#     read one place out of step. Neither layer 0 nor the type checker can
#     see it: the renderer never prints a flags word, and a flags 0 is what
#     an operation WITH an optional field would legitimately write.
#
#     tileiras loses the stream one operation later and says so in four
#     lines, of which the first is the informative one:
#
#       error: error at offset 112: failed to get result type 0 for DivIOp
#       error: error at offset 751: failed to parse function body for
#         function 'trig_sweep'
#       error: error at offset 751: failed to create function from bytecode
#       error: input does not correspond to Tile IR bytecode
#
#     There is no `divi` in this kernel: `DivIOp` is what the byte after the
#     extra one decodes to once the reader is one place out of step, which
#     is the same shape as the measurement `exp`'s doc comment records
#     (`failed to get result type 0 for CmpIOp`).
if run_item trig-extra-flags; then
  mutant_project trig-extra-flags bytecode.dawn \
    '    "sin", "cos", "tan", "sinh", "cosh", "atan2", "remf"]))' \
    '    "cos", "tan", "sinh", "cosh", "atan2", "remf"]))'
  writer_mutant_checks trig-extra-flags trig_sweep func-one-long \
    "error at offset 112: failed to get result type 0 for DivIOp"
fi

# 17. The writer says a `join_tokens` has one operand more than it wrote.
#     The count is a one-byte varint either way, so the file is the same
#     length and the text cannot see it; the reader walks past the end of
#     the operand list for that instruction.
#
#     This is knife T2's layer-3 evidence for `join_tokens` 0x3C. Its
#     operand list is the one thing about the operation that can be wrong
#     without being a type error: every token is a token, so a joined set
#     that is too large or too small is caught here and nowhere below.
if run_item join-tokens-operand-count-wrong; then
  mutant_project join-tokens-operand-count-wrong bytecode.dawn \
    'let w1 = emit(emit_op_counted(w0, OP_JOIN_TOKENS, Token), len(toks))' \
    'let w1 = emit(emit_op_counted(w0, OP_JOIN_TOKENS, Token), len(toks) + 1)'
  writer_mutant_checks join-tokens-operand-count-wrong token_join same-size \
    "operand index 91 out of bounds (size=40) for operand 2"
fi

# 18. The writer concatenates along the other dimension. `dim` is an inline
#     varint and 0 and 1 are both one byte, so the file is the same length.
#
#     `cat`'s `dim` decides the RESULT SHAPE (CatOp's verifier derives it),
#     so a wrong dimension can never reach the device: it is a type error,
#     always, whatever the operands. That is why this is a layer-1 mutant
#     and why `cat`'s device-level evidence is a different one --
#     cat-operands-swapped in scripts/tile-gpu-diff, which keeps the shape
#     and moves the answer.
if run_item cat-dim-swapped; then
  mutant_project cat-dim-swapped bytecode.dawn \
    'emit_ref(emit_ref(emit(emit_op(w0, OP_CAT, to), dim), lhs), rhs)' \
    'emit_ref(emit_ref(emit(emit_op(w0, OP_CAT, to), 1 - dim), lhs), rhs)'
  writer_mutant_checks cat-dim-swapped shape_ops same-size \
    "'cuda_tile.cat' op invalid concat at position 1, expected: 8 but got: 4"
fi

# 19, 20, 21. The three pointer conversions, each written as one of the
#     others. All three are one-byte opcodes, so the file is the same
#     length in every case, and all three are refused by the assembler
#     rather than by the device.
#
#     That is not a weakness of the corpus, it is what these operations
#     are: `ptr_to_int`, `int_to_ptr` and `ptr_to_ptr` change a TYPE and
#     leave the address alone, so there is no value for a writer to get
#     wrong. Any wrong writing of one is a type error, and a type error
#     never reaches a GPU. The three kernels behind them still carry the
#     ops at layer 2 (scripts/tile-gpu-diff runs ptr_roundtrip and
#     ptr_recast on the device against a host reference that decodes the
#     bit pattern itself); these three say that the byte written is the
#     byte meant.
if run_item int-to-ptr-as-ptr-to-int; then
  mutant_project int-to-ptr-as-ptr-to-int bytecode.dawn \
    'IntToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_INT_TO_PTR, to), src)' \
    'IntToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_INT, to), src)'
  writer_mutant_checks int-to-ptr-as-ptr-to-int ptr_roundtrip same-size \
    "'cuda_tile.ptr_to_int' op operand #0 must be tile of Pointer type values"
fi

if run_item ptr-to-int-as-int-to-ptr; then
  mutant_project ptr-to-int-as-int-to-ptr bytecode.dawn \
    'PtrToIntTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_INT, to), src)' \
    'PtrToIntTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_INT_TO_PTR, to), src)'
  writer_mutant_checks ptr-to-int-as-int-to-ptr ptr_roundtrip same-size \
    "'cuda_tile.int_to_ptr' op operand #0 must be tile of i64 values"
fi

if run_item ptr-to-ptr-as-bitcast; then
  mutant_project ptr-to-ptr-as-bitcast bytecode.dawn \
    'PtrToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_PTR_TO_PTR, to), src)' \
    'PtrToPtrTile(_dst, src, _from, to) -> emit_ref(emit_op(w0, OP_BITCAST, to), src)'
  writer_mutant_checks ptr-to-ptr-as-bitcast ptr_recast same-size \
    "'cuda_tile.bitcast' op operand #0 must be tile of i1"
fi

# 22. The writer's type table gives i16 the bf16 tag. Both are two bytes,
#     so nothing about the file's shape is wrong and the reader gets as far
#     as the verifier, which says what `addi` wants. A tag of another WIDTH
#     could be refused for its length instead; this one cannot, which is
#     why it is the one taken: the twin of f64-tag-as-i64 (eight bytes for
#     eight) and bf16-tag-as-i16 (two for two).
if run_item i16-tag-as-bf16; then
  mutant_project i16-tag-as-bf16 bytecode.dawn \
    '  "i16" -> 2
' \
    '  "i16" -> 6
'
  writer_mutant_checks i16-tag-as-bf16 dtype_i16 same-size \
    "'cuda_tile.addi' op operand #0 must be tile of i1 or i8 or i16 or i32 or i64 values, but got '!cuda_tile.tile<128xbf16>'"
fi

# 23. The writer lays an i64 constant down four bytes wide. The type table
#     still says i64 and the renderer still prints the value, so this is
#     the OTHER half of what a type tag means: a tag says how wide a lane
#     is, and the constant section's blob has to be that wide or the reader
#     cannot tell how many lanes it holds. dtype_i64 is the only kernel
#     here with a constant of this width (2^32, which needs five bytes),
#     and it is in that kernel for this mutant.
if run_item i64-payload-four-bytes; then
  mutant_project i64-payload-four-bytes bytecode.dawn \
    '  "i64" -> bytes.freeze(put_le(bytes.buf(), value, 8))' \
    '  "i64" -> bytes.freeze(put_le(bytes.buf(), value, 4))'
  writer_mutant_checks i64-payload-four-bytes dtype_i64 file-shorter \
    "error at offset 5: failed to validate buffer size and format"
fi

# 24. The writer's type table gives f8E4M3FN the i8 tag. One byte for one
#     byte, so the file is the same length and the verifier is what
#     refuses it: `ftof` takes a float tile and an i8 tile is not one.
#
#     It is the ONLY fp8 tag mutant, and the reason is measured rather than
#     chosen: giving f8E5M2 the f8E4M3FN tag produces a program tileiras
#     accepts without a word (both are float formats of one byte and every
#     operation over them is legal), so below layer 2 those two are the
#     same type, and layer 2 for either is unreachable here since sm_86
#     refuses both. What this mutant shows is that the fp8 tags are
#     load-bearing at all.
if run_item e4m3-tag-as-i8; then
  mutant_project e4m3-tag-as-i8 bytecode.dawn \
    '  "f8E4M3FN" -> 10
' \
    '  "f8E4M3FN" -> 1
'
  writer_mutant_checks e4m3-tag-as-i8 dtype_e4m3 same-size \
    "'cuda_tile.ftof' op operand #0 must be tile of f16 or bf16 or f32 or f64 or tf32 or f8E4M3FN or f8E5M2 or f8E8M0FNU or f4E2M1FN values, but got '!cuda_tile.tile<128xi8>'"
fi

# 25. The writer stops keying `ftof`'s rounding mode on its target and
#     writes `nearest_even` for every conversion, which is the DEFAULT the
#     attribute would carry if nobody thought about it. f8E8M0FNU is the
#     one target that refuses it (Ops.td's FToFOp), so the file is the same
#     length, one enum value for another, and the verifier names both the
#     format and the two modes it does take.
if run_item e8m0-rounding-as-nearest-even; then
  mutant_project e8m0-rounding-as-nearest-even bytecode.dawn \
    '  if to == "f8E8M0FNU" { ROUND_ZERO } else { ROUND_NEAREST_EVEN }' \
    '  ROUND_NEAREST_EVEN'
  writer_mutant_checks e8m0-rounding-as-nearest-even dtype_e8m0 same-size \
    "'cuda_tile.ftof' op invalid rounding mode specified for conversion to f8E8M0FNU. Only 'zero' and 'positive_inf' are supported"
fi

# 26. The same sentence from the other side: the writer's type table gives
#     f8E8M0FNU the f8E5M2 tag, so the `rounding<zero>` written for that
#     target lands on a target that takes only `nearest_even`, and the
#     verifier says so. The two mutants together are what makes
#     ftof_rounding a claim: one says the mode has to be `zero` HERE, the
#     other says it has to be `nearest_even` EVERYWHERE ELSE, and either
#     alone would leave a writer that hard-codes the other mode green.
if run_item e8m0-tag-as-f8e5m2; then
  mutant_project e8m0-tag-as-f8e5m2 bytecode.dawn \
    '  "f8E8M0FNU" -> 18
' \
    '  "f8E8M0FNU" -> 11
'
  writer_mutant_checks e8m0-tag-as-f8e5m2 dtype_e8m0 same-size \
    "'cuda_tile.ftof' op invalid rounding mode specified. Only 'nearest_even' is supported"
fi

# 27. The `loop` region's own rollback. `for`'s is a mutant of the shared
#     `roll_back` function (for-results-not-rolled-back, above); this one
#     is the CALL in the loop arm, because the two regions are written by
#     two arms of the same match and only one of them is `for`'s.
if run_item loop-carried-not-rolled-back; then
  mutant_project loop-carried-not-rolled-back bytecode.dawn \
    '    roll_back(w_block, w_body)' \
    '    w_body'
  writer_mutant_checks loop-carried-not-rolled-back loop_count same-size \
    "operand index 37 out of bounds (size=19) for operand 0"
fi

# 28. `break` with no operands. The loop's results are the values the break
#     hands back, so dropping them is not a stream error but a TYPE error,
#     and the verifier prints both sides. The file does not shrink: the two
#     operand indices come out of the Func section and the alignment
#     padding after it takes the same two bytes back.
if run_item break-values-missing; then
  mutant_project break-values-missing bytecode.dawn \
    '  BreakVals(values, _tys) -> list.fold(values, emit(emit(emit(w0, OP_BREAK), 0), len(values)), emit_ref)' \
    '  BreakVals(_values, _tys) -> emit(emit(emit(w0, OP_BREAK), 0), 0)'
  writer_mutant_checks break-values-missing loop_count same-size \
    "'cuda_tile.break' op operand types must correspond to the parent loop result types"
fi

# 29. The writer stops writing the `overflow` attribute of the three
#     assumptions. The three integer operations of attr_overflow then have
#     nothing between their result type and their operands, so the reader
#     takes the first operand index for the enum; the function section is
#     three bytes short and the assembler names the attribute it could not
#     parse.
#
#     This is where `nsw`, `nuw` and `nw` are covered, and it has to be:
#     they are assumptions the compiler MAY use, not arithmetic, so a
#     program that keeps its promise computes the same thing with them and
#     without them and no corpus can tell them apart.
#     scripts/tileir-features/attrs.txt records the three at layer 1 with
#     that reason spelled out.
if run_item overflow-attr-not-written; then
  mutant_project overflow-attr-not-written bytecode.dawn \
    '  "addi_nsw" -> [OVERFLOW_NSW]
  "subi_nuw" -> [OVERFLOW_NUW]
  "muli_nw" -> [OVERFLOW_NW]' \
    '  "addi_nsw" -> []
  "subi_nuw" -> []
  "muli_nw" -> []'
  writer_mutant_checks overflow-attr-not-written attr_overflow func-three-short \
    "error at offset 72: invalid integer value for enum type: 18"
fi

# 30. The writer swaps the memory ordering and the memory scope of the
#     three suffixed atomic modes. Both are required inline enums written
#     in declaration order, so the swap is same-size and invisible at
#     layer 0 (the renderer spells them from its own table); the assembler
#     refuses it because 3 is not a memory scope.
#
#     One anchor carries six values -- `acquire`, `release`, `acq_rel`,
#     `tl_blk`, `sys` and `device` -- and that is the whole of what any
#     judgement here can be. An ordering constrains CONCURRENT accesses,
#     the corpus that reaches the device gives every lane its own slot, and
#     a judgement about the ordering itself would need two blocks racing
#     and a comparison shape this repository does not have.
if run_item atomic-memory-attrs-swapped; then
  mutant_project atomic-memory-attrs-swapped bytecode.dawn \
    '  "add_acquire_tl_blk" -> ("add", ORDER_ACQUIRE, SCOPE_TL_BLK)
  "add_release_sys" -> ("add", ORDER_RELEASE, SCOPE_SYS)
  "add_acq_rel_device" -> ("add", ORDER_ACQ_REL, SCOPE_DEVICE)' \
    '  "add_acquire_tl_blk" -> ("add", SCOPE_TL_BLK, ORDER_ACQUIRE)
  "add_release_sys" -> ("add", SCOPE_SYS, ORDER_RELEASE)
  "add_acq_rel_device" -> ("add", SCOPE_DEVICE, ORDER_ACQ_REL)'
  writer_mutant_checks atomic-memory-attrs-swapped attr_memsem same-size \
    "error at offset 109: invalid integer value for enum type: 3"
fi

# 31. The writer gives the float atomic mode the integer one's enum value.
#     `add` is 3 and `addf` is 4, neighbours in one enum over both, so this
#     is one byte and the same length; the dialect refuses it because the
#     buffer is f64 and `add` is defined for i32 and i64 only.
#
#     The device could not have caught this one: `add` on an f64 pointer
#     tile is not a wrong answer, it is a program the assembler will not
#     build.
if run_item rmw-addf-as-add; then
  mutant_project rmw-addf-as-add bytecode.dawn \
    '  "addf" -> 4' \
    '  "addf" -> 3'
  writer_mutant_checks rmw-addf-as-add attr_addf same-size \
    "'cuda_tile.atomic_rmw_tko' op 'add' works only with integers i32 and i64"
fi

_item_tick ""
shard_report "${#items[@]}"
echo "tile golden ok"
