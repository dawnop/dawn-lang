# 效果参数（RX-10-B）设计

> 状态：proposed。基线 `098419d`（main）。本文定范围、结构落点与决策点。刀 1 的前置只有
> 决策 1（本文已定），可先做；**刀 4 在决策 5 被评审通过之前不动一行码**。
> RX-10 期权 A 的裁决见 [audit/re-audit-2026-07-30.md](audit/re-audit-2026-07-30.md)
> 第 593 行，B 的原始定义见 [audit/re-audit-b-decisions.md](audit/re-audit-b-decisions.md)
> 第 560 行起。

## 1. 范围：三件载荷，一件出局

RX-10-B 在两份来源文档里累积了三件互不相同的载荷，两份文档从未对账。

| 载荷 | 首次命名 | 性质 |
|---|---|---|
| 一、可命名的效果多态类型（`alias Mapper[T, U, !e]`、`type Box[!e]`） | `audit/re-audit-b-decisions.md:560-564` | 纯检查期 |
| 二、trait / impl 方法带效果行 | `audit/re-audit-b-decisions.md:585`、`effects-design.md:361` | ABI 变更 |
| 三、`effect Yield[T]` | `effects-design.md:42-44`、`:360-361` | 另一根轴 |

**裁决（本文定，不重开）：载荷三 `effect Yield[T]` 出局，另立任务。**

理由是两者方向相反。载荷三是把 `Ty` 塞进 `Eff`，代价写在
`effects-design.md:42-44`：「会让 subst 的类型/效果双 map 互递归、`Map[Eff, …]` 的键全动」。
载荷一与载荷二是把 `Eff` 塞进类型参数列表，代价写在 `audit/re-audit-b-decisions.md:561-564`。
一个动效果轴的内部结构，一个动类型参数列表的成员种类。
[assoc-types-design.md](assoc-types-design.md) 第 158 行已经就同一件事判过：
「RX-10-B（效果参数进类型参数表）：正交；`type Item` 是类型轴成员，效果轴另说」。

把两者当一件任务是文档的错误，且只发生在两处：`effects-design.md:42-44` 的非目标行、
以及同文 §7 开放项 5（`:360-361`）。这两处已随本文改正。载荷三另立任务号，判据是
「`Eff` 要不要带类型参数」，与本文无前后置关系。

**同时出局**：行多态（row polymorphism）。裁决已在 `effects-design.md:55`（D4）：Dawn 无
行多态，handler 因此走语法形式而非一等值。本文不重开，效果参数是**参数**，不是行变量。

## 2. 结构事实：效果变量已存在，但在 `Sig` 里没有位置

这一节先于任何语法讨论，因为它决定了第一刀的形状。

**效果变量今天就是一等 `Eff` 构造器。** `EffVar(name: String, id: Int)` 在
`selfhost/src/check/types.dawn:29`，由 `fresh_effvar` 铸造，`resolve_eff_at`
（`selfhost/src/check/cx.dawn:435-463`）在遇到未登记的小写原子时**隐式**铸一个并存进
`cx.current_eff_vars`（`:449-457`）。这是 `docs/spec.md:1245`「效果变量 `!e` 无需声明，
在签名中出现即引入；作用域是整条签名」的实现。大写未知原子是错误（`cx.dawn:445-448`），
诊断里写着「effect variables are lowercase」。

所以 RX-10-B 不是「引入一个跨效果的变量」。它是「给这个变量一个显式绑定者，和一个
比一条签名更大的作用域」。

**但这个变量在 `Sig` 里没有任何表示。** `Sig`（`types.dawn:964-986`）有 `eff: Eff`（`:973`）、
`tparams: List[Ty]`（`:975`）、`constraints: List[List[Int]]`（`:977`），没有效果参数分量。
签名的效果变量表走一条**侧信道**：`pass_fn_sigs` 在 `passes.dawn:2097` 把
`cx1.current_eff_vars` 抄进 `ev`，在 `:2121` 追加进一条与 `sigs` 平行的 `evs` 列表，
在 `:2126` 作为第三个返回值交出去；消费方是 `enter_fn`
（`selfhost/src/check/checker.dawn:8309`），它把它当独立形参收下并装回
`cx1.current_eff_vars`（`:8327`）。`Sig` 字面量（`passes.dawn:2101-2119`）里没有它的位置。

