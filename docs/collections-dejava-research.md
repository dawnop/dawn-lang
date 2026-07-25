# 集合归位：DawnList/DawnMap/DawnSet 的去 Java 方案（A/B/C 调研 → D 计划）

> 状态：**A/B/C 调研完成；C 已作为过渡态落地（`vendor.dawn` 指路牌）；本文改写计划，主推 D。**
> 这是 de-Java 契约的最后一块（[runtime-intrinsics-design.md](runtime-intrinsics-design.md) §7）。
> StdStrings（v0.10.0）、StdBytes/StdIo（v0.11.0）已退役成 emitter 自写的 `dawn/rt/*` 类；手写 Java
> 只剩三个集合容器 `DawnList`/`DawnMap`/`DawnSet`（源在 `kotlin-final` tag，工作树只有 vendored `.class`）
> 加 ASM shim `AdtClassWriter`。
>
> **本次改写的由来**：A/B/C 都默认「JVM 上集合的 java.util 身份不可约」（旧 §3）。复核编译器前端后发现，
> 这个「不可约」有一个**没写出来的前提——`==`/hash 是编译器硬编码的**。这个前提是可以拆的，拆了之后
> 「纯 Dawn 写集合、且跨 backend 复用」从原则上不可能，变成一个**有界的语言特性项目**（选项 D）。相关：
> [pure-ffi-design.md](pure-ffi-design.md)、[list-append-quadratic] 的实现背景。

## 1. 这三个类是什么

- **DawnList**（104 行）：`extends java.util.AbstractList implements RandomAccess`。不可变**共享数组窗口**——
  `a[0,size)` 是本版本，相邻版本共享 `a`；用 `AtomicInteger used` + CAS 认领槽位，独占尾部时原地扩展、否则复制。
  唯一自定义方法是 `static concat`（`++` 的底座，O(1) 均摊）；`get`/`size` 是 AbstractList 的覆写。
- **DawnMap**（318 行）：`extends java.util.AbstractMap`。**HAMT**——`abstract Node` + `Leaf`/`Collision`/`Bitmap`
  三个具体子类，`find`/`put`/`remove`/`collect` 虚派发；`seq` 单调序号实现插入序迭代；`entrySet` 返回
  **匿名 AbstractSet + 匿名 Iterator**（编译出 `DawnMap$1`/`DawnMap$1$1`）。自定义方法：`EMPTY`、`assoc`、`without`。
- **DawnSet**（57 行）：`extends java.util.AbstractSet`，薄薄一层委托给 DawnMap（元素→`PRESENT` 标记）。
  自定义方法：`EMPTY`、`conj`、`disj`。

## 2. 现状：两层调用图

集合 builtin **不直接**碰容器，中间隔一层 emitter 自写的 `dawn/rt/Maps`、`dawn/rt/Lists` 助手（全是 flat static）：

```
map_insert(builtin) → INVOKESTATIC dawn/rt/Maps.map_insert → INVOKEVIRTUAL dawn/rt/DawnMap.assoc
```

**助手真正碰到的容器方法（一个替代实现必须复刻的全部自定义表面）**：
- DawnMap：`EMPTY`、`assoc`、`without`
- DawnSet：`EMPTY`、`conj`、`disj`
- DawnList：**只有 `concat`**

其余助手方法（`map_get`/`map_size`/`map_keys`/`map_entries`/`set_has`/list 的 `get`/`range`/`slice`/`sortBy` …）
**只调 `java.util.Map`/`Set`/`List` 接口方法**——靠容器 `implements` 这些接口才成立。

**一个不对称的关键事实**：**list 字面量发射的是 `java/util/ArrayList`,不是 DawnList**（`emit.dawn:1506`）。
Dawn 的 `List` 值平时就是 ArrayList,只有经 `++`/`concat` 才变成 DawnList。所以 DawnList 唯一被用到的
独门方法就是那个 owned-tail `concat`;其它一切都走 `java.util.List` 接口。

