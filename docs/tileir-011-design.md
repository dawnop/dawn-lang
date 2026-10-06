# tileir 0.11 设计：一次破坏性发布，收齐四件已裁决的事

> 状态：**proposed**。2026-10-06 写成，范围与刀序可读；§9 的八个开放问题已于同日裁决并写入本文（改动处已同步），但整篇尚未经评审通过，动码前仍以各刀自己的验收为准。
> 实现按两个 PR 切（§7）：A（F0 + U1，纯增量，不动 tile 输入摘要，PR #590）、B（其余全部：S2 + L3 + M + U2 + R，含 kernel 迁移、`neg_inf` 换 `-INFINITY`、`FP16`→`F16` 与唯一一次台账重录）。A 已落地，见 §7。
> 它不引入新的语言特性，只把四条各自已有裁决的改动排进同一个 tileir 版本，并回答「谁先谁后、哪些必须同 PR、
> golden 靠什么证明没动」。四条的权威设计各在自己的文档：
> [staged-for-design.md](staged-for-design.md)（`for` + `var`）、[arith-operator-traits-design.md](arith-operator-traits-design.md)
> 与 [literal-system-design.md](literal-system-design.md)（运算符与字面量）、`std/dtype` 一线（格式与值类型统一，调研与裁决在维护者工作区
> research-format-types-unify-report-20261006，本文 §2.4 复述结论）。
> 现状基线：`origin/main` = 997e370b，`packages/tileir` 0.10.0（K2.5 已合：`mma[A, C: FloatDtype]`、`full`、`.to`、`.transpose`）。
> 本文所有计数都是在这个提交上用 `git grep` 与脚本数出来的，不含 `selfhost/src/embed` 与 `docs/history`；
> 正则计数有口径误差（注释行、字符串里的同名词），写的是「约」的地方就是这个意思，实现刀开工时要重数一遍。

## 1. 目标与非目标

目标：一个 kernel 写成

```dawn
var acc = zeros(o)
for j in d_range(0, N / BK) {
  let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), 0.0) * lit(INV_SQRT_D)
  acc = mma(softmax_p(s), load_at(v, [j]), acc * alpha)
}
```

而不是今天的 `carry` / `.get()` / `.set()` / `d_range` 闭包 / `mul(add(..))` 嵌套调用 / `neg_inf()` 手写常量 /
`Tile[F64]` 里的 `F64` 是一个与 `std/narrow` 同名却不同物的标记。

一次发布，一个版本号 0.11.0，一份迁移表。理由是 `kernels.dawn` 每个 kernel 的同一行里同时有循环、携带、算术、常量与格式拼写，
分四次破坏就是把同一批行改四遍、台账重录四次。K1+K2 一个 PR 栈、台账只重录一次的先例（ruling-tile-surface-09 第 5 条）就是这个理由。

非目标：

- 不动 Tile IR 方言、字节码写入器、渲染器、`lower` 指令表。目标是 `.mlir` 与 `.tilebc` 两个后端逐字节不变（§5）。
- 不做运行期标量参数 K4、不做 staged `if`（S3）、不做类型化 `upload`/`download`（U3）、不做常量带宿主值类型（U4）。各自另立。
- 不动编译器的任何规则（除 §6 点名的、可并行且不属于本版的一把小刀）。

## 2. 范围：五条改动

### 2.1 S2：`StagedIter` / `StagedVar` 的 tileir 实现

编译器侧 S1 已落地（staged-for-design §8）。本版只做库侧：

- 描述符类型与 `StagedIter` impl。终态拼写就是目标写法里的 `d_range`，且**只有一个**：
  `d_range[B: RangeBound](lower: B, upper: B, step: Step[B] = One, unsigned_cmp: Bool = false) -> DRange[B]`。
  `RangeBound` 是 tileir 里的小 trait（`range_idx(b) -> Idx !Dev`），`Int`（宿主边界，录制时固定，转成 `idx_const`）与 `Idx`（设备边界，原样）各给一个 impl；
  今天闭包形式的 `d_range`（Int 界）与 `d_for`（Idx 界）因此合成一个名字，`unsigned_cmp` 一个不少，IR 与 golden 不变（裁决补充 9）。
  **`Item = Idx`**（原稿写 `Item = B`，是错的：循环体吃 `Idx`，`load_at` 也吃 `Idx`，`Int` 界的循环变量同样是 `Idx`）。
  **步长是独立的小类型 `pub type Step[B] = One | By(by: B)`**（ruling-drange-step-20261006）：原定 `step: B = 1` 写不出来，
  因为默认值必须纯（spec 默认值一节），泛型 `B` 上的字面量要 `B.FromInt` 证据，且 `Idx` 的常量 1 是 `idx_const(1)`，会记一条 op。
  默认 `One` 是纯构造器，循环开始时才降成常量 1（`Idx` 界在 kernel 的 `!Dev` 里记 op）；字面量步长写 `step: By(2)`，设备步长（网格步进、持久化 kernel）写 `step: By(nprog)`
  （Triton 的 `tl.range(row_start, n_rows, row_step)` 同形）。没有给 `Step[B]` 实现 `FromInt`：prelude 的 `from_int` 不可按名调用，条件 impl 无法把字面量转交给 `B`，所以 `step: 2` 不成立，不加特例。
  名字 `Step`/`One`/`By` 在 tileir 里查过无冲突；`Unit` 是内建类型名，不能当构造器，故用 `One`。构造器字段必须具名，故 `By(by: B)`，写 `By(x)` 位置传参照常。
  不引入 `d_span`；`d_for` 在 0.11.0 **直接删除**，不留别名。闭包形式的 `d_range` 在 0.11.0 变成同名的描述符，
  调用方同一版内一次迁完（S2 刀同一提交内完成，没有用到临时名）。`effect StagedIter = !Dev`，
  `staged_for` 的体调用今天的区域栈记录机制，
  所以 `For` 的降低、渲染、字节码一行不改。
- `impl[D] StagedVar[Tile[D]]`：`type Cell = Carry[D]`，`var_open(v) = carry(v)`，`var_get(c) = get(c)`，`var_set(c, v) = set(c, v)`，`effect StagedVar = !Dev`。
  泛型 blanket impl 已在 main 上实测可用（research-generic-kernel-report §1.2），`generic_carry` 那条限制不放宽（ruling-generic-kernel 第 1 条，没有真实消费者）。
- `carry` / `get` / `set` / `Carry[D]` 保持公开。`d_loop` 的体是无参闭包加数据相关退出，staged 第一刀不支持 `break`/`return`（staged-for-design D7），
  所以 `d_loop` kernel 与 `prog.dawn` 里的低层记录函数继续用 `carry`。
- `kernels.dawn` 迁移：见 §4 与 §3.1。
- 已知开放项（staged-for-design §7.1）：`var_open` 走 `carry`，而 `carry` 拒无格式初值，所以 `var m = lit(0.0)` 不行；
  初值写 `full(..)`（K2.5 起由类型定格式）或 `zeros(p)`。迁移不需要 `lit` 作初值，因为 `kernels.dawn` 里今天就没有。

