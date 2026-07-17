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
trait impl
true false not
```

关键字不可用作标识符。`panic`、`todo` 是预置函数而非关键字；`derive` 是
上下文关键字（只出现在 `type` 声明尾部）。

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
| `'a'`, `'\n'`, `'世'`, `'\u{1F600}'` | `Int` | 字符字面量 = **码点**（见下） |

**字符字面量走 Go 的 rune 路线**：`'x'` 不是独立类型，而是等于该字符**码点**的 `Int`
字面量（`'a' == 97`）。因此 match 里它就是普通 `Int` 模式，类型系统零改动。单引号内是
单个码点：转义与字符串相同（`\n \t \\ \u{...}`）另加 `\'`；空字面量或含多个码点 → 词法错误。
按码点处理字符串的内建见 §11（`code_points`/`from_code_points`/`str_len`/`substring`）。
没有独立字符类型（Go/Rune 模型使其无必要）。

### 1.6 字符串与插值

双引号字符串，支持转义 `\n \t \\ \" \$` 与 Unicode `\u{1F600}`。
**花括号 `{` `}` 是普通字符，无需转义**——写 JSON、CSS、代码生成很方便。

插值由 `$` 引导（同 Kotlin/Swift）：`$name` 插入一个简单标识符，`${expr}` 插入
任意表达式；被插值的类型必须实现 `to_string`（v0.1：所有内建类型与派生了 `Show`
的用户类型，见 §4.3）：

```dawn
let n = 3
println("got $n items, first = ${list.get(0)}")
```

`$` 后不接标识符或 `{` 时就是字面美元号（`"$5"` 无需转义）；要强制字面 `$` 用 `\$`。
插值内的表达式效果并入整个字符串表达式的效果。

多行字符串用三引号 `"""`，首尾换行与公共缩进被剥除；插值规则相同。

**raw string 用反引号**：`` `...` `` 之间的一切都是字面量——无转义、无插值、
可跨行、不剥缩进，所见即值。唯一限制是内容里不能出现反引号本身（也没有逃生舱，
要写反引号就用普通字符串）。三种形式死角互补：含反引号 → `"..."`；
要插值的模板 → `"""`；含引号与 `$` 的原样文本（正则、代码样本、HTML）→ 反引号。

### 1.7 换行与分号

语句由**换行**分隔，没有分号。行尾是二元运算符、`|>`、逗号、开括号时自动续行；
此外 `|>` 允许出现在**下一行行首**（竖排管道风格，惯用写法）。
惯例上一行一条语句；`dawn fmt` 负责统一。

### 1.8 `dawn fmt`

`dawn fmt <文件>...` 就地格式化；`dawn fmt --check <文件>...` 只报告未格式化的文件
（有则退出码 1，供 CI）。实现是**基于 token 流的重排器**：逐 token 按原样重印
（字符串与插值按源码区间原样保留，一字不改），只改动 token 间的空白——行内间距、
2 空格缩进、折叠连续空行（保留作者的物理换行）。故格式化**保 token、保注释、幂等**，
且只需词法成功（不需能解析），语法错误的文件也能格式化。要点：缩进 2 空格；
二元运算符/`->`/`=>`/`=`/`|>` 两侧各 1 空格；`,`/`:` 后 1 前 0；`(`/`[` 内侧贴紧；
`.`/`?` 贴紧；不折超长行（作者断的行保留）。

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
- `Map[K, V]` — 不可变映射（见下）
- `Set[T]` — 不可变集合（见下）
- 元组 `(A, B, ...)`
- 函数类型 `fn(A, B) -> C !e`（`!e` 可省略，表示纯）

`Option` 与 `Result` 就是普通 ADT，在标准库中定义，无特殊地位
（`?` 运算符对它们有语法支持，见 §9）。

**`Map[K, V]` / `Set[T]`** 是与 `List` 同级的内建持久容器，无字面量语法，全部经
内建函数操作（清单见 §11）。语义要点：

- **持久（不可变）接口**：`map_insert`/`map_remove` 返回新映射，原值不变。
- **键类型**可以是任何具**结构相等**的类型（`Int`/`String`/`Bool`/元组/ADT/record）——
  不再限于 `Int`/`String`。实现要求这些类型有与结构相等一致的哈希（编译器为 ADT/元组/
  record 自动生成 `hashCode`）。
- **迭代顺序 = 插入顺序**，确定且 JVM/native 一致（`map_keys`/`map_entries`/`set_to_list`
  按插入序）。`map_insert` 遇已存在的键**替换值、保留原插入位置**。
- **相等与顺序无关**：两个键值对相同的 `Map` 相等，无论插入次序。
- v0.1 实现为 copy-on-write（每次写复制底层结构，O(n)）；后续可换持久数据结构而不动接口。

### 2.3 和类型（ADT）

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  | Point                       # 无载荷构造器
```

- 构造器字段**必须**带名字；构造调用可按位置或按名：`Rect(2.0, h: 3.0)`。
- 构造器（含字段的）裸名在函数位置是**普通函数值**：`map(xs, Some)` 等价于
  `map(xs, fn(x) => Some(x))`。类型参数从期望的函数类型推导（`Some` 的元素类型来自
  上下文）；仅由字段无法确定的类型参数（如 `Ok` 的错误类型 `E`）需上下文补足，
  否则报「无法推导类型参数」。无载荷构造器（`Point`）本身是值不是函数；记录构造用
  花括号语法，不参与此规则。
- 泛型：`type Tree[T] = | Leaf | Node(left: Tree[T], value: T, right: Tree[T])`

### 2.4 记录（record）

```dawn
type Point = { x: Float, y: Float }

