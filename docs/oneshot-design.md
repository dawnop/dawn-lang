# 一次性恢复（one-shot resumption）：勘察结账

> 状态：**proposed**。2026-08-31 的四路勘察已结账，本文是它的决策面，四份原始报告是档案
> （§10）。勘察给出了本仓在这个问题上的第一批实测数字：JVM `jdk.internal.vm.Continuation`
> 每次 perform 70 至 460 ns、native 影子栈税 15%（朴素）/ 5%（内联）/ 2 至 4%（地板）、
> 效果传染面 48/3320 = 1.45%。三条路线被实测排除，剩两条活路。**路线建议是 yield 冒泡**
> （§5），对拍与代价在 §4。**本文不是已批准的项目**：立项与否，以及立项后的六个待裁点，
> 等用户裁决（§9），在那之前不要照着实现。
> 勘察基线 `main = 5441ed4`，编译器为 v0.70.0，文中 file:line 均对该提交。
> 相邻的既有裁决：[effects-design.md](effects-design.md) §8.3（multi-shot 必须与 RC 一起
> 单独立项）、[handler-state-design.md](handler-state-design.md) 前言的期权记录、
> [spec.md](spec.md) §6.5 的五条裁决。本文不改规范，只登记它们会被怎么波及（§8）。

## 1. 缘起与裁决背景

**用户 2026-08-31 定了两件事。** 第一，**async/await 永久否决**，理由是函数染色；这条不
留重开条件。第二，**一次性恢复作为研究方向勘察，先把成本量出来**，量完再决定立不立项。
本文是第二件事的产物。

**否决 async/await 是一次得分，不是一个缺口。** 生产侧的并发今天已经在虚拟线程上：
`packages/web/src/server.dawn:773` 是 `Executors.newVirtualThreadPerTaskExecutor()`，
`:774` 把它装进 `HttpServer`，请求体读 `stream.readAllBytes()`（`:87`）、响应体
`up.transferTo(out)`（`:198`）、`main` 阻塞在 `CountDownLatch`（`:788`），全是直接风格的
阻塞调用，没有一处 CPS，也没有一处想变成 CPS。整个 `packages/` 里 `effect` 声明为零、
`with handle` 为零。也就是说：**JVM 已经免费给了这个项目结构化并发，而效果系统的血统正是
用来消灭染色的**，再引入一套 `async fn` 只会把已经不染色的东西重新染上。

**研究语言的姿态。** 本仓当前取向是自用研究项目，不为采用者做工作（冻版本、宣传），正确性
与自用体验照常。所以这份勘察的验收标准不是「能不能做」，而是本仓自己的那条判据
（[effects-design.md](effects-design.md):528-533）：

> 加不加效果不问优雅，只问加了之后有没有一条今天写不出的断言变得写得出。

这条判据在 §6 被逐字兑现：勘察找到了那条断言，也找到了它今天为什么写不出。

## 2. 尾恢复档今天的形状

### 2.1 一个降糖，没有 Core 节点

`with handle` **没有自己的类型化节点，也没有 Core 节点**。检查器把它就地改写成两件普通东西
（`selfhost/src/check/checker.dawn:5587-5757`，`check_handle`）：

```
with handle E { arms }; rest
==>
{ <cell lets>;                                  # checker.dawn:5675-5677
  let ev$E = E_record { arm0_clo, …, armN_clo, arm_env };   # XCtor, :5736-5738
  rest_thunk(evidence_pack) }                   # XApply, :5749-5751
```

`selfhost/src/lsp/lspq.dawn:706` 把这句话写在注释里。操作调用是**证据记录上的一次取字段加一次
闭包调用**（`checker.dawn:7074-7091`），lowering 把它降成一次普通间接调用
（`selfhost/src/ir/lower.dawn:3430-3435`，`CCall(CDynamic(tv), …)`）。
`selfhost/src/ir/core.dawn:96-208` 的 40 个 `CExpr` 加 6 个 `CStmt` 里**没有** `CHandle` /
`CPerform` / `CResume` / prompt / label 中的任何一个。

**这对勘察是好消息的那一半：定界符已经恰好是一个调用点**（`checker.dawn:5751`）。不必发明
prompt，只需要包住一个本来就在那儿的调用。**坏消息的那一半：Core IR、两个发射器、RC pass、
comptime 解释器从来没听说过效果**，任何恢复档都要在检查器以下从零引入这个概念。

### 2.2 三行承重代码

尾恢复这一档没有任何「形状检查」，它是被结构强制的，承重的就三处：

| file:line | 它说了什么 |
|---|---|
| `selfhost/src/check/passes.dawn:1202` | `fields ++ [FieldI { name: op.name, ty: TyFn(ptys, ret, EPure) }]`：证据记录里每个操作一个闭包槽，**行是纯的** |
| `selfhost/src/check/checker.dawn:5709-5711` | 臂按 `Some(field.ty)` 去 `check_lambda`：**臂的类型就是操作的签名** |
| `selfhost/src/check/checker.dawn:5749-5751` | `with handle` 块的类型**就是**块剩余闭包的返回类型，剩余原地施用恰好一次 |

一次性恢复要把第一处变成 `fn(P…, (R) -> A) -> A`、把第三处变成一个应答类型多态的判断。
**语言里今天没有应答类型这个变量**，因为不需要：块的值就是剩余的值。这是判断形状的改动，
不是判断里多一条 case。

诊断把这一档说成了大白话，它们会随之移动：`checker.dawn:5707` 的提示
`"the arm is the operation's body: " ++ ty_show(cxa.adts, field.ty)`；`checker.dawn:2025-2027`
对臂里 `break`/`continue` 的提示 *"an arm is called from wherever the operation is raised"*。

### 2.3 三个形制问题的答案

**(a) 臂的闭包会被存起来吗，会被延后吗。** 会存，从不延后。臂闭包是 `ev$E` 记录的一个字段
（`checker.dawn:5736-5738`），绑成一个不可拼写的局部（`:5740-5741`），作为隐藏证据实参**向下**
穿过调用链；但它只在 raise 点被同步读出并施用，没有第二个消费者。两件结构事实让「延后」今天
不可能：臂的字段类型带纯行（`passes.dawn:1202`），证据不能进捕获表（检查器
`checker.dawn:4880-4892`，lowering 断言 `lower.dawn:471-478` 的
`refuse_evidence_captures`）。行为侧的判决性探针是 P-E3
（[handler-state-design.md](handler-state-design.md) §7.6：内层答 41、外层答 900，实测 901 而非 42）。

