# Playground LSP 会话设计（#11）

> 状态：**current** —— #11 当前变更集已经按本文落地「一个浏览器 buffer、一个隔离的
> native LSP 进程、一个有界会话」。gateway 采用第 5.1 节的标准库 Python 窄实现；代码合并
> 不等于生产上线。release 形态 `dawnc` 的资源数据仍须按第 7 节在 production-compatible
> Linux cgroup 中填写，用来复核当前保守限额，而不是阻止协议与隔离实现接受评审。

## 1. 今天缺的不是补全列表，而是一段有状态的语义会话

#11 开始时，Playground 有两套彼此不相认的工具：

- `site/play-ui/src/lint.ts` 在停止输入 1 秒后把完整 buffer POST 到 `/api/check`，再从
  CLI 文本报告里反解 range；429、5xx 或网络失败时保留旧诊断。
- `site/play-ui/src/dawn-lang.ts` 用正则扫描本文件声明，再拼上构建期生成的 builtin、
  关键字和少量构造子。它不知道 checker 已经解析出的类型和作用域。

所以变更前的 squiggle 是一次次独立编译，completion 是另一份近似语言。hover 不存在，
definition 也不存在。

真正的实现已经在 `selfhost/src/lsp/`：同一个 server 提供 diagnostics、completion、hover、
definition、document symbols 与 formatting；它以 stdio 上的 `Content-Length` frame 说
JSON-RPC，并在进程里保存 document / workspace / lifecycle 状态。对于 Playground 首版，
缺的是把这个**已有会话**安全地接到浏览器，而不是在 TypeScript 里重写第三个 checker。

## 2. 变更前部署给出的硬边界

本变更开始时，公开仓库能证明的生产形状如下；实际 443 nginx 配置在私有运维仓，本仓只能
提交 snippet 和部署说明，不能把「代码合并」写成「已经上线」。

| 边界 | 基线事实 | 来源 |
|---|---|---|
| HTTP broker | `dawn-play` 是长期 JVM 进程，监听 `127.0.0.1:8087` | `playground/deploy/dawn-play.service` |
| 公网入口 | 只有 `/api/run`、`/api/check`、`/api/health`；无 WebSocket location | `playground/deploy/nginx-play.conf` |
| 编译/运行并发 | `/run` 与 `/check` 共用 2 个 permit；check 最多等 2 秒，满载回 429 | `playground/src/main.dawn` |
| broker 上限 | `MemoryMax=1G`、`TasksMax=256` | `playground/deploy/dawn-play.service` |
| 一次性 sandbox | `MemoryMax=512M`、`CPUQuota=200%`、`TasksMax=64`、`RuntimeMaxSec=15` | `playground/sandbox/run-sandboxed.sh` |
| native 部署 | 基线 `redeploy.sh` 只送 launcher 与 selfhost JAR，不送 `dawnc` | `playground/deploy/redeploy.sh` |
| 输入 | runner 的 JSON body 最多 65536 bytes | `playground/src/main.dawn` |
| LSP 时序 | Full sync；server 端安静 150 ms 后分析；idle wait 不轮询 | `selfhost/src/lsp/server.dawn` |
| LSP wire 上限 | stdio frame header 8 KiB、body 64 MiB | `docs/lsp-framing-design.md` |

`run-sandboxed.sh` 的 15 秒 unit 是一次编译/运行的 backstop，不能原样拿来承载编辑会话。
反过来，LSP 自己的 64 MiB frame ceiling 是桌面编辑器协议的防失控上限，不是公开网页应当
接受的 source budget。gateway 必须在更外层维持 Playground 现有的小输入边界。

## 3. 首版的用户契约

首版只承诺一个 scratch buffer：

1. 诊断来自 LSP `publishDiagnostics`，不再把 CLI 文本反解成 range。
2. completion 先问 LSP，得到 checker 看见的本地声明、作用域、类型、构造子和 builtin。
3. hover 显示 LSP 的 Dawn 签名。
4. definition 只在当前 buffer 内移动光标和 selection。
5. Run 仍走现有 `/api/run`，分享链接仍只装一份 source；二者 wire contract 不变。

浏览器给文档一个固定的非文件 URI，例如
`untitled:dawn-playground/prog.dawn`。`uri_to_path` 对它返回 `None`，所以 server 走已有
standalone analysis：不发现项目、不读用户指定路径、不拉 Maven，也不会把另一个 session
的 workspace 纳进来。gateway 不接受第二个 document，也不接受客户端把 URI 换成 `file:`。

