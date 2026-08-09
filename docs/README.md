# docs/ 索引

> 状态：**current** —— 全目录的分层索引与状态登记处。**每篇文档的权威状态在它自己的
> 文件头**；这张索引与文件头冲突时以文件头为准，并请顺手改这里。

`docs/` 下现有 83 篇文档 <!-- doc-check: doc-count -->，按时间叠加，混着**规范、调研、
设计方案、落地日志、复盘和运维说明**。读者无从判断哪几段还成立——`design.md` 说实现语言
是 Kotlin，`bootstrap.md` 说 LSP 还在 Kotlin，两者都是当时的事实、现在都不是。
这份索引把它们分层，并给每篇标状态。**篇数与「每篇都在索引里」这两件事都由
`scripts/doc-check.py` 核对**，所以上面那个数字不会像它的前任（长期停在 43）那样烂掉。

**状态取值**

| 状态 | 含义 |
|---|---|
| **normative** | 权威定义。实现与它冲突就是实现的 bug。只有一篇。 |
| **current** | 描述当前的架构或流程，可以照着做。 |
| **historical** | 当时的决策/调研/落地记录。**读作历史，不是现状**；结论可能已被后续推翻。 |

---

## 权威规范

| 文档 | 状态 | 说明 |
|---|---|---|
| [spec.md](spec.md) | **normative** | 语言的权威定义（词法、类型、效果、comptime、互操作、编译模型）。 |
| [spec.en.md](spec.en.md) | **normative** | 上面那篇的**英文译本**。改规范先改中文，再改这里；两者不脱节由 `doc-check.py` 的 transl 检查盯着。 |
| [grammar.ebnf](grammar.ebnf) | historical | 机器可读语法，**已落后于 parser**（2026-08-04 复核仍成立：缺 `use … as`、要求所有函数写 `-> type`、用未定义的 `UPPER_IDENT`、`. IDENT` 不覆盖 `Class.FIELD`）。以 spec.md 与 `selfhost/src/front/parser.dawn` 为准；可执行的那份期望是 `scripts/grammar-corpus/`（CI 门禁），文法的分叉现在以一个失败用例出现。SYN-02/SYN-03 已从**另一头**关掉——本文件写对了，是实现补上了它，逐条见文件头部。 |

## 当前全仓审查（v2）

| 文档 | 状态 | 说明 |
|---|---|---|
| [codebase-audit-v2.md](codebase-audit-v2.md) | current | v0.60 冻结基线 + `18fb3d6` 当前状态层；97 项为 60 fixed / 5 partial / 30 open / 2 retracted，原严重度、证据与 29 行 P1 索引不随后续处置重写。 |
| [codebase-audit-v2/00-methodology-and-retractions.md](codebase-audit-v2/00-methodology-and-retractions.md) | current | 基线、证据等级、严重度、fixed/retracted 边界，以及 HOLD/延后能力不进入自治 TODO 的口径。 |
| [codebase-audit-v2/01-syntax-and-formatting.md](codebase-audit-v2/01-syntax-and-formatting.md) | current | lexer、parser、formatter、pattern 与编辑器语法；SYN-04 guard 只记静态候选，SYN-17 是 D/P3 关键字预算设计项。 |
| [codebase-audit-v2/02-types-effects-and-semantics.md](codebase-audit-v2/02-types-effects-and-semantics.md) | current | 类型、效果、Cursor/Char 与 nominal abstraction；SEM-05/08 已撤回，SEM-09/10 延后，SEM-16 HOLD。 |
| [codebase-audit-v2/03-compiler-and-runtime-architecture.md](codebase-audit-v2/03-compiler-and-runtime-architecture.md) | current | checker/Core/comptime 与双后端；ARC-11 部分修复，ARC-09/10 按既有重开条件 HOLD。 |
| [codebase-audit-v2/04-cli-lsp-build-and-release.md](codebase-audit-v2/04-cli-lsp-build-and-release.md) | current | CLI、LSP、依赖与发布链；TOOL-05/06/08 已修，TOOL-14 因递归输入/fail-open 残余为 partial。 |
| [codebase-audit-v2/05-stdlib-and-packages.md](codebase-audit-v2/05-stdlib-and-packages.md) | current | std、inflate、JSON、Web 与 SHA-2；LIB-07 已修，LIB-18 clean truncation 仅为未验证静态候选。 |
| [codebase-audit-v2/06-docs-tests-and-governance.md](codebase-audit-v2/06-docs-tests-and-governance.md) | current | normative spec、文档状态、examples/packages/contract gates 与仓库治理。 |

