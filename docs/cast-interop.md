# `cast[T]`：统一的 interop 认领原语

> 语言层设计，**先文档、后实现**。目标：把「从擦除的 Java `Object` 认领回具体类型」从
> **一类型一 builtin**（`as_bytes`、将来的 `as_input_stream`…）收敛成**一个泛型内建 `cast`**
> （概念上是 `cast[T]`；v1 surface 写 `cast(x)`、T 由期望类型定，见 §四）。
> 背景与更大图景见 [`builtins-to-stdlib.md`](builtins-to-stdlib.md)（本文是「止住 as_XXX 家族增长」那一步）。

## 一、问题：JVM 泛型擦除

`<T> T get()` 编译到字节码就是 `Object get()`。任何调**返回类型是类型变量**的 Java 方法
（`Optional.get()`、`HttpResponse.body()`、`List.get()`），Dawn 侧拿回来的都是不透明 `Object`，
静态类型在字节码层已丢。恢复的唯一手段是 **`CHECKCAST`**：把 `Object` 认领成某个具体类，
失败抛 `ClassCastException`。

现状 `as_bytes` 就是「写死认领 `byte[]` 的一条 CHECKCAST」：

```kotlin
// check/Types.kt:471 —— 单态：Object -> Bytes，无类型参数
FnSig("as_bytes", listOf(Type.TJava("java.lang.Object", …)), listOf("x"),
      Type.TBytes, Eff.Pure, isBuiltin = true)
// codegen/CodeGen.kt:4438 —— 硬编码目标类
"as_bytes" -> { genExpr(e.args[0]); mv.visitTypeInsn(CHECKCAST, "[B"); true }
```

**问题**：认领 `InputStream` 就得再加 `as_input_stream`，认领 `Reader` 再加一个……
每开一个 interop 洞就改一次编译器。这次流式响应本来要加 `as_input_stream`，
临时靠「挑非泛型 API（`URLConnection.getInputStream()` 返回具体 `InputStream`）」绕过了，
但那不通用——不是每个洞都恰好有非泛型替身。

## 二、结论：一个泛型 `cast` 取代所有 `as_XXX`

```
cast(x: <opaque Object>) -> T             # T 由期望类型定；Pure；失败抛 ClassCastException（可被 java_try 接住）
```

**v1 surface = 期望类型驱动**：**不写显式 `[T]`**，T 从调用点的**期望类型**（let 注解 / 字段类型 /
返回类型 / 实参位）解析，编译器据此发 `CHECKCAST erasure(T)`：

```dawn
let s: InputStream = cast(resp.body()!)   # T = InputStream，来自注解
let b: Bytes = cast(opt.get()!)           # as_bytes 的位置
```

显式 `cast[T](x)` 形式**推迟**（理由见 §四）：cast 的 T 恒是**单个具体引用类**，注解几乎总在手边，
故 v1 不必造「调用点类型应用 `f[T](args)` 语法 + 与下标 `xs[i]` 消歧」那一整套。

### 修正一个误解：「泛型 cast 不可能」不成立

早先的结论是「T 运行时擦除，发不出 per-class CHECKCAST，所以 `as_bytes` 只能单态」。这**混了两件事**：

- ❌ **T 是外层函数自己的类型参数**（codegen 时未知）——确实发不出具体 CHECKCAST。
  但 interop 里从不会「把 Object 认领成一个连自己都不知道是什么的 T」，这是废场景。
- ✅ **T 在调用点由期望类型解析成具体类**——编译器当场就知道要发 `CHECKCAST java/io/InputStream`。
  这**完全可发**。`as_bytes` 能 work 正因 `Bytes` 具体；`cast` 对**任何被期望类型定死的具体 T** 一样。

