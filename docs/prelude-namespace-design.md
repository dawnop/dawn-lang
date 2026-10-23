# prelude 命名空间设计 — 追加兼容性与函数命名空间的「一道门」

> 状态：**historical** —— 已落地（任务 #119，三刀于 2026-08-02 全部完成）。两条契约级决策
> （D1 主路线、D2 范围）由用户于同日定案，见 §2；其余七条（D3–D9）是本文的裁决，
> 可推翻。落地与设计的偏差记在 §6 各刀末尾。
>
> 勘察基线 **383c089**（v0.46.0 种子推进后），文中 file:line 与实测输出均对该提交，
> 已逐条复核。前置阅读：[assoc-types-design.md](assoc-types-design.md)（刀 1/刀 2 已落地）、
> [trait-v2-design.md](trait-v2-design.md) §7.5（本文 §D6 回答它留下的裁决）、
> [effects-design.md](effects-design.md)（效果操作进函数命名空间那部分）。
> 落地后权威条文进 [spec.md](spec.md)，落点清单见 §5。

## 1. 问题与目标

**问题**：往 prelude 加一个 trait，可能让已经通过检查的程序编译失败。

今天 prelude trait 的方法名（`cmp`/`eq`/`hash`/`show` 与 `iter_start`/`iter_done`/
`iter_next`/`iter_get`）被塞进模块的函数命名空间，并且**顶层重名是声明期硬报错**
（spec.md:1619-1623）。刀 2 加 `Iter` 时这条规矩当场收了税：短名 `start`/`done`/
`next`/`get` 会把 std 自己编译坏（7 个顶层 fn 声明期报错 + builtin `get` 静默改绑），
只好改用四个长名（assoc-types-design.md §6 刀 2 记录）。换句话说，**prelude 是只进不出、
且每进一个名字就可能踩到别人的程序**——刀 3 的运算符 trait 还要再进几个。

实测（本次复核，见 §3.4）：一个写了 `fn iter_next` 的存量程序，今天得到 **3 条错误**——
一条声明期硬报错，外加两条级联噪音，因为报错之后 `cx.fns` 里留的仍是 prelude 的签名，
函数体按错的签名检查。

**目标**：

1. **追加兼容性**：往 prelude 加名字，不能让任何已通过检查的程序失败。
2. **注入是逐 trait 的选择**：由 `[]` 这类运算符独占消费的 trait，不该占全局名。
3. 顺手把「谁能写进函数命名空间」收成一条规则，封掉勘察实测出的效果操作导入缺陷。

**非目标**：

- 改 `cx.fns → cx.std_fns → builtins` 这个三层解析序（checker.dawn:3784-3792）。
  本设计不动层，只动**第一层里谁能覆盖谁**。
- 给 prelude trait 方法造限定拼写（见 D5，判为不需要，理由写死在那一节）。
- 引入 warning 诊断档（见 D3，判为超出比例，代价盘在 §8 开放问题 1）。
- 刀 3 本身（运算符 trait）。本文只交付它要消费的接口，见 §7。

## 2. 裁决记录

### D1 主路线 = 遮蔽代替报错 + 逐 trait 声明是否注入（用户定案 2026-08-02）

两件事一起做：

1. **本地定义遮蔽 prelude trait 方法**，今天的声明期硬报错取消。
2. **注入与否成为每个 prelude trait 自己的属性**，不再全体一刀切。`Iter` 的四个
   `iter_*` 与 `Eq`/`Ord`/`Hash`/`Show` 的 `cmp`/`eq`/`hash`/`show` 保持注入
   （存量要），刀 3 的 `Index` 只由 `[]` 消费、不占全局名。

**收益**：新增 prelude 名从此不可能破坏任何存量程序——新名要么没被用到，要么被本模块的
声明遮蔽。§1 的问题根治，而不是每次加名字前做一遍全网撞名勘察。

**与今天哲学的关系**：这不是引入新规矩，是**取消一条例外**。spec §10.3:1575-1576 与
§10.6:1619-1620 已经授权「顶层 fn 可以静默遮蔽 builtin/std 函数名」——std 自己的
`pub fn len` 正是靠这一条才合法。prelude trait 方法今天是这条通则的唯一例外
（spec.md:1620-1623 的「**除外**」），D1 把它拉回通则。

**代价**（三条，逐条在后文处理）：

- 遮蔽是静默的，用户可能不知道自己遮蔽了什么 → D3。
- 被遮蔽后没有别的拼写可以调到 prelude 方法 → D5 论证不需要。
- spec 里「遮蔽在本模块内是全量的」那句要改 → §5，且它**今天就已经不成立**（§3.4 实测 2）。

### D2 范围 = 六个 `cx.fns` 写入点收成一道门（用户定案 2026-08-02）

把「谁能写进函数命名空间、写的时候查什么、冲突时遮蔽还是报错」收敛成一条规则
（§4.1），并封掉 `inject_selective` 效果臂什么都不查的缺陷（checker.dawn:5106）：
两个 `use` 写反顺序，同一份程序语义翻转、零诊断，直接违反 spec §6.5:982。
实测见 §3.4 实测 3。

