# tileinterp：Tile IR 宿主解释器（子集 A）

> 状态：**current** —— 2026-10-20 裁决（`ruling-tileir-interp-20261020`）的第一刀 I1。
> 新包 `packages/tileinterp` 解释 `packages/tileir` 降级后的 `lower.Kernel`，子集 A
> （f64 与整数）。I2 加 mma 与窄格式，另起一篇或回填本篇。

## 0. 一句话

假设备（`std/gpu` 的 `with_gpu_fake`）答的是一次 launch 的**宿主参考实现**，从来不跑
kernel 体。本包第一次让 kernel 体本身在没有 GPU 的机器上执行：`interp_ref(prog, grid)`
把一个记录好的 `TileProg` 变成 `WideRefFn`，直接塞进 `with_gpu_fake` 的表里，
`std/gpu` 一行不改。CI 里多一条「解释器 vs tileref」的对拍，复用 tile-gpu-diff 的语料、
参考与判词。设备仍是唯一权威，解释器是第三个意见。

## 1. 解释哪一层

解释 `lower.Kernel`（`packages/tileir/src/lower.dawn` 的 `Instr`，60 个变体），不解释
记录期的 `TileProg`，也不解释字节码或 MLIR 文本。理由（调研 §一）：

| 层 | 为什么不选 / 为什么选 |
|---|---|
| `TileProg`（71 个变体） | `Load`/`Store`/`CellViewOf` 等是记录期糖，lowering 补上的指针阶梯、`assume div_by`、token 线都看不见，`lower.dawn` 自己的错抓不到 |
| **`lower.Kernel`** | text golden 与 bytecode 共用的唯一来源（`lower.dawn` 头注释），每条指令带结果类型与操作数类型，属性已编码进操作名后缀（`addf_neg_inf`、`maxf_nan`）。解释它就是解释「真正发出去的东西」，只差字节编码一步，而编码错误由层 1（`tileiras` 接收）与字节 golden 守住 |
| 字节码 / MLIR 文本 | 要写与写入器对称的解码器或 `cuda_tile` 解析器（2000 行以上），换来的保真度是层 1 已经覆盖的 |

**tileir 侧的接口**：`lower.lower(prog) -> Kernel` 与 `Kernel`、`Instr`、`Ty`、`Ref` 在 tileir
里一直是 `pub`（tileir 全包没有一处 `pub(pkg)`，`grep` 为零），裁决设想的「把 `lower.Kernel`
暴露成 `pub(pkg)` 以外的只读接口」**已经成立，不用改 tileir 一行**。所以本刀不发 tileir 版本、
台账输入摘要（`scripts/tile-gpu-diff/inputs.py` 的 `TILE_PATHS`）不动。tileir 的 CHANGELOG
记一条「`lower` 模块现在有包外消费者」：今后给 `Instr` 加变体，tileinterp 的穷尽 `match`
编不过，这是有意的（新 opcode 必须在 lower、bytecode、解释器三处同时落地）。

## 2. 语义模型

### 2.1 网格

`interp_ref(prog, grid)` 的 `grid` 是 `[gx]`、`[gx, gy]` 或 `[gx, gy, gz]`，缺的轴是 1。假设备
「不查网格」（`with_gpu_fake` 文档），所以网格必须由调用方在构造时给。block 按 z、y、x 嵌套、
x 最内的顺序**顺序执行**，每个 block 的 `get_tile_block_id` 答自己的坐标，`get_num_tile_blocks`
答网格。这就是 Triton 解释器的做法（`GridExecutor` 三重 for 循环顺序跑每个 program）。
block 间写入不相交时，任何执行顺序答案相同；相交就是竞争，顺序执行只给出一种合法答案，
竞争检测不做（§6）。

`with_gpu_interp(progs, body)` 是给「launch 时才知道网格」的调用方的：一个转发型 `Gpu` handler，
`gpu_launch` 用 launch 自己的网格解释，其余五个操作原样转给外层的 `with_gpu_fake`（spec §6
「臂身体里发本效果，绑定到外层同效果 handler」）。CI 对拍就是靠它把 tile-gpu-diff 的
`with_gpu_real` 换成解释器的。

### 2.2 值

| 值 | 表示 |
|---|---|
| 浮点 tile | `List[Float]`，行主序；子集 A 只有 f64 |
| 整数 tile | `List[Int]`，每个 lane 按位宽回绕到有符号范围（`i1` 是 0/1） |
| 指针 tile | 每 lane 一对（缓冲区序号，元素偏移）；`offset` 加元素偏移 |
| token | 无内容；顺序解释里 `make_token`、`join_tokens` 是空操作 |
| tensor view | 缓冲区、基偏移、形状、步长（动态维取操作数） |
| partition view | tensor view 加 `tile_shape`、`dim_map`、`padding` |

