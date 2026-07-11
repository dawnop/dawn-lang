# M3 执行规划（体验：不让人骂人）

> 本文是 M3 的**逐刀执行手册**，写给执行代理（可能是较小的模型）逐字照做。
> 语义权威在 [spec.md](spec.md)，"为什么"在 [design.md](design.md)；与本文冲突时以 spec 为准，
> 但**发现冲突先停下来报告**，不要自行仲裁。
> M3 完成后本文件删除（决策沉淀进 design.md，本文只是施工图）。

## 0. 全局约定（每一刀都适用，违反任何一条都算失败）

1. **环境**：构建前必须
   `export JAVA_HOME="$HOME/tools/graalvm-community-openjdk-21.0.2+13.1/Contents/Home"`。
   用系统 `gradle`（`/opt/homebrew/bin/gradle`），仓库**没有** `./gradlew`。
   - 构建 fat jar：`gradle :compiler:fatJar`
   - 全部测试：`gradle :compiler:test`
   - 跑样例：`./bin/dawn run examples/calc.dawn "2+3*4"`
2. **一刀一个 commit**，测试全绿才许提交。当前基线 **176 项测试全绿**，只增不减。
   commit message 用英文、祈使句、首行 ≤72 字符；**绝对不加 `Co-Authored-By: Claude`**
   （任何形式的 AI 署名都不加）。
3. **语言约定**：代码注释 / 报错信息 / CLI 输出**一律英文**；`docs/` 下的文档**中文**。
   教程（刀 7）里的示例代码注释可用中文（面向中文读者），`examples/` 里保持英文。
4. **spec 先行**：任何本文没钉死、spec 也没写的语义决策——**停下来问用户**，
   不要自己拍板。已钉死的决策在同一刀的 commit 里同步写进 `docs/spec.md`（和
   `docs/grammar.ebnf`，若涉及语法）。
5. **不许静默删测试**：旧测试若因语义升级而失效，改写成新语义的正面/负面用例并在
   commit message 里说明，不许直接删。
6. **LSP 横向轨道**：凡新增 AST 节点或语法，同一刀内更新
   `compiler/src/main/kotlin/dawn/lsp/AstQuery.kt` 的 visit 分支（悬停/跳转不留死角）。
7. **动手前先读**：每刀列有「先读」清单，读完再写。`Checker.kt`/`CodeGen.kt` 都很大，
   用 grep 定位，不要整读。
8. 顺序**不可调换**：刀 3–5 会新增语法，刀 6 的 `dawn fmt` 必须在语法冻结之后做，
   否则 fmt 要返工两次。

## 1. 刀序总览

| 刀 | 内容 | 交付物 | 预估规模 |
|----|------|--------|----------|
| 1 | golden 报错测试基础设施 + 锁现状 | `GoldenErrorTest.kt` + ≥30 个用例 | 小 |
| 2 | 报错信息打磨（did-you-mean、hint 补齐） | 全类别 golden 覆盖 | 中 |
| 3 | 构造器作函数值 | `map(xs, Some)` 可用 | 小 |
| 4 | 效果并 `!(e1\|e2)` | compose 场景可表达 | 中 |
| 5 | `derive Show` | 用户类型可 `to_string`/插值 | 中 |
| 6 | `dawn fmt`（含 `--check` 与 LSP formatting） | 全 examples 幂等 | 大 |
| 7 | 教程初稿 + doc-test 抽取编译 | `docs/tutorial.md` | 中 |
| 8 | 收尾：README/design.md、native 冒烟 | 里程碑关闭 | 小 |

M3 总验收（design.md 原文）：**报错 golden 套件 + fmt 幂等性测试全绿**。

---

## 刀 1 —— golden 报错测试基础设施

**目标**：把「报错质量」变成可回归的资产。先锁现状，刀 2 的打磨才能看 diff 说话。

**先读**：`compiler/src/main/kotlin/dawn/diag/Diag.kt`（`Diagnostic.render` 就是 golden
的输出格式）、`compiler/src/test/kotlin/dawn/ExamplesTest.kt`（相对路径的处理套路：
gradle 跑测试时 cwd = `compiler/`）。

