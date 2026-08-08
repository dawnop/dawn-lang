# 具名实参与默认参数 — 设计 — #207

> 状态：current —— 已评审通过（用户终裁 2026-08-08，见 §9），按 §8 的刀法落地。
> 勘察基线 `main = 50252e8`，落地基线 `103ed87`（其间只有三个 formatter 提交）。
> 全部实测跑在 `./bin/dawn run`。对应 #207（K5），来自 #198 UI DSL dogfood 勘察的
> 卡壳表：「无默认参数，9 选项组件的调用点不可读」。与 **#206 尾块语法**只有一处
> 接触面（§5），本文给出双方一致的方案。

---

## 1. 问题

Dawn 之前没有默认参数，也不让普通函数收具名实参。两条合起来，一个有 5 个以上可选项的
函数在调用点是不可读的。#198 用一个 9 选项的 Button 组件量过：

```dawn
ButtonA("Continue", () => {}, true, Named("white"), Rgb(0,90,200), 16, Center, 240, 8)
```

**4 个参数是分水岭**：到 5 个要数逗号，到 9 个必须回看声明。而且加一个选项要改所有调用点。

之前的最优变通是 config record + 函数式更新：

```dawn
ButtonB("Continue", () => {}, ButtonStyle { ..button_default(), width: 240 })
```

它已经**是默认参数的手工版**——`{ ..base, field: v }` 就是「缺省值 + 覆盖」。代价是每个
组件多一个类型加一个 default 函数，而且选项被硬切成「位置的」和「样式的」两等公民。

这不只是 UI 的事。`backend-dawn` 里同样的形状到处都是（分页参数、超时、重试次数），
之前一律靠位置传或者多一个 config record。

### 1.1 改动前的报错（实测）

```
$ ./bin/dawn run p_named_fn.dawn
error: `add` is a function, not a constructor; function calls do not take argument names
  = hint: only constructor calls take argument names, as in `Rect(2.0, h: 3.0)`
```

```
$ ./bin/dawn run p7.dawn        # fn f(a: Int, b: Int = 2) -> Int = a + b
error: expected `)`, found `=`
```

两条都拒得干净，语法空间是空的。

---

## 2. 现状勘察：已经有什么

这一节全是实测与 file:line，不是推断。**结论是：这个特性缺的东西比想象的少得多。**

### 2.1 语法早就通了

`arg = [ IDENT ":" ] expr` 在**每个调用位置**都合法，2026-07-31 起（`docs/grammar.ebnf`、
`spec.md` §4.3）。`scripts/grammar-corpus/accept/expr_forms.dawn:32-38` 已经把这件事钉住了：

```dawn
let on_a_function = add(a: 1)(2)
let on_a_dot_call = xs.at(i: 0)
let on_an_applied_result = add(1)(b: 2)
```

语料只跑 `dawn __parse`（`scripts/grammar-corpus/README.md`），所以这些行只证明**能解析**。
「哪个 callee 接受具名实参」是**类型判定**，不是语法判定。

**所以 §3 这一半是纯 checker 改动，parser 一行不动。**

### 2.2 形参名早就在 `Sig` 里，而且早就跨模块

`Sig` 第三个字段就是 `param_names: List[String]`（`selfhost/src/check/types.dawn:685`）。
它在三处被填：顶层 fn（`passes.dawn:1995`）、trait 方法（`passes.dawn:1178`）、
effect operation（`passes.dawn:1010`）。

`ModExports.fns: Map[String, Sig]`（`cx.dawn:303`）**原样搬 `Sig`，不做裁剪**
（`exports_of`，`checker.dawn:8421`/`8517`）。所以形参名跨模块已经通了。

之前它只被用来渲染：`sig_render`（`types.dawn:952-978`）服务于诊断、`dawn doc`
（`doc.dawn:276`）、LSP hover/completion（`lspc.dawn:323`）。

### 2.3 分派规则早就写好了，而且是共享的

`ctor_slots(fields, names) -> List[SlotPick]`（`types.dawn:482-512`）已经把「哪个实参填哪个槽」
这个决定收成一份，构造调用（`checker.dawn:5436`）和构造模式（`checker.dawn:2146`）共用它。
它答的是五种结果：`SlotAt` / `SlotNoField` / `SlotAfterNamed` / `SlotOverflow` / `SlotTaken`。

它的文档注释自己写着「One rule, two spellings」，并且记着两份副本曾经漂移过。
**推广到函数调用就是第三种拼写，不是第四条规则**——刀 0 把它泛化成
`arg_slots(param_names, given)`，`ctor_slots` 变薄包装。

### 2.4 调用检查有两条路，只有一条能拿到名字

`check_call`（`checker.dawn:4864`）进门就分岔（`checker.dawn:4876-4884`）：

| 路 | 何时走 | 拿到什么 | 有形参名吗 |
|---|---|---|---|
| **A** 函数值 | callee 是局部绑定/形参 | `TyFn(params, ret, eff)` | **没有**（`types.dawn:261`） |
| **B** 具名签名 | 顶层 fn / 模块函数 / UFCS / trait 方法 / effect op | `Sig` | **有** |

路 A 还没有两轮推断、没有泛型实例化；路 B 有。

这条分岔**不是为本特性造的**，它已经在那儿了，而且它恰好就是本特性的天然边界：
**具名实参在路 B 可用，在路 A 不可用。**

`docs/audit/application-syntax-design.md:149` 已经把这条裁过：

> **不给函数类型加参数名**（从而支持函数值的 named argument）。那会让 `fn(Int) -> Int` 和
> `fn(x: Int) -> Int` 变成两个类型还是一个类型，是类型系统的问题，范围完全不同。

本文**沿用这条裁决，不重开**。

### 2.5 拒绝点只有两个

- `reject_named_args`（`checker.dawn:4259`），`check_apply` 在 `checker.dawn:4342` 调它——
  **在 `arg_exprs` 丢名之前**（`checker.dawn:4346`）。
- `reject_named_method_args`（`checker.dawn:4283`），`check_method_call` 在 `checker.dawn:6410` 调它。

改这两处的条件，就是 §3 的全部。

