# 视图 DSL 的块形子节点

> 状态：**proposed**。摆材料，不给结论。本文把「子节点用尾块发出，而不是写成列表字面量」
> 这件事的三条路线、各自的墙和各自的代价摆出来，裁决栏留空。
> 勘察基线 `main = 6e0fb63`，文中 file:line 均对该提交，编译器为 v0.69.0。
> 本文的代码块都不标 `dawn run` / `dawn compile`，`doc-check.py` 不编译它们；
> 哪些块是真在这个编译器上跑过的，逐个记在 §9。

## 1. 这份文档回答什么

用户对 Dawn 前端方向的既定前提是「写一门类 Compose 的 UI DSL」，#206 的尾块与 #207 的
具名实参/默认参数都是为它落的（[tail-block-design.md](tail-block-design.md) §13、
[named-args-design.md](named-args-design.md) §9）。两件语法件已经在手上，
`packages/tea-dom` 也已经是一个真在浏览器里跑的消费者
（[dom-bridge-design.md](dom-bridge-design.md)）。

于是问题变得具体：**子节点还要不要继续是列表字面量。** Compose 的写法是子节点由一个
尾块「发出」，`Column { Text("a"); Text("b") }`；Dawn 今天的写法是子节点是一个
`List[Node[M]]` 值，条件渲染写 `if c { [x] } else { [] }` 再 `++`，循环写 `list.map`。

这份文档不是实施方案。它要回答的是：Compose 那种形状在 Dawn 里**能不能表达**，
不能的话缺的是哪几件语言能力，以及不做它的代价是什么。

## 2. 今天的形状

### 2.1 两把刀之后

视图 DSL 最近挨了两把人体工学的刀，都已落地：

- **元素形式**（[spec.md](spec.md) §4.11，提交 `392fc36`，门禁
  `scripts/list-elems-contract`）：列表字面量里换行等价于逗号，`..xs` 展开一段，
  `if c { x }` 贡献 0 或 1 个元素。期望类型向下传，所以中间那些只为标注类型而存在的
  `let` 消失了。终端那份 todo 是它的现役消费者
  （`examples/projects/tea_todo/src/todo.dawn:142-151`）：

  ```dawn
  column([
    header,
    ..if list.is_empty(m.todos) {
      [dim(text("nothing yet; try: add buy milk"))]
    } else {
      list.map(m.todos, t => item_row(t))
    },
    if m.note != "" { text(m.note) },
    dim(text("commands: add <title> | tog <id> | del <id> | press <n> | quit")),
  ])
  ```

- **监听器函数化**（[dom-bridge-design.md](dom-bridge-design.md) §9，提交 `677adaa`）：
  `On[M]` 从装消息值改成装 `fn(String) -> M`，`trait Fill` 和每个应用里的 `impl Fill`
  一起删掉。DOM 那份 todo 是它的现役消费者：`on_value("input", SetDraft(text: ""))`
  变成 `on_value("input", SetDraft)`，应用一个字的胶水都不写。

这两刀合起来，把「一次带值交互要在四处登记」降到两处，把「一段子节点要拆成几个带标注的
`let` 再拼」降到一个字面量。两刀都不碰子节点的**形状**：子节点仍然是一个列表值。

### 2.2 剩下的是列表形状本身

`examples/projects/tea_dom_todo_keyed/src/todo.dawn` 的视图段（160-274 行）是今天最完整的
一份 DOM 视图。剩下的噪声可以逐条点名。

**一、位置占位的空列表。** `el` 的四个形参全是位置实参
（`packages/tea-dom/src/dsl.dawn:22-28`），一次调用用不上的那几个要写 `[]` 顶上。
视图段里有 **11 个 `[]` 字面量，全部是占位**：

```dawn
let heading: Node[Msg] = el("h1", [], [], [text("dawn todo")])          # :161
let status: Node[Msg] = el("p", [("class", "status")], [], [text(summary(m))])  # :175
el("div", [("class", root_class(m))], [], [heading, composer, filters, items, status])  # :176
```

这一条**与本文的三条路线都无关**：默认参数今天就消得掉它，一件新语言能力都不要。
提交 `e8472a6` 刚把「默认值的类型可以提到函数自己的类型参数」打开，于是
`on: List[On[M]] = []` 是合法签名，`el("h1", kids: [text("dawn todo")])` 编得过
（探针 P7）。要不要落到 `dsl.dawn` 是包的事。

**二、根视图仍然是「先声明五段、再拼一次」。**

```dawn
fn view(m: Model) -> Node[Msg] = {                                     # :160
  let heading: Node[Msg] = el("h1", [], [], [text("dawn todo")])
  let composer: Node[Msg] = compose_row(m)
  let filters: Node[Msg] = filter_row(m.filter)
  let items: Node[Msg] =
    keyed("ul", [("class", "list")], [], list.map(visible(m), t => (to_string(t.id), row(m, t))))
  let status: Node[Msg] = el("p", [("class", "status")], [], [text(summary(m))])
  el("div", [("class", root_class(m))], [], [heading, composer, filters, items, status])
}
```

