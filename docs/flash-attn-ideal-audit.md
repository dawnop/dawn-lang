# flash_attn 对照理想写法的复核（tileir 0.12）

> 状态：**current**（2026-10-23 更新；下方保留 10-07 审计）。基线 `origin/main` = 50f15459（tileir 0.12.0，K4 已合）。
> 理想写法取自 [tileir-011-design.md](tileir-011-design.md) §3.1（0.11 目标写法）、
> [tileir-k4-design.md](tileir-k4-design.md)（运行期标量）与维护者工作区的
> research-generic-kernel-report-20261006（泛型 kernel 的目标形状 `fn flash_attn[D, A](.., scale)`）；
> 外部对照是 Triton 教程 06 的融合注意力（<https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html>，
> 取其 `_attn_fwd_inner` 与 `_attn_fwd` 的在线 softmax 部分）。
> 这里没有写进去的数字都没量过。

## 2026-10-23 当前状态

A2 已将 bf16 输出迁为 f32。本次在 A2 合入基线 `5c1bf13f` 上，合并一份 `[D: FloatDtype, A: FloatDtype + ScalarDtype]` 主体、一份泛型五参闭包工厂及类型化录制 helper。Float/Float 保留 `zeros(o)`、自然指数和精确非 FTZ 除法；BF16/F32 保留 `full` 初始化、exp2-FTZ、运行期 log2(e) scale、未收窄 p 的行和、第二 MMA 前的最近偶数 BF16 舍入和近似 FTZ 除法。策略与形状是宿主捕获值，设备 ABI 仍为 Q/K/V/O/scale。

当前编译与录制探针的六对既有 MLIR/tilebc 逐字节不变；36 个架构/维度/头数/格式组合的 TileProg、lower、MLIR、tilebc 也相等。调用图对选定 f64 捕获值严格选臂，并对每个显式设备调用核对编译器位置；同型 `to` 保留一个无 IR 的调用来源。最终门与三卡结果由交付报告记录。方案与边界见 [flash-generic-merge-design.md](flash-generic-merge-design.md)。

P4-c 已提供 `FaShape`/`FaCfg` 和每架构配置工厂，普通 flash 的尺寸参数化已有消费者；剩余 GQA 尺寸与运行期键数交 K3。P3 已对 bf16 采用 exp2-FTZ，f64 继续自然指数。下文保留 10-07 的问题与探针原貌，不能再据此称泛型“待裁”、尺寸“无消费者”或 exp2“缺实测”。P4/A2 的历史性能数据保留原输出格式身份，未称为本次新实测。

## 1. 之前与之后

之前（0.11 末，scale 烧成宿主常量）：

```dawn
fn flash_attn(q: Param[Float], k: Param[Float], v: Param[Float], o: Param[Float]) -> Unit !Dev = {
  let tq = load_cell(q)
  var m: Tile[Float] = full([FA_BQ, 1], -INFINITY)
  var l: Tile[Float] = full([FA_BQ, 1], 0.0)
  var acc = zeros(o)
  for j in d_range(0, ATT_N / FA_BK) {
    let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), lit(0.0)) * lit(ATT_INV_SQRT_D)
    ...
```

之后（本 PR）：

```dawn
fn flash_attn(q: Param[Float], k: Param[Float], v: Param[Float], o: Param[Float], scale: Param[Float]) -> Unit !Dev = {
  let tq = load_cell(q)
  var m: Tile[Float] = full([FA_BQ, 1], -INFINITY)
  var l: Tile[Float] = full([FA_BQ, 1], 0.0)
  var acc = zeros(o)
  for j in d_range(0, ATT_N / FA_BK) {
    let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), 0.0) * scalar(scale)
    ...
```

其余九行不变。golden 的变化只有两处：入口多一个 `%arg4: tile<f64>`，以及原来的
`constant <f64: 0.17677669529663687> : tile<32x32xf64>` 一行换成 `reshape %arg4` 加 `broadcast` 两行
（其后的值编号整体加一，操作数 49 变 50）。`flash_attn_bf16` 同样改成 `Scalar(F32)`，golden 变化同形。
其它 kernel 的 golden 逐字节不动。

## 2. 逐行对照