**做什么**：

1. 新建目录 `compiler/src/test/resources/golden/errors/`，每个用例一对文件：
   `<case>.dawn`（触发错误的源码）+ `<case>.err`（期望输出）。
2. 新建 `compiler/src/test/kotlin/dawn/GoldenErrorTest.kt`：
   - 枚举目录下所有 `.dawn`（`File("src/test/resources/golden/errors")`，参考
     ExamplesTest 的 cwd 处理），对每个文件跑 `analyze(text)`；
   - 期望输出 = 所有 diagnostics 按 span.start 排序后 `render(SourceFile(...))` 拼接。
     **路径归一化**：构造 `SourceFile` 时固定用 `"<case>.dawn"` 作 path（不带目录前缀），
     保证 `.err` 内容与机器无关；
   - 与 `<case>.err` 逐字节比对（统一 `\n`，文件尾恰好一个换行）；
   - **再生模式**：`gradle :compiler:test -DupdateGolden=true` 时不比对而是重写 `.err`。
     再生后必须人工过一遍 `git diff` 再提交，禁止盲刷。
   - 用 JUnit 动态测试（`@TestFactory` + `DynamicTest`）让每个 case 单独显示成一项。
3. **种子用例 ≥30 个**，覆盖每个错误类别（grep `sink.error(` 和 `DawnError(` 得到
   完整清单，按下面分组各写 2–4 个）：
   - 词法：未闭合字符串、非法转义、未闭合 `"""`；
   - 语法：缺右括号、顶层非法声明、match 缺箭头、const 非全大写；
   - 类型：类型不匹配、未知变量、未知函数、实参个数不对、构造器字段错、
     元组元数不符、`==` 比函数；
   - 效果：纯函数体内调 `!io`、效果变量不匹配；
   - 穷尽性：ADT 缺构造器、列表缺长度（`[]` / `[_, _, ..]` 见证）、Bool 缺分支；
   - 模式：let 解构用了可反驳模式、重复绑定；
   - `?` 传播：在非 Option/Result 上用、lambda 返回类型未知时用；
   - comptime/const：除零、fuel 耗尽、panic、引用后声明的 const、类型不可常量序列化；
   - Java 互操作：类不存在、无匹配重载、重载歧义、char/数组返回。

**验收**：`gradle :compiler:test` 全绿（含新增 ≥30 项动态测试）；`-DupdateGolden=true`
再跑一遍后 `git diff` 为空（证明再生是幂等的）。

**commit**：`Golden error-message test harness with ~30 seed cases`

---

## 刀 2 —— 报错信息打磨

**目标**：对标 Gleam/Rust——每条错误指向源码、说人话、**给出改法**（hint）。

**先读**：`Diag.kt` 的 `Diagnostic`（已有 `hint` 字段和 `= hint:` 渲染）；grep
`sink.error(` 全清单（Checker/Parser/Lexer/Comptime/Exhaustive）。

**做什么**：

1. **hint 补齐**：逐条过 `sink.error(` 调用点，凡是「用户能明确改什么」的错误都补
   hint（祈使句英文，如 `add \`!io\` to the enclosing function's signature`）。
   纯陈述型错误（如内部一致性）可不加，但要在清单里注明理由。
2. **did-you-mean**：新增 `diag/Suggest.kt`，实现 `suggest(name, candidates): String?`
   —— Levenshtein 距离 ≤ 2（且 ≤ name.length/2）取最近者。接到四类查找失败上：
   未知变量/函数（候选 = 作用域内绑定 + 顶层函数 + 内建名）、未知构造器/类型
   （候选 = 已声明类型与构造器 + prelude）、未知 record 字段、未知 ADT 字段名。
   hint 形如 `` did you mean `parse_int`? ``。
3. **风格统一**（写成注释钉在 Diag.kt 顶部，作为后续所有报错的 style guide）：
   - message 小写开头、一句话、不带句号；代码片段用反引号；
   - hint 是「怎么改」不是「哪里错」，祈使句；
   - 类型显示用 Dawn 语法（`List[Int]` 而非内部名）——检查现有 `Type.toString`
     是否已如此，不是就修。
