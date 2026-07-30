# 失败穿过 FFI 边界时的模型

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **ERR-02（P1）**、**ERR-03（P1）**、**LANG-02（P1）**。
>
> 状态：**A 步分期落地中——阶段 1（`ForeignError` + `catch_fault_e`/`catch_panic_e`
> 两个过渡内建，两后端都发射）与阶段 2（全部调用点迁到 `_e`；`catch_fault`/
> `catch_panic` 的表项换成 `Result[T, ForeignError]`；`std/io` 走 (ii)）都已合并；
> 阶段 3 等种子推进。B 步 proposed 且可做；C2 步冻结。**
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
`selfhost/src/codegen.dawn` 的 `gen_try_closure` 发射的字节码里
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
- **等 A/B 也一起冻结**。C2 冻结是因为它要 IR，A 与 B 不要
  （A 改 `gen_try_closure` 与调用点，B 改 `cast` 签名）。两者都是破坏性变更，
  越早发窗口越宽。

## 五、落地点

| 步 | 状态 | 文件 | 测试 |
|---|---|---|---|
| A | **可做** | `selfhost/src/codegen.dawn`（`gen_try_closure`）、prelude ADT 表、`std/error.dawn`、全部 `java_try` 调用点 | 现有全量 + 一个「`kind` 是二进制名而非 toString 前缀」的 test |
| B | **可做** | `selfhost/src/types.dawn`（`cast` 签名）、`docs/spec.md` §9、`docs/cast-interop.md`、各调用点 | cast 失败返回 `Err` 而非抛的 test |
| C2 | **冻结**，等 Core IR | 降级阶段的 `LProtect` 节点 + 两个后端的发射、`std/resource.dawn`、三处手写惯用法改写 | 「release 在 panic 路径也执行、且原失败继续传播」的 test |

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
   `selfhost/src/codegen.dawn`（写的是 `dawn/rt/Io` 这类运行时类；`emit.dawn` 是用户代码的
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
| **3** | 调用点从 `_e` 换回 `catch_fault`/`catch_panic`；删掉 `_e` 的表项、JVM 的两次
`gen_try_closure_e` 调用、C 的两个符号 | 终局 |

第四节那条「**不**保留 `Result[T, String]` 便利版本」是**终局**的约束，阶段 3 兑现。
中间两期存在一对过渡拼法，是因为它们**证明会死**——阶段 3 的内容就是删掉它们。

**阶段 1 的具体清单**（都在 `fix/error-model-a`）：

- `selfhost/src/types.dawn`：`FOREIGN_ERROR_ID = 2`、`foreign_error_ty()`、
  `prelude_adts()` 里的 record（`kind`/`message`/`cause: Option[String]`，`derive Show`）、
  `prelude_impls()` 多一条 Show、intrinsic 表 87 → 89 条。
- `selfhost/src/checker.dawn`：`seed_prelude` 注册类型名与构造器名（所以用户也能
  自己造一个 `ForeignError { .. }`）；重定义时的报错话术把它和 `Option`/`Result` 并列；
  `visible_to_user_code()` 多两个名字。
- `selfhost/src/codegen.dawn`：`gen_try_closure_e` 发射
  `dawn/rt/Io.catch_fault_e`/`catch_panic_e`，`kind` 取 `getClass().getName()`
  （**不是** `toString()`，也不是 `getSimpleName()`）。
- `selfhost/src/main.dawn`：`ForeignError` 进无条件发射的 prelude 类列表。
- `runtime/c/dawn_rt.{h,c}`：`dawn_catch_fault_e`/`dawn_catch_panic_e`；`dawn_raise`
  记下 `"panic"`/`"fault"`。**emitc 一行没改**——表就是契约。
- `selfhost/src/interp.dawn`：comptime 拒绝这两个名字（和它们的原版同理由）。
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

### 6.8 路过看见的一处旧账（不在本步范围）

`SHOW_ID = 3`，而 `checker.cx_new` 的 `next_id` 也从 3 起，旁边的注释只列到
Ord/Eq/Hash——Show 是后加的，注释没跟。ADT 那半边没问题（prelude 占 0/1/2，
计数器从 3 起正好接上，这也是 `ForeignError` 拿 2 不用动计数器的原因），
trait 那半边第一个用户 trait 会拿到 3，是否真会与 Show 撞本步没查。
