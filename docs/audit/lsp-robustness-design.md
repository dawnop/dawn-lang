# LSP：URI、UTF-8 与响应性

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **LSP-01（P1）**、**LSP-02（P1）**、**LSP-04（P2）**。
> （LSP-03「畸形 frame 让服务器静默退出」已于 2026-07-25 修复。）
> 状态：**LSP-01 / LSP-02 已落地（2026-07-30），LSP-04 未落地**——它卡在一个缺失的运行时
> 原语上。LSP-01 的落地形态与本文原方案相反：不换 JDK（缝 1 之后 `lsp.dawn` 是零 `use java`
> 的共享前端），而是把手写 decoder 改成校验的。LSP-04 的设计题已于 2026-08-04 用两个探针
> 答完（`io_stdin_ready(timeout_ms) -> Bool !io`，语义 B），验收实验 `scripts/lsp-liveness.py`
> 的三条断言已进 CI 并被变异体逐条打红。**2b / 2c / 2d 已于 2026-08-05 全部落地**：C 后端
> 两个 stdin 读取器都改走 `read(2)`（不再有 stdio 缓冲挡在就绪查询前面），`io_stdin_ready`
> 进了原语表并在两个后端上答出同一张真值表，`lsp.dawn` 的读循环 debounce 了。
> **LSP-04 至此关账**（§六的 3 与 4 是尾款：`$/cancelRequest` 与窗口取值的实测）。
>
> **2d 的落地被种子代际隔在 2b/2c 之后一代**：`selfhost/src` 只准用当前种子已支持的特性
> （docs/bootstrap.md §种子推进协议 3），所以 `lsp.dawn` 调 `io.stdin_ready` 必须等 2b/2c
> 发一个 release、bump `scripts/seed-release.txt` 之后才编得动。
> 台账见 [native-plan-overlap.md](native-plan-overlap.md) §3.7——其「换 JDK」处方已作废。


> **2026-07-30 改判后落地（LSP-01 的 UTF-8 半）**：台账 §3.7 的「换 JDK」处方被当日
> 架构再次作废——缝 1 之后 `lsp.dawn` 是共享前端（零 `use java`，两个 main 共用一份），
> 换回 `java.net.URI` 等于把它踢出共享半区。按原则的正确形态落地：**手写 decoder 修成
> 校验的**（continuation 区间 / overlong / surrogate / 超 U+10FFFF 全拒，坏序列出
> U+FFFD 降级续读），一份纯 Dawn 实现两个工具链共用，单测钉住五类畸形输入。
> **LSP-02 也已落地（同日）**：authority（空/localhost 才是本机，其他主机回 None
> 而不是猜出一个相对路径）、query 与 fragment 在解码前切掉、Windows 盘符
> （`file:///C:/x` → `C:/x`；`/c/x` 不是盘符）、`path_to_uri` 恒发三斜杠的空 authority
> 形式（`C:/x` 若不补斜杠会把盘符解析成主机名），`:` 不再被百分号编码（RFC 3986 的
> pchar，且 `%3A` 人读不出）。往返测试含重音字符与盘符。**LSP-04（debounce）撞墙已记档**：§2.2 的方案
> 依赖「`read_message` 加一个超时形式（有输入就读，没输入就返回 `Idle`）」，
> 而 std/io 只有阻塞的 `read_stdin(n)`——**没有任何「就绪/超时」原语**。
> 造一个（`io_stdin_ready(timeout_ms) -> Bool` 之类）是**运行时契约变更**：
> 两个后端各实现一份（JVM 的 available/带超时读 vs C 的 poll/select）、进 spec §11
> 的原语表、进 intrinsic 语义表。那是一把独立的刀，且它的设计题（就绪 vs 超时读、
> EOF 怎么表达、native 上的信号语义）比 debounce 本身大——**不该顺手塞进 LSP 改动里**，
> 半设计好的原语进语言表面比不做更糟。debounce 的其余部分（generation 计数、
> `$/cancelRequest` 直接回 RequestCancelled）都在那个原语之后才有意义。
>
> **2026-08-04 实测收口**：设计题已经用探针答完，形状定了（语义 B 的 `Bool`），
> 验收实验也已建出并用变异体打红过——见 §2.2.1 与 §2.2.2。落地还欠一件前置：
> C 后端的 `io_read_stdin` 得先从 stdio 换成 `read(2)`。本轮不写任何代码。
>
> **2026-08-05 落地（2b + 2c）**：前置与原语都进了树。实测两个后端在五种 stdin 状态
> （管道有数据 / 管道静默 / 管道 EOF / 有数据且 EOF / 常规文件）上**每一格布尔值都相同**；
> 时延照契约分岔且都在「至多」这一侧——EOF 那格 native 立刻回 `false`、JVM 耗满窗口。
> 落地点的真实清单与逐点变异体记在 §2.2.1 末（原表 9 条错 1 条、漏 4 处）。
## 一、问题

