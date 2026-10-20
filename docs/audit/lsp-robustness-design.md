# LSP：URI、UTF-8 与响应性

> 状态：**historical** —— 动码前的调研与方案，不是当前设计定稿；当前行为以
> `selfhost/src/lsp/` 与 `scripts/lsp-liveness.py` 为准。
> 覆盖 codebase-audit.md 的 **LSP-01（P1）**、**LSP-02（P1）**、**LSP-04（P2）**。
> （LSP-03「畸形 frame 让服务器静默退出」已于 2026-07-25 单独修复。）
>
> **三条都已关账**：LSP-01 / LSP-02 于 2026-07-30，LSP-04 于 2026-08-05
> （2b / 2c / 2d 全部）。LSP-04 的尾款只剩 §六 的 3 与 4（`$/cancelRequest` 与窗口取值的
> 实测）。每一步当时的判断、被推翻的处方与实测数字按时间记在 §七。
>
> 头部只说当前结论。此前它把四段带日期的记录并排放在这里，于是同一段里既写着
> LSP-04 已关账、又写着 LSP-04 撞墙待办，两份索引照抄了错的那半。这不是索引的错，
> 是把日志写进头部的必然结果。

## 一、问题

### 1.1 手写 UTF-8 decoder 不校验（LSP-01）

`selfhost/src/lsp/lsp.dawn` 的 `utf8_decode` 从 percent-decode 出来的字节序列重建码点。
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
（2026-10-19 已测，改为 50 ms，见 §七 末条。）
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
`runtime/c/dawn_rt.{c,h}`、`selfhost/src/embed/rtsrc.dawn`（`gen-rtsrc.py` 重生成）、
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

### 2.2.5 排空、取消、按类调度（§六 step 3，#790，2026-10-19）

**问题**：§2.2.4 的「其它任何东西先 flush」让推迟不可观测，代价是读循环一次只读一帧。
VS Code 每次停顿都同时发出 didChange 和 codeAction，一次长分析期间管道里会排起
`[change v_a, codeAction, change v_b, codeAction, …]`，每个 codeAction 都把一个
**已被身后 sync 取代**的版本送去全量分析；`$/cancelRequest` 也走 flush 分支，
取消本身就会逼出一次分析。

**形状**（`selfhost/src/lsp/server.dawn` 的 `run_lsp_configured`）：

```
loop:
  take = if 有 pending { io.stdin_ready(50) } else { true }
  if take:
    inbox = [读一帧]
    循环：
      while 未读到 Eof/Fatal && io.stdin_ready(0): 读一帧进 inbox
          （读到 $/cancelRequest 时，若目标请求还在 inbox 里未处理，记进 cancelled）
      inbox 空了 → 若刚处理的是「没 flush 就答了的请求」，立刻 flush；退出
      取队头 m：
        已取消的请求        → 回 RequestCancelled（-32800），不 flush
        sync（带文本）      → 进 pending（同 uri 覆盖，异 uri 先 flush）
        TextOnly            → 用「本版本文本」直接答，不 flush
        Inert               → 照旧 handle，不 flush
        Analysed            → flush，再 handle
  else: flush
```

- **消息分类**（`msg_class`，表驱动单测钉住每个方法）：
  - `TextOnly`：formatting、codeAction、documentSymbol。前两个本来只读文本；
    documentSymbol 在分析恰好是同一文本时照旧带 `detail`（签名），否则解析本版本文本、
    省略 `detail`。不拿上一次分析按名字去配：那个签名可能已经不是这个函数的了。
  - `Inert`：`$/` 开头的通知与请求、`initialized`、不带文本的 didOpen/didChange。
  - `Analysed`：其余全部，**包括表里没列的方法**。新加的 handler 默认被当成读分析的，
    先对、再快。didClose/didSave/watched files 也在这里：它们改工作区，publish 序列保持原样
    （lsp-diff 的 `messy` 段就是 didOpen → formatting → didClose）。
- **「本版本文本」**（`text_now`）：pending 是同一 uri 就用 pending 的文本（现算 view 与行表），
  否则用 `st.docs` 里的。pending 的文本**不写进 `Doc`**：QCx 拿 `d.view` 配分析出的 AST，
  先改 `Doc` 不分析就错位了。
