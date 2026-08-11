# Dawn 代码库审查 v2：CLI、LSP、构建与发布

> 状态：**current** —— JVM/native 驱动、LSP、依赖规划、自举与发布链的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- 原审查中对用户最危险的 `dawn check` 假绿、`dawn fmt` 任意文件写回、LSP 文档级私有快照与
  LSP/`doc` 工程 classpath 缺失均已关闭；bootstrap cache generation 也已随 v2 stamp 闭合，
  当前默认接口风险只剩 manifest/lock 的原子写入。
- LSP 现有 debounce、URI/UTF-8 修复、跨后端共享前端、有界 framing、lifecycle state，以及按
  canonical `(project, source_root)` 共享的 captured plan、live snapshot、target lease 和诊断聚合。
- 原审查中的包/自举缺陷大多来自**一件事有两张图或两份身份**；source/Java graph、artifact
  identity、seed jar/std 与 gate/release recipe 已分别收口，当前只剩 manifest/lock
  原子写入。

## TOOL-01 — P1 — `dawn check` 有诊断仍退出 0（已修）

> **后续处置：已修。** 公开 `check` 现在以正常 renderer 输出聚合诊断并退出 1，clean target
> 输出 `ok` 并退出 0，usage/path/target 错误退出 2；机器可读、无论诊断都退出 0 的 golden dump
> 只保留在隐藏 `__check`。JVM 与 native driver 采用同一公开 verdict contract。

- **修复前证据：V。** 规范推荐 `dawn check` 守全仓 CI；当时公开 `check` 与隐藏 `__check`
  共用只输出 `D\t...` dump、没有失败出口的实现。
- **修复前最小复现：** 对确定的 return-inference diagnostics 执行
  `./bin/dawn check file.dawn`，stdout 有诊断而 shell exit status 仍为 0；`doc-check` 被迫解析
  dump 行判断成败。
- **当前实现：** `selfhost/src/main.dawn` 的 `run_check` 与 `run_checkdump` 已分离；
  `selfhost/src/nmain.dawn` 的 `cmd_check` 按同一 0/1/2 语义返回。
- **门禁：** `scripts/selfhost-run-diff.sh` 固定 clean、diagnostic、missing target 与 usage 的 verdict；
  `scripts/native-cli-diff.sh` 另以 clean/diagnostic/missing target 对拍 JVM 与 native，
  `scripts/doc-check.py` 的 compile fence 直接依赖公开 exit status。
- **结论：已修。** 第三方 CI 不再因类型或语法诊断假绿，machine dump 也没有与人类接口混用。

## TOOL-02 — P1 — `fmt` 会覆盖任意直接指定的文件（已修）

> **后续处置：已修。** JVM/native 的 direct-file 路径都先要求 `.dawn` 后缀；lexer 不能完整
> 读取的 Dawn 文件也只报告诊断，不进入写回。目录模式仍只发现 `.dawn` 文件，批处理中 lexer
> 拒绝不妨碍收集其余诊断并最终退出 1；target/path usage 拒绝保持 exit 2。

- **修复前证据：S。** help 声明 target 是 `.dawn`，目录扫描也过滤扩展名；direct file 却不检查，
  随后原地写回。`dawn fmt README.md` 因而会把 Markdown 交给 Dawn formatter 并覆盖原文件。
- **修复前影响：** 一次 path typo 就能破坏非源码文件；当时 lexer diagnostic 还可能被 formatter
  丢弃，非法字符会随重排消失。
- **当前实现：** `selfhost/src/main.dawn` 的 `run_fmt` 与 `selfhost/src/nmain.dawn` 的 `cmd_fmt`
  在读取前拒绝具名非 Dawn 文件，并只对 `fmt.format` 返回 `Ok` 的文本执行写回。
- **门禁：** `scripts/native-cli-diff.sh` 把非 `.dawn` 文件和 lexer 失败文件分别交给两个 driver，
  随后逐字节复核原文件未变；`scripts/selfhost-run-diff.sh` 的只读 `--check` verdict leg 固定同一拒绝。
