# `packages/web` 第五个 major（`web5 / 5.0.0`）

> 状态：**current** —— 2026-09-25 主会话裁定候选 A（一个 major 收 W1–W9，进 v0.79.0）后、
> 动码前写成，实现后在 §七回填。调研原文（他语言对照、dawnop-site 调用点计数、两次 JDK 探针）
> 在 `agent-handoff/research-web5-major-20260925.md`（本仓外），结论摘在 §二。

## 一、问题

web4 的公开面还挂着三类「下一个 major」的账：

- **LIB-13 残差**：`dispatch_segs`/`validate_routes`/`route_meta`/`Dispatch` 只被 `server.dawn`
  跨模块消费，web4 时语言只有两档可见性，收不了。`pub(pkg)` 已在 v0.78.0（种子）里。
- **LIB-16 余项**：`Response` 是公开 record，字面量绕过全部构造器；写边界的
  `response_problem` 是它的补丁。
- **没人记过的两条协议违例**（调研 §0.5 的 JDK 21 `jdk.httpserver` 探针，本机实测）：
  1. 状态码完全不校验，JDK 照单全收：99、600、1000、42、-5 全部原样发出；`text(100, …)`
     让客户端只收到 `100 Continue`，然后等一个永远不来的最终响应。
  2. 用户头里的 `Transfer-Encoding` 与 JDK 自己的 `Content-length` 同时发出，违反
     RFC 9112 §6.1；用户设的 `Content-Length` 被 JDK 静默改写（设 5、实发 11 时线上是 11）。
- 零散的：`Stream` 不带长度，干净 EOF 的截断无从发现（LIB-18 连带候选、总纲 §4.1）；
  `ServerHandle` 公开 record 可伪造；`serve_app_bounded` 与 `serve_app_with` 重复且是
  「`0` = 不限」哨兵的唯一文档出处；body 上限的 Int 兼当开关（LIB-17 建议）；
  `validate_routes` 不校验 method，`route_method_of("get", …)` 静默永不命中。

## 二、先例（摘要）

WAI（Haskell）的 `Response` 是抽象类型：构造函数族 `responseLBS`/`responseStream`/…、只读
访问器 `responseStatus`/`responseHeaders`、一个 map 修改器，与 Dawn 的 `opaque` 加 `pub(pkg)`
逐项对得上。受检 header 类型只在「header 容器本身公开可写」的库里出现（Rust `http` 的
`HeaderMap`）；WAI、Plug、http4s、Ktor 都是字符串加单点校验。status 范围 Go
（`checkWriteHeaderCode`）与 http4s（`Status.fromInt`，100..599）在库里拒绝；
Ktor 把 `Transfer-Encoding` 从用户手里拿走（`UnsafeHeaderException`）。出处 URL 见调研 §6。

## 三、方案

| # | 改动 | 形状 |
|---|---|---|
| W1 | 四个 seam 收进包内 | `pub` → `pub(pkg)`；manifest `name = "web5"`、`version = "5.0.0"`，同一提交 |
| W2 | opaque `Response` | `pub(pkg) type ResponseRep` + `pub opaque type Response = ResponseRep`；只读访问器 `response_status`/`response_content_type`/`response_headers`/`response_body`；`pub(pkg) fn response_rep` 给 server 取表示；删 `response_problem` |
| W3 | status 范围 | 每个构造器要求 200..599，越界 panic；`HttpError` 渲染时越界即中立 500 |
| W4 | 帧头归服务器 | `with_header` 拒 `Transfer-Encoding`；`Content-Length` 必须是十进制非负整数，且与已知 body 长度一致（`Empty` body 不比对，HEAD 元数据要用它），一个响应只收一个 |
| W5 | 定长流 | `Stream(value, length: Option[Int])`；`streaming_sized` 发精确 `Content-Length`，泵完比对字节数，短了记一行截断 |
| W6 | opaque `ServerHandle` | 私有 record 加 `pub opaque type`；公开 `handle_port` |
| W7 | 删 `serve_app_bounded` | 入口三合二 |
| W8 | 上限只收正数 | `ServerConfig.max_body` 非正时 `start` panic；`with_body_limit` 非正时构造即 panic；不再有「不限」 |
| W9 | method 是大写 token | `validate_routes` 拒绝非 token 或含小写字母的 method |

### 3.1 判定只在一处

