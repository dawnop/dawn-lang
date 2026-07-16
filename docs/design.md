# Dawn 设计文档

本文记录 Dawn 的目标、非目标，以及每个重要决策的理由。语法与语义的权威定义在
[spec.md](spec.md)，本文只讲"为什么"。

## 1. 目标

- **一个人能写完、能维护**的语言实现：编译器预算 6–8 千行（Kotlin），
  一年内业余时间可达到自举日常小工具的程度。
- **JVM + native 双目标**，且不为此付出双后端成本：唯一后端是 JVM 字节码，
  native 由 GraalVM native-image 从字节码 AOT 得到。
- **看签名即知副作用**：纯度是类型系统的一部分，不靠约定。
- 报错信息质量对标 Gleam / Rust：错误指向源码、说人话、给修复建议。

## 2. 非目标（v0.1 明确不做）

| 不做 | 理由 |
|------|------|
| 完整代数效应（handlers） | 工程黑洞；两级纯度已拿到大部分收益 |
| ~~trait / typeclass~~ | ~~先用显式传函数顶着，疼了再加~~ → 疼了，2026-07-13 已加（见 D9） |
| async / 协程 | `!io` + JVM 虚拟线程顶着，语言层不引入着色问题 |
| 宏 | comptime 覆盖主要场景，且不引入第二门语言 |
| 自定义运算符 | 防生态长成早期 Scala |
| Java → Dawn 方向互操作 | 双向 ABI 稳定是大语言的活 |
| REPL | 与 comptime/整体编译模型冲突，性价比低 |
| 自定义 GC / 内存模型 | JVM 的 GC 就是我们的 GC |

## 3. 决策记录

### D1 唯一后端 = JVM 字节码（ASM 直出）

native-image 吃字节码，故 `dawn build --native` 只是在 jar 后面接一条
`native-image` 命令。代价是接受封闭世界假设，因此语言设计上主动规避其雷区：

- 不生成自定义 `invokedynamic` bootstrap（方法分发全用
  `invokevirtual`/`invokestatic`）；闭包用 `LambdaMetafactory`（在
  native-image 支持名单内）。
- 语言不提供 `eval`、运行时加载代码、反射。这些特性本来也不在目标里，
  于是 native 编译**不需要任何配置文件**，by construction。

### D2 效果系统只有两级：pure 与 io

完整的 Flix 式多态 effect 系统很漂亮，但类型推导、错误信息、教学成本全部翻倍。
Dawn 的格子只有两个点 {pure, io}，外加效果变量做最简效果多态
（`map(f)` 的效果 = `f` 的效果）。实现上这只是类型检查器里多传一个布尔格子；
收益却是大头：纯函数可以被 comptime 调用、可以被激进优化、测试无需 mock。

升级路径：若未来要加 `!net` / `!fs` 等细分效果，格子从两点扩成幂集，
语法位置（`!` 后缀）已经预留。

### D3 comptime 而非宏；comptime 不操作类型

编译器必须有常量折叠 → 必然内含一个 AST 解释器 → 把它暴露给用户就是 comptime。
只允许纯代码，产物必须是常量可序列化值。刻意不做 Zig 那种"类型是一等 comptime
值"——那会把类型检查器和求值器搅成一团，是小实现驾驭不住的复杂度来源。
泛型走独立的、无聊的参数多态（擦除 + 装箱），不与 comptime 耦合。

### D4 错误处理 = Result + `?`，panic 兜底

异常破坏"签名即契约"（一个不标 `!io` 也能炸的函数是纯度谎言）。
可恢复错误走 `Result[T, E]` + `?` 传播；不可恢复走 `panic()`（进程终止，
JVM 上映射为抛 Error，native 上 abort）。`panic` 不需要 `!io`——它不返回。

### D5 Java 互操作：单向、全部 `!io`、null 自动包 Option

