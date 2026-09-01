# 失败穿过 FFI 边界时的模型

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **ERR-02（P1）**、**ERR-03（P1）**、**LANG-02（P1）**。
>
> 状态：**A 步已完成——三期全部合并。阶段 1（`ForeignError` + `catch_fault_e`/
> `catch_panic_e` 两个过渡内建，两后端都发射）、阶段 2（全部调用点迁到 `_e`；
> `catch_fault`/`catch_panic` 的表项换成 `Result[T, ForeignError]`；`std/io` 走 (ii)）、
> 阶段 3（调用点迁回原名，两后端的实现重新指向结构化那份，过渡拼法删除）。
> 终局只有一对屏障，载荷是 `ForeignError`，不保留 String 版本。
> **B 步也已完成——三期全部合并**（阶段 1 `cast_e` 过渡内建、阶段 2 调用点迁移 +
> 表项翻转、阶段 3 调用点迁回并删除过渡拼法），`cast` 的失败从此是值，
> 分期见 §6.10、收尾见 §6.12；**C2 步已于 2026-07-31 关档「不做」**——`bracket` 改以运行时
> intrinsic 落地（v0.39.0），冻结时那句「codegen intrinsic 会把 `bracket` 绑死在 JVM 上」
> 在 `catch_fault` 之后不成立，见 §6.12 与 [`../core-move2-design.md`](../core-move2-design.md)。**
> 分期理由与每期内容见下方 §六「落地分期」——**那一节是现状，第二节是意图**，
> 两者冲突时以第六节为准。第二、五节里几处与代码对不上的说法，第六节开头逐条记了。
> [`../native-backend-plan.md`](../native-backend-plan.md) §1 定了 native 的 panic 是
> setjmp/longjmp、捕获点是「`catch_panic` / `java_try` 的**对应物**」。两个后果：
> 错误类型不能带 JVM 类名（§2.A 已改），`bracket` 不能是 JVM codegen 特例
> （§2.C 已上移成 IR 节点，等 Phase 0）。撞车登记见
> [native-plan-overlap.md](native-plan-overlap.md) §3.3、§3.4。

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
let served = catch_panic(() => app(req))
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

`selfhost/src/check/types.dawn` 给 `cast` 纯签名；`docs/spec.md` §9 与
`docs/cast-interop.md` 又明确失败抛 `ClassCastException`。于是一个签名为 pure 的
函数可以用**非 Dawn panic 的宿主异常**退出——与 `design.md`「异常破坏签名即契约」的
论证直接冲突。

审查那句话值得原样保留：不要用「pure」同时表示「无副作用」和「不会以隐藏控制流退出」。

## 二、方案

三步，依赖关系是 A → B、A → C（B 与 C 互不依赖）。

### A. `ForeignError`：一个最小的、后端中立的结构化错误

初稿这里写的是 `JavaError { class_name, message, cause }`。**`class_name` 是 JVM
二进制名，那是个 JVM-ism**——native 后端上没有类名，而 native 计划明说
`java_try` 会有「对应物」。一个跨 FFI 边界的错误类型如果从第一天就假设有 Java 类，
第二个后端来的时候要么重做要么长出第二个类型。改成：

```dawn
# std/error.dawn（新增）
## What a foreign failure looks like after it crosses into Dawn.
##
## `kind` is the backend's own name for the failure class — a JVM binary name on
## the JVM backend, an errno symbol or a signal name on the native one. It is a
## *name*, not a rendered message: matching on a name is a decision the compiler
## can check for typos one day, matching on a message prefix (spec §9's current
## advice) is a decision the JDK — or libc — can silently invalidate.
##
## What it is deliberately not: a Java-shaped record. The JVM backend is one
## backend, and a type that spells `class_name` would have to be reinvented for
## the second one.
pub type ForeignError = {
  kind: String,
  message: String,
  cause: Option[String],
}
```

`java_try`/`catch_panic` 的返回类型从 `Result[T, String]` 改为
`Result[T, ForeignError]`。

**`kind` 里放什么由后端定，但它是后端契约的一部分**，要写进
[runtime-intrinsics-design.md](../runtime-intrinsics-design.md)：JVM 后端放
`getClass().getName()`，native 后端放 errno 符号名或信号名。
**跨后端可移植的匹配只有一种**——不匹配 `kind`，只看 `Err`/`Ok`。
想按 `kind` 分流的代码就是后端相关的代码，这一点要在文档里说明白，
不要让它看起来可移植。

**这是 intrinsic 契约的变更**：`Result[T, String]` 直接烧在
`selfhost/src/jvm/codegen.dawn` 的 `gen_try_closure` 发射的字节码里
（handler 现在调 `Throwable.toString()` 存进 `Result$Err`）。要改的是：

1. `gen_try_closure` 改为构造 `ForeignError` 记录（JVM 后端的 `kind` 取
   `getClass().getName()`，另两个字段取 `getMessage()`/`getCause()`）；
2. `ForeignError` 要进 prelude ADT 表（跟 `Option`/`Result` 一样由 codegen 生成类）；
3. 每个 `java_try`/`catch_panic` 的调用点。

