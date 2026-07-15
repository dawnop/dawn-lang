# M6 复盘：用 Dawn 重写生产后端暴露的语言/标准库/框架设计问题

> 背景：M6 用 Dawn 把 dawnop.com 的 FastAPI 后端整体重写（`~/workspace/dawnop-site/backend-dawn/`，
> 44 个 `.dawn` 文件 ~4000 行），覆盖鉴权、文章/页面/标签 CRUD、全站搜索、七牛文件管理、
> 监控聚合、WebDAV，并逐字节对拍 FastAPI。整个后端已 100% 上线、退役 Python。
>
> 这份文档记录**编码过程中真实踩到的设计摩擦**，每条落在 `文件:行`。目的不是否定 Dawn——
> 它能把这样一个真实生产后端跑通并对拍一致，已证明"够用"——而是把摩擦当信号，指导后续里程碑。
>
> 分级图例：🔴 真·根因缺陷（污染面大或会拖垮更大项目） / 🟠 真·可修正的设计瑕疵（人体工学） /
> 🟡 小刺（习惯即可） / ⚪ 非 Dawn 之过（迁移约束或固有难度，列出以示区分）。
> 引用路径：语言本体 `dawn-lang/`，后端 `dawnop-site/backend-dawn/src/`（下称 `src/`）。

---

## 一、总览诊断

| 层 | 最伤的设计 | 分级 |
|---|---|---|
| 语言 | 没有一等 `byte[]`，String 无法自行跨到字节 | 🔴 根因，污染全栈 |
| 语言 | 泛型全擦除 + 装箱，`char = Int` | 🔴 缺陷（性能 + 人体工学） |
| 语言 | Java 互操作把一切包进 Option | 🟠 取舍过度 |
| 语言 | 关键字/命名空间挤占 + 导入规则不一致 | 🟠 可修正瑕疵 |
| 语言 | 类型推断偏弱（空列表要标注、元组不能 `.0`） | 🟡 小刺 |
| 标准库 | SQL 按位置取列 + 手写列类型清单 | 🔴 API 偷懒（非语言所迫） |
| 标准库 | JSON 数字一律 Float | 🔴 设计 bug（M6 已补 `JInt`） |
| 标准库 | 缺 `find/index_of/take/drop/reverse` 等常见函数 | 🟠 缺功能 |
| 标准库 | TTL 缓存靠 `AtomicReference[String]` 塞拼接串 | 🟠 被语言限制逼出的样板 |
| 框架 | Route 是封闭 ADT，加动词就改核心 | 🔴 可扩展性缺陷 |
| 框架 | 中间件对路由无感知，只能硬编码路径字符串 | 🔴 抽象缺失 |
| 框架 | Request/Response 为二进制 bolt-on `raw`/`bin` | 🟠 根因 1 的下游 |
| 框架 | 无流式请求/响应，大文件整包进内存 | 🟠 缺功能 |
| 框架 | 路由线性扫描 + 顺序敏感、无类型安全 URL | 🟡 |

**一句话结论**：真正拖后腿的是**过度简化**（没有 byte[]、数字只有 Float、Route 封闭），
而非**过度严格**。那些"啰嗦"的设计（Result/Option、强制解构、无异常）恰恰是这次迁移几乎零运行期崩溃的原因。

---

## 二、语言核心

### 🔴 根因 1：没有一等 `byte[]`，String 不能自己变字节

Dawn 的 `String` 是 `TString`，不是 `java.lang.String`，连 `getBytes()` 都调不了。后果像多米诺：

- 专门加内建 `utf8_bytes` / `latin1_bytes` 才能过桥（`dawn-lang/src/main/kotlin/.../Types.kt:428`，
  注释自承 "the one bridge a Dawn String cannot cross on its own"）。
- **所有二进制都靠 ISO-8859-1 字符串滥用**：multipart 上传、WebDAV PUT 的文件字节，全先
  `String.new(bytes,"ISO-8859-1")` 解成 latin-1 串，处理完再 `latin1_bytes` 编回
  （`src/multipart.dawn:1-13`、`src/http.dawn:70`、`src/qiniu_rs.dawn:59`）。