Dawn 已有**同构先例**：`map_empty`、`set_empty`、`java_try`、`catch_panic` 都靠期望类型解析结果类型
（**实际用法从不写显式 `[T]`**：`let m: Map[String, Int] = map_empty()`、`java_try(fn() => 1)`）。
`cast` 同款，只多一步——codegen 用解析后的 T 发 CHECKCAST，而**这个 T 已现成落在 Call 节点的
`Expr.type` 上**（checker 填，`ast/Ast.kt:222`）。

## 三、语义

- **签名**：`cast(x) -> T`（`FnSig` 里 result = 类型变量 `t`、`typeParams = [t]`，同 `catch_panic`），
  `x` 形参类型 `java.lang.Object`（吃任何不透明值），`Eff.Pure`。
- **T 从哪来**：由**期望类型**解析（let 注解 / 字段 / 返回 / 实参位），落在 Call 节点 `Expr.type`。
  **无期望类型可依**（如 `let a = cast(x)` 无注解、或 cast 孤立于无类型上下文的表达式中，`Expr.type`
  仍是未解析的 `TVar`）→ **编译期报错**「cast 目标类型未知，请加注解」。这是唯一的使用约束。
- **T 的约束**：解析出的 T 必须是 **CHECKCAST 能落地的引用类型**：
  - `TJava(fqcn)` → 内部名 `fqcn.replace('.', '/')`（如 `java/io/InputStream`）。
  - `Bytes` → `[B`（数组类型，CHECKCAST 直接吃数组描述符）。
  - `String` → `java/lang/String`。
  - **拒绝**基本类型 `Int`/`Float`/`Bool`（CHECKCAST 不能目标 primitive），以及仍是抽象类型变量的 T
    —— 编译期报错，提示「cast 的目标必须是具体引用类型」。
  - Dawn ADT 作为目标：技术上可 CHECKCAST 到其生成类，但**首版不开**（用例都是 Java 互操作类型），
    需要时再放开。
- **失败行为**：类型不符时 CHECKCAST 抛 `ClassCastException`——**loud failure**，和现有 `as_bytes`
  的语义一致（「像任何不透明窄化一样大声失败」）。它是 JVM 运行时异常，可被 `java_try`/`catch_panic`
  收成 `Result`。**不是内存 unsafe**（是受检 checkcast，干净抛异常，非 UB）。
- **纯度**：`Pure`，同 `as_bytes`（CHECKCAST 无副作用；抛异常不算效果，与 `panic` 同类）。

## 四、命名与 surface：叫 `cast`、v1 期望类型驱动（已定，记录理由）

### 4.1 名字为何是 `cast`（而非 `as` 关键字）

- **`as` 已被模块系统预留**：`spec.md` 明写「无 `as` 重命名（v0.1）」——`use X as Y` 导入改名是
  计划中的特性。抢 `as` 当 cast 关键字会和它撞。
- **它是罕见 FFI 逃生阀，不是高频构造**：关键字靠普遍性挣语法位（`if`/`match`/`fn`）；
  cast 只出现在 interop 胶水的个位数调用点。Scala 甚至**故意**把它做成又长又丑的方法
  `asInstanceOf[T]`，就是要让 cast 显眼、少用——terse 的 `as` 关键字反诱导滥用。
- **和 `as_bytes` 同类**：本来就在泛化一个**函数**，`cast` 心智模型不跳类别。
- **命名取舍**：不用 `unsafe_cast`/`checkcast`——它不是内存 unsafe（是受检 CHECKCAST、干净抛异常）、
  且总裹在 `java_try` 里危险已收敛，`unsafe_` 言过其实。取 **`cast`**：诚实（确是一次运行时 checked cast）、
  风格对齐现有内建。

### 4.2 v1 为何期望类型驱动 `cast(x)`，而非显式 `cast[T](x)`

调研过显式 `[T]` 那条路（记录结论，免得后人重走）：

- **它要新造语法 + 消歧**：Dawn 今天没有「调用点类型应用 `f[T](args)`」——`postfixExpr`（`parse/Parser.kt:752`）
  把 `ident[...]` 一律当**下标** `xs[i]`。加显式 `[T]` 得引入 `NAME[类型](args)` 解析并与下标消歧。
