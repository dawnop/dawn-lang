# 拆除增量引擎的 opt-in 切片

> 状态：**current** —— 2026-09-27 用户拍板拆除，两刀落地：刀 1（#259）删体级重放引擎，刀 2（#261）删读取日志与写日志
> 插桩。拆除前的整棵树在 tag `incremental-slice-final`，考古看那个 tag。
> 留下的身份、调度与按键产物是 laziness 的地基；下一步是 laziness，不是 incrementality。

## 一、结论

增量语义引擎的 opt-in 切片（体级重放、准入类别、prepared bodies、读取事实与写日志、bench-replay 及守它们的契约）
是**正确的但不值钱**：三次 G3 实测里重放的每体代价都没有低于冷检，差距还在拉大；它在任何生产路径上都没有消费者；
留着它每次 push 付 push-total 的四成、每次改 `check/` 付近一小时的本机契约全扫。所以拆，分两刀删代码、一刀迁文档。

## 二、为什么拆

### 2.1 三次 G3 实测

G3 的判据是三类重放的每体代价低于冷检。表中是「重放 / 冷检」的每体代价比，大于 1 即重放更贵：

| 类 | 09-24（`b2e19e06`，集群） | 09-26 S2 后（`ec95246c`，集群） | 09-27 大方法刀 2 后（`98d83a6d` 同源，集群空闲节点，作定论） |
|---|---:|---:|---:|
| calls | 0.80 | 0.80 | **1.65**（重放 33.07 ms / 冷检 20.05 ms） |
| generic | 1.15 | 0.94 | **2.22**（65.03 / 29.32） |
| inferred（lambda） | 1.17 | 1.21 | **1.22**（45.79 / 37.63） |
| primitive_inferred | 约 1.5 | 1.43 | **1.69**（20.32 / 12.05） |

读法：大方法拆分（#241）让冷检快了 24% 到 56%，重放路径没有跟着受益（它本来就没被 HotSpot 的大方法限制卡住），
所以「重放比冷检快」在每一类上都不成立，而且冷检越快，重放越不划算。真实编辑矩阵的命中率一直是 0.998 到 1.0：
重放是对的，只是每体的证明成本高于直接重算。

### 2.2 没有生产消费者

生产 LSP 固定走 legacy 前缀复用（`body_enabled false`）；Playground 的 `/check` 每个请求独立 `dawn build`。
重放与读取日志只在契约 harness 与基准里被打开过。

### 2.3 留着的代价

拆除前的调研（基线 `98d83a6d`）量过：

| 项 | 量 |
|---|---|
| CI 声明秒 | 13 个 incremental job 8,461 s，加 17 个宿主 job 里的切片步骤约 2,600 s，合计约 11,000 s，占 push-total 26,617 s 的 41% |
| 本机契约全扫 | 每次改 `check/` 跑 79 个 invocation，53 分钟，峰值 8.9 GiB |
| 维护面 | selfhost 约 12,800 行、scripts 约 12,000 行；探针按字面量构造检查器内部记录，身份、按键产物、大方法拆分每一刀都要逐个改探针 |
| 冷路径 | provenance 表在每次冷构建与每次 legacy 会话复检里都建而无人读；`Cx` 多两个日志字段，检查器每次查找多一层记录分支 |

「只停工不拆」等于继续付上表的全部费用，换来的只是「以后也许重开」的选项，而这个选项 tag 同样能保留（`kotlin-final` 先例）。

## 三、拆了什么

### 3.1 刀 1：重放引擎（#259）

- `check/` 的 15 个模块，7,310 行：`scalar_replay`、`bounded_replay`、`function_entry_proof`、`body_product`、`body_admit`、
  `body_execution`（录制执行器）、`header_product`、`function_product`、`callee_index`、`allocation`（provenance 表）、
  `source_projection`、`source_snapshot`、`scalar_shape`、`query_runtime`、`evidence_spelling`。
- `contract/` 的三个探针：`cached_module_observer`、`session_bodies`、`prepared_sessions`。
- `driver/analyze`、`driver/stdlib`、`driver/incremental`、`lsp/server` 里的 prepared/cached/provenance 分支：
  `analyze_module_step` 收回成一行 `check_module`，`LspAnalysisMode` 收成 `Legacy | Cold`，`Stats` 去掉 11 个体字段。
- `identity` 小瘦身：`ModuleKey`/`module_key` 与只为它存在的测试助手。
- 33 个契约 harness 与它们的模板、8 个 Java 预言机，`scripts/journal-reads/`，`lsp-workspace-contract/prepared-lifecycle.py`。
- CI：5 个 job 整删，剩下的前缀、冷参照、身份、调度器与执行器契约收进 `incremental-prefix-1..3` 三个 job；
  push-total 26,617 s → 25,375 s。`dawn test selfhost` 930 → 804。

### 3.2 刀 2：读取日志与写日志插桩（#261）

