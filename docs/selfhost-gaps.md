# M7 自举前置：缺口清单与修复计划

> 依 [`bytes-design.md`](bytes-design.md)（序 4）、[`unwrap-design.md`](unwrap-design.md)（序 5）
> 的先例：**动码前先出草案**。
>
> [`m7-progress.md`](m7-progress.md) 记的是 **M6 复盘**的修复清单（序 1–6），那张表只剩序 6。
> 但那不是**自举**的清单——自举有它自己的坎，本文件是把 Kotlin 编译器实际用到的构造
> 逐条拿去问「Dawn 写得出来吗」得出的。所有计数都是 grep 实数，所有耗时都可用
> `scripts/bench-map.dawn` 复跑。

## 一、结论先行

一句话：**阻塞项只有两个——位运算符，和「不可变性把编译器逼向 Map 最慢的那个形状」。**
后者不是「Map 慢」那么简单，它牵出一个架构决定（§三），必须在写第一行 lexer 之前定下来。

| 类 | 缺口 | 判定 |
|---|---|---|
| A1 | 位运算符 | 🔴 阻塞。**唯一零逃生口** |
| A2 | Map 复制写入 + AST 不可变 | 🔴 阻塞。见 §二、§三 |
| B1 | 序 6 值类型特化 | 🟠 疼 |
| B2 | trait v2 | 🟠 疼 |
| B3 | 无 `break`/`continue` | 🟠 疼（每日税，非墙） |
| B4 | 无 try/finally | 🟡 `catch_panic` 可凑 |
| B5 | 解释器 TCO | 🟡 comptime 自举时才咬 |
| B6 | 源码包（项目 B） | 🟡 扁平 `src/` 够用 |
| C | 数组 / Int 窄化 / return / sort / 多文件模块 / `char` | ✅ 查过，不是问题 |

## 二、A2 的实测：问题不在「插入多」，在「map 涨不涨」

`CodeGen.kt:265` 的注释自陈：内建 Map「Backed by LinkedHashMap/LinkedHashSet with
**copy-on-write**」——持久接口配复制实现，单次插入 O(n)。

`scripts/bench-map.dawn`（GraalVM 21 / WSL2）：

**① 一个持续增长的 map，对照已线性化的 List**

| n | map_ms | 翻倍比 | list_ms |
|---|---|---|---|
| 5,000 | 184 | — | 1 |
| 10,000 | 516 | 2.8× | 0 |
| 20,000 | 1,500 | 2.9× | 1 |
| 40,000 | 5,269 | 3.5× | 2 |
| 80,000 | **21,118** | **4.0×** | 1 |

翻倍比收敛到 4.0——O(n²) 的签名。List 那列平在 0–2ms，是
[`DawnList` 共享数组窗口](../compiler/src/main/java/dawn/rt/DawnList.java)那次修复的成果，正好当对照组。

**② 同工作量、同键型，唯一差别是复制 vs 就地改写**：80,000 次 → **28,246ms vs 2ms**。

**③ 但形状决定一切**（这条推翻了本文初稿的诊断）：

| 形状 | 插入次数 | 耗时 |
|---|---|---|
| A 作用域栈（5000 个 ×20 条，各自丢弃） | 100,000 | **10–45 ms** |
| B 模块符号表（涨到 4,000） | 4,000 | 75–147 ms |
| C 节点键侧表（涨到 100,000） | 100,000 | **43,288–48,742 ms** |

**A 和 C 的插入次数完全相同，差约 1000×。** 于是本文初稿「Checker 的符号表会 O(n²)」
是**错的**：`Checker.kt:69` 的 `ArrayDeque<HashMap<String, Symbol>>` 恰好是形状 A，
每个作用域小且随即丢弃，它没事。现有 Kotlin 编译器里也**没有**长命的增长表
（`grep "private val .* = HashMap()"` 零结果；所有 `HashMap()` 都在
`Checker.kt:413/557/738/…` 被逐声明重置）。

**那 A2 为什么还是阻塞？** 见下一节。

## 三、真正的坎：不可变性强制选择形状 C

`ast/Ast.kt` 有 **49 个 `var` 字段**。Kotlin 版的架构是——parser 建出带空槽的 AST，
checker 把推断结果**写回节点**，codegen 再读回来：

