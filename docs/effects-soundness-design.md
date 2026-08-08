# 效果 soundness 修复（B 极简）设计 — #188

> 状态：current —— 已评审通过，按 §10 的三刀落地。勘察基线 `abe5105`（main）。
> 本文只回答「怎么修」；「为什么是这个方案」的跨语言调研与两个缺陷的动态复现，
> 见 #188 的验证段与 `docs/codebase-audit-v2/02-types-effects-and-semantics.md`。

## 1. 要修的是什么

两个独立缺陷，都能让 io 在一个**签名声明为纯**的函数里跑起来。

**D1 — 标签轴对函数值调用不设防。** `verify_effects`（checker.dawn:7047）只把
`eff_base(used)` 拿去和 `eff_base(declared)` 比（:7062-7063）。带标签的行确实被记了账
——`XApply` 路径 checker.dawn:4230、`XCallDyn` 路径 :4696 都调 `record_effect`——但
从来没有人核对。具名调用路径不受影响，因为 `evidence_args`（:4905）会在**调用点**
报「没人应答」；经函数值的调用不走那条路，于是标签一路无声。

**D2 — 减标签的人不是应答的人。** 闭包在**创建点**捕获证据（`ev$…` 是普通局部，
checker.dawn:3946-3948 声明，:3952 之后由捕获记账照常带走）。而 `eff_minus`
（:3823，唯一调用点 :3958）是在**消费方**把标签从行里减掉的。于是：A 在
`with handle Leak` 里装一个 `!io` 臂并造出闭包，B 再装一个纯 `Leak` handler、
把标签合法减掉、调用该闭包——跑的是 A 的 io 臂，B 的类型却是纯的。

两者独立：`/tmp/claude-1000/t188/e9_launder_via_handler.dawn` 是一个**不依赖 D1** 的
laundering（转发器自己装 handler，即使 checker 记了标签也会被 `eff_minus` 拿回去）。
两个程序今天都能跑通（2026-08-08 复测，`bin/dawn run` 打出 io 臂的输出）。

顺带记一条**已存在的意外护栏**：`fn h() -> fn() -> Int !Ask = () => ask()`
今天就被拒——`!Ask` 绑到内层函数类型，`h` 自己没有行，于是 `ask()` 找不到证据
（实测 p1）。语法上没有办法给一个返回函数类型的函数写自己的行
（`(fn() -> Int) !io` 被解析成「元素不足的元组」，实测 p5）。这条护栏在本方案的
注解禁令下自然消解，不必单独处理。

## 2. 裁决（用户终裁，不重开）

**B 极简**，三条：

- **①（禁令）** 写出来的函数类型不能带具体具名效果标签。`f: fn() -> Int !Leak` 不合法；
  效果变量 `fn() -> Int !e` 照旧合法；`!io` 照旧合法。
- **②（结算）** 闭包创建点结算：lambda 体内的操作若解析到**本地 `with handle`** 的证据，
  该标签就地从闭包的行里去掉，并把该 handler 各臂的效果并进闭包的行。
- **③（核对）** `verify_effects` 从 `eff_base` 放宽到整行，经函数值的调用把标签也计入并核对。

三条的分工，用一句话说清：**①② 是定理，③ 是断言。** ①② 建立「行里还留着的标签 ⟺
当前函数在签名里认了它」这条不变式（§5），③ 把这条不变式变成机器每次编译都核对的东西。

## 3. 判据：什么算修好了

1. `/tmp/claude-1000/t188/` 下的 laundering 程序全部**编译不过**。逐个复测过今天的状态
   （2026-08-08）：**e1 / e6 / e9 / e15 今天能跑通**，是活的泄漏；**e3 / e14 今天已经被拒**
   （e3 卡在 `argument type mismatch: expected fn() -> Int, got fn() -> Int !Leak`，
   e14 卡在 §1 那条意外护栏），修复后仍被拒，但理由要更准（e3 的闭包行会从 `!Leak`
   变成 `!io`——臂真的会打印，这才是它该被拒的理由）。
2. 存量**被接受**的效果程序全部继续接受：`scripts/spike-native/effect_{handler,lexical}.dawn`、
   `examples/effects/handlers.dawn`、`scripts/checker-corpus/cases/*`、`site/pages/feat_effects.dawn`
   （§7 列出需要迁移写法的 4 处，那 4 处是**注解**，不是行为）。
3. 无 label 的程序逐字节不变——`selfhost/`、`std/`、`backend-dawn/` 里没有一个
   `effect` 声明（已核，§8），所以三条改动的代码路径全部走不到。
4. spec 的纯函数保证（spec.md:951-953）重新成立。

## 4. 规则精确化

### 4.1 ①：注解位禁标签

