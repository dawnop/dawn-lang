# packages/tileref

Host reference implementations of the Tile IR kernels: for each kernel, a pure function that answers what the device's output buffer should hold.

```dawn
use std/gpu.{with_gpu_fake, last_out}
use tileref/ref.{relu_ref}
```

Each function takes the formats (`dtypes`) and contents (`ins`) of every
argument buffer, the output buffer last, and answers what the output buffer
holds after the kernel has run. A kernel that masks the lanes past `n` leaves
them as they were, so each reference takes that `n` and copies the output's
own tail past it. Fixing `n` and any constants gives the function the fake
device wants (`examples/projects/gpu_fake`).

The package depends on std alone, never on `tileir`: a reference is the second
opinion on a kernel and must not share its code path. The format arithmetic
(`round_to`, `wrap_*`, `nibble_*`) is `std/gpu`'s, so a reference and the fake
device agree on what a format can hold.

Changes between versions: [CHANGELOG.md](CHANGELOG.md).
