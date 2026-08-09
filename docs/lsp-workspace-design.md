# LSP workspace 与目标级 Java classpath 设计（TOOL-05/06）

> 状态：**proposed / open**。本批基于 `62715aa`。A（`10b3052`）与 B（`7eb2f25`）已实现并
> 推到 `origin/main`，包含两刀的远端 CI 全绿；C 由本批实现，D 尚未实现。本文只覆盖仍开放的
> TOOL-05 与 TOOL-06，不能因前三刀落地就把任一条标成 fixed。

## 1. 范围与已完成前置

旧的 v0.60 草案把 workspace、framing、lifecycle、两套依赖图、缓存和 classloader 混成一批。
当前代码已经换了地基，执行范围必须收窄：

| 条目 | 当前状态 | 与本文的关系 |
|---|---|---|
| TOOL-07 | 已完成 | `server.read_message` 已在共享 Dawn 层限制 8 KiB header、64 MiB body，并在不可重同步时终止读循环；见 [lsp-framing-design.md](lsp-framing-design.md) |
| TOOL-08 | 已完成 | `server.Lifecycle` 已实现 initialize/shutdown/exit 状态机 |
| TOOL-10 | 已完成 | [source-plan-design.md](source-plan-design.md) 已把 manifest、MVS、fetch、最终 source 图与 Java 坐标统一进 Java-free `compiler-plan.SourcePlan` |
| TOOL-05 | open | A 已建立 captured-plan seam；D 的共享 workspace、全 overlay 与全量 diagnostics 尚未实现 |
| TOOL-06 | open | B 已提供 target-local lease，C 已把 `check`/`doc` 接到各自 target classpath；D 的 LSP 接线尚未实现 |

本文不重开前三项；TOOL-05/06 仍须等 D 的 workspace/LSP 边界落地后才能标成 fixed。

| 刀 | 状态 | 已落地或待完成的边界 |
|---|---|---|
| A | **implemented，`10b3052`，远端全绿** | `ProjectPlan`、captured loader、captured completion；行为与输出差分均通过 |
| B | **implemented，`7eb2f25`，远端全绿** | `JsigLease`、platform-parent loader、显式 loader 查询；行为与输出差分均通过 |
| C | **implemented in this batch** | JVM `check`/`doc` 按 target 获取、校验、关闭 Java lease |
| D | **not implemented** | LSP 每 root 共享 snapshot、lease、diagnostics 与关闭回滚 |

## 2. 当前实现证据

以下事实均按本批工作树的源码符号重新核对，不沿用旧草案行号。

1. `compiler-plan/src/source.dawn` 已公开显式的 `SourceTarget` 与唯一 `SourcePlan`；后者持有
   `project`、`source_root`、最终 `PkgR`、`java_coords` 与规划诊断。`compiler-plan/dawn.toml`
   只有 `fspath`、`sha2`、`inflate` 三个源码依赖，没有 `[java-deps]` 或 `use java`。
2. A 已在 `driver/analyze.dawn` 落地 `ModuleIndex`、`ProjectPlan`、`project_plan` 与
   `load_entries_over`。兼容 loader 会 fresh plan，但 captured loader 只有 plan 入参，不能静默
   重读 manifest；`analyze_document_planned` 把实际 plan 交给 LSP。
3. A 也已让一次 `use` completion 显式消费同一张 `plan.modules.by_use`；`path_items` 与
   `import_items` 不再自行规划。只有 standalone/fallback 的 `None` 分支仍会调用一次
   `use_candidates`，通用 `lspq.QCx` 没有增加 completion-only 字段。
4. `server.dawn` 的 `Doc` 现在同时保存 `Program`、`entry`、`plan`；每个查询仍经 `doc_qcx`
   读取自己的私有快照。`update_doc` 只分析当前 buffer、只发布当前 URI；`didClose` 只删当前
   `Doc` 并清空该 URI，没有让其他文档按磁盘回落后重分析。
5. `analyze_document_planned` 仍以“文本里是否出现小写 module `use`”决定 project/standalone，
   project 分支也仍只构造 `{当前 canonical path -> 当前文本}` 的单元素 overlay。因此没有 `use`
   的合法 `lib.dawn` 不会把 unsaved export 提供给 caller，其他 open buffer 仍从磁盘读取。