## 当前架构与流程

| 文档 | 状态 | 说明 |
|---|---|---|
| [bootstrap.md](bootstrap.md) | current | 自举链：种子 → A → B → C、固定点、种子推进协议。 |
| [bootstrap-input-manifest-design.md](bootstrap-input-manifest-design.md) | current | TOOL-14 的 project-only Producer、已落地的递归 launcher discovery，以及尚未落地的 framed v2 stamp/可恢复 commit-marker 边界。 |
| [package-design.md](package-design.md) | current | 源码包（`[deps]`）与 Maven 依赖（`[java-deps]`）的清单与解析。 |
| [runtime-intrinsics-design.md](runtime-intrinsics-design.md) | current | 运行时 intrinsic 契约——每个 primitive 归哪个运行时模块。**表已从 `emit.dawn` 的 `(class, method)` 收成 `types.dawn` 的 `Rt`/`Intr`（文中的 `rt_intrinsic_target` 是旧名，已不存在）；§8 的三步 Move 表已被 [core-move2-design.md](core-move2-design.md) 更正**。 |
| [core-move2-design.md](core-move2-design.md) | historical | 上面那张表里「Move 2 控制流/match」的**结账盘点**：主体已随 Core IR Phase 0 落地；残余 `CSProtect`（error-model 的 C2）已于 2026-07-31 裁决**关档不做**。`bracket` + `with` + 当时的 `fn` 尾闭包随 v0.39.0/v0.40.0 发布；尾闭包拼写后来由 #206 尾块取代。 |
| [trait.md](trait.md) | current | trait/impl/derive 与 `Ord`。§落地记录里 Float 比较那段已被实现取代（见文内标注）。 |
| [tutorial.md](tutorial.md) | current | 上手教程，**英文正本**。标 `dawn run` 的代码块由 `scripts/doc-check.py` 真编真跑并核对 `output`。 |
| [tutorial.zh-CN.md](tutorial.zh-CN.md) | current | 上面那篇的**中文译本**。改教程先改英文，再改这里；两者不脱节由 `doc-check.py` 的 transl 检查盯着。 |
| [codebase-audit.md](codebase-audit.md) | historical | 2026-07-25 的全仓审查，76 条逐条带当时的处置结论；保留证据与排期，不作当前风险台账。 |
| [audit/README.md](audit/README.md) | historical | 上面那份旧审查遗留待办的历史作业计划：十三份材料的索引、依赖、修复顺序与“不做”理由均保留；当前顺序看审查 v2。 |
| [audit/native-plan-overlap.md](audit/native-plan-overlap.md) | current | 上面那批待办与 native-backend-plan.md 的**撞车登记**：谁让位、谁冻结、谁要改写。动 `audit/` 里任何一份之前先读它。 |
| [native-backend-plan.md](native-backend-plan.md) | current | native 后端的分阶段计划（Phase −1 → 6）与落地日志。**Phase −1…6 全部完成**，Phase 6（native 自举）于 2026-07-30 达成（§14.23，提交 `83def2d`，`scripts/native-fixpoint.sh` 验 B==C + 裸目录 smoke）；重排后的 S0–S4 也已结清。仍开着的只有 `use c` FFI（推迟，见 B 线 K-B6）与 S5「std 收口」（[std-audit.md](std-audit.md)）。 |
| [native-driver-plan.md](native-driver-plan.md) | current | **B 线**：native 驱动补全 + 把后端契约摆到明面上——K-B 刀表、「5,373 行零 `use java`」的核对、以及那条最重要的更正：几条差分脚本的被测方原本写死 `./bin/dawn`，**接上线不会自动覆盖 native**（已由 `native-cli-diff.sh` 修掉）。**七刀已结**：K-B1–K-B5 与 K-B7 落地（逐刀带红演示与阴性对照），K-B6（`use c` FFI）明确推迟。 |
| [jvm-base-plan.md](jvm-base-plan.md) | current | **A 线**：收缩 JVM 后端的可信底座——V49（classfile major 61 → 49）可行性审计的结论与三个代价数、九条被推翻的预设、K-A 刀表。**已 done**：K-A0/K-A0.5/K-A1/K-A3/K-A5/K-A4/K-A6 与 K-A7 期 1/2/3 全部落地，K-A2 取消，`dawn/tool` 已退出 jar 与可信底座（`b66f1d7`）；K-A8.1/K-A8.2 把帧 oracle 装回来并升到 major 52（§5.10、§5.11），K-A8.3 把 52 买回来的接口静态方法登成语料与门禁（§5.12）——K-A 刀表至此全部结清。 |
| [perceus-design.md](perceus-design.md) | current | native 的内存管理（精确 RC + 复用分析）。五刀已全部落地，关账在其 §8；仍是该子系统的权威说明。 |
| [effects-soundness-design.md](effects-soundness-design.md) | current | #188 的修法：具名效果的两个 soundness 缺陷（标签轴对函数值不设防、减标签的人不是应答的人）与「B 极简」三刀——注解位禁标签、闭包创建点结算、`verify_effects` 整行核对。落地后 spec.md §6.5 以它为准。 |
| [native-failure-design.md](native-failure-design.md) | current | #193 的修法：native 失败运行时的三个 P1（ARC-03 消息截断 / ARC-04 嵌套覆盖 / ARC-05 恢复泄漏）实测是**两件事**——载荷所有权与「longjmp 不跑清理」。刀 1 载荷对象化 + 路线 A3（`-fexceptions` + cleanup + ForcedUnwind）；路线 B（Result ABI）不做，重开条件写在 §4.3。载荷契约随刀 2 进 spec.md §9.8.1。 |
| [named-args-design.md](named-args-design.md) | current | #207 的方案：具名实参推广到 `Sig` 支持的 callee + 默认参数（合成 `f$default$k` 零元纯函数）。四条用户终裁在其 §9：实参求值顺序改**写序**（本批唯一 Emit-Change）、单层名、默认值任意纯表达式、std 采用另批。 |
| [tail-block-design.md](tail-block-design.md) | current | #206 的方案：裸 `{ ... }` 尾块（Kotlin 式，含 `{ x => }` 参数头）落到既有 `attach_trailing`，区分机制 = 头部禁记录字面量的开关扩义（`ns`→`nb`）。用户终裁在其 §13：方案乙、guard 位不禁；期 2 的最终口径是 `fn` 不再属于表达式，尾块是唯一 trailing form。 |
| [match-arm-separators-design.md](match-arm-separators-design.md) | current | SYN-10 的定稿：match 臂只由物理换行或逗号分隔，尾逗号合法；删除 FIRST(pattern) 邻接，并以三类 delimiter-aware recovery 与绝对 grammar corpus 固定边界。 |
| [int-min-literal-design.md](int-min-literal-design.md) | current | SYN-08 的定稿：三进制共用无溢出 magnitude parser，仅直接一元负号消费精确 `2^63` marker；双后端与生成 C 契约固定 `INT64_MIN`。 |
| [lsp-framing-design.md](lsp-framing-design.md) | current | TOOL-07 的定稿：共享层在 stdin read 前限制 8 KiB header/64 MiB body，严格解析重复 `Content-Length`，并把不可重同步的 framing failure 固定为一次错误后关读循环。 |
| [source-plan-design.md](source-plan-design.md) | current | TOOL-10 的定稿及 2026-08-09 架构修订：独立无 Java 的 `compiler-plan/` 先形成唯一最终图，再从选中 `PkgR` 收 Java 坐标。 |
| [lsp-workspace-design.md](lsp-workspace-design.md) | current | TOOL-05/06 的已实现设计：canonical `(project, source_root)` workspace、captured `ProjectPlan`、共享 `Program`/诊断与 target-scoped `JsigLease`。 |
| [delete-outcome-design.md](delete-outcome-design.md) | current | LIB-07 的定稿：`io.delete` 以 `Deleted` / `NotFound` / `Err` 区分成功、缺失与 host refusal，底层仍保留 Bool intrinsic ABI。 |
| [cli-arity-design.md](cli-arity-design.md) | current | TOOL-04 的定稿契约：`check`/`fmt` 为 1..N，`test`/`doc` 的 selector 互斥，`build`/`emitc` 恰一个 target；两端保留独立 argv parser，由绝对 exit/stdout/stderr oracle 防止共谋假绿。 |
| [run-argv-boundary-design.md](run-argv-boundary-design.md) | current | TOOL-03 的定稿契约：`run` 只在 target 前解析 compiler option，以 `--` 开启逐字透传的 program argv；JVM 一次顺序解析且 dependency re-exec 保留原始 rest，两端独立 parser 由绝对 oracle 约束。 |
| [std-audit.md](std-audit.md) | current | std 的交付方式、优雅性判据与欠账台账（S5）。骨架五条已做掉大半，仍在册的欠账逐条写在它的状态行里。 |
| [stdlib-impl-notes.md](stdlib-impl-notes.md) | current | std 里几个函数**为什么长成这样**：被否掉的写法、实测数字、逼出今天形状的两后端分歧。std 的 `##` 注释只留契约，这些话从那里搬来。 |