### D3 遮蔽的诊断策略 = 编译器静默，LSP 出提示

**裁决**：编译器一声不吭（与遮蔽 builtin/std 完全同待遇）；hover 与补全在**遮蔽方的
声明处**注一句「shadows the prelude method `Show::show`」。

**Dawn 今天没有 warning 档**，这是查清楚的，不是印象：

- `Diag` 是 `{ msg, lo, hi, hint }`，没有 severity 字段（token.dawn:104）。
- `render` 无条件打 `"error: "` 字面量（diag.dawn:71），注释里写明「Kotlin sink 的
  `warn()` 没有调用点，所以 selfhost 的 Diag 不带 severity」（diag.dawn:52-53）。
- LSP 发布诊断时 severity 硬编码 `JInt(1)`（lsp.dawn:628）。

造一个 warning 档要动这四处，还要连带回答「CI 允不允许有 warning」「`--deny-warnings`
要不要有」「std 自己有没有 warning」。为了一条提示付这个价不成比例——盘在 §8 开放问题 1，
有真需求再做。

**困惑面**（用户点名的那个）：有人无意中写了 `fn cmp`，然后发现 `a == b` 与 `xs < ys`
行为不变、`cmp(a, b)` 却变了。三条缓解：

1. 这**不是**本设计引入的困惑，是今天 builtin 遮蔽已有的形状，而且今天连
   `to_string` 都已经是这样（§3.4 实测 2）。
2. 困惑的正解不是「不许遮蔽」而是「说清楚规则」：运算符与糖按 trait id 找 impl，
   **不经名字**（§4.4 的四条论证），所以遮蔽名字从来不会改运算符行为。这句要进 spec
   （§5 的 §10.3:1577 那条）。
3. hover 提示把它落在编辑器里，成本是 lspq.dawn 一行拼串。

### D4 注入属性的表示 = `TraitI.injects` 字段 + prelude 集合收成一张表

见 §4.2、§4.3。要点：标记落在 `TraitI`（types.dawn:585-599）而不是
`prelude_traits()` 的构造参数，因为「trait 方法名占据函数命名空间」有**三条**注入路径，
一个字段让三条读同一个判词；构造参数只覆盖其中一条。同时把 prelude 集合的四份抄件
（错两份）收编成一张表，两处漏项一并订正。

### D5 逃生阀 = 不给限定形

注入的 trait 方法被遮蔽后，**没有**别的办法按名字调到它，这是有意的。四条论证见 §4.4。
不注入的 trait（`Index`）其方法名仍需在三个地方被拼写——impl 体、`dawn doc`、错误消息
——三处都不需要全局名。

### D6 参数位的关联类型 = 能按名字调用，但投影只参与检查不参与推断

回答 trait-v2-design.md §7.5 那条「直接压在本设计头上的未答裁决」。答案是**能**，
而且今天已经是这样——`Iter` 的三个方法就把 `C.Cur` 摆在参数位，且按名字调得动。
规则与实测见 §4.5。对刀 3 的意义：这条裁决**不再约束**刀 3 的表示选型。

### D7 新形状的诊断 = 不加

改成遮蔽后，「存量程序写了 `fn iter_next` 就编译失败」自动消失。反向的新形状三种，
逐一驳回，见 §4.6。本刀净效果是**减少**诊断噪音（一处错误变三处的级联消失）。

### D8 imported_names 要为效果操作登记

D2 的封堵手法。副作用是一条诊断文本变化（今天误导，改后准确），见 §4.1 与 §6 刀 B。

### D9 分三刀，全部不改 lowering

刀 A（一张表 + 字段，纯重构）→ 刀 B（一道门）→ 刀 C（遮蔽）。三刀都不改 Core、
不改 emit、不改 std 签名，因此**不需要种子三期两发布**。验收判据见 §6。

## 3. 现状（勘察复核，基线 383c089）

### 3.1 三层与解析序

```dawn
pub fn lookup_fn_sig(cx: Cx, name: String) -> Option[Sig] =
  match map.get(cx.fns, name) {
    Some(s) -> Some(s)
    None ->
      match map.get(cx.std_fns, name) {
        Some(s) -> Some(s)
        None -> builtin_sig(cx, name)
      }
  }
```

checker.dawn:3784-3792。第二层 `cx.std_fns` 是从 builtin 表迁去 std 的那批（`load_std`
汇总，stdlib.dawn:163+），第三层是 builtin 表本身（全集见 `dawn doc --builtins`）。
**LSP 手抄了第二份同序**（lspq.dawn:91-100 的 `sig_of`），改解析序要同时改两处——
本设计不改解析序，这条只是记账。

跨层遮蔽静默、零诊断；同层撞车是声明期硬报错。**prelude trait 方法被塞进第一层**
（`seed_prelude`，checker.dawn:1593-1601，pass 0），于是它们与本模块的顶层声明同层，
撞车即报错——这就是 §1 的问题。

