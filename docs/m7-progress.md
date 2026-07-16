# M7 进展：执行 M6 复盘的修复优先级（序 1–4）

> 背景：[`m6-retro.md`](m6-retro.md) 第六节排了一张修复优先级表。第一批 = 序 1 + 序 2 + 序 3
> （互相独立、不破坏现有测试、低风险，且为序 4「一等 Bytes」争取设计时间），随后**序 4 也一并落地**。
> 本文件记录落地状态，供中断后接续。工作跨两仓：语言本体 `dawn-lang/`，后端 `dawnop-site/backend-dawn/`。

## 状态总览

| 序 | 修复项 | 层 | 状态 | 提交 |
|---|---|---|---|---|
| 1 | 补齐 `find/take/drop/reverse` + 字符串 `index_of/last_index_of` | 库 | ✅ 完成 | dawn-lang `1784358`、backend `82664a8` |
| 2 | SQL 命名列取值 `row.col_int("x")` | 库 | ✅ 完成 | backend `862c79c` |
| 3 | Route 开放结构 + 中间件路由感知 | 框架 | ✅ 完成 | backend `3cfe1b4` |
| 4 | 一等 `Bytes` 类型（根因 1） | 语言+库+框架 | ✅ 完成 | 草案 `c42f88c`、lang `fe128b3`、backend `f9c339e` |
| 5 | 互操作 Option 解包：后缀 `!`（根因 3） | 语言+框架 | ✅ 完成 | 草案 `05071e3`、lang `a44e461`、backend `f1b869e` |

第一批（序 1/2/3）+ 序 4 + 序 5 均完成。序 4/5 虽在优先级表里列「第二批」（成本高、需设计草案），
均已做掉。**剩余**：序 6（`Int`/`char` 值类型特化，根因 2）+ 流式请求/响应。

---

## 序 1 — 补齐常见标准库函数（✅）

**语言侧**（`dawn-lang`，提交 `1784358`）：新增六个内建。

- List：`find(xs, pred)->Option[T]`、`take/drop(xs, n)`（越界自动 clamp，不 panic）、
  `reverse(xs)`（返回副本，不改原列表）。
- String：`index_of/last_index_of(s, sub)->Option[Int]`，返回**码点**下标（与 `substring`/
  `code_points` 一致，非 UTF-16），未命中 `None`。

四处同步改动：`Types.kt` 签名、`CodeGen.kt` 运行期方法（`Lists`/`Strings` 类）+ 调用点派发 +
一等函数值 handle、`Comptime.kt` 常量折叠、`Doc.kt` 分组（`DocCmdTest` 要求每个内建都归组）。
新增 golden 用例（含 astral 字符 `\u{1f600}` 验证码点语义）。

**关键坑**：内建不可被用户函数重定义。故既有 golden 里一处用户函数 `find` 改名 `lookup_pair`。

**后端落地**（`backend-dawn`，提交 `82664a8`）：用新内建替换手写查找。

- `fm_paths.dawn`：删掉整套手写码点递归（`index_of/last_index_of/find/find_last/eq_at`），
  直接用内建（这是复盘点名的手写轮子）。
- `multipart.dawn`：删本地 `take`，`drop1` 改用内建 `drop`。
- `search.dawn`：本地带 `from` 偏移的 `index_of` 改名 `index_of_from`（内建同名不可重定义）。

**验证**：dawn-lang 全量 **1117 测试**通过；backend `build.sh` 全绿。

## 序 2 — SQL 命名列取值（✅）

**后端**（`backend-dawn`，提交 `862c79c`）。复盘痛点：按位置取列（`int_at(r,9)`——第 9 列靠数），
改 SQL 要人肉同步两处，数错即运行期 panic。

- `sql.dawn`：新增 `Row` 类型（`cells` + 列名→下标 `Map`，整个结果集共享一份不可变 Map）；
  `query_rows` 与 `query` 并列；**列名直接取自 JDBC `ResultSetMetaData`**——SELECT 改名自动流通，
  无需手维护名单。配套 `col_int/col_str/col_float/col_bool/col_opt_int/col_opt_str`，缺列 panic。
  **位置版 `int_at` 等全部保留，169 处旧调用零改动**（保留位置版兼容，逐步迁移）。
