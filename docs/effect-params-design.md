# 效果参数（RX-10-B）设计

> 状态：**current，五刀全部落地**（刀 5 于 2026-08-20 落地，A″ 关联效果 + 规则丙；
> 刀 1 `cf725f4`，刀 2-4 见 git）。**决策 5 已裁（2026-08-19，A0 + A″）**，条文见下；
> **刀 5 拼写已按跨语言调研修订为 A″ 关联效果（2026-08-19）**：规则丙的运行时机制一字未改，
> 改的是「这个效果叫什么、写在哪」。调研、四问终审与重开条件都在决策 5 里。
> 刀 5 的落地记录（含实测修正与三处偏离）在刀 5 节末尾。
> RX-10 期权 A 的裁决见 [audit/re-audit-2026-07-30.md](audit/re-audit-2026-07-30.md)
> 第 593 行，B 的原始定义见 [audit/re-audit-b-decisions.md](audit/re-audit-b-decisions.md)
> 第 560 行起。
>
> 文内的 `file:line` 一律对 `cf725f4` 实测。刀 1 动过 `passes.dawn` 与 `checker.dawn`
> 的行号并逐条重定位过；**刀 2-5 又动过 types / checker / passes / lower / emit / emitc**，
> 此后行号以符号名为准查现树，不再逐条刷新——设计已落地，正文自此是历史记录。

## 1. 范围：三件载荷，一件出局

RX-10-B 在两份来源文档里累积了三件互不相同的载荷，两份文档从未对账。

| 载荷 | 首次命名 | 性质 |
|---|---|---|
| 一、可命名的效果多态类型（`alias Mapper[T, U, !e]`、`type Box[!e]`） | `audit/re-audit-b-decisions.md:560-564` | 纯检查期 |
| 二、trait / impl 方法带效果行 | `audit/re-audit-b-decisions.md:585`、`effects-design.md:376-379` | ABI 变更 |
| 三、`effect Yield[T]` | `effects-design.md:42-44`、`:376-379` | 另一根轴 |

**裁决（本文定，不重开）：载荷三 `effect Yield[T]` 出局，另立任务。**

理由是两者方向相反。载荷三是把 `Ty` 塞进 `Eff`，代价写在
`effects-design.md:42-44`：「会让 subst 的类型/效果双 map 互递归、`Map[Eff, …]` 的键全动」。
载荷一与载荷二是把 `Eff` 塞进类型参数列表，代价写在 `audit/re-audit-b-decisions.md:561-564`。
一个动效果轴的内部结构，一个动类型参数列表的成员种类。
[assoc-types-design.md](assoc-types-design.md) 第 158 行已经就同一件事判过：
「RX-10-B（效果参数进类型参数表）：正交；`type Item` 是类型轴成员，效果轴另说」。

把两者当一件任务是文档的错误，且只发生在两处：`effects-design.md:42-44` 的非目标行、
以及同文 §7 开放项 5（`:376-379`）。这两处已随本文改正。载荷三另立任务号，判据是
「`Eff` 要不要带类型参数」，与本文无前后置关系。

**同时出局**：行多态（row polymorphism）。裁决已在 `effects-design.md:56`（D4）：Dawn 无
行多态，handler 因此走语法形式而非一等值。本文不重开，效果参数是**参数**，不是行变量。

## 2. 结构事实：效果变量已存在，`Sig` 里的位置由刀 1 补上

这一节先于任何语法讨论，因为它决定了第一刀的形状。刀 1 已落地（`cf725f4`），本节相应改成
落地后的样子，「曾经没有表示」那一段留着，因为它是这一刀的理由。

**效果变量今天就是一等 `Eff` 构造器。** `EffVar(name: String, id: Int)` 在
`selfhost/src/check/types.dawn:29`，由 `fresh_effvar` 铸造，`resolve_eff_at`
（`selfhost/src/check/cx.dawn:435-469`）在遇到未登记的小写原子时**隐式**铸一个并存进
`cx.current_eff_vars`（`:452-463`）。这是 `docs/spec.md:1280`「效果变量 `!e` 无需声明，
在签名中出现即引入；作用域是整条签名」的实现。大写未知原子是错误（`cx.dawn:445-448`），
诊断里写着「effect variables are lowercase」。

所以 RX-10-B 不是「引入一个跨效果的变量」。它是「给这个变量一个显式绑定者，和一个
比一条签名更大的作用域」。

**这个变量在 `Sig` 里曾经没有任何表示，刀 1 给了它一个。** 落地前的形状是：`Sig` 只有
`eff: Eff`、`tparams: List[Ty]`、`constraints: List[List[Int]]`，签名的效果变量表走一条
**侧信道**（`pass_fn_signatures` 把 `cx1.current_eff_vars` 抄进一条与 `sigs` 平行的 `evs`
列表当第三个返回值交出去，消费方 `enter_fn` 把它当独立形参收下）；两处拒绝则把这条侧
信道当谓词用，问的是「解析过程往一张刚清空的临时表里写过没有」，而不是「这条签名声明了
什么」。

今天（`cf725f4`）`Sig` 有 `eparams: List[Eff]`（`types.dawn:1024`，字段注释 `:1014-1023`
写明为什么它不能混进 `tparams`），由 `eff_params_of`（`types.dawn:91-105`）从签名自己那张
表里取出、按效果 id 排序；`enter_fn`（`checker.dawn:8316-8324`）从 `s.eparams` 重建表，不
再收第三个参数；`pass_fn_signatures`（`passes.dawn:2044`）的返回类型回到 `(Cx, List[Sig])`。
两处拒绝现在问 `len(sig.eparams) > 0`（`passes.dawn:1275`、`:1765`）。

**顺序是契约，且被测试钉住。** `eparams` 的序是**铸造序**，也就是 `resolve_eff_at` 头一次
遇到某个名字的次序：`fresh` 递增发 id，每个名字至多铸一次，所以按 id 排序就是首次相遇序。
展开来是「先声明行、再参数类型从左到右、最后返回类型」，注意行是写在最后的，所以首次
**相遇**不等于首次**出现**。这段推理逐字写在 `types.dawn:71-90`，由
`passes.dawn:2195` 的内联测试钉住。后续任何要按位对齐两条签名效果变量的检查（见决策 5 的
问题四）都以这个序为准。

（另有四处只装空表、不问漏没漏，用途是隔离而非判断：`passes.dawn:1050`、`:1542`、`:2067`、
`:2257`，以及 alias 目标解析的 `cx.dawn:550-554`。它们不是探针，改绑定者机制时不必动。）

**证据通道本身已经完工。** 一个签名写出的每个标签在 `bind_evidence`
（`checker.dawn:8365-8375`）声明一个隐藏局部，`ev_sym_list`（`:8377-8387`）按效果 id 收齐，
经 `TFun.ev_syms`（`selfhost/src/check/tast.dawn:259`）→ `CFun.evs`
（`selfhost/src/ir/core.dawn:261`）→ `lower_fn`（`selfhost/src/ir/lower.dawn:3481`，证据在
`:3495-3500`）到两个后端（`selfhost/src/jvm/emit.dawn:1247`，描述符 `:394-407`；
`selfhost/src/c/emitc.dawn:1747`、`:1767`）、解释器（`selfhost/src/ir/interp.dawn:675`）
和 Core dump（`selfhost/src/ir/coredump.dawn:161`、`:430`）。调用侧的附加序是
`vs ++ ds ++ es`（`lower.dawn:2812`、`:2818`）：实参、字典、证据。

缺的不是通道，是「效果能当参数」和「字典槽位能上这条通道」。

## 3. 决策点

编号沿用勘察，便于任务登记按号引用。决策 11 已在 §1 结清（出局）。

### 决策 1（已定，刀 1 已落地）：效果参数用 `Sig` 的**新分量**，不进 `tparams`

**裁决：新增分量 `eparams`，不在 `tparams` 里混。**

强制它的是三处代码，不是审美。

`tparams: List[Ty]` 的元素类型是 `Ty`（`types.dawn:1011`），`Eff` 不是 `Ty`，混进去要么加和类型
要么加平行字段。而 `constraints: List[List[Int]]`（`:1013`）与 `tparams` **按位对齐**
（`bounds_of`，`:1036-1040`）：

- JVM 的字典元数是把 `constraints` 的各段长度求和得来的（`emit.dawn:397-398`）；
- `bind_dicts` 用 `tparams` × `bounds_of(s, i)` 双层遍历（`checker.dawn:8257-8258`），
  内层是 `match tp { TyVar(tn, vid) -> … ; _ -> () }`（`:8259-8281`）。

关键在那个 `_ -> ()`（`checker.dawn:8280`）：一个不是 `TyVar` 的 `tparams` 条目会被**静默跳过**，
而外层的 `i` 照样递增。于是 `constraints` 的下标与 `tparams` 的下标错位，字典符号绑到错的
类型变量上，编译期不报任何错。混合列表会「看起来能用」，然后是错的。

独立分量把「字典轨一行未动」变成可证的，而不是可辩的：`constraints` 与 `tparams` 的对齐关系
逐字不变，字典元数的求和式逐字不变。

**代价已量，也已实付**：预估是 20 处逐字段列出的 `Sig { … }` 字面量分布在 6 个文件，实测
落地时是 **16 处**、5 个文件（`checker.dawn` 6、`passes.dawn` 4、`types.dawn` 3、
`lower.dawn` 2、`interp.dawn` 1）。差额在 `emit.dawn`：预估把它算进来了，而它唯一一处
`Sig` 构造是 `Sig { ..s, … }` 展开式（`emit.dawn:503-507`），展开式不受影响，所以刀 1 一个
字节都没改它。`evs` 侧信道同批退役。

### 决策 2：绑定者是强制还是可选，即 `spec.md:1280` 的隐式引入是否存活

**推荐：可选。保留隐式引入，显式绑定者是它的等价写法。**

强制的代价已重新实测（基线 `098419d`，排除 `selfhost/src/embed/stdsrc.dawn` 与
`rtsrc.dawn`，两者是生成的内嵌副本，计入会重复计数）：

| 位置 | 效果变量原子数 | 需加绑定者的 `fn` 声明数 |
|---|---|---|
| `std/list.dawn` | 32 | 16 |
| `std/pvec.dawn` | 10 | 5 |
| `std/` 其余全部 | 0 | 0 |
| `selfhost/src`（真实声明位） | 0 | 0 |

`std/` 的其余模块只写 `!io`，`!io` 是具体的内建效果，不需要绑定者。`selfhost/src` 里所有
小写效果原子都在**测试夹具的字符串字面量**里（`checker.dawn:9307`、`:9314`、`:9320`、`:9506`、
`:9605`、`types.dawn:2709`、`:2835-2836`、`fmt.dawn:604`、`:608`）或诊断文案里
（`cx.dawn:578`），没有一处是编译器自己的签名。

于是「强制」的账是：21 个 std 签名 + 约 8 条夹具字符串，**且因为改的是 `std/`，要一轮种子**
（见 §4 对种子轮的定义）。「可选」的账是：一处名字有两种引入方式。

推荐可选的理由是这笔账不划算，且「两个绑定者」的担忧不成立：两种写法进的是同一张表
（`cx.current_eff_vars`），不构成遮蔽。规则一句话：**签名自带显式绑定者时，该名字在这条
签名内只解析到它；没有时照 `spec.md:1280` 隐式引入。** `resolve_eff_at` 的隐式铸造臂
（`cx.dawn:452-463`）在前者下不再触发，因为查表就命中了。

若日后要收紧成强制，那是一次独立的破坏批，代价是上表这 21 处，不必现在付。

### 决策 3：语法，以及它如何不与今天的 `!e` 相撞

**推荐：`[T, U, !e]`，效果参数用 `!` 前缀，与效果行的拼写一致。**

`type_params`（`selfhost/src/front/parser.dawn:410-445`）在参数位要 `TYPEIDENT`（`:418`），
效果变量按规则是小写（`cx.dawn:445-448`），所以裸小写 `[T, e]` 在语法上可行但**看不出来**
是效果参数，排除。`[E: Effect]` 与 trait bound 的产生式相撞（`parser.dawn:421-431`），排除。
`!` 在 `[` … `]` 里今天不能开始任何东西，无语法冲突。

必须核对的是 formatter 的 `!` 消歧。`postfix_bang`（`selfhost/src/front/fmt.dawn:169-183`）
靠**后面跟什么**区分效果标记与后缀解包，`is_effect_name` 收 `IDENT` 与 `TYPEIDENT`（`:189`）。
`[T, !e]` 里 `!` 后是 `IDENT`，会被判成效果标记并紧贴打印，正是需要的结果。这是一次
**幂等探针**而不是一次改动；先例是 `assoc-types-design.md:161`（「fmt 免费正确（词法级，
`type` 行与 `T.Item` 实测幂等，零改动）」）。

**范围（2026-08-19 修订）**：本条只管 `fn` / `alias` / `type` 的参数表（刀 2、刀 3）。
**trait 不走参数表**，效果在 trait 上是体内成员 `effect E`、在 impl 上是体内绑定
`effect E = !X`（决策 4 与决策 5 的 A″）。行里的投影 `!C.E` 要**另跑一次同款幂等探针**：
那里 `!` 后跟的是 `TYPEIDENT` 再跟 `.`，`is_effect_name` 两种都收（`fmt.dawn:189`），
但 `.` 之后的成员名怎么贴要实测，`T.Item` 的先例只覆盖了不带 `!` 的那一半。

### 决策 4：哪些声明形式带参数表，形状如何

**这是整个特性最大的分叉。** 今天四种声明形式里三种没有可扩展的列表：

| 形式 | 今天的形状 | 证据 |
|---|---|---|
| `fn` | `tparams: List[TypeParamDecl]`，带 bound | `selfhost/src/front/ast.dawn:328` |
| `alias` / `type` | `tparams: List[String]`，bound 在解析时被丢掉 | `ast.dawn:346`、`parser.dawn:486-492` |
| `trait` | **单个** `tp: String`，外加体内的关联类型成员（#44 已落地，`TraitI.assoc`，`types.dawn:1083`） | `ast.dawn:396`、`docs/grammar.ebnf:78` |
| trait 方法 | **没有**类型参数表 | `docs/grammar.ebnf:83-84` |
| impl 方法 | 明确禁止类型参数表 | `docs/grammar.ebnf:85-86` |

