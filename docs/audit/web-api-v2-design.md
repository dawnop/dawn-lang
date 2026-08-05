# `packages/web` v2：把非法状态变成不可表示

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **WEB-03（P1）**、**WEB-04（P2）**、**WEB-06（P2）**、
> **WEB-07（P2）**、**WEB-09（P2）**、**WEB-10（P2）**。
> （WEB-01/02/05/08 的安全与协议 bug 已于 2026-07-25 落地。）
> 状态：**已落地（2026-08-05，步 1–6 全部）**。步 0（WEB-09 不破坏半）先行于
> 2026-07-30（`6a2b8f9`）；步 1–6 分三批落在 web-v2 分支：ResponseBody + 按种类定长
> + HEAD、raw path 路由 + dot segment 400 + 多值 header、ServerHandle 生命周期。
> 实现与本文的偏离都记在代码注释里，两处值得点名：**包名随 major 换成 `web2`**
> （包管理器的 v2 换名规则强制，消费者靠别名保住 `use web/...` 拼写）；
> `ServerHandle` 多带一个 `done: CountDownLatch`（jdk.httpserver 有 stop 没 join，
> 没有 latch 就没有 join 可阻塞的东西）。
> **这是一次破坏性 API 变更，按 CONTRIBUTING §六先发 tag。**
> 与 [`../native-backend-plan.md`](../native-backend-plan.md) 不重合——那份的 §7
> 明确把 `packages/web` 划到 native 范围外（web 需要 C 写的 HTTP 栈 + socket 层）。
> 台账见 [native-plan-overlap.md](native-plan-overlap.md)。

## 一、问题

2026-07-25 修掉的是**会出事的**那些（body limit 位置、URL 解码、CORS、header 注入）。
剩下的是**形状不对**的那些——它们不会今天出事，但它们让每个使用者都有机会出事。

### 1.1 `Response` 用三个字段表达一个 sum（WEB-06）

```dawn
pub type Response = {
  status: Int,
  content_type: String,
  headers: List[(String, String)],
  body: String,
  bin: Option[Bytes],
  stream: Option[InputStream],      # Some => body/bin 被忽略
}
```

「`stream` 是 Some 就忽略其余」是**注释里的规矩**，类型上任何调用者都能构造
`Response { body: "hi", bin: Some(...), stream: Some(...) }`。
`write_response` 里那串嵌套 match 就是在运行期重新发现这条规矩。

### 1.2 全部响应 chunked（WEB-07）

```dawn
ex.sendResponseHeaders(r.status, 0)   # 0 = chunked
```

小响应拿不到 `Content-Length`；204/304 和 HEAD 请求也会走 body 路径。
这两件事的正解都在 WEB-06——**body 的种类应该决定长度和是否允许 body**。

### 1.3 路由用解码后的 path（WEB-03）

`build_request` 与 dispatch 都用 `URI.getPath()`（已解码）。
若 `%2F` 被解码成 `/`，**客户端数据就改变了路由段边界**：

```
GET /files/a%2Fb        →  getPath() = /files/a/b
                            路由 /files/{name} 匹配失败，或匹配到别的段数
```

这影响授权判断（「这个用户能访问 `/files/{name}` 吗」问的是哪个 name）
和 WebDAV 路径。

### 1.4 请求 header 被压成单值（WEB-04）

```dawn
# server.dawn
let v = headers.getFirst(name)!      # 只取第一个
```

`Cookie`、`Forwarded`、`Accept`、重复自定义 header 的语义全丢。

### 1.5 路由与错误 stringly typed（WEB-09）

method、route pattern、tag 都是任意 `String`。没有启动时的 pattern 校验、
没有重复 capture 检查、没有 route shadow 检测，first-match wins ——
一条宽 route 会**静默**遮住后面的。`HttpError` 只有 status/message。

### 1.6 server 生命周期不可组合（WEB-10）

```dawn
pub fn serve_app_bounded(port, max_body, routes, middleware) -> Unit !io = {
  let addr = InetSocketAddress.new("127.0.0.1", port)   # 写死
  ...
  let latch = CountDownLatch.new(1)
  latch.await()                                          # 永不返回
}
```

