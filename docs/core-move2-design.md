# Core Move 2：控制流 / match lowering 的提取——结账与残余

> 状态：**current** —— 本文是一次**盘点**，不是一份待做的方案。
>
> [`runtime-intrinsics-design.md`](runtime-intrinsics-design.md) §8 把「把 emit 里的
> lowering 抽成 tast→tast pass」排成三步 Move，Move 2 是控制流 + match。写下那三步的
> 时候，`emit.dawn` 有 3568 行、`for`/`while`/`match`/`?`/`!`/插值在它的树遍历里内联发字节码。
> **今天不是这样了。** 本文第一节逐项核对，结论是 Move 2 的主体已经在
> [`native-backend-plan.md`](native-backend-plan.md) 的 Phase 0 里落地——不是被绕过，是**同一件事
> 被那条线做完了**，且做到了比原方案更远的地方（Move 3 的装箱也一并进了 Core）。
>
> 于是本文的正题是第二节起的**残余**：Move 2 的名下还欠一个节点，就是
> [`audit/error-model-design.md`](audit/error-model-design.md) 里那个「冻结，等 Core IR」的
> **C2 / `LProtect`**。Core IR 到了，冻结的理由没了。本文把它设计完，
> 并且——这是本文最重要的一条——**论证在今天的形状下它多半不必被建出来**（§2.6）。
>
> 相关：[`selfhost-codegen.md`](selfhost-codegen.md)（codegen 的移植史，historical）、
> [`perceus-design.md`](perceus-design.md)（native 的 RC，§3.3 与它有一处硬耦合）、
> [`audit/lowered-ir-design.md`](audit/lowered-ir-design.md)（同一件事的另一份独立方案，已降级为补充材料）。

## 0. 三句话

1. **Move 2 的账已经结了**：`match` 决策树、`for`/`while`、`?`/`!`、字符串插值、自尾调用重写、
   lambda 捕获、装箱决策，全部在 `lower.dawn` 里，`emit.dawn` 与 `emitc.dawn` 各自只剩「这台机器
   的事」。原方案担心的「match 编译不想写两遍」**没有发生**：C 后端 1598 行里没有一行 pattern 代码。
2. **残余是一个节点**，不是一批：`CSProtect`（C2 写作 `LProtect`）——「无论怎么退出都执行 release」。
   它是 Core 里唯一一个**两个后端都有本地机制、而 Core 没有词汇**的控制流形状。
3. **而它多半不该被建出来。** C2 冻结时的论证（「codegen intrinsic 会把 bracket 绑死在 JVM 上」）
   在 `catch_fault` 落地之后不再成立：屏障已经是「取闭包的运行时原语，每个后端实现一份」，
   而那正是 intrinsic 契约推荐的形状。§2.6 把这条减法写完，§6 把它作为第一号开放决策交出去。

## 1. 前提复核：Move 2 抽的那些东西现在在哪

### 1.1 §8 的三行表，今天的样子

`runtime-intrinsics-design.md` §8 列了「三处漏进 emit 的 lowering」。逐行核对（`wc -l` 与 `grep`，
2026-07-31，`77d7aa4`）：

| §8 的行 | 当时 | 今天 | 落点 |
|---|---|---|---|
| intrinsic 语义 | 三份不一致 | **一份**：`types.intrinsics()` 声明模块，两个后端各自拼名字 | Move 1 增量 1（`2532c2b`）+ §12.1 的「表里不该有名字」 |
| **结构化控制流 + 语法糖** | `for`/`while`/`match`/`?`/`!`/插值以 tast 存活到 `emit.dawn:764,1026,1456` | **全在 `lower.dawn`** | 见 §1.2 的落点表 |
| 装箱 / 擦除 | `adapt_to/adapt_from` 在每个调用点重算 | **`CBox`/`CUnbox` 两个 Core 节点**，lowering 决定一次 | `core.dawn:141`，`lower.dawn:153` 的注释就是这段论证 |

第三行本来是 Move **3**。它比 Move 2 先到，因为 Perceus 需要所有权显式化，而所有权显式化要求
表示先显式化——`native-backend-plan.md` §11.4 把顺序重排了，而 §8 没有跟着改。**这是文档的
时间差，不是两条路线的分歧。**

### 1.2 落点表：每一样东西现在的定义处

| lowering | 现在在哪 | 产出的 Core 形状 |
|---|---|---|
| `match` 决策树 | `lower.dawn:2556` `lower_match` | 判别式测试 + 字段绑定 + 一趟 once-loop（`CIsCtor`/`CTagOf`/`CField`/`CSLoop`+`CBreak`） |
| 模式（含守卫、嵌套、字面量、元组） | `lower.dawn:322` 起（「A pattern compiles to (test, binds)」） | 短路条件 + 绑定序列 |
| 列表模式 | `lower.dawn:381` `lower_list_pattern` | 长度测试 + 定偏移取元素 |
| `while` | `lower.dawn:2729` | `CSLoop` + 显式 `CBreak` |
| `for` | `lower.dawn:2744` | `CSLoop` + 归纳变量 + `step` 字段 |
| `?` | `lower.dawn:2631` `lower_propagate` | 对 `Option`/`Result` 构造器的显式测试 + `CReturn` |
| `!` | `lower.dawn:2663` `lower_unwrap` | 同上 + `panic` intrinsic |
| 字符串插值 | `lower.dawn:2471` `lower_str` | `str_of_*` intrinsic + `CConcat` |
| 自尾调用（spec §12.4） | `lower.dawn:1965` `wrap_self_loop` / `2011` `self_tail_jump` | 实参进临时量 → 写回形参 → `CContinue` |
| lambda 提升与捕获 | `lower.dawn`（`LSt.lifted`） | `CClosure` + 提升出的 `CFun` |
| 装箱 / 擦除 | `lower.dawn:153` 起 | `CBox` / `CUnbox` |