- **结论：已修。** direct-file 与 directory mode 的安全边界一致，拒绝路径不会再损坏输入。

## TOOL-03 — P2 — `dawn run` 没有 compiler/program 参数边界（已修）

- **原证据：S。** JVM 依次用 `extract_cp`、`extract_ct_opts`、`extract_flag` 扫描完整 argv，确定 target 前就会吞掉同名程序参数；native 的通用 tail parser 则拒绝全部额外 positional。新增 compiler flag 会追溯性抢占旧程序 argv。
- **当前契约：** `dawn run [compiler-options] <target> [-- <program-args>...]`。无参数可省 `--`，显式 `run target --` 同样传空 argv；target 后若有 token，首个必须是分隔符。分隔符不转发，其后 token 包括空串与 option-like 字符串均逐字转发。完整理由见 [`run-argv-boundary-design.md`](../run-argv-boundary-design.md)。
- **实现：** JVM 使用专用一次顺序 parser，同时产出编译计划、target 与 program argv；dependency re-exec 只读取该计划，重启仍附回完整原始 rest。native 保留独立 parser，并把 `[bin] ++ program_args` 实际交给执行入口。
- **门禁：** `scripts/native-cli-diff.sh` 的独立 run absolute leg 分别钉 stdout、stderr 与 exit；覆盖空 argv 两式、target 前 compiler option、空串/option-like 原样透传，以及 target 后裸 token / flag-like token 的固定 usage 拒绝。两端共同接受非法输入也不能靠相等假绿。
- **结论：已修。** compiler option 只在 target 前生效，程序 argv 的名字空间不再被当前或未来的编译器 flag 抢占。

## TOOL-04 — P2 — JVM/native CLI 参数基数已经漂移（已修）

- **原证据：S。** JVM `doc` / `test` 拒绝第二个 target，native 却让末位覆盖；JVM `check` 接受 1..N，native 的通用 tail parser 只接受一个。旧门禁每例最多一个 positional，且只判断两端相等，无法发现两端共谋接受非法输入。
- **当前契约：** `check` 与 `fmt` 为 1..N；`test` 为单 target XOR `--stdlib`；`doc` 在单 target / `--stdlib` / `--builtins` 中恰选一项；`build`、`emitc` 恰一个 target。编译器 options 与 `run` 转发不在本刀内，完整理由见 [`cli-arity-design.md`](../cli-arity-design.md)。
- **实现：** 两个驱动各保留独立 argv plumbing，但分别集中使用单-target拒绝与 selector 计数 helper；native `check` 与 JVM 一样先验证全部路径、再聚合全部诊断。这样没有把 differential 降成同一 parser 自比。
- **门禁：** `scripts/native-cli-diff.sh` 对六个命令逐项钉最小、合法上边界与冲突边界；reject case 同时核对完整诊断和绝对 exit 2，不再以“两个后端给出同一个错误答案”为绿。`build` 的合法边界分别验证 JAR/native executable，`emitc` 比较 C 文本。
- **结论：已修。** 第二个 positional 不再被 native 静默覆盖；所有基数错误都在 target load/codegen 前以一致字节与 exit 2 拒绝。

## TOOL-05 — P1 — 每个 LSP 文档拥有互相矛盾的工程快照（已修）

- **原问题：S。** 每个 `Doc` 曾私有持有完整 `Program`，update 只覆盖当前文件并只发布当前 URI；
  未保存修改依赖模块后，caller 仍从磁盘读旧文本，多个 tab 因而处在不同 semantic world。
- **实现：** `18fb3d6` 让 `Doc` 只持 `Standalone | WorkspaceMember(identity)`。identity 是 canonical
  `(project, source_root)` 的长度前缀无碰撞编码；opaque lookup key 与真实 definition source-root
  边界分离，同一 project 的不同 file-mode source root 不会再由打开顺序合并。每个 identity 捕获
  一份 `ProjectPlan`，并持一份共享 `Program`、URI→entry/path、诊断贡献与 target lease。