**(b) Perceus 或 JVM 发射是否依赖 raise 点的帧还活着。** C 侧是结构性的，JVM 侧是构造性的，
而且 handler 与 raise 点之间的 LIFO 关系是不变量不是巧合。`ev$E` 是 `with handle` 块的局部，
raise 点能看见它只因为它是从 `checker.dawn:5751` 那次调用一路穿下来的隐藏实参；证据既不能被
捕获也不能被存储，所以 **raise 点永远是安装点的后裔帧**。Perceus 那边，
`runtime/c/dawn_rt.h:502-568` 每函数一个 `void *dawn_own[n+1]` 加一个
`__attribute__((cleanup))`，局部 oracle 断言「每个绑定在每条路径上恰好被 drop 一次」
（[perceus-design.md](perceus-design.md):377-381）。JVM 那边操作调用就是操作数栈上一条
`INVOKEINTERFACE apply`（`selfhost/src/jvm/emit.dawn:1983-2011`）。
`docs/audit/error-model-design.md:695-698` 把这件事说成了句子：「没有一等 `resume`，臂物理上
就跑在 raise 点的栈上」，并且写明「若将来引入非尾恢复的臂，这个答案会翻转」。

**(c) 臂里的 `?` 早退今天怎么退栈。** 它不退栈。`check_propagate_typed`
（`checker.dawn:2040-2070`）从最内层 `LambdaCx` 读 `expected_ret`，对臂来说那就是操作声明的
返回类型，所以臂里的 `?` 只有在操作自己返回 `Option`/`Result` 时才成立，而且它**从臂返回**，
成为操作的结果，越不过 raise 点。lowering 侧 `lower.dawn:3874-3903` 就是一个 `CBlock` 加一个
`CSIf` 加一个 `CReturn`，没有异常、没有 longjmp、没有 unwinder。
**结论：一次性恢复的早退没有现成退栈路径可复用**，那是全新的控制流。

### 2.4 前端与门禁的量

前端便宜：`handle` 已经是上下文关键字（`selfhost/src/front/parser.dawn:2525-2528`），全仓
`grep -w resume` 只有两处散文命中，没有任何东西预期一个 `resume` 绑定。真正的前端成本是
`HandlerArm`/`EHandle` 的**arity 变更**，上一次同类变更（`EHandle` 加 `cells`）实测约 8 处匹配
（[handler-state-design.md](handler-state-design.md):364-370），其中 3 处在 `lsp/lspq.dawn`、
1 处在 `ir/interp.dawn`；`fmt` 是 token 流重排版器，上一次同类语法新增**零改动**。
comptime 解释器免费：`with handle` 在编译期本来就被拒（`checker.dawn:5599-5603`）。

门禁量大但是记账工作：`with handle` 全仓 464 处、声明 `effect` 的文件 103 个、`std/` 与
`selfhost/src/` 各为零（由 `scripts/doc-check.py` 的 `check_named_effect_status` 双向钉住）。
会整体移动的是 `scripts/effect-evidence-contract/`（20 条 roster、14 个生产变异体）、
`scripts/spike-native/effect_*.dawn`（19 个程序，两后端）、`scripts/checker-corpus/` 的 69 处、
`scripts/core-golden/`（ABI 一动就是全量重录，且按 arch-split 的教训只能重录不能自动合并）、
`scripts/wasm-dom-contract/collect.sh`（直驱契约的 fixture 就是一个 `with handle` 加一个格子）。
量的参照是 handler 局部状态那次：三刀，加一条 spike-native 语料、一行 roster、三条 rc-contract
断言、一个生产变异体、两个 checker-corpus 用例、八个 grammar-corpus reject
（[handler-state-design.md](handler-state-design.md):806-810 记到秒）。

## 3. 排除的路线，各带实测证据

### 3.1 全栈复制（Koka / libmprompt 式）：结构性死亡

不是「代价高」，是这个后端按今天发的码办不到，三条各自独立：

1. `dawn_handlers` 是一条**栈地址**链表，`struct dawn_handler *prev`
   （`runtime/c/dawn_rt.c:1745`），每个节点都是某个帧上的局部。把栈复制到别处，每个 `prev`
   都指回原处。
2. `jmp_buf jb`（`dawn_rt.c:1743`）存的是 SP/FP，搬迁之后恢复它就是跳回旧地址区间。
3. `dawn_own` 槽是指进帧里的 `void**`，cleanup 属性绑在特定帧地址上的一个变量。

重定位一份复制栈需要知道每一个内部指针，也就是精确栈图，而 C 不给。Koka 能做是因为它发自己的
帧表示，Dawn 发的是普通 C 局部（`selfhost/src/c/emitc.dawn:2070-2088`）。
**把「栈复制」从 native 的选项表里划掉，理由与 wasm 上划掉它是同一条。**

### 3.2 每 handler 域一条侧栈：三个实测坏消息

切换本身不贵：`swapcontext` 往返（一次 perform 加一次 resume）实测 **339.4 ns**，其中
**264 ns 是它做的两次 `sigprocmask` 系统调用**（`sigprocmask(SIG_SETMASK)` 单测 131.8 ns）。
手写寄存器切换（boost.context 式，不碰信号掩码）会落在 75 ns 以下，但那是推断不是测量。
**切换代价不是约束条件**，坏消息在别处。

**其一，ForcedUnwind 跨边界会 abort。** 用 `dawn_rt.c` 的原样机制（带 `jmp_buf` 与 `prev` 的
handler 结构、`dawn_handler_landing` cleanup、指针身份认目标、带 stop function 的
`_Unwind_ForcedUnwind`）做探针，handler 放在主栈、从 `makecontext` 侧栈上 raise，结果是
`STOPFN: unwound past the handler (END_OF_STACK)`，`exit=134`。在真运行时里那就是
`dawn_rt.c:1879-1886` 的 `abort()` 加 `"dawn: unwound past the failure handler"`。侧帧的
cleanup 也没跑，所以这次 raise 在 abort 之上还漏了。**推论：每条侧栈都要有自己的基座
`dawn_handler`，跨挂起边界的 raise 必须在基座接住、手工搬过切换、再抛一次**，而这是在运行时里
注释最反复强调「被搞错过多少次」的那一部分上加新机器。

**其二，ASan 官方不支持，而且每次都自己说。** 每一次消毒运行都打
`WARNING: ASan doesn't fully support makecontext/swapcontext functions and may produce false
positives`。而消毒构建正是本项目 native 正确性论证的载体：`scripts/spike-native/run.sh:215-220`
带 `-fsanitize=address` 加 `detect_leaks=1` 跑整套语料，而 `run.sh:44-58` 记着
`.leaks-on-catch` 豁免家族在 #193 之后被**删掉**，理由是「没人用的豁免是下一次回归的藏身处」。
可以用 `__sanitizer_start_switch_fiber`/`__sanitizer_finish_switch_fiber` 修，但那是更多机器，
而且要穿到每一次切换上。

