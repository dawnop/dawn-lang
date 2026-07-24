# LLVM / native 后端调研

> 状态：**调研,未实现**。本文是 [runtime-intrinsics-design.md](runtime-intrinsics-design.md) §8「LLVM
> 后端具体要什么」的展开——把「接一个非 JVM 后端」从一句愿景落成对现有代码的量化盘点 + 几个硬决策的
> 带推荐结论。不是设计定稿;`§4` 三个决策（发 C vs LLVM IR、RC vs region、UTF-8）是本轮重点深挖。
> 相关:[runtime-intrinsics-design.md](runtime-intrinsics-design.md)(intrinsic 契约=后端接缝)、
> [seq6-research.md](seq6-research.md)(装箱/物化实测)、[spec.md](spec.md)(语义)、[bootstrap.md](bootstrap.md)(种子)。

## 1. 先把工程量摆正

**GraalVM native-image 已经在跑**(`main.dawn:730` `run_native_image --no-fallback`)——「不依赖 JVM 的
独立二进制」这层**已经有了**,它是把 JVM 产物 AOT 编译,语义仍是 JVM 的。所以建 LLVM/native 后端的价值
**不是**出二进制,而是**离开 `java.*` 的运行时语义**:native 的值表示、native 的内存管理、native 的持久
集合、native 的 IO。据三份代码调查量化:

> **LLVM 后端 ≈ 一套新 native 运行时(大头)+ 一个新 codegen 模块(~5,800 行替换)+ ~10% 的 IR 文本
> 发射。前端 ~90% 原样复用。** 难的是运行时(集合/字符串/RC/panic/闭包),不是 IR 发射。

## 2. 复用 vs 分叉(量化)

**原样复用**(后端无关,已 selfhost):`lexer/parser/ast/token/exhaustive`、`types`(减 3 个 JVM helper)、
`tast`(减 FFI 节点)、~7,000 行 `checker`(类型/效应/trait/穷尽)、`interp` 求值核心。这是 design doc 说的
「白拿的杠杆」,代码里核对成立。

**分叉出 native 路**:

| 分叉点 | 规模 | 说明 |
|---|---|---|
| `codegen.dawn` + `emit.dawn` 全替 | ~5,800 行 | 预期中的新后端。接缝 = `emit_module`(`emit.dawn:3439`):吃 `TModule`+`CtOut`+语义表(`Adts`/`Traits`/impl),吐 native 而非 `(类名, 字节)` |
| FFI | ~1,100 行 | TAST 的 `XJava`/`TJavaCall`(`tast.dawn:30-49,79`)+ `TyJava`(`types.dawn:134`)+ ~700 行 checker Java-interop 段(`checker.dawn:5889-6585`)+ `jreflect.dawn` 368 行 + interp route-C(`interp.dawn:596-708`)→ 全改 `use c` |

两个关键事实:

- **`List/Map/Set → java.util` 的 wire 决定只在 codegen 本地**(`desc_of` `codegen.dawn:57-60`),上游零成本——
  坐实 design doc「List[T] 是 java.util 是 JVM 后端细节」。
- **checker 之所以 `!io`,纯粹因为 FFI 反射**(`jreflect.dawn:1-8`):解析 `use java` 类、枚举方法做重载、
  SAM 检测。核心类型系统不碰反射。**去掉 `use java`,checker 能变纯。**

## 3. native 运行时必须复现什么

三份调查的值表示 + 控制/IO 清单,即 native 后端要实现的契约面:

| 值 | JVM 现状(锚点) | native 要造 | 难度 |
|---|---|---|---|
| 标量 | Int≡Cursor≡`i64`、Float=`f64`、Bool、String、Bytes、Unit=单例(`codegen.dawn:44-67`) | 同宽度;**Int 与 Cursor 运行时不可分**(都 `long`) | 易 |
| ADT | 抽象基类 + 每 ctor 一子类,**无 tag 字段**,靠 `INSTANCEOF`/单例身份判别(`emit.dawn:824-866`);nullary=interned 单例;Option/Result 就是普通 ADT | **显式判别式**的 tagged union;结构化 eq/hash/show 逐 ctor | 中 |
| **闭包** | **`invokedynamic`+LambdaMetafactory**,JDK 合成捕获类(`emit.dawn:1955-1979`);body=私有静态方法,签名 `captures++params` | **手写闭包环境 struct `{fnptr; captures…}`** + 顶层函数——**native 最大的一块**(JDK 帮的忙全要自己做) | 中高 |
| trait 字典 | **字典传递**:`dawn/impl/*` 单例实现 `dawn/tr/*`,作隐藏尾参传(每约束一个),直调(WConcrete)/虚调(WForward)(`emit.dawn:383-391,522-534,1747-1825`) | **直接映射成函数指针表 struct**——Dawn 本就 dict-passing,无需单态化,**最干净的一块**。例外:`Show` 是运行时按值的类型分发(`Show.show(Object)`) | 低 |
| 容器 | List→ArrayList/DawnList、Map/Set→DawnMap/DawnSet HAMT、Tuple→TupleN,元素**擦除装箱** | **native 持久 vector + HAMT 运行时库**(残留 native runtime,类比残留 Java) | 高 |
| 效应 | **完全擦除**——`TyFn` 描述符丢掉效应字段(`codegen.dawn:66`) | 无——白拿 | 无 |
| panic | 抛 `PanicError extends Error`(athrow)→unwind 到入口 catch→print+`exit(1)`(`codegen.dawn:300`,`emit.dawn:3260-3294`) | **unwind 机制**(见 §5.1) | 中 |
| catch_panic/java_try | JVM try/catch→`Result`(`codegen.dawn:781-819`) | thunk 边界接住 native unwind→`Ok`/`Err(msg)` | 中 |
| IO/argv | vendored `StdIo`(use java) / 静态字段 `dawn$args`(`std/io.dawn:18`,`emit.dawn:140,3269`) | native `StdIo`(syscall) / 真 `main(argc,argv)` | 易 |
| 装箱 | 只在类型变量槽装箱(`adaptTo = if declared is TVar then box`);**具体位置全原生**(seq6-research §2.1) | 同律:box-at-erased-slot,标量在具体位不装箱 | 中 |

## 4. 三个硬决策(本轮深挖)

### 4.1 codegen 目标:发 C vs 发 LLVM IR vs 绑 libLLVM(及其与 `use c` 的关系)

**先拆两件常被混在一起的事**——它们正交,而且**两条路都要**:

- **`use c` = FFI 机制**(叫 C 库:libc/syscall、Unicode 表/ICU、C 写的持久集合运行时)。**不论哪种后端都要**,
  是 native 运行时的地基,不是可选分支。哪怕走 LLVM,IR 里照样得 `declare` 外部 C 函数、按 C ABI 调它——LLVM
  不省这一步。故本节讨论的**不是** use-c,是「codegen 末端发什么」。
- **codegen 目标 = 发 C 源码 / 发 LLVM IR 文本 / 绑 libLLVM**——真正的岔路,三选一见下。

**codegen 对目标的真实需求**:struct 布局控制(ADT/闭包/元组)、函数指针(闭包/字典)、算术**回绕**
(Int 同 JVM long,`LADD` 无 trap)、RC 内联、panic 的 unwind。**不**需要:GC statepoint、SIMD、精密调度。

| | 发 C | 发 LLVM IR(文本) | 绑 libLLVM(FFI) |
|---|---|---|---|
| 发射难度 | **低**——高层:struct/函数/表达式,无 SSA/phi/基本块/寄存器分配 | 高——要么手搓 SSA(phi),要么 alloca-everything 靠 mem2reg(冗长)+ 管基本块/终结符 | 中,但要先有 `use c`、且绑一大坨 C++ API |
| 优化 | **白拿 clang/gcc `-O2`**(成熟) | LLVM opt passes | 同 |
| 工具链 | **通用**(`cc` 到处有) | 需 llc/clang | 需 libLLVM 开发库 |
| 尾调用 | 无一般 TCO 保证;`[[clang::musttail]]` 可显式标已知尾调(啰嗦、clang 限定) | `tail`/`musttail` + llc 做 TCO,**控制更好** | 同 IR |
| 坑 | 有符号溢出 UB(Int 回绕→须 `-fwrapv`/`int64_t`)、strict aliasing(须 `-fno-strict-aliasing`) | 无 C 的 UB,但发射更底层 | + FFI 复杂度 |
| 自举 | native 编译器 shell 到 `cc`(须在场) | shell 到 llc/clang(更重) | 链接 libLLVM |

