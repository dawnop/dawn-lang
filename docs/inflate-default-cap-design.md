# inflate 默认解压上界

> 状态：**current**。2026-10-03 裁决刀 1：`packages/inflate` 升 3.0.0（包名 `inflate3`），
> 四个解压入口与 `zip.entries` 的 `cap` 默认从「不设上界」改为 `Some(DEFAULT_CAP)`，
> 16 MiB。字节上界不等于内存上界那一半是公开 issue #405，见 §5：先做验收 (ii)，
> pkgfetch 的内存上界降到 32 MiB 并进 inflate-contract；(i) 的完整方案留在 §5.4。

## 1. 问题

inflate 2.0.0 的 `deflate.inflate`、`deflate.inflate_from`、`gzip.gunzip`、`zip.read`
都带 `cap: Option[Int] = None`，默认无上界；`zip.entries` 干脆没有 `cap` 参数。
上界机制本身是对的（写之前检查、超限返回 `Err`、gzip 多 member 共享一个总预算），
缺的是默认值。

这个包**只有一次性 API**：调用者忘了设上界，代价不是读得慢，而是进程 OOM。
DEFLATE 单流比率上限约 1032:1，`gzip -9` 实测 994 KB 展开成 1,024,000,000 B。

仓内唯一生产调用者是 `compiler-plan/src/pkgfetch.dawn`，它对 `gunzip` 与 `zip.read`
都**显式**传上界（刀 1 时是 256 MiB 总量、64 MiB 单条；#405 之后见 §5），不受默认值影响。web、playground、站点、
dawnop-site 后端都不经 inflate。所以改默认的仓内与下游破坏面是 0 处调用。

## 2. 做法

- `deflate.dawn`：`pub const DEFAULT_CAP: Int = 16777216`；`inflate`、`inflate_from` 默认
  `cap: Some(DEFAULT_CAP)`。`gzip.gunzip`、`zip.read` 默认 `Some(deflate.DEFAULT_CAP)`。
  `None` 是显式的「不设上界」。签名形状不变，只有省略 `cap` 的含义变了，所以是 major。
- `zip.entries(src, cap: Option[Int] = Some(DEFAULT_CAP))`：一个上界管**全部条目**的总输出，
  逐条传剩余预算，与 `gunzip` 管多 member 同一语义。中央目录可以让多条记录指向同一段压缩
  数据（Fifield，*A better zip bomb*，USENIX WOOT 2019），按条计费的上界乘以条目数等于没有上界。
- 命中默认上界的报错在原文后追加默认值与出路：

  ```
  deflate: the output exceeds the 16777216 byte limit (stopped at 16776967 bytes); the default cap is 16777216 bytes: pass cap: Some(n) for a larger limit, or cap: None for no limit
  ```

  「是不是默认」按值判断（`lim == DEFAULT_CAP`），显式传 `Some(DEFAULT_CAP)` 也带这句，
  话仍然成立。容器里第一个 member / 条目拿的是整份默认值，由 deflate 自己加注；之后的拿的是
  剩余预算（调用者没见过的数），由 gzip / zip 在外层补注，已有注的不重复加。只给上界拒绝加注，
  损坏的流不会因为放大上界而变好。
- 包内测试钉住三处文案；`scripts/inflate-contract/run.sh` 加一条腿：Java 造的 512 MB 炸弹，
  不传 `cap`，在 256 MB 堆里依次喂 `deflate.inflate`、`gzip.gunzip`（单 member 与「小 member +
  炸弹」）、`zip.entries`，四处都必须以默认上界的文案拒绝。

## 3. 数值依据

上界数的是**输出字节**，而今天 `bytes.Buf` 是 `Array[Int]`，每个输出字节占的内存远大于 1 B
（调研实测：JVM 零字节约 10 到 16 B、`0xFF` 约 16 到 30 B；native 约 32 B）。默认值的意义是
「忘了设也不崩」，所以取的是今天的内存倍数下在工具链自己的 `-Xmx2g` 里对任意输入都安全的那档：

