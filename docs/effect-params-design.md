# 效果参数（RX-10-B）设计

> 状态：proposed。基线 `cf725f4`（main）。本文定范围、结构落点与决策点。
> **刀 1 已落地（`cf725f4`）**；**决策 5 已裁（2026-08-19，A0 + A′）**，条文见下。
> RX-10 期权 A 的裁决见 [audit/re-audit-2026-07-30.md](audit/re-audit-2026-07-30.md)
> 第 593 行，B 的原始定义见 [audit/re-audit-b-decisions.md](audit/re-audit-b-decisions.md)
> 第 560 行起。
>
> 文内的 `file:line` 一律对 `cf725f4` 实测。刀 1 动过 `passes.dawn` 与 `checker.dawn`
> 的行号，旧稿里的引用已逐条重定位。

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
**它自己的 `Sig.eff`** 合成的（`bind_evidence` 读 `eff_labels(s.eff)`，`checker.dawn:8367`；
描述符同理，`emit.dawn:403-406`）。同一个 trait 里不提 `!e` 的纯方法，`Sig.eff` 仍是 `EPure`，
不多一个参数。所以纯兄弟方法不为这个参数付任何运行时代价。

三、字典是按 impl 建的，证据必须走调用点（决策 5）。trait 级的一行让「哪些槽位要证据」
成为 trait 声明的一个静态属性，接口描述符可以一致地推导；方法级则要在每个槽位单独携带
它自己的效果参数表。

`alias` / `type` 的参数表本来就要从 `List[String]` 加宽（决策 8 的刀里一起做）。

### 决策 5（枢纽，已裁 2026-08-19）：效果参数在单态调用点被实例化时，谁供证据

**裁决：A0 + A′。** A′ 是下面的**规则丙**：一个声明级效果参数恒定合成恰好一个隐藏证据
参数，在字典槽位边界上擦除，由 impl 侧的 bridge 适配回来，供给方永远是调用方、在调用点。
A0 是它的同批伴生件：**trait / impl 方法的行可以携带普通的每签名效果变量**，零证据、零
描述符变动。两者的关系是子集：A0 只放开「行里能不能出现效果变量」，A′ 才把效果变量提升成
trait 声明的参数并为它买单。

裁决的输入是 2026-08-19 的两份勘察（决策 5 备忘录与 #208 证伪探针，均在私有 handoff
目录，不入库）：备忘录给出候选表与规则丙条文，探针拿 12 个真跑的程序检验 A′ 的输出位读法
未被证伪、同时找出 A′ 覆盖不到而 A0 覆盖得到的那一族形状。

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

#### 三种情形，以及成本落在哪一种

- **情形 I（impl 侧具体）**：`impl Parser[Sub, !Ask]`。规则甲原样适用，零改动。
- **情形 II（调用点具体）**：见证是 `WConcrete`/`WApply`，label 集合在调用点静态已知。
- **情形 III（调用点刚性）**：`fn drive[C: Parser[S, !e]](c: C, …) !e`，见证是 `WForward`
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
  复制函数体的机制，`perceus-design.md:58` 写明字典传递加擦除正是为了不做它。
- **候选 C（证据向量）**：混合实例化（`!e2 := !(e | Ask)`）要在运行期合并重排，是唯一破掉
  「零新 Core 节点」承诺的候选；排序错一次就是 native 侧 n 格内存不安全。
- **候选 D（被调方 re-lookup）**：按定义不成立，impl 方法体的词法环境里没有调用方的 handler。
- **候选 E（证据进字典）**：上面三条理由封死。

#### A0：trait / impl 方法的行携带普通效果变量

规则丙买下的是 ABI，但它买不下 #208 最高频的那个形状。探针把 #198 最像 Compose 的原型核心
签名 `fn column(body: fn() -> Unit !e) -> Unit !Ui !e` 搬进 trait：

```dawn
trait Container[C, !e] { fn wrap(c: C, body: fn() -> Unit !e) -> Unit !Ui !e }
```