let p = Point { x: 1.0, y: 2.0 }
let q = Point { ..p, x: 3.0 }     # 函数式更新
let d = p.x                        # 字段访问
```

记录是单构造器积类型的糖，同样支持模式匹配。字段不可变——"修改"即函数式更新。

**fn 类型的字段可以直接调用**：`r.f(x)` 调用字段里存的函数值，等价于
`let g = r.f` 后 `g(x)`；字段的效果照常并入调用方。仅当作用域里**不存在**
名为 `f` 的函数时才按字段调用解释——同名函数存在时维持 UFCS 语义（§4.4），
该规则纯增量。

### 2.5 泛型

- 类型参数用 `[T, U]` 声明在名字后：`fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`
- 单态性：类型参数在每个调用点必须能完全推导，不支持高阶类型（HKT）。
- 实现为擦除 + 装箱（v0.1）；单态化留作后续优化，不影响语义。
- **没有子类型、没有继承、没有变型（variance）**。类型要么相等要么不同。
- 函数体内的局部标注可以引用签名的类型参数（`let acc: List[T] = []`）——
  刚性类型参数在推断里视同已知的具体类型。

### 2.6 类型别名

```dawn
type Meters = Float                                  # 内建标量
type Pair = (Int, String)                            # 元组
type Names = List[String]                            # 泛型应用
type Handler = fn(Request) -> Result[Response, HttpError] !io   # 函数类型
type Lookup[T] = fn(String) -> Option[T]             # 可带类型参数
```

别名是**透明**的（不是 newtype）：解析期展开，与被指的类型完全互换。

**与单构造器 ADT 的区分**（`type Color = Red` 仍是 ADT）：`=` 右侧是
`fn` 类型、元组、带参的 `Name[...]`、或裸内建标量（`Int/Float/Bool/String/Unit`，
它们永远不可能是构造器名）时按别名解析；其余裸大写名维持 ADT 语义。

限制：别名不可递归（环报错）；不可携带效果变量（只能 `!io` 或纯）；
`pub` 后可跨模块导入（`use m.{Handler}`）。

---

## 3. 声明

模块顶层只允许：`use`、`type`、`const`、`fn`、`test`。没有顶层可变状态。

### 3.1 函数

```dawn
fn add(a: Int, b: Int) -> Int = a + b

fn greet(name: String) -> Unit !io = {
  println("hi, $name")
}
```

- **参数类型必须写全**（所有函数）；`pub fn` 还必须写返回类型——公开签名是 API 契约。
- **私有函数可以省略返回类型**：`fn double(x: Int) = x * 2`。省略时返回类型与效果
  都从函数体推导（想强制效果仍可写 `!io`）。三类函数**必须**标注返回类型：
  ① `pub`；② 递归/互递归（编译器按调用图拓扑序推导，环上无法推导）；
  ③ 体内用了 `return` 或 `?`（二者需要已知的返回类型）。
- 写了 `-> T` 的函数维持原规则：效果省略即纯，**体内出现 io 而签名未标则报错**——签名是承诺。
- 函数体是 `=` 后的单个表达式；块 `{ }` 也是表达式（§5.2）。
- 没有默认参数、没有变长参数、没有重载。

**局部命名函数**：块内可写 `fn name(params) -> T [!io] = body` 语句——本质是
「名字在自身 body 内可见的 lambda」，因此**可递归**（自尾调用编译为循环，§12.4）、
可捕获外围绑定（按值，同 lambda 规则）、可当值传递。参数类型与返回类型必须写全；
效果只能是 `!io` 或纯（效果多态请提升到顶层）；不可声明类型参数（外围函数的类型参数天然在作用域内）。

```dawn
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}
```

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

### 3.5 trait 与 impl

单参数、名义式的 typeclass，字典传递实现（完整设计与判定规则见
[trait.md](trait.md)）：

```dawn
trait Ord2[T] {
  fn cmp2(a: T, b: T) -> Int
  fn max_of(a: T, b: T) -> T = if cmp2(a, b) >= 0 { a } else { b }  # 默认体
}

impl Ord2[Point] {
  fn cmp2(a: Point, b: Point) -> Int = a.x - b.x
}

fn sort2[T: Ord2](xs: List[T]) -> List[T] = ...   # 约束：[T: Trait (+ Trait)*]
```

- trait 恰有一个类型参数；方法进入模块函数命名空间（可直呼、可 UFCS、可管道）。
- **一致性**：全程序每个「trait × 类型」至多一个 impl；**孤儿规则**：impl 只能
  写在 trait 或主体类型的声明模块。impl 全局生效，不需要 `use`。
- v1 主体：非泛型具名类型与 `Int`/`Float`/`Bool`/`String`；无条件 impl、无 dyn、
  无 supertrait。trait 方法效果只能是纯或 `!io`，impl 的效果 ⊑ trait 声明。
- 预置 `trait Ord[T] { fn cmp(a: T, b: T) -> Int }` 及 `Int`/`Float`/`String`
  的 impl；`derive Ord` 生成字段字典序比较（和类型先比构造器声明顺序），字段须为
  `Int`/`Float`/`String` 或自身具 Ord impl 的类型。
- 限制：trait 方法与带约束的函数不可用作函数值（提示包 lambda）；comptime 中
  不允许 trait 约束的调用与 impl 排序。

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
- 排序比较 `< <=` 等：`Int`/`Float`/`String` 原生有序；其他类型桥接到预置
  trait `Ord` 的 `cmp`（见 §3.5）——有 impl（手写或 `derive Ord`）即可比较，
  受 `[T: Ord]` 约束的类型参数同理。
- 用户类型的打印：`type` 声明后加 `derive Show` 获得 `to_string` 与字符串插值支持
  （可 derive 的还有 `Ord`，见 §3.5；多个用逗号：`derive Show, Ord`）。
  渲染形如合法 Dawn 源码：
  - 无载荷构造器 → `Red`；带位置字段的构造器 → `Circle(1.5)`；
  - 记录 → `Point { x: 0.0, y: 2.5 }`（带字段名）；
  - `String` 字段带双引号并转义（`"a\nb"`）；`Int`/`Float`/`Bool` 同各自 `to_string`；
  - 容器递归渲染：`List` → `[a, b]`、元组 → `(a, b)`、`Option`/`Result` 随载荷（`Some(Red)`）。
  - 每个字段类型必须可打印（函数字段、未 `derive Show` 的嵌套用户类型 → 声明处报错）；
    泛型类型可打印 **当且仅当** 其类型实参都可打印（`Box[Int]` 可，`Box[fn(...)→...]` 不可）。

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
for x in [1, 2, 3] { println("$x") }
while queue.non_empty() { ... }
```

