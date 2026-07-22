# M7 自举前置：缺口清单与修复计划

> 依 [`bytes-design.md`](bytes-design.md)（序 4）、[`unwrap-design.md`](unwrap-design.md)（序 5）
> 的先例：**动码前先出草案**。
>
> [`m7-progress.md`](m7-progress.md) 记的是 **M6 复盘**的修复清单（序 1–6），那张表只剩序 6。
> 但那不是**自举**的清单——自举有它自己的坎，本文件是把 Kotlin 编译器实际用到的构造
> 逐条拿去问「Dawn 写得出来吗」得出的。所有计数都是 grep 实数，所有耗时都可用
> `scripts/bench-map.dawn` 复跑。

## 一、结论先行

一句话：**两个阻塞项都已落地——位运算符（§四）和 Map 复制写入（§二，换成持久 HAMT，
形状 C 48742ms→10ms）。** Map 那个曾牵出一个架构决定（§三，AST 不可变→选甲），那决定仍成立，
但如今是「type 分两棵树更干净」的设计理由，不再是「否则 O(n²)」的性能生死——HAMT 已让形状 C
不再致命（见 §二末的复盘）。**语言层面的自举前置到此清零，剩下是自举本身的实现活。**

| 类 | 缺口 | 判定 |
|---|---|---|
| A1 | 位运算符 | ✅ 已落地（2026-07-21，见 §四）。曾是唯一零逃生口 |
| A2 | Map 复制写入 | ✅ 已落地（2026-07-21，HAMT，见 §二）。形状 C 48742ms→10ms |
| A2′ | AST 不可变 | 🟢 已定架构（选甲，§三），属自举实现，非语言缺口 |
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

### ✅ 已落地（2026-07-21）：换成持久 HAMT

Map/Set 从 copy-on-write 换成 [`DawnMap`](../compiler/src/main/java/dawn/rt/DawnMap.java)/
[`DawnSet`](../compiler/src/main/java/dawn/rt/DawnSet.java)——32 路分支的 hash array
mapped trie，`assoc` 只复制根到叶那条路（约 `log32 n` 个小节点），O(n) 复制没了。
二者 `implements java.util.Map/Set`，故 `genMapsClass` 里所有读路径（get/keys/values/
entries/size/index/show）**一字未改**；只有 empty/insert/remove/from 六个写路径改成走
持久原语。插入序靠每个活键的 `seq` 保留（更新复用旧 `seq`→保位），相等继承 `AbstractMap`
的顺序无关语义（spec §2.2 全项对齐）。

同一支 `bench-map.dawn`，换实现后：

| 项 | copy-on-write | HAMT |
|---|---|---|
| ① 增长 map @80k | 21,118 ms | **8 ms**（与 List 同量级） |
| ② vs 就地 LinkedHashMap @80k | 28,246 ms | 24 ms（持久开销，可接受） |
| ③ 形状 C @100k | 48,742 ms | **10 ms** |

验证：`DawnMapTest`（含 6 万次随机 assoc/without 对拍 `LinkedHashMap`、全 hash 碰撞链压测）+
golden `run/map_persistence`。

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

> **HAMT 落地后的复盘（2026-07-21）**：理由一（解耦风险）已兑现——Map 重写完成，
> 自举不再被它卡。同时它**抽掉了「选甲否则 O(n²)」的性能论据**：形状 C 现在 10ms，
> 乙（节点键侧表）不再是性能陷阱。**但选甲的裁决不变**——理由二（类型系统保证分刀，
> 而非靠约定）是设计质量论据，与性能无关，独立成立。即：甲仍赢，只是现在赢在干净，不再赢在快。

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
Dawn 是绿地，按 Rust 的整套顺序：按位**紧于比较**（除掉这个坑）、移位紧于按位、
算术又紧于移位。落地后的阶梯（`spec.md §4.3`，数字越大越紧）：

```
4   == != < <= > >=      比较（不结合）
5   |                    按位或           新
6   ^                    按位异或         新
7   &                    按位与           新
8   << >> >>>            移位             新（>> 算术、>>> 逻辑）
9   ++                   连接
10  + -
11  * / %
12  not、一元 -、~        前缀（~ 新）
```