**兼容过渡**：加一个 `pub fn message(e: ForeignError) -> String`，
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
pub fn cast[T](o: Object) -> Result[T, ForeignError]   # pure，失败是值
```

`try_cast` 之类的新名字**不加**——留着旧名字继续做不安全的事，
等于这条改动没发生。改名字反而更糟：`cast` 是所有人会先看到的那个。

**调用点**（`grep cast(` 已确认）：`packages/web/src/server.dawn` 的流式响应、
`playground`、`selfhost/src/ir/interp.dawn` 与 `pkgfetch.dawn` 里几处。
都改成 `cast(x)?` 或显式 match。数量可控。

**破坏性**：是。按 CONTRIBUTING §六先发 tag，dawnop-site 再 bump。

> **落地时的两处更正**（以 §6.10 为准）：调用点是 14 处，去处是
> `jreflect` 5、`jfold` 4、`vendor` 2、`maven` 1、`packages/web` 2——
> 上面那份「`interp.dawn` 与 `pkgfetch.dawn`」是写方案时凭印象点的，两个都没有。
> 而且这一步和 A 步一样**一期做不完**：改签名要三期两发布，理由同 §6.2。
> 「都改成 `cast(x)?` 或显式 match」这句也没落成：14 处一处也用不上 `?`
> （落空全是本文件的 bug，不是要往上传的情况），而 match 得配一条带注解的 `let`
> ——scrutinee 位置没有期望类型，T 就不绑定。见 §6.11。

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
) -> Result[B, ForeignError] !e
```

**「编译器/runtime 保证 release」这半句**是审查的原话，也是这里唯一的难点：
纯用 Dawn 写 `bracket`，它内部还是靠 `catch_panic`——那就只是把同一个惯用法
换了个名字。要真保证，`bracket` 得由编译器发射真正的「无论怎么退出都执行」结构。

于是 C 有两个版本：

- **C1（便宜）**：纯 Dawn 的 `bracket`，内部 `catch_panic`。收益是消灭三处手写惯用法、
  统一形状。**不解决**「丢原始上下文」。
- **C2（正确）**：`bracket` 是**降级阶段的一个 IR 节点**（`LProtect(body, release)`），
  两个后端各自发射：JVM 发 `visitTryCatchBlock` 带 `null` 类型（= finally），
  native 发 setjmp/longjmp 的 unwind 保护。原始失败继续向上传播，
  release 一定执行，栈不变。

初稿这里写的是「C2 = 一个 codegen intrinsic，发 JVM finally 块」。
**那是把它绑死在 JVM 上**——native 后端没有 finally，`bracket` 会变成第二份实现。
上移到 IR 之后依赖关系反而简单了：C2 不再是「等 IR 做完之后的一个后续改动」，
它**就是** IR 的一部分。

**建议仍然是直接做 C2**（C1 的收益里最大的一块「统一形状」在 C2 里照样有，
而 C1 会让第二次改动多一批调用点要动），但**它现在冻结**，等 Core IR 落地——
见 [native-plan-overlap.md](native-plan-overlap.md) §3.4。

> **2026-07-31 冻结解除**：Core IR 已落地。复核结论见
> [../core-move2-design.md](../core-move2-design.md)——`catch_fault` 定形后「绑死 JVM」的
> 论证不再成立，`bracket` 多半该是运行时 intrinsic 而非 IR 节点（该文 §2.6 与开放决策 1）；
> 本节的返回类型签名与「原始失败继续传播」互相矛盾（该文决策 2）。
>
> **同日结账：C2 关档「不做」，`bracket` 以运行时 intrinsic 落地（v0.39.0）。**
> 第三个屏障族 `bracket(resource, release, use) -> B`：急切 acquire、release 每条路径
> 恰好执行一次、原失败原样传播（native 按 `is_panic` 位 re-raise）。
> **`CSProtect`（本节写作 `LProtect`）这个 Core 节点不会被建出来**，图纸存
> [../core-move2-design.md](../core-move2-design.md) §2.3–2.5，推翻需新证据。

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
  有了 `kind` 之后调用方自己 match 就行，而每加一个分流形式就多一个
  要在后端里发射的方法。
- **给 `ForeignError` 加 `Show` 之外的渲染**。`derive Show` 够用；
  服务端要什么格式是服务端的事。
- **保留 `Result[T, String]` 版本作为便利函数**。留着它，所有旧代码就都不会迁移，
  两种错误类型会永久共存——那是这次改动想消灭的东西。（阶段 2 兑现：`catch_fault`/
  `catch_panic` 的 String 载荷已不存在，`std/io` 也没在门口降级。）
- **给 `ForeignError` 的 `kind` 定义一套跨后端的规范化取值**（比如把
  `java.io.IOException` 和 libc 的 `EIO` 映射到同一个 `io_error`）。
  听起来可移植，实际是在**猜**两套错误分类的对应关系，而猜错的地方
  正是调用方会依赖的地方。`kind` 是后端自己的名字，可移植的匹配只有
  `Ok`/`Err` 这一层——把这条限制写明白比造一层假的可移植性诚实。
- **等 A/B 也一起冻结**（当时的判断；C2 后来关档不做，A/B 已全部落地）。C2 冻结是因为它要 IR，A 与 B 不要
  （A 改 `gen_try_closure` 与调用点，B 改 `cast` 签名）。两者都是破坏性变更，
  越早发窗口越宽。

## 五、落地点

| 步 | 状态 | 文件 | 测试 |
|---|---|---|---|
| A | **可做** | `selfhost/src/jvm/codegen.dawn`（`gen_try_closure`）、prelude ADT 表、`std/error.dawn`、全部 `java_try` 调用点 | 现有全量 + 一个「`kind` 是二进制名而非 toString 前缀」的 test |
| B | **进行中**（阶段 1 已落地，见 §6.10） | `selfhost/src/check/types.dawn`（`cast` 签名）、`docs/spec.md` §9、`docs/cast-interop.md`、各调用点 | cast 失败返回 `Err` 而非抛的 test |
| ~~C2~~ | **关档「不做」**（2026-07-31）——`bracket` 改以**运行时 intrinsic** 落地（v0.39.0），不建 `LProtect` 节点 | ~~降级阶段的 `LProtect` 节点 + 两个后端的发射~~、`std/resource.dawn`、三处手写惯用法改写 | 「release 在 panic 路径也执行、且原失败继续传播」的 test（随 v0.39.0 落地） |

A 与 B 都是破坏性变更 → 各自先发 tag。A 会改发射的字节码 → `Emit-Change:`
（按 REL-02 的新格式，要标 target；见 [native-plan-overlap.md](native-plan-overlap.md) §3.8）。

## 六、落地分期

> 本节写于 A 步阶段 1 落地时（2026-07-30），描述的是**代码里真实发生的事**。
> 与第二、五节冲突处以本节为准。

### 6.1 先勘误：第二、五节与今天的代码对不上的地方

写第二节时 native 后端还没有，`java_try` 还没改名。逐条：

1. **`java_try` 已在 v0.30.0→v0.31.0 之间改名 `catch_fault`**（见 stdlib.dawn 的 `moved`
   表，旧名字现在只换来一句「renamed to `catch_fault`」）。下文一律用新名。
2. **A 步必须同时覆盖 C 后端**。第二节只点了 `gen_try_closure`——那个函数还在
   `selfhost/src/jvm/codegen.dawn`（写的是 `dawn/rt/Io` 这类运行时类；`emit.dawn` 是用户代码的
   JVM 发射器，`emitc.dawn` 是 C 发射器）。但 native 后端 2026-07 已经在跑，
   `runtime/c/dawn_rt.c` 里 `dawn_catch_fault`/`dawn_catch_panic` 是一对 setjmp/longjmp
   屏障。**好消息是 C 侧不必改发射器**：intrinsic 表说某个原语归 `RtIo`，emitc 就发
   `dawn_<name>` 的调用，加一个原语等于在 C 里写一个同名函数。
3. **`ForeignError` 不能声明在 `std/error.dawn` 里**。intrinsic 的返回类型要求编译器
   在读任何 std 之前就知道这个类型，所以它只能是 **prelude 类型**（与 `Option`/`Result`
   同列，固定 id = 2），而 prelude 类型不允许被 std 重新声明。第二节那段
   `# std/error.dawn（新增）` 的代码块是不可行的写法。
4. **过渡助手 `message()` 阶段 1 一行都放不下**。std 是**整目录被当前跑着的编译器读的**
   （`--std` 默认就是 `std/`，`modules.txt` 也从目录读、而不是从嵌到 jar 里的副本读），
   所以只要把 `error` 写进 `std/modules.txt`，**种子**就会去编译 `std/error.dawn`，而种子
   不认识 `ForeignError`。它只能进阶段 2。
5. 而且它未必必要：`ForeignError` 是 **record**，调用点直接写 `e.message` 就行，
   不需要一个函数去取字段。第二节把它想成「机械但量大的改写」，是因为当时把它当成了 ADT。
6. **native 的 `kind` 不是 errno 符号名**。C 运行时的 raise API 是
   `dawn_raise(msg, is_panic)`——**没有 errno**，也**不捕信号**。所以 native 的 `kind`
   落在运行时真有的那个东西上：`"panic"` / `"fault"`，也就是 `catch_kinds.dawn` 早就
   在问的那个分工。要 errno 得给每一个 `dawn_fault` 调用点加一个 kind 参数，那是独立的
   一件事，而 `kind` 之所以定义成「后端自己的名字」，正是为了它以后能变细而不违约。
7. **`cause` 在 JVM 侧是渲染而非嵌套**：取 `getCause().toString()`。嵌一个
   `ForeignError` 进 `ForeignError` 会让 handler 沿着链递归，而调用方几乎不读它。
   native 侧恒为 `None`——那里没有任何东西把一个失败挂在另一个下面。
8. **第五节表里 A 步那格「全部 `java_try` 调用点」属于阶段 2**，而且比那一格写的大得多，
   见 6.4。

### 6.2 为什么一期做不完：种子约束

`bin/dawn` 是种子驱动的（种子 = `scripts/seed-release.txt` 钉的 release，现为 v0.31.0）。
selfhost 自己的源要**同时**过两张 intrinsic 表：种子那张（用来把 selfhost 编成编译器 A），
和 HEAD 这张（A 再编 selfhost 一遍，跑内联 test、做 fixpoint）。于是：

- **改名可以一期做完**：一次加两个名字，两张表都认识旧名，新名先 dormant。
  `java_try`→`catch_fault` 就是这么走的（`10ed122` 加新名 dormant → v0.31.0 发布 +
  种子推进 → `a3cf536` 迁调用点并删旧名）。
- **改签名不行**：同一段源码不可能同时满足 `Result[T, String]` 和
  `Result[T, ForeignError]`。唯一两边都过的调用点写法是 `Err(_)`（把载荷丢掉），
  而需要消息的调用点——也就是这次改动想服务的那些——恰好没有这种写法。

所以签名变更要**两次发布 + 两次种子推进**，代码分三期。这不是保守，是算术。

### 6.3 三期

| 期 | 落什么 | 边界 |
|---|---|---|
| **1**（已合并） | `ForeignError` prelude 类型 + `catch_fault_e`/`catch_panic_e` 两个新内建，两后端都发射；测试与语料。**调用点一个不动。** | 之后发 tag，`seed-release.txt` 推进 |
| **2**（已合并） | 全部调用点迁到 `_e`；`std/io` 走 §6.5 的 (ii)；**同一提交**里把 `catch_fault`/`catch_panic` 的表项改成 `Result[T, ForeignError]`（此时它们零调用点，改了不影响任何源）。`std/error.dawn` **没建**，见 §6.7 | 再发 tag + 种子推进 |
| **3**（已合并） | 调用点从 `_e` 换回 `catch_fault`/`catch_panic`；删掉 `_e` 的表项、JVM 的两次
`gen_try_closure_e` 调用、C 的两个符号。落下来的样子见 §6.8——两个后端的原版实现是**陈的**，
所以不止是删 | 终局 |

第四节那条「**不**保留 `Result[T, String]` 便利版本」是**终局**的约束，阶段 3 兑现。
中间两期存在一对过渡拼法，是因为它们**证明会死**——阶段 3 的内容就是删掉它们。

**阶段 1 的具体清单**（都在 `fix/error-model-a`）：

- `selfhost/src/check/types.dawn`：`FOREIGN_ERROR_ID = 2`、`foreign_error_ty()`、
  `prelude_adts()` 里的 record（`kind`/`message`/`cause: Option[String]`，`derive Show`）、
  `prelude_impls()` 多一条 Show、intrinsic 表 87 → 89 条。
- `selfhost/src/check/checker.dawn`：`seed_prelude` 注册类型名与构造器名（所以用户也能
  自己造一个 `ForeignError { .. }`）；重定义时的报错话术把它和 `Option`/`Result` 并列；
  `visible_to_user_code()` 多两个名字。
- `selfhost/src/jvm/codegen.dawn`：`gen_try_closure_e` 发射
  `dawn/rt/Io.catch_fault_e`/`catch_panic_e`，`kind` 取 `getClass().getName()`
  （**不是** `toString()`，也不是 `getSimpleName()`）。
- `selfhost/src/main.dawn`：`ForeignError` 进无条件发射的 prelude 类列表。
- `runtime/c/dawn_rt.{h,c}`：`dawn_catch_fault_e`/`dawn_catch_panic_e`；`dawn_raise`
  记下 `"panic"`/`"fault"`。**emitc 一行没改**——表就是契约。
- `selfhost/src/ir/interp.dawn`：comptime 拒绝这两个名字（和它们的原版同理由）。
- 测试：`types.dawn` 两个新 test；`scripts/spike-native/foreign_error.dawn`（两后端，
  只问可移植的：两个屏障的分工与串版逐字一致、`kind` 是名字不是渲染）；
  `scripts/error-contract/`（单后端，问 JVM 的名字逐字是什么）。

**阶段 1 的 Emit-Change**：六个 `emit *` 标签全动。实测差异**恰为两处**——
多一个 `ForeignError.class`，`dawn/rt/Io.class` 多两个方法；Core golden 的 13 份 dump
逐字节不变，只有 selfhost 自身的模块 hash 动（改了哪些模块就动哪些）。

### 6.4 调用点账（阶段 2 要动的）

`catch_fault(` / `catch_panic(` 的调用，按去处（不含生成文件 `stdsrc.dawn`/`rtsrc.dawn`
里那些字符串常量）：

| 去处 | 个数 |
|---|---|
| `std/io.dawn` | 9 |
| `selfhost/src/`（vendor 3、main 3、jreflect 3、interp 3、maven 1、jarw 1） | 14 |
| `packages/web/src/server.dawn` | 6 |
| `playground/src/play/gate.dawn` | 3 |
| 语料（catch_kinds 6、pvec-contract 3、strings 2、io_run 1、array-contract 1） | 13 |
| **合计** | **45** |

阶段 1 之后 `foreign_error.dawn` 又多两处旧写法，那是**故意**的：它把同一个 thunk
同时喂给两对屏障，断言两边的裁决逐字一致；阶段 3 随 `_e` 一起清掉。

### 6.5 主线裁决（已定）

1. **`std/io` 的公开错误类型**（阶段 2 的规模由它决定）。`io.read_file` 那 9 个函数
   到 v0.32.0 为止返回 `Result[T, String]`，`Err` 里装的就是 `catch_fault` 的载荷。
   两条路：
   - **(i) std/io 在边界上降级**：`e.message` 转回 String，公开签名不变。改动最小，
     代价是把这次想消灭的东西留在 std 的门口——所有人拿到的仍然是一段文本。
   - **(ii) std/io 也返回 `Result[T, ForeignError]`**：直接调用点 72 处，加上所有用 `?`
     把它往上传的函数（它们的错误类型跟着变），会溢出到 `dawnop-site`。

   **裁决：(ii)**，阶段 2 已照此落地。第一节 1.1 的临床表现正是「跨层接口依赖消息
   文本」，止在 std 门口等于没治。`dawnop-site` 的外溢在它下一次升 `.dawn-version`
   时处理，不在本仓范围内。
2. **`_e` 这个拼法**。留着不换：它只活两期，v0.32.0 那一版的 `dawn doc --builtins`
   里已经有了，再换一次名字等于让同一件事在两个 release 的公开清单里各留一道疤。

### 6.6 阶段 2 落下来的样子

- **调用点 45 个**，一个不剩地迁到 `_e`：std/io 9、selfhost 14（vendor 3、main 3、
  jreflect 3、interp 3、maven 1、jarw 1）、`packages/web` 6、playground 3、语料 13。
  `scripts/spike-native/foreign_error.dawn` 里那两处旧写法**留着**——它把同一个
  thunk 同时喂给两对屏障、断言裁决逐字一致，而它只用 `Err(_)`，是唯一在两张表下
  都成立的调用点写法（§6.2），也正是那两个表项能被翻的原因。
- **`std/io` 的 9 个签名换成 `Result[T, ForeignError]`**，直接调用点 76 处随之改：
  绝大多数是 `"... : " ++ e` 变成 `++ e.message`。三处需要判断：
  - `stdlib.std_read` 的错误类型**留 String**——`load_std` 的 `Err` 是编译器自己
    造的句子（「bundled std module 不 parse」），不是外部失败；边界上取 `.message`。
  - `analyze.read_over` 的错误类型跟着 std/io 变——它只是转发，两个调用点都丢载荷。
  - `jreflect.invoke_static` 保留 `Result[_, String]`，并且是**全仓唯一**把 `kind`
    印进文本的地方（本地 helper `rendered`，等价于 `Throwable.toString()`）：那句
    诊断是「`Math.abs` threw java.lang.ArithmeticException」，异常类名就是答案，
    而这个模块本身就是 JVM 反射路线，不存在第二个后端。
- **`kind` 在文本里的通则**：别的地方一律只取 `.message`。`kind` 是后端自己的名字，
  印它会让同一段 CLI 输出在两个后端上不一样——这正是 `foreign_error.dawn` 从不打印
  `kind` 的理由。
- **`std/io.list_dir` 的非目录分支**是 std 自己造的 `ForeignError`，`kind` 定为
  `"io.not_a_directory"`——全 std 唯一一个不是后端给的 kind。
- Emit-Change 两处：`doc --builtins`（两个屏障的签名，外加两条 `_e` 的说明文字）与
  `lsp`（补全项的 `detail` 就是签名）。Core golden 只有 `std.io.core` 变，另有 5 个
  模块是 ADT id 漂移（脚本自己会说「no instruction differs」），已 `--record`。

### 6.7 `std/error.dawn` 没有建

§6.1 第 5 条的怀疑成立：`ForeignError` 是 record，`e.message` 是一次字段读，
`message()` 那个助手没有存在的理由。阶段 2 全程只出现过一个渲染需求
（`jreflect` 那句 `threw ...`），而它要的恰恰是**不可移植**的那一半——`kind`——
所以它是个模块内的私有函数，不是 std 的公开 API。std 里凭空多一个模块，
代价是一个永久的公开命名空间和一条种子纪律，收益是省掉一个点号。

### 6.8 阶段 3 落下来的样子（迁移收尾）

- **调用点 47 个换回原名**：std/io 9、selfhost 14（vendor 3、main 3、jreflect 3、
  interp 3、maven 1、jarw 1）、`packages/web` 6、playground 3、语料 15（catch_kinds 6、
  pvec-contract 3、error-contract 2、strings 2、io_run 1、array-contract 1）。
  比 §6.4 那张表多 2，是因为 `scripts/error-contract/` 是阶段 1 才建的，生下来就写 `_e`，
  没进过那份账。
- **删掉的**：`types.dawn` 的两条表项（89 → 87）与两条 `rt_of`；`checker.visible_to_user_code()`
  少两个名字；`interp` 的 comptime 拒绝名单少两个；`doc.dawn` 的 builtin 清单少两条。
- **两个后端各有一份「陈的原版」要处置，不是单纯删 `_e`**。阶段 2 翻的是**表项**，
  两个后端的**实现**没跟着翻：JVM 的 `gen_io_class` 仍把原名指向 `gen_try_closure`
  （渲染成 String 的那份），C 的 `dawn_catch_fault`/`dawn_catch_panic` 仍走
  `dawn_run_caught`（同样是 String）。这在阶段 2 无害——原名零调用点——但它意味着
  阶段 3 不是删两个孪生，而是**把原名重新指到出 `ForeignError` 的那份实现上，再删掉
  陈的那份**。JVM：`gen_try_closure_e` 改名成 `gen_try_closure`，旧的整个删掉；
  C：`dawn_run_caught_e` 收编成 `dawn_run_caught`，旧的整个删掉。两边都不留第二份
  handler 逻辑。
- **顺手补上一条 §6.2 没算到的纪律：运行时符号的契约也归种子管，而 `bin/dawn` 从前
  是一段式自举。** 一个 jar 里的 `dawn/rt/Io` 是**谁编的谁发射的**：`bin/dawn` 拿种子
  编出 A 就直接用，于是 A = 今天的调用点 + 上一版的屏障。载荷没变的时候这对得上，
  变了就对不上——本步实测 A 在每一条失败路径上抛 ClassCastException（`String` 转
  `ForeignError`），包括 `use java` 走 `$` 回退的那条，`playground` 和 `packages/web`
  两个仓内目标当场编不动，而构建过程一声不吭。修法是让 `bin/dawn` 走两段：种子编出
  A，A 再编一次，留下的是 fixpoint 那个 B。多花一次编译（本机 ~5s），换来「源码与
  运行时同出一棵树」——`selfhost-fixpoint.sh` 从来只承诺 B == C，而这个脚本一直在发
  A。这不是错误模型专有的坑，是**任何一次运行时契约变更**都会踩的坑，所以修在
  `bin/dawn` 而不是修在这次迁移里。
- **`foreign_error.dawn` 换了问法**。它原来的一半是「两对拼法裁决一致」，那个问题随
  `_e` 消失。剩下的预算改问一个同样可移植、而且以前没人问过的：**同一个 fault 被
  `catch_fault` 拦下和被 `catch_panic` 拦下，`kind`/`message` 逐字相同**——两个屏障
  只在「抓什么」上不同，不在「怎么报」上不同。顺带补了 panic 载荷的三条可移植断言，
  以及唯一一条可移植的**文本**断言：`panic("deliberate")` 的 `message` 就是那个实参，
  两个后端都是。仍然一次都不打印 `kind`。
- **Emit-Change 三处**：`doc --builtins` 少两条；`lsp` 的三份补全清单各少两项
  （`detail` 就是签名）；`emit *` 六个目标各差**一个文件**——`dawn/rt/Io.class`
  （少两个 `_e` 方法，原名那两个改出 `ForeignError`）。第三处是阶段 2 欠下的，见上一条。

### 6.9 路过看见的一处旧账（不在本步范围）

`SHOW_ID = 3`，而 `checker.cx_new` 的 `next_id` 也从 3 起，旁边的注释只列到
Ord/Eq/Hash——Show 是后加的，注释没跟。ADT 那半边没问题（prelude 占 0/1/2，
计数器从 3 起正好接上，这也是 `ForeignError` 拿 2 不用动计数器的原因），
trait 那半边第一个用户 trait 会拿到 3，是否真会与 Show 撞本步没查。

### 6.10 B 步的分期（`cast` → `Result`）

B 步受的约束与 A 步**逐字相同**，不是类比：`cast[T](o) -> T` 和
`cast[T](o) -> Result[T, ForeignError]` 没有任何一个调用点能同时满足，而 selfhost 自己的
14 处 `cast` 要同时过种子那张表和 HEAD 这张表（§6.2）。所以又是三期两发布。

| 期 | 落什么 | 边界 |
|---|---|---|
| **1**（已合并） | `cast_e` 过渡内建（表 87 → 88），两后端都发射；测试与语料。**`cast(` 一个不动。** | 之后发 tag，`seed-release.txt` 推进 |
| **2**（已合并） | 全部 `cast` 调用点迁到 `cast_e`；**同一提交**里把 `cast` 的表项改成 `Result[T, ForeignError]`，**并把两个后端的发射一起改指新形状**（此时它零调用点）。落下来的样子见 §6.11 | 再发 tag + 种子推进 |
| **3**（已合并） | 调用点从 `cast_e` 换回 `cast`；删掉 `cast_e` 的表项与两个发射器分支里的第二个名字；JVM 那个 `dawn/rt/Io.cast_e` 方法收编成 `cast`（native 没有对应符号，它是内联的 C，不必动）。落下来的样子见 §6.12 | 终局 |

**阶段 1 的具体清单**：

- `selfhost/src/check/types.dawn`：intrinsic 表多一条 `cast_e`（**纯**——失败成了值，
  没有效应可声明，这正是这次改动的内容）；`cast_e_target()` 供两个后端读
  `Result[T, ForeignError]` 里的 T。
- `selfhost/src/check/checker.dawn`：`visible_to_user_code()` 多一个名字；「目标须是引用类型」
  那条检查两个拼法共用（`cast` 读返回类型，`cast_e` 读它的第一个类型实参）。
- `selfhost/src/jvm/codegen.dawn`：`gen_cast_e` 往 `dawn/rt/Io` 里写一个
  `cast_e(Object, Class) -> Result`；`gen_try_closure` 的 handler 抽成 `gen_caught_err`，
  两处共用同一份 `ForeignError` 字段纪律（发射的字节逐字不变）。
- `selfhost/src/jvm/emit.dawn`：`cast_e` 的分支把目标类当 `Class` 常量 LDC 上去再调那个方法；
  `unerase_class()` 是 `unerase` 那张表的「名字版」。
- `selfhost/src/c/emitc.dawn`：`cast_e` 分支恒出 `Ok`，见下条。
- `selfhost/src/ir/interp.dawn`：comptime 拒绝（同 `cast` 的理由——comptime 没有宿主对象）。
- `selfhost/src/doc.dawn`：`interop` 组多一条。
- 测试：`types.dawn` 两处（表计数、两个拼法的签名并列）；
  `scripts/error-contract/probe.dawn` 加五条——命中带出原值、落空的 `kind` 逐字是
  `java.lang.ClassCastException`、它是名字不是渲染、`cause` 为 `None`、
  以及**`cast_e` 报的就是 `cast` 抛的**（阶段 3 是一次替换的前提）。

**三处判断，不是照抄**：

1. **JVM 侧是一个方法，不是内联的 try 块。** `cast` 是写进调用者的一条 CHECKCAST，
   而把**那条**包进 handler 不成立：进 handler 时 JVM 会清空操作数栈，于是
   `f(a, cast_e(x))` 这种表达式中途的 `cast_e` 会在汇合点丢掉已经压进去的 `a`。
   方法有自己的栈——这也正是两个屏障是方法的原因。
2. **`Class.cast`，不是 `instanceof` 测试。** 它就是 CHECKCAST 把操作数改成参数传，
   所以 `null` 照样通过（CHECKCAST 就是这么放行的），抛的是真的
   `ClassCastException`，`kind` 于是仍然是从异常上**读**下来的，而不是这份代码
   写死的字面量。
3. **native 侧恒出 `Ok`，并且说明理由而不是发死代码。** 这个后端的 `cast` 是一次
   **重解释**而非检查——没有运行期类型可比——而它那个 `Object` 唯一的来源是
   `use java`，`emitc` 在几百行之外就拒绝了。所以 `Err` 这条路在这里不可达，
   照抄一份 handler 只会是永远跑不到的代码。这是镜像不是发明：两个拼法在 JVM 上
   有区别，是因为那里的 CHECKCAST **会**失败。

**阶段 1 的 Emit-Change**：`emit *` 六个目标各差**一个文件**——`dawn/rt/Io.class`
多一个 `cast_e` 方法，别的一字不动；`doc --builtins` 多一条；`lsp` 的三份补全清单
各多一项。Core golden 的 13 份 dump 逐字节不变，只有 selfhost 自身改到的模块 hash 动。

### 6.11 B 步阶段 2 落下来的样子

- **调用点 14 个迁到 `cast_e`**：`jreflect` 5、`jfold` 4、`vendor` 2、`maven` 1、
  `packages/web` 2。**全部是 unwrap-panic**，一个也没改成传播：这些 `cast` 的目标类
  都是 JDK 或第三方库当场声明的（`getMethods()` 是 `Method[]`，coursier 的 `fetch()`
  是 `List<File>`，`ofByteArray` 的 body 是 `byte[]`），落空是本文件的 bug 而不是一种
  情况，而**恰好有两处的外层函数返回 `Result`**——`jfold.from_java_ret` 与 `maven.fetch`
  ——把落空折进那个 `Err` 会让「编译器自己坏了」伪装成「你的依赖拉不下来 / 你的
  comptime 调用不合法」，怪错人。没有一个调用点在屏障里（`vendor`/`maven` 那两处
  看着像，实际在 `catch_fault` 的 `Ok` 臂里、闭包之外），所以 panic 保住了
  「原样致命」这条语义。
- **`scripts/error-contract/probe.dawn` 反过来留着 `cast`**，而且是全仓唯一一处：
  它把 `thrown_by_cast`（原来靠 `catch_fault` 接住抛出）改写成 `missed_by_cast`
  （直接读 `Result`），并断言两个拼法的 `kind` **与 `message` 都**逐字相同。
  这一处能留，是因为 `scripts/` 只被 HEAD 的 `bin/dawn` 编译，种子从不碰它（§6.2 的
  约束是「同一段源要过两张表」，这段只过一张）。留它的收益是把 §6.8 那颗地雷变成
  一道闸门：**表项翻了而发射器没翻的话，`let r: Result[Bytes, ForeignError] = cast(x)`
  会发出一条 `CHECKCAST Result`，probe 在进函数的路上就死**，而不是等到阶段 3 才被
  发现。
- **同一提交里翻的三处**：`types.dawn` 的表项、`emit.dawn` 的 JVM 分支、`emitc.dawn`
  的 C 分支。后两处不是各写一份，而是**和 `cast_e` 合成同一条分支**（`name == "cast"
  || name == "cast_e"`）——A 步阶段 2 留下的正是「一个名字有两份实现，其中一份陈了」，
  而合并之后这件事在语法上就不可能再发生一次。checker 那条「目标须是引用类型」的
  两分支读法也合了，两个拼法现在都从 `Result` 里读 T。
- **`unerase` 没有变成死码**：`cast` 曾是它的调用者之一，还有四处（函数值 apply 的
  回收、CCast、erased 汇合点）。

**四件计划没预料到的**：

1. **`emit *` 一格没动**，尽管这一步动了 14 个调用点。因为 `prev-diff` 比的是
   **两个编译器编同一份源**：种子（v0.34.0）和 HEAD 都认识 `cast_e`，而翻掉的那条
   `cast` 分支在语料里零调用点、根本发射不到。所以本阶段的 Emit-Change 恰好两条
   （`doc --builtins` 与 `lsp`），与 A 步阶段 2 同形同因（§6.6）。
2. **不存在一个泛型的 unwrap 助手**，这是 B 步比 A 步啰嗦的真正原因。A 步的调用点是
   `catch_fault(f)` → `catch_fault_e(f)`，一个词的事；B 步每处要多三行。想收成
   `fn reclaim[T](o: Object) -> T` 是不行的：`cast[T]` 的 T 取自**调用点的期望类型**，
   写进一个泛型函数里，T 在那里就是个类型变量，`unerase_class` 给出 `Object`——
   检查会**静默失效**、什么都放行。所以 14 处都是写开的。
3. **调用点是两条语句，不是一条。** `match cast_e(x) { .. }` 编不过：match 的
   scrutinee 没有期望类型，T 于是不绑定，`check_call` 报「cannot infer type
   parameter(s) T」。定型是 `let r: Result[T, ForeignError] = cast_e(..)` 再 match
   `r`。**这个形状是永久的**——阶段 3 只把 `cast_e(` 改回 `cast(`，不重排这三行。
4. **`jreflect.invoke_static` 里那处仍是 panic**，尽管它是 §6.6 点名的「全仓唯一把
   `kind` 印进文本的地方」，而且外层就返回 `Result[_, String]`。它印 `kind` 是在报
   *被调用的 Java 方法*抛了什么；`Method[]` 里躺着个非 `Method` 不是那件事。

**阶段 2 的 Emit-Change**（实测）：

- `doc --builtins`：`cast` 的 `sig` 从 `fn cast[T](x: Object) -> T` 变成
  `fn cast[T](x: Object) -> Result[T, ForeignError]`，两条 `doc` 文本各重写一次。
- `lsp`：三份补全清单（id 31 / 36 / 39）里 `cast` 那项的 `detail` 就是签名，
  共 6 行（三对）。别的一字不动。
- `emit *` / `fmt` / `spike-native` / `native-fixpoint` / `table-freight` 全绿未动；
  Core golden 的 13 份 dump 逐字节不变，`selfhost.sha` 动了 9 个模块（checker、doc、
  emit、emitc、jfold、jreflect、maven、types、vendor）——恰好是改了**代码**的那些，
  `interp` 只改了注释所以没动，这本身是那份 hash 的一次抽检。

### 6.12 B 步阶段 3 落下来的样子（迁移收尾）

- **调用点 16 处换回 `cast`**：树内 14（`jreflect` 5、`jfold` 4、`vendor` 2、`maven` 1、
  `packages/web` 2）加 `scripts/error-contract/probe.dawn` 2。**形状一处没动**——
  `let r: Result[T, ForeignError] = cast(..)` 再 match `r` 是永久形状（§6.11 第 3 条），
  这一步只换了一个词，没有把三行收成一行的余地。
- **删掉的**：`types.dawn` 的表项（88 → 87）；`checker.visible_to_user_code()` 少一个名字；
  `interp` 的 comptime 拒绝名单少一条（60 → 59）；`doc.dawn` 的 builtin 清单少一条；
  两个发射器的 `name == "cast" || name == "cast_e"` 合回 `name == "cast"`，checker 那条
  「目标须是引用类型」同理。编译器内部的两个名字一并跟上（`cast_e_target` →
  `cast_target`、`gen_cast_e` → `gen_cast`），它们只在源码里存在，不值一个字节。
- **`dawn/rt/Io.cast_e` 改名成 `cast`，这是一处判断而不是照抄。** 这个方法对用户不可见，
  留着旧名字也能跑；改的理由是 `dawn/rt/Io` 里**每一个**方法都以它实现的那个 intrinsic
  命名（`catch_fault`、`catch_panic`、`io_*`），留下 `cast_e` 就是让运行时类成为全仓
  最后一处还活着的死拼法，而解释它的只有一句注释和 git 历史。代价是可测的一次性开销
  （下面的 `emit *`），不对称的是那处不协调是永久的。A 步的同题答案指向同一边：那边的
  屏障方法名一直就是表面名，改名的是发射器里的函数（`gen_try_closure_e` →
  `gen_try_closure`），一个字节都没动。
- **native 一行不用改**：那个后端的 cast 是发射在调用处的一次重解释，压根没有对应的
  运行时符号可改（§6.10 的表里已经写明），恒出 `Ok` 的那条分支照旧。
- **probe 换了问法**（同 §6.8 的做法）。「两个拼法逐字一致」的两条断言随第二个拼法消失，
  预算改问同样没人问过的另一半载荷：失败的 `message` 里**两个类名都在**——它是什么、
  它没能变成什么（实测 `Cannot cast java.lang.String to [B`）。这是 JVM 给失败的
  `Class.cast` 写的原话，钉住它就是把「从真异常上读下来的」和「这段代码自己编的字符串」
  分开——与上面 `kind` 那两条是同一个区分，只是换了一个字段。`missed_by_cast` 那个
  只为对照存在的助手一并删掉。

**阶段 3 的 Emit-Change**（实测，三处）：

- `doc --builtins`：少 `cast_e` 那一条，5 行。
- `lsp`：三份补全清单（id 31 / 36 / 39）各少一项 `cast_e`，`detail` 就是签名，共 6 行（三对）。
- `emit *`：**六个目标全动**，与前两期只动一格不同。`dawn/rt/Io.class` 六份都变
  （方法改名 + 常量池整体后移一格，javap 逐条比对无一条指令不同）；另外有 `cast` 调用点的
  模块也各变一条 invokestatic 的 NameAndType：`selfhost` 的 `jreflect`/`jfold`/`vendor`/`maven`
  （5+4+2+1）、`packages/web` 的 `server`（2）、`playground` 里那份随包带进去的
  `dawn$pkg$web/server`（2）。`site`、`packages/json`、`examples/calc.dawn` 只有 `Io.class`。
- Core golden 的 13 份 dump 逐字节不变；`selfhost.sha` 动了 13 个模块，其中 11 个是真改了
  代码的（checker、codegen、doc、emit、emitc、interp、jfold、jreflect、maven、types、vendor），
  另 2 个（exhaustive、reach）是 `types.dawn` 一动就顺带的 ADT id 漂移。

**一条实测出来的账**：`emit *` 这一整格**全部**是改运行时方法名的价钱，跟 14 个调用点无关。
把改名单独退回去再量一次，`selfhost` 与 `packages/web` 与种子逐字节相同——原因和 §6.11 第 1 条
一样，调用点写的是哪个拼法在字节码里根本不存在，被调方法的名字才在。所以这次的 Emit-Change
不是「迁移收尾自然会有的」，是一次命名决定的标价，它就该这么被读。

---

## 七、屏障族的效果行：先分成二比一，再分成一比一比一

三个屏障一直共用一条 `!io`。本节记两次裁决：2026-08-08 的 SEM-11 把 `bracket` 放开成
效果多态（`release`/`use`/调用共用一个行变量 `!e`）、两个 catch 维持 `!io`（§7.1–§7.4）；
2026-09-01 复核了那三条论证，发现它们逐条是 `catch_panic` 的论证，于是 `catch_fault`
也放开（§7.5）。**§7.1–§7.4 保留原样**，包括其中已被证伪的部分——被证伪的地方由 §7.5
逐条指出，不回头改写，否则读者无从知道当时凭什么那么裁。

### 7.1 `bracket` 为什么能放开

第二节 C 的草案写的就是 `!e`（见上面那段 `std/resource.dawn` 的签名）。v0.39.0 落地成
运行时 intrinsic 时抄成了 `!io`，没有留下理由——是收窄，不是决定。

判据是**它观察不观察失败**。`bracket` 不观察：release 跑完，原失败带着自己的种类和
消息继续走，调用方拿到的东西与没有 bracket 时逐字相同。所以它不该往行里加东西，而
钉死 `!io` 恰恰是加——它让「保护一个纯资源」把使用者变成不纯的，而这跟资源纯不纯毫无
关系。放开之后带标签的闭包也第一次能进 bracket：钉死时 `fn(A) -> B !Ask` 连实参都传
不进去（`argument type mismatch: expected fn(Int) -> Int !io`）。

**代价为零，且是实证的**：效果行在两个发射器看到 Core 之前就已擦除，同一个
`dawn/rt/Io.bracket` 服务所有实例化。`selfhost-prev-diff.sh` 在这次改动上全绿——
`emit *` 六个目标、`fmt`、`lex`/`parse` 逐字节不变，无 Emit-Change，不推种子。

### 7.2 catch 对为什么不能

> **2026-09-01 追记**：下面三条逐条查下来是 `catch_panic` 的论证，论证一在写下时就已被
> ERR-01 掏空。`catch_fault` 据此放开，见 §7.5；本小节保留原文。

原草案也想给它们 `!e`。三条论证各自独立地否掉了这件事，判据同上——**它们观察失败**，
而失败的可观察量不是纯函数允许有的：

1. **栈溢出的 panic 是调用上下文的函数。** 同样的实参、同样的闭包，栈深不同则一个返回
   `Ok`、一个返回 `Err`。纯函数的定义是同输入同输出，而这里「输入」里根本没有栈深这一项。
2. **panic 消息烘 `file:line`。** 在被捕获的函数上面加一行空行会改变 `Err` 里的 message，
   于是「纯」的结果随源码排版而变；`comptime` 会把构建机上的那份消息折成常量烘进产物，
   把这件事从难看变成不可接受。
3. **优化器有权折叠与消重纯调用**（spec §纯函数）。捕获的**次数**因此不是程序说了算的，
   而 `catch_*` 的每一次执行都可能产生一个不同的 `Err`。一个允许被消重的捕获点，
   语义上就不是一个捕获点。

这是 Haskell 那条「imprecise exceptions 只能在 `IO` 里捕」的 Dawn 版。同构的地方在于
Dawn 的 panic 也**不进效果行**：它不是一个被声明、被处理、被行减掉的效果，而是一条
横穿所有行的退出路径。捕获一条不在行里的东西，就只能由捕获点自己在行里留下印子。

### 7.3 重开条件

若 panic 有朝一日升为效果行的成员（Koka 的 `exn` 路线：`panic` 声明成一个效果、
函数签名带 `!exn`），三条论证同时失效——那时栈深、消息与折叠都是被声明的效果的一部分，
`catch_*` 应改为**行减多态**（吃一个带 `exn` 的行，还一个不带的），与 `with handle`
对 `E` 做的事情是同一件。在那之前，本节维持原判；§7.4 记的是经裁决的一处合法出口，
它不动判据，只放开参数位。

> **2026-09-01 追记**：这条重开条件**没有**被 §7.5 用掉。§7.5 走的是另一条路——不动 panic
> 的地位，只按「观察的是哪一种失败」把判据读细——所以本条对 `catch_panic` 原样有效。

不改的还有 `bracket` 的分组：`dawn doc --builtins` 仍把它列在 `io` 组下。那是给人看的
目录，不是签名。

### 7.4 eparams 形状：保住三条论证的出口（2026-08-25 裁决）

2026-08-25 的勘察在整仓副本里两后端端到端实测了第四种形状，用户已裁决采纳：

```dawn
fn catch_fault[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io
fn catch_panic[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io
```

放开的是**参数位**，不是屏障自己的行。机制是 `Sig.eparams`：签名绑定的效果变量买一格
擦除证据参数，`sig_abi_eff`（`selfhost/src/check/types.dawn:1524-1534`）直接构造 `EUnion`，
于是 `io` 与效果变量在 ABI 层共存。checker 侧早有同形状的先例，`checker.dawn:6230-6240`
那段注释举的例子逐字就是 `fn run(t: fn() -> Int !e) -> Int !io`。

**三条论证逐条仍然成立。** §7.2 的判据「观察失败的必须不纯」约束的是**屏障自己的行**，
不是被保护闭包的行，而 eparams 形状下捕获动作仍然只在 `!io` 上可用：

1. **栈深。** 纯函数依然写不出一个能观察栈深的签名。被放行的 `fn() -> T !e` 自己不观察
   任何失败，它只是被护送穿过屏障，`Ok`/`Err` 的分岔仍然只出现在 `!io` 的调用方那边。
2. **`file:line`。** 消息仍然只在 `Err` 里，而 `Err` 仍然只有 `!io` 的调用方拿得到。
   `comptime` 折不进一个纯签名，因为纯签名调不动 catch。
3. **折叠与消重。** 可折叠的是纯调用，捕获点带 `!io`，不在那个集合里。捕获的次数照旧
   由程序说了算。

放宽的只有一件事：什么东西可以被护送穿过屏障。带具名标签的闭包（`fn() -> T !Ask`）
以前连实参都传不进去，症状与 §7.1 里 `bracket` 钉死时那条同源。

**这不是 §7.3 说的那个重开。** panic 仍然不是效果行的成员，`catch_*` 仍然不是行减多态，
§7.2 的判据一个字没有变。变的只是参数位上那一格从 `!io` 松成 `!e`，§7.3 的重开条件
原样有效。

**实测**（2026-08-25 勘察，两后端）：checker-corpus 128 个 case、511 条诊断的 golden
逐字不变；纯签名想调用 `catch_fault`/`catch_panic` 仍被拒，因为捕获本身还是要 `!io`。

**同批钉住的一条语义。** handler 臂在屏障的动态范围内被就地调用时，臂自身抛出的 fault
被**内层屏障**接走，跟的是动态范围，不是 `io` 记账上的安装者；两后端答案一致。这是尾恢复
档的必然后果（没有一等 `resume`，臂物理上就跑在 raise 点的栈上），不是屏障给出的一条
独立承诺。若将来引入非尾恢复的臂，这个答案会翻转，届时要重裁，不能照抄本条。

### 7.5 `catch_fault` 也放开（2026-09-01 裁决）

签名从此不同形：

```dawn
fn catch_fault[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !e
fn catch_panic[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io
```

#### 7.5.1 §7.2 那三条论证逐条查下来是 `catch_panic` 的论证

复核对着实现读，不对着 §7.2 的文字读。

**论证一（栈深）今天两边都不成立**，而且在写下时就已经不成立了。`catch_panic` 捕的是
`[PanicError, Exception]`（`jvm/rtclasses.dawn` 的 `gen_try_closure`），
`StackOverflowError` 是 `VirtualMachineError` 是 `Error`，不在名单里；同处注释自己写明
这是刻意的。native 侧故意不装 SIGSEGV handler，栈耗尽是进程崩不是失败种类。改成这样的是
ERR-01，早于 SEM-11——所以 §7.2 落笔时这一条已经被自家的另一项修改掏空了，只是没人对着
实现读过它。**栈深影响不了 `Ok`/`Err`，因为栈耗尽根本到不了 `Result`。**

**论证二要重述，重述后只咬 `catch_panic`。** 「panic 消息烘 `file:line`」这句话没有实现
支撑：`assert` 烘的是被断言表达式的**源码文本**，下标越界烘的是索引与长度，`panic(m)` 烘
的是 `m`；在被捕获的函数上面加一行空行不会改变任何 message。但它有一个更强且成立的形式：
消息是**源码排版 × 后端**的函数——`assert` 的消息随拼写变，越界在 JVM 上是
`index N out of bounds for length M`、在 native 上是 `Array index out of bounds`，而
spec §9.8.1 只承诺 `panic(m)` 两后端逐字节相同。纯函数的结果不许是这两样的函数。
`catch_fault` 不拦 panic，这条对它不适用。

**论证三（折叠与消重）要咬人，前提是纯闭包有可能失败。** 纯闭包能 panic（越界、除零、
`expect`、显式 `panic`），所以对 `catch_panic` 实打实成立。fault 那侧则要靠下面这条
不变式，而它有一个洞。

#### 7.5.2 判据的加细，与它依赖的不变式

判据仍是 SEM-11 自己那条「观察失败的必须不纯」，只是按**观察的是哪一种失败**读：

> **panic 是语言自己定义的失败，没有任何行记录它可能发生，所以观察它的人必须不纯。
> fault 是外部世界造成的失败，通往外部世界的每一条路在能失败之前就已经记过 `io` 的账
> （io 原语与 `use java` 调用无条件 `EIo`），所以观察它的人已经不纯了，屏障不必再记一笔。**

三个屏障因此排成一条线，而不是二比一：`bracket` 什么都不观察（`!e`）→ `catch_fault`
观察的失败已被别人记过账（`!e`）→ `catch_panic` 观察的失败没人记过账（`!io`）。

**这不是 §7.3 说的那个重开。** panic 仍然不是效果行的成员，`catch_panic` 仍然不是行减
多态，§7.3 的重开条件原样有效。

#### 7.5.3 不变式的洞：续延，不是 `discard`

落地前在两个后端实测过（七个合成程序，JVM 与 `__emitc` → `cc` 各跑一遍）。结论比预期的糟，
而且方向不同：

- 草案怀疑的是 `discard`：签名纯，展开途中跑被放弃计算里的 `bracket` release，
  release 可以 fault。实测坐实——`catch_fault(() => 纯函数_discard())` 两后端都交出
  `Err`，同一程序里「release 不失败」的对照给 `Ok`，所以不是假阳性。
- **但洞不是 `discard` 的。** 一个纯签名的函数**恢复**续延（`k(5)`），remainder 在纯帧里
  做 io 并 fault，两后端同样交出 `Err`；把屏障和 `discard` 全部拿掉，纯签名函数的**返回值**
  就是磁盘上那个文件的内容，而且它能被传进只收纯 fn 值的形参槽。破不变式的是
  [`oneshot-design.md`](../oneshot-design.md) §11.2 的裁决本身：`k` 的类型是
  `TyFn([fret], answer, EPure)`，硬编码在 `checker.dawn`。`checker-corpus` 的
  `handler_resume.dawn` 就是这条裁决的现成语料，一直绿着。

所以不变式的正确写法带一个具名例外：**fault 只从 io 来，除非它是被一条续延带过纯边界的**。
spec §9.8.1 末尾按这个写法记着，不写成无例外的正条文。

**这个洞不由本刀修**，理由是给 `discard` 绑行变量给零：调用点的 `!e` 由实参的 fn 类型
实例化，而实参永远是纯 fn 类型（臂 binder 由 checker 合成成 `EPure`，存进 ADT/格子/列表的
字段也只能声明成纯）。要让 `!e` 非纯，`k` 的类型必须**携带**剩余的行，那正是 §11.2 为了
让 `k` 能当普通值存起来而裁掉的 `TyCont`。张力记在这里，重开归
[`oneshot-design.md`](../oneshot-design.md) §11.2。

#### 7.5.4 定价：今天的收益接近零，理由是向前的

同一条不变式把收益也框住了：`catch_fault` 的调用点绝大多数被护闭包本来就 `!io`（因为它
要能 fault），对这些点摘掉屏障的 `!io` 收益为零。全生态逐个判定下来，能跟着变纯的函数
只有两个，且都只被 `test {}` 调用，传染面 0。

值得做的理由只有一条，是向前的：`std/io` 里每个会失败的 fs 函数体都是
`catch_fault(io_*)`，fs 族一旦提升成具名效果 `!Fs`，屏障那条 `io` 会与 `!Fs` 并存
（`io` 不吸收任何原子），于是 `std/io` 里一条 `!Fs`-only 的签名都出不来，分解等于没做。
**这把刀让那件事成为可能，不负责做它。**

#### 7.5.5 种子：一轮或零轮

子效果包含站在这边：`base_subsumes` 里 outer 带 `io` 则基轴无条件通过，所以「过量声明」
恒合法，全仓没有「declared but unused effect」这条诊断。于是同一批可以只翻表项与镜像、
调用点签名一律不动——编译器自身源码在旧表与新表下都合法。摘调用点上不再需要的 `!io`
要等下一个 release，而由 §7.5.4，那一步全生态只收得到两个 test-only 的函数，可以不做。

与 `ForeignError` 载荷那次（三个 release + 过渡拼法）不同量级：那次改的是**返回类型**，
走类型相等判定；这次改的是**行**，走子效果包含。**这次没有理由引入过渡拼法。**

#### 7.5.6 看护：谁会在两个屏障重新变成一个形状时报红

一条只写在文档里的不对称，下一次重构会把它抹平而不自知。所以两边各留一条会红的判词：

- `checker-corpus` 的 `catch_effects.dawn`/`bracket_effects.dawn`：三条诊断只由
  `catch_panic` 产生，`catch_fault` 那侧改成了**接受**的行。把 `catch_panic` 一并放开，
  这三条金样静默消失；把 `catch_fault` 改回去，`catch_effects` 里那条「纯闭包的结果被交给
  只收纯 fn 值的槽」编不过。两个方向都有一条判词，这是刻意的：只钉一头的判词对
  「两个一起改」是瞎的。
- `check/types` 的两条内联测试：签名文本逐字，加上 `sig.eff` 逐值（`catch_fault` 是
  `EffVar`，`catch_panic` 的基轴是 `EIo`）。实测过：把 `catch_panic` 也改成透传，
  521 条里红 2 条、checker-corpus 少 3 条诊断。

`nev(sig_abi_eff(s)) == 1` 对这条不对称**是瞎的**（`io` 不占证据槽），而它继续断言两边都是
1，因为那正是「一个 shim 服务两条行」的理由。判词和它看不见的东西写在一起，是为了下一个
读的人不必自己发现后半句。

差分那侧另有一条新语料 `scripts/spike-native/ctl_discard_fault.dawn`：展开途中 release
逃逸一条 **fault**（§7.5.3 的洞，做成可跑的程序），两后端对拍。它不钉 `kind` 字面量——
`kind` 是声明为后端相关的（runtime-intrinsics-design.md §12.4），所以每条穿越的失败都跟
「同一条 fault，中间不放 discard」比较。把比较改成钉字面量，两后端立刻分歧。
