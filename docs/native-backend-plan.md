# native 后端计划

> 状态：**动工计划(2026-07-25 定稿)**。上游决策见
> [llvm-backend-research.md](llvm-backend-research.md) §10、
> [runtime-intrinsics-design.md](runtime-intrinsics-design.md)、
> [collections-dejava-research.md](collections-dejava-research.md) §9。
> 本文只回答一件事:**从今天到 native 自举，按什么顺序做、每步怎么验。**

## 1. 决策总表(已拍板，不再重开)

| 项 | 结论 | 定于 |
|---|---|---|
| 终点 | **Phase A(交叉发射)+ Phase B(native 自举)** | 07-25 |
| JVM 后端归宿 | **长期共存、平权** —— 共享层值得投资 | 07-25 |
| 共享 IR | **完整 Core IR**，两个后端都只吃 Core | 07-25 |
| 内存管理 | **直接上 Perceus**(精确 RC + 复用分析，非原子，无环回收器) | 07-25 |
| codegen 末端 | **发 C**(以后可换 LLVM IR，前端/运行时/FFI 不动) | 07-25 |
| native 运行时语言 | **C** | 07-25 |
| `use c` 签名来源 | **手写 extern 声明** | 07-25 |
| 包管理(native) | **shell 出去调 `curl`**；`[java-deps]`/coursier 在 native 上直接报不支持 | 07-25 |
| 生成的 C | **不入库**，只作发版 artifact | 07-25 |
| 字符串 | **UTF-8**，Cursor = 字节偏移(观测透明) | 07-25 |
| Unicode 表 | **先 ASCII-only** | 07-25 |
| hash/比较任意值 | **传 Eq/Hash 字典** → D0 是前置 | 07-25 |
| `Array[T]` | **语言不公开**，先作 std 内部原语 | 07-25 |
| List 表示 | **严格 RB**(32 叉 trie + 尾块)，relaxed 以后可加 | 07-25 |
| panic | **setjmp/longjmp**，两个捕获点(catch_panic / java_try 的对应物) | 07-25 |
| 泛型 | **不单态化**，沿用 box-at-type-var-slot | 07-25 |
| 一般尾调 | **不做**，大栈代替 | 07-25 |
| 验收 | **差分测试 + 全套 `dawn test` + native 固定点**，三道全要 | 07-25 |
| comptime 解释器 | **retarget 到 Core IR**，在 Phase 0 内完成(§6 R6) | 07-25 |

**平台假设(未经确认，按此推进)**:先只做 **Linux x86-64**，C11 + POSIX。macOS 应接近免费(同为 POSIX)，
排在 Phase A 验收之后。**Windows 不在范围内**。

## 2. 一个改变排序的结论:D 必须在 C 运行时之前

`llvm-backend-research.md` §5.2 写着「List(持久 vector)、Map/Set(HAMT)是 native 运行时的大头，先用 C 写」。
**这条已被 D 计划作废。** 集合纯 Dawn 化之后，两个后端复用同一份 Dawn 集合源，C 运行时**永远不需要长出集合库**
——它只需要实现 `Array[T]` 四个操作。

后果:**D0→D3 必须排在 C 运行时之前**。反过来做会白写三四千行 C，然后再删掉。这也是 D0(Eq/Hash trait 化)
从「de-Java 的第一步」变成「native 的关键路径」的第二个理由。

## 3. 工程量

对照 selfhost 重写(31,175 行 Dawn / 135 提交 / 2026-07-19~23):

| 块 | 规模(估) | 性质 |
|---|---|---|
| Phase 0 Core IR | ~4,000–6,000 行净变更 | 重构，有完整 oracle |
| D0 Eq/Hash trait 化 | ~800–1,500 行 | 巨型 Emit-Change，**全线最高风险** |
| D1–D3 集合纯 Dawn 化 | ~1,500–2,000 行 | 有实测支撑(§9)，风险已知 |
| C 发射器 | ~2,500–3,500 行 | 新写，可对差分 |
| C 运行时 | ~2,000–3,000 行 C | 新写，**无 oracle** |
| Perceus pass | ~800–1,200 行 | 新写，算法有论文 |
| `use c` FFI | ~600–900 行 | 镜像现有 Java FFI 面，但无反射 |
| Phase B 去 `use java` | ~1,000 行 | 大部分是删除 |

合计 **12,000–18,000 行**，约 selfhost 的 **40–55%**。但**每行风险高于 selfhost**——selfhost 每一步都有
Kotlin 编译器当标准答案(`__lex`/`__parse` golden diff → B==C 固定点)，native 的运行时层(内存、Unicode、ABI)
**没有任何可对拍的参照**，且 bug 以偶发损坏而非干净的不匹配形式出现。

## 4. 阶段