UFCS 与直呼同一条路：`x.f(a)` 在 checker.dawn:8770-8771 转成 `f(x, a)` 走
`check_call → lookup_fn_sig`，**没有**按接收者类型查 impl 的分支。所以遮蔽对点调用
与直呼是同一件事，不必分别设计。

### 3.2 六个写入点

pass 顺序：`seed_prelude → pass_java_uses → pass_imports → pass_type_shells →
pass_ctor_fields → pass_effects → pass_resolve_aliases → pass_register_traits →
pass_register_impls → pass_fn_signatures → …`（checker.dawn:9797-9809）。
prelude 最先，引入次之，本模块声明最后——这个顺序本身就是「谁该遮蔽谁」的答案，
今天只是没有被表述成规则。

| # | 位置 | 写的是谁 | 写之前查什么 |
|---|---|---|---|
| 1 | checker.dawn:1599 | prelude trait 的方法（循环 1594-1601） | **无** |
| 2 | checker.dawn:5048 | `use m.{f}` 引入的函数 | 只查 `imported_names`（5040-5045） |
| 3 | checker.dawn:5106 | `use m.{E}` 带进来的效果操作 | **什么都不查** |
| 4 | checker.dawn:2255 | 本模块 `effect` 的操作 | `alias_shadows` → `import_clashes` → `map.has(cx.fns, …)` |
| 5 | checker.dawn:2434 | 本模块 `trait` 的方法 | 同上 |
| 6 | checker.dawn:3242 | 本模块顶层 `fn` | 同上 |

还有一处 `cx.fns` 写入不是命名空间入口：checker.dawn:9652-9653 在推断完成后把
`Sig{inferring: true}` 换成 sealed 版本，且 `if map.get(cx3.fns, d.name) == Some(s)`
守着——覆写同名同值，不建立新绑定。一道门不收它。

三处 `alias_shadows`/`import_clashes` 走的是 checker.dawn:317-334 的四个小函数。
第 4/5/6 号写入点的第三档检查各自拼自己的错误文本（"operation … is already a
function"、"trait method … collides with"、"function … is defined twice"），三份措辞、
一套语义。

### 3.3 prelude 集合抄了四份，错两份

| 抄件 | 位置 | 内容 | 对不对 |
|---|---|---|---|
| 1 | spec.md:1621-1622 | 8 个方法名 | 对 |
| 2 | checker.dawn:1594 | 5 个 trait id | 对 |
| 3 | checker.dawn:2313 | 3 个 trait 名字符串 | **漏 Show / Iter** |
| 4 | lspc.dawn:260 | 1 个 trait 名（只补 `Ord`） | **漏 Eq / Hash / Show / Iter** |

抄件 3 的后果实测：

```
$ trait Show[T] { fn zzz(x: T) -> Int }
error: trait `Show` is defined twice        # 应该是 "is a prelude trait and cannot be redefined"
$ trait Eq[T] { fn zzz(x: T) -> Int }
error: `Eq` is a prelude trait and cannot be redefined
```

`Iter` 同 `Show`。「defined twice」在只写了一次的文件上是纯误导。

再加一份**语义**抄件：`exports_of`（checker.dawn:10515-10525）把 pub trait 的方法
塞进 `ModExports.fns`——那是第三条注入路径，D4 的字段必须被它读到。

### 3.4 四条实测（本次复核跑的）

**实测 1 — 硬报错会级联**。`fn iter_next(x: Int) -> Int = x + 1` 加一个调用点：

```
error: `iter_next` is already a method of trait `Iter` (trait methods share the function namespace)
error: `iter_next` takes 2 argument(s), got 1
  = hint: signature: fn iter_next[T: Iter](c: T, k: T.Cur) -> T.Cur
error: cannot infer type parameter(s) T for `to_string`
3 errors
```

报错之后 `cx.fns` 里留的是 prelude 的签名，函数体按它检查。D1 之后这段是 0 错误。

**实测 2 — spec §10.3:1577「遮蔽是全量的」今天已不成立**。`to_string` 是 builtin
（types.dawn:1233，带 `SHOW_ID` 约束）而不是 prelude 方法，所以用户可以拿它当 trait
方法名：

```dawn
type B = B(v: Int) derive Show
trait Pretty[T] { fn to_string(x: T) -> String }
impl Pretty[B] { fn to_string(x: B) -> String = "pretty" }
# println(to_string(b))  ->  pretty
# println("${b}")        ->  B(1)
```

实测输出正是 `pretty` / `B(1)`。名字走用户实现，`${…}` 走 derive Show——因为
`${…}` 在 lower.dawn:1604-1660 按 `SHOW_ID` 找 impl，不经 `cx.fns`。**已存在的可观测
分道**，不是本设计引入的。

**实测 3 — 效果操作导入的顺序敏感**。两个模块各自 `pub effect A { fn ask() -> Int }` /
`pub effect B { fn ask() -> Int }`，主模块两条 `use` 只换顺序：

```dawn
use a.{A}
use b.{B}
pub fn main() -> Unit !io = {
  with handle A { ask() => 1 }
  with handle B { ask() => 2 }
  println(to_string(ask()))
}
```