4. 每处改动**同步更新/新增 golden 用例**；本刀结束后 golden 用例数应明显增长
   （目标 ≥45），且每个 did-you-mean 场景各有一个用例。

**验收**：golden 全绿；抽查 5 条 diff 确认新消息确实更好（commit message 里贴 1–2 个
before/after 例子）。

**commit**：`Polish diagnostics: fix hints everywhere actionable, did-you-mean suggestions`

---

## 刀 3 —— 构造器作函数值

**目标**：`xs |> map(Some)`、`map(shapes, Circle)` 这类把 ADT 构造器当函数传的写法成立。

**先读**：Parser.kt 中裸 `Some` 已解析为 `CtorCall(name, emptyList(), hasParens=false)`
（Parser.kt 约 570 行）；Checker.kt 的 `checkFnValue`（M2 里内建/顶层函数作值的入口，
含「泛型按期望类型实例化」）与 `checkCtorCall`；CodeGen.kt 的 `genFnValue` /
`genBuiltinBridge` / `pendingBuiltinBridges`（桥接方法的现成套路）。

**做什么**：

1. **checker**：当 `CtorCall(hasParens=false)` 出现在期望类型为 `TFn` 的位置、且名字
   解析为**带字段的 ADT 构造器**时，走函数值路径：参数类型 = 构造器字段类型、返回
   类型 = 所属 ADT；泛型 ADT（如 `Some`）按期望 TFn 合一实例化（复用 `checkFnValue`
   的实例化逻辑）。注意：
   - **无字段构造器**（`Red`）本来就是值不是函数——期望 TFn 时报错并给 hint；
   - record 类型**不做**（record 用字面量语法构造，没有裸名歧义；spec 不承诺）；
   - 与 M2 的 const 解析（`CtorCall.constDecl`）共用裸 TYPEIDENT 路径，注意分支先后：
     先查 const，再查构造器。
2. **codegen**：仿 `genBuiltinBridge`——为被用作值的构造器生成静态桥接方法
   `dawn$ctor$<AdtName>$<CtorName>(field...) -> Adt`（体 = new + init），LMF 指向它；
   桥接去重、挂进现有 pending 队列在 `drainLambdas` 里排空。
3. **spec**：§4.5（或函数值所在小节）补一句「构造器可作函数值」；grammar 无需改
   （语法本来就通）。
4. **测试** `CtorValueTest.kt`（≥6）：`map(xs, Some)`；管道 `|> map(Circle)`；泛型
   实例化（`Option[Int]`）；嵌套（`fold` 里用）；负例：无字段构造器作 TFn、
   构造器字段数与期望 TFn 参数数不符（golden 用例 +2）。
5. **LSP**：AstQuery 对该场景悬停显示构造器签名（若现有 CtorCall 分支已覆盖则确认即可）。

**验收**：测试全绿；`design.md` M1 尾巴清单里「构造器作函数值」可以划掉（刀 8 统一改）。

**commit**：`Constructors as first-class function values`

---

## 刀 4 —— 效果并 `!(e1|e2)`

**目标**：高阶函数能表达「我的效果 = 两个函数参数效果之并」，如
`fn compose[A,B,C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1|e2)`。

**语法已在 grammar.ebnf 钉死**（第 33–35 行）：`"!" "(" effect_atom { "|" effect_atom } ")"`，
atom = `io` 或效果变量。

**先读**：`Types.kt` 第 10–30 行——现状 `sealed class Eff { Pure, Io, Var(name) }`，
已有 `lubEff(a, b)` 和 `substEff`；Checker.kt 里效果检查/实例化的调用点（grep `Eff.`、
`lubEff`、`substEff`）。

**做什么**：