**落点只有一个**：`cx.dawn:449`，`resolve_type` 的 `TFn` 分支。它先
`resolve_eff_at` 解析效果位，此时 `eff_labels(eff)` 非空即为「写出来的函数类型带标签」，
就地报错。

一个落点覆盖全部位置，因为**所有**写出来的类型都经过 `resolve_type`，且它对
`TTuple`/`TNamed` 的类型实参递归下去：

| 位置 | 覆盖方式 |
|---|---|
| 函数参数类型 | `resolve_type` |
| 函数返回类型 | `resolve_type` |
| lambda 参数注解（`(f: fn() -> Int !Ask) => …`，checker.dawn:3750） | `resolve_type` |
| `let` / `var` 注解 | `resolve_type` |
| `alias` 目标 | `resolve_type`（另有 passes.dawn:316 的语法层先手） |
| record / variant 字段 | 已禁（passes.dawn:316，checker.dawn:7932 钉住） |
| 嵌套（`List[fn() -> Int !Ask]`、元组元素） | `resolve_type` 递归 |
| 泛型实参、`cast` 目标 | 走 `resolve_type` 的同一条路 |

**不被禁的三件**，必须写进诊断 hint，否则这条禁令会读成「具名效果不能出现在类型里」：

- **函数自己的签名行**（`fn one() -> Int !Ask = ask()`）。签名行不是 `TypeRef`：
  `FnDecl` 的 `eff` 是原子列表，由 `resolve_eff`（checker.dawn:177）单独解析，
  根本不经过 `resolve_type`。这是禁令能这么窄的原因。
- **效果变量**（`fn(T) -> U !e`）。`resolve_eff` 的判据是「原子是否解析到已声明的
  effect」，不是拼写；解析成 `EffVar` 就不是 label，放行。
- **`!io`**。base 轴不受影响。

**已存在的同族禁令。** spec.md:1116-1124 的「边界（v1）」里已经有两条同宗的：
类型声明位（alias / 字段）禁标签，以及带标签的具名函数不能当值传
（`check_fn_value`，checker.dawn:2552，标签分支 :2564-2575）。后者的理由写在代码注释里
——「证据是隐藏参数，函数值没地方放它」——**①是把同一条理由推广到写出来的函数类型**：
一个写着 `!Ask` 的函数类型看起来在说「调用我的人得供证据」，而 Dawn 的证据从来不由
调用方供，只由闭包捕获。这个拼写没有对应的运行时含义，所以它不该存在。

**诊断。**

```
error: a function type cannot name the effect `Ask`
  --> …:9:20
  |
9 | fn sink(f: fn() -> Int !Ask) -> Int = f()
  |                    ^^^^^^^^^^^^^^^
  = hint: use an effect variable — `fn() -> Int !e` accepts a closure that
          raises `Ask` and forwards it into this signature's row. A written
          label would read as "the caller supplies the handler", and a closure
          carries the handler it was created under (docs/spec.md §6.5)
```

hint 必须点名效果变量，因为它是**唯一**的迁移写法，而且严格更通用：`!e` 既收带标签的
闭包（checker.dawn:8029-8031 已钉住），也收纯闭包。

### 4.2 ②：创建点结算

**钩子只有一个**：`evidence_args`（checker.dawn:4905）是全语言唯一解析证据的地方
——操作调用与「签名里写出标签的具名函数」两条路都从这里拿 `ev$…`。把它的解析结果
分类，就拿到了结算所需的全部信息。

**状态。**

- `Frame` 加 `handle_evs: Map[Int /*ev 的符号 id*/, Eff /*该 handler 各臂效果的并*/]`，
  在 `check_handle` 声明 ev 局部处（checker.dawn:3946-3948）写入；`bind_evidence`
  （:7020）绑的签名证据**不**进这张表。表里有 ⟺ 这个证据是本地 `with handle` 的。
- `LambdaCx`（checker.dawn:3783-3790）加两个字段：`settled: List[(Int, Eff)]`（被本地
  handler 应答过的标签，附其臂效果）与 `unsettled: List[Int]`（有其它来源的标签）。

**记账。**

1. `evidence_args` 解析到符号 `sid`：`handle_evs` 命中 → 往最内层 `LambdaCx.settled`
   压 `(eid, arm_eff)`；未命中（即签名证据）→ 往 `unsettled` 压 `eid`。
   `lambda_stack` 为空（函数体直接层）时丢弃——那种情形下没有闭包可结算。
2. 三个**不经证据解析**却带标签的记账点，一律压 `unsettled`：
   `XApply` 路径 checker.dawn:4230、`XCallDyn` 路径 :4696、以及 :4854 处
   `instantiate_eff` 产生的、**不在 `eff_labels(s.eff)` 里**的标签（经效果变量流进来的）。
   这三处的证据都在别人的捕获里，本闭包无从结算。

**结算。** `check_lambda` 算出 `lam_eff`（checker.dawn:3816）后：

