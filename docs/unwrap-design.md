# 序 5 设计草案：互操作 Option 解包（后缀 `!`）

> 对应 [`m6-retro.md`](m6-retro.md) **根因 3**（🟠 Java 互操作把一切包进 Option → `.expect()` 满天飞）。
> 依 [`bytes-design.md`](bytes-design.md)（序 4）的先例：**动码前先出草案**。

## 一、问题

`backend-dawn/src/http.dawn` 一个文件里 13 处 `.expect(...)`，占位串毫无信息量：

```dawn
let uri = URI.create(url).expect("uri")
let base = HttpRequest.newBuilder().expect("b").uri(uri).expect("b-uri")
let nobody: BodyPublisher = BodyPublishers.noBody().expect("nobody")
let req = withHeaders.method("GET", nobody).expect("get").build().expect("req")
let resp = shared_client().send(req, BodyHandlers.ofByteArray().expect("bh")).expect("resp")
```

`"b-uri"`/`"bh"`/`"nobody"` 是被迫编造的字符串——**既不是错误原因，也不是修复提示**，
纯粹是为了让 `expect` 有第二个实参。真正的信息（哪一行、哪个方法返回了 None）反而没有。

## 二、复盘原方案 `@NonNull` —— 实测否决

复盘建议「互操作层区分 `@NonNull`（多数 JDK API 有注解）」。**这条假设是错的**，实测（GraalVM 21）：

| 方法 | `getAnnotations()` | `getAnnotatedReturnType().getAnnotations()` |
|---|---|---|
| `URI.create(String)`（永不 null） | `[]` | `[]` |
| `HttpRequest.newBuilder()`（永不 null） | `[]` | `[]` |
| `Base64.getEncoder()`（永不 null） | `[]` | `[]` |
| `String.trim()`（永不 null） | `[]` | `[]` |
| `Map.get(Object)`（**真·可空**） | `[]` | `[]` |

JDK 类**不携带运行期可见的可空性注解**（JDK 自身不用 JSR-305/JetBrains 注解；即便用了，
`CLASS` 保留期也读不到）。于是编译器**无从区分** `URI.create`（非空）与 `Map.get`（可空）——
两者反射出来一模一样。

而痛点 100% 在 JDK API 上（`URI`/`HttpRequest`/`Base64`/`Duration`）。注解方案只能惠及
「带 RUNTIME 注解的第三方 jar」，与痛点不相交。**故否决**，取复盘给的另一条路：`!` 后缀糖。

> 记录：`compiler/` 目前**零注解读取**（grep `getAnnotation`/`isAnnotationPresent` 无实质命中）。
> 反射对象本身是现成的（`Checker.kt:1593` 已把 `java.lang.reflect.Method` 挂到 AST 上），
> 将来若要支持带注解的第三方 jar，接线成本很低——但收益低，不进本轮。

## 三、方案：后缀 `!`

```dawn
expr!        # Option[T] -> T，None 则 panic（消息自动生成）
```

改写后：

```dawn
let uri = URI.create(url)!
let base = HttpRequest.newBuilder()!.uri(uri)!
let nobody: BodyPublisher = BodyPublishers.noBody()!
let req = withHeaders.method("GET", nobody)!.build()!
let resp = shared_client().send(req, BodyHandlers.ofByteArray()!)!
```

`!` 是 `expect` 的语法糖，**唯一区别是消息由编译器生成**（含位置与来源，见第七节）——
比手写 `"b-uri"` 信息量更大，却不用编。`expect(o, "自定义原因")` 保留不动：当你**确实有话要说**时用它。

## 四、为什么保留 Option 包装（不顺手取消）

一个诱人的替代方案是「Java 引用返回一律不包 Option」（像构造子那样）。**否决**，因为：

1. 无注解 ⇒ 编译器分不出 `URI.create`（非空）和 `Map.get`（可空）。不包 = **把 null 放进 Dawn**，
   后续对它调方法就是 NPE。
2. Dawn 的核心卖点正是「无运行期崩溃：错误要么编译期暴露，要么落在显式 `Result`/`Option` 分支」。
   放 null 进来等于在最基础的地方凿一个洞。
3. 复盘自己的结论（第七节）：**「Dawn 的问题不是"管得太多"，而是几个地方"省得太狠"。M7 的方向应是
   补齐被省掉的基础能力，而非放松已被证明有效的严格性。」** 取消包装恰恰是放松严格性。

**结论**：留住 Option（安全），砍掉噪音（人体工学）。`!` 精确地只做后者。

## 五、构造子/方法「不一致」——澄清为**有原则的区分**

复盘把「构造子不包 Option、实例方法包」列为「两套规则加重心智负担」。重新审视后认为
**这不是缺陷，是正确的**：

- JLS 保证 `new` 表达式**永不**返回 null。构造子不包 Option 是**有依据的**，不是随意豁免。
- 实例方法**可以**返回 null，且（第二节）无法静态区分，故必须包。

所以规则其实只有一句、可教：**「Java 构造子直接给你对象；Java 方法给你 `Option`，用 `!` 解包
（或 `match` 好好处理）」**。本轮不改这个区分，只在 spec 里把「为什么」写清楚。

> 补充证据：构造子路径（`Checker.kt:1559-1561` + `CodeGen.kt:3630`）已经是「不包装的 Java 值
> 在全流水线正常流动」的现成活证——`!` 的产物走的是同一条路。

## 六、语法与冲突分析

`!` 在 Dawn 里已被占用于**效果标注**（`fn f() -> T !io`，spec §2「效果变量：`!` 后接 `[a-z]...`」）。
逐条核对**无冲突**：