### 2.6 编译模型：整程序、单进程、每次从源码

`analyze_program`（`driver/analyze.dawn:1019-1084`）按依赖序把每个模块解析 + 检查一遍；
std 也是每次从内嵌源码重新 check（`driver/stdlib.dawn:169-220`）；依赖包是源码分发。
**没有磁盘上的签名摘要，没有已检查 IR 的缓存**（`pkg/` 缓存的是 Maven jar 与 manifest）。

`CheckedMod.m: Module`（`analyze.dawn:994`）保着每个模块的完整 AST，整个 codegen 期间都活着。

这条事实**直接杀死 §4 的一整类顾虑**：「改了默认值要不要重编调用方」在 Dawn 里不成立，
因为每次都重编。Scala 的 `f$default$2`、Kotlin 的 bitmask 蹦床，它们各自要买的那个
「二进制兼容」属性，Dawn 一分钱都不需要付。

### 2.7 后端：调用就是直接调用

- JVM：普通函数 = 模块类上的 `public static` 方法，**名字原样不 mangle**
  （`jvm/emit.dawn:1414`、flags `emit.dawn:1132`）。跨模块 = `invokestatic`
  （`emit.dawn:1544-1554`），descriptor 从整程序表 `prog_fns` 取（`main.dawn:306-335`）。
  `pub` 与私有**不体现在字节码里，全是 `ACC_PUBLIC`**。
- native：`dawn_<owner>__<name>` 直接 C 调用（`c/emitc.dawn:263`、`1099-1101`），整程序一个编译单元。
- 函数值：`let g = f` 已经会合成一个 `lambda$N` 转发器 + 零捕获闭包
  （`lift_fn_value`，`ir/lower.dawn:2389-2422`）。

### 2.8 合成函数的先例已经有三层

- **lowering 合成具名顶层函数**，按名字去重，追加进模块函数表，之后后端分辨不出来：
  `struct_rel_fn`（`lower.dawn:1327-1391`），三个用户 `structeq$…` / `structcmp$…` / `structhash$…`。
  `lower_module_full`（`lower.dawn:3448-3451`）自己写着「从这里起它们就是普通顶层函数」。
- `lambda$N` 转发器（`lower.dawn:2172`）。
- 后端级：字典类、trait 接口、闭包类、`dawn$test$N`。

标识符词法是 `[a-z][a-z0-9_]*`（`grammar.ebnf:22`），**`$` 用户写不出来**，合成名不会撞。

### 2.9 一笔已裁的语义债：构造器具名实参曾按**声明顺序**求值

```dawn
type R = { a: Int, b: Int }
let r = R { b: tap("written-1st (fills b)", 1), a: tap("written-2nd (fills a)", 2) }
```

改动前实际输出：

```
written-2nd (fills a)
written-1st (fills b)
```

ADT 构造器同样（探针 `p12.dawn`）。原因在 `lower_ctor`（`ir/lower.dawn:2737-2790`）：
`XCtor` 带 `written`（源序）与 `slots`（字段序 → 源序下标），
`for s in slots` 那个循环直接**按字段序** lower，注释写着「backends need no reordering」。

`docs/spec.md` 之前没有一句关于实参求值顺序的规定。这与 Python / C# / Scala / Swift /
Kotlin 全部相反（那些都是写序）。构造器字段带副作用的少，所以一直没人踩到；**函数实参带
副作用的多**，推广具名实参就会把它推到台前。

**终裁：改成写序，并同批修构造器（§9 裁决 1）。** 这是本批唯一的 Emit-Change。

---

## 3. 方案一：具名实参推广到普通函数

### 3.1 规则

**一句话：`Sig` 支持的 callee 接受具名实参，`TyFn` 支持的不接受。**

具体：

| callee | 接受具名实参 | 名字来自 |
|---|---|---|
| 顶层函数 `f(a: 1)` | ✅ | 该函数的 `Sig.param_names` |
| 模块限定 `m.f(a: 1)` | ✅ | 同上（`check_module_call`，`checker.dawn:6329`） |
| UFCS / 点调用 `x.f(a: 1)` | ✅ | 同上（`check_method_call` 尾部，`checker.dawn:6549`） |
| 管道 `x \|> f(a: 1)` | ✅ | 同上（parser 已把 `x` 前置成 `pos_arg`，`parser.dawn:1264`） |
| trait 方法 `x.area(scale: 3)` | ✅ | **trait 声明的**形参名（见 §3.5） |
| effect operation `get(key: "a")` | ✅ | effect 声明的形参名 |
| 构造器 `R(b: 1)` | ✅（原有） | 字段名 |
| 函数值 `g(a: 1)`、`f(1)(b: 2)` | ❌ | —— |
| Java 成员 `o.m(a: 1)` | ❌ | Java 元数据里没有形参名（见 §3.6） |

分派规则**一字不改**地复用 §2.3 的那份：位置前缀从左到右占槽，具名按名占槽，
具名之间任意重排，**位置实参不得跟在具名实参之后**（`SlotAfterNamed` 保留，理由见 §5）。
重名 → `SlotTaken`，未知名 → `SlotNoField` 走 `suggest.hint` 出拼写建议。

**接收者不可具名。** `x.f(self: y)` 里 `self` 已被接收者按位置填掉，`arg_slots` 直接答
`SlotTaken` → 「参数 `self` 被传了两次」。免费得到，不必写新规则。

### 3.2 落地点

| 文件 | 改什么 |
|---|---|
| `check/types.dawn` | `ctor_slots` 的循环泛化成 `arg_slots(names: List[String], given: List[Option[String]])`；`ctor_slots(fields, …)` 变成薄包装 |
| `check/checker.dawn` | `reject_named_args` 只对「callee 是表达式（函数值应用）」的路保留（改词）；`check_call` 收 `List[Arg]`，路 B 用 `arg_slots` 定槽、路 A 与 Java 改词继续拒 |
| `check/checker.dawn` | `reject_named_method_args` 撤下，`check_method_call` 把 `List[Arg]` 传进各分支：模块调用与 UFCS 放行，Java 与 fn 字段仍拒 |
| `check/checker.dawn` | 路 B 的实参循环从「位置 zip」改成「先 `arg_slots` 定槽，再两轮检查」——形状照抄 `check_ctor_call`（`checker.dawn:5428-5504`） |
| `check/checker.dawn` | 四条诊断改词（见 §3.3） |
| `docs/spec.md` §4.3 | 改写具名实参段落 |
| `docs/spec.en.md` | 同步（含「No default arguments」行，已因本批过期） |

