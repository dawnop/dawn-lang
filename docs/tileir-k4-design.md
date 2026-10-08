# tileir K4 设计：kernel 的运行期标量参数

> 状态：**proposed**（七个开放问题已于 2026-10-07 裁决，见 §7 与 ruling-k4-design-20261007；整篇仍待评审）。2026-10-07 写成，基线 `origin/main` = 731db7f3，`packages/tileir` 0.10.0。
> 依据：维护者工作区的 ruling-generic-kernel-20261006（K4 在刀序第 3 条，独立可并行，碰 `std/gpu` 与 Core golden）与
> ruling-drange-step-20261006（`Step[B] { Unit, By(B) }`，设备步长是 K4 之后的主线写法）。
> 与 [tileir-011-design.md](tileir-011-design.md) 的关系：那篇 §1 与 §10 第 13 条把 K4 明确排除在 0.11 之外，本文是那条「另立」的落地。
> 本文所有行号是在上面那个提交上读出来的；没有量过的数字一律写「未量」，并写明由哪一刀去量。

## 0. 先纠正一个前提

任务说明里写「kernel 的标量（尺寸、缩放因子、序列长度、grid-stride 的程序数）今天都是编译期常量」。核对后只有一半成立：

- 尺寸、缩放因子、序列长度：对，今天只有两条路，一条是宿主常量烧进 kernel（§1.1），一条是把标量放进一个 i32 / f64 缓冲区、kernel 里 `load` 出来（§1.2）。
- **程序数不是标量参数**：`num_blocks(axis)`（`packages/tileir/src/dev.dawn:2883`）直接发 `get_num_tile_blocks`，是设备在运行期回答的 `Idx`。
  `scripts/tile-golden/kernels.dawn:3462` 的 `grid_stride` 已经在用它。所以 `d_range(.., step: By(num_blocks(0)))`
  不依赖 K4，只依赖 `Step[B]` 本身（0.11 的 S2 与 d_range 一刀）。ruling-drange-step 里「K4 落地后这是主线写法」应读成：
  K4 补上的是**循环上界与步长里的尺寸**（`By(nprog)` 的 `upper` 是运行期的 `n`），不是 `nprog` 本身。
  本文按这个更正后的前提设计，该更正已由 ruling-k4-design-20261007 第 7 条确认。

## 1. 今天的状态

### 1.1 宿主常量烧进 kernel

kernel 体是一个在记录期运行一次的闭包（`trace_kernel`，`packages/tileir/src/prog.dawn:1347`；体里每个 `Dev` 操作被 handler 记成一条 `TileOp`）。
体里用到的宿主 `Int` / `Float` 是闭包捕获的普通值，记录时就折进操作里：

- `f_const(F64, ATT_INV_SQRT_D)`（`kernels.dawn:2362`）、`lit(ATT_INV_SQRT_D)`（`kernels.dawn:2182`、`2214`）：缩放因子成了 `ConstF`；
- `d_range(0, LORA_DIN / LORA_T) { .. }`（`kernels.dawn:2064` 附近）：上界成了两条 `idx_const`；
- `grid_stride(x, out, rounds)`（`kernels.dawn:3462`）的 `rounds` 是宿主 `Int`，注释写明「`rounds` is a host constant」。

这条路的性质：值不同就是另一个程序，另一份 `.tilebc`，另一份 cubin。它与 cuTile Python 的 `ct.Constant` 同构（§2.2），不需要任何新语法，
而且这个形态要**保留**：编译期标量就是闭包捕获，不另设标注（§4.1）。

### 1.2 缓冲区里的运行期标量（T12 的做法）

T12 动态形状一刀需要「同一个 cubin 在两个形状上都对」，当时没有标量入口参数，做法是把形状放进一个 `Param[I32]` 缓冲区再读出来：

```dawn
fn dyn_dims(dims: Param[I32]) -> (Idx, Idx, Idx) !Dev = {
  let rows = idx_of(load(dims, idx_const(0), []))
  ...
```
（`kernels.dawn:4520`；`idx_of` 在 `dev.dawn:3126`，注释自己写着「a dynamic extent has to come from somewhere, and the general somewhere is a buffer」。）

代价是三层的：宿主要分配并上传一个缓冲区、kernel 要多一次全局内存 load、每个标量占一个缓冲区位置而不是一个参数。
结构上的事实是：缓冲区路与标量参数路在 kernel 里写出来的东西同形，
`load(dims, idx_const(0), [])` 换成 `scalar(n)`，下游的 `idx_of` 与 `tensor_view_dyn(.., [Dyn(rows), ..])` 不动。
这三层的数字是第 4 刀量的，在下面。

**量法**（`scripts/scalar-bench/`）：同一个 kernel `out = x * 3.0`，每块一个 128 lane 的 f64 tile，写成三份：
标量参数（`scalar(s)`，入口多一个 `tile<f64>` 参数）、缓冲区读标量（`load(s, idx_const(0), [])`，多一个一元素缓冲区）、
宿主常量（`f_const(F64, 3.0)`，入口少一个参数）。三份的 `.tilebc` 分别是 304、333、296 字节。

- 编译：同一台机器上 `tileiras`（13.4.92）对三份字节码各跑 3 次的墙钟毫秒。
- 启动：宿主观测的一次 launch 的耗时：200 次预热后，计时从第一次 launch 起到随后的 `sync` 止，除以 launch 次数，
  一次重复 N 次 launch，共 3 次重复，取中位数，写最小与最大。网格取 1 块（launch 本身是成本）与 1024 块（kernel 的访存也算进来）。
  每份在计时之后读回一次结果，确认算的是 `x * 3`。