- **更新与查询：** 每次 settled change 以该 root 全部 `Doc.text` 现场构造唯一 overlay，恰好一次
  `load_entries_over` / `analyze_program`。duplicate canonical path 的不同 live text 进入 conflict，
  丢弃旧 `Program` 并让语义查询 fail closed；冲突解除后恢复。completion、hover、definition 与
  documentSymbol 都经 `analysis_of`，definition 只借用同 identity 且位于真实 source root 内的
  live view。completion 会删除当前 entry，也不会被同 entry 的 duplicate URI 重新插回。
- **诊断与关闭：** 每次变更发布全部相关 URI，包含 `[]`；外部 diagnostics 按所有 root 的贡献
  全局聚合，撤销一个 root 不会清掉另一个 root 的同 URI 诊断。`didClose` 删除 live overlay 来源，
  以剩余文档和磁盘回落重建；最后成员关闭 lease 并删除 workspace。
- **行为负控：** `scripts/lsp-workspace-contract/` 的 18 个真实会话与 18 个 compiling mutants
  覆盖 single-overlay、current-module self-completion、duplicate last-wins、global definition、
  didClose 不重建和 project-only identity 等退化。每个 mutant 先编译，再由唯一 owning label
  定向见红；同 project/different source root 两种打开顺序会让 project-only mutant 精确触发
  `SOURCE_ROOT_WORKSPACE_MERGED`，并实际核对两侧 diagnostics、definition 与 module resolution。
- **已知边界：** `canon` 尚不解析 symlink 或平台 case-fold；manifest 变更须关闭该 root 全部文档
  后 reopen 才 fresh plan；已安装 workspace 的 unexpected compiler panic 依赖进程退出回收资源。
  这些是后续 identity/refresh/unwind 能力，不把原“每文档矛盾快照”问题重新打开。
- **结论：已修。** 一个 canonical `(project, source_root)` 在任一时刻只有一个可查询语义世界。

## TOOL-06 — P1 — LSP 与 `doc` 不加载工程 `[java-deps]`（已修）

- **原问题：S。** build/run/test 通过 dependency re-exec 看见工程 JAR，`doc` 与 LSP 却使用宿主
  process classpath；正式 build 成功的 `use java` 会在编辑器和 API 文档中产生系统性假错误。
- **实现：** `SourcePlan` 是 source graph 与 Java coordinates 的唯一事实源。`7eb2f25` 提供
  platform-parent `JsigLease`；`9f914d4` 让 JVM `check`/`doc` 对每个 target 以同一 captured plan
  `fetch_checked`、校验 lock、构造 lease、在 bracket 内分析并在输出/退出前关闭；多 target 不合并
  jars。`18fb3d6` 又让 Java-free LSP server 接显式 host factory，每个 workspace identity 独占一份
  target lease，native 使用 refused/no-op lease。
- **失败边界：** planner diagnostics 非空时跳过 Maven/网络，以 zero-jar target lease 继续分析并
  原样发布全部 planner diagnostics。Maven、lock 或 loader setup failure 则进入显式
  `Unavailable`，保留 buffer/formatting、语义查询 fail closed，绝不回退 system loader 或旧
  `Program`。`didChange` 不调用 factory；新成员与 `didSave` 才重试，且 `didSave` 不刷新 captured
  plan。JVM `jsig_for` 的宿主/I/O failure 用 `catch_fault` 转为 `LocDiag`，不吞 compiler panic。
- **生命周期：** JVM standalone 是 server-lifetime `jsig_for([])`，只见 JDK、不见 compiler
  ASM/Coursier；shutdown、exit、EOF、fatal framing 与最后成员关闭都 best-effort 释放 lease，
  单个 close panic 不阻止其余资源关闭。首次 rebuild 若在安装前 panic，会先关闭已构造 lease。
- **行为负控：** `scripts/jsig-lease-contract/` 固定 platform-parent、同 FQCN 隔离与释放；
  `scripts/java-target-classpath-contract/` 让 system-loader、合并 multi-target lease、跳 lock、绕过
  bracket 与 ASM bridge 退化先编译再定向转红；`scripts/lsp-workspace-contract/` 进一步固定两 root
  Java 隔离、standalone zero-jar、Unavailable 重试边界及 last-close/shutdown/EOF/fatal cleanup。