```
settle(lam_eff, settled, unsettled):
  keep   = { E ∈ eff_labels(lam_eff) | E ∈ unsettled 或 E ∉ settled }
  extra  = ⋃ { arm_eff | (E, arm_eff) ∈ settled, E ∉ keep }
  eff_union([ eff_with_labels(eff_base(lam_eff), keep), extra ])
```

三条判据，逐条给理由：

- **「解析到本地 `with handle` 的证据」= 词法作用域内最近的那个**，因为
  `resolve_local`（:4911）本来就取最内层绑定。不需要新的作用域规则。
- **臂的效果并入闭包的行**：臂闭包是被捕获的证据记录的字段，调用闭包就会跑它们，
  所以它们发生在**闭包被调用时**，属于闭包的行。臂效果同时也照旧记在装 handler 的
  块头上（:3938）——那是保守的重复计费，`record_effect` 对完全相同的行去重，
  不同的行也只是让 `verify_effects` 多核对一次，无用户可见差别。
- **部分结算取保守：只要该标签还有别的来源，就整条留着**。这是 §5 那条反例逼出来的
  （p2 实测）：把「行里出现 E」和「E 被本地应答过」混为一谈，会把一个证据其实来自
  签名参数的闭包结算成纯的，然后它就能存进纯字段流出去。留着标签是过近似，永远安全。

**嵌套 handle** 不需要额外规则：内层的 ev 遮蔽外层，`resolve_local` 自然取内层。
**臂里再发本效果**（§4.4「自己不应答自己」）也自然对：`check_handle` 是**先查臂、
后绑 ev**（:3929 vs :3946），所以臂里的 `ask()` 解析到的是外层证据，臂闭包据此
对外层结算——语义与既有条文一致，不是新行为。

**`eff_minus` 的去留：删。** 这条是本方案里唯一「不只是修，还搬家」的动作，值得单独说。

`with handle` 的剩余部分是一个真闭包（v0.40.0 的 `with` 通路），`check_handle` 在
声明 ev **之后**才检查它（:3946-3950），所以剩余闭包体内的每一次直接操作调用、
每一次「签名写了标签的具名函数」调用，都会解析到**本 handler 的** ev，从而被 ② 结算。
`eff_minus(reff, eid)`（:3958）此时已经没有东西可减。它唯一还能减掉的，是**没有**
被结算的标签——即来自函数值调用、或经效果变量流进来的那些；而按 §5 的不变式，
那些标签所在的函数必然自己在签名里认了它们。所以减掉它们只会**掩盖**信息，
不会放宽任何合法程序。

删掉之后，「行失去一个成员」这件事在全语言只发生在**一个**地方，而且是**闭包创建点**
——也就是证据被捕获的那一点。这正是 D2 的根治：减法和捕获在同一点发生，就不可能
减错人。spec.md:1099-1100 与 effects-design.md:186-190 的「减法只发生在这一个语法
节点上、不进 unification」这句话保留，但那个节点从 `with handle` 换成了 lambda。

删 `eff_minus` 与 ③ 是一对：单独删它、不上 ③，是空操作（没人核对标签）；单独上 ③、
不删它，不变式仍然成立但没被断言。所以两者同刀。

### 4.3 ③：整行核对

`verify_effects`（checker.dawn:7047）的循环体，`:7062-7063` 从

```
let base = eff_base(used)
if not eff_subsumes(eff_base(declared), base) { … }
```

改成对整行 `eff_subsumes(declared, used)`，报错文案里的 `eff_show(base)` 换成
`eff_show(used)`。`eff_subsumes`（types.dawn:162）本来就是双轴的：标签轴做集合包含，
base 轴走 `base_subsumes`。无 label 时两者逐字节等价，所以这条改动对存量是恒等的。

**必须同时处理重复诊断。** `check_call` 在 :4854 先 `record_effect(callee_eff)`，
到 :4869 才 `evidence_args`。若证据不在（`unhandled_effect`，:4929 报「没人应答」），
标签已经进了账本，整行核对会在函数末尾**再报一次**「未声明 !Ask」。两条都对，但说的是
同一件事。做法：`evidence_args` 返回它失败的标签集，`check_call` 把这些标签从要记的行里
摘掉（只记 `eff_base`），或把 `record_effect` 挪到 `evidence_args` 之后按成功的标签记。
后者更干净，但要留意 :4854 的 `callee_eff` 还被 :4857 之后的分支读——实施时按前者更稳。

`verify_effects` 现有的那段注释（:7057-7060，「the label axis answers for itself」）
必须改写：修完之后标签轴只在**具名调用**路径自己应答，经函数值到达的标签由这里应答。

## 5. 效果变量实例化边界（最深的水）

