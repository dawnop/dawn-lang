# `packages/web` 第七个 major：JDK server 拆成独立包（`web7 / 7.0.0` 与 `web_jvm / 1.0.0`），及单交换适配层（§九）

> 状态：**current** —— 2026-10-20，native B1a。依据：「完全 native 化」裁决第 4 条与调研 §1(B)、
> Q4（均在本仓外的 agent-handoff）。本篇写成于动码前，实现后回填了 §八的实测。
> 下一刀（B1b，单交换适配层）在 §九，§七留的接口在那里兑现。
> 修订（同日）：初稿把 Java 收进包内一个模块，协调者验收时指出目录加载会读 `src/` 下每个模块，
> 包内留一个 JVM 模块就让整包 native check/doc 仍然红、A2 的例外去不掉，故改为独立包。§二、§五、§六、不做的据此重写。

## 一、问题

`packages/web` 有 34 行 `use java`：`types.dawn` 一行（`InputStream`）、`server.dawn` 三十三行
（`HttpServer`、虚拟线程 executor、`ResponseStream` 的 pump、`spill_body`，以及测试夹具用的
`HttpClient`、`HttpURLConnection`）。native 驱动拒绝任何可达的 `use java`
（`jsig_refused`），所以对这个包它什么也做不了。动手前实测（v0.94.0 的 `dawnc`，只跑 check 与 doc）：

```
dawnc check packages/web    -> 255 errors   (types 3, server 251, 余下为级联)
dawnc doc   packages/web    -> error: `use java` is not available in this compiler
                               --> packages/web/src/types.dawn:12:10
```

代价不只是一个包：站点的包页文档要给 web 留一个 JVM 例外（A2 的 `package-docs.sh`），
`native-asan-tests.sh` 有一条 `EXCLUDED`，Playground runner 为此自写了 `play/http1.dawn`，
完全 native 化的服务线也卡在这里。

这些 Java 里**真正需要 Java 的只有一小块**：服务器本身（socket、线程、HTTP 解析）。
别的都是借道：`types.dawn` 的 `InputStream` 只因为流式响应体要装一个上游；`server.dawn` 里的
路径、查询串、表单的语义（切段、百分号解码、点段拒绝、多值折叠）是 String 到 String 的纯函数，
却因为 `URLDecoder` 两处调用，和 JDK 住在了一起。

## 二、包与模块边界

`packages/web`（`web7`）纯 Dawn，零 `use java`：

| 模块 | 内容 |
|---|---|
| `web/types` | `Request`、`Response` 及构造器、`HttpError`、`ErrorFormat`、`BodySource`、`DEFAULT_MAX_BODY` |
| `web/router` | 路由表、`route_*`、`tagged`、`body_limit`、`guarded`，以及服务器要用的分派（`dispatch_segs`、`validate_routes`、`Dispatch`、`route_meta`） |
| `web/middleware` | `with_logging`、`with_cors`、`with_body_limit` |
| `web/wire`（新） | 路径切段与解码、点段拒绝、查询串与表单（`parse_form`、`form_value`、`form_all`） |

`packages/web-jvm`（manifest 名 `web_jvm`，`1.0.0`）：一个模块 `web_jvm/server`（原 `web/server`），
带全部 `use java`，`[deps]` 里 `web = "../web"`。放在 `server` 而不是 `web_jvm/jvm_server`，因为包名已经说了后端。

**命名**：仓里多词包名目录用连字符（`tea-core`、`tea-dom`）、manifest 名用下划线（`tea_core`），
依赖别名取 manifest 名；`web-jvm` / `web_jvm` 照此。major 在名字里只从 2 起带（`web7`、`json2`），
`web_jvm` 是新包，从 1.0.0 起，名字不带数字。

**搬了什么、为什么：**

- `wire` 里的函数原本 `!io`，只因为 `URLDecoder.decode` 会抛、而唯一能接住的 `catch_fault` 是 `!io`。
  现在百分号解码用 `std/bytes` 的 `decode_utf8_lossy` 自己做，函数是纯的，`parse_form` 不再带 `!io`。
  两个服务器（JVM 的、B1b 的）读请求走同一份代码，这是单独成模块的理由。
- `DEFAULT_MAX_BODY` 进 `types`：任何服务器都从同一个数起步。`ServerConfig` 留在 `web_jvm/server`，
  因为它有 `host` 与 `port`，单交换适配层没有。
