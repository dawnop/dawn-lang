# 语义收口设计（S1）

> 状态：**current** —— S1 语义收口的设计，步 1–3 已落地；未完的部分在文中标注。
>
> 对应 [`native-backend-plan.md`](native-backend-plan.md) §11.4 的 S1 那张表。
> 那张表是路线,每行一句话；这份是**动码前的设计**,把每行里真正要做的裁决写下来。
>
> 为什么值得先写:S1 的六项都不是加功能,是**把一件事的 N 份定义收成一份**。
> 收错方向的代价不对称——多收一份(把本该分开的两个关系合并)是**静默改语义**,
> 而它们今天恰好长得一模一样。§2.3 记了一条我差点就那么干的。

## 1. 度量:一个关系今天有几份定义

不是读代码读出来的印象,是逐处点出来的。**「两个 Dawn 值相等吗」这个问题,
今天有七份互相独立的答案**:

| # | 位置 | 管什么 | 对 `Bytes` | 对 ADT |
|---|---|---|---|---|
| 1 | `emit.gen_equality`(`emit.dawn:733`) | `==` 运算符,JVM | `Arrays.equals`,**内容** | `Object.equals` → 转 #2 |
| 2 | `codegen.gen_equals_method`(`codegen.dawn:2590`) | ADT/record 类的 `equals`,JVM | `Object.equals`,**身份** | 逐字段,递归转 #2 |
| 3 | `codegen.emit_native_eq`(`codegen.dawn:2912`) | prelude `Eq[标量]` 的字典体,JVM | `Arrays.equals`,**内容** | 不适用 |
| 4 | `codegen.gen_tuple_class`(`codegen.dawn:655`) | 元组类的 `equals`,JVM | `Object.equals`,**身份** | `Object.equals` → 转 #2 |
| 5 | `emitc.gen_cbinary`(`emitc.dawn:408`) | `==` 运算符,C | 够不着(`bytes_*` 未实现) | C 的 `==`,**指针** |
| 6 | `interp.value_eq`(`interp.dawn:241`) | comptime 折叠 | 无 `Bytes` 值 | 逐字段,第四份手写遍历 |
| 7 | vendored `dawn/rt/Lists` / `Maps` | 容器的元素相等 | `Object.equals`,**身份** | `Object.equals` → 转 #2 |

七份里 #3 的文档注释是这样写的:

> Two same-typed scalars on the stack → a boolean, matching what the `==`
> operator emits for that type (emit.gen_equality). **The two must agree**

——一条**靠注释维持的不变量**。它今天在标量上确实成立,而在 `Bytes` 上,#1/#3 与 #2/#4/#7
已经分岔:`scripts/spike-native/eq_bytes.dawn` 的 21 行里有 8 行答错。ADT 上 #5 与其余六份分岔:
`eq_adt.dawn` 的每一个 yes 在 native 上都是 no。

哈希是同一张图的第二层:`hash` 内建对 `Bytes` 走 `Arrays.hashCode`(**内容**,
`emit.dawn:2205` 特判),而同一个 `Bytes` 作为 ADT 字段被 `hash_of`(`codegen.dawn:2514`)
哈希时走 `Object.hashCode`(**身份**)。实测 `hash(bytes_utf8("hi"))` 两次都是 4290,
是内容哈希;而 `checker` 禁止 `Bytes` 进 Map 键的诊断说的是「hashes by identity, not
content」——那句话只对容器那条路成立。**同一个 `Bytes`,两个哈希,诊断只知道其中一个。**

### 1.1 根因不是「忘了同步」

七处都不是随手写的,每处都对**它自己看得见的那部分**做了正确的事。问题在于
**Core IR 里 `CBinary(CEq, a, b)` 不携带语义**:它只说「这里要比一下」,不说比什么。
于是每个消费者必须自己发明一个答案,而「发明」这个动作没有任何门禁能看见。

这与 §11.3 已经裁决过的一件事同形:字典槽的桥接方法原先由**每个后端各生成一遍**,
后来改成 lowering 合成一个普通顶层函数,槽只指向它,两个后端都不知道这件事存在。
**结构相等是同一形状的第二例。**

## 2. 不动的三条(先查 spec,再动手)

收口的诱惑是把长得一样的表合并。以下三条**看起来**是重复,实际不是,合并即改语义。

### 2.1 `Float` 的 `Eq` 与 `Ord` 刻意不同 —— **已推翻(2026-07-26)**

实测:

```
nz = 0.0 * -1.0        # 真的 -0.0,1.0/nz = -Infinity
nz == z                true      # 运算符,也是 [T: Eq] 的答案
cmp(nz, z)             -1        # [T: Ord] 的字典
nan == nan             false
cmp(nan, nan)          0
```

`cmp(a,b) == 0` 与 `a == b` 在 `NaN` 和 `±0.0` 上给相反答案。

**这一段原本的结论是「这不是缺陷」**:spec §4.3 白纸黑字写着两者「刻意不同(同 Java
`compare` 与 Rust `total_cmp` 的取舍:比较要诚实,排序要成序)」。我在设计 S1.5 时
把它当成第八条缺陷,查到这句就收手了,还在这里写下「记在这儿是为了让下一个人不必再撞一次」。

**2026-07-26 用户裁决:推翻。`Ord[Float]` 从全序降成偏序 —— 删掉 `Ord[Float]`。**

两条理由:

- 这是**同一个值两个答案,取决于走哪条路**,与同日裁掉的 `Hash[Float]` 是同一种病。
  留一个删一个是双标。
- **引 Rust 那句站不住**:Rust 的 `total_cmp` 是 `f64` 的**固有方法**,要显式调用;
  `f64` 本身**没有 `Ord` impl**。spec 拿 Rust 当先例,而 Rust 恰恰不这么做。真正的
  先例是 Java —— 而 Java 那条正是 Kotlin 要专门写一节文档、再挂一个未修 issue 的地方
  ([`equality-survey.md`](equality-survey.md) §2)。

**具体形状**:

- 删 `Ord[Float]`(`prelude_impls()` 的 Ord 标量表去掉 `TyFloat`)。
- **不引入 `PartialOrd` trait。** Rust 需要它是因为 `<` 在 Rust 就是 trait 方法;
  Dawn 的 `<`/`<=`/`>`/`>=` 对 `Int/Float/String/Cursor` 走 checker 的 **native fast
  path,根本不解见证**(`checker.dawn:2919` 的 `OpLt | OpLe | OpGt | OpGe` 支)。
  Float 的偏序已经由运算符表达着了,`PartialOrd` 没有活干。
  **「降成偏序」= 少一个 impl,不是多一个 trait。**
