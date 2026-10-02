# LSP 悬停与内联提示：设计（A1–A4）

> 状态：current。本线的总纲：除类型之外，hover 与 inlay 还能告诉读者什么、按什么刀序做。
> A1（hover 显示 const 与 comptime 块的值）已落地；A2–A4 落地时回填 §8「状态」，并在这里改写被
> 事实推翻的前提。调研依据是 2026-10-02 的只读调研报告（仓外协作档，结论摘在 §2）。

---

## 1. 问题

今天的 hover 只回类型。光标停在一个常量上，读者看到的是 `const LIMIT: Int`；停在
`comptime { 1 << 20 }` 上，看到的是 `Int`。值明明已经算出来了：每次分析都会对没有类型错误的
模块跑一遍 comptime（`driver/analyze.dawn` 的 `analyze_module_step`，`if len(cx.diags) == 0` 那一段），
结果放在 `CheckedMod.ct: CtOut`（`consts: Map[String, CValue]`、`blocks: Map[(Int, Int), CValue]`）里。
std 各模块的同一份结果在 `StdCtx.mods`。这份成本已经付过，只是没有拿出来给人看。

本线要回答的是：hover 和 inlay 在类型之外还能给什么，哪些今天就能给，哪些要先补前置，哪些不给。

## 2. 调研摘要

各家 LSP 的做法（出处见调研报告表一）：

- **rust-analyzer** hover 在 `const`/`static` 上显示求值后的值，整数附十六进制：
  `const foo: u32 = 123 (0x7B)`；求值失败就退回初始化式源码。
- **gopls** 对 go/types 已折叠的任何常量表达式显示值，具名常量写成 `= 原表达式 // 值`。
- **clangd** 向上找第一个能 constexpr 求值的表达式，显示 `Value = …`，整数 ≥10 或为负时附十六进制
  （`printExprValue` 的 `uge(10)` 判据）。
- **ZLS** 有 InternPool 已知值时显示 `类型 = 值`，但 README 自认复杂 comptime 解不出来。

能读出的规律：求值覆盖面取决于语言给的判据（Go 常量文法、C++ constexpr、Rust const 上下文）；
没有一家能在 hover 时对「调用了普通用户函数的表达式」安全求值。Dawn 不一样的地方有两点：

1. `const` 与 `comptime` 的值**本来就由编译器自己算**，用的是产物所用的同一个 Core IR 解释器
   （`ir/interp.dawn` 头注释：它特意读 Core 而不读 TAST，为的是和后端结构上一致）。所以 hover
   显示的值，就是 `comptime { E }` 嵌进产物的值。
2. 这一步不需要新增任何求值，只是查表。这是 A1 排第一的理由：代价最小，价值最高。

## 3. A1：hover 显示 const 与 comptime 块的值

### 3.1 文本格式

全部仍在**一个** ```` ```dawn ```` 围栏里（`server.dawn` 的 `handle_hover` 不变）。契约 helper
（`scripts/lsp-decl-pairing.py` 等，去掉围栏后整串比较）与 Playground 的 `hoverText`
（`site/play-ui/src/lsp.ts`，只认整段是一个围栏）都按单围栏读；多段 markdown 是 A3 的事。

| 情形 | hover 文本 |
|---|---|
| const 声明处、引用处、`use m.{C}` 里的名字、`m.C` 限定引用 | `const LIMIT: Int = 42  (0x2A)` |
| 小整数（<10） | `const SMALL: Int = 7` |
| 字符串 | `const GREETING: String = "hi\tthere"` |
| 长列表 | `const SQUARES: List[Int] = [0, 1, 4, 9, …, 289, 3…]  (100 elements)` |
| `comptime` 关键字（块的整个 span） | `comptime: Int = 1048576  (0x100000)` |
| 求值失败 | `const SEED: Int` 换行 `(not evaluated: builtin `hash` is not available at comptime)` |
| 本模块有类型错误 | `const MASK: Int` 换行 `(not evaluated: module has errors)` |
| 声明模块不是本模块且有错 | `(not evaluated: module util has errors)` |

值与后缀之间是两个空格，和 rust-analyzer 的 `123 (0x7B)` 同形，多一个空格是为了在等宽字体里把
「值」和「注」分开（值本身可能以 `)` 结尾）。

`comptime` 的 offer 覆盖整个块（`e_lo..e_hi`），在通用兜底（只给类型）之后发出，所以同 span
平局时它赢；块内部的节点按「最内层优先」规则照样赢，`1 << 20` 上仍然是 `Int`。

### 3.2 渲染规则（`selfhost/src/lsp/lspv.dawn`）

`CValue` 抹掉了读者需要的信息：`Char` 是 `VInt`，记录是按位置的 `VAdt`。所以渲染**按类型读值**，
类型取自 checker 给常量的类型：

- `Int`：十进制；`Char`（`TyOpaque` 的 `CHAR_OPAQUE_ID`，沿 opaque 链判断）显示 `'a'`，转义与
  lexer 的 `lex_escape` 对齐（`\n` `\t` `\r` `\\` `\'`，其余控制字符 `\u{XX}`）。