### 2.2 L3：Tile 与 Idx 上的运算符与字面量 impl

按 literal-system-design D12 与 arith-operator-traits-design，本版把 impl 写在 tileir（孤儿规则要求写在 `Tile`/`Idx` 的声明模块）：

| impl | 体 | 效果 |
|---|---|---|
| `impl[D] Add[Tile[D]]`、`Sub`、`Mul`、`Div` | `add`、`sub`、`mul`、`div`（默认 rounding 与 ftz） | `!Dev` |
| `impl[D] Neg[Tile[D]]` | `neg` | `!Dev` |
| `impl[D] FromFloat[Tile[D]]` | `lit(x)` | `!Dev` |
| `impl Add[Idx]`、`Sub`、`Mul`、`Div`、`Rem` | `idx_add`、`idx_sub`、`idx_mul`、`idx_div`、`idx_rem` | `!Dev` |
| `impl FromInt[Idx]` | `idx_const(n)` | `!Dev` |

要点与取舍：

- **Tile 的运算符 impl 是浮点的。** 今天 `add[D]` 对任何 `D` 都发 `addf`，整数 tile 另有 `add_i`/`sub_i`/`mul_i`/`div_i`/`neg_i`（只收 `Tile[I32]`）。
  `impl[D] Add[Tile[D]]` 与 `impl Add[Tile[I32]]` 会重叠，条件 impl 不可写（arith D5），所以 `Tile[I32]` 的运算符**不给**，`kernels.dawn` 里的 `*_i` 调用（64 处）保持函数形。
  这是一个有牙的限制，不是疏漏；风险见 §8.1。
- 不给 `FromInt[Tile[D]]`：`t * 2` 报错，写 `t * 2.0`（literal D12 原文）。`FromFloat[Tile[D]]` 让字面量 `2.0` 在 `Tile[D]` 一侧自动成 `lit(2.0)`。
- 具名常量不是字面量（literal D3）。`t * ATT_INV_SQRT_D` 仍是类型错误，写 `t * lit(ATT_INV_SQRT_D)`。`kernels.dawn` 里这种写法约 3 处具名加 2 处宿主变量（`lit(step)` 一类），`lit` 因此保留（ruling-arith-literal-final 第 3 条）。
- 比较、`max`/`min`、`exp` 等不是运算符，保持函数。
- 判词：**tile-golden 逐字节零变化**。每个 impl 的体就是今天那个函数调用，记录出的指令序列相同。

### 2.3 F0：`INFINITY` / `NAN`，取代 `neg_inf()` / `ref_neg_inf()`

今天的 `neg_inf()` 是 `kernels.dawn:198` 的 `fn neg_inf() -> Float = 0.0 - 1.0 / 0.0`，`ref_neg_inf()` 是 `packages/tileref/src/ref.dawn:2005` 的同一行；
两份各自为政，原因是 std 没有这两个值。本版由 std 提供 `pub const INFINITY: Float` 与 `pub const NAN: Float`，负无穷写 `-INFINITY`（一元 `-` 在 `Float` 上是原生快路，字节不变）。

- 计数：`kernels.dawn` 定义 1 加调用 9 处（`f_const(F64, neg_inf())` 6、`full(.., neg_inf())` 2、`d_reduce2(.., neg_inf(), ..)` 1）；`ref.dawn` 定义 1 加调用 8 处；
  文档里 `neg_inf()` 出现在 tileir README 1 处、tutorial 与译本各 3 处、tile-backend-design 3 处、std-defaults-design 1 处。
- `NAN` 今天没有任何消费者（view 的 `PadNaN` 是枚举，不是值）。它随 `INFINITY` 一起进是裁决的要求，意义是 `x != x` 之外第二个说得出 NaN 的办法。
  风险（§8.4）：编译期求值 `0.0 / 0.0` 在两个后端是否产出同一个 NaN 位型，实现刀必须测。
- 住在新模块 `std/float`（裁决，§9 Q1）：不在 tile 路径上，F0 不触发 `tile.yml`；`MAX`、`EPSILON`、`is_nan` 以后同处。负无穷写 `-INFINITY`，不另给 `NEG_INFINITY`。kernels 与 `tileref` 加 `use std/float.{INFINITY}`（这一步属 PR B：两处都在 tile 路径上；PR A 只加模块）。`std/float` 是新 std 文件，要进 `std/modules.txt` 并过 `gen-stdsrc`（嵌入的 stdsrc 随之变，Emit-Change 与 core-golden 同 §6.2）。

### 2.4 U1 + U2：格式统一

结论复述（依据见维护者工作区调研报告；本文不重做调研，只记结论与我复核过的事实）：

- 今天 `std/gpu` 有 15 个**格式标记** `F64 F32 BF16 I32 F16 I8 U8 I16 I64 TF32 F8E4M3FN F8E5M2 F8E8M0FNU I4 F4E2M1FN`（单构造子 ADT，类型位置当 `Tensor[D]`/`Tile[D]` 的幻影参数，值位置当见证），
  tileir 另有一个 `I1`。`std/narrow` 有宿主值类型 `BF16`、`FP16`、`F32`；定宽整数（`std/int/i8` 到 `u64`，待合并）有 `I8 I16 I32 U8 U16 U32 U64`。
  两边同名不同物：`BF16`、`F32` 今天就撞，定宽整数合入后再撞 `I8 I16 I32 U8`。今天仓内没有一个文件同时引入两边，所以是潜伏的；字面量系统落地后，
  「同一个模块既要宿主值 `BF16` 又要设备格式 `BF16`」会变成常态。
- 根因是 Dawn 没有调用点类型实参（spec §2.5），要在调用点点名一个格式只能传一个值。`std/gpu.dawn:36-42` 与 tile-backend-design §3 (288-292 行) 里
  「不复用 narrow 类型」的理由是「那样 `alloc(narrow.bf16(0.0), n)` 得造一个值当标签」。这条理由在下面的方案里**不再成立**，本版要明写它被推翻了。
