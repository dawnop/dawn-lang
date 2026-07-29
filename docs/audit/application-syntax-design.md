# 把调用变成真正的后缀运算

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **SYN-02（P1）**，顺带结清 **SYN-03**。
> 状态：**proposed，可做**——与 [`../native-backend-plan.md`](../native-backend-plan.md)
> 不重合（本文只动 parser 与 checker，不动 emit）。反而是**顺风**：
> 把五种调用形式收成一个后缀节点，Core IR 那边的 `LCall` 就少一批要 lower 的源形态。
> 台账见 [native-plan-overlap.md](native-plan-overlap.md)。

## 一、问题

`docs/grammar.ebnf` 把 `call_args` 写成任意 `primary_expr` 的 postfix，
听起来函数是一等值、调用是一般后缀运算。实际不是：

- `selfhost/src/parser.dawn` 的 postfix 循环只处理 `?`、`!`、`[]` 和 `.`；
- 普通调用在 `ident_or_call` 特判——**只有「名字后面跟 `(`」这一种形状**；
- 构造器调用另有一处特判（还是唯一支持 named argument 的地方，这就是 SYN-03）。

实测：

```dawn
make()(1)      # error：第二个 ( 处语法错误
(if c { f } else { g })(1)   # 同样不行
r.handler(x)   # 这个能过，但走的是「字段里存函数值」的另一条路径
```

也就是说：**函数值只有在「名字直接绑定到它」时才能调用**。
条件表达式的结果、字段读取的结果、函数返回值都不能直接应用。

后果不只是写法受限。parser、AST 和 checker 因此同时养着
`ECall`、`EMethod`、`EApply`/动态调用几套路径——复杂度比真正统一的
application 更高，而不是更低。

## 二、复盘

这不是一个被论证过的取舍，`docs/design.md` 里找不到「调用不做成一般后缀」的决策。
它是自底向上长出来的：先有 `f(x)`，再有 `x.f(y)` 的点调用糖，再有构造器的
named argument，再有函数值——每一步都在前一步旁边加一个特判，没有哪一步单独看不合理。

EBNF 写成一般后缀，说明**当初的意图就是一般后缀**，只是实现没走到。

## 三、方案

### 3.1 AST 层：一个 `EApplyPost` 节点

parser 的 postfix 循环加一条：遇到 `(` 就构造

```dawn
EApplyPost(callee: Expr, args: List[Arg], lo: Int, hi: Int)
```

`Arg` 允许 `Positional(Expr)` 与 `Named(name, Expr)`——**语法上一律允许**，
是否合法由 checker 判定（见 3.2）。这一步就把 SYN-03 结清了：
EBNF 说「所有 arg 都可为 `IDENT: expr`」，改完之后这句是**真的**。

`ident_or_call` 与构造器的两处特判**删掉**。`f(x)` 变成
`EApplyPost(EIdent("f"), [...])`，走同一条路。

### 3.2 checker 层：由 callee 的类型决定这是什么调用

`check_apply(callee, args)` 分四种：

| callee 解析成 | 结果 | named argument |
|---|---|---|
| 顶层/局部函数名 | 静态调用 | **拒绝**（今天也不支持，保持） |
| 构造器名 | 构造 | **允许**（今天唯一支持的地方） |
| 表达式，类型是 `fn(..) -> ..` | 动态调用（`XCallDyn`/`XApply`） | 拒绝（函数类型没有参数名） |
| Java 成员 | Java 调用 | 拒绝 |

named argument 的合法性从**语法位置**变成**类型判定**。错误信息因此能说人话：
「`f` 是函数不是构造器，函数调用不支持参数名」——今天是一句语法错误。

### 3.3 与点调用的关系

`r.f(x)` 现在 parse 成 `EApplyPost(EField(r, "f"), [x])`。
checker 里的消歧规则（spec §2.4：作用域内存在同名函数时报歧义，见 SYN-06）
**原样保留**——它现在作用在 `EApplyPost` 的 callee 上，逻辑不变。