- **按序语义不变**：没取消的 `Analysed` 请求只分析它前面的东西，身后排着的 sync 等它答完。
  两个 sync 之间夹着这样的请求就不合并，hover、rename 按它被问到的那个文本作答。
- **为什么答完 TextOnly 后立刻 flush**：客户端在 sync 后紧跟请求，说明这一阵改动已经发完
  （VS Code 的 250 ms Delayer 已经替我们等过了）。不这样做，VS Code 节奏下停手延迟会多出
  一个防抖窗口；P0 的「请求即 flush」正是靠这一点拿到 D=0（调研模型 K1 去掉这条时
  A 467 → 517–543 ms）。
- **规范边界**（LSP 3.17）：
  - `$/cancelRequest`：被取消的请求仍要回复，`RequestCancelled = -32800` 是「服务端看到了取消」时的码。
  - `ContentModified = -32801` 的注释原文：「A server should NOT send this error code if it
    detects a content change in its unprocessed messages ... If a client decides that a result
    is not of any use anymore the client should cancel the request.」所以队列里有后续改动
    **不是**服务端自己放弃的理由，过期的语义请求只能靠客户端取消来省。VS Code 在内容变化的
    瞬间发取消，比被 250 ms 推迟的 didChange 早到，排空正好吃到这个结构。
  - `$/` 开头的通知可以忽略，`$/` 请求回 MethodNotFound：都不 flush。
  - 只有「正在执行」的分析被作废时才轮得到 ContentModified，那是条件刀 2 的事（下文）。
- **排空的边界**：读到 Eof 或 Fatal 就不再读；它们之前的帧照常处理，Fatal 之后的字节仍然
  从不解释（`lsp-framing.py` 28 项照绿）。`exit` 让 `serving = false`，inbox 里剩下的帧不再处理。
  每读一帧多一次 `stdin_ready(0)`，调研实测 JVM 0.67–0.76 µs/次、C 0.18–0.45 µs/次。
- **semanticTokens 不是 TextOnly**：`lsptok.dawn` 的 token 全部来自名字解析
  （`walked_resolutions`），没有「词法部分」。issue 原文那句不准，PR 正文已更正。

#### 三条新断言与它们的变异体（`scripts/lsp-liveness.py`）

三条都是「一次写入多帧」（gap 0）：这里测的是队列，不是时间。

| 断言 | 写入 | 要求 |
|---|---|---|
| `cancel` | didChange v1、semanticTokens K、`$/cancelRequest` K、didChange v2 | K 回 -32800；之后只 publish 一次，version 2 |
| `coalesce` | didChange v1、codeAction、didChange v2、codeAction | 两个 codeAction 都有 result；只 publish 一次，诊断点名 `zzz_2` |
| `order`（护栏） | didChange v1（含 `only_in_one`）、hover 在 `only_in_one` 上、didChange v2 | hover 点名 `only_in_one`；version 1、2 各 publish 一次 |

变异体（本机实测，`java -jar <变异体> lsp`，日志在任务 scratchpad）：

| jar | `cancel` | `coalesce` | `order` |
|---|---|---|---|
| 刀 1 | PASS | PASS | PASS |
| origin/main（改前） | **FAIL** 取消的请求拿到 result，publish `[1, 2]` | **FAIL** 2 次分析 | PASS |
| `no-drain`（`stdin_ready(0)` 前加 `false &&`，只读一帧） | **FAIL** 同上 | **FAIL** 2 次分析 | PASS |
| `no-cancel`（`cancel_target` 恒回 `[]`） | **FAIL** 同上 | PASS | PASS |
| `jump-queue`（Analysed 分支 flush 前把 inbox 里同 uri 的后续 sync 提成 pending） | PASS | PASS | **FAIL** hover 不点名 `only_in_one`，publish `[2, 2]` |
| `text-flushes`（TextOnly 分支先 flush） | PASS | **FAIL** 2 次分析 | PASS |

每条断言至少被一个变异体单独打红；`hangup/liveness/idle/debounce/freshness` 在全部六把 jar 上都是 PASS。`order` 在今天的服务端上是绿的，它防的是「合并过头」。

#### VS Code 节奏回放（前后背靠背）

