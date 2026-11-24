# GPU G14-1：计划表类型化、dtype 泛型 GEMM 工厂与融合 epilogue

> 状态：**current**（进行中）。一个分支两个提交：先做计划表类型化（纯重构，既有设备字节与全部黄金文件逐字节不变），
> 再加 bf16 输入、f32 累加的 GEMM 工厂与三种 epilogue。改的全是 `scripts/tile-golden/kernels.dawn`
> 及其周边，即 tile inputs 之内；最终 inputs 经三卡串行录账一次。

## 1. 为什么做

`scripts/tile-golden/kernels.dawn` 里同一个概念有三套拼写：

- matmul 的计划表 `mm_plan(arch: String, dtype: String)` 与 `mm_record` 用 `"f64"/"f16"/"i8"` 字符串分派，
  兜底是 `panic("matmul: available dtypes are f64, f16 and i8")`；
- 注意力的 `fa_plan(arch: String, d: Int)` 与 `fa_record(..., bf16: Bool, ...)` 用布尔分派；
- 同一个文件里的 `fa_record_typed` 却已经是泛型 `Dtype[D]`，并在体内用 `dtype_name(dt) == "f64"` 之类的字符串比较
  重新判断一遍哪对格式合法，再 panic。

三种表示说的是同一件事（元素格式与架构），彼此是平行真相；`_ -> panic` 把本该由类型排除的情形留到运行期。
CUTLASS 与 cuTile 都把元素类型和累加类型作为类型参数，不靠字符串。Dawn 已有 ADT、泛型与 trait，本刀不需要新语言特性。

缺口的另一半：没有任何一条 matmul 是「16 位输入、f32 累加、累加器上做完收尾再存」。现有 f16 matmul 是 f16 累加且
`store_cell(c, acc)` 直接存；FA 是唯一的 bf16 输入 f32 累加的 kernel，但它不是 GEMM。

## 2. 第一个提交：计划表类型化

### 2.1 做什么

- `type Arch = Generic | Sm86 | Sm90 | Sm100 | Sm120`，封闭。只有 `arch_name` 知道 tileir 的 hint 表以什么拼写做键
  （`"default"`、`"sm_90"` ...）；只有命令行入口 `arch_from_name` 把字符串变成 `Arch`，未登记的名字落到 `Generic`，
  与此前「没有测量过的架构取通用计划」一致。
- `trait MmElem[D]`：每个有 matmul 的元素格式一个 impl（`Float`、`F16`、`I8`），带 `mm_plan` 与 `mm_trace`
  （后者固定缓冲区格式：f16 保持 f16 累加与输出，i8 保持 i32）。`mm_record[D: MmElem](dt, arch, shape, ..)`
  取代 `mm_record(arch, dtype: String, ..)`。
- `trait FaElem[D]`：`BF16`（f32 累加）与 `Float`（f64）两个 impl，带 `fa_plan` 与 `fa_trace`。
  `fa_record[D: FaElem](dt, arch, d, n, bh, ..)` 取代 `bool`。`fa_record_typed` 退为私有助手，只被两个 impl 调用，
  体内的字符串合法性判断与 panic 随之删去：合法的格式对就是 impl 本身。
- `recording_policy` 的 `arch` 改为 `Arch`；`mm_named`、`fa_named`、`config_manifest`、`mm_config_check`、
  `fa_config_check`、`flash_output_records` 随之改写。

### 2.2 验证（纯重构的判据）

- 256 个黄金 kernel 的文本与字节码，在 JVM 与原生两个后端上与已提交的 `.mlir` / `.tilebc` 逐字节相同
  （`--config-manifest` 输出 456548 字节，与改前逐字节相同；`flash-config/check.py` 三项 PASS）。
- 原先靠 `panic` 兜底的拒绝（`mm_record("sm_90", "f32", ..)`）现在是检查器错误。负控放在
  `scripts/tile-golden/plan-rejected.dawn`：把 `kernels.dawn` 当作模块导入，用 `F32` 调 `mm_record`、用 `F16`/`F32`
  调 `fa_record`、用字符串当架构、用字符串当格式，逐条与 `plan-rejected.expected` 比对。
  工作项 `plan-type-rejections` 登记在 `matrix.txt`。
- 其余运行期拒绝（cga 与行块的性能过滤、非整块形状、偏移乘积越界）保持原样、原消息、原调用点位置。
- 两处只随行号移动的记录：`scripts/call-records-contract/rows.expected`（调用点行号）与
  `site/gpu-map/flash_attn.map`（源码位置配对）。两者除行号与位置外无任何差异。

