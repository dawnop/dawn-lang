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
| `Array[T]` | **语言不公开**，先作 std 内部原语(已落地;JVM 上 push/with 不对称,见 §10) | 07-25 |
| List 表示 | **严格 RB**(32 叉 trie + 尾块)，relaxed 以后可加 | 07-25 |
| panic | **setjmp/longjmp**，两个捕获点(catch_panic / java_try 的对应物) | 07-25 |
| 泛型 | **不单态化**，沿用 box-at-type-var-slot | 07-25 |
| 一般尾调 | **不做**，大栈代替 | 07-25 |
| 验收 | **差分测试 + 全套 `dawn test` + native 固定点**，三道全要 | 07-25 |
| comptime 解释器 | **retarget 到 Core IR**，在 Phase 0 内完成(§6 R6) | 07-25 |
| trait v2 | **做最小切片**(泛型主体的条件 impl)，是 D2 的前置——推翻 §9.1 的「不做」 | 07-25(审计后) |
| 阶段顺序 | **按「一件事有几份定义」重排**为 S0–S4，见 §11.4；§4 的内容有效、顺序作废 | 07-25(审计后) |

**平台假设(未经确认，按此推进)**:先只做 **Linux x86-64**，C11 + POSIX。macOS 应接近免费(同为 POSIX)，
排在 Phase A 验收之后。**Windows 不在范围内**。

## 2. 一个改变排序的结论:D 必须在 C 运行时之前

`llvm-backend-research.md` §5.2 写着「List(持久 vector)、Map/Set(HAMT)是 native 运行时的大头，先用 C 写」。
**这条已被 D 计划作废。** 集合纯 Dawn 化之后，两个后端复用同一份 Dawn 集合源，C 运行时**永远不需要长出集合库**
——它只需要实现 `Array[T]`(5 个操作 + `popcount`，§10.2)。

后果:**D0→D3 必须排在 C 运行时之前**。反过来做会白写三四千行 C，然后再删掉。这也是 D0(Eq/Hash trait 化)
从「de-Java 的第一步」变成「native 的关键路径」的第二个理由。

## 3. 工程量

对照 selfhost 重写(31,175 行 Dawn / 135 提交 / 2026-07-19~23):

| 块 | 规模(估) | 性质 |
|---|---|---|
| Phase 0 Core IR | ~4,000–6,000 行净变更 | 重构，有完整 oracle |
| D0 Eq/Hash trait 化 | ~800–1,500 行 | ~~巨型 Emit-Change，全线最高风险~~ **实测后下调,见 §9** |
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

> **顺序已被 §11 取代(2026-07-25)。** 本节每个阶段**要做的事**仍然有效,读它了解内容;
> **什么时候做**看 §11。变的是三件:S0(让今天已经错的东西在 CI 上变红)插到最前;
> 语义收口(相等/渲染/字典/intrinsic 词汇表)从散在各阶段的碎片合成一整段,排在 C 后端之前;
> trait v2 的最小切片从「不做」变成 D2 的前置。

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

### Phase 1 — D0:Eq/Hash trait 化

把 `==` 从硬连线 `BEq`、hash 从自动派生结构 `hashCode`，改成骑 Ord 已有的字典轨(`dict_syms` /
`resolve_witness` → `WitRef`)的可 override trait。

**验收的硬要求:派生默认必须与今天的结构 equals/hashCode 逐字节等价。** 语义零变化。

> **动工后修正(2026-07-25):本节原写「风险最高 / 巨型 Emit-Change」,实测后两条都要改。**
> 爆炸半径已数清(2,047 处 `==`,分类见 §9),预期中最大的工作量(补 `[T: Eq]` bound)**为零**,
> 而真正的障碍是计划没提的一件:6% 的站点在结构泛型上,trait v1 表达不出。出路是**编译期合成
> 结构见证**而不是先做 trait v2。Emit-Change 也不「巨型」——见证让后端自己挑物化方式,
> JVM 的派生路径继续发今天的 `equals`。**详见 §9。**

出口条件:`Map[K,V]` 能要求 `[K: Eq + Hash]`；全套测试绿；Emit-Change 已审。
遵守两版种子纪律——新 trait 落地一版(休眠)，下一版 selfhost/std 才能用。
(种子等待比预想的短:只有 selfhost/std **源码写出** `Eq` bound 时才需要新种子,
编译器内部改动不需要。故 D0-1/D0-2 不必等,D0-3 才等。)

### Phase 2 — D1/D2/D3:集合纯 Dawn 化

- **D1**(**已完成**):`Array[T]` 作 std 内部原语(不公开)+ `popcount`。
  **`array_with` 的语义必须在这一步定死为「纯值语义 + 唯一时就地实现」**，而不是「返回新数组」
  ——实测差 12 倍，直接决定 D3 成不成立(§9.3)。
  > **动工后的修正。** 这条要求在 JVM 上**做不到**——`with` 写的槽位已经交出去了,没有水位线
  > 能判断还有谁在读。原语因此拆成 `array_push`(有快路径)和 `array_with`(总是复制),
  > 而 12 倍恰好整个落在 push 那条路上,所以结论不变。**详见 §10。**
- **D2**:Map/Set 改纯 Dawn HAMT over `Array` + `Iter` trait(`for-in` 从后端 intrinsic 移到语言 trait)。
  后端契约 4 个原语 → 2 个。
- **D3**:List 改纯 Dawn 严格 RB。**`for-in` 必须用叶子游走迭代器，不能用 `nth()` 逐个索引**
  (随机索引实测慢 8–18× 且随 n 增长)。后端契约 2 → 1。

出口条件:后端集合契约只剩 `Array[T]`；自举总时长回归 ≤ +15%(实测预期 +11%)；全套测试绿。
D1 单独的出口条件已达成:`scripts/array-contract/run.sh`(值语义 + 就地追加)进了 CI,见 §10.3。

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

出口条件:**`array_with` 在唯一时确实就地写**(用计数器验，对照 JVM 侧实测的 99.1% 快路径命中率)。
这是 native 相对 JVM 多出来的那一格——JVM 上 `with` 只能复制(§10.1),Perceus 的 `rc==1` 才补得上。

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

  > **更正(2026-07-25)**:这一条把 `Iter` 的障碍说小了。种子等待是**次要**障碍,主要障碍是
  > `impl[T] Iter[List[T]]` 的主体是泛型的,trait v1 写不出来——同 §9.1 的更正块。种子等待
  > 只在 selfhost/std **源码写出**新构造时才发生;先要有那个构造。
- **R6 — comptime 解释器是第三实现(已解决:2026-07-25 retarget 到 Core,见 §7)。**

  一个内建的**含义**曾经活在两处:`emit.dawn`(编成字节码)与 `interp.dawn`(编译期直接在 `VList` 上算),
  加上 native 就是三处,且没有任何机制强制三者一致。**retarget 之后解释器读的是 Core**,于是「一个内建
  叫什么名字、拿几个参数、在什么形状的树里」只有一份;剩下的分歧只在**同名 intrinsic 的实现**上,
  那正是运行时契约要管的事。

  有一处例外值得记下:字符串/cursor 那族**没有第二份实现**——`interp.dawn:404` 的 `rt_raw` 反射调用编译器自己
  classpath 上的 `dawn.rt.Strings`(即它编译时会发射的那个类)。**但这条 route-C 依赖 JVM**(反射 / `Class.forName` /
  classpath)，native 上根本不存在，Phase 6 必须换成直接调 C 运行时。

  与集合的耦合(仍然成立):`CValue` 只有扁平的 `VList`，且 `len/get/range/sort_by/concat` 五条原生臂
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

## 7. 进度(2026-07-25)