**两处拒绝把这条侧信道当谓词用。** trait 方法与 impl 方法的签名检查各装一张空的
`current_eff_vars`（`passes.dawn:1229-1231`、`:1716-1718`），跑完 `resolve_type` 之后问
「有没有东西**漏**进来」（`:1250`、`:1740`），漏了就报错（`:1256-1259`、`:1742-1744`）。
这是拿副作用当谓词：判据不是「这条签名声明了什么」，而是「解析过程往一张临时表里写过没有」。

（另有四处只装空表、不问漏没漏，用途是隔离而非判断：`passes.dawn:1049`、`:1539`、`:2062`、
`:2213`，以及 alias 目标解析的 `cx.dawn:543-548`。它们不是探针，改绑定者机制时不必动。）

**证据通道本身已经完工。** 一个签名写出的每个标签在 `bind_evidence`
（`checker.dawn:8351-8359`）声明一个隐藏局部，`ev_sym_list`（`:8363-8373`）按效果 id 收齐，
经 `TFun.ev_syms`（`selfhost/src/check/tast.dawn:255-259`）→ `CFun.evs`
（`selfhost/src/ir/core.dawn:261`）→ `lower_fn`（`selfhost/src/ir/lower.dawn:3465-3470`、`:3502`）
到两个后端（`selfhost/src/jvm/emit.dawn:1247`，描述符 `:394-407`；
`selfhost/src/c/emitc.dawn:1747`、`:1767`）、解释器（`selfhost/src/ir/interp.dawn:675`）
和 Core dump（`selfhost/src/ir/coredump.dawn:161`、`:430`）。调用侧的附加序是
`vs ++ ds ++ es`（`lower.dawn:2782`、`:2788`）：实参、字典、证据。

缺的不是通道，是「效果能当参数」和「字典槽位能上这条通道」。

## 3. 决策点

编号沿用勘察，便于任务登记按号引用。决策 11 已在 §1 结清（出局）。

### 决策 1（已定）：效果参数用 `Sig` 的**新分量**，不进 `tparams`

**裁决：新增分量（暂名 `eparams`），不在 `tparams` 里混。**

强制它的是三处代码，不是审美。

`tparams: List[Ty]` 的元素类型是 `Ty`（`types.dawn:975`），`Eff` 不是 `Ty`，混进去要么加和类型
要么加平行字段。而 `constraints: List[List[Int]]`（`:977`）与 `tparams` **按位对齐**
（`bounds_of`，`:989-993`）：

- JVM 的字典元数是把 `constraints` 的各段长度求和得来的（`emit.dawn:397-398`）；
- `bind_dicts` 用 `tparams` × `bounds_of(s, i)` 双层遍历（`checker.dawn:8255-8256`），
  内层是 `match tp { TyVar(tn, vid) -> … ; _ -> () }`（`:8257-8279`）。

关键在那个 `_ -> ()`（`checker.dawn:8278`）：一个不是 `TyVar` 的 `tparams` 条目会被**静默跳过**，
而外层的 `i` 照样递增。于是 `constraints` 的下标与 `tparams` 的下标错位，字典符号绑到错的
类型变量上，编译期不报任何错。混合列表会「看起来能用」，然后是错的。

独立分量把「字典轨一行未动」变成可证的，而不是可辩的：`constraints` 与 `tparams` 的对齐关系
逐字不变，字典元数的求和式逐字不变。

**代价已量**：`Sig` 加一个分量要改 **20 处**逐字段列出的 `Sig { … }` 字面量，分布在 6 个文件
（`checker.dawn` 6、`passes.dawn` 4、`types.dawn` 5、`lower.dawn` 3、`interp.dawn` 1、
`emit.dawn` 1）；另有 12 处 `Sig { ..s, … }` 展开式不受影响。同批可以退役 `evs` 侧信道
（`passes.dawn:2097`、`:2121`、`:2126`、`checker.dawn:8309`）。

### 决策 2：绑定者是强制还是可选，即 `spec.md:1245` 的隐式引入是否存活

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
签名内只解析到它；没有时照 `spec.md:1245` 隐式引入。** `resolve_eff_at` 的隐式铸造臂
（`cx.dawn:449-457`）在前者下不再触发，因为查表就命中了。

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

