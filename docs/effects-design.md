# 效果处理器（尾恢复档）设计 — 用户具名效果 + `with handle`

> 状态：**historical**（已实施：任务 #110 批 1，2026-08-01）。四项塑形裁决由用户于 2026-08-01 定案（见 §2）；
> 本文把裁决展开成可实施的设计。勘察基线 v0.43.0（67a91a5）；文中 file:line 均对该提交。
> 落地后的**权威条文在 [spec.md](spec.md) §6.5**，教程见 [tutorial.md](tutorial.md) §17；
> 本文自此是设计记录，不再随实现更新。
>
> 实施时与本文有两处出入，均为本文内部矛盾所迫：
> 1. **标签的拼写是效果自己的名字**（`effect Ask` → `!Ask`）。§3.2 的例子写 `!ask`，
>    同一节又规定「`!name` 先查作用域内的 effect 声明」——两者不能同时成立。
>    parser 因此接受 `!` 后的 TYPEIDENT；大写却查不到的原子报错，不再铸成效果变量。
> 2. **多个 `!` 组可叠写**（`!Ask !io`），§3.2 的例子需要它，旧产生式只认一组。
>
> 另有一处本文未预支付、实施时定下的边界：**签名的效果不再推断出标签**。
> 未标注返回类型的函数封签时只留基轴——证据参数由**写出来的**签名合成，
> 事后才冒出来的标签没有参数可走（每个这样的标签在发出处已经报过错）。
>
> 本文的代码块都是**提案语法**，未标 `dawn compile`——doc-check 不会编译它们。
>
> **2026-08-24 补记**（正文一字未改，设计文档是历史记录）：具名效果这一档还在，但本文
> 描述的**词法/创建点**语义已被 2026-08 的 V1′ 证据包路线翻转。今天的做法是：函数值的类型
> 带着完整的效果行，效果在**调用点**应答，`with handle` 是全语言唯一能从行里减去一个标签的
> 节点，逃逸的闭包不带走创建点的 handler。被翻转的是 §4.4 的「handler 是创建点的」、§4.6 的
> 创建点结算，以及 §4.5 末条「写出来的函数类型不许带标签」（今天任何 `TypeRef` 位置都可以写）。
> 同批转为历史的还有 [effects-soundness-design.md](effects-soundness-design.md)。
> **当前权威仍是 [spec.md](spec.md) §6.5**，证据包的机制在该节末尾的「实现（信息性）」。

## 1. 目标与非目标

**目标**：让用户声明自己的效果（一组操作签名），在调用处直接调操作，由词法上最近的
`with handle` 应答。效果进类型：一个函数会发出哪些具名效果，签名里写得出、编译器算得出、
没人应答时报得出。

**档位 = 尾恢复（tail-resumptive）**：handler 臂就是「就地调用、返回值即操作结果」的
普通闭包。这一档在两个后端都是一次普通调用——JVM 一次 `INVOKEINTERFACE`，
C 一次 `dawn_clo` 间接调用，**不需要延续捕获、不碰 Perceus 的 dup/drop 调度表、
comptime 解释器也能执行**（`ceval` 不做蹦床的裁决不受影响）。
Haskell 的 `effectful` 生态整个跑在这一档上（abort 用真异常），是「这档单独就有用」的
存在性证明；Koka 里它是覆盖常见情形的最重要优化，在这里它是全部。

**非目标**（v1 明确不做，都有归处）：

- **非尾恢复 / 多次恢复**：需要延续捕获（OCaml 5 的 fiber/分段栈、WasmFX 的栈切换），
  与 C 后端的 Perceus + 单栈模型正面冲突（perceus-design §5.5 的平衡检查假设控制流
  正常返回）。远期若做，CSProtect 图纸（core-move2-design §2.3 的不变量 I1–I4）是
  诚实的成本起点。
- **aborting handler**（操作不返回调用点）：那是失败机制的形状，Dawn 已有
  `catch_fault`/`catch_panic`/`bracket`。「异常式效果」映射到既有屏障族，不给 handler
  加逃逸档——`effectful` 同款取舍。