`use a` 在前输出 **2**，`use b` 在前输出 **1**，两次都是 0 诊断。根因在
checker.dawn:5101-5109：效果臂直接 `map.insert(cx1.fns, op, sg)`，既不查
`imported_names` 也不登记进去——`imported_names` 记的是 `use` 括号里逐字写的名字
（`A`/`B`），操作名 `ask` 从没进过那张表。spec §6.5:982 说「与普通函数同名即重定义
错误」，这条路上一句都没兑现。

**实测 4 — 同一个洞的第二个症状**。`use a.{A}` 加本模块 `fn ask() -> Int = 9`：

```
error: function `ask` is defined twice
```

文件里 `ask` 只定义了一次。第 6 号写入点的第三档 `map.has(cx.fns, …)` 命中了引入的
操作，但因为 `imported_names` 没登记，`import_clashes` 没命中，于是走了措辞最不合适
的那一档。

## 4. 设计

### 4.1 一道门

一个函数收掉六个写入点：

```dawn
## Where a name in the function namespace came from. The pass order
## (checker.dawn:9797-9809) already puts these in precedence order; this type
## is that order made sayable.
pub type Origin =
  | OPrelude
  | OImport(from: String)
  | OLocal(kind: String)   # "function" / "trait method" / "operation"

pub fn bind_fn(cx: Cx, name: String, sig: Sig, org: Origin, lo: Int, hi: Int) -> Cx
```

`Cx` 加一个字段 `fn_origin: Map[String, Origin]`，与 `fns` 同步维护。规则只看
「已有绑定的 Origin」×「本次的 Origin」：

| 已有 ＼ 本次 | `OImport` | `OLocal` |
|---|---|---|
| （无） | 写入 | 写入 |
| `OPrelude` | 遮蔽，静默写入 | **遮蔽，静默写入**（D1 改的就是这一格） |
| `OImport` | **报错**：`x` 同时从两个模块引入 | 报错：`import_clash`（不变） |
| `OLocal` | pass 序保证不会发生（断言） | 报错：defined twice / already a method（不变） |

`OPrelude` 只在 `seed_prelude` 出现，且那时表是空的，所以第一行第一格恒成立。

**前置检查升格**：`alias_shadows`（checker.dawn:325）今天只在第 4/5/6 号写入点查，
一道门里对 `OImport` 也查——`use json/lexer` 与 `use x.{lexer}` 撞车今天从哪条路
报错取决于顺序，收进一道门后是一条规则。

**诊断**（三条，其余不变）：

- 两个引入撞车，复用现成措辞（checker.dawn:5041-5044）：
  `` `ask` is imported more than once (from `a` and `b`) ``。
  操作要点名它是操作，hint：
  `` `ask` is an operation of both `A` and `B`; import one, or qualify it as `a.ask(…)` ``。
- 本地声明撞已引入的操作名：由 D8（`imported_names` 为操作名登记）自动从
  「function `ask` is defined twice」变成 `import_clash` 的
  「function `ask` conflicts with a name imported from `a`」——实测 4 的误导消失。
- 遮蔽 prelude：**无输出**（D3）。

**为什么是「遮蔽」而不是「就近优先」**：`cx.fns` 是一张平表，没有作用域链；遮蔽的实现
就是覆写，被覆写者不再可达。这与 §4.4 的逃生阀论证是同一件事的两面。

### 4.2 注入属性落在 `TraitI`

```dawn
pub type TraitI = {
  id: Int,
  name: String,
  tvar: Ty,
  is_pub: Bool,
  owner: Option[String],
  src_path: Option[String],
  methods: List[(String, MethodSig)],
  assoc: List[String],
  ## Do this trait's method names occupy the module function namespace?
  ## True for every trait a user can declare; false only for compiler-built
  ## traits whose sole consumer is an operator (docs/prelude-namespace-design.md D1).
  injects: Bool
}
```

**三条注入路径必须读同一个字段**：

| 路径 | 位置 | 今天 | 改后 |
|---|---|---|---|
| prelude 播种 | checker.dawn:1597-1600 | 无条件注入五个 trait 的方法 | `if tr.injects` |
| 本模块 `trait` 声明 | checker.dawn:2421-2434 | 无条件 | `if tr.injects`（用户 trait 恒 true，形同不变） |
| `pub trait` 导出 | checker.dawn:10515-10525 | 无条件塞进 `ModExports.fns` | `if tr.injects` |

第三条是勘察里没点名的那条：不读字段的话，一个 `injects: false` 的 pub trait 的方法
仍会被 `use m.{method}` 拉进来，字段就成了摆设。今天没有 `injects: false` 的用户
trait，但字段既然在 `TraitI` 上，三条路径必须一致——这正是它不该做成
`prelude_traits()` 构造参数的理由：构造参数只覆盖第一条。

**没有表面语法**。`trait` 声明恒 `injects: true`；`false` 只由编译器构造的 trait 使用。
用户可声明的不注入 trait 留作开放问题（§8 开放问题 2），字段先在那里。