- 命令：`scripts/scalar-bench/run.sh --tileiras <tileiras> --gpu-name sm_NN [--launches N]`；本机 3080 直接跑，
  B200 由外部 runner 在本仓库镜像里跑同一个脚本，tileiras 用本机 `install-tileiras.sh` 装出的三个文件
  （`bin/tileiras`、`bin/ptxas`、`lib/libnvvm.so.4`）随工作树带过去，远端先核 sha256（`8733d2ef`、`6f6a7015`、`eeef1ca7` 前缀）。
- 机器：RTX 3080（sm_86，WSL2，驱动 616.56，本机 16 核，非独占，无锁频）；B200（sm_100，驱动 580.159.04，卡独占，无锁频）。

**编译（`tileiras`，毫秒，中位数 最小 最大）**

| 机器 | 标量参数 | 缓冲区读标量 | 宿主常量 |
|---|---|---|---|
| RTX 3080 (sm_86) | 56 (56 到 59) | 56 (56 到 57) | 56 (55 到 57) |
| B200 (sm_100，`--opt-level 0`) | 74 (71 到 88) | 66 (62 到 66) | 61 (61 到 69) |

3080 上三份没有可见差别；B200 上标量参数那份中位数高了十几毫秒，但三次里一次是 88，离散度和差值同量级，不能据此说编译更慢。
cubin 大小：sm_86 为 6240 / 6368 / 6240 字节，sm_100 为 12616 / 12760 / 12456 字节。

**启动（纳秒每次 launch，中位数 最小 最大；每次重复 2000 次 launch）**

| 机器 | 网格 | 标量参数 | 缓冲区读标量 | 宿主常量 |
|---|---|---|---|---|
| RTX 3080 | 1 块 | 7011 (6986 到 7129) | 7136 (6866 到 7165) | 6152 (5866 到 7348) |
| RTX 3080 | 1024 块 | 6467 (6048 到 6772) | 6477 (6453 到 15960) | 8503 (8345 到 8920) |
| B200 | 1 块 | 5088 (5074 到 5196) | 5434 (5383 到 5567) | 4685 (4649 到 4829) |
| B200 | 1024 块 | 5100 (5049 到 5219) | 5500 (5444 到 5529) | 4697 (4606 到 4833) |

3080 另跑一次每次重复 5000 次 launch：1 块为 6895 / 6141 / 6119，1024 块为 5810 / 6102 / 5645（离散度到 13469 与 8958 的离群值），
两次的次序互相矛盾，**3080 上三份的启动差在噪声里**（WSL2 的驱动路径与非独占的 CPU 使宿主侧计时有几百纳秒到数微秒的抖动）。
B200 上三次重复很紧（最大与最小差 3% 到 4%），次序稳定：宿主常量最快，标量参数慢约 0.4 微秒（约 8%），缓冲区读标量慢约 0.7 到 0.8 微秒（约 15%）。
这个差是宿主一侧每次 launch 多传一个参数字或多传一个缓冲区指针的成本，不是 kernel 里那次 load：1 块与 1024 块的差值相同。

**结论（只限于这些数）**：在一次几微秒的 launch 上，标量参数比缓冲区读标量便宜（B200 上稳定可见，3080 上不可见），比烧进程序的宿主常量贵不到一微秒；
编译时间三份无可靠差别。代价不是「标量参数慢」，而是「每个不同的常量要一份 cubin」与「每个标量要一个缓冲区与一次 load」之间的取舍，
这两样都比本表量到的 launch 成本大得多，本表没有量它们。

### 1.3 入口签名里只有指针

所有写出这条链的地方都假定「入口参数 = 指针」，这是 K4 要动的全部面：

| 位置 | 事实 |
|---|---|
| `lower.dawn:323`（`Kernel.params`） | `params: List[String]`，每项是一个格式名，注释写明 every parameter is a scalar `tile<ptr<dtype>>` |
| `render.dawn:597` 与 `kernel_lines`（`render.dawn:614`） | 总是 `%arg{i}: tile<ptr<dt>>` |
| `bytecode.dawn:2153` 起（`encode_kernel`） | `nvals: len(k.params)` 预留参数值编号；每个参数 `ty(Tile([], PtrTo(dt)))` 后进 `func_ty` |
| `lower.dawn:697`（`pointers`） | 用 `Arg(param)` 引用第 `param` 个入口值，类型显式写 `Tile([], PtrTo(dtype))` |
| `prog.dawn:763`（`check_param`） | 记录时核对 `Param[D]` 的位置与格式与声明一致 |
| `dev.dawn:941`（`param`） | `Param[D] = (pos, dtype_name)`，只被 `load`/`store`/视图等「用指针」的操作消费 |
| `prog.dawn:1424`（`Arg[D]`） | `In` / `Out` / `Shared` 三个角色，都是缓冲区 |
| `std/gpu.dawn:712`、`770` | `gpu_launch(kernel, gx, gy, gz, args: List[Int])`，`args` 是缓冲区句柄 |
| `std/gpu.dawn:1061` 起、`1117` 起 | `Entry1..Entry5[A..]` 的类型参数是格式，`launch_entryN` 取 `Tensor[A]` |
| `std/gpu.dawn:1544`、`1655`（真设备） | `device_pointers(table, args)` 把句柄换成设备地址，交给 `gpu_launch_host` |
| `runtime/c/dawn_rt.c:5042` | `ptrs[i] = (CUdeviceptr)box.val.i; params[i] = &ptrs[i]`，每个参数按 8 字节地址传给 `cuLaunchKernel` |
| `selfhost/builtins.dawn:424`、`selfhost/src/check/types.dawn:3885` | `gpu_launch_host(module, kernel, gx, gy, gz, Array[Int])` 的 intrinsic 声明 |
| fake 设备（`std/gpu.dawn:1349`、`1380`） | 按名字找宿主参考函数 `WideRefFn`，传 `dtypes` 与各缓冲区的 `List[Float]` 内容 |