### 决策 4：哪些声明形式带参数表，形状如何

**这是整个特性最大的分叉。** 今天四种声明形式里三种没有可扩展的列表：

| 形式 | 今天的形状 | 证据 |
|---|---|---|
| `fn` | `tparams: List[TypeParamDecl]`，带 bound | `selfhost/src/front/ast.dawn:328` |
| `alias` / `type` | `tparams: List[String]`，bound 在解析时被丢掉 | `ast.dawn:346`、`parser.dawn:486-492` |
| `trait` | **单个** `tp: String` | `ast.dawn:396`、`docs/grammar.ebnf:78` |
| trait 方法 | **没有**类型参数表 | `docs/grammar.ebnf:83-84` |
| impl 方法 | 明确禁止类型参数表 | `docs/grammar.ebnf:85-86` |

**推荐：效果参数挂在 trait 上（`trait Parser[S, !e]`），不给 trait 方法新开参数表。**

三条理由。

一、trait 本来就要改。它今天只有一个类型参数（`ast.dawn:396`、`grammar.ebnf:78`），
要带效果参数就得有一张列表；给方法再开一张是第二次改动、第二个作用域、第二套解析。

二、「一行管全 trait」的粗粒度只在拼写上，不在 ABI 上。方法的证据参数是按
**它自己的 `Sig.eff`** 合成的（`bind_evidence` 读 `eff_labels(s.eff)`，`checker.dawn:8353`；
描述符同理，`emit.dawn:403-406`）。同一个 trait 里不提 `!e` 的纯方法，`Sig.eff` 仍是 `EPure`，
不多一个参数。所以纯兄弟方法不为这个参数付任何运行时代价。

三、字典是按 impl 建的，证据必须走调用点（决策 5）。trait 级的一行让「哪些槽位要证据」
成为 trait 声明的一个静态属性，接口描述符可以一致地推导；方法级则要在每个槽位单独携带
它自己的效果参数表。

`alias` / `type` 的参数表本来就要从 `List[String]` 加宽（决策 8 的刀里一起做）。

### 决策 5（枢纽）：效果参数在单态调用点被实例化时，谁供证据

**这是决定载荷二成立与否的决策，也是本文唯一要求先评审后动码的一条。**

先把两条既有规则摆出来，它们都会被这一条撞到。

**规则甲（写出来的标签合成参数）**，`docs/spec.md:1417`：

> 签名里写出的每个标签给函数追加一个隐藏证据参数，**排在字典参数之后**、按效果 id 升序。

实现是 `evidence_args`（`checker.dawn:5953-5992`），它按 `eff_labels(declared)` 逐个从词法
环境解析证据；找不到就是「没人应答」的报错，报在调用点。

**规则乙（经效果变量流进来的标签不合成参数）**，`docs/spec.md:1418-1419`：

> 经效果变量流进来的标签不合成参数

紧接的半句给的理由是证据在闭包的捕获里，因此高阶库函数（`list.map` 之流）零改动。
同一条规则在 `effects-design.md:293-297`（§5.2 步 4）复述为「证据参数只按签名里**字面写出的**
labels 合成；经变量流进来的 labels 由闭包捕获自理」。实现是
`instantiated_labels`（`checker.dawn:5925-5938`）与 `evidence_args` 的互补关系：前者算出
「实例化行里被调方没写下来的标签」，后者只管写下来的那些。

**规则乙的全部依据是「有一个闭包可以捕获它」。字典槽位不是闭包。**

而证据也不能存进字典。`dictish`（`selfhost/src/c/rc.dawn:528-538`）的注释是结论本身：

> A dictionary: outside the ledger entirely. It has no header at all -- a drop on one
> would read garbage as a count -- so no binding of one is ever tracked and no release
> is ever emitted.

`effects-design.md:277-280`（§5.1）把这条写成裁决：「**刻意不复用 CDict**：字典是账本外的
无头静态表，而 handler 臂是捕获局部的真闭包，必须进 RC 账本」（该处引的
`rc.dawn:513-521` 是旧行号，现址是 `rc.dawn:528-538`）。