**其三，LSan 对一次性恢复恰好要漏的那一类完全失明。这是整份勘察最锋利的一条。** 探针把
「捕获后不恢复直接丢弃」做到规模：200 条续延，每条挂在自己的侧栈上、各持一个 4 KB 的 owned
对象，然后全部丢弃（释放侧栈，从不跑 release），擦栈、`body_ctx` 清零。结果：
**800 KB 真漏，零条报告**。同一个二进制、同一次运行里的阴性对照，一个 777 字节的无引用
`malloc` 被立刻报出来并带栈回溯。工具是好的，它只是看不见这一类。

这正是本仓自己那条「门禁的绿没有信息量」的教科书实例：**native 的内存 oracle 会在一次性恢复
引入的那个 bug 上变绿。** 编译期那侧也一样：`selfhost/src/c/rc.dawn:28-31` 的 `rc_check` 坚持
「每个绑定在每条路径上恰好释放一次」，而一条挂起的续延是一条**还没走完**的路径，丢弃一条未恢复
的续延是 `rc_check` 根本没有表示的路径。[effects-design.md](effects-design.md):508 早就写下了
这句判词：Perceus 的局部 oracle「假设控制流正常返回」。

### 3.3 帧税：把「谁来丢弃被放弃的续延」这一问的价格买回来

答案本来就在树里：wasm 因为没有 unwinder，已经让每个 own 数组自注册到一条影子栈上
（`dawn_rt.c:1961-1986` 的 `dawn_wasi_own_push`/pop），raise 时手工走一遍逐槽 drop
（`dawn_rt.c:2000-2010`）。**这正是「不靠平台 unwinder，把一段栈区间里的 owned 槽全丢掉」这个
原语**，它存在、被门禁看着、只是被关在 `#ifdef __wasi__` 里。把它对 native 也打开，丢弃一条续延
就是同一个循环，边界从 handler 的 `own_depth` 换成续延的基座深度。**代价是每个调用帧一次 push
一次 pop，对每个 native 程序永远收，不管它用不用效果。**

这笔税已经实测（分支 `own-stack-tax`，提交 `cf10003`；`DAWN_OWN_FRAME(n)` 无条件 push，pop 折进
`dawn_own_drop` 这个 cleanup，于是 unwind 按最内层优先的顺序恰好注销它销毁的那些）。两个编译器
从**逐字节相同的发射 C** 与相同 cc 参数构建，唯一差别是链进去的 `dawn_rt.c`；native fixpoint 仍然
成立。WSL2，5 次交错重复取中位数：

| 工作负载 | base | 无条件（已提交） | 内联版 | 最大 RSS 税 |
|---|---|---|---|---|
| W1 `dawnc emitc nmain.dawn`（3.66 亿次 push，高水位 523） | 6.60s | **7.56s（+14.5%）** | 7.14s（+8.2%） | +0.02% |
| W2 `dawnc check nmain.dawn`（只前端） | 2.65s | **2.96s（+11.7%）** | 2.78s（+4.9%） | +0.06% |
| W3 帧密集微基准（3.6 亿次 push） | 3.14s | **3.72s（+18.5%）** | 3.30s（+5.1%） | 噪声 |

每帧折算：W1 2.63 ns（无条件）/ 1.48 ns（内联），W3 1.61 ns / 0.44 ns。阳性对照
`DAWN_OWN_STACK_STATS=1`：nmain 编译 `pushes 365518697, high water 523, live at exit 0`；
`recover_live` 做 100 次强制 unwind 之后仍然 `live at exit 0`，`dawn_own_stack_pop` 里的 LIFO
断言一次没响；基线二进制什么都不打印（阴性对照）。烟测：`scripts/spike-native/run.sh` 的 10 条
（含 `effect_handler_state`、`bracket_fatal`、`deep_stack`、`recover_*`）全过，ASan 带
`detect_leaks=1` 全程在跑，`differential ok`。

**诚实读法：接近 20% 而不是接近 2%，但成本的形状说的是「贵，不是被定价出局」。** 一多半不是机制
本身而是那次跨函数调用：把 push/pop 挪成头文件里的 `static inline` 就掉到 4.9 至 8.2%，而且还有
余量（无条件的 8 字节存进 bump 指针区、热路径上不判 realloc、release 构建去掉 LIFO 断言）。
公道的说法是「朴素连接的侧栈收 15%，调优过的收约 5%，地板是每帧一次存加一次减，算 2 至 4%」。
**RSS 税是零**（高水位 523 项约 4 KB，对 309 MB 工作集）：反对侧栈的理由不是内存。
两条不能跳过的注记：`selfhost-bench-contract` **没有**用作负载，因为 `selfhost-bench.py` fork 的是
**JVM release jar**，对 C 运行时的改动结构性失明，W2/W3 是替补；**wasm 腿未验证**（本机没有 wasi
sysroot），wasi 下的 `__attribute__((destructor))` 是最想被人复核的那一件。

### 3.4 wasm：只有 CPS 活得下来

从**已发布的产物**实测（`site/build/tea/counter.wasm`，502 KB，2026-08-30 构建）：导出恰好只有
`memory` / `_initialize` / `dawn_turn`；有 tag section（来自 `-fwasm-exceptions`）；global section
一共 8 字节，即 `__stack_pointer` 且**不导出**；**没有任何 `asyncify_*` 导出**。构建参数在
`selfhost/src/nmain.dawn:551-560`，没有 Asyncify pass、没有 JSPI、没有 emscripten 层。
没有 `ucontext`；也不能复制栈，因为 clang 的 wasm ABI 会分裂局部：取过地址的局部（`dawn_own`
数组就是）住在线性内存的影子栈上，而返回地址与未取地址的局部住在引擎自己的栈里，线性内存够不着。

**还有一条更结构性的事实。** reactor 的唯一入口由驱动追加（`selfhost/src/nmain.dawn:398-409`）：

```c
__attribute__((export_name("dawn_turn")))
int32_t dawn_turn(void) { int rc = main(0, (char **)0); fflush(NULL); return (int32_t)rc; }
```

**每一轮都从头调 `main`**，`dawn_rt_init` 每轮跑一次，**没有任何 Dawn 栈跨得过一轮边界**，
活下来的只有一个类型擦除的 retained root（`dawn_rt.h:679-686`）。所以即便有一套能用的栈切换，
续延也跨不过轮边界，而轮边界正是 UI 唯一想挂起的地方。

