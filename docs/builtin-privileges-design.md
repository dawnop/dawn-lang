# 内建类型特权设计（裁决 6）

> 状态：**current**。本文记录 2026-09-24 裁决 6 的五条（SPC-10、SPC-03、SPC-08、SPC-17、SPC-18）
> 的语言契约、实现落点、破坏性影响与负控。他语言调研见交接目录
> `agent-handoff/research-builtin-privileges-20260924.md`（Rust/Haskell/OCaml/Go/Swift/Scala/Kotlin/Gleam，逐项带出处）。

## 0. 共同的问题

四个 prelude 关系（`Eq`/`Hash`/`Ord`/`Show`）在内建标量上的覆盖面，今天是几张没有统一理由的表：

| | `==` | `<` | `[T: Ord]`/`sort` | `hash` | `to_string` |
|---|---|---|---|---|---|
| `Int`/`String` | 有 | 有 | 有 | 有 | 有 |
| `Float` | 有 | 有（IEEE） | **无**（NaN，2026-07-26 有理由） | **无**（-0.0，有理由） | 有 |
| `Bool` | 有 | **无** | **无** | 有 | 有 |
| `Bytes` | 有 | **无** | **无** | 有 | 有 |
| `Unit` | **无** | **无** | **无** | **无** | **无** |

`Float` 那两格有写下来的理由；`Bool`、`Bytes`、`Unit` 那几格没有，而且用户无处自救：
`impl Ord[Bool]` 是孤儿 impl，hint 指向一个写不进去的模块。另外 `<` 的原生快路径
（`checker.dawn` 的 `ol == TyInt || ol == TyFloat || ol == TyString`）与 `ord_scalars()`
是两张手抄表。

## 1. SPC-10：`Ord[Bool]`、`Ord[Bytes]`

**契约**：
- `Ord[Bool]`：`false < true`（Rust、Haskell、OCaml、Scala 同；Haskell 的理由是「构造器声明序即序」，
  Dawn 的 `derive Ord` 对和类型用的正是这条，Bool 就是两个构造器的枚举）。
- `Ord[Bytes]`：无符号逐字节字典序，公共前缀相等时短者小（Haskell `compareBytes`、Rust `[u8]` 的定义）。
  这也是 `Ord[String]` 在 native 上的实际算法（UTF-8 memcmp + 长度），不引入新语义。
- `cmp` 仍只承诺 `-1`/`0`/`1`。
- `Float` 不变：无 `Ord`，保留 IEEE `<`。

**同一张表**：`types.ord_scalars()` 是唯一的表，`[Int, Bool, String, Bytes, Unit]`（Unit 见 §2）。
`<` 的快路径改为 `is_ord_scalar(ol) || ol == TyFloat`：表里的都走原生比较，`Float` 是表外唯一具名例外
（偏序也有原生 `<`）。以后往表里加一个标量，`<` 与 `[T: Ord]` 同时得到它，不可能再分叉。

**后端**：
- JVM：`Bool` 的 `cmp` 与 `<` 用 `Integer.compare(II)I`；`Bytes` 用 `java.util.Arrays.compareUnsigned([B[B)I`
  再 `Integer.signum`（JDK 9+，工具链要求 JDK 21）。
- native：运行时新增 `dawn_cmp_bool`、`dawn_cmp_bytes`（与 `dawn_cmp_str` 同形：memcmp 公共前缀，再比长度）；
  `<` 在 `Bytes` 上发 `(dawn_cmp_bytes(a, b) op 0)`，`Bool` 直接用 C 的关系运算（`bool` 提升为 int，`false < true`）。
- comptime 解释器：`<` 补 `VBool` 一臂；`Bytes` 在 comptime 本就没有值，不涉及。

## 2. SPC-03：`Unit` 进标量表

**契约**：`Unit` 有 `Eq`、`Hash`、`Ord`、`Show` 四个 prelude impl。
- `() == ()` 为真，`cmp((), ())` 为 `0`，`() < ()` 为假、`() <= ()` 为真。
- `hash(())` 为 `1`：spec §3.5 的合成哈希「种子 `1`，逐部分折进去」，`Unit` 是一个部分都没有的值，答案就是种子。
- `show(())` 与 `to_string(())` 都是 `()`（与 Rust `Debug`、Haskell `show`、Scala `toString` 一致）。
- 推论：`Result[Unit, E]` 可 `==`、可 `to_string`、可作 `Map` 键、可排序。std/io 测试里 8 个为绕开
  「Unit 无相等」写的局部 `ok` lambda 与 23 处调用改成直接 `== Ok(())`。
