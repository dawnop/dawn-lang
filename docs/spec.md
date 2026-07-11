# Dawn 语言规范（v0.1 草案）

本文是语法与语义的权威定义。设计动机见 [design.md](design.md)，
机器可读语法见 [grammar.ebnf](grammar.ebnf)。

规范用词：**必须**（违反即编译错误）、**保证**（实现承诺的行为）、
**未定义**（v0.1 不承诺，勿依赖）。

---

## 1. 源文件与词法

### 1.1 源文件

- 编码 UTF-8，扩展名 `.dawn`。
- 一个文件即一个模块（见 §11）。

### 1.2 注释

```dawn
# 行注释，到行尾
## 文档注释，附着于紧随其后的声明（工具链提取）
```

### 1.3 标识符与命名约定

- 值、函数、模块名：`lower_snake_case`，匹配 `[a-z][a-z0-9_]*`
- 类型与构造器：`UpperCamelCase`，匹配 `[A-Z][A-Za-z0-9]*`
- 效果变量：`!` 后接 `[a-z][a-z0-9_]*`（`io` 为保留效果名）

命名约定是**强制的**：小写开头一定是值，大写开头一定是类型/构造器。
parser 依赖这一点消歧（模式匹配中 `x` 是绑定、`X` 是构造器）。

### 1.4 关键字

```
fn let var type const use java pub
match if else for in while
comptime test assert
true false not
```

关键字不可用作标识符。`panic`、`todo` 是预置函数而非关键字。

### 1.5 字面量

| 形式 | 类型 | 说明 |
|------|------|------|
| `42`, `1_000_000`, `0xFF`, `0b1010` | `Int` | 64 位有符号；下划线可作分隔 |
| `3.14`, `1.0e-9` | `Float` | IEEE 754 double |
| `true` / `false` | `Bool` | |
| `"hello"` | `String` | 见 §1.6 |
| `()` | `Unit` | 唯一值 |
| `[1, 2, 3]` | `List[Int]` | 允许尾逗号 |
| `(1, "a")` | `(Int, String)` | 元组，2 至 8 元 |

没有字符类型；单字符用长度为 1 的 `String`（v0.1 决定，未来可能加 `Rune`）。

### 1.6 字符串与插值

双引号字符串，支持转义 `\n \t \\ \" \{` 与 Unicode `\u{1F600}`。

`{expr}` 为插值，`expr` 是任意表达式，其类型必须实现 `to_string`
（v0.1：所有内建类型与派生了 `Show` 的用户类型，见 §4.3）：

```dawn
let n = 3
println("got {n} items, first = {list.get(0)}")
```

插值内的表达式效果并入整个字符串表达式的效果。

多行字符串用三引号 `"""`，首尾换行与公共缩进被剥除。

### 1.7 换行与分号

语句由**换行**分隔，没有分号。行尾是二元运算符、`|>`、逗号、开括号时自动续行；
此外 `|>` 允许出现在**下一行行首**（竖排管道风格，惯用写法）。
惯例上一行一条语句；`dawn fmt` 负责统一。

---

## 2. 类型

### 2.1 基础类型

`Int`（64 位）、`Float`（double）、`Bool`、`String`、`Unit`。

**没有 null。** 所有类型的值都必然有效；可缺失用 `Option[T]` 表达。
**没有隐式转换。** `Int` → `Float` 必须显式 `to_float(n)`。

### 2.2 内建复合类型

- `List[T]` — 不可变持久列表
- `Option[T]` — `Some(T) | None`
- `Result[T, E]` — `Ok(T) | Err(E)`
- `Map[K, V]` — 不可变映射（v0.1 键限 `Int`/`String`）
- 元组 `(A, B, ...)`
- 函数类型 `fn(A, B) -> C !e`（`!e` 可省略，表示纯）

`Option` 与 `Result` 就是普通 ADT，在标准库中定义，无特殊地位
（`?` 运算符对它们有语法支持，见 §9）。