- `for`/`while` 是 `Unit` 类型的语句，体内可用 `var` 累积。
- 没有 `break`/`continue`（v0.1）；复杂控制流请写递归——尾递归保证成环（§12.4）。
- `for x in a..b` 支持右开区间的整数范围。

惯用风格优先 `map`/`filter`/`fold`；循环是给性能敏感处和口味用的。

### 4.8 下标

```dawn
let x = xs[i]        # List[T] -> T；越界 panic（含负数）
let v = m["key"]     # Map[K, V] -> V；缺键 panic（消息含键值）
let c = rows[1][0]   # 可链式、可与 ?/./() 组合
```

- **`[]` 是断言，get 家族是问询**：`xs[i]` 用于「下标必然合法，越界是 bug」的场合
  （panic 语义，同 Rust）；越界/缺键是正常分支时用 `get(xs, i)` / `map_get(m, k)`（返回 `Option`）。
- 下标只作用于 `List`（下标为 `Int`）与 `Map`（下标为键类型），其余类型是编译错误。
- comptime 中支持 `List` 下标（越界为编译错误）。
- 只读——列表与映射是不可变的，没有 `xs[i] = v`。

### 4.9 return

```dawn
fn classify(n: Int) -> String = {
  if n < 0 { return "negative" }   # guard 子句
  if n == 0 { return "zero" }
  "positive"
}
```

- `return expr` / 裸 `return`（仅 `Unit` 函数）从**最内层函数**提前返回——
  在 lambda 内则退出该 lambda（同 `?` 的作用域规则）。
- `return` 是类型为 `Never` 的表达式，可出现在任意表达式位置（如 match 分支）。
- 所在函数（或 lambda 的期望类型）必须已声明返回类型——省略返回类型的推导函数内不可用。

---

## 5. 模式匹配