## 3. 关键约束的重新诊断：不可约的只有「身份」，而身份不可约的前提是 `==`/hash 硬编码

旧调研把「去 Java」判死，靠的是三层约束一层比一层硬。复核后，前两层是**可机械改动的 codegen 约定**，
只有第三层是真障碍——而第三层的「不可约」有一个**能拆掉的隐藏前提**。

1. **类型即接口（codegen 约定，可改）。** `desc_of` 把 `TyList/TyMap/TySet` 映射成 `Ljava/util/List/Map/Set;`
   （`codegen.dawn:57`）。这是一个描述符选择,不是语言事实——若集合成为 Dawn ADT,`desc_of(TyMap)` 改成
   `Ldawn/rt/DawnMap;`（一个 Dawn 类）即可。面广但机械。
2. **发射的代码在集合上调 JDK 接口方法（走契约，可改）。** for-in（`List.size/get`）、Show（`Map.entrySet`→`iterator`）
   这些点,今天直调 java.util 接口。把它们**路由到集合自己的 Dawn API / intrinsic**——正是我们已经建好的
   `rt_intrinsic_target` 那套机制。有界的重定向工作。
3. **`==`/hash 就是 `Abstract*` 契约（旧调研判为「不可约」——**只在一个前提下成立**）。** `gen_equality` 对引用
   类型发 `Object.equals`（`emit.dawn:2424`）;对 map/set 派发到 DawnMap/DawnSet 从 `AbstractMap`/`AbstractSet`
   **继承**的**结构化、忽略顺序**的 equals/hashCode（spec §2.2）。旧结论:「Dawn 对 map/set 的相等语义本体就是
   JDK Abstract\* 契约,Dawn 无继承无法用纯源表达」。

   **被漏掉的前提:今天 `==` 是硬连线的 `BEq` 运算符、hash 是自动派生的结构 `hashCode`,两者都没有 override 通道。**
   正因为编译器把相等/哈希钉死成「结构化」,而 HAMT 的树形**不是规范形**(同一逻辑 map、插入删除历史不同→树形不同),
   才**不得不**借 AbstractMap 那个「迭代 entry 当集合比」的顺序无关 equals。**「不可约」不可约的是「在 `==`/hash
   硬编码前提下」**——把这个前提拆掉,身份就下沉到 Dawn 层,容器就能用纯 Dawn 表达。

**而拆这个前提的机件,Dawn 已经有了**（复核所得，旧调研未纳入）:
- **位运算已是 surface 语法**:`OpBand/Bor/Bxor/Shl/Shr/Ushr`（`& | ^ << >> >>>`,`parser.dawn`）。HAMT 索引够用,
  只差 popcount——正好当一个新 intrinsic 进 `rt_intrinsic_target` 表。
- **trait + 字典传递机制已在**:`trait Ord[T]`、用户 `impl`（`imp.derived` 区分派生 vs 手写）、`derive`、`[T: Ord]` bound；
  关键的**字典传递** `dict_syms: Map[(TyVar, TraitId), Sym]` + `resolve_witness(cx, trait_id, ty)` → `WitRef`。
  `sort` 就是靠它把元素的 Ord 见证 thread 进去。**Eq/Hash 还没上这条轨,但轨已经铺好。**

> 修正后的结论:集合的 java.util 身份**不是 JVM 平台的铁律,是「`==`/hash 尚未 trait 化」的当前实现的产物**。
> 前两层约束机械可改,第三层靠给 Eq/Hash 补 trait 化(骑 Ord 现成的轨)即可解除。**去 Java 对集合从「原则不可能」
> 变成「一个有界的语言特性项目」。**

## 4. 旧选项 A/B/C：都只是「换一种方式产出 JVM 实现」，java.util 身份不动

这三个是在「身份不可约」前提下的最优解，现记录为背景。**共同局限:全都保留 java.util 身份,对 native 后端零贡献。**

