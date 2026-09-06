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
另有标量类型 15 种（本仓 **13** 种，刀 T3 之后；改判当天是 7 种）、类型构造子 8 个（本仓 4 个）、属性标签 12 个（本仓 2 个）、
段 8 个（本仓 5 个）。

**先说最该先说的一句：两个目标几乎正交。** 预研排的那十五刀最多解锁 2 到 4 道题。十五刀
全部落地之后（2026-09-06），实测是 **1 道**：T1 记下 61，累计 85 → **86 / 97**，`problems.txt`
至今是这个数。预研当时写的是「61 靠三角函数、81 靠 i4 与 `unpack`，39 / 78 补上一格但仍欠多
launch」，逐条对下来三句都要改：

- **61 一条三角函数都不走。** 题面把 `cos` 与 `sin` 当输入缓冲区传进来，与刀 21 在 93 上记过的
  反转一模一样（§6.6 末尾）。它落在 T1 里是因为 `rope` 正好是三角族的 kernel 级控制，属于「把
  已经付过钱的机制花掉」。真正卡在三角函数上的是 **76** 与 **39**，T1 都不取。
- **81 要的 i4 与 `unpack` 已经由 T9 做到层 3**，机制在树上了。但方言里 `ptr<i4>` 根本不成立，
  本仓也不为亚字节格式开缓冲区通道（§6.12 一），所以取 81 是另一件事，本战役不做。
- **39 / 78 欠的多 launch 仍然欠着**：39 除了旋转因子还要每级一次 launch。

所以 leetgpu 那本账停在 86 / 97 是裁决在起作用，不是欠债：这十五刀的目标是特性不是题目，
一道题只在它的 kernel 恰好是某一族的控制时才顺手记下（61 就是这么来的）。反过来，
剩下 11 题里 29 / 67（top-k）与 60（RNG）**永远不会**被特性覆盖解锁，Tile IR 的 100 条
操作码里没有任何选择、排序或随机机制。改目标不是换一个方向继续走，是换一条路。

六条裁决：

1. **「覆盖」的判据是层 2**，也就是本机 3080 上有第二意见。层 1（`tileiras` 接受）不够，
   因为「门的绿没有信息量」；层 3（有会红的变异体）对某些格子物理上不成立，所以做不到
   层 3 的**逐条具名豁免**，理由写进台账：`assume`（方言自己说错谓词是 UB）、
   `OptimizationHints`（提示不改答案）、Debug 与 Producer 段、`nsw` / `nuw` / `nw`
   （它们是编译器的假设不是运算）。
2. **view 族暂排除**（**2026-09-06 被用户撤销**，见本条末）：`make_tensor_view` /
   `get_tensor_shape` / `load_view_tko` / `store_view_tko` / `make_partition_view` /
   `get_index_space_shape` / `make_gather_scatter_view` / `make_strided_view` /
   `atomic_red_view_tko` 九条操作码、四个类型标签与 `PaddingValue` 五值枚举，连同 T11 到
   T13 三刀一起挂起。它是与指针梯子并列的第二套取址方式，是全清单里最大的一块，等 T1 到
   T10 做完再回头裁。

   **裁决作废，原文留在上面是为了脉络。** T1 到 T10、T15、TE 收官之后，用户在 2026-09-06
   撤销了这一条并立项 T11 到 T13。这条裁决当时的理由（「等做完再回头裁」）本身就是一张
   期票，回头裁的结果是做：view 族是清单里最大的一块，而 T1 到 T10 已经把「一条操作码怎么
   落到三层」这件事跑熟了。T11 落的是**静态**那一半（四条操作码、两个类型标签、五个
   `PaddingValue`，见 §6.14），动态维与两条形状查询归 T12，`StridedView` /
   `GatherScatterView` / `atomic_red_view_tko` 归 T13。三张台账上还写着 `ruling 2` 的行，
   读作「已撤销、等它的刀」，不再读作「无限期挂起」。
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

**版本墙（T8）比想象的便宜，这条预研独立复核过，刀 T8 落地时又逐处重量了一遍。**
预研说 13.2 与 13.3 之间本仓写出去的字节只有三处会变：文件头第 10 字节的
`BYTECODE_MINOR`、`exp` 0x17（13.3 起内联写 `rounding_mode`）与 `mmaf` 0x49（13.3 起写一个
flags varint）。刀 T7 量出第四处（Global 段的记录多两个 varint），刀 T8 把清单重新枚举了一次，
**四处成立、另有两处版本分支对本仓恰好是空的**，逐条见 §6.11。其余操作逐字节相同，
这不是估计而是 `cmp -l` 出来的。`bytecode.dawn` 那句「the bytecode this writes is the same
at 13.1, 13.2 and 13.3」已随刀 T8 改写。


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
  `mmai`（整数 MMA，等整数缓冲）。`mmaf` 的 `fast_acc` 从刀 T8 起有地方写（13.3 的 flag，
  写入器发的 flags varint 里那一位恒为 0，见 §6.11）。
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
  `rounding_mode` 是 13.3 才加的；在 13.2 上写了会让读取器把下一个字节当别的东西，实测报
  `failed to get result type 0 for CmpIOp`），刀 T8 把钉子挪到 13.3 之后它**必须**写这一格，
  不写同样被拒（§6.11）；`exp2 / rsqrt` 只写 flags（`flush_to_zero`
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
- `encode(prog) -> Bytes` 写 `cuda-tile` 字节码：头（magic + 13.3，刀 T8 之前是 13.2）、Func / Constant / Type /
  String 四个 section、结束字节。只编码指令表装得下的东西：内存操作 `weak`、无 mask、带 token
  操作数；`addf` 为 `rounding<nearest_even>`、不 flush-to-zero；整数操作 `overflow` none；tile 为
  0 或 1 阶。不写 debug section（函数位置索引 0 = unknown）。**entry 的 optimization_hints
  从刀 T15 起写得出**（默认仍不写，只有 `trace_kernel_hinted` 记下的程序带它；load / store
  的同名可选属性同刀落地，见 §6.10）。版本常量 `BYTECODE_MAJOR / BYTECODE_MINOR` 钉在包里。
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
  512 字节 SASS）；13.4 被拒 `unsupported Tile IR bytecode version: 13.4`。刀 3 钉 13.2，理由是
  cuTile.jl 的兼容表说 Ampere / Ada 的最低字节码是 13.2（`launch.jl` 的 `tile_ir_requirement`）；
  那是**下限**不是上限，而刀 T8 把钉子挪到了 13.3，因为 13.3 才有的操作码要它。挪之后
  sm_86 的 cubin 逐字节没变，§6.11 记的就是这次测量。
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
| 1 字节码编译 | 是（刀 3 起；今天是 `tile-golden-1` 到 `tile-golden-6` 六片，刀 T5 起） | `tileiras --gpu-name sm_86` | 编码错、类型错、不支持的 op | 算的对不对 |
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
`unsupported opcode 127 for bytecode version 13.2`，刀 T8 之后同一条答的是 13.3）。刀 5 又加三个（`sum` 上）：
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
实例：这一格从刀 3 起一直是绿的，而它从来没看过 stderr。今天三层各有：层 0 一百四十三个
kernel 的文本与字节码 golden，两后端逐字节；层 1 CI 每 push（六个分片）；层 2 有脚本、台账与 CI 门（§6.4），
本机驱动升到 616.56 之后台账末行是 `pass`，「算的对不对」这一格从刀 7a 起有答案了。
（刀 4 到刀 6 期间这里写的是「本机驱动 560.94 装不进 cubin，台账第一行记的是 `blocked`」；
那两行 `blocked` 留在台账的历史里，是那个装载器答过的话。）

**刀 T2 把层 1 与层 3 的边界量清楚了一次**，因为它的八条操作码里有四条**只能**在层 1 红。
判据是「这个属性说的是一个值，还是一个类型」：`permute` 的 `permutation` 与 `cat` 的 `dim`
决定**结果的形状**（两个操作的 verifier 都是从属性推出结果类型再比对），三条指针转换决定
**结果的元素格式**，所以把它们写错一律是类型错，`tileiras` 在设备之前就拒掉。于是刀 T2 的
五条层 1 变异体（`join-tokens-operand-count-wrong` / `cat-dim-swapped` /
`int-to-ptr-as-ptr-to-int` / `ptr-to-int-as-int-to-ptr` / `ptr-to-ptr-as-bitcast`）各自钉住一句
报文，而设备上那四条（`permute-identity` / `cat-operands-swapped` /
`extract-indices-reversed` / `num-tile-blocks-as-block-id`）**必须**绕开这条判据才立得住：
`permute-identity` 靠的是 `shape_ops` 那个 4x4x8 的 tile 前两维**相等**（换了它就是形状错，
到不了设备），`cat-operands-swapped` 换的是操作数而不是 `dim`，`extract-indices-reversed`
换的是操作数的顺序而两个维度都恰好有两个 slice，`num-tile-blocks-as-block-id` 换的是
opcode 而 `get_num_tile_blocks` 与 `get_tile_block_id` 逐字节同形。台账（`features.txt`）
按 T0 的读法把这两类都记成层 3，理由与 `for` 那一行一样：层 3 要的是「有一条会红的变异体，
且它改的是那条操作码的写法」，不是「它必须在设备上红」。

### 6.3 版本钉法（刀 3 实况）

三个数同批改：`tileiras` 的版本与三个 wheel 的 sha256、字节码版本（`packages/tileir/src/bytecode.dawn`
的 `BYTECODE_MAJOR / BYTECODE_MINOR`，写入头）、本机台账里的驱动版本。全部记在
`scripts/tile-golden/toolchain.txt`（`bytecode 13.3`，刀 T8 之前是 13.2 / `tileiras 13.3.36` / `gpu-name sm_86` /
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

**分片的均衡是量出来的，绝对值不是**。最终树上不分片跑一次全量：**1303 s**（144 项，531 条
PASS，退出 0），期间 load 从 7.2 涨到 12.7。按 `ITEM_TIMES` 把 144 项摊回四片是
**317.3 / 330.9 / 319.9 / 320.2 s**，彼此相差不到 4.3%，第 2 片多出来的那点是一个偏重的
变异体，这正是「除得尽」应有的样子。而单项均值 kernel 5.99 s、变异体 32.57 s，对照刀 21
安静时的 4.30 s 与 13.65 s，分别是 1.4 倍与 2.4 倍（变异体每个要一次 native 构建，抢 CPU 时
吃亏最大）。所以这次的绝对秒数换算成 planning value 是 775 / 802 / 780 / 780，**远在 660 s
的 run pole 之上，而那是负载的产物不是回归**：刀 21 早就记过同一棵树全量能从 746 s 拉到
881 s。四条预算行因此按上面的推导走，不按这次的秒数走。

重述前按规矩跑了审计（`scripts/gate-observations.py` 拉 09-03 与 09-04 的 25 次 run，
`scripts/check-gate-budgets.py --observed`）：四片 CI 实测最差 **427 / 414 / 385 / 371 s**，
一条都没被点名，离「某一片实测过 550 s 就分第五片」的触发条件最近的也还有 120 s；把本刀的
活加上去的投影是 ~427 / 443 / 394 / 380 s，**不分第五片**。审计顺带点了九条与 tile 无关的
欠债行（native-diff-1/2、syntax-mutants-1/3、builtin-type-1/2、checker-corpus、
pipe-contract-1、list-elems-contract），本刀不动它们。**欠一次安静的本机重测**，而重测只会把
这四个上限往下压，那是这份文件不据以动作的方向。

**刀 T2 的实测：十个新项（五个 kernel 五条变异体），四条预算行全部上调，而且这一次是把刀 T1
欠下的「空闲机器上重测一次」付掉之后上调的。** 三轮 `ITEM_TIMES`，前两轮在 T1 落地之前的
151 项上，第三轮在 rebase 之后的 154 项上：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| 第一轮 kernel（另一个 agent 在跑，负载 7 到 26） | 131 | 4.98 s | 27.10 s | 8.40 s | 1100.3 s |
| 第一轮变异体 | 20 | 15.44 s | 24.53 s | 18.36 s | 367.3 s |
| 第二轮 kernel（同一棵树，负载约 5.5） | 131 | 4.23 s | 5.66 s | 4.85 s | 635.6 s |
| 第二轮变异体 | 20 | 15.36 s | 19.42 s | 17.42 s | 348.3 s |
| 第三轮 kernel（rebase 后，机器空闲，负载 0.18 到 4.09） | 133 | 4.30 s | 5.54 s | 4.64 s | 616.7 s |
| 第三轮变异体 | 21 | 13.11 s | 21.77 s | 16.82 s | 353.2 s |

不分片整跑三轮分别 **1484 s / 1000 s / 984 s**。前两轮把刀 21 的结论又说了一遍，而且说得更响：
kernel 的极差从 **5.4 倍**收到 **1.3 倍**，变异体几乎没动。没有哪个 kernel 本身是贵的。

**第三轮说出了一件不是负载的事：变异体比刀 21 读的贵。** 16.82 s 对 13.65 s，而一条变异体是
一次**包的原生重建**，所以它正是那个「成本随包一起长」的项。四条预算行因此不是被负载抬上去的，
是被这件事抬上去的。按项求和的四片是 **244.1 / 249.0 / 233.4 / 243.4 s**（均分 242.5 s），
`(本机 + 70) × 2` 得 **628 / 638 / 607 / 627 s**。四条**全部高于**它们原来写着的
552 / 558 / 527 / 535 s，所以四条全部重述，`timeout-minutes` 是 **32 / 32 / 31 / 32**。
最紧的一条离 660 s 的 pole 只剩 **22 s**，于是第五片成了下一刀的问题，而不是一个投影：
触发条件没变（CI 观测过 550 s，或规划值过 pole），只是第二条已经在一刀的射程内了。
同一份 `ITEM_TIMES` 按五片求和是 **191.5 / 189.3 / 194.1 / 205.3 / 189.7 s**，
规划值 **523 / 519 / 528 / 551 / 519 s**，所以分第五片确实解得开，只是不该在触发之前分。

**第二片重的原因是一条变异体，不是任何一个 kernel。** 154 项里 21 条变异体，21 mod 4 = 1，
所以第二片拿六条而另外三片各拿五条；一条变异体 16.8 s，四片之间的最大差是 15.6 s。
刀 T1 那次「分片算术头一次除得尽」因此只持续了一刀。

`scripts/gate-observations.py` 这一天拉下的四片 CI 最差是 **427 / 414 / 385 / 371 s**，
四条新预算行都在它之上，本刀因此没有一条落进那份「声称低于实测」的名单
（那名单上另有十二条是既有欠账，与本刀无关）。

`tile-gpu-diff/run.sh` 的本机读数见 §6.4 的台账行；这一刀往它里面加了一个族（五个 kernel）
与四条变异体，每条变异体重编五个 kernel、重汇编五次、真机重跑五次。

**刀 T3 的实测：四片装不下了，分第五片。** 这一刀加六个 kernel 与五个变异体，矩阵 154 项长到
**165 项**（139 个 kernel、26 个变异体）。在 rebase 到 T2 之后的最终树上跑一轮不分片的
`ITEM_TIMES`（本机 load 1.1 涨到 3.3，全量 **1084 s**）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 139 | 4.42 s | 5.74 s | 4.67 s | 649.8 s |
| 变异体 | 26 | 13.58 s | 18.89 s | 16.15 s | 419.9 s |

两个数都与刀 T2 那轮空机器读数一致（kernel 均值 4.64、变异体 16.82），**第二次证实了 T2 找到
的那件唯一不是负载的事**：变异体的成本随包一起长（它是一次原生重建），kernel 之间没有差别。

**分片：N = 4 → N = 5，触发条件是 pole 而不是 CI 观测**，与 N = 3 → N = 4 那次同因。把 165 项
按 round-robin 发成四片是 **277.2 / 262.2 / 261.4 / 268.8 s** 的 ITEM_TIMES，规划值
**694 / 664 / 663 / 678 s**，**四片全部越过 660 s 的 run pole**，不是最差那片越过。发成五片是
**214.4 / 208.9 / 210.2 / 215.3 / 220.9 s**。第五片最重是因为 26 mod 5 = 1，多出来的那个变异体
归它，值 16.2 s。

**顺手改正一处：ITEM_TIMES 的和不是一片的墙钟。** 这一刀没有沿用刀 T2 的算法，而是把差量量了
出来：第五片在同一棵树上真跑一遍是 **251.94 s**，它的 item 和是 220.9 s，也就是**每一片要付
约 31 s 没有任何 item 记账的成本**（C 运行时、干净工程的 native 构建，以及它们之间的几次 JVM
启动）。于是五条预算行按 `(item 和 + 31 + 70) × 2` 写，是 **631 / 620 / 622 / 633 / 644 s**；
刀 T2 那四条都因为同一个 31 s 少算了。**644 s 离 pole 只剩 16 s**，所以下一把往第五片加东西的
刀要再分一次（同一张表六片是 558 到 575 s）。但这不等于 CI 也紧：四片的实测是
427 / 414 / 385 / 371 s 对预算 628 / 638 / 607 / 627 s，约 0.66，五片应当落在 330 到 360 s。

**第五片买的仍然是预算余量而不是墙钟**，这句话从刀 16 起没变：本 workflow 一次 run 现在是
**41 个 job**（加 ci.yml 的 `secrets` 是 42），账号并发上限 20，第 41 个只会排在第一波后面；
跑得最久的仍然不是 tile。`mutant-shards-complete` 的 `needs:` 多一行，
`.github/actions/dawn-toolchain/action.yml` 的 job 计数从「四十 / 三十六」改成
「四十一 / 三十七」。

`tile-gpu-diff/run.sh` 本机 **442 s**（刀 T2 记的是 366 s；rebase 前的同一份脚本量到 431 s）。多的是一个 native 构建、三个
kernel 的真机对拍与一条变异体（它要把三个 kernel 各重编一次）。它只在本机跑，CI 上仍只有
亚秒的 `--check`。`dawn test --stdlib` 多了四个参考实现与十一个测试（151 → 162），
`dawn test packages/tileir` 多了九个（88 → 97，其中 T2 的与本刀的各一部分），都是秒级。

**刀 T5 的实测：六个新项，五片装不下了，分第六片。** 这一刀加四个 kernel 与两个变异体，
矩阵 165 项长到 **171 项**（143 个 kernel、28 个变异体）。在 rebase 之后的最终树上跑一轮不分片的
`ITEM_TIMES`（本机 load 4.1 涨到 7.5，全量 **1278 s**，item 和 1261 s）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 143 | 4.54 s | 6.02 s | 5.12 s | 732.5 s |
| 变异体 | 28 | 15.49 s | 20.37 s | 18.88 s | 528.7 s |

**变异体又贵了，而这是第三次读到同一件不是负载的事**：16.15 s（T3）→ 18.88 s（本刀）。
一个变异体是包的一次原生重建，所以它的成本随包一起长；kernel 之间仍然彼此相差不到 1.5 s。

**分片：N = 5 → N = 6，触发条件是 pole 而不是 CI 观测**，与 N = 3 → N = 4、N = 4 → N = 5
两次同因，连着三刀了。把 171 项按 round-robin 发成五片是
**261.8 / 241.5 / 244.3 / 255.7 / 257.8 s** 的 ITEM_TIMES，规划值
**726 / 685 / 691 / 713 / 718 s**，**五片全部越过 660 s 的 pole**，不是最差那片越过；
发成六片是 **219.7 / 215.7 / 218.9 / 199.0 / 197.9 / 209.9 s**，是进得来的最少片数。
六条预算行按 `(item 和 + 31 + 70) × 2` 写成 **641 / 633 / 640 / 600 / 598 / 622 s**，
`timeout-minutes` 33 / 32 / 32 / 30 / 30 / 32。**六条全部重述**（含两条往下重述的），
理由是刀 16 立的规矩：N 变了，为另一个 N 算出来的行按定义作废。

六片随后在同一棵树上背靠背跑了一遍，分得很平：**约 240 / 233 / 230 / 226 / 228 / 201 s**（第一片是从总时长倒推的，其余五片是各自 coverage 文件之间的时间差），每一片都低于下面那六条预算行按 item 和加 31 s 算出来的数。预算是上限，这就是它的用处；`scripts/mutant-coverage/check.py` 对六片的并集答 `tile-golden: 171 mutant(s) covered across 6 shard(s)`。

那个 31 s 是从刀 T3 的测量搬过来的，没有重测：本刀这一轮自己的「墙钟减 item 和」是 **16.5 s**，
两个数里 31 s 是保守的那个，而预算是上限。**641 s 离 pole 只剩 19 s**，所以下一把往第一片加东西的
刀要再分一次（同一张表七片是 551 到 575 s）。CI 那边并不紧：四片的实测是 427 / 414 / 385 / 371 s
对预算 628 / 638 / 607 / 627 s，约 0.66，六片应当落在 260 到 290 s。

`tile-gpu-diff/run.sh` 本机 **496 s**（刀 T3 记的是 442 s）。多的是一个 native 构建、四个 kernel
的真机对拍与一条变异体（它把四个 kernel 各重编一次）。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 多了四个参考实现与一个测试（162 → 163），`dawn test packages/tileir` 多了
四个（97 → 101）。
**刀 T4 的实测：六片装不下了，分第七片；而两轮读数第一次在「装不装得下」上互相不认。**
这一刀加八个 kernel 与三个变异体，矩阵 171 项长到 **182 项**（151 个 kernel、31 个变异体）。
在 rebase 到刀 T5 之后的最终树上跑一轮不分片的 `ITEM_TIMES`，机器**安静**（load 2.0 到 3.5，
全量 **1265 s**，item 和 1250 s）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 151 | 4.45 s | 5.83 s | 4.76 s | 718.7 s |
| 变异体 | 31 | 13.90 s | 18.66 s | 17.14 s | 531.2 s |

**这两个均值比刀 T5 的低（5.12 与 18.88），比刀 T3 那轮空机器的高（4.67 与 16.15）**，而 T5
那轮是在 load 4.1 到 7.5 下读的。于是六片按本轮读数是
**208.0 / 221.1 / 204.8 / 204.0 / 207.3 / 204.7 s**，规划值
**618 / 644 / 612 / 610 / 617 / 611 s**，全部在 660 s 的 pole 之下、最差那片还剩 16 s；
按 T5 的单项均值同一副牌是 **227.5 / 241.3 / 222.4 / 222.4 / 222.4 / 222.4 s**，规划值
**657 / 685 / 647 / 647 / 647 / 647 s**，第二片**越过 pole**。

**两个模型在这一格上第一次给出相反的答案**，而拿一轮安静读数去比一轮带负载的读数，正是这一节
从刀 21 起一直在警告的那件事。裁法是这份文件一贯的那一条：**预算是上限，所以按两个模型里差的
那个规划**。差的那个说六片装不下。

**七片在两个模型下都装得下。** 本轮实测是
**172.2 / 174.5 / 175.9 / 175.8 / 183.3 / 183.6 / 184.6 s**（规划值 546 到 571 s）；按 T5 的均值是
四片 188.2 s、三片 201.9 s（规划值 **578** 与 **606 s**）。七条预算行取两者的**逐片较大值**，
也就是 T5 那一列，`timeout-minutes` 是 29 / 29 / 29 / 29 / 31 / 31 / 31。分法是 151 mod 7 与
31 mod 7 给的：前四片各 22 个 kernel 四个变异体，后三片各 21 个 kernel 五个变异体，而一个
变异体是 3.7 个 kernel，所以重的是后三片。

七片随后在同一棵树上背靠背跑了一遍：**~219 / 214 / 219 / 220 / 233 / 222 / 233 s**
（第一片由整轮总时长倒推，其余按各自 coverage 文件的时间戳量），每一片都不高于下面那七条
预算行声称的「item 和 + 31 s」，这正是上限该有的样子；`scripts/mutant-coverage/check.py`
对七片的并集答 `tile-golden: 182 mutant(s) covered across 7 shard(s)`。

CI 那侧仍然不紧：四片时代的实测是 427 / 414 / 385 / 371 s 对预算 628 / 638 / 607 / 627 s，
约 0.66，七片应当落在 230 到 260 s。**第七片买的仍然是预算余量而不是墙钟**：本 workflow
一次 run 现在是 **43 个 job**（加 ci.yml 的 `secrets` 是 44），账号并发上限 20。
`mutant-shards-complete` 的 `needs:` 多一行，`.github/actions/dawn-toolchain/action.yml` 的
job 计数从「四十二 / 三十八」改成「四十三 / 三十九」。

**这一刀在墙钟之外还撞出三条锚点**，值得单记，因为它们正是「锚点必须唯一匹配」这条规矩
存在的理由：改写 `rounding()` 让 `addf-no-rounding` 的锚点 0 匹配，改写原子的属性表让
`atomic-rmw-claims-weak-ordering` 的锚点 0 匹配，而在 `std/narrow` 里加一个与 `round_binary`
同样分解的定向舍入函数，让 `scripts/narrow-contract` 的 `no-subnormal-clamp` 变成 **2 matches**。
三次都是 harness 当场报出来而不是安静地少跑一个变异体：前两条搬到了新的那一行上，第三条把
锚点扩成「那两行注释加那一句」，注释是它指着 `round_binary` 而不是指着邻居的东西。

`tile-gpu-diff/run.sh` 这一刀多一个族（八个 kernel）与六条变异体，每条变异体重编八个 kernel、
重汇编八次、真机重跑八次；调用都走刀 T5 加的 `device` 超时兜底。它只在本机跑，CI 上仍只有
亚秒的 `--check`。`dawn test --stdlib` 多了九个参考实现与两个测试（163 → 165），
`dawn test packages/tileir` 多了四个（97 → 101，其中 T5 的与本刀的各一部分）：这一刀往包里
加的是取值不是机制。不分片整跑一次的 182 项全绿（`ran 182 of 182`，退出 0）。

**刀 T7 的实测：六个新项，八片装得下，五刀以来第一次不用分片。** 这一刀加三个 kernel 与
三个变异体，rebase 到 T6 之后矩阵 193 项长到 **199 项**（160 个 kernel、39 个变异体）。

在合并后的树上跑一轮不分片的 `ITEM_TIMES`（机器空，load 1.4 到 3.3，全量 **1502 s**，
item 和 1486.4 s）：160 个 kernel 4.61 到 6.35 s（均值 **5.05**）、39 个变异体 14.68 到
19.05 s（均值 **17.40**）。两个均值都落在刀 T6 的（4.76 / 17.38）与刀 T5 的（5.12 / 18.88）
之间，这是连着第五次读到同一件事：变异体是包的一次原生重建，成本随包长；kernel 不随。

**分片：N = 8 不动，八条预算行重述。** 八片按实测是
**182.6 / 187.7 / 188.6 / 191.4 / 188.1 / 188.3 / 188.4 / 171.3 s**（规划值 544 到 584 s），
按本轮均值是 577 七次加 543，按刀 T5 的均值是 **596 七次加 558**。八条行取三者的逐片较大值，
仍是 T5 那一列。**最重那片 596 s，离 660 s 的 pole 还剩 64 s**，与 T6 留下的余量一样多：
本刀这六项按位置散在八片里，每片多不到一项，而 T5 的模型本来就已经是那条行在认的数。
八条**全部重述**不是因为 N 变了（N 没变），是因为**项集变了、每一片的账都动了**：
第二到第五片原先认的是 558 s，现在要认 596 s。九片的同一张表是 537 到 575 s，留给后面的刀。

`tile-gpu-diff/run.sh` 在合并后的树上 **723 s**（本刀多三个 kernel 的真机对拍与三条变异体，
其中一条要重建 std 并重编对拍程序）。它只在本机跑，CI 上仍只有亚秒的 `--check`。
`dawn test --stdlib` 多了五个参考实现、没有新测试；`dawn test packages/tileir` 多了七个
（106 → **113**）。

**刀 T15 的实测：六个新项，八片仍装得下，六条预算行上调、两条不动；这是连着第二刀不分片。**
这一刀在刀 T7 之上加两个 kernel 与四个变异体，矩阵 199 项长到 **205 项**（162 个 kernel、
43 个变异体）。在 rebase 到 T7 之后的最终树上跑一轮不分片的 `ITEM_TIMES`，**机器安静**
（load 0.6 到 2.3），全量 **1545.8 s**：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 162 | 4.61 s | 7.53 s | 4.89 s | 792.4 s |
| 变异体 | 43 | 14.79 s | 17.47 s | 17.16 s | 737.9 s |

两个均值又一次落在刀 T6 的（4.76 / 17.38）与刀 T5 的（5.12 / 18.88）之间，这是连着第六次
读到同一件事：一个变异体是包的一次原生重建，成本随包长；kernel 不随。

八片按本轮实测是 **189.6 / 188.8 / 195.7 / 201.1 / 203.3 / 184.8 / 183.9 / 183.0 s**
（规划值 568 到 609 s），按刀 T5 的单项均值是 **606 / 606 / 633 / 633 / 633 / 596 / 596 / 596 s**。
八条按惯例取**逐片较大值**，也就是 T5 那一列（自刀 T4 起一直如此）。**其中六条上调，
第 6 与第 7 片算出来正好是它们已经写着的 596 s，就不动**（刀 14 的规矩：预算是上限，
往下重述只会让下一刀再抬一次）。分法是 162 mod 8 与 43 mod 8：第 1、2 片各 21 个 kernel
五个变异体，第 3 到 5 片各 20 个加**六个**变异体，第 6 到 8 片各 20 个加五个；贵的是中间
那三片，贵在多一个变异体而不是多一个 kernel。