- **跨包要付的公开面。** 服务器原先在包内，靠 `pub(pkg)` 读 `Response` 的内部表示、调分派与路径函数。
  跨包后：`Response` 仍 opaque，服务器改用已有的公开访问器（`response_status`、`response_content_type`、
  `response_headers`、`response_body`）读它，**没有**新开内部表示；但 `Dispatch`、`dispatch_segs`、
  `validate_routes`、`route_meta`、`raw_segs`、`decode_path_seg`、`has_dot_segment`、`parse_query`、
  `multimap`、`join_with`、`log_request` 从 `pub(pkg)` 升为 `pub`，加了 `##` 文档。这是 web5 收窄过的面
  再放开一部分，理由是「写服务器的人需要它们」；它们是读请求的规则与分派决策，不是能绕过构造器检查的东西。
- `same_body`/`same_response`（`pub(pkg)`）是给包内测试用的相等，见 §三的代价。

## 三、流式响应体的新形状

`ResponseBody` 的 `Stream(value: InputStream, length: Option[Int])` 要换成不带 Java 类型的形状。
比较了三种：

**A. 拉取式 `BodySource = { read: fn(Int) -> Bytes !io, close: fn() -> Unit !io }`（选定）。**
`read(n)` 至多返回 `n` 字节、空 `Bytes` 表示结束；`close` 释放上游，服务器对每个收到的
source 恰好调一次（读完、传输失败、HEAD 与 1xx/204/205/304 根本不读，三种出口都调）。

**B. 推送式 `Stream(run: fn(fn(Bytes) -> Unit !io) -> Unit !io, length)`。**
响应体是「往 sink 里写」的函数，服务器给 sink。对单交换适配层最顺（sink 就是写 stdout），
也不需要 close：生产者自己用 `bracket`。但**上游在构造响应时已经打开**（要先拿到状态码与头才能决定
返回什么响应），HEAD 与无体状态下 `run` 根本不会被调，上游就没人关。补一个 `close` 字段后它是
A 加一层回调，没有更简单。另外「服务器统计已发字节以判截断」要包一层计数的 sink，比数 `read` 的返回值绕。

**C. 核心里声明一个抽象类型，由 JVM 一侧填。** 语言没有「核心声明、后端填入」的机制：要么核心
`use java` 才能写出表示，要么用 `cast` 绕，而 `cast` 要 Java 的 `Object`。这条路等于没拆，否决。

选 A 的理由：形状同 std 的读风格（`read(n)`），native 适配层直接用 `read_stdin`
与 fd 读实现；`close` 语义只有一条；截断与失败的判别（`pump_with`）原样保留，只是把
`transferTo` 换成按 8 KiB 读写的 `copy_source`。

**代价，如实写下：**

1. **`ResponseBody` 与 `Response` 失去 `==`。** 函数没有相等，`response_body(r) == Text("x")`
   从此是类型错误。包内测试改用 `same_body`/`same_response`（`pub(pkg)`）；下游测试改用 `match`。
   这是破坏面的一项（§四）。
2. **每块多一次 `Bytes` 分配。** 原来 `transferTo` 在 JDK 里搬字节，现在每 8 KiB 经过
   `readNBytes`。**本篇不做吞吐断言**，没有测过；真要在意，B1b 稳定后用 dawnop-site 的
   下载路径测，数据再回填这里。
3. **「有多少读多少」要自己做。** `InputStream.readNBytes(n)` 会等到读满 `n` 字节或 EOF，
   用它做 `read` 会让慢上游的下载卡到攒满一块才出第一个字节，破坏流式响应存在的理由。
   `input_source` 因此先读一个字节（阻塞），再取 `available()` 内已就绪的部分，等价于
   `read(byte[])`；有测试钉住（`an InputStream source reads what is ready…`）。

## 四、major 的破坏面

`web` 包名 `web6` → `web7`（v2-in-name 规则），版本 `7.0.0`；`web_jvm` 从 `1.0.0` 起。
CHANGELOG 里逐条写了迁移办法，这里只列面：

1. `web/server` 没了：`start`、`join`、`stop`、`serve_app`、`serve_app_with`、`ServerConfig`、
   `ServerHandle`、`handle_port` 在新包 `web_jvm/server`，签名不变；消费者在 `[deps]` 里 `web` 旁加一条 `web_jvm`。
