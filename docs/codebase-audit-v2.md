# Dawn 代码库精细审查 v2

> 状态：**current** —— 保留 v0.60.0 / `86f6a0f63960` 的冻结审查基线；本文件的
> “机器权威的当前四状态层”是 98 项 finding 处置的唯一当前状态源，详细证据在
> `docs/codebase-audit-v2/`。
>
> 审查方式：六专题并行只读审查 + 主审去重、静态复核和少量无副作用探针。
> 最高风险效果项按要求只记录静态可能性，未做动态利用验证。

## 1. 一句话结论

Dawn 已经具备共享 Core IR、JVM/native 双后端、自举固定点、纯 Dawn 集合与相当完整的门禁，旧审查中的两个 P0 和多项协议缺陷已经不再成立；v0.60.0 冻结基线记录 **1 个未动态验证的 P0 候选、29 个 P1、55 个 P2、12 个 P3**，该严重度表不随后续处置重写。98 项 finding 的当前处置只读 §2 的机器权威四状态层；TOOL-05/06 已随共享 LSP workspace 与 target-scoped Java classpath 关闭，GOV-04 已由单一状态源与行为负控关闭，TOOL-14 已随完整 v2 launcher generation 合同关闭，当前 P1 优先级是两项 partial 的边界收口，以及仍需维护者裁决的 Cursor 契约。

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

### 冻结后的历史状态层（截至 `76491bb`）

> 本节是曾经发布的三状态快照，保留给 append-only 证据链与现有 `doc-check` 的冻结分区
> 自检；**它不是当前状态**。它以 tag `v0.62.0`（`f2d4e79`）为已发布基点，
> 并计入其后收口的 TOOL-03/TOOL-04/TOOL-07/TOOL-10、SYN-08、SYN-10、九项低耦合治理，
> 以及截至 HEAD `76491bb` 已独立验收的 SYN-03、SYN-15、ARC-06、LIB-04、LIB-05、LIB-09、GOV-05；
> 它不重写、重判或重新计数原审计的严重度、
> 证据与 P1 索引。下文仍按 v0.60.0 原文阅读。

| 状态 | 本层含义 |
|---|---|
| **已修** | 原发现指出的缺陷边界截至本层快照已关闭。 |
| **部分** | 已有实质修复，但明细所指出的至少一个边界在当前代码中仍成立，不能冒称关闭。 |
| **开放** | 截至本层快照没有足够证据宣告关闭；未改、只做设计或只做前置重构都归此类。 |

**已修（54）**

- 语法（11）：`SYN-01`–`SYN-03`、`SYN-06`–`SYN-08`、`SYN-10`、`SYN-14`、`SYN-15`、`SYN-18`、`SYN-19`。
- 语义（7）：`SEM-01`、`SEM-02`、`SEM-03`、`SEM-11`、`SEM-12`、`SEM-15`、`SEM-17`。
- 架构（4）：`ARC-03`–`ARC-06`。
- 工具链（13）：`TOOL-01`–`TOOL-04`、`TOOL-07`、`TOOL-09`、`TOOL-10`、`TOOL-11`、`TOOL-12`、
  `TOOL-14`、`TOOL-15`、`TOOL-16`、`TOOL-17`。
- 库（7）：`LIB-01`–`LIB-05`、`LIB-09`、`LIB-11`。
- 治理（12）：`GOV-01`–`GOV-03`、`GOV-05`–`GOV-13`。

**部分（3）**

- [`ARC-01`](codebase-audit-v2/03-compiler-and-runtime-architecture.md)：明细要求以 symbol ID 构图；当前 `checker.dawn` 的 `name_refs` 虽已排除词法绑定和模块别名，`EMethod` 仍会把非模块 receiver 的方法名记成本模块函数边，同名真实成员仍可能形成伪循环。
- [`ARC-02`](codebase-audit-v2/03-compiler-and-runtime-architecture.md)：明细要求覆盖 String、method 与 classfile 硬边界；当前 `ldc_str` 已分块、`class_bytes` 已接住 ASM failure，但 Core finalize 仍没有 span，超限 method/class 只能报 class/ASM method 文本而没有源码位置，仍须用户手工拆分。
- [`LIB-10`](codebase-audit-v2/05-stdlib-and-packages.md)：明细要求 CORS 包住最终 error response；当前 `with_cors` 已处理 handler 的 `Ok`/`Err`，但 `server.dawn` 的 dot-segment 400 与 body-limit 413 在 Request 和 middleware 之前产生，仍没有 CORS headers。

