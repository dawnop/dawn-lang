# Dawn 代码库精细审查 v2

> 状态：**current** —— 基于 v0.60.0 / `86f6a0f63960` 的当前风险总纲；详细证据在 `docs/codebase-audit-v2/`。
>
> 审查方式：六专题并行只读审查 + 主审去重、静态复核和少量无副作用探针。
> 最高风险效果项按要求只记录静态可能性，未做动态利用验证。

## 1. 一句话结论

Dawn 已经具备共享 Core IR、JVM/native 双后端、自举固定点、纯 Dawn 集合与相当完整的门禁，旧审查中的两个 P0 和多项协议缺陷已经不再成立；但 v0.60.0 仍有 **1 个未动态验证的 P0 候选、29 个 P1、55 个 P2、12 个 P3**。最需要先处理的不是继续加语法，而是：效果 soundness、formatter/check 的破坏性默认行为、native failure runtime、Cursor 后端一致性、inflate/package trust boundary、LSP workspace model，以及 parser/checker 各阶段的重复事实源。

## 2. 基线与口径

- 最终基线：`86f6a0f6396084871b6d663fbf6092af66a3991a`，工具版本 v0.60.0。
- 审查从 `77ae6aebf6cc6c160a88160c0f2d664b06fd62b9` 开始；期间三次并发提交只推进版本/seed并重命名四个内部模块，没有改变本报告所评估的行为。最终引用已迁到新路径。
- 共记录 **97 项**：1 P0 候选、29 P1、55 P2、12 P3。设计争议只有在能指出组合性、无效状态或维护税时才进入 P2。
- `SEM-01`、native nested failure 与 unsafe boundary 没有做危险动态验证；其余少量 parser/formatter/check 探针只使用临时输入。
- 旧报告不直接继承严重度。本轮逐项对照当前源码；已修、已合理驳回和 historical EBNF 都列入撤回表。
- **基线后处置：** `SYN-14` 已由 #206 期 2 选择尾块方案收口；`SYN-18` 已由
  `cb2c061` 统一为紧凑 `a..b`；`SEM-11` 已分拆裁决为效果多态的 `bracket !e` 与
  固定 `!io` 的 `catch_fault`/`catch_panic`。下表的 97 项与严重度计数冻结为
  v0.60.0 审查基线，不因后续修复重写历史。

### 截至当前 main（`b16dcec`）的状态层

> 本节是冻结基线之后的**后续状态**，以 tag `v0.62.0`（`f2d4e79`）为已发布基点，
> 并计入其后收口的 TOOL-03/TOOL-04/TOOL-07/TOOL-10、SYN-08、SYN-10、九项低耦合治理，
> 以及截至 HEAD `b16dcec` 已独立验收的 SYN-15、ARC-06、LIB-05、LIB-09、GOV-05；
> 它不重写、重判或重新计数原审计的严重度、
> 证据与 P1 索引。下文仍按 v0.60.0 原文阅读。

| 状态 | 本层含义 |
|---|---|
| **已修** | 原发现指出的缺陷边界截至本层快照已关闭。 |
| **部分** | 已有实质修复，但明细所指出的至少一个边界在当前代码中仍成立，不能冒称关闭。 |
| **开放** | 截至本层快照没有足够证据宣告关闭；未改、只做设计或只做前置重构都归此类。 |

**已修（52）**

- 语法（10）：`SYN-01`、`SYN-02`、`SYN-06`–`SYN-08`、`SYN-10`、`SYN-14`、`SYN-15`、`SYN-18`、`SYN-19`。
- 语义（7）：`SEM-01`、`SEM-02`、`SEM-03`、`SEM-11`、`SEM-12`、`SEM-15`、`SEM-17`。
- 架构（4）：`ARC-03`–`ARC-06`。
- 工具链（13）：`TOOL-01`–`TOOL-04`、`TOOL-07`、`TOOL-09`、`TOOL-10`、`TOOL-11`、`TOOL-12`、
  `TOOL-14`、`TOOL-15`、`TOOL-16`、`TOOL-17`。