这条边界刻意意味着：首版不做多文件项目，不给 `use java` 提供 JVM classpath，definition
不跳进磁盘 std 或包。issue 要的是「definitions within the buffer」，这四项已经构成一个
可独立验收、不会偷偷长成云 IDE 的切片。

## 4. 进程模型：每个连接一个 native LSP

### 4.1 不共享一个 `run_lsp`

一个 shared server 看似省掉重复 std，但它的隔离代价比进程更大：

- `LspState` 的 lifecycle、document map、workspace map 与 standalone lease 都属于整个进程；
  一个 session 的 `shutdown` / `exit` 不是局部操作。
- request id、URI 和 server push notification 都没有 tenant 字段。multiplexer 必须重写并反向
  路由三者，任何漏写都会把 completion、diagnostic 或 buffer 内容送给另一位用户。
- server 会对 `file:` URI 做项目规划和 definition 文件读取。共享进程里，允许一个浏览器
  选择 URI 就等于允许它选择整个进程的文件世界。
- 当前 debounce 是一个进程内的单线程 read/analyse loop。某个昂贵 buffer 会挡住所有人的
  response；加租户队列等于另写 scheduler。

这些不是标准 LSP transport adapter 的工作，而是在复制 `LspState` 的所有权。首版拒绝这条路。
重开 shared model 的条件是 LSP server 自身先有显式、多租户且可行为测试的 session abstraction；
不能由网络层靠 URI 前缀假装隔离。

### 4.2 选择 native host

每个成功建立的浏览器连接独占一个 release 形态 `dawnc lsp` 子进程：

- 连接、stdio、LSP lifecycle 和 OS process lifetime 一一对应，不需要 request-id multiplexing。
- native host 已明确用 `jsig_refused_lease()`；首版正好不承诺 Java completion，也不需要在
  每个 session 里再养一个 JVM。
- binary 自带 embedded std，synthetic non-file URI 不要求给 session 暴露 checkout。
- kill process 就能完整回收 session；不需要相信一张共享 map 的每条清理路径都走到了。

这不是「native 一定更省内存」的性能断言。它只是功能边界更窄、没有 JVM classpath 的候选；
RSS、启动时间与诊断延迟仍须按第 7 节实测；过不了预算就停止上线这条方案，而不是把暂定
限额改口说成测量结论。

## 5. Transport：一条 WebSocket 只桥接一个 stdio

公网路径固定为 `wss://dawn-lang.dawnop.com/api/lsp`，开发环境仍用同源 `/api/lsp` 交给
Vite proxy。浏览器与 gateway 之间用 WebSocket；WebSocket 的一条 text message 承载一个**不带
`Content-Length` 的 JSON-RPC body**。gateway 往子进程写时补标准 LSP frame，从子进程读时
按标准 frame 拆开再发一条 text message。首版只收 text message，关闭 `permessage-deflate`；
fragment 由所选 WebSocket 实现重组，完整 message 仍受同一个 byte cap。

gateway 自己拥有 lifecycle 边界：只接受 client adapter 固定的 initialize → initialized →
didOpen 顺序，socket 关闭时由 gateway 发 shutdown / exit。会话中其余 message 逐条验证：

- handshake 要求预定的 `Sec-WebSocket-Protocol`，并验证浏览器 `Origin` 等于站点 origin；这只挡
  drive-by browser abuse，不代替 IP rate limit 与全局 admission（非浏览器客户端能伪造 Origin）；
- 只放行 Full `didChange`、completion、hover 与 definition；不允许再次 initialize / didOpen；
- 所有 `textDocument.uri` 必须等于固定 synthetic URI；只允许一个 open document；
- 解 JSON 后再次检查 source UTF-8 byte length 不超过 Playground 现有 65536-byte budget；
- 单个 wire message 另设小而固定的 gateway 上限，不把 LSP 内层 64 MiB ceiling 暴露到公网；
- completion / hover / definition 在写入前先 flush 最新 Full sync。server 对任何 query 都会先
  flush 自己的 pending update，因此查询与所见文本同一顺序。

### 5.1 已裁决：标准库 Python 的窄 gateway