`CSLoop.step` 那个字段值得单独记一句，因为它是「lowering 一次、两个后端白拿」的教科书例子：
没有它，`for` 的自增只能放在 body 底部，而 `continue` 会跳过它、循环永不终止。**把 step 做成节点的
字段，就是不让它成为每个后端各自的 bug。**（`core.dawn:183` 的注释写了同一件事。）

### 1.3 减法减出来的边界：`emit.dawn` 残余是什么

`emit.dawn` 从 4353 行降到 **2506 行**，且它自己的文件头把这次减法写成了验收标准：

> This file used to consume TAST directly and was twice this size. What is gone -- the match
> decision tree, `for`/`while` shape, `?`/`!`, string interpolation, lambda capture analysis,
> the boxing decision, the self tail call rewrite -- did not move to another JVM file: it moved
> to lower.dawn, where the C backend reads it too. What is left is the part that is genuinely
> about this machine: slots, descriptors, stack discipline, invokedynamic, and `use java`.

机器可查的版本：`grep -c 'TArm\|XMatch\|pattern' selfhost/src/emit.dawn` → **0**。
`use tast` 只剩 `{TJavaCall, TFun, TModule, TBinOp, BEq..BGe}`——`TJavaCall` 是 `CForeign` 故意
原样带着的 JVM 事实，其余是三个类型名和比较算子的拼写。

**这就是「真正的 Core IR 边界被减法减出来」那句话兑现的样子。** 残余的五样——槽位分配、
descriptor、操作数栈纪律、`invokedynamic`、`use java`——没有一样是可移植的。

### 1.4 `emitc.dawn` 的「平行臂」不存在

Move 2 的存在理由之一是「杀掉 emitc 的平行臂」。**那批平行臂从来没长出来**：`emitc.dawn` 是
Core→C，1598 行，文件头说得很直白——

> Everything structural is already gone by the time Core arrives -- `match` is discriminant
> tests and binds, `for` is a loop with an explicit step, `?` is a test against a constructor,
> interpolation is concat calls.

它对控制流的全部代码是四处：`CBreak`→`goto loop_end`（:434）、`CContinue`→`goto loop_step`（:435）、
`CIf`→`emit_if`（:445）、`CSLoop`→带 step 标签的 `for(;;)`（:1222）。**这是「消费同一个节点」，
不是「第二份 lowering」。** 要量化 Move 2 省下的重写代价，就是这个数：C 后端为整门语言的控制流
写了 **4 个 arm**，而不是一份 match 决策树编译器。

### 1.5 comptime 解释器也吃 Core

`interp.dawn:1046` 的 `ceval` 的输入类型是 `CExpr`。它曾是**第三份语言定义**（自己决定 `match`
是什么、`?` 返回什么、`for` 怎么迭代、什么时候装箱），现在读后端读的同一份 IR，删掉了模式匹配器、
`for`/`while`、`?`/`!`、插值，以及四分之三的函数值表示。

残留的 TAST 走查只有一处且不是求值：`interp.dawn:1616` 附近的 `walk_expr` 是**收集 comptime 块
span** 的预扫描，跑在 lowering 之前，按定义只能看 TAST。**它不是 Move 2 的欠账**，本文不动它。

### 1.6 于是 Move 2 的原始 scope 里还剩什么

一句话：**零**。原表三行全部关账，且第三行（装箱）跑到了 Move 3 的位置。
本文余下部分讲的是那之后才看清的一个洞。

## 2. 残余：`CSProtect`

### 2.1 C2 的约束，原文

[`audit/error-model-design.md`](audit/error-model-design.md) §二.C 与 §五：

- 「**C2（正确）**：`bracket` 是**降级阶段的一个 IR 节点**（`LProtect(body, release)`），
  两个后端各自发射：JVM 发 `visitTryCatchBlock` 带 `null` 类型（= finally），
  native 发 setjmp/longjmp 的 unwind 保护。**原始失败继续向上传播，release 一定执行，栈不变。**」
- 「初稿这里写的是『C2 = 一个 codegen intrinsic，发 JVM finally 块』。**那是把它绑死在 JVM 上**
  ——native 后端没有 finally，`bracket` 会变成第二份实现。」
- 「**它现在冻结**，等 Core IR 落地。」

以及同文 §6.10 的一条**独立约束**，写在 `cast_e` 落地时，讲的是为什么屏障是方法而不是内联 try 块：

> **JVM 侧是一个方法，不是内联的 try 块。** `cast` 是写进调用者的一条 CHECKCAST，
> 而把**那条**包进 handler 不成立：进 handler 时 JVM 会清空操作数栈，于是
> `f(a, cast_e(x))` 这种表达式中途的 `cast_e` 会在汇合点丢掉已经压进去的 `a`。
> 方法有自己的栈——这也正是两个屏障是方法的原因。

**这条是本节全部设计的支点。** 它不是「try/catch 在 JVM 上做不到」，它是
「**受保护区间必须从一个操作数栈为空的位置开始**」。

### 2.2 命名：`LProtect` → `CSProtect`