不返回 handle → 不能优雅停止、不能选地址、不能注入 executor、
不能测生命周期、不能做 readiness 探针。

## 二、方案

一次发布，改五处 API。分开发会让使用者迁移两三遍。

### 2.1 `ResponseBody` 求和类型（WEB-06 + WEB-07）

```dawn
pub type ResponseBody =
  | Empty
  | Text(value: String)
  | Binary(value: Bytes)
  | Stream(value: InputStream)

pub type Response = {
  status: Int,
  content_type: String,
  headers: List[(String, String)],
  body: ResponseBody,
}
```

`write_response` 因此能对每种 body 做对的事：

| body | Content-Length | 说明 |
|---|---|---|
| `Empty` | `-1`（jdk.httpserver 的「无 body」） | 204/304 自然落这里 |
| `Text(s)` | UTF-8 编码后的字节数 | 小响应终于有长度了 |
| `Binary(b)` | `bytes.len(b)` | |
| `Stream(s)` | `0`（chunked） | 长度未知，这才是 chunked 该用的地方 |

**HEAD**：dispatch 时把 HEAD 当 GET 匹配，写响应时发 header、不发 body。
这是 RFC 9110 §9.3.2 的要求，今天完全没实现。

现有构造函数（`text`/`json_response`/`binary`/`streaming`/`raw`）签名不变，
只是内部构造 `ResponseBody` —— **大部分调用点因此不用改**。
要改的是直接写 `Response { .. }` 字面量和读 `r.body`/`r.bin`/`r.stream` 的地方。

### 2.2 raw path + 显式逐段 decode（WEB-03）

`Request` 加一个字段，而不是换掉旧的：

```dawn
pub type Request = {
  ...
  path: String,        # 解码后的，保留——日志和展示要它
  raw_path: String,    # 新增：URI.getRawPath()
  ...
}
```

`dispatch` 改用 `raw_path`：按 `/` 切分**未解码**的段，
然后对每一段单独 percent-decode 填进 `params`。于是 `%2F` 留在段内，
不产生新的段边界。

同时定义三条今天没定义的策略（写进 `packages/web` 的 README）：

| 情况 | 处置 |
|---|---|
| 重复 slash（`/a//b`） | 保留空段，不合并——合并是路径改写，属应用的事 |
| dot segment（`/a/../b`） | **拒绝**，400。路由前做路径规范化是一类经典漏洞的来源 |
| trailing slash（`/a/`） | 沿用今天的行为（router 已容忍），文档写明 |

### 2.3 `headers` 变多值（WEB-04）

```dawn
headers: Map[String, List[String]],

pub fn header(req: Request, name: String) -> Option[String]        # 第一个，签名不变
pub fn headers_all(req: Request, name: String) -> List[String]     # 新增
```

`header` 的签名和语义都不变 → **绝大多数调用点不用改**。
只有直接读 `req.headers` 这个 Map 的地方要改。

### 2.4 RouteTable 启动时校验（WEB-09 的一半）

**这一半不破坏 API**，可以先做、单独发：

`serve_app` 在 `server.start()` 之前跑一遍：

- pattern 语法合法（`{name}` 闭合、名字是合法标识符）；
- 同一条 route 内没有重复 capture 名；
- 没有 route 被前面的 route 完全遮住（shadow 检测）。

任一条不过 → panic，消息指出是哪两条 route、哪个段。
**启动时炸**好过运行期静默 404。

`HttpError` 加 `code: Option[String]` 与 `headers: List[(String, String)]`
（401 要能带 `WWW-Authenticate`），method/status 的受限类型**不做**——见 §四。

### 2.5 `ServerHandle`（WEB-10）

```dawn
pub type ServerConfig = {
  host: String,          # 默认 "127.0.0.1"
  port: Int,
  max_body: Int,
}

pub type ServerHandle = { server: HttpServer, port: Int }

pub fn start(cfg: ServerConfig, routes: List[Route], mw: List[Middleware]) -> ServerHandle !io
pub fn join(h: ServerHandle) -> Unit !io      # 阻塞到 stop
pub fn stop(h: ServerHandle, grace_secs: Int) -> Unit !io

## The old shape, kept: start + join. Most programs want exactly this.
pub fn serve_app(port: Int, routes: List[Route], mw: List[Middleware]) -> Unit !io
```

