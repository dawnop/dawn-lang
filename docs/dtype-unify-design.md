# 设备格式与 std 值类型统一：规则、现状复核、U3/U4

> 状态：**proposed**。2026-10-08 写成。本文有两半，生命周期不同：
> 规则、依赖方向、见证铸造、`HasDtype`、只存储格式（§1 到 §3）描述的是**已经落地**的 U1 与 U2
> （提交 3aa0f8aa、24d3fcd2，2026-10-06 至 07，权威条文在 spec §12.6），读作现状；
> 尚未落地、待评审的只有 U3（类型化 `upload`/`download`）与 U4（常量带宿主值类型），即 §6 与 §7。
> 依据：维护者工作区的调研报告 research-format-types-unify-report-20261006（下称「10-06 报告」）。
> 基线：`origin/main` = c7c81203，种子 v0.85.0，`packages/tileir` 0.12.0。
> 本文所有计数都在这个提交上用 `git grep` 数出来，不含 `selfhost/src/embed`；没有量过的写「未量」。

## 0. 先说一个与任务前提不同的事实

U0 的任务单假设 U1、U2 还没做。核对 `origin/main` 发现它们**已经做完**，并且是在 10-06 报告之后的两天内：

| 刀 | 提交 | 内容 |
|---|---|---|
| U1（std 一侧，纯增量） | 3aa0f8aa（10-06） | 新 `std/dtype`（`Dtype[T]`、`pub(pkg)` 铸造、`HasDtype`、`F64`/`I64`/`I1`）；`std/int/{i8,i16,i32,u8}` 加同名见证与 impl（经 `scripts/fixed-ints/gen.py`）；同名类型加常量的 `dawn doc` 锚点与 LSP 各一条测试 |
| U1（narrow 一侧）+ U2 | 24d3fcd2（10-07） | `std/narrow` 加 `BF16 F16 F32` 的见证与 impl，加只存储的 `TF32 F8E4M3FN F8E5M2 F8E8M0FNU F4E2M1FN`，`FP16` 改 `F16`；`std/gpu` 删 14 个标记与旧 `Dtype` trait，只留 `I4`；`alloc`/`module_global` 收 `Dtype[T]`；tileir 删 `I1`，`Tile[F64]` 变 `Tile[Float]`，`FloatDtype` 答 `Dtype[D]`，tileir 0.11.0；全仓迁移；tile golden 逐字节不变 |

排期与实现记录在 [tileir-011-design.md](tileir-011-design.md) §2.4、§7、§7.1（那篇把 U1/U2 与 S2/L3/F0 排进同一个 tileir 版本，U2 因而没有走 10-06 报告里的「tileir 0.11.0」之外的版本号）。
所以本篇 U0 的角色变了：不再是动码前的设计稿，而是把统一这件事**单独成篇**（tileir-011 里它只是五条改动之一），
复核 10-06 报告的数字与语言事实，并把仍然开着的 U3、U4 立起来。§12.6 的改写**已经在 spec 里**（见 §5），不需要再出草案；
本文只给 U3 落地时 §12.6 要动的那几句（§6.3）。

## 1. 规则、依赖方向、铸造、`HasDtype`

**规则（spec §12.6 已有等价表述；这是一句话版）**：类型位置写值类型，值位置写格式名。
两者对 `std/narrow` 与定宽整数同名（`Tile[BF16]` 与 `alloc(BF16, n)`），对内建三种是
`Float`/`F64`、`Int`/`I64`、`Bool`/`I1`。

**依赖方向**：`std/dtype` ← `std/narrow` 与 `std/int/*` ← `std/gpu` ← `packages/tileir`。
`std/dtype` 什么都不引入，是最底层的小模块。`std/modules.txt` 的顺序就是这个方向
（dtype、narrow、int/i8 到 int/u64、float、……、gpu）。`Dtype` 不放进 narrow 或 gpu 的理由：
narrow 不该依赖 gpu（反向成环），整数模块也要用它。

**铸造**：`pub opaque type Dtype[T] = String`，唯一的构造函数 `dtype_named` 是 `pub(pkg)`，
所以只有捆绑 std（一个包，spec §10.4）里的模块能造一个格式；用户程序不能给自己的类型声明设备格式。
一个类型要有设备格式，在**它自己的声明模块**里写三行并排：类型、同名 SCREAMING 见证常量、`impl HasDtype`。