C2 写于 `lowered-ir-design.md` 的 `LIR`/`L*` 命名下。那套命名没有落地——落地的是
`core.dawn` 的 `C*`：表达式 `CExpr` 的变体是 `C…`（`CIf`/`CCall`/`CBox`），语句 `CStmt` 的变体是
`CS…`（`CSLet`/`CSLoop`/`CSIf`/`CSDiscard`/`CSDrop`）。

**按仓库约定，这个节点叫 `CSProtect`，且它是一个 `CStmt`。** 「是语句」不是风格选择，是 §2.1
那条约束的**结构性兑现**：`emit.dawn:2150` 的 `gen_cstmt` 每一条臂进出时操作数栈都是空的
（`CSDiscard` 显式 `pop_value`、`CSLoop` 对 body 与 step 各 `pop_value` 一次、`CSIf` 让两个分支
各自丢掉自己的值「so both reach the merge with the same empty stack」）。把 protect 做成语句，
「try 范围从空栈开始」就由类型保证，而不是由 emitter 的自觉保证。

### 2.3 形状与不变量

```dawn
# in core.dawn, as a CStmt variant
| CSProtect(result: Int, ty: Ty, body: CExpr, release: CExpr)
```

- `result` 是一个 lowering 新铸的符号（`LSt.next_sym`），语义是 `let result: ty = <body>`：
  绑定**在受保护区间内部**完成，区间外用 `CLocal(result, ty)` 读。这样 body 的值不必跨越
  try 范围的边界活在操作数栈上——它活在一个局部槽里，而槽不受 handler 清栈影响。
- `release` 求值为 `Unit`，**在两条路上各求值一次**：正常出口一次，unwind 出口一次。
- `CSProtect` **不接住**失败。unwind 路径跑完 `release` 之后原样继续传播。它是 finally，不是 catch。

四条不变量，按「谁保证」分列：

| # | 不变量 | 谁保证 |
|---|---|---|
| I1 | `body` 里没有目标在区间之外的 `CReturn`/`CBreak`/`CContinue` | **lowering 按构造保证**（§2.6：唯一的产出方把 body 建成一个调用） |
| I2 | `release` 是调用形状（`CCall`/`CIntrinsic`），不是任意子树 | lowering；理由见 §2.4 的「release 发两遍」 |
| I3 | 进入 `CSProtect` 时操作数栈为空 | `CStmt` 的位置 + `gen_cstmt` 现有纪律 |
| I4 | `result` 只被同一个 `CBlock` 里紧随其后的语句读到 | lowering |

**I1 要有门禁，不能只写在文档里。** `coredump.dawn` 已经是 Core 的可读化输出，
`scripts/selfhost-core-diff.sh` 已经在 CI 里；I1 的检查放进 `dawn __lower` 的覆盖率走查
（`main.dawn:1300` 附近那趟 `catch_panic(fn() => one(...))`）最省事：走查时对每个 `CSProtect`
的 body 做一次「有没有逃逸跳转」的遍历，有就 panic，走查把它报成 GAP。

### 2.4 JVM 渲染

`emit.dawn` 今天有且只有一处内联 try/catch：`gen_jvm_main`（:1263），入口包装。它的形状**就是**
`CSProtect` 要的形状，可以照抄：

```
  visitTryCatchBlock(try_start, try_end, handler, null)   ; null = finally，接一切
try_start:
  <body>                        ; 进来时栈空
  store_slot(ty, slot_of result)
try_end:
  <release>                     ; 正常路径
  goto after
handler:                        ; JVM 清栈，只压一个 Throwable
  ASTORE exc
  <release>                     ; 异常路径
  ALOAD exc
  ATHROW
after:
```

四处要点：

1. **`null` 类型的 handler = finally。** ASM 的 `visitTryCatchBlock(.., null)` 就是 catch-all；
   `codegen.dawn:1012` 的 `gen_try_closure` 已经在用带具体类型的版本，API 是同一个。
2. **release 发两遍。** javac 现代版本也是复制 finally 体（JSR/RET 早已废弃）。**代价由 I2 兜住**：
   release 是一次调用，复制的是一条 INVOKE，不是一棵树。lowering 本来就会把 release 的 lambda
   提升成顶层函数（`LSt.lifted`），所以 I2 是白拿的。
3. **栈图由 ASM 算。** `AdtClassWriter` 是 `COMPUTE_FRAMES`（`super(COMPUTE_FRAMES)`），handler
   的帧不用手写。**但**它覆写了 `getCommonSuperClass`，未知配对会 `super.getCommonSuperClass`
   走类加载——handler 的栈是 `java/lang/Throwable`，JDK 类，能加载。这条进 §4 的风险登记。
4. **`exc` 与 `result` 各占一个槽。** `alloc(g, n)` 只增不减（`next_slot` 单调），所以两个槽是
   净增，不与任何别的绑定冲突。方法的 `maxLocals` 由 `COMPUTE_FRAMES` 一并算。

### 2.5 native 渲染

`runtime/c/dawn_rt.c` 已经有整套 unwind 设施，`CSProtect` 是在它上面加**一个**函数：

- 现状：`dawn_handler { jmp_buf jb; struct dawn_handler *prev; bool catches_panic; }` 组成一条
  handler 链（`dawn_handlers`）；`dawn_raise(msg, is_panic)` 从内向外找第一个肯接的 handler，
  把消息拷进 `dawn_failure_buf`、种类写进 `dawn_failure_kind`，然后 `longjmp`；
  `dawn_run_caught` 是 `catch_fault`/`catch_panic` 共用的 setjmp 侧。
