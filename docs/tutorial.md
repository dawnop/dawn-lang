# Dawn Tutorial

*[中文](tutorial.zh-CN.md) — this file is the original; the Chinese text is a translation of it.*

> Status: **current** — the reader-facing tutorial; the examples marked `dawn run` here are really run by CI (`scripts/doc-check.py`).

A deliberately small statically typed language: it compiles to JVM bytecode, and a
native executable comes straight out of GraalVM native-image. This tutorial takes you
from the first program to calling Java.

> The `dawn` fenced blocks in this document were once extracted, compiled, run and
> checked against their `output` mechanically, by `TutorialTest` on the Kotlin side;
> that test is archived together with the Kotlin implementation at the `kotlin-final`
> tag. **The gate is back** (TEST-04 in docs/codebase-audit.md): `scripts/doc-check.py`
> is one of CI's jobs, and every block here marked ```` ```dawn run ```` is really
> compiled and really run. **Blocks not marked `run` are still maintained by hand**
> and may lag behind the language — mark your own if it matters that they are right.

---

## 1. Installing, and the first program

You need JDK 21 (native compilation additionally needs GraalVM). `bin/dawn` brings up
its own toolchain: on the first run it downloads the `dawn-selfhost.jar` of the release
pinned by `scripts/seed-release.txt` (the **seed**, checked against
`scripts/seed-checksums.txt` by SHA-256), then uses the seed to compile `selfhost/`
into the current compiler. There is no Gradle — the Kotlin implementation is archived
at the `kotlin-final` tag, and `./gradlew :compiler:fatJar` does not exist on main.

```bash
./bin/dawn --version              # the first run fetches the seed and rebuilds the toolchain
./bin/dawn run  hello.dawn        # compile and run (on the JVM)
./bin/dawn test hello.dawn        # run the test blocks in the file
./bin/dawn build hello.dawn --native -o hello   # produce a standalone binary
```

The first program. Functions are pure by default; touching IO — printing, here —
requires `!io` on the signature:

```dawn run
pub fn main() -> Unit !io =
  println("Hello, Dawn")
```
```output
Hello, Dawn
```

String interpolation is introduced by `$`: `$name` interpolates a plain variable,
`${expr}` any expression (the value interpolated has to be printable). Braces on their
own are ordinary characters — without a `$` there is no interpolation:

```dawn run
pub fn main() -> Unit !io = {
  let name = "Dawn"
  let year = 2026
  println("$name was born in $year")
}
```
```output
Dawn was born in 2026
```

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

---

## 5. Lists, tuples and destructuring

The built-in `List` has literals, `++` for concatenation, `len`, `range` and for-in.
List patterns destructure head and tail:

```dawn run
fn describe(xs: List[Int]) -> String =
  match xs {
    [] -> "empty"
    [x] -> "just $x"
    [first, ..rest] -> "$first, and ${len(rest)} more"
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
  println("$q remainder $r")
}
```
```output
3 remainder 2
```

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

## 7. Error handling: Result and `?`

Dawn has no exceptions. A recoverable error goes through `Result[T, E]`; `?` takes the
value out of an `Ok`/`Some` and returns early from an `Err`/`None`. For the
unrecoverable kind there is `panic`, which does not return and therefore needs no `!io`.

```dawn run
fn half(x: Int) -> Result[Int, String] =
  if x % 2 == 0 { Ok(x / 2) } else { Err("$x is odd") }

fn quarter(x: Int) -> Result[Int, String] = {
  let h = half(x)?
  half(h)
}

pub fn main() -> Unit !io =
  match quarter(20) {
    Ok(v) -> println("got $v")
    Err(e) -> println("error: $e")
  }
```
```output
got 5
```

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

---

## 11. Calling Java

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

The v1 boundary: an impl's subject can only be a **non-generic** named type or
`Int`/`Float`/`Bool`/`String` (there are no conditional impls, and `List[T]` cannot be a
subject); and a call under a trait constraint is not available in comptime. The full
design is in [trait.md](trait.md), in Chinese.

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

### The v1 boundary

- A **tail-resumptive** arm is one ordinary call and its return value is the result.
  An effect declared `ctl` may also carry **control arms**
  (`op(...) resume k => ...`), which bind the continuation instead of resuming: the
  arm's value becomes the value of the whole `with handle`, and `k` is an ordinary
  function value that may be stored and resumed later. Once only: resuming twice is not
  in this tier, and one that will never be resumed is abandoned with `discard`, which
  is what runs the suspended frames' releases.
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

---

That is every core feature of Dawn. The deeper reference is [spec.en.md](spec.en.md) and
the design trade-offs are in [design.en.md](design.en.md). Those two are **written in
Chinese and translated**: they are living documents, edited in Chinese by every change to
the language, so the Chinese half is the original and the English half is registered
against it. The rest of `docs/` is monolingual — its reader is the author, and prose that
has to be translated before it can be written is prose that does not get written.
