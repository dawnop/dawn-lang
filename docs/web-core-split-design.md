# `packages/web` 第七个 major：JDK server 拆成独立包（`web7 / 7.0.0` 与 `web_jvm / 1.0.0`）

> 状态：**current** —— 2026-10-20，native B1a。依据：「完全 native 化」裁决第 4 条与调研 §1(B)、
> Q4（均在本仓外的 agent-handoff）。本篇写成于动码前，实现后回填了 §八的实测。
> 下一刀（B1b，单交换适配层）不在本篇范围，只在 §七留接口。
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

## 不做的（理由）

- **不加兼容层**（`web/server` 转发模块、`streaming` 的 `InputStream` 重载）：重载要核心 `use java`，
  转发模块要 JVM 与核心同名并存；仓内无调用方，外部只有 dawnop-site，一次升钉解决。
- **不在加载器里加「按后端排除模块」的机制**（manifest 声明后端专属模块、加载器据此跳过）：它只为
  `packages/web` 一个包存在，却要让 `check`、`doc`、`test`、`build` 每条路径都认它，并让「包的文档
  包含哪些模块」依赖当前后端，而拆成两个包不需要任何新机制：包本来就是 Dawn 里「一组一起检查的
  模块」的单位，带 `use java` 的包整包走 JVM，不带的整包走 native，A2 的机器判据已经在按这个分。
- **不留「包内放一个 JVM 模块」的形态**：初稿走过这条路，实测目录目标仍加载它，整包 check/doc 仍红，
  A2 的例外去不掉。
- **不抽后端中立的帧决策**（`body_length` 三态）：属于 B1b，那时有第二个使用者才知道形状对不对。
- **不做吞吐断言与基准**：§三的代价 2 没有测过，这里不写数。
- **不迁移 Playground runner 的 `play/http1.dawn`**：任务单第 4 条，B1b 稳定后另开一刀；
  本刀只改了两处会因本刀变成错话的头注释。
- **不把 `ServerConfig` 搬进核心**：它带 `host`/`port`，单交换适配层没有这两个概念，
  搬进去只会让核心类型里多出一半用不上的字段。
