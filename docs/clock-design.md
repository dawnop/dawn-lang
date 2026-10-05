# 时钟：两个读数原语与 std 的 `Clock` 效果

> 状态：**current**。2026-10-05，K1（原语两后端 + 浏览器 WASI 垫片）与 K2（`std/io` 的 `Clock`
> 效果声明）同一分支 `feat/clock-intrinsic` 两个提交；K3（tea-term、web 中间件改用）与
> backend-dawn 的迁移不在本文。调研与裁决见 `research-clock-intrinsic-report-20261005` 与
> `ruling-clock-intrinsic-20261005`（agent-handoff，未入库）。

## 问题

std 没有时钟。intrinsic 表的 `io_in_rt` 里 24 个名字没有一个读时间（`selfhost/src/check/types.dawn`
的 `intrinsics()`）；凡要时间的地方都直接 `use java "java.lang.System"`：`packages/web` 的日志中间件、
playground 的计时、`selfhost/src/contract/bench.dawn`。这些代码因此只能跑在 JVM 后端，native 与
wasm 目标上无从读钟。

仓外的 backend-dawn 更进一步说明了缺什么：它自己声明了一个 `Clock` 效果答墙钟毫秒，同时有 23 处
拿 `currentTimeMillis` 相减量耗时。后者是一个真实的正确性缺陷：墙钟会被 NTP 拨动，相减得到的
可能是负数或尖刺。Go 加单调读数的直接起因就是这一类故障（Go 提案 12914，Cloudflare 的闰秒事故）。

## 形状

### 两个原语，不是一个

```
fn io_clock_wall_ns() -> Int !io   # 纪元（1970-01-01T00:00:00Z）起的纳秒，可倒退、可为负
fn io_clock_mono_ns() -> Int !io   # 单调，原点任意，只有两次读数之差有意义
```

两种钟回答两个问题，每个宿主都分开给：Linux 的 `CLOCK_REALTIME` 与 `CLOCK_MONOTONIC`
（clock_gettime(2)），WASI preview1 的 `realtime` 与 `monotonic` clockid，JVM 的
`Instant.now()`/`currentTimeMillis` 与 `nanoTime`（后者文档原话：只能用来量经过时间）。只给墙钟，
量耗时就是错的；只给单调钟，JWT 过期、TC3 签名的时间戳就写不出来。

两个原语都是 `RtIo`、std-only（进 `io_in_rt`，自动得到 internal）、`!io`、comptime 拒绝。

### 单位：纳秒，一个 `Int`

`Int` 是 64 位有符号、溢出二补码环绕（spec §1.5、§4.3「数值边缘语义」）。纪元纳秒能表示的范围约是 1678 到 2262 年，Go 的
`UnixNano` 文档给的是同一个区间。单调钟的差值在环绕下仍然正确，所以比较两次读数要用减法
（`b - a >= t`），不用比较绝对值，这条与 JVM `nanoTime` 文档给的写法相同。

不取毫秒：毫秒会丢掉宿主已有的精度。本机实测（2026-10-05，GraalVM CE 21.0.2，WSL2 Linux）：
`Instant.now()` 连取 10 万次，纳秒字段对 1000 取余得到 1000 个不同的余数，即 JVM 墙钟的分辨率
在微秒以下；`clock_getres` 对两个钟都答 1 ns，连读两次 `CLOCK_MONOTONIC` 最小的非零步长 10 ns。

### 两后端用同一个单调钟

native 选 `CLOCK_MONOTONIC`，不选语义上更好的 `CLOCK_BOOTTIME`（计入挂起时间，OCaml mtime 的
选择）。理由是两后端要按字节对拍（`scripts/native-cli-diff.sh`），而 HotSpot 的 `nanoTime` 在
Linux 上就是 `CLOCK_MONOTONIC`（JDK-8006942 讨论过换 `MONOTONIC_RAW`，以 Won't Fix 关闭）。
本机实测同源：先后启动的 JVM 打印 `nanoTime` = 1248909047665，C 程序打印 `CLOCK_MONOTONIC` =
1248977227742，差 68 ms，正是两次进程启动的间隔，`/proc/uptime` 同时答 1248.98 s。

### 代价

一次读数是一次 vDSO 调用，不进内核。本机实测（同上环境，负载均值约 30，数字偏高，只看量级），
每次调用：

| 读法 | ns/次（三轮） |
|---|---|
| C `clock_gettime(CLOCK_MONOTONIC)` | 24.5 / 41.6 / 26.2 |
| C `clock_gettime(CLOCK_REALTIME)` | 26.7 / 31.7 / 28.8 |
| JVM `System.nanoTime()` | 27.8 / 37.9 / 43.8 |
| JVM `Instant.now()` 拆成纪元纳秒 | 77.8 / 50.1 / 59.6 |
| JVM `System.currentTimeMillis()`（对照） | 41.5 / 42.3 / 30.1 |

