# 运行时 intrinsic 契约：去 Java 与后端可移植的统一重构

> 状态：**规划中,未实现**。本文把两个看似独立的诉求——① 去掉编译器里手写的 Java 运行时代码、
> ② 将来能接一个非 JVM(如 LLVM/native)后端——收敛成**同一件事**:在语言核心与后端之间立一层
> **显式的运行时 intrinsic 契约**,把所有 `java.*` 关进 JVM 后端对该契约的实现里。
> 相关:[sourceview-design.md](sourceview-design.md)(切片器收敛,同类"把实现细节收口"的重构)、
> [spec.md](spec.md)(语言语义)、[bootstrap.md](bootstrap.md)(种子/两阶段)。

## 1. 背景:两个诉求指向同一个重构

**诉求 A —— 去掉手写 Java。** 当前编译器带 7 个手写 Java 文件(源在 `kotlin-final` tag,工作树只有
vendored `.class`):`DawnList/DawnMap/DawnSet`(不可变集合,~479 行)、`StdStrings/StdBytes/StdIo`
(std 的静态方法substrate,~462 行)、`AdtClassWriter`(ASM 的栈帧 shim,115 行)。selfhost 已收口,
但"核心数据结构源码归档在 tag、树里只剩二进制"这件事,让 selfhost **不算名副其实地完整**。

**诉求 B —— 将来接 LLVM/native 后端。** Dawn 现在只发射 JVM 字节码;GraalVM native-image 给的是
AOT 编译的**同一套 JVM 语义**,不是独立后端。真正的 native 后端意味着没有 JVM、没有 `java.lang`、
没有 `java.util`。

这两件事**表面无关,内里同一**:阻碍 B 的,恰恰是 A 里那些"语言核心直接说 `java.*`"的地方。
把 A 做对的方向,就是 B 的地基。做错的方向(见 §6),会让 A 完成但 B 更难。

## 2. 现状:java.* 泄漏在哪

| 泄漏点 | 现状 | 后端无关? |
|---|---|---|
| `List[T]`/`Map`/`Set` 的 wire 类型 | codegen `TyList → Ljava/util/List;` 等 | ❌ 焊死 java.util |
| 不可变集合实现 | `dawn/rt/DawnList/Map/Set` extends `java.util.Abstract*` | ❌ |
| std 字符串/字节/IO | `std/str.dawn` 写 `unsafe_pure { StdStrings.len(s) }`,`use java "dawn.rt.StdStrings"` | ❌ std 源直接点名 JVM 类 |
| 码点操作 | `code_points`/`from_code_points` 是**编译器内建**(语言命名、后端发射) | ✅ **这是对的雏形** |
| 部分 rt 类 | `Show/Lists/Maps/Strings/Tuple/Fn/Unit/PanicError` 由 `codegen.dawn` 发射字节码 | ⚠️ 后端本地实现,但契约隐式 |

**关键观察**:`code_points` 已经是理想模型——语言层命名一个抽象操作,JVM 后端负责发射它的实现。
问题是这套模型**只覆盖了零星几个内建**,而字符串/集合/IO 的大头要么直接 `use java`、要么是 vendored
Java 类。**要做的是把这个模型长全。**

## 3. 核心洞见

1. **前端天生后端无关,且已 selfhost。** lexer/parser/checker/comptime 解释器与目标平台无关。
   接 LLVM = **新 codegen + native 运行时 + native FFI**,不是新编译器。这块是白拿的杠杆。
2. **`List[T]` 是 java.util.List 是 JVM 后端细节,不是语言承诺。** 语言层 `List[T]` 是抽象类型;
   LLVM 后端会把它 lower 成 native 结构。那个"绑 java.util"的纠结**不跟到 LLVM**——它后端本地。
3. **但现在它泄漏进了 std。** `std/str.dawn` 直接说 `java.lang.String`,集合就是 `java.util`。
   这层泄漏才是接 LLVM 的真正障碍——不是编译器,是语言核心里散落的 `java.*`。
4. **tast 已经是七成后端无关的 IR。** checker 把语义解析(trait 字典 `WitRef`/`dict_syms`、
   ADT 布局 `XCtor.slots`、类型槽 `syms`、`ord` witness)烘进了 tast;真正 JVM-only 的 IR 节点
   只有 `TJavaCall`。**接第二个后端不是「新写一个编译器」,是「共享 tast + 把三处漏进 emit 的
   lowering 收回」**——这条纠正了「新 codegen = 一整块从零 lowering」的误判,详见 §8。

## 4. 目标架构:五层,中间立一层 intrinsic 契约