- `String`：双引号，转义同上，`${` 写成 `\${`，`"` 写成 `\"`。
- `Float`、`Bool`、`Unit`：`to_string` 与 `()`。
- `List`、元组：递归，元素按元素类型读。
- ADT：记录显示 `P { x: 1, c: 'z' }`，和类构造器写法相同；和类构造器显示 `Circle(1.5)`，无字段的
  显示 `Dot`。字段类型由 ADT 的类型参数代换到 `TyAdt` 的实参上（`subst`），所以
  `Option[Char]` 里的字段是 `'z'` 而不是 `122`。`Option` 走同一条路。
- 其他 opaque 类型按目标类型读：运行时 opaque 类型**就是**它的目标（`types.peel_opaque` 的注释）。
- 类型和值对不上（`TyError` 等）时按值自己的形状退回。
- 函数值（`VClosure`）与字典（`VDict`）作为顶层值时不显示值：`<fn>` 告诉不了读者类型以外的任何东西；
  嵌在容器里时显示 `<fn>`。今天 spec §7.2 规定常量只能装可序列化的值，这条只是兜底。

`driver/checkdump.dawn` 的 `cv_show` 刻意不复用：它是 `__check` golden 的格式，与上一 release
逐字节对拍，不能学类型；它的职责（每个常量一行精确的值）也不是这里的职责。

### 3.3 十六进制与截断阈值

- **十六进制**：整数 `n >= 10` 时附 `(0xHEX)`，大写。阈值取 clangd 的 `uge(10)`：小于 10 时两种写法是
  同一个数字，附上只是噪声。**负数不附**：补码取决于位宽，而 Dawn 的 `Int` 不对外承诺位宽；clangd
  对负数附十六进制，这里不学。`Char` 不附（码点不是它想表达的东西，A2 的字面量 hover 再议）。
- **截断宽度 `VALUE_SHOWN = 80` 码点**（`lspv.dawn`），不复用 K0 的 `DEFAULT_SHOWN = 40`：默认值与
  签名里的其他形参共享一行，40 是为了不把后面的形参挤出 hover（[std-defaults-design.md](std-defaults-design.md) §4.2）；
  常量的值独占自己那一行的剩余部分，80 是读者习惯整行读完的宽度，也大致是编辑器 hover 弹窗不折行的宽度。
  一张表（这条阈值真正针对的情形）在 80 码点里还能露出前十几个元素，够读者和生成它的代码对一下。
- **截断方式**复用 K0 的切法：K0 的 `default_display` 里那段循环提成了 `types.cut_balanced(text, width)`，
  `default_display` 改为调用它（行为逐字节不变，K0 的测试照旧通过）。切口标 `…`，再补齐被切开的
  字符串、括号与插值的闭合符，所以截断后的文本仍是括号平衡的。
- **长度后缀**：顶层是列表且被切时附 `(N elements)`（单个元素时 `element`），顶层是字符串且被切时附
  `(N code points)`。Dawn 字符串的长度是码点数（spec §11），不说「字符」也不说 UTF-16 码元。
  元组、记录被切时不附长度：它们的长度写在类型里。
- **渲染本身有界**：集合在文本超过宽度后就不再加元素，长字符串只取前 `宽度 + 1` 个码点，所以十万个
  元素的表和一百个元素的表花的时间一样。

### 3.4 值从哪里读

hover 不做任何求值，只读分析已经留下的结果：

