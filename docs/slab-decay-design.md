# native slab 空闲页的衰减式保留

> 状态：**current / 已落地**。来源是 2026-10-11 的 Koka 差距调研（R2）：binarytrees
> 在 native 上每轮 595,164 次缺页，sys 时间占 32%，而 Koka 是 167 次。本文只讲
> **保留策略**；「mimalloc 永久否决」不动，slab 这个决定也不动。
> 前置阅读：[slab-residency-design.md](slab-residency-design.md)（slab 的整体形状、
> 32 KiB tranche、empty cache 的由来）。

## 1. 问题

`runtime/c/dawn_rt.c` 的 slab 分配器把退下来的整块空 slab 按 size class 缓存，**每个 class
最多 `DAWN_SLAB_KEEP = 4` 块**，超出的立刻 `madvise(MADV_DONTNEED)` 还给内核，下次要用
再缺页。对「建一棵树、释放、再建一棵」这种分配密集的循环，这等于每一轮都把刚还掉的页
再缺回来。

实测（WSL2，Ryzen 7 9700X，`clang-20 -O2`，`/usr/bin/time -v`，binarytrees n=19）：

| 配置 | 墙钟（最短） | sys | 缺页 | 峰值 RSS |
|---|---|---|---|---|
| `KEEP=4`（现状） | 2.400 s | 0.80 s | 595,164 | 100.6 MB |
| `KEEP=1024` | 1.490 s | 0.03 s | 26,788 | 100.6 MB |

`KEEP=1024` 把墙钟砍掉 38%，峰值 RSS 一字节不变：被反复缺回的页本来就在峰值里。
调研原始数据见 `research-koka-gap-20261011.md` §4.6（私有交接文档，数字已在上表复测）。

但**不能直接把 `KEEP` 改成 1024**。`KEEP` 同时是「空闲驻留的上界」：头文件把它写成
规格级的断言（128 个 class × 4 × 64 KiB = 32 MiB 以内），`scripts/rc-contract` 用一个写死
的 `33554432` 钉着它，`slab-residency-design.md` 的 lexer 小活集 RSS 也在这条线上。
1024 把上界推到 8 GiB，等于没有上界；一个突发之后永远不还的进程，就是这个分配器
当初存在的理由（`malloc` 不还页）的倒退。

## 2. 方案：按区间最小值衰减（interval-minimum decay）

不再给 empty cache 一个固定上限，而是**让它自己衰减**：

- 每个 size class 记 `empty_low`：自上次清扫以来 empty cache 的**最低水位**（每次从 cache
  取走一块时更新）。
- 每过 `DAWN_SL_DECAY_MS`（默认 1000 ms）清扫一次：每个 class 释放 `empty_low − KEEP` 块
  （不低于 `KEEP`），然后 `empty_low := empty_n`。
- 退役（slab 的最后一个对象被释放）**一律进 cache**，不再就地 `madvise`。

「最低水位」的含义：一个区间里 cache 从来没有降到过 `low` 以下，说明那 `low − KEEP`
块这一整段时间**一次都没被用到**，是真正的富余；一个循环不断建、不断放的 class，
cache 每个周期都被抽空到接近 0，`low` 就是 0，什么也不会被释放。这就是 jemalloc、
mimalloc 的 decay 想表达的同一件事，只是这里不需要后台线程。

与调研任务单里的「高水位 + 批量释放、按近期峰值缩放」比较：高水位要选一个数（相对
近期峰值多少？），选错一边就退回 4 或退回 1024；区间最小值**不含需要调的比例**，
只含一个时间常数，而时间常数只决定「富余多久才还」，不影响分配循环的缺页数。

### 2.1 谁来敲钟

分配器是单线程的，没有后台线程，也不该有（信号处理函数里不能碰空闲链表）。时钟只在
**本来就已经离开快路径**的地方读：

1. `dawn_sl_slow`（取新 batch、换 slab）；
2. `dawn_sl_retire`（一整块 slab 退下来）；
3. `dawn_sl_put` 里 **current slab 降到 `used == 0`** 时，每 256 次读一次钟；
4. 阻塞原语入口（§2.2，这一条不是敲钟，是立即归还）。

第 3 条是实测逼出来的：稳态循环（每轮只在一个 class 的 current slab 里分配再释放）既不取
新 batch 也不退役，前两处永远不触发，爆发之后的 194 MB 一直不还（§4.3 第一次实验）。
`used` 的减一本来就在，这里只多一次与零的比较；而「一个 class 每次只活一个对象」的最坏
形状每次释放都会命中它，所以才要 256 次一读（16 次一读时该形状 +9%，256 次时 +4.5%，
§4.4）。

