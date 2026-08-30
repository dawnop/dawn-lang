# native slab 小活集驻留调研与方案

> 状态：**current / 已裁决并落地**。本文对应 #10。2026-08-30 在
> `78759444` 上完成复现与归因，裁决为方案 A：逻辑 slab 仍是 64 KiB，fresh slab 以
> 32 KiB tranche 增量 materialize；hot allocation path、empty cache 与退役策略不变。
> 可重复语料在 `scripts/slab-bench/`，运行时契约在 `scripts/rc-contract/`。

## 1. 问题

native 运行时把不超过 2 KiB 的分配交给 16-byte size class 的 64 KiB slab。
这条路径在分配密集的形状上已有明确收益：#10 记录的 2026-08 历史测量里，编译器自身
与红黑树形状分别比普通 `malloc` 少约 25% 和 35% RSS。还剩一个相反的形状：lexer
只有很小的同时存活集合，却持续造出并释放大量短命对象；历史数字是 slab 约
14.2 MiB、普通 `malloc` 约 14.2 MiB、mimalloc 约 11.8 MiB。

这些是 issue 留下的**历史数字**，不是当前基线。当前固定语料没有重现“三者约
14 MiB”的绝对数：当前 eager slab 的 quiet RSS 反而低于 glibc/mimalloc；但它重现了题目
真正要找的机制——只触碰少量对象的 class 会预付整个 64 KiB，而且 lexer 峰值里约
1.3 MiB 可以由这份预付页数闭账。本文据此先重建测量、再裁决，而不是直接改 `KEEP`。
落地同时满足：

1. 在当前 `main` 重现 eager first-touch 浪费，并把差额归到具体机制；
2. lexer 的 quiet RSS 与峰值 RSS 都有可重复的改善；
3. 编译器自身和红黑树两个既有胜出形状的 RSS、wall time 不退步；
4. `scripts/rc-contract/` 的 RSS、复用、size class、oversize 与手工 ASan poisoning
   契约全部保留，`slab-never-retires` 等 production mutant 仍按登记的 red set 变红。

## 2. 今天实际保留了什么

`KEEP` 是嫌疑，但不是唯一、甚至未必是最大的嫌疑。当前状态机有三种不同的驻留来源，
必须分开量。

### 2.1 首次触碰一个 class 会写满 64 KiB

`runtime/c/dawn_rt.c` 的 `dawn_sl_layout` 为 slab 内的**每个 block**写 free-list link；
`dawn_sl_carve` 在新取一个 slot 时无条件调用它。映射虽然是 `MAP_NORESERVE`，这次遍历却
把 slab 的数据页都写驻留了。因此“某个 class 只分配过一个对象”不是“一页成本”，而是
接近完整的 64 KiB 成本。

这点和 size-class rounding 不是一回事。rounding 决定请求落进哪个 class、一个 slab 能放
多少同时存活对象；`dawn_sl_layout` 决定一个只用到一次的 class 也会先触碰整块 slab。

### 2.2 每个触碰过的 class 可钉住一个空 current slab

`dawn_sl_put` 在释放 current slab 的最后一个对象时只把 block 推回
`dawn_sl_head[cls]`，把 `used` 减到零后直接返回。它不会进入 empty list，也不会调用
`madvise`。这是刻意的：若立即退役，一个“始终只存活一个对象”的热 class 会每次分配都走
slow path。

最多 128 个有效 class，各钉一块就是 8 MiB；更重要的是，这部分**不受
`DAWN_SLAB_KEEP` 约束，也不计入 `dawn_slab_stats(..., cached, ...)`**。历史差额
14.2 − 11.8 = 2.4 MiB 恰好相当于约 38 块 slab；这只是提出必须测 `empty current`
计数的理由，不能当作归因结果。

### 2.3 `KEEP` 只保留退下来的非 current slab

只有一个 current slab 曾经发完全部 block、换了新 current，旧 slab 随后又释放到
`used == 0`，才会走 `dawn_sl_retire`。每个 class 前四块进 `dawn_sl_empty[cls]`，再多的
才 `madvise(MADV_DONTNEED)` 并进入全局 spare list。