- **已知边界：** 语法合法但 resolver 在传递 Maven coordinate 上失败时，诊断来源仍可能只定位
  根 `dawn.toml`，尚不能精确指出贡献坐标的 dependency manifest；这不等于 target classpath
  再次缺失。
- **结论：已修。** `check`、`doc` 与 LSP 的 Java 查询都绑定 captured target plan 和显式 lease，
  setup failure 以用户可见诊断 fail closed。

## TOOL-07 — P1 — LSP header/body 没有长度上限（已修）

- **证据：S。** header 逐 byte 无限累积：`selfhost/src/lsp/server.dawn:575`；`Content-Length` 无最大值即交给 read primitive：`:603`。JVM 把 Int64 直接 `L2I`：`selfhost/src/jvm/rtclasses.dawn:1445`；native 按声明长度分配：`runtime/c/dawn_rt.c:1971`。
- **边界：** 无终止空行可无限增长 header；大于 `2^31-1` 的 body length 在 JVM 截断，native 可能巨量分配或阻塞。
- **影响：** malformed/hostile client 可 OOM、hang 或让两个后端分叉。
- **建议：** header/body hard cap；拒绝 duplicate、negative、overflow length，在 host-int conversion 前校验；超限回 JSON-RPC parse error 后关闭连接。
- **后续处置：已修。** 共享 `server.dawn` 现将完整 header（含 `CRLF CRLF`）限制为
  8192 bytes、body 限制为 67108864 bytes，并在 `io.read_stdin(length)` 前完成 ASCII-only
  header 行、字段名/十进制值、`Int` overflow、body cap 与全部重复字段一致性验证。第 8192
  byte 恰好完成可收，未完成则当场 fatal；未知但语法正确的 header 可忽略，无冒号或空/非法
  字段名不可；`0` 合法。
- **恢复边界：** 只有完整有界 body 的 JSON parse error 属于可恢复 `Malformed`。partial
  header/body、缺失/非法/冲突/超限长度与 header 超限统一进入 `Fatal`：只发一次固定
  `-32700` / `id: null` parse error，随后关闭 read loop；clean EOF 仍静默。完整 body 的非法
  UTF-8 也回 `-32700` 后继续，但会在 replacement decoder 前拒绝，不能被 U+FFFD 修成合法 JSON。
- **门禁：** `server.dawn` 纯测试覆盖 8192/8193、0/00042、64 MiB 边界、近似非法拼写、
  `2^63`/`2^31` 与重复字段；`scripts/lsp-framing.py` 以真实流固定致命/可恢复分界、坏帧后
  不再解释合法 `initialize`、严格 response framing oracle、launcher 先退出时仍清理同组
  child，以及 Linux RSS 天花板。harness self-test 11/11，JVM/native 真实流各 28/28；普通
  gate 跑 JVM，`scripts/native-cli-diff.sh` 另以 native release 形状 binary 跑独立 leg。完整理由见
  [`lsp-framing-design.md`](../lsp-framing-design.md)。

## TOOL-08 — P2 — LSP 没有 initialize/shutdown 状态机（已修）