五个名字各出现两次，一次声明一次使用，且每个都要 `: Node[Msg]` 标注。元素形式本可以让
它们直接落进字面量（那正是 `tea_todo` 做的），这里没有，是因为 `keyed` 那一段跨了六行，
把它塞进兄弟字面量里读不出来。这是**排版**逼出来的中间变量，不是类型逼出来的。

**三、循环是 `list.map` 出一串二元组。**

```dawn
list.map(visible(m), t => (to_string(t.id), row(m, t)))                # :173
```

`(key, node)` 的二元组是 `keyed` 的签名逼出来的，理由写在
`packages/tea-dom/src/dsl.dawn:60-66`（漏一个 key 要是类型错误而不是静默回落下标配对）。
它是对的，但它读起来不像「for 每一行」。

**四、两种形状的行整个复写一遍。** `row`（:248-274）是 `if / else`，两臂各是一个完整的
`el("li", ...)` 调用，第二臂里还嵌了两处 `if ... { ... } else { ... }` 算 class 和图标。
条件在这里是**整节点**级的，元素形式帮不上（它只在字面量里成立），`++` 也帮不上。

把这四条合起来看：第一条是签名问题，第二、三、四条才是「子节点是一个列表值」这件事本身的
代价。Compose 形状要买的正是后三条。

## 3. 路线一：由效果发出子节点

形状是：声明一个 `effect Emit`，组件调 `emit` 把自己交出去，容器安装 handler 把块里发出的
都收下来。

```dawn
effect Emit {
  fn emit(n: Node) -> Unit
}

fn collect(body: fn() -> Unit !Emit) -> List[Node] = ???

fn el(tag: String, props: ... = [], on: ... = [], body: fn() -> Unit !Emit = () => ()) -> Unit !Emit =
  emit(Elem(tag: tag, props: props, on: on, kids: collect(body), key: None))
```

**这条路线的表面语法今天全部解析并通过类型检查。** 探针 P5（`el` 带默认参数 + 尾块 +
块里 `if` 无 `else` 当语句）与 P6（整页视图，见 §6）都编得过，只把 `collect` 换成桩。
换句话说，#206 和 #207 已经把这条路线的**拼写**买齐了；缺的全在 `collect` 那一行。

### 3.1 收集点那堵墙（实测）

`collect` 要在两次 `emit` 之间存住已经收到的东西。尾恢复档的 handler 臂是普通闭包，
按值捕获，[spec.md](spec.md) §6.5 明写「臂本身也是闭包，同样拒绝捕获外层 `var`、
拒绝在臂内赋值」（spec.md:1647）。把它写出来喂给编译器：

```dawn
effect Emit {
  fn emit(n: Int) -> Unit
}

fn collect(body: fn() -> Unit !Emit) -> List[Int] = {
  var acc: List[Int] = []
  with handle Emit { emit(n) => { acc = acc ++ [n] } }
  body()
  acc
}
```

v0.69.0 逐字回答（探针 P1）：

```
error: cannot assign to `acc` from inside a `with handle` arm
  = hint: an arm is a closure and captures by value; hand the value back as the operation's result instead
error: a `with handle` arm cannot capture `var` bindings (capture is by value)
  = hint: bind it to a let before the handler, or pass it in as an operation parameter
error: the closure `with` introduced cannot capture `var` bindings (capture is by value)
  = hint: bind it to a let before the `with`, or pass it as a parameter
```

**三条，不是一条。** 前两条是臂的墙；第三条是块剩余的墙，它说的是：即使臂能写 `acc`，
`with handle` 之后那一行 `acc` 也读不出来，因为块剩余本身是闭包
（[spec.md](spec.md) §4.10 的按值捕获纪律）。收集**和**交回，两头都堵死。

这不是新发现，是 [effects-design.md](effects-design.md) §7 开放问题 1 在 2026-08-02 就量到
的结论（「收集类站点在尾恢复档不可表达」）。那份判词写在 V1′ 之前，效果的语义此后翻过一次
（handler 从创建点改判为调用点，[spec.md](spec.md) §6.5），所以本文重新在今天的编译器上
问了一遍，答案没有变。

**能不能写成 fold。** 不能，而且不是拼写问题。尾恢复档没有 `resume`：臂就地返回，
返回值就是操作的结果（[effects-design.md](effects-design.md) §1）。要把
`resume with acc ++ [n]` 那种形状写出来，需要延续，而延续正是这一档明确不做的东西
（与 C 后端的 Perceus 单栈模型正面冲突，同节）。累积值在两次 `emit` 之间没有地方住：
臂之间没有共享的槽，语言里也没有 ref cell（`Array` 是 `is_std_module` 门控的表示原语，
[spec.md](spec.md):231-232，用户模块借不到这个名字）。

