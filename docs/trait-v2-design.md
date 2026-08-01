# trait v2 最小切片：设计

> 状态：**historical** —— trait v2 八刀已全部落地；权威描述在 spec §7 与 `docs/trait.md`。
>
> 对应 [`native-backend-plan.md`](native-backend-plan.md) §11.4 的 S2.1。
> v1 的设计定稿在 [`trait.md`](trait.md)，S1 的在
> [`semantics-closure-design.md`](semantics-closure-design.md)。
> 横向调研(其他语言怎么处理相等)在 [`equality-survey.md`](equality-survey.md)。
>
> **读法**:§1 是拍下来的四条方向,§2 是动手前的实测(它把「破坏性改动」这个
> 说法推翻了,并纠正了我记错的两个数),§3 是设计,§3.12 是刀法。
>
> 一条贯穿全文的观察:§3 里原本列的七个难题,**有三个是同一个决定的推论**
> ——把主体形状收到 Haskell 98 的实例头(§3.2),匹配算法、一致性判定、
> 递归终止一起消失。

## 0. 为什么 S2.1 从「以后再说」变成「下一件事」

`impl_table: Map[(Int, Ty), ImplI]` 的键是**具体类型**,`impl_subject_ok`
(`checker.dawn:1917`)只放行具名非泛型 ADT 与 `Int`/`Float`/`Bool`/`String`,
`resolve_witness` 用 `map.get(cx.impl_table, (trait_id, t))` **精确查表**——
没有匹配、没有替换、没有递归求解。于是 `impl[T: Eq] Eq[List[T]]` 写不出来。

「凡语言表达不出来的地方都在编译器里打特判」的总根因就是这一条。今天欠着的账:

- S1 步 1 的 `struct_eq` 残留:编译器自身还有 **50 处,全是 `List[…]`**(§2.1.1)。
- `==` 接受含刚性类型变量的复合类型,而且**连 `Eq` bound 都不要求**
  (`fn f[T](x: Option[T], y: Option[T]) = x == y` 今天编得过)。实测全仓
  **没有一处这么写**(§2.1)——不是巧合,是这类函数今天写不出来。
- S1.4 的 `[T: Show]` bound:补 bound 会补到一半发现 `List[T]` 没有 impl 可写。
- `Iter`(S2.2)与 D2 的集合(S3)都以它为前置。

## 1. 已定的四条（2026-07-26）

### 决策 1 — 字典走**运行期参数化构造**，不走编译期单态化

今天字典是**单例**:JVM 一个类一个 `INSTANCE`,C 一个静态 `struct`(S1 步 3 刚把
两个后端都统一到这个形状上)。条件 impl 的字典要从别的字典构造出来——
`Eq[List[Int]]` 需要 `Eq[Int]`。

否掉的是「编译期单态化」:给每个具体实例化发一个自己的单例。它零新 Core 节点、
`dict_ref` 今天就按具体主体索引,但**主体含刚性类型变量时单态化不了**——
`fn f[T: Eq](x: Option[T], y: Option[T])` 要的 `Eq[Option[T]]` 得从**调用方传进来的**
`Eq[T]` 现搭,而调用方是谁在编译 `f` 时并不知道。

> **这条的理由我记错过一次。** 上一版写的是「D0 实测这类位置占 6%」——那个 6% 指的是
> **已实例化**的泛型(`Option[String]` 之类),不是刚性变量;刚性变量的实测是 **0**
> (§2.1)。数字错了但决定不变,**真正的理由是 Dawn 传字典而不单态化**(trait v1 的裁决,
> `trait.md` §5 把单态化列为「性能刀,需求出现再说」)。在字典传递下,条件 impl 的字典
> 天然依赖一个运行期才拿得到的字典,单态化解不开——除非连带推翻 v1 的字典传递决定。

代价是清楚的:新 Core 节点(字典从字典构造),两个后端各改一处;JVM 的字典从
「一个类一个 `INSTANCE`」变成运行期构造 + 缓存,热路径上多分配。

### 决策 2 — 主体形状收到 `F[T]` 与 `Map[K, V]`，元组不进

一元 `F[T]` 覆盖 `List[T]` / `Option[T]` / `Set[T]` / 用户泛型 ADT。
加二元是因为 **D2 早晚要给 `Map` 写 impl**,现在做省一轮;代价是替换、
一致性判定、递归解 bound 全部要处理多参。

元组不进:没有 head 名字、是 n 元的,`impl[A: Eq, B: Eq] Eq[(A, B)]` 要按元数
铸一族;而元组相等**已经被 S1 步 1 的展开器盖住了**,收益最小。

### 决策 3 — 条件 impl **写进 std 源码**，不由编译器合成

`List`/`Map`/元组是内建类型构造器,**没有声明模块**,而孤儿规则(spec §3.5)说
「impl 只能写在 trait 或主体类型的声明模块」。所以这条要求:**给内建类型构造器
认一个归属模块**(std),孤儿规则据此放行。

否掉的是「编译器合成、不进源码」——那是今天的形状(S1 步 1 的展开器就是),
孤儿规则不用改、不用发种子。选源码是选「语言表达得出来」这条更硬的标准:
std 里真写 `impl[T: Eq] Eq[List[T]]`,编译器里对应的合成机器删掉。

代价:**要走两次发布的种子舞**(见决策 4),而且孤儿规则的扩展要单独想清楚——
「std 拥有内建类型构造器」这句话得能挡住用户在自己模块里给 `List` 写 impl。

### 决策 4 — S2.1 与 S1.4 **各发各的**，不合并休眠期

两个都要「先发一版让种子学会、下一版才能用」(先例:StdStrings 的 Stage 2a/2b)。
选各发各的:每个改动有干净的种子边界,出事能二分。代价是多一轮发布开销。

顺序因此固定:**S2.1(2a → 发布 → 2b)→ S1.4(2a → 发布 → 2b)→ S1.5 → S1.1**。

### 决策 5 — `derive` 对泛型类型**解禁**，生成条件 impl

今天两个 derive 处理泛型的方式不一样,而且都在等条件 impl:

- `derive Ord` 直接报错(`checker.dawn:1968`),hint 自己写着「**v1** Ord subjects are
  non-generic」——v2 正是解它的地方。
- `derive Show` 在声明处放行(`is_showable_field` 对 `TyVar` 返回 `true`),**到用处才报**。
  实测 `type Box[T] = { v: T } derive Show` 编得过,`to_string(Box { v: (x: Int) => x + 1 })`
  才报「cannot print a value of type `Box[fn(Int) -> Int]`」。不是漏洞,但报错点离声明远。

解禁之后两者都变成声明处生成 `impl[T: Ord] Ord[Box[T]]` / `impl[T: Show] Show[Box[T]]`,
在声明处一次检清——与 §3.7 对 `==` 做的是同一件事,只是换了个 trait。

**落点分两处**(理由同决策 6):`derive Ord` 进 **2a**;`derive Show` 要等
`Show` 成为 trait,随 **S1.4**。

> **「纯加法」是错的(实测 2026-07-26,动手时)。** `derive Ord` 的**方法体根本不在
> Core 里**——`emit.dawn` 直接写 JVM 字节码(`gen_derived_ord_cmp` / `emit_field_cmp` /
> `cmp_fields`)。于是给泛型解禁需要那个方法体能收字典参数,而手写字节码收不了。
>
> 顺手量出一个**更大的洞**:C 后端对 `derive Ord` 发出一个**调用**
> `impl$0$Adt<n>$cmp` 却从不定义它——是未定义符号,不是 panic,**一句诊断都没有**。
> 而 `spike-native/` 里**没有任何语料用 `derive Ord`**(2026-07-26 实测),所以这个洞
> 一直不可见。先补语料钉住(`ord_derive`,提交 `33a587b`),再修。
>
> 修法就是 §3.6 对相等做过的那件事:**把这个关系降到 Core**(`cmp_at` /
> `struct_cmp_body`,与 `eq_at` 共用 `struct_rel_fn` 脚手架),两个后端各编一次同一份
> 定义。泛型解禁于是**白拿**——刀 4 的字典参数机制正好就是它要的。连带:
>
> - 新 Core 节点 `CTagOf`(「是哪个构造器」)。`CIsCtor` 只答「是不是这个」,
>   拿它拼出序要 O(n²) 次测试;JVM 是 instanceof 链(本来就有),C 读 `->tag`。
> - `CImpl` 的 `derived: Bool` **删掉**:derived impl 不再产生 impl 调用,那个位子
>   永远是 `false`——又一次「表已经知道答案」。
> - `emit.dawn` 净删 119 行手写字节码。