UFCS（`x.f(a)` 等价 `f(x, a)`）也不变，同样在 checker 里判。

## 四、语法与冲突分析

### 4.1 `(` 的续行规则

spec §1.7：行尾是开括号时自动续行。改成一般后缀之后，

```dawn
let x = f
(1 + 2)
```

会被读成 `f(1 + 2)` 而不是两条语句——**这是新的歧义**。

**处置**：要求后缀 `(` 与 callee **之间没有换行**。也就是 postfix 循环遇到
「上一个 token 与 `(` 之间跨了行」时不吃它。这与 spec §4.3 对一元 `-` 的处理同源
（`x\n  - y` 不作续行，因为无法判定），是同一条纪律的延伸。

Rust、Swift、Kotlin 都有等价规则，不是新发明。

### 4.2 元组字面量

`(1, 2)` 是元组。`f(1, 2)` 是调用。区分靠「前面有没有 callee」，
postfix 循环天然做到——这一条不产生新冲突，因为今天 `f(1,2)` 已经这么解析了。

### 4.3 `!` 与 `?` 的相对位置

`f()!` 与 `f!()` 现在都能 parse（后者是「解包 `f` 再调用」）。语义清楚，
不需要额外规则。

## 五、为什么不顺手把 X 也改了

- **不动 SYN-05**（`!` 同时表达效果和解包）。那是可读性，与本文无关，
  且在 codebase-audit.md 里已驳回。
- **不给函数类型加参数名**（从而支持函数值的 named argument）。
  那会让 `fn(Int) -> Int` 和 `fn(x: Int) -> Int` 变成两个类型还是一个类型，
  是类型系统的问题，范围完全不同。
- **不做偏应用/柯里化**。`f(1)(2)` 在本文之后**能 parse**，但语义仍然是
  「`f(1)` 的结果必须是函数」。自动柯里化是另一门语言。

## 六、不做的（记录理由）

- **只改 EBNF 不改实现**（审查给的第二个选项：「在规范里明确承认这是受限的一等函数
  并删掉错误的 EBNF」）。EBNF 已经在 2026-07-25 标成 historical，短期止血完成。
  但长期选这条等于承认「函数是一等值」这句话有星号——而那句话是 README 的卖点之一。
  真正的问题不是文档说错了，是实现少做了一步。
- **保留 `ident_or_call` 作为快路径**。「名字后面跟 `(`」是 99% 的情况，
  留着特判能省一次类型判定。不留：两条路径就是两套要同步的语义，
  这正是今天 `ECall`/`EMethod`/`EApply` 并存的成因。
- **顺手统一 `EMethod`**。点调用的消歧规则（SYN-06）比调用本身复杂，
  且它在 checker 里是对的。本文只统一「怎么应用」，不动「点后面那个名字是什么」。

## 七、落地点

| 文件 | 改什么 |
|---|---|
| `selfhost/src/parser.dawn` | postfix 循环加 `(`；删 `ident_or_call` 与构造器的调用特判；跨行 `(` 不吃 |
| `selfhost/src/ast.dawn` | `EApplyPost` + `Arg` 求和类型 |
| `selfhost/src/checker.dawn` | `check_apply` 四分支；named argument 从语法判定改为类型判定 |
| `selfhost/src/astdump.dawn` | AST dump 形状变化 |
| `docs/spec.md` §4.3 | 后缀表里 `()` 的说明；跨行 `(` 的规则 |
| `docs/grammar.ebnf` | 这条修完，EBNF 的 `call_args`/`arg` 产生式**第一次变成真的** |

**验收**：`make()(1)`、`(if c { f } else { g })(1)`、`get_handler()(req)` 都能编译并运行。

**输出变化**：AST dump 形状变了 → `selfhost-prev-diff.sh` 会红，需要 `Emit-Change:`。
错误信息也会变（语法错误变成类型错误），同样要声明。

**破坏性**：语法是**放宽**不是收窄，现有代码全部继续编译。但 AST dump 与错误文案
属工具链输出，按仓库纪律要声明。
