# 尾块参数 — 设计 — #206（K3 + K4）

> 状态：current —— 已评审通过（用户终裁 2026-08-08，见 §13），**期 1 已落地**
> （`c684819..5d7b094`，落地基线 `497f096`）；期 2 的源码迁移、parser 退役与陈旧示例
> 清理由 `d4cb422`、`fde3203`、`7238851` 落地，实测记录见 §15。期 2 的最终文档口径是：`fn` 不再属于
> 表达式，尾块是唯一 trailing form；§1–§13 保留方案比较、过渡语法与发布刀法的历史证据，
> 其中旧 `fn` 示例不是现行语法。勘察基线
> `main = 50252e8`，行号引用以它为准。上游：#198 UI DSL 勘察（K3/K4 两条）。
> 本文只管**语法**：裸 `{}` 尾块、它与既有四处花括号语法的互不侵犯、尾块怎么绑形参。
> 具名实参与默认值在 [`named-args-design.md`](named-args-design.md)（K5，已落地），
> 与本文的接触面见 §5.3。

---

## 0. 一句话

裸 `{}` 尾块不需要新机制：**parser 里已经有一个「花括号后缀禁用」模式**（`ns` 参数，
`parser.dawn:1249` 起逐级穿线），它今天就在 `if`/`while`/`for`/`match` 头部关掉记录字面量
（`parser.dawn:1701`）。当年否掉裸 `{}` 的那条理由——「与无括号 `if` 头的体无法区分」——
指的正是这个模式要解决的问题，而这个模式在那之后落地了。把 `ns` 从「禁记录字面量」
扩成「禁花括号后缀」是一个 `&&` 的事。

配套实测：**目标语法今天是硬解析错误**（探针 `a_sameline`/`j_with_brace`/`l_matcharm_brace`
三处一致），所以这是纯加法，没有任何现存合法程序会改变含义。

---

## 1. 要推翻的三处既有裁决

按 `CONTRIBUTING.md:40-44`（「不做的（记录理由）」），推翻要给新证据。三处原文：

**`docs/spec.md:628-629`**
```
  **只认 `fn` 拼写的形式**：裸 `{ ... }` 尾闭包（Kotlin 式）永久不做，
  它与无括号 `if`/`while` 头的体无法区分（`if c { ... }`）。
```

**`docs/core-move2-design.md:545`**
```
>   裸 `{}` 尾闭包（Kotlin 式）维持不做——被无括号 `if` 头的解析歧义否决，与破坏容忍无关。
```

**`scripts/grammar-corpus/reject/brace_trailing_lambda.dawn`**（全文）
```
# expect: expected a newline after this statement
# expect: allowed at module top level
# A bare `{ ... }` after a call is not a trailing lambda and never will be:
# it cannot be told apart from the body of a paren-less `if`/`while` header
# (docs/core-move2-design.md §6). Only the `fn`-spelled form attaches.
```

### 1.1 新证据（三条，全部实测）

**E1 — 「无法区分」在 parser 里早已有区分机制，且已经用在同一个位置上。**
`expression` 到 `postfix_expr` 的每一级都带一个 `ns: Bool`（`parser.dawn:1249,1251,1307,
1321,1344,1366,1380,1394,1414,1432,1448,1471,1489,1508,1619,1699`），它在四处被置 `true`：
`while` 条件 `:1194`、`for` 的 from/to `:1219,:1224`、`if` 条件 `:1979`、`match` 被检者 `:2215`。
唯一的消费点是 `ctor_expr`：

```dawn
fn ctor_expr(p: P, st: St, ns: Bool) -> PR[Expr] = {
  let (st1, name) = adv(p, st)
  if at_kind(p, st1, LBRACE) && not ns { return record_lit(p, st1, name) }   # :1701
```

实测（`n_ns_header.dawn` / `o_ns_paren.dawn`）：

```dawn
if p == P { x: 1 } { io.println("eq") }     # 报错：花括号被读成 if 的体
if p == (P { x: 1 }) { io.println("eq") }   # 通过：加括号即恢复
```

**记录字面量与 `if` 头的歧义，与尾块与 `if` 头的歧义，是同一个歧义。** 前者在
2026-07-31 一般后缀调用落地时就用 `ns` 消掉了，后者用同一条线、同一批站点、
同一条「加括号恢复」的出路。当年那条裁决写在这个机制之前。

**E2 — 尾块位与柯里化调用位不共享任何记号，`fn` 当年是为后者存在的。**
`fn` 尾闭包的存在理由写在 `parser.dawn:1579-1588`：