于是**捕获这条路已经被封死**，证据只能走调用点。
`docs/codebase-audit-v2/02-types-effects-and-semantics.md:276` 写「dictionary 必须显式携带
或捕获 evidence」，把它当成一个未定的二选一，这是错的：捕获那一支要先把字典搬进 Perceus 账本，
那是 [perceus-design.md](perceus-design.md) 的改动，不是效果系统的改动，任务号与负责人都不同。

**所以需要第三条规则，`effects-design.md` §4.6 与 §5.2 都没有它。** 它要回答两个方向：

**5a（调用方）** 一个 trait 方法的效果参数在调用点被实例化成 `(base, L)` 时，`L` 里的标签
要不要合成证据实参？必须要，因为被调方没有闭包可捕获。落法是把 `instantiated_labels`
（`checker.dawn:5925-5938`）算出的那批标签**按来源分流**：来源是普通效果变量的照旧不合成
（规则乙保留，`list.map` 仍然零成本）；来源是声明级效果参数的合成实参。这要求实例化时记下
「这个标签是从哪个变量来的」，今天 `unify_eff` 的 `EffVar` 臂（`checker.dawn:697-703`）只累积
lub，不记来源。

**5b（被调方）** 一个刚性效果参数在 impl 方法体内是什么？它是一个**不可使用、只能转发**的
隐藏参数：方法体不知道那个效果有哪些操作，所以永远调不动它的操作；它唯一的用途是继续传给
签名提到同一个参数的被调者。`bind_evidence`（`checker.dawn:8351-8359`）今天按
`eff_labels(s.eff)` 绑定，刚性效果参数在 `eff_labels` 里不出现（`types.dawn:65-69` 只返回
具体标签），所以 5b 需要**按效果参数**而不是按标签绑定隐藏局部，并让 `evidence_args` 在
被调方签名提到该参数时转发它。这是一套今天不存在的机制（证据多态），也是载荷二真实成本的
所在，以及第四刀必须独占一次发布的理由。

**两条既有规则的改法**（若 5a/5b 按上述落）：

- `spec.md:1418` 的「经效果变量流进来的标签不合成参数」要加限定：**除非该变量是一个声明级
  效果参数**。
- `effects-design.md:293-297`（§5.2 步 4）的「只按字面写出的 labels 合成」要改成「按字面写出的
  labels 加上被实例化的效果参数合成」。

**若评审的结论是「字典捕获证据」，那本文的第四刀就不是效果系统的改动。** 它是把字典搬进
Perceus 账本，属于 [perceus-design.md](perceus-design.md) 的范围，另立任务、另有负责人；
本文的载荷二随之退回「等那件事」。这句话必须写在这里，因为它决定第四刀归谁。

### 决策 6：刚性效果参数会被推断进吗

**推荐：不会。刚性效果参数是已知效果，不是待解变量。**

`unify_eff`（`checker.dawn:688-714`）今天分三类：`EPure`/`EIo` 交给 `eff_subsumes`（`:695-696`）；
`EffVar` 绑定并累积 lub（`:697-703`）；`EUnion` 与 `ELabeled` **明确不被推断进**
（`:706`、`:709-713`，注释「a union in a declared parameter position is not inferred into」、
「a declared label is not inferred into either」）。

一个声明级的刚性效果参数三类都不是。它应当照 `is_concrete` 对刚性**类型**参数的处理
（`checker.dawn:718-728`：出现在 `cx.current_tparams` 里就算已知），而效果侧今天没有对应物。
所以决策 6 的落地物是「效果侧的 `is_concrete`」。

### 决策 7：使用点省略效果实参是什么意思

**推荐：省略即纯，与 `instantiate_eff` 今天的默认一致；不是元数错误。**

`instantiate_eff`（`checker.dawn:5940-5947`）把未绑定的效果变量默认成 `EPure`，注释在
`:5792`（「an unbound effect variable means pure」）。让 `Mapper[Int, String]` 报元数错误会与
这条默认冲突，也会让效果参数比类型参数更啰嗦。

一个真实缺口要一并记下：类型引用今天**没有**效果实参的语法位，`TNamed`/`TQual` 的实参只是
`List[TypeRef]`（`selfhost/src/front/ast.dawn`）。所以「显式给效果实参」这件事本身需要新语法。
推荐第一批不做，只支持省略（推断），显式实参等出现无法推断的消费者再开。

### 决策 8：RX-10 期权 A 是撤销、收窄，还是保留