**`HasDtype[T]`**：`trait HasDtype[T] { fn dtype_of() -> Dtype[T] }`，`T` 只在返回位，由期望类型选 impl
（`let f: Dtype[Float] = dtype_of()`）。它服务**没有见证值**的泛型代码（`full`、`mma` 的累加器）。
有见证的函数（`alloc`、`param`、`to`、`In(..)`）签名是 `Dtype[D]`，不带 trait 约束。
tileir 另有 `FloatDtype`（只给七个算术浮点），与 `HasDtype` 分开保留，理由在 tileir-011 §9 Q4：并成一个会把整数与只存储格式放进 `full` 的约束，类型错误退成运行期拒绝。

**被推翻的前提**：`std/gpu` 文件头与 `tile-backend-design.md` §3 曾写「不复用 narrow 的类型，
因为那样 `alloc(narrow.bf16(0.0), n)` 得造一个值当标签」。同名见证让这条不再成立（不需要造值）。
两处文字已随 24d3fcd2 改掉，`std/dtype.dawn` 的文件头明写了这条被推翻。

## 2. 复核：与 10-06 报告相比变了什么

| 项 | 10-06 报告 | 现在（c7c81203） |
|---|---|---|
| 撞名 | `BF16 F32`，定宽整数后加 `I8 I16 I32 U8`，共 6 个 | 0 个：`std/gpu` 不再导出任何标记（`use std/gpu.{BF16}` 报「no exported name」）。撞名只会发生在用户自己声明了同名类型的模块，机制照旧（实测 §4 第 6 条） |
| `FP16` 改名 | U1 的一部分，约 24 处 | **已做**，`F16`、`f16()`、`round_f16`；`std/narrow` 之外的 `fp16` 只剩 `scripts/opaque-twin/narrow.dawn` 的标签字符串与文档里的历史叙述；10-06 报告 §4.2 数的 163 行 17 个文件已清；`std/moved.txt` 已于 10-07 撤销（机制整个删了），所以报告与 tileir-011 §7.1 提的「`fp16` 四行 no-hint」不再存在 |
| 格式数 | std/gpu 15 个标记 + tileir 的 `I1` | 16 个见证：内建 3（`F64 I64 I1`）、narrow 8（`BF16 F16 F32 TF32 F8E4M3FN F8E5M2 F8E8M0FNU F4E2M1FN`）、int 4（`I8 I16 I32 U8`）、gpu 1（`I4`）。16 个 `impl HasDtype` 一一对应 |
| tileir 版本 | U2 = 0.11.0 | 0.11.0 已发（U2 同版），**0.12.0 也已发**（#606，运行期标量参数，`ByPtr`/`ByValue`，`ScalarDtype`）。下一个 minor 是 0.13.0，只有 U4 会碰 tileir（U3 只改 std/gpu） |
| 类型位置 `[F64]`/`[I64]`/`[I1]` | 全仓 675 处，16 个文件 | 迁移前（24d3fcd2 的父提交）重数：619 + 12 + 61 = 692，仍是 16 个文件（正则口径与报告不同，差的 17 处没有逐条查是哪些行，不影响结论）。迁移后残留的 `[F64]` 都是本地自定义同名类型（`scripts/opaque-twin`、`scripts/checker-corpus` 各夹具自己的 `type F64 = F64`）与 `site/src/gen/gpumap.dawn` 的两处字符串，不是 std 标记 |
| 见证位置 | 约 1359 处 | 现在 `param(`243、`f_const(`183、`alloc(`55、`float_to_float(`10、`module_global(`9、`.to(`8，`In/Out/Shared/Scalar(格式, ..)` 713；口径同 10-06 报告（裸出现，不含注释），不再有迁移意义，只作规模记录 |
| 约束 | tileir 约 34 处 `[.. : Dtype]` | 迁移后 `HasDtype`/`FloatDtype`/`ScalarDtype` 的出现：`dev.dawn` 15、`prog.dawn` 1、`std/gpu` 10、`std/narrow` 10、`std/dtype` 5、各整数模块各 3 |
| 引入 `std/gpu` 的 `.dawn` 文件 | 33 个（tileir-011 数）；10-06 报告数 11 个「引入行含标记」 | 37 个（K4 以来新增的 tile-gpu-diff 与 tile-golden 程序），其中没有一处再引标记 |
| `Tensor[U32]` | 「在 `alloc` 处是类型错误」 | 精确说法：`Tensor[U32]` 这个**类型**仍然写得出来；造不出 `Dtype[U32]`（没有见证、`HasDtype[U32]` 不存在），所以没有 `alloc` 能产出它。实测 §4 第 5 条。`alloc[D](d: Dtype[D], ..)` 本身没有 trait 约束，拒绝来自「没有这个值」 |