**633 s 离 660 s 的 pole 还剩 27 s**，也就是一个半 kernel、不到一个变异体。所以
**下一把加变异体的刀必须分第九片**；本刀不分，因为 633 仍在 pole 之下，而第九片买的
只有预算余量（这条 workflow 一轮会变成 45 个 job，账号并发上限 20）。同一张表九片是
537 到 575 s。**CI 那侧一点也不紧**：`scripts/gate-observations.py` 拉 2026-09-04 与 09-05
共 25 轮 main，八片各自最差是 **427 / 458 / 432 / 445 / 445 / 393 / 402 / 367 s**，CI 对本机
的比值约 2.1，本刀每片加约 8 s 本机，投影最差约 **475 s**，离「某一片实测过 550 s 就分片」
的触发线还有 75 s。重述前按规矩跑了 `check-gate-budgets.py --observed` 审计：15 条被点名的
欠债行**没有一条是 tile-golden 的**（native-diff 四片、syntax-mutants 两片、builtin-type 两片、
tree-policy、test、java-target-classpath、lsp-workspace、checker-corpus、pipe-contract-1、
list-elems-contract），本刀不动它们。

**同一张表在 rebase 之前量过一次**（199 项，另一个 agent 全程在建东西，load 5 到 7）：
全量 1652.3 s，kernel 均值 5.55 s、变异体均值 18.80 s，八片实测 600 到 618 s 的规划值。
两轮之间**项数增加而每项变便宜**，这只可能是负载，不可能是内容；采信的是安静那一轮，
另一轮记在这里是因为「同一棵树在有别人的机器上能慢 6%」这件事这一节已经量过很多次，
本刀是又一个实例。

**这一刀还撞出两条锚点，都是同一条规矩救的。** `optimization_hints` 印在 store 那一行的
`token=` 与冒号之间，于是 `drop-store-token` 的锚点（渲染器里 store 那一整串）当场
`anchor is not unique (0 matches)`；`t_load` 多一个形参，`load-dtype-f64` 的锚点同样落空。
两条都是 harness 当场报出来的，不是安静地少跑一个变异体，这正是刀 T4 记下那三次之后
这条规矩继续存在的理由。搬家后的 store 锚点靠 `, ${ty(val_ty)}` 保持唯一（只有 store 有），
理由写在 `run.sh` 那一段里。

`tile-gpu-diff/run.sh` 在最终树上 **622.6 s**（刀 T7 之后这一族多了三个 global kernel 与六条
变异体，本刀又加两个 kernel 与一个复用的控制 `vadd`；机器安静，load 约 2.3）。它只在本机跑，
CI 上仍只有亚秒的 `--check`。`dawn test packages/tileir` 多一个测试（113 → 114），
`dawn test --stdlib` 一个没多：**这一刀不碰 std**，`scripts/gen-stdsrc.py` 跑完 `git status` 是干净的。

**刀 T8 的实测：四个新项，八片仍装得下，四条预算行上调、四条不动；而 T15 写下的那句
「下一把加变异体的刀必须分第九片」被本刀的测量推翻了，所以那句话是改掉而不是照办。**
这一刀加一个 kernel（`global_flags`）与三条变异体，另把 T7 的
`global-visibility-written-at-13-2` 原地换成 `global-visibility-omitted-at-13-3`，矩阵
205 项长到 **209 项**（163 个 kernel、46 条变异体）。在最终树上跑一轮不分片的 `ITEM_TIMES`，
**机器安静**（load 0.4 到 2.3），全量 **1561.8 s**（209 项全跑，701 条 PASS，退出 0）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 163 | 4.53 s | 5.18 s | 4.73 s | 770.7 s |
| 变异体 | 46 | 14.65 s | 17.14 s | 16.86 s | 775.6 s |

两个均值又一次落在刀 T6 的（4.76 / 17.38）与刀 T3 的（4.67 / 16.15）之间，**这是连着第七次
读到同一件事**：一条变异体是包的一次原生重建，成本随包长；kernel 不随，而且这一轮 163 个
kernel 首尾只差 0.65 s，是这条脚本量到过的最平的一次。这一刀往包里加的机制是四个版本谓词，
不是新操作，所以变异体均值比 T15 那轮（17.16）还略低。

**八片装得下，而 T15 那句预言不成立的原因是重分牌而不是别的。** T15 留下的形势是
「最重那片 633 s，离 660 s 的 pole 只剩 27 s，一个半 kernel、不到一个变异体」，于是它写下
「下一把加变异体的刀必须分第九片」。本刀加了**三条**变异体，八片却仍然装得下：46 mod 8 = 6,
所以第 1 片与第 4 到 8 片各拿六条、第 2 与第 3 片各拿五条，而 T15 时是第 3 到 5 片拿六条。
**三条变异体没有落在原来最重的那三片上**，原来最重的第 3 到 5 片里有两片反而变轻了。八片按
本轮实测是 **201.5 / 183.5 / 184.2 / 192.8 / 196.2 / 196.0 / 195.7 / 196.3 s**
（规划值 605 到 595 s），按刀 T5 的单项均值是 **644 / 606 / 606 / 633 / 633 / 633 / 633 / 633 s**。
八条按惯例取**逐片较大值**，也就是 T5 那一列（自刀 T4 起一直如此），于是第 1 片
606 → **644**、第 6 到 8 片 596 → **633**，其余四条算出来不高于已经写着的数，按刀 14 的规矩
不动。`timeout-minutes` 是 **33 / 31 / 32 / 32 / 32 / 32 / 32 / 32**。

**最紧的一条 644 s 离 pole 只剩 16 s**，是 T15 留下的 27 s 的六成。所以那句预言改写成一句更
准的：**触发分片的是规划值过 pole 或 CI 观测过 550 s，不是「加了一条变异体」**；本刀加三条
而没有触发，而 16 s 的余量意味着下一刀多半会触发。同一张表九片是 **541 到 572 s**，留给
下一个人；第九片买到的仍然只有预算余量（这条 workflow 一轮会变成 45 个 job，账号并发上限 20）。

**CI 那侧离两个触发线都远。** `scripts/gate-observations.py` 拉 2026-09-04 到 09-05 共 25 轮
main，八片各自最差是 **427 / 458 / 432 / 445 / 445 / 396 / 403 / 377 s**，最差的一条离 550 s
的观测触发线还有 92 s。重述前按规矩跑了 `check-gate-budgets.py --observed` 审计：**15 条被
点名的欠债行没有一条是 tile-golden 的**（native-diff 四片、tree-policy、syntax-mutants 两片、
builtin-type 两片、test、java-target-classpath、lsp-workspace、checker-corpus、
pipe-contract-1、list-elems-contract），本刀不动它们。

`tile-gpu-diff/run.sh` 这一刀**一个 kernel 也没加**（`global_flags` 只到层 1，理由见 §6.11
第八条），所以它跑的是与 T15 同一份语料，读数见 §6.4 的台账行。`dawn test packages/tileir`
多两个测试（114 → **116**），`dawn test --stdlib` 一个没多：**这一刀不碰 std**，
`scripts/gen-stdsrc.py` 跑完 `git status` 是干净的。

**刀 T10 的实测：八片装不下，九片也装不下，分到第十片；而逼出这一步的不是这一刀的内容，
是机器自己变慢了。** 这一刀加四个 kernel（`alloca_scratch` / `alloca_two` / `alloca_ctl` /
`mmaf_scaled_e4m3`）与四条变异体，矩阵 209 项长到 **217 项**（167 个 kernel、50 条变异体）。
在最终树上跑一轮不分片的 `ITEM_TIMES`，**机器安静**（load 3.7 到 4.9），全量 **2076 s**
（217 项全跑，退出 0，item 和 2056.8 s）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 167 | 5.17 s | 6.50 s | 5.91 s | 987.7 s |
| 变异体 | 50 | 18.10 s | 23.10 s | 21.38 s | 1069.1 s |

**这两个均值都在刀 T3 以来每一次读数之外，而这是本节第一次读到「不是负载、也不是内容」的
东西。** 刀 T3 到 T8 之间 kernel 读到过 4.64 / 4.67 / 4.73 / 4.76 / 4.89 / 5.05 / 5.12，
变异体读到过 16.15 到 18.88；5.91 与 21.38 两个都在这两段区间之上，kernel 比其中最高的那次
还高 15%。同一棵树在同一天早些时候、机器上另有四个门在跑时读到 6.89 与 20.45，所以安静那一轮
也不是负载的产物。**变的是什么这里量不出来；量得出来的是今天这组数更差，而预算是上限**，
所以按它规划，这与刀 T4 立下的「按两个模型里差的那个规划」是同一条规矩。

**八片按这组数是 745 / 709 / 704 / 712 / 706 / 708 / 711 / 734 s，没有一片在 660 s 的 pole
之下**；九片是 684 / 643 / 642 / 642 / 638 / 666 / 673 / 669 / 675 s，**仍有四片在 pole 之上**。
这是本节第一次出现「N+1 也不够、要跳到 N+2」的格子。十片是
**611 / 615 / 613 / 622 / 621 / 619 / 618 / 605 / 604 / 605 s**，十片全在 pole 之下，最差那片
还剩 **38 s**。十条预算行按惯例取实测与刀 T5 单项均值的**逐片较大值**（T5 的那一列是
565 七次加 555 三次），**这一次较大的是实测那一列**，与刀 T4 到 T8 恰好相反，理由就是上面那段。
十条**全部重述**，因为 N 变了而为另一个 N 算出来的行按定义作废（刀 16 的规矩）。
`timeout-minutes` 是 31 / 31 / 31 / 32 / 32 / 31 / 31 / 31 / 31 / 31。

分法是 167 mod 10 与 50 mod 10：前七片各 17 个 kernel、后三片各 16 个，而 **50 除得尽，
所以每一片正好五条变异体**，这是刀 T1 之后第一次变异体分得齐，也是十条行彼此只差 18 s 的原因。

**CI 那一侧离两个触发线都很远，这一点在一次由本机变慢逼出来的分片旁边值得说明白。**
`scripts/gate-observations.py` 拉 2026-09-04 到 09-06 共 25 轮 main，八片各自最差是
**417 / 458 / 432 / 445 / 445 / 427 / 416 / 429 s**，对预算 644 / 606 / 633 / 633 / 633 /
633 / 633 / 633 s 约 0.7；十片分 217 项应当落在 350 s 上下，离 550 s 的观测触发线还有 200 s。
重述前按规矩跑了 `check-gate-budgets.py --observed` 审计：**16 条被点名的欠债行没有一条是
tile-golden 的**（native-diff 四片、tree-policy、syntax-mutants 两片、builtin-type 两片、
test、java-target-classpath、lsp-workspace、checker-corpus、pipe-contract-1、
compiler-weight-contract、list-elems-contract），本刀不动它们。

**第十片买的仍然是预算余量而不是墙钟**，这句话从刀 16 起没变过：本 workflow 一次 run 现在是
**46 个 job**（加 ci.yml 的 `secrets` 是 47），账号并发上限 20，第 46 个只会排在第一波后面；
跑得最久的仍然不是 tile。`mutant-shards-complete` 的 `needs:` 多两行，
`.github/actions/dawn-toolchain/action.yml` 的 job 计数从「四十四 / 四十」改成「四十六 / 四十二」。
**十片没有在本机背靠背跑过**，这是本刀相对前几刀欠的一件事：分片的并集由 CI 的
`mutant-shards-complete` 兜住，而不分片那一轮的 217 项是逐项跑过的（`ran 217 of 217`）。

`tile-gpu-diff/run.sh` 在最终树上 **723 s**（刀 T8 那一代跑的是同一份语料）。本刀往它里面加
一个族（三个 kernel）与一条变异体（`alloca-aliased`，它把三个 kernel 各重编一次）。它只在本机跑，
CI 上仍只有亚秒的 `--check`。`dawn test packages/tileir` 多两个测试（115 → **117**），
`dawn test --stdlib` 一个没多（166 → 166）：**本刀往 std 加的是三个参考实现、零个测试**，
而它确实碰了 `std/gpu.dawn`，所以 `scripts/gen-stdsrc.py` 与 Core golden 都重跑了（§7 的行里记着）。

**刀 T9 的实测：七个新项，十片仍装得下，十条预算行一条也没动；而这一刀的另一半测量是机器本身，
差一点让它多分一片。** 这一刀（rebase 到 T10 之后）加三个 kernel 与四条变异体，矩阵 217 项长到
**224 项**（170 个 kernel、54 条变异体）。在合并后的最终树上跑一轮不分片的 `ITEM_TIMES`，
**机器安静**（load 1.3 到 2.6），全量 **1812.4 s**（224 项全跑，退出 0）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 170 | 4.67 s | 5.28 s | 4.90 s | 833.3 s |
| 变异体 | 54 | 15.30 s | 18.16 s | 17.83 s | 962.8 s |

两个均值又一次落在刀 T6 的（4.76 / 17.38）与刀 T3 的（4.67 / 16.15）之间，**这是连着第八次
读到同一件事**：一条变异体是包的一次原生重建，成本随包长；kernel 不随，而且这一轮 170 个 kernel
首尾只差 0.61 s。

**十条预算行一条也不动。** 十片按本轮实测是 187.6 / 190.2 / 190.4 / 190.9 / 172.4 / 172.8 /
173.3 / 174.1 / 171.3 / 173.1 s 的 item 和，`(item 和 + 31 + 70) × 2` 是前四片 577 到 584 s、
后六片 545 到 550 s；按刀 T5 的单项均值是 603 四次加 565 六次。逐片取较大值仍是 T5 那一列，
而那十个数**每一个都低于**该片已经写着的行（604 到 622 s）。刀 14 的规矩是「预算是上限，往下
重述只会让下一刀再抬一次」，所以十条原样保留，最紧的一条（622 s）距 660 s 的 pole 还有 38 s。

十片随后在同一棵树上背靠背跑了一遍，全绿：**205.1 / 206.5 / 205.8 / 209.6 / 190.2 / 190.2 /
190.8 / 190.5 / 187.3 / 190.5 s**，按 `(本机片值 + 70) × 2` 是 515 到 559 s，同样一条也没超过
它已经写着的行；`scripts/mutant-coverage/check.py --coverage-dir` 对十片的并集答
`tile-golden: 224 mutant(s) covered across 10 shard(s)`。刀 T10 欠的那件事（十片没在本机
背靠背跑过）本刀顺手付掉了。

**这一刀顺带量了一次机器，值得单记，因为它差点多要一片。** rebase 之前，同一台机器上、
`ps` 说没有别人的时候，216 项的那一轮读到的是 **6.94 s 一个 kernel、20.47 s 一条变异体**，
比刀 T8 前一天的读数高 45%，而且**可复现**（随后九片背靠背跑了一遍，与 item 和对得上）。
那一轮里本刀新加的三个 kernel 是 6.00 / 6.16 / 6.17 s，**低于该轮自己的均值**；而**没有动过的
163 个 kernel 下界 5.23 s、刀 T8 那一轮上界 5.18 s**，两个区间不相交。所以那不是内容。
四小时后 rebase 之后的这一轮又回到 4.90 s。**这件事是这一节一贯那句话的又一个实例**：本机的
绝对秒数是这里最吵的一个输入，真正撑着预算行的是单项均值那一列。

`tile-gpu-diff/run.sh` 在最终树上 **667.2 s**（刀 T10 记的是 723 s，那是它自己那一代的语料）。
这一刀往 `dtype` 族里加两个 kernel（`dtype_i4` / `pack_roundtrip`）与两条变异体
（`exti-i4-zero-extends` 重编包、`pack-halves-swapped` 重建 std），台账行见 §6.4。`dawn test packages/tileir` 多一个测试（117 → **118**），`dawn test --stdlib` 多四个
（166 → **170**）：**本刀碰了 `std/narrow.dawn` 与 `std/gpu.dawn`**，`scripts/gen-stdsrc.py`
已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录。


**刀 T11 的实测：八个新项，十片仍装得下，十条预算行一条也没动；而本机那一轮**读数**是废的，
这一节第一次遇到「废」而不只是「高」。** 这一刀加五个 kernel 与三条变异体，rebase 到刀 TG
之后矩阵 227 项长到 **235 项**（176 个 kernel、59 条变异体）。在 rebase 之前的树上跑过一轮
不分片的 `ITEM_TIMES`（232 项），**机器全程被另一个 agent 占着**（起跑时 load 4.8，中途最高
17.8，收尾 5.9），全量
**2503 s**（41:43，232 项全跑，退出 0）：

| | 项数 | 最小 | 最大 | 均值 | 合计 |
|---|---|---|---|---|---|
| kernel | 175 | 5.07 s | 8.23 s | 6.03 s | 1054.7 s |
| 变异体 | 57 | 18.68 s | 42.65 s | 25.07 s | 1429.2 s |

比刀 T9 那一轮安静读数高 **23%（kernel）与 41%（变异体）**。这本身还只是「高」，刀 T9 已经
记过一次同样的事。**让它成为「废」的是下面这一条**：把这一轮按十片分，planning value 是
675 到 722 s；按**十一片**分，是 628 到 683 s。**两种分法每一片都越过 660 s 的 pole。**
一轮**分片分不下去**的读数，量的就不是这个矩阵，而是那台机器当时在干什么，因为被抬高的是
单项成本本身而不是除法。

**又量了两轮，两轮都在同一个方向上，而这就是「废」的证据本身。** 那台机器整晚没有安静下来
（另一个 agent 在同一棵仓库上跑它自己的 GPU 对拍与原生构建），所以「等安静了再量一轮」是个
等不到的条件。第二轮的前 21 个 kernel 读到 5.71 到 6.16 s、均值 **5.98 s**，与第一轮的
6.03 s 一致到小数点后一位，那一句问完就停了；第三轮是 rebase 到刀 TG 之后的最终树上的全量
一轮，**235 项全跑退出 0**，墙钟 **3246 s**（54:06），读到 176 个 kernel 4.98 到 16.50 s
（均值 **6.57**）与 59 条变异体 20.30 到 91.47 s（均值 **35.11**）。三轮一轮比一轮高，而
中间那半小时另一个 agent 把 load 推到 40：**91 s 的一条变异体不是这条变异体的成本**。所以
这是刀 T9 那次「`ps` 说没有别人却读到 6.94 s、四小时后回到 4.90 s」的同一件事，只是这一晚
它一直没有回来。

**这一刀因此不用刀 TG 的加法**（在已有的行上加新项自己的读数），理由是算术不是口味：TG 的
那三条行里已经带着 TG 自己那一轮的负载，再把这一刀同样带负载的读数加上去，shard 2 到 5 会变成
666 / 671 / 679 / 689 s，四片越过 pole，而支撑它的只是别人两个晚上的编译作业。真正管事的仍是
**单项均值那一列**，而它**本来就把新项算进去了**，因为它是按每一片自己的构成算的：按刀 T5 的
5.088 s 一个 kernel、19.0 s 一条变异体，合并后的分法（1 到 6 片各 18 个 kernel、7 到 10 片各
17 个；6 片 5 条变异体、其余各 6 条）给出 613 / 613 / 613 / 613 / 613 / 575 / 603 / 603 /
603 / 603 s。**每一条都不高于该片在刀 TG 抬过三条之后已经写着的行**，所以十条一条不动
（刀 14 的规矩：预算是上限，往下重述只会让下一刀再抬一次）。

**「十片还装得下」这句话另有一个本机负载碰不到的证据：CI 自己的观测。**
`scripts/gate-observations.py` 取 2026-09-04 到 09-06 的 25 次运行，十片的最差是
440 / 458 / 498 / 445 / 445 / 427 / 416 / 429 / 391 / 371 s。分第十一片的触发条件是
**某一片在 CI 上被观测到超过 550 s**，最差的一片是 498 s，而八个新项摊到十片上约 +15 s。

`tile-gpu-diff/run.sh` 在最终树上 **935.3 s**（15:35，load 6.9 到 7.8；同一棵语料上一轮读到
1008.2 s，刀 T9 那一代记的是 667.2 s，中间隔着刀 TG 的 `sym_diff` 一族）。多出来的那一段是
本刀往这份语料里加的一个 native 构建（`view_diff.dawn`）、六个 case 的真机对拍与四条变异体
各自的一次重编包加五次汇编加一次对拍。

`dawn test packages/tileir` 从 118 涨到 **122**（本刀加四个测试，断言的字节串全是手算的）。
**本刀碰了 `std/gpu.dawn`**（多一个参考实现 `view_padding_ref`），`scripts/gen-stdsrc.py`
已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录。

**刀 T12 的实测：六个新项，十片装不下了，分第十一片。** 这一刀加三个 kernel 与三条变异体，
矩阵 235 项长到 **241 项**（179 个 kernel、62 条变异体）。跑了两轮不分片的 `ITEM_TIMES`：
rebase 之前那一轮全量 **2285 s**（38:05，机器上另有 agent，load 3.8 到 5.5），rebase 到 `c7b481b6` 之后那一轮全量 **2183 s**（36:23，预算就是按它算的）；最后又 rebase 到 `ed11fcf4`（上游只动 tea 与 example，编译器与 std 一个字节没动）并重跑了一遍验证，全量 **2098 s**（34:58），179 个 golden 与 62 条变异体全绿。

| 轮次 | kernel | 变异体 |
|---|---|---|
| rebase 前 | 179 项 4.99 到 7.78 s，均值 **5.52** | 62 项 16.45 到 23.69 s，均值 **20.65** |
| 最终树 | 179 项 5.06 到 6.64 s，均值 **5.51** | 62 项 16.28 到 22.00 s，均值 **19.01** |

**最终树那一轮不是「废」的，这是它与刀 T11 那三轮的全部差别。** 它的**变异体那一列与刀 T5 的
模型常数对到小数点后两位**（19.01 对 19.0），所以它量的不是机器。剩下比模型高的只有 **kernel
那个常数**，而那个常数是过期的那个：T5 定的是 5.088 s，此后 T2 读 4.64、T11 读 6.03 与 6.57、
本刀两轮都读 5.5。

于是十片的 planning value 是 **666 / 627 / 635 / 634 / 628 / 628 / 628 / 625 / 628 / 651 s**，
第一片 **666 s 越过 660 s 的 pole**。这不是一句判断而是一台机器的判断：把 666 写进预算行，
`check-gate-budgets.py` 当场拒绝（`budget claims 3x 666s, over the 660s run-pole`），而那正是
pole 存在的理由。按模型写 651 是能过的，但那等于在三轮读数都说 5.5 的时候继续按 5.088 报账，
每片少报 15 s。

**所以分第十一片**，触发条件是「规划值过 pole」那一半，与刀 20 那次同源。十一片的 planning
value 是 **575 / 581 / 586 / 605 / 606 / 606 / 605 / 604 / 608 / 608 / 568 s**，最差的一片
距 pole 还有 52 s，十条旧行按这一轮重述、第十一条新写。CI 观测那一半没有触发：
`scripts/gate-observations.py` 取 2026-09-05 到 09-06 的 25 次运行，十片的最差是
498 / 471 / 458 / 452 / 445 / 442 / 442 / 431 / 429 / 427 s，都没有被
`check-gate-budgets.py --observed` 点名，离 550 s 的触发线最近的一片还差 52 s；分成十一片之后
预期落在 450 s 上下。**两个触发条件里过了一个就分**，这是第一次由 planning 那一半单独触发。

第十一个 job 不拉长墙钟（并发上限 20，第 47 个 job 排在尾巴上），它买的是预算余量，
账记在 `gates.yml` 的 `tile-golden-11` 注里，`.github/actions/dawn-toolchain/action.yml`
的两个计数同批改成四十七与四十三。

`tile-gpu-diff/run.sh` 在最终树上 **769.9 s**（12:50），比刀 T11 那一轮的 935.3 s 短，
尽管本刀往里加了一个 native 构建（`dyn_diff.dawn`）、七个 case 的真机对拍与两条变异体：
差额是机器负载，不是语料。

`dawn test packages/tileir` 从 122 涨到 **126**，`dawn test --stdlib` 从 174 涨到 **175**。
**本刀碰了 `std/gpu.dawn`**（两个参考实现与一个测试），`scripts/gen-stdsrc.py` 已跑、
`stdsrc.dawn` 同批提交，Core golden 在 rebase 之后的最终树上重录。

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
「61 靠三角函数」（那一句已按本节的结论改写，原话留在这里），开工按刀 9 与刀 21 的规矩逐条
核签名，答案又在签名里：
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

### 6.7 写入器的三个字节形状（刀 T2 实测）

从 `BytecodeGen.cpp` 与 `BytecodeWriter.cpp` 逐条量出来的，三条都是「读源码比读文档准」的
实例。只有第二条是**先写错、被 `tileiras` 纠正**的（那次的报文钉在写入器的注释里），另外两条
在源码里就分得清；写在一起是因为三条都长得像已经在案的某个形状，而字节不是：

1. **`DenseI32ArrayAttr` 不是 `ArrayAttr`。** 归约的 `identities` 是 `mlir::ArrayAttr`，写法是
   「个数 + 每个元素自包含（tag、元素类型下标、载荷）」；`permute` 的 `permutation` 是
   `DenseI32ArrayAttr`，它的 ODS getter 答的是 `ArrayRef<int32_t>`，于是走
   `writeOpAttribute` 的 `writeLEVarSize` 那一支：**个数 varint，然后每个元素四个裸的小端
   字节**，没有 tag 也没有类型下标。两者都是「一串小整数」，读起来一模一样，字节完全不同。
   写入器里 `emit_i32_array` 与 `identity_attr` 相邻放着，包测试把两种形状并排钉死。
2. **变长操作数的操作也写结果个数。** tblgen 的 `Operator::isVariadic()` 对**参数或结果**
   任一为变长都答真，而 `generateSimpleResultSerialization` 是在这个谓词下写结果个数的。
   所以 `extract`（一个固定结果 + 变长的 `indices`）与 `join_tokens`（一个固定结果 + 变长的
   `tokens`）都要在结果类型**之前**写一个 1。先写漏了，`tileiras` 答
   `error at offset 98: failed to get result type 10 for ExtractOp`（它把类型下标当成了个数）。
   写入器里这条走 `emit_op_counted`，与 `emit_op` 分开，注释写着这句报文。
3. **`I64Attr` 是裸的内联 varint。** `cat` 的 `dim` 走 `writeOpAttribute` 的 `std::is_integral_v`
   那一支（`writeVarInt`），读端由生成代码把位宽递给 `parseScalarAttributeInline`，所以流里
   **没有类型下标**、也不是 zigzag 的。与刀 3 起 `reduce` 的 `dim` 同形，这次是确认而不是发现。

另外两条与语义有关、写在 `packages/tileir/src/dev.dawn` 的接口注释里而不是这里：`extract`
的 `indices` 是**切片编号**不是元素偏移（源 tile 的每一维有 `from[k] / to[k]` 个切片），
`permute` 的 `perm[k]` 说的是「答案的第 k 维是源的第 `perm[k]` 维」（PermuteOp 的 verifier
就是拿这条推结果形状的）。
**刀 T3 的实测（其余标量类型，零新操作码）**。六种标量类型 `i16` `i64` `tf32` `f8E4M3FN`
`f8E5M2` `f8E8M0FNU`，字节码侧几乎是现成的（`num_tag` 只多三行），贵的全在宿主与工具链侧。
八条结论，其中五条是**只有跑一遍才知道**的：

1. **三种 fp8 在这台机器上到不了层 2，而且 sm_89 也不行。** 刀单写的是「sm_86 无原生 fp8
   转换指令，cvt 到 e4m3/e5m2 要 sm_89」，实测更严：`tileiras` 13.3.36 在 **sm_86 与 sm_89
   两个目标上都拒**，答
   `error: Incompatibility with architecture 'sm_86': unsupported type 'f8E4M3FN'`，
   `sm_100` 才收。于是 `scripts/tile-golden/run.sh` 多了一个 `kernel_arch()`：三个 fp8 kernel
   按 `--gpu-name sm_100` 汇编，别的照旧 sm_86，字节码 golden 一视同仁。本机是 RTX 3080，
   所以那三行的层 2 是**物理上做不到**而不是没做，豁免逐条写在 `scripts/tileir-features/types.txt`。

2. **`ftof` 从 f64 直接进 f8E8M0FNU 会把 `tileiras` 打死。** 退出码 132（SIGILL），两个流上
   一个字都没有，每个 `--gpu-name` 都一样；从 **f32** 进去则正常。所以 `dtype_e8m0` 这一个
   kernel 绕道 `f64 → f32 → f8E8M0FNU → f32 → f64`，宿主参考跟着舍两次。这是**给汇编器的
   bug 打的补丁**，不是这个格式的性质：注释写在 kernel 上，下一个修好这条的 `tileiras` 应当
   让它少两次转换。

