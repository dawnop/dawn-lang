# 集合归位：DawnList/DawnMap/DawnSet 的去 Java 方案调研（A/B/C）

> 状态：**调研，未实现**。这是 de-Java 契约的最后一块（[runtime-intrinsics-design.md](runtime-intrinsics-design.md) §7）。
> StdStrings（v0.10.0）、StdBytes/StdIo（v0.11.0）已退役成 emitter 自写的 `dawn/rt/*` 类；手写 Java
> 只剩三个集合容器 `DawnList`/`DawnMap`/`DawnSet`（源在 `kotlin-final` tag，工作树只有 vendored `.class`）
> 加 ASM shim `AdtClassWriter`。本文评估这三个容器怎么处理，给出推荐。相关：
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

## 3. 关键约束：java.util 身份在 JVM 上不可约

去 Java 的第一直觉是"用纯 Dawn 重写"。对集合**不行**,原因分三层,一层比一层硬:

1. **类型即接口。** `desc_of` 把 `TyList/TyMap/TySet` 映射成 `Ljava/util/List/Map/Set;`(`codegen.dawn:57`)——
   在编译器自己的类型系统里,Dawn 集合**就是** JDK 接口,到处如此。
2. **发射的代码直接在 Dawn 集合上调 JDK 接口方法**:for-in(`List.size/get`)、Show(`Map.entrySet`→`iterator`)。
   要求这个值**真的** implements 该接口。
3. **最硬:`==`/hash 就是 `Abstract*` 契约。** `gen_equality` 对引用类型发 `Object.equals`(`emit.dawn:2434`);
   对 map/set 这会派发到 DawnMap/DawnSet 从 `AbstractMap`/`AbstractSet` **继承**来的**结构化、忽略顺序**的
   equals/hashCode(spec §2.2 要求)。**Dawn 对 map/set 的相等与哈希语义,本体就是 JDK `Abstract*` 的契约**,
   不是编译器发射的任何东西。这正是 `extends java.util.Abstract*` 无法绕开的地方。

**互操作(`use java`)反而依赖最窄**:只有 Dawn `List` 能跨边界(→`List`/`Collection`/`Iterable`,发射侧用
`Collections.unmodifiableList` 零拷贝包装,**正因为它已经是 java.util.List**);`maven.dawn` 接收 coursier 的
`java.util.List` 直接 `.size/.get`。**Map/Set 从不跨 FFI 边界**。

> 结论:集合的 java.util 身份**不是缺陷,是 JVM 平台**——每门 JVM 语言(Kotlin/Scala/Clojure)的集合都活在
> java.util 里。**在 JVM 后端上,"集合没有 java.*" 原则上不可能**,与 A/B/C 怎么选无关。能选的只是"这个 JVM
> 实现是 vendored 的 .java,还是 emitter 发的字节码,还是别的"。

## 4. 三个选项

### 选项 A — 加"extends java"codegen 特性,用 Dawn 写 HAMT/窗口逻辑

让 Dawn 的类型声明能 `extends java.util.AbstractMap` 并覆写抽象方法,HAMT 节点写成 Dawn ADT。

- **能达成 equals/hash?** 能——发射的类 extends AbstractMap 就**免费继承**结构化 equals/hashCode(§3 第 3 层自然满足)。
- **代价 1:引入继承。** Dawn **刻意没有继承**(README「没有继承」是立身特性)。即便"窄",extends-java 也是往
  语言表面加一个违背核心决策的东西。
- **代价 2:仍然去不掉 java.*。** HAMT 节点要可变数组(`Node[]` 的 clone/arraycopy、CAS 的 AtomicInteger),
  Dawn 纯不可变模型**没有裸数组**,只能走 `use java` 裸 `Object[]`/`AtomicInteger` FFI。于是 A 把 java 依赖
  **从「.java 里 extends AbstractMap」搬到「.dawn 里 extends-java 特性 + use java 裸数组」——依赖没消失,只是挪位**,
  还多欠一套数组变异 FFI。
- **裁决:否。** 违背"无继承",且纯度收益是幻觉(照样 `use java` 数组)。成本最高、收益最虚。

### 选项 B — 手搓字节码发射(像 Show/Maps 那样)

把三个容器转写进 `codegen.dawn` 的 ASM。注意:B 在**字节码层**发 `extends AbstractMap`(只是 `cw.begin` 的
一个超类名串,Q4 证明管道已具备),**不碰语言的"无继承"**——这是 B 相对 A 的关键优势。

- **DawnList:可行。** 一个 flat 类:`extends AbstractList`、覆写 `get`/`size`、一个 static `concat`(CAS 循环 +
  两段 array-copy)。规模约等于「comparator + 一个稍长 static 方法」,和我刚发的 bytes/io 同量级。**退役 1/3。**
