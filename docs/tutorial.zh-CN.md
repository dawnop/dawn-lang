<!-- doc-check: translation-of docs/tutorial.md @ 2dcc2f0d343852b8 -->

# Dawn 教程

*[English](tutorial.md) —— 正本是英文；本文是它的译本，`scripts/doc-check.py` 盯着两者不脱节。*

<!--
> 状态：**current** —— 面向读者的教程；其中标注 `dawn run` 的示例由 CI 实跑（`scripts/doc-check.py`）。

维护者说明，放在注释里，站点不向读者显示。
本文的 `dawn` 围栏代码块曾由 Kotlin 侧的 `TutorialTest` 机械抽取、编译、运行并核对
`output`；那套测试随 Kotlin 实现一起归档在 `kotlin-final` tag。**门禁已经补回来了**
（docs/codebase-audit.md 的 TEST-04）：`scripts/doc-check.py` 是 CI 的一个 job，
把本文标了 ```` ```dawn run ```` 的块逐个真编真跑。**没标 `run` 的块仍是人工维护的**，
可能落后于语言；正确性重要的示例请自己标上。
-->

一门刻意小的静态类型语言，有两个平级后端：编译到 JVM 字节码，或经 C 编成 native
可执行文件。本教程共二十章，从第一个程序一直讲到自己声明的效果与它们的 handler，
再讲到包、程序可以编译到的目标，最后讲 GPU 上的 kernel。

---

## 1. 安装与第一个程序

[Releases 页](https://github.com/dawnop/dawn-lang/releases/latest)上的每个 release
都发布两套工具链，各自旁边附 SHA-256。它们是两个不同的编译器，不是同一个东西的两种下载，
按有没有 JVM 选一个。

**不用 JVM**（linux-x86_64）：`dawnc` 是一个静态可执行文件，标准库与 C 运行时都在里面。
它经 C 后端编译，所以拒绝 `use java`（第 11 章是它唯一跟不了的一章）。

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawnc-linux-x86_64
curl -fsSLO $base/dawnc-linux-x86_64.sha256
sha256sum -c dawnc-linux-x86_64.sha256
chmod +x dawnc-linux-x86_64 && sudo mv dawnc-linux-x86_64 /usr/local/bin/dawnc
```

**用 JVM**（JDK 21 或更新，任意平台）：`dawn-selfhost.jar` 自带标准库，单这一个 jar
就是完整的工具链。

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawn-selfhost.jar
curl -fsSLO $base/dawn-selfhost.jar.sha256
sha256sum -c dawn-selfhost.jar.sha256      # macOS：shasum -a 256 -c
```

下面的命令写作 `dawn`。用静态二进制时它是 `dawnc`；用 jar 时它是
`java -jar dawn-selfhost.jar`。

```bash
dawn run  hello.dawn        # 编译并运行
dawn test hello.dawn        # 运行文件里的 test 块
dawn fmt  hello.dawn        # 就地格式化
```

**从源码构建**，前提是有一份检出和 JDK 21：`./bin/dawn` 就代替 `dawn`。它首次运行时
下载种子（`scripts/seed-release.txt` 钉住的那个 release 的 `dawn-selfhost.jar`，按
`scripts/seed-checksums.txt` 校验），再用种子编译 `selfhost/` 里的编译器。在检出里，
`./bin/dawn build hello.dawn --native -o hello` 用 GraalVM native-image 打包 JVM 构建，
这和 `dawnc` 是两条不同的路。

第一个程序。函数默认是纯的；碰 IO（这里是打印）必须在签名标 `!io`：

```dawn run
pub fn main() -> Unit !io =
  println("你好，Dawn")
```
```output
你好，Dawn
```

字符串插值写作 `${expr}`，简单变量与任意表达式一样写（插入的值必须可打印）。
花括号本身是普通字符——不写 `$` 就不是插值：

```dawn run
pub fn main() -> Unit !io = {
  let name = "Dawn"
  let year = 2026
  println("${name} 诞生于 ${year}")
}
```
```output
Dawn 诞生于 2026
```

另见：[spec.md](spec.md) §12.1

---

## 2. 值、类型与函数

`let` 绑定不可变，`var` 可变。基本类型有 `Int`、`Float`、`Bool`、`String`。
顶层函数必须写全参数类型与返回类型——签名即契约。

```dawn run
fn square(x: Int) -> Int = x * x

fn abs(x: Int) -> Int =
  if x < 0 { 0 - x } else { x }

pub fn main() -> Unit !io = {
  var total = 0
  total = total + square(3)
  total = total + abs(-4)
  println(to_string(total))
}
```
```output
13
```

管道 `|>` 把左侧塞进右侧调用的第一个参数，读起来是数据的流向：

```dawn run
fn double(x: Int) -> Int = x * 2
fn inc(x: Int) -> Int = x + 1

pub fn main() -> Unit !io =
  5 |> double |> inc |> to_string |> println
```
```output
11
```

### 具名实参与默认值

形参可以带默认值，写作 `name: Type = expr`，调用时就可以省掉这个实参。任何实参也都可以
按名字传：位置实参从左往右占位，具名实参占它点名的那一格，名字之间的先后随意。

```dawn run
fn greet(name: String, greeting: String = "Hello", punct: String = "!") -> String =
  "${greeting}, ${name}${punct}"

pub fn main() -> Unit !io = {
  println(greet("Dawn"))
  println(greet("Dawn", punct: "?"))
  println(greet(punct: ".", name: "reader", greeting: "Welcome"))
}
```
```output
Hello, Dawn!
Hello, Dawn?
Welcome, reader.
```

默认值在每次省掉它的调用里重新求值，而且必须是纯的：要是它能做 io，一次调用做不做 io
就取决于调用方传没传这个实参。实参按书写顺序求值，不管它们落在哪一格。名字属于签名，
所以函数值没有名字：`let g = greet` 之后，`g(name: "x")` 是错误，`g` 要求三个实参一个
不少。构造器也一样收名字，字段名就是它的形参名（`Rect(w: 3.0, h: 4.0)`）。

另见：[spec.md](spec.md) §2.1、§3.1、§4.3、§4.4

---

## 3. match 与穷尽性

`match` 按模式分派。编译器检查**穷尽性**：漏了分支会报错，并告诉你漏了哪个。

```dawn run
fn sign(x: Int) -> String =
  match x {
    0 -> "zero"
    n if n > 0 -> "positive"
    _ -> "negative"
  }

pub fn main() -> Unit !io = {
  println(sign(0))
  println(sign(7))
  println(sign(-2))
}
```
```output
zero
positive
negative
```

另见：[spec.md](spec.md) §5

---

## 4. 数据建模：ADT 与 record

代数数据类型（ADT）用 `|` 列出各构造器。加 `derive Show` 让它能打印：

```dawn run
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  derive Show

fn area(s: Shape) -> Float =
  match s {
    Circle(r) -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io = {
  println(to_string(Circle(2.0)))
  println(to_string(area(Rect(3.0, 4.0))))
}
```
```output
Circle(2.0)
12.0
```

record 是带命名字段的乘积类型，用花括号构造与更新：

```dawn run
type Point = { x: Float, y: Float } derive Show

fn shift(p: Point, dx: Float) -> Point =
  Point { ..p, x: p.x + dx }

pub fn main() -> Unit !io = {
  let a = Point { x: 1.0, y: 2.0 }
  println(to_string(shift(a, 10.0)))
}
```
```output
Point { x: 11.0, y: 2.0 }
```


`type` 声明的永远是新类型；给已有类型起**别名**用 `alias`——两边可以互换使用，
常用来给元组或函数类型一个说话用的名字：

```dawn run
alias Point = (Int, Int)

fn shift(p: Point, dx: Int) -> Point = {
  let (x, y) = p
  (x + dx, y)
}

pub fn main() -> Unit !io = {
  let p: Point = (1, 2)
  println(to_string(shift(p, 3)))
}
```
```output
(4, 2)
```

另见：[spec.md](spec.md) §2.3、§2.4、§2.6

---

## 5. 列表、元组与模式解构

内建 `List` 有字面量、`++` 连接、`len`、`range`、for-in。列表模式能解构头尾：

```dawn run
fn describe(xs: List[Int]) -> String =
  match xs {
    [] -> "空"
    [x] -> "单个 ${x}"
    [first, ..rest] -> "首个 ${first}，还有 ${len(rest)} 个"
  }

pub fn main() -> Unit !io = {
  println(describe([]))
  println(describe([9]))
  println(describe([1, 2, 3]))
}
```
```output
空
单个 9
首个 1，还有 2 个
```

元组打包定长异构值，`let` 可直接解构：

```dawn run
fn divmod(a: Int, b: Int) -> (Int, Int) = (a / b, a % b)

pub fn main() -> Unit !io = {
  let (q, r) = divmod(17, 5)
  println("${q} 余 ${r}")
}
```
```output
3 余 2
```

另见：[spec.md](spec.md) §2.2、§4.11、§5.1

---

## 6. 循环：while、for、break 与 continue

递归和 `map`/`fold` 之外，Dawn 也有普通循环：`while` 条件循环、`for x in 列表`、
`for i in a..b`（含 a 不含 b）。`break` 提前退出**最内层**循环，`continue` 跳到下一轮；
它们是 `Never` 类型的表达式，不能穿过 lambda 边界。

```dawn run
pub fn main() -> Unit !io = {
  var sum = 0
  for i in 0..5 {
    if i == 3 { continue }
    sum = sum + i
  }
  println("${sum}")

  var n = 0
  while true {
    n = n + 1
    if n * n > 30 { break }
  }
  println("${n}")
}
```
```output
7
6
```

另见：[spec.md](spec.md) §4.7

---

## 7. 错误处理：Result 与 `?`

Dawn 没有异常。可恢复的错误走 `Result[T, E]`；`?` 在 `Ok`/`Some` 时取值、
在 `Err`/`None` 时提前返回。不可恢复的用 `panic`（它不返回，故不需要 `!io`）。

```dawn run
fn half(x: Int) -> Result[Int, String] =
  if x % 2 == 0 { Ok(x / 2) } else { Err("${x} 是奇数") }

fn quarter(x: Int) -> Result[Int, String] = {
  let h = half(x)?
  half(h)
}

pub fn main() -> Unit !io =
  match quarter(20) {
    Ok(v) -> println("得到 ${v}")
    Err(e) -> println("错误：${e}")
  }
```
```output
得到 5
```

另见：[spec.md](spec.md) §8

---

## 8. lambda 与效果系统

匿名函数用 `(参数) => 表达式`——单个不带注解的参数可省括号，写成 `x => 表达式`；
类型可推导时参数注解可省。函数类型写作
`fn(A) -> B !e`，其中 `!e` 是效果。纯函数看签名即知没有副作用，测试无需 mock。

```dawn run
pub fn main() -> Unit !io = {
  let nums = [1, 2, 3, 4]
  let evens = filter(nums, n => n % 2 == 0)
  let doubled = map(evens, n => n * 2)
  println(to_string(doubled))
}
```
```output
[4, 8]
```

高阶函数用**效果变量**转发参数的效果：`map(f)` 的效果等于 `f` 的效果。
两个函数参数的效果之并写作 `!(e1 | e2)`——纯 ∘ 纯还是纯，沾 io 便是 io。

```dawn run
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2) =
  a => g(f(a))