3. **f8E8M0FNU 的舍入模式是类型决定的，两个方向都验过。** Ops.td 说进这个目标只收 `zero`
   与 `positive_inf`，进别的目标只收 `nearest_even`，于是写入器的 `ftof_rounding` 按**目标格式**
   查表（这是本写入器唯一一处由目标格式决定属性字节的地方）。两条层 1 变异体是这句话的两半：
   `e8m0-rounding-as-nearest-even`（一律写默认值）答
   `'cuda_tile.ftof' op invalid rounding mode specified for conversion to f8E8M0FNU. Only 'zero' and 'positive_inf' are supported`，
   `e8m0-tag-as-f8e5m2`（把标签换掉，让 `zero` 落在别的目标上）答
   `'cuda_tile.ftof' op invalid rounding mode specified. Only 'nearest_even' is supported`。
   只有一条的话，一个把模式写死成另一个值的写入器仍然是绿的。

4. **tf32 有存储形态，而且和猜的一样。** 刀单写的是「tf32 大概率没有存储形态（它是 MMA 的
   输入格式）」，实测相反：`ptr<tf32>` 在 **sm_86** 上就被接受，设备把它当一个 32 位槽读，
   低 13 位不参与。宿主那侧 `narrow.tf32_bits` 就是这么铺的（binary32 的字，低 13 位清零），
   512 条 lane 逐位对上，含次正规、含 ±0.0、含 ±inf。所以 `dtype_tf32` 的语料形状不是刀单
   预备的「只能做往返」，而是两段：段 0 读一个 **tf32 缓冲区**（存储形态），段 1 是
   `f64 → tf32 → f64`（转换舍入）。

5. **f64 → tf32 是一次正确舍入，不是双舍入。** 这条本来是风险：设备完全可能把它做成
   `f64 → f32 → tf32`。512 条 lane（含两个精确中点、最大有限值、越界、次正规）与
   `narrow.round_binary(x, 11, -126, 127)` **逐位相同**，所以它是单次舍入。

6. **层 1 分辨不了 f8E4M3FN 与 f8E5M2。** 把 `f8E5M2` 的标签换成 `f8E4M3FN` 的，`tileiras`
   在 sm_100 上一声不吭地收下（两者都是一字节的浮点格式，每个操作都合法）。这就是 `f8E5M2`
   那一行没有变异体的理由，写在台账的豁免里：能分开它们的只有设备，而设备这里够不着。
   `e4m3-tag-as-i8`（换成同宽的整数标签）是能红的那一条，它证明的是 fp8 标签**根本是承重的**。

7. **f8E4M3FN 的溢出答案是一个量不出来的选择。** FN 意味着没有无穷，所以超出 448 的值只能是
   饱和或 NaN，方言的 `ftof` 没有饱和属性。`std/narrow.round_f8e4m3fn` 按 IEEE 的规则做，
   把无穷换成唯一剩下的编码：中点 464 按 ties-to-even 落回 448，再往上是 NaN。
   `round_f8e8m0` 有同样性质的第二个选择（低于 2^-127 的正数向上钳到 2^-127 而不是答 NaN）。
   两处都在源码里写明「这是选择不是测量」，等一台 sm_100 出现再兑现。

8. **i16 与 i64 的层 2 都拿到了，但 i64 欠一格。** i16 的整个值域在 `Float` 里精确，所以
   2^15 回绕是逐位判词的一部分（语料里 137 条 lane 的加法回绕、512 条的乘法回绕、447 条的
   左移回绕）；i64 的宿主通道是 `List[Float]`，53 位有效数字够不到 64 位，所以语料全部落在
   ±2^52 内（505 条 lane 的乘积超出 i32 范围，这是「它真是 64 位」的判词），而 **2^63 回绕
   一格证据也没有**，作为具名欠账写在 `types.txt` 与 `std/gpu` 的 `I64` 上。

**一条层 2 变异体，和它的一个意外。** `tf32-tag-as-f32`（写入器把 tf32 的标签写成 f32 的）
在层 0 不可见、层 1 被收下，设备上只红 `dtype_tf32`。意外在于**红的是段 1 不是段 0**：一个
tf32 的字当 f32 的字读就是同一个数，所以读缓冲区那一段一动不动，动的是转换那一段（该留 11
位有效数字的地方留了 24 位）。`run.sh` 因此不只检查「有一个 kernel 红了」，还检查红在第几段。

**刀 T5 的实测（`loop` 0x41 与 `break` 0x0A，唯一缺的区域形状）。** 三个语义问题在动工前
就问了写入器源码与 `tileiras`，答案写在这里、也写在 `packages/tileir/src/dev.dawn` 的
`t_while_begin` / `t_while_end` 注释里：

1. **`break` 可以在 `loop` 体内嵌套的 `if` 里，这是 C 风格的出口成立的原因。**
   `Ops.td` 给 BreakOp 的是 `ParentOneOf<["IfOp", "LoopOp"]>`，而 `LoopOp` 带
   `SingleBlockImplicitTerminator`：`loop` 的区域只有一个块，块的终结子只能是 `continue`
   或 `break`，所以一个「有时退出、有时继续」的循环**必须**把 `break` 放进体内的 `if`。
   方言自己的 `mlirExample` 印的就是这个形状。于是公开面是一段式的
   `d_loop(init, body)`，`body` 答一个 rank-0 的 `Scalar[I1]` 与下一个值，写入器发
   `if cond { break 进来的值 } else { yield }` 再发 `continue 下一个值`；计划稿里那个
   两段式的 `d_loop_until(init, step, cond)` 不必做。
2. **`break` 与 `continue` 各带几个值：都与循环的携带值一样多，但带的不是同一批。**
   `continue` 带下一轮收到的值，`break` 带循环**结束后的结果**，而 LoopOp 的结果类型可以
   与 iter_values 的类型不同（方言的第四个例子就是 i32 进 f32 出）。本包不用那条自由：
   两边都是携带值的类型。记录 handler 让 `break` 带**进入这一轮的**携带值，所以
   `d_loop` 读作「当 `cond` 为假时把值换成 `next`」，body 在停下来那一轮算出的东西被丢掉。
   写错这一条是**类型错**而不是数值错，`tileiras` 当场拒：把 `break` 的操作数删光，它答
   `'cuda_tile.break' op operand types must correspond to the parent loop result types:
   () vs (...)`，这就是层 1 变异体 `break-values-missing`。
3. **值编号在区域结束时回滚，规则与 `for` 完全一致，而且是同一段代码。**
   `BytecodeWriter.cpp` 的 `writeBlock` 在块开始时记下 `nextValueIndex`，块结束时把
   `valueIndexMap` 弹回去并把计数复位；这与操作是哪一个无关，`for`、`if`、`reduce` 和
   `loop` 都走它。所以 `loop` 的结果编号从块参数占用的那一格重新开始。层 1 变异体
   `loop-carried-not-rolled-back` 删掉本包 `loop` 那一臂的回滚调用（**不是** `for` 那一臂
   共用的 `roll_back` 函数，两条是两个锚点），`tileiras` 答
   `error at offset 196: operand index 37 out of bounds (size=19) for operand 0`。

`loop` 的字节布局比 `for` 少三样、也少一样看不见的：没有归纳变量、没有三个边界操作数，
**也没有 flags varint**。`for` 的 flags 是它的可选属性 `unsignedCmp` 在 13.2 加进来的，
`loop` 一个可选属性和可选操作数都没有，于是 tblgen 的
`getVersionOrderedBitAssignments` 答空表、`generateFlagsFieldSerialization` 直接返回。
剩下的与 `for` 同形：结果个数、结果类型、操作数个数与初值、区域数 1、块数 1、块参数个数
与类型、块内操作数与操作。

**这一刀的层 2 变异体是本目录里唯一一条可能把设备挂住的**，所以它的语料是设计出来的而不是
挑出来的。`loop-break-condition-inverted` 把 handler 建出口时的两个分支对调，于是循环在
条件的**反面**停下。三个带循环的 kernel 都必须在取反之后**更早**停，而不是永不停：
`loop_count` 与 `loop_until` 的条件在进入时为假，取反后第一次测试就 break；`loop_none` 的
条件在进入时为真（它就是「零轮」的那个 kernel），取反后不 break，但它一步跨过阈值，第二次
测试就 break。步长如果小一点，这条变异体就会是一个不返回的 kernel，而
`scripts/tile-gpu-diff/run.sh` 的 `device`（就是 `timeout`）是这件事的机器兜底：任何设备
程序跑过 `DEVICE_TIMEOUT` 秒就被杀掉、判 `launch:timeout` 并中止整轮，不会有哪条变异体
靠「等下去」拿到它想要的判词。杀进程才能释放上下文，等 CUDA 不会。

### 6.8 属性域的实测（刀 T4）

刀 T4 零新操作码，做的是把六个枚举族与三个单位属性里**本仓从没写过的取值**写出来，
放到本机 3080 上问一遍。预研给的分工里有三格写着「层 2 没有判词」，**实测推翻了两格**，
下面按族记。八个 kernel 的形状都是**分段**：同一份操作数、同一个操作，在两个或更多属性
取值下各算一遍，每个答案占输出缓冲区自己的一段。这不是排版，是判词：只算一遍的 kernel
只能对着一份「相信这个属性是什么意思」的参考实现比，两遍都算的 kernel 把差别放进了同一个
缓冲区，于是「属性有没有起作用」是一个**车道计数**，而不是一段论证。那个计数印在
`attr_diff` 的 `probe` 行上，`run.sh` 把每一个都钉在零以上。

**一、三种舍入模式，逐位对上，而且是宿主先写下答案的。** `negative_inf`（2）与
`positive_inf`（3）在 `addf` / `mulf` / `divf` 上，f32 tile；`approx`（4）在 `sqrt` 上。
宿主参考是 `std/narrow` 新加的 `round_binary_toward`，它是 `round_binary` 的定向版本，
和它一样是纯算术（没有 float-to-bits），并且在**溢出**这一格与它不同：往自己符号那侧舍
是无穷，往另一侧舍是最大有限值（IEEE 754 §4.3），一个只会往无穷溢出的实现会在这里读错。
本机实测 `attr_round` **逐位相同**，`probe` 是 `add=512 mul=445 div=494`：512 条车道里
上下两向答案不同的分别是 512、445、494 条，也就是语料确实把结果放在了两个 f32 邻居之间。

**这一格能进逐位档，是语料给的不是代数给的**，理由值得写下来：两个 f32 的和与积在 f64 里
**精确**（积最多 48 位有效），所以宿主可以对精确结果定向舍入；商不精确，于是语料让除数是
**2^-30 乘一个小奇数**，商是一个分母小于 32 的有理数，离任何 f32 格点至少 2^-29 相对距离，
远大于 f64 除法自己的 2^-53 误差，双重舍入因此够不着。`attr_diff` 把这条性质印在 `index`
行上（`odd_divisors=512`）。

**二、`flush_to_zero` 有判词，预研说没有。** 这是本刀最该记的一格。次正规的操作数或次正规的
结果在 FTZ 下变成同号零，这是**可观测的**，语料只要含次正规就行：`attr_ftz` 一半车道加两个
次正规（和是次正规），一半车道拿次正规乘一个正常数（积是次正规），`probe` 读到
`add=256 mul=256`：512 条车道里正好一半在带与不带之间答不同的数。设备的行为与方言散文
逐字相符：**输入和结果都冲**（宿主参考因此先冲两个操作数、再算、再冲结果），逐位对上。
唯一的手续是 f32：`verifyFtz` 只让 f32 tile 带它，而 `std/gpu` 的真设备没有 f32 缓冲格式
（`element_bytes`），所以这一族的 kernel 收 f64 缓冲、进 kernel 再 `ftof` narrow 一次。
f64 精确持有每一个 f32 值（次正规也是），所以这一步不改语料。

**三、`propagate_nan` 与 `unordered` 也都有判词，而且方言的两句散文都成立。**
`maxf` 不带 `propagate_nan` 是 IEEE 754-2019 的 `maximumNumber`（只有两边都是 NaN 才答
NaN，否则答非 NaN 的那个），带上是 `maximum`（有一边是 NaN 就答 NaN）；`ordered` 的比较在
有 NaN 时一律答假，`unordered` 一律答真。`attr_nan` 十六段，`probe` 读到
`ordering=768 maxf=128 minf=128`：六个谓词各在 128 条 NaN 车道上答反，`maxf` 与 `minf` 各
128 条。这是这棵树上**第一次把 NaN 当成一个值来比**。容差档把任一侧的 NaN 判成失败，逐位
档比的是渲染文本，而 `NaN` 是文本里的一个词，所以只有逐位档能问这个问题。

**四、`unsignedCmp` 的答案是一个整数，不是一个舍入。** 起点 `0x7FFFFFF0`、终点
`0x80000010`、步长 1：有符号读法里终点是负数、在起点之下，循环一次都不跑；无符号读法里它
在起点之上 32，循环跑 32 次。`attr_ucmp` 把两个循环各自的迭代次数存出来，本机实测
`signed=0.0 unsigned=32.0`，与手算的一样。这是刀 T4 六个层 3 变异体里唯一一个红得**不像**
数值问题的：`for-unsigned-bit-dropped` 把 32 变成 0。

**五、`approx` 只能是容差档，而它的证据是两段之间的距离。** 近似平方根没有宿主定义：它是
架构的近似，级数是另一个意见，所以 `attr_approx` 的两段（`nearest_even` 与 `approx`）都
对着同一份正确舍入的参考比，两段都在容差之内（最大 miss 是容差的 0.0116）。**属性有没有
到设备，靠的是两段之间的差**：本机 512 条车道里 81 条不同，最大相对距离
**1.1914e-7**，正好是 f32 的一个 ulp（2^-23）。`sqrt-approx-as-nearest-even` 这条变异体
因此是本刀唯一一条**判词抓不到**的：verdict 照样是 `close:tolerance`，红的是那个计数掉到
零，而 `run.sh` 把它钉在零以上，所以它红。这也是那个计数为什么是**钉**而不是**印**。

**六、三种溢出假设与五个内存序 / 范围取值，设备答不了，理由不同。**
`nsw` / `nuw` / `nw` 说的是编译器**可以假设**什么，越界的程序是未定义的：守约的语料带与不带
算出同一个答案，不守约的语料没有可比的答案。裁决 1 点名了这三个，台账的具名豁免叫
`assumption-not-arithmetic`。内存序（`acquire` / `release` / `acq_rel`）与内存范围
（`tl_blk` / `sys`）约束的是**并发**访问，而 `attr_memsem` 每条车道有自己的槽位、每个 block
有自己的 384 个，什么都不竞争，于是每种序算出同一批和；真判词要两个 block 互相观察，那个
判词形状这棵树没有（逐位档比的是一次 launch 之后的一个缓冲区）。豁免叫 `no-race-in-corpus`。
两族的变异体因此都在 `scripts/tile-golden/run.sh` 里、在层 1 红：`overflow-attr-not-written`
让读者把第一个操作数下标当成枚举（`invalid integer value for enum type: 18`），
`atomic-memory-attrs-swapped` 把序与范围对调（`invalid integer value for enum type: 3`）。

**七、`atomic_rmw` 的 `addf` 是一个字节的差，而那个字节只有汇编器看得见。**
`add` 是 3、`addf` 是 4，同一个枚举里的邻居；把 f64 缓冲上的 `addf` 写成 `add`，方言直接
拒绝（`'add' works only with integers i32 and i64`），所以 `rmw-addf-as-add` 是层 1 变异体
而不是设备变异体。`attr_addf` 本身仍是层 2 的客户：四个 block 往**同一批** 128 个槽位原子
累加，车道跨 block 冲突，语料是小整数因而任何到达顺序都是同一个和，与刀 14 给整数直方图
写下的是同一条代数论证。

**八、一件没有判词、也没有假装有的事**：`rmw_mode_value` 里的十种模式有八种今天没有客户
kernel。台账给它们一个自己的状态 `spelled`（写入器的表能拼出来、没有 kernel 要它），
豁免 `no-client-kernel`；叫 implemented 是虚报覆盖，叫 unimplemented 是虚报缺口。

**属性域的第三本账**是 `scripts/tileir-features/attrs.txt`，**50 行**、一行一个取值（刀 T4 建表时
44 行，刀 T6 加了四个属性标签，刀 T15 又加两个），由
`scripts/tileir-features/check.py` 与操作码那本共用一个解析器、各有自己的期望集合与证据
读法。它多一种证据 `const:<NAME>`：写入器里那个常量的**值**要等于台账那一行的 `code`，
这是这本账与写入器之间的机器绑定（操作码那本用的是 `OP_` 表）。`--self-test` 给它十五条
负控加一条阳性对照。

### 6.9 Global 段的字节形状与静态全局的生命期（刀 T7 实测）

刀 T7 加的是 `global` 0x31、`get_global` 0x2C 与 **Global 段（id 6）**。六条结论，前四条
是**读写入器源码**量出来的，后两条只有本机 3080 答得了。

**一、`global` 不在指令流里，它是段里的一条记录。** 它在冻结的操作码表里有编号，
`BytecodeWriter.cpp` 却从不把它写进函数体：`writeGlobalSection` 把模块里的 `GlobalOp`
收集起来单独成段，`writeFunctionTableSection` 那一侧的 `isa<FunctionOpInterface, GlobalOp>`
把它跳过。所以本仓没有 `OP_GLOBAL` 常量，台账 `features.txt` 给它的状态是
**`structural`**，与 `entry` 0x16、`module` 0x4B 同类，证据是写入器的函数名
（`writer:global_section`）而不是一条指令。`get_global` 相反，它是 entry 里的一条普通指令，
状态是 `implemented`。

**二、一条记录是四个 varint，不是六个。** 布局（`writeGlobalSection` 与 `parseGlobalSection`
两半对读）：

```
global-section =: numGlobals[varint] global-entry*
global-entry   =: symbolNameIndex[varint] valueTypeIndex[varint]
                  constantValueIndex[varint] alignment[varint]
```

初始值本身**不在这一段里**，它走 Constant 段，记录里只有下标；类型是初始值的 tile 类型
（`GlobalOp::verify` 要求 rank 为 1，所以是 `tile<Nxf64>` 而不是 `tile<f64>`），
`alignment` 是 13.1 就有的 `I64Attr`，默认 0。这一段只写 varint、从不对齐，所以段头不带
对齐位；读者对这个段号**特意跳过对齐校验**（`Section::Global` 那一条 case 的注释就是这么写的）。
它在文件里排**第一**，在 Func 之前，与 `writeBytecode` 的顺序一致；读者按 id 收集 payload
再按自己的顺序解析，所以位置是惯例不是要求。

**三、13.3 才加的两个字段，在 13.2 上一律不写，而这不是「少写一点」。**
`symbol_visibility` 与 `constant` 在 Ops.td 里被标成 `"13.3"`，写入器在 13.3 以下写四个
varint、在 13.3 及以上写六个，读者的 `kMinGlobalInfoSize` 在同一个边界上从 4 变 6。于是在
T7 当时钉的 13.2 上，多写那两个 varint 不是「一条读者会跳过的长记录」，而是**下一条记录被从
那两个字节开始读**。变异体 `global-visibility-written-at-13-2` 就是这句话，`tileiras` 答
`expect Cuda Tile integer or float type but got: '<<NULL TYPE>>'`；这也是语料要在一个模块里
声明**两个**全局的原因（只有一个的话，多出来的字节落在段尾、读者根本不看）。C++ 写入器从
另一侧说同一件事，而且指名道姓：
`global \`x\` uses non-public symbol visibility, which cannot be encoded in bytecode version 13.2 (requires bytecode 13.3+)`。
**所以 `visibility.public` / `visibility.private` / `unit.constant` 三行从 T7 改判给 T8**，
理由具名写在 `attrs.txt` 的 `13.3-record-field`。注意 `since` 列仍是 13.1：
SymbolVisibility **枚举**的两个取值确实是 13.1（AttrDefs.td），13.3 的是 GlobalOp 上那个
**参数**和段里那两个字段。「值存在」与「有地方写它」是两件事，台账的两列分别说这两件事。

**刀 T8 把这一段兑现了，也把它的变异体翻了过来。** 钉子挪到 13.3 之后写入器写六个 varint，
`global-visibility-written-at-13-2` 于是变成一句合法的写法、被同一把刀退役，取而代之的是
反向的 `global-visibility-omitted-at-13-3`（在 13.3 的文件里只写四个）。同一堵墙的两侧，
两次都由 `global_table` 的两个全局钉住，报文见 §6.11。

**四、`get_global` 的符号是一个纯字符串表下标。** 它的 `name` 是 `FlatSymbolRefAttr`，
tblgen 生成的 getter 答 `StringRef`，于是走 `writeOpAttribute` 的 `std::is_same_v<..., StringRef>`
那一支，写 `strMgr.getStringIndex(name)`；读者的 `FlatSymbolRefAttr` 分支用
`readAndGetString` 读回来。流里**没有 tag、没有类型下标**。它既无变长操作数也无变长结果，
所以不写个数；它没有可选字段，所以不写 flags。整条指令就是
`opcode, resultTypeIndex, symbolStringIndex` 三个 varint。结果类型是 **rank-0 的
`tile<ptr<T>>`**（ODS 写的是 `ScalarTileOf<PointerType>`），所以本包的降低把它接上
`MakePtrs` 用的同一对 `reshape` + `broadcast`，一个字都不用新写。

**五、`tileiras` 读不了文本，所以 .mlir 这一层没有对拍。** `tileiras --help` 的
USAGE 行写的是 `<tile bytecode file>`，把渲染出的 `.mlir` 喂给它答
`input does not correspond to Tile IR bytecode`（退出码 3，实测）。于是 `global` 那行的
文本形状只被层 0 的 golden 钉住，字节形状被层 1 钉住，两者互不校对；这与本目录里每一条
操作一样，写在这里是因为刀单问了。渲染出的初始值用的是本渲染器自己的浮点拼法
（`1.5`，MLIR 的打印器会写 `1.500000e+00`），与 `ConstFloat` 一致。

**六、静态存储确实跨 launch 保值，本机量到了。** `global_scratch` 的 kernel 把输入加到一个
可写全局上，把和同时写回全局和输出；`std/gpu` 的真 handler 按 kernel 名缓存已装载的模块
（`with_gpu_real` 的 `mods`），所以**同一个模块连发两次 launch**，第二次读到的是第一次写的。
实测输出是输入的两倍（前三条车道 `6.25, 6.5, 6.75`，输入是 `3.125, 3.25, 3.375`），与宿主
参考逐位相同。宿主参考把同一个累加量放在**输出缓冲区**里，那是宿主唯一看得见它的地方，
所以两边只在「全局保住了值」这一条成立时才对得上。刀单预留的「若真机每次 launch 重新装载
模块就改成同一 launch 内先写后读」这条退路**没有用上**。
变异体 `module-reloaded-per-launch` 是这句话的反面：把 handler 的模块缓存拿掉、每次 launch
重新 `cuModuleLoadData`，于是全局每次回到初始值，`global_scratch` 红而 `global_table` /
`global_ctl` 不动。它**一个字节都不动**，层 0 与层 1 看不见它，因为字节码里根本没有一句话
说模块活多久；这是本目录里第二条这种形状的变异体（第一条是 `grid-y-ignored`）。

**可见性够不着的那一格，欠的是什么（已还，而答案不是这段话预期的）。** 这一段原来写的是：
「宿主能看见 public 而看不见 private」这个判词还需要一条本仓没有的 FFI，`cuModuleGetGlobal`，
所以那两个取值最多到层 1，要到层 2 得先加那条 FFI。**刀 TG 加了那条 FFI，判词并没有出现。**
本机的驱动对 `private` 全局与 public 全局一视同仁：都查得到、都读得回、都写得进、写完
launch 都读得到新值。所以欠的从来不是一条 FFI，是一个这台机器上不存在的差别；`attrs.txt`
上那三行的豁免因此从 `no-module-symbol-ffi` 换成 `visibility-not-in-the-lookup`（可见性；符号查询与链接两处都问过了）与
`constant-not-in-the-cubin`（`constant`），逐条实测记在 §6.13。**这条欠账在 T8 落地后已经
换过一次名字**：`13.3-record-field` 说的是「没有字节可写」，那件事 T8 解决了；这是第二次。

### 6.10 `OptimizationHints` 的字节形状与它到达了哪里（刀 T15）

刀 T15 零新操作码，做的是**属性标签 11 与它包着的标签 10**。这一族与前面每一族都不同的地方
不在字节上，在判词上：方言明说 hint 是**建议**，不改变 kernel 算什么，所以这一格的层 2
`device:` 证据**按定义写不出来**，台账因此把这一族封在层 1 并具名豁免
`hints-do-not-change-answers`（裁决 1 点名的就是它）。下面按「字节」「工具链答什么」
「设备答什么」三段记。

**一、同一个属性，两个地方，两种字节。** 这是从 `BytecodeWriter.cpp` 逐条读出来的，不是猜的，
而且它把一条比 T6 那条更细的规矩摆了出来：

| 写在哪 | 走哪条路 | 标签 11 | 之后 |
|--------|----------|---------|------|
| entry | `writeFunctionTableSection` → `writeSelfContainedAttribute` | **写** | 里面那个 `DictionaryAttr` 以 `isSelfContained=false` 写，所以**没有** 10 |
| load / store | 生成的算子写入器 → `writeOpAttribute` | **不写** | flags 的那一位就是宣告，字节直接从外层计数开始 |

判据是 `writeOpAttribute` 的 `std::is_base_of_v<Attribute, T>` 那一支：
`isSelfContained = mlir::detail::IsInterface<T>::value`。`assume` 的 `predicate` 声明成
**接口**（刀 T6 的 §6.8 记过），所以它带标签；`optimization_hints` 声明成具体的
`CudaTile_OptimizationHintsAttr`，所以它不带。**同一个属性类型在函数表里带标签、在指令里不带**，
两处都对，而且没有第三种可能。

外层字典的**值**是每架构一个 `DictionaryAttr`，值是自包含的，所以每一个都带自己的 10。一个
hint 的值是自包含的 `IntegerAttr`：标签 1、`i64` 的类型下标、varint 的值。于是完整形状是

```
[11]                      只有 entry 写这一个字节
<varint N>                架构条目数
  <varint strIdx(arch)>   "sm_86" / "default" 的 String 段下标
  [10]                    这个值是一个字典
  <varint M>              这个架构下的 hint 数
    <varint strIdx(key)>  "occupancy" 等
    [1] <varint i64> <varint value>
```

**键是 String 段下标而不是内联字节**，读端 `readAndGetString`；**空键与重复键被拒**
（`DictionaryAttr::findDuplicate`）；**顺序不作要求**（`DictionaryAttr::get` 自己排序），
本写入器仍按字典序写，因为那是 C++ 写入器对同一段文本会写出的字节。

指令那一侧还有一个位置问题，`getVersionOrderedBitAssignments` 回答了：flags 的位先按版本分组，
组内**先属性后操作数**。load 的可选字段全是 13.1，声明序是 `memory_scope`、
`optimization_hints`、`mask`、`paddingValue`、`token`，所以 hint 是**第 1 位**，
`bytecode.dawn` 里那三个 mask / pad / token 常量从 4 起也正是因为这两位在前面。属性字节写在
flags 与必写的内联枚举之后、操作数之前。

**二、工具链只看形状，不看内容，而这是量出来的。**
`OptimizationHintsAttr::verifyParamWithContext` 第一行就是
`if (!getWarnUnsupportedHints()) return success();`，而 `-Wunsupported-hints` 默认关。
本机实测三条，`tileiras --gpu-name sm_86` 每一条都**退出 0、两个流上一个字都没有**：

| 改什么 | 结果 |
|--------|------|
| 键写成 `occupancy_qqq`（方言没有的名字） | 收下 |
| 架构写成 `sm_86a`（方言没有的架构） | 收下 |
| `latency` 写成 904（合法范围是 1 到 10） | 收下 |

所以计划里那条 `hint-key-unknown` **做不成变异体**：它不会红。这一格是「层 1 盲」，
台账的豁免把这三句话原样记下。**能红的全是形状**，四条都在
`scripts/tile-golden/run.sh`，各钉一句 `tileiras` 的原话：

| 变异体 | 改哪 | 报文 |
|--------|------|------|
| `hint-dictionary-count-wrong` | 内层字典的条目数 +1 | `failed to read key for DictionaryAttr element 1` |
| `hint-tag-as-dictionary` | entry 的标签 11 写成 10 | `invalid optimization hints attribute for function 'hint_entry'` |
| `hint-flag-bit-misplaced` | load 的 hint 位写成 `memory_scope` 的第 0 位 | `operand index 91 out of bounds (size=19) for operand 1` |
| `hint-entry-flag-dropped` | entry 的 0x04 位不置、属性照写 | `operand index 10 out of bounds (size=4) for operand 0` |

第二条值得单记：把 11 换成 10，读端把整个属性**解析成功**（一个 OptimizationHints 就是前面
多一个字节的 Dictionary），然后函数表拒绝手里这个东西。所以那一个字节是**身份**而不是拼写。

**三、hint 到达了编译器，而这是 cubin 说的，不是判词说的。** 同一个 kernel 带与不带 hint，
`tileiras --gpu-name sm_86` 出的 cubin 都是 8320 字节，md5 如下（`hint_entry` 的体就是 vadd 的体）：