### 1.4 Tile IR 与 cuTile 允许什么

- Tile IR 规范（13.4）：`cuda_tile.entry` 的参数由 `function_type` 决定，**规范的 entry 条目没有逐类型列举**；它写明 kernel 不能返回值、
  必须由宿主用 `cuLaunchKernel` 启动、启动时给三维 grid。来源：https://docs.nvidia.com/cuda/tile-ir/13.4/sections/operations.html
  （只读了该页前十万字符）。
- 检索摘要（未逐字核对原页）称：kernel 参数是 SSA 值，类型必须是 rank-0 的 tile，输入张量以标量指针提供。
  来源：https://docs.nvidia.com/cuda/tile-ir/latest/sections/prog_model.html 、https://docs.nvidia.com/cuda/tile-ir/13.4/sections/prog_model.html
  这与「rank-0 的 `tile<i32>` / `tile<f32>` 是合法入口参数」相容，但**没有一条一手引文说整数与浮点 rank-0 tile 可以作入口参数**。
  所以第 1 刀的第一件事是量：手写字节码，入口 `(%n: tile<i32>, %s: tile<f32>)`，过 `tileiras`（层 1）再在设备上读回（层 2）。量出来之前本文的 §3.2 是假设。
- cuTile Python：标量参数「passed directly」，是 bool / int / float；`ct.Constant[T]` 标注的参数被内嵌成常量，「a distinct machine representation of the kernel for each different value」，
  机器表示 0 字节；整数参数默认推断为 int32，`ct.ScalarInt64` 强制 int64。来源：
  https://docs.nvidia.com/cuda/cutile-python/execution.html 、https://docs.nvidia.com/cuda/cutile-python/compilation.html 、
  https://docs.nvidia.com/cuda/cuda-programming-guide/02-basics/writing-tile-kernels.html
  文档没有谈基于值的特化或对齐整除特化（读到的页面里没有）。
- 仓库自己的台账里**没有**一个 golden 的入口参数不是指针：`git grep` 入口行里的 `tile<i32>` / `tile<f32>` 参数在 `scripts/tile-golden/*.mlir` 为 0 处。这是 K4 第一次发这种入口。

## 2. 别的语言怎么做

| 系统 | 运行期标量 | 编译期标量 | 值特化 | 来源 |
|---|---|---|---|---|
| Triton | 无标注的参数就是运行期标量，作为 kernel 参数按值传 | `tl.constexpr`：每个不同的值编一个变体 | 默认对整数参数按三类特化：等于 1、能被 16 整除、其他；`do_not_specialize` 可关。这是自动的，换类就重编 | https://triton-lang.org/main/python-api/generated/triton.jit.html （页面只列出 `do_not_specialize` 签名，没有解释）；特化规则取自检索摘要：https://pytorch.org/blog/triton-kernel-compilation-stages/ 与若干 issue，**未逐字核对** |
| cuTile Python | 无标注的标量参数，整数默认 int32 | `ct.Constant[T]`，每个值一份机器表示 | 文档未提 | §1.4 的三个 URL |
| CUDA C++ | `__global__` 的按值参数，参数区上限与参数字节数是驱动的事 | 模板参数 | 无（编译器按模板实例化，参数值不特化） | CUDA C++ Programming Guide 的 kernel 参数一节，**本文未查阅原页**，只作为背景，不据此下任何设计结论 |
| cutile-rs | `#[cutile::entry]` 函数的普通标量形参，如 `qk_scale: f32`、`alpha: f32` | const 泛型 | 未查 | https://github.com/NVlabs/cutile-rs 的 `flash_attention.rs`、`mxfp8.rs`（见 research-generic-kernel-report-20261006 §5） |

对 Dawn 有用的三点：

1. **「编译期还是运行期」在三个系统里都写在参数声明处**（`constexpr`、`ct.Constant`、泛型 const），而不是写在使用处。Dawn 的记录期模型让这一点更省：
   kernel 体是闭包，捕获宿主值就是编译期，所以只需要给**运行期**那一种加一个声明。
2. **Triton 的整除 16 特化是自动的、值相关的**，换来的是对齐假设，代价是同一 kernel 的变体数不可预知，且第一次遇到新类时要重编。
   Dawn 的字节码在宿主看到值之前就生成，没有「按值重编」的位置；Tile IR 已有作者显式声明的 `assume div_by`（`dev.dawn:3368` 的 `assume_div_by`）。
   所以 Dawn 不做自动特化（§8 第 1 条），整除信息由 kernel 作者显式 `assume_div_by` 给出。
3. **整数标量的位宽要明确**：cuTile 默认 int32 并给 int64 开关。Dawn 的 `Idx` 就是 rank-0 `i32`，标量尺寸默认走 `I32`，需要 64 位时写 `I64`，不靠推断。

## 3. 提议的表面

### 3.1 kernel 侧

运行期标量是 `Arg[D]` 的第四个角色，与缓冲区的三个角色并列：

```dawn
pub type Arg[D] =
  | In(d: D, g: Cells)
  | Out(d: D, g: Cells)
  | Shared(d: D)
  | Scalar(d: D)         # 名字已裁，见 §7 第 1 条
```

`d` 仍是格式见证（`std/dtype` 的 `Dtype[T]`：`I32`、`I64`、`F32`、`F64`），所以「std 的值类型就是格式」这一条不变：
`Scalar(F32)` 的宿主值类型是 `F32` 对应的宿主类型，格式名与 `In(F32, ..)` 里的是同一个词。

body 参数仍是 `Param[D]`（`trace1..5` 的签名不变）。一个新操作把它读成设备值：

```dawn
pub fn scalar[D](p: Param[D]) -> Tile[D] !Dev      # rank-0 tile
```