- **选项 A — 加「extends java」codegen 特性,用 Dawn 写 HAMT。** 违背 Dawn 立身的「无继承」,且 HAMT 数组变异仍要
  `use java` 裸 `Object[]`/`AtomicInteger`——java 依赖只是从 .java 挪进 .dawn。**否。**
- **选项 B — 手搓字节码发射(像 Show/Maps)。** DawnList 可行(一个 flat 类);DawnMap 不可行——需要 codegen 从没有过的
  「内部/匿名类 + 虚派发层级」基础设施,或把 HAMT 拍平成 ~300 行诡诈 ASM。**仅 List 划算。**
- **选项 C — 继续 vendored,正式归位成「JVM 后端对集合契约的实现」。** 零代价零风险,**已落地**(`vendor.dawn` 头注释 +
  `vendored_outers` 文档)。它对**功能目标(解锁 native 后端)已完全足够**,但不兑现「工作树无手写 Java」。

（A/B/C 的完整评估见本文档 git 历史 `005d63c` 前的版本。）

## 5. 选项 D（主推）：把 Eq/Hash 提升成 trait，集合纯 Dawn 化，backend 适配自动发生

D 不是「换一种产出 JVM 实现的方式」,是**解除第三层约束本身**:一旦相等/哈希下沉到 Dawn 层,集合就是普通的
Dawn ADT + 函数 + 见证传递,而这三者**现有 lowering 在每个 backend 上都已经会处理**。「适配不同 backend」不再是要
设计的东西——它是 ADT lowering 的既有能力。

### 5.1 三步

**第 1 步(真正的工作量)——Eq / Hash 从「运算符/派生」提升成「可 override 的 trait」,骑 Ord 已铺好的轨:**

```
trait Eq[T]   { fn eq(a: T, b: T) -> Bool }
trait Hash[T] { fn hash(x: T) -> Int }
```

- 每个类型一个**派生默认 impl**,字节码必须与今天 `gen_equality`/`gen_hash_code_method` 产出**逐字节相同**
  （这是最关键的约束,见 §7 风险）;
- `==` 不再直接发 `BEq`,而**dispatch 到 `Eq` 见证**;绝大多数类型命中派生默认,行为不变;
- 允许**用户 override**:`impl Eq for Map[K,V] { eq(a,b) = entries_equal_as_set(a,b) }`、`impl Hash for Map ...`。
  顺序无关身份就此从 AbstractMap **搬进 Dawn 源**。

**第 2 步——Map/Set 携带 key 的 Eq+Hash 字典**,和 `sort` 携带 Ord 见证一样:`Map[K,V]` 隐式带 `[K: Eq + Hash]` bound,
构造/insert/lookup 处 thread K 的见证。机制现成,复用 `resolve_witness`/`dict_syms`。

**第 3 步——集合成为纯 Dawn ADT + 函数 + 见证,backend 适配自动:**
- **后端接口只剩一个原语 `Array[T]`**(new/get/len/`with`)。集合(HAMT/RRB)全是它之上的纯 Dawn ADT,**后端不再实现
  任何 `list_*/map_*/set_*` intrinsic**——换后端 = 实现一个数组类型。`with` 返回新数组、语义纯;可变藏进后端实现
  ——**两个后端都要做「唯一时就地写」**(JVM 用 CAS 水位线 / native 用 Perceus rc==1),见 §9.3。详见 [runtime-intrinsics-design.md](runtime-intrinsics-design.md) §5。
- **迭代靠语言侧 `Iter` trait**(像 Rust `IntoIterator`):`for-in` dispatch 到集合的 Dawn 迭代函数,不走后端 `iter` intrinsic。
- **JVM**:4 个手写节点类 → 编译器发射的 ADT variant 类(和任何 `enum` 同路径)。**全程零 java.util**,一个 Dawn Map
  就是一个 Dawn ADT。§3 前两层的 `desc_of` 重定向 + 调用点路由在此一并做掉。
- **native/LLVM**:**同一份 Dawn 源**,节点 lower 成 tagged struct,`Array[Node]` 走 RC/region buffer。零容器运行时契约。

