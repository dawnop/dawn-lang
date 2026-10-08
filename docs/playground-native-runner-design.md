# Playground runner 进程 native 化：套接字激活加一连接一进程（C 路）

> 状态：**proposed**（2026-10-08 起草）。依据 `agent-handoff/research-native-services-20261007.md` 第 3.2 节 C 路，
> 与协调者 10-08 裁决「runner A 路 #630 先合；C 路立设计稿并先测 `read_stdin` 64 KiB 与每请求启动成本；
> B 路（`/run` 走 `dawnc build`）暂缓，等 C 路设计里的 cc 开销实测后合裁」。
> 本稿建立在 PR #630（`/check` 与 `/compile` 的 C 视图改走 native `dawnc`，未合并时以其描述与 diff 为准）之上。
> 本稿**没有实现任何东西**，只有第三节三组实测和一份刀序。

## 一、要什么，不要什么

要：Playground 的 runner **进程本身**不再是常驻 JVM。今天它是 `dawn run /opt/dawn/playground`：JVM 先编译 runner 源码再跑，
`packages/web` 包着 `com.sun.net.httpserver`，每请求一条虚拟线程；空闲时一对 JVM 合计约 560 MB（3.1），到 `/health` 通 2.4 到 3.3 s。
C 路把它换成：systemd 套接字激活（`Accept=yes`），每个连接起一个 native Dawn 进程，从 stdin 读一个 HTTP/1.1 请求，
向 stdout 写一个响应，退出。空闲时没有 runner 进程；一次请求的进程约 2.3 MiB、约 1 ms（3.2）。

不要：

- **不让 native 长出 socket、线程或原子 RC。** 三项都被现行裁决挡着（FFI 不做，10-04；多线程形态先钉不实施；`docs/native-backend-plan.md:378`
  把「`packages/web` 在 native 上跑」明文列为不在范围内）。C 路的全部意义是**绕开**它们，所以它不是「web 在 native 上跑」。
- **不碰沙箱单元。** 每请求的编译器单元与程序单元（`sandbox/run-sandboxed.sh`）一字不改；runner 只是更便宜的调度者。
- **不承诺砍掉 JDK。** 见 1.1：只要 `/run` 仍是 `java -jar`、`/compile` 仍列 JVM 视图，服务器就仍需要 JDK。

### 1.1 先说清楚：C 路拿走的是哪一块内存

| 部分 | 现状 | C 路之后 |
|---|---|---|
| runner 常驻进程（`dawn run` 的父 JVM 加子 JVM） | 空闲 125 + 439 = 约 564 MB（3.1） | 无常驻进程；每请求约 2.3 MiB |
| `/check`、`/compile` 的 C 视图的编译器 | #630 后 native，单次约 64 MB | 同 #630 |
| `/run` 的编译器与程序 | JVM，编译约 510 MB、程序约 55 MB | **不变**（B 路才动） |
| `javap`（JVM 视图）、`use java` 回落 | JVM | **不变** |

所以 C 路单独拿到的是**常驻开销**（`MemoryMax=1G` 的 runner 单元可以降到几十 MB 量级）和**启动**（不再有「先在 JVM 里编译自己」的 2.4 s 与 600 MB 峰值）；
并发峰值里的 `/run` 编译器 JVM 仍在。不要把 C 路读成「Playground 内存降一个数量级」，那是 B 路的账。

## 二、架构

```
nginx ──proxy_pass http://unix:/run/dawn-play/http.sock:/…──▶ dawn-play.socket (Accept=yes)
                                                                 │ 每个连接
                                                                 ▼
                                      dawn-play@<n>.service  (StandardInput=socket, StandardOutput=socket)
                                       └─ dawn-play serve    ← native Dawn 二进制，约 144 KB 量级
                                            1. 读请求头（逐字节到 CRLFCRLF，上限 16 KiB）
                                            2. 读 Content-Length 个字节的 body（上限 MAX_BODY）
                                            3. 路由 /health /run /check /compile
                                            4. 重活：闸门 + 沙箱单元（今天的 exec.dawn，经 Proc.run）
                                            5. 向 stdout 写 `HTTP/1.1 …` + `Connection: close`，排空 stdin，退出
```

### 2.1 从 `packages/web` 搬什么、不搬什么