- `scalar` 对 `In`/`Out`/`Shared` 参数在记录期拒绝，`load`/`store`/视图/`ptrs` 对 `Scalar` 参数在记录期拒绝。这与「`In` 记录期拒绝写」同一类机制
  （`prog.dawn` 的 `Access` 与 `check_param` 一线），**不是**编译期类型错误。选这条路的理由是 `trace2(.., body: fn(Param[A], Param[B]) -> ..)` 的 body 类型对四个角色必须一致，
  否则每种角色组合要一个 `traceN`；代价是误用在记录期而不是检查期暴露，而每个 kernel 都有 golden 记录，所以暴露点是测试而不是线上。
- `scalar(p)` 的结果是 rank-0 `Tile[D]`。算术走现有的 rank-0 加宽规则（`dev.dawn` 里「a rank-0 accumulator is widened」「the rank-0 rule widens it」），
  所以 `s * scalar(scale)`、`mma(..) * scalar(scale)` 不需要新规则。L3 之后写成 `mma(tq, kt, 0.0) * scalar(scale)`，与 cutile-rs 的 `qk * qk_scale` 同形。
- 要当索引用时：`idx_of(scalar(n))`，`idx_of` 已经存在（`dev.dawn:3126`）。**不另造 `scalar_idx`**：一个概念一个名字，`Tile[I32]` 到 `Idx` 的那一步已经有名字。
  `scalar` 对 `Param[I32]` 的结果因此直接接进 `d_range(0, idx_of(scalar(n)), step: By(num_blocks(0)))`。

### 3.2 允许的格式

第一版允许 `I32`、`I64`、`F32`、`F64`。理由：它们是 `cuLaunchKernel` 按值传、参数大小为 4 或 8 字节的格式，host 侧各有现成或可写的位模式
（`std/narrow.f32_bits` 在 `narrow.dawn:833`；`I32`/`I64` 是整数本身；`F64` 需要一个 `f64_bits`，今天没有，§5 第 2 刀补，纯算术，与 `f32_bits` 同法）。
`F16`/`BF16`/`I16`/`I1`/fp8/`I4` 先拒绝：小于 4 字节的参数在参数区里的布局与填充没有量过，`I1` 在 Tile IR 里是 rank-0 `tile<i1>` 而宿主没有对应的位。
拒绝在编译期：`Scalar[D: ScalarDtype]`，`ScalarDtype` 优先复用 `std/dtype` 的 `HasDtype` 加子集约束，不另造平行体系（§7 第 4 条）。

### 3.3 编译期标量

不加任何东西。闭包捕获的宿主 `Int` / `Float` 就是编译期标量（§1.1）。两种写法的区别只有一个：**哪一个让 cubin 随值变**。
`kernels.dawn` 里目前的写法全部属于第一种，K4 不迁移它们（§5 第 5 刀按需迁一两个有判词的）。

### 3.4 与 `d_range` 的 `Step` 的衔接

`d_range[B: RangeBound](lower: B, upper: B, step: Step[B] = Unit, ..)` 里 `B` 可以是 `Idx`。有了 `Scalar`，一个持久化 kernel 写成：

```dawn
fn persistent(x: Param[F32], n: Param[I32], out: Param[F32]) -> Unit !Dev = {
  let rows = idx_of(scalar(n))
  for r in d_range(block_id(0), rows, step: By(num_blocks(0))) {
    ...
  }
}
```

`Step`/`By` 的形状已由 ruling-drange-step 定死，K4 不改它。K4 对它的唯一要求是：`upper` 是运行期 `Idx` 时 `d_range` 的 Idx 臂已经支持（§1.2 的 `idx_of` 路径今天就在 `d_for` 上用）。

### 3.5 宿主侧

`Entry1..Entry5` 的类型参数今天是格式 `A`，`launch_entryN` 取 `Tensor[A]`。标量位置取的是**值**而不是 `Tensor`，所以需要一个宿主侧的实参类型把两者统一：

```dawn
pub opaque type Launch[A] = ...                 # 一个已经绑好的实参，A 是格式
pub fn buffer[A](t: Tensor[A]) -> Launch[A]     # 缓冲区
pub fn scalar[A: ScalarDtype](v: A) -> Launch[A]  # 标量，v 就是 A 的 std 宿主值类型
pub fn erase[A](l: Launch[A]) -> LaunchArg        # 无类型的 `launch` 收的是擦除后的实参
```

公开的无类型 `launch` 也只有这一种写法：`launch(kernel, grid, args: List[LaunchArg], ..)`，缓冲区与标量都经 `buffer`/`scalar` 再 `erase` 进同一个列表，**没有只收缓冲区句柄的第二个入口**（§7 第 3 条）。
于是 `launch_entry2[A, B](e: Entry2[A, B], a: Launch[A], b: Launch[B], grid: List[Int] = [])`。`entry2(.., arg_in(..), arg_scalar())` 的第二个 `EntryArg`
（`std/gpu.dawn:810` 的 `EntryArg` 家族加一个 `arg_scalar()`）告诉启动「这个位置要标量」，位置与实参种类对不上是启动前的 `gpu.bad_entry`，
与「同一个缓冲区传两次」的 `gpu.aliased_argument` 同一类（`std/gpu.dawn:1015` 的 `launch_plan`）。理由与限制：

- 编译期能说的是**格式与个数**（`Launch[A]` 的 `A`），编译期说不了的是**种类**（缓冲区还是标量）。种类由 entry 的 `EntryArg` 在启动前核对，
  这是 std/gpu 现有分工的延伸（`std/gpu.dawn` 的「typed entries」注释：what the type cannot say is checked here, above the effect）。
- 标量的宿主值类型是 std 值类型本身：`F32` 格式传 `narrow.F32`，`F64` 传 `Float`，`I64` 传 `Int`（§7 第 5 条）。

### 3.6 `Gpu` 效果与真设备