### 5.2 关键分解：List 和 Map/Set 是两个不同问题

旧调研把三者绑一起谈,其实**身份不可约只是 Map/Set 的问题**:

- **Map/Set**:痛点是**顺序无关身份**(§3 第 3 层)。D 正是这一点的解;HAMT 用**路径复制的持久 ADT**表达
  (immutable `List[Node]` 节点数组,每次 assoc 复制 ≤32 宽的小数组——正是 Clojure 非 transient 路径的做法),
  纯 Dawn 完全可表达,位运算/popcount 齐活。**这是 D 精确解锁的部分。**
- **List**:**根本没有身份问题**——它的相等是有序结构化,正是 `derive` 已经给的。List 的唯一难点是**性能**:
  均摊 O(1) 的 `++` 靠的是可变共享数组 + CAS(见 [list-append-quadratic]),纯 Dawn 无裸可变数组。
  **已定:换成先严格 RB(relaxed 以后可加),两后端共用同一份纯 Dawn 源(见 §5.3、§9.3)**,不走「可变数组 primitive」那条会把
  mutation 塞进语言、且逼 List 永远当 runtime primitive 的路。与 Eq/Hash 无关,是纯性能/表示决策。

### 5.3 List 的实现选型：先严格 RB，两后端统一一份纯 Dawn 源

> **本节已被 §9.3 的实测细化,先读那里。** 要点:决定成败的是后端 `array_with` 做不做「唯一时就地写」
> (差 12 倍),而不是下面理由 2/4 说的那些渐进复杂度;下面理由 3 对 JVM 的乐观估计也已被实测取代。

**决策(2026-07-25):List 的底层从今天的 flat「共享数组窗口 + CAS」(DawnList)换成 **严格 RB**(32 叉 trie +
尾块),relaxed 作为以后可加的节点形态;作为唯一实现,JVM 与 native 后端共用同一份纯 Dawn 源。** 不选
「加可变数组 primitive intrinsic」的原地路线——**但注意 §9.3:`Array.with` 本身必须带唯一性就地写,
否则这条路不成立。**

理由(与前一轮 native 后端讨论一致):

1. **一份源、每个 backend 复用**——这是纯 Dawn 集合的初衷。原地方案要往语言/运行时塞一个「带唯一性原地更新的可变
   数组」primitive,那会**让 List 永远是 runtime primitive、去不掉的 Java/native 那一块**,和 D 的方向相悖。RRB 是纯
   函数式 ADT(节点=持有子节点小数组),和 Map 的 HAMT 同族,**能真正纯 Dawn 化**。
2. **全操作均匀 O(log n)**——不止 append。今天 DawnList 的 `slice`/按下标更新/prepend/`++`两个大 list 都是 O(n) 复制;
   RRB(relaxed 节点)把它们全压到 O(log n),`++` 恰是 Dawn list 的核心操作。
3. **快路径靠后端 RC,不靠语言 mutation**:
   - **native**:Perceus RC 在节点唯一(rc==1)时原地复用 → 线性 `++` 恢复近 O(1) 均摊,最坏仍 O(log n)。两头都要到。
   - **JVM**:无 RC,但**尾节点(≤32 宽)吸收每 32 次里的 31 次 append**,每次只 copy 一个 ≤32 小数组=常数,每 32 次
     才推一次 spine=O(log n)。故 JVM append ≈ **均摊 O(1)(常数因子 ~32)+ 摊薄的 O(log n)/32**,**不是每次 O(log n)**——
     相对现 DawnList 只是常数因子变化,非 log 级退化,且远好于原来的 O(n²)。换来 List 去 Java + 全操作均匀 + 无 per-backend 分叉。
4. **消除 copy-on-branch 悬崖**:结构共享让持久/共享使用不再撞 O(n) 复制(原地方案分叉即 O(n))。