| 默认 | JVM 峰值（实测折算） | native RSS（实测） | `-Xmx2g` 下 |
|---|---|---|---|
| 16 MiB | 约 0.25 到 0.5 GB | 约 0.56 GB | 安全 |
| 64 MiB | 约 1 到 2 GB | 约 2.1 GB | `0xFF` 输入贴边 |
| 256 MiB | 超出 | 约 8 GB | 零字节输入即 OOM |

合理负载的量级：dawn-lang 自身 tag 归档 tar 25.2 MB、zip 8.3 MB，走的是 pkgfetch 的显式上界。

## 4. 不做的（理由）

- **比率上界。** 一次性 API 开始解压时已知 `len(src)`，比率只是推导出来的绝对上界；合法的高比率
  输入（全零、稀疏数据）存在；默认值不能引用形参，写不出来。Apache `mod_deflate` 需要它是因为
  请求体流式到达。
- **流式 API。** 没有需求方，Dawn 也还没有 Bytes 流抽象；以后要做与本刀不冲突。
- **强制必填 `cap`。** 把 K3 刚收掉的噪音换个形式加回每个调用点，且挡不住人人写 `cap: None`。
- **`Limit` 枚举、哨兵 `Int`。** 前者为「一个可选的数」新造类型，`Option[Int]` 已经说清楚；
  后者复刻 Node `kMaxLength` 式的伪默认。
- **默认 64 MiB 或 256 MiB。** 见 §3，今天在 `-Xmx2g` 下不稳。`bytes.Buf` 换成真字节缓冲后
  再评（放宽上界不让任何原先成功的调用失败，minor 即可）。
- **web 请求体解压。** web 今天不解码 `Content-Encoding`，`max_body` 管的是线上字节；要开这个口子
  必须另设解压后上限，且要等内存倍数修好。

## 5. pkgfetch 的内存上界（#405）

### 5.1 复现

经 pkgfetch 本身复现，入口是 `dawn add file://<archive>`（`fetch_and_hash` → `unpack`，与
`dawn build` 拉 `[deps]` url 同一条路），`bin/dawn` 默认的 `-Xss512m -Xmx2g -XX:+UseSerialGC`，
外加 `ulimit -v` 与 `timeout`。炸弹是 Python 流式造的约 1 MB 归档，内容是 1 GiB 的 `0xFF`：

| 归档 | 当时的上界 | 结果 | 峰值 RSS | 墙钟 |
|---|---|---|---|---|
| tar.gz（整流先 gunzip） | 256 MiB | `java.lang.OutOfMemoryError: Java heap space` | 2.13 GB | 74.5 s |
| zip，目录谎报条目 1000 B | 单条 64 MiB | `Err`（`exceeds the 67108864 byte limit`） | 2.14 GB | 9.7 s |
| zip，诚实的 64 MiB 条目 | 单条 64 MiB | 解开（之后因不是 Dawn 包而报错） | 2.30 GB | 13.8 s |

tar.gz 一路是确定的崩溃；zip 一路今天拒得住，但堆已经满了，只差一档。

同一个 1 GiB `0xFF` gzip 直接喂 `gzip.gunzip(cap: Some(n))`，在同样的 JVM 参数下扫上界：

| 上界 | `-Xmx2g` 下 | 峰值 RSS | 墙钟 |
|---|---|---|---|
| 32 MiB | `Err` | 1.38 GB | 1.6 s |
| 48 MiB | `Err` | 2.03 GB | 4.3 s |
| 64 MiB | `Err`，满堆反复回收 | 2.15 GB | 13.3 s |
| 80 / 96 / 128 MiB | OOM | 2.16 GB | 69 到 85 s |

最小可用堆：16 MiB 要 384m 以上（384m OOM，512m 拒绝），32 MiB 要 768m 以上（768m OOM，1g 拒绝），
48 MiB 在 1536m 下 OOM。折算每输出字节约 32 B 堆（`0x80` 到 `0xFF` 每个都是独立的装箱 `Long`，
外加 `Array` 扩容时的旧新两份引用数组），与 §3 的调研倍数一致，取的是上沿。

### 5.2 选路：做 (ii)，(i) 留后

issue 的验收二选一：(i) `Buf` 换真字节缓冲；(ii) 先降 pkgfetch 常数并加门。这一刀做 (ii)，理由：