工具是防抖调研的 `debounce_bench.py` 加两种客户端模式：`vscode-c`（Delayer 250 + codeAction
+ semanticTokens，并在每次内容变化时立刻对未答请求发 `$/cancelRequest`），`vscode-qs`（同上去掉
semanticTokens，每个单词字符后 10 ms 先 flush 再发 completion，照抄调研模型的 vscode-qs）。
两把 jar 都是同一棵源码树加计时探针（flush 前后打 `System.nanoTime`），服务端
`-Xss512m -Xmx2g -XX:+UseSerialGC`，D=50，同一键序列背靠背，每格热身 1 遍、记录 3 遍，
每遍开始前 loadavg ≤ 4（实测 0.22–1.09）。延迟 = 一行最后一键到该版本诊断发布（含客户端
250 ms Delayer）；「过期」= 开始分析时更新的版本已经发到服务端的那些分析。

| 场景 | 改前：延迟中位 / 最大 | 刀 1：延迟中位 / 最大 | 分析次数（3 遍） | 过期分析 | 回 -32800 |
|---|---|---|---|---|---|
| A driver/analyze，vscode-c | 433 / 888 ms | 442 / 465 ms | 35,31,33 → 35,31,33 | 0 → 0 | 0 → 1–3 |
| A，vscode-qs | 426 / 949 ms | 433 / 479 ms | 46,46,48 → 46,46,48 | 0 → 0 | 0 → 0–1 |
| T check/types，vscode-c | 863 / 2099 ms | 809 / 1670 ms | 46,55,45 → 38,47,43 | 2–27 → 0 | 0 → 13–25 |
| T，vscode-qs | **8303 / 10362 ms** | **866 / 1808 ms** | 74,78,82 → 49,52,55 | 70–77 → 0 | 0 → 44–50 |

读法：A 持平（调研模型 R1 之后 0.47 → 0.49 s），中位差 7–9 ms 在遍间噪声内，最大值反而收紧
（改前那两遍 888/949 ms 是一次过期分析挡在最后一版前面）。T 在每键补全节奏下 8.3 s → 0.87 s，
与模型的 12.3 s → 0.64 s 同一量级；过期分析从每遍 70 多次降到 0。T 第一行的 1.3–2.1 s 两边都有，
是那一行的单次分析本身慢（解析失败态的导入者重检，#789 P3），不是调度。
原始数据：任务 scratchpad 的 `runs/*/rows.json` 与 `bench.log`。

#### lsp-diff

`selfhost-lsp-diff.sh` 只差一处：`messy` 段 formatting（id 161）的回复从 publish 之后挪到
publish 之前（2 行）。提交带 `Emit-Change(lsp)`。documentSymbol 到达时没有
pending，字节不变。

#### 刀 2 是条件刀

在模块边界放弃被取代的分析（`driver/incremental.analyze` 加 poll）**不在这一刀**：它要改
name-reuse 与 #789 P3 正在改的函数和契约文件，而且模型预计 R1 之后它主要省 CPU、几乎不省延迟。
等那两刀落地后再量一次，过阈值才做。所以 PR 写的是 `Refs #790`。

### 2.2.6 先发打开文件的诊断（L-edit，2026-10-20）

**问题**：裁决 `ruling-lsp-accept-line-20261019` 把 sync 分两层定线：被编辑文件自身的诊断
（L-edit）p90 ≤ 100 ms，工作区收敛（L-ws）另算。`scripts/lsp-sync-bench/bench.py` 在
origin/main 上量出 L-edit 全部场景越线，(b) `eff_suffix` 签名改动 p90 约 1.3 s，而且 edit 与
sync 在 540 个样本里都差不到 1 ms：服务端等 `incremental.analyze` 把整个工作区算完，
再由 `install_workspace` 按 URI 排序一次发完，被编辑文件从不先发。

**gopls 的做法**（`gopls/internal/server/diagnostics.go` 的 `diagnoseSnapshot`，
https://github.com/golang/tools/blob/master/gopls/internal/server/diagnostics.go ；用户文档
https://tip.golang.org/gopls/features/diagnostics ）：`diagnosticsDelay` 非零时分两段。
第一段 `diagnoseChangedFiles` 只对被改的**打开**文件所在的包做解析与类型检查（不跑 analyzer），
立即以 `final=false` 发布；等 delay 之后第二段算整个工作区，以 `final=true` 发布。
它允许第二段改写第一段：analyzer 的诊断只在第二段出现，所以同一文件可能发两版。
它的 `publishFileDiagnosticsLocked` 只在内容摘要变了时才真的发，同内容不重发。