### 4.3 prelude 集合收成一张表

唯一真相在 types.dawn，紧挨 `prelude_traits()`：

```dawn
## The prelude trait ids, in id order. Everything that needs to know "which
## traits does the prelude bring" reads this -- the seeding loop, the
## redefinition guard, LSP completion, `dawn doc`.
pub fn prelude_trait_ids() -> List[Int] = [ORD_ID, EQ_ID, HASH_ID, SHOW_ID, ITER_ID]

pub fn is_prelude_trait_name(n: String) -> Bool = ...   # 由 prelude_traits() 派生
```

改造与订正：

| 抄件 | 改成 | 可观测变化 |
|---|---|---|
| checker.dawn:1594 | `for tid in prelude_trait_ids()` | 无 |
| checker.dawn:2313 | `if is_prelude_trait_name(d.name)` | `trait Show` / `trait Iter` 的报错从「defined twice」变成「is a prelude trait and cannot be redefined」 |
| lspc.dawn:260 | 遍历 `prelude_traits()` 加补全项 | 补全多出 `Eq`/`Hash`/`Show`/`Iter` 四项 |
| spec.md:1621-1622 | 8 个名字降级为示例，全集指向 `dawn doc --builtins` | 见 §5 |

doc.dawn:434 已经在读 `prelude_traits()`，不用改。

**为什么不把方法名也列成一张表**：方法名是 `TraitI.methods` 的键，从 trait 表派生即可
（`is_prelude_method(n)` 遍历 `prelude_trait_ids()` 的 methods）。再列一份就是第五份抄件。

### 4.4 遮蔽之后还剩什么（D5 的论证）

遮蔽一个 prelude 方法名之后，用户**没有**别的拼写能调到它。这一节论证这是可接受的，
因为它是本设计最可能被将来质疑的一处，理由写死在这里。

**论证 1：遮蔽是逐模块、逐名字的**。`cx.fns` 每个模块一份（`check_module` 从
`seed_prelude(cx)` 起手，checker.dawn:9797）。impl 是全程序生效的（spec §3.5 的一致性
条款），所以你写的 `impl Show[Money]` 在任何别的模块、在整个 std 里照常被找到。
遮蔽只让**这个模块里这个拼写**指向别处。

**论证 2：trait 的用途不经过那个名字**。每个 prelude trait 都有一条不走 `cx.fns` 的
消费路径，按 trait id 直接找 impl：

| trait | 消费路径 | 位置 |
|---|---|---|
| `Show` | `${…}` / `to_string` | lower.dawn:846、1604-1660 |
| `Eq` | `==` / `!=` | lower.dawn:843、1012-1079 |
| `Ord` | `<` `<=` `>` `>=`、std 的 `sort` 族 | lower.dawn:842-845、1252-1290 的 `cmp_at` |
| `Iter` | `for..in` | lower.dawn:2838-2841（四个 `lower_trait_call`） |
| `Hash` | `Map`/`Set` 的键路径 | `index_wits`（checker.dawn:4127）与字典轨 |

实测 2 已经把这条演示过了：名字被换掉，`${…}` 一动不动。

**论证 3：impl 体里的方法名是声明不是查找**。`impl Show[T] { fn show(x: T) -> String }`
的 `show` 由 `pass_register_impls`（checker.dawn:2583）按 trait id 对表，不经
`lookup_fn_sig`。所以「遮蔽了 `show` 还能不能写 `impl Show`」的答案是能，而且不用想。

**论证 4：候选拼写都要新机器**。

- `Show.show(x)`：表达式位的「大写名 + 点」今天已经有含义（`Class.FIELD` 静态字段，
  2026-07-23 人体工学批）。要么撞车，要么加消歧规则。
- `std/prelude.show(x)`：要让 prelude trait 变成某个 std 模块**声明**的 trait。它们今天
  是编译器构造的（types.dawn:981-1049，固定 id 0–4），身份、pass 顺序、`owner: None`
  全都建立在「不属于任何模块」之上。改这个是另一个项目。
- `use std/prelude.{show}` 之类的再引入：同上，前提是它先属于某个模块。

**结论**：不给限定形。需要两个拼写同时在场时，改自己那个名字——一行，且是你自己的代码。
这与 builtin 今天的成交条件逐字相同（spec §10.6:1619 已经把它当卖点写了）：写了
`fn len` 就再也拼不出 builtin 的 `len`，从来没人要过退路。

**不注入的 trait（`Index`）其方法名仍要被拼写的三个地方**，都不需要全局名：

1. **impl 体**：`impl[T] Index[List[T]] { fn index(…) }`——声明位，论证 3。
2. **`dawn doc`**：trait 条目下列方法，从 `TraitI.methods` 渲染，与命名空间无关。
3. **错误消息**：「`Index` has no method `index`」「`[]` needs an `Index` impl for …」
   ——字符串，与命名空间无关。

### 4.5 参数位的关联类型（D6，回答 trait-v2-design §7.5）