### 1.1 手写 UTF-8 decoder 不校验（LSP-01）

`selfhost/src/lsp.dawn` 的 `utf8_decode` 从 percent-decode 出来的字节序列重建码点。
它不检查：continuation byte 是不是真的 `10xxxxxx`、overlong encoding、
surrogate 范围（D800–DFFF）、最大码点（> 10FFFF）。不完整序列直接跳一个字节：

```dawn
} else {
  i = i + 1        # 落到这里就是「不认识，跳过」
}
```

后果：同一个 URI，Dawn 与 JVM/编辑器可能解出不同的路径；
更糟的是解出的码点可能落进 `from_code_points` 的非法范围，
那是 panic 而不是错误。

### 1.2 file URI 是字符串拼接（LSP-02）

```dawn
pub fn uri_to_path(uri: String) -> Option[String]   # 只去掉 "file://"
pub fn path_to_uri(path: String) -> String          # 只拼上 "file://"
```

authority（`file://host/path`）、Windows drive（`file:///C:/x` → `C:\x`）、
UNC（`file://server/share`）、相对路径、`#`/`?`、以及 URI normalization
全部没有处理。

`java.net.URI` + `java.nio.file.Paths` 已经正确实现了这些。手写没有理由。

### 1.3 每次按键做全项目同步分析，无取消（LSP-04）

`lsp.dawn:5` 的文件头明说每次 change 重建完整分析。具体：

- `textDocumentSync = 1`（Full）——每次改动收全文；
- `update_doc` 调 `analyze_document(path, text, std, 100000000)`；
- 主循环单线程，`$/cancelRequest` 不处理。

配合「目录模式加载全部模块」（LANG-07），项目一大就会出现输入延迟，
且旧的分析结果会覆盖新状态——因为它是同步的，最后跑完的那个赢。

## 二、方案

### 2.1 URI 与 UTF-8 全部交给 JDK（LSP-01 + LSP-02，同一次改动）

```dawn
use java "java.net.URI"
use java "java.nio.file.Paths"

## file: URI → filesystem path, or None when the URI is not a local file.
##
## Paths.get(URI) handles authority, Windows drive letters, UNC and
## normalization; the hand-written version handled the prefix and nothing else.
## The percent-decode and the UTF-8 decode that used to sit under it are gone
## with it — URI does both, correctly, including rejecting the malformed
## sequences the hand-rolled decoder silently skipped.
pub fn uri_to_path(uri: String) -> Option[String] =
  match java_try(() => Paths.get(URI.create(uri)!)!.toString()!) {
    Ok(p) -> Some(p)
    Err(_) -> None
  }

pub fn path_to_uri(path: String) -> String =
  ...Paths.get(path)!.toUri()!.toString()!...
```

`utf8_decode`、`utf8_bytes`、手写的 percent-decode 一并删掉。

**为什么这次能用 JDK，而 `packages/json` 的 lexer 不能**：
JSON 的解码是这个包的**产品**，得自己掌握（且要跟 fixture 对拍）；
URI 解码是**基础设施**，正确性早有定义、JDK 早有实现。
`packages/web` 的 WEB-02 修复走的就是这条路（改用 `URLDecoder`），本文一致。

**要注意的**：`catch_fault`（当时叫 `java_try`）曾返回 `Result[T, String]`，
[error-model-design.md](error-model-design.md) 已把它改成 `ForeignError`。
两者不冲突——这里只用了 `Err(_)`，不看内容。

### 2.2 debounce + generation cancellation（LSP-04 第一步）

审查给的分步是对的：**先 debounce + generation，再谈缓存**。

```
主循环（不变，单线程读）
  ├─ didChange → 只记下 (uri, text, ++generation)，不分析
  └─ 空闲 N ms 后 → 分析最新的 generation
```

关键是**不引入并发**：

- 主循环仍然单线程；
- `read_message` 加一个超时形式（有输入就读，没输入就返回 `Idle`）；
- 收到 `Idle` 且有 pending 改动且距最后一次改动 > N ms → 跑分析。

于是「旧诊断覆盖新状态」这个竞态**根本不会出现**——因为从来没有两个分析同时在跑。
连续按键期间只有最后一次会被分析。

`N` 取多少：暂定 150ms，**没有实测出处，落地时要测**（CONTRIBUTING §二）。
测法：记录 `didChange` 到诊断发布的墙钟时间，在 selfhost 自身（31k 行）上连续输入。

### 2.2.1 就绪原语：实测真值表与裁决