- crypto 每个原语都要先 `utf8_bytes(s)`（`src/crypto.dawn:13`、`src/qiniu_sign.dawn:25`）。
- `byte[]` 不能出现在函数签名（spec §9.5），只能作 `Object` 在单个函数体内存活。

**为什么不合理**：二进制 I/O 是后端刚需（上传、签名、哈希、代理）。把它硬塞进"字符串世界"，
是把复杂度从语言转嫁给每个使用者。latin-1 往返虽巧妙（0..255 一一映射，无损），但它是 hack 而非设计——
大文件还因此被迫整包进内存（叠加根因 2 与框架流式缺失）。

**更好的设计**：一等不可变 `Bytes` 类型；`String.utf8() -> Bytes` / `Bytes.decode(charset) -> String`
作标准方法；I/O 直接走 `Bytes`。

### 🔴 根因 2：泛型全擦除 + 装箱，且 `char = Int`

- `HttpResponse<T>.body()` 的 `T` 擦成不透明 `Object`，调用处要 `String.valueOf(...)` 桥回
  （`src/http.dawn:58,81`），或为二进制专门加 `fetch_bytes(...) -> Result[Object,String]`（`src/http.dawn:20`）。
- 向下转型靠运行期 CHECKCAST（项目里专门做了 "G6" 这一刀才让 `Object` 收窄回具体引用形参）。
- **`code_points(s): List[Int]`**——字符处理要把字符串炸成 `List[Int]`，一篇文章正文就是**百万个装箱 Int**。
  `src/multipart.dawn` 头注释专门警告 "never code_points on the content ... would box millions of Ints"；
  但 `src/export.dawn:26`(needs_quote)、`src/repo_article.dawn:14`(word_count)、`src/search.dawn:29`(高亮)
  仍不得不用。

**为什么不合理**：把 `char` 变成堆上的 `Int`、把字符串遍历变成百万次分配，对一个要跑文本（博客！）的
语言是硬伤。native-image 二进制也因此膨胀。

**更好的设计**：值类型特化（至少 `Int`/`char`）；`String` 提供 `char_at`/`index_of`/迭代器，
不强制物化成 `List[Int]`。

### 🟠 根因 3：Java 互操作把一切包进 Option → `.expect()` 满天飞

`src/http.dawn:22-28` 连续 **10 个 `.expect()`**：

```
let uri = URI.create(url).expect("uri")
let base = HttpRequest.newBuilder().expect("b").uri(uri).expect("b-uri")
let nobody: BodyPublisher = BodyPublishers.noBody().expect("nobody")
let req = withHeaders.method("GET", nobody).expect("get").build().expect("req")
```

且**不一致**：构造子 `SecretKeySpec.new(...)` 直接返回对象（不包 Option），实例方法 `.newBuilder()`
返回 Option（`src/crypto.dawn:21` vs `src/http.dawn:23`）。同段代码有的 `.expect` 有的不，靠记忆区分。

**为什么不合理**：JDK 的 `URI.create`/`newBuilder` 永不返回 null，保守包成 Option 是"用噪音换安全"；
构造子/方法两套规则加重心智负担。

**更好的设计**：互操作层区分 `@NonNull`（多数 JDK API 有注解）；或提供 `!` 后缀糖统一解包，
而非满屏 `.expect("b-uri")` 这种无意义占位串。

### 🟠 瑕疵 4：关键字/命名空间挤占 + 导入规则不一致

- `type` 是关键字 → page 的 `type` 列在 Dawn 侧被迫叫 `kind`，SQL/JSON 边界再手工映射回 `"type"`
  （`src/repo_pagetag.dawn:14`、`src/api_admin2.dawn:200`）。
- `get` 是内建 → config 取值函数改名 `lookup`（`src/config.dawn:47`）。
- **record 字面量不能限定类型名**：不能写 `auth.Auth{...}`，必须 `use auth.{Auth}` 再写裸 `Auth{...}`
  （`src/main.dawn:14,35`）。