2. `parse_form`、`form_value`、`form_all` 搬到 `web/wire`；`parse_form` 去掉 `!io`。
3. `DEFAULT_MAX_BODY` 搬到 `web/types`。
4. `streaming` 第三个参数与 `Stream` 变体的载荷由 `InputStream` 改为 `BodySource`；
   JVM 程序用 `web_jvm/server.input_source(stream)` 包一层。
5. `ResponseBody`、`Response` 没有 `==`。
6. 百分号解码的一处行为差：JDK 的 `URLDecoder` 接受带符号的转义（`%+1` 解成字节 1），
   新实现只认十六进制数字，`%+1` 是畸形转义、整个分量原样保留。其余与原来一致。
7. 公开面放开一部分（§二末条），属加法。

不做兼容层：没有弃用别名，没有 `web/server` 转发模块（转发模块要 `web` 依赖 `web_jvm`，
方向反了，也会让 `web` 重新带上 `use java`）。仓内无调用方，外部只有 dawnop-site，
升钉那一刀由协调者安排；改动点清单在本刀报告里，其中 `[deps]` 要多一条 `web_jvm`。

## 五、拆开之后 native 能做什么

实测（v0.94.0 `dawnc`，整包目录目标）：

```
dawnc check packages/web   -> ok
dawnc doc   packages/web   -> 四个模块的文档 JSON
dawnc test  packages/web   -> 61 passed
```

整包 check、doc、test 都过，这是任务单要的结果。夜间 ASan（`native-asan-tests.sh`）按目录跑 `packages/web`，
`EXCLUDED` 里换成 `packages/web-jvm`（带 `use java` 的那个包，原因由脚本复核）。

## 六、文档与 A2 例外

A2 的 `site/package-docs.sh` 按包内容判断走哪个驱动：包自己或任一路径依赖含 `use java` 行就走
`./bin/dawn doc`，否则走 `dawnc doc`，没有手写名单。拆分后：

- `web`：无 `use java`，也无含 `use java` 的路径依赖，走 `dawnc doc`，例外自然消失；
- `web-jvm`：含 `use java`，走 JVM 驱动，判据照旧，脚本里的 JVM 分支**必须保留**（它不是过渡态了）。

所以 A2 脚本的判据一行不用改，只有它头注释里「web 留 JVM 直到 B1」那句要换成 `web-jvm`；
那个文件在 #822 里，合入后随 rebase 改（见报告）。包页多一个 `web-jvm` 条目，由目录枚举自动带出。

## 七、给 B1b 留的接口

B1b 的单交换适配层只用 std 的 stdin/stdout 原语，是纯 Dawn，可以直接放进 `web` 包（不必再拆包）。它只需要：

- `wire` 的路径、查询、表单（同一份代码，两边同跑 golden 契约时不会漂）；
- `BodySource`（stdin 读、stdout 写即可实现）；
- `DEFAULT_MAX_BODY` 与 `ErrorFormat`。

`web_jvm/server` 里尚未抽出的、B1b 必须与它一致的语义：`body_length` 的帧决策（`-1`/`0`/`n`，
JDK 约定，B1b 应先把它改成后端中立的三态再复用）、守卫在读体前运行、`stream-body` 的 spill 与
413 的三处措辞、HEAD 的头与长度、1xx/204/205/304 无体。本刀**没有**动这些，只是不再让它们
和 JDK 调用纠缠在同一个模块之外的地方。

## 八、验证与门

- JVM：`dawn test packages/web` 61 项、`dawn test packages/web-jvm` 91 项（含依赖 web 的 52 项，
  自身 39 项），合计与拆分前的 100 项一致，含 #818 的断言 helper；另有三项新增
  （百分号解码的边界、路径段的加号、`input_source` 的就绪读取）。
- `scripts/native-web-core.sh`：`dawnc check packages/web` 与 `dawnc doc packages/web` 整包通过，
  带两条负控（往 `router.dawn` 加回一行 `use java`、把 `web-jvm` 的服务器模块拷进 `web/src`），
  都必须因 `use java` 被拒而红。作为 `prev-diff-native` job 的一个独立步骤跑在
  `native-cli-diff.sh` 之后，本机 1.4 s，按 5 s 计入预算（job 785 s → 790 s，push 总量 +5 s）。
- `emit packages/web-jvm` 加进 prev-diff 与 classfile-verify 的语料，原来 `emit packages/web` 里的
  服务器类现在由它覆盖。

## 九、单交换适配层（B1b，`web7 / 7.1.0`、`web_jvm / 1.1.0`）

