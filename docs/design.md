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
| trait / typeclass | 先用显式传函数顶着，疼了再加（v2 候选） |
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

## 4. 特性来源致谢

- 克制的特性集与报错质量标杆：Gleam
- 纯度/效果标记：Flix（简化到两级）
- comptime:Zig（去掉类型级编程）
- `?` 传播、表达式导向:Rust
- 管道 `|>` 首参传递:Gleam / Elixir

## 5. 里程碑

- **M0 走通**（已完成）：`Int`/`String`、函数、`match`、`!io` 检查；
  `dawn run` 与 `dawn build --native` 两条命令产出一致结果。
- **M1 像门语言**（进行中）：ADT/record/泛型、`Result`+`?`、模式穷尽性检查、test 块。
  - 已落地：ADT（含命名字段构造、嵌套构造器模式、`..`、结构相等）、
    穷尽性检查（usefulness 算法，精确列出缺失构造器）。
  - 待做：record、泛型 + `List`/`Option`/`Result`、lambda + 函数类型 + 效果变量、
    `?` 传播、test 块。
- **M2 立身特性**：comptime、Java 互操作、字符串插值、标准库 core。
- **M3 体验**：报错信息打磨、`dawn fmt`、示例与教程。