- **qualified 调用只对 whole-module import 生效，bare 名只对 selective import 生效**——最坑的一条不一致：
  三个 repo 都有 `by_slug`/`list_admin`，于是 `api_admin.dawn` 全 whole-module + 限定调用、
  `api_public.dawn` 混用、`api_admin2.dawn` 按模块切风格（`src/api_admin.dawn:13` vs `src/api_admin2.dawn:12`）。
  同一代码库三种风格。

**更好的设计**：上下文关键字（`type` 只在定义位置是关键字）；允许 `module.Type{}` 字面量；
无论导入方式都允许限定调用。

### 🟡 小瑕疵 5：类型推断偏弱 + 语法小刺

- 空列表 `[]` 必须标注 `let l: List[String] = []`（`src/export.dawn:65-68`）。
- 元组不能 `.0`，一律解构 `let (a,b) = p`（`src/http.dawn:42`），用不到的成员还得 `_` 占位。
- 语句只能换行分隔（不能 `;`）、`match` 分支带 `assert` 要 `{}`——风格取舍，初学反复踩。

> ✅ **澄清一条**：曾以为"嵌套类点式导入要手工把 `.` 换 `$`"，实测编译器**自动处理**
> （`src/http.dawn:8` 直接写 `HttpRequest.Builder` 即可）。这条不算摩擦，是做对了的地方。

---

## 三、标准库

### 🔴 SQL：按位置取列 + 手写列类型清单（纯 API 偷懒，不怪语言）

```
# src/repo_article.dawn:56 —— 11 列查询要手写 11 个 Col
[ColInt, ColStr, ColStr, ColStr, ColInt, ColInt, ColInt, ColStr, ColStr, ColStr, ColInt]
# 取值全靠位置，改 SQL 要人肉同步两处
("word_count", jint(word_count(str_at(r, 9))))   # 第 9 列是什么？靠数
```

`int_at(r,0)`/`str_at(r,1)` 位置一错就运行期 panic，无编译期保护（`src/sql.dawn:142-175`、
`src/auth.dawn:59,67`）。**最容易改好**的一条——不是语言所迫，是 `sql` 模块 API 设计得糙。

**更好的设计**：`row.int("views")` 命名列取值；或派生宏从 record 自动生成映射（类 `sqlx::query_as!`）。

### 🔴 JSON：数字一律 Float（真·设计 bug，M6 已补救）

`src/json/value.dawn` 注释自承：M4 词法器**只产 `JNum`(Float)**，于是 `42 → 42.0` 的 round-trip
把 TTL 缓存里的字节数、ID、计数全变 `x.0`。补救是 M6 才加的 `JInt` + 解析器 `is_int_literal`
判断有无小数点（`src/json/parser.dawn:113`）。**现状=已解决**，但教训是：整数/浮点区分是常识，
一开始就该有，别"简化过头"。

### 🟠 缺常见函数，被迫手写

`find`/`index_of`/`last_index_of` 非内建，`src/fm_paths.dawn:63-82` 用尾递归手写了一整套字符串查找。
`take`/`drop`/`reverse` 也缺。这些是 Python/JS/Java 内建常识，缺了就每项目重造轮子、每次可能引入 off-by-one。

### 🟠 TTL 缓存靠 `AtomicReference[String]` 塞 `"时间戳|payload"`（`src/ttl.dawn`）

没有泛型可变容器、没有全局可变状态的干净出口，缓存退化成"timestamp 和 payload 用 `|` 拼进字符串，
取出再 split"。能用，但是被语言限制逼出的样板。

### 🟡 其他被迫手写的样板

- `.env` 解析手写（Python 用现成 `python-dotenv`）（`src/config.dawn`）。
- 无 try/finally → `with_db` 回调式确保连接关闭（`src/db.dawn`）——回调式补偿不够优雅。

### ⚪ 不怪 Dawn：跨语言时间对拍

`src/fm_paths.dawn:52` 的 `ts()` 要用 `LocalDateTime + ZoneId.systemDefault()` 精确复刻 Python 朴素
`datetime.timestamp()`——这是**迁移对拍的固有难度**（两运行时对朴素时间的解释要逐字节一致），非 Dawn 之过。