必须保住的形状，一句话：`list.map(xs, x => x + ask())` 得继续能编译
（`scripts/spike-native/effect_lexical.dawn:31`、`examples/effects/handlers.dawn:40`）。

### 5.1 (a) 禁的是**书写**，不是**存在**

`map` 的签名是 `fn map[e](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`。调用点上
`unify` 把 `e` 绑成 `ELabeled(EPure, [Ask])`，`instantiate_eff`（checker.dawn:4890）
把它代进 `map` 的行。于是**内部**确实存在一个「函数类型上挂着具体标签」的 `Ty`：
argument lambda 的推断类型就是 `TyFn([TyInt], TyInt, ELabeled(EPure,[Ask]))`。

这类型必须允许存在，否则效果多态就没了。① 的落点在 `resolve_type`——只对
**parse 出来的 `TypeRef`** 生效，对 `unify`/`subst_eff`（types.dawn:634-652）/
`instantiate_eff` 造出来的 `Ty` 完全不管。禁令与内部表示是两件事，落点天然把它们分开。

`subst_eff` 的 `ELabeled` 分支（types.dawn:652）与 `eff_union`（:111）不需要任何改动：
标签「不是变量，没有东西可以替换它」这条注释仍然成立。

### 5.2 (b) 这样的行为什么减不掉——不变式与它的证明

> **不变式（结算或声明，Settled-or-Declared）。** 在函数 `g` 的体内任意位置，
> 若一个可达的值的类型是 `fn(…) -> _ !R` 且 `R` 含具体标签 `E`，则 `g` 的签名行含 `E`。

证明按「带标签的函数类型能从哪来」穷举。共六个来源：

1. **lambda 字面量**。它的行经 ② 结算：本地 handler 应答的标签已被去掉，留下的标签
   要么来自 `bind_evidence`（:7020）绑的签名证据——而 `bind_evidence` 只按
   `eff_labels(s.eff)` 绑，所以 `g` 声明了 `E`；要么来自体内其它带标签的值（来源 2–6，
   归纳）；要么来自臂效果里残留的标签——臂本身也是 lambda（`check_lambda(…, arm=true)`，
   :3929），同样结算过，其残留标签同理归纳。
2. **`g` 的参数**。写出来的类型不能带标签（①）；写 `!e` 的，在 `g` 体内 `e` 是不透明的
   `EffVar`，永远不是具体标签。⇒ 不产生。
3. **具名函数当值用**。`check_fn_value`（:2552）在 :2564 直接拒。⇒ 不产生。
4. **调用的返回值**。返回类型是写出来的（① 管），除非它经效果变量而来
   （`fn mk[e](f: fn() -> Int !e) -> fn() -> Int !e`）——那时 `e` 的实例来自实参，
   归纳到 1–6。
5. **数据结构里读出来的**。record/variant 字段禁标签（passes.dawn:316，
   checker.dawn:7932 钉住）；泛型容器 `List[T]`、元组可以装（`T` 是类型参数，
   没有写出标签），但装进去的值必须先在 `g` 的体内存在 ⇒ 归纳。若容器跨函数边界
   传出去，接收方的参数类型要么写了标签（① 拒），要么是 `List[T]`——那么在接收方体内
   `T` 是 `TyVar`，**调不动**（`check_call` 的局部分支 :4671 要求 `TyFn`），
   只能原样传回；trait 方法也帮不上忙（trait/impl 方法禁标签，passes.dawn:1196/:1671）。
6. **`const` / comptime**。`comptime` 一律拒绝具名效果（`check_handle` 的 :3862
   与 `leave_isolated`）。⇒ 不产生。

不变式一旦成立，「行会不会被 `eff_minus` 减错」这个问题就消失了——不是因为减法安全，
而是因为**减法被删了**（§4.2）。留在行里的标签只有一条出路：被 ③ 拿去和签名核对，
而不变式说签名里有它。这就是「只传播不可减」这条要求在本方案里的落法：
它不是一条新规则，是**删掉旧规则之后的剩余状态**。

### 5.3 找反例：找到一个，它改变了 ② 的设计

**反例（p2，实测今天被拒，naive 版本的 ② 会放行）：**

```dawn
type Box = { f: fn() -> Int }
fn pure_call(f: fn() -> Int) -> Int = f()

fn g() -> Box !Ask = {
  let k = () => ask()               # 证据来自 g 的签名参数，行 !Ask
  with handle Ask { ask() => 2 }    # H，纯臂
  let m = () => k()                 # m 体内没有任何证据解析
  Box(m)
}
```

如果 ② 的判据写成「lambda 收工时，把行里每个标签拿去 `resolve_local` 一次，
解析到本地 handler 就结算」——`m` 收工时 `ev$Ask` 解析到的正是 `H`，于是 `m` 被结算成
纯的，存进纯字段 `Box.f` 流出 `g`，再喂给声明为纯的 `pure_call`。运行时 `m → k →
g 的调用方装的臂`，那个臂可以是 io 的。**纯函数里跑 io，D2 原样复活。**