**Dawn 的形状**：不分两段跑，在**同一次**分析里按模块完成的时刻发。

- `driver/incremental.analyze_placing[S]`：和 `analyze` 同一个循环，多一个折叠回调
  `fn(S, String, Program) -> S`。每个模块的步骤（复用或重检）放进 carry 之后，若它的模块路径
  在调用方给的 `watch` 集合里，就把「这个模块此刻的 Program」交给回调：`modules` 是到它为止的，
  `diags` 是 `loaded.diags` 加**它自己这一步**的诊断，`decl_spans` 是到它为止的。
  `analyze` 就是 `watch` 为空的它，其它调用方不变。
- `lsp/server.dawn`：didChange 与「加入已就绪工作区的 didOpen」重建时，`watch` = 本工作区所有
  打开文档的模块路径。回调把这些文档的诊断按最终的同一条管线（`add_loc_diags` → 工作区 walk
  诊断 → refresh 问题，再经 `diagnostics_for_uri` 把别的根的贡献按键序拼上）算出来，立即
  `publishDiagnostics`，并记下发了什么。`install_workspace` 最后照旧对受影响的 URI 逐个算
  最终诊断；**与已先发的那份相同就不再发**，不同就再发一次（兜底，见下）。
- 依赖方（导入被编辑模块的其它打开文档）也是 `watch` 里的成员，各在自己的模块完成时发；
  关闭的文件（只有带诊断或刚清空诊断的才会被发）等收敛后由 `install_workspace` 发。模块按依赖序
  分析，被编辑模块总在导入它的模块之前完成，所以被编辑文件的 publish 先于依赖方到达。

**正确性：先发的就是最终的**。一个打开文档 U（路径 P、模块 M）最终的诊断表是：

1. `rendered_diags(prog)` 里路径为 P 的条目，按程序顺序。`prog.diags` = `loaded.diags` 接各模块
   步骤的诊断，而 `analyze_module_step` 给每条步骤诊断的路径都是本模块文件（`mf.path`），
   一个程序里不会有两个模块同一路径，所以路径为 P 的只有 `loaded.diags` 里的（分析开始前就定了）
   和 M 自己那一步的。过滤保持相对顺序，所以「`loaded.diags` ++ M 的诊断」过滤到 P 与最终逐条同序。
2. 位置换算 `identity.absolute(prog.decl_spans, d)` 按 `d.owner.module` 查表。M 的诊断只可能归属
   M 或它之前的模块（模块成 DAG，后面的模块 M 看不见），这些表项在 M 完成时都已是最终值：
   后面的模块只往表里**加**自己的键。
3. 工作区 walk 诊断与 refresh 问题来自 plan，不随这次分析变。
4. 别的工作区根对 U 的贡献在这次重建期间不变；`diagnostics_for_uri` 用把本工作区换成临时 slot 的
   状态算，拼接顺序与最终一致。`version` 取同一个 `st.docs`。

所以按论证不会二次发布。`install_workspace` 的「相同才跳过」只是兜底：若哪天有人让后面的模块
往前面的文件报诊断，论证失效时客户端会收到第二版（最终值），而不是停在错的那版上。
新的 liveness 断言 `edit-first` 同时检查每个 URI 在一次 sync 里只发一次，兜底若被触发会红。

**与 #790 的取消、合并语义**：分析本身仍是同步的，中途不读 stdin，也就不存在「工作区那段被新改动
取代」的半截分析（模块边界放弃仍是 §2.2.5 的条件刀 2）。下一轮 sync 照常整轮重发；已先发的不撤回，
被下一轮覆盖，这正是 LSP 对 publishDiagnostics「后到者为准」的语义。冲突快照（同一路径两份文本）
不分析，不先发。独立缓冲区本来就只发自己，不变。

**不覆盖的路径**：didClose、manifest 刷新、首次激活工作区（`activate_workspace`）仍在收敛后统一发。
前两者不在打字路径上；首次激活要冷算全部模块，打开文件也排在依赖之后，先发收益小，而它外面有
`catch_panic` 兜着「装不上就关 lease」，先发一半再 panic 会让客户端看到一个没装上的工作区的诊断。

