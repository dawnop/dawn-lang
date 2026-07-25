# 相等怎么设计：七门语言的做法与代价

> [`trait-v2-design.md`](trait-v2-design.md) §2 那条开着的问题(`==` 要不要 `Eq` bound)
> 不是 Dawn 独有的。这份是动手前的横向调研:每条路都有语言走过,**代价都已经付过了**,
> 没必要自己再付一遍。
>
> 调研日期 2026-07-26。结论在 §5。

## 0. Dawn 今天站在哪

两条,都不是自己发明的:

- **`==` 全域、不要求 bound**,擦除位置由后端各自决定含义 —— 这是 **OCaml 的 polymorphic compare**。
- **运算符是 IEEE,而 `Ord` trait 是全序**(`cmp(-0.0, 0.0) = -1` 但 `-0.0 == 0.0` 为 true)
  —— 这是 **Kotlin/Java 的 `==` vs `.equals()` 分裂**。

下面会看到:这两条恰好是调研里**唯二被写进博客标题和 issue 跟踪器的痛点**。

## 1. `==` 与相等 trait 的关系

| 路 | 谁走了 | 结果 |
|---|---|---|
| **A. `==` 就是 trait 方法,要 bound** | Rust(`PartialEq::eq`)、Haskell(`Eq`)、Swift(`Equatable`) | 三个「后来者」的共同收敛点。无残留、无 RTTI |
| **B. 全域,但编译器推断 bound** | Haskell 对**无签名**的绑定就是这么做的(context inference) | **没有语言把它作为全语言策略**。Haskell 写了签名就必须写约束;单态性限制(monomorphism restriction)有一部分正是这条带来的麻烦 |
| **C. 全域 + 运行期结构走** | OCaml(`compare_val`)、Elm、Java/Scala 的 `Object.equals` | 见下 |

### C 这条路的实测结局(OCaml)

OCaml 的 `=` 是运行期结构比较,直接在低层表示上递归,**完全绕开类型系统**。已知代价:

- 函数值 → 抛 `Invalid_argument`(不是编译错误,是运行期)
- 循环结构 → **不终止**
- 忽略自定义比较 —— 抽象类型自己定义的相等被绕过
- 慢,且编译器只能在部分情况下优化掉

Jane Street 那篇讲这件事的博文,标题就叫 **"The perils of polymorphic compare"**。
而 OCaml 生态的实际解法是 **`ppx_compare`:按类型在编译期生成比较函数**。

> **这一条对 Dawn 最有意思**:`ppx_compare` 干的事,就是 Dawn S1 步 1 的展开器已经干了的事。
> 也就是说 Dawn 现在的位置是「**已经有了 ppx_compare,还在犹豫要不要保留 polymorphic compare**」。
> 保留它的唯一后果是 native 后端必须带 RTTI —— 而 OCaml 正是靠运行期表示才做得到这件事,
> 那份表示也正是它那些坑的来源。

## 2. Float:唯一没有免费答案的地方

浮点让「相等」不成立**自反性**(`NaN != NaN`),而自反性是等价关系的最低要求。
五种处置,五种代价:

| 语言 | 做法 | 代价 |
|---|---|---|
| **Rust** | **拆 `PartialEq` / `Eq`**。`f64: PartialEq` 但**不是** `Eq`,连带**不是** `Hash` → **f64 不能当 HashMap 键** | prelude 多一个 trait,签名到处多一层 |
| **Haskell** | `Eq Double` 存在且**不合法则** | `Data.Map` 用 `Double` 键在 NaN 上静默出错 |
| **Swift** | `Float: Equatable` + `Hashable`,IEEE 语义 | 同上,stdlib 注释自己承认法则破了 |
| **Kotlin/Java** | **运算符与方法分开**:静态已知 `Double` 时 `==` 是 IEEE;泛型/装箱时走 `.equals()` 是**全序**(`NaN.equals(NaN)` 为 true、`0.0.equals(-0.0)` 为 false) | 见下 |
| **Go** | `float64` 满足 `comparable`,`==` 是 IEEE | NaN 作 map 键 → **同一个键对应多个条目,且索引取不出来**,只能靠 `range`;Go 1.21 专门加 `clear` 内建来兜 |

### Kotlin 那条的实测结局

Kotlin 官方文档为此专门写了一节 —— 因为**同一个值在两种上下文里给不同答案**是要教的。
而且 Kotlin **自己内部也没统一**:JetBrains 有个跟踪 issue(KTIJ-11497)说
**data class 生成的 `equals` 用的是 IEEE 语义**,与 `Double.equals` 的全序不一致。

> 这正是 Dawn 的 `eq_bytes` / `eq_adt` 语料抓到的同一种病:**一个关系,两个答案,取决于它经过哪条路**。
> Kotlin 是这条路上走得最远的语言,它的结论是「这需要一节文档 + 一个未修的 issue」。

## 3. 元组:结构类型 vs 具名类型

| 语言 | 元组是什么 | 能不能有相等 impl |
|---|---|---|
| **Swift** | 结构类型 | **不能**。SE-0283「Tuples are Equatable, Comparable, Hashable」**2020 年通过,至今未实现**。官方理由:元组是结构类型不是具名类型,**没有可以扩展的实体**。社区实际结论是「别用元组,改用 struct」 |
| **Rust** | 结构类型,但 `core` 用宏铺到 **12 元** | 能,靠宏 |
| **Haskell** | 同上,`base` 铺到 15 元 | 能,靠手写 |
| **Scala** | **元组就是普通类**(`Tuple2[A, B]`…) | 白拿 |
| **Kotlin** | **根本没有元组类型**,只有 `Pair`/`Triple` data class | 白拿 |