- **消歧可解、但没必要现在做**：Dawn 有 Go 没有的红利——类型名词法上大写（`lex/Lexer.kt:119`
  `isUpperCase → TYPEIDENT`）、调用只作用于名字（`Call.callee: String`）、下标结果不可调
  （`postfixExpr` 无 `(` 后缀，`a[i](args)` 今天就非法）。故消歧靠「大写词法类 + callee 泛型性」可判
  （沿用 Go 的「推到类型检查期按 base 是否泛型定」）。**但这是一整个特性**，cast 用不上。
- **期望类型驱动是现成机制、且零新增管线**：全仓泛型调用（`map_empty`/`java_try`）**本就靠期望类型推**、
  从不写 `[T]`；而 checker 已把每个表达式的推断类型填在 `Expr.type`（`ast/Ast.kt:222`）——codegen 直接读它
  发 CHECKCAST，**连 AST 字段都不用加**。cast 点又几乎总有期望类型（你 cast 就是为了当某个已知类型用）。
- **代价可接受**：无期望类型的位置写个注解 `let s: InputStream = cast(x)`——读起来像 Scala 的类型 ascription，
  清晰不啰嗦。

**显式 `cast[T](x)` 推迟、且推迟不留债**：真等到出现「期望类型推不动、必须手写类型实参」的复杂泛型时，
再把 `f[T]` + 上面的 Go 式消歧作为**独立特性**加进来——那时注解驱动的老代码一行不改，向前兼容。

## 五、落地点（期望类型驱动，footprint 很小）

**无 parser 改动、无 `typeArgs` 字段、无消歧**——那一整条链子全省。只碰三处 + spec：

| 文件 | 现状（`as_bytes`） | 改动 |
|---|---|---|
| `check/Types.kt`（as_bytes 在 :471） | 单态 `FnSig(Object→Bytes)` | 加 `FnSig("cast", [Object], result=t, typeParams=[t], Eff.Pure)`（一行，同构 `catch_panic`） |
| `check/Checker.kt` | — | cast 调用检查后：`Expr.type` 若仍是 `TVar` → 报「cast 目标类型未知，请加注解」；若是 primitive（`Int/Float/Bool`）→ 报「目标须是引用类型」 |
| `codegen/CodeGen.kt:4438` | `"as_bytes"` 分支：`CHECKCAST [B` 写死 | **删该分支**，换成 `"cast"` 分支：**读 Call 节点 `Expr.type`**（checker 已填的解析后 T）→ 求内部名/描述符 → `visitTypeInsn(CHECKCAST, …)`。目标为 `Bytes` 时它发的就是同一条 `CHECKCAST [B`，故涵盖旧 as_bytes |
| `cli/Doc.kt:203` / `spec.md` §9.5,§11 | as_bytes 条目 | **删 as_bytes**、加 `cast` 文档串 + 记语义/T 约束 |

**「实例化 T 在 codegen 可见」已由现成机制解决**：checker 把每个表达式的推断类型填在 `Expr.type`
（`ast/Ast.kt:222`）。对 `cast(x)` 而言，`Expr.type` 就是期望类型解析出的 T——codegen 直接读，**无需**
在 Call 节点另加类型实参槽。上一版文档担心的「真实工作量」（把实例化类型实参穿到 codegen）在期望类型
驱动下**不存在**：那个 T 本就在 `Expr.type` 上。

**删掉 `as_bytes`、折进 `cast`**（`as_bytes(x)` ≡ `cast(x)` 且期望类型为 `Bytes`）：
- **净收益**：少一个 builtin（`Types.kt` FnSig）+ 少一条 codegen 名字特判分支——对齐 builtins-to-stdlib
  「消灭 as_XXX 家族」的主旨；`cast` 覆盖其余所有引用类型（`InputStream`/`String`/任意 `TJava`）。
