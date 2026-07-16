# 设计草案：一等 `Bytes` 类型（M7 序 4，根因 1）

> 输入：[`m6-retro.md`](m6-retro.md) 根因 1「没有一等 `byte[]`，String 不能自己变字节」+
> 第六节优先级表序 4。目标：让字节数组成为**可命名、可传参、可存储**的一等类型，回收
> `utf8_bytes`/`latin1_bytes` hack、消灭全栈的 ISO-8859-1 字符串滥用、简化 web 框架的
> `Request.raw`/`Response.bin` bolt-on，并为将来的流式 I/O 铺路。
>
> 本文件是**动码前的设计定稿**。实现分两仓：语言本体 `dawn-lang/`（编译器 Kotlin），
> 后端迁移 `dawnop-site/backend-dawn/`。

## 0. 现状与问题（一句话）

今天 `byte[]` 是 `Type.TJava("[B")`——**故意不可命名**的不透明直通值（spec §9.5）：
只能作单个函数体内的 `Object` 存活，不能进签名、不能索引、不能比较。于是二进制数据被迫
「借道字符串」：`utf8_bytes`/`latin1_bytes` 两个内建把 String 桥成不透明 `byte[]`，
所有二进制体先 `String.new(bytes,"ISO-8859-1")` 解成 latin-1 串（0..255 一一映射字节）处理、
再 `latin1_bytes` 编回。`read_body` 因此把同一份 bytes 解码两遍（UTF-8 + latin-1），
`Request` 多背一个 `raw: String`、`Response` 多背一个 `bin: Option[Object]`。

## 1. 核心决策

### 决策 A：`Bytes` 的运行期表示 = 裸 `byte[]`（`[B`），不包装

编译器新增 `Type.TBytes`，运行期就是 JVM `[B`——与现在的不透明 `byte[]` **同一表示**，
零额外分配、零间接。理由：
- 与代码库既有风格一致（String=`java.lang.String`、List=`ArrayList`，都直接用 JVM 类型，
  只有 tuple 因需跨任意元数的结构相等才单独 emit 包装类）。
- `Bytes` 是**载荷**（I/O 体、crypto 输入、multipart 内容），要 slice/concat/index，
  不做 Map/Set 键——不需要结构化 hashCode。
- 不透明 `byte[]` ↔ `Bytes` 的转换在运行期是**恒等**（都是 `[B`），只是类型系统层面
  「从不可命名变可命名」，无字节码代价。

**代价（明确记录）**：`byte[]` 的 JVM `equals`/`hashCode` 是**引用同一性**。故：
- `==`/`!=` 我们**特判为结构相等**（emit `java.util.Arrays.equals`），见决策 C。
- 但 `Bytes` **不适合作 Map/Set 键**（容器用的是值自带的 `hashCode`，即引用同一性，
  与结构化 `==` 不一致）。v1 **不**在 checker 里硬禁（省改动面），而是**文档明确劝退**；
  真有需要用键时改用 `decode` 出的 String 或 hex。若日后证明是坑，再加 checker 守卫。

### 决策 B：String↔Bytes API = 自由函数 + UFCS（不引入方法机制）

Dawn 的 `x.f(a)` 是 **UFCS 糖**（`Ast.kt:257`：desugar 成 `f(x,a)`）。故 retro 想要的
`s.utf8()` / `b.decode(cs)` 直接由自由内建 `utf8(s)` / `decode(b, cs)` 得到，
两种写法都能用，**不需要**给 String/Bytes 加任何「方法」机制。也与既有 String 内建
（`substring(s,i,j)`、`code_points(s)` 都是自由函数）一致。

### 决策 C：v1 能力边界（够用即止，明确划线）

