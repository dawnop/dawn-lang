# Where an error comes from

A kernel meets four checkers on its way to a GPU, and each speaks differently.
Knowing which one spoke is most of the fix.

| Layer | When it runs | What it looks like | The usual fix |
|---|---|---|---|
| **type check** | `dawn check`, `dawn run`, the editor; before anything executes | a compiler error with a source position | change the type: the format, the effect or the argument is wrong |
| **record** | while `trace1` to `trace6` or `trace_kernel` runs your kernel body once | a panic `tileir: kernel `name`: op #N `op`: ... at src/main.dawn:L:C`, the line of your own call | the kernel asks for something the shapes or roles cannot give; change the call it names |
| **emit** | `render`, `encode`, `lower`, then `tileiras` | a panic `tileir: ...` with no kernel name, or `tileiras` refusing the bytes | usually a view or a region whose parts disagree; occasionally a defect in the assembler |
| **device** | the host program, on the fake device or a real one | an `Err(ForeignError)` whose `kind` is `gpu.*` or `cuda.*` | the host call, the launch geometry or the machine; the kind says which |

The order is also the order of cost. A mistake the type checker can see never
reaches the recorder, and one the recorder can see never reaches `tileiras`,
whose verifier answers in terms of the bytecode and not of your Dawn.

## Type check

The format of a buffer is in its type, so a kernel, its entry and the host
buffers it is launched over are held to one another by the compiler. Real
messages, from a file that gets each wrong:

```
error: `no_effect` uses the effect `Dev`, but its signature does not declare !Dev
error: argument type mismatch: expected fn(Param[F32], Param[Float], Param[Float]) -> Unit !Dev, got fn(Param[Float], Param[Float], Param[Float]) -> Unit !Dev
error: argument type mismatch: expected DeviceBuffer[Float], got DeviceBuffer[F32]
```

The second is `trace3("vadd", In(F32, g), In(F64, g), Out(F64, g), vadd)` with
a `vadd` written over `Param[Float]`: the marker says f32 and the kernel says
f64. The third is a `DeviceBuffer[F32]` handed to a `launch_entry3` whose entry
was recorded over f64 parameters. Mixing two formats in one element-wise
operation (`add(load_cell(a), load_cell(b))` over a `Param[Float]` and a
`Param[F32]`) is the same error, at the call.

| Fragment of the message | Layer | Cause | Fix |
|---|---|---|---|
| `its signature does not declare` | type check | a function calls `load_cell`, `add` or any other `Dev` function without `!Dev` in its signature | add `!Dev`; a kernel body is a function whose only effect is `Dev` |
| `argument type mismatch` | type check | a format, a role or an arity differs between a marker, the kernel's `Param[..]` and a host `DeviceBuffer[..]` | make the three agree; the message prints both types |

## Record

`trace1` to `trace6` run the kernel body once under a handler that writes every
operation down, and that handler holds each operation to the shapes and
formats of its operands, to the role of each parameter and to the cells that
cut it. A refusal is a panic that names the kernel and, for an operation, its
number (`MakeToken` is `#0`, then in the order recorded) and its dialect name.
Real messages:

```
tileir: kernel `shapes_differ`: op #4 `+`: rhs is tile<64xf64>, declared tile<128xf64> (rhs comes from `load` at src/main.dawn:58:11) at src/main.dawn:59:15
tileir: kernel `write_in`: op #7 `store_cell`: parameter 0 is an In, and nothing writes an In at src/main.dawn:84:3
tileir: kernel `not_pow2`: every tile dimension is a power of two, got 100 in [100] at src/main.dawn:69:12
tileir: kernel `pointer_store`: op #3 `store`: parameter 1 is an Out, which is written through its cells alone (store_cell, store_sub); a parameter written any other way is a Shared at src/main.dawn:89:3
```

The trailing position is a line of your own kernel: the call you wrote that the
recorder was running when it refused (every public function of `tileir/dev`
takes `at: Loc = caller()` since 0.21.0, so the recorder knows where each call
was written). A refusal that needs an operand says where that operand was made
(`rhs comes from `load` at ..`) and one inside a region says which `for` or
`d_if` it is in, each with its line. An operator (`+ - * /`, a `var`, a float
literal) has no line of its own, because a trait method takes no `caller()`
default; its message ends in the nearest line it does have, the enclosing
region's, else the line that called `trace_kernel` or `trace1` to `trace6`. The
kernel name says which function, the operation name which call in
it; `op #N` counts operations, so a run of `load`s and `add`s is a few numbers
long and the one named is the one to look at. The recorder has no codes, only
messages, and they are free text, so the rows below are keyed by a fragment of
the message and not by a code.

