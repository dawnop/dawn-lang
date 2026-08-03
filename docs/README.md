# docs/ 索引

43 篇文档按时间叠加，混着**规范、调研、设计方案、落地日志、复盘和运维说明**。
读者无从判断哪几段还成立——`design.md` 说实现语言是 Kotlin，`bootstrap.md` 说 LSP
还在 Kotlin，两者都是当时的事实、现在都不是。这份索引把它们分层，并给每篇标状态。

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
| [grammar.ebnf](grammar.ebnf) | historical | 机器可读语法，**已落后于 parser**，见 codebase-audit.md 的 SYN-02/03/04。以 spec.md 与 `selfhost/src/parser.dawn` 为准。 |

## 当前架构与流程

| 文档 | 状态 | 说明 |
|---|---|---|
| [bootstrap.md](bootstrap.md) | current | 自举链：种子 → A → B → C、固定点、种子推进协议。 |
| [package-design.md](package-design.md) | current | 源码包（`[deps]`）与 Maven 依赖（`[java-deps]`）的清单与解析。 |
| [runtime-intrinsics-design.md](runtime-intrinsics-design.md) | current | 运行时 intrinsic 契约——每个 primitive 归哪个运行时模块。**表已从 `emit.dawn` 的 `(class, method)` 收成 `types.dawn` 的 `Rt`/`Intr`（文中的 `rt_intrinsic_target` 是旧名，已不存在）；§8 的三步 Move 表已被 [core-move2-design.md](core-move2-design.md) 更正**。 |
| [core-move2-design.md](core-move2-design.md) | current | 上面那张表里「Move 2 控制流/match」的**结账盘点**：主体已随 Core IR Phase 0 落地，残余只剩 `CSProtect`（error-model 的 C2），并论证它多半不必被建出来。 |
| [trait.md](trait.md) | current | trait/impl/derive 与 `Ord`。§落地记录里 Float 比较那段已被实现取代（见文内标注）。 |
| [tutorial.md](tutorial.md) | current | 上手教程。代码块目前**人工维护**——机械校验随 Kotlin 侧 `TutorialTest` 一起归档了。 |
| [codebase-audit.md](codebase-audit.md) | current | 2026-07-25 的全仓审查，76 条逐条带处置结论（已修 / 驳回 / 待办）。 |
| [audit/README.md](audit/README.md) | current | 上面那份审查剩下 28 条待办的**作业计划**：九份设计文档的索引 + 修复顺序。 |
| [audit/native-plan-overlap.md](audit/native-plan-overlap.md) | current | 上面那批待办与 native-backend-plan.md 的**撞车登记**：谁让位、谁冻结、谁要改写。动 `audit/` 里任何一份之前先读它。 |
| [native-backend-plan.md](native-backend-plan.md) | current | native 后端的分阶段计划（Phase −1 → 6）与决策总表。**Phase 6（native 自举）已于 2026-07-30 达成**（§14.23，`scripts/native-fixpoint.sh` B==C），后面的 S 批仍在走。 |
| [native-driver-plan.md](native-driver-plan.md) | current | **B 线**：native 驱动补全 + 把后端契约摆到明面上——K-B 刀表、「5,373 行零 `use java`」的核对、以及那条最重要的更正：`selfhost-fmt-diff.sh`/`selfhost-run-diff.sh`/`selfhost-lsp-diff.sh` 的被测方全是写死的 `./bin/dawn`，**接上线不会自动覆盖 native**。K-B1/K-B2 已落地，含三组红演示与阴性对照。 |
| [jvm-base-plan.md](jvm-base-plan.md) | proposed | **A 线**：收缩 JVM 后端的可信底座——三个没有主干源码的 vendored 包、V49（classfile major 61 → 49）可行性审计的结论与三个代价数、九条被推翻的预设、K-A0…K-A6 刀表。K-A0/K-A0.5 已落地。 |

## 待办的设计方案（`docs/audit/`，全部 proposed）

审查剩下的待办，动码前的方案。索引与顺序见 [audit/README.md](audit/README.md)，
**与 native 那条线的撞车见 [audit/native-plan-overlap.md](audit/native-plan-overlap.md)**——
下面标「冻结」的部分在那份台账里写明了等什么。

[audit/purity-boundary-design.md](audit/purity-boundary-design.md)（LANG-01 P0 + ARCH-06，步 3 冻结）·
[audit/lowered-ir-design.md](audit/lowered-ir-design.md)（ARCH-01/02/03/04，**已降级为 Core IR 的补充材料**）·
[audit/error-model-design.md](audit/error-model-design.md)（ERR-02/03 + LANG-02，A/B 已落地，**C2 关档不做**）·
[audit/application-syntax-design.md](audit/application-syntax-design.md)（SYN-02/03）·
[audit/nominal-types-design.md](audit/nominal-types-design.md)（LANG-04/05，步 4 冻结）·
[audit/module-access-design.md](audit/module-access-design.md)（LANG-06/07）·
[audit/lsp-robustness-design.md](audit/lsp-robustness-design.md)（LSP-01/02/04）·
[audit/package-integrity-design.md](audit/package-integrity-design.md)（PKG-02/04）·
[audit/web-api-v2-design.md](audit/web-api-v2-design.md)（WEB-03/04/06/07/09/10）

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
[stdlib-naming.md](stdlib-naming.md)

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
| [collections-dejava-research.md](collections-dejava-research.md) | 集合去 Java 化的 A/B/C 三案，推荐 C。**已落地**（S3，2026-07-27）：三个容器都是纯 Dawn。 |
| [llvm-backend-research.md](llvm-backend-research.md) | 第二后端**的调研**，读作历史——那个后端已经建成并自举了（native，Core IR → C，`scripts/native-fixpoint.sh` 验 B==C）。现状与计划看 [native-backend-plan.md](native-backend-plan.md)。 |

## 历史：里程碑与自举过程

[design.md](design.md)（M0–M4 的决策记录；**「实现语言 = Kotlin」等条目已过期**，见文首状态标注）·
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

## 还没做的

codebase-audit.md 的 DOC-10 提了三件事，这里只落地了第一件：

1. ✅ 分类索引（本文）。
2. ⬜ 每篇加 front matter（状态、适用版本、superseded-by），而不是只在索引里标。
3. ⬜ 里程碑与提交哈希记录移进 `docs/history/`。

2 和 3 是 30 余个文件的机械改动，跟本次审查修复放在一起会淹掉真正的改动，留待单独一提交。

---

## 这些文档是被检查的（TEST-04）

`scripts/doc-check.py`（CI 门禁「documentation checks」）检查三件事：

- 每篇 `docs/` 下的文档在开头 12 行内声明 `> 状态：…`（三档 + proposed，见上）；
- 每条相对链接指向真实存在的文件；
- 每个同文件 `#锚点` 对得上某个标题；
- 每个标注为 ```` ```dawn run ```` / ```` ```dawn compile ```` 的代码块真的编得过、跑得起来。

块检查是 opt-in 的：规范里多数示例是片段（一个类型声明、三行 match），
逼它们都变成整模块会毁掉行文。**正确性重要的示例请自己标上** `run` 或 `compile`。