**尾调用现状**(`emit.dawn` gen_call_fn):**自递归尾调已经是「回写参数 + goto 入口」的循环**(spec §12.4)——
最常见的递归形态零栈增长。只有**一般/互递归尾调**退化成普通 `INVOKESTATIC`,深栈,就是 `-Xss512m` 的来源。
故 MVP 阶段「大 native 栈」就够,不必强求一般 TCO。

**先例**:Nim / Vala / Chicken Scheme / 早期 Haskell 走**发 C**;Rust / Crystal / Zig 走 **libLLVM**。小型
自举语言的经典务实选择是发 C(基础设施最少)。

> **推荐:先发 C 起步,发 LLVM IR 是升级不是起点,libLLVM 排除——三者是先后关系,不是对错关系。**
>
> - **绑 libLLVM = 最不该先做**:要先有 `use c` 去调 LLVM 的 C/C++ API(循环依赖),且 API 跨版本极不稳,自举
>   语言绑一大坨不稳库 = 长期维护税。排除。
> - **发 C = 起点**:最快到可跑 native、优化白拿(clang `-O2`)、工具链最稳最通用(`cc` 版本无关)、可调试、
>   FFI 天然。Phase A 交叉发射与首个 native 自举都用它。**发射比现在经 ASM 发字节码还简单**(现有 codegen 已在
>   处理一个更底层的栈机目标)。让步只有「一般 TCO 不保证」——但自递归尾调已是循环,大栈够 MVP;回绕/aliasing
>   用编译标志兜。
> - **发 LLVM IR 文本 = 终点,不是起点**:等运行时/语义跑通、要生产级性能或真正的一般尾调消除时再切。这正是
>   **GHC 的历史路径**(via-C → 后加 LLVM 后端)。切的时候**仍不绑 libLLVM**,只把「发 C」换成「发 IR」。
>
> **关键:发 C ⇏ 放弃 LLVM。** 你发的 C 用 clang 编,本来就走 LLVM——只是让 clang 替你做 SSA/寄存器分配/优化,
> 而不是自己发 IR。等哪天 clang 挡了路(尾调、布局精度),把「发 C」换成「发 IR」即可:**前端、运行时、FFI、
> Perceus pass 全不动,只换 codegen 末端那一层**。正是这层的可换性,让「codegen 目标」这个决定可以安全推迟。
>
> 一个坦白:发 C 让「去 Java」略显反讽(转而依赖 C 编译器)——但那是**构建期工具链依赖**,不是**运行期
> `java.*` 依赖**,性质不同,可接受(design doc §9 已接受平台/FFI 绑定)。

### 4.2 RC vs region vs GC

**使能前提(Dawn 独有)**:严格求值 + 不可变 + 无可变别名 → **无法构造环**(不可变 ADT、无 mutation、无
惰性)。因此 **RC 不需要环回收器,即健全**。这是决定性的。

**装箱现实收窄了 RC 要追什么**(seq6-research §2.1):`adaptTo = if declared is TVar then box`——**具体位置的
标量是原生 `i64`/`f64`,零堆分配**;堆对象 = 引用类型(String/Bytes/ADT/List/Map/Set/闭包)+ 泛型槽的装箱值。
RC 正好追 `is_ref`(`codegen.dawn:88-101`)那一集,标量不进 RC。

**并发**:语言无线程原语(唯一线程是 spec `use java "java.lang.Thread"` 的 FFI 示例,`spec.md:783`,且不 port)
→ **非原子 RC**(单线程),inc/dec 无 atomics、便宜。

| 方案 | 评价 |
|---|---|
| **RC(Perceus 式)** | **推荐**。见下 |
| region/arena | bump 分配、整块释放,对相位化分配(parse→AST,check 后释放)极好;但值跨相位逃逸(TAST 一路流),region 推断(Tofte-Talpin/MLKit)复杂且有 region 泄漏病态。**当作定点优化,不当内存模型。** |
| tracing GC | 无环故非必需;不可变让 GC 更简单(无写屏障),但引入停顿/运行时复杂度,相对「RC 无环」无收益。 |