**唯一一个真的编得过的收集器，以及它为什么不算。** 把累积器换成一个 Java 可变对象，
绑定就是 `let`，臂不是「赋值外层 var」而是「穿过一个引用去改」：

```dawn
use java "java.lang.StringBuilder"

fn collect(body: fn() -> Unit !Emit) -> String !io = {
  let sb = StringBuilder.new()
  with handle Emit { emit(n) => { let _ = sb.append(n) } }
  body()
  sb.toString()!
}
```

这个编得过也跑得出（探针 P4，`emit(1)` 打印 `1`）。它答不了这个问题，三条独立理由：

1. **它装不下 `Node`。** 跨边界的 Dawn 值只有 `Int`/`Float`/`Bool`/`String`/`Unit` 与
   引入的类（[spec.md](spec.md) §9.2 的映射表），ADT 不在其中，Java 集合也不反向转成
   Dawn 值（§9.7）。把 `Node` 换进去，编译器答
   `no overload of ArrayList.add matches (Node)`（探针 P4b）。
2. **它是 `!io`。** 而 `trait App` 的 `fn view(m: M) -> M.View` 没有行位
   （`packages/tea-core/src/app.dawn:52`）。给 impl 的 `view` 写 `!io`，编译器答
   `view is declared !io but trait App declares it pure`（探针 P8）。`update` 有关联效果
   可绑，`view` 没有，这是 `#369` 那一刀刻意留的形状。
3. **它只在 JVM 上存在。** `tea-dom` 的宿主形态是 wasm reactor
   （[dom-bridge-design.md](dom-bridge-design.md) §2）。

所以结论是硬的：**今天没有任何写法能把 Dawn 值收集出一个 handler。**

### 3.2 第二堵墙：效果不带类型参数

`emit` 要交出去的是 `Node[M]`，而 `M` 是应用自己的消息类型。写出来：

```dawn
effect Emit[T] {
  fn emit(x: T) -> Unit
}
```

编译器答（探针 P2）：

```
error: an effect cannot declare type parameters
  = hint: v1 effects are bare labels; specialize at the declaration instead
```

条文在 [spec.md](spec.md):1601（「效果本身不带类型参数；`effect Yield[T]` 当前不支持」），
它是另一根轴、另立项，与已经关账的 RX-10-B 无前后置关系
（[effects-design.md](effects-design.md) §7 开放问题 5）。

后果不是「少一点糖」，是**词汇的归属换人**：`effect Emit` 只能在 `Node[Msg]` 具体化之后
声明，也就是只能声明在**应用里**，不能声明在 `packages/tea-dom` 里。`tea_dom/dsl` 是泛型的
（11 个 `pub fn` 全带 `[M]`，`dsl.dawn:19-124`），它交不出这个效果。

### 3.3 第三堵墙：装 handler 的人必须点名效果

那么让应用声明效果、让库函数经效果变量转发呢？转发可以，安装不行：

```dawn
fn collect(body: fn() -> Unit !e) -> List[Int] = {
  with handle e { emit(n) => { } }
  ...
}
```

```
error: expected the effect to handle (`with handle Ask { ... }`), found `e`
```

（探针 P3。条文在 [spec.md](spec.md):1732：「效果多态代码能转发、不能装 handler」，
`with handle E` 在语法上就点名一个具体效果，安装点永远是单态的。）

而 `el` 必须安装：它要收自己的子节点。三堵墙叠起来的结论是：**路线一里，`el`/`keyed`/`text`
这一整套词汇必须住在每个应用自己的模块里，每个应用抄一份。** 这跟「`tea_dom` 提供词汇」是
相反的方向。

### 3.4 签名污染

假设三堵墙都拆了，签名会变成什么，逐个写出来（这些是探针 P6 里真编过的形状）：

| 今天 | 路线一 |
|---|---|
| `fn view(m: Model) -> Node[Msg]` | `fn view(m: Model) -> Node[Msg]`（不变） |
| `fn row(m: Model, t: Todo) -> Node[Msg]` | `fn row(m: Model, t: Todo) -> Unit !Emit` |
| `fn compose_row(m: Model) -> Node[Msg]` | `fn compose_row(m: Model) -> Unit !Emit` |
| `fn filter_row(cur: Filter) -> Node[Msg]` | `fn filter_row(cur: Filter) -> Unit !Emit` |
| `fn filter_button(label: String, which: Filter, cur: Filter) -> Node[Msg]` | `... -> Unit !Emit` |

`view` 不变是这条路线唯一的好消息，而且是结构性的：`with handle` 是全语言唯一能从行里减去
标签的节点（[spec.md](spec.md) §6.5），`collect` 装了 handler 就把 `!Emit` 减掉了，
所以 `trait App` 那条纯签名（`app.dawn:52`）仍然满足。**前提是 `collect` 本身是纯的**，
这正是 §3.1 第 2 条排除 Java 收集器的原因。