- 方案 a1（同名见证常量）：
  - 新模块 `std/dtype`：`pub opaque type Dtype[T] = String`（只能由 std 铸造，`pub(pkg)` 构造函数）、`pub fn dtype_name[T](d: Dtype[T]) -> String`、
    `pub trait HasDtype[T] { fn dtype_of() -> Dtype[T] }`（`T` 只出现在返回位，由期望类型选 impl），以及三个内建见证
    `pub const F64: Dtype[Float]`、`pub const I64: Dtype[Int]`、`pub const I1: Dtype[Bool]`。
  - 每个值类型在自己的声明模块里一次声明类型、同名 SCREAMING 见证常量、`HasDtype` impl：`std/narrow` 的 `BF16`、`F16`（`FP16` 改名）、`F32`，
    `std/int/i8`、`i16`、`i32`、`u8` 的 `I8 I16 I32 U8`。`TF32`、`F8E4M3FN`、`F8E5M2`、`F8E8M0FNU`、`F4E2M1FN` 作为只存储值类型进 `std/narrow`
    （`FromFloat`、`to_f64`、`Show`，无算术）；`I4` 作为只存储类型留在 `std/gpu`。`U16`、`U32`、`U64` 不 impl `HasDtype`：方言没有无符号整数 tile 类型。
  - 一次 `use std/narrow.{BF16}` 同时拿到类型与见证，所以 `alloc(BF16, n)`、`In(BF16, ..)`、`p.to(BF16)`、`f_const(BF16, 0.5)`、`param(BF16, 0)` 的**见证拼写一个字不变**；
    变的只有引入行，以及内建三种的**类型位置**：`Tile[F64]` 写成 `Tile[Float]`，`Tile[I64]` 写成 `Tile[Int]`，`Tile[I1]` 写成 `Tile[Bool]`。
    见证常量仍叫 `F64`、`I64`、`I1`（常量名必须 SCREAMING，`Float` 当不了常量名，调研里实测过）。
  - 规则一句话：**类型位置写值类型，值位置写格式名；两者对 narrow 与定宽整数同名，对内建三种是 `Float`/`F64`、`Int`/`I64`、`Bool`/`I1`。**
  - 语言事实（调研在 v0.82.0 种子上实测，我复核了依赖的修复）：同模块的 `pub opaque type X` 与 `pub const X` 并存且 `use m.{X}` 同时引入两者；返回位 trait 由期望类型选 impl；
    跨模块常量初始化调用其他模块函数依赖 #416（修复 c89862ac，已在当前种子 v0.85.0 内）。不需要编译器改动。
- **U1**：建 `std/dtype`，给 `std/int` 的 `I8 I16 I32 U8` 与内建三种加见证与 impl（PR A，纯增量）；给 narrow 加见证与 impl、加只存储类型、`FP16` 改名 `F16`（PR B，因为 `std/narrow.dawn` 是 tile 输入，见 §7）。`std/gpu` 的旧标记此刻原样保留（它整模块 `use std/narrow`，用限定名，不撞）。
- **U2** 是一次性切换：删 `std/gpu` 的 15 个标记（`I4` 例外）与旧 `Dtype` trait（`dtype_name(d: D)`），`alloc`/`module_global` 收 `Dtype[T]`；tileir 删 `I1`，
  `Param/Ptrs/TensorView/GridView/GatherScatterView/Tile/Arg` 的参数改成值类型，`param`/`f_const`/`to`/`unpack_bytes`/`float_to_float` 等收 `Dtype[B]`（不再带 trait bound）。

### 2.5 mma 与 full 如何从类型拿格式

K2.5 的 `FloatDtype[D]`（`fn float_dtype() -> D`，`float_name`）已经独立走到「只在返回位出现 `D`，由期望类型选 impl」这一步，a1 只是把它答的东西从标记值换成 `Dtype[D]`：

```dawn
pub trait FloatDtype[D] { fn float_dtype() -> Dtype[D] }      # float_name 由 dtype_name 取代
impl FloatDtype[Float] { fn float_dtype() -> Dtype[Float] = F64 }
impl FloatDtype[F32]   { fn float_dtype() -> Dtype[F32]   = F32 }   # narrow 的 F32，七个算术浮点各一
```

- `mma[A, C: FloatDtype](a: Tile[A], b: Tile[A], acc: Tile[C]) -> Tile[C]`、`full[D: FloatDtype](shape, v: Float) -> Tile[D]`：**签名拼写不变**，
  `D` 与 `C` 仍由期望类型或实参类型定。变的是 impl 体与 `Tile[F32]` 里 `F32` 指哪个类型。
- 保留 `FloatDtype` 而不是直接用 `std/dtype.HasDtype`：mma 的组合表只收七个算术浮点，`f8E8M0FNU` 与 `f4E2M1FN` 没有算术（K2.5 报告）；
  用 `HasDtype` 会把整数与只存储格式放进 `full` 的约束，错误从类型错误退成运行期记录拒绝。
- `.to(fmt)`：`to[A, B](a: Tile[A], fmt: Dtype[B]) -> Tile[B]`，`p.to(BF16)` 拼写不变，`BF16` 在值位置是 `Dtype[narrow.BF16]`，不再需要 `B: Dtype`。
- `lit` / `FromFloat[Tile[D]]` 不带格式，在使用处定格式，与 `D` 是什么类型无关，不受影响（调研 §3.1）。

## 3. 目标写法

### 3.1 flash_attn

`scripts/tile-golden/kernels.dawn:2176`（今天，0.10.0）：

```dawn
fn flash_attn(q: Param[F64], k: Param[F64], v: Param[F64], o: Param[F64]) -> Unit !Dev = {
  let tq = load_cell(q)
  let m: Carry[F64] = carry(full([FA_BQ, 1], neg_inf()))
  let l: Carry[F64] = carry(full([FA_BQ, 1], 0.0))
  let acc = carry(zeros(o))
  d_range(0, ATT_N / FA_BK) { j =>
    let s: Tile[F64] = mul(mma(tq, load_at(k, [j]).transpose(), lit(0.0)), lit(ATT_INV_SQRT_D))
    let m_new = max(m.get(), reduce_max(s, keepdims: true))
    let p = exp(sub(s, m_new))
    let alpha = exp(sub(m.get(), m_new))
    l.set(add(mul(l.get(), alpha), reduce_sum(p, keepdims: true)))
    acc.set(mma(p, load_at(v, [j]), mul(acc.get(), alpha)))
    m.set(m_new)
  }
  store_cell(o, div(acc.get(), l.get()))
}
```

0.11.0（目标）：

```dawn
fn flash_attn(q: Param[Float], k: Param[Float], v: Param[Float], o: Param[Float]) -> Unit !Dev = {
  let tq = load_cell(q)
  var m: Tile[Float] = full([FA_BQ, 1], -INFINITY)
  var l: Tile[Float] = full([FA_BQ, 1], 0.0)
  var acc = zeros(o)
  for j in d_range(0, ATT_N / FA_BK) {
    let s: Tile[Float] = mma(tq, load_at(k, [j]).transpose(), 0.0) * lit(ATT_INV_SQRT_D)
    let m_new = max(m, reduce_max(s, keepdims: true))
    let p = exp(s - m_new)
    let alpha = exp(m - m_new)
    l = l * alpha + reduce_sum(p, keepdims: true)
    acc = mma(p, load_at(v, [j]), acc * alpha)
    m = m_new
  }
  store_cell(o, acc / l)
}
```

逐条说明（这些是裁决要求的性质，不是我新加的）：

- 携带序 = `var` 的声明序 `m, l, acc`，与今天 `carry` 的创建序相同；赋值位置序是 `l, acc, m`，**不同**。这正是 staged-for 裁决里
  「按赋值位置排序使 flash_attn 变红」的负控所对的东西：若实现把携带序错成赋值序，`For` 的迭代参数顺序变，golden 红。
- `mma(tq, .., 0.0)`：`0.0` 作为 `acc: Tile[C]` 的实参，期望类型由 `let s: Tile[Float]` 经返回类型传到 `C`，`FromFloat[Tile[Float]]` 把它折成 `lit(0.0)`。
  这依赖「标注 `s` 的类型」（K2.5 已有这条标注，今天就是为 `lit` 累加器定格式而加），不依赖字面量推断新能力。