| 阶段 | 状态 |
|---|---|
| **Phase −1** 接缝 spike | **完成** |
| **Phase 0** Core IR | **完成**——IR + lowering 覆盖整门语言;JVM / C / comptime 三个消费者都吃 Core,`emit.dawn` 的 TAST 路已删(4353 → 2318 行) |
| Phase 1 D0 | **进行中**——trait 已入 prelude(休眠);爆炸半径已实测,见 §9 |
| Phase 2 D1–D3 | **D1 完成**——`Array[T]` + `popcount` 已落地(std 内部,休眠);契约在 JVM 上被迫拆成 push/with 两半,见 §10。D2/D3 未动 |
| Phase 3 C 发射器 | **写了不少,但要按收口后的 Core 重导**——它跑在了它所消费的语义前面,见 §11.1 |
| Phase 4 Perceus | 未动 |
| Phase 5 `use c` / Phase A 验收 | 差分 harness 已就位并进了 CI,`use c` 未动 |
| Phase 6 native 自举 | 未动 |

**已落地的件**:`selfhost/src/core.dawn`(IR)、`selfhost/src/lower.dawn`(TAST → Core)、
`selfhost/src/emitc.dawn`(Core → C)、`emit.dawn`(Core → JVM)、`runtime/c/dawn_rt.{h,c}`、
`scripts/spike-native/`(差分 harness + 五个语料,已接 CI)。
入口:`dawn __emitc <file> -o <out.c>`(发 C)、`dawn __lower <target>`(覆盖率门禁)。

**Phase 0 的验收状态**:
- `dawn __lower` 在编译器 + 两个 package + playground + m4 例子上**零缺口**。
- selfhost 158 / json 1 / web 15 / site 65 / playground 18 测试全绿;**固定点 B==C 成立**
  ——编译器通过 Core IR 编了自己,结果再编自己逐字节相同。N vs N−1 的四件差分(emit / run /
  fmt / lsp)全过。
- Emit-Change 分两次落地。翻默认那次改「改变形状的那一半」(match / 循环 / 插值),m4 json
  语料 63 个类中 55 个逐字节相同、总字节 +1.1%;拆 TAST 路那次只改 15/3029 个类,全是
  自递归、递归局部函数或「内建当值用」的调用方。

**拆 TAST 路时补的三件**(都是跑出来的,不是读出来的):
- **spec §12.4 的自尾调用**。Core 路原本发的是真调用,10⁸ 次深度直接爆栈,而 TAST 路是循环。
  尾位置**必须在 lowering 期间跟踪**——等 Core 建完再回头找就晚了,match 臂里的尾调用那时
  已经变成「赋值 + break」。重写形式 = 实参进临时量 → 临时量写回形参 → 跳转;临时量正是
  `f(b, a)` 正确的原因。这件事做在 lowering 里,于是 C 后端**白拿**(新语料在无优化的 C 下
  也能跑 500 万层)。
- **局部命名函数不在自己的捕获表里**(检查器把那个绑定剔掉了),所以在自己体内提到自己
  只能重建闭包。漏掉它发的是**非法字节码**,不是错答案。
- **内建当函数值用**(`map(xs, to_string)`)在 lowering 里 panic。现在和普通函数一样走提升包装。

**comptime 解释器 retarget(2026-07-25,R6 关账)**:`interp.dawn` 原本自己决定 `match` 是什么、
`?` 返回什么、`for` 怎么迭代、什么时候装箱——**第三份语言定义**,且没有任何机制强制它和两个后端一致。
现在它读后端读的同一份 IR。
- **删掉的**:模式匹配器、`for`/`while`、`?`/`!`、字符串插值,以及四分之三的函数值表示
  (lowering 把 lambda / 局部命名函数 / 顶层函数当值 / 内建当值 / 裸构造器全提升成同一形状,
  于是 `VClosure` 顶掉了 `VLambda`/`VFnRef`/`VBuiltinF`/`VCtorRef`)。
- **两条规则不是搬走而是不再重复**:①**spec §12.4** —— 自尾调用在 Core 里已经是循环,于是 comptime
  白拿,原先会撞 `MAX_CALL_DEPTH` 的深递归现在能折叠(补了测试);②**`unsafe_pure`** —— 旧的
  route-C 检查在复述效果系统已经保证的事(没有那个块调用就是 `!io`,而 `!io` 进不了 const),
  Core 丢掉这个标记,效果系统留着。
- **函数按需 lowering 并在本次求值内缓存**,不是整程序预先 lowering:一次 comptime 求值只碰到
  几个函数。实测无可测量的编译耗时变化(4.7–4.9s,噪声内)。
- **唯一的退步是 span**。Core 没有源位置,所以 comptime 失败现在报在**被折叠的 const / comptime 块**上,
  而不是子表达式上;消息、hint、条数不变。保持 Core 无 span 是有意的——等真正需要行号表(调试信息)
  时再一次性加,那时 comptime 的 span 顺带变好。

**Phase 0 的真正教训**:出口条件写成「零 Emit-Change」是错的(§6 的自纠已记);更值得记的是
**「两条路都在」这件事本身是最强的 oracle**。三个 bug 全靠拿同一个程序两边跑出来的差异定位,
而不是靠读 IR。拆掉旧路之后这个 oracle 就没了——后面每一步都得自带对拍物(N−1 差分、native
差分、固定点),这也是把 `spike-native/run.sh` 接进 CI 的原因。

**Core 已覆盖并在两个后端对拍验证**:标量、算术/位运算、短路、控制流、字符串与插值、ADT 构造/字段/判别式、
match(守卫、嵌套模式、字面量模式、元组模式)、`?`/`!`、元组、闭包(lambda 提升 + 捕获环境 + 函数值)、
trait 字典(去虚化 + 转发 + 默认方法 + 桥接)、类型变量槽的装箱。

> **更正(2026-07-25,审计后)**:上面这句话的**「对拍验证」四个字要打折**,而且折得很厉害。
> 差分语料里 `==` **只出现在 `Int` 和 `String` 上,一处都没有比较过两个 ADT 值**——而 ADT 相等
> 恰恰是两个后端给相反答案的地方(JVM `equal` / native `NOT equal`,都退出 0,无诊断)。
> 「trait 字典」同理:语料只有在**同一模块内静态可知**的见证,`[T: Eq]` 这类要真转发字典的形状
> 一个都没有,而它发出的 C 引用两个**没有定义**的符号,`cc` 编不过。
>
> 所以这份清单描述的是**lowering 的覆盖面**,不是**两个后端答案一致的覆盖面**。后者今天要小得多。
> 根因不在语料的勤勉程度,在 harness 的准入规则——详见 §11.2。**已修**:四个语料 + 写下来的期望
> 输出 + `known-red.txt` 已进 CI(`scripts/spike-native/`)。

**Core 已覆盖的其余部分**:comptime const 与 comptime 块、索引、构造器作函数值、解构 let、
列表模式、构造器 spread、集合上的 for-in、derive 出来的 impl、有序比较的 Ord 见证。

**C 后端尚未覆盖**(JVM 侧已全覆盖):集合(等 D1–D3)、comptime const、`use java`
(`CForeign`,native 侧**按设计拒绝**——那是 FFI 不可移植的一半)。

**为什么先让 C 后端吃 Core,而不是先改 `emit.dawn`**:R1 说的就是「对着唯一一个后端设计中立 IR 会长出
JVM-ism」。让那个**不可能继承 JVM 假设**的后端先吃,是最直接的对冲。事后看这步是对的:四条设计缺陷
(`CSDiscard`、`CSLoop.step`、`CBreak` 点名循环、字典槽统一签名)都是**在写第二个后端之前**发现的。

**Core 有三个消费者,不是两个**:`emit.dawn`(JVM)、`emitc.dawn`(C)、`interp.dawn`(comptime)。
第三个是有意义的:它**不是代码发生器**,所以它对节点集的要求和两个后端不重叠——它需要节点能被
*直接求值*,而后端只需要节点能被*翻译*。节点集被这两类消费者一起验过,比被两个后端验两遍强。