**效果多态能藏什么、藏不了什么。** 能藏的：`!e` 让高阶库函数零改动转发，
`list.map`、`for` 脱糖走的游标函数都不必知道 `Emit` 存在
（[spec.md](spec.md) §6.3「效果变量横跨两轴」；探针 P6 里
`for t in visible(m) { key(...) { row(m, t) } }` 就在一个 `!Emit` 的块里编过）。
藏不了的两件：

- **组件自己的签名。** 一个组件发 `Emit`，它的签名就得写出来。`!e` 是「转发调用者的行」，
  不是「隐藏自己的行」；写 `!e` 的函数不能 `with handle`，也不能自己发一个具体标签而不申报。
- **trait 方法的行。** [spec.md](spec.md) §6.5 的边界那条：写出来的标签在 impl 与 trait
  之间**必须恰相等**，因为每个标签是一格隐藏证据参数，是方法的元数。关联效果
  （#369 的 `effect E = !()`）能让每个 impl 绑自己的行，但那一格是**擦除**的投影，
  `with handle` 同样点不了它的名。

### 3.5 纯度与测试

视图函数从返回值变成发出值，测试要先跑收集器才拿得到树。今天
`examples/projects/tea_dom_todo_keyed/src/todo.dawn:407-425` 这条：

```dawn
test "both fields are controlled, so the document renders the model" {
  let field: Node[Msg] =
    el("input", [("class", "field"), ("value", "buy milk")], [on_value("input", SetDraft)], [])
  assert first_kid(compose_row(update(init(), SetDraft(text: "buy milk")))) == Some(field)
  ...
}
```

路线一里 `compose_row` 返回 `Unit`，所以它变成：

```dawn
assert first_kid(one(collect(() => compose_row(update(init(), SetDraft(text: "buy milk"))))))
  == Some(field)
```

`collect(() => ...)` 是每一条视图断言都要多写的一层，`one(...)` 是第二层（见 §3.6）。
**值相等本身不丢**：只要 `collect` 是纯的，`Model -> Node` 仍然是一个纯函数的复合，
`==` 仍然断得了一帧，`scripts/wasm-dom-contract` 的转录一个字节都不会变
（它比的是线上的字节，构造方式在线外，见 §7）。丢的是**直接性**：今天一条断言问的是
`compose_row(m)`，路线一里问的是「把 `compose_row(m)` 跑进一个收集器之后的那棵树」。

### 3.6 键控子节点

`keyed("ul", props, on, kids: List[(String, Node[M])])` 的二元组在块形式里没有位置，因为块
不返回值。对应的拼写是一个包装：

```dawn
keyed("ul", props: [("class", "list")]) {
  for t in visible(m) {
    key(to_string(t.id)) { row(m, t) }
  }
}
```

`key` 的实现要把块里发出的东西**恰好取一个**出来：

```dawn
fn key(k: String, body: fn() -> Unit !Emit) -> Unit !Emit = emit(with_key(one(collect(body)), k))

fn one(ns: List[Node]) -> Node =
  match ns {
    [n] -> n
    _ -> panic("a view emits exactly one node")
  }
```

这是路线一自带的一笔账，且不只在 `key` 上：`view` 的最外层也要 `one(collect(...))`。
**「这个块恰好发出一个节点」不在类型里**，它是一次运行期检查。今天这件事是类型说了算
（`row` 返回 `Node[Msg]`，写不出「返回零个」）。`dsl.dawn:60-66` 记着 `keyed` 收二元组列表的
理由是「漏一个 key 要是类型错误而不是静默回落」；块形式把这一条从类型级降到 panic 级，
方向相反。

### 3.7 混用

不能白拿。尾块永远脱糖成一个 thunk：`f(a) { e }` 就是 `f(a, () => e)`
（[spec.md](spec.md):842），而块形式的组件返回 `Unit`，值形式的组件返回 `Node[M]`，
同一个名字给不了两种返回类型。三种活法：

1. **词汇分叉。** `el` 返回 `Node[M]`，`el_` 发出自己（`fn el_(...) -> Unit !Emit =
   emit(el(...))`）。`dsl.dawn` 的 11 个 `pub fn` 里 8 个是节点构造器
   （`text`/`el`/`keyed`/`div`/`div_of`/`span`/`button`/`foreign`），要各配一个孪生，
   3 个监听器构造器不受影响。API 面从 11 涨到 19。
2. **只留块形式**，值形式的调用点自己写 `one(collect(() => ...))`。反向适配比正向贵。
3. **只留值形式**，块形式的调用点自己写 `emit(...)` 包一层。这时块里每一行都以 `emit(`
   开头，Compose 的观感也就没了。