| 能力 | v1 | 说明 |
|---|---|---|
| 进签名 / 传参 / 存进 record | ✅ | 核心目的 |
| `utf8(String)->Bytes` 构造 | ✅ | 替 `utf8_bytes` |
| `decode(Bytes,charset)->String` | ✅ | 替 `String.new(bytes,cs)` |
| `byte_len` / `byte_at` / `byte_slice` / `byte_index_of` | ✅ | multipart 解析 + 通用 |
| `++` 拼接 | ✅ | 扩展既有操作符到 Bytes |
| `==`/`!=` 结构相等 | ✅ | emit `Arrays.equals` |
| `Show`（`derive Show` 里含 Bytes） | ✅ | 渲染为摘要 `<N bytes>`，保住 `Request`/`Response` 的 derive Show |
| Java `byte[]` 返回 → `Bytes`、`Bytes` → Java `byte[]` 参 | ✅ | 互操作桥 |
| comptime 折叠（const 里用 Bytes） | ❌ | 需 `CValue.VBytes`；后端无此需求，触碰即报「not available at comptime」（同今日 byte 内建） |
| 作 bare 一等函数值（`map(xs, utf8)`） | ❌ | 用 lambda（`fn(x)=>utf8(x)`）；同今日 byte 内建无 value-handle |
| 作 Map/Set 键 | ⚠️ | 引用同一性，文档劝退（见决策 A） |
| 索引糖 `b[i]` | ❌ | 用 `byte_at(b,i)`；`checkIndex` 不动 |
| 通用 `encode(s,charset)->Bytes` | ❌ | 后端只需 utf8；YAGNI，日后可加 |
| `Request`/`Response` 正文彻底只留 Bytes | ❌ | 见决策 D（保 `body: String` 的文本人体工学） |

跳过 comptime 折叠与 value-handle 各省一处 CodeGen/Comptime 改动、且与现有 byte 内建行为一致，
是有意的最小化，不是遗漏。

### 决策 D：web 框架迁移走「有界」路线，不强推全 Bytes 正文

- **`Request`**：`body: String` **保留**（UTF-8，多数 handler 直接拿去 parse JSON/form，
  改成 Bytes 会波及每个 POST handler）。把 `raw: String`（latin-1 副本）**改成 `raw: Bytes`**
  （真·原始字节）。`read_body` 从「解两遍」变「解一遍 UTF-8 + 留字节数组」→ 返回 `(String, Bytes)`。
- **`Response`**：`body: String` 保留（`json_response`/`text` 等都建 String 正文）。把
  `bin: Option[Object]` **改成 `bin: Option[Bytes]`**。`binary(...)` 收 `Bytes`。因 Bytes 可 Show，
  `Response` 可重新 `derive Show`（此前因 `Object` 不可 Show 才没 derive）。
- 二进制 handler（multipart 上传、WebDAV PUT）从读 `req.raw`(latin-1 String) 改读 `req.raw`(Bytes)。

如此**消灭 latin-1 hack（彻底）、消灭第二次 latin-1 解码、`bin` 从不透明 Object 变 Bytes**，
但**不动**几十个文本 handler。「正文只留一个 Bytes 字段 + `req.text()` 惰性解码」是更纯的形态，
但要改每个文本 handler，留作后续（与流式一起做更顺）。

## 2. 类型语义

- `Bytes`：不可变字节序列，元素是 0..255 的字节；`byte_at` 返回 `Int`（无符号，0..255）。
- 相等：结构（逐字节）。顺序（`<`）：v1 不支持（无需求）。
- 空：`utf8("")` 得空 Bytes；无需专门字面量。
- 越界策略：`byte_slice(b,start,end)` 把 start/end **clamp 到 [0,len]**、`start>end` 得空
  （宽容，便于解析；与序 1 的 take/drop clamp 一致，而非 substring 的 panic）。
  `byte_at(b,i)` 越界 **panic**（编程错误，同 List 索引）。
- `byte_index_of(b, needle, from)`：从字节下标 `from` 起找 `needle` 首次出现，返回字节下标
  `Option[Int]`；`from` clamp 到 [0,len]；空 `needle` → `Some(min(from,len))`（对齐序 1 字符串 index_of）。

## 3. API（内建清单）

