# 从 builtin 到 stdlib：把编译器里的库搬出去

> 语言层议题，**先文档、不动代码**。触发点是 `cast[T]`（interop cast 统一）的讨论：
> 「为什么有这么多 builtin，能不能避免」。本文回答现状、根因、别的语言怎么做、以及
> Dawn 的迁移路线。`cast[T]` 的设计见 [`cast-interop.md`](cast-interop.md)；本文是它之后的下一个议题。

## 一、结论（TL;DR）

- 编译器现有 **75 个 builtin 函数**（`check/Types.kt` 的 `FnSig` 表）。
- 按「**即便有了 FFI + Dawn prelude 仍写不出来**」这条硬判据分，**不可约的核只有 4 个**：
  `java_try`、`catch_panic`、`cast[T]`、`panic`。其余 **71 个**都是「本该在标准库、却塞进了
  编译器」的东西——**这张 builtin 表就是 Dawn 事实上的 stdlib，只是长错了地方（长在编译器里）**。
- 架构上这一点被证实：集合/字符串 builtin 全是**薄派发**——lower 成 `INVOKESTATIC dawn/rt/Lists.map(…)`，
  背后 runtime 类（`nLists`/`nStrings`/`nMaps`…）由编译器**手写 ASM 生成**；底层类型是现成的
  （`List` = `java.util.List`、`String` = `java.lang.String`、`Bytes` = `byte[]`）。**它们本就是库函数，
  只是靠「名字特判」接进来**。搬走它们还能**删掉编译器里 ~63 个名字特判分支**，编译器反而变小。
- 根因：Dawn **还没有「用 Dawn 写的标准库」的容身之所**（源码包「项目B」未启动），
  于是发布 `map`/`split` 的唯一办法就是烧进编译器。
- 别的 JVM/系统语言的统一做法：**极小的不可约 intrinsic 核 + 用语言自己写的大 Prelude，
  自动引入**。Dawn 照此把 ②③ 两层迁出编译器，最终**只留 4 个 intrinsic**。
- **不需要**先做完整包管理器，也**不需要**新造「调用 runtime」的机制：runtime 类已是普通 JVM 类，
  prelude 里 `use java "dawn.rt.Lists"` 直接 FFI 转发即可（`pub fn map(xs, f) = Lists.map(xs, f)`）。
  唯一缺的编译器特性是「bundle 一份 `std` 源码 + 隐式 `use std`」——一个小杠杆，②③ 就能分批搬走。

## 二、现状：75 个 builtin 的三层分类

来源：`compiler/src/main/kotlin/dawn/check/Types.kt` 的 builtins map（`FnSig("…", …, isBuiltin = true)`）。

| 层 | 数量 | 能否移出编译器 | 迁移形态 |
|---|---:|---|---|
| **① 真·intrinsic（最小核）** | **4** | ❌ 不能——即便有 FFI + prelude 也写不出来 | 保留为 builtin |
| **② JDK 薄包装** | ~25 | ✅ 用 Dawn 写、`use java` 调 JDK / runtime | `std/strings.dawn`、`std/bytes.dawn`、`std/fs.dawn` |
| **③ 可用 Dawn 自举** | ~38 | ✅ prelude 一行 FFI 转发到 `dawn.rt.*`，或 trait | `std/list.dawn`、`std/map.dawn`、`std/set.dawn` + trait |
| **（近核）已下放** | ~8 | ✅ 曾像 intrinsic，实则可 prelude 化（见下） | prelude sugar / FFI runtime 助手 |

### ① 真·intrinsic（4，最小核）

判据是最严的一条：**即便有了 FFI 和 Dawn prelude，仍写不出来**的才留。只剩 4 个：

```
java_try      # Dawn 的 try/catch：catch JVM Throwable 要异常表字节码，无 surface 语法可替代
catch_panic   # 监督边界：try/catch 覆盖 Dawn panic 在内的一切 Throwable
cast[T]       # 从类型实参发 CHECKCAST，无通用 Java 方法可替代（见 cast-interop.md）
panic         # Never 发散 + 抛 PanicError；catch_panic 的语义搭档、穷尽性分析的锚点
```

> 对照 GHC：「基本类型无法用 Haskell 定义，故内建；凡是能用 Haskell 定义的，就都用 Haskell
> 定义」。这 4 个正是 Dawn 的「无法用 Dawn 定义」集合。

**曾被当 intrinsic、实则可下放的「近核」（一并移出）**：

```
to_int  to_float   # → prelude，FFI 到 runtime 静态助手 dawn.rt.Num.toInt/toFloat（内部 d2l/l2d，无装箱）
todo               # → prelude sugar：fn todo() -> Never = panic("todo")（panic 在，它就多余）
args               # → prelude 访问器，FFI runtime
print  println     # → prelude，FFI java.lang.System.out
read_line          # → prelude，FFI java.lang.System.in
```