`packages/web` 的 `server.dawn` 有 32 行 `use java`（`HttpServer`、虚拟线程、`InputStream`、`HttpClient` 等），整体不可能进 native。
`types.dawn:12` 还有一行 `use java "java.io.InputStream"`（`ResponseStream` 的底层），所以**连 `web/types` 也不能原样导入**：
`dawnc` 对任何可达的 `use java` 都拒绝。`router.dawn` 与 `middleware.dawn` 是零 `use java`（`grep -c`），但它们依赖 `types` 里的 `Request`/`Response`。

做法（K1 之内要定的事，见第七节问题 2）：

- 新写 `playground/src/play/http1.dawn`：一个**只服务单请求**的 HTTP/1.1 解析与响应渲染，纯函数加一个读 stdin 的薄层。
  不做 keep-alive、不做分块请求体、不做 `Expect: 100-continue`、不做 Range；方法只认 GET 与 POST。几百行量级，沿用 runner 现有的
  `raw(status, content_type, body)` 形状（`play/contract.dawn` 本来就把错误渲染成自己的 JSON，不走框架的 `Err` 分支）。
- runner 路由只有四条（`/health`、`/run`、`/check`、`/compile`），用一个 `match path` 即可，**不需要**把 `router`/`middleware` 搬过来。
  `with_logging` 的等价物是每请求往 stderr 写一行，由 journald 收。
- 不改 `packages/web`。把 `types.dawn` 的 `ResponseStream` 拆出去是另一件事（它对 dawnop-site 后端的 native 化才有意义，不在本稿范围）。

### 2.2 keep-alive：不做，`Connection: close`

一个连接一个进程，进程在响应写完就退出，所以没有 keep-alive。这与 nginx 的默认行为一致：`proxy_http_version` 默认 1.0，
nginx 对上游每请求新开一条连接并发 `Connection: close`，当前 `nginx-play.conf` 没设 `keepalive`，所以**对 nginx 来说没有任何行为变化**。
实测 JVM runner 新连接的 `/health` p50 1.27 ms，native 进程 1.21 ms（3.2），新连接成本在同一量级，没有 keep-alive 的损失可言。

浏览器到 nginx 之间的 keep-alive 不受影响（nginx 终结它）。

### 2.3 读请求：`read_stdin(n)` 的语义决定了写法

`std/io.dawn` 的 `read_stdin(n)` 是「恰好 n 字节，只有输入结束才会短」，**不是**「现有多少给多少」。直接读 `read_stdin(65536)` 会一直阻塞到
64 KiB 到齐或对端关闭。所以：

- 请求头：`read_stdin(1)` 逐字节读到 `\r\n\r\n`，上限 16 KiB（超限回 431/400）。
- body：解析出 `Content-Length` 后 `read_stdin(cl)`；`cl` 超过 `MAX_BODY`（65536）直接回 413，**不读 body**（与 `main.dawn` 现行的按字节上限一致）。
- 回完响应后**排空 stdin**（`while stdin_ready(0) { read_stdin(1) }`），原因见 3.1 的「未读完就退出会丢响应」。

没有 `Content-Length` 的 POST 视为长度 0（`Transfer-Encoding: chunked` 回 411；nginx 对上游发的是带长度的请求，所以 chunked 不会出现）。

## 三、实测

环境：WSL2 本机，机器同时被别的任务占着（`uptime` 负载 7 到 9），release **v0.85.0** 的 `dawnc-linux-x86_64`（native 编译器），
GraalVM CE 21.0.2。绝对数偏慢，比值可信。生产机的数字没有测。脚本在写者的 scratch 目录，不入库（一次性的原型，且依赖本机进程布局）。

套接字激活的实现：本机没有 sudo，`systemd-run --user` 不带 `Accept=yes` 的模板单元，所以用 **`systemd-socket-activate -l <unix socket> -a --inetd`**
（`systemd` 自带，每个连接 fork 一个子进程并把连接作为 stdin/stdout/stderr 交给它）。这与真实的 `Accept=yes` 的区别是：真实路径多一次 systemd
启动一个 service 单元的开销（cgroup 创建等），**本机没测**，所以 M2 的数字是下界，生产要在部署时按 3.4 的方法再测一次。

原型是一个 60 行的 Dawn 程序（逐字节读头、读 `Content-Length` 个字节、回 `{"declared":…,"got":…,"sum":…}`，`sum` 是 body 的滚动校验和），
`dawnc build` 编出 144 KB 的二进制。