- spec §2.1「`Eq`/`Hash`/`Show` 对 `Unit` 无实现」那条例外删除。

**实现**：四个关系在 `Unit` 上是常量，不值得每个后端各写一份原语。lowering 的 `eq_at`/`cmp_at`/`hash_at`/`show_at`
在 `Unit` 上直接产出 `CBlock([CSDiscard(a), CSDiscard(b)], Some(常量))`：操作数照常按序求值（保留副作用），
结果是常量。运算符路径（无见证的 `==`/`<`）遇到 `Unit` 也改走这条，后端不会见到 `Unit` 上的 `CBinary`。
`to_str` 的 `Unit` 臂原来直接丢弃操作数，同时改成先求值再给 `"()"`。

## 3. SPC-08：derive 表驱动

**契约**：可 derive 的 prelude trait 是一张封闭表，今天两项 `Ord`、`Show`（Haskell 2010 的 deriving 也是
Prelude 里的封闭集合；Kotlin/Swift 的合成同样封闭；Rust 的开放靠过程宏，Dawn 没有也不打算有）。
- 表：`types.derivable_traits()`，每行 `Derivable { name, trait_id, adjective }`，次序 `Ord`、`Show`
  （即此前铸 impl 的次序，派生 impl 的登记次序因此不变）。derive 解析、impl 铸造、字段检查三处遍历它。
- `AdtI` 的两个布尔字段 `derives_show`/`derives_ord` 收成一个 `derives: List[Int]`（trait id）。
- 表外名字的诊断：`` `X` is not a derivable trait ``，hint 从表生成（「the derivable traits are Ord, Show」），
  对 `Eq`/`Hash`（结构默认，写 impl 是覆盖）与 `Display`（手写的呈现决定）各给一句具体原因，其余名字说明
  这是封闭集合。
- `Eq`/`Hash` 维持结构自动（Go 先例），写进 spec §3.5。

**负控**：把表里的 `Ord` 行删掉，`derive Ord` 的 checker 语料（`derive_table.dawn`）红。

## 4. SPC-17：`opaque type` 不再继承 target 的 `Show`

**契约**：opaque 类型对 `Eq`/`Hash`/`Ord`/`Index`/`Iter` 仍然「自己没写就用 target 的」，
对 `Show` **不再**如此：要打印就在声明模块写 `impl Show[X]`。理由：关系只回答真假或符号，不暴露表示；
渲染直接把表示印出来。GHC 的 `GeneralizedNewtypeDeriving` 是同一条切分：复用表示的字典，
「except Show and Read, which really behave differently for the newtype and its representation」。

**实现**：`resolve_witness` 的 opaque 回落跳过 `SHOW_ID`，缺 `Show` 时给专门的 hint；`derived_field_ok`
对 `SHOW_ID` 不再下钻 opaque 的 target（`derive Show` 的字段同理）。lowering 的 `show_at`/`to_str`
里「opaque 没有自己的 impl 就渲染 target」的回落随之不可达，删除，`has_own_show` 一并删除。
`Display` 的「逐层 peel、每层重问」也随之删除：能进 `to_string` 的 opaque 必有自己的 `Show`，
没写 `Display` 就走自己的 `Show`，不借下层的 `Display`。`display-layering-contract` 第二条规则相应改成
`display_is_not_inherited`，mutant `inherit-display` 把旧的 peel 加回去。

spec §2.7 的别名替换法判据：允许看见 `TyOpaque` 的事从五件变成六件，第六件是 `Show` 见证解析。
`scripts/opaque-twin/` 的渲染断言迁出双胞胎（两种拼写在渲染上本就不再等价）。

**逐个审计（std + packages 的 `pub opaque type`，外加 `Char`）**：