- **迁移面就 2 处真实调用点**，都在本轮 `.dawn-version` bump 内顺带改：
  - dawn-lang 自测 `BytesTest.kt:154`（`let b: Bytes = as_bytes(...)` → `cast(...)`，测试名/断言随之改）；
  - dawnop-site `http.dawn:37`（`BytesResp { bytes: as_bytes(resp.body()!) }` → `cast(...)`）。
- **字段位依赖（顺带验证 streaming 要的同一条路）**：`http.dawn:37` 是**记录字段位**，`cast` 的 T 需从
  字段类型 `bytes: Bytes` 作期望类型传入——与 streaming 的 `StreamResp { stream: cast(...) }` 同路。
  若 checker 现不传字段期望类型：补上（streaming 也受益）或退成 `let b: Bytes = cast(...)` 再塞（总能写）。

## 六、别的语言对照

- **Scala**：`x.asInstanceOf[T]` —— **单个**泛型 cast，降级成 `CHECKCAST erasure(T)`。同一思路；
  差别只在 surface：Scala 显式写 `[T]`，Dawn v1 让 T 由期望类型定（`let s: InputStream = cast(x)`）。
- **Kotlin**：更进一步，读 classfile 的 **`Signature` 属性**拿到泛型返回，**自动**插 CHECKCAST，
  用户 `optional.get()` 直接得 `String`，连 cast 都不写。这是「根治」路（对应 builtins-to-stdlib
  的路 B「读签名 + 参数化 Java 类型」），**本特性不做**——`cast` 是务实档，一次到位地消灭 as_XXX 家族，
  且工作量小（期望类型 + `Expr.type` 全现成）。

## 七、测试计划（实现时补）

1. `let b: Bytes = cast(x)` 与 `as_bytes(x)` 行为一致（认领 `Optional.of(byte[]).get()`）。
2. `let s: InputStream = cast(x)`：认领 `URLConnection`/`ByteArrayInputStream` 交出的 `Object`，`readAllBytes` 通。
3. `let s: String = cast(x)`：认领 `Object` 到 `java/lang/String`。
4. 期望类型来自**字段/返回/实参位**（非 let 注解）也能解析 T（覆盖 `Expr.type` 各来源）。
5. 类型不符：`let s: String = cast(byteArrayVal)` → `ClassCastException`，被 `java_try` 收成 `Err`。
6. 编译期拒绝：目标 primitive（`let n: Int = cast(x)`）、以及**无期望类型**（`let a = cast(x)` 无注解）报错。

## 八、不做 / 权衡

- **v1 采期望类型驱动 `cast(x)`**（T 从 `Expr.type` 取），不造显式 `cast[T](…)` 语法 + 消歧——
  推迟到真有「期望类型推不动的复杂泛型」时再作独立特性，向前兼容（§4.2）。
- **不做 Kotlin 式 Signature 自动插**（那是 builtins-to-stdlib 的远期路 B，动类型系统）。
- **不引入 `as` 关键字**（理由见 §4.1）。
- **删掉 `as_bytes`**（不留别名）：`cast` 完全吸收它，多留一个特化 builtin 反而背离「消灭 as_XXX」的初衷；
  迁移面仅 2 处真实调用点（§五）。

## 参考

- [Type Casts in Scala (Baeldung)](https://www.baeldung.com/scala/type-casting) —— `asInstanceOf[T]` 单原语
- [Type Erasure in Scala (Sid Shanker)](https://squidarth.com/scala/types/2019/01/11/type-erasure-scala.html) —— CHECKCAST 落点
- [How Kotlin Handles Type Erasure on the JVM](https://medium.com/@AlexanderObregon/how-kotlin-handles-type-erasure-on-the-jvm-36d03d83ca82) —— Signature 属性 + 自动 checkcast
- 本仓 `docs/builtins-to-stdlib.md`（更大图景）、`spec.md` §9.5（Bytes/as_bytes）、§11（builtin 清单）
