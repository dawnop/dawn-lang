# packages/tileir

A pure Dawn generator of CUDA Tile IR that records a kernel body written against the `Dev` effect and emits it as `cuda_tile` text or as bytecode `tileiras` can assemble.

A kernel body is an ordinary Dawn function whose only effect is `Dev`.
Recording it once yields a `TileProg`, which `render` prints as `cuda_tile`
text and `encode` writes as bytecode. Buffers and launches are `std/gpu`'s,
and a format is a value type with a witness of the same name: `Float` and
`F64`, `Int` and `I64`, `Bool` and `I1` (`std/dtype`), `BF16`, `F16` and `F32`
(`std/narrow`), `I32` (`std/int/i32`).

```dawn
use std/dtype.{F64}
use tileir/dev.{Dev, Param, load_cell, store_cell, add, DYN_DIM}
use tileir/prog.{trace3, cells, In, Out}
use tileir/render.{render}
use tileir/bytecode.{encode}

fn vadd(a: Param[Float], b: Param[Float], out: Param[Float]) -> Unit !Dev =
  store_cell(out, add(load_cell(a), load_cell(b)))

let g = cells([DYN_DIM], [128])     # 128-wide cells, as many as the grid has
let (prog, entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
let text = render(prog)     # cuda_tile text
let bytes = encode(prog)    # bytecode for tileiras
```

| Module | Contents |
|------|------|
| `dev` | the `Dev` effect, the opaque handle types (`Tile[D]`, `Param[D]`, `Idx`, views, ...) and the typed functions a kernel calls |
| `prog` | `TileProg`; `trace1` to `trace5` and `trace_kernel`, the recording handlers; the parameter markers |
| `lower` | `lower(prog)`, the linear instruction table |
| `render` | `render(prog)`, the `cuda_tile` text; `line_map` |
| `bytecode` | `encode(prog)`; `bytecode_version()` is `"13.4"` |
| `asm` | `tileiras_args(version, gpu_name)`, `assembler_defect(version, gpu_name)`: how to call `tileiras` (see below) |

The full public surface is what `./bin/dawn doc packages/tileir` prints.

## Parameters and cells

`trace1` to `trace5` take one marker per parameter and answer an entry
`std/gpu` can launch with typed arguments (`launch_entryN`):