**求值顺序的落点（裁决 1 的函数侧）**：名字在 checker 里消解成槽位后，`XCallFn.args`
仍按**声明序**排列、恰好 `len(param_tys)` 长——Core IR 与两个后端零改动。写序语义由
checker 兑现：**只在写序≠声明序时**，在调用节点外套一层块（临时变量按写序 `TSLet`，
调用节点的实参引用这些临时变量）；写序==声明序的调用点不套块，产物逐字节不变。
构造器侧对应的落点在 `lower_ctor`（§7.3）。

**`Sig`、`ModExports`、`exports_of`、Core IR、两个后端：零改动。**

### 3.3 诊断

之前四条消息全部以「不是构造器」为理由，推广之后这个理由错了，必须重写：

| 场景 | 之前 | 改成 |
|---|---|---|
| 函数值 `g(a: 1)` | ``\`g\` is a function, not a constructor; …`` | ``\`g\` is a function value, and a function type carries no parameter names`` + hint「按位置传」 |
| `f(1)(b: 2)` | `this callee is a function value, …` | 同上（无名可引） |
| Java `o.m(a: 1)` | ``\`X.Y\` is a Java member, …`` | ``Java methods carry no parameter names`` + hint「按位置传」 |
| 未知名 | ——（新增） | 复用构造器那条的形状：``\`f\` has no parameter \`xx\``` + `suggest.hint` |

「一次调用只报一次」这条现有纪律（`checker.dawn:4249-4258` 的注释）保留。

### 3.4 与 `f(a)(b)` 的关系

Dawn 没有柯里化，`f(1)(2)` 的语义是「`f(1)` 的结果必须是函数」
（`spec.md` §4.3、`application-syntax-design.md:154`）。

所以问题不存在：**第一次应用可以具名（callee 是 `Sig`），第二次不行（callee 是值）。**
这不是妥协，是同一条规则的直接推论，而且诊断能把理由说清楚。

### 3.5 trait 方法：名字取自声明，impl 随便改

**实测（`p10.dawn`）：impl 可以任意改形参名，零诊断。**

impl 比对只看类型列表与返回类型（`passes.dawn:1656`）加效果 subsumption（`passes.dawn:1661`），
从不比名字。

**std 里现成的反例，而且比预想的糟**：prelude `Iter` 声明 `iter_done` 的形参名是
`["c", "k"]`（`types.dawn:1214-1216`）——`c` 是**接收者**，`k` 是游标。
五个实现（`std/list.dawn:41`、`str.dawn:338`、`bytes.dawn:357`、`map.dawn:134`、`set.dawn:90`）
全部把接收者叫 `xs`/`s`/`b`/`m`，把**游标**叫 `c`。

于是照 §3.1 的规则，`xs.iter_done(c: 3)` 里的 `c` 指的是**接收者**，而接收者已被点调用填掉，
报的是「参数 `c` 被传了两次」。这是 §6.4 那笔审计（刀 4，另立）存在的理由。

裁决：**名字取自 trait 声明，impl 的形参名纯属局部，不加新检查。**

- 这是字典传递下唯一健全的答案：调用点看到的是 trait 的 `Sig`（`passes.dawn:1197` 把它
  `bind_fn` 进函数命名空间），impl 静态未知。
- 与 Rust 同（trait 方法形参名只是文档，impl 可改名）。Swift 要求 label 一致，但 Swift 的
  label 本来就是签名的一部分（§6.2）。
- **不加「impl 应与 trait 同名」的检查**：那会当场把 std 的三处 `iter_done` 判红，
  而它们改名是有理由的。Dawn 没有 warning 通道，所以是「error 或什么都不做」二选一——
  选什么都不做。
- **代价必须写下来**：`bytes.iter_done(c: 3)` 里的 `c` 指的是 trait 的第 1 个形参
  （即接收者），不是 impl 的第 2 个。这会误导。缓解只能靠 §6.4 的一次性 API 审计。

### 3.6 Java FFI：明确不做

Java 反射拿的是 `getParameterTypes()` 不是 `getParameters()`（`jvm/jreflect.dawn:147`），
`JMethod` 只有 `param_cls: List[String]`（`jsig.dawn:16`）。要拿到 Java 形参名需要目标 jar
用 `-parameters` 编译（绝大多数没有）或读 debug 信息 LVT。**不做**，诊断照 §3.3 改词说明理由。

---

## 4. 方案二：默认参数

### 4.1 语法

```
param = IDENT ":" type_expr [ "=" expr ] ;
```

```dawn
fn column(kids: List[Widget], align: Align = Start, gap: Int = 0) -> Widget = …

column(kids)
column(kids, gap: 12)
column(kids, align: Center, gap: 12)
```

之前 `fn f(a: Int, b: Int = 2)` 报 `expected \`)\`, found \`=\``（实测），语法空间是空的。

`Param` 加一个字段（`front/ast.dawn:35`）：

```dawn
pub type Param = { name: String, tref: TypeRef, default: Option[Expr], lo: Int, hi: Int }
```

**默认值不必在参数表尾部。** `fn f(a: Int = 1, b: Int)` 合法，只是调用时 `a` 只能具名传
（因为位置前缀是从左到右占的，跳不过去）。不为此加限制：限制要多一条规则，而收益只有
「防止作者写出难用的签名」——那不是编译器的活。

### 4.2 求值时机与环境

**每次调用求值一次，在声明处的作用域里。**

- **每次求值**，不是一次求值后共享。这直接躲开 Python 的 `def f(x=[])` 那个著名陷阱
  （Dawn 的值本来就不可变，但 `List` 字面量每次新建仍然是更容易解释的语义）。