### 3.1 M1：`read_stdin` 的正确性与耗时

客户端是 Python，经 unix 套接字连接。64 KiB body 是伪随机字节，校验和与客户端算的一致才算对。

| 场景 | 耗时 | 结果 |
|---|---|---|
| `GET /health` | 1.8 ms | 正确 |
| 64 KiB，一次 `sendall`，客户端**不关连接** | 1.7 ms（重复 3 次均 1.7） | `got=65536`，校验和一致 |
| 64 KiB，请求头切 3 段 + body 切 8 段 8 KiB，段间睡 50 ms | 551 ms（≈ 11 个间隔） | 正确，耗时等于客户端的节奏 |
| 请求头逐字节发（2 ms 间隔）+ 5000 字节 body 切 5 段 | 217 ms | 正确 |
| 声明 1000、只发 400、1.5 s 后 `shutdown(SHUT_WR)` | 1500 ms | `got=400`（读到输入结束才短），校验和对 |
| 声明 1000、只发 400、**不关**连接 | 3 s 探测窗口内无响应 | 进程一直阻塞，见下 |
| 请求头发到一半就 `shutdown(SHUT_WR)` | 1.3 ms | 回 400 |
| body 之后跟了多余字节（管线化），或 POST 无 `Content-Length` 却带了 body；第一版原型 | 1.7 ms | 响应丢失，`Connection reset by peer`（见教训 3） |

结论与三条教训：

1. **64 KiB 与分段到达都正确**；逐字节读头不是瓶颈，整个 64 KiB 请求端到端 1.7 ms。
2. **声明长度大于实际且客户端不关连接，进程会无限阻塞**，因为 `read_stdin(n)` 没有超时。必须在**外层**兜底：单元上设 `RuntimeMaxSec`
   （或 `timeout(1)` 包一层），nginx 的 `proxy_read_timeout`/`client_body_timeout` 会先切断慢客户端，进程随之读到输入结束。
   `stdin_ready(timeout_ms)` 可以在读 body 之前做一次有界的存在性检查，但它只问「有无至少一个字节」，不能替代整体超时。
3. **未读完就退出会丢响应。** 第一版原型回完就退出，当 stdin 里还有没读的字节（管线化的下一个请求、无 `Content-Length` 的 POST 带的 body）时，
   内核对连接发 RST，客户端 `recv` 得到 `Connection reset by peer`，**已经写出的响应也读不到**（实测 2 例复现）。
   排空 stdin 后两例都正常。排空必须用 `stdin_ready(0)` 加 `read_stdin(1)`：用 `stdin_ready(20)` 会让每个请求多等 20 ms（实测 p50 从 1 ms 变 21 ms），
   用 `read_stdin(4096)` 会再次阻塞（恰好 n 字节语义）。
   nginx 不管线化，所以生产上这是防御性处理，不是热路径。

另一点：`print`/`println` 只收 `String`，没有写原始字节到 stdout 的函数。runner 的响应是 JSON 文本，够用；将来若要回二进制（不会，Playground 没有）再议。

### 3.2 M2：每请求的进程启动成本

200 个请求，每个新连接；表中是客户端从 `connect` 到读到 EOF 的墙钟。

| 路径 | p50 | p95 | max |
|---|---|---|---|
| native 进程，`GET /health`，Python `fork/exec` + `socketpair`（无套接字激活层） | 0.92 ms | 1.12 ms | 1.24 ms |
| native 进程，`POST` 64 KiB，同上 | 1.32 ms | 1.48 ms | 1.64 ms |
| native 进程，`GET /health`，`systemd-socket-activate -a --inetd` + unix 套接字 | 1.21 ms | 1.41 ms | 1.57 ms |
| native 进程，`POST` 64 KiB，同上 | 1.64 ms | 1.76 ms | 1.88 ms |
| **现行 JVM runner**，`GET /health`，每次新连接，`Connection: close` | 1.27 ms | 2.31 ms | 6.25 ms |

- 每请求进程的**峰值常驻 2.3 MiB**（`/usr/bin/time -f %M`：GET 2380 KiB，POST 64 KiB 2348 KiB）；二进制 144 KB。
  （`resource.getrusage(CHILDREN)` 报 13.7 MiB，那是 Python 自己 `fork` 前的映像，不是子进程；以 `time` 为准。）