```
      # `f(a)(x) => e`: the arguments were already consumed as a call, which is
      # what a `(` after an expression always is. A bare arrow lambda cannot be
      # a trailing closure for exactly this reason -- `f(a)(x)` is a curried
      # call, and the two readings are indistinguishable until the `=>`
```

这条对 `(` 成立，对 `{` **不成立**：`{` 在后缀位没有第二种读法。裸箭头 lambda 进不了尾位
是因为它以 `(` 开头，而 `(` 已被应用占据；花括号没有这个问题。当年把两件事绑在一起谈了。

**E3 — 目标语法今天是硬错误，改动是纯加法。** 三处一致（探针原文）：

| 位置 | 输入 | 今天 |
|---|---|---|
| 语句位 | `f(1) { io.println("x") }` | `error: expected a newline after this statement`（`a_sameline`）|
| `with` 右侧 | `with x <- use_it(1) { ... }` | 同上（`j_with_brace`）|
| match 臂体 | `1 -> f(2) { ... }` | `error: expected a newline, ',' or '}' after this match arm`（`l_matcharm_brace`）|
| `if` 头换行 | `if true` ⏎ `{ ... }` | `error: expected '{', found '\n'`（`k_if_nextline_brace`）|

最后一行顺带说明：**头部本来就要求花括号与条件同行**，所以在头部禁掉尾块不损失任何
今天能写的东西。

反面对照（今天合法，改后必须仍合法）：语句位独立裸块 `{ io.println(...) }` 单占一行
（`d_stmtblock`，跑通）；`P { x: 1 }` 记录字面量（`e_typeident_sameline`，跑通）；
`adder(3)(4)` 柯里化（`f_curried`，输出 7）。

**结论**：三处裁决可以推翻，理由从「不可区分」降为「当年还没有区分机制」。
落地时三处都要就地改写并写明推翻依据，不是删掉了事。

---

## 2. 文法（产生式级）

在 `docs/grammar.ebnf` 的 `postfix` 家族上改两处、加一条：

```ebnf
postfix_expr    = primary_expr { postfix } ;
postfix         = "?"
                | "!"
                | "." IDENT [ call_args | trailing_lambda | tail_block ]
                | "[" expr "]"
                | call_args
                | trailing_lambda                  (* 期 2 删除 *)
                | tail_block ;

tail_block      = "{" [ block_params "=>" ] block_body "}" ;
block_params    = IDENT
                | "(" [ lambda_params ] ")" ;      (* 方案乙（已裁，§13） *)
block_body      = { stmt NEWLINE } [ expr ] ;      (* 与 block 的内部完全相同 *)
```

EBNF 表达不了的四条**边条件**（写进 spec §4.3，机器在 parser 里）：

- **S1 同行**：`{` 与它前一个记号之间不得有 NEWLINE。
  *代价为零*：后缀循环遇 NEWLINE 只为 `.` 续链（`parser.dawn:1606-1611`），
  换行本来就断后缀链。与 `(` 和 `fn` 是同一条纪律（spec §4.3「跨行的 `(` 不吃」）。
- **S2 禁用模式**：`nb == false` 时 `tail_block` 才是 `postfix` 的候选。
  `nb` 就是今天的 `ns` 改名（见 §3 R2）。
- **S3 前驱不是 `}`**：`{` 的前一个记号若是 `}` 则拒，专有诊断（见 §3 R7）。
- **S4 TYPEIDENT 优先**：`TYPEIDENT "{"` 在 `nb == false` 时由 `ctor_expr` 先吃成
  `record_expr`（`parser.dawn:1701`），所以 `tail_block` 永远落不到裸 TYPEIDENT 上（R3）。

**脱糖**：`tail_block` 与 `trailing_lambda` 落在同一个函数上，
`attach_trailing`（`parser.dawn:2160-2166`）——调用长一个实参、点调用长一个实参、
裸名字变成应用。糖只换拼写不换节点，AST 是同一个 `ELambda`。

---

## 3. R1–R7 逐条裁决

R1–R6 来自 #198 §C，R7 是本文新增。

### R1 同行 — **采纳，原样**

`{` 只有与 callee 的收尾同行才开尾块。见 S1，实现代价为零。

跨行仍是两条语句（`d_stmtblock` 实测跑通，改后必须保持）：

```dawn
let a = f(1)
{ io.println("bare statement block") }   # 独立块语句，不是 f 的实参
```

### R2 头部禁尾块 — **采纳，但改机制**：不是「新开一个禁尾块模式」，是**把既有的 `ns` 扩义**

`ns` 今天的语义是「本表达式内禁记录字面量」，唯一消费点 `parser.dawn:1701`。
改动 = 改名 `ns` → `nb`（no brace suffix），语义扩成「禁一切花括号后缀」，
加第二个消费点（后缀循环的 LBRACE 臂）。**穿线一行不改**，四个 `true` 站点一行不改
（`:1194,:1219,:1224,:1979,:2215`）。

被禁的位置与恢复方式：

| 位置 | 禁 | 恢复 |
|---|---|---|
| `if` / `while` 条件 | 是 | `if (f(x) { ... }) { ... }` |
| `for x in` 的 from / to | 是 | 同上 |
| `match` 被检者 | 是 | 同上 |
| `with x <- ` 的 callee | 是（**新增站点**，见 R6） | 加括号 |
| match 臂的 guard（`if cond ->`） | **否** | — |
| 其余（`let` 初值、实参、臂体、语句位…） | 否 | — |

guard 位判**不禁**：guard 后面跟的是 `->` 不是块，没有「体被吃掉」的读法，
禁了反而多一条要记的规矩。臂体位（C7）同理判**不禁**，`1 -> f(2) { ... }` 合法。

括号内自动恢复是免费的：`call_args`（`:1717`）、`paren_expr`（`:1947`）、
`list_lit`（`:1925`）、下标（`:1524`）全部传 `false`。

Rust 对结构体字面量在 `if` 头走的正是这条；Swift SE-0056 是同一形状的另一半。

### R3 尾块不落 TYPEIDENT callee — **采纳，但它是自动的，不需要写代码**

`Column { text("a") }` 里的 `{` 在 `ctor_expr`（`:1699-1703`）就被 `record_lit` 吃掉了，
根本到不了后缀循环。代价为零，一个记号都不用前瞻——Dawn 的组件函数是 snake_case，
`column { }` 与 `Column { x: 1 }` 天然分家。

**要补的是诊断质量，不是判定。** 今天的报法（`i_recordlit_stmts` 实测）：

```
error: expected `}`, found `(`
  --> 5:24
5 |   let c = Column { text("a") }
```

建议在 `record_lit` 里加一条：字段位读到的名字后面若跟 `(`，说
「`Column` 是类型名，尾块只跟在函数调用后；组件函数用小写名」。这是一刀，可后补。

### R4 裸 `{}` 只做零参 — **驳回原案，改为方案二选一，见 §4**

#198 建议裸 `{}` 只做零参尾块、带参永远写 `fn(x) => { ... }`。
本文认为这条要与「`fn` 全退役」一起裁，单独裁没意义——见 §4，那是本设计唯一的真两难。

### R5 尾块绑最后一个形参 + 豁免顺序规则 — **采纳**，细则见 §5（K4）

### R6 `with` 与尾块不得同调用 — **采纳，且升级为解析期规则**

`with x <- f(a)` 已经在同一落点追加尾闭包（`parser.dawn:2096` 调 `attach_trailing`）。
若 `f(a) { ... }` 也追加一个，一次调用就长两个闭包实参，而作者只看见一个。

裁法：`with_stmt` 解析 callee 时传 `nb = true`（`parser.dawn:2088` 那一行的 `false` 改
`true`），随后若当前记号是 `{`，报专有诊断——
「`with` 已经把块的剩余部分作为最后一个实参交给 `f`；这里的 `{` 会是第二个。
把它包进括号，或者不用 `with`」。

不靠 `want_sep` 兜底：今天的兜底是 `expected a newline after this statement`
（`j_with_brace` 实测），指着后果不指着决定。

`with handle E { ... }` 不受影响：那个 `{` 由 `handle_stmt` 自己 `want`（`:2113`），
不走表达式路径。

### R7 前驱是 `}` 时拒尾块 — **新增，采纳**

没有这条，下面四种写法会静默变成「把块当实参应用到一个块/条件/记录上」：

```dawn
if c { 1 } else { 2 } { 3 }      # 尾块挂到 if 表达式上
match x { ... } { ... }
Point { x: 1 } { ... }
f(a) { ... } { ... }             # 一次调用两个尾块
```

判定是一个记号：`{` 的前驱是 `RBRACE` 就拒。诊断
「尾块只能跟在调用后面；这里的前一个记号是 `}`」。

代价：无。`f { ... }.len()` 不受影响（那是 DOT 臂）；`f(x => { ... }) { ... }` 不受影响
（前驱是 `)`）。附赠「一次调用至多一个尾块」这条规则，不用另写。

### 无括号版 `f { ... }` — **采纳，不列为两难**

判据是**与今天等价**，不是新口味：spec §4.3 白纸黑字写着
「`f fn(x) => e` 就是 `f(x => e)`」，parser 的 `attach_trailing` 第三臂
（`:2165` `other -> EApply(other, ...)`）就是干这个的。裸 `{}` 若不许无括号版，
等于在换拼写的同时砍掉一个既有能力，而且 `column { }`——整个提案的目标形状——就写不出来。

风险面已被 R3 和 S2 关掉：大写名归记录字面量，头部归 `nb`。剩下的
「一个裸名字后面同行跟花括号」今天是解析错误，纯加法。

---

## 4. 唯一的真两难：带参尾块怎么写（`f(a) { x => ... }`）

这条决定 `fn` 是「退到一个位置」还是「从表达式里彻底消失」。**已裁：方案乙**（用户终裁 2026-08-08，§13）。

### 4.1 冲突是什么

`{ x => e }` 今天是合法表达式：一个块，它的值是一个 lambda。
实测 `probe_amb2.dawn:8`：`let f = { (x: Int) => x + 1 }` 编译通过。

但**这个冲突只在尾块位存在，而尾块位今天是解析错误**（E3）。所以两个方案的差别
不是「会不会改坏现存代码」（都不会），而是「`{ x => ... }` 在尾块位读作什么」。

### 4.2 方案甲：裸 `{}` 只做零参，`fn` 退守带参尾闭包位

```dawn
column { text("hi") }                  # 零参：裸花括号
list.map(xs) fn(x) => { x + 1 }        # 带参：仍写 fn
```

- **加分**：零新规则；`{ x => e }` 在任何位置读法一致；fmt 一行不改（§6 实测）；
  语法总量不增；#198 原推荐。
- **减分**：Compose 观感只拿到一半——`items(list) { item -> ... }` 是 Compose 里
  出现频率最高的形状之一，方案甲里它是 `items(list) fn(item) => { ... }`；
  两种尾参数拼写并存，教学时要讲「什么时候写 `fn`」；`fn` 永久留在表达式语法里。

### 4.3 方案乙：带参也进花括号，`fn` 从表达式位彻底消失

```dawn
column { text("hi") }
list.map(xs) { x => x + 1 }
list.fold(xs, 0) { (acc, x) => acc + x }
```

`tail_block` 的头部（`block_params "=>"`）是一条**独立产生式**，不是「块被重新解释」——
如同 `Point { x }` 用花括号但不是块。在尾块位，`{ x => ... }` 里的 `x =>` 是形参表。

- **加分**：`fn` 在表达式里彻底没有位置（spec §4.5 的「写法只有一种」终于字面为真）；
  Compose 观感完整；高亮/TextMate/文档里「`fn` 的第二种含义」整条删掉；
  裁决面变小（不用再解释「哪个位置写 `fn`」）。
- **减分**（逐条量过，全部有数）：
  1. 在尾块位失去「块的值是一个 lambda」这个读法。逃生阀存在且已验证形状：
     `f(a) { (x => e) }`（加括号后 `paren_is_lambda` 返回 false，`:1878-1897`）。
     全仓现存受影响站点：**0**（尾块位今天不存在）。
  2. **fmt 要修一条规则**。实测（`fmt2.dawn`）：
     ```
     let a = list.map(ys) { x =>
           io.println("one")     ← 6 空格
         io.println("two")       ← 4 空格
     }
     ```
     根因：行尾 `=>` 命中 `is_cont_ender`（`fmt.dawn:297`），下一行被当成续行 +1 级，
     再下一行不是续行又退回去。修法与 `unary_minus`/`postfix_bang`
     同型（`fmt.dawn:54+`）：预先算出「块 lambda 头」的 `=>` 记号 `lo` 集合
     （判据 = 最内层未闭合的 opener 是**同一行**开的花括号），从 `is_cont_ender` 里排除。
     **爆炸半径实测为 0**：全仓 366 个跟踪 `.dawn` 文件里
     「开了 `{` 且行尾是 `=>`」的行数 = 0（`rg '\{[^{}]*=>\s*$'`）。handler 臂
     （`op(a) =>` 行尾）不命中，因为它的 `{` 开在上一行。
  3. 前瞻：需要在块首判一次「IDENT + `=>`」或 `paren_is_lambda`。
     两者都已实现且已在 primary 位使用（`:1637`、`:1878`），零新机制。

### 4.4 裁决：方案乙

用户终裁（2026-08-08）采方案乙，判据是「语言里少一条规则比多一条值钱」：方案甲把
`fn` 永久钉在表达式语法里，只为守住一个在该位置没人会写的读法；方案乙的两项成本
（一条 fmt 规则、一个加括号逃生阀）都已量到底，且爆炸半径都是 0。配套追认：
**箭头保持 `=>`**（乙案 = Kotlin 的形状 + Dawn 的箭头，`->` 不添第三义）、
**无隐式 `it`**（单参写 `{ x => }`）、无括号版 `f { }` 与空括号版 `f() { }` 均合法
（tail_block 是普通后缀）。

---

## 5. K4：尾块与形参、具名实参的关系

今天 `probe_tail.dawn` 报 `positional arguments cannot follow named arguments`
（发出点 `checker.dawn:5454`，判定在 `types.dawn:482 ctor_slots`）。
`Column(align: Center) { ... }` 必须合法，否则「具名 + 尾块」这个组合永远写不出来。

### 5.1 规则

- **K4-1 尾块是一个带标记的位置实参**：`Arg` 加一个字段
  （`ast.dawn:123` `pub type Arg = { name: Option[String], e: Expr, lo: Int, hi: Int }`
  加 `trailing: Bool`），`attach_trailing` 造它时置 `true`。
- **K4-2 尾块绑「最后一个声明的形参 / 字段」**，与它前面有没有具名实参无关，
  **豁免**「位置实参不得跟在具名实参后」。
- **K4-3 若那个形参已被填过**（具名或位置），报专有诊断：
  「最后一个形参 `body` 已经给过了；尾块要填的就是它」。
- **K4-4 判定落在 `ctor_slots`**（`types.dawn:482`）：加一个 `trailing: Bool` 参数，
  最后一项若是 trailing 则跳过 `saw_named` 分支、直接取
  `len(fields) - 1`，已填则出 `SlotTaken`。模式侧永远传 `false`（模式里没有尾块），
  所以这个共享函数多一个只有一个调用方用的参数——但共享点保住了
  （`types.dawn:466-481` 的注释说明了为什么这两侧必须共享一份）。
  既有内联测试在 `types.dawn:2105-2122`，扩四条。
- **K4-5 普通函数**今天不收具名实参（`spec.md:633-637`），所以对函数而言尾块就是
  最后一个位置实参，行为不变。K5（具名实参推广到函数 + 形参默认值）落地后
  K4-2 自动统一适用：
  ```dawn
  fn column(align: Align = Start, gap: Int = 0, body: fn() -> Unit !e) -> Unit !Ui !e
  column(gap: 12) { text("hi") }     # body ← 尾块，gap ← 12，align ← 默认
  ```

### 5.2 为什么按「最后一个声明的形参」而不是「最后一个函数型形参」

按类型选会让实参归属依赖类型推断的结果，而尾块的归属在语法阶段就该定；
两个函数型形参时还要再定一条 tie-break。Kotlin 用的就是「最后一个声明的形参」，
Dawn 的构造器字段本来就是有序的，规则可以一句话说完。

### 5.3 与 K5 文档的接触面

只有一条，写进两边：**尾块填最后一个声明的形参；默认值填剩下的洞。**
其余（参数名进不进函数类型、默认值求值时机与纯性）全归 K5。

---

## 6. fmt：唯一性与缩进

fmt 是**记号流重排**，保留作者的物理换行，只改记号间空白
（`fmt.dawn:1-8` 的头注）。所以「尾块要不要换行」不是 fmt 的决定，是作者的；
fmt 的义务只有两条：不得在 callee 与 `{` 之间插入换行（它从不合并/拆分行，天然满足），
以及缩进算对。

**零参尾块：fmt 一行不用改，实测已经对了。** 把目标拼写喂给今天的 `dawn fmt`
（fmt 只需要词法成功，不需要解析成功，所以能测），`fmt1.dawn` 输入是全部顶格的，输出：

```dawn
pub fn main() -> Unit !io = {
  column {
    greeting("world")
    row {
      button("ok")
    }
  }
  column(
    align: Center,
    gap: 12,
  ) {
    text("hi")
  }
}
```

第二遍 diff 为空（幂等）。两条机制各就各位：`space()` 对 `IDENT`/`RPAREN` → `LBRACE`
不抑制空格（`:225-255` 无对应规则），所以出 `column {` 和 `) {`；
`reflow` 的 `body` 判定（`:174` `t.kind == LBRACE && len(openers) == logical_depth`）
认出「这个花括号从本逻辑行开头起没关过任何括号」，把它锚到语句的缩进上，
所以多行实参表收尾的 `) {` 也锚对了。

**带参尾块（方案乙）要修一条**，见 §4.3(2)，爆炸半径实测 0。

**唯一性**：一个尾块的合法排版有两种（单行 `f(a) { x }`、多行），由作者的换行决定，
fmt 不改。这与语言其它地方一致（`if` 的体、记录字面量都是这样），不引入新的
「fmt 会重排我的代码」面。

---

## 7. 互不侵犯的证明

四条，都不需要前瞻，也不需要类型信息。

**7.1 与柯里化调用 `f(a)(b)`。** 后缀循环（`:1510-1615`）按记号类别分派，
应用臂的触发记号是 `LPAREN`（`:1567`），尾块臂是 `LBRACE`。两个记号类不相交，
分派是一次 `kind_of` 比较、无回溯。故 `f(a)(b)`、`f(a) { }`、`f(a)(b) { }`
三者互不影响。**裸箭头 lambda 进不了尾位是因为它以 `(` 开头**（`:1579-1588`），
花括号没有这个性质——这正是 E2。

**7.2 与记录字面量 `P { x: 1 }`。** 见 R3：`TYPEIDENT` 后的 `{` 在 `primary` 阶段
（`ctor_expr`，`:1701`）就被消费，后缀循环看不到它。大小写把两者分在词法层。

**7.3 与 `if`/`while`/`for`/`match` 头部。** 见 R2：`nb == true` 时尾块臂不触发，
与记录字面量在同一位置被同一个开关关掉。且头部本来就要求花括号同行
（`k_if_nextline_brace` 实测），所以禁用不损失可写性。

**7.4 与 `with`。** `with` 从来不走 `fn` 语法：`with_stmt`（`:2074-2097`）与
`handle_stmt`（`:2110-2133`）自己造 `ELambda(..., sugar = true)`，
再调 `attach_trailing`（`:2160`）。**`fn` 尾闭包退役对 `with` 零影响**——
两者共享的是 AST 层的 `attach_trailing`，不是拼写。spec §4.10 的
「落点与尾闭包同一处」说的也是这个落点。
唯一要动的是 R6 那条「同一次调用别装两个闭包」的拒绝。

---

## 8. 破坏面（实数）

### 8.1 `fn` 尾闭包的站点普查

用判别式 `\bfn\s*\([^()]*\)\s*=>`（充要：`fn IDENT(` 是声明，`fn(...) ->` 是函数类型，
`fn(...) =>` 只可能是尾闭包，`grammar.ebnf:134` + `reject/arrow_lambda_fn_prefix.dawn`）。
多行参数表变体 `rg -U` 跑过，0 命中。

| 类别 | 条数 | 位置 |
|---|---|---|
| **可执行调用点** | **14** | `scripts/spike-native/trailing_fn.dawn` 6（21,22,25,31,34,37）；`scripts/grammar-corpus/accept/sugar_forms.dawn` 6（42–46,56）；`accept/arrow_lambda.dawn` 2（46,47）|
| 测试夹具（字符串里） | 8 | `selfhost/src/front/parser_test.dawn` 5（414,417,420,423,495）；`front/fmt.dawn` 2（373,375）；`site/src/hl/dawn.dawn` 1（251）|
| 诊断文案 / 注释 | 11 | `parser.dawn` 6（含**用户可见**的 1587、1673）；`checker.dawn` 2461,6780；`types.dawn` 1673；spike 头注释 3 |
| 文档散文 | 17 | `docs/spec.md` 6、`spec.en.md` 6、`grammar.ebnf` 130-160、audit 4、history 1 |
| 反例夹具（要改写） | 2 | `reject/brace_trailing_lambda.dawn`、`reject/arrow_lambda_trailing.dawn` |

**产品代码站点数：`selfhost/src` 0、`std/` 0、`packages/` 0、`examples/` 0、
`site/` 0（那 1 处是字符串夹具）、backend-dawn `src/` 0。**

`fn` 尾闭包上线于 v0.40.0（`88b9fa7`），至今**没有任何产品代码采用它**。
它只活在为它自己写的语料里。这一条改变了破坏批的性质：迁移量 14，不是几百。

### 8.2 `with` 站点（核实 #198 的说法）

dawn-lang 80 处（`with handle` 43 / `with x <-` 35 / reject 2），
产品代码 16 处且全是 `with x <- bracket(...)`；backend-dawn 0 处。
**全部走 `attach_trailing`，不含 `fn` 拼写，故不受本批影响**（§7.4）。
#198 说的「25 处」偏低，但结论（不受影响）成立。

### 8.3 潜在收益面（不是破坏面）

今天写成普通实参的零参 lambda `(() => ...)`：dawn-lang **152** 处
（`scripts/` 60、`selfhost/src` 52、`std/` 26、`packages/` 10、`examples/` 2；
统计须排除 `.dawn/seeds/std-v0.4x–v0.60.0/` 13 份快照，否则虚高到 389），
backend-dawn `src/` **15** 处。它们今天不写成尾闭包，正是因为尾位强制写 `fn`。
这些站点的迁移是可选的、可后补的、不进破坏批。

### 8.4 会红的门禁

`grammar-corpus`（8 个 accept 站点 + 2 个 reject 用例）、
`spike-native/trailing_fn`、`parser_test.dawn` 5 条、`fmt.dawn` 2 条、
`site/src/hl/dawn.dawn:251`、`doc-check`（spec 与 spec.en 双语摘要）。
backend-dawn 的四份 HTTP 契约 golden 与语法无关，不动。

---

## 9. 种子纪律

机制以 `scripts/emitchange.sh` 为准（`docs/bootstrap.md:44,124` 那句
「裸声明=通配」已过期，#124/`1fc6909` 把它改成硬错误）。
标签是**闭集**，逐字列在 `scripts/emit-labels.txt`，禁 glob，一 label 一行，
写在「上个 tag 到 HEAD」区间的提交信息正文里。

**判据（`docs/audit/error-model-design.md:295-307`）**：改名可一期，改签名要三期。
本批是**改语法**，问「两种拼写能不能在一期内共存」——**能**（parser 同时接受
`fn` 尾闭包与裸尾块，两条独立的后缀臂）。故 **两期两发布两次种子推进**，不是三期。

### 期 1（发布 vN）— 纯加法

parser 接受 `tail_block`；`fn` 尾闭包保持接受；`ns` → `nb` 扩义；R6/R7 诊断；
K4 的 checker 改动；fmt 的块 lambda 头修正（方案乙）。
**`selfhost/src` 与 `std/` 的拼写一处不改**（种子还不认识裸尾块）。

预期声明：

```
Emit-Change(emit selfhost): the parser is part of the compiler.
```

先例 `cddc35a`（v0.42.0 加裸箭头 lambda）只声明了这一条，并在正文里写明
「另外五个 emit 目标逐字节比过、相同」——本批照抄这个留痕格式。

不预期动的（但**必须先跑门禁再写声明**，`CONTRIBUTING.md:81-83` 的坑：
同段里一条声明会替后面同 label 的差异挡灯）：

- `fmt` / `fmt backend-dawn`：fmt 修正的爆炸半径实测 0（§4.3(2)）。
- `parse backend-dawn` / `lex backend-dawn`：期 1 是纯加法，旧写法解析结果不变。
- `lsp`：见 §10。

→ tag、bump `scripts/seed-release.txt`、**补登 `scripts/seed-checksums.txt` 与
`seed-std-checksums.txt`**（这一步历史上漏过两次）。

### 期 2（发布 vN+1）— 删语法

迁移 14 个可执行站点 + 8 个字符串夹具到裸尾块；parser 拒 `fn` 尾闭包并给退役诊断；
`fn` 从表达式位彻底消失（方案乙）或退守带参尾位（方案甲，则本期只删零参形式）。

历史预期声明：`Emit-Change(emit selfhost)`；§15 的实际测量覆盖这项预测，结果为零差异，
因此没有写该声明。

**与先例 `4098b93`（v0.43.0 退役 `fn` lambda 前缀）的关键差别**：那次声明了
`Emit-Change(parse backend-dawn)`，因为跨仓生产语料有 305 处旧写法。
**本批 backend-dawn 的 `fn` 尾闭包站点是 0**（§8.1），所以这条大概率**不需要**。
这是本批比先例便宜的地方，也是唯一必须实测确认的地方——跑
`scripts/selfhost-prev-diff.sh` 看 `parse backend-dawn` 到底动没动，再决定写不写。

→ tag、bump、补登校验和。

### 期外（任意后续发布）

`(() => ...)` 的 167 处可选迁移。AST 恒等，先例 `4098b93` 迁了 ~323 个 lambda
而 emit 未动（Core dump 无位置信息），故预期零声明。分批走，不进破坏批。

---

## 10. LSP / TextMate / 高亮

面很小，逐条：

- **LSP**（`selfhost/src/lsp/{server,lspc,lspq}.dawn`）：补全项由类型与作用域生成
  （`lspc.dawn:439` 那类渲染），**不生成尾闭包片段**，也没有 signature help。
  会动的只有诊断文本，而那被 `grammar-corpus` 与 `checker-corpus` 钉住。
  `Emit-Change(lsp)` 预期不需要，但 `scripts/selfhost-lsp-diff.sh` 要跑一遍确认。
  *可选后补*：形参最后一位是函数型时，补全里给一个 `f(…) { … }` 的片段。不进本批。
- **TextMate**（`editors/vscode/syntaxes/dawn.tmLanguage.json`）：
  `:30` 把 `fn` 列进关键字，`:85` 单独匹配 `fn IDENT` 出定义名。
  期 2 后 `fn` 只剩声明含义，两条规则都仍然正确，**不必改**。
  尾块的花括号不需要新 scope（块的花括号本来就没有）。
- **站点高亮器**（`site/src/hl/dawn.dawn`）：`:250-253` 的测试
  「trailing-closure params are not definition names」钉的正是
  `map(xs) fn(c) => c` 不把 `c` 当定义名。期 2 要改写这条测试；
  方案乙下高亮器还要确认 `{ x =>` 里的 `x` 不被当成定义名（同一条规则的镜像）。

---

## 11. 刀法与 oracle

每刀一个可独立回滚的提交，oracle 写在提交信息里。

### 期 1

| 刀 | 内容 | oracle |
|---|---|---|
| **1-A** | `ns` → `nb` 纯改名 + 注释改写，语义不变 | `scripts/selfhost-fixpoint.sh` + `grammar-corpus` 全绿且**一个字节不变**；`selfhost-core-diff.sh` 期望 `selfhost.sha` 只动 parser 一行 |
| **1-B** | 后缀循环加 `tail_block` 臂（零参形；方案乙则含块参头）+ S1–S4 | 新增 `grammar-corpus/accept/tail_block.dawn`（清单见 §12）；`parser_test.dawn` 加 6 条；`reject/brace_trailing_lambda.dawn` **改写成 accept**，同时新写三条 reject（R6/R7/头部位） |
| **1-C** | R3 记录字面量诊断改善（可选，可延后） | `checker-corpus` 或 `grammar-corpus/reject` 一条新用例 |
| **1-D** | K4：`Arg.trailing` + `ctor_slots` 尾项规则 + K4-3 诊断 | `types.dawn:2105` 的内联测试扩 4 条；`checker-corpus/cases/tail_block_named.{dawn,expected}` |
| **1-E** | fmt 块 lambda 头续行修正（**只在方案乙**） | `fmt.dawn` 内联测试加 2 条；`./bin/dawn fmt std site selfhost packages examples --check` 全绿；`scripts/selfhost-fmt-diff.sh` 期望**零差异**（已实测语料里 0 命中） |
| **1-F** | 文档：spec §4.3/§4.5/§4.10、`grammar.ebnf`、`core-move2-design.md:545` 的裁决就地改写（写明推翻依据 = E1/E2/E3）、`spec.en.md` 同步 | `scripts/doc-check.py`（链接/锚点/示例可跑/译本摘要） |
| **1-G** | `spike-native/tail_block.dawn` + `.expect`：尾块的**语义**（脱糖成最后一个实参、点调用出方法调用、裸名出应用、效果穿透） | `scripts/spike-native/run.sh` 两后端同输出 |

发布前另跑（不在 CI）：`scripts/native-fixpoint.sh`、`scripts/replay-bootstrap.sh`。

### 期 2

| 刀 | 内容 | oracle |
|---|---|---|
| **2-A** | 迁移 14 个可执行站点 + 8 个字符串夹具到裸尾块 | 各自所在门禁（`grammar-corpus`、`spike-native`、`parser_test`、`fmt` 内联、`site/hl` 内联） |
| **2-B** | parser 拒 `fn` 尾闭包，退役诊断；删 `lambda_expr` 的尾位调用（`:1553`、`:1591`）与 `:1587`/`:1673` 的旧文案 | 新 reject 用例钉退役诊断；`grammar-corpus`；`selfhost-prev-diff.sh` **读一眼 `parse backend-dawn` 是否真的没动** |
| **2-C** | 文档删 `fn` 尾闭包全部叙述；`grammar.ebnf` 删 `trailing_lambda` | `doc-check` |

**先跑门禁、再写 Emit-Change 行**——同一 tag 区间内先写的声明会替后面的差异挡灯。

---

## 12. 语料清单

### accept（新增 `scripts/grammar-corpus/accept/tail_block.dawn`）

零参、无括号 callee、点调用、多行实参表收尾、嵌套、单行、`let` 初值位、
match 臂体位、guard 位、管道右侧、`f(a) { }.len()`、括号内恢复
（`if (f(x) { }) { }`）、方案乙则加：单参 `{ x => }`、多参 `{ (a, b) => }`、
带注解 `{ (x: Int) => }`、零参头 `{ () => }`。

### reject（每篇首行起 `# expect:` 钉住诊断序列，多一条少一条都算失败）

| 文件 | 钉住 |
|---|---|
| `tail_block_in_if_header.dawn` | `if f(x) { ... } { ... }` 在头部不开尾块 |
| `tail_block_after_with.dawn` | R6 专有诊断 |
| `tail_block_after_brace.dawn` | R7：前驱是 `}` |
| `tail_block_on_typeident.dawn` | R3：`Column { text("a") }` 的改善诊断（随 1-C） |
| `brace_trailing_lambda.dawn` | **删除**（它钉的正是本批推翻的裁决），内容移入 accept |
| `arrow_lambda_trailing.dawn` | **保留**：`g(xs) (x) => x` 仍拒——`(` 位的歧义没变（E2） |
| 期 2 新增 `fn_trailing_retired.dawn` | `fn` 尾闭包的退役诊断 |

### checker-corpus（`cases/<name>.dawn` + `.expected`，逐条钉 span/文本/hint/顺序）

`tail_block_named.dawn`（K4-2 通过 + K4-3 重复填充报错）、
`tail_block_arity.dawn`（尾块使实参数超出）。

---

## 13. 用户终裁（2026-08-08）与期 1 落地记录

1. **方案乙**：带参数的块也进花括号——`items(list) { item => ... }`；`fn` 从表达式位
   消失（期 2 执行删除，期 1 两拼写共存）。追认见 §4.4。
2. **guard 位不禁尾块**；`if`/`while`/`for`/`match` 头部与 `with` callee 禁（S2/R6）。
3. 期 1 的 `Emit-Change` 实测（2026-08-08，`selfhost-prev-diff` 全量跑过）：
   **只有 `Emit-Change(emit selfhost)` 一行**；其余 emit 目标、backend-dawn 的
   lex/parse/fmt 扫描、run/fmt/lsp 差分与 v0.60.0 逐字节一致（窗口内已声明的
   #207 期差异除外）。期 2 仍须届时实测，不以预测为准。

**期 1 落地**（`c684819..5d7b094`，七刀一一对应 §11 的 1-A…1-G）：
fixpoint 与 native-fixpoint B==C；grammar corpus 12 accept / 26 reject；
checker corpus 99 例（新增 `tail_block_named` / `tail_block_arity`，cerr 覆盖率
257/261）；`spike-native/tail_block` 两后端同输出；全仓 `fmt --check` 零差异
（§4.3(2) 的爆炸半径实测 0 成立）。每条边条件（S1–S4）、R6/R7/R3 与 K4/fmt
修正各配了变异负控：S2 的变异让 std/cursor 都解析不了（`if` 体被吃掉——
当年裁决怕的正是它，开关就是证明），S4 的变异让 std/io 解析不了，其余负控
分别红在对应的 reject/checker/fmt 用例上。
一处实现纪要：fmt 的 `block_arrow` 判「同一行」不能数 NEWLINE 记号——lexer 在每个
续行记号（`{`、`,`、`=>` 自身）后吞掉 NEWLINE（`lexer.continues_line`），
行号须从源文本的码点位置数。

---

## 14. 期 2 的最终语法口径

本节只收现行结论；前十三节继续保存调研、被驳回方案、期 1 过渡态与门禁计划：

1. `fn` 只用于具名函数声明与函数类型，不再有任何表达式位置。
2. 同行追加最后一个实参只写尾块：`f(a) { x => e }`；旧 `f(a) fn(x) => e` 被拒并教迁移。
3. 裸 `f(a) (x) => e` 仍不成立，因为 `(x)` 已被一般后缀解析成第二次应用；这不影响
   以 `{` 开头的尾块。
4. `with` 继续在 AST 层把块剩余部分附成最后一个实参，不依赖任何已退役的 `fn` 拼写。

---

## 15. 期 2 实际落地与实测记录（2026-08-09）

期 2 已落地的三笔源码提交是：

1. `d4cb422`（migration）：把可执行语料与测试夹具从旧 trailing-lambda 拼写迁到尾块。
2. `fde3203`（parser retirement）：拒绝 `fn` trailing closure，给出迁移诊断，并删除退役的
   表达式解析路径。
3. `7238851`（stale-example cleanup）：清理仍把旧拼写当作现行示例的注释与说明。

**Emit-Change 裁决来自测量，不是遗漏**：`scripts/selfhost-prev-diff.sh` 实测
`emit selfhost` 为零差异，其他检查也通过，因此没有写 §9 历史预测的
`Emit-Change(emit selfhost)`。`scripts/selfhost-run-diff.sh` 首次运行时，`bin/dawn`
重建工具链的提示信息进入被比较的 stderr，造成一次瞬态假差异；立即重跑后所有标签通过。

其余已经实际运行的门禁：

- `scripts/selfhost-fmt-diff.sh`：389 files 通过。
- `scripts/selfhost-lsp-diff.sh`：52 messages 通过。
- `./bin/dawn test selfhost`：348 tests 通过。
- `./bin/dawn test site`：82 tests 通过。
- checker corpus：99 cases / 390 diagnostics 通过。
- `python3 scripts/doc-check.py`：79 docs / 70 checked blocks 通过。

退役规则的变异负控也实际见红：临时禁用 postfix 中 `k == FN` 的退役分支后，
`fn_trailing_retired` 的 3 个诊断断言按预期失败；恢复该分支后，grammar corpus
以 12 accept / 27 reject 全部通过。

本记录不声称期 2 的 selfhost fixpoint、native fixpoint 或 native 全量门禁已经通过；
这些门禁在实际运行并留痕前仍属于发布收尾项。
