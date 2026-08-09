# Dawn 代码库审查 v2：CLI、LSP、构建与发布

> 状态：**current** —— JVM/native 驱动、LSP、依赖规划、自举与发布链的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- 对用户最危险的是 `dawn check` 假绿与 `dawn fmt` 对任意文件原地写回；两者都是默认接口语义，而不是隐藏调试命令的小问题。
- LSP 已有 debounce、URI/UTF-8 修复、跨后端前端与有界 framing，但仍缺 workspace snapshot、工程 Java classpath 与 lifecycle state，尚不适合把“与 build 一致”作为承诺。
- 包/自举链的问题集中在**一件事有两张图或两份身份**：source graph vs Java graph、artifact coordinate vs basename、seed jar vs seed std、gate recipe vs release recipe。

## TOOL-01 — P1 — `dawn check` 有诊断仍退出 0

- **证据：V。** 规范推荐 `dawn check` 守全仓 CI：`docs/spec.md:1681`；公开 `check` 与隐藏 `__check` 共用实现：`selfhost/src/main.dawn:1634`。实现只输出 `checkdump`：`selfhost/src/main.dawn:1601`、`:1622`，把诊断编码成 `D\t...`：`selfhost/src/driver/checkdump.dawn:45`，没有失败出口。
- **最小复现：** 对确定的 return-inference diagnostics 执行 `./bin/dawn check file.dawn`，stdout 有两行 `D`，shell exit status 仍为 0。
- **旁证：** `scripts/doc-check.py:903` 被迫自己解析 `D` 行，说明调用者不能依赖 exit code。
- **影响：** 按规范写的第三方 CI 会在类型/语法错误时假绿；JVM `dawn check` 与 native `dawnc check` 的 exit semantics 也不同。
- **建议：** 破坏性修正公开 `check`：正常 renderer + 有诊断 exit 1 + usage error exit 2；只有 `__check` 保留 machine golden dump。

## TOOL-02 — P1 — `fmt` 会覆盖任意直接指定的文件

- **证据：S。** help 声明 target 是 `.dawn`：`selfhost/src/main.dawn:516`；目录扫描过滤扩展名，但 direct file 不检查：`selfhost/src/main.dawn:1367`，随后原地写回：`selfhost/src/main.dawn:1385`。native 同样：`selfhost/src/nmain.dawn:312`、`:330`。
- **边界：** `dawn fmt README.md` 会把 Markdown 交给 Dawn formatter 并覆盖原文件；与目录模式的安全规则不同。
- **影响：** 一次 path typo 就能破坏非源码文件。结合 `SYN-01` 的 lexer-diagnostic 丢弃，风险更高。
- **建议：** direct file 也必须拒绝非 `.dawn` 并 exit 2。若要 formatter stdin/任意文本，使用不写回的显式模式。

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

## TOOL-05 — P1 — 每个 LSP 文档拥有互相矛盾的工程快照

- **证据：S。** 每个 `Doc` 保存完整 `Program`：`selfhost/src/lsp/server.dawn:389`，query 读取该私有 snapshot：`:399`。更新只把当前文件放进 overlay：`selfhost/src/driver/analyze.dawn:1243`，state 也只替换当前 doc：`selfhost/src/lsp/server.dawn:715`；diagnostics 只发布当前 URI：`:732`。
- **边界：** 未保存修改 `lib.dawn` 的 export，再编辑 caller；caller 的 analysis 仍从磁盘读旧 lib。两个 tab 对同一 workspace 拥有不同 semantic world。
- **影响：** 正常多文件编辑产生假诊断、错误 hover/definition 与不刷新的跨文件诊断。
- **建议：** workspace-level state：统一 URI→live text overlay、dependency graph、generation 与 shared analysis snapshot；一处更新后重算并发布所有受影响 open docs。

## TOOL-06 — P1 — LSP 与 `doc` 不加载工程 `[java-deps]`

- **证据：S。** dependency re-exec 只覆盖 build/run/test：`selfhost/src/main.dawn:855`、`:1642`；`doc` 直接用当前 process classpath：`:1442`，`lsp` 直接启动：`:1660`。LSP 注释却称 `use java` 与 compile 一致：`selfhost/src/lsp/server.dawn:439`。
- **边界：** 工程通过 `[java-deps]` 引入 class 后，build/run 成功，LSP 与 `dawn doc` 报 class not found。
- **影响：** editor 和 API docs 对正式 build 产生系统性假错误。
- **建议：** 抽出权威 project dependency plan，check/doc/lsp/build/run/test 共用；LSP 按 workspace root 缓存解析 classpath。

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

## TOOL-08 — P2 — LSP 没有 initialize/shutdown 状态机

- **证据：S。** `LspState` 无 lifecycle state：`selfhost/src/lsp/server.dawn:435`；`shutdown` 只回 response：`:686`，`exit` 无条件 status 0：`:688`。
- **影响：** shutdown 后仍回答普通 request；未 shutdown 的 abnormal exit 也被报告为正常，影响 editor restart/fault detection。
- **建议：** `PreInit | Running | Shutdown`；shutdown 后只接受 exit，未 shutdown 的 exit 使用非零状态。