### 3.5 JVM：`jdk.internal.vm.Continuation` 能用，但不能拿去发布

三个常见反驳全是假的，逐条探过：不需要 `--enable-preview`（JDK 26 与 GraalVM CE 21.0.2 上只加
`--add-exports java.base/jdk.internal.vm=ALL-UNNAMED` 就编就跑）；**不被 major 52 的 classfile
钉子挡住**（把一个能跑的类的第 4 至 8 字节改写成 major 52 再跑，输出照旧）；用户不需要命令行参数
（jar manifest 里写 `Add-Exports: java.base/jdk.internal.vm`，裸 `java -jar` 即可，已验）。
接线是两处一行改动：`selfhost/src/jvm/jarw.dawn:134-137` 的 manifest，与
`selfhost/src/main.dawn:548` 的 `child_java_cmd()`。

实测（JDK 26，每项 20 万至 200 万次，已预热）：

| 操作 | ns |
|---|---|
| 基线：今天的 perform（一次接口调用） | **1** |
| `new Continuation` + 跑完，不 yield | 31 |
| `new` + `run` + 深度 0 处 yield + `run` | 186 |
| 同上，深度 8 | 368 |
| 同上，深度 64 | **459** |
| 同上，深度 512 | **6,430** |
| 复用续延，`resume` + `yield`，深度 0 | 73 |

**读法：JVM 上一次性恢复每次 perform 70 至 460 ns，而且是 O(perform 与 prompt 之间的帧数)**，
因为冻结/解冻在复制栈。512 层间隔时是 6.4 µs，是尾恢复 perform 的 6400 倍；而「handler 装在
靠近 `main` 处、perform 散在调用树深处」既是病态情形，也是人们自然的写法。

**不能发布的理由只有一条，但足够：** 它是无兼容承诺的内部 API，且是 HotSpot 专有，而本仓的
CI 跑 JDK 21/26 双矩阵（`.github/workflows/release.yml:48`）正是因为不信任单个 JDK 能替别的
JDK 说话。**作研究探针没问题，作可发布的档位就是把 JVM 腿押给 Oracle 的一个小版本。**
虚拟线程模拟也在这一格被划掉：虚拟线程之间的交接 170 ns，但一边是平台线程时是 27,068 ns
（载体钉住 / 调度器唤醒），差 160 倍且**在源码里看不出来会拿到哪一个**；更要命的是它 JVM 独有，
而 `native-diff` 门禁就是为了拒绝「只在一个后端存在的语言特性」而建的。

## 4. 两条活路的对拍：静态选择性 CPS 与 yield 冒泡

### 4.1 传染面：1.45%，而且是闭合数字不是下界

对两棵树里每一个 `.dawn` 声明做了签名扫描（按 `docs/grammar.ebnf:64-69` 的效果文法，只看返回
类型区域里深度 0 的 `!atom` 组，所以 `fn(T) -> U !e` 这种**参数**上的行被正确排除），
**3320 个声明零解析失败**：

| 根 | 纯 | 只 `!io` | 具名地标签 | 关联投影 | `!e` 变量 | 合计 |
|---|---:|---:|---:|---:|---:|---:|
| `selfhost/src` | 1601 | 480 | 0 | 0 | 0 | 2081 |
| `std` | 254 | 30 | 0 | 0 | 25 | 309 |
| `packages` | 358 | 61 | 0 | 8 | 0 | 427 |
| `examples` | 184 | 35 | 12 | 0 | 2 | 233 |
| `site` | 211 | 58 | 1 | 0 | 0 | 270 |
| **dawn-lang 合计** | **2608** | **664** | **13** | **8** | **27** | **3320** |
| `dawnop-site/backend-dawn/src` | 419 | 478 | 10（`Clock`） | 0 | 0 | 907 |

需要「可挂起」变体的是后三类：**48/3320 = 1.45%**（连 backend-dawn 是 58/4227 = 1.37%），
按源码行是 **516 / 100 027 行 = 0.52%**。

**为什么这是闭合数字而不是下界。** 吸收禁令（[spec.md](spec.md) §6.2 规则 7，
[effects-design.md](effects-design.md):442-443 复述：一条行只增不减，唯一的减法点是
`with handle`）意味着一条行**已经是**函数体能触及的东西的传递闭包。若 `f` 调 `g` 而 `g` 能挂起，
`f` 的 ABI 行就带着 `g` 的标签。**于是「需要可挂起变体的函数集合」恰好等于后三类，由 soundness
保证，不需要任何调用图分析。效果系统已经把传染分析的钱付过了。**

**`io` 的裁决直接决定这张表。** 若 `io` 永不承载一次性恢复的 handler（可信的裁决：`io` 不是可声明
的 `effect`，压根没有证据槽，`selfhost/src/check/types.dawn:279` 就是 `assert nev(EIo) == 0`，且 `!io`
在 codegen 是擦除的），则第二类原样留在直接风格。**推论：编译器里 480 个 `!io` 函数、backend-dawn
里 478 个、以及 `main` 自己，全部不动。** 既做 io 又抛具名标签的函数落在第三类不是第二类，
分类是互斥的，表里已经反映（`packages/tea-term/src/runtime.dawn:50` 的 `!io !A.E` 记在具名）。

### 4.2 双份编译 vs 永远 CPS，以及 comptime 怎么定这一局

静态选择性 CPS 的选项 (i) 是**双份编译**：27 个 `!e` 加 8 个关联投影 = **35 个函数体、约 380 行**
要出孪生体，外加**五个行多态原语**（`selfhost/builtins.dawn:96` `catch_fault`、`:99` `catch_panic`、
`:136` `sort_by`、`:284` `map_fold`，以及 `bracket`），它们的体是逐后端手写的，所以孪生体也得手写：
5 个原语 × {JVM 字节码发射器、C 运行时、wasi 变体、comptime 解释器臂}。这是**两种设计共同的、
不可约的那块集中成本**。

选项 (ii)「行多态函数一律 CPS」被 comptime 一条判死：`ir/interp.dawn`（3124 行）今天完全不动，
因为 comptime 拒 `with handle`（`checker.dawn:5599-5603`）、拒 reactor intrinsic
（`interp.dawn:833-835`）、拒 `catch_fault`/`catch_panic`/`map_fold`（`builtins.dawn` 上的
`# comptime: rejected`），**comptime 代码永远不可能挂起**。双份编译下每个 comptime 调用点把
`!e` 实例化成纯，lowering 挑直接孪生体，`interp` 见不到 `$k` 符号。永远 CPS 下 `interp` 就得解释
CPS 化的 `sort_by`/`map_fold` 体。**这是双份编译胜过永远 CPS 的决定性论据。**
选项 (iii)（单态化）本来就关着：[native-backend-plan.md](native-backend-plan.md):36，泛型不单态化，
沿用 box-at-type-var-slot。

