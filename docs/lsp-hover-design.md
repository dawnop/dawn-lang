# LSP 悬停与内联提示：设计（A1–A4）

> 状态：current。本线的总纲：除类型之外，hover 与 inlay 还能告诉读者什么、按什么刀序做。
> A1（hover 显示 const 与 comptime 块的值）已落地；A2 已落地（§4）；A3 已落地（§A3）；A4 落地时回填 §9「状态」，
> 并在这里改写被事实推翻的前提。调研依据是 2026-10-02 的只读调研报告（仓外协作档，结论摘在 §2）。

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
| 字段 | 否 | `dawn doc` 不给字段文档，hover 不另立一条附着规则 |
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
- **模块文档进 `use` 行 hover**（`module_doc_of`）：`front/docs` 已经能给，但 `use` 行的 hover 今天只回
  `use std/list`，加文档是独立的一小刀，留到有需要时做。
- **字段文档**：见 A3.2。
- **把文档渲染成 HTML、改写 markdown**：编辑器自己渲染 markdown；Playground 按纯文本显示正文。
- **builtin 的文档**：builtin 没有 `##` 源码；`selfhost/builtins.dawn` 是给人读的镜像，不是 hover 的数据源。

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
| A3 | 已落地（分支 `feat/lsp-hover-docs`） | 合入后由协调者回填 |
| A4 | 未开工 | |
| B 组 | 未立项 | |
