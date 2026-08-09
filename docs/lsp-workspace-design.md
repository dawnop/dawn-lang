# LSP workspace 与目标级 Java classpath 设计（TOOL-05/06）

> 状态：**proposed，动码前的调研与方案**。源码基线为 `be664a3`。本文只覆盖仍开放的
> TOOL-05 与 TOOL-06；TOOL-07、TOOL-08、TOOL-10 已完成，只作为前置事实引用。

## 1. 范围与已完成前置

旧的 v0.60 草案把 workspace、framing、lifecycle、两套依赖图、缓存和 classloader 混成一批。
当前代码已经换了地基，执行范围必须收窄：

| 条目 | 当前状态 | 与本文的关系 |
|---|---|---|
| TOOL-07 | 已完成 | `server.read_message` 已在共享 Dawn 层限制 8 KiB header、64 MiB body，并在不可重同步时终止读循环；见 [lsp-framing-design.md](lsp-framing-design.md) |
| TOOL-08 | 已完成 | `server.Lifecycle` 已实现 initialize/shutdown/exit 状态机 |
| TOOL-10 | 已完成 | [source-plan-design.md](source-plan-design.md) 已把 manifest、MVS、fetch、最终 source 图与 Java 坐标统一进 Java-free `compiler-plan.SourcePlan` |
| TOOL-05 | open | LSP 仍是一文档一份 `Program`，只覆盖当前 buffer，只发布当前 URI |
| TOOL-06 | open | `check`、`doc`、LSP 仍从 system classloader 反射，未按 target 加载 `[java-deps]` |

本文不重开前三项，也不在实现前把 TOOL-05/06 标成 fixed。

## 2. 当前实现证据

以下事实均按 `be664a3` 的源码符号重新核对，不沿用旧草案行号。

1. `compiler-plan/src/source.dawn` 已公开显式的 `SourceTarget` 与唯一 `SourcePlan`；后者持有
   `project`、`source_root`、最终 `PkgR`、`java_coords` 与规划诊断。`compiler-plan/dawn.toml`
   只有 `fspath`、`sha2`、`inflate` 三个源码依赖，没有 `[java-deps]` 或 `use java`。
2. `selfhost/src/driver/analyze.dawn` 仍在 `load_directory`、`load_file_over`、
   `use_candidates` 分别调用 `source_plan`。`resolve` 的 `follow_only` 参数只有声明，没有读者。
3. `selfhost/src/lsp/server.dawn` 的 `Doc` 仍直接保存完整 `Program`；`update_doc` 只把当前
   文本交给 `analyze_document`，再只向当前 URI 发送 diagnostics。`didClose` 只删 `Doc` 和清空
   该 URI 的 diagnostics，没有让依赖它的其他文档回落磁盘后重分析。
4. `analyze_document` 的 project 分支只构造 `{当前 canonical path -> 当前文本}` 的单元素
   overlay。其他 open buffer 仍从磁盘读取。
5. `lspc.path_items` 与 `lspc.import_items` 都自行调用 `use_candidates`。两支在一次 completion
   中互斥，并非旧草案所说的“同一请求必跑两次”；但无论命中哪支，都会脱离本次文档分析的
   snapshot 再规划一次。通用查询上下文 `lspq.QCx` 当前只含 typed/query 数据，不应为此永久
   增加 completion-only 字段。
6. `jvm/jreflect.dawn` 的八个 `Jsig` 查询最终都经 `ClassLoader.getSystemClassLoader()`；
   `LspState` 只有一份全局 `Jsig`。`main.dawn` 的 `check`、`doc`、`lsp` 直接传
   `jsig_real()`，只有 build/run/test 先解析 Java 依赖并 re-exec。
7. build/run/test 的 re-exec 暂时仍有生产消费者：`jvm/emit.dawn` 在 varargs component 与
   interface 判断处直接问 `jreflect`，`jvm/jfold.dawn` 的 comptime Java FFI 也直接反射。
   因此“checker 有 target loader”不能推出“可以删除 re-exec”。