- **(i) 牵动 tile 路径。** `bytes.Buf` 的调用者除了 inflate 与 pkgfetch，还有
  `packages/tileir/src/bytecode.dawn`（Tile IR 字节码写出）、`std/gpu.dawn`、web、tea-term、
  `scripts/tile-gpu-diff/seq_diff.dawn`。换表示会让 tileir 的字节码写出走新代码，tile 台账与
  goldens 都要重验，任务单要求 (i) 不碰 tile 路径，这一条已经不满足。
- **(i) 不是一刀。** 它要的是一个新的运行时值（不能复用 `Array[Int]`：元素是擦除的，后端无从按
  `Int` 特化），面是：类型表与 intrinsic 契约（`types.dawn` 的 `bsig` / `Intr` / `rt_of`，
  checker 的 std-only 限制与效果表）、`selfhost/builtins.dawn` 镜像（双向对账门禁）、JVM 后端
  `rtclasses.dawn` 用 ASM 生成一个新运行时类、native 后端 `runtime/c/dawn_rt.{c,h}` 加结构体与
  引用计数、`emitc.dawn` / `rc.dawn` 的类型映射、comptime 解释器拒绝、spec §9.5.1、`std/bytes.dawn`
  与 `gen-stdsrc.py`、一份像 array-contract 那样钉「独占时原地扩展」的合约。每一项都不难，合起来
  是一条线，不是一刀。
- **(ii) 今天就关掉崩溃。** 崩溃发生在 `dawn add` / `dawn build` 的不可信输入路径上，
  (ii) 只动两个常数和三处用法，门也能直接站在 pkgfetch 上。

### 5.3 做法

- `compiler-plan/src/pkgfetch.dawn`：`MAX_ENTRY_BYTES`（64 MiB）改名并收紧为
  `MAX_EXPANDED_BYTES = 33554432`（32 MiB），同时管 zip 单条目（声明大小检查与传给 `zip.read`
  的 `cap`）与 tar.gz 的整流 gunzip（原来传的是 `MAX_ARCHIVE_BYTES`，256 MiB）。改名是因为它的
  意义变了：它是「同一时刻解压进内存的量」，是内存上界，不是归档的字节数。
- `MAX_ARCHIVE_BYTES` 保持 256 MiB：下载体（`curl --max-filesize` 与读回后的长度检查）与 zip 落盘
  总量都是每字节 1 B 或根本不在内存里，它们是字节上界，没有倍数问题。最坏的叠加是 256 MiB 的
  下载体加 32 MiB 条目的解压峰值约 1 GiB，仍在 `-Xmx2g` 之内。
- 32 MiB 的依据：最坏字节下约需 1 GiB 堆，是 `-Xmx2g` 的一半（48 MiB 能拒但堆几乎满，64 MiB 要满堆
  回收 13 s）；合理负载方面，本仓 tag 的 tar 是 25.4 MB（`git archive` 实测，v0.50.0 时 9.0 MB、
  v0.81.0 时 23.2 MB），zip 单文件最大 0.63 MB（`checker.dawn`）。tar.gz 一路离上界只剩约 30%，
  这正是 (i) 要解决的；在那之前 GitHub 依赖请用 `.zip`，它逐条解压，32 MiB 只管单个文件。
- 改后同样三份归档：tar.gz `Err`（`exceeds the 33554432 byte limit`），RSS 1.55 GB，3.2 s；
  谎报 zip `Err`，RSS 1.58 GB，3.9 s；诚实的 64 MiB 条目在声明大小检查处就被拒，0.4 s。
- native 工具链没有堆上限，按调研的约 32 B/字节 RSS，tar.gz 一路的最坏峰值从约 8 GB 降到约 1 GB。

门：`scripts/inflate-contract/run.sh` 末尾加一条腿（不新增 job），`pkgbomb.py` 流式造 1 GiB `0xFF`
的 tar.gz 与目录谎报的 zip，清掉 `DAWN_JVM_OPTS` 让堆就是 `bin/dawn` 钉的那个，跑
`dawn add file://...`：必须失败、输出里必须有上界的原话、不得出现
`OutOfMemoryError`。原话自 10-04 起要点名 pkgfetch 自己的上界（`exceeds the <MAX_EXPANDED_BYTES> byte limit (stopped at`，
数值从 `pkgfetch.dawn` 源码读），理由与负控见 §5.6。负控两份，都用改过的 pkgfetch 重建工具链再跑整份合约：