### 决策 6 — std 给容器写**四种**条件 impl，但 `Show` 那条落在 S1.4

决策 3 只说了 `Eq`(和 §3.10 配对的 `Hash`)。裁决扩到四种:`Eq`/`Hash`/`Ord`/`Show`,
一次补齐容器的能力,以后不用再回来。今天 `sort(List[List[Int]])` 编不过——
`prelude_impls()` 的 Ord 只有 `Int`/`Float`/`String` 三个标量。

**但 `Show` 那条今天一个字都写不出来**:`Show` 还不是 trait,是
`AdtI.derives_show` 标志位 + `is_showable`/`is_showable_field` 两个静态谓词 +
运行时 `dawn/rt/Show` 的 instanceof 链的合称,没有 `SHOW_ID`、没有字典(§6)。
这正是 S1.4 要做的事,而 S1.4 排在 S2.1 之后又是因为它要等条件 impl。

不是死锁,是顺序。**保序,不合并**:

| | 内容 | 落点 |
|---|---|---|
| `Eq`/`Hash`/`Ord` 的容器条件 impl | 刀 6 | S2.1 的 2b |
| `impl[T: Show] Show[List[T]]` 等 | S1.4 —— 它本来就是「给 std 补 `[T: Show]` bound」那一刀,顺手写这条正是它的活 | S1.4 的 2b |

> **实际只写了 `List` 的三条(2026-07-26)。`Map`/`Set` 推到 S3,理由是实测出来的。**
>
> 手写 `impl[K: Eq, V: Eq] Eq[Map[K, V]]` 的body 要在 b 里找 a 的键——而找键用的是
> `map_get`,走的是**运行时的哈希与相等**,不是 `Eq[K]` 字典。于是这条 impl 会**悄悄
> 混用两套相等**:值比较听 `Eq[V]` 的,键比较听运行时的。写成 O(n²) 的逐键 `eq(k, k')`
> 能避开,但那是拿正确性换正确性。
>
> 根因是容器的查找还不是 Dawn 的——**S3(集合纯 Dawn 化)之后,map 的查找 `就是` 那个
> 字典**,这条 impl 才写得对。所以 `Map`/`Set` 的 `Eq`/`Hash` 排进 S3,和元组(决策 7)
> 同一批。`Ord[Map]`/`Ord[Set]` 则**永远不写**:哈希容器没有自然序,「一次补齐」不该
> 补一个编出来的序。
>
> **连带**:`uncomparable_part` 也删不掉。§3.6 说它会被「求解器解不出 `Eq[TyFn]`」
> 替代,而那要求**每个可比的类型都有 impl**;`Map`/`Set`/`Array` 还没有,结构默认这条
> 兜底就还得留着,函数值不可比也还得靠它说。同样推到 S3。