无论哪一种，`tea_term` 那份词汇（`packages/tea-term/src/dsl.dawn`，104 行）要不要跟着分叉是
另一笔账：它今天与 `tea_dom/dsl` 是同一层的两份拼写，形状一致是刻意的。

### 3.8 缺的语言能力，逐件

| 缺件 | 今天的答复 | 探针 |
|---|---|---|
| handler 局部状态（臂之间有一个槽，`with handle` 交回终值） | 三条 capture 错误 | P1 |
| 参数化效果 `effect Emit[T]` | `an effect cannot declare type parameters` | P2 |
| 在效果变量上装 handler | `expected the effect to handle ..., found e` | P3 |

第一件是必需的，且没有替代（§3.1）。第二、三件是「词汇能不能住在 `tea_dom` 里」的问题：
不解决，每个应用抄一份 DSL；解决其中任何一件都够。

第一件的形状在 [effects-design.md](effects-design.md) §7 已经点名过候选（Koka 的 `var`
handler 字段），并且明说「等 dogfood 疼了再设计」。本文就是那个 dogfood 报告：疼点是
UI DSL，而且它不是「写起来别扭」，是不可表达。

## 4. 路线二：块产生列表

语言改动：子节点位置上的一个块，把它的表达式语句收成一个列表。

```dawn
el("div", props: [("class", "compose")]) {
  field
  add
  boom
}
```

这条路线本文论证**不该做**，理由不是代价大，是它过不了本仓对语法歧义的那道常青线
（`CONTRIBUTING.md:54-59` 的「不做的（记录理由）」要求推翻旧裁决必须给新证据；
[tail-block-design.md](tail-block-design.md) §1 是一次合格的推翻，它给的证据是
「区分机制早已在 parser 里、且已经用在同一个位置上」。这里没有对应的东西）。

**第一，块的值这条规则会有第二种读法。** [spec.md](spec.md) §4.2 定的是：块的值是最后一个
表达式，其余语句必须是 `Unit`。路线二要的是：块的值是**所有**表达式的列表。同一个 `{ ... }`
今天出现在函数体、`if` 分支、循环体、match 臂和尾块五个位置上，而尾块与前四个在语法上不可
分辨（它就是一个 thunk 的体）。所以「收集」不能由语法决定，只能由**被调方最后一个形参的
类型**决定。于是同一份源码的含义要等类型检查器算出 callee 是谁才定得下来，这与 §4.2 的
「块的值是最后一个表达式」并列成两条规则，读者在读到 `{` 时判不出走哪一条。

顺带一个实测：今天 `column { text("a") \n text("b") }` 不是「两个含义待定」，而是硬错误
（探针 P6′）：

```
error: this Node value is discarded
  = hint: write let _ = ... to discard it, or move it to the block's tail/return position
```

所以路线二在「合法程序集合」上确实是加法，这是它唯一的好消息。但它要占的那块地今天由一条
**规则**占着，不是由空白占着，而那条规则的存在理由（不许悄悄丢弃 `Result`）与子节点无关，
不会因为这里换了含义就在别处失效。

**第二，没有 else 的 `if` 会有第三种读法。** 今天它有两种，各有各的地盘且互不相邻：普通表达式
位置上必须是 `Unit`（[spec.md](spec.md) §4.6），列表字面量的元素位置上贡献 0 或 1 个
（§4.11）。路线二要在**块语句**位置上再给一种「贡献 0 或 1 个」。第三种与第一种共用一个位置
（块语句），区分依据又是那个要等类型才知道的「块收不收集」。§4.11 那一刀之所以干净，恰恰是
因为它只动了元素位置：那个位置在特性存在之前只能是 `Unit`，「把它挪到元素位置上没有和任何
既有含义冲突」（spec.md:1323）。路线二没有这个性质。

**第三，一收集就要回答 collection-for，而它已经被判过。** 块里写 `for t in xs { row(t) }`
必然要问「循环体收集吗」，[spec.md](spec.md):1324 记着否掉 collection-for 的理由
（`list.map` 已经写得下，加了 for 立刻要回答为什么没有 while）。路线二把这个问题从
「要不要加一条元素形式」升级成「块语句里的每一种控制流各贡献什么」：`while`、`match`
的每个臂、`with` 的糖区、`return`，一条都躲不掉。§4.11 那一刀能把范围收在三种元素形式里，
是因为它有一个封闭的语法位置；块没有。

三条合起来，路线二不是「代价高」，是**它要把一个位置的含义交给类型去定**，而这正是本仓
反复拒绝的那类设计（`spec.md:162` 拒 `+`/`-` 行首续行、`spec.md:318` 拒 UFCS 的静默优先级、
[tail-block-design.md](tail-block-design.md):40 当年拒裸 `{}` 尾闭包，用的都是同一条判据）。
破坏容忍在这里帮不上忙：能被破坏性改动买到的是「换一个拼写」，买不到「同一个拼写两种读法」。

## 5. 路线三：停在列表

