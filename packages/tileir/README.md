# packages/tileir

A pure Dawn generator of CUDA Tile IR that records a kernel body written against the `Dev` effect and emits it as `cuda_tile` text or as bytecode `tileiras` can assemble.

A kernel body is an ordinary Dawn function whose only effect is `Dev`.
Recording it once yields a `TileProg`, which `render` prints as `cuda_tile`
text and `encode` writes as bytecode. Buffers and launches are `std/gpu`'s,
and a format is a value type with a witness of the same name: `Float` and
`F64`, `Int` and `I64`, `Bool` and `I1` (`std/dtype`), `BF16`, `F16` and `F32`
(`std/narrow`), `I32` (`std/int/i32`).

## A kernel, end to end

One kernel, from `trace3` to an assertion on the answer, with nothing but the
fake device under it. The device side is `vadd`; `record` runs it once and
answers the program and the entry a launch takes; `run` is the host side, whose
only effect is `Gpu`, so the same function runs on any device:

```dawn
use std/dtype.{F64}
use std/gpu.{Gpu, alloc, copy_from_host, copy_to_host, free, sync, buffer_arg, launch_entry3, Entry3,
  with_gpu_fake, reference_kernels }
use std/list
use tileir/dev.{Dev, Param, load_cell, store_cell, add}
use tileir/prog.{TileProg, trace3, cells, In, Out}

fn vadd(a: Param[Float], b: Param[Float], out: Param[Float]) -> Unit !Dev =
  store_cell(out, add(load_cell(a), load_cell(b)))

fn record() -> (TileProg, Entry3[Float, Float, Float]) = {
  let g = cells([256], [128])
  trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
}

fn run(e: Entry3[Float, Float, Float], xs: List[Float], ys: List[Float]) -> Result[List[Float], ForeignError] !Gpu = {
  let n = len(xs)
  let a = alloc(F64, n)?
  let b = alloc(F64, n)?
  let out = alloc(F64, n)?
  copy_from_host(a, xs)?
  copy_from_host(b, ys)?
  launch_entry3(e, buffer_arg(a), buffer_arg(b), buffer_arg(out))?
  sync()?
  let got = copy_to_host(out)?
  free(a)?
  free(b)?
  free(out)?
  Ok(got)
}

fn xs() -> List[Float] = list.map(range(0, 256), i => to_float(i))

fn ys() -> List[Float] = list.map(range(0, 256), i => to_float(2 * i))

fn expected() -> List[Float] = list.map(range(0, 256), i => to_float(3 * i))

test "the kernel launched through its entry on the fake device adds the vectors" {
  let (_p, e) = record()
  assert with_gpu_fake(reference_kernels(), () => run(e, xs(), ys())) == Ok(expected())
}
```

`g` says every parameter is 256 elements cut into 128-wide cells, so the grid is
the two cells of the output and nothing states it; `entry` is what
`launch_entry3` takes in place of a kernel name and a block count, and the
formats of the arguments are in its type. An extent of `DYN_DIM` leaves the
length to the launch, which then names the grid (`launch_entry3(.., grid: [n / 128])`).
`launch_entryN` refuses, before any device is asked, an `Out` or `Shared`
argument that aliases another argument, a grid that disagrees with the cells
and a tensor shorter than its cells reach.

The fake device never runs a kernel body. It looks the launch's name up in a map
and calls the host reference registered there (`reference_kernels()` has `vadd`),
so this test checks the host half (the entry, the cells, the grid, the buffers)
and the reference against numbers written by hand, not the device code. That is
the job of the real device, next. The whole program, with the command line that
drives it, is
[`examples/projects/gpu_fake/src/first.dawn`](../../examples/projects/gpu_fake/src/first.dawn),
and this code is that file's: CI compiles it and runs its tests.

### On a GPU

Build the actual example from the repository root (JDK 21 and a C compiler
are needed to build the native driver). Choose the target explicitly for your
card: `sm_86`, `sm_90` or `sm_100`; pass the assembler executable explicitly too.
The commands below use `sm_86` as an example. If `tileiras` is already
installed, set `TILEIRAS` to that executable instead of the installer command:

```bash
source site/dawnc.sh
DAWNC=$(site_dawnc)
"$DAWNC" build examples/projects/gpu_fake -o gpu_fake
./gpu_fake fake
TILEIRAS=$(scripts/tile-golden/install-tileiras.sh "$HOME/.cache/dawn-tileiras")
./gpu_fake assemble sm_86 "$TILEIRAS"
```

`assemble` records the same `vadd`, calls `asm.assemble`, installs the cubin
with `with_gpu_real` and calls the same typed host `run` shown above. It prints
the bytecode and cubin SHA-256 hashes and byte lengths, the upload/download
lengths, then `real device: ok, 256 lanes agree with 3 * i` only after every
lane agrees with the independent answer. It exits 0 only on success. An
assembly failure exits 1 and prints `AssembleError`, its constructor and
explanation. A device refusal exits 1 with its English kind and message; a
wrong answer exits 1 with the first wrong lane and its expected/actual values.
A read/write or usage error exits 2. No target detection or cache is involved.

The existing separate steps remain available with that same binary:

```bash
./gpu_fake emit vadd.tilebc
"$TILEIRAS" --gpu-name sm_86 -o vadd.cubin vadd.tilebc
./gpu_fake real vadd.cubin
```

These plain assembler flags are sufficient for this straight-line `vadd`.
For other kernels, use `tileir/asm.tileiras_args` as explained below.
On the JVM (`./bin/dawn run examples/projects/gpu_fake -- fake`), fake needs
neither GPU nor assembler. The real paths require the native build:
`with_gpu_real` reports `gpu.unsupported_backend` on the JVM and
`gpu.no_driver` without an NVIDIA driver; neither refusal counts as success.
CPU CI compiles the complete path and runs fake and controlled assembler
failures, without attempting a device launch.

### The Tile IR itself

`render` prints the program as `cuda_tile` text and `encode` writes the bytecode
the assembler reads:

```dawn
use tileir/render.{render}
use tileir/bytecode.{encode}

let (prog, entry) = record()
let text = render(prog)     # cuda_tile text
let bytes = encode(prog)    # bytecode for tileiras
```

| Module | Contents |
|------|------|
| `dev` | the `Dev` effect, the opaque handle types (`Tile[D]`, `Param[D]`, `Idx`, views, ...) and the typed functions a kernel calls |
| `prog` | `TileProg`; `trace1` to `trace6` and `trace_kernel`, the recording handlers; the parameter markers |
| `lower` | `lower(prog)`, the linear instruction table |
| `render` | `render(prog)`, the `cuda_tile` text; `line_map` |
| `bytecode` | `encode(prog)`; `bytecode_version()` is `"13.4"` |
| `asm` | `assemble`, `tileiras_args(version, gpu_name, prog)`, `assembler_defect(version, gpu_name, prog)`, `has_break_loop(prog)`: how to call `tileiras` (see below) |

The full public surface is what `./bin/dawn doc packages/tileir` prints.
[OPERATIONS.md](OPERATIONS.md) says which `cuda_tile` operation each function
records, and [ERRORS.md](ERRORS.md) which of four layers an error comes from,
what it looks like and how to fix it. Both are checked against the source.

## Parameters and cells

`trace1` to `trace6` take one marker per parameter and answer an entry
`std/gpu` can launch with typed arguments (`launch_entryN`):

