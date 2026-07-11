# Dawn

一门刻意小的静态类型语言：编译到 JVM 字节码，native 可执行文件由 GraalVM
native-image 直接获得——语言对两个目标零感知。

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)

fn area(s: Shape) -> Float =
  match s {
    Circle(r)  -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io =
  [Circle(1.0), Rect(2.0, 3.0)]
    |> map(area)
    |> sum
    |> fn(t) => println("total: {t}")
```

## 三个立身特性

1. **两级效果系统**——函数默认纯，碰 IO 必须标 `!io`，编译器推导并检查。
   看签名即知函数是否碰外界；纯函数测试零 mock。
2. **comptime**——`comptime { ... }` 在编译期由解释器执行，结果烧进常量池。
   查找表、预计算、配置校验都在这里做。没有宏。
3. **Java 单向互操作**——`use java "..."` 直接调 Java 类，标准库几乎白拿；
   所有 Java 调用自动视为 `!io`，null 进不了语言（自动包 `Option`）。

## 同样重要的是没有什么

没有 null、没有异常（只有 `Result` + `?`）、没有继承、没有宏、没有 async、
没有自定义运算符、没有 trait（v0.1）。理由见 [docs/design.md](docs/design.md)。

## 文档

- [docs/design.md](docs/design.md) — 设计目标、决策记录（为什么是这样而不是那样）
- [docs/spec.md](docs/spec.md) — 语言规范（词法、语法、类型、效果、comptime、互操作、编译模型）
- [docs/grammar.ebnf](docs/grammar.ebnf) — EBNF 语法
- [examples/](examples/) — 示例程序

## 工具链

```bash
# 构建编译器（需要 JDK 21；native 编译需要 GraalVM）
gradle :compiler:fatJar

./bin/dawn run examples/m0/fizzbuzz.dawn      # 编译并运行（JVM）
./bin/dawn build foo.dawn -o app.jar          # 产出可执行 jar
./bin/dawn build foo.dawn --native -o app     # 产出独立 native 二进制
./bin/dawn lsp                                # LSP 服务器（stdio，编辑器用）
```

## 编辑器支持

内置 LSP 服务器（`dawn lsp`）：实时诊断、悬停（类型/签名）、跳转定义、文档大纲。
编译器前端做了完整的错误恢复——文件残缺时其余部分照常分析，一次报出全部错误。
VS Code 扩展与 Neovim / Helix 配置见 [editors/](editors/)。

状态：**M0、M1、M2 已实现**——验收样例 [examples/shapes.dawn](examples/shapes.dawn) 与
[examples/calc.dawn](examples/calc.dawn) 原样通过 `dawn run` 与 `dawn test`，
JVM 与 native 输出一致。

- M0：Int/Float/Bool/String、函数、match、`!io` 效果检查、自递归尾调用消除、
  字符串插值、`dawn run` / `dawn build --native`。
- M1：**ADT** + 嵌套构造器模式 + 基于 usefulness 算法（Maranget）的**穷尽性检查**
  （缺分支精确列出缺失构造器）；**record**（字面量/简写/函数式更新 `{ ..p, x: 3.0 }`/字段访问/模式）；
  **泛型**（调用点自动推导、擦除 + 装箱）+ prelude `Option`/`Result` + 内建 `List`
  （字面量、`++`、`len`/`get`/`range`、for-in）；**lambda 与效果多态**
  （按值捕获、函数类型 `fn(A) -> B !e`、效果变量随调用点实例化，
  LambdaMetafactory 在 native-image 下免配置已实测）；**`?` 传播**；
  **test 块**（`assert` 失败报两侧值，`dawn test` 执行、构建剥除）。
- M2：**comptime**（编译期求值纯 Dawn 代码，fuel 预算，结果嵌入常量池/静态字段）
  与顶层 **const**；**`use java` 互操作**（编译期反射读签名、重载打分消解、
  null 在边界包成 `Option`、全部 `!io`）；**stdlib core**（字符串函数、
  `read_file`/`write_file`/`args`、`expect`/`unwrap_or`）；**元组** + let/var
  模式解构；**列表模式** `[x, ..rest]`/`[..init, last]`（穷尽性按长度精确检查）；
  三引号多行字符串；点调用糖 `x.f(a)`；函数/内建作一等值（泛型按期望类型实例化）。

详见 [docs/design.md](docs/design.md) 里程碑。编译器 Kotlin + ASM，
测试 176 项（`gradle :compiler:test`）。native 二进制启动约 7ms。
