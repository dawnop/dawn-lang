# packages/tileir

A pure Dawn generator of CUDA Tile IR that records a kernel body written against the `Dev` effect and emits it as `cuda_tile` text or as bytecode `tileiras` can assemble.

A kernel body is an ordinary Dawn function whose only effect is `Dev`.
Recording it once yields a `TileProg`, which `render` prints as `cuda_tile`
text and `encode` writes as bytecode. Buffers and launches are `std/gpu`'s,
and so are the format markers (`F64`, `BF16`, ...).

```dawn
use std/gpu.{F64}
use tileir/dev.{Dev, Param, load_cell, store_cell, addf, DYN_DIM}
use tileir/prog.{trace3, cells, In, Out}
use tileir/render.{render}
use tileir/bytecode.{encode}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(a), load_cell(b)))

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
- `cells(extent, tile, pad: PadZero, along: ..)` cuts the tensor. An extent
  of `DYN_DIM` is the grid's to decide; `pad` is what a read past the extent
  answers; `along[j]` is the grid axis dimension `j` follows, or `FREE_AXIS`
  when the kernel picks that cell itself.

`trace_kernel(name, formats, body)` records a body over `param(d, pos)`
handles, every one `Shared`; it is there for kernels with more than five
parameters. `launch_entryN` refuses an `Out` or `Shared` argument that
aliases another argument, a grid that disagrees with the cells and a tensor
shorter than its cells, before any handler runs.

## Writing a kernel

A kernel names no shape it can read off its operands. The cells say where a
block reads and writes, element-wise operations take their shape and format
from their operands, and a matrix product's from its two factors:

```dawn
use tileir/dev.{Dev, Param, load_at, store_cell, zeros, mmaf, d_range}
use tileir/prog.{trace3, cells, In, Out, FREE_AXIS}

fn matmul(a: Param[F64], b: Param[F64], c: Param[F64]) -> Unit !Dev = {
  let acc = d_range(0, 256 / 32, zeros(c), (k, sofar) => mmaf(load_at(a, [k]), load_at(b, [k]), sofar))
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
  accumulator a block starts from.
- A constant is rank 0: `f_const(F64, 0.5)`, `i_const(3)`. A rank-0 tile
  widens on its own wherever an operation meets a wider one, and nowhere
  else: `broadcast(t, shape)` widens dimensions of length 1 explicitly, and
  places that need a rank-0 tile (a condition, a loop bound, a cell index)
  refuse a wider one.
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
  `addf(a, b, rounding: Down)`, `d_global("t", F64, xs, visibility: Private)`.
- Memory operations are ordered by the token chain the recorder threads
  through them, not by program order. `d_fork2` runs two chains, and writes
  it cannot show to be disjoint are refused.

## Control flow

`d_range(lower, upper, init, (k, acc) => ...)` is a loop over host bounds
carrying one tile; `d_for(lower, upper, step, init, ..)` takes `Idx` bounds
the device computes, and `d_for2` to `d_for4` carry more. A carried value
keeps its format and shape: start it from `zeros(p)` or a `broadcast`, not
from a rank-0 constant. `d_loop` runs until its body answers true; `d_if`
takes two regions that answer the same format and shape, and neither may
load or store. The body runs once on the host and what it emits lands in the
region.

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
rule), as is the `k` of `mmaf`, `mmaf_scaled` and `mmai`. A mismatch panics
while the kernel records, naming the operation by its depth-first number in
`TileProg.ops` (`MakeToken(0)` is #0), for example:
``tileir: kernel `vadd_half`: op #6 `addf`: rhs is tile<128xf64>, declared tile<64xf64>``.

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
- `t_cell_view`, `t_sub_view`, `t_cell_fill` and `t_retile` read a
  parameter's marker; a handler with no markers should refuse them.

Changes between versions: [CHANGELOG.md](CHANGELOG.md). Design, measurements
and the bytecode format:
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).