- JVM runner：从 `dawn run` 到 `/health` 通 **3.25 s**（本机负载高；10-07 调研在空闲机上测得 2.37 s）；空闲时子 JVM 125 MB + 父 JVM 439 MB，
  父进程 `VmHWM` 571 MB。按 `contract.sh` 约定在 `PLAY_TEST_PORT=18097` 上起，沙箱关（`PLAY_UNSAFE_LOCAL=1`），`-Xmx512m`。
- JVM runner 在**同一个连接上**复用时 `/health` p50 为 44 ms，p95 48 ms。这是 Python `http.client` 与 JDK `HttpServer` 之间 Nagle 加延迟 ACK 的老问题，
  与本稿无关，**不拿它当对比**；nginx 对上游本来就不复用连接。
- 结论：**进程启动不是成本**。新进程的 `/health` 与常驻 JVM 在同一毫秒量级；真正的成本全在各路由里的重活（编译、跑程序），这些本稿不动。
- 没测、需要估的：`/run` 路径上 runner 自己的活（解析 JSON、`cache_key` 的 SHA-256）。`packages/sha2` 是纯 Dawn，7.7 MB/s
  （调研报告第 2 节），64 KiB 约 8.5 ms `[推论]`，相对 1 s 以上的编译可忽略，但要在 K2 里实测。

### 3.3 M3：B 路（`/run` 走 `dawnc build`）的 cc 开销

各 5 次，取中位数，同一台负载 7 到 9 的机器，JVM 一侧 `DAWN_JVM_OPTS="-Xss512m -Xmx512m"`。`dawnc build` 的 cc 部分约等于 `build` 减 `emitc`。

| | `dawn build` 出 jar（JVM） | `dawnc build` 出二进制（含 cc） | `dawnc emitc`（不含 cc） | cc 阶段（差） |
|---|---|---|---|---|
| hello（1 行 `println`） | 1.41 s（1.30 到 1.56） | 1.68 s（1.66 到 1.75） | 0.88 s | 约 0.8 s |
| `examples/data/shapes.dawn` | 1.42 s（1.32 到 1.59） | 2.41 s（2.03 到 2.44） | 0.93 s | 约 1.5 s |
| 编译峰值 RSS | 502 到 525 MB | 64 到 68 MB | 64 到 65 MB | |
| 运行 | `java -Xmx256m -jar`：0.05 到 0.06 s，55 到 56 MB | 0.00 s，2.0 到 2.3 MB | | |

读法：

- 编译墙钟 B 路比 JVM **慢 0.3 s（hello）到 1.0 s（shapes）**，比调研报告估的「+1 s」更温和，且随程序大小增长（cc 阶段随生成的 C 增长，C 视图最大 872 KB）。
- 内存是数量级的差：编译 510 MB 到 65 MB，运行 55 MB 到 2 MB。并发闸 `MAX_CONCURRENT=2` 的峰值从约 1.1 GB 降到约 130 MB（`/run` 全 native 时）。
- 代价：服务器要装 `gcc`/`clang`（DEPLOY.md 现在只要 JDK），沙箱单元要放行 cc 的 fork、`TasksMax`、可写临时目录；`use java` 程序在 Playground 不可用。
- 与 C 路的关系：**独立**。C 路不依赖 B 路，B 路不依赖 C 路；但两者都做完才能不装 JDK（还要砍或另想 JVM 视图）。
  数据留给协调者合裁，本稿不替它定。

## 四、并发闸与缓存的重设计

### 4.1 闸门：从 `Semaphore` 到 `flock`

今天：进程内公平 `Semaphore(2)`，`/run` 排队 15 s、`/check` 与 `/compile` 等 2 s，超时回 429。C 路里没有「同一个进程」，闸门必须是跨进程的。

- **用 `flock(1)` 加槽位文件**：`/run/dawn-play/slot.0`、`slot.1`（`RuntimeDirectory=dawn-play`）。内核在进程退出时释放锁，包括被 SIGKILL，
  所以今天 `with_gate` 的 `bracket` 要防的「panic 漏许可证最终把闸门焊死」在这里**不存在**，是个净收益。