## TOOL-09 — P1 — origin guard 会给预置的伪造 cache “祝圣”

- **证据：S。** 下载 tree 得到真实 hash 后，若 target dir 已存在就不替换也不验证：`selfhost/src/pkg/pkgfetch.dawn:527`、`:532`；随后仍写 origin record：`:494`、`:507`。`check_origin` 只比较下载到的 `actual` 与声明：`:579`；resolver 继续使用旧 target：`selfhost/src/driver/analyze.dawn:265`。
- **边界：** 预建一个内容被篡改、目录名却是合法 hash 的 cache entry，并删除 origin；首次 build 下载正确内容后仍编译旧目录，同时写下合法 origin。
- **影响：** 一次 local cache injection 变成持久“可信”状态，违背无记录旧条目应验证的设计。
- **建议：** 记录 origin 前对实际 target 执行 `verify_cached(target, actual)`；不符则 hard fail 或原子替换 staged tree。

## TOOL-10 — P1 — source deps 与 Java deps 由两张不同的图规划

**状态：已修（双事实源范围）。** `source_plan(target)` 现在先抓取 source package、完成 MVS，再只从最终
`PkgR` 图收集 Java 坐标；根坐标优先、package children-before-parent、声明序、canonical root
visited 与完整坐标首见去重由纯测试固定。`manifestv` 以绝对 source span 稳定合并 `[deps]`
path entry 与 `[deps.<alias>]` URL table，因此混合声明序也会进入最终图；同一 archive 的 fetch
failure 以 `(hash, url)` 去重，使同一坏镜像跨 alias/阶段只尝试一次、同 hash 的其他镜像仍可
回退；missing subdir 则按 `(hash, subdir)` 去重。目录与 `.dawn` 文件目标
共用这一规划算法，`resolve_java_deps` / `dawn lock` 都消费 `SourcePlan.java_coords`。`pkg/maven.dawn` 只接收
`manifestv.MCoord`，light manifest parser、重复 coordinate parser 与 cache graph walk 已删除。
完全离线的 `scripts/source-plan-contract/run.sh` 用两个 alias 要求同名 package 的 1.0/1.1：
loser 携带不存在的 `g:poison:1`，winner 携带本地 `g:selected:1`；冷/热 cache 的文件目标都能
build，lock 只含 winner；隔离 cache 的 inspector 直接读取公开 `source_plan`，固定 URL/path
混合声明的双向顺序与 root-first；冷、热 JAR 都实际运行并精确输出 `winner:42`，且 bad-first /
good-second 的同 hash 镜像可恢复、同一坏 URL 跨 alias/阶段仍只报告一次。设计与边界见
[`source-plan-design.md`](../source-plan-design.md)。

**残余边界：** JVM CLI 的 parent 先调用 `source_plan` 取得 classpath，re-exec 后 child loader
会再次调用它；两次共享唯一事实源，但不是同一个 snapshot，中间修改 manifest/cache/path package
仍有 TOCTOU。跨进程传递递归 plan 或取消 re-exec 会扩散到完整 `ProjectPlan`、TOOL-05 workspace
snapshot 与 TOOL-06 classloader，本刀不冒称解决；TOOL-10 在这里仅关闭“双 parser/双 graph”。

- **证据：S。** Java dependency collector 在正式 source load 前运行：`selfhost/src/main.dawn:858`；远端 package 只看已有 cache：`selfhost/src/pkg/maven.dawn:68`。source resolver 之后才 fetch + MVS：`selfhost/src/driver/analyze.dawn:343`、`:376`。
- 两者还用不同 manifest parser；light parser 会在 quoted String 内的 `#` 处截断：`selfhost/src/pkg/manifest.dawn:35`，正式 loader 用 `manifestv`：`selfhost/src/driver/analyze.dawn:176`。
- **边界：** cold cache 的远端 source package 声明 `[java-deps]` 时，第一次 build 跳过 jar，第二次 cache warm 后行为改变；未被 MVS 选中的 cached version 也可能污染 classpath。
- **影响：** build 结果依赖 cache history，lock/classpath 不是最终 source graph 的函数。
- **建议：** 先完成唯一 source dependency plan 与版本选择，再只从最终 roots 收集 Java coordinates；删除第二套 manifest/graph parser。

## TOOL-11 — P1 — lock 与 vendoring 用 jar basename 当 artifact identity

- **证据：S。** lock artifact 只有 `(basename, hash)`：`selfhost/src/pkg/maven.dawn:213`、`:270`；compare 按 basename：`:293`。build 把依赖复制到同一个 `lib/<basename>`：`selfhost/src/main.dawn:1108`、`:1113`。
- **边界：** `group.a:util:1.0` 与 `group.b:util:1.0` 都产出 `util-1.0.jar`；lock identity 歧义，vendor 后者静默覆盖前者。
- **影响：** lock 可能无法验证自己生成的集合；deployment jar 缺少编译期存在的 dependency。
- **建议：** lock schema 使用完整 coordinate/type/classifier/hash；vendor filename 含 coordinate 或 content hash。迁移前至少 collision hard fail。