- `CSProtect` 要的是「接住、跑 release、**再抛出去**」，所以缺的正好是一个 **re-raise**：

```c
/* 挂一个无条件接住的 handler；跑完 release 之后把原样的失败交给下一层。 */
static void dawn_reraise(void);   /* 用 dawn_failure_* 里还在的那份，从 dawn_handlers 继续找 */
```

两处细节，都是真的而不是修辞：

- **`is_panic` 今天没被存下来**。`dawn_failure_kind` 存的是 `"panic"`/`"fault"` 两个字面量，
  re-raise 要还原「这是不是 panic」才能正确决定外层哪个 handler 肯接。最小改动是加一个
  `static bool dawn_failure_is_panic;`，和 kind 同处写入。**这是 C2 在 native 侧的全部新增状态。**
- **`catches_panic` 必须是 `true`**。finally 要对两种失败都跑 release；它不停止 panic，
  它 re-raise。「接住但不吞」在这条链上是可表达的，因为链的推进由 setjmp 侧自己做
  （`dawn_handlers = h.prev` 之后再 raise，自然找下一层）。

emitc 侧对应地长出一条 `CSProtect` 臂：局部 `dawn_handler h` + `setjmp` + 两个调用点。
它和 `CSLoop` 那条臂是同一个量级。

### 2.6 减法：closure 定界时，这个节点不必被建出来

**这是本文最重要的一节。** 把上面两小节的设计和今天的代码放在一起，会得到一个 C2 写作时
不可能知道的结论。

C2 冻结的论证是：「codegen intrinsic 发 JVM finally 块 = 把 bracket 绑死在 JVM 上，
native 没有 finally，bracket 会变成第二份实现。」

**这个论证在 `catch_fault` 落地之后不成立了。** 看今天的屏障：

| | JVM | native |
|---|---|---|
| `catch_fault` | `codegen.dawn:1161` 生成 `dawn/rt/Io.catch_fault(Fn0)`，方法体里一个真 try/catch | `dawn_rt.c:759` `dawn_catch_fault(dawn_clo*)`，setjmp |
| Core 里的样子 | `CIntrinsic("catch_fault", [clo], ty)` | 同一个节点 |

**这不是「第二份实现」，这是 intrinsic 契约本身。** `runtime-intrinsics-design.md` §4 的第②层
就是这个：「一小组抽象原语，语言命名、后端各自实现」。两个后端为 `str_len` 各写一份实现不叫重复，
为 `catch_fault` 各写一份也不叫。C2 当时把「后端各自实现一个**原语**」和
「后端各自重写一遍 **lowering**」混成了一件事——Move 2 要杀的是后者，不是前者。

于是问：`bracket` 需要 `CSProtect` 吗？

`bracket(acquire, use_it, release)` 的三个参数都是**闭包**。受保护的区间因此是
`CCall(use_it, [a])` ——**一次调用**。而一次调用：

- 满足 I1，且是**平凡地**满足：`use_it` 体内的 `return` 返回的是 `use_it`，
  `?` 传播的是 `use_it` 的返回值，`break` 被检查器在闭包边界上就拒了。
  逃逸**在语言层面就跨不出闭包**。
- 满足 I2、I3、I4 同理。

**一个受保护区间恒为一次调用的 protect，就是一个取闭包的运行时函数。** 它可以是：

```java
// dawn/rt/Io.bracket(Fn0 acq, Fn1 use, Fn1 rel)
Object a = acq.apply();
try { return use.apply(a); } finally { rel.apply(a); }
```

```c
/* dawn_bracket(acq, use, rel) —— dawn_reraise 仍然要，位置从 emitc 挪进 runtime */
```

零个新 Core 节点，`lower.dawn` 一行不改，`emit.dawn`/`emitc.dawn` 各一条已有形状的 intrinsic 臂
（`rt: RtIo`，名字各后端自己拼——§12.1 之后这一步是自动的）。C2 的三条实质要求——
**release 一定执行、原始失败继续传播、栈不变**——逐条兑现。

**那 `CSProtect` 什么时候真的要？** 当受保护区间**不是**一个闭包的时候。也就是：当 Dawn 长出
`defer` 或 `try { } finally { }` 这样的**面语法**，让区间和它的宿主函数共享一个栈帧、
从而可以被 `return`/`?`/`break` 穿出去。那时 I1 从「白拿」变成「lowering 要把每条逃逸边
改写成先跑 release 再跳」，`CSProtect` 也从「可有可无」变成「唯一的写法」。

而 `audit/error-model-design.md` §三明确写了**不给语法**：「不给 Dawn 加 `throw`/`catch`」、
C 一节的标题就是「先给标准库函数，不给语法」。**所以在今天的决策集合里，`CSProtect` 没有客户。**

这不是说 §2.3–2.5 白写了。它们是**为那个决策被推翻时准备好的图纸**，而 §3 会说明这张图纸
在 pass 架构里落哪儿。§6 的开放决策 1 就是把这件事交出去。

### 2.7 关于「不给语法」这条，有一份反证要一并交出去

一次全仓走查（`catch_panic`/`catch_fault` 的 60+ 个调用点逐个看）的结果，值得原样记下来，
因为它把「三处手写惯用法都是直线体」这个前提**打了折**：

**C2 点名的三处确实都是直线体**，路径与文档的简写略有出入：