所以 `KEEP=4` 最坏可保留 128 × 4 × 64 KiB = 32 MiB，但一个真正从未装满一块 slab
的小活集根本到不了这条分支。先把 `KEEP` 改成 0 会回答一个有用的问题，却不能单独证明
问题已经被修。

### 2.4 不是数据页的成本

- 1 GiB reserve 是虚拟地址空间；未触碰页不计 RSS，但计 `RLIMIT_AS`。这一取舍不在本题
  范围内。
- `dawn_sl_grid` 是 side metadata。它的高水位应单独记录，不能把 BSS 或 slot 元数据误算成
  slab 数据页。
- sanitized build 默认绕开 slab；`-DDAWN_SLAB_FORCE` 那条腿的 shadow 页是另一份已写清
  的成本，不能与普通 build 的 RSS 混量。
- `madvise` 当前没有检查返回值。归因探针要记录失败次数；“retired 计数增加”本身不证明
  内核真的收回了页。

## 3. 可重复的 lexer 语料

release native driver 的源是 `selfhost/src/nmain.dawn`，它**没有** `__lex` 子命令；拿
`dawnc __lex ...` 测只会测到 usage/启动。`fmt --check` 又会混入 formatter。因此
`scripts/slab-bench/workloads/lexer/` 提供一个只做 lex 的固定入口，输入固定为归档 commit
里的 `selfhost/src/front/lexer.dawn`，默认在同一进程重复 100 次。源码字符串跨轮存活；每轮
token / diagnostic graph 在循环体末释放。所有 allocator 变体链接同一份 emitted C。

被测程序先输出动态的 `checksum\t...`，再输出固定 `ready`。随后只用不分配的
`stdin_ready` 等待；runner 收到第二行后读取同一进程的 `/proc/<pid>/status`，采样完成才写
一个字节，让进程调用 `read_stdin` 并退出。因此 stdin buffer 不会污染 quiet RSS：

- `quiet_vmrss_kib` 是 churn 已结束、对象图已释放后的 `VmRSS`；
- `vmhwm_kib` 是同一进程的峰值；
- `to_ready_ms` 从 exec 前量到 `ready`，不含等待采样。

runner 先做一次不计入摘要的 warm-up，再交错运行 fresh process；RSS/wall 不设 CI 阈值，
只有 build、protocol、退出和跨变体 checksum 是硬失败。它同时保存 `samples.tsv`、
`environment.tsv` 和 `builds.tsv`。既支持 Git ref，也支持没有 `.git` 的远端 build worker
显式传入 eager runtime/candidate runtime/corpus snapshot。

本轮环境：Ubuntu 24.04.4 on WSL2，kernel 6.18.33.2，4 KiB page，AMD Ryzen 7 7840HS
（8C/16T），GCC 13.3.0，glibc 2.39，mimalloc 2.1.2；base/corpus commit
`78759444`。四 allocator 主矩阵每个 workload/variant 用 1 warm-up + 5 个交错 sample；随后
对 eager/candidate 以每个轮内位置各出现四次的 8 sample 平衡顺序复测。lexer 100 轮，持久
红黑树 24 轮，compiler 1 轮。三个 checksum 分别恒为 `938400`、`2422197960096`、
`15669348`。原始样本、build 输入摘要、corpus manifest 与环境记录随 harness 保存在
`scripts/slab-bench/results/2026-08-30-wsl2/` 的 `primary/`、`exact-contended/` 与
`paired-exact/`；第三个目录是最终源码的平衡复测，第二个保留一轮被宿主抖动污染、没有用于
裁决的原始证据。

## 4. 归因矩阵

第一轮没有把调试计数写进产品 runtime。更窄的实验给出了足够的独立变量：`KEEP=0/1`
只动 non-current empty cache；“current 一空即退役”给出退役收益上界；4/8/16/32 KiB
candidate 只动 first-touch extent；`mincore` 则直接观察 fresh slab 的页，不受 libc 或
全进程 RSS 噪声影响。下表前五行是 lexer 100 轮的 attribution pilot；后三行是持久红黑树
24 轮、8 个交错 sample 的 extent 裁决复测（KiB / ms）。正式四 allocator 矩阵的逐样本值
在 §3 所述结果目录。