opaque 之后，`Response` 只能经本模块的构造器与 `with_header`/`try_with_header` 产生，
所以校验只在构造处一份：status、`content_type`（`raw`/`binary`/`streaming` 的参数直通
`Content-Type`，web3 3.1.0 时它是唯一不需要字面量就能到达的未校验路径）、每个头。
写边界的 `response_problem` 与「换成中立 500」的 `withheld_response` 一并删掉：
非法响应已不可构造，第二份规则只剩漂移的机会。构造器的拒绝是 panic（程序用自己的值造
响应，造不出来是调用方的 bug），落在 handler 的逐请求隔离里渲染成 500，与 `with_header`
一直以来的结局相同；请求输入派生的头值仍走 `try_with_header` 的 400。

### 3.2 为什么 W3 是 200..599 而不是 RFC 的 100..599

RFC 9110 §15 的有效范围是 100..599，但 1xx 是临时响应，web 不支持 upgrade，也没有发
临时响应的 API，handler 返回的永远是**最终**响应；1xx 作最终响应一律是 bug（探针里
`text(100, …)` 挂死客户端）。一条规则比「100..599 再单独拒 1xx」少一个分支。
`body_length` 里 1xx 那一臂随之不可达，保留作为 RFC 对照的一行，不再有测试喂它 1xx。

### 3.3 W3 不是 §四否决的「受限类型」

`audit/web-api-v2-design.md` §四否决的是 method/status 换**封闭枚举**，理由是封闭枚举必须带
`Other(String)` 逃生口、等于绕回 String。W3、W9 给的是**范围/语法校验**：status 仍是 Int，
method 仍是 String，集合仍开放（任意 2xx..5xx、任意 WebDAV 动词），被拒的只是在 HTTP 里
本来就不合法的值。这正是 §四自己给的替代方案（「String 常量 + 启动时校验」）漏掉的那半。

### 3.4 W5 的截断检测

`transferTo` 返回实际搬运的字节数。定长流由 JDK 的定长输出流收尾：上游多给，JDK 的
`write` 抛出（`TransferFailed`，已有日志）；上游少给（干净 EOF），`transferTo` 正常返回
一个小于声明的数，这就是以前无从分辨的截断，现在记 `Truncated(sent, expected)` 一行日志。
头已发出，status 已花掉，不改 status、不告诉客户端（`streaming-response-design.md` §4.3 的
既有裁决）；客户端靠 `Content-Length` 自己看得出连接提前结束，这是定长相对 chunked 的全部收益。
不定长流（`streaming`）行为不变。

## 四、迁移面

仓内：`playground` 只用 `text`/`raw`/`body_text`/`serve_app`，不读 `Response` 字段，源码不改。
dawnop-site（调研 §0.4，main dc0a8fb）：`webdav.dawn:1551` 一个 test 改用 `response_headers`；
W8 涉及两行（`main.dawn:92` 的 `ServerConfig.max_body` 与 `with_body_limit(2000000, …)`），
若其中有非正值须改成正数，随站点下次升钉一起改；
`[deps.web]` 换 url/hash 与 `version = "5.0.0"`，`use web/...` 25 行不动（别名）。
站内两处自设 `Content-Length` 都在空 body 上（HEAD 的 `with_meta`、OPTIONS），W4 放行。

## 五、门禁

- `emit packages/web`（prev-diff）两条腿编同一份 HEAD 源码，包源码改动两边抵消，预期无字节差，
  不需要 `Emit-Change`。出差即说明同批改了编译器，不许。
- `api-diff.py` 按 manifest `name` 作 unit 键，报「unit removed web4 + unit added web5」，
  不逐符号列收窄；发布说明的符号清单手写。
- doc-check 的 LIB-16 anchor（`present … pub type Response = {`）随 W2 消失，同一提交翻 fixed。

## 六、不做的（理由）

- **受检 `HeaderName`/`HeaderValue`**（主会话裁定不做）：W2 之后 `with_header` 是写入头的
  唯一路径，它已经做名值检查（加 W4 的帧头规则）；受检类型只是同一个不变量的第二种表达，
  站点侧却要改约 20 处。WAI、Plug、http4s、Ktor 同款：字符串加单点校验。
- **`Request`/`HttpError` 做 opaque**：两者是输入与数据，test 要手造 `Request`（`read_headers`
  注释明写手造的必须和线上一样），`HttpError` 的越界由 W3 在渲染时兜住。
- **method/status 封闭枚举**：维持 web-api-v2 §四的否决，理由见 §3.3。
- **写边界纵深防御**：见 §3.1。留着它就是同一条规则两份。
- **`Option[Int]` 的 body 上限**：一个永远有上限的服务器更简单；要「不限」的路由有
  `raw-body`/`stream-body` 两个标签（它们由 nginx 或磁盘兜底），全局不限没有正当用途。
- **拆 4.1.0 先发 W3/W4/W9**：拆开的尾巴会一直等下去（LIB-13 残差挂了一个多月）。

## 七、实现回填

（实现后回填）