- **许可证必须跨整个 `execute`（编译阶段加运行阶段）**，而 `Proc.run` 是「同步运行一个命令」，`flock` 命令一退出锁就没了。所以重活走**二级进程**：
  前端进程完成解析、体积检查、缓存查询后，执行 `gate.sh <wait_secs> dawn-play job <dir>`；`gate.sh` 在超时内轮询各槽位 `flock -w 0.25`，拿到锁后
  `exec` 作业；作业（同一个二进制的子命令）做今天 `exec.dawn` 的全部事（建工作目录、写 `prog.dawn`、两个沙箱单元、读回输出、清理），把结果写到 `<dir>/result.json`；
  前端读它并回响应。拿不到锁时 `gate.sh` 以固定退出码（如 75）退出，前端回 429。
- 代价：**失去公平排队**（Java 的 `fair=true` 是 FIFO，`flock` 轮询不是）。在 nginx 已按 IP 限速（`/run` 12 r/min，burst 4）的前提下，两槽位的饥饿窗口很小，
  但这是行为变化，列入第七节问题 3。
- `MaxConnections=` 不能替代：超限是拒绝而非排队，且它按连接数而不是按重活数计，`/health` 也会占名额。但它可以作**总上限**兜底（如 16），防止慢客户端攒出一千个等锁进程。

### 4.2 缓存：砍掉，或落成文件

现状：进程内 LRU，128 项、32 M 字符，只服务「同一程序在 C 与 JVM 两个标签页之间切换」，键是 `sha256(toolchain + code) + target`。

两个选项，推荐**先砍**：

- 砍：每次请求都编译。代价是切标签页多等一次编译；#630 之后 `/compile` 的 C 视图是 native 的，约 1 s，用户可以接受，且编辑器本来不是每次按键都编。
- 落文件：`/var/lib/dawn-play/cache/<key>`，命中时 `utime` 当 LRU，写时用临时文件加 `rename` 保证原子，淘汰用 `systemd-tmpfiles` 的 age 或写入时的概率性清扫。
  Dawn 有 `Fs`（`rename`、`list_dir`），不需要新原语；但「条数加字符数」两个界要自己实现，且多进程并发写同一键要靠 `rename` 的原子性。

推荐先砍，等实测显示切标签页的重复编译确实成为抱怨再落文件（第七节问题 4）。这也符合仓库的方向：不为没有证据的需求加持久化。

### 4.3 `/health`

走同一条路，不取闸门。返回 `{"ok":true,"version":…,"build":…}`，版本来自 `dawnc --version` 与 `dawn --version`（#630 已经在启动时比较）。
进程每请求新起，所以这个探测**每次**花一次子进程（约 2 到 5 ms 量级，`first_line_of` 现状 `waitFor(5s)`）。可以把版本串烘进二进制（`version.dawn` 式常量，构建时注入），
健康检查就零子进程。部署脚本 `redeploy.sh` 靠 `/health` 的 200 判定重启成功，所以语义不变。

## 五、沙箱单元的相互作用

- 每请求的编译单元与程序单元（`dawn-play-run-<id>`）**不变**；`sudo -n run-sandboxed.sh` 的白名单、限额、`RuntimeMaxSec=15` 都不动。
- runner 单元的差别：`dawn-play@.service` 以 `User=dawn-play` 运行，**不能设 `NoNewPrivileges=yes`**（它要 `sudo`），这与今天的 `dawn-play.service` 一致，
  所以安全姿态**不变也不更差**。每个连接一个 service 实例意味着每个请求在 systemd 里是一个独立的 cgroup，`TasksMax`、`MemoryMax` 自然按请求计，
  是比今天「一个大 broker」更细的隔离。
- **超时与 kill 要重建。** 今天 `exec.dawn` 用 `ProcessBuilder.waitFor(timeout)` 加 `destroyForcibly` 加另起 `sudo … stop <unit>`；native 的 `Proc.run` 同步阻塞、没有超时、
  没有 kill。兜底在沙箱里已经有（`RuntimeMaxSec=15`，`stop <id>` 动作），作业进程自己的超时靠外层 `timeout(1)`（`gate.sh` 里 `exec timeout --kill-after=2 <budget> …`）。
  这是净新增的 shell 层，需要契约测试覆盖（K3）。
- `Proc.run(argv, out_path, err_path)` 的输出必须落文件：与今天一致（沙箱输出就是落在 runner 预先打开的文件里）。
- 随机与时间：`UUID.randomUUID` 换成 `Clock` 加 pid 加 `uuidgen` 之一；`chmod` 用 `Proc.run ["chmod"]`；`System.nanoTime` 用 `Clock`；`open_box` 的 0777/0711 用同一办法。均 S 级。