不变量：按位 `& ^ |` 紧于比较、松于连接/算术；`&`>`^`>`|`；移位紧于按位、松于连接；
`~` 前缀，与 `not`/一元 `-` 同槽。故 `a & b == c` = `(a & b) == c`、`1 + 1 << 4` = `(1+1) << 4`。

### ✅ 已落地（2026-07-21）

四刀全兑现，一趟过 60+ 测试，新增两个 golden（`run/bitwise_operators`、
`errors/type_bitwise_non_int`）：

- `Token.kt` `AMP CARET TILDE SHL SHR USHR` / `Lexer.kt` `>>>` 三字符前置探测 + `<<`/`>>`
  进两字符表 + `& ^ ~` 单字符 + `continuesLine`。
- `Parser.kt` `borExpr→bxorExpr→bandExpr→shiftExpr` 四层夹在 `cmpExpr` 与 `concatExpr` 之间，
  `~` 进 `unaryExpr`。（**运算符非一等函数值**——Dawn 无运算符 section 语法，无需 handle。）
- `Checker.kt` `bothInt()`（仅 `Int`）+ `UnOp.BNOT`；`CodeGen.kt` `LAND/LOR/LXOR`、移位前
  `L2I` 收窄计数、`~x` = `x ^ -1L`；`Comptime.kt` `bitwise()` 折叠 + `inv()`。
- `Formatter.kt` 新符号进 continuation 两集、`~` 贴操作数；`spec.md §4.3` 优先级表重排。

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
2. ~~位运算符~~ ✅ 已落地（2026-07-21，见 §四）。四刀一趟过，零逃生口这项就此消解。
3. ~~持久 Map（HAMT）~~ ✅ 已落地（2026-07-21，见 §二末）。形状 C 48742ms→10ms，
   O(n²) 消解。P0 地基三项到此清零。

### P0.5 · 定 AST 架构 —— **选甲（多棵 AST）** ✅ 草案已出

定稿在 [`selfhost-ast.md`](selfhost-ast.md)：`Parsed*` → `Typed*` 双树、checker 是
lowering 一刀、四刀与树的对应一页图，并穷举核对 `ast/Ast.kt` 的 44 个 `var` 槽全部有主。
完整节点表留待 P3 随真代码收敛。

### P0.6 · 自举前清障批 ✅ 完成（2026-07-22，v0.3.0）

设计审查（对照语言设计文献）翻出的账在 parser 还唯一时一次结清，十刀：

1. **数值边缘语义写死**（spec §4.3）：溢出环绕、`/` 向零取整、`%` 随被除数；
   除零改真 panic（裸 ArithmeticException 会被 `java_try` 误捕）；Float cmp 换
   `Double.compare` 全序（DCMPL 在 NaN 两侧同号，排序失反对称）。
2. **Float/Bytes 禁作 Map/Set 键**（递归含嵌套，spec §2.2）——两套相等/同一性哈希
   的静默丢键从「不宜」升级为编译错误。
3. **`alias` 独立关键字**（spec §2.6）：同形不同义的启发式删除；用户类型首次可别名。
4. **字段调用同名冲突改报错**（spec §2.4）：对齐 §10.3 模块别名的处理。
5. **`break`/`continue`**（spec §4.7）：Never 表达式，三种循环 + comptime，禁穿 lambda。
6. **行首 `.` 续行**（spec §1.7）：竖排方法链，Java builder 不再一行到底。
7. **`Cursor` 不透明类型**（spec §11）：游标契约进类型系统；家族回迁内建
   （builtins→std 的第一个有据例外，判据记入 builtins-to-stdlib.md 补记）；
   新原语 `cursor_skip` 消掉 split 曾默许的那次游标算术。
8. **定夺记录**（design.md D10）：match 箭头 / 否定三写法 / `..` 三用维持现状并归档。
9. **stdlib 命名定夺**（[`stdlib-naming.md`](stdlib-naming.md)）：初版「平铺名永久
   有效」当日被否决——**要优雅，接受破坏性更新**。改定破坏性路线：std 收进真模块
   （`use std/map` → `map.insert(...)`，热名选择性引入），平铺前缀名分两版退役。
   实施单列为 **P0.7**（见下），仍在自举 P1 之前。
