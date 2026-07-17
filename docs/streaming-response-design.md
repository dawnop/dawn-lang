# 流式响应设计草案（GET 代理下载恒定内存）

> 对应 [`m6-retro.md`](m6-retro.md) **§4 无流式请求/响应**的后半，以及
> [`streaming-design.md`](streaming-design.md) **§六**留的尾巴（「响应流式……留作下一轮」）。
> 依 [`bytes-design.md`](bytes-design.md)、[`unwrap-design.md`](unwrap-design.md)、
> [`varargs-design.md`](varargs-design.md) 的先例：**动码前先出草案**。
> 前置全部就位：序 4 一等 `Bytes`、序 3 路由 tag、请求侧流式均已落地。

## 一、问题

GET 代理下载把整个对象一次性读进内存再发出。两条路径都这样：

```dawn
# api_fm.dawn  content 代理
fetch_bytes(url, []) -> Ok(r) -> binary(200, ct, r.bytes)      # r.bytes = 整个对象
# webdav.dawn  serve_file 代理（含 206 分段）
fetch_bytes(range_url, hdrs) -> binary(206, mime, r.bytes)
```

`fetch_bytes` 用 `BodyHandlers.ofByteArray()`（`http.dawn:36`）——**上游整包 buffer 成 `byte[]`**；
`write_response` 再 `out.write(bytes)` 整块写出（`web/server.dawn:37-41`）。于是单次下载的瞬时内存
≈ **1× 对象大小**，4G 内存的机器上一个大媒体文件就能顶爆。

**为什么现在还没炸**：两层缓解压着（[`streaming-design.md`](streaming-design.md) §六）——
**会跟随 302 的客户端**（rclone/cyberduck/mountain duck/raidrive）直连七牛、**根本不经后端**；
只有 **macOS webdavfs、Windows mini-redirector** 这类跨域 302 不可靠的客户端才走代理。
外加 **Range 透传**让分段读每次只取一段。所以本轮是把最后这条内存路径也堵上，**影响面窄**
（仅上述不跟随 302 的客户端 + fm `content` 兜底端点）。

## 二、地基几乎就位——语言侧靠**通用 `cast[T]`** 认领擦除泛型

请求侧那轮已经把响应侧要用的 Java API 一并实测过了
（[`streaming-design.md`](streaming-design.md) §二表格），响应侧要用的两个当时就标了「本轮不用」：

| API | 实测出处 | 响应侧用途 |
|---|---|---|
| `BodyHandlers.ofInputStream()` | streaming-design.md §二 ✅ | 上游响应体作流拿回，**不 buffer 进内存** |
| `InputStream.transferTo(OutputStream)` | 同上 ✅（8KB 缓冲，请求侧 `server.dawn:142` 已在用） | 上游流 → socket，恒定内存 |

`ofInputStream` 还有一个 `ofByteArray` 没有的好处：**可以先读 `statusCode()` 再碰 body**。
故「先判上游状态、非 2xx 就报错、不流」这套现有逻辑原样保留，甚至比现在更顺
（现在是先把错误体也 buffer 下来再判）。

**语言缺口 = 擦除泛型的认领，由通用 `cast[T]` 一并解决**：`HttpResponse.body()` 是**擦除泛型**，
Dawn 视之为 `java.lang.Object`（这正是 `fetch_bytes` 用 `as_bytes` 把它认领成 `Bytes` 的原因，
`http.dawn:27`）。`ofInputStream` 的 body 同样擦除成 `Object`，认领成 `InputStream` 就用同一把工具——
**单个泛型内建 `cast[T]`**（设计见 [`cast-interop.md`](cast-interop.md)）：

```dawn
let s: InputStream = cast[InputStream](resp.body()!)   # 认领擦除泛型 body 为具体流
let b = cast[Bytes](resp.body()!)                      # as_bytes 的位置，同一把工具
```