**开放（40）**

- 语法（8）：`SYN-04`、`SYN-05`、`SYN-09`、`SYN-11`、`SYN-12`、`SYN-13`、
  `SYN-16`、`SYN-17`。
- 语义（10）：`SEM-04`–`SEM-10`、`SEM-13`、`SEM-14`、`SEM-16`。
- 架构（6）：`ARC-07`–`ARC-12`。
- 工具链（4）：`TOOL-05`、`TOOL-06`、`TOOL-08`、`TOOL-13`。
- 库（11）：`LIB-06`、`LIB-07`、`LIB-08`、`LIB-12`、`LIB-13`、`LIB-14`、
  `LIB-15`、`LIB-16`、`LIB-17`、`LIB-18`、`LIB-19`。
- 治理（1）：`GOV-04`。

`74b3121` 当时只完成 #194 knife 1a：把 project dependency resolution 抽成一个 seam；
该提交本身既没有让 LSP/`doc` 加载 `[java-deps]`，也没有让 source 与 Java dependency
从同一最终图规划，因此当时未关闭 `TOOL-06` 或 `TOOL-10`。后续 SourcePlan 收口关闭
`TOOL-10`，`9f914d4` 又把 `check`/`doc` 接到 target classpath，最终由 `18fb3d6` 的共享 LSP
workspace 与每 identity lease 关闭 `TOOL-05/06`。这段演进不改写上面的历史快照计数。

代表性提交与验证来源（不取代明细中的原证据）：A1–A3 见 `60256bc`、`cd3cfc1`、
`a0d7800`、`cfb3bb8`、`dd51afc`、`a18b09a`、`77b0c07` 及 grammar/checker/package/dtoa
contracts 与 selfhost differential；#188 见 `2d6d61e`、`e154e38`、`50252e8` 及 checker
corpus；#193 见 `16f508c`、`0a3a4ba`、`3c9472c` 及 `scripts/spike-native/run.sh`、
`scripts/native-cli-diff.sh`；#206 与 release/bootstrap 收口见 `fde3203`、`2683638`、
`c4761ce`、`3a3ad4b`、`77374c9`、`086ea95` 及 `scripts/bootstrap-guards/run.sh`。

计数自检：**54 已修 + 3 部分 + 40 开放 = 97**。逐专题状态自检：语法 **11/0/8**、
语义 **7/0/10**、架构 **4/2/6**、工具链 **13/0/4**、库 **7/1/11**、治理 **12/0/1**
（顺序均为已修/部分/开放）；各专题仍分别覆盖 19 / 17 / 12 / 17 / 19 / 13 项，
与冻结总数一致且无重复、遗漏。

### 机器权威的当前四状态层

> R-AUDIT 在 `bfc358a6116303623a4968f8247689bcd5645793` 逐一核对六份明细的 97 个 ID；
> 此后 `38f625a` / `24d5d2f` 关闭 `SYN-12`，`79df07f` / `60e174a` 关闭 `SYN-16`，
> `9f914d4` / `18fb3d6` 关闭 `TOOL-06` / `TOOL-05`，`3e13645` 以完整 v2 launcher
> generation（fail-closed hasher、framed digests、pre/post re-plan、可恢复 commit-marker）
> 关闭 `TOOL-14`，GOV-04 又把本节收成机器校验的
> 唯一当前状态源。上一个三状态快照不删除、不改写其 ID 清单；这里增加 `retracted`，
> 把“实现修好”与“复核后不再认定为缺陷”分开。基线后的 `ARC-13` 作为新增 finding
> 直接以 fixed 入账，因此六份明细中的 98 个标题定义当前 ID universe；冻结历史层仍只
> 覆盖原 97 项，冻结 P1 映射仍只覆盖原 29 项。本节必须对当前 universe 无重复、无遗漏、
> 无未知 ID 地精确分区，并与当前专题矩阵和冻结 P1 映射一致。