> 2026-07-30 记了一段侦察（`d4359c0`），当时**没跑过任何东西**，靠的是对 `poll` 与
> `available()` 的先验印象。2026-08-04 用两个独立探针（一个 C 一个 Java，各自被真实
> 管道 / 真实文件 / 真实 pty 驱动）把四种状态逐格量了一遍，**结论与那段侦察在三处相反**。
> 下面凡标「实测」的格子都有探针出处，标「推断」的没有。

#### 真值表（实测，Linux 6.18 WSL2 / glibc 2.39 / GraalVM 21.0.2）

状态：**a** 有数据待读、写端开着；**b** 写端开着但静默；**c** 写端已关（EOF、无数据）；
**d** 静默一段后才写；**e** 有数据且写端已关。
（payload 有 5 字节 `hello` 与 6 字节 `hello\n` 两种——tty 的 canonical 模式不给不带换行的输入，
所以补了后者；表里 5 与 6 的差别只是这个，不承载别的意思。）

| stdin | 状态 | C：`poll(POLLIN, 200ms)` | C：`FIONREAD` | JVM：`available()` | 随后阻塞读 |
|---|---|---|---|---|---|
| pipe | a | `ret=1 revents=POLLIN`，1µs | 5 | 6 | 全部字节 |
| pipe | b | `ret=0 revents=0`，**200.2ms**（超时真生效） | 0 | 0（300ms 内 59 次全 0） | 阻塞不返回 |
| pipe | **c** | `ret=1` **`revents=POLLHUP`**（**没有 POLLIN**） | 0 | **0**（与 b 逐字节相同） | `read`→0 / `read()`→−1 |
| pipe | d | 200ms 超时后下一次调用命中 | 0→5 | 0→6（5ms 粒度，226ms 命中） | 拿到数据 |
| pipe | e | `revents=POLLIN\|POLLHUP` | 5 | 5 | 5 字节 |
| file | a | `ret=1 revents=POLLIN` | 5 | 5 | 5 字节 |
| file | **c** | `ret=1` **`revents=POLLIN`**（常规文件恒可读） | **0** | **0** | 0 字节 |
| tty | a | `ret=1 revents=POLLIN` | 6 | 6 | 6 字节 |
| tty | b | `ret=0`，200.2ms | 0 | 0 | 阻塞不返回 |
| tty | c（挂断） | `revents=POLLIN\|POLLERR\|POLLHUP` | `-1 errno=EIO` | **抛 `IOException: Illegal seek`** | 0 / −1 |

`select` 与 `poll` 在每一格答案相同（也实测了），不构成第三种选择。
tty 的 a/d 首轮实测「永不就绪」是探针自造的：pty 默认 canonical 模式，不带换行的
payload 不投递——补上 `\n` 后与 pipe 一致。同理首轮 JVM 矩阵的多处超时是
`readNBytes(n)` **必须凑满 n 字节才返回**（正是 `io_read_stdin` 的语义），不是 Java 的性质。

#### 被实测推翻的三条

1. **「POSIX 在 EOF 报 `POLLIN`」是错的**。Linux 上管道写端关闭且无数据时
   `revents` 只有 `POLLHUP`，有数据时是 `POLLIN|POLLHUP`。于是
   **C 端能区分「有数据」与「EOF」**，而侦察假设它不能——这正是当时说
   「契约必须选 POSIX 那个」的全部依据，依据没了。
2. **「JVM 是难的那一半」是反的**。`System.in` 是 `BufferedInputStream`，
   `available()` **把自己的缓冲算进去**：读掉 20 字节里的 1 字节后仍答 19（实测）。
   而 C 后端的 `dawn_io_read_stdin` 走 **stdio `fread`**，`poll`/`FIONREAD`
   **看不见 stdio 的缓冲**：同一实验里 `fread(1)` 之后 `FIONREAD=0`、
   `poll` 老老实实超时 200ms，而 19 字节就躺在 glibc 的缓冲里。
   **在 C 后端，基于 `poll` 的就绪原语在今天的 `io_read_stdin` 之上是错的。**
3. **「EOF 算不就绪 → 服务器空转不退出」不是原语的性质，是循环形状的性质**。
   见下。

#### 形状裁决

| 形状 | C 能否实现 | JVM 能否不起线程实现 |
|---|---|---|
| `-> Bool`，语义 A「读不会阻塞」（EOF 也算就绪） | 能（`ret>0`） | **不能**——EOF 时 `available()=0`，与状态 b 逐字节相同（实测 pipe/b vs pipe/c） |
| `-> Bool`，语义 B「至少有一字节可读」（EOF 不算就绪） | 能（`poll` + `FIONREAD>0`） | **能**（`available()>0`） |
| `-> Int` 三态（有数据 / 超时 / EOF） | **能**（超时→0；`FIONREAD>0`→1；否则→−1；tty 挂断的 `EIO` 也归 −1） | **不能**，理由同语义 A |