> **修正一处早先的错判**：本草案初稿曾说「泛型认领做不到，T 运行期被擦、发不出 `CHECKCAST`」，
> 于是要补一个**与 `as_bytes` 逐行同构的**单态内建 `as_input_stream`。这个推理**错了**：擦除只挡得住
> 「T 是外层函数自己的类型参数」的 cast；而 `cast[InputStream](...)` 里 T 在**调用点被字面实例化成
> 具体类**，编译器当场就能发 `CHECKCAST java/io/InputStream`——`as_bytes` 能 work 正是同理。故不必
> 一类型一内建，`cast[T]` 一个就够，且它**顺带消灭整个 `as_XXX` 家族**（见 [`builtins-to-stdlib.md`](builtins-to-stdlib.md)）。

**设计沿革**（记录，免得后人重走）：`as_input_stream` 单态内建（初稿）→ 因「每开一个洞都改编译器」
被否 → 一版 `URLConnection.getInputStream()`（返回具体 `InputStream`、零编译器改动）作**过渡**验证了
特性可行 → **终稿取 `cast[T]`**：让现代 `HttpClient` 路径与 `fetch_bytes` 保持一致，且不再按类型累积内建。

**跨仓代价**：`cast[T]` 落地 dawn-lang 后发一个新 tag，dawnop-site 再 bump `.dawn-version`
（开发期走逃生阀 `echo main > .dawn-version`）。`cast[T]` 不是为本特性一次性加的——它是 `as_bytes`
的泛化、服务所有 interop 认领点，本特性只是它的**头号使用者**。

## 三、真正的设计题：`Response` 怎么持有这条流

请求侧靠**落临时文件、只把路径 `String` 交给 handler** 绕过了 Show 约束
（[`streaming-design.md`](streaming-design.md) §三/§四）——因为上传本来就需要磁盘上的文件
（`ofFile` 要 Path），落盘不是妥协。**响应侧不同**：我们要的是**边收边回**（上游流直接泵向 socket，
首字节立刻出、全程恒定内存），先落盘再泵会白搭一次全量磁盘往返 + 首字节延迟，把「流式」做成了「缓存」。
所以响应侧**得让 `Response` 真的持有那条流**。

而 `Response derive Show`（`web/types.dawn:52`），opaque 的 `InputStream` 字段**不可 Show**
（请求侧实测：`field s of type Option[InputStream] is not printable`），`Show` 又**不是可手写 impl 的 trait**
（编译器里只是 `derivesShow` 标志位，v1 预置 trait 只有 `Ord`）。三条出路：

- **方案 A（本草案推荐）——`Response` 去掉 `derive Show`，直接持 `Option[InputStream]`。**
- 方案 B——`Response` 携 `proxy: Option[{url, headers}]` 纯数据，由 server 层去取并泵（Show 保住）。
- 方案 C——给语言加一等 `Stream` 类型（像序 4 的 `Bytes`），`Response` 持它。

### 为什么是 A：那个 `derive Show` 实测**无人消费**

序 4 曾「特意让 `Response` 重获 `derive Show`」（streaming-design.md §三），本草案**核对了它到底有没有人用**：

- 全仓无任何地方对 `Response` 调 `show`/`to_string`/字符串插值（`grep` 净空）；
- `Response` 未作字段嵌进任何别的类型（不存在「靠它才能 derive」的下游）；
- 唯一碰 `Response` 的测试（`web/types.dawn:219`）只读 `.headers`/`.status`，是字段访问，与 Show 无关。

即 `Response` 的 `Show` 是**反射式保留、零消费**。去掉它编译与测试都不受影响。原则上「线类型皆可打印」
这条只对 `Request` 与文本/JSON/二进制 `Response` 继续成立（构造方式不变）；**唯独流式 `Response` 退出**
——而一条活的 socket 流本就没有可 `show` 的内容，退出是**恰当**而非退步。
（注：`Bytes` 在 Show 下是**有界摘要**（CodeGen `Bytes renders as a summary`），故序 4 的保留当时是有意义的；
只是没人真去 show 它。）

### 为什么不是 B / C

- **B（proxy 描述符）** 保住了 Show，代价更大：① 把**通用 web 框架**（`web/server`）耦合到 HTTP 客户端
  （`http.dawn`）——框架本意是应用无关的；② **控制反转**——handler 从「产出字节」退化成「产出配方」，
  于是上游错误（七牛 404 / 错误 JSON 冒充 200，正是 `http.dawn:19-22` 记的那个 bug）在 handler 返回 `Ok` **之后**
  才在 server 层暴露，现有那句精确的 `Err(http_error(502, "qiniu ${status}"))` 映射**没地方放了**，只能在 server 里泛化处理。