- `a < b` 的行为不变(仍是 IEEE)。变的只是 `[T: Ord]` 不再接受 `Float`。

**实测影响面:全仓 1 处** —— `examples/traits.dawn:71` 的 `assert cmp(1.5, 1.5) == 0`。
没有 `sort` 落在 Float 列表上;唯一的 `derive Ord`(`examples/traits.dawn:10` 的 `Card`)
字段是 `Int`/`String`。要给 Float 排序的人改写 `sort_by(xs, (a, b) => …)`,把语义显式选出来。

**还留着一处不对称,没裁**:`Eq[Float]` 仍在,而它**不自反**(`nan == nan` 为 false)——
S1 步 2 正是拿「不自反」挡掉函数值的。Rust 靠拆 `PartialEq`/`Eq` 安置这件事,Dawn 只有
一个 `Eq`。S1.5 动手前要么裁、要么明确记下不裁。

原来那句「合并会静默抹掉语义」仍然成立,只是理由换了:`eq_scalars()` 和 Ord 的标量清单
差别一部分是能力(Bool/Bytes/Cursor 没有 `<`),另一部分是语义 —— 而语义那部分现在的
处置是**让它消失**,不是保留。

### 2.2 容器自身的相等留到 D2/D3 —— **已了结(2026-07-25)**

写下时的理由:`dawn/rt/Lists` / `Maps` / `Sets` 是 **vendored 的 `.class`**
(`vendor.dawn` 从 classpath 读,源在归档的 `kotlin-final`),本仓库改不动,所以
`List[Bytes] == List[Bytes]` 这一种没有任何修法。

D2/D3 把三个容器换成纯 Dawn 的 `std/hamt` 与 `std/pvec`,vendored 的 `.class` 一个不剩,
相等改由 std 自己写的条件 impl 给出(`impl[T: Eq] Eq[List[T]]`)。这一种连同它所在的
那类洞一起没了。

### 2.3 `Bytes` 进 Map/Set 键的硬禁不撤 —— **已推翻(2026-07-27)**

写下时的理由:即使 `hash` 内建对 `Bytes` 是内容哈希,容器用的仍是 `byte[]` 自带的
`hashCode`。所以禁令要留到 D2/D3。

D2/D3 之后容器是纯 Dawn 的,查键用的是键类型的 `Eq`/`Hash` 字典,再没有第二套哈希。
`Bytes` 两头都是内容(`Arrays.equals` / `Arrays.hashCode`),它是一个合法的键,
S3 尾款把禁令撤了。

**这条留给下一次的教训不是「预判错了」,是「禁令没有到期提醒」。** 禁令的理由是
「容器用宿主的哈希」,理由消失于 D2/D3,而禁令自己不会知道——它是一条独立的结构行走,
和它所依赖的那个事实之间没有任何机械联系。撤掉它的办法也正是这个:**让规则由它依赖的
东西直接给出**(键合法性 = `[K: Eq + Hash]` 这条 bound 解得开),这样理由变了,规则自动跟着变。

## 3. S1.2:结构见证展开器

### 决策 1 — 结构相等的定义放在 lowering 合成的**普通 Core 函数**里

候选:

| | 做法 | 为什么不 |
|---|---|---|
| a | Core 加一个带语义的节点 `CStructEq(ty)` | 每个后端实现一次 = 还是 N 份,只是把 N 份挪了个位置 |
| b | **lowering 合成普通 Core 函数,`CEq` 只留给后端原生的标量关系** | ← 采纳 |
| c | checker 合成 `impl Eq[T]`,body 是 Dawn AST,走已有 impl 通路 | checker 里没有「合成表达式再走一遍类型检查」的机制;`derive Ord` 恰恰是**绕开**它、把体留给后端才成立的,照抄它等于照抄病灶 |

(b) 的合成物形如:

```
fn dawn$eq$<ty_key>(a: T, b: T) -> Bool =
  # ADT:先比判别式,再逐字段递归
  # 元组/record:逐字段递归
  # 标量:塌缩成 CBinary(CEq, ..),那是后端原生的关系
```

命名走 `core.dawn` 的 `ty_key`——**唯一一份**,§11.3 已裁决过(三个生产者曾把同一个 impl
叫成三个名字)。

### 决策 2 — 按需合成,不是每个 ADT 都合成

lowering 遇到一个需要结构相等的具体 `Ty` 才合成一份,memo 存在 `LSt` 里。理由:

- 程序不比较的类型不该多出一个函数和一段字节码。
- 「每个 ADT 一份」这个说法本身不成立:`Option[Point]` 与 `Option[Int]` 是两份不同的比较。
  按 `Ty` 而不是按 ADT 声明索引,泛型实例化才落得下。

### 决策 3 — 只展开 **ground** 类型;擦除残留变成一个**具名**的运行期原语

> 这条与上一版的「JVM 类的 `equals` 改成转发到合成函数」**不同**。上一版是错的,
> 动手写展开器的第一天就撞上了两处硬矛盾,记在这里而不是抹掉:
>
> 1. **合成函数按实例化类型索引(决策 2),而 JVM 类按声明索引。** `Option[Point]` 与
>    `Option[Int]` 共用一个 class,一个 `equals` 转发不到两份不同的合成函数。
>    跨模块也不成立:`Point` 的 class 在声明它的模块里发,比较它的合成函数在使用它的模块里。
> 2. **`==` 的左值可以含刚性类型变量,而且今天连 bound 都不需要。** 实测:
>    ```dawn
>    fn same2[T](x: Option[T], y: Option[T]) -> Bool = x == y   # 编得过,无 [T: Eq]
>    ```
>    展开 `Option[T]` 需要 `Eq[T]` 的字典。要拿到它,要么**强制 `==` 要求 `Eq` bound**
>    (对的方向,同 Rust/Haskell,但是破坏性的语言改动 + 要改 spec),要么等 S2.1 的
>    条件 impl(`impl[T: Eq] Eq[Option[T]]`)。两条都不在 S1 里。

于是分两半:

| 左值类型 | lowering 发什么 | 谁实现 |
|---|---|---|
| **ground**(不含刚性 `TyVar`) | 合成函数的直接调用 | Core,一份,两个后端都编它 |
| **非 ground** | `CIntrinsic("struct_eq", ..)` / `("struct_hash", ..)` | 后端各一处,但**有名字、可数、可查** |