值按 `lower` 重编的连续编号存进 `Map[Int, Val]`；区域内定义只在区域内被引用（`lower.dawn`
保证），所以不需要作用域分析。

内存是每个缓冲区一块 `std/mem` 的 `F64Buf`（`with_mem` 内，整体仍是纯函数）。整数缓冲区以
`Float` 进出，这是假设备的约定（`WideRefFn` 的类型），i64 超过 2^53 已由假设备在 launch 前拒绝
（`gpu.fake_inexact`）。返回值是**写过**的缓冲区位置与内容，与 `WideRefFn` 的约定一致。

### 2.3 view、mask 与 padding

- partition view 的 tile 维 `k` 对应 tensor 维 `dim_map[k]`：下标为 `idx` 的 tile 中坐标为 `c`
  的元素，其 tensor 坐标 `t[dim_map[k]] = idx[k] * tile_shape[k] + c[k]`，地址是
  `base + Σ t[d] * strides[d]`。`get_index_space_shape` 答 `ceil(shape[dim_map[k]] / tile_shape[k])`
  （设计 §6 T12 节）。
- 越界读：view 有 padding 时答 padding 值（五种）；`NoPadding` 时是「不指定值」，解释器把这些
  lane 记为未定义（§2.4）。越界写由方言屏蔽，解释器跳过（设计 3273 行）。
- `load_ptr_tko` 带 mask：mask 关掉的 lane 不访问内存，有 pad 时答 pad，无 pad 时答不指定值，
  同样记为未定义。`store_ptr_tko` 的关掉的 lane 不写。

### 2.4 UB 检查（默认开）

解释器是测试工具，所以设备不查的未定义行为它查，查到就拒绝这次 launch（`interp.ub`，带指令名
与位置）。Pallas 的 `InterpretParams` 是同一种设计（`out_of_bounds_reads` 默认报错、
`uninitialized_memory` 填毒值）。

1. **越界访问**：指针载入/存储的活 lane、view 的界内元素落在缓冲区外；`inbounds` 承诺被违反；
   `extract`/`insert` 的下标越界。
2. **读未定义值**：上面两种「不指定值」的 lane 带一个未定义标记，逐元素运算、选择、形状运算、
   归约与扫描都传播它；它一旦被**存进内存**，或被用作控制流条件、循环界、view 下标，就是 UB。
   只是算出来又丢掉不算（设备上那也无害）。
3. **假 `assume`**：`div_by`、`same_elements`、`bounded` 三种谓词按定义检查（方言说假谓词是 UB）。
   指针上的 `div_by` 按「缓冲区基址对齐到 256 字节」的模型检查。
4. **整数除零**、**移位量超出位宽**、**溢出假设（`nsw`/`nuw`/`nw`）被违反**、**非饱和 `ftoi` 的 NaN
   与越界**、`loop`/`for` 超过步数上限（防死循环，2^24 步）。

`interp_ref(prog, grid, ub_checks: false)` 关掉 1 到 3 中的「拒绝」，未定义 lane 填 NaN（浮点）或
0（整数）继续算。默认开。

### 2.5 浮点

- 加减乘除、比较、`maxf`/`minf`（含 `propagate_nan` 两路与 ±0）、`remf`、`ceil`/`floor`、`negf`/`absf`、
  `fpowi`（设计 T16 节量出的「右到左二进制幂，负指数取倒数」）在 f64 上**逐位**。
- 定向舍入（`addf_neg_inf` 等）用 TwoSum / Dekker 乘积求出精确误差再向一侧挪一个 ulp；`divf`
  用 Dekker 乘积求余数的符号。`flush_to_zero` 把次正规输入与结果冲成同号零。
- `sqrt` 正确舍入：牛顿迭代后用 Dekker 乘积判定 ±1 ulp。`sqrt_approx` 走同一个函数（设备差 1 ulp，
  容差档）。
- 超越函数（`exp exp2 log log2 rsqrt tanh fpowf sin cos tan sinh cosh atan2`）**不复用 tileref**
  （裁决第 4 条），本包只用宿主的加减乘除另写一套，走与 tileref 不同的路：`exp` 先除以 2^10、
  Taylor 求和、再平方十次（tileref 是按 `k·ln2` 约化）；`log` 在这个 `exp` 上做 Halley 迭代
  （tileref 是 atanh 级数）；三角用三段 π/2 的 Cody–Waite 约化；`atan` 两次半角化简再级数。
  相对误差约 1e-13，只承诺容差档（`atol = rtol = 1e-5`，设计 §6.6），与设备、与 tileref 都是
  不同的意见。小整数次幂的 `fpowf` 走二进制幂，其余 `exp(y·log x)`。