## 审查待办的设计方案（`docs/audit/`）

2026-07-25 那次全仓审查剩下的待办，动码前的方案。索引、顺序与逐份状态见
[audit/README.md](audit/README.md)，**与 native 那条线的撞车见
[audit/native-plan-overlap.md](audit/native-plan-overlap.md)**。

这一节曾整体标着「全部 proposed」，**今天只剩一份还名副其实**：

| 文档 | 覆盖 | 状态 |
|---|---|---|
| [audit/web-api-v2-design.md](audit/web-api-v2-design.md) | WEB-03/04/06/07/09/10 | **proposed，未动**——只发了 WEB-09 的不破坏半；破坏性 API 变更，先发 tag |
| [audit/lsp-robustness-design.md](audit/lsp-robustness-design.md) | LSP-01/02/04 | **均已落地**：LSP-01/02 于 07-30 完成，LSP-04 debounce 于 08-05 完成；本文保留历史方案与负控记录 |
| [audit/nominal-types-design.md](audit/nominal-types-design.md) | LANG-04/05 | 步 1–3 **驳回**（`opaque type` 已提供该机制）；**LANG-04 仍是活账** |
| [audit/module-access-design.md](audit/module-access-design.md) | LANG-06/07 | **已落地**（2026-07-30 当日全部发出） |
| [audit/package-integrity-design.md](audit/package-integrity-design.md) | PKG-02/04 | **已落地**（`dawn cache verify` + `dawn lock --check`） |
| [audit/application-syntax-design.md](audit/application-syntax-design.md) | SYN-02/03 | **已落地**（2026-07-31 结清） |
| [audit/purity-boundary-design.md](audit/purity-boundary-design.md) | LANG-01 P0 + ARCH-06 | **已关账**：步 1 落地、步 2 被吞并、步 3 裁决不做 |
| [audit/error-model-design.md](audit/error-model-design.md) | ERR-02/03 + LANG-02 | A/B **已落地**，**C2 关档不做** |
| [audit/lowered-ir-design.md](audit/lowered-ir-design.md) | ARCH-01/02/03/04 | **降级为 Core IR 的补充材料**，不是任何一条待办的方案 |
| [audit/ceval-trampoline-verdict.md](audit/ceval-trampoline-verdict.md) | purity-boundary 步 3 的收益重估 | **裁决：不做**（07-31，翻案条件写在文里） |
| [audit/re-audit-2026-07-30.md](audit/re-audit-2026-07-30.md) | 第二轮复审 53 条发现 | current（发现记录），§六已 triage 并逐批消化 |
| [audit/re-audit-b-decisions.md](audit/re-audit-b-decisions.md) | 复审 B 批八条契约件 | **已裁决**（07-31，全部按建议），降为过程记录 |