- **C（一等 `Stream`）** 是最大的锤子，为两个端点改语言、加 spec，不划算。序 4 给 `Bytes` 立一等是因为
  二进制体到处都是；流式只此两处，且 A 已足够。

方案 A 把 handler 依旧当作**唯一取字节、判状态、映错误**的地方——正是现有代码的形状，改动最小。

## 四、方案（A）

### 4.1 `http.dawn`：新增 `fetch_stream`

`StreamResp` **只带 status + stream**——上游 Content-Range/mime handler 全都本地自算
（`serve_file` 从可信的 `o.size` 拼 `Content-Range`、从 `o.content_type` 定 mime），无需从上游透传。

```dawn
pub type StreamResp = { status: Int, stream: InputStream }

pub fn fetch_stream(url, headers) -> Result[StreamResp, String] !io =
  java_try(fn() => {
    ... let resp = shared_client().send(req, BodyHandlers.ofInputStream()!)!
    # statusCode() 先读（判 2xx/206）；body() 是擦除 Object，cast[InputStream] 认领成流，尚未消费
    StreamResp { status: resp.statusCode(), stream: cast[InputStream](resp.body()!) }
  })
```

与 `fetch_bytes` **并存**（小对象/需要就地看字节的仍用 `ofByteArray`）。

**206-vs-200 改看上游状态**：现有 `serve_file` 靠 `byte_len(r.bytes) == end-start+1` 判分段是否命中——
流式下拿不到长度（不物化）。改为**看上游 `status == 206`**：七牛荣誉 Range 即回 206，忽略即回 200。
这既流式兼容、又更直接（我们已用 `range_of` 对可信的 `o.size` 校验过区间，故本地拼的 `Content-Range` 正确）。

### 4.2 `web/types.dawn`：`Response` 加流字段，去 `derive Show`

```dawn
pub type Response = {
  status: Int, content_type: String,
  headers: List[(String, String)],
  body: String,
  bin: Option[Bytes],
  stream: Option[InputStream],   # 新增：边收边回；Some 时忽略 body/bin
}   # ← 删掉 derive Show（§三：实测无人消费）

# 流式响应构造器。v1 只走 chunked（sendResponseHeaders(status, 0)），与现二进制路径的线行为一致。
pub fn streaming(status, content_type, stream) -> Response = ...
```

既有构造器（`text/json_response/raw/binary/redirect/attachment`）全部补 `stream: None`，行为零变化。
`with_header` 用 `{..r}` 展开、**自动保留 `stream`**；需核对中间件里没有**逐字段重建** `Response` 的地方
（有则会丢掉新字段）。

### 4.3 `web/server.dawn`：`write_response` 加流分支

**v1 只 chunked**：现二进制路径本就 `sendResponseHeaders(status, 0)`（chunked、无 Content-Length），
现有代理客户端（含 206 + `Content-Range` 无 Content-Length 的分段）已在此路径上正常工作，故流式沿用 0，
**线行为与今天逐字节一致，只是内存恒定**。透传上游 `Content-Length` 给客户端 seek/进度是后续精修（§六）。

```dawn
match r.stream {
  Some(s) -> {
    ex.sendResponseHeaders(r.status, 0)   # chunked
    let out = ex.getResponseBody()!
    # transferTo 可能因客户端中途断开而抛；catch 住，好让上游流照常 close（否则 HttpClient 连接泄漏）
    let _ = catch_panic(fn() => { let _n = s.transferTo(out); () })
    close_stream(s)   # java_try 包住 close，其失败非致命、也不得跳过 out/ex 的关闭
    out.close(); ex.close()
  }
  None -> ... # 现有 bin/body 两路不动（仍在各自分支里 sendResponseHeaders(status, 0)）
}
```

- **生命周期**：`ofInputStream` 的 body **必须读到 EOF 或 close**，否则 HttpClient 连接泄漏。
  `transferTo` 读到 EOF，随后 `close`；`catch_panic` 当 finally（streaming-design.md §4.4 同款）兜住客户端中途断开。
  handler 因上游非 2xx 走 `Err` 分支时，那条流也要 close（在 `fetch_stream` 里判完 status 若不 ok 即 close，不返给 handler）。