于是**语义 B 的 `Bool` 是两个后端都能不起线程实现的唯一形状**，推荐它：

```
io_stdin_ready(timeout_ms: Int) -> Bool !io
## true 当且仅当此刻至少有一字节可以立即读到。
## EOF 不是就绪：EOF 由既有的阻塞读报告，它仍是唯一的读者。
## timeout_ms 是**上界**而非下界：常规文件到达 EOF 时 C 端会立刻返回 false
## （实测 1µs），JVM 端会耗满窗口（实测 300ms）。契约只承诺「至多」。
```

语义 B 曾被判死刑的那条理由（客户端关掉管道后服务器等一个永不到来的就绪信号）
**只在「循环完全由就绪驱动」时成立**。把循环写成——

```
loop:
  if ready(N):        读一帧（此时不会阻塞）；EOF 由这次读报告
  else if 有待分析:    跑分析，清空
  else:               什么都不用做 → 直接做一次阻塞读   ← 关键的第三支
```

——EOF 就总在有限步内被那次阻塞读撞上：待分析的活先跑完，下一轮无事可做，阻塞读返回 0。
两个后端的 stand-in 实测退出时延 **0.00s / 0.02s**（见下）。第三支不是补丁，它是对的：
**没有活干的时候，阻塞正是应该做的事**。

三态形状虽然 C 端做得出（真值表里每格都能答），但 JVM 端要它就得起后台读线程，
而线程的代价不是一条线程：**阻塞读只能有一个所有者**，于是 `read_stdin` 与
`read_line` 都必须改走那个队列，且线程从进程启动就开始吞字节。
实测过一个具体后果：起了读线程的 JVM 进程再 spawn 一个继承 stdin 的子进程，
子进程读到空（`child-got:[]`），不起线程时读到 `line-for-child`。
（`io.run` 今天在 C 侧继承 fd 0、在 JVM 侧走 ProcessBuilder 默认的 PIPE，两侧本就不同答，
是另一笔账；这里只用它证明「读线程会替别人吃掉字节」。）

#### 落地前置（这是本轮挖出来的新账）

**C 后端的 `io_read_stdin` 必须先从 stdio 换成 `read(2)`**，否则就绪原语是假的：
今天 `dawn_io_read_stdin` 用 `fread`、`io_read_line` 用 `fgetc`，两者彼此自洽，
但 `poll` 对它们的缓冲一无所知。而 LSP 的 `read_message` 逐字节读 header
（`io.read_stdin(1)`），glibc 一次就把整帧吸进缓冲——就绪查询会答「没数据」，
debounce 会在数据已经到齐时开跑分析，**debounce 恰好被它打败**。
这不是今天的 bug（今天没人问 `poll`），是原语的前置条件。

新增一个 intrinsic 的落地点（照 `io_read_stdin` 现有分布点出来的，共 9 处）：
`types.dawn` 的签名表 + std-only 名单、`stdlib.dawn` 的「不是语言表面」提示表、
`interp.dawn` 的 comptime 拒绝名单、`rtclasses.dawn` 的 JVM 字节码生成、
`runtime/c/dawn_rt.{c,h}`、`selfhost/src/rtsrc.dawn`（`gen-rtsrc.py` 重生成）、
`std/io.dawn` + `stdsrc.dawn`（`gen-stdsrc.py` 重生成）、两个 emitter 的 arm
（`scripts/intrinsic-parity.py` 会验）、`docs/spec.md` §11。

#### 落地后的实际清单（2026-08-05，逐点用变异体核过）

上面那张表**第 8 条是错的**，还**漏了 4 处**。实际落地是下面这些，右列是「漏掉它会红在
哪」——逐条打过变异体，没打红的照实记着。