| 常量在哪 | 读哪份 `CtOut` | 判错读哪份 `Cx` |
|---|---|---|
| 本模块 | `qc.entry.ct` | `qc.entry.cx` |
| 工程里的其他模块 | `qc.prog.modules` 中 `mod_path` 相同的那个 `CheckedMod.ct` | 同一个 `CheckedMod.cx` |
| std | `qc.std.mods` 中模块路径相同的那一项 | 同一项的 `Cx` |

常量属于哪个模块：限定引用 `m.C` 的 `XConstRef` 带着 owner；裸名的 owner 是空串，按
`def_of_const` 同样的两处找：本模块声明了就是本模块，否则查 `cx.imported_names`。

`comptime` 块的值在 `ct.blocks[(lo, hi)]`，键是 typed tree 里 `XComptime` 的 span。typed tree
的 span 在每个声明结束时已由 `check/tast_positions` 换成文件位置，`interp.eval_block` 用同一个 span
存值，所以两边是同一种单位，不会因为两个声明里的块相对位置相同而撞键。

渲染用**声明模块**的 `cx.adts`，不用入口模块的：常量的类型可能引用入口模块没导入的 ADT，
`adt_of` 对未知 id 会 panic，而声明模块一定认识自己检查过的类型。

### 3.5 失败的两种原因

UI 上只有三态：显示值、「未求值：原因」、不显示（函数值）。前两态都要告诉读者为什么，不能悄悄缺一块：

1. **模块有类型错误**：`analyze_module_step` 只在 `len(cx.diags) == 0` 时跑 comptime，`ct` 整个是空的。hover
   用同一个条件判断（检查器没有警告级诊断，所以「有诊断」就是「有错」），显示
   `(not evaluated: module has errors)`；常量在别的模块时点名那个模块。
2. **求值失败**（fuel 用尽、调用深度超限、builtin 被拒）：`interp.fold_expr` 的失败诊断带
   `origin`，而 origin 一律是折叠边界的 span（`failure_diag` 只在 origin 为空时填，填的就是
   `fold_expr` 收到的 `lo, hi`）：常量的是 `TConst` 的 span，块的是 `XComptime` 的 span。hover
   按这个 span 在 `ct.diags` 里找到那条诊断，取消息首行，去掉 `comptime: ` 前缀，显示
   `(not evaluated: <原因>)`。找不到时只显示 `(not evaluated)`。

### 3.6 增量与 Playground

- **增量记忆**（[lsp-module-memo-design.md](lsp-module-memo-design.md)）：hover 只读已有的 `ct`，
  记忆复用一个模块的步骤时 `ct` 跟着 `CheckedMod` 一起复用，不新增任何状态。
- **Playground**：走同一个 hover，网关不用改；文本仍是单围栏，`hoverText` 能照常剥掉围栏
  （`playground/test/contract.sh` 验证）。

## 4. 门禁与契约

- `./bin/dawn test selfhost`：`lsp/lspv` 五条（每种值、记录与和类、十六进制阈值、截断、函数值）；
  `lsp/server` 三条（声明与引用、comptime 关键字与块内最内层、builtin 被拒、模块有错、std 常量经
  探针 std 的选择性导入、裸引用与别名限定）。
- `scripts/selfhost-lsp-diff.sh`：会话新增 `consts.dawn`，hover 九处（声明、`comptime` 关键字、
  截断的表、字符串、被拒的常量、`use util.{LIMIT}`、跨模块引用、`u.LIMIT`、std 的 `memfs.BASE`），
  再改坏模块后 hover 一处；原有的 `LIMIT))` 一处文本随之变化。提交里写 `Emit-Change(lsp)`。
- `scripts/lsp-decl-pairing.py` 的 16 条不 hover 常量名，不受影响。

## 5. 实测

`scripts/incremental-semantics-contract/lsp-bench.py --uri untitled:bench2001`：2,000 个函数加一个
`const LIMIT: Int = comptime { 1 << 20 }` 与 `main`，hover 落在 `main` 里的 `LIMIT` 引用上（改后回
`const LIMIT: Int = 1048576  (0x100000)`，改前回 `const LIMIT: Int`），11 轮、预热 3 轮，改前（父提交
`c7a05cf2`）与改后交错两遍，每格 n = 8。本机 16 核，WSL2，GraalVM CE 21。

