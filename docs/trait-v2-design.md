# trait v2 最小切片：设计

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
  实测 `type Box[T] = { v: T } derive Show` 编得过,`to_string(Box { v: fn(x: Int) => x + 1 })`
  才报「cannot print a value of type `Box[fn(Int) -> Int]`」。不是漏洞,但报错点离声明远。

解禁之后两者都变成声明处生成 `impl[T: Ord] Ord[Box[T]]` / `impl[T: Show] Show[Box[T]]`,
在声明处一次检清——与 §3.7 对 `==` 做的是同一件事,只是换了个 trait。

**落点分两处**(理由同决策 6):`derive Ord` 是纯加法,进 **2a**;`derive Show` 要等
`Show` 成为 trait,随 **S1.4**。

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

> **这是明知要删的脚手架。** S3 之后 `List`/`Map`/`Set` 是 std 里的真 ADT,
> `head_owner` 退化成只剩 `HAdt` 那一支。决策 3 选「写进 std 源码」时就接受了
> 这一段过渡代码;记在这里,免得将来有人把它当永久设计去维护。

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

### 3.12 刀法（每刀含测试，均可单独验）

1. **语法 + AST + `ImplI` 扩展**。解析得了,注册时报「条件 impl 尚未支持」。
   纯前端,零行为变化。
2. **`impl_table` 改按 head**。此时还没有条件 impl,所以**这刀必须零 Emit-Change**
   ——是纯重构,拿 Core golden 和 `__emit` 逐字节验。
3. **`solve` + `WApply` + 按需合成结构 impl**,替掉 `WStructural`。
   `==` 暂不接(仍走 `resolve_eq_witness`),所以行为不变。
4. **`CDictApply` + 三个消费者**(JVM / C / interp)。
5. **`derive Ord` 对泛型解禁**(决策 5)。纯加法,所以要赶在发布前进 2a,让种子学会。
6. 发布 **2a**。
7. **std 给容器写 `Eq`/`Hash`/`Ord` 条件 impl** + `==` 走 `solve` + 删三处旧机制。
   **破坏性、Emit-Change 大。**(`Show` 那条见决策 6,落在 S1.4。)
8. 收尾:spec §3.5 改 bullet、known-red 该删的删、`trait.md` v1 范围表标注。

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