**推荐：收窄，不撤销。**

`refuse_decl_effvar`（`selfhost/src/check/passes.dawn:293-302`）今天对类型声明位的效果行一律
拒绝，一条消息盖两个不同的理由。这个设计的自述在 `:281-292`：

> Saying which of the two it is would take knowing whether the atom names a declared
> effect, and this pass runs before `pass_effects` registers them.

B 落地后两个理由分道：**效果变量**那一半变成有条件的（取决于这个声明自己的参数表里有没有
绑定它），**具名效果**那一半仍然无条件（`effects-soundness-design.md` §4.1 的禁令，实现在
`refuse_written_label`，`cx.dawn:573-582`）。有条件的那一半需要知道声明自己的参数表，这个
pass 拿得到；但要区分「小写原子是本声明绑定的效果参数」和「小写原子什么都不是」，仍不需要
`pass_effects`。所以 pass 序不必改，改的是消息：拆成两条，各说各的理由。

顺带结清一条与裁决无关的旧账：`audit/re-audit-b-decisions.md:576-578` 记下的 `poly_apply`
提示（「add !e to the end of the signature」而签名已经有 `!e`）「无论选 A 还是 B 都是错的」；
选 B 时它必须改。同一刀里改。

### 决策 9：效果参数在 `sig_render` 里渲染吗

**推荐：渲染。**

`sig_render`（`selfhost/src/check/types.dawn:1248`）是唯一的签名渲染器，`tparams` 连 bound
一起渲染在 `:1249-1265`。它同时服务 `dawn doc`（`selfhost/src/doc.dawn:251`、`:278`、`:388`、
`:567`、`:613`、`:638`、`:699`）与 LSP hover（`selfhost/src/lsp/lspq.dawn:333`）。

渲染的代价是 `Emit-Change(doc --builtins)` 与 `Emit-Change(lsp)`（标签见
`scripts/emit-labels.txt:38`、`:59-62`）。不渲染的代价是 hover 与 doc 对签名的元数说谎，
而证据参数的个数正取决于它。前者是一次声明，后者是长期错误。

顺带记一条已经陈旧的东西：LSP 在 `!` 之后的补全**只给 `io`**
（`selfhost/src/lsp/lspc.dawn:841-845`，注释「the effect row: `!` admits exactly one builtin
effect」）。自 #110 落地具名效果起这就不对了，B 会让它更不对。不阻塞本文，登记为小件。

### 决策 10：trait / impl 一致性检查如何比较与渲染带效果行的方法

**推荐：`eff_show2` 删除，换 `eff_show`；一致性判据 `eff_subsumes` 不变。**

一致性检查在 `passes.dawn:1764`：`eff_subsumes(msv.sig.eff, eff)`，判据本身双轴，不必改
（`eff_subsumes` 在 `types.dawn:174-181`）。要改的是渲染与文案：

```
fn eff_show2(e: Eff) -> String = if e == EIo { "io" } else { "" }
```

`passes.dawn:1932`。一个两值渲染器，它存在的**原因**就是这个位置只能是纯或 `!io`。它今天对
任何别的行返回空串，于是 `:1765-1767` 会打出「`m` is declared ! but trait `T` declares it
pure」。同一处的 `want_render`（`:1758-1760`）也把 `eff_suffix(msv.sig.eff)` 写死。

这是「限制被烘进代码而不是被检查」的最小最具体的证据，也是判断第四刀是否落干净的
现成判据：`eff_show2` 还在，就说明没落干净。

### 决策 11：`effect Yield[T]` 在不在范围内

**已在 §1 结清：出局，另立任务。**

## 4. 刀法

四刀。先把两个成本讲清楚，因为审计把它们混了
（`docs/codebase-audit-v2/02-types-effects-and-semantics.md:282` 写「字典形状变更还要
Emit-Change 加一轮种子」）：

- **Emit-Change** 由**发射出来的产物移动**触发。声明的标签集见
  `scripts/emit-labels.txt`（`emit *` 在 `:20-29`，`fmt` 在 `:35`，`lsp` 在 `:38`，
  `doc *` 在 `:59-62`）。
