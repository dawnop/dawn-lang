# Tile 后端：宿主效果、假设备与分阶段路线

> 状态：**current**。立项计划由用户于 2026-09-02 裁决（§2 的 D1 至 D4 四条均按推荐），
> 本文是那份计划稿的正式版，自此是 tile 后端这条线的权威说明。基线 dawn-lang `6396f017`
> （0.71.0 发布之后、种子已推进到 v0.71.0）；文中 file:line 对 `aca84fb9`（0.71.0），
> 两者之间只有种子推进，源码未动。
> **刀 1 已落地**（`std/gpu.dawn`：`Gpu` 效果、`Dtype`、`Tensor[D]`、`with_gpu_fake`），
> 落地形状以源码为准，§4 描述的就是它。**刀 2 已落地**（`packages/tileir`：`Dev` 效果、
> `Tile[D] / Param[D] / Idx`、`TileProg`、记录 handler、文本渲染器，`scripts/tile-golden`），
> §5.1 描述的就是它。**刀 3 已落地**（`packages/tileir` 的 `lower`（两个消费者共用的指令表）与
> `bytecode`（字节码写入器），`scripts/tile-golden` 加字节码 golden 与 `tileiras` 层 1，
> CI 新 job `tile`），§5.3 与 §6 描述的就是它。**刀 5 已落地**（`packages/tileir` 的
> 索引算术与 `d_for` / `d_for2`、记录 handler 的区域栈、`For` 的降低 / 渲染 / 编码，
> 第二个 kernel `sum` 与 `std/gpu.sum_ref`），§5.2 描述的就是它。**刀 4 的管线已落地**（`RtGpu`
> 八个 intrinsic、原生运行时的 `dlopen libcuda`、JVM 拒绝类、`with_gpu_real`、`scripts/tile-gpu-diff`
> 的对拍脚本与台账、CI 台账门），§4.2、§4.4 与 §6.4 描述的就是它；**GPU 对拍本身待驱动**：本机
> 560.94 上管线走到 `cuModuleLoadData` 被 `CUDA_ERROR_INVALID_IMAGE` 拦住，台账第一行记的就是这一步
> （§6.4）。**刀 0 已落地**（`std/narrow`：三个 opaque 格式、`round_binary`、`Narrow` trait，
> `scripts/narrow-contract` 的精确 oracle），§3.2 描述的就是它。**刀 6 已落地**（`gpu.BF16`
> 标记与 `Tensor[BF16]`、`std/narrow` 的 bf16 位模式编解码、宿主侧 `Bytes` 打包与两个 `Bytes`
> 版 intrinsic、假设备按缓冲格式舍入并把格式交给参考实现、`vadd_bf16` 的层 0 / 1 golden 与
> cubin、对拍脚本的三组 bf16 语料），§3.2、§3.3、§4.3、§4.4 与 §6.4 描述的就是它；**六刀全部
> 落地，层 2 待驱动**：bf16 的设备对拍与 f64 的一样停在 `cuModuleLoadData`（§6.4）。
> **刀 7a / 7b / 8 已落地，层 2 已通**（驱动升到 616.56 之后）：7a 是边界与逐元素算术，
> 7b 是归约、超越函数与两档判词，**8 是二维 tile、任意 stride 的指针梯子、`mmaf` 与三维
> grid**；三刀合起来 30 个 kernel 全部在本机 3080 上与手写参考对上，leetgpu 累计 22 / 97
> （§7 的刀单，判词与负控见 §6.5、§6.6）。
> 前置勘察与计划稿是两份不入库的研究备忘录（agent-handoff 的
> `cutile-backend-fit.md` 与 `tile-backend-plan.md`），探索过程留在那里，
> 本文只保留结论与证据坐标。
> 代码块都不标 `dawn run` / `dawn compile`，`doc-check.py` 不编译它们；
> 已落地的部分以 `std/gpu.dawn` 及其 test 块为准。

## 1. 目标与非目标

**目标**：让一个 Dawn 程序在宿主侧描述一个 tile kernel，把它编成 CUDA Tile IR 字节码，
由 `tileiras` 编成 cubin，经 driver API 在 NVIDIA GPU 上启动；并且**同一段宿主程序在没有
GPU 的机器上用假设备跑完并给出相同答案**。后半句是让宿主逻辑能进 CI 的唯一办法。
第一里程碑是 f64 向量加法端到端；第二里程碑是 bf16 tile 与循环、条件。

**非目标**，每条都核实过「真的能不碰」：

| 不做 | 核实 |
|------|------|
| 通用 GPU 语言、SIMT、线程索引 | Tile IR 本身没有线程索引，无从做起 |
| 自动并行挖掘（把 `for` 变 tile 运算） | 分阶段路线下 kernel 体显式调用 tile 级操作，没有「从标量循环抬向量」这一步 |
| 改 checker 的类型规则 | `opaque`（spec.md §2.7）、trait（spec.md §3.5）、`effect` 与 `with handle`（spec.md §6.5）三件现成机制拼出全部类型面，草案与刀 1 均只用它们。唯一例外是门禁脚本 `scripts/opaque-twin/run.sh` 多一种标记（§3.4），那不是 checker |
| 动 Core、lowering、两个发射器 | 宿主侧新 intrinsic 只加表项与运行时函数（§4.4），发射器按契约不动（runtime-intrinsics-design.md §12.1）。`lower.dawn:1163` 的分组表要不要加组见 §4.4 |
| CPU 解释器、Tile IR 模拟器 | 假设备答的是 `launch` 这一整个操作（宿主侧参考实现），不模拟 Tile IR 语义；Tile IR 层的正确性只由本机对拍保证（D4） |
| f32 / bf16 进 `Ty` | D3 已裁：`std/narrow` 的 opaque 方案覆盖 + − × ÷ √ |
| 接 MLIR、在 CI 里构建 `cuda-tile` | §6.1；本机构建一次只作 round-trip 对拍工具 |
| 多设备、流、异步 | `Gpu` 效果 v1 同步；`gpu_sync` 存在只为把「launch 返回不等于算完」写进契约 |
| kernel 之间的函数调用 | Tile IR 无 call；分阶段路线下 Dawn 函数调用在记录时展开，天然内联。递归 helper 靠 handler 的深度计数拒绝（§5.2） |

## 2. 裁决

### 2.1 四条裁决项（用户 2026-09-02 裁决：全部按推荐）

| # | 问题 | 选项 | 推荐（即裁决） | 一句话理由 |
|---|------|------|---------------|-----------|
| D1 | 路线 | (a) 子集编译：Core 到 Tile IR 的发射器；(b) 分阶段：kernel 体是 `!Dev` 效果函数，记录 handler 在宿主运行期把一次执行变成 Tile 程序；(c) 混合：(b) 为主，第二里程碑再给同一个 kernel 体加编译期发射 | **(b)，(c) 记为期权而非承诺** | (b) 零编译器改动、零 Core 节点、零 checker 改动；「无 call 对字典传递」这堵墙留在宿主侧自然消失；草案已跑出 vadd 的 Tile IR 文本。代价是 kernel 内依赖 tile 值的控制流要走 `d_if` / `d_for` 而不是 Dawn 的 `if` / `for`（§5.2）。(a) 换来的只是 kernel 里能写原生 `if` / `for` / `+`，要付的是子集标注、第三份「机器的事」语义与那堵墙；(c) 的编译期发射器要等 (b) 稳定后才知道该吃什么形状 |
| D2 | 第一里程碑范围 | (i) vadd f64 端到端：trace、文本、字节码、`tileiras`、3080 上跑、与假设备对拍；(ii) 只到文本 golden；(iii) 直接含 bf16 | **(i)** | (ii) 的绿没有信息量；(iii) 把类型层与设备层两个未知量绑在一刀里。(i) 是「每一层都被下一层校验过一次」的最小闭环 |
| D3 | 窄浮点 opaque 进不进 std | (i) 现在进，独立模块 `std/narrow`，与 tile 解耦；(ii) 先只做 f64 tile，bf16 等第二里程碑；(iii) 不做 opaque，等 f32 进 `Ty` | **(i)，排在刀 1 之后、与 tile 并行**；tile 侧第一里程碑仍只用 f64 | 方案核实成立：`opaque type BF16 = Float` 过 checker，`round_binary` 纯 Dawn 实现对 174 个精确 oracle 用例（含溢出、次正规、tie）在 JVM 与 native 上逐位一致且 ASan 干净，opaque 换 alias 后测试照过（§3.2）。它有独立价值（CPU 上模拟量化），Emit-Change 面小。(iii) 是 5 到 10 人日的 checker 战役 |
| D4 | 本机 GPU 作为 oracle 的纪律 | (i) 本地里程碑门 + 台账文件，CI 检查台账不落后于 tile 相关改动；(ii) 自托管 runner；(iii) 只信层 0 与层 1 | **(i)** | (ii) 把本机 WSL2 暴露给公开仓库的 PR 触发面；(iii) 与「门禁的绿要有信息量」正面冲突。(i) 的机器强制点见 §6.4。前提：本机驱动 560.94 低于 cuTile 硬要求的 r580，先升 Windows 侧驱动；本机也还没装 `nvidia-cuda-tileiras` |

### 2.2 对三条设计前提的修正

维护者给了三条前提（窄浮点 opaque、张量幻影参数、倾向分阶段路线）。核实后三处要改：

1. **「每个运算 = f64 运算后 `round_bf16`」成立，但拼不成运算符。** Dawn 只有 `Index`
   可由用户实现，`+ - * /` 不是 trait（spec.md §3.5 预置的七个，spec.md:575），且 opaque
   在声明模块内也不许 `u + 1`（spec.md:385）。所以 bf16 是一族具名函数
   `narrow.add / mul / ...`，不是 `a + b`。语义结论不变，人体工学降一档（§3.2）。
2. **「opaque-twin 门禁成立」对 `BF16` 成立，对 `Tensor[D]` 幻影不成立。** 把
   `pub opaque type Tensor[D] = ...` 换成 `alias` 后 `D` 失去载体，`upload[D](t: Tensor[D])`
   一类签名处处「cannot infer type parameter(s) D」。这是 spec.md:397 五件事里的
   「统一判定」在起作用，合法；但 `run.sh` 只有 `twin-rejected`（双方都拒）与
   `twin-normalise` 两种标记，没有「alias 侧拒、opaque 侧过」。刀 1 给门禁加了第三种（§3.4）。
3. **层 1「CI 里跑 `tileiras` 编译检查」多一条前置。** `tileiras` 吃字节码不吃 MLIR 文本
   （README 流水线是 `cuda-tile-translate --mlir-to-cudatilebc` 再 `tileiras`），而
   `cuda-tile-translate` 不在任何 pip 包里，要从钉在特定 LLVM commit 上的源码构建。所以
   CI 的编译检查必须等自写字节码写入器（刀 3）落地才进得去；文本 golden（层 0）不受影响。
   刀序因此把字节码写入器提前到 GPU 运行时之前（§7）。`tileiras` 本身有 pip 包
   `nvidia-cuda-tileiras`（manylinux x86_64 wheel，37 MB），CI 可钉版本加 sha256 装（§6.1）。

### 2.3 草案里撞到的两个语言事实

- `effect`、`trait`、`type` 共一个命名空间（`passes.dawn:1158`）：`effect Tile` 与
  `opaque type Tile[D]` 撞名。名字因此一次定好：宿主效果叫 `Gpu`，类型叫 `Tensor[D]`，
  trait 叫 `Dtype`；`Tile` 与 `Dev` 留给 `packages/tileir`。
- handler 的状态格不能被 lambda 捕获（`checker.dawn:1978`）：臂里要先 `let s = store`
  再进 `list.map`。假设备与记录 handler 都会反复撞到，是人体工学坑不是设计坑。

### 2.4 目标改判：从「覆盖 leetgpu 题目」到「覆盖 Tile IR 的每一个特性」（用户 2026-09-05 裁决：六条全按推荐）

刀 0 到刀 20 的目标是把 leetgpu.com 的题目做完，今天 83 / 97（刀 21 在途，照常收尾）。2026-09-05 用户把目标换成
**覆盖 Tile IR 的每一个特性**。预研（本机私有笔记，不入库）从 `NVIDIA/cuda-tile@be0889cd`
的本地 checkout 逐条数出全量：公开操作码 **100** 条（0x00 到 0x75，中间两段冻结空号
0x19-0x24 与 0x34-0x39），本仓 `packages/tileir/src/bytecode.dawn` 的 `OP_` 表实现 **63** 条，
另有标量类型 15 种（本仓 7 种）、类型构造子 8 个（本仓 4 个）、属性标签 12 个（本仓 2 个）、
段 8 个（本仓 5 个）。

**先说最该先说的一句：两个目标几乎正交。** 预研排的那十五刀最多解锁 2 到 4 道题
（61 靠三角函数、81 靠 i4 与 `unpack`，39 / 78 补上一格但仍欠多 launch）；反过来，
剩下 14 题里 29 / 67（top-k）与 60（RNG）**永远不会**被特性覆盖解锁，Tile IR 的 100 条
操作码里没有任何选择、排序或随机机制。改目标不是换一个方向继续走，是换一条路。

六条裁决：

1. **「覆盖」的判据是层 2**，也就是本机 3080 上有第二意见。层 1（`tileiras` 接受）不够，
   因为「门的绿没有信息量」；层 3（有会红的变异体）对某些格子物理上不成立，所以做不到
   层 3 的**逐条具名豁免**，理由写进台账：`assume`（方言自己说错谓词是 UB）、
   `OptimizationHints`（提示不改答案）、Debug 与 Producer 段、`nsw` / `nuw` / `nw`
   （它们是编译器的假设不是运算）。
2. **view 族暂排除**：`make_tensor_view` / `get_tensor_shape` / `load_view_tko` /
   `store_view_tko` / `make_partition_view` / `get_index_space_shape` /
   `make_gather_scatter_view` / `make_strided_view` / `atomic_red_view_tko` 九条操作码、
   四个类型标签与 `PaddingValue` 五值枚举，连同 T11 到 T13 三刀一起挂起。它是与指针梯子
   并列的第二套取址方式，是全清单里最大的一块，等 T1 到 T10 做完再回头裁。
3. **`assert` 与 `print_tko` 的两种新判词形状要建**（「这次 launch 应当失败」与「这次
   launch 应当打印这些字节」），放在 T6 那一刀内部完成，不提前立项。
4. **Debug 段挂起**，等 CUDA 13.4 的 wheel 带上 `tileirdisasm` 能做文本对拍再做。今天
   写出来只能被「`tileiras` 仍然接受」验证，那是层 1。
5. **CI**：特性语料照常进 `scripts/tile-golden` 的分片，接受片数从四涨到五或六；每一刀的
   报告必须写「不分片跑一次」的墙钟数字与分片后各片的数字。
6. **立第二本账**：`scripts/tileir-features/features.txt` 逐操作码记「实现于哪一刀、覆盖到
   哪一层、豁免理由」，门禁 `scripts/tileir-features/check.py` 以 `bytecode.dawn` 的 `OP_`
   表为期望集合，缺行即红。`scripts/leetgpu-diff/problems.txt` 保留不动。

**两本账是两个承诺，不是一件事的两个视角。** `problems.txt` 说的是「这个后端解得了哪些
leetgpu 题」，`features.txt` 说的是「这个后端实现了 Tile IR 的哪些特性」；上面那句「几乎
正交」正是它们不能互相代替的原因。两个 `check.py` 形状相同（逐行解析、字段逐项查得到、
`--self-test` 带阳性对照），都在 CI 里跑：leetgpu 那本在 `tile-golden-1`，特性这本在
`tree-policy`（它只读文本文件，不要工具链）。台账的列义与三层门的读法写在
`features.txt` 的头注里，那儿是权威。

刀序（预研排的，机制最便宜的先，但把版本墙放在它解锁的那一批之前）：

| 刀 | 内容 | 新操作码 |
|----|------|---------|
| **T0** | 特性台账与门禁（本刀） | 0 |
| T1 | 三角与浮点取余：`sin` `cos` `tan` `sinh` `cosh` `atan2` `remf` | 7 |
| T2 | 形状与指针转换：`extract` `cat` `permute` `join_tokens` `get_num_tile_blocks` `int_to_ptr` `ptr_to_int` `ptr_to_ptr` | 8 |
| T3 | 其余标量类型：`i16` `i64` `tf32` `f8E4M3FN` `f8E5M2` `f8E8M0FNU` | 0 |
| T4 | 属性域的其余取值：三种舍入、三种溢出、`unordered`、内存序与内存范围、`flush_to_zero`、`propagate_nan`、`for` 的 `unsignedCmp`、`atomic_rmw` 的 `addf` | 0 |
| T5 | `loop` 与 `break`（唯一缺的区域形状：出口由区域内算出的条件决定） | 2 |
| T6 | `assert` `assume` `print_tko`，与它们的四个属性标签；两种新判词形状 | 3 |
| T7 | 静态全局：`global` `get_global`，与 Global 段（id 6） | 2 |
| T8 | 13.2 到 13.3 的版本墙，只做这一件事（它会让全部 `.tilebc` golden 进一次 diff） | 0 |
| T9 | 13.3 亚字节：`i4` `f4E2M1FN` 加 `pack` `unpack` | 2 |
| T10 | 13.3 其余：`alloca` `mmaf_scaled` | 2 |
| T15 | `OptimizationHints`（属性标签 11 加 Dictionary 10） | 0 |

T11 到 T13（view 族）按裁决 2 挂起，T14（Debug 段与 Producer 段）按裁决 4 挂起。
leetgpu 刀 21 照常收尾，之后不再派 leetgpu 刀，剩余题目只作副产品记录。

**版本墙（T8）比想象的便宜，这是预研独立复核过的一条。** 13.2 与 13.3 之间本仓写出去的
字节只有三处会变：文件头第 10 字节的 `BYTECODE_MINOR`、`exp` 0x17（13.3 起必须内联写
`rounding_mode`）与 `mmaf` 0x49（13.3 起要写一个 flags varint）。其余 98 个操作逐字节相同。
`bytecode.dawn` 那句「the bytecode this writes is the same at 13.1, 13.2 and 13.3」在今天
实现的 63 条里只有这两条是例外，而当年那次三版本对拍用的 vadd 一条都没碰上，所以升版时
那句注释要跟着改。


## 3. 类型层

### 3.1 opaque 机制的坐标

- `opaque type X = Float` 合法，spec.md:351 的示例正是 `pub opaque type Meters = Float`；
  语法与 `alias` 相同，差别只在谁能看穿（spec.md:371）。
- 转换只在赋值、传参、返回位置；声明模块内 `u + 1` 也是错（spec.md:385）。所有运算都是
  `let x: Float = a` 解包、算、以 opaque 位置返回自动回包。
- 运行期 opaque 就是目标（spec.md:388-390），`peel_opaque`（types.dawn:638）是后端看表示的
  唯一入口；只有五件事允许看见 `TyOpaque`（spec.md:396-403）。
- 幻影参数明文允许：「即使某个类型参数根本不出现在 target 里，`Phantom[Int]` 与
  `Phantom[String]` 仍是两个类型」（spec.md:392-394）。

### 3.2 窄浮点：`std/narrow`（刀 0，D3）

没有 `float_to_bits` 一类 intrinsic，舍入用纯算术：找指数（精确的倍增与减半）、按 2 的幂
缩放到整数域（精确）、`to_int` 截断后手工 ties-to-even、再乘回。次正规靠把量子钳在
`2^(emin-p+1)`；溢出比较最大有限值后给 `1.0/0.0`。

```dawn
pub opaque type BF16 = Float

pub fn round_binary(x: Float, p: Int, emin: Int, emax: Int) -> Float
pub fn round_bf16(x: Float) -> Float = round_binary(x, 8, -126, 127)
pub fn round_fp16(x: Float) -> Float = round_binary(x, 11, -14, 15)
pub fn round_f32(x: Float) -> Float = round_binary(x, 24, -126, 127)

pub fn bf16(x: Float) -> BF16 = round_bf16(x)
pub fn add(a: BF16, b: BF16) -> BF16 = {
  let x: Float = a
  let y: Float = b
  round_bf16(x + y)
}
```

证据：Python 用 `fractions.Fraction` 做精确 round-to-nearest-even 作 oracle，58 个输入
（手挑的 tie、次正规、溢出、`5e-324`、`1.79e308` 边界加 40 个随机 64 位模式）乘三种格式
共 174 条，JVM `bad=0`，`scripts/spike-native/run.sh` 七项全部 `differential ok`。
落地时语料进 `scripts/spike-native/narrow_round.dawn` 加手写 `.expect`，oracle 生成脚本进
`scripts/narrow-contract/`（同 `dtoa-contract` 的形状）。

双舍入定理的适用面：

| 运算 | bf16 (p=8) | fp16 (p=11) | f32 (p=24) | 说明 |
|------|-----------|-------------|------------|------|
| `+ − × ÷ √` | 成立，需宽格式精度至少 18 | 至少 24 | 至少 50 | Figueroa：宽格式精度不小于 2p+2 时「宽算一次加窄舍一次」等于窄格式正确舍入。设备上 `addf ... rounding<nearest_even> : tile<Nxbf16>` 是原生 bf16 加，与 `round_bf16(a + b)` 逐位相等就是定理的内容 |
| fma | 不覆盖 | 不覆盖 | 不覆盖 | 三元运算无定理；拆 `mulf` 加 `addf` 各自舍入，或声明容差 |
| 超越函数 | 无定理 | 无定理 | 无定理 | 定义为「f64 算再舍入」；设备侧只能容差契约。**刀 7b 起这一格有客户了**：`exp / exp2 / log / log2 / rsqrt / tanh / pow` 七个操作与它们的七个 kernel 全在容差档，判词 `atol = rtol = 1e-5`（§6.6）。`sqrt` 是例外，IEEE 754 要求它正确舍入，本机实测设备答案与宿主参考逐位相同 |
| matmul / `mmaf` | 容差 | 容差 | 容差 | tensor core 内部 f32 累加且顺序不定。层 2 对拍从第一天就分「逐位」与「容差」两档，逐位那档才是门禁 |
| fmod | 精确 | 精确 | 精确 | 任何精度下都精确，不需舍入 |

设备侧硬要求：所有 `addf / mulf / divf` 显式写 `rounding<nearest_even>`，其它模式让定理失效。

模块面（落地形状以 `std/narrow.dawn` 为准）：导出 `opaque BF16 / FP16 / F32`、四个 `round_*`、
三个构造子 `bf16 / fp16 / f32`、`Narrow` trait（`to_f64 / add / sub / mul / div / sqrt / neg / abs`），
以及刀 6 加的 **bf16 位模式编解码** `bf16_bits(x: Float) -> Int` / `bf16_of_bits(bits: Int) -> Float`：
没有 float-to-bits 原语，位模式用 `round_binary` 同款的精确算术拼出来（指数靠倍增减半，尾数靠
2 的幂缩放到整数域）。`bf16_bits` 对不在格点上的值**截断**（等于取 binary32 高半字的位），
不舍入，所以调用方先 `round_bf16`；NaN 一律答规范 quiet NaN `0x7FC0`（`Float` 没有程序能读的
payload），超出范围答该符号的无穷。std 测试对全部 65536 个位模式做「解码 → 编码」往返：65282 个
非 NaN 模式逐位回到自己且 `round_bf16(v) == v`（编解码的格点就是舍入的格点），254 个 NaN 模式
解码成 NaN、编码回 `0x7FC0`。只做 bf16；fp16 / f32 的编解码同形，有客户再加。不导出运算符
（做不到）、不导出 fma。不给 `BF16` 写 `impl Display`，渲染沿用 `Float`。登记进 `std/modules.txt`。
Emit-Change 面：刀 0 与刀 6 实报都是全部十个 `emit` label 都动（见 §8）。

### 3.3 `Dtype` 与 `Tensor[D]`（刀 1 已落地）

约束来自 spec.md:636-640：类型参数只出现在投影或不出现在参数位的方法按名字不可调用，
所以 dtype 以**标记值**入参：

```dawn
pub type F64 = | F64
pub type F32 = | F32
pub type BF16 = | BF16          # 刀 6
pub type I32 = | I32            # 刀 10

pub trait Dtype[D] {
  fn dtype_name(d: D) -> String
  fn dtype_bytes(d: D) -> Int
}

pub opaque type Tensor[D] = (Int, Int)     # 句柄与元素个数；D 幻影

pub fn alloc[D: Dtype](d: D, len: Int) -> Result[Tensor[D], ForeignError] !Gpu
pub fn upload[D](t: Tensor[D], data: List[Float]) -> Result[Unit, ForeignError] !Gpu
pub fn download[D](t: Tensor[D]) -> Result[List[Float], ForeignError] !Gpu
pub fn free[D](t: Tensor[D]) -> Result[Unit, ForeignError] !Gpu
pub fn launch(kernel: String, grid: Int, args: List[Int]) -> Result[Unit, ForeignError] !Gpu
pub fn sync() -> Result[Unit, ForeignError] !Gpu
pub fn handle_of[D](t: Tensor[D]) -> Int
pub fn size[D](t: Tensor[D]) -> Int
```

与计划稿的一处出入：target 从 `Int` 改成 `(Int, Int)`，句柄旁边带上元素个数。原因是
§4.2 那条纪律：接缝在错误面之下，`upload` 的长度检查、`alloc` 的长度检查、`launch` 的
grid 检查都在效果**之上**、由 std 函数做，于是两种 handler 都覆盖得到；而长度检查要能做，
张量值本身就得知道自己多长。std 自己铸的失败种类：`gpu.bad_length`（`alloc` 的 `len < 1`）、
`gpu.length_mismatch`（`upload` 的长度不符）、`gpu.bad_grid`（`launch` 的 `grid < 1`），
三者在每个 handler 下都是同一个字符串。

**bf16 标记（刀 6 已落地）**：`gpu.BF16 = | BF16`，`dtype_name` 答 `"bf16"`、`dtype_bytes` 答 2。
它与 `std/narrow` 的 opaque `BF16` **同名不同物**：标记是缓冲元素格式的标签（无内容的值，按名传给
`alloc`），narrow 的是宿主上的一个数；`gpu.F32` 与 `narrow.F32` 早就是这个关系，bf16 照做，程序
用限定名 `gpu.BF16` / `narrow.BF16` 区分（同一模块不带别名地同时 `use` 两者会撞名，这是既有事实）。
没有复用 narrow 的类型做标记：那样 `alloc(narrow.bf16(0.0), n)` 得造一个值当标签，而效果操作
只搬字符串，两边本就不需要认识对方的类型。**宿主值在每种格式下都是 `List[Float]`**：`upload` 到
bf16 张量把每个 Float 舍入到最近的 bf16（ties-to-even，设备自己的 load 也不会拒绝一个 f64），
`download` 把每个 bf16 精确地答成 Float；两个 handler 共用 `element_bytes(dtype) -> Option[Int]`
（`f64` → 8、`bf16` → 2、其它 `None`）决定接不接受一个 `gpu_alloc`，`f32` 仍是「能打字不能分配」。
`Tensor[D]` 的 target 没变（仍是 `(Int, Int)`，格式记在 handler 的表里），所以 opaque-twin 与
checker-corpus 的语料一字未动。

**i32 标记（刀 10 已落地）**：`gpu.I32 = | I32`，`dtype_name` 答 `"i32"`、`dtype_bytes` 答 4，
`element_bytes` 答 `Some(4)`。它原本声明在 `packages/tileir/src/dev.dawn` 里，因为那时 i32 只是
tile 的元素格式、不是缓冲格式；刀 10 让它两者都是，于是按「缓冲格式归 std/gpu」搬了过来
（Dawn 没有 re-export，所以是搬而不是转出；`I1` 仍留在包里，它只是 tile 格式）。
`round_to("i32", x)` = **向零截断后按二补数回绕**——「32 位缓冲装得下什么」的完整含义，
`to_int` 的截断正是方言 `ftoi` 的 `nearest_int_to_zero`，回绕正是 `addi` / `muli` 的行为；
一个只截断不回绕的参考会在每个溢出的和上与设备分道扬镳。真设备侧走刀 6 的 `Bytes` 通道
（`pack_i32` / `unpack_i32`，小端四字节），与 bf16 同一条路。

**`List[Float]` 通道对 i32 无损**：binary64 尾数 53 位，i32 与 u32 的值域都在 32 位以内，
所以一个整数值从 `upload` 到 `download` 一个 bit 也不动。这不是细节，是刀 10 能把整个族
钉在逐位档上的前提之一（另一个是整数加法模 2^32 的精确结合律，见 §6.6）。

`Tensor[F64]` 传给要 `Tensor[F32]` 的参数是类型错误，`scripts/checker-corpus/cases/phantom_opaque.dawn`
把这条钉成 must-red 语料。

