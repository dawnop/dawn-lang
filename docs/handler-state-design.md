# handler 局部状态

> 状态：current。2026-08-29 由用户立项（裁决记在
> [tea-block-children-design.md](tea-block-children-design.md) §8 问题二），
> 同日五条待裁全部裁完，本文自此是这个项目的权威说明。
> **裁的是候选二（handler 域 `var`）加一条强制逃逸禁令**，候选一关档；
> 逐条裁决与理由在 §8，支撑它的三路跨语言勘察在 §10。
> **语言侧 2026-08-29 落地，看护件 2026-08-30 落地**，落地记录挂在 §7.3、§7.4、§7.8
> 三节的末尾。两半实施勘察同日回来：拼写终裁落定（§8 问题二）、三处旧勘察被实测推翻
> （§2.1、§4.3、§4.5 各带一条补注）、动刀前那条 evidence 逃逸疑点已结案
> （§7.6：没有第二出口，前置条件解除）。落刀前只剩 §7.7 一条三选一的取舍。
> 勘察基线 `main = ae3cd59`，文中 file:line 均对该提交，编译器为 v0.69.0。
> 代码块都不标 `dawn run` / `dawn compile`，`doc-check.py` 不编译它们；
> 哪些形状是真在这个编译器上问过的，逐条记在 §9。
>
> **期权记录。** 本档只做尾恢复。若将来放开多次 `resume`，格子的表示要从「handler
> 帧上的一个槽位」升级为「随续延捕获一起复制」（Effekt ICFP 2025 那条路，§10.2）。
> 候选二不堵这条路；这句话是留给那天的。

## 1. 这份文档回答什么

一个 handler 的臂如何在两次操作调用之间存住东西。

**两个客户，互不相干。**

第一个是 lexer 的诊断收集。[effects-design.md](effects-design.md) §7 开放问题 1
在 2026-08-02 就量到了它：helper 发诊断、驱动循环收进 `var diags`，改写成
`effect Report` 之后臂里的 `diags = diags ++ [d]` 被拒，没有变通，于是 lexer 维持
元组捎带不改写。那份判词末尾把环闭上了：「第一个真实客户到来之前，先要 handler 局部状态」。

第二个是视图 DSL 的子节点收集。[tea-block-children-design.md](tea-block-children-design.md)
§3.1 把同一堵墙在 v0.69.0 上重问了一遍（效果语义此后翻过一次），答案没变，而且量出
它是**三条错误**而不是一条：臂不能赋值外层 `var`、臂不能捕获 `var`、块剩余也不能读 `var`。
收集和交回两头都堵死。

两个客户共同的形状：**一个效果的多次调用之间需要一个共享的可写格子，而尾恢复档里没有延续，
所以格子不能藏在延续里**。

**立项裁决（2026-08-29）**：立项，立成效果系统自己的项目，两个客户并列，UI 不是唯一理由。
设计文档动笔前先做实现侧勘察（已做，结论在 §2）。

**与问题三的边界。** 同日裁决把「参数化效果 `effect Emit[T]`」与「效果变量上装 handler」
**缓裁**，待本文把 handler 状态的形状定下来之后再做实现侧比价。所以本文只回答
「臂怎么攒东西」，不回答「效果怎么带类型参数」。这条边界有一个实际后果：UI 客户在问题三
落地之前，那一套 `emit` / `el` / `text` 词汇只能住在应用模块里，不能住进
`packages/tea-dom`（[tea-block-children-design.md](tea-block-children-design.md) §3.2、§3.3）。
本文不因此改变优先级：DSL 词汇住哪儿是包结构问题，能不能写出来是语言问题。

本文也不重开尾恢复档。`resume` 与多次恢复是效果设计
（[effects-design.md](effects-design.md) §1）明确不做的东西，与 native 的 Perceus 单栈模型
正面冲突。本文的两个候选都在「臂就地返回」的前提下工作。

## 2. 今天的形状

### 2.1 handler 的实现链

`with handle` 没有自己的 tast 节点，也没有自己的 Core 节点。它是检查器里的一次改写，
`check_handle`（`selfhost/src/check/checker.dawn:5141-5276`）：

1. 每个声明的操作恰好一臂，臂按操作声明的函数类型 `check_lambda` 成一个普通闭包
   （`checker.dawn:5215-5240`）。
2. 臂被检查完之后，在**绑 `E` 自己的证据之前**，把臂们要用的证据打成一个包 `arm_env`
   （`checker.dawn:5246-5251`）。注释就写在那儿：「an arm does not answer itself」。
3. 造一条记录 `ev$E`：每个操作一个字段装它的臂闭包，最后追加一个 `env` 字段装 `arm_env`
   （`XCtor(eid, 0, arm_nodes ++ [arm_env], ...)`，`checker.dawn:5253-5254`）。
   记录的形状由 `pass_effects` 在声明效果时合成，`env` 字段在
   `selfhost/src/check/passes.dawn:1236` 追加。
4. 块的剩余部分当成一个闭包检查，然后就地调用它，实参是这一层算出来的证据包
   （`checker.dawn:5263-5274`）。
5. 块记的行是「剩余的行减去 `E`，并上各臂的行」（`eff_minus`，`checker.dawn:5272`；
   规则条文在 [spec.md](spec.md) §6.5）。

操作调用同样没有节点：它是一次字段读加一次动态调用
（`checker.dawn:6566-6583`）。字段下标是操作在效果里的序号，交给臂的证据是**记录自己的
`env` 字段**，不是这一次 raise 所在帧的环境。这一句是「臂不答自己」的实现。

于是四条事实，本文后面反复用到：

- 臂是普通的被提升的 lambda，零捕获，一个擦除类型的证据形参。
- 证据永远不进捕获表。检查器在 `resolve_local` 里就不让它进
  （`checker.dawn:4840-4842`），lowering 再兜一道，捕获表里出现证据类型直接 panic
  （`selfhost/src/ir/lower.dawn:429-447`）。
- 一次 `with handle` = 一条记录。嵌套安装是两条记录，内层遮蔽外层（探针 P3）。
- 一个臂发出它自己应答的那个效果，答它的是**外层** handler（探针 P4；
  同一条已由 `scripts/spike-native/effect_lexical.dawn` 的 `inner_ten` 钉住）。

> **勘误（2026-08-29，实施勘察）：第一条里的「零捕获」是偶然，不是结构事实。** 上面那句
> 留着是它当初的判断。实测臂可以捕获外层的 `let`：`ask() => k + 1` 捕获函数体里的
> `let k`，编译通过且答案正确。零捕获只是今天那几个臂恰好没有捕获对象。
> 这对候选二是好消息：格子可以走现成的按值捕获路径进臂的捕获表，`ev$E` 的形状一个字不用动。
> §4.4、§4.5 两条补注里关于「格子怎么被臂够到」的说法按这一条为准。

### 2.2 三条禁令是一条机制

§1 引的那三条错误看起来是三处规则，实测是同一段代码。

`resolve_local` 从内往外走 lambda 栈，对每个被穿过的帧问一次
（`checker.dawn:4831-4851`）：写就报「不能跨闭包赋值」，读到 `var` 就报「按值捕获拒 `var`」，
读到证据就**默默放行且不记捕获**，其余的记进捕获表。三个分支，一段 `if`。

诊断文案的差别（说「`with handle` 臂」还是说「`with` 引入的闭包」）由 `LambdaCx.arm`
这个 Bool 决定，而那个字段的注释明写它只为诊断存在
（`selfhost/src/check/cx.dawn:229-242`）。臂和块剩余在这段代码眼里是同一种东西。

这对本文是好消息：**要放开的不是三条规则，是一段 `if` 里的一个分支**。§4 的候选二正是
在这里加第三种「默默放行并改写」的名字，而证据那一支就是现成的先例。

### 2.3 D.0：定价发现

尾恢复档里没有延续。臂就地返回，返回值就是操作的结果。所以在两次 raise 之间，
**唯一还活着并且两次都够得着的对象，是这一次安装造出来的那条 `ev$E` 记录**。
别的什么都不共享：臂零捕获，证据不进捕获表，块剩余是另一个闭包。

要让第一次 raise 写的东西被第二次 raise 读到，就需要一个可变的格子。

**而 Dawn 今天没有任何可观察的可变堆对象。**

- 数组不是存储，是值。`array_with` 返回新数组，
  `selfhost/src/check/types.dawn:3032-3036` 的注释写死了这一点：
  「Values, not storage: every operation returns a new array and none of them
  is observably destructive」。
- Core 没有字段写节点。
- JVM 后端的 ADT 字段是 `ACC_FINAL`（`selfhost/src/jvm/codegen.dawn:651`）。
- 用户模块借不到 `Array` 这个名字（`is_std_module` 门控）。

唯一编得过的可变累积器是穿过 Java 引用去改一个 Java 对象，而它答不了这个问题的三条理由
已经逐条记在 [tea-block-children-design.md](tea-block-children-design.md) §3.1：装不下 ADT、
是 `!io`、只在 JVM 上存在。

