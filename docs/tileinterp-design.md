# tileinterp：Tile IR 宿主解释器

> 状态：**current** —— 2026-10-20 裁决（`ruling-tileir-interp-20261020`）的 I1 与 I2。
> 新包 `packages/tileinterp` 解释 `packages/tileir` 降级后的 `lower.Kernel`。
> I1 是子集 A（f64 与整数，§1 到 §6）；I2（§7）加 `fma`、矩阵乘（`mmaf`、`mmaf_scaled`、`mmai`）
> 与 `std/narrow` 的窄格式，flash_attn 与 flash_attn_bf16 在覆盖内，Playground 的 flash_attn 样例真跑。
> 下文 §1 到 §6 写的是 I1 时的状态；与 §7 冲突处以 §7 为准（§2.2 的值表、§2.6 的拒绝名单、§5 的覆盖数、§6 末条）。

当前 FlashAttention 读者入口统一为 BF16 输入、F32 状态/scale/输出，见
[读者面设计](flash-attn-bf16-front-design.md)与[实际样例](../site/play-ui/samples/flash_attn.dawn)。
本文原有 f64 展示、调用计数、编译时延及测量说明属于所记实施阶段，不能作为
当前展示或性能声明；泛型算法、数值 helper、host plan 与内部 f64 回归能力保留。

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
4. **整数除零**、**溢出假设（`nsw`/`nuw`/`nw`）被违反**、**非饱和 `ftoi` 的 NaN
   与越界**、`loop`/`for` 超过步数上限（防死循环，2^24 步）。

`interp_ref(prog, grid, ub_checks = false)` 关掉 1 到 3 中的「拒绝」，未定义 lane 填 NaN（浮点）或
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
`with_gpu_interp` 把它变成 launch 的 `Err(kind = "interp.unsupported_op")`。

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
- **mma 与窄格式**：I2 已做，见 §7。

## 7. I2：fma、矩阵乘与窄格式

2026-10-20，本机，基线 origin/main `93b09760` 加修复 PR #810（`build.py` 把 vadd 家族的 cubin 个数写死成 2，
#808 加 vadd_f32 后成了 3，tile-golden-11 的解释器一步没有判词行；现在个数取自驱动自己的 usage 行）。

### 7.1 矩阵乘的累加顺序与精度

**事实先行**：`mmaf` 只承诺乘积，不承诺沿 k 的和怎么分组、怎么舍入；sm_86 上 f64 的 `mmaf` 根本不走张量核，
`tileiras --remarks=tensorcore` 报 `Instruction = FMA`（tileref 的 matmul 一节写过）。张量核上的和也不是 IEEE 序列：
一块乘积按最大指数对齐，丢掉的低位截断，不在步间规范化（Fasi 等，"Numerical behavior of NVIDIA tensor cores"，
PeerJ Computer Science 2021，<https://peerj.com/articles/cs-330/>）。所以解释器的累加顺序**是一个模型，不是对设备的测量**，
和 tileref、和真机的比对因此**永远是容差档**（tile-backend-design 6.5）。

模型（`packages/tileinterp/src/mma.dawn` 头注释同文）：

| 累加器 | 做法 | 理由 |
|---|---|---|
| f64（操作数 f64） | 从累加器操作数出发，k 升序，每步一次 `fma`（单次舍入） | 设备在 sm_86 上就是 FMA 指令；fused 比 tileref 的「先乘后加」少一次舍入，是更接近设备的读法 |
| 更窄（f32、f16） | 操作数乘积在 binary64 里精确（操作数至多 24 位有效数），在 binary64 里求和，**最后一次**舍入进累加器格式 | 逐步舍入进 f32 会多出 k 次没有任何文档支持的舍入；张量核的内部误差与 binary64 同量级，远小于 f32 |
| `mmaf_scaled` | 因子 `(a * sa) * (b * sb)` 全部精确（尺度是 2 的幂），宽累加，最后舍入进 f32 | 同上；公式是 Ops.td 的 `MmaFScaledOp` |
| `mmai` | i8 乘积在 i32 上回绕求和 | 整数加法对 2^32 取模满足结合律，顺序不是模型，是精确的 |

**逐位一致与否**（实测，`run.sh` 的 `miss` 列是误差占容差的比例）：

- 与 tileref：`matmul` 等整数值语料（每个乘积和部分和都是整数，f64 上精确）**逐位**一致；`batched_matmul` 的 `miss` 为 8.0e-11
  （最后一位的差：解释器 fused，tileref 乘后加）；`layer_norm` 3.1e-11、`group_norm` 3.3e-11、`attn_*` 序列 2e-9 量级。