**U1/U2 范围的更新**：10-06 报告的 U1（「`std/gpu` 的旧标记暂留」）与 U2（「一次性切换」）在落地时合并成了 tileir-011 的 PR A（std/dtype 与整数一侧，#590）和 PR B（narrow 一侧加切换，因为 `std/narrow.dawn` 在 `TILE_PATHS`，动它就动 tile 输入摘要）。
报告里的两条负控（把 narrow 的 `BF16` 见证名改成 `"f16"`、把 `impl HasDtype[Float]` 答成 `"f32"`，各让 tile-golden 红）属于 tileir-011 §6.3 的变异体，不在这里重复。

## 3. 只存储的格式

没有宿主算术，只有存储：

| 格式 | 声明处 | 有什么 | 缓冲格式？ |
|---|---|---|---|
| `TF32` | `std/narrow` | `FromFloat`、`Show`、`HasDtype`、`round_tf32` | 是（4 字节） |
| `F8E4M3FN` `F8E5M2` `F8E8M0FNU` | `std/narrow` | 同上 | 是（1 字节） |
| `F4E2M1FN` | `std/narrow` | 同上 | 否（tile 格式，半字节） |
| `I4` | `std/gpu`（它不是 narrow 的浮点，也不是 `std/int` 的宽度） | 见证与 `HasDtype`，没有宿主值 | 否 |

它们没有 `to_f64`：该名字是 `Narrow` trait 的成员，trait 方法共享函数命名空间，第二个同名方法编不过（tileir-011 §7.1）。
这条对 U3 有后果（§6.2 开放问题 1）。`BF16 F16 F32` 有完整算术（`Narrow`、运算符），`F32` 可写进类型但 `element_bytes` 不认，分配不了。
`U16 U32 U64` 没有设备格式，是故意的：方言没有无符号整数 tile 类型（符号是操作的属性）。`U8` 有，因为它是缓冲格式，kernel 侧写 `Param[I8]`。

## 4. 语言事实复测（v0.85.0 种子，`dawn 0.85.0 (selfhost) b1:df3d8115201d`）

10-06 报告的 §3.1 在 v0.82.0 上实测三条，另有撞名一条与常量命名一条。全部在当前工具链重跑，草稿在 scratchpad，不进仓库。
命令都是 `./bin/dawn run <目录或文件>` 或 `./bin/dawn check <文件>`。

1. **同模块同名类型 + 常量，一次 `use` 引入两者。** 两文件工程：`fmts.dawn` 里
   `pub opaque type BF16 = Float`、`pub opaque type Fmt[T] = String`、`pub const BF16: Fmt[BF16] = mkf("bf16")`；
   `main.dawn` 里 `use fmts.{BF16, Tile, mk, name}`，`let t: Tile[BF16] = mk(BF16)`，`println(name(BF16))`。
   输出 `bf16`，退出 0。（注：单模块内不能把 `Fmt` 写成带字段的和类型再 `.name`，那是另一个错，与本题无关。）
2. **返回位 trait 由期望类型选 impl，含 opaque 类型。** 用真 std：`use std/dtype.{Dtype, HasDtype, dtype_name, dtype_of}`、
   `use std/narrow.{BF16}`，泛型 `fn name_of[D: HasDtype](t: Tile[D]) -> String`，内部 `let f: Dtype[D] = dtype_of()`，
   对 `Tile[Float]`、`Tile[BF16]`、`Tile[Bool]` 各调一次。输出 `f64 bf16 i1`。
   另 `let d: Dtype[BF16] = dtype_of()` 后 `println("${dtype_name(d)} ${dtype_name(BF16)}")` 输出 `bf16 bf16`：类型位置的 `BF16` 与值位置的 `BF16` 来自同一条 `use std/narrow.{BF16}`。
3. **常量名必须 SCREAMING。** `pub const Float: Int = 1` 报
   `error: constant names are SCREAMING_SNAKE_CASE`（hint 指向 spec §1.3）。所以 `Float` 当不了自己的见证名，见证是 `F64`。
4. **`dtype_named` 是 `pub(pkg)`。** 用户程序 `use std/dtype` 后调 `dtype.dtype_named("mine")` 报
   ``error: `dtype_named` is package-private to package `std` ``，hint `only modules of package `std` may name it`。
   （直接 `use std/dtype.{dtype_named}` 更早报另一句「not a builtin」，是同一限制的另一个入口，不单列。）
