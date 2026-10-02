# packages/tileref

Host reference implementations of the Tile IR kernels: for each kernel, a pure function that answers what the device's output buffer should hold.

Every kernel `scripts/tile-golden` records has a function here. Its input is
the format and contents of each argument buffer, and its output is what the
output buffer should contain after the device has run. Layer 2's comparison
programs in `scripts/tile-gpu-diff` check the real device against them, and
the "second opinion" column of `scripts/leetgpu-diff/problems.txt` points here
for every problem.

## Why a package and not std

Until 0.82.0 these functions were in `std/gpu`. The rule is the one in
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5.3 (in
Chinese): what needs no intrinsic does not go into std. Every reference is a
pure function over `List[Float]` and uses no intrinsic. In std they cost every
compilation a check of some 3000 lines no program reaches, and they put a
solution corpus under std's API discipline (`std/moved.txt`, `Param-Change`,
naming sweeps). The decision and its measurements are in the design's §5.3,
under the subsection on moving the references out of `std/gpu`.

`std/gpu` keeps only the device model: the `Gpu` effect, the formats, the two
handlers, and the two entries of `reference_kernels`, `vadd_ref` and
`sum_ref` (`dawn test --stdlib` needs a usable fake-device table).

## Not dependent on `tileir`

A reference is the second opinion on a kernel, so it must not go through the
kernel's code path. The manifest has no `[deps]`, so the package depends on
std alone, and `scripts/leetgpu-diff/check.py` reads the manifest and fails if
`tileir` ever appears in it.

## Usage

The path is relative to the consumer's `dawn.toml`
(`examples/projects/gpu_fake` writes `"../../../packages/tileref"`):

```toml
[deps]
tileref = "../../packages/tileref"
```

```dawn
use std/gpu.{with_gpu_fake, last_out}
use tileref/ref.{relu_ref}
```

The format arithmetic (`round_to`, `wrap_*`, `nibble_*`) is `std/gpu`'s, so the
fake device and the references can never give two answers to what a format
can hold.