### 4.3 哨兵：不需要返回类型改造

返回值在两个后端都是无装箱、精确类型的（JVM 描述符 `J`/`D`，`jvm/emit.dawn:275,511,520`；C 侧
`RInt64 -> "int64_t"`，`c/emitc.dawn:363,398`，而 `emitc.dawn:1981` 记着一次「把 int64_t 返回当
指针」的真崩溃），所以 `fn(…) -> Int !Ask` 返回一个指针形状的哨兵不可表达。**但也不需要 `Either`
包装。** Koka 的答案是旁路标志位、yield 时返回值就是垃圾，这在无装箱返回下成立，而**本仓恰好有
现成先例**：`runtime/c/dawn_rt.c:1790` 的 `static dawn_failure dawn_inflight`，一个进程级的在途失败
记录，由 `dawn_reraise`（`:2152`）与两道屏障（`:2078,2122`）读。一个
`static dawn_yield dawn_inflight_yield` 是同样的形状、同样的生命期、同样的测试故事；JVM 侧是一个
静态字段。**于是：不改返回类型，一个运行时全局加一个 intrinsic，落点恰好是
[handler-state-design.md](handler-state-design.md):531-545 已经逐件列过的那七个文件。**

### 4.4 头对头

| | 静态选择性 CPS | yield 冒泡 |
|---|---|---|
| 需要重构的函数体 | 35（外加 5 个手写原语） | 同样的 35（外加同样的 5） |
| 代码体积 | 后三类**每个两份体** | **每个一份体** |
| `eff_carries` 加宽点的约定适配器（`check/types.dawn:462`） | **需要**：eta 包装，或每闭包两个入口（native 的 `dawn_clo` 要么加 8 字节，要么按头字节 kind 区分） | **不需要** |
| 新 Core 节点 | 无 | 无 |
| 循环里含 perform | `CSLoop` 头上的状态机 | 同 |
| 不挂起时的运行时代价 | 除非能证明否则每个 bind 点都分配续延 | **一次 load 加一次可预测分支**，且只在有效果的调用点，98.6% 的代码什么都不发 |
| 挂起时的代价 | 每帧一次堆分配加 `ncaps` 次存 | 相同 |
| 返回类型 / 哨兵 | 不适用 | **无包装**，一个运行时全局（先例 `dawn_inflight`） |
| JVM / native 栈 | **风险所在**：一般尾调已被裁为不做（`native-backend-plan.md:37`「一般尾调 / 不做，大栈代替」），要么长栈要么 trampoline，而 trampoline 已被定价并拒绝（[audit/ceval-trampoline-verdict.md](audit/ceval-trampoline-verdict.md) §2） | 帧正常返回，不增长 |
| `c/rc.dawn` | 约 120 行：续延就是一个普通闭包 | **约 400 行，风险所在**：每个函数多一条出口路径，槽要用 `dawn_take` 交给续延而不是被 `dawn_own_drop` 丢掉 |
| `ir/interp.dawn` | 0（comptime 处处挑直接孪生体） | 0（标志位在 comptime 永不置位） |
| `ir/reach.dawn` | 约 30（保活孪生体） | 0 |
| 屏障（`bracket` / `catch_fault` / `catch_panic`） | 5 个原语 × 3 处手写 | 同，**再加**不许跑 `release`、不许把 yield 报成失败 |

**两条都不需要新的 Core 节点**，因为「剩余部分是一个堆闭包」就是**今天的代码**
（`checker.dawn:5738-5756` 与 `:7080-7091`），`CClosure` 已被 Perceus 完整建模
（`c/rc.dawn:238,389,1009,1678`）也被约定推断建模（`c/infer.dawn:88-133`）。真正要干活的形状只有
一个：**循环体里含 perform**，它要在 `CSLoop` 头上抬出状态变量加一串 `CSIf` 分派，Core 没有标签也
没有 goto（`ir/core.dawn:96-208`），所以是 O(状态数) 次判断、没有跳转表。树里现成的最坏例子是
`examples/projects/tea_dom_search/src/search.dawn:252-265`：三层嵌套 `for`，一个可变 `var shown`，
perform 在最内层。`std` 那 25 个组合子全是累积器式自尾递归写法（`std/list.dawn:61-131`），
所以它们是免费的。

**修正一条框架预设：冒泡并不省掉函数体重构。** Koka 的 `Core/Monadic.hs` 也是一趟源到源的
单子/bind 切分。冒泡买到的不是「不用切分」，而是**谁来驱动返回**：CPS 去调用续延（一次一般尾调），
冒泡**正常返回**、由调用方决定。它在编译期真正更便宜的地方是**不需要孪生体**，于是没有代码体积
翻倍、没有可达性变化、没有「挑哪一份」的判断，而且**没有约定跨越适配器**，§4.2 那整个问题连同
`dawn_clo` 第二指针的问题一起消失。更贵的地方是：标志位测试必须在**每一个**行非纯（模 `io`）的
调用之后发射，机械但**必须穷尽，漏一处就是一次静默丢弃的恢复**。

### 4.5 规模：约一到一个半次战役，不是 18k 行黑洞

消费 `CExpr`/`CStmt` 的文件是**九个不是八个**（`ir/coredump.dawn` 464 行常被漏掉），连
`ir/core.dawn` 自身共 **19 169 行**。但按上表逐项加总，**静态 CPS 约 1400 至 1800 行编译器改动，
冒泡约 1800 至 2200 行**，即那个悲观上界的一成左右。参照系是本仓「一次战役」的单位，即 handler
局部状态那批：**55 个文件、+2620/−212**，其中 `selfhost/src` 是 **+1375/−135** 分布在 8 个
Core 邻接文件上。**所以：选择性 CPS 约等于一到一点五次 handler-state 战役的编译器工作量，再加一次
客户侧战役。** 主导风险不是规模，是两条：JVM 侧续延链在没有一般尾调时的栈深度，以及 Perceus 的
`gone` oracle 那句「假设控制流正常返回」。

## 5. 推荐路线：yield 冒泡

**理由一，血统连续。** 本仓的效果实现是证据传递（Koka "Effect handlers, evidently" 那一系），
冒泡是同一系里对「非尾恢复」的原生答案。它复用今天已经成立的三件东西：剩余部分已经是堆闭包、
哨兵已有 `dawn_inflight` 的先例形状、intrinsic 落点表已经写好
（[handler-state-design.md](handler-state-design.md) §7.1）。