（[arch-split-design.md](arch-split-design.md) 曾在此列，**2026-08-03 已落地**，
移到下一节。）

## 设计方案（已落地，作为特性的「为什么」）

[bytes-design.md](bytes-design.md) ·
[cast-interop.md](cast-interop.md) ·
[pure-ffi-design.md](pure-ffi-design.md) ·
[sourceview-design.md](sourceview-design.md) ·
[streaming-design.md](streaming-design.md) ·
[streaming-response-design.md](streaming-response-design.md) ·
[unwrap-design.md](unwrap-design.md) ·
[varargs-design.md](varargs-design.md) ·
[builtins-to-stdlib.md](builtins-to-stdlib.md) ·
[stdlib-naming.md](stdlib-naming.md) ·
[trait-v2-design.md](trait-v2-design.md)（八刀，`==` 走 `Eq` bound）·
[semantics-closure-design.md](semantics-closure-design.md)（S1：把一件事的 N 份定义收成一份）·
[assoc-types-design.md](assoc-types-design.md)（`type Item` 与投影 `T.Item`，两刀）·
[operator-traits-design.md](operator-traits-design.md)（`[]` 背后的 `Index`）·
[prelude-namespace-design.md](prelude-namespace-design.md)（函数命名空间的「一道门」）·
[effects-design.md](effects-design.md)（用户具名效果 + `with handle`，尾恢复档）·
[core-move2-design.md](core-move2-design.md)（Move 2 的结账与 `CSProtect` 关档）