```
① 语言核心(类型/语义)          ← 后端无关(已经是)
──────────────────────────────
② 运行时 intrinsic 契约          ← 一小组抽象原语,语言命名、后端各自实现
   Array[T](new/get/len/with)    (集合全靠它:Map/Set=HAMT、List=RRB,皆纯 Dawn)
   + str 核心(code_points…)
   + bytes_* + io_* + panic + popcount(可选)
──────────────────────────────
③ std 库(Dawn 写)              ← 只用 intrinsic + Dawn,不碰 java.*  → 换后端免费
   集合(list/map/set)在这一层,纯 Dawn ADT over Array;迭代靠语言侧 Iter trait
──────────────────────────────
④ 后端 codegen + 运行时          ← JVM:intrinsic → java.util/String + dawn/rt 类
                                  LLVM:intrinsic → native 实现
──────────────────────────────
⑤ FFI                           ← use java(JVM 限定)/ use c(LLVM 限定),本就不可移植
```

**这层 intrinsic 契约是整个设计的脊椎。** 它是一份"语言假设运行时提供的最小原语集";每个后端
实现这份契约;std 只写在契约之上。GHC 的 primops、Rust 的 `core`/lang-items、Go 的 runtime 包
都是这个套路。

## 5. intrinsic 契约要覆盖什么(初版清单)

按现有 Std*/rt 类的表面反推,契约大致是:

- **str**:`len`(码点)、`slice`(码点索引)、`concat`、`code_points`/`from_code_points`(已有)、
  `contains/starts_with/ends_with/index_of`、大小写、`trim`、cursor 家族(Dawn Cursor 编码)、`reverse`。
- **bytes**:`utf8`(编码)、`decode`、`len`、`at`、`slice`、`index_of`。≈「字节版 Array」,已接近最小原语。
- **集合(list/map/set)→ 塌成一个原语 `Array[T]`**。**不再有 `list_*/map_*/set_*` intrinsic**——集合是 `Array` 之上的
  **纯 Dawn ADT**(Map/Set=HAMT,List=严格 RB,relaxed 以后可加;见 collections-dejava-research §5.3/§9.3)。后端只需实现
  这一个不可变数组类型:
  - `array_new() -> Array[T]` / `array_get(Array[T], Int) -> T` / `array_len(Array[T]) -> Int`
  - `array_push(Array[T], T) -> Array[T]`(追加一格)/ `array_with(Array[T], Int, T) -> Array[T]`(替换一格)
  - 加一个 `popcount`(HAMT bitmap;可纯 Dawn 循环,故可选)。
  **所有「可变」藏进后端对这两个写操作的实现**。语言侧全程纯,mutation 不越过契约——DawnList 的
  「可变数组+CAS 独占检测」由此降级成后端对一个纯原语的私有实现细节。
  > ⚠️ **「唯一时就地写」是契约的一部分,不是可选优化**(实测,collections-dejava-research §9.3):
  > 后端若每次都复制,纯 Dawn List 慢 ~14× → 自举 +129%;若唯一时就地写,只慢 ~2.1× → 自举 +11%。**差 12 倍,
  > 直接决定 List 能不能纯 Dawn 化。** 故 `Array` 的语义必须写成
  > 「**纯值语义 + 唯一时就地实现**」,而不能只写「返回新数组」。
  >
  > **但两个后端能就地的范围不同(D1 落地时发现,native-backend-plan §10.1)。** `array_push` 写的是
  > 一格从没交出去过的存储,水位线就够判断——JVM 用 DawnList 已验证的 CAS(实测快路径命中 99.1%)。
  > `array_with` 写的槽位**已经交给这个版本、也可能交给了别人**,判断「还有谁在读」要的是引用计数,
  > 不是水位线:**JVM 上因此只能复制**,native 上 Perceus 的 `rc==1` 才补得上(单线程,连 CAS 都不需要)。
  > 这就是原语从 4 个变成 5 个、且 `array_new` 不再预填的原因——预填会让水位线一上来就顶满,
  > 快路径永远进不去。12 倍整个落在 push 那条路上,所以结论不变。
