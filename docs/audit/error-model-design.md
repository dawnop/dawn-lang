# 失败穿过 FFI 边界时的模型

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **ERR-02（P1）**、**ERR-03（P1）**、**LANG-02（P1）**。
> 状态：proposed。

三条放一起，因为它们是同一句话的三个后果：**Dawn 没有异常语法，但 JVM 异常会穿透，
而语言目前只有一种接住它的方式——变成 `String`。**

## 一、问题

### 1.1 异常被降成字符串，跨层接口依赖消息文本（ERR-02）

`java_try` 与 `catch_panic` 都返回 `Result[T, String]`，字符串是
`throwable.toString()`。类型、cause、stack、结构化字段全部丢掉。

`docs/spec.md` §9 因此建议**按类名前缀匹配字符串**。这条建议的临床表现在
`packages/web/src/types.dawn`：

```dawn
# Same lift, but the status is chosen from the message. A few repository errors
# are client errors in disguise (a bad page reference, a duplicate slug) and the
# only thing that distinguishes them is the text, so those call sites pass a
# classifier instead of a fixed code.
pub fn as_http_with[T](r: Result[T, String], f: fn(String) -> HttpError) -> ...
```

注释说得很坦白：**唯一能区分它们的就是文本**。于是重构一句错误文案、
换一个 JDK 版本、加一次本地化，都可能改变程序的控制流。

### 1.2 没有 `finally`，于是 `catch_panic` 被当 finally 用（ERR-03）

语言没有 `try/finally`、`defer`、`using`，也没有线性资源。现有代码的写法：

```dawn
# packages/web/src/server.dawn
# the temp body file lives exactly as long as the handler call. Dawn has no
# try/finally, so catch_panic plays that role (same idiom as with_tx): it
# returns rather than unwinding, so the delete below always runs.
let served = catch_panic(fn() => app(req))
match req.body_file { Some(p) -> delete_quietly(p); None -> () }
```

`playground/src/play/gate.dawn` 的 `with_gate` 是同一个套路（放许可），
`server.dawn` 的流式响应分支也是（关上游流）。

这个惯用法有两个代价：

1. **它促成了 ERR-01**。想让 `catch_panic` 当 finally 用，就会想让它接住一切——
   于是它接住了 `Throwable`。2026-07-25 已经把它收窄到 `PanicError + Exception`，
   但那只是止血：把「清理」建立在「捕获」之上这件事本身没变。
2. **它丢原始上下文**。异常变成字符串之后重新 panic，栈已经不是原来那条。

### 1.3 `cast` 签名是纯的，失败抛 JVM 异常（LANG-02）

`selfhost/src/types.dawn` 给 `cast` 纯签名；`docs/spec.md` §9 与
`docs/cast-interop.md` 又明确失败抛 `ClassCastException`。于是一个签名为 pure 的
函数可以用**非 Dawn panic 的宿主异常**退出——与 `design.md`「异常破坏签名即契约」的
论证直接冲突。

审查那句话值得原样保留：不要用「pure」同时表示「无副作用」和「不会以隐藏控制流退出」。

## 二、方案

三步，依赖关系是 A → B、A → C（B 与 C 互不依赖）。

### A. `JavaError`：一个最小的结构化错误

```dawn
# std/error.dawn（新增）
## What a Java throwable looks like after it crosses into Dawn.
##
## `class_name` is the binary name, not the toString() prefix: matching on a
## *name* is a decision the compiler can check for typos one day, matching on a
## message prefix (spec §9's current advice) is a decision the JDK can silently
## invalidate.
pub type JavaError = {
  class_name: String,
  message: String,
  cause: Option[String],
}
```

`java_try`/`catch_panic` 的返回类型从 `Result[T, String]` 改为
`Result[T, JavaError]`。

**这是 intrinsic 契约的变更**：`Result[T, String]` 直接烧在
`selfhost/src/codegen.dawn` 的 `gen_try_closure` 发射的字节码里
（handler 现在调 `Throwable.toString()` 存进 `Result$Err`）。要改的是：

1. `gen_try_closure` 改为构造 `JavaError` 记录（读 `getClass().getName()`、
   `getMessage()`、`getCause()`）；
2. `JavaError` 要进 prelude ADT 表（跟 `Option`/`Result` 一样由 codegen 生成类）；
3. 每个 `java_try`/`catch_panic` 的调用点。

**兼容过渡**：加一个 `pub fn message(e: JavaError) -> String`，
现有 `Err(m) -> ... m ...` 的调用点改成 `Err(e) -> ... error.message(e) ...`。
机械但量大。

**为什么不带 stack**：`StackTraceElement[]` 要么是不透明 Java 数组
（Dawn 拿不动），要么要 render 成 `List[String]`——而 render 的代价要付在
**每一次** `java_try` 上，包括那 99% 立刻被丢弃的成功路径旁边的失败。
真需要栈的场景（服务端日志）可以另给一个 `java_try_traced`。