- 库（6）：`LIB-01`、`LIB-02`、`LIB-03`、`LIB-05`、`LIB-09`、`LIB-11`。
- 治理（12）：`GOV-01`–`GOV-03`、`GOV-05`–`GOV-13`。

**部分（3）**

- [`ARC-01`](codebase-audit-v2/03-compiler-and-runtime-architecture.md)：明细要求以 symbol ID 构图；当前 `checker.dawn` 的 `name_refs` 虽已排除词法绑定和模块别名，`EMethod` 仍会把非模块 receiver 的方法名记成本模块函数边，同名真实成员仍可能形成伪循环。
- [`ARC-02`](codebase-audit-v2/03-compiler-and-runtime-architecture.md)：明细要求覆盖 String、method 与 classfile 硬边界；当前 `ldc_str` 已分块、`class_bytes` 已接住 ASM failure，但 Core finalize 仍没有 span，超限 method/class 只能报 class/ASM method 文本而没有源码位置，仍须用户手工拆分。
- [`LIB-10`](codebase-audit-v2/05-stdlib-and-packages.md)：明细要求 CORS 包住最终 error response；当前 `with_cors` 已处理 handler 的 `Ok`/`Err`，但 `server.dawn` 的 dot-segment 400 与 body-limit 413 在 Request 和 middleware 之前产生，仍没有 CORS headers。

**开放（42）**

- 语法（9）：`SYN-03`、`SYN-04`、`SYN-05`、`SYN-09`、`SYN-11`、`SYN-12`、`SYN-13`、
  `SYN-16`、`SYN-17`。
- 语义（10）：`SEM-04`–`SEM-10`、`SEM-13`、`SEM-14`、`SEM-16`。
- 架构（6）：`ARC-07`–`ARC-12`。
- 工具链（4）：`TOOL-05`、`TOOL-06`、`TOOL-08`、`TOOL-13`。
- 库（12）：`LIB-04`、`LIB-06`、`LIB-07`、`LIB-08`、`LIB-12`、`LIB-13`、`LIB-14`、
  `LIB-15`、`LIB-16`、`LIB-17`、`LIB-18`、`LIB-19`。
- 治理（1）：`GOV-04`。

`74b3121` 当时只完成 #194 knife 1a：把 project dependency resolution 抽成一个 seam；
该提交本身既没有让 LSP/`doc` 加载 `[java-deps]`，也没有让 source 与 Java dependency
从同一最终图规划，因此当时未关闭 `TOOL-06` 或 `TOOL-10`。本次 SourcePlan 收口后，
source 与 Java dependency 已统一由最终选中图规划，`TOOL-10` 已关闭；LSP/`doc` 的
classpath 加载仍未完成，`TOOL-06` 保持开放。

代表性提交与验证来源（不取代明细中的原证据）：A1–A3 见 `60256bc`、`cd3cfc1`、
`a0d7800`、`cfb3bb8`、`dd51afc`、`a18b09a`、`77b0c07` 及 grammar/checker/package/dtoa
contracts 与 selfhost differential；#188 见 `2d6d61e`、`e154e38`、`50252e8` 及 checker
corpus；#193 见 `16f508c`、`0a3a4ba`、`3c9472c` 及 `scripts/spike-native/run.sh`、
`scripts/native-cli-diff.sh`；#206 与 release/bootstrap 收口见 `fde3203`、`2683638`、
`c4761ce`、`3a3ad4b`、`77374c9`、`086ea95` 及 `scripts/bootstrap-guards/run.sh`。

计数自检：**52 已修 + 3 部分 + 42 开放 = 97**。逐专题状态自检：语法 **10/0/9**、
语义 **7/0/10**、架构 **4/2/6**、工具链 **13/0/4**、库 **6/1/12**、治理 **12/0/1**
（顺序均为已修/部分/开放）；各专题仍分别覆盖 19 / 17 / 12 / 17 / 19 / 13 项，
与冻结总数一致且无重复、遗漏。

完整方法、严重度、证据等级和撤回项见[方法与旧结论处置](codebase-audit-v2/00-methodology-and-retractions.md)。

