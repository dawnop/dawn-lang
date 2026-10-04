# tileir changelog

Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3), and a new `Dev` operation moves the minor:
a handler written outside the package does not compile until it answers it.
Section numbers refer to
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).

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