| 服务端 | hover 中位数（两遍） | hover p95（两遍） | sync 中位数（两遍） |
|---|---|---|---|
| 改前 | 7.65 / 6.74 ms | 15.9 / 16.6 ms | 80.2 / 84.8 ms |
| 改后 | 6.02 / 6.27 ms | 16.9 / 18.3 ms | 77.6 / 76.6 ms |

差别落在两遍之间的波动里，没有可测差异。这与预期一致：hover 多做的只是一次 `Map` 读加一次有界渲染，
comptime 本来就在每次分析里跑（sync 不变）。

## 6. 刀序

| 刀 | 内容 | 前置 | 验收 |
|---|---|---|---|
| **A1** | hover 显示 const 与 comptime 块的值（本文 §3） | 无 | lsp-diff 会话加 const 声明、引用（跨模块、std）、comptime 关键字、失败与有错各一处；`Emit-Change(lsp)` |
| **A2** | 字面量 hover：Int 进制对照（学 gopls，只在拼写与值不同时给）、Char 码点与 UTF-8、Float 是否精确与 f32 舍入、String 码点数与 UTF-8 字节数、字符串内转义 | A1 的单围栏格式稳定 | 会话加 5 处字面量；f32 那一行与 `narrow-contract` 的 oracle 抽样对拍 |
| **A3** | `##` 文档进 hover：先把 `doc.dawn` 的 `doc_of` 挪到 `front/`（`dawn doc` 输出逐字节不变），再拼正文段；同一 PR 把契约 helper 统一成「取第一个 ```` ```dawn ```` 围栏」、Playground `hoverText` 支持多段 | A2 | `dawn doc` 不变；会话加一处带 `##` 的 hover；Playground 加一条 |
| **A4** | `textDocument/inlayHint`：`let` 推断类型、lambda 形参类型、参数名（默认关）、调用处的单态效果行；网关白名单与 CM6 decoration 可拆成 A4′ | A3 | 会话加一次 inlayHint；`lsp-bench.py` 报 inlay 延迟 |
| B 组 | 纯且闭合表达式的 hover 求值、被省略默认实参的值 inlay、效果多态调用的实例化行、`?` 的错误类型、semantic tokens、references → rename | 解释器 pub(pkg) 入口、闭合检查、lowering panic 的负控、hover 用 fuel 的墙钟实测、native 栈深实测 | 各自立项时定 |

## 7. 不做的（理由）

- **内存布局 hover**：布局是后端的事，spec §11「度量是后端的，且永不成为可观察的值」，显示出来只对一个后端成立。
- **Unicode 字符名**：编译器没有名字表；加一张就多一份随 Unicode 版本重生成、还要过门禁的数据，换来的只是
  Char 字面量 hover 上的一点装饰。重开条件：有用户诉求，且表的体积实测可接受。
- **隐式 drop 提示**：Perceus RC 是 native 后端的内部实现，不是语言语义。
- **闭合括号注释**：Dawn 的函数普遍很短，`dawn fmt` 的缩进模型已经够读。
- **codeLens（run/test/引用计数）**：项目当前是自用研究定位，跑测试走 CLI。
- **参数名 inlay 默认开**：Dawn 有具名实参，作者可以直接写出名字；默认关与 gopls 一致。
- **把 UTF-16 码元数当字符串长度显示**：Dawn 的长度是码点数，UTF-16 只是 JVM 后端的表示。
- **A1 内：负数的十六进制**：见 §3.3。
- **A1 内：求值失败时退回显示初始化式源码**（rust-analyzer 的做法）：初始化式就在声明处，读者跳过去就能看到；
  hover 该说的是**为什么**没有值，那一行源码说不了。
- **A1 内：hover 时补一次求值**（例如模块有错时只对这个常量跑解释器）：那是 B 组「纯且闭合表达式求值」的入口，
  要先补 fuel 预算与墙钟实测；A1 的约束是只读已付的成本。

## 8. 状态

| 刀 | 状态 | 提交 |
|---|---|---|
| A1 | 已落地 | `0c31ed4d`（合入 main 时若经 rebase，以 main 上的哈希为准） |
| A2–A4 | 未开工 | |
| B 组 | 未立项 | |