- `* lit(ATT_INV_SQRT_D)`：具名常量不是字面量，`lit` 保留（§2.2）。若写成 `* 0.17677669529663687` 则 `lit` 也可省，但 kernel 里命名常量更清楚，本文不改常量。
- 初值 `-INFINITY`：`full(shape, v: Float)` 的 `v` 是宿主 `Float`，`-INFINITY` 是 `Float` 的一元负，原生快路。
- `flash_attn_bf16` 同形：`var m: Tile[F32] = full(.., -INFINITY)`、`p.to(BF16)`、结果 `(acc / l).to(F64)` 末尾的 `F64` 是见证（类型 `Dtype[Float]`），拼写不变。
  `Param[BF16]` 里的 `BF16` 此后是 `std/narrow.BF16`。

### 3.2 matmul（最短的循环携带）

```dawn
# 今天（kernels.dawn:393）
let acc = carry(zeros(c))
d_range(0, MM_K / MM_TK) { k => acc.set(mma(load_at(a, [k]), load_at(b, [k]), acc.get())) }
store_cell(c, acc.get())

# 0.11.0
var acc = zeros(c)
for k in d_range(0, MM_K / MM_TK) { acc = mma(load_at(a, [k]), load_at(b, [k]), acc) }
store_cell(c, acc)
```

这个形状在 `kernels.dawn` 里出现约十五次（`matmul`、`mmf`、`mmi`、`lora`、`attn_context`、`gp_*` 一族），是迁移量最大的一类，也最机械。

### 3.3 sum（Idx 界、Idx 运算符、字面量）

```dawn
# 今天（kernels.dawn:68）
let b = block_id(0)
let n = idx_const(chunks)
let base = idx_mul(b, n)
let first = load_at(x, [base])
let one = idx_const(1)
let lo = idx_add(base, one)
let up = idx_add(base, n)
let total = carry(first)
d_for(lo, up, one) { k => total.set(add(total.get(), load_at(x, [k]))) }
store_cell(out, total.get())

# 0.11.0
let b = block_id(0)
let n: Idx = idx_const(chunks)           # chunks 是宿主变量，不是字面量，idx_const 保留
let base = b * n
var total = load_at(x, [base])
for k in d_range(base + 1, base + n) { total = total + load_at(x, [k]) }
store_cell(out, total)
```

字面量 `1` 在 `Idx` 一侧经 `FromInt[Idx]` 定型。`idx_const(chunks)` 这类宿主变量参数的调用保留，`kernels.dawn` 里 `idx_const(<名字>)` 93 处不动，
`idx_const(<整数字面量>)` 114 处在 Idx 运算或 Idx 形参位置上可以删。

### 3.4 `attn_causal`（`neg_inf` 与 select）

```dawn
store_cell(s, select(allowed, v, f_const(F64, neg_inf())))     # 今天
store_cell(s, select(allowed, v, f_const(F64, -INFINITY)))     # 0.11.0
```

`F64` 在这里是见证，`Dtype[Float]`，不变。同形的 `f_const(F64, neg_inf())` 共 6 处（`attn_causal` 一族的掩码、`lm_*`、局部量 `ninf`）一并改。

## 4. 迁移计数（实测）

测量对象 `origin/main` 997e370b。「行」指含该记号的非注释行或匹配次数，口径见各行。

### 4.1 `scripts/tile-golden/kernels.dawn`（5941 行，269 个函数）

| 改动 | 范围 | 计数 |
|---|---|---|
| S2 循环 | `d_range(` 调用 27，`d_for(` 调用 9 | 36 个循环，另有 `d_loop` 5（不动） |
| S2 携带 | `carry(` 共 50 处、分布在 37 个函数 | 其中 33 个函数 43 处迁 `var`（带 127 处 `.get()`/`.set(` 提及）；`d_loop` 的 4 个函数 7 处 `carry` 保留 |
| L3 Tile 运算 | 裸调用 `add(` 23、`sub(` 13、`mul(` 48、`div(` 9、`neg(` 7 | 100 处改运算符；`max`/`min` 30 处保留 |
| L3 Idx 运算 | `idx_add` 61、`idx_mul` 61、`idx_sub` 3、`idx_div` 3、`idx_rem` 3 | 131 处改运算符 |
| L3 字面量 | `idx_const(<整数字面量>)` 114；`lit(<字面量>)` 5；`f_const(格式, <字面量>)` 77（共 122 处 `f_const`） | `f_const` 在非 `lit` 路径上不删（它是带格式的见证调用），不计入迁移 |
| F0 | `neg_inf` 定义 1，调用 9 | 10 |
| U2 类型位置 | `Tile/Param/Ptrs/Tensor/Carry/…[F64]` 449（该文件），`[I64]` 4，`[I1]` 2 | 455 |
| U2 引入行 | `use std/gpu.{…}` 一行变多行（`std/dtype`、`std/narrow`、`std/int/*` 各一） | 1 个导入块 |

### 4.2 全仓

| 改动 | 位置 | 计数 |
|---|---|---|
| U2 类型位置（`.dawn`，16 个文件） | `[F64]` 602、`[I64]` 12、`[I1]` 61 | **675** |
| 同上，按文件 | `kernels.dawn` 449；`tileir/prog.dawn` 60；`render.dawn` 20；`dev.dawn` 6（F64）加 59（I1）加 7（I64）；`gpu_fake` 18；checker-corpus 与 opaque-twin 17；`tile-gpu-diff` 四个程序各 4；`std/gpu` 9；`gpumap` 2 | 同上 |
| U2 类型位置，拼写不变的格式 | `[I32]` 235、`[F32]` 46、`[I8]` 19、`[F16]` 15、`[BF16]` 10 与其余小项 | 约 350，只改 import |
| U2 见证位置（裸出现，非类型实参） | `F64` 约 1004、`I32` 约 140、`F32` 约 83、`BF16` 约 54、`F16` 约 37、`U8` 约 27 | 约 1400，拼写不变，只改 import；`FP16` 22 个改成 `F16` |
| `use std/gpu` 的文件 | 33 个 `.dawn`（`kernels.dawn`、tileir 三个源文件、`tileref`、`gpu_fake`、26 个 `tile-gpu-diff` 程序、`phantom_opaque`） | 33 个引入块 |
| `FP16`/`fp16` 改名 `F16` | 163 行，17 个非文档非生成物文件（`std/narrow` 59、`spike-native` 61、`examples/data/narrow.dawn` 13、play-ui 样例 6、`ref.dawn` 3 等）；文档 13 行；`embed/stdsrc` 由生成器重出 | 约 176 |
| `[D: Dtype]` / `FloatDtype` 约束 | `dev.dawn` 15、`prog.dawn` 7、`std/gpu` 3、`vadd_diff` 2、CHANGELOG 1 | 约 28 |
| S2 全仓 | `prog.dawn` 的 `d_range(`/`d_for(` 17 与 `carry(` 23（包内联测试）；`gpu_fake` `carry(` 2；`gpumap` 2 | 约 44，其中 `prog.dawn` 里属于低层记录函数的不迁 |
| F0 全仓 | `ref.dawn` 定义 1 调用 8；kernels 10；README 1 | 20 个代码点 |