**所以任何 handler 状态设计都要先买同一件东西：一个格子原语。** 这是本文最重要的勘察结论，
也是两个候选共享的地基。最省的形状是一格 box 加三个运行时 intrinsic：

```
cell_new(x: T) -> Cell[T]
cell_get(c: Cell[T]) -> T
cell_set(c: Cell[T], x: T) -> Unit
```

体例照 `ev_get` / `ev_append`：它们是 `lower.internal_intrinsics()` 里的名字
（`selfhost/src/ir/lower.dawn:1003-1007`），用户拼不出来，因此**不进
`types.builtins()`，也不进 `selfhost/builtins.dawn` 的镜像**，builtin 声明镜像那道门禁
够不着它们。落点是每个后端一份实现加 comptime 解释器一份，实测清单在 §7.1。

> **落地更正（2026-08-29，原语已入 main，提交 `3c2c506`）。** 三处与上文不同，按实况为准：
>
> - **是四个不是三个。** 多的一个是 `cell_take(c: Cell[T]) -> T`：转移出槽内引用、槽置空，
>   调用者义务随后覆写。理由是唯一性：`cell_get` 交出借用、emitter 补 dup，累积器经它读出来
>   引用计数恒为 2，pvec 的就地复用从 100% 掉到 0%（实测 573/573 对 0/573）；收集器赋值
>   必须走 take，先例是 `dawn_array_steal`。
> - **comptime 解释器不是「一份实现」，是四行具名拒绝。** `with handle` 在 comptime 本就被拒，
>   格子不可达；四个名字进 `comptime_rejects()`，分区测试逐个探针验证拒绝真的发生。
> - **「镜像门禁够不着」只对一半。** 签名镜像确实不含它们，但 `builtin-decl-contract` 的 dump
>   显式遍历 `internal_intrinsics()` 按名点名，`selfhost/builtins.dawn` 的名字计数注释也跟着改。
>
> 另一条给后续 mutant 语料的实测教训：负控探针的槽里不能放字符串字面量，字面量是不朽静态，
> 漏放与双放都空转，探针必须在 set 与 take 两点都持堆值。

**格子不必是 `ev$E` 的字段。** 它可以在造记录之前先造出来，臂按值捕获它。捕获的是一个
不可变的引用，指向一个可变的对象；按值捕获这条纪律一个字都不用改。这一点用 Java 对象
在今天的编译器上直接验过（探针 P5：`let` 绑一个 `AtomicLong`，三次 raise 各读各写，
区域之后读出 6），也验过嵌套安装各攒各的（探针 P6，答 882）。

把格子留在记录外面还有一个好处：`ev$E` 的形状是 `pass_effects` 按效果声明合成的，
一个效果一条；而格子是**每次安装**一个。两者的生命周期本来就不同，硬塞进记录会把
「效果有几个状态」和「装了几次」搅在一起。

## 3. 候选一：参数化 handler

> **2026-08-29：候选一关档。** 本节三小节留着是勘察记录，不再是备选。理由在 §8 问题一，
> 先例在 §10.1（Koka 自己删了它）、§10.5（Eff 的 resource 是同一形制，2015 年整体删除）、
> §10.7（纯 state-passing 在只有尾恢复的系统里不可表达，所以这条路只剩那个退化形）。
> §3.3 的触点清单里格子那几行、§3.4 的无环论证，翻案之后都还被候选二借用。

### 3.1 形状

Koka 的路子。安装点带一个初值，每个臂多收一个状态形参、多还一个状态，另有一个
`return` 臂把「剩余的返回值」和「最终状态」合成这次 `with handle` 的值。

```dawn
with handle Emit([]) {
  emit(n, st) => ((), st ++ [n])
  return(x, st) => st
}
```

臂的类型从操作声明的 `fn(P...) -> R` 变成 `fn(P..., S) -> (R, S)`；`return` 臂的类型是
`fn(Rem, S) -> V`，`Rem` 是块剩余的返回类型，`V` 是整个 `with handle` 区域的值类型。

底下是 §2.3 的格子：安装点求值初值、`cell_new`，臂被合成的外壳包一层，读 `cell_get`、
调用作者写的臂、把返回的第二个分量 `cell_set` 回去、把第一个分量当操作的结果返回。
格子不可拼写，作者碰不到它。

### 3.2 两个客户

UI 收集器：

```dawn
effect Emit {
  fn emit(n: Node) -> Unit
}

fn collect(body: fn() -> Unit !Emit) -> List[Node] = {
  with handle Emit([]) {
    emit(n, st) => ((), st ++ [n])
    return(_x, st) => st
  }
  body()
}
```

lexer 诊断收集：

```dawn
effect Report {
  fn report(d: Diag) -> Unit
}

fn lex_all(src: String) -> (List[Token], List[Diag]) = {
  with handle Report([]) {
    report(d, st) => ((), st ++ [d])
    return(toks, st) => (toks, st)
  }
  lex_loop(src)
}
```

lexer 这一份把交回表面用满了：它要的不是状态本身，是「剩余的值」和「状态」的元组，
`return` 臂正是拼这个的地方。UI 那一份则把剩余的值丢掉（`_x` 是 `Unit`）。
两个客户各要一半，这是 `return` 臂存在的理由。

### 3.3 触点清单

| 位置 | 动什么 |
|---|---|
| `selfhost/src/front/parser.dawn:2577-2598` | `with handle E(init)` 的安装实参；`handler_arm` 多认一种臂头（多一个形参）与 `return(x, st) => e` 这第四种臂形 |
| `selfhost/src/check/checker.dawn:5141-5276` | 初值求值与类型化、臂签名由 `fn(P...) -> R` 合成为 `fn(P..., S) -> (R, S)`、`return` 臂的类型化、区域值类型从「剩余的返回类型」改成 `return` 臂的返回类型 |
| `selfhost/src/check/checker.dawn:5215-5240` | 臂个数/元数诊断随之改口径（今天说「takes N parameter(s)」，多出来的那个状态位要说清是谁加的） |
| `selfhost/src/check/passes.dawn:1136-1266` | `ev$E` 记录形状：字段类型跟着臂类型走 |
| `selfhost/src/check/types.dawn` | 三个 cell intrinsic 的声明 |
| `selfhost/src/ir/lower.dawn:1003-1007` | 归类进 `internal_intrinsics()`（分区测试在同文件） |
| `selfhost/src/jvm/emit.dawn`、`selfhost/src/c/emitc.dawn` | 每个后端一份 cell 实现 |
| `selfhost/src/ir/interp.dawn` | comptime 解释器一份 |
| `runtime/c/dawn_rt.c` | 格子的 C 实现与所有权注释 |
| `selfhost/src/check/tast.dawn` | 若 `return` 臂需要独立的 tast 形状 |

`resolve_local`（`checker.dawn:4831-4851`）**不动**：候选一没有新的可写名字，状态是
形参和返回值，走的是普通的作用域。

### 3.4 无环论证

`Cell` 这个类型作者拼不出来，格子这个值作者也拿不到：安装点写的是初值，臂写的是
`(结果, 新状态)`，编译器合成的外壳负责 `cell_get` / `cell_set`。于是

- 没有闭包能捕获格子，因为没有名字指向它；
- 格子里能装的只有臂返回的第二个分量，那是一个普通的 Dawn 值。

要成环，需要「格子里的值能够到格子」。第一条断掉了这条路。所以**候选一不引入任何新的
可构造的引用环**，native 的 RC 零漏不变量不受影响。

注意这不是「状态里不能放函数值」。状态里放函数值是合法的（`S` 是任意类型），环之所以
构造不出来，是因为那个函数值无论捕获了什么，都捕获不到格子。

### 3.5 两个待裁语义点

**交回表面。** 今天 `with handle` 这个语句对块的值没有贡献：区域的值就是剩余部分的值
（`checker.dawn:5273-5275`）。加了 `return` 臂之后，区域的值改由 `return` 臂算。
这是一次语义扩展而不是修补，要明说三件事：

- `return` 臂可不可以省略。省略时的默认是 `return(x, _st) => x`（退化回今天的形状），
  还是「有初值就必须有 `return` 臂」。本文倾向后者：默认值会让「状态被悄悄丢掉」编得过。
- 不带初值的 `with handle E { ... }` 是否继续合法。必须继续合法，否则今天所有的
  handler 都要改写；两种形态在语法上由有没有 `(` 区分。
- `return` 臂里能不能发效果。臂们的行已经并进区域的行（§2.1 第 5 条），`return` 臂
  按同一条处理即可，不是新规则。

**`?` 与最终状态。** [spec.md](spec.md) §6.5 写着 `?` 透明穿过 `with handle` 区域。
探针 P7 把这句话的后果量了出来：`?` 在剩余部分里触发时，区域之后的那一行不再执行，
攒到一半的状态原地丢掉（打印 `state before ?: 3`，函数返回 `None`）。