6. `location_of` 仍遍历全局 `st.docs` 寻找 canonical path；它没有 workspace root 过滤，会把另一
   root 的 live buffer 当作当前 project 的 definition source。
7. B 已在 Java-free `check/jsig.dawn` 落地 `JsigLease`，并在 `jvm/jreflect.dawn` 将八类查询拆成
   显式 loader 版本。`jsig_for(jars)` 使用 platform parent；原 `jsig_real()` 与直接 wrapper
   仍使用 system loader。C 已让 `main.dawn` 的 `check`、`doc` 消费 target lease；`lsp` 尚未消费，
   `LspState` 也仍只有一份全局 `Jsig`。
8. `pkg/maven.dawn` 直接使用 `coursierapi.*`；C 已在 `selfhost/dawn.toml` 显式声明
   `io.get-coursier:interface:1.0.28`，使 selfhost 的 platform-parent target loader 不依赖
   compiler application classpath 泄漏 Coursier。
9. build/run/test 的 re-exec 暂时仍有生产消费者：`jvm/emit.dawn` 在 varargs component 与
   interface 判断处直接问 `jreflect`，`jvm/jfold.dawn` 的 comptime Java FFI 也直接反射。
   因此“checker 有 target loader”不能推出“可以删除 re-exec”。
10. `driver/analyze.canon` 只是 `fspath.absolute`：绝对化后做词法 `.`/`..` 归一，不解析 symlink，
    也不做 case-fold。D 的 identity 与冲突检测先沿用这一定义，更强的文件身份留作 residual。

现有 `server.dawn` 关于“编辑器中的 `use java` 与 compile 完全一致”的注释与当前宿主 wiring 冲突；
D 落地时应一起改正，不能继续把 system classpath 当作 target classpath。

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

只有 `Workspace` 持有 project 会话活状态：一个 root 的全部 open-buffer overlay、一份共享
`Program`，以及一份 target-scoped `JsigLease`。不同 canonical root 的所有这些值完全隔离。

```dawn
type DocAnalysis =
  | Standalone(
      prog: Program,
      entry: String,
      modules: Option[Map[String, String]]
    )
  | WorkspaceMember(root: String)

type Doc = {
  uri: String,
  path: Option[String],
  canonical_path: Option[String],
  text: String,
  view: SourceView,
  ls: List[Int],
  analysis: DocAnalysis
}
```

这是 D 的所有权接缝，不是给同一份结果起两个名字：只有 `Standalone` 持有私有
`Program`/`entry`；`WorkspaceMember(root)` 必须经 `root` 找到 workspace 的共享 `Program` 与
`entry_by_uri`。`Standalone.modules` 只服务 completion：非文件 URI 为 `None`，非法 module path
回退时可以保留定位过程中捕获的 module index。`Doc` 本身不再持有 project `Program`/`entry`，
也不复制 workspace plan。

```dawn
type Workspace = {
  plan: ProjectPlan,
  path_by_uri: Map[String, String],
  overlay: Map[String, String],
  prog: Program,
  entry_by_uri: Map[String, String],
  java: JsigLease,
  published_external_diag_uris: Set[String]
}
```

`LspState.workspaces: Map[String, Workspace]` 的 key 就是 canonical project root，记录内部不再
重复 `key`。`path_by_uri` 明确表示 URI -> canonical path；传给 loader 的 entry path 列表按稳定
URI 顺序从它派生，不能再用含糊的 `entries` 同时表示两件事。`published_external_diag_uris`
记录上次实际发布过 planner、manifest、Maven、lock 等 project diagnostics 的 URI，供恢复或
关闭时逐个发送空数组。JVM `LspState` 另持一份 server-lifetime zero-jar standalone lease；
native 对应位置持有 no-op 的 refused lease。

## 4. A（已实现）：captured-plan seam

A 在 `10b3052` 建立了可复用边界，但没有宣称修复 TOOL-05/06。

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

已落地边界：

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

A 的 captured-plan、loader mutant 与 completion mutant 合同已通过；`selfhost-lsp-diff.sh`、
`selfhost-prev-diff.sh` 实测字节不变，Core review 只接受了 `driver.analyze`、`lsp.server`、
`lsp.lspc` 的预期 owner，包含该提交的远端 CI 已通过。