```dawn
match shape {
  Circle(r) if r > 100.0 -> "big circle"
  Circle(r)              -> "circle $r"
  Rect(w, h)             -> "rect $wx$h"
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
3. 标了 `!io` 但体是纯的 → 允许（预留演化空间）；「多余 `!io`」的 lint 需要类型分析，
   v0.1 的 `dawn fmt --check` 只做格式检查、**未实现**该提示（留待后续）。
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
- `!(e1 | e2)` 为并，**规范化**后存储：`io` 吸收一切（含 `io` 的并即 `io`）、`pure`
  是幺元（可省去）、单个变量的并降级为该变量本身（`!(e|e)` 即 `!e`）。因为格子只有
  两点，求解就是布尔或——推导必然可判定。
- 调用点实例化：`compose(inc, tag)` 若 `inc` 纯、`tag` 为 `!io`，则结果类型的效果并
  规范化为 `!io`；两者皆纯则规范化为纯，结果可在纯上下文调用。
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

**后缀 `!`**：`o!` 把 `Option[T]` 解成 `T`，`None` 则 panic。语义同
`expect(o, msg)`，唯一区别是**消息由编译器生成**——含产生 `None` 的调用与源位置
（`unwrapped None from URI.create() at src/http.dawn:23`），故不必为它编造占位串。

```dawn
let uri = URI.create(url)!                      # 而不是 .expect("uri")
let base = HttpRequest.newBuilder()!.uri(uri)!  # 而不是 .expect("b") / .expect("b-uri")
```

`!` 存在的理由就是 §9.2：Java 把**引用返回一律包成 `Option`**，而绝大多数 JDK 方法
其实永不返回 null，于是解包是常态。

- 只作用于 `Option`。`Result` 用 `?` 传播（§8.1）或 `match`。
- 与 `.`/`[]` 同级、左结合：`a()!.b()!` 即 `((a()!).b())!`。
- 行尾可以是 `!`——它不是二元运算符，故不触发续行（§1.7）。
  `x! != v` 中 `!=` 仍是一个 token（先按最长匹配切分），比较的是解包后的值。
- **确有话要说**时仍用 `expect(o, "原因")`——它就是为此存在。

`get`/`map_get` 返回 `Option`（问询）；下标 `xs[i]`/`m[k]` 越界/缺键 panic（断言，§4.8）；
`Int` 除零 panic。

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
- 类解析发生在**编译期反射**：JDK 类恒可见；第三方类须以 `--cp <jars>` 提供
  （`dawn run/test/build` 通用，§12.1），编译与运行共用同一份 classpath。
  LSP v0.1 仅解析 JDK 类，第三方类在编辑器里报未找到但命令行可编译。
- **嵌套类用点号写**：`use java "java.net.http.HttpResponse.BodyHandlers"`
  （不是 `$`——`$` 在字符串里会被当插值）。解析时先整体反射，失败则从右往左把
  `.` 逐个换成 `$` 重试，故任意嵌套深度都能用点号书写；绑定名取最后一段
  （`BodyHandlers`）。嵌套类的**泛型方法**仍按擦除返回不透明 `Object`（§9.2）——
  如 `HttpResponse.body()` 返回 `Object`，取字符串体用 `String.valueOf(...)` 桥回。

### 9.2 类型映射

| Dawn | Java | 方向 |
|------|------|------|
| `Int` | `long`（接收 `int` 自动加宽） | 双向 |
| `Float` | `double` | 双向 |
| `Bool` | `boolean` | 双向 |
| `String` | `java.lang.String` | 双向 |
| `Unit` | `void` | 返回 |
| 引入的类 `T` | 该类引用 | 双向 |

**Java 方法返回引用类型一律为 `Option[T]`**——null 在边界处被拦下。用 `!` 解包（§8.2）
或 `match` 处理：

```dawn
let uri = URI.create(url)!          # 方法：包 Option，解包
let sb = StringBuilder.new()        # 构造子：不包，直接是对象
```

**为什么方法包、构造子不包**——这不是两套随意的规则，而是各有依据：

- **构造子不包**：JLS 保证 `new` 表达式**永不**返回 null，包成 `Option` 是纯噪音。
- **方法包**：方法**可以**返回 null，且编译器**无从静态区分**。JDK 类不携带运行期可见的
  可空性注解——`URI.create`（永不 null）与 `Map.get`（真可空）反射出来的注解**都是空**。
  既然分不出，就只能一律包：宁可让 `!` 显式承担风险，也不把 null 放进 Dawn。

基本类型返回值不包 Option；`short`/`byte`/`int` 返回自动加宽为 `Int`，`float` 加宽为
`Float`。`char` 出入参 v0.1 不支持；数组走不透明直通（§9.5）。**Option 实参传 null**
同样推迟（v0.1 无法从 Dawn 侧传 null 给 Java）。

### 9.3 重载消解

按"实参个数 + 静态类型"打分选唯一候选（精确匹配 `long`/`double` 优于收窄到
`int`/`float`，`String` 优于 `CharSequence`/`Object`）；并列最高分或无候选都是
编译错误（错误信息列出候选签名）。函数值实参只匹配函数式接口形参（§9.4）；
Dawn `List` 实参可匹配 `List`/`Collection`/`Iterable` 形参（§9.6）；数组实参精确匹配
优于宽化到 `Object`（§9.5）。

**变长参数**照 JLS 分两相：**先不打包**试一轮（相位 1），全部失败才**按变参打包**
（相位 2）；**相位优先于分数**——分数是逐参求和、随实参个数增长，不分相位会让打包
候选反超精确匹配。可变部分内联铺开，与 Java 写法一致：

```dawn
let p = Path.of("a", "b", "c")!                  # 打包成 String[]，得 a/b/c
let l = List.of("a", "b")!                       # 相位 1 胜：选 of(E, E)
let e = List.of()!                               # 不传可变部分 = 打包 0 个 = 空数组
let b = BodyPublishers.concat(head, file, tail)! # 可变部分可放 Java 引用
```

尾部实参逐个对**数组分量类型**打分，规则同普通形参，故 SAM 转换（§9.4）与 List 桥
（§9.6）在可变部分内同样可用。传一个**现成数组**当可变部分（如 `String[]`）走相位 1，
原样传入不重新打包。注意标量不装箱（§9.2），故 `Object...` 收 `String` 与 Java 引用，
**收不了 `Int`/`Float`/`Bool`**；`char` 出入参不支持，`char...` 随之不支持。

### 9.4 SAM 转换：函数值跨边界

```dawn
use java "java.lang.Thread"

