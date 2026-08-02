# 小型 lowered IR，以及靠它拆开 checker 与 emitter

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **ARCH-04（P2）**、**ARCH-01（P1）**、**ARCH-02（P1）**、
> 以及 **ARCH-03（P1）** 的「若真要第二后端」那一半。
>
> 状态：**整篇降级为补充材料，不是任何一条待办的方案。**
>
> - **§一–§二、§四–§六（LIR 本身）**：与 [`../native-backend-plan.md`](../native-backend-plan.md)
>   的 **Phase 0（Core IR）** 是独立写出来的两份方案，结论一致（一层 IR、不做 SSA、
>   验收是零 Emit-Change）。**以那份计划的 Phase 0 为准**——它的节点集更全（见 §三的表），
>   且它知道 native 后端要什么。Phase 0 已落地。
> - **§3.2/§3.3（`Cx`/`Gen` 拆分）**：曾是本文唯一没被那份计划覆盖的部分，
>   **已于 2026-08-03 被 [`../arch-split-design.md`](../arch-split-design.md) 复测取代**
>   ——六组件表判为不做，理由见该文 §6.1，摘要见本文 §3.2 的警示框。
> - **仍然有效的只剩 §1.3 的排序论证**（先做 IR 再拆 God module，反了会做两遍）。
>
> **本文的所有行数与字段数都停在 2026-07-25**，逐处已加复测标注；引用数字前先看标注。
> 撞车登记见 [native-plan-overlap.md](native-plan-overlap.md) §3.1、§3.2。

## 一、问题

### 1.1 TAST 同时是四样东西

`selfhost/src/tast.dawn` 定义的树现在承担：

1. **类型树**——checker 的输出，带类型与符号 id；
2. **lowered tree**——desugar 之后的形态（`XPropagate`、`XUnwrap`、`XApply` 都是降级产物）；
3. **Java ABI**——`TJavaCall` 直接携带 JVM 类名（`fqcn`）、descriptor 参数类
   （`param_cls`/`ret_cls`）、`is_static`/`is_ctor`、SAM 与 List bridge 信息；
4. **codegen 输入**——emit 直接吃它出 ASM。

一棵树承担四种角色的后果是：**任何一个新语义特性都要同时改 checker 和 emit**，
而两者之间没有可以单独验证的中间产物。

### 1.2 于是 checker 和 emitter 都成了单体

实测（`wc -l`，2026-07-25）：

| 文件 | 行数 | 状态记录字段数 |
|---|---:|---:|
| `checker.dawn` | 7,924 | `Cx` **46** |
| `emit.dawn` | 3,532 | `Gen` **31** |
| `codegen.dawn` | 2,529 | — |

`Cx` 的 46 个字段混着七类东西：名字与作用域（`scopes`/`syms`/`fns`/`std_fns`）、
ADT/alias/trait/impl（`adts`/`aliases`/`alias_resolving`/`traits`/`impl_table`/`local_impls`）、
类型变量与效果（`current_tparams`/`current_eff_vars`/`used_effects`/`eff_witness`/`dict_syms`）、
Java 反射（`java_classes`）、import/export（`module_aliases`/`module_fn_sigs`/
`imported_names`/`module_exports`/`moved`）、const/comptime（`consts`/`const_order`/
`all_const_names`/`const_cutoff`）、lambda/loop 控制（`lambda_stack`/`loop_stack`/`loop_jumps`）、
诊断与源位置（`diags`/`src_path`/`line_starts`/`reported_key_types`）。

`Gen` 的 31 个字段同时管 JVM 栈槽（`slots`/`next_slot`）、闭包与 SAM
（`pending_lambdas`/`pending_sam`/`lambda_ctr`/`sam_ctr`）、函数值桥与构造器桥
（`pending_fnval`/`pending_bi`/`pending_ctorb`/`emitted_*`）、trait witness、
常量字段（`consts`/`blocks`/`const_fields`/`const_by_key`）和控制流 label（`loop_stack`/`fn_start`）。