- **参数化效果**（`effect Yield[T]`）：把 `Ty` 塞进 `Eff` 会让 subst 的类型/效果双 map
  互递归、`Map[Eff, …]` 的键全动。**另立项**（原先记作「留给 RX-10 期权 B」，那是错的：
  B 是把 `Eff` 塞进类型参数表，方向相反，见 §7 开放项 5 与
  [effect-params-design.md](effect-params-design.md)）；v1 要泛型就在声明处具体化。
- **重写 std**：io 不改写成用户效果（那是重写 checker 脊柱），panic 不改写成 aborting
  handler（上一条）。本特性是纯加法。

## 2. 裁决记录（2026-08-01，用户定案）

| # | 问题 | 裁决 |
|---|------|------|
| D1 | 效果名住哪 | **新 `effect` 声明**——第三种具名声明形式。不复用 trait（撞「纯或 io / 单 tparam / 禁效果变量」三面墙，checker.dawn:1975-2011）；不用裸行标签（op 无家可归，且与「非 io 原子=新效果变量」的现行解析规则相撞） |
| D2 | 参数化 | **v1 裸标签**。`!ask` 无类型参数，op 签名写死在声明里 |
| D3 | 与 `!io` 的关系 | **第二轴**。具名效果是效果行里独立于 io/效果变量的新分量；io 的吸收推理零变动，具名效果精确保留、绝不被吸收 |
| D4 | handler 形态 | **语法形式**。`with handle E { … }` 子句点名效果，checker 在此做「行减 E」。跨语言规律背书：有行多态才能把 handler 类型化成一等值（Koka/Unison），无行多态的语言走语法形式（Flix）或二等能力（Effekt）——Dawn 无行多态 |
| D5 | 证据怎么传 | **字典轨式隐藏参数**（立项时已定向）。但见 §5：证据不复用 CDict 节点，而是普通记录——字典轨被当作「按固定序附加隐藏尾参」的**约定**复用，不是节点复用 |

## 3. 表面语法

### 3.1 效果声明

```dawn
effect Ask {
  ## 向上下文要一个 Int。
  fn ask() -> Int
}

effect State {
  fn get() -> Int
  fn put(v: Int) -> Unit
}
```

- `effect` 是新关键字（实施前先 grep 全语料确认无标识符冲突；破坏窗口尚热，直接保留字）。
- 操作是普通函数签名，**自身不得再带效果注记**——操作的效果就是它所属的效果本身；
  handler 臂的身体做了什么 io，记在装 handler 的那个块头上（§4.3），不记在操作签名上。
- 操作名进入模块命名空间，与普通函数同池：`use m.{ask}` 选择性引入、模块限定 `m.ask(…)`
  都照旧。一个模块内操作名与函数名同名同池冲突，照常报重定义。
- v1 不允许 `effect` 带类型参数（D2）。

### 3.2 操作调用与签名拼写

```dawn
fn sum_three() -> Int !ask =
  ask() + ask() + ask()

fn logged(x: Int) -> Int !ask !io = {
  io.println("asking")
  ask() + x
}
```

- 调用处就是普通调用；效果 `!ask` 出现在签名的效果位，与 `!io`、效果变量 `!e` 并列，
  可叠写多个。
- **`!name` 的判别规则**：`resolve_eff`（checker.dawn:342-349）现在把任何非 io 原子铸成
  新鲜效果变量。新规则是**先查作用域内的 effect 声明**：`name` 命中已声明效果（含 `use`
  引入的）→ 具名效果标签；未命中 → 仍是效果变量（现行为）。效果名首字母大写、
  效果变量惯用单小写字母，实践上不混；判别是 checker 级的，parser 不变。
  实施前 grep 语料里所有 `!<ident>`，确认没有既有效果变量恰好与将来会 `use` 进来的
  效果同名的隐患面。

### 3.3 `with handle`

```dawn
fn main() -> Unit !io = {
  with handle Ask { ask() => 42 }
  io.println("${sum_three()}")      # 126
}
```

多操作、多行臂、嵌套：

```dawn
fn demo() -> Int = {
  var s = 0
  with handle State {
    get() => s
    put(v) => { s = v }             # 臂是闭包：v1 里不能写外层 var——见 §7 开放问题 1
  }
  with handle Ask { ask() => get() + 1 }
  put(41)
  ask()
}
```