当前 `packages/web` 建在 `com.sun.net.httpserver.HttpServer` 的完整 request/response 模型上，
没有公开 WebSocket upgrade、逐帧读写或 hijack seam。仓库也没有已固定版本、可直接复用的
server-side WebSocket dependency。为这个单一路由引入通用框架会增加供应链与常驻内存；把
WebSocket 顺手塞进 `packages/web` 则会同时扩大公共 API 和攻击面。

当前实现选择第三条、刻意更窄的路线：独立的 `playground/lsp_gateway.py` 只用部署环境已有的
Python 标准库，在 `127.0.0.1:8088`（配置也只接受数字 loopback）实现本协议所需的 RFC 6455
子集。nginx 是唯一公网入口，把同源 `/api/lsp` rewrite 到精确的 `/lsp`；gateway 不是通用
WebSocket server，也不进入 `packages/web`。

这条路线的安全边界写在代码和黑盒 contract 两处：

- upgrade 只接受精确 path、Origin allowlist、大小写敏感的 `dawn-lsp-v1` subprotocol 和版本 13；
  不接受 request body、extension 或握手后的预送字节；
- 只实现 masked text、bounded fragmentation、ping/pong 和 close；拒绝 binary，限制 header、
  frame 数、control frame 数、完整 message、消息速率与消息总数；
- upgrade 后 15 秒内必须完成到 `didOpen`，会话有 10 分钟 idle 和 30 分钟 absolute deadline；
  全局最多两个 native session，满载立即回 503 + `Retry-After`；
- JSON-RPC 在转发前重建 allowlist 字段，固定 URI、Full sync、lifecycle、pending request 数和
  64 KiB source；一个 WebSocket 只拥有一个 sandboxed native process；
- service 只监听 loopback；公网 rate/connection limit、TLS 和 Upgrade header 转发仍由 nginx
  负责。gateway 的 stdlib parser 不应被复用为任意 WebSocket 应用服务器。

HTTP create-session + polling 不作为推荐兜底：它需要并发 session registry、token、长轮询、
notification 队列和 GC，状态面比「socket 断开即回收子进程」更大。SSE 也只有 server→client
半条路，仍然要补另一条带 token 的 POST 通道。

## 6. 会话生命周期与 sandbox

gateway 只在 admission 成功后 spawn child。顺序固定：

1. 建立 WebSocket，创建一个 session id（只进日志，不成为客户端选择资源的凭证）。
2. 在专用 transient unit 中启动 `dawnc lsp`，接上 stdin/stdout/stderr。
3. gateway 验证并转发 client adapter 的固定 initialize / didOpen handshake；URI 在 gateway
   处固定，客户端只能提供 initial text。
4. socket close、protocol violation、child EOF、idle timeout 或 absolute timeout 任一发生，发送
   shutdown/exit 并关闭 child stdin，给一次短 grace；仍未退出就 stop 整个 unit。
5. 子进程完成正常退出或 transient unit stop 后才把 admission permit 放回。stderr 持续排空、
   只记录累计 byte count，不缓存或写入内容；进程 CPU、内存与 absolute lifetime 由 cgroup 兜底。

建议的产品策略是 **10 分钟无编辑/查询即 idle 回收，30 分钟 absolute 回收**。active 页面遇到
absolute 回收会自动新建 session、重新发送当前 buffer；这使泄漏或断线的最坏驻留时间有界，
也不把 session 做成需要持久化的资源。WebSocket ping/pong 只判死连接，不刷新「用户活动」。

LSP unit 与一次性 run unit 分开。它至少保持以下现有 hardening：`DynamicUser`、
`PrivateNetwork=yes`、`ProtectHome=yes`、`ProtectSystem=strict`、空 capability set、
`NoNewPrivileges=yes`、`MemorySwapMax=0`。它不需要 writable project dir，临时目录只用于
runtime 必需文件。LSP transient unit 使用 31 分钟 `RuntimeMaxSec` 兜住 30 分钟 session；当前
CPU、memory、tasks 与 parent slice 数值是第 7 节待实测复核的 hard ceiling，不能称为测量结果。

日志只记 session id、连接/子进程状态、stderr byte count、退出或拒绝原因；不记 source、hover
内容、method 值或完整 JSON-RPC body。公开 Playground 没有账户边界，日志不能反过来成为
一份代码仓库。

## 7. 合并/上线前补齐的 measurement 与 admission 复核