候选一把这个洞变得更显眼：`return` 臂是作者写的、看起来一定会跑的一段代码，而 `?`
会跳过它。三种口径：

1. `?` 照旧透明，`return` 臂不跑，状态丢掉。与今天一致，代价是 `return` 臂骗人。
2. `?` 穿过时也跑 `return` 臂，结果丢掉。语义可疑：`return` 臂的返回类型是 `V`，
   而 `?` 要交出去的是 `Err`/`None`，两者对不上。
3. 区域内禁止 `?`。太重，`with` 糖的纪律里 `?` 是明确放行的那一个。

本文倾向口径 1，并把「`return` 臂在 `?` 逃逸时不执行」写进 spec 的 §6.5，而不是留给读者猜。
这是一次裁决，不是细节。

## 4. 候选二：handler 域 var

### 4.1 形状

在 handler 的花括号里声明一个 `var`，臂读它写它，块剩余在区域之后也读得到它。

```dawn
with handle Emit {
  var acc: List[Node] = []
  emit(n) => { acc = acc ++ [n] }
}
```

臂的类型不变，安装点不带实参，没有 `return` 臂。交回靠作用域：`acc` 在
`with handle` 之后的块剩余里可见。

底下还是 §2.3 的格子。`acc` 这个名字被绑成一个格子；`resolve_local` 在穿过闭包边界
时把对它的读改写成 `cell_get`、写改写成 `cell_set`，臂和块剩余都按这条改写。

> **拼写终裁（2026-08-29）：就是上面这一种，格子写在 handler 花括号内、臂之前。**
> 问二本来还并录了一种「`var` 声明在 `with handle` 之前、邻接安装点」的 Effekt 形，
> 前半实施勘察之后否掉了，理由与三条附带规定都在 §8 问题二。
> 一个容易误读的地方先说清：`var` 与赋值语句在 Dawn 里**不是新东西**
> （[spec.md](spec.md) §4.1，函数体局部，赋值是语句）。新的只是 `var`
> 出现在 handler 花括号里这个**位置**。

### 4.2 两个客户

UI 收集器：

```dawn
fn collect(body: fn() -> Unit !Emit) -> List[Node] = {
  with handle Emit {
    var acc: List[Node] = []
    emit(n) => { acc = acc ++ [n] }
  }
  body()
  acc
}
```

lexer 诊断收集：

```dawn
fn lex_all(src: String) -> (List[Token], List[Diag]) = {
  with handle Report {
    var diags: List[Diag] = []
    report(d) => { diags = diags ++ [d] }
  }
  let toks = lex_loop(src)
  (toks, diags)
}
```

两份都比候选一短，而且**逐字就是 §1 那两个客户当初写出来被拒的那段代码**，只是
`var` 的声明位置从函数体挪进了 handler 的花括号。这是候选二最强的一点：它把三条错误
消息里的两条直接变成合法，第三条（块剩余读不到）由作用域规则解决。

### 4.3 触点清单

| 位置 | 动什么 |
|---|---|
| `selfhost/src/front/parser.dawn:2598` | `handler_arm` 多认一种「`var` 声明」臂形 |
| `selfhost/src/check/checker.dawn:5141-5276` | 在检查臂之前先绑这些名字；作用域延伸到块剩余 |
| `selfhost/src/check/checker.dawn:4831-4851` | **第三种分支**：穿过闭包边界读写这类名字时改写成 cell intrinsic，不记捕获 |
| `selfhost/src/check/cx.dawn:229-242` | `LambdaCx` 可能需要知道自己是不是这个 handler 的臂 |
| `selfhost/src/ir/lower.dawn:429-447` | 证据不进捕获表那道 panic 的邻居：格子进不进捕获表要有定论 |
| `selfhost/src/check/types.dawn`、`lower.dawn:1003-1007`、两个后端、`interp.dawn`、`runtime/c/dawn_rt.c` | 同 §3.3 的格子那几行 |

`passes.dawn` 的 `ev$E` 形状**不动**：臂类型没变。这是候选二比候选一少动的一处。

> **勘误（2026-08-29，实施勘察）：上表两头都估错了，方向相反。** 表留着是它当初的估计。
>
> - **低估了 AST。** 真正的成本在 `EHandle` 加一个 `cells` 字段，这是一次 arity 变更，
>   牵动约 8 处匹配。上表一行都没给它。
> - **高估了 parser 与 fmt。** parser 只需在臂循环里加一个 `VAR` 分支；`handler_arm`
>   今天要求首 token 是 IDENT，`var` 又已经是保留字，所以槽位干净、零歧义。
>   fmt **零改动**：它是 token 流重排版器，不 parse，实测新语法已经格式化正确。
>
> `ev$E` 形状不动这一条仍然成立，而且比原文以为的更稳：§2.1 的勘误说明臂本来就能捕获
> `let`，格子走现成的捕获路径就行，不必为它改记录。

### 4.4 环风险

这是候选二要付的价，而且它是本文里唯一一处「引入语言从未有过的东西」。

```dawn
with handle Tick {
  var s: fn() -> Int = () => 0
  tick() => { s = () => s() + 1 }
}
```

`s = () => s() + 1` 里的那个 lambda 读了 `s`，所以它捕获格子；而格子随即装上了这个
lambda。格子 → 闭包 → 格子，**这是 Dawn 里第一个可构造的引用环**。

今天它构造不出来，而且拦住它的正是候选二要拆的那堵墙（探针 P8：同样一行在函数体里写，
答 `lambdas cannot capture var bindings`）。

后果落在 native。Perceus 是精确引用计数，没有环收集器；一个环就是一次泄漏，
而 `runtime/c/dawn_rt.c` 那一线的姿态是 LSan 全量启用、出口零漏
（[perceus-design.md](perceus-design.md)）。所以候选二要么

- 限制状态类型（例如禁止函数类型与含函数字段的类型进 handler 域 `var`），这条限制要
  沿着类型传递地判，代价不小且会挡住合法用法；
- 或者接受「这是 Dawn 的第一类 RC 泄漏」，并写清它在文档里的位置、在
  rc-contract 里加一条明知会漏的负控；
- 或者只在格子写入时做一次「新值是否可达该格子」的运行时检查，那是把环收集的成本
  搬到写路径上。

三条都不好看。本文倾向候选一的主要理由就是这一条：候选一的无环论证是结构性的（§3.4），
不需要限制、不需要豁免、不需要运行时检查。

> **本节已被翻案（2026-08-29）**，上面那段留着是它当初的判断，不是现状。问一裁的是候选二
> **加一条强制逃逸禁令**：格子只准被这次安装的臂与块剩余读写，读写落到 cell intrinsic 上；
> 除此之外任何闭包捕获格子都是编译错误，格子本体也不能作为值传出 handler 的词法域。
> （禁令的准确表述见 §4.5 的第二条勘误：格子**进**臂与余部闭包的捕获表，进不了别人的。）
>
> 环因此构造不出来。`s = () => s() + 1` 要成环，第一步是那个内层 lambda 捉住格子，
> 而它既不是臂也不是块剩余，这一步直接报错。于是本节列的三条出路一条都不用走：
> 不限制状态类型、不给 native 开第一个 RC 泄漏豁免、不在写路径上加可达性检查。
> 末句「本文倾向候选一的主要理由就是这一条」随之作废。裁决与理由在 §8 问题一。
>
> 禁令不是本仓发明的。三门语言都在挡同一件事，只是手段不同：Koka 让 `var` 逃出词法域成为
> 类型错误，Effekt 用 region 与捕获集合，Eff 因为挡不住而把整个机制删掉（§10.9）。

### 4.5 纯度声明与 evidence 第三臂先例

`cell_get` / `cell_set` 必须被声明为**纯**，否则候选二答不了 UI 客户：
`trait App` 的 `fn view(m: M) -> M.View` 没有行位（`packages/tea-core/src/app.dawn:52`），
收集器一旦带上任何行，impl 的 `view` 就编不过。

这个声明是可以辩护的。格子不可拼写、不被捕获出区域、生命周期被安装点的动态范围夹住，
所以「一次安装内部的读写」在区域之外不可观察；对区域外的调用者，`collect` 是一个纯函数，
同样的输入给同样的输出。这正是效果系统对 `unsafe_pure`
（[spec.md](spec.md) §6.4）接受的那种论证。

但它**是这门语言的第二个 `unsafe_pure` 形状的声明**，而第一个是明确圈在 std 里、
要作者具名担保的逃生门。这次的担保人是编译器自己，范围更宽。要立项就得把担保写成
条文而不是注释：格子不可拼写、格子不进捕获表（`lower.dawn:429-447` 的邻居）、
格子不随任何值离开区域。三条缺一条，纯度声明就是假的。

候选一不欠这一笔，理由是同一条：它的臂签名里没有格子，纯度问题只落在合成的外壳上，
而外壳是编译器写的。