**负控**（本机，`java -jar <变异体> lsp`）：

| jar | `edit-first`（`lsp-liveness.py`） | 契约 `module memo shows a watched module's diagnostics as final once its step is placed` |
|---|---|---|
| 本刀 | PASS，`[b_lib, a_main]` | PASS |
| origin/main（改前） | **FAIL** `[a_main, b_lib]` | （无此接口） |
| `watch-none`（`analyze_placing` 里 `if false && set.has(watch, …)`） | **FAIL** `[a_main, b_lib]` | — |
| `no-skip`（`install_workspace_after` 不比 `sent`，照发） | **FAIL** `[b_lib, a_main, a_main, b_lib]` | — |
| `load-diags-only`（交给回调的 `diags` 去掉本步的） | **FAIL** `[b_lib, a_main, a_main]`（兜底重发） | **FAIL** |
| `step-diags-only`（去掉 `loaded.diags`） | — | **FAIL** |
| `no-spans`（交给回调的 `decl_spans` 换成空表） | — | **FAIL** |

其余八条 liveness 断言在每把 jar 上都 PASS。`lsp-workspace-contract` 的四个变异体
（`only-current-diagnostics`、`drop-diagnostics-version`、`unopened-version-zero`、`skip-empty-diagnostics`）
与 `retry-unavailable-on-change` 跟着新的发布代码改了锚点，意图不变，本机 `run.sh` 全部「编得过、再打红」。
lsp-diff 对真父提交（`EMITCHANGE_MODE=range`）逐字节相同：语料里没有「打开的导入者 URI 排在被编辑文件之前」的会话，
不写 `Emit-Change`。

**实测**（`scripts/lsp-sync-bench/bench.py --baseline`，两个服务端同时起、逐次交错，默认 6 遍 × 7 轮 + 150 个 `pub fn` 抽样，
launcher 的 `-Xss512m -Xmx2g -XX:+UseSerialGC`；基线是 origin/main `a0c6484f`，本刀是 rebase 后的同一提交，load 1.47–3.85，守卫暂停 1080 s。rebase 前对 `c5fa9ed5` 的一轮同量级，见报告）。单位 ms，中位 / p90：

| 场景 | 改前 edit | 本刀 edit | 改前 sync | 本刀 sync |
|---|---|---|---|---|
| (a) `driver/analyze` 体内 | 122 / 161 | **58 / 156** | 122 / 161 | 65 / 163 |
| (b) `check/types.eff_suffix` 签名 | 242 / 271 | **67 / 179** | 242 / 272 | 243 / 265 |
| (c) `front/ast` 体内 | 32 / 40 | **19 / 83** | 32 / 40 | 34 / 97 |
| (d) `check/types` 加类型 | 728 / 1324 | **67 / 200** | 728 / 1324 | 715 / 1304 |
| 抽样 150 个 `pub fn` | 159 / 268 | **87 / 122** | 159 / 268 | 156 / 252 |

- 中位数全部进了 L-edit 的 100 ms；sync 配对差都在 ±3 ms，先发没有给工作区收敛加成本。
- **p90 在 SerialGC 下仍越线（a 156、b 179、d 200、抽样 122）**。分布是双峰：(rebase 前那轮) (b) 42 个样本里 28 个在 60–83，
  14 个在 126–188。GC 日志（`-Xlog:gc`，同一服务端单跑 (b)）：编辑期间每约 180 ms 一次 young GC，每次 58–71 ms，
  落进约 60 ms 的 edit 窗口的概率正好是三分之一左右。`-Xmn768m` 加大年轻代只让每次停顿更长（a p90 218）。
- 只换收集器、其余参数不变，同一 jar 单跑：ParallelGC edit p90 a 84、b 92、c 39、d 88、抽样 85，**全部在线内**；
  G1 是 88 / 107 / 38 / 137 / 75。两者的 sync 也更低（ParallelGC (b) 198 / 216）。
  换 launcher 的收集器影响所有子命令与内存占用，不在本刀，另列为一刀（§四）。

### 2.3 缓存留到第二步

