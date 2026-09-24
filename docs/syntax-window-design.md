# 语法破坏性窗口设计（裁决 2，v0.78.0）

> 状态：**proposed** —— 裁决 2（`agent-handoff/rulings-20260924.md`）的落地方案。六条改动一次过，
> 随 v0.78.0 发布；种子推进之前 `selfhost/src` 不用任何新语法，被删掉的拼写全仓迁走。
> 调研（各语言做法与出处）见 `agent-handoff/research-syntax-window-20260924.md`，本文只写 Dawn 的做法与理由。

## 0. 范围

| 编号 | 改动 | 破坏性 |
|---|---|---|
| SYN-N03 + SYN-N01 | `java test assert with in` 降为上下文关键字；三份手抄关键字表改为对账 | 零（只放宽） |
| SYN-N04 | 删 `$name` 插值短形，只留 `${expr}`；`dawn fmt` 在本窗口内做迁移 | 是（fmt 吸收） |
| SYN-N05 + SYN-N11 | 记录只用 `{}`，和类型构造器只用 `()`，表达式位与模式位同规则；AST 不再记括号拼写 | 是（三格关闭，全仓迁移） |
| SYN-N08 | 或-模式允许前导 `\|`；fmt 对齐多行或-模式 | 小（行首 `\|` 不再续接按位或，见 §4.3） |
| SPC-19 | 局部 `fn` 的效果行允许具名效果 | 零（只放宽） |
| RX-08 / SYN-N07 | 维持，不改 | 无 |

## 1. SYN-N03：五个硬关键字降为上下文关键字

### 1.1 语法前后

之前：`java test assert with in` 是 `token.keyword` 表里的硬关键字，词法层就产 `JAVA` / `TEST` /
`ASSERT` / `WITH` / `IN`，任何位置都不能当标识符（`let in = 1`、字段 `test: Int` 都报
`expected a field name, found \`in\``）。

之后：词法层把五个词一律产 `IDENT`，由 parser 在各自唯一的语法位置按文本认：

| 词 | 认作关键字的位置（判据） | 其余位置 |
|---|---|---|
| `java` | `use` 之后、且下一个 token 是字符串字面量：`use java "a.B"` | 普通标识符（模块路径段 `use java/x` 也照常） |
| `test` | 顶层声明首、且下一个 token 是字符串字面量：`test "name" { … }` | 普通标识符 |
| `assert` | 语句首、且下一个 token 能开始一个表达式（字面量、名字、`(`、`[`、`{`、`-`、`not`、`~`、`if`、`match`…） | 普通标识符：`assert = 1` 是赋值，`assert.x` 是字段/方法，行尾的 `assert` 是名字 |
| `with` | 语句首、且下一个 token 是名字（`with x <- …`、`with handle E {…}`、`with _`/`with T` 报原来的诊断） | 普通标识符：`with(x)`、`with = 1` |
| `in` | `for` 头里 pattern 之后 | 普通标识符 |

语句首是唯一有歧义的地方，判据都取「按旧文法这个词后面能跟什么」：旧文法下 `assert` 后面必须是
表达式、`with` 后面必须是名字；作为普通名字，它后面跟一个表达式开头（两个操作数相邻）或一个名字
从来不是合法程序。所以判据只把原本非法的串分给关键字，不夺走任何合法写法。
唯一的例外是 `assert(x)` / `assert [x]` / `assert -x`：旧文法下它们本来就是 assert 语句，
新文法照旧；一个名叫 `assert` 的局部函数在语句首不能写成 `assert(x)` 调用（写 `let r = assert(x)`
或换名）。这与 Kotlin 的 soft keyword、C# 的 contextual keyword 取舍相同。

表达式位遇到 `with x <- …`（旧诊断「`with` is a statement and needs an enclosing block」）照旧报：
`primary_expr` 看到 `with` 后面紧跟名字再跟 `<-` 或 `handle` 时给同一条诊断。

### 1.2 AST 与 token 变化