fn spawn_hello(msg: String) -> Unit !io = {
  let t = Thread.new(fn() => println(msg))   # Dawn lambda → java.lang.Runnable
  t.start()
  t.join()
}
```

- Java 形参是**函数式接口**（interface 且恰有一个抽象方法，`Object` 的公共方法不计）时，
  实参可传 Dawn 函数值——lambda、命名函数、构造器值均可。仅限接口；单抽象方法的
  **抽象类**不支持（实现经 LambdaMetafactory，构建期展开，native-image 零配置）。
- **匹配**：SAM 方法签名按 §9.2 映射成 Dawn 函数类型后做常规匹配；lambda 的参数类型
  可从形参播种（与泛型实参推导同一机制）。重载打分时函数值只匹配函数式接口形参。
  Dawn 不追踪 Java 泛型实参，**泛型 SAM**（`Predicate`/`Function` 这类）的参数按擦除后
  的类型进入 Dawn（通常是不透明 `Object`，只能原样传递）；具体类型的 SAM
  （`Runnable`、`HttpHandler`）才有完整体验。
- **效果不设限**：纯函数、`!io` 函数、效果变量函数都可传出。效果系统不追踪 Java 侧
  何时调用——Java 可能在任意线程、任意时刻（包括本次调用返回之后）调用该函数值。
  这不破坏纯度契约：Java 代码只可能在 Dawn 的 `!io` 调用之下、或无 Dawn 栈的
  Java 线程上运行，任何纯函数的签名承诺都未被违反。
- **参数的 null 边界**：回调的引用类型参数**不包 `Option`**，以 `T` 直达；桥接层逐参
  检查，Java 传入 null 立即 panic（消息指明回调边界）。与返回值包 `Option`（§9.2）
  互补：返回位置的 null 是常态故进类型，回调参数的 null 属病态故 fail-fast。
- **返回值收窄**：SAM 方法要 `int` 而 Dawn 函数返回 `Int` 时做**检查性收窄**，超出
  范围 panic，不静默截断；要 `float` 时按 IEEE 规则收窄 `Float`（可能损失精度，
  这是浮点语义而非溢出）。
- Dawn 函数在回调中 panic，以 `dawn.rt.PanicError`（`Error` 的子类）传给 Java
  调用方，不捕获不包装。

### 9.5 数组：不透明直通；`byte[]` = 一等 `Bytes`

数组值与未导入的引用类同待遇（§9.1）：可**接收、持有、传参**——重载打分按数组类型
精确匹配，或宽化到 `Object`；返回位置照 §9.2 包 `Option`。但数组（除 `byte[]`，见下）
**不可命名**（签名里写不出该类型）、**不可创建、不可索引**；要长度用
`use java "java.lang.reflect.Array"` 的 `Array.getLength(a)`。

**`byte[]` 是唯一例外：它就是一等类型 `Bytes`**（§9.5.1）。Java 方法返回的具体 `byte[]`
（如 `readAllBytes`/`toByteArray`/`Base64.decode`/`MessageDigest.digest`）照 §9.2 落成
`Option[Bytes]`；`Bytes` 可写进签名、存进 record、切片/索引/拼接/按内容比较；反向传给
Java `byte[]` 形参（`OutputStream.write`、`MessageDigest.isEqual` 等）直接匹配。

```dawn
use java "java.nio.file.Files"
use java "java.nio.file.Path"

fn slurp(p: String) -> String !io = {
  let bytes: Bytes = Files.readAllBytes(Path.of(p).expect("path")).expect("readable")
  decode(bytes, "UTF-8")
}
```

#### 9.5.1 `Bytes`：一等不可变字节序列

`Bytes` 是不可变的字节序列，运行期就是裸 `byte[]`。库函数（§11「bytes」组）：
`utf8(s) -> Bytes`（字符串的 UTF-8 字节）、`decode(b, charset) -> String`（按字符集解码）、
`byte_len`、`byte_at(b, i) -> Int`（0..255，越界 panic）、`byte_slice(b, start, end)`
（`[start,end)`，下标 clamp 进范围）、`byte_index_of(b, needle, from) -> Option[Int]`。
`Bytes ++ Bytes` 拼接、`==`/`!=` 按**内容**比较（`Show` 渲染为 `<N bytes>` 摘要）。
`byte[]` 的 JVM `hashCode` 是引用同一性，故 **`Bytes` 不宜作 Map/Set 键**（用 `decode` 出的
String 或十六进制键代替）。`Bytes` 不参与 comptime 常量折叠，也不能作 bare 一等函数值
（用 lambda 包一层）。

**不透明值收窄回具体引用形参**：擦除泛型的返回（§9.2）落成不透明 `Object`，但业务
常需把它**原样喂回**某个要具体引用类型的 Java 形参——例如 `HttpResponse.body()`
以 `BodyHandlers.ofByteArray()` 取到的 `Object` 实为 `byte[]`，要写进
`OutputStream.write(byte[])`。此时重载消解允许不透明 `Object` 实参匹配具体引用形参，
桥接处插一次运行期 `CHECKCAST`（失败即 `ClassCastException` 穿透，非静默）。方向与
§9.3 的「宽化到 `Object`」相反、成对：宽化是丢类型信息传出，收窄是运行期认领回来。
不透明值仍**不可命名、不可索引**——收窄只发生在跨边界传参的隐式适配处，Dawn 代码
拿不到该类型的名字。这让「取二进制体 → 透传出去」这类管道无需把字节读进 Dawn 值
（省一次全量拷贝，大文件不顶爆内存）。

若确知某个擦除泛型的不透明 `Object` 运行期是某个具体引用类型（如 `HttpResponse.body()` 配
`BodyHandlers.ofByteArray()` 时是 `byte[]`），用泛型内建 `cast(x) -> T` 把它**认领**成该类型
（T 取自调用点的期望类型，如 `let b: Bytes = cast(...)`；§9.5.1）——桥接处插一次运行期 `CHECKCAST`，
类型不符即 `ClassCastException` 穿透。T 须是引用类型（编译期拒绝 primitive / 无期望类型）。

### 9.6 List 桥接：Dawn `List` 直达集合形参

Java 形参声明为 `java.util.List` / `java.util.Collection` / `java.lang.Iterable` 时，
实参可传 Dawn `List[T]`。**零拷贝**：桥接处套一层不可变视图
（`Collections.unmodifiableList`），Java 侧的变异方法抛
`UnsupportedOperationException`——同 Scala `asJava` / Clojure 持久集合的约定。

- 元素类型 `T` 限：`Int` / `Float` / `Bool` / `String` / 已导入或不透明的引用类。
  元素是 `List`/`Map`/`Set`/ADT/元组/record/函数值时拒绝（编译错误）——嵌套容器
  零拷贝会泄漏内层可变性，v0.1 不做深包装。
- 元素按 §9.2 的装箱表示直达（`Int` → `java.lang.Long`）。泛型擦除意味着期待
  `List<Integer>` 的 API 会在取用时 `ClassCastException`，v0.1 不救，选 API 时留意。
- 方向仅 Dawn → Java；Java 返回的集合仍是不透明引用 + `Option`（§9.2），可链式调用。
  `Map`/`Set` 桥接 v0.1 未提供。

### 9.7 限制

不能继承 Java 类；不能以**命名类**形式实现 Java 接口——函数值经 SAM 转换（§9.4）
传出是唯一路径。静态字段 v0.1 不支持（枚举与常量走 `TimeUnit.valueOf("SECONDS")`、
`Charset.forName("UTF-8")` 这类静态方法绕行）。数组不可创建/索引/命名（§9.5）；
`Map`/`Set` 不桥接、Java 集合不反向转换为 Dawn 值（§9.6）。变长参数只支持不传
可变部分（§9.3）；`Option` 实参传 null 不支持（§9.2）。

### 9.8 异常屏障：`java_try`

Dawn 无异常：Java 调用抛出的异常默认原样穿透并终止程序（等同 panic 语义）。
但**预期中的外部失败**（网络断开、SQL 约束冲突、解析失败）在 Java 世界以异常表达，
它们不是 bug，应进 `Result`。内建 `java_try` 是唯一的转换点：

```dawn
use java "java.lang.Long"