- `check/semantic_reads`（读取事实）、`check/write_journal`（写日志，含 `SignatureKey`）两个模块；`Cx.function_reads`、
  `Cx.body_writes` 两个字段；`revalidate_read`、`revalidate_function_read`、`revalidate_witness_read`、`revalidate_context_read`
  四个候选修订重验入口。
- 约 80 个 `*_read` 包装。读取日志一走，它们只剩「返回传进来的 `Cx`，旁边附一个查表结果」，调用者再把那个没变的
  `Cx` 线程下去；包装删掉，调用点直接问表（或包装里本来就叫的那个纯函数），约 500 个调用点。为线程这些读取而改成
  返回 `Cx` 的函数恢复成纯函数，大多回到 `7cfb807e`（第一刀读取插桩）之前的形状：`needs_expected`、`refutable_span`、
  `structural_gap`、`ord_subject`、`qual_fn` 一族、Java 打分一族（`sam_*`、`param_score`、`score_with`、`fit_score`）等。
  `check/exhaustive` 整篇回到 `c957ada1` 之前的纯算法。
- 四个写入口（`write_symbol`、`write_signature`、`write_alias`、`write_bounds`）保留为普通写入。
- 115 个内联测试：检查器的读取与重验测试 96 个、`cx` 7 个、`exhaustive` 8 个、两个被删模块 4 个；另有两个检查器测试
  保留冷路径断言、去掉读取断言。`dawn test selfhost` 804 → 689。
- 14 个读取族 harness（diagnostic、local-value、type、function、export、Java namespace/oracle/class/member、effect、
  environment、associated 读取，context 与 witness 重验）。
- CI：`incremental-1`、`-2`、`-3-1`、`-4`、`-5`、`-6`、`-7-2`、`-8` 八个 job 只剩读取族步骤，整删，4,859 s；
  push-total 25,375 s → 20,516 s。本机契约全扫从 33 个 invocation 降到 14 个。
- 顺带：`checker-corpus/coverage.py` 原来只能经旧 `(Cx, answer)` 元组的槽位追到三处诊断记录的文字，
  现在也认单名不可变 `let` 整个绑定的记录与 Option（带正负控）；覆盖率仍是 292/296，与拆除前相同。

### 3.3 刀 D：文档

六篇设计文档转 `docs/history/`（见 [docs/README.md](README.md) 的「历史」一节），
`symbol-id-design.md`、`package-visibility-design.md`、`unused-imports-design.md`、`qualified-effects-design.md` 与
审查 v2 的第 03 篇里引用被删模块的句子改成过去时并指到这里。

## 四、留了什么，为什么

| 保留件 | 位置 | 为什么留 |
|---|---|---|
| 声明身份（M0.5） | `check/identity`：`DeclKey` 路径、`pack`/`derive`、`DeclSpans`、`PathTable` | 已是冷输出的坐标系：诊断按声明相对偏移记录、symbol id 按声明派生，拆掉它冷输出就变 |
| 保序调度与 SCC（S1/S2） | `execute_module_bodies`、`inferred_dependencies`、`inferred_groups`、`cycle_components`、`attempt_inferred_group`、`Cx.unsealed_uses` | 冷检本身在用：推断函数的检查顺序与真环判定；`Cx.unsealed_uses` 是真依赖边，不是读取插桩 |
| 执行器接缝 | `BodyExecutor`（冷执行器 + 测试用追踪执行器） | laziness 第二步要一个跳过体的执行器，插口就是它 |
| 具名 header 产物（S3） | `ModuleHeaders` 的三张 `PathTable` | 按键而不是按下标配对，冷路径在用 |
| 带键的类型化树（S4） | `TFun.decl`/`TConst.decl`、LSP 按键取树 | LSP 查询在用 |
| 体内偏移与未用导入 | `check/tast_positions`、`check/import_use` | 冷输出的一部分；未用导入走语法遍历，不依赖执行器 |
| legacy 前缀复用 | `driver/incremental` | 生产 LSP 唯一用的复用 |
| 冷参照与前缀契约 | `contract/{cold,prefix,probe,bench}`、`incremental-prefix-1..3` | 守上面几件 |

这些合起来是 laziness 的地基。rust-analyzer、TypeScript、Roslyn 与 matklad 的 Rust Glancer 的共同点是「身份与 header 层全量、
函数体按需」，没有一家在函数体里做重放加证明。Dawn 的非私有函数必须写返回类型（`front/parser.dawn` 的
`pub functions must declare a return type`），所以模块的导出只由 header 决定：第一步按模块粒度，只对打开的文件跑体检查，
关闭的文件只跑 `check_module_headers` 与 `exports_of`，不需要新的依赖分析；第二步按声明粒度，才用到 S1/S2 的依赖图与
SCC 和 `BodyExecutor` 这个插口。

## 五、拆的时候怎么证明冷输出没变

两刀都是「删掉一条冷路径不走的分支」，判据是冷输出与 legacy LSP 逐字节不变，提交里没有一条 `Emit-Change`：