| 落点 | 漏掉它会怎样 |
|---|---|
| `types.dawn` `builtins()` 签名 | 名字不存在，`std/io.dawn` 编不过 |
| `types.dawn` `io_in_rt` 列表（一张表同时管 rt 归属与 std-only） | **停在 stage 2**：`panic: codegen: Core intrinsic without a JVM mapping: io_stdin_ready` |
| `stdlib.dawn` 「不是语言表面」提示表 | **全绿**。304 个测试一个不红，只是诊断从「`io_stdin_ready` is not a builtin; use std/io, then io.stdin_ready(...)」退化成「undefined function: io_stdin_ready」。本轮唯一一处无门禁的落点 |
| `interp.dawn` `comptime_rejects()` | interp 的划分测试按名字红（`assert a \|\| r`），不是只靠计数 |
| `rtclasses.dawn` JVM 字节码 | **2c 单独落地时全绿**：`classfile-verify` 只解析语料里真出现的引用，而那时仓库里没有调用点，于是 0 unknown 通过；只有跑到那个名字的程序才 `NoSuchMethodError`。**2d 之后 `lsp.dawn` 就是那个调用点**，洞随之关上 |
| `runtime/c/dawn_rt.{c,h}` | 链接期 `undefined reference to 'dawn_io_stdin_ready'` |
| `rtsrc.dawn`（`gen-rtsrc.py` 重生成） | `cdriver :: the embedded C runtime matches runtime/c on disk` |
| `std/io.dawn` + `stdsrc.dawn`（`gen-stdsrc.py` 重生成） | `stdlib :: the embedded std matches std/ on disk` |
| `docs/spec.md` §11 | 无门禁。而且 §11 **没有原语清单**（开篇就写「本节不列清单」），落点是「IO 的表态」那段散文 |
| ➕ `lower.dawn` 划分测试的计数 | `assert len(map.keys(it)) == 89` 红 |
| ➕ `types.dawn` 自测的计数 | `assert map_size2(bs) == 89` 红 |
| ➕ `interp.dawn` 自测的计数 | `assert len(rejects) == 61` 红 |
| ➕ `scripts/core-golden/` 重录 | Core golden 红。差异全是 `structeq$AdtN` 的 id 整体 +1（NORM 里已备案的噪声）加上 `std.io.core` 多出这个函数 |

**第 8 条（两个 emitter 的 arm）不成立，而且照做会红**：`io_stdin_ready` 由运行时模块
（`RtIo`）拥有，`emit.dawn` 只按 `Rt → class` 查表、`emitc.dawn` 的 `rt_symbol` 直接拼
`dawn_ ++ name`，两边都不按名字写 arm。真给它加一条，`intrinsic-parity.py` 会以「有 arm
却不在 `lower.dawn` 任何名单上」判红。也就是说这个门禁**根本不覆盖这个 intrinsic**——它只
读 `inline_intrinsics()` 与 `jvm_only_intrinsics()`。

不是落点但绕不开的一件：`selfhost-prev-diff.sh` 的六个 `emit *` 与 `selfhost-run-diff.sh`
的 `doc --builtins` 都会差（生成符号名里的 ADT id 整体位移），要七条 `Emit-Change`——
glob 是禁的。

### 2.2.2 验收：两个实验，先证明它们能红

选错的后果是**服务器空转或挂死**，两者都不会在单元测试里出现——所以在写原语之前
先把能抓住这两种失效的实验建出来，并用**故意写错的实现**打红过。
（2026-08-04 实测；本节是 stand-in 循环上的那一轮，已收进 `scripts/lsp-liveness.py`，
见 §2.2.3——**换了被测对象之后阈值和变异体都重新定过一遍**。）

- **挂断实验**：客户端关掉写端后，服务器必须在限期内退出。断言退出时延 < 2s。
- **空转实验**：客户端保持连接但静默 N 秒，服务器 CPU 时间
  （`/proc/<pid>/stat` 的 utime+stime）必须近零。断言 < 0.25s。

四个变异体，两个后端各跑一遍（stand-in 循环，不是真 `lsp.dawn`）：

| 变异体 | 挂断 | 空转 |
|---|---|---|
| `good`（语义 B + 上面那个第三支） | PASS 0.00s / 0.02s | PASS 0.00s（0.0% 单核） |
| `good-posix`（语义 A，仅 C 端可行） | PASS 0.00s | PASS 0.00s |
| `hang`（EOF 不算就绪 **且没有第三支**） | **FAIL 2.00s 仍存活** | PASS 0.00–0.05s |
| `spin`（超时靠反复重问而不是靠等） | PASS | **FAIL 4.00s / 4.99s CPU，≈100% 单核** |

两个实验各由**一个**变异体单独打红，互不掩护——这正是要的：`hang` 只红挂断，
`spin` 只红空转。今天的 `bin/dawn lsp`（还没有 debounce，纯阻塞读）两项都绿
（退出 0.06s、6s 静默窗口 0.01–0.08s CPU），那是 debounce 落地后必须守住的基线。

**空转实验自带一个盲点，已经补上**：它分不清「因为守规矩所以安静」与
「因为压根没干活所以安静」——拿 `sh -c 'cat >/dev/null'` 当服务器，空转实验
照样 PASS。所以实验多要一条存活断言（静默窗口开始前 stdout 必须已出现
`publishDiagnostics`）；加上之后同一个 `cat` 变异体转红。
门禁的绿不构成证据，直到证明它能红。