10. 发版 v0.3.0（破坏性：`alias`/`break`/`continue` 成关键字、cursor 家族签名换
    `Cursor`），backend-dawn 同步迁移。

### P0.7 · stdlib 破坏性重组为模块限定式（已完成）

设计见 [`stdlib-naming.md`](stdlib-naming.md)，实施记录：

1. **捆绑 std 可 `use`**：`use std/x` 命中 jar 资源（loader 跳过磁盘、checker 唯一
   报错点；`src/std/` 磁盘路径保留）；限定/选择性引入走既有 §10.3 机制。comptime
   的函数查找改按 owner（跨模块短名重名 `map.insert`/`set.insert` 必需）。
2. **顶层遮蔽内建/std 函数名合法**（Rust 式）：注册期两处报错删除；codegen 的
   builtin 分派从按名改为按 checker 解析结果（`e.sig.isBuiltin`）。
3. **键类型检查改挂实例化**：`KEYED_CREATORS` 点名删除，改为「泛型调用实例化出的
   结果类型里每个 Map/Set 都查」——用户包装函数首次也被抓（golden 锁定）。
4. **std 重组**：str/bytes/io/list/map/set/cursor 七模块短名；隐式面钉死 v0.3 平铺
   拼写（防 `len`/`get` 被短名顶掉），非 prelude 每处警告一次（`DiagnosticSink.warn`
   首个用户）；改名件走 `std/legacy` 转发。v0.4.0 双拼写 → v0.5.0 删平铺。
5. 两仓迁移：examples/site/playground（25 文件）与 backend-dawn；教程补
   循环/alias/Cursor/std 模块章节；spec §10.6 重写、§11 全部改限定拼写。

自举编译器直接用新拼写书写。

### P1 · 第一刀：Lexer（试水）✅ 完成（2026-07-22）

488 行。选它因为它**不依赖 P0 之外的任何东西**：游标已有（v0.2.1）、不吃 Map 性能、
不碰数组。验收：golden 对拍——同一批 `.dawn` 源，Kotlin 版与 Dawn 版 token 流逐字节比。

> **这一刀的真正产出不是 lexer，是缺口清单。** 切完回头修订 B1/B2/B3 的优先级。

**实施记录**：

- 落点 `selfhost/`（`src/token.dawn` 74 个 TokKind + 关键字表；`src/lexer.dawn` 词法器
  主体 + 26 个内联测试；`src/dump.dawn` 规范 dump；`src/main.dawn` 入口）。
- 金标准是新增的隐藏命令 **`dawn __lex`**（`cli/LexDump.kt`）：token 流 + 诊断的规范行格式。
  `scripts/selfhost-lex-diff.sh` 对全仓 323 个 `.dawn` 文件（std 源、examples、site、
  playground、golden 全部 + 可选外部语料 backend-dawn）双跑逐字节 diff，已进 CI。
- **表示**：Kotlin 版直接按 UTF-16 下标；`Cursor` 刻意不透明拿不到整数，Dawn 版改为
  开头一次 `code_points` + 平行的 UTF-16 偏移表（`offs[i]`），span 从表里读，与 Kotlin
  逐字节一致。字符分类走 `Character.isLetter/isDigit/...`（`unsafe_pure` 包裹）保证
  Unicode 语义精确对齐。
- **控制流移植**：Kotlin 用可变 pos + 异常做中止恢复；Dawn 版每个 helper 返回新位置，
  中止型失败返回 `Err((失败位置, Diag))`——**失败位置必须随错误返回**，否则 EOL 重同步
  从 token 起点开始，三引号/反引号扫到 EOF 的用例会把后面的行重新词法化（golden 对拍
  抓出来的唯一分歧，两处）。
- **顺手修掉 Kotlin 版两个崩溃**（移植即审计）：`\u{}` 码点越界/负值 → 未捕获
  IllegalArgumentException；`1e`/`2.5e+` 裸指数 → 未捕获 NumberFormatException。
  均改为正常诊断，`LexRecoveryTest` 锁定。