**裁决（2026-08-19 按跨语言调研修订）：`fn` / `alias` / `type` 的效果参数进参数表；
trait 一张效果参数表都不开，效果在 trait 上是体内成员。** 旧稿的推荐是
「效果参数挂在 trait 上（`trait Parser[S, !e]`）」，A″ 把它换成：

```dawn
trait Parser[S] { effect E   fn next(s: S) -> Option[(S.Tok, S)] !S.E }
impl Parser[StrSrc] { effect E = !()  ... }
```

理由是决策 5 的那五条，其中两条直接对应本条的分叉：**一**、效果在 trait 边界上是**输出位**
（推论三），写进输入位的参数表是 RFC 195 记过病历的形状，调研里 trait 参数表零票；
**二**、trait 体内成员这条路是**现成**的，#44 的 `type Item` 已经把声明位、impl 体内绑定位、
投影位、exactly-once 覆盖检查、归约门全部铺好了，A″ 只是把它复制到效果轴，而开参数表要新增
第二种参数种类与第二套绑定者作用域。

旧稿三条理由里有一条**与拼写无关、原样保留**：「一行管全 trait」的粗粒度只在拼写上，不在
ABI 上。方法的证据参数是按**它自己的 `Sig.eff`** 合成的（`bind_evidence` 读
`eff_labels(s.eff)`，`checker.dawn:8367`；描述符同理，`emit.dawn:403-406`）。同一个 trait 里
不提该效果的纯方法，`Sig.eff` 仍是 `EPure`，不多一个参数。**纯兄弟方法不为它付任何运行时
代价**，这一点在 A″ 下更明显：方法要不要证据，看的是它自己的行里有没有写 `!S.E`。

另两条随拼写作废：「trait 本来就要改一张列表」不再是理由（trait 的类型参数表照旧只有一个，
不动）；「trait 级的一行让哪些槽位要证据成为静态属性」在 A″ 下由**投影出现在哪些方法行里**
承担，同样是 trait 声明的静态属性，结论不变而载体换了。

**不给 trait / impl 方法新开类型参数表**这一条不变（`grammar.ebnf:83-86`）。
`alias` / `type` 的参数表本来就要从 `List[String]` 加宽（决策 8 的刀里一起做），
`fn` 的 `[T, U, !e]`（决策 3）也不变。

### 决策 5（枢纽，已裁 2026-08-19）：效果参数在单态调用点被实例化时，谁供证据

**裁决：A0 + A″。** 机制是下面的**规则丙**：一个声明级效果参数恒定合成恰好一个隐藏证据
参数，在字典槽位边界上擦除，由 impl 侧的 bridge 适配回来，供给方永远是调用方、在调用点。
A0 是它的同批伴生件：**trait / impl 方法的行可以携带普通的每签名效果变量**，零证据、零
描述符变动。两者的关系是子集：A0 只放开「行里能不能出现效果变量」，A″ 才把效果提升成
trait 的一个声明成员并为它买单。

**拼写在同一天被修订过一次，机制没有。** 上午的裁决写作 A0 + A′，A′ 的拼写是给 trait
开一张效果参数表（`trait Parser[S, !e]`）。当天的跨语言调研（下一节）把拼写改成
**A″「关联效果」**：效果是 trait 体内的一个成员 `effect E`，由 impl 在体内绑定，消费者在
行里写投影 `!S.E`：

```dawn
trait Parser[S] {
  effect E
  fn next(s: S) -> Option[(S.Tok, S)] !S.E
}
impl Parser[StrSrc]  { effect E = !()  ... }
impl Parser[FileSrc] { effect E = !Ask ... }
fn many[C: Parser](c: C) -> List[C.Tok] !C.E
```

（纯的绑定怎么拼，`effect E = !()` 还是允许省略，是刀 5 的语法条文，本文不定。）

改拼写的五条理由：

1. **拼写与语义一致。** 推论三（下）已经把效果实参判成**输出位**：由 impl 唯一确定、不参与
   选 impl。A′ 把一个输出位的东西写进输入位的参数表，而这正是 RFC 195 描述的那个病，
   Rust 与 Haskell 各自迁过一遍（引文见下一节）。
2. **少一个概念。** A″ 复用 #44 的全套机器：`TraitI.assoc`（`types.dawn:1083`）、
   `ImplI.assoc_bindings`（`:1274`）、`subst_subject`（`lower.dawn:939`、`emit.dawn:494`）、
   `reduce_assoc`（`checker.dawn:457`）。trait 的第二张参数表、新的参数种类、新的绑定者
   作用域全都不需要。
3. **消掉双寻址路径。** A0 的 `!e`（调用者的、零证据）与 A″ 的 `!C.E`（impl 的、一格证据）
   拼写上字面可辨；A′ 下两者都写作 `!e`，只能靠「它在哪张表里被绑定」区分。
4. **问题二按构造消失**（见下）。
5. **落点不变。** 刀 5 的描述符与 bridge 五处落点（JVM 四处、C 一处）与 A′ 方案逐处相同，
   一处不增不减；`dict_key`（`lower.dawn:930`）仍是零字节改动。

代价据实两条。**一**：`Eff` 要加一个投影构造子（详见刀 5），**二**：`subst_ty` 作用在一个
带 bound 的类型变量上时必须触发效果侧归约，这是一条新的轴间接触面，**落刀前先实测**。
若实测显示这条耦合比预估贵，退路是 A′ 参数拼写（重开条件见本节末）。

裁决的输入是 2026-08-19 的三份勘察（决策 5 备忘录、#208 证伪探针、跨语言调研，均在私有
handoff 目录，不入库）：备忘录给出候选表与规则丙条文，探针拿 12 个真跑的程序检验输出位
读法未被证伪、同时找出 A′ 覆盖不到而 A0 覆盖得到的那一族形状，调研定拼写。

#### 跨语言调研（2026-08-19）：拼写为什么从 A′ 改成 A″

调研（opus subagent 用 WebSearch 产出，主会话验收）扫的是十门语言在「接口边界上怎么抽象
效果」这一格的实际做法。原始档在私有 handoff 目录、不入库，所以本节把承重的部分整个搬进来：
汇总表、四条铁律、最承重的几段逐字引文、来源。**本节要能独立读懂，不许把那份档当承重件。**

**验收口径。** 两条最承重的引文由验收方独立复核成立：doc.flix.dev 的 `type Aef: Eff` /
`type Aef = { … }` 与 Dividable 例、RFC 195 的输入位/输出位定义。查出一处小偏差：
**RFC 195 原文没有点名 `Item`**，它只以 `Iterator<A>` 作输出位的例子，`type Item` 是后来
std 迁移的产物，本文按此更正。一处实质更正：报告把「A″ 依赖 #44」列为主要代价，而 **#44
已落地**（上面第 2 条列的四处都在树上，#208 探针的 p5 跑通的就是它），这笔代价已付。
取证边界：Flix 的 PLDI'24 论文正文取不到（ACM DL 403），Flix 部分用官方文档、api.flix.dev
与作者 LambdaDays 2025 讲稿取证；关联效果的上界与默认值细则无一手依据，按未证实处理，
所以 A″ 的 v1 既不给 `effect E` 开上界也不给默认值。

| 语言 | 接口是否抽象效果 / 怎么拼 | 效果由谁定 | 相等还是包含 | 证据表示 | 与一致性的互动 |
|---|---|---|---|---|---|
| Flix | trait 体内 `type Aef: Eff`，方法行写 `\ Aef[t]` | impl（`type Aef = {DivByZero}`），输出位 | 关联效果按相等绑定；instance 定义处另有子效果 | **不传证据**，handler 动态作用域运行期查找 | instance 形状规则与 `spec.md:603-608` 同款，效果不能当 impl 选择器 |
| Swift | `throws(E)`；协议侧 `associatedtype Failure: Error` | 泛型参数=调用方；associatedtype=遵从方 | **包含**，非抛满足抛；`throws(Never)` = 非抛 | 无（异常机制） | associatedtype 是输出位，不参与协议选择 |
| Rust const traits（RFC 3762） | `const trait` / `const impl` / `T: [const] Trait` | impl（写在 impl 头），输出位 | 更纯的 impl 满足更弱的 bound | 无，RFC 明确不把效果当类型系统泛型参数 | 一个 (trait, type) 仍只有一个 impl |
| Rust keyword generics（草案） | `#[maybe(async)] trait Read`，impl 头 `impl async Read for T` | impl；函数侧调用方选 | 未定（文档明说） | 未定 | 明文：一个类型只能实现 effectful 或 base 变体之一 |
| Koka | 无 trait，行变量 `<exn\|e>` | 调用方 | 行合一（等价非子类型） | **证据向量**按标签规范序，每函数多收一个向量参数 | 不适用 |
| Effekt | 有 interface，**无效果变量**，二等 block 参数做语境多态 | 调用点上下文提供能力 | 不适用 | **一效果一能力**，调用点作隐藏实参传入 | 无一致性规则 |
| Unison | 无 typeclass，`->{e}` | 调用方 | 空能力集禁止能力 | 运行期 request / handler | 官方不做 typeclass 的理由正是一致性 |
| Haskell MTL | `class Monad m => MonadState s m \| m -> s`，效果是类的**输入参数** | 调用方 / 上下文 | 按 head 解析实例 | 字典 | **反面教材**：fundep 补确定性，16 个实例 13 个是提升样板 |
| Scala 3 CC | 类 / trait 的抽象捕获集成员 `type X^`，可带界 | 实现方（成员），输出位 | **subcapturing**（包含） | 能力是普通 term 参数（`using fs: FileSystem`） | 无 coherence 规则 |
| OCaml 5 | 否，类型完全不追踪 | 无 | 无 | 运行期 `Effect.Unhandled` | 不适用 |

**铁律一：效果写在哪，trait 参数表零票。** 体内成员三票（Flix `type Aef: Eff`、Swift
`associatedtype`、Scala 3 CC 的 `type X^`），impl 头两票（Rust 两套），Koka / Unison 只有
方法行，Effekt / OCaml 无。**写过参数表的两家都迁走了，且各留了一手文档**：Rust 的 RFC 195
把 `Iterator<A>` 的 A 挪成关联类型，Haskell 的 MTL 至今把效果写在类的输入参数位、靠
fundep 补确定性。A′ 正是这两家迁走之前的形状。

**铁律二：trait 边界一律输出位。** 在接口上抽象效果的语言，全部让 impl 定效果；输入位只
出现在自由函数的泛型参数上。没有一门语言让调用方独立于 impl 去选 trait 方法的效果。这是
推论三（一致性推论）的独立背书。附带一条：凡有一致性规则的语言，效果实参都被逼成输出位；
Unison 因为一致性干脆不做 typeclass；Effekt 与 Scala 3 没有一致性规则，所以能力可以是自由值。

**铁律三：一致性检查处一律包含。** Swift 的非抛满足抛，Rust 的更纯 impl 满足更弱 bound，
Scala 的 subcapturing 空集是子集。Flix 拆成两半：关联效果成员**按相等**绑定，「更纯的实现
可以过」是独立的**子效果**机制，只在 lambda 与 instance 定义两处开，顶层函数不许
（「Flix supports *sub-effecting* … in two cases: for (a) lambda expressions and
(b) instance definitions.」）。没有一门在一致性检查处要求相等。这条落成问题一的答案。

**铁律四：证据表示三分，Dawn 的两个出局候选各得一手背书。** 三种做法是规范序证据向量
（Koka）、一效果一能力调用点交出（Effekt，即规则丙）、不传证据靠动态 handler 查找（Flix）。
候选 C（证据向量）的病历是 Koka 自己写的（Evidently 论文的 §6.3，正是 Dawn 的情形 III）：

> for any functions with a closed effect, the offset of all evidence is constant. Only
> functions that are polymorphic in the effect tail need to index dynamically. Details …
> left to future work.

候选 B（按效果行单态化）的病历是 RFC 3762 自己写的：「we do not track the effect as a true
generic parameter in the type system」，理由是那会「cause two entirely separate MIR bodies
to be generated」。**而 Flix 的自由抄不了**：它能让一个关联效果装下一整个标签集合，是因为
它根本不传证据（「Flix effect handlers use dynamic scope, deep handlers, and support
multiple resumptions.」），那正是 Dawn 已否的候选 D。**拼写可以抄，问题三上的自由抄不了。**

**逐字引文（承重的四组）。**

Flix（doc.flix.dev；LambdaDays 2025 讲稿）：

```flix
trait Dividable[t] {
    type Aef: Eff
    pub def div(x: t, y: t): t \ Dividable.Aef[t]
}
instance Dividable[Float32] { type Aef = { Pure } ... }
instance Dividable[Int32]   { type Aef = { DivByZero } ... }
```

「An associated effect is an abstract effect member of a trait.」instance 形状：
「An instance type must be a type constructor applied to zero or more distinct type
variables.」stdlib 里两机制同现一行（api.flix.dev 的 Foldable，本调研最有分量的实证，
问题三的作用域依据）：

```flix
def forEach(f: a -> Unit \ ef, t: t[a]): Unit \ ef + Aef[t]
def size(t: t[a]): Int32 \ Aef[t] with Foldable[t]
```

`ef` 是普通的每签名效果变量（调用方、输入位，对应 Dawn 的 A0），`Aef[t]` 是关联效果
（impl、输出位，对应 Dawn 的 A″），拼写不同、同现一行、缺一不可；消费者写的是投影。

Rust RFC 195（对 A′ 拼写最直接的一击）：

> An "input" type parameter is used to *determine* which `impl` to use.
> An "output" type parameter is uniquely determined *by* the `impl`, but plays no role in
> selecting the `impl`.

Swift（TSPL / SE-0413）：「a nonthrowing method can override a throwing method, and a
nonthrowing method can satisfy a protocol requirement for a throwing method.」这是问题一的
包含答案在另一门语言里的成文。SE-0108（Rejected，问题二最强反驳的原文）：