`analyze_document` 每次重跑 lex/parse/module graph。缓存它们需要失效判定
（哪些模块受这次改动影响），而那要先有模块图的增量表示。
**不在本文范围**——debounce 之后延迟已经从「每次按键」降到「停下来之后一次」，
先量一量还剩多少痛再决定。workspace snapshot 与 target-scoped Java classpath 已于
`18fb3d6` 按 [`../lsp-workspace-design.md`](../lsp-workspace-design.md) 落地；该实现仍明确只修
正确性，不提前做 checker cache。

## 三、为什么不顺手把 X 也改了

- **不改 `textDocumentSync` 到 Incremental**。增量同步要维护文档的行索引
  并正确应用 range 编辑——是自己的一份工作，且它省的是**传输**不是**分析**，
  而痛在分析。
- **不动 `lspq.dawn`**（1,671 行的查询层）。本文只碰传输与调度。
- **不做多线程 LSP**。见 §2.2——单线程 + debounce 已经消掉了竞态，
  引入线程会把它请回来。

## 四、不做的（记录理由）

- **服务端自己回 ContentModified 作废排在改动前面的请求**（clangd 对不发取消的客户端这么做）。
  LSP 3.17 在 `ContentModified` 的注释里明文不许因未处理消息里的改动发它；VS Code 本来就发取消。
- **didClose 与前面同 uri 的 didOpen 合并成什么都不做**。会改 publish 序列（lsp-diff 的 `messy`），
  而 W 类消息几乎不在打字路径上，没有收益。
- **刀 2（模块边界放弃被取代的分析）放进同一刀**。它改 name-reuse 与 #789 P3 正在改的
  `incremental.analyze` 和契约文件；R1 之后模型预计它主要省 CPU，等那两刀落地后量过再定。
- **照 gopls 分两段跑（先只检被改文件所在模块，再算工作区）**（§2.2.6）。Dawn 的模块按依赖序检查，
  被编辑模块本来就在导入它的模块之前完成，在同一次分析里于它完成时发布即可，不必再跑一遍；
  gopls 第一段不跑 analyzer，第二段会改写第一段，Dawn 这样做先发的就是最终的。
- **先发时用「上一轮的依赖方诊断」填充没算到的文件**。那会发出一版注定要被覆盖的过期诊断，
  正是任务要求避免的「先发一版、后发另一版」。
- **只先发被编辑文件，不先发其它打开文件**（§2.2.6）。其它打开文件也是在自己的模块完成时就定了，
  多发不多算，只是早到；限定成被编辑文件反而要多一条判断，还得区分 didOpen。
- **本刀顺手把 launcher 的 `-XX:+UseSerialGC` 换成 ParallelGC**。实测它能让 L-edit 的 p90 全部进线（§2.2.6），
  但 `bin/dawn` 的 JVM 参数管所有子命令（编译、测试、门禁），要量内存峰值与 CI 墙钟，单独一刀。
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
| 1 | `selfhost/src/lsp/lsp.dawn`：`uri_to_path`/`path_to_uri` 改 JDK；删 `utf8_decode`/`utf8_bytes`/percent-decode | lsp 内联 test：Windows drive、UNC、非法 UTF-8、`%2F` |
| 2a ✅ | `scripts/lsp-liveness.py`：挂断 / 存活 / 空转三条断言进仓库，进 `gates.yml` 的 `test` job | **已完成**（2026-08-04）。三条在真 `bin/dawn lsp` 上各被变异体单独打红过，阈值与实测见 §2.2.3 |
| 2b ✅ | `runtime/c/dawn_rt.c`：`io_read_stdin` 从 `fread` 换成 `read(2)`（`io_read_line` 同步） | **已完成**（2026-08-05）。变异体：换回 `fread` 后，6 字节输入读掉 5 字节，就绪查询答 `false`，而第 6 字节确实还在（下一次读拿得到）——正是设计预言的那一格 |
| 2c ✅ | 新 intrinsic `io_stdin_ready(timeout_ms) -> Bool !io` | **已完成**（2026-08-05）。落地点的实际清单与逐点变异体见 §2.2.1 末；9 处里 1 处是错的、另有 4 处漏记。`intrinsic-parity.py` 不覆盖它 |
| 2d ✅ | `selfhost/src/lsp/lsp.dawn`：主循环 debounce + **无事可做时阻塞读**那一支 | **已完成**（2026-08-05）。`lsp-liveness.py` 增两条断言（`debounce` / `freshness`），各有自己的变异体；两个后端的 lsp 转录仍与 v0.50.0 **逐字节相同**。见 §2.2.4 |
| 3 ✅ | `selfhost/src/lsp/server.dawn`：读循环排空、`$/cancelRequest` 回 `RequestCancelled`、按类调度（#790 刀 1） | **已完成**（2026-10-19）。`lsp-liveness.py` 增 `cancel`/`coalesce`/`order` 三条，各被变异体单独打红；VS Code 节奏下 check/types 每键补全 8.3 s → 0.87 s。见 §2.2.5 |
| 4 ✅ | 实测 debounce 窗口，把 150ms 换成有出处的数字 | **已完成**（2026-10-19）：50 ms，出处与代价见 §七 末条 |
| 5 ✅ | `driver/incremental.analyze_placing` + `lsp/server.dawn`：打开文件在自己的模块分析完时先发诊断（L-edit） | **已完成**（2026-10-20）。`lsp-liveness.py` 增 `edit-first`，`contract/module_memo` 增一条逐模块对终值的契约，各被变异体打红。见 §2.2.6 |