关键在第二行不再是**裸 `CBinary(CEq)`**。今天的擦除路径与标量路径在 Core 里长得一模一样,
所以「后端自己发明了一个答案」这件事不可见;换成具名 intrinsic 之后:

- JVM 的实现就是 `Object.equals` —— 也就是说 `gen_equals_method`(#2)**不再是一份野生的拷贝**,
  它是「JVM 对 `struct_eq` 这个契约的实现」。同一份代码,身份变了,从此有契约可对。
- native 今天的实现是**照名字 panic**,而不是静默的指针比较。缺口从「答错」降级成「答不了」。
- 残留量**可数**:`grep struct_eq` 数得出还有多少地方没收口,S2.1 落地时这两个 intrinsic 整体删除。

### 决策 4 — 两份实现必须相等,而这件事由语料钉住,不由注释钉住

决策 3 留下两份实现(Core 的合成函数、JVM 的 `struct_eq`)。它们必须是**同一个关系**,
否则 `x == y` 与 `map.get(m, x)` 会给不同答案——Dawn 的 `Map`/`Set`/`List` 是 vendored 的
Java 容器,比较键用的就是 `key.equals()`,也就是 `struct_eq` 那条路。

今天它们在 `Bytes` 上已经不等(§1 的表)。所以这一批**必须同时**把
`gen_equals_method` 的 `Bytes` 臂改成 `Arrays.equals`、`hash_of` 的改成 `Arrays.hashCode`
(两处必须配对改,否则违反 JVM 的 equals/hashCode 契约)。元组类同理。

这不是「顺手修个 bug」——在决策 3 的结构下它是**契约一致性要求**。
`bytes-design.md` 决策 A 当初判「不修」,理由是只修 record/tuple 会留下
「record 结构化、List 仍身份」的更难预测的不一致;而在这里,record 与 List
走的是同一条 `struct_eq`,一起改,那个理由不再成立。

剩下的洞收敛成**一种**:容器直接装裸 `Bytes`(`List[Bytes]`)——vendored 的 `Lists`
逐元素调 `Object.equals`,`byte[]` 没有内容 `equals` 可调。那一种留到 D2/D3,
写进 `known-red.txt` 的说明。

**agreement 由语料钉**:`eq_bytes.dawn` 增加一个容器用例(`List[Wrap]`),
`==` 与容器查找必须给同一个答案。注释维持不变量的时代到此为止(§1 引的那句
「The two must agree」就是反例)。

### 决策 4 — `interp.value_eq` 也调同一份

comptime 解释器执行的是 Core,合成函数就在 Core 里,`value_eq` 对 ADT 的手写遍历
(#6)因此可以整段删掉,只留标量。这条顺带把 `const_fold` 那类「两个后端折的是同一份
`interp.dawn`,所以在错答案上达成一致」的风险面缩小。

### 决策 5 — `CEq` 收窄成「后端原生标量关系」并写进 `core.dawn` 的注释

展开器落地后,`CBinary(CEq, ..)` 的合法左值类型收窄成标量(含 `String`/`Bytes`);
非标量要么是合成函数的调用(ground),要么是 `struct_eq`(擦除)。
这一条必须**写进节点定义的注释**并由 lowering 断言,否则下一个人照旧会在 ADT 上发 `CEq`,
而两个后端照旧会各自发明答案——这次没有语料能发现,因为语料只测已知的类型。

### 决策 6 — 两条入口都要接,它们从一开始就是分开的

`==` 运算符**不经过见证**:checker 对 `BEq` 直接返回 `no_wit()`(`checker.dawn:2848` 一带),
lowering 用一张平铺的算符表把它翻成 `CEq`(`lower.dawn:195`)。`WStructural` 只服务
`[T: Eq]` 这条 bound 路(`lower.dawn:728` 的 `primitive_eq_witness`)。

**这就是「一个关系七份定义」的第一因**:运算符和 trait 从语言的第一天起就是两条独立管道,
而不是一条管道的两个入口。展开器必须同时接上两条,并且在接上之后,
「`a == b`」与「`[T: Eq]` 实例化到 `T = A` 后调 `eq(a, b)`」在 Core 里应当发出**同一个调用**。
这一点本身就该有断言。

## 4. S1.6:`WStructural` 收窄

`checker.dawn:4395` 今天对任何缺 impl 的具体类型**无条件**发 `WStructural`,注释写
「equality is total」。于是两个**函数值**能通过 `[T: Eq]` 并按引用比较,而同一个文件里
写 `g == h` 是编译错误(`checker.dawn:2828`「functions cannot be compared」)。
**同一个关系,两道门,答案不同。**

收窄规则:只有**结构可分解到有 impl 的叶子**的类型才发 `WStructural`;`TyFn` / `TyArray`
报错,措辞与运算符那道门一致。

与 S1.2 必须同批:展开器要求「每个叶子都有定义」,而这条正是它的前置——今天的
`WStructural` 允许叶子没有定义,展开器碰到就只能 panic 或再发明一次。

## 5. S1.3:Core 的字典表成为唯一真相

`CDictRef` 携带一个 `_key`,JVM 后端**明确忽略它**,回头查 `g.impl_table` 重导类名
(`emit.dawn:1875`,注释里写着「the key a table-based backend uses is ignored here」)。
于是 `CModule.dicts` 只有一个读者,而那是未完成的 C 后端——**那张表从来没被验过**,
`dict_forward:cc` 发出的 C 引用两个不存在的符号就是它的第一份证据。

改法:JVM 也读表。这一步的门禁是 S0.4 的 Core golden——它是今天唯一看得见
`CModule.dicts` 的东西。

### 5.1 动手之后:病根不在读者那侧,在写者那侧

原以为这步是「把 `emit.dawn:1875` 那几行换成查表」。逐处点下来,**表本身是坏的**,
换读者只会把坏值读出来。三类槽里有两类根本没有定义:

| 见证 | 槽今天填什么 | 那个符号存在吗 |
|---|---|---|
| 用户 `impl`(`provided` 非空) | `CSlotFn` → `make_bridge` 合成的桥 | 存在 |
| **prelude impl**(标量,`provided` 为空) | `CSlotDefault(owner, "eq")` | **不存在**——prelude trait 没有 default |
| **derive 来的 impl**(`provided` 也是空的) | `CSlotDefault(owner, "cmp")` | **不存在** |
| **`WStructural`** | 短路成一个共享 key,**连 `CDictDef` 都不注册** | 不存在 |

而且 `CSlotDefault` 的 owner 取的是 `owner_or(tr.owner, st.owner)`,prelude trait 的
`owner` 是 `None`,于是回落到**用户模块**——C 里出来的 `dawn_eqhash__default_1_eq`
连模块都指错了。

所以真正的改法与决策 1 同形:**lowering 把这两类槽也合成成普通 Core 函数**
(`prim$<tid>$<subject>$<method>`),body 就是 `prim_relation`——`Eq` 走 §3 的展开器,
`Hash`/`Ord` 走具名 intrinsic。于是三类槽在 Core 里长得一模一样,后端只要转发。

副产品是把 JVM 那五个**手写字节码的字典生成器**(`gen_prelude_eq_impl` /
`gen_prelude_hash_impl` / `gen_prelude_ord_impl` / `gen_structural_eq_impl` /
`gen_structural_hash_impl`)连同 `gen_impl_class` 一起删掉:它们的 body 现在是 Core
函数,类只剩一层转发,一个 `gen_dict_class` 就够。§1 那张表里的 **#3
(`emit_native_eq`)就是这么消失的**——它不是被改对了,是不再需要存在。

### 5.2 顺带落网的第八条:`cmp(3, 9)` 会在运行期崩

同一个病根还有一个更响的症状,是写这一步时读代码读出来的:

```
$ dawn run 'println(to_string(cmp(3, 9)))'
NoSuchMethodError: 'long ordprim.dawn$default$Ord$cmp(Object, Object, Object)'
```

`==`/`<` 这些运算符不走字典,所以从没碰过;而**直接写 `cmp(a, b)`**、主体是标量时,
`lower_trait_call` 找不到 `provides`,就落到「调 trait default」那条,而那个 default
不存在。**编译期全绿,运行期必崩。** 修法就是上面那条:标量 Ord 也是 `primitive_witness`,
塌缩成 `cmp` 原语,和 `Eq`/`Hash` 一视同仁。

## 6. S1.4:`Show` 成为第四个 prelude trait

> **已落地(2026-07-26,v0.16.0–v0.17.0)。** 下面的判断都成立,动手时另外撞上四件
> 事,记在这里:
>
> 1. **线又画早了一刀。** v0.16.0 注册了 trait、发了版,然后发现 `Show` 从没进
>    `traits_by_name`——种子认得这个形状,却拒绝用户写 `impl Show[X]`,std 一行也
>    写不出来。同一条轴、同一类错误,trait v2 刚教过一遍(那次 2 版变 4 版)。
>    **判据不是「种子解析得了吗」,是「种子能编译一个用了它的 std 吗」**,而这次
>    还要再加一条:**能编译一个用了它的用户程序吗**。
> 2. **发接口的那段扫描读错了东西。** 它只认「某个函数签名带这个 bound」,可
>    条件 impl 是字典出现的另一条路——它自己的字典类实现该接口,它的实参实现
>    bound 命名的接口——一个 bound 都不写也会走到。`Eq` 有同样的洞,只是 std 的
>    `eq_go[T: Eq]` 恰好在每个程序的 fn 命名空间里,把它盖住了。
> 3. **解释器不能只会拒绝。** 渲染一进字典轨,折叠一个含容器的 const 就撞上
>    `no_traits`——那会把「错答案」变成「编译不过」,更糟。所以这一刀顺手让 comptime
>    真的会走字典:字典是个带 key 的值,key 找槽表,槽是普通函数,字典本身当尾参
>    传进去(JVM 的字典类就是这么干的)。impl 方法得另立一张表按 (trait, head, 方法)
>    找,因为一个模块里两条 impl 可以同名,而 `by_owner` 只按名字键。
> 4. **一个 trait 兼两职,线只能画在这儿。** `to_string("a")` 是 `a`,`["a"]` 是
>    `["a"]`——引号是「这是值不是标点」的记号。`show` 只能是其中一份;选了嵌套那份,
>    于是经 `[T: Show]` 渲染一个字符串带引号,`${x}` 在静态类型就是 `String` 时不带。
>    Rust 拆成 Display/Debug 才没有这个取舍。
>
> 出口达成:`show_derive:emitc` 与 `const_fold:jvm` 都删了,**差分 harness 里
> 一条「编造的答案」都不剩**,三条 known-red 全是 native 还没有的能力。
> 代价一处:`to_string` 带 bound 之后不能再当函数值传(`map(xs, to_string)`),
> 全生态一处(`examples/calc.dawn`),诊断里写着改法。

今天 `Show` 不是 trait,是三件东西的合称:`AdtI.derives_show` 标志、
`is_showable`/`is_showable_field` 两个静态谓词(`checker.dawn:986`/`1009`)、
运行时 `dawn/rt/Show` 的 instanceof 链。tagged union 没有链可走,所以 native
**结构性无解**(`show_derive:emitc`)。

改成真 trait 之后,渲染与 `Eq`/`Hash`/`Ord` 走同一条字典轨,native 的问题从
「没有对应物」变成「和别的 trait 一样」。`is_showable` 与 `is_showable_field` 的区别
(前者要求具体、后者放行类型参数)在 trait 世界里就是「有没有 `[T: Show]` bound」,
两个谓词一并消失。

`interp.dawn` 把非标量渲染成 `"<value>"` 那条(`const_fold:jvm`)也在这里闭合:
有了字典,解释器有真的东西可调。

## 7. S1.5:不是「六表合一」,是「拆开被合错的、合并被拆错的」

> **已落地(2026-07-26)。** 两件破坏性改动照裁定做了:`Hash[Float]` 与
> `Ord[Float]` 都删了,`ord_scalars()` 现在是 `[Int, String]`,`hash_scalars()`
> 是新表(eq 减去 Float)。实测影响面确实只有一处(`examples/traits.dawn` 的
> `cmp(1.5, 1.5)`),已改成演示新规则。
>
> 三处与设计不同,记在这里:
>
> 1. **「要合的」那半已经不用做了。** `impl_subject_ok` 在 trait v2 刀 2 里就被
>    `impl_shape_bad` 取代了,主体合法性现在由 `head_of` 一处决定——Bytes/Cursor
>    自然在内,「语言给自己写了用户被禁止写的 impl」这条自相矛盾随之消失。
>    收口有时是别的刀顺手完成的,动手前值得再查一次。
> 2. **`invalid_key_part` 还改不成「问表」。** 它要走进容器和 ADT 里面,而 ADT
>    今天仍是结构性哈希、没有 impl 可指,照表问会把每个用户类型都判成不能当键。
>    这条与 `uncomparable_part` 同形,一起归 S3。措辞已改准,并把「规则其实已经
>    是 `Hash` 解不出来」写进了注释。
> 3. **`Eq[Float]` 明确不裁。** 它不自反(`nan == nan` 为 false),而 S1 步 2 正是
>    拿「不自反」挡的函数值。仍然留着:Dawn 只有一个 `Eq`,拆成 `PartialEq`/`Eq`
>    会让 `1.5 == 2.5` 这种日常写法多背一层概念,代价大于收益;要自反性的地方
>    (容器查找)已由「Float 不能作键」挡住。**这是裁定,不是遗漏。**

plan 的一句话是「标量能力表六合一」。逐个看过之后,这句话**不准确**——六张表回答的
不是同一个问题:

| 表 | 回答的问题 | 处置 |
|---|---|---|
| `eq_scalars()`(`types.dawn:536`) | 哪些标量的 Eq/Hash 后端原生实现 | **拆**:见下 |
| `prelude_impls()` 里 Ord 的 `[Int,Float,String]` | 哪些标量有序 | **去掉 `Float`**(§2.1,2026-07-26 裁决) |
| `is_showable` / `is_showable_field` | 哪些类型可渲染 | S1.4 一并消失 |
| `invalid_key_part`(`checker.dawn:340`) | 哪些类型不能进 Map/Set 键 | 改走 bound,但见 §2.3 |
| `impl_subject_ok`(`checker.dawn:1844`) | 用户可以给哪些标量写 impl | **合**:见下 |

**要拆的**:`prelude_impls()` 今天用**同一个** `eq_scalars()` 同时铸 `Eq` 和 `Hash`
的 prelude impl。但 Eq 和 Hash 对 `Float`/`Bytes` 的答案本该不同——`Eq[Float]` 成立,
而 `Hash[Float]` 按 spec §2.2 就不该存在(两套相等给不出一致的哈希)。一张表服务两个问题,
是「合错了」。拆开之后 `invalid_key_part` 才可能真的改成「`Hash[T]` 解不出来」。

**要合的**:`impl_subject_ok` 放行 `Int/Float/Bool/String`,**没有 `Bytes` 和 `Cursor`**;
而 `prelude_impls()` 给 `Bytes`/`Cursor` 都铸了 `Eq`/`Hash`。**语言自己给某些主体写了 impl,
却禁止用户给同样的主体写 impl。** 这就是 plan 说的「Cursor 那条自相矛盾」,
两处该是同一份清单。

## 8. S1.1:intrinsic 身份从 `String` 换成 ADT

intrinsic 今天用字符串名标识,于是「这个名字属于谁、可见吗、ABI 是哪类」散在:
`rt_intrinsic_target` 的前缀链、`erased_builtin_sig` 的**第二套**前缀链、
`internal_builtins()` 的四份手抄名单,以及两张表里的死臂。

改法见 [`runtime-intrinsics-design.md`](runtime-intrinsics-design.md):身份换成 ADT,
可见性 / ABI 类别 / 运行时归属写进 `Sig` 声明。这项与前五项**无依赖**,
放最后是因为它最宽、最机械,且它的收益(编译器内部整洁)不解锁任何红线。

## 9. 顺序与门禁

前五项按依赖排,不按大小排:

| 步 | 内容 | 出口 | 门禁 |
|---|---|---|---|
| 1 | S1.2 展开器(ground)+ 决策 3 的具名 intrinsic + 决策 4 的 `Bytes` 配对修 | ✅ 三行已删 | Core golden 已重录 |
| 2 | S1.6 `WStructural` 收窄(`TyFn`/`TyArray` 报错) | ✅ §11.1 的三已闭合 | 既有 164 测 |
| 3 | S1.3 字典表成为唯一真相 | ✅ `dict_forward:cc` 已删 | Core golden 是唯一看得见它的门 |
| 4 | S1.4 `Show` 成 trait | `show_derive:emitc`/`const_fold:jvm` 删除 | 差分 harness 全绿 |
| 5 | S1.5 的「拆」+「合」+ `invalid_key_part` 改走 bound | `impl_subject_ok` 与 prelude 同一份清单 | 既有测试 |
| 6 | S1.1 intrinsic 身份 | 四份手抄名单消失 | 无红线,靠 golden |

**第 1 步不可再拆**:决策 3 与决策 4 之间的中间状态是「`x == y` 与 `map.get(m, x)`
给不同答案」,那比今天一致地错更糟。其余各步之间都可以停。

> **上一版把 S1.5 的「拆」排在第 1 步,那是错的。** 理由本是「最小、风险最低」,
> 但实测发现它**观察不到**:`resolve_witness`(`checker.dawn:4395`)对缺 impl 的
> `Eq`/`Hash` 无条件发 `WStructural`,所以删掉 `Hash[Float]` 的 prelude impl 之后,
> `[T: Hash]` 实例化到 `Float` 仍然照编不误,只是改走结构默认。
> **那一步要到 S1.6 收窄之后才有出口条件**,故挪到第 5 步。

每步都要过:`dawn fmt --check`、`dawn test selfhost`、fixpoint `B == C`、
`spike-native/run.sh`、`array-contract`、`selfhost-core-diff.sh`、N vs N−1 差分
(改字节码的必须带 `Emit-Change:`)。

### 9.1 第 1 步做完之后的实测

- **`eq_adt` 在 native 上从「每个 yes 都答成 no」变成全绿**,`diff` 一并绿。C 后端第一次
  有结构相等,而它一行 C 都没为此写——编的是 lowering 展开出来的同一份 Core。
- **`eq_bytes:jvm` 全绿**,21 行逐字对上手写的 `.expect`。
- **残留可数**:编译器自身的 52 个模块里,合成出 **50** 个比较函数,还剩 **54** 处
  `struct_eq`。约一半,与决策 3 的预期一致——这个数就是 S2.1 的进度条。
  > 后续查清(2026-07-26,`trait-v2-design.md` §2.1.1):这些残留**全是 `List[…]`**,
  > 一处刚性类型变量都没有——`expandable_eq` 只认 `TyAdt`/`TyTuple`,容器即使 ground
  > 也落到 intrinsic。所以它量的是**容器归位**,删它的是 `impl[T: Eq] Eq[List[T]]`。
- **自举比值没有可测的退化**:7 次采样中位数 1.0981,相对基线 −1.5%,而 spread 12.6%。
  换句话说这台机器分辨不出这次改动的开销,**不能**据此声称变快了。
  (3 次采样那轮给的是 1.1520 / spread 15.0%,正是 S0.5 那条「spread ≥ 15% 就别下结论」
  的用处——那一轮什么也不能说明。)
- **顺手抓到一条自伤**:第一版把 `!=` 也一律走展开器,于是标量的 `a != b` 从 `CNe`
  变成了 `not (a == b)`——白丢一个两个后端都直接实现的节点。Core golden 的 diff 里
  一眼可见,这正是 S0.4 建它的理由。

### 9.2 第 2 步:比审计说的更糟一档

审计(§11.1 的三)记的是「两个函数值能通过 `[T: Eq]` 并按引用比较」。实测下来还要糟:

```
eq2(f1, f2)   false
eq2(f1, f1)   false      # 同一个函数,和自己比
```

**`Eq` 连自反都不成立**——`f1` 作为值在每个使用点铸一个新对象,于是引用比较对自己也答 false。
这不是「按引用比较」这种可以接受的弱语义,是没有语义。

收窄的做法不是加一道检查,是**把两道门合成一道**。原先:

- `==` 问 `contains_fn`,而那个 walk **不进 ADT 字段**——`Holder(f) == Holder(g)` 一路放行;
- `[T: Eq]` bound 什么都不问。

现在两边问同一个 `uncomparable_part`,于是 bound 不可能接受运算符拒绝的东西,
而 `Holder` 这种「ADT 里藏了个函数」第一次被拦住。诊断措辞也只有一份。

**编译器自身 34k 行一行没改就通过了**,说明这条规则没有误伤真实代码。

- **第 2 步的字节码面很大**。每个被比较的类型多一个合成函数,`equals` 多一层转发。
  自举比值(`scripts/selfhost-bench.sh`,今天 1.115)是这一步唯一的量,做完对一次;
  若明显退化,先看是不是每个 ADT 都合成了(决策 2 没落实)。
- **`Emit-Change` 会连着好几步**。N vs N−1 差分要求逐条声明,不要攒到最后一起写。
- **种子纪律**:S1 全程不得让 N−1 的编译器编不动 HEAD 的 `selfhost/src`。展开器是
  编译器**自己**也要用的东西(编译器里到处是 ADT 比较),所以第 2 步是自举压力最大的一步。
- **`known-red.txt` 是双向 ratchet**:每步修好的那几行必须同批删掉,漏删会红。

### 9.3 第 3 步的实测

- **`dict_forward` 全线绿**:`cc` 通过之后 `native`/`diff`/`stderr`/`exit` 一并通过,
  即 C 程序不只是编得过,输出与手写的 `.expect` 逐字相同。三种见证(prelude 标量、
  用户 impl、结构默认)都对。known-red **5 → 4**。
- **发出去的类少了**:`examples/eqhash.dawn` 从 **76 个类降到 61 个**。旧版一旦程序里
  任何地方有 `Eq`/`Hash` bound,就无条件铸 20 个字典类(3 个 Ord 标量 + 6 Eq + 6 Hash +
  2 个 structural + 2 个用户 impl 单例),而这个程序只用到 4 个。现在**按需**:
  lowering 注册了几个就发几个。
- **编译器自身**:8 个字典,8 个槽,`CSlotDefault` **零个**——8 个槽以前全是
  `slot default X.cmp` 这种指向不存在符号的项,现在全是 `slot fn X.prim$0$String$cmp`。
- **自举比值 1.0910**(7 次采样,spread 7.7%,基线 1.1151)。没有可测退化。

两条本可以静默过去的坑,都是「JVM 第一次真的去调那些 body」暴露的:

1. **合成 body 的 access**。lifted body 一律 `ACC_PRIVATE`,而字典类在
   `dawn/dict/…` 这个**另一个包**里,一调就 `IllegalAccessError`。以前从没人调过。
2. **合成 body 的描述符**。`gen_fn` 从 `captures ++ params` 拼描述符,**漏掉 `dicts`**;
   桥的字节码里却给字典参数分了槽。这个矛盾之所以能长期存在,正是因为**桥从来没被调用过**
   ——它加载不到的槽从不读,类照样过校验。

第 3 步之后,`emit.dawn` 里再没有第二处「这个见证是谁」的推导。留下的 `impl_table`
用途(`eq_override`、derive Ord 判定)问的是**类怎么生成**,不是见证身份,见 plan §11.4
的更正块。

### 9.4 记一条量到两次的噪声:ADT id 不稳

第 1 步和第 3 步各撞了一次:改动与某个模块毫无关系,Core golden 却报它变了。两次都是
**ADT id 整体漂移**——`checker.next_id` 是 ADT、trait、类型变量、每个符号**共用的一个
计数器**,所以在 `types.dawn` 里加两个函数,后面所有类型的 id 就 +2。

第 1 步时通过让 `coredump` 按名字渲染构造器压掉了大部分噪声;这次剩下的一处是
**合成比较函数的名字**(`structeq$Adt1814`)——它由 `ty_key_inst` 拼出,里面就是那个
裸 id。这不是可以在 dump 里归一化掉的东西:那是真实发射的方法名,归一化等于关掉
`__emit` 的探测器。

要根治得把 id 空间拆开(ADT 一个计数器,符号另一个),那会重命名一切,不属于 S1。
记在这里,是因为它的代价已经量到两次:**每次 golden 报「这些模块变了」,都要先排除
这一项**才能读出真正的改动。

## 10. S3 尾款:三处收窄的实测(2026-07-27)

D2/D3 落地后留下三件继承来的清理,记在这里,因为**三件里有两件的前提被实测推翻**。

### 10.1 `struct_eq` 还剩谁能到达

先量,再改。把编译器自身(54 模块)、backend-dawn(27)、`packages/web`(15)、
`packages/json`(13)、playground(22)全部 `__lower --dump`,`grep 'intrinsic struct_eq'`:
**零**。决策 3 立这个原语时说「残留量可数」,数出来是 0。

但「语料里没有」不等于「到不了」。逐形状探针跑下来,有三种能到达,其中两种是坏的:

| 形状 | 实测 |
|---|---|
| `fn f[T](a: Box[T], b: Box[T]) -> Bool = a == b` | 编译通过,落到擦除的运行期行走 |
| `eq2((), ())` / `hash(())` / `[()] == [()]` | **VerifyError: 操作数栈下溢** |
| `javaObj1 == javaObj2` | 正常,等于 `Object.equals` |

第二种的根因值得记:`Unit` 在 JVM 上占 **0 个栈槽**、描述符是 `V`,`unbox to=Unit` 弹掉
对象什么也不压。于是「先取两个操作数再 `invokevirtual equals`」这条路,操作数是空的。
Dawn 早就在两个地方拒绝过 `Unit`——`Show[Unit]` 报错、元组元素不能是 `Unit`——只有
`Eq`/`Hash` 放行,然后崩。**同一个立场在三个地方要各写一遍,写漏一个就是崩溃**,这正是
S1 那句「一个关系有几份定义」的另一种形态。

> **2026-07-27 更正**:上面那句「根因」只对了一半。零槽位确实是崩的**机制**,但它
> 不是该被保留的**前提**——次日的 #51 把 `Unit` 改成了普通的一个引用槽位
> (`Ldawn/rt/Unit;`),因为「零宽」在 JVM 描述符里根本没有拼法,形参、字段、捕获位
> 全部写出非法描述符。`Eq[Unit]`/`Hash[Unit]` 的禁令留着,但**只剩语义那半条腿**:
> 只有一个值,答案会是常量——与它占几个槽位无关。元组元素的禁令则随之删掉了:
> 那个位置本来就是擦除的 Object 槽,`List[Unit]` 合法而 `(Unit, Int)` 不合法讲不通。

第一种的根因是 `solved_structurally` 的兜底:合成 impl 的某个参数解不出见证时,它
**回落成 `WConcrete`** 而不是报错。写这条兜底时的注释说得很明白——「要求 bound 是破坏性
变更,属于刀 7」——刀 7 来了又走了,没做。改法是让它和条件 impl 同形:**合成 impl 的
见证能力,到它各部分的见证为止**。

三种关掉两种之后,`struct_eq` 只剩「宿主传进来的值」这一个主体,于是它改名 `java_eq`,
契约从「运行期结构行走」变成「宿主自己的相等」。**这对 native 是净减一项**:C 后端根本
见不到 `TyJava`,从此不欠这份实现——决策 3 当初写的是「S2.1 落地时这两个 intrinsic 整体
删除」,实际是**换了个更小的契约留下**,因为「Dawn 不定义宿主值的相等」是事实,不是缺口。

### 10.2 `uncomparable_part` / `invalid_key_part` 合不合

`uncomparable_part` 早就不是「第二道门」了——刀 7 之后它长在 `resolve_witness` 里,
是 Eq/Hash 结构默认的那条判定。真正的问题在它**只问 `Eq` 的表**:

```
[T: Hash] 实例化到 Float → has_impl_at(EQ_ID, TyFloat) 为真 → 放行 → Double.hashCode
```

S1.5 删掉 `Hash[Float]` 就是为了让这件事不可能,但那道墙只砌在**键位置**
(`invalid_key_part`),`hash(1.5)` 在键位置之外照样能过。改法:把它按 trait 参数化,
Eq 与 Hash 各自落到自己的标量清单上。

而 `invalid_key_part` 的三条禁令,改完之后逐条看:

| 禁 | 结论 |
|---|---|
| `Float` | bound 自己拒了(上面那条修完之后) |
| `Array` | bound 早就拒了(`Array` 按同一性持有) |
| `Bytes` | **理由已不成立**,见 §2.3 |

于是整条行走(连同 `check_key_type` / `check_key_types_in` / `reported_key_types`)删掉,
键合法性 = `[K: Eq + Hash]`。plan §11.4 记的阻塞理由是「ADT 不经 impl 哈希,照表问会把
每个用户类型判成不能当键」——**这条早已过期**:该问的不是 impl 表,是 `resolve_witness`,
而结构默认本来就是它答案的一部分。

代价一条,记清楚:检查点从**类型标注**移到**用到键的那个操作**。`Map[Float, Int]` 这个
类型现在拼得出来,只是没有任何操作能往里放键。这是可接受的——一个谁也放不进东西的空 map
无害,而报错落在真正非法的那一步上,位置比标注处更准。

### 10.3 `head_owner` 删不掉,而且比写下时更承重

注释说它是「有明确终点的脚手架:S3 之后它们是 std 里的普通 ADT,只剩 `HAdt` 那一支」。
**S3 没有让它们变成 ADT**——D2/D3 的关键裁决恰恰是让 `List`/`Map`/`Set` 继续做 `Ty` 变体,
只换 `desc_of` 与路由,这才绕开了 `is_builtin_name` 的重定义禁令和种子兼容那堵墙。

而且它现在更承重了:D2/D3 给 std 写了 `impl[K: Eq + Hash, V: Eq] Eq[Map[K, V]]`,
让这条 impl 不算孤儿的,正是 `head_owner(HMap) == Some("std/map")` 这三行。所以结论是
**它不是脚手架,是答案**,注释照实改。

## 11. opaque 的十二处漏写(2026-07-27,#53/#54 顺出来的)

#53 和 #54 报的是两个函数少了 `TyOpaque` 臂。按「一件事有几份定义」的老习惯把每个吃
`Ty` 的函数盘了一遍,结果是**十二处**,而且最重的两处不是崩溃是**静默给错答案**:

| 形状 | opaque | `alias` 孪生 |
|---|---|---|
| `opaque type N = String`,`to_string(n)` | `"bob"` | `bob` |
| `opaque type D = Bytes`,`a == b` | **`false`** | **`true`** |
| `opaque type M = Int` 作构造子字段 | **编译器死在 ASM** | 正常 |
| `Map[(Celsius,Int),Int]`,`Celsius = Float` | checker 放行、lowering panic | 干净诊断 |
| `derive Show` 的字段是 opaque | 「not printable」 | 正常 |
| `const D: Meters = 3` | 拒 | 正常 |

第二行最难看:`==` 说不等,而同一个程序里字典和 HAMT 说相等——**一个关系,两个答案**,
正是 S1 那条教训的原样重演,只是这次分歧的两边都在同一次运行里。

### 判据:别名替换法

spec §2.6 说 `opaque type` 与 `alias` 的差别**只有一条**——谁被允许看穿。于是判据可以是
机械的:**把 `opaque type N = T` 换成 `alias N = T`,答案变了就是 bug**,除非你是那四件
事之一(可赋值性、impl 选择、符号命名、诊断里的类型名)。

还有个次序:**先问身份再问表示**。`is_eq_scalar` 故意**不** peel——它要是 peel 了,
`eq_at` 会在查 impl 表之前就返回 `CBinary`,`impl Eq[UserId]` 就被删掉了。所以
peel 的位置一律在 `has_impl_at` 之后,`show_at` 早就是这么写的,这次是让另外两个跟上。

### 为什么文档没拦住

`emit_method_return` 上方有一整段注释讲的就是这个坑(S0.3,「opaque type over Int 就是
这样一个东西」),**三十行之后** `gen_equality` 原样再犯一次。同一个 `gen_ctor_class` 里
三个兄弟方法,`gen_hash_code_method` 对了,`gen_equals_method` 和 `gen_to_string_method`
错了。**文档在三十行的距离上都传不过去**,所以判据落成了脚本:`scripts/opaque-twin/`,
每个语料跑两遍(原样 / 替换成 `alias`)比输出,编译错误也算输出。它建好当天就抓出了
第十二处(`derived_field_ok`),那处是手工那一轮漏掉的。

**语料只覆盖 opacity 允许的操作**。spec §2.7 写着转换只发生在赋值/传参/返回位,不在
表达式内部——`u + 1` 本模块里也是错的。所以算术和 `<` 不在语料里:它们**本来就该**
两种拼法不同。孪生性质管的是 §2.7 承诺的那四样:相等、哈希、序、渲染,加上表示本身。

---

## 12. 家族里最后一个:`hash`(2026-07-28)

`==`(§3)、`cmp`(trait v2 刀 5)、`show`(§6)先后收成「lowering 按类型自身结构展开的
一个普通 Core 函数」。`hash` 一直不是:`prim_relation` 无论主体是什么都发
`CIntrinsic("hash", ..)`。JVM 上它落到 `Object.hashCode`——对生成的 ADT 类就是发射器
直接写成字节码的那个方法;native 过了标量就没有答案。所以 `dawn __emitc selfhost`
的第一堵墙是**元组的哈希**,不是那 62 处 `use java`。

### 12.1 先补语料,后动刀:两条 known-red 活了一天

`scripts/spike-native/hash_key.dawn`。**`.expect` 里写的是数,不是「相等」**——差分只能
证明两个后端一致,而哈希有一种一致证不出来的错法:和自己的 `==` 不一致的哈希,会把两个
相等的键放进不同的桶。所以期望值是**按定义手算的**,不从任何一个后端读出来。

它当场问出两件事。

**一、无载荷构造器的哈希是 JVM 的身份哈希。** `gen_ctor_class` 对 `singleton` 不生成
`hashCode`,于是继承 `Object` 的。实测:同一个 `Origin`,在探针程序里是 `349885916`,
在语料程序里是 `1309552426`。**它不是值的函数**——不同的程序、不同的分配顺序就是不同的数,
第二个后端更无从产出。

**二、标签不参与。** `==` 与 `cmp` 都比构造器序,`hash` 不比。

### 12.2 有两个答案是「选」的,不是「保」的

改这一刀本来的纪律是**数必须和今天逐位相同**——HAMT 的桶位跟着哈希走,数一变,
编译器自己的 Map 迭代序就变,发射顺序跟着变,真回归就藏在一片顺序位移里。

这条纪律在第一件事上直接塌了:身份哈希**不可能**由一个 Core 函数复现。既然保不住,
那就得选对:标签也一并折进去。**不折的代价是可算的**——身份哈希一拿掉,每个类型的
每个空构造器都落到同一个数,这个编译器自己的 `Ty` 和 `Head` 里就有十几个,
它们会挤进 HAMT 的同一个桶。

于是定义是:

```
标量        后端自己的(Float 不在其中:-0.0 == 0.0 为真,没有哈希能同时同意这个和自己)
元组        h = 1;              逐元素 h = 31*h + hash(e)
单构造器    h = 1;              逐字段 h = 31*h + hash(f)   —— 没有标签可分辨
多构造器    h = 1; h = 31*h+tag; 逐字段 h = 31*h + hash(f)
```

**除标签外每个数都还是原来的数**:seed 1、`31*h + part`,就是发射器写的 `hashCode`
和 `java.util.Arrays.hashCode` 做的事。「只在有一个以上构造器时才折标签」也不是为省事——
`struct_eq_body` 和 `struct_cmp_body` 里那句「一个构造器,没有判别式可分歧」是同一条规则。

**32 位收窄写成 mask/flip/subtract 而不是 `(h << 32) >> 32`**:折叠跑在 Dawn 的 64 位
Int 上,末尾收一次和每步收一次结果相同(都是 mod 2³² 的同一套算术),但每个操作数都留在
2³² 以下——不移负数,也没有给 C 的有符号溢出规则留话可说的地方。

### 12.3 展开器会写出没人看的东西

第一版对多构造器无条件建 `isctor` 链。`Head` 是十几个全裸标签,于是十几条臂**逐字相同**,
都是 `31*1 + tag`。改法是「只有带字段的构造器才需要一条臂」——空构造器的答案就是种子,
而种子正是最后那个 `else`。全裸标签的联合因此一条测试都不发。

这不是优化,是**结构展开的默认产物需要被读一遍**:它写得出正确但荒谬的代码,而所有
门禁都会放它过去。

### 12.4 爆炸半径是量出来的

| 门禁 | 结果 |
|---|---|
| `fixpoint` | HEAD 逐字节重建自己 —— 换哈希没让编译器变得不确定 |
| `prev-diff`:site / playground / packages/web / packages/json / calc | **无变化** |
| `prev-diff`:selfhost | 变了 —— 全仓只有编译器自己拿复合值当 Map 键(`Impls = Map[(Int, Head), ImplI]`) |
| `run-diff` / `lsp-diff` / `fmt-diff` | 无变化 —— 包括 `__pkghash` 那个 d1 树哈希 |

**native 顺带补上 `dawn_hash_bytes`。** `Bytes` 是哈希标量(`hash_scalars`),而 C 运行时
从来没给它写过哈希——`scalar_rt` 一路落到 `no_rt`。JVM 那边是 `Arrays.hashCode`,
所以 C 侧照抄那个折叠,元素按**有符号** byte 取,这跟结构哈希是同一个形状。