> associated type inference is the only place in Swift where we have a global type
> inference problem: it has historically been a major source of bugs

> A type's associated types don't 'stand out' in the type declaration

该提案被否是兼容性决定，不是对推断的背书，所以它作为「别从方法体推断绑定」的证词仍然有效。

**来源**（2026-08-19 访问）。Flix：doc.flix.dev 的 associated-effects / associated-types /
traits / effect-polymorphism 四页，api.flix.dev 的 Foldable 与 Indexable，flix.dev 的
lambdadays2025 讲稿。Swift：swift-book TSPL Declarations，swift-evolution 0413-typed-throws
与 0108-remove-assoctype-inference（Rejected）。Rust：RFC 3762（const-trait-impl）、
rfcs text/0195-associated-items.md、keyword generics 的 effects-initiative explainer。
Koka：Effect Handlers, Evidently（PACMPL 4 ICFP Art.99, 2020）、MSR-TR-2025-56。
Effekt：effekt-lang.org 的 effect-safety / effect-polymorphism、OOPSLA 2020 论文。
Unison：官方 abilities 两页与 unisonweb/unison#502。MTL：hackage mtl-2.3.2 的
Control-Monad-State-Class。Scala 3：docs.scala-lang.org 的 experimental/cc。
OCaml：ocaml.org/manual/5.3/effects.html。

#### 两条既有规则，以及它们为什么撞在一起

**规则甲（写出来的标签合成参数）**，`docs/spec.md:1452`：

> 签名里写出的每个标签给函数追加一个隐藏证据参数，**排在字典参数之后**、按效果 id 升序。

实现是 `evidence_args`（`checker.dawn:5954-5993`），它按 `eff_labels(declared)` 逐个从词法
环境解析证据；找不到就是「没人应答」的报错，报在调用点。

**规则乙（经效果变量流进来的标签不合成参数）**，`docs/spec.md:1453-1454`：

> 经效果变量流进来的标签不合成参数

紧接的半句给的理由是证据在闭包的捕获里，因此高阶库函数（`list.map` 之流）零改动。
同一条规则在 `effects-design.md:309-313`（§5.2 步 4）复述为「证据参数只按签名里**字面写出的**
labels 合成；经变量流进来的 labels 由闭包捕获自理」。实现是
`instantiated_labels`（`checker.dawn:5926-5939`）与 `evidence_args` 的互补关系：前者算出
「实例化行里被调方没写下来的标签」，后者只管写下来的那些。

**规则乙的全部依据是「有一个闭包可以捕获它」。字典槽位不是闭包。**

而证据也不能存进字典，这一支有三条独立理由，不只一条。第一条是 `dictish`
（`selfhost/src/c/rc.dawn:531-539`，注释在 `:528-530`）：

> A dictionary: outside the ledger entirely. It has no header at all -- a drop on one
> would read garbage as a count -- so no binding of one is ever tracked and no release
> is ever emitted (docs/perceus-design.md 3).

第二条是参数化字典**永活**：`dawn_dict_new`（`runtime/c/dawn_rt.c:195`）在运行期分配带实参
的字典，同处注释（`:176-180`）写明 lives forever 并用 `DAWN_LSAN_OWN` 对它
`__lsan_ignore_object`，[perceus-design.md](perceus-design.md) 的「字典不加头」一段
（`:176-183`）把「参数化字典会泄漏」写成契约而不是待办。证据一旦进字典的 `args`，它捕获的
那些局部就跟着永久泄漏。第三条最硬：`args` 的元素类型是 `struct dawn_dict *`
（`runtime/c/dawn_rt.h:271`），结构上放不下一个 ADT。

`effects-design.md` §5.1 把第一条与第三条写成裁决，第二条本文档同批补进去了。
于是**捕获这条路已经被封死**，证据只能走调用点。

#### 规则丙（条文）

> **规则丙（效果参数在调用点结算，按参数而非按标签）**
>
> 一个**声明级效果参数**在签名的效果行里出现，就为该函数追加**恰好一个**隐藏证据参数，
> 排在写出来的标签所合成的证据之后，按效果参数的声明序。它在**字典槽位边界上擦除**：
> 接口与槽位签名只知道有这么一格，具体证据类型由 impl 侧的 bridge 适配回来。
>
> 供给方永远是**调用方，在调用点**，来源与规则甲同一处：词法环境里按效果 id 命名的证据
> 局部（`ev_local_name`，`checker.dawn:208-209`）。效果参数被实例化成一个具体标签时，调用
> 方交出该标签的证据；被实例化成调用方自己的效果参数时，调用方交出自己那一格；被省略时
> （决策 7 的「省略即纯」）交出占位值。
>
> **字典本身不携带任何证据。** 它携带的是「这个槽位要几格证据」的形状，而形状只取决于
> trait 声明，与实例化无关。
>
> **v1 边界**：一个效果参数至多站一个标签。要两个效果就写两个参数。
>
> **推论一**：规则乙原样保留。分流判据不是「这个标签从哪个变量来」，而是「这个变量住在
> `Sig` 的哪个分量里」，而决策 1 已经把效果参数放进独立分量 `eparams`（`types.dawn:1024`）。
>
> **推论二**：跨 handle 边界没有新规则。`handle_evs` 的结算判据（`checker.dawn:4701`、
> `:5972-5975`）逐字适用。没有新的健全性面：#188 的反例是关于闭包**创建点**的，而 trait
> 方法调用不是创建点。
>
> **推论三（一致性推论）**：bound 里的效果实参是**输出位**，由 impl 唯一确定。impl 方法体
> 拿到的是具体效果，可以真的调它的操作；只有泛型消费者拿到擦除的、只能转发的那一格。

推论三不是审美，是一致性规则逼出来的，而这条约束此前没有任何文档记过：全程序每个
「trait × 类型」至多一个 impl（`spec.md:601-602`），匹配判据是主体 head 相等
（`:603-608`），`impl_at`（`types.dawn:1202-1206`）按 `(tid, head_of(subject))` 查表，
`impl_for`（`lower.dawn:986-990`）与 `dict_key`（`lower.dawn:930`）同理。**impl 不能按效果
实参分家**，于是二居其一：效果实参由 impl 唯一确定（输出位，语义是关联效果），或者效果实参
对 impl 全称量化（impl 方法体只能转发）。裁决取前者。

**A″ 下的读法（2026-08-19 修订，规则丙条文一字不改）。** 条文写于 A′ 拼写下，读的时候做
三处替换。一、「声明级效果参数」逐处读作「签名的效果行里出现的**关联效果投影** `!C.E`」。
二、「按效果参数的声明序」读作「按主体类型变量在 `tparams` 里的位置排，同一主体内按该
trait 的 `effect` 成员声明序排」，与 `TraitI.assoc`（`types.dawn:1083`）同一条纪律；这个
序和 `eparams` 的铸造序一样是契约，要有一条内联测试钉住（先例：`types.dawn:71-90` 的推理
由 `passes.dawn:2195` 钉住）。三、「一个效果参数至多站一个标签」读作「一个关联效果成员至多
绑一个标签」，**且它只约束 A″ 的证据槽、不约束 A0**（见问题三）。

**A″ 让推论三从推论变成拼写。** 关联效果按定义就是 impl 说了算的成员，输出位不必再论证，
读者从 `effect E` 三个字就看得出来。跨语言调研的铁律二是这一读法的独立背书。

#### 三种情形，以及成本落在哪一种

- **情形 I（impl 侧具体）**：`impl Parser[Sub] { effect E = !Ask … }`。规则甲原样适用，
  零改动。
- **情形 II（调用点具体）**：见证是 `WConcrete`/`WApply`，label 集合在调用点静态已知。
- **情形 III（调用点刚性）**：`fn drive[C: Parser](c: C, …) !C.E`，见证是 `WForward`
  （`lower.dawn:2295-2297`）。编译 `drive` 时 label 集合未知。**全部成本在此。**

规则丙让情形 III 免费：`drive` 收一格擦除证据，原样转发。元数处处静态，等于「写出来的
标签数 + 行里提到的效果参数个数」，两者都是 trait 声明的静态属性。bridge 侧的还原走既有
通路：`make_bridge`（`lower.dawn:1122-1183`）对普通参数已经在做 `adapt_out`（`:1153`），
证据走同一条路。**一致性红利**：槽位形状只取决于 trait 声明，所以 `dict_key` 一个字节不用改。

Core IR 零新节点。native 侧擦除证据是 `void*`，照常进 owned 集合（`emitc.dawn:1859`），纯
实例化的占位值定 `NULL`（`dawn_drop(NULL)` 是既有的 no-op 分支）；JVM 侧擦除位是
`Ljava/lang/Object;`，bridge 侧 CHECKCAST。代价是两条：一个效果参数至多绑一个标签；擦除格
不被验证器检查，与字典同类同量的风险。

#### 其余候选为什么出局

- **候选 A（情形 III 在 v1 禁掉，效果实参进字典身份）**：零新 Core 节点，但 `dict_key` 要
  变，而且损失的恰好是泛型消费者，也就是 SEM-10 影响的那一批人。规则丙不用付这个价。
- **候选 B（按效果行单态化）**：这是编译模型改动，不是效果系统改动。Dawn 没有按类型实参
  复制函数体的机制，`perceus-design.md:58` 写明字典传递加擦除正是为了不做它。跨语言调研补
  一手背书：RFC 3762 明说不把效果当类型系统里的泛型参数，理由是那会生成两份独立的 MIR body。
- **候选 C（证据向量）**：混合实例化（`!e2 := !(e | Ask)`）要在运行期合并重排，是唯一破掉
  「零新 Core 节点」承诺的候选；排序错一次就是 native 侧 n 格内存不安全。跨语言调研补一手
  背书：唯一实做过的 Koka 自己把「效果尾多态时要动态索引」记成未完成（引文在调研一节）。
- **候选 D（被调方 re-lookup）**：按定义不成立，impl 方法体的词法环境里没有调用方的 handler。
  Flix 走的正是这一支（不传证据、动态作用域查找），它因此能让一个关联效果装下一整个标签
  集合。**Dawn 不能，所以 Flix 在问题三上的自由不可引用。**
- **候选 E（证据进字典）**：上面三条理由封死。

#### A0：trait / impl 方法的行携带普通效果变量

规则丙买下的是 ABI，但它买不下 #208 最高频的那个形状。探针把 #198 最像 Compose 的原型核心
签名 `fn column(body: fn() -> Unit !e) -> Unit !Ui !e` 搬进 trait：

```dawn
trait Container[C] { fn wrap(c: C, body: fn() -> Unit !e) -> Unit !Ui !e }
```

（探针原稿写的是 `trait Container[C, !e]`，那是借了 A′ 的参数表拼写。A0 用的是
`spec.md:1280` 的隐式引入，一张参数表都不需要；A″ 下 trait 也不再有效果参数表，所以这里
按 A0 的真实形状更正。另注：行里的 `!Ui` 是具名标签，要等刀 5 才放行；只落刀 4 时这条行
写作 `fn wrap(c: C, body: fn() -> Unit !e) -> Unit !e`，`!Ui` 那一半由自由函数版 `column`
先顶着。）

这里的 `!e` 是**调用者的**，同一个 `column` 一处传纯块、一处传 `!io` 块。把它换成由 impl
决定的东西就是错的形状，A″ 的关联效果与 A′ 的 trait 参数同错：效果一旦由 impl 定死，
「内容块能做什么」就变成了组件作者的决定。候选 A 也不解决（内容闭包的参数类型必须写效果
变量，写标签会被 `refuse_written_label` 顶回，`cx.dawn:579-588`）。

它要的东西比 A″ 便宜得多：

> **候选 A0**：允许 trait / impl 方法的行携带**普通的每签名效果变量**（`spec.md:1280` 的隐式
> 引入），标签仍禁。
>
> 代价：**零证据参数**（`evidence_args` 只遍历 `eff_labels(declared)`，只写变量的行 label 集
> 为空，规则乙原样覆盖）、零描述符加宽、`lower_trait_call` 丢弃 `evid` 无所谓（本来就没有）、
> 字典形状一字不动。唯一的真活是 trait/impl 效果变量对齐，见下面的问题四。

A0 是刀 5 的真子集（对 A′ 与对 A″ 都是），也是 #208 唯一有实测背书的诉求，单独就能把
`Container` / `column` 族搬进 trait。刀法上它自成一刀，理由见 §4。跨语言调研给了它第二份
独立背书：Flix 在把 11 个 trait / 28 个 instance 重构到关联效果之后，Foldable 的
`forEach` 仍然同时带着普通效果变量 `ef` 与关联效果 `Aef[t]`，两机制同现一行、缺一不可。
Flix 的路线（OOPSLA'20 的效果多态在前、PLDI'24 的关联效果在后）也就是「先 A0 后 A″」这条
排期被别人走过一遍。

2026-08-26 起这份背书在树内也有了对应物：`packages/tea-core` 的 `trait App[M]` 带一个关联效果
成员 `effect E`，`update` 的行是投影 `!M.E`，树里两个 impl 都绑 `effect E = !()`（`fb41e44`）。
它印证的是排期那一半，即普通效果变量先落地、关联效果后叠上去；「两机制同现一行」那一半仍只有
Flix 的 `forEach` 一例，`App` 的方法行里没有属于调用方的效果变量。

**措辞纪律**：刀 4 旧稿写「把两处拒绝收窄成『未绑定的效果变量』」。这句话在 A0 下会把
`Container` 重新挡回去，因为读者会把「绑定」读成「由 trait 参数表绑定」。正确说法是：
**`spec.md:1280` 的隐式引入在 trait 方法里算「已绑定」**，A0 删掉的是四条拒绝里针对**效果
变量**的那一半，保留针对**具名标签**的那一半。

#### 5a 简化、5b 作废、决策 6 微调