| entry 上的 hints | cubin md5 |
|------------------|-----------|
| 无 | `b9f8073b8900f52eaf6e5727c56d581c` |
| `sm_86 = {num_cta_in_cga = 1}` | 同上 |
| `sm_86 = {num_worker_warps_per_cta = 4}` | 同上 |
| `sm_100 = {occupancy = 2}` | 同上 |
| `sm_86 = {occupancy = 2}` | 同上 |
| `sm_86 = {num_worker_warps_per_cta = 8}` | `f5b9ee2b2ad45ac6de4258809f993dc7` |
| `sm_86 = {occupancy = 4}` | `e83a91915fdfad399c6e66c45fa6d85e` |
| `default = {occupancy = 4}` | `e83a91915fdfad399c6e66c45fa6d85e` |
| `sm_86 = {num_worker_warps_per_cta = 8, occupancy = 2}` | `e68cdd6cd009fdd512a8784aefcd3826` |
| `default = {occupancy = 4}` 加 `sm_86 = {num_cta_in_cga = 1, num_worker_warps_per_cta = 8, occupancy = 2}` | `e68cdd6cd009fdd512a8784aefcd3826` |
| `default = {occupancy = 4}` 加 `sm_86 = {num_worker_warps_per_cta = 8}` | `0cbe7b98b9e33d7c4b2392504a1d8d57` |

四条读得出来的话：

1. **入口 hint 真的进了编译器。** 两个键各自都能把 cubin 换掉。
2. **`default` 是真的 fallback，而且被 `sm_xx` 盖住。** 第 7 与第 8 行字节相同（`default` 供出
   `occupancy = 4`），第 9 与第 10 行也相同（`sm_86` 有自己的 `occupancy`，`default` 那份不算数）。
   一个不读 `default` 的实现会让第 8 行等于「无」，一个不让 `sm_xx` 盖住 `default` 的实现会让
   第 10 行等于第 11 行。
3. **架构键被当真。** `sm_100 = {occupancy = 2}` 在 sm_86 上等于「无」。
4. **单个 hint 与「默认值」不是一回事。** `occupancy = 2` 单独写等于「无」，
   而 `warps = 8` 之后再写 `occupancy = 2` 又不等于只写 `warps = 8`：这两个键在编译器里互相影响，
   所以「某个值就是默认值」这句话对单个键成立、对一对不成立。

**load / store 上的 `latency` 不动 cubin 一个字节**（`hint_memory` 带与不带，8320 字节逐字节相同，
md5 `bddd559544b055ecbf7cd8458ae16eab`）。本机没有 `cuobjdump` / `nvdisasm`（钉的三个 wheel 里
没有，`tileiras` 那个 bin 目录里只有 `ptxas` 与 `nvcc`），所以 SASS 一层没有第二意见，
上面这些只有长度与 md5。

**这一整节都不是判词。** 汇编器可以忽略任何 hint，也可以对任何 hint 动手，两种都合规，
所以没有一行进 PASS / FAIL 的门。`scripts/tile-gpu-diff/hint_diff.dawn` 问的是能问的那一句：
`hint_entry`、`hint_memory` 与**不带任何 hint 的 `vadd`** 在同一份语料上跑，三个设备答案
**逐字节相同**（`agree=3/3`，run.sh 钉住）。那是方言的承诺被守住，不是某个取值被观测到。

### 6.11 版本墙：13.2 到 13.3 逐处量了一遍（刀 T8）

刀 T8 零新操作码，做的只有一件事：把 `BYTECODE_MINOR` 从 2 挪到 3。预研说这一步只动三处
字节，刀 T7 量出第四处，本刀**没有沿用那份清单，而是把写入器重新枚举了一遍**，因为
「只动三处」这种话正是过一年就不再为真的那一类。

**一、清单是枚举出来的，不是抄来的。** 在 `NVIDIA/cuda-tile@be0889cd` 上，一个操作在
13.2 与 13.3 之间改变形状只有两条途径，两条都由 tblgen 生成：`BytecodeGen.cpp` 的
`generateFlagsFieldSerialization`（某个操作的**第一个**可选字段落在 13.3，于是 flags varint
从 13.3 起才写）与同文件的必需属性那一支（`DefaultValuedAttr` 标成 13.3，于是那个值从 13.3
起内联写、低于 13.3 时若不等于默认值就报错）。所以把 `Ops.td` 里每一条 `"13.3"` 的参数逐行
列出来，再去掉本身就是 13.3 才有的操作（`alloca` / `atomic_red_view_tko` / `mmaf_scaled` /
`pack` / `unpack` / `make_strided_view` / `make_gather_scatter_view`，本仓一条都不发），
剩下的只有四行，落在三个操作上：

| 操作 | 13.3 的字段 | ODS 里的种类 | 字节上的后果 |
|------|-------------|--------------|--------------|
| `exp` 0x17 | `rounding_mode` | `DefaultValuedAttr`（必需，默认 `full`） | 13.3 起内联多一个 varint |
| `mmaf` 0x49 | `fast_acc` | `UnitAttr`（可选，且是它唯一的可选字段） | 13.3 起多一个 flags varint |
| `global` 0x31 | `constant` 与 `symbol_visibility` | 一个 `UnitAttr` 一个 `DefaultValuedAttr` | 不在指令流里，见下 |
| `module` 0x4B | `producer` | `OptionalAttr<StrAttr>` | Producer 段，见下 |

`BytecodeWriter.cpp` 里另有两处**手写**的版本分支，与 tblgen 无关：`writeGlobalSection`
（`kMinGlobalExtendedFields` = 13.3，低于它一条记录写四个 varint、到了它写六个，多出来的正是
上表 `global` 那两个字段）与 `writeProducerSection`（13.3 起才有的段）。加上文件头的
major / minor / tag 三个字节，写入器里**全部**的版本相关处就是这些；其余的版本判断
（`isOpcodeAvailableInVersion`、`isAttrTagAvailableInVersion`、`isEnumValueAvailableInVersion`）
都只决定**拒不拒**，不决定形状，而往高版本走从不失去任何东西。

**二、六处里有两处对本仓恰好是空的，而这也是量出来的。**

- **Producer 段**：`writeProducerSection` 在 13.3 以下直接返回，在 13.3 及以上**也**直接返回，
  只要模块没有 `producer` 属性。本仓从不设它，所以这个段一个字节都不写。
- **类型的统一位域**：`BytecodeTypeCodeGen.cpp` 有第三个 13.3 边界，
  `kUnifiedBitfieldVersion`，带 `OptionalParameter` 的**类型**从 13.3 起改写一个统一的位域
  varint。这一处预研与 T7 都没有提到，本刀是第一次记它。它对本仓为空的理由是可查的：
  `Types.td` 里带 `OptionalParameter` 的类型恰好只有三个，`PartitionViewType`、
  `StridedViewType` 与 `GatherScatterViewType`（**不是 `TensorViewType`**：它的三个参数
  `elementType` / `shape` / `strides` 一个可选的都没有，这句 T8 写错了，T11 改正），全是
  view 族，按裁决 2 与 T11 到 T13 一起挂起；`ptr` / `tile` / `token` / `func` 一个可选参数
  都没有。**这条要记下来，因为 view 族一旦解禁它就不再是空的**，那时字节形状会跟着版本变，
  而不是只跟着类型变。（**它已经不空了**：裁决 2 于 2026-09-06 被撤销，刀 T11 落地了
  `PartitionViewType` 的 `padding_value`，两条路都写在 `bytecode.dawn` 里，见 §6.14。）

于是真正会动的是四处：文件头第 10 字节、`exp` 的内联 `rounding_mode`、`mmaf` 的 flags varint、
Global 段记录的两个 varint。写入器把这四处写成四个谓词（`for_has_flags` 的形状，共用一个
`at_least`），所以下一次挪钉子改的是常量而不是四段代码。

**三、「其余的逐字节相同」是量出来的，两个方向各量了一次。**

正向是**账**：162 个 kernel 逐个把 13.2 与 13.3 的 `.tilebc` 拆成段，Func 段应当涨
「`exp` 条数加 `mmaf` 条数」个字节、Global 段应当涨「全局条数乘二」个字节，两个数都从
`.mlir` 上数出来。**162 个 kernel 全部对上，没有一个例外**：Func 段总共涨 56 字节、
Global 段总共涨 6 字节，与预测逐字相等。109 个 kernel 一条 `exp`、一条 `mmaf`、一个全局都
没有，它们与 13.2 的差别**只有第 10 个字节**。文件总长这一格另说：159 个文件长度不变
（段的对齐填充把涨的那点吃掉了），3 个正好长 8 字节（`attn_scores` / `gqa_scores` /
`lin_attn_s`，它们的 Func 段跨过了一个 8 字节对齐边界，所以填充整整多了一步）。**所以
「同样大小」不是这一族变异体的判据，段长才是**，`exp-rounding-unwritten` 与
`mmaf-flags-unwritten` 因此用 `func-one-short` 而不是 `same-size`。

反向是**复现**：把本刀这棵树的写入器的 `BYTECODE_MINOR` 改回 2（只改这一个常量，三个谓词
随之全部为假），重新生成每一个 kernel 的字节码，与 `origin/main` 上 T7 那一代录下的 golden
逐字节比。**162 个全部相同。** 这一条比正向那一条强：正向说「差的地方是我预测的那些」，
反向说「除了这些谓词，写入器一个字节也没有别的改动」，两句话合起来才是「版本墙只是版本墙」。

**四、这堵墙不改设备答案，而这是本节最该记的一句。** 用钉版本的 `tileiras` 13.3.36 把每个
kernel 的 13.2 字节与 13.3 字节各汇编一次（三个 fp8 kernel 照旧走 `--gpu-name sm_100`，
其余 `sm_86`），**162 个 cubin 逐字节相同，一个都不差**。所以升版买到的是 13.3 才有的操作码
（`pack` / `unpack` / `alloca` / `mmaf_scaled`，归 T9 与 T10）与 Global 记录的两个字段，
付出的是零：既有 kernel 在设备上算的东西一个位都没动。`toolchain.txt` 里原来那句
「13.2 is the lowest version Tile IR runs on Ampere and Ada」也随本刀改掉了。那句话把
**架构的下限**说成了**字节码版本的性质**；架构下限是 r580 驱动与 `sm_86` 目标，由
`driver` 与 `gpu-name` 两行各自承担。

**五、`fast_acc` 到不了设备，这一格也是量的不是推的。** `mmaf` 的 flags varint 从 13.3 起
存在，本仓写 0。把写入器那个字改成 1 之后，`.tilebc` 恰好动一个字节，而
`tileiras --gpu-name sm_86` 出的 cubin **逐字节不变**，四个 `mmaf` kernel 都试过
（`matmul` / `batched_matmul_f16` / `attn_scores` / `lora_hidden`），f16 那个与 f64 那些
一样不变。一个到不了设备的位不可能让设备答出别的数，所以 `attrs.txt` 的 `unit.fast_acc`
封在层 1，豁免叫 `fast-acc-not-in-the-cubin`，那是一句实测而不是一句「没写客户 kernel」。

**六、头里的版本号确实约束读者，而这需要一条变异体才知道。** `header-minor-still-2` 让头
写 13.2、正文照 13.3 的形状写。读者本可以不理会那个字节（后面的字节是一个合法的 13.3 程序），
实测它理会：`tileiras` 答
`expect Cuda Tile integer or float type but got: '<<NULL TYPE>>'`，**与 T7 的
`global-visibility-written-at-13-2` 一模一样的报文**，因为读者正是拿头里的版本去选
`kMinGlobalInfoSize`，选了 4 就把第二条记录从多出来的那两个 varint 读起。同一堵墙，
T7 从 13.2 那侧撞过一次，本刀从 13.3 这侧撞回去（`global-visibility-omitted-at-13-3`），
而这一条从头顶上撞下来。

**七、四条层 1 变异体的报文，逐条钉在 `run.sh` 里。**

| 变异体 | 改哪 | `tileiras` 的原话 |
|--------|------|-------------------|
| `exp-rounding-unwritten` | `exp` 不写 13.3 的 `rounding_mode` | `error at offset 67: invalid integer value for enum type: 21` 加 `failed to parse attribute 'rounding_mode'`（21 是紧跟着的操作数下标） |
| `mmaf-flags-unwritten` | `mmaf` 不写 13.3 的 flags varint | `invalid block structure: block is expected to have a terminator operation, but the last operation 'cuda_tile.absf' is not a terminator.` |
| `global-visibility-omitted-at-13-3` | Global 记录在 13.3 上只写四个 varint | `number of globals (2) exceeds the maximum of 1 that can fit in the remaining payload of 9 bytes.` |
| `header-minor-still-2` | 头写 13.2，正文写 13.3 形状 | `expect Cuda Tile integer or float type but got: '<<NULL TYPE>>'` |

T7 的 `global-record-alignment-dropped` 还在，但它的**报文换了数字**：记录从四个 varint 长成
六个，剩余载荷从 6 字节变成 10 字节，所以那句话现在是
`... that can fit in the remaining payload of 10 bytes`。这是「变异体的判词是报文原文，
不是退出码」的又一个实例：光看退出码的话，这条变异体在版本挪动之后仍然是绿的。

**八、可见性与 `constant` 只买到层 1，欠的那条 FFI 写在台账里。** 新 kernel `global_flags`
声明一个 `private` 全局与一个 `constant` 全局并读它们，`tileiras` 在 sm_86 上一次通过
（10496 字节 cubin，`FUNC GLOBAL global_flags`），Global 段的两条记录末尾分别是
`01 00` 与 `00 01`。这就是这两个取值能拿到的全部：分得清 public 与 private 的判词是
「宿主查得到前者、查不到后者」，要 `cuModuleGetGlobal`，而 `std/gpu` 的 `Gpu` 效果里没有这条
操作，本刀也不为它扩 handler 面。`attrs.txt` 上三行的豁免因此从 `13.3-record-field`
（「没有字节可写」，本刀已解决）换成 `no-module-symbol-ffi`（「没有 FFI 可问」，仍然欠着）。

> **刀 TG 后记（2026-09-06）**：那条 FFI 加了，判词没有出现。本机驱动的
> `cuModuleGetGlobal` 对 private 全局与 public 全局答的是同一件事，`constant` 位连 cubin
> 都进不去。链接那一侧也问过了（两个各声明同名 public 全局的 cubin 撞不撞名），同样问不出来：
> `cuLinkComplete` 对**任何** cubin-only 链接都答 `CUDA_ERROR_NO_BINARY_FOR_GPU`，
> 一个输入也一样、`ptxas` 出的普通 cubin 也一样，而同一个 harness 喂 PTX 链得通，所以那是
> 这台驱动对 cubin 的态度而不是可见性的性质。所以这一段的最后一句已经作废，三行的豁免现在叫
> `visibility-not-in-the-lookup` 与 `constant-not-in-the-cubin`，两次实测都写在 §6.13。本节其余
> 七条不受影响：它们说的是字节，而字节没有变。

### 6.12 亚字节：`i4` 与 `f4E2M1FN` 的位布局，`pack` / `unpack` 的字节形状（刀 T9 实测）

刀 T9 加两条操作码（`pack` 0x6F、`unpack` 0x70）与两个类型标签（`f4E2M1FN` 19、`i4` 22），
四个都是 13.3 才有的。字节码版本刀 T8 已经挪到 13.3，所以这一刀不碰版本。八条结论，
其中五条只有跑一遍才知道。

**一、`i4` 不是一个数值类型，它是一个 tile 元素格式。** `Types.td` 的 `CudaTile_AnyInt`
列的是 i1 / i8 / i16 / i32 / i64，**没有 i4**；`CudaTile_NumberType` 是 `AnyFloat` 加
`AnyInt`，而 `ptr` 的 pointee 参数受 `CudaTile_NumberType` 约束。于是 **`ptr<i4>` 根本不成立**，
一个 i4 的缓冲区在这个方言里不存在。i4 只出现在四处：`CudaTile_TileElementType`（所以
`tile<Nxi4>` 成立）、`ExtIOp_IntegerType`、`TruncIOp_IntegerType`，以及 `pack` / `unpack`
两个操作自己的 `!listconcat(..., [CudaTile_Int4])`。**它没有任何算术**：`addi` 一族要
`CudaTile_IntTileType`，那张表也把 i4 排除在外。所以一个 i4 kernel 的形状是被方言定死的：
读字节、`unpack`、`exti` widen、在 32 位上算、`trunci` 回四位、`pack`、写字节。
`scripts/tile-golden/kernels.dawn` 的 `dtype_i4` 就是这七步。

`f4E2M1FN` 不一样：它在 `CudaTile_AnyFloat` 里，所以 `ptr<f4E2M1FN>` 能解析，`ftof` 也收它
（`CudaTile_FloatTileType` 列了它）。本仓仍然不给它开缓冲区通道，理由是宿主侧：
`std/gpu.element_bytes` 说的是「一个缓冲区元素占几个字节」，而半个字节它答不出来。
两个格式因此都走同一条路，语料把 lane 装在 i32 字里，kernel 自己 `pack` 成字节。

**二、半字节的顺序是方言写死的，而写下它的地方是 tensor view 那一节。** `Types.td` 在
`TensorViewType` 的注释里把 4 位格式的排布逐位画了出来：元素 `i`（i 为偶）在一个字节的
bits 3..0，元素 `i + 1` 在 bits 7..4，并且举了 `[0.5, 1.5]` 的例子（0001 与 0011，
低半字节先）。view 族按裁决 2 挂起，但**这条排布不是 view 的性质**，`unpack` 铺 tile 用的是
同一条；本刀在 3080 上验过（`dtype_i4` 的段 4 按 lane 奇偶取 a 或 b 的半字节，与宿主
`std/gpu.nibble_at` 逐位相同）。宿主那一侧只有一个函数说这件事（`nibble_shift`），
两个方向都读它，变异体 `pack-halves-swapped` 改的就是它。

**三、`pack` / `unpack` 的字节形状与 `bitcast` 一模一样，一个字节都不多。** 两条操作各有
一个固定操作数、一个固定结果、**零个属性、零个可选字段**，所以 tblgen 的
`getVersionOrderedBitAssignments` 答空表、`generateFlagsFieldSerialization` 什么都不写，
`generateSimpleResultSerialization` 也只写结果类型下标而不写结果个数（它不是变长的，
与刀 T2 记的 `extract` / `join_tokens` 相反）。流里是「opcode、结果类型下标、操作数下标」，
和一条 `bitcast` 逐字段同形。本包因此**没有为它们新加渲染臂或写入臂**：它们降低成同一条
`Cast` 指令，唯一的差别是两个 `Ty` 的形状不同，而形状本来就在 `Ty` 里。

**四、结果的 lane 数是操作的一半而不是一个属性。** `verifyPackUnpackTypes`（两条共用一个
模板）要求：两边都是 rank 1；两边的元素**位宽不同**（同宽用 `bitcast`）；两边都是整数个字节；
两边的**总位数相等**。它算位宽时 `i1` 按 1 位、`tf32` 按 32 位、其余按
`getIntOrFloatBitWidth`。于是 lane 数按两个宽度的比例缩放，这是一条算出来的形状而不是一个
写在流里的数。变异体 `pack-result-shape-unhalved` 把这个比例去掉，`tileiras` 答
`'cuda_tile.pack' op expects source and result to have the same size in bytes, but got source
tile size 128 bytes and result tile size 32 bytes`。这也是本目录里**唯一一条文本与字节一起动**
的变异体，而那是操作的性质不是选择：lane 数就是结果类型，渲染器印的是交给它的类型。

**五、`i4` 在 sm_86 上就能跑，`f4E2M1FN` 不能，而且拒的是类型不是算术。** 实测
`tileiras` 13.3.36：`dtype_i4` 与 `pack_roundtrip`（含 `pack` / `unpack` / `exti` / `trunci`
over i4）在 sm_86、sm_89、sm_100 三个目标上全收；`dtype_e2m1` 与任何提到 `f4E2M1FN` 的
kernel 在 sm_86 与 sm_89 上都答
`error: Incompatibility with architecture 'sm_86': unsupported type 'f4E2M1FN'`，sm_100 才收。
**刀单预备的那条退路不成立**：预研设想「把 f4 的位模式当整数搬，让 pack/unpack 至少在位模式上
到层 2」，实测被拒的是**类型本身**，所以一个只 `unpack` 成 `f4E2M1FN` 再 `pack` 回去、
一次转换都不做的 kernel 同样进不了 sm_86 的汇编器。于是 `pack_roundtrip` 的第二段改走
`i16`（另一个方向的比例：字节数减半），fp4 那一段搬进 `dtype_e2m1`，按 `--gpu-name sm_100`
离线装配到层 1，层 2 的豁免与三个 fp8 格式逐字相同。

**六、i4 的层 2 判词只能是移位，不能是加减乘。** i4 没有自己的算术，所以 kernel 一定先 widen；
而 `+ - *` 在模 16 意义下与 widen 的符号无关，零扩展和符号扩展给出的低四位一样。能分开两者的
是**算术移位**：`-1 >> 1` 是 -1、`15 >>> 1` 是 7，落回半字节是 0xF 与 0x7。`dtype_i4` 的段 1
与段 2 因此是同一条移位在两种 widen 下的两份答案，语料 4096 条 lane 里有 2048 条最高位为 1。
写入器的 `exti` 一直只写 `UNSIGNED`，本刀按 `shri` / `shru` 的老办法加了第二个名字 `extis`
（同一条 opcode、另一个 signedness 属性），层 2 变异体 `exti-i4-zero-extends` 改的就是那一个
字节：文本不动（渲染器有自己的表）、`tileiras` 收下（两个取值都合法）、文件同长，只有设备看得见。

**七、半字节顺序的判词必须依赖 lane 下标，否则一致的换名是看不见的。** 这一条是变异体逼出来的。
宿主把「lane k 在字里的位置」收成一个函数之后，`pack-halves-swapped` 换的是一次**一致的重命名**：
读和写都换，于是任何「对每条 lane 做同一件事」的段都仍然与设备相符（一个一元函数与一个置换
及其逆的复合还是它自己）。`dtype_i4` 的段 4 是为这条变异体存在的：它按 lane 奇偶取 a 或 b 的
半字节，是全族唯一一处运算依赖下标的地方，实测也正是唯一红的一段
（`first seg 4 lane 0: device -2.52645136E8 host 2.52645135E8`）。`pack_roundtrip` 则是族内控制，
它一次往返把 lane 放回原处，对顺序完全失明。

**八、fp4 的两个答案是选择，而这台机器量不了。** `f4E2M1FN` 的 FN 比 `f8E4M3FN` 的强：那个格式
没有无穷但留了两个 NaN 编码，这个格式**两样都没有**，十六个位模式全是有限数
（±0、±0.5、±1、±1.5、±2、±3、±4、±6）。于是超出 6.0 与 NaN 进来时没有可答的编码，
`std/narrow.round_f4e2m1` 的两条选择逐条写在源码里：溢出**饱和**到同号的 6.0（OCP MX 的转换
是饱和的，而且没有无穷可溢出），NaN 答 +0.0（零是唯一不会被任何有限输入答出来的值，
所以读回它的语料知道自己撞到了这条臂）。`round_f8e4m3fn` 与 `round_f8e8m0` 各留过一条同样
性质的选择，三条都要等一台 sm_100 才能兑现。


### 6.12 `alloca` 与 `mmaf_scaled` 的实测（刀 T10）

刀 T10 加的是 13.3 剩下的两条非 view 操作码：`alloca` 0x71 与 `mmaf_scaled` 0x72。两条同一天
落地、同一个版本进的方言，而它们到达的层不同，这一节按操作分开记。

**一、`alloca` 的字节是五个 varint，而其中一个是本仓第一个「无条件存在的 flags 字」。**
布局（`BytecodeGen.cpp` 的 `generateOpWriter` 顺序：结果、flags、属性、操作数、区域）：

```
alloca =: opcode[varint] resultTypeIndex[varint] flags[varint]
          num_elem[varint] alignment[varint]
```

`num_elem` 与 `alignment` 都是 `ConfinedAttr<I64Attr>`，走 `writeOpAttribute` 的
`std::is_integral_v` 那一支，也就是**裸内联 varint**，没有标签、没有类型下标、不是 zigzag，与
`cat` 的 `dim` 同形。`global` 是 `UnitAttr`，`generateAttributeSerialization` 跳过它，它只是
flags 的第 0 位。**这个 flags 字与 `mmaf` 的不同：`mmaf` 的 `fast_acc` 是 13.3 才加到一个
13.1 操作上的，所以它的 flags 字带版本判断；`alloca` 本身就是 13.3，它的唯一可选字段和它同岁，
`getVersionOrderedBitAssignments` 答的最小版本等于操作的版本，于是
`generateFlagsFieldSerialization` 无条件写。** 本仓因此没有 `alloca_has_flags()` 这样的谓词，
而 `mmaf_has_flags()` 是有的。`alloca` 一个操作数也没有，也没有任何变长的东西，所以流里没有任何计数。

**二、`alloca` 在 sm_86 上一次通过，层 2 也拿到了。** 这一条本来是风险（前研预期它像 fp8 一样
要新硬件），实测不是：`tileiras 13.3.36 --gpu-name sm_86` 直接接受，本机 3080 上三个 kernel
（`alloca_scratch` / `alloca_two` / `alloca_ctl`）与宿主参考**逐位相同**。语料的形状是
「让内存自己答话」：这棵树上此前每一个指针要么来自宿主上传的缓冲区（`ptrs`），要么来自模块
声明的全局（`get_global`），而一次 alloca 的地址**宿主永远看不见**，所以判词只能是
「kernel 的答案取决于它读回了什么」。`alloca_scratch` 把 `x + x` 存进去、在同一次 launch 里
读回来再加一次输入，答 `3 * x`；一块读回零的暂存会答 `x`。

**三、两次 alloca 是两块内存，这是量出来的。** `alloca_two` 在一个块里分配两次，往第一块写
`x`、往第二块写 `-x - 1`，答两者之差 `2 * x + 1`；两块**如果同址**，第二次写会盖掉第一次，
于是每一条 lane 都答 0。`scripts/tile-gpu-diff/run.sh` 的 `alloca-aliased` 就是这句话的机器
形态：记录 handler 把第一次之后的每一次 `alloca` 都答成第一次的句柄（一个把这条操作当纯函数
做公共子表达式消除的编译器会这么干），字节动、`tileiras` 照收（一块内存上开两个指针是合法
程序），设备上 `alloca_two` 全 0 而 `alloca_scratch`（只分配一次）与 `alloca_ctl`（不分配）
一字不动。语料的 `unaliased=128` 是这条变异体成立的前提：`0.25 * k + 0.125` 在整数 `k` 上
永远不是 -0.5，所以 `2 * x + 1` 没有一条 lane 天然是 0。

**四、`global` 位到不了 cubin，与 `fast_acc` 同一个形状的一次测量。** 方言说这个位让地址
「可以被别的 tile thread 访问」，不带它则地址私有于当前 tile thread。一个只跟自己说话的
kernel 带不带它都算同一个东西，所以问题是这个位有没有到机器：`alloca_two` 的第二次分配带它、
第一次不带，把**两次都**设上之后 `.tilebc` 恰好动一个字节（偏移 56，0 变 1），而
`tileiras --gpu-name sm_86` 出的 cubin **逐字节不变**。一个到不了 cubin 的位不可能让设备答出
别的数，所以 `attrs.txt` 的 `unit.global` 封在层 1，豁免叫 `global-bit-not-in-the-cubin`，
与 T8 给 `fast_acc` 写的那一条同族、同证据形状。

**五、`alloca` 的生命期没有独立判词，这一格是空着的而不是绿的。** 方言说分配活到它所在的块
结束（`AllocaOp` 的散文：the lifetime of the allocation is limited to the block in which the
alloca resides）。要证否它，需要读一块已经结束的分配，而那是未定义行为，没有可比的答案，
与 §6.8 给 `nsw` / `nuw` / `nw` 写的是同一条论证。T7 的 `global` 恰好相反：静态全局的生命期
是**模块**的，所以两次 launch 就能观测，`module-reloaded-per-launch` 是那条变异体。两条
写在一起是因为它们看起来是同一类问题而判词的可得性正相反。

**六、按大小做的变异体一条也没有，理由是它们全是未定义行为。** 刀单预备了
`alloca-size-halved`。写出来会是这样：`num_elem` 减半，而 kernel 仍然写 128 个元素，于是越界。
越界的程序没有定义的答案，绿也不是证据、红也不是证据（裁决 1 点名的正是这一类）。
**能把「计数写错了」变成判词的不是设备而是方言的 verifier**，条件是那个数落在
`alignment` 的位置上：`alloca-alignment-as-num-elem` 把 `num_elem` 写进对齐槽，
`tileiras` 答 `'cuda_tile.alloca' op 'alignment' must be power of two`。这一句成立要
`ALLOCA_ELEMS` **不是** 2 的幂，所以 `kernels.dawn` 把它定成 192 而不是 128，并且在那儿写下
了理由。这是「语料是设计出来的」的又一个实例（第一个是 T5 的 `loop-break-condition-inverted`）。