| 变体 | 只改变什么 | quiet RSS | VmHWM | wall | 结论 |
|---|---|---:|---:|---:|---|
| S0 eager slab | `KEEP=4`，fresh slab 完整 layout | ≈5,172 | ≈9,400 | ≈1,492 | 当前基线 |
| S1 glibc | `-DDAWN_NO_SLAB` | ≈8,892 | ≈8,892 | ≈1,779 | 当前固定语料没有重现历史绝对排序 |
| S2 mimalloc | S1 同一 program object，链接 mimalloc 2.1.2 | ≈8,676 | ≈8,676 | ≈1,424 | 启动/quiet 更高，wall 更低 |
| S3 `KEEP=0` | 只去掉 non-current empty cache | ≈3,900 | ≈9,400 | ≈1,500 | 改善 quiet，几乎不动 peak |
| S4 `KEEP=1` | 只缩窄 non-current empty cache | ≈4,200 | ≈9,400 | ≈1,500 | 与 S3 同方向，说明 cache 是 quiet 的一部分 |
| S5 current 立即退役 | `KEEP=0`，current 到 0 也 `madvise` | ≈2,360 | ≈8,600 | 34,000–39,000 | 上界有收益，但热 churn 慢约 24 倍，排除 |
| R4 4 KiB tranche | 红黑树 eager / candidate | — | — | 2,015 / 2,090 | +3.7%，排除 |
| R16 16 KiB tranche | 红黑树 eager / candidate | — | — | 2,034 / 2,076 | +2.1%，排除 |
| R32 32 KiB tranche | 红黑树 eager / candidate | — | — | 2,002 / 2,005 | +0.1%，落在噪声内 |

4 KiB 在 lexer 上的 quiet/HWM 各少约 1.3 MiB；fresh class 从完整 64 KiB 改为一页首触碰，
差额与约 23 个冷 class 相符。production mutant 恢复 64 KiB 后，单独进程里的 `mincore`
也从一页变成十六页，把这份差额钉到 eager layout，而不是 rounding 或 `madvise` 计数。
但扩展红黑树样本推翻了“RSS 最低就是默认值”的初裁：4 KiB 和 16 KiB 都出现可重复 wall
回退，32 KiB 则保住 wall，同时仍把冷 class 的首次驻留减半。最终因此采用 32 KiB；它保留
current 和既有 empty cache，也不把 24 倍的立即退役代价带进热形状。`KEEP` pilot 说明方案
B 将来仍可能独立研究 quiet cache budget，但它不改善本轮 peak，故不与本刀捆绑。

## 5. 采纳方案 A：逻辑 64 KiB slab，按 extent 触碰

第 4 节已把 lexer peak 的主要可控差额归到 eager first-touch，并排除了立即退役；本节为
最终实现。

### 5.1 状态机

slab 的地址归属、64 KiB slot、size class 和 current/partial/empty/spare 四种角色都不变。
变化只在一块新 carve 的 current slab 怎样得到 free block：

1. carve 只初始化 metadata，不遍历数据页；记录 `batches = 0`。
2. `dawn_sl_head[cls] == NULL` 时，slow path 先看 current 是否还有未 materialize 的 block。
3. 若有，按 32 KiB 边界所覆盖的完整 block 向后建一段 free list，增加 `batches`，并从这段
   交出第一块。
4. 只有所有 batch 已消费且 head 为空时，current 才真的满，随后才走今天的
   partial → empty → carve 选择。
5. 一个 slab 能退成非 current，前提仍是它曾经全部发完；因此进入 empty cache 的 slab 已完整
   materialize，现有复用和退役语义不变。

extent 以完整 block 为单位，不能假设 block size 整除 32 KiB。一个跨 batch 边界的 block
归到后一个 batch，从 block 的真实起点开始 unpoison/write，因此总容量仍精确等于
`floor(64 KiB / block_size)`。若 block 比测试覆盖的 batch 更宽，slow path 会跳到第一个能
容纳完整 block 的边界；尾端没有新完整 block 时消费逻辑 tail 并换下一 slab。独立的
1024-byte batch / 1152-byte block 契约固定这个边界。普通产品值由 R4/R16/R32 曲线裁成
32768 bytes。