### 2.2.3 门禁：`scripts/lsp-liveness.py`（§六 2a，已落地）

上一节的红是在 stand-in 循环上取得的。收进仓库后被测对象变成真的 `bin/dawn lsp`，
**红的能力不能继承**，所以三条断言各自被重新打红了一遍（2026-08-04）。

三条断言各自独立报 PASS/FAIL，阈值与出处：

| 断言 | 上界 | 实测出处 |
|---|---|---|
| `hangup` 客户端关掉 stdin 后退出 | **5.0s** | `bin/dawn lsp` 实测 0.06s（四次一致），stand-in 0.00 / 0.02s；留 ~80× |
| `idle` 6s 静默窗口内的 utime+stime | **0.5s** | `bin/dawn lsp` 实测 0.01–0.08s（六次）；`spin` 变异体 6.23s ≈ 103% 单核。上下各 ~6–12× |
| `liveness` 静默窗口开始前 stdout 见过 `publishDiagnostics` | 60s 内 | 实测 0.91–1.01s；上界抄 `native-cli-diff.sh` leg 5 的同一个等待 |

三个变异体，都打在真服务器上：

| 变异体 | hangup | liveness | idle |
|---|---|---|---|
| `Eof -> { running = true }`（EOF 不退出） | **FAIL 5.00s 仍存活** | PASS | PASS 0.01s |
| didChange 后忙等（见下） | PASS 0.06s | PASS | **FAIL 6.23s，103.8% 单核** |
| `sh -c 'cat >/dev/null'` | PASS 0.00s | **FAIL 60s 无 `publishDiagnostics`** | PASS 0.00s |

第三行就是「门禁的绿没有信息量」的实例：`cat` 把 hangup 和 idle 两条都拿了满分。

落地过程推翻的三件（都写进脚本注释了）：

1. **静默前的等待不能是定长**。初版在见到第一条 `publishDiagnostics` 后固定等 1.0s
   就开窗，结果健康的服务器被判 FAIL——三条 didChange 还有三次分析没跑完，
   **0.54s 合法的活漏进了窗口**。改成「等 stdout 静止 1.5s」：debounce 落地后
   三条 didChange 只答一次，定长等待在那一侧同样错。空转仍抓得住，因为空转的特征
   恰好是 stdout 静而 CPU 响。
2. **`bin/dawn lsp` 的静默窗口 CPU 不是 0.00s**，是 0.01–0.08s（JVM 的后台开销）。
   §2.2.2 记的 0.00s 是 stand-in 的数，别拿它当上界。
3. **整数累加循环在真服务器上烧不动 CPU**：`spin = spin + i` 跑 2×10¹⁰ 次，
   在 1 秒内返回了**算术上正确的溢出结果** `-8446744083709551616`——JIT 把它折了。
   空转变异体只好改成字符串活（`to_string(i) ++ "x"`，5×10⁸ 次 ≈ 9s）。
   记一笔：任何拿空循环当计时器的地方都是假的。

还有一件是刻意的：**hangup 实验只发握手、不发 didChange**，idle 实验才发。
挂断断言问的是读循环的 end-of-input 那条路，最短的会话就是最强的形式；
而这条分工正是空转变异体没有连带打红 hangup 的原因——今天的服务器只有一个阻塞点，
一个真正「静默期烧 CPU 又仍能响应挂断」的变异体在**就绪原语存在之前根本写不出来**
（那正是 2c 的理由）。

`$/cancelRequest` 在这个模型下可以直接**回一个 `RequestCancelled` 错误**——
因为没有真的在跑的请求可以取消，请求要么还没开始要么已经完成。这是合规的。

### 2.2.4 debounce 落地（§六 2d，2026-08-05）

**形状与 §2.2 原方案有一处不同**：没有给 `read_message` 加 `Idle`，就绪查询放在**主循环**
里。三支照旧，只是第一支的条件改成「有待分析的文本」：

```
loop:
  take = if 有 pending { io.stdin_ready(150) } else { true }   # 无事可做 → 阻塞读
  if take: 读一帧
             ├─ didOpen/didChange → 只记进 pending（同一 uri 覆盖，不同 uri 先冲掉旧的）
             └─ 其它任何东西      → 先 flush pending，再 handle
  else:    窗口走完没等到东西 → flush pending
```

**关键的一条是「其它任何东西先 flush」**，它让「推迟」在协议上完全不可观测：所有读分析结果
的答复（hover / definition / completion / symbols / formatting）和所有关于文档的输出都要
过这一点。实测的后果是 `selfhost-lsp-diff.sh` 的 50 条消息**逐字节不变**（两个后端各跑一
遍），因此**没有 `Emit-Change(lsp)`**——转录里没有连着两条同 uri 的更新，唯一能被合并的地方
不存在。