- `TokKind` 删 `JAVA TEST ASSERT WITH IN` 五个变体，`token.keyword` 表删五行。
- `dawn __lex` 的 dump 里这五个词从此印成 `IDENT`（`lex backend-dawn` 标签的字节变化）。
- AST 不变：`DUseJava`、`DTest`、`SAssert`、`SFor`、`with` 的脱糖产物都照旧。
- `lsp/lspc.dawn` 里用 `IN` / `WITH` token 判上下文的两处改成按文本认。

### 1.3 三份手抄表改为对账（SYN-N01）

真相源是两处源码：硬关键字 = `token.dawn` 的 `keyword` 表；上下文关键字 = `parser.dawn` 里
`is_word(p, st, n, "<word>")` 的调用点（parser 按文本认词一律经这个 helper，所以调用点集合就是清单；
今天 11 个：`opaque ctl as derive handle resume` 加本刀五个）。
- `editors/vscode/test/scope-contract.js`：删掉手写的 `CONTEXTUAL_KEYWORDS` 常量，改成从 `parser.dawn` 的
  `is_word` 调用点抽取，抽取结果为空即红；与 grammar 的 `x-dawn-contextual-keywords` 与 `contextualKeywords`
  模式逐项相等；另加一条：每个上下文关键字在 `let x = <word>` 里不得带任何关键字 scope。
- `dawn.tmLanguage.json`：五个词从 `x-dawn-hard-keywords` 挪到 `x-dawn-contextual-keywords`，
  各配一条带上下文的模式（`use java "`、行首 `test "`、行首 `assert`/`with`、`for … in`）；补上漏登的 `ctl`、`resume`。
- `scripts/doc-check.py`：spec §1.4 的硬关键字代码块与 `token.keyword` 逐项相等、上下文关键字表第一列与
  `is_word` 调用点逐项相等（替换今天只查 `opaque` 一个词的检查）；spec.en.md 同规；五条自检（多/少 × 硬/上下文，
  加一条精确清单不误报）。

### 1.4 fmt

五个词成了 IDENT 之后，`for x in [1, 2]` 会按「标识符后的 `[` 贴紧」印成 `in[1, 2]`，行首 `assert (x)` 同理。
fmt 加一个 token 级集合 `contextual_keywords`：`for` 同深度上的第一个 `in`、行首后跟 `(`/`[` 的 `assert`，
按关键字加空格。其余三个词在关键字位置后面不会跟括号，原规则已经对。

### 1.5 负控

- 探针 `let in = 1`、`let with = 2`、`let assert = 3`、`let java = 4`、`let test = 5` 与 record 字段名
  `test`、`in` 编译通过（旧编译器报错 → 先红）。
- `for x in xs` 仍是循环、`with x <- f()` 仍脱糖、`assert x == 1` 仍是断言、`use java "…"` 仍引入类、
  `test "…" {}` 仍是测试块（parser_test 与 selfhost 测试全绿即证）。

## 2. SYN-N04：删 `$name`，只留 `${expr}`

### 2.1 语法前后

之前：`"$name"` 以词法最长匹配吞标识符（`lexer.lex_dollar` 的第二个分支），`"$obj_x"` 在同时有
`obj` 与 `obj_x` 时静默取后者，`"$obj.name"` 静默变成 `obj` 拼 `".name"`。

之后（**永久规则**）：`${expr}` 是唯一的插值写法。`$` 后紧跟能开始名字的字符（字母或 `_`）是
**词法错误**，诊断同时给出两种改法：

```
error: `$` followed by a name is not an interpolation: `$a`
  = hint: write `${a}` to interpolate it, or `\$a` for a literal dollar sign
```

`$` 后接其它字符（数字、空格、标点、串尾）仍是字面 `$`；`\$` 转义保留（写字面 `$name` 与字面 `${`
都靠它）。这是 Kotlin 的同款规则：`$` 接名字必是插值，字面要转义。

