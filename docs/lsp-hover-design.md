# LSP 悬停与内联提示：设计（A1–A4、B1）

> 状态：current。本线的总纲：除类型之外，hover 与 inlay 还能告诉读者什么、按什么刀序做。
> A1（hover 显示 const 与 comptime 块的值）已落地；A2 已落地（§4）；A3 已落地（§A3）；A4（inlay hints）已落地（§A4）；
> A5（文档里的 `` [`name`] `` 链接可点，文档注释 D4）已落地（§A5）；D7（补全项文档、signatureHelp 文档、
> `use` 行的模块文档，文档注释 D7）见 §D7。B1（省略的默认实参作 inlay hint）已落地（§B1）。
> C5（纯且闭合表达式的 hover 求值）已落地：解释器入口 C5-1 与 LSP 接线 C5-2（§C5）。
> B 组立项时在这里改写被事实推翻的前提。调研依据是 2026-10-02 的只读调研报告（仓外协作档，结论摘在 §2）。

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

## 4. A2：字面量 hover

### 4.1 文本格式

仍是**一个** ```` ```dawn ```` 围栏，与 A1 同形：第一行是字面量的类型（通用兜底本来给的那一行），
第二行是值行。hover 文本里的英文是正本，下表照录 lsp-diff 会话的真实输出。

| 字面量 | 值行 |
|---|---|
| `255`、`1_000_000` | `255  (0xFF)`、`1000000  (0xF4240)`：十进制写法显示去掉下划线的值，十六进制沿 A1 的 `n >= 10` 阈值与大写 |
| `7`、`0` | 无值行，只有 `Int`：0..9 的十进制一位数，写法、十进制值与十六进制是同一个字符，值行只是回声（理由见 4.4） |
| `0_7`、`0x0` | `7`、`0x0 = 0`：写法与值不同，仍给值行 |
| `0xFF`、`0b1010` | `0xFF = 255`、`0b1010 = 10`：非十进制写法原样回显，再给十进制 |
| `-0x8000000000000000` | `-0x8000000000000000 = -9223372036854775808`：唯一带负号的字面量（spec §1.5），负号随写法回显 |
| `'é'` | `'é'  U+00E9  UTF-8: C3 A9` |
| `'\n'`、`'\u{1F600}'` | `'\n'  U+000A  UTF-8: 0A`、`'😀'  U+1F600  UTF-8: F0 9F 98 80` |
| `1.5` | `1.5  (exact)` |
| `1.1` | `1.1  (not exactly representable)` |
| `"héllo\n"` | `"héllo\n"  (6 code points, 7 UTF-8 bytes)` |
| `"a ${x}"` | 无值行，只有 `String`：带插值的字符串是表达式，不是字面量 |
| `true`、`()` | 无值行：没有类型之外的信息 |

规则：

- **Int**：lexer 只认 `0x` 与 `0b` 两种前缀（`lexer.dawn` 的 `lex_number`，spec §1.5 的表），没有 `0o`，
  所以只回显这两种。十六进制写法不再附 `(0x…)`：那就是读者刚写下的东西。负号是一元运算，hover
  落在 `-0xFF` 的 `0xFF` 上显示 `0xFF = 255`；只有 `-2^63` 由 parser 并进字面量的 span，它的回显带负号。
- **Char**：字符本身按 A1 的 `char_lit` 渲染（转义与 `lex_escape` 对齐，控制字符写 `\u{X}`），
  码点 `U+` 后至少四位大写十六进制（Unicode 的惯例写法），UTF-8 字节两位一组。转义写法与直接写法
  给同一行：码点不因写法而变。
- **Float**：先给最短往返拼写，即 `to_string(Float)`，也就是 `std/fmt.dtoa`（spec §4.3 的数值渲染；
  两个后端编译同一份定义），程序打印出来就是这个样子。再说字面量是否**恰好**是这个 double（见 4.3）。
- **String**：字面量按 A1 的 `str_lit` 渲染（转义、`${` 写成 `\${`），超过 `VALUE_SHOWN = 80` 码点时用
  `cut_balanced` 截断。后缀**总是**给两种长度：码点数（`str.len` 的口径，spec §11）与 UTF-8 字节数；
  单数写 `1 code point`、`1 UTF-8 byte`。A1 里长度只在截断时出现，因为那里它是截断的标记；这里长度
  本身就是 hover 的目的。三引号字符串与反引号 raw string 是同一种 `EStr`，按同一规则（三引号的值是剥掉
  缩进以后的那段）。
- **命中**：最内层优先，与 A1 一致。字面量的 offer 与通用兜底同 span，后发出，所以同 span 平局时它赢。
  `const X: Int = 0xFF` 里，hover 在 `X` 上是 A1 的 `const X: Int = 255  (0xFF)`，在 `0xFF` 上是
  `Int` 换行 `0xFF = 255`。

### 4.2 原文与值从哪里来

parse 树的字面量节点只留**值**：`EInt(v)`、`EChar(v)`（码点）、`EFloat(v)`、`EStr(parts)`（转义已解开的
`SPText`），span 是文档的码点下标。写法（`0xFF` 还是 `255`、`1.1` 还是 `1.10`）不在树里。

不改 AST：改了会牵动 `astdump` 与 golden，代价不值。写法从文档文本按 span 切出来：`QCx` 新增
`cps: List[Char]`，即 `server.doc_qcx` 拿到的 `Doc.view.cps`，与 hover 的 offset 同一个坐标系。
两者都用：写法决定「这是十六进制写法」与「这个十进制数是否精确」，值决定显示什么。span 落在文本
外（分析的是另一个版本）时写法为空；Float 的写法若读回来不是这个值，就不下精确与否的结论。两种情况都
只丢回显，值行仍然正确。

### 4.3 Float 的「是否精确」

Dawn 没有现成的精确十进制展开：`std/fmt.dtoa` 只出最短往返拼写，两个后端和 comptime 解释器都调这一份
（`ir/lower.dawn` 的 `show_scalar`）；`runtime/c` 里没有 `printf` 系的浮点格式（没有 `%.17g`），`jfold` 已不在
`selfhost/src`。任务约定不写大数精确展开，所以这里判定的是一个更窄的问题：**写下的十进制数是不是
某个 double**。

写下的值是 D × 10^k = D × 5^k × 2^k（D 是去掉小数点的整数）。它恰好是 double，当且仅当它能写成
odd × 2^e，odd 为奇数且 < 2^53，e ≥ −1074（最小次正规数的步长），且 odd × 2^e < 2^1024。判定就是这句话
直接算：

1. 去掉 D 的前导零与尾随零（尾随零并进 k）；全是零就是 `0.0`，精确。
2. k < 0 时，把 D 除以 5 共 −k 次，有余数就不是二进分数，不精确；k ≥ 0 时，k > 22 直接不精确（5^23 > 2^53）。
3. 把 D 的因子 2 除净并进 e；剩下的奇数部分（k > 0 时再乘 5^k）必须 < 2^53，再查 e 的范围。

运算只是对一串十进制数字做「除以 5」「除以 2」的长除法。一个精确的 double 最多有 767 位有效数字
（最长的是次正规数的展开），所以超过 800 位的写法直接判不精确，不做任何除法；成本因此有上界。
`0.1000000000000000055511151231257827021181583404541015625` 是 0.1 的 double 的完整展开，判为 `exact`；
少一位或改一位就不是。

### 4.4 不做的（A2 内，理由）

- **字符名称**（gopls 的 `U+00E9 LATIN SMALL LETTER E WITH ACUTE`）：编译器没有名字表，见 §8。只给码点与字节。
- **f32 舍入行**（调研 C2 提的 `as f32: …`）：Dawn 没有 f32 字面量类型，这一行回答的问题程序里问不出来。
  `std/narrow.round_f32` 给得出舍入后的值，但要把它显示成读者能核对的十进制，要么写精确展开（本刀明令不写），
  要么用 double 的最短拼写（`1.100000023841858`，看起来像一个随意的近似，反而误导）；§7 刀序里「与
  `narrow-contract` 的 oracle 抽样对拍」的验收也就无从谈起。重开条件：有 f32 类型，或者有人需要在
  hover 里核对 `std/narrow` 的结果。
- **大数精确十进制展开**（clangd、调研 C2 的 `0.1000000000000000055511…`）：见 4.3，判定是否精确不需要它。
- **只在写法与值不同时才给**（gopls 的判据）：只采纳到一位数为止。十进制写法仍给值行，好让 `255` 与 `0xFF`
  的 hover 形状一致（`255` 的值行带十六进制，有信息）；但 0..9 的十进制一位数（无 `0x`/`0b` 前缀、无下划线、
  无负号）不给值行，hover 退回 A2 之前的单行类型。理由：这时写法、十进制值、十六进制三者是同一个字符，值行纯属
  回声。本刀初版曾给 `7` 也出一行 `7`，CI 的 `pipe-contract` 随即红在 `hover_qctor_arg`：它 hover
  `One(7)+4` 里实参位置的 `7`，契约要的正是裸类型 `Int`（`scripts/pipe-contract/run.sh`）。契约不改，
  改规则：裸类型是实参位置上最有用的回答，回声行只是噪声。
- **光标落在字符串里的某个转义上时单独解释它**（gopls 的做法）：要把 hover offset 映回 `SPText` 里的位置，
  而 parse 树已经把转义解开了；整串的值行已经显示了解开后的结果。
- **字面量 pattern**（`match n { 0xFF -> … }`）：pattern 走 `walk_p`，不经过 `walk_e`；需要时另开一刀。
- **二进制写法再附十六进制**：回显加十进制已经够核对；多给一种进制是 ZLS 的进制对照表，噪声大于信息。

## A3. `##` 文档进 hover

### A3.1 回包格式

照 rust-analyzer 的形状（调研 C3 的样例）：代码围栏、一条分隔线、文档正文。

````
```dawn
fn area(s: Shape) -> Float
```

---

Area of a shape, in square units.
````

- 围栏里的内容与 A1/A2 完全相同（`Target.hover`），文档段拼在围栏**之后**：围栏 + `\n\n---\n\n` + 正文。
- **没有 `##` 时回包与 A3 之前逐字节相同**（单围栏）。只空白的文档（一行孤零零的 `##`）按没有处理：
  分隔线下面什么都没有，不如不画。
- 正文是注释原样的 markdown（去掉 `## ` 前缀之后的那些行，与 `dawn doc` 的 `doc` 字段同一串），不改写。
- 拼装在 `selfhost/src/lsp/lspdoc.dawn` 的 `hover_markdown`；`server.dawn` 的 `handle_hover` 调它。

### A3.2 哪些目标带文档

规则：**有声明点、且 `dawn doc` 的附着规则能读到的声明**带文档；读法就是 `dawn doc` 那一条
（`front/docs.doc_of`：声明首行正上方连续的 `##` 行，空行断开，普通 `#` 不算）。

| 目标 | 带文档 | 读哪一行之上 |
|---|---|---|
| fn（声明处、调用处、选择性导入、`m.f`、管道） | 是 | `FnDecl.lo` |
| impl 方法的声明处 | 是 | 该方法的 `FnDecl.lo` |
| trait 方法（声明处、经 trait 解析的调用） | 是 | `TraitMethod.lo` |
| type（声明处、选择性导入） | 是 | `TypeDeclR.lo` |
| 构造器（声明处、构造、pattern、选择性导入、限定构造） | 是 | 构造器自己那行（`CtorDecl.lo`），不是 type 那行 |
| const（声明处、裸引用、`use m.{C}`、`m.C`） | 是 | `DConst` 的 `lo` |
| trait、effect、effect 操作的声明处 | 是 | 各自的 `lo` |
| 字段（声明处、记录的字段访问 `p.x`） | 是（文档注释 D2 起） | 字段自己那行（`FieldDecl.lo`），与构造器同一条规则。构造器或字段与所属声明同行时没有自己的文档（`dawn doc` 给 `null`，spec §1.2），hover 照旧读那一行之上，显示的是所属声明的文档，作为显示层回退 |
| 局部变量、形参、lambda 形参、match 绑定、局部 fn | 否 | 它们不是对外的声明；`let` 上方的 `##` 只是注释 |
| 字面量（A2）、comptime 块、`use` 行、impl 头、builtin | 否 | 没有声明点或没有 `##` 源码 |

`front/docs` 是 A3 的前置小刀：`doc_src_of`/`doc_of`/`module_doc_of` 原来在入口层 `doc.dawn`，`lsp/` 不能
反向依赖入口层；挪到 `front/`（它只读 lexer 的注释 token 与 parse 树的 span）后两边共用一份规则，
`dawn doc --stdlib`、`--builtins` 与三个工程的输出前后逐字节相同。

### A3.3 文档从哪里读

查询层（`lspq`）不做 I/O，只在 `Target.doc` 里记下**哪段文本、哪个 offset**（`DocSite`）；
文本由 server 取：

| 声明在哪 | `DocHome` | 文本 |
|---|---|---|
| 本文档 | `DocHere` | 当前缓冲区 `Doc.text`（与 `QCx.cps` 同一版本） |
| 工程里的其他模块 | `DocFile(path)` | 与 go to definition 同一个查找（`def_source`）：同一 source root 里打开着的缓冲区，否则磁盘 |
| std（目录或内嵌） | `DocStd(mod_path)` | `StdCtx.srcs` 里那个模块的文本 |

std 走 `StdCtx.srcs` 而不是调研建议的 `std_file_of` 读文件：`srcs` 就是 std 被检查时的文本，span 与它
一一对应；内嵌 std 没有文件，`srcs` 里照样有文本。所以「内嵌 std 的声明没有定义可跳，但仍有文档」
在结构上成立：`Site` 把跳转目标（`def`/`def_path`）与文档位置（`doc`）分开记，前者为空不影响后者。

`location_of` 原有的「找哪段文本」逻辑提成了 `def_source`，location 与文档共用它，所以同一个声明
的跳转与文档不会读到两份不同的文本。

### A3.4 成本

找文档要从文件开头词法整段文本：`##` 出现在字符串里就不是注释，只有从头开始的 lexer 知道哪些
字符串还开着。三层处理：

1. **先做字符串检查**（`lspdoc.may_have_doc`）：声明首行的上一行里根本没有 `##` 时直接答「无文档」，
   不词法。注释不跨行，所以这一步是精确的，不是启发式。大多数声明没有文档，走的是这条路。
2. **按文本记忆**（`server.doc_src_memo`）：`LspState.doc_memo` 以文件（`doc <uri>`、`file <path>`、
   `std <mod_path>`）为键，存词法出的注释表和**整段原文**；再次查询时原文逐字相同才复用（比较整段
   文本而不是摘要：不会有摘要碰撞，JVM 上比较 30 万码点的字符串是微秒级）。最多 32 个文件，满了就清空重来。
   std 的文本在会话内不变，所以 std 的文档只在第一次 hover 时词法一次。
3. **注释归行改成一遍扫描**（`front/docs.doc_src_of`）：原来每条注释调一次 `line_of`，从头数行首，
   代价是「注释数 × 行数」；改成随注释顺序推进同一个指针，结果相同（有单测对拍 `line_of`），`dawn doc`
   也跟着受益。

实测（`scripts/incremental-semantics-contract/lsp-bench.py`，11 轮、预热 3 轮、每格 n = 8，改前 = 父提交
`30419580`，与改后交错两遍；本机 16 核，WSL2，GraalVM CE 21）：

| 场景 | 改前 hover 中位数 | 改后 hover 中位数 |
|---|---|---|
| `plain2000`：2,000 个无文档函数，hover 本文件的 `f1999` | 7.31 / 13.16 ms | 9.26 / 9.11 ms |
| `gpu`：hover `gpu.round_to`（std 最大的模块，2,139 行，有文档） | 0.55 / 0.83 ms | 1.30 / 0.88 ms |
| `big2000`：2,000 个函数**每个都有两行 `##`**，每轮先改文本再 hover `f1999` | 7.29 / 9.12 ms | 59.20 / 48.00 ms |

- 前两行没有可测差异：无文档走第 1 步；std 走第 2 步的命中。
- 第三行是最坏情形：8,000 行、4,000 条文档注释，且每轮都改文本，于是每次 hover 都是一次未命中，要词法
  整段文本，多出约 40–50 ms。同一版本上的后续 hover 命中记忆，回到第二行的量级。去掉记忆与一遍扫描之前
  （只有逐次词法）这一行是 88.75 / 87.81 ms，`gpu` 是 12.82 / 12.03 ms。
- 进一步的办法（只词法到声明所在行之前的前缀；或让分析阶段的词法顺手留下注释表）都没做：前者对文件末尾的
  声明没有帮助，后者把成本挪进每次编辑的 sync，而 sync 是比 hover 更热的路径。

### A3.5 截断

文档按**整行**截断：最多 `DOC_SHOWN_LINES = 50` 行、`DOC_SHOWN = 4000` 码点（`lspdoc.dawn`）。std 与
`packages/web` 现有 398 条文档里最长的是 47 行（`std/gpu.with_gpu_real`）、2,883 码点，所以今天写下的
文档都完整显示；上界只防「没打算在弹窗里读」的超长注释在每次 hover 时整段传输（Playground 经网关转发，
回包大小也是它的成本）。

被截断时：保留的行里若有奇数个代码围栏行（以 ```` ``` ```` 开头），补一行 ```` ``` ```` 把它关上，否则后面的
说明会被吞进代码块；末尾加一行 `(truncated; the rest is at the declaration)`，go to definition 就能到那里。
单独一行就超过 4000 码点时在行内切开并标 `…`。与 A1 的 `VALUE_SHOWN` 不同，这里不用 `cut_balanced`：
文档是 markdown 散文，不是括号平衡的值，按行切才不会把一个列表项或一行代码切成两半。

### A3.6 契约与 Playground

- **契约 helper**：凡是从 hover 回包里取文本比较的脚本，统一经 `scripts/lsp_hover.py` 的
  `hover_code(result)` 取**第一个 ```` ```dawn ```` 围栏**里的内容（没有围栏的纯文本回包原样返回），
  不再「去掉所有 ``` 后整串比较」。这样带文档的 hover 不会让只关心类型的契约变红，而文档段由
  server 单测与 lsp-diff 会话守。
- **Playground**：`site/play-ui/src/lsp.ts` 的 `hoverText` 认「围栏 + `---` + 正文」：围栏里的代码照旧，
  正文按纯文本显示在代码下方（去掉 `---` 与围栏标记），不把 ```` ``` ```` 与 `---` 原样漏出。

### A3.7 不做的（A3 内，理由）

- **沿别名链收集文档**（ZLS 的做法：`const a = b.c;` 的 hover 带上 `b.c` 的文档）：Dawn 最常见的「别名」是
  选择性导入的 `use m.{f as g}`，hover 解析到原声明，文档本来就跟着来；`type A = B` 这类类型别名是作者在
  那一点写下的新声明，它没有 `##` 时说明作者没打算替它另写说明，把 `B` 的文档挂上去会让读者以为那是 `A`
  的承诺；链上多条文档还要定一条先后与合并规则，那是一份新的语义。重开条件：出现「别名的文档总是空、
  读者总得跳一次」的实际抱怨。
- **模块文档进 `use` 行 hover**（`module_doc_of`）：A3 时留作独立的一小刀，文档注释 D7 做了，见 §D7.3。
- **字段文档**：A3 时不做（`dawn doc` 当时不给字段文档，hover 不另立规则）；文档注释 D2 让 `dawn doc` 发布字段文档后，
  hover 随之补上，见 A3.2。
- **把文档渲染成 HTML、改写 markdown**：编辑器自己渲染 markdown；Playground 按纯文本显示正文。
- **builtin 的文档**：builtin 没有 `##` 源码；`selfhost/builtins.dawn` 是给人读的镜像，不是 hover 的数据源。

## A4. inlay hints（`textDocument/inlayHint`）

### A4.1 四种提示与默认值

| 种类 | 样子 | 默认 | 数据 | LSP 字段 |
|---|---|---|---|---|
| `let` 推断类型 | `let xs«: List[Int]» = range(0, n)` | 开 | `TSLet` 的符号（`Sym.ty`） | `label: ": List[Int]"`，`kind: 1`（Type），无 padding |
| lambda 形参类型 | `xs.map(x«: Int» => x + 1)` | 开 | `XLambda` 的形参符号（hover 的 `offer_lambda_params` 用的同一组） | 同上 |
| 调用处的效果行 | `read_file(p)« !Fs»` | 开 | 被调者 `Sig.eff`；局部函数值取它类型里的行 | `label: "!Fs"`，`kind: 1`，`paddingLeft: true` |
| 参数名 | `column(«kids: »k, «gap: »12)` | **关** | 被调者 `Sig.param_names` | `label: "kids:"`，`kind: 2`（Parameter），`paddingRight: true` |

`«…»` 是编辑器画出来的部分，不在文本里。类型标签自带冒号、不要 padding，画出来正好是读者会写的
`let xs: List[Int]`；效果标签要左 padding，画出来是 `read_file(p) !Fs`。

类型串与效果行都走 hover 的渲染（`types.ty_show`、`types.eff_suffix`），同一个类型在 hover 与 inlay 里写法相同。
效果行有一个以上的标签时也照 hover 写成 `!(Ask|Fs)`（名字排序、竖线分隔），即使声明处写的是 `!Fs !Ask`：
提示回答的是「这次调用带着什么行」，与 hover 的签名同一个答案、同一种写法，不另立一套拼法。

**规则：**

- **`let`**：只给没写标注的 `let`/`var`；`let _ = …` 没有绑定，不给。解构 `let (a, b) = …`（解构不许标注，
  parser 直接拒）的每个绑定各给一个，位置是各自名字的末尾。名字的末尾从文档文本读：`SLet` 只记整条语句的
  span，`TSLet` 的符号 span 也是整条语句（`checker.check_let` 用语句的 `lo..hi` 声明它），名字不在任何树里。
  文法是 `let`/`var`、空白、名字，中间不可能有注释或换行，所以「关键字后跳过空白读一个标识符」是确定的；
  读出来的名字和 `SLet` 的名字不一致（分析的是另一个版本的文本）时不给，不猜。
- **lambda 形参**：只给没写标注的形参，位置是形参名末尾。覆盖 `x => …`、`(a, b) => …`、尾随块
  `{ x => … }`、`with x <- f(…)`（parser 把它变成一个形参的 lambda，文法上不能标注）与局部 `fn`
  的形参；handler 臂（`op(a) => …`）不给：那是效果操作的形参，类型就写在 `effect` 声明里，离读者一跳。
- **长度**：类型串超过 `TYPE_HINT_SHOWN = 25` 个码点就**不显示**（不截断）。依据：rust-analyzer
  `inlayHints.maxLength` 默认 25，clangd `InlayHints.TypeNameLimit` 默认 24。两家处理不同：rust-analyzer
  截断成 `…`，clangd 整个不给。这里学 clangd：截过的类型不是一个类型，读者不能照抄成标注，而长类型正是
  最该去 hover 看全的那种；25 取 rust-analyzer 的数，两者只差一个码点，取较宽的那个。
- **含错误的类型不显示**：类型里有 `TyError`（渲染成 `?`）说明这一带检查失败，诊断已经在报，提示只会把
  `?` 抄一遍。
- **效果行**：只给行里有**具名效果**（effect 标签，`Fs`、`Ask` 这类）的调用。纯调用不给；只有 `!io` 的调用
  也不给：`io` 是基轴不是具名效果，`println` 一类到处都是，给了就是噪声，有标签时 `io` 随整行一起显示
  （`!(Fs|io)`）。**效果多态的调用不给**：被调者的行里有效果变量（`!e`）或关联效果投影（`C.E`），读者要的是
  实例化以后的行，而 typed tree 的 `XCallFn` 只带 evidence 列表、不带实例化的行（`check/tast.dawn` 的
  `XCallFn` 定义），只给声明的行会把 `!e` 原样摆在调用处，什么也没回答。这一半在 B 组。
  覆盖的调用：具名函数（本模块、别的模块、std）、builtin、trait 方法、效果操作（`ask()`）、经 UFCS 或模块
  限定的同一批，以及局部函数值（`XCallDyn`，取它类型 `fn(…) -> T !Fs` 里的行）。位置是调用的末尾；
  调用带尾随块时放在实参括号 `)` 之后、块之前（不然 `with x <- f(…)` 的提示会落在整个块的末尾）。
- **参数名**（默认关）：只给按位置写的实参；具名实参（`gap: 12`）已经写出了名字，不给；尾随块不给；
  `x |> f(a)` 里被管道插进去的 `x` 不在括号里，不给，也不计数。另有两条隐藏规则（TypeScript
  `includeInlayParameterNameHintsWhenArgumentMatchesName` 默认关、ZLS `inlay_hints_exclude_single_argument`
  的同款）：括号里只有一个实参时整次调用都不给；实参就是与形参同名的变量时（`pad(s, width, b)` 里的
  `width`）只这一个不给。UFCS 调用 `xs.f(a)` 的接收者占第 0 个形参，括号里的实参从第 1 个起算；判据是 typed
  tree 第一个实参的 span 是否就是接收者（不看实参个数：省略了默认实参时两边个数本来就对不上）。

### A4.2 range 与排序

只回位置落在请求 range 内（两端都含）的提示，按位置排序。range 先换成码点 offset（与 hover 同一个
`lsp_offset`），再在**声明**一级剪枝：span 与 range 不相交的顶层声明整个不走，所以编辑器只请求可见区域时，
代价跟可见区域里的声明成正比，不跟文件大小成正比（实测见 A4.5）。

### A4.3 配置通路：`initializationOptions`

```json
"initializationOptions": { "inlayHints": {
  "letTypes": true, "lambdaParamTypes": true, "callEffects": true, "parameterNames": false,
  "defaultArguments": true
} }
```

`defaultArguments` 是 B1 加的（§B1.4）。五个键都可省，省了取上表的默认值；类型不对的值也按省略处理。只在 `initialize` 读一次。

不用 `workspace/configuration`：那是服务端向客户端发的请求，server 今天除了一次
`client/registerCapability` 之外从不向客户端发请求，也不处理客户端的回包（`is_response` 一律丢掉）；为一组
四个布尔值加一条请求-回包通路，代价与收益不成比例。重开条件：有人需要不重启编辑器就切换开关。
VS Code 扩展不改：四个默认值就是扩展想要的，`vscode-languageclient` 原生支持 inlay。

### A4.4 分层

- `lsp/lspinlay.dawn`：每种提示**给不给、写成什么**（长度、错误类型、效果行判据、参数名的隐藏规则），纯函数，
  单测不需要程序。
- `lsp/lspq.dawn` 的 `inlay_hints(qc, lo, hi, opts)`：找提示的位置。复用 hover 的那一趟平行遍历（parse 树与
  typed tree 按位置配对，处理好了 handler、管道、具名实参重排这些形状），`Q` 多一个可选的收集器；hover
  请求时收集器为空，遍历的行为与开销都不变。查询层不做 I/O。
- `lsp/server.dawn` 的 `handle_inlay_hint`：range 换算、JSON、码点到 UTF-16 的位置换算。

### A4.5 实测

`scripts/incremental-semantics-contract/lsp-bench.py`，`--uri untitled:*` 单缓冲区，11 轮、预热 3 轮、每格 n = 8，跑两遍；
本机 16 核，WSL2，GraalVM CE 21。`inlay` 请求全文，`inlay_view` 请求从目标行起 60 行（编辑器一屏）；hover 是同一轮里
同一快照上的请求，作对照。

| 缓冲区 | 提示数（全文 / 一屏） | hover 中位数 | inlay 全文中位数 | inlay 一屏中位数 |
|---|---|---|---|---|
| `plain2000`：2,000 个一行函数（4,001 行），没有 `let` | 0 / 0 | 8.59 / 11.99 ms | 6.52 / 6.68 ms | 1.13 / 1.48 ms |
| `lets2000`：2,000 个函数，每个一条 `let`、一个 lambda、一次 `!Fs` 调用（12,002 行） | 8,000 / 40 | 48.77 / 46.70 ms | 79.82 / 78.23 ms | 2.03 / 1.82 ms |
| std 最大的能单独分析干净的模块 `std/narrow.dawn`（1,462 行） | 137 / 3 | 12.70 / 13.55 ms | 4.45 / 4.61 ms | 0.91 / 0.93 ms |

（std 里更大的 `gpu.dawn`、`io.dawn` 作为用户缓冲区打开会报几十条「std 内部 builtin 不可见」的诊断，`lsp-bench.py`
要求基线无诊断，所以取 `narrow`。）

- **一屏的请求是 1–2 ms**，与文件大小基本无关：顶层声明级剪枝之后，只走可见范围里的那几个函数。Playground 与
  VS Code 都只请求可见范围，这是实际路径。
- **全文请求在提示多时慢于 hover**：`lets2000` 全文 80 ms 对 hover 47 ms。差额是 8,000 条提示本身：每条一个
  `show_ty`、一次码点到 UTF-16 的位置换算、一个 JSON 对象，回包约 0.5 MB。没有提示的 `plain2000` 全文与
  hover 同一量级。全文请求只在验收时用（调研 §六 A4 行的「全文 range」），编辑器不发。
- **hover 不受影响**：用父提交的 `lsp-bench.py`（只量 hover/definition/completion）对父提交 `597dfb3a` 与本刀交错跑两遍，
  `plain2000` hover 8.04 / 7.61 ms 对 7.61 / 7.48 ms，`lets2000` 43.61 / 50.87 ms 对 45.91 / 47.98 ms，落在两遍之间的
  波动里。`Q` 多出的收集器在 hover 时是 `None`，每个提示点只多一次 `match`。
- **可选的收敛办法**（没做）：全文请求的大头之一是遍历沿用 hover 的 offer，每个节点都渲染一次 hover 文本，收集提示时
  这些文本立刻被丢掉。把 offer 的文本改成惰性的（或收集模式下跳过 offer）能省掉这一份，但要动 hover 遍历的每个
  offer 点；一屏的请求已经在 2 ms 以内，不值得为全文请求付这份改动。

### A4.6 不做的（A4 内，理由）

- **被省略的默认实参**：A4 时以为要显示求得的值才比 signatureHelp 多给信息，B1 推翻了这个前提，
  以源码文本落地，见 §B1。
- **`?` 传播的错误类型**（`parse(s)?« ⇡ ParseError»`）：价值中等，要先从外层返回类型里取错误分量；放 B 组。
- **闭合括号注释**（`}« // fn handle»`）：Dawn 的函数普遍很短，`dawn fmt` 的缩进模型已经够读（§8）。
- **效果多态调用的实例化行**：见 A4.1，`XCallFn` 不带实例化的行；放 B 组。
- **`for` 的循环变量类型、`match` 臂的绑定类型**：本刀只做任务定下的 `let` 与 lambda；`for x in xs` 的 `x`
  类型多半一眼可知（元素类型），`match` 臂绑定的类型由构造器决定，hover 一下就有。需要时同一套规则加一处即可。
- **`inlayHint/resolve`、tooltip、可点击的类型标签**：提示本身就是全部信息；hover 已经给 tooltip 能给的东西。
- **`workspace/inlayHint/refresh`**：服务端按序回答、每次请求现算，没有后台缓存要通知客户端刷新
  （sourcekit-lsp 那种模式是另一种架构）。

## A5. 文档链接（文档注释 D4）

文档正文里的 `` [`name`] `` 是对声明的引用（spec §1.2「链接」）。记号、解析规则与 `dawn doc` 的失败在 spec 与
文档注释裁决里定；这里只记 hover 这一侧。

### A5.1 解析与落点

- **解析器只有一个**：`selfhost/src/driver/doclinks.dawn` 的 `resolve_link`，`dawn doc` 与 hover 共用。它要的是
  文档所在模块的导入表（`CheckedMod.cx` 的 `module_aliases`、`module_exports`、`imported_names`、
  `import_renames`）与其他模块的 parse 树。`front/` 两样都看不到；`check/` 不该做（注释不影响语义，`dawn run`
  不为它付费）；`driver/` 是同时拿得到二者、且 `doc.dawn` 与 `lsp/` 都能导入的最低一层。哪些文本是链接
  （扫描）只读注释文本，留在 `front/docs`（`doc_links`、`rewrite_links`），两边同一份。
- **作用域按文档所在的模块**，不是按被 hover 的文档：hover 一个 std 函数时，它文档里的链接在那个 std 模块里
  解析（`DocHome` 已经记着文本来自哪个模块：`DocHere` 是当前文档，`DocFile(path)` 是工程里的那个模块，
  `DocStd(mp)` 是 `StdCtx.mods` 里那个模块的 `Cx`）。

### A5.2 渲染成什么

解析到的链接改写成 Markdown 链接，目标是声明所在文件的 `file://` URI，片段 `#L<行>,<列>`（1 起）指到声明的名字：

````
Twice [`plain`](file:///work/app.dawn#L7,4), unlike [`linkprobe.probe`](file:///work/std/linkprobe.dawn#L2,8)
````

- 文件与行的查找就是 go to definition 那一条（`def_source`：本文档、同一 source root 里打开着的缓冲区、
  否则磁盘），所以链接跳到的地方与在名字上按 F12 一样。整个模块（`[`list`]`）指到文件第 1 行。
- 片段格式：VS Code 打开 hover 里的 `file:` 链接时认 `#L<line>,<col>`；不认片段的客户端照样打开文件。
- **为什么不学 gopls 链到文档站**：gopls 把 `[Name]` 链到 pkg.go.dev（或它自带的文档服务），前提是每个包都
  有一个文档页。Dawn 只有 std 上站（`stdlib.html`），工程与 packages 没有；而编辑器里的读者要的是声明本身，
  跳到声明正是 hover 旁边 go to definition 的语义。站点锚点的规则只在 `site/src/gen/stdlib.dawn` 一处，
  编译器里再抄一份就是会悄悄漂移的第二份。
- **不改写的情形**：解析不到的链接、目标没有文件的链接（prelude 名字；std 用内嵌副本时没有目录）按原样留下。
  CommonMark 把它渲染成带方括号的代码，不认识 Markdown 的客户端看到的也是原文。hover 不报错：报错是
  `dawn doc` 的事，编辑器里一段坏链接不应该让 hover 失败。
- 不含 `` [` `` 的文档不做任何解析，回包与 D4 之前逐字节相同；含链接的才建模块表、逐个解析。改写在截断
  （A3.5）之前，链接只会让行变长，截断仍按整行。

### A5.3 Playground

Playground 的 LSP 跑在服务器上，`file://` 指的是服务器上的路径，浏览器打不开，也不该给人看。
`site/play-ui/src/lsp.ts` 的 `docText`（tooltip 本来就把文档当纯文本显示）把这种链接还原成它的代码 span，
丢掉目标，selftest 加一条。网关不改：它不解析 hover 正文。

### A5.4 不做的（A5 内，理由）

- **补全项、signatureHelp 里的链接**：D7 给这两处加文档时走的就是同一个 `linked_doc`（§D7.1）。
- **`[name]`（不带反引号）**：调研 §3.2 的候选之一。仓里 `##` 正文写方括号的地方多是区间与类型参数
  （`[0, len)`、`List[T]`），认它会把这些读成坏链接；只认带反引号的一种，链接与非链接一眼可分。
- **链到 packages 的站点页**：packages 还没有 API 页（裁决 P2/P3 之后再说）。

## D7. 补全项、signatureHelp 与 `use` 行的文档（文档注释 D7）

裁决是文档注释那条线的 D7 行，调研 §3.9 的表：补全项带文档、signatureHelp 带函数整体文档、`use` 行
hover 显示模块文档，三件都用 hover 已有的那一份文档（A3 的读法、A5 的链接、A3.5 的截断）。

### D7.1 一份文档，三个出口

`server.dawn` 的 `site_doc(DocSite)` 是唯一的取文档入口：按 `DocHome` 找文本（A3.3 那张表）、经
`doc_src_memo` 取注释表、读出文档、改写链接。hover（`target_doc`）、补全的 resolve、signatureHelp 都调它，
所以同一个声明在三处显示的是同一段文字。`DocSite` 从 `{ home, lo }` 改成 `{ home, at }`，
`at` 是 `DeclAt(lo)`（声明的文档，原来的语义）或 `ModuleDoc`（模块文档，`front/docs.module_doc_of`）。

| 出口 | 回包里的位置 | 内容 |
|---|---|---|
| hover | `contents.value` | 围栏 + `---` + 文档（A3.1，不变） |
| `completionItem/resolve` | `documentation`（`MarkupContent`，markdown） | 只有文档，没有围栏：签名已在 `detail` |
| signatureHelp | `signatures[0].documentation`（markdown） | 只有文档：签名就是 `label` |

三处都过 `cut_doc`（A3.5 的截断）。没有文档时不加字段：resolve 原样回送收到的项，signatureHelp 的
`SignatureInformation` 只有 `label` 与 `parameters`，与 D7 之前逐字节相同。

### D7.2 补全：resolve 时才取文档

- 服务端声明 `completionProvider.resolveProvider: true`。补全列表本身**不带文档**：一张列表有几百个名字，
  来自几十个模块，列表时就取文档等于每次补全都要词法这些模块（调研 §3.9）；读者只会停在一两项上，
  客户端对那一项发 `completionItem/resolve`。
- **`data` 里放什么**：文档的 uri，和 `use` 行补出来的项所属的模块路径（`module`）。标签与 kind 已在项上，
  三者足以找到声明，不放 offset、签名或别的大对象。只有可能有声明文档的 kind（Function、Class、Interface、
  Module、EnumMember、Constant、TypeParameter 即 effect）带 `data`；关键字、局部变量、builtin 类型不带。
- **uri 只说一次**：每项都带 uri 让补全回包变大（实测 2,100 项的列表从 185 KB 到 266 KB，§D7.6）。客户端在
  `initialize` 声明 `textDocument.completion.completionList.itemDefaults` 含 `"data"`（LSP 3.17）时，回包改成
  `CompletionList`，`itemDefaults.data` 放一次 `{uri}`，代码里补出来的项不再带 `data`，只有 `use` 行的项带自己的
  `{uri, module}`（项自己的值优先于默认值，规范如此）。没声明的客户端照旧收到数组、每项带 `data`。VS Code 的
  languageclient 与 Playground 都声明了。这时客户端会把默认 `data` 也套到关键字上，所以 resolve 先按 kind 过滤，
  不可能有文档的项原样回送、不查任何东西。
- **找声明**（`lspq.item_doc_site`）：
  - `module` 在：Module 项读该模块的模块文档；其他项在该模块的 parse 树里按名字找顶层声明
    （`decl_lo_named`：fn、type 与别名、const、trait、effect，然后是构造器）。
  - `module` 不在（代码里补出来的项）：按 kind 在文档的作用域里解析，读的就是 hover 的落点：Function 走
    `sig_of` 再 `site_of_sig`（与 hover 同序：本模块、std、builtin），Class 走 `adts_by_name`，EnumMember 走
    `ctors_by_name`，Constant 走 `site_of_const`；trait、effect、别名先找本模块声明，再找按名字导入的。
    同名时 kind 区分：与函数同名的局部变量是 Variable，没有文档；记录类型与它的构造器同名，kind 不同。
  - 模块还没载入（`use` 行正在写的那个模块，按定义它不在程序里）：按补全时用的同一份候选表找到文件，
    经 `def_source` 读文本、parse 一次、按名字找声明。这种文档的链接原样保留：没有检查过的模块就没有
    可用来解析链接的作用域。
- 复用 A3 的 `doc_memo`：resolve 与 hover 共用同一张按文本记忆的注释表。

### D7.3 `use` 行

- **模块路径上 hover**：`use std/list` 的 `std/list` 上，回 `use std/list` 的围栏加模块文档。模块在程序里
  或在 std 里时有文本（`holder_by_path`）；用它的 parse 树判断「开头的 `##` 块属于模块而不是第一个声明」
  （`module_doc_of` 的规则）。预检：文本去掉开头空白后不以 `##` 开头的，不词法。没有模块文档的模块，
  回包与之前逐字节相同。
- **选择性导入的名字上 hover**：fn、type、构造器、const 原来就带文档（A3.2）；trait 与 effect 原来在
  `use` 行上没有 hover，现在按声明给 `trait Tool[T]`、`effect Ask` 加文档，并能跳到声明。

### D7.4 signatureHelp

只给函数整体的文档（`SignatureInformation.documentation`）。**不做逐参数文档**（`ParameterInformation.documentation`）：
Dawn 没有 `@param` 一类记号，引入它就是调研 §3.3 否掉的约定小节；具名实参让参数名本身成了 API，参数的说明
写在正文里用反引号已经够读。文档的位置与 hover 在被调用者名字上读到的相同（`sig_doc_site` 即 `site_of_sig`）。

### D7.5 Playground

- **网关**（`playground/lsp_gateway.py`）：自己拼给子进程的 `initialize` 加上
  `completionList.itemDefaults: ["data"]`（§D7.2），补全回包里 uri 只出现一次。白名单放行 `completionItem/resolve`，照 A4 对 inlayHint 的做法逐字段重建：
  只有 `label`（非空、≤ 256）、`kind`（1–25）、`data` 过网关；`data.uri` 必须是 Playground 那一个文档，
  `data.module` 必须是由 `/` 连起来的单词字符段（不可能是文件路径或 URI）。回包也重建：只留 `label`、`kind`、
  `detail`、`data` 与 markdown/plaintext 的 `documentation`，服务端以后若加 `command`、`additionalTextEdits`
  也不会漏过去。capabilities 的 `resolveProvider` 改为 `true`。
- **play-ui**（`site/play-ui/src/lsp.ts`）：`initialize` 声明 `resolveSupport` 与 `itemDefaults: ['data']`，收到
  `CompletionList` 时把 `itemDefaults.data` 补给没有自己 `data` 的项。带 `data` 的项给 CM6 一个 `info` 函数，选中该项时才发 resolve（懒加载），
  正文经 hover 的 `docText` 转成纯文本（`file://` 链接只留代码 span），用 hover 的 `docNode` 画成
  `.dp-completion-doc`。info 面板固定宽度、超高滚动，在列表里上下移动只换文字、不改面板大小；字比 hover 小一号、
  颜色用 `--muted`。没有文档或请求过期时不显示面板。Playground 的网关不放行 signatureHelp，这一半只在编辑器里有。

### D7.6 实测

本机 16 核，WSL2，GraalVM CE 21；测量时机器上还有别的写者在跑，load average 35–50，所以只看交错对照，不看绝对值。
改前 = 父提交 `9fb834d0` 的工具链，与改后交错跑。三个缓冲区（`--uri untitled:*`）：`plain2000`（2,000 个无文档函数，
补全列表 2,100 项）、`docs2000`（同样 2,000 个函数，每个两行 `##`，每轮先改文本，所以每次 resolve 都是注释表的未命中）、
`stdfold`（一行 `use std/list`，补全落在 prelude 的 `fold` 上，约 100 项）。

**补全列表本身**（`lsp-workspace-contract` 的客户端，同一缓冲区上三个服务端轮流请求，丢掉前 20% 作预热）：

| 缓冲区 | 改前 | 改后，每项带 `data` | 改后，`itemDefaults` | 回包字节（改前 / 每项 / 默认值） |
|---|---|---|---|---|
| `plain2000`（60 轮） | 139.4 ms | 140.9 ms | 128.0 ms | 185,481 / 266,250 / 185,572 |
| `stdfold`（200 轮） | 2.46 ms | 3.12 ms | 2.80 ms | 8,819 / 11,446 / 8,908 |

大列表上没有可测差异；小列表上每项带 `data` 多出约 0.6 ms，是多序列化的那 30% 字节，声明了 `itemDefaults` 的客户端
（VS Code、Playground）回包与改前只差几十字节。

**resolve**（`lsp-bench.py` 的 `resolve` 列，11 轮、预热 3 轮、每格 n = 8，两遍）：

| 缓冲区 | resolve 中位数 | 说明 |
|---|---|---|
| `plain2000` | 5.3 / 9.3 ms | `f1999` 无文档：字符串预检即答，时间是重取分析快照与解析 kind |
| `docs2000` | 18.5 / 10.7 ms | 8,000 行、4,000 条文档注释，每轮改文本后第一次取文档要词法整段（A3.4 的最坏情形） |
| `stdfold` | 2.1 / 1.2 ms | std 的注释表在会话里只词法一次 |

同一组跑里 hover、definition、inlay 的中位数前后落在两遍之间的波动里。

### D7.7 不做的（D7 内，理由）

- **逐参数文档**：见 D7.4。
- **列表时就带文档**（不用 resolve）：见 D7.2；VS Code 与 CM6 都支持懒取，只有不支持 resolve 的客户端看不到文档，
  它们本来也只显示 `detail`。
- **补全项的 `detail` 改成带文档的长文本**：`detail` 是一行签名，客户端把它画在列表里，放文档会把列表撑乱。
- **没载入模块的文档链接**：见 D7.2 最后一条；要解析就得先检查那个模块，那是一次分析，不是一次 resolve。
- **`use java` 行**：Java 类没有 `##`。

## B1. 省略的默认实参（inlay hint）

调用处省掉了带默认值的形参时，在实参括号里补一条提示，写出省掉了哪些形参、各自的默认值**源码文本**：

```dawn
let a = pad(s, 4«, fill: " "»)
let b = span(«lo: 0, hi: 9»)
let g = cursor.find(s, "a"«, from: start(s)»)
```

调研报告（C4）原先把这一项放在 B 组，前提是「要显示**求得的值**才比 signatureHelp 多给信息，所以要等
C5 的求值入口」。本刀推翻这个前提：signatureHelp 只在光标停在实参列表里时出现，读者扫过一屏代码时看不到；
提示回答的是「**这次调用有一个实参没写出来**」，这件事在源码里没有任何痕迹，有没有值都是信息。求值另算
（见 B1.7）。

### B1.1 形状与位置

- **一条调用一条提示**，`kind: 2`（Parameter），不要 padding。标签是 `name: text` 按**声明序**用 `, ` 连起来；
  括号里已经写了实参时以 `, ` 开头，画出来就是一段合法的具名实参：`pad(s, 4, fill: " ")`。clangd
  `DefaultArguments` 也是一条提示装下所有被省的实参。
- **位置**：括号里最后一个写出的实参末尾；括号里没有实参时紧跟 `(` 之后；调用没有括号（`5 |> zero`）时
  在名字末尾，标签自带括号：`5 |> zero«(m: 1)»`。放在实参列表末尾而不是「被省的那个位置」：中间省掉的
  形参只能靠具名实参跳过，具名实参可以写在任何位置，所以末尾的那段文字照抄进源码仍然合法、语义不变
  （`mid(s, last: 2«, gap: 1»)`）；插在中间反而要把后面的位置实参改成具名的。
- **哪些形参算被省**：用 checker 自己的规则 `types.arg_slots`（位置实参从左往右占、具名实参占它的名字、
  尾随块占最后一个形参），前面补上接收者占的槽。所以具名乱序、`x |> f(a)` 管道插入的实参（在括号外，
  不影响落点，参与计数）、尾随块（`each([1]«, step: 1») { n => … }`，提示在 `)` 前、块之前）、UFCS
  （`s.pad(4«, fill: " "»)`，接收者占第 0 个形参）、模块限定（`str.pad_start`、`df.span()`）都与调用的
  实际含义一致。
- **出错的调用不给**：有实参落不到形参上（名字不存在、给了两次、位置实参过多），或有一个没默认值的形参
  没给，诊断已经在报，提示不再猜。checker 对后者与参数个数错误直接产出 `XError`，那些调用本来就没有签名可读；
  前者仍然类型化成对 `pad` 的调用，靠 `arg_slots` 的判据拦下（负控见 B1.5）。
- 覆盖的调用与 A4 的效果行相同：具名函数（本模块、别的模块、std）、trait 方法、经 UFCS 或模块限定的同一批。
  builtin、效果操作、局部函数值的签名没有默认值（`Sig.param_defaults` 为空），不会出提示。
  `x |> m.f`（管道进一个不带括号的点号名）今天在 checker 里是「把 `m.f` 当函数值调用」，函数值没有默认值，
  这样写省掉默认实参本身就是一个参数个数错误；不是本刀的事。

### B1.2 文本与截断

- 文本是 `Sig.param_defaults` 里作者写的默认值（K0 起就有，已经压成一行），与 signatureHelp、hover 的签名同一份。
- **截断**：沿用 A4 的界 `TYPE_HINT_SHOWN = 25` 个码点，但超界时**不是整条不给**，而是这一项写成 `name: …`。
  A4 对类型整条不给的理由是「截过的类型不能照抄成标注、长类型正该去 hover 看」；这里提示的主要信息是
  「有一个实参没写」，整条丢掉就把这件事藏了，而全文就在 signatureHelp 里。每一项各自判界，一条调用里短的
  默认值照常显示（`, fill: " ", why: …`）。

### B1.3 与 K6「默认值读前面的形参」的关系

K6 起默认值可以引用声明在它前面的形参：`fn find(s: String, sub: String, from: Cursor = start(s))`。提示显示的是
**被调者**的表达式，`from: start(s)` 里的 `s` 是 `find` 自己的形参，不是调用处的变量；调用处写的是
`cursor.find(name, "w")` 时，提示仍是 `start(s)`。不做替换（把 `s` 换成 `name`）：那等于重新打印一棵表达式树，
实参若不是简单名字还要加括号、处理遮蔽，而且替换后的文本是一个调用处并不存在的表达式。读者把 `s` 读成
「第一个形参」就够了，signatureHelp 就在旁边列着形参名。

### B1.4 默认开

`initializationOptions.inlayHints.defaultArguments`，默认 **开**（A4.3 的五个键之一）。业界没有一家默认开
（clangd `DefaultArguments` 关、rust-analyzer `missingArguments` 关、Kotlin 只在 override 上显示），这里不跟，理由：

1. **这是源码里唯一完全看不见的实参。** A4 让参数名默认关，理由是 Dawn 有具名实参，作者想让读者看见名字就可以写；
   被省的默认实参没有可写的地方，写出来就不叫省了。类型与效果行默认开，是同一条判据：源码里看不出来、
   又会改变读者对这行代码的理解。
2. **数量少。** 默认参数在 Dawn 里是 2026-08 才有的（#207），std 里带默认值的公开函数约十个（`str.pad_start`、
   `fmt.parse_int`、`cursor.find`、`narrow.round_*`、`gpu.launch` 等），K 线的调研结论也是「std 真候选少」。
   C++ 默认关的一大原因是标准库里默认实参遍地都是（allocator、comparator），Dawn 没有这个噪声源。
3. **Dawn 的默认值是纯的**（spec §3），提示文本不会隐藏副作用，只是把一个读者看不到的值摆出来。

### B1.5 测试与负控

- `lsp/lspinlay` 两条：一条提示、`, ` 开头与否、无括号自带括号、空列表不给；超界写成 `…` 且只影响那一项。
- `lsp/server` 四条，都经 `handle_inlay_hint`：各形状（位置、空括号、具名乱序、中间省掉、尾随块、UFCS、
  std 模块限定、K6 的 `start(s)`、管道带括号与不带括号、超界、全写出的不给）；`kind: 2` 无 padding、
  `defaultArguments: false` 关掉；模块限定调用省掉第一个形参（探针 std 的 `df.span()`）；出错的调用不给。
- 负控（每条单独改、跑 `./bin/dawn test selfhost`、还原）：
  - `arg_slots` 的非 `SlotAt` 不退出 → 「出错的调用」一条红（`pad("x", 1, nope: 2)` 出了 `, fill: " "`）；
  - UFCS 不补接收者槽 → 各形状一条红（`s.pad(4)`）；
  - 默认值改成关 → 两条红；
  - 去掉 `…` 截断 → `lspinlay` 与 `server` 各一条红；
  - `receiver_slots` 不认默认值填充 → 模块限定那一条红（`df.span()` 只剩 `hi: 9`，`lo` 被当成接收者）。
  - 「没默认值的形参没给就不出」这条判据改掉后测试仍全绿：这类调用 checker 产出 `XError`，走不到这里。
    判据留着作防线，不算有门禁覆盖。
- `receiver_slots` 的修正顺带修了 A4 参数名的同一处：模块限定调用省掉第一个形参时，默认值填充节点的 span
  是整个调用，起点正好与别名相同，旧判据把它当成 UFCS 接收者，参数名会错一位。今天只有带默认值的首个形参
  加具名实参才会撞上。
- `scripts/selfhost-lsp-diff.sh` 会话新增 `dflt.dawn`、`defaults.dawn`，按默认选项请求一次全文 inlayHint；
  原有的 `inlays.dawn` 里 `pad_to(tag, width, "-")` 省掉了 `why`，回包多出 `, why: …`。提交里写 `Emit-Change(lsp)`。
- Playground：网关对 inlayHint 只按 range 逐字段转发，回包不过滤；CM6 的 decoration 按 label 原样画。
  两处都**不用改**，截图验过（浅、深各一张，在仓外协作档）。

### B1.6 实测

`lsp-bench.py --uri untitled:*`，11 轮、预热 3 轮、每格 n = 8；父提交 `842ac8b5` 的工具链（另起 worktree 构建）
与本刀交错两遍。本机 16 核，WSL2，GraalVM CE 21，测量时机器上有其他写者（load 约 10），只看交错对照。

| 缓冲区 | 提示数（父 / 本刀，全文） | inlay 全文中位数（父 / 本刀，两遍） | inlay 一屏中位数（父 / 本刀，两遍） | hover 中位数（父 / 本刀，两遍） |
|---|---|---|---|---|
| `defaults2000`：2,000 个函数，各两条 `let` 调 `pad` 省掉 `fill`（一次位置、一次具名乱序），12,001 行 | 4,000 / 8,000 | 57.3, 38.6 / 81.8, 54.8 ms | 2.06, 1.62 / 2.41, 1.61 ms | 29.5, 23.9 / 26.1, 21.0 ms |
| `written2000`：同上但 `fill` 都写出来（没有可提示的默认值） | 4,000 / 4,000 | 55.9, 41.5 / 44.6, 42.5 ms | 2.35, 1.74 / 1.62, 1.68 ms | 32.3, 25.7 / 27.7, 25.9 ms |

- **一屏的请求仍在 2 ms 上下**，与 A4.5 同一量级；编辑器只发这种请求。
- 全文请求多出的时间来自多出的 4,000 条提示（每条一次位置换算与一个 JSON 对象），与 A4.5「全文请求的大头是
  提示本身」一致；没有可提示的默认值时（`written2000`）两边落在波动里，`arg_slots` 只在签名带默认值时才跑。
- hover 不受影响：收集器为 `None` 时 `hint_default_args` 第一行就返回。

### B1.7 不做的（B1 内，理由）

- **显示求得的值**（调研 C4 的原提议）：要 C5 的解释器入口、fuel 预算与 native 栈深实测，仍在 B 组；
  而且 K6 之后默认值可以读前面的形参，值取决于这次调用的实参，`find` 的 `from` 就是 `start(s)` 的那个游标，
  显示成一个数字反而不如源码文本好懂。重开条件：C5 落地，且有默认值的文本确实读不懂的实例。
- **把被调者形参名替换成调用处的实参**：见 B1.3。
- **每个被省形参一条提示**：同一位置的多条提示在编辑器里挨着画，分隔符要靠 padding 拼，CM6 与 VS Code 画出来
  不一样；一条提示的标签自己带 `, `，在两边读起来都是一段合法的实参列表。
- **提示可点击插入（`textEdits`）**：把默认值抄进调用就失去了「随被调者的默认值变」的意义，没有理由鼓励。
- **构造器的默认字段**：Dawn 的记录与构造器字段没有默认值。

## C5. 纯且闭合表达式的 hover 求值

光标停在一个复合表达式上时，若它闭合（不引用表达式外绑定的局部）且纯（被调方效果行为空），hover 在类型后面
给出它的值。立项依据是 2026-10-03 的调研与裁决（仓外协作档）：判据、UI 与预算都在那里定了，这里只记落码时的
取舍。分两刀：**C5-1** 是解释器入口（本节 C5.1–C5.5，已落地），**C5-2** 是 LSP 接线（判据、`Target.expr`、
hover 拼接，C5.6–C5.12，已落地）。前置 E1（#416，comptime 跨模块调用）、E2（#417，native 深度上限）、E3（#418，fuel 按
分配大小计）均已合入。

### C5.1 入口：`ir/interp.eval_closed`

- `pub(pkg) fn eval_closed(tm, world, scope, ct, std 三张表, std_names, adts, traits, impls, owner, e, opts)
  -> Result[CValue, String] !io`：对一个已检查模块里的闭合表达式 `e` 求值。闭合与纯由调用方判（只有它有
  span 可判），入口不重判；解释器自己的动态兜底（拒绝 io builtin、Map/Set、`cmp`、cell、ctl）照旧生效。
- **上下文与构建期同一份**：`eval_module_in` 里组装 `ICx` 的那段抽成 `module_icx`，构建期的模块运行与
  `eval_closed` 共用；后者再填上模块那次运行已经折好的 `ct.consts` 与 `ct.blocks`。所以 `e` 在这里的含义就是
  它写在该模块一个 `comptime` 块里时的含义，表达式里嵌的 `comptime { … }` 读的是那次运行留下的值。
  E1 的 `CtWorld` 一并接上：调工程里先分析的模块的纯函数，与构建期 comptime 走同一条路（`world.owners`）。
  传入的 `world` 是「本模块之前」的那一份，与 `eval_comptime_in` 相同。
- **不留状态**：lowering 缓存每次从空开始、用完即弃，一次求值不影响下一次看到的东西。实测里中位数在
  个位毫秒（调研 §3.2），缓存的失效条件比求值本身复杂，不做（调研 6.3）。
- **失败一律回 `Err(原因)`**：原因是一行、去掉构建期诊断的 `comptime: ` 前缀。fuel 耗尽、深度超限、解释器拒绝
  都在这条路上。（C5-1 时设想 C5-2 把它拼成 A1 同形的 `(not evaluated: 原因)`；C5-2 落地时改为一律不显示，见 C5.8。
  原因仍回给调用方，测试靠它区分「是预算拦下的」。）

### C5.2 `catch_panic` 屏障

lowering 与解释器遇到不变式被破坏时 panic（ARC-06），构建期这是对的：编译器该停。hover 跑在语言服务进程里，
一次 hover 不能把进程带走，所以整个 `fold_expr` 套在 `catch_panic` 里，panic 回 `Err("panic: <消息首行>")`。
首行保留 L2（#425）给 panic 加上的调用点后缀 ` at src/ir/lower.dawn:L:C`，不剥：这类 panic 只在编译器有 bug 时出现，
读者要做的是报 bug，调用点正是报告里最有用的一行；剥掉它就得在解释器里再写一份「消息末尾哪段是调用点」的解析，
与 `catch_panic` 交出的消息形状（L2 的调研已定：调用点是消息的一部分）各说各话。测试只钉住消息与文件，不钉行列。
它是**第二道**防线：模块有错时 TAST 里有 `XError`，lowering 必 panic，所以调用方与 A1 一样只在模块无错时求值；
屏障兜的是这条规则没预见到的情形。调研的负控已经证明去掉它时注入的 lowering panic 让 LSP 进程退出，
所以它进门禁（C5.4）。JVM 的 `OutOfMemoryError` 不归它管：E3 让 fuel 在分配之前按大小扣，内存由 fuel 界住。

### C5.3 预算：`HOVER_FUEL`、`HOVER_DEPTH`、`ct_hover`

- `HOVER_FUEL = 100000`、`HOVER_DEPTH = 1500`，`ct_hover(host) = { fuel: HOVER_FUEL, depth: min(HOVER_DEPTH, host.depth) }`。
  JVM 与 native 同值（裁决第 2 条及 10-04 追裁：同一份代码在 VS Code 与 Playground 给同一答案；1,500 即 native
  宿主上限 `NATIVE_CALL_DEPTH`）。`min` 只是防御：今天两端都取到 1,500，宿主上限将来若更低，以宿主为准。
- **常量放解释器侧，不放 lsp 侧**：深度是关于解释器宿主栈的断言，不能超过 `NATIVE_CALL_DEPTH`，而知道栈能撑多深的
  是 `ir/interp`；lsp 已经从这里取 `ct_default`，常量放在 lsp 等于把数字放到离它所服从的上限隔一层的地方。
  两个编辑器调用方（C5-2 的 hover、之后 C4 的默认实参值 inlay）都经 `ct_hover` 取预算。
- 预算由调用方以 `CtOpts` 传入，入口不自己选：测试要用别的预算证明「是预算拦下的」（同一表达式加 fuel 或加深度
  就求得出值）。

### C5.4 测试与负控

- `ir/interp_test` 五条：预算两端相同且不超宿主深度（`ct_hover(ct_default()) == ct_hover(ct_native())`、
  浅宿主保留自己的深度）；求值（调本模块函数加 const、表达式内嵌的 comptime 块读运行留下的值）；fuel 耗尽与深度
  超限回 `Err`，同一表达式放宽预算后求得值；跨模块纯函数经 `CtWorld` 求得值，换成空世界回 `Err`；注入 `XError`
  （表达式本身，lowering 在解释器启动前 panic）与把被调函数体换成 `XError`（解释器按需 lowering 时 panic）都回
  `Err("panic: lower: XError reached lowering")`，之后入口照常可用。
- 变异负控 `scripts/comptime-eval-closed-contract/run.sh`：在 selfhost 的私有副本里去掉屏障、编译并跑测试，要求
  恰好上面最后一条变红，且 FAIL 行下面是逃出来的 panic 原文。测试运行器按条接住 panic，所以证据是「panic 原文
  出现在这条测试名下」而不是进程退出；在没有这层 try/catch 的宿主（语言服务）里，这就是进程退出。
- 构建期 comptime 行为零变化：`module_icx` 是纯搬移，prev-diff、prev-diff-native、lsp-diff 无字节差异，
  没有 `Emit-Change`。

### C5.5 不做的（C5-1 内，理由）

- **入口内重判闭合与纯**：判据要 span 与 TAST 的绑定信息，是 lspq 的事；解释器侧重判就是第二份判据，会漂。
- **入口内自选预算**：见 C5.3 末条；编辑器的预算只有一处定义（`ct_hover`），入口只执行。
- **跨请求缓存 lowering 结果**：见 C5.1。
- **接住 JVM 的 `OutOfMemoryError`**：OOM 之后 JVM 状态不可信，E3 已在分配之前用 fuel 拦（调研 6.3）。

### C5.6 判据：`lsp/lspeval.fold_refusal`

判据与求值放在新模块 `lsp/lspeval`，不放 `lspq`：`lspq` 管「光标下是什么」，这里管「那个东西能不能、值得不值得
求值」，两件事的失败方式不同，`lspq` 也已经三千多行。`lspq` 只做两处改动：`Target` 加 `expr: Option[TExpr]`，
只有 `walk_e` 的通用兜底填 `Some`（所以被求值的正是 hover 高亮的那一段）；`sym_get`、`sig_by_owner` 改为 `pub(pkg)`。

按调研第二节，逐构造器遍历 TAST，任一条不满足即拒绝（返回原因，只给测试与读代码的人看）：

- **没有可显示的值**：类型是 `Unit`、`Never`、函数，含类型变量或关联类型，或不可 const 序列化（与 comptime 块对
  结果的要求同一个集合）。
- **不计算**：字面量、局部变量、常量引用、函数值、构造器值、`comptime` 块本身（A1/A2 已有各自的 hover）；
  字符串只有含 `${}` 时才算。
- **闭合**：每个 `XLocal`、`XCallDyn`、`TSAssign` 的符号声明位置 `Sym.dlo/dhi` 落在表达式 span 内；符号不是字典、
  证据或 handler 状态槽；没有 `XEvRead`；witness 里没有 `WForward`（递归查 `WApply`）；`return`、`?` 只出现在
  表达式自己的 lambda 或局部函数里，`break`、`continue` 只出现在表达式自己的循环里。
- **纯**：没有 `XJava`、`cell_*` builtin；`XCallFn`/`XCallBuiltin` 被调方签名的行没有标签、没有 io、没有关联效果，
  行里有效果变量时每个函数类型实参的行必须为空；`XCallDyn`/`XApply` 被调值的 `TyFn` 行为空。签名查不到（K0 的
  `f$default$k`）时放行，由解释器的动态拒绝兜底。

模块有类型错误时不求值，与 A1 同条件。

### C5.7 上下文：`Program.ct_world`

`eval_closed` 要模块的 `CtWorld`。分析结束后 `Program` 里原本没有它，`CheckedMod` 也不记「这个模块的 comptime
跑没跑」（解析失败的模块 `cx.diags` 为空却没跑），所以从模块表重建「本模块之前」的世界做不准。改为 `Program` 带上
**跑完全部模块之后**的那一份（`analyze_observed` 与增量会话 `incremental` 各一处赋值，`carry.ct_world` 本来就在）。
多出来的只是本模块与它之后的模块：本模块自己的函数 `module_icx` 本来就放在最前面，之后的模块按 DAG 不可能被本模块
的表达式调到，所以答案与用「之前」的那一份相同；代价是一个引用。

### C5.8 显示什么

| 情形 | hover |
|---|---|
| 判据放行、求出值 | `T = 值`，与 A1 同形（`lspv.value_text`：十六进制、截断、长度后缀照 A1） |
| 值渲染后与源码相同（去空白比较，`lspv.value_echoes`） | 只显示类型 |
| 判据拒绝 | 只显示类型 |
| 求值失败（fuel、深度、解释器拒绝、panic） | 只显示类型 |

与调研 5.3 的差别：调研建议「判据放行、解释器拒绝」时写第二行 `(not evaluated: 原因)`，本刀按任务裁定**一律不写**。
理由：读者看不出「判据放行」与「判据拒绝」的界线在哪里，同样是不显示值，一种写原因、一种不写，只会让人以为后者是
漏了；而 hover 求值本来就是附赠，求不出时类型照旧正确。A1 的 const 不同：const 的值是构建要用的，求不出就是一个
构建期诊断，hover 必须说明。`Unit` 在判据里就拒绝（不求值），回声在求值后判断。

### C5.9 预算与两端一致

`server.hover_value` 以 `ct_hover(st.host.ct)` 调用：JVM 的宿主深度 100,000、native 的 1,500，`ct_hover` 两端都取
fuel 10⁵、深度 1,500。同一份代码在 VS Code（JVM）与 Playground（native）给同一答案，由
`scripts/native-cli-diff.sh` 第 12 腿逐点对拍（下节）。

### C5.10 测试与负控

- `lsp/server` 三条，都经 `hover_value`（与 `textDocument/hover` 同一路径）：
  - 求出值：本模块函数调用（`fib(15) + 1` → `Int = 611  (0x263)`）、插值读常量、效果多态的 `map` 配纯 lambda、
    整个块（块里自己绑的 `z`）、深度 1,400 的递归；块内 `z * z` 只显示类型（`z` 在它外面绑定，不上爬）。
  - 只显示类型：外层局部 `k + 1`；签名 `!io` 但函数体什么也不做的 `noisy(1) + 2`；把有效果 lambda 传给 `map`；
    超 fuel 的 `spin(60000)`；超深度的 `down(1600)`；回声 `[1, 2, 3]`；`Unit`；可能 `return` 出去的 `if`；`println`。
  - 模块有错时不求值。
- 变异负控（一次性，私有副本里改一处、跑 `dawn test selfhost`，各恰好一条红）：
  - 去掉闭合判据（局部一律算闭合、`return`/`break` 一律放行）→ `if 1 > 3 { return 0 } else { 5 * 2 }` 显示
    `Int = 10`。只拿「外层局部」那条是抓不到的：解释器找不到符号会报错，结果仍是只显示类型；会给出**错值**的是
    逃逸，这正是调研 3.3 说判据管的是诚实而不只是安全。
  - 去掉纯判据（行一律算纯）→ `noisy(1) + 2` 显示 `Int = 4`。同理，`println` 抓不到（解释器拒绝 io builtin），
    要用「声明了效果、函数体却能折」的被调方。
  - 预算放宽（用宿主的 `ct_default` 而不是 `ct_hover`）→ `spin(60000) + 3` 被求出值。
- `scripts/selfhost-lsp-diff.sh` 会话新增 `evals.dawn`，hover 十一处（同上各情形）；原有 `literals.dawn` 里
  `"n = ${MASK}"` 由 `String` 变为 `String = "n = 255"`，其余既有回包逐字节不变（以父提交为参照的无遮蔽对照）。
  提交里写 `Emit-Change(lsp)`。
- `scripts/native-cli-diff.sh` 第 12 腿：JVM 与 native 服务端对同一缓冲区七个点逐点 hover，要求两端相同、至少一处
  显示了值（防两端都不求值而空对空一致）、`down(1600)` 两端都不显示。负控：native 换成父提交（不求值）的 dawnc，
  四个点报不一致、该腿变红。第 4 腿（native 对上一 release）跑同一份会话，但有 Emit-Change 可遮蔽，所以另立此腿。

### C5.11 实测

本机 16 核，WSL2；native 用 `cc -O2`（`native-cli-diff.sh` 的同一组参数），同一缓冲区七个点各 hover 11 次，
「中位」是后 10 次。

| 点 | native 首次 / 中位 | JVM 首次 / 中位 |
|---|---|---|
| `fib(15) + 1`（显示值） | 9.3 / 6.0 ms | 27.0 / 1.8 ms |
| `spin(60000) + 3`（fuel 耗尽） | 18.6 / 19.0 ms | 13.4 / 3.9 ms |
| `down(1600) + 4`（深度超限） | 9.0 / 6.9 ms | 9.5 / 2.2 ms |
| `k + 1`（判据拒绝） | 0.4 / 0.4 ms | 0.9 / 0.7 ms |

- **内存**：native 服务端打开这份缓冲区、不 hover 时最大 RSS 47.5 MiB；上面 77 次 hover 后 60.3 MiB（父提交的
  dawnc 同一会话 48.5 MiB）。Playground 的 native LSP 限 `MemoryMax=256M`，余量充足。`s = s ++ s` 翻 29 次的
  分配炸弹（调研 3.6，E3 之前在 JVM 上 OOM）hover 后最大 RSS 48.9 MiB：E3 按大小计费，fuel 先耗尽。

### C5.12 不做的（C5-2 内，理由）

- **写出求不出值的原因**：见 C5.8。
- **从模块表重建「本模块之前」的 `CtWorld`**：见 C5.7。
- **常驻的变异负控脚本**：C5-1 的屏障负控进了门禁，因为屏障失守的代价是进程退出、且没有别的测试能看见；这里三个
  变异体各自都有现成的 `lsp/server` 用例抓红，常驻要多编译三份 selfhost（每份约一分钟）。重开条件：判据被重写。
- 调研 6.3 的其余条目（inlay 全量求值、上爬、选区求值、带 IO 求值、错误模块求值、用户 Show、结果缓存）照旧不做。

## 5. 门禁与契约

- `./bin/dawn test selfhost`：`lsp/lspv` 五条（每种值、记录与和类、十六进制阈值、截断、函数值）；
  `lsp/server` 三条（声明与引用、comptime 关键字与块内最内层、builtin 被拒、模块有错、std 常量经
  探针 std 的选择性导入、裸引用与别名限定）。
- `scripts/selfhost-lsp-diff.sh`：会话新增 `consts.dawn`，hover 九处（声明、`comptime` 关键字、
  截断的表、字符串、被拒的常量、`use util.{LIMIT}`、跨模块引用、`u.LIMIT`、std 的 `memfs.BASE`），
  再改坏模块后 hover 一处；原有的 `LIMIT))` 一处文本随之变化。提交里写 `Emit-Change(lsp)`。
- `scripts/lsp-decl-pairing.py` 的 16 条不 hover 常量名，不受影响。
- A2：`lsp/lspv` 四条（Int、Char、Float、String 各一条，含 `0`、`9`/`10` 阈值、`0x0`、`U+10FFFF`、空串、
  80 码点截断、不精确的浮点与 0.1 的完整展开）；`lsp/server` 两条（各类字面量的整段 hover、const 名与其
  字面量各自命中），A1 那条里块内最内层的断言改落在 `<<` 上；落在 `1` 上的现在是字面量，按 4.4 的一位数
  规则只答 `Int`。会话新增
  `literals.dawn`，hover 十二处（const 名、`0xFF`、`255`、`0b1010`、`1_000_000`、三种 Char、两种 Float、
  两种 String），提交里写 `Emit-Change(lsp)`。会话里没有一位数字面量，一位数规则不改动这份转写。
- A2：`scripts/pipe-contract/run.sh` 的 `hover_qctor_arg` hover 实参位置的 `7`，要求恰好 `Int`；一位数
  规则让它保持原样。改 `selfhost/src/lsp/` 时这道门要跑。
- A3：`front/docs` 两条（声明文档的附着规则、一遍扫描与 `line_of` 对拍）外加从 `doc.dawn` 搬来的一条；
  `lsp/lspdoc` 五条（无文档即单围栏、围栏后接正文、空文档、字符串预检、截断）；`lsp/server` 三条（同模块的
  fn、构造器与 const 带文档，无文档的 fn、局部变量与字面量回包与 A3 之前逐字节相同；探针 std 与内嵌 std
  的声明带文档；注释表按文本记忆）。会话的 `util.dawn` 给 `helper` 加 `##`，`app.dawn` 给 `compute` 加 `##`，
  hover 在跨模块调用 `helper(n)`、本模块声明 `compute` 上带文档；会话里原有的 std 目标（`str.trim`、`fold`、
  consts 会话的 `memfs.BASE`）本来就有 `##`，随之带上文档。提交里写 `Emit-Change(lsp)`。
- A3：`scripts/lsp-decl-pairing.py` 等契约 helper 改经 `scripts/lsp_hover.py` 取第一个围栏（§A3.6）。
- A4：`lsp/lspinlay` 三条（类型提示的 25 码点界与错误类型、效果行要具名且无变量、参数名的两条隐藏规则）；
  `lsp/server` 六条，都经 `handle_inlay_hint` 的 JSON 回包（let 推断类型、解构的每个名字、已标注跳过；lambda
  形参与超长类型；操作调用、带标签的函数、局部函数值的效果行，纯调用与 `!e` 调用不给；range 两端都含、按位置、
  `kind` 与 padding；参数名默认关，`initializationOptions` 打开后的两条隐藏规则；尾随块的效果行落在 `)` 后）。
- A4：`scripts/selfhost-lsp-diff.sh` 会话新增 `inlays.dawn`，`initialize` 带
  `initializationOptions.inlayHints.parameterNames: true`，请求两次 inlayHint（全文、`let xs` 那两行）；上一 release
  对它回 `-32601`，`initialize` 的 capabilities 也多了 `inlayHintProvider`。提交里写 `Emit-Change(lsp)`。脚本把
  completion 数组按 label 排序的规范化改为跳过带 `position` 的数组：提示的顺序是服务端定的（按位置），要原样比。
- A4：Playground 网关白名单放行 `textDocument/inlayHint`（range 逐字段重建后转发，capabilities 多一个
  `inlayHintProvider`），`playground/test/lsp_contract.py` 加一条（多余的键不过网关）；`site/play-ui` selftest 加六条
  （回包校验、class、decoration 位置、请求形状与坏项过滤）。
- D7：`lsp/server` 六条，都经 JSON 回包：resolve 带文档（本模块、按名字导入的 std 函数），无文档的声明与关键字不带、
  未知文档原样回送；声明了 `itemDefaults` 的客户端收到 `CompletionList`、uri 只在默认值里出现一次，关键字带着默认
  `data` 回来也原样回送；`use` 行补出的模块与成员（模块文档带解析后的链接、const、trait、effect，无文档的 fn 不带）；
  没载入的同目录模块从文件读；signatureHelp 带文档与不带；`use` 行 hover 的模块路径与选择性导入的 fn、const、
  trait、effect。负控：resolve 不填 `documentation` 时前两条变红（见报告）。
- D7：`scripts/selfhost-lsp-diff.sh` 会话加一次 resolve（util 的 `helper`）和一次 `use std/list` 上的 hover；上一 release
  对 resolve 回 `-32601`，`use` 行只回围栏；补全项多了 `data`，`initialize` 的 `resolveProvider` 变为 `true`。
  提交里写 `Emit-Change(lsp)`。
- D7：网关合约加两条（resolve 的项逐字段重建、多余字段与服务端的 `command` 不过网关；data 指向别的文档或模块路径
  不合法时拒绝）；`site/play-ui` selftest 加七条（有 data 才有 info、列表不触发 resolve、请求形状、回包、链接去目标、
  `itemDefaults.data` 补给缺 data 的项、无文档不显示）。`lsp-bench.py` 加 `resolve` 一栏。

## 6. 实测

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

## 7. 刀序

| 刀 | 内容 | 前置 | 验收 |
|---|---|---|---|
| **A1** | hover 显示 const 与 comptime 块的值（本文 §3） | 无 | lsp-diff 会话加 const 声明、引用（跨模块、std）、comptime 关键字、失败与有错各一处；`Emit-Change(lsp)` |
| **A2** | 字面量 hover：Int 进制对照、Char 码点与 UTF-8、Float 是否精确、String 码点数与 UTF-8 字节数（本文 §4；f32 舍入与「只在拼写与值不同时给」改为不做，理由见 §4.4） | A1 的单围栏格式稳定 | 会话加 12 处字面量；`Emit-Change(lsp)` |
| **A3** | `##` 文档进 hover：先把 `doc.dawn` 的 `doc_of` 挪到 `front/`（`dawn doc` 输出逐字节不变），再拼正文段；同一 PR 把契约 helper 统一成「取第一个 ```` ```dawn ```` 围栏」、Playground `hoverText` 支持多段 | A2 | `dawn doc` 不变；会话加一处带 `##` 的 hover；Playground 加一条 |
| **A4** | `textDocument/inlayHint`：`let` 推断类型、lambda 形参类型、参数名（默认关）、调用处的单态效果行；网关白名单与 CM6 decoration 可拆成 A4′ | A3 | 会话加一次 inlayHint；`lsp-bench.py` 报 inlay 延迟 |
| B 组 | 纯且闭合表达式的 hover 求值、被省略默认实参的值 inlay、效果多态调用的实例化行、`?` 的错误类型、semantic tokens、references → rename | 解释器 pub(pkg) 入口、闭合检查、lowering panic 的负控、hover 用 fuel 的墙钟实测、native 栈深实测 | 各自立项时定 |

## 8. 不做的（理由）

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

## 9. 状态

| 刀 | 状态 | 提交 |
|---|---|---|
| A1 | 已落地 | `615d3116` |
| A2 | 已落地 | `30419580` |
| A3 | 已落地 | `597dfb3a` |
| A4 | 已落地 | `5c07b1e6` |
| A5（文档注释 D4） | 已落地 | |
| D7（文档注释 D7） | 合入后由协调者回填 | |
| B1（省略的默认实参 inlay） | 已落地 | `31519d46`（main 上的哈希，PR #421） |
| C5-1（解释器入口 `eval_closed`） | 已落地 | `98f000f5`（main 上的哈希，PR #432） |
| C5-2（hover 接线） | 已落地 | 合入后由协调者回填 |
| B 组其余 | 未立项 | |