## 8. 明确不在范围内

- `packages/web` / `packages/json` / `site` / `playground` 在 native 上跑(web 需要 C 写的 HTTP 栈 + socket 层)。
- Windows。
- 发 LLVM IR(正交轴，以后换末端那一层即可)。
- 一般尾调用消除。
- 完整 Unicode(先 ASCII-only)。
- JVM 侧退役(两后端长期平权)。

## 9. D0 的爆炸半径:实测(2026-07-25)

计划一直把 D0 写成「全线最高风险」,依据是**「改 `==` dispatch 动的是编译器里每一处相等比较」**。
动工前先把「每一处」数出来了——在检查器的 `==` 处插桩,编译器 + 两个 package 全量跑一遍,
按操作数静态类型归类。

**编译器自身 2,047 处 `==`**:

| 类别 | 处数 | 占比 | trait v1 能否表达 |
|---|---|---|---|
| 标量(String 793 / Int 610 / Float 8 / Bool 3 / Cursor 2) | 1,416 | 69% | ✅ prelude impl |
| 非泛型 ADT(TokKind 211 / Ty 206 / CBinOp 46 / Eff 28 / …) | 498 | 24% | ✅ `impl Eq[Ty]` |
| **结构泛型**(`Option[X]` ~79 / `List[X]` ~39 / `Result[X,Y]` 5 / 元组) | ~123 | 6% | ❌ |
| **裸类型变量 `T`** | **0** | 0% | — |

`packages/web` 形状相同,且出现三层嵌套(`Option[List[(String, String)]]`)。

**两个结论都和计划的预设相反**:

1. **`[T: Eq]` bound 的铺设量是零。** 计划(和我)预期的主要工作量是「给每个比较 `T` 的泛型函数补约束」。
   实测**一处都没有**——std 压根没有 `list.contains` 这类元素相等函数,`map`/`set` 是 intrinsic 包装。
   风险最大的那件事不存在。
2. **真正的障碍是另一件,且计划没提**:6% 的站点落在 `Option[T]`/`List[T]`/元组这类**结构泛型**上,
   而 spec §3.5 把 trait v1 的主体限定为「非泛型具名类型」、明写「无条件 impl」,§1223 把
   「条件 impl、泛型主体」排在 trait v2。**`impl[T: Eq] Eq[List[T]]` 今天写不出来**,
   `ImplI.subject` 是个单态 `Ty`,impl 表键是 `(trait_id, Ty)`。

### 9.1 出路:编译期合成结构见证,而不是先做 trait v2

**不做 trait v2。** 因为实测的第 4 行:**每个使用点的类型都是全具体的**(零 `TyVar`),
于是 `Eq[Option[String]]` 可以由编译器**按需合成一个单态字典**、闭包住 `Eq[String]`——
这正是 `impl[T: Eq] Eq[List[T]]` 会产出的东西,只是由编译器生成而非用户书写。
D2 的纯 Dawn HAMT 里 `K` 确实是类型变量,但它的**调用方**在具体类型上,合成后传下去即可,
`WForward` 那条轨 Ord 已经证明能走。

这样换来的是:不必现在就裁决 trait v2 的一致性/重叠/孤儿规则(那是比 D0 大得多的设计面),
而 v1 的「用户只能给自己的非泛型类型写 impl」保持不变。

> **这一节的结论已推翻(2026-07-25,审计后)。** 「不做 trait v2」在 D0 的范围内成立,
> 但它**推不到 D2**,而计划把它当成了一条通用决策。
>
> `WStructural` 是**编译器合成的结构关系**。D2 的纯 Dawn HAMT 需要的恰恰相反:一个
> **非结构的、由类型自己定义**的相等。两件事方向相反,前者顶不上后者。
>
> 实测把这条钉死了:`Array` 的 `==` 是引用同一性,而且**传递地**——一个装着 `Array[Int]`
> 的 record,两份独立构造、内容相同,`==` 得 `false`;嵌进 `Option`/`List`/元组,每一层
> 都是 `false`。HAMT 的节点就是 `Array`,所以 `WStructural` 走到那一格必然退化。
> 于是 `map1 == map2` 对两个内容相同的 map 会是 `false`——而编译器自身有 2,047 处 `==`。
>
> **`Iter` 上同一件事重演**:`impl[T] Iter[List[T]]` 的主体也是泛型的。§4 的 D2 把 Iter
> 写成一行附带项,§6 R5 只把它当「要等两版种子」——两处都没识别出它的前置是同一个 trait v2。
>
> 结论:**trait v2 的最小切片(泛型主体的条件 impl)是 D2 的硬前置**,排进 §11 的 S2。
> 需要裁决的设计面比这一节担心的小:只做 `impl[T: C] Tr[F[T]]` 这一种形状,不开重叠。

### 9.2 于是 D0 的风险评级下调

原评级建立在「每处 `==` 都要改 dispatch」上。但 Core 携带见证之后,**后端可以自己挑物化方式**:
JVM 在见证是派生结构相等时继续发今天的 `INVOKEVIRTUAL equals`(逐字节相同),只有显式 impl 才走字典;
native 永远走字典。而当前语料里显式 impl 有**零处**。所以「巨型 Emit-Change」不成立——
JVM 侧的派生路径本来就是「`equals` 方法 = Eq 字典的 JVM 物化」,这不是妥协,是**被现有运行时逼出来的**:
`DawnMap`/`DawnSet` 是 `java.util.Abstract*` 的子类,在 D2 之前必须继续按 `equals`/`hashCode` 工作。

### 9.3 已落地

`Eq`(id 1)/`Hash`(id 2)进 prelude,六个标量(Int/Float/Bool/String/Bytes/Cursor)有 prelude impl。
显式 `impl Eq[T]`/`impl Hash[T]` 可写可调;标量上的 `eq`/`hash` **去虚化成原语**而不是查字典
——prelude impl 没有函数体可调(后端原生比较),而这也正是「bound 实例化到标量」该塌缩成的形状。
`==` 一个字节没动。`[T: Eq]`/`[T: Hash]` bound 暂时报错:bound 是唯一需要**转发**字典的构造,
而 prelude 字典类还没发射。

**没有 `derive Eq`**——Dawn 的 `==` 本来就对所有类型结构化(spec §4.3),等于每个类型隐式实现 Eq;
trait 的作用是让类型**覆盖**它,不是让类型**选择加入**。

**D0-2**:`[T: Eq]`/`[T: Hash]` 约束打开,字典按需发射——只有程序里真有这类约束时才带上
`dawn/tr/{Eq,Hash}` 与 12 个标量字典单例;没有则逐字节不变(拿改动前的 jar 对拍过)。

**D0-3(语义那步)**:`==` 在有显式 `impl Eq` 的类型上即该 impl。配套两件缺一不可——
①**类的 `equals`/`hashCode` 转发到 impl**(它们是 Eq/Hash 字典在 JVM 上的物化,容器和派生字段比较
都从这儿走关系;只改运算符会让 `a == b` 为真而 `map.get(m, b)` 为 None);
②**`impl Eq` 与 `impl Hash` 必须成对**,单边覆盖就是同一个 bug 换张脸。
见证多了第三种 `WStructural`:约束实例化到没有 impl 的类型时,由编译器合成结构见证
(JVM 上一个共享单例即可,因为结构关系就是值自己的 `equals`;主体静态已知时直接塌缩成原语)。

> **可覆盖带来一个新陷阱**:`impl Eq[T]` 体内写 `a == b` 就是这个 impl 自己,无限递归——
> 覆盖之后结构化默认**从覆盖体内够不着**。`examples/eqhash.dawn` 把这条写在注释里。
> 目前不诊断(直接自递归好查,间接的要做调用图),留给需要时再补。