### 3.4 opaque-twin 怎么对待这两个 opaque

- `BF16`：`sed 's/^pub opaque type /pub alias /'` 后 `dawn test` 照过，可以按原样进
  `scripts/opaque-twin/narrow.dawn`，形状照 `char.dawn`：在一次运行内把 `bf16` 上的
  `==` / `<` / hash 与 `Float` 上的比对，不一致就 `panic`。
- `Tensor[D]`：alias 版推断失败，是五件事里「可赋值性与统一判定」的合法差异。刀 1 给
  `run.sh` 加了第三种标记 `# twin-infer-only: <why>`，含义是「opaque 侧必须编译并运行；
  alias 侧必须被拒，且每条诊断都是 cannot infer type parameter(s)」。它把幻影与 alias
  的唯一差别拼写成了一个判词：alias 侧若某天开始接受（`D` 从虚空里推出来了）或开始报别的
  错，都会红。语料 `scripts/opaque-twin/phantom.dawn` 同时在 opaque 侧钉住身份仍是目标的
  （句柄的 `==` / `<` / hash 与 `(Int, Int)` 一致）。

## 4. 宿主层：`Gpu` 效果族

### 4.1 操作清单（刀 1 已落地）

效果操作不能带类型参数，效果本身也不能（spec.md §6.5），所以操作面是单态、句柄级的；
§3.3 的类型化包装是唯一的用户面。名字带 `gpu_` 前缀，理由与 `Fs` 的 `fs_` 相同
（`std/io.dawn:417-420`：`use std/gpu.{Gpu}` 会把操作名倒进引入方命名空间）。

```dawn
pub effect Gpu {
  fn gpu_alloc(dtype: String, len: Int) -> Result[Int, ForeignError]
  fn gpu_upload(handle: Int, data: List[Float]) -> Result[Unit, ForeignError]
  fn gpu_download(handle: Int) -> Result[List[Float], ForeignError]
  fn gpu_launch(kernel: String, grid: Int, args: List[Int]) -> Result[Unit, ForeignError]
  fn gpu_free(handle: Int) -> Result[Unit, ForeignError]
  fn gpu_sync() -> Result[Unit, ForeignError]
}
```

v1 刻意缺的：`gpu_load_module(bytes)`（第一里程碑 kernel 由 `launch` 的名字查表，模块在
handler 安装时一次性给；第二里程碑再把「字节码到模块句柄」做成操作）；三维 grid
（`grid: Int` 先一维，`(Int, Int, Int)` 是零成本升级）。`upload / download` 的 `List[Float]`
**保留到了刀 6 之后**：操作面在每种格式下都搬 `List[Float]`（与假设备的参考实现同一种值），
bf16 的打包发生在操作**之下**、真 handler 里（§4.4 的 `Bytes` 版 intrinsic），假设备则按缓冲
格式舍入；计划稿「换 `Bytes`」的那一步没有必要，因为格式转换只有真设备那一侧需要字节。

### 4.2 `with_gpu_real` 形态（刀 4 已落地）

```dawn
pub fn with_gpu_real[T](kernels: Map[String, Bytes], body: fn() -> T !Gpu !io) -> T !io
```

与计划稿的两处出入，都有理由：

- **参数是 `Map[String, Bytes]` 而不是一个 `module: Bytes`**。`packages/tileir` 的 `encode` 一次
  编一个 kernel，一个程序要用两个 kernel 就有两个 cubin；按名字装表与 `with_gpu_fake` 的
  `Map[String, fn]` 同形，`launch` 查表找不到名字时两个 handler 答同一个 `gpu.no_kernel`，
  也正是 §4.5 说的「模块与 kernel 名的绑定在宿主层是一张表」。
- **臂里不是 `catch_fault(() => gpu_*_host(...))`，intrinsic 自己答 `Result`**。原生 fault 只带
  一条消息，`kind` 恒为 `"fault"`（runtime-intrinsics-design.md §12.4），经 `catch_fault` 出来的
  `kind` 装不下 CUresult 的名字；所以八个 intrinsic 直接构造 `ForeignError`，`kind` 是
  `cuda.<cuGetErrorName>`（如 `cuda.CUDA_ERROR_INVALID_IMAGE`），message 写驱动调用名与数字
  （`cuModuleLoadData: CUresult 200 (...)`）。没有 libcuda 可装载答 `gpu.no_driver`，JVM 上一律
  `gpu.unsupported_backend`。**接缝仍在错误面之下**：臂把这个 `ForeignError`原样交出，不加工。

handler 的状态与假设备同款：句柄从 1 起编号、`Map[Int, (设备指针, 元素数, 格式名)]` 一张表，未签发
或已释放的句柄答 `gpu.no_such_buffer`；`gpu_alloc` 收 `element_bytes` 认识的格式（`f64`、刀 6 起
`bf16`），按元素字节数分配，其它答 `gpu.unsupported_dtype`。f64 缓冲经 `Array[Float]` 过运行时
（逐 double 复制，NaN payload 也不丢）；bf16 缓冲在 std 里 `pack_bf16`（先 `round_bf16` 再
`bf16_bits`，低字节在前）成 `Bytes` 交给 `gpu_upload_bytes_host`，`download` 取 `n * 2` 字节回来
`unpack_bf16`。**f64 没有改走 `Bytes`**：Dawn 没有 float-to-bits，纯 Dawn 把 f64 拆成 8 字节要每个
元素跑一遍指数循环、还会丢 NaN payload，而 `Array[Float]` 那条缝对每一个位模式都精确且零成本；
两条缝各是自己格式最便宜的精确缝。`gpu_launch` 先查名字、再查参数（`gpu.no_arguments`、
`gpu.no_such_buffer`），
**然后才碰设备**：cubin 在该 kernel 第一次 `launch` 时交给 `cuModuleLoadData`，模块句柄留到本次
安装结束，所以不 launch 的程序不装模块，alloc/upload/download 在装不了模块的驱动上照样可用，
这正是 560.94 上能验到的那一半。grid 计 tile block 数，intrinsic 以 block dims `(1,1,1)`、
shared 0 调 `cuLaunchKernel`（cuda-tile 宿主示例的启动形态）。第一个需要设备的操作打开设备
（`cuInit`、device 0、`cuCtxCreate_v2`）；`body` 返回后 `gpu_close_host` 销毁上下文
（连带释放程序没 free 的缓冲与模块）并 `dlclose`。std 侧唯一能在 `dawn test --stdlib` 里断言的是
「不碰设备的拒绝」（dtype、句柄表、kernel 表三处，两个后端与有无驱动的机器上答案相同），
`std/gpu.dawn` 最后一个 test 块就是它；设备本身归 `scripts/tile-gpu-diff`（§6.4）。

### 4.3 假设备 `with_gpu_fake`（刀 1 已落地）

```dawn
pub alias RefFn = fn(List[String], List[List[Float]]) -> List[Float]
pub alias WideRefFn = fn(List[String], List[List[Float]]) -> List[(Int, List[Float])]
pub fn with_gpu_fake[T](kernels: Map[String, (Int, WideRefFn)], body: fn() -> T !Gpu) -> T
pub fn last_out(f: RefFn) -> WideRefFn
pub fn vadd_ref(dtypes: List[String], ins: List[List[Float]]) -> List[Float]
pub fn sum_ref(dtypes: List[String], ins: List[List[Float]]) -> List[Float]
pub fn round_to(dtype: String, x: Float) -> Float
pub fn reference_kernels() -> Map[String, (Int, WideRefFn)]
```

- **纯**（签名无 `!io`），所以它进得了 `dawn test --stdlib` 与 comptime。
- 句柄从 1 起编号，缓冲是 `Map[Int, (格式名, List[Float])]`；`gpu_alloc` 接受 `element_bytes`
  认识的格式（`f64`、`i32`、`i8`、`u8`、`bf16`、`f16`），其它 dtype 答 `Err(kind: "gpu.unsupported_dtype")`，
  与真设备拒绝它没有的格式同形；不存在的句柄答 `gpu.no_such_buffer`；**缓冲持有的是该格式的内存会
  持有的值**：`gpu_upload` 存入前按缓冲格式 `round_to`（f64 就是原样），launch 写回的值也按**那个**
  缓冲的格式舍入；长度不查（长度检查在效果之上）；`gpu_launch` 按名查 `kernels`，把每个实参缓冲的
  **格式表**与内容按序交给参考实现，参考实现答 `[(实参位置, 内容)]`，每一对写进那个位置的缓冲；
  位置越界答 `gpu.bad_write_back`；名字不在表里答 `gpu.no_kernel`，一个实参都没有答
  `gpu.no_arguments`；`grid` 被忽略（参考实现一次算整个向量）。
- **参考实现说自己写了哪几个缓冲**（刀 11 的改动面）。刀 10 之前的签名是 `-> List[Float]`，
  假设备把它存进**最后一个**实参；刀 11 起是 `-> List[(Int, List[Float])]`，于是一个 kernel
  可以填两个缓冲（`sum_diff`），也可以改写它自己读的那个（`reverse` / `invert`，就是「原地」的
  全部含义：写回列表里的位置也在输入里）。每个输入都在任何一对被应用之前读完，所以原地的参考
  看到的是设备的 load 看到的那份。四十个旧签名的参考一个没改，`last_out` 在建表处替它们说
  「写最后一个」——四十次 `[(len(ins) - 1, ..)]` 是四十次写错下标的机会，而它一句话也没多说。
  真设备不需要任何对应改动：kernel 写哪个缓冲是 kernel 的事，宿主只是多下载几个。
- **参考实现知道 dtype**（刀 6 的改动面：签名前面加一个 `List[String]`，`vadd_ref` / `sum_ref` /
  `reference_kernels` / `with_gpu_fake` 四处签名，`vadd_diff.dawn` 只经 `reference_kernels()`
  用它、没有改）。原因是寄存器语义：内存里的舍入假设备自己做，但 `sum` 的累加 tile 在 bf16 下
  **每一步** `addf` 都舍入，一个只在最后写内存时舍入的假设备会把多步双舍入算错；所以 `vadd_ref`
  对输出格式 `round_to` 每个和、`sum_ref` 对每一步 `acc + x` 舍入。`vadd_bf16` 与 `vadd` 用同一个
  参考（`reference_kernels` 把两个名字都指向 `vadd_ref`）。
- `launch` 用的是宿主侧参考实现，第一里程碑就是 `vadd_ref`。同一个参考实现是层 2 对拍
  `.expect` 的来源之一（另一来源是手写的期望值）。
- 每个参考实现的表项把缓冲参数个数与函数放在一起；假设备在调用函数之前做精确相等检查，
  不等时答 `gpu.bad_arity`，message 同时写 kernel 名、期望数和实际数。零参数仍保留既有
  `gpu.no_arguments`；`vadd` / `vadd_bf16` 要 3 个（两输入一输出），`sum` 要 2 个。
- 刀 6 的 std 测试把假设备钉在 narrow 上：全部 65536 个 bf16 位模式各配一个固定种子 LCG 抽出的
  随机位模式，bf16 `vadd` 在假设备上的答案与 `narrow.add(bf16(a), bf16(b))` 逐值渲染相同（`to_string`
  分得清 `-0.0` 与 NaN）；另一组 1024 对格点外的随机 Float，验的是上传时的舍入（假设备若不舍入
  就答 `round(a + b)` 而不是 `round(round(a) + round(b))`，这组会红）。
- 今天写不出的断言「一个 `!Gpu` 程序在没有 GPU 的机器上跑完 vadd 并得到正确答案」是
  `std/gpu.dawn` 的第一个 test 块。

层 2 对拍的形状：同一个 `!Gpu` 程序跑两遍，一遍 `with_gpu_fake` 一遍 `with_gpu_real`，
输出同一组行。这与 `scripts/spike-native/effect_fs_seam.dawn`（`c569ff18`）一模一样。

### 4.4 intrinsic 与运行时落点（刀 4 已落地）

- `types.dawn` 的 `Rt` 加 `RtGpu`；`intrinsics()` 登记**十项**（刀 4 八项、刀 6 两项），全部
  `internal: true`、行是 `!io`、归属 `RtGpu`：六个操作的 `gpu_{alloc,upload,download,launch,free,sync}_host`，
  加 `gpu_load_module_host(cubin: Bytes) -> Result[Int, ForeignError]`（答 CUmodule 句柄）与
  `gpu_close_host() -> Unit`（释放上下文与库），再加刀 6 的 `gpu_upload_bytes_host(devptr, data: Bytes)`
  与 `gpu_download_bytes_host(devptr, nbytes) -> Result[Bytes, ForeignError]`。多出的两个是刻意的：
  装模块单独成操作才能懒到第一次 launch（§4.2），close 单独成操作才有地方在 handler 退出时释放
  （LSan 下实测零漏）。ABI 上缓冲区是裸设备指针（`Int`）、f64 数据是 `Array[Float]`、打包格式的数据
  是 `Bytes`、launch 参数是 `Array[Int]`：`Array` 与 `Bytes` 是两个后端都能在运行时边界叫出名字的
  容器，List 到 Array 的一趟与 bf16 的打包都走在 std 里（`std/pvec` 的 `Vec` 是记录不是 `List`，
  std 源码里两者不能互换，所以用 `array_new/array_push` 循环；打包用 `bytes.Buf`）；返回值全是
  `Result`，理由见 §4.2。C 侧的两个 `Bytes` 函数只是 `cuMemcpyHtoD_v2` / `cuMemcpyDtoH_v2` 加一次
  `dawn_bytes_of`，不认识任何格式。
- C 侧：`runtime/c/dawn_rt.c` 末尾一段，夹在 `DAWN_RT_GPU_BEGIN / END` 两个标记之间（台账门
  按这一段比较，§6.4）。`dlopen("libcuda.so.1", RTLD_NOW | RTLD_LOCAL)`，`dlsym` 十三个入口
  （版本化符号要自己拼：`cuCtxCreate_v2 / cuMemAlloc_v2 / cuMemcpyHtoD_v2 / cuMemcpyDtoH_v2 /
  cuMemFree_v2 / cuCtxDestroy_v2`，cuda.h 里的宏在 dlsym 面前不存在），不链 `-lcuda`，也不加
  `-ldl`（glibc 2.34 起 dlopen 在 libc 里；任何链接行都没改）。借用约定要守：Array 的槽是借来的，
  读 `->val.f` 而不能 `dawn_unbox_float`（后者会释放 box，第一版就因此在 native 上 `drop of a
  value with rc=...` 崩掉）。wasi 分支每个函数答 `gpu.unsupported_backend`。
- JVM 侧：`rtclasses.dawn` 的 `gen_gpu_class` 出 `dawn/rt/Gpu`，八个静态方法直线体、无分支无
  handler，每个 `new Result$Err(new ForeignError("gpu.unsupported_backend", "<name>: ...", None))`
  （`gpu_close_host` 答 Unit）；`emit.dawn` 的 `rt_class` 多一臂；`main.dawn` 与 `dawn/rt/Io` 同样
  无条件发射。「抛异常」改成「答 Err」是因为错误模型：按构造拒绝应当是值不是 `LinkageError`。
- 分组表不用动：`RtGpu` 走 `rt` 表项，`lower.dawn` 的分配测试按 `rt: Some(_)` 自动归组；
  `scripts/intrinsic-parity.py` 只读 inline 两组，也不用动（计划稿说的 `rt_class` 锚点并不存在）。
  要动的是三处计数与两张表：`types.dawn` / `lower.dawn` 的 intrinsic 总数 99 → 107 → 109，
  `ir/interp.dawn` 的 `comptime_rejects` 加名字（77 → 85 → 87，编译期不许开驱动，理由同 io），
  以及 `selfhost/builtins.dawn` 的镜像行（`scripts/builtin-decl-contract` 双向对账；刀 4 漏了这张表，
  `825b465b` 补上，刀 6 的两项随手同步）。

### 4.5 kernel 怎么被 `launch` 点名

分阶段路线下不需要 `CFnRef`：kernel 是 §5 记录出来的值，有名字（`entry @vadd`），
`gpu_launch("vadd", ...)` 传字符串；`with_gpu_real` 装机时拿到整个模块的字节码，
`cuModuleGetFunction` 按名取。模块与 kernel 名的绑定在宿主层是一张 `Map[String, TileProg]`，
名字不在表里两种 handler 都答 `Err(kind: "gpu.no_kernel")`。

## 5. 设备层（分阶段路线）

### 5.1 kernel 体是什么值（刀 2 已落地）

一个只发 `Dev` 效果的普通 Dawn 函数。操作单态、句柄级，与 `Gpu` 同款；类型化包装加幻影
（落地形状以 `packages/tileir/src/dev.dawn` 为准）：

```dawn
pub opaque type Tile[D] = Int                 # kernel 内的 SSA 名
pub opaque type Param[D] = (Int, String)      # 参数位与 dtype 名，在 param() 处定格
pub opaque type Idx = Int                     # 标量 i32 tile 的句柄：block id 及其派生

pub effect Dev {
  fn t_block_id(axis: Int) -> Int
  fn t_load(param: Int, dtype: String, idx: Int, n: Int) -> Int
  fn t_store(param: Int, dtype: String, idx: Int, n: Int, v: Int) -> Unit
  fn t_addf(dtype: String, n: Int, a: Int, b: Int) -> Int
}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let i = block_id(0)
  let ta = load(a, i, 128)
  let tb = load(b, i, 128)
  store(out, i, 128, addf(F64, 128, ta, tb))
}
```

`trace_kernel("vadd", ["f64","f64","f64"], () => vadd(param(F64,0), param(F64,1), param(F64,2)))`
在记录 handler 下跑一遍，`render` 出的文本就是 `scripts/tile-golden/vadd.mlir`（26 行）。
拼写按 Tile IR 规范附录的向量加示例与 `cuda-tile` 仓库的 round-trip 测试
（`test/Bytecode/operationsTest.mlir`）：入口参数是标量 `tile<ptr<f64>>`，每个 load / store
之前先 `reshape → broadcast → offset` 把它铺成 `tile<128xptr<f64>>`，偏移是
`idx * 128 + iota`（`constant / muli / reshape / broadcast / iota / addi` 六行）；
链头 `%0 = make_token : token`，`load_ptr_tko weak %p token=%t : ... -> tile<128xf64>, token`
与 `store_ptr_tko weak %p, %v token=%t : ... -> token` 各消费一个 token 产生一个；
`addf` 显式 `rounding<nearest_even>`。同一 (参数, 索引, 宽度) 的指针梯子只发一次。
文本合法性刀 2 时只对照了规范文本与那份测试；刀 3 起文本与字节码由同一张指令表产出
（`lower.dawn`，见 §5.3），字节码被 `tileiras` 13.3.36 接受并编成 sm_86 cubin（§6.1），
而 `tileiras` 内含 `cuda-tile` 的 reader 与 verifier（拒绝时给出字节偏移与 op 名，§6.2），
所以那个退出码就是这同一张表的机器判词。`cuda-tile-translate` 仍不在本机，文本本身没有过
parser 的 round-trip，这一点没变。

落地的设计点：

- **Tile 程序的正式表示是 ADT 不是字符串**：`TileProg = { name, params: List[String], ops: List[TileOp] }`，
  `TileOp` 是 SSA 形式的变体：`MakeToken(dst)`、`BlockId(dst, axis)`、
  `Load(dst, tok_out, param, dtype, idx, n, tok_in)`、`Store(tok_out, param, dtype, idx, n, value, tok_in)`、
  `AddF(dst, dtype, n, lhs, rhs)`，外加给刀 5 留位的
  `For(iv, lower, upper, step, inits, carried, results, body)`（本版无人记录、lowering 拒绝）。
  文本渲染与字节码编码是它的两个消费者，golden 钉文本，`tileiras` 钉字节码；两者之间
  自刀 3 起隔着一张共用的线性指令表（§5.3）。
  记录里的句柄是 trace 编号（从 1 起，0 是入口 token），渲染时按出现顺序重编，
  因为指针梯子的中间名在记录里没有。
- **token 链线性**：handler 里一个 `tok` 状态格，每个内存操作消费上一个、产生下一个，
  `MakeToken(0)` 是链头。
- **记录 handler 在效果之上做两项校验并 `panic`**：`param(d, pos)` 必须与 `trace_kernel`
  的 `params` 表一致（位置在范围内、格式相同），tile 宽度必须是 2 的幂。前者是刀 2
  负控「`load` 的 dtype 写死 f64」变红的位置：f32 kernel 的入口说 f32、load 说 f64，
  在记录时就被拒，而不是等到 `tileiras`。
- 与计划稿的一处出入：索引不是裸 `Int` 而是 `opaque type Idx = Int`。宿主整数与 SSA
  句柄在类型上分开，把宿主数当索引传给 `load` 是类型错误，不是渲染器里的悬空句柄。

### 5.2 kernel 内的控制流（刀 5 已落地）

记录时 Dawn 的 `if / for / while` 是宿主求值：条件只依赖宿主已知量（形状、参数位、常量）时，
展开是对的、免费的，也就是 cuTile 里 `ct.Constant` 折叠的效果。条件依赖 tile 值时 Dawn 的
`if` 拿不到它（`Tile[D]` 是句柄），必须走结构化操作。

**已核实**：效果操作的参数可以是函数类型，handler 臂里能调用它，但那个函数类型不能写
`!Dev`（在 `effect Dev` 自己的声明体里 `!Dev` 还不在作用域）；写效果变量 `!e` 能过 check，
但传进去的闭包只准纯或 `!io`（spec.md §6.3：名义类型绑定的效果参数只走空证据），一个发
`Dev` 操作的循环体在调用点就被拒。所以 `d_for` 不做成操作，做成 `packages/tileir` 里的
普通函数，夹在两个操作之间（落地形状以 `packages/tileir/src/dev.dawn` 为准）：

```dawn
pub effect Dev {
  # ... 刀 2 的四个操作 ...
  fn t_idx_const(value: Int) -> Int                 # 标量 i32 tile：宿主常量
  fn t_idx_add(a: Int, b: Int) -> Int
  fn t_idx_mul(a: Int, b: Int) -> Int
  fn t_loop_begin(lower: Int, upper: Int, step: Int, inits: List[Int]) -> (Int, List[Int])
  fn t_loop_end(outs: List[Int]) -> List[Int]
}

pub fn idx_const(value: Int) -> Idx !Dev
pub fn idx_add(a: Idx, b: Idx) -> Idx !Dev
pub fn idx_mul(a: Idx, b: Idx) -> Idx !Dev

pub fn d_for[D](lower: Idx, upper: Idx, step: Idx, init: Tile[D],
                body: fn(Idx, Tile[D]) -> Tile[D] !Dev) -> Tile[D] !Dev
pub fn d_for2[A, B](lower: Idx, upper: Idx, step: Idx, a: Tile[A], b: Tile[B],
                    body: fn(Idx, Tile[A], Tile[B]) -> (Tile[A], Tile[B]) !Dev) -> (Tile[A], Tile[B]) !Dev
```

`d_for` 调 `t_loop_begin` 开区域（答归纳变量句柄与区域内的携带值句柄），在宿主上把 `body`
**跑一次**（体内发的操作落进当前区域），再调 `t_loop_end(outs)` 关区域（答循环之后的携带值
句柄）。普通函数的参数类型写 `!Dev` 没有限制。

落地的设计点，与计划稿的出入逐条标出：

- **区域栈**：记录 handler 多一格 `frames: List[Frame]`，`Frame` 存开区域时的外层操作表与
  循环头（`iv / lower / upper / step / inits / carried`）。`t_loop_begin` 压栈并把当前操作表
  清空，`t_loop_end` 弹栈、把体包成 `For(iv, lower, upper, step, inits, carried, results, body)`
  接回外层表；`body` 以 `Continue(values)` 结尾（下一轮收到的值）。这正是 JAX `lax.scan`
  的 tracing 形状。
- **token 穿过循环携带值**：handler 把 `tok` 作为**最后一个**携带值自己带进带出：`inits`
  末尾是循环前的 token，体从区域内的携带 token 起链，`Continue` 末尾是体的最后一个 token，
  循环后 `tok` 换成 `results` 末尾。kernel 体看不见它。负控 `loop-token-not-carried`
  （run.sh）把「循环后换 token」这一行删掉，`sum` 在降低时被按名拒绝。
- **循环边界与步长是 `Idx`**（SSA 句柄）而不是宿主 `Int`：`for` 的三个操作数在 Tile IR 里是
  `tile<i32>` 值，块相关的边界（`b * chunks + 1`）本来就要算；宿主常量走 `idx_const`，这是
  三个索引算术操作进 `Dev` 的原因。计划稿写的是 `(start, end)` 宿主整数。
- **公开面是带类型的 `d_for` / `d_for2`，句柄级的 `d_for(carried: List[Int], ...)` 是模块私有**
  （`loop_handles`）：opaque 只在声明模块内能拆包（spec.md §2.7），一个外部 kernel 体既造
  不出 `Int` 也换不回 `Tile[D]`，句柄级签名在模块外不可用；导出拆包函数会让幻影可伪造。
  两个 tile 之外的携带值组合等有客户再加。
- **降低时按区域限定作用域**：`lower.dawn` 的名字表与指针梯子的 memo 在进区域时继承外层、
  出区域时回到外层加上 `results`；体内定义的句柄记进 `closed`，之后再被引用按名拒绝
  （「a loop body defined and which is not visible after the loop」），而不是渲染成一个越出
  支配关系的 SSA 名。指令表给 `For` 编号的次序是文本的阅读序：结果、归纳变量、携带值、体。
- **字节码的区域布局**（`BytecodeWriter.cpp` 的 `writeRegion / writeBlock` 与
  `BytecodeGen.cpp`）：`for` = opcode、**结果个数**（有变长操作数或结果的操作都先写个数，
  `return` 与 `continue` 的两个 0 就是这个）、结果类型、**flags**（`unsigned` 是 13.2 加的
  可选字段，写入器只在目标版本不低于 13.2 时写这一格，所以字节码从此与版本号相关）、
  操作数个数与操作数、区域数 1、块数 1、块参数个数与类型、块内操作数与操作。**值编号**：
  块参数接着外层计数往下编，块内结果继续，块结束时计数**回滚**到块参数之前，`for` 自己的
  结果再从那里编。指令表的编号是文本的，写入器用一张 `index` 表把表值映射到这套索引，
  不是第二套编号。负控 `for-results-not-rolled-back` 删掉回滚，`tileiras` 以
  `operand index 39 out of bounds (size=25)` 拒绝。
- **刀 7a 加了什么、没加什么**：加的是边界（`load_ptr_tko` 的 `mask` 与 `paddingValue`、
  `store_ptr_tko` 的 `mask`，都是这两个操作本来就有的可选操作数段，零新类型）与逐元素算术
  （`subf mulf divf negf absf maxf minf fma`、`cmpf cmpi select`、`constant` 的浮点与整数
  splat、`iota`）。**仍然没有**：`reduce` / `scan`（要 `identities` 属性与归约区域）、
  超越函数、二维及以上的 tile（`render.ty` 的 rank ≥ 2 仍 panic）、`mmaf`、多维 grid、
  整数与窄浮点缓冲、view 类型族。逐条归属见 agent-handoff 的 cuTile 覆盖计划。
- **`d_if` 刀 7b 做了**（刀 5 时判为「等第一个需要 tile 值条件的 kernel」）。它是本包第一个
  **两个区域**的操作：`if` 的读取器数区域数，给一个或三个都当场拒（实测），所以没有 else 的
  `if` 也要写第二个区域。条件是 **rank-0 的 `tile<i1>`**，rank-1 的会被拒
  （`op operand #0 must be 0D tile of i1 values`，实测），这也是 `Scalar[D]` 这个 opaque
  存在的原因：`Tile[D]` 在本包里是 rank 1，两者在 Tile IR 里不可互换，`spread` 是唯一的桥。
- **降低 `if` 要把 then 分支降两遍**：结果的类型是 then 分支 `yield` 出来的东西的类型，而
  结果的编号必须在两个分支之前（文本的阅读序）。所以 `lower_if` 先用外层状态把 then 分支
  降一遍、只从它的终结子读类型，丢掉编号与 memo，再正式降一遍。降低是纯函数，两遍必然一致。