下表保留当时的审计快照。当前 A2 已将 bf16 输入/f32 累加的输出从 f64 迁为 f32，
五个录制入口与宿主四字节缓冲同步；表中泛型探针的 `(acc / l).to(F64)` 已被此输出契约替代，
不能复制成当前 bf16 实现。P3 已采用 exp2-ftz，P4-c 已实现普通 flash 的配置/尺寸工厂与多形状消费者。
泛型主体合并按裁决排在 A2 后，随后才做 GQA；运行期键数与 GQA 尺寸/布局仍待 K3。
历史测量保留其原来的 f64 输出身份，A2 同轮测量另记。参见 [后端设计](tile-backend-design.md#646-a2bf16-flash-的-f32-输出契约2026-10-23)。


| 位置 | 现在 | 理想或 Triton | 差距 | 类别 | 处理 |
|---|---|---|---|---|---|
| 签名 | `scale` 是第五个入口参数 | Triton 的 `sm_scale` 是运行期实参；cutile-rs 的 `qk_scale: f32` 同 | 本来是缺口（scale 烧进 cubin） | 1 | **本 PR 已修**（f64 与 bf16 两个 kernel，各一个提交） |
| `* scalar(scale)` | 显式 `scalar(p)` | `s * sm_scale`（Python 里标量直接乘） | K4 §8 第 7 条已裁：`Tile * Float` 不做，运行期读入必须显式写 | 不是缺口 | 已裁，不动 |
| `lit(0.0)` 累加器 | 显式 `lit` | 0.11 目标写成裸 `0.0`，由 `FromFloat[Tile[D]]` 折成 `lit` | 裸 `0.0` 今天能编，**golden 逐字节不变**（实测），但站点调用图（`record.py`、`gpumap.dawn`）把每个 `lit` 调用配到源码里的一个调用节点，裸字面量折出的 `lit` 没有源码 span，`record.py` 当场拒绝 | 1，但卡在站点调用图的配对规则 | **已做**：`record.py` 把裸数字配成可选的 `lit` 行，kernel 两处改写成裸 `0.0`，golden 逐字节不变 |
| `var m/l/acc` 与 `for` | 声明序携带，`d_range` | 同 | 无 | 无 | 无 |
| `f64` 与 `bf16` 两份几乎相同的函数 | `flash_attn`、`flash_attn_bf16` | `fn flash_attn[D, A]`，`var m: Tile[A]`，一份体 | 今天能写：用 `[D: FloatDtype, A: FloatDtype + ScalarDtype]`、`p.to(dt)`、`(acc / l).to(F64)`，两个 dispatch 臂各绑一组格式。**已在草稿工程里实测**：bf16 臂的 golden 与单独的 bf16 kernel 只差调用点的名字，f64 臂的累加器初值由 `zeros(o)`（一行）变 `full`（常量加 broadcast），多两个操作 | 1 | **未做，待裁**（问题 1）：它会让 GPU 页展示的那个 kernel 带上泛型签名 |
| 尺寸 `FA_BQ`、`FA_BK`、`ATT_N`、`ATT_D` 是模块常量 | 常量 | Triton 的 `BLOCK_M`、`BLOCK_N`、`HEAD_DIM` 是 `tl.constexpr` 实参 | P-A（research-tile-surface-09 §5.3）：kernel 写成 `fn flash_attn(bq, bk) -> fn(..)`，字节零变化。当前没有第二个形状，没有消费者；页面、`record.py`、站点测试都把 `fn flash_attn(` 当作 kernel 自己的签名 | 1，无消费者 | **未做**（问题 4），等 K3 的 `flash_attn_gqa` |
| 键数 `ATT_N / FA_BK` | 常量 | Triton 的 `N_CTX` 是运行期实参 | `blocks_of` 与 `DYN_DIM` 已有，但动态维的长度今天走 T12 的 `dims` 缓冲区；是否把它迁成标量参数，K4 §5 第 5 行写的是「另议」 | 1 或 2，未决 | **未做，待裁**（问题 3） |
| `exp` | `exp(s - m_new)` | Triton 把 `1/ln2` 折进 scale，用 `exp2` | `exp2` 已有。这是性能选择，不是表达力缺口：仓里没有它快多少的实测，设计文档规矩是性能断言要有出处；参考实现也得换底 | 1，缺实测 | **未做**（问题 5） |
| 输出 `logsumexp`（`M`） | 无 | Triton 在 epilogue 里存 `m_i + log2(l_i)` 给反向用 | 是另一个 kernel（训练前向），不是写法差距。多一个 `Out` 参数不需要任何新 API | 不是缺口 | 另议，需要时按新 kernel 做 |
| 因果遮罩（`STAGE == 2`） | 无 | Triton 有 | 同上；`attn_causal` 在三个 launch 的版本里已有遮罩的写法 | 不是缺口 | 另议 |
| `.transpose()` 读 K | `load_at(k, [j]).transpose()` | Triton `tl.trans(k)` | 无 | 无 | 无 |
| 行统计 `keepdims` | `[BQ, 1]`，同秩长度 1 隐式广播 | Triton 用 `[:, None]` | 无 | 无 | 无 |
| `acc`、`m`、`l` 的格式 | 写在两处标注 | Triton 的 `tl.float32` 累加器 | 无 | 无 | 无 |

没有类别 2 或 3 的条目：每个缺口要么今天就能写、要么是还没有消费者的取舍。第 3 类（语言特性）只剩一条旁证：
泛型携带 `var m: T`（`T` 是裸类型参数）仍被编译器拒绝（staged-for-design §7.0），但目标写法的携带类型是 `Tile[A]`，
不受影响，没有真实消费者就不开。

## 3. 待裁的问题

1. **泛型合并**。把两个 kernel 合成一个 `[D, A]` 函数，代价是 GPU 页与 explorer 展示的 `flash_attn` 带泛型签名，
   且 f64 golden 的累加器初值多两个操作。收益是少一份重复，且 `flash_attn_gqa` 之后只写一份。
2. **裸字面量进调用图**。让 `record.py` 与 `gpumap.dawn` 接受「没有源码调用的 `lit`」（表里那一行没有 span），
   或者保留 `lit(0.0)` 的显式写法。**已做**（acb09e4b）：`record.py` 把裸数字配成可选的 `lit` 行，两个 kernel 的累加器初值改写成裸 `0.0`，
   golden 逐字节不变。
3. **键数作运行期标量**。要不要把 T12 的 `dims` 缓冲区迁成标量参数，并让 `flash_attn` 读它。
4. **尺寸参数化**（P-A）要不要现在做，还是等 K3。
5. **`exp2`**。要不要先在外部 runner上量一次再决定。

## 4. 本 PR 的验证

三份台账在最终摘要上各录一次（sm_86 本机、sm_100、sm_90），记录见各自台账文件的末行。
变异体 `scale-baked-again`（把 `scalar(scale)` 写回 `f_const`）是 `tile-golden` 里第一个改 kernel 而不改
`packages/tileir` 的变异体：golden 变红，而 `tileiras` 仍然接受它，所以只有 golden 能抓住它。
