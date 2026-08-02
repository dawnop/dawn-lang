# 与 native 后端计划的重合登记

> 状态：**current**。这份文档只做一件事：**记下 [`../native-backend-plan.md`](../native-backend-plan.md)
> 与本目录九份设计方案在哪里撞上了**，以及每一处该怎么处理。
>
> 它是一份台账，不是方案。方案在各自的文档里，这里只写「谁让位、谁冻结、谁要改」。

## 零、为什么需要这份台账

两条线是**独立写出来的**：

- `native-backend-plan.md` 2026-07-25 在 main 上定稿，全文只引用了
  `codebase-audit.md` 一次（§5 的 TEST-01），**没有引用 `docs/audit/`**——
  本目录的九份文档当时还在 `audit-fixes` 分支上，没进 main。
- 本目录的九份文档也没看过那份计划。

所以两边的重合是**独立趋同**，不是集成。趋同的地方（比如「要一层 IR」「验收是零
Emit-Change」「不做 SSA」）是好消息——两次独立推导得到同一个结论，说明结论稳。
**撞车的地方才是这份台账存在的理由**：同一批文件、同一批调用点、两份排期，
谁先动谁就让另一份返工。

**处理原则：不重合的先做，重合的冻结并登记。** 冻结的不是「以后再说」，
是「等 native 那条线的某个具体决议落地，然后按登记的改法做」——每条都写明等什么。

## 一、总账

按 `../codebase-audit.md` §15 的 33 个编号：

| 类别 | 条数 | 编号 |
|---|---:|---|
| **A. 被计划吸收**，本目录让位 | 5 | ARCH-03 ARCH-04 BOOT-01 TEST-02 ARCH-05 |
| **B. 撞车**，冻结或改写（§三） | 9 | ARCH-01 ARCH-02 ARCH-06 ERR-02 ERR-03 LANG-02 LANG-04 LSP-01 REL-02 |
| **C. 不重合**，现在就做 | 19 | 其余 |

C 的 19 条见 [README.md](README.md) §三的批次表——那里是排期，这里不重复。

## 二、A 类：被吸收的五条

| 编号 | 吸收进 | 说明 |
|---|---|---|
| **ARCH-03** | 整份计划 | 「第二后端只改 intrinsic 表不成立」是问题陈述，计划是完整答案（Core IR + `use c` capability + C 发射器），比 [lowered-ir](lowered-ir-design.md) §3 表走得远得多。 |
| **ARCH-04** | Phase 0 | 「无 IR 的原始论证已过期」。两边独立得出同一结论：**一层** IR、不做 SSA、验收是零 Emit-Change。计划的措辞「任何 Emit-Change 都说明搬错了」与本目录的「不接受 `Emit-Change:` 豁免」是同一句话。 |
| **BOOT-01（P0）** | Phase 2（D1–D3） | 集合运行时只有续传二进制、没有主干源码。集合纯 Dawn 化之后这条自然消失。 |
| **TEST-02** | Phase 2 | 同上——纯 Dawn 的集合有源码级 test，不再需要给二进制补测试。 |
| **ARCH-05 前两条建议** | Phase 2 + Phase 0 | 「运行时支持以手写 ASM 生成」。第三条建议（把 opcode/descriptor 收进一个后端模块）**不在**计划里，归 B 类的 ARCH-01/02。 |

这五条在 `codebase-audit.md` §15 里本来就有三条标了「被另一条线覆盖」。
现在那条线有排期、有工程量估算、有实测支撑（`5863df6` 的 spike），台账可以合上。

## 三、B 类：撞车的九条，逐条登记

### 3.1 ARCH-01 / ARCH-02：计划里根本没有

**撞的不是内容，是覆盖范围。** 计划的 Phase 0 只做「抽出 Core IR」，
46 字段的 `Cx` 和 31 字段的 `Gen` 原样留着。而 Phase 5 还要往 checker 里加
`use c` 的解析面——`Cx` 只会更大。

**处理：不冻结，但改排期。** 拆 God module 仍然是本目录的事，
排在 **Phase 0 之后、Phase 5 之前**：
- 之后，是因为 [lowered-ir](lowered-ir-design.md) §1.3 的论证不变——没有 IR，拆到哪儿都还是直连；
- 之前，是因为 `use c` 落到一个已经拆开的 checker 上比落到 7,924 行的单体上便宜。