> **复测（2026-08-03，`86b1cec`）——上表与上面两段的字段名单都已过期，别照着它做事：**
>
> | 文件 | 行数 | 状态记录字段数 |
> |---|---:|---:|
> | `checker.dawn` | **11,308** | `Cx` **47** @ `:91-164` |
> | `emit.dawn` | **2,534** | `Gen` **21** @ `:92-128` |
> | `codegen.dawn` | **3,425** | —（全文零 `Gen` 引用） |
>
> `Cx` 的 `reported_key_types` **已不存在**（全 `selfhost/src/` 零命中，随 `check_key_type`
> 那条行走一起删掉，见 [`../semantics-closure-design.md`](../semantics-closure-design.md)）。
> `pending_lambdas`/`lambda_ctr`/`pending_fnval`/`pending_bi`/`pending_ctorb` 全仓已零命中；
> `emitted_*`/`fn_start` 还在，但在 `lower.dawn` 里，不再是 `Gen` 的字段；`Gen` 的 `loop_stack`
> 换成了 `cloops`（Core 给循环起了名字）。**lowering 搬进 Core 之后 `emit.dawn` 反而变短**
> ——本节「emitter 也成了单体」的论据，今天只剩 `checker.dawn` 那一半还成立。
> 现状与拆法以 [`../arch-split-design.md`](../arch-split-design.md) §1.1、§2.3、§2.4 为准。

审查里最尖锐的一句要原样记住：

> 不可变记录线程化只是把「一个可变大对象」变成「每步复制/更新一个不可变大对象」，
> 没有真正降低耦合。

对。不可变性在这里买到的是「不会有人从别处偷偷改它」，**不是**模块化。
46 个字段仍然被 7,900 行以任意组合读写（2026-08-03：**47 个字段、11,308 行**）。

### 1.3 为什么这份文档排在最前面

审查把 ARCH-01（拆 checker）、ARCH-02（拆 emitter）、ARCH-05（运行时逻辑
从手写 ASM 挪出去）分开列，但它们有同一个前提：**没有 IR，拆到哪儿都还是直连**。

- 拆完 checker，emit 仍然直接吃 TAST → 耦合只是换了个地方；
- 想给运行时逻辑做源码级单测，得先有一个「不是 ASM」的表示；
- 想接第二后端（ARCH-03），得先有一个不带 JVM descriptor 的调用节点。

先做 IR、再拆两边，顺序反了要做两遍。

## 二、复盘：当初拒绝 IR 是对的

`docs/design.md` 在 M0 阶段拒绝引入 IR，理由是编译器预算 6–8 千行、
多一层表示就多一层要维护的不变量。**在那个规模上这是对的**，不是失误。

变化的是前提：checker + emit 现在是 11,456 行，`design.md` 已经标注
「6–8 千行（Kotlin）」这条前提被推翻。原论证失效了，结论就该重新算。

**同样要记住的是原论证里仍然成立的那部分**：不要造大而全的 SSA。
审查自己也说了这个分寸——「不是立刻造『大而全 SSA』，而是增加一个小型 lowered IR」。
本文完全采纳。

## 三、方案：一层 `LIR`，八件事

新增 `selfhost/src/lir.dawn`。下表是**本文原来列的六样**与
[`../native-backend-plan.md`](../native-backend-plan.md) Phase 0 清单的**并集**——
两边各有对方没看见的东西，第 7、8 行是本文原来漏掉的，标了出处：

| # | 统一什么 | 现在的样子 | LIR 里的样子 |
|---|---|---|---|
| 1 | call | `XCallFn`/`XCallBuiltin`/`XCallDyn`/`XApply`/`XJava` 五种 | `LCall(target, args)`，`target` 是 `LTarget` 和类型 |
| 2 | 控制流 | `XIf`/`XMatch`/`TSWhile`/`TSFor` + label 在 emit 现算 | 显式 `LBlock` 列表 + `LJump`/`LBranch`，label 在 LIR 里就有名字 |
| 3 | match | emit 里的 instanceof 链 | 已经降级成 `LBranch` 链，emit 不再认识 pattern |
| 4 | closure | `pending_lambdas`/`PendingL` 在 `Gen` 里排队 | `LClosure(captures, body_ref)`，捕获列表是 LIR 的一部分 |
| 5 | trait witness | `WitRef`/`WForward`/`WConcrete` 混在表达式里 | `LDict` 显式参数，去虚化是 LIR→LIR 的一次改写 |
| 6 | FFI | `TJavaCall` 带 fqcn + descriptor + SAM + List bridge | `LForeign(capability_id, args)`，**不带任何 JVM 名字** |
| 7 | **装箱/擦除**（漏项） | `adapt_to`/`adapt_from`（`emit.dawn:328`）在**每个调用点**重算「槽是不是 TyVar」 | 物化成 `LBox`/`LUnbox` 节点，判定在 lower 时做一次 |
| 8 | **所有权**（漏项） | 不存在——JVM 有 GC，没人需要它 | dup/drop 节点 + owned/borrowed 参数模式，**JVM 后端当 no-op 忽略** |