**后端接口:只落到 `Array[T]` 一个原语。** HAMT 与 RRB 都是「小数组组成的树」,朝后端要的只是 `Array` 的
new/get/len/`with`(见 [runtime-intrinsics-design.md](runtime-intrinsics-design.md) §5)。`with` 返回新数组、语义纯,可变藏进
后端实现——**两个后端都必须做「唯一时就地写」**(JVM 用 DawnList 已验证的 CAS 水位线,native 用 Perceus 的
`rc==1`);写成「JVM 一律 copy」是错的,实测差 12 倍(§9.3)。**这是最小接口:换后端 = 实现一个数组类型,
不是 20 个集合 intrinsic。**

**代价(诚实)**:RRB relaxed 平衡实现量大、逻辑微妙(比 flat array 的 ~100 行多得多)。若实测「两个大 list 相 `++`」
罕见,可先落**朴素 32 叉 PersistentVector**(append/get/iterate/slice 同为 O(log n),实现简单不少,唯 big++big 退 O(n))
作台阶,再升级到 relaxed。

## 6. 两个目标，D 同时兑现

- **目标 ①:解锁 native 后端。** C 已足够(契约边界在,容器在边界后)。但 C 让 native 后端**必须另写一份 native 集合
  运行时**;D 让 native 后端**直接复用同一份 Dawn 集合源**——更省、更不易漂移。
- **目标 ②:工作树里没有手写 Java。** 只有 A/B/D 能把 .java 挪出归档,而 A 违背无继承、B 只对 List 划算、**且 A/B 都
  保留 java.util 身份**;**唯有 D 真正消除身份**(Map/Set 变纯 Dawn ADT),两个目标一起兑现。

## 7. 推荐与分阶段计划

**主推 D,分阶段,C 作为已落地的过渡态并存到 D 的 Map/Set 阶段完成为止。**

D 是一个**语言特性项目**——语言侧加三个 trait(**Eq / Hash / Iter**)+ 后端加一个原语(**`Array[T]`**),不是集合重写;
集合退役只是第一个受益者(顺带给用户 `derive Eq` / 自定义 `==` 松绑)。**净效果是把集合从后端契约整族搬进语言层:
后端接口从 ~20 个集合 intrinsic 缩成一个数组类型。** 建议按依赖顺序:

1. **阶段 D0 —— Eq/Hash trait 化(前置,最大风险在此)。** 加 `Eq`/`Hash` 内建 trait + 派生默认;`==`/hash dispatch
   到见证。**验收铁律:对所有现有类型,派生默认产出的字节码与今天逐字节相同**——用 `selfhost-fixpoint` +
   `selfhost-prev-diff` 盯死。这一步不碰集合,先独立发一版稳住。
2. **阶段 D1 —— `Array[T]` 原语 + popcount。** 后端加不可变数组原语(new/get/len/`with`,§5.3);popcount 进
   `rt_intrinsic_target`(JVM→`Integer.bitCount`)。两版种子纪律:先 dormant 发版。
3. **阶段 D2 —— Map/Set 纯 Dawn 化 + `Iter` trait。** HAMT/Set 写成 `Array` 之上的 Dawn ADT + `impl Eq/Hash`;
   加 `Iter` trait 让 `for-in` dispatch 到 Dawn 迭代函数;`desc_of` 重定向 + 调用点路由;退役 DawnMap/DawnSet 两个
   vendored 类,**且删掉 `map_*/set_*` intrinsic**。**手写 Java 4→2。**

   > **前置(2026-07-25 审计补)**:这一行里的 `impl Eq/Hash` 与 `Iter` 主体都是**泛型的**
   > (`Map[K,V]` / `List[T]`),而 trait v1 的 `impl_subject_ok` 只放行具名非泛型类型。
   > **今天这两件一行都写不出来。** 出路不是 D0 的 `WStructural`——那是编译器合成的**结构**关系,
   > 而 HAMT 需要的恰恰是类型自己定义的**非结构**关系;何况 `Array` 的 `==` 是引用同一性且传递,
   > 结构关系走到节点那一格必然退化。故 **trait v2 的最小切片是 D2 的硬前置**,
   > 见 [native-backend-plan §11.4](native-backend-plan.md) 的 S2.1。