### Phase −1 — native 接缝 spike(几小时，可抛弃)

`llvm-backend-research.md` §8 的「native hello world」:平凡程序(main + println + 整数算术，无集合/闭包/ADT)
**直接从 TAST** 发 C + 极小运行时，跑通即弃。

**它不是 emit_c 的第一版**，是 Core IR 的设计探针——见 §6 R1。不做它就等于对着唯一一个 JVM 后端设计中立 IR，
历史上这么干的都设计歪了。

出口条件:`cc` 编出的二进制打印正确结果并 `exit(0)`。

### Phase 0 — Core IR(最大的单块，前置一切)

新建 `core.dawn`(IR 数据类型)+ `lower.dawn`(TAST → Core)，把 `emit.dawn` 改成只吃 Core。

要从 `emit.dawn` 那趟树遍历里搬出来的:

1. **结构化控制流 + 语法糖** —— `for`/`while`/`match`/`?`/`!`/字符串插值(现在活到
   `emit.dawn:764,1026,1456` 才内联 lower)。**match 决策树是皇冠明珠**，这次之后只写一遍。
2. **装箱/擦除** —— `adapt_to`/`adapt_from`(`emit.dawn:328`)在每个调用点重算「槽是不是 TyVar」，
   要物化成 IR 节点。这是 Rank 1 最烂的耦合。
3. **intrinsic 语义** —— `rt_intrinsic_target`(`emit.dawn:2219`)已收口过一次(Move 1)，把它变成 Core 层的
   intrinsic 节点，两个后端各自映射。
4. **RC 感知** —— 因为选了 Perceus 直接上，Core IR 从第一天就要能承载 dup/drop 节点和 owned/borrowed 参数模式。
   JVM 后端把它们当 no-op 忽略。**这是「先提取 IR」在这套决策下从可选变成必须的原因。**

还要一并做掉第五件——**把 `interp.dawn` 也 retarget 到 Core**(理由与被否的替代见 §6 R6):

5. **comptime 解释器改吃 Core** —— 于是 `match` 臂序、`for`/`?`/插值的展开只 lower 一遍，comptime 与两个
   后端**不可能**在这些事上分歧。附带好处直接对冲 R1:Core 的节点集将被**三个消费者**验证(JVM 发射器、
   解释器、纸面推演的 C 发射器)，而不是只对着一个 JVM 后端设计。
   > **这件事的成本对时机极其敏感。** 与 Core 同期做是边际成本;等 `emit.dawn` 和 `emit_c.dawn` 都定型
   > 再回头接，就是第三次重写。**真实截止点 = 冻结 Core 节点集之前**，不是「Phase 2 之前」。

出口条件:158 项 selfhost 测试 + packages/site/playground 全绿、`selfhost-fixpoint.sh` B==C 成立、
`fmt --check` 过。

> **修正(2026-07-25,动工后)**:本节原写「这一阶段不产生任何 Emit-Change,任何 Emit-Change 都说明
> 搬错了」。**那条是错的**,写它的时候还没动手。真相是 Phase 0 的两半性质不同:
>
> - **形状保持的一半**(装箱物化、intrinsic 归表、调用形式)——确实应当**零 Emit-Change**,
>   它们只是把决定提前,不改发射顺序。这半仍按原门禁验。
> - **形状改变的一半**(match、`for`/`while`、`?`/`!`)——**必然产生 Emit-Change**。今天
>   `emit.dawn` 的 match 是「标签 + 值留在栈上」,Core 的 match 是「一次性循环 + 结果临时量」。
>   要它们发出同样的字节码,只能让 Core 长成 JVM 栈机的形状——那正是 R1 说的 JVM-ism。
>
> 故门禁改为**分增量**:形状保持的增量零 Emit-Change;形状改变的增量**允许 Emit-Change,但必须
> 逐条审**,并由全套测试 + 固定点 B==C 兜行为等价。**止损点相应改为:形状保持的增量若出现
> Emit-Change,说明搬错了。**

### Phase 1 — D0:Eq/Hash trait 化(风险最高)

把 `==` 从硬连线 `BEq`、hash 从自动派生结构 `hashCode`，改成骑 Ord 已有的字典轨(`dict_syms` /
`resolve_witness` → `WitRef`)的可 override trait。

**验收的硬要求:派生默认必须与今天的结构 equals/hashCode 逐字节等价。** 这是巨型 Emit-Change，
但语义必须零变化。

出口条件:`Map[K,V]` 能要求 `[K: Eq + Hash]`；全套测试绿；Emit-Change 已审。
遵守两版种子纪律——新 trait 落地一版(休眠)，下一版 selfhost/std 才能用。

### Phase 2 — D1/D2/D3:集合纯 Dawn 化