| | 位置 | 形状 |
|---|---|---|
| permit | `playground/src/play/gate.dawn:25` `with_gate` | `try_enter` → `catch_panic(body)` → `leave` → 重抛 |
| upstream stream | `packages/web/src/server.dawn:86` | `catch_panic(fn() => s.transferTo(out))` → `close_stream(s)` |
| 临时 body 文件 | `packages/web/src/server.dawn:283` | `catch_panic(fn() => app(req))` → `delete_quietly` |

三处的注释都写着同一句话：「Dawn has no try/finally, so catch_panic plays that role」。

**但「都是直线体」是幸存者偏差**，两条证据：

1. **有人为了让 release 单出口，把体挪进了兄弟函数。**
   `selfhost/src/pkgfetch.dawn:435` 取临时目录、调 `fetch_into(url, work)`、`delete_tree(work)`；
   而 `fetch_into` 的体是**连着四个 `return Err(e)`**。受保护区间本来就是早退形状，
   只是被搬下去一帧，好让释放能写成直线。
2. **没搬的地方就在漏。** `selfhost/src/main.dawn:1086` `run_build` 取了临时目录，
   紧接着一个 `return cli_error(...)`，**没有释放**；`nmain.dawn:134` `cc_build` 与 `:199` `cmd_run`
   各取一个临时目录、各有早退、**都不释放**；`selfhost/src/vendor.dawn:96,177` 的 `JarFile`
   在循环里 `panic` 时跳过 `jf.close()`（其中 `:177` 那处还嵌在 `for` 里，天然的 `break` 案例）；
   `jarw.dawn:72` 的 `FileOutputStream`+`ZipOutputStream` 在 `put()` 撞重名条目时两个都漏。

数量：3 处点名 + 10 处同形状且**今天就在漏** + 2 处同形状且正确 = **15 处生产代码**，
另有 5 处脚本。其中「acquire 与 release 分在两个函数里」的最难一例是
`main.dawn:1086` 取、`main.dawn:1024` 放。

**这批数据不改变 §2.6 的结论，但它改变结论的有效期。** 闭包版 `bracket` 能服务的是
三处点名 + 两处 Tier 2，以及 Tier 1 里肯做一次机械重构（把体提成一个闭包）的那些；
剩下的——尤其是跨函数的那一例——要的不是标准库函数，是 `defer`。
**所以「不给语法」这条决策，应该在看过这 10 处泄漏之后再确认一次，而不是照抄。**

## 3. Pass 架构

### 3.1 流水线现状，以及新 pass 会插在哪

```
lexer → parser → checker(TAST) ──► lower.dawn(Core) ──┬──► emit.dawn      → JVM 字节码
                                       │              ├──► rc.dawn → emitc.dawn → C
                                       │              └──► interp.dawn    → comptime 值
                                       └── reach.dawn（读 LMod.m 决定 Unicode 表货运）
```

`lower.dawn` **不是一趟 tast→tast pass，它是 tast→Core 的唯一一趟**，`LMod`
（`lower.dawn:3072`）是它的产物：`m` 是给整翻译单元后端（emitc）的扁平 `CModule`，
`fns`/`tests` 是给 JVM 的分组形式（一个源函数配上为它提升出来的体），`dicts` 是不删减的字典表，
`emitted_core(l)`（`:3240`）把两半拼回给「要看见一个 jar 里全部东西」的消费者。

**这个形状回答了 Move 2 原方案的一个问题**：「pass 是一趟还是每特性一趟」。答案是
**一趟**，而且已经是了——因为它不是 tast→tast 的可选改写，它是**换表示**，中间没有第二个消费者。
`rc.dawn` 是唯一一个 Core→Core 的 pass，只在去 C 的路上跑（`rc.dawn` 文件头：
「It runs on the way into the C backend and nowhere else -- the JVM has a collector」），
这也正是「knife 2 changes no JVM byte」能按构造成立而不是靠检查成立的原因。

### 3.2 顺序约束

若 `CSProtect` 要建，它的顺序约束只有三条，都是被现有结构定死的：

1. **在 lowering 内部产生**，不是之后的改写。理由和自尾调用是同一条（`native-backend-plan.md`
   记的教训）：「尾位置**必须在 lowering 期间跟踪**——等 Core 建完再回头找就晚了」。
   protect 同理，等 Core 建完再找「哪段是受保护区间」，那时 `bracket` 已经变成一个普通调用了。
2. **在派生 `Ord`/`Eq` 合成之后**没有约束——两者不相交（合成的是相等关系的体，protect 包的是
   资源区间）。**在 `reach` 之前**也没有约束：`reach` 读 `LMod.m` 数 Unicode 表货运，protect 不带表。
3. **在 `rc.dawn` 之前**，且 `rc.dawn` 必须认识它——见 §3.3，这是唯一一条**硬**约束。

### 3.3 `rc.dawn` 是唯一一处真的会疼

`rc.dawn` 底部的 `rc_check` 是这个 pass 的本地 oracle：它走结果，
**坚持每个绑定在每条出口路径上恰好被释放一次**。`CSProtect` 引入的 unwind 路径是一条
**`rc_check` 看不见的新出口边**。两个后果：

- **不改 `rc.dawn` 会怎样**：`CSProtect` 的 body 里铸的绑定在 unwind 路径上不被 drop，
  也就是漏。**而这在 native 上已经是写明的设计内例外**：`perceus-design.md` §7 的门禁一节写着
  「**被接住的 fault** 会漏掉 longjmp 丢弃的 C 帧所持引用（catch_fault 的机制成本），
  这样的语料程序旁边放 `<name>.leaks-on-catch` 标记、单独关检测」——`scripts/spike-native/`
  里就有 `catch_kinds.leaks-on-catch` 这个文件。