1. **表示**：`Eff` 新增 `class Union(val vars: Set<Var>, val io: Boolean)`，并写
   **规范化构造器** `Eff.union(atoms: List<Eff>): Eff`：
   - 含 `Io` → 若无变量直接 `Io`，有变量则 `Union(vars, io=true)`…… **不对，钉死更简单的
     语义**：`io` 吸收一切——含 `Io` 就是 `Io`；
   - 全 `Pure` → `Pure`；单个变量 → 该 `Var`（不包 Union）；
   - 多个不同变量 → `Union(vars, io=false)`（io 字段可以省掉，直接 `Union(vars: Set<Var>)`）。
   - 结构相等按集合比（`equals`/`hashCode` 认真写，TFn 相等性依赖它）。
2. **substEff** 扩展：对 Union 逐 atom 代换后重新 `Eff.union(...)` 规范化
   （代换结果可能引入 Io 或合并成单变量）。
3. **lubEff** 扩展成对 Union 正确的 join（Pure 是幺元、Io 是吸收元、Var/Union 并集）。
4. **subsumption**：调用点效果检查处，`Union` 允许出现在纯上下文**当且仅当**其全部
   变量都实例化为 Pure；报错消息里显示规范化后的效果（`!(e1|e2)` 形式）。
5. **parser**：效果位置解析 `!( atom | atom ... )`；单 atom 带括号也允许（解析后
   规范化掉）。`Eff` 的显示（toString/悬停）输出 `!(e1|e2)`，变量按名字典序。
6. **spec**：§效果小节（grep `效果变量`）补「效果并」语义段：规范化规则（io 吸收、
   pure 幺元、单变量降级）+ compose 例子。
7. **测试** `EffectUnionTest.kt`（≥7）：compose 两纯函数 → 结果可在纯上下文调用；
   pure+io → 调用处必须 `!io`；io+io → io；同一变量并自身 → 降级为单变量；
   三元并；负例：纯函数体内调用 union 实例化出 Io 的结果（golden +1）；
   悬停显示规范化形式（AstQuery 单测或手动验证后在 commit message 注明）。

**陷阱**：`Eff.Var` 目前用 `name` 做同一性——签名内共享、调用点实例化的机制别破坏；
Union 的 `vars` 集合里存的必须是**同一批** Var 实例/名字，实例化映射 `effMap` 的 key
类型是 `Eff.Var`，确认 `equals` 语义（读 Types.kt:17 附近，Var 可能是引用相等——
若是引用相等，Union 的集合语义要跟着用同一套判等，不要想当然改成按名相等）。

**commit**：`Effect union !(e1|e2) with normalization`

---

## 刀 5 —— `derive Show`

**目标**：`type Color = | Red | Green | Blue derive Show` 之后，`to_string(c)`、
字符串插值 `"{c}"`、`println` 皆可用。这是自举时调试打印 AST 的刚需（design.md M3）。

**语法权威**：spec §4.3 已钉死——`type` 声明尾部 `derive Show`，v0.1 仅有 `Show`。
grammar.ebnf 若缺 `derive` 产生式，本刀补上。

**先读**：Checker.kt:764 `checkPrintable`（现状哪些类型可打印、错误消息长什么样）；
CodeGen.kt 里 ADT 构造器类的生成处（grep `equals` ——结构相等怎么生成的，toString
照同一个模子）；`to_string` 内建的 codegen 路径（grep `to_string`）。

**钉死的输出格式**（同步写进 spec §4.3）：

- 无字段构造器 → `Red`；
- 位置字段构造器 → `Circle(1.0)`（逗号+空格分隔）；
- 命名字段（record 及命名字段构造器）→ `Point { x: 0.0, y: 2.5 }`；
- 字段值递归渲染：`String` 字段**带双引号并转义**（`"a\nb"` 风格，同源码字面量）；
  `Int`/`Float`/`Bool` 同现有 `to_string`；List → `[1, 2]`；元组 → `(1, "a")`；
  嵌套 derive 类型递归。
- 即：目标是「合法的 Dawn 源码形状」（Rust 的 `Debug` 观感）。

**做什么**：

1. **parser/AST**：`TypeDecl` 加 `derives: List<String>`（span 留好）；解析 `derive`
   后跟 TYPEIDENT，非 `Show` 报错（hint: only `Show` exists in v0.1）。record 类型声明
   同样支持。
