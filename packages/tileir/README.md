# packages/tileir

A pure Dawn generator of CUDA Tile IR that records a kernel body written against the `Dev` effect and emits it as `cuda_tile` text or as bytecode `tileiras` can assemble.

A kernel body is an ordinary Dawn function whose only effect is `Dev`. Running
it once under a recording handler yields a `TileProg` (an ADT in SSA form),
which is lowered to a linear instruction table and then rendered as
`cuda_tile` dialect text or encoded as `tileiras` bytecode. The design and the
order of the work are in
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5 and §6
(in Chinese); this package is knives 2 and 3 there. It is not in std: it
needs no intrinsic, and the bytecode version has to be pinned in a package
constant.

The host side (buffers, launch) is `std/gpu`, which knows kernel names and
bytecode and does not know `TileProg`. The format markers are `std/gpu`'s
(`F64`, `BF16` and so on); this package does not declare a second set. A bf16
kernel is written the same way as an f64 one (`Param[BF16]`,
`addf(BF16, ...)`), and the dtype name `"bf16"` runs through recording,
lowering, rendering (`tile<128xbf16>`) and bytecode (type tag 6). By the
double-rounding theorem, the device's `addf ... rounding<nearest_even>` on
bf16 answers what `std/narrow.round_bf16` of the f64 sum answers;
`scripts/tile-golden`'s `vadd_bf16` pins the text and the bytes, and
`scripts/tile-gpu-diff` checks the device against the fake device.

## Modules