### 2.2 阻塞前的规则

被阻塞的进程不能再扫第二次，所以规则取最简单且能保证的一条：

> **进入一个可能长时间阻塞的原语时，若此刻不能立即得到结果，先把每个 class 的 empty cache
> 一次性释放到 `KEEP`（`dawn_slab_before_block`），再阻塞。**

保证：爆发之后阻塞的进程，在阻塞开始之前就已把富余还掉，不依赖区间、不依赖第二次清扫。
不能立即得到结果的判定对 stdin 是 `poll(0, POLLIN, 0) == 0`：喂文件或管道里已有数据的
程序不付这个代价，缓存跨行保留；`io_run` 的 `waitpid` 无条件归还（子进程运行多久未知，
且 spawn 本身远比一次 `madvise` 贵）。代价与旧行为同阶：一个「每个请求一次爆发、请求之间
阻塞在 stdin」的服务，每个请求结束就回到 `KEEP=4` 的状态，下个请求重新缺页，与改动前相同，
不更差。

逐个核对 `dawn_rt.c` 的原语：

| 原语 | 判定 | 理由 |
|---|---|---|
| `dawn_io_read_line` | 钩 | 入口 `dawn_stdin_may_block()`；入口时有数据、中途才停的半行不再检查（逐字节 poll 会让读行慢一倍） |
| `dawn_io_read_stdin` | 钩 | 每次 `read(2)` 前检查（块粒度，便宜） |
| `dawn_io_stdin_ready` | 钩 | `timeout_ms > 0` 时检查；零超时是探测，不阻塞 |
| `dawn_io_run`（`waitpid`） | 钩（无条件） | 等子进程，时长未知 |
| sleep、socket、accept | 无 | 运行时里没有这些原语（grep 过 `sleep`、`socket`、`accept`、`connect`、`select`） |
| `dawn_slurp`（`read_file`/`read_bytes` 的 `fread`） | 不钩 | 读的是文件路径，常规文件不阻塞；读 FIFO 属于误用，不为它在每次读文件前多一次 `poll` |
| ctl 载体线程的 `pthread_cond_wait`/`join` | 不钩 | 同进程内协程交接，等的是自己的另一半，不是外部事件 |
| `dawn_io_clock_*`、`write_*`、`print*` | 不钩 | 不阻塞（写管道写满可阻塞，但那是下游慢，不是等输入，不为它每次写加检查） |

### 2.3 契约怎么变

- 头文件那句「至多 32 MiB 空闲」改成：**连续两个静默区间之后**至多 `KEEP × 128 × 64 KiB`
  = 32 MiB。两个区间，因为第一次清扫只记录水位，第二次才释放。
- `scripts/rc-contract` 的 `slab_returns_pages`、`slab_bound_is_honoured` 在断言前调用测试
  专用的 `dawn_slab_quiesce()`（连扫两次，等价于两个静默区间）；新增 `slab_retains_a_burst`
  断言反方向：突发释放后 **不** 立即还（`retired` 不动、`cached` 涨 100 块以上），清扫后
  才还。`slab_returns_before_blocking`：突发后在真实的 `read_stdin` 上阻塞，管道的写端是
  fork 出的子进程，它等 0.5 s 后从 `/proc` 读父进程**阻塞期间**的 RSS 并写回管道；断言该
  RSS 与基线相差不到 8 MiB。在上一版（只有 `dawn_slab_idle` 钟）上这条断言是红的，
  本版绿；mutant `slab-blocks-without-returning` 拥有它。
- mutant：`slab-never-retires` 改成「清扫永不释放」；新增 `slab-releases-at-once`（旧行为：
  超过 `KEEP` 就地释放），由 `slab_retains_a_burst` 独占。

## 3. 落点

| 文件 | 改动 |
|---|---|
| `runtime/c/dawn_rt.c` | `dawn_sl_release`（从 retire 里拆出）、`dawn_sl_sweep`、`dawn_sl_tick`；retire 一律进 cache；`dawn_sl_slow`、current 清零处敲钟；`dawn_slab_before_block`；`read_line`/`read_stdin`/`stdin_ready`/`io_run` 入口的钩子 |
| `runtime/c/dawn_rt.h` | `DAWN_SLAB_KEEP` 注释改成「衰减后的下限」；`dawn_slab_before_block`；契约专用 `dawn_slab_quiesce` |
| `selfhost/src/embed/rtsrc.dawn` | `scripts/gen-rtsrc.py` 重新生成 |
| `scripts/rc-contract/*` | 见 2.3 |