`port: 0` → 让 OS 选，`ServerHandle.port` 报告真实端口。
这一条单独就能让 `packages/web` 的测试不用再硬编码端口
（`playground/test/contract.sh` 里那段 WSL2/WinNAT 端口注释就是这个问题的产物）。

## 三、为什么不顺手把 X 也改了

- **不改 middleware 的形状**。`fn(Handler) -> Handler` 很好，没人抱怨过。
- **不引入路由 DSL / 宏**。`route_get("/a/{id}", h)` 这个形状留着；
  改的是它启动时会不会被检查。
- **不做 HTTP/2 或 TLS**。`server.dawn` 的文件头明说 nginx 在前面终止 TLS，
  这个分工不变。

## 四、不做的（记录理由）

- **method/status 换成受限类型**（WEB-09 的另一半）。
  `type Method = GET | POST | ...` 看起来更严，实际会在两处硌人：
  WebDAV 用的是 `PROPFIND`/`MKCOL`/`COPY`/`MOVE`（`route_method` 今天接任意 verb，
  dawnop-site 在用），而 status 是三位数字的开放集合。
  给它们封闭类型就得同时给一个 `Other(String)` 逃生口——那等于回到 String，
  只是多了一层包装。**改成 String 常量 + 启动时校验**（§2.4）拿到的是同样的收益。
- **把 `body: String` 做成惰性解码**（WEB-01 的剩余项）。
  同时保留 byte[] 和 String 确实是双份峰值，但 8 MiB 的服务器上限已经把它限住了；
  改成惰性要么让 `Request` 带一个可变槽（与不可变记录冲突），
  要么让 `body` 变成函数（每个 handler 都要改）。收益不值。
- **保留 `bin`/`stream` 字段作为兼容层**。留着它们，非法状态就还能构造，
  这次改动的全部意义就没了。
- **一次只改一个**。五处 API 分五次发，使用者要迁移五遍、读五份 release note。
  一次改完是对使用者更客气的选择，即使 diff 更大。

## 五、迁移

`packages/web` 的版本从 `1.0.0` 到 `2.0.0`。仓库内使用者只有 `playground`。
仓库外是 dawnop-site——按 CONTRIBUTING §六：

1. 这边先发 tag；
2. 那边提一个 bump `.dawn-version` 的提交，同时改 web API 调用；
3. 过渡期那边可以短暂写 `main` 现编，**别长期留着**。

迁移清单（写进 release note）：

| 改动 | 影响 |
|---|---|
| `Response.body` 变 `ResponseBody` | 直接写 `Response { .. }` 字面量、读 `r.bin`/`r.stream` 的地方 |
| `Request.headers` 变多值 | 直接读 `req.headers` 的地方；用 `header()` 的不受影响 |
| `Request` 加 `raw_path` | 只增不减，构造 Request 的地方（测试）要补字段 |
| `HttpError` 加两个字段 | 用 `http_error()` 的不受影响；写字面量的要补 |
| dot segment 拒绝 | 行为变化：原本能过的 `/a/../b` 现在 400 |
| RouteTable 启动校验 | 行为变化：有 shadow 的路由表现在启动即失败 |

## 六、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| 0 | `packages/web/src/router.dawn`：RouteTable 校验（**不破坏 API，可先发**） | shadow / 重复 capture / 坏 pattern 各一条 |
| 1 | `types.dawn`：`ResponseBody`、`Response`、`HttpError` | 构造函数行为不变的 test |
| 2 | `server.dawn`：`write_response` 按 body 定长度；HEAD | Content-Length 正确、204 无 body、HEAD 只发头 |
| 3 | `server.dawn` + `router.dawn`：`raw_path` + 逐段 decode + dot segment 400 | `%2F` 不产生新段；`/a/../b` → 400 |
| 4 | `server.dawn` + `types.dawn`：多值 header | `Cookie` 两条都在 |
| 5 | `server.dawn`：`ServerConfig`/`ServerHandle`/`start`/`join`/`stop` | 起停一轮、`port: 0` 拿到真实端口 |
| 6 | `playground/src/main.dawn` 跟随 | contract 10/10 |