今天这个程序被拒（实测：`field f of Box is fn() -> Int, got fn() -> Int !Ask`），
所以它是**由本修复引入**的回归，不是存量缺陷。

结论：§4.2 的判据必须挂在 **`evidence_args` 的每一次解析**上，而不是收工时对行做
一次事后查询。差别就是 `m`——它的行里有 `Ask`，但它一次证据都没解析过，
所以 `settled` 是空的、`unsettled` 由 :4696 的记账填上，标签留着。**没有第二个反例。**

（同族的第二个探针 p6 通过：`mixed()` 里 `m = () => k() + ask()` 两种来源都有，
按「保守留着」的判据行仍是 `!Ask`，程序继续接受。）

### 5.4 (c) 泛化 / 实例化往返：逐个边界

| 边界 | 具体行会不会「再物化」成可减形态 | 判定 |
|---|---|---|
| 实参位（`map(xs, x => ask())`） | `e := {Ask}`，`instantiate_eff` 把标签代进被调方的行，记在调用方账上 | 安全：调用方按不变式声明了 `Ask`；被调方体内 `e` 不透明，`eff_minus` 已删 |
| 返回位（`fn mk[e](…) -> fn() -> Int !e`） | 标签跟着实参的实例回到调用方 | 安全：仍在同一个函数体内，不变式未变 |
| 字段位 | 禁（passes.dawn:316） | 不可达 |
| 泛型容器 `List[T]` / 元组 | 可装，但 `T` 在接收方是 `TyVar`，调不动 | 安全（§5.2 来源 5） |
| let 多态 | Dawn 的 `let` 不做泛化——局部绑定拿的是具体推断类型 | 无此边界 |
| `alias` 展开 | alias 目标禁标签 | 不可达 |
| `unsafe_pure` | 只遮 io，标签原样记回（checker.dawn:3661-3670） | 不变 |
| `assignable` 的三道门（let / return / assign） | `eff_subsumes` 双轴（types.dawn:162，checker.dawn:367） | 不变，且是 ① 之外的第二道保险 |

一条**已存在且本方案不解决**的表达力缺口，留档：返回函数类型的函数**写不出自己的行**
（`fn f() -> fn() -> Int !io` 的 `!io` 绑到内层；`(fn() -> Int) !io` 解析成元组，实测 p5）。
今天就存在（实测 p4 的第三条诊断：装 io 臂又返回闭包的函数无法声明 `!io`）。
变通是把闭包包进 record（`fn f() -> Thunk !io`，实测可行）。要真解需要给返回位的
函数类型加括号形式，属于语法批，**不进本设计**。

## 6. 拒绝面与新诊断