> 追加于 2026-10-21，native B1b。依据：裁决第 1 条（一请求一进程）、第 4 条（web 单交换适配层）与 B0 补注；
> 调研 §1(B)。§七留的接口在这里兑现。本节写成于动码前，§九.7 的数字是实现后的实测。

### 九.1 边界

一个函数 `web/exchange.serve_exchange(cfg, routes, middleware, t)`：从 `Transport` 读一次 HTTP/1.1 交换的
原始请求字节，解析成 `Request`，跑应用（分派、点段拒绝、守卫、请求体、中间件、handler），把 `Response`
写成字节，返回。纯 Dawn，零 `use java`，放进 `web`（B1a 报告已确认不必拆包；它只用 std 的 bytes、str，
以及 spill 用的临时文件）。

```
Transport  = { read: fn(Int, Int) -> Bytes !io, write: fn(Bytes) -> Unit !io }
ExchangeConfig = { max_body: Int, errors: ErrorFormat }        # 没有 host 与 port：这里不监听
```

- **后端中立的读取接口**。`read(pos, n)` 返回请求自偏移 `pos` 起至多 `n` 字节，空 `Bytes` 表示请求结束。真流（stdin、
  socket）忽略 `pos` 只给下一批字节，测试用 `Bytes` 按 `pos` 切片。带 `pos` 不是为了随机访问，而是因为闭包不能
  修改捕获的变量，一个假 transport 没有别的办法有状态（实测：`cannot assign to n from inside a lambda`）。
- **头部一次一字节读到 CRLFCRLF**。`std/io.read_stdin(n)` 是「恰好 n 字节，只在 EOF 处变短」，更大的读会阻塞到
  攒满；一请求一进程不付这个代价，换来的是没有读缓冲、没有要带到下一个请求的状态。体按 8 KiB 分片读，
  「至多 n」与「恰好 n」两种流都能用。
- **stdout 就是线**。适配层自己的日志一律走 stderr；`with_logging` 打 stdout，在这个 transport 上那就是响应的字节，
  所以新增 `with_logging_to_stderr`，走 `serve_exchange` 的程序装它。
- **`web_jvm/server` 共用决定，不共用解析器**。jdk.httpserver 在任何 Dawn 代码运行前就把线上的东西解析完了，解析器没法共用；
  解析之后的每一个决定能共用，也共用了：分派、点段 400、守卫先于读体、体的上限（`body_ceiling`）、中间件链与 panic 的 500
  （`serve_through`）、响应帧的决定（`framing`：`Withheld`/`Sized(n)`/`Chunked` 三态，JDK 一侧再译成 `-1`/`n`/`0`）、
  流式体的收尾分类（`pump_with`、`pump_report`）。它们是 `web/exchange` 里的 `pub` 函数，`web_jvm/server` 直接调用，
  原先 server.dawn 里的同名私有副本已删。日志落点作为参数（`log`）传入：JDK 一侧 stdout，适配层 stderr。

### 九.2 语义清单：与 `web_jvm/server` 一致的每一条

「契约」列是 `scripts/web-exchange-contract/contract.py` 里钉住这条的夹具。

