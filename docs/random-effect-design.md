# 随机字节：原语 `io_random_bytes` 与 std 的 `Random` 效果

> 状态：**current**。2026-10-14，一个分支 `s7-random`：本文先行，随后是原语两后端 + comptime 拒绝
> + 浏览器 WASI 垫片，最后是 `std/io` 的 `Random` 效果。站点侧（把 `util/crypto.dawn` 改成建在
> `random_bytes` 上）不在本文，等含本原语的 release 之后另行处理。

## 问题

std 没有熵。想要不可预测的字节（会话 token、上传链接 id、UUID）只能 `use java
"java.security.SecureRandom"`，于是这些代码只能跑在 JVM 后端，native 与 wasm 目标无从取熵，
也没有办法在测试里把它换成固定字节。

仓外 backend-dawn 的 `util/crypto.dawn` 是现状的样本：UUID 走 `UUID.randomUUID()`，
`random_bytes(n)` 对 `SecureRandom` **一字节一次 `nextInt(256)`**，注释说这样是为了避开 Java 侧
原地填充 `byte[]`。用到的熵形状全是「n 个字节」：UUIDv4 是 16 字节加两处位掩码，token 是 32
字节的 base64url，没有任何地方要整数范围或浮点。

## 形状

### 一个原语，一个操作

```
fn io_random_bytes(n: Int) -> Bytes !io     # RtIo，std-only，comptime 拒绝
```

```dawn
pub effect Random { fn random_bytes(n: Int) -> Bytes }
pub fn with_random_real[T, !e](body: fn() -> T !Random !e) -> T !io
```

- **返回不可变的 `Bytes`**，与 `io_read_stdin(n) -> Bytes` 同类。不做「调用方给缓冲、原地填」：
  那是 crypto.dawn 注释里担心的别名问题，值语义下根本不会出现。
- **只有一个操作，并且集合一次定对。** 每个声明的操作在 handler 里恰好一臂（spec §6.5），往已
  发布的效果里加操作是对所有用户 handler 的破坏性变更（`docs/clock-design.md` 同一条教训）。熵
  只有一个自然操作；整数、范围、浮点都能在纯 Dawn 里从字节推出（拒绝采样），不进效果。
- **效果名取 `Random`，不取 `Entropy`。** 用户面向的是「随机」，熵源是 handler 的实现细节。
  Rust `getrandom`、Zig `io.random`、Go `crypto/rand` 都叫 random。文档首行写明它是
  CSPRNG 的输出，不是可播种的 PRNG。
- **形状照抄 `Clock`**：公开操作带 `random_` 前缀（`use std/io.{Random}` 会把操作引进导入模块
  自己的命名空间，spec §6.5），生产 handler 体行写 `!e`，嵌套测试看护这一点。
- **没有 `random_bytes_of` 之类的包装函数。** `Clock` 要包装是因为 `clock_mono` 回 opaque 的
  `Instant`，而这里操作本身就是用户要调的那个名字。

### n 的语义

- `n == 0` 回空的 `Bytes`。
- `n < 0` 是 **panic**：调用方的 bug，不是宿主的失败。两后端同一句话
  `random_bytes: n must not be negative`。
- 没有人为的上界。getrandom(2) 单次调用有上限（Linux 上 2^25 - 1 字节），所以 native 一律循环
  处理短读与 `EINTR`；JVM 一个数组装不下 2^31 以上，`n` 超过 `Integer.MAX_VALUE` 时与其他
  数组原语同样的失败（内存不足），不另立文本。没有消费者要 MB 级熵，真要更多调用方循环。

### 失败：`dawn_fault`，不返回 `Result`

读熵失败（native 上 getrandom 与回落都读不到）是 `dawn_fault`，不编一个字节，也不给
`Result`。这条与 Clock 的惯例相同，并且有外部先例：Go 1.24 起 `crypto/rand` 读失败直接
fatal，不再返回 error，原因是被调用方忽略的 error 路径造出了可预测的全零 UUID
（CVE-2025-66565 一类）。Dawn 没有办法让调用方在业务路径上「安全地忽略」一个 `Result`，
所以不给这个口子。Rust `getrandom` 返回 `Result`，但它的文档把失败列为极旧内核与特殊沙箱，
上层 crate 多数直接 `expect`。

### 两个后端

- **JVM**（`selfhost/src/jvm/rtclasses.dawn` 的 `dawn/rt/Io`）：一个静态 `SecureRandom`
  （线程安全），`nextBytes(new byte[n])` 一次调用。不直接读 `/dev/urandom`：Linux 上
  `SecureRandom` 默认的 NativePRNG 本来就读它，非 Linux 宿主上也自动选对。
- **native**（`runtime/c/dawn_rt.c`，`dawn_io_random_bytes`）：首选 `getrandom(2)`，无标志位，
  即初始化后才返回的阻塞语义（`/dev/urandom` 在启动早期不保证这点）；**只有 `ENOSYS`**
  才回落读 `/dev/urandom`（Rust `getrandom` 的回落同样只覆盖内核不支持的目标）。其他错误
  （`EINTR` 除外，重试）直接 `dawn_fault`。仓库此前没有任何 `getrandom`/`urandom` 引用，
  这是新依赖。native 后端按 Linux 推进（`native-backend-plan.md` 的平台假设），不写 macOS/BSD 的
  `getentropy` 分块。