> 顺带挖出一个先于 D0 的静默 bug:`Bytes` 的相等**只有裸用时**是结构化的,嵌进 record/元组/List/Option
> 就退回引用同一性(实测见 [bytes-design.md](bytes-design.md) 决策 A)。根因正是 D0 要消灭的
> 「相等的含义活在两处」。**现在不修**——半修会更不可预测,全修要等 D2/D3 的纯 Dawn 容器。

## 10. D1 的契约,和它在 JVM 上被迫拆开的地方(2026-07-25)

### 10.1 计划写死的那条语义,JVM 实现不了

§5 与 [runtime-intrinsics-design](runtime-intrinsics-design.md) §5 把 `Array` 定成四个操作
`array_new(Int, T) / array_get / array_len / array_with`,并要求

> `array_with` 的语义必须写成「**纯值语义 + 唯一时就地实现**」……两个后端都做得到:JVM 用
> DawnList 已验证的 CAS 水位线,native 用 Perceus 的 `rc==1`。

**「两个后端都做得到」对 `with` 不成立。** DawnList 的水位线之所以成立,靠的是一个 `with` 没有的
前提:**一个版本从不读自己窗口以外的槽位**。追加写的是 `a[size]`——一格谁都还没见过的存储,
于是「跟别人共享底层数组」和「我改了这一格」不矛盾。而 `with(v, i, x)` 里 `i < len`:那一格
**已经交给 v、也可能交给了别的版本**,任何共享都会被看见。要判断「没人再读它」,需要的是引用计数,
不是水位线——JVM 上没有,native 上 Perceus 的 `rc==1` 才有。

半吊子的做法(拿一个 `owned` 标志做一次性移交)是**不安全的**:它把旧版本悄悄变成非法值,而
「旧版本是不是真死了」恰恰是 JVM 答不上来的那个问题。

### 10.2 于是原语拆成两个,而 12 倍还在

落地的契约(6 个,不是 4 个):

| 原语 | 语义 | JVM 快路径 |
|---|---|---|
| `array_new() -> Array[T]` | 空数组 | — |
| `array_len(a) -> Int` | 长度 | — |
| `array_get(a, i) -> T` | 取值,越界 panic | — |
| **`array_push(a, x) -> Array[T]`** | 追加一格 | **有**:版本正好终止于共享水位时 CAS 认领 `a[len]`,就地写 |
| `array_with(a, i, x) -> Array[T]` | 替换第 i 格 | **无**,总是复制 |
| `popcount(n) -> Int` | HAMT bitmap 用 | — |

`array_new(Int, T)`(预填 n 格)因此也没有了:预填会让 `used` 一上来就等于 n,快路径永远进不去。
建 k 宽的 HAMT 节点改成 k 次 push,同样 O(k)。

**结论不变的原因**:§9.3 量的 12 倍来自**尾块追加**——Clojure 式 PersistentVector 的 `conj`
在尾块未满时就是一次 append,spike 里模拟它的 `push_owned` 写的正是 `tail ++ [x]`。
那 12 倍整个落在 `push` 这条路上,而 `push` 的快路径是**可靠的**。`with` 只出现在 trie 内部节点
的路径复制(每 32 次 push 才碰一次一层)和 HAMT 节点更新上——后者实测只占编译时间 0.5%(§9.2)。

**代价记在账上**:native 上 Perceus 会把 `with` 也变成就地写,所以这个不对称是 **JVM 独有的**,
不是语言语义。契约写的是「纯值语义 + 后端在能证明唯一时就地实现」,JVM 能证明的只有 frontier 那一格。

### 10.3 验收:`scripts/array-contract/`

`Array` 不在语言表面(只有 std 模块能写 `Array`、能调 `array_*`),所以它进不了 `examples/`。
harness 把探针模块拷进一份 std/ 副本再编译,已接 CI。它验两件:

- **值语义**,尤其 `fork` 一格:两次 push 落在同一个版本上,两个结果各看到自己的元素
  (一个赢 CAS,另一个复制)。
- **就地追加真的发生**。这条**故意从 Dawn 里观测不到**,只能拿时钟量:累积形状有它 O(n)、
  没它 O(n²)。实测 **20 万次 linear 14ms vs 2 万次 forked 666ms**——注意 n 还差 10 倍。
  CI 给 20 万次 linear 设 3 秒预算,离两边各差一到两个数量级,不是在赌竞态。

### 10.4 顺手挖出的一个先于 D1 的静默 bug

写探针时踩到:在 std 里**直接**拿具体值调擦除槽位的 intrinsic 会发出无法通过校验的类。
`map_insert(m, "k", 5)` 里 `5` 该装箱进 `V` 的擦除槽,而 lowering 对 `XCallBuiltin` 不做
`adapt_in`——发出去的是 long,描述符写的是 Object,`VerifyError`。

一直没炸,是因为**每个 std wrapper 自己就是泛型的**:值在进 wrapper 时已经擦除,到 intrinsic
手上本来就是 Object。D2/D3 要在 std 里写具体元素类型的数组代码,这个洞会立刻变成日常。

修法是让这类 intrinsic 的**声明签名就是它的 ABI**(`erased_builtin_sig`),box/unbox 回到 Core 层——
和别的调用一视同仁。`unwrap_or`/`expect`/`cast` 不在其列:它们的后端处理器读的是 Core 节点自身的类型
而不是声明类型(`unwrap_or` 按**结果**类型给 fallback 开槽),在这儿装箱反而会弄坏它们。
这个划分一直是隐含的,D1 只是把它写了出来。**对现有程序零 Emit-Change**——会变的那些今天本来就发不出来。

### 10.5 落地的 Emit-Change

一个类:每个程序多一个 `dawn/rt/Array`。拿改动前的 jar 对 `examples/{calc,shapes,traits}` 逐字节对拍,
差异**只有这一个新增文件**,其余一字未动。(它和 `dawn/rt/Lists`/`Maps`/`Strings` 一样是无条件发射的
运行时类;D0 的字典按需发射是因为那是个组合家族,这里是一个固定类。)

## 11. 重排(2026-07-25,纯粹性审计之后)

D1 收工后做了一次全项目审计,问的是「哪里不够纯粹、哪里是临时补丁」。**得到的答案比这个问题严重一档:
有四处已经在给错答案了**,而且都不是新引入的。本节记这次审计,并据此重排 §4 的顺序。

### 11.1 五条实测

不是读代码读出来的推论,是跑出来的。

**一、同一份源码,两个后端给相反的答案。**

```dawn
type P = | P(x: Int, y: Int)
let a = P(1, 2)   let b = P(1, 2)
if a == b { println("equal") } else { println("NOT equal") }
```

JVM 打 `equal`,native 打 `NOT equal`(发出的 C 是 `if ((v281 == v282))`,指针比较)。
两边都退出 0,零诊断。

根因:`resolve_eq_witness` 对「具体类型 + 无 impl」返回 `no_wit()`,lowering 于是发一个
**没有语义的 `CBinary(CEq, ..)`**,含义留给消费者自己发明——`emit.dawn:729` 发 `Object.equals`,
`emitc.dawn:191` 发 C 的 `==`,`interp.dawn:241` 是第三份手写的结构遍历。
**Core 号称承载完整语义,而相等这条最基础的关系没进去。**

**二、`const` 静默取到错误的值,在生产的 JVM 后端上。**

```
const   point = <value>       # to_string(Point(1,2)) 被折成了这个字面量
runtime point = Point(1, 2)   # 同一个表达式在运行期
```

`interp.dawn` 把每个非标量渲染成占位串 `"<value>"`,注释断言这条路不可达,实测可达。

**三、`[T: Eq]` 是一个永不失败的约束。**

`checker.dawn:4395` 对任何缺 impl 的类型**无条件**发 `WStructural`,注释写「equality is total」。
于是两个**函数值**能通过 `[T: Eq]` 并按引用比较,而同一个文件里写 `g == h` 是编译错误
(`checker.dawn:2828`「functions cannot be compared」)。同一个关系,两道门,答案不同。