### 5.2 fast path 与 metadata

`dawn_sl_get` 的热路径仍是“一次 head load、一次 null branch、pop”；不加 bump/free-list
二选一分支。代价只在 head 用完时多进几次 slow path，写 link 的总数不超过今天完整 layout
写过的总数。最热 class 最终仍得到同一块完整 64 KiB slab；只触碰少量对象的冷 class 不再
预付其余页。

实现没有改动 `used` 的 32-bit 口径。原结构在 `list` 后本来有一个 tail-padding byte；
`uint8_t batches` 正好占用它，产品默认值对应两 batch；override 合同允许的最大 batch 数仍由
static assertion 限制在 255。metadata row 继续是 32 bytes（64-bit target），所以 side table
不因本刀增长。reserve 建立后还请求 `MADV_NOHUGEPAGE`；否则 anonymous-THP=always 的机器
可能把一次 32 KiB tranche fault 放大成 2 MiB，令策略与 `mincore` 契约依赖宿主 THP 模式。

### 5.3 ASan poisoning

forced-ASan leg 必须继续满足“未发出的相邻 block 是 poisoned”。新 slab 初始化时 poison
整个 64 KiB 的**shadow**，但不写数据页；materialize 一个 extent 时只对该段执行
unpoison → 写 links → repoison，真正交出的 block 再 unpoison。不得用“未触碰所以安全”替代
poison：mmap 的新地址对 ASan 默认是 addressable，省掉整块 shadow poison 会让
`slab_poisons_an_unissued_neighbour` 假绿。

## 6. 未采纳方案 B：保留每类突发复用，限制全局 empty cache

`KEEP=0/1` 的确改善 quiet RSS，但没有改善本轮 peak；立即退役又有约 24 倍 wall 代价。
因此本批不采用本节，也不把它与方案 A 混成无法归因的一刀。以下只保留将来独立重开时的
边界。

直接把 `DAWN_SLAB_KEEP` 从 4 改成 0 或 1 是一把过宽的刀：它同时砍掉单一热 class 的突发
复用，而 lexer 的问题可能只是许多冷 class 各留几块。方案 B 保留“每类最多 4 块”的局部
上限，再增加一个**跨 class 的总 empty-slab budget**：

- 新空 slab 到来而总额未满，照旧按 class 缓存；
- 总额已满，从别的 class 的 empty list 选一块最久未复用者 `madvise`，再缓存新到者；
- victim 选择只发生在 slab 变空的 slow path，fast allocate/free 不加时钟或链表维护；
- 总额取值仍必须由编译器、红黑树、lexer 三条曲线重新裁定，不能从 32 MiB 反推一个看起来
  整齐的数字。

实现可在 129 个 class head 上做有界扫描并记 class-level empty epoch，或给 empty slab 增加第二
组全局 links。两者要以 metadata 成本、退役路径 wall time 和 ASan 状态机实测二选一；不在
没有数据时先造 LRU 基础设施。

## 7. 胜出形状不能退

每个候选都与其 parent 版本交错测两轮；保存原始样本，不只写百分比。若 wall/RSS 的方向在
两轮不一致，结论是 inconclusive，增加样本或查机器噪声，不挑有利的一轮。

| 形状 | 固定语料与动作 | before | candidate | 裁决 |
|---|---|---:|---:|---|
| lexer | §3 harness，100 次 lex | 5,228 / 9,504 / 1,487 | 4,492 / 8,804 / 1,456 | quiet −14.1%，HWM −7.4%，wall −2.1% |
| native compiler | native compiler emit 固定 selfhost snapshot | 22,496 / 317,460 / 8,677 | 18,892 / 313,744 / 8,584 | quiet −16.0%，HWM −1.2%，wall −1.1% |
| 持久红黑树 | 32,768 keys × 24 轮，保留旧 root 并校验两棵树 | 2,828 / 20,092 / 2,019 | 2,572 / 19,816 / 2,001 | quiet −9.1%，HWM −1.4%，wall −0.9% |