> **勘误（2026-08-29）：「第二个 `unsafe_pure` 形状的声称」这句要收窄。** 上面那段留着是
> 它当初的判断。问五裁的是格子走 `internal_intrinsics()`，`Cell[T]` 与格子本体用户都拼不出来；
> 问一又加了逃逸禁令。于是要担保的不再是「一类用户可写的可变格子是纯的」，而是
> 「编译器自己合成的、用户够不着的那三次读写是纯的」，与 `ev_get` / `ev_append` 同一档，
> 而不是与 std 里那个具名逃生门同一档。
>
> 本节要求写成条文的三条一条都不减：翻案之后它们不再是「纯度声明的附加条件」，
> 它们就是禁令本身，缺一条禁令和纯性一起垮。裁决在 §8 问题一与问题五。
>
> **勘误（2026-08-29，实施勘察）：三条里的「格子不进捕获表」是写错了。** 正确的表述是
> **「格子只进这次安装的臂与余部闭包的捕获表，其余闭包捕获它就是编译错误」**。
> 差别不是措辞：臂本来就能捕获 `let`（§2.1 的勘误），格子正是靠这条现成的路被臂够到的，
> 真要一格都不进捕获表反而得另造机制。
>
> 顺带堵一个看起来很顺手的实现捷径：**`LambdaCx.sugar` 不能当许可证**。
> `with x <- f()` 的余部闭包也是 sugar，但它是被当作实参交给用户函数的，用户可以把它存起来；
> 拿 `sugar` 当「这是编译器造的、可以放行」的判据，逃逸禁令当场开一个洞。
> 判据必须是「这个闭包是不是本次安装的臂或余部」，不是「它是不是糖」。

**先例。** `resolve_local` 加第三种分支这件事本身不新。证据那一支
（`checker.dawn:4840-4842`）做的就是「穿过闭包边界时，这个名字不按捕获处理，
按别的方式解决」。候选二要加的分支形状与它同款，只是解决方式从「读自己的包」
变成「读写一个格子」。这条先例降低了实现风险，但降不了 §4.4 的语义风险。

## 5. 候选三：库级 State（不是独立候选）

把状态做成一个普通的效果，用库拼出来：

```dawn
effect State[S] {
  fn get() -> S
  fn put(s: S) -> Unit
}
```

这条路要两件语言能力，两件都在 2026-08-29 被**缓裁**
（[tea-block-children-design.md](tea-block-children-design.md) §8 问题三）：

- `effect State[S]` 要参数化效果，也就是把 `Ty` 塞进 `Eff`
  （[effects-design.md](effects-design.md) §7 开放问题 5 把它判为另一根轴）；
- 用它写收集器还要「在效果变量上装 handler」，否则 `collect` 拼不出自己要 handle 的
  那个具体效果。

而且即使这两件都有了，`State` 的 handler 自己还是要在 `get` 与 `put` 之间存住 `s`。
换句话说**它不是本文问题的替代方案，它是本文答案的一个消费者**。

所以候选三不是第三个候选，是下游。记录在此，等问题三裁完再回来看它值不值得进 std
（[effects-design.md](effects-design.md) §2 的「std 效果件维持都不」那条裁决今天仍然成立）。

## 6. 语义细则

以下六条对两个候选统一回答，除非分列。

**6.1 状态类型的来源。** 候选二写在 `var` 的声明上，与函数体里的 `var` 同款，可以要求
必须显式标注（handler 的花括号里没有上下文可推）。候选一的初值在安装点，类型从初值推，
但 `[]` 这种空字面量推不出元素类型，所以要么允许安装点标注
（`with handle Emit([]: List[Node])`），要么要求从 `return` 臂或臂的状态形参反推。
本文倾向：**候选一要求臂的状态形参可被标注**，与 lambda 形参同一条规则，不给安装点加语法。

**6.2 重入。** 勘察里最省事的一条：**一个臂够不着自己这次安装**。臂拿到的证据是安装点
之前那一层的环境（`checker.dawn:5246-5251`），所以臂里发同一个效果，答它的是外层 handler
（探针 P4 答 `outer 10`，不是死循环）。这条不是本文引入的，是 V1′ 调用点语义的既有形状，
`effect_lexical` 已经钉住。

后果：`读格子 → 调用 → 写格子` 这个经典的丢更新形状，**在这一档里构造不出来**，因为中间
那次调用无论怎么绕都回不到同一个格子。于是重入的裁决可以很轻：

> 一次安装的格子只被这次安装的臂访问；臂内发出的同名效果由外层 handler 应答，
> 与格子无关。嵌套安装各有各的格子（探针 P6）。

要留意的是这条依赖「臂的环境是安装点之前那一层」。哪天这条变了，重入语义要重裁。
本文建议把这条依赖写进 spec §6.5 的条文里，而不是只留在 `checker.dawn` 的注释里。

**6.3 臂内 panic。** panic 不是 `catch_fault` 接得住的东西（探针 P9：臂在写完格子之后
panic，程序打印 panic 串并以 1 退出，`catch_fault` 的 `Err` 分支没有跑到）。所以
「臂在读和写之间 panic，状态停在半路」这个状态在进程内不可观察。裁决可以是一句话：
**臂内 panic 终止程序，格子的中间状态没有观察者**。若将来 panic 变成可恢复的，这条要重开。

**6.4 嵌套遮蔽。** 同一效果重复 `handle` 是内层遮蔽外层，合法，今天就是这样
（探针 P3：`outer=1 inner=2 after=1`）。两个候选都不改这条，改动只是「每层各带一个格子」。

**6.5 块的行不变。** `with handle` 的类型规则（[spec.md](spec.md) §6.5：
`(base ∪ ⋃base_i, (L ∖ {E}) ∪ ⋃L_i)`）不能因为加了状态而变。探针 P10 钉的是今天的基线：
装了 handler 的 `collect` 自己是纯的，`Emit` 不出现在它的签名里。加状态之后这一条必须
逐字成立，否则 §4.5 的 `view` 那道墙立刻回来。

**6.6 `?` 与最终状态。** 见 §3.5 的第二个待裁点（已裁：口径一，§8 问题三）。
候选二受同一条影响，只是症状轻些：
`?` 逃逸时块剩余里那行读 `acc` 的代码本来就不会执行，没有「看起来一定会跑的 `return` 臂」
在骗人。这是候选二的一处小优势。

## 7. 实施与看护

### 7.1 格子 intrinsic 的落点

照 `ev_get` / `ev_append` 的体例，一个不可拼写的内部原语要在这些地方各露一次面
（清单从今天的 `ev_get` 逐文件读出来）：

| 文件 | 露什么 |
|---|---|
| `selfhost/src/check/types.dawn` | 签名 |
| `selfhost/src/ir/lower.dawn` | 归类进 `internal_intrinsics()`（`:1003-1007`）；同文件的分区测试保证「加了却没分类」会红 |
| `selfhost/src/jvm/emit.dawn` | JVM 的 arm |
| `selfhost/src/c/emitc.dawn` | C 的 arm |
| `selfhost/src/ir/interp.dawn` | comptime 解释器的 arm |
| `selfhost/src/jvm/rtclasses.dawn`、`selfhost/src/embed/rtsrc.dawn` | 运行时源的登记 |
| `runtime/c/dawn_rt.c` | C 实现 |

**不进 `selfhost/builtins.dawn`。** builtin 声明镜像那道门禁对着的是
`types.builtins()`，`ev_get` / `ev_append` 都不在里面（实测：`grep -c 'ev_' selfhost/builtins.dawn`
答 0）。格子若跟随 ev 的形态做成内部原语，镜像门禁够不着它；若反过来做成用户可拼写的
`Cell[T]`，就必须进镜像，而那同时意味着放弃 §3.4 的无环论证。**这两件事是同一个选择的两面**。

**intrinsic-parity 会看着。** `scripts/intrinsic-parity.py` 逐名核对两个后端的 arm 集合，
双向都查（声明了没 arm、有 arm 没声明）。少写一个后端不会等到用户编译才炸。

**RC 契约照 `dawn_rt.c:1453-1460` 的体例。** `dawn_ev_append` 的头上写着一段
`OWNERSHIP.` 注释，逐句交代哪个参数是借的、结果是谁拥有的、每条被结果够到的引用各由谁记账。
格子的三个函数各欠一段同款：`cell_new` 的实参是被拿走还是被 dup、`cell_get` 交出去的是
借用还是 owned、`cell_set` 要放掉旧值。这三句话写错任何一句都是漏或者双放，
而 rc-contract 与 native-diff 是唯二会说话的地方。

### 7.2 种子时序

两个候选都要新语法，所以自举纪律（[bootstrap.md](bootstrap.md) 的「特性纪律」那条，
`docs/bootstrap.md:86`）适用：`selfhost/src` 与它的编译 closure 只准用**当前种子已支持**的
特性。落地顺序是：selfhost 实现 → 发 release → 推进种子三文件 → 下一轮 selfhost 才能自用。

但 `packages/` 与 `examples/` 用的是树内编译器，不受这条限制。于是排期是分开的：