| 状态 | 当前含义 |
|---|---|
| **fixed** | 原发现指出的缺陷边界已经由实现、规范与对应门禁关闭。 |
| **partial** | 已有实质修复，但原发现至少一个边界仍成立，不能冒称关闭。 |
| **open** | 发现仍成立；其中可包含 HOLD、延后能力或待 ABI/产品裁决项，执行状态另行注明。 |
| **retracted** | 逐项复核后认定原发现把已明确、内部一致的设计选择误当成缺陷；不是“通过实现修好”。 |

#### 当前 fixed（77）

- 语法（16）：`SYN-01`–`SYN-03`、`SYN-05`–`SYN-12`、`SYN-14`–`SYN-16`、`SYN-18`、`SYN-19`。
- 语义（11）：`SEM-01`–`SEM-03`、`SEM-06`、`SEM-07`、`SEM-11`–`SEM-15`、`SEM-17`。
- 架构（6）：`ARC-03`–`ARC-06`、`ARC-12`、`ARC-13`。
- 工具链（17）：`TOOL-01`–`TOOL-17`。
- 库（14）：`LIB-01`–`LIB-05`、`LIB-07`–`LIB-12`、`LIB-14`、`LIB-15`、`LIB-17`。
- 治理（13）：`GOV-01`–`GOV-13`。

#### 当前 partial（4）

- 架构（3）：`ARC-01`、`ARC-02`、`ARC-11`。
- 库（1）：`LIB-16`。

#### 当前 open（15）

- 语法（3）：`SYN-04`、`SYN-13`、`SYN-17`。
- 语义（4）：`SEM-04`、`SEM-09`、`SEM-10`、`SEM-16`。
- 架构（4）：`ARC-07`–`ARC-10`。
- 库（4）：`LIB-06`、`LIB-13`、`LIB-18`、`LIB-19`。

#### 当前 retracted（2）

- 语义（2）：`SEM-05`、`SEM-08`。

当前计数自检：**77 fixed + 4 partial + 15 open + 2 retracted = 98**。逐专题矩阵：
语法 **16/0/3/0**、语义 **11/0/4/2**、架构 **6/3/4/0**、工具链 **17/0/0/0**、
库 **14/1/4/0**、治理 **13/0/0/0**（顺序均为 fixed/partial/open/retracted）。
状态迁移逐项为：`LIB-07` fixed、`ARC-11` partial、`SEM-06` fixed、`TOOL-08` fixed、
`TOOL-14` fixed → partial（订正冒称的 fixed，后由 `3e13645` 的 v2 generation 收口回
fixed）、`SEM-05`/`SEM-08` retracted、`SYN-12`/`SYN-16` fixed，
`TOOL-05`/`TOOL-06`/`GOV-04`/`SYN-11`/`SYN-09` fixed。
2026-08-11 由 `doc-check.py` 的 evidence 检查一次性订正八条：`SEM-07`（`6874f64` 的
export-surface pass）、`TOOL-13`（`3f5d64c` 的 `atomic_write_file` 调用点迁移）、
`LIB-08`（`ce9cd15` 的结构化 `JsonError`）、`LIB-12`（`05db7f2` 的 query/form multimap）、
`LIB-14`（`4825c84` 的 tail capture 保段）、`LIB-15`（`aed3107` 的 handle 持有 executor）、
`LIB-17`（`3a21be8` 的 0/负数单一读法）与 `LIB-10`（`79448da` 让两条早退拒绝走 middleware
链，partial → fixed）全部转 fixed；`LIB-16` 的 header sanitizer 半边由 `a2d9571` 改成
拒绝而非删除，open → partial。这八条在订正前是**实现已发布、状态仍写 open** 的窗口，
分区、计数与专题矩阵三项自检当时全绿，那正是 evidence 检查存在的理由。
其后 `ARC-12` 由模块级 `LowerCache` 收口，open → fixed。同日 `SEM-13` open → fixed：
受约束函数与 trait method 现在是一等函数值，`check_fn_value` 在期望函数类型定型主体之后
写出 eta 展开，字典由 `resolve_witness` 在合成闭包内解析，外层约束的字典随之进入捕获列表。
随后 `SEM-14` open → fixed：用户可在所有函数返回位书写硬保留的 `Never`，storage 位置继续
拒绝；JVM 的 direct、dynamic、closure、trait/impl/default 与 SAM bottom call 统一走
non-fallthrough seam，并由双后端、classfile、checker、LSP 与 doc 合同固定。
其后新增 `ARC-13` 并直接记 fixed：native RC 的 `unloop` 现在拒绝删除终止语句仍跳向的
`CSLoop`，源码 `break`/`continue` 不再留下无目标 C goto；独立 match control 与删除 mutant
共同固定修复边界。它是冻结基线后的新增项，不改写原 97 项严重度与 29 项 P1 索引。