- **单向**（Dawn 调 Java）：避免承诺 ABI。
- **全部 `!io`**：无法逐方法审计 Java 的纯度，保守处理。代价是
  `Math.sin` 这类明显纯的也标了 io——用标准库包一层白名单解决
  （stdlib 内部用 `@trusted_pure` 逃生门，用户代码不开放）。
- **null 不进语言**：Java 引用类型返回值自动是 `Option[T]`。
  宁可调用处多写一个 `.expect()`，不让 null 污染类型系统。

### D6 无中间 IR

AST → 类型/效果检查（在 AST 上标注）→ ASM 直出字节码。优化交给 JVM JIT 和
native-image。等真的需要优化 pass 或第二后端时再引 IR——为想象中的需求
预付架构成本是小项目最常见的死法。唯一的例外是尾递归重写（AST 层变换）。

### D7 实现语言 = Kotlin

比 Java 少三成样板（数据类、sealed class、模式匹配雏形正好用来写编译器），
产物同样是 jar，同样能 native-image 自举编译器本身。

### D8 互操作三件套：SAM 转换、数组直通、List 零拷贝桥（2026-07-12 定稿）

M6 前置，先用 playground runner 验收。四个语义决策全部对照过 Kotlin/Scala/Clojure 前例：

- **SAM = indy + LambdaMetafactory**（Kotlin 1.5+/Scala 2.12+ 同路；spike 证 native-image
  零配置）。统一走 `dawn$sam$N` 静态桥 + LMF 捕获函数值，不为直接引用做免捕获特化。
- **回调引用参数不包 Option，桥接处 null 检查即 panic**——Kotlin 同款
  （`Intrinsics.checkNotNullParameter` fail-fast）。`handle(ex: Option[HttpExchange])`
  的人体工学不可接受；返回位置 null 是常态（进类型），回调参数 null 属病态（fail-fast）。
- **效果不设限**：`!io` 在 codegen 是擦除的，调用约定不变——Kotlin 禁 suspend lambda
  转 SAM 是因为 suspend 改了调用约定（多 Continuation 参数），Dawn 无此障碍。
  可靠性论证：Java 代码只在 Dawn `!io` 调用之下或无 Dawn 栈的线程上运行，
  纯函数契约不可能被违反。
- **List 桥零拷贝 + 不可变视图**（`Collections.unmodifiableList`）——Scala `asJava` /
  Clojure 持久集合同款；且 Dawn `TList` 运行时表示本来就是 `java.util.List`，
  桥成本 ≈ 一个 INVOKESTATIC。原「List.copyOf 拷贝」方案被前例调研推翻。
  嵌套容器元素拒绝（零拷贝会泄漏内层可变性）。
- **收窄溢出 panic**（Clojure `RT.intCast` 同款）；panic 穿边界按 RuntimeException
  自由传播（三家一致）。
- **明确不做**：静态字段读取（`valueOf`/`forName` 绕行够用）、Map/Set 桥、
  Java→Dawn 集合反向转换——留 M6 真痛了再议。

### D9 trait = 单参数名义 typeclass + 字典传递（2026-07-13 定稿）

完整设计与实现记录见 [trait.md](trait.md)；spec §3.5 是规范化摘要。要点：

- **取 Rust 的一致性模型**（每个 trait×类型全程序唯一 impl + 孤儿规则），
  **取 Haskell 的字典传递实现**——擦除+装箱后端天然契合，具体调用点全部去虚化
  （`invokestatic`），只有约束转发走接口调用。不做单态化（native-image 代码
  膨胀 + 编译时间不划算，v2 可作优化再议）。
- **单参数、无条件 impl、无 supertrait、无 dyn**：v1 只解决「泛型约束 +
  自定义排序」。多参数/关联类型每个都让推导和报错翻倍，先不付这个成本。
- **运算符只桥比较族**（`< <= > >=` → 预置 `Ord.cmp`）：`==` 保持结构相等
  不放开——自定义相等会连坐 Map/Set 键语义与模式匹配，风险大收益小。