第 6 条是 ARCH-03 的答案：JVM 类名与 descriptor 从 IR 里消失，
挪进后端的一张 capability 表（`emit.dawn` 现有的 `rt_intrinsic_target` 是这张表的雏形，
见 [runtime-intrinsics-design.md](../runtime-intrinsics-design.md)）。
`LForeign(capability_id, args)` 正好就是 `use c` 需要的接口形状。

第 7 条是那份计划称作「**Rank 1 最烂的耦合**」的东西，本文原来完全没看见。
它比其余几条更该进 IR：`adapt_to` 的判定依赖类型信息，而 emit 是所有阶段里
离类型最远的一个。

**第 8 条不是补一个节点，是改 IR 的形状。** 它来自计划里「直接上 Perceus」这个
决策：精确 RC 要求每个值的所有权状态在 IR 上可表达，而这个维度**必须从第一天就在**——
事后往一棵已经定型的树上加所有权，等于重做一遍。这也是「先提取 IR」在那套决策下
从可选变成必须的原因。JVM 后端把 dup/drop 当 no-op，因此本文的验收（输出逐字节不变）
仍然成立。

### 3.1 流水线变成

```
parse → check（出 TAST）→ lower（出 LIR）→ [opt: LIR→LIR 改写] → emit（LIR → ASM）
```

`lower` 是新的、独立的、**可以单独测试**的一遍。这是整件事最大的收益：
今天没有任何一个位置可以断言「desugar 的结果应该长这样」。

### 3.2 拆 checker（ARCH-01）

> **⚠ 本节与 §3.3 已被 [`../arch-split-design.md`](../arch-split-design.md) 取代（2026-08-03）。**
>
> 下面这张六组件表**判为不执行**，理由是那份文档 §6.1 的三条复测：
>
> 1. **收窄不了签名**——body 检查是一个整体，`check_fn` 家族五个入口的传递可达字段
>    几乎是全集，切成六份不会让任何一个函数少收一个字段。
> 2. **`DiagSink` 想要的漏斗已经存在**——`Cx.diags` 在 `checker.dawn` 里只有两处记录更新
>    （`cerr`/`cerr_h`，`cerr_o` 委托给它们）。把它做成子记录只换来字段数的算术减法，
>    却要改掉每一个 `cerr` 调用点。
> 3. **表本身已经烂了**——`reported_key_types` 已随 `check_key_type` 那条行走一起删除
>    （全 `selfhost/src/` 零命中）；而 `src_path` 被划进 `DiagSink` 是误判，它与
>    `local_traits` 的共现更紧（孤儿规则报错要说清 impl 在哪个文件），**是身份不是输出**。
>
> 取代它的形状：**模块拆到位、记录只切两刀**（`Frame`、`GenCtx`）。理由是 Dawn 里
> 「拆文件」和「拆状态」不是同一件事——模块拆分对调用点零代价，记录拆分每个写点加一层。
>
> 本节保留原文，作为「一个看起来正确、复测之后不成立的方案」的记录。
> §1.3 的排序论证不受影响，仍然有效。

> **这一节和下一节是本文唯一没有被 native 计划覆盖的部分。** 那份计划的 Phase 0
> 只做「抽出 Core IR」，`Cx` 与 `Gen` 原样留着（写这段时是 46 / 31 字段，
> 今天是 **47 / 21**）；而它的 Phase 5 还要往 checker 里加 `use c` 的解析面——
> `Cx` 只会更大。所以拆 God module 仍然是本目录的事，
> **排在 Phase 0 之后、Phase 5 之前**。

有了 LIR，checker 的输出边界变窄了（它只需要产出 TAST，不再需要为 emit 准备信息），
`Cx` 才拆得动。按审查的六分法：

| 组件 | 从 `Cx` 拿走 |
|---|---|
| `SymEnv` | `scopes` `syms` `next_id` `fns` `std_fns` |
| `TypeEnv` | `adts` `adts_by_name` `aliases` `alias_resolved` `alias_resolving` `ctors_by_name` `current_tparams` |
| `EffEnv` | `used_effects` `eff_witness` `current_eff_vars` |
| `TraitEnv` | `traits` `traits_by_name` `local_traits` `local_impls` `impl_table` `dict_syms` |
| `JavaResolver` | `java_classes` |
| `DiagSink` | `diags` `src_path` `line_starts` |

剩下的（import/export、const/comptime、lambda/loop）留在一个明显更小的 `Cx` 里。

**分批做，每批能独立验证**：一次拿走一个组件，跑全量 + 差分。
一次性的几千行机械改写没人能评审。

### 3.3 拆 emitter（ARCH-02）

