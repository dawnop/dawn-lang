# 纯度边界与 comptime 执行环境

> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **LANG-01（P0）** 与 **ARCH-06（P1）**。
> 状态：proposed。

两条审查条目放在一起，因为它们指向同一个东西：**comptime 求值器是什么，
它被允许做什么，它跑在哪儿。** LANG-01 问「谁能盖 pure 章、盖了之后编译期能执行什么」，
ARCH-06 问「这个求值器为什么要 512MB 宿主栈」。分开写会各自绕过对方的一半答案。

## 一、问题

### 1.1 `unsafe_pure` 是对用户开放的不健全逃生门

`docs/spec.md` §6 保证纯函数同参同值、无可观测副作用；§6.4 又把 `unsafe_pure`
作为普通语言语法开放，并承认它不健全。`docs/design.md` 的原始决策写的是
「unsafe escape 不向用户代码开放」——与现状相反。

`selfhost/src/checker.dawn` 的 `check_unsafe_pure` 只做一件事：把 body 里
具体的 `io` 效果屏蔽成 `Pure`（效果变量拒绝，完全没有 io 的 body 报「多余的戳」）。
它**不看调用者是谁**，不区分 std 与用户代码。

于是任何人可以写：

```dawn
fn now() -> Int = unsafe_pure { System.currentTimeMillis()! }
```

签名是纯的。编译器据此可以做的推理（同参同值、可重排、可折叠、可省略）全部失效。

### 1.2 comptime 会在编译器进程内反射执行 Java 静态方法

`selfhost/src/interp.dawn` 的 `eval_java`（route C）：只在 `unsafe_pure` 内可达、
只接受 static 方法、只跨 Int/Float/Bool/String/Unit 边界——三道限制都是真的，
但**边界之内是任意的**。`jreflect.invoke_static(fqcn, method, param_cls, jargs)`
对 JDK 的哪个类没有限制。

也就是说 `const X: Int = unsafe_pure { SomeClass.doIt() }` 让**编译一份源码**
变成了在编译器 JVM 里执行宿主 Java 的入口。

fuel 挡不住：

```dawn
# interp.dawn:699
# a Java call is opaque to the fuel counter, so charge a flat cost
let (st3, env3, _) = burn_n(st1, env1, 100, lo, hi)?
```

一次反射调用固定收 100 点 fuel，然后进去待多久都行。`docs/pure-ffi-design.md`
自己也写了这一点：反射一旦进入无法打断。

**已经做过的缓解**（2026-07-25，见 codebase-audit.md）：Playground 是仓库里唯一
「编译不可信源码」的实例，它现在 fail-closed 开沙箱，编译阶段也有独立 timeout。
但那是部署侧的补丁，语言工具本身仍然没有隔离。

### 1.3 求值器递归在宿主栈上，于是全仓要 `-Xss512m`

`interp.dawn` 文件头：

> The Kotlin interpreter runs on a dedicated 64MB thread; this one recurses on
> the host stack, so the selfhost JVM is launched with -Xss512m instead.

这个参数从 `bin/dawn` 一路传到 `selfhost/src/main.dawn` 的 `spawn_java`——
也就是说**用户程序也继承了它**。用户程序的深递归今天靠这个参数活着。

512MB 是虚拟地址保留（不是驻留），但它在容器里会撞 `ulimit`/cgroup 的内存核算，
而且把一个编译器实现细节泄漏成了用户程序的运行参数。

> 注：Kotlin 版的 64MB 与现在的 512MB 差 8 倍，这个数字的来历没有实测记录。
> 本方案不打算把它调小——见 §五。

## 二、复盘：为什么当初是这样

`docs/pure-ffi-design.md` 定的三条路线里，route C（comptime 折叠 Java）
是为了让 `core/math` 这类 std 模块能把 `java.lang.Math` 包成纯函数。
那个用例是真实的、且**只发生在 std 里**——spec §11 现在还写着
「`core/math`：内部以 `unsafe_pure` 包装 `java.lang.Math`」。

也就是说：**这个机制从一开始就只有 std 需要**，对用户开放是顺手的结果，
不是设计出来的。审查说得对，`design.md` 的原意就是不开放。