**四、`unsafe_pure` 不是 FFI 图章,是无条件的效应擦除器。**

它只检查「块内有没有 io」,不检查那个 io 是不是 Java 调用。于是一个签名里没有 `!io` 的 `fn`
可以往 stdout 打印。(升级到「编译期读文件塞进 const」**没能复现**——挡住它的是 `io_read_file`
不在 comptime 解释器实现的那 37/82 个 intrinsic 里,不是效应系统。)

**五、`Bytes` 的相等只在裸的时候按内容,一嵌进任何东西就变回身份——在 JVM 后端上。**

```
utf8("hi") == utf8("hi")                  yes
Wrap(utf8("hi")) == Wrap(utf8("hi"))      no
Blob { data: .. } == Blob { data: .. }    no      # Option / 元组 / List 同
```

`Bytes` 运行期就是 JVM 的 `byte[]`,它自带的 `equals` 是引用同一性,所以内容相等是**手写**的
——而且只写了一处:`emit.gen_equality`,只有 `==` 运算符会走到。派生 `equals` 的字段臂、
发出来的元组类、运行时容器,各有一份自己的「相等」,没有一份知道 `Bytes` 的存在。

这和第一条是同一条缝的两面:第一条是两个后端对同一个 `CEq` 各自发明含义,这条是**同一个后端内部**
「相等」有四五份定义。`bytes-design.md` 决策 A 已记下且**判为暂不修**——只修编译器发得出的那几处,
会留下「record 结构化、List 仍身份」这种更难预测的不一致。闭合它的是 S1(`Eq` 成为真 trait,
`Eq[Bytes]` 只有一份)+ D2/D3(容器变纯 Dawn),不是补丁。

附带一条:`[T: Eq]` 转发的程序发出的 C 引用 `dawn_dict__default_1_eq` 与 `dawn_dict_1_Structural`,
两个符号在整个文件里都没有定义。`CModule.dicts` 只有一个读者——未完成的 C 后端;JVM 后端绕过 Core,
回头查检查器的 `impl_table`(`emit.dawn:1875`)。**所以那张表从来没被验过。**

### 11.2 它们为什么全都躲过了 CI

差分 harness 的准入规则原先写在 `run.sh` 的头注释里:

> a program only belongs here once both backends can compile it, so a failure is always a
> regression, never a gap.

**这条规则是它自己的盲区。** 它只收两个后端已经同意的程序,于是语料只能由实现者随实现增长,
天然覆盖不到实现者没想到的事。结果就是 §7 那句话要打的折:五个语料里 `==` 只出现在 `Int` 和
`String` 上。

第二个盲区是 `codebase-audit.md` TEST-01 早就点过的:**只做后端互比,等于把 JVM 今天的行为
认证成正确答案**;更糟的是**两个后端共有的缺陷会让它们在错答案上达成一致**——凡是编译期折叠的
都属此类,两边折的是同一份 `interp.dawn`,`diff` 检查对上面第二条会报 ok。

**已修(`616d3f7`)**:`scripts/spike-native/` 加四个语料 `eq_adt` / `show_derive` /
`dict_forward` / `const_fold`,各配一份**手写的** `.expect`;harness 从「只 diff stdout」改成
七个具名检查(`emitc` / `cc` / `jvm` / `native` / `diff` / `stderr` / `exit`)。
今天六个检查是红的,记在 `known-red.txt` 里,那是个**双向 ratchet**:清单外的失败是红的,
清单内的检查**开始通过**也是红的——修好一个缺陷,对应那行必须跟着删。

新的准入规则:**语料按语言的语义面收,不按后端的完成度收。**

### 11.3 根因:一件事有几份定义

四条实测指向同一件事。「一个值和另一个值的关系」今天有五套互不知情的机制:

| 关系 | 今天是什么 | 后果 |
|---|---|---|
| `Ord` | 真 trait + 字典 + `derive Ord` | 唯一做对的一个 |
| `Eq`/`Hash` | trait(D0)+ 硬连线 `==` + `WStructural` 合成 + JVM 的 `Object.equals` 物化 + `Bytes`/`Array` 两个身份洞 | 11.1 的一、三 |
| `Show` | **不是 trait**:`AdtI.derives_show` 布尔位 + `is_showable` 静态谓词 + 运行时 instanceof 链,不可覆盖 | 11.1 的二;tagged union 上结构性无解 |
| Map/Set 键合法性 | `invalid_key_part` 独立结构行走 | 与 Hash trait 平行且打架(S3 尾款删,键合法性 = `[K: Eq + Hash]`) |
| 「哪个标量支持什么」 | **六张手抄表**(`eq_scalars` / Ord prelude impl / `impl_subject_ok` / `<` 快路径 / `is_showable` / `derive Ord` 可比字段) | 已经互相矛盾:`cursor.start(s) < cursor.end(s)` 编得过,`list.sort` 却报 Cursor 无序 |

而这五套有**同一个前置**:`impl_subject_ok`(`checker.dawn:1844`)只放行具名非泛型类型 + 四个标量,
`impl_table` 的键(`checker.dawn:95`)是一个**基类型**。**`impl[T: Eq] Eq[List[T]]` 写不出来,
所以每次都绕。** §9.1 把其中一次绕过记成了胜利。

同一个形状还有第三处:`for-in`。`lower.dawn:1589` 的 `lower_for_list` 把 `for x in xs` 降成
`len` + `list_index` 的下标循环——**迭代硬连线到「可随机索引」**。D3 的严格 RB 随机索引实测慢
8–18× 且随 n 增长,所以 `Iter` 不是 D2 的附赠品,是 D3 的正确性前提。

> **更正(2026-07-27,实测)**:上一句把两件事合成了一件。「**不按下标降**」确实是 D3 的正确性
> 前提;「**按 `Iter` trait 降**」不是。`for..in` 今天只迭代 `TyList` 一种类型
> (`checker.dawn:5733`),`for` 处没有多态可言;而 lowering 早就能发具名调用
> (`LSt.prog_fns` + `CCall(CDirect(owner, name), …)`,合成的 `eq`/`cmp`/`show` 就这么发的)。
> 所以 S3 里 `lower_for_list` 换成对 `std/list` 四个游标函数的直接调用即可——下标没了、
> 后端 intrinsic 也没了、编译器里的 arm 数不变,**语言一个字都不用加**。
> `Iter` 买到的是「`for` 能迭代 List 以外的东西」,今天树内无人在等。
> 推导与证据在 [`trait-v2-design.md`](trait-v2-design.md) §7。

### 11.4 重排后的顺序

原顺序按**后端交付物**排(Core IR → 集合 → C 发射器 → Perceus → FFI → 自举)。
新顺序按**「一件事今天有几份定义」**排。前三段全部在 C 后端之前。

#### S0 — 让已经错的东西变红

今天的门禁量不到 §11.1 里的任何一条。这一段不产生用户可见变化,它的价值是让后面每一步的
「做完了」第一次有意义。

| # | 事 | 出口条件 |
|---|---|---|
| S0.1 | 差分 harness 比 stdout + stderr + 退出码 | ✅ `616d3f7` |
| S0.2 | 语料 + 手写 `.expect` + `known-red.txt` ratchet | ✅ `616d3f7` 四个语料六条红;`eq_bytes` 后补,八条红在案 |
| S0.3 | 收回穷尽性检查 | ✅ `c2a891e`。往 `Ty` 插一个探针变体,报错数 **3 → 9**,两个后端都在内(改动前 emitc **一处都没有**) |
| S0.4 | Core IR golden | ✅ `scripts/selfhost-core-diff.sh` 进 CI:三个程序的全量 dump + 编译器 52 模块的哈希清单 |
| S0.5 | 自举耗时基线 | ✅ `scripts/selfhost-bench.sh` + `.baseline`(**本地工具,不进 CI**) |