- pkgfetch 换回父提交的版本（tar.gz 256 MiB、zip 64 MiB）：tar.gz 腿 OOM，合约红；
- 只把 zip 的单条上界改成 128 MiB：tar.gz 腿绿，zip 腿 OOM，合约红。

### 5.4 (i) 的完整方案（留后续）

- **类型**：新的 std-only 内建类型（暂名 `ByteBuf`），与 `Array` 同级：用户代码不能直接写，
  只有 std 能用（`types.dawn` 中 `bytes_from_array` 那条「也点名 Array，所以 std-only」的规则照抄）。
  `std/bytes.dawn` 的 `opaque type Buf = ByteBuf`，公开面（`buf` / `put` / `put_bytes` / `size` /
  `buf_at` / `freeze`）一个字都不变，所以 inflate、tileir、web 等调用者不改源码。
- **原语**（`RtBytes` 模块）：`bytebuf_new`、`bytebuf_push(b, x) -> ByteBuf`、`bytebuf_len`、
  `bytebuf_at`、`bytebuf_freeze -> Bytes`。值语义与 `array_push` 同一个子句：版本是共享缓冲上的
  窗口 `[0, len)`，缓冲记录「发出过的最高位置」，`len` 等于它时原地追加，否则复制。
  JVM 后端是 `byte[]` 加 `AtomicInteger used` 加 `len`（`rtclasses.dawn` 里照 `gen_array_class`
  生成）；native 是 `dawn_bytebuf { hdr; uint8_t *data; cap; high }` 加引用计数，单线程不需要 CAS。
  `freeze` 复制 `[0, len)`，Bytes 保持不可变。
- **自举**：种子用自己的 std 编 stage A，所以 HEAD 的 `std/bytes.dawn` 可以在同一提交里改用新原语，
  `selfhost/src` 与 `compiler-plan` 本身不直接调用原语，不受「种子已支持」的限制（落地时要用
  fixpoint 与 native-fixpoint 实测确认，这一条是推断）。
- **门**：一份 bytebuf 合约（值语义 + 原地扩展的时钟断言，形状照 `scripts/array-contract`），
  `dawn test --stdlib`、两个 fixpoint、builtin 镜像对账、tile goldens 与 tile-gpu-diff 台账
  （因为 tileir 走 `Buf`），prev-diff 的 `emit` label 照实声明。
- **之后**：每字节约 1 B，本节的 `MAX_EXPANDED_BYTES` 与 §3 的 `DEFAULT_CAP` 都按新倍数重评
  （刀 3，放宽是 minor），本节的 inflate-contract 腿原样保留，作为新表示的回归门。

### 5.6 复测与门的收紧（2026-10-04）

在 `e89f6a46` 上经 `dawn add file://...` 复测，JVM 是 `bin/dawn` 默认的 `-Xss512m -Xmx2g -XX:+UseSerialGC`，
native 是 `nmain` 经 `__emitc` 加 `cc -O2` 出的驱动（native 的 `add` 与 JVM 是同一个 `pkg/add` 与
`compiler_plan/pkgfetch`）。都在 `ulimit -v` 与 `timeout` 下跑：

| 归档 | JVM 结果 | JVM 峰值 RSS / 墙钟 | native 结果 | native 峰值 RSS / 墙钟 |
|---|---|---|---|---|
| tar.gz，1 MB，1 GiB `0xFF` | `Err`（32 MiB 上界） | 1.57 GB / 2.9 s | `Err` | 1.09 GB / 1.6 s |
| zip，1 MB，目录谎报 | `Err`（32 MiB 上界） | 1.60 GB / 2.7 s | `Err` | 1.09 GB / 1.5 s |
| zip，235 MB：7 个 31.9 MiB 随机 stored 条目，末条是谎报的 `0xFF` 炸弹 | `Err` | 2.05 GB / 5.6 s | `Err` | 1.33 GB / 10.8 s |
| tar.gz，232 MB：1 GiB `0xFF` 后接 220 MiB 随机 | `Err` | 2.00 GB / 2.9 s | `Err` | 1.33 GB / 2.4 s |
| zip，234 MB：同上 7 个 stored 条目加一个诚实的 32 MiB `0xFF` 条目 | 解开（之后报不是 Dawn 包） | 2.21 GB / 13.4 s | 同 | 1.33 GB / 87 s |

