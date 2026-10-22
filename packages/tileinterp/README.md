# packages/tileinterp

A host interpreter for the Tile IR kernels `packages/tileir` records: the kernel body itself runs on a machine with no GPU, behind std/gpu's fake device.

std/gpu's fake device answers a launch with a host reference you register
for it; it never runs the kernel. This package runs it. `interp_ref(prog,
grid)` lowers the recorded `TileProg` with tileir's `lower` and answers a
`WideRefFn`, the function the fake device's table holds, so `std/gpu` and
the host program need no change. The interpreter executes the lowered
instruction table, the same table the text renderer and the bytecode writer
spell, block by block in order, x fastest.

```dawn
use std/dtype.{F64}
use std/gpu.{Gpu, with_gpu_fake, alloc, copy_from_host, copy_to_host, launch, buffer_arg, erase}
use std/list
use std/map
use tileir/dev.{Dev, Param, load_cell, store_cell, add, DYN_DIM}
use tileir/prog.{trace3, cells, In, Out}
use tileinterp/interp.{interp_ref}

fn vadd(a: Param[Float], b: Param[Float], out: Param[Float]) -> Unit !Dev =
  store_cell(out, add(load_cell(a), load_cell(b)))

fn run(xs: List[Float], ys: List[Float]) -> Result[List[Float], ForeignError] !Gpu = {
  let a = alloc(F64, len(xs))?
  let b = alloc(F64, len(xs))?
  let out = alloc(F64, len(xs))?
  copy_from_host(a, xs)?
  copy_from_host(b, ys)?
  launch("vadd", len(xs) / 128, [erase(buffer_arg(a)), erase(buffer_arg(b)), erase(buffer_arg(out))])?
  copy_to_host(out)
}

let g = cells([DYN_DIM], [128])
let (prog, _entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
let xs = list.map(range(0, 256), i => to_float(i))
# two blocks of 128: the grid is fixed when the function is made, because
# the fake device does not read the launch's grid
let got = with_gpu_fake(map.from([("vadd", (3, interp_ref(prog, [2])))]), () => run(xs, xs))
# got == Ok([0.0, 2.0, 4.0, ...])
```

When the grid follows the data, `device.with_gpu_interp(progs, body)` reads
it off every launch instead: install it inside `with_gpu_fake` (which keeps
the buffers) and give it a lookup from kernel name to `TileProg`.

## What it interprets

The integer formats (`i1`, `i4`, `i8`, `i16`, `i32`, `i64`) and every float
format `std/narrow` models: f64, f32, tf32, bf16, f16, f8E5M2, f8E4M3FN,
f4E2M1FN and f8E8M0FNU. Element-wise arithmetic and comparisons, `select`,
the shape operations (`reshape`, `broadcast`, `extract`, `insert`, `cat`,
`permute`, `iota`), reductions and scans (left fold), `for`, `loop` and `if`
with `break`, `continue` and `return`, tensor and partition views with their
five padding values, pointer loads and stores with mask and padding, `assume`,
the conversions between those formats (`ftof` with its five roundings,
`itof`, `ftoi`, `bitcast`, `pack` / `unpack`), `fpowi`, the transcendental
functions, `fma` and the matrix products `mmaf`, `mmaf_scaled` and `mmai`.

A float lane of a narrow format is a Float that is a value of the format, and
every operation ends by rounding into the format with `std/narrow`'s own
functions, so the interpreter and `std/narrow` cannot disagree about a
format. Add, subtract, multiply, divide, square root, the directed roundings
and `fma` are exact (one rounding of the exact result); the transcendental
functions are written here (not taken from packages/tileref, which is what CI
holds this package against) and are good to about 1e-13 relative, the
tolerance tier's side of docs/tile-backend-design.md 6.6.

A matrix product promises a product and nothing about how the sum over `k` is
grouped, so the interpreter's accumulation is a model: a binary64 accumulator
takes one fused step per `k`, ascending; a narrower one sums the exact
products in binary64 and rounds once at the end. Comparisons against it are
tolerance-tier ones (docs/tileinterp-design.md 7.1).

Everything else is refused before anything runs, with
`interp.unsupported_op` and the instruction's name: atomics, fences and PDL,
strided and gather views, module globals, `alloca`, `assert`, `print_tko`, the
pointer casts and the one format `std/narrow` does not model (f8E5M3FNU) are
not planned, because a sequential run gives one legal answer where a device
has several and could not check the rest.

## Undefined behaviour

The checks are on by default (`ub_checks: true`), and a launch that reaches
undefined behaviour fails with `interp.ub` rather than answering: an access
outside its buffer, a broken `inbounds` promise, an `extract` or `insert` out
of range, an integer division by zero, a broken
overflow assumption, a non-saturating `ftoi` of NaN or of a value out of
range, a false `assume`, and the use (a store, a branch, a bound, an index)
of a lane a masked load or an out-of-bounds view read left unspecified.
`ub_checks: false` runs on with NaN or 0 in such lanes.

A refused launch panics with `<kind>: <message>` under `interp_ref`, whose
`WideRefFn` type has no error channel; `interp_kernel` answers the same as
`Err(InterpError)`, and `with_gpu_interp` as the launch's `Err`.

## How it is held

`scripts/tileinterp-diff` runs every layer-2 program of
`scripts/tile-gpu-diff` with this interpreter in the device's chair, against
the same packages/tileref references and tiers, in CI. The kernels it covers
are listed in `scripts/tileinterp-diff/covered.txt`. The GPU stays the
authority: the device ledgers are recorded on the machines that have one.
Design and measurements: [`docs/tileinterp-design.md`](../../docs/tileinterp-design.md)
(in Chinese).

Changes between versions: [CHANGELOG.md](CHANGELOG.md).

Integer shifts normalize every count with `count & (width - 1)`, including negative counts. Left shifts wrap at the lane width, arithmetic right shifts copy the sign bit, and logical right shifts fill with zero. These rules also apply to raw interpreted integer shift instructions; surface tile operators additionally record an explicit device mask.