现有 `server.dawn` 关于“编辑器中的 `use java` 与 compile 完全一致”的注释与第 6 条冲突；
TOOL-06 落地时应一起改正，不能继续把 system classpath 当作 target classpath。

## 3. 三层所有权

三层只允许向上组合，不允许复制下层字段。

### 3.1 `compiler-plan.SourcePlan`

`SourcePlan` 继续独占：

- 显式 `ProjectDirectory` / `SourceFile` target；
- manifest 校验、源码包 fetch、MVS 与最终 `PkgR`；
- `project`、`source_root`、Java coordinates 与规划诊断。

Maven artifact fetch、`dawn.lock` 校验、Java 对象和 classloader 永远不进 `compiler-plan/`。

### 3.2 selfhost `ProjectPlan`

`ProjectPlan` 只包一份 `SourcePlan`，再派生 compiler-facing 模块索引：

```dawn
pub type ModuleIndex = {
  project_files: List[String],
  by_use: Map[String, String]
}

pub type ProjectPlan = {
  source: source.SourcePlan,
  modules: ModuleIndex
}
```

`project_files` 是一次稳定排序的项目 source-tree walk，保留调用者路径拼写，也保留模块名非法的
`.dawn` 文件，让 loader 继续产生现有诊断。`by_use` 只含合法、非 `std` 的 module path，值是
canonical file path；项目模块与直接 `[deps]` 包继续使用现有消费者 alias 拼写。

`ProjectPlan` **不复制** `project/source_root/pkgs/java_coords/diags`，也不持有 `Program`、`Cx`、
`ModExports`、Maven jars、lock 状态或 classloader。它放在 `driver/analyze.dawn`，复用已有的
`module_path_of`、`bad_segments`、`walk_dawn` 和 alias 规则，不新建一份 module-path 算法。

### 3.3 LSP `Workspace`

只有 `Workspace` 持有会话活状态：一个 root 的全部 open-buffer overlay、open entries、一份共享
`Program`，以及一份 target-scoped `JsigLease`。不同 canonical root 的所有这些值完全隔离。

```dawn
type Workspace = {
  key: String,
  plan: ProjectPlan,
  overlay: Map[String, String],
  entries: Map[String, String],
  prog: Program,
  entry_by_uri: Map[String, String],
  java: JsigLease
}
```

`Doc` 在最终形态只保留 URI、path、live text、`SourceView`、line starts、workspace key 与 entry。
无法归入 project 的 untitled/standalone buffer 可以保留私有 standalone `Program`，但不得伪造
project `Workspace`。

## 4. 第一刀：建立 captured-plan seam

第一刀只建立可复用边界，不宣称修复 TOOL-05/06。

```dawn
pub type DocumentAnalysis = {
  prog: Program,
  entry: String,
  plan: Option[ProjectPlan]
}

pub fn project_plan(target: source.SourceTarget) -> ProjectPlan !io

pub fn load_entries_over(
  plan: ProjectPlan,
  entries: List[String],
  overlay: Map[String, String]
) -> LoadResult !io

pub fn analyze_document_planned(
  path: String,
  text: String,
  std: StdCtx,
  opts: CtOpts,
  js: Jsig
) -> DocumentAnalysis !io
```

边界必须满足：

- `load_entries_over` 只消费传入的 `plan.source.source_root`、`plan.source.pkgs` 与规划诊断，
  **不得**在内部再次调用 `source_plan` / `project_plan`。
- `load_directory(dir)` 保留现有 `src/` 前置拒绝顺序，再以
  `ProjectDirectory(dir)` 构造 plan，以 `plan.modules.project_files` 作为 entries。
- `load_file_over(file, overlay)` 以 `SourceFile(file)` 构造 plan，再以 `[file]` 作为 entries；
  `load_file` 签名与行为不变。
- `analyze_document_planned` 的 standalone 分支返回 `plan = None`；project 分支返回实际用于
  load 的同一个 `ProjectPlan`。旧 `analyze_document -> (Program, String)` 保留为丢弃 plan 的
  compatibility wrapper。
- 删除未使用的 `resolve.follow_only`，不借机改变 load 范围或诊断。