每个单元格依次是 quiet KiB / HWM KiB / wall ms，均为 5 个正式样本的中位数。四 allocator
矩阵还得到 glibc/mimalloc：lexer 为 `8,940/8,940/1,772` 与 `8,752/8,752/1,471`；红黑树
为 `24,296/24,296/2,578` 与 `20,176/20,176/2,054`；compiler 为
`267,124/328,648/11,457` 与 `191,256/315,416/9,605`。candidate 在两个既有胜出形状上
继续胜过 glibc/mimalloc，且三条 candidate/eager wall 都没有回退。

最终源码的 8-sample 平衡复测给出 eager→candidate wall：lexer
`1,467.716→1,469.859 ms`（+0.15%）、红黑树 `2,018.746→2,035.543 ms`（+0.83%）、
compiler `8,658.511→8,553.561 ms`（−1.21%）；RSS 改善与主矩阵逐项一致。lexer/红黑树的
亚 1% 方向与主矩阵相反，故按本文纪律判为噪声、不是可重复回退。中间那轮四 allocator
复跑同时把 glibc compiler 从约 11.5 秒抖到 19.4 秒，并让同组样本在 9.1–23.7 秒间摆动；
它完整保留在 `exact-contended/`，不进入摘要。主矩阵的 candidate source 只与最终源码差三处
注释；三轮的 `runtime-candidate.o` MD5 都是 `2ea2ecdd5615af85b17874f3706eeedf`，所以
主矩阵量到的是与最终源码相同的机器代码，而不是近似实现。

仓库没有留下历史红黑树 benchmark 源或 runner；本批因此归档了一份固定的等价压力形状：
每轮按确定排列插入 32,768 个 key、每 256 次保留一个旧 root、覆盖固定 key 集，然后同时
校验新旧树；24 轮 checksum 固定为 `2422197960096`。它和 lexer/compiler 一起进入同一个
runner、同一 build manifest 和交错采样协议。

## 8. 运行时契约与独立 RSS 腿

原有 `scripts/rc-contract/rc_test.c` 固定五件事：block 复用、size class 不串、释放 64 MiB
后归还页、缓存上界、4 KiB oversize 走 malloc；六个 forced-ASan probe 固定手工 poisoning。
本刀新增第六项 `slab_materializes_on_demand`：它作为 fresh process 的第一个 allocation，给
2032-byte class 分一个对象后先通过 `DAWN_RC_CONTRACT` 专用 observation port 断言逻辑首批
恰为 32 KiB，再用 `mincore` 断言它在 4 KiB host page 上只驻留八页；前者让 64 KiB-page
Linux 也能区分 candidate 与 eager mutant，后者继续直接固定实际 RSS。随后耗尽所有 tranche、
验证精确 block 容量与 full-empty slab 的地址序复用。
`slab-eagerly-materializes` production mutant 只把 batch 改回 64 KiB，使观察值回到十六页，
并只 redden 这个 owner。

`mincore` 避免了全进程 RSS 阈值，却仍保留 issue 要求的顺序隔离：`rc_test --case NAME` 支持
精确 selector，`run.sh` 在 full roster 之外，分别以 plain 和 `-DDAWN_SLAB_FORCE` fresh
process 单跑 `slab_materializes_on_demand` 与既有 `slab_returns_pages`。后一项的 allowance
仍从 page size、carved bytes 和 forced-ASan 1:8 shadow 推导，不拿某台机器的一次余量调参。

另一条独立 binary 以 `DAWN_SL_BATCH=1024`、block 1152 bytes 分满 56 个对象；第 57 个必须
恰好落在下一 64 KiB slot。它钉住“最后一个完整 block 在第 63 batch 结束、第 64 batch 没有
新 block”时不能越界。原 allocator mutants 的 red set 与所有 ASan probes保持不变。

## 9. 落点与提交边界

最终落点为：

1. `docs/slab-residency-design.md`：填完全部数字、环境、原始样本位置与最终裁决；被推翻的
   前提原地改正。