| # | 形状 | 诊断 |
|---|---|---|
| ① | `fn sink(f: fn() -> Int !Ask) -> Int` | 见 §4.1 |
| ① | `alias T = fn() -> Int !Ask` | 语法层先手（passes.dawn:316）已报「a type declaration cannot carry effect variables」；实施时决定是否让 ① 的文案接管这两处——**建议接管**，因为「effect variables」这个词对 `!Ask` 是错的，是既有小瑕疵 |
| ② | 无新拒绝（②是纯放宽：闭包的行变小或换成臂的效果，能通过的门只多不少） | — |
| ③ | `fn f() -> Int = { … k() … }`，`k: fn() -> Int !Ask` | `function \`f\` is not declared !Ask but calls \`k\` (!Ask)` + hint「add !Ask …, or handle it with \`with handle Ask { … }\`」 |
| ③ | 同上但标签经效果变量实例化而来 | 同上，witness 名是被调函数名 |

**③ 在 ① 之后没有可达的新拒绝**——不变式说了，这样的值在不声明该标签的函数里造不出来。
这不是「③ 没用」，而是「③ 是断言」：它红了，就说明 ①② 的不变式破了。语料要按这个
定位来写（§10 刀 3）。

## 7. 破坏面清单（全仓实数：**4 处**）

`grep -rn --include='*.dawn' -E '\bfn\s*\([^)]*\)\s*->[^=]{0,60}![A-Z]'` 全仓命中 5 条，
去掉 `checker.dawn:8063`（那是错误消息里的字符串字面量，不是类型），实数 4：

| 站点 | 现写法 | 迁移写法 | 备注 |
|---|---|---|---|
| `scripts/spike-native/effect_lexical.dawn:24` | `fn escaping() -> fn() -> Int !Ask` | `fn escaping() -> fn() -> Int` | ② 让逃逸闭包的行变成臂的效果（此处臂是 `ask() => 7`，纯）。第 20-23 行的注释要改：「类型仍说 `!Ask`」被推翻 |
| `scripts/checker-corpus/cases/trait_method_effects.dawn:7` | trait 方法参数 `f: fn() -> Int !Ask` | 保留，`.expected` 重录 | 本来就是 reject case，只是诊断可能从「trait 方法禁效果变量」变成/多出 ① 的文案 |
| `scripts/checker-corpus/cases/trait_method_effects.dawn:33` | impl 方法同款 | 同上 | 同上 |
| `selfhost/src/check/checker.dawn:7932`（内联 test） | `pub type Box = { f: fn() -> Int !Ask }` | 若 ① 接管文案则断言串同批改 | 见 §6 第二行的裁决 |

**不受影响**（已逐个看过）：`examples/effects/handlers.dawn`、`site/pages/feat_effects.dawn`、
`scripts/spike-native/effect_handler.dawn`、`scripts/grammar-corpus/accept/effect_forms.dawn`
（`fn through_a_variable(f: fn() -> Int !e)` 是效果变量，合法）、
`scripts/checker-corpus/cases/{handlers,effect_escape,effect_use,main_effect,purity,comptime,
isolated_*,with_sugar,fn_namespace,effect_decl}.dawn`。

**行为面的破坏，只有一处**：`effect_escape.dawn` 的三道门今天靠「逃逸闭包的行是 `!Ask`」
才拒得动（`.expected` 里三条诊断）。② 之后闭包的行变成臂的效果，若臂是纯的，
`let g: IoFn = () => get()` 反而合法了——**这是修复的目的，不是回归**：那个闭包真的
只会跑纯臂。语料要相应改造：把「纯臂 → 现在合法」和「io 臂 → 仍然拒（因为行成了 `!io`）」
两条都录进去，这比今天的版本测得更准。

**`backend-dawn`（~/workspace/dawnop-site）零 effect 声明**——全仓无 `effect` 关键字、
无 `with handle`，故本修复对它是完全惰性的，升钉时零迁移。同理 `selfhost/src/` 与 `std/`。

## 8. 种子纪律评估

**结论：一期，无 `Emit-Change`，不需要种子推进。**

三条依据：

1. **编译器自己的源码里没有 label。** `effect` 声明只出现在 `examples/`、`scripts/`、
   `site/pages/`（14 个文件，全部实测枚举过），`selfhost/src/` 与 `std/` 一个都没有。
   ⇒ `resolve_type` 的新分支只在 `eff_labels(eff)` 非空时报，走不到；`evidence_args`
   的分类只在有证据可解析时跑，走不到；`verify_effects` 的 `eff_subsumes` 在无 label 时
   与 `base_subsumes` 逐字节等价（types.dawn:162-168 的短路：`eff_labels(inner)`
   是空列表，循环零次）。
2. **Core 不携带效果行。** `selfhost/src/ir/lower.dawn` 全文只有两处 `Eff`
   （:3479、:3585，都是构造 `EPure` 填签名），不读任何行。②改的是**推断出的行**，
   而行不进 Core、不进 descriptor、不进字典/证据参数（证据参数按 `Sig` 的
   **写出来的** labels 合成，effects-design.md §5.2 步 1，与推断行无关）。
   ⇒ 对任何 label-free 输入，emit 逐字节不变。
3. **唯一带 effect 的 emit 差分输入**是 `emit examples/effects/handlers.dawn`
   （`scripts/emit-labels.txt` 里在册）。该文件无注解位标签，且按 2. 的理由 emit 不变。

因此：`scripts/emitchange.sh` 不需要任何声明；`scripts/core-golden/` 不需要重录；
`bin/seeds` 不动。**要重录的只有 `scripts/checker-corpus/*.expected`**——
`effect_escape.expected`、`trait_method_effects.expected`，以及新增 case 的 golden，
用 `--record` 出，diff 进 review（诊断顺序敏感，见 checker-corpus/README.md）。

**语料演进**（按 checker-corpus/grammar-corpus 各自的分工）：

- `grammar-corpus`：**不动**。① 是 checker 的拒绝，不是语法的；`effect_forms.dawn`
  照旧解析通过。
- `checker-corpus` 新增：
  - `effect_fn_type_label.dawn` —— ① 的四个位置（参数 / 返回 / let 注解 / `List[…]` 嵌套）各一条。
  - `effect_settle.dawn` —— ② 的四个形状：本地结算（纯臂 → 闭包纯）、io 臂（闭包 `!io`）、
    部分结算（p6 的 `mixed`，标签留着）、§5.3 的 p2 反例（必须仍被拒）。
  - `effect_row_verify.dawn` —— ③：经函数值调用带标签、函数未声明。
- `spike-native` 新增一份运行语料（双后端对拍 stdout）：io 臂 + 逃逸闭包，
  证明「行说 `!io` 且真的打印」；并把 e9 / e15 的形状作为**编译失败**语料
  （spike-native 比的是 stdout，编译失败的形状更适合放 checker-corpus）。

## 9. spec / 设计文档改动清单

中文正本改完，孪生英译同批，`scripts/doc-check.py` 的 `translation-of … @ digest` 一并重登。

| 文件:行 | 现状 | 改成 |
|---|---|---|
| `docs/spec.md:951-953`（§6.2 规则 4） | 「纯函数**保证**：给定相同参数返回相同值、无可观测副作用」 | 保持结论，补一句：该保证此前对具名效果**不成立**（逃逸闭包能把 io 臂带进纯函数），#188 修复后重新成立；指向 §6.5 的边界条 |
| `docs/spec.md:1096-1100`（§6.5 类型规则） | 「块记 `(base ∪ ⋃base_i, (L ∖ {E}) ∪ ⋃L_i)`」「行减 E 只发生在这一个语法节点上」 | 减法搬到闭包创建点：块记 `(base ∪ ⋃base_i, L' ∪ ⋃L_i)`，`L'` 是剩余闭包**结算后**的标签集；「只发生在一个节点」保留，节点换成 lambda |
| `docs/spec.md:1105-1110`（逃逸闭包） | 「逃逸闭包的**类型**仍写着 `!E`，调用它的地方仍要在行里认下这个标签」 | **推翻**：逃逸闭包的类型不再写 `!E`，写的是它捕获的那些臂的效果。类型如实反映「会跑什么」，而不是「谁得供 handler」——因为 Dawn 从不由调用方供 |
| `docs/spec.md:1116-1124`（边界 v1） | 「类型声明位」一条 + 「带标签的闭包不能存进记录字段」 | 推广成「**任何写出来的函数类型**都不能带具名效果标签」；删掉「不能存进记录字段」——② 之后闭包的行已经结算，存得进去了 |
| `docs/spec.md:1130-1134`（实现，信息性） | 证据参数只按写出来的 labels 合成 | 不变，补一句它的对偶：闭包按创建点结算，两条合起来才是完整的证据流 |
| `docs/effects-design.md:177-190`（§4.3） | 「行减 E」全节 | 论断被推翻，改写；保留旧结论并注明为什么错（减法在消费方，捕获在生产方） |
| `docs/effects-design.md:192-204`（§4.4） | 「逃逸闭包 well-defined」段 | 保留 well-defined 的论证，删掉/改写「类型仍写着 `!E`」 |
| `docs/effects-design.md:205-224`（§4.5） | 四处拒绝 | 加第五条：函数类型注解位 |
| `docs/effects-design.md` 新增 §4.6 | — | 「创建点结算」：判据、臂效果并入、部分结算取保守、p2 反例留档 |
| `docs/codebase-audit-v2/02-types-effects-and-semantics.md:17` | 静态反例形状（D2） | 标注已修 + 修法指向本文 |
| `docs/spec.en.md:1334`、`:1345-1349` | 上两条的英译 | 同批 |
| `docs/tutorial.md` §17（:706-800） | 效果一节 | 通读一遍：若出现「逃逸闭包类型仍带标签」的说法同改（英正本，无中译义务） |

## 10. 刀法分批

**刀序 = ②（结算）→ ①（禁令）→ ③（核对 + 删 `eff_minus`）。** 三刀，一个发布，不推种子。

排这个序的理由是 §5 的实测：今天逃逸闭包的行是 `!Ask`，**唯一能写出来的返回类型正是
① 要禁的那个**（p4 实测三条诊断）。① 先落会让逃逸闭包彻底不可返回，等于在中途留一个
比修复前更差的状态。② 先落是纯放宽，任何时刻仓库都是可用的。

### 刀 1 — ②：闭包创建点结算

改：`Frame.handle_evs`、`LambdaCx.{settled,unsettled}`、`evidence_args` 分类、
三处非证据记账点压 `unsettled`、`check_lambda` 的 `settle`。
`check_handle` 保持原样（`eff_minus` 这刀不动，避免一刀两变量）。

**oracle**
- `scripts/checker-corpus` 全跑：只有 `effect_escape.expected` 该变（§7），
  变化逐条读过再 `--record`。任何**其它** case 的诊断变化 = 这刀错了。
- `scripts/spike-native/effect_{handler,lexical}.dawn` 双后端 stdout 逐字节不变
  （`effect_lexical.dawn:24` 此刻仍写 `!Ask`，仍合法——② 只让它的行变小，
  `eff_subsumes` 方向对，返回位仍通过）。
- `selfhost-prev-diff.sh` 的 `emit examples/effects/handlers.dawn` 不变。
- 新增 `checker-corpus/cases/effect_settle.dawn`，**含 §5.3 的 p2 反例**——
  这条是这刀的核心 oracle：它必须**继续被拒**。写不出这条 case 就说明判据挂错了地方。
- 负控（`gate-green-is-not-evidence` 的教训）：把 `settle` 的「部分结算取保守」
  临时改成「无条件结算」，`effect_settle.dawn` 的 p2 条必须红。红不了 = 语料没测到。

### 刀 2 — ①：注解位禁标签 + 4 处站点迁移

改：`cx.dawn:449` 的 `TFn` 分支加拒绝；`passes.dawn:316` 的文案是否接管（§6）；
迁移 §7 的 4 处；新增 `checker-corpus/cases/effect_fn_type_label.dawn`。

**oracle**
- 四个活泄漏 e1 / e6 / e9 / e15 **编译不过**，且都是被 ① 挡的（四者的入口都是
  一个写着 `fn() -> Int !Leak` / `!Ask` 的参数）。已被拒的 e3 / e14 仍被拒，
  且 e3 的诊断从 `got fn() -> Int !Leak` 变成 `got fn() -> Int !io`——
  **挡的理由要对得上**，这条比「红了」本身信息量大。
- `grammar-corpus` 逐字节不变（语法未动）。
- `effect_forms.dawn:23` 的 `!e` 参数继续通过——这条是「禁令没有误伤效果变量」的证据。
- `trait_method_effects.expected` 重录，diff 里每条变化能说出理由。
- 负控：把拒绝条件从 `len(eff_labels(eff)) > 0` 改成恒假，新 case 必须红。

### 刀 3 — ③：整行核对 + 删 `eff_minus`

改：`verify_effects` :7062-7063 与文案、:7057-7060 注释改写；`check_call` 的
`record_effect`/`evidence_args` 顺序（§4.3 的重复诊断）；`check_handle:3958` 去掉
`eff_minus`；删 `eff_minus`（:3823）本体；新增
`checker-corpus/cases/effect_row_verify.dawn`。

**oracle**
- 全套 `checker-corpus` 绿 = 不变式（§5.2）成立的机器证据。**这刀的 oracle 就是
  「什么都没变」**，所以它比别的刀更需要负控：
  - 负控 A：临时把 `check_fn_value:2564` 的拒绝去掉（让带标签的具名函数能当值传），
    `effect_row_verify.dawn` 必须红——证明 ③ 真的在核对。
  - 负控 B：临时把刀 1 的结算关掉，`effect_escape` / `effect_settle` 必须红。
- 「没人应答」与「未声明」不重复报：新 case 里放一个 `ask()` 在无 handler 的纯函数里，
  期望**恰好一条**诊断。
- 文档改动（§9）与本刀同批，`scripts/doc-check.py` 绿。

### 不进本设计

- 返回位函数类型的括号语法（§5.4 的表达力缺口，今天就有）。
- 臂写外层 `var`（effects-design.md §7 的开放问题 1）。
- `dawn doc` 不认识 `effect`（#115）。

## 11. 实测收据（勘察期，2026-08-08，基线 abe5105）

探针程序在 `/tmp/claude-1000/t188-probe/`，复现命令
`./scripts/dcap ./bin/dawn {check,run} <file>`：

| 探针 | 问的问题 | 今天的答案 |
|---|---|---|
| `p1.dawn` | `fn h() -> fn() -> Int !Ask` 里 `!Ask` 绑内层还是绑 `h` 的行？ | 绑内层；`h` 无行 ⇒ `ask` 找不到证据，**已被拒**（§1 的意外护栏） |
| `p2.dawn` | naive 结算（收工时对行做事后查询）会不会漏？ | 会。今天该程序被 `field f of Box is fn() -> Int, got fn() -> Int !Ask` 拒；naive 版本会放行 ⇒ §4.2 的判据必须挂在 `evidence_args` 上（§5.3） |
| `p4.dawn` | 逃逸闭包今天的行是什么？ | `!Ask`。「唯一能写的返回类型正是 ① 要禁的那个」⇒ 刀序必须 ② 先 ① 后（§10）。第三条诊断另外暴露：装 io 臂又返回闭包的函数**无法声明 `!io`** |
| `p5.dawn` | `(fn() -> Int) !io` 能解析吗？ | 不能，报「元组元素不足」⇒ §5.4 的表达力缺口是真的，且今天就有 |
| `p6.dawn` | 用效果变量重写的 e15、以及混合来源的闭包，今天接受吗？ | 都接受（`ok`）⇒ ① 的迁移写法可行，「部分结算取保守」不会拒掉存量 |
| `p7.dawn` | 带标签闭包能存进纯字段吗？ | 不能 ⇒ ② 之后能（因为行已结算），这是修复带来的**放宽**，不是回归 |

活泄漏复现：`e1` / `e6` / `e9` / `e15` 四个程序 `dawn run` 打出 io 臂的输出；
`e3` / `e14` 今天已被拒。