已写进 [lowered-ir-design.md](lowered-ir-design.md) §7 的阶段表。

> **更新（2026-08-03）**：Phase 0 已落地，这条的排期条件到期。方案改由
> [`../arch-split-design.md`](../arch-split-design.md) 承接（lowered-ir §7 的 E/F 两行已划掉）。
> 本节的数字也全线过期：`Cx` 今天是 **47** 字段、`checker.dawn` 是 **11,308** 行，
> 而 `Gen` 反向缩到 **21** 字段、`emit.dawn` 缩到 **2,534** 行——lowering 搬进 Core
> 之后 emitter 那半边的病情自己好了一大半，剩下的病灶在 `codegen.dawn`（3,425 行，
> 一次都没提到 `Gen`）。**「ARCH-01 ──► ARCH-02」是排期不是技术依赖**：`emit.dawn`
> 是叶子、与 checker 零耦合，两条 lane 可并行（该文 D12）。

### 3.2 Core IR 的节点集：本目录漏了两样

计划 Phase 0 要搬四样，本目录的 `LIR` 只覆盖其中两样：

| 计划 Phase 0 要搬的 | 本目录 §3 有没有 |
|---|---|
| 结构化控制流 + 语法糖（含 match 决策树） | ✅ 表里的 2、3 |
| **装箱/擦除**（`adapt_to`/`adapt_from` 在每个调用点重算「槽是不是 TyVar」） | ❌ **漏了** |
| intrinsic 语义（`rt_intrinsic_target`） | ✅ 表里的 6（以 capability 形式） |
| **RC 感知**（dup/drop 节点、owned/borrowed 参数模式） | ❌ **漏了** |

第二样计划称它是「Rank 1 最烂的耦合」，本目录完全没看见。
第四样是 Perceus 决策的直接后果——**它不是补一个节点，是改 IR 的形状**：
每个值的所有权状态要能在 IR 上表达，JVM 后端把 dup/drop 当 no-op 忽略。

反过来，本目录有两样计划的 Phase 0 清单里没明写：**closure 捕获列表**与
**trait witness 显式化**。Phase 3 需要它们（手写环境 struct、字典函数指针表），
只是没写进 Phase 0。`LForeign(capability_id, args)` 那条正好就是 `use c` 要的接口形状。

**处理：[lowered-ir-design.md](lowered-ir-design.md) §3 的表已补成两边的并集。**
这份文档因此从「本目录的方案」降级成「计划 Phase 0 的补充材料」——
真正动手时以计划的 Phase 0 为准。

### 3.3 `JavaError` 在 native 上没有意义（ERR-02）

计划 §1 定了 panic = setjmp/longjmp，两个捕获点是「catch_panic / `java_try` 的**对应物**」。
本目录设计的错误记录是：

```dawn
pub type JavaError = { class_name: String, message: String, cause: Option[String] }
```

`class_name` 是 **JVM 二进制名**——native 上没有类名。整个类型是 JVM-ism。

**处理：改成后端中立的形状**，已写进
[error-model-design.md](error-model-design.md) §2.A。不冻结——A 步是纯 JVM 侧的
改动，早做早收益，只要类型定义从第一天就不假设有 JVM 类名。

### 3.4 `bracket` 的 C2 版是 JVM codegen 特例（ERR-03）

本目录的 C2 是「`bracket` 作 intrinsic，codegen 发 JVM `try/finally`
（`visitTryCatchBlock` 带 `null` 类型）」。native 上没有 finally，
要靠 setjmp/longjmp 的 unwind 保护。

**处理：C2 上移成 Core IR 节点**，两个后端各自发射。
好消息是这一改让 C2 从「等 lowered-ir 阶段 C」变成「**就是** IR 的一部分」——
依赖关系反而简单了。**冻结，等 Phase 0。**

### 3.5 `ceval` trampoline 化与 R6 撞车（ARCH-06 + LANG-01 建议 3）——**已结账**