`gpu_launch` 的 `args: List[Int]` 变成一个能区分缓冲区与标量的列表。形状（§7 第 3 条已裁：公开 `launch` 与效果操作用同一个列表）：

```dawn
pub type LaunchArg =
  | Buf(handle: Int)
  | Word(dtype: String, bits: Int)

fn gpu_launch(kernel: String, gx: Int, gy: Int, gz: Int, args: List[LaunchArg]) -> Result[Unit, ForeignError]
```

真设备（`with_gpu_real`）把 `Buf` 换成设备地址、`Word` 保持位模式，都放进同一个 `Array[Int]` 交给 `gpu_launch_host`。
**C 运行时与 intrinsic 声明因此一个字都不用动**：`dawn_rt.c:5042` 对每个参数传 `&ptrs[i]`，一个 8 字节的字；
`cuLaunchKernel` 按 kernel 声明的参数大小从那个地址取前 4 或 8 字节，x86-64 与 aarch64 都是小端，所以 `I32`/`F32` 的位模式放在 Int 的低 32 位就是正确的参数字节，
`I64`/`F64` 占满。这一条依赖「驱动按声明大小读、不检查多出的字节」，是**假设**，第 3 刀在 3080 上量（同一个 kernel 传 `bits` 与带垃圾高位的 `bits`，读回应相同）。
如果量出来不成立，退路是改 `dawn_rt.c`（同一个 Array[Int]，另加一个 `Array[Int]` 的宽度表），那会碰 selfhost 的 intrinsic 声明与 `rtsrc` 嵌入，代价高得多，所以先试不碰的路。

fake 设备（`with_gpu_fake`，`std/gpu.dawn:1349`）：宿主参考函数 `WideRefFn` 今天接 `(dtypes, ins: List[List[Float]])`。标量不是缓冲区，
所以参考函数多接一个按声明序的 `List[Float]`：`(dtypes, ins, scalars) -> List[Float]`。这改了 `reference_kernels()` 里每个现有参考的签名（`vadd_ref`、`sum_ref` 两个，
`packages/tileref/src/ref.dawn` 里按名字登记的那些另算，见 §6），属于破坏性改动，**不留旧签名**。

## 4. 降低

### 4.1 入口签名与 SSA 值

- `TileProg.params` 与 `Kernel.params` 今天是 `List[String]`。K4 需要每一项说明「指针」还是「标量」。推荐把它升成
  `List[KParam]`，`KParam = | ByPtr(dtype: String) | ByValue(dtype: String)`（§7 第 2 条已裁；数出的改动面是 `params: [` 35 处、`trace_kernel(` 调用 87 处）。
- 渲染：`%arg{i}: tile<ptr<dt>>` 对 `ByPtr`，`%arg{i}: tile<dt>` 对 `ByValue`。字节码：`ty(Tile([], PtrTo(dt)))` 对 `ByPtr`，`ty(Tile([], Num(dt)))` 对 `ByValue`；
  `Num` 臂的 `i32` / `f32` / `i64` / `f64` 在写入器里已有（它们是普通 tile 的元素类型）。
- 值编号：`nvals: len(k.params)`（`bytecode.dawn:2153`）已经给每个参数预留编号，标量参数**不新增一条指令**：
  `ByValue` 参数 `i` 就是值 `Arg(i)`，类型 `Tile([], Num(dt))`。记录侧新增一条 `TileOp`，`ScalarArg(dst, param)`，
  `lower` 对它不发指令，只把句柄 `dst` 绑到 `Arg(param)` 并记类型（对照 `lower.dawn:697` 把 `Arg(param)` 当 `Ref` 用的写法，以及 `define`/`bind` 在 `lower.dawn:591` 前后的绑定函数）。
  这条只在读了 `lower.dawn` 的这几处之后写下，**没有实现过**；第 1 刀的第一个单元测试就是它。
- 由于不发指令，`ScalarArg` 在 `lower_spans` 的 `Owner` 表里没有行；调用图/悬停对它的归属（`CallLines`）需要核对一次（§5 第 1 刀列了一条测试）。

### 4.2 对现有台账的影响

- **现有 191 个 kernel 的 `.mlir` 与 `.tilebc` 逐字节不变**：`params` 里每一项都是 `ByPtr`，渲染与编码走原来的臂。这是第 1 刀的判据，不是推测；
  `tile-golden/run.sh` 的层 0 会直接红绿。变异体负控见 §5 第 1 刀。
- **tile 输入摘要会动**：`packages/tileir`、`packages/tileref`、`std/gpu.dawn` 都在 `TILE_PATHS`（`scripts/tile-gpu-diff/inputs.py:34`）。
  按项目规则，凡是动摘要的 PR 带自己的台账重录（`ledger.txt`、`ledger-sm90.txt`、`ledger-sm100.txt`，层 2；sm_90 / sm_100 走外部 runner）。
  本机 3080 是 sm_86，所以 sm_86 的账本机录，另两本走外部 runner。
- 新增 golden：每个新 kernel 一对 `.mlir`/`.tilebc`，进 `matrix.txt`。现在是 241 项十一片，每片 575 到 608 秒，pole 660 秒（`tile-backend-design.md` §6.5 的 T12 行）。
  新增项会不会越过 pole **未量**：第 1 刀用 `ITEM_TIMES` 量新项耗时再判断要不要分第十二片。**改 CI 必须报墙钟**，所以这条在第 1 刀的 PR 里写数。
- `std/gpu.dawn` 与 `std/narrow.dawn` 改动：要跑 `scripts/gen-stdsrc.py`，`stdsrc.dawn` 同批提交，Core golden 之后重录（T12 刀的前例，`tile-backend-design.md` §6.15）。
  `Emit-Change(<label>)` 是否需要：只在 selfhost 的 emit 输出改变时要。K4 不改 selfhost 编译器与 intrinsic（§3.6 的假设成立时），
  `stdsrc` 是 embed 的输入但 `emit selfhost` 一类差分的逐字节结果是否因它变化，**要在第 2 刀实测后按 `scripts/emit-labels.txt` 逐 label 声明**，本文不预判 label 名。