- `selfhost-core-diff.sh`：examples 的 Core dump 一个不变；selfhost 里变的只有被改的模块自身，以及因为 `Cx` 的形状变了
  而跟着变的读者。刀 2 是 13 个模块：`check/` 里被改的 6 个（含删掉的 2 个），加上 `c/cdriver`、`driver/analyze`、
  `driver/incremental`、`driver/stdlib`、`lsp/lspc`、`main`、`check/import_use`，后 7 个把 `Cx` 的字段下标与局部编号
  归一化以后，剩下的只有 `Cx` 整体重建时那两个被删字段的拷贝；
- `checker-corpus/run.sh` 不 `--record` 全过（163 个夹具，649 条诊断按记录的顺序）；
- `selfhost-prev-diff.sh`、`selfhost-run-diff.sh`、`selfhost-fmt-diff.sh`、`selfhost-lsp-diff.sh` 对 N−1 零字节差；
- `selfhost-fixpoint.sh` B==C、`native-fixpoint.sh` 通过；
- `lsp-configured.py --mode Legacy` 分别用拆除前后的编译器起服务端，`lsp-edit-matrix.py`（1000 函数，10 个修订）与
  `lsp-project-matrix.py`（8 个跨模块修订）的全部诊断与 hover/definition/completion 回复逐字相同；
- 负控：S1 的「丢轮次只按下标」变异在拆除后的树上仍让 core-diff（`check.checker` 变）与 checker-corpus
  （`infer_order_*` 四个夹具）变红。

刀 2 删掉的是检查器每次查找都要过的一层，所以它有可测的冷路径收益。本机（GraalVM CE 21.0.2，`-Xss512m -Xmx2g
-XX:+UseSerialGC`）两个编译器对同一份输入交错各跑 5 轮 `check selfhost`（各预热 1 轮）的中位数：

| 编译器 | 墙钟 s | CPU s | 峰值 RSS MB |
|---|---:|---:|---:|
| 刀 2 前（`e4f2029e`） | 5.69 | 17.61 | 634 |
| 刀 2 后 | 5.15 | 16.16 | 612 |

五轮墙钟分别是 5.67 到 5.74 与 5.12 到 5.21，不重叠：墙钟 −9.5%、CPU −8.2%。检查器方法的字节码随之变小
（`code_length`，`check/checker` 全模块 226,063 → 192,922 字节；`check_call` 5,689 → 5,286，`check_apply` 2,714 → 2,402，
`infer_call_args` 1,246 → 976）。`bench.py` 的冷阶段（各树检查自己的源码，所以还含输入变小的部分）selfhost 目标
`cold` 中位数 1,152 → 1,042 ms、`check` 619 → 514 ms；LSP 独立缓冲区（500 个函数）的同步延迟两边都在 26 到 28 ms，
没有可测差异。刀 1 同法测的 `check selfhost` 也是「没有可测差异」（provenance 表每进程只建一次）。

## 六、不做的（理由）

- **不保留读取事实作「将来整体 memo 的依赖记录」。** rust-analyzer/Salsa 的依赖是查询框架自动记的，粒度是函数体与签名，
  不是检查器的五十种查找事实；Dawn 真要做整体 memo，S2 的依赖图加「导出相等即早截断」已经够用。
- **不先删读取插桩再删引擎。** 读取事实是重放的输入，引擎还在时删插桩等于让在树的代码失去守卫。
- **不把这些 job 改成按路径触发来省预算。** 这是 `tile.yml` 走过的路，触发率随后失控；删掉比挪走干净。
- **不在拆除刀里顺手做 laziness。** 拆除的判据是冷输出与 legacy LSP 逐字节不变，laziness 故意改变 LSP 行为
  （关闭文件不再推送体内诊断），混在一起两条判据都证不干净。
- **不把 `ExportDiagnostic` 退回拆读取前的「在辅助函数里直接报错」。** 它现在还承载包可见性的「选择报哪条」
  （`pkg_private_export`），退回去会改变诊断现场的结构与覆盖率台账的键；它是普通的诊断记录，不是插桩。
- **不改 `Cx.unsealed_uses`。** 它看起来像读取记录，实际是 S2 的真依赖边，调度器靠它丢弃用了未封签名的试检。

## 七、出处

- 用户裁决：2026-09-27（拆 / 不拆继续养 / 先不动只停工，选拆）。
- 三次 G3 实测：09-24 `b2e19e06`、09-26 `ec95246c`、09-27 `98d83a6d`，均在集群上跑 `bench-replay`，表中数字取自各次报告。
- 代价与清单：拆除前调研，基线 `98d83a6d`，`wc`/`grep` 实测，CI 秒数取 `gates.yml` 的 `# budget: 3x` 声明。
- 外部：<https://rust-analyzer.github.io/book/contributing/architecture.html>、
  <https://rust-analyzer.github.io//blog/2020/07/20/three-architectures-for-responsive-ide.html>、
  <https://matklad.github.io/2026/08/21/rust-glancer.html>、<https://basarat.gitbook.io/typescript/overview/checker>、
  <https://github.com/KirillOsenkov/Bliki/wiki/Roslyn-Immutable-Trees>。