- **Range/206 不变**：webdav 把 Range 发给七牛、拿 206 回来；改后 `fetch_stream` 带 Range → 上游 206 →
  handler 置 status 206、本地拼的 `Content-Range` 落进 `headers`。分段读只取该段，内存与全量下载同为恒定。
- **流中途断**：headers 一旦发出（chunked），上游中断已无法改 status，只能断连接——可接受。

### 4.4 两个 handler 改造（形状不变）

`api_fm.content` 与 `webdav.serve_file`：把 `fetch_bytes + binary` 换成 `fetch_stream + streaming`，
**保留** `ok_status` 判断与 `Err(http_error(...))` 映射（handler 仍是取字节+判状态+映错误的唯一处）。

### 4.5 收益

单次代理下载瞬时内存从 **≈1× 对象大小** 降到 **恒定（~8KB `transferTo` 缓冲）**，且**边收边回**
（首字节不再等全量下载）。可回退当初为大文件抬的 JVM 堆 / nginx 限额（若 PUT 侧未先回退）。
**恒定内存证据**留作实现期测试（大对象经代理下载不炸小堆），量化数字实测后回填——同请求侧 §五.6。

## 五、落地点

0. **dawn-lang**（前置）：落地泛型内建 `cast[T]`（`as_bytes` 的泛化，设计见 [`cast-interop.md`](cast-interop.md)：
   Types.kt/CodeGen.kt/Doc.kt + 测试）；spec §9.5 补一句；发 tag。dawnop-site bump `.dawn-version`。
   —— 这一步**不专为本特性**，服务所有 interop 认领点、消灭 `as_XXX` 家族。
1. `http.dawn`：`fetch_stream(url, headers) -> Result[StreamResp, String]`（`ofInputStream`，
   body 用 `cast[InputStream]` 认领；`StreamResp = { status, stream }`，Content-Range 由 handler 自算故不带）。
2. `web/types.dawn`：`Response` 加 `stream: Option[InputStream]`、**去 `derive Show`**、加 `streaming(...)` 构造器、既有构造器补 `stream: None`。
3. `web/server.dawn`：`write_response` 加流分支（chunked + `catch_panic` 当 finally 关闭上游流）。
4. `api_fm.dawn` / `webdav.dawn`：`content`、`serve_file` 改 `fetch_stream + streaming`，保留状态判断与错误映射。
5. 中间件核对：确认无逐字段重建 `Response`（都走 `{..r}` 展开）。
6. 测试：字节精确往返（含 >8KB 多块）、206 分段字节与 `Content-Range` 正确、上游非 2xx 走 `Err` 不流、恒定内存证据。
7. `docs/spec.md`：§9.5 把 `as_bytes` 记为 `cast[Bytes]` 的便捷别名、补 `cast[T]`（互操作认领）；`Response` 去 Show 记进 backend README。
8. 回填 [`m7-progress.md`](m7-progress.md)：把「响应流式」从「不进本轮」移入已完成，记提交哈希。

## 六、不做（记录理由）

- **先落盘再泵**（镜像请求侧的 `body_file`）：能保住 `derive Show`、零框架改动，但**不是边收边回**——
  白搭一次全量磁盘往返 + 首字节延迟，把流式做成缓存。响应侧的价值恰在并发管道，故不取；仅作 A 若受阻时的兜底。
- **定长响应（透传上游 `Content-Length`）**：v1 走 chunked（与今天二进制路径一致）已够；把上游长度回给客户端
  让其 seek/显进度是纯精修，`StreamResp` 加一个 `content_length` 字段 + `write_response` 改 `sendResponseHeaders(status, len)` 即可，本轮不做。
- **`/api/fm/upload`（multipart 代理上传）**：请求体是 multipart，流式化需流式 multipart 解析器，是另一件事；
  且前端主流程走直传七牛，此端点是备用（同 streaming-design.md §六）。
- **多段 Range（multipart/byteranges）**：七牛 + 上述客户端单段足够，多段是另一个话题。
