# packages/tileir

A pure Dawn generator of CUDA Tile IR that records a kernel body written against the `Dev` effect and emits it as `cuda_tile` text or as bytecode `tileiras` can assemble.

A kernel body is an ordinary Dawn function whose only effect is `Dev`.
Recording it once yields a `TileProg`, which `render` prints as `cuda_tile`
text and `encode` writes as bytecode. Buffers and launches are `std/gpu`'s,
and so are the format markers (`F64`, `BF16`, ...).

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
let text = render(prog)     # cuda_tile text
let bytes = encode(prog)    # bytecode for tileiras
```

| Module | Contents |
|------|------|
| `dev` | the `Dev` effect, the opaque handle types (`Tile[D]`, `Param[D]`, `Idx`, `Scalar[D]`, views, ...) and the typed functions a kernel calls |
| `prog` | `TileProg`; `trace_kernel`, `trace_calls` and `trace1` to `trace5`, the recording handlers |
| `lower` | `lower(prog)`, the linear instruction table |
| `render` | `render(prog)`, the `cuda_tile` text; `line_map` |
| `bytecode` | `encode(prog)`; `bytecode_version()` is `"13.4"` |

The full public surface is what `./bin/dawn doc packages/tileir` prints.

## Writing a kernel

- A memory operation takes an element offset: `tile_at(idx, n)` is `idx * n`.
- A shape is a list of powers of two; `[]` is a rank-0 tile (`Scalar[D]`).
- `trace_kernel(name, params, body)` takes each entry parameter's format by
  position; a `param(d, pos)` that disagrees with it panics.
- An operation's attributes are named parameters with the dialect's default:
  `addf(F32, s, a, b, rounding: Down)`, `d_global("t", F64, xs,
  visibility: Private)`.
- `load` and `store` take `strides:`, `mask:`, `pad:` and `hints:`, all
  defaulted: `load(p, base, shape, strides: Some([N, 1]))`,
  `load(p, base, shape, mask: Some(m), pad: Some(z))`. A `pad` without a
  `mask` is refused; a `mask` without a `pad` reads masked lanes as
  unspecified.
- Memory operations are ordered by the token chain the recorder threads
  through them, not by program order. `d_fork2` runs two chains, and writes
  it cannot show to be disjoint are refused.

## Control flow

`d_for(lower, upper, step, init, (k, acc) => ...)` is a loop over `Idx`
bounds carrying one tile (`d_for2` to `d_for4` carry more); the body runs
once on the host and what it emits lands in the loop's region. `d_if` takes
two regions that each answer a tile of the same shape and format and neither
may load or store.

```dawn
# block b folds `chunks` consecutive 128-wide tiles of x into one
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

Nesting is capped at `MAX_LOOP_DEPTH` (16) and one recording at
`MAX_HANDLES` (65536) handles; past either the recording panics.

## Parameters with cells

`trace1` to `trace5` take one marker per parameter instead of format names,
and answer an entry `std/gpu` can launch with typed arguments:

```dawn
use std/gpu.{F64, alloc, launch_entry3}
use tileir/prog.{trace3, cells, In, Out}

let g = cells([1024], [128])     # a tensor of 1024, cut into cells of 128
let (prog, entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
launch_entry3(entry, a, b, out)  # later, under a Gpu handler
```

- `In(d, cells)` is read only; a write into it is refused while recording.
  `In(d, Whole)` is an input read anywhere.
- `Out(d, cells)` is written one cell per block, and the `Out` cells are the
  launch grid; two `Out` parameters that make two grids are refused.
- `Shared(d)` is read and written freely, as every `trace_kernel` parameter is.
- `cells(extent, tile, pad: PadZero, along: ..)` cuts the tensor. `pad` is what
  a read past the extent answers; `along[j]` is the grid axis dimension `j`
  follows, or `FREE_AXIS`.

`launch_entryN` refuses an `Out` or `Shared` argument that aliases another
argument, a grid that disagrees with the cells and a tensor shorter than its
cells, before any handler runs.

A body recorded this way can address its parameters by cell:

```dawn
use tileir/dev.{
  load_cell, store_cell, exp, sub, div, reduce_max, reduce_sum, PadNegInf
}
use tileir/prog.{trace2, cells, In, Out}

fn softmax(x: Param[F64], o: Param[F64]) -> Unit !Dev = {
  # this block's [1024]; the lanes past 1000 read -inf
  let t = load_cell(x)
  let e = exp(F64, [1024], sub(F64, [1024], t, reduce_max(t)))
  # the lanes past 1000 are not written
  store_cell(o, div(F64, [1024], e, reduce_sum(e)))
}

let x = In(F64, cells([1000], [1024], pad: PadNegInf))
let o = Out(F64, cells([1000], [1024]))
let (prog, entry) = trace2("softmax", x, o, softmax)
```

- `load_cell(p)` reads this block's cell; `load_at(p, [k])` is the same when
  some dimensions follow no grid axis. `store_cell(o, t)` writes an `Out`'s
  cell. `zeros(p)` and `fill(p, v)` make a tile shaped like a cell of `p`.
- `reduce_sum`, `reduce_max`, `reduce_min` and `scan_sum` take `dim:` (the
  last by default) and `keepdims:`.
- A rank-0 tile widens on its own where an element-wise operation declares a
  wider shape; `broadcast(m, shape)` widens dimensions of length 1. Places
  that need a rank-0 tile (a condition, a loop bound, a cell index) refuse a
  wider one.

## What the recorder refuses

Each value handle has a format and a shape, and every element-wise operand is
held to what the operation declares, as is the `k` of `mmaf`, `mmaf_scaled`
and `mmai`. A mismatch panics while the kernel records, naming the operation
by its depth-first number in `TileProg.ops` (`MakeToken(0)` is #0), for
example:
``tileir: kernel `vadd_half`: op #6 `addf`: lhs is tile<128xf64>, declared tile<64xf64>``.

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
- `t_cell_view` and `t_cell_fill` read a parameter's marker; a handler with no
  markers should refuse them.

Changes between versions: [CHANGELOG.md](CHANGELOG.md). Design, measurements
and the bytecode format:
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).