这条 seam 有一项明确成本：每次 fresh file-mode plan 会遍历完整 project source tree，并对每个
唯一的直接 dependency root 遍历一次；它不解析全部文件，指向同一 root 的重复 alias 共享一次
walk。第一刀接受这项正确性成本，D 刀由 workspace 持有 plan，消除编辑器会话内的重复遍历；
CLI 是否再加缓存必须先量测，不能在没有失效协议时偷加全局状态。

第一刀里 `Doc` **暂时仍各持一份 `Program`**，只新增 `plan: Option[ProjectPlan]`。completion
不把 module index 塞进通用 `QCx`，而是显式接收 completion-specific 参数：

```dawn
pub fn completions_at(
  qc: QCx,
  project_modules: Option[Map[String, String]],
  text: String,
  offset: Int
) -> List[CItem] !io
```

只有确认 cursor 位于 `use` completion 后才取得候选表：`Some` 直接复用文档分析捕获的
`plan.modules.by_use`；`None`（例如尚未完成的 `use ` 或 standalone buffer）最多调用一次
兼容 `use_candidates`。`path_items` 与 `import_items` 接收同一张表，自己不得重新规划。

这一刀的硬预算是：`selfhost-lsp-diff.sh` 与 `selfhost-prev-diff.sh` 字节不变，
**零 `Emit-Change`**。Core golden 可以因记录形状移动而重录，但只接受预期的
`driver.analyze`、`lsp.server`、`lsp.lspc` 变化；无关模块变化先调查，不直接录入。

## 5. TOOL-06：`JsigLease`，不是进程 classpath

### 5.1 已验证的构造路径

真实 spike 已推翻旧注释“reflection here cannot do”的前提：

- 直接调用 `URLClassLoader.new(urls, parent)` 会因 `urls` 的 Dawn 静态类型是 `Object` 而稳定
  报“没有 `(Object, ClassLoader)` 构造器”；这条直接路线不可用。
- 现有 FFI 已能用 `Array.newInstance(URL, n)` + `Array.set` 造真实 `URL[]`，再经
  `Class.getConstructor(Class...)` 与 `Constructor.newInstance(Object...)` 调构造器，最后
  `cast[URLClassLoader]`。
- parent 使用 `ClassLoader.getPlatformClassLoader()`，避免把编译器自身 application classpath
  泄漏给 target，同时仍由 JVM delegation 看见 JDK classes。
- 两个包含相同 FQCN、不同 API 的 JAR 可被两份 loader 同时正确解析；system loader 看不见
  fixture class。两线程各重复查询 200 次没有串类；关闭 loader 后其独有 resource 不再可见，
  异常路径上的 `bracket` 也完成关闭。

因此无需新增 Dawn 语法、`URL[]` 表面类型、Java helper 或 seed runtime helper，也无需用户裁决。

### 5.2 API 与宿主边界

Java-free `check/jsig.dawn` 增加生命周期记录；JVM 实现在 `jvm/jreflect.dawn`：

```dawn
pub type JsigLease = {
  jsig: Jsig,
  close: fn() -> Unit !io
}

pub fn jsig_for(jars: List[String]) -> JsigLease !io
```

`jreflect` 把现有查询拆成显式 loader 参数的内部函数；`jsig_for` 的八个闭包捕获同一 loader。
既有 `jsig_real()` 与直接 `jreflect` wrapper 继续走 system loader，供仍依赖 re-exec 的
build/run/test emitter 与 comptime FFI 使用。

`pkg/maven.dawn` 保持 selfhost 所有权，可抽出一个不打印、不退出的 helper：

```dawn
pub fn fetch_checked(
  project: String,
  coords: List[MCoord]
) -> Result[List[String], String] !io
```

它完成 Coursier fetch 与已有 lock parse/hash/check；调用者决定把 `Err` 变成 CLI failure 还是
workspace-level diagnostic。失败时必须 fail closed，绝不退回 system loader。

共享的 `lsp/server.dawn` 不能 import Java-backed Maven/jreflect。`run_lsp` 改为接收宿主提供的
“`SourcePlan` -> `JsigLease`”工厂：JVM main 用 `fetch_checked` + `jsig_for`，native main 返回
target-local 的 `jsig_refused()` no-op lease。这样 server 仍是零 `use java` 的共享前端。