- `repo_article.dawn`：把旗舰 11 列查询（复盘点名的那个）全部迁到按名取值；三个几乎相同的详情
  shaper 合并成 `detail_json`；`list_item_json`/`shape_items` 走 `Row`。单列 count/flag 查询保留位置版。

**验证**：新增 sql 测试覆盖乱序列名、别名 `count(*) as n`、表限定列 `x.id` 取 bare 名
（`tags_json` 的 `select t.id,...` 依赖此）。backend **53 测试**全绿。

## 序 3 — Route 开放结构 + 中间件路由感知（✅）

复盘两个框架结构性问题：① Route 是封闭 ADT，加动词就改核心（加 `Method` 构造子 + 改三个访问器）；
② 中间件对路由零感知，body-limit/CORS 只能硬编码路径字符串（`starts_with(path,"/dav")` 等）。

**落地结果**（backend-dawn，纯框架改造，dawn-lang 语言本体无改动）：全部按下述方案实现，
`build.sh` **54 测试全绿**（新增 1 条 router 用例 `tags ride along on the matched route and reach RouteMeta`），
并对改动最大的 `handle()` 路径做了运行期冒烟（jar 起在本地，无 DB 的静态端点 + 中间件）：
`GET /api/health`→200 且 CORS 头贴上（匹配路由、无 no-cors tag）、`OPTIONS /api/articles`→204 预检、
`GET /nope`→404、`DELETE /api/health`→405、`OPTIONS /dav`→200 `Dav: 1,2` **且不贴 Access-Control-\***
（no-cors tag 生效、绕过 CORS 直达 DAV handler）——tag 驱动与旧硬编码路径行为逐一对齐。
契约三套（read/edge/webdav）对拍留部署时在生产库环境复核（需真 DB + 并存 FastAPI 比对）。

**方案（已实现）**：

- **Route 改开放记录**：`type Route = { method: String, pattern: String, tags: List[String], handler: Handler }`。
  method 就是字符串，`route_method/route_pattern/route_handler` 三个 pattern-match 访问器全删（改字段访问）。
  加动词 = 传不同字符串，不再动核心。
- **构造器命名坑**：Dawn **不允许大写函数名**（实测 `pub fn Get` 报 "expected a function name (lowercase)"），
  且小写 `get` 与内建 `get` 冲突。故构造器只能用 `route_get/route_post/route_put/route_delete` +
  通用 `route_method_of(verb, ...)`（替代 `Method`）。**代价：要扫 7 个文件、约 54 处 `Get(`→`route_get(`**
  （`api_admin`/`api_admin2`/`api_fm`/`api_public`/`auth`/`api_monitor`/`webdav`）。
- **中间件路由感知**：给 `Request` 加 `route: Option[RouteMeta]`（`RouteMeta = { method, pattern, tags }`，
  不含 handler 以便 derive Show）。`server.dawn` 的 `handle` 改成**先 dispatch 一次**拿到匹配路由，把
  `RouteMeta` 塞进 Request 再跑中间件链——中间件读 `req.route.tags` 取代硬编码路径（如 body-limit 看
  `tags` 里有没有 `"raw-body"`，CORS 看有没有 `"no-cors"`）。**注意**：中间件仍需包在最外层，保证 CORS
  preflight（OPTIONS）与日志对**未匹配**请求（404/405）也生效——所以是「dispatch 求元数据 + 复用同一
  dispatch 结果执行」，而非把中间件搬到路由之后。

**落地步骤（全部完成）**：① `web/router.dawn`：`Route` 改开放记录，`route_get/route_post/route_put/
route_delete/route_method_of` 构造器 + `tagged(r, tags)` 组合子 + `route_meta(r)`；`Found` 由携带
`handler` 改为携带整个 `Route`（这样 server 一次 dispatch 既能取 handler 执行又能取 meta），三个
pattern-match 访问器删除改字段访问；② `web/types.dawn`：新增 `RouteMeta {method,pattern,tags} derive Show`、
`Request` 加 `route: Option[RouteMeta]`（4 处测试字面量补 `route: None`）；③ `web/server.dawn`：`handle`
改为 catch_panic 内 build_request→**dispatch 一次**→`meta_of` 注入 `Request.route`→中间件链包住复用同一
`Dispatch` 的 `run_dispatch`（中间件仍最外层，故 CORS 预检/日志对 404/405 也生效）；④ `web/middleware.dawn`：
新增 `route_has_tag`（`match req.route`），`with_body_limit` 看 `raw-body`、`with_cors` 看 `no-cors`，删
`is_upload_path`/`starts_with(path,"/dav")`；⑤ dav 全部路由 `tagged(..., ["raw-body","no-cors"])`、
`/api/fm/upload` `tagged(..., ["raw-body"])`；⑥ 7 文件 54 处构造器调用 sed 迁移 + 各自 import 改名。