5. **没有 `HasDtype` 的类型拿不到格式。** `use std/int/u32.{U32}`，`let d: Dtype[U32] = dtype_of()` 报
   ``error: `dtype_of` requires `HasDtype[U32]`, but `U32` has no such impl``。
   `gpu.alloc(U32, 4)` 则是 ``undefined constructor: U32``（`std/int/u32` 没有同名常量）。
   `let a: Result[Tensor[Float], ForeignError] = alloc(BF16, 2)` 报 `argument type mismatch: expected Dtype[Float], got Dtype[BF16]`，签名提示 `fn alloc[D](d: Dtype[D], len: Int) -> Result[Tensor[D], ForeignError] !Gpu`：传错格式是类型错误，不是运行期失败。
   同一个 `with_gpu_fake` 下 `alloc(BF16, 2)`、`alloc(F64, 2)`、`alloc(U8, 2)` 都 `Ok`，三个 `Ok` 计 3。
6. **撞名仍按本地名查，不分类别。** 两文件工程里 `use fmts.{BF16}` 加 `use std/narrow.{BF16}` 报
   ``error: `BF16` is imported more than once (from `fmts` and `std/narrow`)``，与 10-06 在 v0.82.0 上的文案一致。
   `use std/gpu.{BF16}` 现在报 ``module `std/gpu` has no exported name `BF16` ``：旧标记已不存在。
7. **#416（跨模块常量初始化调用函数）在当前种子里。** `scripts/seed-release.txt` = v0.85.0，`std/narrow` 的 `pub const BF16: Dtype[BF16] = dtype_named("bf16")` 就依赖它，且 `std` 全量在当前工具链上编过；上面第 1、2 条的真 std 路径即是证据。

## 5. spec §12.6 现状

spec §12.6（`docs/spec.md` 的「设备后端：GPU」）与英文译本已随 24d3fcd2 改写，不再有草案要出：

- 「**跨界的类型**」一节已写：`Tensor[D]` 的 `D` 是格式的值类型，`Tensor[Float]` 与 `Tensor[BF16]` 是两个类型；
  格式有 15 个（节里的计数含 `I4` 且不含 `I1`，因为 `I1` 不是缓冲格式，与本文 §2 的 16 个见证口径不同，两处不矛盾）；
  `U16 U32 U64` 没有，所以 `Tensor[U32]` 在 `alloc` 处是类型错误（见本文 §2 末行的精确说法，spec 这句是简写）。
- 一句话规则目前**没有**逐字写进 spec；散落在 `use std/narrow.{BF16}` 同时带来类型与见证那句里。是否把 §1 的规则句加进 §12.6 是 §7 的开放问题 3。

## 6. U3：类型化 `upload`/`download`

### 6.1 现状与目标

今天宿主值一律是 `List[Float]`：`gpu_upload(handle, data: List[Float])`、`gpu_download(handle) -> Result[List[Float], ForeignError]`，
native 的 `gpu_upload_host`/`gpu_download_host` 在 `selfhost/src/check/types.dawn` 里也是 `TyArray(TyFloat)`。对 `i64` 只在 ±2^53 内精确
（`std/gpu.dawn` 的格式注释与 `scripts/tile-gpu-diff/dtype_diff.dawn` 的 i64 语料明写了这条债，语料限制在 ±2^52 内）。
统一之后得到的前提是：`Tensor[T]` 的 `T` 已经是宿主值类型。目标：`upload(t: Tensor[T], data: List[T])`、`download(t) -> List[T]`，
`Tensor[U8]` 下得到 `List[U8]`，`Tensor[Int]` 下得到 `List[Int]` 且精确。

### 6.2 设计要点（待裁）

1. **编码从哪来。** `HasDtype` 只给名字，不给编解码。需要一个新 trait（暂记 `Pod[T]`：`to_bits`/`of_bits`，或直接 `Bytes` 读写），
   由各类型在自己的模块里 impl，与见证并排。`BF16 F16 F32 I8 I16 I32 U8` 的位型已有函数（`narrow.*_bits`、整数模块的 `wrap`）；
   只存储格式没有 `to_f64`（§3），但有 `*_bits`，所以编解码走位型而不走 `to_f64`。`F64`/`Int`/`Bool` 在 `std/dtype` 或 prelude 一侧 impl。