- **在声明处的作用域**：默认值表达式可以引用被调方模块的私有函数与 `const`，
  不能引用调用方的任何东西。这是唯一说得通的读法——作者写下 `= DEFAULT_GAP` 时想的是
  自己模块里那个常量。
- **实现即语义**：默认值表达式在一个**不含本函数形参**的作用域里检查（§4.4 的合成函数
  就是零元的），所以「引用其他形参」自然报 `undefined variable`——不是额外检查，
  是作用域结构使然。

### 4.3 纯性与效果

**默认值表达式必须是纯的（不带任何效果行，`!io` 与具名效果都不行）。**

理由是类型面，不是实现：如果默认值能带效果，那么

```dawn
fn f(a: Int, b: Int = read_config()) -> Int !io
```

的效果行就会随「调用方有没有传 `b`」而变——同一个函数两个效果行。要么恒定按最坏情况算
（那 `f(1, 2)` 也白背一个 `!io`），要么让签名依赖调用点（那不是类型系统）。两条都不能要。

**起步再收窄一档**：默认值表达式的类型**不得提及本函数的类型参数**（实现为：形参的声明
类型提及本函数 tparam 即拒），且**不得引用其他形参**（§4.2 末条，作用域结构使然）。

- 不提及类型参数：否则默认值的 `TExpr` 里会带声明处的类型变量，跨调用点要做替换。
  挡住它，`fn join[T](xs: List[T], sep: String = ", ")` 这种真实用例照样成立。
- 不引用其他形参：`fn f(a: Int, b: Int = a * 2)` 把默认值从「一个常量表达式」
  变成「一个依赖调用点的函数」（OCaml 与 Scala 都为此付过设计代价）。
- **这两条以后放宽都不是破坏性变更**，先不做。

允许：字面量、`const`、纯函数调用（含本模块私有的）、构造器、`comptime` 块。
不允许：`!io`、具名效果、Java 调用（`unsafe_pure` 包着的除外，那已经是纯的了）、
引用其他形参、形参类型提及本函数的 tparam。

由于默认值必须纯，**默认值之间、默认值与写出的实参之间的求值顺序不可观测**——
裁决 1 的「写序」只须对写出的实参成立。

### 4.4 ABI：合成零元函数（路 B），合成点在 checker

对每个带默认值的形参 k，在**声明所在模块**合成一个零元纯顶层函数：

```
<fn_name>$default$<k>() -> <param_ty>
```

调用点缺该实参时，checker 在该槽位填一个对它的普通调用节点；发射出来就是
JVM 一条 `invokestatic` / native 一次直接 C 调用（两边 JIT/`-O2` 都会内联零元纯函数）。

**合成点选在 checker（`check_module`，TFun 层）而不是草案原拟的 lowering
（`struct_rel_fn` 机制）**，因为 TFun 层是三个消费者共同的上游：

- comptime 解释器按名找 `TFun`（`ir/interp.dawn:137/1758`，`icx.fns` 由 `tm.fns` 构建）——
  lowering 层合成的它看不见，const 初始化式里省缺实参的调用会找不到函数；
- JVM 的跨模块 descriptor 表 `prog_fns` 与 native 的 `program_tables` 是两个 driver
  各建一份（`main.dawn:306-335`、`c/cdriver.dawn:53`），合成的 `Sig` 要进这两张表，
  从 `TModule` 出发两边可以共用一个助手；
- lowering / 两个后端把追加进 `tm.fns` 的合成 TFun 当普通顶层函数，零改动——
  这正是 `struct_rel_fn` 注释里「从这里起它们就是普通顶层函数」的同一条性质，
  只是提前一层拿到。

合成由**声明**驱动，不由调用点驱动：每个带默认值的形参恒定合成一个，与调用方无关，
确定性、无跨模块顺序依赖。未被用到的那些是死码（Dawn 本来就不 tree-shake，整程序发射）。
命名不会撞：`$` 不在标识符词法里（`grammar.ebnf:22`）。

#### 明确不做的两条

- **合成重载**（Kotlin `@JvmOverloads` 那套）：Dawn 没有重载，做这个要引进 mangle + 按元数分派，
  而分派本来就在 checker 里做完了。而且 `@JvmOverloads` 的历史教训正好是反面教材——
  在中间加一个带默认值的形参，已编译的二进制调用点会静默改绑。
- **bitmask 蹦床**（Kotlin 真正用的那套）：它买的是「一个符号搞定所有形参组合」的二进制兼容，
  Dawn 每次整程序从源码编（§2.6），这个属性一分钱不值；而代价是每次调用多一个 Int 参数加
  每形参一次分支。一个 10 选项的组件调用要跑 10 次分支，正好是 UI 场景最不能付的。
- 草案还评估过**调用点展开**（把默认值的 `TExpr` 搬进每个调用点）：要求跨模块搬运
  per-module 符号 id 与字典/证据装配，三类工程风险全在它那边，且默认值表达式被复制进
  每个调用点。弃。

### 4.5 arity 检查改区间