空选项。两把刀之后 DSL 已经是 Elm 形状，而 Elm 就是这么发了十年。

**保住的：**

- `Model -> Node` 是纯函数，`view` 在 `trait App` 里的那条纯签名不必松动
  （`app.dawn:52`）。
- 一帧是一次 `==`（`todo.dawn:389-405` 那条测试），不必先跑收集器。
- 「这个组件恰好是一个节点」由类型说了算，不是运行期 panic（§3.6 的反面）。
- 零新机制：不欠 handler 局部状态、不欠参数化效果、不欠第二套块语义。
- `tea_dom` 继续提供泛型词汇，应用不抄 DSL（§3.2、§3.3 的反面）。

**丢掉的：**

- **视图里的控制流人体工学。** 整节点级的条件仍然是 `if c { ... } else { ... }` 两臂各写一遍
  完整调用（`todo.dawn:248-274` 的 `row`），循环仍然是 `list.map` 出二元组。这是 §2.2 的
  第三、四条，元素形式够不着。
- **用户要的那个像。** Compose 的观感来自「子节点是块里的语句」，这一条不做，
  `column { ... }` 这个形状在 Dawn 里就只出现在别的地方（`with` 糖、`bracket`、
  `xs.each { ... }`），不出现在视图里。#206 和 #207 是为它落的，落完之后视图仍然是列表，
  这笔投入的兑现要记在别处。

**中间那一档，今天就有。** 尾块永远是 thunk，那么让 thunk 返回列表：

```dawn
fn el(tag: String, body: fn() -> List[Node] = () => []) -> Node = Elem(tag: tag, kids: body())

el("div") {
  [
    text("a")
    if show { text("b") }
    ..[text("c")]
  ]
}
```

编得过也跑得出（探针 P9，三个子节点）。它买到的只有「子节点挪到括号外面」，代价是多一对
方括号，元素形式照常可用。反过来，尾块**填不了**一个非函数的形参：

```dawn
fn el2(tag: String, kids: List[Node] = []) -> Node = ...
el2("div") { [text("a")] }
```

```
error: argument type mismatch: expected List[Node], got fn() -> List[Node]
```

（探针 P9′。`f(a) { e }` 恒等于 `f(a, () => e)`，spec.md:842。）
这一档不需要裁决，它是今天签名怎么写的问题，但它划出了**不改语言能拿到的上界**：
子节点能移到括号外，`[`/`]` 移不掉。

## 6. 端态代码整页

下面是 `todo.dawn` 的整个视图段在路线一里的样子。这一整页在 v0.69.0 上**通过了类型检查**
（探针 P6，`dawn check` 答 `ok`），唯一的桩是 `collect`，它是 §3.1 那件缺的语言能力。
词汇（`el`/`keyed`/`key`/`text`/`on_click`/`on_value`）在探针里与应用同模块，
这不是排版选择，是 §3.2 与 §3.3 的后果。

★ 标出的两处是今天写不出来的东西。

```dawn
effect Emit {
  fn emit(n: Node) -> Unit
}

# ★ 需要新语言能力：handler 局部状态。今天三条 capture 错误（§3.1）。
fn collect(body: fn() -> Unit !Emit) -> List[Node] = ???

# ★ `effect Emit` 只能在 Node 的消息类型具体化之后声明，所以这一套词汇住在应用里，
#   不在 packages/tea-dom 里（§3.2、§3.3）。
fn el(
  tag: String,
  props: List[(String, String)] = [],
  on: List[On] = [],
  body: fn() -> Unit !Emit = () => (),
) -> Unit !Emit = emit(Elem(tag: tag, props: props, on: on, kids: collect(body), key: None))

fn keyed(
  tag: String,
  props: List[(String, String)] = [],
  on: List[On] = [],
  body: fn() -> Unit !Emit = () => (),
) -> Unit !Emit = emit(Elem(tag: tag, props: props, on: on, kids: collect(body), key: None))

fn key(k: String, body: fn() -> Unit !Emit) -> Unit !Emit = emit(with_key(one(collect(body)), k))

fn text(s: String) -> Unit !Emit = emit(Text(s: s))

# ---- 视图 ----------------------------------------------------------------

fn view(m: Model) -> Node = one(collect(() => root(m)))

fn root(m: Model) -> Unit !Emit =
  el("div", props: [("class", root_class(m))]) {
    el("h1") { text("dawn todo") }
    compose_row(m)
    filter_row(m.filter)
    keyed("ul", props: [("class", "list")]) {
      for t in visible(m) {
        key(to_string(t.id)) { row(m, t) }
      }
    }
    el("p", props: [("class", "status")]) { text(summary(m)) }
  }

fn compose_row(m: Model) -> Unit !Emit =
  el("div", props: [("class", "compose")]) {
    el("input", props: [("class", "field"), ("value", m.draft)], on: [on_value("input", SetDraft)])
    el("button", props: [("class", "add")], on: [on_click(Add)]) { text("add") }
    el("button", props: [("class", "boom")], on: [on_click(Boom)]) { text("boom") }
  }

fn filter_row(cur: Filter) -> Unit !Emit =
  el("div", props: [("class", "filters")]) {
    filter_button("all", All, cur)
    filter_button("active", Active, cur)
    filter_button("done", Done, cur)
  }

fn filter_button(label: String, which: Filter, cur: Filter) -> Unit !Emit =
  el(
    "button",
    props: [("class", if which == cur { "filter on" } else { "filter" })],
    on: [on_click(Only(f: which))],
  ) { text(label) }

fn row(m: Model, t: Todo) -> Unit !Emit =
  if m.editing == Some(t.id) {
    el("li", props: [("class", "row editing")]) {
      el("input", props: [("class", "draft"), ("value", m.edit)], on: [on_value("input", SetEdit)])
      el("button", props: [("class", "save")], on: [on_click(Save)]) { text("save") }
      el("button", props: [("class", "cancel")], on: [on_click(Cancel)]) { text("cancel") }
    }
  } else {
    el("li", props: [("class", if t.done { "row done" } else { "row" })]) {
      el("button", props: [("class", "box")], on: [on_click(Toggle(id: t.id))]) {
        text(if t.done { "[x]" } else { "[ ]" })
      }
      el("span", props: [("class", "title")], on: [on_click(Edit(id: t.id))]) { text(t.title) }
      el("button", props: [("class", "kill")], on: [on_click(Drop(id: t.id))]) { text("x") }
    }
  }
```