- **原证据：S。** `LspState` 没有 lifecycle state；`shutdown` 只回 response，`exit` 无条件 status 0，因此 shutdown 后仍回答普通 request，未 shutdown 的异常退出也被编辑器误认成正常。
- **当前契约：** `PreInit` 只接受带 id 的 `initialize` request，其他 request 回 `-32002`，notification 丢弃，`exit` 为 status 1；`Running` 拒绝重复 initialize，shutdown notification 不迁移状态，只有 shutdown request 进入 `Shutdown`；`Shutdown` 只接受 exit 并以 status 0 结束，request 回 `-32600`，notification 丢弃。
- **实现：** `Lifecycle = PreInit | Running | Shutdown` 与纯 `lifecycle_gate` 位于 `selfhost/src/lsp/server.dawn:435`、`:461`；主循环在 `update_of`、pending flush 与 `update_doc` 分析前先执行 gate：`:542`、`:549`。进入 shutdown 的分支先丢弃 pending 再回应：`:571`，所以最后一次 `didChange` 不会在 shutdown/exit 前发布 diagnostics。clean EOF 与 fatal framing 分支保持原边界。
- **门禁：** `scripts/lsp-lifecycle.py` 的七类真实会话覆盖初始化前 request/notification、重复 initialize、shutdown notification、shutdown 后 request、初始化前/运行中异常 exit、正常 exit 与 pending 丢弃；`scripts/lsp-lifecycle-contract/run.sh` 的五个私有 selfhost mutant 分别把 gate 移到 update 后、异常 exit 改 0、shutdown 后继续服务、shutdown 前 flush、重复 initialize 放行，均成功编译运行并由目标会话见红。`scripts/lsp-framing.py` 的前导零合法值改用 initialize request，不再用初始化前 shutdown 伪造 framing 正例。
- **结论：已修。** 生命周期消息不能再绕过 gate 触发 document update、pending analysis 或普通 request dispatch；合法 shutdown/exit 与异常提前退出有可区分的 process status。

## TOOL-09 — P1 — origin guard 会给预置的伪造 cache “祝圣”（已修）

> **后续处置：已修。** `compiler-plan/src/pkgfetch.dawn` 的 `fetch_into` 区分新发布与 adopted
> target；若同 hash 目录已经存在，必须先用 `verify_cached(target, actual)` 重新计算其树摘要。
> 验证失败直接返回，外层 `fetch_and_hash` 因而不会写 origin record。

- **修复前证据：S。** fetch 得到真实 hash 后，若 target dir 已存在就既不替换也不验证；调用者
  随后仍记录“该 URL 产生该 hash”。`check_origin` 只比较新下载的 actual 与声明，resolver 最终
  使用的却是原有 target。
- **修复前边界：** 预建一个内容被篡改、目录名却是合法 hash 的 cache entry，并删除 origin；
  首次 build 下载正确内容后仍编译旧目录，同时写下合法 origin。
- **门禁：** `scripts/pkg-origin-contract/run.sh` 植入合法 hash 名、错误内容且无 origin 的 cache
  entry，要求 build 以“目录内容与自身名字不符”失败，并确认没有生成 origin record。
- **结论：已修。** 新下载内容不能再替一个未经验证的既有目录背书，local cache injection
  不会被 origin metadata 持久化为可信事实。

## TOOL-10 — P1 — source deps 与 Java deps 由两张不同的图规划

**状态：已修（双事实源范围）。** 独立无 Java 的 `compiler-plan/` 包实现
`source_plan(target)`：它先抓取 source package、完成
MVS，再只从最终 `PkgR` 图收集 Java 坐标；
根坐标优先、package children-before-parent、声明序、canonical root visited 与完整坐标首见去重
由该包的测试固定。`compiler-plan/src/manifestv.dawn` 以绝对 source span 稳定合并 `[deps]`
path entry 与 `[deps.<alias>]` URL table，因此混合声明序也会进入最终图；同一 archive 的 fetch
failure 以 `(hash, url)` 去重，使同一坏镜像跨 alias/阶段只尝试一次、同 hash 的其他镜像仍可
回退；missing subdir 则按 `(hash, subdir)` 去重。目录与 `.dawn` 文件目标
共用这一规划算法，`resolve_java_deps` / `dawn lock` 都消费 `SourcePlan.java_coords`。
`selfhost/src/pkg/maven.dawn` 只接收 `compiler_plan/manifestv.MCoord`（owner 为
`compiler-plan/src/manifestv.dawn`），light manifest parser、重复
coordinate parser 与 cache graph walk 已删除。
完全离线的 `scripts/source-plan-contract/run.sh` 用两个 alias 要求同名 package 的 1.0/1.1：
loser 携带不存在的 `g:poison:1`，winner 携带本地 `g:selected:1`；冷/热 cache 的文件目标都能
build，lock 只含 winner；隔离 cache 的 inspector 只依赖 Planner 公开 API，固定 URL/path
混合声明的双向顺序与 root-first；冷、热 JAR 都实际运行并精确输出 `winner:42`，且 bad-first /
good-second 的同 hash 镜像可恢复、同一坏 URL 跨 alias/阶段仍只报告一次。设计与边界见
[`source-plan-design.md`](../source-plan-design.md)。