这里的 `!e` 是**调用者的**，同一个 `column` 一处传纯块、一处传 `!io` 块。A′ 下这是错的
形状（`!e` 由 impl 定死，「内容块能做什么」变成组件作者的决定），候选 A 也不解决（内容闭包
的参数类型必须写效果变量，写标签会被 `refuse_written_label` 顶回，`cx.dawn:579-588`）。

它要的东西比 A′ 便宜得多：

> **候选 A0**：允许 trait / impl 方法的行携带**普通的每签名效果变量**（`spec.md:1280` 的隐式
> 引入），标签仍禁。
>
> 代价：**零证据参数**（`evidence_args` 只遍历 `eff_labels(declared)`，只写变量的行 label 集
> 为空，规则乙原样覆盖）、零描述符加宽、`lower_trait_call` 丢弃 `evid` 无所谓（本来就没有）、
> 字典形状一字不动。唯一的真活是 trait/impl 效果变量对齐，见下面的问题四。

A0 是 A′ 的真子集，也是 #208 唯一有实测背书的诉求，单独就能把 `Container` / `column` 族
搬进 trait。刀法上它自成一刀，理由见 §4。

**措辞纪律**：刀 4 旧稿写「把两处拒绝收窄成『未绑定的效果变量』」。这句话在 A0 下会把
`Container` 重新挡回去，因为读者会把「绑定」读成「由 trait 参数表绑定」。正确说法是：
**`spec.md:1280` 的隐式引入在 trait 方法里算「已绑定」**，A0 删掉的是四条拒绝里针对**效果
变量**的那一半，保留针对**具名标签**的那一半。

#### 5a 简化、5b 作废、决策 6 微调

- **5a 整段简化。** 不需要来源追踪。落法是让 `evidence_args`（调用点在 `checker.dawn:5883`）
  对**先代换过效果实参**的行调用，`instantiated_labels`（`:5895`）同批代换。两处一行的改动。
- **5b 整段作废。** 规则丙按效果参数绑定隐藏局部，就是 `bind_evidence`
  （`checker.dawn:8365-8375`）的镜像循环，读 `Sig.eparams` 而不是 `eff_labels`，二十行量级。
  旧稿说的「证据多态」重量来自「元数随实例化变」，而规则丙把元数钉成 1。
- **决策 6 微调。** 正确说法是「效果参数不参与 lub 累积，但在见证求解时被代换」。

#### 四个机制问题（正式条文要答，**待终审**）

四条都在实写探针时浮出，规则丙本身不依赖它们的答案，但落刀前每一条都要有一句话的定论。
下面是提案，各带最强反驳。

**问题一（待终审）：bound 里的效果实参按相等还是按包含匹配？翻转点在哪？**

*提案*：**按包含**，方向是「impl 投影出的效果实参 ⊑ bound 写出的那个」，也就是 bound 写的
是上界。理由是这条判据全语言已经有了：`eff_subsumes`（`types.dawn:210-217`）就是它，
`unify_eff` 的 `EPure`/`EIo` 两臂（`checker.dawn:695-696`）已经把基轴交给它，trait/impl
一致性检查（`passes.dawn:1787`）用的也是它。改成相等会逼每个 impl 声明最大行，那正是审计说
的「被迫退回 `!io`」。元数不受影响：格数只看 trait 声明，impl 的行更小也不会少一格，调用方
交占位值。

*翻转点*：不是一个时刻，是一次查表。`unify_eff` 的 `EffVar` 臂（`checker.dawn:697-703`）
今天无条件累积 lub，那是给**被调方的待解变量**用的；一个已被外层声明绑定的效果变量必须
不被推断进。判据取类型轴现成的那条：`is_concrete`（`checker.dawn:718-728`）问「它在不在
`cx.current_tparams` 里」，效果侧对应的问法是「它的 id 在不在外层签名的 `eparams` 里」。
刀 1 之后这张表已经就位且恰好正确：`enter_fn`（`checker.dawn:8316-8324`）就是从 `s.eparams`
重建 `current_eff_vars` 的。所以决策 6 的落地物「效果侧的 `is_concrete`」与本问题的翻转点
是同一件东西。