2. **checker**：
   - `checkPrintable` 放行「derive Show 的用户类型」；泛型类型可打印当且仅当类型
     实参都可打印（`Option[fn(Int)->Int]` 不可打印——现有内建容器应已如此，对齐）；
   - derive 站点校验：每个字段类型必须可打印（函数类型必炸），错误指向字段、
     hint 说明哪个字段挡路（golden +2：函数字段、未 derive 的嵌套类型字段）。
   - 嵌套：字段是另一个用户类型时，要求那个类型也 derive Show（错误提示加 hint:
     `` add `derive Show` to type `Inner` ``）。
3. **codegen**：给每个构造器/record 类生成 `toString()` 覆写（ASM，StringBuilder 拼接，
   模仿现有 equals 生成器的结构）；`to_string` 内建对 derive 类型直接
   `invokevirtual toString`。字符串字段的引号/转义在生成的 toString 里做（可生成
   调用 `dawn/rt/Strings` 的静态辅助 `showString(String): String`，在 genStringsClass
   里补这个方法，避免字节码里写转义循环）。
4. **spec**：§4.3 补输出格式的钉死描述 + 例子；grammar.ebnf 补 `derive` 产生式。
5. **测试** `DeriveShowTest.kt`（≥8）：无字段/位置字段/命名字段/嵌套/泛型
   （`Option[Color]` 打印 `Some(Red)`——注意 prelude 的 Option 是内建渲染，确认两边
   格式一致）/插值/List 内嵌 derive 值；负例：未 derive 就插值（golden 用例更新——
   这条错误现在应带 `` add `derive Show` `` hint）、derive 站点函数字段。
6. **LSP**：TypeDecl 悬停/大纲带出 `derive Show` 标注。

**陷阱**：native-image 封闭世界下 `toString` 覆写完全安全（invokevirtual，非反射）；
但**不要**用 `String.format`（locale 陷阱），Float 渲染必须与现有 `to_string(Float)`
走同一条路径（读现有实现，保证 `1.0` 不变成 `1`）。

**commit**：`derive Show: generated toString for user types`

---

## 刀 6 —— `dawn fmt`（本里程碑最大的一刀）

**目标**：`dawn fmt <file...>` 就地格式化；`dawn fmt --check <file...>` 只检查、不改、
不合格退出码 1 并列出文件。**对全部 examples 幂等**（验收硬指标）。LSP 挂
`textDocument/formatting`。

**架构决策（钉死，不要改走 AST 美打印路线）**：**基于 token 流的重排器**，不是 AST
pretty-printer。理由：AST 打印器要处理全部节点且天然丢注释/空行，token 重排器只做
「间距 + 缩进 + 空行」三件事，语义保真可机械证明，实现量小一个数量级。代价是不做
超长行折行——v0.1 接受（用户自己断的行保留）。

**先读**：`Lexer.kt`（`skipComment` 在第 35 行附近——`#` 行注释目前被丢弃；
`lexTripleString` 多行字符串）；`Token.kt`（token 种类清单）；`Main.kt`（subcommand
分发在 28–33 行）。

**做什么**：

1. **词法层**：Lexer 加可选的注释收集——构造参数 `collectComments: Boolean = false`，
   为 true 时 `skipComment` 把 `Comment(text, span)` 存进旁路列表（**不进 token 流**，
   parser 零改动）。同理收集每个 token 的原始 span（应已有）。