> Swift 是最强的反面证据:它选了「元组保持结构类型」,**六年没能把已通过的提案实现出来**,
> 而这六年里社区给的建议是绕开元组。选了「元组是 ADT」的 Scala/Kotlin,这个问题根本不存在。

## 4. prelude 类型的归属

`Option`/`Result` 这类类型,编译器要认识(`?` 糖),但 impl 要写得出来 —— 谁拥有它们?

| 语言 | 做法 |
|---|---|
| **Rust** | `Option`/`Result` 是 `core` 里的**普通泛型 enum**;编译器通过 `#[lang = "…"]` 认名字,`?` 走 `Try` trait |
| **Swift** | `Optional` 是 stdlib 里的普通 enum,编译器知道它(`?`/`!` 糖) |
| **Haskell** | `Maybe`/`Either` 就是 `base` 里的普通类型,零编译器特判 |

**没有主流语言把 `Option` 留在编译器内部。** 一致做法是「stdlib 的普通类型 + 编译器认一个 lang item」。

## 5. 借鉴结论

三个「后来者」(Rust 2015、Swift 2014、Scala 3 2021)在**相等是 trait**这条上完全收敛;
分歧只在 Float 怎么拆、元组算不算具名类型。而 Dawn 今天同时站在 OCaml(polymorphic compare)
和 Kotlin(运算符/方法双答案)两条**已知痛点**上,且这两条都不是当年权衡后选的 —— 是
「`==` 先于 trait 存在」的历史顺序留下的。

| Dawn 的问题 | 建议借鉴 | 依据 |
|---|---|---|
| `==` 与 `Eq` 的关系 | **A:`==` 是 trait 方法,要 bound** | 三个后来者的收敛点;C 的代价 OCaml 已经付过且生态在绕开它,而绕开的手段正是 Dawn 已有的展开器 |
| Float | **拆 `PartialEq` / `Eq`**(Rust) | 唯一让法则真成立的做法。Haskell/Swift 的「承认破法则」与 Kotlin 的「两个答案」都是明码标价的债,而 Dawn 刚在 S1 步 2 用「不自反」挡了函数值 —— 不拆就是双标 |
| 元组 | **变成 std 的 ADT**(Scala/Kotlin) | Swift 六年未实现的提案是反面证据 |
| prelude 归属 | **搬进 std + lang item**(Rust/Swift) | 三家一致,没有第二种做法 |

### 三条要留意的细节

1. **拆 Eq 会连带问 Ord。** Rust 拆的是 `PartialOrd`/`Ord`,`f64` 只有 `PartialOrd`;
   而 **Dawn 今天的 `Ord[Float]` 已经是全序**(`Double.compare`)。要么跟 Rust 一起拆、
   `Ord[Float]` 降级成 Partial,要么保持全序 —— 这是拆分方案里唯一要单独裁的一刀。
2. **Scala 3 的 `CanEqual`(multiversal equality)解决的是另一个问题**:默认全域相等会让
   `Dog == Cat` 编得过。机制是「默认宽松 + `import scala.language.strictEquality` 可选严格」。
   Dawn 的痛点不是「不该比的比了」,是「比了但两个后端答案不同」,所以这条不直接适用 ——
   但它示范了「相等的严格性可以是可选的」这条设计空间,记在这里备查。
3. **B(推断 bound)没有先例可抄。** Haskell 只在无签名时推断,写了签名就得写约束;
   Dawn 签名必写,采用 B 等于让函数的 ABI 依赖函数体,是逆着语言已有的显式取向走。

## 来源

- Jane Street, *The perils of polymorphic compare* — https://blog.janestreet.com/the-perils-of-polymorphic-compare/
- OCaml Stdlib 手册(`compare` 的函数值/循环结构条款)— https://ocaml.org/manual/5.1/api/Stdlib.html
- `ppx_compare` — https://github.com/janestreet/ppx_compare
- Rust `std::cmp::Eq`(自反性与 `f64`)— https://doc.rust-lang.org/std/cmp/trait.Eq.html
- Kotlin 官方文档 *Numbers*(浮点比较的静态类型/泛型分裂)— https://kotlinlang.org/docs/numbers.html
- Kotlin 官方文档 *Equality* — https://kotlinlang.org/docs/reference/equality.html
- JetBrains KTIJ-11497(生成的 `equals` 用 IEEE,与 `Double.equals` 不一致)— https://youtrack.jetbrains.com/issue/KTIJ-11497/
- Swift Evolution SE-0283 *Tuples are Equatable, Comparable, Hashable*(已通过、未实现)— https://github.com/swiftlang/swift-evolution/blob/main/proposals/0283-tuples-are-equatable-comparable-hashable.md
- Swift Forums, *Tuples conform to Equatable* — https://forums.swift.org/t/tuples-conform-to-equatable/32559
- Scala 3 *Multiversal Equality* — https://docs.scala-lang.org/scala3/reference/contextual/multiversal-equality.html
- Go blog, *All your comparable types* — https://go.dev/blog/comparable
- golang/go#20660 *proposal: spec: disallow NaN keys in maps* — https://github.com/golang/go/issues/20660
