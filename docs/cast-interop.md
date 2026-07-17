# `cast[T]`：统一的 interop 认领原语

> 语言层设计，**先文档、后实现**。目标：把「从擦除的 Java `Object` 认领回具体类型」从
> **一类型一 builtin**（`as_bytes`、将来的 `as_input_stream`…）收敛成**一个泛型内建 `cast[T]`**。
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

## 二、结论：一个 `cast[T]` 取代所有 `as_XXX`

```
cast[T](x: <opaque Object>) -> T          # Pure；失败抛 ClassCastException（可被 java_try 接住）
```

调用点写死具体 T，编译器当场发 `CHECKCAST erasure(T)`：

```dawn
let s: InputStream = cast[InputStream](resp.body()!)
let b = cast[Bytes](opt.get()!)           # as_bytes 的位置
```

### 修正一个误解：「泛型 cast 不可能」不成立

早先的结论是「T 运行时擦除，发不出 per-class CHECKCAST，所以 `as_bytes` 只能单态」。这**混了两件事**：

- ❌ **T 是外层函数自己的类型参数**（codegen 时未知）——确实发不出具体 CHECKCAST。
  但 interop 里从不会「把 Object 认领成一个连自己都不知道是什么的 T」，这是废场景。
- ✅ **T 在调用点被字面实例化成具体类**——编译器当场就知道要发 `CHECKCAST java/io/InputStream`。
  这**完全可发**。`as_bytes` 能 work 正因 `Bytes` 具体；`cast[T]` 对**任何调用点写死的具体 T** 一样。

Dawn 已有**同构先例**：`map_empty[K,V]()`、`set_empty[T]()`、`java_try[T]`、`catch_panic[T]`
都是「结果类型由显式 `[T]` 定、值参给不了信息」的类型应用内建。`cast[T]` 只是多一步——
codegen 要用实例化后的 T 去发 CHECKCAST。

## 三、语义

- **签名**：`cast[T](x) -> T`，`x` 形参类型 `java.lang.Object`（吃任何不透明值），`Eff.Pure`。
- **T 的约束**：必须在调用点解析成 **CHECKCAST 能落地的引用类型**：
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

## 四、命名：为什么是 `cast[T]` 而非 `as` 关键字（已定，记录理由）

- **`as` 已被模块系统预留**：`spec.md` 明写「无 `as` 重命名（v0.1）」——`use X as Y` 导入改名是
  计划中的特性。抢 `as` 当 cast 关键字会和它撞。
- **它是罕见 FFI 逃生阀，不是高频构造**：关键字靠普遍性挣语法位（`if`/`match`/`fn`）；
  cast 只出现在 interop 胶水的个位数调用点。Scala 甚至**故意**把它做成又长又丑的方法
  `asInstanceOf[T]`，就是要让 cast 显眼、少用——terse 的 `as` 关键字反诱导滥用。
- **和 `as_bytes` 同类**：本来就在泛化一个**函数**，`cast[T]` 心智模型不跳类别。
- **避开优先级地狱**：中缀 `as` 要和后缀 `!`、`.`/`[]` 链排优先级（`resp.body()! as InputStream` 怎么结合？）；
  `cast[InputStream](resp.body()!)` 天然没这问题。
- **命名取舍**：不用 `as[T]`（长得像关键字、又撞预留的 `as`）。备选 `unsafe_cast[T]`/`checkcast[T]`
  更「扎眼」，但它不是内存 unsafe、且总裹在 `java_try` 里危险已收敛，**`unsafe_` 言过其实**。
  取 **`cast[T]`**：诚实（确是一次运行时 checked cast）、风格对齐现有内建。

## 五、落地点

| 文件 | 现状（`as_bytes`） | 改动 |
|---|---|---|
| `check/Types.kt:471` | 单态 `FnSig(Object→Bytes)` | 加 `FnSig("cast", [Object], result=t, typeParams=[t])`；在类型检查里**校验实例化后的 T 是合法 CHECKCAST 目标**（引用类型、非抽象、非 primitive） |
| `codegen/CodeGen.kt:4438` | `CHECKCAST [B` 写死 | 新 `"cast"` 分支：**从该 call 节点的实例化 T 求内部名/描述符**再 `visitTypeInsn(CHECKCAST, …)` |
| `cli/Doc.kt:203` | as_bytes 文档串 | 加 `cast` 文档串 |
| `spec.md` §9.5 / §11 | as_bytes 条目 | 记 `cast[T]` 语义 + T 约束 |