```
utf8(s: String) -> Bytes                                   # 文本→字节（UTF-8）；替 utf8_bytes
decode(b: Bytes, charset: String) -> String                # 字节→文本；替 String.new(bytes,cs)
byte_len(b: Bytes) -> Int
byte_at(b: Bytes, i: Int) -> Int                           # 0..255；越界 panic
byte_slice(b: Bytes, start: Int, end: Int) -> Bytes        # clamp；[start,end)
byte_index_of(b: Bytes, needle: Bytes, from: Int) -> Option[Int]
# 操作符（非具名内建）：Bytes ++ Bytes -> Bytes ；Bytes == / != Bytes（结构）
```

UFCS 写法：`s.utf8()`、`b.decode("UTF-8")`、`b.byte_len()`、`b.byte_slice(0, n)`、
`b.byte_index_of(sep, 0)`。

`utf8_bytes` / `latin1_bytes` **退役**（删签名/dispatch/doc）。`latin1_bytes` 的唯一用途
（latin-1 串→精确字节）随 latin-1 串本身消失而消失。

## 4. 编译器落地（精确落点）

运行期辅助类新增 `dawn/rt/Bytes`（仿 `genStringsClass`），承载 `concat/slice/indexOf/at/eq/show`
的静态方法（都吃/吐裸 `[B`）。

### 4.1 `check/Types.kt`
1. `sealed class Type` 加 `object TBytes : Type("Bytes")`（挨着 `TString`，`:92`）。
2. `Type.named`（`:170`）加 `"Bytes" -> TBytes`。
3. `subst`（`:182`）：nullary，走 `else -> t`，无需改（确认即可）。
4. `BUILTINS`（`:338-503`）：删 `utf8_bytes`/`latin1_bytes`（`:443-451`），加 6 个新 `FnSig`
   （`utf8/decode/byte_len/byte_at/byte_slice/byte_index_of`，`byte_index_of` 返回 `TAdt(OPTION, [TInt])`）。

### 4.2 `check/Checker.kt`
5. `builtinTypeNames`（`:1167`）加 `"Bytes"`（错误提示）。
6. `resolveType`（`:995-1041`）：走 `Type.named` 即可（步骤 2），确认 `ref.name=="Bytes"` 能解析。
7. `isShowable`/`isShowableField`（`:1735-1753`）：`TBytes -> true`。
8. `checkBinOp`（`:2244-2291`）：`++` 分支（`:2263`/`:2268`）允许 `TBytes ++ TBytes -> TBytes`；
   `==`/`!=`（`:2271`）已按 `lt==rt` 通过（同类型即可），只需保证 codegen 侧结构相等。
9. `paramScore`（`checkJavaCall`，`:1433-1476`）：加 `TBytes` 臂——Dawn `Bytes` 可传给 Java `byte[]`
   形参（`p.cls == ByteArray`），仿 `TList` 桥（`:1470`）。
10. `mapJavaReturn`（`:1593-1606`）：Java 方法返回具体 `byte[]` → `TBytes`（不再是不透明 `TJava`）。
11. `assignable`（`:1210-1214`）：**不透明** `TJava(java.lang.Object)`（擦除泛型返回，如
    `HttpResponse.body()`）可赋给 `TBytes`——codegen 侧 `CHECKCAST "[B"`。这解决 `fetch_bytes` 的
    `resp.body()`（编译期 Object、运行期 byte[]）落成 `Bytes`。
12. `isConcrete`：确保 `TBytes` 算 concrete（grep 校验）。

### 4.3 `codegen/CodeGen.kt`
13. `descOf`（`:532`）：`TBytes -> "[B"`。
14. `slotsOf`（`:590`）=1、`isRef`（`:597`）=true、`boxedDescOf`（`:655`）：加 `TBytes`（引用）。
15. `unerase`（`:614`）：`TBytes -> CHECKCAST "[B"`（从擦除 Object 恢复；亦服务决策 11 的
    Object→Bytes 赋值）。`box`（`:604`）：引用，恒等。