- **DawnMap:不可行(现状下)。** 现在**没有任何 emitter 发射内部类/嵌套类/匿名类,也不用 invokedynamic**——
  每个 `gen_*_class` 只发一个 flat 类。DawnMap 是**类层级**(`$Node`/`$Bitmap`/`$Leaf`/`$Collision` + 虚派发)
  **加两个匿名 entrySet 迭代器类**($1/$1$1)。要发它,得先给 codegen 造出「发射内部/匿名类 + 虚派发层级」
  这套它从没有过的基础设施。**除非把 HAMT 拍平**(节点合成单个带 tag 的类、switch 代替虚派发、entrySet 物化成
  ArrayList 免掉匿名迭代器)——那是把算法重写成不自然的形状,~300+ 行诡诈 ASM,做到逐字节正确风险很高。
- **DawnSet:薄,DawnMap 在就容易。**
- **裁决:仅 List 值得;Map/Set 成本/风险过高。**

### 选项 C — 继续 vendored,但正式归位成"JVM 后端对集合 intrinsic 的实现"

不动代码,只把 `DawnList/Map/Set` **明确记为 JVM 后端对 list/map/set 契约的实现**,留指路牌(源在 kotlin-final、
native 后端实现同一契约的 native 版)。vendoring 机制本身很干净:`vendored_outers` → `rt_class_family` 从
**运行中编译器自己的 classloader** 读 `.class` 字节、逐字节拷进输出;嵌套/匿名类靠 `$` 前缀名谓词自动带走
(加个内部类都不用改 vendoring)。

- **代价:零。** **风险:零。**
- **不达成"工作树无 .java"**:源仍在 tag 归档。但这重新框定了"完整性"焦虑(见 §5)。

## 5. 重新框定:两个目标要分开看

de-Java 这条线其实有两个目标,对集合它们指向不同答案:

- **目标 ①:解锁 native 后端。** 集合**早已在 intrinsic 契约后面**(map_*/set_*/list builtin → Maps/Lists
  助手 → 容器)。JVM 实现是 vendored-Java 还是 emitted-字节码,**对 native 后端零影响**——它无论如何都用 native
  持久集合实现同一份契约。**对目标 ①,C 已完全足够;A/B 对它零贡献。**
- **目标 ②:工作树里没有手写 Java(完整性/名副其实)。** 只有 A/B 能把 .java 挪出归档。但 §3 证明 java.util
  身份在 JVM 上不可约,所以 A/B **都做不到"集合没有 java.\*"**,只能做到"java 逻辑从 .java 换成 .dawn/字节码"。
  而 A 违背无继承、B 只对 List 划算。

**核心判断:vendored 的三个容器不是"未完成的 selfhost",是"JVM 后端的运行时",躲在一份显式契约后面——正如
native 后端将来的 native 集合运行时也不会是「Dawn 语言源码」。**把它们当后端运行时接受,是诚实的,也是
runtime-intrinsics-design §7 早就给的框架(「归位成 JVM 后端对 intrinsic 的实现」)。

## 6. 推荐

**主推 C**:把 DawnList/Map/Set 正式记为 JVM 后端的集合契约实现,写清指路牌,结案。理由:
1. 对唯一的功能目标(native 后端)C 已足够——契约边界已经在,容器在边界后面。
2. A 要引入违背核心立身特性的继承,还去不掉 java 数组,纯度收益是假的。
3. B 只有扁平的 DawnList 划算,而 DawnList 恰恰是最不像"自定义类"的一个(字面量都是 ArrayList,只有 concat
   用到它);为它把可读的 Java 换成不可读的 ASM,依赖(java.util)一分没少。DawnMap 的 HAMT 层级/内部类远超
   codegen 现有能力。

**可选加做(若「工作树无 .java」这条审美足够值钱)**:
- **B-for-List**:单独退役 DawnList(可行、有界),手写 Java 4→3。但我判断低价值(理由同上第 3 条)。
- **C+ 变体**:把三个 `.java` 源**搬回工作树**(如 `runtime/java/`,显式标注 = JVM 后端运行时),build 加一步
  javac。这不用 A/B 的任何代价就解决了"源码只在 tag 归档"的尴尬,代价是重新引入一个 javac 构建依赖(当前
  toolchain 只从种子 jar 构建、无 javac)。若在意"在树里可见/可维护"甚于"零 java 源",这比 A/B 都划算。

**不推荐 A。**

## 7. 结论

集合是 de-Java 里唯一**结构上打不穿**的一块:JVM + 无缝互操作下,`implements java.util.*` 的身份不可约,而
Dawn 无继承使其无法用纯 Dawn 源写。三个选项里,A 用违背立身特性的代价换来假纯度,B 只对最不重要的 DawnList
划算、对 DawnMap 需要 codegen 从没有过的内部类/虚派发基础设施。**正确的动作不是硬去 Java,是承认这三个容器
就是 JVM 后端的运行时、已经躲在 intrinsic 契约后面(选项 C),并把这一点写清楚。** 完整性的名义由「契约显式、
后端实现可换」来兑现,而不是由「工作树里一个 .java 都没有」来兑现。

> 开放的小决策:C 之下要不要顺手做 **B-for-List**(退 1/3、有界)或 **C+**(源回树 + javac)。二者都不是必须,
> 取决于对"树内无 java 源"这条审美的估值。`AdtClassWriter`(ASM shim)是并列的另一块(§11),同属"后端依赖"性质。