**理由二，98.6% 的代码一分钱不付。** 吸收禁令把「可挂起」变成一个签名可判的性质，标志位测试只在
1.45% 的函数体里发射，其余什么都不发。静态 CPS 相反：除非编译器能证明不必，否则在每个 bind 点
分配续延，无论有没有东西真的挂起。

**理由三，它绕开了本仓已经裁过的那道墙。** 静态 CPS 把每一次「返回」变成对续延的一般尾调，而
一般尾调**已裁为不做、用大栈代替**（`native-backend-plan.md:37`），trampoline 也已被单独定价并
拒绝（[audit/ceval-trampoline-verdict.md](audit/ceval-trampoline-verdict.md) §2 的诚实口径是
「真实 scope 不是 33 个臂，是 33 加 6 个臂，外加十二个函数的调用协议改成显式帧」）。**推荐冒泡
就是不去重开这条裁决。**

**它输在三处，三处都是「要干活，但干得完」。**

1. **`c/rc.dawn` 约 400 行对约 120 行。** 每个函数多一条出口路径要配平，而 oracle 假设正常返回。
   缓解形状是现成的：`dawn_take`（`runtime/c/dawn_rt.h:551-555`）「在同一个表达式里把引用交出去
   并清空槽位」，所以 yield 路径按槽 `dawn_take` 之后再建剩余闭包。**不能**走的路是每槽一个条件
   drop：`dawn_rt.h:509-516` 记着每槽一个 cleanup 属性把自举驱动的编译从 **16s 顶到 354s**。
2. **`c/emitc.dawn` 约 250 行对约 150 行**，同因。wasm 侧还有同一问题的第二份拷贝
   （`dawn_rt.c:1957-2003` 的影子栈注册），交接必须发生在 cleanup 触发之前。
3. **穷尽性是硬要求**：漏一个标志位测试点等于静默丢一次恢复，而这类 bug 只在真客户下才现形。
   这条要在立项时就配好机器（变异体，见 §7）。

## 6. 客户与解锁的断言

### 6.1 reactor 假说：运行时以下成立，语言以上被三件事挡住

**以下成立。** retained root 是一个裸的类型擦除 `void *` 静态（`runtime/c/dawn_rt.c:650-654`），
`dawn_drop` 按头字节 kind 分派，含 `DAWN_K_CLO` 与捕获掩码遍历（`dawn_rt.c:1253-1271`）；RC 纪律
写明并探过（set 借用加 dup 再丢旧值，`set(get())` 别名安全；get 返回 owned，`dawn_rt.c:3033-3048`，
由 `scripts/wasm-dom-contract/retained-rc.c:36-66` 钉住）；LSan 看到的是活着的 C 静态而不是泄漏。
**而且这个 retained 值今天就已经是一个闭包**：`std/reactor.dawn:22-24` 的
`type Root = Root(advance: fn(String) -> (Option[Root], Option[String]))`，由 `rooted[S]` 捕获 `S`
构建（`:26-38`），`S` 无约束，所以 `S` 可以是或含有一条续延。

**三件挡路的都在包一层，不在运行时。**

1. **没有 `Cmd` 通道，是裁决。** `packages/tea-core/src/app.dawn:14-22` 明写把 `Cmd` 推给 tea v2；
   `packages/tea-core/src/sub.dawn:1-19` 写「v1 没有 Cmd 通道」。**今天除了 DOM 监听器在 `event`
   轮里被 `route.at` 解析出来之外，没有任何东西能产生一条 Msg**（`packages/tea-dom/src/reactor.dawn:185-205`）。
2. **tea-dom 在 `event` 上拒绝提交状态替换。** `packages/tea-dom/src/reactor.dawn:183` 只有 `Init`
   臂返回 `Some(kept)`，`:179,188,194-195,200,203` 一律 `None`，由 `:454-470` 的测试钉住。
   `std/reactor.serve` 自己没有这条限制（`std/reactor.dawn:83-86` 提交任何 `Some`），
   所以这是 `turn_with_state` 的形状改动，不是重新设计。
3. **step 回调是纯的，故意的。** `std/reactor.dawn:28,64`，理由在 `:13-14`：
   「application code cannot re-enter an io pump from inside a turn」。存下来的续延可以**被恢复**
   （调一个纯闭包没问题），但它自己不能做 io、也不能发自己的回复。

### 6.2 最小演示形状与它写得出的那条断言

`examples/projects/tea_dom_await`：一个 `effect Async { fn fetch(url: String) -> String }`；
`update` 用直接风格写成 `let body = fetch(url); …`；reactor step 里装一个 handler，它的 `fetch`
臂**把续延捕获进 `S`、返回一条请 JS 去取的回复**；JS 取回来，作为一条普通 `event` 行发回来；
下一轮把续延从 `S` 里取出来、用 body 恢复它。需要三件：一次性恢复、`turn_with_state` 允许在
`event` 上替换、以及 `packages/tea-dom/js/reactor.mjs` 里一个新回复变体。**不需要** `externref`、
不需要唤醒、不需要栈切换：恢复就是后一次 `dawn_turn` 里的一次普通闭包调用。

它按本仓判据（[effects-design.md](effects-design.md):528-533）让这条断言变得写得出：

> `assert len(msg_constructors(Msg)) == 2`：应用的 `Msg` 类型恰好只有那两个用户意图构造子
> （`Typed`、`Pressed`），**而轮转记录显示了一次三轮的异步往返，其结果是作为一个 `let` 的值到达
> `update` 的，不是作为一条消息。**

**今天这条断言原则上写不出**，因为每一次异步往返都必须是一个 `Msg` 构造子，Msg 是唯一能重新进入
`update` 的东西。两半都可机器核对，transcript 那一半的现成 harness 形状是
`scripts/wasm-dom-contract/retained.mjs`。

**框定。** reactor 里的任何一次性恢复演示，实质是「tea v2 的 `Cmd` 通道，用一条续延而不是一个消息
构造子来实现」，立项时应当按这个名字来立（见 §9 问题 ⑥）。顺带记一条今天的事实：
`tea_dom_search` 全无异步，索引在 `init` 的 flags 串里一次到齐并被 retained
（`examples/projects/tea_dom_search/src/search.dawn:80-87`），每次击键都是同步的库内扫描。

## 7. 风险台账