**七、`mmaf_scaled` 只买到层 1，而这不是没做，是这台机器上做不到。**
`MmaFScaledOp_OperandTileType` 只有三个成员：`f8E4M3FN`、`f8E5M2`、`f4E2M1FN`，
scale 是 `f8E4M3FN` 或 `f8E8M0FNU`，累加器与结果**只能**是 f32。也就是说
**没有一个宽操作数的形态可以退回去**：`mmaf` 收到 f64，`mmaf_scaled` 一个宽格式都不收。
而 T3 已经量过 `tileiras` 在 sm_86 与 sm_89 上都拒 fp8。本刀又量了一遍，并且往上多问了一格：

| `--gpu-name` | `tileiras 13.3.36` 的原话 |
|--------------|---------------------------|
| sm_86 | `error: Incompatibility with architecture 'sm_86': unsupported type 'f8E4M3FN'` |
| sm_89 | `error: Incompatibility with architecture 'sm_89': unsupported type 'f8E4M3FN'` |
| sm_90 | `error: Incompatibility with architecture 'sm_90': unsupported type 'f8E8M0FNU'` |
| sm_100 | 接受，89720 字节 cubin，`FUNC GLOBAL mmaf_scaled_e4m3` |

**sm_90 那一行是新的**：Hopper 收 f8E4M3FN 而不收 f8E8M0FNU，所以块缩放这一族的门槛比
fp8 本身还高一代。`mmaf_scaled_e4m3` 因此走 `run.sh` 的 `kernel_arch()`（与三个 `dtype_*`
fp8 kernel 同一条路）按 sm_100 汇编，本机 RTX 3080 永远见不到它。台账 `features.txt` 给它
层 1，豁免用 `types.txt` 已经在用的那个名字 `architecture`。

**八、`mmaf_scaled` 不写 flags 字，而这一条要靠它的兄弟才说得清楚。** 它有五个操作数
（lhs、rhs、acc、lhs_scale、rhs_scale）、**零个属性**、零个可选字段，所以
`getVersionOrderedBitAssignments` 答空表、`generateFlagsFieldSerialization` 一个字节也不写；
没有变长的东西，也就没有计数。整条指令是
`opcode, resultTypeIndex, 五个操作数下标`。而它的兄弟 `mmaf` 从 13.3 起**是**写 flags 字的
（`fast_acc` 那一位）。一个照抄 `mmaf` 那一臂的写入器会多写一个字节，读者会把它当第一个
操作数、其后每一个都错一位。这就是变异体 `mmaf-scaled-writes-a-flags-word`，
`tileiras` 答 `operand index 91 out of bounds (size=77) for operand 2`。它与 T8 的
`mmaf-flags-unwritten` 是同一堵墙的两侧，而两侧指向的是**两个不同的操作**：一个必须写、
一个必须不写，只有把两条都钉住，「flags 字什么时候存在」才是一条规则而不是一次巧合。

**九、V 不是属性，是两个形状的商。** 方言的散文说每个 scale 元素缩放 K 方向上连续
`V` 个元素，但 `Ops.td` 里**没有** `V` 这个参数：`MmaFScaledOp::verify` 只要求
lhs_scale 与 lhs 的 M 维相等、rhs_scale 与 rhs 的 N 维相等、两个 scale 的 K 维彼此相等，
K 维本身可以任意小于 K。所以 `V = K / scale_K` 是**推出来的**，字节码里一个字也没有它。
本包的公开面 `mmaf_scaled` 收 `block` 并由它算两个 scale 的形状，记录 handler 拒绝
`block` 除不尽 K 的调用；这是「让调用者说 V」与「让调用者说两个形状」之间的选择，取前者是
因为除不尽在这一层是可以拒的，而形状不一致要到 `tileiras` 才拒。

**十、一条语言限制，撞上了才知道。** `t_mmaf_scaled` 最自然的签名有十一个参数
（两个格式、四个数、五个句柄）。它**编译通过**，运行时崩在
`java.lang.NoClassDefFoundError: dawn/rt/Fn12`：`selfhost/src/main.dawn` 只生成
`dawn/rt/Fn0` 到 `Fn9`，也就是写出来的函数值最多八个参数（证据包占一个），而一个效果操作
就是一个函数值。处置是把 `[m, k, n, block]` 并成一个 `List[Int]`，签名回到八个参数，
理由写在 `dev.dawn` 的声明上。**这是一个编译期应当拒绝而实际拖到运行期的形状**，作为具名
欠账记在 §8，已开 issue #87。


### 6.13 模块符号：宿主看得见什么（刀 TG 实测，结论与刀单预期相反）

刀 TG 是全覆盖战役收官后的第一笔尾款：T7 与 T8 都写过「`visibility.public` /
`visibility.private` / `unit.constant` 三行要到层 2，还差一条 `cuModuleGetGlobal` 的
FFI」。本刀把那条 FFI 加了，然后量出这三行**到不了层 2**，而且理由不是缺东西，是那句话
本身不成立。六条结论。

**一、FFI 加在效果面上，不加在程序里。** `std/gpu` 的 `Gpu` 效果多一条操作
`gpu_module_global(kernel, name, dtype)`，公开面是
`module_global[D: Dtype](d, kernel, name) -> Result[Tensor[D], ForeignError]`。它答的是一个
**普通的 `Tensor`**，只不过背后的存储是模块的：`upload` / `download` / `launch` 一个字都不用
新写，宿主于是能读一张没人上传过的表、改它、再 launch 一次看设备读到什么。真臂
`gpu_module_global_host` 是 `cuModuleGetGlobal_v2`（`_v2` 后缀是因为 size 出参是 `size_t`），
答一个两元素 `Array[Int]`（地址、字节数），这是运行时边界上两个后端都叫得出的形状；假臂按
模块声明的全局表答。**借来的句柄不可释放**：`free` 收下并什么都不做，因为内存是模块的、句柄是
这次安装的，同一个符号的第二次查找答的还是它。

**二、`symbol_visibility` 到达 cubin，而这是可查的。** `tileiras` 给 `private` 全局一个
**LOCAL** ELF binding，给 public 的一个 **GLOBAL** binding。新 kernel `global_syms` 一个模块
声明三个全局（`@shown` public、`@hidden` private、`@frozen` constant）并全读，
`scripts/tile-golden` 的 assemble 步因此多一句判词：三个符号各 1024 字节，`@shown` 与
`@frozen` GLOBAL、`@hidden` LOCAL。变异体 `visibility-private-written-as-public` 把写入器的
枚举钉死成 public，字节同长、`tileiras` 照收，而 `@hidden` 变成 GLOBAL binding，这一句就红。
**这是本仓第一条被 `tileiras` 接受的层 1 变异体**：其余每一条的判词都是「汇编器拒绝」，这一条
的判词是「汇编器写出来的 ELF 不一样」。台账上这两行的 `mutant:` 因此从
`global-visibility-omitted-at-13-3`（记录的**形状**）换成它（记录的**取值**）。

**三、`symbol_visibility` 到不了答案，而这是量出来的。** 方言写得很清楚：public 是
"accessible from host code"，private 是 "device-only access"（Ops.td 的 GlobalOp）。本机
（RTX 3080、驱动 616.56、`tileiras` 13.3.36、sm_86）**不是这样**：

- `cuModuleGetGlobal` 对 `@shown`、`@hidden`、`@frozen` **三个都答**，各 1024 字节，
  地址各不相同。
- 三个都能 `cuMemcpyDtoH` 读回来，读到的正是各自声明里的表，逐位相同。
- 三个都能 `cuMemcpyHtoD` 写进去，写完再读回来是写进去的值。
- 写完再 launch 一次，kernel 三段读到的全是宿主写的新表。
- 把 `@frozen` 改成 **`private constant`**（编译器最有理由把初始值折进代码的那一格）
  重新汇编，以上四条一条不变。

只有模块**没有声明**过的名字被拒，报文是驱动自己的 `CUDA_ERROR_NOT_FOUND`（500）。所以没有
任何设备答案取决于写的是 public 还是 private，层 2 的判据（「答案依赖于这个取值」）在这台机器上
无法满足。台账的豁免因此从 `no-module-symbol-ffi`（「没有 FFI 可问」）换成
`visibility-not-in-the-lookup`（「问过了，驱动不区分」）。**这一步是把一句推断换成一次测量，
不是把一格覆盖换成另一格**：旧豁免说的是「差一条 FFI」，那句话现在已知是错的。

**三之二、链接那一侧也问了，同样问不出来。** 可见性在 CUDA 里最可能真正生效的地方不是符号查询
而是**链接**：两个各自声明同名 public 全局的 cubin 链在一起应当撞名，两个 private 的不应当。
这本来会是一条 `cuda.<CUresult>@link` 形状的层 2 判词。本机答不了这个问题，而这也是量出来的：

- 造两个 kernel（`link_pub_a` / `link_pub_b`），各声明一个 public 的 `@shared_g`，初始值不同；
  private 与 constant 各一对同形。六个 `.tilebc` 由 `tileiras --gpu-name sm_86` 汇编通过。
- `cuLinkCreate_v2` 成功、`cuLinkAddData_v2(CU_JIT_INPUT_CUBIN)` 两个都收下，
  `cuLinkComplete` 答 **`CUDA_ERROR_NO_BINARY_FOR_GPU`（209）**，错误日志缓冲区是空的。
  三对（public / private / constant）报文一模一样。
- **一个输入也一样**：只加 `link_pub_a` 一个 cubin，`cuLinkComplete` 照答 209。
- **阳性对照有两个**。一，同一个 harness 喂一段 PTX（`CU_JIT_INPUT_PTX`）链接成功、
  `cuLinkComplete` 出 3240 字节的镜像、`cuModuleLoadData` 装得上、kernel 跑得起来，所以 harness
  是对的。二，用同一套工具链里的 `ptxas -arch=sm_86` 把那段 PTX 编成一个**普通 cubin** 再喂进去，
  照答 209，所以这不是 Tile IR 的毛病，是这台驱动对 cubin-only 链接的态度。
- `CU_JIT_TARGET` 设成 `CU_TARGET_COMPUTE_86` 与不设，答案相同。

所以链接侧没有判词可拿，理由与 `symbol_visibility` 无关。这一条与上一条合起来才是豁免
`visibility-not-in-the-lookup` 的全部依据：问过了两处，驱动两处都不区分。

**四、`constant` 连 cubin 都到不了。** 把写入器的 `constant` varint 钉死成 0，
`global_syms.tilebc` 同长、动一个字节，而 `tileiras --gpu-name sm_86` 出的 cubin **逐字节相同**，
与 T8 量 `fast_acc` 的形状一模一样。符号表也说同一件事：`@frozen` 与 `@shown` 一样落在
`.nv.global.init`、一样是 GLOBAL binding、一样 1024 字节，没有只读段。这条比较写成了门禁
（`scripts/tile-golden` 的 `constant-flag-as-mutable`）而不是一句注释，所以将来某个
`tileiras` 一旦改放位置，红的是门而不是这段文字。豁免叫 `constant-not-in-the-cubin`。

**五、层 2 这一族仍然有东西可拿，只是不是这三行。** `scripts/tile-gpu-diff/sym_diff.dawn`
是新族，它在设备上钉住的是 `global` 的**宿主契约**：符号查得到、大小对、初始值确实到了显存、
宿主按名字写进去的字节下一次 launch 读得到、没声明的名字被驱动拒。这是本目录里唯一一族其
判词不是「比一个缓冲区」的：这棵树上其它每一个字节都是程序自己 `cuMemcpyHtoD` 送进去的。
这一族里**没有**可见性的变异体，而这是有意的：写入器的枚举钉死成 public 之后设备答的每一格都不变，
所以那条变异体按构造必绿，而一条没有红集的绿不是证据（`docs/README.md` 那条常青教训）。它归
`scripts/tile-golden`，在那里它有红集（cubin 的 `@hidden` binding 从 LOCAL 变 GLOBAL，符号判词红）；
本族的头注把这件事具名记下来，免得下一个读者以为是漏了。

**六、假设备照着测量改，不照着方言改。** `with_gpu_fake_globals` 的全局表把**三个**都放进去，
`@hidden` 也在里面。写成「private 查不到」会让假设备比真设备更严，于是层 2 对拍会在一个本仓
自己编出来的差异上红。假设备是模型不是仿真器，它模的是量到的行为。它比真设备窄的一处是具名的：
它的存储是值不是字节，所以只答声明时用的那个格式，别的格式回 `gpu.bad_global_dtype`。

### 6.14 view 族的字节形状、`padding_value` 的位模式，与 sm_86 收不收（刀 T11 实测）

> **view 族已清零。** 这一节是它的第一刀，§6.15 是第二刀（动态维与两条形状查询），§6.16
> 是收官刀（步长视图、聚散视图与 `atomic_red_view_tko`）。九条操作码、四个类型标签与五个
> `PaddingValue` 全部实现且全在层 3，三张台账上再没有一行 `ruling 2`。

刀 T11 落地的是**第二套取址方式**：`make_tensor_view` 0x43 说一个张量在哪、按什么步长排；
`make_partition_view` 0x42 把它切成一格一格等大的 tile；`load_view_tko` 0x3E 与
`store_view_tko` 0x66 按**格子的下标**搬一个 tile。此前每个 kernel 都靠 `iota` / `muli` /
`addi` / `offset` 现搭一条指针梯子，现在剩下的只有「一维一个下标」，而 block id 本来就是。

**一、`tensor_view` 的记录是标签、元素类型下标，然后两个定宽数组。**

```
tensor_view =: tag(14)[varint] elementTypeIndex[varint]
               rank[varint] shape[int64 LE]*rank
               rank[varint] strides[int64 LE]*rank
```

`shape` 与 `strides` 都走 `writeLEVarSize(ArrayRef<int64_t>)`：计数一个 varint，然后**每个
元素八个原始小端字节**。不是 per-element varint，也不是 zigzag。`tile` 的形状用的是同一个
形状，本刀只是多了一个数组。动态维（方言印成 `?`）在线上是
`ShapedType::kDynamic` 也就是 INT64_MIN，字节 `00 00 00 00 00 00 00 80`，并且要在
`make_tensor_view` 上配一个操作数；本写入器只发静态维，动态那半归刀 T12。

**二、`partition_view` 的记录里有本仓第一个「类型的可选参数」，而它有两条路。**

```
partition_view(13.3) =: tag(15)[varint] optionalFlags[varint]
                        n[varint] tile_shape[int32 LE]*n
                        tensorViewTypeIndex[varint]
                        n[varint] dim_map[int32 LE]*n
                        [padding_value[varint]]
partition_view(13.2) =: tag(15)[varint]
                        n[varint] tile_shape[int32 LE]*n
                        tensorViewTypeIndex[varint]
                        n[varint] dim_map[int32 LE]*n
                        present[byte] [padding_value[varint]]
```

`tile_shape` 是 `DenseI32ArrayAttr`、`dim_map` 是 `ArrayRef<int32_t>`，两者在线上完全同形：
计数一个 varint，然后每个元素**四个**原始小端字节。`tensor_view` 是一个类型表下标。

差别全在 `padding_value` 上，而它是 `Types.td` 里 `PartitionViewType` 唯一的
`OptionalParameter`，所以它是位域的 **bit 0**。两条路不是「同一个字节换个地方」：13.3 起
位域 varint 挤在**标签和第一个参数之间**，参数位上一个字节都不写；13.2 及以下**根本没有
位域**，每个可选参数在自己的位置上带一个 `writeByte(present)`。`BytecodeTypeCodeGen.cpp`
的 `generateOptionalParamFlags` 最后一个分支就是这条判断（类型是 13.1、参数也是 13.1，
所以既不需要参数版本检查、类型本身又不是 13.3 之后进的，落到裸的
`config.bytecodeVersion >= kUnifiedBitfieldVersion`）。本仓钉 13.3，走位域；两条都写在
`bytecode.dawn` 里，`partition_view_has_bitfield()` 是那个比较，而变异体
`partition-view-padding-inline-flag-at-13-3` 就是「在 13.3 的文件里写 13.2 的形状」。它
**同长**，`tileiras` 拒得干脆：`error at offset 18: failed to read tile_shape data`,
因为读者把本该是位域的那个字节当成了 tile_shape 的计数。

**`dim_map` 在线上永远写全，哪怕它是恒等映射。** 方言的打印器在文本里省略恒等映射、解析器
再补回来，线上没有这条规矩：读者把计数当真。

**三、四条操作的记录，与「结果计数写不写」的那条规矩。**

```
make_tensor_view    =: 43 numResults(1) resultType base nShape[0] nStrides[0]
make_partition_view =: 42 resultType source
load_view_tko       =: 3E numResults(2) tileType tokenType flags ordering
                         view nIndex index* [token]
store_view_tko      =: 66 numResults(1) tokenType flags ordering
                         tile view nIndex index* [token]
```

`Operator::isVariadic()` 只要**任一**操作数或结果是 variadic 就为真，而
`generateSimpleResultSerialization` 在它为真时写结果计数。所以 `make_tensor_view` 明明只有
一个结果也要写那个 1（两个动态数组是 variadic 操作数），`make_partition_view` 什么都不
variadic 所以不写。这与 `extract` / `join_tokens` 是同一条规矩，T2 已经量过一次。

`make_tensor_view` 的两个 `0` 也不是填充：它带 `AttrSizedOperandSegments`，每个 variadic
组自带计数，静态形状就是两个空组。少写它们，读者会拿下一条指令的操作码当段长。

两条内存操作的 flags 位是 bit0 `memory_scope`、bit1 `optimization_hints`、bit2 `token`，
比指针载入低两位（后者还有 `mask` 与 `paddingValue` 两个可选操作数）。**view 没有 mask 也没有
pad 操作数**：越界读什么写在**类型**里，越界写由方言直接屏蔽。这是本族最省的一处，也是三个
kernel 能把 mask 与 pad tile 一起删掉的原因。

**四、sm_86 收 view 族，没有架构豁免。** 这件事没有任何文档门槛可查：`cuda-tile` 整棵树里
`sm_86` 这个串一次都没出现，Ops.td / Types.td / 校验器 / 写入器 / 测试全都不按架构收放
view 族，唯一的门是**字节码版本**（四条操作与两个类型都是 13.1）。所以只能发出去看。发了：
五个 kernel 在 `--gpu-name sm_86` 上全部一次通过，cubin 8448 到 13312 字节，`FUNC GLOBAL`
齐全。fp8 / fp4 那种 `Incompatibility with architecture` 在这里一次也没出现。

**五、五个 `PaddingValue` 在设备上的位模式，是量出来的。** 判词不能停在「它是个 NaN」：
`nan` 的载荷标准没有规定。所以 `view_padding` 是一个 **f32 kernel 跑在 i32 缓冲区上**
（`ptr_recast` 的老办法反过来用），宿主读回来的是位模式本身。2026-09-06 在本机 RTX 3080 上
实测，五个值各占一个输出缓冲区的第 100 到 127 lane：

| 值 | 枚举 | binary32 位模式 | 有符号 i32 |
|----|------|-----------------|------------|
| `zero` | 0 | `0x00000000` | 0 |
| `neg_zero` | 1 | `0x80000000` | -2147483648 |
| `nan` | 2 | `0x7FC00000` | 2143289344 |
| `pos_inf` | 3 | `0x7F800000` | 2139095040 |
| `neg_inf` | 4 | `0xFF800000` | -8388608 |

四个是 IEEE 754 binary32 的定义，`nan` 那一行不是：`0x7FC00000` 是载荷为零的 quiet NaN，
这是这台机器答的。`std/gpu.dawn` 的 `pad_bits` 把五个都钉成常量，别的设备答别的 NaN 就红在
那一行。

**六、一件做不到的事：步长为零的读没有 view 写法。** `TensorViewType::verify` 要求每一维的
extent 和 stride 都**严格为正**，而卷积核的权重读法恰恰是「每个 lane 读同一个 `w[t]`」，也就
是两轴步长都是 0。`view_conv2d` 因此是一个**混着的** kernel：九个 tap 走 view，权重那一读留
在指针梯子上。这不是偷懒，是方言的边界：view 是给**张量**用的，广播不是张量。

**七、四条设备级变异体各自的红集，也是量出来的而不是推的。**

| 变异体 | 红 | 绿（控制） |
|--------|----|-----------|
| `view-strides-swapped` | view_transpose / view_max_pool / view_conv2d | 两个一维 kernel（反转单元素列表是恒等）、transpose_tail |
| `partition-dim-map-reversed` | view_transpose / view_max_pool | **view_conv2d**、两个一维 kernel、transpose_tail |
| `padding-value-bit-cleared` | view_padding / view_pad_i32 | 三个几何 kernel、transpose_tail |
| `padding-enum-off-by-one` | view_padding | view_pad_i32、三个几何 kernel、transpose_tail |

`view_conv2d` 在第二行是**绿**的，而这正是变异体买来的读数而不是假设：它的下标空间是 3 乘 3，
把 kernel 里每一个 `dim_map` 都反转等于把两个 block id 一起换名，进去换一次出来再换一次，答案
不动。`view_max_pool` 的下标空间是 2 乘 1、`view_transpose` 的是 4 乘 2，换名都不抵消。这与
刀 9 的 `stride-row-major-swapped` 是同一条道理的第二次实例（刀 18 在 `conv3d` 上量到过它的
另一面）。

三个几何 kernel 在第三行也是绿的：它们越界的 lane 在 store 那一侧被同样地屏蔽掉了，一个从来
不落盘的 padding 值当然看不见。这不是变异体弱，这正是 `view_padding` 存在的理由。

**八、`padding-enum-off-by-one` 为什么绕开 `zero`。** 直觉的写法是 `(code + 1) % 5`，实测它
在 `view_pad_i32` 上被 `tileiras` **拒掉**（`zero` 变成 `neg_zero`，而特殊值只许配浮点元素
格式），而被拒的 cubin 根本到不了设备。所以那条旋转只在四个特殊值之间转，`zero` 留在原地：
「特殊值配整数」那句话由层 1 的 `padding-nan-on-integer-elements` 单独钉，报文是
`padding_value nan can only be used with floating point element types, got 'i32'`。**这条
校验在方言自己的测试树里一个用例都没有**（`grep` 那句报文，`test/` 里零命中），所以本仓这条
变异体是它两边唯一的看护。


### 6.15 动态维、两条形状查询，与「一个 cubin 两个张量」（刀 T12 实测）

刀 T11 把 view 族的静态一半落地：张量在哪、多大、怎么排，全写在**类型**里。刀 T12 落的是
另一半。方言允许一维的 extent（或 stride）不进类型：它印成 `?`，`make_tensor_view` 用一个
**操作数**把值带进来。于是一个 cubin 不再对应一个张量，而是对应一个**秩**。两条形状查询
`get_tensor_shape` 0x2F 与 `get_index_space_shape` 0x2D 是 kernel 把那些数读回来的办法。

**一、`?` 在线上是 `ShapedType::kDynamic`，也就是 INT64_MIN。**

`tensor_view` 的记录一个字节也没多：shape 与 strides 仍是「计数一个 varint，每个元素八个原始
小端字节」，动态那一维只是把那八个字节写成 `00 00 00 00 00 00 00 80`。这条值得单独记一句，
因为**最容易写错的不是形状而是数**：Dawn 的 `Int` 里没有 INT64_MIN 的字面量（`0 - 9223372036854775808`
的正半边先溢出），而顺手把 -1 移八次得到的是 `ff` 八遍，读者会把它当 extent −1，验证器再以
「维度必须严格为正」拒掉，**长度一模一样，报文却在另一件事上**。所以 `put_dim` 把那个位模式
直接拼出来，包内测试逐字节钉住它。

**二、操作数在指令里是两个变长组，形状组在前。**

```
make_tensor_view =: 43 numResults(1) resultType base
                    nShape[varint] shapeOperand*
                    nStrides[varint] strideOperand*
```

刀 T11 写的那两个 `0` 现在填上了。`MakeTensorViewOp::verify` 要求每个组的长度**恰好等于**类型里
对应位置的 `?` 个数，所以记录 handler 在这里多了两条判词（数不上就拒），而「每个操作数都是
rank-0 的整数 tile、且彼此同类型」那条要类型，落在 lowering 里：本仓的 `Idx` 就是 `tile<i32>`，
于是那条检查是一次相等而不是一遍扫描。

**三、两条查询的记录形状相同，而它们吃的类型不同。**

```
get_tensor_shape      =: 2F numResults(rank) resultType*rank src
get_index_space_shape =: 2D numResults(rank) resultType*rank src
```

`writeResultTypes` 是**逐结果**写类型下标的，所以一个秩为 2 的查询把同一个下标写**两遍**而不是
一遍。结果计数写是因为结果是 variadic（`generateSimpleResultSerialization`），flags 一个字节都不写
（两条操作都没有可选属性、没有可选操作数），操作数计数也不写（`src` 是唯一操作数且不 variadic）。

两条的区别全在**吃什么**上，而这正是它们互换时的层 1 判词：`get_tensor_shape` 的参数类型是
`CudaTile_TensorViewType`，`get_index_space_shape` 的是 `CudaTile_TileView`（partition / strided /
gather 三个，**不含 tensor view**）。所以把 0x2F 写成 0x2D 会被拒、反过来也会被拒，两条报文各不
相同，逐条记在下面第七节。

答什么也不同：`get_tensor_shape` 答张量自己的 extent，`get_index_space_shape` 答**格子的个数**，
也就是 `ceil(shape[dim_map[k]] / tile_shape[k])`，秩是 tile 的秩（`PartitionViewType::getViewIndexRank`
读的是 `getTileShape().size()`）。两者在本仓的秩相等，是因为 `verifyPartitionViewLike` 要求它们相等，
不是因为它们是一回事。

**四、一条查询发的是整条指令，绑的是其中一个结果。** 这与 `get_tile_block_id` 是同一条规矩：
`block_id(0)` 与 `block_id(1)` 各发一条三结果的指令，各绑一个。形状查询照抄，所以
`view_index_space` 的文本里有两条一模一样的 `get_index_space_shape`。这不是冗余的手滑，是本仓
对多结果操作的既有写法，`assume` 之外每一处都这样。

**五、「动态」这件事的判词不是字节，是同一个 cubin 跑两个张量。**

`dyn_diff` 的用例单位因此不是 kernel 而是 **(kernel, 形状)**：三个动态 kernel 各跑两个形状，
`view_transpose` 第七个跑一次，一共七个用例、五种张量形状。一个把 extent 烘进类型的写法答不出
其中的第二个，而这句话正是层 2 要买的读数。2026-09-06 在本机 RTX 3080 上七个用例全部
`identical:exact`。

其中最值钱的一格是 `twin=same`：`view_dyn_transpose` 与 `view_transpose` 是**同一个算子的两种
拼法**，共用 `transpose_ref` 与同一份语料，而 `dyn_diff` 在同一个进程里把两个 cubin 的输出缓冲区
逐 lane 比了一遍。两份都对参考实现绿只说明参考实现被写对了两次；两个 cubin 互相逐位相同才是
这一族的判词，与刀 T15 的 `agree=3/3` 是同一种形状。

**六、语料里那个 `1` 是设计出来的。** 维度缓冲区是 `[rows, cols, 1]`，第三项从不被 kernel 写成常量，
于是**最内层的 stride 也是操作数**，两个变长组因此都是二长。这不是凑数：如果一个 kernel 有两个
动态 extent 和一个动态 stride，两个组长度不等，「把两个组对调」的变异体就会先被 `tileiras` 以
「dynamic shape operands 数目不符」拒掉，那是层 1 的报文，而它要量的是设备。同一个道理让
`masked` 与 `padded` 两个计数被钉在零以上：前者是 `view_tensor_shape` 的 grid 盖到、mask 排除掉的
lane 数（4），后者是 `view_index_space` 的格子落在张量外的 lane 数（816）。任一为零，那条被查询
决定的边界就什么也没决定。

**七、变异体的红集也是量出来的。**

| 变异体 | 层 | 红 | 绿（控制） |
|--------|----|----|-----------|
| `dynamic-dim-written-static` | 1 | `view_dyn_transpose`（`tileiras` 拒） | 静态 view 的五个 kernel 一个字节不动 |
| `tensor-shape-as-index-space-shape` | 1 | `view_tensor_shape`（`tileiras` 拒） | 同上 |
| `index-space-shape-as-tensor-shape` | 1 | `view_index_space`（`tileiras` 拒） | 同上 |
| `dynamic-shape-and-stride-operands-swapped` | 2 | 三个动态 kernel 的全部六个用例 | `view_transpose`（没有操作数可换） |
| `shape-query-dim-reversed` | 2 | `view_tensor_shape` 与 `view_index_space` 的四个用例 | **`view_dyn_transpose`**（不问任何查询，字节一动不动）与 `view_transpose` |

`shape-query-dim-reversed` 的锚点在 `lower.dawn` 而不在写入器里，这是本台账第三处写下来的判断
（前两处是 `grid-y-ignored` 与 `erf-sign-not-flipped`，都记在 `features.txt` 的头注里）：它换的是
**kernel 读这条操作的哪一个结果**，也就是「第 k 个结果是第 k 维」这句话本身，而那是这条操作码的
语义合同而不是别的什么。`view_dyn_transpose` 在这一行是绿的，并且是**字节级**的绿：它一条查询也
不发，所以变异体连它的 `.tilebc` 都碰不到。