- **impl 全局生效、不随 use**——一致性保证唯一，导入与否只影响名字可见性，
  不影响实例选择，避免 Scala 隐式那类「导入决定行为」的坑。
- **意外之喜**：模块 DAG + 孤儿规则使跨模块重复 impl 结构性不可能（两个合法
  归属模块需互相引用成环），一致性只需拦同模块重复。
- `derive Ord`（字段字典序）与 `sort`/`sort_by`/`max`/`min`/`max_by`/`min_by`
  同刀交付，让「疼点→解药」闭环。

## 4. 特性来源致谢

- 克制的特性集与报错质量标杆：Gleam
- 纯度/效果标记：Flix（简化到两级）
- comptime:Zig（去掉类型级编程）
- `?` 传播、表达式导向:Rust
- 管道 `|>` 首参传递:Gleam / Elixir

## 5. 里程碑

- **M0 走通**（已完成）：`Int`/`String`、函数、`match`、`!io` 检查；
  `dawn run` 与 `dawn build --native` 两条命令产出一致结果。
- **M1 像门语言**（完成，2026-07-11；验收样例 `examples/shapes.dawn` 原样通过
  `dawn run` 与 `dawn test`，JVM/native 输出一致）：
  - ADT（命名字段构造、嵌套构造器模式、`..`、结构相等）+ 穷尽性检查
    （usefulness 算法，精确列出缺失构造器）；
  - record（字面量/同名简写/函数式更新 `..base`/字段访问/记录模式）、Float 字面量模式；
  - 泛型（fn/type 类型参数、调用点合一推导 + 期望类型播种、擦除 + 装箱）、
    prelude `Option`/`Result`、内建 `List`（字面量/`++`/`len`/`get`/`range`/for-in/结构相等）；
  - lambda（捕获按值、禁捕 `var`）、函数类型 `fn(A) -> B !e`、顶层函数作值、
    效果变量（签名内共享、调用点实例化）、`map`/`filter`/`fold`；
    LambdaMetafactory 在 native-image 下免配置已实测；
  - `?` 传播（Option/Result，Err/None 原实例直接早退）、test 块 + `assert`
    （`==` 断言失败报两侧值；`dawn test` 执行、`dawn build` 剥除）。
  - 留到后续：列表模式 `[x, ..rest]`、构造器作函数值、效果并 `!(e1|e2)`、
    let 模式解构、`derive Show`。
- **M2 立身特性**（完成，2026-07-12；验收样例 `examples/calc.dawn` 原样通过
  `dawn run` 与 `dawn test`，native 一致；测试 176 项全绿）：
  - comptime（纯子集 AST 解释器 + fuel 预算 + 常量嵌入 / 非标量静态字段物化）
    与顶层 const（SCREAMING_SNAKE、声明序求值故无环）；
  - `use java` 互操作（编译期反射读签名、重载打分消解、null→`Option`、
    varargs 空参、结果可弃、全部 `!io`——映射规则已在 spec §9 敲死）；
  - stdlib core：字符串函数（chars/split/join/trim/parse_int...）、
    `read_file`/`write_file`/`args`/`read_line`、`expect`/`unwrap_or`；
  - 三引号多行字符串（插值本就完整）、列表模式 `[x, ..rest]`/`[..init, last]`
    （穷尽性按长度构造器精确判定）；
  - 计划外补的前置：元组 + let/var 模式解构、点调用糖 `x.f(a)`、
    函数/内建作一等值（泛型按期望类型实例化）、`?` 进 lambda（返回类型已知时）、
    `==` 用左侧类型给右侧做推导种子——calc.dawn 逐行逼出来的。