| Fragment of the message | Layer | Cause | Fix |
|---|---|---|---|
| `, declared ` | record | an element-wise operation, a product or a store met an operand whose format or shape is not the one the operation (or the first operand) fixed | line the shapes up with `broadcast`, `reshape` or a `keepdims` reduction, or fix the load that made the odd one |
| `nothing writes an In` | record | a store into a parameter whose marker is `In` | make the marker `Out` (written one cell per block) or `Shared` (the escape hatch for atomics and scatters) |
| `which is written through its cells alone` | record | `store`, `scatter`, an atomic or `store_view` into an `Out` | write the cell with `store_cell` or `store_sub`, or mark the parameter `Shared` |
| `every tile dimension is a power of two` | record | a tile, a cell or a view with a dimension that is not 1, 2, 4, 8, ... | cut the tensor into power-of-two tiles and let the tail be padding or a mask |
| `squeeze axis` | record | 轴为负数、越过 storage rank、重复，或 tile 长度不是 1 | 每个单例 storage tile 轴至多使用一次；extent 不要求为 1 |
| `expects projected value shape` | record | 非 scalar store 的值形状错误，即使元素总数相同也拒绝 | 在 store_cell 前显式 reshape 为投影值形状 |
| `projected value dimensions and piece numbers` | record | store_sub 使用了 storage rank，没有使用投影值 rank | shape 与 piece 按值维度指定；单例 storage 轴自动恢复 |
| `loops nest deeper than` | record | a body that recurses through `d_range` or `d_loop` unrolls forever | make the recursion a loop; the bound is `MAX_LOOP_DEPTH` |
| `but the dialect takes` | record | an `optimization hint` value outside the dialect's range (`latency` 1 to 10, `occupancy` 1 to 32, `num_worker_warps_per_cta` 4 or 8, `num_cta_in_cga` a power of two to 16 and 1 on sm_80 to sm_89), or an architecture that is not `default` or `sm_` and a number, or one given twice; `tileiras` accepts every one of these in silence and ignores it | change the value to the one the message names; the check is here because the assembler's own is off by default |

## Emit

`render` and `encode` first lower the record (`lower`), then print it as
`cuda_tile` text or write it as bytecode. This layer checks what only the
whole record can show: that a view's parts agree with the tensor under it,
that a region ends in the right terminator, that a format has an encoding.
Its panics have no kernel name, because by now the program is a value and not
a running kernel. A real one, from a partition view whose `dim_map` names a
dimension the tensor does not have, which the recorder accepts:

```
tileir: dim_map sends a tile dimension to tensor view dimension 3, which is outside 0 to 0 at tileir/lower.dawn:549:16
```

| Fragment of the message | Layer | Cause | Fix |
|---|---|---|---|
| `dim_map sends a tile dimension to tensor view dimension` | emit | a `partition_view` or `strided_view` maps a tile dimension to a dimension the tensor view does not have | give the view the dimensions of the tensor, or fix the map |
| `expected tensor_view rank and tile rank to match` | emit | a `partition_view` whose tile has more or fewer dimensions than the tensor view under it | cut the tile with the tensor's rank |
| `load_view promises inbounds over a view with padding` | emit | `inbounds: [true]` on a view that has a padding value, which `tileiras` refuses without saying why | drop the promise, or cut the view with `NoPadding` |

Past the emitter is `tileiras`, which reads the bytecode and answers in the
dialect's terms. Its verifier refuses a program the recorder let through (a
format an architecture does not have, say) and it prints the dialect's own
sentence. Handed bytes that are not Tile IR at all, it says
`error: input does not correspond to Tile IR bytecode` and exits 3. A cubin
that assembles and computes the wrong thing is not an error at any layer; the
one such case this package knows is a defect of one assembler version on some
targets, which `asm.assembler_defect` names (see
"Assembling with tileiras" in [README.md](README.md)).

## Device

The host side is `std/gpu`: every operation answers `Result[_, ForeignError]`,
and the `kind` is one of the rows below. Most are raised **above the effect**,
before any handler is asked, so the fake and the real device refuse them in
the same words; the rest are a handler's. The inventory is the union of actual
error constructors in `std/gpu.dawn`, the marked GPU section of
`runtime/c/dawn_rt.c` and the JVM GPU generator in
`selfhost/src/jvm/rtclasses.dawn`. Shared kinds have one row with both origins.
Runtime checks run inside the real handler: they can follow driver
initialization and earlier device operations. A `cuda.*` kind is the CUDA driver's
own `CUresult` name, passed through unchanged (`cuda.CUDA_ERROR_NOT_FOUND`
for a global a module does not export).

A real one, from launching an entry whose Out cells make two blocks with a
grid of three:

```
gpu.grid_mismatch: gpu.launch_entry: kernel `vadd`: the Out cells make 2 block(s) along axis 0 and the launch asks for 3
```

