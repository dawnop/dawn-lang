# LSP workspace 与目标级 Java classpath 设计（TOOL-05/06）

> 状态：**current / implemented**。A（`10b3052`）、B（`7eb2f25`）、C（`9f914d4`）与
> D（`18fb3d6`）均已实现；TOOL-05 与 TOOL-06 据此标记为 **fixed**。D 的本地 18×18
> 行为合同已通过；远端 [CI run 31337782587](https://github.com/dawnop/dawn-lang/actions/runs/31337782587)
> 为 **11/11 success**，其中独立 `lsp-workspace` job 用时 3m10s。

## 1. 收口范围

旧 v0.60 草案把 workspace、framing、lifecycle、两套依赖图、缓存和 classloader 混在一起。
最终实现只关闭下列相互依赖的边界，不重开已经定稿的协议问题：

| 条目 | 当前状态 | 最终边界 |
|---|---|---|
| TOOL-05 | **fixed** | 同一 canonical `(project, source_root)` 只有一份 captured plan、live overlay 集合、共享 `Program`、诊断贡献与 target lease |
| TOOL-06 | **fixed** | JVM `check`、`doc` 与 LSP 都按 target 的最终 `SourcePlan` 使用隔离 Java classpath；native 保持显式 refusal |
| TOOL-07 | fixed | 共享 Dawn framing 层限制 8 KiB header、64 MiB body；见 [lsp-framing-design.md](lsp-framing-design.md) |
| TOOL-08 | fixed | `server.Lifecycle` 实现 initialize/shutdown/exit 状态机 |
| TOOL-10 | fixed | Java-free `compiler-plan.SourcePlan` 统一 manifest、MVS、最终 source 图与 Java 坐标；见 [source-plan-design.md](source-plan-design.md) |

四刀的责任边界如下：

| 刀 | 提交 | 实现 |
|---|---|---|
| A | `10b3052` | `ProjectPlan`、captured loader 与 captured completion seam |
| B | `7eb2f25` | `JsigLease`、platform-parent target loader 与显式 loader 查询 |
| C | `9f914d4` | JVM `check`/`doc` 按 target fetch、校验、使用并关闭 Java lease |
| D | `18fb3d6` | LSP 共享 workspace、target lease、失败态、诊断聚合、关闭回滚与完整行为合同 |

## 2. 三层所有权

三层只允许向上组合，不复制下层事实。

### 2.1 `compiler-plan.SourcePlan`

`SourcePlan` 独占：

- 显式 `ProjectDirectory` / `SourceFile` target；
- manifest 校验、源码包 fetch、MVS 与最终 `PkgR`；
- `project`、`source_root`、Java coordinates 与全部 planner diagnostics。

Maven artifact fetch、`dawn.lock` 校验、Java 对象和 classloader 不进入 `compiler-plan/`。
当 planner diagnostics 非空时，LSP 不触发 Maven/网络；它仍创建 zero-jar target lease，继续
`load_entries_over` / `analyze_program`，由 `Program.diags` 原样携带并发布全部 planner diagnostics。
这些诊断不是 `Unavailable` setup failure，也不能被压成一条。

### 2.2 selfhost `ProjectPlan`

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

`project_files` 是稳定排序的项目 source-tree walk；`by_use` 只含合法、非 `std` 的 module path。
`load_entries_over(plan, entries, overlay)` 只消费 captured plan，不在内部重新规划。LSP workspace
因此能在会话内固定 source graph、module index 与 Java coordinates，避免按键时重读 manifest。

### 2.3 LSP identity、`Doc` 与 `Workspace`

文件模式下，同一 project 可以产生不同 `source_root`。例如 `app/rogue.dawn` 的 source root
可能是 `app/`，而 `app/src/main.dawn` 的 source root 是 `app/src/`；只按 project 建 key 会让
打开顺序决定两个文档共享哪张图。因此最终 workspace identity 是 canonical：

```text
(canon(plan.source.project), canon(plan.source.source_root))
```

两部分分别用“十进制长度 + `:` + 原值”编码后连接，形成无碰撞的 opaque `lookup_key`。
`lookup_key` 只用于 `LspState.workspaces` 查表，**绝不解释为文件路径**。真实 canonical
`source_root` 单独保留，供 definition 的文件系统边界判断使用；查表 identity 与 filesystem
boundary 是两个不同概念。

```dawn
type WorkspaceIdentity = {
  source_root: String,
  lookup_key: String
}

type DocAnalysis =
  | Standalone(prog: Program, entry: String, modules: Option[Map[String, String]])
  | WorkspaceMember(identity: WorkspaceIdentity)
```

`Doc` 只保存 URI/path、canonical path、live `text`/`SourceView`/line starts 与上述身份。
只有 standalone 文档私有持有 `Program`；workspace member 不复制 plan、Program、entry 或 lease。

```dawn
type Workspace = {
  plan: ProjectPlan,
  path_by_uri: Map[String, String],
  prog: Option[Program],
  entry_by_uri: Map[String, String],
  lease: JsigLease,
  diag_by_uri: Map[String, List[Json]]
}

type UnavailableWorkspace = {
  plan: ProjectPlan,
  path_by_uri: Map[String, String],
  problem: LocDiag,
  diag_by_uri: Map[String, List[Json]]
}
```

`Workspace` 不持久保存 overlay。每次 rebuild 都以 `Doc.text` 为唯一 live-text 权威，现场构造
完整 overlay；这样不存在 `Doc.text` 与第二份缓存漂移。`WorkspaceSlot` 有两种显式状态：

- `Ready(workspace)`：target setup 成功。正常时 `prog = Some(...)`；duplicate canonical path
  冲突时保留同一 lease 和成员，但把 `prog` 置为 `None`，表示 fail-closed conflict snapshot。
- `Unavailable(workspace)`：Maven、lock 或 loader factory setup 失败，只有一条已定位的
  `LocDiag`；buffer 与 formatting 保留，所有语义查询不可用，也没有旧 `Program` 或 fallback loader。

## 3. Workspace 成员与 captured-plan 刷新

### 3.1 `didOpen` 与身份定位

- 新本地 URI 可以执行一次 fresh `project_plan(SourceFile(path))`，用它确定 canonical
  `(project, source_root)` identity。
- 只有以 `.dawn` 结尾且 `project_module_path` 合法的本地文件能成为 workspace member。
  extensionless 小写文件即使位于项目内也保持 standalone，不能被误认成合法 module。
- 非 `file:` URI、非法 module path 与其他不能形成项目成员身份的 buffer 保持 standalone。
- identity 已存在时，新 plan 只用于定位并立即丢弃；成员使用 workspace 已捕获的 plan 与 lease。
  若该 slot 是 `Unavailable`，新成员是允许重试 setup 的低频边界，但仍使用旧 captured plan。
- 同一 project、不同 source root 必须落入不同 `lookup_key`；两个打开顺序都产生相同隔离结果。

### 3.2 `didChange`、`didSave` 与 manifest 更新

已有 `WorkspaceMember` 的 `didChange` 不 replan、不 fetch、不调用 host factory。Ready workspace
只重建语义快照；Unavailable workspace 只更新 buffer/view 和诊断映射，保持 fail closed，避免每次
按键触发网络重试。

`didSave` 是 Unavailable 的显式 setup 重试点，但它仍使用 captured plan。保存可以重试 lock 或
瞬态 Maven/loader failure；它**不会**读取新的 `dawn.toml` 并替换 source graph。修改 manifest 后，
必须关闭该 identity/source root 的全部文档，再 reopen 一个文档，才会 fresh plan。未来若增加
显式 refresh，也必须先完整构造新 plan/lease，再原子替换，最后关闭旧 lease。

### 3.3 Duplicate canonical path conflict

一次 rebuild 按 URI 稳定排序成员，在写入 overlay 之前比较 canonical path 对应的全部 live text。
两个 URI 若归一到同一路径且文本不同：

- 不选择排序靠后的文本，不安装 last-wins overlay；
- 丢弃旧 `Program`，语义查询返回空结果；
- 向冲突 URI 发布定位在各自 live view 的诊断；
- 文本恢复一致或其中一个 URI 关闭后，下一次 rebuild 自动恢复 Ready program。

## 4. 一次 workspace rebuild

每次 settled update 对一个 identity 执行固定流程：

1. 按 URI 稳定排序所有成员，从 `path_by_uri` 与各自 `Doc.text` 构造完整 overlay、entries 与
   `entry_by_uri`；冲突检查先于 `Map` 覆盖。
2. 无冲突时恰好一次调用 `load_entries_over(ws.plan, entries, overlay)`，再恰好一次调用
   `analyze_program(..., ws.lease.jsig)`，形成该 workspace 的唯一 `Program`。
3. `load_entries_over` 把 `plan.source.diags` 放进加载结果，因此一次分析会保留全部 planner
   diagnostics；它们不会因 Maven 被跳过而消失。
4. 新 `Program`、entry map 与诊断完整形成后一起替换 workspace；所有 completion、hover、
   definition、documentSymbol 等查询都经统一 `analysis_of` seam 取得同一快照。

completion 的 module 候选以 captured `plan.modules.by_use` 为基线，先删除当前 entry，再补入
其他 live entries。另一个 duplicate URI 若 entry 与当前文档相同，也不得把当前 module 插回；
其余尚未落盘的合法 live module 会被补入，无需重跑 planner。

当前 server 保持同步 debounce，不引入 generation、异步 task 或 cancellation。Slice D 先保证
语义世界唯一且可预测，不承诺增量 checker 性能。

## 5. Definition 与 source-root 边界

`analysis_of` 同时返回 opaque workspace lookup key 与真实 `definition_root`：

- lookup key 只选择当前 workspace slot；
- definition root 只判断目标 canonical path 是否位于当前 source root；
- 目标属于该 root 且在同一 workspace live-open 时，definition 使用目标文档的 live
  `SourceView` 和 line starts；
- 目标不属于该 root、目标只在另一 identity 打开，或当前分析是 standalone 时，一律读磁盘，
  不遍历全局 `st.docs` 借用别人的 live world。

这个分离同时阻止两类泄漏：编码 key 被误当路径，以及同一 project 的不同 source root 互相
借用 live definition。

## 6. Diagnostics 所有权与聚合

每个 Ready/Unavailable slot 保存自己对 `URI -> diagnostics` 的贡献。一次 install、rebuild、
恢复或关闭会对“旧贡献 URI ∪ 新贡献 URI ∪ 相关 open/closed URI”发布结果，包括显式空数组。
range 始终用诊断目标文档自己的 live view；未打开的 manifest、lock 或 dependency 文件按磁盘
内容定位。

发布前，server 会稳定遍历**全部 workspace**，聚合同一 URI 的所有贡献。撤销一个 root 只删除
该 root 的 contribution，再发布其余聚合结果；不能因为两个 workspace 都指向同一个
`dawn.toml`、`dawn.lock` 或 dependency file，就由先关闭者把后者诊断清空。

Maven/lock/loader setup failure 由 JVM host 转为 `LocDiag`：manifest/factory 错误定位
`dawn.toml`，lock 错误定位 `dawn.lock`。`Unavailable.problem` 只承载这类单项 setup failure；
planner 的多条 source diagnostics 仍走正常 zero-jar analysis 路径。

## 7. Target-scoped `JsigLease`

### 7.1 B：隔离 loader

Java-free `check/jsig.dawn` 公开：

```dawn
pub type JsigLease = {
  jsig: Jsig,
  close: fn() -> Unit !io
}

pub fn jsig_for(jars: List[String]) -> JsigLease !io
```

JVM `jsig_for` 使用 platform parent：target 能看见 JDK classes，但看不见编译器 application
classpath。显式 loader 版本的反射查询绑定同一 loader；两个含相同 FQCN、不同 API 的 target
可以并存而不串类。已有 build/run/test emitter 与 comptime FFI 仍保留 system-loader 路径，
因此本轮不删除其 re-exec。

### 7.2 C：`check` / `doc`

JVM `check`/`doc` 对每个 target 只规划一次，以同一 captured plan：

1. `load_planned(plan)` 加载 source；
2. `fetch_checked` 解析 Maven artifacts 并校验 `dawn.lock`；
3. `jsig_for(jars)` 构造 target lease；
4. 在 bracket 内只运行 `analyze_program`；
5. 关闭 lease 后再 render、print 或 exit。

多 target `check` 不合并 jars。Maven/lock/loader setup failure fail closed；native `check`/`doc`
继续 `jsig_refused()`，不 import Maven/Coursier/JVM reflection。selfhost 的固定 ASM bridge 只在
target loader 能解析 ASM 时叠加数据签名，不能借 system loader 泄漏宿主 ASM。

### 7.3 D：显式 LSP host factory

共享 Java-free server 接收：

```dawn
pub type LspLeaseHost = {
  standalone: fn() -> JsigLease !io,
  project: fn(source.SourcePlan) -> Result[JsigLease, LocDiag] !io
}
```

- JVM project factory 使用 `fetch_checked` + `jsig_for`；`jsig_for` 的宿主/I/O failure 由
  `catch_fault` 转为 `dawn.toml` 诊断，compiler invariant panic 不会被降格成用户错误。
- planner diagnostics 非空时 factory 跳过 Maven/网络，以 `jsig_for([])` 继续分析并发布全部
  planner diagnostics。
- JVM standalone 在 server lifetime 内共享一份 `jsig_for([])` lease；可见 JDK，不可见
  编译器 ASM/Coursier。native standalone/project 都返回 `jsig_refused_lease()` no-op lease。
- setup 先完整构造 lease，再安装 workspace。首次 rebuild 若 unexpected panic，关闭尚未安装的
  lease 后重新 panic，不把半成品留在 state。

## 8. 关闭、回滚与异常退出

`didClose` 先移除 URI 与 `Doc`，再处理所属 slot：

- 还有成员时，以剩余 `Doc.text` 重建；被关闭 buffer 不再进入 overlay，依赖读取其磁盘版本，
  未落盘文件则正常产生缺失模块诊断；
- 最后一个成员关闭时，先从 state 删除 workspace 并发布聚合后的清空/剩余诊断，再关闭 lease；
- Unavailable 没有 lease，关闭只撤销其诊断贡献；全部关闭后 reopen 会 fresh plan。

shutdown request、正常/异常 `exit`、EOF 与 fatal framing 都执行 `close_all_leases`。单个
`lease.close` 由 `catch_panic` 隔离并记录错误，不能阻止其他 workspace 或 standalone lease
继续关闭；state 随后清空所有 lease ownership，shutdown 后再 exit 不会重复关闭。

## 9. 18 例 × 20 mutant 行为合同

`scripts/lsp-workspace-contract/` 在私有 selfhost 副本上运行 18 个真实 JSON-RPC 正例，并为
每个边界编译一个 mutant，共 20 个：`diagnostics-current` 与 `did-close` 各拥有两个，其余一
例一个。每个 mutant 必须先编译成功，再只运行 owning case；只有出现该 case 唯一的 failure
label 才算负控见红，build failure、timeout、协议错误或无关 assertion 都不算。

18 个正例覆盖：

- 全 live overlay、未落盘模块、当前模块 completion 自排除；
- extensionless 本地 buffer 保持 standalone；
- 同一 project 的不同 source root 按两种打开顺序隔离，definition/module resolution 均不串；
- close rollback、duplicate canonical path conflict、root-scoped definition；
- 当前 URI、空数组与各自 live source view 的全量 diagnostics；
- 多 root external-diagnostic aggregation；
- 同 FQCN Java target 按两种打开顺序隔离；
- standalone classpath 隔离；
- last close、shutdown、running exit、EOF、fatal framing 与 injected close failure 的 cleanup；
- Unavailable 在 `didChange` 不重试、在 `didSave` 才重试。

对应 18 个 compiling mutants 包括退化为 project-only identity。该 mutant 由
`source-root-identity` case 的唯一 `SOURCE_ROOT_WORKSPACE_MERGED` assertion 定向打红；合同不只
计数 lease，还验证两侧 diagnostics、definition 与 module resolution。

## 10. Residuals 与明确不做

下列边界不把 TOOL-05/06 重新标成 open：

- **symlink/case-fold identity。** 当前 `canon` 只做绝对化与词法 `.`/`..` 归一，不解析 symlink，
  也不做平台 case-fold；duplicate conflict 只能覆盖当前 canonical 定义识别出的同一路径。
- **manifest refresh。** `didSave` 只重试 captured plan 的 lock/瞬态 setup；修改 `dawn.toml` 后
  必须关闭该 root identity 的全部文档再 reopen，才会 fresh plan。
- **传递 Java 坐标来源。** manifest 语法合法、但 resolver 在传递 Maven coordinate 上失败时，
  setup diagnostic 仍可能只定位根 `dawn.toml`，尚不能精确指出贡献该坐标的 dependency manifest。
- **已安装 workspace 的 unexpected panic。** 新 lease 在安装前 rebuild panic 会显式关闭；若
  已安装 workspace 的后续 rebuild 遇到 compiler invariant panic，当前依赖进程退出后的宿主资源
  回收，未建立可恢复的逐 workspace unwind 协议。
- **不做 checker cache。** `analyze_program` 的全局 ID 与 `ModExports` identity 尚未证明可稳定
  复用；Slice D 接受每次 settled update 的全 workspace 重分析成本。
- **不删除 build/run/test re-exec。** emitter 与 comptime FFI 仍查 system loader；跨进程
  plan snapshot 与 TOCTOU 另案处理。
- **不改 framing/lifecycle、增量 text sync、文件 watcher 或并发 cancellation。** 这些边界与
  本轮 workspace 正确性独立。

截至 `18fb3d6`，A-D 的实现、18×18 行为负控、clean-checkout 重建与远端 11/11 CI 已共同关闭
TOOL-05/06。
