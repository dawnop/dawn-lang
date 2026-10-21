# tileinterp changelog

Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3).

## 0.2.1 (2026-10-21)

Models `exp2_ftz` (tileir 0.20.0): the input is flushed at the format's own
smallest normal, `2^x` is rounded into the format, and a subnormal result is
flushed, the way `addf_ftz` and `mulf_ftz` already are.

## 0.2.0 (2026-10-20)

Knife I2 (`docs/tileinterp-design.md` 7). Reads nothing new from
`packages/tileir`.

- Narrow float formats: f32, tf32, bf16, f16, f8E5M2, f8E4M3FN, f4E2M1FN and
  f8E8M0FNU lanes, rounded with `std/narrow` after every operation; `ftof`
  with its five roundings, `itof` into them, `bitcast`, `pack` and `unpack`
  over them (NaN payloads survive a bitcast). A kernel may read a buffer as a
  format of the same width (an f32 kernel over an i32 buffer).
- `fma`: one rounding, in binary64 (Boldo and Melquiond) and in the narrow
  formats.
- `mmaf`, `mmaf_scaled` and `mmai`. The accumulation order and rounding are a
  documented model, not a measurement of any device (design 7.1).
- Still refused by name: atomics, fences and PDL, strided and gather views,
  globals, `alloca`, `assert`, `print_tko`, pointer casts, f8E5M3FNU.
- `scripts/tileinterp-diff` covers 175 of 208 golden kernels (106 before),
  with the architecture-gated family added: the interpreter has no card to
  gate on.

## 0.1.0 (2026-10-20)

First release (`docs/tileinterp-design.md`, knife I1 of the 2026-10-20
ruling). Depends on `packages/tileir` 0.17.0 and reads only what that
version already makes public: `lower.lower`, `Kernel`, `Instr` and their
types.

- `interp.interp_ref(prog, grid, ub_checks: true) -> WideRefFn`: a recorded
  kernel as std/gpu's fake device runs a reference, lowered once and
  interpreted at the given grid on every call.
- `interp.interp_kernel(kernel, grid, dtypes, ins, scalars, ub_checks)`: the
  same on a lowered kernel, answering `Err(InterpError)` where
  `interp_ref` panics. Kinds: `interp.unsupported_op` (refused before
  running), `interp.ub`, `interp.bad_launch`, `interp.internal`.
- `interp.unsupported_in(kernel)`: the static walk behind the first kind.
- `device.with_gpu_interp(progs, body)` and `with_gpu_interp_log`: a `Gpu`
  handler that interprets each launch at the launch's own grid and forwards
  the other operations to the handler outside it.
- Subset A: f64 and integer formats; matrix products, `fma`, narrow float
  formats, atomics, fences, strided and gather views, globals, `alloca`,
  `assert`, `print_tko` and pointer casts are refused by name.
- `scripts/tileinterp-diff` holds it against packages/tileref over every
  layer-2 corpus: 106 golden kernels covered.