### 2.3 和类型（ADT）

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  | Point                       # 无载荷构造器
```

- 构造器字段**必须**带名字；构造调用可按位置或按名：`Rect(2.0, h: 3.0)`。
- 构造器在模块内是普通函数值，可传给高阶函数。
- 泛型：`type Tree[T] = | Leaf | Node(left: Tree[T], value: T, right: Tree[T])`

### 2.4 记录（record）

```dawn
type Point = { x: Float, y: Float }

let p = Point { x: 1.0, y: 2.0 }
let q = Point { ..p, x: 3.0 }     # 函数式更新
let d = p.x                        # 字段访问
```

记录是单构造器积类型的糖，同样支持模式匹配。字段不可变——"修改"即函数式更新。

### 2.5 泛型

- 类型参数用 `[T, U]` 声明在名字后：`fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`
- 单态性：类型参数在每个调用点必须能完全推导，不支持高阶类型（HKT）。
- 实现为擦除 + 装箱（v0.1）；单态化留作后续优化，不影响语义。
- **没有子类型、没有继承、没有变型（variance）**。类型要么相等要么不同。

### 2.6 类型别名

```dawn
type Meters = Float          # 透明别名（v0.1 只有透明别名，不是 newtype）
```

---

## 3. 声明

模块顶层只允许：`use`、`type`、`const`、`fn`、`test`。没有顶层可变状态。

### 3.1 函数

```dawn
fn add(a: Int, b: Int) -> Int = a + b