- **缺口清单（本刀实测）**：语言层面零新缺口——tuple 返回值 + `?` 传播 + `break`/
  `continue`/`return` + char 字面量足以直译;唯一别扭处是限定名不能当函数值(`filter`
  的谓词得包 lambda)。B1(值类型特化)的判断材料:词法整仓 323 文件 ~2s,分配无感,
  **lexer 一侧不构成推动序 6 的证据**,决定权移交 P3/P4 的实测。

### P2 · 表示层

拿 P1 的数据决定序 6（B1）范围——§三选甲提高了分配量，但**不预判**，等实测。
同期做 trait v2（B2），它是 `m.get(k)` 与迭代器协议的前置，P3 两刀都吃它。

### P3 · 第二、三刀：Parser + Checker ✅ 完成（Parser 2026-07-22，Checker 2026-07-22）

1,214 + 2,779 行。P0 的持久 Map 与 P0.5 的双树架构在这里验收。
golden：AST dump **加诊断文本**逐字节对拍——编译器的错误信息是它一半的价值，
回归了不会有别的测试告诉你。

**Parser 半刀 ✅ 完成（2026-07-22）**：

- 金标准 `dawn __parse`（`cli/AstDump.kt`，规范行格式：每节点一行 + 缩进 + span），
  `scripts/selfhost-parse-diff.sh` 全语料（327 文件，含全部错误恢复 golden）逐字节
  对拍全绿，已进 CI。
- 落点 `selfhost/src/{ast,parser,astdump,parser_test}.dawn`。AST 按 P0.5 选甲：
  **纯解析树**，Kotlin `Ast.kt` 的 44 个 checker `var` 槽一个不带。
- 移植法：可变 pos + sink + 异常 → `St { pos, diags }` 状态线程 +
  `PR[T] = Result[(St, T), (St, Diag)]` + `?` 当 throw 用；`Err` 携带失败点状态
  （P1 的教训直接复用，对拍一次通过）；`noStructLit` 成员改 `ns` 参数线程。
- Dawn 语言笔记（写 1,900 行编译器代码的实感）：match 臂体只收表达式——赋值 /
  `for` / `assert` 语句都要包 `{ }`；`alias` 等关键字不可作变量名；跨模块 `use` +
  74 个构造器的选择性引入完全够用。仍无新语言缺口。

### P4 · 第四刀：CodeGen ✅ 完成（2026-07-22）

4,010 行，最大的一刀，也是唯一大量 `use java`（ASM）的一刀。**验收最硬**：编译产物
`.class` 逐字节比——已达成。落点 `selfhost/src/{codegen,emit,vendor}.dawn`（共
~5,300 行）+ 共享 `dawn.tool.AdtClassWriter`（两边同一个 frame writer，钉平
COMPUTE_FRAMES）。金标准 `dawn __emit`；`scripts/selfhost-emit-diff.sh` 全语料
（examples 全部 + site 99 类 + playground 91 类）逐字节全绿，进 CI。
过程账在 [`selfhost-codegen.md`](selfhost-codegen.md)。

### P5 · 固定点 ✅ 完成（2026-07-22）

stage0（Kotlin）发射 selfhost → stage1；selfhost 发射自己（432 类）与 stage1
逐字节一致 = stage2；再用 stage2 的类跑同一发射，stage3 与 stage2 逐字节一致。
`scripts/selfhost-fixpoint.sh`，进 CI。**Dawn 编译器已自举。**
尚欠（非阻塞）：selfhost 自打独立 jar（AdtClassWriter 还住在编译器 jar 里）；
Kotlin 版随后可冻结为 bootstrap 种子（学 Go 保留 go1.4）。

## 八、不做的（记录理由）

- **为编译器开可变集合的口子**。Dawn 的内核是不可变 + 无运行期崩溃；为了写自己的编译器
  破例，等于承认这套设计写不了正经程序。§三选甲正是为了**不必**破这个例。
- **`@NonNull` 第三方 jar 识别**——[`m7-progress.md`](m7-progress.md) 已记：与痛点不相交。
- **移植那 49 个 `var` 字段的可变 AST 架构**——见 §三理由二，那是债不是特性。