## 六、部署变更与回滚

### 6.1 新增与改动

- `dawn-play.socket`：`ListenStream=/run/dawn-play/http.sock`，`Accept=yes`，`SocketUser=dawn-play`，`SocketGroup=www-data`（nginx 用户能连），`SocketMode=0660`，
  `MaxConnections=16`。
- `dawn-play@.service`：模板单元，`StandardInput=socket`，`StandardOutput=socket`，`StandardError=journal`，`User=dawn-play`，
  `RuntimeMaxSec=60`（兜底 3.1 的「无限阻塞」），`MemoryMax=256M`，`TasksMax=64`，`RuntimeDirectory=dawn-play`（槽位文件）。
  环境变量沿用今天 `dawn-play.service` 的（`DAWN_BIN`、`PLAY_JDK`、`PLAY_WORK_ROOT`、`PLAY_SANDBOX_SCRIPT` 等），去掉 `JAVA_HOME`/`DAWN_JVM_OPTS`（runner 不再是 JVM）。
- `nginx-play.conf`：`proxy_pass http://127.0.0.1:8087/run` 换成 `http://unix:/run/dawn-play/http.sock:/run`（四个 location）。
  `proxy_read_timeout` 保持；加 `client_body_timeout 10s`（防慢速上传占满进程）。
- `redeploy.sh`：多一步 `dawnc build playground -o /opt/dawn/bin/dawn-play`（原子替换二进制），重启对象从 `dawn-play` 变为 `dawn-play.socket`（模板实例不用重启，新连接自然用新二进制）。
  `DEPLOY.md` 的步骤 2（装 JDK）保留（`/run` 与 `javap` 还要它）。
- 构建 runner 本身需要 `dawnc`（#630 已要求部署上有）；`dawnc build` 要 cc，所以**构建机**（不是请求路径）要有 C 编译器。生产要不要装 cc 取决于在哪构建：
  推荐在 CI 或本机构建、`scp` 二进制，生产不装 cc（与 B 路的「装 cc」是两件事）。

### 6.2 回滚

整个切换在 nginx 的 `proxy_pass` 一处。保留 `dawn-play.service`（JVM 版）已安装、`disable` 不删，回滚就是：
`systemctl start dawn-play` + 把 nginx 四处 `proxy_pass` 改回 `127.0.0.1:8087` + `nginx -s reload`，秒级。二进制 runner 与 JVM runner 读同一套环境变量与同一个 `run-sandboxed.sh`，
状态（缓存除外，缓存本就是进程内的）无迁移，所以回滚不丢数据。

## 七、刀序

0. **前置**：#630 合并；`web/types` 的 `InputStream` 问题的取舍（问题 2）。
1. **K1：`play/http1.dawn` 单请求解析与响应。** 纯函数加 stdin 薄层，`dawn test` 里用字节串喂；原型的 M1 场景（分段、短 body、超限、排空）变成永久测试。
2. **K2：`serve` 子命令与路由。** 复用 `contract.dawn` 的渲染；`/health` 烘入版本；`/run`、`/check`、`/compile` 先**直接调**今天的 `exec.dawn`（它仍然 `use java`，所以此刀的二进制仍是 JVM 构建的）。
   这一刀的验收：同一份 `contract.sh` 在新旧两种入口下都过（见下）。
   **K2 落地记录（10-08）**：`play/routes.dawn`（四条路由，输入 body 字节、输出 `Reply{status, body}`，不 import `web`）被
   `main.dawn`（长驻 web 服务）与新的 `play/serve.dawn`（每进程一个请求）共用，两个入口不会在答案上漂移。入口选择：`dawn run playground -- serve`
   或 `java -jar play.jar serve`。serve 仍是 JVM 构建，不能 `dawnc build`：路径上剩下的 `use java` 都在 K3 的清单里
   （`exec` 16 行、`cache` 7 行、`gate` 2 行、`config` 1 行，加 `routes` 里的 `Semaphore` 与 `System.nanoTime`），另外 `main.dawn` 要拆成独立的 native 入口项目才不带 `web`。
   serve 里的闸门是进程内 `Semaphore`，每个进程只有一个请求，所以恒放行：**K2 的 serve 不得挡在流量前面**，跨进程 flock 闸门与 job 子进程是 K3。
   serve 不跑启动清扫（清扫会删掉兄弟进程正在用的工作目录）；access log 与 compile 缺口日志写 stderr，stdout 只有响应。
   `/health` 与 `/run` 等每请求重新问一次工具链版本（子进程），烘入版本也是 K3。
   验收：16 个请求（health、run 五种、check 两种、compile 三种、坏 JSON、坏 UTF-8、超限、空 body、404、405）对现行 JVM runner 与
   `systemd-socket-activate -a --inetd` 驱动的 serve 比对，状态码与响应体逐字节一致（`ms` 与 `cached` 两个字段按设计归一：serve 没有缓存）；`contract.sh` 42 项全绿。
   sha2 64 KiB 在 native（dawnc 0.85.0）实测 0.87 到 1.16 ms/次（负载 7 到 9 的机器），摘要与 hashlib 一致，远低于裁决 8 的 20 ms 线。