- `with handle E { 臂… }` 是 `with` 语句的新子句形态：**块的剩余部分**在该 handler 的
  作用域内，这与 v0.40.0 的 `with x <- f(…)` 完全同构（parser.dawn:1900-1917 的
  块剩余闭包化直接复用），也继承它的全部纪律：只在块内合法、剩余部分是真闭包、
  `return`/`break`/`continue` 被拒（诊断文案点名 `with handle`）、`?` 透明穿过（§4.5）。
- 臂形如 `op(参数…) => 表达式`，`=>` 与 lambda 同记号（臂本来就是闭包）；臂之间换行分隔。
  每个声明的操作**恰好一臂**，少臂、多臂、臂名不属于该效果都是编译错误。
- 嵌套 handler 就是嵌套 `with`：内层先生效（innermost wins），词法作用域（§4.4）。
- handler 一个效果一装；同一效果在同块重复 `handle` 是内层遮蔽外层，合法（同名变量遮蔽同款）。
- 允许 handle 一个块内实际没发出的效果（无害的死证据，Koka 同款放行）。

## 4. 类型规则（第二轴的落法）

### 4.1 表示：labels 进 `Eff` 的规范形

D3 的「第二轴」不落在 `TyFn`/`Sig` 加新字段上，而是落在 `Eff` 的规范形里加一个分量：

```
今天：Eff = EPure | EIo | EffVar(name, id) | EUnion(vars)      # types.dawn:25-30
提案：规范形 = (base, labels)
       base   ∈ { pure, io, vars(排序去重), io 吸收 vars 后的 io }   # 即今天的四构造
       labels = 具名效果 id 的排序集合（新分量）
```

- **io 的吸收规则只作用于 base 分量**：`eff_union` 里 io 吸收变量（types.dawn:43）照旧；
  **labels 绝不被吸收、绝不近似**——证据合成（§5）要按 label 精确开参数，吸收即击穿。
- `eff_subsumes`：base 部分照旧（io 是顶、pure 是底），labels 部分是集合包含。
  `!io` 的函数**不能**免签发出具名效果——这是 D3 裁决的实质。
- **效果变量横跨两轴**：`!e` 的实例化可以携带 labels（`map(xs, x => ask())` 里 list.map 的
  `!e` 实例化成 `(pure, {ask})`）。这是必须的：`for` 循环脱糖走 std/list 的游标函数，
  高阶传播若不带 labels，循环体里发效果直接死路。subst_eff（types.dawn:346-362）改成
  按规范形逐分量代换。
- 触及面（备忘录已点）：`eff_union`/`lub_eff`/`eff_subsumes`/`subst_eff`/渲染
  （types.dawn:41-116, 346-362），以及 `Eff` 作 Map 键的三处（checker.dawn:125-126,
  4543, 4563）——`Eq`/`Hash[Eff]` 随规范形扩展。每一刀都是加分量，不改既有分量的语义；
  labels 为空时全套行为与今天逐字节相同（这是实施的门禁判据：**存量语料零 Emit-Change**）。
- spec §6.1 的「格子只有两点，求解就是布尔或」（spec.md:849-853）修订为：
  base 轴仍是两点布尔或；labels 轴是有限集合并/差，仍平凡可判定。

### 4.2 传播

操作调用给当前函数体记一笔 `(pure, {该效果})`（record_effect 通路，checker.dawn:323-331）；
签名声明了该 label 则通过，没声明则与今天漏报 `!io` 同款报错：

```
sum_three uses the effect `ask`, but its signature does not declare `!ask`
  hint: add `!ask`, or answer it here with `with handle Ask { ... }`
```

**只有 `pub fn main` 的 labels 必须为空**——它没有调用者提供证据，「没人应答」的错误落在它的
签名上，与效果变量今天的落点一致。导出边界不在此列：普通 `pub fn` 携带公开具名效果正是
`pub effect` 的用途，调用方可以继续传播或安装 handler；公开面上被拒的是**私有**效果，那条
规则归 SEM-07 的导出面校验（`docs/public-surface-design.md` §六，spec §3.3 / §6.5）。

### 4.3 「行减 E」——`with handle` 的类型规则