JVM 墙钟多出的二三十纳秒是 `Instant` 对象的分配与两次取字段；墙钟读数不在热循环里（它服务于
时间戳，热循环量耗时用单调钟），不值得为它换一个丢精度的 API。

## 三个宿主

- **JVM**（`selfhost/src/jvm/rtclasses.dawn` 的 `dawn/rt/Io`）：单调是一条 `INVOKESTATIC
  System.nanoTime`；墙钟是 `Instant.now()` 取 `getEpochSecond() * 1_000_000_000 + getNano()`。
  不用 `currentTimeMillis`，理由见上（JDK 9 起 `Clock.systemUTC()` 给到底层时钟的精度，
  JDK-8068730）。
- **native**（`runtime/c/dawn_rt.c`）：`clock_gettime` 两个 clockid，`tv_sec * 1e9 + tv_nsec`。
  `emitc` 不需要新分支：表里带 `rt` 的原语一律调 `dawn_<name>`。这两个 clockid 在 Linux 上不会
  失败；万一返回非零，按其余 io 原语的惯例 `dawn_fault`，不编一个数。
- **wasm32-wasi**：同一个翻译单元，wasi-libc 的 `clock_gettime` 落到 `clock_time_get`，C 侧不需要
  `#ifdef`。CLI 侧的 wasm 契约跑在 Node 的 `node:wasi` 上，它实现了 `clock_time_get`。要补的是
  tea-dom 的手写浏览器垫片 `packages/tea-dom/js/wasi.mjs`：它按模块自己的 import 表构造 import
  对象，缺的函数答 `NOSYS`。补上之后，realtime 答 `Date.now()` 乘 10^6，monotonic 答
  `performance.now()` 换成纳秒。浏览器为防计时攻击把 `performance.now()` 粗化到 100 µs（跨源隔离时
  5 µs，MDN）；契约承诺的是纳秒**单位**，不是纳秒**分辨率**，所以不违约。

## comptime 拒绝

两个名字进 `ir/interp.dawn` 的 `comptime_rejects()` 的 io 循环，`selfhost/builtins.dawn` 镜像行尾写
`# comptime: rejected`，`scripts/builtin-decl-contract` 的 P5 核对两处一致。

用户实际碰到的是更早的一道：`const` 初始化必须是纯的，`const T: Int = io.now_wall_ns()` 在检查器
就报 `const initializers must be pure, but `now_wall_ns` is !Clock`。解释器的拒绝是第二道，挡的是
检查器以为纯、却经由某条路径到达原语的情形。

不给固定值（例如 0）：那会让 `const BUILT_AT = ...` 静默编出 1970 年，是一个看起来能用的错答。
读钟让同一份源码在不同时刻编出不同的字节，正是可复现构建要消灭的输入；业界的解法是构建方显式给出
`SOURCE_DATE_EPOCH`（reproducible-builds.org），不是让编译器自己读钟。

## `std/io` 的 `Clock`

```dawn
pub effect Clock {
  fn clock_wall_ns() -> Int
  fn clock_mono() -> Instant
}
pub opaque type Instant = Int
pub fn with_clock_real[T, !e](body: fn() -> T !Clock !e) -> T !io
pub fn now_wall_ns() -> Int !Clock
pub fn now() -> Instant !Clock
pub fn elapsed_ns(from: Instant, to: Instant) -> Int
pub fn instant_at_ns(ns: Int) -> Instant
```

- **单调读数是 opaque 的 `Instant`，墙钟读数是 `Int`。** 两种读数在类型上不能混，这是 Rust 的分法
  （`SystemTime` 与 `Instant` 两个类型），不是 Go 的「一个 `Time` 值里两份读数，减法自动走单调那份」。
  Go 那样做是为了保持 `Time` 的向后兼容（提案明说），代价是一份在序列化、`Round`、`In` 时会被
  悄悄剥掉的隐藏状态。Dawn 有 opaque 类型，混用可以直接是类型错误。墙钟不包：纪元纳秒本身就是
  一个可序列化、有意义的数（JWT `exp`），包一层只多一次拆包。
- **`elapsed_ns` 饱和到 0。** 单调钟在一级平台上有 OS 保证，但 Rust 记录了硬件、虚拟化与 OS 缺陷
  偶尔会让它倒退，早期 Rust 在此 panic，后来改成饱和（`Instant` 文档）。饱和让「量出负耗时」这件事
  不可能发生在调用方手里。