| Kind | Layer | Raised by, and why | Fix |
|---|---|---|---|
| `gpu.bad_length` | device | above the effect: `alloc` of a buffer with fewer than one element; also the C runtime, after driver initialization, rejects a negative byte count at allocation or device-to-host copy | allocate at least one element; a raw runtime call must pass a nonnegative byte count |
| `gpu.length_mismatch` | device | above the effect: `copy_from_host` of a list whose length is not the buffer's; also a raw upload of the wrong number of bytes | upload exactly as many elements as the buffer holds |
| `gpu.unsupported_dtype` | device | a handler at `alloc`, or above the effect when a typed copy names a format that is not a buffer format: the device does not move that format (the message lists the ones it does) | use a listed format, or convert on the host |
| `gpu.bad_grid` | device | above the effect: a grid axis below one or above CUDA's limit, more than three axes, or a launch with a dynamic Out extent that did not name its grid; also the C runtime, after driver initialization and before function lookup, rejects any axis below 0 or above 2^31 - 1 | pass `grid:` with the block counts; check the host and raw runtime limits |
| `gpu.grid_mismatch` | device | above the effect: the grid passed, or an In's cells, disagree with the Out cells that fix the grid | drop `grid:` when the Out cells fix it, or make the cells agree |
| `gpu.bad_entry` | device | above the effect: an entry whose cells are malformed, or an argument of the wrong kind (a `scalar_arg` where the kernel reads a buffer) | record the kernel with `traceN` and pass what its markers say |
| `gpu.aliased_argument` | device | above the effect: an `Out` or `Shared` argument is the same buffer as another argument | allocate a buffer for the output |
| `gpu.short_tensor` | device | above the effect: a buffer holds fewer elements than its cells reach | allocate (or upload) the full extent |
| `gpu.no_such_buffer` | device | a handler: a handle that was never issued or was freed | do not use a buffer after `free` |
| `gpu.no_kernel` | device | a handler: no kernel of that name (the fake device has the map it was given, the real one the cubins) | register the kernel under the name you launch |
| `gpu.no_arguments` | device | a handler: a launch with no buffers | pass the kernel's arguments |
| `gpu.bad_arity` | device | the fake device: the reference registered for the kernel wants another number of buffers | launch with the buffers the reference takes |
| `gpu.bad_write_back` | device | the fake device: the reference writes back to an argument position the launch does not have | register the reference with a position the launch has |
| `gpu.fake_inexact` | device | the fake device: an i64 buffer holds a value a `Float` cannot carry exactly, and the reference sees Floats | keep the values within 2^53, or test on a real device |
| `gpu.no_module_symbol` | device | the fake device: the kernel's module exports no global of that name (a `private` global is not exported) | declare the global public, or look up another name |
| `gpu.bad_global_dtype` | device | a handler: the global was already looked up as another format | read one global in one format |
| `gpu.bad_global_size` | device | the real device: the global's byte size is not a whole number of elements of the format asked for | ask for the format it was declared with |
| `gpu.no_driver` | device | the C runtime during driver initialization: `libcuda.so.1` cannot be loaded or a required driver entry point is absent | install a compatible NVIDIA driver and make its library available, or use the fake device |
| `gpu.driver_too_old` | device | the C runtime at module load, after driver initialization and before `cuModuleLoadData`: a cubin with ELF ABI version 8 or newer needs driver API 13000 (CUDA 13, r580 or newer), but the loaded driver reports less; a failed version query is treated as 0 | update the loaded driver to support the toolchain's cubin ABI, or rebuild with a compatible toolchain; the message prints the ABI and required and actual API versions |
| `gpu.bad_kernel_name` | device | the C runtime at launch, after driver initialization and grid validation but before `cuModuleGetFunction`: the kernel name contains a NUL byte, which a C driver name cannot represent | remove the embedded NUL and use the kernel's exported entry name |
| `gpu.bad_symbol_name` | device | the C runtime at module-global lookup, after driver initialization but before `cuModuleGetGlobal_v2`: the symbol name contains a NUL byte | remove the embedded NUL and use the global's exported name |
| `gpu.unsupported_backend` | device | the JVM GPU runtime and the C runtime's WebAssembly branch: any real-device operation on a backend with no device runtime | build for a native target with the C backend (`dawnc build`) |
| `cuda.CUDA_ERROR_NOT_FOUND` | device | the driver, unchanged. One example of a family: `cuda.` followed by the `CUresult` name, for everything the driver refuses; this one is a global a module does not export | read the CUDA driver documentation for the name |


K3-G rejects invalid CellAxis values before recording the body when possible:
Grouped requires a positive i32 group, a valid axis, static In capacity and
complete groups. Typed launch checks unknown grid relationships after resolving
the actual grid and keeps full-capacity reach and alias checks. Out requires
Axis in every dimension. read_prefix requires In Grid, static capacities and
a Free storage dimension; its length must be a rank-0 i32. Dynamic length
bounds remain the caller's host precondition. A ReadView passed to store_view
is a compiler type error, independently of recorder In write protection.