## 3. 第二个提交：bf16 到 f32 的 GEMM 与融合 epilogue

### 3.1 累加类型由输入类型决定

```dawn
pub trait GemmElem[D] {
  type Acc
  fn gemm_acc(dt: Dtype[D]) -> Dtype[D.Acc]
  fn gemm_plan(dt: Dtype[D], arch: Arch) -> MmPlan
  fn gemm_zero(dt: Dtype[D], shape: List[Int]) -> Tile[D.Acc] !Dev
  fn gemm_mma(a: Tile[D], b: Tile[D], acc: Tile[D.Acc]) -> Tile[D.Acc] !Dev
}
```

累加格式不是工厂的第二个类型参数，而是 `D.Acc`，由 impl 绑定（`impl GemmElem[BF16] { type Acc = F32 .. }`）。
所以「bf16 输入配 f64 累加」没有可写的拼写；epilogue 的参数类型写成 `Tile[D.Acc]`，给错累加类型的 epilogue
是类型错误。`mma[A, C: FloatDtype]` 本身不限制 `A` 与 `C` 的搭配，合法性由 tileiras 在汇编时才说；
这里把它提前到检查器。

未选的做法：把累加类型做成第二个类型参数 `A: FloatDtype + ScalarDtype`（`fa_kernel` 的写法）。那样合法的
`(D, A)` 对只能靠运行期比较 `dtype_name` 来守，这正是第一个提交刚刚删掉的东西。

### 3.2 epilogue 是累加器上的函数

```dawn
fn gemm_identity(acc: Tile[F32]) -> Tile[F32] !Dev = acc
fn gemm_scale(acc: Tile[F32], alpha: Param[F32]) -> Tile[F32] !Dev = acc * scalar(alpha)
fn gemm_bias_relu(acc: Tile[F32], bias: Param[F32]) -> Tile[BF16] !Dev =
  max(acc + load_at(bias, [idx_const(0)]), f_const(F32, f32(0.0))).to(BF16)
```

- 两个工厂：`gemm_record`（epilogue 只看累加器）与 `gemm_record_with`（epilogue 多读一个操作数：偏置行，
  或启动时传入的标量）。第三个内核参数由调用者以 `Arg[X]` 描述，工厂不猜。
- epilogue 在寄存器里的累加器上执行，之后只有一次 `store_view_tko`。偏置行用 `[1, N]` 的 cells 按 B 的列切，
  同一列块的所有行块读同一个 cell，在累加器的行方向广播。
- 激活作用在 f32 的和上，转换最后做。relu 与单调舍入可交换，所以仅靠 relu 区分不出「先转换后激活」；
  能区分的是偏置：`bf16(acc + bias)` 与 `bf16(acc) + bf16(bias)` 是两次舍入对一次舍入。设备语料据此构造
  （见 4.2）。
- 闭包参数不能自己写效果的老限制（tile-backend-design 的 `d_for` 记录，§6.43 之前的章节）：epilogue 的类型是 `fn(Tile[D.Acc]) -> Tile[O] !Dev`，
  效果写在函数类型上。本刀先用最小样例确认它可录制，再写工厂；实测录制通过（`gemm_bias_relu_bf16.mlir`）。

### 3.3 计划表

`gemm_plan` 不是新测量：sm_90 与 sm_100 取 f16 matmul 已测的格（tile-backend-design §6.43 的 P4-e 小节），
通用架构取 64x64x32。bf16 与 f16 的操作数瓦片相同，差别只在累加器是 f32。它们走同一个
`recording_policy`（cga=2 且行块小于 128 拒绝；sm_90 行块 256 无 cga=2 拒绝）。**本刀不对这些格作任何速度断言**；
每张卡上它们是否能汇编、能启动、数值是否正确，由设备家族 `gemm` 逐卡回答。

### 3.4 黄金与负控

新增黄金（各经 tileiras 汇编，sm_90 与 sm_100 变体按各自架构）：

| kernel | 内容 |
|---|---|
| `gemm_bf16`、`gemm_bf16_sm90`、`gemm_bf16_sm100` | 恒等 epilogue，f32 输出 |
| `gemm_scale_bf16` | 启动时标量缩放，f32 输出 |
| `gemm_bias_relu_bf16`、`gemm_bias_relu_bf16_sm100` | 偏置加 relu 后转 bf16 输出 |

