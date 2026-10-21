# io 原语一批：stdout 字节与 flush、追加写、区间读、文件大小、磁盘容量、sleep

> 状态：**current**。2026-10-21，native B2。本文先行，随后是两后端的八个原语、std/io 的公开面、
> `scripts/io-prims-contract` 契约与 `web` 的 `stdio_transport` / 块式 `stream-body`。依据：
> 调研 `research-full-native-20261020.md` §2 表第 3、8 行与裁决第 6 条（sleep 进时间族）；缺口清单
> 来自 [web-core-split-design.md](web-core-split-design.md) §九.8。

## 问题

dawnop-site 的后端要摆脱 JVM，B1b 已经让 `web/exchange` 在 native 上收发一个 HTTP 交换，但它是靠绕路
跑通的：

- 二进制响应只能经 `write_bytes("/dev/stdout")`，每次写重开描述符，管道成立、普通文件与 socket 不成立；
  `print` 只收 `String`，没有 flush，native 的 stdout 是 64 KiB 块缓冲。
- WebDAV 的 PUT 上限 512 MiB，`stream-body` 的 native 一侧整体读进内存再写一次文件（JVM 一侧按块）。
- Range 请求、文件大小、磁盘用量（监控页）、`cpu_window` 里的 `Thread.sleep` 在 std 里都没有对应物，
  后端只能 `use java`。

这一批补齐八个原语，两后端各自实现，一份契约把它们钉成同一个答案。

## 签名与归属

| std 公开面 | 效果 | 原语（`RtIo`，std-only，comptime 拒绝） | 失败 |
|---|---|---|---|
| `write_stdout(b: Bytes) -> Unit !io` | `io` | `io_write_stdout(b)` | 不报告（同 `print`） |
| `flush_stdout() -> Unit !io` | `io` | `io_flush_stdout()` | 不报告 |
| `append_bytes(path, content) -> Result[Unit, ForeignError] !Fs` | `Fs`，新操作 `fs_append_bytes` | `io_append_bytes(path, content)` | `Err` |
| `read_range(path, off, n) -> Result[Bytes, ForeignError] !Fs` | `Fs`，`fs_read_range` | `io_read_range(path, off, n)` | `Err`；负参数 panic |
| `file_size(path) -> Result[Int, ForeignError] !Fs` | `Fs`，`fs_size` | `io_file_size(path)` | `Err` |
| `disk_space(path) -> Result[DiskSpace, ForeignError] !Fs` | `Fs`，`fs_disk_total` 与 `fs_disk_free` | `io_disk_total(path)`、`io_disk_free(path)` | `Err` |
| `sleep_ns(ns: Int) -> Unit !Clock` | `Clock`，新操作 `clock_sleep_ns` | `io_sleep_ns(ns)` | 不报告 |

`DiskSpace = { total: Int, available: Int }`。`Fs` 由 15 个操作变 20 个，`Clock` 由 2 个变 3 个；
`std/memfs` 同步补臂，仓内其余手写 handler（`examples/effects/files.dawn`、`scripts/spike-native`、
`packages/web` 的中间件测试、`packages/tea-term` 的运行时测试）逐处补臂。没有兼容层：增加操作破坏
所有 handler，这是 `Fs` 加 `fs_real_path` 时就接受的代价（[fs-real-path-design.md](fs-real-path-design.md)），
`std/memfs` 住在 std 里正是为了让 selfhost 不被冻住。

## stdout 写字节与 flush

**不进 `Console`。** `Console` 在 `compiler-plan/src/consolemem.dawn` 里有一个 selfhost 消费的完整
handler；自举时那份源码被种子 std 和 HEAD std 各编一次，给 `Console` 加操作，同一份 `with handle
Console` 对不上两边（桥的论证与 `Fs` 的 R1/R2 同形）。`read_stdin` 当年也没有进 `Console`，理由是
没有测试问过「程序从终端读了什么」；字节写出对称。所以是两个普通的 `!io` 函数。代价是测试里不能用
handler 断言写出的字节，要断言走进程外的契约。