> **本节的论断已被推翻（#188，2026-08-08）。** 保留原文与推翻的理由；现行条文见
> §4.6 与 [effects-soundness-design.md](effects-soundness-design.md)。

原设计：设块剩余闭包推得效果 `(base, L)`，handler 臂们的身体推得效果 `(base_i, L_i)`：

```
with handle E { 臂… } 之后，装 handler 的这个块记账：
    (base ∪ ⋃base_i,  (L ∖ {E}) ∪ ⋃L_i)
```

- 减法只减 `E` 自己；臂身体自己发的效果（含 io、含别的 label、含 `E` 自己——臂里再发
  本效果走**外层** handler，见 §4.4）全部并回块头上。
- 这条规则是 D4 选语法形式的全部回报：`handle E` 三个字让 checker 静态知道减哪个。
  今天的 `unify_eff` 三态（纯收纯 / io 收一切 / 变量累积 LUB，checker.dawn:1024-1038）
  不需要「减法」构造——减法只发生在这一个语法节点上，不进 unification。

**为什么错。** 减法在**消费方**（装 handler 的块），捕获在**生产方**（造闭包的那一点）。
两者不同点，于是 A 在自己的 handler 里造一个带 io 臂的闭包传出去，B 再装一个纯 handler
把标签合法减掉、调用那个闭包——跑的是 A 的 io 臂，B 的类型却是纯的。减法减对了标签，
减错了人。修法是把减法搬到捕获那一点（§4.6），`with handle` 这个节点自此不做减法。

### 4.4 词法作用域语义

证据按**词法**解析（§5）：操作调用绑定到词法上最近的 `with handle`，闭包在创建点
捕获当时的证据。推论：

- 逃逸闭包 well-defined：在 `handle` 块内建的闭包带着该 handler 逃出块外再被调用，
  仍由原 handler 应答——尾恢复档下 handler 就是一段普通代码，没有栈魔法可失效。
  这是 Effekt 的词法 handler 语义；Effekt 用二等能力禁逃逸来保安全，Dawn 不需要禁：
  没有延续，逃逸没有不健全面，只有语义选择。spec 条文要把这条写明白
  （「handler 是创建点的，不是调用点的」）。
  （原文此处还说逃逸闭包的**类型仍写着 `!E`**、调用它的地方仍要认下这个标签。
  这半句已推翻：逃逸闭包的类型写的是它捕获的那些臂的效果，见 §4.6。well-defined
  的论证本身不受影响。）
- 臂身体里发**本效果**，绑定到**外层**的同效果 handler（自己不应答自己，与 Koka 一致）；
  没有外层就是臂签名欠 label，正常报。

### 4.5 与既有机制的交互

- **`?` 传播**：操作调用就是普通调用，返回 `Option`/`Result` 的操作照常接 `?`。
  臂身体里的 `?`：臂是闭包，遵守 lambda 现规——`?` 的货币必须在臂内自洽
  （臂的返回类型是操作声明的返回类型，不是 `Result`，所以臂里的 `?` 必须内部消化，
  否则照常报「`?` 的载体类型不符」）。
- **`return`/`break`/`continue`**：块剩余闭包内照拒（with 糖现规，checker.dawn:3355+），
  臂身体内同拒（同一条规则，臂也是 sugar 闭包）；两处诊断都点名 `with handle`。
- **trait/impl 方法**：**行是完整的行**（RX-10-B 刀 5 已落地；刀 4 先放行了效果变量）。
  标签与关联效果投影都可以写：标签在槽位上是一格类型精确的证据参数，投影是一格擦除的
  （规则丙，[effect-params-design.md](effect-params-design.md) 决策 5）。两处标签拒绝
  已随刀 5 删除；一致性检查把 trait 的行经 impl 的 `effect E = !X` 绑定归约后与 impl 的
  行比较，基轴按包含、标签轴恰相等——每个标签是一格隐藏证据参数，是方法的元数。
- **comptime / const**：v1 一律拒绝具名效果（`leave_isolated` 通路加 labels 检查，
  checker.dawn:4580-4589）。「handler 是纯的就该放行」是真问题，但把「纯 handler」
  判据做对需要臂效果的组合推理，v1 不背——今天的「否」从偶然变成裁决，留档重开。
