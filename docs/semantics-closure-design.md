# 语义收口设计（S1）

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

### 2.1 `Float` 的 `Eq` 与 `Ord` 刻意不同

实测:

```
nz = 0.0 * -1.0        # 真的 -0.0,1.0/nz = -Infinity
nz == z                true      # 运算符,也是 [T: Eq] 的答案
cmp(nz, z)             -1        # [T: Ord] 的字典
nan == nan             false
cmp(nan, nan)          0
```

`cmp(a,b) == 0` 与 `a == b` 在 `NaN` 和 `±0.0` 上给相反答案。**这不是缺陷。**
spec §4.3 明写:`==`/`<` 是 IEEE 比较(NaN 与任何值含自身皆 false、`-0.0 == 0.0` 为 true),
而 `Ord.cmp` 是**全序**(Java `Double.compare` 语义:NaN 大于一切、`-0.0 < 0.0`),
两者「**刻意不同**(同 Java `compare` 与 Rust)」。

我在设计 S1.5 时把它当成第八条缺陷,查 spec 才发现是白纸黑字的裁决。**记在这儿是为了
让下一个人不必再撞一次**:`eq_scalars()` 和 Ord 的标量清单差别只有一部分是能力
(Bool/Bytes/Cursor 没有 `<`),另一部分是语义,合并会静默抹掉后者。

### 2.2 容器自身的相等留到 D2/D3

`dawn/rt/Lists` / `Maps` / `Sets` 是 **vendored 的 `.class`**(`vendor.dawn` 从 classpath 读,
源在归档的 `kotlin-final`),本仓库改不动。所以 `List[Bytes] == List[Bytes]` 这一种
今天没有任何修法。§3 决策 3 会把洞收敛到**只剩这一种**。

### 2.3 `Bytes` 进 Map/Set 键的硬禁不撤

即使 `hash` 内建对 `Bytes` 是内容哈希,容器用的仍是 `byte[]` 自带的 `hashCode`。
禁令(`checker.dawn:340` `invalid_key_part`)在 D2/D3 之前必须留着。要改的是**诊断措辞**——
「hashes by identity」得说清是哪条路。

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

### 决策 3 — JVM 类的 `equals`/`hashCode` **改成转发**到合成函数

这是最容易做错的一步,也是**不能与决策 1 分两次做**的原因。

Dawn 的 `Map`/`Set`/`List` 是 vendored 的 Java 容器,比较键用的是 `key.equals()`。
若 `==` 改走合成函数、而容器仍走 `gen_equals_method` 生成的 `equals`,
**Dawn 的 `==` 与 Map 的键相等就变成两个关系**——比今天的一致地错更糟。

故 `gen_equals_method` / `gen_hash_code_method` / 元组类的 `equals` 全部改成转发。
先例现成:`gen_forwarding_equals`(`codegen.dawn:2663`)就是给 `impl Eq` 用的同一手法。
于是定义仍是一份,容器自动跟随。

代价:`equals` 多一层静态调用。**收益**:`Bytes` 在 record / ctor / Option / 元组里
自动变成内容相等,连带**装在容器里的 ADT** 也对了,剩下的洞收敛成一种——容器直接装裸
`Bytes`(`List[Bytes]`)。那一种写进 `known-red.txt` 的说明,等 D2/D3。

### 决策 4 — `interp.value_eq` 也调同一份

comptime 解释器执行的是 Core,合成函数就在 Core 里,`value_eq` 对 ADT 的手写遍历
(#6)因此可以整段删掉,只留标量。这条顺带把 `const_fold` 那类「两个后端折的是同一份
`interp.dawn`,所以在错答案上达成一致」的风险面缩小。

### 决策 5 — `CEq` 收窄成「后端原生标量关系」并写进 `core.dawn` 的注释

展开器落地后,`CBinary(CEq, ..)` 的合法左值类型收窄成标量(含 `String`/`Bytes`)。
这一条必须**写进节点定义的注释**并由 lowering 断言,否则下一个人照旧会在 ADT 上发 `CEq`,
而两个后端照旧会各自发明答案——这次没有语料能发现,因为语料只测已知的类型。

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

改法:JVM 也读表。`emit_module` 不再需要 `impl_table` 参数,Core 才**真的**后端无关。
这一步的门禁是 S0.4 的 Core golden——它是今天唯一看得见 `CModule.dicts` 的东西。

## 6. S1.4:`Show` 成为第四个 prelude trait

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

plan 的一句话是「标量能力表六合一」。逐个看过之后,这句话**不准确**——六张表回答的
不是同一个问题:

| 表 | 回答的问题 | 处置 |
|---|---|---|
| `eq_scalars()`(`types.dawn:536`) | 哪些标量的 Eq/Hash 后端原生实现 | **拆**:见下 |
| `prelude_impls()` 里 Ord 的 `[Int,Float,String]` | 哪些标量有序 | 保留(§2.1) |
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
| 1 | S1.5 的「拆」:`Eq`/`Hash` 的 prelude 清单分开 | `Hash[Float]`/`Hash[Bytes]` 解不出 | 既有 164 测 + `dict_forward` |
| 2 | S1.6 收窄 + S1.2 展开器 + 决策 3 的转发(**一批**) | `eq_adt:native`/`eq_adt:diff`/`eq_bytes:jvm` 三行删除 | Core golden 重录 + `Emit-Change` |
| 3 | S1.3 字典表 | `dict_forward:cc` 删除 | Core golden 是唯一看得见它的门 |
| 4 | S1.4 `Show` 成 trait | `show_derive:emitc`/`const_fold:jvm` 删除 | 差分 harness 全绿 |
| 5 | S1.5 的「合」+ `invalid_key_part` 改走 bound | `impl_subject_ok` 与 prelude 同一份清单 | 既有测试 |
| 6 | S1.1 intrinsic 身份 | 四份手抄名单消失 | 无红线,靠 golden |

**第 2 步是唯一不可再拆的一批**:决策 1 与决策 3 之间的任何中间状态都是「`==` 与
Map 键相等是两个关系」,那比今天更糟。其余各步之间都可以停。

每步都要过:`dawn fmt --check`、`dawn test selfhost`、fixpoint `B == C`、
`spike-native/run.sh`、`array-contract`、`selfhost-core-diff.sh`、N vs N−1 差分
(改字节码的必须带 `Emit-Change:`)。

## 10. 风险

- **第 2 步的字节码面很大**。每个被比较的类型多一个合成函数,`equals` 多一层转发。
  自举比值(`scripts/selfhost-bench.sh`,今天 1.115)是这一步唯一的量,做完对一次;
  若明显退化,先看是不是每个 ADT 都合成了(决策 2 没落实)。
- **`Emit-Change` 会连着好几步**。N vs N−1 差分要求逐条声明,不要攒到最后一起写。
- **种子纪律**:S1 全程不得让 N−1 的编译器编不动 HEAD 的 `selfhost/src`。展开器是
  编译器**自己**也要用的东西(编译器里到处是 ADT 比较),所以第 2 步是自举压力最大的一步。
- **`known-red.txt` 是双向 ratchet**:每步修好的那几行必须同批删掉,漏删会红。