> **2026-07-31 结账。** R6 已于 07-25 决议（interp 吃 Core），本条的冻结条件消失；
> 随后的收益重估把步骤 3 判为**不做**，裁决与实测在
> [ceval-trampoline-verdict.md](ceval-trampoline-verdict.md)。
> 关键数字：深输入下 parser 每层烧 16 帧、`-Xss1m` 只吃得下 153 层嵌套，
> 比 `ceval`（159 层）更早倒——**trampoline 掉 `ceval` 只是换个先崩的 pass，
> `-Xss512m` 摘不掉**；而真实语料（含编译器自己 31,175 行）在 `-Xss256k` 下编得过，
> 也不需要靠它摘。下面的原文保留：翻案条件（那份 §七）成立时它仍是起点。
>
> 连带作废的是 §五「这份台账什么时候可以删」的条件 2——R6 决议已到期且已消费。

计划 R6 写得很明确：

> `interp.dawn` 有 `len/get/range/sort_by/concat` 的原生臂和 `VList`，且 `CValue`
> **没有 `VMap`/`VSet`**。Core IR 落地后，interp 该吃 Core 还是继续吃 TAST?
> **此项未决，不阻塞 Phase 0，但必须在 Phase 2（集合契约变更）之前决定。**

本目录的步骤 3 要把 `ceval` 的 30 余个 `TExpr` 构造器逐个拆成
「求值子表达式前」与「子表达式回来之后」两半。**如果 interp 之后改吃 Core，
这份工作全部重做。**

~~**处理：步骤 3 冻结，等 R6 决议**（计划自己承诺在 Phase 2 之前给出）。~~
**处理（07-31 改）：步骤 3 不做**，见本节表头。
步骤 1（`unsafe_pure` 收归 std）与步骤 2（comptime allowlist）**不受影响，照做**——
它们改的是 checker 的一个判定和 `eval_java` 的一张表，与 `ceval` 的形状无关。

**还有一半 ARCH-06 是解决不了的**：计划 §1 定了「一般尾调**不做**，大栈代替」，
Phase 3 的 `pthread_attr_setstacksize` 就是 `-Xss512m` 在 native 上的延续。
也就是说「用户程序靠大栈跑深递归」从**债**变成了**决策**。
ARCH-06 能拿掉的只有「编译器的 comptime 求值器吃宿主栈」那一半。
这一点要写进 spec，不要让用户以为深递归以后会变好。

> **07-31 补两条实测**（[verdict](ceval-trampoline-verdict.md) §三、§五）：
> ①「用户程序靠大栈」这条决策的代价是可量的——编译成 jar 的 100,000 层非尾递归
> 要 `-Xss8m`，512m 给的是约 640 万帧余量；②Phase 3 的 `pthread_attr_setstacksize`
> **至今没落地**（`runtime/c/` 与 `nmain`/`cdriver`/`emitc` 全无栈尺寸设置），
> native 今天吃 OS 默认 8 MB，深输入的表现是 SIGSEGV 无消息。
> 「`-Xss512m` 在 native 上的延续」现在还只是计划里的一行字。

### 3.6 `'a'` 变 `Char` 与 Phase 6 撞同一批文件（LANG-04）

计划 Phase 6 要把 `java.lang.Character` / `Long.parseLong` 从 lexer/parser 里
纯 Dawn 化（已定 ASCII-only）。本目录 [nominal-types](nominal-types-design.md) 步骤 4
要改 `lexer.dawn` / `packages/json` / `fmt.dawn` 的**全部码点算术**。

同一批文件，两次「必须一次改完、否则半途状态难讲」的机械大改。

**处理：合并成一次，且 `Char` 先做。** 理由是纯 Dawn 的 `char_is_digit` 之类
写在 `Char` 上比写在 `Int` 上正确——先做 ASCII-only 的纯 Dawn 版再改类型，
等于把同一批函数签名改两遍。

nominal-types 的**步骤 1–3 是纯新增**（parser/checker/emit 支持 `type X = new T`），
不改任何现有代码，**不冻结**。只有步骤 4 冻结。

> 顺带核对过一条不构成撞车的：计划 §1 把 `Cursor` 从码点索引改成**字节偏移**并称
> 「观测透明」。`std/cursor.dawn` 的全部操作（`char`/`next`/`prev`/`slice`/`skip`/`find`）
> 都是按字符定义的，`Cursor` 也确实无法从 `Int` 铸造，所以这个说法成立。
> 代价在实现侧（`prev` 要回扫前导字节），不在语义侧。

### 3.7 LSP-01 的「不做」理由被作废