- **wasm32-wasi**：同一个翻译单元，wasi-libc 没有 `getrandom`（它的 `sys/random.h` 只在
  `__wasilibc_unmodified_upstream` 下声明），只有 `getentropy`，落到 preview1 `random_get`，单次
  最多 256 字节，所以 C 侧有一处 `#ifdef __wasi__`，循环分块。CLI 侧的 wasm 契约跑在 Node 的 `node:wasi` 上，它实现了 `random_get`。
  要补的是 tea-dom 的手写浏览器垫片 `packages/tea-dom/js/wasi.mjs`：它按模块自己的 import
  表构造 import 对象，缺的函数答 `NOSYS`，那样 `getentropy` 失败、`dawn_fault`。补上之后
  `random_get` 答 `crypto.getRandomValues`，该 API 单次上限 65536 字节，所以垫片分块。
  可达性已核实：原语走的就是同一份 C 运行时，不存在 wasm 侧编译期拒绝的必要。

### comptime 拒绝

`io_random_bytes` 进 `ir/interp.dawn` 的 `comptime_rejects()` 的 io 循环，`selfhost/builtins.dawn`
镜像行尾写 `# comptime: rejected`。理由比时钟更强：编译期取熵会让 `const SECRET = ...` 编出
每次不同、且被写进 jar 或二进制的「秘密」，同时破坏可复现构建。不给固定值（例如全零）：
那会让一个看起来能用的 `const` 静默地成为公开常量。用户实际碰到的是更早的一道：`const` 初始化
必须是纯的，检查器就会报 `!Random`；解释器的拒绝是第二道。

## 可测试性

生产 handler 是 `with_random_real`；测试写 `with handle Random { random_bytes(n) => <确定字节> }`。
`Bytes` 有公开构造器，不需要像 `Instant` 那样补构造函数。业界对照：Unison 的 `Random`
ability 有 seed 驱动的 handler，Elixir 的 Skuld 库的 Random 效果有生产、seeded、固定值三个
handler。Dawn 的假 handler 就是这一路，所以熵做成效果而不是裸 `!io` 函数。

## 性能

本机实测（2026-10-14，GraalVM CE 21.0.2，WSL2 Linux，负载不低，只看量级；每轮 1 万次
`random_bytes(16)`，第三轮的稳态数字）：

| 读法 | ns/次 |
|---|---|
| JVM `SecureRandom.nextBytes(byte[16])` | 122（前两轮含预热：1777、135） |
| JVM 一字节一次 `nextInt(256)`，共 16 次（站点现状） | 970（前两轮：2885、1317） |
| C `getrandom(buf, 16, 0)` | 221 / 222 / 229 |

一次批量调用比今天的逐字节写法快约 8 倍（稳态）；native 一次 getrandom 是一次系统调用，
200 余纳秒，足够 token 与 UUID 这类低频用途。需要吞吐的消费者（若有）应取一大块再切，
而不是反复要 16 字节。

## 验证

- `scripts/intrinsic-parity.py`：名字在表里有 `rt`，JVM 有方法、native 有 `dawn_` 函数。
- `scripts/builtin-decl-contract/run.sh`：P5 核对 comptime 标记与拒绝列表一致。
- `./bin/dawn test selfhost` 的三个计数测试各动一（builtin 表、intrinsic 表、comptime 拒绝
  列表），类型表测试断言它是 `RtIo` 且 internal；`driver/analyze` 一条端到端测试：`const`
  取随机字节在检查器就被拒，诊断写明 `!Random`。
- std 测试（两后端，`dawn test --stdlib` 转写按字节一致，所以**不打印读数**）：假 handler 答
  确定字节；真 handler 下长度对、两次读数不同（16 字节相同的概率 2^-128，可以断言）、
  `n == 0` 回空、`n < 0` panic；七个生产 wrapper 嵌套。
- 变异体负控：把真源换成全零、把长度少一，两个都必须使上面的测试变红。
- `selfhost-prev-diff.sh`：`doc --builtins` 的清单多一条 `io_random_bytes`，`emit` 各标签因
  `dawn/rt/Io` 多一个方法而变，都按 Emit-Change 声明；`std/io` 头部注释多一行，`lsp` 里指向其中定义的位置下移一行，同样声明。
- `scripts/wasm-contract/run.sh`：wasi 的 `getentropy` 能编、能链。

## 不做的（理由）

- **UUID 与 token 不进 std。** 它们是纯 Dawn，建在 `random_bytes` 之上，留在消费者的
  `util/crypto.dawn`。Rust、Go 的标准库也把 UUID 留给库（Rust `uuid` crate、Go
  `google/uuid`）。出现第二个消费者再抽成 `packages/` 的包。
- **不做 UUIDv7。** 没有消费者；它还要 `!Clock !Random` 的拼装，等需求出现。
- **不叫 `Entropy`。** 见「形状」。
- **不返回 `Result`。** 见「失败」；Go 1.24 的前车之鉴。
- **不做整数、浮点、范围的随机原语。** 从字节推导，保持原语面最小。
- **不做可播种 PRNG 进 std。** 仓内没有消费者；要时做成纯 Dawn 的包。
- **不并进 `Clock`。** 时钟与熵不是一类读数，测试需求相反（冻结时间 vs 注入固定字节），并进去
  则「恰好一臂」逼每个只想假造熵的 handler 也答时钟。
- **不读 `/dev/urandom` 当主路径，也不用现有 `io_read_bytes(path)` 去读它。** 后者读到
  EOF，而 `/dev/urandom` 没有 EOF；wasm 没有这个文件；Windows 上的 JVM 也没有。
- **不做 `getentropy` 分块。** native 后端目前只按 Linux 推进。
- **comptime 不给固定值。** 见上。