16. `emitShared`（`:192`）新增 `genBytesClass()`：`dawn/rt/Bytes.{concat,slice,indexOf,at,eq,show}`。
17. `genBuiltinCall`（`:3928-4231`）：加 6 个新 dispatch 臂；`utf8` 内联
    `String.getBytes(UTF_8)`（复用退役的 utf8_bytes 字节码），`decode` 内联
    `new String([B, charset)`，其余 `INVOKESTATIC dawn/rt/Bytes.*`。删 `utf8_bytes`/`latin1_bytes` 臂。
18. `++` 的 codegen（binop `BinOp.ADD`/concat 路径，`:4264` 附近的类型分派）：`TBytes` →
    `INVOKESTATIC dawn/rt/Bytes.concat`。
19. `genEquality`（`:2695`）：`TBytes` → `INVOKESTATIC java/util/Arrays.equals([B[B)Z`（`!=` 取反）。
20. `dawn/rt/Show`：加 Bytes 渲染 `<${len} bytes>`；`isShowable` 打开后，record 的 derive-Show
    对 Bytes 字段调它（确认 `genShow`/`showField` 的类型分派处，随 grep 定位）。
21. `mapJavaReturn` 改了后，`String.new(bytes,...)`（现取 opaque）改由 `decode` 内建替代；
    `adaptJavaArg`（`:3433`）无需改（`Bytes` 传 Java `byte[]` 参走既有 CHECKCAST，`descOf` 已给 `[B`）。

### 4.4 `check/Comptime.kt` / `cli/Doc.kt`
22. `Comptime.callBuiltin`（`:327-432`）：6 个新内建**不加折叠**臂 → 落 `else` 报「not available at
    comptime」（可接受，v1 边界）。
23. `Doc.BUILTIN_GROUPS`（`:150-237`）：删 `utf8_bytes`/`latin1_bytes` 项、加 6 个新内建到某组
    （如新增「bytes」组或并入现有「strings/io」组）——**DocCmdTest 强制每个 builtin 恰好归组一次**，漏则测试红。

### 4.5 spec / 文档
24. `docs/spec.md` §9.5（`:665-712`,`:820-823`）：改写——数组仍是不可命名不透明直通，但新增
    一等 `Bytes`；§11 内建表加 6 个新内建、删 2 个旧的。`docs/design.md` 记里程碑决策。

## 5. 后端迁移（`backend-dawn/`，有界清单）

> 依赖：先出新 `dawn.jar`。次序：框架核心 → http → multipart → qiniu → crypto/签名 → handler。

- **web/server.dawn**：`read_body -> (String, Bytes)`（`String.new(bytes,"UTF-8")` + 裸 bytes 作
  `Bytes`，删第二次 latin-1 解码）；`build_request` 绑 `raw: Bytes`；`write_response` 的 `match r.bin`
  写 `out.write(bytes)`（`bytes: Bytes` 传 Java `byte[]` 参，既有 CHECKCAST）。
- **web/types.dawn**：`Request.raw: String -> Bytes`；`Response.bin: Option[Object] -> Option[Bytes]`；
  `binary(bytes: Object) -> binary(bytes: Bytes)`；删 `use java "java.lang.Object"`；`Response derive Show`。
- **http.dawn**：`fetch_bytes -> Result[Bytes, String]`（`resp.body()` 的 Object 落 Bytes，决策 11）；
  `post_latin1(body_l1: String)` → `post(body: Bytes)`（删 `latin1_bytes`）；删 Object 导入。
- **multipart.dawn**：`Part.content: Bytes`；`parse_multipart(body: Bytes, boundary)` 用
  `byte_index_of`/`byte_slice`/`byte_len` 切分；文本字段 `decode(part.content,"UTF-8")`。
- **qiniu_rs.dawn**：`upload_bytes(content: Bytes)`；`multipart(...)` 用 `Bytes ++ Bytes` 拼；
  `post_latin1`→`post`；与 `upload_text` 归一（文本先 `utf8`）。
- **crypto.dawn / tencent_sign.dawn**：13 处 `utf8_bytes(x)` → `utf8(x)`；`String.new(bytes,"UTF-8")`
  （`crypto.dawn:56`）→ `decode(bytes,"UTF-8")`；base64/digest 参/返回改 `Bytes`。
  `MessageDigest.isEqual(Bytes, Bytes)`（常时比较）走 Java `byte[]` 参桥。