**改裁记录（2026-09-24，协调方）**：裁决 2 原文是「删除后 `"$x"` 里的 `$` 是普通字符，不新增诊断」。
下游勘察（`agent-handoff/site-impact-20260924.md`）数到 dawnop-site 有 307 处 `$name`；若它们静默变成
字面文本，SQL、签名串、URL 全部错文而编译照过。静默错文正是 SYN-N04 要消灭的那一类（合法程序算出
作者没写的值），把它换个方向再造一次不可接受；显式错误让每一处都被看见，fmt 迁移又让修复是机械的。
所以改为报错。

### 2.2 实现

- `lexer.lex_dollar` 的标识符分支改为产一条诊断，字面量本身照旧成一个 token（文本按原样收进 SText），
  所以文件其余部分照常词法、照常报错，fmt 也能拿到完整 token 流。为此 `lex_string` / `lex_triple`
  多返回一组「不阻止 token 成形」的诊断，`lex_go` 汇入总诊断；插值代码里嵌套字面量的这类诊断不在
  外层收集（parser 重新词法插值代码时会报，避免重复）。
- AST 不变（插值仍是 `SPInterp(expr)`）。
- `lexer.is_dollar_name(d)` 按消息前缀认出这一类诊断，fmt 靠它区分「可修复」与「必须拒绝」。

### 2.3 fmt 迁移规则（本窗口）

`dawn fmt` 对每个 STRING token 的源文本做一次改写（`fmt.migrate_dollar_names`）：`\` 转义之后的字符
原样，`${ … }` 内部代码里的嵌套字符串递归同样处理，其余 `$ident`（`ident` 按旧词法最长匹配）改写为
`${ident}`；raw 字符串（反引号）没有插值，不动。`format` 在词法诊断全是 `$name` 类时照常排版（这类
诊断不丢 token），其它词法诊断照旧拒绝。

因为 `$name` 从此恒是错误，这条迁移不会改变任何能编译的程序的含义。它仍按协调方要求**只在本窗口
存在**：v0.78.0 发布、下游用 v0.78.0 的 `dawn fmt` 迁完之后，第一个版本删除它，fmt 恢复「只改空白与
单行首竖线」的承诺。

### 2.4 全仓迁移

- `.dawn`：一次性 Python 脚本（与 fmt 迁移同一算法，但不改其它排版，放 scratchpad 不入库）迁了 44 个
  文件 400 处（site 为主；`selfhost/src` 与 `std` 零处，所以无需重生成 stdsrc）。交叉验证：对其中 36 个
  在 fmt 覆盖范围内的文件，取 `origin/main` 原文跑新 `dawn fmt`，结果与脚本迁移后的文件逐字节相同。
- 文档 ```dawn 代码块：spec、spec.en、tutorial、tutorial.zh-CN、README、README.zh-CN 共 40 处；
  插值一节的散文按新规则改写。
- 迁移后全仓 `$name` 零命中（新编译器编译全部语料即证）。

### 2.5 负控

- 探针 `p_dollar.dawn`：`let a = "A"`、`obj`、`obj_x` 后 `println("$a.b")`、`println("B:$obj_x")`。
  种子 v0.77.0 输出 `A.b` / `B:WRONG`（静默取值）；新编译器报两条错并给出两种改法；
  `dawn fmt` 改成 `"${a}.b"` / `"B:${obj_x}"`，再跑不动。
- grammar corpus：`reject/dollar_name.dawn` 钉两条诊断的顺序与措辞；`accept/dollar_literals.dawn`
  钉 `$5`、`$ `、`$-`、`\$a`、`\${a}`、串尾 `$` 都是字面。

## 3. SYN-N05 / SYN-N11：构造器拼写

### 3.1 语法前后

「记录只用 `{}`，位置构造器只用 `()`」在 Dawn 的读法：和类型构造器按圆括号声明（`Rect(w: Float, h: Float)`），
它就是「位置构造器」一侧，字段带名只意味着圆括号里可以写 `name:` 具名实参（与函数调用同一分派规则）。
声明形状决定使用形状（Rust struct/tuple struct、OCaml inline record、Roc record/tag 同理，见调研报告 §3）。