- **所以 `CSProtect` 的 native 泄漏不是新债，是同一笔旧债的同一条腿。** 一个用了 protect
  且走了 unwind 路径的语料程序，照现有惯例放一个 `.leaks-on-catch` 标记即可。
  **这条要写进 knife 的验收里**，否则 asan 档会红，而红的原因会被误诊成 codegen bug。

反过来，**闭包版 `bracket`（§2.6）连这一条都不欠**：受保护的东西在 `use_it` 的帧里，
longjmp 丢弃它和 longjmp 丢弃 `catch_fault` 的帧是同一件事、同一个已登记的例外。

### 3.4 comptime 怎么办

`interp.dawn:674` 附近有一张「comptime 不给用户代码看见」的名单，`catch_fault`/`catch_panic`
在上面（`out = out ++ ["args", "catch_fault", "catch_panic"]`），理由写在那儿：
「`catch_fault`/`catch_panic` take an `!io` thunk they would have to run」。

**`bracket` 走同一条路：进那张名单。** 无论它是 intrinsic 还是 `CSProtect`，
comptime 都不需要认识它——一个 `const` 折不出资源。这是零成本的一条，但要显式做，
因为 `lower.dawn:520` 的注释记着：「an intrinsic in neither this list nor `types.intrinsics()`
is a name no dispatcher should have an arm for, which is how the three dead arms were found」。

## 4. 刀法

先说一句会改变整节读法的话：**§1 的结论是刀 A 与刀 B 不存在**——它们已经落地，
验收记录在 `native-backend-plan.md` §Phase 0。下面给的是**残余**的刀法。

### 刀 1 — `bracket` 作运行时 intrinsic（推荐先做，是 C2 的解冻）

**scope**：`types.dawn` 加一条 intrinsic（`rt: RtIo`）；`codegen.dawn` 在 `dawn/rt/Io` 里写
`bracket`（`gen_try_closure` 旁边，同款 handler 纪律）；`runtime/c/dawn_rt.c` 加
`dawn_failure_is_panic` + `dawn_reraise` + `dawn_bracket`；`interp.dawn` 的 comptime 名单 +1；
`doc.dawn` 的 interop 组 +1；三处手写惯用法改写。**零个 Core 节点，`lower.dawn` 一行不改。**

**验收**：

| 门禁 | 期望 |
|---|---|
| `./bin/dawn test selfhost` / `test site` / `json-suite.sh` | 全绿 |
| `scripts/selfhost-fixpoint.sh` | B == C |
| `scripts/selfhost-core-diff.sh` | **13 份 dump 逐字节不变**；`selfhost.sha` 只有真改到的模块动。**不需要 `--record`** ——Core 的节点集没变 |
| `scripts/selfhost-prev-diff.sh` | **有差异**：`dawn/rt/Io.class` 多一个方法 → `Emit-Change(emit *): ...` |
| `scripts/spike-native/run.sh` | 新增一个 bracket 语料（正常路径 + 失败路径各断言 release 跑过）；失败路径那支配 `.leaks-on-catch` |
| `scripts/error-contract/run.sh` | 加一条：release 跑过之后**原始 `kind`/`message` 逐字不变**地传到外层 |
| `bin/dawn fmt … --check` / `doc-check.py` / `site/build.sh` | 清 |

**逐字节不可能的地方，明说**：`Emit-Change` 是**必然**的——往 `dawn/rt/Io` 里加方法就是改输出。
这与 `cast_e` 那次（§6.10）形状完全相同，那次的差异是「六个 emit 目标各差一个文件」，
本刀应当**完全一样**。若差异不止 `Io.class` 一个文件，说明碰到了不该碰的东西，**停下来查**。

**风险登记**：
- `dawn/rt/Io.bracket` 的 descriptor 要用 `Fn0`/`Fn1` 的擦除约定（`Object apply(Object)`），
  三个闭包的返回都在擦除位——**装箱由 lowering 的 `CBox` 负责，emitter 不要自己加**。
- `dawn_reraise` 忘了还原 `is_panic` → 一个被 protect 穿过的 panic 会被外层 `catch_fault` 接住，
  而它本不该接。**这条必须有语料**：`catch_fault(bracket(..panic..))` 必须仍然是致命的。

### 刀 2 —（条件性）`CSProtect` 节点

**只在开放决策 1 判为「要 `defer` 面语法」时才做。** scope：`core.dawn` 加一个 `CStmt` 变体、
`coredump.dawn` 加它的打印、`lower.dawn` 产出它（含 I1 的逃逸边改写）、`emit.dawn` 与
`emitc.dawn` 各加一条臂、`rc.dawn` 认识新出口边、`dawn __lower` 的走查加 I1 检查。

**验收**：同刀 1，**外加**：
- `scripts/selfhost-core-diff.sh` **必然 `--record`**：节点集变了，dump 变了。
  这是那道门禁自带的纪律（脚本头写着 `--record` 用法），**不是 Emit-Change**。
  `--record` 的提交要把 diff 读一遍——它是可读的，这正是那份 golden 存在的理由。
- `rc-contract/run.sh` 与 asan 档：新出口边的 drop 语义，见 §3.3。

**风险登记**（这把刀是本文里唯一有「可能做不到逐字节」的）：
- **I1 的逃逸改写会改变已有代码的字节。** 一旦 `defer` 存在，任何函数体都可能含 protect，
  而 lowering 对逃逸边的改写（先跑 release 再跳）会改 `?` 与 `return` 的发射形状。
  **这不是 output-preserving 的改动**，它是 Emit-Change，而且是**范围广**的那种。
  **这条改变该刀的发布纪律**：按 CONTRIBUTING §六走 tag + 种子推进，不能夹在别的刀里。
