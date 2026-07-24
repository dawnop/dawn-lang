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
   str_* / list_* / map_* /        (code_points 已是其一)
   set_* / bytes_* / io_* / panic
──────────────────────────────
③ std 库(Dawn 写)              ← 只用 intrinsic + Dawn,不碰 java.*  → 换后端免费
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
- **bytes**:`utf8`(编码)、`decode`、`len`、`at`、`slice`、`index_of`。
- **list**:`get`、`size`、`concat`(不可变、O(1) 均摊 append)、`iter`。
- **map/set**:`empty`、`assoc`/`without`、`get`、`has`、`size`、`keys`、`iter`(HAMT 语义:插入序迭代)。
- **io**:`print`/`println`、`read_line`、`read_file`/`write_file`、`is_dir`、`list_names`。
- **控制**:`panic`、效果系统的 IO 边界。

> 契约的**边界画在哪**是核心决策(§8):画粗(整个 String API 当一个 intrinsic)则 JVM 后端实现少、
> 但 LLVM 后端要重写多;画细(只暴露 `code_points`/`from_code_points`,其余用 Dawn 拼)则 std 更可移植、
> 但 JVM 上可能有性能损失(每次 `str.len` 物化码点数组 vs `codePointCount` 原生)。**倾向:细契约 +
> 少数性能敏感项保留粗 intrinsic**(如 `str_len` 直给,不走物化)。

## 6. de-Java 的正确方向 vs 错误方向(关键决策记录)

**错误方向**:把 `StdStrings` 溶进 `std/str.dawn`、直接 FFI 调 `java.lang.String`。
——对"没有手写 Java"达标,但把 `java.lang.String` 从一个 Java 类**搬进了 std 源码**,std 反而更
JVM-锁死。LLVM 后端一看 std 里全是 `java.lang.String.codePointCount`,傻眼。

**正确方向**:把 `StdStrings` 的**逻辑**变成"JVM 后端对 `str_*` intrinsic 的实现",`std/str.dawn`
改写成 over-intrinsic(不点名任何 `java.*`)。于是同一份力气:std 变可移植(诉求 B),手写 Java 类
被后端实现吸收(诉求 A)。

> **这是本文最重要的一条:去 Java 要朝 intrinsic 契约去,不朝内联 java FFI 去。** 前者一份力气两处用,
> 后者只满足诉求 A、还加深了对 JVM 的耦合。

## 7. 那三个集合:java.util 身份不可约,但可归位

在 **JVM 后端 + 要无缝互操作**两个前提下,"一个 `implements java.util.List` 的类"是**不可约**的:
即便让 Dawn 有自己的 list 类型,它一跨进 `use java` 签名(`String.join`、`Files.readAllLines`……)
就得要 java.util 身份;边界适配器本身又是个 `implements java.util.List` 的类——继承的坑只是从"到处"
挪到"边界"。Dawn 语言无继承,所以这个类**没法用纯 Dawn 源写**。

因此集合的去 Java **不是"翻译成 Dawn ADT"**,而是"把它归位成 **JVM 后端对 list/map/set intrinsic 的
实现**":

- **JVM 后端**:`DawnList/Map/Set`(extends `java.util.Abstract*` + HAMT/CAS)是 JVM 对集合 intrinsic
  的实现。它**怎么产生**有三条路(见 §8 决策):(A) 加窄 codegen 能力让 Dawn 类型声明 `extends java`、
  HAMT 节点用 Dawn ADT;(B) codegen 手搓字节码发射(像 Show/Maps);(C) 继续 vendored,只把它**明确
  记为"JVM 后端 intrinsic 实现"**、留指路牌。
- **LLVM 后端**:native 持久集合(HAMT/持久向量),实现同一份契约。跟 java.util 无关。

语言核心与 std **永远不点名 java.util**——只用 list/map/set intrinsic。这样集合的 java.util 身份被
彻底关进 JVM 后端,LLVM 后端换一套 native 实现即可。

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
  - 持久集合(HAMT/持久向量)、字符串(UTF-8 还是 UTF-16 的 native 表示?决策项)。
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
- **集合怎么产生**(§7):A 窄 codegen `extends java` 特性 / B 手搓字节码 / C vendored 归位留指路牌。
  → **已调研,推荐 C**(2026-07-24):[collections-dejava-research.md](collections-dejava-research.md)。java.util 身份
  在 JVM 上不可约(`==`/hash 就是 `Abstract*` 契约),对 native 后端目标 C 已足够;A 违背无继承+仍需 java 数组,
  B 只有扁平的 DawnList 划算、DawnMap 的 HAMT 层级超出 codegen 现有能力。可选:B-for-List(退 1/3)或 C+(源回树+javac)。
- **ASM/AdtClassWriter**:算不算这轮范围。ASM 是第三方(可当外部依赖),AdtClassWriter 是我们写的但
  绑死 ASM——彻底零手写 Java 要连它一起换(Dawn 写的字节码+栈帧写入器,`jarw.dawn` 是同类先例)。
- **LLVM 侧**:字符串 native 表示(UTF-8/16)、内存管理选型(RC/region/GC)。→ 这几项已在
  [llvm-backend-research.md](llvm-backend-research.md) §4 深挖并给出推荐(UTF-8 / Perceus 式 RC / 先发 C)。

## 12. 结论

去 Java 和接 LLVM 是**同一套重构的两个视角**:立一层运行时 intrinsic 契约,把 `java.*` 全关进 JVM
后端对它的实现里,std 写在契约之上。这样 selfhost 名副其实(无语言核心里的手写 Java),且 native
后端只需实现同一份契约。**方向比进度重要:朝 intrinsic 契约去,别朝内联 java FFI 去。**