2. `runtime/c/dawn_rt.c`：只实现被裁定的 residency policy；公开 header 的 slab 尺寸、上限、
   idle-budget 与统计口径均未改变。
3. `scripts/rc-contract/rc_test.c`、`mutate.py`、`matrix.txt`、`run.sh`：新 owner、production
   mutant、独立 RSS 运行与原 red set。
4. 可重复的 `scripts/slab-bench/` 语料与 runner：lexer、native compiler、红黑树三条；它是
   本地 measurement 工具，不把不稳定 wall/RSS 阈值塞进共享 CI。
5. `python3 scripts/gen-rtsrc.py` 重生 `selfhost/src/embed/rtsrc.dawn`；runtime 文本进入 native
   driver，不能只改磁盘版。
6. 重录 `scripts/core-golden/selfhost.sha` 与 `.norm.sha` 中 `embed.rtsrc` 的 hash；按实际
   differential 结果在提交正文逐条写合法 `Emit-Change(...)`，不得预写豁免。

完整验证包括 `scripts/rc-contract/run.sh`、新增 benchmark 的
eager/candidate/glibc/mimalloc 矩阵、native fixed point、`scripts/spike-native/run.sh`、native
CLI differential、selfhost Core golden 与生成 runtime round-trip。所有重构和构建在同一份
reviewed source snapshot 上完成；具体结果列在 PR 的 Test Plan，benchmark 数字列在 §7。

## 10. 不做（以及理由）

- **不在归因前直接改 `KEEP=0/1`。** 它只触达非 current empty list，可能错过真正差额，又
  先牺牲热 class 的突发复用。
- **不让 current 一空就立即退役。** S5 只作收益上界；一个单对象热 class 会每次分配都
  slow-path + layout/madvise，正是当前 current pin 避免的形状。
- **不把 bump pointer 加进永久 fast path。** 现有源码记录该额外分支曾稳定慢约 2%；方案 A
  的 admission test 是 fast path 不变。
- **不先改 `DAWN_SLAB_GRAIN` 或 `DAWN_SLAB_MAX`。** grain 同时改变 rounding、class 数和
  pinned-current 数，无法单独归因；MAX 还改变 oversize 契约与 idle-budget 上界。
- **不把 64 KiB slab 整体缩小。** ownership 依赖 reserve-relative shift，一刀会同时改变
  slot grid、slow-path 频率和热 class amortization；incremental physical extent 能在不改逻辑
  slab 的情况下先回答同一 RSS 问题。
- **不加后台 purge 线程或墙钟 decay。** runtime 明确只有启动线程运行 Dawn code，allocator
  因而无锁；为了一条 residency policy 引入并发、计时和退出竞态，边界远大于本题。
- **不把 forced-ASan 的 shadow RSS 当普通 build 回退。** 它是手工 poisoning 的结构成本，
  allowance 与单跑规则已有独立证明。
- **不顺手改 reserve 的 1 GiB `RLIMIT_AS` 成本、macOS `MADV_FREE` 或 wasm allocator。** 三者
  都不参与这次 Linux lexer 缺口，且各自需要不同平台契约。

## 11. 历史材料

本 allocator 没有独立设计文档；当前最接近权威记录的是源码长注释和以下提交：

- `92d38d85`：size-class slab、current、empty cache 与 `MADV_DONTNEED`；
- `70d21744`：五项 C 契约及四个 production mutant；
- `6cc2d716`：用独立 literal 钉住 32 MiB empty-cache 上界；
- `24167652`：forced-ASan allocator 腿与手工 poisoning probes；
- `f4b5aee2`：单独运行时 ASan shadow allowance 的修正；
- `8072e05a`：embedded runtime 重生与 Core hash 记录。

`dawn_rt.c` 同时保存了已试过而不重开的路线：每 block header 在各语料比普通 malloc 多
18%–37% RSS；free-list 旁再放 bump 状态稳定慢约 2%；只限制 free block cache 不能归还底层
页。这些 verdict 仍成立，除非新的测量明确击中它们的重开条件。