- **5a 整段简化。** 不需要来源追踪。落法是让 `evidence_args`（调用点在 `checker.dawn:5883`）
  对**先代换过效果实参**的行调用，`instantiated_labels`（`:5895`）同批代换。两处一行的改动。
  A″ 下「代换」具体化成「归约投影」，走的是 #44 的同一扇门（`reduce_assoc`，
  `checker.dawn:457`；D5 的纪律是归约用的 impl 与字典选的 impl 必须是同一个答案）。
- **5b 整段作废。** 规则丙按效果参数绑定隐藏局部，就是 `bind_evidence`
  （`checker.dawn:8365-8375`）的镜像循环，读的不是 `eff_labels` 而是签名自己的效果参数表，
  二十行量级。A″ 下这张表是「行里出现的关联效果投影集合」（`fn` 上的效果参数仍读
  `Sig.eparams`，`types.dawn:1024`）。旧稿说的「证据多态」重量来自「元数随实例化变」，而
  规则丙把元数钉成 1。
- **决策 6 微调。** 正确说法是「效果参数不参与 lub 累积，但在见证求解时被代换」。

#### 四个机制问题（**已裁 2026-08-19**）

四条都在实写探针时浮出，规则丙本身不依赖它们的答案，但落刀前每一条都要有定论。旧稿把四条
标成「待终审」并各给一个提案；跨语言调研之后四条全部裁定，下面每条给裁决、一句话理由、
保留下来的论证，以及**重开条件**。

**问题一（已裁 2026-08-19）：bound 里的效果实参按相等还是按包含匹配？翻转点在哪？**

**裁决：按包含**，方向是「impl 那侧的效果 ⊑ bound 写出来的那个」，也就是 bound 写的是上界。
一句话理由：这条判据全语言已经有了（`eff_subsumes`，`types.dawn:210-217`），改成相等会逼
每个 impl 声明最大行，那正是审计说的「被迫退回 `!io`」；调研的铁律三是它的跨语言背书。

`unify_eff` 的 `EPure`/`EIo` 两臂（`checker.dawn:695-696`）已经把基轴交给 `eff_subsumes`，
trait/impl 一致性检查（`passes.dawn:1787`）用的也是它。元数不受影响：格数只看 trait 声明，
impl 的行更小也不会少一格，调用方交占位值。

**(a) 与 (b) 合并给同一个答案（本次修订补记）。** 这个问题其实有两半：(a) impl 满足 trait
声明时的一致性检查，(b) bound 上写了具体效果实参（`W: View[!Ui]`）时拿一个 impl 去对。
Flix 把两半分开：关联效果成员按**相等**绑定，「更纯的实现可以过」是独立的子效果机制，只在
lambda 与 instance 定义两处开。**Dawn v1 合并**，理由是没有 `where` 编址：v1 没有任何拼写
能表达「恰好是这条行」，(b) 分出来也无处安放。而且 A″ 的惯用拼写是绑定者加投影（`!C.E`），
消费者几乎不会在 bound 上写死一条具体行，**(b) 极少触发**。

*翻转点*：不是一个时刻，是一次查表。`unify_eff` 的 `EffVar` 臂（`checker.dawn:697-703`）
今天无条件累积 lub，那是给**被调方的待解变量**用的；一个已被外层声明绑定的效果变量必须
不被推断进。判据取类型轴现成的那条：`is_concrete`（`checker.dawn:718-728`）问「它在不在
`cx.current_tparams` 里」，效果侧对应的问法是「它的 id 在不在外层签名的 `eparams` 里」。
刀 1 之后这张表已经就位且恰好正确：`enter_fn`（`checker.dawn:8316-8324`）就是从 `s.eparams`
重建 `current_eff_vars` 的。所以决策 6 的落地物「效果侧的 `is_concrete`」与本问题的翻转点
是同一件东西。

*最强反驳（保留，答案不变）*：在输出位上做包含检查读起来是反的。若效果由 impl 唯一确定，
bound 写的 `View[!Ui]` 就不是需求而是模式，接受一个纯 impl 意味着消费者自己的行被高估。
高估永远安全，但它意味着「投影出唯一答案」与「bound 只是上界」是两件事，两个行不同的 impl
会同时满足同一个 bound，读回来的是哪个必须另有规定。**回应**：投影读的是 impl 的实际绑定
（一致性保证每个 subject 唯一），bound 是检查不是定义，两者可以并存，但**这条并存关系要写
进 spec**，否则第一个写关联效果的人会踩。

**重开条件**：出现消费者需要「恰好那条行」而不是上界；或者效果排除（Flix 的 `ef - {Throw}`）
与 `where` 编址两件里任何一件落地。落地之后照 Flix 拆两半：(b) 改相等，包含留给 (a)。

**问题二（已裁 2026-08-19，被 A″ 溶解）：impl 在哪里写效果实参？**

**裁决：impl 在自己的体内写 `effect E = !X`，恰好一次，强制，不从方法行推断。** 与 #44 的
D4（`type Item = X`）同形、同处、同一套检查：`ImplI.assoc_bindings`（`types.dawn:1270-1274`）
在注册时做 exactly-once 覆盖检查。一句话理由：A″ 让这个问题按构造消失，impl 头的产生式
（`grammar.ebnf:85`）与主体形状条（`spec.md:603-608`）一个字不动，`impl_at`
（`types.dawn:1202-1206`）、`impl_for`（`lower.dawn:986-990`）、`dict_key`（`lower.dawn:930`）
的寻址也一个字不动。

**「从方法行投影 + 跨方法取并」整条删除。** 旧稿的提案是 impl 不写、从方法行反推，两条方法
行不一致时投影它们的并。它有两个独立的病。一、**零先例**：调研的十门语言里没有任何一门从
方法签名反推接口级的效果绑定，「跨方法行取并」是发明，而发明要自带全部诊断设计。
二、**唯一做过见证推断的语言自己反对**：Swift 的关联类型推断被它自己写成「associated type
inference is the only place in Swift where we have a global type inference problem: it has
historically been a major source of bugs」，SE-0108 提议删掉它；提案被否是兼容性决定，不是
对推断的背书。同一提案里的另一句「A type's associated types don't 'stand out' in the type
declaration」正是旧稿「最强反驳」担心的那件事：impl 的对外形状变成隐式、impl 头上没有 diff。
显式绑定把这条反驳一并解决，代价只是一行拼写。

**重开条件**：若 #44 的机制被撤（现已不可能），投影加取并是唯一剩下的方案，届时必须先有
一个变异体证明「两条方法行给出不同标签」时错误确实报出、且诊断点名是哪两条方法行。另：
若拼写退回 A′，问题二仍取「impl 体内写一次」，这是调研里最一边倒的一格。

**问题三（已裁 2026-08-19，作用域限 A″ 的证据槽）：一格擦除证据怎么装多标签的行？**

**裁决：v1 不定义打包形状；一个关联效果至多绑一个标签，要两个效果就写两个 `effect` 成员。**
一句话理由落在**证据表示**而不是效果语义：`CFun.evs`（`core.dawn:255-261`）是一列扁平
`CParam`，任何打包都要一个 Core 级的构造物，而那正是候选 C 触礁的地方。

**作用域（本次修订）：这条边界只约束 A″ 的证据槽，不约束 A0。** A0 的行里是普通的每签名
效果变量，落在规则乙下、零证据参数，它实例化成几个标签与证据槽无关。实证在 Flix 的 stdlib：
`def forEach(f: a -> Unit \ ef, t: t[a]): Unit \ ef + Aef[t]` 一行里两种机制同现，`ef` 自由、
`Aef[t]` 受限。旧稿没有区分这两者，会把 A0 一起限住。

**Flix 的自由不能被引用成反例。** 它的关联效果能装下一整个标签集合，代价是它根本不传证据
（「Flix effect handlers use dynamic scope, deep handlers, and support multiple
resumptions.」），也就是 Dawn 已否的候选 D。拼写抄得，问题三上的自由抄不得。

*v2 真要开时的规范位是 lowering，不是后端*：合成一个普通记录类型（字段按效果 id 升序，
与 `bind_evidence`、`ev_sym_list`、`sig_desc_with_dicts` 共用同一条排序纪律，
`checker.dawn:8365-8375`、`:8377-8387`、`emit.dawn:394-407`），两个后端把它当普通 ADT 看。
两边不会各自约定，是因为它们根本不知道有过打包这回事。位置性元组不行：那要求两个后端对
「第 i 格是什么」达成一致，正是要避免的。

*最强反驳（保留）*：推迟意味着 v1 边界在承重。若日后放开，已编译出来的描述符还能用，唯一的
原因是这一格从第一天起就是擦除的。这是支持擦除的论据，不是反对推迟的。真正的风险是人体
工学：消费者想让一个效果站「调用者的整条行」时，「写两个成员」的 Effekt 形状读起来很别扭。
**回应**：那个消费者要的是行多态，D4（`effects-design.md:56`）已经裁掉；而「调用者的整条
行」这件事本来就该走 A0 的效果变量，不该走关联效果。

**重开条件**：出现一个真实签名，证明某个效果必须同站两个标签、且写不成两个成员（Effekt 走了
多年没遇到）。真遇到就走「lowering 合成一个普通记录」，不走 Koka 的向量。

**问题四（已裁 2026-08-19，作用域缩到只剩 A0）：trait / impl 的效果变量怎么对齐？**

**裁决：先代换后比较，比较点不动，按位铸造序；另补一个置换变异体。** 一句话理由：两侧的
效果变量都在 `Sig.eparams` 里、按铸造序排，代换表就是按位 zip，而 `subst_eff` 的键正是 id，
与 zip 产出的键同型。

**作用域缩小（本次修订）：这个问题只剩 A0。** A″ 不按位对齐，因为关联效果**按成员名对齐**：
trait 声明 `effect E`，impl 写 `effect E = !X`，名字本身就是配对关系，覆盖检查是 #44 现成的
exactly-once。旧稿最强反驳担心的「铸造序在源码上看不见」，在 A″ 那半边不存在。

*落法*：比较点是 `passes.dawn:1787` 的 `eff_subsumes(msv.sig.eff, eff)`（备忘录与探针记的
`:1764` 是刀 1 之前的行号）。`eff_subsumes`（`types.dawn:210-217`）把基轴交给 `base_subsumes`
（`types.dawn:181-204`），后者对 `EffVar` 只认 id 相等（`outer == inner`，或
`union_has(ovs, id)`），而 trait 的 `!e` 与 impl 的 `!e` 是两次独立的 `fresh_effvar` 铸造
（铸造臂在 `cx.dawn:452-463`），所以永远不相等。今天不触发，只因为两侧的 `eff` 恒是
`EPure`/`EIo`。修法是类型轴在**同一处**已经做过的那件事的效果轴镜像：`want` / `want_ret`
（`passes.dawn:1778-1780`）先把 trait 的 tparams 经 `inst` 代换再比类型，行也照此处理。
刀 1 让这件事变便宜且完备：两侧的变量现在都在 `Sig.eparams` 里、按铸造序排（`types.dawn:1024`，
序的契约写在 `:71-90`），所以代换表就是 `msv.sig.eparams` 与 `msig.eparams` 的按位 zip。
方向取「把 trait 的变量代换成 impl 的」，然后 `eff_subsumes(subst_eff(msv.sig.eff, em), eff)`。
长度不等就报错并点名（impl 把 trait 的一个变量拆成两个，是这条的唯一触发方式）。

**补一条验收物（本次修订）：置换变异体。** 长度不等的拒绝只挡得住长度，挡不住**等长置换**
（impl 把两个效果变量的顺序对调）。把按位 zip 换成「对调」或「旋转一位」的变异体必须红，
否则「按位对齐」这条契约没有下界，绿只说明没人看过。这条进刀 4 的验收清单。

*最强反驳（保留）*：按位 zip 把两侧绑在**铸造序**上，而铸造序是解析器的产物，源码上看不见。
读者并排看 trait 与 impl 时无法看出配对关系；按名字配（`!e` 对 `!e`）则是看得见的。
**回应**：按名字配会强迫 impl 作者抄 trait 的拼写，而别的轴都不这么要求（impl 方法根本没有
类型参数表，`grammar.ebnf:85-86`，trait 的 tparam 一直是按位经 `inst` 代换的）。而且铸造序
在刀 1 之后不再是产物：它是文档化并被 `passes.dawn:2195` 钉住的契约。所以取按位，长度不等
的拒绝加上置换变异体是它的安全网。

**重开条件**：置换变异体若显示对齐会接受错误的 impl，立即重开。刀 2 的显式绑定者语法**允许
但不强制**写在 trait / impl 方法上；等它普及之后按名匹配变成免费，按位可以退成兜底。

#### 重开条件汇总（2026-08-19）

本决策的六条重开条件，前四条已附在各问题下，这里连同另外两条一并列出，便于日后按条对照。

1. **问题一（包含）**：见上。
2. **问题二（impl 体内写一次）**：见上。
3. **问题三（一格一标签）**：见上。
4. **问题四（按位对齐）**：见上。
5. **输出位读法**：#208 的 12 个探针程序与 Flix 的 stdlib 重构是两份独立的未证伪。重开必须
   给出一个具体签名，并说明它为什么写不成 A0（普通效果变量）。
6. **A″ 对 A′ 的拼写**：若实测发现 `EffAssoc` 把轴间耦合拉得比预估贵，尤其是 `subst_ty`
   作用在带 bound 的类型变量上时必须触发效果侧归约这一条，就退回 A′ 的参数表拼写，但
   **保留问题二的改法**（impl 体内写一次）。这条实测是刀 5 的开工前置，见 §4。

#### 随刀落的文档改动（拟稿，与刀一起提交）

以下逐字目标已核对到 `cf725f4`，条文随对应的刀落地，不提前改。第 5 条是 A″ 修订新增的。

1. **`docs/spec.md:1453-1454`（规则乙）** 改成：经**签名内引入的**效果变量流进来的标签不合成
   参数，那种情况下证据在闭包的捕获里，所以高阶库函数（`list.map` 之流）零改动。**行里出现
   的关联效果投影 `!C.E` 不在此列**（A′ 拼写下这一句写作「声明级效果参数」）：它为函数追加
   恰好一个隐藏证据参数，排在写出来的标签之后，在字典槽位边界上擦除。字典槽位不是闭包，
   没有捕获可依赖，所以证据由调用方在调用点交出。