1. **本代**：语言侧落地；UI 客户（`packages/tea-dom` 的消费者，也就是
   `examples/projects/tea_dom_*`）立刻改写。它是第一个验证者，而且它的验收 oracle
   已经现成（§7.3）。
2. **隔一代**：发 release、推进种子之后，lexer 客户迁移。
   [effects-design.md](effects-design.md) §7 那条「lexer 维持现状的元组捎带，不改写」
   的判词到那时才可以撤销。

这个顺序还有一个附带好处：UI 客户先跑一遍，等 lexer 迁移时，形状已经在真实代码里
待过一代了。

### 7.3 直驱契约腿

2026-08-29 的问题五裁决：`scripts/wasm-dom-contract` 的两份转录逐字节不变是**必要条件
而非充分条件**，路线一施工时另加一条直驱收集器的契约腿，照 `keyed-ops.sh` 先例。
那条腿的三个判词照抄：

- **嵌套容器各收各的**：内层 `collect` 的产物不混进外层。今天用 Java 格子已经预演过
  这条形状（探针 P6，答 882：外层攒到 1，吞下内层的 78，再攒 2）。
- **emit 顺序即子节点顺序**：臂被调用的次序与 `kids` 列表的次序逐位相同。
- **条件臂为假时不发射**：块里的 `if` 没有 `else` 时，假分支一个子节点都不产生。

三条都不依赖 DOM，可以在纯 `tea_core` 的值上判，所以这条腿不必进 wasm 那条慢道。

**落地记录（2026-08-30）：这条腿仍然欠着，但第一个判词已有语言侧的家。**
`scripts/spike-native/effect_handler_state.dawn` 的 `nested` 一线就是「嵌套容器各收各的」
在纯语言层的形状：内层安装自攒自的、只把一个数交回外层，外层吞下那个数而吞不到内层的零件。
另外两个判词（emit 顺序即子节点顺序、条件臂为假不发射）是 DSL 那一侧的，本档没有替身，
路线一施工时照原样加。

### 7.4 effect-evidence-contract 登记

`scripts/effect-evidence-contract/roster.txt` 是双向棘轮：列了却不在的会红，
`scripts/spike-native/effect_*.dawn` 没列的也会红。handler 状态落地要新增至少一个语料，
按 roster 的两条车道之一登记（`assertions` 或 `transcript`），并在 roster 的
「What each entry owns」清单里加一行说它拥有什么。

语料本身照该目录的纪律写：每条线自己装 handler、各用互不相同的质数当标记，
每个 case 都要**读过格子**才算数（只安装不读，格子坏了也是绿的）。至少四条：
攒三次读一次、嵌套两层、臂发同名效果落到外层、`?` 从剩余里逃逸后的状态口径（§3.5）。

**落地记录（2026-08-30）：已登记，五条线而不是四条。**
语料是 `scripts/spike-native/effect_handler_state.dawn`，roster 里走 `transcript` 车道，
「What each entry owns」清单里有对应段落。第五条线（累加器长到越过 pvec 尾部并进入 trie
第二层）是 §7.8 那条 take 改写唯一能被量出来的地方，理由写在 §7.8 的落地记录里。

`arm_raises` 那条线的写法与原计划有一处出入，值得记下来，因为它是实测才知道的：
**外层格子在同一个块里再装一次 handler 之后就读不到了**。格子的许可是逐帧判的
（`resolve_local`），而嵌套 `with handle` 的块剩余是那一次安装的帧，不是外层那次的，
于是块尾读外层格子会撞上「cannot cross the closure `with` introduced」。
比 §8 问题二那句「只有这次安装的臂与块剩余能读写它」窄一档。语料改成让被调函数自己装第二个
handler，两个格子各自在自己的剩余里被读，形状不变而两条许可都成立。
这一档是紧是宽本档不裁，只把它记在这里。

### 7.5 门禁清单

从 `scripts/gate-map/gatemap.py` 逐路径问出来的，按候选分列。**两个候选共有**（格子部分）：

| 动的文件 | 会说话的门 |
|---|---|
| `selfhost/src/check/types.dawn` | Core IR golden、builtin 类型清单（2 片）、builtin 声明镜像、intrinsic parity、Inflate、export surface（3 片）、prev-diff、selfhost tests、formatting |
| `selfhost/src/ir/lower.dawn` | Core IR golden、intrinsic parity、display layering、classfile Never mutants、java member dispatch、list element、export surface、prev-diff |
| `selfhost/src/jvm/emit.dawn`、`selfhost/src/c/emitc.dawn` | Core IR golden、intrinsic parity、prev-diff、native-diff |
| `runtime/c/dawn_rt.c` | **RC 契约、RC 参数模式变异体**、Array 契约、Map reuse、atomic write、native-diff、prev-diff-native（两条）、wasm-target（三条）、site dist JVM vs native |
| `selfhost/src/ir/interp.dawn` | Core IR golden、prev-diff、selfhost tests |

**候选一另加**（它改语法与臂类型）：

| 动的文件 | 会说话的门 |
|---|---|
| `selfhost/src/front/parser.dawn` | **grammar corpus**、**syntax mutants（3 片）**、list element、pipe contract（2 片）、lsp use-path、Core IR golden、prev-diff |
| `selfhost/src/check/checker.dawn` | Core IR golden、checker 诊断语料、effect evidence contract、export surface（3 片）、java narrowing、opaque twin、builtin type（2 片）、syntax mutants、classfile verify、intrinsic parity、prev-diff |
| `selfhost/src/check/passes.dawn` | checker 诊断语料、LSP workspace、run/test transcript vs N-1、example main contracts、syntax mutants（3 片）、Core IR golden、prev-diff |
| `selfhost/src/check/tast.dawn` | Core IR golden、prev-diff、selfhost tests |

**候选二另加**：parser（同上，语法面更小：只多一种臂形）、`checker.dawn`（同上）、
`cx.dawn`，外加 §4.4 要求的 rc-contract 新负控。`passes.dawn` 不动。

两个候选都会动 `docs/`，`scripts/doc-check.py` 的 links / anchors / sections / status /
count / index 六项都盯着。spec.md §6.5 的条文要跟着改，改完 `spec.en.md` 的译本
digest 会由 transl 检查逼着同步。

裁决落定之后这张表还要按 §4.3 的勘误调一次：`tast.dawn` 那一行是候选二**也**要动的
（`EHandle` 加 `cells` 字段），而 parser 那一行的面比表里估的小。

### 7.6 那条疑点已结案：evidence 没有第二出口

`checker.dawn:5210-5213` 的注释说证据会被「charged to any closure this handler's evidence
ends up inside」（引 [effects-soundness-design.md](effects-soundness-design.md) §4.2），
而 `resolve_local`（`checker.dawn:4840-4842`）说证据**永不进捕获表**。两句话字面上是张力，
今天没人对齐过它们。

这对逃逸禁令是有后果的，不是学术问题：候选二的臂闭包捕获了格子，而臂闭包住在 `ev$E` 里。
若证据另有一条逃逸路径（哪怕只是「证据被算进某个闭包的账」这一种说法成立），
那么禁令就有第二个出口要堵，而 §4.4 的无环论证是挂在「出口只有一个」上的。

以上是疑点当初的陈述，留着是为了看清问的是什么。后半勘察查完了。

**结论（2026-08-29，后半勘察）：没有第二出口，动刀的前置条件解除。** 三段实测，
探针都在 v0.69.0 上跑。

**机制。** 函数值的运行期元数 = 形参加上恰好一个证据槽（`types.fn_arity`，
`types.dawn:270-274`），而那一格是 lowering 在**调用点**填的隐藏参数
（`fn_value_evs`，`lower.dawn:403-406`）。证据是传进去的，不是捕获来的。

**判决性探针 P-E3。** 在区域里造一个发效果的闭包，让它逃出区域，再在外面调用：
应答它的是**调用点**那一层的 handler。内层答 41、外层答 900，实测得 901 而不是 42。
创建点的证据不随闭包走，「证据被算进某个闭包的账」这种说法就此证伪。

**三道锁，从名字到符号到兜底。** `ev$E` 这个绑定只在 `push_scope` 与 `pop_scope` 之间可名
（`checker.dawn:5259`、`:5269`）；`resolve_local` 对 `ev_of` 符号放行且不记捕获
（`checker.dawn:4836-4842`，按符号属性判而不是按名字猜，所以是精确的）；
lowering 再做一道名义兜底（`refuse_evidence_captures`，`lower.dawn:440-447`）。

**那句注释是过期引用，不是缺陷。** `checker.dawn:5210-5212` 引的
[effects-soundness-design.md](effects-soundness-design.md) §4.2（闭包创建点结算）
已被 V1′ 翻转，那份文档自己的头也已经 declare 成 historical。今天对应的真机制是另一件事：
臂的行经 `record_effect` 记进外层帧（`checker.dawn:5237`）。这句注释列进刀内的顺手改写项
（改引 [spec.md](spec.md) §6.5），它是文档债，不是漏洞。