- **io**:`print`/`println`、**`eprint`/`eprintln`**、`read_line`、`read_file`/`write_file`、`is_dir`、**`exists`**、
  **`mkdirs`**、`list_names`、**`exit`**。**不可约的效果边界**,小契约保留。
  > **加粗五项是 2026-07-28 补的,判据是「命令行程序在任何后端上都要它」**。编译器今天走 `use java` 拿这五样;
  > 其中 stderr 最尖锐——`System.err` 是**静态字段**,而 `use java` 只到方法(spec §9.1),
  > 于是 `errio.dawn` 整个模块的存在理由就是用 method handle 绕过去。**stdout 在契约里而 stderr 不在,是意外不是决定**。
  > `exit` 取 `Unit` 不取 `Never`:它映射到 `System.exit`(JVM 上是 void),而 Never 要两个 emitter
  > 都停止把调用当作会落下来——那套机制只有 `panic` 需要。
  > **没进来的**:`getenv`/`getProperty`(只被包管理和 JVM classpath 用)、临时文件(可在 mkdirs 之上搭)、
  > 二进制文件读写(只被 JVM 后端和包管理用)——都不在 native 编译器的关键路径上,不为不需要的东西扩契约。
  >
  > **上面那句在一天后被自己推翻(2026-07-28),推翻它的是一个裁决而不是一个发现**:门控形式定为
  > **两个 main 共享前端**(不引入语言级条件编译)。这句话重新划了「关键路径」——**包管理是目标无关的**
  > (按 url+hash 取 Dawn 源码包,和发射什么后端无关),所以它必须跟着 native main 走;真正留在 JVM main 的
  > 是「启一个 JVM 跑刚发射出来的 class」那部分。于是 `getenv` / 二进制读写 / 临时目录**成了**关键路径。
  > 又补九项:`cwd`、`getenv`、`read_bytes`/`write_bytes`、`delete`、`rename`、`temp_dir`、`is_symlink`、
  > `read_stdin`。仍然按同一条判据挑——每一项在编译器里都有一个今天走 `use java` 的调用点;
  > **仍然没进来的**是 classpath 属性、进程派生、`canExecute`,它们只为启动 JVM 而存在。
  >
  > `read_stdin` 是 `eprintln` 的同一个故事:`System.in` 也是静态字段,所以 LSP 读消息帧同样绕了 method handle。
  > **通道不是 method handle。** `rename` 取 `rename(2)` 的语义(同一文件系统内原子、否则失败),
  > 因为调用方在做「下载、校验、按内容哈希发布」——更弱的语义不成立;`temp_dir` 收一个 parent 参数正是为了这个:
  > 暂存目录必须和目的地同盘,原子才谈得上。
- **控制**:`panic`、效果系统的 IO 边界。

> 契约的**边界画在哪**是核心决策(§8)。**集合已给结论=细到极致**:整族集合在后端边界上只剩 `Array[T]` 一个原语
> (4 个操作),换后端 = 实现一个数组类型,而非重写 ~20 个集合 intrinsic。**str 是唯一不能塌成一个原语的**——Unicode +
> native 表示(UTF-8 vs UTF-16,§8 开放决策)使然,故保持画细:`code_points`/`from_code_points` + 少数性能敏感项
> (如 `str_len` 直给、不走物化)保留粗 intrinsic,其余纯 Dawn 拼。
>
> **迭代不进后端契约**:集合成纯 ADT 后,`for-in` 靠一个 **`Iter` trait**(语言侧,像 Rust `IntoIterator`)dispatch 到集合的
> Dawn 迭代函数,而非后端 `iter` intrinsic。于是「迭代」也从后端接口移到语言 trait + Dawn 源——同样朝「后端接口更小」走。
>
> **更正(2026-07-27,实测)**:结论(迭代不进后端契约)成立,手段改了——不用 trait,
> lowering 直接发对 `std/list` 游标函数的具名调用。见 [`trait-v2-design.md`](trait-v2-design.md) §7。

## 6. de-Java 的正确方向 vs 错误方向(关键决策记录)

**错误方向**:把 `StdStrings` 溶进 `std/str.dawn`、直接 FFI 调 `java.lang.String`。
——对"没有手写 Java"达标,但把 `java.lang.String` 从一个 Java 类**搬进了 std 源码**,std 反而更
JVM-锁死。LLVM 后端一看 std 里全是 `java.lang.String.codePointCount`,傻眼。

**正确方向**:把 `StdStrings` 的**逻辑**变成"JVM 后端对 `str_*` intrinsic 的实现",`std/str.dawn`
改写成 over-intrinsic(不点名任何 `java.*`)。于是同一份力气:std 变可移植(诉求 B),手写 Java 类
被后端实现吸收(诉求 A)。

> **这是本文最重要的一条:去 Java 要朝 intrinsic 契约去,不朝内联 java FFI 去。** 前者一份力气两处用,
> 后者只满足诉求 A、还加深了对 JVM 的耦合。

## 7. 那三个集合:身份不可约的前提可拆——现主推 D(纯 Dawn 化)