fn inc(x: Int) -> Int = x + 1
fn dbl(x: Int) -> Int = x * 2

pub fn main() -> Unit !io = {
  let f = compose(inc, dbl)
  println(to_string(f(10)))
}
```
```output
22
```

### 块作为最后一个实参

调用的最后一个实参是函数时，可以写成紧跟在调用后面、同一行上的一个裸块：
`f(a) { e }` 就是 `f(a, () => e)`。带参数的块像 lambda 那样在 `=>` 前写出参数，
一个裸名字，或者一个带括号的列表：

```dawn run
fn twice(body: fn() -> Unit !e) -> Unit !e = {
  body()
  body()
}

pub fn main() -> Unit !io = {
  twice {
    println("hi")
  }
  let total = fold([1, 2, 3], 0) { (acc, x) => acc + x * x }
  println("${total}")
  let loud = map(["a", "b"]) { s => s ++ "!" }
  println("${loud}")
}
```
```output
hi
hi
14
["a!", "b!"]
```

不管前面传了什么，块填的都是**最后一个**形参，所以 `fold(xs, 0) { ... }` 读起来就是
「从 0 开始 fold，用这个」。块必须和调用在同一行开头；下一行的 `{` 是另一条块语句。
在 `if`、`while`、`for` 的头部以及 `match` 后面，花括号是语句体而不是实参，那里要给
调用加括号：`if (f(x) { ... }) { ... }`。配上具名实参与默认值，一个选项很多、又带一段
主体的函数在调用点就读作 `column(gap: 12) { ... }`。

另见：[spec.md](spec.md) §4.3、§4.5、§6

---

## 9. 字符串与标准库

标准库分两层：少数高频名（`println`、`map`/`filter`/`fold`、`len`、`to_string`…）
在 **prelude** 里，随处直接可用；其余都住在**模块**里，`use std/x` 引入后用
`x.fn(...)` 限定调用——字符串在 `std/str`，还有 `std/list`、`std/map`、`std/set`、
`std/bytes`、`std/io`、`std/cursor`。热名可以选择性引入（`use std/str.{trim}`）。

字符串函数按码点处理。`str.split` 是**字面量**分隔（不是正则）；`join` 是它的逆：

```dawn run
use std/str

pub fn main() -> Unit !io = {
  let parts = str.split("a,b,c", ",")
  println(to_string(len(parts)))
  println(join(parts, " - "))
}
```
```output
3
a - b - c
```

字符串有三种写法，死角互补：双引号 `"..."` 支持转义与 `$` 插值；三引号 `"""` 跨行、
剥公共缩进、引号免转义（插值照常）；**反引号 `` `...` `` 是 raw string**——无转义、
无插值、可跨行，写正则、代码样本、HTML 片段所见即值（唯一限制：内容不能含反引号）：

```dawn run
pub fn main() -> Unit !io = {
  println(`"quotes" and $dollar and \n stay literal`)
}
```
```output
"quotes" and $dollar and \n stay literal
```

`parse_int` 把字符串转成 `Option[Int]`（失败是 `None`，不是异常）：

```dawn run
fn parseOr(s: String, fallback: Int) -> Int =
  match parse_int(s) {
    Some(n) -> n
    None -> fallback
  }

pub fn main() -> Unit !io = {
  println(to_string(parseOr("42", 0)))
  println(to_string(parseOr("oops", -1)))
}
```
```output
42
-1
```

另见：[spec.md](spec.md) §1.6、§10.6、§11

---

## 10. comptime 与 const

`comptime { ... }` 在编译期由解释器执行，结果烧进常量池——没有宏。
顶层 `const` 名字用全大写，其初始化隐式是 comptime：

```dawn run
fn fib(n: Int) -> Int =
  if n < 2 { n } else { fib(n - 1) + fib(n - 2) }

const FIB10: Int = comptime { fib(10) }

pub fn main() -> Unit !io =
  println(to_string(FIB10))
```
```output
55
```

另见：[spec.md](spec.md) §7

---

## 11. 调用 Java

*仅限 JVM 工具链。* 本章需要 `dawn-selfhost.jar` 或检出里的 `./bin/dawn`。
静态的 `dawnc` 经 C 编译、拒绝 `use java`，用它的话请直接跳到第 12 章。

`use java "..."` 直接调 Java 类。所有 Java 调用自动视为 `!io`；引用类型返回值
自动包成 `Option[T]`——null 进不了 Dawn。构造用 `.new`，静态方法用类名。

```dawn run
use java "java.lang.Math"

pub fn main() -> Unit !io = {
  let n = Math.abs(-7)
  println(to_string(n))
}
```
```output
7
```

另见：[spec.md](spec.md) §9

---

## 12. test 块与 dawn fmt

`test "名字" { ... }` 里用 `assert` 写断言；`dawn test` 执行它们，`dawn build`
会把它们剥除。纯函数测试不需要任何 mock：

```dawn run
fn add(a: Int, b: Int) -> Int = a + b

test "加法可交换" {
  assert add(2, 3) == add(3, 2)
  assert add(0, 5) == 5
}

pub fn main() -> Unit !io = println("ok")
```
```output
ok
```

最后：`dawn fmt` 统一代码风格（2 空格缩进、规整间距），`dawn fmt --check` 供 CI
校验。养成提交前 `dawn fmt` 的习惯，代码评审就不必再争空格。

另见：[spec.md](spec.md) §3.4、§1.8

---

## 13. 模块与项目

超过一个文件就是一个项目。目录约定：模块放在 `src/` 下，入口是 `src/main.dawn`。
一个 `.dawn` 文件 = 一个模块，模块路径就是它相对 `src/` 的路径。

```
myapp/
└── src/
    ├── main.dawn
    └── util/
        └── math.dawn      # 模块 util/math
```

默认所有声明模块私有，`pub` 才导出。引入有两种：`use util/math` 整模块引入
（限定访问 `math.double(x)`，别名取路径末段），或 `use util/math.{double}` 选择性
引入（直接用 `double`）。类型、构造器、常量跨模块只能走选择性引入。

`src/util/math.dawn`：

<!-- doc-check: skip-check 两文件项目的被引入的那一半，没有 main，单文件编不成程序 -->
```dawn skip-check
pub fn double(x: Int) -> Int = x * 2

pub type Shape =
  | Circle(r: Float)
  | Square(side: Float)
  derive Show
```

`src/main.dawn`：

<!-- doc-check: skip-check 同一项目的入口那一半，use util/math 要求上面那个文件同时在场 -->
```dawn skip-check
use util/math
use util/math.{Shape, Circle, Square}

pub fn main() -> Unit !io = {
  println(to_string(math.double(21)))
  println(to_string(Circle(2.0)))
}
```

用 `dawn run myapp`（传目录）编译并运行整个项目；`dawn test myapp` 跑所有模块的
test 块，`dawn build myapp` 打成一个 jar。单文件的 `dawn run foo.dawn` 依然可用。
循环 `use` 是编译错误；一个名字与被引入模块的别名相同也会报错——它们共享一个命名空间。

另见：[spec.md](spec.md) §10.1、§10.2、§10.3

---

## 14. Map 与 Set

`Map[K, V]` 和 `Set[T]` 是内建的**持久**容器：每次「修改」都返回新容器，原值不变。
没有字面量语法，操作都在 `std/map` 与 `std/set` 模块里。迭代顺序 = 插入顺序
（JVM 与 native 一致）。

```dawn run
use std/map
use std/set

pub fn main() -> Unit !io = {
  let m = map.insert(map.insert(map.empty(), "a", 1), "b", 2)
  println(to_string(map.get(m, "a")))
  println(to_string(map.get(m, "z")))
  println(to_string(map.keys(m)))

  let s = set.from([3, 1, 2, 1, 3])
  println(to_string(set.len(s)))
  println(to_string(set.has(s, 2)))
}
```
```output
Some(1)
None
["a", "b"]
3
true
```

键可以是任何具结构相等的类型（`Int`/`String`/元组/ADT/record）。`map.get` 返回
`Option[V]`——查不到是 `None`，不是异常。相等与顺序无关：键值相同的两个 `Map` 相等。

另见：[spec.md](spec.md) §2.2、§11

---

## 15. 字符与码点

字符字面量 `'a'` 的类型是 `Char`：一个 Unicode 标量值，表示就是它的码点。它是
`Int` 上的 opaque type（§2.7），所以 `==`、`<`、哈希、`match` 里的字面量模式全都
是 `Int` 那一份——但它不是 `Int`，`'a' + 1` 不成立，两者互转要经 `std/char`：
`char.code(c)` 拿码点，`char.of(n)` 从码点造字符（不是标量值就 `None`）。

```dawn run
use std/char
use std/str

fn is_digit(c: Char) -> Bool = c >= '0' && c <= '9'

pub fn main() -> Unit !io = {
  println(to_string(is_digit('7')))
  println(to_string(char.code('a')))
  println(to_string(str.len("héllo 🙂")))
  println(str.slice("世界你好", 0, 2))
  println(from_code_points(['h', 'i']))
}
```
```output
true
97
7
世界
hi
```

`code_points`/`from_code_points` 在字符串与 `List[Char]` 间往返（含增补平面的
emoji），`str.len` 数码点，`str.slice` 按码点下标切片，`str.at` 取一个 `Char`，
`str.from_char` 把一个 `Char` 变成字符串。`"${c}"` 就是同一个单字符字符串：`std/char`
写了 `impl Display[Char]`，而 `Display` 是顶层渲染那一层。嵌套那一层的 `Show` 仍是目标
类型的那一份，所以列表里的 `Char` 仍打印成码点数字。

按码点**下标**的函数每次都要从串首数起（单次 O(n)，循环里就是 O(n²)）。扫描字符串
用 `std/cursor`：**游标**是不透明的位置，每步恒定开销；对它做算术是编译错误，
比较先后（`==`、`<`）是允许的。

```dawn run
use std/cursor

pub fn main() -> Unit !io = {
  let s = "a🎈b"
  let c = cursor.next(s, cursor.start(s))
  println("${cursor.char(s, c)}")
  println(cursor.slice(s, c, cursor.end(s)))
}
```
```output
127880
🎈b
```

一步就是一个字符：emoji 的代理对不会被拆开。`cursor.char` 回的是 `Int` 不是
`Char`，因为它到尾要答 `-1`——一个不是字符的哨兵住不进「每个值都是字符」的类型里
（spec §4.8）。`cursor.find(s, sub, from)` 返回
`Option[Cursor]`，`cursor.skip(s, c, sub)` 跳过一段已知出现的字面量。

另见：[spec.md](spec.md) §1.5、§2.7、§11

---

## 16. trait：约束泛型与运算符重载

到目前为止，泛型函数对 `T` 一无所知——不能比较、不能打印、不能调方法。
**trait** 给类型参数加上能力约束。声明一个 trait，为具体类型写 `impl`，
然后用 `[T: Trait]` 约束泛型：

```dawn run
trait Area[T] {
  fn area(s: T) -> Float
  fn bigger_than(s: T, limit: Float) -> Bool = area(s) > limit
}

type Rect = { w: Float, h: Float }

impl Area[Rect] {
  fn area(s: Rect) -> Float = s.w * s.h
}

fn total_area[T: Area](xs: List[T]) -> Float =
  fold(xs, 0.0, (acc, x) => acc + area(x))

pub fn main() -> Unit !io = {
  let rooms = [Rect { w: 3.0, h: 4.0 }, Rect { w: 2.0, h: 2.0 }]
  println(to_string(total_area(rooms)))
  # trait 方法就是普通函数名，UFCS 点号调用也行
  println(to_string(rooms[0].bigger_than(10.0)))
}
```
```output
16.0
true
```

规则很少：trait 恰有一个类型参数；每个「trait × 类型」全程序**只允许一个 impl**；
impl 必须写在 trait 或者主体类型所在的模块里（孤儿规则）。带默认体的方法
（上面的 `bigger_than`）impl 可以不写，写了就是覆盖。

### 排序：`Ord` 与比较运算符

预置 trait `Ord[T]`（唯一方法 `cmp(a: T, b: T) -> Int`，负/零/正表示小于/等于/大于）
桥接了 `< <= > >=`：`Int`/`Float`/`String` 天生有序，自定义类型给一个 `Ord` impl
（或直接 `derive Ord`）就能用比较运算符、当 `[T: Ord]` 的实参、喂给排序函数：

```dawn run
type Card = { rank: Int, name: String } derive Show, Ord

fn max2[T: Ord](a: T, b: T) -> T = if a < b { b } else { a }

pub fn main() -> Unit !io = {
  let hand = [Card { rank: 3, name: "queen" }, Card { rank: 1, name: "pawn" }]
  # derive Ord 按字段声明顺序逐个比较（和类型先比构造器顺序）
  println(to_string(hand[1] < hand[0]))
  println(max2("pear", "apple"))
  println(to_string(sort([3, 1, 2])))
  println(to_string(map(sort(hand), c => c.name)))
  println(to_string(max_by(hand, c => c.rank)))
}
```
```output
true
pear
[1, 2, 3]
["pawn", "queen"]
Some(Card { rank: 3, name: "queen" })
```

配套的列表函数都是稳定排序、平局取第一个：`sort`/`max`/`min` 要求元素有 `Ord`，
`sort_by(xs, cmp)` 接自定义比较函数，`max_by`/`min_by(xs, key)` 按键取极值
（键类型要有 `Ord`）。

trait 方法，以及任何带约束的函数，都可以当裸函数值传递。它要的是一个期望的函数
类型，因为那才说明约束在哪个类型上解析；剩下的包装连同字典由编译器写出：

```dawn run
fn shout[T: Show](xs: List[T]) -> List[String] = map(xs, to_string)

pub fn main() -> Unit !io = {
  println(join(shout([1, 2, 3]), " "))
  # 这里的约束是 `shout` 自己的，所以包装闭包捕获 `shout` 收到的那个字典，
  # 与手写 `x => to_string(x)` 同形
  println(join(shout(["a", "b"]), " "))
}
```
```output
1 2 3
"a" "b"
```

没有期望类型时（比如 `let f = to_string`），约束没有可解析的类型，编译器会直接
这么说；写出类型，或者手写带标注参数的 lambda。

### 一个 List 装多种类型：函数字段的 record

`List[T]` 只装一个 `T`。想让一个列表装**不同类型**、而它们都支持同一个操作时，Dawn 没有
`dyn Trait` 可用。做法是：把那个操作装进一个函数字段的 record，用 `opaque` 类型把 record
藏起来，再给这个类型写它自己的 impl。约束在打包的地方解析，那是具体类型最后一次还看得见
的位置：

```dawn run
type ShownRepr = { render: fn() -> String }

pub opaque type Shown = ShownRepr

pub fn shown[T: Show](x: T) -> Shown = {
  let r: ShownRepr = ShownRepr { render: () => show(x) }
  r
}

impl Show[Shown] {
  fn show(s: Shown) -> String = {
    let r: ShownRepr = s
    r.render()
  }
}

pub fn main() -> Unit !io = {
  let xs: List[Shown] = [shown(1), shown("two"), shown(true)]
  for x in xs {
    println("${x}")
  }
}
```
```output
1
"two"
true
```

第二行带引号。那是 `Show[String]` 一贯的渲染结果，不是例子写错了。

这一招对「主体只出现在一个位置」的 trait 完整可用：`Show`、`Hash`，以及任何
`fn(T) -> ...` 形状的方法。它够不着 `Eq` 和 `Ord`：`eq(a: T, b: T)` 与
`cmp(a: T, b: T)` 要两个**同一类型**的值，而打包扔掉的恰好就是这个事实。所以异构的
`List` 有，异构的 `Map` 键没有。这条线为什么落在这里、Dawn 为什么不做 trait 对象，
见 [trait.md](trait.md) §10。

impl 的主体可以是泛型的：`impl[T: Eq] Eq[List[T]]` 是一条**条件 impl**，泛型类型上的
`derive` 写出的也是一条（`type Box[T] = { v: T } derive Ord` 得到
`impl[T: Ord] Ord[Box[T]]`）。v1 的边界：主体的实参必须是这个 impl 自己的、互不相同的
类型参数（`impl Eq[List[Int]]` 被拒绝）；comptime 里不能用 trait 约束的调用。
完整设计见 [trait.md](trait.md)。

### 关联类型，以及 `[]` 与 `for` 背后的 trait

trait 可以声明一个属于自己、由每个 impl 填上的类型：trait 里写 `type Item`，impl 里写
`type Item = String`。签名经由类型参数够到它，写作 `C.Item`，于是泛型函数可以谈论
「这个容器装的东西」，而不必知道那是什么：

```dawn run
trait Store[C] {
  type Key
  type Item
  fn fetch(c: C, k: C.Key) -> Option[C.Item]
}

type Shelf = { names: List[String] }

impl Store[Shelf] {
  type Key = Int
  type Item = String
  fn fetch(c: Shelf, k: Int) -> Option[String] = get(c.names, k)
}

# 泛型的使用方：不管 store 的键和元素是什么，照原样用
fn fetch_or[C: Store](c: C, k: C.Key, fallback: C.Item) -> C.Item =
  match fetch(c, k) {
    Some(x) -> x
    None -> fallback
  }

pub fn main() -> Unit !io = {
  let s = Shelf { names: ["tea", "rice"] }
  println(fetch_or(s, 1, "nothing"))
  println(fetch_or(s, 5, "nothing"))
}
```
```output
rice
nothing
```

`fetch_or` 只对着 trait 检查一次；每个调用点上 `C.Item` 变成该 impl 绑定的类型，所以
`fetch_or(s, 1, "nothing")` 收一个 `String`、也返回 `String`。impl 对每个关联类型恰好
绑定一次；漏绑，或者绑了 trait 没声明的名字，都是错误。

有两个内置 trait 就是这么写的，语言自己的语法正是经过它们。`Index[C]` 有 `type Idx`、
`type Item` 和一个方法 `index`，`c[i]` 调的就是它：`List`（以 `Int` 为下标）和 `Map`
（以键为下标）自带 impl，给自己的类型写一个 impl 就有了 `[]`。`Iter[C]` 有 `type Cur`、
`type Item` 和四个游标方法，`for x in c` 走的就是它：

```dawn run
type Grid = { w: Int, cells: List[Int] }

impl Index[Grid] {
  type Idx = (Int, Int)
  type Item = Int
  fn index(g: Grid, p: (Int, Int)) -> Int = {
    let (x, y) = p
    g.cells[y * g.w + x]
  }
}

type Countdown = { from: Int }

impl Iter[Countdown] {
  type Cur = Int
  type Item = Int
  fn iter_start(it: Countdown) -> Int = it.from
  fn iter_done(it: Countdown, c: Int) -> Bool = c == 0
  fn iter_next(it: Countdown, c: Int) -> Int = c - 1
  fn iter_get(it: Countdown, c: Int) -> Int = c
}

pub fn main() -> Unit !io = {
  let g = Grid { w: 3, cells: [1, 2, 3, 4, 5, 6] }
  println("${g[(2, 1)]}")
  let launch = Countdown { from: 3 }
  for n in launch {
    print("${n} ")
  }
  println("liftoff")
}
```
```output
6
3 2 1 liftoff
```

两个 trait 都在 prelude 里，所以两个 impl 都不需要 `use`。`[]` 只读（没有 `c[i] = v`），
一个类型也只有一种下标类型。`index` 本身不能按名字调用，因为 `[]` 就是它的写法；
`Iter` 的四个方法可以。

另见：[spec.md](spec.md) §3.5、§4.8

## 17. 自己的效果：`effect` 与 `with handle`

`!io` 是编译器内建的那一种效果。你也可以声明自己的：一组**操作**，谁来实现由调用方
在使用点决定。

```dawn run
effect Ask {
  fn ask() -> Int
}

fn sum_three() -> Int !Ask = ask() + ask() + ask()

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 42 }
  println(to_string(sum_three()))
}
```
```output
126
```

三件事在这段里：

- `effect Ask { ... }` 声明效果与它的操作。操作是**没有体**的函数签名——体由 handler 给。
- `sum_three` 直接调 `ask()`，签名里写下 `!Ask`。不写会报错，并告诉你两条出路。
- `with handle Ask { ask() => 42 }` 装上 handler：**这一句之后的整个块**在它的作用域内。
  臂 `ask() => 42` 就是一个闭包，调用 `ask()` 就是调它，返回值就是 `ask()` 的值。
- 这个「块的剩余部分」自己也是闭包，所以它按值捕获：`with handle` **之前**声明的 `var`，
  在它之后既不能读也不能赋值；**之后**声明的 `var` 没问题。诊断会说明这一点，并给两条
  出路：在 `with handle` 之前先 `let` 一个快照，或者把值作为参数传进来。

### 多个操作，和有参数的操作

一个效果可以有多个操作，handler 必须**每个都答**，一个不多一个不少：

```dawn run
effect Log {
  fn note(msg: String) -> Unit
  fn level() -> Int
}

fn work(n: Int) -> Int !Log = {
  note("working on ${n}")
  n * level()
}

pub fn main() -> Unit !io = {
  with handle Log {
    note(m) => println("[log] ${m}")
    level() => 3
  }
  println(to_string(work(7)))
}
```
```output
[log] working on 7
21
```

臂的身体可以做任何事——包括 io。它算在**装 handler 的那个块**头上（上面的 `main` 因此
是 `!io`），不算在发出操作的 `work` 头上：`work` 只欠 `!Log`。

### 谁来应答：词法上最近的那个

handler 是按**写在哪里**找的，不是按运行时的栈找的。内层遮蔽外层：

```dawn run
effect Ask {
  fn ask() -> Int
}

fn twice() -> Int !Ask = ask() + ask()

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 1 }
  println(to_string(twice()))
  with handle Ask { ask() => 10 }
  println(to_string(twice()))
}
```
```output
2
20
```

臂里再发**本效果**，找的是**外层**的 handler（handler 不答自己）——所以
`with handle Ask { ask() => ask() * 10 }` 是「把外面那个答案乘十」，不是死循环。

闭包**不会**留住它写在谁下面的那个 handler。带它跑出块外，标签也跟着跑：它的行里仍写着
`!Ask`，应答的是**最终调用它的地方**在场的那个 handler。类型说的是谁得供 handler，
不是某个臂会做什么，所以纯臂的 handler 交给你的同样是一个 `!Ask` 闭包，io 臂的也是。

于是函数类型可以写具名效果，而且字面读法就是它的意思。`fn(f: fn() -> Int !Ask)` 说的是
「谁调用 `f`，谁供 `Ask` 的 handler」，调用真就是这么走的。`fn(f: fn() -> Int !e)`
是另一种写法，不是迁移写法：效果变量收任何行的闭包，并把那条行转发进你自己的行。

### 高阶函数不用改一行

效果变量（`!e`）会连同具名效果一起转发，所以 `map`、`fold`、`for` 循环都照旧：

```dawn run
effect Ask {
  fn ask() -> Int
}

fn shifted(xs: List[Int]) -> List[Int] !Ask = map(xs, x => x + ask())

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 100 }
  println(to_string(shifted([1, 2, 3])))
}
```
```output
[101, 102, 103]
```

### handler 的状态：臂表里的 `var`

臂表的开头可以声明若干 `var`。每一个都是一格**状态格子**：属于这一次 handler 安装的可变
状态。臂读它写它，`with handle` 之后的块剩余再读它，这就是一个攒东西的 handler 把攒下来的
东西交回给安装点的方式。

```dawn run
effect Spend {
  fn spend(item: String, n: Int) -> Bool
}

## 没有预算参数，也没有累加量：`shop` 只知道自己在问。
fn shop(orders: List[(String, Int)]) -> List[String] !Spend = {
  var bought: List[String] = []
  for o in orders {
    let (item, cost) = o
    if spend(item, cost) {
      bought = bought ++ [item]
    }
  }
  bought
}

pub fn main() -> Unit !io = {
  with handle Spend {
    var left: Int = 10
    var skipped: List[String] = []
    spend(item, n) =>
      if n <= left {
        left = left - n
        true
      } else {
        skipped = skipped ++ [item]
        false
      }
  }
  let bought = shop([("bread", 3), ("cheese", 12), ("apples", 4)])
  println("${bought} left=${left} skipped=${skipped}")
}
```
```output
["bread", "apples"] left=3 skipped=["cheese"]
```

`shop` 没有预算参数、没有累加器，返回值里也不带一个。预算是 handler 的，两格格子是它存
预算的地方，`main` 的最后一行就是「`with handle` 之后的块剩余」在读它们。没有 return 臂，
格子是带状态的 handler 唯一的交回表面。

格子必须**全部排在臂之前**，而且类型标注不可省：臂表的花括号里没有可推的上下文。

两条规则把格子和普通 `var` 分开：

- 臂是闭包，所以臂里不能写外层的 `var`（本节开头那条规则）。例外是它自己的格子：那是这次
  安装自己的状态，不是从外面捕获进来的绑定。
- 格子出不去。臂**里面**手写的 lambda 不许捕获它，格子本身也没有可拼写的类型，所以没有第二
  个名字够得着它。

每次安装各有各的格子。同一个效果再嵌套装一次，格子是另一套，内层攒的东西不会跑到外层去。

### 标准库的效果，以及一张表做的文件系统

程序平常直接调用的那几块外部世界，`std/io` 用本章一直在写的那种效果声明出来：`Fs`
（文件）、`Env`（工作目录与环境变量）、`Proc`（运行另一个程序）、`Exit`（结束进程）和
`Console`（写 stdout 与 stderr）。`io.read_file` 等文件函数是 `!Fs`，`io.getenv` 和
`io.cwd` 是 `!Env`，`io.run` 是 `!Proc`。于是签名说出了函数碰的是世界的哪一块，测试也
可以用一个假的 handler 来应答那个效果。

std 自带一个现成的假实现：`std/memfs` 用内存里的一张表应答 `Fs`。
`memfs.with_fs(tree, body)` 在 `tree` 上跑 `body`，把结果连同 `body` 跑完后的那棵树一起
交回来。`Env` 只有两个操作，给它写个假的就是两行 `with handle`：

```dawn run
use std/io
use std/io.{Fs, Env}
use std/memfs
use std/str

# 签名把话说完了：它碰文件，别的什么都不碰。
fn archive(path: String) -> Result[Int, ForeignError] !Fs = {
  let text = io.read_file(path)?
  io.write_file(path ++ ".bak", text)?
  Ok(len(str.split(text, "\n")))
}

# 这个读环境，别的什么都不碰。
fn greeting() -> String !Env =
  match io.getenv("USER") {
    Some(name) -> "hello, ${name}"
    None -> "hello, stranger"
  }

pub fn main() -> Unit !io = {
  let tree = memfs.put(memfs.empty(memfs.BASE), "notes.txt", "one\ntwo\nthree")
  let (lines, after) = memfs.with_fs(tree, () => archive("notes.txt"))
  println("${lines}")
  println("${memfs.file_paths(after)}")
  println("${memfs.text(after, "notes.txt.bak")}")

  with handle Env {
    env_cwd() => "/home/ada"
    env_get(name) => if name == "USER" { Some("ada") } else { None }
  }
  println(greeting())
}
```
```output
Ok(3)
["/dawn-memfs/notes.txt", "/dawn-memfs/notes.txt.bak"]
Some("one\ntwo\nthree")
hello, ada
```

`archive` 读了一个文件、写了另一个，自始至终没碰磁盘。`memfs.with_fs` 是纯的，所以同样
几行放进 `test` 块也能用，不用建临时目录，也不用收拾。程序要接触真实世界，就在最外层
装一次生产 handler：`io.with_fs_real(() => ...)`，以及同样形状的 `with_env_real`、
`with_proc_real`、`with_exit_real` 和 `with_console_real`，它们都是 `!io`。（`println`
本身目前仍是普通的 `!io`；`Console` 是给那些想让测试读回输出的代码准备的。）

### 控制臂：`ctl`、`resume k` 与 `discard`

到目前为止，每条臂都是应答操作，然后让调用方接着往下走。声明为 `ctl` 的效果还可以带
**控制臂**，它拿到的是剩下的那段计算：`op(args) resume k => ...` 绑定 `k`，一个函数，
用你传给它的值从操作之后接着往下跑。臂的值就是整个 `with handle` 块的值，所以不调用
`k` 的臂会提前结束这个块，答案由它自己给。

```dawn run
ctl effect Check {
  fn check(ok: Bool, why: String) -> Unit
}

fn validate(age: Int) -> String !Check = {
  check(age >= 0, "negative")
  check(age < 150, "too large")
  "age ${age}"
}

fn close(name: String) -> Unit !io = println("closed ${name}")

fn admit(age: Int) -> String !io = {
  with handle Check {
    check(ok, why) resume k =>
      if ok {
        k(())
      } else {
        discard(k)
        "rejected: ${why}"
      }
  }
  with log <- bracket("log", close)
  "${log}: ${validate(age)}"
}

pub fn main() -> Unit !io = {
  println(admit(30))
  println(admit(-1))
  println(admit(200))
}
```
```output
closed log
log: age 30
closed log
rejected: negative
closed log
rejected: too large
```

`admit(-1)` 里，`validate` 发出 `check(false, "negative")`，臂不恢复：第二个 `check` 和
`"age ..."` 那一行都不会跑，`"rejected: negative"` 就是 `admit` 整个块的答案。
`admit(30)` 里臂在每次 check 都调用 `k(())`，块的其余部分最后算出的值从 `k` 里返回，
成为臂的值。

续延只能用一次：恢复两次是 panic。确定不再恢复的续延用 `discard(k)` 放弃，操作与 handler
之间的清理靠它来跑；这里就是打印 `closed log` 的那个 `bracket`，三条路径上它都跑了。
只是把 `k` 扔掉则什么都不跑，这是有意的：要是清理在回收器哪天轮到它时才跑，两个后端上的
行为就会不一样。`k` 是普通函数值，也可以存起来以后再恢复。`std/io` 的 `Exit` 是 `ctl`
效果，理由正是本节开头那一条：测试用一条不恢复的臂应答 `io.exit(1)`，把退出码当作值交回来，
而生产环境的臂结束进程。

### v1 的边界

- 「操作不返回调用点」的用法通常走既有的失败机制：`Result` + `?`、
  `catch_fault`/`catch_panic`/`bracket`。
- 效果不带类型参数（没有 `effect Yield[T]`）。
- comptime / const 初始化不发具名效果，也装不了 handler。trait / impl 方法可以带标签，
  任何写出来的函数类型（`alias` 目标、record 字段、参数位）也可以；impl 仍欠的是一条
  标签与 trait 恰相等的行，因为每个标签都是这个方法的一格隐藏参数。
- 带标签的函数可以当函数值传：标签进到值的类型里，由调用点供 handler。只有**操作**本身
  不行，它背后没有可取的函数符号；包一层 lambda（`() => ask()`）即可。
- 臂是闭包，所以臂里不能写外层的 `var`，也不能 `return`/`break` 跳出去。例外是它自己的
  格子，也就是上面那一节。

完整规则见 [spec.md](spec.md) §6.5，设计取舍见
[effects-design.md](effects-design.md)。

另见：[spec.md](spec.md) §6.5、§11

---

## 18. 包与项目

第 13 章的项目只要一个目录就够了。一旦它依赖别处的代码，就会多一个 `dawn.toml`：一份
可选的清单，装目录约定说不出的东西，也就是项目的身份和它的依赖。目录结构、入口、模块路径
仍归目录管；没有这个文件的项目，行为和以前完全一样。

```toml
schema = 1        # 永远是第一个键
name = "myapp"    # 项目的身份，[a-z_][a-z0-9_]*
```

### 依赖是源码包

包本身也是一个项目，有自己的 `dawn.toml` 和自己的 `src/`。下面是一个小包 `greet`，
就放在 `myapp` 旁边：

```
greet/
├── dawn.toml          # schema = 1, name = "greet", version = "1.0.0"
└── src/
    ├── hello.dawn
    └── style.dawn
myapp/
├── dawn.toml
└── src/
    └── main.dawn
```

`greet/src/style.dawn`：

<!-- doc-check: skip-check 包里的一个模块：没有 main，它的 pub(pkg) 也只在所属的包里才有意义 -->
```dawn skip-check
# greet 包的每个模块都看得见，包外一概看不见
pub(pkg) fn shout(s: String) -> String = s ++ "!"
```

`greet/src/hello.dawn`：

<!-- doc-check: skip-check 包的公开模块：它的 use style 要求上面那个文件在场，而包没有 main -->
```dawn skip-check
use style.{shout}

pub fn hello(name: String) -> String = shout("hello, ${name}")
```

包内的模块按它在包自己的 `src/` 下的路径互相引入，和第 13 章一样。`dawn add` 把依赖写进
`myapp` 的清单：

```text
$ dawn add ../greet --dir myapp
Added greet as `greet` (path myapp/../greet)
```

```toml
schema = 1
name = "myapp"

[deps]
greet = "../greet"
```

`[deps]` 下的键是 `myapp` 对这个包的称呼：它就是 `use` 行的第一段。

`myapp/src/main.dawn`：

<!-- doc-check: skip-check 两项目示例里的使用方那一半：use greet/hello 只能经由 myapp 的 dawn.toml 解析 -->
```dawn skip-check
use greet/hello.{hello}

pub fn main() -> Unit !io = println(hello("Dawn"))
```

`dawn run myapp` 打印 `hello, Dawn!`。

### `pub(pkg)`：包内共享，包外不可见

在模块私有（什么都不写）和 `pub` 之间还有第三级。`pub(pkg)` 声明对它所在包（一份
`dawn.toml` 描述的那个单元）的每个模块可见，对包外一概不可见。`shout` 是 `greet` 的各个
模块共用的辅助函数，`myapp` 够不着它：

```text
$ dawn run myapp      # main.dawn 里又加了一行：use greet/style.{shout}
error: `shout` is package-private to package `greet`
  --> myapp/src/main.dawn:2:18
  |
2 | use greet/style.{shout}
  |                  ^^^^^
  = hint: only modules of package `greet` may name it
```

`pub` 声明的签名里不许出现 `pub(pkg)` 类型，和不许模块私有类型出现在公开签名里是同一条
规则；`dawn doc` 也只列 `pub` 的条目。没有 `dawn.toml` 的项目是一个包，打包附带的标准库
整体也是一个包。

### 远程包、版本与 MVS

路径依赖适合放在你旁边的代码。发布出来的包是某个 URL 上的一个归档，用解包后内容的哈希
钉住：

```toml
[deps.json]
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.7.0.zip"
version = "1.0.0"
hash = "d1:<sha256>"          # 解包后文件树的内容哈希
subdir = "packages/json"      # 包在归档里的位置
```

这个哈希没人手算。`dawn add <url>` 会抓取归档、算哈希、读包自己的清单拿到名字和版本，
再把条目写进去，文件其余部分的注释和排版原样保留；`--subdir` 指明包在归档里的位置，
`--as` 换一个键。对同一个包再 add 一次会就地更新它的条目，升版本就是这么升的。

一个程序里的两个包以不同版本依赖同一个第三方包时，程序只得到它的**一份**：所要求的各个
最低版本里最高的那个。这就是最小版本选择（MVS），Go 用的那套算法；要求永远只是一个最低
版本，没有上界，也没有排除。对 Dawn 来说只有一份不是图省事。每个「trait × 类型」在整个
程序里恰有一个 impl（第 16 章），一个包有两份，它的每个类型就有两份，各带两个 impl。包的
身份是它自己清单里的 `name`，不是你给它起的键，所以一个改了名的大版本（`json2`）只要保留
旧键，照样可以写作 `use json/...`。

第三张表 `[java-deps]` 列的是给第 11 章 `use java` 用的 Maven 坐标
（`sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"`，只收精确版本）。JVM 工具链负责解析和
下载；`dawnc` 拒绝 `use java`，也就用不上它们。设计与理由见
[package-design.md](package-design.md) 和
[package-visibility-design.md](package-visibility-design.md)。

另见：[spec.md](spec.md) §10.1、§10.4

---

## 19. 后端与目标

同一份源码有两种编法，第 1 章已经见过这两个驱动。`dawn` 是 JVM 后端：`dawn run` 编成
字节码再起一个 JVM，`dawn build app -o app.jar` 写出可执行 jar，能跟着第 11 章走进
`use java` 的也只有它。`dawnc` 是 C 后端：它发出 C 交给 `cc`，所以 `dawnc build app -o app`
是一个哪里都没有 JVM 的 native 可执行文件，`dawnc run` 则是编出来马上运行。`check`、
`test`、`fmt`、`doc`、`add`、`lsp` 两边都有。

其中有两条都叫 native，它们是两条不同的路：

| 命令 | 得到什么 | `use java` |
|---|---|---|
| `dawn build app -o app.jar` | 装在 jar 里的 JVM 字节码 | 可以 |
| `dawn build app --native -o app` | 上面那个 jar，由 GraalVM `native-image` 预先编译 | 可以 |
| `dawnc build app -o app` | 由 `cc` 编译的 C，全程没有 JVM | 不行 |

不调用 Java 的程序在两边打印出相同的字节。这是验过的，不是指望：仓库让语料走两个后端，
逐字节比对输出，而且 C 后端编得动编译器自己。

### WebAssembly 与 reactor

`dawnc` 还有一个目标。`dawnc build --target wasm app -o app.wasm` 用 clang 把同一份 C
编到 `wasm32-wasip1`（要一个带 WASI sysroot 的 clang；`DAWN_WASM_CC` 可以指定别的，
比如 wasi-sdk 的）。产物是一个普通的 WASI 命令模块：运行时调一次它的 `_start`，程序
一直跑到结束。

浏览器里的页面要的是另一种形状：一个一直活着、每来一个事件就被调一次的模块，`--reactor`
编的就是它。这种模块没有 `_start`，导出的恰好是三项：`memory`、`_initialize` 和 `dawn_turn`。
宿主实例化模块之后先调一次 `_initialize`，之后每来一条消息就调一次 `dawn_turn`，每次调用
跑一遍 `main`（[spec.md](spec.md) §12.5）。把状态从这一轮带到下一轮的是 `std/reactor` 的 `serve`：它读
一行，连同到目前为止的状态一起交给你的 step 函数，再留下 step 返回的状态。站点的
[演示](https://dawn-lang.dawnop.com/zh/tea.html)页就是三个这样的 reactor（一个计数器、
一个待办列表和站内搜索），各自用 `dawnc build --target wasm --reactor` 编出，由
`packages/tea-dom` 从 JavaScript 驱动。wasm 这边只读写消息，从不碰 DOM 节点；同一个程序
在 shell 里也能应答：`echo '{"op":"init"}' | dawn run examples/projects/tea_dom_counter`。
设计见 [dom-bridge-design.md](dom-bridge-design.md)。

### GPU：设备是一个效果

`std/gpu` 给 GPU 程序的宿主一侧套上第 17 章一直在搭的那个形状：一个 `Gpu` 效果，它的操作
分配缓冲区、往里上传、按名字启动 kernel、等待、再下载。驱动设备的函数写 `!Gpu`，由哪台
设备应答取决于装 handler 的人。`with_gpu_fake` 用宿主内存里的一张表应答，启动 kernel 就是
调用登记在这个名字下的宿主参考函数。它是纯的，所以下面这段在哪儿都能跑，不要 GPU、不要
驱动，也不要 `!io`：

```dawn run
use std/gpu.{Gpu, F64, alloc, upload, download, launch, sync, free, handle_of, with_gpu_fake,
  reference_kernels}

# GPU 程序的宿主一半：分配、上传、启动、等待、读回。
# 它唯一的效果是 `!Gpu`；由哪台设备应答，是调用方的选择。
fn vector_add(xs: List[Float], ys: List[Float]) -> Result[List[Float], ForeignError] !Gpu = {
  let n = len(xs)
  let a = alloc(F64, n)?
  let b = alloc(F64, n)?
  let out = alloc(F64, n)?
  upload(a, xs)?
  upload(b, ys)?
  launch("vadd", 1, [handle_of(a), handle_of(b), handle_of(out)])?
  sync()?
  let got = download(out)?
  free(a)?
  free(b)?
  free(out)?
  Ok(got)
}

fn unknown_kernel() -> Result[Unit, ForeignError] !Gpu = {
  let h = alloc(F64, 1)?
  launch("vmul", 1, [handle_of(h)])
}

pub fn main() -> Unit !io = {
  # 假设备：宿主内存里的一张表，所以在哪儿都能跑，而且是纯的
  let sum = with_gpu_fake(reference_kernels(), () => vector_add([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]))
  println("${sum}")
  # 设备不认识的 kernel 会被拒绝，而不是瞎猜
  match with_gpu_fake(reference_kernels(), () => unknown_kernel()) {
    Ok(_) -> println("ran")
    Err(e) -> println("refused: ${e.kind}")
  }
}
```
```output
Ok([11.0, 22.0, 33.0])
refused: gpu.no_kernel
```

`reference_kernels()` 是假设备自带的表（`vadd`、`vadd_bf16` 和 `sum`）。同一个
`vector_add` 一字不改，就能在真卡上跑在 `with_gpu_real(kernels, body)` 底下：它用 CUDA
驱动应答同样的操作，`kernels` 把每个名字映到编译好的模块。这个 handler 需要 C 后端
（在 JVM 上每个操作都答 `gpu.unsupported_backend`），还需要一台装了 NVIDIA 驱动的机器。

kernel 本身也是 Dawn，对着 `packages/tileir` 写：它的 `Dev` 效果把 kernel 执行的操作记录
下来，记录再编码成 NVIDIA 的 Tile IR 字节码，由 `tileiras` 汇编成 `with_gpu_real` 装载的
模块。记录同样是纯的，所以这里就能看它发生。这个例子要用 `packages/tileir`，所以它是一个
`[deps]` 里写着 `tileir` 的项目（第 18 章），不是单个文件；它也没有 Playground 链接，因为
Playground 只跑单个文件：

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_cell, store_cell}
use tileir/prog.{trace2, cells, In, Out}
use tileir/render.{render}

# 每个 tile 块读 `x` 里属于自己的那一格，写进 `out` 里属于自己的那一格。
# 这里一个数也没拷：函数体只跑一次，跑在一个把它记录下来的 handler 底下。
fn copy(x: Param[F64], out: Param[F64]) -> Unit !Dev = store_cell(out, load_cell(x))

# 一行 Tile IR 执行的操作：`=` 后面的那个词，如果有的话。
fn op_of(line: String) -> Option[String] = match str.split_once(line, " = ") {
  Some((_results, rest)) -> Some(str.split(rest, " ")[0])
  None -> None
}

pub fn main() -> Unit !io = {
  let g = cells([256], [128])     # 256 个元素，每格 128：两个 tile 块
  let (prog, _entry) = trace2("copy", In(F64, g), Out(F64, g), copy)
  for line in str.split(render(prog), "\n") {
    match op_of(line) {
      Some(op) -> println(op)
      None -> ()
    }
  }
}
```
```output
make_token
assume
make_tensor_view
make_partition_view
get_tile_block_id
load_view_tko
assume
make_tensor_view
make_partition_view
store_view_tko
```

`copy` 从头到尾没见过一个数。`trace2` 在一个 handler 底下把它的函数体跑了一次，handler 把每个
`Dev` 操作记下来；`render` 把这份记录打印成 Tile IR 文本，一行一个操作，上面的程序只留下每行的
操作名。两个参数怎么切由 `In` 和 `Out` 标记说，所以 kernel 体里一个形状也不写：每个 tile 块
找到自己的格子（`get_tile_block_id`），载入，再存回去。

第 20 章讲怎么写 kernel：标记说了什么、记录拒绝什么、循环、归约，以及宿主程序怎样在假设备
和真卡上跑它。

另见：[spec.md](spec.md) §12.1、§12.3

---

## 20. GPU kernel

第 19 章记录了一个 kernel，就停在了那里。本章写六个，每个讲一件事：向量加法、长度不是 tile
整数倍的向量、softmax、矩阵乘、按行的 softmax，以及转置。最后一节之前的内容在任何机器上都能
跑，用 JVM 后端即可，因为记录 kernel 是纯的，假设备也是纯的。只有最后一节需要 GPU、它的驱动
和 `tileiras`。

GPU 程序分两层，每层一个效果。kernel 体唯一的效果是 `!Dev`，来自 `packages/tileir`：函数体
在宿主上只跑一次，跑在一个把每个操作记下来的 handler 底下，记下来的就是 Tile IR。宿主一侧的
效果是 `!Gpu`，来自 `std/gpu`（第 19 章）：它分配缓冲区，按名字启动记录好的 kernel。本章每个
例子都是 `[deps]` 里写着 `tileir` 的项目，所以都没有 Playground 链接。想自己跑，就把它放进一个
项目的 `src/main.dawn`，项目的 `dawn.toml` 指向你检出里的 `packages/tileir`，写法照
`examples/projects/gpu_fake/dawn.toml`。

### kernel 是一个会被记录的函数

```dawn run deps=tileir
use std/gpu.{F64}
use tileir/dev.{Dev, Param, load_cell, store_cell, addf}
use tileir/prog.{trace3, cells, In, Out}
use tileir/render.{render}

# 每个 tile 块读 `a` 和 `b` 里属于自己的那一格，写进 `out` 里属于自己的那一格。
fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(a), load_cell(b)))

pub fn main() -> Unit !io = {
  let g = cells([256], [128])     # 256 个元素，每格 128：两个块
  let (prog, _entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
  print(render(prog))
}
```
```output
cuda_tile.module @m {
  entry @vadd(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %14 = addf %7, %12 rounding<nearest_even> : tile<128xf64>
    %15 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %18 = store_view_tko weak %14, %17[%4] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
```

`vadd` 什么也没算。`trace3` 拿三个参数句柄调用了它一次，调用发生在一个 handler 底下，handler
把函数体执行的每个 `Dev` 操作记下来；`render` 把这份记录打印成 `cuda_tile` 文本。函数体执行了
四个操作（两个 `load_cell`、一个 `addf`、一个 `store_cell`），文本其余部分是它们降低出来的样子。
每个参数先成为它整个张量的视图（`make_tensor_view`），再按标记描述的格子切开
（`make_partition_view`）。`get_tile_block_id` 是正在跑的那个块，`load_view_tko` 读这个块的格子。
`assume div_by<16>` 是关于指针对齐的一个承诺，汇编器可以利用它。

`!Dev` 是函数体唯一的效果，所以够不到宿主内存，也没有数可看：kernel 能做的恰好就是 `Dev`
提供的那些。`Param[F64]` 是元素格式为 `std/gpu` 的 `F64` 的参数，和宿主缓冲区带的是同一个
标记，所以在这个 kernel 要 `F64` 的位置传 `Tensor[F32]` 是类型错误。

### 格子：形状写在哪里

`vadd` 的函数体里没有长度，没有 tile 宽度，也没有偏移。这些属于标记。`cells([1000], [128])`
把 1000 个元素的张量切成每格 128：八格，最后一格有 24 个 lane 越过了末尾。`In` 和 `Out` 说明
kernel 对每个参数做什么，而 `Out` 的格子就是启动网格：八个块，块 `i` 读写第 `i` 格。越过
extent 的 lane 读到的是标记的填充值（标记不另说就是零），而且不写回，所以尾巴不需要 mask。

```dawn run deps=tileir
use std/gpu.{Gpu, F64, alloc, upload, download, with_gpu_fake, reference_kernels, launch_entry3}
use std/list
use tileir/dev.{Dev, Param, load_cell, store_cell, addf}
use tileir/prog.{trace3, cells, In, Out}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(a), load_cell(b)))

# 宿主一半：三个 `n` 元素的缓冲区，按 1000 个元素的格子启动。
fn add_1000(n: Int) -> Result[List[Float], ForeignError] !Gpu = {
  let g = cells([1000], [128])     # 八格；最后一格有 24 个 lane 越过末尾
  let (_prog, entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
  let xs = list.map(range(0, n), i => to_float(i))
  let a = alloc(F64, n)?
  let b = alloc(F64, n)?
  let out = alloc(F64, n)?
  upload(a, xs)?
  upload(b, xs)?
  launch_entry3(entry, a, b, out)?
  download(out)
}

pub fn main() -> Unit !io = {
  for n in [1000, 999] {
    match with_gpu_fake(reference_kernels(), () => add_1000(n)) {
      Ok(ys) -> println("${len(ys)} values, the last is ${ys[len(ys) - 1]}")
      Err(e) -> println("refused: ${e.kind}: ${e.message}")
    }
  }
}
```
```output
1000 values, the last is 1998.0
refused: gpu.short_tensor: gpu.launch_entry: kernel `vadd`: argument 0 (In) holds 999 element(s) and its cells reach 1000
```

`trace3` 答回记录和一个入口，`launch_entry3` 接这个入口和三个张量，张量的格式由入口的类型
定死。在问任何 handler 之前，它先拿缓冲区对照格子：999 个元素的缓冲区够不到 1000 个元素的
extent 的末尾。它还拒绝和格子不一致的网格，以及和别的参数共用缓冲区的 `Out`。extent 写成
`DYN_DIM` 时，格子数交给启动来定，比如 `launch_entry3(entry, a, b, out, grid: [8])`，这时缓冲区
要盖住每一格的全部：八格、每格 128，就是 1024 个元素。

`1998.0` 是参考实现的答案，不是 kernel 的。假设备从不运行 kernel 体：它拿启动的名字查表，调用
登记在那个名字下的宿主函数，对 `vadd` 来说就是 `std/gpu` 的 `vadd_ref`。这个程序检查的是宿主
一侧、启动检查和参考实现。kernel 与参考实现是否一致，要到真卡上才知道（最后一节）。

### 记录拒绝什么

类型检查看得见格式：在该放 `Tile[F64]` 的地方放 `Tile[F32]` 是类型错误。形状、角色和网格不在
类型里，由记录边走边查。拒绝是一个 panic，报出 kernel 名和操作（按记录顺序编号），这时还没有
任何字节码：

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_cell, store_cell, store, addf, f_const, broadcast, block_id,
  tile_at}
use tileir/prog.{trace2, cells, In, Out}

fn adds_one(x: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(x), f_const(F64, 1.0)))

fn writes_its_input(x: Param[F64], out: Param[F64]) -> Unit !Dev = store_cell(x, load_cell(x))

fn adds_two_shapes(x: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(x), broadcast(f_const(F64, 1.0), [64])))

fn stores_by_pointer(x: Param[F64], out: Param[F64]) -> Unit !Dev =
  store(out, tile_at(block_id(0), 128), load_cell(x))

# panic 的消息末尾是它在哪里被抛出；只留它说了什么。
fn reason(message: String) -> String = match str.rsplit_once(message, " at ") {
  Some((what, _where)) -> what
  None -> message
}

fn try_record(body: fn(Param[F64], Param[F64]) -> Unit !Dev) -> String = {
  let g = cells([256], [128])
  match catch_panic(() => trace2("k", In(F64, g), Out(F64, g), body)) {
    Ok(_) -> "recorded"
    Err(e) -> reason(e.message)
  }
}

pub fn main() -> Unit !io = {
  println(try_record(adds_one))
  println(try_record(writes_its_input))
  println(try_record(adds_two_shapes))
  println(try_record(stores_by_pointer))
}
```
```output
recorded
tileir: kernel `k`: op #5 `store_cell`: parameter 0 is an In, and nothing writes an In
tileir: kernel `k`: op #6 `addf`: rhs is tile<64xf64>, declared tile<128xf64>
tileir: kernel `k`: op #8 `store`: parameter 1 is an Out, which is written through its cells alone (store_cell, store_sub); a parameter written any other way is a Shared
```

`adds_one` 给 128 个 lane 的 tile 加一个常量。常量是 0 阶的（`f_const(F64, 1.0)` 没有形状），
0 阶 tile 遇到更宽的就自己加宽。不用开口要就会发生的加宽只有这一种：`adds_two_shapes` 先把常量
加宽到 64 个 lane，再碰上 128，于是被拒。`writes_its_input` 往 `In` 里写。`stores_by_pointer`
走指针路写自己的 `Out`，在一个元素偏移处 `store`，偏移甚至是对的。它照样被拒：`Out` 只经它的
格子写（`store_cell`，或者写一格中一块的 `store_sub`），别的写法一概不行，这样「块 `i` 写第
`i` 格」就一直是记录器查的事，而不是读代码的人查的事。要写到别处的 kernel 把参数声明成
`Shared`，下面的转置就是这样。

### 归约与填充

四个 lane 装三个值的 softmax。这次假设备跑的参考实现是这里写的，不是 `std/gpu` 自带的：

```dawn run deps=tileir,tileref
use std/gpu.{Gpu, F64, Entry2, alloc, upload, download, with_gpu_fake, reference_kernels,
  launch_entry2, last_out}
use std/list
use std/map
use std/str
use tileir/dev.{Dev, Param, PadNegInf, load_cell, store_cell, exp, sub, div, reduce_max,
  reduce_sum}
use tileir/prog.{trace2, cells, In, Out}
use tileir/render.{render}
use tileref/ref.{ref_exp}

fn softmax(x: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let t = load_cell(x)                        # 越过 extent 的那个 lane 读到 -inf
  let e = exp(sub(t, reduce_max(t)))          # reduce_max(t) 是 0 阶的，会自己加宽
  store_cell(out, div(e, reduce_sum(e)))      # extent 之外一个也不写
}

# kernel 的合同，写在宿主上：`x` 前 `n` 个值的 softmax，
# `out` 在它们之后的每个元素原样不动。
fn softmax_ref(n: Int, _formats: List[String], bufs: List[List[Float]]) -> List[Float] = {
  let xs = list.take(bufs[0], n)
  let m = list.fold(xs, xs[0], (a, v) => if v > a { v } else { a })
  let es = list.map(xs, v => ref_exp(v - m))
  let total = list.fold(es, 0.0, (a, v) => a + v)
  list.map(es, v => v / total) ++ list.drop(bufs[1], n)
}

fn run(entry: Entry2[F64, F64]) -> Result[List[Float], ForeignError] !Gpu = {
  let x = alloc(F64, 4)?
  let out = alloc(F64, 4)?
  upload(x, [1.0, 2.0, 3.0, 0.0])?
  upload(out, [9.0, 9.0, 9.0, 9.0])?     # out[3] 在 extent 之外：kernel 不碰它
  launch_entry2(entry, x, out)?
  download(out)
}

pub fn main() -> Unit !io = {
  let (prog, entry) = trace2("softmax", In(F64, cells([3], [4], pad: PadNegInf)),
    Out(F64, cells([3], [4])), softmax)
  # 填充值是记录的一部分
  for line in str.split(render(prog), "\n") {
    if str.contains(line, "= make_partition_view") && str.contains(line, "neg_inf") {
      println(str.trim(line))
    }
  }
  let kernels = map.insert(reference_kernels(), "softmax",
    (2, last_out((formats, bufs) => softmax_ref(3, formats, bufs))))
  println("${with_gpu_fake(kernels, () => run(entry))}")
}
```
```output
%3 = make_partition_view %2 : partition_view<tile=(4), padding_value = neg_inf, tensor_view<3xf64, strides=[1]>, dim_map=[0]>
Ok([0.09003057317038043, 0.24472847105479767, 0.6652409557748218, 9.0])
```

`PadNegInf` 让越过 extent 的那个 lane 读到 `-inf`。求最大值时它不起作用，`exp` 它恰好是 0，
所以总和就是三个真 lane 的和。换成默认的零填充，总和会多算一个 `exp(0 - 3)`，每个答案都偏小
一点。填充值写在记录下来的程序里（`padding_value = neg_inf`），所以设备也受它约束。
1 阶 tile 的 `reduce_max(t)` 是 0 阶的，`sub` 碰上四个 lane 的 `t` 时它自己加宽。

`softmax_ref` 是 kernel 的合同，写在宿主上。它答回前 `n` 个值的 softmax，之后的元素原样不动，
所以哨兵 `9.0` 留了下来。`last_out` 把一个只答最后一个缓冲区的函数变成 `with_gpu_fake` 要的
表项，旁边的 `2` 是 kernel 接几个缓冲区。这个文件里的 `exp` 是设备的，所以宿主一侧用
`packages/tileref` 的 `ref_exp`；仓库自己那些 kernel 的参考实现都在那个包里。

### 循环与矩阵

矩阵乘，每个块算 `c` 的一个 64×64 tile，沿 K 走：

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_at, store_cell, zeros, mmaf, d_range}
use tileir/prog.{trace3, cells, In, Out, FREE_AXIS}
use tileir/render.{render}

fn matmul(a: Param[F64], b: Param[F64], c: Param[F64]) -> Unit !Dev = {
  let acc = d_range(0, 256 / 32, zeros(c), (k, sofar) => mmaf(load_at(a, [k]), load_at(b, [k]), sofar))
  store_cell(c, acc)
}

pub fn main() -> Unit !io = {
  let a = In(F64, cells([256, 256], [64, 32], along: [0, FREE_AXIS]))
  let b = In(F64, cells([256, 256], [32, 64], along: [FREE_AXIS, 1]))
  let c = Out(F64, cells([256, 256], [64, 64]))     # 网格：4×4 个块
  let (prog, _entry) = trace3("matmul", a, b, c, matmul)
  # 沿 K 走八趟，记录里却只有一个循环、一个 mmaf
  for line in str.split(render(prog), "\n") {
    let l = str.trim(line)
    if str.contains(l, "= for ") || str.contains(l, "= mmaf ") || str.starts_with(l, "continue ") {
      println(l)
    }
  }
}
```
```output
%5, %6 = for %7 in (%2 to %3, step %4) : tile<i32> iter_values(%8 = %1, %9 = %0) -> (tile<64x64xf64>, token) {
%26 = mmaf %16, %24, %8 : tile<64x32xf64>, tile<32x64xf64>, tile<64x64xf64>
continue %26, %25 : tile<64x64xf64>, token
```

`along` 说格子的每一维跟网格的哪个轴走。`a` 的第 0 维（行）跟网格轴 0，第 1 维（沿 K）不跟任何
轴：`FREE_AXIS` 的意思是这一维由 kernel 自己挑格子，挑法就是 `load_at(a, [k])`。`b` 正好反过来，
`c` 是 `Out`，它的格子就是网格。`d_range(0, 8, init, body)` 是走八趟的循环，带着一个 tile，也就是
累加器。`zeros(c)` 是一个形状和 `c` 的一格相同的 tile，所以累加器的形状从头到尾不用写；`mmaf` 从
操作数读出 m、k、n（`a` 和 `b` 的 k 对不上，记录时就拒）。

循环体和 kernel 体一样只跑了一次：记录里是一个 `for` 区域，八趟由设备去跑。这个区域在累加器
旁边还带着第二个值，token。内存操作的先后由记录器串起来的 token 链决定，不由程序文本的先后决定。

### 按行归约：keepdims 与 broadcast

二维时，归约要选一维来做。这里每个块拿 32 行、每行 64 个分数，把每一行变成 softmax：

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_cell, store_cell, exp, sub, div, reduce_max, reduce_sum,
  broadcast}
use tileir/prog.{trace2, cells, In, Out}

fn row_softmax(x: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let s = load_cell(x)                                          # [32, 64]
  let m = broadcast(reduce_max(s, keepdims: true), [32, 64])    # [32, 1]，再到 [32, 64]
  let p = exp(sub(s, m))
  store_cell(out, div(p, broadcast(reduce_sum(p, keepdims: true), [32, 64])))
}

# 同一个 kernel，去掉了第一个 `broadcast`。
fn row_softmax_unbroadcast(x: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let s = load_cell(x)
  let p = exp(sub(s, reduce_max(s, keepdims: true)))
  store_cell(out, div(p, broadcast(reduce_sum(p, keepdims: true), [32, 64])))
}

fn reason(message: String) -> String = match str.rsplit_once(message, " at ") {
  Some((what, _where)) -> what
  None -> message
}

fn try_record(body: fn(Param[F64], Param[F64]) -> Unit !Dev) -> String = {
  let g = cells([256, 64], [32, 64])     # 八个块，每块 32 行
  match catch_panic(() => trace2("row_softmax", In(F64, g), Out(F64, g), body)) {
    Ok(_) -> "recorded"
    Err(e) -> reason(e.message)
  }
}

pub fn main() -> Unit !io = {
  println(try_record(row_softmax))
  println(try_record(row_softmax_unbroadcast))
}
```
```output
recorded
tileir: kernel `row_softmax`: op #10 `subf`: rhs is tile<32x1xf64>, declared tile<32x64xf64>
```

`reduce_max(s, keepdims: true)` 归约最后一维（默认 `dim: -1`），并把这一维留成长度 1：得到
`[32, 1]` 的 tile，每行一个最大值。把它加宽回 `[32, 64]` 要用 `broadcast` 写出来，因为只有 0 阶
tile 会自己加宽。第二个 kernel 去掉了 `broadcast`，在减法处被拒；拒绝里写的是 `subf`，即 `sub`
记录下的 Tile IR 操作。

NumPy 会替你加宽。不这么做，是因为它的规则会在一种情况下错得像对的：对一个方的 `[64, 64]`
tile 不带 `keepdims` 做归约，NumPy 把 `[64]` 的结果对齐到最后一个轴，于是元素 (i, j) 减去的是
第 j 行的最大值。这里那种写法同样被拒，每一次加宽都写在发生的地方。

把这一步放进一个沿 key/value 块走的循环，带上一路的最大值和一路的和，就是 FlashAttention：
`scripts/tile-golden/kernels.dawn` 里的 `flash_attn` 就是这个循环，用的是同一批操作。
[GPU 页](https://dawn-lang.dawnop.com/zh/gpu.html)展示了后端为这种规模的 kernel 记录下来的东西，
以及它们在设备上的答案是怎么被核对的。

### 格子说不清的时候：`Shared`

`Out` 的格子就是网格，顺序也是网格自己的：块 (i, j) 写第 (i, j) 格。转置打破了这一点，块
(i, j) 读 `x` 的第 (i, j) 格，写的却是 `out` 的第 (j, i) 个 tile：

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_cell, store, block_id, idx_add, idx_mul, idx_const}
use tileir/prog.{Arg, trace2, cells, In, Out, Shared}

# 128×64 的矩阵，切成 32×32 的 tile。块 (i, j) 读 `x` 里属于自己的那一格，
# 转置后写到 64×128 的 `out` 的第 (j, i) 个 tile。
fn transpose(x: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let t = load_cell(x)
  let at = idx_add(idx_mul(block_id(1), idx_const(32 * 128)), idx_mul(block_id(0), idx_const(32)))
  store(out, at, t, strides: Some([1, 128]))     # out 的步长，对调：布局本身完成转置
}

fn reason(message: String) -> String = match str.rsplit_once(message, " at ") {
  Some((what, _where)) -> what
  None -> message
}

fn try_record(out: Arg[F64]) -> String = {
  let x = In(F64, cells([128, 64], [32, 32]))     # 4×2 格
  match catch_panic(() => trace2("transpose", x, out, transpose)) {
    Ok(_) -> "recorded"
    Err(e) -> reason(e.message)
  }
}

pub fn main() -> Unit !io = {
  println(try_record(Out(F64, cells([64, 128], [32, 32]))))     # 2×4 格
  println(try_record(Shared(F64)))
}
```
```output
tileir: kernel `transpose`: argument 0 (In) has 4 cell(s) in dimension 0, which follows grid axis 0, and the grid has 2 block(s) there
recorded
```

按自己的格子声明成 `Out`，`out` 构成 2×4 的网格，`x` 的 4×2 格和它对不上，记录在函数体运行
之前就拒。`Shared(d)` 是逃生口：kernel 自己寻址的参数，走指针路。这里 `store` 在一个元素偏移处
写 tile，用的是对调过的 `out` 步长，于是 tile 落下时就转置好了，tile 内部一个元素也没挪。原子
操作、scatter、一个块写两块区域，都因为同样的理由是 `Shared`，`grep Shared(` 能把它们全找出来。
没有 `Out` 时网格归调用方：`launch_entry2(entry, x, out, grid: [4, 2])`。

另有两条出路，各一句话。一个 kernel 要用两种形状读同一个 `In`，就用 `retile(p, extent, tile)`
给它第二个视图。`trace1` 到 `trace5` 记录最多五个参数的 kernel，参数更多时用 `trace_kernel`，
每个参数都是 `Shared`。

### 上真卡

在 GPU 上跑，换的只是 handler。宿主函数还是格子那一节的那个，`with_gpu_fake` 换成
`with_gpu_real`，表里每个 kernel 名映到汇编好的模块，而不是参考实现：

<!-- doc-check: skip-check 需要 NVIDIA GPU、它的驱动和 tileiras，CI 上都没有 -->
```dawn skip-check
use std/gpu.{Gpu, F64, Entry3, alloc, upload, download, launch_entry3, with_gpu_real}
use std/io
use std/io.{with_fs_real}
use std/list
use std/map
use tileir/dev.{Dev, Param, load_cell, store_cell, addf}
use tileir/prog.{trace3, cells, In, Out}
use tileir/bytecode.{encode}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev =
  store_cell(out, addf(load_cell(a), load_cell(b)))

fn add_1000(entry: Entry3[F64, F64, F64]) -> Result[List[Float], ForeignError] !Gpu = {
  let xs = list.map(range(0, 1000), i => to_float(i))
  let a = alloc(F64, 1000)?
  let b = alloc(F64, 1000)?
  let out = alloc(F64, 1000)?
  upload(a, xs)?
  upload(b, xs)?
  launch_entry3(entry, a, b, out)?
  download(out)
}

pub fn main() -> Unit !io = {
  let g = cells([1000], [128])
  let (prog, entry) = trace3("vadd", In(F64, g), In(F64, g), Out(F64, g), vadd)
  let argv = args()
  if len(argv) == 1 && argv[0] == "encode" {
    # 这份记录，写成 tileiras 读的字节码
    println("${with_fs_real(() => io.write_bytes("vadd.tilebc", encode(prog)))}")
  } else {
    # tileiras 写出的模块，挂在入口启动时用的名字下
    match with_fs_real(() => io.read_bytes("vadd.cubin")) {
      Ok(cubin) -> match with_gpu_real(map.from([("vadd", cubin)]), () => add_1000(entry)) {
        Ok(ys) -> println("${len(ys)} values, the last is ${ys[999]}")
        Err(e) -> println("refused: ${e.kind}")
      }
      Err(e) -> println("no vadd.cubin: ${e.message}")
    }
  }
}
```

把这个程序做成项目 `vadd_card`：

```text
dawn run vadd_card -- encode                         # 写出 vadd.tilebc
tileiras --gpu-name sm_86 -o vadd.cubin vadd.tilebc
dawnc run vadd_card                                  # 在卡上启动 vadd
```

`encode` 写出的就是 `render` 打印的那份记录，格式是 `tileiras` 汇编用的字节码。`--gpu-name` 是
卡的架构（RTX 30 系列是 `sm_86`）。最后一步需要 C 后端：在 JVM 上 `with_gpu_real` 的每个操作都答
`gpu.unsupported_backend`。它还需要一个足够新、支持 Tile IR 的 NVIDIA 驱动，以及仓库测试时用的
那个 `tileiras`；两者都钉在 `scripts/tile-golden/toolchain.txt` 里，
`scripts/tile-golden/install-tileiras.sh <dir>` 从 wheel 装那个 `tileiras`。在卡上，这个程序应当
打印假设备在格子那一节打印的东西。如果打印的不一样，就是 kernel 和参考实现不一致，仓库的设备
门禁就是为了发现这种事；[GPU 页](https://dawn-lang.dawnop.com/zh/gpu.html)讲了这些门禁。

接下来去哪儿：`examples/projects/gpu_fake` 是一个完整程序，多个 kernel 加上它们的宿主一侧。
`packages/tileir/README.md` 列了参数标记和记录器拒绝的东西，`dawn doc packages/tileir` 打印整个
API。设计和实测见 [tile-backend-design.md](tile-backend-design.md)。

另见：[spec.md](spec.md) §12.6

---

至此你已见过 Dawn 的全部核心特性。更深的规范见
[spec.md](spec.md)，设计取舍见 [design.md](design.md)。这两篇**先写中文再翻译**：
它们是活文档，每次改语言都在中文里改，所以中文是正本、英文按它登记。`docs/` 其余文档
仍**只有中文**：它们的读者是作者本人，一段要先翻译才能写出来的话，就是一段写不出来的话。
