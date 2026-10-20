# tileinterp changelog

Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3).

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