完整方法、严重度、证据等级和撤回项见[方法与旧结论处置](codebase-audit-v2/00-methodology-and-retractions.md)。

## 3. 冻结严重度总览

> 本表只回答 v0.60 发现时的严重度，不是当前状态计数；当前四状态矩阵见 §2。

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

### 4.1 当前未验证静态候选（不计入严重度）

| ID | 静态候选 | 当前口径 |
|---|---|---|
| `SYN-04` | `lower_match` 在每个 or-pattern alternative 内 lowering 同一 guard；多个 alternative 同时匹配时，effectful guard 可能重复求值 | 只记录可能性，未做运行探针；不把它从冻结 P2 改判为 P0/P1。 |
| `SEM-04` | comptime Cursor 使用 code-point index，JVM 使用 UTF-16 offset，native 使用 UTF-8 byte offset；折叠出的 Cursor 偏移可能跨执行模型失配 | 只记录静态跨后端候选，未验证可达程序；不另计严重度。 |
| `LIB-18` | streaming body 的 `transferTo` 正常 EOF 与异常均没有长度/结果契约；上游 clean truncation 可能被当作成功结束 | 只记录静态协议候选，未构造网络探针；不另计严重度。 |

这三项是当前“先记账、暂不验证”的最高风险候选；它们不改变 v0.60 冻结严重度表，也不在
98 项之外新增 ID。

### 4.2 冻结 v0.60 P0 候选（`SEM-01` 当前已修）

> 以下表格与建议保留 v0.60 的原始静态证据。`SEM-01` 后续已经动态确认并由 #188 修复，
> 不再是当前 P0 候选，也不再执行下面的旧探针建议。

| ID | 问题 | 为什么重要 |
|---|---|---|
| `SEM-01` | 逃逸 closure 捕获创建点 handler evidence，但类型仍写原效果标签；另一处 pure handler 可能消掉标签后执行旧 handler 的 IO arm | 若静态推导成立，`pure` 无副作用保证不 sound。按要求未动态验证；详见[类型与效果](codebase-audit-v2/02-types-effects-and-semantics.md)。 |

建议维护者先做一个隔离的 compile/run probe，但不要先写 workaround。应先决定词法 handler 的类型语义：禁止 evidence 逃逸、把旧 handler arm effect 纳入 closure type，或改调用点 evidence。这个决定会影响后续所有 effect feature。

### 4.3 冻结 v0.60 的 P1 分组

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

### 5.1 冻结 P1 的当前逐项映射

> 上面的 29 行是 v0.60 严重度索引，保持原文。下表只追加当前状态，不改写原行或冻结严重度。