**generation 计数没有做，因为不需要**：单线程 + 「至多一个 pending」已经让「旧分析盖新状态」
无从发生。计数是用来在并发下辨认过期结果的，这里没有并发。

#### 两条新断言与它们的变异体（`scripts/lsp-liveness.py`）

| 断言 | 真服务器 | 变异体 | 变异体实测 |
|---|---|---|---|
| `debounce` 分析次数 < 编辑次数 | PASS `1 analyses for 5 edits 60ms apart` | `DEBOUNCE_MS = 0` | **FAIL `5 analyses for 5 edits`** |
| `freshness` 最后那次分析是最新文本 | PASS `the last diagnostics name zzz_5` | pending「先到的赢」而不是「后到的覆盖」 | **FAIL `they name [1] -- the analysis that ran was of an edit the client had already replaced`** |

两个变异体互不掩护：`DEBOUNCE_MS = 0` 的 `freshness` 是 PASS 的（它把每一次都分析了，最后
一次自然最新），「先到的赢」的 `debounce` 是 PASS 的（确实只分析了一次）。这正是把它们分成两
条而不是一条的理由。

**实验的 gap 是整个实验**，两条地板都是量出来的，不是估的：

- **gap = 0（一次性灌进管道）时，两个变异体都合并成 1 次**——帧在循环发问之前就已经躺在
  管道里，窗口多大都无所谓。**一个没有间隔的 debounce 实验什么也证明不了**，这条值得单独记。
- **gap ≥ 20ms** 时 `DEBOUNCE_MS = 0` 才稳定回到 5/5；再小，第 k 次分析还没跑完第 k+1 次
  编辑就到了，变异体会「碰巧」合并。
- gap 必须 < 窗口，否则真服务器**本来就该**每次都发。

取 60ms：高于地板 3 倍、低于窗口 2.5 倍，也差不多是快手打字的间隔。

#### 2a 的窗口定义在 debounce 之后仍然成立

`lsp-liveness.py` 用的是「等 stdout 静止 1.5s」而不是定长等待。落地后跑过：`liveness` 与
`idle` 都 PASS（`idle` 0.01–0.03s CPU / 6s 窗口），说明静默窗口确实开得出来。定长在这一侧
会错的原因和它在另一侧会错的原因是同一个——**debounce 之后三条 didChange 只答一次**，
定长会把窗口开在还没答的时候。

#### 顺带量出来的：`hangup` 从 0.06s 变成 0.21s（JVM）/ 0.02s（native）

多出来的是那一次被推迟的分析：客户端关掉 stdin 之后，`stdin_ready` 立刻回 `false`（管道
POLLHUP、无 POLLIN），循环先把 pending 分析完，再去做那次阻塞读，读到 0 字节才退出。
上界 5s，留了 20 倍以上。

#### 「JVM 那条 arm 没门禁」这个洞，2d 关上了

§2.2.1 末的表里记着：2c 单独落地时，删掉 `rtclasses.dawn` 的 `gen_io_stdin_ready`
**全绿**——`classfile-verify` 对**已发出的 `dawn/rt` 类缺成员**是「计数不判红」的
（`reach.dawn` 会有意裁剪，那笔账归 `scripts/table-freight`），而那时也没有调用点。
2d 之后 `lsp.dawn` 就是调用点，同一个变异体实测：

```
hangup:    PASS -- exited 0.00s ...          ← 又一次「绿没有信息量」：崩了的进程退得最快
liveness:  FAIL -- no publishDiagnostics in 60s
idle:      FAIL -- server was gone before the window opened
debounce:  FAIL / freshness: FAIL
```

抓住它的是 `lsp-liveness.py`（五条里红四条）与 `selfhost-lsp-diff.sh`，**不是**
`classfile-verify`。

### 2.3 缓存留到第二步

`analyze_document` 每次重跑 lex/parse/module graph。缓存它们需要失效判定
（哪些模块受这次改动影响），而那要先有模块图的增量表示。
**不在本文范围**——debounce 之后延迟已经从「每次按键」降到「停下来之后一次」，
先量一量还剩多少痛再决定。

## 三、为什么不顺手把 X 也改了

- **不改 `textDocumentSync` 到 Incremental**。增量同步要维护文档的行索引
  并正确应用 range 编辑——是自己的一份工作，且它省的是**传输**不是**分析**，
  而痛在分析。
- **不动 `lspq.dawn`**（1,671 行的查询层）。本文只碰传输与调度。
- **不做多线程 LSP**。见 §2.2——单线程 + debounce 已经消掉了竞态，
  引入线程会把它请回来。