bootstrap source-input 协议已拆到 `scripts/bootstrap-input-manifest-contract/run.sh`；三个 compiling
mutant 只复制并编译 Planner 与薄 producer probe。两个合同均已删除临时 ASM fixture，正式
`selfhost` 的 ASM 依赖不受影响。

**残余边界：** JVM CLI 的 parent 调用 `source_plan` 取得 classpath，re-exec 后 child loader
再次调用；
两次共享唯一事实源，但不是同一个 snapshot，中间修改 manifest/cache/path package
仍有 TOCTOU。TOOL-05/06 已关闭单进程 `check`/`doc`/LSP 的 captured workspace 与 classloader；
跨进程传递递归 plan 或取消 build/run/test re-exec 仍是独立工作，本刀不冒称解决。
TOOL-10 在这里仅关闭“双 parser/双 graph”。

- **原证据：S。** 修复前 Java dependency collector 先于正式 source load，source resolver 随后才
  fetch + MVS；当前两条入口都消费 `compiler-plan/src/source.dawn` 的同一规划结果。
- 修复前两者还使用不同 manifest parser；light parser 会在 quoted String 内的 `#` 处截断：
  `selfhost/src/pkg/manifest.dawn:35`。当前正式 validator 的 owner 是
  `compiler-plan/src/manifestv.dawn`。
- **边界：** cold cache 的远端 source package 声明 `[java-deps]` 时，第一次 build 跳过 jar，第二次 cache warm 后行为改变；未被 MVS 选中的 cached version 也可能污染 classpath。
- **影响：** build 结果依赖 cache history，lock/classpath 不是最终 source graph 的函数。
- **建议：** 先完成唯一 source dependency plan 与版本选择，再只从最终 roots 收集 Java coordinates；删除第二套 manifest/graph parser。

## TOOL-11 — P1 — lock 与 vendoring 用 jar basename 当 artifact identity（已修）

> **后续处置：已修。** Maven 层先把每个 resolved jar 变成 `Artifact { path, name, hash }`。
> basename 不冲突时保持原名；同 basename 的不同内容会让组内每个成员都使用
> `<short-content-hash>-<basename>`，同一内容的重复路径则去重。lock 与 vendor 共同消费这份
> artifact list，且 lock parser 拒绝重复 name。

- **修复前证据：S。** lock 只保存 `(basename, hash)` 并按 basename 比较，build 又把依赖复制到
  同一个 `lib/<basename>`。
- **修复前边界：** `group.a:util:1.0` 与 `group.b:util:1.0` 都产出 `util-1.0.jar`；lock identity
  歧义，vendor 后者静默覆盖前者。
- **门禁：** `selfhost/src/pkg/maven.dawn` 的 inline tests 构造两份同名不同内容 jar，要求二者
  都存活、组内两项都带 content qualifier、lock 能自验证；另一个测试要求重复 name 的 lock
  直接拒绝。
- **结论：已修。** lock 验证与部署 vendoring 使用同一组唯一 artifact 名，原 basename collision
  不再丢依赖。

## TOOL-12 — P1 — executable JAR `Class-Path` 没有正确 URI/byte wrapping（已修）

> **后续处置：已修。** Class-Path entry 先按 UTF-8 bytes percent-encode，`/` 与 URI unreserved
> 字符保留；相对 entry 与 base 外的 `file:` entry 走同一编码。manifest physical line 按 UTF-8
> byte 数限制到 72，continuation 的前导空格计入本行宽度，且重组后保持原值。

- **修复前证据：S。** `--cp` path 直接变相对字符串或 `file:` 加绝对路径，manifest 再以空格拼
  entry；72-byte wrapping 实际按 code point 计数。
- **修复前边界：** space 会拆成两个 token，`#` 变 URI fragment，非 ASCII path 的 UTF-8 bytes
  可超过 physical line limit。