## TOOL-12 — P1 — executable JAR `Class-Path` 没有正确 URI/byte wrapping

- **证据：S。** `--cp` path 直接变相对字符串或 `"file:" ++ abs`：`selfhost/src/main.dawn:1143`；manifest 以空格拼 entry：`selfhost/src/jvm/jarw.dawn:68`；72-byte wrapping 实际用 code-point length：`:72`。
- **边界：** space 会拆成两个 token，`#` 变 URI fragment，非 ASCII path 的 UTF-8 bytes 可超过 physical line limit。
- **影响：** compile 成功的 executable jar 在 `java -jar` 时找不到依赖。
- **建议：** 每项转换成 RFC-compliant URI reference并 percent-encode；按 UTF-8 octet wrap continuation line。

## TOOL-13 — P2 — `dawn.toml` 与 `dawn.lock` 写入不原子

- **证据：S。** `dawn add` 直接覆盖 manifest：`selfhost/src/pkg/add.dawn:163`、`:173`；`dawn lock` 直接写目标：`selfhost/src/main.dawn:837`。仓库已有 atomic replace primitive：`std/io.dawn:100`。
- **影响：** disk full、process termination 或 write error 可把受版本控制文件留成 truncated state。
- **建议：** 在目标目录写 temp，flush/close/validate 后 atomic rename，保留原 mode；失败不动旧文件。

## TOOL-14 — P1 — launcher stamp 未覆盖真实 compiler build inputs

- **证据：S。** stamp 只覆盖 `selfhost/src`、manifest、std 与 seed release：`bin/dawn:97`；`selfhost/dawn.toml:12` 还有三个 local source deps。stamp 也漏 `selfhost/dawn.lock`、`scripts/seed-checksums.txt`、`scripts/seedjar.sh` 与 build recipe `bin/dawn`。
- cache hit 直接执行旧 jar：`bin/dawn:169`；只有决定 rebuild 后才重新验证 seed：`:141`。
- **影响：** 修改 `packages/json`/`sha2`/`inflate`、lock、checksum policy 或 launcher 后，`bin/dawn` 可继续运行旧 compiler；撤销 seed trust 也不触发重建。
- **建议：** 从权威 dependency plan 生成 content-addressed input manifest，至少覆盖 transitive source、lock、seed checksum/resolver 与 recipe。

## TOOL-15 — P1 — seed jar 已校验，配对 seed std 未校验

- **证据：S。** jar cache hit 每次校验：`scripts/seedjar.sh:68`、`:78`；seed std cache hit 只检查 `modules.txt` 存在：`:90`、`:93`，首次内容来自 tag archive：`:98`。stage 1 与 release 都使用该目录：`bin/dawn:156`、`.github/workflows/release.yml:61`。
- **影响：** writable cache 或被移动的 tag 可改变 bootstrap input，而 jar checksum 与现有 trust narrative 看不见。
- **建议：** 为 seed std 记录并每次验证 canonical tree hash，或从已校验 release artifact 提取；cache 更新使用 atomic directory replacement。

## TOOL-16 — P1 — 默认 seed 验证在前提缺失时 fail-open

- **证据：S。** tag 没有 checksum 时只 warning 并成功：`scripts/seedjar.sh:37`；没有 SHA-256 tool 时也只 warning：`:42`。release 只打印“请登记摘要”的 notice：`.github/workflows/release.yml:101`。
- **边界：** 未来 bump `seed-release.txt` 却漏加 checksum，所有默认 bootstrap/CI 静默使用未验证 compiler。
- **影响：** 一次普通 release omission 就关闭信任门禁。
- **建议：** pinned/default seed 必须 fail-closed；historical replay 或 local escape 用显式 `--allow-unverified`/env，不能复用默认路径。

## TOOL-17 — P2 — release JAR 自举配方是第二份实现

- **历史证据：S。** 日常 fixpoint 曾在 `scripts/selfhost-fixpoint.sh` 内联整条链；release workflow 又内联一份，并明确写着 “second copy—keep them in step”。因此两边可以各自 B==C，却发布不同 recipe 的产物。
- **已处置（2026-08-09）：** `scripts/build-release-jar.sh -o <jar>` 成为唯一、不可重组的 release JAR 接口，固定 seed std/current std/vendor、A/B/C、standalone smoke 与同文件系统原子提升；`scripts/selfhost-fixpoint.sh` 降为薄 wrapper，`release.yml` 只调用 builder，仍独立负责版本、checksum、native 与 upload。
- **回归门禁：** `scripts/bootstrap-guards/run.sh` 强制 workflow 与 wrapper 各恰好一次 canonical 调用，并拒绝内联 `build selfhost` 或 stage artifact；缺调用、双调用、追加内联、错误输出名与 wrapper 绕过五个变异负控都必须转红。