| # | 风险 | 证据 | 状态 |
|---|---|---|---|
| R1 | **`c/rc.dawn` 的第二条出口路径** 与 Perceus 局部 oracle 的「假设控制流正常返回」相撞 | [effects-design.md](effects-design.md):508；`c/rc.dawn:28-31`；`perceus-design.md:377-381` | 冒泡路线的头号风险，缓解形状是 `dawn_take`（`dawn_rt.h:551-555`），每槽条件 drop 已被 16s→354s 判死 |
| R2 | **三道屏障要认识 yield**：`bracket` 跨 yield 时**不许**跑 `release`（计算还没结束），`catch_fault`/`catch_panic` 跨 yield 时**不许**报成 `ForeignError` | `dawn_rt.h:746-765`；`builtins.dawn:96,99` | 每道 × 3 处手写（JVM 发射器 / C / wasi）；这类 bug 只在真客户下现形 |
| R3 | **标志位穷尽性**：漏一个测试点 = 静默丢弃一次恢复 | §4.4 | 必须由变异体看护，不能靠 review |
| R4 | **SAM 桥的承诺会被推翻**：[design.md](design.md):105-107 写着「Kotlin 禁 suspend lambda 转 SAM 是因为 suspend 改了调用约定，Dawn 无此障碍」。两种设计都为非纯行**造出**这个障碍 | `docs/design.md:105-107`，英译 `design.en.md:135` | **没有人给它定过价。** 一次性恢复之下，Java SAM 桥要么限定在纯/`io` 行，要么加一个适配器 |
| R5 | **R4 与 sam-snapshot 分支的边界条款相交**：JVM 的 SAM 证据洞（`jvm/emit.dawn:1145-1162`，`m.visitInsn(OP_ACONST_NULL)`）正由「创建点快照」在另一分支上修 | `packages/web/src/server.dawn:770` 的 `createContext` 就是这条边界，今天在生产上跑 | 快照定了「跨边界的闭包看见什么」，一次性恢复定了「哪些行还能跨这条边界」。**两条要一起裁**，见 §9 问题 ④ |
| R6 | **spec §6.5 五条裁决全部被波及** | 见下 | 逐条重裁，不能照抄 |
| R7 | **native 帧税是永久的**：调优后约 5%、地板 2 至 4%，对每个 native 程序收，不管它用不用效果 | §3.3 | 后续问题不是「能压到多低」，而是「能不能只让够得着续延的函数付」。而在 5% 无条件的压力下，把一个干净的每帧不变量变成一次全程序分析，正是那种压力 |

**R6 逐条**（原文在 [spec.md](spec.md) §6.5）：

1. **格子（`spec.md:1644-1650`）**：「从本次安装的臂与块剩余可达」预设两者都在安装的动态范围内。
   一次性恢复下剩余**就是**续延，`acc` 必须活过臂的返回。
   [handler-state-design.md](handler-state-design.md):16-20 的期权记录已经把答案记账了：
   「格子的表示要从 handler 帧上的一个槽位升级为随续延捕获一起复制」（Effekt ICFP 2025 那条路）。
2. **按值捕获（`spec.md:1660-1665`）**：原则不变，但臂多了一个 `resume` 绑定，而它本身是一等值，
   「臂是闭包、按值捕获」不再是全部故事。
3. **行规则（`spec.md:1673-1680`）**：结论「行失去一个成员只发生在 `with handle` 这一个语法节点上」
   活得下来，但它的**理由**（「剩余部分是闭包，运行它的就是这个节点」）恰恰是被一次性恢复推翻的
   那一句，要重写。同理 `checker.dawn:5722` 把每个臂的行记在**安装块**上，那今天是事实，之后是断言。
4. **`?` 早退（`spec.md:1681-1685`）**：local state interpretation 仍然点中正确答案，但
   「格子随 handler 帧一起销毁」需要新的所指（没有单一的帧了），在 native 上还变成一个 RC 问题：
   被放弃的续延，它的 owned 槽由谁丢。
5. **逃逸禁令（`spec.md:1724-1729`）**：**交互最锋利的一条**。禁令的实现是拿 `lc.handler_of` 比
   格子的 `hid`（`checker.dawn:4954`），它的正当性论证是被许可的那些闭包
   *"called once and in place … and never handed to anybody"*（`checker.dawn:4902-4906`）。
   **一等 `resume` 就是那个被交出去的剩余闭包。** 要么给 `resume` 开例外，并把禁令的可靠性论证
   从「词法帧身份」重建到「续延身份」上；要么格子与一次性恢复互斥。
   `spec.md:1732-1736` 那条逃生门本来就写好了这一天：「不承诺多次 `resume` 放开之后仍然如此，
   放开之后格子须随延续复制，那是另一次裁决」。
   另有一条更窄的先例要一起重推：[handler-state-design.md](handler-state-design.md) §7.8 把
   `cell_take` 收窄到三条，第一条是「赋值必须在本次安装的臂里」，理由是本次安装的任何臂都不可能在
   空槽窗口里跑起来；**一条挂起后又恢复的臂恰好重开这个窗口**，三条与它们的三个负控都要重推。

## 8. 重开与波及的既有裁决