§7.5 留的问题：「trait 方法的关联类型出现在参数位时，这个方法还能不能按名字调用」。

**答案：能，而且今天已经是这样**。`Iter` 的三个方法把 `C.Cur` 摆在参数位
（types.dawn:1034-1043），实测调得动：

```dawn
pub fn main() -> Unit !io = {
  let xs = [10, 20, 30]
  let k = iter_start(xs)
  println(to_string(iter_get(xs, k)))      # 10
  let k2 = iter_next(xs, k)
  println(to_string(iter_done(xs, k2)))    # false
}
```

**但规则要写死：投影只参与检查，不参与推断**。类型参数的推断只看**非投影**的参数位；
主体定下来之后，投影按 impl 的绑定归约，再与实参比对。实测证据——造一个类型参数只出现
在投影里的方法：

```dawn
trait Coll[C] {
  type It
  fn first(c: C) -> C.It
  fn only(k: C.It) -> Int
}
```

`first(b)` 通过；`only(7)` 得两条错误：

```
error: argument type mismatch: expected C.It, got Int
  = hint: signature: fn only[C: Coll](k: C.It) -> Int
error: cannot infer type parameter(s) C for `only`
  = hint: Dawn has no call-site type arguments, so the type has to arrive as an expectation: annotate the binding an argument comes from, or the one that takes the result
```

诊断已经准确，不需要额外机器。**推论**：一个 trait 方法若其类型参数只出现在投影里，
它按名字不可调用；trait 作者应把主体放进参数表（`Iter` 四个方法都把 `c: C` 放在第 0 位，
正是这个原因）。这条进 spec 的 trait 节。

**对刀 3 的意义**：`fn index(c: C, i: Int) -> C.Item` 的主体在第 0 参，两条路都没有障碍。
§7.5 说这个问题「决定第一刀的表示选型」——现在它不决定了。而且叠上 D1 的
`injects: false`，`index` 根本不进函数命名空间，按名字调用的问题在刀 3 上直接消失。

### 4.6 新形状要不要诊断（D7）

改成遮蔽后，「存量程序写了 `fn iter_next` 就编译失败」自动消失（实测 1 的三条错误变
零条）。反向的新形状三种，逐一驳回：

1. **「遮蔽了 prelude 方法却没写 impl」**——那就是一个普通函数。`fn show(x: Int) -> String`
   与 `Show` 没有任何关系，没有可诊断的东西。诊断它等于禁用八个名字，回到原点。
2. **「同一模块既 `fn show` 又 `impl Show[T]`」**——impl 不受影响（论证 3），运算符不受
   影响（论证 2），语义完全清楚。这是个合法且偶尔有用的形状（你的 `show` 做别的事）。
3. **「遮蔽者的签名与 trait 方法不同」**——遮蔽的全部意思就是「我要一个不同的 `show`」。
   要求签名相同等于要求它是个 impl。

净效果：本刀**只减不增**诊断。

## 5. spec 落点

逐条，每条给「今天写的什么」与「改成什么」。

| 条款 | 今天 | 改成 |
|---|---|---|
| §3.5:426-428 | `Iter` 四方法名「随 prelude 注入函数命名空间，**顶层 `fn` 不得重名**（同其余 prelude trait 方法；「遮蔽 builtin/std」的 §10.3 规则不适用于 trait 方法名）」 | 删「不得重名」与整个括号：「四个方法名随 prelude 注入函数命名空间，与其余 prelude 名同待遇——**可被本模块的声明遮蔽**（§10.3）」 |
| §3.5 新增 | — | 「**注入是逐 trait 的属性**：一个 trait 的方法名是否占据函数命名空间由该 trait 决定。今天五个 prelude trait 全部注入；由运算符独占消费的 trait（如 `[]` 背后的那个）不注入，其方法名只在 impl 体、文档与错误消息里出现。」 |
| §3.5 新增（trait 节） | — | 「**关联类型出现在参数位不参与推断**：类型参数由非投影的参数位定，投影随后按 impl 绑定归约再比对。类型参数只出现在投影里的方法按名字不可调用。」（D6） |
| §6.5:982 | 「操作名进入模块的函数命名空间：与普通函数同名即重定义错误，`pub effect` 的操作随 `use m.{Ask}` 一起进来」 | 补齐三档：与本模块任何顶层声明（fn / trait 方法 / 另一个效果的操作）同名 → 错误；与**另一处引入**的名字（含另一个效果的操作）同名 → 错误；与 prelude 名同名 → 遮蔽。第二档今天一句都没兑现（实测 3）。 |
| §10.3:1574-1575 | 「**与 prelude 名冲突**：选择性引入**可以**遮蔽 prelude」 | 保留，把「prelude」明确成「prelude 名，**包括 prelude trait 的方法名**」 |
| §10.3:1575-1576 | 「**顶层 fn / trait 方法**也可以遮蔽 builtin/std 的**函数**名（Rust 式）」 | 「的**函数**名」三字删掉，主语补全：「顶层 fn / trait 方法 / 效果操作可以遮蔽 builtin、std 与 **prelude trait 方法**」 |
| §10.3:1577 | 「故遮蔽在本模块内是全量的：被遮蔽的拼写在该模块不可达，这是声明者自己的选择」 | **这句今天就不成立**（实测 2）。改成：「遮蔽只作用于**这个拼写**：被遮蔽的拼写在该模块不可达。运算符与糖（`==`、`${…}`、`for..in`、`[]`）按 trait 找 impl、不经名字，因此**不受遮蔽影响**——遮蔽 `show` 不会改变 `${x}` 的输出。」 |
| §10.6:1619-1623 | 「**prelude trait 的方法名除外**：`cmp`/`eq`/`hash`/`show` 与四个 `iter_*` 随 prelude 进入函数命名空间，顶层 `fn` 重名是声明期错误（trait 方法共享函数命名空间，§3.5）」 | 整段反转：「prelude trait 的方法名与 builtin/std 名同待遇——随 prelude 进入函数命名空间，**可被本模块的声明遮蔽**。全集见 `dawn doc --builtins`。」（顺手让 spec 不再手抄八个名字，见 §4.3） |
| §10.6 新增 | — | **本设计的产出条文**：「**prelude 追加是兼容的**：往 prelude 加名字不会让任何已通过检查的程序失败——新名要么没被用到，要么被本模块的声明遮蔽。这条是 prelude 可以演进的前提。」 |