- `In(d, cells)` is read only; a write into it is refused while recording.
  `In(d, Whole)` is an input read anywhere (a gather's table, a pointer read).
- `Out(d, cells)` is written one cell per block, and the `Out` cells are the
  launch grid: dimension `j` of an `Out` follows grid axis `along[j]`, each
  axis at most once (the identity unless `along` says otherwise), and an
  axis no dimension follows has one block. A batched product keeps its
  batch on axis 2 with `cells([B, M, N], [1, T, T], along: [2, 0, 1])`.
- `Shared(d)` is the escape hatch: atomics, scatters, a block that writes two
  regions, a write through pointers. `grep Shared(` finds every one.
- `Scalar(d)` is a value the launch passes by value (`i32`, `i64`, `f32` or
  `f64`), not a buffer: no cells, read in the body with `scalar(p)`, and
  passed with `std/gpu`'s `scalar_arg(v)`.
- `cells(extent, tile, pad: PadZero, along: ..)` cuts the tensor. An extent
  of `DYN_DIM` is the grid's to decide; `pad` is what a read past the extent
  answers; `along[j]` is the grid axis dimension `j` follows, or `FREE_AXIS`
  when the kernel picks that cell itself.

`trace_kernel(name, params, body)` records a body over `param(d, pos)`
handles, every one `Shared`; it is there for kernels with more than five
parameters. `params` says how each is passed: `ByPtr("f32")` is a buffer,
`ByValue("f32")` a scalar the launch hands over (`i32`, `i64`, `f32` or
`f64`), which the body reads with `scalar(p)` and never through memory. `launch_entryN` refuses an `Out` or `Shared` argument that
aliases another argument, a grid that disagrees with the cells and a tensor
shorter than its cells, before any handler runs.

## Writing a kernel

A kernel names no shape it can read off its operands. The cells say where a
block reads and writes, element-wise operations take their shape and format
from their operands, and a matrix product's from its two factors:

```dawn
use tileir/dev.{Dev, Param, load_at, store_cell, zeros, mma, d_range}
use tileir/prog.{trace3, cells, In, Out, FREE_AXIS}

fn matmul(a: Param[Float], b: Param[Float], c: Param[Float]) -> Unit !Dev = {
  var acc = zeros(c)
  for k in d_range(0, 256 / 32) { acc = mma(load_at(a, [k]), load_at(b, [k]), acc) }
  store_cell(c, acc)
}

let (prog, entry) = trace3("matmul",
  In(F64, cells([256, 256], [64, 32], along: [0, FREE_AXIS])),
  In(F64, cells([256, 256], [32, 64], along: [FREE_AXIS, 1])),
  Out(F64, cells([256, 256], [64, 64])), matmul)
```

- `load_cell(p)` reads this block's cell; `load_at(p, [k])` names the cell
  along each `FREE_AXIS` dimension. Lanes past the extent read the marker's
  `pad`, so a tail needs no mask.
- `store_cell(o, t)` writes this block's cell of an `Out`;
  `store_sub(o, [i, j], t)` writes one piece of it, shaped like `t`. These
  are the only writes an `Out` takes: a `store`, `scatter`, atomic or
  `store_view` into one is refused while recording.
- `zeros(p)` and `fill(p, v)` are a tile shaped like a cell of `p`, the
  accumulator a block starts from. `full(shape, v)` is a float tile of any
  shape whose format is the one it is checked against:
  `let m: Tile[F32] = full([BQ, 1], 0.0)`.
- A constant is rank 0: `f_const(F64, 0.5)`, `i_const(3)`. `lit(0.5)` is
  a float constant with no format, which takes the format of the
  element-wise operation it meets (`mul(s, lit(0.5))`; write it after a
  typed operand, since the checker finds the format left to right); a
  place that needs a format of its own refuses it and asks for `f_const`.
- An operand of an element-wise operation widens on its own in two cases: a
  rank-0 tile widens to any shape, and a tile of the operation's rank widens
  along its dimensions of length 1, so `sub(s, reduce_max(s, keepdims:
  true))` needs nothing more. A tile of another rank is refused (a
  reduction without `keepdims` dropped the dimension it would line up by).
  `broadcast(t, shape)` widens explicitly, for places that are not
  element-wise (a loop's starting value); places that need a rank-0 tile (a
  condition, a loop bound, a cell index) refuse a wider one.
- `Idx` arithmetic is `idx_add`, `idx_sub`, `idx_mul`, `idx_div` and
  `idx_rem` (signed, toward zero): a grid axis that holds a head and a
  group folded together is read back as `idx_div(b, g)` and `idx_rem(b, g)`.
- `mma(a, b, acc)` is the matrix product `a * b + acc`. `a` and `b` share
  a format and `acc` may have another, from the dialect's table: f8E4M3FN,
  f8E5M2 and f16 operands into f16 or f32, bf16, tf32 and f32 into f32,
  f64 into f64. A `lit(0.0)` accumulator takes the accumulator's format, so
  it needs one from the context: `let s: Tile[F32] = mma(a, b, lit(0.0))`.
  `mma_scaled` is the block-scaled product and `mmai` the i8 one.
- `t.to(BF16)` converts a float tile, rounding to nearest even (a tile
  already in that format is answered unchanged); `float_to_float` takes the
  other roundings. `t.transpose()` swaps a rank-2 tile's dimensions;
  `permute_tile(t, perm)` reorders any rank.
- `reshape(t, shape)` regroups `t`'s lanes into `shape`, row-major, as
  many lanes as before: a `[T, T]` product goes into a `[1, T, T]` cell as
  `store_cell(o, reshape(acc, [1, T, T]))`. No write reshapes on its own.
- `reduce_sum`, `reduce_max`, `reduce_min` and `scan_sum` take `dim:` (the
  last by default) and `keepdims:`; `d_reduce` and `d_scan` take a body for
  any other fold. A rank-1 tile reduces to rank 0.
- `retile(p, extent, tile)` is a second view of a parameter a kernel reads
  two ways, as a grid view `load_view` reads at any index.
- The pointer path is still there for what no cell describes:
  `load(p, base, shape, strides:, mask:, pad:, hints:)` and
  `store(p, base, t, strides:, mask:, hints:)`, `gather`, `scatter`, the
  atomics, `tensor_view` and the views cut from it. A memory operation takes
  an element offset: `tile_at(idx, n)` is `idx * n`.
- An operation's attributes are named parameters with the dialect's default:
  `add(a, b, rounding: Down)`, `d_global("t", F64, xs, visibility: Private)`.
  Float arithmetic is `add`, `sub`, `mul`, `div`, `max`, `min`, `neg`, `abs`,
  and `+ - * /` and unary `-` on tiles (and on `Idx`) are the same calls: over
  an integer tile they record the integer operations. Importing `max` and
  `min` shadows the prelude's in that module.
- Memory operations are ordered by the token chain the recorder threads
  through them, not by program order. `d_fork2` runs two chains, and writes
  it cannot show to be disjoint are refused.

## Control flow

A value that changes as a loop goes is a `var`, which a `for` over a
`d_range` carries: `var acc = zeros(p)`, then `acc = t` in the body replaces it
with a tile of the same format and shape, and after the loop it holds what the
last iteration assigned. A `var` starts from a tile with a shape (`zeros(p)`,
`full`, a `broadcast`), not from a rank-0 constant or a `lit`. This is
FlashAttention with bf16 inputs and f32 accumulation:

```dawn
use std/float.{INFINITY}

var m: Tile[F32] = full([BQ, 1], -INFINITY)
var l: Tile[F32] = full([BQ, 1], 0.0)
var acc: Tile[F32] = full([BQ, D], 0.0)
for j in d_range(0, N / BK) {
  let s: Tile[F32] = mma(tq, load_at(k, [j]).transpose(), lit(0.0)) * lit(scale)
  let m_new = max(m, reduce_max(s, keepdims: true))
  let p = exp(s - m_new)
  let alpha = exp(m - m_new)
  l = l * alpha + reduce_sum(p, keepdims: true)
  acc = mma(p.to(BF16), load_at(v, [j]), acc * alpha)
  m = m_new
}
store_cell(o, (acc / l).to(F64))   # o: Param[Float]
```

`carry`, `get` and `set` remain for the loops a `for` cannot write: `d_loop`'s
body is a closure with a data-dependent exit.

- `for j in d_range(lower, upper, step: By(n), unsigned_cmp: false) { .. }` is
  a loop. The bounds are host numbers (`Int`, fixed when the kernel is
  recorded) or `Idx` values the device computes; the step is `One` by default,
  or `By(n)` of the same kind as the bounds, so a grid-stride loop writes
  `step: By(nprog)`. The induction variable is always an `Idx`.
  (`extent_of(p, dim)` and `blocks_of(p, dim)` are a parameter's extent and
  its number of cells along a dimension.)
- `d_loop { .. }` runs until its body answers a true rank-0 mask. On the
  iteration that answers true the loop stops with the carries as they
  entered it, so compute the mask before the `set`s.
- `d_if(cond, () => .., () => ..)` runs one of two regions, neither of which
  may load or store; a carry either sets is the `if`'s answer, and a branch
  that does not set it keeps what it held.

A region carries a carry only if its body sets it, and carries those in the
order they were made; one the body only reads is the tile it held outside,
and a loop that sets nothing carries nothing but the memory token. The recorder finds
them by recording the body once as a trial and discarding it, so a body runs
twice on the host (2^n times n regions deep). A body is otherwise ordinary
Dawn: host `if` and `for` in it unroll while recording.

Nesting is capped at `MAX_LOOP_DEPTH` (16) and one recording at
`MAX_HANDLES` (65536) handles; past either the recording panics.

## Occupancy

A 128 by 128 f16 matrix product on sm_86 holds one block per SM by default
(65568 bytes of shared memory) and is slower than the pointer path it
replaces; with `hint_occupancy(2)` it fits two (49184 bytes) and is faster.
Give such a kernel `hints: [for_arch("sm_86", [hint_occupancy(2)])]`. The
measurement is in §6.26 of the design document.

## What the recorder refuses

Each value handle has a format and a shape, and every element-wise operand is
held to the shape the operation takes from its operands (after the rank-0
and same-rank rules), as is the `k` of `mma`, `mma_scaled` and `mmai` and the format pair of
`mma`. A mismatch panics
while the kernel records, naming the operation by its depth-first number in
`TileProg.ops` (`MakeToken(0)` is #0), for example:
``tileir: kernel `vadd_half`: op #6 `addf`: rhs is tile<128xf64>, declared tile<64xf64>``.

## Assembling with tileiras (#558)

Neither this package nor `std/gpu` runs `tileiras`: you assemble the bytes
and hand `with_gpu_real` the cubins. **With tileiras 13.4.92, pass
`--opt-level 0` when assembling for sm_90, sm_100, sm_103, sm_107 or
sm_110.** At the default level that assembler stores a wrong loop exit value
for a loop that leaves through `break` with two carried values
([#558](https://github.com/dawnop/dawn-lang/issues/558),
[NVIDIA/cuda-tile#25](https://github.com/NVIDIA/cuda-tile/issues/25)). Other
targets, and other tileiras versions, keep the default level. Ask `asm`
rather than hard-coding this, so the workaround lifts when you move to a fixed
tileiras:

```dawn
use tileir/asm.{tileiras_args, assembler_defect}

let args = tileiras_args("13.4.92", "sm_90")   # ["--gpu-name", "sm_90", "--opt-level", "0"]
let why = assembler_defect("13.4.92", "sm_90") # Some("tileiras 13.4.92 miscompiles ...")
# then: tileiras <args> -o kernel.cubin kernel.tilebc
```

`-O0` costs device time: measured on sm_86, up to 4.5x for kernels that
compute and 8x for a small loop (§6.28).

## Writing your own `Dev` handler

A handler has to answer every operation of `Dev`, so a new operation is a
version bump (see the changelog). What a handler owes the ones that issue
nothing:

- `t_call_enter(name)` / `t_call_exit()` and `t_body_enter()` /
  `t_body_exit()`: answer `()` and record nothing. The call pair wraps the
  body of each public function; the body pair wraps each closure a public
  function takes. `prog.trace_calls` uses them to attribute operations to
  the calls the kernel wrote; `render.line_map` refuses a program whose
  operations fall outside any pair.
- `t_shape_of(h)`: answer the format and shape of handle `h` (rank 1 or more).
  The named reductions and `broadcast` read it.
- `t_cell_view`, `t_sub_view`, `t_cell_fill`, `t_retile` and `t_extent_of`
  read a parameter's marker; a handler with no markers should refuse them.
- `t_carry_new`, `t_carry_get`, `t_carry_set` keep the carries, and
  `t_trial_begin` / `t_trial_end` bracket a trial: `t_trial_end` answers
  the carries made before the trial that were set during it, in the order
  they were made, and puts every piece of the handler's state back as it
  was at `t_trial_begin`.

Changes between versions: [CHANGELOG.md](CHANGELOG.md). Design, measurements
and the bytecode format:
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).