- `getCommonSuperClass` 覆写 + `COMPUTE_FRAMES`：handler 帧的合流若牵出未登记的类对，
  会走类加载。JDK 类没问题，**Dawn 自己生成的 ADT 类若在 handler 后合流则要看 supers 表**。
  缓解：handler 分支只做 ASTORE/调用/ATHROW，**不与正常路径合流**（§2.4 的形状就是这样，
  `after:` 只有正常路径到达）。
- **操作数栈**：I3 由 `CStmt` 保证，但**若谁把它改成 `CExpr` 就地垮掉**——§2.1 引的那段话
  一字不差地适用。这条要写进 `core.dawn` 的节点注释里，因为文档会过期而注释在现场。

### 刀 3 — （非本文 scope，登记）`defer` 的面语法

若开放决策 1 判「要」，语法、检查器、spec 是独立一刀，且**排在刀 2 之后**——
先有节点、后有语法，反过来会让语法落地那天同时欠一个 IR 和一批逃逸改写。

## 5. 明确不做

- **Move 3（装箱）**：不在本文 scope，且**已经完成**——`CBox`/`CUnbox` 在 `core.dawn:141`，
  决策点在 `lower.dawn:153`。本文只是登记它比 Move 2 先到（§1.1）。
- **后端 #2 本身**：Phase 3 已完成，不在本文。
- **`TJavaCall` / `CForeign`**：**保持 JVM-only**。`core.dawn:167` 的注释就是这条决策：
  「the native backend refuses this node, and `use c` will get its own, which the JVM backend
  will refuse in turn」。protect 不碰它。
- **把 `catch_fault`/`catch_panic` 改成 Core 节点**：不做。它们是 intrinsic，
  §2.6 论证了那是对的形状；改成节点会把「后端各自实现一个原语」误当成「后端各自重写 lowering」。
- **给 `bracket` 多资源版本（`bracket2`/可变列表）**：不做。两处站点持有两个资源
  （`jarw.dawn` 的 fos+zos、`site/src/gen/pages.dawn` 的 in+out），嵌套两层 `bracket` 够用，
  而每加一个形状就多一个要在两个后端里发射的名字（这条是 `audit/error-model-design.md` §四
  拒绝 `java_try_catching` 的同一条理由）。
- **任何需要 Emit-Change 的改动**——**除了两处，都已列明理由**：刀 1 的 `Io.class` 加一个方法
  （不可避免，且与 `cast_e` 同形），刀 2 的逃逸改写（不可避免，且**必须单独发布**）。
  除此之外本文不接受 Emit-Change。
- **`interp.dawn:1616` 的 TAST 走查**：不动。它跑在 lowering 之前收集 comptime span，
  按定义只能看 TAST（§1.5）。

## 6. 开放决策

> **三条均已裁决（2026-07-31，用户，附对 Rust/Kotlin/Koka/Gleam/Go/Haskell 的横向调研）**：
>
> 1. **C（intrinsic + 留糖后路）**——刀 1 现在做；**签名取 Haskell 序
>    `bracket(acquire, release, use)`（use 在最后）**，为将来 Koka `with`/Gleam `use` 式
>    「剩余块作尾闭包」的 parser 级糖留路（糖机制 = 剩余块附加为**最后一个**实参；
>    本文正文示例写的旧序 `(acq, use, rel)` 以本裁决为准）。`with` 已查证：不在关键字表、
>    全仓（含 backend-dawn）零同名标识符，升格属破坏窗口，候选与 #90 同窗；`use` 被导入
>    语义终身占用，不复用。defer/糖/关键字升格**另行裁决**，带上 §2.7 的 10 处泄漏与调研。
> 2. **A（返回 `B`）**——protect 与 catch 正交；Haskell `bracket`/Kotlin `use`/Koka
>    `finally`/Go `defer` 无一返回 Result，行业全体一致。
> 3. **A（站点迁移分开、滞后一个发布）**——selfhost 内站点本被自举强制滞后
>    （种子要先认识 bracket）。
>
> **同日修订（大前提变更：语言处早期，不惧破坏、只求最优形态）**——「另行裁决」的部分就地定案：
>
> **落地记（2026-08-01）**：bracket intrinsic 随 v0.39.0、`with` 语句与 `fn` 尾闭包随
> v0.40.0 均已发布（语义入 spec §4.10/§4.3/§9.8.2）；下文从「目标」读作「已发生」。
>
> - **`with` 语句不再等窗口**：紧随刀 1 排期（目标 v0.40.0：`with x <- f(...)` 关键字 + `<-`
>   形式 + checker 拒糖区内 `return`/`break`；`?` 透明组合）。10 处泄漏站点**直接用最终形态**
>   迁移，不经历裸嵌套闭包的中间态。
> - **`fn` 尾闭包（Koka 式）同批**：纯新增零歧义，SYN 统一后只动唯一后缀应用节点；`with`
>   服务线性资源、尾闭包服务树形 DSL（Compose 式 UI 是其最强需求方），两糖各管一半。
>   裸 `{}` 尾闭包（Kotlin 式）维持不做——被无括号 `if` 头的解析歧义否决，与破坏容忍无关。
> - **defer / `CSProtect` 正式关档「不做」**：零迁移成本下重比，输的不是成本是形态——隐式
>   控制流的语句机制与纯表达式语言相斥（FP 系全体不设），唯一优势（保护区内 `return`/`break`）
>   在表达式导向 + `?` 透明组合下不承重。§2.3–2.5 图纸存档，推翻需新证据。
> - **连锁**：积压的破坏窗口队列（RD-06 命名族、RD-09 尾款、RD-14 渲染，#90 视 lexer 进度）
>   排成有日程的破坏批，v0.40.0 后紧随清算，不再「等着」。
>
> **再修订（同日，lambda 人体工学轮）**：
>
> - **acquire 改急切值**：`bracket(resource: A, release: fn(A) -> Unit !e, use: fn(A) -> B !e) -> B`
>   ——Dawn 无异步异常，「资源已取、保护未装」的窗口里没有用户代码可跑，thunk 无保护收益
>   （Haskell 包 thunk 只为异步异常；Koka `finally` 即急切形）。两个闭包位而非三个；
>   配合 with 糖后资源代码零 lambda：`with f <- bracket(open(path), close)`。
> - **箭头 lambda 进破坏批（#109）**：`x => e` / `(a, b) => e` / `() => e`，去掉 `fn` 仪式
>   （`=>` 已独占标记 lambda，match 臂是 `->` 不冲突；parser 用 JS/Scala 式重解释）。
>   **尾闭包位保留 `fn` 拼写**保无歧义（否则与柯里化调用 `f(a)(x)` 撞）。占位符 lambda
>   （Kotlin `it`/Scala `_`）判不做：边界歧义与显式气质相斥。具名函数裸传（eta 缩减）
>   今天已可用，是消 lambda 噪音的第一手段。
> - **match 臂 `->` 与 lambda `=>` 刻意不统一**（spec §4.5 已记原则）：去 `fn` 后 `=>` 接过
>   「lambda 起点标记」职责，臂体嵌 lambda 时两种箭头是唯一视觉信号（Rust 同款分立，
>   Scala 式统一反而在最需要区分处失去区分）。`->` = 子句箭头（类型、臂），
>   `=>` = 表达式箭头。