路 B（`Sig`）的 arity 检查改成区间：`min_arity = 无默认值的形参数`（注意不是「前缀」，
因为默认值可以不在尾部），`max_arity = len(param_tys)`。诊断要能说出区间：
``\`f\` takes 1 to 3 argument(s), got 4``；`min == max` 时措辞与原来逐字相同（存量零差异）。
实参数在区间内但必填形参没被填上（具名跳过了它）→ 缺参诊断，形状同构造器的
`missing field(s)`。

路 A（`TyFn`）与匿名 callee 的 arity 检查**不动**——函数类型不带默认值，理由同 §2.4。

**由此得到一条必须写进 spec 的规则**：把一个有默认值的函数当函数值用（`let g = f`），
`g` 的类型是全参的 `fn(A, B, C) -> R`，默认值丢失。这与「构造器裸名当函数值时字段名丢失」
（`spec.md` §2.3）是同一条纪律的延伸，不是新概念。

### 4.6 范围：只给顶层函数

| 目标 | v1 支持默认值 | 理由 |
|---|---|---|
| 顶层 fn（含私有、模块函数） | ✅ | 主场景 |
| 局部 `fn` 语句 | ❌（勘察修正） | 草案误记为「同一条 param_list」。实际上局部 fn 的形参是 `LambdaParam`（`parser.dawn:1121-1129` 自己的循环，不走 `typed_params`），对它的调用走路 A（`resolve_local` → `XCallDyn`，callee 是 `TyFn`）——无 `Sig` 可挂默认值。给一条针对性 parse 错误 |
| lambda | ❌ | lambda 参数连类型注解都是可选的；默认值要挂在 `TyFn` 上才有意义，而那条已裁掉（§2.4） |
| 构造器字段 | ❌（见 §10） | record 的 `{ ..default(), x: v }` 已经在做这件事，且更灵活 |
| **trait 方法** | ❌ | 默认值该归 trait 声明还是 impl？字典传递下 impl 静态未知，只能归 trait；但那样 impl 就无法覆盖默认值。而 Dawn 已经有一个叫「default」的东西（trait 的默认方法体，`CDefault`），两个 default 挤在一个特性里是自找的混乱。**等到有第二个消费者再说**。impl 方法同拒（对 trait `Sig` 的调用永远用不上它） |
| **effect operation** | ❌ | operation 的调用是「读证据记录的字段 + 调闭包」（`checker.dawn:5121` 的 `op_of` 分叉），没有可挂 `$default$k` 的符号；handler 臂的元数也要跟着变。同样等消费者 |
| Java 方法 | ❌ | 没有形参名，更没有默认值 |

trait 方法与 effect op **收具名实参（§3）但不收默认值**——这两件事可以分开，因为具名实参
纯粹是 checker 里的槽位分派，而默认值要落一个符号。

---

## 5. 与 #206 尾块的接触面（唯一一处）

#206 需要 `f(a, align: Center) { ... }` 成立。这在之前是硬错，**而且不用等裸 `{}`，
现有的 `fn` 尾闭包就已经踩上了**（实测 `p3.dawn`）：

```dawn
let b = Box(n: 1) fn() => 7
error: positional arguments cannot follow named arguments
```

裁决取 **(ii) 尾块按名绑最后一个形参**（弃 (i) 全局放宽「位置实参不得跟在具名实参后」——
五门参照语言没有一门放宽它，见 §11）：

尾闭包/尾块**不是「写在具名实参之后的位置实参」**，它是 desugar 追加的一个实参；
让 desugar 追加**具名**的那一个：

```dawn
f(a, align: Center) { body }
  ⇝  f(a, align: Center, body: <closure>)      # body = 最后一个形参的名字