- **D1**:`Array[T]` 作 std 内部原语(不公开)+ `popcount`。
  **`array_with` 的语义必须在这一步定死为「纯值语义 + 唯一时就地实现」**，而不是「返回新数组」
  ——实测差 12 倍，直接决定 D3 成不成立(§9.3)。
- **D2**:Map/Set 改纯 Dawn HAMT over `Array` + `Iter` trait(`for-in` 从后端 intrinsic 移到语言 trait)。
  后端契约 4 个原语 → 2 个。
- **D3**:List 改纯 Dawn 严格 RB。**`for-in` 必须用叶子游走迭代器，不能用 `nth()` 逐个索引**
  (随机索引实测慢 8–18× 且随 n 增长)。后端契约 2 → 1。

出口条件:后端集合契约只剩 `Array[T]`；自举总时长回归 ≤ +15%(实测预期 +11%)；全套测试绿。

### Phase 3 — C 发射器 + C 运行时

顺序按 `llvm-backend-research.md` §8:**ADT → 闭包 → 字典 → 字符串(UTF-8)**。

- **ADT**:显式判别式的 tagged union(JVM 侧是无 tag、靠 `INSTANCEOF`/单例身份，native 必须显式)。
- **闭包**:手写环境 struct `{fnptr; captures…}` + 顶层函数。**native 最大的一块**——JVM 侧
  `invokedynamic` + LambdaMetafactory 帮的忙全要自己做。
- **trait 字典**:直接映射成函数指针表 struct。**最干净的一块**，Dawn 本就是 dict-passing。
  例外:`Show` 是运行时按值分发。
- **字符串**:UTF-8 + 一个小编解码器；`str_lower/upper/trim` 先 ASCII-only。
- **运行时其余**:`panic`(setjmp/longjmp)、`StdIo`(syscall)、真 `main(argc, argv)`、大主线程栈
  (`pthread_attr_setstacksize`)。

C 编译标志:`-fwrapv`(Int 回绕同 JVM long)、`-fno-strict-aliasing`。这两条不是可选的。

### Phase 4 — Perceus

Core IR 上新增精确 dup/drop 插入 pass + 复用分析(rc==1 时原地)。Koka 论文有完整算法，Dawn 的纯性
(严格求值 + 不可变 + 无可变别名 → **无法构造环**)让它可解且无需环回收器。

**必须同时提供一个 `--rc=leak` 调试模式**(drop 全部 no-op)。理由见 §6 R3。

出口条件:`array_with` 在唯一时确实就地写(用计数器验，对照 JVM 侧实测的 99.1% 快路径命中率)。

### Phase 5 — `use c` FFI + Phase A 验收

手写 extern 声明机制，镜像现有 `use java` 的 TAST/checker 面但**无反射**——这也是
`checker.dawn` 能从 `!io` 变纯的地方(它 `!io` 纯粹因为 `jreflect` 解析 `use java`)。

**Phase A 验收**:JVM 上的编译器 `--target c` 给一批用户程序发 C，差分 harness 比 JVM/native 的
stdout 与退出码逐字节一致。

### Phase 6 — Phase B:native 自举

替换编译器自身的 99 处 `use java`(17 模块):

| 用途 | native 怎么办 |
|---|---|
| ASM | **不需要**——native codegen 不发字节码，它自己就是 C 文本发射器 |
| coursier / `[java-deps]` | **砍掉**，native 上报不支持 |
| jreflect | **删**——`use c` 无反射 |
| HTTP(拉包) | shell 出去调 `curl` |
| `java.lang.Character` / `Long.parseLong`(lexer/parser) | 纯 Dawn 化(已定 ASCII-only) |
| 文件/进程 IO | `use c` |

出口条件:**native 固定点** —— native 编译器编自己得到的下一代与自身一致(B==C)。

## 5. 测试与 oracle 基建(与阶段并行搭)

三道，缺一不可(§1 验收):

1. **差分 harness**(`scripts/native-diff.sh`)—— 一个程序语料库，同时在 JVM 与 native 下跑，比 stdout +
   退出码。**语料随每个特性增长**:ADT → 闭包 → 字典 → 集合 → 字符串。这是 Phase 3–5 唯一的 oracle，
   必须在写 C 发射器**之前**就位。
2. **全套 `dawn test` 在 native 下**(selfhost 158 / packages / site / playground)—— 需要测试运行器本身
   能在 native 上跑，故排在 Phase 5 之后。
3. **native 固定点**(`scripts/native-fixpoint.sh`)—— Phase 6 的出口，跑一趟很贵，当里程碑门禁而非日常门禁。

注意差分测试的已知盲区(`codebase-audit.md` TEST-01):**它会把旧 bug 固化成正确行为**。JVM 侧错的地方，
native 照抄才算"通过"。故语料要配少量**独立的期望输出**(不是从 JVM 抄的)。