**语义。**

- `write_stdout` 与 `print`、`println` 共用同一个缓冲（native 的 `stdout` stdio 流，JVM 的
  `System.out`），文本与字节保持写入顺序。
- 写是**缓冲的**：返回不保证对端已经收到。`flush_stdout` 返回后，此前写的全部字节已交给描述符。
- 进程正常结束（`main` 返回、`exit`）会 flush 剩余的字节：native 靠 `exit` 刷 stdio，JVM 的
  `PrintStream` 本来就自动 flush。契约里 `ready` 模式的末尾故意不 flush，要求结束时送达。
- **`io_run` 在起子进程前 flush stdout。** 子进程继承 stdout 时直接写描述符，若父进程先前的字节还在
  缓冲里，子进程的输出会超车。两后端都加了这一步（native `fflush(stdout)`，JVM `System.out.flush()`），
  契约探针里 `A`、`echo B`、`C` 必须按序出来。这是本批唯一一处改变既有原语行为的地方，影响仅限于
  先前会乱序的程序。
- 写失败（对端关了）不报告，与 `print` 一致（SIGPIPE 处理见 `dawn_rt_init` 的注释）。

**为什么 flush 是独立原语而不是 `write_stdout` 自带。** 响应头与体分几次写，每次都 flush 是多余的系统
调用；而「流式体的一块要立刻到对端」又是必须的。两者都是调用方的策略，`stdio_transport` 选择每次写后
flush（一块一次系统调用，与块大小同量级）。

## 追加写

**比较的两条路。**

| | 路径追加 `append_bytes(path, bytes)` | 写句柄 `open_append(path) -> Handle`、`write(h, b)`、`close(h)` |
|---|---|---|
| 要的新东西 | 一个操作 | 不透明句柄类型、关闭协议、泄漏防护（`bracket`）、句柄表 |
| 单次开销 | 一次 `open` + `write` + `close` | 一次 `write` |
| 失败后的状态 | 无状态，没有要释放的东西 | 句柄泄漏或双关闭要靠类型约束 |
| handler 怎么假 | 一个臂，表里追加 | 四个操作加句柄的假实现 |
| 并发 | `O_APPEND` 每次调用原子 | 同 |

**选路径追加。** 目标是 512 MiB 的 PUT 按块落盘不整体进内存：64 KiB 一块是 8192 次 `open`，本机实测
与写本身相比是噪声（见下，256 MiB 在 native 上约 0.5 s，包含向管道喂数据与落盘）。句柄带来的泄漏面（panic
时谁关？）是真问题，路径追加没有。Go、Python、Rust 的追加都先开句柄（`os.OpenFile` 带 `O_APPEND`、`open(path, "ab")`、`OpenOptions::append`），靠析构、`with` 或垃圾回收来关；Dawn 没有析构，句柄的关闭只能靠 `bracket`，每个调用方都要写对，所以选无状态的一边。

**语义。** 文件和父目录缺失就创建（与 `write_bytes` 一致）；已存在就在末尾追加；目录挡路、父路径是文件、
无权限都是 `Err`。一次调用内的写入是 `O_APPEND` 的原子追加：两个写者的调用整块交错，不会互相覆盖。
失败发生时已落盘的字节留着（追加没有回滚）。JVM 是 `Files.write(path, b, CREATE, APPEND)`，native 是
`open(O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC, 0666)` 加写循环（处理短写与 `EINTR`）。

## 区间读

`read_range(path, off, n)`：从字节 `off` 起至多 `n` 字节。

- 文件在 `off + n` 之前结束就**变短**；`off` 在末尾或之后就是**空**，不是错误。想拒绝越界的调用方先
  `file_size`。Range 请求本来就要先知道总长来算 `Content-Range`，把「越界」留给调用方判断，原语不替它
  选一种错。