于是 §4.4 的无环论证挂着的那个前提成立：出口只有一个，就是格子本身被捕获，而禁令正堵在那里。

**一条实测警示：普通 `let` 今天可以随闭包逃出区域。** 探针 P-E4-A：区域内
`let captured = ask() * 10`，一个闭包捕获它并逃出区域，在区域外调用得 411。合法，今天就这样。
这正是格子若被当普通捕获处理时的危险形状：值跑出去了，handler 帧却已经没了。
许可证判据恰好把它对格子关死：`resolve_local` 的第四分支要求**被穿过的每一个** lambda 帧
都属于这次安装，逃出去的那个闭包不属于，捕获格子当场是编译错误；`let` 版不受影响。
两个方向都要进 checker 诊断语料：`let` 版必须保持合法（P-E4-A 是这一条的负控锚点），
cell 版必须被拒。少了前一半，禁令就可能悄悄把普通捕获也一起收紧，而没人会发现。

顺带确认 §4.3 那句「`passes.dawn` 不动」在这条路线下成立：格子走臂与余部闭包的捕获表，
不骑 `ev$E`。

### 7.7 lowering 那道兜底守卫：已裁 (c)，不兜底

格子的 Core 类型已定为独立的 `TyVar("cell", 0)`，**不复用 `erased_ev_ty`**：复用会让
lowering 那道兜底守卫对格子失明，格子顶着证据的皮就混过去了。

剩下的取舍是那道守卫要多精确，三选一：

- **(a) 结构匹配**：按 `TyVar("cell")` 扫捕获表，对臂与余部闭包的合法捕获放行。
  代价是 lowering 得知道哪些被提升的 lambda 是臂，今天它不知道。
- **(b) 名义精确**：保留负 id。代价是一旦进 `prelude_adts` 就会被 `desc_of` 当成类，
  与 JVM 的 ACC_FINAL 类生成冲突，必须把它排除在显式类表之外。
- **(c) 不兜底**：只靠 checker 的许可证。最省，但 §7.6 那三道锁在格子这一侧就少一道。

**裁决（刀 C，2026-08-29）：(c)。** 两条理由，第二条是主的。

**(a) 的载体不便宜，勘察实测。** 许可标记今天没有任何现成字段可搭：`tast.XLambda` 有
`params / pnames / body / captures / lo / hi / ty` 七个字段，没有一个说得出「本 lambda 是臂
或余部」——`sugar` 与 `arm` 只活在检查期的 `cx.LambdaCx` 里，不进 tast。要让标记流到
`lower.lift_lambda`，得给 `XLambda` 加第八个字段，改 tast.dawn 加 8 处构造/匹配点，
其中 3 处在 `lsp/lspq.dawn`、1 处在 `ir/interp.dawn`——也就是把这一刀的爆炸半径从
checker 扩到 LSP 与 comptime 解释器两组门禁上。lowering 侧倒是不缺信息的另一半：
`LSt.syms` 就是检查器的 `types.Sym` 表，`cell_of` 在那儿看得见；缺的只有「这个被提升的
闭包属于谁」。

**真正的判据是：证据需要第二道网，是因为它没有第一道。** `refuse_evidence_captures`
存在的理由写在它自己的注释里——「what this catches is the checker having stopped doing
so」。证据不可拼写，于是**没有任何 Dawn 程序能构造出那个回归**，语料够不着它，只有一句
内部断言能说话。格子反过来：它可拼写，回归当场就是一个用户程序的行为变化，
`scripts/checker-corpus/cases/handler_cells_escape.dawn` 的那组 golden 诊断就是那道网，
而 `handler_cells.dawn`（零诊断）钉住反方向。许可证判据被负控证明过会红
（把判据换成 `lc.sugar`，`through_with_sugar` 当场转绿而语料转红）。

附带一条：真回归了也不是内存不安全。格子是堆上的一格，native 侧进 RC，
逃出去的闭包拿到的是一个仍被计数的对象；后果是「语义错」而不是「悬垂」。
语义错正是 golden 语料看得见的那一类。

(a) 若日后重开，重开的触发条件应当是「格子变得不可拼写」或「XLambda 因别的理由已经加了
臂标记」，而不是再算一遍这笔账。

### 7.8 `cell_take` 什么时候能用（刀 C 定，比原判词窄）

`cell_take` 存在的理由是复用：经 `cell_get` 读出的累积器 rc 恒为 2，pvec 就地复用
100%→0%。但 take 会**清空槽位**，从那一刻到赋值的 `cell_set` 之间槽是空的，
于是「这段窗口里还有谁能读到这个格子」是唯一要回答的问题。

原判词只有一条「RHS 里对同一格子的读恰好一次」。落刀时实测出它不够，补成三条
（判据与反例都写在 `checker.cell_take_ok` 的注释里，逐条有语料或探针）：

1. **赋值必须在本次安装的臂里。** 在块余部不安全：RHS 可以 raise `E`，而 `E` 正是这次
   安装应答的，于是臂会在窗口里跑起来读同一个格子。臂里同样的 raise 落到外层 handler
   （§6.2），本次安装的臂跑不起来。母案（累积臂）正好在臂里，所以这条不花钱。
2. **RHS 里对该格子的出现恰好一次**，且**写也算一次出现**——嵌套一个对同一格子的赋值，
   等于在一个它不知道的窗口里写。
3. **不能在 lambda 或循环下面。** 循环体跑不止一次，「写了一次读」不等于「读了一次」：
   `for i in 0..2 { r = r ++ acc }` 第二圈就读到空槽。

三条各有一个负控实测（把该条去掉，程序当场 NPE 于 `std/pvec`）：去掉 1 → 块余部里
`acc = acc ++ [emitting()]` 崩；去掉 2 → `acc = f(acc, acc)` 崩；全去掉 → 循环那条崩。
合法侧由 `handler_cells.dawn` 的 `double_read` / `looped` 两个用例钉住。

计数走 AST（`cell_occurrences`，对 `ast.Expr` **穷尽 match、无通配臂**）：漏数一种表达式
形态就是把两次读当成一次，而多数一次只赔掉复用。被遮蔽的同名 `let` 也算一次出现，
同样是往安全那边偏。

**落地记录（2026-08-30）：复用是量出来的，不是论出来的。**
`scripts/effect-evidence-contract/README.md` 的 mutant N 把 `cell_take_ok` 改成恒假
（每次读都降成 `cell_get`），重建之后全树没有一处变红，因为丢掉一次 take 不是错答案。
只有 `DAWN_RC_STATS=1` 说得出话：同一份语料，干净的一遍是 `array_with in-place 29,
copied 0`，变异之后是 `in-place 0, copied 29`，两万元素那一档是 573/0 对 0/573。
100% 就地复用塌到 0%，与本节开头那句预测逐字相符。

代价是语料长度：一千元素以下 pvec 一个 trie 节点都不会被改写，两个计数器都是零，
丢了 take 和留着 take 长得一模一样。`long_tail` 因此是两千元素而不是四十。

同一份 README 的 mutant M 钉的是另一半：C 后端 `cell_get` 那一臂的 `dup_expr` 包裹删掉，
借来的引用被当成拥有的交出去，spike-native 的 asan 腿立刻报 heap-use-after-free。
两条都是手打、实测、恢复的文档化变异体，理由是它们都在编译器侧，自动化一条要重建一次
`bin/dawn`。

RC 那三句所有权话另有一条自动化看护：`scripts/rc-contract` 加了三条断言
（`cell_set_releases_the_old_value` / `cell_take_empties_and_transfers` /
`cell_get_does_not_transfer`），外加 production mutant `cell-set-forgets-the-old-value`，
它把 `dawn_cell_set` 里的 `dawn_drop(old)` 删掉。红集只有一条，就是它 own 的那条；
另外两条在 `matrix.txt` 里被登记成 `control`，即「这个 mutant 只是丢了一次释放，
不是把原语改坏了」。

**CI 墙钟账。** rc-contract 那一步本地从 8.7s 到 9.1s，加倍进位后 `contracts` job 的
计划值 440s 变 441s，3 倍刚好越过 22 分钟，故 `timeout-minutes` 22 改 23，离 660s 的
run-pole 还很远，整轮墙钟不动。spike-native 全量本地 230.75s 变 231.54s（四路并行，
一条 6s 的语料被调度空隙吃掉了），557s 那条 runner 观测值没被推动，budget 不重述。
effect-evidence 在 `test` job 里从 23.8s 到 25.3s，同一个 job 的预算里毫发无损。

## 8. 裁决

每条先给本文当初的倾向与最强的反对意见，末行是用户 2026-08-29 的裁决。
倾向与反对都按原样留着：五条里有两条最后没按倾向走，留着才看得出为什么。
支撑裁决的跨语言证据在 §10。

**问题一：候选一（参数化 handler）还是候选二（handler 域 var）。**