- **`unsafe_pure`**：只遮 io（现语义），**不遮 labels**——labels 是证据合成的输入，
  遮了就断参数。措辞不用改（它本来就只说 io）。
- **类型声明位**：效果位在类型声明里的拒绝（RX-10 期权 A，checker.dawn:361-416）
  对 labels 同拒同 hint——函数**类型**（`fn(Int) -> Int !ask` 作字段/别名目标）里
  出现 label 与效果变量同罪。这意味着 v1 里**带 label 的闭包不能存进记录字段**——
  与「效果变量不进类型声明」同一条既有边界，不新开。
  （#188 把这条推广到**任何写出来的函数类型**，见下一条；同时「带 label 的闭包不能
  存进记录字段」不再成立——闭包的行已在创建点结算，存得进去了。）
- **写出来的函数类型**（#188 追加的第五条拒绝）：任何 `TypeRef` 位置的
  `fn(…) -> T !E` 都不合法，不限于类型声明位——参数、返回、`let` 注解、泛型实参、
  元组元素同拒。理由与「函数值不能带 label」同宗：证据是隐藏参数，只由闭包在创建点
  捕获，从不由调用方供，所以「写出来的标签」没有对应的运行时含义。迁移写法是效果变量。
  函数自己的签名行不是 `TypeRef`，不受影响。

### 4.6 创建点结算（#188 追加，取代 §4.3）

lambda 收工时结算自己的行：体内每一次证据解析都已记下是谁应答的，于是

- 解析到**本函数体内 `with handle`** 的证据 → 该标签从行里去掉，并把该 handler
  **各臂的效果并进行**。臂是被捕获的证据记录的字段，调用闭包就会跑它们，所以它们
  发生在闭包被调用时，属于闭包的行。
- 解析到**签名的隐藏参数**、或经函数值调用 / 效果变量实例化而来的标签 → 留在行里。
- **部分结算取保守**：同一个标签既有本地 handler 又有别的来源时，整条留着。别的来源
  仍由别人的臂应答，结算掉会把它交给错的 handler。过近似永远安全。

判据挂在**每一次证据解析**上，不是收工时对行做一次事后查询。反例：一个闭包只调用
另一个带标签的闭包、自己一次证据都没解析过，事后查询会在作用域里找到一个碰巧同名的
本地 handler 并把它结算成纯的。逐条推导见
[effects-soundness-design.md](effects-soundness-design.md) §5.3。

于是「行失去一个成员」在全语言只发生在**闭包创建点**这一个节点——也就是证据被捕获的
那一点。减法与捕获同点，就不可能减错人。

## 5. 证据传递与 lowering（零新 Core 节点）

### 5.1 证据就是普通记录

每个 `effect E` 让 lowering 合成一个**普通记录类型**（对用户不可见、不可拼写，
命名走 `ev$E` 之类的合成名，与 `structeq$Adt…` 同池）：

```dawn
# 合成物示意（用户拼不出这个名字）
type ev$Ask = { ask: fn() -> Int }
type ev$State = { get: fn() -> Int, put: fn(Int) -> Unit }
```

- **刻意不复用 CDict**：字典是账本外的无头静态表（`dictish` 在 rc.dawn:531-539，
  它的注释在 :528-530；types.dawn:343-347 是同一条规则从类型侧看的样子），
  而 handler 臂是捕获局部的真闭包，必须进 RC 账本。备忘录 §1.5.2 的裁决在此落地：
  证据是普通值，走普通记录 + 普通闭包的全部既有通路——**两个后端、interp、Perceus
  一行都不用改**。「字典轨」被复用的是它的调用约定（隐藏尾参、固定序），不是它的表示。
- **不复用 CDict 还有第二条独立理由：参数化字典永活。** `dawn_dict_new`
  （runtime/c/dawn_rt.c:195）在运行期分配一个带实参的字典，同处注释（:176-180）写明它
  lives forever，并用 `DAWN_LSAN_OWN`（:181-193）对它 `__lsan_ignore_object`；
  [perceus-design.md](perceus-design.md) 的「字典不加头」一段（:176-183）把「`dawn_dict_new`
  造出来的参数化字典会泄漏」写成契约而非待办。证据一旦进字典的 `args`，它捕获的那些局部
  就跟着永久泄漏。第三条更硬：`args` 的元素类型是 `struct dawn_dict *`
  （runtime/c/dawn_rt.h:271），结构上放不下一个 ADT。