类型负控 `scripts/tile-golden/gemm-rejected.dawn`：`F32`、`F64` 输入（无 `GemmElem` impl）；
累加类型错误的 epilogue（`Tile[F64]`）；输出缓冲类型与 epilogue 结果类型不符；缺少 epilogue 的额外操作数。
先证明会红：门禁在期望文件不符时失败，且把 `impl GemmElem[F32]` 加进 `kernels.dawn` 后四条拒绝变成接受，工作项失败。

数值变异体（合法录制，数值错误，设备拒绝）：

- `gemm-bias-after-convert`：先转换再加偏置；
- `gemm-relu-before-bias`：先激活再加偏置；
- `gemm-scale-dropped`：标量缩放被忽略。

各自在 tile-golden 里确认「录制合法且黄金文本变了」，在 tile-gpu-diff 里确认「cubin 能装、能启动、被独立参考拒绝」。

## 4. 设备验证

### 4.1 判据

沿用既有口径。输入用 exact-by-corpus：元素取 `{-1, 0, 1} / 16` 的小整数倍，每个乘积与每个部分和都是 f32 能精确表示的
二进制小数，所以 f32 累加的结果与求和顺序无关，对 f64 主机参考逐元素精确相等。这验证数据路径、布局与启动网格，
不声称一般语料下的舍入精度。另给一条一般语料的容差档（任意 bf16 值），主机参考用 f64，容差档只回答「没有大错」。
sm_86 按既有 advisory 口径记账。

### 4.2 语料与变异体的可分辨性

- 恒等与标量缩放：精确档。缩放取 `3/8`（精确）。
- 偏置加 relu 转 bf16：偏置取 `k / 1024`，累加和取 `1/256` 的倍数，二者之和在 f32 里精确，但在 bf16 里不精确；
  于是 `bf16(acc + bias)` 与 `bf16(acc) + bf16(bias)` 在语料里确有差异（变异体因此会红）。
  语料中必含负的和，使 relu 的两侧都被走到。

### 4.3 设备结果

（待三卡录账后回填。）

## 5. 不做的（理由）

- **运行期 autotune**：已裁不做。配置是编译期常量，带台账出处。
- **尾块（M、N、K 非整块）**：属 G14-2，动 `prog.dawn` 的 cells 推导，要等 R4-f 合并后设计。本刀的 GEMM 与 matmul
  一样拒绝非整块形状，且消息与调用点位置不变。
- **f16 输入 f32 累加、f32 输入的 impl**：trait 已经让它们是「再写一个 impl」的事，但没有对应的设备语料与计划测量，
  本刀不先写没有证据的 impl。
- **替换现有 matmul / matmul_f16 / matmul_i8**：它们的设备字节是第一个提交的回归基线，保持逐字节不变。
- **把 kernel 工厂迁出 `scripts/tile-golden` 成为库**：评估见 §6，本刀不做。
- **性能断言与调参**：本刀不测速，不填新的性能表格；`gemm_plan` 是借用 f16 已测格的未测量默认值，文中已如实标明。
- **行归约型 epilogue（softmax、层归一化）**：需要跨列块的归约，不是瓦片局部的收尾，另成一刀。

## 6. 工厂迁出测试语料的评估

可复用的 kernel 工厂（`fa_kernel`、`mm_kernel`、`gemm_record`、各计划表、`recording_policy`）住在
`scripts/tile-golden/kernels.dawn`，即测试语料文件里；Playground 样例 `flash_attn.dawn` 因此是手抄副本，
靠 doc-check 的固定片段与录制对拍防漂移。

本刀之后迁出的代价与收益：

- 收益：样例与语料共享同一份源码；`Arch`、`MmElem`、`FaElem`、`GemmElem` 已是类型，库边界天然存在。
- 代价：`kernels.dawn` 在 tile inputs 之内，把工厂搬进 `packages/` 一个新包（不是 `packages/tileir`，那里声明
  不放调优表）会改变 inputs 摘要的定义与 `call-records-contract`、`site/gpu-map`、变异体锚点三处对源码文本的读取；
  新包还要决定谁持有计划表与台账出处。
- 本刀为此做了两件让搬家变机械的事：工厂与计划表只经 `pub` 的类型化入口暴露（`plan-rejected.dawn` 已经把
  `kernels.dawn` 当模块导入，证明了这条边界可行）；GEMM 工厂写成自足的一段。
- 结论：不单独立刀；要搬时作为独立裁决，先改 inputs 摘要定义，再搬文件。