- 与真机：流程相同、判词相同（设备也只在容差档比）。真机侧的数是台账上的，不在本刀重录（§7.6）。
  flash_bf16 在 `tolerance_of` 里有自己的 `atol = 2^-16 * max|v|`（seq_diff.dawn 的推导：设备对 tileref 实测约 1.8e-8 绝对、
  约占界的 1e-3）。解释器对 tileref 实测 `miss = 1.2e-3`（占同一个界），**与设备同一个量级**；那条「忘了把 p 收窄到 bf16」的
  对照在解释器上同样红（`miss = 28.5`）。
- **容差的出处**：`atol = rtol = 1e-5` 是 leetgpu 的判分容差（tile-backend-design 6.6），flash_bf16 的 `2^-16 * max|v|` 是上面那段推导。
  解释器没有自己的容差，用的就是量设备的那把尺子。

### 7.2 窄格式在解释器里的表示与舍入时机

- **表示**：窄格式的一个 lane 是**一个落在该格式网格上的 Float**（`std/narrow` 自己的不变量）。f32、tf32、bf16、f16、f8E5M2、
  f8E4M3FN、f4E2M1FN、f8E8M0FNU 全部如此；位型只在 `bitcast`、`pack`、`unpack` 要它时才出现。
- **舍入只走 `std/narrow`**：`formats.round_into(格式, 方向, x)` 逐格式转给 `round_f32 / round_tf32 / round_binary / round_f8e5m2 /
  round_f8e4m3fn / round_f4e2m1 / round_f8e8m0`，**没有第二份实现**，所以解释器与 `std/narrow` 对「一个格式的值是什么」不会有分歧。
- **时机**：每一个产出该格式 lane 的运算，结果立刻舍入进格式——`addf subf mulf divf sqrt`、`maxf` 之外的一元与二元运算、`fma`、
  `ConstFloat`、`itof`、`ftof`、`fpowi` 的每一步乘法。读入口也舍一次（缓冲区里本来就在网格上，是空操作，挡住游离的 off-grid Float）。
  加减乘除与平方根「在 binary64 里算再舍入」是正确舍入（Figueroa 双舍入定理，std/narrow 头注释：宽格式至少 2p+2 位，最宽的 f32 要 50，binary64 有 53）。
  超越函数没有这个保证，是「binary64 里算再舍入」的**定义**，在容差档。
- **定向舍入**（`addf_neg_inf` 等）与 `flush_to_zero`：定向的用 `math.add_dir / mul_dir / div_dir` 给出精确结果在 binary64 里的上下两个邻居，
  再各自按方向舍入进格式（格式网格是 binary64 网格的子集，所以 floor 的 floor 还是 floor）；`flush` 在格式自己的最小正规数处冲（f32、tf32、bf16 是 2^-126，f16 是 2^-14）。
- **转换**：`ftof` 的五种舍入由 `prog.ftof_mode` 给出（和 lowering 写进文本的是同一个函数），`f8E8M0FNU` 的 `positive_inf` 没有实测，**拒绝**；
  `itof` 到窄格式：超过 2^53 的整数先舍进 binary64 再舍进窄格式会舍两次，所以走 round-to-odd。
- **`bitcast` 保 NaN 载荷**：`std/narrow` 的位型函数对 NaN 答规范 NaN，而设备的 `bitcast` 不动位型。`int_ops` 的语料里有 NaN 型的 i32，
  先实测为 4/1024 个 lane 不同；`formats.to_bits / of_bits` 对 f32、tf32、bf16、f16 的 NaN 用 binary64 NaN 的高位带载荷，往返恒等。
  填充值 `PadNan` 是正的静默 NaN（`0x7FF8...`，设备写出 `0x7FC00000`），不是宿主 `0.0/0.0` 带的符号。
- **同宽重解释**：kernel 可以把缓冲区读成同宽的另一种格式（`view_padding` 是 f32 的 kernel 读 i32 缓冲区），lane 就是位型，
  过 `formats` 的编解码；宽度不同仍是 `interp.bad_launch`。
- **f8E5M3FNU 拒绝**：`std/narrow` 没有它的舍入函数，也没有宿主值，边缘行为没人测过（std/narrow 的声明处自己这么说）。
  含它的 kernel（`dtype_e5m3`、`mmaf_scaled_e5m3`）整个拒绝，`interp.unsupported_op`，带原因。

### 7.3 fma 是单次舍入

- **binary64**：std/math K5 后直接调用 `std/math.fma`，全部有限指数范围均为单次舍入；不再有旧的极端指数两次舍入兜底。
  包内测试保留乘积相消，并新增中间乘积溢出后有限相消、次正规中点；窄格式继续走下述 round-to-odd。