2. **`docs/spec.md:1436`**（「trait / impl 方法：方法的行是纯或 `!io`」，在 §6.5 的
   「边界（v1）」小节，该小节起于 `:1432`）随 A0 那一刀改写成「方法的行可以带效果变量，
   不能带具名标签」，随刀 5 再放开关联效果投影与具名标签。
3. **`docs/spec.md:1280`（§6.3）** 按决策 2 加一句：签名自带显式绑定者时，该名字在这条签名内
   只解析到它。
4. **`docs/spec.md` §6.5 的边界表新增一条**：**「效果多态代码能转发、不能结算」**。理由是
   `with handle E` 在语法上就点名一个具体效果（`grammar.ebnf:102-103`、`spec.md:1399-1402`），
   所以 handler 安装点永远是单态的；`pub fn main` 的 labels 必须为空
   （`effects-design.md:175-177`、`passes.dawn:2301-2307`）是同一堵墙的另一面。
5. **A″ 的三处新拼写进 spec 与 grammar（随刀 5）**：trait 体内的 `effect E` 成员、impl 体内的
   `effect E = !X` 绑定、行里的投影 `!S.E` / `!C.E`。条文照 #44 的 `type Item` 逐条对照写：
   同处声明、注册时 exactly-once 覆盖检查、投影的许可位置沿用 D6（方法签名内，含参数位与
   返回位）、归约纪律沿用 D3（急切）与 D5（与 witness 同一个 `impl_at`）。**v1 不给
   `effect E` 开上界，也不给默认值**，理由是调研在这一格拿不到一手依据（Flix 的细则未证实），
   而上界与默认值都是纯加法。同时把问题一的并存关系写进去：bound 是检查不是定义，投影读的
   是 impl 的实际绑定。

另有两处随刀 4 改的旧稿，目标已重定位、条文等刀：`effects-design.md:309-313`（§5.2 步 4）的
「只按字面写出的 labels 合成」要改成「按字面写出的 labels，外加行里出现的每个关联效果投影
一格」；`effects-design.md:227-230`（§4.5 的 trait/impl 条）要改写「labels 必须为空」，并顺手
更正它自己引的四个行号（现址是 `passes.dawn:1276-1279`、`:1766-1768`、`:1213-1229`、
`:1700-1717`）。§4.6（`:248-266`，创建点结算）**不必改**：它讲的是闭包，而规则丙不新增闭包
创建点，两者正交。

`docs/codebase-audit-v2/02-types-effects-and-semantics.md:276-280` 已经是对的，不必改：它现在
写的就是「捕获进 dictionary 那一支已经封死」并把球踢给本决策。

### 决策 6：刚性效果参数会被推断进吗

**推荐：不会。刚性效果参数是已知效果，不是待解变量。**

`unify_eff`（`checker.dawn:688-714`）今天分三类：`EPure`/`EIo` 交给 `eff_subsumes`（`:695-696`）；
`EffVar` 绑定并累积 lub（`:697-703`）；`EUnion` 与 `ELabeled` **明确不被推断进**
（`:707`、`:710-714`，注释「a union in a declared parameter position is not inferred into」、
「a declared label is not inferred into either」）。

一个声明级的刚性效果参数三类都不是。它应当照 `is_concrete` 对刚性**类型**参数的处理
（`checker.dawn:718-728`：出现在 `cx.current_tparams` 里就算已知），而效果侧今天没有对应物。
所以决策 6 的落地物是「效果侧的 `is_concrete`」。

**微调（随决策 5 裁决，2026-08-19）**：本条旧稿的措辞不够准。准确说法是「效果参数**不参与
lub 累积**，但在见证求解时**被代换**」。落地物仍是「效果侧的 `is_concrete`」，而它同时就是
决策 5 问题一说的那个翻转点：判据是「这个 `EffVar` 的 id 在不在外层签名的 `eparams` 里」，
刀 1 之后这张表由 `enter_fn`（`checker.dawn:8316-8324`）从 `s.eparams` 重建，现成可问。

### 决策 7：使用点省略效果实参是什么意思

**推荐：省略即纯，与 `instantiate_eff` 今天的默认一致；不是元数错误。**

**落地修订（2026-08-19，刀 3 验收）**：「不是元数错误」保留；「省略即纯」不成立于字面，
落地为**省略即由上下文求解**。省略的那一格仍是声明自己的那个效果变量：把纯闭包存进
`Mapper[Int, String]` 它就解成纯，把 `!io` 闭包存进去就解成 `!io`；消费方要在自己的行里
容得下它，而一条只由本签名绑定的 `!e` 容不下别处绑的变量，所以消费方今天写 `!io`。
字面读法（省略处直接代入 `EPure`）被否有两条理由：它让 `type Box[!e]` 与 `type Box`
完全等价（绑定者一无所获）；且会把本节自己的刀 3 语料判非法：把 `!io` 闭包存进字段再
调回，这个程序今天按 SEM-01 创建点结算零证据地正确运行，而「消费方纯、io 闭包照存」
则不健全。spec §6.3 的条文按树写，本条以它为准。

`instantiate_eff`（`checker.dawn:5941-5948`）把未绑定的效果变量默认成 `EPure`，注释在
`:5793`（「an unbound effect variable means pure」）。让 `Mapper[Int, String]` 报元数错误会与
这条默认冲突，也会让效果参数比类型参数更啰嗦。

一个真实缺口要一并记下：类型引用今天**没有**效果实参的语法位，`TNamed`/`TQual` 的实参只是
`List[TypeRef]`（`selfhost/src/front/ast.dawn`）。所以「显式给效果实参」这件事本身需要新语法。
推荐第一批不做，只支持省略（推断），显式实参等出现无法推断的消费者再开。

**后续（#344 tier 1，已落地）**：语法位补上了。`TNamed`/`TQual` 各多一条
`eargs: List[EffArg]`（与 `args` 分列，理由同决策 1），`type_args` 按首 token 分流。
收实参的只有**透明 `alias`**：它就地展开，实参落在展开式里；记录、变体、`opaque type` 的身份
是「名字 + 类型实参」，没有位置记住这个行，一律拒绝并说明理由。可写的行由规则丙′ 限死，
今天只有 `!io`。省略式一字未改。条文在 spec §6.3。

**第二档（#351，已落地，取代上一段的 `{!io}` 限制）**：实参位收**内联行位置能写的一切**——
`!io`、围合签名绑的变量 `!e`、具名标签 `!Ask`、限定标签 `!C.E`、以及它们的并
（`!(Ask | io)`、`!(Ask | e)`）。

理由一句话：**透明别名就是它的展开**。`Thunk[!Ask]` 与 `fn() -> Int !Ask` 是同一个类型的
两种拼法，而后者一直合法（决策 8 收窄后，类型声明位写具名标签就是合法的）。同一个类型
按拼法分合法性，就是让别名成为一道语义关卡，而它不是。

规则丙′ 因此收窄到**名义侧**，且这不是豁免而是原判据的正确切法。丙′ 的理由从来不是
「声明绑的变量特殊」，是「通道不存在」：记录、变体、`opaque type` 的身份只记名字与类型实参，
字段里那条行留在原地，只能解成不欠证据的行。透明别名恰恰有通道——它展开，行落进**消费方
自己的签名**，而签名有隐藏证据参数（§6.5）。所以 `fn retry(n: Int, f: Thunk[!e]) -> Int !e`
里的 `!e` 是 `retry` 自己绑的变量，证据到 `retry` 的帧里取，与内联写法一模一样。

落地面很小：`earg_subst` 从「把每个 eparam 映到 `EIo`」改成「用 `resolve_eff_at` 在使用点
作用域里解析实参，映到解出的行」，`refuse_owed_earg` 整个删除（它唯一的调用者是
`check_eargs`，那里只剩元数）。拼接不必新写：`subst_eff` 的并集机械（`eff_union` →
`base_union`）本来就拍平、去重、且 io 不吸收变量（#345）。

**顺手件**：「变量绑在别处，写 `!e` 会绑到另一个变量」那条 hint 以前只能推荐 `!io`。
现在若该变量是某个透明别名的 eparam（按 id 反查 `cx.aliases` 与各模块导出表），hint 直接
指出真出路：把实参写出来，填一条本签名绑得住的行。`verify_effects` 另收一条 `s.eparams`，
用来分辨「这个变量本签名绑不绑得住」——绑得住时（如 `fn f(t: Thunk[!e]) -> Int`，`!e` 由实参
引入到本签名）普通的「加 `!e`」建议就是对的。

### 决策 8：RX-10 期权 A 是撤销、收窄，还是保留

**推荐：收窄，不撤销。**

`refuse_decl_effvar`（`selfhost/src/check/passes.dawn:294-303`）今天对类型声明位的效果行一律
拒绝，一条消息盖两个不同的理由。这个设计的自述在 `:282-293`：

> Saying which of the two it is would take knowing whether the atom names a declared
> effect, and this pass runs before `pass_effects` registers them.

B 落地后两个理由分道：**效果变量**那一半变成有条件的（取决于这个声明自己的参数表里有没有
绑定它），**具名效果**那一半仍然无条件（`effects-soundness-design.md` §4.1 的禁令，实现在
`refuse_written_label`，`cx.dawn:579-588`）。有条件的那一半需要知道声明自己的参数表，这个
pass 拿得到；但要区分「小写原子是本声明绑定的效果参数」和「小写原子什么都不是」，仍不需要
`pass_effects`。所以 pass 序不必改，改的是消息：拆成两条，各说各的理由。

顺带结清一条与裁决无关的旧账：`audit/re-audit-b-decisions.md:576-578` 记下的 `poly_apply`
提示（「add !e to the end of the signature」而签名已经有 `!e`）「无论选 A 还是 B 都是错的」；
选 B 时它必须改。同一刀里改。

### 决策 9：效果参数在 `sig_render` 里渲染吗

**推荐：渲染。**

`sig_render`（`selfhost/src/check/types.dawn:1295`）是唯一的签名渲染器，`tparams` 连 bound
一起渲染在 `:1296-1312`。它同时服务 `dawn doc`（`selfhost/src/doc.dawn:251`、`:278`、`:388`、
`:567`、`:613`、`:638`、`:699`）与 LSP hover（`selfhost/src/lsp/lspq.dawn:333`）。

渲染的代价是 `Emit-Change(doc --builtins)` 与 `Emit-Change(lsp)`（标签见
`scripts/emit-labels.txt:38`、`:59-62`）。不渲染的代价是 hover 与 doc 对签名的元数说谎，
而证据参数的个数正取决于它。前者是一次声明，后者是长期错误。

**A″ 要渲染的是两样（2026-08-19 修订）**：行里的投影 `!C.E`（在 `sig_render` 里，与
`T.Item` 的渲染同处，`types.dawn:718` 已有 `TyAssoc` 的臂可照抄），以及 trait 体内的
`effect E` 成员（在 `dawn doc` 的 trait 渲染里，与关联类型成员并列）。两者都是刀 5 的账，
标签不变。

顺带记一条已经陈旧的东西：LSP 在 `!` 之后的补全**只给 `io`**
（`selfhost/src/lsp/lspc.dawn:841-845`，注释「the effect row: `!` admits exactly one builtin
effect」）。自 #110 落地具名效果起这就不对了，B 会让它更不对。不阻塞本文，登记为小件。

### 决策 10：trait / impl 一致性检查如何比较与渲染带效果行的方法

**推荐：`eff_show2` 删除，换 `eff_show`；一致性判据 `eff_subsumes` 不变。**

一致性检查在 `passes.dawn:1787`：`eff_subsumes(msv.sig.eff, eff)`，判据本身双轴，不必改
（`eff_subsumes` 在 `types.dawn:210-217`）。要改的是渲染与文案：

```
fn eff_show2(e: Eff) -> String = if e == EIo { "io" } else { "" }
```

`passes.dawn:1937`。一个两值渲染器，它存在的**原因**就是这个位置只能是纯或 `!io`。它今天对
任何别的行返回空串，于是 `:1788-1790` 会打出「`m` is declared ! but trait `T` declares it
pure」。同一处的 `want_render`（`:1781-1783`）也把 `eff_suffix(msv.sig.eff)` 写死。

这是「限制被烘进代码而不是被检查」的最小最具体的证据，也是判断第四刀是否落干净的
现成判据：`eff_show2` 还在，就说明没落干净。

### 决策 11：`effect Yield[T]` 在不在范围内

**已在 §1 结清：出局，另立任务。**

## 4. 刀法

**五刀**（决策 5 裁决后从四刀变五刀：A0 独立成刀，排在原刀 4 之前，原刀 4 顺延为刀 5，理由
写在刀 4 那一节）。先把两个成本讲清楚，因为审计把它们混了
（`docs/codebase-audit-v2/02-types-effects-and-semantics.md:286` 写「字典形状变更还要
Emit-Change 加一轮种子」）：

- **Emit-Change** 由**发射出来的产物移动**触发。声明的标签集见
  `scripts/emit-labels.txt`（`emit *` 在 `:20-29`，`fmt` 在 `:35`，`lsp` 在 `:38`，
  `doc *` 在 `:59-62`）。
- **一轮种子**只由 `selfhost/src` 或 `std` **开始使用** N−1 种子解析不了的语法触发。纪律写在
  `effects-design.md:326`、`:333`（「selfhost/src 与 std 不得使用新语法（种子 parse 不了）」），
  底座是 `bootstrap.md`。

两者独立：改字典描述符只花 Emit-Change 行，不要种子轮；改 `std/` 的签名拼写要种子轮，
哪怕一个字节的产物都没动。

### 刀 1（已落地，`cf725f4`）：给效果参数在 `Sig` 里安家，不改变任何可观察行为

计划是：加 `Sig` 分量（决策 1）；让 `resolve_eff_at` 的隐式铸造记进这个分量；退役 `evs`
侧信道，`enter_fn` 改从 `Sig` 读回；把两处泄漏探针换成对签名参数表的直接提问。

**实际交付**（差异只有一处，见下）：