| 类型 | target | 判断 | 处置 |
|---|---|---|---|
| `std/char.Char` | `Int` | 已有 `impl Show`/`impl Display` | 不变 |
| `std/cursor.Cursor` | `Int` | 已有 `impl Show`（SEM-04） | 不变 |
| `std/bytes.Buf` | `Array[Int]` | 可变构建器句柄，打印它等于打印内部数组 | 不可打印；要看内容先 `to_bytes` |
| `std/gpu.Tensor[D]` | `(Int, Int)` | 设备句柄，句柄号对用户无意义 | 不可打印 |
| `std/narrow.BF16`/`FP16`/`F32` | `Float` | 数值，打印是正常需求（今天的语料就在打） | 补 `impl Show`，渲染为所含 `Float`（与今天逐字节相同） |
| `packages/sha2.Digest` | `DigestState` | 进行中的哈希状态，打印会泄漏中间状态 | 不可打印；结果用 `finish`/`hex` |
| `packages/tileir` 的 `Tile`/`Idx`/`Param`/`Scalar`/`Ptrs`/`TensorView`/`GridView`/`GatherScatterView` | `Int` 或 `(Int, String)` | SSA 句柄，句柄号对用户无意义 | 不可打印 |

selfhost 内部的 opaque 类型（`check/*`、`driver/*`）若有打印点，同样逐个补 impl 或改打印点，结果在 §7 回填。

**破坏性**：上表「不可打印」的类型上 `to_string`/`${}`/`derive Show` 字段现在是编译错误。
dawnop-site 按 `.dawn-version` 钉 release，本改动不影响它，直到它升钉；升钉时的迁移是「在需要打印处先转成 target」
或「请求补 `impl Show`」。

## 5. SPC-18：`f[T](x)` 的诊断

`id[Int](3)` 今天给三条错误，第一条是「`id` 当值用推不出类型参数」，第二条是「undefined constructor: Int」，
「Dawn 没有调用点类型实参」落在第三条、而且挂在外层 `to_string` 上。Go 1.18 起 `f[int](x)` 正是显式实例化的写法，
Go 用户最可能写出这个拼写。

**契约**：`EIndex` 的主体是一个裸名、解析到**泛型**函数或内建（不是局部变量），而下标是一个**不是构造器的类型名**
（内建类型名，或本模块可见的类型名；`List[Int]` 这种嵌套也算）时，checker 只报一条：
`Dawn has no call-site type arguments: `id[Int]` reads as indexing the function `id``，
hint 给出标注写法（`let x: Int = id(...)` 或带标注参数的 lambda）。结果类型是错误类型，外层调用不再追报。

## 6. 负控

| 条 | 负控 | 期望 |
|---|---|---|
| SPC-10 | 两后端对拍语料 `spike-native/ord_bool_bytes.dawn` 在改前 | 编译失败（红） |
| SPC-03 | `spike-native/unit_relations.dawn` 在改前 | 编译失败（红） |
| SPC-08 | 删 `derivable_traits()` 的 `Ord` 行 | checker 语料 `derive_table` 红 |
| SPC-17 | checker 语料 `opaque_show.dawn`：句柄 `to_string` 报错 | 改前无诊断（红） |
| SPC-18 | checker 语料 `call_site_type_args.dawn` 的诊断顺序 | 改前三条、顺序不同（红） |

## 7. 实施记录

（实现后回填：提交、集群 run、实测。）

## 不做的（理由）

- **不让用户 trait 可 derive**：需要编译期元编程或「空 impl + 默认方法」的 `DeriveAnyClass` 式开放；
  后者让 `derive Foo` 与 `impl Foo[T] {}` 成为同一件事的两种写法。
- **不给 `Float` 补 `Ord`**：2026-07-26 的理由不变（NaN 无全序）。
- **不结构化 `Show`**（SPC-08 选项 c）：渲染是呈现决定，默认可打印会重新打开 SPC-17 关掉的泄漏。
- **`Unit` 不加后端原语**：四个关系都是常量，lowering 折掉即可；加原语是给每个后端各添一份永远返回常量的代码。
- **opaque 不做「可 allow 的 lint」**（SPC-17 选项 a）：Dawn 只有一种诊断等级（裁决 8 同理）。
- **不引入调用点类型实参**：SPC-18 只修诊断；语法是另一个裁决的范围。