2. **线上走什么。** 走 `Bytes`，每个元素 `element_bytes` 字节、小端；`gpu_upload`/`gpu_download` 两个效果操作的签名随之改（`Bytes` 取代 `List[Float]`），
   native 运行时与 `gpu_*_host` 内建同步改。JVM 与 wasm 本来就答 `gpu.unsupported_backend`，只是类型签名变。
3. **假设备。** 现在缓冲存 `List[Float]` 并按名 `round_to`；U3 后参考实现（`WideRefFn`）仍可保持 `List[Float]` 通道（它是「参考」，不是设备），只在边界解码：
   这是 10-06 报告写的「参考实现通道仍是 `List[Float]`」，本文沿用，因为改它会动 `packages/tileref` 全部参考实现且没有收益。
4. **`download` 的返回格式不在 `Tensor` 的类型里的情形。** `Tensor[F32]` 可写不可分配，`download` 对它无从谈起，与现状同。

### 6.3 §12.6 要动的句子（U3 落地时）

只动这些：

- 「值以 `List[Float]` 进出，每种格式都是如此……对 `i64` 只在 ±2^53 之内精确」整条改写为：值以 `List[T]` 进出，`T` 是张量的元素类型；
  `upload` 把每个值编码成格式的位型（宽整数不再经 `Float`），`download` 精确答出；`i64` 的精确性债从此关闭。
- 「`upload` 的数据长度不等于 `size(t)`」的 `gpu.length_mismatch` 不变；`upload` 的舍入（`round_to`）一句改为「值在 `T` 里已经是该格式的值，`upload` 不再舍入」（`FromFloat`/`FromInt` 在构造时已舍入或范围检查）。
- 假设备「按缓冲格式舍入」一句同步。

本文不提前改 spec：规范文本在 U3 落地前动，会让规范领先实现。

### 6.4 刀与判词

| 刀 | 内容 | 破坏 | 判词（门禁） | 负控 |
|---|---|---|---|---|
| U3a | 设计稿：`docs/gpu-typed-transfer-design.md`（编码 trait 形状、线协议、native 运行时改动、`Gpu` 效果面、迁移量）；实测 `Bytes` 路径与现 `List[Float]` 路径的墙钟（性能断言要有出处） | 否 | 裁决 | — |
| U3b | std 增量：编码 trait 与各类型 impl；`upload_typed`/`download_typed` 暂以新名并存（只存在于这一刀与下一刀之间，U3c 同提交内收回，不留别名） | 否 | std 测试；`dawn doc`/LSP 同名语料不受影响 | 把某类型的 `of_bits` 少一个字节宽，其 round-trip 测试红 |
| U3c | 切换：`Gpu` 效果的 `gpu_upload`/`gpu_download` 改 `Bytes`；`upload`/`download` 收 `List[T]`；native 运行时；迁移 `tile-gpu-diff` 的 26 个驱动、`gpu_fake`、教程中英、spec §12.6、site gpu 页 | 是（std/gpu、`Gpu` 效果、native 运行时） | `dtype_diff` 的 i64 语料越过 2^53（例如 2^53+1 与 -2^62）逐位相等；tile golden 不变（不碰 tile 输入以外的路径，但 `std/gpu.dawn` 在 `TILE_PATHS`，所以 `inputs=` 摘要变，台账 verdict 不变、sm_86 重录、sm_90/sm_100 由所有者重录）；`Emit-Change` 逐 label；`selfhost-run-diff.sh` | ①把 `download` 解码改回经 `Float`，i64 语料在 2^53+1 红；②把 `upload` 的位型字节序写反，`dtype_diff` 红 |

U3 不碰 tileir 包本身（tileir 不引 `upload`/`download`），所以不需要 tileir 的 minor；若迁移期要动 `tileref`，随它自己的版本线。

## 7. U4：常量带宿主值类型

`f_const(d, v: Float)` 与 `full[D](shape, v: Float)` 今天收 `Float`，舍入发生在记录或渲染一侧。
U4 想要 `full[D: ..](shape, v: D)`：宿主侧的舍入（`let w: BF16 = 0.1` 已经是 `bf16(0.1)`，literal D7）在调用点可见，正对着 Triton #12102 那一类标量常量缺陷。
**未量**：`f_const(BF16, 0.1)` 今天记录的是 0.1 还是已舍入的值，渲染出的常量文本是否会因 U4 改变。U4a 的第一步就是量这个，结果决定 U4 动不动 tile golden。
`full` 的 `D` 需要从 `D` 取回 `Float`：`BF16 F16 F32` 有 `to_f64`（`Narrow`），只存储格式没有（§3），`Float` 自己是恒等；这条与 U3 的编码 trait 是同一个缺口，**U4 应排在 U3 之后，并复用 U3 的 trait**，而不是再造一个。