不改 emitc、不改发射的 C：`Emit-Change` 不涉及（运行时随 C 一起内嵌，只影响运行速度与
驻留，不影响任何发射文本）。

## 4. 实测

机器：AMD Ryzen 7 9700X、WSL2、内核 6.18，**负载不静**（其他写者在跑，1 分钟负载
3.8 到 4.7）。`clang-20 -std=c11 -O2 -fwrapv -fexceptions -fno-strict-aliasing`，
同一份发射的 C 只换运行时；每格 5 次交错取最短墙钟，缺页取最小，RSS 取最大。
`base` = `origin/main` 的运行时，`new` = 本方案，`k1024` = 仅把 `KEEP` 改成 1024（参照上界）。

| 基准 | 配置 | 墙钟（最短） | sys | 缺页 | 峰值 RSS |
|---|---|---|---|---|---|
| binarytrees 19 | base | 2.400 s | 0.80 s | 595,164 | 100.6 MB |
| | **new** | **1.470 s（−38.8%）** | 0.02 s | 24,743 | 101.1 MB |
| | k1024 | 1.490 s | 0.03 s | 26,788 | 100.6 MB |
| rbtree | base | 3.910 s | 0.11 s | 65,786 | 264.8 MB |
| | new | 4.110 s | 0.09 s | 65,790 | 265.1 MB |
| | k1024 | 4.070 s | 0.09 s | 65,787 | 264.7 MB |
| rbtree-ck（cons） | base | 7.810 s | 1.35 s | 523,867 | 2,086.6 MB |
| | new | 8.040 s | 1.31 s | 523,870 | 2,090.8 MB |
| | k1024 | 8.410 s | 1.48 s | 523,868 | 2,090.8 MB |
| deriv | base | 3.460 s | 0.45 s | 231,386 | 927.2 MB |
| | new | 3.280 s | 0.37 s | 231,389 | 927.5 MB |
| | k1024 | 3.520 s | 0.42 s | 231,385 | 927.1 MB |
| cfold | base | 0.590 s | 0.20 s | 120,631 | 477.4 MB |
| | new | 0.650 s | 0.18 s | 120,634 | 481.9 MB |
| | k1024 | 0.660 s | 0.18 s | 120,630 | 481.7 MB |

读法：

- **只有 binarytrees 受益**，而且 `new` 与上界 `k1024` 同值（1.47 对 1.49 s，缺页 24.7k 对 26.8k）。
- 另外四个的缺页与 `base` 相同到个位数：它们的缺页是堆**增长**的首次触碰（RSS 就是
  峰值），保留策略碰不到。调研里「rbtree-ck 18%、cfold 30%、deriv 14% 的 sys 时间」
  因此**不是**这一刀的目标，它们的墙钟差（−5% 到 +10%）是噪声：交错 5 次，但跑的时候
  机器负载从 3.8 升到 8.2（其间还跑过 `doc-check`），`k1024` 在 rbtree-ck 上反而最慢。
- **RSS 代价**：峰值 RSS 在 deriv、rbtree 上 +0.3 MB 以内，在 rbtree-ck +4.2 MB（+0.2%），
  在 cfold +4.5 MB（+0.9%）；它们的 cache 在爆发期间不再被边增长边还回。binarytrees
  +0.5 MB。

### 4.3 突发之后会不会还

`burst.dawn`：先建并释放一棵 2^21 层的树（峰值 194 MB），随后只做每轮约 24 KB 的小
分配释放循环 3.7 s。每 100 ms 采样 `/proc/<pid>/status` 的 `VmRSS`：

| 采样点 | base | new |
|---|---|---|
| 0.1 s（爆发后） | 194 MB | 194 MB |
| 0.2 s | 2 MB | 194 MB |
| 1.0 s | 2 MB | 194 MB |
| 1.9 s | 2 MB | 194 MB |
| 2.0 s | 2 MB | 151 MB |
| 2.1 s 起到 3.7 s 结束 | 2 MB | 2 MB |

`base` 在 0.2 s 内还完；`new` 保留约 2 个清扫间隔，第二次清扫（约 2 s）一次释放全部富余
（`madvise` 约 190 MB 用时在一个 100 ms 采样内）。此后稳态循环不缺页（`new` 的 3.7 s 里 sys
时间可忽略）。