**踩坑/记录**：
- **WrongMethod 不携带路由 → 405 请求 `route=None`**：`Dispatch::WrongMethod` 只知「路径命中过」不知具体
  Route，故 405 请求拿不到 tags。影响面仅「/dav 上一个不在 verbs 列表里的未知动词且 body>2MB」这一极端角
  （标准 DAV 动词全在列表里、均 Found），可忽略；标准 404/405 行为与旧版一致（旧版 CORS/body-limit 也只在
  Ok 分支或按路径豁免）。
- **CORS 只贴 Ok 响应**（`Err(e)->Err(e)` 原样穿透，由 server 层 error_response 渲染）——404/405 不带
  Access-Control-*，此为**旧有行为**，序 3 未改动、非回归。
- 运行期本地起服务在 **WSL2** 上 `127.0.0.1` 低端口 bind 常报 `Address already in use`（Windows WinNAT
  保留端口段，Linux `ss` 看不到），换高端口（实测 18080）可绑；冒烟测试用高端口即可。

---

## 序 4 — 一等 `Bytes` 类型（✅ 根因 1）

设计定稿见 [`bytes-design.md`](bytes-design.md)（动码前先出草案，`c42f88c`）。

**语言本体**（dawn-lang `fe128b3`）：新增 `Type.TBytes`（运行期就是裸 `byte[]`，与不透明数组
同表示、零间接），内建 `utf8/decode/byte_len/byte_at/byte_slice/byte_index_of/as_bytes`，
操作符 `++`（`dawn/rt/Bytes.concat`）与按内容的 `==`（`Arrays.equals`），`Show` 渲染 `<N bytes>`；
Java `byte[]` 返回落成 `Option[Bytes]`、`Bytes` 反向传 Java `byte[]` 形参（`paramScore`）。
退役 `utf8_bytes`/`latin1_bytes`。四处注册（Types 签名 / CodeGen 运行期+dispatch / Doc 分组；
comptime 折叠与 value-handle **有意跳过**，同旧 byte 内建）。UFCS 让 `s.utf8()`/`b.decode(cs)`
免方法机制。**1124 测试全绿**（新增 `BytesTest` 8 例，改 `JavaInteropTest` 用新 API）。

**关键设计点**：`as_bytes(x)` 是唯一新增的「显式」互操作收窄——把擦除泛型的不透明 `Object`
（如 `HttpResponse.body()`）认领为 `Bytes`。先前试过让 `assignable` 隐式放行 `Object→Bytes`，
但**泛型内的 `expect[T]` 会把期望类型 `Bytes` 灌进 `T` → `Option[Object]` vs `Option[Bytes]` 不合**，
且 codegen 无处插 `CHECKCAST`；改为显式内建（运行期 CHECKCAST，非 `byte[]` 即 CCE 穿透，spec §9.5）。

**后端迁移**（backend-dawn `f9c339e`，有界路线）：`Request.raw` latin-1 String→`Bytes`、
`Response.bin` `Option[Object]`→`Option[Bytes]`（Response 重获 `derive Show`）、`read_body` 单次解码、
`fetch_bytes→Result[Bytes]`、`post_latin1→post_bytes`、multipart 改 over Bytes（结构用
`byte_index_of/byte_slice` 定位、内容留 Bytes、仅 ASCII 头 `decode` 取字段）、qiniu multipart 组 Bytes、
crypto/tencent `utf8_bytes→utf8`。`body: String` 保留（不动几十个文本 handler）。**build.sh 54 测试全绿**
（crypto 向量、multipart、qiniu/tencent 签名逐字节不变），jar 起服务 health/dav/404 正常。字节精确的
upload/PUT 往返对拍留部署时（同 M6.5，需 qiniu 钥 + 网络）。

---

## 序 5 — 互操作 Option 解包：后缀 `!`（✅ 根因 3）

设计定稿见 [`unwrap-design.md`](unwrap-design.md)（动码前先出草案，`05071e3`）。