- **M3 体验**（完成，2026-07-12；报错 golden 套件 + fmt 幂等性/保真测试全绿，
  测试 366 项；calc/shapes 及 derive-Show/构造器值/效果并组合样例 JVM 与 native 输出一致）：
  - 报错打磨：`diag/Suggest.kt`（有界 Levenshtein，阈值 `min(2, len/2)`，单字符不猜）
    接到未知变量/函数/构造器/类型/字段五处；补齐可执行 hint；Diag.kt 顶钉风格指南；
    `GoldenErrorTest`（`@TestFactory` + `-DupdateGolden` 再生）锁住每条消息文本；
  - `dawn fmt`：**token 流重排器**（`fmt/Formatter.kt`）——按 span 原样重印每个 token
    （字符串/插值一字不改），只改 token 间空白；缩进用 opener-line 栈让块正确嵌套；
    保 token / 保注释 / 幂等三不变量由 `FmtTest` 对全部 examples 与 golden 源校验；
    `dawn fmt [--check]` + LSP `documentFormattingProvider`；
  - M1 尾巴收编：**构造器作函数值**（`map(xs, Some)`，LMF over `dawn$ctor$` 桥接）、
    **效果并 `!(e1|e2)`**（`Eff.Union` + 规范化，`effSubsumes` 驱动覆盖检查与合一）、
    **`derive Show`**（每个 ADT/元组生成 toString 走 `dawn/rt/Show`，渲染成合法 Dawn 源码形状）；
    let 模式解构与列表模式已在 M2 提前完成；
  - **教程初稿** `docs/tutorial.md`（11 章，`TutorialTest` 抽取每个 dawn 块机械编译、
    带 output 的块跑输出比对）。
  - 计划外补的前置：元组元素/嵌套渲染、返回位置 lambda 取类型参数作参数类型。
- **M4 工程能力**（完成，2026-07-12；八刀 97e6aac..，测试 748 项全绿；验收样例
  `examples/m4/json` 过 JSONTestSuite 全部 318 例，JVM 与 native 输出一致）：
  从「单文件玩具」到「能写项目」，语义先在 spec §10/§11、§1.5/§2.2 敲死再动手。
  - 模块系统：多文件项目、`use`（整模块 / 选择性 `.{...}`）、`pub` 可见性、`src/` 根约定、
    禁环、拓扑序 comptime（`check/ModuleLoader.kt` 加载器 + `analyzeProgram`）。
    定夺：模块别名与绑定同名 = 编译错误（消歧）；类型/构造器/常量跨模块只走选择性引入；
    无 `dawn.toml`（目录约定即工程）。codegen 运行时类提到程序级、ADT 类名带模块前缀。
  - `Map`/`Set`：内建持久容器，`LinkedHashMap`/`LinkedHashSet` copy-on-write，保插入序
    确定（JVM/native 一致）；平铺内建 API；为作键给 ADT/元组/record 生成配套 `hashCode`。
  - char：走 **Go 的 rune 路线**——`'a'` 是等于码点的 `Int` 字面量（词法层搞定，类型系统零改），
    配 `code_points`/`from_code_points`/`str_len`/`substring`/`char_to_string`。**bytes 推迟**。
  - `dawn run/test/build/fmt` 吃项目目录；LSP 多文件支持（`analyzeDocument` 从磁盘解析 use；
    跨文件跳转：FnSig/AdtInfo/FieldInfo/ConstDecl 带 `srcPath`，导入的函数/类型/构造器/常量、
    `alias.fn` 调用与 `use` 行条目都能跳到定义所在文件）。
  - **坑**：`\r` 不是 Dawn 转义（用 13）；（字符串里 `{` 恒是插值的旧坑已随 `$` 插值改版消失）
    `assert`/赋值是语句不能作 match 臂；`map_empty()` 靠 needsExpected 推迟到兄弟实参定型后再推导。