- 负的 `off` 或 `n` 是 **panic**（`read_range: off and n must not be negative`），在 std 的公开函数里
  拦（handler 听不到），原语里再拦一次。理由同 `random_bytes(-1)`：调用方的 bug，不是宿主的失败。
- 夹到文件之后仍超过 `2^31 - 1` 字节是 panic（`the range is too large`），因为 JVM 数组装不下；两后端
  同样处理，大文件分块读。`n` 取 `Int` 最大值表示「读到末尾」是允许的（先夹到文件）。
- 路径不存在、是目录、读失败都是 `Err`。文件在读的过程中缩短是 `Err`（native 的 `pread` 返回 0、JVM 的
  `readFully` 抛 EOF），不当成短答案，免得把「读出错」当成「文件到头了」。
- JVM 用 `RandomAccessFile`（异常路径关文件），native 用 `open` + `fstat` + `pread` 循环。

## 文件大小

`file_size(path)`：**常规文件**的字节数，跟随符号链接。目录、设备、不存在都是 `Err`。JVM 的
`Files.size` 对目录会答一个文件系统相关的数，原语在 JVM 一侧补了 `isRegularFile` 检查，两后端一致拒绝。
不做 `stat` 全家（修改时间、权限）：目前没有消费者，要时另开。

## 磁盘容量：statvfs 对 `Proc.run df`

选 **statvfs 原语**，不裁成 `df`。

- `df` 要起子进程、给 stdout 找一个临时文件（`Proc.run` 的流只能去文件）、解析随语言环境变的文本；
  wasm 上没有进程。statvfs 是一次系统调用，纯数字，两后端各一行（JVM `Files.getFileStore(path)` 的
  `getTotalSpace` / `getUsableSpace`，在 Linux 上读的就是 `statvfs`，数字与 C 一侧同一个公式：
  `f_blocks * f_frsize` 与 `f_bavail * f_frsize`）。
- `available` 取 `f_bavail`（非特权进程能用的），不取 `f_bfree`；监控页要的是「还能写多少」。
- 两个标量原语，不是一个返回对子的原语：原语表的返回类型是一个标量，对子要为它单开一个元组形状，再由
  std 拆开。代价是两次 `statvfs`，数字是仪表而不是快照，文档里写明。
- native 在 wasm32-wasi 上 fault（wasi-libc 没有 `statvfs`）；`Err`。

## sleep

**放进 `Clock`，不另立效果**（裁决第 6 条）。`clock_sleep_ns(ns)` 是第三个操作。理由：

- 会等的程序也是会读时间的程序；测试里想假时钟的人想连等待一起假（上面 `std/io` 的测试里，假
  `clock_sleep_ns` 推进假的 `clock_mono`，等待代码不用真等）。
- 另立效果让每个会睡的签名多一行，而一个 handler 分不开两者。
- 原先的注释写「sleep 若要来，作为一个独立效果」，理由是 handler 必须给每个操作一个臂，加操作破坏
  所有现有 handler。这条代价这次付：仓内四处假时钟补一臂。没有外部消费者（dawnop-site 钉在旧 tag，
  升钉时自己补）。

`sleep_ns(ns)`：至少睡 `ns` 纳秒；`ns <= 0` 立即返回。被信号打断就接着睡（native 的 `nanosleep` 用
剩余时间续上，JVM 的 `Thread.sleep` 同一契约）；调度会让它更长，从不更短。JVM 是
`Thread.sleep(ns / 10^6, ns % 10^6)`。wasi 上是 `nanosleep`（`poll_oneoff`），浏览器垫片答 NOSYS 时提前
返回，那里本来就不能阻塞。

## 错误形状

- 失败一律是 `Result[_, ForeignError]` 的 `Err`（经 `catch_fault`），`kind`、`message` 是后端各自的，
  契约只要求「是 `Err`」，不比较措辞。
