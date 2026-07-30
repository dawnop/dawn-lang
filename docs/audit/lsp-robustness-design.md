# LSP：URI、UTF-8 与响应性

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **LSP-01（P1）**、**LSP-02（P1）**、**LSP-04（P2）**。
> （LSP-03「畸形 frame 让服务器静默退出」已于 2026-07-25 修复。）
> 状态：**proposed，可做**——改法与
> [`../native-backend-plan.md`](../native-backend-plan.md) 不重合，
> 但 §四里「不留 fallback」那条的**理由**被它作废了，已改写。
> 台账见 [native-plan-overlap.md](native-plan-overlap.md) §3.7。


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
  match java_try(fn() => Paths.get(URI.create(uri)!)!.toString()!) {
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

> **就绪原语的关键分叉（2026-07-30 侦察，尚未动手）**：形状应取
> `io_stdin_ready(timeout_ms: Int) -> Bool`（就绪查询，不读字节；阻塞读仍是唯一读者，
> 于是 EOF 语义不被搅动）——而不是「带超时的读」，后者会把超时与 EOF 混成同一个短读，
> 而 LSP 的帧协议已经把短读判成 EOF。
>
> **但两个后端对「EOF 时是否就绪」天然不同答**：POSIX 的 `poll` 在 EOF 时报 `POLLIN`
> 就绪（读不会阻塞，返回 0），而 Java 的 `InputStream.available()` 在 EOF 时返回 0，
> 即「不就绪」。契约必须选一个，而**必须选 POSIX 那个**：若 EOF 算不就绪，一个关掉管道的
> 客户端会让服务器永远等一个不会到来的就绪信号——空转而非退出。代价是 JVM 侧
> `available()` 单独答不出这个（它分不清「暂时没有」与「永远没有」），要么裹
> `PushbackInputStream` 预读一字节（而预读本身会阻塞，正是要避免的），要么另起一条读线程。
> **这就是这把刀真正的设计题**，也是它不该被顺手塞进任何别的改动的原因：选错的后果是
> 服务器空转或挂死，而两者都不会在单元测试里出现。

`$/cancelRequest` 在这个模型下可以直接**回一个 `RequestCancelled` 错误**——
因为没有真的在跑的请求可以取消，请求要么还没开始要么已经完成。这是合规的。

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

## 六、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| 0 | `scripts/selfhost-lsp-diff.sh` 语料加畸形 URI | 记录旧行为 |
| 1 | `selfhost/src/lsp.dawn`：`uri_to_path`/`path_to_uri` 改 JDK；删 `utf8_decode`/`utf8_bytes`/percent-decode | lsp 内联 test：Windows drive、UNC、非法 UTF-8、`%2F` |
| 2 | `selfhost/src/lsp.dawn`：`read_message` 加 `Idle`；主循环 debounce + generation | 「连续 5 次 didChange 只分析 1 次」 |
| 3 | `selfhost/src/lsp.dawn`：`$/cancelRequest` 回 `RequestCancelled` | 协议合规 |
| 4 | 实测 debounce 窗口，把 150ms 换成有出处的数字 | 记录 harness 与数据 |

无破坏性变更（LSP 是工具，不是语言表面）。