| 规则 | JVM 一侧 | 适配层 | 契约夹具 |
|---|---|---|---|
| 请求行：方法是 token，目标是 origin-form（以 `/` 开头），版本 `HTTP/1.0` 或 `HTTP/1.1` | JDK 解析 | `parse_request_line` | `head-garbage-request-line`，`head-http-2` |
| 头部：名字是 token，值不含控制符，不接受折行，不接受裸 CR/LF；键小写、重复名保序成 multimap（WEB-04） | JDK 解析，`read_headers` 折成小写 multimap | `parse_head` | `query-multimap`（`X-Multi` 两次） |
| 目标里 java.net.URI 会拒绝的东西（坏的 `%` 转义，`"<>\^`{|}[]` 与 DEL）一律 400 | JDK 的 `URISyntaxException` | `target_ok` | `path-bad-escape`、`path-truncated-escape`、`path-signed-escape`、`path-illegal-char`、`path-illegal-bracket`、`query-bad-escape`、`query-illegal-char` |
| 路径与查询串的含义：按原始路径切段再各段独立解码（WEB-03），`+` 在路径里是字面量，查询串先切后解（防参数走私） | `web/wire` | 同一份 `web/wire` | `path-encoded-slash`、`path-utf8`、`path-plus-literal`、`path-tail-capture`、`path-interior-empty`、`query-multimap` |
| 点段（`.` `..`，原样或百分号编码）在每条路由上 400，且在分派之后、读体之前，所以 400 带着匹配路由的 tags、走完中间件链 | `handle` | `serve_request` | `dot-segment-plain`、`-single`、`-encoded`、`-on-a-route`、`-with-body` |
| 守卫先于读体；守卫的拒绝也走中间件链，体一个字节都不读；守卫 panic 是应用措辞的 500 | `build_request` | `build_request` + 共用的 `run_guard` | `guard-refuses`、`guard-refuses-without-reading`、`guard-passes*` |
| `Content-Length` 请求体：声明长度超上限时读之前就 413；否则读恰好那么多字节 | `read_body` | `read_body` | `body-content-length`、`body-exact-ceiling`、`body-over-ceiling`、`body-over-ceiling-declared-only` |
| chunked 请求体：解码；扩展 `;name=value` 读后丢弃；超上限的那个 chunk 读之前就 413 | JDK 的 chunked 流 | `read_chunked` | `chunked-*`（含 `-extension`、`-over-ceiling`、`-over-ceiling-split`、`-route-ceiling-over`） |
| 体的上限：路由的 `body_limit` 优先，否则服务器的 `max_body`；`raw-body` 路由除非自带上限否则无上限；`stream-body` 路由按路由自己的上限 | `body_ceiling` | 同一个 `body_ceiling` | `body-route-ceiling-*`、`spill-*` |
| 畸形的请求体（chunk 大小不是十六进制、chunk 后缺 CRLF、裸 LF、体比声明短、trailer 无尽头）是同一个 400，同一句话 `malformed request body` | `read_chunk`（本刀新增） | `bad_body` | `chunked-bad-size`、`-empty-size`、`-missing-data-crlf`、`-cut-short`、`-no-terminator`、`-bare-lf`、`-size-overflow`、`body-short-of-length` |
| 请求体格式歧义（`Content-Length` 与 `Transfer-Encoding` 并存、重复 `Content-Length`、带符号的长度）400，不是 `chunked` 的编码 501 | JDK | `body_kind` | `head-te-gzip` |
| `stream-body` 路由：handler 拿到 `body_file` 与空 `body`，临时文件在 handler 返回后删 | `spill_body` | `spill_body`（见九.5 的差别） | `spill-content-length`、`-chunked`、`-empty`、`-over-route-ceiling`、`-no-server-ceiling` |
| HEAD：状态与头与 GET 一致，长度已知且大于 0 时带 `Content-Length`，不写 body；流式体照样 `close` | `write_response` | `write_response` | `head-hello`、`head-empty`、`head-204`、`head-404`、`head-stream-*` |
| 1xx、204、205、304 无体、无长度头，流式体关闭不读 | `framing` | `framing` | `get-204-no-body`、`stream-on-a-no-body-status` |
| 空体是 `Content-Length: 0`；Text 按 UTF-8 字节数；Binary 逐字节 | `framing` | `framing` | `get-empty-body`、`body-binary`、`chunked-binary` |
| 流式体：长度未知 `Transfer-Encoding: chunked`，已知则精确 `Content-Length`；传输失败与 panic 与干净 EOF 三分，截短单列 | `pump_with` | 同一个 `pump_with` | `stream-chunked`、`stream-sized`、`stream-short-of-its-length`、`stream-past-its-length` |
| 错误响应的形状：`{"<detail_key>": message}`，措辞来自 `ErrorFormat`，错误自带的头（`WWW-Authenticate`）原样带上 | `error_response` | 同一个 `error_response` | `guard-refuses`、`body-over-ceiling` |
| 中间件顺序：`[a, b]` 是 `a(b(core))`；每一个答复（404、405、400、413、401）都过链 | `serve_through` | 同一个 `serve_through` | 夹具应用的 `X-Stamped` 中间件盖在每个答复上 |
| handler panic 是应用措辞的 500，原因进日志 | `serve_through` | 同一个 | `handler-panic` |
| 头部之前的拒绝（头解析失败、体帧不可用）没有 `Request`，不过中间件，答框架自己的 JSON 错误 | JDK 自己答 | `refuse` | `head-*`（只比状态） |
| `Connection: close`：一请求一进程，不做 keep-alive、不做管线化 | JDK 按请求头 | 每个响应都发 | 驱动检查每个 native 响应都带它 |

### 九.3 响应的线格式

状态行 `HTTP/1.1 <code> <reason>`；头依次是 `Content-Type`、响应自带的头（按序）、`Content-Length` 或
`Transfer-Encoding: chunked`、`Connection: close`。流式体每次 `read` 的结果写成一个 chunk，正常结束写 `0\r\n\r\n`；失败或
panic 时**不写**结尾 chunk，连接带着缺口结束，客户端据此知道被截断（状态码已经发出，没有别的信号）。
`Sized(n)` 的流若上游写超过 `n`，那一片不写，pump 以 panic 分类（JDK 的定长流对同一情况是拒绝写入），日志一行。
HTTP/1.0 客户端的 chunked 响应不带分帧、靠关闭连接结束。

### 九.4 先例

- **CGI（RFC 3875）与 SCGI**：一次交换一个进程（CGI）或一个 netstring 头加体（SCGI），请求体按 `CONTENT_LENGTH` 读，
  chunked 由前置服务器消掉。我们是同一形状，但 chunked 由适配层自己消，因为前置 nginx 在 `proxy_request_buffering off`
  时会把 chunked 原样转给上游。
- **Go `net/http/cgi`**：`cgi.Serve(handler)` 从环境和 stdin 构造 `*http.Request`，把 `ResponseWriter` 的输出写到 stdout；
  应用代码与 `net/http` 服务器上跑的是同一个 `Handler`。这正是这里「同一个应用、两个 server」的形状；
  Go 的 chunked 解码在 `net/http/internal` 的 `chunkedReader`，对 chunk 头一行有长度上限（`errLineTooLong`），
  对 `http.MaxBytesReader` 的上限在读的时候数、越界即停，与 `read_chunked` 的「越界那个 chunk 读之前就拒」同向。
- **Rust hyper 的 HTTP/1 解码**（`proto/h1/decode.rs`）：把体的帧分成 `Length`、`Chunked`、`Eof` 三种 `Decoder`，
  chunk 解码是一个字节一个字节推进的状态机（size、扩展、LF、数据、CR、LF、trailer），chunk 扩展有上限。
  我们按同一个切分（`BodyKind = NoBody | Counted | ChunkedBody`），用「一次读一行」代替状态机，因为这里没有异步。
- **Python `wsgiref`**：`wsgiref.handlers.CGIHandler` 是 WSGI 的单交换形态，`wsgi.input` 就是 stdin，按 CGI 的约定
  读 `CONTENT_LENGTH`，不解码 chunked 请求体。它是反例：不解码 chunked 的单交换层，要求前置服务器消掉。

出处是各项目的公开规范与源码文件（RFC 3875；SCGI 规范；`net/http/cgi/child.go`、`net/http/internal/chunked.go`；
hyper 的 `src/proto/h1/decode.rs`；CPython `Lib/wsgiref/handlers.py`），本篇没有逐行引用行号。

### 九.5 与 JVM 一侧不同的地方，逐条列全

契约把下面每一条当作**已知差异**：夹具里带 `jvm=<状态>` 或 `compare="status"`/`"short"`，驱动只比状态（或比「都没交付完整长度」），不比字节。
没有列在这里的差异都是红。

1. **JDK 自己的头部拒绝**。头解析失败、坏转义、非法字符，JDK 在 Dawn 运行前答自己的 `text/html` 400，体是
   `<h1>400 Bad Request</h1>URISyntaxException thrown`；适配层答框架的 JSON 400。状态一致，体不比。
2. **trailer**。RFC 9112 §7.1.2 允许 chunked 体后带 trailer 段；JDK 的 chunked 流遇到 trailer 抛异常（本刀之前是 500，
   现在随畸形体一起是 400）。适配层按 RFC 读完丢弃，答 200。夹具 `chunked-trailer`：JVM 400，适配层 200。
3. **HTTP 版本与目标形式**。JDK 把任何版本记号当 1.1 服务，也接受 absolute-form（`GET http://h/x`）；适配层只讲 1.0/1.1、
   只收 origin-form，其余 505/400。前置的 nginx 从不发这两种。夹具 `head-http-2`、`head-absolute-form`。