- `Sig.eparams: List[Eff]`（`types.dawn:1024`），由 `eff_params_of`（`types.dawn:91-105`）
  从签名自己那张 `current_eff_vars` 建出。
- **序被定成铸造序并写进文档**：按效果 id 排序，等价于 `resolve_eff_at` 首次遇到名字的次序，
  展开来是「行、参数类型从左到右、返回类型」，行写在最后所以首次相遇不等于首次出现。推理在
  `types.dawn:71-90`，由 `passes.dawn:2195` 的内联测试钉住。这是计划里没写、落地时补上的：
  渲染器与后续的按位对齐都要读这个序，一个「顺序无所谓」的列表迟早会被 HAMT 序咬。
- `evs` 侧信道退役，`pass_fn_signatures` 的返回类型回到 `(Cx, List[Sig])`
  （`passes.dawn:2044`）；`enter_fn`（`checker.dawn:8316-8324`）从 `s.eparams` 重建表。
- 两处拒绝现在问 `len(sig.eparams) > 0`（`passes.dawn:1275`、`:1765`），触发的程序与诊断
  一字不变。

每条签名的效果参数恰好就是今天隐式规则铸出的那些，所以行为逐位不变。`sig_render` 不改，
doc 与 LSP 不动。

**Emit-Change：零**，用**未遮蔽的真父对照**（拿父提交建的编译器编这棵树）实测，十个 `emit`
目标逐字节相同，lex / parse / fmt dump 相同。**语料移动：零。种子：零。** Core golden 是
重录（`Sig` 自己加字段，Core 会动），从不声明。

**它自己就站得住**，即使 B 永不落地：效果变量是全语言唯一一个「在它所绑定的东西里没有表示」
的绑定者，而两处拒绝拿副作用当谓词。这两条都是缺陷，与特性无关。刀 1 还把泄漏探针变成真正的
提问，那是后几刀能把拒绝**收窄**而不是**删除**的前提，也让决策 5 问题四的按位代换表变得
现成（两侧的变量都在 `eparams` 里，序还是同一条契约）。

### 刀 2：`fn` 上的显式绑定者语法，可选且等价

`parser.dawn:410-445` + `docs/grammar.ebnf:45-46` + `spec.md:1280` 的条文。合法化
`fn map[T, U, !e](…)`。语义零变化，绑定者与今天的隐式引入等价（决策 2）。

**Emit-Change：可能 `fmt`（`scripts/emit-labels.txt:35`），需先跑幂等探针（决策 3）。**
决策 9 若说渲染，本刀不触发 doc/lsp，因为等价签名渲染结果不变（除非作者真写了绑定者）。
**种子：零**，条件是 `selfhost/src` 与 `std` 在发布之前不用新语法（一代滞后）。
前置：决策 2、3。

### 刀 3：`alias` 与 `type` 上的绑定者，RX-10 A 收窄

`ast.dawn:346` 的 `tparams: List[String]` 加宽，`parser.dawn:486-492` 跟着改；
`refuse_decl_effvar`（`passes.dawn:294-303`）收窄成只拒**未绑定**的变量，消息拆两条（决策 8）；
`poly_apply` 的提示同批改。交付 RX-10 的原始诉求：
`alias Mapper[T, U, !e] = fn(T) -> U !e` 与 `type Box[!e] = { f: fn(Int) -> Int !e }`。

**纯检查期，无运行时物。** 因为 SEM-01 的结算规则（`effects-soundness-design.md:39-40` 的 ②，
落在 `effects-design.md:248-266` §4.6）让闭包在**创建点**结算自己的行并自带证据，字段上的
`!e` 由闭包捕获的证据消掉，没有东西要在调用时传。`effects-design.md:240-241` 已经就此更正过
自己：「「带 label 的闭包不能存进记录字段」不再成立」。

**Emit-Change：决策 9 若说渲染，则 `doc *` 与 `lsp`。种子：零。**
前置：决策 3、4、7、8。

刀 1 至刀 3 一个发布。

### 刀 4（A0）：trait / impl 方法的行带**效果变量**，标签仍禁

**为什么单独成一刀（已裁 2026-08-19）。** 三条：

1. **前置不同。** A0 的前置只有决策 5 的问题四（trait/impl 效果变量对齐）；刀 5 还要 A″ 的
   三处新拼写与问题一到问题三的定论。绑在一起，A0 要陪着等。四问已于同日裁定，但刀 5 另有
   一项开工前置（`EffAssoc` 的轴间耦合实测，见刀 5），A0 不必等它。
2. **代价不同，验收也不同。** A0 零证据参数、零描述符加宽、零 Core 变动，`dict_key` 一字不动；
   刀 5 的验收清单整个是描述符对称性（JVM 四处、C 一处，见下）。混成一刀会让「描述符一处没漏」
   这条验收失去干净的对照组。
3. **它自己就站得住**，与刀 1 同款判词：trait 方法的行今天被烘死成两值（`eff_show2`），这是
   缺陷不是特性。而且它是 #208 唯一有实测背书的诉求（决策 5 的 A0 一节）。

**反驳与回应**：四条拒绝会被动两次（A0 把「拒一切」改成「只拒标签」，刀 5 再把「只拒标签」
改成「放行关联效果投影与具名标签」），`trait_method_effects.expected` 也要重录两次。回应是
这恰好让每一次移动都读得懂：A0 那次消失的正好是四条效果变量诊断，两条具名标签诊断一条不动。

**两处按 A″ 修订的细则（2026-08-19）。**

- **「一个效果参数至多一个标签」这条 v1 边界与 A0 无关**（问题三的作用域修订）。A0 的行里是
  普通的每签名效果变量，落在规则乙下、零证据参数，它实例化成几个标签与证据槽没有关系。
  跨语言实证是 Flix 的 `forEach`：普通效果变量 `ef` 与关联效果 `Aef[t]` 同现一行，前者自由、
  后者受限。刀 4 不得把这条边界写进任何针对效果变量的检查。
- **验收补一条置换变异体**（问题四）。下面的对齐检查用按位 zip，而现有的长度守卫只挡长度、
  挡不住等长置换。把 zip 换成「两侧对调」或「旋转一位」的变异体必须红，否则这条契约没有下界。

**落点。** 四条拒绝按同一条界线处理：删掉效果变量那一半，留下具名标签那一半。

- trait 方法行级（`passes.dawn:1213-1229`，诊断在 `:1227`），今天一条消息盖两件事，按
  `label != ""` 分岔已经写好了，A0 只需把 `else` 那支放行。
- trait 方法 `eparams` 级（`:1275-1279`）：整条删除。
- impl 方法行级（`passes.dawn:1700-1717`，诊断在 `:1715`）与 impl `eparams` 级（`:1765-1769`）：
  同上。
- `eff = if len(me.effs) == 0 { EPure } else { EIo }`（`:1254`、`:1741`）换成真的
  `resolve_eff_at`。
- **对齐检查**（决策 5 问题四）：`passes.dawn:1787` 的 `eff_subsumes(msv.sig.eff, eff)` 改成
  先按 `eparams` 按位代换再比，长度不等报错。这是 A0 唯一的真活。
- `eff_show2`（`:1937`）删除，`want_render`（`:1781-1783`）改用 `eff_show`（决策 10）。

**措辞纪律（改正旧稿）**：旧稿写「把另两条收窄成『未绑定的效果变量』」。这句在 A0 下会把
`Container` 形状重新挡回去，因为「绑定」会被读成「由 trait 参数表绑定」。**`spec.md:1280`
的隐式引入在 trait 方法里就算「已绑定」**，A0 之后 trait 方法行里没有「未绑定的效果变量」
这种东西。A″ 之后 trait 根本没有效果参数表，这句旧稿的说法只会更容易被误读，所以不要复活它。

**trait 方法默认体**（`CSlotDefault`，`lower.dawn:1111`；符号 `default_symbol`，
`emitc.dawn:1313`）：不含主体、全程序一份。行提到效果变量时默认体处在情形 III 的定义侧，
拿到的是刚性效果、只能转发，自洽。**v1 放行**，但要写进 spec，否则它是一条只有实现知道的规则。

**Emit-Change：零**（不写 trait 方法效果行的程序编出来逐字节不变），除非决策 9 的渲染让某个
被渲染的签名真的多出一个 `!e`，而今天 `std` 与 `selfhost/src` 没有这样的 trait 方法。
**语料**：`scripts/checker-corpus/cases/trait_method_effects.expected` 今天钉住 11 条诊断，
其中四条（`trait methods cannot declare effect variables`、`trait method signatures cannot
carry effect variables`、`impl methods cannot declare effect variables`、`impl method
signatures cannot carry effect variables`）随本刀消失，另需 accept 侧新语料。**种子：零。**

**前置：决策 5 的问题四、决策 10。**

### 刀 5（A″）：关联效果、写出来的标签，与规则丙

（旧稿的标题是「刀 5（A′）：trait 参数表、写出来的标签，与规则丙」。2026-08-19 按跨语言
调研改拼写，机制不变。）

**三处新拼写，逐处对照 #44 的 `type Item`。**

1. **trait 体内 `effect E` 成员**：**无上界、无默认值**（v1；理由是调研在这一格拿不到一手
   依据，而两者都是纯加法）。存进 `TraitI` 里一张与 `assoc`（`types.dawn:1083`）同形的列表。
   （默认值随 #369 于 2026-08-26 追加，见 §9；上界仍未做。）
2. **impl 体内 `effect E = !X` 绑定**：**强制且恰好一次**，不从方法行推断（问题二），注册时
   做 exactly-once 覆盖检查，与 `ImplI.assoc_bindings`（`types.dawn:1270-1274`）同形同处。
3. **行里的投影 `!S.E` / `!C.E`**：许可位置沿用 D6（方法签名内，含参数位与返回位），归约
   纪律沿用 D3（急切）与 D5（归约用的 impl 与字典选的 impl 是同一个答案，同一扇门）。

**类型侧只加一个构造子。** `Eff` 加 `EffAssoc(tvar_id: Int, trait_id: Int, name: String)`。
主体**限定为带该 trait bound 的类型变量**，只存它的 id，所以 **`Eff` 里仍然不出现 `Ty`**。
载荷三出局的两条判词（`effects-design.md:42-44` 的「会让 subst 的类型/效果双 map 互递归」
与「`Map[Eff, …]` 的键全动」）因此**不适用**：效果轴不必遍历类型结构，键仍是标量三元组，
`Eff` 的归一化（`EUnion` 与 `ELabeled` 的排序纪律，`types.dawn:26-40`）多一个按
`(tvar_id, trait_id, name)` 排的原子，不多一层结构。

**剩下的那一条耦合是单向的，而且是开工前置。** `subst_ty` 作用在一个带 bound 的类型变量上
（把 `C` 代换成具体类型）时，**必须触发效果侧的归约**，否则行里会留下一个主体已经不存在的
投影。这是本刀唯一的新轴间接触面。**落刀前先做一次实测探针**：量它在 `subst` / `unify` /
`inst` 三条路径上的落点数与触发频度，以及「未归约投影能不能活到 ground 类型」这条不变式
（`types.dawn:1167-1173` 对 `TyAssoc` 的同款不变式）在效果轴上怎么表述。比预估贵就走本节末
的退路。

**#44 的机器已经在树上，这笔依赖已付。** 调研报告把「A″ 依赖 #44」列成主要代价，实测不是：
`TraitI.assoc`（`types.dawn:1083`）、`ImplI.assoc_bindings`（`:1274`）、`subst_subject`
（`lower.dawn:939`、`emit.dawn:494`）、`reduce_assoc`（`checker.dawn:457`）与投影的十处穷尽
墙都已随 #44 落地（`assoc-types-design.md` 的状态是 current）。本刀是把同一套形状复制到效果
轴，不是从头造一套。

按规则丙落第三条证据规则；把 `lower_trait_call`
（`lower.dawn:2256-2347`）今天丢弃的 `evid` 接上（它绑在 `:2793` 的 `XCallFn` 模式里，
`:2795` 转 trait 路径时不传；函数内**六**个发射点 `:2287`（`prim_relation`）、`:2296`、
`:2314`、`:2321`、`:2333`、`:2342` 一律只发 `vs` 或 `vs ++ ds`，从不发证据）；bridge 的
`evs: []`（`lower.dawn:1183`）要真的填。

**这五处落点与 A′ 方案逐处相同，一处不增不减**（拼写改了，ABI 没改）；`dict_key`
（`lower.dawn:930`）仍然一个字节都不动，因为槽位形状只取决于 trait 声明，与实例化无关。
A″ 让这一点更直白：一个槽位要不要证据，看的是那条方法行里写没写投影。

**JVM 四处描述符，C 一处 cast 形状。这个不对称本身进验收清单**，因为 C 侧漏了不会立刻炸，
JVM 侧漏了是 VerifyError。

1. **`CImpl` 调用点的描述符是位置重建的**（`emit.dawn:1821-1834`）：超出 trait 方法自身参数
   的每一个实参一律按 `TyVar("D", 0)` 算（`:1830`），而 impl 方法定义侧的证据是**精确类型**
   （`sig_desc_with_dicts` 在 `:401-406` 按标签的 ADT id 发）。证据实参一追加，两边就不一致，
   **这是 VerifyError，不是编译错误**。旧稿没列这一处。
2. **trait 接口描述符**（`gen_trait_interface`，`emit.dawn:1310`，描述符在 `:1317`）。
   `tr_iface`（`rtclasses.dawn:3000`）只产名字，不必改。
3. **INVOKEINTERFACE 调用点**（`trait_method_desc`，`emit.dawn:412`，用在 `CMethod` 的
   `:1852-1855`）。
4. **字典类的转发方法**（`gen_dict_class`，`emit.dawn:1717`）：方法自身描述符在 `:1736-1737`
   的 `method_desc`，转发目标在 `:1748` 的 `sig_desc_with_dicts`，后者已经追加证据。两边今天
   只因为 `ms.sig.eff` 从不带标签而恰好一致。