这一行的前提是 §2.1 的第 3 条敲钟：去掉它，同一个程序整整 3.7 s 内一直是 194 MB。

### 4.4 快路径代价

最坏形状：每轮分配释放一个对象（`one.dawn`，1 亿次，该 class 的 current slab 每次释放都
降到 0）。

| 配置 | 墙钟（最短，9 次交错） |
|---|---|
| base | 1.100 s |
| new（256 次一读） | 1.150 s（+4.5%） |
| new（16 次一读） | 1.200 s（+9%） |

1 亿次、约 11 ns 一轮，增加约 0.5 ns。这是**人为最坏**：真实程序在同一 class 里很少
每次释放都清空 current slab。代价是真的，不抹平。

### 4.5 小活集的静默 RSS

`scripts/slab-bench/run.py`（eager = `base`，candidate = `new`，每格 6 次交错取中位数）在
「churn 结束、`ready` 行刚打印」的瞬间采 `VmRSS`：

| workload | base quiet | new quiet（刚 ready） | new 静默 2.5 s 后 | HWM base / new |
|---|---|---|---|---|
| lexer | 4.9 MB | 10.3 MB | 4 MB | 10.3 / 11.4 MB |
| rbtree | 2.8 MB | 20.4 MB | 2 MB | 20.1 / 20.4 MB |
| compiler | 20.6 MB | 495.6 MB | 20 MB | 529.6 / 534.5 MB |

这是本方案**最诚实的代价**：「分配完立刻看」的驻留，在 harness 的采样点上仍是突发峰值。
重测（含阻塞前归还，`sb4`）：lexer 8.7 MB、rbtree 18.8 MB、compiler 493.7 MB，而 `base` 为
4.9、2.8、20.6 MB。原因是 harness 在进程打印 `ready` 的**同一时刻**采样，进程此时还没走到
`stdin_ready` 里的归还；同一批二进制用 `ready` 之后每 0.5 s 采样：首个样本（0.0 s）lexer
8、rbtree 18、compiler 483 MB，**0.5 s 起** 4、2、20 MB，与 `base` 相同。HWM 相差 1 MB 到
5 MB，是 cache 在爆发期间不被边还边增长的代价。

结论：阻塞在 stdin 或等待子进程的程序，在阻塞开始时就归还（§2.2）；不阻塞也不分配的
程序，要等到下一次分配器活动才会扫（§5）。短命的一次性程序（编译器本体）不受影响，
退出时内核全部回收。

## 5. 没解决的

- **半行与逐块阻塞。** `read_line` 只在入口检查：入口时已有数据、读到一半对端停住，
  这次阻塞前不归还（下次进入原语时归还）。
- **不阻塞也不分配的循环**（纯计算）不会触发归还；它也不产生新的富余，持有量不再增长。
- **cur slab 钉着长命对象的 class 不敲钟。** 第 3 条触发依赖 current slab 降到 0。

## 6. 不做的（理由）

- **不接 mimalloc。** 已被否决，且本方案在 binarytrees 上已拿到 `KEEP=1024` 的全部收益
  （1.47 对 1.49 s）。mimalloc 在调研里还要再快约 20%，那是分配器本身（小对象路径、
  对象大小类）的账，不是保留策略的账。
- **不改 `KEEP` 常量。** 1024 在数字上等价，但没有上界，破坏头文件里的 32 MiB 断言；
  衰减是在不放弃上界的前提下拿到同一收益。
- **不做「高水位 + 按近期峰值缩放」。** 要选比例；区间最小值不含比例，见 §2。
- **不起后台线程或定时信号。** 分配器单线程是刻意的（`dawn_rt.c` 头注释）；信号处理函数
  里碰空闲链表会和快路径竞争。
- **不在快路径加计数器。** 每次分配释放加一次增量就是 §4.4 的最坏形状的 +9% 以上；现在
  只在「current slab 降到 0」这个已经罕见的分支里多一次增量。
- **不动 rbtree、deriv、cfold、rbtree-ck 的 sys 时间。** 实测这四个在本方案下缺页与墙钟
  都不变（§4 表）：它们的缺页是堆增长的首次触碰，不是退还后再缺，保留策略碰不到。
  调研里的「14%/30%/18% sys」要靠别的刀（对象大小、`MAP_POPULATE` 之类）。