4. **失败的流式体**。JDK 的响应头与已写的体留在缓冲里，定长流中途失败时整个连接被关闭、客户端什么都没收到（实测响应为空）；
   适配层头一写就出、体写多少出多少。契约（`compare="short"`）要求两边都没有交付完整的承诺长度。
5. **`Date` 头**。JDK 总加；适配层不加，前置 nginx 在上游没有 `Date` 时自己补。契约两边都去掉再比。
6. **头名大小写、头的顺序、chunk 边界**。JDK 写 `Content-type`，适配层写 `Content-Type`；JDK 的头表有自己的顺序；
   JDK 与适配层的 chunk 切分处不同。契约里小写化、排序、比较解码后的体与「结尾 chunk 是否到达」。
7. **`stream-body` 在适配层是整体读入内存再写一次文件**。JVM 一侧按 8 KiB 边读边写、内存恒定。std/io 目前没有追加写，
   适配层读体时按路由自己的上限（无上限则无）进内存，再 `write_bytes` 一次。handler 看到的 `Request`（`body_file`、空 `body`）
   两边一致；差别只在内存，而一个进程只服务一个请求，付一次。追加写原语（B2）到了就改成按块追加，不改接口。
8. **畸形体的措辞不是 `ErrorFormat` 字段**。`malformed request body` 是两边共用的硬编码英文；给 `ErrorFormat` 加字段会让每一处
   该类型的记录字面量编译失败，下一个 major 再收。