```kotlin
Checker.kt:1289   e.type = t        // 另有约 15 处同类：call.type / fa.type / d.info / al.resolved
Comptime.kt:79    c.value = ComptimeInterp(...).eval(c.init, HashMap())
```

**Dawn 的 record 不可变，这条路整个走不通。** Dawn 版只有两条出路：

- **甲、多棵 AST**：`ParsedExpr` → `TypedExpr`，每刀产出新树。
- **乙、节点键侧表**：保留一棵树，`Map[NodeId, Type]` 存推断结果——**这正好是形状 C**。

即：Map 的 O(n²) 确实阻塞自举，但**不是因为编译器插入次数多，而是因为不可变性会把你推到
唯一会死的那个形状上**。这是本轮最有价值的发现，记下来免得再走一遍。

### 裁决：选甲（多棵 AST）

**理由一——解耦风险。** 甲让 P0 的 Map 重写从「阻塞项」降级为「优化项」：HAMT 做砸了、
做晚了，自举照样推进。乙是把两个高风险项串联，任一失手全线停摆。

**理由二——那 49 个 `var` 是 Kotlin 版的技术债，不是待移植的特性。** 「AST 节点是可变的、
谁都能往上写字段」意味着「`e.type` 在哪一刀被填的」只能靠读全代码知道；
`recv.type = TUnit` 那种 `// a namespace, not a value` 的注释就是这笔债的利息。
分成 `ParsedExpr`/`TypedExpr` 后，**「这一刀之后类型一定填好了」由类型系统保证**，
不再靠约定。这正是 Dawn 该擅长的事——rustc、GHC 也都是这么分的。

**理由三——代价可控。** 多写一套类型定义，但两棵树共享绝大多数结构；且省掉了
`Map[NodeId, Type]` 的查表开销与「查不到怎么办」的分支。

**代价与风险（记录在案）**：AST 节点数量级的额外分配。这条与 **B1 序 6**（值类型特化 /
物化开销）直接相干——若 P1 试水刀显示分配是瓶颈，序 6 的优先级要提前。
[`seq6-research.md`](seq6-research.md) 自己的教训是「两次预测都被实测推翻」，故此处
**不预判**，留给 P1 的数据。

## 四、A1 位运算符：唯一零逃生口

```
grep -rn "bit_or|bit_and|shift_left|<<|>>" docs/spec.md check/Types.kt  →  零结果
```

`CodeGen.kt` 满屏 `ACC_PUBLIC or ACC_FINAL`——Kotlin 的按位或。Dawn 既无内建，
`use java` 也救不了：`java.lang.Long` 不提供按位方法，JVM 的 `LOR`/`LAND` 只有字节码
指令、没有 API 入口。

窄替代：ACC 标志位互不相交，可用 `+` 冒充 `|`。但哈希、掩码、字符分类位集冒充不了。

**运行期直落**：`Int`（64 位）上 `&|^` → `LAND`/`LOR`/`LXOR`，`<< >> >>>` →
`LSHL`/`LSHR`/`LUSHR`，`~` → `LCONST_1 …` 其实是 `x ^ -1`（`ICONST_M1 I2L LXOR`）。

### 定论：做成运算符，不做内建函数

照 [`unwrap-design.md`](unwrap-design.md) §六 的做法逐条查冲突——结论是**无冲突**，
故按运算符走（内建 `bit_or(bit_or(a,b),c)` 在满屏 `ACC_PUBLIC | ACC_FINAL` 的 codegen 里
不可读，而它买来的「避冲突」并不存在）。

**词法**（`Lexer.kt`）：

| 符号 | 现状 | 加它 |
|---|---|---|
| `\|` | 已是 `PIPE`（:479） | **不动词法**，只在表达式文法加一层优先级 |
| `&` `^` `~` | 未进词法，撞到 `unrecognized character`（:483） | 新增三个单字符 case，纯增量 |
| `<<` `>>` | `<` `>` 是单字符 `LT`/`GT`（:472-473） | 加进 `:448` 的两字符最大匹配表 |
| `>>>` | —— | 三字符，须在两字符表**之前**先探三字符（唯一一处例外，加个 `three` 前置分支） |