### 4.3 参考实现（tileref）与 GPU 页

- 仓库里没有 Tile IR 的解释器：`packages/tileref/src/ref.dawn` 是**逐 kernel 的宿主参考函数**（头注释：a plain function of the argument buffers' formats and contents），
  `scripts/tile-gpu-diff` 把设备结果与它比。所以「参考解释器」在这里的意思是：每个用到标量的 kernel 的参考函数多接一个标量参数。
  这反而是 K4 的一个好处：一个参考函数 `attn_ref(q, k, scale)` 同时服务两个 scale 值的两个用例，不再是常量烧进参考。
- tileref 的头注释规定它只依赖 std、不得在清单里写 `tileir`（`scripts/leetgpu-diff/check.py` 检查）。K4 的标量值类型与 `Launch` 都在 std/gpu，不破坏这条。
- GPU 页：`docs/gpu-page-newapi-design.md` 的页面讲 tileir 0.8 API，七件事与代码片段取自真 kernel。K4 的表面（`Scalar`、`scalar`、`scalar(..)`）
  是新增，**不在本文范围里改那一页**；§5 第 5 刀末尾列一条「页面是否要加一段」的判断，按那篇文档的 §二 规则（每件事配一段真代码）由写页者裁。

## 5. 刀序

每刀一个提交。按「一个主题一个 PR」分：**PR-A**（第 1、2 刀，机制与宿主表面，一次摘要重录）、**PR-B**（第 3、4 刀，设备判词与量），**PR-C**（第 5 刀，迁移）。
PR-A 与 PR-B 都动 tile 摘要，各自带自己的 ledger 重录；为减少重录，可以把 B 并进 A 的栈而不并进 A 的提交（栈内每个提交的摘要不必各自重录，PR 的最终树重录一次，沿用 K1+K2 的先例，tileir-011-design §1）。

| 刀 | 内容 | 判据 / 测试 | 负控 |
|---|---|---|---|
| 1 | **量**：手写 `tile<i32>`、`tile<f32>` 入口字节码，`tileiras` 汇编，3080 上读回。再做 `KParam`、`Scalar`、`scalar`、`ScalarArg`、渲染与编码两臂，写 `scalar_scale` 与 `scalar_len` 两个新 kernel | 层 0：新 golden 两个；**现有 191 对 golden 零字节变化**。层 1：`tileiras --gpu-name sm_86` 收下。包内测试：`ScalarArg` 不发指令、`Owner` 表无行、`scalar` 对非 `Scalar` 参数拒绝、`load` 对 `Scalar` 参数拒绝 | 层 0/1 变异体三条：`scalar-param-as-ptr`（写入器把标量参数仍写成 `tile<ptr<..>>`，文本与字节、`tileiras` 都应红）、`scalar-dtype-as-i32`（`f32` 写成 `i32`，同宽异类，`tileiras` 应拒）、`scalar-arg-index-shifted`（值编号错一位，另一参数被当标量，`tileiras` 或设备红）。每条先证明会红再接入矩阵 |
| 2 | **宿主**：`LaunchArg`、`gpu_launch` 新签名、**公开 `launch` 改收 `List[LaunchArg]` 并在同一刀迁完 `scripts/tile-gpu-diff/*.dawn` 里约 26 个 `launch(` 调用点及其余调用方**、`arg_scalar`、`Launch[A]`、`buffer`/`scalar`/`erase`、`launch_entryN` 新形参；fake 设备的 `WideRefFn` 多接 `scalars`；`f64_bits`；两个 handler 的测试 | 包内与 `dawn test --stdlib`：种类不符 `gpu.bad_entry`、标量个数不符、`F16` 等被拒的格式在 `Scalar` 构造点报；`with_gpu_fake` 下 `vadd_scaled` 在两个 scale 值上得两个不同答案 | `std` 变异体：`scalar` 把 `F32` 位模式当 `F64` 写（宿主测试红）、`launch_plan` 不核对种类（`gpu.bad_entry` 的测试红）。**变异体改 `std/gpu.dawn` 必须同时跑 `gen-stdsrc.py`**，否则等于没改（既有教训：std 变异体不跑 gen-stdsrc 等于没改） |
| 3 | **设备判词**：`scripts/tile-gpu-diff` 新增一个族 `scalar_diff.dawn`：同一个 cubin 两个标量值各一次，另有 `I32` 长度当掩码边界与当循环上界两个用例；并量 §3.6 的「高位垃圾」假设 | 3080 上全部 `identical:exact` 或在已声明容差内；**同一 cubin、两个 scale 值都对**是判词；`bits` 带垃圾高位与干净位模式结果相同（假设成立的证据） | 层 2 变异体三条：`word-high-bits-cleared`（宿主在传 `I32` 前清高位时仍应绿，作为假设的控制）、`scalar-passed-as-handle`（`Word` 当 `Buf` 走 `device_pointers`，设备应红）、`scalars-swapped`（两个标量位置对调，两个用例都红）。外部 runner sm_90 / sm_100 重录 |
| 4 | **量**：同一个 kernel 的「标量参数版」「缓冲区读标量版」「宿主常量版」三份，在 3080 与外部 runner sm_100 上量单次 launch 与编译（`tileiras`）耗时，写回本文 §1.2 的「未量」 | 数字入文档，带命令与机器。**只有这一刀产出性能结论** | 无变异体，量的是时间不是正确性；重复三次取中位数并写离散度 |
| 5 | **迁移**（可选、可拖）：把 `flash_attn`（`kernels.dawn` 的 `ATT_INV_SQRT_D`）改成 `scalar(scale)` 一份新 kernel；`T12` 的 `dyn_dims` 一族是否改标量参数，另议 | 被改 kernel 的 golden 重录，且重录差异**只**在入口签名与那一处常量；其余 kernel 逐字节不变 | `tile-golden` 里被迁移的 kernel 的变异体沿用；新增一条 `scale-baked-again`（`scalar(scale)` 又写成 `f_const`，golden 应红，证明迁移真的发生了） |