- **窄格式**：操作数至多 24 位，乘积在 binary64 里精确；`c` 用 round-to-odd 加上，再舍进格式；对至多 51 位有效数的目标格式，
  先 round-to-odd 再舍入等于对精确值舍入一次。测试：f32 的 `(1+2^-12)^2 - (1+2^-11)` 是 `2^-24`，先舍乘积会得 0。

### 7.4 覆盖（更正计数之后）

调研与 I1 的 127/185 来自 `scan_golden.py` 的正则 bug（`\b` 在 `128xf32` 里不成立）。新的计数脚本是
`scripts/tileinterp-diff/scan.py`：按 `tile<..>` 与 `ptr<..>` 的角括号和 `x` 分隔读元素类型，按指令名认「按构造拒绝」的算子，
自带一个钉住旧 bug 的自测。208 个 golden 的账：

| 去向 | 数 |
|---|---|
| 按构造拒绝（原子 7，栅栏与 PDL 1，alloca 2，全局 4，指针转换 2，assert 2，print 1，只靠 strided 视图 2，gather 视图 2，f8E5M3FNU 2；`view_atomic*` 同时算原子） | 25 |
| 上限（其余） | **183** |
| 　其中实际覆盖（某个同意的 case 里解释器跑过） | **175**（I1 是 106） |
| 　其中语料故意踩 UB（`attr_overflow`、`attr_sat`） | 2 |
| 　其中没有层 2 程序（`carry_extent idx_softmax sum vadd_debug vadd_producer foldif_debug`，没有 tileref 参考） | 6 |

裁决写的 185 是调研的数；用更正后的脚本这个上限是 183。**flash_attn 与 flash_attn_bf16 在覆盖内**，对 tileref 的判词都是 `close:tolerance`。
**`differ` 为 0。** 新进来的 69 个：矩阵乘与注意力一族（`mmaf`）、f32 的 `attr_*`、`vadd_bf16`、`vadd_f32`、`dtype_tf32`、`f16_ops`、
fma 的 6 个，以及架构门控的 `dtype_e4m3 dtype_e5m2 dtype_e8m0 dtype_e2m1 mmaf_scaled_e4m3`：这五个设备要 sm_89 以上才有 cubin，
解释器没有「卡」可挑，所以 `build.py` 把 `arch_diff` 家族也编进来（占位参数改成 `<kernel> <cubin>` 对）。

**按容差比对的 kernel（67 个只在容差档上同意，逐个列在 `run.sh` 的 `tolerance-tier only` 行）及理由**（31+5+14+3+2+12 = 67）：

| 理由 | 数 | kernel |
|---|---|---|
| 含矩阵乘，累加顺序是模型（7.1） | 31 | `attn_alibi attn_bwd_mmt attn_causal attn_context attn_scores attn_sinks attn_window batched_matmul gpt_context gpt_dense gpt_down gpt_fc gpt_qkv gpt_scores gqa_context gqa_scores llama_down llama_ffn llama_out llama_qkv llama_scores lora_base lora_hidden lora_out matpow_step mha_context mha_scores swiglu_down swiglu_proj xattn_context xattn_scores` |
| 含矩阵乘，且含超越函数 | 5 | `attn_decay flash_attn flash_attn_bf16 lin_attn_out lin_attn_s` |
| 含超越函数（`exp log tanh sin cos rsqrt` 等）：不复用 tileref，两边各算各的，只承诺容差 | 14 | `attn_softmax cce_row dpo_loss gpt_gelu grpo_row llama_rms mathops ppo_loss sigmoid silu softmax swiglu_act swiglu_half trig_sweep` |
| 含超越函数与 `fma`（`fma` 本身是单次舍入，但后面接超越函数） | 3 | `erf_sweep geglu ssm_scan` |
| 含 `fma`，递推链上的最后一位随两侧公式写法而变 | 2 | `gae linrec` |
| 语料声明的档就是容差：设备的归约树顺序不指定，解释器与 tileref 都左折叠，差是 kernel 与参考公式写法不同带来的最后几位（`miss` 不超过 3.3e-11，多数是 0） | 12 | `attn_bwd_ds batch_norm cce_mean fused_rms_norm gpt_ln group_norm grpo_adv kv_context kv_scores layer_norm llama_rope seg_scan` |

`erf_sweep` 的 `miss = 1.2e-2` 与 `geglu` 的 `3.6e-2` 是这个表里最大的两个，来自 kernel 自己的有理逼近对 tileref 精确 `erf` 的差，
设备上同样存在（erf_diff 的头注释），不是解释器的差；其余全部小于 6e-8。

### 7.5 Playground：flash_attn 真跑