- **M5 语言网站**：文档、教程、spec 渲染、examples 陈列、`dawn doc` 生成 API 文档。
  - 静态生成器用 Dawn 写（dogfood M4），产物 nginx 托管、零后端；
  - playground 在线试玩做二期（编译服务 + 沙箱限时）。
  - 验收：站点上线，且生成它的程序是 Dawn 写的。
- **M6 博客后端重写**（代码实现完成，2026-07-14；十三刀，backend-dawn ~4000 行 Dawn、
  46 单测全绿；仅剩生产切流的运维执行 + 7 天观察，见 dawnop-site 仓库 `backend-dawn/`）：
  真实生产 dogfood，故意排在自举前——真实项目会把 stdlib 与报错的痛点全逼出来，
  趁语言未冻结修起来便宜。**验收结论：整个博客后端（公开站 + 全套后台内容管理 + 搜索 +
  认证 + 文件管理 + 监控）在 Dawn 上跑通，与 FastAPI 参照实现逐字段对拍一致，路由表
  100% 覆盖（唯一缺口 `POST /api/fm/upload` 与 WebDAV 一并进 M6.5，同缺"二进制请求体"）。**
  - **痛点逼出的语言补强**（全部落进 spec，未加语法负担）：`--cp` 第三方 classpath
    （§9.1/§12.1）、`java_try` 异常屏障 + `catch_panic` 监督边界（§9.8）、`utf8_bytes`
    与不透明值收窄回具体引用形参（§9.5，让「取二进制体→透传」零拷贝）、嵌套类点式
    导入（§9.1）、`to_lower`/`to_upper`（§11）。**D8「互操作三件套」被真实项目验证够用**：
    sql/crypto/http/web/json 五套地基库全用 `use java` + 纯 Dawn 写成、留在应用层（未进
    语言 stdlib，印证「语言不加 async/web，靠互操作借 JVM 生态」的判断）。
  - **契约保真手法**：两端同一 SQLite 库副本 + 同 `SECRET_KEY`，逐端点 diff JSON；
    改七牛/发信等副作用端点用官方 SDK 造隔离前缀对象对拍再清理，生产数据不进测试库。
    JWT 与 PyJWT 双向互认（旧会话零失效）、jBCrypt 认 Python 的 `$2b$` 哈希（归一 `$2a$`）、
    三类七牛签名 + 腾讯 TC3 均对拍官方 SDK 逐字节。
  - Web 地基全走 `use java`，语言不加 async：HTTP 用 `com.sun.net.httpserver` +
    JVM 21 虚拟线程（每请求一线程，语言层零着色）；JSON 用 M4 的纯 Dawn 库；
    SQLite 走 JDBC 薄包装；JWT/bcrypt/七牛用现成 Java 库；
  - 前置「互操作三件套」**已落地**（2026-07-12，三刀 39507df/fdd44c2/后继，测试 892 项，
    spec §9.4–§9.6，决策记录见 D8）：SAM 转换、数组不透明直通、List 零拷贝桥。
    验收样例 = **playground runner**（M5 二期后台，Dawn 写），跑通后再动博客重写。
    spec 原 §9.4（现 §9.7）挡 SAM 的理由（native-image 免配置）已由 spike 排除
    （`scripts/spike-sam/`，2026-07-12）：ASM 生成的 invokedynamic + LambdaMetafactory
    适配 `Runnable` / 捕获型 `Supplier` / `HttpHandler` 三形态，接 `jdk.httpserver` +
    虚拟线程自请求，JVM 与 native 输出逐字节一致、零反射配置——LMF lambda 由
    native-image 构建期展开，边界可以放开；
  - 迁移策略：逐端点替换，nginx 按路由切流量；WebDAV 量大且走独立子域名，最后迁或留 Python。
  - 验收：Vue 前端不改一行指向 Dawn 后端，现有契约测试 + 端到端全绿。