4. **阶段 D3 —— List → 先严格 RB(relaxed 以后),两后端统一一份纯 Dawn 源**(已定,见 §5.3/§9.3)。RB 写在同一个 `Array`
   原语上;退掉 DawnList vendored 类、删 `list_*` intrinsic;快路径 native 靠 Perceus RC 原地复用、JVM 靠尾节点吸收
   (均摊 O(1),见 §5.3)。做则手写 Java 4→1(只剩 `AdtClassWriter` ASM shim,属并列的「后端依赖」)。

**风险(诚实清单)**:
- **D0 的爆炸半径**:改 `==` dispatch 动的是编译器里每一处相等比较,派生默认差一个字节就是巨型 Emit-Change。
  这是整个项目成败所在,必须靠逐字节 fixpoint 兜住。
- **性能对等**:字典传递有开销(但 Ord/sort 已在付);持久 HAMT 路径复制比手调 Java 多分配,需基准确认可接受。
- **FFI 边界**:集合不再是 java.util 后,`use java` 返 `java.util.List` 需**显式转换**(java.util ↔ Dawn)。旧 §2 已证
  只有 List 跨 FFI 边界,故有界、局限在 `use java` 几处。
- **List 换 RRB 的 JVM 性能**:见 §5.3,JVM 侧 append 仍是均摊 O(1)(尾节点吸收,常数因子 ~32),非 log 级退化;是 D3
  的专属取舍,不阻塞 D2。

## 8. 结论

旧调研判「集合是 de-Java 唯一结构上打不穿的一块」,判错了前提:打不穿的不是 JVM 平台,是**「`==`/hash 还没
trait 化」的当前实现**。前两层约束机械可改,第三层——真正的身份不可约——**只在 `==`/hash 硬编码时成立**。Dawn
已经有位运算、有 trait + 字典传递(Ord 的轨),缺的只是**让 Eq/Hash 骑上这条轨**。

**正确的动作不是承认集合是不可退役的后端运行时(C 的结论),而是把 Eq/Hash 提升成可 override 的 trait(D),让集合
的身份下沉到 Dawn 层——于是集合成为普通 Dawn ADT,现有 lowering 自动把它带到每个 backend。** C 是诚实的过渡态、
已落地;D 是真正兑现「纯 Dawn 集合 + 跨 backend 复用」的路,且第一步(Eq/Hash trait)本身就是一个独立有价值的语言
特性。完整性的名义,最终由「集合是纯 Dawn 源、每个 backend 自动复用」来兑现。

> 与 D 并列、不受其影响的一块:`AdtClassWriter`(ASM shim,§11 of design doc)——它是 codegen 发字节码的工具,
> 属「JVM 后端依赖」,native 后端换成 native emitter,与集合归位无关。

## 9. 集合 spike 实测(2026-07-25)：结论与本文前八节的判断相反

按「先测,再决定」跑了两组实验。**结果推翻了 §5.2 的分工判断:Map 是安全的那个,List 才是危险的那个。**

### 9.1 实验一：纯 Dawn HAMT vs 手写 Java HAMT(微基准)

用今天的语言写了一个纯 Dawn HAMT(32 叉、路径复制、`(K,V)` 泛型 ADT,节点孩子放在 ≤32 宽的 List 里当
`Array` 的替身),对着 builtin Map 量。正确性自检 0 失败。best-of-5,微秒:

| 形态 | 纯 Dawn | builtin | 倍数 |
|---|---|---|---|
| 插入(Int 键,隔离出纯遍历+重建) | — | — | **~22–28×** |
| 插入(String 键,含未缓存哈希) | — | — | **~17–24×** |
| **查找**(String 键) | — | — | **1.4–1.6×** |
| A 小作用域 5000×20 | 11588 | 1740 | 6.6× |
| B 模块表 4000 | 2964 | 154 | 19.2× |
| C 节点表 100000 | 123579 | 7166 | 17.2× |