## 3. 结果总览

| 专题 | P0 候选 | P1 | P2 | P3 | 明细 |
|---|---:|---:|---:|---:|---|
| 语法、词法、formatter、编辑器 | 0 | 2 | 13 | 4 | [01](codebase-audit-v2/01-syntax-and-formatting.md) |
| 类型、trait、效果、语义 | 1 | 4 | 11 | 1 | [02](codebase-audit-v2/02-types-effects-and-semantics.md) |
| checker、Core、后端、runtime | 0 | 5 | 5 | 2 | [03](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| CLI、LSP、构建、包、自举、发布 | 0 | 12 | 5 | 0 | [04](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| std、inflate、JSON、Web、SHA | 0 | 5 | 13 | 1 | [05](codebase-audit-v2/05-stdlib-and-packages.md) |
| 文档、测试、治理 | 0 | 1 | 8 | 4 | [06](codebase-audit-v2/06-docs-tests-and-governance.md) |
| **总计** | **1** | **29** | **55** | **12** | **97** |

## 4. 最高风险项

### 4.1 P0 候选：先静态复核，再决定是否阻断 release

| ID | 问题 | 为什么重要 |
|---|---|---|
| `SEM-01` | 逃逸 closure 捕获创建点 handler evidence，但类型仍写原效果标签；另一处 pure handler 可能消掉标签后执行旧 handler 的 IO arm | 若静态推导成立，`pure` 无副作用保证不 sound。按要求未动态验证；详见[类型与效果](codebase-audit-v2/02-types-effects-and-semantics.md)。 |

建议维护者先做一个隔离的 compile/run probe，但不要先写 workaround。应先决定词法 handler 的类型语义：禁止 evidence 逃逸、把旧 handler arm effect 纳入 closure type，或改调用点 evidence。这个决定会影响后续所有 effect feature。

### 4.2 建议在下一次功能开发前修的 P1 组

1. **源码与 CI 基础安全**：`SYN-01` formatter 遇词法错误删 token，`TOOL-02` 还会覆盖任意直接文件；`TOOL-01` 的公开 `dawn check` 即使有诊断也 exit 0。
2. **已存在的合法程序被拒/误编**：`ARC-01` 用裸名字构返回推断依赖图，参数重名即可制造伪递归；`SEM-02` effect union 没有调用点 substitution；`SEM-03` opaque String 的自定义 Show 被 bypass。
3. **跨后端语义**：`SEM-04` Cursor 不绑定 String，JVM/native/comptime 使用三种 offset；`ARC-03/04/05` 的 native failure payload 会截断、被 nested release 覆盖并在恢复时泄漏引用。
4. **输入与供应链边界**：`LIB-01/02/03` 让 compression bomb 和 truncated ZIP/DEFLATE 在 guard 前或错误地通过；`TOOL-09/10/11` 让 cache、source graph、Java graph 和 artifact identity 依赖历史或 basename。
5. **工程工具一致性**：`TOOL-05/06/07` 使 LSP 多文件 snapshot、Java deps 与 frame limit 不可靠；`TOOL-14/15/16` 使 launcher stamp、seed std 与 checksum fail-open 没有形成闭合信任链。

## 5. 全部 P1 索引

| ID | 摘要 | 专题 |
|---|---|---|
| `SYN-01` | formatter 在词法失败时仍写回并删除未知字符 | [语法](codebase-audit-v2/01-syntax-and-formatting.md) |
| `SYN-02` | 插值的第二套扫描器不识别 Char/raw string | [语法](codebase-audit-v2/01-syntax-and-formatting.md) |
| `SEM-02` | effect union 调用点不实例化 | [语义](codebase-audit-v2/02-types-effects-and-semantics.md) |
| `SEM-03` | `to_string` 绕过 opaque String 自定义 `Show` | [语义](codebase-audit-v2/02-types-effects-and-semantics.md) |
| `SEM-04` | Cursor 无 owner，三执行模型 offset 不同 | [语义](codebase-audit-v2/02-types-effects-and-semantics.md) |
| `SEM-06` | Java `Object` 隐式窄化插入隐藏异常 | [语义](codebase-audit-v2/02-types-effects-and-semantics.md) |
| `ARC-01` | 返回推断把 local/parameter 名当顶层依赖 | [架构](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| `ARC-02` | JVM classfile limits 变 ASM/internal exception | [架构](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| `ARC-03` | native failure message 固定截断 512 bytes | [架构](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| `ARC-04` | nested cleanup 覆盖 native 全局 failure payload | [架构](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| `ARC-05` | longjmp 恢复路径泄漏丢弃 frame 的引用 | [架构](codebase-audit-v2/03-compiler-and-runtime-architecture.md) |
| `TOOL-01` | `dawn check` 有诊断仍 exit 0 | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-02` | `fmt` 可原地覆盖非 Dawn 文件 | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-05` | LSP 每文档维护独立工程 snapshot | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-06` | LSP/doc 不加载 `[java-deps]` | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-07` | LSP frame header/body 无界且后端转换不同 | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-09` | origin guard 给已有伪造 cache 写可信记录 | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-10` | source 与 Java dependency 由两张图规划 | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-11` | lock/vendor 以 jar basename 作为 identity | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-12` | JAR `Class-Path` 未 URI encode，换行不按 bytes | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-14` | launcher stamp 漏 transitive source/lock/recipe | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-15` | seed jar 有 hash，seed std 无 hash | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `TOOL-16` | 默认 seed 缺 checksum/tool 时 fail-open | [工具链](codebase-audit-v2/04-cli-lsp-build-and-release.md) |
| `LIB-01` | 解压限制在完整 materialize 后才检查 | [库](codebase-audit-v2/05-stdlib-and-packages.md) |
| `LIB-02` | ZIP central directory 损坏被当正常结束 | [库](codebase-audit-v2/05-stdlib-and-packages.md) |
| `LIB-03` | DEFLATE EOF 后补零并可能接受截断流 | [库](codebase-audit-v2/05-stdlib-and-packages.md) |
| `LIB-10` | CORS 不覆盖 4xx/5xx error response | [库](codebase-audit-v2/05-stdlib-and-packages.md) |
| `LIB-11` | Web request-body tempfile 有无 owner 路径 | [库](codebase-audit-v2/05-stdlib-and-packages.md) |
| `GOV-01` | dtoa 的独立 200k oracle 未进 CI | [治理](codebase-audit-v2/06-docs-tests-and-governance.md) |

## 6. 语言设计建议

### 6.1 用一种结构表达一件事

- member access 不应由大小写在 parser 阶段提前分 field/method；application、pipe、formatter 应共享统一 postfix model。
- or-pattern 应是 `Pattern` 节点，不是 match-arm 外挂 list；`for` 应复用不可反驳 binding grammar。
- lambda 不应“普通位置禁 `fn`、尾调用位置只许 `fn`”；#206 已选择不与 curried
  application 冲突的 `{ ... }` 尾块作为唯一 trailing form，本条按期 2 收口。
- parser 的 builtin type/decl-start inventory、TextMate keyword inventory 与 spec 表格应生成或至少由 contract test 对齐。

### 6.2 让 effect system 先闭合再继续扩展

- 先裁决 `SEM-01` 的 lexical evidence/escaping closure 语义。
- 删除 effect substitution 双实现，补 union normalization。
- 让 trait method、associated type bound、barrier 与 private effect inference 能组合；否则具名 effect 只能存在于孤立的一阶函数。
- 对 public API 做 effective visibility；private effect/type/trait 不应泄露成调用方无法书写的 contract。

### 6.3 不让 representation 变成用户语义

- `Char` 不应因为底层是 Int 就默认显示 `97`；Cursor 也不能因为底层是不同后端的 offset 就跨 String 比较。
- `Unit`、`Never` 应完成类型系统闭合，而不是靠 direct-field 禁令或 `Unit` workaround。
- opaque type 的 Show、SHA Digest、HTTP Response、header 与 artifact identity 都应由类型/API 保证 invariant，不能靠调用者约定。

### 6.4 两后端一致性要覆盖失败与工具，不只覆盖正常 stdout

- failure payload 的 ownership、nested failure、message bytes、cleanup leak 必须成为 backend contract。
- JVM/native CLI 的 reject/exit/arity 需要共享 fixture；LSP frame overflow 的双后端负例已由 TOOL-07 收口。
- differential 不能替代 independent oracle；dtoa、ZIP/DEFLATE 与 grammar diagnostics 都需要外部或完整预期。

## 7. 架构建议

1. **阶段产物带 identity。** 用 `RegisteredImpl`、`LoweredFn` 等具名结构替代平行 List + index；所有 mismatch 在边界报 compiler invariant。
2. **symbol identity 分层。** nominal/effect/trait ID 与 local/typevar/temp ID 分开，避免前一模块的小改动重排后续全局产物。
3. **workspace/project 只有一份计划。** LSP live overlay、source dependency graph、Java classpath、lock 与 build inputs 从同一 project plan 派生。
4. **可恢复 failure 不再依赖裸 `longjmp` 丢帧。** 若继续使用 setjmp，必须有显式 cleanup/payload stack；否则采用 Result-style unwind ABI。
5. **大栈是临时策略，不是语言 ABI。** 512 MB stack 的裁决有历史依据，但应以 measured high-water 和 iterative pass 逐步下降。

## 8. 建议修复顺序

### A. 立即、小刀且高收益

- `SYN-01`、`TOOL-01`、`TOOL-02`：先阻止源码破坏与 CI 假绿。
- `ARC-01`、`SEM-02`、`SYN-02`：修合法程序拒绝和 effect/interpolation 明确错误。
- `LIB-02/03`、`TOOL-11/12/16`：输入完整性、artifact collision、manifest 与 seed fail-open。
- `GOV-01/02/06/07`：把已有 contract 真接进 gate，不必先重构 compiler。

### B. 下一次 breaking release

- Cursor owner + `Char` API/display；Unit/Never；public visibility；Java Object checked cast。
- or-pattern AST、general pipe、match-arm separator、parenthesized type、`for pattern`、尾闭包语法裁决。
- JSON structured error、query multimap、opaque Response/Header/Digest。

### C. 需要设计文档的结构改造

- escaping effect handler soundness；trait + named effects + associated bounds。
- native failure payload/cleanup redesign。
- workspace-level LSP + single dependency plan。
- stable IDs 与 typed stage products；逐步退出 512 MB stack。

## 9. 旧审查如何读

不要把 `docs/codebase-audit.md` 的“current”和 P0 table 当作当前状态。v2 已明确撤回：用户可达 `unsafe_pure`、无集合源码、无 Core IR、非一般调用、Char/LSP debounce/Web v2 未落地、JSON 大整数/非法输出、cast/catch/bracket 缺失等结论。Unicode 标识符、`!` 双义、Float Ord/Hash、historical EBNF 等争议也没有重新包装成问题。

逐条理由和仍保留的“已知债务”见[方法与撤回](codebase-audit-v2/00-methodology-and-retractions.md)。

## 10. 明细目录

- [00 — 方法、证据、严重度、旧结论撤回](codebase-audit-v2/00-methodology-and-retractions.md)
- [01 — 语法、词法、formatter、TextMate](codebase-audit-v2/01-syntax-and-formatting.md)
- [02 — 类型、trait、效果、语义](codebase-audit-v2/02-types-effects-and-semantics.md)
- [03 — checker、Core、后端、native runtime](codebase-audit-v2/03-compiler-and-runtime-architecture.md)
- [04 — CLI、LSP、依赖、构建、自举、发布](codebase-audit-v2/04-cli-lsp-build-and-release.md)
- [05 — std、inflate、JSON、Web、SHA-2](codebase-audit-v2/05-stdlib-and-packages.md)
- [06 — spec、文档、测试、CI、治理](codebase-audit-v2/06-docs-tests-and-governance.md)