C 侧只有一处：槽位调用的单一 cast 形状（`emitc.dawn:1265-1272`），因为 C 的槽位是裸函数
指针、类型在调用点重建；`fn_signature`（`emitc.dawn:1731-1752`）与 `fn_signature_def`
（`:1758-1772`）早就发 `f.evs`，不必改。`note_lifts`（`emit.dawn:1152`）与 `CDefault` 调用点
（`emit.dawn:1841` 走 `fn_desc_with_dicts`）已经证据感知，也不必改。

**Emit-Change：每一个 `emit *` 标签**（`scripts/emit-labels.txt:20-29`），加决策 9 的
`doc *` 与 `lsp`。新增语料：`scripts/spike-native/` 的差分件、grammar-corpus 的 accept/reject
对（三处新拼写各要一对：trait 体内 `effect E`、impl 体内 `effect E = !X`、行里的 `!C.E`；
reject 侧至少要有「impl 漏写绑定」与「impl 写两次」两条，钉住 exactly-once），
以及 `trait_method_effects` 的第二次重写（`trait methods cannot declare the effect`
与 `impl methods cannot declare the effect` 两条随本刀消失；两条
`a function type cannot name the effect` 不在本文范围内，那是 #188 的第五条拒绝，留着）。
**种子：零**，除非 `selfhost/src` 或 `std` 自己开始写 trait 方法效果行。
Core 无新节点：`CDictDef`（`core.dawn:285-295`）在调用点路线下不加字段，`CFun.evs`
（`:261`）与 coredump 的 `ev` 参数（`coredump.dawn:161`、`:430`）现成；Core golden 是重录，
从不声明（`scripts/emit-labels.txt:15-17`）。

**前置：刀 4；决策 4（已按 A″ 改写）、6、9、10；决策 5 的四个机制问题（2026-08-19 已全部
裁定）；外加一项开工前置：`EffAssoc` 的轴间耦合实测（`subst_ty` 触发效果侧归约）。**

**退路（A′）。** 若那次实测显示耦合比预估贵，就把拼写退回 A′ 的 trait 效果参数表，
**但保留问题二的改法**（impl 在体内写一次，不从方法行投影，不做跨方法取并）。规则丙、五处
描述符落点、`dict_key` 零改动这三样在两种拼写下相同，所以退路只动语法与类型侧的那一个
构造子，不动本刀已经买下的 ABI。

刀 4 与刀 5 各独占一个发布。

#### 刀 5 落地记录（2026-08-20）

按本节与开工前置探针（`eff-assoc-coupling-probe.md`）落地；探针的三处实测修正照单全收：

- **六个必插落点全部接线**：调用效果实例化 choke（`check_call` 里 `reduce_eff` 包住
  `instantiate_eff`，返回位与参数期望位包 `reduce_ty_effs`）、`unify_into` 声明侧 choke、
  `unify_eff`（签名扩成带 `cx` 与类型绑定表，声明侧原子先归约再比较）、SEM-13 函数值
  实例化、`passes` 一致性检查（`reduce_eff_via_bindings`）、两个后端的 `subst_subject`
  （行与 `TyFn` 内的行一并经绑定归约）。
- **`EUnion` 扩形**：`EUnion(vars, assocs, io)`——投影原子按 (tvar, trait, name) 排序，
  外加一个 io 位，因为 io 吸收变量但**不吸收投影**（投影是待到的证据，同标签），而旧载荷
  表示不了 io 与原子共存的行。
  > **「io 吸收变量」这半句已作废**（2026-08-25，#345）：并运算里 io 不吸收任何原子，
  > 变量与投影同等待遇。权威条文见 [spec.md](spec.md) §6.6。
- **穷尽墙照探针清单新写**：`base_parts` 是效果基轴的第一堵穷尽墙（ELabeled 到基轴
  panic）；`base_subsumes` 改写在它上面，io 不覆盖原子、原子按恰相等包含；`eff_is_ground`
  是 ground 判据；`pub fn main` 的墙扩到投影；调用点解析不到证据来源时是诊断
  （"needs evidence here"）。每堵墙各有一个能转红的变异（见验收记录）。
- **描述符五处落点如清单**：JVM 四处（`sig_desc_with_dicts` 追加擦除格、
  `trait_iface_desc` 统一接口声明 / INVOKEINTERFACE / 字典类转发三处、`CImpl` 位置重建改从
  归约后的行读证据描述符）；C 一处（槽位 cast 把字典拼进实参与证据之间）。
  `dict_key` 一个字节未动。桥接（`make_bridge`）收 trait 形状的证据参数、按 impl 的绑定
  重选并 unerase（`adapt_out` 即 CHECKCAST）。
  > **「unerase 即 CHECKCAST」这半句已作废**（2026-08-26，#355）：投影那一格装的是
  > **证据包**，重选是按标签键走一步链（`ev_from_pack`），不是把整格 cast 成证据记录。
  > 见 §8。

**三处对设计的偏离，均已实测**：

1. **`CMethod` 加了一个 `nev` 字段**（Core 节点字段，非新节点）：C 后端的槽位调用把字典
   拼在实参与证据之间，而 emitc 没有 trait 元数据可数出证据几格，故 Core 携带。coredump
   只在非零时打印，证据零格的 dump 逐字节不变。
2. **投影证据的槽序取 (tvar, trait_id, 成员名) 三元组序**，而非本文「同一主体内按 trait 的
   `effect` 成员声明序」：三元组序与规范形的排序共用一个定义（`by_assoc`），checker、
   lowering 与两个后端都不必查 trait 表就得到同一张表；序依旧是契约，由内联测试钉住。
3. **一致性检查在标签轴上取恰相等**（基轴仍按包含，问题一不动）：impl 方法的证据布局由
   它自己的行合成，而去虚化调用按「trait 行经绑定归约」重建描述符——impl 少写一个标签
   就是元数漂移（实测是 NoSuchMethodError，不是诊断），所以「写出来的标签」两边必须
   逐一相等，诊断点名少了哪个。

另两笔记录：`EffAssoc` 除三元组身份外携带主体的显示名（与 `EffVar` 存名同理，渲染
`C.E` 不必查表）；`grammar.ebnf` 自 2026-07-25 起是 historical，三处新拼写进的是
grammar-corpus（accept 一件、reject 六件），不再改 EBNF。种子零已由 fixpoint 实测
（B == C 逐字节）；九个 emit 语料目标对真父对照逐字节相同（唯一差异是两棵工作树的
绝对路径烘进 panic 串的已知假阳性），`fmt`/`lsp`/`run`/`doc` 差分全绿、无声明。
`trait_method_effects` 第二次重写落地：两条 cannot declare 拒绝消失，替位的是行比较
自己的话；`assoc_effects` 一族语料钉住注册、绑定、归约、ground 墙与双后端证据往返。

**它们与 `#208` 的关系（改正旧稿，2026-08-19）。** 旧稿在此写「刀 4 …… 并解开 `#208`
（UI DSL）要的泛型 state trait」。这句没有勘察背书：#198 的原始勘察全文（358 行、九条卡壳
K1–K9）里 trait 一个字都没出现，Elm 架构的 `update` 按定义是纯的（效果是 `Cmd` 数据），
所以「泛型 state trait」这个诉求在实测里不存在。链条是审计的通用影响句
（`audit-v2/02:275`）被 `:288-291` 挂到 #208 上，再被本文写成「#208 要的」，没有一环是实测。

正确的说法是三句：刀 4（A0）把 trait 表面这堵墙拆掉，`Container` / `column` 那一族（容器
组件收内容闭包）从此写得进 trait；刀 5 关掉 `SEM-10`；而 **#208 真正的墙是 K1（handler 臂
不能累积状态）与 K2（callee 装的 handler 罩不住 caller 传进来的闭包），这两条刀 4 与刀 5
都不碰**。SEM-10 与 #208 的绑定是排期方便，不是技术依赖。

## 5. 先例

完整的十门语言横向对照在决策 5 的「跨语言调研」一节（含汇总表、四条铁律与逐字引文），
这里只留与本文条文直接挂钩的几条，另补三条 2026-08-19 新进来的。

**Flix**：**A″ 的直接来源，也是唯一一门把关联效果做完的语言**。trait 体内 `type Aef: Eff`、
instance 体内 `type Aef = {…}`、消费者写投影，与本文的 `effect E` / `effect E = !X` / `!C.E`
一一对应。两处不能照抄：它的关联效果能装一整个标签集合，靠的是不传证据的动态 handler 查找
（Dawn 已否的候选 D）；它的 instance 形状规则倒是与 `spec.md:603-608` 逐字同款。
它的 stdlib 还给 A0 与 A″ 的共存提供了实证（`forEach` 一行两机制）。

**Swift**：两处位置两种拼写不混用（协议侧 `associatedtype Failure: Error` 是输出位，
函数侧 `throws(E)` 是输入位），与本文「A0 归效果变量、A″ 归关联效果」的分工同构。
非抛满足抛是问题一的包含答案在别处的成文；SE-0108 是问题二不做推断的证词。

**Rust**：两套效果提案都把效果写在 impl 头而不是类型参数表，RFC 3762 明说不把效果当类型
系统的泛型参数（候选 B 的一手病历）；RFC 195 的输入位/输出位定义是 A′ 出局的直接依据。

**Effekt**：最近，且差距明显。Dawn 已经按名引用它的词法 handler 语义
（`effects-design.md:210`「这是 Effekt 的词法 handler 语义」），同样只有尾恢复，同样在调用点
传隐藏证据（`spec.md:1452`），同样没有行多态（`effects-design.md:56` D4）。Effekt 的
`interface` 方法可以带效果参数，能力以隐藏实参在调用点传入；它对「谁给接口方法供能力」的
回答是**调用方，在调用点**，正是 `rc.dawn:531-539` 逼 Dawn 走的那一支。规则丙与它同宗，
包括「一个效果参数至多站一个标签」这条 v1 边界。

**Koka**：全效果行多态。引它只为一件事：论证 Dawn 不做行多态。`effects-design.md:56` 的 D4
已经写下跨语言规律（有行多态才能把 handler 类型化成一等值）。

**Unison**：abilities 进行、推断、隐式，人体工学上最接近载荷一想要的东西，但同样依赖行。

**OCaml 5**：效果不进类型。它是「可以先发 handler 再谈效果类型」的先例，不是参数化的先例。

**Scala 3 capabilities**：能力是**值**加捕获追踪，多态走普通类型参数携带能力集。与 Dawn 的
两点基格 + 标签轴不同宗。

## 6. 落点清单

行号一律对 `cf725f4`。spec 债的拟稿条文在决策 5 的「随刀落的文档改动」一节，这里只列位置。

**spec**：§6.3（`docs/spec.md:1271`）加效果参数的绑定与作用域，并按决策 2 在 `:1280` 加一句；
§6.5 的「边界（v1）」小节（`:1432-1446`）里「trait / impl 方法：方法的行是纯或 `!io`」那条
（`:1436`）随刀 4 与刀 5 分两次改，同一小节新增「效果多态代码能转发、不能结算」一条；
`:1452-1454` 的证据合成规则按规则丙加第三条。**随刀 5 另加 A″ 的三处拼写**：关联效果成员的
声明与作用域、impl 体内绑定的 exactly-once、投影 `!C.E` 的许可位置与归约，条文照 spec 里
关联类型（`type Item`）那几条逐条对写。`spec.en.md` 的 translation digest 同批重登记。

**grammar.ebnf**：`:45-46` 的 `type_params`（`fn` / `alias` / `type` 的效果参数，刀 2 与刀 3）；
`:83-86` 的 `trait_method` / `impl_decl`（方法行放开，刀 4 与刀 5）；刀 5 另加三处产生式：
trait 体内的 `effect` 成员、impl 体内的 `effect` 绑定、效果行里的投影。**`:78` 的 `trait_decl`
不再需要改**（A″ 不给 trait 开效果参数表，旧稿因 A′ 把它列进来）。

**effects-design.md**：§4.5 的 trait/impl 条（`:227-230`，它自己引的四个行号也已过期）与
§7 开放项 5（`:376-379`）；§5.2 步 4（`:309-313`）按规则丙改。§5.1（`:269-299`）的行号与第二条
理由已随本批改正，不必再动。

**审计**：`codebase-audit-v2/02-types-effects-and-semantics.md` 的 SEM-10 条：`:274` 的两处
锚点（它引的 `spec.md:1429-1431` 现址是 `:1434-1436`，`passes.dawn:1218-1227`、`:1706-1714`
现址是 `:1213-1229`、`:1700-1717`）、`:286` 的成本混淆。`:276-280` 的「携带或捕获」已经改对，
不必再动。

**门禁**：`scripts/checker-corpus/cases/trait_method_effects.dawn` 与同名 `.expected`
（今天 11 条诊断：刀 4 去掉效果变量那四条，刀 5 去掉具名标签那两条，写出来的函数类型那两条
两刀都不碰，其余三条是级联）、`scripts/grammar-corpus/`
的 accept/reject 对、`scripts/spike-native/` 的差分语料，以及按本文第 4 节逐刀声明的
Emit-Change 标签。

## 7. 追记：行相减（#350，2026-08-25 裁决）

五刀落地之后暴露出来的一个洞，补在这里而不另开文档：它改的是效果参数**在调用点怎么被
实例化**，正是决策 5 的地界。

### 7.1 缺陷

```dawn
fn go(f: fn() -> Int !(e | io)) -> Int !(e | io) = f()
```

传一个既做 io 又抛 `Tell` 的闭包进去，被拒：`expected fn() -> Int !(e|io), got
fn() -> Int !(Tell|io)`。根在 spec §6.6 的「函数值逐原子容得下」加上 `unify_eff` 的实现：
参数行是「一个变量并上若干具体原子」时，那条臂是一次包含判定，而 `e` 还没有绑定，包含判
自然不成立，于是**任何**抛具名效果的闭包都进不去。当时唯一能收下它的拼法是光秃的 `!e`，
因为那条路径走的是 `ELabeled` 臂，残量直接交给了变量。

换句话说：标签轴上的行相减一直是work的（`!(e | Ask)` 收得下 `!(Tell | Ask)`），基轴上的
从来不是。两者是同一件事写在两个轴上。