- **刀 7b 加了什么、没加什么**：加的是归约（`reduce` 0x58 + `yield` 0x6D，含 N 元与
  `identities` 属性）、两区域的 `if`（0x32）、十个超越函数
  （`exp` 0x17、`exp2` 0x18、`log` 0x3F、`log2` 0x40、`sqrt` 0x64、`rsqrt` 0x5D、
  `tanh` 0x6A、`pow` 0x54、`floor` 0x27、`ceil` 0x0D）、rank-0 tile（`Scalar[D]` 与
  `spread`）、`d_for3 / d_for4`。**仍然没有**：`scan`（0x5E，与 `reduce` 同一套区域编码，
  归刀 13）、二维及以上的 tile（`render.ty` 的 rank ≥ 2 仍 panic）、`mmaf`、多维 grid、
  整数与窄浮点缓冲、view 类型族、`sin / cos / tan / sinh / cosh / atan2 / remf`
  （同族、零新机制，有客户再加）、跨 block 的归约（一次 launch 只归约一个 tile block 内的
  一个 tile，所以本刀的归约 kernel 都是「整条向量装进一个 1024 宽的 tile、grid = 1」的形状）。
- **刀 8 加了什么、没加什么**：加的是 **tile 的形状**（`Dev` 的每个操作、`TileOp`、`Instr`
  的 `n: Int` 全线换成 `shape: List[Int]`，`render.ty` 的 rank ≥ 2 panic 拆掉，拼法是
  `tile<64x32xf64>`；字节码的 tile 类型载荷本来就写 `int64 shape[]`，一个字没改）、
  **任意 stride 的指针梯子**（`load` / `store` 除形状外还收一串以元素为单位的 stride，
  梯子是每维一条 `iota`、`reshape` + `broadcast` 到整块、乘该维的 stride 再求和；
  **零新 opcode**，`iota / reshape / broadcast / muli / addi / offset` 都是现成的）、
  `mmaf`（0x49）、`reduce` 的 `dim` 真的有多个取值、**三维 grid**（`gpu_launch_host` 的
  `grid: Int` 换成 `gx, gy, gz`，是本刀唯一动运行时的地方）。
  **仍然没有**：`scan`（0x5E，归刀 13）、`permute`（0x53）与 `cat`（0x0C）：转置用两个
  对调的 stride 就够了，零新 opcode，见下。也没有整数与窄浮点缓冲（归刀 10 / 11）、
  gather / scatter（归刀 12）、原子操作（归刀 14）、`erf`（归刀 15）、view 类型族与 TMA、
  `mmaf` 的 `fast_acc`（13.3 的 flag，我们钉 13.2，不写）、`mmai`（整数 MMA，等整数缓冲）。
- **`n: Int` → `shape: List[Int]` 是纯重构，有机器判词**：改完之后 `--record` 重录，
  刀 7a / 7b 的 **23 个 `.mlir` 与 23 个 `.tilebc` 一字节没动**。两件事让它成立：rank-1
  的梯子发的还是原来那几条指令（rank-0 的 base 与指针总是「reshape 到全 1 形状、broadcast
  到整块」，一维的 `iota` 不 reshape 也不 broadcast，stride 为 1 不发 `muli`），而
  block 索引乘 tile 宽度这一步从梯子里搬到了 kernel 源码的 `tile_at(idx, n)`，发的
  `constant` 与 `muli` 落在原来的位置。
- **转置不需要 `permute`**：`out[j][i] = x[i][j]` 就是「按 `[C, 1]` 读、按 `[1, R]` 写」，
  同一块 tile 换一对 stride 存回去。`transpose` kernel 因此是 stride 的 oracle 而不是形状
  操作的 oracle，而且矩阵是 128x64 的长方形，对调两个 stride 是错的答案而不是同一个答案的
  另一种拼法。`permute` 与 `cat` 因此没有客户，不做。
- **`reduce` 的结果掉的是被归约的那一维，区域参数永远是 rank-0**：方言散文说的是
  「除被归约的那一维外形状不变」，但它自己的第二个 `mlirExample` 印的是
  `tile<8x64xf32> dim=0 -> tile<8xf32>`。两者不一致，实测以实现为准：把结果类型写成保留
  被归约的那一维，`tileiras` 报
  `inferred type(s) '!cuda_tile.tile<2xf64>' are incompatible with return type(s) '!cuda_tile.tile<32xf64>'`。
  区域的两个块参数则**与操作数的秩无关，一律 rank-0**；写入器一度把结果类型写进块参数，
  `tileiras` 以 `'cuda_tile.addf' op failed to verify that all of {lhs, rhs, result} have
  same type` 拒绝。两条都是量出来的。
- **stride 为 0 是合法的，而且有用**：`batch_norm` 的每通道 `gamma` 是一个数，要作用在
  整列上；把它按 `[BN_ROWS]` 形状、`[0]` stride 读，梯子发出的偏移量整块相同，
  `load_ptr_tko` 就把同一个地址读 128 遍。`group_norm` 的每通道 `gamma` 同理，用
  `[1, 0]`。这省掉了一族「把一维张成二维」的公开操作。
- **归约区域与 `if` 区域里禁止访存**：方言要求归约体是纯的，而两种区域都不携带内存序 token,
  所以里面的 load / store / `d_for` 一律在记录时按名拒绝（`a load inside a reduce or if
  region has no memory order`）。这是本包自己立的规矩，不是方言的。
- **各操作的属性形状是量出来的，不是猜的**：`exp` 在 13.2 **一个属性都不写**（它的
  `rounding_mode` 是 13.3 才加的；写了会让读取器把下一个字节当别的东西，实测报
  `failed to get result type 0 for CmpIOp`）；`exp2 / rsqrt` 只写 flags（`flush_to_zero`
  是 UnitAttr，只占一个 flag 位、没有载荷）；`sqrt` 写 flags 再写 `rounding<nearest_even>`；
  `tanh` **不写 flags、只写 rounding**，而且 f64 只接受 `full`（写 `nearest_even` 会被拒，
  写 `approx` 报 f32-only，都实测）；`log / log2 / floor / ceil / pow` 什么都不写。
  每一种错的形状都单独喂过 `tileiras`，报文记在 `packages/tileir/src/bytecode.dawn` 的
  测试块里。
- **递归上限**：两个常量，`MAX_LOOP_DEPTH = 16`（区域栈深度，递归穿过 `d_for` 的 helper
  在这里停）与 `MAX_HANDLES = 65536`（一次记录能铸的句柄数，不进循环的递归 helper 在这里
  停）。都是 `panic`，报文点名原因。

第二个 kernel `sum`（`scripts/tile-golden/kernels.dawn`，golden `sum.mlir` 46 行 /
`sum.tilebc` 392 字节，cubin 8448 字节、`FUNC GLOBAL sum` 768 字节 SASS）：块 b 把 `x` 里
编号 `b*chunks .. b*chunks+chunks-1` 的 `chunks` 个连续 128 宽 tile 折进 `out` 的一个 tile，
第一个 tile 作携带值进循环，其余按序 `addf`；`chunks` 是记录时的宿主常量（golden 为 4）。
没有用 `reduce`：它要 `identities` 属性（ArrayAttr 套 FloatAttr）与带块参数的归约区域，
是另一套属性编码，而「每块出一个 tile」已经是两阶段归约的第一阶段，第二阶段（tile 内归约
写标量）等有客户再加。**逐位一致的论证**：宿主参考 `std/gpu.sum_ref` 按同一顺序折叠
（第一个 tile 起、逐 tile 左结合），设备侧 `addf` 是 `rounding<nearest_even>`、不 flush-to-zero，
每一步都是 IEEE double 加法，操作数与顺序相同则结果逐位相同；从第一个 tile 起而不是从 0.0 起，
是因为 `0.0 + -0.0 = +0.0` 会让全 `-0.0` 的 lane 差一个符号位。`std/gpu` 的测试把块 0 的
四个 tile 定成 `2^53, 1, 1, -2^53`：左结合得 0.0、右结合得 2.0、成对得 1.0，答案本身说出
用的是哪种顺序。层 2 的 GPU 对拍归刀 4 的脚本与台账。

- **刀 14 加了什么、没加什么**：加的是两个原子操作，`atomic_rmw_tko`（0x08，模式枚举
  and / or / xor / add / addf / max / min / umax / umin / xchg）与 `atomic_cas_tko`（0x07）。
  取址方式与 gather / scatter 相同（一张 i32 索引 tile 而不是 base 加 stride 梯子），因为
  想要原子的理由就是目的地由数据决定。公开面 `atomic_rmw` / `atomic_rmw_masked` /
  `atomic_add_masked` / `atomic_cas` / `atomic_cas_masked`。**仍然没有**：
  `atomic_red_view_tko`（0x75，13.3 才有，要 view 类型族，本仓钉 13.2）、`erf`（归刀 15）、
  view 类型族与 TMA、`loop` / `break`（清点下来 leetgpu 没有一道题需要，见刀单）。
  两个操作都只在 i32 缓冲上有客户：`addf` 模式的浮点原子加机制齐了，但射程内没有题需要它，
  而一个没有客户的模式在这棵树上等于没有被测过（刀 13 的区域参数顺序就是这么错了两刀半的）。

- **刀 15 加了什么、没加什么**：**一个 opcode 也没加**。Tile IR 的一百个操作里没有 `erf`，
  `ct` 里也没有，而 leetgpu 65 是拿 `torch.erf` 写的。所以 `tileir/dev.erf` 是一段
  **组合**：Abramowitz & Stegun《Handbook of Mathematical Functions》7.1.26 的五项有理式
  乘 `exp(-x^2)`，负半轴走奇对称 `erf(-x) = -erf(x)`（一个 `select`）。用到的操作
  `absf / mulf / addf / divf / negf / exp / subf / cmpf / select` 全部是刀 7a 与 7b 就有的。
  这是这棵树上**唯一一个不是「设备做什么的拼写」而是「近似」的公开函数**，它的误差
  1.5e-7 是有出处的常数而不是实现细节，所以写进了 doc 注释，也被层 2 量出来钉住
  （本机实测 1.380e-7，§6.6）。**仍然没有**：view 类型族与 TMA、`loop` / `break`
  （清点下来 leetgpu 没有一道题需要，见刀单）、`atomic_red_view_tko`（0x75，要 13.3）。

### 5.3 谁把它变成 Tile IR、何时

- **谁**：`packages/tileir`（纯 Dawn 源码包，与 `packages/inflate` 同类）。它声明 `Dev`、
  `Tile[D] / Param[D]`、记录 handler、`TileProg`、文本渲染器、字节码写入器。不进 std：
  它不需要 intrinsic（只有 std 能名 intrinsic，`checker.dawn:1801`），而且包可以有自己的
  版本与 `dawn.toml`，Tile IR 字节码版本钉在包常量里（§6.3）。`std/gpu` 只认 `Bytes`
  与 kernel 名，不认识 `TileProg`，两边解耦。
- **何时**：宿主运行期，`launch` 前一次、按 kernel 名缓存。comptime 折叠是期权，前提是
  `ceval` 能跑 `with handle`，不在本计划内。
- **产物**：字节码是终态，文本是 golden 与 spike。

**刀 3 落地的形状**（`packages/tileir/src/lower.dawn`、`bytecode.dawn`）：

- `lower(prog: TileProg) -> Kernel` 把记录降成一张线性指令表：`Instr` 是 Tile IR 的一条操作
  （`MakeTok / BlockIds / ConstI32 / MulInt / AddInt / Reshape / Broadcast / Iota / Offset /
  LoadPtr / StorePtr / AddFloat / Ret`），值按定义序从 0 密集编号，操作数是 `Arg(pos)`（入口参数）
  或 `Val(id)`。指针梯子、去重、SSA 重编全在这里，渲染器与写入器各只是「一条 `Instr` 一种拼法」，
  不再各自决定发什么。抽出这一层时文本 golden 逐字节未动，这是纯重构的证据。
- `encode(prog) -> Bytes` 写 `cuda-tile` 字节码：头（magic + 13.2）、Func / Constant / Type /
  String 四个 section、结束字节。只编码指令表装得下的东西：内存操作 `weak`、无 mask、带 token
  操作数；`addf` 为 `rounding<nearest_even>`、不 flush-to-zero；整数操作 `overflow` none；tile 为
  0 或 1 阶。不写 debug section（函数位置索引 0 = unknown），不写 entry 的 optimization_hints
  （`tileiras --gpu-name` 已给了架构）。版本常量 `BYTECODE_MAJOR / BYTECODE_MINOR` 钉在包里。
- 格式的权威来源是 `NVIDIA/cuda-tile` 仓库（commit `be0889cd`，2026-09）的
  `lib/Bytecode/Writer/BytecodeWriter.cpp`、`Reader/BytecodeReader.cpp`、三张冻结的编号表
  （`BytecodeOpcodes.td` / `BytecodeTypeOpcodes.td` / `BytecodeAttrOpcodes.td`）与生成逐操作
  布局的 `tools/cuda-tile-tblgen/BytecodeGen.cpp`（结果类型 → 可选字段的 flags 位域 → 属性 →
  操作数 → 区域；flags 位按版本分组、组内先属性后操作数）。cuTile.jl（`5717de1d`）的
  `src/bytecode/{writer,encodings,types}.jl` 是同一格式的独立实现，用作对照；它总写 debug section、
  并把 i1 / i32 预注册在类型表 0 / 1 位，本实现按首用序注册且不写 debug section，两种形态 reader
  都收。
### 5.4 子集编译（期权，只记录）

子集 = 「`eff == EPure` 或只含 `!Dev`、一阶、单态、标量只有 Int / Float / Bool、容器只有
`Param`、控制流只有 Core 三种」；kernel 由 `gpu_launch` 的 `CFnRef` 点名而不加声明标记；
发射器 `selfhost/src/tile/emit_tile.dawn` 吃 Core，按名拒绝其它节点；SSA 构造、跨层 break、
循环内 return 的三合一改写是主体。与 §5.1 的兼容点：kernel 体若只用 `Dev` 操作，两条路线
吃的是同一个函数，这是 D1(c) 期权的形状。

## 6. 工具链与 CI

### 6.1 `tileiras`：能进 CI，钉法照 wasi-sdk（刀 3 实测）

- 钉 `nvidia-cuda-tileiras==13.3.36`（manylinux2014 x86_64 wheel 37,050,964 字节，
  sha256 `9221618a…8f00eca`，与 PyPI JSON API 给的一致）。**`--no-deps` 单装跑不起来**：它对每个
  输入（含空模块）都答 `error: failed to compile Tile IR program`；逐个文件移除实测，它在运行时要
  旁边有 `libnvvm.so.4`（`nvidia-nvvm==13.3.73`，69 MB）与 `ptxas`（`nvidia-cuda-nvcc==13.3.73`，
  44 MB），第三个声明的依赖 `nvidia-nvjitlink` 与 libdevice 都不需要。三个 wheel 的版本与 sha256
  记在 `scripts/tile-golden/toolchain.txt`，`install-tileiras.sh` 按精确版本下载、`sha256sum -c`、
  再 `--no-index --no-deps` 装进一个 venv（wasi-sdk 那步的规矩：校验和不与文件同源）。
  二进制只链 libc / libm / libpthread（`ldd`），无 CUDA 驱动依赖，`nvidia-smi` 不存在也能跑。
- **版本区间实测**：`tileiras --list-versions` 答 13.1 / 13.2 / 13.3；同一 vadd 写成三个版本号，
  三份都被 `--gpu-name sm_86` 接受且 cubin 逐字节相同（8320 字节，ELF 内 `FUNC GLOBAL vadd`
  512 字节 SASS）；13.4 被拒 `unsupported Tile IR bytecode version: 13.4`。钉 13.2：cuTile.jl 的
  兼容表说 Ampere / Ada 的最低字节码是 13.2（`launch.jl` 的 `tile_ir_requirement`）。
- **许可已读**（wheel 内 `License.txt`，NVIDIA SLA）：授权是「安装并使用 SDK」，开发者工具
  「仅供内部使用」除非另标可分发；CI 上是从 PyPI 安装使用、不再分发，落在授权内。这是本文的判断，
  不是律师的；若日后不许，层 1 退回本机，见 §8。
- `cuda-tile-translate` 仍不在 pip、未构建。刀 3 不再需要它做 round-trip：`tileiras` 内含
  `cuda-tile` 的 bytecode reader 与 MLIR verifier，拒绝时给出字节偏移与 op 名（§6.2 的变异体
  报文），比一个只会打印文本的翻译器说得更多。CUDA 13.4 起 wheel 旁会有 `tileirdisasm`
  （cuTile.jl 已接），升钉时可把它接进 run.sh 做文本对拍。

### 6.2 三层门

| 层 | 每次 push | 工具 | 抓什么 | 抓不到什么 |
|----|-----------|------|--------|-----------|
| 0 文本 golden | 是 | 无 | 记录 handler 与渲染器改了没 | 发的对不对 |
| 1 字节码编译 | 是（刀 3 起；今天是 `tile-golden-1 / tile-golden-2 / tile-golden-3` 三片） | `tileiras --gpu-name sm_86` | 编码错、类型错、不支持的 op | 算的对不对 |
| 2 执行对拍 | 否，本机 | 3080 加驱动不低于 580 | 算的对不对（逐位与容差两档）；刀 16 起对比的单位可以是一**串** launch 而不是一次，刀 17 把这串的价钱压到「一道题一个 kernel」 | 其它架构 |

层 0 golden 放 `scripts/tile-golden/*.mlir` 与 `*.tilebc`（字节码也钉，两后端逐字节），确定性
规则照 `coredump.dawn`（SSA 号按首现重编）。层 1 是同一个 `run.sh` 的 `assemble` 步：对每个
`.tilebc` golden 跑 `tileiras --gpu-name sm_86`，退出码即判词，产物须是 ELF。三个写入器变异体
证明这一层有信息量（文本 golden 看不见它们，字节码 golden 只能说「变了」、一次 `--record` 就洗白）：

| 变异体 | 改哪 | `tileiras` 的原话 |
|--------|------|-------------------|
| `make-token-as-iota` | `OP_MAKE_TOKEN` 0x44 → 0x3A | `'cuda_tile.iota' op result #0 must be tile of i1 or i8 or i16 or i32 or i64 values, but got '!cuda_tile.token'` |
| `store-token-unwritten` | store 仍置 token 位、不再写 token 操作数 | `error at offset 84: operand index 92 out of bounds (size=27) for token segment, element 0`（92 = 下一条 `return` 的 opcode） |
| `f64-tag-as-i64` | 类型表 f64 → tag 4 | `'cuda_tile.addf' op operand #0 must be tile of f16 or bf16 or f32 or f64 values, but got '!cuda_tile.tile<128xi64>'` |

阳性对照先于接受：接受之前先证明它会拒（坏 magic → `input does not correspond to Tile IR
bytecode`；截断 → `section length 4 exceeds remaining bytecode data`；未分配 opcode 0x7F →
`unsupported opcode 127 for bytecode version 13.2`）。刀 5 又加三个（`sum` 上）：
`loop-token-not-carried` 与 `region-stack-pop` 是 handler 变异体，降低时按名拒绝、不出文本；
`for-results-not-rolled-back` 是写入器变异体，文本不动、字节同长、`tileiras` 答
`operand index 39 out of bounds (size=25) for operand 1`。层 1 还多查每个 cubin 的符号表里有
`GLOBAL FUNC <kernel>`（python 直接读 ELF64，不依赖 binutils）。

**刀 7b 补了层 1 的一个洞：退出码不是它的全部判词。** `tileiras` 会一边退出 0、一边把拒绝
写在标准错误上：实测 `tanh` 带 `rounding<nearest_even>`（f64 的 `tanh` 不接受这个模式）照样
写出 cubin、退出 0，同时打印
`'cuda_tile.tanh' op invalid rounding mode specified, expect one of [approx, full]`。
只读退出码的门会把它当绿。`run.sh` 的 `assemble` 因此改成「退出码为 0 **且** 输出里没有
`^error:`」，`tile-gpu-diff` 那边的 `assemble_golden` 同改。这是「门的绿没有信息量」的又一个
实例：这一格从刀 3 起一直是绿的，而它从来没看过 stderr。今天三层各有：层 0 七十七个
kernel 的文本与字节码 golden，两后端逐字节；层 1 CI 每 push（三个分片）；层 2 有脚本、台账与 CI 门（§6.4），
本机驱动升到 616.56 之后台账末行是 `pass`，「算的对不对」这一格从刀 7a 起有答案了。
（刀 4 到刀 6 期间这里写的是「本机驱动 560.94 装不进 cubin，台账第一行记的是 `blocked`」；
那两行 `blocked` 留在台账的历史里，是那个装载器答过的话。）

### 6.3 版本钉法（刀 3 实况）

三个数同批改：`tileiras` 的版本与三个 wheel 的 sha256、字节码版本（`packages/tileir/src/bytecode.dawn`
的 `BYTECODE_MAJOR / BYTECODE_MINOR`，写入头）、本机台账里的驱动版本。全部记在
`scripts/tile-golden/toolchain.txt`（`bytecode 13.2` / `tileiras 13.3.36` / `gpu-name sm_86` /
三行 `wheel … sha256=…` / `driver 560.94`），而且不是散文：`install-tileiras.sh` 只认它的 `wheel` 行，
`run.sh` 拿 `kernels --bytecode-version` 对 `bytecode` 行、拿 `tileiras --version` 对 `tileiras` 行，
任一不符直接红；刀 4 起 `driver` 行也是机器读的：`tile-gpu-diff/run.sh` 在它与 `nvidia-smi` 不符时
拒绝写台账，`--check` 要求它等于台账末行的驱动（§6.4）。与计划稿的一处出入：wheel 的 sha256 不写在 `gates.yml` 里而写在这个文件里，
因为本机装与 CI 装要读同一份。`gatemap.py` 对它的判词是 `exact`（两个 tile-golden 分片各自的两步都以它为输入），
对 `packages/tileir/src/bytecode.dawn` 是 `coarse`（`run.sh` 点名 `packages/tileir`）；
计划稿想要的「coupled」不必另加规则，run.sh 的交叉校验就是那条耦合的机器形态。

### 6.4 本机对拍脚本与台账（D4 的机器强制点，刀 4 已落地）

**脚本** `scripts/tile-gpu-diff/run.sh`（本机一次约 26 s，含两次 tileiras、一次 JVM 运行、
四次原生构建）：用钉版本的 `tileiras` 把 `scripts/tile-golden/vadd.tilebc` 与 `vadd_bf16.tilebc` 汇编成
两个 cubin；先在 JVM 上跑 `vadd_diff.dawn`，要求真 handler 在第一个操作就答 `gpu.unsupported_backend`；
再原生跑它：**四组 f64 输入**（128 / 1024 / 128 / 4096 个元素，含负数、百万量级、`-0.0`、`1e300`、
`1e-300`，走 `vadd`）加**三组 bf16 输入**（刀 6：128 个「十分之几对二分之几」、1024 个随机 Float 对
随机位模式、**全部 65536 个位模式按序对随机 Float**，走 `vadd_bf16`；每组都故意含格点外的 Float），
每组在 `with_gpu_real` 与 `with_gpu_fake` 下各走一遍 alloc → upload → 回读两个输入 → launch → sync →
download，逐段打印设备答的 kind；回读与该格式会持有的值比（`round_to`），结果按 `to_string` 的整段
渲染比（分得清 `-0.0` 与 NaN，即逐位）。末行判词三种：`pass`（每组逐位相同）、
`blocked:<kind>@<stage>`（驱动在该段拒绝，各组一致）、`fail`（设备答了但数字不同，或内存回读就
不同）。计划稿里的「容差档」本版没有客体（vadd 是逐位档），随 matmul 一起来。三个变异体内置在脚本里
（§7 刀 4 行的两个，加刀 6 的 `pack-truncates`：打包层不再先 `round_bf16`、让 `bf16_bits` 截断，三组
bf16 的回读全部 `differ:roundtrip`、四组 f64 不动；与 `download-short` 同层，所以在 560.94 上就要红）。

**台账** `scripts/tile-gpu-diff/ledger.txt`，脚本追加、不手写，一行
`<commit> <date> <driver> <tileiras> <gpu-name> <result> [# note]`。commit 是 HEAD 的 12 位；tile
路径有未提交改动时拒绝写（那一行会指着一棵没跑过的树），`toolchain.txt` 的 `driver` 行与
`nvidia-smi` 不符时也拒绝（先改那一行、提交、再跑，于是台账提交只加一行）。第一行：

```
ad03cbb02b18 2026-09-02 560.94 13.3.36 sm_86 blocked:cuda.CUDA_ERROR_INVALID_IMAGE@launch # cuModuleLoadData: CUresult 200 (CUDA_ERROR_INVALID_IMAGE)
```

**CI 门** `run.sh --check`，`tile-golden-1` 的倒数第二步（几条 git 命令，亚秒；checkout 改为 `fetch-depth: 0`，
祖先判定要历史）：台账末行要能解析；commit 存在且是 HEAD 的祖先；日期是过去的一天；结果是 `pass` 或
`blocked:...`（`fail` 可以留在历史里，不能在末行）；自该 commit 起 tile 路径没变，tile 路径 =
`packages/tileir`、`std/gpu.dawn`、`scripts/tile-golden`、`scripts/tile-gpu-diff`（台账本身除外）与
`runtime/c/dawn_rt.c` 里 `DAWN_RT_GPU_BEGIN / END` 之间那一段（运行时其它部分不是 tile 路径，
两个版本各取该段比较，标记丢了算改了）；`toolchain.txt` 的 `driver` 与 `tileiras` 行等于台账末行。
`std/narrow.dawn` 自刀 6 起在 tile 路径里（假设备用它舍入、打包用它编码）；
「blocked 是允许状态」是新加的语义，因为一台装不进 cubin 的机器的诚实记录比没有记录有用，
门拒绝的是沉默。负控：把末行 commit 改成一个非祖先（另一分支的 sha），`--check` 红，原文见刀 4 报告。

**560.94 上的实测**（`cuDriverGetVersion` 答 12060）：`cuInit` / `cuDeviceGet` / `cuCtxCreate_v2` /
`cuMemAlloc_v2` / `cuMemcpyHtoD_v2` / `cuMemcpyDtoH_v2` 全部 `CUDA_SUCCESS`，四组输入的内存回读逐位
相同；`cuModuleLoadData` 对 `tileiras 13.3.36 --gpu-name sm_86` 出的 cubin 答
**`CUDA_ERROR_INVALID_IMAGE`（200）**。cubin 的 ELF 头 `EI_ABIVERSION = 8`（CUDA 13 的 ELF ABI），
12.x 驱动的装载器不认，所以拦在装载而不是启动，与 cuTile 文档「r580 起」一致。ASan + LSan 下同一条
路径（`ASAN_OPTIONS=protect_shadow_gap=0`，否则 `cuMemAlloc` 在 ASan 的影子内存下答 OUT_OF_MEMORY；
`leak:libcuda.so` 压掉驱动自己的两处内部分配）本仓运行时零漏，`dlclose` 四次安装各一次无事。

**刀 6 在 560.94 上的实况，与一个新发现**：bf16 的三组与 f64 的四组停在同一处，launch 之前的
alloc（2 字节一元素）、`Bytes` 上传、回读（含 65536 个位模式的整段打包往返与格点外 Float 的舍入）
全部 `same`。但刀 4 记录的「`cuModuleLoadData` 答 `CUDA_ERROR_INVALID_IMAGE`」**只是那台机器当天
的堆布局**：刀 6 把对拍程序改成七组、std 的 handler 换了形状之后，同一个驱动在第三次装模块时
在 `cuModuleLoadData` 内部**向空指针写**（ASan 报 `SEGV on unknown address 0xb`，栈全在 libcuda
里；同一份 cubin、同一 rc = 2、同一字节，`-O0`/`-O2` 崩、`-O1` 不崩，加一句 `fprintf` 不崩，把
image 拷到页对齐的缓冲有时不崩，old 程序配新 std 崩、配 main 的 std 不崩：纯堆布局轮盘，与
dlclose 无关，也与 image 后面的字节无关，都逐一试过）。一个 12.x 的装载器读 CUDA 13 的 ELF
（EI_ABIVERSION = 8）没有干净的拒绝路径，所以刀 6 让运行时**先看再问**：`dawn_gpu_open` 多取
`cuDriverGetVersion`，`gpu_load_module_host` 读 image 的 ELF ABI 版本字节，ABI ≥ 8 而驱动 API
< 13000 就答 `gpu.driver_too_old`（消息带两个数字），不把字节交给装载器。台账末行因此从
`blocked:cuda.CUDA_ERROR_INVALID_IMAGE@launch` 变成 `blocked:gpu.driver_too_old@launch`；刀 4
那一行留在历史里，是这个装载器答过的话。`pack-truncates` 与 `download-short` 在这台机器上都已红过。