JVM 一侧的行为变化（唯一一处）：读请求体时 JDK 流抛出的异常（chunk 大小不是十六进制、chunk 被截断、体比 `Content-Length` 短）
原来作为 panic 一路上抛，答 500；现在是 400 `malformed request body`，与适配层同一句。这是缺陷修复，不是兼容层：
客户端发的是畸形请求，答 5xx 本来就不对。

### 九.6 日志与 stdout

适配层与共用决定的日志走传入的 `log`：适配层传 stderr，JDK 一侧传 stdout。`middleware.with_logging` 照旧 stdout（JVM 服务器的行为不变），
新增 `with_logging_to_stderr` 给 `serve_exchange` 程序用。`serve_exchange` 不会替应用拦截 `println`：应用自己往 stdout 写字节，
就是往响应里写字节，文档里写明。

### 九.7 实测与门

- `dawnc test packages/web`：80 项（原 61，新增 19 项，覆盖头解析、目标校验、体帧判定、chunked 解码与畸形帧、上限、HEAD、帧决定、响应头、pump 分类）；
  `dawn test packages/web-jvm`：111 项（含它依赖的 web 的 80 项；其中新增一项：JDK 读不了的请求体是 400，内存与 spill 两条路都答 400 且不留临时文件）。
- **契约** `scripts/web-exchange-contract/run.sh <dawnc>`：同一个应用（`contract_app`），同一组 78 个原始请求，JVM 一侧
  （`web_jvm/server`，起一次）与 native 一侧（`dawnc build` 出的二进制，每个夹具起一个进程，请求走 stdin、响应读 stdout）。
  结果 78/78 一致；每个夹具还带着两边必须答的状态码，防两边一起答错。
  夹具覆盖：Content-Length 与 chunked（多块、二进制、空、扩展、trailer、上限内外、路由自己的上限）、畸形 chunked（九种）、超限体
  （声明超限、实读超限、chunked 超限）、HEAD（含流式、204、404）、点段（四种）、守卫（拒绝、不读体就拒、通过、通过后撞上限）、
  `stream-body`（定长、chunked、空、超路由上限）、流式响应（chunked、定长、短于、长于、挂在 204 上）、panic、
  查询多值与路径解码。
- **负控**（`run.sh` 内）：在一份拷贝上把适配层弄坏四次，契约必须在对应夹具上变红。四次都红，且先证明了变异应用得上
  （改写的那行出现且只出现一次，否则脚本失败）：去掉 chunked 解码、HEAD 也写 body、去掉点段检查、守卫不被调用。
- 单进程时延（本机，含起进程与收尾的 stdin 排空，300 次中位数 / p95）：`GET /hello` 1.46 / 1.74 ms，`POST /echo` 60 字节 1.51 / 1.95 ms，
  chunked 60 字节 1.36 / 1.76 ms。这是适配层本身的量级，不含 systemd `Accept=yes` 起实例的成本（runner 实测约占 `/health` p95 的 90%）。
- 墙钟：契约整套（建 JVM jar、建 native、78 夹具、四次负控各建一次 native）本机 41 s。

### 九.8 B2 要补的缺口（本刀没有碰 std，也没有碰编译器）

