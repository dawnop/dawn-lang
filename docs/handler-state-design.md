# handler 局部状态

> 状态：proposed。2026-08-29 由用户立项（裁决记在
> [tea-block-children-design.md](tea-block-children-design.md) §8 问题二），
> 本文是立项后的设计文档，**未评审，不要照着实现**。
> 两个候选各自完整，倾向与最强反对写在 §8，裁决栏留空。
> 勘察基线 `main = ae3cd59`，文中 file:line 均对该提交，编译器为 v0.69.0。
> 代码块都不标 `dawn run` / `dawn compile`，`doc-check.py` 不编译它们；
> 哪些形状是真在这个编译器上问过的，逐条记在 §9。

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

**格子不必是 `ev$E` 的字段。** 它可以在造记录之前先造出来，臂按值捕获它。捕获的是一个
不可变的引用，指向一个可变的对象；按值捕获这条纪律一个字都不用改。这一点用 Java 对象
在今天的编译器上直接验过（探针 P5：`let` 绑一个 `AtomicLong`，三次 raise 各读各写，
区域之后读出 6），也验过嵌套安装各攒各的（探针 P6，答 882）。

把格子留在记录外面还有一个好处：`ev$E` 的形状是 `pass_effects` 按效果声明合成的，
一个效果一条；而格子是**每次安装**一个。两者的生命周期本来就不同，硬塞进记录会把
「效果有几个状态」和「装了几次」搅在一起。

## 3. 候选一：参数化 handler

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

**6.6 `?` 与最终状态。** 见 §3.5 的第二个待裁点。候选二受同一条影响，只是症状轻些：
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

### 7.4 effect-evidence-contract 登记

`scripts/effect-evidence-contract/roster.txt` 是双向棘轮：列了却不在的会红，
`scripts/spike-native/effect_*.dawn` 没列的也会红。handler 状态落地要新增至少一个语料，
按 roster 的两条车道之一登记（`assertions` 或 `transcript`），并在 roster 的
「What each entry owns」清单里加一行说它拥有什么。

语料本身照该目录的纪律写：每条线自己装 handler、各用互不相同的质数当标记，
每个 case 都要**读过格子**才算数（只安装不读，格子坏了也是绿的）。至少四条：
攒三次读一次、嵌套两层、臂发同名效果落到外层、`?` 从剩余里逃逸后的状态口径（§3.5）。

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

## 8. 待裁决

每条给出本文的倾向与最强的反对意见。裁决栏留空。

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
- 裁决：

**问题二：交回表面。**

- 本文倾向：候选一走 `return` 臂，且**不给默认**（没有 `return` 臂就不许带初值），
  理由是默认会让「状态被悄悄丢掉」编得过。候选二走作用域延伸（handler 花括号里的
  `var` 在块剩余里可见）。
- 最强反对：作用域延伸这件事，候选二做起来比听上去怪。`with handle` 的花括号在今天是
  一个封闭的臂表，里面的东西一个都不往外看；让其中一种绑定往外看，读者要记住哪种往外
  哪种不往外。候选一的 `return` 臂虽然是新语法，但它把交回明写成一行代码，没有隐式作用域。
- 裁决：

**问题三：`?` 与最终状态。**

- 本文倾向：口径 1（`?` 照旧透明，`return` 臂不跑，状态丢掉），并把这句写进
  [spec.md](spec.md) §6.5 的条文，不留给读者猜。探针 P7 是它今天的样子。
- 最强反对：`return` 臂看起来一定会跑，`?` 让它不跑，这是把一个陷阱写进语法里。
  Koka 那边 `return` 子句与异常的交互也是同一处公认的粗糙。真要选口径 1，
  至少应当在 `?` 出现在带状态的区域里时给一条 lint 级的提醒。
- 裁决：

**问题四：重入语义。**

- 本文倾向：按 §6.2 那条写死（臂够不着自己这次安装，嵌套各有各的格子），并把它所依赖的
  「臂的环境是安装点之前那一层」从 `checker.dawn` 的注释升格为 spec 条文。
- 最强反对：把一条实现事实升格成条文，等于承诺以后不能改它。今天它是 V1′ 调用点语义的
  副产品，不是被设计出来的；先写进 spec 会在下一次动效果语义时变成额外的约束。
  折中是写成「本档（尾恢复）下如此」，把承诺限定在这一档。
- 裁决：

**问题五：格子原语是内部的还是用户可拼写的。**

- 本文倾向：**内部**，照 `ev_get` / `ev_append` 的形态，进 `internal_intrinsics()`，
  不进 `types.builtins()`，不进 `selfhost/builtins.dawn` 的镜像。§3.4 的无环论证依赖这一条。
- 最强反对：一个可拼写的 `Cell[T]` 能顺手解决别的事（可变累积、记忆化），而且
  「语言里有一个可变格子」这件事迟早要面对，现在藏起来只是推迟。反驳这条要指出：
  一旦可拼写，环就可构造，代价与候选二相同，而收益归到了本文之外的用例上。
- 裁决：

## 9. 机器验过的探针

探针在 `dawn.toml`（`schema = 1` + `name`）+ `src/main.dawn` 的最小项目里跑，
编译器 v0.69.0，基线 `main = ae3cd59`。只有本文作者亲自重跑过的才列在这里。

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