三点要记:

- **S0.3 的形状不是「删 wildcard」。** 两个后端里字面上的 `_ -> panic` 只有三处;危险的是
  `_ -> <默认值>`(加变体不炸、直接给错答案),以及 **emitc 的五条 `if t == Ty…` 链**
  ——穷尽性检查结构上够不着它们,必须先变成 `match`。而槽宽、load/store 指令、装箱、C 类型
  回答的是同一个问题,所以每个后端立一个 `JvmRepr`/`CRepr` 分类器当**唯一**的全函数,
  其余从它派生。**需要逐变体类名的**(`desc_of`/`unerase`)仍是 `Ty` match。
  划线处写进了 `JvmRepr` 的文档注释:**答案取决于 Dawn 语义的函数(内容相等、哈希、渲染、序)
  不得经它分派**——那里新变体继承 `RRef` 是错答案而不是缺答案。
- **S0.4 的价值不在「多一道保险」。** `CModule.dicts` 今天**没有任何上线的消费者**
  (JVM 走 `lower_fn_only`,回头查 checker 的 `impl_table`),`CParam.mode`/`CSDup`/`CSDrop`
  按设计发射成空——这三块可以整体改错而全树门禁不变红。golden 是唯一看得见它们的东西,
  也正是 §6 R4「Core 不变则两后端都不必重审」所依赖的那个否定判断的证据。
  顺带验一条以前只是假设的事:**std 的 Core 与目标程序无关**(`program_tables` 会把用户 impl
  并进表里,所以这是假设不是定理)——脚本拿三个程序对拍它,不成立就先报这件事。
- **S0.5 量的是比值不是秒数。** fixpoint 的三趟不等价:passA 是**已发布的种子**在编 HEAD,
  对 HEAD 的任何改动(尤其 D2/D3)结构性免疫,正好是理想对照组。故指标 = 同一次运行内
  `passC_user / passA_user`,机器/JDK/源码树增长全约掉,**入库的基线在别的机器上才有意义**。
  今天 = **1.115**,与 §9.2 历史量到的 +11% 同一个量法。wall(离散 4%)与 RSS(换 JVM 差 44%)
  只记不判。**不进 CI**:runner 抖动远大于 15% 的预算。

#### S1 — 语义收口:一台机器,一次建对

四件事今天是四份实现,本该是同一台机器的四个客户。

**动码前的设计定在 [`semantics-closure-design.md`](semantics-closure-design.md)**,那里逐处点了
「两个 Dawn 值相等吗」今天的**七份**独立答案,并把下面每行真正要做的裁决写下来。三条与本表出入的:

- **「必须一起做」只对其中一步成立。** 不可拆的是「展开器 + JVM 类的 `equals` 改成转发」:
  中间状态是「Dawn 的 `==` 与 Map 的键相等成了两个关系」,比今天一致地错更糟。其余各步之间可以停。
- **S1.5 那句「六表合一」不准确。** 六张表回答的不是同一个问题:有一张(`prelude_impls` 用同一个
  `eq_scalars()` 同时铸 `Eq` 和 `Hash`)是**合错了要拆**,另一对(`impl_subject_ok` 与 prelude 清单)
  才是要合的——语言给 `Bytes`/`Cursor` 铸了 impl,却禁止用户给同样的主体写 impl。
- **`Float` 的 `Eq` 与 `Ord` 刻意不同**(spec §4.3,同 Java/Rust):实测 `-0.0 == 0.0` 为 true 而
  `cmp(-0.0, 0.0)` 为 −1。这看着像第八条缺陷,查 spec 才知道是白纸黑字的裁决——收口时合并即改语义。
- **S1.3 那句「`emit.dawn` 不再需要 `impl_table` 参数」只对一半。** 字典那条路确实全断了
  (`CDictRef` 不再回查),但 `impl_table` 还留着两处**与见证无关**的用途:ADT 类的
  `equals`/`hashCode` 被哪个显式 impl 接管(`eq_override`)、以及某个 ADT 的 `Ord` 是不是
  derive 来的。这两个问题问的是**类怎么生成**,不是「这个见证是谁」,Core 不携带它们。

| # | 事 | 消灭掉 |
|---|---|---|
| S1.1 | intrinsic 身份从 `String` 换成 ADT;可见性 / ABI 类别 / 运行时归属写进 `Sig` 声明 | `rt_intrinsic_target` 的前缀链、`erased_builtin_sig` 的**第二套**前缀链、`internal_builtins()` 的四份手抄名单、两张表里的死臂 |
| S1.2 | 结构见证展开器:`WStructural` 在 lowering 期展开成 Core 里可见的逐字段比较(判别式 + 递归 `CEq`),标量塌缩成原语 | 11.1 的一;native 的 `dawn_adt_eq` 需求一并消失 |
| S1.3 ✅ | Core 的字典表成为唯一真相,JVM 后端也读它(删 `emit.dawn:1875` 回查 `impl_table`) | 那张没人验过的表;JVM 手写的五个字典生成器(prelude Eq/Hash/Ord × 标量、两个 structural)与 `gen_impl_class` 一并消失 |
| S1.4 | `Show` 成为第四个 prelude trait,上同一条字典轨 | 11.1 的二;native 的渲染从「结构性无解」变成「和别的 trait 一样」 |
| S1.5 | 标量能力表六合一;Map/Set 键合法性改走 bound | Cursor 那条自相矛盾 |
| S1.6 | `WStructural` 收窄:只发给结构可分解到有 impl 的叶子,`TyFn`/`TyArray` 报错 | 11.1 的三 |

**出口条件**:`known-red.txt` 里 `eq_adt:*`、`eq_bytes:jvm`、`show_derive:emitc`、
`dict_forward:cc`、`const_fold:jvm` 六行全部删除(ratchet 会强制)。**已删四行**
(`eq_adt:native`/`eq_adt:diff`/`eq_bytes:jvm` 见 S1.2,`dict_forward:cc` 见 S1.3),
余 `show_derive:emitc` 与 `const_fold:jvm`,都在 S1.4。`eq_bytes:jvm` 是
其中唯一一条**今天就在生产后端上给错答案**的,S1.2 展开结构见证时它自然闭合——
前提是展开器把 `Bytes` 当成有 impl 的叶子,而不是又一个「引用类型就 `Object.equals`」。

#### S2 — 把语言表达不出来的东西还给语言

| # | 事 | 为什么在这儿 |
|---|---|---|
| S2.1 | **trait v2 最小切片:泛型主体的条件 impl**。`impl_table` 改按 head 索引 + 匹配替换 + 递归解 bound;字典从单例扩到**参数化构造**(新 Core 节点,两个后端各一处) | D2 的硬前置,见 §9.1 的更正块。只做 `impl[T: C] Tr[F[T]]` 一种形状,不开重叠 |
| S2.2 | ~~`Iter` trait;`for-in` 从后端 intrinsic 变成语言 trait~~ **撤下** | 两次改判:先是发现它缺前置(关联类型)与 oracle(RRB),再是发现**它根本不是前置**——`for` 脱掉下标不需要 trait。见 §11.3 的更正块与 [`trait-v2-design.md`](trait-v2-design.md) §6/§7。`for` 的改造并进 S3 |
| S2.3 | `pub opaque type`:库可定义的抽象类型 | 每要隐藏一次表示就现搓一套机制——Cursor 靠编译器铸造的不透明标量,D2 的 HAMT 节点是下一次。**`Array` 曾被列在这儿,是错挂的**,见下方更正块 |
| S2.4 | `unsafe_pure` 收窄成真 FFI 图章;`java_try` / `cast` / `catch_panic` 出通用内建表;`std/io` 的错误契约脱离 JVM | 11.1 的四;`std/io` 今天建在 `java_try` 上,所以「可移植 std」是假的 |
| S2.5 | 发一版 + bump 种子 | **不可压缩的串行点**。§7 把 D1 记成「完成」,但今天 std 里一行 `Array` 都还写不了 |