无破坏性变更（LSP 是工具，不是语言表面）。2b/2c 动的是运行时契约与 intrinsic 表，
但只加不改：`io_read_stdin` 的**可观察**语义（恰好 n 字节，短读即 EOF）不变，
换掉的是它底下的缓冲层。

## 七、落地日志（按时间顺序）

> 本节是过程记录，按发生顺序读；结论在头部。

**2026-07-30 改判后落地（LSP-01 的 UTF-8 半）**：台账 §3.7 的「换 JDK」处方被当日
架构再次作废——缝 1 之后 `lsp.dawn` 是共享前端（零 `use java`，两个 main 共用一份），
换回 `java.net.URI` 等于把它踢出共享半区。按原则的正确形态落地：**手写 decoder 修成
校验的**（continuation 区间 / overlong / surrogate / 超 U+10FFFF 全拒，坏序列出
U+FFFD 降级续读），一份纯 Dawn 实现两个工具链共用，单测钉住五类畸形输入。
**LSP-02 也已落地（同日）**：authority（空/localhost 才是本机，其他主机回 None
而不是猜出一个相对路径）、query 与 fragment 在解码前切掉、Windows 盘符
（`file:///C:/x` → `C:/x`；`/c/x` 不是盘符）、`path_to_uri` 恒发三斜杠的空 authority
形式（`C:/x` 若不补斜杠会把盘符解析成主机名），`:` 不再被百分号编码（RFC 3986 的
pchar，且 `%3A` 人读不出）。往返测试含重音字符与盘符。

**当日 LSP-04（debounce）撞墙已记档**：§2.2 的方案依赖「`read_message` 加一个超时形式
（有输入就读，没输入就返回 `Idle`）」，而 std/io 只有阻塞的 `read_stdin(n)`——**没有任何
「就绪/超时」原语**。造一个（`io_stdin_ready(timeout_ms) -> Bool` 之类）是**运行时契约
变更**：两个后端各实现一份（JVM 的 available/带超时读 vs C 的 poll/select）、进 spec §11
的原语表、进 intrinsic 语义表。那是一把独立的刀，且它的设计题（就绪 vs 超时读、
EOF 怎么表达、native 上的信号语义）比 debounce 本身大——**不该顺手塞进 LSP 改动里**，
半设计好的原语进语言表面比不做更糟。debounce 的其余部分（generation 计数、
`$/cancelRequest` 直接回 RequestCancelled）都在那个原语之后才有意义。

**2026-08-04 实测收口**：设计题已经用探针答完，形状定了（语义 B 的 `Bool`），
验收实验也已建出并用变异体打红过——见 §2.2.1 与 §2.2.2。落地还欠一件前置：
C 后端的 `io_read_stdin` 得先从 stdio 换成 `read(2)`。本轮不写任何代码。

**2026-08-05 落地（2b + 2c）**：前置与原语都进了树。实测两个后端在五种 stdin 状态
（管道有数据 / 管道静默 / 管道 EOF / 有数据且 EOF / 常规文件）上**每一格布尔值都相同**；
时延照契约分岔且都在「至多」这一侧——EOF 那格 native 立刻回 `false`、JVM 耗满窗口。
落地点的真实清单与逐点变异体记在 §2.2.1 末（原表 9 条错 1 条、漏 4 处）。