> 说明：算术/比较运算符（`+ - * / == < && ++`…）**本就不在 builtin 表里**（codegen 单独处理），
> 不计入本表——最小核是 4 就是实打实的 4，没把运算符偷偷藏进别处。
>
> `panic` 其实也*几乎*能下放（无非「`Never` 发散 + 抛 `PanicError`」）。留它当第 4 个是**有意的锚点**：
> 它是 `catch_panic` 的语义搭档、也是穷尽性分析里「这条分支不产值」的依据。再往下到 3 是拿语义
> 清晰度换一个数字，**停在 4**。

### ② JDK 薄包装（~25，可移出）

本质是「`use java` 一行 + 一层参数转换」，塞进编译器只是因为当时没有 stdlib 可放：

```
# String（→ java.lang.String / Integer / Character）
str_len  substring  to_lower  to_upper  trim  split
starts_with  ends_with  index_of  last_index_of  contains
chars  char_to_string  code_points  from_code_points
parse_int  parse_float

# Bytes（→ byte[] / String.getBytes / new String）
decode  byte_at  byte_len  byte_slice  byte_index_of

# 文件系统 / IO（→ java.nio.file.Files）
read_file  write_file  list_dir  is_dir
```

> 注：`contains` / `index_of` / `last_index_of` 在字符串与列表上都有语义，迁移时按 trait 或
> 各自模块拆分（见 ③ 的 trait 方案）。

### ③ 可用 Dawn 自举（~38，可移出）

集合/容器/Option。runtime 类（`dawn.rt.Lists`/`Maps`）已存在且是普通 JVM 类，prelude 里
**一行 FFI 转发**即可（`pub fn map(xs, f) = Lists.map(xs, f)`）；纯 Dawn 重写留作后续可选：

```
# List（prelude 转发 dawn.rt.Lists，或纯 Dawn 递归重写）
map  filter  fold  find  range  reverse  take  drop
sort  sort_by  join  len  get  min  max  min_by  max_by

# Map（10）
map_empty  map_from  map_get  map_has  map_insert  map_remove
map_size  map_keys  map_values  map_entries

# Set（7）
set_empty  set_from  set_has  set_insert  set_remove  set_size  set_to_list

# Option / Result
expect  unwrap_or

# 多态渲染 —— 应是 trait，不是 builtin
to_string          # → Show trait（已有 derive Show）
```

## 三、根因：没有「用 Dawn 写的 stdlib」的容身之所

别的语言的 `map`/`split`/`substring` 都住在**用该语言自己写的标准库**里；Dawn 没有这个地方，
所以**唯一能发布 `map` 的办法就是把它烧进编译器当 `FnSig` + codegen**。

对照包管理设计（`docs/package-design.md`）：源码包「项目B」**未启动**（硬阻塞：`className = modPath`）。
项目B 一旦落地，②③ 就有地方以「可分发、带版本的包」形态存放。但——**只是把它们移出编译器
并不需要项目B**（见第五节）。

## 四、别的语言怎么做

统一规律：**极小的不可约 intrinsic 核 + 用语言自己写的大标准库（Prelude），自动引入。**

| 语言 | intrinsic 核 | 库怎么来的 | 关键手法 |
|---|---|---|---|
| **Haskell / GHC** | `GHC.Prim`：一把机器级 primop（无法用 Haskell 定义的部分） | `base`/Prelude 用 Haskell 写在其上，自动 import | 「能用语言定义的就用语言定义」 |
| **Rust** | `core::intrinsics`：藏起来的实现细节（`transmute`/`size_of`） | `core`/`std` 用 Rust 写；运算符 `a+b` **desugar 成 trait `Add::add`** | intrinsic 外包一层库函数；运算符=trait |
| **Scala / Kotlin** | 几乎为零 | 整个 stdlib 用语言自己写，连 `println` 都是库函数 | 运算符是方法，全靠 JVM + stdlib |
| **Go** | 极小且**冻结**的一撮（`len` `append` `make` `new` `copy` `panic` …） | 其余全在标准库 | 数量少是设计价值（泛型前没法表达才进 builtin） |
| **Zig** | `@` 前缀 builtin（`@sizeOf` `@intCast` `@import`） | 不减数量，但用**命名空间**隔开 | 普通命名空间保持干净、builtin 一眼可辨 |

两条可直接用的手法：
1. **Prelude 写在语言里、自动引入**（Haskell/Rust/Scala）——这是把 63 个搬出去的主干。
2. **多态操作收敛成 trait**（Rust `Add::add`）——`to_string`/`len`/`==`/排序 不必是 magic builtin。

## 五、Dawn 的迁移路线（按依赖排序）

**杠杆 1 — 用 trait 吃掉「多态 builtin」（今天就能做，Dawn 已有 trait）**
- `to_string` → **`Show` trait**（已有 `derive Show`，`to_string` 不该另立 builtin）。
- `len` / `==` / 排序 → `Len` / `Eq` / `Ord` trait。对齐 Rust `Add::add` 模型。
- 收益直观、风险小，可作为「builtin 能被 trait 取代」的单点验证。