**推翻了复盘的两条前提**（这是本轮最有价值的产出，记下来免得再走一遍）：

1. **复盘建议的「识别 `@NonNull`（多数 JDK API 有注解）」是错的**——实测（GraalVM 21 反射）
   `URI.create` / `HttpRequest.newBuilder` / `Base64.getEncoder` / `String.trim`（皆永不 null）
   与 `Map.get`（**真可空**）的 `getAnnotations()` 和 `getAnnotatedReturnType().getAnnotations()`
   **全是 `[]`**。JDK 不带运行期可见的可空性注解，编译器无从区分；而痛点 100% 在 JDK API 上，
   注解方案与痛点不相交。故取复盘的另一条路：`!` 后缀糖。
2. **「构造子不包 Option、方法包」不是缺陷，是有原则的区分**——JLS 保证 `new` 永不返回 null，
   故构造子不包是**有依据的**；方法可以返回 null 且分不出，只能包。规则其实一句话可教，
   本轮只把「为什么」写进 spec §9.2，不改行为。

**保留 Option 包装**（没顺手取消）：无注解则不包 = 把 null 放进 Dawn，违背「无运行期崩溃」
内核，也违背复盘自己第七节的结论——**「Dawn 的问题不是"管得太多"，而是几个地方"省得太狠"。
M7 的方向应是补齐被省掉的基础能力，而非放松已被证明有效的严格性。」** 留住安全，只砍噪音。

**语言侧**（`a44e461`）：`Unwrap` AST 节点（+ `panicMsg`，checker 填——codegen **没有**源文本
或行号表，`Diagnostic.render(file)` 是渲染时才拿 `SourceFile`）；Parser 后缀循环加 `BANG` 分支
（与既有 `QUESTION`/`Propagate` 平行）；Checker `Option[T]->T`、非 Option 报错（Result 的 hint
指向 `?`）、新增**可选** `srcText` 参数（仅为消息里的行号，构造点只有 `Analyze.kt` 两处，
缺省 `null` 降级为不带行号、不破坏任何测试）；CodeGen 复用 `genPropagate` 的 ADT 惯用法
（消息是编译期常量，无需实参槽）；Comptime `eval` 也支持（否则 `comptime` 里 `expect` 能跑而
`!` 不能，行为不一）。**1135 测试全绿**（新增 `UnwrapTest` 7 例 + golden `unwrap_postfix`/
`unwrap_not_option`）。

**两处非显然的修正**（都不在草案预料内）：
- **`Lexer.continuesLine` 必须移除 `BANG`**：行尾 `!` 是后缀解包的常态（`let u = URI.create(s)!`），
  而该表会**吞掉行尾 token 之后的换行**做续行 → 语句黏到下一行，报「expected a newline after
  this statement」。最小复现 `let n = Some(1)!` + 下一行任意语句。spec §1.7 原文只说「二元运算符/
  `|>`/逗号/开括号」续行，**BANG 本就不该在表里**——此修正是把实现拉回 spec。
- **Formatter 要区分后缀 `!` 与效果标注 `!io`**（两者空格**相反**，而 prev/cur 判不出：
  `Result[..] !io` 与 `xs[0]!` 前面都是 `]`）。判据取**后面跟什么**：效果标注后面是效果名
  或 `!(e1 | e2)` 的括号，后缀 `!` 两者皆不可能（表达式不能并排；且**只有标识符可被调用**，
  故不存在 `x!(y)` 与效果联合相混）。分类要在**含 NEWLINE 的原始 token 表**上做，否则
  `foo()!` 换行后接语句会被误判成效果。`!(e1 | e2)` 这一支是 `FmtTest/effect_union` 抓出来的。

**后端落地**（`f1b869e`）：134 处占位 `.expect` → `!`，**保留 3 处**——判据不是「是不是 Java
互操作」，而是**消息里有没有编译器复现不了的运行期信息**：`"db connect failed: $url"` ×2、
`"mac $algo"` ×1 告诉你哪个 url / 哪个算法失败，这正是 `expect` 存在的理由；而
`"b-uri"`/`"request body"`/`"result set"` 都只是在给值起名，自动消息
（`unwrapped None from ex.getRequestBody() at src/web/server.dawn:22`）严格更强。
重灾区 `http.dawn` 从 13 处占位串降到 0。58 测试全绿 + jar 起服务冒烟（health/404/401）。