### 6.16 步长视图、聚散视图与 `atomic_red_view_tko`（刀 T13 实测，view 族清零）

刀 T11 落的是**网格视图**：一个张量切成一格一格等大的 tile，一个下标一个 tile 维。刀 T12 落的是
它的动态一半。刀 T13 落的是网格说不出来的那三样，view 族至此清零：九条操作码、四个类型标签、
五个 `PaddingValue` 全部实现且全在层 3，`features.txt` 与 `types.txt` 上再没有一行
`deferred` 或 `unimplemented`。

**一、两个类型的记录，与「统一位域」第一次不是版本分支。**

```
strided_view(13.3) =: tag(21)[varint] optionalFlags[varint]
                      n[varint] tile_shape[int32 LE]*n
                      n[varint] traversal_strides[int32 LE]*n
                      tensorViewTypeIndex[varint]
                      n[varint] dim_map[int32 LE]*n
                      [padding_value[varint]]

gather_scatter_view(13.3) =: tag(20)[varint] optionalFlags[varint]
                             n[varint] tile_shape[int32 LE]*n
                             tensorViewTypeIndex[varint]
                             sparse_dim[varint]
                             [padding_value[varint]]
```

`traversal_strides` 是第二个 `DenseI32ArrayAttr`，和 `tile_shape` 逐字段同形；`sparse_dim` 是
一个 `uint32_t`，走 tblgen 的标量模板，**线上就是一个裸 varint**，没有计数也没有标签。

值钱的一句在位域上。刀 T11 记过 `partition_view` 的位域有两条路（13.3 位域、13.2 参数位上一个
present 字节），而那是因为它**在 13.1 就有了**：`generateOptionalParamFlags` 对一个早于 13.3
的类型要包一层 `config.bytecodeVersion >= kUnifiedBitfieldVersion`。这两个类型**是 13.3 才有的**，
`isUnifiedBitfieldVersion(type.sinceVersion)` 为真，于是生成的写入器落到那个**没有任何版本检查**
的分支：位域 varint 无条件写。所以本仓这两个类型只有一种拼法，而 `partition_view` 有两种，
这是同一条规则的两面。

**二、`atomic_red_view_tko` 的记录，与「答不出东西的内存操作」。**

```
atomic_red_view_tko =: 75 numResults(1) tokenType flags
                       ordering scope mode
                       view nIndex index* value [token]
```

结果计数写，是因为 `index` 是 variadic（`Operator::isVariadic()` 任一即真，`make_tensor_view`
是同一条规矩）。flags 只有一位，而且是 **bit 0**：这条操作的 `memory_scope` 是**必填实参**而不是
`OptionalAttr`（原子族的规矩，不是 load 的），`optimization_hints` 它根本没有，所以唯一的可选字段
是那个 token 操作数，位次比 `load_view_tko` 的低两位。三个必填属性按声明顺序内联在操作数之前，
操作数则按声明顺序去掉属性：view（无计数）、下标（有计数）、value、token。

它是这棵树上第一个**什么都不答的内存操作**：`atomic_rmw_tko` 答旧值和 token，这条只答 token。
这正是八个 tile block 能往同一格里归约而互相之间没有顺序的原因。

方言把两个枚举域**收窄**了，这是本仓第一次遇到 `OnlyVariants`：内存序只收 `relaxed`（写入器因此
把它写死），内存范围只收 `tl_blk` 与 `device`，模式收九种、`xchg` 被点名拒绝
（`AtomicRedViewTkoOp::verify`）。`bytecode.dawn` 的 `red_mode_value` 就是最后那一条：一个不答
旧值的归约没有东西可以拿去交换。

**三、聚散视图是这棵树上第一个「下标不同型」的操作。**

`GatherScatterViewType::verifyIndices` 要求 `sparse_dim` 那一位的下标是**一维 tile**，长度等于
tile 在那一维的宽度，其余各位仍是 rank-0 的标量。于是 `printIndexTypes` 的 splat 分支第一次
不成立，`load_view_tko` 的那一行印出**两个**下标类型而不是一个：

```
%22, %23 = load_view_tko weak %18[%14, %1] token=%15
  : gather_scatter_view<tile=(4x8), padding_value = pos_inf,
      tensor_view<16x6xf32, strides=[6, 1]>, sparse_dim=0>,
    tile<4xi32>, tile<i32> -> tile<4x8xf32>, token
```

`lower.dawn` 的 `view_index_tys` 是这条规则唯一的落点，`Instr` 的 `idx_ty: Ty` 因此改成
`idx_tys: List[Ty]`（一个视图的下标不再共用一个类型）。**方言的语义要靠设备来问**：一维那位是
张量的**行号**而不是 tile 下标，其余各位仍是 tile 下标。`cuda-tile` 树里
`gather_scatter_view` 只有两个用例（都在 `invalid.mlir` 里，都是拒绝用例），一个正例都没有，
所以这条读法是 `view_token_embed` 在本机 3080 上**量出来**的：它按这条读法与
`token_embed_ref`（指针梯子版 `token_embed` 在 gath_diff 里用的同一份参考）逐位一致。

**四、`sm_86` 收这三样，没有架构豁免，但 bf16 的 ADDF 是另一回事。**

五个新 kernel 在 `--gpu-name sm_86` 上**一次通过**，cubin 8448 到 12960 字节，`FUNC GLOBAL`
齐全。唯一一处有架构门的是 `atomic_red_view_tko` 的 `addf` 配 **bf16**：`Ops.td` 的散文写着
「bf16 is supported from Hopper (sm90) onward. On earlier architectures (e.g. Ampere/sm80),
atomicRMW ADDF with bf16 is not supported.」。这是 view 族里唯一一句提到架构的话，而且它在
**散文里**而不在校验器里。本机是 Ampere（RTX 3080，sm_86），所以 `view_atomic` 的 `addf`
用的是 f64；bf16 那一格是**具名豁免**，理由与三个 fp8 格式那条同类，写在 `attrs.txt` 的头注里。

**五、五个 kernel、六个用例，全部 `identical:exact`，三份参考是别处的。**

2026-09-07 在本机 RTX 3080 上：

| 用例 | 参考 | 它证明什么 |
|------|------|-----------|
| `view_conv1d` | `conv1d_ref`（stride_diff 的指针梯子版同一份） | 一个下标是一个**窗口**：traversal 1、tile 4，窗口三重叠 |
| `view_token_embed` | `token_embed_ref`（gath_diff 同一份） | 一次 load 收集运行期决定的八行 |
| `view_atomic` | `view_atomic_ref`，其中 `add` 那一格与 `histogram_ref` 对账 | 九种模式一次跑完，八个 block 往一格里归约 |
| `view_stride_pad` | `strided_pad_ref` | traversal 8、tile 4：网格**跳着走**，最后一格出界读 padding |
| `view_gather_pad` | `gather_pad_ref` | 聚散视图的 padding 在**列**那一侧：tile 八列宽、张量六列 |
| `conv1d` | `conv1d_ref` | 本族的 kernel 级控制：同一个卷积走指针梯子，三条新操作码一条也没有 |

语料的六个计数（`run.sh` 逐项钉在零以上）：`overlap=258`（`view_conv1d` 里被不止一个窗口读到的
元素）、`skipped=44`（`view_stride_pad` 的网格永远走不到的元素）、`padded=2` 与 `gpadded=32`
（两个 padded kernel 各自出界的 lane）、`repeats=43` 与 `grepeats=5`（被点名不止一次的行号）、
`cross=16`（被不止一个 block 命中的 bin）、`negative=2`（减掉 bias 之后为负的贡献）。
最后一个是 `umax` / `umin` 与 `max` / `min` 分家的全部理由：没有负数它们是同一个答案的两种拼法。

**`view_conv1d` 的语料是八分之一而不是十分之一，这一条是设计出来的。** 指针梯子版按参考实现
自己的顺序折四个 tap，这一版发的是一条 `reduce`，方言不规定它的折叠树。八分之一让每一个部分和
都精确，于是两种顺序答同一批位；十分之一不会。

**六、变异体的红集也是量出来的。**

<<MUTANTS>>

**七、一件顺手清掉的账：九种原子模式。**