文档（U2 的类型位置，`[F64|I64|I1]` 实参）：`tutorial.md` 36、`tutorial.zh-CN.md` 36、`spec.md` 5、`spec.en.md` 5、`tile-backend-design.md` 10、tileir README 7、CHANGELOG 1，
及本批设计稿（literal 3、arith 1）。教程先改英文再改中文，doc-check 的 translation-of 摘要要重登记（CLAUDE.md「对外那一层」）。spec 与 spec.en.md 同步改（先中文再英文）。

## 5. 破坏清单与调用者要做的事

### 5.1 tileir 0.11.0 的破坏（公开面）

| 破坏 | 迁移 |
|---|---|
| `Tile[F64]` / `Param[F64]` / `Tensor[F64]` 等类型位置的 `F64`、`I64`、`I1` | 改 `Float`、`Int`、`Bool`；见证（`param(F64, 0)`、`In(F64, ..)`、`f_const(F64, ..)`、`alloc(F64, n)`）不变 |
| 格式标记不再来自 `std/gpu` | `BF16 F32 F16 TF32 F8*` `F4E2M1FN` 改 `use std/narrow.{..}`；`I8 I16 I32 U8` 改 `use std/int/i8.{I8}` 等；`F64 I64 I1` 改 `use std/dtype.{..}`；`I4` 仍在 `std/gpu` |
| `std/gpu.Dtype` trait（`dtype_name(d: D)`）与 15 个 `impl` 删除 | `std/dtype.Dtype[T]` 是一个值类型，名字 `dtype_name(d)` 保留；自写 `impl Dtype[..]` 的调用者要改写（预期为零，今天无外部实现） |
| `alloc`、`module_global` 的参数由「任意标记值」改为 `Dtype[T]` | 传同名见证常量即可；传 `U16`/`U32`/`U64` 的 `Tensor` 从「能写」变成类型错误（它们没有 `HasDtype`） |
| `narrow.FP16`、`fp16()`、`round_fp16`、`fp16_bits`、`fp16_of_bits` | 改 `F16`、`f16()`、`round_f16`、`f16_bits`、`f16_of_bits`（std 公开面破坏，随承载它的编译器 release 一起发） |
| tileir 删 `I1` 类型与 `impl Dtype[I1]` | `Tile[Bool]`；见证 `I1` 来自 `std/dtype` |
| `FloatDtype::float_dtype` 的答案类型 `D` 改为 `Dtype[D]`，`float_name` 删除 | 自写泛型 kernel 的 `[D: FloatDtype]` 约束不变；读 `float_name(d)` 的改 `dtype_name(float_dtype())` |
| 闭包形式的 `d_range(lo, hi) { i => .. }` 被同名描述符取代；`d_for(lo, hi, step) { i => .. }` 删除，并入 `d_range`（`B: RangeBound`，Int 与 Idx 各一个 impl，步长是 `Step[B] = One | By(by: B)`；§9 Q2，无别名） | `for i in d_range(lo, hi) { .. }`；原 `d_for` 调用改 `d_range`（边界是 `Idx` 即得 Idx 版）；体内的外层 `Carry` 改 `var` |
| `neg_inf()` 一类自写常量 | 由 `-INFINITY` 取代（它们本来就不在 tileir 的公开面，是 kernels/ref 里的私有函数） |

旧名（`std/gpu` 的 `F64` 等标记、`Tile[F64]`、`FP16`）**不给迁移提示**：`std/moved.txt` 不扩展到类型名，不加弃用别名。仓内没有别的消费者，U2 直接删旧名，调用方由编译错误引到新写法（§9 Q5）。

不破坏：`carry`/`get`/`set`/`Carry` 保持公开；所有算术函数名（`add`、`mul`、`max` 等）保持，运算符是加法；`lit` 保持；
所有 kernel 的行为与 `.mlir`/`.tilebc` 输出不变。

### 5.2 最低编译器版本

tileir 0.11.0 依赖：S1（`StagedIter`/`StagedVar` 改写）、运算符 trait 与 L1 字面量（已发的 release）、U1 的 `std/dtype` 与 narrow/int 见证、F0 的 `INFINITY`/`NAN`。
CHANGELOG 的第一行写明承载这些的最小 dawn 版本；发版顺序见 §7，先发承载 std 改动的编译器 release，再发 tileir 0.11.0。

### 5.3 谁受影响

仓内：`kernels.dawn`、`packages/tileir`、`packages/tileref`、`examples/projects/gpu_fake`、`scripts/tile-gpu-diff` 的 26 个程序、`scripts/checker-corpus`（`phantom_opaque`、`arith_ops_opaque`、`literals`）、
`scripts/opaque-twin`、`site/src/gen/gpumap.dawn` 与 `site/gpu-map/flash_attn.map`、教程与 spec。仓外：dawnop-site 按 `.dawn-version` 钉 release，是否用到 tileir 或 `std/narrow` 的 `fp16` 没有核实（开工前 grep 一次），升钉时自己迁。

## 6. golden 策略

### 6.1 必须逐字节不变的

- `scripts/tile-golden` 的全部 `.mlir` 与 `.tilebc`（今天 195 个 kernel，K2.5 报告的数字），**JVM 与 native 两个后端**都不变。
  依据：渲染与编码只经 `dtype_name` 的字符串，名字一个不变；运算符与 `for` 在检查器里改写成与今天相同的调用（TAST 层）；`INFINITY` 是同一个双精度值。
- 台账判词：`ledger.txt`（sm_86）、`ledger-sm90.txt`、`ledger-sm100.txt` 的 verdict 与各族计数不变，变的只有 `inputs=` 摘要。
- tileiras 汇编仍全部通过，cubin 不要求比较（汇编输入字节相同，所以输出相同；不单独断言）。

### 6.2 会动的

| 项 | 为什么动 | 怎么处理 |
|---|---|---|
| `std/stdsrc` 嵌入与 std 的 JVM 类 | U1/U2/F0 改了 std 源 | `emit *` 一族标签（`scripts/emit-labels.txt` 的 10 个 `emit` 行，加 `doc --builtins`、`doc site`）预计命中；以 `selfhost-prev-diff.sh` 与 `selfhost-run-diff.sh` 的**实际输出**为准，逐 label 写 `Emit-Change(<label>): …`，不接受通配 |
| Core IR | std 公开面改了 | 树里已不存的 core-golden（`scripts/core-golden/` 已删，`selfhost-core-diff.sh` 是按需对比两个 revision 的工具，不是门禁），没有要重录的东西；需要时贴 `selfhost-core-diff.sh` 的输出做证据 |
| checker-corpus | `imports.expected`、`phantom_opaque`、`arith_ops_opaque`、`literals` 里的 `Tile[F64]` 与导入 | 重录并核对差异只有拼写 |
| `site/gpu-map/flash_attn.map` | 调用名与列位置整体变（`mul(`→`*`，`d_range`→`for`） | 重录，核对调用数 37 降到更低的新数 |
| 教程与 spec 中英的摘要 | 文档改 | `doc-check.py` 重登记 |
| tile 台账 `inputs=` | TILE_PATHS 命中 | sm_86 本机重录一次；sm_90、sm_100 由所有者在集群重录（既有惯例，K2.5 报告「未做」栏同） |