---

## 四、Web 框架

### 🔴 Route 是封闭 ADT，加一种路由形态就要改框架核心

原型只有 `Get/Post/Put/Delete` 四个构造子。WebDAV 需要 11 个动词（OPTIONS/PROPFIND/MKCOL/MOVE/COPY/LOCK…），
于是**改核心**加了 `Method(verb, pattern, handler)` 构造子，并同步改三个访问器的 pattern-match
（`src/web/router.dawn:7-41`）。尾段捕获 `{rest*}` 也是为 WebDAV 现加，`match_path` 从"长度相等逐段比"
变成三路分支（`src/web/router.dawn:59-87`）。

**为什么不合理**：Web 框架应**对扩展开放**。用封闭 ADT 表达路由，意味着每加一类需求（新动词、通配、正则）
都得动框架本身。

**更好的设计**：路由 = `(method: String, matcher, handler)` 的开放结构；method 就是字符串；
matcher 可组合（精确/前缀/通配/参数）。

### 🔴 中间件对路由零感知 → 硬编码路径字符串

中间件是纯 `fn(Handler)->Handler`，看不见任何路由元数据。后果：body-limit 和 CORS 只能在函数体里
**硬编码路径判断**：

```
# src/web/middleware.dawn:33 —— 上传路径豁免体积限制，靠字符串前缀
starts_with(path,"/dav") || path == "/api/fm/upload"
# src/web/middleware.dawn:41 —— CORS 跳过 WebDAV，又一次字符串判断
if starts_with(req.path, "/dav") { next(req) }
```

想"只给 admin 路由加限流"这种最普通的需求，这框架做不到——中间件无法按路由分组。新增上传端点就得回去改
`is_upload_path`。

**更好的设计**：中间件能拿到路由元数据（handler 名/标签/是否需鉴权）；支持按路由组挂载中间件。

### 🟠 Request/Response 为二进制 bolt-on（根因 1 的下游）

`Request` 硬加 `raw: String`（latin-1 副本），`Response` 硬加 `bin: Option[Object]`，`read_body`
把同一份 bytes **解码两遍**（UTF-8 + latin-1）（`src/web/types.dawn:10`、`src/web/server.dawn:22`）。
写响应还要 `match r.bin` 分叉。不是框架的错，是根因 1（没有 byte[]）在框架层的复现。

### 🟠 无流式请求/响应

请求体一次性 `readAllBytes` 进内存，响应体一次性 `write`。WebDAV PUT 大文件因此整包驻留内存——
这正是上线时把 JVM 堆 256m→512m、并给 nginx 加 `client_max_body_size 64m` 的原因。源码注释自标
"first-version limits"（`src/webdav.dawn:9`）。GB 级文件、Range 续传都做不了。

### 🟡 路由线性扫描 + 顺序敏感，无类型安全 URL

- 首个匹配即中，于是 `/api/articles/admin` **必须**排在 `/api/articles/{slug}` 之前，否则 admin 被当 slug
  （`src/main.dawn:56` 注释就在防这个）。全靠注释，无编译期检查。
- 路径是散落各处的字符串字面量，无 URL 反解，前端只能另维护一套 URL 常量，无单一真相源。

### ⚪ 自找的，不算框架缺陷：pydantic 报错逐字复刻 + "detail" 键

`query_int_bounded` 硬编码 pydantic 错误串（连**全宽冒号 `：`** 都还原）、`error_response` 用 `"detail"` 键
（`src/web/types.dawn:103`、`:77`）——这些是**为对拍 FastAPI 主动背的包袱**，非框架缺陷。不需对拍时删掉即可。
列此以免把"迁移约束"误算成"框架毛病"。

---

## 五、判断分级小结

**必须修（真会拖垮更大项目）**
1. 一等 `Bytes` 类型 + `String↔Bytes` 标准方法（根因 1）——一个能消掉全栈至少 5 处 hack。
2. `Int`/`char` 值类型特化 + `String` 不物化的字符访问（根因 2）——文本应用尤其需要。
3. SQL 命名列取值（标准库 easy win）。
4. Route 开放结构 + 中间件路由感知（框架两个结构性问题）。