| 冲突面 | 结论 |
|---|---|
| `!=`（不等） | Lexer 走**两字符最大匹配**（`Lexer.kt:443-444`：`"!=" -> NEQ`）**先于**单字符 `'!' -> BANG`（`:473`）。`x! != v` 正确切分；`x!=v` 仍读作 `x != v`（想解包再比较须写空格，同其他语言）。 |
| 布尔取反 | Dawn 用**关键字 `not`**（`Token.kt:61`、`Parser.kt:724`），不占 `!`。表达式前缀位空闲。 |
| 效果标注 | `BANG` 在 parser 里**只有一个使用点**（`Parser.kt:515`，解析 `->` 之后的效果），属**签名语法**；`!` 后缀在**表达式语法**。两者上下文不相交（`-> T !io = expr!` 能唯一解析）。 |

**结合性/优先级**：后缀，与 `.`/`[]`/调用同级、左结合 —— `a()!.b()!` = `((a()!).b())!`。
插入点天然：`Parser.kt` 后缀循环已是 `when { LBRACKET -> …; DOT -> …; else -> return e }`，
加一个 `BANG ->` 分支即可，与现有 case 完全平行。

## 七、语义与自动消息

- **类型**：`expr!` 要求 `expr: Option[T]`，产出 `T`。非 Option 报错：
  ``error: `!` expects an `Option[T]`, found `Int` `` + hint「remove the `!`」。
- **效果**：纯（`expect` 本身 `Eff.Pure`，`Types.kt:403`）。`!` 不引入效果。
- **运行期**：与 `expect` 同——`INSTANCEOF Option$Some` 不中则 `NEW Panic; ATHROW`。

**消息格式**（编译期生成的常量串）：

```
unwrapped None from HttpRequest.newBuilder() at src/http.dawn:23
```

- 来源描述：操作数是 `MethodCall` 时取 `Recv.method()`；其余情形省略该子句。
- 位置：`<srcPath>:<line>`。

**位置信息的取得**（唯一需要新接线的地方）：`CodeGen` **没有**任何行号设施
（无 `visitLineNumber`/`visitSource`），`Diagnostic.render(file)` 是在**渲染时**才拿到 `SourceFile`，
故 `Checker` 手里只有 `srcPath`（路径）没有文本、算不出行号。
方案：给 `Checker` 加**可选**参数 `srcText: String? = null`，在 check 期把消息算好、
挂到 AST 节点上（沿用 `e.javaMethod` 那套「checker 标注 / codegen 消费」），codegen 只读常量。
构造点仅 **2 处**（`Analyze.kt:37,152`），且默认 `null` 时**降级为不带行号**（不破坏任何测试）。

## 八、落地点（与序 4 同构）

1. **`ast/Ast.kt`**：新增 `Unwrap(operand: Expr, span: Span)` 节点 + `var panicMsg: String?`（checker 填）。
2. **`parse/Parser.kt`**：后缀循环加 `BANG ->` 分支。
3. **`check/Checker.kt`**：`Unwrap` 分支——要求 `Option[T]`、产出 `T`、算 `panicMsg`；
   加可选 `srcText` 参数（第七节）。
4. **`codegen/CodeGen.kt`**：`Unwrap` 分支——复用 `expect` 的 `INSTANCEOF`/`Panic` 序列，
   消息取 `panicMsg` 常量。
5. **`fmt/Formatter.kt`**：打印后缀 `!`（不加空格）。
6. **`lsp/`**（`AstQuery`/`Completion`）：新节点需能被遍历（不崩）。
7. **`docs/spec.md`**：表达式/操作符处定义 `!`；§9.2 补「为什么方法包、构造子不包」的依据
   （JLS + 无注解实测），并指向 `!`。
8. **测试**：`UnwrapTest.kt`（类型、非 Option 报错、panic 消息、`x! != v` 切分）；
   golden run（`unwrap_postfix.dawn`）+ golden errors（`unwrap_not_option.dawn/.err`）。

> `!` 是**语法**不是内建，故 **不进** `Types.kt` 的 `BUILTINS`、**不需要** `Doc.kt` 分组
> （`DocCmdTest` 要求每个内建都归组——这条不适用）。

## 九、后端迁移（`dawnop-site/backend-dawn`）

有界替换：`.expect("<占位串>")` → `!`。主战场 `src/http.dawn`（13 处）；
`crypto.dawn`/`qiniu_*.dawn`/`tencent_*.dawn`/`webdav.dawn`/`web/server.dawn` 等处的
Java 互操作 `.expect` 一并扫。

**判据**：`.expect` 的字符串**是不是占位串**。
- 占位串（`"b-uri"`/`"bh"`/`"uri"`）→ 换 `!`。
- **有真实语义**的（如 `.expect("request body")` 这类当"错误说明"用的）→ **保留 `expect`**，
  它正是为此存在。

验收：`build.sh` 全绿（58 测试）+ jar 起服务冒烟。

## 十、不做的（记录理由）

- **`Result[T,E]` 的 `!`**：本轮只解 Option。Result 有 `?` 传播，痛点不在那儿；范围控制。
- **`@NonNull` 第三方 jar 识别**：第二节——与痛点不相交，接线成本虽低但收益低。
- **取消 Option 包装**：第四节——违背 Dawn 的严格性内核与复盘自身结论。
- **构造子/方法统一**：第五节——区分是有原则的，只补文档不改行为。
- **`!` 的 comptime 折叠**：同序 4 的 `as_bytes`（有意跳过）；无常量 Option 场景。