**升驱动后要做的事**：Windows 侧把 NVIDIA 驱动升到 r580 以上（WSL2 的 `libcuda.so.1` 随宿主驱动来，
WSL 内不装驱动），`nvidia-smi` 确认版本后把 `toolchain.txt` 的 `driver` 行改成该版本、提交，跑
`./scripts/tile-gpu-diff/run.sh`，提交它追加的台账行。预期末行变 `pass`：f64 四组与 bf16 三组全部
`identical`，其中第三组 bf16 就是 §7 刀 6 行的断言「设备 bf16 `addf` 与 `narrow.round_bf16(f64 加)`
对全部 65536 个 bf16 值对加随机对逐位一致」；`grid-zero` 变异体从 SKIP 变成 PASS。若 f64 组
`identical` 而某组 bf16 `differ:result`，那是 §8 墙一的剩余风险成真：该代硬件的 bf16 `addf` 不守
nearest_even，处置是把 bf16 降到容差档并在 §3.2 的表里改那一格。若 f64 组就 `differ:result`，
那是这条线的第一个真问题。

### 6.5 墙钟

新 job `tile` 并行，不 `needs:` 任何长杆（刀 3 实测：wheel 热缓存 8 s、冷约 25 s；`run.sh`
本机 40 s，含一次 native 构建、两个 kernel 两后端两种输出、七次 `tileiras`、五个变异体；
加 checkout 与工具链动作按 45 s 估，planning value 110 s，翻倍 220 s，`timeout-minutes: 11`，
远在 run-pole 660 s 之下）。刀 5 实测 `run.sh` 本机 100 s（三个 kernel、十一次 `tileiras`、
八个变异体各一次 native 构建），planning value 170 s，翻倍 340 s，`timeout-minutes: 17`，
仍在 run-pole 之下。刀 6 实测 `run.sh` 本机 91 s（四个 kernel、十四次 `tileiras`、
十个变异体；比刀 5 的 100 s 快是机器当天的事，不是脚本变轻），仍在 170 s 的 planning value 之内，
`tile` job 的 budget 不动。`dawn test --stdlib` 多了 65536 次编解码往返与 65536 对假设备
vadd，本机 12.7 s → 13.5 s，`test` job 的 budget 不动。刀 7a 实测：同一台机器上
`run.sh` 122 s（改动前，四个 kernel 十个变异体）→ 129 s（改动后，十个 kernel 二十次 `tileiras`
十一个变异体）。多出来的只有 7 s，因为墙钟的大头是每个变异体一次 native 构建，而这一刀只加了
一个变异体（两次测量前后相连，机器状态相同；换一个时段整段可以到 165 s，所以有意义的是这个
差值而不是绝对值）；仍在 170 s 的 planning value 之内，`tile` job 的 budget 不动。`tile-gpu-diff/run.sh` 26 s → 46 s
（多一个 native 构建、六个 kernel 的真机对拍与 `mask-all-true` 变异体的六次汇编），它只在本机跑，
CI 上仍只有亚秒的 `--check`。`scripts/leetgpu-diff/check.py` 与它的 `--self-test` 各亚秒。刀 2 时挂在 `test` job 里的 tile-golden 步随之搬走，`test` 的 budget
回到 323 s。刀 1 与刀 0 只加 std 测试，落在 `test` job 的 `dawn test --stdlib` 步，秒级。

**刀 7b 的实测与一次预算调整**：同一台机器上、前后相连地成对测量（绝对值随机器当天的负载
浮动，有意义的是差值）：`tile-golden/run.sh` **123 s（改动前，十个 kernel、二十次 `tileiras`、
十一个变异体）→ 188 s（改动后，二十三个 kernel、四十六次 `tileiras`、同样十一个变异体）**，
**多 65 s / +53%**。变异体一个没加，多出来的全是十三个新 kernel 的两后端两种输出与二十六次
`tileiras`。也就是说墙钟的结构变了：刀 7a 时大头是「每个变异体一次 native 构建」，现在
kernel 循环已经和它同量级。

按同一比例，`tile` job 的 planning value 从 170 s 抬到 **260 s**（45 s checkout 加工具链
+ 25 s wheel + 190 s run.sh），翻倍给冷跑的 runner 是 **520 s**，`timeout-minutes` 按惯例
取三倍，从 17 抬到 **26**。**run-pole 660 s 没有被越过，但余量从 320 s 缩到 140 s**。
所以这里把处置先写下来：**下一刀再让 kernel 数翻一番，就分片，不再抬预算**。分片的形状是
`mutants` 那 19 片的形状：`tile` job 按 `kernels=()` 切成 N 片，每片跑自己那一段的
trace / golden / bytecode / assemble；十一个变异体那部分不分片，它们已经是墙钟的小头，
而且每一个都要一次完整的 native 构建，切开只会重复构建。

`tile-gpu-diff/run.sh` **40 s → 91 s**（同样成对测量：多一个 native 构建、十三个 kernel 的
真机对拍、`reduce-identity-wrong` 的十三次汇编与一次对拍、`softmax-no-max-subtract` 的一次
汇编与一次对拍）。它只在本机跑，CI 上仍只有亚秒的 `--check`。`scripts/leetgpu-diff/check.py`
与它的 `--self-test` 仍各亚秒。`dawn test --stdlib` 多了三个级数函数与它们的五个测试，本机
秒级，`test` job 的 budget 不动。

**刀 8 的实测：预算不动，也不分片。** 同一台机器上成对测量了两次、两个方向：
`tile-golden/run.sh` **227 s（23 个 kernel）→ 233 s（30 个）**，反过来再测一次
**222 s（30 个）→ 201 s（23 个）**。差值 +6 s 与 +21 s，机器当天的噪声就有 ±25 s，
所以能说的是「七个 kernel 不到 +10%」。**kernel 数从 23 涨到 30 是 +30%，不是 §6.5 上面
那句话设的「翻一番」触发条件**，所以 planning value 与 `timeout-minutes` 都不动。

分片的处置本身仍然有效（按 `kernels=()` 切片，形状照 `mutants` 那 19 片），但这里补一条
刀 7b 时没写的约束：**本 workflow 现在是 24 个 job，而本账号的并发上限是 20**
（`gates.yml` 的 `mutants.strategy.matrix` 旁边记着这笔账）。再切一片 `tile` 出来只会排队，
不会缩短墙钟。所以真到要分片的那一刀，得连着并发上限一起算，而不是只看 `tile` 自己。

`tile-gpu-diff/run.sh` **91 s → 99 s**（多一个 native 构建、七个 kernel 的真机对拍、
`grid-y-ignored` 的一次 C 运行时重编与一次对拍、`mma-acc-not-carried` 的一次汇编与一次
对拍）。它只在本机跑，CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 多了七个参考实现，
没有新测试，秒级不变。

**刀 9 的实测：预算不动，也不分片。** 同一台机器上前后相连地成对测量
`tile-golden/run.sh`：**241 s（30 个 kernel）→ 263 s（39 个）**，差值 **+22 s / +9%**。
变异体一条也没往这条脚本里加（新的三个都在 `tile-gpu-diff/run.sh`），多出来的全是九个新
kernel 的两后端两种输出与十八次 `tileiras`。kernel 数从 30 涨到 39 是 +30%，仍不是 §6.5
上面那句话设的「翻一番」触发条件，planning value 与 `timeout-minutes` 都不动；`tile` job
的步骤名从「30 kernels」改成「39 kernels」。

`tile-gpu-diff/run.sh` **99 s → 129 s**（多一个 native 构建、九个 kernel 的真机对拍，
以及三个新变异体：`stride-row-major-swapped` 与 `halo-one-lane-short` 各一次汇编一次对拍、
`ladder-strides-reversed` 九次汇编一次对拍）。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 多了八个参考实现与一个测试，秒级不变。

**刀 10 的实测：仍然不分片。** 同一台机器、同一棵树上成对测量 `tile-golden/run.sh`，
两次运行的唯一差别是 `kernels=()` 里那四个名字：**260 s（39 个 kernel）→ 279 s（43 个）**，
差值 **+19 s / +7%**。四个 kernel 是 +10%，离 §6.5 上面那句话设的「翻一番」还很远，
planning value 与 `timeout-minutes` 都不动。这之后又加了第十二个变异体
（`ftoi-rounds-instead-of-truncates`，它本来是按层 2 写的、被 `tileiras` 收走了，见 §6.6），
整条脚本落到 **299 s**：一个变异体 +20 s，与刀 3 以来每个写入器变异体的量级一样。

`tile-gpu-diff/run.sh` **129 s → 154 s**（多一个 native 构建、四个 kernel 的真机对拍，
以及两个新变异体，各四次汇编一次对拍）。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 多了四个参考实现与三个测试，秒级不变。

**分片：`tile` 拆成 `tile-golden-1 / tile-golden-2`（刀 12 之前的前置工作）。** 刀 11 之后 CI 实测
`tile` job **609 s**（run 33748678694，其中 `run.sh` 那一步 567 s），已经越过它自己声明的 520 s
planning value，距 run-pole 660 s 只剩 51 s。按刀 9 / 10 / 11 的斜率外推每刀约 +88 s，刀 12 就会到
约 710 s。所以这一刀先分片，不再抬预算。

**为什么不按上面写的「按 `kernels=()` 切」。** 刀 7b 写下的处置是「按 kernel 切片，变异体那部分不分片，
它们已经是墙钟的小头」。本机相位实测把后半句推翻了：51 个 kernel 的循环 **204 s**（几乎全是 102 次 JVM
启动，原生二进制跑完 51 个 kernel 只要 0.3 s、51 次 `tileiras` 一共 3.3 s），12 个变异体 **175 s**
（每个一次原生重建，均 9.25 s）。两半没有哪一半单独主导，而且 kernel 那半涨得更快（新 kernel 每个约 8 s，
新变异体每个约 21 s）。只切变异体等于没切，只切 kernel 会把 175 s 那半整块留给一个 job。

**切法：一张混合 matrix。** `scripts/tile-golden/matrix.txt` 一行一个工作项，前 51 行是 kernel 名、
后 12 行是变异体名，按运行顺序；`run.sh --shard I/N` 复用仓库已有的 `scripts/mutant-coverage/shard.sh`，
round-robin 取模而不是切连续块，因为工作项成本相差五倍以上（`reverse` 一个抵五个普通 kernel），
连续块会把贵的凑在一片里。启动时把可执行列表与 matrix.txt 双向 `cmp`，运行时 `run_item` 再把实际
运行顺序钉到同一张表上，于是加了 kernel 不加 matrix 行、或者搬动一个变异体块，都当场红。

**分片切不到判词。** 一个 kernel 的四次运行、两份 golden 与一次汇编都在同一片里做完；变异体比对的是
磁盘上已入库的 golden，不是本片 kernel 循环的产物，所以一个变异体和它点名的干净 kernel 落在不同片上，
合取仍然成立。分片唯一新增的失败路径是 shard.sh 头注写死的那条：某片静默少跑了工作项，PASS 行长得
一模一样、也照样退出 0。由每片记下自己跑了什么、`mutant-shards-complete` 把并集对到 matrix.txt 兜住；
`tile-golden-1 / tile-golden-2` 加进了它的 `needs:`（gates.yml 头注给它的那条唯一 `needs:` 豁免）。

**本机实测（同一台机器、同一棵树、同一个 tileiras，机器上没有别的活）**：不分片 **387 s**，两片
**186 s** 与 **175 s**。（同两片还有一对 254 s / 299 s 的观测，那次机器上并行跑着另一个 job，不采信：
runner 不与人共享。）两片 PASS 行的并集与不分片那次**逐行相同**（218 行），
十二条变异体的 PASS 行各只出现一次；`check.py --coverage-dir` 收下并集。CI 每片的 planning value =
本机片值 + 70 s（checkout 与工具链 45 s、wheel 25 s），翻倍写进 budget 行；这是 planning value
不是观测，第一次真实的分片 run 落地后要用观测改写它。

**转 N = 3 的触发条件写进了 job 注释**：任一片自己的观测过 550 s 就再分，而不是重述预算（550 s 翻倍
已经过了 660 s 的 pole）。按每刀每片约 +50 s 外推，那是两刀之后的事。反过来说现在不多切：本 workflow
一次 run 是 **36 个 job**（2026-09-03 起，含 ci.yml 自己的 `secrets`）、账号并发上限 20，而 `tile`
从来不是 run 的长杆（长杆是 native-diff，783 到 1119 s；它同日拆成了四片，每片 267 到 391 s 的
planning value），第三片只会排队，买不到墙钟。（2026-09-04：std 剪枝刀落地后 native-diff 四片
降到 195 / 140 / 166 / 126 s，长杆改由 builtin-type-1 顶着（521 s），整轮 span 883 s 降到
715 s；`tile` 仍然不是长杆，这一段的结论不变。）

**刀 12 的实测：预算重述一次，仍不再分片。** 同一台机器、同一棵树上前后相连地成对测量
不分片的 `tile-golden/run.sh`：**386 s（51 个 kernel）→ 423 s（55 个）**，差值 **+37 s / +10%**，
一个 kernel 约 9 s，与刀 9 / 10 / 11 的斜率一致。变异体一条也没往这条脚本里加——这一刀零新
opcode，gather 发的是 `offset` + `load_ptr`，与普通 load 逐字节同族，层 1 没有新的字节形状可拒，
新的三条负控全在 `tile-gpu-diff`。

两片在最终那棵树上、机器上没有别的活时是 **204 s** 与 **193 s**，同一棵树不分片再测一次是
**347 s**（上面那对 386 / 423 是背靠背的成对测量，取的是差值不是绝对值）。同一对分片在另一批测量里
（机器上并行跑着别的活）读到 274 s 与 228 s，不采信，理由与刀 11 那条注记相同：runner 不与人
共享。**绝对值的噪声（±40%）比这一刀的增量还大**，所以有意义的是不分片那一对背靠背的差值。

按 `gates.yml` 一直用的算法（本机片值 + 70 s 的 checkout 与 wheel，再翻倍给冷 runner），两片的
planning value 从 512 s / 490 s 抬到 **548 s / 526 s**，`timeout-minutes` 随之 26 → 28 与 25 → 27。
这是**重述**而不是新增预算：CI 实测（run 33763512，`fffe98f8`）两片是 340 s 与 348 s，对 512 / 490
的比值约 0.66；按本机涨幅缩放，观测预计落在 373 s 与 384 s，离上面写下的 N = 3 触发线（任一片
自己的**观测**过 550 s）还有两刀。

`tile-gpu-diff/run.sh` **180 s → 205 s**（多一个 native 构建、四个 kernel 的真机对拍，以及三个
新变异体：`gather-mask-dropped` 四次汇编一次对拍，另外两条各一次汇编一次对拍）。它只在本机跑，
CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 多了四个参考实现与一个测试（137 → 138），
`dawn test packages/tileir` 多了五个测试（77 → 82），都是秒级。

**刀 14 的实测：只抬一片的预算，仍不分片。** 同一台机器、同一个 tileiras、机器上没有别的活，
在基线树（`a7d2479e`，刀 13）与本树上背靠背地各测三次：不分片 **402 s → 474 s**
（+72 s / +18%），第一片 **208 s → 244 s**（+36 s / +17%），第二片 **216 s → 214 s**（持平）。
这一刀把 kernel 从 62 加到 64、变异体从 13 加到 15，round-robin 恰好给每片各一个，所以
一片应涨约 9 s 的 kernel 加约 21 s 的变异体重建，第一片读到的正是这个数。第二片读到的是**下降**，
那是机器噪声：这一节每一条注记都测过噪声比单刀的增量宽，所以采信的是成对差值而不是绝对水平。

按 `gates.yml` 一直用的算法（本机片值 + 70 s 的 checkout 与 wheel，再翻倍给冷 runner），
第一片是 314 s 翻倍 = **628 s**，越过它原来写的 600 s，于是重述，`timeout-minutes` 30 → 32；
第二片是 284 s 翻倍 = 568 s，**低于**它已经写着的 588 s，所以那一行不动：预算是上限不是目标，
往下重述只会在下一刀再抬一次。CI 预计：run 33763512（`fffe98f8`）两片观测 340 s / 348 s，
刀 13 把它们缩放到 383 s / 404 s，再按本刀的本机涨幅缩放一次是约 **448 s 与 400 s**，
离 N = 3 的触发线（任一片自己的**观测**过 550 s）还没到，本刀不分片。第一片现在离触发线
大约还有一刀这样大小的距离。

`tile-gpu-diff/run.sh` 在本树上 **242 s**（刀 13 记的是 198 s，但那次机器是空的，本次有另一棵
基线树在同时建工具链），多的是一个 native 构建、两个 kernel 的真机对拍、控制语料的第二次运行，
以及两个新变异体。它只在本机跑，CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 多了两个参考
实现与一个测试（143 → 144），`dawn test packages/tileir` 多了六个测试（82 → 88），都是秒级。

**刀 15 的实测：这一刀的墙钟量不出来，能量出来的是每一项的成本。** 这一天机器上一直有另一个
agent 在建东西（load average 7 到 11），成对测量做了两轮、第二轮把顺序反过来（先本树后基线树），
结果自相矛盾：不分片一轮 **338.7 s → 418.7 s**（+80.0 s）、另一轮 **481.9 s → 488.3 s**
（+6.5 s）；分片一轮 **150.0 → 227.0** 与 **149.6 → 212.3**，另一轮 **238.5 → 346.7** 与
**242.1 → 287.1**。**两轮里分片的增量之和都大于同一轮不分片的增量**（139.6 s 对 80.0 s、
153.2 s 对 6.5 s），而两片的并集就是不分片，所以这不可能是真实增长，只能是噪声。

能量的是**每一项的成本**，因为 `--only` 把固定开销摊在一个 item 上：`erf_sweep` 16.70 s / 16.62 s、
`geglu` 17.03 s / 17.33 s，对照既有的逐元素 kernel `silu` 16.50 s / 16.84 s。**新 kernel 就是一个
普通 kernel 的价钱**，没有需要解释的异常；这一刀加两个 kernel、零个变异体，round-robin 给每片各一个。

于是 planning value 取最后一次量准的本机片值（244 s 与 214 s）加上本节自刀 12 起一直用的斜率
（每 kernel 约 9 s）：253 s 与 223 s。第一片 (253 + 70) × 2 = **646 s**，越过它写着的 628 s，
于是重述，`timeout-minutes` 32 → 33；第二片是 586 s，仍低于它写着的 588 s，不动。
**646 s 离 660 s 的 run-pole 只剩 14 s**：下一刀只要再给第一片加一个 kernel，就会被**上限**
而不是被观测触发线逼着分第三片。

`tile-gpu-diff/run.sh` 在本树上 **244 s**，多的是一个 native 构建、两个 kernel 的真机对拍、
控制语料的第二次运行，以及两个新变异体各跑两个语料。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 多了三个参考实现与两个测试（144 → 146），`dawn test packages/tileir` 一个没多
（88 → 88：`erf` 是组合，包里没有新机制可测，它的判词全在层 2）。

**刀 16 先分片再加东西，两个提交。** 分片是纯机械改动，加 kernel 是内容改动；混在一个提交里，
「哪一片变慢了」这个问题就不可回答（这条是刀 16 前研写下的，照办）。分片本身买不到墙钟：
本 workflow 一次 run 现在是 **36 个 job**（加上 ci.yml 自己的 `secrets` 是 37）、账号并发上限
20，第 36 个只会排在第一波后面；而 `tile` 从来不是 run 的长杆。它买的是**预算余量**——刀 15
留下第一片 646 s 的 planning value，距 660 s 的 run-pole 只剩 14 s，而斜率是每 kernel 约 18 s
的 planning value，所以下一刀只要给第一片加一个 kernel 就得抬 pole。抬 pole 正是 pole 存在
要拒绝的动作，分片是它逼出来的那一步。

**刀 16 的实测：两轮，其中不分片那一对又自相矛盾。** 这一天本机一直有另一个 agent 在建东西，
负载在 3 到 8 之间来回。92 个工作项（77 个 kernel + 15 个变异体），两轮读数：

| | 三片 | 不分片 |
|---|---|---|
| 第一轮（负载 6，rebase 前那棵树） | **197 / 189 / 177 s** | **494 s** |
| 第二轮（rebase 到 `c5ff0b7c` 之后；三片赶上机器空闲那段，不分片那次负载又回到 7） | **170 / 171 / 171 s** | **622 s** |

不分片的两次差 128 s，而且方向与三片相反：第一轮三片之和 563 s **大于**同轮不分片的 494 s
（合理，每片各付一次约 23 s 的固定开销），第二轮三片之和 512 s **远小于**同轮不分片的 622 s
（不可能，两者跑的是同一张表）。所以**不分片那一列这一天量不准**，可采信的是三片那一列，
而它给出的第二条信息比数字本身更有用：机器空下来之后三片是 **170 / 171 / 171 s**，
round-robin 把 92 个工作项分得**很平**，第一轮那 20 s 的离散是负载不是分片。

按 `gates.yml` 一直用的算法（本机片值 + 70 s 的 checkout 与 wheel，再翻倍给冷 runner），
三条预算行**全部重述**（N 变了，旧的两条按定义作废），取两轮里**较差**的那个读数——预算是
上限而不是目标：**534 s / 518 s / 494 s**，`timeout-minutes` 27 / 26 / 25。CI 预计：N = 2 时
最后一次记下的投影是 408 s 与 390 s（共 798 s 的分片时间），本刀十一个 kernel 把本机总量抬了
约五分之一，三片分它，落在约 **320 s / 310 s / 290 s**，离 N = 4 的触发线（任一片自己的**观测**
过 550 s）很远。

能量准的仍是**每一项的成本**（`--only` 把固定开销摊在一个 item 上，各测两次）：
`attn_scores` 14.72 / 14.74 s、`swiglu_proj` 14.67 / 14.16 s、`apsp_step` 14.21 / 14.55 s、
`matpow_step` 13.91 / 14.65 s，对照既有的二维 `mmaf` kernel `matmul` 14.60 / 15.79 s。
**新 kernel 就是一个普通 kernel 的价钱**，十一个也没有需要解释的异常。（绝对水平比刀 15 记的
16.5 s 低，那是另一天另一种负载；只有同一批里的相对值可采信。）

`tile-gpu-diff/run.sh` 本机 **242 s**（刀 15 记的是 244 s，也就是没动），多的是一个 native 构建、
十一个 kernel 的汇编、六条序列的真机对拍，以及**四条变异体乘六条序列共 24 次真机重跑**——
这一族的变异体不重建任何东西，改的是序列这份数据，所以它们比别的族便宜得多。它只在本机跑，
CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 与 `dawn test packages/tileir` 一个测试
都没多（146 → 146、88 → 88）：这一刀往包里加了零个机制，判词全在层 2。

**刀 17 的实测：七个 kernel，三条预算行照较差的那一轮重述。** 这一天机器上仍然有别的活
（负载 4 到 10），所以下面这两轮**只用来算预算，不与刀 16 的读数横比**。99 个工作项
（84 个 kernel + 15 个变异体）：

| | 三片 |
|---|---|
| 第一轮 | **196 / 187 / 178 s** |
| 第二轮 | **190 / 176 / 174 s** |

不分片跑了一次：**645 s**。它比同一天三片之和（561 s / 540 s）大 **84 s 以上**，方向与
刀 16 第二轮那次一样「不可能」——三片各付一次约 23 s 的固定开销，不分片本该更小才对。
连着两刀量到同一个反常，所以**不分片这一列在这台机器上就是量不准**，不采信、也不进预算，
记在这里只是为了下一个人不必再量第三次。

取每片较差的那个读数，照 `gates.yml` 一直用的算法（本机片值 + 70 s，翻倍给冷 runner）：
**532 s / 514 s / 496 s**，`timeout-minutes` 仍是 27 / 26 / 25。**三条里两条降了一条升了**，
升的是第三片（494 → 496 s）。这个方向与「加了七个 kernel」对不上，正说明**在这种负载下
片值本身就是噪声**：七个 kernel 按每 kernel 约 8 s 的本机斜率只值 56 s，摊到三片上每片
不到 20 s，比两轮之间的自然离散（第一片 196 与 190、第二片 187 与 176）大不了多少。
预算行仍然照规矩重述，因为预算是上限而不是估计。

CI 投影：刀 16 记的是 92 项时的 320 / 310 / 290 s，七个 kernel 每片加约 19 s，落在
**340 / 330 / 310 s**。**没有一片投影过 550 s，所以 N 不动。** 再说一次：N = 4 的触发线是
任一片自己的**观测**过 550 s，投影不触发任何事，本刀也没有分片。

`tile-gpu-diff/run.sh` 本机 **256 s**（同一天另一次 259 s；刀 16 记的是 242 s）。多的是七个 kernel 的汇编与
**四条变异体乘十二条序列共 48 次真机重跑**（刀 16 是 24 次）；这一族的变异体不重建任何
东西，所以 24 次重跑只值十几秒。`dawn test --stdlib` 与 `dawn test packages/tileir` 一个
测试都没多（146 → 146、88 → 88）：这一刀也往包里加了零个机制。

**刀 18 的实测：八个 kernel，三条预算行全部抬高。** 这一天机器上仍然有别的活（负载 2 到 6，
另一个 agent 从头到尾在做 native 构建），所以下面这一轮**只用来算预算，不与刀 17 的读数横比**。
107 个工作项（92 个 kernel + 15 个变异体），三片与不分片背靠背跑了一轮：

| | 三片 | 不分片 |
|---|---|---|
| 第一轮（负载 2 到 6，另一个 agent 在做 native 构建） | **228 / 227 / 231 s** | **560 s** |
| 第二轮（最终树，负载回到 3 到 4） | **203 / 200 / 202 s** | **574 s** |

**不分片这一列两轮都是「可能」的**，而且方向与刀 16 第二轮、刀 17 那次都相反：三片之和
686 s 与 605 s 都**大于**同轮不分片的 560 s 与 574 s，正是「每片各付一次固定开销」该有的
样子。刀 17 写下「这一列可以不必再量了」，本刀顺手又量了两次，两次都得到相反的方向。于是
这一列的结论要改成一句更弱也更准的话：**这台机器上不分片与三片之和的差是负载的函数，不是
分片的函数**，两个方向都出现过，所以哪一个方向都不能单独当证据用。预算仍然只看三片。

两轮里三片彼此都只差 3 到 4 s（228 / 227 / 231 与 203 / 200 / 202），是这条脚本分片以来
最平的两次；round-robin 把 107 个工作项分得很平这件事，刀 16 已经量过一次
（170 / 171 / 171），这里是第二、三次。

照 `gates.yml` 一直用的算法（本机片值 + 70 s 的 checkout 与 wheel，翻倍给冷 runner），
取两轮里**较差**的那一轮——预算是上限而不是目标——三条预算行重述为
**596 s / 594 s / 602 s**，`timeout-minutes` 30 / 30 / 31。**三条都涨**，与刀 17 那次
「两降一升」不同：八个 kernel 按每 kernel 约 8 s 的本机斜率值 64 s、摊到三片每片约 21 s，
而较差那一轮每片涨了 32 到 53 s、较好那一轮每片涨了 7 到 24 s——**两者的差就是机器的负载，
不是这一刀的内容**，第二轮那三个数才是这八个 kernel 的实际斜率。预算行仍然照较差的那一轮
重述；三条都仍在 660 s 的 run-pole 之下，余量最小的一条（第三片 602 s）还有 58 s。

CI 投影：run 33763512 观测到的 CI 与本机之比约 1.73，套到 228 / 227 / 231 s 上是
**395 / 393 / 400 s**。**没有一片投影过 550 s，所以 N 不动。** 再说一次：N = 4 的触发线是
任一片自己的**观测**过 550 s。

`tile-gpu-diff/run.sh` 本机 **304 s**（刀 17 记的是 256 s）。多的是八个 kernel 的汇编与
真机对拍、五个既有变异体各多几次汇编（`ladder-strides-reversed` 从九次到十次、
`gather-mask-dropped` 从四次到五次、两个 erf 变异体各从两次到三次、两个整数变异体各从四次
到六次），以及**四条变异体乘十三条序列共 52 次真机重跑**（刀 17 是 48 次）。它只在本机跑，
CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 与 `dawn test packages/tileir` 一个测试
都没多（146 → 146、88 → 88）：这一刀往包里加了零个机制，判词全在层 2。

**刀 19 的实测：十个 kernel，三条预算行一条也没重述，因为该重述的那一条撞上了 pole。**
这一天机器上没有别的 agent（每次都查过 `ps`：只有本刀自己的 java 与 cc1），所以下面三轮是
这条脚本少见的「只有自己」的读数。117 个工作项（102 个 kernel + 15 个变异体）：

| | 三片 | 不分片 |
|---|---|---|
| 第一轮（起跑时还带着刚跑完的 Core golden 重录，负载 4.40） | **249 / 258 / 284 s** | **763 s** |
| 第二轮（空闲起跑，负载 3.09） | **225 / 240 / 306 s** | 未量 |
| 第三轮（rebase 之后的最终树） | **253 / 242 / 262 s** | **840 s** |