- 本文倾向：**候选一**。两条依据。其一，§3.4 的无环论证是结构性的：格子不可拼写因此
  不可捕获，因此环不可构造，不需要类型限制、不需要豁免、不需要运行时检查。其二，
  native 的零漏不变量（LSan 全量、出口零漏）今天是一条硬不变量，候选二要么给它开第一个洞，
  要么为了不开洞而引入一条沿类型传递的限制。用一次拼写噪音换一条不变量，本文认为划算。
- 最强反对：候选一的 `(r, st')` 是拼写噪音。UI 客户那一行 `emit(n, st) => ((), st ++ [n])`
  里，`()` 和那对括号都是给编译器看的，作者要说的只有 `st ++ [n]`；而候选二的
  `emit(n) => { acc = acc ++ [n] }` 逐字就是作者脑子里的那句话，而且**它就是两个客户当初
  自然写出来的那段代码**。加上 `return` 臂是一整个新语法面（第四种臂形、新的区域值来源、
  §3.5 那三个要裁的口径），而候选二的语法增量只有一行 `var` 声明。反驳这条要说清
  「第一个引用环」到底有多贵，而那个价钱本文只定了性没定量。
- **裁决（2026-08-29）：候选二**，带一条**强制逃逸禁令**：格子被闭包捕获是编译错误，
  格子本体不能作为值传出 handler 的词法域；只有这次安装的臂与块剩余能读写它，
  且这两处由检查器改写成 cell intrinsic，不进捕获表。理由是本文倾向候选一的两条依据
  在跨语言勘察之后都不再成立。其一，§4.4 的引用环在禁令下构造不出来，成环的第一步
  （闭包捉住格子）本身就是编译错误，所以候选二不再欠 native 一个 RC 泄漏豁免。
  其二，候选一在尾恢复档里只剩一个退化形（§10.7 证明纯 state-passing 编码在没有非尾恢复的
  系统里不可表达），而那个退化形逐字等于 Eff 的 resource，原作者 2015 年把它整体删了；
  Koka 也已把参数化 handler 从语法里删掉，今天官方惯用的就是候选二的形状（§10.1、§10.5）。
  另有一笔本文没记的税：多操作效果里根本不碰状态的臂，也要陪着写 `(回值, 新状态)` 元组。

**问题二：交回表面。**

- 本文倾向：候选一走 `return` 臂，且**不给默认**（没有 `return` 臂就不许带初值），
  理由是默认会让「状态被悄悄丢掉」编得过。候选二走作用域延伸（handler 花括号里的
  `var` 在块剩余里可见）。
- 最强反对：作用域延伸这件事，候选二做起来比听上去怪。`with handle` 的花括号在今天是
  一个封闭的臂表，里面的东西一个都不往外看；让其中一种绑定往外看，读者要记住哪种往外
  哪种不往外。候选一的 `return` 臂虽然是新语法，但它把交回明写成一行代码，没有隐式作用域。
- **裁决（2026-08-29）：改判，本问退化为拼写细节。** 它原来问的是交回表面选哪种机制，
  而问一裁了候选二之后交回一定走作用域，剩下的只是格子的声明写在哪个花括号里。
  当时并录了两种拼法：**Koka 形**（`var` 在 handler 的词法域内，由 `return` 臂把终态
  交出来，§10.1 的 `pstate`）与 **Effekt 形**（`var` 声明在 `with handle` 邻接的外层，
  区域之后直接读，没有 value case，§10.2）。
- **拼写终裁（2026-08-29，前半实施勘察之后）：格子写在 handler 花括号内第一行**，
  也就是 §4.1 那个形状：

  ```dawn
  with handle Emit {
    var acc: List[Int] = []
    emit(n) => { acc = acc ++ [n] }
  }
  body()
  acc
  ```

  **Effekt 的邻接形被否**，理由是归属判不出来：`var` 写在 `with handle` 之前，编译器没有
  办法说清哪个 `var` 属于这个 handler，放行等于把整个「可变捕获」特性面一起放开，而那不是
  本文要买的东西。花括号内形三条都占：归属可判定（格子属于这一次安装）、逃逸禁令有挂点、
  语法增量极小（`var` 已是保留字，`handler_arm` 首 token 要求 IDENT，槽位干净零歧义，
  fmt 实测零改动）。三条附带规定：**格子必须全在臂之前**（乱序给专门诊断，别让读者猜
  声明顺序有没有意义）、**类型标注强制**（花括号里没有上下文可推）、
  声明的是位置而不是新语法（`var` 与赋值语句见 [spec.md](spec.md) §4.1）。

**问题三：`?` 与最终状态。**

- 本文倾向：口径 1（`?` 照旧透明，`return` 臂不跑，状态丢掉），并把这句写进
  [spec.md](spec.md) §6.5 的条文，不留给读者猜。探针 P7 是它今天的样子。
- 最强反对：`return` 臂看起来一定会跑，`?` 让它不跑，这是把一个陷阱写进语法里。
  Koka 那边 `return` 子句与异常的交互也是同一处公认的粗糙。真要选口径 1，
  至少应当在 `?` 出现在带状态的区域里时给一条 lint 级的提醒。
- **裁决（2026-08-29）：口径一。** `?` 照旧透明；早退时状态丢弃，格子随 handler 帧一起销毁。
  这不是本文发明的口径，它是文献里的 **local state interpretation**（§10.8），
  即状态 handler 装在错误边界内侧时的标准答案。要用一句话写进 [spec.md](spec.md) §6.5 的条文，
  不留给读者猜。翻案之后这条的代价比原文估计的还小：候选二里没有「看起来一定会跑的
  `return` 臂」在骗人（§6.6），早退时不执行的就是块剩余里那行读格子的代码。

**问题四：重入语义。**

- 本文倾向：按 §6.2 那条写死（臂够不着自己这次安装，嵌套各有各的格子），并把它所依赖的
  「臂的环境是安装点之前那一层」从 `checker.dawn` 的注释升格为 spec 条文。
- 最强反对：把一条实现事实升格成条文，等于承诺以后不能改它。今天它是 V1′ 调用点语义的
  副产品，不是被设计出来的；先写进 spec 会在下一次动效果语义时变成额外的约束。
  折中是写成「本档（尾恢复）下如此」，把承诺限定在这一档。
- **裁决（2026-08-29）：条文化，按折中限定档位。** 按 §6.2 写死（臂够不着自己这次安装，
  臂内发出的同名效果由外层 handler 应答，嵌套安装各有各的格子），条文里明写
  「尾恢复档下如此」，不承诺放开多次 `resume` 之后仍然这样。两侧证据都齐：四门语言先例
  一致（§10.1 的 Koka 用类型钉死、§10.9 的汇总），本仓探针 P4 与调研当日的重跑也一致
  （内层臂的 `ask()` 落到外层 handler，得 30）。

**问题五：格子原语是内部的还是用户可拼写的。**

- 本文倾向：**内部**，照 `ev_get` / `ev_append` 的形态，进 `internal_intrinsics()`，
  不进 `types.builtins()`，不进 `selfhost/builtins.dawn` 的镜像。§3.4 的无环论证依赖这一条。
- 最强反对：一个可拼写的 `Cell[T]` 能顺手解决别的事（可变累积、记忆化），而且
  「语言里有一个可变格子」这件事迟早要面对，现在藏起来只是推迟。反驳这条要指出：
  一旦可拼写，环就可构造，代价与候选二相同，而收益归到了本文之外的用例上。
- **裁决（2026-08-29）：内部。** 照 `ev_get` / `ev_append` 的体例进 `internal_intrinsics()`，
  不进 `types.builtins()`，不进 `selfhost/builtins.dawn` 的镜像；用户拼不出 `Cell[T]`，
  也拼不出格子本体。这条在候选二下比在候选一下更承重：§3.4 的无环论证原本挂在
  「臂签名里根本没有格子」上，翻案之后改由「不可拼写」加「逃逸禁令」两条一起顶
  （§4.4 的翻案补注、§4.5 的勘误补注）。落点清单在 §7.1，RC 契约那三句话照
  `dawn_rt.c:1453-1460` 的体例写。

## 9. 机器验过的探针

探针在 `dawn.toml`（`schema = 1` + `name`）+ `src/main.dawn` 的最小项目里跑，
编译器 v0.69.0，基线 `main = ae3cd59`。只有本文作者亲自重跑过的才列在这里。
实施勘察那一批（P-E1…P-E4）不在本表，它们连同各自的数字记在 §7.6，
出处是那次勘察而不是本表作者的重跑。