现有仓库没有 release-native LSP 的每会话 RSS、启动时间或 64 KiB buffer 延迟数据。当前
实现先用每 session 256 MiB、全局两个 session、aggregate 512 MiB 的保守 hard ceiling，把
协议、隔离、回收与 fallback 做成可测试切片；这些数仍是待实测复核的部署值，不是性能结论。

用**将部署的同一个 release `dawnc`**，在 production-compatible Linux cgroup 中记录：

| 场景 | 记录 | release `dawnc` 实测结果 |
|---|---|---|
| initialize 后空闲 | startup→initialize reply；idle RSS/PSS；60 秒 CPU time | 待填写 |
| 打开五个 Playground sample（各自 fresh process） | didOpen→diagnostics 的 p50 / max；peak RSS/PSS | 待填写 |
| 64 KiB 合法 source | didOpen→diagnostics；peak RSS/PSS | 待填写 |
| burst Full sync | 连续更新后只收最后文本的 diagnostics；CPU time；peak RSS | 待填写 |
| completion / hover / local definition | response latency；答案正确性 | 待填写 |
| timeout / disconnect | unit 回收时间；permit 与进程数回到基线 | 待填写 |

每个场景至少跑 10 个 fresh process；表里记 median、p95/max、binary version、host kernel、
cgroup limits 和 harness commit。measurement 脚本进入仓库，原始 TSV/JSON 作为 PR artifact；
本文写摘要和来源，不贴一次手跑的漂亮数字。

部署方先给 LSP parent slice 一个**不会挤掉现有 broker、两个 run sandbox 和同机服务**的总 memory
预算 `B`。取 64 KiB 场景的实测 peak RSS p95，加 25% headroom 向上取 MiB 为单 session
`MemoryMax = R`；全局 admission 为 `floor(B / R)`，同时受 tasks 和 CPU parent slice 的更小值
限制。`B` 必须来自生产运维预算，公开仓目前没有足够事实替维护者填写。

以下任一成立则方案停止、回到设计评审：

- 连两个 session 都无法在明确的 `B` 内同时存活；
- 64 KiB source 在 cap 内稳定 OOM；
- sample 的 didOpen→diagnostics p95 超过 3 秒；
- child disconnect 后不能在 2 秒内回收。

这四条是首版 admission test，不是上线后再观察的告警。

## 8. 慢与不可用时怎么降级

静态工具不是在 LSP 上线时删除，而是 fallback：

| 失败点 | 浏览器行为 |
|---|---|
| WebSocket handshake 429/503、网络失败 | 不建 session；diagnostics 继续用 `/api/check`，completion 用现有 static source |
| completion 超过 750 ms | 取消 UI 等待并立即给 static completion；不为此再启动一次编译 |
| hover / definition 超过 1 s | 本次显示 unavailable；编辑不被阻塞 |
| diagnostics 3 s 未到 | 关闭慢 session，下一次输入停顿回 `/api/check`；旧诊断在新结果前保留 |
| child / gateway 中途断开 | 保留当前 buffer 和最后诊断，带 jitter 重连一次；失败后保持 fallback |

client 每次送 Full sync 时记本地 generation 与文本 snapshot。`publishDiagnostics` 到达时，只有
当前 editor 仍是那个 snapshot 才应用；否则丢掉旧结果，等待后续 sync。这不要求改现有 LSP
wire 去增加非标准字段。

LSP 恢复后，completion 合并时以 server 结果为先、按 label 去重；static source 始终可单独工作。
`/api/check` 至少保留一个发布周期，且 live check 同时验证 LSP 路径和 fallback 路径，之后是否
删除 compile-only diagnostics 另立决定。

## 9. 落地点与门禁

当前变更集的落点如下：

| 位置 | 改动 |
|---|---|
| `site/play-ui/src/lsp.ts` | WebSocket JSON-RPC client、UTF-16 position 转换、generation、request timeout 与 reconnect |
| `site/play-ui/src/main.ts` | LSP diagnostics/completion/hover/local-definition 接 CodeMirror；fallback 保留 |
| `site/play-ui/src/lint.ts` | 保留 `/api/check` parser，改成可切换 fallback，而非默认唯一来源 |
| `site/play-ui/vite.config.ts` | dev WebSocket proxy，行为与 production snippet 同源 |
| `site/play-ui/test/selftest.ts` | fake socket 的正常、慢响应、断线、重连、generation 与 UTF-16 range contract |
| `playground/lsp_gateway.py` | stdlib gateway、child framing、allowlist、admission 与 lifecycle |
| `playground/test/lsp_contract.py` | fake stdio LSP 驱动的黑盒 gateway contract |
| `playground/sandbox/` | 固定 native executable、session id 校验、transient unit hardening 与 sudoers |
| `playground/deploy/` | 新 service/slice、nginx WebSocket location、bounded real-native smoke 与上线/回滚说明 |