```

于是「位置不得跟具名后」原封不动，整条链上不需要任何豁免。

规则细则：

- **callee 有 `Sig`**（路 B）→ 按最后一个形参的**名字**追加。
- **callee 是函数值**（路 A，无名可引）→ 按位置追加。这与 §3 一致：路 A 上根本不可能有具名
  实参，所以「位置跟在具名后」不会发生，不产生冲突。
- **最后一个形参已被具名占掉** → `SlotTaken` → 「参数 `body` 被传了两次」。免费拿到。
- **构造器同理**：`Box(n: 1) fn() => 7` desugar 成 `Box(n: 1, f: <closure>)`，当场就通。

**依赖关系**：(ii) 要求「具名实参能落在函数上」先成立，也就是 **#207 是 #206 这一半的前置**。
两份设计各自成文，接口就是这一句：*尾块在 callee 有 `Sig` 时按最后一个形参名绑定，
否则按位置绑定*。

---

## 6. API 演进语义

### 6.1 加一个带默认值的形参，是不是破坏性变更

分三种位置答，不是一个答案：

| 改动 | 位置调用点 | 具名调用点 |
|---|---|---|
| 在**尾部**加一个带默认值的形参 | 不破坏 | 不破坏 |
| 在**中间**加一个带默认值的形参 | **破坏**（后续位置实参整体错位） | 不破坏 |
| 在**头部**加一个带默认值的形参 | **破坏** | 不破坏 |
| 改一个默认值的**值** | **静默改变行为** | **静默改变行为** |
| 给一个已有形参**加**默认值 | 不破坏 | 不破坏 |
| 把一个默认值**去掉** | 破坏（少传的调用点报 arity） | 破坏 |
| **给形参改名** | 不破坏 | **破坏** |

中间/头部插入在类型不同时会被 arity 或类型错抓住，**类型相同时不会**。
**这条不需要语言机制去防，需要写进文档**：库作者只在尾部加带默认值的形参。
「改默认值的值 = 静默行为变更」这一条与 C++/C#/Scala/Kotlin 全部相同，无解，写下来即可。

### 6.2 形参名从此进入公共 API：单层名（裁决 2）

**终裁：单层（Kotlin / Scala / Python / OCaml 路线）**——形参名既是外部标签又是内部变量名。
理由见 §9 裁决 2；Swift 双层标签的正反面对照保留在 §11。

### 6.3 形参名进公共 API 的连锁：`dawn doc` 与 LSP 已经在展示它了

`sig_render`（`types.dawn:952-978`）是诊断、`dawn doc` 与 LSP **唯一**的签名渲染器，
它一直就把形参名印出来。所以「形参名是不是公共的」这件事在**文档层面已经既成事实**，
本特性只是把它变成**可执行的**。

`sig_render` 要跟着加默认值的渲染，这是 §8 刀 3。**落地修正**：渲染成
`gap: Int = ...` 而不是带值的 `= 0`——`Sig` 不携带默认值表达式（它是合成函数的
函数体），`Cx` 也不存模块源文本可切；调用方需要从签名读到的是「这个实参可省略」。
要印出值就得把源文本穿进 passes，另立后批再议。

### 6.4 一次性代价：std 的形参名从此是 API

std 有几百个 pub 函数，形参名从没按「会被调用方写出来」的标准审过。已经找到的坏例子是
`Iter`（§3.5）。修法是改 trait 声明（`c`→接收者名、`k`→`c`），不是改 impl。

这是一笔真实的、必须单独排的活（§8 刀 4），**不能塞进落地那一刀**：它是 API 面变更，
要单独发布（裁决 4），而且 CONTRIBUTING §七的「命名族准入判据」正是给它用的尺子。

---

## 7. 破坏面、期数与种子纪律

### 7.1 具名实参（§3）：纯放宽

- **改动前能编译的程序，改动后全部照旧编译，语义逐字节相同。**改动只把一批**之前被拒**
  的程序变成被接受。
- `scripts/grammar-corpus/` 只跑 `dawn __parse`，完全不受影响。
- 受影响的是诊断文本：`checker.dawn:6866`/`6890` 两条内联 test 断言了旧措辞，跟着改。
- **`Emit-Change`：无**（前提是不在同一刀里 dogfood，见 §7.4）。

### 7.2 默认参数（§4）：语法是纯增量，合成由声明驱动

- 语法：`= expr` 在形参表里之前是硬语法错（实测），空间是空的 → 纯增量。
- 每个带默认值的形参合成一个函数；存量代码一个默认值都没有 → 合成零个 →
  **存量语料逐字节零差异**。
- 所以 `Emit-Change` 同样是**无**，只要这一刀不改 std、不 dogfood（裁决 4 保证了这一点）。

### 7.3 求值顺序（裁决 1）：唯一的 Emit-Change

构造器的 lowering 要变。把爆炸半径收窄的办法：**只在调用真的发生重排时才引入临时变量**
（即具名实参落槽的字段序下标序列不是递增的）。全部按声明序写的调用点照旧逐字节发射，
差异被限制在真正重排的那些点上。

- 构造器侧落点：`lower_ctor`——重排时写出的实参按写序 `CSLet` 进临时变量，
  `CCtor` 按字段序引用它们；spread base 在语法上只能写在最前，之前就先求值，与写序一致。
- 函数侧落点：checker（§3.2）——同一条「非重排零差异」纪律。
- 落地时**测量**：数一遍 selfhost + std + packages + backend-dawn 里「具名实参顺序与
  声明顺序不一致」的构造调用有多少个，逐站点核对行为。这是刀 0 的一项产出，不是估计。
- **实测**（基线 103ed87）：selfhost **31 处**（`Cx`/`Frame`/`W` 的 spread 更新与散记录
  字面量，实参全部纯——run-diff 全绿证实行为零变化）、`examples/data/shapes.dawn` 2 处
  （纯字面量）、std / site / playground / packages / **backend-dawn 0 处**。
  唯一移动的标签是 `emit selfhost`。文本扫描初版漏掉了字段间夹注释的记录字面量
  （`Cx` 全军覆没），core-golden 的逐模块对账才是把它揪出来的 ground truth——
  「门禁的绿没有信息量」的又一实例，这次绿的是自制测量脚本。

### 7.3.1 落地时挖出的第三个站点：C 后端本身

两后端对拍语料里一直没有「一个调用带两个有副作用实参」的程序，于是一条**存量分歧**
藏到了本批：JVM 从左到右求值实参，C 后端把实参表达式内联进 C 调用表达式，而 C 不规定
实参求值顺序——gcc/x86-64 实际**从右到左**。裁决 1 把写序定为规范后这就是 conformance
bug，而且与具名实参无关：纯位置调用就踩（基线编译器复现实测）。

修法 `emitc.emit_ordered`：一个节点带两个以上**非原子**操作数时，逐个按写序绑进临时
变量（不足两个时逐字节照旧发射；字典表达式不跑可观察代码、且其 C 类型与 Core 携带的
类型变量类型不一致，留在原位）；`&&`/`||` 的短路降级为 if 不受影响。覆盖
`emit_call`（含 CDynamic 目标 / CMethod 字典先于实参，对齐 JVM）、`emit_intrinsic`、
`emit_alloc` 与 `emit_binary` 的全部严格臂。钉住它的是
`scripts/spike-native/eval_order.dawn`（位置实参）与 `named_args.dawn`
（具名重排 + 构造器 + 管道），双后端 + ASan。

### 7.4 种子纪律

编译器自己的源码**在落地这一批里不使用新语法**，那么种子编译器不需要认识它 → **零种子轮**。

Dogfood（编译器自身、std、backend-dawn 用上具名实参与默认值）是**另一刀、另一次发布**
（裁决 4），走标准的「三期两发布」：期 1 加特性发布 → 推种子 → 期 2 迁移调用点。
这与 v0.42/v0.43 的箭头 lambda 迁移是同一套流程，已经跑过两遍。

`backend-dawn` 升钉是再下一步，与本文无关。

---

## 8. 刀法与 oracle

四刀本批（0/1/2/3），两刀另立（4/5）。

### 刀 0 —— 分派规则泛化 + 求值顺序改写序（裁决 1 的构造器侧）

- `ctor_slots(fields, names)` 的循环泛化成
  `arg_slots(param_names: List[String], given: List[Option[String]])`，`ctor_slots` 变薄包装。
- `lower_ctor` 改写序：只在重排调用点引临时变量（§7.3）。
- 数一遍存量语料里「具名实参顺序 ≠ 声明顺序」的构造调用（含 backend-dawn），
  作为 Emit-Change 声明的测量依据。
- **oracle**：`types.dawn:2105-2122` 那批内联 test 全绿且**一行不改**；
  非重排调用点产物逐字节零差异（`selfhost-prev-diff` + core-golden 逐条目对账）；
  重排调用点的差异逐个解释；新增 run 语料钉住写序。
- **负控**：把 `arg_slots` 里的 `saw_named` 强制成 `false`，必须有 test 变红；
  把「取第一个同名形参」改成「取最后一个」，必须有 test 变红（这一条之前测不出来——
  两份副本曾在这点上漂移而无人发现——补一个 `arg_slots` 直接测重名表的 test）。

### 刀 1 —— 具名实参推广到 `Sig` 支持的 callee

- `check_call` 收 `List[Arg]`；路 B 用 `arg_slots` 定槽；路 A 与 Java 改词继续拒；
  重排调用点由 checker 套块兑现写序（§3.2）。
- 四条诊断按 §3.3 重写；`checker.dawn:6866`/`6890` 两条内联 test 跟改。
- spec §4.3、`spec.en.md` 同批改。
- **oracle**：
  - 新增内联 test 覆盖：重排、混用位置+具名、重名（`SlotTaken`）、未知名（含 `suggest.hint`
    建议）、位置跟在具名后仍拒、UFCS 具名、管道具名、接收者被具名（应报 given twice）、
    trait 方法具名（用 trait 声明的名）、effect op 具名、函数值具名仍拒、Java 具名仍拒。
  - `scripts/selfhost-prev-diff.sh` **逐字节零差异**（编译器自身没用新语法）。
  - `run-diff` / `fmt-diff` / `lsp-diff` 全绿——这三个是独立标签，`doc --builtins` 是第四个。
  - grammar corpus 不受影响（parse-only），**别把它当本刀的证据**：「能解析」与
    「类型检查通过」是两个事实，这个语料只证明前一个。

### 刀 2 —— 默认参数（parser + checker 合成）

- `Param.default: Option[Expr]`；parser 的 `typed_params` 加 `[ "=" expr ]`；
  局部 fn 形参给针对性 parse 错误；trait 方法 / effect op / impl 方法在 passes 拒。
- `Sig` 加 `param_defaults`；三条约束（纯性 / tparam / 引用其他形参）的检查与诊断。
- arity 检查改区间（§4.5）；缺槽填 `f$default$k` 调用。
- `check_module` 合成零元 TFun；两个 driver 的程序表加合成 `Sig`（§4.4）。
- **oracle**：
  - 存量语料**逐字节零差异**（零个默认值 → 零个合成函数）。这是本刀最重要的一条。
  - 新增 run 语料：默认值被用/被覆盖、非尾部默认值、默认值调私有函数、默认值是 `comptime`、
    默认值每次调用新建（用一个可辨识的 `List` 观察）。
  - **两后端对拍**：同一段程序 JVM 与 native 输出一致（合成函数在两边都是普通函数，
    这条应当免费通过——如果不通过，说明 §4.4 的判断错了，及早发现）。
  - 三条约束各配一个 reject 用例（带效果的默认值 / 形参类型提及 tparam / 引用其他形参），
    每个钉住诊断文本。
  - **负控**：把纯性检查注释掉，那三个 reject 用例必须至少一个变红。

### 刀 3 —— 渲染面（诊断 / doc / LSP / fmt）

- `sig_render` 出默认值（`gap: Int = 0`）；`dawn doc` 与 LSP 自动跟随（同一个渲染器）。
- `dawn fmt` 对 `= expr` 的排版（fmt 的缩进是词法级启发式，新语法要单独验，而且
  **本仓全过 `--check` 只证明它自洽**，要拿仓外写法试）。
- **oracle**：受影响标签各自声明 `Emit-Change`（这一刀是**故意**改输出的，逐 label 写，
  不用通配——CONTRIBUTING §五）；范围以实测为准。**实测为空集**：四个差分标签与
  `doc --builtins` 全部零差异（存量语料没有默认值，渲染分支走不到）；唯一移动的是
  checker-corpus 里默认值案例的 signature hint，`--record` 重录。

### 刀 4（另立，另发布）—— std 形参名审计

按 §6.4。对着 CONTRIBUTING §七的准入判据过一遍 std 的 pub 函数形参名，改名是破坏性变更，
必须单独发一版并在 release note 里列全。

### 刀 5（另立，另发布）—— dogfood

按 §7.4 的三期两发布。第一个消费者建议是 backend-dawn 而不是编译器自身：
它的调用点更像真实业务代码，能更早暴露人体工学问题，而且不牵动种子。

---

## 9. 裁决（用户终裁 2026-08-08，不重开）

草案在此处列过四条待裁两难，逐条裁定如下。

### 裁决 1 —— 实参求值顺序：**写序**，同批修构造器

构造器之前按**声明序**求值（§2.9 实测），spec 一个字没写，且与 Python / C# / Scala /
Swift / Kotlin 全部相反。推广具名实参到函数会把这条没记过账的语义债推到台前——函数实参
带副作用远比构造器字段常见。

**裁定：改成写序，构造器同批修。** 理由：这条债已经存在且没被记录，本特性是把它暴露出来
的那个事件；趁有人在看的时候关掉，比留着等某个人某天调试半天要便宜。「代码按你读的顺序跑」
与 Dawn「一行一语句」是同一条纪律。

这是本批**唯一预期的 Emit-Change**。半径收窄：只在写序≠声明序时引临时变量，
写序==声明序的调用点产物**必须逐字节不变**（§7.3）。

### 裁决 2 —— 形参名的公共性：**单层名**（Kotlin/Scala 路线，不做 Swift 双层标签）

**裁定：单层。** 理由：

- 构造器字段名已经是单层的先例——字段名就是公共 API，没人为此付两层的税；
  双层意味着构造器与函数在同一件事上两套写法。
- Swift 双层的收益依赖「标签默认必填」，而 Dawn 不可能默认必填（会破坏现存全部调用点）；
  「可选的双层标签」拿到的是 Swift 一半的收益和全部的复杂度。
- 后悔药是便宜的：`fn move(to dst: P)` 这条语法空着，将来要加是**纯增量**，
  不需要破坏窗口。这与 #178 的裁法同调。

同时**不做位置专用标记**（Python 的 `/`、Swift 的 `_`）：只有库作者会用、且很容易用错；
真要控制这件事，靠 §6.4 的审计。

代价（认下）：`list.map(xs, f)` 的 `f`、`str.split(s, sep)` 的 `sep` 从此永久是 API，
而这些名字从没按 API 标准审过——刀 4 的活由此而来。

### 裁决 3 —— 默认值表达式的能力：**任意纯表达式**（不限 comptime），调用时求值

**裁定：纯表达式。** 理由：`comptime` 的可序列化约束（spec §7.2）挡住 `Map`/`Set`/函数值，
而 UI 组件的默认回调 `= () => ()` 恰好是函数值，直接落在禁区里——对 #198 的原始场景是
致命的。`= Rgb(0, 90, 200)`、`= new_empty_style()` 这类真实默认值要能写。

代价（认下）：每次省缺调用多一次零元纯函数调用（JIT/`-O2` 会内联，但不是字面的零）。

### 裁决 4 —— std 采用：**不同批**（刀 4 / 刀 5 另立另发布）

**裁定：分开。** 理由：「门禁的绿没有信息量」那条教训说的正是这个——
「存量零默认值 → 零合成函数 → 产物逐字节零差异」是本批能拿到的最强 oracle，
不该为了早几天的便利换掉；形参名审计（§6.4）也需要时间做对。

代价（认下）：特性落地后一段时间里没有真实用户，人体工学问题晚暴露——由刀 5 的
dogfood（首选 backend-dawn）尽快补上。

---

## 10. 不做的（记录理由）

- **不给函数类型加形参名。** 沿用 `application-syntax-design.md:149` 的裁决，不重开：
  那会让 `fn(Int) -> Int` 与 `fn(x: Int) -> Int` 变成一个还是两个类型，范围完全不同。
  代价是函数值上不能具名（§3.4），而这个代价换来的是路 A/路 B 那条**已经存在**的分岔
  正好就是特性边界，一条新规则都不用加。
- **不做偏应用/柯里化。** `spec.md` §4.3 已裁。`f(a: 1)(b: 2)` 里第二次应用不具名，
  不是妥协是推论。
- **不放宽「位置实参不得跟在具名实参之后」。** §5 的方案 (ii) 让尾块**按名**绑定，
  于是根本不需要豁免。放宽的收益只有「少一条规则」，代价是 `f(b: 2, 1)` 这种调用点合法化。
- **不给构造器字段加默认值。** record 的 `{ ..default(), x: v }`（实测可用）已经在做这件事，
  而且更灵活——它能一次覆盖任意子集，而默认值只能一个一个给。ADT 构造器有默认值还会与
  模式匹配的元数打架（模式里那些槽是不能省的）。两件事不合并。
- **不做位置专用标记**（Python 的 `/`、Swift 的 `_`）。见裁决 2。
- **不检查 impl 形参名与 trait 一致。** §3.5：会当场判红 std 里五处有正当理由的改名；
  Dawn **没有 warning 通道**，所以只能 error 或不做，选不做。真正该做的是把 trait 声明的
  名字改对（§6.4 刀 4）。
- **不给 trait 方法与 effect operation 加默认值（v1）。** §4.6 各自的理由。
  具名实参照给，两件事分开。
- **不给局部 fn 加默认值（v1）。** §4.6 勘察修正：它的调用走路 A，无 `Sig` 可挂。
- **不合成重载、不做 bitmask 蹦床、不做调用点展开。** §4.4。
- **不为 Java 方法读 `-parameters` / LVT 拿形参名。** §3.6。

---

## 11. 先例：五门语言各自付了什么代价

| 语言 | 具名实参 | 默认值的 ABI | 本文取了什么 / 避了什么 |
|---|---|---|---|
| **Swift** | argument label 与 parameter name **两层**，label **默认必填**，`_` 关闭 | 编译期，跨模块靠 `.swiftmodule` 带表达式 | **不取双层**（裁决 2）：它的收益依赖「默认必填」，而 Dawn 不可能默认必填 |
| **Kotlin** | 具名 + 默认，位置实参原则上不得跟在具名后（有一条极少人记得的例外） | 真正的实现是合成 `f$default(…, mask: Int)` **蹦床**；`@JvmOverloads` 只是 Java 互操作层 | **避开两者**（§4.4）：蹦床买的二进制兼容 Dawn 不需要；`@JvmOverloads` 的教训正是「中间插形参会静默改绑」 |
| **Scala** | 具名 + 默认 | 合成 `f$default$k` **取值方法**，一个形参一个 | **取这条**（§4.4），因为它把表达式留在声明模块里，不用跨模块搬已检查的树 |
| **Python** | 关键字实参 + `/` 位置专用 + `*` 关键字专用 | 默认值**在定义时求值一次并共享** → `def f(x=[])` 陷阱 | **反着做**（§4.2）：每次调用求值。不做 `/`（裁决 2） |
| **OCaml** | `~label` 标签实参，可省略、可重排 | 默认值 `?(x = e)` 与 option 类型缠在一起 | **不取**：OCaml 的标签参与类型推断，产生了一整类「标签推不出来」的坑；Dawn 把名字挡在 `TyFn` 之外（§2.4）正是为了不进这个门 |

一条横向观察：**这五门里没有一门放宽「位置实参不得跟在具名实参之后」**。§5 的方案 (ii)
（尾块按名绑定）让 Dawn 也不必放宽，这是它比 (i) 好的第二个理由。

---

## 12. 一页速查

| 问题 | 答案 |
|---|---|
| parser 要改吗 | §3 不改（语法早就通了）；§4 改一处（`typed_params` 加 `[ "=" expr ]`）+ 局部 fn 一条针对性拒绝 |
| `Sig` / `ModExports` 要改吗 | §3 零改动（`param_names` 早就在，且跨模块）；§4 加一个 `param_defaults` |
| Core IR / 后端要改吗 | 零改动；重排调用点的写序由 checker 套块（函数）与 `lower_ctor` 临时变量（构造器）兑现 |
| 谁能收具名实参 | 有 `Sig` 的 callee：顶层 fn / 模块函数 / UFCS / 管道 / trait 方法 / effect op / 构造器 |
| 谁不能 | 函数值、`f(a)(b)` 的第二次应用、Java 方法 |
| 谁能有默认值 | 顶层 fn（含私有、模块函数）。局部 fn、trait 方法、effect op、lambda、构造器都不 |
| 默认值在哪求值 | 每次调用，在声明处的作用域（无形参在内），必须纯 |
| 实参求值顺序 | **写序**（裁决 1）；重排才引临时变量，非重排逐字节不变 |
| 与 #206 的接口 | 尾块在 callee 有 `Sig` 时**按最后一个形参名**绑定，否则按位置绑定；「位置不得跟具名后」不放宽 |
| 破坏面 | 纯放宽 + 一条已裁的 Emit-Change（求值顺序，仅重排调用点） |
| 种子轮 | 落地零轮；dogfood 另立（裁决 4），走三期两发布 |
| 刀数 | 本批 4（0/1/2/3）+ 2 另立（std 审计、dogfood） |