> **更正(2026-07-27,实测)**:S2.3 行原先把 `Array` 的 `cx.is_std_module` 名字门控
> 列为 `opaque type` 要收编的三套临时机制之一,并因此排了一件「随 S3 一起迁」的待办。
> **`opaque type` 收编不了它**:本机制要一个目标类型,而 `Array` 没有目标——它就是表示
> (`codegen.dawn:1146-1427` 的 `dawn/rt/Array`、`emitc.dawn:142` 的 `ROpaque`);
> 且两者方向相反(本机制公开名字隐藏表示,门控隐藏名字对 std 公开表示)。
> 门控留着,那件待办删掉。S3 真正要用 `opaque type` 的是 std 自己的节点类型与集合门面
> (`opaque type Vec = Array[Int]` 这类,目标是原语,实测今天就能写),不需要动门控。
> 三条实测与顺手修掉的静默重定义缺陷见 [`trait-v2-design.md`](trait-v2-design.md) §8.3。

#### S3 — 集合纯 Dawn 化(原 D2/D3)

内容同 §4 Phase 2,现在可以老实做了。补一件 §4 漏掉的:**`std/list` 的每个函数今天都是
`get(xs, i)` 索引递归**,D3 换 RB 时必须一起改成叶子游走——§4 只安排了 `for-in`。

| 刀 | 事 | 状态 |
|---|---|---|
| 1 | `for` 去下标化:`lower_for_list` 改发 `std/list` 四个游标函数的具名调用 | ✅ 2026-07-27 |
| 2 | `std/list` 九个顺序游走改走同一组游标 | ✅ 2026-07-27 |
| 3 | **D2**:Map/Set 换 `std/hamt`(纯 Dawn HAMT over `Array`),`map_*`/`set_*` 从后端 intrinsic 变成 lowering 期对 std 的具名调用;`Eq`/`Hash` 以字典传入;`DawnMap`/`DawnSet`/`dawn/rt/Maps` 退役 | ✅ 2026-07-27,自举 **+0.7%**(见 [collections §9.6](collections-dejava-research.md)) |
| 4 | **D3**:List 换 `std/pvec`(32 叉 trie + 尾块,纯 Dawn over `Array`);list 原语留在 Core、由后端翻译成 `std/pvec` 调用;`DawnList`/`dawn/rt/Lists` 退役 | ✅ 2026-07-27,自举 **+11.7%**(§9.3 预测 +11%) |

| 5 | **尾款**:`struct_eq` 收窄成 `java_eq`(宿主值的相等,native 见不到 `TyJava`,从此不欠这份实现);结构默认按 trait 参数化(`[T: Hash]` 不再收 `Float`);合成 impl 的见证到它各部分为止;键合法性删掉独立行走改走 bound | ✅ 2026-07-27,零 Emit-Change |

S3 收工:手写 Java **4→1**(只剩 `AdtClassWriter` 这个 ASM shim),`dawn/rt` 里不再有
任何集合类,后端的集合契约就是 `Array` 五个操作 + `popcount`。合计自举 +12.5%。

尾款那一刀关掉了两个能编译却会崩的形状(`Unit` 的 `Eq`/`Hash` 是 JVM 操作数栈下溢,
`Box[T]` 无 bound 的 `==` 落到擦除行走),两个都不在任何语料里——量法与结论见
[`semantics-closure-design.md`](semantics-closure-design.md) §10。

