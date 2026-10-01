<!-- doc-check: translation-of docs/tutorial.md @ 075afa588adb57e0 -->

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
可执行文件。本教程共十九章，从第一个程序一直讲到自己声明的效果与它们的 handler，
再讲到包，以及程序可以编译到的目标。

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
模块。`examples/projects/gpu_fake` 是一个完整程序，九个这样的 kernel 加上它们的宿主一侧，
在假设备上由 `packages/tileref` 里的参考实现应答。设计，以及设备一侧今天走到了哪一步，
见 [tile-backend-design.md](tile-backend-design.md)。

另见：[spec.md](spec.md) §12.1、§12.3

---

至此你已见过 Dawn 的全部核心特性。更深的规范见
[spec.md](spec.md)，设计取舍见 [design.md](design.md)。这两篇**先写中文再翻译**：
它们是活文档，每次改语言都在中文里改，所以中文是正本、英文按它登记。`docs/` 其余文档
仍**只有中文**：它们的读者是作者本人，一段要先翻译才能写出来的话，就是一段写不出来的话。