**值得改善（人体工学）**
5. 互操作 Option 收敛（用 JDK nullability 注解），消掉满屏 `.expect`。
6. 上下文关键字 + `module.Type{}` 字面量 + 统一限定调用规则。
7. 补齐 `find/index_of/take/drop/reverse` 等标准函数。

**可接受的取舍（学习型语言的合理简化，不建议改）**
- 无 null / 无异常 / Result-Option：啰嗦，但真的挡住整类 bug——这次迁移零空指针、零未捕获异常。
- 效果系统 `!io` 污染：标注负担真实，但换来"纯/不纯"一目了然，方向对；只需给纯逻辑更好的逃生门。
- 换行分隔语句、`.new` 直接返回：小刺，习惯即可。

**已解决**
- JSON 整数保真：M6 已加 `JInt` + 解析器判定，现状 OK。

---

## 六、修复优先级排序（M7 输入）

排序原则：**先快赢去风险、建立节奏 → 再结构性重构 → 最后大改造**；同层内按"影响 ÷ 成本"。
`Bytes`（根因 1）影响最大但成本也最高，故不排第一，而是先用几个隔离的快赢铺垫，最后集中攻坚。

| 序 | 修复项 | 层 | 影响 | 成本 | 依赖 | 理由 |
|---|---|---|---|---|---|---|
| **1** | 补齐标准库函数 `find/index_of/last_index_of/take/drop/reverse` | 库 | 中 | 极低 | 无 | 纯新增内建/库函数，零破坏；立刻消掉 `fm_paths` 等处手写递归。热身、建节奏。 |
| **2** | SQL 命名列取值 `row.int("col")`（保留位置版兼容） | 库 | 高 | 低 | 无 | 隔离在 `sql` 模块；干掉一整类"数错列号→运行期 panic"。日频最高的痛。 |
| **3** | Route 改开放结构 + 中间件可见路由元数据 | 框架 | 高 | 中 | 无 | 结构性；与二进制无关，可独立做。让日后加动词/按组挂中间件不再动核心。 |
| **4** | 一等 `Bytes` 类型 + `String↔Bytes` + I/O 走 Bytes | 语言+库+框架 | 极高 | 高 | 无（但牵动 http/crypto/multipart/框架 binary 字段） | 根因 1。落地后可回收 `utf8_bytes`/`latin1_bytes` hack、简化 Request.raw/Response.bin、为流式铺路。需先出设计草案。 |
| **5** | 互操作 Option 收敛（`@NonNull` 识别 / `!` 解包糖） | 语言 | 中 | 中 | 可搭 4 的互操作改动一起 | 消掉满屏 `.expect("b-uri")`；与 Bytes 都动互操作层，合并做省重复。 |
| **6** | `Int`/`char` 值类型特化 + `String` 非物化字符访问 | 语言（编译器） | 高（性能） | 高 | 无 | 根因 2。编译器大改（装箱→值类型、code_points 去物化）。放最后，独立里程碑，需性能基准护栏。 |

**建议第一批（低风险、可立即动手）**：序 1 + 序 2 + 序 3。三者互相独立、不破坏现有 1098+ 测试，
能立刻改善日常人体工学与框架可扩展性，且为序 4（Bytes）争取设计时间。

**不进本轮**：上下文关键字/`module.Type{}`（瑕疵 4，纯人体工学，可择机）、流式请求响应
（依赖序 4 的 Bytes 落地后再做更顺）。

---

## 七、给未来的自己：一条反直觉的经验

这次改一个**自制语言写的生产后端**，最省心的部分恰恰来自那些"啰嗦"的设计——Result/Option +
强制解构 + 无异常让我几乎没遇到运行期崩溃，所有错误都在编译期或显式 `Result` 分支暴露。
真正拖后腿的是**过度简化**（没有 byte[]、数字只有 Float、Route 封闭），而非**过度严格**。
Dawn 的问题不是"管得太多"，而是几个地方"省得太狠"。M7 的方向应是**补齐被省掉的基础能力**，
而非放松已被证明有效的严格性。