这一页与 `todo.dawn:160-274` 逐条对照，账是这样：

| 项 | 今天 | 路线一 |
|---|---|---|
| 占位 `[]` | 11 | 0（其中大部分由默认参数消掉，与路线无关，§2.2） |
| `view` 里的中间 `let` | 5 个，各带 `: Node[Msg]` 标注 | 0 |
| 列表的循环 | `list.map(visible(m), t => (to_string(t.id), row(m, t)))` | `for t in visible(m) { key(...) { ... } }` |
| `row` 的两臂 | 两个完整 `el("li", ...)` 调用 | 两个完整 `el("li", ...) { ... }` 调用（没变） |
| 「恰好一个节点」 | 类型 | `one(...)` 的 panic |
| 视图函数的返回类型 | `Node[Msg]` | `Unit !Emit` |

**`row` 那一行是这张表里最诚实的一格**：整节点级的二选一在路线一里也没有变短。买到的是根
视图的五个 `let`、`keyed` 的二元组、以及块里那些无 `else` 的 `if`（它们变成普通语句，
不必是元素形式）。

## 7. 影响面清单

**线格式：不动。** 构造在 guest 侧，线上过的是 `enc_node` 编出来的那棵树
（`packages/tea-dom/src/wire.dawn:124`），一个节点是怎么被构造出来的，编码器看不见。
`scripts/wasm-dom-contract` 的两份转录（计数器 120 行、待办 455 行）应当逐字节不变，
这也是这条路线唯一现成的 oracle：**改构造而不改线，是可以被逐字节证明的**
（监听器函数化那一刀就是这么验的，[dom-bridge-design.md](dom-bridge-design.md) §9.2）。

**调和器：不动。** `tea_core/diff` 吃的是 `Tree` 的值（`packages/tea-core/src/diff.dawn`，
704 行），与词汇无关。`tea_core/app.dawn` 的 `trait App` 也不动，前提是 `collect` 纯
（§3.4）。

**会动的：**

| 位置 | 规模 | 动什么 |
|---|---|---|
| 语言（handler 局部状态） | 未估 | §3.8 的第一件，本文不设计 |
| 语言（参数化效果或效果变量上装 handler） | 未估 | §3.8 的第二、三件；不做则每个应用抄一份 DSL |
| `packages/tea-dom/src/dsl.dawn` | 207 行 | 8 个节点构造器改形状或配孪生（§3.7） |
| `packages/tea-term/src/dsl.dawn` | 104 行 | 跟不跟，另裁 |
| `examples/projects/tea_dom_todo{,_keyed}/src/todo.dawn` | 各 472 行，视图段约 115 行 | 视图段重写，测试加收集器一层 |
| `examples/projects/tea_dom_counter/src/counter.dawn` | 149 行 | 同上，量小 |
| `examples/projects/tea_todo/src/todo.dawn` | 视图段约 30 行 | 只在终端词汇跟着分叉时 |
| `packages/tea-dom/src/node.dawn` / `wire.dawn` / `route.dawn` / `reactor.dawn` | 0 | 不动 |
| `scripts/wasm-dom-contract` 的转录 | 0 | 期望逐字节不变，这是验收判据 |

粗量：语言之外约 400 到 500 行改写，其中一半是示例与测试。语言那一件不在这个量级里，
也不该由这份文档估。