- 归约与扫描按**左折叠**（与 tileref 的 `sum_ref` 同序）。设备的折叠树不指定（§6.6 第 2 条），
  逐位档 kernel 的语料本来就让折叠顺序不可见。

### 2.6 拒绝

未实现的指令在解释开始前整体检查一遍，第一条不支持的指令让整次 launch 失败，`interp.unsupported_op`，
报文带指令名与原因（例如 `mmaf (matrix product, I2)`、`addf on bf16 (narrow formats are I2)`）。
解释过程中不再有第二个 `unsupported_op` 来源，所以「静态说支持」与「运行时没拒绝」是同一个判断。
`WideRefFn` 没有错误通道，`interp_ref` 以 `panic("interp.unsupported_op: ...")` 失败；
`with_gpu_interp` 把它变成 launch 的 `Err(kind: "interp.unsupported_op")`。

## 3. 对拍与判词

**方法**：`scripts/tileinterp-diff/run.sh` 把 tile-gpu-diff 的家族程序原样拷进一个工程，只做三处
文本替换：`with_gpu_real(` 换成 `interp_gpu_real(`（解释器设备），`args()` 换成定长的占位路径，
`pub fn main` 换名成可被统一入口调用。语料、tileref 参考、逐位/容差判词、每个 case 的
`  verdict` 行一字不动，所以「解释器 vs tileref」用的就是「设备 vs tileref」那把尺子：
逐位档逐位，容差档 `atol = rtol = 1e-5`，`flash_bf16` 沿用 `tolerance_of`。
`scripts/tile-golden/kernels.dawn` 作为模块编进去，按名字 `trace` 出每个 kernel 的 `TileProg`。

**判词**：每个家族的每个 `  verdict` 行必须是同意（`identical*`、`close:tolerance`）或
`blocked:interp.unsupported_op@launch`；`differ:*` 与其它任何 `blocked:*`（含 `interp.ub`）都红。
一个 kernel 算「覆盖」，当且仅当它在某个同意的 case 里被解释器跑过。覆盖集合钉在
`scripts/tileinterp-diff/covered.txt`，跑出来的集合与它不等就红（多了要登记，少了是回退）。

**为什么不是新写语料**：tile-gpu-diff 二十多个家族、一万多行，每个 case 的语料都是为「让折叠顺序
不可见」「让 mask 的尾巴被看见」专门设计过的。另写一份既重复又会漂。

**先例**：Triton `TRITON_INTERPRET=1`（numpy 逐操作、program 顺序执行、barrier 空操作；
<https://triton-lang.org/main/programming-guide/chapter-3/debugging.html>，
<https://github.com/triton-lang/triton/blob/main/python/triton/runtime/interpreter.py>）；
JAX Pallas TPU interpret mode（`detect_races`、`out_of_bounds_reads`、`uninitialized_memory`、
网格顺序随机化；<https://docs.jax.dev/en/latest/_autosummary/jax.experimental.pallas.tpu.InterpretParams.html>）；
tinygrad `DEV=PYTHON`（<https://github.com/tinygrad/tinygrad/blob/master/tinygrad/runtime/ops_python.py>）。
cuTile Python 与 cutile-rs 都没有解释器。

## 4. 改写 tile-backend-design

- §1 非目标第 5 行「CPU 解释器、Tile IR 模拟器」**推翻**：改成「在设备上之外再造一个权威」，
  解释器是第三个意见，不是 oracle。
- D4 的含义改写为：**CI 到层 1 加解释器路径，设备执行仍只在台账机器上，设备是唯一权威**。
  墙三「CI 只到层 1」那半句同步改。

## 5. 实测

2026-10-20，本机（WSL2，16 核），基线 origin/main `f2bf502a`。

**覆盖：208 个 golden 里 106 个**（`scripts/tileinterp-diff/covered.txt`），全部在逐位档或容差档上
与 tileref 同意，**零个 `differ`**。183 个 case 里 119 个同意、64 个被拒（`interp.unsupported_op`
61、预期 UB 2、i64 超 2^53 的 `gpu.fake_inexact` 1）。

**目标 127 的更正**：调研的 127 来自 `scan_golden.py`，它用 `\b(f32|...)\b` 判窄格式，而
`tile<128xf32>` 里 `x` 与 `f` 都是单词字符，`\b` 不成立，于是 7 个用了 f32 的 kernel（`attr_round`、
`attr_ftz`、`attr_ftof`、`attr_approx`、`int_ops`、`dtype_e2m1`、`dtype_e5m3`）漏进了子集 A。改正正则后
「f64 与整数」的子集是 **120**。这 120 个的去向：