| 刀 | 内容 | 破坏 | 判词 | 负控 |
|---|---|---|---|---|
| U4a | 量：`f_const`/`full` 当前对 `BF16 F16 F32` 的 0.1 记录的是什么；设计稿 `docs/` 一篇（可并入 U3a 的稿） | 否 | 裁决 | — |
| U4b | tileir 0.13.0：`full`/`f_const`/`lit` 的值形参收 `D`；迁移 `scripts/tile-golden/kernels.dawn` 与 `tile-gpu-diff` 用到 `f_const(格式, 字面量)` 的约 183 处（字面量 `0.5` 按期望类型折叠成 `D`，多数写法不变） | 是（tileir，次版本） | tile golden 逐字节不变，除非 U4a 量出舍入位置不同（若变，逐个 golden 声明）；assemble | 把 `full` 的取值回 `Float` 路径换成不舍入，`BF16` 的 0.1 golden 变红 |

## 8. 开放问题（需要裁决）

1. U3 的编码 trait 放哪、叫什么：`std/dtype` 里与 `HasDtype` 并列，还是 `Dtype[T]` 本身携带编解码闭包（铸造处一次给齐）。后者让 `Dtype[T]` 变成「名字 + 编解码」，`pub(pkg)` 铸造的论证不变，且不新增 trait，但 `Dtype` 不再是 `String` 的薄包装。
2. 只存储格式没有 `to_f64`（trait 方法共享函数命名空间）：是否值得为此给 `Narrow` 之外起新名（如 `value_of`），还是 U3/U4 一律走位型。倾向走位型。
3. 是否把 §1 的一句话规则逐字加进 spec §12.6（以及 §2.5 的「没有调用点类型实参」附近加一条指回）。加了就要同时动 `docs/spec.en.md` 并重登记译本摘要。
4. U3 是否一并把 `Gpu` 效果的 `launch` 实参里的 `Word` 位型与 `upload` 的位型编码统一成一个 trait（K4 的 `ScalarDtype` 与 U3 的编码 trait 有重叠：二者都是「某类型的位型」）。倾向 U3a 设计稿里一并回答。
5. `Tensor[U32]` 目前类型层可写（§2 末行）。是否要让 `Tensor[D]` 的构造点（`alloc`）以外也拒绝，需要 `Tensor[D: HasDtype]` 类约束，而 opaque 类型的类型参数没有约束位置。不建议做，除非出现真实误用。

## 9. 不做的（理由）

1. **`pub alias F64 = Float`**（让 `Tile[F64]` 零迁移）：一个类型两个名字，悬停与诊断仍印 `Float`，读者要多记一层映射。迁移已完成，更没有理由。
2. **不要见证、只靠期望类型（a2）**：约 1400 处见证要改成标注，`p.to(BF16)` 的流式写法消失，Dawn 的局部推断在 K2.5 就已经逼出过额外标注。
3. **标记改名或挪模块（b）**：格式信息两份，迁移量约 3.5 倍，类型化传输还要关联类型手连。（现在是历史选项。）
4. **维持现状靠限定引入（c）**：撞名面扩到 6 个，类型化传输与 `Tensor[U32]` 的类型错误都做不了。
5. **给 `U16 U32 U64` 造设备格式**：方言没有无符号整数 tile 类型，不 impl `HasDtype` 才是诚实的。
6. **把 `Dtype` 放进 `narrow` 或 `gpu`**：narrow 不该依赖 gpu，整数模块也要用它，所以单独一个底层小模块。
7. **给旧标记写迁移提示或 `std/moved.txt` 条目**：没有外部消费者，旧名直接删；`std/moved.txt` 机制本身已于 10-07 撤销。
8. **为 U3 保留 `List[Float]` 的旧 `upload`/`download` 作别名**：破坏性变更不做兼容层，调用方（26 个驱动与示例）同提交迁完。
9. **改参考实现（`WideRefFn`）的 `List[Float]` 通道**：它是宿主参考而非设备，改了动 `packages/tileref` 全部参考实现且没有收益（§6.2 第 3 条）。
10. **让 `Tile[Float]` 与 `Tile[BF16]` 之间可隐式转换**：区分靠 `BF16` 是 opaque，转换用 `.to(BF16)`，这是统一的目的而不是代价。