`attrs.txt` 的 `rmw.*` 十行里，此前只有 `add` 与 `addf` 有客户，另外八行挂着 `no-client-kernel`。
`view_atomic` 一口气跑九种，于是七行从 `deferred` 到 `implemented` 且到层 3（`atomic-red-mode-rotated`
是它们共同的变异体）。剩下的一行是 `rmw.xchg`，而它留在那儿的理由变了：不是没有客户，是
**这条操作码不收它**。它是三张台账里最后一行 `deferred`。

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
| **T2 形状与指针转换**（已落地，特性覆盖的第二刀，§2.4） | 「Tile IR 的三个形状操作、grid 的范围、token 的合流与三条指针转换，各有一个 kernel 在本机 3080 上跑过，而且各有一条**改它自己写法**的变异体会红」（今天写不出：包里的 `permute` 是 stride 的排列而不是方言的 0x53，token 链是一条线不是一张图，grid 的范围没人读过，地址只是梯子的中间值而不是一个能算的数） | **八条新 opcode**（全 13.1）：`extract` 0x26 / `cat` 0x0C / `permute` 0x53 / `join_tokens` 0x3C / `get_num_tile_blocks` 0x2E / `int_to_ptr` 0x33 / `ptr_to_int` 0x56 / `ptr_to_ptr` 0x57。包：`dev` 加十三个效果操作、`I64` 与 `Ptrs[D]` 两个类型、十二个公开函数（`extract` / `cat` / `permute_tile` / `num_blocks` / `d_fork2` / `ptrs` / `ptr_offset` / `ptr_to_int` / `int_to_ptr` / `ptr_to_ptr` / `load_ptrs` / `i64_const` 与 `add_i64`），`prog` 加十一种 `TileOp` 与三个校验、`lower` 加八条 `Instr`、`render` 与 `bytecode` 各八行。`d_fork2` 是 `t_tok_get` / `t_tok_set` / `t_tok_join` 的唯一客户，它们是记录 handler 的排序单元被暴露出来的样子，与 `t_loop_begin` / `t_loop_end` 之于 `d_for` 同理。kernel：五个（`shape_ops` / `grid_stride` / `token_join` / `ptr_roundtrip` / `ptr_recast`）。宿主：`std/gpu` 五个参考实现加一个私有的 `f32_of_bits`（没有 bits-to-float 原语，按 `narrow.bf16_bits` 的反方向用精确算术拼）。层 2 新族 `scripts/tile-gpu-diff/shape_diff.dawn` | 层 0/1 五个新 golden，`FUNC GLOBAL` 五个，`tileiras` 全过；层 2 本机 3080 五个 kernel 全绿（**逐位 5、容差 0**）；台账八行从 `unimplemented` 改成 `implemented`，实现 70 → 78 条、未实现 19 → 11 条、层 3 从 19 条到 **27 条**，而且**八条全部到层 3**。刀 3…T1 的 128 个 golden 一字节没动 | **九条，分成两半，而分法本身是本刀最值钱的结论**（§6.2）：层 1 五条（`join-tokens-operand-count-wrong` / `cat-dim-swapped` / `int-to-ptr-as-ptr-to-int` / `ptr-to-int-as-int-to-ptr` / `ptr-to-ptr-as-bitcast`，各钉一句 `tileiras` 报文），层 2 四条（`permute-identity` / `cat-operands-swapped` / `extract-indices-reversed` / `num-tile-blocks-as-block-id`，红集逐条按名字钉死，每条只红它自己那一个 kernel）。判据是「这个字段说的是值还是类型」：`permute` 的 `permutation`、`cat` 的 `dim` 与三条指针转换的元素格式**都决定结果类型**，写错就是类型错、到不了设备，所以它们的层 3 证据只能长在层 1 上；四条设备变异体各自绕开了这条判据，`permute-identity` 靠的是 `shape_ops` 的 4x4x8 前两维相等 | 1.5（实报 1.5；`dawn test packages/tileir` 97 个测试全绿（本刀加九个）、`dawn test --stdlib` 152 全绿（加一个）、`dawn test selfhost` 595 全绿；`tile-golden` 不分片整跑三轮 1484 / 1000 / 984 s，空闲机器上四片 244.1 / 249.0 / 233.4 / 243.4 s，四条预算行全部上调到 628 / 638 / 607 / 627 s，`timeout-minutes` 32 / 32 / 31 / 32，pole 未动；`tile-gpu-diff` 多一个族与四条变异体。数字与两轮的负载见 §6.5） |
| **T3 其余标量类型**（已落地，覆盖刀里第一把零新操作码的） | 「Tile IR 的十五种标量类型里，这六种（`i16` `i64` `tf32` `f8E4M3FN` `f8E5M2` `f8E8M0FNU`）本仓写得出、`tileiras` 收得下，能上设备的三种在本机 3080 上逐位对得上；而 tf32 到底有没有存储形态、f8 到底要哪一代硬件、f8E8M0FNU 的 `ftof` 要哪个舍入模式，都是量出来的而不是抄散文抄来的」 | `packages/tileir`：`bytecode.dawn` 的 `num_tag` 三行 fp8 标签、`int_payload` 的 i16 臂、`ftof` 的舍入按**目标格式**查表（`ftof_rounding`，写入器唯一一处由目标格式决定属性字节的地方）；`render.dawn` 同一处；`prog.dawn` 的整数格式白名单加 i16 / i64；`dev.dawn` 的整数运算多一族**按宽度具名**的（`addi` `subi` `muli` `shli` `shri` `consti`，与 i32 那一族共用一个实现），`int_to_float` / `float_to_int` 补上源格式（12 处调用点，golden 逐字节未动，这也是它的判据）。`std/narrow`：`round_tf32` / `round_f8e5m2` / `round_f8e4m3fn` / `round_f8e8m0` 与五组位模式函数（含 f32 的，tf32 需要它），八个内联测试。`std/gpu`：六个标记与 `Dtype` 实现、`element_bytes` / `round_to` / `wrap_i16`、六对 `pack_*` / `unpack_*` 与 `pack_to` / `unpack_from` 的分发、四个参考实现。kernel 六个（`dtype_i16` `dtype_i64` `dtype_tf32` `dtype_e4m3` `dtype_e5m2` `dtype_e8m0`），新族 `scripts/tile-gpu-diff/dtype_diff.dawn`。第三本账 `scripts/tileir-features/types.txt`（23 行）与 `check.py` 的第二张表（一个解析器） | 层 0/1 六个新 golden；fp8 三个按 `--gpu-name sm_100` 汇编（sm_86 与 sm_89 都拒，见 §6.6）、其余按 sm_86；层 2 本机 3080 `dtype_i16` / `dtype_i64` / `dtype_tf32` 三个 `identical:exact`。台账 `types.txt` 实现 19 / 未实现 2 / 挂起 4；`features.txt` 一行未动（零新操作码，只有 `LANDED_KNIVES` 多了 `T3`） | 层 1 四条：`i16-tag-as-bf16`（同宽异族的标签）、`i64-payload-four-bytes`（常量 blob 写窄了，文件短一截）、`e4m3-tag-as-i8`、`e8m0-rounding-as-nearest-even` 与 `e8m0-tag-as-f8e5m2`（同一句话的两个方向）。层 2 一条：`tf32-tag-as-f32`，只红 `dtype_tf32` 而且只红它的第二段（第一段读缓冲区，一个 tf32 的字当 f32 读是同一个数），另外两个 kernel 是控制。`f8E5M2` 没有变异体，理由是量出来的：把它的标签换成 `f8E4M3FN` 的，`tileiras` 收下 | 1（实报 1；`tile-golden/run.sh` 不分片 **1084 s**（165 项），四片装不下（规划值 694 / 664 / 663 / 678 s 全部越过 660 s 的 pole），**分成第五片**，五片规划值 631 / 620 / 622 / 633 / 644 s；`tile-gpu-diff/run.sh` 本机 442 s，见 §6.5） |
| **T5 `loop` 与 `break`**（已落地，唯一缺的区域形状） | 「一个 kernel 可以循环到它自己算出来的条件为真为止：迭代轮数既不在字节码里、也不在录制里，而本机 3080 与一份独立写的宿主参考对得上，轮数本身也对得上」（今天写不出：`for` 的三个边界都是录制时就有的索引句柄，`d_for` 的体跑多少遍在记录的那一刻就定了） | **两条新 opcode**（都是 13.1）：`loop` 0x41 与 `break` 0x0A。包：`dev` 加 `t_while_begin` / `t_while_end` 两个效果操作与 `d_loop` / `d_loop2` 两个公开函数（外加 `s_consti` / `s_le_i` 两个 rank-0 整数原语），`prog` 加 `Loop` / `Break` 两种 `TileOp`、`WhileFrame` 一种区域帧与两条 handler 臂，`lower` 加 `WhileLoop` / `BreakVals` 两条 `Instr` 与 `lower_loop`（`yielded` 多认一种终结子：break 对它的 `if` 不 yield 任何东西），`render` 与 `bytecode` 各两行。kernel 四个：`loop_count`（Collatz 步数，118 轮）、`loop_bound`（同一个答案用 `d_for` 跑定长，family 的 kernel 级控制）、`loop_until`（牛顿开方，8 轮）、`loop_none`（条件在进入时就为真，零轮）。宿主：`std/gpu` 四个参考实现与三个私有辅助。新族 `scripts/tile-gpu-diff/loop_diff.dawn`；`run.sh` 加 `device`（`timeout`）兜底 | 层 0/1 四个新 golden，`FUNC GLOBAL` 四个，`tileiras` 一次通过；层 2 本机 3080 四个 kernel 全 `identical:exact`（逐位 4、容差 0），设备量出来的轮数 `loop_count=118 loop_until=8`。台账两行从 `unimplemented` 改成 `implemented`（实现 78 → **80**、未实现 11 → **9**；层 3 从 27 条到 **29 条**，两条都到层 3）。刀 3…T3 的既有 golden 一字节没动 | 层 1 两条：`loop-carried-not-rolled-back`（`loop` 那一臂的回滚被删，与 `for` 的 `roll_back` 是两个锚点；`tileiras` 答 `operand index 37 out of bounds (size=19) for operand 0`）与 `break-values-missing`（break 的操作数删光，`tileiras` 按**类型**拒：`op operand types must correspond to the parent loop result types`）。层 2 一条：`loop-break-condition-inverted`（handler 把出口 `if` 的两个分支对调），三个带循环的 kernel 全红、`loop_bound` 不动。**这一条是本目录里唯一一条可能把设备挂住的变异体**，所以三个 kernel 的语料都是「取反后更早停」而不是「永不停」，`loop_none` 的步长（1000 对阈值 1）就是为这件事选的 | 1（实报 1；`dawn test packages/tileir` 101 个测试全绿（本刀加四个）、`dawn test --stdlib` 163 全绿（加一个）、`dawn test selfhost` 595 全绿；`tile-golden/run.sh` 不分片 **1278 s**（171 项），五片装不下（规划值 726 / 685 / 691 / 713 / 718 s 全部越过 660 s 的 pole），**分成第六片**，六片规划值 641 / 633 / 640 / 600 / 598 / 622 s；`tile-gpu-diff/run.sh` 本机 496 s，见 §6.5） |
| **T4 属性域的其余取值**（已落地，覆盖刀里第二把零新操作码的） | 「Tile IR 的六个属性枚举与三个单位属性里，本仓从没写过的取值全部写得出、`tileiras` 收得下，而且每一个在本机 3080 上都问过一遍：定向舍入答的是不是格式自己的答案、`flush_to_zero` 到底冲不冲输入、`unordered` 与 `propagate_nan` 是不是方言散文说的那样、无符号循环边界比较跑几次」（今天写不出：写入器把 `rounding<nearest_even>`、`overflow<none>`、`ordered`、`relaxed device` 与「没有一个单位属性置位」写成了常量，别的取值一个都发不出去） | **零新 opcode**。`bytecode.dawn`：十四个新常量（三种舍入、三种溢出、`unordered`、三个内存序、两个内存范围、三个标志位），`float_op` / `int_op` / `predicate_value` 收下带后缀的名字，`float_op_rounds` 换成 `float_rounding`，新增 `float_flags` / `cmp_ordering` / `rmw_attrs`，`ForLoop` 的 flags 由 `unsigned` 决定。`render.dawn`：`float_spelling` / `float_units` / `int_overflow` / `cmp_ordering` / `rmw_memory` / `rmw_spelling` 六张拼写表。`prog.dawn` / `lower.dawn`：`For` 与 `ForLoop` 多一个 `unsigned` 字段，四张名字白名单加长，`cmpi` 的谓词与 `cmpf` 的分开（整数没有 `comparison_ordering`）。`dev.dawn`：十九个公开函数（`addf_down` / `addf_up` / `mul_down` / `mul_up` / `div_down` / `div_up` / `addf_ftz` / `mul_ftz` / `maxf_nan` / `minf_nan` / `sqrt_approx` / 六个 `*_u` 比较 / `add_i_nsw` / `sub_i_nuw` / `mul_i_nw` / `d_for_unsigned`）。`std/narrow`：`round_binary_toward` 与 `round_f32_toward`（三种定向舍入，溢出这一格与 `round_binary` 不同：往符号那侧是无穷、另一侧是最大有限值），一个内联测试。`std/gpu`：`f32_flush` 与八个参考实现，一个测试。kernel 八个（`attr_round` / `attr_nan` / `attr_ftz` / `attr_approx` / `attr_overflow` / `attr_memsem` / `attr_addf` / `attr_ucmp`），新族 `scripts/tile-gpu-diff/attr_diff.dawn`。第四本账 `scripts/tileir-features/attrs.txt`（44 行）与 `check.py` 的第三张表 | 层 0/1 八个新 golden，`FUNC GLOBAL` 八个，`tileiras` 一次通过；层 2 本机 3080 八个 kernel 全绿（**逐位 7、容差 1**）。台账 `attrs.txt` 实现 26 / 挂起 13 / 未实现 5，层 3 有 13 条、层 2 有 5 条、层 1 有 8 条（八条全是具名豁免）。逐条实测见 §6.8：`add=512 mul=445 div=494`（定向舍入分开的车道）、`ordering=768 maxf=128 minf=128`、`add=256 mul=256`（FTZ，**预研说没有判词，实测有**）、`lanes=81 distance=1.1914e-7`（approx 与正确舍入差一个 f32 ulp）、`signed=0 unsigned=32` | **九条，分成两半**：层 1 三条在 `scripts/tile-golden/run.sh`（`overflow-attr-not-written` / `atomic-memory-attrs-swapped` / `rmw-addf-as-add`，各钉一句 `tileiras` 报文），层 2 六条在 `scripts/tile-gpu-diff/run.sh`（`directed-rounding-as-nearest-even` / `ftz-bit-dropped` / `propagate-nan-bit-dropped` / `cmpf-always-ordered` / `for-unsigned-bit-dropped` / `sqrt-approx-as-nearest-even`，红集逐条按名字钉死，每条只红它自己那一个 kernel）。分法与刀 T2 不同：这里不是「值还是类型」，而是**这个取值改了之后还是不是一个合法程序**。溢出与内存序改了之后仍然合法、设备答同一个数，所以它们只能在层 1 红（把属性整个不写、把序与范围对调）；舍入、NaN、FTZ、`unsignedCmp` 改了之后设备答另一个数。`sqrt-approx-as-nearest-even` 是唯一一条**判词抓不到**的：verdict 照样是 `close:tolerance`，红的是 `probe` 那个计数掉到零，而 `run.sh` 把它钉在零以上。另有两条既有变异体的锚点被这一刀改坏、当场报「anchor is not unique（0 matches）」并搬了家（`addf-no-rounding` 与 `atomic-rmw-claims-weak-ordering`） | 1.5（实报 1.5；`dawn test packages/tileir` 101 全绿、`dawn test --stdlib` 165 全绿、`dawn test selfhost` 全绿；`tile-golden` 不分片整跑 182 项 1265 s（安静机器），六片装不下（按刀 T5 的单项均值第二片规划值 685 s，越过 660 s 的 pole；按本刀这轮安静读数六片是 618 / 644 / 612 / 610 / 617 / 611 s，还进得来，**两个模型第一次给出相反答案**，按「预算是上限」取差的那个），**分成第七片**，七条预算行 578 / 578 / 578 / 578 / 606 / 606 / 606 s，`timeout-minutes` 29 / 29 / 29 / 29 / 31 / 31 / 31，pole 未动，见 §6.5） |
| **T6 `assert` `assume` `print_tko`**（已落地，两种新判词形状） | 「一次 launch 可以**按设计失败**，而宿主收到的是设备写进字节码 String 段的那句话；一次 launch 可以**按设计打印**，而它放在标准输出上的字节与宿主参考算出来的逐字节相同；一个不改答案的假设，设备照样给同一个答案」（今天写不出：这棵树上的每一条判词都是「缓冲区里的数与参考的数一样」，没有一条能说「这次不该成功」，也没有一条看得见缓冲区以外的字节） | **三条新 opcode**（全 13.1）：`assert` 0x05 / `assume` 0x06 / `print_tko` 0x55，与它们用到的四个属性标签 `String`(5) / `DivBy`(8) / `SameElements`(9) / `Bounded`(12)。包：`dev` 加 `AssumePred` 一种和类型与 `t_assert` / `t_assume` / `t_print` 三个效果操作，公开面 `d_assert` / `d_assume` / `assume_div_by` / `assume_same_elements` / `assume_in_range` / `d_print`（只收 rank-0 参数，理由见 §6.7 第 7 条），`prog` 加 `Assert` / `Assume` / `Print` 三种 `TileOp`、`check_assume` 与 `format_args`（把 PrintTkoOp 的 verifier 抄到记录时），`lower` 加 `AssertTile` / `AssumeTile` / `PrintTile`，`render` 加三行与一个字符串转义器，`bytecode` 加三条编码与 `assume_attr` / `emit_i64_array` / `emit_byte` / `emit_opt_signed`。kernel 六个：`assert_pass` 与 `assert_fail`（同一个 `assert_guard` 的两个极限，语料全在其下 / 全在其上）、`print_tile`、`assume_divby` / `assume_same` / `assume_bounded`（三个谓词各一个，也是本族的 kernel 级控制）。宿主：`std/gpu` 五个参考实现与两个公开的折叠（`print_tile_sum` / `print_tile_max`，判词要用它们算期望字节）。新族 `scripts/tile-gpu-diff/assert_diff.dawn`，**三个进程**：默认档、`--case fail`、`--case print` | 层 0/1 六个新 golden，`FUNC GLOBAL` 六个，`tileiras` 一次通过；层 2 本机 3080 默认档四个 kernel 全 `identical:exact`（逐位 4、容差 0），`assert_fail` 的 launch 按预期在 `cuCtxSynchronize` 上答 `CUDA_ERROR_LAUNCH_FAILED`（719）并在标准输出上留下 128 行带 lane 下标的消息，`print_tile` 的标准输出与宿主参考逐字节相同（`7072696e745f74696c652073756d3d38323536206d61783d3132380a`，即 `print_tile sum=8256 max=128`）。台账三行从 `unimplemented` 改成 `implemented`（实现 80 → **83**、未实现 9 → **6**；层 3 从 29 条到 **31 条**，`assert` 与 `print_tko` 到层 3，`assume` 按裁决 1 停在层 2 并具名豁免）。刀 3…T5 的既有 golden 一字节没动 | 层 1 **五条**，每条钉一句 `tileiras` 的原话：`assert-message-tagged`（补一个标签 5 → `failed to parse attribute 'message'`，这条钉的是「标签根本不写」）、`print-tko-token-unwritten`（flags 说带 token、操作数不写 → `operand index 91 out of bounds (size=19) for token segment, element 0`）、以及三个谓词各一条载荷变异体（`assume-divby-tag-as-same-elements` / `assume-same-elements-payload-four-bytes` / `assume-bounded-bounds-swapped`），**三条都被拒，没有一条是层 1 盲的**。层 2 **两条**：`assert-condition-inverted`（kernel 源变异体，`assert_guard` 的 `lt_i` 换 `ge_i`）→ **两个方向都在红集里**，本来通过的 `assert_pass` 现在失败、本来失败的 `assert_fail` 现在通过，三个 `assume` kernel 与 `print_tile` 层 0 一字节不动；`print-format-wrong`（包把 `d_print` 的操作数反过来交）→ **缓冲区一个字节没变、程序自己的判词仍是 `pass`**，动的只有标准输出那一行，这是本目录里唯一一条任何缓冲区比对都看不见的变异体。**另有一件不加 kernel 也不加变异体的**：刀 T4 的 `attr_ftz` 语料两种车道的结果都是次正规，冲结果一项就能解释全部差异（实测：只去掉宿主参考的两处**操作数**冲零，八个 attribute kernel 全绿），本刀给它补第三种车道（`2^-126 + k·2^-149`，和是正规数），新 probe 字段 `attr_ftz:normal_sum` 由 run.sh 钉在零以上，见 §6.8 | 1（实报 1；`dawn test packages/tileir` 106 个测试全绿（本刀加五个）、`dawn test --stdlib` 166 全绿（加一个）、`dawn test selfhost` 595 全绿；rebase 到 T4 之后矩阵 193 项，`tile-golden` 不分片 **1388.4 s**，七片装不下（按刀 T5 的单项均值最重那片 654 s，离 660 s 的 pole 只剩 6 s，而推到那儿的正是本刀这十一个项），**分成第八片**，八条预算行 596 / 558 / 558 / 558 / 558 / 585 / 585 / 585 s，`timeout-minutes` 30 / 28 / 28 / 28 / 28 / 30 / 30 / 30，pole 未动；第一片真跑 196.4 s；`tile-gpu-diff/run.sh` 本机 **708.7 s**，见 §6.5） |
| **T7 静态全局**（已落地，覆盖刀里第一把加**段**的） | 「一个 kernel 读得到模块自己声明的一张表，那张表没有人上传过；而一个可写的静态全局在同一个模块的两次 launch 之间保住了值，本机 3080 与一份独立写的宿主参考逐位对得上」（今天写不出：这棵树上每一个字节都是 `cuMemcpyHtoD` 送进去的，`Tensor` 是唯一的设备存储，而 launch 之间设备上留下什么，从来没有被问过） | **两条新 opcode**（都是 13.1）：`get_global` 0x2C 与 `global` 0x31，加 **Global 段（id 6）**。`global` 不进指令流，写入器把模块的 GlobalOp 单独收集成一段（`writeGlobalSection`），所以台账给它 `structural`。包：`dev` 加 `t_global` / `t_get_global` / `t_store_ptrs` 三个效果操作与 `d_global` / `d_global_aligned` / `global_ptrs` / `store_ptrs` 四个公开函数（`store_ptrs` 是 T2 的 `load_ptrs` 欠的另一半，零新 opcode），`prog` 加 `Global` 记录、`TileProg.globals` 与 `GetGlobal` / `StoreAt` 两种 `TileOp`，`lower` 加 `GetGlobalPtr` 一条 `Instr`（结果是 rank-0 的 `tile<ptr<T>>`，展开走 `MakePtrs` 用的同一对 reshape + broadcast），`render` 加模块级的 `global` 行，`bytecode` 加 `OP_GET_GLOBAL` / `SEC_GLOBAL` / `global_payload` / `global_section`。kernel 三个：`global_table`（两个全局、两段输出，`@tbl_b` 另带 256 字节对齐）、`global_scratch`（一个可写全局，两次 launch）、`global_ctl`（同一个答案从两个缓冲区算，两条 opcode 都不含，是本族的 kernel 级控制）。宿主：`std/gpu` 五个新函数（两张表加三个参考实现）。新族 `scripts/tile-gpu-diff/global_diff.dawn`，它的 `stages` 多一个 `launches` 参数 | 层 0/1 三个新 golden，`FUNC GLOBAL` 三个，`tileiras` 一次通过；层 2 本机 3080 三个 kernel 全 `identical:exact`（逐位 3、容差 0），`global_scratch` 两次 launch 后输出是输入的两倍。台账 `features.txt` 两行：`get_global` 从 `unimplemented` 改成 `implemented`、`global` 改成 `structural`（实现 80 → **81**、结构性 2 → **3**、未实现 9 → **7**；层 3 从 29 条到 **31 条**，两条都到层 3）；`attrs.txt` 三行（`visibility.public` / `visibility.private` / `unit.constant`）的 knife 列从 T7 改判给 **T8**，具名豁免 `13.3-record-field`。刀 3…T4 的既有 golden 一字节没动 | 层 1 三条，全在 `global_table` 上（它声明两个全局，所以一条记录写错会把下一条读歪，这是语料的设计而不是巧合）：`global-record-alignment-dropped`（记录少写第四个 varint，`tileiras` 答 `number of globals (2) exceeds the maximum of 1 that can fit in the remaining payload of 6 bytes`）、`global-visibility-written-at-13-2`（把 13.3 才有的两个字段写进 13.2 的文件，答 `expect Cuda Tile integer or float type but got: '<<NULL TYPE>>'`；这条就是版本墙的实测）、`get-global-symbol-not-written`（`get_global` 不写它的字符串下标，答 `failed to read string for FlatSymbolRefAttr`，读到的下标 91 是 `reshape` 的 opcode）。层 2 三条：`global-initializer-reversed` 与 `get-global-wrong-symbol` 是包变异体，`tileiras` 都收下（一张表就是一张表，一个已声明的符号被点两次也是合法程序），只有设备说 `global_table` 答错，`global_ctl` 与 `global_scratch` 的字节和判词都不动；`module-reloaded-per-launch` 是 handler 变异体，**一个字节都不动**（字节码里没有一句话说模块活多久），只有 `global_scratch` 红。另有一条给验收者的自轴负控，**不用改包也不用改 golden**：把 `std/gpu.dawn` 的 `global_table_b` 那一行的 `0.0 - to_float(i * i) - 0.25` 改成 `+ 0.25`，别重录 golden，直接跑 `tile-gpu-diff`。`global_table` 的 cubin 里烧的还是旧表、宿主参考已经是新表，所以它红；`global_ctl` 把同一个函数**上传**进缓冲区、参考也用它，两边一起动，所以它绿；`global_scratch` 不碰这张表，也绿。红一个绿两个（**实测**，判词 `differ:result` / `identical:exact` / `identical:exact`），正是「设备读到的是声明进段里的字节，不是宿主此刻的想法」 | 1（实报 1；rebase 到 T6 之后 `dawn test packages/tileir` 113 个测试全绿（本刀加七个）、`dawn test --stdlib` 全绿、`dawn test selfhost` 全绿；`tile-golden/run.sh` 不分片 **1502 s**（199 项，160 kernel + 39 变异体），**八片不用加第九片**、八条预算行重述，最差一片距 660 s 的 pole 还剩 64 s；`tile-gpu-diff/run.sh` 本机 723 s，见 §6.5 与 §6.9） |
| **T8 版本墙 13.2 到 13.3**（已落地，覆盖刀里第四把零新操作码的，也是 T 序里唯一单独跑的一把） | 「本仓写的字节码是 13.3 的，而挪这一格**恰好**改了哪些字节、**没有**改哪些，是量出来的：162 个 kernel 的段长增量与从 `.mlir` 数出来的预测逐字相等，把写入器改回 13.2 能逐字节复现 T7 那一代的全部 golden，而 13.2 与 13.3 的 sm_86 cubin 162 个逐字节相同」（今天写不出：钉的是 13.2，13.3 才有的操作码一条也编不出来，而「升版要动哪些字节」只存在于预研的一句话里） | **零新 opcode**。`bytecode.dawn`：`BYTECODE_MINOR` 2 → 3，四个版本谓词（`exp_has_rounding` / `mmaf_has_flags` / `global_has_extended_fields`，与既有 `for_has_flags` 共用新的 `at_least`），`MMAF_FLAG_FAST_ACC` / `MMAF_FLAG_FAST_ACC_UNSET` / `VIS_PUBLIC` / `VIS_PRIVATE` 四个常量，`unary_rounding` 给 `exp` 加一臂，`FloatMma` 加 flags varint，`global_section` 的记录从四个 varint 长到六个。`prog.dawn`：`Global` 多 `is_private` / `constant` 两个字段。`dev.dawn`：`t_global` 多两个形参，公开面加 `d_global_private` / `d_global_const`。`render.dawn`：`global_line` 印 `private` 与 `constant`（`public` 按方言的打印器省略）。`toolchain.txt` 的 `bytecode` 行改 13.3 并改写它那句关于 Ampere / Ada 的注解。kernel 一个：`global_flags`（一个 private 全局加一个 constant 全局）。台账 `attrs.txt` 四行 `unit.fast_acc` / `unit.constant` / `visibility.public` / `visibility.private` 从 `unimplemented` 改成 `implemented`（实现 32 → **36**、层 1 从 14 条到 **18 条**），`rounding.full` 因 `exp` 现在内联写它而从层 2 升到层 3；豁免 `13.3-record-field` 换成 `no-module-symbol-ffi` 与 `fast-acc-not-in-the-cubin`，`check.py` 的 `LANDED_KNIVES` 加 `T8` | **全部 162 个 `.tilebc` golden 重录，`.mlir` 一个字节没动**（四处会变的形状没有一处出现在文本里）；`global_flags` 是第 163 个，`tileiras` 在 sm_86 上一次通过。三条独立测量见 §6.11：**账**（162 个 kernel 的 Func 段涨「`exp` 条数加 `mmaf` 条数」、Global 段涨「全局条数乘二」，总计 56 与 6 字节，与预测逐字相等，无一例外；109 个 kernel 只有第 10 个字节变了；159 个文件总长不变、3 个正好长 8 字节，那是对齐整整多了一步）、**复现**（写入器改回 13.2 之后 162 个 golden 与 `origin/main` 逐字节相同）与 **cubin**（13.2 与 13.3 的 162 个 cubin 逐字节相同，所以版本墙不改设备答案）。清单本身也是重新枚举的：`Ops.td` 每一条 13.3 参数加 `BytecodeWriter.cpp` 两处手写分支加 `BytecodeTypeCodeGen.cpp` 的类型统一位域，**六处里四处会动、两处对本仓恰好是空的**（Producer 段没有 `producer` 属性可写；统一位域只对带 `OptionalParameter` 的三个 view 类型生效，**T11 到 T13 解禁后它就不空了**，这条本刀第一次记；那三个是 `PartitionViewType` / `StridedViewType` / `GatherScatterViewType`，本行原写成 `TensorView` / `GatherScatterView` / `StridedView`，`TensorViewType` 零可选参数，刀 T11 改正） | 层 1 **四条**，三条是新写的、一条是把 T7 的翻过来：`exp-rounding-unwritten`（13.3 上 `exp` 不写 `rounding_mode` → `invalid integer value for enum type: 21` 加 `failed to parse attribute 'rounding_mode'`，21 是紧跟着的操作数下标）、`mmaf-flags-unwritten`（不写 flags varint → `block is expected to have a terminator operation, but the last operation 'cuda_tile.absf' is not a terminator.`）、`global-visibility-omitted-at-13-3`（13.3 上只写四个 varint → `number of globals (2) exceeds the maximum of 1 that can fit in the remaining payload of 9 bytes.`；T7 的 `global-visibility-written-at-13-2` 在 13.3 上成了合法写法，被本刀退役换成它）、`header-minor-still-2`（头写 13.2、正文写 13.3 形状 → `expect Cuda Tile integer or float type but got: '<<NULL TYPE>>'`，**与 T7 那条一模一样的报文**，因为读者正是拿头里的版本选 `kMinGlobalInfoSize`：所以「头的版本号约束读者」是量出来的而不是假定的）。T7 的 `global-record-alignment-dropped` 留着但**报文换了数字**（剩余载荷 6 字节变 10 字节），这是「判词是报文原文不是退出码」的又一个实例。层 2 **零条**：`fast_acc` 写 1 只动一个字节而 cubin 逐字节不变（四个 `mmaf` kernel 都试过，f16 的与 f64 的一样），一个到不了设备的位不可能让设备答出别的数，具名豁免 `fast-acc-not-in-the-cubin`；可见性与 `constant` 要 `cuModuleGetGlobal` 才有层 2 判词，本刀不扩 handler 面，具名豁免 `no-module-symbol-ffi`。另有一条给验收者的自轴负控：把 `std/gpu.dawn` 的 `global_table_b` 那一行的 `0.0 - to_float(i * i) - 0.25` 改成 `+ 0.25`，**别重录 golden**，`tile-golden` 上 `global_table` 与本刀新加的 `global_flags` 一起红（后者的 `@frozen` 取自同一个函数），而且红在**层 0 的文本 golden** 上而不是字节上，因为全局的初始值是印在 `.mlir` 里的；`global_ctl` 不声明全局，绿。`tile-gpu-diff` 上只有 `global_table` 红（`global_flags` 不在那份语料里）。实测三条判词：`FAIL: global_table: JVM text differs from global_table.mlir` / `FAIL: global_flags: JVM text differs from global_flags.mlir` / `global_ctl` 两条 golden 全 PASS | 1（实报 1；`dawn test packages/tileir` **115** 全绿（本刀加一个测试、给既有一个加了 `mmaf` 那几条断言），`dawn test --stdlib` 未动（**本刀一个 std 文件也没碰**，`gen-stdsrc` 跑完树是干净的）；矩阵 **209 项**，`tile-golden` 不分片 **1561.8 s**、209 项全跑退出 0，**八片仍装得下**（最重那片 644 s，距 660 s 的 pole 剩 16 s），四条预算行上调四条不动 644 / 606 / 633 / 633 / 633 / 633 / 633 / 633 s，`timeout-minutes` 33 / 31 / 32 / 32 / 32 / 32 / 32 / 32，pole 未动；**T15 写下的「下一把加变异体的刀必须分第九片」被推翻并原地改写**，理由是重分牌，见 §6.5） |
| **T15 `OptimizationHints`（属性标签 11 加 Dictionary 10）**（已落地，覆盖刀里第三把零新操作码的） | 「entry 与 load / store 都写得出方言的 `optimization_hints`，`tileiras` 收得下，而它到底是**建议**还是别的什么，是量出来的：本机 3080 上带 hint 的 kernel 与不带的那个逐字节答同一批数，而 cubin 的字节在 entry 上确实动了」（今天写不出：写入器一个 hint 也发不出去，`encode` 那一段写着「不写 entry 的 optimization_hints」，而 load / store 的 hint 位永远是 0） | **零新 opcode**。`dev.dawn`：`Hint` / `Hints` 两个别名、`for_arch` 与四个键构造子（`hint_num_cta_in_cga` / `hint_num_worker_warps_per_cta` / `hint_occupancy` / `hint_latency`）、`load_hinted` / `store_hinted`，`t_load` / `t_store` 各多一个 `hints` 形参。`prog.dawn`：`TileProg` 多一个 `hints` 字段，`trace_kernel` 拆成它与 `trace_kernel_hinted`，`Load` / `Store` 两个 `TileOp` 各多一个 `hints`。`lower.dawn`：`Kernel` 与 `LoadPtr` / `StorePtr` 同样多一个。`render.dawn`：`hints_attr` 一个拼写器（entry 与两个内存操作共用）。`bytecode.dawn`：`ATTR_DICTIONARY`(10) / `ATTR_OPTIMIZATION_HINTS`(11) / `FLAG_HAS_HINTS`(0x04) / `LOAD_FLAG_HINTS`(2) / `STORE_FLAG_HINTS`(2) 五个常量与 `put_hints` / `emit_hints` / `hints_flag`。kernel 两个（`hint_entry` / `hint_memory`，两个都是 vadd 的体），新族 `scripts/tile-gpu-diff/hint_diff.dawn`（**第一个把 `vadd` 当 kernel 级控制拉进自己进程的族**）。台账 `attrs.txt` 加 `tag.Dictionary` 与 `tag.OptimizationHints` 两行 | 层 0/1 两个新 golden，`FUNC GLOBAL` 两个，`tileiras` 一次通过；层 2 本机 3080 三个 kernel 全 `identical:exact`，`agree=3/3`（两个带 hint 的与不带的 `vadd` 逐字节同一批数）。台账 48 行长到 **50 行**，实现 30 → **32**、层 1 从 12 条到 **14 条**（层 2 与层 3 一条不动），两行都是具名豁免 `hints-do-not-change-answers`。刀 3…T6 的既有 golden 一字节没动。逐条实测见 §6.10：entry 带标签 11 而指令不带（判据是 ODS 类型是接口还是具体类型）、键是 String 段下标、hint 位是 load flags 的第 1 位、`default` 是真 fallback 且被 `sm_xx` 盖住、`sm_100` 的 hint 在 sm_86 上等于没写 | 层 1 **四条**，各钉一句 `tileiras` 的原话：`hint-dictionary-count-wrong`（内层计数 +1 → `failed to read key for DictionaryAttr element 1`）、`hint-tag-as-dictionary`（11 写成 10 → `invalid optimization hints attribute for function 'hint_entry'`）、`hint-flag-bit-misplaced`（hint 位写成 `memory_scope` 的第 0 位 → `operand index 91 out of bounds (size=19) for operand 1`）、`hint-entry-flag-dropped`（0x04 不置而属性照写 → `operand index 10 out of bounds (size=4) for operand 0`）。层 2 **零条，而且是按定义零条**：hint 不改答案，台账具名豁免。计划里的 `hint-key-unknown` **做不成**，这是本刀最该记的一条负结果：未知的键、未知的架构、越界的值，`tileiras` 三条全部**退出 0 且不打印**（`-Wunsupported-hints` 默认关），所以层 1 对 hint 的**内容**是盲的，只对**形状**不盲 | 1（实报 1；`dawn test packages/tileir` **114** 全绿（本刀加一个），`dawn test --stdlib` 未动（**本刀一个 std 文件也没碰**，`gen-stdsrc` 跑完树是干净的）；rebase 到刀 T7 之后矩阵 **205 项**，`tile-golden` 不分片 **1545.8 s**，**八片仍装得下**（按刀 T5 单项均值最重那片 633 s，距 660 s 的 pole 剩 27 s），六条预算行上调两条不动 606 / 606 / 633 / 633 / 633 / 596 / 596 / 596 s，`timeout-minutes` 31 / 31 / 32 / 32 / 32 / 30 / 30 / 30，pole 未动；见 §6.5） |
| **T9 亚字节 `i4` 与 `f4E2M1FN`，加 `pack` 0x6F 与 `unpack` 0x70**（已落地，覆盖刀里把标量类型表填满的那一把） | 「本机 3080 上跑得动一个四位整数的 kernel：字节 `unpack` 成半字节、widen、算、`trunc` 回四位、`pack` 回字节，每一条 lane 与一份独立写的宿主参考逐位相同；而**哪半个字节是第 k 条 lane**、**widen 带不带符号**，两条都是设备答出来的而不是抄来的」（今天写不出：写入器一个 `pack` 也发不出去，`num_tag` 十三个格式里没有这两个，而 `i4` 有没有指针类型、`f4E2M1FN` 在 sm_86 上收不收，只存在于预研的一句猜测里） | **两条新 opcode**（都是 13.3，字节码版本刀 T8 已经挪好，本刀不碰）。`bytecode.dawn`：`OP_PACK` / `OP_UNPACK` 两个常量，`cast_op` / `cast_attrs` 各加两臂（**零属性**），`num_tag` 加 `f4E2M1FN` 19 与 `i4` 22，另加 `extis`（`exti` 的 SIGNED 双生名，照 `shri` / `shru` 的老办法）。`prog.dawn`：`Repack` 一种 `TileOp`、`dtype_bits` 位宽表、`repack_shape` 与 `check_repack`（把 `verifyPackUnpackTypes` 的四条搬到记录时拒绝）。`lower.dawn`：`Repack` 降低成**既有的 `Cast` 指令**，`render.dawn` 与写入器因此**一个新臂也没加**，只多一个 `cast_spelling`（`extis` 印成 `exti`）。`dev.dawn`：效果操作 `t_repack`，公开面 `pack_bytes` / `unpack_bytes` / `ext_i4` / `ext_u4` / `trunc_i4`。`std/narrow`：`round_f4e2m1` / `f4e2m1_bits` / `f4e2m1_of_bits`。`std/gpu`：`I4` / `F4E2M1FN` 两个标记与 `Dtype` impl、`element_bits`、`wrap_i4`、`nibble_shift` / `nibble_at` / `nibble_into` / `nibble_word`（半字节布局的唯一一份说法）、`dtype_i4_ref` 与 `pack_roundtrip_ref`。kernel 三个：`dtype_i4`（五段）、`dtype_e2m1`（两段，sm_100）、`pack_roundtrip`（两段，i4 与 i16 两个方向）。语料并进最贴近的族 `dtype_diff`（三个 kernel 长到五个）。台账 `features.txt` 两行 `pack` / `unpack` 从 `unimplemented` 改成 `implemented`（与刀 T10 的两行合起来，实现 84 → **88**、**未实现归零**：100 条公开操作码里剩下的九条全是 view 族的 `deferred`；层 3 从 33 条到 **36 条**），`types.txt` 两行同样（实现 17 → **19**，**未实现同样归零**：十五种标量格式至此全部实现），`check.py` 的 `LANDED_KNIVES` 加 `T9`，而它最后一条 `unimplemented` 的自测锚点因为 T10 把最后两行也实现了，搬到 view 族的 `deferred` 行上（照 T10 自己那三条的做法） | 层 0/1 三个新 golden，`FUNC GLOBAL` 三个，`tileiras` 一次通过（`dtype_e2m1` 按 `--gpu-name sm_100`）；层 2 本机 3080 上 `dtype_i4` 与 `pack_roundtrip` 都是 `identical:exact`（逐位 5、容差 0），语料 4096 条半字节里 2048 条最高位为 1、十六种编码全覆盖、892 条加法回绕、2455 条乘法回绕。逐条实测见 §6.12，其中五条只有跑一遍才知道 | 层 1 **四条**：`i4-tag-as-i8`（i4 标签写成 i8 的 → 文件短四字节，`'cuda_tile.unpack' op expects source and result to have different element type widths`）、`e2m1-tag-as-i4`（fp4 标签写成 i4 的，同宽不同类 → `'cuda_tile.ftof' op operand #0 must be tile of ... values, but got '!cuda_tile.tile<128xi4>'`）、`unpack-as-pack`（0x70 写成 0x6F → `'cuda_tile.pack' op result #0 must be tile of i8 values, but got '!cuda_tile.tile<256xi4>'`）、`pack-result-shape-unhalved`（结果 lane 数不按位宽比例缩放 → `'cuda_tile.pack' op expects source and result to have the same size in bytes, but got source tile size 128 bytes and result tile size 32 bytes`；**这是本目录唯一一条文本与字节一起动的变异体**，因为 lane 数就是结果类型，两半都被检查）。层 2 **两条**：`exti-i4-zero-extends`（写入器把 `extis` 的 SIGNED 写成 UNSIGNED → 文本不动、`tileiras` 收下、文件同长，设备上 `dtype_i4` 从第 1 段起红，另外四个 kernel 全绿）、`pack-halves-swapped`（宿主的 `nibble_shift` 换半字节，**一致的重命名** → 四个逐 lane 相同的段全都仍然与设备相符，只有依赖 lane 下标的第 4 段红，`pack_roundtrip` 作为族内控制全绿）。另有一条给验收者的自轴负控：把 `std/gpu.dawn` 的 `dtype_i4_ref` 里 `} else if seg == 2 {` 那一臂的 `ua >>> 1` 改成 `sa >> 1`，**别重录 golden、别碰包**，直接跑 `tile-gpu-diff`：`dtype_i4` 红在第 2 段（它把两种 widen 的答案变成同一个），`pack_roundtrip` 与另外三个 dtype kernel 全绿。实测判词一个 `differ:result` 四个 `identical:exact`，红的那一句是 `first seg 2 lane 1: device 2.004318071E9 host -1.0` | 1（实报 1；rebase 到刀 T10 之后 `dawn test packages/tileir` **118** 全绿（本刀加一个），`dawn test --stdlib` **170** 全绿（本刀加四个）；**本刀碰了 `std/narrow.dawn` 与 `std/gpu.dawn`**，`scripts/gen-stdsrc.py` 已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录；矩阵 **224 项**（rebase 到 T10 的 217 项之上），`tile-golden` 不分片 **1812.4 s** 全跑退出 0，**十片仍装得下、十条预算行一条也没动**（最紧的 622 s，距 660 s 的 pole 剩 38 s）；rebase 之前的那一轮机器慢了四成半而 rebase 之后又回到常速，两轮都记在 §6.5） |
| **T10 13.3 其余：`alloca` 与 `mmaf_scaled`**（已落地，T 序里 view 族之外的最后一把新操作码刀） | 「一个 kernel 分配得到一块只属于自己的暂存，往里写、在同一次 launch 里读回来，本机 3080 与一份独立写的宿主参考逐位相同；同一个块里的两次分配是两块内存，而这句话有一条会红的变异体；而块缩放的矩阵乘写得出来、`tileiras` 收得下，它到底要哪一代硬件是量出来的而不是猜的」（今天写不出：这棵树上每一个指针要么来自宿主上传的缓冲区、要么来自模块声明的全局，没有一条指令能凭空要一块内存；`mmaf_scaled` 则一个字节也发不出去） | `bytecode.dawn`：`OP_ALLOCA`(0x71) / `OP_MMAF_SCALED`(0x72) / `ALLOCA_FLAG_GLOBAL` 三个常量与两条编码臂。`lower.dawn`：`AllocaPtr` 与 `FloatMmaScaled` 两条指令、两条降低臂（`alloca` 复用 `get_global` 的 `spread_rank0`）。`prog.dawn`：`Alloca` 与 `MmaFScaled` 两个 `TileOp`，记录 handler 拒绝非二的幂对齐、负元素数与除不尽 K 的块大小。`dev.dawn`：`t_alloca` / `t_mmaf_scaled` 两个效果操作与公开面 `alloca_ptrs` / `alloca_shared_ptrs` / `mmaf_scaled`。`render.dawn`：两条渲染臂。`std/gpu.dawn`：三个参考实现（**本刀唯一碰 std 的地方**）。kernel 四个（`alloca_scratch` / `alloca_two` / `alloca_ctl` / `mmaf_scaled_e4m3`），新族 `scripts/tile-gpu-diff/alloca_diff.dawn`。台账：`features.txt` 两行改 `implemented`（实现 84 → **86**），`attrs.txt` 的 `unit.global` 一行改 `implemented`（实现 36 → **37**），`check.py` 的 `LANDED_KNIVES` 加 `T10`，四条自测锚点从这三行搬到 view 族的 `deferred` 行上 | 层 0/1 四个新 golden，`tileiras` 一次通过：`alloca` 的三个在 **sm_86**（这是本刀的第一个反预期，前研以为它像 fp8 一样要新硬件），`mmaf_scaled_e4m3` 只在 **sm_100**。层 2 本机 3080 三个 kernel 全 `identical:exact`，语料的 `live=128 unaliased=128 apart=128` 三个计数被 `run.sh` 各自钉在 128。十条实测见 §6.12，其中四条值得单记：**`alloca` 的 flags 字无条件存在**（它的唯一可选字段和它同岁，所以没有 `alloca_has_flags()` 这样的谓词，而 `mmaf_has_flags()` 是有的）；**`global` 位到不了 cubin**（两次分配都设上只动 `.tilebc` 一个字节，sm_86 的 cubin 逐字节不变，与 T8 给 `fast_acc` 写的同族）；**sm_90 收 f8E4M3FN 而不收 f8E8M0FNU**，所以块缩放的门槛比 fp8 本身还高一代；**V 不是属性**，`Ops.td` 里没有这个参数，`V = K / scale_K` 是两个形状的商 | 层 1 **四条**：`alloca-flags-unwritten`（不写 flags → `failed to get result type 0 for BitcastOp`）、`alloca-alignment-as-num-elem`（把元素数写进对齐槽 → `'cuda_tile.alloca' op 'alignment' must be power of two`，这一句成立要 `ALLOCA_ELEMS` 不是二的幂，所以它定成 192 而不是 128，语料是为判词设计的）、`mmaf-scaled-scale-operand-missing`（少写第五个操作数 → `operand #4 must be mmaf_scaled scale tile type of f8E4M3FN or f8E8M0FNU values`）、`mmaf-scaled-writes-a-flags-word`（多写一个 flags 字 → `operand index 91 out of bounds (size=77) for operand 2`；它与 T8 的 `mmaf-flags-unwritten` 是同一堵墙的两侧，一个必须写、一个必须不写）。层 2 **一条**：`alloca-aliased`（记录 handler 把第一次之后的每一次 `alloca` 都答成第一次的句柄 → `alloca_two` 每条 lane 答 0，`alloca_scratch` 与 `alloca_ctl` 一字不动）。**按大小做的变异体一条也没有**，理由写在 §6.12 第六条：越界是未定义行为，绿红都不是证据。另有一条给验收者的自轴负控：把 `std/gpu.dawn` 的 `alloca_two_ref` 那一行的 `x[i] - round_to(...)` 改成 `x[i] + round_to(...)`，**别重录 golden**，`tile-gpu-diff` 上只有 `alloca_two` 红（`differ:result`），`alloca_scratch` 与 `alloca_ctl` 绿；`tile-golden` 全绿，因为参考实现不进任何 golden | 1（实报 1；`dawn test packages/tileir` **117** 全绿（本刀加两个），`dawn test --stdlib` **166** 未动（三个参考实现、零个新测试），但**本刀碰了 `std/gpu.dawn`**，所以 `scripts/gen-stdsrc.py` 与 Core golden 都重跑了：归一化哈希动了三个模块（`std.gpu`、`embed.stdsrc`、`compiler_plan.exitmem`，最后一个是 ADT id 位移），`prev-diff` 与 `run-diff` 全绿且十个 emit label 自 v0.76.0 起已声明；矩阵 **217 项**，`tile-golden` 不分片 **2076 s**（217 项全跑，退出 0），**八片九片都装不下、分到第十片**（最重那片 622 s，距 660 s 的 pole 剩 38 s），十条预算行全部重述 611 / 615 / 613 / 622 / 621 / 619 / 618 / 605 / 604 / 605 s，`timeout-minutes` 31 / 31 / 31 / 32 / 32 / 31 / 31 / 31 / 31 / 31，pole 未动；逼出这一步的是**本机变慢**而不是这一刀的内容，见 §6.5） |
| **21 两块 transformer**（已落地） | 「设备把两串**整块**的 launch 跑成两个程序：leetgpu 74 十二次、93 十七次，比此前最长的序列还长七次，而二十九次 launch 里有六次用的是既有 kernel。同时台账第一次承认一件事：一行可以录在比题目小的形状上，而那是宿主参考实现的限制，不是后端的」 | 包、假设备、真机 handler、运行时**一行没改**，`tileiras` 与字节码版本没动，**零新 opcode**（74 的 gelu 是 `tanh` 近似而不是刀 15 的 `erf`，`tanh` 从刀 7b 起就在包里）。kernel：十五个。`gpt_ln` / `gpt_qkv` / `gpt_scores` / `gpt_context` / `gpt_dense` / `gpt_fc` / `gpt_gelu` / `gpt_down`（74），`llama_rms` / `llama_qkv` / `llama_rope` / `llama_scores` / `llama_out` / `llama_ffn` / `llama_down`（93）。**复用的六处**：74 的第四次 launch 是刀 16 的 `attn_softmax`、第七与第十二次是第一个里程碑的 `vadd`（它的长度是 grid 不是录制，所以任何宽度的残差加都是它）；93 的第八次是 `attn_softmax`、第九次是刀 19 的 `gqa_context` 一字节没改（投影直接写成头优先的布局，正好是它录制时读的那个布局）、第十五次是刀 16 的 `swiglu_act`、第十一与第十七次是 `vadd`。一个 kernel 跑多次的也有三处：`gpt_ln` 两次、`llama_rms` 两次、`llama_qkv` **三次**（Q 四个头、K 与 V 各两个头，头数是 grid 给的，缓冲区的总宽度根本不进这个 kernel）、`llama_rope` 两次、`llama_ffn` 两次。宿主：`std/gpu` 九个参考实现加一个 `ref_tanh`；`linear_bias_ref` 一个供 74 的四次线性层用 | 层 0/1 十五个新 golden，`FUNC GLOBAL` 十五个，`tileiras` 一次通过；层 2 本机 3080 二十二条序列加对照全绿（**逐位 3、容差 20**），`gpt2` 的 miss 1.80e-9、`llama` 5.01e-8。leetgpu **74 / 93** 可解，累计 **85 / 97**。刀 7a…20 的 111 个 golden 一字节没动。**93 的 RoPE 不需要三角函数**：题目签名把 `cos` 与 `sin` 当输入缓冲区传进来（前研的怀疑反过来了，需要三角函数的是 **76**，它的角度在 solve 内部算，本刀因此不取它） | 层 1 **零条**（零新 opcode）。层 2 **零条新变异体**：负控是把两条序列塞进刀 16 那四条变异体，矩阵从 84 格长到 **92 格**、红集从 72 长到 **80**，两条新序列四条全红（grid 那条在这里红而在 `kv` / `ols` 上绿，因为它们的第二次 launch 把输出列块放在 grid 的第二根轴上）。另有一条**自轴负控**：把 `std/gpu.rope_ref` 的 cos 与 sin 对调，只有 `llama` 一条红（miss 5.01e-8 → 1.13e7）。顺手补一个门：`problems.txt` 表头的题数从刀 18 起就没人改过（83 行的表上写着 73），`check.py` 现在读它 |
| **TE 展柜 example**（已落地，T 序的收尾刀；不加特性、不上设备，层 `-`） | 「一个读者不必有 GPU、也不必读 4949 行 `scripts/tile-golden/kernels.dawn`，就能在一个文件里看到这轮 T1 到 T15 各自加了什么公开面，而且每一条都配一个跑得起来的断言」（今天写不出：`examples/projects/gpu_fake` 只有一个 vadd，T2 到 T15 的公开面在树上只出现在门禁脚本里） | `examples/projects/gpu_fake/src/main.dawn`（130 行长到 607 行，一个 kernel 长到九个：`shapes` T2、`narrowed` T3/T9、`interval` T4、`collatz` T5、`guarded` T6、`table` T7、`scratch` T10、`vadd_hinted` T15，`vadd` 留作刀 1 的原点；T1 三角、T8 版本墙、`mmaf_scaled` 只在注释里提一句）、`scripts/example-main-contract/registry.json` 重钉 stdout、本表与 `docs/README.md` 各一行 | `./scripts/example-tests.sh`（101 个 test 全绿，其中 example 自己 23 条（刀 TG 之后是 102 与 24））、`example-main-contract` 的 selftest 与 run、`dawn fmt --check`、`doc-check`。**层 `-`**：example 刀不进 `scripts/tile-golden`、不上设备，`.mlir` / `.tilebc` golden 一个字节没动；假设备的答案由 `std/gpu` 的参考实现给，测试断言的是手算出来的数 | 把 `std/gpu.global_table_a` 的 `+ 1.0` 改成 `+ 2.0`，example 的「T7: the answer is the two tables, plus ten」红且只有它红（101 个 test 里 1 红），改回即全绿 | 0.5（实报 0.5） |
| **TG 模块符号：`cuModuleGetGlobal`**（已落地，T 序收官后的第一笔尾款；**结论与刀单预期相反**） | 「宿主能按名字问一个模块要它自己声明的全局：查得到地址与大小、读得回声明的那张表、写得进去、写完再 launch 一次 kernel 读到的是宿主写的值；而模块没声明过的名字被驱动拒，报文是它自己的 `CUDA_ERROR_NOT_FOUND`」（今天写不出：`Gpu` 效果里没有任何操作能命名模块内部的东西，这棵树上每一个字节都是程序自己 `cuMemcpyHtoD` 送进去的） | 效果面：`Gpu` 加 `gpu_module_global`，公开面 `module_global[D: Dtype]` 答一个 `Tensor[D]`（借来的句柄，`free` 收下不做事），两臂同契约；`with_gpu_fake_globals` 是带模块全局表的假设备安装器，`with_gpu_fake` 委托给它。运行时：`gpu_module_global_host` 一条 intrinsic（`cuModuleGetGlobal_v2`，答两元素 `Array[Int]`），`builtins.dawn` / `types.dawn` / `rtclasses.dawn` / `dawn_rt.{h,c}` 各一处。kernel 一个：`global_syms`（一个模块三个全局：public / private / constant）。层 2 新族 `scripts/tile-gpu-diff/sym_diff.dawn`。`scripts/tile-golden` 的 assemble 步加一句 ELF 符号表判词。台账 `attrs.txt` 三行换 `mutant:` 与豁免，`check.py` 的 `LANDED_KNIVES` 加 `TG`。example `gpu_fake` 加一条 TG 展柜行与一条测试 | **本刀的验收是一次测量，而它推翻了刀单的假设**（§6.13）：本机 RTX 3080 / 驱动 616.56 / sm_86 上，`cuModuleGetGlobal` 对 `@shown`（public）、`@hidden`（private）、`@frozen`（constant）**三个都答**，各 1024 字节；三个都读得回声明的表、都写得进、写完 launch 三段读到的全是宿主写的新表；把 `@frozen` 改成 `private constant` 重新汇编，四条一条不变；只有没声明过的名字被拒（`cuda.CUDA_ERROR_NOT_FOUND`）。**链接那一侧也问了**：两个各声明同名 public 全局的 cubin 本应撞名、两个 private 的本不应，而 `cuLinkComplete` 对任何 cubin-only 链接都答 `CUDA_ERROR_NO_BINARY_FOR_GPU`（一个输入也一样，`ptxas` 出的普通 cubin 也一样，同一 harness 喂 PTX 链得通），所以那一侧也没有判词。于是三行**到不了层 2**，豁免从 `no-module-symbol-ffi`（「没有 FFI 可问」）换成 `visibility-not-in-the-lookup`（「问过了两处，驱动都不区分」）与 `constant-not-in-the-cubin`。层 1 反而变强了：`symbol_visibility` 确实到达 cubin（private 是 LOCAL binding、public 是 GLOBAL binding），`constant` 连 cubin 都不到（写 0 之后 sm_86 cubin 逐字节相同） | 层 1 一条新变异体 `visibility-private-written-as-public`（写入器的枚举钉死成 public → 字节同长、**`tileiras` 照收**，而 `@hidden` 变成 GLOBAL binding，`tile-golden` 的符号表判词红。这是本目录里唯一一条被汇编器接受的层 1 变异体）；一条新的**测量项** `constant-flag-as-mutable`（`constant` 钉死成 0 → 字节动一个、cubin 逐字节相同，这一条**绿才是断言**，将来 `tileiras` 换了放法它就红）；层 2 **一条也没有**，而这是决定不是遗漏：可见性的变异体在设备上按构造必绿，一条没有红集的绿不是证据，所以 `scripts/tile-gpu-diff` 的头注把它记成一条具名观测而不是一条变异体。另有一条给验收者的自轴负控：把 `std/gpu.dawn` 的 `global_syms_c` 那一行的 `- 40.0` 改成 `- 41.0`，**别重录 golden**，`tile-golden` 上只有 `global_syms` 红（层 0 的 `.mlir` 就红，全局初始值印在文本里），`global_table` / `global_ctl` / `global_scratch` / `global_flags` 全绿 | 0.5（实报 0.5；矩阵 209 项长到 **212 项**，`tile-golden` 八片，预算行按 ITEM_TIMES 重述；`dawn test --stdlib` **174** 全绿（本刀加四个测试），`gen-stdsrc` 跑完树干净） |