**第三片是系统性地最贵的一片，而这是新事实。** 刀 16 与刀 18 各量过一次「round-robin 把工作项
分得很平」（170 / 171 / 171 与 228 / 227 / 231），本刀三轮的散布是 35 s、81 s 与 20 s，而且
三轮里第三片都是最慢的一片。两个原因叠在一起：一是 117 恰好被 3 整除，第三片从 35 项涨到
39 项（前两片从 36 涨到 39），单这一步就多一项；二是这一片本来就压着 `matmul`、`reverse`、
`conv3d`、`gaussian_blur` 这几个单价最高的。**「round-robin 分得平」这句话到此为止只对项数
成立，对秒数不再成立**，下一个要动这张表的人该先量单价再排顺序（`matrix.txt` 的表头本来就
写着「重排会把工作项挪片，是无害的，但要在提交信息里说」）。

**按 `gates.yml` 一直用的算法（本机片值 + 70 s，翻倍给冷 runner），取三轮里每片各自较差的
读数 253 / 258 / 306 s，三条预算行会是 646 / 656 / 752 s。第三条越过了 660 s 的
run-pole，越了 92 s；而且这不是取「较差」取出来的：三轮里第三片最快的一次是 262 s，算出来
是 664 s，仍然越了 4 s。三轮没有一轮进得来。** 抬 pole 正是 pole 存在要拒绝的动作，所以
**本刀不重述任何一条预算行**：
`gates.yml` 里仍然是刀 18 的 596 / 594 / 602 s 与 30 / 30 / 31 分钟，`check-gate-budgets.py`
仍然绿（它比的是 `timeout-minutes` 与声明值，不是本机秒数）。这一段就是那条没写进 `gates.yml`
的记录，留给下一个人裁。**（一）**分第四片，但触发线是 CI **观测**过 550 s，而下面的投影是
438 / 446 / 529 s，还没到；**（二）**照单价重排 `matrix.txt`，把第三片摊平，三轮的和是 791 s、
771 s 与 757 s，均摊后是 264 s、257 s 与 253 s，预算 668 s、654 s 与 646 s，**最差的那一轮
仍然差 8 s 才进得来**；
**（三）**抬 pole。三条都不是一把刀该自己决定的。

CI 投影：run 33763512 观测到的 CI 与本机之比约 1.73，套到 253 / 258 / 306 s 上是
**438 / 446 / 529 s**。**没有一片投影过 550 s，所以 N 不动**。真正超出的是本机的规划值，
不是 CI 的观测值，这两件事第一次分了家，也是上面那三个选项谁都不明显的原因。

`tile-gpu-diff/run.sh` 本机 **305 s**（刀 18 记的是 304 s）。多的是十个 kernel 的汇编与真机
对拍、`reduce-identity-wrong` 与 `gather-mask-dropped` 各多一次汇编，以及**四条变异体乘
十七条序列共 68 次真机重跑**（刀 18 是 52 次）。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 与 `dawn test packages/tileir` 一个测试都没多（146 → 146、88 → 88）：
这一刀往包里加了零个机制，判词全在层 2。

**实施中途 main 落了 Console 刀 2，rebase 到 `fc85846a`。** 冲突仍然只有
`scripts/core-golden/selfhost{,.norm}.sha` 两个文件，仍然按刀 18 立的规矩办：**取哪一边都会
丢掉另一把刀的重录，正确做法是对合并后的树重录一次**。这一次合并后只有四个模块的哈希动
（`main` / `nmain` / `consolemem` / `exitmem`，正是 Console 刀碰过的四个，它们的 id 被本刀
的十个参考实现再推一次），另外 83 个与四份 `.core` 都已经是 rebase 前那次重录的样子。
Emit-Change 对新基线又量了一遍，十一条判词逐条相同（八动两不动加 `doc --builtins`），
ADT 位移仍是 +199。上面的第一、二轮墙钟是在 rebase 前的树上量的，第三轮是在 rebase 之后的
最终树上量的；Console 刀 2 不碰任何 tile 路径，三轮因此可以并排读。

**刀 20 的实测：九个 kernel，四条预算行全部重述，`matrix.txt` 按单价重排，N 从 3 变 4。**
刀 19 把三个选项留给了下一个人（分第四片 / 照单价重排 / 抬 pole），这一刀取了前两个，
并且**先量了单价才排的顺序**。量法进了 `run.sh`：`ITEM_TIMES=<文件>` 时每个工作项写一行
`<名字> <秒>`，默认关闭、关闭时不花时间。一次不分片的整跑（126 个工作项 = 111 个 kernel
加 15 个变异体，**831 s**）给出：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 111 | 4.28 s | 6.71 s | 5.26 s | 583.8 s |
| 变异体 | 15 | 13.21 s | 18.12 s | 15.34 s | 230.2 s |

**这张表推翻了刀 19 写下的那一句。** 刀 19 说第三片贵是因为它压着 `matmul` / `reverse` /
`conv3d` / `gaussian_blur` 这几个「单价最高的」；实测**每一个变异体都比每一个 kernel 贵**，
而 kernel 之间只差 2.4 s。真正的杠杆是 15 个变异体怎么分，而变异体的块在 `run.sh` 里按源码
顺序排、`run_item` 又把 `matrix.txt` 的顺序钉死在运行顺序上，所以它们的分片是位置给的、
挪不动（挪要搬十五段代码，换不来任何东西）。**能排的只有 kernel**：先按贵到便宜排，再一个
一个发给当前最轻的那一片，配额是各片在前 111 个位置上占的格数。

**N=3 就算这样排也进不来。** 同一份 126 项按单价排成三片是 270.8 / 272.3 / 270.9 s，
规划值 684 s，仍在 660 s 的 pole 之上 24 s；刀 19 算过的「均摊后最差那一轮仍差 8 s」这次
是差 24 s，因为又多了九个 kernel。**四片是进得来的最少片数**：

| | 四片 | 不分片 |
|---|---|---|
| 第一轮（rebase 前的树，负载 3.1 至 3.6） | **200 / 195 / 182 / 197 s** | **831 s** |
| 第二轮（rebase 之后的最终树，同时录分片覆盖，负载 2.6 至 3.5） | **187 / 188 / 174 / 179 s** | 未量 |

取每片各自较差的读数（都在第一轮），`(本机 + 70) × 2` 是 **540 / 530 / 504 / 534 s**，
四条预算行全部按它重述，`timeout-minutes` 是 **27 / 27 / 26 / 27**。最高的一条离 660 s 的
pole 还有 120 s，**pole 一动没动**。CI 投影：沿用 1.73 的比值是 **346 / 337 / 315 / 341 s**，
没有一片接近 550 s 的观测触发线，所以下一次分片的理由仍然要靠观测或者再一次撞 pole。

**四片买的仍然是预算余量而不是墙钟**，这句话从刀 16 起没变过：一次 run 现在有 38 个 job
顶着 20 的并发上限，第 38 个只会排队；跑得最久的仍然是 native-diff 那一族，tile 从来不是
长杆。新的第四片进来之后，**这次 run 的跨度由尾巴决定，不由 job 数决定**。

第二轮同时把 `MUTANT_COVERAGE_DIR` 打开，`scripts/mutant-coverage/check.py --coverage-dir`
对四片的并集答 `tile-golden: 126 mutant(s) covered across 4 shard(s)`：分片改了 N,
并集仍然是整张表。

`tile-gpu-diff/run.sh` 本机 **319 s**（刀 19 记的是 305 s；同一份脚本在机器上还有别的 agent 时量到 401 s，两个数一起记，因为这一族的读数对负载敏感）。多的是九个 kernel 的汇编与真机
对拍，以及**四条变异体乘二十一条序列共 84 次真机重跑**（刀 19 是 68 次），其中 `ols` 一条
就有十次 launch。它只在本机跑，CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 与
`dawn test packages/tileir` 一个测试都没多：这一刀往包里加了零个机制，判词全在层 2。

**实施中途 main 两次前进（刀 19 合入后的 `f0e1704e`，以及重述预算行的 `e3d47a8c`），
rebase 到后者。** 冲突仍然是老三样加两处：`scripts/core-golden/selfhost{,.norm}.sha`
（按刀 18 立的规矩对合并后的树重录一次，不取任何一边），`gates.yml` 的 job 计数段
（main 那边刚加了 `native-selfhost-tests`，两边各把同一个数字改成 37，合起来是 **38**，
加 ci.yml 的 `secrets` 是 39），以及 `docs/README.md` 那一行（两边都在删破折号，取并集）。

**刀 21 的实测：十五个 kernel，两条预算行重述，`matrix.txt` 的顺序**不再**是杠杆。**
这一刀量了两轮 `ITEM_TIMES`，同一棵树、同一个 `tileiras`，差别只有机器上有没有别人：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| 第一轮 kernel（另一个 agent 在建东西，负载 6 到 9 且在下降） | 126 | 4.35 s | 6.04 s | 5.35 s | 674.3 s |
| 第一轮变异体 | 15 | 11.99 s | 14.42 s | 13.80 s | 207.0 s |
| 第二轮 kernel（机器空闲，负载约 2） | 126 | 4.09 s | 4.66 s | 4.30 s | 541.5 s |
| 第二轮变异体 | 15 | 11.63 s | 14.10 s | 13.65 s | 204.8 s |

不分片整跑第一轮 881 s、第二轮 746 s。**两轮对变异体的说法一致，对 kernel 的说法互相
不认**：逐项相关系数变异体 **0.96**、kernel **0.07**；而第一轮的「成本对位置」相关系数是
**−0.58**（负载在跑的过程中降下来了，所以先跑的那些看起来贵），第二轮是 −0.01。
空闲机器上每个 kernel 与每个 kernel 相差不到 0.6 s。

**结论是刀 20 那次「按单价从贵到便宜发牌」读的是负载噪声。** 它没有被推翻成「排反了」，
而是被推翻成「这一列没有信息」。处置是**不重排**（重排等于把同一份噪声反着读一遍），
本刀的十五个 kernel 直接接在表尾。真正决定分片的是两件与顺序无关的事：十五个变异体在表尾
的块顺序（141 项时它们落成 **4 / 3 / 4 / 4**，所以最轻的一片从第三片换成了第二片），以及
126 mod 4。第二轮按项求和的四片是 **193.1 / 179.3 / 185.0 / 189.0 s**，均分应是 186.6 s。

四片背靠背的墙钟（空闲机器，负载约 3）：**205.6 / 186.3 / 189.1 / 193.4 s**。按本文件一贯的
算法 `(本机 + 70) × 2`：**552 / 512 / 518 / 526 s**。**只重述第一片与第三片**。第二片的
512 s 与第四片的 526 s 都**低于**它们已经写着的 530 s 与 534 s，而预算是上限不是目标，
往下重述只会让下一刀再抬一次（刀 14 立的规矩）。`timeout-minutes` 因此是 **28 / 27 / 26 / 27**。
最紧的一条离 660 s 的 pole 还有 **108 s**，pole 一动没动。

**N 仍然是 4，而这次不是投影而是观测。** `scripts/gate-observations.py` 拉下 2026-09-03 之后
24 轮 main 的实际用时，四片各自最差是 **427 / 414 / 385 / 331 s**（run 33843495626 /
33822343705 / 33863991167 / 33887762680），CI 对本机的比值约 **2.1**。每片多约四个 kernel、
本机约 17 s、CI 约 36 s，于是投影 **463 / 448 / 417 / 361 s**，最差的一片离 550 s 的观测
触发线还有 87 s。

`tile-gpu-diff/run.sh` 本机 **367 s**，同一棵树上第二次量到 **305 s**（刀 20 记的是 319 s；
这条脚本的读数一向对负载敏感，两个数一起记）。多的是十五个 kernel 的汇编与
真机对拍，以及**四条变异体乘二十三条序列共 92 次真机重跑**（刀 20 是 84 次），其中 `llama`
一条就有十七次 launch。它只在本机跑，CI 上仍只有亚秒的 `--check`。`dawn test --stdlib` 与
`dawn test packages/tileir` 一个测试都没多：这一刀往包里加了零个机制。

**刀 T1 的墙钟与分片（一次不能重述预算的测量）**。这一刀给 `tile-golden` 加两个 kernel
（`trig_sweep` / `rope`）与一个变异体（`trig-extra-flags`），矩阵 141 项长到 **144 项**。
于是分片的算术**头一次除得尽**：128 个 kernel 与 16 个变异体，每片 32 个加 4 个，四片的活
一模一样，剩下的差都是机器的。

**本机这次的绝对秒数不能用来重述预算，理由写在这儿而不是藏着**：跑的时候机器上还有另外
五个 agent（`uptime` 的 load average 在 31 到 37 之间），刀 21 已经量过同一棵树在这种情况下
全量从 746 s 拉到 881 s。所以四条预算行是这样重述的：各自拿刀 21 那次安静测量的读数，加上
刀 21 的单项均值（一个 kernel 4.30 s、一个变异体 13.65 s，这个模型把刀 21 实测的四片和预测
到 1.5 s 以内），**只往上走**。四片各加的东西不一样：第 1 片什么也没加（它本来就是 32 + 4），
第 2 片加的是一个**变异体**，第 3、4 片各加一个 kernel。于是
planning value 552 / 530 / 518 / 534 变成 **552 / 558 / 527 / 535**，`timeout-minutes`
28 / 28 / 27 / 27。

重述前按规矩跑了审计（`scripts/gate-observations.py` 拉 09-03 与 09-04 的 25 次 run，
`scripts/check-gate-budgets.py --observed`）：四片 CI 实测最差 **427 / 414 / 385 / 371 s**，
一条都没被点名，离「某一片实测过 550 s 就分第五片」的触发条件最近的也还有 120 s；把本刀的
活加上去的投影是 ~427 / 443 / 394 / 380 s，**不分第五片**。审计顺带点了九条与 tile 无关的
欠债行（native-diff-1/2、syntax-mutants-1/3、builtin-type-1/2、checker-corpus、
pipe-contract-1、list-elems-contract），本刀不动它们。**欠一次安静的本机重测**，而重测只会把
这四个上限往下压，那是这份文件不据以动作的方向。

### 6.6 两档判词：逐位与容差（刀 7b）

层 2 从第一天就写着「分逐位与容差两档」（§6.2 的表、§3.2 的 matmul 行），但直到刀 7b 容差档
才有第一个客户。这一节把两档写成判词。

**逐位档**：整段缓冲区的渲染文本逐字相等（渲染能分辨 `-0.0` 与 `0.0`）。一个 kernel 进这一档
要同时满足两条：

1. 它的每一个操作在 IEEE 754 下都是精确的或正确舍入的（`addf / subf / mulf / divf / sqrt`、
   符号翻转、`select`、比较、乘积精确时的 `fma`）；
2. **它的语料使归约的折叠顺序不可见**。这一条是刀 7b 才被迫写下来的：Tile IR 只要求归约函数
   结合且交换，**不规定树形**，所以 `sum_ref` 的左折叠不是一般语料上的 oracle。本刀的逐位档
   语料全是整数值、且每一个部分和都远在 2^53 之内，此时任何折叠顺序都是同一个精确整数。

**容差档**：逐 lane `|got - want| <= atol + rtol * |want|`，`atol = rtol = 1e-5`，这是
leetgpu 自己的判词。`exp / exp2 / log / log2 / rsqrt / tanh / pow` 是设备 libdevice 的近似
实现，宿主参考是级数（Dawn 没有浮点超越函数，`std/gpu` 的 `ref_exp / ref_log / ref_sqrt` 是
为此写的，精度到最后几个 ulp），**两边是两个意见，谁也不是谁的定义**，所以带这些操作的
kernel 永远在容差档，没有语料能让它们进逐位档。`rms_norm` 也在这一档，不是因为 `sqrt`
（IEEE 754 要求它正确舍入），而是因为它的宿主参考用牛顿迭代求根、不保证最后一位；本机实测
它恰好逐位相同，转录里记的是 `identical:tolerance`。

两档都实现在 `scripts/tile-gpu-diff/red_diff.dawn` 里，因为档位是 kernel 的属性而不是某次运行
的属性；每道题的档位记在 `scripts/leetgpu-diff/problems.txt` 的 `tier` 列，
`scripts/leetgpu-diff/check.py` **读 `red_diff.dawn` 自己的 `tolerance_tier()` 名单**，
把台账那一列与程序对账，所以一行不能声称一个这次运行并没有做的判词。台账行的注释里记两档
各几个（`tiers exact=6 tolerance=7`）。

**顺序探针（记录，不是断言）**：拿 `[2^53, 1, 1, -2^53]` 后面补零的语料跑一次 `reduce_sum`，
答案本身说出设备用的是哪种折叠顺序：左折叠 0、成对 1、右折叠 2。**本机 RTX 3080 +
tileiras 13.3.36 实测答 1.0，即成对（树形）折叠**。`sum_ref` 的左折叠确实不是 oracle，
这不是理论上的担心。探针的答案进台账注释（`fold-order=... (pairwise)`），`tileiras` 升级后
顺序变了会被看见，而不是被发现。

**刀 13 的三条实测（`scan`）**。`scan`（0x5E）与 `reduce` 共用一套区域编码，多一个
`reverse` 属性；下面三件事只有设备能回答，而三条里有两条推翻了动工前的写法。

1. **区域的第一个参数是累加器，第二个是元素**，正向反向都一样。方言 `Ops.td` 的散文说区域
   参数是 `[op_0_current_iter, op_0_prev_iter]`（元素在前），它自己的 mlirExample 却写
   `(%acc, %elem)`（累加器在前），两句不能同真。判据是一个「只答第 k 个参数」的 kernel：
   答第一个参数的在设备上答出该维的**第一个**元素，答第二个的答出**最后一个**；`reduce`
   与 `scan` 都是这样，`reverse = true` 时「第一个」按折叠方向算，也就是下标最大的那个。
   于是本仓 `d_reduce` 一族原来的参数名是反的。这在 `reduce` 上永远看不见（树里每一个
   归约体都可交换），在 `scan` 上直接决定答案，所以随这一刀改正；改名是纯改名，55 个
   golden 一字节没动，这也是它的判据。
2. **identity 不参与第一个位置的折叠**：一个元素的前缀就是它自己，而不是
   `f(identity, x[0])`。同一个探针给的答案：body 只答累加器时，设备答的是 `x[0]` 而不是
   identity。`linrec` 的 `h[0] = x[0]` 正是这条，leetgpu 82 的参考实现也这么写。
3. **设备的浮点前缀和不是顺序左折叠**。刀单原话是「scan 的结果与顺序有关，不像 reduce，
   所以浮点也能逐位比左折叠参考实现」，实测推翻：`scan_diff` 的顺序探针拿 100 个倒数跑
   `prefix_sum`，答案与左折叠差 73 个 lane、与「每个前缀各自从右往左折」差 51 个，两个都
   不是它。**所以浮点扫描一律容差档**（本机最大 miss 3.0e-10，是容差的 3e-10 倍），整数
   扫描仍是逐位档，而且和刀 10 一样是**代数**给的不是语料给的：模 2^32 的加法精确结合，
   任何重组都是同一个值。

还有一条直接决定能解几道题：**方言散文写着 `scan`「restricted to only support single tile
input」，但它的 verifier 不这么说，`tileiras` 收下，设备也算对**。一阶线性递推
`h[t] = a[t] * h[t-1] + x[t]` 折的是仿射映射，而一个仿射映射是两个数，所以 82 / 110 / 94
三道题全靠双操作数 scan；`ssm_scan` 更把它开在一张 rank-2 的 tile 上，一次 launch 带走一个
通道的全部隐状态。散文与机器分歧时以机器为准，并把测量写在这里，是这一条的处置。

**刀 14 的实测（原子操作）**。`atomic_rmw_tko`（0x08）与 `atomic_cas_tko`（0x07）是这棵树上
第一对「两个 lane 可以指向同一个元素」的操作。在它们之前每一个 scatter 都必须写一个置换，
因为方言不给单次 store 的各 lane 之间任何顺序，重复的目的地于是没有答案；原子操作正是给出
答案的那个机制，而 13 Histogramming 是射程内唯一严格需要它的题。

1. **属性布局一次写对，判据是刀 10 立下的那条**。两个操作的 `memory_scope` 都是必填参数
   （`CudaTileArg<CudaTile_MemoryScopeAttr, ..>`），不像 `load_ptr_tko` 的那个是
   `OptionalAttr`；于是它们**没有任何可选属性**，flags 的第一位就是第一个可选**操作数**
   `mask`（1）、第二位是 `token`（2），而 load 的这两位是 4 与 16。必填属性按声明序内联：
   `memory_ordering_semantics`、`memory_scope`，`atomic_rmw_tko` 再多一个 `mode`。
   `tileiras` 第一次就收下，设备也逐位证实。三张枚举表读自 `AttrDefs.td`：`AtomicRMWMode`
   的顺序是 and 0 / or 1 / xor 2 / add 3 / addf 4 / max 5 / min 6 / umax 7 / umin 8 /
   xchg 9（不是字母序，也不是 `add` 打头），`MemoryScope` 是 tl_blk 0 / device 1 / sys 2，
   `MemoryOrderingSemantics` 是 weak 0 / relaxed 1 / acquire 2 / release 3 / acq_rel 4。
2. **`weak` 是这两个操作唯一不接受的内存序**。`Ops.td` 给它们的是
   `OnlyVariants<["RELAXED", "ACQUIRE", "RELEASE", "ACQ_REL"]>`：`weak` 的语义正是
   「假设没有别的线程碰这个位置」，与原子操作的目的相反，方言把这条矛盾做成了拒绝而不是
   忽略。所以它是一个层 1 变异体而不是一句注释。
3. **语料是判词的一半，而这一刀把那一半做成了可测量的**。原子加与「gather、addi、scatter」
   三条指令在**没有冲突的语料上是同一个程序**。所以 `atom_diff` 除了主语料还带一个
   `--corpus unique`（每个 bin 恰好一个 lane、跨块也不重复），`run.sh` 把
   `atomic-as-plain-store` 变异体在两个语料上各跑一次：主语料上必须红、控制语料上必须绿。
   主语料的冲突计数印在转录里（`counted=476 of 500`、`bin_repeated=460`、
   `cross_block_bins=16`）并被 `run.sh` 钉在零以上。这是刀 12 把 scatter 的
   `in_range_repeated` 钉在零那条规矩的反向用法：一边把重复钉死为零，一边把重复钉死为正。
   没有第三步，「变异体会红」并不能区分是原子在起作用还是别的什么在起作用。
4. **两个 kernel 都是逐位档，而且和刀 10 一样靠代数不靠语料**：模 2^32 的整数加法精确结合
   交换，所以直方图不管冲突的 lane 以什么顺序到达都是同一个总数；`cas_swap` 每个槽位只有
   一个 lane，根本没有顺序可言。
5. **CAS 在 leetgpu 上没有客户**，所以照刀 12 对 `scatter_perm` 的做法加了一个无题的覆盖
   kernel `cas_swap`：128 个槽位、每槽一个 lane，期望值为负的 lane 被掩码挡住，返回的旧值
   写进第四个缓冲。语料同时含「命中并交换」34 个、「不命中而保持」若干与「被掩码」26 个，
   三者都被 `run.sh` 钉在零以上，否则 `cas-compare-ignored` 没有东西可红。

**刀 14 的两个层 1 变异体，一个同长一个长一字节**：

| 变异体 | 改哪 | 层 0 | 层 1 |
|--------|------|------|------|
| `atomic-rmw-claims-weak-ordering` | 写入器给 `atomic_rmw_tko` 写 `weak`（0）而不是 `relaxed`（1） | **看不见**：渲染器有自己的拼写表，`.mlir` 照印 `relaxed` | 拒：`'cuda_tile.atomic_rmw_tko' op memory ordering semantics must be one of: relaxed, acquire, release, acq_rel` |
| `atomic-cas-writes-an-rmw-mode` | 写入器给 CAS 也写一个 `mode` 字节，这是读这两个操作时最容易犯的复制错 | 看不见 | 拒：字节**多一个**，读者从那里起每个操作数都错一格，`failed to parse function body for function 'cas_swap'`。`writer_mutant_checks` 因此第一次需要 `func-one-long` 这个形状 |

**刀 14 的两个层 2 变异体**：

| 变异体 | 改哪 | 层 0 | 层 1 | 层 2 |
|--------|------|------|------|------|
| `atomic-as-plain-store` | 包的 `atomic_add_masked` 改发 gather、`addi`、scatter 三条 | 变（histogram 的字节动，`cas_swap` 的不动） | 收（一次 load 加一次 store 是合法的） | **只有 `histogram` 红**：24 个 lane 里 16 个错，每个 bin 每块只剩一次增量。控制语料（每 bin 一个 lane）上**必须绿**，这一格是判词的另一半 |
| `cas-compare-ignored` | `cas_swap` 把要写的值当成期望值交给 CAS | 变（`cas_swap` 的字节动，histogram 的不动） | 收（`AllTypesMatch<["cmp","val","result"]>` 两种交法都满足） | **只有 `cas_swap` 红**：该换值的 34 个槽位一个也没换 |

**刀 15 的实测（`erf` 的组合实现）**。这一刀是这棵树上第一个**判词的主语是近似而不是设备**
的刀，三条测量值得写下来：

1. **1.5e-7 是有出处的常数，本机量到 1.380e-7**。Abramowitz-Stegun 7.1.26 的误差界是手册
   自己写的；`erf_diff` 的 `error` 行印出设备答案与 `std/gpu.ref_erf` 的最大绝对差，
   `run.sh` 把它钉在 `(0, 1.5e-7]` 里。**下界也钉**：差为零意味着参考实现变成了 kernel
   自己的代码路径。`erf_sweep` 上是 **1.3797e-7**，`geglu` 上是 **3.6356e-7**（同一个误差
   被乘子放大了，所以量误差要用没有乘子的那个 kernel）。

2. **参考实现必须是另一个意见，而不是同一个有理式**。`std/gpu.ref_erf` 用的是全正项级数
   `erf(x) = (2/√π) exp(-x²) Σ 2^n x^(2n+1) / (1·3·…·(2n+1))`，没有相消，精度约 4e-15
   （`|x| > 6` 直接答 1，`erfc(6)` 是 2.2e-17）。如果参考也跑 7.1.26，那么**一个抄错了系数的
   实现会与它一致**，而且这一刀的误差根本无从测量——这条比「参考不能调用 kernel」更强一点：
   参考不能是同一个近似。

3. **74 GPT-2 Block 用的不是 erf**。刀单把 65 与 74 排在一起，核实题面后发现 74 的前馈层写的是
   `F.gelu(fc, approximate="tanh")`，即 tanh 近似；它一道 erf 也不用。它本来也进不来：
   LayerNorm → QKV 投影 → 多头注意力 → 投影 → 残差 → LayerNorm → 前馈，是一串要中间缓冲的
   乘积链，一次 launch 只写参数缓冲的后端表达不了（与刀 9 落选的 12 / 26 / 80 同因）。
   于是刀 15 只解 65，累计 **54 / 97**。反过来，那个 tanh 公式正好当负控，见下表。

**刀 15 的两个层 2 变异体**（都在包的 `erf` 里，因而两个 kernel 一起动；分开它们的是**语料**）：

| 变异体 | 改哪 | 层 0 | 层 1 | 层 2 主语料 | 层 2 控制语料（`--corpus positive`） |
|--------|------|------|------|------|------|
| `erf-tanh-approx` | 换成 PyTorch `gelu(approximate="tanh")` 的公式，写成 erf 就是 `tanh(1.1283791670955128 x + 0.10091094891335171 x³)` | 变（两个 kernel 的字节都动） | 收（`tanh` 与 `exp` 一样合法） | **两个都红**：误差约 3.6e-4，是 `atol = 1e-5` 的 36 倍 | **两个仍红**：近似错了，正半轴也一样错 |
| `erf-sign-not-flipped` | 去掉奇对称的 `select`，一律答 `erf(|x|)` | 变（两个 kernel 的字节都动） | 收（少一个比较与一个 select 的 kernel 仍是合法 kernel） | **两个都红**：负 lane 差到 2 | **必须全绿**：没有负 lane 时它是恒等改写 |

第一条存在的理由是**证明容差档没选宽**：一个能放过 3.6e-4 的容差等于没有判词，第二条在控制
语料上的绿也就没有意义了。第二条存在的理由是**证明语料在干活**：这是刀 14
`atomic-as-plain-store`「无冲突语料上必须绿」那条规矩反过来用一次——一边把负 lane 钉在零以上，
一边钉在零。两条语料判词都是 `PASS corpus` 行，`run.sh` 逐条查
（`negative` / `tail` / `near_zero` 三个计数，主语料上三个都要大于零，控制语料上第一个必须为零）。

**只有层 2 能红的两个负控**（刀 7a 的 `mask-all-true` 是第一个）：