## 5. TOOL-06：`JsigLease`，不是进程 classpath

### 5.1 B 已验证并实现的构造路径

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

这些能力已在 B（`7eb2f25`）实现，无需新增 Dawn 语法、`URL[]` 表面类型、Java helper 或 seed
runtime helper。

### 5.2 B 已实现的 API

Java-free `check/jsig.dawn` 已增加生命周期记录，JVM 实现在 `jvm/jreflect.dawn`：

```dawn
pub type JsigLease = {
  jsig: Jsig,
  close: fn() -> Unit !io
}

pub fn jsig_for(jars: List[String]) -> JsigLease !io
```

`jreflect` 已把八类查询拆成显式 loader 参数的内部函数；`jsig_for` 的闭包捕获同一 loader。
既有 `jsig_real()` 与直接 `jreflect` wrapper 继续走 system loader，供仍依赖 re-exec 的
build/run/test emitter 与 comptime FFI 使用。B 的 owning contract 已证明双 JAR 同 FQCN 隔离、
platform parent 不泄漏 application classpath、正常/异常关闭；五个 compiling mutant 均已打红。

### 5.3 C：`check` / `doc` target wiring（本批实现）

C 补出 plan-aware loader，避免 source load 与 Java coordinates 各自规划：

```dawn
pub fn load_planned(plan: ProjectPlan) -> LoadResult !io
```

它按 `plan.source.target` 保持现有 directory/file 语义，只消费已捕获的 plan。directory target 的
`src/` 不存在拒绝必须仍发生在 `project_plan` 之前，不能因引入 helper 而先解析 manifest 或抓包。

`pkg/maven.dawn` 保持 selfhost 所有权，可抽出一个不打印、不退出的 helper：

```dawn
pub fn fetch_checked(
  project: String,
  coords: List[MCoord]
) -> Result[List[String], String] !io
```

它完成 Coursier fetch 与已有 lock parse/hash/check，并保持 Coursier 返回的 JAR 顺序。不存在
lock 才表示“无 lock”；文件已存在但不可读、格式错误、hash drift 都是 `Err`。即使 `coords=[]`
也要拒绝已有 stale lock。helper 不打印、不退出；失败时 fail closed，绝不退回 system loader。

`selfhost/src/pkg/maven.dawn` 自己直接引用 `coursierapi.*`，所以 C 在
`selfhost/dawn.toml` 显式加入 `io.get-coursier:interface:1.0.28`，并同步更新 `selfhost/dawn.lock`。
这是真实 target dependency，不允许用 application parent 特判 selfhost，否则 TOOL-06 的隔离
定义会被编译器自身悄悄绕过。

selfhost 还直接导入编译器生成的 `dawn.rt.Asm` / `dawn.rt.AsmWriter`。target `Jsig` 只允许在
target loader 自己能解析 `org.objectweb.asm.ClassWriter` 时，为这两个固定类名叠加固定的纯数据
签名；不得查询 system loader、改用 application parent，或按 project name 特判。两类从
`Object` / `ClassWriter` 继承的方法与字段及其 assignability 仍通过 target loader 查询，不能复制
宿主 ASM 的反射结果。程序显式导入任一 bridge 时必须同时发射两个 bridge class，使通过检查的
target JAR 能独立链接；target 没有 ASM 时两个 bridge 都不可见。

JVM `check`/`doc` 对每个 target 的固定流程是：先完成 target 前置校验；只调用一次
`project_plan`；以 `load_planned(plan)` 加载；以同一 `plan.source` 调 `fetch_checked`；构造
`jsig_for(jars)`；在 `bracket` 内只运行 `analyze_program`；bracket 返回并关闭 loader 后，才允许
render、print、`fail_compile`、`fail_doc`、`cli_error` 或 `io.exit`。任何会退出进程的函数都不能
出现在 bracket body，因为 `System.exit` 不会替它执行普通 finally。