| # | 问的是 | 结果 |
|---|---|---|
| P1 | 收集型 handler（`var acc` + 臂赋值 + 区域后读） | 3 条错误，逐字与 §1 引的一致 |
| P2 | callee 装的 handler 罩不罩得住 caller 传进来的闭包 | 罩得住，`run(() => ask() * 2)` 打印 `10` |
| P3 | 嵌套安装同一效果 | `outer=1 inner=2 after=1`，内层遮蔽外层 |
| P4 | 臂发出它自己应答的效果，谁答 | 外层 handler 答，打印 `outer 10`，不是死循环 |
| P5 | 臂捕获一个 `let` 绑的可变对象（Java 格子），跨三次 raise 累积 | 打印 `6`，累积成立 |
| P6 | 嵌套两层收集器，各自一个格子 | 打印 `882`，外层状态跨过内层安装存活 |
| P7 | `?` 在块剩余里逃逸时，攒到一半的状态 | 打印 `state before ?: 3` 后返回 `None`，状态丢掉 |
| P8 | 自引用的 `var` 槽（环的最小形状）今天能否构造 | 不能，`lambdas cannot capture var bindings` |
| P9 | 臂写完格子之后 panic，`catch_fault` 接不接得住 | 接不住，打印 panic 串并以 1 退出 |
| P10 | 装了 handler 的函数自己的行 | 不含 `Emit`，`collect` 是纯的，打印 `0` |

P5、P6、P7、P9 里的「格子」都是 `java.util.concurrent.atomic.AtomicLong`，
因为语言里今天没有格子（§2.3）。它们量的是**格子这个形状够不够用**，不是提议用 Java 实现它；
[tea-block-children-design.md](tea-block-children-design.md) §3.1 已经逐条说明 Java 那条路
为什么不算答案。

## 10. 跨语言调研（2026-08-29）

三路只读勘察，问的是同一个问题：别的效果系统里，handler 的臂靠什么在两次操作调用之间
存住东西，以及它们怎么处理格子逃出词法域。§8 的五条裁决里有三条是被这一节翻过来的，
所以出处照录。

### 10.1 Koka

**参数化 handler 只活在 2016 年的技术报告里。** MSR-TR-2016-29 给的形制与本文候选一同款：
状态经 `resume` 的首参往下传（`resume(s', ())`），`return` 臂返回 `(x, s)`。
今天的 Koka 语法里它不在了：`parser.y` 的 `handlerexpr` 没有参数位，AST 里那个
`hndlrLocalPars` 字段恒为空，是没删干净的残留。

**官方惯用的就是候选二。** handler 的词法域里一个 `var`，臂写它，`return` 臂读它交出去。
book 里 tour 的 emit-collect 例与本文 §4.2 的 UI 收集器同构；`pstate` 那一族用
`return(x) (x, st)` 把终态和剩余的值一起交还，正是本文 §3.2 说 lexer 客户需要的那种元组。

**`var` 逃逸是类型错误。** 生命周期不得超出词法域，book 里有一个专门的 `wrong()` 反例。
这是问一那条禁令的第一条先例：Koka 明说 `var` 是 "not quite first-class"。

**多次 resume 下 `var` 随栈保存恢复。** `std/core/hnd.kk` 的 `prompt-local-var` 做的就是这件事，
文档还明写若改成堆分配就会 "leak across resumptions"。这是本文期权记录那句话的来源：
放开多次 `resume` 的那天，格子的表示必须跟着换。

**`return` 臂在非本地退出时不跑，而 `finally` 只能返回 `()`。** 于是「早退时把已收集的东西
交还」在 Koka 里无解。这条正好是问三的对照：Koka 也是 local state interpretation。

**臂看不见自己。** `emit-quoted1` 的类型 `⟨emit,emit|e⟩` 把这一点钉死；要覆盖外层得写
`override`，而 `override` 是 `mask behind` 的糖。与 §6.2 的重入条款、探针 P4 一致。

Dawn 的 v1 档对应 Koka 的 `fun` 与 `linear effect`，后者官方明言免掉 monadic 变换。
出处：koka-lang 的 `book/tour.kk.md`、`spec.kk.md`、`lib/std/core/hnd.kk`，与 MSR-TR-2016-29。

### 10.2 Effekt

`var` 声明在 `try` **之外**、臂里赋值、`try` 之后直接读，没有 value case。官方 tour 的
collect 例与本文 §4.2 同构。这就是问二裁决里的「Effekt 邻接形」。

**早退时状态存活是白送的。** 臂不调 `resume` 就是早退，而格子在被丢弃的那段控制流之外，
截断之后仍然读得到。注意这与问三不冲突：Dawn 的 `?` 是从**块剩余**里逃逸，格子随
handler 帧一起销毁，两者丢的不是同一段控制流。

**逃逸靠 region 与捕获集合挡。** `var` 分配在栈上，闭包类型写成 `() => Int at {r}`，
捕获集合进类型，所以格子跑不出它的 region。这是问一那条禁令的第二条先例，手段与 Koka 不同
而挡住的是同一件事。

**「格子在 handler 内还是外」的语义差别（backtrack 与 carry-over）只在多次恢复下可观测。**
单次恢复档里两种写法答案相同，这也是问二能退化成拼写细节的原因。

多次恢复加栈上格子的实现参考：Muhcu、Schuster、Steuwer、Brachthäuser，
《Multiple Resumptions and Local Mutable State, Directly》，ICFP 2025。期权记录指的就是它。
出处：effekt-lang.org 的 tour（effects / variables / regions 三节）。

### 10.3 OCaml 5

官方 `effects-examples/state.ml` 把本文的两个候选并排实现了一遍：`LocalMutVar` 用 `ref` 格子
（候选二），`StPassing` 把 handler 求值成一个 `λst` 函数（候选一）。handler 是
`retc` / `exnc` / `effc` 三个口子；续延一次性，重复用报 `Continuation_already_resumed`。
另有一个 `GlobalMutVar`，源码里注明它对嵌套 `run` 不安全，与 §6.4 的嵌套遮蔽是同一个坑。

### 10.4 Unison

递归的 handler 函数显式传状态（`storeHandler` / `impl map` 那一族），每次 `resume` 都要
显式重装 handler；要交还终态就把纯分支从 `pure` 改成 `(pure, state)`。续延类型里仍带 `{A}`，
是浅 handler 形态。它是「不给语言支持、让用户手写」的那一端。

### 10.5 Eff

**resources 就是候选一的逐字形制**：`operation op x @ s -> (result, newstate)`，而且臂里不许
再发效果，违者运行期报错。这条限制本身就说明了退化形有多窄。

2015-06-05 的提交 `1c6d7fa0` "Remove instances" 把整个机制删掉，提交里没写理由。
当年引入它的动机原文倒是留着：一等引用「may propagate outside the scope of its handler
where its behaviour is undefined」。也就是说，Eff 是**因为挡不住逃逸**才删的；
问一那条禁令正是它当年没有的那件东西。

### 10.6 Links

参数化 handler 的糖已经删了（当前 lexer 里连 `handler` 关键字都没有），官方例
`deep_state.links` 改成让用户手写 state-passing。与 Koka、Eff 合起来是三删。

### 10.7 形制判死：纯 state-passing 在尾恢复档不可表达

这是本节最关键的负结果，它把候选一从「拼写噪音大一些」降级成「只剩一个退化形」。

经典的 state-passing 编码要求臂返回一个 `λst`，并且对**续延的结果**再应用一次
（`(k s) s`）。按定义，「先拿到 `k` 的结果再往上应用」不是尾恢复。Koka 的 `fun` 档是判据：
它的糖是 `resume(f())`，臂体的值落在 `resume` 的实参位，`resume` 之后不再有计算。

Hillerström 的博士论文 §3.4 给出参数化 handler 的形式化（`T-Handler‡`：`resume` 是二元函数；
`S-Ret‡` 把终态代入 `return` 臂），§6.3 等处给出表达性证明：把参数化 handler 翻译掉需要把
答案类型抬成 `A → B!E`，而这一步在尾恢复档下用不了。

推论：Dawn 只有尾恢复，所以候选一在 Dawn 里能拼出来的只有那个退化形，而那个退化形逐字
等于 §10.5 的 Eff resource。这是问一裁决的第二条依据。

### 10.8 `?` 早退的标准术语

Wu、Schrijvers、Hinze，《Effect Handlers in Scope》，Haskell 2014，用 `tripleDecr` 例区分
**global** 与 **local state interpretation**：state handler 装在 error 边界内侧就是 local，
早退时状态丢弃。问三裁的口径一就是它，所以 spec 条文里用得上这个名字。

工程侧的做法参考 fused-effects：三个 `State` carrier 各自在文档里用一句话写明自己的语义
（`IORef` 那版写的是「不丢状态但不回滚」）。这印证了问三裁决的后半句：口径本身不难选，
难的是有没有写进条文；写一句话就够。

### 10.9 三家收敛的那一条

Koka、Effekt、Eff 在同一件事上收敛：**格子必须绑死 handler 的词法域，不可捕获，
不可作为值传出**。手段各不相同（Koka 判类型错误、Effekt 用 region 与捕获集合、
Eff 挡不住于是把整个机制删了），结论一致。问一那条禁令就是这一条。

也要如实记下差别：这三门都没有纯尾恢复档，所以「格子完全不可拼写」这一步没有先例，
是本仓特有的设计空间。它的方向与 Koka 的 "not quite first-class" 一致，但比三家都更靠里一格，
代价与收益要由本仓自己的门禁看住（§7.5）。