### 6.3 变异体（证明检查有牙）

「绿」不是证据，只有变异体能分「没漏」与「没看」。tile-golden 的既有 273 个变异体（K2.5 报告）全部仍须红。**每把刀另加至少一个本刀专属变异体，且要先证它会红再合并**：

| 刀 | 变异体 | 预期 |
|---|---|---|
| S2 | `StagedVar` 的携带序按赋值位置排序（裁决点名） | `flash_attn` 的 golden 红 |
| S2 | `staged_for` 的体少打开一个格子（漏掉体内只读不写的 `m`） | `flash_attn` 红 |
| S2 | `d_range` 的 `unsigned_cmp` 实现忽略 | `attr_ucmp` 红 |
| L3 | `Sub[Tile[D]]` 的体调 `add` | 含 `sub` 的 kernel 红（`flash_attn` 的 `s - m_new`） |
| L3 | `Neg[Tile[D]]` 的体调恒等 | 含 `neg` 的 kernel 红 |
| L3 | `Rem[Idx]` 体调 `idx_div` | `idx_softmax` 红 |
| L3 | `FromFloat[Tile[D]]` 体调 `lit(x + 1.0)` | 含字面量 tile 的 kernel 红 |
| F0 | `INFINITY` 定义成 `1.0 / 0.0` 的负，或 `-INFINITY` 换成 `INFINITY` | `attn_causal` 与 `flash_attn` 红 |
| U2 | `std/narrow` 的 `BF16` 见证名改成 `"f16"` | `vadd_bf16`、`flash_attn_bf16` 红（调研的原话） |
| U2 | `impl HasDtype[Float]` 答 `"f32"` | 几乎全红 |
| U2 | `FloatDtype[F32]` 答 `"f64"` | `flash_attn_bf16` 红 |

还要一条**反向**的检查，防止「全绿只因为迁移没发生」：迁移完成后加一个计数断言（`kernels.dawn` 中 `d_range(`、`d_for(`、`neg_inf`、非 `d_loop` 函数里的 `carry(`、`[F64]` 为零），
并用一个把旧写法塞回一处的变异体证明这条断言会红。落点倾向 `scripts/tileir-features/check.py` 或 `scripts/tile-golden/run.sh` 的头部检查，具体由 M 刀定。

### 6.4 不跑什么

本文所在刀（Z0）只写文档，不跑 GPU、不跑重门禁。实现刀的验收门沿用 K2.5 的清单：`scripts/tile-golden/run.sh` 全量（约 3100 s）、`tile-gpu-diff --dry`（约 1900 s）、
`dawn test packages/tileir`/`tileref`/`site`、`examples/projects/gpu_fake`、`doc-check.py`、`site/gpu-map/record.py`、`pub-doc-check.py`、
`mutation-anchor-preflight-test.py`、`tileir-features/check.py`、`leetgpu-diff/check.py`、`dawn fmt … --check`；加上 `gate-map` 对每个改动路径列出的门。
墙钟影响要报（改门禁必报），本版不改 workflow，预期为零。

## 7. 刀序、依赖与 PR 切分

外部前置（本版之外，已合或在途）：std 定宽整数（`std/int/*`，待合）、#416（已在种子）、S1、运算符 trait、L1（已合）、K2.5（已合，#574）。

| 刀 | 内容 | 依赖 | 破坏 | 打包 |
|---|---|---|---|---|
| Z0 | 本文 | 无 | 否 | 单独一个文档 PR |
| C0 | 编译器小刀：二元运算左操作数接收期望类型（ruling-generic-kernel 第 2 条，约 5 行；已实现，改写运算符设计 D7，见 arith-operator-traits-design D7） | 无 | 否 | **单独 PR**，可与一切并行；不阻塞 tileir 0.11（本版写法 `lit(2.0) * t` 的需求不在目标写法里），属于「可与 S2 并行」那把 |
| F0 | 新模块 `std/float`：`INFINITY`/`NAN`（`neg_inf()` 的迁移不在本刀，归 B，因为改 kernels 与 tileref 会动 tile 输入摘要） | 无 | 否（加法） | **PR A**。不在 tile 路径上，不触发 `tile.yml`；要 `gen-stdsrc`，新增 spike-native 的两后端对拍用例 |
| U1 | `std/dtype`、`std/int` 四个类型的见证与 impl（`I8 I16 I32 U8`，经 `scripts/fixed-ints/gen.py`）、内建三个见证（`F64 I64 I1`）。**narrow 一侧**（`BF16 F16 F32` 的见证与 impl、只存储类型、`FP16`→`F16`）：`std/narrow.dawn` 是 tile 输入，动它就动摘要，所以留给 B | std 定宽整数合并 | 否（加法） | **PR A**（与 F0 同 PR，各一个提交）；narrow 一侧归 B |
| S2 | tileir 的 `d_range[B: RangeBound]`（Int 与 Idx 各一个 impl，取代 `d_range`/`d_for` 两个闭包形式）、`StagedIter`/`StagedVar` impl；不引入 `d_span`；`d_for` 不留别名 | S1（已合） | 否 | **PR B** |
| L3 | tileir 的运算符与字面量 impl；**第一步先实测** `add(Tile[I32], Tile[I32])` 今天的行为（§8.1），按结果决定 impl 体是否走检查 helper、是否开 issue | 运算符与 L1（已合） | 否 | **PR B** |
| M | `kernels.dawn`、`prog.dawn` 内联测试、`gpu_fake`、`tile-gpu-diff` 程序按 S2/L3/F0 迁移（含 `neg_inf()`/`ref_neg_inf()` 换 `-INFINITY`，`use std/float.{INFINITY}`）；加计数断言 | S2、L3、F0 | 否（旧 API 仍在） | **PR B** |
| U2 | 一次性格式切换（含 narrow 一侧的见证、`FP16`→`F16`）；**不**扩展 `std/moved.txt`，旧名直接删（§8.5、§9 Q5） | U1、M | **是** | **PR B**，**必须同一个 PR 完成**（见下） |
| R | 版本号 0.11.0、把闭包形式的 `d_range` 收回（栈中间的临时名一并清掉；`d_for` 已在 S2 删除）、CHANGELOG 迁移表、README、教程中英、spec、site gpu 页与调用图、台账重录 | U2 | 是 | **PR B** 的最后一个提交 |

**必须同 PR / 同栈**：