| 去向 | 数 | kernel |
|---|---|---|
| 覆盖 | 106 | covered.txt |
| 语料故意踩 UB，默认检查拒绝 | 2 | `attr_overflow`（`subi` 带 `no_unsigned_wrap` 却回绕）、`attr_sat`（非饱和 `ftoi` 的 NaN），登记在 `expected-ub.txt` |
| 没有层 2 程序（没有 tileref 参考） | 6 | `carry_extent`、`idx_softmax`、`sum`、`vadd_debug`、`vadd_producer`、`foldif_debug`（后三个与已覆盖的 `vadd`/`foldif` 同程序） |
| 只出现在含 mma 步骤的序列里（序列在 mma 处被拒，后面的步骤没跑或不计） | 6 | `gpt_ln`、`gpt_gelu`、`llama_rms`、`llama_rope`、`swiglu_act`、`attn_bwd_ds` |

即子集 A 里**每一个有 tileref 参考、能单独比较的 kernel 都覆盖了**。全部 208 个的去向：覆盖 106；
预期 UB 2；被拒的 51 个里 mma 19、窄格式 16、`fma` 6（这三类是 I2），原子 4、`alloca` 2、全局 2、
指针转换 2、strided/gather 2、`assert` 1、栅栏 1（不排）；跑过但只在被别的步骤拦下的序列里 12；
解释器没被叫到 33（序列在前一个 mma 步骤处已停的后续步骤，没有层 2 程序的 6 个，以及没构建的家族：
原子、符号查询、fp8/fp4 架构族、单独进程的 `assert_fail`/`print_tile`）。

**墙钟**（`scripts/tileinterp-diff/run.sh`）：`dawn build` 一次 4 到 5 s，24 个家族各一个 JVM 共 15 s，
合计约 20 s。CI 挂在 tile.yml 的 `tile-golden-11`（声明最低的一片），按慢 runner 两倍加一成记 45 s，
声明 765 s → 810 s，path-total 9435 s → 9480 s（`Gate-Budget(path-total)`）。包自己的测试走
gates.yml 现有的 `package-tests.sh`（自动发现，3 s）。

**负控**（`run.sh --selftest`，`scripts/tileinterp-diff/mutate.py` 三个变异体，本机 75 s，不进 CI）：

| 变异体 | 必须红的 | 实测 |
|---|---|---|
| `mulf-adds`：`mulf` 算成加法 | 对拍 | 红，36 条，第一条 `mask: differ:result`（leaky_relu） |
| `bounds-unchecked`：越界检查关掉 | 包测试「store past the end」 | 红 |
| `unsupported-skipped`：`mmaf` 过静态检查、执行时静默跳过 | 包测试「refused by name」与对拍 | 都红（`matmul` 落到 `interp.internal`） |

`mulf-adds` 还量出一件事：`loop_until` 的退出条件依赖乘积，变异后循环不再退出，解释器的 2^24 步上限
要几分钟才到，所以 run.sh 给每个家族一个墙钟上限（默认 120 s，自测 30 s），超时写一条任何判词都不收的
`verdict timeout`。

**tileir 公开面**：零改动（§1）。tileinterp 对 `Instr` 的静态检查（`op_problem`）逐个列出 60 个变体、
不用通配，删掉一行就编不过（实测 `non-exhaustive match, missing: Ret`），新 opcode 必须先在这里表态。

## 6. 不做的（理由）

- **原子（`atomic_rmw_tko`、`atomic_cas_tko`、`atomic_red_view_tko`）**：顺序执行下原子就是普通
  读改写，只给出一种合法调度。整数可交换模式的最终内存与调度无关，但 `atomic_rmw` 返回的旧值与
  CAS 的成败依赖调度；做出来容易让用户误以为测过并发（裁决第 1 条）。
- **栅栏与 PDL（`memory_fence_alias_tko`、`gdc_*`）**：实现是空操作，一行；难在无法验证，解释器
  没有并发，也没有跨 launch 的 PDL。空操作的绿没有信息量。
- **竞争检测与网格顺序随机化**：Pallas 有，但它与原子是同一类问题（并发语义），随 C 档一起不排。
  块间写不相交今天由记录期的 `d_fork2` 检查与 `Out` 格子承担。
- **C 档其余**（strided / gather view、`int_to_ptr` 一族、全局、`alloca`、`assert`/`print`）：裁决
  不排 C。它们在本刀明确拒绝（`interp.unsupported_op`），不静默跳过。
- **mma 与窄格式**：I2。