**为什么是 Perceus**:Dawn ≈ [Koka](https://koka-lang.github.io)(纯、不可变、效应系统、严格)。**Perceus** = 编译器
静态插入精确的 dup/drop + **复用分析**(引用计数==1 时原地复用内存)。它直击 Dawn 的三个痛点:

- seq6 点名的**物化开销**——重建 list 在唯一时原地进行;
- 历史上 List `++` 的 O(n²)(见 [seq6-research](seq6-research.md) 与 List 表示演进)——唯一列表追加变 O(1);
- 持久结构的一般开销——让「不可变更新」在唯一时退化成原地 mutation,与命令式竞争。

它是**恰好 Dawn 这一语言类**的 state-of-the-art。代价:要新增一个精确 dup/drop 插入 pass——是编译器工作,
但 Koka 论文有完整算法,Dawn 的纯性让它可解。

> **推荐:精确引用计数,Perceus 式(Koka),非原子,无环回收器。** 确定性、无停顿,且复用分析让不可变更新
> 原地化——解掉否则会缠住朴素 RC / 全 HAMT 方案的持久结构性能顾虑。region 留作未来定点优化;GC 非必需。

### 4.3 字符串:UTF-8 vs UTF-16

**现状**:String = `java.lang.String`(UTF-16),Cursor = UTF-16 偏移,`code_points` 给码点视图。

**观测透明性(关键)**:走一遍 intrinsic 表面——所有**暴露**的字符串值要么是码点粒度(`code_points`/`str_len`/
`str_index_of` 返回码点数/码点索引),要么**不透明**(Cursor 上算术是类型错误)。Cursor 的「UTF-16 偏移」本质
**不可观测**。故把底层换成 UTF-8(Cursor=字节偏移)**在观测上透明**。唯一接缝 `cursor_skip(s,c,sub)` 加的是
sub 的编码长度——UTF-16 加 `sub.length()`、UTF-8 加 sub 的字节数,都是「跨过这个 sub 出现」→ 同一结果位置 →
同一文本。透明。

| | UTF-8 | UTF-16 |
|---|---|---|
| 内存 | ASCII 1 字节,紧凑 | ASCII 2 字节,浪费 |
| IO | 文件/stdout/网络本就是 UTF-8→`read_file`/`write_file`/`println` **零重编码** | 每次 IO 要转码 |
| 码点索引 | O(n) 解码——但**现状已如此**(cursor 才是 O(1) 原语,码点索引本就靠 cursor 走 O(n)),无退化 | O(n)(UTF-16 有代理对) |
| 代理对 | 无(码点迭代更干净) | 有 |
| idiom | Rust/Go/Swift 母语 | 仅 JVM/JS |
| 逐字节 == JVM | 否(但观测透明) | 是(零行为变化) |

**Unicode 数据成本**(与编码正交):`str_lower`/`str_upper`(locale-independent 全 Unicode 折叠,源自
StdStrings 的 `Locale.ROOT`)、`str_trim`(Unicode 空白)不论何种编码都要 Unicode 表。native 选项:①内嵌
最小 case/whitespace 表(几 KB);②链 ICU(全但重);③先 ASCII-only + 后续补全。建议先①或③,把「全 Unicode
对等」当成与后端正交的运行时完备性任务。

> **推荐:native 用 UTF-8,Cursor = UTF-8 字节偏移。** 观测透明、贴 native IO 与 idiom、IO 零重编码。要造:
> 运行时一个小 UTF-8 编解码 + `str_lower/upper/trim` 的 Unicode 表(内嵌最小或链 ICU,可先 ASCII)。
>
> **回喂契约**:intrinsic 契约文档里 cursor 语义必须写成**「不透明位置、码点粒度、非 UTF-16 偏移」**——
> de-Java 把 cursor 归位进 `dawn/rt/Strings` 已经让表示可换,但契约措辞不能把它重新锁死在 UTF-16。

## 5. 其他决策(推荐直给)

### 5.1 panic 的 unwind

JVM 靠抛 `Error` + 栈 unwind,catch_panic/java_try 是 try/catch。native 无 JVM 异常。选项:setjmp/longjmp
(简单、C 友好)、libunwind(`invoke`/landingpad,更「正规」)、Rust 式 panic runtime。**推荐 setjmp/longjmp** 接
catch_panic/java_try 两个点(全 intrinsic 表面只有这俩会捕获),未捕获则 print+abort。要保留的可观测语义 = `Result`
形状 + `throwable.toString()` 的消息文本。

### 5.2 集合运行时

List(持久 vector)、Map/Set(HAMT)、Tuple 是 native 运行时的大头(残留 native runtime,类比残留 Java)。
先用 C 写运行时库,稳定后可考虑 Dawn-over-raw-intrinsic(但会重演 DawnList 的自举循环:list 的底座不能用 list
字面量)。§4.2 的 Perceus 复用让这些持久结构的更新在唯一时原地化,是它们性能可用的关键。

### 5.3 装箱/擦除

沿用 JVM 的 box-at-type-var-slot 律:泛型槽是统一指针(装箱值),具体位是原生标量。native 先**统一装箱**
(对齐语义、RC 均匀),小整数后续用**标签指针**优化(把小 Int 塞进指针 + 标签位,免堆装箱)。**别单态化**——
Dawn 是 dict-passing 而非单态化,改成单态化是大手术且与字典表示冲突。

### 5.4 深递归 / 栈

`-Xss512m` 说明存在深的非尾递归(一般/互递归尾调不 TCO,见 §4.1)。native 先给**大主线程栈**
(`pthread_attr_setstacksize`/`ulimit`),或按 `m8-selfhost-only.md` 的可选后续把热点深递归改迭代。

## 6. 分期

- **Phase A — 交叉发射(先做)**:JVM 编译器加 `--target native`,给**用户程序**发 C + native 运行时。编译器
  仍跑 JVM。低风险、立刻有**真 native 运行时**(不是 GraalVM 对 JVM 语义的 AOT)。验证:一批 Dawn 程序在
  JVM 与 native 下**行为一致**(而非字节一致——UTF-8 使字节必然不同)。
- **Phase B — native 自举(远)**:编译器把自己编成 native。拦路 = 自身 **99 处 `use java`**(17 模块、~60 类:
  ASM/coursier/http/反射/进程)。**但**:native codegen 不发 JVM 字节码 → **不需要 ASM**(它自己就是 C/LLVM
  文本发射器);不需要 coursier(native 包管理或砍掉);jreflect 只为解析 `use java` → native 走 `use c` 无反射。
  故 native 自举编译器是**另一套构建**(native codegen 模块 + use-c FFI + native 运行时),是最远里程碑。

**正交轴**:「codegen 目标发 C 还是 LLVM IR」(§4.1)与「Phase A/B 分期」互不相干——A、B 都先发 C;等真需要
时把末端换成发 IR,前端/运行时/FFI/Perceus pass 全不动。而 **`use c`(FFI 地基)两个 Phase、两个 codegen 目标
都要**:Phase A 的 native 运行时靠它叫 libc/Unicode,Phase B 的自举编译器靠它取代自身 99 处 `use java`。

## 7. 回喂 intrinsic 契约 / de-Java(同一件事)

- 每个 intrinsic(`code_points`/`cursor_*`/`str_*`/`list_*`/`map_*`)= 一个 native 契约点。**契约要抽象写**
  (cursor=不透明位置非 UTF-16;list/map/set=操作非 java.util),否则会把某个后端的实现细节锁进语言。
- **str_* 精简的结论被 LLVM 加强**:薄契约 = native 运行时少写;但性能项(`str_len`/`str_starts_with`)native
  也得原生实现。故——**砍冗余的(`str_contains`/`str_index_of`,可纯 Dawn over `index_of_from`),留性能的**,
  与独立得出的 9→7 结论一致。
- 最干净的 native 映射:**trait 字典(本就 dict-passing→函数指针表)、效应(擦除)、ADT**。最重的:**闭包、
  集合运行时、RC、UTF-8 字符串栈**。

## 8. 最小第一步(验证接缝)

「native hello world」:给一个平凡 Dawn 程序(main + println + 算术,无集合/闭包/ADT)发 C + 一个极小 native
运行时(Unit / panic / StdIo)。跑通 = 证明了 codegen 接缝 + 运行时骨架 + 工具链链路。之后按
**ADT → 闭包 → 字典 → 集合 → 字符串(UTF-8)→ RC(Perceus)→ 自举** 逐步长。

## 9. 仍开放

- Perceus dup/drop 插入 pass 的具体落点(新 pass vs 融进 codegen)。
- native 运行时用什么写(C / Rust / Zig / Dawn-over-raw)——影响自举纯度。
- Unicode 表策略(内嵌最小 / ICU / ASCII-first)。
- 一般尾调用:大栈够用多久,何时值得切 LLVM IR 上 `musttail`。
- `use c` FFI 的**设计**(机制本身是地基、必做,见 §4.1;开放的是**怎么做**:与 `use java` 对称,但 C 无反射,
  签名从哪来——头文件解析 / 手写 extern 声明 / 绑定生成器)。这是 native 自举的前置,建议在 Phase A 早期定。