**分解**:查找几乎不亏(纯遍历、零分配),**插入慢 ~20× 且全在「重建节点」的分配上**。两个具体原因:
1. `Array.with` 在纯 Dawn 里只能用 `slice ++ [x] ++ slice`(约 3 次分配)近似,Java 是一次 `arraycopy`;
2. **纯 Dawn 没有引用相等**。DawnMap 用 `n == m ? this : new DawnMap(n)`(Java 引用比较)判「子树没变」,
   纯 Dawn 的 `==` 是结构性的(在树上 O(n)),只能改成每层返回一个 `(Node, Bool)` 元组——每层多一次分配。
   若要消掉,需要一个 `ref_eq` 原语。

另一个实测到的既存事实:**Dawn `String` 与 `use java "java.lang.String"` 是不同类型,纯 Dawn 拿不到
`String.hashCode` 的缓存值**,只能每次从码点重算。JVM 缓存它,native 也不会自动有——除非 native 的字符串
表示自己缓存哈希(一个该记下的设计选项)。

### 9.2 实验二：集合变慢 20× 对自举的真实影响(直接模拟,非外推)

把 vendored 的 `DawnMap`/`DawnList` 换成「每次操作内部干 20 遍」的版本(volatile sink 防消除),放在种子 jar
前面的 classpath 上,量同一条编译命令。**这直接模拟了「集合换成纯 Dawn、慢 20×」的结果**——20× 正是 9.1
量到的倍数。对照验证:补丁生效,spike 里 builtin 的 map 操作实测慢 11–13×。

| | 基线 | Map 20× | List 20× |
|---|---|---|---|
| wall(3 趟中位) | 4.93s | **5.43s(1.10×)** | **14.21s(2.88×)** |
| user(3 趟中位) | 13.04s | 14.67s(1.12×) | 24.21s(1.86×) |
| 反推占编译时间 | — | **≈0.5%** | **≈10%** |

> **Map 操作只占编译时间约 0.5%,List 的 `++` 占约 10%——差 19 倍。**

一个副产品发现:第一版 List 扰动(把 `concat` 整个跑 20 遍)让编译**慢到 10 分钟跑不完**,不是 20× 而是灾难性——
因为重复调用会**自己和自己抢 CAS**,后 19 次落到复制路径,累积重新变成 **O(n²)**。这既是实验设计的坑(已改成不碰
`used` 的 O(add) 忙等),也**反证了 owned-tail 优化有多吃重**。

### 9.3 实验三：纯 Dawn 持久向量(严格 RB)——决定性变量是 `Array.with` 的唯一性

9.2 只量到「集合慢 K 倍会怎样」,K 要另外测。把 HAMT 的 20× 套到 List 上是错的:HAMT 插入(哈希+popcount+
逐层路径复制+元组)和 List 追加是完全不同的操作。于是照 9.1 的办法给 List 也写了一个纯 Dawn 版
(`scripts/spike-hamt/vec.dawn`):Clojure 式 PersistentVector = 32 叉 trie + 尾块,正是「严格 RB」。
正确性自检 0 失败;`pure_us` 随 n 线性,确认追加确实 **O(1) 均摊**。

关键在于尾块怎么更新——也就是后端原语 `array_with` 的语义:

| `array_with` 的行为 | 纯 Dawn RB 追加 | 代入 9.2 的占比推算自举 |
|---|---|---|
| **每次复制**(≤32 槽) | **~14×**(10.6/14.0/16.7/17.1、10.8/15.5) | **+129%** |
| **唯一时就地写** | **2.0–2.4×**(1.9/1.9/2.1/2.4、2.0/2.1/2.2/2.3) | **+11%** ✅ |

> **决定性的设计变量既不是「RB vs 平坦」,也不是「纯 Dawn vs 手写」,而是后端的 `Array.with` 做不做
> 「唯一时就地写」。** 差 12 倍,并且直接决定 D3 可不可行。