| | 记录 `type P = { x: Int }` | 和类型构造器 `Rect(w: Float, h: Float)` |
|---|---|---|
| 表达式 | `P { x: 1 }`、`P { ..p, x: 2 }`；`P(1)`/`P(x: 1)`/`P()` 报错（**今天已拒**） | `Rect(1.0, h: 2.0)`；`Rect { w: 1.0, h: 2.0 }` 报错（**新关**） |
| 模式 | `P { x, .. }`；`P(x: a)`/`P(a)` 报错（**新关**） | `Rect(w, ..)`；`Rect { w, .. }` 报错（**新关**） |

新诊断（措辞与今天的记录诊断成对）：
- `constructor \`Rect\` is built with parentheses: Rect(...)`，hint 同今天的 `constructor: Rect(w: Float, h: Float)`；
- 模式位：`record \`P\` is matched with braces: P { ... }` 与 `constructor \`Rect\` is matched with parentheses: Rect(...)`。

裸名规则不变：记录裸名不是值也不是函数；带字段构造器的裸名在函数位是函数值；无字段构造器裸名是值。
无字段构造器写 `None()` 的旧行为不变（不在本裁决内）。

### 3.2 AST 变化

- `ECtor(name, args, spread, has_parens, clo, chi, lo, hi)`（`has_parens` 实义是「有花括号」）拆成两种节点：
  - `ECtor(name, lo, hi)`：裸名头；圆括号形仍是 `EApply(ECtor, args)`（SYN-02 的统一应用节点，不变）；
  - `ERecord(name, fields, spread, nlo, nhi, lo, hi)`：花括号记录字面量。
- `PCtor(name, args, has_rest, has_parens, …)` / `PQual(…, has_parens, …)` 删 `has_parens`，拆出
  `PRecord(name, fields, has_rest, …)` / `PQualRecord(qual, name, …)`：花括号是记录模式，圆括号（或裸名）是构造器模式。
  裸名 `C` 与 `C()` 不再区分：「构造器有字段、模式一个子模式也没给也没写 `..`」统一报
  `constructor \`C\` has N field(s); a bare name does not match it`（hint 照旧：写 `C(..)`）。
- checker 的 `CtorUse` 三值**保留名字，改了来源**：它今天是「正在检查的是哪一种构造器构造」——裸名 `ECtor`、
  `ERecord` 字面量、`EApply` 于裸名头——由调用方按节点种类给出，不再从 AST 的拼写位读出。它必须存在，
  因为有两条规则本来就关于「写的是哪种构造」而不是关于实参：记录用花括号、构造器用圆括号（本节），
  以及裸名是值不是一次构造。删掉它只能把同一个三分拆进三个入口函数、各自复制「解析名字、常量回退、
  未定义构造器提示」那一段（带增量引擎的 read 记账），那是复制不是简化。任务单写「删 CtorUse 三值」，
  这里偏离，理由如上；AST 上记拼写的 `has_parens` 已全部删除，这是裁决真正要的那一半。
- 模式侧同理：`check_ctor_pattern_at` 收一个 `braces: Bool`，由 `PRecord`/`PQualRecord` 与 `PCtor`/`PQual`
  两类节点给出。
- `..base` 的「functional update only works on records」一条随之不可达（花括号用在构造器上先被新诊断拒绝，
  圆括号里没有 `..`），删除。

保留的字段（有语义，不是拼写记号）：
- `Arg.trailing`：尾块/`with` 挂上的实参填**最后一个声明的形参**，不参加「位置实参不能跟在具名之后」规则，
  并决定「最后一个字段已给」的诊断。这是槽位分派语义，fmt 从不读它（fmt 是 token 级的）。
- `ELambda.sugar`：标记 parser 由 `with` 合成的闭包。它决定一族跨闭包诊断的措辞
  （`return`/`break`/赋值/捕获 `var`/handler 状态格跨越 `with` 引入的闭包），作者屏幕上没有那个 lambda，
  说「lambda」会指向不存在的代码。它是来源信息（与 span 同类），不是作者写法的两种拼写之一；
  一个 lambda 只有一种写法，`with` 的余下部分也只有一种写法。fmt 不读它。
  两者都满足裁决里的限定「凡是只为 fmt 保留写法的」之外，故保留。