- **门禁：** `selfhost/src/main.dawn` 的 URI inline test 固定普通路径、space、`#` 与非 ASCII；
  `selfhost/src/jvm/jarw.dawn` 的 tests 对每条 physical line 逐字节计数，并验证 continuation
  重组后的 Class-Path 完全等于输入。
- **结论：已修。** executable jar 的 dependency path 不再因 URI tokenization 或 byte wrapping
  在 `java -jar` 阶段失效。

## TOOL-13 — P2 — `dawn.toml` 与 `dawn.lock` 写入不原子（已修）

<!-- audit-anchor: absent selfhost/src/pkg/add.dawn | atomic_write_file -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `3f5d64c` 把 `dawn add` 的 manifest
> 写入与 `dawn lock` 的目标写入都换成 `std/io.atomic_write_file`：同目录 stage、read-back
> 校验、权限搬运、单次 rename，失败一律清理且原文件不动。算法与宿主能力两件新增
> （`io_temp_file` 独占创建、`io_copy_permissions` 不跟随链接）的定稿在
> `docs/atomic-write-design.md`，负控在 `scripts/atomic-write-contract/`（含
> `callsites-expected.txt`，调用点漏迁会转红）。symlink fail-closed、hardlink detach 是
> 该设计写明的边界，不属本项。**本条曾在实现发布后继续写 open**，由 `doc-check.py` 的
> evidence 检查发现。

- **证据：S。** `dawn add` 直接覆盖 manifest：`selfhost/src/pkg/add.dawn:163`、`:173`；`dawn lock` 直接写目标：`selfhost/src/main.dawn:837`。仓库已有 atomic replace primitive：`std/io.dawn:100`。
- **影响：** disk full、process termination 或 write error 可把受版本控制文件留成 truncated state。
- **建议：** 在目标目录写 temp，flush/close/validate 后 atomic rename，保留原 mode；失败不动旧文件。

## TOOL-14 — P1 — launcher stamp 未覆盖真实 compiler build inputs（已修）

> **后续处置（2026-08-10）：已修。** `3e13645` 落地完整 v2 launcher generation，此前
> partial 复核所列的四个开放边界逐一关闭：
>
> - SHA-256 工具启动即验 `abc` known vector，每次调用检查 status 与输出形状；无工具、
>   启动失败、空输出、非 64-hex 全部 fail closed，`no-sha256`/mtime fallback 已删除；
> - source/inputs digest 改为 type/length framing（`byte_length ":" raw_bytes`，record、
>   scope、kind、path、树根、相对叶路径、存在/缺失状态与内容分别 frame），拼接分割歧义
>   由真实碰撞用例钉住；
> - stage1 与最终 candidate 各自 re-plan，manifest 与 framed source stream 逐字节比较，
>   发散即 `bootstrap inputs changed during build` 且不提升；
> - 持久化 `dawn-selfhost.inputs`，v2 stamp 绑定 source/bootstrap/inputs/jar 四摘要与
>   seed identity（含 `DAWN_SEED` override）；唯一 staging 目录按 jar → inputs → stamp
>   提升，stamp 是 commit marker，提升后与 exec 前配对复验，最多两次有界重试。
>   v1 时代的 zero-toolchain shell fallback 连同其 manifest parser 一并删除——cold
>   checkout 的第一份权威清单来自 seed 构建出的 stage1。
>
> 协议全文见 [`bootstrap-input-manifest-design.md`](../bootstrap-input-manifest-design.md)。

- **修复前证据：S。** stamp 曾只覆盖 `selfhost/src`、manifest、std 与 seed release，漏 local
  source deps、lock、checksum/resolver 与 launcher recipe；root manifest 的 direct-only shell
  读取也看不到传递 package；后又查明 no-hasher fail-open、无长度 framing、无 pre/post
  re-plan 与不可恢复 promotion 四个残余边界。
