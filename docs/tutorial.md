# Dawn 教程

> 状态：**current** —— 面向读者的教程；其中标注 `dawn run` 的示例由 CI 实跑（`scripts/doc-check.py`）。

一门刻意小的静态类型语言：编译到 JVM 字节码，native 可执行文件由 GraalVM
native-image 直接得到。本教程带你从第一个程序走到调 Java。

> 本文的 `dawn` 围栏代码块曾由 Kotlin 侧的 `TutorialTest` 机械抽取、编译、运行并核对
> `output`；那套测试随 Kotlin 实现一起归档在 `kotlin-final` tag。**门禁已经补回来了**
> （docs/codebase-audit.md 的 TEST-04）：`scripts/doc-check.py` 是 CI 的一个 job，
> 把本文标了 ```` ```dawn run ```` 的块逐个真编真跑。**没标 `run` 的块仍是人工维护的**，
> 可能落后于语言——正确性重要的示例请自己标上。

---

## 1. 安装与第一个程序

需要 JDK 21（native 编译另需 GraalVM）。`bin/dawn` 会自己拉起工具链：首次运行时它下载
`scripts/seed-release.txt` 钉住的那个 release 的 `dawn-selfhost.jar`（**种子**，按
`scripts/seed-checksums.txt` 校验 SHA-256），再用种子把 `selfhost/` 编译成当前的编译器。
没有 Gradle——Kotlin 实现已随 `kotlin-final` tag 归档，`./gradlew :compiler:fatJar`
在 main 上不存在。

```bash
./bin/dawn --version              # 首次会自动取种子并重建工具链
./bin/dawn run  hello.dawn        # 编译并运行（JVM 内）
./bin/dawn test hello.dawn        # 运行文件里的 test 块
./bin/dawn build hello.dawn --native -o hello   # 产出独立二进制
```

第一个程序。函数默认是纯的；碰 IO（这里是打印）必须在签名标 `!io`：

```dawn run
pub fn main() -> Unit !io =
  println("你好，Dawn")
```
```output
你好，Dawn
```

字符串插值由 `$` 引导：`$name` 插简单变量，`${expr}` 插任意表达式（插入的值必须可打印）。
花括号本身是普通字符——不写 `$` 就不是插值：

```dawn run
pub fn main() -> Unit !io = {
  let name = "Dawn"
  let year = 2026
  println("$name 诞生于 $year")
}
```
```output
Dawn 诞生于 2026
```

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

---

## 5. 列表、元组与模式解构

内建 `List` 有字面量、`++` 连接、`len`、`range`、for-in。列表模式能解构头尾：

```dawn run
fn describe(xs: List[Int]) -> String =
  match xs {
    [] -> "空"
    [x] -> "单个 $x"
    [first, ..rest] -> "首个 $first，还有 ${len(rest)} 个"
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
  println("$q 余 $r")
}
```
```output
3 余 2
```

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
  println("$sum")

  var n = 0
  while true {
    n = n + 1
    if n * n > 30 { break }
  }
  println("$n")
}
```
```output
7
6
```

---

## 7. 错误处理：Result 与 `?`

Dawn 没有异常。可恢复的错误走 `Result[T, E]`；`?` 在 `Ok`/`Some` 时取值、
在 `Err`/`None` 时提前返回。不可恢复的用 `panic`（它不返回，故不需要 `!io`）。

```dawn run
fn half(x: Int) -> Result[Int, String] =
  if x % 2 == 0 { Ok(x / 2) } else { Err("$x 是奇数") }

fn quarter(x: Int) -> Result[Int, String] = {
  let h = half(x)?
  half(h)
}

pub fn main() -> Unit !io =
  match quarter(20) {
    Ok(v) -> println("得到 $v")
    Err(e) -> println("错误：$e")
  }
```
```output
得到 5
```

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

---

## 11. 调用 Java

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

---

## 15. 字符与码点

Dawn 没有独立的字符类型，走 Go 的 rune 路线：字符字面量 `'a'` 就是等于它**码点**的
`Int`（`'a' == 97`）。于是它在 `match` 里就是普通整数模式，字符串按码点处理。

```dawn run
use std/str

fn is_digit(c: Int) -> Bool = c >= '0' && c <= '9'

pub fn main() -> Unit !io = {
  println(to_string(is_digit('7')))
  println(to_string(str.len("héllo 🙂")))
  println(str.slice("世界你好", 0, 2))
  println(from_code_points([104, 105]))
}
```
```output
true
7
世界
hi
```

`code_points`/`from_code_points` 在字符串与码点列表间往返（含增补平面的 emoji），
`str.len` 数码点，`str.slice` 按码点下标切片，`str.from_char` 把一个码点变成字符串。

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

一步就是一个字符：emoji 的代理对不会被拆开。`cursor.find(s, sub, from)` 返回
`Option[Cursor]`，`cursor.skip(s, c, sub)` 跳过一段已知出现的字面量。

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

v1 的边界：impl 的主体只能是**非泛型**具名类型或 `Int`/`Float`/`Bool`/`String`
（没有条件 impl，`List[T]` 不能做主体）；trait 方法不能当函数值传递（包一层
lambda 即可）；comptime 里不能用 trait 约束的调用。完整设计见
[trait.md](trait.md)。

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

闭包在**创建的地方**捕获 handler，带着它跑出块外也照样有效。它的类型仍写着 `!Ask`：
逃逸决定的是谁应答，不是标签写不写。

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

### v1 的边界

- 一个臂就是一次普通调用、返回值即结果（**尾恢复**）。没有「把延续存起来以后再恢复」
  「恢复两次」这类玩法——那需要延续捕获，不在这一档里。
- 「操作不返回调用点」的用法请走既有的失败机制：`Result` + `?`、
  `catch_fault`/`catch_panic`/`bracket`。
- 效果不带类型参数（没有 `effect Yield[T]`）。
- trait / impl 方法、comptime / const、类型声明位（`alias` 目标、record 字段）
  都不接受具名效果。
- 带标签的函数（含操作本身）不能直接当函数值传——包一层 lambda 即可
  （`() => ask()`），lambda 会捕获证据。
- 臂是闭包，所以臂里不能写外层的 `var`，也不能 `return`/`break` 跳出去。

完整规则见 [spec.md](spec.md) §6.5，设计取舍见
[effects-design.md](effects-design.md)。

---

至此你已见过 Dawn 的全部核心特性。更深的规范见
[spec.md](spec.md)，设计取舍见 [design.md](design.md)。