### 3.3 fmt

fmt 是 token 级的，拿不到「这个名字是记录还是构造器」（跨模块），所以括号种类不能由 fmt 归一；
AST 不再记括号拼写，checker 以节点种类报错并给出改写 hint。全仓迁移用一次性脚本：以新编译器的诊断
span 为准把 `(` `)` 与 `{` `}` 对换（字段简写 `{ x }` ↔ `(x: x)` 按形补全），脚本不入库，迁移结果由
`dawn check` 全绿与 selfhost 测试证明。

### 3.4 负控

- `type P = { x: Int }` 后 `P(x: 1)`（表达式）：旧新都报（已拒）；`match p { P(x: a) -> a }`：旧 ok，新报
  「matched with braces」（先红）。
- `type S = A(v: Int) | B`：`A { v: 1 }` 与 `match s { A { v } -> v, B -> 0 }` 旧 ok、新报错。
- 探针 `P()` 表记录：报错且 hint 用 `{}`。

## 4. SYN-N08：或-模式前导 `|`

### 4.1 语法前后

之前：`pattern = alt { "|" alt }`，`| A | B -> …` 报 `expected a pattern`。
之后：`pattern = [ "|" ] alt { "|" alt }`，与和类型声明（首个 `|` 可省）同一条规则；所有用 pattern 的位置
（match 臂、`let` 模式、`for` 模式、嵌套）都接受。AST 不变（`POr` 照旧，前导 `|` 不留痕）。

### 4.2 fmt

多行或-模式对齐而非阶梯：以 `|` 开头的行，若最内层开括号是花括号（即它站在 match 体的臂位，而不是
`(`/`[` 里的嵌套模式），不再按续行缩进 +1，而与臂同列：

```dawn
match c {
  | A
  | B -> 1
  D
  | E -> 2
}
```

（后一种即 rustfmt 的多行或-模式排法。）圆括号里的嵌套或-模式保持续行缩进。和类型声明不受影响：
它的 `|` 行站在 `=` 的续行上，不在花括号里。

### 4.3 连带：行首 `|` 不再续接按位或

允许臂以 `|` 开头之后，`0 -> x` 换行 `| A -> 2` 有两种读法：`x | A`（按位或续行）或新臂。
裁定：**行首 `|` 属于模式，不续接按位或**。按位或要跨行就把 `|` 留在行尾（lexer 的
`continues_line` 本来就认行尾 `|`）。这与行首 `-` 不续接减法（`parser.lead_op` 不收算术对）同一个理由：
一个符号在行首有两种含义时，行首只给其中一种。实现：`bor_expr` 不再用 `lead1` 跨换行找 `|`。
破坏面：全仓编译即知，迁移时报告实数。

### 4.4 负控

`match c {\n  | A\n  | B -> 1\n  _ -> 0\n}` 旧报 `expected a pattern`，新通过；fmt 对它不动点；
`A\n| B -> 1` 被 fmt 从阶梯改成对齐。

## 5. SPC-19：局部 `fn` 的具名效果

### 5.1 语法前后

之前：局部 `fn` 的行只能空或恰好 `!io`，其它一律报 `local functions cannot declare effect variables`
（对具名标签是错误措辞），并把函数降成 `!io`，外层于是再收一条连带错误。
之后：局部 `fn` 的效果行与**写出来的函数类型**（`fn(...) -> T !Row`）用同一个解析器：`io`、具名标签、
外层签名已绑定的效果变量与关联效果投影都合法。不能**引入**新的效果变量（局部 `fn` 不能声明类型参数，
同理也不能声明效果参数）；行里出现一个外层没有绑定的小写名字，报的是那个解析器对未绑定效果变量的诊断。

### 5.2 实现