| ID | 当前状态 | 复核结果 |
|---|---|---|
| `SYN-01` | fixed | formatter 词法失败不再写回。 |
| `SYN-02` | fixed | 插值扫描边界已统一并有 grammar contract。 |
| `SEM-02` | fixed | effect union 调用点 substitution 已闭合。 |
| `SEM-03` | fixed | opaque `Show` 不再被 String representation shortcut 绕过。 |
| `SEM-04` | open | Cursor owner/value 与跨后端 offset 契约仍待裁决。 |
| `SEM-06` | fixed | Java reference narrowing 只允许显式 checked cast。 |
| `ARC-01` | partial | lexical binding/module alias 已过滤，非模块 `EMethod` 裸名伪边仍在。 |
| `ARC-02` | partial | 长 String 与 ASM failure 已接住，method/class 超限仍无 source span。 |
| `ARC-03` | fixed | native failure payload 已对象化且不截断。 |
| `ARC-04` | fixed | nested failure payload 已按 handler frame 隔离。 |
| `ARC-05` | fixed | native recoverable unwind 已运行 cleanup。 |
| `TOOL-01` | fixed | 公开 `check` 的诊断与 exit contract 已闭合。 |
| `TOOL-02` | fixed | direct-file `fmt` 已限制 Dawn 源文件并保护写回。 |
| `TOOL-05` | fixed | canonical `(project, source_root)` 共享 plan、live overlay、Program、诊断与关闭回滚已闭合。 |
| `TOOL-06` | fixed | `check`/`doc`/LSP 已按 target 使用隔离 `JsigLease`，setup failure fail closed。 |
| `TOOL-07` | fixed | LSP framing 已有 header/body 上限与双端合同。 |
| `TOOL-09` | fixed | cache origin 不再给未验证旧目录背书。 |
| `TOOL-10` | fixed | source 与 Java dependency 已由唯一 `SourcePlan` 规划。 |
| `TOOL-11` | fixed | lock/vendor artifact identity 已脱离 basename。 |
| `TOOL-12` | fixed | JAR `Class-Path` URI 与 byte wrapping 已闭合。 |
| `TOOL-14` | fixed | fail-closed known-vector hasher、framed digests、stage1/candidate pre/post re-plan、持久化 inputs 与可恢复 commit-marker 已随 launcher generation 合同（66 断言 + 21 mutant 负控）全部落地。 |
| `TOOL-15` | fixed | seed std 已纳入摘要验证。 |
| `TOOL-16` | fixed | 默认 seed 缺摘要/工具时已 fail closed。 |
| `LIB-01` | fixed | bounded inflate 在 materialize 前限制输出。 |
| `LIB-02` | fixed | ZIP central directory 完整性已按声明边界校验。 |
| `LIB-03` | fixed | DEFLATE EOF 不再补零接受截断流。 |
| `LIB-10` | fixed | dot-segment 400 与 body-limit 413 现在都在 middleware 链下产生，CORS 与访问日志随之覆盖。 |
| `LIB-11` | fixed | request-body tempfile 从创建起即有 owner。 |
| `GOV-01` | fixed | dtoa 独立 oracle 已进入持续门禁。 |

逐行重算结果：**26 fixed / 2 partial / 1 open / 0 retracted = 29**。唯一 open 为 `SEM-04`；两项
partial 为 `ARC-01`、`ARC-02`。

## 6. 语言设计建议

> 本节保留冻结审查的长期建议；其中已修、retracted、delayed 或 HOLD 的项，以明细后续处置
> 和 §8·D 的当前顺序为准。

### 6.1 用一种结构表达一件事

- member access 不应由大小写在 parser 阶段提前分 field/method；application、pipe、formatter 应共享统一 postfix model。
- or-pattern 应是 `Pattern` 节点，不是 match-arm 外挂 list；`for` 应复用不可反驳 binding grammar。
- lambda 不应“普通位置禁 `fn`、尾调用位置只许 `fn`”；#206 已选择不与 curried
  application 冲突的 `{ ... }` 尾块作为唯一 trailing form，本条按期 2 收口。
- compiler-owned builtin type 已由分层 inventory 驱动 checker/LSP/doc，parser 保持只读语法
  形状；decl-start、TextMate keyword inventory 与 spec 表格仍应生成或至少由 contract test 对齐。

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

> 本节同样是冻结方向清单，不代表每项当前都可自治开工；`ARC-09/10` 的 HOLD 与依赖条件见
> 架构明细，当前执行顺序见 §8·D。

1. **阶段产物带 identity。** 用 `RegisteredImpl`、`LoweredFn` 等具名结构替代平行 List + index；所有 mismatch 在边界报 compiler invariant。
2. **symbol identity 分层。** nominal/effect/trait ID 与 local/typevar/temp ID 分开，避免前一模块的小改动重排后续全局产物。
3. **workspace/project 只有一份计划。** 该原则已由 TOOL-05/06 的 canonical workspace identity、captured `ProjectPlan` 与 target lease 落地；后续不得重新引入按文档或按请求规划。
4. **可恢复 failure 不再依赖裸 `longjmp` 丢帧。** 若继续使用 setjmp，必须有显式 cleanup/payload stack；否则采用 Result-style unwind ABI。
5. **大栈是临时策略，不是语言 ABI。** 512 MB stack 的裁决有历史依据，但应以 measured high-water 和 iterative pass 逐步下降。