- **M6 复盘 → 修复批次**（[`m6-retro.md`](m6-retro.md) 排优先级，进展见 [`m7-progress.md`](m7-progress.md)）：
  用真实生产后端的编码摩擦反推语言/库/框架补强。序 1（补 `find/take/drop/reverse` +
  字符串 `index_of`）、序 2（SQL 命名列取值）、序 3（web 框架 Route 开放记录 + 中间件路由
  tag 感知）已落地。**序 4「一等 `Bytes`」（2026-07-16，根因 1）**：设计定稿见
  [`bytes-design.md`](bytes-design.md)。决策——`Bytes` 运行期就是裸 `byte[]`（与不透明数组同
  表示、零间接），新增 `TBytes` 类型 + `utf8/decode/byte_len/byte_at/byte_slice/byte_index_of/
  as_bytes` 内建 + `++`/`==`/`Show`，`byte[]` 的 Java 返回落成 `Bytes`；**退役 `utf8_bytes`/
  `latin1_bytes`**，消灭全栈的 latin-1 字符串滥用与 `Request.raw`/`Response.bin` bolt-on
  （spec §9.5/§9.5.1/§11）。UFCS 让 `s.utf8()`/`b.decode(cs)` 免方法机制白得。1124 测试全绿。
- **M7 自举**：Dawn 编译 Dawn，压轴——自举后语言每改一处要同时伺候两个编译器，
  故放在语言基本冻结之后。
  - 分四刀（Lexer → Parser → Checker → CodeGen，ASM 走 `use java`），
    每刀用 golden 输出与 Kotlin 版对拍；
  - 三阶段自举链：stage0（Kotlin 版）编出 stage1（Dawn 写的编译器）→ stage1 编译自己
    得 stage2 → stage2 再编译自己得 stage3，**stage2 与 stage3 逐字节一致**即固定点；
  - Kotlin 版从此冻结为 bootstrap 种子（学 Go 保留 go1.4），不再演进。
  - 验收：固定点 + 全部测试经自举编译器跑通，JVM/native 输出一致。

两条横向轨道贯穿全程：**LSP** 随每个特性同步演进（M1 已验证节奏可行；
2026-07-12 补齐 completionProvider——作用域符号/内建/构造器/关键字 + 字符串注释
抑制 + `!` 触发 io，web 框架同刀撞出的 G1 字段直调/G2 类型别名/G3 刚性类型
参数三处语言缺口同日落地，spec §2.4/§2.6/§2.5）；
**验收样例先行**——每个里程碑动工前先把验收物写好放进仓库。

**trait v1**（2026-07-13，六刀落地，见 D9 与 [trait.md](trait.md)）：单参数
typeclass + 字典传递；`trait`/`impl`/`[T: Ord]` 语法、一致性 + 孤儿规则、
`< <= > >=` 桥接预置 `Ord`、`derive Ord`、`sort`/`sort_by`/`max`/`min`/
`max_by`/`min_by`；验收样例 `examples/traits.dawn`，教程 §15，spec §3.5；
测试 1094+ 项全绿，JVM/native 对拍一致。

**人体工学四件套**（2026-07-12，对 Kotlin/Rust/Scala 等 `[]`/推断/局部函数惯例
调研后定案，测试 973 项全绿）：① `[]` 下标——List/Map 断言语义（越界/缺键
panic），`get`/`map_get` 保持 Option 问询，comptime 支持 List 下标（spec §4.8）；
② `return` 提前返回——Never 类型表达式，作用域规则同 `?`（spec §4.9）；③ 局部
命名函数——块内 `fn name(...)`，可捕获/可递归/自尾调用成环，递归调用编译为
impl 方法 invokestatic 直调、自引用作值走闭包重建（spec §3.1、§12.4）；④ 私有
函数签名推断——非 pub 可省返回类型与效果，按调用图拓扑序推导，递归/`?`/`return`
须标注；const 检查拆两段（先登记类型后查初始化器）以便 const 调用推断函数
（spec §3.1）。web 框架/站点生成器同日 dogfood 换用 `[]`。