*最强反驳*：在输出位上做包含检查读起来是反的。若效果实参由 impl 唯一确定，bound 写的
`View[!Ui]` 就不是需求而是模式，接受一个纯 impl 意味着消费者自己的行被高估。高估永远安全，
但它意味着「投影出唯一答案」与「bound 只是上界」是两件事，日后要把效果实参当关联效果读回来
时，两个行不同的 impl 会同时满足同一个 bound，读回来的是哪个必须另有规定。**回应**：投影读
的是 impl 的实际行（一致性保证每个 subject 唯一），bound 是检查不是定义，两者可以并存，但
这条并存关系要写进 spec，否则第一个写关联效果的人会踩。

**问题二（待终审）：impl 在哪里写效果实参？两条方法行不一致时投影什么？**

*提案*：**不写，从方法行投影**；v1 不给 impl 头开效果实参位。理由在语法与寻址两侧：impl 的
主体位产生式是 `impl TYPEIDENT "[" type_expr "]"`（`grammar.ebnf:85`），而主体形状条
（`spec.md:603-608`）同时决定「哪个 impl 匹配」「两个 impl 是否重叠」「递归求解是否终止」
三件事，往括号里塞一个效果实参要同批改这条，以及 `impl_at`（`types.dawn:1202-1206`）与
`impl_for`（`lower.dawn:986-990`）的寻址。投影一样都不需要：impl 方法的行本来就解析好了存在
`msig.eff` 里（今天被 `passes.dawn:1741` 钉成 `EPure`/`EIo`，刀 4 换成真的 `resolve_eff_at`），
而一致性检查（`passes.dawn:1787`）已经在读它。

*两条方法行不一致时*：投影是**并**，取值范围限于 trait 声明里提到该参数的那些方法。这不是
错误，和「一个 trait 一个纯方法一个 `!Http` 方法」是同一种情况，消费者看到的是 join。v1
边界（一个效果参数至多一个标签）在这里变成一条真正的错误：若并出来是两个标签（`!Http` 与
`!Log`），报在 impl 上，诊断要点名是哪两条方法行。

*最强反驳*：投影让 impl 的对外形状变成隐式。给某个方法体加一个标签，会静默加宽这个 impl 的
每个消费者看到的东西，而 impl 头上没有任何 diff。显式槽位则是声明且被检查的。**回应**：一致
性检查可以把投影结果渲染进诊断，把隐式变成看得见的；而显式槽位是纯加法语法，日后要加就是
「检查写出来的等于投影出来的」，不必现在付语法与寻址的账。

**问题三（待终审）：一格擦除证据怎么装多标签的行？打包形状与顺序的规范位在哪？**

*提案*：**v1 不定义打包形状**。v1 边界把一个效果参数钉成至多一个标签，所以这一格的值恒是
恰好一个证据记录或占位值，多标签的情形不存在。这不是回避：`CFun.evs`（`core.dawn:255-261`）
是一列扁平 `CParam`，任何打包都要一个 Core 级的构造物，而那正是候选 C 触礁的地方。

*v2 真要开时的规范位是 lowering，不是后端*：合成一个普通记录类型（字段按效果 id 升序，
与 `bind_evidence`、`ev_sym_list`、`sig_desc_with_dicts` 共用同一条排序纪律，
`checker.dawn:8365-8375`、`:8377-8387`、`emit.dawn:394-407`），两个后端把它当普通 ADT 看。
两边不会各自约定，是因为它们根本不知道有过打包这回事。位置性元组不行：那要求两个后端对
「第 i 格是什么」达成一致，正是要避免的。

*最强反驳*：推迟意味着 v1 边界在承重。若日后放开，已编译出来的描述符还能用，唯一的原因是
这一格从第一天起就是擦除的。这是支持 A′ 擦除的论据，不是反对推迟的。真正的风险是人体工学：
消费者想让 `!e` 站「调用者的整条行」时，「写两个参数」的 Effekt 形状读起来很别扭。**回应**：
那个消费者要的是行多态，D4（`effects-design.md:56`）已经裁掉。

**问题四（待终审）：trait / impl 的效果变量怎么对齐？**

