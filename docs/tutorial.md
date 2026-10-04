# Dawn Tutorial

*[中文](tutorial.zh-CN.md) — this file is the original; the Chinese text is a translation of it.*

<!--
> Status: **current** — the reader-facing tutorial; the examples marked `dawn run` here are really run by CI (`scripts/doc-check.py`).

Maintainer note, kept in a comment so the site does not show it to readers.
The `dawn` fenced blocks in this document were once extracted, compiled, run and
checked against their `output` mechanically, by `TutorialTest` on the Kotlin side;
that test is archived together with the Kotlin implementation at the `kotlin-final`
tag. **The gate is back** (TEST-04 in docs/codebase-audit.md): `scripts/doc-check.py`
is one of CI's jobs, and every block here marked ```` ```dawn run ```` is really
compiled and really run. **Blocks not marked `run` are still maintained by hand**
and may lag behind the language; mark your own if it matters that they are right.
-->

A deliberately small statically typed language, with two peer backends: it compiles to
JVM bytecode or, through C, to a native executable. This tutorial has nineteen chapters:
it takes you from the first program to effects of your own and their handlers, and then
to packages and to the targets a program compiles for.

---

## 1. Installing, and the first program

Every release on the [releases page](https://github.com/dawnop/dawn-lang/releases/latest)
publishes two toolchains, each with its SHA-256 beside it. They are different compilers,
not two downloads of one, so pick by whether you have a JVM.

**Without a JVM** (linux-x86_64): `dawnc` is one static executable with the standard
library and the C runtime inside it. It compiles through the C backend, so it refuses
`use java` (chapter 11 is the one chapter it cannot follow).

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawnc-linux-x86_64
curl -fsSLO $base/dawnc-linux-x86_64.sha256
sha256sum -c dawnc-linux-x86_64.sha256
chmod +x dawnc-linux-x86_64 && sudo mv dawnc-linux-x86_64 /usr/local/bin/dawnc
```

**With a JVM** (JDK 21 or newer, any platform): `dawn-selfhost.jar` carries the standard
library, so the jar on its own is the whole toolchain.

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawn-selfhost.jar
curl -fsSLO $base/dawn-selfhost.jar.sha256
sha256sum -c dawn-selfhost.jar.sha256      # macOS: shasum -a 256 -c
```

The commands below say `dawn`. With the static binary that is `dawnc`; with the jar it is
`java -jar dawn-selfhost.jar`.

```bash
dawn run  hello.dawn        # compile and run
dawn test hello.dawn        # run the test blocks in the file
dawn fmt  hello.dawn        # format the file in place
```

**From source**, if you have a checkout and JDK 21: `./bin/dawn` stands in for `dawn`.
Its first run downloads the seed (the `dawn-selfhost.jar` of the release pinned by
`scripts/seed-release.txt`, checked against `scripts/seed-checksums.txt`) and compiles
the compiler in `selfhost/` with it. There `./bin/dawn build hello.dawn --native -o hello`
packages the JVM build with GraalVM native-image, which is a different road from `dawnc`.

The first program. Functions are pure by default; touching IO — printing, here —
requires `!io` on the signature:

```dawn run
pub fn main() -> Unit !io =
  println("Hello, Dawn")
```
```output
Hello, Dawn
```

String interpolation is written `${expr}`, for a plain variable as much as for any
expression (the value interpolated has to be printable). Braces on their own are ordinary
characters — without a `$` there is no interpolation:

```dawn run
pub fn main() -> Unit !io = {
  let name = "Dawn"
  let year = 2026
  println("${name} was born in ${year}")
}
```
```output
Dawn was born in 2026
```

See also: [spec.en.md](spec.en.md) §12.1

---

## 2. Values, types and functions

`let` binds immutably, `var` mutably. The primitive types are `Int`, `Float`, `Bool`
and `String`. A top-level function has to write out every parameter type and its return
type — the signature is the contract.

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

The pipe `|>` puts its left-hand side into the first argument of the call on its right,
so a line reads in the direction the data flows:

```dawn run
fn double(x: Int) -> Int = x * 2
fn inc(x: Int) -> Int = x + 1

pub fn main() -> Unit !io =
  5 |> double |> inc |> to_string |> println
```
```output
11
```

### Named arguments and default values

A parameter may carry a default, written `name: Type = expr`, and a call may then leave
that argument out. Any argument may also be passed by name: the positional ones fill the
slots from the left, a named one takes the slot it names, and names may come in any
order.

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

A default is evaluated afresh on every call that leaves it out, and it has to be pure:
if it could do io, whether a call did io would depend on whether the caller passed that
argument. Arguments run in the order they are written, whichever slots they land in.
The names belong to the signature, so a function value has none: after `let g = greet`,
`g(name: "x")` is an error and `g` wants all three arguments. Constructors take names the
same way, their field names standing in for parameter names (`Rect(w: 3.0, h: 4.0)`).

See also: [spec.en.md](spec.en.md) §2.1, §3.1, §4.3, §4.4

---

## 3. match and exhaustiveness

`match` dispatches on patterns. The compiler checks **exhaustiveness**: a missing arm
is an error, and the error says which one is missing.

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

See also: [spec.en.md](spec.en.md) §5

---

## 4. Modeling data: ADTs and records

An algebraic data type (ADT) lists its constructors with `|`. Add `derive Show` to make
it printable:

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

A record is a product type with named fields, constructed and updated with braces:

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

What `type` declares is always a new type; to give an existing one an **alias**, use
`alias` — the two spellings are interchangeable, and it is mostly used to give a tuple
or a function type a name you can say out loud:

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

See also: [spec.en.md](spec.en.md) §2.3, §2.4, §2.6

---

## 5. Lists, tuples and destructuring

The built-in `List` has literals, `++` for concatenation, `len`, `range` and for-in.
List patterns destructure head and tail:

```dawn run
fn describe(xs: List[Int]) -> String =
  match xs {
    [] -> "empty"
    [x] -> "just ${x}"
    [first, ..rest] -> "${first}, and ${len(rest)} more"
  }

pub fn main() -> Unit !io = {
  println(describe([]))
  println(describe([9]))
  println(describe([1, 2, 3]))
}
```
```output
empty
just 9
1, and 2 more
```

A tuple packs a fixed number of values of different types; `let` destructures one
directly:

```dawn run
fn divmod(a: Int, b: Int) -> (Int, Int) = (a / b, a % b)

pub fn main() -> Unit !io = {
  let (q, r) = divmod(17, 5)
  println("${q} remainder ${r}")
}
```
```output
3 remainder 2
```

See also: [spec.en.md](spec.en.md) §2.2, §4.11, §5.1

---

## 6. Loops: while, for, break and continue

Besides recursion and `map`/`fold`, Dawn has ordinary loops as well: `while` on a
condition, `for x in list`, and `for i in a..b` (a included, b excluded). `break` leaves
the **innermost** loop early and `continue` goes to the next round; both are expressions
of type `Never`, and neither can cross a lambda boundary.

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

See also: [spec.en.md](spec.en.md) §4.7

---

## 7. Error handling: Result and `?`

Dawn has no exceptions. A recoverable error goes through `Result[T, E]`; `?` takes the
value out of an `Ok`/`Some` and returns early from an `Err`/`None`. For the
unrecoverable kind there is `panic`, which does not return and therefore needs no `!io`.

```dawn run
fn half(x: Int) -> Result[Int, String] =
  if x % 2 == 0 { Ok(x / 2) } else { Err("${x} is odd") }

fn quarter(x: Int) -> Result[Int, String] = {
  let h = half(x)?
  half(h)
}

pub fn main() -> Unit !io =
  match quarter(20) {
    Ok(v) -> println("got ${v}")
    Err(e) -> println("error: ${e}")
  }
```
```output
got 5
```

See also: [spec.en.md](spec.en.md) §8

---

## 8. Lambdas and the effect system

An anonymous function is written `(params) => expr` — a single un-annotated parameter
may drop the parentheses and be written `x => expr`, and a parameter annotation may be
left out wherever the type can be inferred. A function type is written
`fn(A) -> B !e`, where `!e` is its effect. A pure function's signature is enough to know
it has no side effects, and a test for one needs no mocks.

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

A higher-order function forwards its arguments' effects through an **effect variable**:
the effect of `map(f)` is the effect of `f`. The union of two function parameters'
effects is written `!(e1 | e2)` — pure ∘ pure is still pure, and anything that touches
io is io.

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

### A block as the last argument

When a call's last argument is a function, it can follow the call as a bare block on the
same line: `f(a) { e }` is `f(a, () => e)`. A block that takes parameters names them
before a `=>`, as a lambda does, one bare name or a parenthesised list:

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

The block fills the **last** parameter whatever came before it, which is why
`fold(xs, 0) { ... }` reads as "fold from 0, with this". It has to open on the same line
as the call; a `{` on the next line is a block statement of its own. In an `if`, `while`
or `for` header, and after `match`, the braces are the body and not an argument, so
parenthesise the call there: `if (f(x) { ... }) { ... }`. With named arguments and
defaults, it is how a function with many options and a body reads at the call site:
`column(gap: 12) { ... }`.

See also: [spec.en.md](spec.en.md) §4.3, §4.5, §6

---

## 9. Strings and the standard library

The standard library comes in two layers. A few high-frequency names (`println`,
`map`/`filter`/`fold`, `len`, `to_string`, …) live in the **prelude** and are available
everywhere; everything else lives in a **module**, brought in with `use std/x` and
called qualified as `x.fn(...)` — strings are in `std/str`, and there are also
`std/list`, `std/map`, `std/set`, `std/bytes`, `std/io` and `std/cursor`. A hot name can
be imported selectively (`use std/str.{trim}`).

String functions work in code points. `str.split` separates on a **literal**, not a
regex; `join` is its inverse:

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

There are three ways to write a string, and their blind spots complement each other.
Double quotes `"..."` support escapes and `$` interpolation; triple quotes `"""` span
lines, strip the common indent and need no escaping for quotes (interpolation still
applies); and **backticks `` `...` `` are a raw string** — no escapes, no interpolation,
may span lines, so a regex, a code sample or a fragment of HTML is worth exactly what it
looks like (the one restriction: the content may not contain a backtick):

```dawn run
pub fn main() -> Unit !io = {
  println(`"quotes" and $dollar and \n stay literal`)
}
```
```output
"quotes" and $dollar and \n stay literal
```

`parse_int` turns a string into an `Option[Int]` — failure is `None`, not an exception:

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

See also: [spec.en.md](spec.en.md) §1.6, §10.6, §11

---

## 10. comptime and const

`comptime { ... }` is executed at compile time by the interpreter and its result is
burned into the constant pool — there are no macros. A top-level `const` is named in
upper case, and its initializer is implicitly comptime:

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

See also: [spec.en.md](spec.en.md) §7

---

## 11. Calling Java

*JVM toolchain only.* This chapter needs `dawn-selfhost.jar` or a checkout's `./bin/dawn`.
The static `dawnc` compiles through C and refuses `use java`, so with it, skip to
chapter 12.

`use java "..."` calls a Java class directly. Every Java call counts as `!io`, and a
reference return type is wrapped in `Option[T]` automatically — null does not get into
Dawn. Construct with `.new`, and call static methods on the class name.

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

See also: [spec.en.md](spec.en.md) §9

---

## 12. test blocks and dawn fmt

`test "name" { ... }` holds assertions written with `assert`; `dawn test` runs them, and
`dawn build` strips them out. A test for a pure function needs no mocks at all:

```dawn run
fn add(a: Int, b: Int) -> Int = a + b

test "addition commutes" {
  assert add(2, 3) == add(3, 2)
  assert add(0, 5) == 5
}

pub fn main() -> Unit !io = println("ok")
```
```output
ok
```

And finally: `dawn fmt` settles the code style (2-space indent, regular spacing), and
`dawn fmt --check` is the form CI wants. Get into the habit of running `dawn fmt` before
you commit, and code review never has to argue about whitespace again.

See also: [spec.en.md](spec.en.md) §3.4, §1.8

---

## 13. Modules and projects

More than one file is a project. The directory convention: modules live under `src/`,
and the entry point is `src/main.dawn`. One `.dawn` file is one module, and the module
path is its path relative to `src/`.

```
myapp/
└── src/
    ├── main.dawn
    └── util/
        └── math.dawn      # module util/math
```

Everything is module-private by default; `pub` exports. There are two forms of import:
`use util/math` brings in the whole module (accessed qualified, `math.double(x)`, the
alias being the last segment of the path), or `use util/math.{double}` imports
selectively (used directly, as `double`). Types, constructors and constants can only
cross a module boundary through a selective import.

`src/util/math.dawn`:

<!-- doc-check: skip-check the imported half of a two-file project: no main, so a single file is not a program -->
```dawn skip-check
pub fn double(x: Int) -> Int = x * 2

pub type Shape =
  | Circle(r: Float)
  | Square(side: Float)
  derive Show
```

`src/main.dawn`:

<!-- doc-check: skip-check the entry half of the same project: use util/math needs the file above to be present too -->
```dawn skip-check
use util/math
use util/math.{Shape, Circle, Square}

pub fn main() -> Unit !io = {
  println(to_string(math.double(21)))
  println(to_string(Circle(2.0)))
}
```

`dawn run myapp`, given a directory, compiles and runs the whole project; `dawn test
myapp` runs the test blocks of every module, and `dawn build myapp` packs it into one
jar. Single-file `dawn run foo.dawn` still works. A `use` cycle is a compile error, and
so is a name that collides with an imported module's alias — the two share one
namespace.

See also: [spec.en.md](spec.en.md) §10.1, §10.2, §10.3

---

## 14. Map and Set

`Map[K, V]` and `Set[T]` are built-in **persistent** containers: every "modification"
returns a new container and leaves the original alone. There is no literal syntax; the
operations live in the `std/map` and `std/set` modules. Iteration order = insertion
order, on the JVM and on native alike.

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

A key may be of any type with structural equality (`Int`/`String`/tuples/ADTs/records).
`map.get` returns an `Option[V]` — a miss is `None`, not an exception. Equality ignores
order: two `Map`s with the same keys and values are equal.

See also: [spec.en.md](spec.en.md) §2.2, §11

---

## 15. Characters and code points

The character literal `'a'` has type `Char`: one Unicode scalar value, represented as
its code point. It is an opaque type over `Int` (§2.7), so `==`, `<`, hashing and a
literal pattern in a `match` are all `Int`'s — but it is not an `Int`, `'a' + 1` does
not typecheck, and converting between the two goes through `std/char`: `char.code(c)`
gives the code point, `char.of(n)` builds a character from one (`None` if it is not a
scalar value).

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

`code_points`/`from_code_points` go back and forth between a string and a `List[Char]`
(supplementary-plane emoji included), `str.len` counts code points, `str.slice` slices
by code-point index, `str.at` takes one `Char`, and `str.from_char` turns one `Char`
into a string. `"${c}"` is that same one-character string: `std/char` writes an
`impl Display[Char]`, and `Display` is the top-level rendering. `Show`, the nested one,
is still the target type's, so a `Char` inside a list prints as its code-point number.

A function that indexes **by code point** counts from the front of the string every time
(O(n) once, O(n²) inside a loop). To scan a string, use `std/cursor`: a **cursor** is an
opaque position with a constant cost per step; arithmetic on one is a compile error,
while comparing two (`==`, `<`) is allowed.

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

One step is one character: an emoji's surrogate pair is never split down the middle.
`cursor.char` answers an `Int` rather than a `Char`, because at the end it has to answer
`-1` — a sentinel that is not a character has no home in a type where every value is one
(spec §4.8). `cursor.find(s, sub, from)` returns an `Option[Cursor]`, and
`cursor.skip(s, c, sub)` steps over a literal already known to occur there.

See also: [spec.en.md](spec.en.md) §1.5, §2.7, §11

---

## 16. trait: constrained generics and operator overloading

Up to here a generic function has known nothing about `T` — it cannot compare it, print
it or call a method on it. A **trait** attaches a capability constraint to a type
parameter. Declare a trait, write an `impl` for a concrete type, then constrain the
generic with `[T: Trait]`:

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
  # a trait method is an ordinary function name, so a UFCS dot call works too
  println(to_string(rooms[0].bigger_than(10.0)))
}
```
```output
16.0
true
```

The rules are few: a trait has exactly one type parameter; each "trait × type" pair
admits **exactly one impl** in the whole program; and an impl has to be written in the
module of either the trait or the subject type (the orphan rule). A method with a
default body (`bigger_than` above) may be left out of an impl, and writing it is an
override.

### Sorting: `Ord` and the comparison operators

The built-in trait `Ord[T]` — one method, `cmp(a: T, b: T) -> Int`, negative/zero/
positive for less/equal/greater — is what bridges `< <= > >=`. `Int`/`Float`/`String`
are ordered from the start; give a type of your own an `Ord` impl (or just `derive Ord`)
and it can use the comparison operators, be passed where `[T: Ord]` is asked for, and be
fed to the sorting functions:

```dawn run
type Card = { rank: Int, name: String } derive Show, Ord