> **本节结论已更新**。早先判「JVM 上 `implements java.util.*` 不可约、集合只能归位成后端 intrinsic 实现(C)」。
> 复核前端后发现「不可约」有一个**能拆的隐藏前提——`==`/hash 是编译器硬编码的**。完整推演见
> [collections-dejava-research.md](collections-dejava-research.md)(A/B/C 调研 → **D 计划**)。以下为修正后的判断。

**Map/Set 的身份不可约,只在 `==`/hash 硬编码时成立。** 今天 `==` 是硬连线 `BEq`、hash 是自动派生结构 hashCode,
无 override 通道;正因钉死成「结构化」而 HAMT 树形非规范形,才不得不借 `AbstractMap` 的顺序无关 equals。Dawn
**已有** trait + 字典传递(Ord 的轨:`dict_syms`/`resolve_witness`)和位运算 surface 语法——缺的只是让 **Eq/Hash
骑上这条轨**。一旦相等下沉到 Dawn 层,Map/Set 就能写成**路径复制的持久 Dawn ADT + `impl Eq/Hash`**,身份真正消除。

因此集合去 Java 的正解是 **D:把 Eq/Hash 提升成可 override 的 trait,集合纯 Dawn 化**——而非归位成不可退役的后端
运行时(C)。分工:

- **Map/Set**:身份是唯一障碍,D 精确解锁(HAMT 用 immutable `List[Node]` 路径复制,位运算/popcount 齐活)。
- **List**:无身份问题(有序结构相等即 `derive` 所给);唯一难点是均摊 O(1) `++` 的可变数组 + CAS——独立性能取舍
  (可变数组 intrinsic 或换树结构),与 Eq/Hash 无关。
- **两个后端一份源**:集合成普通 Dawn ADT 后,现有 ADT/函数/见证 lowering 自动带到 JVM 与 LLVM,native 后端**直接
  复用同一份 Dawn 集合源**,不必另写 native 集合运行时。

- **过渡态(已落地)**:C——`DawnList/Map/Set`(extends `java.util.Abstract*`)作为 JVM 后端当前实现,`vendor.dawn`
  已留指路牌。C 保留到 D 的 Map/Set 阶段完成为止。
- **路线**:见 collections-dejava-research §7 分阶段(D0 Eq/Hash trait 化 → D1 **`Array[T]` 原语**+popcount → D2 Map/Set
  纯 Dawn 化 + `Iter` trait,4→2 → D3 List→**先严格 RB**(relaxed 以后可加),两后端统一一份纯 Dawn 源)。**语言侧新增 Eq/Hash/Iter
  三 trait,后端侧新增 `Array` 一原语;净效果=集合从后端契约整族搬进语言层(~20 intrinsic → 一个数组类型)。最大
  风险在 D0:改 `==` dispatch 是巨型 Emit-Change,派生默认须逐字节等价。**
  > **两处已被实测推翻(2026-07-25)**:①D0 的「巨型 Emit-Change」不成立——见证让后端自己挑物化方式,
  > 现有语料**零 Emit-Change**([native-backend-plan §9.2](native-backend-plan.md));②真正的最大风险在
  > **D2 之前**:`impl Eq/Hash[Map[K,V]]` 与 `impl Iter[List[T]]` 的主体是泛型的,trait v1 写不出来,
  > 需要先做 trait v2 的最小切片(同文 §11.4 的 S2.1)。
- **List 的表示已定:先严格 RB(32 叉 trie + 尾块),relaxed 作以后可加的节点形态**(2026-07-25,collections-dejava-research §5.3/§9.3):不走「可变数组 primitive」原地
  路线(那会让 List 永远是 runtime primitive、与纯 Dawn 相悖)。RB 是纯函数式 ADT、和 HAMT 同族可纯 Dawn 化。
  **成败条件已实测**(§5 的 `array_with` 警示框、collections-dejava-research §9.3):纯 Dawn RB 的追加相对今天的
  DawnList,在 `array_with` 每次复制时慢 ~14×(自举 +129%)、在唯一时就地写时只慢 ~2.1×(自举 +11%)。故
  **`array_with` 的唯一性是前置条件,必须在 D1 设计 `Array` 时定死**;另 `for-in` 要用叶子游走迭代器实现,
  不能用 `nth()` 逐个索引(随机索引实测慢 8–18× 且随 n 增长)。

语言核心与 std **永远不点名 java.util**——只用 list/map/set intrinsic。D 完成后,这个 intrinsic 契约背后在 JVM 上
就是**纯 Dawn 集合源**(而非 vendored Java),LLVM 后端复用同一份源。