fn greet(name: String) -> Unit !io = {
  println("hi, {name}")
}
```

- 顶层函数**必须**写全参数类型与返回类型（文档即契约）；效果标记可省略，
  省略时由编译器推导，但**推导结果若含 io 而签名未标则报错**——签名是承诺。
- 函数体是 `=` 后的单个表达式；块 `{ }` 也是表达式（§5.2）。
- 没有默认参数、没有变长参数、没有重载。

### 3.2 常量

```dawn
const MAX_DEPTH: Int = 64
const SIN_TABLE: List[Float] = comptime {
  range(0, 360) |> map(fn(d) => sin(to_radians(d)))
}
```

顶层 `const` 的右侧隐式处于 comptime 上下文（§8），必须是纯的、可常量化的。

### 3.3 可见性

所有声明默认模块私有；`pub` 导出。`pub` 可用于 `fn`、`type`、`const`。
`pub type` 同时导出其构造器与字段。

### 3.4 测试块

```dawn
test "precedence" {
  assert eval("2+3*4") == Ok(14)
}
```

- `test` 块只被 `dawn test` 编译执行，`dawn build` 剥除。
- 块内允许 `!io`。
- `assert expr`：`expr` 为 `Bool`；失败时报告源文本与两侧子表达式的值
  （编译器对 `==`、比较运算符做拆解以给出好的失败信息）。

---

## 4. 表达式

Dawn 是表达式导向的：`if`、`match`、块都产生值。

### 4.1 绑定

```dawn
let x = 42              # 不可变绑定，类型推导
let y: Float = 1.0      # 可选标注
var acc = 0             # 可变局部变量
acc = acc + 1           # 赋值，仅对 var 合法
```

- `let` 不可变、不可遮蔽（同一作用域重复绑定同名是错误；嵌套作用域允许遮蔽）。
- `var` 仅限函数体内的局部变量；record 字段、参数、顶层均不可变。
- 赋值是语句（类型 `Unit`），不是表达式——`if (x = 1)` 这类错误不存在。

### 4.2 块

```dawn
let area = {
  let w = 3.0
  let h = 4.0
  w * h                  # 最后一个表达式是块的值
}
```

块引入新作用域；最后一个表达式是块的值，其余语句必须是 `Unit` 类型
（防止悄悄丢弃 `Result`——丢弃非 Unit 值必须显式 `let _ = ...`）。

### 4.3 运算符与优先级

自低到高：

| 优先级 | 运算符 | 结合性 | 说明 |
|--------|--------|--------|------|
| 1 | `\|>` | 左 | 管道，见 §4.4 |
| 2 | `\|\|` | 左 | 逻辑或，短路 |
| 3 | `&&` | 左 | 逻辑与，短路 |
| 4 | `== != < <= > >=` | 不结合 | 比较；链式比较是语法错误 |
| 5 | `++` | 右 | `String`/`List` 连接 |
| 6 | `+ -` | 左 | 仅数值，两侧同类型 |
| 7 | `* / %` | 左 | 仅数值；`Int` 除零 panic |
| 8 | `not`、一元 `-` | 前缀 | |
| 9 | `? . () []调用` | 后缀 | `?` 见 §9 |

- `==`/`!=` 是结构相等，对任意类型可用（函数类型除外——比较函数是编译错误）。
- 排序比较 `< <=` 等仅 `Int`/`Float`/`String`。
- 用户类型的打印：`type` 声明后加 `derive Show` 获得 `to_string`
  （v0.1 仅有 `Show` 这一个 derive）。

### 4.4 管道

`x |> f(a, b)` 等价于 `f(x, a, b)`——把左侧塞进**第一个参数**。
`x |> f` 等价于 `f(x)`。标准库 API 均按"主数据是第一参"设计以配合管道。

### 4.5 Lambda

```dawn
let double = fn(x: Int) => x * 2
let add = fn(a, b) => a + b       # 参数类型可推导时可省略
xs |> map(fn(x) => x * x)
```

- `fn(params) => expr`；body 要多条语句就用块 `fn(x) => { ... }`。
- 闭包按值捕获绑定（捕获 `var` 是编译错误——想共享可变状态请显式传递）。

### 4.6 if

```dawn
let sign = if x > 0 { 1 } else if x < 0 { -1 } else { 0 }
```

- 条件必须是 `Bool`，分支体必须是块。
- 作为值使用时 `else` 必须存在且分支同类型；
  作为语句（值被丢弃）时可省 `else`，此时分支必须是 `Unit`。

### 4.7 循环

```dawn
for x in [1, 2, 3] { println("{x}") }
while queue.non_empty() { ... }
```

- `for`/`while` 是 `Unit` 类型的语句，体内可用 `var` 累积。
- 没有 `break`/`continue`（v0.1）；复杂控制流请写递归——尾递归保证成环（§12.4）。
- `for x in a..b` 支持右开区间的整数范围。

惯用风格优先 `map`/`filter`/`fold`；循环是给性能敏感处和口味用的。

---

## 5. 模式匹配

```dawn
match shape {
  Circle(r) if r > 100.0 -> "big circle"
  Circle(r)              -> "circle {r}"
  Rect(w, h)             -> "rect {w}x{h}"
  Point                  -> "point"
}
```

### 5.1 模式形式

| 模式 | 例 | 匹配 |
|------|-----|------|
| 字面量 | `0`, `"yes"`, `true` | 相等则匹配 |
| 绑定 | `x` | 恒匹配并绑定 |
| 通配 | `_` | 恒匹配不绑定 |
| 构造器 | `Some(x)`, `Rect(w, h)`, `Rect(w: w, ..)` | 按位置或按名解构，`..` 忽略其余字段 |
| 记录 | `Point { x, .. }` | 字段解构 |
| 元组 | `(a, b)` | |
| 列表 | `[]`, `[x, ..rest]` | 空表 / 头与余下 |
| 或 | `0 \| 1 \| 2` | 任一匹配（各分支绑定必须一致） |
| 守卫 | `pat if cond` | 模式匹配且守卫为真 |

### 5.2 穷尽性

`match` **必须穷尽**。编译器对 ADT/Bool/Option/Result/元组做穷尽性检查，
缺分支报错并列出缺失构造器。`Int`/`String`/`Float` 上的 match 必须有
`_` 或绑定兜底分支。

`let` 也接受不可反驳模式：`let (a, b) = pair`、`let Point { x, y } = p`。

---

## 6. 效果系统

### 6.1 模型

效果格子只有两点：**pure**（默认、不写）与 **io**。
`!io` 覆盖一切可观测副作用：文件、网络、时钟、随机数、打印、可变全局态、
以及全部 Java 互操作。

### 6.2 规则

1. 函数体的效果 = 体内所有调用效果的并。
2. 签名未标 `!io` 的函数，体内出现 io 效果 → 编译错误
   （报错指出哪个调用引入了 io，并建议在签名加 `!io` 或消除该调用）。
3. 标了 `!io` 但体是纯的 → 允许（预留演化空间），`dawn fmt --check` 提示。
4. 纯函数**保证**：给定相同参数返回相同值、无可观测副作用。
   编译器可据此折叠、消重、在 comptime 调用。
5. `panic`/`todo`/`assert` 不算 io——它们不返回（发散不是效果）。

### 6.3 效果多态

高阶函数用效果变量转发参数的效果：

```dawn
fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2)
```

- 效果变量 `!e` 无需声明，在签名中出现即引入；作用域是整条签名。
- `!(e1 | e2)` 为并。因为格子只有两点，求解就是布尔或——推导必然可判定。
- 调用点实例化：`map(xs, println)` 中 `e = io`，故整个调用是 io。

### 6.4 逃生门

`@trusted_pure` 注解可将一个 `!io` 表达式断言为纯（如缓存、日志式调试）。
**仅标准库内部可用**，用户代码使用是编译错误。v0.1 不向用户开放任何纯度逃生门。

---

## 7. comptime

### 7.1 形式

```dawn
const CRC_TABLE: List[Int] = comptime { crc32_table() }