`docs/trait.md:246` 提到 prelude 交互，一句话跟改；`docs/tutorial.md` 未涉及，不动。

## 6. 分期与验收

三刀，都不改 lowering、不改 Core、不改 emit、不改 std 签名。

### 刀 A — 一张表 + `injects` 字段（纯重构）

- types.dawn：`TraitI.injects`（五个 prelude trait 与 `prelude_trait()` 辅助全填 `true`）、
  `prelude_trait_ids()`、`is_prelude_trait_name()`。
- checker.dawn:1594 / 2313 / 2421-2434 / 10515-10525 读表读字段。
- lspc.dawn:260 遍历 `prelude_traits()`。

**行为变化只有两条**：`trait Show` / `trait Iter` 的报错文本订正；LSP 补全多四项。

**验收**：`selfhost-fixpoint.sh` 绿；`selfhost-core-diff.sh` + `core-golden/` 逐字节不变
（本刀不碰 lowering，Core 必须一字不差）；`selfhost-run-diff.sh` 绿；
**`selfhost-lsp-diff.sh` 会红**，声明 `Emit-Change(lsp *)`——补全项是它的输出。
新增内联 test：五个 prelude trait 名逐个撞 `trait X` 都得到 prelude 那条消息。

> 验收纪律引自 #110 的教训：差分脚本在**未 `git add`** 的树上跑等于没跑。三刀的
> 差分一律在 add 之后跑。

### 刀 B — 一道门

- `Origin` 类型 + `Cx.fn_origin` + `bind_fn`。
- 六个写入点全部改走 `bind_fn`；第 3 号（效果臂，checker.dawn:5101-5109）同时
  把操作名登记进 `imported_names`（D8）。
- `alias_shadows` 前置检查升格到 `OImport`。

**行为变化两条**：

1. 效果操作重复引入由静默变错误。拒绝的是**今天没有稳定语义**的程序（实测 3：`use`
   顺序决定语义）。**验收项**：`selfhost/src`、`std/`、`packages/`、`backend-dawn/`
   全仓无此形状——实测确认，不是推断。
2. 本地声明撞已引入的操作名，诊断文本由「defined twice」变 `import_clash` 措辞
   （实测 4 的误导修掉）。

**验收**：同刀 A 的四件差分；新增语料 `effect_op_import.dawn` 钉住实测 3、实测 4 两个
形状（前者从「两种输出」变「一条错误」，后者钉新文本）。

### 刀 C — 遮蔽

- `bind_fn` 的 `OPrelude` 行改成静默写入（一格）。
- 删掉第 4/5/6 号写入点里「已经是 prelude trait 方法」那一支的报错——注意它今天与
  「已经是**用户** trait 方法」共用一条文本（checker.dawn:2426-2432、3234-3240 的
  `match prev.trait_id`），只反转 prelude 那一半。
- lspq.dawn 加 hover 提示（D3）。

**行为变化**：接受集**单调变大**，没有任何原本能编译的程序改变含义——这是「存量逐字节
不变」的机器证明形式：

| 判据 | 怎么验 | 为什么足够 |
|---|---|---|
| Core 逐字节 | `selfhost-core-diff.sh` + `core-golden/*.core` | 遮蔽只改「名字解析到谁」。存量程序没有遮蔽形状，解析结果不变 → Core 必逐字节相同。Core 是编译器输出的第一个稳定表示，比对它比比对字节码更早暴露分歧 |
| 运行输出 | `selfhost-run-diff.sh` | 跑得起来的语料输出不变 |
| 格式化 | `selfhost-fmt-diff.sh` | 本刀不动 fmt，必须全绿；红了说明碰了不该碰的 |
| LSP | `selfhost-lsp-diff.sh` | hover 文本变化 → 声明 `Emit-Change(lsp *)` |
| N−1 编译 HEAD | `selfhost-prev-diff.sh` | 本刀只放宽接受集，HEAD 不使用新自由度 → 必绿 |