| **T11 view 族的静态一半**（已落地，裁决 2 撤销后的第一刀） | 「一个 kernel 不搭指针梯子也取得到全局内存：张量在哪、按什么步长排、切成多大的 tile 全写在**类型**里，而它算出来的答案与指针梯子版**共用同一份宿主参考**、在本机 3080 上逐位相同；越界的 lane 读什么是类型上的一个枚举，它在设备上留下的五种位模式是量出来的而不是查表抄的」（今天写不出：这棵树上每一个地址都是 `iota` / `muli` / `addi` / `offset` 现搭的一条梯子，view 族按裁决 2 一个字节也发不出去，`PaddingValue` 五行在台账上全是 `deferred`） | `bytecode.dawn`：`OP_MAKE_TENSOR_VIEW`(0x43) / `OP_MAKE_PARTITION_VIEW`(0x42) / `OP_LOAD_VIEW_TKO`(0x3E) / `OP_STORE_VIEW_TKO`(0x66) 四个操作码常量，`TAG_TENSOR_VIEW`(14) / `TAG_PARTITION_VIEW`(15) 两个类型标签，`PAD_ZERO` 到 `PAD_NEG_INF` 五个枚举值，`VIEW_FLAG_SCOPE / HINTS / TOKEN` 三个位，`partition_view_has_bitfield()` 与 `padding_code()`，`ty` 两条新臂（含 13.3 位域与 13.2 内联标志两条路）与 `encode_instr` 四条新臂。`lower.dawn`：`Ty` 长出 `TensorView` 与 `PartitionView` 两个构造子（后者是**扁的**，把 tensor view 的三个字段抄进来而不是嵌一个 `Ty`），`Instr` 四条，`view_operands` 把两条内存操作共用的两个检查（句柄真是 partition view、下标个数等于 tile 维数）放在一处。`prog.dawn`：`TileOp` 四条与记录 handler 四臂（形状与步长严格为正、tile 维是 2 的幂、`dim_map` 是排列、特殊 padding 只配浮点）。`dev.dawn`：`Padding` 六值 ADT（数值留在 `bytecode.dawn`，与本包其余枚举同规矩）、`TensorView[D]` / `PartitionView[D]` 两个 opaque、四个效果操作、五个公开函数与 `view_grid`。`render.dawn`：两个类型的文本形状与四条指令行。`std/gpu.dawn`：`view_padding_ref`。kernel 五个：`view_transpose` / `view_max_pool` / `view_conv2d`（刀 9 的 strided kernel 改用 view 写，与指针梯子版共用 `transpose_ref` / `max_pool_ref` / `conv2d_ref`）、`view_padding`（五个 padding 值一个 kernel，f32 元素跑在 i32 缓冲区上）、`view_pad_i32`。新族 `scripts/tile-gpu-diff/view_diff.dawn`（六个 case，最后一个是指针梯子的 `transpose_tail`，本族的 kernel 级控制）。台账三张全动：`features.txt` 四行、`types.txt` 两行、`attrs.txt` 五行从 `deferred` 改成 `implemented` 且全到层 3（操作码实现 88 → **92**、类型 19 → **21**、属性 37 → **42**），`check.py` 的 `LANDED_KNIVES` 加 `T11` 并把落在这些行上的九处自测锚点搬到 T12 / T13 的行上，`types.txt` 把 `GatherScatterView` 改成权威的 `GatherScatterViewType` | 层 1：五个新 golden 在 `--gpu-name sm_86` 上**一次通过**（cubin 8448 到 13312 字节，`FUNC GLOBAL` 齐全），**没有架构豁免**。层 2：`view_diff` 六个 case 在本机 3080 上全部 `identical:exact`，其中三个与指针梯子版共用同一份宿主参考。三张台账 `check.py` 与 `--self-test` 全绿 | 层 1 三条、层 2 四条，每条都有具名红集（表在 §6.14 七）：`tensor-view-tag-as-ptr`（tensor view 写成 ptr 标签 → `expected ::mlir::cuda_tile::TensorViewType but got '!cuda_tile.ptr<f64>'`）、`partition-view-padding-inline-flag-at-13-3`（13.3 的文件里写 13.2 的可选参数形状，**同长** → `failed to read tile_shape data`）、`padding-nan-on-integer-elements`（`zero` 变 `nan` 落在 i32 元素上 → `padding_value nan can only be used with floating point element types, got 'i32'`；**这条校验在方言自己的测试树里一个用例都没有**）；`view-strides-swapped`（tensor view 的步长反写 → 三个几何 kernel 红，两个一维的与 `transpose_tail` 绿）、`partition-dim-map-reversed`（`dim_map` 反写 → `view_transpose` 与 `view_max_pool` 红，**`view_conv2d` 绿**，因为它的下标空间是 3 乘 3、换名两头抵消，这是量出来的读数）、`padding-value-bit-cleared`（位域 bit 0 清零、payload 仍写在后面，类型表按自己的偏移寻址所以那个字节没人看 → partition view 没有 padding，`view_padding` 与 `view_pad_i32` 红）、`padding-enum-off-by-one`（四个特殊值转一格、`zero` 留在原地 → `view_padding` 红，`view_pad_i32` 是它的控制；为什么绕开 `zero` 见 §6.14 八）。另有一条给验收者的自轴负控：把 `std/gpu.dawn` 的 `pad_bits` 里 `0x7FC00000` 改成 `0x7F800000`，**别重录 golden**，`tile-gpu-diff` 上只有 `view_padding` 红（第三个输出缓冲区的第 100 到 127 lane），其余五个 case 全绿 | 1（实报 1；`dawn test packages/tileir` **122** 全绿（本刀加四个测试，全是手算出来的字节串）；rebase 到刀 TG 之后矩阵 227 项长到 **235 项**（176 kernel、59 变异体），`tile-golden` 在最终树上不分片 **3246 s**（54:06，235 项全跑退出 0），**十片仍装得下、十条预算行一条也没动**（理由与本机那一轮为什么不能用见 §6.5）；`tile-gpu-diff/run.sh` 见 §6.4 的台账行。**本刀碰了 `std/gpu.dawn`**，`scripts/gen-stdsrc.py` 已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录） |
| **T12 view 族的动态一半，加两条形状查询**（已落地，view 族第二刀） | 「一个 kernel 处理的张量**多大**不写在程序里：extent 与 stride 是 `make_tensor_view` 的操作数，kernel 从缓冲区里读它们，两条形状查询再把设备算出的数答回来当掩码边界和循环边界用；判词是**同一个 cubin 在两个不同形状的张量上都对**，而它与静态拼法在同一份语料上逐位相同」（今天写不出：T11 的每一个 extent 都烘在类型里，一个 cubin 对应一个张量；`get_tensor_shape` 与 `get_index_space_shape` 两行台账是 `deferred / ruling 2`，一个字节也发不出去） | `bytecode.dawn`：`OP_GET_TENSOR_SHAPE`(0x2F) / `OP_GET_INDEX_SPACE_SHAPE`(0x2D) 两个操作码，`put_dim`（`ShapedType::kDynamic` 的八个字节，位模式直接拼而不是移位得来）、`emit_group`（一个变长操作数组的计数加操作数）与 `emit_shape_query`，`ty` 的 tensor view 臂改走 `put_dim`，`encode_instr` 两条新臂加 `MakeTensorView` 那条填上两个组。`lower.dawn`：`Instr` 两条新构造子、`MakeTensorView` 多三个字段，`is_idx_ty` 与 `shape_query`（发整条指令、绑第 `dim` 个结果，与 `BlockId` 同形），`TensorViewOf` 加「每个动态操作数都是 rank-0 i32 tile」的检查。`prog.dawn`：`TileOp` 两条、handler 两臂，`TensorViewOf` 多两个字段，动态维放行非正 extent 但把「操作数个数等于问号个数」钉死。`dev.dawn`：`DYN_DIM` 标记与 `Dim` 三件套、`t_tensor_view` 多两个形参、`t_tensor_shape` / `t_index_space_shape` 两个效果操作，公开面 `tensor_view_dyn` / `tensor_dim` / `index_space_dim` / `idx_of` / `idx_as_scalar`。`render.dawn`：`extent` 印 `?`、`mixed` 把操作数名字填回 shape 与 strides、两条查询的指令行。`std/gpu.dawn`：`masked_double_ref` 与 `view_grid_sum_ref`。kernel 三个：`view_dyn_transpose`（`view_transpose` 的动态拼法，共用 `transpose_ref` 与同一份语料）、`view_tensor_shape`（查询答的数当掩码边界，并把答案写进 i32 缓冲区）、`view_index_space`（查询答的数当两重循环边界，一个 block 走完整张网格）。新族 `scripts/tile-gpu-diff/dyn_diff.dawn`，它的用例单位是 **(kernel, 张量形状)**：七个用例、五种形状，最后一个是静态的 `view_transpose`。台账两张动：`features.txt` 两行从 `deferred` 改成 `implemented` 且到层 3（操作码实现 92 → **94**、层 3 从 40 到 **42**），`make_tensor_view` 与 `types.txt` 的 `TensorViewType` 各补一条证据，`check.py` 的 `LANDED_KNIVES` 加 `T12`，头注多写下第三处判断（三处自测锚点落在 `make_strided_view` / `StridedViewType` / `rmw.xchg` 上，本刀一处也没碰） | 层 1：三个新 golden 在 `--gpu-name sm_86` 上**一次通过**（cubin 8736 / 11536 / 15776 字节），没有架构豁免。层 2：`dyn_diff` 七个用例在本机 3080 上全部 `identical:exact`，`twin=same`（动态与静态两个 cubin 在同一进程里逐 lane 相同）。四张台账 `check.py` 与 `--self-test` 全绿 | 层 1 三条、层 2 两条，红集在 §6.15 七：`dynamic-dim-written-static`（`?` 写成静态常量，**同长** → `'cuda_tile.make_tensor_view' op expected 0 dynamic shape operands, got 2`）、`tensor-shape-as-index-space-shape`（0x2F 写成 0x2D，两条记录同形所以读者读得完，**同长** → `'cuda_tile.get_index_space_shape' op operand #0 must be TileView instance, but got '!cuda_tile.tensor_view<?x?xf64, strides=[?,?]>'`）、`index-space-shape-as-tensor-shape`（反过来，**不是**同一条报文倒过来读 → `'cuda_tile.get_tensor_shape' op operand #0 must be tensor view type, but got '!cuda_tile.partition_view<...>'`）；`dynamic-shape-and-stride-operands-swapped`（两个变长组对调，两组都是二长所以计数仍对得上 → 三个动态 kernel 的六个用例全红，静态 `view_transpose` 绿）、`shape-query-dim-reversed`（锚点在 `lower.dawn`：绑第 `rank-1-dim` 个结果而不是第 `dim` 个 → `view_tensor_shape` 与 `view_index_space` 的四个用例红，**`view_dyn_transpose` 连 `.tilebc` 都不动**，它一条查询也不发）。另有两条给验收者的自轴负控。设备那一侧：把 `scripts/tile-gpu-diff/dyn_diff.dawn:370` 的 `[to_float(blocks(rows, VD_SUM_TILE)), to_float(blocks(cols, VD_SUM_TILE))]` 改成 `[to_float(rows), to_float(cols)]`（宿主改成期待张量的 extent 而不是网格的），**什么都不用重录**，`tile-gpu-diff` 上只有 `view_index_space` 的两个用例红（第四个缓冲区的前两个 lane），其余五个绿。golden 那一侧：把 `scripts/tile-golden/kernels.dawn:4720` 的 `idx_const(2)` 改成 `idx_const(1)`，**别重录 golden**，三个动态 kernel 的文本与字节 golden 全红（`unit` 读到 `cols` 那一格），而 `view_transpose` 等静态 kernel 一个字节不动 | 1（实报 1；`dawn test packages/tileir` **126** 全绿、`dawn test --stdlib` **175** 全绿（本刀加四个包测试与一个 std 测试）；矩阵 235 项长到 **241 项**（179 kernel、62 变异体），`tile-golden` 在最终树上不分片 **2183 s**（36:23，241 项全跑退出 0；rebase 之前那一轮是 2285 s）；**十片装不下了，分第十一片**：最终树那一轮十片的 planning value 是 666 / 627 / 635 / 634 / 628 / 628 / 628 / 625 / 628 / 651s，第一片越过 660s 的 pole 而 `check-gate-budgets.py` 当场拒绝，十一片是 575 到 608s；十条旧行按这一轮重述、第十一条新写，`action.yml` 的两个计数同批改，见 §6.5 与 gates.yml 的 `tile-golden-11` 注；`tile-gpu-diff/run.sh` 见 §6.4 的台账行。**本刀碰了 `std/gpu.dawn`**，`scripts/gen-stdsrc.py` 已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录） |
| **T13 view 族的收官刀**（已落地，view 族第三刀，本族清零） | 「一个 kernel 取址的方式不再只有『等大的格子』：**步长视图**的遍历步长与 tile 宽度是两个数，所以一个下标可以是一个**重叠的窗口**（卷积）或者一个**跳着走的格子**（下采样）；**聚散视图**在一个维度上收的是**运行期读出来的行号**而不是格子下标，所以一次 load 收集哪几行由数据决定；而 `atomic_red_view_tko` 把**一整块 tile** 原子地归约进视图的一格并且**什么都不答**，于是八个 tile block 往同一格里写而彼此之间没有顺序。三者的答案分别与指针梯子版的 `conv1d`、`token_embed` 与 `histogram` **共用同一份宿主参考**」（今天写不出：`make_strided_view` / `make_gather_scatter_view` / `atomic_red_view_tko` 三行台账是 `deferred / ruling 2`，`StridedViewType` / `GatherScatterViewType` 两行同样，一个字节也发不出去；八个原子模式在 `attrs.txt` 上挂着 `no-client-kernel`） | `bytecode.dawn`：`OP_MAKE_GATHER_SCATTER_VIEW`(0x73) / `OP_MAKE_STRIDED_VIEW`(0x74) / `OP_ATOMIC_RED_VIEW_TKO`(0x75) 三个操作码，`TAG_GATHER_SCATTER_VIEW`(20) / `TAG_STRIDED_VIEW`(21) 两个标签，`ATOMIC_RED_FLAG_TOKEN`、`view_bitfield`（13.3 原生类型的**无条件**位域）/ `put_padding` / `put_i32_array` 三个共用写法、`scope_value` 与 `red_mode_value`（`xchg` 点名拒绝），`ty` 两条新臂与 `encode_instr` 三条新臂。`lower.dawn`：`Ty` 长出 `StridedView` 与 `GatherScatterView`（同样是**扁的**），`view_tile_shape` / `view_index_tys` / `view_padding_of` / `view_source_checks` 四个共用函数，`Instr` 三条新构造子且 `LoadViewTile` / `StoreViewTile` 的 `idx_ty: Ty` 改成 `idx_tys: List[Ty]`（聚散视图的下标不同型），`view_operands` 多一条「每个下标是这个视图在那一位要的类型」。`prog.dawn`：`TileOp` 三条与记录 handler 三臂，`check_view_record` 把三个视图共有的记录级规则收成一处。`dev.dawn`：`PartitionView[D]` 更名 `GridView[D]`（`partition_view` 与 `strided_view` 两个构造子答同一个句柄，它们在 kernel 里做的事一模一样）、新 opaque `GatherScatterView[D]`、`GatherIdx` 两值 ADT、`padding_present`、三个新效果操作与 `strided_view` / `gather_scatter_view` / `load_gather` / `store_gather` / `atomic_red_view` / `strided_grid` 六个公开函数，外加 `d_reduce_dim_i`。`render.dawn`：两个类型的文本形状、三条指令行、`pad_clause` 与 `index_types`（`printIndexTypes` 的 splat 规则，聚散视图是树上第一个不走 splat 的）。`std/gpu.dawn`：`strided_pad_ref` / `gather_pad_ref` / `view_atomic_ref`。kernel 五个：`view_conv1d`（重叠窗口，共用 `conv1d_ref`）、`view_token_embed`（共用 `token_embed_ref`）、`view_atomic`（九种模式一个 kernel，`add` 那一格与 `histogram_ref` 对账）、`view_stride_pad` 与 `view_gather_pad`（f32 元素跑在 i32 缓冲区上，宿主比位模式）。新族 `scripts/tile-gpu-diff/gsview_diff.dawn`（六个 case，最后一个是指针梯子的 `conv1d`）。台账三张全动：`features.txt` 三行、`types.txt` 两行、`attrs.txt` 七行从 `deferred` 改成 `implemented` 且全到层 3（操作码实现 94 → **97**，`deferred` 与 `unimplemented` 双双归零；类型 21 → **23** 全实现；属性 42 → **49**，只剩 `rmw.xchg` 一行 `deferred`），`check.py` 的 `LANDED_KNIVES` 加 `T13`、`CONSTRUCTOR_SPELLING` 加两个标签，并把落在这些行上的**九处**自测锚点搬到已实现行或 T14 上（逐处列在报告与代码注释里） | 层 1：五个新 golden 在 `--gpu-name sm_86` 上**一次通过**（cubin 8448 到 12960 字节，`FUNC GLOBAL` 齐全），**没有架构豁免**；唯一有架构门的是 `addf` 配 bf16，逐档量出 sm_80/86/87 拒、sm_89/90/100 收（方言散文说「Hopper 起」，实测早一代，见 §6.16 四）。层 2：`gsview_diff` 六个 case 在本机 3080 上全部 `identical:exact`，其中三份宿主参考是别处那三个指针梯子 kernel 用的同一份，`histogram=same` 是第四份对账。三张台账 `check.py` 与 `--self-test` 全绿 | 层 1 五条、层 2 三条，每条都有具名红集（表在 §6.16 六）：`make-strided-view-as-partition-view` / `make-gather-view-as-strided-view`（操作码互换，**同长** → 结果类型不对）、`gather-sparse-dim-and-tensor-view-swapped`（`sparse_dim` 与张量视图下标对调，**同长** → `expected 'tensor_view' type`）、`atomic-red-scope-and-mode-swapped`（范围与模式对调 → 模式值 3 以上落在只有三个取值的范围域上）、`atomic-red-value-and-token-swapped`（值与 token 对调 → token 不是 tile）；`strided-traversal-as-one`（所有遍历步长写成 1，下标空间只会变大所以没有未定义行为 → **只有 `view_stride_pad` 红**，`view_conv1d` 与 `view_atomic` 字节动而答案不动，因为它们那两个视图只在下标 0 上读）、`view-padding-bitfield-cleared`（13.3 位域 bit 0 清零 → 两个 padded kernel 红）、`atomic-red-mode-rotated`（七种模式各转一格、`add` 与 `addf` 留在原地 → `view_atomic` 红）。另有一条给验收者的自轴负控 | 1（实报 1；`dawn test packages/tileir` **132** 全绿、`dawn test --stdlib` **176** 全绿（本刀加六个包测试与一个 std 测试）；矩阵 241 项长到 **251 项**（184 kernel、67 变异体），`tile-golden` 在最终树上不分片见 §6.5；**十一片仍装得下**；`tile-gpu-diff/run.sh` 见 §6.4 的台账行。**本刀碰了 `std/gpu.dawn`**，`scripts/gen-stdsrc.py` 已跑、`stdsrc.dawn` 同批提交，Core golden 在其后重录） |

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
- **写出来的函数值最多八个参数，而超出只在运行期报**：`selfhost/src/main.dawn` 只生成
  `dawn/rt/Fn0` 到 `Fn9`（证据包占一个形参），一个效果操作就是一个函数值，所以十一个形参的
  `t_mmaf_scaled` 编译通过、运行时崩在 `java.lang.NoClassDefFoundError: dawn/rt/Fn12`
  （刀 T10 实测）。刀内的处置是把四个数并成一个 `List[Int]`，签名回到八个；**语言侧的欠账
  是这个限制没有编译期诊断**，已开 issue #87。
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
