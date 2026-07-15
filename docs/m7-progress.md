# M7 进展：执行 M6 复盘的修复优先级（第一批）

> 背景：[`m6-retro.md`](m6-retro.md) 第六节排了一张修复优先级表。**第一批 = 序 1 + 序 2 + 序 3**
> （互相独立、不破坏现有测试、低风险，且为序 4「一等 Bytes」争取设计时间）。本文件记录第一批
> 的落地状态，供中断后接续。工作跨两仓：语言本体 `dawn-lang/`，后端 `dawnop-site/backend-dawn/`。

## 状态总览

| 序 | 修复项 | 层 | 状态 | 提交 |
|---|---|---|---|---|
| 1 | 补齐 `find/take/drop/reverse` + 字符串 `index_of/last_index_of` | 库 | ✅ 完成 | dawn-lang `1784358`、backend `82664a8` |
| 2 | SQL 命名列取值 `row.col_int("x")` | 库 | ✅ 完成 | backend `862c79c` |
| 3 | Route 开放结构 + 中间件路由感知 | 框架 | ✅ 完成 | backend `3cfe1b4` |

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

## 不进第一批（回指 [`m6-retro.md`](m6-retro.md) 第六节）

- 序 4 一等 `Bytes` 类型（根因 1，影响极高、成本高，需先出设计草案）。
- 序 5 互操作 Option 收敛（消满屏 `.expect`，可搭序 4 一起做）。
- 序 6 `Int`/`char` 值类型特化（根因 2，编译器大改，需性能基准护栏）。