fn max2[T: Ord](a: T, b: T) -> T = if a < b { b } else { a }

pub fn main() -> Unit !io = {
  let hand = [Card { rank: 3, name: "queen" }, Card { rank: 1, name: "pawn" }]
  # derive Ord compares field by field in declaration order (a sum type compares constructors first)
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

The list functions that go with it are stable sorts that keep the first of a tie:
`sort`/`max`/`min` want `Ord` on the element, `sort_by(xs, cmp)` takes a comparison
function of your own, and `max_by`/`min_by(xs, key)` take the extreme by a key (whose
type needs `Ord`).

A trait method, or any function with a bound, can be passed around as a bare function
value. What it needs is an expected function type, because that is what says which type
the bound is discharged at; the wrapper is then written for you, dictionary and all:

```dawn run
fn shout[T: Show](xs: List[T]) -> List[String] = map(xs, to_string)

pub fn main() -> Unit !io = {
  println(join(shout([1, 2, 3]), " "))
  # the bound here is `shout`'s own, so the wrapper closes over the dictionary
  # `shout` was handed, which is what `x => to_string(x)` would have done
  println(join(shout(["a", "b"]), " "))
}
```
```output
1 2 3
"a" "b"
```

Without one, as in `let f = to_string`, there is nothing to discharge the bound at and
the compiler says so; write the type, or write the lambda with an annotated parameter.

### One list, many types: a record of functions

A `List[T]` holds one `T`. When you want a list of *different* types that all support
the same operation, Dawn has no `dyn Trait` to reach for. Capture the operation in a
record of functions, hide the record behind an `opaque` type, and give that type an impl
of its own. The bound is discharged where the value is packed, which is the last place
the concrete type is still known:

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

The second line keeps its quotes. That is what `Show[String]` renders, here and
everywhere else, and not a slip in the example.

The trick is complete for a trait that takes its subject in one position: `Show`,
`Hash`, anything shaped `fn(T) -> ...`. It does not reach `Eq` or `Ord`, whose
`eq(a: T, b: T)` and `cmp(a: T, b: T)` need two values of the *same* type, and packing
is exactly what throws that fact away. So a heterogeneous `List` is available and a
heterogeneous `Map` key is not. Why the line falls there, and why Dawn does not add
trait objects, is in [trait.md](trait.md) §10, in Chinese.

An impl's subject may be generic: `impl[T: Eq] Eq[List[T]]` is a **conditional impl**,
and `derive` on a generic type writes one (`type Box[T] = { v: T } derive Ord` gives
`impl[T: Ord] Ord[Box[T]]`). The v1 boundary: the subject's arguments must be the impl's
own, distinct type parameters (`impl Eq[List[Int]]` is rejected); and a call under a
trait constraint is not available in comptime. The full design is in
[trait.md](trait.md), in Chinese.

### Associated types, and the traits behind `[]` and `for`

A trait can declare a type of its own that each impl fills in: `type Item` in the trait,
`type Item = String` in the impl. A signature reaches it through the type parameter, as
`C.Item`, so a generic function can talk about "whatever this container holds" without
being told what that is:

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

# a generic consumer: whatever the store's key and item are, it uses them as they are
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

`fetch_or` is checked once, against the trait, and at each call `C.Item` becomes the
impl's binding, so `fetch_or(s, 1, "nothing")` takes and returns a `String`. An impl
binds each associated type exactly once; leaving one out, or binding a name the trait
does not declare, is an error.

Two of the built-in traits are written this way, and they are the ones the language's
own syntax goes through. `Index[C]` has `type Idx`, `type Item` and one method, `index`,
and it is what `c[i]` calls: `List` (indexed by `Int`) and `Map` (by its key) come with
impls, and one impl gives a type of your own `[]`. `Iter[C]` has `type Cur`, `type Item`
and four cursor methods, and it is what `for x in c` walks:

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

Both traits are in the prelude, so neither impl needs a `use`. `[]` is read-only (there
is no `c[i] = v`), and a type has exactly one index type. `index` itself cannot be
called by name, because `[]` is its spelling; the four `Iter` methods can.

See also: [spec.en.md](spec.en.md) §3.5, §4.8

## 17. Effects of your own: `effect` and `with handle`

`!io` is the one effect the compiler knows about. You can declare your own: a set of
**operations** whose implementation the caller picks at the point of use.

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

Three things are happening there:

- `effect Ask { ... }` declares the effect and its operations. An operation is a function
  signature with **no body** — the body comes from the handler.
- `sum_three` calls `ask()` directly and writes `!Ask` into its signature. Leaving it out
  is an error, and the error names the two ways out.
- `with handle Ask { ask() => 42 }` installs the handler: **the whole of the block after
  that line** is inside its scope. The arm `ask() => 42` is a closure, calling `ask()`
  calls it, and its return value is the value of `ask()`.
- That rest of the block is itself a closure, so it captures by value: a `var` declared
  **before** the `with handle` can be neither read nor assigned after it, while a `var`
  declared **after** it is fine. The diagnostic says so and suggests the two ways out,
  binding a `let` snapshot before the `with handle` or passing the value in as a parameter.

### More than one operation, and operations with parameters

An effect may have several operations, and a handler has to answer **every one of them**
— no more and no fewer:

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

An arm's body may do anything, io included. That counts against **the block that
installed the handler** — which is why `main` above is `!io` — and not against `work`,
which emitted the operation: `work` owes only `!Log`.

### Who answers: the nearest one lexically

A handler is found by **where it is written**, not by the runtime stack. An inner one
shadows an outer one:

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

An arm that emits **its own effect** again finds the **outer** handler — a handler does
not answer itself — so `with handle Ask { ask() => ask() * 10 }` means "take the answer
from outside and multiply it by ten", not an infinite loop.

A closure does **not** keep the handler it was written under. Carry it out of the block
and it carries the label with it: its row still says `!Ask`, and the handler that answers
is the one in scope **where the closure is finally called**. The type says who has to
supply a handler, not what any particular arm would have done, so a handler with pure arms
leaves you an `!Ask` closure just as an io one does.

A function type may therefore name an effect, and it means exactly what it reads as.
`fn(f: fn() -> Int !Ask)` says "whoever calls `f` supplies the `Ask` handler", which is
how the call really works. `fn(f: fn() -> Int !e)` is the other spelling rather than a
workaround: an effect variable takes a closure with any row at all and forwards that row
into your own.

### Higher-order functions need no change

An effect variable (`!e`) forwards a named effect along with everything else, so `map`,
`fold` and `for` loops carry on as before:

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

### Handler state: a `var` in the arm table

An arm table may open with `var` declarations. Each one is a **cell**: mutable state that
belongs to this one installation of the handler. The arms read and write it, and the block
after the `with handle` reads it afterwards, which is how a handler that accumulates
something hands what it accumulated back to the code that installed it.

```dawn run
effect Spend {
  fn spend(item: String, n: Int) -> Bool
}

## No budget parameter, no running total: `shop` only knows that it asks.
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

`shop` has no budget parameter, no accumulator and no return value carrying one. The
budget is the handler's, the two cells are where it is kept, and the last line of `main`
is the block after the `with handle` reading them. There is no return arm; the cells are
the only surface a stateful handler hands anything back through.

Cells must be declared **before** the arms, and their type annotation is not optional:
inside the arm table there is no context to infer it from.

Two rules keep a cell apart from an ordinary `var`:

- An arm is a closure, so it cannot write to an enclosing `var` (that is the rule from the
  start of this section). Its own cells are the exception: they are this installation's
  state rather than a binding captured from outside it.
- A cell cannot leave. A lambda written **inside** an arm may not capture one, and a cell
  has no type a program can write down, so no second name reaches it.

Each installation gets its own cells. A nested `with handle` for the same effect keeps a
separate set, and what the inner one accumulates does not reach the outer one.

### The standard library's effects, and a file system that is a table

`std/io` declares effects of the kind this chapter has been writing for the parts of the
outside world a program usually just calls: `Fs` (files), `Env` (the working directory
and environment variables), `Proc` (running another program), `Exit` (ending the process)
and `Console` (writing to stdout and stderr). `io.read_file` and the rest of the file
functions are `!Fs`, `io.getenv` and `io.cwd` are `!Env`, `io.run` is `!Proc`. So a
signature says which part of the world a function touches, and a test can answer that
effect with a fake.

std ships one fake ready-made: `std/memfs` answers `Fs` from a table in memory.
`memfs.with_fs(tree, body)` runs `body` against `tree` and hands back the result together
with the tree as `body` left it. `Env` has two operations, and a fake for it is a
`with handle` of two lines:

```dawn run
use std/io
use std/io.{Fs, Env}
use std/memfs
use std/str

# The signature says it all: this touches files and nothing else.
fn archive(path: String) -> Result[Int, ForeignError] !Fs = {
  let text = io.read_file(path)?
  io.write_file(path ++ ".bak", text)?
  Ok(len(str.split(text, "\n")))
}

# And this reads the environment, and nothing else.
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

`archive` read one file and wrote another, and nothing touched a disk. `memfs.with_fs` is
pure, so the same lines work in a `test` block with no temporary directory to make or
clean up. A program meets the real world by installing the production handlers once, at
the top: `io.with_fs_real(() => ...)`, and likewise `with_env_real`, `with_proc_real`,
`with_exit_real` and `with_console_real`, each of them `!io`. (`println` itself is still
plain `!io`; `Console` is there for code whose output a test wants to read back.)

### Control arms: `ctl`, `resume k` and `discard`

Every arm so far answers its operation and lets the caller carry on. An effect declared
`ctl` may also have **control arms**, which take hold of the rest of the computation
instead: `op(args) resume k => ...` binds `k`, a function that resumes the code after the
operation with the value you pass it. The arm's value is the value of the whole
`with handle` block, so an arm that does not call `k` ends the block early, with an
answer of its own.

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

For `admit(-1)`, `validate` asks `check(false, "negative")`, and the arm does not resume:
the second `check` and the `"age ..."` line never run, and `"rejected: negative"` is the
answer of `admit`'s whole block. For `admit(30)` the arm calls `k(())` at each check, and
what the rest of the block finally produces comes back out of `k` as the arm's value.

A continuation is one-shot: resuming it twice is a panic. One you will never resume is
abandoned with `discard(k)`, and that is what runs the cleanups between the operation and
the handler; here it is the `bracket` that prints `closed log`, which ran on all three
paths. Just dropping `k` runs nothing, on purpose: a cleanup that ran whenever a
collector got round to it would behave differently on the two backends. `k` is an
ordinary function value, so it may also be stored and resumed later. `std/io`'s `Exit`
is a `ctl` effect for the reason this section starts from: a test answers `io.exit(1)`
with an arm that does not resume and hands the status back as a value, where the
production arm ends the process.

### The v1 boundary

- For "the operation does not come back to the call site" the failure machinery is
  usually the answer: `Result` + `?`, `catch_fault`/`catch_panic`/`bracket`.
- An effect takes no type parameters (there is no `effect Yield[T]`).
- comptime and const initialisers raise no named effect and cannot install a handler.
  Trait and impl methods do take labels, and so does any written function type (an `alias`
  target, a record field, a parameter); what an impl still owes is a row whose labels match
  the trait's exactly, because each label is one of the method's hidden parameters.
- A labelled function can be passed as a function value: the label goes into the value's
  type, and the call site supplies the handler. Only an **operation** cannot, since there
  is no function symbol behind it; wrap it in a lambda (`() => ask()`).
- An arm is a closure, so it cannot write to an enclosing `var` and cannot `return` or
  `break` its way out. Its own cells are the exception, and they are the section above.

The full rules are in [spec.en.md](spec.en.md) §6.5 and the design trade-offs in
[effects-design.md](effects-design.md).

See also: [spec.en.md](spec.en.md) §6.5, §11

---

## 18. Packages and projects

Chapter 13's project needed nothing but a directory. Once it depends on code that lives
somewhere else, it gets a `dawn.toml`: an optional manifest for what the directory
convention cannot say, which is the project's identity and its dependencies. The layout,
the entry point and the module paths stay the directory's business, and a project
without one works exactly as before.

```toml
schema = 1        # always the first key
name = "myapp"    # the project's identity, [a-z_][a-z0-9_]*
```

### A dependency is a source package

A package is a project of its own, with its own `dawn.toml` and its own `src/`. Here is a
small one, `greet`, sitting next to `myapp`:

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

`greet/src/style.dawn`:

<!-- doc-check: skip-check one module of a package: it has no main, and its pub(pkg) only means something inside the package around it -->
```dawn skip-check
# visible to every module of the greet package, and to nothing outside it
pub(pkg) fn shout(s: String) -> String = s ++ "!"
```

`greet/src/hello.dawn`:

<!-- doc-check: skip-check the package's public module: its use style needs the file above, and a package has no main -->
```dawn skip-check
use style.{shout}

pub fn hello(name: String) -> String = shout("hello, ${name}")
```

Inside the package, modules import each other by their path under the package's own
`src/`, as chapter 13's did. `dawn add` writes the dependency into `myapp`'s manifest:

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

The key under `[deps]` is how `myapp` spells the package: it is the first segment of a
`use` line.

`myapp/src/main.dawn`:

<!-- doc-check: skip-check the consuming half of a two-project example: use greet/hello resolves only through myapp's dawn.toml -->
```dawn skip-check
use greet/hello.{hello}

pub fn main() -> Unit !io = println(hello("Dawn"))
```

`dawn run myapp` prints `hello, Dawn!`.

### `pub(pkg)`: shared inside a package, hidden outside it

Between module-private (nothing written) and `pub` there is a third level. A `pub(pkg)`
declaration is visible to every module of its own package, the unit one `dawn.toml`
describes, and to nothing outside it. `shout` is a helper the modules of `greet` share,
and `myapp` cannot reach it:

```text
$ dawn run myapp      # main.dawn now also says: use greet/style.{shout}
error: `shout` is package-private to package `greet`
  --> myapp/src/main.dawn:2:18
  |
2 | use greet/style.{shout}
  |                  ^^^^^
  = hint: only modules of package `greet` may name it
```

A `pub` declaration's signature may not mention a `pub(pkg)` type, by the same rule that
keeps a module-private type out of a public signature, and `dawn doc` lists `pub` items
only. A project with no `dawn.toml` is one package, and so is the bundled standard
library as a whole.

### Remote packages, versions and MVS

A path is for code that sits next to yours. A published package is an archive at a URL,
pinned by the hash of what it unpacks to:

```toml
[deps.json]
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.7.0.zip"
version = "1.0.0"
hash = "d1:<sha256>"          # content hash of the unpacked file tree
subdir = "packages/json"      # where the package sits inside the archive
```

Nobody computes that hash by hand. `dawn add <url>` fetches the archive, hashes it, reads
the package's own manifest for its name and version, and writes the entry, leaving the
comments and layout of the rest of the file as they were; `--subdir` says where the
package sits in the archive and `--as` picks a different key. Adding the same package
again updates its entry in place, which is how a version is bumped.

When two packages in one program depend on the same third one at different versions, the
program gets **one** copy of it: the highest of the minimum versions asked for. This is
minimal version selection (MVS), the algorithm Go uses, and a requirement is only ever a
minimum: no upper bounds, no exclusions. For Dawn the single copy is not a convenience.
Every trait-and-type pair has exactly one impl in a whole program (chapter 16), and two
copies of a package would be two copies of each of its types, with two impls each. A
package's identity is the `name` in its own manifest rather than the key you gave it,
so a major version that renames the package (`json2`) can still be spelled
`use json/...` by keeping the old key.

The third table, `[java-deps]`, lists Maven coordinates for chapter 11's `use java`
(`sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"`, an exact version and nothing else). The
JVM toolchain resolves and fetches them; `dawnc` refuses `use java` and so has no use for
them. The design and its reasons are in [package-design.md](package-design.md) and
[package-visibility-design.md](package-visibility-design.md), in Chinese.

See also: [spec.en.md](spec.en.md) §10.1, §10.4

---

## 19. Backends and targets

One source compiles two ways, and chapter 1 has already met both drivers. `dawn` is the
JVM backend: `dawn run` compiles to bytecode and starts a JVM, `dawn build app -o app.jar`
writes an executable jar, and it is the only one that can follow chapter 11 into
`use java`. `dawnc` is the C backend: it emits C and hands it to `cc`, so
`dawnc build app -o app` is a native executable with no JVM anywhere, and `dawnc run`
builds one and runs it at once. `check`, `test`, `fmt`, `doc`, `add` and `lsp` exist on
both.

Two of these are called native, and they are different roads:

| Command | What you get | `use java` |
|---|---|---|
| `dawn build app -o app.jar` | JVM bytecode in a jar | yes |
| `dawn build app --native -o app` | that jar, compiled ahead of time by GraalVM `native-image` | yes |
| `dawnc build app -o app` | C compiled by `cc`, with no JVM at all | no |

A program that does not call Java prints the same bytes under both. That is checked
rather than hoped for: the repository runs its corpora through both backends and compares
the output byte for byte, and the C backend compiles the compiler itself.

### WebAssembly, and reactors

`dawnc` has one more target. `dawnc build --target wasm app -o app.wasm` compiles the
same C for `wasm32-wasip1` with clang (one with a WASI sysroot; `DAWN_WASM_CC` names
another, such as wasi-sdk's). The result is an ordinary WASI command module: a runtime
calls its `_start` once and the program runs to the end.

A page in a browser wants the other shape, a module that stays alive and is called once
per event, and `--reactor` builds that. The module has no `_start`; it exports exactly
three things: `memory`, `_initialize` and `dawn_turn`. The host calls `_initialize` once,
after instantiating the module and before anything else, then calls `dawn_turn` with each
message, and each call runs `main` once ([spec.en.md](spec.en.md) §12.5). `std/reactor`'s `serve` is what carries state from one turn to the next: it reads a
line, hands it to your step function together with the state so far, and keeps the state
the step returns. The site's [Demo](https://dawn-lang.dawnop.com/tea.html) page is three
of these (a counter, a to-do list and the site search), each built with
`dawnc build --target wasm --reactor` and driven from JavaScript by `packages/tea-dom`.
The wasm side only ever reads and writes messages, never a DOM node, and the same
program answers a shell: `echo '{"op":"init"}' | dawn run examples/projects/tea_dom_counter`.
The design is in [dom-bridge-design.md](dom-bridge-design.md), in Chinese.

### GPUs: a device is an effect

`std/gpu` gives the host side of a GPU program the shape chapter 17 has been building: a
`Gpu` effect whose operations allocate a buffer, upload to it, launch a kernel by name,
wait, and download. A function that drives a device says `!Gpu`, and which device answers
is up to whoever installs the handler. `with_gpu_fake` answers from a table in host
memory, where launching a kernel calls the host reference function registered under its
name. It is pure, so this runs anywhere, with no GPU, no driver and no `!io`:

```dawn run
use std/gpu.{Gpu, F64, alloc, upload, download, launch, sync, free, handle_of, with_gpu_fake,
  reference_kernels}

# The host half of a GPU program: allocate, upload, launch, wait, read back.
# Its only effect is `!Gpu`; which device answers is the caller's choice.
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
  # the fake device: a table in host memory, so this runs anywhere, and purely
  let sum = with_gpu_fake(reference_kernels(), () => vector_add([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]))
  println("${sum}")
  # a kernel the device does not know is refused, not guessed at
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

`reference_kernels()` is the fake device's built-in table (`vadd`, `vadd_bf16` and
`sum`). The same `vector_add`, unchanged, runs on a real card under
`with_gpu_real(kernels, body)`, which answers the same operations from the CUDA driver,
and whose `kernels` maps each name to its compiled module. That handler needs the C
backend (on the JVM every operation answers `gpu.unsupported_backend`) and a machine with
an NVIDIA driver.

The kernels are Dawn as well, written against `packages/tileir`: its `Dev` effect records
the operations a kernel performs, and the record is encoded as NVIDIA's Tile IR bytecode,
which `tileiras` assembles into the module `with_gpu_real` loads. Recording is pure as
well, so you can watch it here. This example needs `packages/tileir`, so it is a project
with `tileir` under its `[deps]` (chapter 18) rather than one file, and it has no
Playground link, because the Playground runs one file:

```dawn run deps=tileir
use std/gpu.{F64}
use std/str
use tileir/dev.{Dev, Param, load_cell, store_cell}
use tileir/prog.{trace2, cells, In, Out}
use tileir/render.{render}

# One tile block reads its cell of `x` and writes it to its cell of `out`.
# Nothing is copied here: the body runs once, under a handler that records it.
fn copy(x: Param[F64], out: Param[F64]) -> Unit !Dev = store_cell(out, load_cell(x))

# The operation a line of Tile IR performs: the word after `=`, if it has one.
fn op_of(line: String) -> Option[String] = match str.split_once(line, " = ") {
  Some((_results, rest)) -> Some(str.split(rest, " ")[0])
  None -> None
}

pub fn main() -> Unit !io = {
  let g = cells([256], [128])     # 256 elements in cells of 128: two tile blocks
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

`copy` never saw a number. `trace2` ran its body once under a handler that wrote each
`Dev` operation down, and `render` prints that record as Tile IR text, one operation per
line; the program above keeps only each line's operation. The `In` and `Out` markers say
how the two parameters are cut, so the kernel body says nothing about shape: each tile
block finds its cell (`get_tile_block_id`), loads it and stores it.

`examples/projects/gpu_fake` is a whole program of nine such kernels with their host
side, answered on the fake device by the references in `packages/tileref`. The design,
and how far the device side reaches today, is in
[tile-backend-design.md](tile-backend-design.md), in Chinese.

See also: [spec.en.md](spec.en.md) §12.1, §12.3

---

That is every core feature of Dawn. The deeper reference is [spec.en.md](spec.en.md) and
the design trade-offs are in [design.en.md](design.en.md). Those two are **written in
Chinese and translated**: they are living documents, edited in Chinese by every change to
the language, so the Chinese half is the original and the English half is registered
against it. The rest of `docs/` is monolingual — its reader is the author, and prose that
has to be translated before it can be written is prose that does not get written.