- 调用方的 bug（负的范围）是 panic，两后端同一句话，进 `catch_panic` 后是一个值。
- 不存在 `Err` 与「正常的空答案」混用：越界区间是 `Ok(空)`，不存在的路径是 `Err`。

## wasm32-wasi

同一份 C 翻译单元：`statvfs` 的头与两个函数在 `__wasi__` 下换成 fault，`O_CLOEXEC` 没有时退化为 0，
其余（`open`、`pread`、`fstat`、`nanosleep`、`fwrite`）wasi-libc 都有。`scripts/wasm-contract` 不新增程序，
这一批没有浏览器消费者。

## 契约与实测

`scripts/io-prims-contract/run.sh`（接进 `contracts-3` job；只要 JVM 工具链与 `cc`，原生一侧的 C 由 `./bin/dawn __emitc` 出，不要 native 驱动）：

- `probe.dawn` 经公开面逐个调用，含错误路径：JVM、native `-O1`、native 加 ASan + LSan + UBSan，输出
  都必须等于手写的 `expected.txt`（不是从运行里录的）。
- `streams`：256 MiB 的体经 stdin 以 64 KiB 一块追加到文件，256 MiB 的文件以 64 KiB 一块 `read_range` 流到
  stdout；SHA-256 逐字节核对，并用 `wait4` 的 `ru_maxrss` 取峰值。`ready` 模式写 `ready\n`、flush、阻塞读
  一个字节：驱动要求 5 秒内在程序仍阻塞时收到 `ready\n`，并要求末尾未 flush 的字节在结束时送达。

内存峰值（本机 x86-64 Linux，256 MiB，64 KiB 块）：

| 场景 | 峰值驻留 |
|---|---|
| native 追加 256 MiB（stdin → `append_bytes`） | 20.3 MiB |
| native 流出 256 MiB（`read_range` → `write_stdout`） | 21.6 MiB |
| native 的空程序基线（1 MiB 体） | 20.4 MiB |
| 对照：同一个体先全读进内存再 `write_bytes` | 773.9 MiB |
| JVM 追加 256 MiB（`-Xmx64m`，本机 JDK；集群上的 GraalVM JDK 为 273.6 MiB） | 82.4 MiB |
| JVM 流出 256 MiB（`-Xmx64m`） | 77.6 MiB |
| 对照：JVM 全读进内存（`-Xmx64m`） | `OutOfMemoryError` |
| `web` 的 `stream-body`，256 MiB，定长 | 16.2 MiB |
| `web` 的 `stream-body`，256 MiB，chunked | 16.2 MiB |
| 对照：`raw-body` 路由持有同一个体 | 774.1 MiB |

JVM 的驻留是 JVM 自己的（同一堆上限下随 JDK 差三倍），所以契约对 JVM 只要求在 64 MiB 堆下跑通、不设驻留界；对照的全读版在该堆下 OOM 才是 JVM 一侧的牙。native 的 20 MiB 是运行时自己的底（与体的大小无关：1 MiB 体同样 20.4 MiB），所以界取 32 MiB；峰值与块大小
同量级，不随体增长。

### 负控

| 变异 | 层 | 必须变红的检查 | 结果 |
|---|---|---|---|
| `flush_stdout` 什么也不做 | native 运行时 | `ready`：5 秒内收不到 `ready\n` | 红 |
| 追加改成覆盖（`O_TRUNC`） | native 运行时 | 探针对比 + 追加驱动 | 红 |
| 区间读偏移加一 | native 运行时 | 探针对比 + 区间驱动 | 红 |
| `fs_append_bytes` 臂改调 `io_write_bytes` | std（`--std` 副本） | JVM 与 native 探针 | 红 |
| `fs_read_range` 臂偏移加一 | std（`--std` 副本） | JVM 与 native 探针 | 红 |
| 把体全读进内存再写（`slurp`） | 程序 | native 峰值须 > 200 MiB；JVM 须在 64 MiB 堆下死 | 都发生 |