- **`instant_at_ns` 是公开的构造器。** opaque 只在声明模块内可见，没有它，std/io 之外的假 handler
  写不出 `clock_mono` 臂。这在「opaque 防混用」上开了一个口子，但口子是显式拼写的。Rust 的
  `Instant` 没有公开构造器，所以 Rust 的测试要靠运行时钩子（tokio `time::pause`）；在 Dawn 里假
  handler 是一等测试手段，std/io 的五族全是这么测的。
- **一个效果两个操作，不拆成 `WallClock`/`MonoClock`。** 两种读数的生产 handler 总是一起装，测试也
  总是一起冻结。拆开会让每个程序多套一层 wrapper，而 wrapper 的套层次序已经是 std/io 要用测试看护
  的东西（「the six real wrappers nest」）。代价是只想冻结墙钟的测试也要写一条
  `clock_mono() => instant_at_ns(0)`，因为每个操作恰好一臂（spec §6.5）。
- **操作集合一次定对。** 同一条「恰好一臂」规则让往已发布效果里加操作成为对所有用户 handler 的破坏性
  变更；backend-dawn 今天就有 11 个安装点在答它自己的 `Clock`。所以 `Clock` 只放两个读数。
- **公开函数的行写 `!Clock`，生产 handler 体行写 `!e`。** 与 `Env` 的 `cwd() -> String !Env`、
  `with_env_real` 同形。新效果没有旧调用者，没有五族那种「先 `!io` 一个 release」的过渡；selfhost
  内的消费者要等种子推进到含本声明的 release（docs/bootstrap.md 特性纪律 4），packages 与 tea-term
  不受种子纪律约束，可以在同一 release 改用。
- **名字 `Clock`** 与 backend-dawn 的用户效果同名。两者身份不同，只有同一模块同时引入两者才冲突，
  且可以改名引入（spec §6.5 的 `use std/io.{Fs as Files}`），不构成改名理由。

## 验证

- `scripts/intrinsic-parity.py`：两个名字在表里有 `rt`，JVM 有方法、native 有 `dawn_` 函数。
- `scripts/builtin-decl-contract/run.sh`：P5 核对 comptime 标记与拒绝列表一致。
- `./bin/dawn test selfhost` 的三个计数测试各动二（builtin 表、intrinsic 表、comptime 拒绝列表），
  类型表测试断言两个名字是 `RtIo` 且 internal；`driver/analyze` 一条端到端测试：`const` 读钟在检查器
  就被拒，诊断写明 `!Clock`。
- std 测试：真 handler 下单调读数连读不减、两次读数之间做一段已知的工作后严格增大、墙钟过了
  2023 年；假 handler 冻结时间并逐次前进，`elapsed_ns` 的倒退读数饱和到 0；六个生产 wrapper 嵌套。
  测试**不打印读数**，因为 `dawn test --stdlib` 的转写要在两后端之间按字节一致。
- `scripts/wasm-contract/run.sh`：wasi 的 `clock_gettime` 能编、能链。

## 不做的（理由）

- **sleep**：仓内零消费者（全仓 `.dawn` 只有 `scripts/spike-native/ctl_vthread.dawn` 一个探针），
  tea-term 要的是读数不是睡眠；浏览器宿主没有阻塞睡眠，一次 reactor 调用必须答一条消息。放进
  `Clock` 会因「恰好一臂」逼每个只想冻结时间的假 handler 多写一臂，日后再加又是破坏性变更。
  将来出现不能用 `use java` 的消费者（native/wasm 上的重试退避、限速）时，以独立效果（暂名
  `Timer`）落地，届时一起裁「假钟如何同时答 now 与 sleep」：handler 局部格子每次安装私有
  （spec §6.5），两个 handler 共享不了一格虚拟时间。
- **`CLOCK_BOOTTIME`**：计挂起时间，语义上更好，但 JVM `nanoTime` 是 `CLOCK_MONOTONIC`，两后端
  对拍优先。
- **毫秒**：丢精度，见「单位」；要毫秒的调用方除以 1_000_000 即可（向零取整，spec §4.3）。
- **`(sec, nsec)` 元组返回**（Haskell `clock` 的 `TimeSpec`）：2262 年上界对一门 2026 年的语言可以
  接受；元组要装箱，且 builtin 签名多一种形状。
- **日历、时区、格式化**：原语只给纪元纳秒。backend-dawn 的 `LocalDate`/`LocalDateTime` 因此留在
  `use java`；日历是另一份设计，需求出现再立。
- **comptime 给固定值**：见上，静默的错答比诊断更糟。
- **C FFI**：时钟是两后端都有、语义一致的宿主查询，正是 intrinsic 契约的形状（10-04 FFI 裁决）。