fn parse(s: String) -> Result[Int, String] !io =
  java_try(fn() => Long.parseLong(s))       # 异常 → Err("java.lang.NumberFormatException: ...")
```

- 签名 `java_try[T](f: fn() -> T !io) -> Result[T, String] !io`；闭包可为纯函数。
- 只拦 `java.lang.Exception` 及其子类；`Error` 不拦——**Dawn 的 panic
  （`dawn.rt.PanicError` 是 `Error` 子类）原样穿透**，panic 仍然是 bug、不可恢复。
- `Err` 载荷是 `Throwable.toString()`（异常类名 + 消息），供日志与上抛；
  需要区分异常种类时按前缀匹配字符串，v0.1 不提供结构化异常对象。
- 边界之内失败照常传播：`java_try` 包住整段复合调用即可，无需逐调用包裹。

配套的 `catch_panic[T](f: fn() -> T !io) -> Result[T, String] !io` 拦的是
**任意 `Throwable`（含 Dawn panic `PanicError`）**，用于**监督边界**——服务器的
单个请求、任务 runner 的单次执行：一个请求 panic 应变成 500 并记录，而非掀翻整条
连接或进程。它与 `java_try` 分工明确：`java_try` 处理**预期外部失败**、放 panic 穿透；
`catch_panic` 是**隔离点**、兜住一切。普通业务失败仍走 `Result`，别拿 `catch_panic`
当常规错误处理。

---

## 10. 模块系统

### 10.1 文件与模块路径

一个 `.dawn` 文件 = 一个模块。模块路径 = 相对**模块根**的路径去掉扩展名：
`<root>/json/lexer.dawn` → 模块 `json/lexer`。路径每段须匹配 `[a-z_][a-z0-9_]*`
（与文件名一致），否则编译错误。

**模块根的确定**：

- **目录模式** `dawn run|test|build <dir>`：根 = `<dir>/src`，入口 = `<dir>/src/main.dawn`
  （缺失则报错并给出预期路径）。
- **文件模式** `dawn run|test|build <file.dawn>`：从该文件所在目录**向上找最近的名为
  `src` 的祖先目录**作为根；找不到则根 = 文件所在目录。LSP 用同一条启发式，故单独打开
  一个子模块文件也能解析它相对根的 `use`。

**目录约定即工程定义**：模块根、入口、模块路径全部由目录结构决定，不需要清单文件。

项目**可选**带一个 `dawn.toml`，只承载目录约定表达不了的东西——工程身份与依赖。
没有它的项目按上述规则照常工作。schema 1 的内容：

```toml
schema = 1                                      # 必须是第一个 key
name = "backend_dawn"                           # 工程身份（[a-z_][a-z0-9_]*）