> **调用形态已就位，缺的是重名派发**：Dawn **已同时具备 UFCS 与 `|>`**，且二者脱糖一致——
> `f(x, a)`、`x.f(a)`（UFCS，`Checker.kt:1320` / spec §4.3，优先于 Java 实例方法与记录字段函数）、
> `x |> f(a)`（`Parser.kt:652`）**是同一个 `f(x, a)` 的三种写法**。所以 `map.get(k)` 这种「方法式」
> 写法**语法层今天就支持**，无需新语法。分工上：**`.` 管单点调用**（`m.get(k)`、`s.trim()`），
> **`|>` 管数据流水线**（`xs |> filter(p) |> map(f) |> sort_by(key)`，避免反着读的嵌套）；
> 注意 `|>` 穿的是**左侧数据**，故 `m |> get(k)` 对、`k |> map` 方向反了。
>
> 但 UFCS **按名字**解析自由函数、Dawn builtin 表名字唯一（无 ad-hoc 重载），所以 `get`（List 已占）
> 与 Map 的取值**不能同名共存为自由函数**——今天只能写 `m.map_get(k)`（丑）。要让 `m.get(k)` 与
> `xs.get(i)` **同名共存**，就得把 `get` 做成**按接收者派发的 trait 方法**（一个 `Index`/`Get` trait，
> List/Map 各自 impl）。**即：漂亮的 `m.get(k)` 与「stdlib trait 化」是同一件事**，归本杠杆一起做；
> 在此之前保留 `map_get`/`map_has`/`map_insert` 前缀名。**stdlib 约定**：函数一律「接收者/集合当第一参」，
> 三形态（前缀 / `.` / `|>`）自动都通。

**杠杆 2 — 给编译器加「bundle std 源 + 隐式 import」（一个小特性）**
- Dawn **已支持项目内多文件源模块**（`backend-dawn` 用 `use web/…`、`use http` 组织）。
  所以 `std/strings.dawn` 里 `use java "java.lang.String"` 再导出 `substring`/`split`，
  **技术上现在就成立**。
- 唯一缺口：编译器**捆绑一份 std 源码 + 对每个编译单元隐式 `use std`**（像 Prelude 自动 import）。
  这比整个包管理器小得多，是本路线的**关键使能特性**。

**杠杆 3 — 分批把 ②③ 迁进 `std/*.dawn`**
- ②（JDK 薄包装）：`std/strings.dawn`、`std/bytes.dawn`、`std/fs.dawn`，`use java` 实现。
- ③（集合）：`std/list.dawn`、`std/map.dawn`、`std/set.dawn`，先一行 FFI 转发 `dawn.rt.*`，
  纯 Dawn 重写可选。
- 「近核」（`to_int`/`to_float`/`todo`/`args`/`print`/`println`/`read_line`）一并迁入 `std/`。
- 每迁一批，编译器 builtin 表 + 对应的名字特判分支就瘦一圈；**最终只剩 ① 的 4 个 intrinsic**。

**杠杆 4 —（可选，远期）把 `std` 做成可版本化的独立包**
- 只有当想让 stdlib **可分发、带版本、脱离编译器发版节奏**时，才需要「项目B」。
- 「移出编译器」不等于「做成包」——前三步不依赖项目B。

## 六、权衡与不做

- **`print`/`println`/`read_line`/`args` 已划出核**：作为 `std/io.dawn` 的
  `use java "java.lang.System"` 包装（`args` 走 runtime 访问器）。它们的效果边界靠 prelude 函数
  签名上的 `!io` 表达，不需要 intrinsic 地位。**最小核锁定为 4（见 ①）。**
- **性能**：集合从 codegen 特例改成 Dawn 实现，可能损失一点内联优化。先以「正确 + 变薄」为目标，
  真有热点再把个别函数标 `@inline`/回收成 intrinsic（Rust 的 intrinsic-behind-wrapper 模式）。
- **不追求一步到位**：这是一条可**分批、可回滚**的路线，不是一次大重构。`cast[T]` 先行，
  trait 化 `to_string` 次之，其余按 `std/` 模块逐个搬。
- **不引入宏**：Lisp/Rust 靠宏收缩核心，但 Dawn 当前无宏、也不为此引入；trait + Prelude 已够。

## 参考

- [ghc-prim: GHC primitives (Hackage)](https://hackage.haskell.org/package/ghc-prim) —— 不可约 primop 的边界
- [core::intrinsics (Rust)](https://doc.rust-lang.org/core/intrinsics/index.html) —— intrinsic 藏在库函数背后
- [Rust Tidbits: What Is a Lang Item?](https://manishearth.github.io/blog/2017/01/11/rust-tidbits-what-is-a-lang-item/) —— 运算符 desugar 成 trait
- 本仓 `docs/package-design.md`（项目B / 源码包）、`docs/trait.md`（trait 现状）、`docs/spec.md` §11（builtin 清单）