2. **新文件** `compiler/src/main/kotlin/dawn/fmt/Formatter.kt`，入口
   `format(source: String): String`。算法：
   - 词法得到 tokens + comments，二者按 span 归并成一条流；
   - **行结构保留**：两个相邻元素之间在原文里有无换行、有几个空行，是格式化的输入
     信号——同一行的保持同一行，跨行的保持跨行；连续空行压成 1 个（顶层声明之间
     允许 1 个，`import`/`use` 组内 0 个）；
   - **行内间距**：按 token 对查表决定 0 或 1 个空格。规则钉死：二元运算符、`->`、
     `=>`、`=`、`|>` 两侧各 1 空格；`,`/`:` 后 1 前 0；`(`/`[` 内侧 0；`{` 字面量内侧
     各 1（`{ x: 1 }`）；一元 `-`/`not` 后 0/1（not 后 1）；`.`/`?`/调用左括号贴前；
     match 臂 `|` 后 1。拿 `examples/` 现状对照校准——**examples 的既有风格就是规范**；
   - **缩进**：每行缩进 = 2 空格 × 括号深度（`{`/`(`/`[` 进出计数），行首若是
     `}`/`)`/`]` 先减后算；**续行**（行首 token 是 `|>` 或二元运算符或 `.`）+1 级；
     match 臂内的多行体按深度自然成立；
   - **注释**：整行注释缩进对齐当前深度；行尾注释与代码之间正好 1 空格，`#` 后
     正好 1 空格（`#!` shebang 之类不存在，无需豁免）；
   - 行尾空白全删；文件以恰好一个 `\n` 结尾。
3. **多行字符串（最大陷阱）**：`"""..."""` token 内部**一个字符都不许动**——缩进
   重排必须以 token 为单位而非按行 split 源文本；实现上对 token 流重排本来就天然
   安全，但要小心多行字符串使一个 token 横跨多行：其后续行不参与缩进计算，深度
   计数也不受字符串内容里的括号字符干扰（用 token 而不是字符扫描就不会错）。
   插值 `{expr}` 在 M2 里是否被拆成子 token？**先读 Lexer 确认字符串插值的 token
   形态**再动手；若插值段是独立 token，整个字符串 token 组按原样透传。
4. **语义保真的机械证明**（`FmtTest.kt` 的核心断言，对每个输入跑）：
   - `tokens(fmt(src)) == tokens(src)`（种类 + 文本逐个相等，注释与空白除外）；
   - 注释多重集不变（文本逐条相等，顺序不变）；
   - **幂等**：`fmt(fmt(src)) == fmt(src)`。
5. **fixture 测试**：`compiler/src/test/resources/golden/fmt/<case>.dawn`（乱格式输入）
   + `<case>.formatted`（期望输出），≥12 个用例：缩进错乱、运算符无空格、多余空行、
   行尾注释、整行注释、多行字符串内含假括号 `"""){"""`、match 多臂、record 字面量、
   管道链续行、效果并签名、derive 声明、逗号风格。支持 `-DupdateGolden=true` 再生。
6. **全量校验测试**：对 `examples/**/*.dawn` + `golden/errors/*.dawn` 全部跑保真三断言；
   examples 若被 fmt 改动，**把 fmt 结果写回 examples 一并提交**（token 等价性保证
   行为不变，`ExamplesTest` 的 stdout 断言仍须全绿以双保险）。
7. **CLI**：`Main.kt` 加 `"fmt" -> cmdFmt(args.drop(1))`；`cmdFmt`：无参打 usage 退 1；
   `--check` 模式对每个文件比对 fmt(src)==src，不同则打印文件名，最后
   `exit(1 if any)`；默认模式就地写回（内容相同不写，保 mtime）；文件不存在/解析
   失败（词法级错误）报错退 1——**注意 fmt 只需要词法成功**，语法/类型错的文件也要
   能格式化（token 重排器天然支持，别在里面调 analyze）。usage 文本（第 15 行）同步。
8. **LSP**：`Server.kt` 声明 `documentFormattingProvider`，实现 `textDocument/formatting`
   返回单个全文替换 TextEdit（内容未变返回空数组）。
9. **spec**：§2（惯例小节，79 行附近「`dawn fmt` 负责统一」）扩成一小节：钉死缩进
   2 空格、间距规则要点、fmt 不折长行、注释保留。**注**：spec 334 行提到
   `dawn fmt --check` 提示「标了 `!io` 但体是纯的」——该 lint 需要类型分析，**本刀
   明确不做**，在 spec 该行加「（v0.1 未实现）」括注，design.md 记一笔留给 M4+。

**验收**：`./bin/dawn fmt --check examples/**/*.dawn`（zsh 展开或脚本枚举）退出 0；
保真三断言对全部输入通过；全部既有测试绿。

**commit**：`dawn fmt: token-stream formatter, --check mode, LSP formatting`

---