fn lookup(d: Int) -> Float =
  SIN_TABLE.get(d % 360).expect("table covers 0..360")
```

`comptime { ... }` 是表达式：编译期由编译器内置解释器求值，
结果作为常量嵌入产物。顶层 `const` 的右侧隐式处于 comptime 上下文。

### 7.2 约束

1. comptime 代码**必须是纯的**（可调用任何纯函数，包括本模块与依赖模块的）。
2. 结果类型必须**常量可序列化**：`Int`/`Float`/`Bool`/`String`/`Unit`、
   以及仅由这些组成的 `List`/`Map`/元组/record/ADT。函数值不行。
3. 求值有步数预算（默认 10⁸ 步，`--comptime-fuel` 调整），超限报错——
   保证编译必然终止。
4. comptime 里没有 Java 互操作、没有 io（由约束 1 自动保证）。

### 7.3 明确不做

comptime **不能**生成类型、不能生成声明、不能内省 AST。
它只是"提前跑一段纯 Dawn 代码"。元编程不是 v0.1 的目标。

---

## 8. 错误处理

### 8.1 可恢复：Result / Option + `?`

```dawn
fn parse_config(path: String) -> Result[Config, String] !io = {
  let text = read_file(path)?          # Err 时提前返回该 Err
  let json = json.parse(text)?
  Config.from_json(json)
}
```

- 后缀 `?` 作用于 `Result[T, E]`：`Ok(v)` 解出 `v`，`Err(e)` 使**当前函数**
  立即返回 `Err(e)`。对 `Option[T]` 同理（`None` 提前返回 `None`）。
- `?` 所在函数的返回类型必须是相容的 `Result`/`Option`（`E` 类型必须一致，
  v0.1 无自动错误类型转换）。
- 这是 v0.1 中唯一的非局部控制流。

### 8.2 不可恢复：panic

`panic(msg)`：打印消息与 Dawn 层栈迹，进程以非零退出。
`todo()` 等价于 `panic("not yet implemented")` 且能通过任意类型检查
（返回类型为底类型 `Never`）。

数组越界式错误不存在（`List.get` 返回 `Option`）；`Int` 除零 panic。

---

## 9. Java 互操作

### 9.1 引入与调用

```dawn
use java "java.nio.file.Files"
use java "java.nio.file.Path"
use java "java.lang.StringBuilder"

