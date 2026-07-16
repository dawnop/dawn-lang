# 流式请求体设计草案（WebDAV PUT 恒定内存）

> 对应 [`m6-retro.md`](m6-retro.md) **§4 无流式请求/响应**。依 [`bytes-design.md`](bytes-design.md)（序 4）、
> [`unwrap-design.md`](unwrap-design.md)（序 5）的先例：**动码前先出草案**。
> 前置：序 4 的一等 `Bytes` 已落地（复盘说「流式依赖序 4 先做更顺」）。

## 一、问题

请求体一次性 `readAllBytes` 进内存（`web/server.dawn:21-25`），WebDAV PUT 大文件整包驻留。
上传链**再拷一份**：

```dawn
multipart(...) = utf8(head) ++ content ++ utf8(tail)   # qiniu_rs.dawn:65 —— 又一份全量拷贝
post_bytes(...) -> BodyPublishers.ofByteArray(body)
```

于是单次 PUT 的瞬时内存 ≈ **3× 文件大小**。这正是上线时被迫
**JVM 堆 256m→512m + nginx `client_max_body_size 64m`** 的原因（`webdav.dawn:8` 的注释自标
"First-version limit"）。GB 级文件做不了。

## 二、地基已就位——**不需要任何新语言特性**（实测 JDK 21 / GraalVM 21）

| API | 实测 | 用途 |
|---|---|---|
| `InputStream.transferTo(OutputStream)` | ✅ 拷贝 9 bytes 成功 | 恒定内存拷贝（内部 8KB 缓冲） |
| `BodyPublishers.ofFile(Path)` | ✅ `contentLength=9` | 从磁盘流式发送，不载入内存 |
| **`BodyPublishers.concat(a, b, c)`**（JDK 16+） | ✅ `contentLength=17`（=4+9+4） | **multipart 框架 + 文件**：`concat(ofByteArray(head), ofFile(tmp), ofByteArray(tail))` |
| `BodyHandlers.ofInputStream()` | ✅ | 响应侧（本轮不用，见第六节） |

`concat` 是关键：它让我们既能保持 qiniu 要求的 multipart 表单格式，又**不必把文件读进内存**，
且 `contentLength` 可算出（qiniu 需要 `Content-Length`）。

## 三、约束：opaque Java 字段**破坏 `derive Show`**（实测）

```
error: cannot derive Show for `WithJava`: field `s` of type Option[InputStream] is not printable
```

且 **`Show` 不是 trait**（编译器里只是 `info.derivesShow` 标志位；v1 预置 trait 只有 `Ord`），
**没有手写 `impl Show[Request]` 的逃生口**。

⇒ `Request`/`Response` **不能持有 `InputStream`**（序 4 才特意让 `Response` 重获 `derive Show`）。

⇒ **设计决定**：框架**边收边写临时文件**，只把**路径 `String`** 交给 handler。
路径是纯数据、Show 完好，而且这恰恰**就是 FastAPI 版的做法**（CLAUDE.md：「不 `await request.body()`
把整包读进内存，而是边收边写临时文件（内存恒定）、再用 `put_file` 从磁盘按块读」）。
对 qiniu 上传而言我们**本来就需要一个文件**（`ofFile` 要 Path），故这不是妥协。

## 四、方案

### 4.1 路由 tag 决定是否流式（复用序 3 的 tag 机制）

序 3 已经把「路由元数据给中间件看」做好了（`RouteMeta.tags`）。新增 tag **`"stream-body"`**：

```dawn
Method("PUT", "/dav/{rest*}", put) |> tagged(["raw-body", "no-cors", "stream-body"])
```

语义区分（两者正交，PUT 两个都要）：
- `raw-body`：**不受** 2MB JSON body 上限约束（既有）。
- `stream-body`：**不把 body 读进内存**，改为落临时文件（新增）。

### 4.2 server 必须**先 dispatch 再读 body**

现状 `handle` 是 `build_request(ex)`（**内含 readAllBytes**）→ `dispatch`。要按 tag 决定读法，
就得倒过来：method/path 来自 URI，不需要 body，故可先 dispatch：

```
uri/method/path  →  dispatch  →  meta(tags)  →  按 tags 读 body  →  handler
```

- 命中 `stream-body`：`getRequestBody()` 的 InputStream **`transferTo`** 临时文件 →
  `body_file: Some(path)`；`body = ""`、`raw = 空 Bytes`（该类 handler 不看这两个）。
- 否则：维持原样（`readAllBytes` → `body`/`raw`），零行为变化。

### 4.3 `Request` 新增字段（纯数据）

```dawn
# 流式路由（tag "stream-body"）的请求体落地路径；其余路由为 None。
# 框架负责创建与删除，handler 只管读。
body_file: Option[String],
```

### 4.4 临时文件生命周期（Dawn 无 try/finally）

沿用 `with_tx` 的既有惯用法——用 `catch_panic` 当 finally：

```dawn
fn with_body_file(path, f) = {
  let out = catch_panic(fn() => f())   # 捕获后返回，不会穿过我们
  delete_file(path)                    # 故这一行必然执行（含 handler panic）
  ...
}
```

### 4.5 上传侧：`upload_file(path)`

```dawn
concat(ofByteArray(utf8(head)), ofFile(path), ofByteArray(utf8(tail)))
```
`qiniu_rs.upload_file` + `http.post_publisher`，与既有 `upload_bytes`（小内容/文本仍用它）并存。

### 4.6 收益

单次 PUT 瞬时内存从 **≈3× 文件大小** 降到 **恒定（~8KB 缓冲 + 磁盘）**。
上线后可回退当初的两个补丁：**堆 512m→256m**、**nginx `client_max_body_size` 抬高/取消**。

## 五、落地点

1. `web/types.dawn`：`Request` 加 `body_file: Option[String]`（Show 完好）。
2. `web/server.dawn`：`handle` 改为先 dispatch；`read_body` 按 tag 分叉；临时文件建/删。
3. `http.dawn`：`post_publisher(url, headers, publisher)`（`post_bytes` 复用它）。
4. `qiniu_rs.dawn`：`upload_file(..., path)` 用 `concat + ofFile`。
5. `webdav.dawn`：`put` 走 `body_file`；路由加 `stream-body` tag；更新头部注释（删 "first-version limit"）。
6. 测试：字节精确往返（含 >1 个 8KB 缓冲的多块文件）+ 恒定内存证据（大文件 PUT 不炸小堆）。
7. `docs/spec.md`：`transferTo`/`concat` 属互操作既有能力，无 spec 变更；框架 tag 语义记在 backend README。

## 六、不做（记录理由）

- **响应流式（GET 代理）**：需要 `Response` 持有流 → 撞第三节的 Show 约束，是**独立的设计题**
  （要么给语言加一等 `Stream` 类型如序 4 的 `Bytes`，要么让 Response 携 `proxy: {url,headers}` 由
  server 取——后者把通用框架耦合到 HTTP 客户端）。且现状已被两层缓解：**会跟随 302 的客户端
  直连七牛**（根本不经后端）、**Range 透传**让分段读只取该段。留作下一轮。
- **`/api/fm/upload`（multipart 代理上传）**：请求体本身是 multipart，流式化需要**流式 multipart
  解析器**（现为 over Bytes 的整包解析），是另一件事。且前端主流程走**直传七牛**，此端点是备用。
- **`ofFile` 的分片续传**：qiniu 单请求表单上传够用（大文件走网页直传）；分片 v2 是另一个话题。