状态一律 historical：写作当时的取舍成立，文中的行数、性能数字和「现在是什么样」
的描述**不保证仍然准确**。特性本身的权威描述在 spec.md。

**例外，仍值得读**：[arch-split-design.md](arch-split-design.md)
（ARCH-01 拆 `Cx` + ARCH-02 拆 `Gen`，**取代 lowered-ir-design.md §3.2 的六组件方案**；
2026-08-03 十二刀落地）。它不只是「为什么这么拆」，还是一份**怎么在没有行为门禁的
地方证明重构是恒等变换**的作业记录：归一化全量 Core 不变量、五语料逐字节对拍、
以及 §5.4 那条「我们以为有门禁看着、实测两个都看不见」的自我更正。
下一次动编译器大结构之前读它的 §5 与 §10。

## 调研

| 文档 | 说明 |
|---|---|
| [seq6-research.md](seq6-research.md) | 字符串/序列性能，`Cursor` 的由来。CONTRIBUTING 拿它当「调研推翻原前提也是成果」的范例。 |
| [equality-survey.md](equality-survey.md) | 七门语言怎么设计相等。结论已由 trait v2 兑现（`==` 走 `Eq` bound）。 |
| [collections-dejava-research.md](collections-dejava-research.md) | 集合去 Java 化的 A/B/C 三案，推荐 C。**已落地**（S3，2026-07-27）：三个容器都是纯 Dawn。 |
| [llvm-backend-research.md](llvm-backend-research.md) | 第二后端**的调研**，读作历史——那个后端已经建成并自举了（native，Core IR → C，`scripts/native-fixpoint.sh` 验 B==C）。现状与计划看 [native-backend-plan.md](native-backend-plan.md)。 |