1. **stdout 写字节**。std 目前只有 `print(String)`，二进制响应无法经 `print` 出去。契约的 native 主程序暂用
   `write_bytes("/dev/stdout", …)`，每次写重开描述符，对驱动给的管道成立、对普通文件与 socket 不成立；`stdio_transport` 因此不进
   `web` 的公开面，等 `io_write_stdout_bytes` 与 flush 落地后再加。
2. **追加写与按区间读**。`stream-body` 的块式 spill 与流式回写要用。
3. **排空**。退出时 stdin 里还有没读的体（早拒绝）会让内核发 RST，客户端可能丢掉已写出的响应。契约的 native 主程序在
   `serve_exchange` 返回后用 `stdin_ready(0)` 排空（runner 的 `drain` 同款）；这是调用方的事，没有放进适配层，因为「排空多少、等多久」
   是传输自己的策略（runner 实测 20 ms 的等待会把 p50 从 1 ms 推到 21 ms）。

### 九.9 给 dawnop-site 的后续改动点（本刀不动那个仓库）

见本刀报告。要点：升钉到含 web 7.1 与 web_jvm 1.1 的 tag；JVM 服务器不变；`[deps.web_jvm]` 已在 B1a 的清单里；
native 服务线（B3）改用 `web/exchange`，主程序在 `serve_exchange` 之后排空 stdin，日志中间件换 `with_logging_to_stderr`。

## 不做的（理由）

- **不加兼容层**（`web/server` 转发模块、`streaming` 的 `InputStream` 重载）：重载要核心 `use java`，
  转发模块要 JVM 与核心同名并存；仓内无调用方，外部只有 dawnop-site，一次升钉解决。
- **不在加载器里加「按后端排除模块」的机制**（manifest 声明后端专属模块、加载器据此跳过）：它只为
  `packages/web` 一个包存在，却要让 `check`、`doc`、`test`、`build` 每条路径都认它，并让「包的文档
  包含哪些模块」依赖当前后端，而拆成两个包不需要任何新机制：包本来就是 Dawn 里「一组一起检查的
  模块」的单位，带 `use java` 的包整包走 JVM，不带的整包走 native，A2 的机器判据已经在按这个分。
- **不留「包内放一个 JVM 模块」的形态**：初稿走过这条路，实测目录目标仍加载它，整包 check/doc 仍红，
  A2 的例外去不掉。
- **不抽后端中立的帧决策**（`body_length` 三态）：B1a 时的取舍，属于 B1b；B1b 已做，即 `web/exchange.framing`（§九.1）。
- **不做吞吐断言与基准**：§三的代价 2 没有测过，这里不写数。
- **不迁移 Playground runner 的 `play/http1.dawn`**：任务单第 4 条，B1b 稳定后另开一刀；
  本刀只改了两处会因本刀变成错话的头注释。
- **不把 `ServerConfig` 搬进核心**：它带 `host`/`port`，单交换适配层没有这两个概念，
  搬进去只会让核心类型里多出一半用不上的字段。
- **不做 keep-alive 与管线化**（B1b）：一请求一进程（裁决第 1 条），每个响应都发 `Connection: close`。keep-alive 要在两个请求之间
  带读缓冲，而「头部一次一字节读到 CRLFCRLF」正是为了不带这个状态；常驻并发是被裁决排除的另一条线。
- **不做 HTTP/2**（B1b）：前置 nginx 对上游讲 HTTP/1.1，没有消费者。
- **不做 TLS**（B1b）：裁决第 5 条，要么前置 nginx 终结，要么走 curl 子进程；适配层读到的永远是明文。
- **不加 `Date` 头**（B1b）：前置 nginx 在上游没有 `Date` 时自己补；加了就要在适配层里装 `Clock` 处理器并把时间格式化成 IMF-fixdate，
  换来的只是契约里多一条要归一化的差异。
- **不给 `ErrorFormat` 加「畸形请求体」字段**（B1b）：会让每处该类型的记录字面量编译失败；两边共用硬编码英文，下一个 major 再收。
- **不抽 `stdio_transport` 进公开面**（B1b）：stdout 写字节的原语没有（§九.8），现在公开的实现只能是 `/dev/stdout` 重开描述符的权宜之计。
- **不把畸形体答成 JDK 原来的 500**（B1b）：客户端发的是畸形请求；改的是 JVM 一侧，让两边都对。
- **不移植 Playground runner 的 `play/http1.dawn`**（B1b）：任务单第 4 条，它是只读参考；适配层稳定、B2 的 stdout 字节落地后另开一刀。