### 7.2 裁决与判据

**接受**：参数行形如 `!(e | R)`，`e` 是被调方签名绑定的**唯一**效果变量，`R` 是这条行里
的具体原子集合（具名标签、`io`、关联效果投影），实参行 `S` 满足 `R ⊆ S`，并且**共现前提**
成立时，令 `e := S \ R`。（`R ⊆ S` 这一条 2026-08-26 删除，见 7.7；共现前提不变。）

**共现前提**：被调方签名里提到 `e` 的每一条行，都写下了 `R` 的全部原子。

判据是可观察性。`!(e | R) ~ !S` 的解不止一个（`e` 取 `S \ R`、取 `S`、取两者之间任何含
`S \ R` 的行都能让这一条行相等），但它们在**含 `R` 的行**上取值一致。所以「选了哪个解」
只可能从一条提到 `e` 却不提 `R` 的行上被读出来。签名里没有这样的行，选择就不可观察，
取 `S \ R` 不损失主型；有这样的行，选择就是替调用者做了一个它没写下的决定，仍然拒绝。

这条判据同时解释了为什么「`e := S` 对不对」不是一个可以用变异体证伪的问题：共现前提成立
时，`e` 的每一处消费都会把 `R` 并回去，`S` 与 `S \ R` 在那些位置上不可分辨。要证明这段
代码有信息量，只能去动共现检查本身，或者动 `R ⊆ S` 这个前提，或者把绑定的行弄脏。

### 7.3 实测：向上放宽没有先把这件事办掉

动手前量的一件事，因为 spec §6.6 说「向上放宽仍然免费」，听上去像是 `S ⊉ R` 已经有人管。
在 `a4f9668` 上量到的是：

| 实参行 `S` | 参数行 | 判定（改动前） |
|---|---|---|
| `pure` | `!(e \| io)` | 接受，`e` 保持未绑定，实例化为 `pure` |
| `!io` | `!(e \| io)` | 接受，同上 |
| `!Tell` | `!(e \| io)` | **拒绝** |
| `!(Tell \| io)` | `!(e \| io)` | **拒绝**（就是 #350） |

也就是说，改动前接受的集合恰好是 `S ⊆ R`（`e` 未绑定时 `eff_carries` 判的是
「`{e} ∪ R ⊇ S`」）。向上放宽只覆盖「目标行本来就逐原子容得下实参行」的情形，它并没有
把 `!Tell` 补上一个 io 再放行。新规则接受的集合是 `R ⊆ S`，两个集合只在 `S = R` 处相交，
而那里两条路径给出同一个答案（`e := pure`）。所以这条规则是**纯增量**：改动前绿的没有一
条变红。实现上也按这个顺序写：先问「本来就容得下吗」，容得下就原样走老路。

这张表 2026-08-26 还有第二个用处：它同时量出了当时**被拒的那一格**（`!Tell` 进
`!(e | io)`）长什么样，而那一格就是 7.7 删掉的东西。表本身不作废，它是 `a4f9668` 那天的
实测；作废的只是「`!Tell` 那行必须是拒绝」这个结论。

### 7.4 边界（都是裁决，不是省事）

- **只处理一个效果变量**。行里有两个及以上，余量在它们之间没有主型划分，拒绝不变。
- **只处理参数类型顶层的 `fn`**。嵌在容器里的行不是「一个函数值到达一个槽」。
- **前一个实参绑过 `e` 不是终点**。变量从**未代换**的声明行上读，这一次的余量并进已有
  绑定，见 7.5 小节。（旧稿这一条写的是「`e` 必须仍然自由」，2026-08-26 追认取并时作废。）
- **共现扫描只看被调方的声明**。不看体，不看调用点的其他信息。

### 7.5 取并，不是先来也不是后到（2026-08-26 追认）

一次调用把多个函数值实参穿过同一个 `e` 时，各实参的余量 `S_i \ R` 取并并进 `e` 的绑定。
另外两种做法都实测过，各自的败因如下。

**先来居上**（`e` 一旦有绑定就不再动它）。同一对闭包，判定取决于实参写下的次序：`!(e|io)`
的参数上，抛标签的那个写在前面被拒、写在后面被接受。诊断也难看，它把第一个实参定下的那条
行印成 `expected`，而作者从没写过那条行。

**后到居上**（先减掉旧绑定再重绑）。`dawn check` 全绿，`dawn run` 在 `dawn_ev_get` 上
panic：先写的那个闭包拿到的证据包里缺了它自己那个原子。这个「检查全绿、运行期 panic」的
类别，正是 2026-08 的证据一批在别处一件件关掉的东西。

**一致性**。光秃的 `!e` 参数一直是取并的（`unify_eff` 的 `EffVar` 臂就是
`lub_eff(prev, actual)`），`fn both(t: fn() -> Int !e, u: fn() -> Int !e)` 收两个抛不同标签
的闭包一直是绿的。一条参数行的两种拼法不该给出不同答案。这一点在 Koka 那里是白捡的，在这里
不是：Koka 的实参行是开的，取并是行多态合一的副产品；Dawn 的实参行是闭的，少写这一句，
实现就会默认滑向先来居上。撤销成本也小：一次 `lub_eff` 调用，加语料里的几条。

**配套条件**：`e` 要在每个参数**未代换**的声明行上找。前一个实参绑定 `e` 之后，代换后的行
里没有变量可找，只照代换后的行看会把第二个实参判成一次普通的行不匹配。

### 7.6 落点

实现是 `selfhost/src/check/checker.dawn` 的 `earg_row_subtract`（连同 `sig_rows` /
`earg_cooccurs` / `eff_row_minus`），在 `check_call` 的两轮推断循环里，`unify_into` 之前
调用。拒绝时的提示同批加厚：指向今天就能用的修法（把参数行写成光秃的 `!e`），共现前提
失败时另外点名是哪一处出现让选择变得可观察。

门禁：`scripts/checker-corpus/cases/effect_row_subtract.dawn` 钉住接受与拒绝两侧的判词，
`scripts/spike-native/effect_row_subtract.dawn` 与 `scripts/effect-evidence-contract` 的名册
钉住运行期，两个后端都跑。spec 的条文进 §6.6，中英同批。

### 7.7 `R ⊆ S` 这个前提删了（#363，2026-08-26 裁决）

**裁决**：实参的行不必含有 `R`。短于 `R` 的行照样绑定 `e := S \ R` 并接受，7.2 里的
`R ⊆ S` 作废。共现前提、双变量拒绝、以及「实参行里有个原子而目标位置没有」那一侧的拒绝，
三条都不动。

**它拦住的是什么**。7.3 那张表里 `!Tell` 进 `!(e | io)` 的那一格。被拒的集合恰好是
「做了点事，但不是 `R`」：纯闭包过，`!io` 闭包过，只抛自己那个标签的闭包不过。这正是
`run` / `with_timing` / `retry` / `bracket` 这一族组合子的默认形状，io 是**组合子自己
的体**在做，写进参数行是在说「回调可以做 io」，不是在收一笔回调必须付的账。转发也拦：
`fn forward(g: fn() -> Int !e2) -> Int !(e2 | io) = run(g)` 两边都承诺了 io，照样被拒。

**为什么删掉是安全的**。包是**作用域，不是行的流水账**（`runtime/c/dawn_rt.c` 在
`dawn_ev_is_node` 上方的原话）。调用点建包用的是这一次**实例化后**的行
（`checker.evidence_pack`，经 `evidence_var_args`），不是闭包自己的行；读取是
`dawn_ev_get` 按键沿链走，不是按下标定位。所以短一截的闭包拿到的是个超集，多出来的键没
人读，取不到才 panic，多给不会。`types.eff_carries` 的头注早就把同一件事写在另一侧：
「超集永远安全，被拒的是行里有个原子而目标没有」。

**判据来自实测，不是推理**。M3 变异体（只删这一条前提，别的不动）跑下来：`dawn check` 过，
运行期答案算术正确（补齐探针 43 / 149 / 149，转发探针 43），效果证据契约、selfhost 测试
全绿，checker 语料只有 `short_of_r` 那一条判词消失。删除据此落地。

**门禁**：`scripts/spike-native/effect_pad_row.dawn` 按值钉住四个故事（补 io、补具名原子、
转发、纯闭包进带名原子的槽），进 `scripts/effect-evidence-contract` 的名册，两个后端都跑；
`scripts/checker-corpus/cases/effect_row_subtract.dawn` 把这几个形状挪进「接受」半边，
留下的三条拒绝判词不动。生产变异体 H（把前提装回去，检查期红）与 I（把包按闭包的行建，
运行期红）记在 `scripts/effect-evidence-contract/README.md`。

## 8. 追记：投影那一格装的是证据包（#355，2026-08-26）

### 8.1 缺陷

```dawn
fn f[T: P](x: T, t: fn() -> Int !T.E) -> Int !T.E = run(x) + t()
```

check 全绿，运行期 panic `effect evidence missing`。别名拼写 `Thunk[!T.E]` 忠实转发同一个
洞（#351）。行里投影旁边再站一个证据原子时，报的不是 panic 而是 `ClassCastException`
（某个效果的记录被 cast 成另一个效果的），因为那时投影那一格不是整格交出去，而是被 cons
到节点的 `outer` 位或被 `ev_append` 接进链里，走链的人于是拿到别人的记录。`!io` 不是原子，
不占格，所以它是唯一不触发的邻居。

### 8.2 根因

规则丙的条文写着「效果参数被实例化成一个具体标签时，调用方交出该标签的证据」。V1′ 的证据
包落地后这句就不对了：投影和效果变量是同一类原子——**行未知的原子**——而
`lower.ev_from_pack` 的规则从落地起就是「非标签键由整条链回答」。于是调用点
（`evidence_assoc_args`）交出记录、去虚化的读者（`impl_ev_sources`）把记录 cast 回来，两边
自洽，跟布局的其余部分不自洽。**只要没有人走那一格，两套约定就分不出来**：投影写在返回
行位时确实没人走（callee 转发进字典，impl 侧 cast 回来），而 `assoc_effects.dawn` 通篇是
返回行位，所以门禁全绿。写在**参数行位**上就有人走了——调用函数值时那一格就是被交出去的
包，闭包在里面按标签键问它。

### 8.3 裁决与判据

**投影那一格装包**，与效果变量同待遇。判据是 `ev_from_pack` 那条既有规则：一个键是标签就
走到它的节点，不是标签就整条链回答。规则丙的**机制一字未改**——一个投影恒定一格、调用点
供给、字典槽位边界上擦除——变的只是那一格里装什么。

调用点因此改成用 `evidence_pack` 建那一格（把投影按调用点的绑定归约后的行喂进去），刚性
转发、纯、io 三种情形从 `evidence_pack` 里原样落出来：刚性时行里只有一个非 ground 原子，
`evidence_pack` 的免分配快路径就是「那一格本身」，正是原来刚性支路做的事。读者侧
`impl_ev_sources` 相应改成走一步链。

### 8.4 边界

- **`types.assoc_key` 按 trait id 分带**，所以同一 trait 上的两个投影（`!T.E` 与 `!U.E`）
  共用一个键。它答得对，理由是非标签键由整条链回答、而包的超集仍是包——同一条性质设计里
  处处在用。修复前它答错：一个投影拿到另一个投影的记录。
- **`sig_abi_eff` 不把参数行里的投影折进 ABI**（效果变量有 `eparams` 那一折，投影没有）。
  实测这不是洞：一个投影要被读，它就必须写进本函数的行（否则 checker 直接拒绝，
  "not declared !T.E but calls"），而写进行里就有格；闭包里读到的那一格来自闭包自己的包，
  不是本帧的槽。两条都有探针实测。

### 8.5 落点

`selfhost/src/check/checker.dawn` 的 `evidence_assoc_args`，`selfhost/src/ir/lower.dawn` 的
`impl_ev_sources` / `ev_select`（`impl_evidence` 与 `make_bridge` 共用后者）。

门禁：`scripts/spike-native/effect_assoc_row.dawn` 与 `scripts/effect-evidence-contract` 的
名册钉住运行期，两个后端都跑；`scripts/checker-corpus/cases/effect_type_args_ok.dawn` 里那
条「刻意不进运行期门禁」的注释随之作废。两个生产变异体（读者半边与写者半边各一）记在
`scripts/effect-evidence-contract/README.md`。

## 9. 追记：关联效果默认值（#369，2026-08-26 裁决）

刀 5 的「无默认值」是 v1 的取证保守（调研在这一格拿不到一手依据），当时就标为纯加法。
树内随后自己长出了消费者：tea 的 `trait App` 加 `effect E` 时五个 impl 各付一行
`effect E = !()` 纯样板，且那次迁移动了 8 个文件——「trait 加成员 → 全部 impl 破坏」正是
默认值要买断的演化形状。用户裁决（2026-08-26）：**只做效果轴**；关联类型默认值不做，
等真消费者出现再裁（类型轴今天可删除的绑定是零行，且没有规范默认元——效果轴有，`!()`
是效果格的底，与「省略即纯」同构）。

**机制一句话**：trait 成员可写 `effect E = !X`，右侧与 impl 绑定同一条 ground 纪律
（`!()`、`!io` 或一个具名效果；变量、投影、并集照拒）。注册 trait 时解析进
`TraitI.eff_defaults`；`pass_register_impls` 的缺绑定分支若查到默认，就把它物化成该 impl
的绑定，查不到保持原报错。物化之后，归约、证据、两个后端对「默认来的」与「写出来的」
绑定不可分辨——tea 五个 impl 删掉绑定前后 Core 逐字节相同，是这句话的可执行判词。
降级、后端、证据链路零改动。

门禁：grammar-corpus 的 reject `assoc_effect_member_default` 翻成 accept（显式契约翻转），
另加坏默认 RHS 的 reject 族；checker-corpus `assoc_effect_defaults` 钉「省略即默认、覆盖
生效、无默认照报缺、错默认两端拦」；`effect_assoc_row.dawn` 的 `ByDefault`/`Overr` 对按值
钉两条路，生产变异体 J/K/L 记在 `scripts/effect-evidence-contract/README.md`。