3. **K3：去 Java 化 `exec.dawn` / `cache` / `gate` / `config`**：22 行 `use java` 逐个换成 `Proc.run`、`Clock`、`Fs`、`env`；闸门换 `gate.sh`；缓存先砍。到这一刀才能 `dawnc build`。
   **K3 落地记录（10-08）**：serve 路径上已无 `use java`，`dawnc build playground/native` 出 832 KB 的二进制（`serve` 与 `job <dir>` 两个子命令）。
   - `exec.dawn`：每个子进程都是 `Proc.run`。`Proc.run` 同步、无超时无 kill，所以预算是 `timeout -k 2 N sh -c '…'`，里面的 `sh` 把输出与退出状态写进 runner 自己的文件，
     **缺状态文件即超时**（程序自己 `exit 124` 仍是它的状态，有测试）；超时后再 `stop <unit>`。`chmod` 走命令，计时走 `Clock`，id 取 `/proc/sys/kernel/random/uuid`（无则 `uuidgen`）。
     有界读取是一个 `sh`：`[ -f ] && [ ! -L ] && head -c`，结果落 scratch 文件再读，不跟链接、不在 FIFO 上阻塞。
   - 闸门：路由不再碰 `Semaphore`，改为把 `Job` 交给 `Host`（`play/host.dawn`）。长驻 JVM 服务的 host 保留进程内公平 `Semaphore` 与答案缓存（`play/jvmhost.dawn`，全仓这条路径上仅剩的 `use java`）；
     serve 的 host（`play/gate.dawn`）把任务写成文件，跑内嵌的 gate 脚本：轮询两个 `slot.N` 的 `flock -n`，拿到后 `exec <本二进制> job <dir>` 并让锁描述符 9 随之继承，
     所以许可证跨编译与运行，进程怎么死（含 SIGKILL）内核都释放。拿不到则退出码 75，前端回 429，等待时长沿用 15 s（/run）与 2 s（/check、/compile）。
     任务与结果用长度前缀字段写文件（`play/job.dawn`），不用 JSON：870 KB 的 C 文本是切片，不是逐字符扫描。作业的子进程会关掉 9 号描述符（`TIMED_SH`），逃逸的程序占不住槽位。
   - 缓存：serve 不留（裁决 4）；JVM 服务照旧。`/health` 零子进程：部署设 `PLAY_TOOLCHAIN_ID="<version> <build>"`（`dawn --version` 名字之后的两词），未设则探一次 `dawn --version`（本机 0.27 s）。
     `javap` 改为只查在不在（`command -v`），不再每请求起一个 JVM；`/run` 不再问 `dawnc`，`/check` 与 `/compile` 各一次 `dawnc --version`（约 11 ms）。
   - 槽位目录 `PLAY_SLOT_DIR`（单元的 `RuntimeDirectory=/run/dawn-play`），缺省 `<work root>/play-slots`。`timeout`、`flock`、`head`、`chmod`、`rm` 是新的运行时依赖（coreutils 与 util-linux）。
   - 验收：`playground/test/serve-compare.py <二进制> --gate --bench` 对现行 JVM runner 与 `systemd-socket-activate -a --inetd` 驱动的二进制比对 17 个请求（health、run 五种、check 两种、compile 三种、坏 JSON、坏 UTF-8、超限、空 body、404、405），
     状态码与响应体逐字节一致（`ms`、`cached` 归一）；两槽三个并发慢 `/run`，第三个等到槽位才答；两槽占满时 `/check` 2.0 s 后 429；SIGKILL 两个作业后下一个请求立刻拿到槽位。
     `contract.sh` 48 项在 JVM 入口上仍全绿；`playground/test/native-tests.sh` 在 `dawnc test` 下跑 89 个 test 块。