**词法零冲突的两个关键**：(1) `&&`/`||` 是 `AMPAMP`/`PIPEPIPE`，两字符最大匹配（:456-457）
**先于**单字符，`a & b` 与 `a && b`、`a | b` 与 `a || b` 各自切分正确；(2) Dawn 类型参数用
`[]` **不用** `<>`（`Map[Int, Int]`），故没有 C++ `Foo<Bar<Baz>>` 的 `>>` 歧义——`<`/`>`
只当比较符，`<<`/`>>` 可安全占两字符。

**文法零冲突**：`PIPE` 现有三处用法**全在非表达式子文法**，都不下降到表达式的二元阶梯——

| PIPE 现用途 | 位置 | 所属文法 |
|---|---|---|
| sum 类型构造子分隔 `type T = A \| B` | `Parser.kt:260,267` | 类型声明 |
| 效果并集 `!(io \| log)` | `Parser.kt:523` | 签名（`->` 之后） |
| 模式或 `case A \| B =>` | `Parser.kt:1059` | 模式（`pattern()`，不解析二元表达式） |

模式那处最像冲突，实则不然：`pattern()` 只认字面量/构造子/绑定，**从不进算术二元层**，
故 `case 1 | 2 =>` 恒是「模式 1 或 模式 2」，无「`1|2` 按位或」的另读。

**优先级**：C 家族把按位放在比较**之下**，留下 `a & b == c` 解成 `a & (b == c)` 的著名坑。
Dawn 是绿地，按 Rust 的做法让按位**紧于比较**除掉这个坑。插进现阶梯（数字越大越紧）：

```
4   == != < <= > >=      比较（不结合，不变）
4.3 |                    按位或           新
4.5 ^                    按位异或         新
4.7 &                    按位与           新
5   ++                   连接（不变）
6   + -
6.5 << >> >>>            移位             新
7   * / %
8   not、一元 -、~        前缀（~ 新）
```

不变量（精确数字是实现细节，这四条是硬约束）：按位 `& ^ |` 紧于比较、松于算术；`&`>`^`>`|`；
移位紧于按位、在乘除附近；`~` 是前缀，与 `not`/一元 `-` 同槽。

**落地点照序 1 的四处注册**：`Types.kt` 签名（`(Int, Int) -> Int`，纯）/ `CodeGen.kt`
`genBinary`（:3657 的 `when(e.op)` 加分支）+ 一等函数值 handle / `Comptime.kt` 常量折叠
（:563 的 `arith` 旁）/ `Doc.kt` 分组 / `spec.md §4.3` 优先级表补三行。`BinOp` 枚举
（`Ast.kt:382`）加 `BAND BOR BXOR SHL SHR USHR`，`UnOp`（:388）加 `BNOT`。

## 五、B 类：会疼，不阻塞

| # | 缺口 | 实据 | 疼在哪 |
|---|---|---|---|
| B1 | 序 6 值类型特化 | [`seq6-research.md`](seq6-research.md)：解析树每值一个堆对象 | 编译器是全仓最 Int 密集的程序。lexer 那半已被 A1 游标（v0.2.1）解掉；parser/checker 还疼，且 §三选甲后**分配量上升**，相干性提高 |
| B2 | trait v2 | 卡在多参数 trait / 关联类型 | 到处 `map_get(env, n)` 写不成 `env.get(n)`；13.5k 行乘这个摩擦 |
| B3 | 无 `break`/`continue` | spec §4.9 明记 v0.1 无 | 140 处 `.add(` 循环里必有提前退出。递归可替代，但这是**每日税** |
| B4 | 无 try/finally | 8 处 `finally` | `catch_panic` 可凑（同 `with_tx` 惯用法），难看 |
| B5 | 解释器 TCO | [`pure-ffi-design.md`](pure-ffi-design.md):447 深递归直接 StackOverflow | 自举后 comptime 解释器也要用 Dawn 写，这次没有 Kotlin 的栈可借 |
| B6 | 源码包（项目 B） | 硬阻塞是 `className=modPath`，见 [`package-design.md`](package-design.md) | 13.5k 行摊在扁平 `src/`——`dawnop-site/backend-dawn` 40 文件已证可行，只是难受 |

**就地累积的量**（供 B3 与 §三互参）：`.add(` 140、`.append(` 98、`HashMap()` 23、
`MutableMap` 15、`MutableList` 7、`ArrayDeque` 5。