| 变异体 | 改哪 | 层 0 | 层 1 | 层 2 |
|--------|------|------|------|------|
| `reduce-identity-wrong` | `d_reduce` 把 identity 加 1：求和的 identity 从 `0.0` 变 `1.0`，求最大值的 `-inf` 不动（`-inf + 1 = -inf`） | 变（文本印 `identities=[1.0 : f64]`，`--record` 能洗白） | **收**（`tileiras` 只校验 identity 的**格式**与操作数是否一致，从不看**值**，实测） | 十三个 kernel 里带求和归约的**八个**全红，另外五个一动不动 |
| `softmax-no-max-subtract` | softmax kernel 不再减最大值 | 变（少一个 `reduce`） | 收（是一个合法的、更短的 kernel） | 只有 softmax 红：在 1000 附近的语料上设备算 `exp(1000)` 溢出成 `+inf`，`inf / inf = NaN`，而参考是有限的。**语料是判词的一部分**，所以语料与 kernel 放在一起 |

第二个变异体值得单说：它在小语料上**数值上完全正确**，层 2 也照样是绿的。让它红的是语料，
不是机制。这就是为什么 `red_diff.dawn` 里 softmax 的语料是 `1000 + i % 17` 而不是随手一组数。

**刀 8 的两个负控，其中一个在 Dawn 源码以下**：

| 变异体 | 改哪 | 层 0 | 层 1 | 层 2 |
|--------|------|------|------|------|
| `grid-y-ignored` | `runtime/c/dawn_rt.c` 的 `cuLaunchKernel` 把 gridDimY 写死 1 | **看不见**（grid 不在字节码里，也不在文本里） | **看不见**（`tileiras` 从不启动任何东西） | 七个 kernel 里 grid 有第二根轴的**四个**全红（`matmul` / `batched_matmul` / `transpose` / `group_norm`），一维 grid 的三个一动不动 |
| `mma-acc-not-carried` | GEMM 的 K 循环不再携带累加器，每轮从新的零 tile 起 | 变（`--record` 能洗白） | 收（是一个合法、同样良类型的 kernel） | 只有 `matmul` 红：它答的是最后一片 K 的乘积而不是整个和 |

`grid-y-ignored` 是这条线上第一个**编译器与包都看不到**的变异体：它改的是 C 运行时，
而三层门里只有层 2 会启动 kernel。刀 7 之前也写不出来，那时每个 kernel 的 grid 都是一维的，
把 gridDimY 写死 1 什么也不改变。

**f64 `mmaf` 在 sm_86 上：汇编得了，但不落 tensor core。** 开工第一件事是拿一个手写的最小
模块问 `tileiras`（一个 throwaway Python 写入器，先逐字节复现 `vadd.tilebc` 再改）：
`mmaf` 的 f64、f32、bf16 三种输入在 sm_80 / sm_86 / sm_90 上都退出 0、stderr 干净。
但 `--remarks=tensorcore` 说的是另一回事：

- f64 64x32x64（`matmul` 的形状）：`remark[failed]: MMA operation failed to optimize to use
  Tensor Cores, it is using FMA instructions instead`，`reason: MMA size does not fit in the
  tensor core`，`note: Instruction = FMA`。f64 8x4x8、16x16x16 与 f32 64x32x64 一样。
- bf16 输入、f32 累加、64x32x64：`remark[passed]: MMA operation successfully optimized to
  use Tensor Cores`，`note: Instruction = Tensor-core SM80`。

本机是 GA102，没有快速 f64 tensor core，所以这个结果就是硬件的实话，不是我们编错了。
**处置**：本刀的两个 GEMM 用 f64 缓冲（`element_bytes` 今天只认 f64 与 bf16），走的是 FMA
路径；`mmaf` 的容差档判词因此**不是**「tensor core 不精确」而是「K 上的求和顺序没有规定」，
这一条与硬件无关，永久成立。真正走上 tensor core 的 bf16 × bf16 → f32 需要一个 f32 或
bf16 的输出缓冲（`ftof` 把 f32 累加器转回 bf16），归刀 11。

**计划里的 tfloat32 与 f32 两组语料没有跑，理由是形状不对**：计划写的是「f32 输入时同时跑
一组 tfloat32 舍入的和一组 f32-as-f32 的」，而本刀的缓冲只有 f64（f32 缓冲要 `element_bytes`
认识 4 字节，是刀 11 的事）。换成了本机能做的等价记录：`matmul` 的语料是整数值、每个部分和
都远在 2^53 之内，所以任何求和顺序都是同一个精确整数。实测设备与参考**逐位相同**
（`identical:tolerance`，miss 0.0），这是**赠品**而不是判词；`batched_matmul` 的语料是十分之几，
不在二进制格点上，求和的分组因此可见。实测 `close:tolerance`，最大 miss **1.02e-10**
（判词的 1e-10 倍）。这一对就是「容差档在这里确实在干活」的证据。

**刀 10：逐位档的对照组，以及它凭什么不靠语料。** 上面两条逐位档的条件里，第 2 条
（「语料使折叠顺序不可见」）一直是一个**关于语料**的条件，这让「容差」看起来像是层 2 的
能力上限而不是操作的性质。整数族把这件事分开了：i32 的结果只有一个值、没有舍入模式，
而**整数加法模 2^32 精确地结合且交换**，所以设备选什么折叠树都答同一个数——第 2 条对
`s_addi` 无条件成立，不需要挑语料。加上 `List[Float]` 通道对 i32 无损（§3.3），
`count_eq` / `subarray_sum` / `rainbow` / `int_ops` 四个 kernel 在同一条流水线上被钉在
逐位档，靠的是代数而不是数据。于是「容差」是 `exp` 与 `mmaf` 的属性，不是层 2 的属性。

**刀 10 的两个负控，两个层 0 都看不见**：

| 变异体 | 改哪 | 层 0 | 层 1 | 层 2 |
|--------|------|------|------|------|
| `shri-always-logical` | **写入器**把 `shri` 的 `signedness` 写成 unsigned，算术右移全变逻辑右移 | **看不见**：渲染器有自己的拼写表，`.mlir` 照印 `signed`，`--record` 洗不出任何东西 | 收（`signedness<unsigned>` 与 `<signed>` 同样合法，汇编器对一个 kernel 想要哪个没有意见） | 四个 kernel 里做算术右移的**两个**红（`rainbow` / `int_ops`），另外两个不动。**语料是判词的一半**：两种右移在每个非负操作数上答案相同，所以 `int_diff` 的数据铺满整个 i32 值域 |
| `exti-sign-extends` | 写入器把 `exti` 的 `signedness` 写成 signed，于是一个比较掩码展宽成 0 与 **-1** 而不是 0 与 1 | **看不见**（同上，文本照印 `unsigned`） | 收（有符号展宽也是合法操作，只是不是这一处要的那个） | 展宽掩码的**两个**红（`count_eq` 答出取负的计数，`int_ops` 的奇偶项翻号），另外两个不动 |

这一对比刀 7b、刀 8 的负控更深一格：那几个至少还会动 `.mlir`，一次 `--record` 能把它们
洗白（这正是「层 0 的绿没有信息量」）。这两个连 `--record` 都洗不到，因为渲染器与写入器
各持一张表，文本那张没有被改。能红它们的只有设备。

**计划里的第二个负控没有落在层 2，而是落在层 1**：`ftoi-rounds-instead-of-truncates`
（把 `ftoi` 的舍入模式写成 nearest_even）是按「奇数 lane 上 `a / 2` 落在两个整数正中间」
设计的层 2 判词，实测 `tileiras` **直接拒**：`'cuda_tile.ftoi' op invalid rounding mode
specified. Only 'nearest_int_to_zero' is supported`。设备根本见不到它，所以它登记在
`scripts/tile-golden/run.sh` 的写入器变异体里（文本不动、字节同长、汇编器点名），
层 2 那一格换成了 `exti-sign-extends`。**变异体落在哪一层是测出来的，不是设计出来的。**

**这一刀真正被层 2 抓到的错，是 `divi` 的属性布局。** 写入器最初在每个「有默认值的属性」
前面写一个 flags varint，理由是把 `DefaultValuedAttr` 当成了可选字段；tblgen 的
`isOptional()` 只认 `OptionalAttr`，`BytecodeGen.cpp` 把带默认值的属性送去**必填**那条路
（读 `extractDefaultValue` 的那一支），所以它是内联写的。**这个错在只有一个属性的操作上
完全看不见**：`addi` 的「flags 0」与它的「overflow none」是同一个字节，`tileiras` 分不出
两种读法，层 0 与层 1 都是绿的。`divi` 有两个属性（先 `signedness` 后 `rounding`），
多出来的那个字节把两个都挪了一格，读者把 0 当成 signedness，于是设备做的是**无符号除法**——
一个完全合法的程序，汇编器照收。是 `int_ops` 在带负被除数的语料上把它逼出来的：
1000 个 lane 里 499 个红，红的恰好是 `a < 0` 的那些。修好后 `int_ops.tilebc` 动了一个字节，
`int_ops.mlir` **一个字符没动**——这就是那条错误从头到尾的可见性。

**`tileirdisasm` round-trip：未做。** 计划里那一格是「若本机能构建或找到
`cuda-tile-translate`（`--mlir-to-cudatilebc` 的逆向），把 `.tilebc` 反汇编回文本与 `.mlir`
golden 对拍」。本机没有：pin 的三个 wheel（`nvidia-cuda-tileiras` / `nvidia-nvvm` /
`nvidia-cuda-nvcc`）里只有 `tileiras` 一个可执行文件，它只读字节码、不写文本；
`NVIDIA/cuda-tile` 的 `cuda-tile-translate` 要从源码连同 MLIR / LLVM 一起构建，不在这一刀的
范围内。**所以「文本与字节码说的是同一件事」今天仍然只有一个人类可读的论证**（两个消费者
读同一张指令表，`lower.dawn` 的表是唯一真相），没有机器判词。这一格是空的，不是绿的。

**刀 20 的实测（第三条逐位档，以及一条判词的洞）**。leetgpu 33 是这一族第三条进逐位档的
序列，而它进得去的理由与前两条不同，值得单列一条：

- `apsp`（刀 16）与 `kmeans`（刀 19）靠的是**语料**。两者都有归约，Tile IR 不规定归约树，
  所以只有当每一个部分和都精确时左折叠才是 oracle；语料因此被钉成整数与四分之一的倍数。
- `ols` 靠的是**代数**，语料不参与。它的十次 launch 里没有一次归约：Gram 矩阵是一个
  `d_for` 按下标顺序累加的，消元步与取答案都是逐元素的 `mulf` / `subf` / `divf`。IEEE 754
  要求这四个操作全部正确舍入，而两边的运算顺序都由下标固定，**没有一棵折叠树是自由的**，
  所以任何语料上它都逐位。本机实测 miss 恰好 `0.0`。

顺带一条：`mulf` 后接 `addf` / `subf` **不会**被合并成 fma。这不是新测的，是刀 7a 的
`elemops`（`((a+b)*a)-b`，逐位档，宿主参考分三步各舍一次）从第一天起就在证的事；`ols` 的
消元步 `a - colk * prow` 是同一个形状，如果设备会自己合并，两者都会红。

**判词的洞：一条序列只下载一个缓冲区。** leetgpu 111 有三个输出（dQ、dK、dV），而在它之前
每条序列的 `Seq` 只有一个 `read` 字段，判词也只比较那一个缓冲区。一个只写对 dQ、另外两个
一个字节都不写的设备会拿到绿，而哨兵机制救不了它，因为没人去看那两个缓冲区。改动是把
`read: String` 换成 `reads: List[String]`，`stages` 依次下载并首尾相接；十七条既有序列全部
变成 `reads: [原来那一个]`，四种判词结局与容差的量法一点没动。这是**多输出的题以后都要走的
路**，74 / 76 / 93 三块 transformer 也会用到。

**刀 21 的实测（第一条记录在比题目小的形状上的行，以及三角函数问题的反转）**。这一刀的
两道题都是**整块 transformer**，十二次与十七次 launch，比之前最长的 leetgpu 33 还长七次；
四条结论值得单列：

- **第一次出现「录制形状不是题目形状」的行。** 在这两行之前，台账每一行的维度都是调用方
  给的，所以「录在哪个形状上」是题目本来就有的一个形状。74 与 93 不是：GPT-2 124M 写死了
  D = 768、12 个头、FFN 3072，Llama 那块写死了 512 宽、8 个查询头对 2 个键头、FFN 1408。
  这里录的是 64 个 token 的 64 宽 / 128 宽、2 个与 4 个查询头、前馈 128 / 64。**能缩的与
  不能缩的分开说**：`kernels.dawn` 里的一个录制常量就是一个循环上界与一个 stride，所以同
  一批 kernel 在题目的常量上是同一批程序、grid 归调用方；缩不了的是**第二意见**，它是手写
  的宿主参考实现，跑在 `List[Float]` 上，而 GPT-2 光权重就是七百万个。所以这两行claim 的是
  「这个块的结构在一个宿主参考答得动的形状上」，不是「跑过一块 124M」。`problems.txt` 里
  为此写了一段，读的人应当把它读成机制而不是模型。
- **三角函数的问题反过来了。** 前研标了 93 的 RoPE「可能要 sin/cos」，开工前按刀 9 的规矩
  逐条核签名，答案在签名里：`solve(x, output, weights, cos, sin, seq_len)`，**cos 与 sin 是
  输入缓冲区**，所以 93 一个三角函数都不需要。真正需要的是 **76**：它的 RoPE 角度是在 solve
  内部由架构常量 `2π/19` 与位置算出来的，签名里没有任何东西提供它们，所以 76 落在三角函数
  那一桶里，本刀不取（它另外还是一条 11 步自回归、每步要 argmax 的序列）。
- **74 的 gelu 是 tanh 近似，不是刀 15 的 erf。** 参考实现写的是
  `F.gelu(x, approximate="tanh")`，两者在 |x| = 2 附近差约 1e-3，远在这条序列的容差之外。
  `tanh` 从刀 7b 起就在包里，所以**零新 opcode**；要新写的是宿主那一侧的第二意见
  `std/gpu.ref_tanh`，而它**不能整段用 `(e - 1) / (e + 1)`**：小参数上那个减法会吃掉答案的
  每一位有效数字，所以 |x| < 0.25 走的是 `exp(y) - 1` 的级数（全正项，不相消）。
- **十七次 launch 的合成误差仍然远在容差之内。** 本机 3080 上 `gpt2` 的 scaled miss 是
  **1.80e-9**、`llama` 是 **5.01e-8**（1.0 就是 `atol = rtol = 1e-5`）。这是这一族量过的最长
  的合成，值得记一笔：长度本身不推误差，推误差的是操作的种类。

负控这边零条新变异体：四条序列变异体乘二十三条序列，矩阵从 84 格长到 **92 格**、红集从 72
长到 **80**，两条新序列**四条全红**。其中 `grid-of-later-launch-copied-from-the-first` 在
它们身上红，与刀 20 的 `kv` / `ols` 那两个绿形成对照：两块 transformer 的第一次 launch 都是
「一行一个 block」的归一化，紧接着的投影却把输出的列块放在 grid 的**第二**根轴上（GPT-2 的
打包 QKV 是六块，Llama 的 Q 是四个头），所以把第一次的 N×1×1 抄过去只写得出其中一块。

**另有一条自轴负控**：把 `std/gpu.rope_ref` 的 cos 与 sin 对调（语料里两张表 1024 个位置有
970 个不同，所以这确实改了语义），只有 `llama` 一条从 `close:tolerance` 变成
`differ:result`，miss 从 5.01e-8 跳到 **1.13e7**，其余二十二条序列与全部单 launch 的判词
一个都没动。

**顺手补一个门。** `problems.txt` 的表头写着「N of the 97 reachable problems」，这个数从刀 18
之后就没人改过：83 行的表上写着 73，跨了两把刀没人发现，因为**没有任何程序读它**。
`check.py` 现在读它，并且自检里有一条负控。这是「注释里的数字不是判词」的又一个实例。

**刀 T1 的实测（三角与浮点取余，目标改判后的第一把加操作码的刀）**。七条新操作码
`sin` 0x62 / `cos` 0x12 / `tan` 0x69 / `sinh` 0x63 / `cosh` 0x13（13.1）、`atan2` 0x6E（13.2）、
`remf` 0x59（13.1），全是 FloatingPoint 组的逐元素浮点指令。五条结论：

1. **七条一个可选字段都没有，所以一个 flags varint 也不写。** 逐条核过 `Ops.td`：每条记录的
   `arguments` 只有 `source`（或 `lhs` 与 `rhs`），既没有 `OptionalAttr` 也没有可选操作数，
   于是 `getVersionOrderedBitAssignments` 返回空表、`generateFlagsFieldSerialization` 什么也不
   发。`bytecode.dawn` 的 `float_op_has_flags` 是黑名单形态，七条全部进黑名单。**多写一个
   flags 0 在层 0 与层 1 都是隐形的**：渲染器根本不打印 flags，而 flags 0 正是一条**有**可选
   字段的操作会合法写出的值；但字节流会长一个字节，读者从此错开一位。变异体
   `trig-extra-flags` 只给 `sin` 多写这一个字节，`tileiras` 的原话是
   `error at offset 112: failed to get result type 0 for DivIOp`（这个 kernel 里没有 `divi`：
   `DivIOp` 是错开一位之后下一个字节解出来的东西，和 `exp` 那条注释记的
   `failed to get result type 0 for CmpIOp` 是同一种形状）。
2. **`remf` 是截断取余（C 的 `fmod`），不是 IEEE `remainder`，而这是量出来的不是抄来的。**
   方言的散文写着 `a - trunc(a / b) * b`、符号随被除数，本仓的 `std/gpu.ref_remf` 用移位相减
   把截断取余算**精确**（两个可表示数的余数本身可表示，所以这条参考实现不是意见而是答案）。
   语料 500 条 lane 里有 **248 条**「余数的绝对值超过除数的一半」，那正是 IEEE `remainder`
   会给出另一个答案的地方；另有 106 条负被除数、44 条 `|a| < |b|`。本机 3080 上
   `remf` 那一段的 scaled miss 是 **0.0**，逐位相同。所以设备确实跑截断取余，且这句话有
   语料撑着：换成 IEEE 语义会在 248 条 lane 上红。
3. **`atan2` 的操作数是分子在前，而操作数的名字会把人带沟里。** `Ops.td` 把两个操作数叫
   `x` 和 `y`（按这个顺序），而 C 的 `atan2` 是 `y` 在前；真正说了算的是紧挨着的那句散文
   「the arc tangent of the ratio of first and second input arguments x / y」，所以方言的 `x`
   是 C 的 `y`。**按名字读会把两个操作数读反**，这就是层 2 变异体
   `atan2-operands-swapped`（它不是稻草人，是一个仔细的人真会走的那条路）。语料把四个象限
   与两条轴都放进去：99 条第二象限、100 条第三象限、99 条 `y = 0`（分子两种符号都有）、
   1 条原点 `atan2(0, 0)`，全部与 C 的约定一致（原点答 0）。**负零不进语料**：这棵树上的
   `Float` 造不出负零，而 `atan2(±0, ±0)` 的四种答案要靠负零才分得开。
4. **本机 3080 的逐操作误差**（scaled miss，1.0 就是 `atol = rtol = 1e-5`）：
   `sin=1.37e-11 cos=1.42e-11 tan=2.71e-11 sinh=2.50e-10 cosh=2.50e-10 atan2=1.48e-11
   remf=0.0`。`sinh` / `cosh` 大一个量级不是设备差，是宿主参考走 `(e ± 1/e) / 2`、而语料到
   `|x| = 30`（`cosh(30) = 5.3e12`）时 `ref_exp` 自己的几个 ulp 被放大了。语料**不到**
   溢出边（`cosh(710)` 是无穷，而无穷不在任何容差之内，`within` 就是这么写的）。
   `tan` 的语料离极点最近 1.24e-3，最大 tan 值 806，靠的是容差的相对那一半。
5. **`trig_sweep` 不求和。** `mathops`（刀 7b）把十个超越函数加成一个总数，够抓「操作码抄错
   一行」但说不出是哪个函数的哪条 lane 动了；`trig_sweep` 把七个函数各写进输出缓冲区自己的
   一段（七段各 500 lane，同一条 tail mask 在七个基址上各用一次），于是每个函数的每条 lane
   都是一次独立比较，转录里还有一行 `ops` 分别记七个 miss。`sin-as-cos` 只红第一段，这是
   分段的直接好处。

**刀 T1 的第二件事：leetgpu 61 不需要三角函数，而这是同一个反转的第二例。** §2.4 的预研写着
「61 靠三角函数」，开工按刀 9 与刀 21 的规矩逐条核签名，答案又在签名里：
`solve(Q, cos, sin, output, M, D)`，题面还额外保证两张表是 half-split（第 `j` 列与第 `j + D/2`
列相等），**`cos` 与 `sin` 是输入缓冲区**。刀 21 在 93 上记过一模一样的反转，理由也一样。
于是 61 这一行是刀 18 那种「把已经付过钱的机制花掉」的行，而它落在这把刀里是因为它的 kernel
正好是这一族的**kernel 级控制**：`rope` 一条三角函数都不走，三条变异体一条都不许动它。
真正卡在三角函数上的是 **76**（角度由 `2π/19` 与位置在 solve 内部算出，另外还是 11 步自回归
带 argmax 的序列）与 **39**（FFT 的旋转因子，另外还要每级一次 launch），本刀都不取。
`rope` 是**逐位档**，而且和 leetgpu 33 一样靠代数不靠语料：两个乘、一个加减，IEEE 754 全要求
正确舍入，两边的顺序都由下标固定，宿主参考的 `+ (-x2) * s` 就是 kernel 的 `- x2 * s`；实测
miss 恰好 0.0。

**台账那本账的一处约定要改。** `features.txt` 的表头原来写着「`T` 前缀表示还没做」，因为 T0
落地时一条操作码也没加。T1 是第一把真加操作码的覆盖刀，于是这句不再成立：现在
`check.py` 里有一个 `LANDED_KNIVES` 集合，两个方向都查：`implemented` 的行不许指向一把没人
动过的刀，`unimplemented` 的行也不许指向一把已经落地的刀（那把刀本该欠着它）。自检里各有
一条负控。

## 7. 刀序

种子轮通则：新 std 模块与新包都不被 `selfhost/src` 使用，预期零轮（`prev-diff.sh:62-64`
只要求 N−1 jar 能编 HEAD selfhost）。Fs 的那条教训（`std/io.dawn:410-416`：io 函数不能在
声明 `Fs` 的同一版里改走 `Fs` 操作）在这里不触发，因为没有任何既有 std 函数要改走 `Gpu`。