*提案*：**先代换后比较，比较点不动。** 比较点是 `passes.dawn:1787` 的
`eff_subsumes(msv.sig.eff, eff)`（备忘录与探针记的 `:1764` 是刀 1 之前的行号）。
`eff_subsumes`（`types.dawn:210-217`）把基轴交给 `base_subsumes`（`types.dawn:181-204`），
后者对 `EffVar` 只认 id 相等（`outer == inner`，或 `union_has(ovs, id)`），而 trait 的 `!e`
与 impl 的 `!e` 是两次独立的 `fresh_effvar` 铸造（铸造臂在 `cx.dawn:452-463`），所以永远不
相等。今天不触发，只因为两侧的 `eff` 恒是 `EPure`/`EIo`。

修法是类型轴在**同一处**已经做过的那件事的效果轴镜像：`want` / `want_ret`
（`passes.dawn:1778-1780`）先把 trait 的 tparams 经 `inst` 代换再比类型，行也照此处理。
刀 1 让这件事变便宜且完备：两侧的变量现在都在 `Sig.eparams` 里、按铸造序排（`types.dawn:1024`，
序的契约写在 `:71-90`），所以代换表就是 `msv.sig.eparams` 与 `msig.eparams` 的按位 zip，
而 `subst_eff`（`types.dawn:964-988`）的键正是 id，与 zip 产出的键同型。方向取「把 trait 的
变量代换成 impl 的」，然后 `eff_subsumes(subst_eff(msv.sig.eff, em), eff)`。长度不等就报错
并点名（impl 把 trait 的一个变量拆成两个，是这条的唯一触发方式）。

*最强反驳*：按位 zip 把两侧绑在**铸造序**上，而铸造序是解析器的产物，源码上看不见。读者
并排看 trait 与 impl 时无法看出配对关系；按名字配（`!e` 对 `!e`）则是看得见的。**回应**：
按名字配会强迫 impl 作者抄 trait 的拼写，而别的轴都不这么要求（impl 方法根本没有类型参数
表，`grammar.ebnf:85-86`，trait 的 tparam 一直是按位经 `inst` 代换的）。而且铸造序在刀 1
之后不再是产物：它是文档化并被 `passes.dawn:2195` 钉住的契约。所以取按位，长度不等的拒绝
就是它的安全网。

#### 随刀落的文档改动（拟稿，与刀一起提交）

以下四处逐字目标已核对到 `cf725f4`，条文随对应的刀落地，不提前改。

1. **`docs/spec.md:1453-1454`（规则乙）** 改成：经**签名内引入的**效果变量流进来的标签不合成
   参数，那种情况下证据在闭包的捕获里，所以高阶库函数（`list.map` 之流）零改动。**声明级
   效果参数不在此列**：它为函数追加恰好一个隐藏证据参数，排在写出来的标签之后，在字典槽位
   边界上擦除。字典槽位不是闭包，没有捕获可依赖，所以证据由调用方在调用点交出。
2. **`docs/spec.md:1436`**（「trait / impl 方法：方法的行是纯或 `!io`」，在 §6.5 的
   「边界（v1）」小节，该小节起于 `:1432`）随 A0 那一刀改写成「方法的行可以带效果变量，
   不能带具名标签」，随 A′ 那一刀再放开标签。
3. **`docs/spec.md:1280`（§6.3）** 按决策 2 加一句：签名自带显式绑定者时，该名字在这条签名内
   只解析到它。
4. **`docs/spec.md` §6.5 的边界表新增一条**：**「效果多态代码能转发、不能结算」**。理由是
   `with handle E` 在语法上就点名一个具体效果（`grammar.ebnf:102-103`、`spec.md:1399-1402`），
   所以 handler 安装点永远是单态的；`pub fn main` 的 labels 必须为空
   （`effects-design.md:175-177`、`passes.dawn:2301-2307`）是同一堵墙的另一面。

另有两处随刀 4 改的旧稿，目标已重定位、条文等刀：`effects-design.md:309-313`（§5.2 步 4）的
「只按字面写出的 labels 合成」要改成「按字面写出的 labels，外加每个被提到的声明级效果参数
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