**而两个后端都做得到**:JVM 上 DawnList 今天就是靠 CAS 水位线做到的(实测该快路径命中 **99.1%**,
见 9.5);native 上 Perceus RC 的 `rc==1` 天然如此,且单线程连 CAS 都不需要,比 JVM 版更简单。

> **D1 落地时的修正(2026-07-25)**:上面这句里的 `Array.with` 应当读作「尾块**追加**」,不是任意位置的
> 替换。水位线只判得了「一格谁都还没见过」,而这正是追加;`with(v, i, x)` 里 `i < len` 的槽位已经交出去了,
> 判「还有谁在读」要引用计数——**JVM 上因此只能复制**。原语于是拆成 `array_push`(有快路径)与
> `array_with`(总是复制)。**这不改结论**:本节量到的 12 倍来自尾块追加(spike 里模拟它的 `push_owned`
> 写的就是 `tail ++ [x]`),整个落在 push 那条路上。完整推演见
> [native-backend-plan.md](native-backend-plan.md) §10。

**尚未测的一项**:随机索引(trie 下降 vs `ArrayList.get`)慢 **8–18×**,且随 n 增长——这部分没有进 9.2 的扰动,
所以那里的推算是下界。但编译器的 list 访问以**顺序遍历**为主(`for x in xs`),顺序遍历应当用**叶子游走的
迭代器**(每元素 O(1) 摊还),不能用 `nth()` 逐个索引去实现——**这是 D3 的一条实现约束,不是性能结论**。

### 9.4 结论：难度与风险是反的，但两个都做得成

| | 语义难度 | 性能风险 |
|---|---|---|
| **Map/Set** | **难**——身份不可约,要 Eq/Hash trait 化(D0,巨型 Emit-Change) | **低**——20× 也只 +10% wall |
| **List** | **易**——有序结构相等,`derive` 就给,无身份问题 | **低,但有条件**——`Array.with` 必须唯一时就地写(+11%);否则 +129% |

**§5.2「List 是独立的、可选的小问题」判得不对**:它确实没有身份问题,但它是**性能上唯一带条件的一块**,
而那个条件落在 `Array` 原语的语义上,必须在 D1 设计 `Array` 时就定死,不能留到 D3。

- **Map/Set(D2)**:性能安全,+10% 自举。难度全在 D0,而 D0 因 native 选了「传字典」已在关键路径上——
  **两条线在 D0 合流,Map 顺势走完。**
- **List(D3)**:**严格 RB 仍然是对的选型**,relaxed 留作以后可加的节点形态。**前提是 D1 的 `Array.with`
  带唯一性就地写**;顺序遍历要用叶子游走迭代器。满足这两条,+11%,可做。
- **`Array.with` 的唯一性因此从「优化」升级为「契约的一部分」**:它是 List 可不可纯 Dawn 化的开关,
  必须写进 runtime-intrinsics-design §5 的原语语义里(JVM 用水位线/CAS,native 用 RC)。

### 9.5 副产品：编译器的 list 用法实测

给 `DawnList.concat` 加计数器,量一次完整编译:

```
fast=76,357,600   copy=705,534   → 复制路径仅 0.92%
追加元素 77.4M     复制元素 89.2M  → 平均每次复制 126 个元素
```

**一次编译 7,700 万次 list 追加**(这才是 `++` 占 10% 的原因——不是每次慢,是次数极多),
**owned-tail 快路径命中 99.1%**。这既解释了为什么 9.3 的「唯一时就地写」这么关键(99% 的追加都能吃到),
也说明 O(n) 复制悬崖在真实负载里基本不出现(分叉只占 0.9%,平均才 126 个元素)。

> spike 源码:`scripts/spike-hamt/`(`hamt.dawn` 纯 Dawn HAMT、`vec.dawn` 纯 Dawn 持久向量),
> 扰动与计数实验的补丁 Java 与流程记在同目录 README。