- `In(d, cells)` is read only; a write into it is refused while recording.
  `In(d, Whole)` is an input read anywhere (a gather's table, a pointer read).
- `Out(d, cells)` is written one cell per block, and the `Out` cells are the
  launch grid: dimension `j` of an `Out` follows grid axis `along[j]`, each
  axis at most once (the identity unless `along` says otherwise), and an
  axis no dimension follows has one block. A batched product keeps its
  batch on axis 2 with `cells([B, M, N], [1, T, T], along = [Axis(2), Axis(0), Axis(1)])`.
- `Shared(d)` is the escape hatch: atomics, scatters, a block that writes two
  regions, a write through pointers. `grep Shared(` finds every one.
- `Scalar(d)` is a value the launch passes by value (`i32`, `i64`, `f32` or
  `f64`), not a buffer: no cells, read in the body with `scalar(p)`, and
  passed with `std/gpu`'s `scalar_arg(v)`.
- `cells(extent, tile, pad: PadZero, along: ..)` cuts the tensor. An extent
  of `DYN_DIM` is the grid's to decide; `pad` is what a read past the extent
  answers; `along[j]` is the grid axis dimension `j` follows, or `Free`
  when the kernel picks that cell itself.

`trace_kernel(name, params, body)` records a body over `param(d, pos)`
handles, every one `Shared`; it is there for kernels with more than six
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
use std/gpu.{Axis, Free}
use tileir/prog.{trace3, cells, In, Out}

fn matmul(a: Param[Float], b: Param[Float], c: Param[Float]) -> Unit !Dev = {
  var acc = zeros(c)
  for k in d_range(0, 256 / 32) { acc = mma(load_at(a, [k]), load_at(b, [k]), acc) }
  store_cell(c, acc)
}

let (prog, entry) = trace3("matmul",
  In(F64, cells([256, 256], [64, 32], along = [Axis(0), Free])),
  In(F64, cells([256, 256], [32, 64], along = [Free, Axis(1)])),
  Out(F64, cells([256, 256], [64, 64])), matmul)
```

- `load_cell(p)` reads this block's cell; `load_at(p, [k])` names the cell
  along each `Free` dimension. Lanes past the extent read the marker's
  `pad`, so a tail needs no mask.
- `store_cell(o, t)` writes this block's cell of an `Out`;
  `store_sub(o, [i, j], t)` writes one piece of it, shaped like `t`. These
  are the only writes an `Out` takes: a `store`, `scatter`, atomic or
  `store_view` into one is refused while recording.
- `cells(..., squeeze = [axis, ...])` 按原 storage 维度编号，从值中删除 tile
  长度为 1 的轴，extent 可以大于 1。轴顺序无关；重复、负数、越界与非单例轴
  在 body 前拒绝。全轴投影得到 rank-0。storage 几何、launch grid、reach、
  alias 与 Out 所有权保持完整。load 在 view load 后 reshape，store 精确验证
  值形状，必要时广播 scalar，再恢复单例 storage 轴。`store_sub` 的 piece
  使用值维度，在投影轴插零；`extent_of`、`blocks_of` 与 `load_at` 的 free
  下标始终使用 storage 维度。
- `tile_shape(t)` 返回 `Tile[D]` 的记录期静态值形状，类型为 host `List[Int]`。
  不发设备操作、不分配 handle；rank-0 与同格式值也保留来源调用。
- `zeros(p)` and `fill(p, v)` are a tile shaped like a cell of `p`, the
  accumulator a block starts from. `full(shape, v)` is a float tile of any
  shape whose format is the one it is checked against:
  `let m: Tile[F32] = full([BQ, 1], 0.0)`. The value is a `D`, so a literal
  is already rounded to the format and a `Float` computed on the host is
  written `f32(x)`.
- A constant is rank 0: `f_const(F64, 0.5)`, `i_const(3)`; `f_const(BF16, 0.1)`
  records the bfloat16 nearest to 0.1. `lit(0.5)` is
  a float constant with no format, which takes the format of the
  element-wise operation it meets (`mul(s, lit(0.5))`; write it after a
  typed operand, since the checker finds the format left to right); a
  place that needs a format of its own refuses it and asks for `f_const`. A
  bare float literal where a tile is expected, like the `0.0` of `mma`
  below, is a `lit`.
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
  f64 into f64. A literal `0.0` accumulator takes the accumulator's format, so
  it needs one from the context: `let s: Tile[F32] = mma(a, b, 0.0)`.
  `mma_scaled` is the block-scaled product and `mmai` the i8 one.
- `t.to(BF16)` converts a float tile, rounding to nearest even (a tile
  already in that format is answered unchanged); `float_to_float` takes the
  other roundings. From f64 to F8E5M2, F8E4M3FN or F4E2M1FN, the default
  rounds the source binary64 value once to the target grid, then saturates.
  Signed zero is preserved; E5M2/E4M3 retain the NaN class and E2M1 maps
  NaN to +0. Explicit f64 -> f32 -> target still means two roundings.
  `t.transpose()` swaps a rank-2 tile's dimensions;
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
  `add(a, b, rounding = Down)`, `d_global("t", F64, xs, visibility: Private)`.
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
FlashAttention with bf16 inputs and f32 accumulation and output (`scale` is a
`Scalar(F32)` parameter, read with `scalar(scale)`):

```dawn
use std/float.{INFINITY}
use std/narrow.{f32}

var m: Tile[F32] = full([BQ, 1], f32(-INFINITY))
var l: Tile[F32] = full([BQ, 1], 0.0)
var acc: Tile[F32] = full([BQ, D], 0.0)
for j in d_range(idx_const(0), blocks_of(k, 1)) {
  let s: Tile[F32] = mma(tq, load_at(k, [j]).transpose(), 0.0) * scalar(scale)
  let m_new = max(m, reduce_max(s, keepdims = true))
  let p = exp2(s - m_new, ftz = true)
  let alpha = exp2(m - m_new, ftz = true)
  l = l * alpha + reduce_sum(p, keepdims = true)
  acc = mma(p.to(BF16), load_at(v, [j]), acc * alpha)
  m = m_new
}
store_cell(o, div(acc, l, approx = true, ftz = true))   # o, scale: Param[F32]
```

The launch passes `f32(log2(e) / sqrt(D))` as the scale, changing base once.
The [Playground sample](../../site/play-ui/samples/flash_attn.dawn) records the shared
generic body with this BF16/F32 numerical policy and a 32×16 demonstration layout.

`carry`, `get` and `set` remain for the loops a `for` cannot write: `d_loop`'s
body is a closure with a data-dependent exit.

- `for j in d_range(lower, upper, step = By(n), unsigned_cmp = false) { .. }` is
  a loop. The bounds are host numbers (`Int`, fixed when the kernel is
  recorded) or `Idx` values the device computes; the step is `One` by default,
  or `By(n)` of the same kind as the bounds, so a grid-stride loop writes
  `step: By(nprog)`. The induction variable is always an `Idx`.
  (`extent_of(p, dim)` and `blocks_of(p, dim)` are a parameter's extent and
  its number of cells along a dimension.)
- `d_loop { .. }` (its `at` default comes first, so the block is the last
  argument) runs until its body answers a true rank-0 mask. On the
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
replaces; with `occupancy: Some(2)` it fits two (49184 bytes) and is faster.
Give such a kernel
`hints: [for_arch("sm_86", entry_hints(occupancy: Some(2)))]`. The
measurement is in §6.26 of the design document.

## Hints

A hint is advice the assembler may take or leave: it never changes what a
kernel computes, only the code it makes. `hints:` takes one entry per
architecture (`for_arch("sm_86", ..)`, or `"default"`), and the record under
it depends on what carries the hint:

| Carried by | Record | Keys |
|---|---|---|
| the entry (`trace_kernel`, `trace1` to `trace6`) | `entry_hints(..)` | `num_cta_in_cga`, `num_worker_warps_per_cta`, `occupancy` |
| `load`, `store` | `ptr_hints(..)` | `latency` |
| `load_cell`, `load_at`, `store_cell`, `store_sub`, `load_view`, `store_view`, `load_gather`, `store_gather` | `view_hints(..)` | `allow_tma`, `latency` |

`tileiras` checks none of the values (its own check is off by default), so a
value outside the dialect's range is refused when the kernel is recorded:
`latency` 1 to 10, `occupancy` 1 to 32, `num_worker_warps_per_cta` 4 or 8,
`num_cta_in_cga` a power of two to 16 and 1 on sm_80 to sm_89. An
architecture must be `default` or `sm_` and a number, and appear once.

## What the recorder refuses

Each value handle has a format and a shape, and every element-wise operand is
held to the shape the operation takes from its operands (after the rank-0
and same-rank rules), as is the `k` of `mma`, `mma_scaled` and `mmai` and the format pair of
`mma`. A mismatch panics
while the kernel records, naming the operation by its depth-first number in
`TileProg.ops` (`MakeToken(0)` is #0) and, for the four float operators, as
the kernel wrote it. The message ends in the line of your own source that the
call was written on (since 0.21.0: every public function of `tileir/dev` takes
`at: Loc = caller()`, and the recording keeps the one of the call you wrote, not
the ones the library makes for itself), for example:
``tileir: kernel `vadd_half`: op #6 `+`: rhs is tile<128xf64>, declared tile<64xf64> (rhs comes from `load_cell` at src/main.dawn:14:22) at src/main.dawn:15:19``.
After the reason come, in this order, where the wrong operand was made (the
call you wrote, or `the `+` operator` for one an operator made), and, when the
operation is inside a region, the regions, outermost first, each with the line
of the call that opened it:
``... declared tile<4xf64> (inside the body of a `d_range` at src/main.dawn:26:12, inside the then branch of a `d_if` at src/main.dawn:27:7) at src/main.dawn:26:12``.
An operator (`+ - * /`, a `var`, a bare float literal) is a trait method, which
takes no `caller()` default, so it has no line of its own: the message ends in
the nearest line it does have (the enclosing region's, else the line that
recorded the kernel) and the operand note says where the operands came from.
[ERRORS.md](ERRORS.md) sorts these messages, the compiler's and the device's
into four layers, with the fix for each.

## Assembling with tileiras

`asm.assemble(prog, gpu_name, tileiras)` is the whole step between a recorded
program and a cubin. It encodes `prog`, writes a temporary `.tilebc`, asks
`tileiras --version` which assembler it was given, runs it with the arguments
for that version and target, reads the cubin back and removes the scratch
directory. `tileiras` is the path of the executable (a bare name is looked up
on `PATH`); this package does not install it. The runnable path above is implemented in
`examples/projects/gpu_fake/src/first.dawn`. These are its complete assembly
and driver functions, using `record`, `run`, `xs` and `ys` defined above;
`finish` checks `expected()` lane by lane and exits 1 on a failure:

```dawn
use std/io
use std/io.{Exit}
use std/map
use sha2/sha256
use tileir/asm.{assemble, AssembleError, explain}
use tileir/bytecode.{encode}
use std/gpu.{with_gpu_real}

fn answer_error(r: Result[List[Float], ForeignError]) -> Option[String] = match r {
  Err(e) -> Some("${e.kind}: ${e.message}")
  Ok(zs) -> {
    let want = expected()
    if len(zs) != len(want) { Some("answer length: expected ${len(want)}, got ${len(zs)}") } else {
      var wrong: Option[String] = None
      for i in range(0, len(want)) {
        if wrong == None && zs[i] != want[i] {
          wrong = Some("answer lane ${i}: expected ${want[i]}, got ${zs[i]}")
        }
      }
      wrong
    }
  }
}

fn finish(device: String, r: Result[List[Float], ForeignError]) -> Unit !io !Exit = match answer_error(r) {
  None -> io.println("${device} device: ok, 256 lanes agree with 3 * i")
  Some(error) -> {
    io.eprintln("gpu_fake: ${error}")
    io.exit(1)
  }
}

fn on_real(cubin: Bytes, e: Entry3[Float, Float, Float]) -> Result[List[Float], ForeignError] !io =
  with_gpu_real(map.from([("vadd", cubin)]), () => run(e, xs(), ys()))

fn assembly_error(e: AssembleError) -> String = "AssembleError: ${e}: ${explain(e)}"

fn assemble_run(prog: TileProg, e: Entry3[Float, Float, Float], gpu_name: String, tileiras: String) -> Unit !io !Exit =
  match io.with_fs_real(() => io.with_proc_real(() => assemble(prog, gpu_name, tileiras))) {
    Err(err) -> {
      io.eprintln(assembly_error(err))
      io.exit(1)
    }
    Ok(cubin) -> {
      let source = encode(prog)
      io.println("bytecode: ${len(source)} bytes, sha256 ${sha256.hex(source)}")
      io.println("cubin: ${len(cubin)} bytes, sha256 ${sha256.hex(cubin)}")
      io.println("transfer: upload 256 + 256 f64 lanes (4096 bytes), download 256 f64 lanes (2048 bytes)")
      finish("real", on_real(cubin, e))
    }
  }
```

It returns `Result[Bytes, AssembleError]` and takes the `Fs` and `Proc`
effects, so a test answers both without an assembler. The failures are told
apart: `AssemblerNotFound` (nothing could start `tileiras`), `AssemblerFailed`
(a non-zero exit, with the arguments and what it printed on stderr),
`NoCubin` (a zero exit and no output), `UnknownVersion` (a `--version` without
one complete, unambiguous standard version record) and `Scratch` (the host
refused a temporary file). Nothing is cached; an assembly takes well under a second.

The version record is `Cuda compilation tools, release M.m, VM.m.p`, with
ASCII decimal components and no leading zeros except `0`. The release must
agree with the full version. Surrounding whitespace, LF and CRLF are accepted;
incomplete versions, suffixes and duplicate records are rejected before the
assembly subprocess starts. `UnknownVersion` retains the original stdout.
Other complete versions keep the existing argument policy. A new vendor
format needs an explicit contract and fixture before it is accepted.

Where to get `tileiras`: it is in the CUDA Toolkit 13.4 and later
(`<toolkit>/bin/tileiras`), and on PyPI as `nvidia-cuda-tileiras`, which needs
`nvidia-nvvm` and `nvidia-cuda-nvcc` of the same version beside it.
`scripts/tile-golden/install-tileiras.sh <dir>` installs the version this
repository pins from those wheels and prints the binary's path. It needs no
GPU and no driver.

### Why the arguments are not always the plain ones (#558)

**With tileiras 13.4.92, a program that has a `loop` which `break`s needs
`--opt-level 0` when it is assembled for sm_90, sm_100, sm_103, sm_107 or
sm_110.** At the default level that assembler stores a wrong loop exit value
for a loop that leaves through `break` with two carried values
([#558](https://github.com/dawnop/dawn-lang/issues/558),
[NVIDIA/cuda-tile#25](https://github.com/NVIDIA/cuda-tile/issues/25)). Any
other program, other targets and other tileiras versions keep the default
level, which is what makes a `for`-loop kernel such as flash attention fast.
`assemble` applies this itself; a build script that runs `tileiras` on its own
asks `asm` rather than hard-coding it, so the workaround lifts when you move
to a fixed tileiras:

```dawn
use tileir/asm.{tileiras_args, assembler_defect, has_break_loop}

let args = tileiras_args("13.4.92", "sm_90", prog)   # a loop that breaks: ["--gpu-name", "sm_90", "--opt-level", "0"]
                                                     # any other program: ["--gpu-name", "sm_90"]
let why = assembler_defect("13.4.92", "sm_90", prog) # Some("tileiras 13.4.92 miscompiles ...") or None
# then: tileiras <args> -o kernel.cubin kernel.tilebc
```

`has_break_loop` looks for a `loop` with a `break` at any depth, which is
wider than the four conditions the issue minimised, on purpose. `-O0` costs
device time: measured on sm_86, up to 4.5x for kernels that compute and 8x
for a small loop (§6.28); on sm_90 and sm_100 a flash-attention kernel took 35x
to 57x of its `-O3` time (bf16), which is why only the programs at risk pay.

## Writing your own `Dev` handler

A handler has to answer every operation of `Dev`, so a new operation is a
version bump (see the changelog). What a handler owes the ones that issue
nothing:

- `t_call_enter(name, at)` / `t_call_exit()` and `t_body_enter()` /
  `t_body_exit()`: answer `()` and record nothing. The call pair wraps the
  body of each public function (`at` is the `Loc` of the call, `None` for an
  operator, which has none); the body pair wraps each closure a public
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


## Read layouts (0.28.0)

`cells(..., along = ...)` now takes the single nominal `std/gpu.CellAxis`
type. Import `Axis`, `Free` and `Grouped` from `std/gpu`. Integer axis lists
and the old integer sentinel have been removed. Axis(k) preserves one-to-one
cell/grid mapping; Free takes an explicit index. Grouped(k,g) reads
floor(block_id(k)/g), only for In with static capacity. Require a positive
i32 group, complete grid groups, and cell count == grid[k]/g. Duplicate source
axes, Grouped with DYN_DIM, and Grouped in Out (including g=1) are refused.

`read_prefix(p, dim, length)` creates a separate `ReadView[D]` of an In Grid.
Only one Free storage dimension's zero-based prefix is narrowed. All capacity
extents, physical strides, tile, padding, axes and squeeze stay the marker's.
`read_at(view, free)` reads legal cells; `read_blocks(view, dim)` queries its
effective index space. `blocks_of(p, dim)` and `extent_of(p, dim)` still query
capacity. ReadView has no writes and cannot be passed to `store_view`.

The length operand must be a rank-0 i32. Before conversion and launch, the
caller must validate 1 <= length <= capacity, positive dimensions, complete
HQ/HKV groups, and I32 offset products. Entry6 validates roles and capacity;
it does not know which scalar is a prefix length. PadZero protects tail K/V
loads; an attention algorithm must explicitly mask invalid scores before
max, exp and sum. This release adds small semantic probes, not production
fused GQA or a wider domain for the ordinary BF16 flash example.