> 次日(#51)发现前一个的根因写窄了:零槽位是机制不是前提。`Unit` 已改成一个普通
> 引用槽位,`Eq`/`Hash` 的禁令改由语义单独支撑。见 spec §2.1 与 §12.2。

**一条排序上的更正**:D2 的原语在 lowering 期换成对 `std/hamt` 的具名调用,D3 不能照做。
comptime 解释器吃的是 Core,而且它**自己实现了 list 原语**——`const B: List[Int] = [A, 4]`
靠的就是那份实现。把 list 原语也在 lowering 期换掉,常量折叠就只剩「解释 `std/pvec`」一条路,
而那要 `array_*`,comptime 是拒绝的。所以 list 原语留在 Core,由**后端**翻译成 `std/pvec`
调用——表示本来就是后端的选择。Map/Set 没撞上这条,只因为 comptime 从来就拒绝它们。

#### S4 — native(原 Phase 3–6)

顺序不变,内容变轻。**C 发射器按收口后的 Core 重导**:今天在语义载体缺席时写的那部分
(ADT 相等、渲染、字典)是负资产,正确动作是先让语料把它照红,不是继续往前补。
Perceus 的出口条件要重写——§4 引用的 99.1% 是**另一个操作**、在一个 D3 要删掉的类上量的。

### 11.5 代价,和不变的部分

**代价说清楚**:S0 + S1 + S2 大约在 D2 之前插了 3–5k 行,native 自举整体后移。
换来的是 S3 和 S4 的每一步不用再打补丁。

**不变的**:§1 决策总表除「不做 trait v2」外全部维持——两后端长期平权、直接上 Perceus、
发 C、完整 Core IR、不单态化、UTF-8、验收三道。§2 的排序结论(D 必须在 C 运行时之前)也维持,
S1/S2 只是又在它前面插了两段。

**这次审计本身的教训**,和 Phase 0 那条是同一条的另一面:Phase 0 记的是「两条路都在是最强的
oracle」;这次记的是**「两条路都在」不会自动变成 oracle,得有人去写那个逼它们对答案的语料**。
四条实测里有三条在 Phase 0 收工那天就已经存在了,而当天的 CI 是绿的。

## 12. `Unit` 在两个后端上的宽度(2026-07-27,#51)

`dawn_rt.h` 从一开始就写着「Unit is a value, not an absence」,C 后端给它一个字节;
JVM 后端却给它 **0 个槽位**、描述符 `V`。零宽在 JVM 描述符里没有拼法,于是形参、ADT
字段、闭包捕获、trait/impl 方法全都写出**非法描述符**,类加载即死;`opaque type H = Unit`
还能绕过 checker 里那四条写成 `t == TyUnit` 的禁令。spec §2.1 明写 `List[Unit]` 合法,
可 `map` 一个 `List[Unit]` 编译不过——lambda 形参被拒。

**裁决:JVM 跟 C 走**,`Unit` 是一个普通引用槽位(`Ldawn/rt/Unit;` 单例)。`RUnit` 变体
删掉,以此逼编译器指出每一个要重读的点;`slots_of(t) == 0`(问宽度)改成 `is_bottom(t)`
(问有没有值)。五条 `Unit` 禁令只留构造子字段那条——它讲的是建模不是描述符——并让它
peel opaque。

顺手关掉的 C 侧同族缺陷:`c_type(TyUnit)` 是 `dawn_unit`(一个字节),`slot_of` 却把它
归到 `dawn_slot` 的**指针**成员。`dawn_slot` 加了 `u` 成员、加了 `dawn_box_unit`,
两边这才一致。

**它为什么一直没被发现**:`scripts/spike-native/run.sh` 在 JVM 那一跑失败时,会把
`emitc`/`cc`/`native` 全标成 `blocked`——**JVM 拒绝的程序,C 后端永远测不到**。而这一族
里 JVM 恰恰是先崩的那个。语料 `unit_value.dawn` 现在把七项检查全走一遍。

## 13. S4 第一程:std 进翻译单元,known-red 清空(2026-07-27/28)

### 13.1 顺序是被实测定死的

`__emitc` 原本只 lower **程序自己的**模块。S3 之后集合就是 std(`[1, 2]` 调 `std/pvec.of_array`),
所以任何拿着 list 的程序都在 `cc` 那步撞墙。07-27 试过直接把 std 链进来,结果整个语料一起红:
std 自己要 `cursor_start`,C 侧没有。于是顺序写死:**先补 intrinsic 长尾,再链 std**。

这一程按那个顺序走完了:C 运行时把契约整个实现了一遍(cursor 8 / str 9 / bytes 7 / io 8 /
parse 3 / code_points 与 join / java_try 与 catch_panic),emitc 改成从 intrinsic 表读
(见 [`runtime-intrinsics-design.md`](runtime-intrinsics-design.md) §12.1),std 随即链得进去。
`scripts/spike-native/known-red.txt` **现在一条不剩**。

### 13.2 链进 std 之后炸出来的四个静默误编译

都在**擦除边界**上,都能编译,都是 JVM 靠 verifier 和 LambdaMetafactory 免费拿到、C 必须自己写的:

| 缺的那一下 | 症状 |
|---|---|
| 元组字段按构造点的具体类型存 | `map_from([(1, "one")])` 把 key 当指针读 → 段错误 |
| 列表字面量元素不装箱 | `[1, 2, 3]` 渲染时同上 |
| 闭包 adapter 用 lambda 的具体类型 | `map` 一个 `List[Unit]`:`int64_t` 返回值被当指针 |
| impl 符号按**实例化**主体命名 | 调用点 `List_Int`、定义点 `List_Var123`,链接失败 |

前三条的共同答案是同一句:**擦除位置上的东西一律走 slot**。元组在 JVM 上是两个 `Object`
(无论从什么建的),`Fn` 接口的 `apply` 也是擦除的——C 侧照抄这个形状即可。

第四条不是形状问题而是**一件事两份定义**:JVM 的 `codegen.subject_name` 特意丢掉类型实参
(「名字标识的是 impl,而相干性保证一个 head 至多一个 impl」),emitc 用的 `ty_key` 却保留 list 的元素。
`ty_key` 的注释写着它假设「impl 主体都是具体类型」——那个前提在 std 写下
`impl[T: Show] Show[List[T]]` 的那天就没了。规则挪进 `core.subject_key`,
两边由 codegen 的测试 "an impl is named by its head" 拴住。

### 13.3 顺带

- **comptime const** 现在两个后端都发:标量内联(JVM 也是这么做的),结构化的仍然拒绝并说明理由
  ——C 没有 `<clinit>` 可以重建它。const 按简单名解析,所以那张表是**每模块**一份
  (std/pvec 的 `MASK` 和 std/hamt 的 `MASK` 是两个常量)。
- **`panic` 分支**:JVM 的 ATHROW 不会落下来,C 的赋值却照写不误,`dawn_str t = DAWN_UNIT;` 编不过。
  `no_value()` 统一回答「这个分支有没有值可赋」。std/str 的 `substring` 第一行就是。
- **Bytes 的 `++` 和 `==`**:前者发的是**字符串**拼接,后者比的是指针。`eq_bytes.dawn` 本来就是为这个写的语料,
  之前一直卡在 `emitc` 那步没跑到。

## 14. S4 第二程:门控裁决,与 42 处的真实重量(2026-07-28)

### 14.1 裁决:两个 main 共享前端,不引入条件编译

native 编译器不带 JVM 后端,需要一个门控机制。两个候选:**语言级条件编译**(`#[cfg]` 一类)或
**两个 entry 共享前端**。定为后者,判据是语言表面积:条件编译一旦进语法就再也拿不出去,
而两个 main 是纯工程手段、零语言表面积。

这条裁决**重新划了「关键路径」**,而这正是它值得先做的原因——它决定余下 90 处 `use java` 里
哪些要动。上一程写下的「getenv / 二进制 IO / 临时文件不在关键路径上」在一天后被它推翻:
**包管理是目标无关的**(按 url+hash 取 Dawn 源码包,和发射什么后端无关),所以 pkgfetch 必须
跟着 native main 走。真正留在 JVM main 的,是「启一个 JVM 去跑刚发射出来的 class」那部分。

### 14.2 42 处不是一码事:按「归哪个 main」重量

上一程按**碰了什么**分类(文件/进程/网络),这一程按**归哪个 main** 重分,答案很不一样:

| | 处 | 归属 |
|---|---|---|
| `maven` | 6 | **JVM 侧**。解析 Maven 坐标只对 JVM 目标有意义;唯一调用点在 `dawn build` 的 java-deps 分支 |
| `main` 的 `run`/`build`/`test` | 多数 | **JVM 侧**。classpath 属性、`ProcessBuilder java -jar`、找 `JAVA_HOME`/`native-image`、`canExecute` |
| `main` 的 `fmt`/`doc` | 2 | 目标无关,而且 `io.exists` 早就够——上一程漏网 |
| `analyze` | 3 | 1 个**死导入**;1 处路径规范化 |
| `lsp` | 6 | `System.exit` 漏网 1;`System.in` 1(+3 处为它绕的 method handle);路径规范化 1 |
| `stdlib` | 1 | 换机制:std 源码在 JVM 上从 jar 资源读,native 得另有出处 |
| `pkgfetch` | 19 | 真要迁,且卡在两件事上(§14.4) |

`analyze.canon` 和 `lsp.canon` 是**逐字重复的同一个函数**——一件事两份定义,和上一程 `subject_key`
那条同类。

### 14.3 九个原语,一次休眠落地

`cwd`、`getenv`、`read_bytes`/`write_bytes`、`delete`、`rename`、`temp_dir`、`is_symlink`、`read_stdin`。
判据没变:每一项在编译器里都有一个今天走 `use java` 的调用点。**仍然没进来的**是 classpath 属性、
进程派生、`canExecute`——它们只为启动 JVM 而存在。

两条设计不是随手定的:

- **`rename` 取 `rename(2)` 的语义**(同一文件系统内原子、否则失败)。调用方在做「下载、校验、
  按内容哈希发布」,更弱的语义不成立。`temp_dir` 因此收一个 parent 参数——暂存目录必须和目的地同盘,
  原子才谈得上。
- **`read_stdin` 是 `eprintln` 的同一个故事**:`System.in` 也是静态字段,所以 LSP 读消息帧同样绕了
  method handle。通道不是 method handle。

`io_files.dawn` 在休眠这一步就把九项在两个后端上跑通了(语料由 HEAD 编,不受种子纪律约束),
并顺手查出一个**两个后端答案不同**的真偏离:`io_write_file` 在 JVM 侧一直建父目录,C 侧没有,
所以「往还不存在的目录里写文件」只在一个后端上成功。没有语料问过这件事。

harness 也改了一处:两个后端的运行都把 stdin 接到 `/dev/null`。读 stdin 的语料本来会挂住开发者的终端,
而且在 CI 里读到的东西还不一样。

### 14.4 pkgfetch 卡在两件事上(都不在这一刀内)

1. **`Bytes` 没有构造器。** Dawn 里 `Bytes` 目前是**只读**的:能从 `String` 拿(`bytes.utf8`)、能切、
   能读,但造不出一个任意字节序列——要发出 `0x80` 就得有一个 UTF-8 编码等于它的 `String`,而那不存在。
   解压要落盘就必须能造。`Array[T]` 是天然的缓冲区,但它是 **std-only** 的(只有 std 能 `array_*`),
   所以要么 sha256/inflate 进 std,要么给 std 一个 `opaque type BytesBuf`(`Cursor` 是同类先例)。
2. **HTTP/TLS 写不了。** SHA-256、DEFLATE、zip 读取器都是纯 Dawn 能写的(tar 读取器早就是),
   HTTPS 不是。三条路:一个 `io_http_get` intrinsic(JVM 用 HttpClient、C 用 libcurl——但那给 native
   运行时加了一个外部依赖)、shell out 到 curl、或者 native 编译器不支持远程包。**这是下一个裁决。**
