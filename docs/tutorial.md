# Dawn 教程

一门刻意小的静态类型语言：编译到 JVM 字节码，native 可执行文件由 GraalVM
native-image 直接得到。本教程带你从第一个程序走到调 Java。

> 本文所有 ```dawn 代码块都由测试机械保证能编译（`TutorialTest`）；带 `output`
> 的块还会真的运行并核对输出。放心照抄。

---

## 1. 安装与第一个程序

构建编译器需要 JDK 21（native 编译另需 GraalVM）：

```bash
gradle :compiler:fatJar          # 产出 dawn 工具
./bin/dawn run  hello.dawn        # 编译并运行（JVM 内）
./bin/dawn test hello.dawn        # 运行文件里的 test 块
./bin/dawn build hello.dawn --native -o hello   # 产出独立二进制
```

第一个程序。函数默认是纯的；碰 IO（这里是打印）必须在签名标 `!io`：

```dawn
pub fn main() -> Unit !io =
  println("你好，Dawn")
```

```output
你好，Dawn
```

字符串插值由 `$` 引导：`$name` 插简单变量，`${expr}` 插任意表达式（插入的值必须可打印）。
花括号本身是普通字符——不写 `$` 就不是插值：

```dawn
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

```dawn
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

```dawn
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

```dawn
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

```dawn
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

```dawn
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

---

## 5. 列表、元组与模式解构

内建 `List` 有字面量、`++` 连接、`len`、`range`、for-in。列表模式能解构头尾：

```dawn
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

```dawn
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

## 6. 错误处理：Result 与 `?`

Dawn 没有异常。可恢复的错误走 `Result[T, E]`；`?` 在 `Ok`/`Some` 时取值、
在 `Err`/`None` 时提前返回。不可恢复的用 `panic`（它不返回，故不需要 `!io`）。

```dawn
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

## 7. lambda 与效果系统

匿名函数用 `fn(参数) => 表达式`；类型可推导时参数注解可省。函数类型写作
`fn(A) -> B !e`，其中 `!e` 是效果。纯函数看签名即知没有副作用，测试无需 mock。

```dawn
pub fn main() -> Unit !io = {
  let nums = [1, 2, 3, 4]
  let evens = filter(nums, fn(n) => n % 2 == 0)
  let doubled = map(evens, fn(n) => n * 2)
  println(to_string(doubled))
}
```

```output
[4, 8]
```

高阶函数用**效果变量**转发参数的效果：`map(f)` 的效果等于 `f` 的效果。
两个函数参数的效果之并写作 `!(e1 | e2)`——纯 ∘ 纯还是纯，沾 io 便是 io。

```dawn
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2) =
  fn(a) => g(f(a))

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

## 8. 字符串与标准库

字符串函数按码点处理。`split` 是**字面量**分隔（不是正则）；`join` 是它的逆：

```dawn
pub fn main() -> Unit !io = {
  let parts = split("a,b,c", ",")
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

```dawn
pub fn main() -> Unit !io = {
  println(`"quotes" and $dollar and \n stay literal`)
}
```

```output
"quotes" and $dollar and \n stay literal
```

`parse_int` 把字符串转成 `Option[Int]`（失败是 `None`，不是异常）：

```dawn
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

## 9. comptime 与 const

`comptime { ... }` 在编译期由解释器执行，结果烧进常量池——没有宏。
顶层 `const` 名字用全大写，其初始化隐式是 comptime：

```dawn
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

## 10. 调用 Java

`use java "..."` 直接调 Java 类。所有 Java 调用自动视为 `!io`；引用类型返回值
自动包成 `Option[T]`——null 进不了 Dawn。构造用 `.new`，静态方法用类名。

```dawn
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

## 11. test 块与 dawn fmt

`test "名字" { ... }` 里用 `assert` 写断言；`dawn test` 执行它们，`dawn build`
会把它们剥除。纯函数测试不需要任何 mock：

```dawn
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

## 12. 模块与项目

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

```dawn skip-check
pub fn double(x: Int) -> Int = x * 2

pub type Shape =
  | Circle(r: Float)
  | Square(side: Float)
  derive Show
```

`src/main.dawn`：

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

## 13. Map 与 Set

`Map[K, V]` 和 `Set[T]` 是内建的**持久**容器：每次「修改」都返回新容器，原值不变。
没有字面量语法，全部通过内建函数操作。迭代顺序 = 插入顺序（JVM 与 native 一致）。

```dawn
pub fn main() -> Unit !io = {
  let m = map_insert(map_insert(map_empty(), "a", 1), "b", 2)
  println(to_string(map_get(m, "a")))
  println(to_string(map_get(m, "z")))
  println(to_string(map_keys(m)))

  let s = set_from([3, 1, 2, 1, 3])
  println(to_string(set_size(s)))
  println(to_string(set_has(s, 2)))
}
```

```output
Some(1)
None
["a", "b"]
3
true
```

键可以是任何具结构相等的类型（`Int`/`String`/元组/ADT/record）。`map_get` 返回
`Option[V]`——查不到是 `None`，不是异常。相等与顺序无关：键值相同的两个 `Map` 相等。

---

## 14. 字符与码点

Dawn 没有独立的字符类型，走 Go 的 rune 路线：字符字面量 `'a'` 就是等于它**码点**的
`Int`（`'a' == 97`）。于是它在 `match` 里就是普通整数模式，字符串按码点处理。

```dawn
fn is_digit(c: Int) -> Bool = c >= '0' && c <= '9'

pub fn main() -> Unit !io = {
  println(to_string(is_digit('7')))
  println(to_string(str_len("héllo 🙂")))
  println(substring("世界你好", 0, 2))
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
`str_len` 数码点，`substring` 按码点下标切片，`char_to_string` 把一个码点变成字符串。

---

至此你已见过 Dawn 的全部核心特性。更深的规范见
[spec.md](spec.md)，设计取舍见 [design.md](design.md)。