`playground/test/lsp-contract.sh` 当前用逐帧 oracle 独立于 Dawn build 运行，结果为 **20 passed,
0 failed**，固定了：

- initialize → didOpen → diagnostics → completion → hover → local definition → shutdown；
- 两个并发 session 各有 child，同值 request id 不串线；
- source/message cap、第二 document、`file:` URI、binary frame 和不在 allowlist 的 method 被拒绝；
- Origin / subprotocol 不符时在 spawn 前拒绝，满 admission 回 503 + `Retry-After`；
- setup timeout、malformed child frame 与 active SIGTERM 都关闭 socket、回收 child/permit；
- deploy smoke 贯通 handshake→child→diagnostics，只对显式 503 有限重试，且每次有 30 秒不可续期
  monotonic deadline；日志断言确保 child stderr 内容不会落盘。
- service/slice、nginx route、sudoers、sandbox wrapper 与 native artifact 路径由静态 contract 读取，
  固定 loopback、cgroup hard ceiling、提权命令、隔离属性和相对 artifact 规范化。

contract 还会静态钉住 nginx、systemd、sudoers 与 wrapper 的关键联动；`nginx -t`、
`systemd-analyze verify`、`visudo -cf`、Python compile 与 shell syntax 是上线前静态检查。
production-compatible Linux 上的 real `dawnc` smoke 和第 7 节资源表仍是部署门禁，不拿 fake
oracle 冒充 native 性能证据。

现有 `scripts/selfhost-lsp-diff.sh` 继续守 server 的语义输出；bridge contract 守网络适配与隔离，
两者不能互相代替。若实现只新增 gateway/UI，不改变 selfhost LSP response，就不预写
`Emit-Change(lsp)`；门禁真测出 transcript 变化后再按仓库规则声明。

## 10. 一个 issue / 一个 PR，按逻辑 commit 分刀

#11 是 roadmap 上的一项功能，当前变更作为**一个 PR**评审，不再把可运行功能拆成四个相互等待
的 PR。创建提交时按以下逻辑 commit 保持 review 与 revert 边界：

1. **design/contract**：本文、固定 wire/lifecycle/security contract 与 fake stdio oracle；
2. **gateway/sandbox**：一 socket / 一 native child、framing/allowlist、admission 与 transient unit；
3. **UI/fallback**：四项功能、generation/timeout、一次 jitter reconnect、`/api/check` 与 static
   completion fallback、Vite WebSocket proxy；
4. **deploy**：service/slice、nginx snippet、bounded smoke、手工安装与回滚说明。

这些是一个 PR 内的 review slices，不表示已经创建或推送提交，也不授权生产发布。UI 在 endpoint
缺失时自动回现状；生产回滚删除 `/api/lsp` location 并停止 gateway 即可，`/run` 与 `/check`
全程不迁移 wire contract。

## 11. 不做的（以及重开条件）

- **不做 shared LSP process**：第 4.1 节的 tenant ownership 没有 server-level abstraction。
- **不做项目/多文件**：需要可信的虚拟文件系统、package source 与跨文件 definition 策略；
  一个 buffer 的四项能力先证明 hosting 值得养。
- **不做 Java / Maven completion**：native host 明确拒绝，且公网页面不该为输入时的 query 拉包。
- **不在首版删除 `/api/check` 或 static completion**：它们是明确的退化路径。
- **不顺手给 `packages/web` 发明 WebSocket**：公共包协议与 RFC 6455 安全边界要自己的设计和门禁。
- **不把 compiler 放进浏览器 wasm**：当前 LSP 依赖 stdio、host IO 与 process lifecycle；改造成
  browser reactor 是另一条架构线。只有第 7 节证明 server-side 最小并发也不可部署时才重开。
- **不承诺 production 自动发布**：真实 nginx 443 配置不在公开仓库，deploy 是维护者手工步骤。