## 历史：里程碑与自举过程

[design.md](design.md)（M0–M4 的决策记录；**「实现语言 = Kotlin」等条目已过期**，见文首状态标注）·
[design.en.md](design.en.md)（上面那篇的英文译本，中文是正本）·
[selfhost-gaps.md](selfhost-gaps.md) ·
[selfhost-ast.md](selfhost-ast.md) ·
[selfhost-checker.md](selfhost-checker.md) ·
[selfhost-codegen.md](selfhost-codegen.md) ·
[m6.md](history/m6.md) ·
[m6-retro.md](history/m6-retro.md) ·
[m7-progress.md](history/m7-progress.md) ·
[m8-selfhost-only.md](history/m8-selfhost-only.md)（淘汰 Kotlin 实现的决策与落地）

这一层全部 historical。指向 `compiler/` 的链接已改为 `kotlin-final` tag 上的
GitHub URL——那套实现不在 main。

---

## DOC-10 的三件事：都已落地

1. ✅ 分类索引（本文）。
2. ✅ 每篇自带状态——**换了形状落地**：不是 YAML front matter（站点渲染器会把它当正文
   印出来），而是 H1 下面一行 `> 状态：…`，由 `scripts/doc-check.py` 的 status 检查强制。
   「适用版本」只有 spec.md 需要，它带 `<!-- doc-check: version -->` 标记，版本号从
   `selfhost/src/version.dawn` 读，不由人抄。
3. ✅ 里程碑记录已在 `docs/history/`（m6 / m6-retro / m7-progress / m8-selfhost-only）。

一条经验留在这儿：**状态行会烂，而且是成批地烂**——写文档的人落地后改正文、很少回头
改文件头那一行。2026-08-04 全目录过了一遍，改掉的多数不是「写错了」，是「写对过」。
所以凡是能交给机器的都交出去了（篇数、索引覆盖、状态行的存在、版本号），
剩下「状态行说的是不是真话」没有机器能判，只能靠下一次人工复核。

---

## 这些文档是被检查的（TEST-04）

`scripts/doc-check.py`（CI 门禁「documentation checks」）检查这些：

- **状态**：每篇 `docs/` 下的文档在开头 12 行内有一行 `> 状态：…`（三档 + proposed，见上；
  英文文档写 `> Status: …`）。
  只查这一行**在不在**，查不了它**是不是真的**——假装能查会比这个缺口更糟。
- **链接**：每条相对链接指向真实存在的文件。
- **锚点**：每个 `#片段`（同文件与跨文件都算）对得上目标文档里的某个标题。
- **章节**：每个写明了目标文档的 `§N` 交叉引用，对得上那份文档里一个编号标题。
- **版本**：每处关于**当前工具链版本**的断言等于 `selfhost/src/version.dawn`。
- **篇数与覆盖**：本文开头那个「N 篇文档」等于 `docs/` 的真实篇数，且**每篇都被本文链到**。
  新写一份文档不进索引，门禁就红。
- **代码块**：每个标注为 ```` ```dawn run ```` / ```` ```dawn compile ```` 的块真的编得过、跑得起来。
- **围栏**：教程里每个 ```` ```dawn ```` 块标明自己是三种中的哪一种，每处豁免写明理由。
- **站点程序**：网站发布的每个整程序跑得起来，且输出与旁边记着的那份逐字节相同
  （`site/pages/` 与 `site/play-ui/samples/`，`*.dawn` 对 `*.out`）。
- **译本**：每篇译文登记了它所译原文的摘要，该摘要仍是原文当前的，且两边的代码围栏一一对齐。

块检查是 opt-in 的：规范里多数示例是片段（一个类型声明、三行 match），
逼它们都变成整模块会毁掉行文。**正确性重要的示例请自己标上** `run` 或 `compile`。