JVM 一侧**没有** flush 变异：`System.out` 是自动 flush 的 `PrintStream`，字节写本来就立即送出，一个不能变红
的控制什么也证明不了。flush 的契约在 native 上才有牙；JVM 一侧由探针里的顺序与 `ready` 模式要求它不比
native 差。

## web 的跟进

> 这一节随种子推进后的下一刀落地：`packages/web` 在 prev-diff 里被上一个 release 的编译器按它自带的 std 检查，今天的 std 新名字它认不得；
> 同理 web 中间件里两个用 handler 假 `Clock` 的测试暂时离开该文件，随下一个种子回来。

- `web/exchange.stdio_transport()`：读取 `read_stdin(n)`（忽略位置），写取 `write_stdout` 加
  `flush_stdout`，每次写后 flush，流式体的每一块立刻到对端。进 `web` 的公开面；契约的 native 主程序
  改用它，仍然 78/78。
- `stream-body` 的 native 一侧改成块式：先建临时文件，体每 64 KiB 读一块、追加、丢掉；chunked 解码拆成
  `chunk_head` / `chunk_tail` 两步，与内存路径共用，声明长度超限仍在建文件之前拒绝，任何中途失败
  （短体、畸形帧、超限、盘拒绝）都删文件并按内存路径同样的状态回答。
- web 版本 7.2.0（纯加法：`stdio_transport`；`stream-body` 的内存行为变化不可观察于 `Request` 形状）。
- 契约：`scripts/web-exchange-contract/run.sh` 增 256 MiB 上传的内存断言（定长与 chunked 各一次，峰值
  < 32 MiB）与持有整体的对照路由（> 200 MiB）。

## dawnop-site 要改的点（本刀不动那个仓库）

- 升钉后 `Fs` 的 handler 要补五臂，`Clock` 的 handler 补一臂（`clock_sleep_ns`）。
- `cpu_window` 的 `Thread.sleep` 改 `sleep_ns`；`File.getTotalSpace` / `getUsableSpace` 改 `disk_space`；
  `File.length` 改 `file_size`。
- native 服务线：`serve_exchange` 配 `stdio_transport()`，DAV 的 PUT 不再整体进内存；Range 请求用
  `file_size` 加 `read_range`，响应体经 `streaming` 分块。

## 不做的（理由）

- **不做写句柄 / 文件句柄类型**：比较见「追加写」。要它的消费者（随机写、大量小块追加的热路径）
  出现并且实测路径追加撑不住，再设计，那时的句柄要有关闭协议。
- **不把字节写出放进 `Console`**：会冻住 selfhost 的 `Console` handler，见上。
- **不做 `fs_stat` / 修改时间 / 权限位查询**：没有消费者。
- **不做 `fs_truncate`、`fs_preallocate`、`fsync`**：追加写的持久化语义（崩溃后留多少）不在本批；
  PUT 落盘后的 `rename` 才是原子点，调用方用 `rename`。
- **不做 `sleep` 的可中断或带截止形态**：没有消费者；定时器与超时是并发话题，裁决里排在常驻服务之后。
- **不做 `sleep_ms` 之类的换算函数**：乘一千万是调用方的算术，库里放它就要决定溢出怎么办。
- **不让 `read_range` 在越界时报错**：见「区间读」。
- **不做 `statvfs` 的 inode、块大小等其它字段**：监控页只要总量和可用量。
- **不在 `write_stdout` 里检测对端关闭**：与 `print` 同一个吞掉写失败的契约，改它是另一刀。
- **不在 JVM 一侧为 flush 造变异体**：见「负控」。
- **不重写 `play/http1.dawn`**：它是 Playground runner 的自写 HTTP 层，B1b 的任务单已经排除。