## 8. 待裁决

裁决栏留空。每条给出本文的倾向与最强的反对意见。

**问题一：路线二（块产生列表）是否就地关档。**

- 本文倾向：关档，理由在 §4，并写进「不做的（记录理由）」，重开条件是「有人给出一个不依赖
  类型的、块位置上的收集判据」。
- 最强反对：Dart 的 collection-if/collection-for 在真实语言里活着，用户群没有因此读不懂
  代码；本文举的三条都是「规则变复杂」，没有一条是「程序含义不确定」。反驳这条要说清
  「同一个块在两个 callee 下含义不同」到底算不算歧义。

**问题二：handler 局部状态是否立项。**

- 本文倾向：立项，但**不以 UI DSL 为唯一理由**。它在
  [effects-design.md](effects-design.md) §7 已经被 lexer 诊断收集那个探针独立地要过一次，
  两个客户不相干，这比一个客户强。
- 最强反对：它是效果系统的第二个大件，而效果系统刚在 V1′ 之后关账；UI DSL 只是「想要」，
  不是「不做就错」，路线三什么都不欠。而且它一旦落地就要回答「臂能不能捕获、状态是不是每次
  安装一份、逃逸闭包带不带它」，这些在调用点语义下都不是小问题。

**问题三：参数化效果 `effect Emit[T]` 是否随之立项。**

- 本文倾向：不随之。它是另一根轴（[effects-design.md](effects-design.md) §7 开放问题 5
  已经这么裁过），而且「效果变量上装 handler」是更小的一刀，同样能让词汇住回
  `packages/tea-dom`。
- 最强反对：「效果变量上装 handler」听起来小，实际要回答「装在一个还没定下来是哪个效果的
  变量上，减的是哪个标签」，这可能比参数化效果更难。两者的代价没有量过。

**问题四：如果一、二、三都不做，`dsl.dawn` 要不要就地吃掉默认参数。**

- 本文倾向：要，它与三条路线全都正交，只消 §2.2 第一条（11 个占位 `[]`），
  探针 P7 已验今天编得过。
- 最强反对：`el` 的四个位置实参今天读起来是「标签、属性、监听、子节点」四栏对齐，
  改成具名之后短调用变短、长调用变长；这是排版偏好，归人不归机器
  （[dom-bridge-design.md](dom-bridge-design.md) 的克制风格同源）。

**问题五：验收 oracle 认不认「转录逐字节不变」。**

- 本文倾向：认，且把它当作路线一唯一的硬判据（§7）。
- 最强反对：转录只覆盖两个应用走到的路径，`keyed-ops.sh` / `payload.sh` / `props.sh` 三套
  存在正是因为转录看不见它们（[dom-bridge-design.md](dom-bridge-design.md) §8）。
  构造方式换了，「转录没变」可能只是说明这条路径没被驱动到，
  这正是「门禁的绿没有信息量」那一类。

## 9. 机器验过的探针

探针在 `dawn.toml`（`schema = 1` + `name`）+ `src/main.dawn` 的最小项目里跑，
编译器 v0.69.0（`./bin/dawn`，基线 `6e0fb63`）。

| # | 问的是 | 结果 |
|---|---|---|
| P1 | 收集型 handler（`var acc` + 臂赋值） | 3 条错误，逐字抄在 §3.1 |
| P2 | `effect Emit[T]` | `an effect cannot declare type parameters` |
| P3 | `with handle e`（效果变量） | `expected the effect to handle ..., found e` |
| P4 | Java 可变累积器（`StringBuilder`，`Int` 载荷） | 编过、跑过、打印 `1` |
| P4b | 同上换成 `Node` 载荷 | `no overload of ArrayList.add matches (Node)` |
| P5 | `el(tag, cls: ..., body: ... = () => ())` + 尾块 + 块里 `if` 无 `else` | 编过、跑过 |
| P6 | §6 整页（`collect` 打桩） | `dawn check` 答 `ok` |
| P6′ | `column { text("a") \n text("b") }`（`text` 返回 `Node`） | `this Node value is discarded` |
| P7 | 默认值的类型提到函数自己的类型参数（`on: List[On[M]] = []`） | 编过、跑过 |
| P8 | `impl App` 的 `view` 写 `!io` | `view is declared !io but trait App declares it pure` |
| P9 | 尾块返回列表（`body: fn() -> List[Node]`）+ 元素形式 | 编过、跑过，3 个子节点 |
| P9′ | 尾块填非函数形参（`kids: List[Node]`） | `expected List[Node], got fn() -> List[Node]` |

**没有验过的**：路线一的运行期行为。`collect` 在今天的语言里写不出来（§3.1），
所以「emit 出来的顺序就是子节点的顺序」「嵌套容器各收各的」这两条只有类型级的证据，
没有执行级的。这是本文最大的一处欠账，也是它不给结论的一部分原因。
