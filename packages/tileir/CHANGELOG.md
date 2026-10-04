# tileir changelog

Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3), and a new `Dev` operation moves the minor:
a handler written outside the package does not compile until it answers it.
Section numbers refer to
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).

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