### 5.3 生命周期

- `check` 的每个 target 各自构造 `ProjectPlan`、解析/校验 jars，并在 `bracket` 内用该 lease
  分析；多 target 不合并 classpath。
- `doc` 对单个 target 走同一流程。两者都用 plan-aware loader，Java coords 与 source load
  来自同一个 captured `SourcePlan`。
- LSP 每个 workspace 独占一份 lease。替换 plan/classpath 时先完整构造新 plan、jars 与 lease，
  再原子替换 workspace，最后关闭旧 lease；构造失败保留旧值并发布 project diagnostic，
  不安装半成品。
- 关闭最后一个 workspace 文档、正常 `exit`、EOF 与 fatal framing 退出都关闭对应 lease。
  关闭后不得再查询。
- 当前 server 同步执行，第一轮没有 close/query 竞态；未来若引入并发分析，必须另加引用计数
  或等待 in-flight query，不能复用本轮假设。

## 6. TOOL-05：workspace 正确性

一次 settled update 对所属 workspace 执行以下固定流程：

1. 将所有 open docs 的 canonical path -> live text 汇总成一张 overlay；URI -> canonical path
   汇总成 entries。
2. 以 entries 的稳定 URI 顺序调用一次 `load_entries_over(ws.plan, ..., ws.overlay)`，再调用一次
   `analyze_program(..., ws.java.jsig)`，形成唯一 `Program` 与 `entry_by_uri`。
3. 对该 workspace 的**每个** open URI 发布 diagnostics，包括空数组；range 使用对应文档的
   live `SourceView`，不能拿别的 buffer 或磁盘文本计算。
4. planner/Maven/lock 这类 project diagnostic 归到 `dawn.toml` URI；恢复后同样显式清空，
   不能因 manifest 未打开而静默丢失。

`didClose` 先从 entries 与 overlay 移除该文档，再按剩余 entries 重分析：若关闭的 unsaved 文件
仍被其他 open doc 引用，loader 必须回落磁盘内容。随后清空已关闭 URI，并重发所有剩余 open
URI；最后一个 entry 被关闭时移除 workspace 并关闭 lease。

多 root 以 canonical project root 为 key。overlay、Program、module index 与 loader 均不得跨 root
查询；两个 root 即使依赖相同 FQCN 的不同 JAR，也必须得到各自答案。

第一轮继续使用现有同步 debounce。**不加** `gen`、异步 task 或 cancellation：没有并发分析，
就没有旧 generation 覆盖新结果的竞态。workspace correctness 先求答案一致，不承诺增量性能。

## 7. 分刀顺序与输出预算

| 刀 | 内容与 API/行为边界 | 主要门禁与负控 | Emit-Change 预算 |
|---|---|---|---|
| A | `ProjectPlan`、`project_plan`、`load_entries_over`、`analyze_document_planned`；兼容 wrappers；Doc 暂存 plan；completion 显式复用 module index | captured-plan contract；把 loader 改回 fresh replan 必红；把 completion 改回 fresh `use_candidates` 必红；LSP/prev diff 字节不变 | **0，硬要求** |
| B | `JsigLease`、platform-parent `URLClassLoader`、loader-parameterized reflection；尚不改 CLI/LSP 行为 | 双 JAR 同 FQCN、system-loader mutant、合并全局 loader mutant、close resource、异常 bracket | **0** |
| C | JVM `check`/`doc` 按 target 使用同一 captured plan + `fetch_checked` + bracketed lease；native refusal 不变 | 带 `[java-deps]` 的 check/doc；多 target 同 FQCN 隔离；删除 close 或绕过 bracket 必红 | 预期 **0**；若既有 transcript 真变，先逐项 review 再按闭集 label 声明 |
| D | `Workspace`：全 overlay、全 entries、一份 Program、每 root lease、didClose rollback、全量发布 | 两文档 unsaved export、didClose 磁盘回落、只发当前 URI mutant、双 root 同 FQCN、全部 diagnostics | 只有本刀可能需要 **一次 `Emit-Change(lsp)`**；以实测 diff 为准，不预写 |