多 target `check` 逐 target 创建并关闭 lease，不合并 jars。Maven/lock/loader setup failure
fail-fast，退出码为 1；普通源码 diagnostics 仍在所有 target 的 lease 都关闭后聚合报告。成功的
`check`/`doc` 不新增 dependency progress 输出。native `check`/`doc` 继续使用
`jsig_refused()`，不 import Maven/Coursier/jreflect，也不创建 loader。

### 5.4 D：LSP 宿主边界与生命周期（未实现）

共享的 `lsp/server.dawn` 不能 import Java-backed Maven/jreflect。`run_lsp` 改为接收宿主提供的
“`SourcePlan` -> Result[JsigLease, String]`”工厂：JVM main 用 `fetch_checked` + `jsig_for`，
native main 返回 target-local 的 `jsig_refused()` no-op lease。这样 server 仍是零 `use java` 的
共享前端，fetch/lock 失败也能成为 project diagnostic，而不是伪造一份可用 lease。

- LSP 每个 workspace 独占一份 lease。新 workspace 先完整构造 plan、jars 与 lease，成功后才
  安装；构造失败发布 project diagnostic，不安装半成品。D 不自动替换已有 root 的 captured
  plan/lease；未来若增加显式 replan，才按“先建新值、原子替换、最后关闭旧 lease”执行。
- JVM standalone 文档统一使用一份 `jsig_for([])`：platform parent 允许 JDK classes，但看不见
  编译器 application classpath；native standalone 继续使用 `jsig_refused()`。standalone 不能
  退回 `jsig_real()`。
- 关闭最后一个 workspace 文档、正常 `exit`、EOF 与 fatal framing 退出都关闭对应 lease。
  server-lifetime standalone lease 也在这些退出路径关闭；关闭后不得再查询。
- 当前 server 同步执行，第一轮没有 close/query 竞态；未来若引入并发分析，必须另加引用计数
  或等待 in-flight query，不能复用本轮假设。

## 6. TOOL-05：workspace 正确性

### 6.1 成员资格与 captured root

- 每个合法本地 `file:` `.dawn` 文件都进入其 project workspace，**即使文本没有 `use`**。
  workspace 身份由 path、`ProjectPlan.source` 与合法 module path 决定，不再由内容启发式决定；
  这样未写 `use` 的 open `lib.dawn` 也能把 unsaved export 提供给 caller。
- 非 `file:` URI 保留 private standalone analysis；本地文件若不能产生合法 module path，也回退
  standalone，同时保留非法文件名/module path 诊断。两者都不得伪造 project workspace。
- 已有文档的 `didChange` 必须复用 `WorkspaceMember(root)`，不得重新规划。新 URI 可以调用一次
  `project_plan(SourceFile(path))` 来定位 canonical root；若 `st.workspaces` 已有该 root，fresh plan
  立即丢弃，继续使用旧 workspace 的 captured plan 与 lease。只有创建新 root 时才安装新 plan。
- 两个 URI 若归一到同一 canonical path 且 live text 不同，更新必须 fail closed：不按 URI 排序
  选择“最后一个”覆盖 overlay，不安装含歧义的新 snapshot，并向两个 URI 发布冲突诊断。文本
  恢复一致或其中一个关闭后再重建。

### 6.2 一次 workspace update

一次 settled update 对所属 workspace 执行以下固定流程：

1. 按 URI 稳定排序全部成员，从 `path_by_uri` 与各 `Doc.text` 构造完整 canonical path -> live text
   overlay；冲突检查必须发生在 `Map` 插入覆盖信息之前。
2. 以相同 URI 顺序派生 entry path 列表，恰好调用一次
   `load_entries_over(ws.plan, paths, overlay)`，再恰好调用一次
   `analyze_program(..., ws.java.jsig)`，形成唯一 `Program` 与 `entry_by_uri`；新 snapshot 完整成功
   后才原子替换旧 workspace。
3. 对该 workspace 的**每个** open URI 发布 diagnostics，包括空数组；每条 range 使用目标文档
   自己的 live `SourceView` 与 line starts，不能拿触发编辑的 buffer 或磁盘文本代算。
4. planner、manifest、Maven、lock 等 project diagnostic 发布到各自 external URI。每轮对“上轮
   `published_external_diag_uris` ∪ 本轮 URI”稳定遍历，没有新诊断的 URI 也发送 `[]`，再把集合
   更新为本轮实际非空集合；manifest 没打开不等于可以静默丢失或永不清理。

旧 `ModuleIndex` 不会包含尚未落盘的新文件。completion 候选必须以
`ws.plan.modules.by_use` 为基线，再把 live `entry_by_uri` 对应的 `path_by_uri` 补入；不能因为
文件不在 captured tree walk 中就让 `use new_module` 的 completion 永久缺席，也不能为补它重跑
planner。

### 6.3 查询、关闭与 root 隔离

查询先经统一 `analysis_of(st, doc)`：`Standalone` 读取自身 `Program`/`entry`，
`WorkspaceMember(root)` 读取 `st.workspaces[root].prog` 与当前 URI 的 `entry_by_uri`。completion、
hover、symbols 与 definition 不再绕过这条所有权接缝。

`location_of` 查 live definition 时只遍历**同一个 root 的成员**。目标 path 不属于本 workspace 的
live doc 时读取磁盘，禁止遍历全局 `st.docs`；即使另一个 root 恰好打开了同一 canonical path，
也不能借用其 live `SourceView`。

`didClose` 先移除该 URI 的 `path_by_uri`、overlay 与成员关系，再按剩余成员重建 workspace：若
关闭的 unsaved 文件仍被其他 open doc 引用，loader 回落磁盘；若文件从未落盘，则正常产生缺失
模块诊断。随后清空已关闭 URI，重发所有剩余 URI，并按上一节清理 stale external diagnostics。
最后一个成员关闭时，先清空全部 `published_external_diag_uris`，再关闭 lease、删除 workspace。

多 root 以 canonical project root 为外层 map key。overlay、Program、module index、diagnostics 与
loader 均不得跨 root 查询；两个 root 即使 module path 或依赖 FQCN 相同，也必须得到各自答案。

第一轮继续使用现有同步 debounce。**不加** `gen`、异步 task 或 cancellation：没有并发分析，
就没有旧 generation 覆盖新结果的竞态。workspace correctness 先求答案一致，不承诺增量性能。

## 7. 分刀顺序与输出纪律

| 刀 | 状态与 API/行为边界 | 主要门禁与负控 | 输出结论或裁决规则 |
|---|---|---|---|
| A | **已实现 `10b3052`**：`ProjectPlan`、captured loader、Doc 暂存 plan、completion 显式复用 module index | captured-plan contract；fresh replan loader 与 fresh completion mutants 均已打红 | LSP/prev 实测字节不变 |
| B | **已实现 `7eb2f25`**：`JsigLease`、platform-parent loader、loader-parameterized reflection | system query/parent、合并 loader、drop close、bypass bracket 五类 mutants 均已打红 | LSP/prev 实测字节不变 |
| C | **已实现（本批）**：同一 captured plan + `load_planned` + `fetch_checked` + bracketed lease；target ASM 条件式固定 bridge overlay 与成对发射；native refusal 不变 | check/doc target deps；多 target 同 FQCN；with-ASM/no-ASM、linked JAR、drop-overlay；system leak、合并 lease、跳 lock、绕 bracket mutants | 无预授权；先跑差分并逐项 review |
| D | **未实现**：完整 overlay、单一 Program、每 root lease、全量发布、didClose rollback | unsaved export/new module、root definition、duplicate URI、standalone zero-jar、全 diagnostics | 无预授权；先跑差分并逐项 review |

每个 mutant 必须先成功构建，再由 owning contract 精确打红；grep 只能补结构边界，不能替代行为
负控。任何输出差异声明都只能在门禁和人工 diff review **之后**按闭集 label 写，本文不提前
放行 C/D 的任何输出变化。

## 8. 验收矩阵

| 合同 | 正例 | 必红变异 |
|---|---|---|
| captured plan | 先规划 alias -> 包 A，再把磁盘 manifest 改成包 B；old plan 仍加载 A，fresh wrapper 加载 B | `load_entries_over` 内重跑 `project_plan(plan.source.target)` |
| captured completion | didOpen 后改磁盘 manifest；当前 Doc 的 `use alias/module.{` 仍列旧包导出，新会话列新包导出 | 忽略显式 module index，恢复 fresh `use_candidates` |
| loader 隔离 | system loader 看不见 fixture；两份 target lease 对相同 FQCN 分别看到 A/B API | 改回 system loader；或把两个 target 合并进一份 loader |
| loader 释放 | 正常 close 与异常 bracket 后，JAR 独有 resource 都不可见 | 删除 `close`；让异常路径绕过 bracket |
| check/doc target classpath | 带 `[java-deps]` 的 check/doc 成功；同一次 multi-target check 的同 FQCN 不串；malformed/hash drift/stale/unreadable lock 均退出 1 | 改回 `jsig_real()`；循环外共享 lease；跳过 lock；在 bracket 内 exit |
| selfhost ASM bridge | target 带 ASM 时两 bridge 可检查，导入任一 bridge 都发射两类且独立 JAR 可链接运行；target 不带 ASM 时两者都不可见 | 删除条件式 bridge overlay，with-ASM case 精确丢失两 bridge；或无条件 overlay 使 no-ASM case 错误通过 |
| unsaved export | 两文档都 open；只在被依赖 buffer 改 `pub` 名，依赖方立即按 live 文本重新诊断/补全/definition | overlay 退回单元素，或仍从各 Doc.Program 查询 |
| 新建未落盘模块 | 新 open `new_module.dawn` 尚未落盘且没有 `use`；caller completion 立即列出 `new_module` 与 live exports | completion 只读 captured `plan.modules.by_use` |
| didClose rollback | 关闭未保存的被依赖文件后，剩余文档按磁盘版本重分析 | 只删 Doc/清 diagnostics，不重分析 workspace |
| 全量 diagnostics | 一次 edit 后所有 open URI 都收到最新数组，含 `[]`；不同换行与 astral 字符的 range 各用自己的 live view | 只发当前 URI、跳过空数组，或所有 range 复用触发文档 view |
| external diagnostics | manifest/Maven/lock 错误发布到对应 URI；恢复与最后关闭都显式发 `[]` | 不记录已发布 external URI，恢复后遗留旧诊断 |
| root-scoped definition | A 的 definition 指向共享 dependency 的磁盘文件；同一 canonical path 在另一 root 以不同 live text 打开，A 仍按 A root 的成员或磁盘算位置 | `location_of` 恢复遍历全局 `st.docs` |
| 多 root | 两 root 的 overlay、Program、diagnostics 与同 FQCN Java API 互不泄漏，两个打开顺序都正确 | workspace key 退回全局值，或所有 root 复用首个 lease |
| duplicate canonical URI | 两 URI 映到同一 canonical path 且文本不同；两者收到冲突诊断，不安装 last-wins snapshot；关闭一个后恢复 | 按排序把后一文本写进 overlay |
| standalone zero-jar | JVM untitled buffer 可见 JDK class、看不见编译器自带 ASM/Coursier；native 对 `use java` 仍拒绝 | standalone 退回 `jsig_real()` 或 native 创建 JVM loader |

已完成的 A/B owning contracts、Core review、LSP/prev 差分与远端 CI 均通过。C 本批验收及 D 后续
落地时至少运行：
`./bin/dawn test selfhost`、`./bin/dawn test compiler-plan`、新 contract mutants、
`scripts/lsp-use-completion.py`、`scripts/lsp-lifecycle-contract/run.sh`、
`scripts/selfhost-lsp-diff.sh`、`scripts/selfhost-prev-diff.sh`、Core golden review、formatter 与
`scripts/doc-check.py`。差分出现任何字节变化都先查明 owner 与行为，再决定是否接受，不能从本稿
推导出预先批准的 label。

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
- **canonical identity 仍是词法 identity。** 当前 `canon` 不解析 symlink，也不做平台 case-fold；
  duplicate URI 的 fail-closed 规则只能覆盖现有 canonical 定义识别出的冲突。真实文件身份另案。
- **不让 completion 数据污染 `QCx`。** module index 是 completion 请求的显式参数，不属于 hover、
  definition 等通用 typed query context。
- **不改增量 text sync、文件 watcher或协议 framing/lifecycle。** 它们与本轮正确性边界独立。
- **不更新审计 fixed 状态。** TOOL-05/06 只有在 A-D 全部实现、负控打红、门禁通过后才能关账。