4. **K4：部署单元与 nginx 切换。** 先在另一个 socket（如 `dawn-play-canary.socket`）上与 JVM runner 并行，对同一批请求做响应字节比对（沿用 `contract.sh` 的 48 项），再切 nginx。
5. **K5：删 JVM runner 的启动路径**（保留 `dawn-play.service` 文件一个版本周期作回滚，再删）。

契约测试的做法：`playground/test/contract.sh` 现在起 `dawn run playground` 并用 curl 驱动。C 路不改它的 curl 部分，只加一个启动模式：
`systemd-socket-activate -l <sock> -a --inetd <binary> serve`，curl 用 `--unix-socket`。这样同一份用例对两种入口各跑一遍，差异即缺陷。

## 八、开放问题

1. **B 路与 C 路的先后/合并。** 3.3 给出数据；若合裁做 B 路，K3 里 `exec.dawn` 的 `java -jar` 就不用保留，且服务器可以不装 JDK 的前提只差 JVM 视图的去留（产品决策）。
2. **`web/types` 的 `InputStream`。** 本稿选择「runner 不导入 `web/types`，自己写 `http1`」，代价是 `Request`/`Response` 在 runner 里是另一套小类型。
   备选：把 `ResponseStream` 从 `types.dawn` 移到只有 JVM 才导入的模块，使 `types` 零 `use java`，这会让 router 与中间件在 native 上可用，但是 `packages/web` 的公开面变更
   （需 web 的 major 或明确的 minor 说明），且是否值得为一个只有 4 条路由的 runner 做，留给协调者。
3. **闸门公平性。** `flock` 轮询不是 FIFO。是否接受？替代是 `gate.sh` 里排号文件（更多 shell），我倾向接受。
4. **缓存砍掉是否可接受。** 需要线上数据：切 C/JVM 标签页导致重复编译的比例（现在没有这个计数）。
5. **真实 `Accept=yes` 的单元启动开销。** 本机无 sudo，没测；需要在部署机上测一次 `dawn-play@.service` 的 `connect` 到响应，与 3.2 的 1.2 ms 对比。我预期是毫秒到十几毫秒量级，仍远小于编译。
6. **`Connection: close` 的上游。** 假设 nginx 不管线化；若以后加了别的上游客户端（站点后端直接调 runner），排空逻辑要保留。
7. **runner 的二进制由谁构建。** 是 CI 产物（`scp`）还是生产上 `dawnc build`（要装 cc）；倾向前者。
8. **`stdin_ready(0)` 排空的竞态。** 排空只清掉「此刻已到」的字节，晚到的仍可能触发 RST；nginx 场景无此情形，但这不是证明。若要彻底，需要 `shutdown(SHUT_WR)` 后读到 EOF，而 native 的 `std/io` 没有半关闭原语。

## 九、不做的（理由）

- **不实现 socket / HTTP 服务端 / 线程进 native**：被 10-04 的 FFI 与并发裁决挡着，且 C 路证明不需要它们。
- **不做 keep-alive 或长连接状态**：nginx 对上游不复用连接，进程每请求新起，1.2 ms 的启动不构成成本（3.2）。
- **不搬 `packages/web` 的 `router`/`middleware`**：runner 只有四条路由，为它们引入框架就要先解决 `web/types` 的 `use java`（问题 2），代价大于收益。
- **不改沙箱单元和 sudoers**：C 路只换调度者，攻击面不应因为换调度者而变。
- **不在 C 路里砍 JDK 或 JVM 视图**：那是 B 路与产品的决定（1.1）。
- **不为缓存先做持久化**：没有「重复编译确实是问题」的证据（4.2）。
- **不用 `MaxConnections` 当并发闸**：超限是拒绝不是排队，且 `/health` 会占名额（4.1）。
- **不加兼容层或双栈长期共存**：K4 的并行只是切换前的比对，K5 删旧入口，回滚靠保留的 JVM 单元文件而不是代码里的开关。
- **不把测量脚本入库**：一次性原型，依赖本机的 `systemd-socket-activate` 与进程布局；永久的覆盖是 K1 的 `dawn test` 与契约测试的 inetd 启动模式。