fn slurp(p: String) -> Option[String] !io =
  Files.readString(Path.of(p).expect("valid path"))

fn build() -> String !io = {
  let sb = StringBuilder.new()      # 构造器统一拼写为 .new
  sb.append("a")
  sb.append("b")
  sb.toString().expect("non-null")
}
```

- `use java "全限定名"` 把类引入为：一个不透明类型 + 一个静态方法命名空间。
  静态字段（如 `System.out`）v0.1 不支持——只有方法。
- 构造器统一为 `Type.new(args)`，**返回 `T` 本身**（构造器不会返回 null，不包 Option）；
  实例方法用 `.method(args)`。
- **所有 Java 调用的效果都是 `!io`**，无例外（理由见 design.md D5）。
- **Java 调用的返回值允许直接丢弃**（语句位置或 Unit 块的尾位置）——Java API 常返回
  `this` 或状态码；「不得悄悄丢弃」规则只保护 Dawn 值。
- 返回值里出现**未导入的引用类**（如 `Path.of` 的 `Path`）时，值仍可用（自动成为
  不透明类型、可继续链式调用）；只有要在签名里**写出类型名**才需要 `use java` 导入。

### 9.2 类型映射

| Dawn | Java | 方向 |
|------|------|------|
| `Int` | `long`（接收 `int` 自动加宽） | 双向 |
| `Float` | `double` | 双向 |
| `Bool` | `boolean` | 双向 |
| `String` | `java.lang.String` | 双向 |
| `Unit` | `void` | 返回 |
| 引入的类 `T` | 该类引用 | 双向 |

**Java 返回引用类型一律为 `Option[T]`**——null 在边界处被拦下。
基本类型返回值不包 Option；`short`/`byte`/`int` 返回自动加宽为 `Int`，`float` 加宽为
`Float`。`char` 与数组的出入参 v0.1 不支持。**Option 实参传 null** 同样推迟
（v0.1 无法从 Dawn 侧传 null 给 Java）。

### 9.3 重载消解

按"实参个数 + 静态类型"打分选唯一候选（精确匹配 `long`/`double` 优于收窄到
`int`/`float`，`String` 优于 `CharSequence`/`Object`）；并列最高分或无候选都是
编译错误（错误信息列出候选签名）。变长参数方法只支持**不传可变部分**的调用
（自动补一个空数组，如 `Path.of(p)`）；传可变实参 v0.1 不支持。

### 9.4 限制

不能继承 Java 类、不能实现 Java 接口、不能把 Dawn 函数作为
lambda 传给 Java（v0.1；这是为 native-image 免配置保留的边界）。
需要回调的场景请在 Dawn 侧轮询或用标准库封装。

---

## 10. 模块系统

- 一个 `.dawn` 文件 = 一个模块；模块路径 = 相对项目根的目录路径 + 文件名：
  `src/geo/shape.dawn` → `geo/shape`。
- 引入：`use geo/shape`（整个模块，限定访问 `shape.area(s)`）或
  `use geo/shape.{Shape, area}`（选择性引入，非限定使用）。
- 循环 `use` 是编译错误。
- 入口：main 模块的 `pub fn main() -> Unit !io`。
- 标准库模块隐式可用的部分（prelude）：`List`/`Option`/`Result` 的构造器、
  `map`/`filter`/`fold`/`range`/`println` 等约 30 个常用名。

---

## 11. 标准库草案（v0.1 范围）

- `core/list`：`map filter fold len get take drop reverse sort concat range ...`
- `core/string`：`chars split join trim starts_with ends_with contains
  parse_int parse_float to_string ...`（字符串转数字是 `parse_int(s) -> Option[Int]`——
  没有重载，`to_int`/`to_float` 只做 Int↔Float 转换）
- `core/option` / `core/result`：`map unwrap_or expect and_then ...`
- `core/map`：`insert get remove keys values ...`（持久映射）
- `core/math`：`abs min max sin cos sqrt pow to_float to_int ...`（纯——
  内部以 `@trusted_pure` 包装 `java.lang.Math`）
- `io`：`println read_line read_file write_file args env ...`（全部 `!io`）

实现策略：能薄包 Java 就薄包（`String` 直接是 `java.lang.String`），
持久 `List`/`Map` 自实现（Dawn 写，自举前先 Kotlin 写）。

---

## 12. 编译模型

### 12.1 产物

| 命令 | 产物 |
|------|------|
| `dawn run main.dawn` | 编译到内存/临时目录，起 JVM 执行 |
| `dawn build -o app.jar` | 可执行 jar（`Main-Class` 已设） |
| `dawn build --native -o app` | 前一步 + `native-image`，独立二进制 |
| `dawn test` | 编译含 test 块的变体并执行 |

**保证**：同一程序在 JVM 与 native 下行为一致（除启动时间与内存占用）。

### 12.2 字节码映射

| Dawn 构造 | JVM 实现 |
|-----------|----------|
| 模块 | 一个类，函数为 static 方法 |
| ADT | abstract class + final 子类；无载荷构造器为单例 |
| record | final class + 字段（不依赖 Java record，兼容旧字节码目标） |
| `match` | `instanceof` 链 + 字段读取（不用 indy、不用 pattern switch） |
| lambda/闭包 | `LambdaMetafactory`（native-image 支持名单内） |
| 泛型 | 擦除 + 装箱 |
| `Int`/`Float`/`Bool` | 原生 `long`/`double`/`boolean`，仅泛型位置装箱 |
| `panic` | 抛 `dawn.rt.PanicError`（Error 子类，不可被 Dawn 捕获） |

### 12.3 native-image 契约

语言构造**保证**不产生：反射调用、自定义 indy bootstrap、动态类加载、
JNI（Java 互操作走普通 invoke）。因此 `--native` 构建不需要
reachability 配置。若引入的 Java 库自身用反射，责任在库——错误信息会提示
这超出 Dawn 的保证范围。

### 12.4 尾调用

**自递归尾调用保证**编译为循环（不长栈）。互递归尾调用 v0.1 不保证。
判定规则：函数体内对自身的调用处于尾位置（返回位置、match/if 分支的
尾位置、块的末表达式）。

---

## 13. 语法速查

```dawn
# ---- 声明 ----
use geo/shape.{Shape, area}
use java "java.nio.file.Files"

pub type Color = | Red | Green | Blue derive Show
type Point = { x: Float, y: Float }
const ORIGIN: Point = Point { x: 0.0, y: 0.0 }

pub fn dist(a: Point, b: Point) -> Float =
  sqrt(pow(a.x - b.x, 2.0) + pow(a.y - b.y, 2.0))

# ---- 表达式 ----
let n = 42                       var acc = 0
let (a, b) = pair                acc = acc + 1
if x > 0 { "pos" } else { "non-pos" }
match opt { Some(v) -> v, None -> fallback }
xs |> filter(fn(x) => x > 0) |> map(to_string) |> join(", ")
read_file(path)?                 # Result 传播
comptime { heavy_pure_calc() }   # 编译期求值

# ---- 测试 ----
test "dist is symmetric" {
  assert dist(p, q) == dist(q, p)
}
```

---

## 14. 未来方向（明确不在 v0.1）

按优先级：trait/typeclass（显式传函数疼了之后）、细分效果（`!fs`、`!net`）、
互递归尾调用、`break`/`continue`、Dawn lambda 传给 Java、newtype、
单态化优化、`Rune` 类型。