### 决策 1 —— `bracket` 是运行时 intrinsic，还是 Core 节点？

**推荐：intrinsic（刀 1），并把 `CSProtect` 的图纸留在 §2.3–2.5 备用。**

理由是 §2.6 的减法：受保护区间恒为一次闭包调用时，protect 就是一个取闭包的运行时原语，
和 `catch_fault` 一模一样；而「两个后端各实现一份原语」是 intrinsic 契约本身，不是重复。
C2 冻结时的反对论证（「绑死 JVM」）针对的是 codegen 特例，不是 intrinsic 契约——
那份文档写在 `catch_fault` 定形之前。

**但要带着 §2.7 那 10 处泄漏一起判**：intrinsic 版服务不到跨函数的 acquire/release，
也服务不到「体里有早退」的那些（要先做一次把体提成闭包的机械重构）。
**若判定那 10 处必须被服务，则本决策连带推翻 `audit/error-model-design.md` §三的「不给语法」**，
并按刀 2 → 刀 3 的顺序走。

### 决策 2 —— `bracket` 的返回类型：`B` 还是 `Result[B, ForeignError]`？

**推荐：`B`。**

`audit/error-model-design.md` §二.C 给的签名是 `-> Result[B, ForeignError]`，但同一节对 C2 的
描述是「**原始失败继续向上传播**」。两句互相矛盾：返回 `Result` 就是接住了，就没在传播。
那个签名是 C1（纯 Dawn、内部 `catch_panic`）的形状被带进了 C2 那一段。

返回 `B` 的好处是**正交**：protect 和 catch 是两件事，要 `Result` 的调用方写
`catch_fault(fn() => bracket(...))`，两个原语各做一件事。三处手写惯用法里
`with_gate` 现在正是「接住 → 释放 → **重新 panic**」，返回 `B` 之后它整个塌成一行。

### 决策 3 —— 三处（或十五处）站点的迁移，跟刀 1 同批还是分开？

**推荐：分开，且滞后一个发布。**

刀 1 会 Emit-Change（`Io.class` 加方法），按 CONTRIBUTING §六要先发 tag；
而站点迁移不改发射、只改调用方，是单阶段安全的。混在一起会让「这次改动改了什么字节」
这个问题多一个答案。先落原语、发版、再迁站点。

`selfhost/src/` 里那些站点（`pkgfetch`/`vendor`/`jarw`/`nmain`/`main`）另有一条约束：
它们要过两张表（种子 + HEAD），所以任何签名变更走三期两发布——这条是 §6.2 的老规矩，
但迁移到一个**新增**的函数不改任何已有签名，**不受它约束**。

---

## 附：本文推翻的两处旧记载

1. **[`runtime-intrinsics-design.md`](runtime-intrinsics-design.md) §8 的三步 Move 表**：
   Move 2 与 Move 3 都已落地，落在 `native-backend-plan.md` 的 Phase 0 里，且 Move 3 先于 Move 2 完成。
   §8 那三个行号（`emit.dawn:764,1026,1456`）指向的是 3568 行时代的文件，今天 2506 行、
   那三处不存在。
2. **[`audit/error-model-design.md`](audit/error-model-design.md) §二.C 的「C2 冻结，等 Core IR」**：
   Core IR 到了，冻结解除；但解除之后看到的第一件事是它**可能不需要被建**（§2.6），
   而它的返回类型签名与它自己的描述矛盾（决策 2）。