## 8. 建议修复顺序

> A–C 保留 v0.60 冻结排期，不删除历史；当前执行顺序以本节末尾 D 为准。

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
- workspace-level LSP + single dependency plan（TOOL-05/06 已由 A-D 落地）。
- stable IDs 与 typed stage products；逐步退出 512 MB stack。

### D. 当前订正顺序（`18fb3d6`）

1. **TOOL-05/06 已关账：** `18fb3d6` 以 canonical `(project, source_root)` workspace、共享
   `Program`、诊断聚合与每 identity lease 完成收口，不再占用当前修复队列。
2. **先收口 partial P1：** 只剩 `ARC-01/02` 的 symbol edge/source origin（`TOOL-14` 已由
   `3e13645` 的 launcher v2 generation 收口，`LIB-10` 已由 `79448da` 把两条早退拒绝
   接进 middleware 链收口）。
3. **把 `SEM-04` 留给维护者裁决：** Cursor 是携带 owner 的值还是 generative identity，以及
   不同 owner 的 Eq/Ord 是否拒绝；裁决前只保留静态候选，不写 workaround。
4. **低耦合自治批：** `SYN-11`、B200-1B 后续、`SYN-09`、`SYN-05` 与 `SEM-07` 均已关账；
   下一项按依赖推进 `SYN-04 → SYN-13`；`SYN-17` 只留在 D/P3 关键字预算设计队列。
5. **类型化阶段产品：** `ARC-07` 后接 `ARC-08`，再以稳定 lowered identity 推进
   `ARC-11B`；不把 `ARC-09/10` 的 HOLD 项混入自治队列。`ARC-12` 已单独收口
   （模块级 `LowerCache` + 贯穿的 lifted-lambda 计数器），它给 `ARC-11B` 提供的是
   「同一函数体在整个模块里只有一份」这条身份前提，不是 `ARC-11B` 的全部前置：
   后者还欠 `RC-03` 的 `fold_children`/`visit` 原语，缺它就是第七份手写全树遍历。
6. **破坏性 package API：** `json2` / `web3` 两个 major 已带走 `LIB-08`、`LIB-12`、`LIB-14`、
   `LIB-15`、`LIB-17`；余下 `LIB-06`、`LIB-13`、`LIB-16`、`LIB-18`、`LIB-19` 按下一个 major
   与迁移窗口分批。`SEM-09/10` 是 intentional delayed capability/ABI，`SEM-16` 是 HOLD，
   均不作为自治修 bug。

## 9. 旧审查如何读

`docs/codebase-audit.md` 已明确标为 **historical**；不要把其中的 P0 table 或排期当作当前状态。v2 已明确撤回：用户可达 `unsafe_pure`、无集合源码、无 Core IR、非一般调用、Char/LSP debounce/Web v2 未落地、JSON 大整数/非法输出、cast/catch/bracket 缺失等结论。Unicode 标识符、`!` 双义、Float Ord/Hash、historical EBNF 等争议也没有重新包装成问题。

逐条理由和仍保留的“已知债务”见[方法与撤回](codebase-audit-v2/00-methodology-and-retractions.md)。

## 10. 明细目录

- [00 — 方法、证据、严重度、旧结论撤回](codebase-audit-v2/00-methodology-and-retractions.md)
- [01 — 语法、词法、formatter、TextMate](codebase-audit-v2/01-syntax-and-formatting.md)
- [02 — 类型、trait、效果、语义](codebase-audit-v2/02-types-effects-and-semantics.md)
- [03 — checker、Core、后端、native runtime](codebase-audit-v2/03-compiler-and-runtime-architecture.md)
- [04 — CLI、LSP、依赖、构建、自举、发布](codebase-audit-v2/04-cli-lsp-build-and-release.md)
- [05 — std、inflate、JSON、Web、SHA-2](codebase-audit-v2/05-stdlib-and-packages.md)
- [06 — spec、文档、测试、CI、治理](codebase-audit-v2/06-docs-tests-and-governance.md)