1. U2 内部不可拆。`std/gpu` 删标记与 tileir 改签名、33 个 `use std/gpu` 文件的迁移同时发生，否则中间态编不过（旧 tileir 引不到被删的标记）。这是 §4.2 的 675 处类型位置加约 33 个引入块，按「机械轮派新写者」的惯例整块做。
2. 台账只重录一次，并且只在 B 的最后一个提交（R）里重录。两个 PR 的分界按「动不动 tile 输入摘要」划：A 不动，B 动（kernels、tileref、`std/narrow.dawn`、`std/gpu.dawn` 与全部消费者），台账 verdict 不变、只变 `inputs=`。每个 PR 各自须通过 tile-golden 逐字节检查。
3. R 必须在 U2 之后。S2 刀在同一提交内用描述符取代闭包形式并迁完全部调用方，所以不需要临时名；若实现中确需，临时名只许活在 B 的中间提交，R 之前收回。

**两个 PR（2026-10-06 改定的切法，原为三个）**：

| PR | 内容 | tile 输入摘要 | 破坏 |
|---|---|---|---|
| A（#590） | F0 + U1，一刀一个提交 | **不动**。`std/float`、`std/dtype`、`std/int/*`、`scripts/fixed-ints`、`scripts/spike-native` 都不在 `TILE_PATHS`；`run.sh --check` 在 A 上必须原样绿 | 否，纯增量 |
| B | 其余一切：S2（`d_range[B: RangeBound]`、`StagedIter`/`StagedVar`）、L3（运算符与字面量 impl）、迁移 `neg_inf()`/`ref_neg_inf()` 换 `-INFINITY`、M（mma/full 的类型级格式来源）、U2（格式一次性切换，narrow 一侧见证、`FP16`→`F16`）、R（台账重录） | 动 | 是：`d_for` 删除、旧 `d_range` 闭包形式换成描述符、旧格式标记删除 |

为什么从三个并成两个：任何动 tile 摘要的 PR 都得带台账（`tile.yml` 门禁看的就是摘要），原来的 B 与 C 各动一次摘要，要么重录两次，要么 B 带着一份马上作废的台账。并成一个，台账只在栈顶重录一次。B 内部仍按刀分提交，每个提交可单独构建与过各自的定向测试；S2 与 U2 之间的 `d_range` 临时名问题因此只在 B 的提交序里存在，不再跨 PR（本版实现中 S2 刀直接让描述符取代闭包形式并同提交迁完全部调用方，没有用到临时名）。

U1 的 narrow 一侧留给 B 的原因：`std/narrow.dawn` 在 `TILE_PATHS`（`scripts/tile-gpu-diff/inputs.py`），而见证常量必须与类型同名同模块（`use std/narrow.{BF16}` 一次拿到类型与见证，这是 a1 的全部意义），不能放进 `std/dtype`：同时引入 `std/dtype.{BF16}` 与 `std/narrow.{BF16}` 会撞名。`impl HasDtype[..]` 按孤儿规则可以写在 trait 所在的 `std/dtype`，所以只有常量卡住。A 里 `std/int/{i8,i16,i32,u8}` 与内建三个见证不碰 tile 输入，照常做。

A 里「同名类型加常量」的两个风险用测试钉住，不靠早合暴露：`dawn doc` 的锚点（类型与常量各自唯一可寻址）与 LSP 悬停（值位置悬停显示常量、类型位置显示类型、跳转各落各处）。B 里 narrow 的同名对沿用同一批用例。

**排序理由**：M 在 U2 之前，是因为 U2 改的是 `kernels.dawn` 里 `Tile[F64]` 一类 449 处纯机械拼写，M 改的是循环与算术行；先 M 后 U2，U2 的 diff 才是纯机械、可由脚本验证。
反过来 U2 先，M 的每一处改写都要对着新拼写重写一遍。F0 在 M 之前，是因为 M 要用 `-INFINITY`。

**发版**：栈合并后先发一个编译器 release（承载 U1、F0、U2 的 std 改动），推进种子，再发 tileir 0.11.0（tileir 不是编译器 release 的一部分，按自己的版本线）。
tileir 的 `dawn.toml` 版本 0.10.0 到 0.11.0 改在 R。

## 8. 开放风险

1. **`impl[D] Add[Tile[D]]` 对整数 tile 的行为。** 静态阅读：`add[D]` 经 `binary` 调 `t_binaryf`，记录 handler 的 `t_binaryf` 臂（`prog.dawn:2557`）只检查形状、操作名与操作数格式一致，我没有读到「`dtype` 必须是浮点」的检查，所以 `add` 在 `Tile[I32]` 上大概率发出 `addf` 而不被拒。这只是读码结论，**未实测**。裁决（§9 Q6）：L3 的**第一步**是实测（记录一个 `add(Tile[I32], Tile[I32])` 看是拒绝、还是产出非法 IR）；若是未经检查的 `addf`，开公开 issue（英文，file:line，验收判据），并让运算符 impl 经一个检查 `D` 为浮点格式的 helper 实现，而不是直接调 `add`。
2. **`dawn doc` 的锚点。** 同模块里 `pub opaque type BF16` 与 `pub const BF16` 并存时，`dawn doc` 生成的锚点是否冲突（两者都叫 `BF16`）。U1 刀先用语料钉住；若冲突，给常量与类型分前缀锚点。
3. **LSP 悬停。** 一个格式名在值位置（`p.to(BF16)`）悬停该显示 `const BF16: Dtype[BF16]` 还是类型；跳转定义落到哪个。`lspeval` 对常量折叠表的读法是 L2 的缺口（literal 裁决点名）。需要 LSP 会话对拍（`selfhost-lsp-diff.sh`）加一个用例。
4. **`NAN` 与 `INFINITY` 的编译期求值。** `0.0 / 0.0` 与 `1.0 / 0.0` 在 comptime 折叠与两个后端（JVM、C）是否一致，NaN 的位型是否被保持。`INFINITY` 的位型可测（`0x7FF0000000000000`）；`NAN` 的 payload 无消费者，只要求 `x != x`。F0 刀加内联测试，两后端各跑一次。
5. **写错格式时的 hint：不做。** 旧代码写 `use std/gpu.{F64}` 与 `Tile[F64]`，新版里 `std/gpu` 不再导出 `F64`，得到的是普通的「没有导出此名」错误。裁决（§9 Q5，10-06 更正）：不给 `Tile[F64]` 提示，不扩展 `std/moved.txt`（它今天只管函数，扩展到类型名等于为一次迁移造兼容机制），U2 直接删旧名。
6. **`FP16` 改名是 std 公开面破坏。** 它随 U2（PR B）进编译器 release；`examples/data/narrow.dawn`、play-ui 样例、`spike-native` 同步改。dawnop-site 升钉前要 grep `narrow.fp16`/`FP16`，裁决（§9 Q8）要求把这条写进它的升钉清单（本仓不替它做）。
7. **import 块变长。** `kernels.dawn` 与每个 `tile-gpu-diff` 程序的 `use std/gpu.{F64, BF16, I32, ..}` 一行会变成 `std/dtype`、`std/narrow`、`std/int/i32` 等多行。核实结果：**Dawn 没有 re-export**（`spec.md` 没有 `pub use` 或同义条文，`std/` 与 `packages/` 里没有一处 `pub use`，只有选择性引入与整模块引入），所以 tileir 无法提供聚合出口。裁决（§9 Q7）：不为此引入 re-export，33 个文件各多 2 到 3 行 import 可以接受。
8. **泛型 kernel。** `var m: Tile[A]` 对裸类型参数 `A` 走 blanket `impl[D] StagedVar[Tile[D]]` 已在 main 上通过（调研 §1.2）；`generic_carry`（`T` 本身作携带类型）仍被拒，不属于本版。
9. **`d_loop` 与 `var` 混用。** 本版 `d_loop` kernel 不迁，`carry` 仍公开；若一个 kernel 同时有 `for` 与 `d_loop`，两种携带并存。树里没有这样的 kernel（4 个 `d_loop` 函数都不用 `for`），但文档要写清边界。
10. **台账的集群部分。** sm_90 与 sm_100 的重录依赖集群与所有者；栈合并后这两行 `inputs=` 在所有者重录前是陈旧的。K2.5 同样处理，不是新问题。