| 刀 | 今天写不出的断言 | 改动面 | 验收 | 负控 | 人日 |
|----|-----------------|--------|------|------|------|
| **1 宿主效果 + 假设备**（已落地） | 「一个 `!Gpu` 程序在没有 GPU 的机器上跑完 vadd 并得到正确答案」 | `std/gpu.dawn`、`modules.txt`、`std.gpu.core` golden、checker-corpus 一条幻影 must-red、opaque-twin 第三种标记与语料 | `dawn test --stdlib` 过 | 删掉 `upload` 的长度校验，假设备下长度不符仍 `Ok` 的测试要红 | 1 到 2 |
| **0 窄浮点**（与刀 1 并行，D3） | 「`round_bf16(a + b)` 在两个后端上与精确 oracle 逐位一致」 | `std/narrow.dawn`、`scripts/narrow-contract/`、`spike-native/narrow_round.dawn` 加 `.expect`、`opaque-twin/narrow.dawn` | 174 条以上 `differential ok`；twin 过 | ties-to-even 改成 ties-away，oracle 用例红；删量子钳位，`1e-40` 用例红 | 1 到 2 |
| **2 记录 handler + 文本 golden**（已落地） | 「同一个 kernel 体记录两次产出逐字节相同的 Tile IR 文本，且与手写 golden 相同」 | `packages/tileir`（`Dev`、`Tile[D] / Param[D] / Idx`、`TileProg`、渲染器）、`scripts/tile-golden/{vadd,vadd_f32}.mlir` 与 `run.sh`（两后端）、opaque-twin 一条语料、包测试 | golden 逐字节，两后端；`cuda-tile-translate` 本机没有，round-trip 推迟到刀 3 | 渲染器少发 store 的 token 操作数，`vadd.mlir` 红；`load` 的 dtype 写死 `f64`，f32 kernel 在记录时被拒而 f64 的不动（两条都内置在 `run.sh`，两后端各验） | 2 到 3（实报 1；门禁 17s 本机，落在 `test` job，budget 323s → 357s） |
| **3 字节码写入器 + CI 层 1**（已落地） | 「`tileiras --gpu-name sm_86` 接受我们写的字节码并产出 cubin」 | `packages/tileir/src/lower.dawn`（两个消费者共用的指令表，渲染器改吃它、文本 golden 逐字节未动）与 `bytecode.dawn`（约 330 行含测试，比估的 1500 少：只编码指令表装得下的十三种操作）、`scripts/tile-golden` 加 `*.tilebc` golden、`toolchain.txt`、`install-tileiras.sh`、三个写入器变异体，`gates.yml` 新 job `tile` | 本机 `tileiras` 13.3.36 接受，8320 字节 cubin（§6.1）；CI `tile` job | 三个写入器变异体各被 `tileiras` 以具名报文拒绝（§6.2） | 4 到 6（实报 1；`run.sh` 本机 40 s，`tile` job budget 220 s planning value） |
| **4 `with_gpu_real` + 本机对拍**（管线落地，GPU 对拍待驱动） | 「GPU 算出的 vadd 与假设备逐位一致」 | `RtGpu` 加八个 intrinsic（六操作 + 装模块 + close）、`dawn_rt.c` 的 `dlopen libcuda`（约 300 行 C）、JVM `dawn/rt/Gpu` 拒绝类、`with_gpu_real`、`scripts/tile-gpu-diff/{run.sh,vadd_diff.dawn,ledger.txt}`、`gates.yml` 的 `--check` 步；parity 脚本不必动 | 本机 `run.sh` 走到 `cuModuleLoadData` 被 560.94 拦住，台账记 `blocked`；CI 台账门绿 | `download-short`（handler 少取一个元素）对拍在 560.94 上就红；`grid-zero`（launch 传 0 block）在 560.94 上 SKIP 并明说原因，升驱动后要红；台账 commit 写成非祖先，`--check` 红 | 3 到 4（实报 1；`run.sh` 本机 25 s，`--check` 亚秒，`tile` job budget 不变） |
| **5 结构化控制流 + 第二个 kernel**（已落地） | 「带 `d_for` 的归约 kernel 与假设备逐位一致」 | `d_for / d_for2` 普通函数加 `t_loop_begin / t_loop_end` 与三个索引算术操作、区域栈、token 穿过循环携带值、`For` 的降低 / 渲染 / 字节码区域编码、`sum` kernel 与 `std/gpu.sum_ref`；`d_if` 未做（§5.2） | `scripts/tile-golden` 加 `sum.mlir / sum.tilebc`、层 1 含 `FUNC GLOBAL sum`；本机对拍归刀 4 的脚本 | 循环后 token 不换（`loop-token-not-carried`）与区域栈弹反（`region-stack-pop`）→ 降低时按名拒绝；写入器不回滚值索引（`for-results-not-rolled-back`）→ `tileiras` 红 | 3 到 4（实报 1；`run.sh` 本机 100 s，`tile` job budget 340 s planning value） |
| **6 BF16 tile**（落地，GPU 对拍待驱动） | 「设备 bf16 `addf` 与 `narrow.round_bf16(f64 加)` 对全部 65536 个 bf16 值对加随机对逐位一致」 | `gpu.BF16` 标记与 `element_bytes`、`narrow.bf16_bits / bf16_of_bits`、`pack_bf16 / unpack_bf16` 与两个 `Bytes` 版 intrinsic（`builtins.dawn` 镜像同步）、假设备按格式舍入并把 `dtypes` 交给参考实现、`vadd_bf16` 的 `.mlir / .tilebc` golden、对拍脚本三组 bf16 语料、台账门加 `std/narrow.dawn` | 层 0 / 1 本机与 CI 绿（`FUNC GLOBAL vadd_bf16`）；假设备 65536 对 = narrow；本机对拍走到 `cuModuleLoadData` 被 560.94 拦住，台账记 `blocked`（§6.4） | 计划的「设备侧 rounding 改 `approx`」在 560 上验不了，换成层 0 / 1 能红的等价物：`addf-no-rounding`（渲染器丢掉 `rounding<nearest_even>`，`vadd_bf16.mlir` 红；写入器那一半 `tileiras` 每种模式都收，只有设备能看见，故不设变异体）与 `bf16-tag-as-i16`（写入器 bf16 标签改 i16，`tileiras` 拒绝）；打包层 `pack-truncates`（`round_bf16` 漏掉、`bf16_bits` 截断）在 std 测试与 560 上的回读都红；假设备上传不舍入，格点外那组 std 语料红 | 2（实报 1；`run.sh` 本机 91 s，`tile-gpu-diff/run.sh` 26 s） |
| **7a 边界与逐元素**（已落地） | 「一个长度不是 tile 宽度整数倍的向量，最后一块越界的 lane 既不读也不写，且设备算得与手写参考逐位一致」 | `Dev` 加 `t_load / t_store` 的可选 mask 与 pad、`t_constf / t_consti / t_iota / t_lanes / t_unaryf / t_binaryf`（`t_addf` 并入）`/ t_fma / t_cmpf / t_cmpi / t_select`；包内 `I32 / I1` 两个 tile 元素格式标记；`lower` 的 `LoadPtr / StorePtr` 带可选操作数、`ConstInt / ConstFloat / FloatUn / FloatBin / FloatFma / CmpFloat / CmpInt / SelectTile`；`bytecode` 加 11 个 opcode 与 mask / paddingValue 两个 flag 位、`ieee_bits` 纯算术拼位模式；`std/gpu` 五个带 `n` 的参考实现；`scripts/tile-golden` 六个 kernel；`scripts/tile-gpu-diff/mask_diff.dawn`；`scripts/leetgpu-diff` 台账与门 | 层 0/1 六个新 golden，`FUNC GLOBAL` 六个；层 2 本机 3080 六个 kernel 逐位一致（含 mask 保住的尾部 lane）；leetgpu 1 / 8 / 21 / 23 / 31 / 62 可解 | `mask-all-true`（降低时把 `cmpi` 换成恒真 `i1` 常量）→ 层 0 变、层 1 收、**层 2 六个 kernel 全红**；`load-pad-flag-as-token`（padding 的 flag 位改成 token 的）→ 文本不动、字节同长，`tileiras` 丢流 | 2 到 3（实报 1；`tile-golden/run.sh` 本机 122 s → 129 s、`tile-gpu-diff/run.sh` 26 s → 46 s） |
| **7b 归约、超越函数与两档判词**（已落地） | 「设备的归约与手写参考在一个折叠顺序不可见的语料上逐位一致，而带 `exp` 的 kernel 在 `atol = rtol = 1e-5` 下一致」 | `Dev` 加 `t_spread / t_reduce_begin / t_reduce_end / t_if_begin / t_if_else / t_if_end`，`t_unaryf / t_binaryf` 的名单加十个超越函数；`Scalar[D]` 与 `RedId` 两个新公开类型、`spread / d_reduce / d_reduce2 / d_if / d_for3 / d_for4 / s_*` / 六个 `idx_*` 比较；宽度 0 表示 rank-0 tile；`prog` 的区域栈变成四种 `Frame` 的 ADT、归约与 `if` 区域内禁访存；`lower` 加 `ReduceTile / IfElse / YieldVals` 与 `close_scope`（`if` 的 then 分支降两遍读类型）；`bytecode` 加 13 个 opcode、`ArrayAttr` 里的自包含属性、zigzag 与 u64 varint、两区域编码；`std/gpu` 加 `ref_exp / ref_log / ref_sqrt` 与十个参考实现；十三个 kernel 与它们的 golden；`scripts/tile-gpu-diff/red_diff.dawn`（两档判词 + 顺序探针）；`problems.txt` 加十行、`check.py` 加档位对账 | 层 0/1 十三个新 golden，`FUNC GLOBAL` 十三个；层 2 本机 3080 十三个 kernel 全绿（逐位 6、容差 7，最大误差 8.3e-11，是容差的 1e-10 倍）；leetgpu 4 / 5 / 17 / 27 / 35 / 50 / 52 / 68 / 107 / 108 可解，累计 16 / 97 | `reduce-identity-wrong`（求和 identity 0.0 → 1.0）→ 层 0 变、层 1 **收**、层 2 八个带求和的 kernel 红、另外五个不动；`softmax-no-max-subtract`（不减最大值）→ 层 0/1 都收，层 2 在 1000 附近的语料上溢出成 NaN，只有 softmax 红。另外补上层 1 的一个洞：`tileiras` 会退出 0 还打印 `error:`（f64 `tanh` 带 `nearest_even`），`assemble` 改成两条都要过 | 2 到 3（实报 1；`tile-golden/run.sh` 本机 123 s → 188 s、`tile-gpu-diff/run.sh` 40 s → 91 s） |
| **8 二维 tile、多维 grid 与 `mmaf`**（已落地） | 「设备算出的矩阵乘积、转置与四种归一化与手写参考在 `atol = rtol = 1e-5` 下一致，而 grid 的第二根轴真的被启动了」 | 包：`n: Int` → `shape: List[Int]` 全线（`Dev` / `TileOp` / `Instr` / `render.ty` 的 rank ≥ 2）、以元素为单位的任意 stride 的指针梯子（零新 opcode）、`t_mmaf`（0x49）、`d_reduce_dim`（`dim` 不再只有 0）、`tile_at` / `row_major` / `load_strided` / `store_strided`；宿主：`gpu_launch_host` 的 `grid` 换成 `gx, gy, gz`（`dawn_rt.c` / `dawn_rt.h` / JVM 拒绝类 / `types.dawn` / `builtins.dawn` 镜像 / `rtsrc.dawn`），`launch3` 与仍是一维的 `launch`；`std/gpu` 七个参考实现；七个 kernel 与它们的 golden；`scripts/tile-gpu-diff/mm_diff.dawn`；`problems.txt` 加六行 | 层 0/1 七个新 golden，`FUNC GLOBAL` 七个；层 2 本机 3080 七个全绿（逐位 1、容差 6，最大 miss 1.02e-10，是容差的 1e-10 倍）；leetgpu 2 / 30 / 40 / 83 / 105 / 113 可解，累计 22 / 97。刀 7a / 7b 的 23 个 golden 一字节没动 | `grid-y-ignored`（C 运行时把 gridDimY 写死 1）→ 层 0 与层 1 **都看不见**，层 2 只有 grid 有第二根轴的四个红；`mma-acc-not-carried`（K 循环不携带累加器）→ 层 0 变、层 1 收，层 2 只有 `matmul` 红 | 4 到 6（实报 1；`tile-golden/run.sh` 本机 227 s → 233 s、`tile-gpu-diff/run.sh` 91 s → 99 s） |
| **9 任意 stride 的指针梯子**（已落地） | 「设备算出的转置、卷积、池化与模板与手写参考**逐位**一致，而两维 stride 没有被对调」 | 包：`permute` / `axis_strides` / `coord` / `and_mask` / `in_range` / `axis_mask`（**零新 opcode**，全是已有的 `iota / muli / addi / offset / cmpi / select`；`load_strided` 与 `store_strided` 刀 8 就有了，公开面仍是「shape 与 strides 两张表」而不是 `Layout` 记录，理由写在 `dev.dawn` 的 `permute` 头上：`shape` 同时是每个算术操作的参数，记录只会让每隔一次调用就要拆一次包）；`std/gpu` 八个参考实现；九个 kernel 与它们的 golden；`scripts/tile-gpu-diff/stride_diff.dawn`；`problems.txt` 加九行 | 层 0/1 九个新 golden，`FUNC GLOBAL` 九个；层 2 本机 3080 九个**全部逐位一致**（这一刀没有容差档：只有取址变了）；leetgpu 3 / 9 / 10 / 28 / 42 / 63 / 66 / 69 / 90 可解，累计 31 / 97。刀 7a / 7b / 8 的 30 个 golden 一字节没动 | `stride-row-major-swapped`（转置的输出布局取成输入的两个维度）→ 层 0 变、层 1 收，层 2 只有 `transpose_tail` 红，6000 个 lane 里 5880 个错位；**方阵会放过它**，因为 `rows == cols` 时两个表达式是同一张表，连字节都不动，所以矩阵取 100 × 60。`ladder-strides-reversed`（降低时每一维取对面那一维的 stride）→ 六个 kernel 的字节动、`tileiras` 全收，层 2 **只有 `depthwise_conv1d` 红**：把一个 kernel 里的每张布局一起反过来，等于把 tile 自己的两根轴换名，方 tile 上会对消（4 × 32 的 tile 躲不掉）。这条记下来是因为意外本身就是证据：降低层的 stride 对调在方 tile 上是看不见的。`halo-one-lane-short`（模糊 kernel 的 tap 边界少一格）→ 层 0 变、层 1 收，层 2 只有 `gaussian_blur` 红 | 1 到 2（实报 1；`tile-golden/run.sh` 本机 241 s → 263 s、`tile-gpu-diff/run.sh` 99 s → 129 s） |
| **10 整数 tile、i32 缓冲、位运算与转换**（已落地） | 「设备算出的计数、子数组和、哈希链与整数算术全家桶与手写参考**逐位**一致，而这一次逐位不靠语料而靠代数」 | 包：`Dev` 加 `t_unaryi` / `t_binaryi` / `t_convert` 三个操作（覆盖 20 个 opcode）；公开面 `add_i`…`shr_u`（`shri` 与 `shru` 是同一个 opcode 的两种 signedness）、`neg_i` / `abs_i` / `mulhi_i`、`s_addi` / `d_reduce_i`、五个转换 `int_to_float` / `float_to_int` / `mask_to_int` / `int_to_mask` / `bits_to_float` / `bits_to_int`；`prog` 三个 `TileOp` 与三张白名单；`lower` 的 `IntUn` / `IntBin` / `Cast`（`addi` / `muli` 复用梯子已有的 `AddInt` / `MulInt`）；`bytecode` 加 20 个 opcode 与 `int_op` / `int_attrs` / `cast_op` / `cast_attrs` 四张表，逐条读自 `Ops.td` 与 `BytecodeGen.cpp`；渲染器给 i32 常量做回绕（`0x9E3779B1` 在 i32 lane 里是 -1640531535）。宿主：`I32` 从包搬进 `std/gpu`（i32 从此既是 tile 格式又是缓冲格式）、`element_bytes("i32") = 4`、`round_to` 的向零截断加二补数回绕、`wrap_i32`、`pack_i32` / `unpack_i32` 与真设备的字节通道；四个参考实现；四个 kernel 与它们的 golden；`scripts/tile-gpu-diff/int_diff.dawn`；`problems.txt` 加五行 | 层 0/1 四个新 golden，`FUNC GLOBAL` 四个；层 2 本机 3080 四个**全部逐位一致**，且这一档是**代数**给的不是语料给的（i32 结果只有一个值，整数加法模 2^32 精确结合交换，`List[Float]` 通道对 i32 无损）；leetgpu 24 / 43 / 44 / 45 / 47 可解，累计 36 / 97。刀 7a/7b/8/9 的 39 个 golden 一字节没动 | `shri-always-logical`（写入器把 `shri` 的 signedness 写成 unsigned）→ 层 0 **看不见**（渲染器另有一张表）、层 1 收，层 2 只有做算术右移的 `rainbow` / `int_ops` 红，另外两个不动；语料必须铺满整个 i32 值域，两种右移在非负操作数上是同一件事。`exti-sign-extends`（掩码有符号展宽成 0 与 -1）→ 层 0 看不见、层 1 收，层 2 只有 `count_eq` / `int_ops` 红。计划里的 `ftoi-rounds-instead-of-truncates` 实测被 `tileiras` 拒，改登记为层 1 的写入器变异体。**真正被层 2 抓到的错是 `divi` 的属性布局**：把 `DefaultValuedAttr` 当成可选字段多写了一个 flags 字节，在只有一个属性的操作上与 `overflow none` 同字节因而全绿，`divi` 有两个属性于是设备做了无符号除法，`int_ops` 在负被除数上 499 lane 红 | 2 到 3（实报 1；`tile-golden/run.sh` 本机 260 s → 279 s，加第十二个变异体后 299 s；`tile-gpu-diff/run.sh` 129 s → 154 s） |
| **11 宿主加宽：多输出、原地、f16、i8**（已落地） | 「一个 kernel 填两个缓冲、另一个改写它自己读的那个，设备与手写参考在两个缓冲上都逐位一致」 | 宿主：参考实现签名 `-> List[Float]` → `-> List[(Int, List[Float])]`（写回哪几个 arg 位）与适配器 `last_out`、`gpu.bad_write_back`、`F16 / I8 / U8` 三个格式标记与 `element_bytes` / `round_to` / `wrap_i8` / `wrap_u8` / `pack_f16` / `pack_i8` / `pack_u8` 与它们的 unpack、真设备的 `pack_to` / `unpack_from` 两张分发表；`std/narrow` 加 `fp16_bits` / `fp16_of_bits`（照 bf16 抄，换掉每一个常数）。包：`ftof`（0x2A）与 `mmai`（0x4A）两个 opcode、`float_to_float` / `ext_u8` / `trunc_u8` / `i8_const`、`t_mmai` 与 `MmaI` / `IntMma` 一路、`f16` 与 `i8` 的常量载荷。八个 kernel 与它们的 golden；`scripts/tile-gpu-diff/wide_diff.dawn`（第一支每个 case 缓冲格式不同、且要下载多个缓冲的对拍程序）；`problems.txt` 加六行 | 层 0/1 八个新 golden，`FUNC GLOBAL` 八个；层 2 本机 3080 八个**全部逐位一致**；leetgpu 7 / 19 / 22 / 32 / 57 / 58 可解，累计 42 / 97。刀 7a…10 的 43 个 golden 一字节没动。**`--remarks=tensorcore` 实测**：f16 `mmaf` 与 int8 `mmai` 在 sm_86 上**都上 tensor core**（`Tensor-core SM80`，形状分别是 `[16, 8, 16]` 与 `[16, 8, 32]`），刀 8 「只有 bf16 上」的记录只是没试过这两种 | `inplace-writes-copy`（假设备把写回落到一个没人有的句柄上）→ 层 0 层 1 **按构造**盲（`std/gpu` 不发射任何 Tile IR），层 2 八个全红，且两个原地 kernel 读回来的是**语料**而另外六个读回来的是哨兵，门禁两样都查。`f16-rounds-like-bf16`（f16 打包用 `round_bf16` 舍入）→ 层 0 层 1 盲，层 2 **只有 `f16_ops` 红**：`dot_f16` 的小整数与两个 GEMM 的半整数在 bf16 上也精确，三个同样上传 f16 缓冲的 kernel 是对照组，语料是这条判词的一半。`u8-reads-signed`（真设备用 `unpack_i8` 读 u8 缓冲）→ 只有 `invert` 红，且只因为它的语料铺满整个八位值域 | 2 到 3（实报 1；`tile-golden/run.sh` 本机 279 s → 330 s、`tile-gpu-diff/run.sh` 154 s → 180 s，两条都随机器负载在 ±15% 内浮动） |
| **12 gather / scatter（数据相关索引）**（已落地） | 「设备用一个从缓冲里读出来的索引 tile 取址，与手写参考**逐位**一致；越界的 lane 被掩码挡住，重复的索引在 gather 上合法而在 scatter 上无解」 | 包：**零新 opcode**。`Dev` 加 `t_gather` / `t_scatter` 两个操作，`prog` 两个 `TileOp`，`lower` 的 `index_pointers`（与 `pointers` 同样的 reshape / broadcast / offset 三条，只是 `offset` 的偏移操作数换成别人算好的 tile）；公开面 `gather` / `gather_masked` / `scatter` / `scatter_masked` 与 `or_mask`。宿主：`std/gpu` 四个参考实现（`token_embed_ref` / `sort_ref` / `merge_ref` / `scatter_perm_ref`，`sort_ref` 自带插入排序，因为 `std/list.sort` 要 `Ord` 而 `Float` 没有）。四个 kernel 与它们的 golden；`scripts/tile-gpu-diff/gath_diff.dawn`；`problems.txt` 加三行 | 层 0/1 四个新 golden，`FUNC GLOBAL` 四个；层 2 本机 3080 四个**全部逐位一致**（这一刀也没有容差档：只有取址变了，两个排名 kernel 折叠的是 0 与 1）；leetgpu 15 / 71 / 106 可解，累计 45 / 97。刀 7a…11 的 51 个 golden 一字节没动 | `gather-mask-dropped`（`gather_masked` 不再交出 mask 与 pad）→ 层 0 变、层 1 收（无掩码的 load 也是 load），层 2 **只有 `token_embed` 红**：它 104 个 id 里有 11 个在表外，掩码一丢就读到地址钳位落到的那一行。它答的是**错数**而不是崩溃，因为 kernel 除了掩码还钳了地址——不然层 2 只会记一个 `blocked`，而 `blocked` 不是差异。`scatter-unpermuted`（`scatter_perm` 写在 lane 自己的下标上）→ 层 0 变、层 1 收，层 2 只有它红，264 个 lane 错 255 个。`rank-scatter-in-lane-order`（`sort_rank` 算完排名却把值顺序存下去）→ 只有它红，且它的 scatter **不带掩码**，是前一条够不着的那半个公开面。`merge_rank` 没有自己的变异体，这是量出来的而不是漏的：任何一种破坏它「一边严格一边宽松」的改法都会让两组排名撞到同一个元素上，而重复的 scatter 目的地在设备上**无解**——一个预期行为是未定义的变异体不是门。它是三条变异体的对照组 | 1 到 2（实报 1；`tile-golden/run.sh` 本机 386 s → 423 s、`tile-gpu-diff/run.sh` 180 s → 205 s） |
| **13 `scan`**（已落地） | 「设备算出的前缀和、分段前缀和、一阶线性递推与反向扫描与手写参考在各自的档位下一致，而区域的两个参数没有被认反、`reverse` 没有被忽略、独占前缀没有被写成含本位的」 | 包：`scan`（0x5E）一个新 opcode，区域编码与 `reduce` 同一套，属性按声明序 `dim` / `reverse` / `identities`（`reverse` 是 `BoolAttr`，写入器按 `BytecodeWriter.cpp` 的 bool 路径写**一个字节**，不是可选字段因而不进 flags）；`Dev` 加 `t_scan_begin` / `t_scan_end`，`prog` 的 `Scan` 与 `ScanFrame`，`lower` 的 `ScanTile`（**结果类型就是操作数类型**，归约才丢维），渲染器一行；公开面 `d_scan` / `d_scan_i` / `d_scan2` 与 `s_mulf` / `s_fma` / `s_eq` / `s_maxi` / `s_const`。**顺带改正 `d_reduce` 一族的区域参数命名**（见 §6.6，纯改名，golden 一字节没动）。宿主：`std/gpu` 七个参考实现。七个 kernel 与它们的 golden；`scripts/tile-gpu-diff/scan_diff.dawn`（第九支对拍程序，带扫描顺序探针）；`problems.txt` 加七行 | 层 0/1 七个新 golden，`FUNC GLOBAL` 七个；层 2 本机 3080 七个全绿（逐位 2、容差 5，最大 miss 3.0e-10，是容差的 3e-10 倍）；leetgpu 16 / 51 / 70 / 72 / 82 / 94 / 110 可解，累计 **52 / 97**。刀 7a…12 的 55 个 golden 一字节没动 | 层 1：`scan-result-drops-the-dim`（写入器给 scan 写 `reduce` 的结果类型）→ 文本不动、字节同长，`tileiras` 拒绝并说 scan 的结果类型就是操作数类型。层 2 两条：`scan-reverse-ignored`（写入器把 `reverse` 写死 false）→ 层 0 **看不见**（渲染器印的是记录里的 `reverse=true`）、层 1 收，设备上**只有 `gae` 红**，而且也只有它的字节动，另外六个在字节与设备两处都是对照组；`exclusive-scan-as-inclusive`（`compact` 用含本位的前缀计数当目的地）→ 层 0 变、层 1 收，设备上只有它红，`seg_scan` 在浮点上走同一步但走的是另一个表达式，是对照组 | 1 到 2（实报 1；`tile-golden/run.sh` 本机不分片 **330 s → 464 s**（+41%，同一棵树同一小时背靠背；斜率比前几刀的每 kernel 约 9 s 陡，因为 `ssm_scan` 是 rank-2 的双操作数 scan、cubin 18 KB，而十三个变异体每个都要重编长了七个 kernel 的 `kernels.dawn`），两片 **230 s / 224 s**；`tile-gpu-diff/run.sh` 在基线树 03967a30 上 **201 s** → 本树 **198 s**，也就是没动：七个 kernel 的汇编与一次原生构建加起来比这台机器的噪声还小） |
| **14 原子操作**（已落地） | 「两个 lane 指向同一个元素时，设备的直方图与手写参考逐位一致；而这一条判词不是语料碰巧成立的，把同一个 kernel 放到无冲突的语料上，「原子」与「读改写三条指令」就变成同一个程序」 | 包：`atomic_rmw_tko`（0x08，模式枚举 and / or / xor / add / addf / max / min / umax / umin / xchg）与 `atomic_cas_tko`（0x07）两个新 opcode，取址方式与 gather / scatter 相同（一张 i32 索引 tile，复用 `index_pointers`）；`Dev` 加 `t_atomic_rmw` / `t_atomic_cas`，`prog` 两个 `TileOp` 与一张模式白名单，`lower` 的 `AtomicRMWPtr` / `AtomicCASPtr`，渲染器两行，`bytecode` 两个 opcode 与三张枚举表（`AtomicRMWMode` / `MemoryScope` / `MemoryOrderingSemantics`）；公开面 `atomic_rmw` / `atomic_rmw_masked` / `atomic_add_masked` / `atomic_cas` / `atomic_cas_masked`。宿主：`std/gpu` 两个参考实现。两个 kernel 与它们的 golden；`scripts/tile-gpu-diff/atom_diff.dawn`（第十支对拍程序，带 `--corpus unique` 控制语料与冲突计数）；`problems.txt` 加一行 | 层 0/1 两个新 golden，`FUNC GLOBAL` 两个；层 2 本机 3080 两个**全部逐位一致**（这一刀没有容差档，且和刀 10 一样是代数给的：模 2^32 的整数加法精确结合交换，`cas_swap` 每槽一个 lane 根本没有顺序）；leetgpu 13 可解，累计 **53 / 97**。刀 7a…13 的 62 个 golden 一字节没动 | 层 1 两条：`atomic-rmw-claims-weak-ordering`（写 `weak` 而不是 `relaxed`）→ 文本不动、字节同长，`tileiras` 说这两个操作的内存序只能是 relaxed / acquire / release / acq_rel；`atomic-cas-writes-an-rmw-mode`（给 CAS 也写一个 `mode` 字节）→ 字节多一个，读者从那里起每个操作数都错一格（`writer_mutant_checks` 因此第一次需要 `func-one-long` 这个形状）。层 2 两条：`atomic-as-plain-store`（包的 `atomic_add_masked` 改发 gather + `addi` + scatter）→ 层 0 变、层 1 收，设备上**只有 `histogram` 红**（24 个 lane 错 16 个），而且**在无冲突的控制语料上必须绿**，这一格是判词的另一半；`cas-compare-ignored`（kernel 把要写的值当成期望值交给 CAS）→ 只有 `cas_swap` 红，该换值的 34 个槽位一个也没换 | 1（实报 1；`tile-golden/run.sh` 本机在基线树 `a7d2479e` 与本树上背靠背：不分片 **402 s → 474 s**（+18%），两片 **208 s → 244 s** 与 **216 s → 214 s**；第一片的 planning value 600 s → **628 s**、`timeout-minutes` 30 → 32，第二片的 588 s 不动（本机算出来是 568 s，低于它）；`tile-gpu-diff/run.sh` 本机 **242 s**） |
| **15 `erf` 的组合实现**（已落地） | 「设备算出的高斯误差门与手写参考在 `atol = rtol = 1e-5` 下一致，而这一次判词的主语是**近似**而不是设备：容差不是宽到什么都放过，语料也不是碰巧覆盖了近似最难的那一半」 | 包：**零新 opcode**。`tileir/dev.erf` 是 Abramowitz & Stegun 7.1.26 的五项有理式乘 `exp(-x^2)`，负半轴走奇对称的一个 `select`；用到的 `absf / mulf / addf / divf / negf / exp / subf / cmpf / select` 刀 7a 与 7b 就都有了。宿主：`std/gpu.ref_erf`（全正项级数，精度约 4e-15，**不是**同一个有理式）与两个参考实现 `erf_sweep_ref` / `geglu_ref`。两个 kernel 与它们的 golden；`scripts/tile-gpu-diff/erf_diff.dawn`（第十一支对拍程序，带 `--corpus positive` 控制语料、三个语料计数与一条误差探针）；`problems.txt` 加一行 | 层 0/1 两个新 golden，`FUNC GLOBAL` 两个；层 2 本机 3080 两个都在容差档内一致，**实测 7.1.26 的绝对误差 1.3797e-7**（`erf_sweep`，无乘子）与 3.6356e-7（`geglu`，被乘子放大），`run.sh` 把前者钉在 `(0, 1.5e-7]`；leetgpu 65 可解，累计 **54 / 97**。刀 7a…14 的 64 个 golden 一字节没动。**74 GPT-2 Block 不进来**：核实题面后它的前馈层用的是 `F.gelu(approximate="tanh")`，一道 erf 也不用，而且是一串要中间缓冲的乘积链 | 层 1 **零条**（没有新字节形状可拒，这是零新 opcode 的另一面）。层 2 两条，都在包的 `erf` 里因而两个 kernel 一起动，分开它们的是**语料**：`erf-tanh-approx`（换成 PyTorch `gelu(approximate="tanh")` 的公式）→ 误差 3.6e-4，是 atol 的 36 倍，**两个 kernel 在两个语料上都红**，它证明的是容差档没选宽；`erf-sign-not-flipped`（去掉奇对称的 `select`）→ 主语料上两个都红，**在没有负 lane 的控制语料上必须全绿**，它证明的是语料在干活 | 0.5（实报 1；这一刀的墙钟量不出来，见 §6.5：机器整天有别的活，两轮成对测量的分片增量之和都大于同一轮不分片的增量。能量的是每一项的成本，`--only` 下 `erf_sweep` 16.70 s / `geglu` 17.03 s 对 `silu` 16.50 s，就是一个普通 kernel 的价钱。planning value 按 244 + 9 与 214 + 9 推：第一片 628 s → **646 s**、`timeout-minutes` 32 → 33，第二片 586 s 低于已写的 588 s 不动；646 s 离 660 s 的 run-pole 只剩 14 s。`tile-gpu-diff/run.sh` 本机 **244 s**） |
| **16 多 launch 的判词**（已落地） | 「设备把一串 launch 跑成一个程序：一次上传、N 次 launch、一次下载，中间结果从不离开设备，而它与手写参考的一致不靠任何一次 launch 单独成立；同时这条判词在序列被打乱、被截短、被喂回旧数据时必然红，在中间缓冲经宿主原路返回时必然绿」 | **包一行没改，`std/gpu` 的假设备与真机 handler 一行没改，运行时一行没改**——四层今天就能跑多 launch（假设备的缓冲表跨 launch 存活并把当前内容交给参考实现，真机的 cubin 表本来就按 kernel 名索引，`cuLaunchKernel` 走 null stream 天然有序）。缺的只是**怎么说**一个序列和**怎么判**它。harness：`scripts/tile-gpu-diff/seq_diff.dawn`（第十二支对拍程序）把序列做成数据——具名缓冲 `Buf`、一条 launch 一个 `Step`（kernel、grid、按名字给的实参）、`Seq`（缓冲、步骤、判词读哪个缓冲、哪一步读了更早一步写的哪个中间缓冲），加一个 `repeat(n, body)`，`n` 是宿主值、每一轮可以点不同的缓冲（矩阵幂就是靠它在两个累加器之间乒乓）。宿主：`std/gpu` 五个参考实现（`matmul_bt_ref` / `lora_out_ref` / `row_softmax_ref` / `swiglu_act_ref` / `apsp_step_ref`，其余三处复用 `matmul_ref`）。十一个 kernel 与它们的 golden。门禁：`problems.txt` 的 `kernel` 字段允许 `+` 连接，`check.py` 的 `case != kernel` 改成「case 声明的 kernel 集合等于本行」，权威是层 2 程序自己的 `sequence_kernels()`；`reference` 字段同样按 `+` 一一对应。CI：`tile-golden` 由两片分成**三片** | 层 0/1 十一个新 golden，`FUNC GLOBAL` 十一个；层 2 本机 3080 六条序列全绿（**逐位 1、容差 5**）。**档位是操作的性质不是 launch 数的性质**：`apsp` 十六次 launch 全是 `minf` 与 `addf`，仍然逐位；另外四条含 `mmaf`，容差是**端到端**量的（参考链的第二段吃的是参考自己的第一段输出），最大 miss 1.7e-10，是容差的 1.7e-10 倍。leetgpu **6 / 37 / 73 / 84 / 85** 可解，累计 **59 / 97**。刀 7a…15 的 66 个 golden 一字节没动 | 层 1 **零条**（零新 opcode）。层 2 **四条，全部是序列这份数据的变换**，红集按名字与个数钉死（24 个 (变异体, 序列) 格里 17 红）：`second-launch-sees-stale-buffer`（驱动在读它的那次 launch 前把中间缓冲的上传内容放回去）→ 五道题全红，**对照序列 `decoupled` 必须绿**；`launch-order-swapped`（逆序发出）→ 四道题红，**`apsp` 不红，而且不是运气**：把最短路在「最后被处理的中间点」切开，两半都在那一轮之前完成了，所以 Floyd-Warshall 的轮次**可交换**，一遍跑完全部 k 与顺序无关（代数给的，同刀 10 / 14）；`last-launch-dropped` → 六条全红，这是「每次 launch 都真的发生了」那条；`grid-of-later-launch-copied-from-the-first` → **只有 `attention` 与 `swiglu` 红**，`matpow` / `apsp` / `decoupled` 本来就一个 grid 到底，而 `lora` 的中间那次 launch **不读第二根 grid 轴**，多出来的 block 重算同一块 tile、写同样的字节——grid 变异体在它加出来的 block 幂等的地方是隐形的。控制项：中间缓冲经宿主下载再上传，六条序列的判词一个都不许动。语料：每条序列印 `changed_by_first`，五道题钉在零以上、`decoupled` 钉死为零 | 2（实报 1；见 §6.5：机器有别的活，两轮三片读到 197 / 189 / 177 s 与 170 / 171 / 171 s，不分片那一对自相矛盾（494 s 与 622 s）不采信；三条预算行按较差的那一轮全部重述为 534 / 518 / 494 s，`timeout-minutes` 27 / 26 / 25；`tile-gpu-diff/run.sh` 本机 242 s） |
| **17 第二刀多 launch：一道题一个 kernel**（已落地） | 「设备把六串新的 launch 跑成六个程序，而其中四串**共用**刀 16 已经录好的两个 kernel：一个注意力变体是一条**关于分数的规则**，不是三个新 kernel；同时刀 16 那四条序列变异体在这十二条序列上的红集是逐条可预言的，包括它们**不**该红的地方」 | 与刀 16 一样：包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动。kernel：七个，`attn_causal` / `attn_alibi` / `attn_window` / `attn_sinks` / `attn_decay`（各是 `attn_scores` 加一条位置规则）与 `cce_row` / `cce_mean`。**没有第八个**：53 / 55 / 59 / 112 的第二、三次 launch 直接用刀 16 的 `attn_softmax` 与 `attn_context`，92 用它的 `attn_context`，条件是它们跑在刀 16 记录的那个形状上（ATT_M=64、ATT_N=64、ATT_D=32）。宿主：`std/gpu` 七个参考实现加两个私有辅助（`bt_dot` 把转置乘积拆到一个元素，五条规则各写一行）。harness：`seq_diff.dawn` 加六条序列，其中四条是**同一个函数**的四次调用（`masked_attn_seq(名字, kernel)`），因为四份拷贝会把「它们是同一条序列」这句话说四遍、并且总有一遍是错的 | 层 0/1 七个新 golden，`FUNC GLOBAL` 七个；层 2 本机 3080 十二条序列全绿（逐位 1、容差 11），六条新序列最大 miss 2.5e-11（容差的 2.5e-11 倍）。leetgpu **25 / 53 / 55 / 59 / 92 / 112** 可解，累计 **65 / 97**。刀 7a…16 的 77 个 golden 一字节没动 | 层 1 **零条**（零新 opcode）。层 2 仍是刀 16 那四条，矩阵从 24 格长到 **48 格**、红集从 17 长到 **39**，逐格按名字钉死。九个绿全部是**已经在案的三种形状**：`decoupled` 只被 `last-launch-dropped` 红（它没有依赖）；`apsp` 不被 `launch-order-swapped` 红（Floyd-Warshall 可交换）；`grid-of-later-launch-copied-from-the-first` 在后续 launch 幂等的地方隐形——刀 16 的 `matpow` / `apsp` / `decoupled`（一个 grid 到底）与 `lora`（中间那次不读第二根轴）之外，本刀又添两例：`decay` 的第二次 launch 是 `attn_context`，**只读第一根 grid 轴**；`cce` 的第二次是 `cce_mean`，**一根都不读**，六十四个 block 各算各的、写同一个答案。**没有一个新形状**，这本身是判词的结论：这四条变异体在这一族上的行为已经被解释干净了 | 1（实报 1；见 §6.5：三片 196 / 187 / 178 s 与 190 / 176 / 174 s，预算行重述为 532 / 514 / 496 s，`timeout-minutes` 不动；`tile-gpu-diff/run.sh` 本机 259 s） |
| **18 机制花掉：把已经付过钱的东西写出来**（已落地） | 「已有的机制能解的题，和已经解了的题，不是一回事——七道题一次 launch、一道题三次，全部用刀 7a 到 12 早就有的操作，一个 opcode 也没加」 | 包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动。kernel：八个。`matvec`（18，一次 `mulf` 加一次沿维度的归约，没有 `mmaf`）、`conv3d`（11，`conv2d` 把第三维放到 grid 上）、`subarray_sum2d` / `subarray_sum3d`（48 / 49，秩 1 的 tile 用 `divi` / `remi` 拆出二维三维坐标）、`swiglu_half`（54，`geglu` 的形状换一个 swish 门）、`dequant`（64，索引由 lane 自己的坐标算出、不从任何缓冲区读）、`mha_scores` / `mha_context`（12，注意力族的**头**是一个列切片，也就是一个基址加一个行 stride）。**没有第九个**：12 的第二次 launch 直接用刀 16 的 `attn_softmax`，因为各头的分数块首尾相接，整块就是 `heads * N` 行 `N` 列，按行做 softmax 不必知道行属于哪个头；75 一个 kernel 也没加，它的 `A` 是稠密缓冲区、参考实现就是 `torch.matmul`，所以它是 `matmul` 在另一个形状上，与 8 之于 1 同理。宿主：`std/gpu` 七个参考实现 | 层 0/1 八个新 golden，`FUNC GLOBAL` 八个；层 2 本机 3080 全绿：`mm_diff` 8 条、`stride_diff` 10 条、`int_diff` 6 条、`gath_diff` 5 条、`erf_diff` 3 条、`seq_diff` 13 条序列。leetgpu **11 / 12 / 18 / 48 / 49 / 54 / 64 / 75** 可解，累计 **73 / 97**。刀 7a…17 的 84 个 golden 一字节没动 | 层 1 **零条**（零新 opcode），层 2 **零条新变异体**——这一刀的负控是把八个 kernel 塞进五个既有族的变异体表里，看哪些该红、哪些该绿。三条结论：`ladder-strides-reversed` **预言会红、实测绿**（见 §6.5 上面的表与 `tile-gpu-diff/run.sh` 里那条注：conv3d 的 tile 是方的、两条 mask 的上限不等，本以为 mask 会破坏对称，实际不会，因为 mask 的坐标也走同一条 stride 梯子、跟着一起换轴——抵消要么全发生要么不发生）；`gather-mask-dropped` 多了一个**会 gather 的控制**（`dequant` 的每个索引都在缓冲区内，所以它的 gather 无 mask，比三个根本不 gather 的控制说得多）；两条 erf 变异体第一次有了**kernel 级的控制**（`swiglu_half` 与 `geglu` 同形不同门，两条变异体都不许动它，层 0 与设备上都不许），在此之前这一族只有语料级的控制。序列那四条：矩阵从 48 格长到 **52 格**、红集从 39 长到 **43**，`mha` 四条全红，一个新形状都没有 | 1（实报 1；见 §6.5：三片 228 / 227 / 231 s，预算行重述为 596 / 594 / 602 s，`timeout-minutes` 抬到 30 / 30 / 31；`tile-gpu-diff/run.sh` 本机 304 s） |
| **19 最后两道单 launch，与第三刀多 launch**（已落地） | 「射程内每一道**机制齐了只是没写**的题都写完了。那一桶从九题减到二题再减到零；而多 launch 那一桶还在按刀 17 的价钱掉，因为一次 launch 的复用可以架在 mask 上、grid 上，也可以架在**一个平均**上」 | 与刀 16 到 18 一样：包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动。kernel：十个。`agent_step`（14）与 `nearest_idx`（38）是同一个 N×N 成对形状的两个客户：一个 block 一个 agent / 一个点，一条 lane 是一个**配对**，自己那一对靠「打一个必输的分」去掉；后者是这棵树上唯一一个读 f64 写 i32 的 kernel。`xattn_scores` / `xattn_context`（26）是刀 18 的头布局在**两个序列长度**上，`gqa_scores` / `gqa_context`（80）把 KV 头放到第三根 grid 轴、组内序号放到第一根（`Idx` 上没有除法，所以等式要反过来写），`grpo_adv` / `grpo_row`（109），`kmeans_assign` / `kmeans_centroid`（20）。**没有第十一个**：26 与 80 的第二次 launch 是刀 16 的 `attn_softmax`，109 的第三次是刀 17 的 `cce_mean`（负号折进第二次 launch，因为负号精确，所以取负再平均等于平均再取负）。宿主：`std/gpu` 十个参考实现，其中 `kmeans_centroid_ref` 是这一族第一个**写两个缓冲区**的序列参考。harness：`red_diff` 加 `agent_step`（第一个归约**选出来的子集**的 kernel），`gath_diff` 加 `nearest_idx`（第一个把**算出来的地址本身**当答案写下去的 kernel），`seq_diff` 加四条序列，其中 `kmeans` 的 `repeat` 体是**两次** launch | 层 0/1 十个新 golden，`FUNC GLOBAL` 十个；层 2 本机 3080 全绿：`red_diff` 14 条、`gath_diff` 6 条、`seq_diff` 17 条序列（逐位 2、容差 15）。leetgpu **14 / 20 / 26 / 38 / 80 / 109** 可解，累计 **79 / 97**，「机制齐了只是没写」那一桶**清零**。刀 7a…18 的 92 个 golden 一字节没动 | 层 1 **零条**（零新 opcode），层 2 **零条新变异体**：负控仍是把十个 kernel 塞进既有的变异体表。两条结论，一条是推翻。（一）`reduce-identity-wrong` 的红集**不是**「归约的操作数是不是算出来的」。刀 7b 到 18 一直这样解释那张表，而 `agent_step` 的三次求和折的都是 `select`，字节移动、设备不动，是绿；剩下能把它与那六个分开的只有 tile 的宽度（六个红都是 1024 lane，它是 64），那是观察不是机制，所以那张表继续按名字钉六个、不再宣称规则。（二）序列那四条：矩阵从 52 格长到 **68 格**、红集从 43 长到 **58**，十个绿全在案的三种形状里，其中 `kmeans` 的 grid 绿是**为了让变异体守规矩而制造出来的**：`kmeans_centroid` 的 store 带一条 `c < KM_K` 的 mask（质心缓冲区只有四个元素，而这条变异体会把 64 个 block 抄到它头上，没有 mask 就是越界写，那是崩溃而不是答错），加了 mask 之后多出来的 block 什么都不写，于是隐形 | 1（实报 1；见 §6.5） |
| 7（期权）混合路线 | 「同一个 kernel 体经编译期发射器与经记录 handler 产出相同的 Tile 程序」 | `selfhost/src/tile/emit_tile.dawn` | 两路 `TileProg` 相等 | 不在本计划内 | 6 到 10 |