## 8. LLVM 后端具体要什么

- **新 codegen——但不是从零。** 关键发现(2026-07-24 核实 codegen 实际形状):**tast 已经是七成
  后端无关的 IR**。checker 把后端无关的语义解析烘进了 tast 槽位——trait 派发方案(`WitRef`+`dict_syms`,
  字典传递、非 JVM 接口)、构造器布局(`XCtor.slots`)、类型信息(`syms`)、`ord` witness;唯一真正
  JVM-only 的 IR 节点是 `TJavaCall`。第二个后端直接吃这些。

  **障碍不是「新写 codegen」,是三处 lowering 漏过了 tast、卡死在 `emit.dawn`(3568 行)那趟树遍历里**
  ——正是后端 #2 会被迫重写一遍的东西:

  | 泄漏的 lowering | 现状(entanglement) | 后端 #2 的重写代价 |
  |---|---|---|
  | **intrinsic 语义** | ~~三份不一致~~ → emit 已收口(Move 1 增量 1):string/list/map/io 的 (class, method) 归入 `emit.dawn` 的 `rt_intrinsic_target` 表、走一条 INVOKESTATIC 臂(descriptor=`method_desc(签名)`、装箱=`adapt_to`);`types.dawn` 签名表由它复用。**残余**:`interp.dawn` 仍反射调 `dawn.rt.*`(unicode 原语)| 56 个 builtin 语义要重发一遍;native 自举时 interp 的反射求值**根本没法用** |
  | **结构化控制流 + 语法糖** | `for`/`while`/`match`/`?`/`!`/字符串插值以 tast 节点存活,到 `emit.dawn:764,1026,1456` 才内联 lower 成字节码 | match 编译(决策树)是皇冠明珠,**不想写两遍** |
  | **装箱 / 擦除** | 泛型擦除到 `Object`;装箱决策 `adapt_to/adapt_from`(`emit.dawn:328`)在每个调用点重算「槽是不是 TyVar → 装箱」,没物化成 IR 节点 | Rank 1 最烂的耦合,散在每个 arg/return 点 |

  **策略:后提取,不前设计**(见 §11)。不对着唯一一个 JVM 后端设计「中立」Core IR(必然把 JVM-ism——
  2 槽 long、装箱模型、INVOKEINTERFACE——烘进「中立」层还自称中立,最经典的错误),也不先写 LLVM emitter
  再抽公共层(等于 lower 逻辑写两遍才发现 IR)。而是把上述三处**可证明中立**的 lowering 从 emit 抽成
  tast→tast 的 pass,**只在 JVM 上做、fixpoint 验证字节码逐字节相同**(output-preserving = 单次发布、
  非 Emit-Change,不碰种子纪律)。抽完后 `emit.dawn` 残余逼近「Core IR → 字节码编码」,真正的 Core IR
  边界**被减法减出来**、且已被「产出逐字节相同的 JVM 输出」验证过中立。

  三步按「单在 JVM 上的独立收益」排:
  1. **Move 1 — intrinsic 语义表(先做)**:消灭 types/emit/interp 三份分歧,给 native 自举需要的
     **非反射权威语义源**,同时**就是本文 §10 步骤 1「契约显式化」**——一份力气推两条接缝。
     **增量 1 已落地**(`2532c2b`):`gen_builtin_call` 的 ~15 条手写字节码臂收成 `rt_intrinsic_target`
     表 + 一条臂,`gen_map_call` 折入;纯 output-preserving(fixpoint B==C、语料逐字节相同、非
     Emit-Change)。**表 = 契约的 string/list/map/io 半边**。残余(可选):interp 的 `param_cls`
     从签名派生,消掉最后一处机械重复;真去反射化属后端阶段(native runtime 实现契约)。
  2. **Move 2 — 控制流/match lowering pass**:开始 scope 后端 #2 时做;match 编译单独抽出可独立测。
  3. **Move 3 — 显式 box/unbox 节点**:推迟到后端 #2 逼你面对表示问题时;Perceus RC 正好是
     **只有 native 后端跑**的 core-IR→core-IR pass、需要所有权/装箱显式化,那时 Move 3 自然到位。

  `TJavaCall` 保持 JVM-only(后端 #2 直接报错,与 `use c` 对称);闭包(indy/LMF,`emit.dawn:1955`)
  只 ~8 个函数、localized,重写便宜,不进这轮。
- **native 运行时**(JVM 白送、native 要自造):
  - 持久集合:Map/Set=HAMT,**List=严格 RB(relaxed 以后)**(已定,§7);字符串(UTF-8 还是 UTF-16 的 native 表示?决策项)。
  - **内存管理**:JVM 有 GC,native 没有。**Dawn 的纯性是利好**——数据不可变、无可变别名,持久结构是
    无环 DAG → **引用计数就够**(不必防环),或 region/arena 更省。不一定要上完整 tracing GC。
  - `panic`/效果 IO 的 native 实现(unwind 或返回码)。
- **native FFI**(`use c`/extern)替 `use java`。
- **staging**:可先让 JVM-hosted 编译器**交叉发射** LLVM 给用户程序;native 自举(编译器把自己编成
  native)是更远的里程碑。

## 9. FFI 的分裂(诚实接受)

`use java` 是 JVM 限定,`use c` 将是 LLVM 限定——**FFI 本质不可移植**。用了 `use java` 的程序
(backend-dawn 全家:sqlite-jdbc/jBCrypt……)就是 JVM-only,这没问题、也很诚实。可移植的是**语言核心
+ std + 只用 intrinsic 的纯 Dawn 程序**;碰了平台 FFI 的部分天然绑定该平台。

## 10. 分期计划

1. **契约显式化(地基)**:把隐式、泄漏的 intrinsic 集合**写成一份明确清单**(§5),定边界(§8 决策)。
   这是 LLVM 的地基,也把 de-Java 引到对的方向。
2. **JVM 后端实现该契约**:`StdStrings/StdBytes/StdIo` 的逻辑归位成 JVM 对 str/bytes/io intrinsic 的
   实现(codegen 发射或 Dawn-over-低层内建);集合按 §7 归位。删对应手写 Java 源/vendor 条目。
3. **std 重写为 over-intrinsic**:`std/str` 等不再 `use java`,只走 intrinsic。
4. **【将来】LLVM 后端** = 新 codegen + native 运行时,实现同一契约。
5. **【更远】native 自举**:先交叉发射,后自举。

**验证 / 两阶段**:每步过五件对拍 + fixpoint;动 emit 的部分走"发布 → cmp B C → bump `seed-release.txt`"、
提交写 `Emit-Change:`。契约与 std 改动多为单阶段安全,codegen 发射改动是 Emit-Change。

## 11. 开放决策

- **~~中间层策略:前设计 Core IR vs 后提取~~ → 已定:后提取**(2026-07-24)。tast 已是七成中立 IR;把
  intrinsic 语义 / 控制流+match / 装箱这三处漏进 emit 的 lowering 抽成 output-preserving 的 tast→tast
  pass,让真正的 Core IR 边界从残余 emit 里减出来。三步 Move(1 语义表 / 2 控制流 / 3 装箱)见 §8。
- **契约边界画多细**(§5 blockquote):细契约更可移植 vs 粗 intrinsic 更快;倾向"细 + 少数性能敏感项保粗"。
- **~~集合怎么产生~~ → C 已落地作过渡态,主推 D**(2026-07-25 修订):[collections-dejava-research.md](collections-dejava-research.md)。
  A(窄 codegen `extends java`)违背无继承+仍需 java 数组;B(手搓字节码)只有扁平 DawnList 划算、DawnMap 的 HAMT
  层级超出 codegen 现有能力;**C**(=把 DawnList/Map/Set 归位成「JVM 后端对契约的实现」)**已落地**——指路牌写进
  `selfhost/src/vendor.dawn`。**但 A/B/C 共同的隐藏前提被拆穿**:「java.util 身份不可约」只在 `==`/hash 硬编码时成立。
  **改判主推 D**:把 Eq/Hash 提升成可 override 的 trait(骑 Ord 现成的字典轨),集合写成纯 Dawn 持久 ADT,身份真正消除、
  两 backend 一份源。C 保留到 D 的 Map/Set 阶段完成。路线:D0 Eq/Hash trait 化(最大风险,巨型 Emit-Change)→ D1 popcount
  intrinsic → D2 Map/Set 纯 Dawn 化(4→2)→ D3 List→先严格 RB(relaxed 以后),两后端一份纯 Dawn 源(4→1)。**List 表示
  已定 RRB(relaxed),非可变数组原地路线**(§7,collections-dejava-research §5.3)。**接口最小化(2026-07-25)**:集合整族
  塌成一个后端原语 `Array[T]`(new/get/len/`with`),`list_*/map_*/set_*` intrinsic 全删、集合变纯 Dawn ADT;迭代靠语言
  侧 `Iter` trait 不进后端契约。换后端 = 实现一个数组类型。
- **ASM/AdtClassWriter**:算不算这轮范围。ASM 是第三方(可当外部依赖),AdtClassWriter 是我们写的但
  绑死 ASM——彻底零手写 Java 要连它一起换(Dawn 写的字节码+栈帧写入器,`jarw.dawn` 是同类先例)。
- **LLVM 侧**:字符串 native 表示(UTF-8/16)、内存管理选型(RC/region/GC)。→ 这几项已在
  [llvm-backend-research.md](llvm-backend-research.md) §4 深挖并给出推荐(UTF-8 / Perceus 式 RC / 先发 C)。

## 12. 契约有了第二份实现(2026-07-27/28)

前面十一节都是**一份实现下的设计**。C 运行时把契约整个实现了一遍,以下是被第二份实现证伪或坐实的东西。

### 12.1 名字:表里不该有名字

`Intr.rt` 原本是 `Option[(Rt, String)]`——模块 + **它在那个模块里叫什么**。逐条看下来,那个 String
**每一项都是 intrinsic 自己的名字换成 Java 大小写**(`cursor_start` → `cursorStart`,`java_try` → `javaTry`)。
即:表里存的不是数据,是**一个后端的拼写习惯**,而表是两个后端共用的。后果不是难看,是**第二个后端根本读不了这张表**
——emitc 只能手写 `else if` 链,于是「哪个运行时函数实现这个 intrinsic」有了两份定义,其中一份还缺了 32 项。

现在 `rt: Option[Rt]` 只说模块,名字各后端自己拼:JVM 是 `(rt_class(o), name)`,C 是 `dawn_` ++ name。
生成的 `dawn/rt/*` 里那 13 个 camelCase 方法改成了 intrinsic 自己的名字(Emit-Change)。

> **判据**:表里的一列若能由键算出来,它就不是数据。这条同时解释了为什么改完之后
> 「加一个 native intrinsic」= 「写一个按约定命名的 C 函数」,emitter 不必动。

### 12.2 字符串表示:UTF-8 vs UTF-16 不是开放决策,是**哪些位置可观察**的问题

§11 把它挂在「开放决策」下。实际答案是分层的:

| 位置 | 货币 | 可观察? |
|---|---|---|
| `str.len` / `str.index_of` / `str.last_index_of` | **码点**索引 | **是**——两后端必须逐位相同 |
| `Cursor`(cursor 家族) | JVM=UTF-16 下标,C=**UTF-8 字节偏移** | **否** |
| `hash` / `cmp` at String | UTF-16 码元(Java 定义) | 是——C 侧按 UTF-16 走一遍 |

> **2026-07-28 更新**:第一行不再是 intrinsic。「可观察 ⇒ 两后端必须逐位相同」这个要求,
> 靠「两份实现 + 一份语料」维持了很久;现在它们是 `std/str` 里**建在游标之上的一份 Dawn 定义**,
> 两个后端编译同一份代码,要求自动成立。真正留在表示边界上的只有第二行那 7 个游标原语
> (`index_of_from`/`cursor_skip` 也已降成 `std/cursor` 里的走查)。见
> `docs/native-backend-plan.md` §14.12。

Cursor 那一行是 `opaque type Cursor = Int` 挣来的:模块外做不了算术、也没有 `Show[Cursor]`,
所以那个数**谁也看不见**,两后端各挑各的最省的表示。这跟 `array_push` 的「唯一时就地写」是同一形状——
**契约规定的是可观察行为,不是实现**;区别只在 Array 那条要用时钟量,这条靠类型系统挡住。

### 12.3 诚实记录:C 侧现存的偏离

不是 gap(未实现),是**实现了但答案可能不同**,各自写在定义处:

- ~~`str_lower`/`str_upper` 只折 ASCII~~ / ~~`char_is_*` 在 U+007F 以上 panic~~ **2026-07-28 关掉**:
  两族都不再是偏离。**两张表整个收进了编译器**(`selfhost/src/case_table.dawn` 与
  `class_table.dawn`)——codegen 写进 `dawn/rt/Strings`、emitc 写进发出来的 C,两个后端从
  同一处领同一份数据。在此之前 JVM 侧读的是**宿主 JDK 那一版 Unicode**,所以连「只跑 JVM
  的程序」答案都取决于谁编译的它;native 那边一个是差 18 个码点、一个是当场 panic。
  见 `docs/native-backend-plan.md` §14.15–14.17。
- `str_of_float` / `parse_float` 不是 Java 的语法/最短往返形式。浮点因此不进差分语料。
- `catch_fault`/`catch_panic` 的 `Err` 载荷:JVM 是异常的 `toString`,native 是 panic 消息。**只分支 Ok/Err 的程序一致**。
  它们的结构化版本 `catch_fault_e`/`catch_panic_e` 把这条从「偏离」改成**写明的契约**,见 §12.4。
- `io_list_names` 的顺序两边都未定义。
- `io_temp_dir` 的随机后缀两边形状不同(JVM 是数字串,C 是 `mkdtemp` 的六位)。**名字本来就不该被读**,
  所以这不是可观察的——`io_files` 语料只断言它是个新目录,不打印它。

反过来,**这一批查出一个真偏离并且修了**:`io_write_file` 在 JVM 侧一直 `getParentFile().mkdirs()`,
C 侧没有,于是「往还不存在的目录里写文件」只在一个后端上成功。没有语料问过这件事——`io_files`
现在问了,两个写原语也都走同一个 `dawn_mkparents`。

反过来,原本以为要偏离、实测不必的:`char_is_space` 的全 Unicode 集合小到可以写全(§`dawn_is_space_cp`),
所以它不再是 ASCII-only。

### 12.4 `ForeignError.kind`:一个**声明为后端相关**的契约位

2026-07-30 起,两个屏障有了结构化载荷的孪生版本
(`catch_fault_e`/`catch_panic_e` → `Result[T, ForeignError]`,
见 [audit/error-model-design.md](audit/error-model-design.md) §六)。
`ForeignError` 是 prelude 类型,三个字段,其中 **`kind` 是这份契约里唯一一个
「两后端答案不同、而且这是规定」的位置**:

| 字段 | JVM 后端 | native 后端 | 可移植? |
|---|---|---|---|
| `kind` | `getClass().getName()`,即**二进制名**(`java.io.FileNotFoundException`、`dawn.rt.PanicError`) | 运行时自己的失败种类:`"panic"` / `"fault"` | **否——按定义** |
| `message` | `getMessage()`,null 记作 `""` | raise 时那条消息 | 否(文本本就不受约束) |
| `cause` | `getCause().toString()`,无则 `None` | 恒为 `None` | 否 |

前面每一行「可观察 ⇒ 两后端必须逐位相同」的要求,到这一行**故意反过来**。理由与
§12.2 的 Cursor 那行是同一个形状,但结论相反:Cursor 那个数**谁也看不见**,所以两边
各挑各的;`kind` 谁都看得见,但它答的是「**这个后端**把这类失败叫什么」,而两套失败
分类之间没有真实的对应关系。硬造一层规范化取值(把 `java.io.IOException` 和 `EIO`
映射到同一个 `io_error`)是在**猜**,猜错的地方正是调用方会依赖的地方。所以:

> **可移植的匹配只有 `Ok`/`Err` 这一层。** 按 `kind` 分流的代码就是后端相关的代码。

三条随之而来的规矩:

1. **`kind` 是名字,不是渲染。** JVM 侧的失败模式很具体:`toString()` 就在
   `getName()` 旁边,拼出来是 `名字: 消息`——那正是 spec §9.8 从前让调用方去解析的
   东西。`scripts/error-contract/` 逐字钉住 JVM 的名字,
   `scripts/spike-native/foreign_error.dawn` 在两个后端上钉住「它是个名字」
   (没有冒号、没有空格,且 `message` 不为空也不等于它)——后者能同时对
   `java.io.FileNotFoundException` 和 `fault` 成立,这也是它写成那样的原因。
2. **native 的取值可以变细,不算违约。** 今天是 `"panic"`/`"fault"`,因为 C 运行时的
   raise API 就是 `dawn_raise(msg, is_panic)`:没有 errno,也不捕信号。将来给
   `dawn_fault` 加上 errno 符号名是一次扩展,而不是一次毁约——`kind` 从第一天就
   声明为「后端自己的名字」,正是为了留这个口子。
3. **两个屏障的分工不因载荷而变。** `catch_fault_e` 抓的和 `catch_fault` 抓的
   逐字相同,`catch_panic_e` 同理;`foreign_error.dawn` 把同一个 thunk 喂给两对屏障
   并断言裁决一致,免得过渡期里长出两套错误模型。

## 13. 结论

去 Java 和接 LLVM 是**同一套重构的两个视角**:立一层运行时 intrinsic 契约,把 `java.*` 全关进 JVM
后端对它的实现里,std 写在契约之上。这样 selfhost 名副其实(无语言核心里的手写 Java),且 native
后端只需实现同一份契约。**方向比进度重要:朝 intrinsic 契约去,别朝内联 java FFI 去。**