**2026-08-05 落地（2d）与关账**：2d 被种子代际隔在 2b/2c 之后一代——`selfhost/src`
只准用当前种子已支持的特性（docs/bootstrap.md §种子推进协议 3），所以 `lsp.dawn` 调
`io.stdin_ready` 必须等 2b/2c 发一个 release、bump `scripts/seed-release.txt` 之后才编得动。
之后：`scripts/lsp-liveness.py` 的三条断言进 CI 并被变异体逐条打红；C 后端两个 stdin
读取器都改走 `read(2)`（不再有 stdio 缓冲挡在就绪查询前面）；`io_stdin_ready` 进了原语表
并在两个后端上答出同一张真值表；`lsp.dawn` 的读循环 debounce 了。**LSP-04 至此关账。**
LSP-01 的落地形态与本文原方案相反：不换 JDK，而是把手写 decoder 改成校验的。
台账见 [native-plan-overlap.md](native-plan-overlap.md) §3.7——其「换 JDK」处方已作废。

**2026-10-19 step 4 落地：`DEBOUNCE_MS` 150 → 50**。依据是一轮本机实测（VS Code 与
Playground 两种客户端各跑一遍，服务端 `-Xss512m -Xmx2g -XX:+UseSerialGC`）加两份按键
节奏出处：

- VS Code 的 `vscode-languageclient` 在 Full sync 下自带 250 ms 尾随合并，光标停下后
  的 codeAction 又会强制服务端立刻分析；D=0/150/400 三档的分析次数相同（16/16/16、
  19/19/19、34/34/34），服务端窗口在它下面被绕过。
- Playground 同一时刻只有一个 sync 在途，窗口是每次往返的纯延迟：停手到诊断
  D=150 时 152 ms，D=50 时 52 ms，分析次数不变（约 81 次）。
- 150 ms 也等不到停手：从 Dhakal 等（CHI 2018，136M 按键）随机抽 356 人、25.5 万个
  键间隔，57% 超过 150 ms；Thomas 等（ACE 2005）测得 IDE 里改代码的字母连击中位数
  174 ms、块边界 474 ms。
- 代价只落在逐键发送、自己不合并的客户端上：以 `lsp/lspc` 为模型、中速打字者、
  每档 200 个种子，150 → 50 让每键服务端忙碌 148 → 183 ms（+24%），停手到诊断的
  中位数 334 → 272 ms。

`scripts/lsp-liveness.py` 的 `KEYSTROKE_GAP_S` 同刀 0.06 → 0.03：它必须夹在 §2.2.3 的
20 ms 下限与窗口之间，60 ms 已越过 50 ms 窗口。诊断延迟的大头不在防抖：解析失败态
的崩溃（#788）与重渲染（#789 R1）同一 PR 修掉；非 sync 消息强制分析过期态（#790）
另案。不做自适应防抖（clangd 式）：没有取消机制前，自适应只是在错的地方调参。

**2026-10-19 step 3 落地（#790 刀 1）**：读循环先排空已到达的帧再处理，客户端取消的请求回
RequestCancelled，formatting/codeAction/documentSymbol 从本版本文本直接答，`$/` 消息不再 flush；
没取消的语义请求仍按序只分析它前面的文本。设计、三条新断言与四个变异体、前后实测见 §2.2.5。
lsp 转录只差 `messy` 段 formatting 回复的位置（`Emit-Change(lsp)`）。不回 ContentModified
（LSP 3.17 明文不许因未处理消息里的改动发它）；模块边界放弃（刀 2）留作条件刀。

**2026-10-20 step 5 落地（L-edit）**：`driver/incremental.analyze_placing` 在每个打开文档的模块放进 carry 时把
「到它为止的程序」交给 LSP，服务端当场发布这个文档的诊断，收敛后只补发内容变了的 URI。先发的就是最终的
（论证与负控见 §2.2.6）。L-edit 中位数 (b) 242 → 67 ms、(d) 728 → 67 ms、抽样 159 → 87 ms；p90 仍被 SerialGC 的
young GC 拖在 122–200 ms，ParallelGC 下全部进线，换收集器另列一刀。