合计（不含刀 7）16 到 23 人日。字节码写入器是最大的单块，也是唯一能让 CI 的绿有信息量的
一块。每一刀的门禁改动都要报墙钟；没有一刀碰长杆。

| **20 三条注意力序列与一次消元**（已落地） | 「设备把四串新的 launch 跑成四个程序，而九个新 kernel 里没有一个只是把已经录过的东西再写一遍：leetgpu 111 的**七次** launch 里五次用的是既有 kernel，leetgpu 56 的三次 launch 只有两个 kernel。同时判词本身补上一个洞：一道有三个输出的题，不能靠看其中一个下判断」 | 包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动，**零新 opcode**。kernel：九个。`kv_scores` / `kv_context`（96，int8 缓存加逐位置 f32 scale）、`attn_bwd_mmt` / `attn_bwd_ds`（111，转置乘积与 softmax 的雅可比）、`lin_attn_s` / `lin_attn_out`（56）、`ols_gram` / `ols_elim` / `ols_beta`（33）。**复用的四处**：111 的第一、二次 launch 是刀 16 的 `attn_scores` 与 `attn_softmax`，第四次是 `attn_scores` **第二次**（`dP = dO V^T` 本来不该除 `sqrt(d)`，但消费它的 `dS` 那一行对 `dP` 线性，所以把除法提前到这次 launch、末尾那次删掉，答案一模一样），第六次是 `attn_context`，第三、七次是同一个 `attn_bwd_mmt` 跑两遍；96 的中间一次是 `attn_softmax`；56 的第二次是 `lin_attn_s` 再跑一遍，只把第二个实参换成一个**全 1 的缓冲区**（列和就是与一列 1 的乘积，复用在**操作数**上，前三刀分别在 mask、grid 与 scale 上）。宿主：`std/gpu` 九个参考实现。harness：`Seq` 的 `read: String` 改成 `reads: List[String]`，判词把它们首尾相接后比较 | 层 0/1 九个新 golden，`FUNC GLOBAL` 九个，`tileiras` 一次通过；层 2 本机 3080 二十条序列加对照全绿（**逐位 3、容差 18**）。leetgpu **33 / 56 / 96 / 111** 可解，累计 **83 / 97**。刀 7a…19 的 102 个 golden 一字节没动。**33 是第三条逐位档序列，而它的理由比另外两条强**：`apsp` 与 `kmeans` 的逐位要靠语料，33 只靠代数，它的每一个操作都是 f64 的 `addf` / `subf` / `mulf` / `divf`，IEEE 754 要求这四个都正确舍入，两边的顺序又都由 `d_for` 与下标固定，没有一棵折叠树是自由的（实测 miss 恰好 0.0）；高斯-约当不选主元也是代数给的（Gram 矩阵对称正定，顺序主子式全正） | 层 1 **零条**（零新 opcode）。层 2 **零条新变异体**：负控是把四条序列塞进刀 16 那四条变异体，矩阵从 68 格长到 **84 格**、红集从 58 长到 **72**，逐格按名字钉死。十二个绿仍是在案的三种形状，`kv` 与 `ols` 的 grid 绿落在**第一种**（一个 grid 到底）而不是第二种（幂等）：`kv` 三次 launch 都是一个 block 一个头，`ols` 全程一个 block，因为一次消元步在写每一行的同时要读主元行，两个 block 就是数据竞争。另有一条**自轴负控**：把 `std/gpu.ols_beta_ref` 读的列从 `f` 改成 `f + 1`，只有 `ols` 一条红 |
| **T0 特性台账与门禁**（已落地，目标改判后的第一刀，§2.4） | 「Tile IR 的 100 条公开操作码里，每一条都说得出实现于哪一刀、覆盖到哪一层、以及做不到那一层时的具名理由」（今天说不出：`problems.txt` 记的是题不是特性，而「还差什么」只存在于预研笔记里） | `scripts/tileir-features/`（`features.txt` 100 行加头注、`check.py` 加 `--self-test`）、`gates.yml` 的 `tree-policy` 加一步、`docs/tile-backend-design.md` §2.4 与本表、`docs/README.md` 一句 | `check.py` 绿并打印计数（实现 63 / 未实现 26 / 挂起 9 / 结构性 2；层 2 有 48 条、层 3 有 17 条）；期望集合是 `bytecode.dawn` 的 `OP_` 表，两个方向都查 | `--self-test` 十五条负控加一条阳性对照，负控含：多一个 `OP_` 而台账无行、台账少一行、码对不上、`implemented` 行声称层 2 但没有任何 golden 含这个操作、声称层 3 但不指名变异体、版本列与 13.2 / 13.3 增量表不符；阳性对照是真实输入必须绿 | 0.5（实报 0.5；门禁本机 0.03 s，自检 0.13 s，落在 `tree-policy`，budget 不动） |
| **T1 三角与浮点取余**（已落地，覆盖刀里第一把加操作码的） | 「Tile IR 的 `sin` / `cos` / `tan` / `sinh` / `cosh` / `atan2` / `remf` 这七条逐元素浮点指令，本机 3080 上每一个 lane 都与一份独立写的宿主参考对得上；而 `remf` 到底是截断取余还是 IEEE `remainder`、`atan2` 的两个操作数谁是分子，都是量出来的而不是抄散文抄来的」 | `packages/tileir`：`bytecode.dawn` 七个 `OP_` 常量加 `float_op` 七行，七条全进 `float_op_has_flags` 的黑名单（它们一个可选字段都没有）；`dev.dawn` 七个公开函数；`prog.dawn` 的名字表。`render.dawn` **一行没改**（op 名从头到尾是字符串，rounding 表里没有它们）。`std/gpu.dawn`：七个 `ref_*` 二次意见（`ref_sin` / `ref_cos` 是 Cody-Waite 分段常量加泰勒级数，`ref_atan` 是两级参数归约加级数，`ref_remf` 是移位相减的**精确**算法）加 `trig_sweep_ref` / `rope61_ref`，四个测试块。kernel 两个：`trig_sweep`（七段输出，每个函数一段）与 `rope`（leetgpu 61）。新族 `scripts/tile-gpu-diff/trig_diff.dawn` | 层 0/1 两个新 golden，`FUNC GLOBAL` 两个，`tileiras` 一次通过；层 2 本机 3080 `trig_sweep` `close:tolerance`（最大 miss 2.50e-10）、`rope` `identical:exact`（miss 0.0）。逐操作 miss：`sin=1.37e-11 cos=1.42e-11 tan=2.71e-11 sinh=2.50e-10 cosh=2.50e-10 atan2=1.48e-11 remf=0.0`。语料的十项计数由 `run.sh` 逐项钉在零以上。台账七行从 `unimplemented` 改成 `implemented`（实现 63 → **70**、未实现 26 → **19**；层 2 有 53 条、层 3 有 19 条）。leetgpu **61** 可解，累计 **86 / 97**，但 **61 一条三角函数都不需要**（`cos` 与 `sin` 是输入缓冲区，是刀 21 在 93 上记过的同一个反转），所以它是「花掉机制」而不是「本刀解锁」，真正卡在三角函数上的是 76 与 39 | 层 1 一条：`trig-extra-flags`（给 `sin` 多写一个 flags 0 → 文本不动、字节长一个、`tileiras` 答 `error at offset 112: failed to get result type 0 for DivIOp`）。层 2 两条写入器变异体，都同长、层 0 盲、`tileiras` 收下：`sin-as-cos`（`sin` 写成 `cos` 的操作码）与 `atan2-operands-swapped`（两个操作数对调，即按操作数名字而不是散文去读方言）；两条都只红 `trig_sweep`，`rope` 是 kernel 级控制（它一条三角函数都不走）一次都不动 | 1（实报 1；`tile-golden/run.sh` 本机全量见 §6.5，`tile-gpu-diff/run.sh` 加一个 native 构建、两个 kernel 的真机对拍与两个变异体） |

| **21 两块 transformer**（已落地） | 「设备把两串**整块**的 launch 跑成两个程序：leetgpu 74 十二次、93 十七次，比此前最长的序列还长七次，而二十九次 launch 里有六次用的是既有 kernel。同时台账第一次承认一件事：一行可以录在比题目小的形状上，而那是宿主参考实现的限制，不是后端的」 | 包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动，**零新 opcode**（74 的 gelu 是 `tanh` 近似而不是刀 15 的 `erf`，`tanh` 从刀 7b 起就在包里）。kernel：十五个。`gpt_ln` / `gpt_qkv` / `gpt_scores` / `gpt_context` / `gpt_dense` / `gpt_fc` / `gpt_gelu` / `gpt_down`（74），`llama_rms` / `llama_qkv` / `llama_rope` / `llama_scores` / `llama_out` / `llama_ffn` / `llama_down`（93）。**复用的六处**：74 的第四次 launch 是刀 16 的 `attn_softmax`、第七与第十二次是第一个里程碑的 `vadd`（它的长度是 grid 不是录制，所以任何宽度的残差加都是它）；93 的第八次是 `attn_softmax`、第九次是刀 19 的 `gqa_context` 一字节没改（投影直接写成头优先的布局，正好是它录制时读的那个布局）、第十五次是刀 16 的 `swiglu_act`、第十一与第十七次是 `vadd`。一个 kernel 跑多次的也有三处：`gpt_ln` 两次、`llama_rms` 两次、`llama_qkv` **三次**（Q 四个头、K 与 V 各两个头，头数是 grid 给的，缓冲区的总宽度根本不进这个 kernel）、`llama_rope` 两次、`llama_ffn` 两次。宿主：`std/gpu` 九个参考实现加一个 `ref_tanh`；`linear_bias_ref` 一个供 74 的四次线性层用 | 层 0/1 十五个新 golden，`FUNC GLOBAL` 十五个，`tileiras` 一次通过；层 2 本机 3080 二十二条序列加对照全绿（**逐位 3、容差 20**），`gpt2` 的 miss 1.80e-9、`llama` 5.01e-8。leetgpu **74 / 93** 可解，累计 **85 / 97**。刀 7a…20 的 111 个 golden 一字节没动。**93 的 RoPE 不需要三角函数**：题目签名把 `cos` 与 `sin` 当输入缓冲区传进来（前研的怀疑反过来了，需要三角函数的是 **76**，它的角度在 solve 内部算，本刀因此不取它） | 层 1 **零条**（零新 opcode）。层 2 **零条新变异体**：负控是把两条序列塞进刀 16 那四条变异体，矩阵从 84 格长到 **92 格**、红集从 72 长到 **80**，两条新序列四条全红（grid 那条在这里红而在 `kv` / `ols` 上绿，因为它们的第二次 launch 把输出列块放在 grid 的第二根轴上）。另有一条**自轴负控**：把 `std/gpu.rope_ref` 的 cos 与 sin 对调，只有 `llama` 一条红（miss 5.01e-8 → 1.13e7）。顺手补一个门：`problems.txt` 表头的题数从刀 18 起就没人改过（83 行的表上写着 73），`check.py` 现在读它 |

## 8. 风险

**墙一（无 f32 / bf16）**：处置 = `std/narrow` 的 opaque 加双舍入定理，已核实可行，代价是
没有运算符语法。定理只护 `+ − × ÷ √`，其余按 §3.2 的表分「f64 算再舍」与「容差契约」两档；
tensor core 路径永远只是容差档。剩余风险：某代硬件上 bf16 `addf` 不遵守 nearest_even，
对拍会抓到但没有修法，只能把该 dtype 降到容差档。

**墙二（无 call 对字典传递）**：分阶段路线下消失：字典传递、闭包、泛型全在宿主运行期跑完，
kernel 记录出来的是一阶单态 SSA。换来的限制是 §5.2 的结构化控制流与递归上限。
混合路线（刀 7）重新面对这堵墙。

**墙三（无 CI 执行 oracle）**：处置 = D4。CI 只到层 1，执行只在本机，台账把「有人跑过」
变成机器可查的事实。剩余风险是一台机器、一种架构（sm_86）。前置：驱动升级，刀 4 实测它就是
今天唯一拦着层 2 的东西（§6.4）。

其它：

- `cuda-tile` 随 LLVM 漂移：只影响本机 round-trip 工具，而刀 3 没有用到它；字节码规范有版本号
  与兼容规则，我们写 13.2 版字节码，`tileiras` 13.3.36 读得了（13.1 / 13.2 / 13.3 三个版本号都接受，
  cubin 相同，§6.1 已验证）。
- `tileiras` 许可：SLA 已读（§6.1），CI 上安装使用落在授权内；若日后不许，层 1 退回本机，
  CI 只剩层 0，那时把台账门的触发面扩到 `scripts/tile-golden/**`。
- `tileiras` 的 wheel 依赖没有写在它能读的地方：`--no-deps` 装出来的二进制对任何输入都答一句
  `failed to compile Tile IR program`，不说少了什么。刀 3 花在这上的时间比花在格式上的多；
  `toolchain.txt` 把「要哪两个文件」写成了实测结论，升钉时先重跑那个移除实验。
- 效果操作的闭包参数不能写自己的效果（§5.2 已核实）：`d_for` 走普通函数加区域栈。
- opaque 只在声明模块内能拆包：句柄级的循环签名在 `packages/tileir` 外不可用，公开面只能
  是带类型的 `d_for / d_for2`（§5.2）。
- 命名空间与状态格捕获：§2.3。
- **std 声明的第一个 trait 撞出一处编译器缺陷**：`dawn doc --builtins` 用只含 prelude trait 的表
  渲染 std 签名，`alloc[D: Dtype]` 的 bound 让它 `panic("unknown trait id")`。刀 1 顺手修成按
  各模块自己的 trait 表渲染（`selfhost/src/doc.dawn` 的 `builtins_json`）。另一处顺带发现、
  **未修**的缺陷：`show((1, 4))` 顶层对元组调用在 lowering 里 `panic("lower: no impl for trait 3")`
  （嵌在列表里 `show([(1, 4)])` 正常），与 opaque 无关，在 main 上可复现，待开 issue。
- Emit-Change 面：计划稿预估「新 std 模块无人引用，只落 `emit selfhost`」，**刀 1 实测推翻**：
  与真父提交对照，十个 `emit` label 全动。两个原因，都与引用无关：std 模块的类整体发射进
  每个程序的输出（`std/gpu.class`、它的闭包与字典类都在 calc 的输出里），而且新模块让
  ADT id 重编号，生成的字典类名（`gen$common$dict$1$Adt1810` 之类）跟着改。`doc --builtins`
  也动（参考页列出新模块）。刀 0 同理按十个 label 预估；刀 4 实报见其提交的 Emit-Change 声明：
  std/gpu 多了 `with_gpu_real` 与三个 Array 辅助函数，`dawn/rt/Gpu` 类无条件进每个 jar，
  ADT id 再次重编号（`Adt2042` → `Adt2103`），Core golden 里指令真变的只有编辑过的八个模块。
- 假设备把旧 bug 固化：`with_gpu_fake` 的参考实现若错，GPU 对拍会「一致地错」。所以每个
  对拍语料的 `.expect` 必须手写（`spike-native/run.sh` 的规矩），参考实现只是第二份意见。

## 9. 出处

- 本仓：spec.md §2.7（351-411）、§3.5（552-640）、§6.3、§6.5（1573-1660）、§9.8.1、
  §10.6（2819-2870）；`std/io.dawn:389-475, 860-908`（`Fs` 声明、`with_fs_real`、表 handler
  测试）；`selfhost/src/check/types.dawn:638, 3263-3300`；`selfhost/src/ir/lower.dawn:1113-1290`；
  `selfhost/src/jvm/emit.dawn:794-806`；`selfhost/src/check/checker.dawn:1801, 1978`、
  `passes.dawn:1158`；`scripts/opaque-twin/run.sh`；`scripts/spike-native/run.sh`；
  `scripts/intrinsic-parity.py`；`scripts/gate-map/gatemap.py`；`.github/workflows/gates.yml`；
  [bootstrap.md](bootstrap.md)（种子特性纪律）；[runtime-intrinsics-design.md](runtime-intrinsics-design.md)
  §5、§12.1、§12.5；[effects-design.md](effects-design.md) §1、§2、§6；
  提交 `b262dcc9`（`Fs` 声明的 Emit-Change 清单）、`c569ff18`（`Fs` seam 双后端语料）。
- 不入库的研究备忘录：agent-handoff 的 `cutile-backend-fit.md`（Tile IR 事实核实）与
  `tile-backend-plan.md`（本文的前身，含草案跑出的 Tile IR 文本与 174 条 oracle 的生成脚本）。
- 外部：NVIDIA/cuda-tile README（MLIR 示例、`cuda-tile-translate --bytecode-version=13.1
  --mlir-to-cudatilebc`、`tileiras --gpu-name sm_100`、Apache-2.0 with LLVM Exceptions、
  不接受外部贡献）；Tile IR 规范 operations 节（`get_tile_block_id`、`load_ptr_tko /
  store_ptr_tko`、`addf ... rounding<nearest_even>`、舍入模式清单）；PyPI
  `nvidia-cuda-tileiras`（版本表、wheel 平台、未标 license）；PyPI `cuda-tile`（1.5.0，
  `tileiras` 13.2 只支持 Blackwell 与 Ampere/Ada，驱动不低于 r580，无 CPU 模拟器）；
  本机 `nvidia-smi`：RTX 3080 / 8.6 / 560.94。