[java-deps]                                     # Maven 依赖，`use java` 用得到
sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"      # 精确坐标；禁 SNAPSHOT、禁版本区间
```

`dawn run|test|build` 会拉取 `[java-deps]` 并挂上 classpath（与 `--cp` 合并）；
`dawn build` 另把它们复制进 jar 同级的 `lib/`。仓库地址走 `$DAWN_MAVEN_MIRROR`，不进 manifest。

**manifest 永远是数据，不是代码**——不存在可执行的 `build.dawn`。理由与完整设计见
[`package-design.md`](package-design.md)。

### 10.2 引入

```dawn
use json/lexer                 # 整模块引入；别名 = 末段 lexer，限定访问 lexer.next(...)
use json/value.{Json, render}  # 选择性引入，非限定使用
use java "java.lang.Math"      # Java 互操作（§9），形式不变
```

- 一个模块只能被 `use` 一次（整模块或选择性，二选一）；重复 `use` 是错误。
- `use` 可出现在顶层任意位置（与 `use java` 一致），`dawn fmt` 不重排。
- 无 `as` 重命名（v0.1）。两个整模块引入若末段同名 → 错误（提示改用选择性引入或重组目录）。

### 10.3 名字解析（消歧规则）

- 整模块引入的别名与本模块顶层声明、局部绑定、参数**同一命名空间**：
  **声明任何与模块别名同名的顶层 fn/type/const、局部或参数都是编译错误**
  （"`lexer` shadows the imported module `json/lexer`"）。由此 `lexer.next(x)` 永不歧义——
  `lexer` 要么是一个绑定（走 §4 的 UFCS 点调用），要么是模块别名（限定访问），不可能两者兼是。
- 限定访问只支持**表达式位置**的 `alias.fn(args)`（调用一个 pub 函数）。
  **类型、构造器、常量跨模块只能经选择性引入**（`use m.{Shape, MAX_DEPTH}`）：限定类型引用
  `m.Shape`、限定构造器模式、限定常量 `m.NAME` v0.1 都不做（常量名是大写，本就不走点取）。
- 选择性引入一个 `type` 同时引入其**全部构造器**（与 `pub type` 导出构造器+字段的规则一致）。
- 选择性引入的名字与本模块顶层声明或其他引入冲突 → 错误；与 prelude 名冲突沿用
  「顶层声明遮蔽 prelude」的现行规则（引入视同顶层声明）。

### 10.4 可见性

所有声明默认模块私有；`pub` 导出 `fn`/`type`/`const`（`pub type` 连带构造器与字段，见 §3.3）。
访问或引入非 `pub` 项 → 错误（`` `parse` is private to module json/parser ``，附 hint：加 `pub`）。

### 10.5 编译单元与求值顺序

- **目录模式加载 `src/` 下全部 `.dawn` 文件**（不止 `use` 闭包）：未被引用的模块也要通过
  类型检查（防 bit-rot），其 test 块也被 `dawn test` 执行。
- `use` 依赖图**禁止成环**，报错打印环路（`json/a → json/b → json/a`）。
- 类型检查与 comptime 求值按依赖**拓扑序**进行；跨模块引用的 `const` 值在使用方求值前已就绪。
- 类型同一性：同一 `type` 声明在整个程序中是同一个类型（每个文件只解析/检查一次）。
- 入口：main 模块的 `pub fn main() -> Unit !io`。

### 10.6 prelude

标准库中隐式可用、无需 `use` 的部分：`List`/`Option`/`Result` 的构造器、
`map`/`filter`/`fold`/`range`/`println`、`Map`/`Set` 操作等约数十个常用名（§11）。

---

## 11. 标准库草案（v0.1 范围）

- `core/list`：`map filter fold len get range ...`；排序与极值（元素/键类型须具
  `Ord`，见 §3.5；全部稳定、平局取第一个）：
  - `sort[T: Ord](xs) -> List[T]` — 升序稳定排序
  - `sort_by(xs, cmp: fn(T, T) -> Int) -> List[T]` — 自定义比较函数
  - `max/min[T: Ord](xs) -> Option[T]` — 极值；空列表 `None`
  - `max_by/min_by[T, K: Ord](xs, key: fn(T) -> K) -> Option[T]` — 按键取极值
- `core/string`：`chars split join trim starts_with ends_with contains
  to_lower to_upper parse_int parse_float to_string index_of last_index_of ...`（`to_lower`/`to_upper`
  按 Unicode 大小写折叠；字符串转数字是 `parse_int(s) -> Option[Int]`——
  没有重载，`to_int`/`to_float` 只做 Int↔Float 转换）。
- `core/bytes`（一等 `Bytes`，§9.5.1）：`utf8(s: String) -> Bytes`（字符串的 UTF-8 字节）、
  `decode(b: Bytes, charset: String) -> String`（按字符集解码，替代旧
  `String.new(bytes, charset)`）、`byte_len(b) -> Int`、`byte_at(b, i) -> Int`（0..255，越界 panic）、
  `byte_slice(b, start, end) -> Bytes`（`[start,end)`，下标 clamp）、
  `byte_index_of(b, needle, from) -> Option[Int]`（字节下标首次出现）、
  `cast(x) -> T`（把擦除泛型的不透明 `Object` 认领为具体引用类型 T，T 取自期望类型，§9.5）。
  另有操作符 `Bytes ++ Bytes` 与按内容的 `==`/`!=`。二进制请求体（multipart 上传、WebDAV PUT）、
  crypto/签名、HTTP 收发都直接走 `Bytes`，不再借道 latin-1 字符串。
- **码点 / 字符**（§1.5、§2.1 的补充；字符即码点 `Int`）：
  - `code_points(s: String) -> List[Int]` — 拆成码点（增补平面的代理对合并为一个码点）
  - `from_code_points(cs: List[Int]) -> String` — 由码点组装（接受增补码点）
  - `char_to_string(c: Int) -> String` — 单码点转字符串（非法码点 panic）
  - `str_len(s: String) -> Int` — 码点数（区别于 `chars` 返回的 `List[String]`）
  - `substring(s: String, from: Int, to: Int) -> String` — 按**码点下标**切片，越界 panic
- `core/option` / `core/result`：`map unwrap_or expect and_then ...`
- **`Map` / `Set`**（§2.2 的内建持久容器，v0.1 以平铺内建函数提供；未来再收进 `core/map`
  等模块化组织）：

  ```
  map_empty[K, V]() -> Map[K, V]              set_empty[T]() -> Set[T]
  map_from(entries: List[(K, V)]) -> Map[K, V]   set_from(xs: List[T]) -> Set[T]
  map_insert(m, k, v) -> Map[K, V]            set_insert(s, x) -> Set[T]
  map_remove(m, k) -> Map[K, V]               set_remove(s, x) -> Set[T]
  map_get(m, k) -> Option[V]                  set_has(s, x) -> Bool
  map_has(m, k) -> Bool                        set_size(s) -> Int
  map_size(m) -> Int                           set_to_list(s) -> List[T]
  map_keys(m) -> List[K]
  map_values(m) -> List[V]
  map_entries(m) -> List[(K, V)]
  ```

- `core/math`：`abs min max sin cos sqrt pow to_float to_int ...`（纯——
  内部以 `@trusted_pure` 包装 `java.lang.Math`）
- `io`：`println read_line read_file write_file list_dir is_dir args env java_try ...`（全部 `!io`）
  - `write_file(path, content) -> Result[Int, String]` — **自动创建缺失的父目录**
  - `list_dir(path) -> Result[List[String], String]` — 排序后的条目名；path 不是目录时 `Err`
  - `is_dir(path) -> Bool` — 不存在或出错都视为 `false`

实现策略：能薄包 Java 就薄包（`String` 直接是 `java.lang.String`），持久 `List`/`Map`/`Set`
自实现（v0.1 以 `LinkedHashMap`/`LinkedHashSet` copy-on-write 兜底，保插入序确定；
自举前用 Kotlin 写运行时）。

---

## 12. 编译模型

### 12.1 产物

| 命令 | 产物 |
|------|------|
| `dawn run <file.dawn 或 dir>` | 编译到内存/临时目录，起 JVM 执行 |
| `dawn build <file 或 dir> -o app.jar` | 可执行 jar（`Main-Class: main` 已设） |
| `dawn build ... --native -o app` | 前一步 + `native-image`，独立二进制 |
| `dawn test <file 或 dir>` | 编译含 test 块的变体并执行（目录模式聚合全部模块的 test） |
| `dawn fmt <file 或 dir>...` | 格式化（目录模式递归全部 `.dawn`） |

**参数可为单文件或工程目录**（§10.1）：目录模式加载 `src/` 全部模块，入口
`src/main.dawn`；单文件模式向上找 `src` 祖先为根。jar 收全部模块类，`Main-Class` = 入口
模块类 `main`。

**第三方 jar：`--cp <jars>`**（run/test/build 通用；路径分隔符分隔、可重复）。
编译期 `use java` 解析与运行期加载共用这份 classpath。`build` 把各 jar 记入 manifest
的 `Class-Path`（相对产物目录，jar 挪走要一起挪），产物仍 `java -jar` 直接跑；
`build --native` 改以 `-cp` 形式调 native-image（第三方库的反射/JNI 是否过
native-image，责任在库，见 §12.3）。Dawn 无依赖解析——只接受**单 jar、零传递依赖**
的库，需要依赖树的库不适配。

**保证**：同一程序在 JVM 与 native 下行为一致（除启动时间与内存占用）。

### 12.2 字节码映射

| Dawn 构造 | JVM 实现 |
|-----------|----------|
| 模块 `json/lexer` | 一个类，内部名 `json/lexer`（包 `json`、类 `lexer`），函数为 static 方法 |
| ADT/record | 类名带模块前缀：`json/lexer$Token`、构造器 `json/lexer$Token$Num` |
| 跨模块调用 | 对方模块类上的 `invokestatic`；构造器/字段照常（类公开） |
| ADT | abstract class + final 子类；无载荷构造器为单例 |
| record | final class + 字段（不依赖 Java record，兼容旧字节码目标） |
| `match` | `instanceof` 链 + 字段读取（不用 indy、不用 pattern switch） |
| lambda/闭包 | `LambdaMetafactory`（native-image 支持名单内） |
| 泛型 | 擦除 + 装箱 |
| 结构相等类型 | ADT/record/元组生成配套 `equals` 与 `hashCode`（供 `Map`/`Set` 作键） |
| `Int`/`Float`/`Bool` | 原生 `long`/`double`/`boolean`，仅泛型位置装箱 |
| `panic` | 抛 `dawn.rt.PanicError`（Error 子类，不可被 Dawn 捕获） |

运行时支持类（`dawn/rt/Lists`、`Strings`、`Io`、`Show`、`Maps`、`Tuple*`、`Fn*` 等）
每个程序生成一份，被全部模块类共享。

### 12.3 native-image 契约

语言构造**保证**不产生：反射调用、自定义 indy bootstrap、动态类加载、
JNI（Java 互操作走普通 invoke）。因此 `--native` 构建不需要
reachability 配置。若引入的 Java 库自身用反射，责任在库——错误信息会提示
这超出 Dawn 的保证范围。

### 12.4 尾调用

**自递归尾调用保证**编译为循环（不长栈）——顶层函数与**局部命名函数**（§3.1）皆然。
互递归尾调用 v0.1 不保证。判定规则：函数体内对自身的调用处于尾位置（返回位置、
match/if 分支的尾位置、块的末表达式）。

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

fn double(x: Int) = x * 2        # 私有函数可省返回类型（§3.1）

# ---- 表达式 ----
let n = 42                       var acc = 0
let (a, b) = pair                acc = acc + 1
if x > 0 { "pos" } else { "non-pos" }
match opt { Some(v) -> v, None -> fallback }
xs |> filter(fn(x) => x > 0) |> map(to_string) |> join(", ")
xs[0]                            # 下标：越界 panic；问询用 get（§4.8）
read_file(path)?                 # Result 传播
if n < 0 { return "negative" }   # 提前返回（§4.9）
comptime { heavy_pure_calc() }   # 编译期求值

# ---- 块内局部函数（可递归，§3.1）----
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}

# ---- 测试 ----
test "dist is symmetric" {
  assert dist(p, q) == dist(q, p)
}
```

---

## 14. 未来方向（明确不在 v0.1）

按优先级：trait v2（条件 impl、泛型主体、supertrait、更多 derive）、
细分效果（`!fs`、`!net`）、互递归尾调用、`break`/`continue`、
Dawn lambda 传给 Java、newtype、单态化优化、`Rune` 类型。
（trait v1——单参数 typeclass + 字典传递——已于 2026-07 落地，见 §3.5 与 trait.md。）
