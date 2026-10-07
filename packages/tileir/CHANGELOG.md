# tileir changelog

Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3), and a new `Dev` operation moves the minor:
a handler written outside the package does not compile until it answers it.
Section numbers refer to
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).

## 0.12.0 (2026-10-07)

Breaking: runtime scalar kernel parameters (`docs/tileir-k4-design.md`,
knives 1 and 2).
Every one of the 195 existing `.mlir` and `.tilebc` goldens is unchanged on
both backends.

- An entry parameter says how it is passed. `TileProg.params` and
  `Kernel.params` are `List[KParam]`, `KParam = ByPtr(dtype) | ByValue(dtype)`,
  where they were `List[String]` and every parameter a pointer. `trace_kernel`
  and `trace_calls` take the list: `["f64", "f64"]` is
  `[ByPtr("f64"), ByPtr("f64")]`. A `ByValue` parameter is a rank-0
  `tile<dtype>` in the entry signature, with no instruction and no value of
  its own: the entry parameter is the tile.
- `scalar(p)` reads a by-value parameter as a rank-0 tile. Arithmetic with it
  follows the rank-0 rule, so `load(x, ..) * scalar(s)` scales a tile by a
  value the launch picks, and `idx_of(scalar(n))` is a runtime extent.
  `scalar` is bounded by `std/gpu`'s new `ScalarDtype` (`I32`, `I64`, `F32`,
  `F64`), its own trait and not `HasDtype` because Dawn has no supertraits.
  An opaque type inherits only `Eq`, `Hash` and `Ord` from its target, so
  `scalar(param(F16, 0))` does not check. What a type cannot say is still
  refused when the kernel records: a `ByValue` of any format but `i32`,
  `i64`, `f32` and `f64`, whether named by a string or by a `Scalar(F16)`
  marker. A new `Dev`
  operation, `t_scalar`: a handler written outside the package must answer
  it. The recording also refuses `scalar` of a buffer or of another format,
  and refuses `load`, `store`, `gather`, `scatter`, atomics, pointers and
  views of a by-value parameter.
- Three kernels in `scripts/tile-golden` (`scalar_scale`, `scalar_len`,
  `scalar_wide`) assemble under `tileiras` 13.4.92 for sm_86 and read the
  right values on the RTX 3080, including the 64-bit formats and an `i32`
  whose argument word has garbage in its high half.