## 6. 风险与止损

- **R1 — Core IR 对着唯一一个后端设计，长出 JVM-ism。** 历史上中立 IR 设计歪几乎都是这个原因。
  缓解:Phase −1 的 spike 先跑通；且**冻结 Core 节点集之前，为每个节点写一遍「C 侧怎么发」的纸面推演**。
- **R2 — D0 的 Emit-Change 太大。** 缓解:派生默认逐字节等价当硬门禁；改 dispatch 与改派生分成两个提交，
  中间那个提交必须零 Emit-Change。
- **R3 — Perceus 的内存 bug 与 codegen bug 纠缠。** 选了「直接上 Perceus」就必然面对这个。
  缓解:**`--rc=leak` 模式**(drop 全 no-op)。现象在 leak 模式下消失 ⇒ RC bug；不消失 ⇒ codegen bug。
  这等于把被否掉的「leak 优先」方案保留成一个调试工具，几乎零成本。
- **R4 — 两个后端平权 ⇒ 每次 Emit-Change 要验两套。** 缓解:Core IR 的 golden 测试(Core 层不变则两后端
  都不必重审)。
- **R5 — 种子纪律。** Eq/Hash/Iter 三个新 trait 各需两版才能被 selfhost/std 使用。**这给 Phase 1→2 之间
  插了一个无法压缩的等待**，排期时别忘。
- **R6 — comptime 解释器是第三实现(已决:retarget 到 Core，在 Phase 0 内做)。**

  一个内建的**含义**今天活在两处:`emit.dawn`(编成字节码)与 `interp.dawn:461`(编译期直接在 `VList` 上算)。
  加上 native 就是三处，且没有任何机制强制三者一致。

  有一处例外值得记下:字符串/cursor 那族**没有第二份实现**——`interp.dawn:404` 的 `rt_raw` 反射调用编译器自己
  classpath 上的 `dawn.rt.Strings`(即它编译时会发射的那个类)。**但这条 route-C 依赖 JVM**(反射 / `Class.forName` /
  classpath)，native 上根本不存在，Phase 6 必须换成直接调 C 运行时。

  与集合的耦合:`CValue` 只有扁平的 `VList`，且 `len/get/range/sort_by/concat` 五条原生臂
  (`interp.dawn:461–482`)**假设 List 是扁平列表**;`CValue` 更是**压根没有 `VMap`/`VSet`**(今天写不出值是 Map
  的 `const`)。D2 让 Map/Set 变成普通 Dawn ADT 后，`VAdt` 天然能表示它们，**这个洞顺手就补上了**(前提是
  `Array` 有个 CValue 表示);但 D3 之后那五条 `VList` 臂要么删掉(让 comptime 解释 RB 代码，正确但编译期变慢)，
  要么留作快路径——**那就欠下一笔新的正确性债:必须证明它们与 RB 代码等价。**

  > **被否的替代 C:删掉解释器，comptime 改成「编译 + 执行」**(把初始化表达式用真后端编译、在编译器进程里跑、
  > 拿运行时的值塞回发射代码;JVM 上=合成类 + ClassLoader，native 上=编 `.so` + `dlopen`,即 Rust 过程宏的做法)。
  > 卖点是「语义永远只有一份实现」，且 Dawn 的纯性让它天然安全(效应系统已把 `!io` 挡在 const 位置之外，
  > 见 `interp.dawn:397`)。**否决理由**:①自举循环(编译器源码自己就含 `const`);②交叉编译崩——comptime 代码
  > 要在主机上跑却用目标后端编译，而我们正好要有**两个平权后端**;③威胁模型变宽(`codebase-audit.md` LANG-01
  > 已指出这条线今天就破了，C 会把洞变成门);④每个 const 一次 `fork(cc)` + `dlopen`;⑤**反物化是刺**——
  > 把活的运行时对象变回可嵌入的常量，需要**每后端一份**类型制导的对象图遍历，于是「只有一份实现」是假的，
  > 第三实现问题只是从一个后端无关的文件搬进了后端里。
  >
  > 哪天 Core IR 成熟到反物化能写在 Core 层、两后端共享，C 可以重新拿出来看。

**止损点**:Phase 0 出口若无法做到零 Emit-Change，说明 Core IR 的边界画错了，退回重划而不是硬推。

## 7. 明确不在范围内

- `packages/web` / `packages/json` / `site` / `playground` 在 native 上跑(web 需要 C 写的 HTTP 栈 + socket 层)。
- Windows。
- 发 LLVM IR(正交轴，以后换末端那一层即可)。
- 一般尾调用消除。
- 完整 Unicode(先 ASCII-only)。
- JVM 侧退役(两后端长期平权)。
