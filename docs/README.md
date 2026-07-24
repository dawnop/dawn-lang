# docs/ 索引

29 篇文档按时间叠加，混着**规范、调研、设计方案、落地日志、复盘和运维说明**。
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
| [runtime-intrinsics-design.md](runtime-intrinsics-design.md) | current | `emit.dawn` 的 `rt_intrinsic_target` 契约——运行时 intrinsic 落到哪个类哪个方法。 |
| [trait.md](trait.md) | current | trait/impl/derive 与 `Ord`。§落地记录里 Float 比较那段已被实现取代（见文内标注）。 |
| [tutorial.md](tutorial.md) | current | 上手教程。代码块目前**人工维护**——机械校验随 Kotlin 侧 `TutorialTest` 一起归档了。 |
| [codebase-audit.md](codebase-audit.md) | current | 2026-07-25 的全仓审查，逐条带处置结论（已修 / 驳回 / 待办）。 |

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

## 调研

| 文档 | 说明 |
|---|---|
| [seq6-research.md](seq6-research.md) | 字符串/序列性能，`Cursor` 的由来。CONTRIBUTING 拿它当「调研推翻原前提也是成果」的范例。 |
| [collections-dejava-research.md](collections-dejava-research.md) | 集合去 Java 化的 A/B/C 三案，推荐 C。 |
| [llvm-backend-research.md](llvm-backend-research.md) | 第二后端调研。 |

## 历史：里程碑与自举过程

[design.md](design.md)（M0–M4 的决策记录；**「实现语言 = Kotlin」等条目已过期**，见文首状态标注）·
[selfhost-gaps.md](selfhost-gaps.md) ·
[selfhost-ast.md](selfhost-ast.md) ·
[selfhost-checker.md](selfhost-checker.md) ·
[selfhost-codegen.md](selfhost-codegen.md) ·
[m6.md](m6.md) ·
[m6-retro.md](m6-retro.md) ·
[m7-progress.md](m7-progress.md) ·
[m8-selfhost-only.md](m8-selfhost-only.md)（淘汰 Kotlin 实现的决策与落地）

这一层全部 historical。指向 `compiler/` 的链接已改为 `kotlin-final` tag 上的
GitHub URL——那套实现不在 main。

---

## 还没做的

codebase-audit.md 的 DOC-10 提了三件事，这里只落地了第一件：

1. ✅ 分类索引（本文）。
2. ⬜ 每篇加 front matter（状态、适用版本、superseded-by），而不是只在索引里标。
3. ⬜ 里程碑与提交哈希记录移进 `docs/history/`。

2 和 3 是 29 个文件的机械改动，跟本次审查修复放在一起会淹掉真正的改动，留待单独一提交。