## 六、C 类：查过，不是问题（记录理由，免得再查）

- **数组不可创建/索引**（spec §9.5）——全编译器只有 **3 处** `arrayOf(`，全是单元素
  `String[]`（`cw.visit(..., arrayOf(iface))`），`java.lang.reflect.Array` 可绕。
  **不值得为它改语言。**
- **`Int` 64 位、ASM 全是 `int`** —— spec §9.3「精确匹配 `long`/`double` 优于收窄到
  `int`/`float`」，窄化本就支持。
- **`return` / 尾递归 / `sort` / `java_try` / 多文件模块 / `char`** —— 全部够用
  （`char` 用 `cursor_char -> Int`）。

### 一条撤销的记录

初稿曾把「`use java` 可变集合」列为 B3/就地累积的逃生口。**撤销**：spec §9.2 的
「`Object` 形参收不了 `Int`/`Float`/`Bool`」使它对 Int 键值不成立——

```
error: no overload of `LinkedHashMap.put` matches (Int, Int)
  candidates: public java.lang.Object java.util.HashMap.put(Object, Object)
```

而编译器的节点 id、符号 id 全是 Int。只有 String 与引用类型能走这条路。

## 七、计划

**贯穿原则：每阶段先切一刀真代码再补下一批缺口。** 序 4 和序 5 都是被真代码撞出来的，
不是想出来的；本文件 §二 的诊断也是被基准推翻一次才对的。

### P0 · 地基

1. ~~量 Map~~ ✅ 已完成，见 §二。结论改写了 P0 本身。
2. **位运算符**（§四）。工作量小，但 A1 零逃生口，必须先做。**可独立落地，不依赖其他任何项。**
3. **持久 Map（HAMT 或共享桶）**。理由已换成 §三——为了让形状 C 可用。选甲之后它是
   **优化项而非阻塞项**，可与 P1 并行。

### P0.5 · 定 AST 架构 —— **选甲（多棵 AST）**

在写第一行 lexer 之前定死。产出：`ParsedExpr` / `TypedExpr` 的类型定义草案，
以及「哪一刀消费哪棵树」的一页图。

### P1 · 第一刀：Lexer（试水）

488 行。选它因为它**不依赖 P0 之外的任何东西**：游标已有（v0.2.1）、不吃 Map 性能、
不碰数组。验收：golden 对拍——同一批 `.dawn` 源，Kotlin 版与 Dawn 版 token 流逐字节比。

> **这一刀的真正产出不是 lexer，是缺口清单。** 切完回头修订 B1/B2/B3 的优先级。

### P2 · 表示层

拿 P1 的数据决定序 6（B1）范围——§三选甲提高了分配量，但**不预判**，等实测。
同期做 trait v2（B2），它是 `m.get(k)` 与迭代器协议的前置，P3 两刀都吃它。

### P3 · 第二、三刀：Parser + Checker

1,214 + 2,779 行。P0 的持久 Map 与 P0.5 的双树架构在这里验收。
golden：AST dump **加诊断文本**逐字节对拍——编译器的错误信息是它一半的价值，
回归了不会有别的测试告诉你。

### P4 · 第四刀：CodeGen

4,010 行，最大的一刀，也是唯一大量 `use java`（ASM）的一刀。位运算（A1）在此兑现，
3 处数组走 `reflect.Array`。**验收最硬**：编译产物 `.class` 逐字节比。

### P5 · 固定点

照 [`design.md`](design.md) M7 已排定：stage0（Kotlin）编 stage1 → stage1 编自己得
stage2 → stage2 编自己得 stage3，**stage2 与 stage3 逐字节一致**。
然后 Kotlin 版冻结为 bootstrap 种子（学 Go 保留 go1.4）。

## 八、不做的（记录理由）

- **为编译器开可变集合的口子**。Dawn 的内核是不可变 + 无运行期崩溃；为了写自己的编译器
  破例，等于承认这套设计写不了正经程序。§三选甲正是为了**不必**破这个例。
- **`@NonNull` 第三方 jar 识别**——[`m7-progress.md`](m7-progress.md) 已记：与痛点不相交。
- **移植那 49 个 `var` 字段的可变 AST 架构**——见 §三理由二，那是债不是特性。