- **「两个后端、interp、Perceus 一行都不用改」在规则丙下仍然成立，加一条限定**：Perceus
  与 interp 确实一行不动，两个后端要动的只有**描述符**（JVM 的接口与槽位签名加宽、C 的
  槽位 cast 形状加宽），而擦除的那一格在 JVM 是 `Ljava/lang/Object;`、在 native 是
  `void*`，两处都是既有形状。规则丙的条文与代价见
  [effect-params-design.md](effect-params-design.md) 的决策 5（已裁，2026-08-19）。
- 由此 D11 的判据（core-move2-design §「受保护区间恒为一次闭包调用→运行时原语零
  Core 节点」）以更强形式成立：连运行时原语都不需要，纯 lowering。

### 5.2 lowering 四步

1. **参数合成**：函数签名 labels 非空 → 在字典参数之后按效果 id 升序追加隐藏证据参数
   （`bind_dicts`/`dict_sym_list` 的并行物，读 `Sig` 的 labels 而不是 tparams；
   调用处附加物同序，lower.dawn:2361-2371 的约定照搬）。自尾调不重传（同 :2354-2357）。
2. **操作调用改写**：`ask()` → `ev.ask()`——从词法环境解析 `ev`：最近的 `with handle Ask`
   绑定 > 本函数的隐藏证据参数。就是一次字段取用 + 闭包调用，SYN 统一后缀节点现成。
3. **`with handle` 脱糖**：构造证据记录（臂 → 记录字段的闭包字面量），把块剩余闭包
   照 v0.40.0 with 的既有通路调用，证据入词法环境供步 2/步 1 的调用处解析。
4. **效果变量实例化携带 labels**：调用处给 `!e` 代入 `(base, L)` 时，被调方按其签名的
   label 集合要证据——高阶场景（map 收 `!ask` 闭包）中 map 自己不发 `ask`、只是转手
   调闭包，闭包自带证据（闭包捕获，§4.4），**map 不需要证据参数**。规则：证据参数
   按签名里**字面写出的** labels 合成，外加行里写出的每个关联效果投影一格（擦除，
   规则丙）；经变量流进来的 labels 由闭包捕获自理。
   这条让高阶库函数零改动，是词法语义的直接红利。

### 5.3 可见性与门禁

- 合成记录第一天进 `coredump.dawn`（CDictDef 有 dump 面的同款要求）——
  semantics-closure-design §「表的写入者错了而读者没错」的教训：新证据表必须
  从第一天起被 Core golden 盯住。
- 差分语料：spike-native 加 handler 语料（单效果 / 多操作 / 嵌套遮蔽 / 逃逸闭包 /
  经 map 的高阶传播 / 臂里发外层效果），双后端对拍。
- grammar-corpus：accept（声明、多臂、嵌套、与 `with x <-` 混用）+ reject
  （少臂/多余臂/臂名不属于效果/顶层 `with handle`/`handle` 后不是效果名/
  return 出臂/label 进类型声明位）。

## 6. 分期（自举力学）

种子 v0.43.0 不认识 `effect` / `with handle`，一代滞后照旧：

1. **批 1（本设计的实施批）**：全特性落地——lexer/parser（`effect` 声明、`with handle`
   子句）、Eff 规范形加 labels 分量、传播/减法/四处拒绝、lowering 四步、双后端差分
   语料、spec 新节 + design.md:29 非目标行修订（「完整代数效应」改「非尾恢复档」）、
   tutorial 一节。**selfhost/src 与 std 不得使用新语法**（种子 parse 不了）；parser 的
   内联测试走字符串源码（既有惯例）。存量语料必须零 Emit-Change（labels 空 ⇒ 全套
   行为逐字节同今天，这是 §4.1 承诺的验收判据）；新语料按 prev-diff 实报声明。
2. **发布 v0.44.0 + 种子推进**。
3. **批 2（可选，另行立项）**：编译器/站点内部试点 dogfood（候选：lexer 的
   诊断收集、site 生成器的输出流），用真实使用反哺人体工学；此时才谈 std 是否
   提供任何效果件。