本目录写的是：

> **保留手写 UTF-8 decoder 作为 fallback**——留着它就还得维护它，
> 而它的全部价值是「JDK 不在」——JDK 一定在，Dawn 跑在 JVM 上。

Phase 6 要替换 17 个模块的 99 处 `use java`，`lsp.dawn` 在其中。
**native 上没有 `java.net.URI`。**

**处理：改法不变，理由改写。** JVM 侧那个手写 decoder 确实是错的（不校验
continuation byte、overlong、surrogate、超范围），该换成 JDK。
但「不留 fallback」的理由要从「JDK 一定在」改成「native 上另起一份，
不是把这个留着」——一个不校验的实现不该因为将来需要一个实现就免于被删。
已改，见 [lsp-robustness-design.md](lsp-robustness-design.md) §四。

LSP-02（file URI）同理，同一次改动。LSP-04（debounce）与计划无关，不受影响。

### 3.8 REL-02 从 nice-to-have 变成前置

计划 R4：

> 两个后端平权 ⇒ 每次 Emit-Change 要验两套。

本目录的 REL-02 正是「`Emit-Change` 绑定 target 与 digest」。
**没有它，Phase 3 之后 `Emit-Change:` 这行字说不清改的是哪个后端的输出。**

**处理：提到第 0 批的最前面**，与 TEST-01 并列。它本来被归在「可以立刻做、
不需要设计文档」里，现在它是 native 那条线的前置条件。

### 3.9 PKG-04 的 lock 只覆盖 JVM 那半

计划 §1：native 上 `[java-deps]`/coursier **直接报不支持**，拉包 shell 出去调 `curl`。

于是 `dawn.lock` 里的 `[[java-dep]]` 条目在 native 上是死条目。
反过来 **PKG-02 变重要了**——native 上没有 JDK 的 HTTP 栈和校验设施，
d1 canonical tree hash 是唯一的完整性手段。

**处理：不冻结，PKG-02 优先于 PKG-04。** 已写进
[package-integrity-design.md](package-integrity-design.md) §一。

## 四、反向：计划有、审查完全没看出来的

登记在这里，因为它们说明审查的覆盖有洞，下次同类工作要补：

- **D0（Eq/Hash trait 化）**。`==` 硬连线 `BEq`、hash 是自动派生的结构 `hashCode`，
  于是「任意值能不能比较/哈希」不是 trait 决定的。计划自己标它
  **「全线最高风险」**，而 76 条审查里**没有任何一条**提到它。
  这是审查最大的一个漏项——它检查了类型系统的表面（`unsafe_pure`、alias、Char），
  没有检查**内建操作与 trait 系统的关系**。
- **Perceus 与 `--rc=leak` 调试模式**。审查完全没有内存管理这个维度（因为 JVM 有 GC），
  而它是 native 上最大的正确性风险。
- **`use c` FFI 无反射**，以及由此 `checker.dawn` 可以从 `!io` 变纯。
  审查注意到了 `checker.dawn` 是 God module，没注意到它的效果签名是被 `jreflect` 逼出来的。
- **平台范围**（只 Linux x86-64，Windows 不在范围内）。审查的 CLI-02/CLI-03
  在修跨平台细节（classpath 分隔符、`readlink -f`），而计划把 Windows 划出去了。
  两者不冲突（那些修的是 JVM 侧），但优先级判断要相应下调。
- **「C 运行时无 oracle」这个风险类别**。审查的 TEST-01 说的是
  「差分会把旧 bug 固化成正确行为」，计划说的是「有一整层**根本没有可对拍的参照**」。
  后者更重，审查没有这个概念。

## 五、这份台账什么时候可以删

三个条件同时成立：

1. Phase 0 出口达成（Core IR 落地、零 Emit-Change），§3.1 与 §3.2 的登记兑现；
2. ~~R6 决议（interp 吃 Core 还是吃 TAST），§3.5 解冻~~ —— **已满足（07-31）**：
   R6 于 07-25 决议，§3.5 随之解冻并结账为「不做」；
3. Phase 6 出口（native 固定点），§3.7 的第二份 decoder 有了着落。

在那之前，本目录任何一份文档动手前**先读这里**——它记的是「你要改的东西
另一条线也在改」，而那是返工的唯一来源。