---

## 流式请求体（✅ 复盘 §4 的请求侧，backend `c597a75`/`92a15b2`）

设计定稿见 [`streaming-design.md`](streaming-design.md)（草案 `19c9ba1`）。**无语言改动**——
`InputStream.transferTo` / `BodyPublishers.ofFile` 都是现成的 JDK 能力。

**约束（实测）**：opaque Java 字段**破坏 `derive Show`**，且 `Show` 不是 trait（只有 `Ord` 是）、
无 `impl` 逃生口 ⇒ `Request`/`Response` **不能持有 `InputStream`**。故设计为：框架**边收边写临时文件**、
只把**路径**交给 handler（纯数据、Show 完好；上传本就需要磁盘上的文件给 `ofFile`，故非妥协）。
这也正是 FastAPI 版的做法。

**落地**：路由 tag `"stream-body"`（复用序 3 的 tag 机制）→ `handle` 改为**先 dispatch 再读 body**
（method/path 来自请求行，不需要 body）→ 命中则 `transferTo` 临时文件、`Request.body_file = Some(path)`；
其余路由零行为变化。临时文件用 `catch_panic` 当 finally 删（Dawn 无 try/finally，同 `with_tx` 惯用法）。

**草案被推翻的一条**：原计划 `BodyPublishers.concat(head, ofFile, tail)` 组流式 multipart，
**用不了**——`concat` 是变参，而 **spec §9.3 明确「变长参数方法只支持不传可变部分的调用
（自动补空数组，如 `Path.of(p)`）；传可变实参 v0.1 不支持」**。改为把 multipart **流式装配到磁盘**
再 `ofFile` 发送（Content-Length 精确，qiniu 要求），代价是一次**纯磁盘**拷贝，不影响恒定内存本身。
同因，`Files`/`Path` 那套入口全是变参 → 改用 `java.io.File`（精确参数个数）。（`in` 是关键字，不能做变量名。）

**验证**：59 测试全绿（新增 `assemble_multipart` 字节精确 + 跨多个 8KB 缓冲块）。
本地实证：同为 **64MB 堆 / 200MB 文件**，流式路径成功、旧 `readAllBytes` 路径 `OutOfMemoryError`。
**生产实证**（`dav-stream-test/` 隔离 + 已清理）：2MB PUT→GET 字节精确往返；**100MB PUT → 201，
全程 100 个 RSS 采样平在 52–61MB（堆 256m），零 OOM**；框架临时文件零残留。
**遂回收当初的两个补丁**：`-Xmx512m→256m`、dav `client_max_body_size 64m→0`；
并把 `proxy_read/send_timeout 300s→1800s`（放开大小后超时成了新天花板——100MB 实测 295s，
离 504 只差 5 秒；瓶颈是服务器出站 ~3.5Mbps，不是 Dawn）。

---

## 不进本轮（回指 [`m6-retro.md`](m6-retro.md) 第六节）

- **传可变实参**（spec §9.3 记录的 v0.1 缺口）：Dawn 调不了任何需要传变参的 Java 方法
  （`BodyPublishers.concat`、`List.of(a,b)`…）。**流式这轮撞上了它**（只好绕成磁盘装配）。
  修法：互操作层把 `List[T]` 桥到 `T[]` 形参（`listBridges` 与数组不透明直通都是现成的），
  一并解锁全部变参方法。影响中、成本中，**建议作为下一个语言项**。
- **响应流式（GET 代理）**：撞同一个 `Show` 约束（`Response` 持流），是独立设计题；且已被
  「会跟随 302 的客户端直连七牛」+「Range 透传」两层缓解。
- 序 6 `Int`/`char` 值类型特化（根因 2，编译器大改，需性能基准护栏）。
- `/api/fm/upload`（multipart 代理上传）：请求体本身是 multipart，流式化需流式 multipart 解析器；
  且前端主流程走直传七牛，此端点是备用。
- `Result[T,E]` 的 `!`（序 5 只解 Option；Result 有 `?` 传播，痛点不在那儿）。
- `@NonNull` 第三方 jar 识别（反射对象现成、接线成本低，但与痛点不相交，收益低）。
- 瑕疵 4：上下文关键字 / `module.Type{}` / 限定调用一致性（纯人体工学，可择机）。