- **一轮种子**只由 `selfhost/src` 或 `std` **开始使用** N−1 种子解析不了的语法触发。纪律写在
  `effects-design.md:312`、`:317-318`（「selfhost/src 与 std 不得使用新语法（种子 parse 不了）」），
  底座是 `bootstrap.md`。

两者独立：改字典描述符只花 Emit-Change 行，不要种子轮；改 `std/` 的签名拼写要种子轮，
哪怕一个字节的产物都没动。

### 刀 1：给效果参数在 `Sig` 里安家，不改变任何可观察行为

加 `Sig` 分量（决策 1）；让 `resolve_eff_at` 的隐式铸造（`cx.dawn:449-457`）记进这个分量；
退役 `evs` 侧信道（`passes.dawn:2097`、`:2121`、`:2126`、`checker.dawn:8309`），`enter_fn` 改从
`Sig` 读回；把两处泄漏探针（`passes.dawn:1250`、`:1740`）换成对签名参数表的直接提问。

每条签名的效果参数恰好就是今天隐式规则铸出的那些，所以行为逐位不变。`sig_render` 不改，
doc 与 LSP 不动。

**Emit-Change：零。语料移动：零。种子：零。** 前置只有决策 1。

**它自己就站得住**，即使 B 永不落地：效果变量是全语言唯一一个「在它所绑定的东西里没有表示」
的绑定者，而两处拒绝拿副作用当谓词。这两条都是缺陷，与特性无关。刀 1 还把泄漏探针变成真正的
提问，那是后两刀能把拒绝**收窄**而不是**删除**的前提。

### 刀 2：`fn` 上的显式绑定者语法，可选且等价

`parser.dawn:410-445` + `docs/grammar.ebnf:45-46` + `spec.md:1245` 的条文。合法化
`fn map[T, U, !e](…)`。语义零变化，绑定者与今天的隐式引入等价（决策 2）。

**Emit-Change：可能 `fmt`（`scripts/emit-labels.txt:35`），需先跑幂等探针（决策 3）。**
决策 9 若说渲染，本刀不触发 doc/lsp，因为等价签名渲染结果不变（除非作者真写了绑定者）。
**种子：零**，条件是 `selfhost/src` 与 `std` 在发布之前不用新语法（一代滞后）。
前置：决策 2、3。

### 刀 3：`alias` 与 `type` 上的绑定者，RX-10 A 收窄

`ast.dawn:346` 的 `tparams: List[String]` 加宽，`parser.dawn:486-492` 跟着改；
`refuse_decl_effvar`（`passes.dawn:293-302`）收窄成只拒**未绑定**的变量，消息拆两条（决策 8）；
`poly_apply` 的提示同批改。交付 RX-10 的原始诉求：
`alias Mapper[T, U, !e] = fn(T) -> U !e` 与 `type Box[!e] = { f: fn(Int) -> Int !e }`。

**纯检查期，无运行时物。** 因为 SEM-01 的结算规则（`effects-soundness-design.md:39-40` 的 ②，
落在 `effects-design.md:245-262` §4.6）让闭包在**创建点**结算自己的行并自带证据，字段上的
`!e` 由闭包捕获的证据消掉，没有东西要在调用时传。`effects-design.md:237-238` 已经就此更正过
自己：「「带 label 的闭包不能存进记录字段」不再成立」。

**Emit-Change：决策 9 若说渲染，则 `doc *` 与 `lsp`。种子：零。**
前置：决策 3、4、7、8。

刀 1 至刀 3 一个发布。

### 刀 4：trait / impl 方法带效果行

删两条拒绝（`passes.dawn:1218-1227`、`:1706-1714`），把另两条收窄成「未绑定的效果变量」
（`:1256-1259`、`:1742-1744`）；`eff = if len(me.effs) == 0 { EPure } else { EIo }`
（`:1261`、`:1739`）换成真的 `resolve_eff_at`；给 trait 一张参数表（决策 4）；`eff_show2`
（`:1932`）删除（决策 10）；按决策 5 落第三条证据规则，并把 `lower_trait_call`
（`lower.dawn:2226-2317`）今天丢弃的 `evid` 接上（它绑在 `:2763` 的 `XCallFn` 模式里，
`:2765` 转 trait 路径时不传；函数内五个发射点 `:2266`、`:2284`、`:2291`、`:2303`、`:2312`
一律只发 `vs` 或 `vs ++ ds`，从不发证据）；JVM 的接口方法描述符（`emit.dawn:1736-1737` 的
`method_desc`）加宽到与转发目标（`:1748` 的 `sig_desc_with_dicts`，它在 `:403-406` 已经追加
证据）一致，`tr_iface`（`selfhost/src/jvm/rtclasses.dawn:3000`）随之；C 的单一 cast 形状
（`emitc.dawn:1263-1272`）加宽。