新增语料 `shadow_prelude.dawn`：八个 prelude 方法名各写一个同名顶层 `fn`，加一个
`impl Show[T]` 与一处 `${x}`，钉住「名字走本地、糖走 impl」。

**种子**：三刀都不改 std 签名、不改 emit → **不需要三期两发布**。若将来 std 或
`selfhost/src` 真的想用遮蔽（不建议，见 §8 开放问题 3），那才是种子事件。

**落地偏差（2026-08-02）**：

- 语料落在 `scripts/spike-native/shadow_prelude.dawn`（+ `.expect`），因为那套
  harness 只用 HEAD 编译器跑，加一个文件不会在 N vs N−1 的差分里制造假分歧
  ——而「存量零分歧」正是本刀的核心判据。另加两条内联 test 钉住检查器一侧的事实；
  `for..in` 进不了内联 test（`Iter` 的 impl 全在 std，无 std 的 fixture 迭代不了
  任何东西），由语料覆盖。
- §5 让 spec 把方法名全集指向 `dawn doc --builtins` 的那一条**没有照落**：实测
  `doc.dawn` 只渲染 builtin 表与 std 模块，prelude trait 的方法根本不在输出里，
  这个指针今天不成立。改成指向 spec 自己的 §3.5（五个预置 trait 及其方法就声明在
  那儿，是规范文本），§10.6 因此不再手抄八个名字，去重的目的照样达成，且不必为一句
  措辞给 `dawn doc` 加一类新条目。给 prelude trait 方法做 doc 渲染是「标准库发现性」
  那件事的一部分，不是本刀的。
  **补记（2026-08-02）**：那件事做了——`dawn doc --stdlib` 与站点 `/stdlib` 页把五个预置
  trait 连同方法签名渲染出来了，所以 §10.6 的指针已改回指向该页（§3.5 仍是规范定义处）。
- D3 的 hover 提示未做（本刀交付范围由任务书界定为规则表、spec、测试三项）。
  编译器静默这一半已落地，是 D3 的实质部分；LSP 那半留在 §8 开放问题 1 旁边。

## 7. 与刀 3 的接口

刀 3（运算符 trait，`[]` 背后的 `Index`）动工时可直接消费的三件：

1. **`TraitI.injects` 已在**：`Index` 建成 `injects: false`，`index` 不进任何模块的函数
   命名空间，不占全局名，不需要撞名勘察。
2. **prelude 表已收成一张**：加一个 trait = 改 `prelude_trait_ids()` 一处 + 在
   `prelude_traits()` 里建它。四份抄件的时代结束。
3. **D6 已答**：`fn index(c: C, i: Int) -> C.Item` 的形状不受推断规则限制，
   trait-v2-design §7.5 的前置条件②销账。

并且 **D1 给刀 3 兜了底**：往 prelude 加 `Index` 不可能破坏存量程序——它不注入，
连遮蔽都用不上。

刀 3 自己的账，本设计不裁：`index_wanted`（本基线 checker.dawn:4111-4121，唯一调用点
6055——trait-v2-design §7.5 记的 3274 是它那时的位置，别照抄）
的两条硬编码 arm 退休时改查 `impl_table` 的 `INDEX_ID`；`impl[T] Index[List[T]]`
的体走 `get(…).expect(…)`（多一次 `Option` 分配，要量）还是走 `prim_relation` 臂
（arm 从 checker 挪到 lower，还要自带解释器臂），是 trait-v2-design §7.5 那张表的题目。

## 8. 开放问题（不阻塞，留档）

1. **warning 诊断档**。D3 的备选。代价清单：`Diag` 加 severity（token.dawn:104）、
   `render` 的 `"error: "` 字面量（diag.dawn:71）、LSP 的 `JInt(1)`（lsp.dawn:628）、
   外加策略题「CI 允不允许有 warning」「要不要 `--deny-warnings`」「std 自己有没有
   warning」。有真需求再立项。若立了，第一个 warning 就是「本地声明遮蔽了 prelude
   方法 `Show::show`」。
2. **用户可声明的不注入 trait**。字段已在 `TraitI`，缺的只是表面语法。没有消费者，
   不做。
3. **std / selfhost 自己使用遮蔽**。技术上刀 C 之后就允许，但那会让「哪个 `show` 生效」
   在编译器源码里变成一个要查的问题。约定：**不用**。这条不需要机器强制——用了也只是
   自找麻烦，不影响别人。
4. **`cx.std_fns` 与 builtin 两层的追加兼容性**。本设计只处理 prelude trait 方法这一层。
   那两层今天已经是遮蔽档，天然追加兼容；但「两个 std 模块 pub 同名短名」这类事
   （spec §10.6 的「同名短名跨模块共存」）不在本设计范围。