| 出处 | 裁决 | 一次性恢复怎么碰它 |
|---|---|---|
| [effects-design.md](effects-design.md):43-46 | 非尾恢复 / 多次恢复与 C 后端 Perceus 加单栈模型正面冲突 | 非目标行本身；若立项要改写。**注意这条写着「CSProtect 图纸是诚实的成本起点」，而那个节点不存在**：[core-move2-design.md](core-move2-design.md) 文件头写 `CSProtect` 关档不做，`:292-298` 说它今天没有客户。**这个指针要替换，不是跟随。** 本文 §3 与 §4 就是替换物 |
| [effects-design.md](effects-design.md) §8.3 | 三条：维持尾恢复；回溯/概率编程/自动微分不进任何对外材料；**将来若做 multi-shot，必须与 RC 一起单独立项** | 一次性恢复比 multi-shot 窄一格，但撞的是同一堵墙。第三条的精神直接适用：这不是效果系统内部的一次加法 |
| [effects-design.md](effects-design.md) §8.2 | 多 handler 组合：入案不动手，「第一次出现两个互不相识的库各自带效果各自装 handler 时重开」。`:471` 写「Eio 那个具体故障形态在 Dawn 不可能发生，因为没有延续」 | **那条豁免正是一次性恢复要花掉的钱** |
| [effects-design.md](effects-design.md) §8.1 | 签名噪音：已知风险，暂无缓解，等真实样本 | 每个臂多一个 `resume` 绑定是第四个噪音源 |
| [handler-state-design.md](handler-state-design.md):16-20 | 期权记录：放开多次 `resume` 则格子随续延复制 | **这句话就是写给今天的**，见 §7 R6 第 1 条 |
| [handler-state-design.md](handler-state-design.md) §7.6 | 「没有第二出口，动刀的前置条件解除」，证据由调用点供给、不随闭包走（探针 P-E3） | 一条携带自己 handler 链的续延，正好把这条关掉的第二出口重新打开 |
| [handler-state-design.md](handler-state-design.md) §7.7 | 刀 C 不做 lowering 兜底，重开条件写的是「格子变得不可拼写，或 `XLambda` 因别的理由已经加了臂标记」 | 一个 `resume` 绑定很可能就是那个别的理由 |
| [handler-state-design.md](handler-state-design.md) §8 问一 | 候选二加强制逃逸禁令能成立，是因为环的第一步（闭包抓住格子）是编译错误 | 一等 `resume` 是一个合法持有格子所在帧的闭包，这是该论证的前提 |
| `docs/audit/error-model-design.md`:695-698 | 臂抛出的 fault 由内层屏障接走，「这是尾恢复档的必然后果」 | 原文明写「若将来引入非尾恢复的臂，这个答案会翻转，届时要重裁，不能照抄本条」 |
| [tea-block-children-design.md](tea-block-children-design.md) §3.1 | 收集型 handler 写不成 fold，因为「要 `resume with acc ++ [n]` 那种形状需要延续」 | 实践上已被格子取代；一次性恢复会以另一种方式取代它 |
| [tea-block-children-design.md](tea-block-children-design.md) §8 | 参数化效果「可实施但暂不立项」，重开条件是客户到第三个 | 与一次性恢复相互独立，但争同一份预算 |
| [design.md](design.md):31 与 `design.en.md:40` | 非目标行：非尾恢复档（多次恢复 / 延续捕获） | 若立项要重写，两语都要 |
| [design.md](design.md):105-107 | SAM 转换「Dawn 无此障碍」 | §7 R4：被推翻，且没人定过价 |
| [perceus-design.md](perceus-design.md) §5.5 | 平衡检查器的四条断言 | 不是写成可重开的，它是不变量。要动的是 pass，不是这条 |
| [native-backend-plan.md](native-backend-plan.md):37 | 一般尾调不做，大栈代替 | 静态 CPS 会重开它；**推荐冒泡的第三条理由就是不重开它** |

## 9. 待裁问题

① **立项与否。** 勘察结账了：一到一个半次战役的编译器工作量加一次客户战役，加一笔 2 至 5% 的
native 永久帧税，换回 §6.2 那条断言。裁「不做」是完全成立的答案，本文按 §8 的口径已经把它记成
可查的成本表；裁「做」则请确认路线是 **yield 冒泡**（§5），因为 §4 之后不再对拍。

> **裁决（用户 2026-08-31）：立项。** 同批裁定了一个后继项目：**标准库效果分解**（io 按
> Koka 的思路拆成可应答的具名效果族，逐族推进、每族先命名一条今天写不出的断言，前置是
> [runtime-intrinsics-design.md](runtime-intrinsics-design.md) 的操作可枚举化），
> **排在本项目之后**。②至⑥的形状裁决仍开放，落齐之前不动工。

② **`io` 永不承载一次性恢复的 handler。** 这条裁决直接决定传染面是 1.45% 还是 21.4%
（再加上 664 个 `!io`），也决定 `main` 与整个 `packages/web` 是否留在直接风格。**建议裁「永不」。**

> **裁决（用户 2026-08-31）：永不。**

③ **`resume` 的表面语法**：隐式绑定（作者永不书写，前端零改动，成本全在类型与 lowering），
还是显式绑定（`op(a, b, resume) => …` 或 `op(a) resume k => …`，`docs/grammar.ebnf:114` 一条产生式
加 `handler_arm` 一个分支）。注意 `handle` 已是上下文关键字的先例，可以不占关键字。

④ **SAM 约定条款**：一次性恢复之下，Java SAM 桥限定在纯/`io` 行，还是加一个适配器。
与 sam-snapshot 那条「创建点快照」的边界条款一起裁（§7 R4/R5）。

> **裁决（用户 2026-08-31）：限定。** 可挂起的闭包不跨 Java 边界，编译错误；快照条款只对
> 不可挂起的行继续成立。

⑤ **格子 × `resume`** 三选一：给 `resume` 开例外并重建逃逸禁令的可靠性论证（论证要从续延身份
出发，不能从词法帧身份出发）；格子与一次性恢复互斥；或按期权记录做「随续延复制」。

> **裁决（用户 2026-08-31）：随续延复制**，照 [handler-state-design.md](handler-state-design.md)
> 前言的期权记录（Effekt ICFP 2025 路线）。

⑥ **与 tea v2 `Cmd` 的联动**：`examples/projects/tea_dom_await` 实质是「`Cmd` 通道用续延实现」，
它和 `Cmd` 本身一起立项，还是分两个项目、`Cmd` 先落地再把续延接上去。

> **裁决（用户 2026-08-31）：分两步。** `Cmd` 先按普通消息独立落地，续延后接。

## 10. 勘察产出索引

四份原始报告是档案，本文是决策面；**每个数字在本文只出现一次**，要看它是怎么测出来的回报告。

| 报告 | 位置 | 内容 |
|---|---|---|
| A 编译器侧 | `~/workspace/agent-handoff/research/oneshot-recon-A-compiler.md` | 七层清点（前端 / 类型 / 证据 ABI 与 lowering / 两个后端 / spec / 门禁 / 被重开的裁决），三个形制问题的答案，规模估计 |
| B 运行时侧 | `~/workspace/agent-handoff/research/oneshot-recon-B-runtime.md` | JVM `Continuation` 与虚拟线程探针数字，native 侧栈三条实测（ForcedUnwind abort、ASan 警告、LSan 失明），wasm 裁定，排序过的选项表 |
| C 对拍 | `~/workspace/agent-handoff/research/oneshot-recon-C-cps-vs-bubbling.md` | 传染面扫描、九个 Core 消费者逐项估行、静态 CPS 与冒泡头对头、reactor 假说、那条断言 |
| D 帧税 | `~/workspace/agent-handoff/research/oneshot-recon-D-frame-tax.md` | 无条件影子栈的实测税、阳性对照与烟测、诚实读法 |

**可复现的起点只有两个。** 帧税那一组来自分支 `own-stack-tax`，提交 `cf10003`（工作树
`/home/dawn/workspace/dawn-lang-wt/own-stack-tax`，另有一个一次性的基线工作树），那是真改动、
可以直接重跑。**其余数字是仓外 `/tmp` 探针**：JVM 的 `Continuation`/虚拟线程、native 的
`swapcontext`/ForcedUnwind/LSan 三条，都是为这次勘察写的独立 C 与 Java 小程序，**没有进仓库**。
要重导它们，从报告 B 的方法描述重写探针，不要指望树里有代码可读。