- **api_fm.dawn**：`parse_multipart(req.raw, b)`（req.raw 现 Bytes）；`fp.content: Bytes`、
  文本字段 `.decode("UTF-8")`、大小 `.byte_len()`；删 `utf8_of`。content 代理 `fetch_bytes`(Bytes)→`binary`。
- **webdav.dawn**：PUT `content = req.raw`(Bytes)→`upload_bytes`、大小 `.byte_len()`；
  serve_file `fetch_bytes`(Bytes)→`binary`；`b64_decode` 的 `String.new`→`decode(_,"UTF-8")`。

预计消除：~15 处 `utf8_bytes`/`latin1_bytes`、5 处 `String.new` 双解码、`Request.raw` latin-1 语义、
`Response.bin` 的 `Object`、`post_latin1`、`utf8_of`，及散在 6 文件的 latin-1 注意事项。

## 6. 测试计划

**dawn-lang（Kotlin + golden）**：
- 新增 `BytesTest.kt`：`utf8`+`decode` UTF-8 往返、跨字符集（`decode(utf8("héllo"),"UTF-8")`）、
  高位字节精确（构造含 0x00..0xFF 的 Bytes 经 slice/concat/at 逐字节核对，替代旧
  `latin1_bytes round-trips` 用例）、`byte_index_of`（含 from 偏移、未命中 None、空 needle）、
  `byte_slice` clamp、`==` 结构相等、`Bytes ++ Bytes`、`Bytes` 传 Java `byte[]` 参
  （`ByteArrayOutputStream.write` + `Arrays.equals` 核验，改造 `JavaInteropTest` 的 G6 用例）。
- golden `run/`：一个把文本 utf8→字节→slice→decode 打印的例子。
- `DocCmdTest` 自动校验新内建归组、旧内建移除。
- 删/改引用 `utf8_bytes`/`latin1_bytes` 的既有测试（`JavaInteropTest.kt:66,88-125`）。
- 目标：`gradle :compiler:test` 全绿（现 1117，预计净 +数条）。

**backend-dawn**：`build.sh` 全绿；`http`/`crypto`/`qiniu_sign`/`tencent_sign`/`multipart` 既有单测
对拍不变（crypto 向量、签名逐字节仍须与 Python/ SDK 一致——这是 Bytes 正确性的强校验）；
运行期冒烟 + 三套 contract 对拍留部署时（尤其 fm/upload 二进制字节精确、WebDAV PUT 往返 sha 一致）。

## 7. 风险与缓解

- **crypto/签名字节回归**：utf8_bytes→utf8 是同字节码（`String.getBytes(UTF_8)`），理论零差异；
  由既有向量/逐字节对拍守护。
- **`==` 结构 vs Map 键同一性不一致**：决策 A 已记；文档劝退，v1 不硬禁。
- **`resp.body()` Object→Bytes 赋值**（决策 11）：是本设计唯一「新的隐式收窄」，仿 §9.5 既有
  Object→具体引用参数，加一条 `assignable` + `unerase` CHECKCAST；用 `JavaInteropTest` 专门覆盖。
- **DocCmdTest / 穷尽 `when(t:Type)`**：新增 `TBytes` 可能触发若干 `when` 的 else 或穷尽性检查
  （`Traits.kt`/`Exhaustive.kt`/`lsp/`）——实现时 grep 全部 `is TJava`/`when (.*: Type)` 补臂。

## 8. 交付物

1. 语言本体：`Bytes` 类型 + 6 内建 + `++`/`==`/Show + 互操作桥；`dawn.jar` 重建；`:compiler:test` 全绿。
2. 后端：按 §5 迁移；`build.sh` 全绿 + 冒烟。
3. 文档：`spec.md`/`design.md`/`m7-progress.md`（序 4 完成）+ 本草案标注「已实现」。
4. 两仓提交（不加 Co-Authored-By），按需推送。