`-Xss512m` 是自举时的权宜：Kotlin 版用专用线程，Dawn 版没有创建线程的语法糖，
于是改成调大主线程栈。这是实现约束，不是决策。

## 三、方案

分三步，**每步能独立发布、独立验证**。步骤 1 解决 1.1，步骤 2 解决 1.2，
步骤 3 解决 1.3。

### 步骤 1：`unsafe_pure` 收归 std（对应 LANG-01 建议 1）

在 checker 里加一条：`unsafe_pure` 只在 `cx.is_std_module` 为真时合法。
用户模块里出现它 → 编译错误，hint 指向本文。

`Cx` 已经有 `is_std_module: Bool` 这个字段（`checker.dawn:120` 附近），
判定不需要新机制。

**为什么不是白名单文件**：审查建议「编译器签名/白名单标记的 std primitive」。
一份独立的白名单要回答「住哪、怎么随 std 版本走、第三方包能不能申请」三个问题，
而 `is_std_module` 已经**是**那条边界——std 是随编译器一起发布、一起自举、
一起被 N vs N−1 差分守护的代码。多一份白名单只是多一处会漂移的真相。

**破坏性**：这是语言收窄。按 CONTRIBUTING §六，先发 tag，dawnop-site 再 bump。
需要先扫一遍生态确认没有用户代码在用（`packages/`、`site/`、`playground/`、
`examples/` 已确认没有；dawnop-site 要单独扫）。

**逃生阀**：不给。给了就等于没收窄。真有 std 之外的合理用例，
它应该变成一个 std 函数。

### 步骤 2：comptime 的 Java 调用改 allowlist（对应 LANG-01 建议 2）

route C 从「任意 static 方法」收成一张表：

```dawn
# interp.dawn
## The classes comptime may fold. Not a security boundary on its own — step 1
## already means only std can get here — but it bounds what a std bug can do,
## and it makes "what runs inside the compiler" an enumerable list instead of
## "all of the JDK".
const COMPTIME_ALLOWLIST: List[String] = [
  "java.lang.Math",
  "java.lang.Integer", "java.lang.Long", "java.lang.Double",
  "java.lang.String", "java.lang.Character",
]
```

不在表里 → 编译错误，消息里写明这是 comptime 的封闭列表、以及怎么申请加入
（改这张表 + 说明为什么这个类是纯的和总的）。

**为什么是类粒度不是方法粒度**：方法粒度更严，但表会有几百行，
而且每次 JDK 版本变化都要复核。类粒度的表能一眼读完——
「能一眼读完」是这张表唯一的价值来源。上面六个类全部是无状态的纯计算类。

**要复核的**：`java.lang.String` 有 `intern()`（有全局副作用，但返回 String、
且幂等），`java.lang.Character` 的行为随 Unicode 版本走（同一 JDK 内确定）。
两者都在「同一 JDK 下同参同值」的意义上是纯的，这正是 `unsafe_pure` 承诺的东西。

### 步骤 3：求值器不再吃宿主栈（对应 ARCH-06 + LANG-01 建议 3）

`ceval` 现在是宿主递归。改成显式栈（trampoline）后：

- comptime 的深度由 `ESt.depth` 完全控制，不再靠宿主栈兜底；
- `-Xss512m` 从 `bin/dawn`、`main.dawn` 的 `spawn_java`、各 diff 脚本里去掉；
- **用户程序不再继承编译器的栈参数**。

**做法**：`ceval` 的返回类型已经是 `ER = Result[(ESt, Env, CValue), (ESt, Env, Ctl)]`，
控制流已经显式化了一半（`CReturn`/`CBreak`/`CContinue` 是值不是异常）。
剩下的是把「递归调用 `ceval`」换成「压一个续延帧」。`TExpr` 有 30 余个构造器，
每个都要拆成「求值子表达式前」与「子表达式回来之后」两半——**这是本步骤的全部工作量**，
也是它排在最后的原因。