描述符不一致是**验证器失败**而不是编译错误：接口方法没有证据参数可载，转发目标却要，
两边今天只因为 `ms.sig.eff` 从不带标签而恰好一致。

**Emit-Change：每一个 `emit *` 标签**（`scripts/emit-labels.txt:20-29`），加决策 9 的
`doc *` 与 `lsp`。新增语料：`scripts/spike-native/` 的差分件、grammar-corpus 的 accept/reject
对，以及 `scripts/checker-corpus/cases/trait_method_effects.dawn`（今天钉住 11 条诊断）的重写。
**种子：零**，除非 `selfhost/src` 或 `std` 自己开始写 trait 方法效果行。
Core 无新节点：`CDictDef`（`core.dawn:285-295`）在调用点路线下不加字段，`CFun.evs`
（`:261`）与 coredump 的 `ev` 参数（`coredump.dawn:161`、`:430`）现成；Core golden 是重录，
从不声明（`scripts/emit-labels.txt:15-17`）。

**前置：决策 4、5、6、10；其中决策 5 必须先写下来并评审通过，再动一行码。**
理由见决策 5 末段。

刀 4 独占一个发布。它关掉 `SEM-10`，并解开 `#208`（UI DSL）要的泛型 state trait。

## 5. 先例

**Effekt**：最近，且差距明显。Dawn 已经按名引用它的词法 handler 语义
（`effects-design.md:209`「这是 Effekt 的词法 handler 语义」），同样只有尾恢复，同样在调用点
传隐藏证据（`spec.md:1417`），同样没有行多态（`effects-design.md:55` D4）。Effekt 的
`interface` 方法可以带效果参数，能力以隐藏实参在调用点传入；它对「谁给接口方法供能力」的
回答是**调用方，在调用点**，正是 `rc.dawn:528-538` 逼 Dawn 走的那一支。写语法与决策 5 之前
先读它。

**Koka**：全效果行多态。引它只为一件事：论证 Dawn 不做行多态。`effects-design.md:55` 的 D4
已经写下跨语言规律（有行多态才能把 handler 类型化成一等值）。

**Unison**：abilities 进行、推断、隐式，人体工学上最接近载荷一想要的东西，但同样依赖行。

**OCaml 5**：效果不进类型。它是「可以先发 handler 再谈效果类型」的先例，不是参数化的先例。

**Scala 3 capabilities**：能力是**值**加捕获追踪，多态走普通类型参数携带能力集。与 Dawn 的
两点基格 + 标签轴不同宗。

## 6. 落点清单

**spec**：§6.3（`docs/spec.md:1236`）加效果参数的绑定与作用域，并按决策 2 保留或收紧
`:1245`；§6.5 的边界表（`:1399-1401`）里「trait / impl 方法：方法的行是纯或 `!io`」随刀 4 改；
`:1417-1419` 的证据合成规则按决策 5 加第三条。`spec.en.md` 的 translation digest 同批重登记。

**grammar.ebnf**：`:45-46` 的 `type_params`、`:78` 的 `trait_decl`、`:83-86` 的
`trait_method` / `impl_decl`。

**effects-design.md**：§4.5 的 trait/impl 条（`:226-227`）与 §7 开放项 5（`:360-361`）；
§5.2 步 4（`:293-297`）按决策 5 改。

**审计**：`codebase-audit-v2/02-types-effects-and-semantics.md` 的 SEM-10 条，`:274` 的两处
锚点、`:276` 的「携带或捕获」二选一、`:282` 的成本混淆。

**门禁**：`scripts/checker-corpus/cases/trait_method_effects.dawn` 与同名 `.expected`
（今天 11 条诊断）、`scripts/grammar-corpus/` 的 accept/reject 对、`scripts/spike-native/` 的
差分语料，以及按本文第 4 节逐刀声明的 Emit-Change 标签。