| Module | Contents |
|------|------|
| `dev` | `pub effect Dev` (handle-level, monomorphic device operations), the handle types (`Tile[D]`, `Param[D]`, `Idx`, `Scalar[D]`, `Ptrs[D]`, the view types and others, all opaque, with `D` a phantom format parameter) and the typed functions over them; the groups are below |
| `prog` | `TileOp` and `TileProg`, the recorded ADT; `trace_kernel(name, params, body, hints = [])` is the recording handler, with a region stack; `MAX_LOOP_DEPTH`, `MAX_HANDLES` |
| `lower` | `lower(prog) -> Kernel`: the linear instruction table `Instr` (a region operation's body is a nested table), values numbered densely from 0, operands `Arg(pos)` / `Val(id)`, types `Ty`; the pointer ladders, deduplication, SSA renumbering and region scoping all live here |
| `render` | `render(prog) -> String`: one `cuda_tile.module @m` holding the module's globals and one `entry @<name>`; one line per `Instr`, a region as a header line, a body indented two spaces, and a closing brace |
| `bytecode` | `encode(prog) -> Bytes`: `cuda-tile` bytecode, regions included; `BYTECODE_MAJOR` / `BYTECODE_MINOR` pin the version in the header, and `bytecode_version()` answers `"13.4"` |

The full public surface (signatures and doc comments) is whatever
`./bin/dawn doc packages/tileir` prints, one JSON document for the five
modules. This README does not list every name: the last time a table here did,
`Dev` had a dozen operations, and it grew past sixty while the table stayed
put.

### The groups of `dev`

The table puts every `Dev` operation in a group and names some of the typed
functions of each (a kernel body calls those, not the `t_*` operations). It
was generated from `effects[0].ops` of `./bin/dawn doc packages/tileir`, and a
script checked that the groups cover every operation exactly once (71
operations on 2026-10-03). When an operation is added, its group has to
follow; `dawn doc` is the authority on numbers and names.

| Group | `Dev` operations | Typed functions (examples) |
|----|-----------|--------------------|
| Grid and index | `t_block_id` `t_num_blocks` `t_idx_const` `t_idx_add` `t_idx_mul` | `block_id` `num_blocks` `idx_const` `idx_add` `idx_mul` `idx_lt` |
| Memory and pointers | `t_load` `t_store` `t_gather` `t_scatter` `t_atomic_rmw` `t_atomic_cas` `t_ptrs` `t_ptr_offset` `t_ptr_to_int` `t_int_to_ptr` `t_ptr_to_ptr` `t_load_ptrs` `t_store_ptrs` `t_alloca` | `load` `store` `load_masked` `load_strided` `gather` `scatter` `atomic_rmw` `atomic_cas` `ptrs` `load_ptrs` `alloca_ptrs` |
| Views | `t_tensor_view` `t_partition_view` `t_strided_view` `t_gather_view` `t_atomic_red_view` `t_load_view` `t_store_view` `t_tensor_shape` `t_index_space_shape` | `tensor_view` `tensor_view_dyn` `partition_view` `strided_view` `gather_scatter_view` `load_view` `store_view` `tensor_dim` |
| Constants and shapes | `t_constf` `t_consti` `t_iota` `t_lanes` `t_spread` `t_extract` `t_insert` `t_cat` `t_permute` | `f_const` `i_const` `arange` `lanes` `spread` `extract` `insert` `cat` `permute_tile` |
| Arithmetic, comparison and conversion | `t_unaryf` `t_binaryf` `t_powi` `t_fma` `t_cmpf` `t_cmpi` `t_unaryi` `t_binaryi` `t_select` `t_convert` `t_repack` `t_mmaf` `t_mmaf_scaled` `t_mmai` | `addf` `mul` `exp` `powi` `fma` `lt` `add_i` `select` `int_to_float` `float_to_int` `float_to_float` `pack_bytes` `mmaf` `mmaf_scaled` `mmai` |
| Regions | `t_loop_begin` `t_loop_end` `t_while_begin` `t_while_end` `t_return_if` `t_reduce_begin` `t_reduce_end` `t_scan_begin` `t_scan_end` `t_if_begin` `t_if_else` `t_if_end` | `d_for` `d_for2`…`d_for4` `d_loop` `d_return_if` `d_reduce` `d_scan` `d_if` |
| Tokens | `t_tok_get` `t_tok_set` `t_tok_join` | `d_fork2` |
| Module globals | `t_global` `t_get_global` | `d_global` `global_ptrs` |
| Assertions and debugging | `t_assert` `t_assume` `t_print` | `d_assert` `d_assume` `assume_div_by` `d_print` |

Since knife K2, the attributes of an operation (rounding mode, flush to zero,
NaN propagation, integer `overflow`, a loop's unsigned comparison, a global's
alignment, visibility and constness, and whether an `alloca` is shared) are
named parameters with the dialect's default, placed after the positional
parameters and after `body`: `addf(F32, s, a, b, rounding: Down)`,
`d_global("t", F64, xs, visibility: Private)`,
`trace_kernel("k", ps, () => body(), hints: hs)`. The rounding mode is
`std/narrow`'s `Rounding`. The suffixed names of knives T4 and T17
(`addf_down`, `float_to_int_sat`, `d_global_private`, ...) are gone; the
reasons are in section 7.2 of
[`docs/std-defaults-design.md`](../../docs/std-defaults-design.md) (in
Chinese).

## Usage

```dawn
use std/gpu.{F64}
use tileir/dev.{Dev, Param, param, block_id, tile_at, load, store, addf}
use tileir/prog.{trace_kernel}
use tileir/render.{render}
use tileir/bytecode.{encode}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let blk = tile_at(block_id(0), 128)
  let ta = load(a, blk, [128])
  let tb = load(b, blk, [128])
  store(out, blk, [128], addf(F64, [128], ta, tb))
}

let prog = trace_kernel("vadd", ["f64", "f64", "f64"],
  () => vadd(param(F64, 0), param(F64, 1), param(F64, 2)))
let text = render(prog)     # for people to read and for the goldens to pin
let bytes = encode(prog)    # for tileiras to assemble into a cubin
```

A memory operation takes an element offset, not a block index: `tile_at(idx,
n)` is `idx * n`, and a kernel over a multi-dimensional grid builds its base
from several of them. A shape is a list of dimensions, each a power of two;
`[]` is the rank-0 tile, which the typed surface spells `Scalar[D]`.

`params` gives each entry parameter's dtype name, by position. Every
`param(d, pos)` in the body has to agree with it (the position in range, the
same format), or `trace_kernel` panics: an entry signature that says one
format and a load that says another would be wrong in the bytecode too, by
the time it reached `tileiras`.

Loops inside a kernel use `d_for` (design §5.2). The bounds and the step are
`Idx` (`idx_const` for a host constant), one tile is carried, and the body
runs once on the host; what it emits lands in the loop's region:

```dawn
# block b folds `chunks` consecutive 128-wide tiles of x into one tile of out
fn sum(x: Param[F64], out: Param[F64], chunks: Int) -> Unit !Dev = {
  let b = block_id(0)
  let n = idx_const(chunks)
  let base = idx_mul(b, n)
  let first = load(x, tile_at(base, 128), [128])
  let one = idx_const(1)
  let acc = d_for(idx_add(base, one), idx_add(base, n), one, first,
    (k, t) => addf(F64, [128], t, load(x, tile_at(k, 128), [128])))
  store(out, tile_at(b, 128), [128], acc)
}
```

`d_for2` carries two tiles. Loop nesting is capped at `MAX_LOOP_DEPTH` (16)
and the handles of one recording at `MAX_HANDLES` (65536); past either the
recording panics, so a helper that recurses through `d_for` and one that
recurses without a loop each stop somewhere. A branch on a tile value uses
`d_if` (in `src/dev.dawn`): both regions are required, each runs once on the
host and answers a tile of the same shape and format, and neither may load or
store. Lowering turns it into an `IfElse` the way it turns a loop into a
`ForLoop` (`lower_if` next to `lower_for` in `src/lower.dawn`).

## The shape of a recording

- A handle is an SSA number assigned while recording, starting at 1 (0 is the
  entry token). The same body emitting the same operations in the same order
  records an equal `TileProg`; `scripts/tile-golden/run.sh` records every
  kernel twice and compares.
- The order of memory operations comes from the **token chain** and nothing
  else: the handler keeps one `tok` cell, each load and store consumes the
  previous token and produces the next, and `MakeToken(0)` heads the chain.
  Tile IR gives program order between memory operations no meaning.
- Lowering renumbers values in order of appearance (0, 1, ...), because a load
  or store first has to spread the scalar pointer into a tile of pointers
  (`reshape`, `broadcast`, `offset`, where the offset is `iota` plus the
  base), and those intermediate values are not in the recording. The pointer
  ladder for one (parameter, index, width) is emitted once. The renderer
  spells `Val(k)` as `%k` and `Arg(i)` as `%argi`; the writer puts the entry
  parameters first and the values right after them, in one flat index space.
- `addf` defaults to `rounding<nearest_even>`: design §3.2's double-rounding
  theorem holds for that mode only. The other modes are not public functions:
  the recorder picks a separate internal operation name from the `rounding`
  (and `ftz`) parameter, so the instruction table carries no rounding
  field. `scripts/tile-golden`'s `addf-no-rounding` mutant deletes the
  attribute from the renderer and `vadd_bf16.mlir` goes red;
  `bf16-tag-as-i16` changes the writer's bf16 tag to i16 and `tileiras`
  refuses the bytes.
- **A loop** is recorded as `For(iv, lower, upper, step, unsigned, inits,
  carried, results, body)`, with `body` ending in `Continue(values)`. The
  handler keeps a region stack: `t_loop_begin` pushes and clears the current
  operation list, and `t_loop_end` pops it and wraps the body in a `For`
  attached to the enclosing list. **The token crosses the loop as its last
  carried value**: the last of `inits` is the token before the loop, the body
  chains from the carried token inside the region, the last of `Continue` is
  the body's last token, and after the loop the handler continues from the
  last of `results`; the kernel body never sees it. In lowering, a handle
  defined in the body is closed when the region ends, and a later reference to
  it is refused by name; a pointer ladder built inside is not reused after the
  loop. The table numbers a `ForLoop` in reading order: results, induction
  variable, carried values, body.

## Bytecode

`encode` writes the format that `NVIDIA/cuda-tile`'s `BytecodeWriter.cpp`
writes and `BytecodeReader.cpp` reads (commit `be0889cd`): an 8-byte magic, a
`13.4` version header (`BYTECODE_MAJOR` / `BYTECODE_MINOR` in
`src/bytecode.dawn`; 13.2 before knife T8 and 13.3 before #344, see design
§6.11 and §6.18), the Func, Constant, Type and String sections, and an end
byte. Opcodes and type tags come from the three frozen `.td` tables in that
repository, and each operation's layout from the tablegen backend that
generates it (result types, then the optional-field flags bitfield, then
attributes, then operands). cuTile.jl's `src/bytecode` is an independent
implementation of the same format and was read alongside, item by item; the
reader accepts both of the two places their output differs (it always writes
a debug section and pre-registers i1 and i32), and this package follows the
C++ writer.

Only what the instruction table can hold is encoded: memory operations are
`weak` and carry their token operand, `addf` at its defaults is
`nearest_even` without flush-to-zero, and integer operations carry `overflow` none. **Value numbering
inside a region** follows the reader's rule: block arguments continue the
enclosing count, the block's results follow, the count rolls back to before
the arguments when the block ends, and the region-holding operation's own
results are numbered from there; the writer maps the table's (textual)
numbering onto it with an `index` table. A few shapes depend on the target
version, such as `for`'s optional `unsigned` field (13.2 and later), `exp`'s
inline rounding mode and `mmaf`'s flags (13.3) and the pointer type's flags
word (13.4); the header comment of `src/bytecode.dawn` lists every one, as
measured from the writer, and everything else is byte for byte the same from
13.1 to 13.4. The version, the `tileiras` pin and the wheel's sha256 are in
`scripts/tile-golden/toolchain.txt`, and `run.sh` checks `bytecode_version()`
against it.

## Gates

- `dawn test packages/tileir`: the inline test blocks
  (`scripts/package-tests.sh` discovers them).
- `scripts/tile-golden/run.sh`: for each of the 191 kernels in
  `scripts/tile-golden/kernels.dawn`, a text golden (`*.mlir`) and a bytecode
  golden (`*.tilebc`), on the JVM and natively; then each `.tilebc` goes to
  the pinned `tileiras --gpu-name <toolchain.txt gpu-name>` (sm_86 in the
  default `toolchain.txt`), which has to produce a cubin whose symbol table
  has `GLOBAL FUNC <kernel>` (layer 1, the `.github/workflows/tile.yml`
  workflow, sharded with `--shard I/N`). Locally,
  `scripts/tile-golden/install-tileiras.sh <dir>` installs it, `--tileiras
  <bin>` or `TILEIRAS=` points at it, and `--without-tileiras` skips it
  explicitly. 77 mutants each remove one rule from a copy of the package and
  name the kernel that must go red and how (for example: the renderer drops
  the store's token operand, so the text golden differs; the writer encodes
  `make_token` with `iota`'s opcode, so the text is untouched, the bytes
  differ and `tileiras` refuses them by name). The list with each
  prediction is the header of `run.sh`. `--record` re-records both kinds of
  golden.
- `scripts/opaque-twin/tileir.dawn`: the identity of the three handle types is
  their target's (`# twin-infer-only`).