后三行是两个上界同时顶满的最坏组合：下载体 `A`（每字节 1 B）与一次解进内存的 `E`（`0xFF` 下每字节约
24 到 32 B）。所需堆约为 `A + 32·E`，`A = 256 MiB`、`E = 32 MiB` 时约 1.25 GiB。实测最小堆：
235 MB 那份谎报 zip 在 `-Xmx1024m` 下 OOM（31 s），`-Xmx1280m` 拒绝；单独的 1 MB 炸弹在 `-Xmx1024m`
下就拒绝。所以 `-Xmx2g` 下最坏组合还有约 0.7 GiB 余量，`MAX_ARCHIVE_BYTES` 不必降（§5.5 第一条的
推理有了实测）；native 没有堆上限，最坏 RSS 1.33 GB。

生态里的真实负载：唯一的 url 依赖消费者是 dawnop-site 后端，拉本仓 tag 的 `.zip`；本仓 `HEAD` 的
`git archive` 为 zip 8.8 MB、tar.gz 7.7 MB、展开 26.7 MB，单文件最大 0.66 MB（`checker.dawn`）；
`packages/` 里最大的是 tileir，tar 0.83 MB。zip 一路离两个上界都很远；tar.gz 一路展开量已是
`E` 的 80%，这一条仍要等 (i)，在那之前 GitHub 依赖用 `.zip`。

门的收紧：原先只要求输出里有 `byte limit (stopped at`，任何上界的拒绝都满足它。变异体「`untar` 的
`gunzip` 不传 `cap`」会被 inflate 的 16 MiB 默认上界拒绝，旧门照绿，可 pkgfetch 自己的上界已经
没人量了。现在合约从 `compiler-plan/src/pkgfetch.dawn` 读出 `MAX_EXPANDED_BYTES` 的值，要求拒绝
原话点名这个数。负控：上面这个变异体，新门红、旧门绿；把 `MAX_EXPANDED_BYTES` 改回 256 MiB，
tar.gz 腿 `OutOfMemoryError`，合约红（84 s）。读源码这一步也让 gate-map 把这条腿记成
`pkgfetch.dawn` 的门（之前 `gatemap.py compiler-plan/src/pkgfetch.dawn` 列不出 inflate-contract）。
墙钟：整份合约本机 38.5 s，新增的是一次 `sed`，可忽略。

### 5.5 不做的（理由）

- **把 `MAX_ARCHIVE_BYTES` 一起降。** 它管的是下载体与落盘总量，每字节 1 B，降它只会误伤合法的大
  归档，挡不住内存问题；内存问题只出在「一次解进内存的量」上。
- **按 `-Xmx` 动态算上界。** 上界会变成机器属性，同一个依赖在不同堆下一会儿能装一会儿不能装；
  `bin/dawn` 把堆钉成 2g 正是为了不让构建结果依赖机器。
- **在 inflate 里分块冻结输出来压倍数。** 能把峰值降到每字节几 B，但它是绕开 `Buf` 表示的局部补丁，
  (i) 落地后就是死代码；该修的是表示本身。

### 5.6 (i) 落地：分块 `Buf`（2026-10-05，#405）

调研 `research-bytes-buf-repr-20261004.md` 比了 §5.4 的新运行时类型（方案 A）与只改 std 的分块缓冲
（方案 B，Haskell `ByteString.Builder` 的形状），裁先做 B，A 作 B 吞吐不达标时的后手。落地的是 B：

- `std/bytes.dawn` 的 `Buf` 改成 `opaque type Buf = BufRep`，`BufRep = { chunks: Array[Bytes], tail: Array[Int] }`：
  已写满的块各恰好 4 KiB，冻成 `Bytes`；没写满的那一块仍是装箱的 `Array[Int]`。`put` 推尾部，满了
  `bytes_from_array` 冻成一块；`buf_at` 用移位与掩码找块；`put_bytes` 在块边界上整块 `bytes_slice`，
  不再逐字节装箱；`freeze` 平衡二分拼接（每字节每层复制一次，层数是块数的 log2），不是逐块 `++`
  （那是 O(n²/块)）。