`instantiate_eff`（`checker.dawn:5941-5948`）把未绑定的效果变量默认成 `EPure`，注释在
`:5793`（「an unbound effect variable means pure」）。让 `Mapper[Int, String]` 报元数错误会与
这条默认冲突，也会让效果参数比类型参数更啰嗦。

一个真实缺口要一并记下：类型引用今天**没有**效果实参的语法位，`TNamed`/`TQual` 的实参只是
`List[TypeRef]`（`selfhost/src/front/ast.dawn`）。所以「显式给效果实参」这件事本身需要新语法。
推荐第一批不做，只支持省略（推断），显式实参等出现无法推断的消费者再开。

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

**为什么单独成一刀（提案，待终审）。** 三条：

1. **前置不同。** A0 的前置只有决策 5 的问题四（trait/impl 效果变量对齐）；A′ 还要决策 4 的
   trait 参数表语法和问题一到问题三的终审。绑在一起，A0 要陪着等三个未定的问题。
2. **代价不同，验收也不同。** A0 零证据参数、零描述符加宽、零 Core 变动，`dict_key` 一字不动；
   刀 5 的验收清单整个是描述符对称性（JVM 四处、C 一处，见下）。混成一刀会让「描述符一处没漏」
   这条验收失去干净的对照组。
3. **它自己就站得住**，与刀 1 同款判词：trait 方法的行今天被烘死成两值（`eff_show2`），这是
   缺陷不是特性。而且它是 #208 唯一有实测背书的诉求（决策 5 的 A0 一节）。

**反驳与回应**：四条拒绝会被动两次（A0 把「拒一切」改成「只拒标签」，刀 5 再把「只拒标签」
改成「按 trait 参数表放行」），`trait_method_effects.expected` 也要重录两次。回应是这恰好
让每一次移动都读得懂：A0 那次消失的正好是四条效果变量诊断，两条具名标签诊断一条不动。

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
这种东西。

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

### 刀 5（A′）：trait 参数表、写出来的标签，与规则丙

给 trait 一张参数表（决策 4）；按规则丙落第三条证据规则；把 `lower_trait_call`
（`lower.dawn:2256-2347`）今天丢弃的 `evid` 接上（它绑在 `:2793` 的 `XCallFn` 模式里，
`:2795` 转 trait 路径时不传；函数内**六**个发射点 `:2287`（`prim_relation`）、`:2296`、
`:2314`、`:2321`、`:2333`、`:2342` 一律只发 `vs` 或 `vs ++ ds`，从不发证据）；bridge 的
`evs: []`（`lower.dawn:1183`）要真的填。

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
对，以及 `trait_method_effects` 的第二次重写（`trait methods cannot declare the effect`
与 `impl methods cannot declare the effect` 两条随本刀消失；两条
`a function type cannot name the effect` 不在本文范围内，那是 #188 的第五条拒绝，留着）。
**种子：零**，除非 `selfhost/src` 或 `std` 自己开始写 trait 方法效果行。
Core 无新节点：`CDictDef`（`core.dawn:285-295`）在调用点路线下不加字段，`CFun.evs`
（`:261`）与 coredump 的 `ev` 参数（`coredump.dawn:161`、`:430`）现成；Core golden 是重录，
从不声明（`scripts/emit-labels.txt:15-17`）。

**前置：刀 4；决策 4、6、9、10；决策 5 的问题一、二、三终审。**

刀 4 与刀 5 各独占一个发布。

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

行号一律对 `cf725f4`。四条 spec 债的拟稿条文在决策 5 的「随刀落的文档改动」一节，这里只列位置。

**spec**：§6.3（`docs/spec.md:1271`）加效果参数的绑定与作用域，并按决策 2 在 `:1280` 加一句；
§6.5 的「边界（v1）」小节（`:1432-1446`）里「trait / impl 方法：方法的行是纯或 `!io`」那条
（`:1436`）随刀 4 与刀 5 分两次改，同一小节新增「效果多态代码能转发、不能结算」一条；
`:1452-1454` 的证据合成规则按规则丙加第三条。`spec.en.md` 的 translation digest 同批重登记。

**grammar.ebnf**：`:45-46` 的 `type_params`、`:78` 的 `trait_decl`、`:83-86` 的
`trait_method` / `impl_decl`。

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