提交信息英文、一行祈使句主题，不带 Claude 署名。

**依赖**：第 1 刀先量 `tileiras` 是否接受 rank-0 i32/f32 入口参数，测不通就停下报告，不硬做（§7 末段）。第 1 刀不依赖别的刀。第 2 刀依赖第 1 刀的 `KParam`（`arg_scalar` 对应 `ByValue`）。第 3、4 刀依赖 3080 与外部 runner。K4 排在 0.11 之后、native 性能刀之间（§7 第 7 条）；与 S2/L3/`Step` 无硬依赖，但 §3.4 的持久化写法要等 `Step` 落地，所以第 5 刀排在 0.11 之后。
**版本**：`KParam` 与 `ScalarArg` 是新 `Dev` 操作与公开类型的变化，按 CHANGELOG 的规则（a new `Dev` operation moves the minor）是一次 minor；`gpu_launch` 与 `WideRefFn` 签名变是 `std/gpu` 的破坏性变化。
版本已裁：单独作为 tileir 0.12.0，不并进 0.11（§7 第 6 条）。

## 6. 影响面清单（动码前重数一遍）

- `packages/tileir/src`：`prog.dawn`（`Arg`、`Sig`、`TileOp`、handler、`check_param`、`trace1..5`）、`lower.dawn`（`Kernel.params`、`Arg`、`ScalarArg` 臂）、
  `render.dawn`、`bytecode.dawn`、`dev.dawn`（`scalar`、`t_scalar` 效果操作与 `Dev` handler 的一臂）。
- `std/gpu.dawn`：`Gpu` 效果、`launch`、`EntryArg` 家族、`Entry*`/`launch_entry*`、两个 handler、`reference_kernels` 与 `WideRefFn`；`std/narrow.dawn`：`f64_bits`。
- `packages/tileref/src/ref.dawn`：参考函数签名（凡是登记进 `reference_kernels` 或被 `tile-gpu-diff` 调用的）。
- `scripts/tile-gpu-diff/*.dawn`：`launch(` 出现约 26 处（`git grep -n "launch(" scripts/tile-gpu-diff/*.dawn | wc -l`），
  §7 第 3 条已裁：公开 `launch` 改实参类型，这些调用点在第 2 刀同一个提交里全部迁完，另扫其余目录（`git grep -n "gpu.launch\|launch("`）有无调用方。
- `scripts/tile-golden`：`kernels.dawn`、`matrix.txt`、新 golden、新变异体。
- 台账：`scripts/tile-gpu-diff/ledger*.txt`（三本）、`scripts/tileir-features/*`（`features.txt` 里入口参数的那一行是否存在，动码前核对）。
- 文档：`packages/tileir/CHANGELOG.md`、`docs/tile-backend-design.md` 的刀表（一行）、`docs/README.md` 的索引。
- **不动**：`runtime/c/dawn_rt.c`、`selfhost/builtins.dawn`、`selfhost/src/check/types.dawn`、`selfhost/src/jvm/rtclasses.dawn`（§3.6 的假设成立时）。

## 7. 已裁决的七个问题

七条全部由 ruling-k4-design-20261007（维护者工作区 agent-handoff）裁定，本文已按它改写。原先的选项与论证不再保留，只记结论与它改变了本文哪里。

1. **角色名用 `Scalar`，不用 `Uniform`。** 读取函数已叫 `scalar`，一个概念一个名字；`Uniform` 是图形 API 的术语。
   裁决里写明「若 `Scalar` 在 tileir 里撞名，写者报来再定」。动码前已知两处要核对：`Arg.Scalar` 与 `KParam` 的构造子同名，所以 `KParam` 取 `ByPtr` / `ByValue`（本文已用）；
   宿主侧 `std/gpu.scalar(v)` 与 kernel 侧 `tileir.scalar(p)` 同名不同模块，一个程序同时 `use` 两者的裸名会撞，第 2 刀核对这一点并报告，不预先改名。
2. **`params` 用 `List[KParam]`。** 采纳，见 §4.1。
3. **只有一个公开 `launch`。** 否决「effect op 收 `List[LaunchArg]`、公开 `launch` 仍只收缓冲区」：那是两套发射面，理由只是少迁约 26 个调用点。
   按「不做兼容层、直接破坏并迁移调用方」的规则，公开 `launch` 统一收 `List[Launch[..]]` 一类的实参，缓冲区与标量用一种写法（`buffer(t)` / `scalar(v)`），
   26 个调用点（`git grep -n "launch(" scripts/tile-gpu-diff/*.dawn`）在**同一刀**迁完（§5 第 2 刀）。
4. **不支持的格式在编译期拒绝。** 采纳 `ScalarDtype` trait；能复用 `std/dtype` 的 `HasDtype`（`std/dtype.dawn:45`）加子集约束时优先复用，不另造平行体系。
   第 1 刀先看 `HasDtype` 能否表达「只给 I32/I64/F32/F64」的子集界，不能再退到一个窄 trait，并在 PR 里写明为什么。