每个 mutant 必须先成功构建，再由 owning contract 精确打红；grep 只能补结构边界，不能替代行为
负控。任何 Emit-Change 都在门禁和人工 diff review **之后**写，禁止通配。

## 8. 验收矩阵

| 合同 | 正例 | 必红变异 |
|---|---|---|
| captured plan | 先规划 alias -> 包 A，再把磁盘 manifest 改成包 B；old plan 仍加载 A，fresh wrapper 加载 B | `load_entries_over` 内重跑 `project_plan(plan.source.target)` |
| captured completion | didOpen 后改磁盘 manifest；当前 Doc 的 `use alias/module.{` 仍列旧包导出，新会话列新包导出 | 忽略显式 module index，恢复 fresh `use_candidates` |
| loader 隔离 | system loader 看不见 fixture；workspace A/B 对相同 FQCN 分别看到 A/B API | 改回 system loader；或把两 workspace 合并进一份 loader |
| loader 释放 | 正常 close 与异常 bracket 后，JAR 独有 resource 都不可见 | 删除 `close`；让异常路径绕过 bracket |
| unsaved export | 两文档都 open；只在被依赖 buffer 改 `pub` 名，依赖方立即按 live 文本重新诊断/补全/definition | overlay 退回单元素，或仍从各 Doc.Program 查询 |
| didClose rollback | 关闭未保存的被依赖文件后，剩余文档按磁盘版本重分析 | 只删 Doc/清 diagnostics，不重分析 workspace |
| 全量 diagnostics | 一次 edit 后所有 open URI 都收到最新数组，含需要清空的 `[]` | 发布循环退回只发当前 URI |
| 多 root | 两 root 的 overlay、module path、Program、同 FQCN Java API 互不泄漏 | workspace key 退回全局值或只按 URI 共享 loader |

实现至少运行：`./bin/dawn test selfhost`、`./bin/dawn test compiler-plan`、新 contract mutants、
`scripts/lsp-use-completion.py`、`scripts/lsp-lifecycle-contract/run.sh`、
`scripts/selfhost-lsp-diff.sh`、`scripts/selfhost-prev-diff.sh`、Core golden review、formatter 与
`scripts/doc-check.py`。A 刀若 LSP/prev 任一字节变化直接返工；D 刀才 review 是否需要 `lsp` 声明。

## 9. Residuals 与明确不做

- **Maven/lock 留在 selfhost。** `SourcePlan` 只给 coordinates；网络、artifact bytes 与 lock I/O
  不进入 Java-free planner，`ProjectPlan` 也不缓存 jars。
- **保留 build/run/test re-exec。** emitter 与 comptime FFI 仍查 system loader；删除 re-exec
  必须先把这些消费者也 loader-parameterize，并另做行为合同。
- **re-exec TOCTOU 后续处理。** parent 规划 classpath、child 再规划 source 的时间窗仍在；本轮
  check/doc/LSP 可做到单进程 captured plan，不借此冒称 build/run/test 已有 invocation snapshot。
- **不做 T2 checker cache。** `analyze_program` 的全局 ID 连续分配，`ModExports` 又携带完整 ID
  表；没有先证明 identity 可稳定复用前，缓存 checked module 会制造错绑。本文没有性能目标。
- **不做 `PlanStamp`/fingerprint。** 首轮允许 workspace 创建时重新 walk；正确性完成后再测，
  不能用未实测的性能断言倒逼缓存设计。
- **不做异步 generation/cancellation。** 当前同步 server 没有 stale-result race；需要并发时另案。
- **不让 completion 数据污染 `QCx`。** module index 是 completion 请求的显式参数，不属于 hover、
  definition 等通用 typed query context。
- **不改增量 text sync、文件 watcher或协议 framing/lifecycle。** 它们与本轮正确性边界独立。
- **不更新审计 fixed 状态。** TOOL-05/06 只有在 A-D 全部实现、负控打红、门禁通过后才能关账。