**实现关键点 / 待确认**：codegen 如何拿到该调用点**实例化后的 T**？
需要类型检查阶段把解析出的类型实参记在 Call 节点上（供 codegen 读）。对 `cast` 而言 T **不能从
参数推**（参数是 `Object`），只能来自 (a) 显式 `cast[T](x)` 类型应用，或 (b) 绑定处的期望类型
（`let s: InputStream = cast(...)`）。**首版建议只认显式 `cast[T](…)`**，明确、不依赖期望类型传播；
期望类型驱动留作后续增强。这一步——「实例化类型实参在 codegen 可见」——是本特性的**真实工作量**所在。

**与 `as_bytes` 的关系**：`as_bytes(x)` ≡ `cast[Bytes](x)`。落地后二选一：
- **A（推荐）**：保留 `as_bytes` 作为 `cast[Bytes]` 的便捷别名（Bytes 认领常见，短名有价值），
  内部走同一 codegen 路径；
- B：删 `as_bytes`、全量改调用点（含 dawnop-site `http.fetch_bytes` 的 `as_bytes(resp.body()!)`）。
- 倾向 **A**：零破坏，`as_bytes` 变成「文档化的常用特化」，`cast[T]` 覆盖其余所有类型。

## 六、别的语言对照

- **Scala**：`x.asInstanceOf[T]` —— **单个**泛型 cast，降级成 `CHECKCAST erasure(T)`。`cast[T]` 同款。
- **Kotlin**：更进一步，读 classfile 的 **`Signature` 属性**拿到泛型返回，**自动**插 CHECKCAST，
  用户 `optional.get()` 直接得 `String`，连 cast 都不写。这是「根治」路（对应 builtins-to-stdlib
  的路 B「读签名 + 参数化 Java 类型」），**本特性不做**——`cast[T]` 是「显式写 T」的务实档，
  一次到位地消灭 as_XXX 家族，且工作量小。

## 七、测试计划（实现时补）

1. `cast[Bytes]` 与 `as_bytes` 行为一致（认领 `Optional.of(byte[]).get()`）。
2. `cast[InputStream]`：认领 `URLConnection`/`ByteArrayInputStream` 交出的 `Object`，`readAllBytes` 通。
3. `cast[String]`：认领 `Object` 到 `java/lang/String`。
4. 类型不符：`cast[String]` 一个实为 `byte[]` 的值 → `ClassCastException`，被 `java_try` 收成 `Err`。
5. 编译期拒绝：`cast[Int]`（primitive 目标）、`cast[T]`（T 仍抽象）报错。

## 八、不做 / 权衡

- **不做期望类型驱动的隐式 T**（首版只认显式 `cast[T](…)`），避免依赖类型传播、语义更可预测。
- **不做 Kotlin 式 Signature 自动插**（那是 builtins-to-stdlib 的远期路 B，动类型系统）。
- **不引入 `as` 关键字**（理由见第四节）。
- **保留 `as_bytes` 别名**，零破坏迁移。

## 参考

- [Type Casts in Scala (Baeldung)](https://www.baeldung.com/scala/type-casting) —— `asInstanceOf[T]` 单原语
- [Type Erasure in Scala (Sid Shanker)](https://squidarth.com/scala/types/2019/01/11/type-erasure-scala.html) —— CHECKCAST 落点
- [How Kotlin Handles Type Erasure on the JVM](https://medium.com/@AlexanderObregon/how-kotlin-handles-type-erasure-on-the-jvm-36d03d83ca82) —— Signature 属性 + 自动 checkcast
- 本仓 `docs/builtins-to-stdlib.md`（更大图景）、`spec.md` §9.5（Bytes/as_bytes）、§11（builtin 清单）