同理，且更简单——LIR 已经把 label、闭包捕获、witness 显式化了，
`Gen` 里那些 `pending_*` 队列大部分会直接消失（它们存在的原因就是
「emit 一边走树一边发现还需要生成别的东西」）。

> **这一句被证实了**（2026-08-03）：Core IR 落地后 `Gen` 从 31 字段降到 **21**，
> `pending_lambdas`/`lambda_ctr`/`pending_fnval`/`pending_bi`/`pending_ctorb`
> 全部消失，`emit.dawn` 从 3,532 行降到 **2,534** 行。
> **但由此推不出 ARCH-02 已经解决**：真实盘子是 `codegen.dawn` 3,425 + `emit.dawn` 2,534
> = 5,959 行，其中 `codegen.dawn` 那 3,425 行**一次都没提到 `Gen`**——它是另一种病
> （一个模块里塞了三块互不相干的字节码写手），拆法见
> [`../arch-split-design.md`](../arch-split-design.md) §2.2。

## 四、为什么不顺手把 X 也改了

- **不做优化**。LIR 的第一版**不带任何优化 pass**。它的价值是分层与可测性，
  加优化会让「输出应该逐字节不变」这条验收失效，而那是这次改造唯一的安全网。
- **不动 `rt_intrinsic_target` 的内容**，只动它的位置（从 emit 的一张表变成
  后端 capability 表）。内容正在被去 Java 化那条线改
  （[collections-dejava-research.md](../collections-dejava-research.md)），两边不要同时动。
- **不顺手接第二后端**。本文让第二后端**变得可能**，不实现它。

## 五、验收：输出必须逐字节不变

这是整个改造的安全网，也是它可行的原因：

- `scripts/selfhost-fixpoint.sh`：B == C 必须成立；
- `scripts/selfhost-prev-diff.sh`：emit 语料**不允许有任何字节差异**，
  **不接受 `Emit-Change:` 豁免**——这次改造的定义就是「结构变、输出不变」。
  一旦出现差异，说明 lower 改变了语义，是 bug 不是变更。

分批落地时每批都要过这两关。

## 六、不做的（记录理由）

- **SSA / phi 节点**。`design.md` 拒绝 IR 的原论证里，「多一层表示就多一层不变量」
  这半仍然成立。SSA 的收益全在优化上，而本文明确不做优化。
- **多层 IR（HIR/MIR/LIR）**。一层就能达成分层与可测性。多一层就多一份
  「两层之间是否等价」的验证义务，而现在连一层都还没有。
- **把 TAST 删掉**。checker 仍然需要一棵带类型的树来做类型推断与诊断；
  LIR 是它之后的一遍，不是它的替代。
- **趁机改 `Cx` 的不可变记录风格**。审查批评的是「大对象」不是「不可变」。
  拆小之后不可变线程化就变成优点了——小记录复制便宜，且效果显然。
- **先拆 checker 再做 IR**。见 §1.3。这条要写在这里，因为它看起来是更小的一步，
  而更小的一步在这里是错的。

## 七、落地点

| 阶段 | 文件 | 验收 | 归属 |
|---|---|---|---|
| A | 新增 `selfhost/src/lir.dawn`（类型定义） | 编译通过 | native 计划 Phase 0 |
| B | 新增 `lower.dawn`：TAST → LIR，先只覆盖 call 与控制流 | lower 的内联 test | 同上 |
| C | `emit.dawn` 改吃 LIR（call/控制流部分） | fixpoint + prev-diff **零差异** | 同上 |
| D | 依次搬 match、装箱/擦除、closure、trait witness、FFI、所有权 | 每步 fixpoint + prev-diff 零差异 | 同上 |
| ~~E~~ | ~~拆 `Cx` 六组件（ARCH-01），一次一个~~ | ~~每步全量 + 差分~~ | **已被 [`../arch-split-design.md`](../arch-split-design.md) 取代**（六组件判为不做，见 §3.2 的警示框） |
| ~~F~~ | ~~拆 `Gen`（ARCH-02）~~ | ~~同上~~ | 同上——`Gen` 改为**二分**（只读 `GenCtx` + 可变 `Gen`），且主刀在 `codegen.dawn` 而非 `Gen` |

**阶段 A–D 已让位给 native 计划的 Phase 0**，本文不再是它们的方案，只是补充材料
（§3 表的第 7、8 行是补给它的）。**E、F 已让位给
[`../arch-split-design.md`](../arch-split-design.md)**（2026-08-03，任务 #88），
那里把它们重排成十一刀、每刀单独可证。至此本文**整篇**是补充材料，
不再是任何一条待办的方案。