否掉合并(把 S1.4 的加法那半塞进 2a)的理由:那会让 2b 同时扛 trait v2 的语义变更
**和** Show 的字节码面(#24 原话「字节码面很大」),正是决策 4 想避开的不可二分。
**终态相同,两条路都不产生返工**——每条 impl 只写一次,没有谁要回头改。

### 决策 7 — 元组排进 S3，降级成 std 的 ADT

刀 6 之后 `List`/`Map`/`Set` 都有 std 的显式 impl,**元组成为唯一一个相等仍靠
编译器合成的类型**(决策 2 把它挡在 head 之外:没有 head 名字、是 n 元的)。

裁决:不承认这个特殊永久化,排进 **S3**。理由是两件事共用终点——S3 本来就是
「集合纯 Dawn 化」,元组是同一类残留;而 §3.9 的 `head_owner` 脚手架也要等 S3
(`List`/`Map`/`Set` 变成 std 的真 ADT)才删得掉。

先例见 [`equality-survey.md`](equality-survey.md) §3:选了「元组是 ADT」的 Scala/Kotlin
这个问题根本不存在;选了「元组保持结构类型」的 Swift,SE-0283 通过六年未能实现,
社区结论是「别用元组」。

## 2. 曾经开着的一条：`==` 要不要求 `Eq` bound

> 这一节保留了「开着」时的推理与实测过程,因为**结论是被数据改掉的**,
> 而过程比结论有用。落定在 §3.7。

决策 1 选了参数化构造,它的选项说明里写了「要让残留真死,
`==` 就得要求 `[T: Eq]` bound」——但那句话是**代价提示,不是决定**:

参数化构造给的是**能力**(刚性变量位置解得开),前提是那儿有字典可用。而
`fn f[T](x: Option[T], y: Option[T]) = x == y` **没有 bound**,所以没有 `Eq[T]`
可以构造。要它有,只能让 `==` 要求 bound——那是改 spec §3.5 与 §4.3
(「`==` 本来就对每个类型结构化,等于每个类型隐式实现 Eq;写 impl 是为了覆盖」),
是用户可见的破坏性改动,并且要一并推翻 D0「没有 derive Eq」的裁决。

所以两条路在决策 1 之下都还成立:

| | `==` 保持全域 | `==` 要求 bound |
|---|---|---|
| `struct_eq`/`struct_show` | **永久留着**,是「全域相等」的实现,不是缺口 | 真的删干净 |
| native 后端 | **必须带 RTTI**(见 §2.2) | 不必 |
| spec | 不动 | §3.5 改一条 bullet |
| 用户代码 | 不动 | 见 §2.1 —— **实测为零** |

### 2.1 实测:要补 bound 的地方有多少（2026-07-26）

方法同 D0:在 `resolve_eq_witness` 的「非标量 + 无 impl」那一臂插桩
(`unsafe_pure { errio.eprintln(..) }`,用 `cerr` 不行——诊断会中止编译),
对操作数类型收集刚性 `TyVar`,并查 `cx.dict_syms` 看它是否**已经**有 `Eq` bound。
`Cx` 的 `current_sig` 与 `src_path` 让每一条都能落到「哪个文件的哪个函数的哪个类型参数」。

| 语料 | 非标量 `==` 处 | 其中要补 bound |
|---|---|---|
| `selfhost`(编译器 34k 行 + std) | 612 | **0** |
| `backend-dawn`(生产博客后端) | 95 | **0** |
| `playground` | 42 | **0** |
| `packages/web` | 38 | **0** |
| `site` | 37 | **0** |
| `packages/json` | 4 | **0** |
| **合计** | **828** | **0** |

**覆盖面已验证**:612 与 D0 那次量的分布几乎完全吻合(2,047 处 `==` 中非标量约 30% ≈ 614),
说明探针确实走遍了 52 个模块。

**顺带纠正一个引错的数**:D0 记的「结构泛型 6%」指的是**已实例化**的泛型
(`Option[String]` 26 处、`List[String]` 24 处、`Option[Int]` 12 处…),
不是含刚性类型变量的。那些全是 ground,S1 步 1 的展开器已经盖住。真正含刚性变量的是 **0**。

**为什么是 0,比这个数字本身重要**:不是大家碰巧没这么写,是**写不出来**。
`==` 作用在裸 `T` 上今天就报错;而 `Option[T]`/`List[T]` 这条虽然编得过却没人走,
因为需要它的函数(`list.contains` / `dedup` / `index_of`)**在 std 里压根不存在**
——D0 那次也撞见了同一件事,当时记的是「预期最大的工作量为零」。

> 所以 bound **不是对现存代码的税,是对写不出来的代码的入场券**。条件 impl 落地后
> `list.contains` 才第一次能写,而 `[T: Eq]` 正是让它能写的东西。

同一次插桩也测了 `Show`(S1.4 已定「补 `[T: Show]` bound」)。四种写法**今天全是编译错误**:

```
to_string(x: T)          → cannot print a value of type T
to_string(x: Option[T])  → one of its type arguments is not printable
"${xs}"  xs: List[T]     → cannot interpolate a value of type List[T]
to_string(x: Box[T])     → 即使 Box 写了 derive Show 也被拒
```

`is_showable_field` 放行类型参数,只是让泛型 ADT 能**声明** `derive Show`
(于是 `Box[Int]` 能渲染);在泛型函数**里面**渲染一律拒绝。
所以 `[T: Show]` bound 是**净放宽**,不破坏任何现存代码。

三条诚实的边界:①这是「今天存在的 Dawn 代码」里的 0,不是「未来用户不会撞上」;
②**测不到编不过的代码**,语料分布本身被「今天什么写得出来」塑造过;
③`Ord` 没测,因为它已经是真 trait、已经要 bound,那条路没有变化。

### 2.1.1 顺带查清:那 50 处 `struct_eq` 残留是什么

S1 步 1 说「残留可数,编译器自身 50 处,这个数就是 S2.1 的进度条」。数对了,
但**当时没说清它们是什么**。逐一点出来:

| 操作数类型 | 站点数 |
|---|---|
| `List[Ty]` | 26 |
| `List[(Int, String)]` | 6 |
| `List[Expr]` | 5 |
| `List[String]` | 4 |
| `List[TypeRef]` | 3 |
| 其余(`List[Stmt]`/`List[MatchArm]`/`List[List[Int]]`/…) | 6 |
| **合计** | **50** |

**全部是 `List[…]`,一处刚性类型变量都没有。** 原因在 `eq_at` 的 `expandable_eq`
只认 `TyAdt` 与 `TyTuple`,`TyList`/`TyMap`/`TySet` 即使 ground 也落到 intrinsic。

两个推论:

- **`==` 要不要 bound,删不掉这 50 处里的任何一处**——它们都是 ground。
- 删它们的是**决策 3**(std 里写 `impl[T: Eq] Eq[List[T]]`),或者 S3 让
  `List`/`Map`/`Set` 变成真 ADT 之后自动落进展开器。所以这个进度条量的是
  **容器归位**,不是刚性变量收口。

### 2.2 另一侧的代价:保持全域要 native 带 RTTI

`dawn_adt` 今天是 `tag` + `nfields` + `dawn_slot` union —— **它不知道某个槽是 int64 还是指针**。
要在运行期结构性比较两个擦除指针,就得每个 ADT 一张字段种类表。

Perceus 确实会要一档运行期信息(擦除槽 drop 时要知道有几个字段是指针,Koka 的
`scan_fsize`),但**那一档只回答「要不要 drop」,不回答「这是什么」**,不够做结构相等。

而决定性的一条:运行期走结构**还必须尊重用户写的 `impl Eq[Money]`**,否则同一个类型
在具体位置走 impl、在泛型位置走结构遍历——又是「一个关系两个答案」。要尊重,ADT 描述符里
就得放一个 `eq` 函数指针,**那就是把字典藏进对象头**:同一份信息,每个对象多一个字长、
多一次间接、而且去虚化不了。Dawn 在 trait v1 已经选了字典传递,藏进对象是它的更贵版本。

方向上也不对:S1 每一步都在**减少**运行期分派(步 1 把 `==` 从 `Object.equals` 搬到编译期
合成函数,步 3 把字典类名从 checker 表搬到 Core 表,S1.4 要把 `Show` 从 instanceof 链搬到字典)。
保持全域会是第一次朝反方向走,且不可逆——所有 ADT 的表示就此定死。
另见 `trait.md` v1 范围表「不做 `dyn`/trait 对象」与 spec §1176「语言构造保证不产生反射」,
运行期结构遍历属于同一族。

### 2.3 结论

实测把「破坏性改动」这个说法推翻了:破坏面是 **0**,`Show` 那侧还是净放宽。
剩下真正要付的只有两条 —— **spec §3.5 改一条 bullet**,以及 **Float 怎么拆**
(独立问题,取决于要不要让 `Eq` 真有法则;见 [`equality-survey.md`](equality-survey.md) §2)。

**已在 §3.7 落定:`==` 要求 `Eq` bound。** 决定它的不止实测——§3.6 让运算符与
bound 两条管道并成同一个 `solve`,而并管道之后「`==` 不要 bound」就没有地方安放了。

## 3. 设计

> 这一节原本是「还欠的七项」清单。写下来之后发现**其中三项是同一个决定的推论**:
> 把主体形状收得够紧(§3.2),匹配算法、一致性判定、递归终止三个难题一起消失。
> 所以下面不按清单顺序排,按依赖排。

### 3.1 语法与 AST

```dawn
impl[T: Eq] Eq[List[T]] { fn eq(a: List[T], b: List[T]) -> Bool = ... }
impl[K: Eq + Hash, V: Eq] Eq[Map[K, V]] { ... }
```

`impl_decl`(`parser.dawn:738`)在 trait 名前插一次已有的 `type_params`
(`parser.dawn:356`,`fn` 用的就是它)。无歧义:`impl` 之后 `[` 是类型参数、
`TYPEIDENT` 是 trait 名。零新词法。

| 记录 | 加什么 |
|---|---|
| `DImpl` / `ImplView`(ast) | `tparams: List[TypeParamDecl]` |
| `ImplI`(types) | `tparams: List[Ty]`、`constraints: List[List[Int]]` —— **与 `Sig` 同形**,复用 `bounds_of` |

### 3.2 主体形状：head + 互不相同的类型变量

这是全节的支点。合法主体**只有两种**:

1. **具体主体**(今天的形状):具名非泛型 ADT、`Int`/`Float`/`Bool`/`String`。
2. **head 形状**:`H[a₁, …, aₙ]`,其中 `H` 是具名类型构造器
   (`TyAdt`、`List`、`Map`、`Set`),`aᵢ` 是**互不相同的类型变量**,
   且恰好是这个 impl 声明的那些。

```dawn
impl[T: Eq] Eq[List[T]]          # ✅
impl[K, V] Eq[Map[K, V]]         # ✅
impl[T] Eq[Box[T]]               # ✅ 用户泛型 ADT
impl Eq[List[Int]]               # ❌ 参数不是变量(为什么不放行:§3.4)
impl[T] Eq[List[List[T]]]        # ❌ 嵌套
impl[T] Eq[T]                    # ❌ head 是裸变量
impl[A, B] Eq[(A, B)]            # ❌ 元组(决策 2 已排除)
```

这就是 Haskell 98 的实例头限制。**它买到三样东西**,每一样单独看都是一个难题:

- **匹配退化成「head 相等 + 逐参绑定」**。查 `Eq[List[Int]]` → head 是 `List` →
  取那个 impl → `T := Int`。不需要写合一算法,不需要 occurs check。
- **一致性退化成 head 相等**(§3.4)。
- **递归求解**自动终止(§3.5)。

代价是失去 `impl Eq[List[Int]]` 这种特化。v1 本来就没有特化,而特化是 Rust 至今
没稳定的东西——不进最小切片。

### 3.3 索引：`impl_table` 改按 head

```dawn
pub type Head =
  | HAdt(id: Int) | HList | HMap | HSet
  | HInt | HFloat | HBool | HString | HBytes | HCursor

pub fn head_of(t: Ty) -> Option[Head]     # 非法主体 → None
```

`impl_table: Map[(Int, Ty), ImplI]` → `Map[(Int, Head), ImplI]`。

**查 `Tr[t]` 的算法**(替代今天 `resolve_witness` 的一次 `map.get`):

```
solve(tr, t, depth):
  t 是刚性 TyVar  → 查 dict_syms → WForward(sym) / 报错「add the bound」
  head_of(t) 无   → 报错(TyFn / TyArray / 元组…)
  查 impl_table[(tr, head_of(t))]:
    有 impl → 逐参绑定 σ = {impl.tparams[i] := t 的第 i 个实参}
              对 impl 的每条约束 c:  args ++= [solve(c.trait, σ(c.ty), depth+1)]
              → WApply(tr, t, args)
    没有   → 若 tr ∈ {Eq, Hash, Show} 且 head 是 ADT:
                **按需合成**一个结构 impl(§3.6),再走上面那支
              否则报错
```

### 3.4 一致性：每 (trait, head) 至多一个 impl

比「禁止重叠」更强,也更简单:**判定退化成 head 相等**,一行 `map.get`,
而且用的就是今天那条 duplicate impl 诊断(`checker.dawn:2043`)。

于是 `impl Eq[List[Int]]` 与 `impl[T: Eq] Eq[List[T]]` 不是「重叠」,是**重复**
——报的是同一条错。这也是 §3.2 排除具体参数的原因:允许它就必须回答
「哪个更特化」,那是特化,不是最小切片。

### 3.5 递归终止：由形状保证，不靠深度上限

impl 的约束只能落在**它自己的类型参数**上——这一条不是新规矩,是**表示自带的**:
`constraints: List[List[Int]]` 按类型参数下标索引(§3.1 复用 `Sig` 的形状),
根本没有地方写一条不在 tparams 上的约束。而 §3.2 又保证那些参数是主体的**直接实参**。
两条合起来,每个子目标的类型是父目标的**真子项**,项大小严格递减:

```
Eq[List[(Box[Int])]]  →  Eq[Box[Int]]  →  Eq[Int]  →  prelude,停
```

**不需要深度上限,不需要环检测**——它们是形状限制换来的。`depth` 参数只作为
断言性的兜底(超过一个大数就 panic「求解器没有按预期递减」),不是语义的一部分。

### 3.6 `WStructural` 消失：结构相等也是一个（隐式的）条件 impl

spec §3.5 写着「`==` 本来就对每个类型结构化,**等于每个类型隐式实现 Eq**」。
今天这句话由一个**独立的见证种类** `WStructural` 兑现;改成**真的按需合成一个
`ImplI`**,这句话就落到了它字面的意思上:

```
type Pair[A, B] = { l: A, r: B }
# 求 Eq[Pair[Int, T]] 时按需合成,等价于:
#   impl[A: Eq, B: Eq] Eq[Pair[A, B]]      (body 仍由 eq_at 展开器生成)
```

**连锁删除**:

| 删掉 | 为什么不再需要 |
|---|---|
| `WStructural`(tast.dawn:28) | 它变成 `WApply` 的一种 |
| `uncomparable_part`(S1 步 2 加的那道门) | 「函数值不能比」由**求解器解不出 `Eq[TyFn]`** 天然给出,而且报错措辞只剩一份 |
| `resolve_eq_witness`(`==` 的独立管道) | 第四臂改成调 `solve`,整个函数退化成 `resolve_witness` 的一次调用 |

**`WConcrete` 留着**:非泛型 impl 解出来仍是它,lowering 的去虚化路径(`lower_trait_call`
的 `WConcrete` 支)一行不改。`WApply` 只在**有参数要传**时出现——所以见证种类
从三个变成三个(`WForward`/`WConcrete`/`WApply`),不是四个。

> **动手时这一段收窄了(2026-07-26,提交 `a8410e1`)。** 上面把「删 `WStructural`」和
> 「引入 `WApply`」当成同一件事,读代码后发现不是:两个见证种类在 lowering 里**早就走
> 同一条路**(`witness_value` 两支都是 `dict_ref`),唯一分歧在 `primitive_witness`
> ——「这个调用要不要走 `prim_relation` 而不是方法体」。而那个问题**表里已经有答案**:
> impl 不提供方法又不是 derived ⇒ 没有任何地方有方法体;没有 impl ⇒ Eq/Hash 的结构默认。
>
> 于是 `WStructural` 直接消失,换来的是三份手写条件(见证种类 / `is_eq_scalar` /
> `is_ord_scalar`)合成一个查表——正是 S1 步 3「表是唯一真相」那条的延续。**零 Emit-Change**
> (五个未改语料逐字节一致)。
>
> `WApply` 挪到刀 4:它要等真有**非 ground 主体**(`Eq[Option[T]]`,T 刚性)才有活干,
> 而那条路今天走不到。提前引入是前设计,而且 `WApply` 不带 `CDictApply` 无法 lowering
> ——分两刀会在中间留一个编不过的状态。

设计文档决策 6 那句「`a == b` 与 `[T: Eq]` 实例化后调 `eq(a,b)` 应当发出同一个调用,
**这一点本身就该有断言**」——到这里才第一次写得出那个断言:两条路走的是同一个 `solve`。

> 隐式合成**只给 `Eq`/`Hash`/`Show`** 这三个「每个类型天然就有」的 trait。
> `Ord` 不给:它要么 `derive Ord` 要么手写,今天如此,不变。

### 3.7 `==` 正式落定：要求 bound

§2 的实测(破坏面 0)与 §2.2 的 RTTI 论证,加上 §3.6 让两条管道并成一条,
三者指向同一个决定。**落定:`==` 要求 `Eq` bound。**

实现面比听起来小:`solve` 的第一支(刚性 `TyVar` → 查 `dict_syms`)**今天就已经是
这个行为**(`resolve_eq_witness` 对裸 `TyVar` 就报「add the bound」)。变的是
含刚性变量的**复合**类型不再走 `no_wit()`,而是走 `solve` 递归下去。

spec 要改的是 §3.5 的一条 bullet:「编译器合成结构见证」→「由隐式条件 impl 提供;
主体含类型参数时要求该参数有对应 bound」。§4.3(`==` 对每个类型结构化)不动。

### 3.8 字典物化：ground 静态，非 ground 运行期

决策 1 说「运行期参数化构造」,但**不是所有字典都要**:

| 主体 | 物化 | 代价 |
|---|---|---|
| ground(`Eq[List[Int]]`) | **静态单例**——今天的形状,JVM 一个类、C 一个静态 struct | 零新开销 |
| 非 ground(`Eq[Option[T]]`,`T` 刚性) | 运行期构造 | 新 Core 节点 |

新节点:`CDictApply(key: String, args: List[CExpr], ty: Ty)`。JVM:字典类多一个
带参构造器,`CDictApply` 发 `NEW`/`DUP`/`INVOKESPECIAL`;C:`dawn_dict_new(n)` +
逐槽写入。

**缓存:先不做。** 理由是实测——今天全仓 0 处走非 ground 这条路(§2.1),
先要正确;等语料出现再用 `selfhost-bench.sh` 量。这条写进 §4 门禁。

**`interp` 必须同批**:`CDictRef` 今天返回一个占位的 `VDict`,`CDictApply` 要求
它携带真的槽表,否则 comptime 里穿过字典的调用就假了。这一半**必须在 2a**
——种子的 comptime 折叠器要先认识它(StdStrings 的教训)。

#### 3.8.1 动手记(2026-07-26,刀 4 落地)

三处与上面写的不一样,都是读代码/实测改的。

**(a) 多了一个 Core 节点 `CDictArg`,而且它是两个后端要求相反逼出来的。**
`CDictApply` 建好的字典,槽体怎么拿到它的实参?两条路:让槽多收几个字典参数,
或者让槽从**它本来就收着的那个 self 字典**里读回来。
- JVM 两条都行(转发方法多推几个字段,或者槽自己取字段);
- **C 不行**:`CMethod` 的调用点要在编译期拼出函数指针的类型转换,而调用点
  **不知道被调字典有几个实参**(`dv->nargs` 是运行期的)。

所以槽签名必须**保持一律「trait 方法参数 + self 字典」**,实参从 self 读回来
——`CDictArg(dict, owner, key, idx, ty)`。代价是 JVM 侧多一次 `CHECKCAST` +
`GETFIELD`;换来的是 `CMethod` 调用点、`sig_desc_with_dicts`、`gen_dict_class`
的转发部分**一行没改**。这条是「Core 不许提到目标」那条规矩的一次实际裁决:
两个后端要的东西相反时,选那个让**共享节点保持一种形状**的。

**(b) `interp` 不必同批,上面那句「否则就假了」是错的。** 实测:解释器在
`CMethod` 处就以 `no_traits` 拒绝——comptime 根本走不到穿过字典的调用。
所以 `CDictApply`/`CDictArg` 跟着 `CDictRef` 一起返回占位 `VDict`,是**拒绝**,
不是**假答案**。让 comptime 真的能穿字典是另一件事,不在 trait v2 范围内。

**(c) 没有独立的 `solve` 函数。** §3.3 那段伪码里,「刚性变量查 `dict_syms`」
「查表」两支 `resolve_witness` 本来就是;真正新增的是**子目标怎么求**——而子目标
恰恰**不能**用 `resolve_witness`:它报错、它写 `capture_witness`,两个都是副作用,
而一个失败的子目标必须**不留痕迹地回退**到旧见证(否则就成了 §3.7 的破坏性变更,
那是刀 7)。于是拆成一个纯探针 `probe_witness` + 成功后再补 `capture_wits`。

**保持加法的两道闸**:只对**能展开**的非 ground 主体(ADT/元组)发 `WApply`;
且**每个实参都已经能求解**才发。实测结果:HEAD 源码用改前/改后两版编译器编出的
**561 个 class 逐字节一致**,calc/traits/eqhash 三份 Core golden 也逐字节一致。

**已知的浪费(记在 #28 名下)**:字典按 `ty_key_inst` 命名,而 `TyVar` 的拼写带
它的 id,所以两个不同函数里的 `Option[T]` 会生成两份内容相同的字典。要合并得先
把自由变量规范化编号,而编号来自 `checker.next_id` 那个共享计数器。

### 3.9 孤儿规则：给 head 认一个归属模块

今天(`checker.dawn:2025`):`trait_local || subject_local`,而 `subject_local` 只认
`TyAdt` 且在本模块声明。内建构造器没有声明模块,所以要:

```dawn
fn head_owner(cx: Cx, h: Head) -> Option[String]
#   HAdt(id) → 该 ADT 的声明模块(今天就有)
#   HList / HMap / HSet → 指定的 std 模块
#   标量 → 声明 prelude trait 的那个 std 模块
```

规则变成 `trait_local || head_owner(h) == 当前模块`。用户模块自然被挡住
——`head_owner(HList)` 是 std,不等于用户模块。

> ~~**这是明知要删的脚手架。** S3 之后 `List`/`Map`/`Set` 是 std 里的真 ADT,
> `head_owner` 退化成只剩 `HAdt` 那一支。~~
>
> **2026-07-27 更正:它是答案,不是脚手架。** S3 没让三个容器变成 ADT——D2/D3 的关键
> 裁决恰恰是让它们继续做 `Ty` 变体,只换 `desc_of` 与路由,这才绕开了 `is_builtin_name`
> 的重定义禁令和种子兼容那堵墙。而且它比写下时更承重:让 std 自己的
> `impl[T: Eq] Eq[List[T]]` 不算孤儿的,正是这三行。

### 3.10 `Eq`/`Hash` 成对

今天按 `(tid, subject)` 配对检查。改成**按 head 配对**:
`impl[T: Eq] Eq[List[T]]` 要求存在 `Hash[List[…]]` 的 impl。

两条约束**不要求相同**:`impl[T: Eq] Eq[List[T]]` 配
`impl[T: Hash] Hash[List[T]]` 是对的——各自要各自的能力。

隐式合成(§3.6)天然成对:同一个合成器一次铸两个。

### 3.11 种子怎么切 2a / 2b

| | 内容 | 性质 |
|---|---|---|
| **2a** | §3.1 语法 + §3.3 head 索引 + `solve` + `WApply` + `CDictApply` + JVM/C/**interp** 三个消费者 + `derive Ord` 对泛型解禁(决策 5) | **全是加法**。std 不写条件 impl,`==` 仍走老路 |
| 发布 | v0.12.0 | 种子学会新语法与新 Core 节点 |
| **2b** | std 给容器写 `Eq`/`Hash`/`Ord` 条件 impl(决策 6,`Show` 那条留给 S1.4);`==` 改走 `solve`;删 `WStructural`/`uncomparable_part`/`resolve_eq_witness` | 破坏性语义变更集中在这里 |

这么切的理由:2a 不改任何现有程序的行为(新机制无人使用),**所以它的 Emit-Change
应当接近零**,一旦不是就说明搬错了;2b 的行为变更则全部集中、可二分。

> **这条线画早了一刀(实测 2026-07-26)。** 上表把「语法」放进 2a,而刀 1 的语法是
> **parse 得了、注册就报错**。等到 std 真要写 `impl[T: Eq] Eq[List[T]]` 时,v0.12.0
> 的种子在**检查 std** 这一步就拒了:
>
> ```
> panic: cannot load std from .../std: bundled std module `std/list`
>        does not check: conditional impls are not supported yet
> ```
>
> 种子纪律要的不是「认得这个形状」,是「**接受**这个形状」。于是条件 impl 的真注册
> (刀 7a)必须自己发一版,std 才写得下去。**发布变成三次**:
>
> | | 内容 | 版本 |
> |---|---|---|
> | 2a | 刀 1–5:新机制全部落地,无人使用 | v0.12.0 |
> | 2a′ | 刀 7a:条件 impl 真注册 + 方法带字典参数 | v0.13.0 |
> | 2b | 刀 7b:std 写 impl、`==` 走 solve;刀 8 收尾 | v0.14.0 |
>
> 教训可推广:**「种子要先学会」= 种子要能编译 HEAD 的 `selfhost/src` 和 `std/`**,
> 而不只是能解析它。凡是「先报错、以后再放行」的过渡实现,都要单独占一版。

### 3.12 刀法（每刀含测试，均可单独验）

1. **语法 + AST + `ImplI` 扩展**。解析得了,注册时报「条件 impl 尚未支持」。
   纯前端,零行为变化。
2. **`impl_table` 改按 head**。此时还没有条件 impl,所以**这刀必须零 Emit-Change**
   ——是纯重构,拿 Core golden 和 `__emit` 逐字节验。
3. **删掉 `WStructural`**。~~`solve` + `WApply` + 按需合成~~ —— **动手时收窄了**(见下)。
4. **`WApply` + `CDictApply` + `CDictArg` + 三个消费者**(JVM / C / interp)。**零 Emit-Change**(见 §3.8.1)。
5. **`derive Ord` 对泛型解禁**(决策 5)——实际是**把 derived Ord 降到 Core**,见决策 5 下的实测。**有 Emit-Change**(derived cmp 的字节码改从 Core 生成)。
6. 发布 **2a**。
7. **std 给容器写 `Eq`/`Hash`/`Ord` 条件 impl** + `==` 走 `solve` + 删三处旧机制。
   **破坏性、Emit-Change 大。**(`Show` 那条见决策 6,落在 S1.4。)
8. 收尾:spec §3.5 改 bullet、known-red 该删的删、`trait.md` v1 范围表标注。

> **刀 7 实际分成了三步**(2026-07-26),因为每一步都撞上「种子要先接受」:
>
> | | 内容 | 版本 |
> |---|---|---|
> | 7a | 条件 impl 真注册(§3.2 形状 + §3.9 孤儿规则)+ 方法带字典参数 + 三个调用点传字典 | v0.13.0 |
> | 7a′ | `==` 改走 `resolve_witness`(删 `resolve_eq_witness`)、`Eq`/`Hash` 按 head 配对、后端能给容器主体起名、std 的 impl 种进每个模块的表 | v0.14.0 |
> | 7b | std/list 写 `Eq`/`Hash`/`Ord` | 2b |
>
> 7a′ 里那条「std 的 impl 种进每个模块」是**实测发现的**:`ModExports.impls` 这个字段
> 存在、被填、**没有任何读者**——跨模块的 impl 从来没进过检查器的表。对 `Eq`/`Hash`
> 无所谓(结构默认兜底),对 `Ord` 就是「另一个模块看不见你的 `impl Ord`」。而容器的
> impl 更不能靠 `use`:一致性是全程序的,`a == b` 不该取决于这个模块写没写
> `use std/list`。于是 std 的 impl 与 prelude 的并列,种进每个模块的基表。
>
> **另一个实测坑**:主体 ground 但 impl 是条件的(`Eq[List[Int]]`)——它的字典**不带
> 参数**(子目标也 ground,是编译期常量),但槽体仍然**要把那些常量传给 impl**。
> 「字典带不带参数」和「槽要不要传字典」是两件事,合成一件就会发出一个少两个参数的
> 调用,而且只在**字典被当值传递**时才炸(devirtualise 的路径是对的)。site 的
> markdown 测试抓到了它。

## 4. 门禁

每步都要过:`dawn fmt --check`、四套测试(selfhost/site/web/playground)、
fixpoint `B == C`、`spike-native/run.sh`、`array-contract`、
`selfhost-core-diff.sh`、N vs N−1 四件差分(改字节码的必须带 `Emit-Change:`)。

两条额外的:

- **自举比值**(`scripts/selfhost-bench.sh`,今天 **1.0910**,基线 1.1151)。
  决策 1 在热路径上加分配,这是唯一能看见它的量。spread ≥ 15% 时这台机器
  分辨不了,别下结论。
- **`struct_eq` 计数**。今天编译器自身 50 处,**全是 `List[…]`**(§2.1.1)。
  它归零是**决策 3**(std 写出 `impl[T: Eq] Eq[List[T]]`)兑现的证据,不是决策 1 的
  ——决策 1 的证据要另找,见下。
- **决策 1 的验收物**:写一个「主体含刚性变量的 bound 转发」的语料
  (`fn f[T: Eq](x: Option[T], y: Option[T]) = x == y`),两个后端跑出同一个答案。
  今天全仓找不到这种代码(§2.1 的 0),所以**必须自己造一个**,否则参数化构造
  接没接上刚性变量那一半没有任何门看得见。这一条同时是 §3.8 非 ground 路径的
  唯一覆盖——那条路今天是死代码。
- **第 2 刀必须零 Emit-Change**(§3.12)。`impl_table` 改按 head 时还没有条件 impl,
  所以字节码不该动一个字节;动了就说明 head 索引改变了已有 impl 的解析结果。
- **每刀之间种子纪律不断**:N−1 的编译器要能编 HEAD 的 `selfhost/src`。1–4 刀
  不写条件 impl 就自动满足;第 6 刀靠 2a 已发布的种子。

## 5. 复盘（2026-07-26，八刀关账）

八刀落成十个提交、四个版本(v0.12.0–v0.15.0)。**设计文档说对的部分**:主体形状收成
Haskell 98 的 instance head 确实一条规则办三件事(匹配/重叠/终止),head 索引确实零
Emit-Change,ground 与非 ground 分开物化确实让绝大多数字典仍是编译期常量。

**没说对、被实测推翻的四条**,按被打脸的顺序:

1. **刀 3 大了,刀 4 也不是原来的形状**(§3.6 的引文)。`WStructural` 和 `WConcrete`
   在 lowering 里早就走同一条路;而「非 ground 那条路是死代码」是错的——它今天就能
   走到,JVM 上还答对,靠的是 `Object.equals` 递归时撞上被接管的 `equals`。真正坏的是
   native。
2. **`CDictArg` 是两个后端要求相反逼出来的**(§3.8.1a),设计里根本没有这个节点。
3. **决策 5 的「纯加法」是错的**(决策 5 下的引文):`derive Ord` 的方法体压根不在
   Core 里,而且 C 后端对它发出一个**从不定义的调用**——没有 panic、没有诊断,因为
   `spike-native/` 里一条 `derive Ord` 语料都没有。
4. **2a/2b 的线画早了一刀,而且画早了两次**(§3.11 的引文、§3.12 的引文)。种子纪律
   要的不是「认得这个形状」,是「**接受**这个形状」,还包括「能编译用了它的 std」。

**可推广的三条**:

- **「先报错、以后放行」的过渡实现要自己占一版。** 刀 1 让语法 parse 得了却注册报错,
  看起来是把风险切小了,实际是把种子挡在门外——std 要用这个形状,种子就得先接受它。
- **没有语料的能力等于没有守卫。** `derive Ord` 的洞不是新引入的,是一直都在;
  它可见的那一刻,是有人写了第一个用它的语料。补语料要**先于**修,这样修好之后
  known-red 少一行,而不是多一份没人读的正确性主张。
- **两件事合成一件,就会在第三种情形上炸。** 「字典带不带参数」和「槽要不要传字典」
  被当成同一个问题,于是「主体 ground 但 impl 是条件的」这第三种情形发出了一个少两个
  参数的调用——而且只在字典**被当值传递**时才炸,去虚化的路径一直是对的。抓到它的
  不是编译器的 169 个测试,是 site 的 markdown 测试。

**留给 S3 的**(都记在正文里,不是遗漏):`Map`/`Set` 的 `Eq`/`Hash`(要等容器查找
本身是 Dawn 的)、元组(没有 head)、`uncomparable_part` 与 `struct_eq` intrinsic
(要等每个可比类型都有 impl)、`head_owner` 这段过渡脚手架。

> **S3 的结账(2026-07-27)**,四条对三条:
>
> - `Map`/`Set` 的 `Eq`/`Hash`:D2 写进 std,如期。
> - `struct_eq`:**没有整体删掉,是换了个更小的契约留下**——收窄成 `java_eq`
>   「宿主值的相等」。理由不是做不到,是那件事本来就不是缺口:Dawn 不定义一个
>   Java 对象的相等,而 C 后端见不到 `TyJava`,所以 native 反而是净减一项。
> - `uncomparable_part`:**删不掉,但性质变了**。它早已不是「第二道门」(刀 7 把它
>   放进了 `resolve_witness`),留下来是因为元组没有 head、结构默认得有人兜底。
>   改的是它只问 `Eq` 表这件事——`[T: Hash]` 因此收了 `Float`。
> - `head_owner`:**前提未兑现**,见 §3.9 的更正块。
>
> 顺带清掉的一件不在这张单子上:`invalid_key_part`。它和 `uncomparable_part` 同形,
> 但删得掉——键合法性现在就是 `[K: Eq + Hash]` 这条 bound。详见
> [`semantics-closure-design.md`](semantics-closure-design.md) §10。

## 6. `Iter` 的第二个前置：关联类型（2026-07-27 勘察）

S2.1 关账时，四份文档（`native-backend-plan.md` §4/§6/§9.1/§11.4、
`collections-dejava-research.md` §5、`runtime-intrinsics-design.md` §7、本文 §0）
都把 `Iter` 记成「trait v2 之后的下一步」。**trait v2 有了，`Iter` 仍然写不出来**——
它还有第二个前置，四份文档一处都没有识别。

### 6.1 元素类型没有名字

`TraitI` 只有**一个** subject 类型参数（`tvar: Ty`）。于是：

```dawn
trait Iter[C] {
  fn iter_start(c: C) -> IterState
  fn iter_done(c: C, k: IterState) -> Bool
  fn iter_next(c: C, k: IterState) -> IterState
  fn iter_get(c: C, k: IterState) -> ???   # ← 元素类型无处可写
}
```

走查过的四条出路，全都撞同一堵墙：

| 出路 | 为什么不行 |
|---|---|
| 方法自带类型参数 `fn iter_get[E](...) -> E` | **编译器显式禁止**：`error: trait methods cannot declare their own type parameters`（实测）。就算放开，impl 也无法把自己的 `T` 交给一个自由的 `E` |
| 高阶主体 `trait Iter[C[_]]` | 高阶类型参数，比关联类型更大 |
| 双参数 trait `Iter[C, E]` | 多参数 trait：一致性键、impl head、孤儿规则全要重做 |
| 回调式 `trait Each[C] { fn each(c: C, f: fn(?) -> Unit) }` | 形参位置换了个地方，问题不变 |

所以 **`Iter` 的完整前置是「trait v2 + 关联类型」**，后者的规模与 trait v2 同量级
（语法、`TraitI.assoc`、impl 侧 `type Item = T`、投影类型 `TyAssoc` 及其归约），
不是一刀能收的东西。

### 6.2 而且它在 S3 之前无法验证

更要紧的一条：**今天把 `for` 改掉是无法证伪的**。`for x in xs` 现在降成
`len` + `list_index`，而 `list_index` 落在 `DawnList`（共享数组窗口）上是 **O(1)**——
随机索引慢 8–18× 是 **D3 把 List 换成 RRB 之后**才出现的事（§9.3 实测）。
所以现在换掉下标循环，既没有语料能证明它更快，也没有语料能证明它没写错：
唯一的 oracle 要等 D3 才存在。

### 6.3 结论：重排，不是砍掉

`Iter` 仍然是 D3 的正确性前提——这条没变。变的是它的位置：

- **不在 S2 做**。S2 里它缺前置（关联类型）且缺 oracle（RRB）。
- **关联类型独立成项**（S2.5），按 trait v2 同样的纪律走：设计定稿 → 分刀 →
  每刀自己一版种子。它的收益不止 `Iter`：`Eq`/`Hash` 的 key 类型、`Show` 的
  writer 类型都在等同一个东西。
- **`Iter` 并进 S3 的第一刀**，和 RRB 一起落地、一起被同一份语料证伪。

把「Iter 是 D2 的附带项」写进计划的那次，代价是没识别出 trait v2；这次的教训一样，
只是往前挪了一层：**一个 trait 写不写得出来，取决于它的方法签名能不能被声明，
而不只是它的主体能不能被索引。**

## 7. 关联类型动手前的实测（2026-07-27）：前置本身是假的

§6 把 `Iter` 挪到 S3、把关联类型独立成一项。动手前按 trait v2 §2 的规矩先实测，
**实测把 §6 自己的一半推翻了**：关联类型今天在树内一个消费者都没有，而 `Iter`
也不是 S3 的前置。

### 7.1 「收益不止 `Iter`」是两条没核对的推断

| §6.3 的说法 | 核对结果 |
|---|---|
| `Eq`/`Hash` 的 key 类型在等它 | **撤回**。两个 trait 都是 `fn f(x: T) -> …`，只有主体一个类型；`Map[K, V]` 要的 `K: Eq + Hash` 是 bound，trait v2 已经给了 |
| `Show` 的 writer 类型在等它 | **撤回**。今天 `fn show(x: T) -> String`，没有第二个类型；「改成 writer」是一个还没人提的设计，不是欠着的账 |

于是关联类型的消费者只剩 `Iter` 一个。下一条把这个也拿掉了。

### 7.2 `for` 要脱掉下标，不需要 trait

`lower_for_list`(`lower.dawn:2485`)把 `for x in xs` 降成 `len` + `list_index`，
它自己的注释写着「D2/D3 之后这里变成 `Iter` trait 的调用」；§11.3 据此把 `Iter`
记成 D3 的正确性前提（RB 树随机索引慢 8–18×）。

**「不按下标降」和「按 trait 降」是两件事，这里被合成了一件。** 实测两条：

- `for..in` 今天只迭代**一种**类型：`checker.dawn:5733` 的 `TyList(el) -> el`，
  其余一律报错；Map/Set 要先 `map.entries` / `set.to_list` 转成 List。
  **`for` 处没有多态可言**，所以也没有 trait 要抽象的东西。
- 降成具名调用的材料 lowering 早就齐了：`LSt.prog_fns`(`lower.dawn:94`)是
  `(owner, name) → Sig` 的全表，`CCall(CDirect(owner, name), …)` 就是直接调用的
  形式，合成的 `eq`/`cmp`/`show` 已经这么发(`lower.dawn:983 / 1199 / 1351`)。

所以 S3 里 `lower_for_list` 把两个 intrinsic 换成对 `std/list` 的四个具名调用
(`iter_start` / `iter_done` / `iter_next` / `iter_get`)，下标就没了、后端 intrinsic
也没了，而**编译器里的 arm 数量不变（还是一条 `TyList`），语言一个字都不用加**。

`Iter` 作为 trait 买到的是另一件事:**让 `for` 迭代 List 以外的东西**
(Map/Set/String/用户容器)。那是功能决定，今天树内没有一处在等它。

### 7.3 `for` 的改法有 oracle，`Iter` 没有

§6.2 的「没有语料能证明它没写错」说过头了：selfhost/src 与 std 里有 **871** 个
`for x in xs`，改完还能 fixpoint(B == C)是很强的正确性证据。真正缺 oracle 的
只有「更快」那一半，那要等 RRB——而这一半对具名调用和对 trait 是同一件事。

### 7.4 结论

- **`Iter` 与关联类型一起从 S3 的关键路径撤下。** S3 的 `for` 改造是 lowering 的
  一处局部改动。
- **关联类型仍值得做，但理由换成它自己的**：它是**运算符 trait** 的前置——
  `index_wanted`(`checker.dawn:3293`)今天硬编码 List/Map 两条 arm，用户类型不能
  支持 `xs[i]`；`for` 同理。这是**表达力**项目，不是纯洁性欠账，按它自己的收益
  排期，不再挂在 S3 前面。

动手时用得上的两个数，实测已经留下：

- 往 `Ty` 插 `TyAssoc(trait_id, subject, name)` 探针，穷尽性报 **10 处**，
  与 `TyOpaque` 同一批落点(`ty_show`/`subst`/`core`/`desc_of`/`jvm_repr`/
  `hash_of`/`emit_unerase`/`unerase`/`subst_tvar`/`c_repr`)。
- 种子(v0.19.0)两侧语法都不认：trait 体里的 `type Item` 与 impl 体里的
  `type Item = Int` 都是 parse error。所以第一刀仍要自己占一版。

> 连着两次的教训是同一个形状，只是层级不同：上一次是「没识别出 `Iter` 的前置」，
> 这一次是「**没核对 `Iter` 本身是不是前置**」。计划里一个待办被别的待办引用得越多，
> 越没人回头验它——`Iter` 被四份文档引用，四份都是转述同一句话。

## 8. `Cursor` 迁到 `opaque type`（v0.20.0–v0.24.0，五版）

S2.3 立起了 `opaque type`，但没迁走它的两个动机——`Cursor` 是编译器铸造的不透明标量，
`Array` 靠 `is_std_module` 做名字门控。这一节记 `Cursor` 那一半，以及它为什么花了五版。

**删掉的东西**：`Ty` 的 `TyCursor` 变体、`Head` 的 `HCursor`、`eq_scalars`/`hash_scalars`
里各一行、七个文件里 37 处引用、`builtin_type_names` 里一个名字。换来 `std/cursor` 的
一行 `pub opaque type Cursor = Int` + 一个 `impl Ord[Cursor]`。

顺带修掉一处 §11.3 点过名的自相矛盾：`a < b` 编得过而 `list.sort` 报 Cursor 无序，
因为回答这两个问题的是**两张表**；现在一个 impl 回答两个。

### 8.1 为什么是五版：种子挡的不是语法，是**每一条 std 依赖的规则**

|版本|这一刀|被谁逼出来|
|---|---|---|
|v0.20.0|删 `TyCursor`；`Cursor` 暂时是 `Int` 的拼写；名字不再算冲突|种子占着 `Cursor` 这个名字，**一个名字没法在同一版里既释放又重新占用**|
|v0.21.0|`unify_into` 认不透明转换|转换只写在 `assignable` 里，而**调用路径是 unify 的**，不问 `assignable`|
|v0.22.0|类型变量**绑定**而非看穿|上一刀连类型变量一起看穿了：`Some(i)` 在 `Id` 上推成 `Option[Int]`|
|v0.23.0|同一模块可以既限定导入又选择性导入|std 导出**类型**是头一回：`use std/cursor` 只带函数，类型要 `use std/cursor.{Cursor}`，而两者算重复导入|
|v0.24.0|std 声明 `pub opaque type Cursor = Int`，编译器不再铸造|—|

中间三版每一版都是同一句话的实例：**std 用到的每一条规则都得先在种子里**。
「刀 1 让语法 parse 得了却注册报错，实际是把种子挡在门外」（§5）说的是语法；
这次说的是**语义规则**，代价一样。

### 8.2 三个 bug，都是同一种没覆盖

- `emit_return_of` 按 `t == TyInt` 分派，落不到的类型发 void return——trait 方法返回
  不透明标量时，字典转发方法在**类加载时** `VerifyError`。与 `emit_method_return`
  同形，S0.3 转过一个、漏了这个。
- 转换只在 `assignable` 里，调用路径 unify，于是 `f(p)` 被拒而 `let n: Int = p` 通过。
- 修上一条时连类型变量一起看穿，`Some(i)` 推成 `Option[Int]`——**看穿一个类型不等于忘掉它**。

三个都是「语料只覆盖了一种位置」：`opaque.dawn` 原来只有 return 和 `let`。
补的语料现在把每个位置都走一遍（实参、类型变量绑定、字典转发、Option 往返、
泛型函数），列表位置进了 checker 测试（emitc 还没有集合）。

> **可推广的一条**：一个「一行就够」的规则（`sees_through`）不等于**一处就够**。
> 它被三个地方问：`assignable`、`unify_into`、`check_expr` 的期望类型。
> 只在一处实现，另外两处就各自默认了一个答案——一个拒绝，一个多做。

### 8.3 `Array` 不跟着迁（2026-07-27 实测推翻）

这里原先写着「`Array` 的 `is_std_module` 名字门控还在，随 S3 一起迁」。`Cursor` 一收工就去验，
**是错的**——和 §7 的关联类型同一天、同一个理由：一个待办被别的待办引用得越多，越没人回头验它。
这句话已经传到三份文档（本节、`spec.md` §2.7、`native-backend-plan.md` 的 S2.3 行）和一个任务里。

三条实测，每条都单独足以否掉它：

**一、没有目标类型可指。** `opaque type N = T` 要一个 `T`；`Cursor` 的是 `Int`，早就存在。
`Array` 没有——它**就是**表示：JVM 上是每份程序自带的 `dawn/rt/Array`（`codegen.dawn:1146-1427`
那 282 行），C 后端是 `ROpaque`。把 `List[T]` 当目标实测即死：

```
std 里 pub opaque type Arr[T] = List[T]，然后 array_len(a)
→ argument type mismatch: expected Array[T], got Arr
```

不透明只给身份、不给表示，所以连声明模块内部看穿后拿到的也是 `List[T]`，仍不是 `Array[T]`。
第三条路（把 `dawn/rt/Array` 当 java 类型）在 `types.dawn:853` 上撞死：`pub fn builtins()`
不收 `Cx`，却要在五个 `array_*` 签名里造 `TyArray(t)`——`Array` 因此不可能是「每次编译声明出来的」实体。

**二、方向相反。** 这是更根本的一条。`opaque type` **公开名字、隐藏表示**（用户能写
`var c: Cursor`，只是不能拆开看）；`Array` 的门控**隐藏名字、对 std 公开表示**。
把前者换成后者不是重构，是换成相反的策略。

**三、它不挡 S3。** S3 真正要的形状今天就能写——std 拿本机制给原语做门面，普通用户模块消费它：

```
std/vec.dawn:  pub opaque type Vec = Array[Int]   + array_* 包装
用户模块:      use std/vec.{Vec} → size=5 at3=7
               而 let n: Array[Int] = v → unknown type: Array
```

HAMT/RB 节点那半句是对的（节点是 ADT，是真目标），`Array` 那半句是错挂上去的。

**顺手修掉的一个真缺陷**：`Array` 没进 `pass_type_shells` 的重定义禁令
（`is_builtin_name` 只列 `ty_named` + List/Map/Set）。于是 std 里同名声明**静默走偏**——
`alias Array = List[Int]` 悄悄盖过原语并编译通过；`type Array[T] = Wrap(x: T)` 反过来输给原语，
声明成功而每次**使用**都解析到原语，报出

```
function `f` declares return type Array[Int] but its body is Array[Int]
```

两个不同类型印成同一行字。对照组 `type List[T]` 给的是干净的「builtin type and cannot be
redefined」。禁令加一条 `d.name == "Array" && cx1.is_std_module` 即可——只在 std 内，
因为门控的全部意义就是 std 外面那个 `Array` 是用户自己的。

（同样问过 trait 名：std 里 `pub trait Array[T]` 实测无害，所以**没**动那一处。
对称好看不是改代码的理由。）

### 7.5 §7.4 的消费者故事自己也没走通(2026-07-27,动手前第二次勘察)

§7.4 说关联类型的理由是「`index_wanted` 的两条 arm 能挪进 std 的 impl」。**这句话没有被走过一遍**,
走一遍就停在第一步:std 写不出那个 impl 的体。

```dawn
impl[T] Index[List[T]] {
  type Item = T
  fn index(xs: List[T], i: Int) -> T = xs[i]   # 运算符拿自己定义自己
}
```

两条逃生路,各有代价,都不在 §7.4 的账上:

| 路 | 体怎么写 | 代价 |
|---|---|---|
| 走 `get` | `get(xs, i).expect("index out of bounds")` | **语义正好**——`xs[i]` 本来就是「取不到就 panic」;但 `get` 的签名是 `opt_ty(t)`(`types.dawn:878`),**每次下标多一次 Option 分配**。值不值要用 `selfhost-bench.sh` 量,不是拍板 |
| 走 `prim_relation` | 加一条 `INDEX_ID` 臂,由 prelude 铸 impl | 两条 arm 从 `checker.dawn:3274` **搬到 `lower.dawn:807`**——挪了一个文件,没挪进 std;而且要自带解释器臂,因为 `xs[i]` 今天经 `CIntrinsic("list_index")` 在 comptime 折(`lower.dawn:2146` → `interp.dawn:681`) |

顺带两条订正:

- §7.4 引的 `index_wanted` 行号 **3293 是错的**,那里是 `index_wits`;`index_wanted` 在 **3274**,
  两条 arm 在 3275-3277。
- **`list_index` 不会因此消失**:列表模式匹配直接发它(`lower.dawn:406`、`418`),与 `[]` 无关。

还有一条更靠前的裁决没做:**trait 方法的关联类型出现在参数位时,这个方法还能不能按名字调用**
(`index(v, 0)`)。能,则 `Item` 会进 `check_call_sig` 的推断路径;不能,则只出现在返回位就够了。
**这个问题决定第一刀的表示选型**,先答它再动手。

> §7 的收尾教训是「计划里一个待办被别的待办引用得越多,越没人回头验它」。§7.4 是这一页
> 上第三条被实测推翻的推断,而它是这一页**自己**刚写下的。

**开工条件**(三条,都不大):①`impl[T] Index[List[T]]` 的体到底怎么写,量过 `get` 那条路的分配代价;
②参数位关联类型可否按名字调用;③前置缺陷 #55 已修(已完成,`7f79491`)。