- **门禁：** `scripts/bootstrap-input-manifest-contract/run.sh` 固定 Producer 的递归、去重、
  project-only 与 fail-closed 输出；`scripts/bootstrap-guards/launcher-contract.sh`（由
  `run.sh` 驱动、进 CI）以 fake compiler 角色离线固定 66 项 generation 断言——输入覆盖与
  无关文件控制、坏 manifest/文件系统的 fail-closed、framing 碰撞、发散 pre/post plan、
  promotion 顺序与崩溃恢复、并发唯一 staging、两次配对复验——每个 assertion family 由
  `mutate-launcher.py` 的 21 个可编译 launcher mutant 之一转红。
- **验收（2026-08-10）：** clean checkout 从 v0.62.0 种子冷自建（v2 stamp、热命中零重建）、
  `native-fixpoint.sh`（已迁移到 v2 stamp 校验）A==B==C、`selfhost-prev-diff.sh` 零新增
  Emit-Change 全部通过。
- **结论：已修。** launcher cache 从"内容寻址的单值 stamp"升级为可恢复的多产物
  generation，输入遗漏、摘要歧义、构建期漂移与提升竞态都有 owning assertion 看守。

## TOOL-15 — P1 — seed jar 已校验，配对 seed std 未校验（已修）

> **后续处置：已修。** `scripts/seed-std-checksums.txt` 为每个 seed tag 记录 canonical std tree
> hash；`seed_std_dir` 在 cache hit 与 staged tag archive 提升前都验证完整树，stage 1 因而消费同一
> release 下分别经过摘要验证的 jar/std pair。

- **修复前证据：S。** jar cache hit 每次校验，seed std cache hit 却只检查 `modules.txt` 存在；
  writable cache 或被移动的 tag 可以替换半个 bootstrap input，而 jar checksum 仍为绿。
- **门禁：** `scripts/bootstrap-guards/run.sh` 固定 matching tree 正例，并分别修改现有文件、添加
  新文件、删除该 tag 的摘要记录；三种负例都必须拒绝 seed std。
- **结论：已修。** seed std 与 seed jar 现在处于同一 fail-closed trust boundary。

## TOOL-16 — P1 — 默认 seed 验证在前提缺失时 fail-open（已修）

> **后续处置：已修。** pinned/default seed 缺记录摘要、摘要不符或没有可用 SHA-256 工具时均
> 失败；无法验证的历史 replay 只能通过显式 `--allow-unverified`，本地逃生对应显式
> `DAWN_SEED_ALLOW_UNVERIFIED=1`，默认路径不再继承豁免。

- **修复前证据：S。** tag 没有 checksum 或系统没有 SHA-256 tool 时只 warning 并成功；未来
  bump `seed-release.txt` 漏登记一行即可让所有 bootstrap/CI 使用未验证 compiler。
- **门禁：** `scripts/bootstrap-guards/run.sh` 固定 matching digest 正例，并分别驱动摘要不符、
  摘要缺失、hasher 缺失与显式 opt-out；前三者必须失败，只有显式 opt-out 恢复未验证路径。
- **结论：已修。** 普通 release omission 或 host tool 缺失不能再静默关闭默认种子验证。

## TOOL-17 — P2 — release JAR 自举配方是第二份实现

- **历史证据：S。** 日常 fixpoint 曾在 `scripts/selfhost-fixpoint.sh` 内联整条链；release workflow 又内联一份，并明确写着 “second copy—keep them in step”。因此两边可以各自 B==C，却发布不同 recipe 的产物。
- **已处置（2026-08-09）：** `scripts/build-release-jar.sh -o <jar>` 成为唯一、不可重组的 release JAR 接口，固定 seed std/current std/vendor、A/B/C、standalone smoke 与同文件系统原子提升；`scripts/selfhost-fixpoint.sh` 降为薄 wrapper，`release.yml` 只调用 builder，仍独立负责版本、checksum、native 与 upload。
- **回归门禁：** `scripts/bootstrap-guards/run.sh` 强制 workflow 与 wrapper 各恰好一次 canonical 调用，并拒绝内联 `build selfhost` 或 stage artifact；缺调用、双调用、追加内联、错误输出名与 wrapper 绕过五个变异负控都必须转红。