局部 `fn` 本来就是「名字在自身体内可见的 lambda」（`lower` 里 `TSLocalFn` → `lift_lambda`），函数值恒带一格
证据包（spec §6.5 实现段）。所以具名行不需要新 ABI：调用点按行建包，体内的效果操作从自己那一格包里读
（`XEvRead`），与 lambda 完全一样。§6.5 「边界」一段「被提升成一个没有证据参数的普通函数」是旧理由，删掉。
`check_local_fn` 改为：行 = `resolve_fn_row(effs)`（写出的函数类型用的那一段），体按这个行检查；
`local_fn_missing_evidence` 与三条 `local_fn_effect*` 诊断随之只剩一种情形：体内用了行里**没写**的标签/变量/投影，
措辞改为「not declared in `g`'s row」，hint 为「add it to `g`'s row: fn g(...) -> T !(…)」。

### 5.3 spec

§6.2 规则表加一行：「局部 `fn` 的效果行与 lambda、写出来的函数类型同规则：可写具名效果与外层已绑定的
效果变量/投影，不引入新的效果变量」。§3.1「局部命名函数」一句同步；§6.5「边界（v1）」的局部函数条删旧理由。

### 5.4 负控

调研原探针：`fn outer() -> Int !Ask = { let f = () => ask() + 1; fn g() -> Int !Ask = ask() + 2; f() + g() }`
旧报两条（declare effect variables + 连带 io），新通过并在 handler 下输出正确值（JVM 与 native 各跑一次）。

## 6. Emit-Change 清单（预计）

| label | 原因 |
|---|---|
| `lex backend-dawn` | 五个词印成 `IDENT` |
| `parse backend-dawn` | AST dump 的构造器节点形变化；旧 `$name` 在旧语料里变成字面文本 |
| `fmt backend-dawn` | fmt 迁移 `$name`；或-模式对齐 |
| `fmt` | 或-模式对齐改变格式化结果 |

其余 label 以实跑为准，逐条补。Core golden 在最终 rebase 后的树上重录，不声明。

## 7. 种子约束下的落地顺序

1. 设计文档（本文）。
2. SYN-N03：只放宽，selfhost 源码不用五个词作标识符。
3. SYN-N04：先改 fmt（加迁移），用**新** fmt 迁全仓（种子也认 `${x}`），再删 lexer 分支。
4. SYN-N05/N11：新 checker 报出三格，全仓迁到规范拼写（种子也认），再提交。
5. SYN-N08：只放宽 + fmt 对齐；selfhost 源码不写前导 `|`（种子不认）。
6. SPC-19：只放宽；selfhost 源码不写局部 `fn` 的具名行。
7. 回填本文状态与里程碑记录。

每步 `scripts/selfhost-fixpoint.sh`（种子→A→B→C，B==C）在最终树上跑一次，种子编 HEAD 即证明新语法未进 `selfhost/src`。

## 8. 不做的（理由）

- **SYN-N07 五种应用拼写不归一**：管道、方法调用、尾块各有语义位置（裁决 2），fmt 本来就不改应用形，本窗口不动。
- **RX-08 `type`/`alias`/`opaque type` 三分维持**：三种形式各一种含义（Go alias/definition、Gleam opaque 同构），只留 hint 文案。
- **fmt 不删单行或-模式的前导 `|`**：和类型声明单行删首竖线是 token 级可判的（`type X =` 后第一个 token）；
  match 臂的前导 `|` 与上一臂体末尾之间没有 token 级可靠边界（臂体可以跨行），删错会改义。前导 `|` 是裁决给的可选形式，保留。
- **fmt 不归一构造器括号**：fmt 是 token 级，不知道名字指向记录还是构造器（可能跨模块）；由 checker 报错给 hint。
- **`None()` 这种无字段构造器加空括号**：不在裁决 2 范围。
- **局部 `fn` 引入新的效果变量**：等于局部多态，要给绑定者列表定 ABI（`effect-params-design.md` 决策 5 的同一个面），裁决只要求具名效果。
- **site 构建期高亮器与 play-ui 的 CodeMirror 词表**：它们是启发式着色器，不是契约；按词着色 `in`/`with` 不影响正确性，本刀不改。