5. **宿主值类型用 `narrow.F32` 等 std 值类型。** 采纳，符合「std 值类型兼作格式」；`F64` 与 `I64` 就是 `Float` 与 `Int`。
6. **版本：单独作为 tileir 0.12.0，不并进 0.11。** K4 的 tile 摘要重录因此与 0.11 的 PR C 错开。
7. **前提更正确认。** `nprog` 就是 `num_blocks(0)`，已是运行期 `Idx`，`By(num_blocks(0))` 只依赖 0.11 的 `Step`。
   K4 的优先级因此排在 0.11 之后、native 性能刀之间，不抢 0.11。

另有一条操作性的裁决：**第 1 刀先测 `tileiras` 是否接受 rank-0 的 i32/f32 入口参数，测不通就停下报告，不硬做。** 新 golden 是否让 tile-golden 分片越过 pole，在第 1 刀量。

## 8. 不做的（理由）

1. **Triton 式自动特化（整除 16、等于 1）**：Dawn 的字节码在宿主看到值之前就生成，没有「按值重编」的位置；自动特化让同一 kernel 的变体数不可预知。
   整除信息由作者显式 `assume_div_by`（`dev.dawn:3368`）给出，那是已有的、可以在负控里钉住的写法。
2. **给编译期标量加标注（`ct.Constant` 的对应物）**：kernel 体是记录期闭包，捕获宿主值就是编译期，加标注是第二种写法表达同一件事。
3. **`scalar_idx`、`uniform_int` 之类的派生读取函数**：`idx_of(scalar(n))` 已经是 `Tile[I32]` 到 `Idx` 的唯一一步，再加名字就是一个概念两个名字。
4. **第一版就支持 `F16`/`BF16`/`I16`/`I1`/fp8/`I4` 标量**：小于 4 字节的参数区布局没有量过（§3.2）；真有消费者再量再开。
5. **Tile IR 一侧用「读缓冲区」模拟标量来省入口参数**：那正是今天的做法（§1.2），K4 的全部理由就是去掉它的 load 与缓冲区。
6. **运行期标量参与 tile 形状**：Tile IR 的 tile 形状是类型的一部分，一个 `tile<?xf32>` 并不存在；动态的是 `tensor_view` 的 extent（T12 已有），形状仍由宿主常量决定。
7. **让 `Tile[D]` 的运算符直接收宿主 `Float` 标量（`t * scale`，`scale` 是宿主 `Float` 参数）**：那会把「编译期烧进」与「运行期读入」写成同一个字面，读者看不出 cubin 会不会随值变；
   运行期那种必须显式写 `scalar(p)`。
8. **批量标量（把多个标量打成一个结构体或一个缓冲区传）**：入口参数已能按个数传；打包是 §1.2 的缓冲区路，没有新东西。
9. **对旧 `gpu_launch` 签名或 `reference_kernels` 的旧参考签名留别名**：没有外部消费者，按「破坏性变更不做兼容层」直接改并迁调用方。
10. **在本篇里改 GPU 页或写页面文案**：页面设计在 `gpu-page-newapi-design.md`，K4 表面落地后由写页者按那篇的规则判断要不要加一段。
11. **在 K4 里迁移全部带缩放常量的 kernel**：迁移会重录对应 golden，与「现有 golden 零变化」这条判据混在同一个 PR 里就无法分辨哪一条是预期；只迁一两个有判词的（§5 第 5 刀）。

## 9. 落地记录（tileir 0.12.0）

刀 1 到刀 4 已落地（刀 5 没做，见下）。与上面正文不同或正文没说到的地方：

- `ScalarDtype` 在 `std/gpu`，不在 `packages/tileir`：它带两个方法，`scalar_dtype`（格式见证，tileir 读）与 `scalar_word`（宿主值变成启动的参数字），
  一份 trait 两头用。没有复用 `HasDtype`：Dawn 没有 supertrait，子集只能自成一个约束。#600 之后 opaque 类型只继承 `Eq`、`Hash`、`Ord`，
  所以 `scalar` 对 F16、BF16、I8 是编译期拒绝（checker corpus 的 `scalar_dtype_opaque`）。`Scalar(F16)` 标记是 `Arg` 的构造子，挂不上 trait 约束，
  仍在记录期拒绝，`ByValue("f16")` 这种字符串写的格式同理。
- 标量的宿主值类型：`Float` 与 `Int` 就是 f64 与 i64，`I32` 与 `narrow.F32` 是 i32 与 f32；`std/narrow` 新增 `f64_bits`、`f64_of_bits`。
- `LaunchArg = Buf | Word`，`Word` 是格式名加位模式（i32 与 f32 在低 32 位）。真设备把它原样放进参数字，`dawn_rt.c` 没改：
  3080 上量过，参数字高 32 位是垃圾（`0xDEADBEEF`、`0x7FFFFFFF`、`0xFFFFFFFF`）时 i32 与 f32 的答案不变（`scalar_diff` 三个 garbage 用例，
  `word-high-bits-cleared` 是宿主侧清高位仍绿的对照）。
- `std/gpu` 的缓冲区没有 f32（`element_bytes` 里没有），所以 `scalar_scale` 与 `scalar_len` 用 f64 缓冲区，`scalar_scale` 在设备上把 f32 标量加宽成 f64 再乘。
- 新 golden 四个（`scalar_scale`、`scalar_len`、`scalar_loop`、`scalar_wide`），新 mutant 六条（三条 golden 层，三条设备层）。
- **刀 5（把 `flash_attn` 的 `ATT_INV_SQRT_D` 迁成 `scalar(scale)`）后来做了**：f64 与 bf16 两个 kernel 各一个提交，golden 只动入口签名与那一处常量，变异体 `scale-baked-again`；复核与剩余缺口见 [flash-attn-ideal-audit.md](flash-attn-ideal-audit.md)。当时认为它「远不止改一个 kernel」，实际落点是 `seq_diff` 的 `Step` 多一个 `scalars` 字段、参考函数读启动标量，以及 `record.py` 认 `Scalar` 标记。