## 7. 开放问题（不阻塞 v1，留档）

1. **臂写外层 `var`**：糖区闭包不能捕获外层 `var`（with 糖现状同款）。`State` 这类
   例子实际要靠「先提函数让它自带累积」的既有变通。真解是可变捕获或 handler 局部
   状态语法（Koka 的 `var` handler 字段）——等 dogfood 疼了再设计。§3.3 的示例
   注释里点名此坑。

   **批 2 dogfood 判词（2026-08-02，v0.44.0 实测）**：疼点已量到边界，但不紧急。
   拿 §6 点名的两个候选各写探针：

   - **收集类站点在尾恢复档不可表达**。lexer 诊断收集的形状（helper 发、驱动循环
     收进 `var diags`）改写成 `effect Emit` 后，臂里 `diags = diags ++ [d]` 被两条
     错误拒绝（不能在 lambda 内赋值 / lambda 按值捕获拒 `var`）。没有变通：臂返回
     `Unit`、语言无 ref cell，逐项重装 handler 是 O(n) 反模式。**lexer 维持现状的
     元组捎带 + 驱动累积，不改写**——那本来就是对的形状。

     另：受同一条按值捕获纪律限制的不止臂。`with handle` 吞掉块的剩余部分，那也是个
     闭包，所以**安装点之前**声明的 `var` 在 `with handle` 之后既不能赋值也不能读
     （安装点之后声明的不受影响），错误消息按被穿过的那一帧点名「`with` 引入的闭包」。
     规范记在 `docs/spec.md` §4.10 与 §6.5。
   - **sink 与 reader 立即顺手**。站点生成器日志流（`say(s) => io.println(…)`，臂做
     io）与环境配置读取（`base() => 100`，嵌套安装在 let 块里）都一次写对，语法
     读感好。但**今天没有一处存量代码值得为此改写**：单 handler + 反正要 io 的
     场合，效果只是加了一层间接。效果真正挣钱要等「同一效果 ≥2 个 handler」
     （生产直写 vs 测试捕获）——而测试捕获=收集=正好卡在本条。环闭合：**第一个
     真实客户到来之前，先要 handler 局部状态**。
   - **人体工学小件**：上述拒绝消息只说 lambda，不点名 handler 臂——with 糖的
     return/break 拒绝有点名 `with` 的先例（v0.40.0），臂里应同样点名。
     **已修（#118）**：捕获类拒绝（赋值外层 `var` / 捕获 `var`）与形参个数不符
     三处，现在按**被穿过的那一帧**点名——臂说「`with handle` 臂」、块剩余说
     「`with` 引入的闭包」、作者真写的 lambda 保持原文案。顺带发现 `with` 糖
     那两处从 v0.40.0 起就漏了（只改了 return/break/`?`），一并补上。

   std 效果件维持「都不」（§2 D8）：两个探针都没有产生 std 应当供件的证据。
2. **handler 字面量值化**：`handle E { … }` 的臂块将来可提取为一等值（本质是那个
   合成记录露头），届时需要给合成记录一个可拼写类型。D4 裁决语法形式时未预支付；
   若 RX-10-B 落地行多态化的效果参数，再评估。
3. **aborting 档**：`effectful` 路线（abort=异常）映射到 Dawn 就是「操作返回
   `Result` + 调用处 `?`」或屏障族——够用性等 dogfood 检验，不够再谈。
4. **comptime 纯 handler 放行**（§4.5）。
5. **参数化效果**：两件事，方向相反，分开立项。**RX-10-B 已全线落地**（2026-08-20，
   五刀收官）：效果变量有了显式绑定者与 `Sig.eparams` 的家，trait/impl 方法的行放开，
   关联效果（trait 体 `effect E`、impl 体 `effect E = !X`、行内投影 `!T.E`）与规则丙的
   证据结算随刀 5 落地，范围与全部决策见
   [effect-params-design.md](effect-params-design.md)。**`effect Yield[T]`** 是把 `Ty` 塞进
   `Eff`（代价见本文第 1 节的非目标行），另一根轴，另立项，与 RX-10-B 无前后置关系。