### B. `cast` 返回 `Result`（LANG-02）

```dawn
# 现在
pub fn cast[T](o: Object) -> T          # pure，失败抛 ClassCastException

# 之后
pub fn cast[T](o: Object) -> Result[T, JavaError]   # pure，失败是值
```

`try_cast` 之类的新名字**不加**——留着旧名字继续做不安全的事，
等于这条改动没发生。改名字反而更糟：`cast` 是所有人会先看到的那个。

**调用点**（`grep cast(` 已确认）：`packages/web/src/server.dawn` 的流式响应、
`playground`、`selfhost/src/interp.dawn` 与 `pkgfetch.dawn` 里几处。
都改成 `cast(x)?` 或显式 match。数量可控。

**破坏性**：是。按 CONTRIBUTING §六先发 tag，dawnop-site 再 bump。

### C. `bracket`：先给标准库函数，不给语法

```dawn
# std/resource.dawn（新增）
## acquire → use → release, with release guaranteed on the panic path too.
##
## Not `defer` and not `try/finally`: both need parser + checker + codegen, and
## the thing every current caller actually wants is this exact shape — the
## three call sites that hand-roll it (web/server.dawn's temp body file,
## play/gate.dawn's permit, web/server.dawn's upstream stream) are all
## acquire/use/release with nothing in between.
pub fn bracket[A, B](
  acquire: fn() -> A !e,
  use_it: fn(A) -> B !e,
  release: fn(A) -> Unit !e,
) -> Result[B, JavaError] !e
```

**「编译器/runtime 保证 release」这半句**是审查的原话，也是这里唯一的难点：
纯用 Dawn 写 `bracket`，它内部还是靠 `catch_panic`——那就只是把同一个惯用法
换了个名字。要真保证，`bracket` 得是一个 **intrinsic**，由 codegen 发射
真正的 JVM `try/finally`（`visitTryCatchBlock` 带 `null` 类型 = finally）。

于是 C 有两个版本：

- **C1（便宜）**：纯 Dawn 的 `bracket`，内部 `catch_panic`。收益是消灭三处手写惯用法、
  统一形状。**不解决**「丢原始上下文」。
- **C2（正确）**：`bracket` 作为 intrinsic，codegen 发 finally 块。原始异常继续
  向上传播，release 一定执行，栈不变。

**建议直接做 C2**。C1 的收益里最大的一块（统一形状）在 C2 里照样有，
而 C1 会让第二次改动多一批调用点要动。

## 三、为什么不顺手把 X 也改了

- **不引入业务错误 ADT**。审查建议「`JavaError` 和业务错误 ADT」。前者是语言/std 的事，
  后者（`HttpError` 换成 ADT）是 `packages/web` 的 API 设计，归
  [web-api-v2-design.md](web-api-v2-design.md)。混在一起会让这份改动跨两个发布节奏。
- **不改 `catch_panic` 的捕获范围**。已经改过了（ERR-01，2026-07-25：
  `Throwable` → `PanicError + Exception`）。本文假定那个结果。
- **不给 Dawn 加 `throw`/`catch`**。「没有异常」是设计的一部分；本文做的是
  让**已经存在**的穿透有一个诚实的表示，不是把异常请回来。

## 四、不做的（记录理由）

- **让 `java_try` 按异常类型分流**（`java_try_catching[T](cls, ...)`）。
  有了 `class_name` 之后调用方自己 match 就行，而每加一个分流形式就多一个
  要在 codegen 里发射的方法。
- **给 `JavaError` 加 `Show` 之外的渲染**。`derive Show` 够用；
  服务端要什么格式是服务端的事。
- **保留 `Result[T, String]` 版本作为便利函数**。留着它，所有旧代码就都不会迁移，
  两种错误类型会永久共存——那是这次改动想消灭的东西。
- **等 lowered IR 做完再动**。C2 要在 codegen 发 finally 块，
  确实会与 [lowered-ir-design.md](lowered-ir-design.md) 的 emit 改造撞。
  但 A 与 B 完全不受影响，可以先做；C2 排在 IR 阶段 C 之后。

## 五、落地点

| 步 | 文件 | 测试 |
|---|---|---|
| A | `selfhost/src/codegen.dawn`（`gen_try_closure`）、prelude ADT 表、`std/error.dawn`、全部 `java_try` 调用点 | 现有全量 + 一个「`class_name` 是二进制名而非 toString 前缀」的 test |
| B | `selfhost/src/types.dawn`（`cast` 签名）、`docs/spec.md` §9、`docs/cast-interop.md`、各调用点 | cast 失败返回 `Err` 而非抛的 test |
| C2 | `selfhost/src/codegen.dawn`（`bracket` intrinsic，finally 块）、`std/resource.dawn`、三处手写惯用法改写 | 「release 在 panic 路径也执行、且原异常继续传播」的 test |

A 与 B 都是破坏性变更 → 各自先发 tag。A 会改发射的字节码 → `Emit-Change:`。