## 9. 裁决（2026-10-06）

八个开放问题已由维护者裁决（记录在 agent-handoff 的 ruling-tileir-011-open-20261006），下面每条一行理由，改动已写入对应章节。

- **Q1** `INFINITY`/`NAN` 放新模块 `std/float`（§2.3）。理由：`Float` 是内建类型，常量挂专门模块（Rust `f64::INFINITY`、Zig `std.math.inf` 的思路），不在 tile 路径上所以 F0 不触发 `tile.yml`，以后 `MAX`/`EPSILON`/`is_nan` 同处。
- **Q2** 终态拼写是 `d_range`，且只有一个：`d_range[B: RangeBound](lower: B, upper: B, step: Step[B] = One, unsigned_cmp: Bool = false)`（步长形状见 §2.1 与 ruling-drange-step-20261006；原 `step: B = 1` 写不出来），`Int` 与 `Idx` 各实现 `RangeBound`；`d_for` 删除，不引入 `d_span`，不发弃用别名（§2.1、§7）。理由：目标写法就是用户看过的 `for j in d_range(..)`；Int 界与 Idx 界只差边界类型，用 trait 区分比起两个名字更少记一个；同一个破坏性版本内调用方一次迁完，别名只会多留名字。IR 与 golden 不变。临时名只活在栈的中间提交，R 之前收回。（原「Idx 版沿用 `d_for`」于 10-06 由维护者推翻。）
- **Q3** U1 留在栈内，不单独先合（§7）。理由：不多付一次台账重录；同名类型加常量的 `dawn doc` 锚点与 LSP 悬停风险在 U1 刀内用测试钉住。
- **Q4** `FloatDtype` 与 `HasDtype` 分开保留（§2.5）。理由：mma 组合表只收七个算术浮点，并入会把整数与只存储格式放进 `full` 的约束，类型错误退成运行期拒绝。
- **Q5** 不做 `Tile[F64]` 提示，也不扩展 `std/moved.txt` 支持类型名（§8.5）。理由：仓内没有别的消费者，破坏性变更直接删旧名，编译错误已足够；为一次性迁移扩展机制是兼容层。（原裁决「走 `std/moved.txt` 并最小扩展」于 10-06 由维护者推翻。）
- **Q6** `Tile[I32]` 的 `add` 先实测，作为 L3 的第一步（§8.1）。理由：静态读码看不到浮点检查；若确是未经检查的 `addf`，开公开 issue 并让运算符 impl 经检查过的 helper。整数 tile 的运算符本版仍不给（§10 第 1 条）。
- **Q7** 不引入 re-export（§8.7）。理由：核实语言没有 re-export；每个文件多两三行 import 可以接受。
- **Q8** dawnop-site 升钉前 grep `narrow.fp16`/`FP16`，写进它的升钉清单（§8.6）。理由：本仓不替下游迁移，但清单项不能漏。

## 10. 不做的（理由）

1. **给 `Tile[I32]` 运算符**：与浮点 blanket impl 重叠，条件 impl 不可写（arith D5）；整数 tile 的 `*_i` 调用保持函数形，是 64 处不迁的代价，换来 impl 不歧义。
2. **`FromInt[Tile[D]]`**：`t * 2` 对浮点 tile 含义不明（整数字面量转浮点 tile），literal D12 已裁暂不给；写 `t * 2.0`。
3. **具名常量参与运算符**：`t * ATT_INV_SQRT_D` 仍要 `lit(..)`。literal D3 否决无类型具名常量与常量算术，本版不为 tileir 开例外。
4. **`pub alias F64 = Float`（让 `Tile[F64]` 零迁移）**：一个类型两个名字，悬停与诊断仍印 `Float`，读者要多记一层映射；675 处机械替换不值得换这个（调研 §5）。
5. **不要见证、只靠期望类型（a2）**：约 1400 处见证要改成标注，`p.to(BF16)` 的流式写法消失，Dawn 的局部推断在 K2.5 就已经逼出过额外标注。
6. **格式标记改名或挪模块（b）**：信息两份，迁移量约 3.5 倍，类型化传输还要关联类型手连。
7. **维持现状靠限定引入（c）**：撞名随定宽整数扩到 6 个，类型化传输与 `Tensor[U32]` 的类型错误都做不了。
8. **给 `U16`/`U32`/`U64` 造设备格式**：方言没有无符号整数 tile 类型（符号是操作的属性），不 impl `HasDtype` 才是诚实的。
9. **把 `Dtype` 放进 `narrow` 或 `gpu`**：narrow 不该依赖 gpu（反向成环），整数模块也要用它，所以单独一个底层小模块。
10. **在本版放宽 `generic_carry`**：没有真实消费者（ruling-generic-kernel 第 1 条）。
11. **staged `while`、`break`/`return` 离开 staged 体**：staged-for-design §9 已否；数据相关退出用 `d_loop`。
12. **本版做类型化 `download`（U3）与常量带宿主值类型（U4）**：U3 要改线协议（Bytes），i64 精确性另有一条债；U4 可能动 golden。各自另设计，不与一次「golden 零变化」的发布混装。
13. **本版做 K4 运行期标量参数**：独立，碰 `std/gpu` 的 `Gpu` 效果面与 Core golden，可并行，不并入。
14. **`d_span`、`d_for` 别名、两个并列的循环描述符**：`d_range[B: RangeBound]` 一个名字覆盖 Int 与 Idx 界，另起名字只会多留一个要记的词（§9 Q2）。
15. **`Tile[F64]` 迁移提示与 `std/moved.txt` 对类型名的扩展**：没有别的消费者，旧名直接删；为一次迁移扩展机制就是兼容层（§9 Q5）。
16. **在 PR A 里动 `std/narrow.dawn` 或迁 `neg_inf()`**：两者都在 `TILE_PATHS` 内，会改变 tile 输入摘要；A 的承诺是摘要不动（§7）。
17. **逐刀各发一个版本**：见 §1，同一批行改四遍，台账重录四次。