样例 `site/play-ui/samples/flash_attn.dawn` 变成「记录 → `interp_ref` 在宿主上解释执行 → 与朴素 attention 比对 → 打印」：输出前两个 query 行的前四个值，
和一行「与朴素 attention 在 1e-12 内一致：true」。kernel 与 `const` 行仍与 `scripts/tile-golden/kernels.dawn` 逐字相同（doc-check 的 `PINNED_SAMPLES`
不再要求 `.out` 等于 golden，因为它不再打印 Tile IR 文本；Tile IR 窗格的文本来自 probe 的记录，与样例输出无关）。runner 的项目清单加第三个依赖
`tileinterp`（`tile_manifest`、`tile_ready`、lsp-tile、合约测试同步）。**部署随下次发版**：站点与 runner 同提交（记忆里的老教训）。

**runner 沙箱语义下的耗时**（`dawn build` 编项目，再 `java -Xmx256m -jar`，与 `exec.dawn` 的 `RUN_HEAP` 一致；本机 WSL2，未套 bwrap）：
构建 2.6 s（编译预算 30 s），运行 0.25 到 0.26 s 三次（运行预算 10 s）。远在预算内，不动超时。

### 7.6 负控、墙钟、台账

- 负控（`run.sh --selftest`，本机约 3 分钟，不进 CI）：`mma-drops-term`（f64 乘积漏最后一项）→ 包测试「a matrix product adds every term of k」与对拍双红；
  `narrow-unrounded`（窄格式结果不舍入）→ 包测试「a narrow sum is rounded into its format」与对拍双红（第一条是 `f16_ops`）；
  `fma-two-roundings`（先舍乘积再加，binary64 与窄格式两处）→ 包测试「fma rounds once, in f64 and in f32」红。fma 的对拍不红：
  语料里 fma 的 kernel 全在容差档，两次舍入的差落在容差之内，所以它的负控落在包测试上，这是原因，不是遗漏。
  原有的三个仍红；`unsupported-skipped` 的靶子从 `mmaf`（现在支持）换成栅栏。
- CI 墙钟：本机实测 `run.sh` 由 I1 的约 20 s（构建 5 s，24 个家族 15 s）升到约 42 s（构建 5 s，25 个家族 37 s；多出的是矩阵乘、窄格式与架构门控家族）。
  按 I1 同一条规则（慢 runner 两倍加一成）计 95 s，tile-golden-11 的声明 810 s → 860 s，`path-total` 9480 s → 9530 s，timeout 41 → 43 min，
  提交信息带 `Gate-Budget(path-total)`。仍挂在同一片，不新开片；声明后 shard 11 为 860 s，低于 950 s 的极点。
- 台账：`packages/tileir` 与 `std` 本刀**零改动**（`git diff origin/main -- packages/tileir std` 为空），层 2 输入摘要不动，
  sm_86、sm_90、sm_100 三本台账**不重录**（同 I1）。

### 7.7 不做的（理由）

- **原子、栅栏、PDL、竞争检测、网格顺序随机化**（裁决第 1 条的 C）：顺序执行只给出一种合法调度，做出来容易让用户误以为测过并发。仍然 `interp.unsupported_op`。
- **alloca、全局量、指针转换、strided 与 gather 视图、assert、print_tko**：同属 C 档，裁决不排。
- **f8E5M3FNU**：`std/narrow` 没有舍入函数也没有宿主值，边缘行为未实测；在这个库补它之前解释器不替它猜。`ftof_pos_inf` 到 `f8E8M0FNU` 同理。
- **模拟张量核的内部对齐与截断**：Fasi 等量出了 V100/A100/H100 各自的行为，但那是各代各型号的细节，且 `mmaf` 不承诺它；模型选「宽累加一次舍入」，
  在容差档上与设备同量级（7.1），再往细里做是把一个型号的实现当成语义。
- **另造宿主数学实现**：std/math K5 已替换旧的宿主算法；GPU 的 FTZ、定向舍入与窄格式适配仍在包内，tileref 保留独立级数。
- **把 fma 的对拍做成逐位**：语料里的 fma kernel 都含超越函数或扫描，本来就是容差档；逐位要新写语料，那是 tile-gpu-diff 的事，不在解释器这刀。
- **把远端架构台账冒充本机结果**：本机只重验自身设备，sm_90/sm_100 既有记录不改写；std/math K5 的本机重验另见其交付记录。


## 按位刀 4 的移位语义

整数 shli、shri、shru 先按 lane 位宽取 k = n & (w−1)，负计数同样取二补码低位。
删除 shift_ub 路径；开启与关闭 UB 检查都使用相同计数语义。设备表面另显式发 andi，
解释器的规范化不能替代对设备记录的结构检查及漏掩码数值负控。四宽度边界族
比较 tileref，额外 typed i64 仍受现有 Float 存储精度拒绝约束，不扩大解释器精度承诺。