## 刀 7 —— 教程初稿

**目标**：`docs/tutorial.md`（中文），给 M5 语言网站备料；**所有示例代码由测试
机械保证能编译**（诚实教程）。

**做什么**：

1. **章节结构**（每章 300–600 字 + 2–4 个代码块，总量不求全但求准）：
   1. 安装与第一个程序（工具链三命令：run/build/test；hello + 插值）
   2. 值、类型与函数（let/var、Int/Float/Bool/String、函数、管道 `|>`）
   3. match 与穷尽性（字面量/绑定/守卫如有、编译器帮你补分支的卖点展示）
   4. 数据建模：ADT、record、泛型（`Option`/`Result` 引出）
   5. 列表、元组与模式解构（列表模式、let 解构）
   6. 错误处理：`Result` + `?` + `panic` 的边界（D4 的取舍讲清楚）
   7. lambda 与效果系统（纯度卖点：签名即契约、`!io`、效果变量一句带过）
   8. 字符串与标准库巡礼（chars/split/join/parse_int、read_file/args）
   9. comptime 与 const（查找表例子）
   10. 调 Java（use java、null→Option、全部 `!io` 的理由）
   11. test 块与 dawn fmt（工程习惯收尾）
2. **doc-test 基建**：`compiler/src/test/kotlin/dawn/TutorialTest.kt`——
   - 读 `../docs/tutorial.md`（cwd 注意），提取全部 ```dawn 围栏块；
   - 默认断言：`analyze(block)` 无错误。**片段补全**：不含 `fn main` 的块自动包一层
     `pub fn main() -> Unit !io = { <block> }` 再检查？——**不这么做**（太魔法），钉死
     规则：教程里每个 dawn 块必须是**独立可分析的完整程序**（可含 main 可不含——
     顶层只有 fn/type/const 的文件本来就可分析）；表达式级的碎片写进某个 fn 里展示；
   - 逃生门：围栏信息串写 ```dawn skip-check 的块跳过（用于「这样写会报错」的反例，
     反例应尽量配 golden 而不是 skip）；
   - 含 `fn main` 且紧跟 ```output 围栏的块：编译执行（仿 ExamplesTest 的类加载 +
     captureOut），stdout 必须逐字符等于 output 块内容。
3. README「文档」小节加 tutorial 链接。

**验收**：TutorialTest 全绿；`skip-check` 块 ≤3 个。

**commit**：`Tutorial draft with compile-checked code blocks`

---

## 刀 8 —— 收尾

1. **native 冒烟**：`./bin/dawn build examples/calc.dawn --native -o /tmp/calc &&
   /tmp/calc "2+3*4"` 输出与 JVM 一致；shapes 同理。derive Show 的 toString、
   构造器桥接方法都过一遍 native（应当免配置，若 native-image 报缺配置即打回对应刀）。
2. `dawn fmt --check` 对 examples 全过（再确认一次）。
3. **design.md**：M3 小节改「完成，日期」，附各刀 commit 摘要；M1 尾巴清单划掉
   已收编项；把「fmt --check 的 io-but-pure lint」记入后续候选。
4. **README.md**：状态行加 M3；测试数更新（预期 ≥230）；工具链小节加 `dawn fmt`。
5. 删除本文件（`docs/m3-plan.md`）。
6. 全量 `gradle :compiler:test` 最终确认后提交并 push。

**commit**：`M3 complete: golden diagnostics, dawn fmt, ctor values, effect union, derive Show, tutorial`

---

## 附：卡住了怎么办

- 测试失败先怀疑自己的用例期望，再怀疑实现——M2 期间两次「以为编译器错了，
  其实规范如此」（`[a, .., z]` 至少匹配 2 个元素就是一例）。
- Checker/CodeGen 里找不到锚点：grep 本文提到的函数名；它们在 M2 结束时都存在。
- 任何一刀做完发现要回头改前面刀的产物（尤其 golden 期望），允许——golden 就是
  用来一起演进的，但 diff 必须人工看过。
- 遇到本文与 spec 都没钉死的语义问题：**停，问用户**。宁可停一刀，不可自创语义。