- `Scalar(F32)` is the fourth marker of `trace1` to `trace5`, beside `In`,
  `Out` and `Shared`: the parameter is a `ByValue`, has no cells, and the
  entry the recorder answers takes a scalar at that position
  (`std/gpu`'s `arg_scalar`). `launch_entryN` takes `Launch[A]` arguments,
  `buffer(t)` or `scalar(v)`, and holds each position to the kind the entry
  says (`gpu.bad_entry`). Needs the `std/gpu` of the same release: `launch`
  takes `List[LaunchArg]` (`erase(buffer(t))`, `erase(scalar(v))`) and the
  fake device's `WideRefFn` takes the launch's scalars as a third argument.
- Measured on the device: `scripts/tile-gpu-diff/scalar_diff.dawn` runs the
  four scalar kernels (`scalar_scale`, `scalar_len`, `scalar_loop`,
  `scalar_wide`) bit for bit against the fake device, each cubin on several
  values, with the upper half of the argument word garbage in three cases
  (the device does not read it). A scalar parameter costs about 0.4
  microseconds per launch more than a baked constant and about 0.35 less
  than a one-element buffer on sm_100, and the two compile alike
  (`docs/tileir-k4-design.md` 1.2). `ScalarArg` is the one new operation;
  no opcode, so `scripts/tileir-features` is unchanged.

## 0.11.0 (2026-10-07)

Breaking: a kernel's loops, carried values, arithmetic and formats are
written the way the language writes them, and the format markers are gone.
Needs a compiler whose std has `std/float`, `std/dtype` and the witnesses in
`std/narrow` and `std/int/*` (the release after 0.85.0). Every kernel in
`scripts/tile-golden` records the bytes it did: the 195 `.mlir` and `.tilebc`
goldens are unchanged on both backends.

- A loop is `for j in d_range(lower, upper) { .. }`. `d_range` takes `Int`
  bounds (fixed when the kernel is recorded) or `Idx` bounds (computed on the
  device), `step: One` by default or `By(n)` (`By(nprog)` for a grid-stride
  loop), and `unsigned_cmp`. It replaces both the closure form of `d_range`
  and `d_for`, which is deleted. The body of a `for` carries the `var`s it
  assigns: `var acc = zeros(c)` and `acc = mma(.., acc)` are `carry`, `get`
  and `set`, which stay public for `d_loop`.
- `+ - * /` and unary `-` work on tiles and on `Idx`, a float literal on a
  tile is `lit`, an integer literal on an `Idx` is `idx_const`. Over a float
  tile they record the float operations, over an integer tile the integer
  ones (`addi`, `subi`, `muli`, `divi`, `negi`).
- A float operation (`add`, `neg`, `exp`, ...) over an integer tile is now
  refused when the kernel is recorded. Before, `add` over a `Tile[I32]`
  recorded an `addf` over an i32 tile and nothing refused it (#591).
- A format is a value type with a witness of the same name. `Tile[F64]`,
  `Param[F64]`, `Tensor[F64]` are `Tile[Float]`, `Param[Float]`,
  `Tensor[Float]`; `I64` is `Int` and `I1` is `Bool` in type position. The
  witnesses `F64`, `I64`, `I1` come from `std/dtype`, `BF16`, `F16`, `F32`,
  `TF32`, `F8E4M3FN`, `F8E5M2`, `F8E8M0FNU`, `F4E2M1FN` from `std/narrow`,
  `I8`, `I16`, `I32`, `U8` from `std/int/*`, and `I4` from `std/gpu`. Calls
  that name a format (`param(F64, 0)`, `In(BF16, ..)`, `f_const(F32, 0.5)`,
  `p.to(BF16)`) are spelled as before; only the `use` lines change.
  `std/narrow`'s `FP16` is `F16` (`f16`, `round_f16`, `f16_bits`,
  `f16_of_bits`). The `param`/`f_const`/`to`/`unpack_bytes`/`d_global`
  family takes a `Dtype[T]` instead of a marker with a `Dtype` bound.
- `FloatDtype::float_dtype` answers a `Dtype[D]`, and `float_name` is gone:
  write `dtype_name(float_dtype())`. `I1` is no longer declared here.
- `-INFINITY` and `INFINITY` come from `std/float`; the kernels' and the
  reference's private negative infinity are gone.

## 0.10.0 (2026-10-06)

Breaking: the float matrix product is `mma` and takes an accumulator of
another format, and `Dev`'s `t_mmaf` gains that format: a handler written
outside the package must answer `t_mmaf(dtype, acc, m, k, n, a, b, c)`.
Every kernel in `scripts/tile-golden` records the bytes it did; the new
`flash_attn_bf16` is the one new golden. §6.31.

- `mma[A, C](a: Tile[A], b: Tile[A], acc: Tile[C]) -> Tile[C]` replaces
  `mmaf`. The operands share a format and the accumulator may have another,
  as the dialect's table allows: f8E4M3FN, f8E5M2 and f16 operands into an
  f16 or f32 accumulator, bf16, tf32 and f32 into f32, f64 into f64. The
  recording refuses any other pair and lists these. bf16 operands with an
  f32 accumulator assemble for sm_86's tensor cores.
- `mmaf_scaled` is `mma_scaled`. `mmai` keeps its name: its formats are
  fixed and its tier is exact, as `addi` keeps its `i` beside `add`.
- `full(shape, value)`: a float tile of `shape` in the format it is checked
  against, `let m: Tile[F32] = full([32, 1], 0.0)`. It records what
  `broadcast(f_const(F32, 0.0), [32, 1])` does.
- `t.to(fmt)`: `float_to_float` at nearest even, answering `t` unchanged
  and recording nothing when it is already in `fmt`.
- `t.transpose()`: `permute_tile(t, [1, 0])` for a rank-2 tile.
- New trait `FloatDtype[D]` (`float_dtype()`, `float_name(d)`) for the
  seven arithmetic float formats: how `full` and `mma` learn a format from
  the type alone. A kernel generic in its format bounds it with
  `[D: FloatDtype]` to call either with a `Tile[D]` in hand.
- `prog.MmaF` carries the accumulator's format as `out`, and
  `prog.mma_accumulators(dtype)` answers the table.

| 0.9 | 0.10 |
|---|---|
| `mmaf(a, b, c)` | `mma(a, b, c)` |
| `mmaf_scaled(a, b, c, sa, sb)` | `mma_scaled(a, b, c, sa, sb)` |
| `carry(broadcast(f_const(F64, 0.0), [32, 1]))` | `let c: Carry[F64] = carry(full([32, 1], 0.0))` |
| `float_to_float(p, BF16)` | `p.to(BF16)` |
| `permute_tile(t, [1, 0])` | `t.transpose()` |

A module that defines its own `transpose`, `full` or `to` and imports the
whole of these from `tileir/dev` now has a clash; `scripts/tile-golden`'s
`transpose` kernel function is `transpose_matrix` for that reason.

## 0.9.0 (2026-10-06)

Breaking: loops and `if`s carry device variables instead of tuples, and the
float arithmetic has one naming scheme. `Dev` gains `t_carry_new`,
`t_carry_get`, `t_carry_set`, `t_trial_begin`, `t_trial_end` and
`t_extent_of`; a handler written outside the package must answer them.
Every kernel in `scripts/tile-golden` records the bytes it did, except
three: in `flash_attn` and `loop_bound` one carried value's starting tile is
now recorded before the loop's bounds rather than after them, and
`grid_stride`'s loop no longer carries the constant it handed back unchanged
(0.8's `d_range` had to carry one tile). §6.30.

- `carry(init)` makes a `Carry[D]`, a device variable; `c.get()` reads it
  and `c.set(t)` replaces it, at the same format and shape. `d_range`,
  `d_for`, `d_loop` and `d_if` take bodies that answer `Unit` (`d_loop`'s
  answers its stop mask) and carry the carries their bodies set, in the
  order they were made. The recording finds them by running the body once
  as a trial and discarding what the trial recorded, so a region nested `n`
  deep records its innermost body 2^n times.
- `d_range(lower, upper, step: 1) { j => .. }` and
  `d_for(lower, upper, step, unsigned_cmp: false) { j => .. }`: the body is
  the last parameter, so it is written as a tail block.
- `d_for2`, `d_for3`, `d_for4`, `d_loop2` and the value-answering `d_if` are
  gone.
- Float `addf`, `maxf` and `minf` are `add`, `max` and `min`, beside `sub`,
  `mul`, `div`, `neg` and `abs`. The integer families (`add_i`, `addi`, ...)
  are unchanged. A module that imports `max` or `min` from `tileir/dev`
  shadows the prelude's for host `Int`s too; `list.max` is unaffected.
- `extent_of(p, dim)` and `blocks_of(p, dim)`: the extent of a parameter's
  tensor along `dim` and its number of cells there, as an `Idx`: a constant
  for a static dimension, the grid's blocks along the axis it follows for a
  `DYN_DIM` one.
- New module `asm` (#558): `tileiras_args(version, gpu_name)` answers the
  arguments to assemble with, and `assembler_defect(version, gpu_name)`
  explains them. tileiras 13.4.92 miscompiles a loop exit value on sm_90,
  sm_100, sm_103, sm_107 and sm_110 at `--opt-level` 1 and above
  ([NVIDIA/cuda-tile#25](https://github.com/NVIDIA/cuda-tile/issues/25)), so
  for those targets the answer includes `--opt-level 0`. The table is keyed
  on the exact tileiras version, so a fixed release gets the plain
  arguments. It changes neither `Dev` nor the bytes `encode` writes. §6.28.

| 0.8 | 0.9 |
|---|---|
| `let acc = d_range(0, n, zeros(c), (k, s) => mmaf(a, b, s))` | `let acc = carry(zeros(c))` then `d_range(0, n) { k => acc.set(mmaf(a, b, acc.get())) }` |
| `let (x, y) = d_for2(lo, hi, st, x0, y0, (k, x, y) => (f(x), g(y)))` | `let x = carry(x0)`, `let y = carry(y0)`, then `d_for(lo, hi, st) { k => .. }` whose body sets `x` to `f(x.get())` and `y` to `g(y.get())` |
| `d_loop(v0, v => (done(v), next(v)))` | `let v = carry(v0)` then `d_loop { .. }` whose body computes `done(v.get())`, sets `v` to `next(v.get())` and answers the mask |
| `let r = d_if(c, () => a, () => b)` | `let r = carry(a)` then `d_if(c, () => (), () => r.set(b))` |
| `d_for(.., init, body, unsigned_cmp: true)` | `d_for(.., unsigned_cmp: true) { k => .. }` |
| `addf(a, b)`, `maxf(a, b)`, `minf(a, b)` | `add(a, b)`, `max(a, b)`, `min(a, b)` |

## 0.8.2 (2026-10-06)

Additions only: `Dev` is unchanged, and every program that recorded before
records the same bytes. §6.29.

- `idx_div`, `idx_rem` and `idx_sub`: the quotient (signed, toward zero),
  the remainder and the difference of two `Idx`. They issue the `divi`,
  `remi` and `subi` that `div_i`, `rem_i` and `sub_i` already did, on the
  rank-0 i32 tile an `Idx` is. A grid axis that holds two indices folded
  together (`head * G + group`) is read back out with them.
- Same-rank broadcasting: an operand of an element-wise operation whose
  shape differs from the operation's only in dimensions of length 1 is
  broadcast to it, so `sub(s, reduce_max(s, keepdims: true))` needs no
  `broadcast`. A difference in rank is still refused (rank 0 aside): a
  reduction that dropped the dimension does not line up by trailing
  dimensions. The broadcast is recorded where an explicit `broadcast` in the
  last argument would have been.
- `lit(v)`: a float constant with no format, which takes the format and the
  shape of the element-wise operation it meets: `mul(s, lit(0.5))`. Write it
  after a typed operand (the checker finds `D` from left to right) or under
  an annotation. A place that needs a format of its own (a `broadcast`, a
  reduction, a store, an integer operation) refuses it by name and says to
  write `f_const`.

## 0.8.1 (2026-10-05)

`reshape(t, shape)` regroups a tile's lanes into another shape of as many,
in row-major order, as Tile IR's `reshape` does; the recording refuses a
shape that holds another number of lanes or has a dimension that is not a
power of two. It wraps the `t_reshape` that `keepdims` already issued, so
`Dev` is unchanged and a handler written outside the package compiles as
before. Adds a name only.

An `Out` takes the `along` an `In` already did: dimension `j` follows grid
axis `along[j]`, any injection into the three axes, no `FREE_AXIS`, and an
axis no dimension follows has one block. Before, any `along` but the
identity was refused. Every program that recorded before records the same
bytes. §6.27.

## 0.8.0 (2026-10-05)

Breaking: the one-time migration of the batch's PR-3 (§6.26). A kernel no
longer states a shape or a format it can read off its operands, `Scalar[D]`
is `Tile[D]` at rank 0, and an `Out` is written only through its cells.

- Element-wise operations, comparisons, conversions, selects, `mmaf` /
  `mmai` / `mmaf_scaled`, `extract`, `insert`, `cat`, `permute_tile`, the
  pointer ladder, the views and the debugging operations drop their leading
  format and shape arguments (C3). A conversion takes the tile first and the
  target format second.
- `Scalar[D]` is gone: a rank-0 `Tile[D]` is what a constant, a reduction of
  a rank-1 tile and an index read as a tile are. A rank-0 operand widens on
  its own where it meets a wider one; no other widening is implicit
  (`broadcast`). A place that needs rank 0 (a condition, a loop bound, a
  cell index, `d_return_if`) refuses a wider tile (C3′).
- Constants take no shape: `f_const(d, v)`, `i_const(v)` and the rest record
  nothing until they are used, and are materialised at the shape of the use.
- `store_cell(o, t)` and `store_sub(o, at, t)` are the only writes an `Out`
  takes; a `store`, `scatter`, atomic, `store_ptrs` or `store_view` into one
  is refused while recording, and so is a write through untraceable
  pointers in a kernel that has an `In` or an `Out` (D-7). `zeros(p)` and
  `fill(p, v)` make a cell-shaped tile.
- `d_range(lower, upper, init, body)` is `d_for` over host bounds; a loop's
  carried value and an `if`'s two answers must keep their format and shape.
  `retile(p, extent, tile)` is a second, read-only view of a parameter (C4).
- `Dev` gains `t_sub_view` and `t_retile`.

| 0.7.0 | 0.8.0 |
|---|---|
| `addf(F64, s, a, b)`, `sub`, `mul`, `exp(F64, s, a)`, ... | `addf(a, b)`, `sub(a, b)`, `exp(a)`, ... |
| `eq(F64, s, a, b)`, `eq_i(s, a, b)`, `add_i(s, a, b)` | `eq(a, b)`, `eq_i(a, b)`, `add_i(a, b)` |
| `addi(I16, s, a, b)`, `select(F64, s, c, a, b)` | `addi(a, b)`, `select(c, a, b)` |
| `int_to_float(I32, F64, s, t)`, `float_to_int(..)`, `float_to_float(..)` | `int_to_float(t, F64)`, `float_to_int(t, I32)`, `float_to_float(t, F32)` |
| `mmaf(F64, m, k, n, a, b, c)`, `mmai(m, k, n, a, b, c)`, `mmaf_scaled(..)` | `mmaf(a, b, c)`, `mmai(a, b, c)`, `mmaf_scaled(a, b, c, sa, sb)` |
| `f_const(F64, s, v)`, `consti(I16, s, v)`, `i_const(s, v)` | `f_const(F64, v)`, `consti(I16, v)`, `i_const(v)` |
| `spread(F64, s, x)` | `broadcast(x, s)` |
| `s_addf`, `s_mulf`, `s_maxf`, `s_minf`, `s_fma`, `s_eq`, `s_gt`, `s_select`, `s_const` | `addf`, `mul`, `maxf`, `minf`, `fma`, `eq`, `gt`, `select`, `f_const` |
| `s_addi`, `s_maxi`, `s_le_i`, `s_consti` | `add_i`, `max_i`, `le_i`, `i_const` |
| `idx_as_scalar(i)` | `idx_as_tile(i)` |
| `d_reduce(F64, s, t, id, f)`, `d_reduce_dim(F64, s, k, t, id, f)` | `d_reduce(t, id, f)`, `d_reduce(t, id, f, dim: k)` |
| `d_reduce_i`, `d_reduce_dim_i`, `d_scan_i` | `d_reduce(t, to_float(id), f)`, `d_scan(..)` |
| `d_scan(F64, s, dim, rev, t, id, f)`, `d_scan2(..)` | `d_scan(t, id, f, dim: k, reverse: r)`, `d_scan2(..)` |
| `extract(F64, s, to, t, i)`, `insert(F64, sub, whole, s, t, i)`, `cat(F64, dim, l, r, a, b)`, `permute_tile(F64, s, perm, t)` | `extract(t, to, i)`, `insert(s, t, i)`, `cat(a, b, dim)`, `permute_tile(t, perm)` |
| `load_strided(p, b, s, st)`, `load_masked(p, b, s, m, z)`, `load_strided_masked`, `load_hinted` | `load(p, b, s, strides: Some(st), mask: Some(m), pad: Some(z), hints: h)` |
| `store(p, b, s, t)`, `store_strided`, `store_masked`, `store_strided_masked`, `store_hinted` | `store(p, b, t, strides:, mask:, hints:)` |
| `gather_masked(p, i, s, m, z)`, `scatter_masked`, `atomic_rmw_masked`, `atomic_add_masked`, `atomic_cas_masked` | `gather(p, i, mask: Some(m), pad: Some(z))`, `scatter(.., mask:)`, `atomic_rmw(.., mask:)`, `atomic_add(.., mask:)`, `atomic_cas(.., mask:)` |
| `ptr_offset(F64, s, ps, o)`, `load_ptrs(F64, s, ps)`, ... | `ptr_offset(ps, o)`, `load_ptrs(ps)`, ... |
| `tensor_view(F64, p, ..)`, `load_view(F64, v, ix)`, ... | `tensor_view(p, ..)`, `load_view(v, ix)`, ... |
| `d_assert(s, c, msg)`, `d_print(F64, f, xs)`, `assume_div_by(F64, s, n, t)`, ... | `d_assert(c, msg)`, `d_print(f, xs)`, `assume_div_by(t, n)`, ... |
| `store(o, b, s, t)` into an `Out` | `store_cell(o, t)` or `store_sub(o, at, t)` |
| `d_for(idx_const(0), idx_const(n), idx_const(1), init, f)` | `d_range(0, n, init, f)` (the old spelling still records the same) |

## 0.7.0 (2026-10-04)

- `load` and `store` take the pointer path's options as defaulted named
  arguments (`strides:`, `mask:`, `pad:`, `hints:`), so any combination is one
  call. `load_strided`, `load_masked`, `load_strided_masked`, `load_hinted` and
  the four matching stores remain, each one call of the merged function, and
  record what they recorded in 0.6.0.
- The view an `Out` is written through carries `assume div_by<16>`, as an
  `In`'s already did, so `store_cell` lowers differently. No signature
  changed. §6.25.

## 0.6.0 (2026-10-04)

`load_cell`, `load_at`, `store_cell`, `zeros`, `fill`; `reduce_sum`,
`reduce_max`, `reduce_min` and `scan_sum` with `dim:` and `keepdims:`;
`broadcast`; rank-0 widening. `Dev` gains `t_cell_view`, `t_cell_fill`,
`t_reshape` and `t_broadcast`, which is the only reason this is a minor and
not a patch: every function that existed keeps its signature and records the
same program. §6.25.

## 0.5.1 (2026-10-04)

Parameter markers: `trace1` to `trace5`, `In`, `Out`, `Shared`, `Arg`,
`Cells`, `cells`, `FREE_AXIS`, and typed entries for `std/gpu`'s
`launch_entryN`. Adds names only. §6.24.

## 0.5.0 (2026-10-03)

`Dev` gains `t_body_enter` / `t_body_exit`, and `prog.trace_calls` keeps the
kernel's calls as a tree, each region call over the calls in its closure.
Operations are numbered depth first, a region before its body; before, a
`Call`'s range counted top-level operations and a region's body was one row.
§6.23.

## 0.4.0 (2026-10-03)

`Dev` gains `t_shape_of(h)`. Views and view reads get rows in the handle
table, so a view passed where a tile belongs is refused, as is an `mmaf`,
`mmaf_scaled` or `mmai` whose `k` disagrees with its operands. §6.22.

## 0.3.2 (2026-10-03)

Doc comments. No behaviour change.

## 0.3.1 (2026-10-03)

The recorder refuses element-wise operands that disagree with what the
operation declares, and `d_fork2` writes it cannot show to be disjoint,
naming the operation by its depth-first number. Before, only `tileiras`
refused such a program. §6.21.

## 0.3.0 (2026-10-03)

`Dev` gains `t_call_enter` / `t_call_exit`; `prog.trace_calls` and
`render.line_map` say which public call issued which line.

## 0.2.0 (2026-10-02)

The attribute variants are defaulted named parameters: `addf(F32, s, a, b,
rounding: Down)` for `addf_down`, `float_to_int(..., saturating: true)` for
`float_to_int_sat`, `d_global(..., visibility: Private)` for
`d_global_private`, `trace_kernel(..., hints: hs)` for
`trace_kernel_hinted`, and so on; the 24 suffixed functions are gone. The
recorded IR does not change. Rationale:
[`docs/std-defaults-design.md`](../../docs/std-defaults-design.md) §7.2.

## 0.1.0 (2026-09-02)

The `Dev` effect, the recording handler and the Tile IR text renderer.