**顺序很重要**：步骤 3 改完，`-Xss512m` 才能摘。但摘掉它会让用户程序里原本能跑的
深递归开始 `StackOverflowError`——而 ERR-01 刚把 `StackOverflowError` 从
`catch_panic` 里移出去。所以摘参数这一下要单独一个提交、单独一条 release note，
并且给用户程序保留 `--stack-size` 之类的显式开关。

### 不做：把 comptime 放进子进程（LANG-01 建议 3 的强版本）

审查建议「comptime evaluator 放进资源受限子进程，绝不与主编译器同进程」。
**不做**，理由：

- 每次编译多一次 JVM 启动，加上全部 comptime 值的跨进程序列化。
  代价没有实测，但方向是明确的——而 comptime 出现在**每个带顶层 `const` 的模块**里。
  按 CONTRIBUTING §二，没实测过的性能断言不写进方案，所以这里也不写「慢多少」；
  但要引入它，必须先有那个实测。
- 步骤 1 + 2 之后，能在编译器里跑的东西是「std 的代码调六个 JDK 纯计算类」。
  子进程要防的威胁模型（编译不可信源码 → 宿主执行）已经被前两步堵掉了。

如果将来允许第三方包做 route C，这一条要重新评估。

## 四、为什么不顺手把 X 也改了

- **不改 `cast` 的签名**（LANG-02）。`cast` 被标 pure 但会抛
  `ClassCastException`，与本文是同一类矛盾（pure 同时表示「无副作用」和
  「不会以隐藏控制流退出」）。但它的修法完全不同——改返回类型、改每个调用点——
  归 [error-model-design.md](error-model-design.md)。
- **不重写 `pure-ffi-design.md`**。那是历史设计记录，route A/B/C 的划分仍然成立，
  本文只收窄 route C 的边界。落地后回填一条「已被本文修订」。
- **不动 fuel 模型**。反射调用固定收 100 点这件事在步骤 2 之后不再危险
  （allowlist 里的六个类都不会长时间阻塞）。真要精确计费得给每个 allowlist 条目
  标一个代价，收益不值。

## 五、不做的（记录理由）

- **把 512MB 调小到某个「合理」值**。现在的 512MB 与 Kotlin 版的 64MB 都没有实测出处。
  在步骤 3 落地之前调它只是换一个同样没根据的数字，而步骤 3 之后这个参数根本不存在。
- **给 `unsafe_pure` 加「可信度等级」**（比如 `unsafe_pure(total)` /
  `unsafe_pure(deterministic)`）。听起来更精确，实际是让用户在**编译器无法检查**的
  维度上做更细的声明——声明越细，错得越具体。要么信要么不信。
- **在运行期验证 `unsafe_pure` 的承诺**（比如记录调用做幂等抽查）。
  纯度不是能抽查出来的性质，而抽查的开销要付在每次调用上。
- **允许 comptime 构造 Java 对象**。`eval_java` 现在明确拒绝构造器和实例方法
  （「comptime has no way to build a Java object」）。放开它等于把整个 JDK 对象图
  搬进编译器，与本文方向相反。

## 六、落地点

| 步骤 | 文件 | 测试 |
|---|---|---|
| 1 | `selfhost/src/checker.dawn`（`check_unsafe_pure` 加 `is_std_module` 判定） | checker 内联 test：用户模块用 `unsafe_pure` 报错；std 模块不报 |
| 1 | `docs/spec.md` §6.4 改写、`docs/design.md` 回填「原决策现已恢复」 | — |
| 2 | `selfhost/src/interp.dawn`（`eval_java` 查表） | interp 内联 test：表内类可折叠、表外类报错并给出表 |
| 3 | `selfhost/src/interp.dawn`（`ceval` trampoline 化） | 现有 comptime test 全绿 + 一个「深度 10 万」的 test 不再依赖宿主栈 |
| 3 | `bin/dawn`、`selfhost/src/main.dawn`、`scripts/*.sh` 去 `-Xss512m` | `selfhost-fixpoint.sh` + 全仓测试 |

**发布纪律**：步骤 1 是语言收窄 → 先发 tag。步骤 2、3 不改语言表面，
但步骤 3 会改 `spawn_java` 的 argv → 属工具链输出变化，要 `Emit-Change:`。