## 四、不做的（记录理由）

- **保留手写 decoder 作为 fallback**。留着它就还得维护它。
  初稿这里的理由是「它的全部价值是『JDK 不在』——JDK 一定在，Dawn 跑在 JVM 上」，
  **那个前提已经被 [`../native-backend-plan.md`](../native-backend-plan.md) 的
  Phase 6 作废**（要替换 17 个模块的 99 处 `use java`，`lsp.dawn` 在其中；
  native 上没有 `java.net.URI`）。结论不变，理由换成：**native 上会另起一份**，
  而不是把这个留着。一个不校验 continuation byte、不拒绝 overlong 与 surrogate
  的实现，不该因为将来需要一个实现就免于被删——将来需要的是**对的**那个。
  见 [native-plan-overlap.md](native-plan-overlap.md) §3.7。
- **自己实现严格 UTF-8 decoder**（审查给的第二个选项）。
  写一个正确的 UTF-8 decoder（拒绝 overlong、surrogate、超范围）是可行的，
  但它要自己的一套 corpus 才可信，而 JDK 的那个已经被全世界测过。
  仓库里已经有一个手写 decoder 要还债，不该有第二个。
- **在 debounce 之前先做缓存**。缓存更"根治"，但它的收益要在
  「每次按键都重算」被消除之后才能量出来——先做便宜的那个，再量。

## 五、验收

LSP 的输出受 `scripts/selfhost-lsp-diff.sh` 逐字节守护。本文的改动**会**改变
畸形输入下的行为（那正是目的），所以：

1. 先给 `selfhost-lsp-diff.sh` 的语料**加上畸形用例**：非法 UTF-8 的 URI、
   Windows 盘符 URI、带 authority 的 URI、带 `?`/`#` 的 URI。
   在改代码**之前**加，记录当前（错误的）行为。
2. 改完之后差异逐条 review，确认每一条都是「从错到对」。
3. 提交带 `Emit-Change:`，说明改了哪些 URI 形态的行为。

这个顺序（先补语料记录旧行为，再改）是这类改动唯一能证明自己没改坏东西的办法。

LSP-04 的验收不在这条线上：`selfhost-lsp-diff.sh` 比的是**输出字节**，
而 debounce 改的是**时间与 CPU**，逐字节相同的输出对空转和挂死完全失明。
它的验收是 §2.2.2 的两个实验，且两个都已经被变异体打红过。

## 六、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| 0 | `scripts/selfhost-lsp-diff.sh` 语料加畸形 URI | 记录旧行为 |
| 1 | `selfhost/src/lsp.dawn`：`uri_to_path`/`path_to_uri` 改 JDK；删 `utf8_decode`/`utf8_bytes`/percent-decode | lsp 内联 test：Windows drive、UNC、非法 UTF-8、`%2F` |
| 2a ✅ | `scripts/lsp-liveness.py`：挂断 / 存活 / 空转三条断言进仓库，进 `gates.yml` 的 `test` job | **已完成**（2026-08-04）。三条在真 `bin/dawn lsp` 上各被变异体单独打红过，阈值与实测见 §2.2.3 |
| 2b ✅ | `runtime/c/dawn_rt.c`：`io_read_stdin` 从 `fread` 换成 `read(2)`（`io_read_line` 同步） | **已完成**（2026-08-05）。变异体：换回 `fread` 后，6 字节输入读掉 5 字节，就绪查询答 `false`，而第 6 字节确实还在（下一次读拿得到）——正是设计预言的那一格 |
| 2c ✅ | 新 intrinsic `io_stdin_ready(timeout_ms) -> Bool !io` | **已完成**（2026-08-05）。落地点的实际清单与逐点变异体见 §2.2.1 末；9 处里 1 处是错的、另有 4 处漏记。`intrinsic-parity.py` 不覆盖它 |
| 2d ✅ | `selfhost/src/lsp.dawn`：主循环 debounce + **无事可做时阻塞读**那一支 | **已完成**（2026-08-05）。`lsp-liveness.py` 增两条断言（`debounce` / `freshness`），各有自己的变异体；两个后端的 lsp 转录仍与 v0.50.0 **逐字节相同**。见 §2.2.4 |
| 3 | `selfhost/src/lsp.dawn`：`$/cancelRequest` 回 `RequestCancelled` | 协议合规 |
| 4 | 实测 debounce 窗口，把 150ms 换成有出处的数字 | 记录 harness 与数据 |

无破坏性变更（LSP 是工具，不是语言表面）。2b/2c 动的是运行时契约与 intrinsic 表，
但只加不改：`io_read_stdin` 的**可观察**语义（恰好 n 字节，短读即 EOF）不变，
换掉的是它底下的缓冲层。