- 公开面六个函数与类型 `Buf` 的签名、文档注释一字未改，329 处调用点不改源码；值语义仍是 `array_push`
  的子句，作用在两个数组上：旧版本继续写只复制它自己的尾部（std 新增三条测试钉块边界上的读回、
  旧版本续写与 `put_bytes` 和逐字节 `put` 等价）。越界的 `buf_at` 仍然 panic，文案从数组的越界
  文案改成 `bytes.buf_at: index out of range`，与文档所说「同 `at`」对齐。
- 不加原语、不动后端、不动解释器与镜像，所以不需要两次发版。

实测（本机 16 核 WSL2，同一时段交错跑 5 轮，load 1.3 到 2.7；JVM 探针 `-Xmx6g -XX:+UseSerialGC`，
tileir 与 inflate 用 `bin/dawn` 的 `-Xmx2g -XX:+UseSerialGC`；native `cc -O2`；表中是中位数）：

| 测量 | 改前 | 4 KiB 块 | 64 KiB 块 |
|---|---|---|---|
| 探针 32 MiB `0x00`，JVM 峰值 RSS（每字节） | 539 MB（15.6 B） | 210 MB（5.3 B） | 225 MB（5.8 B） |
| 探针 32 MiB `0xFF`，JVM 峰值 RSS（每字节） | 1350 MB（40.9 B） | 214 MB（5.4 B） | 227 MB（5.8 B） |
| 探针 32 MiB，native 峰值 RSS（每字节，与字节值无关） | 1090 MB（34.0 B） | 99 MB（3.0 B） | 98 MB（3.0 B） |
| 探针 32 MiB `0xFF`，JVM 最小可用堆 | 1024m 不够、1280m 够 | 120m 不够、124m 够 | 112m 不够、128m 够 |
| 探针墙钟 JVM `0xFF` / native | 1.26 / 1.43 s | 0.45 / 1.06 s | 0.47 / 1.47 s |
| tileir 大模块（5000 条 addf 各带常量，20 万元素的 global，编码 20 次），JVM | 8.63 s | 7.56 s | 7.63 s |
| 同上，native | 36.26 s | 31.38 s | 31.67 s |
| inflate 解 26.7 MB（本仓 `git archive` 的 tar.gz，`cap: None`），JVM | 2.03 s，1193 MB | 1.22 s，326 MB | 1.25 s，355 MB |
| 同上，native | 6.85 s，935 MB | 5.69 s，87 MB | 5.82 s，108 MB |

探针把 `Buf` 与冻好的 `Bytes` 都留到退出，所以每字节的下限本来就是 2 B（块一份、结果一份），
冻结时平衡拼接的最上一层再加约 1 B 的瞬时量；JVM 的 RSS 口径还含未回收的中间层，最小可用堆
124m（约 3.9 B/字节）是活对象口径。三组都不退化，反而全快：装箱对象少了，GC 与数组扩容复制
都跟着少。块大小取 4 KiB：每一组都不慢于 64 KiB（native 探针快 28%），尾部的装箱量也小。

之后：`MAX_EXPANDED_BYTES` 与 `DEFAULT_CAP` 按新倍数重评是刀 3（另派），本刀不动；§5.3 的
inflate-contract pkgfetch 腿原样保留作新表示的回归门。`bytes_concat` 原语（刀 2）看拼接是否成为
瓶颈再说，上表里没有它是瓶颈的迹象。

不做的（理由）：

- **方案 A（`ByteBuf` 运行时类型）。** 内存数量级与 B 相同（每字节 1 B 对约 1 到 3 B），吞吐上 B 已经
  快于改前，A 剩下的好处不抵一条线的改动面与两次发版。
- **逐块 `++` 冻结。** 32 MiB / 4 KiB 是 8192 块，前缀被复制 8192 次，约 128 GiB 的复制量。
- **块大小不定长（按写入量倍增）。** `buf_at` 就要二分找块，LZ77 回指是 inflate 的热路径；定长块
  一次移位一次掩码。
