<!-- doc-check: translation-of docs/spec.md @ 3fc5e1fbe1d99cd6 -->

# Dawn Language Specification

*[中文](spec.md) — the Chinese text is the original; this is its translation, and `scripts/doc-check.py` watches the two for drift.*

> Status: **normative**. Applies to version: 0.60.0 (the `VERSION` in `selfhost/src/version.dawn`).<!-- doc-check: version -->
> When the implementation conflicts with this document, this document wins and the implementation
> is a bug — unless some clause here is explicitly marked "superseded by X".
>
> The title read "v0.1 draft" for a long time; by the day that was changed the toolchain had
> already reached 0.11. A document that calls itself a draft cannot act as a judge, and this is
> the only document in the repository qualified to judge disputes about semantics. The version
> number follows `VERSION`; it is no longer numbered separately.

This document is the authoritative definition of the syntax and semantics. For design motivation
see [design.en.md](design.en.md). [grammar.ebnf](grammar.ebnf) is a **historical** machine-readable
grammar and has **fallen behind the parser** (its own header lists the known mismatches) — read it
as a reference, not as a judge. When the grammar is in dispute, this document and
`selfhost/src/front/parser.dawn` win; the executable expectations live in `scripts/grammar-corpus/`.

Wording of this specification: **must** (violating it is a compile error), **guaranteed**
(behaviour the implementation promises), **undefined** (not promised in v0.1; do not rely on it).

---

## 1. Source files and lexical structure

### 1.1 Source files

- UTF-8 encoded, extension `.dawn`.
- One file is one module (see §11).

### 1.2 Comments

```dawn
# Line comment, to end of line
## Doc comment, attached to the declaration that immediately follows (extracted by the toolchain)
```

### 1.3 Identifiers and naming conventions

**The enforced part** — the first character decides the syntactic category, and the parser uses it
to disambiguate (in pattern matching `x` is a binding and `X` is a constructor; `TYPEIDENT` is a
separate token):

- Values, functions, module names: **the first character is a lowercase letter or `_`**
- Types and constructors: **the first character is an uppercase letter**
- Effect variables: `!` followed by a value identifier (`io` is a reserved effect name)

**Style conventions** — not enforced by the toolchain, but followed throughout the repository:
values use `lower_snake_case` (`[a-z][a-z0-9_]*`), types use `UpperCamelCase`
(`[A-Z][A-Za-z0-9]*`).

> **On non-ASCII**: "uppercase / lowercase" is decided by Java's `Character.isUpperCase`, and
> subsequent characters by `Character.isLetterOrDigit` or `_`. So `fn 中文()` and `fn _hidden()`
> both compile — a Han character is neither uppercase nor lowercase, so it takes the "not
> uppercase" branch, i.e. it is a value identifier.
>
> This is **implementation-defined**, not designed: Unicode's XID_Start/XID_Continue,
> normalization (whether the two spellings of `é` count as the same name), and homoglyphs are
> **all undefined** by this specification, and code that depends on them is not portable. Scripts
> without case (Han, Arabic, kana) can therefore only be value names; there is no natural way to
> write them as type names. Converging on a well-defined Unicode identifier syntax is open work
> (SYN-01 in docs/codebase-audit.md).

### 1.4 Keywords

```
fn let var type alias const use java pub
match if else for in while with
return break continue
comptime unsafe_pure test assert
trait impl effect
true false not
```

Keywords cannot be used as identifiers. `panic` and `todo` are built-in functions, not keywords.
There are three further **contextual keywords**, which remain ordinary identifiers elsewhere:
`derive` (only at the tail of a `type` declaration), `as` (only in the renaming position of `use`,
§10.2), and `handle` (after `with`, when the next token is not `<-`, §6.5).

**Symbol tokens take the longest match** (as with `>>>`/`>=`/`->`/`|>`). The binding arrow `<-` of
the `with` statement (§4.10) follows the same rule: `a<-b` reads as `a <- b`, not `a < (-b)`. The
spaced `a < -b` is unaffected, and `dawn fmt` puts a space on both sides of every binary operator
(§1.8), so formatted source never reaches the second reading.

### 1.5 Literals

| Form | Type | Notes |
|------|------|------|
| `42`, `1_000_000`, `0xFF`, `0b1010` | `Int` | 64-bit signed; underscores may be used as separators |
| `3.14`, `1.0e-9` | `Float` | IEEE 754 double |
| `true` / `false` | `Bool` | |
| `"hello"` | `String` | see §1.6 |
| `()` | `Unit` | the only value |
| `[1, 2, 3]` | `List[Int]` | trailing comma allowed |
| `(1, "a")` | `(Int, String)` | tuple, 2 to 8 elements |
| `'a'`, `'\n'`, `'世'`, `'\u{1F600}'` | `Char` | character literal (see below) |

**A character is its own type, `Char`**: one Unicode scalar value (`0..0x10FFFF`, excluding the
surrogate range `D800..DFFF`). It is an **opaque type** (§2.7) over `Int` whose owner is
`std/char` — the representation is the code point, so it is zero-cost, and `==`, `<`, hashing and
literal patterns in `match` all reuse the `Int` ones; `"${c}"` also renders the way `Int` does (for
a one-character string use `str.from_char(c)`). But it is **not** an `Int`: `'a' + 1` does not
hold, and converting between the two goes through `std/char` — `char.code(c) -> Int` takes the code
point, `char.of(n) -> Option[Char]` builds a character from a code point (`None` if it is not a
scalar value). Inside single quotes is a single code point: the escapes are the same as in strings
(`\n \t \r \\ \u{...}`) plus `\'`; an empty literal, more than one code point, or a `\u{...}` that
is not a scalar value → lexical error. For the functions that handle strings by code point see §11
(`code_points -> List[Char]`/`from_code_points`/`str.len`/`str.slice`/`str.at`).
**Note**: the runtime storage is `java.lang.String` (indexed by UTF-16 code units), so "random
access by code point index" needs an O(n) conversion — for the measurements and the design
trade-off see the appendix of [`seq6-research.md`](seq6-research.md). **For character-by-character
traversal use the cursor of §11 (`std/cursor`)**, whose cost per step is constant; the indexed
version is for one-off calls.

> **`cursor.char` is the exception: it returns `Int`, not `Char`.** At the end it answers `-1` (a
> named exception in §4.8), and a sentinel that is not a code point cannot live in a type where
> every value is a code point. The `Char` surface is `str.at`, `str.chars` and `code_points`;
> `cursor.char` is the primitive underneath them.
>
> **History**: up to and including v0.56.0, `'a'` was an `Int` (Go's rune route). The type name
> `Char` landed in v0.54.0 and the `std/char` module in v0.56.0, each one release early and as a
> transparent spelling of `Int`, purely to satisfy the seed discipline (`docs/bootstrap.md`): the
> compiler that compiles the release doing the flip must already know that name and that module.
> The flip was done in one go in v0.57.0. For the phasing, the measurements and the several routes
> that were rejected see [`audit/nominal-types-design.md`](audit/nominal-types-design.md) §7.

### 1.6 Strings and interpolation

Double-quoted strings, with the escapes `\n \t \r \\ \" \$` and Unicode `\u{1F600}`.
**Braces `{` `}` are ordinary characters and need no escaping** — convenient for writing JSON, CSS
and code generation.

Interpolation is introduced by `$` (as in Kotlin/Swift): `$name` inserts a simple identifier,
`${expr}` inserts an arbitrary expression. The interpolated type must have a `Show` witness — the
built-in scalars, user types that write `impl Show` or `derive Show`, and containers and tuples
whose elements are renderable (see §4.3):

```dawn
let n = 3
println("got $n items, first = ${list.get(0)}")
```

When `$` is not followed by an identifier or `{` it is a literal dollar sign (`"$5"` needs no
escaping); to force a literal `$` use `\$`. The effects of the expressions inside an interpolation
are unioned into the effects of the whole string expression.

A `${...}` **must fit on one line** (spanning lines reports `interpolation cannot span lines`), and
that holds inside a triple-quoted string too: what may span lines is the string, not one `${...}`
within it. Otherwise an interpolation takes anything: the `}` that ends it is the one reached
**after skipping whole literals**, so a `}` inside a string, a triple-quoted string, a raw string or
a character literal (`"${'}'}"`, ``"${`}`}"``) does not count.

Multi-line strings use triple quotes `"""`; the leading and trailing newline and the common
indentation are stripped. The interpolation rules are the same.

**Raw strings use backticks**: everything between `` `...` `` is literal — no escapes, no
interpolation, may span lines, indentation not stripped, what you see is the value. The one
restriction is that the content cannot contain a backtick itself (and there is no escape hatch; to
write a backtick, use an ordinary string). The blind spots of the three forms complement each
other: contains a backtick → `"..."`; a template that needs interpolation → `"""`; verbatim text
containing quotes and `$` (regexes, code samples, HTML) → backticks.

### 1.7 Newlines and semicolons

Statements are separated by **newlines**; there are no semicolons — writing a `;` gets a dedicated
diagnostic (telling you to delete it) and is then recovered as a newline, so it does not take
everything after it down with it. A line that ends in a binary operator, `|>`, a comma or an
opening bracket continues automatically; in addition, `|>`, `.` and **binary operators** are all
allowed at the **start of the next line** (vertical pipelines / vertical method chains / vertical
boolean or arithmetic, the idiomatic spelling — a Java builder chain
`x\n  .uri(u)!\n  .build()!` can be broken across lines, and so can a long condition
`a\n  && b\n  && c`). **The sole exception is `+` and `-`**: a leading `-` is ambiguous with unary
negation (is `x\n  - y` the expression `x - y`, or a new statement `-y`? there is no way to tell),
so that pair of arithmetic operators does not continue a line from the start of one. By convention,
one statement per line; `dawn fmt` makes it uniform.

### 1.8 `dawn fmt`

`dawn fmt <file>...` formats in place; `dawn fmt --check <file>...` only reports files that are not
formatted (exit code 1 if there are any, for CI). The implementation is a **reprinter over the
token stream**: it reprints token by token as-is (strings and interpolations are kept exactly as
their source ranges, not a character changed) and only alters the whitespace between tokens —
intra-line spacing, 2-space indentation, collapsing consecutive blank lines (the author's physical
line breaks are kept). Formatting therefore **preserves tokens, preserves comments, and is
idempotent**, and it only needs the lexer to succeed (not the parser), so a file with syntax errors
can still be formatted.

**A successful lex is a precondition, and failing it is a refusal**: a character the lexer rejects
produces no token, and tokens are all that get reprinted, so formatting such a file deletes it.
So `dawn fmt` does not write back a file that does not lex — it renders the diagnostics, exits 1,
and leaves the file untouched (`--check` likewise); the files in the same batch that do lex are
formatted as usual. A **directly named non-`.dawn` file** is refused the same way (exit 2):
directory mode already filters by extension and a named path did not, so one path typo was
enough to feed Markdown to the Dawn formatter and overwrite it.

The rules: indent 2 spaces; 1 space on each side of a binary operator /
`->` / `=>` / `=` / `|>`; 1 space after `,`/`:` and none before; nothing inside `(`/`[`; `.`/`?`
tight; `..` tight on both sides (`a..b`; where it is a prefix instead — the record spread
`{ ..base }`, the list/constructor/record rest `[x, ..rest]` — the space to its left belongs to
the opening bracket's or the comma's rule); over-long lines are not wrapped (lines the author
broke are kept).

---

## 2. Types

### 2.1 Basic types

`Int` (64-bit), `Float` (double), `Bool`, `String`, `Unit`.

`Unit` is a first-class value (its only value is `()`) and **may appear anywhere a value can
appear**: parameters, local variables, closure captures, tuple elements, return values, and as an
instantiated type parameter (`Result[Unit, E]`, `List[Unit]`, `catch_fault(() => <void call>)`).
At runtime it has a real representation — a singleton object (`dawn/rt/Unit`, the same
representation as `None` and as constructors without fields), occupying one reference slot; the C
backend gives it one byte.

There are only two exceptions, and neither is a restriction of the representation:

- **A constructor field cannot be `Unit`** — a branch with no payload is simply written as a bare
  constructor; this is a statement about modelling.
- **`Eq`/`Hash`/`Show` have no implementation for `Unit`** — there is only one value, so the answer
  would be a constant.

**There is no null.** A value of any type is necessarily valid; possible absence is expressed with
`Option[T]`.
**There are no implicit conversions.** `Int` → `Float` must be written explicitly as `to_float(n)`.

### 2.2 Built-in composite types

- `List[T]` — an immutable persistent list. The implementation is a **persistent vector: a 32-way
  trie plus a tail block** (`std/pvec`, pure Dawn source, built on the `Array` primitive): indexing
  is O(log32 n) — at length ≤32 everything is in the tail block, i.e. one array read; `++` appends
  element by element, copying only the tail block while it is not full (≤32 slots), and every 32
  appends it pushes the tail block into the trie and copies one root-to-leaf path, so the
  accumulating loop `acc = acc ++ [x]` is **linear, O(1) amortised**. Structure is shared and a
  published list never changes; appending to an old version does not copy the whole table, only its
  own small piece.
- `Option[T]` — `Some(T) | None`
- `Result[T, E]` — `Ok(T) | Err(E)`
- `Map[K, V]` — an immutable map (see below)
- `Set[T]` — an immutable set (see below)
- Tuples `(A, B, ...)`
- Function types `fn(A, B) -> C !e` (`!e` may be omitted, meaning pure)

`Option` and `Result` are ordinary ADTs, defined in the standard library, with no special status
(the `?` operator has syntactic support for them, see §8.1).

**`Map[K, V]` / `Set[T]`** are built-in persistent containers on a par with `List`. They have no
literal syntax and are operated on entirely through built-in functions (the list is in §11). The
semantics that matter:

- **Persistent (immutable) interface**: `map.insert`/`map.remove` return a new map; the original
  value is unchanged.
- **The key type = a type that has `Hash`**, and there is no second rule. Every operation that
  touches a key (`map.insert`/`map.get`/`map.has`/`map.remove`/`m[k]` and the same-named ones on
  `set`) carries a `[K: Eq + Hash]` bound, and legality of a key is exactly that bound being
  solvable — `Int`/`String`/`Bool`/`Bytes`, tuples, ADTs and records all work (one is synthesised
  from the type's own structure when no impl is written, §4.3), `Float` does not (NaN and `-0.0`
  give it two different equalities, which is why §4.3 does not give it `Hash`), `Array` does not
  (it is held by identity, not by content). The error lands on **the operation that uses the key**,
  not on the type annotation: the type `Map[Float, Int]` can itself be spelled out, there is simply
  no operation that can put a key into it.
  > Before 2026-07-27 there was a separate structural walk (`invalid_key_part`) running over type
  > annotations and generic instantiation points. It was parallel to the bound and **fought with
  > it**: it banned `Bytes` (on the grounds that "hashing is reference identity", while `Bytes` had
  > long since been changed to content hashing) where the bound let it through; and it only stopped
  > `Float` in key position, so `hash(1.5)` still passed anywhere else. What was deleted is that
  > walk, not the rule.
- **Iteration order = insertion order**, deterministic and identical on JVM and native
  (`map.keys`/`map.entries`/`set.to_list` follow insertion order). On a key that already exists,
  `map.insert` **replaces the value and keeps the original insertion position**.
- **Equality does not depend on order**: two `Map`s with the same key-value pairs are equal,
  whatever the insertion order.
- The implementation is a **persistent HAMT** (`std/hamt`, pure Dawn source, built on the `Array`
  primitive): `map.insert`/`map.remove` are O(log32 n), copying only the root-to-leaf path and
  sharing the rest of the structure with the original map (insertion order is maintained by a
  per-key sequence number). Equality and hashing of keys come from the key type's `Eq`/`Hash`
  (passed in as dictionaries), not from the host's object identity.

### 2.3 Sum types (ADT)

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  | Point                       # constructor with no payload
```

- Constructor fields **must** be named; a construction call may pass by position or by name:
  `Rect(2.0, h: 3.0)`.
- The bare name of a constructor (one with fields) in function position is an **ordinary function
  value**: `map(xs, Some)` is equivalent to `map(xs, x => Some(x))`. Type parameters are inferred
  from the expected function type (the element type of `Some` comes from the context); a type
  parameter that the fields alone cannot determine (such as the error type `E` of `Ok`) must be
  supplied by the context, otherwise the compiler reports "cannot infer type parameter". A
  constructor with no payload (`Point`) is itself a value, not a function; record construction uses
  the brace syntax and does not take part in this rule.
- Generics: `type Tree[T] = | Leaf | Node(left: Tree[T], value: T, right: Tree[T])`

### 2.4 Records

```dawn
type Point = { x: Float, y: Float }

let p = Point { x: 1.0, y: 2.0 }
let q = Point { ..p, x: 3.0 }     # functional update
let d = p.x                        # field access
```

A record is sugar for a single-constructor product type, and supports pattern matching just the
same. Fields are immutable — "modification" is functional update.

**A field of fn type can be called directly**: `r.f(x)` calls the function value stored in the
field, equivalent to `let g = r.f` followed by `g(x)`; the field's effects are unioned into the
caller as usual. When a function named `f` **also exists** in scope, `r.f(x)` is a **compile error**
(ambiguity) — a silent precedence would let a new function of the same name, added somewhere far
away, quietly change the meaning of an existing call (§10.3 already rejected the same kind of
ambiguity for module aliases of the same name; the rule here is the same). Disambiguation: to take
the field, bind it first with `let g = r.f`; to call the function, name it directly as `f(r, x)`.

### 2.5 Generics

- Type parameters are declared after the name with `[T, U]`:
  `fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`
- Monomorphism: type parameters must be fully inferable at every call site; higher-kinded types
  (HKT) are not supported.
- Implemented as erasure + boxing (v0.1); monomorphisation is left as a later optimisation and does
  not affect semantics.
- **No subtyping, no inheritance, no variance.** Types are either equal or different.
- A local annotation inside a function body may refer to the signature's type parameters
  (`let acc: List[T] = []`) — a rigid type parameter is treated in inference as a known concrete
  type.

### 2.6 Type aliases

```dawn
alias Meters = Float                                  # built-in scalar
alias Pair = (Int, String)                            # tuple
alias Names = List[String]                            # generic application
alias Handler = fn(Request) -> Result[Response, HttpError] !io   # function type
alias Lookup[T] = fn(String) -> Option[T]             # may carry type parameters
alias Paint = Color                                   # user types (ADT/record) can be aliased too
```

Aliases have **their own keyword, `alias`**; `type` declares only **nominal types** (an ADT or a
record). An alias is **transparent** (not a newtype): it is expanded during resolution and is fully
interchangeable with the type it names.

> **`alias Meters = Float` provides no unit safety whatsoever.** It is fully interchangeable with
> `Float`: `Meters` and `Seconds` can be added together, and passing a bare `Float` where a
> function takes `Meters` goes through fine. The first line above is only a syntax example of "an
> alias can name a built-in scalar" — do not read it as a recommended practice for domain
> modelling; unit types are the **most misleading** use of alias. The real value of aliases is in
> the lines below it: giving a long type a short name (`Handler`, `Lookup[T]`).
>
> For unit safety, what you want is **the `opaque type` of the next section**:
> `pub opaque type Meters = Float` is interchangeable outside its module with neither `Float` nor
> `Seconds`, and getting in and out is two one-line functions (§2.7). This sentence used to read
> "Dawn does not have this yet" — that was written before §2.7 landed and nobody came back to
> change it (the root of LANG-05 is exactly examples and signposts drifting out of sync, and this
> sentence committed the same sin itself).

> Historical note: the two once shared `type`, told apart by a "shape of the right-hand side"
> heuristic — same form, different meaning, and user types could not be aliased (a bare capitalised
> name was always read as a constructor). Now `type X = <fn type/tuple/Name[...]/built-in scalar>`
> is a compile error whose hint points at `alias`; `type Color = Red` keeps its ADT meaning
> unchanged.

Restrictions: an alias cannot be recursive (a cycle is an error); it cannot carry an effect
variable (only `!io` or pure); with `pub` it can be imported across modules (`use m.{Handler}`).

### 2.7 Opaque types

```dawn
pub opaque type UserId = Int                # only this module knows it is an Int
pub opaque type Env = Map[String, Int]
pub opaque type Pair[T] = (T, T)            # may carry type parameters
```

`opaque type N[..] = T` has the same syntax as `alias`, with exactly one difference: **who is
allowed to see through it**. Inside the module that declares it, `N` and `T` convert to each other;
outside that module they are different types.

```dawn
# inside module ids
pub fn wrap(n: Int) -> UserId = n           # ✅ convertible inside this module
pub fn unwrap(u: UserId) -> Int = u         # ✅

# in another module
let bad: Int = wrap(7)                      # ❌ annotated type is Int but the
                                            #    initializer is UserId
```

**Conversion happens at assignment, argument and return positions** (that is, wherever type
assignability is decided), not inside an expression: `u + 1` is still wrong inside the module;
write `let n: Int = u` and then compute, and the result converts back automatically when it reaches
a `UserId` position. This is the discipline of a newtype, and it also keeps "opaque" to a single
decision in the implementation rather than special cases scattered everywhere.

**Opacity blocks the view, it does not change the semantics**: at runtime an opaque type **is** its
target type — the same representation, the same equality, hashing, ordering and rendering, on both
backends, at zero cost. `opaque` is a soft keyword; only `opaque type` means anything.

> **The criterion for implementers (the alias-substitution test)**: replace `opaque type N = T` in
> place with `alias N = T`; if some function's answer changes, it is either one of the four things
> below, or it is a bug. **Only four things** are allowed to see `TyOpaque`: the assignability
> decision (who can convert), impl selection (`head_of`/`impl_at`), symbol naming
> (`ty_key`/`dict_key`/impl method names), and the type name in diagnostics.
> Every other function that eats a `Ty` — width, descriptor, slot, boxing, which instruction,
> whether it can be a constant, whether some trait has an answer — takes the target's answer.
> The order is fixed too: **ask about identity before representation**. `impl Eq[UserId]` must come
> before "compare as Int", or declaring it would be pointless.
> The mechanised form is in `scripts/opaque-twin/`: every corpus program is run twice, once as
> written and once with `alias` substituted, and the outputs must agree (a compile error counts as
> output). Doing this by hand once on 2026-07-27 caught 12 places.

An opaque type can be given its own impls (`impl Show[UserId]`), which take precedence over the
target type's; the orphan rule counts an opaque type as a local type of the module that declares it.

> Why it is needed: before this, every time a representation had to be hidden a mechanism was
> hand-rolled on the spot — `Cursor` was an opaque scalar minted by the compiler, and the HAMT
> nodes from making the collections pure Dawn would have been the next one. This puts the mechanism
> up before there is a third time.
>
> `Cursor` has already been migrated (§11): the compiler's version was deleted outright and
> `std/cursor` stands it back up using the mechanism of this section, the first real user of the
> feature.
>
> **`Array` is not the same kind of thing** — this used to say it would "migrate along with making
> the collections pure Dawn", and measurement showed that was wrong: this mechanism needs a
> **target type**, and `Array` has no target, it **is** the representation; the two also point in
> opposite directions, in that this mechanism publishes the name and hides the representation,
> while `Array`'s `is_std_module` gate hides the name and exposes the representation to std. That
> gate stays; the reason is in [`trait-v2-design.md`](trait-v2-design.md) §8.3.

---

## 3. Declarations

Only these are allowed at module top level: `use`, `type` (including `opaque type`), `alias`,
`const`, `fn`, `test`, `trait`, `impl`. There is no top-level mutable state.

### 3.1 Functions

```dawn
fn add(a: Int, b: Int) -> Int = a + b

fn greet(name: String) -> Unit !io = {
  println("hi, $name")
}
```

- **Parameter types must be written out in full** (for every function); a `pub fn` must write
  the return type as well — a public signature is an API contract.
- **A private function may omit the return type**: `fn double(x: Int) = x * 2`. When it is
  omitted, both the return type and the effects are inferred from the body (write `!io` anyway
  if you want to force the effect). Three kinds of function **must** annotate the return type:
  (1) `pub`; (2) recursive / mutually recursive ones (the compiler infers in topological order
  over the call graph, and on a cycle there is nothing to infer from); (3) ones whose body uses
  `return` or `?` (both need a known return type).
- A function that does write `-> T` keeps the original rule: omitting the effect means pure, and
  **io appearing in the body while the signature does not declare it is an error** — the
  signature is a promise.
- The function body is the single expression after `=`; a block `{ }` is an expression too (§4.2).
- No default arguments, no varargs, no overloading.

**Local named functions**: a block may contain a `fn name(params) -> T [!io] = body` statement —
essentially "a lambda whose name is visible inside its own body", so it **can recurse** (a self
tail call compiles to a loop, §12.4), can capture enclosing bindings (by value, same rule as
lambdas), and can be passed as a value. Parameter types and the return type must be written out
in full; the effect can only be `!io` or pure (lift to the top level for effect polymorphism);
type parameters cannot be declared (the enclosing function's type parameters are naturally in
scope).

```dawn
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}
```

### 3.2 Constants

```dawn
const MAX_DEPTH: Int = 64
const SIN_TABLE: List[Float] = comptime {
  range(0, 360) |> map(d => sin(to_radians(d)))
}
```

The right-hand side of a top-level `const` is implicitly in a comptime context (§7); it must be
pure and reducible to a constant.

### 3.3 Visibility

All declarations are module-private by default; `pub` exports. `pub` can be used on `fn`, `type`,
`alias`, `const`. `pub type` exports its constructors and fields as well.

### 3.4 Test blocks

```dawn
test "precedence" {
  assert eval("2+3*4") == Ok(14)
}
```

- `test` blocks are compiled and run only by `dawn test`; `dawn build` strips them.
- `!io` is allowed inside the block.
- `assert expr`: `expr` is a `Bool`; on failure it reports the source text and the values of the
  sub-expressions on either side (the compiler takes `==` and the comparison operators apart to
  give a good failure message).

### 3.5 trait and impl

A single-parameter, nominal typeclass, implemented by dictionary passing (the full design and the
decision rules are in [trait.md](trait.md)):

```dawn
trait Ord2[T] {
  fn cmp2(a: T, b: T) -> Int
  fn max_of(a: T, b: T) -> T = if cmp2(a, b) >= 0 { a } else { b }  # default body
}

impl Ord2[Point] {
  fn cmp2(a: Point, b: Point) -> Int = a.x - b.x
}

fn sort2[T: Ord2](xs: List[T]) -> List[T] = ...   # bound: [T: Trait (+ Trait)*]
```

- A trait has exactly one type parameter; its methods enter the module function namespace
  (callable directly, by UFCS, or in a pipeline).
- **Injection is a per-trait property**: whether a trait's method names occupy the function
  namespace is decided by that trait. Today a `trait` declaration always injects, and the five
  built-in traits `Ord`/`Eq`/`Hash`/`Show`/`Iter` inject too; a trait consumed exclusively by an
  operator (`Index`, §4.8) does not inject, and its method names appear only in impl bodies, in
  documentation and in error messages.
- **Six built-in traits**: `Ord` (`cmp`, behind ordering beyond `<`/`<=`), `Eq` (`eq`, behind
  `==`/`!=`), `Hash` (`hash`), `Show` (`show`, behind `to_string` and `${...}`), `Iter` (behind
  `for..in`, §4.7), `Index` (behind `[]`, §4.8). The impls for the scalars ship with the language;
  `derive Ord` / `derive Show` cast an ordinary impl, and on a generic type a conditional impl.
  A tuple has no head, so no impl can be written for it; the first four are synthesised
  structurally for tuples by the compiler.
- **`Iter`** declares two associated types and four methods (associated types are covered further
  down this section):
  `trait Iter[C] { type Cur  type Item  fn iter_start(c: C) -> C.Cur
  fn iter_done(c: C, k: C.Cur) -> Bool  fn iter_next(c: C, k: C.Cur) -> C.Cur
  fn iter_get(c: C, k: C.Cur) -> C.Item }` — four cursor methods rather than a `next` that
  returns a pair, so that one step forces no allocation (the shape of the cursor is up to the
  impl). std provides one impl each for `List`/`String`/`Bytes`/`Map`/`Set` (the elements are
  `T` / a single-character `String` / an `Int` byte / `(K, V)` / `T` respectively); a user type
  that implements `Iter` can be iterated by `for`. The four method names are injected into the
  function namespace along with the prelude, and get the same treatment as the rest of the
  prelude names — **they can be shadowed by a declaration in this module** (§10.3).
- **`Index`** declares two associated types and one method:
  `trait Index[C] { type Idx  type Item  fn index(c: C, i: C.Idx) -> C.Item }`.
  The language provides impls for `List` (`Idx = Int`) and `Map` (`Idx = key type`); a user type
  that implements `Index` can use `[]` (example in §4.8). The method name `index` does **not**
  enter the function namespace (see the injection rule above), and appears only in impl bodies,
  in documentation and in error messages. A type has exactly one index type — `Index` is a
  single-parameter trait, so a second kind of subscript on the same container (slicing, say)
  cannot be written.
- **Coherence**: at most one impl per "trait × type" across the whole program; the **orphan
  rule**: an impl can only be written in the module that declares the trait or the subject type.
  Impls take effect globally, no `use` needed.
- **Subject shape**: one type constructor, applied to **pairwise distinct type variables**, and
  those variables are exactly this impl's own parameters — `impl Eq[Money]`,
  `impl[T: Eq] Eq[List[T]]`, `impl[K: Eq, V: Eq] Eq[Map[K, V]]` are all legal;
  `impl Eq[List[Int]]` (a concrete argument) and `impl[T] Eq[Map[T, T]]` (a repeated variable)
  are not. This one rule decides "which impl matches" (heads are equal), "whether two impls
  overlap" (the same), and "whether recursive solving terminates" (a subgoal is a proper subterm
  of its parent goal).
- **Conditional impls**: the methods of `impl[T: Eq] Eq[List[T]]` are generic functions that take
  dictionaries according to their bounds; a concrete target like `Eq[List[Int]]` is solved to a
  constant dictionary at compile time, while `Eq[List[T]]` (with `T` rigid) is built at run time
  from `Eq[T]`. No dyn, no supertraits, no specialisation (no asking "which one is more
  specific"). A trait method's effect can only be pure or `!io`, and an impl's effect ⊑ the trait
  declaration's.
- **Associated types** (design and verdicts in
  [assoc-types-design.md](assoc-types-design.md)): a trait body may declare a bare `type Item`
  member (no bound, no default), and an impl **binds each declaration exactly once** with
  `type Item = X` (X resolves in the impl's own parameter scope, and must not itself be a
  projection); a missing binding, multiple bindings, and binding a name the trait does not have
  are each a compile error. A method signature **projects** it as `T.Item` — the subject must be
  a type parameter carrying that trait bound (exactly one bound declares the name; zero and
  ambiguity are both errors), and a concrete subject such as `List[Int].Item` is not supported.
  - **Reduction is eager**: when instantiation at the call site lands the subject on a concrete
    head, the projection is immediately replaced by the bound value via that subject's impl (the
    same door as dictionary selection) — an unreduced projection **does not exist** in a concrete
    type. A projection on a rigid subject (a `T` inside a generic body) stays as it is, and
    unifies only with a literally identical projection.
  - An associated type name **lives only inside the trait's scope**; it does not enter the module
    type namespace, and `T.Item` is the only way to reach it. An opaque subject looks in its own
    impls first, and falls back to the target's (same order as witnesses). Zero representation at
    run time: types are erased as usual, and a dictionary gains no extra slot.
  - **A projection in an argument position takes no part in inference**: the type parameters are
    fixed by the **non-projection** argument positions; the projection is then reduced through
    that subject's impl binding and compared against the actual argument. Corollary: a method
    whose type parameter occurs only inside a projection cannot be called by name (it reports
    "cannot infer"); trait authors should put the subject in the parameter list — all four `Iter`
    methods put `c: C` in position 0 for exactly this reason.

```dawn compile
trait Head[C] {
  type Item
  fn first(c: C) -> Option[C.Item]
}

impl[T] Head[List[T]] {
  type Item = T
  fn first(c: List[T]) -> Option[T] = get(c, 0)
}

fn head_or[C: Head](c: C, d: C.Item) -> C.Item =   # the projection reduces at instantiation
  match first(c) { Some(x) -> x  None -> d }        # head_or([1], 9) is Int
```
- The built-in `trait Ord[T] { fn cmp(a: T, b: T) -> Int }` and the impls for `Int`/`String`
  (**`Float` has none**: under NaN there is no total order to give — the reasons for refusing are
  in §4.3, numeric edge semantics; the one previously given following `Double.compare` was
  reverted on 2026-07-26).
  - **`cmp` promises only the sign**: less than returns `-1`, equal returns `0`, greater returns
    `1`, and **no other magnitude is promised** — `cmp("a", "z")` used to leak the host's code
    unit difference `-25`; since 2026-07-31 every type uniformly returns −1/0/1 (treating the
    result as a difference to be scaled could overflow anyway, and std has always used only the
    sign).
  - **`Ord[String]` is code point order**: compare code point by code point, the first differing
    code point decides, and when one is a prefix of the other the shorter is smaller. UTF-8's
    byte order is equivalent to code point order (a design property of the encoding); the
    currency of hashing is still UTF-16 code units (see the hash leaves below), and it
    **deliberately does not follow** — a hash only has to agree with `==`, it does not have to
    share a currency with the order. Everywhere else in the language (`str.len`/`slice`/`chars`/
    `code_points`/cursors) the currency was already code points; the order was the last place to
    be aligned (2026-07-31; before that it was UTF-16 code unit order, observable only on
    supplementary plane characters).

  `derive Ord` generates a field-lexicographic comparison (a sum type compares constructor
  declaration order first, and when the constructors differ it produces only `-1`/`1`), and the
  fields must be `Int`/`String`, a type with an Ord impl of its own, or a type parameter of the
  type itself (in which case what is generated is a conditional impl:
  `type Box[T] = { v: T } derive Ord` gives `impl[T: Ord] Ord[Box[T]]`). `List[T]` has a
  lexicographic impl written in std.
- The built-in `trait Eq[T] { fn eq(a: T, b: T) -> Bool }` and
  `trait Hash[T] { fn hash(x: T) -> Int }`. `Eq`'s scalar impls are
  `Int`/`Float`/`Bool`/`String`/`Bytes`; `Hash` has **no `Float`** (the reason for refusing it
  is under numeric edge semantics in §4.3, as for `Ord[Float]`), so it has four.
  **There is no `derive Eq`**: `==` is already structural
  for every type (§4.3), which amounts to every type implementing Eq implicitly; you write an
  impl in order to **override** it.
  - After an override, `==` is that impl, and container and nested comparisons follow along.
  - **`impl Eq` and `impl Hash` must appear as a pair** (a compile error otherwise): equal values
    must hash the same, or the type is useless as a `Map`/`Set` key.
  - Inside the overriding body you cannot use `==` on the subject type itself — that is this
    impl, and it would recurse forever; compare the fields.
  - When an `Eq`/`Hash` bound is instantiated at a type that **has no impl** (an ADT, a tuple),
    the compiler **synthesises** an implementation from that type's own structure — equivalent to
    an implicit conditional impl, requiring the corresponding bound on the type parameter when
    the subject contains one. When the subject is statically known it collapses straight to a
    primitive and no dictionary is built.
  - The synthesised hash is an **observable number** (`hash(x)` can be printed), so it is defined
    here: seed `1`, then `h = 31*h + hash(part)` part by part, in 32-bit wrapping arithmetic;
    tuples in element order, constructors in field order, and **when there is more than one
    constructor the constructor's ordinal is folded in first as the first part** (with a single
    constructor there is no distinguishable tag — the same rule as `==`/`cmp`).
  - The algorithms for the four scalar leaves are likewise defined here (all 32-bit wrapping
    arithmetic, the result a 32-bit number):
    - `Int`: `v ^ (v >>> 32)`, take the low 32 bits.
    - `Bool`: `true` gives `1231`, `false` gives `1237`.
    - `String`: seed `0`, then `h = 31*h + unit` per **UTF-16 code unit**. The currency of
      hashing is UTF-16 code units, which is **a different matter** from the currency of the
      order, and that is deliberate: a hash only has to agree with `==` (same content ⟹ same
      hash), it does not have to share a currency with any order, and when the order's currency
      changes the hash **does not follow**.
    - `Bytes`: seed `1`, then `h = 31*h + b` byte by byte, with `b` the **signed** byte
      (−128..127). Exactly the same shape as the composite rule above — fold each byte as one
      part.
  - `List` is not in this list: std writes `impl[T: Eq] Eq[List[T]]` and the corresponding
    `Hash`/`Ord`. `Map`/`Set`/tuples still go through synthesis.
- Limits: trait methods and functions with bounds cannot be used as function values (the hint
  says wrap them in a lambda); calls with trait bounds and impl-based sorting are not allowed in
  comptime.

---

## 4. Expressions

Dawn is expression-oriented: `if`, `match` and blocks all produce values.

### 4.1 Bindings

```dawn
let x = 42              # immutable binding, type inferred
let y: Float = 1.0      # optional annotation
var acc = 0             # mutable local variable
acc = acc + 1           # assignment, legal only for var
```

- `let` is immutable and cannot be shadowed (binding the same name twice in one scope is an
  error; a nested scope may shadow).
- `var` is limited to local variables inside a function body; record fields, parameters and
  top-level bindings are all immutable.
- Assignment is a statement (type `Unit`), not an expression — the `if (x = 1)` class of
  mistake does not exist.

### 4.2 Blocks

```dawn
let area = {
  let w = 3.0
  let h = 4.0
  w * h                  # the last expression is the block's value
}
```

A block introduces a new scope; the last expression is the block's value, and every other
statement must have type `Unit` (this stops a `Result` from being quietly discarded —
discarding a non-Unit value must be written out as `let _ = ...`).

### 4.3 Operators and precedence

From lowest to highest:

| Precedence | Operator | Associativity | Notes |
|--------|--------|--------|------|
| 1 | `\|>` | left | pipeline, see §4.4 |
| 2 | `\|\|` | left | logical or, short-circuiting |
| 3 | `&&` | left | logical and, short-circuiting |
| 4 | `== != < <= > >=` | non-associative | comparison; chained comparison is a syntax error |
| 5 | `\|` | left | bitwise or; `Int` only |
| 6 | `^` | left | bitwise xor; `Int` only |
| 7 | `&` | left | bitwise and; `Int` only |
| 8 | `<< >> >>>` | left | shifts; `Int` only. `>>` is arithmetic (sign-filling), `>>>` logical (zero-filling) |
| 9 | `++` | right | `String`/`List` concatenation |
| 10 | `+ -` | left | numeric only, both sides the same type |
| 11 | `* / %` | left | numeric only; `Int` division by zero panics |
| 12 | `not`, unary `-`, `~` | prefix | `~` is bitwise complement, `Int` only |
| 13 | `? . () []` call | postfix | `?` see §8.1; `()` has been a **general postfix** since 2026-07-30 (see below) |

- **A call is a general postfix (SYN-02)**: any postfix expression followed on the same line
  by `(` is an application — `make()(1)`, `(if c { f } else { g })(1)`, `get_handler()(req)`
  are all legal. `f(x)` and `Circle(1.0)` take the **same** postfix path (since 2026-07-31
  neither has a special case of its own); which kind of call it is is decided by **what the
  callee is**, not by how it is written: a constructor name → construction, a function name →
  static call (dynamic call if the name is bound to a function value), a Java member → Java
  call, any other expression → applying a function value.
  **A `(` on the next line is not eaten**: a newline ends the postfix chain (only `.` may
  continue a chain across lines, §1.7), so `let x = f` followed by `(1 + 2)` on the next line
  is still two statements — the same discipline as unary `-` not continuing a line.
- **Trailing closure: an `fn` lambda following on the same line is the last argument**
  (2026-07-31). `f(a) fn(x) => e` is `f(a, x => e)`, `xs.each fn(x) => e` is
  `xs.each(x => e)`, `f fn(x) => e` is `f(x => e)` — the landing point is exactly the one
  `(` has (so a dot call yields a method call and everything else an application); the sugar
  changes the spelling, not the node.
  **Only the `fn` spelling is recognised**: a bare `{ ... }` trailing closure (Kotlin style)
  is permanently out of scope — it cannot be told apart from the body of a parenthesis-free
  `if`/`while` header (`if c { ... }`).
  **Same line only**, the same discipline as `(`: `let y = g(1)` followed by
  `fn h(k: Int) -> Int = k` on the next line is two statements; a local function declaration
  is not swallowed by the call on the line above.
  If the body needs several statements, write `f(a) fn(x) => { ... }` (a lambda with a block
  body, §4.5).
- **Named arguments (`f(a: 1)`) are syntactically legal at every call position**, dot calls
  and applied function values included; whether they are usable is decided by **what the
  callee is** (2026-08-08, #207). **A callee with a signature accepts them**: top-level
  functions, module functions, UFCS/dot calls, pipes, trait methods (the names are the
  **trait declaration's** parameter names; an impl's own spellings are purely local), effect
  operations, and constructors (field names, see §2.3). **A function value does not** — a
  function type carries no parameter names, so after `let g = f`, `g(a: 1)` is a type error
  ("`g` is a function value, and a function type carries no parameter names"). **A Java
  member does not** — Java metadata has no parameter names.
  The slotting rule is the **same one** constructors use: the positional prefix takes slots
  left to right, a name takes the slot it names, names may come in any order, and a
  positional argument may not follow a named one; a dot call's receiver has already taken
  the first slot positionally, so `x.f(self: y)` reports "parameter `self` is given twice".
  `f(1)(2)` parses, and the meaning is still "the result of `f(1)` must be a function" —
  Dawn has no automatic currying; the second application's callee is a function value, so it
  cannot take names.
- **Arguments evaluate in written order** (2026-08-08, #207 ruling): call and constructor
  arguments evaluate in the order they are **written** (as in Python / C# / Scala / Swift /
  Kotlin); named arguments reorder the **slotting**, not the evaluation — in
  `R { b: f(), a: g() }`, `f()` runs before `g()` and each value lands on its own field.
  `..base` can only be written first, and evaluates first. Binary operators evaluate left to
  right (`&&`/`||` still short-circuit). Before this rule, constructors evaluated in
  **declaration order** and the C backend left argument order to C (gcc goes right to left)
  — both are fixed to this rule, pinned by the two-backend differential
  (`scripts/spike-native/named_args.dawn`, `eval_order.dawn`).
- Bitwise `& ^ \|` and the shifts **act on `Int` only** (there is no `Float` bit pattern);
  they bind **tighter than comparison**, so `a & b == c` is `(a & b) == c`, without the
  C-family trap. A shift count takes its low 6 bits (as JVM `LSHL` does).

**Numeric edge semantics** (all of them **guaranteed** — after selfhosting the two
implementations are cross-checked against this, "happens to agree" is not allowed):

- `Int` overflow **wraps around** (two's complement, as on the JVM): `MAX + 1 == MIN`. The
  one division that can overflow, `MIN / -1`, wraps too (the result is `MIN`), and
  `MIN % -1 == 0`.
- `/` **truncates toward zero** (`-7 / 2 == -3`, not floor); the **sign of `%` follows the
  dividend** (`-7 % 2 == -1`, `7 % -2 == 1`), and `a == (a / b) * b + a % b` always holds.
- Division by zero with `/` and `%` is a **panic** (message `Int division by zero` /
  `Int modulo by zero`) — a panic and not a Java exception, so `catch_fault` does not catch
  it and only `catch_panic` does (§9.8).
- `Float` arithmetic follows IEEE 754: division by zero does not panic (you get
  `±Inf`/`NaN`); `==` and `< <= > >=` are IEEE comparisons — NaN compares false against any
  value, itself included, and `-0.0 == 0.0` is true.
- **`Float` has no `Ord`** (changed 2026-07-26; before that it was given a total order
  following Java's `Double.compare`). NaN is incomparable with any value, itself included,
  so there is no total order to give on Float — and `Ord` is exactly what
  `sort`/`max`/`min`/`max_by`/`min_by`/`derive Ord` and `[T: Ord]` depend on. "Degrading to
  a partial order" in Dawn means **one impl fewer**, not one trait more:
  `<`/`<=`/`>`/`>=` on scalars do not resolve a witness in the first place, and stay usable
  with the same IEEE semantics as before. Exactly one thing changed: `[T: Ord]` no longer
  admits Float, and `cmp(1.5, 2.5)` no longer compiles. (Rust's `total_cmp` is an inherent
  method on `f64`, and `f64` likewise has no `Ord` impl.)
- **`Float` has no `Hash`** and therefore cannot be a Map/Set key: `-0.0 == 0.0` is true
  while the two bit patterns differ, and no hash can be consistent with that equality and
  with itself at the same time (as in Rust).
- **`Float` has `Eq`, and it is not reflexive** (`nan == nan` is false). That is a fact
  about IEEE, not a hole, and Dawn does **not** split out `PartialEq`/`Eq` as two traits
  because of it (an explicit verdict on 2026-07-26 not to split): Dawn has one `Eq` only,
  and splitting would make an everyday expression like `1.5 == 2.5` carry one more concept,
  a cost far larger than the benefit. Where reflexivity is relied on (container lookup),
  the rule that Float cannot be a key already blocks it.
- **The `to_string`/`Show` rendering of `Float` is a rule the language writes down itself**
  (the implementation is one piece of Dawn source, `std/fmt.dtoa`, shared by both backends
  and by comptime folding; since 2026-07-31 it no longer calls a host method — the **shape**
  of the rule was taken from that day's JVM `Double.toString` (the Schubfach shortest
  round-trip of JDK 19+), so not one byte of the published JVM output changes, but if the
  host switches algorithm from now on Dawn **does not follow**):
  - **Shortest round-trip**: the output is the **shortest** decimal digit string that reads
    back as the original double uniquely; among candidates of the same length the one
    closest to the true value wins, and a remaining tie goes to the even significand.
  - **Two forms**, switched on magnitude: `10^-3 ≤ |v| < 10^7` uses the ordinary decimal
    form (`0.001`, `9999999.0`), everything else scientific notation `d.dddEe` — exactly one
    non-zero digit first, at least one digit after the point, an upper-case `E`, no leading
    zero in the exponent, a `-` on a negative exponent and no `+` on a positive one
    (`1.0E7`, `9.999999999999998E-4`, `4.9E-324`).
  - An integral value keeps its `.0` (`1.0`, not `1`); the fractional part has **at least
    one digit**; `-0.0` keeps its sign.
  - Three special spellings: `NaN` (**unsigned**), `Infinity`, `-Infinity` — the same three
    spellings `parse_float` accepts, so `parse_float(to_string(x))` closes for every `x`
    (§11).
- **`to_int(x)` truncates toward zero and saturates** (as JVM `D2L`): `to_int(2.7) == 2`,
  `to_int(-2.7) == -2`; `NaN` gives `0`, and anything outside the `Int` range (`±Inf`
  included) gives **the nearer end** (`to_int(1.0 / 0.0)` is the maximum value of `Int`).
  This is written down because C's cast is undefined for all three of those inputs and on
  x86-64 answers the minimum `Int` for all three — which is what native answered before
  2026-07-30.

- `==`/`!=` default to structural equality and are available on any type (function types
  excepted — comparing functions is a compile error); a type can override that default with
  `impl Eq` (§3.5).
- The ordering comparisons `<`/`<=`/`>`/`>=` have **two mechanisms**, not one:
  - On `Int`/`Float`/`String` they are **native operations that resolve no witness** — no
    impl lookup, no dictionary built. On `Float` the semantics are IEEE (any comparison
    involving NaN is false, see the numeric edge semantics above).
    Other concrete types bridge to `cmp` of the built-in trait `Ord` (see §3.5) — having an
    impl (hand-written or `derive Ord`) is enough to compare.
  - `[T: Ord]` is a trait bound and goes through dictionaries: on a type parameter
    constrained by it, `<` resolves the `Ord` witness just as `cmp`/`sort` do. `Float` has
    no impl (the reason for refusing is under "`Float` has no `Ord`" above and is not
    repeated here), so `cmp(1.5, 2.5)` does not compile while `1.5 < 2.5` stays legal.
  - The two mechanisms **give the same answer** on `Int`/`String` (on `String`, `<` and
    `cmp` are the same comparison and the same order — **code point order**, see §3.5), and
    **differ on purpose** on `Float`: native `<` is the IEEE partial order, `Ord` wants a
    total order, and Float only has the former.
- Printing user types: add `derive Show` after a `type` declaration to get `to_string` and
  string interpolation support (`Ord` is also derivable, see §3.5; use commas for several:
  `derive Show, Ord`).
  `Show` is a **built-in trait** and `derive Show` mints exactly one impl, so you may also
  hand-write `impl Show[T] { fn show(x: T) -> String }` for a custom rendering, and use a
  conditional impl for a generic type (`impl[T: Show] Show[Box[T]]`). The signature of
  `to_string` is `[T: Show]`.
  The rendering is shaped like legal Dawn source:
  - a constructor with no payload → `Red`; a constructor with positional fields →
    `Circle(1.5)`;
  - a record → `Point { x: 0.0, y: 2.5 }` (with field names);
  - a `String` field is double-quoted and escaped (`"a\nb"`); `Int`/`Float`/`Bool` follow
    their own `to_string`;
  - containers render recursively: `List` → `[a, b]`, a tuple → `(a, b)`, `Option`/`Result`
    follow the payload (`Some(Red)`).
    `Map`/`Set` have no literal syntax and render as **the call that rebuilds them**:
    `map.from([(k, v), ...])`, `set.from([e0, e1])` — the public spelling, because the point
    of "reads like source" is that **you can paste it back** (it once printed the retired
    flat name `map_from`, which pasted back reports undefined function; audit RD-14).
  - every field type must be printable (a function field, or a nested user type without
    `derive Show` → an error at the declaration);
    a generic type is printable **if and only if** its type arguments are (`Box[Int]` is,
    `Box[fn(...)→...]` is not) — on a generic type `derive Show` mints
    `impl[T: Show] Show[Box[T]]`, and that is its bound.
  - **A top-level `String` gets no quotes, a nested one does.** `to_string("a")` is `a`,
    while `["a"]` is `["a"]` — the quotes are the mark for "here is a value, not punctuation
    from what surrounds it".
    The trait method `show` is the **nested** one, so rendering a string through a
    `[T: Show]` bound does carry quotes; `to_string`/`${}` drop them only when the **static
    type is `String`** itself.
    One trait doing two jobs — this line is where the seam sits (Rust splits it into Display
    and Debug).

### 4.4 Pipelines

`x |> f(a, b)` is equivalent to `f(x, a, b)` — it puts the left-hand side into the **first
parameter**. `x |> f` is equivalent to `f(x)`. Standard library APIs are all designed around
"the main datum is the first parameter" so that they work with pipelines.

### 4.5 Lambda

```dawn
let double = (x: Int) => x * 2
let add = (a, b) => a + b         # parameter types may be omitted when inferable
let now = () => 0                 # zero parameters
xs |> map(x => x * x)             # parentheses optional for a single parameter
```

- **There is exactly one spelling**: `params => expr`. `params` is `x` (the parentheses may
  be dropped for a single unannotated parameter), `(a, b)` or `()`, and each parameter may
  carry `: Type`. `=>` owns the single job of "an anonymous function starts here".
- **The `fn` prefix has retired** (2026-08-01): `fn(x) => e` no longer parses as a lambda,
  and a dedicated diagnostic, "a lambda has no `fn` prefix", teaches the new spelling. In an
  expression `fn` has one position left — the trailing closure.
- If the body needs several statements, use a block: `(x) => { ... }`.
- Written after a call (on the same line) it is that call's **last argument** — a trailing
  closure, see §4.3.
  **The trailing-closure position must be written with `fn`**: in `f(a) (x) => e` the `(x)`
  is already the curried call `f(a)(x)`, and the two readings cannot be told apart before
  the `=>` is reached, so what is reserved for that position is exactly the `fn`-prefixed
  spelling — the only surviving use of `fn` on a lambda. The diagnostic names this.
- A form starting with `(` **is only decided after looking at whether a `=>` follows the
  `)`**: `(a: Int)` is a legal parameter list but not a legal expression, so a cover grammar
  (parse it as an expression first, reinterpret it on seeing `=>`) does not work here. When
  the decision fails it reports "invalid parameter list before `=>`" and names the offending
  token (`(a + 1) => e`).
- **A lambda cannot be used directly as the condition of an `if`/`while`**: `if x => { ... }`
  would eat the braces that were meant to be the loop body as the lambda's body. There is a
  dedicated diagnostic for this, not "expected `{`".
- A closure captures bindings by value (capturing a `var` is a compile error — to share
  mutable state, pass it explicitly).
- **Division of labour between the arrows (design verdict, 2026-07-31, deliberately not
  unified)**: `->` is the **clause arrow** and appears only in "declaration-shaped"
  positions — function types (§2.2) and match arms (§5.1); `=>` is the **expression arrow**,
  whose only job is to mark where an anonymous function starts. Neither stands in for the
  other: when an arm body is a lambda (`Some(f) -> x => f(x)`), the two arrows are precisely
  the signal by which the reader tells the levels apart — the same reasoning by which Rust
  keeps `->` and `=>` separate, and the opposite of Scala's unification.

### 4.6 if

```dawn
let sign = if x > 0 { 1 } else if x < 0 { -1 } else { 0 }
```

- The condition must be `Bool`, and a branch body must be a block.
- Used as a value, `else` must be present and the branches must have the same type;
  used as a statement (the value is discarded) `else` may be omitted, and then the branches
  must be `Unit`.

### 4.7 Loops

```dawn
for x in [1, 2, 3] { println("$x") }
while queue.non_empty() { ... }
```

- `for`/`while` are statements of type `Unit`, and `var` may be used inside the body to
  accumulate.
- `break` leaves the **innermost** loop and `continue` jumps to its next round. Both are
  expressions of type `Never` (like `return`, they may appear in expression positions such
  as a match arm); they are legal only inside a loop body, and **cannot cross a
  lambda/local-function boundary** to reach a loop outside (a lambda is a function of its
  own; use `return` to leave it). There is no labelled form — to break out of several
  levels, extract a function and use `return`. comptime loops support them equally.
  The statements after a `with` are also the body of a closure (§4.10), so a `break` there
  likewise cannot reach the loop outside — the diagnostic names `with` instead of talking
  about a lambda the author never wrote.
- **`for x in e` iterates any type that implements `Iter`** (a built-in trait, §3.5): it
  desugars into ordinary trait calls to `iter_start/iter_done/iter_next/iter_get`, and the
  element type is that impl's `Item`. The five std containers
  (`List`/`String`/`Bytes`/`Map`/`Set`) iterate out of the box; a parameter bound by
  `[C: Iter]` in a generic function is equally `for`-able (dictionary forwarding). The
  iteration order is the impl's cursor order (`String` by code point, `Map`/`Set` the same
  as `entries`/`to_list`).
- `for x in a..b` supports half-open integer ranges (not via `Iter`).

Idiomatic style prefers `map`/`filter`/`fold`; loops are there for performance-sensitive
spots and for taste.

### 4.8 Indexing

```dawn
let x = xs[i]        # List[T] -> T; out of range panics (negatives included)
let v = m["key"]     # Map[K, V] -> V; a missing key panics (the message carries the key)
let c = rows[1][0]   # chainable, composes with ?/./()
```

- **`[]` is an assertion, the get family is an enquiry**: `xs[i]` is for the case "the index
  is necessarily valid, out of range is a bug" (panic semantics, as in Rust); when out of
  range / a missing key is a normal branch, use `get(xs, i)` / `map.get(m, k)` (which return
  `Option`).
- Indexing is resolved by the built-in trait **`Index`** (§3.5): the impls for `List`
  (`Idx = Int`) and `Map` (`Idx` = the key type) ship with the language, and **a user type
  gets `[]` by writing one `impl Index`**; a type with no impl is a compile error. An
  `opaque type` inherits its target type's impl (as with `==`/`${…}`/`for..in`).
- comptime supports `List` indexing (out of range is a compile error).
- **Read-only** — there is no `xs[i] = v`, and `Index` has no corresponding write method.
  Lists and maps are immutable; a user type, even a mutable one, is not written through `[]`.
- The comparison operators `<`/`==` route to the native implementation for scalars without
  going through a trait (see §4.3) — `Index` only governs `[]`.

An impl for a user type:

```dawn
type Grid = { w: Int, cells: List[Int] }

impl Index[Grid] {
  type Idx = (Int, Int)
  type Item = Int
  fn index(g: Grid, p: (Int, Int)) -> Int = {
    let (x, y) = p
    g.cells[y * g.w + x]
  }
}

let g = Grid { w: 3, cells: [1, 2, 3, 4, 5, 6] }
let v = g[(2, 1)]                                 # 6

fn first[C: Index](c: C, i: C.Idx) -> C.Item = c[i]   # a generic consumer
```

**The three out-of-range criteria.** The language promises three out-of-range policies only,
and every operation taking an index/range parameter (the `[]` of this section and the
library functions of §11) belongs to exactly one of them, classified by what the parameter
**means** rather than settled function by function:

1. **Assertion** — the parameter is a **position**, the caller claims it is valid, and out of
   range is a bug: `xs[i]`, `m[k]`, `bytes.at`, `str.at`, `pvec.index`/`nth`, an invalid
   range for `cursor.slice` → **panic** (negative indices included).
2. **Enquiry** — out of range / a missing key is a normal branch the caller wants to tell
   apart: the `get` family (`list.get`, `map.get`, absence in `set.has`, a miss in the
   `index_of` family (`str`/`bytes`/`list`), a non-match in `str.strip_prefix`/
   `strip_suffix`, malformed input to `bytes.from_hex`/`from_base64` and to
   `fspath.extension` (package)) → **`Option`** (or `Bool`).
3. **Clamping** — the parameter is a **range**, saying "whatever part of this stretch is
   there", and does not assert that the endpoints exist:
   `list.take`/`drop`/`slice`, `bytes.slice`, `str.slice`/`take`/`drop`,
   `cursor.next`/`prev`/`back`/`seek` → each end is clamped into
   `[0, len]` (a negative becomes `0`, an over-long one `len`), `from > to` gives the empty
   sequence, and it **never panics**.

**The one named exception**: `cursor.char(s, c)` returns the sentinel `-1` at the end rather
than an `Option` (§11, "std/cursor"). It is the primitive that advances character by
character — wrapping every step in an `Option` is one allocation per step; the same sentinel
is wrapped by std into a panic over at `bytes.at` (criterion 1), while here at
`cursor.char` it is part of the public contract (the lexer of `packages/json` depends on
it). Apart from this, no library function may express out of range with a sentinel value.

### 4.9 return

```dawn
fn classify(n: Int) -> String = {
  if n < 0 { return "negative" }   # guard clause
  if n == 0 { return "zero" }
  "positive"
}
```

- `return expr` / a bare `return` (in a `Unit` function only) returns early from the
  **innermost function** — inside a lambda it leaves that lambda (the same scoping rule
  as `?`).
- `return` is an expression of type `Never` and may appear in any expression position (a
  match arm, for instance).
- The enclosing function (or the lambda's expected type) must already declare a return
  type — it is unavailable inside an inferred function that omits its return type.
- **Unavailable inside the sugared region**: the statements after a `with` are the body of a
  closure (§4.10), `return` cannot get out there, and the compiler reports an error on the
  spot, naming `with`.

### 4.10 The `with` statement

```dawn
fn write_all(path: String, bytes: Bytes) -> Unit !io = {
  with f <- bracket(FileOutputStream.new(path), s => s.close())
  f.write(bytes)!
  f.flush()!
}
```

`with x <- f(a, b)` is **parser-level sugar**: **all** the statements after it in the block
are packed into `x => { ... }` and attached as `f`'s **last** argument, and the whole call
becomes the block's value at that point. The snippet above is equivalent to

```dawn
bracket(FileOutputStream.new(path), s => s.close(), f => {
  f.write(bytes)!
  f.flush()!
})
```

- **Inside a block only**, and only as a statement: it has to eat "the rest of the block",
  and with no block there is nothing to eat (`fn f() = with x <- g()` is a syntax error, and
  the hint says to add braces).
- **Several `with`s in one block nest naturally** — the second eats the part after itself.
  With `bracket`, the release order is therefore **inside out** by construction (§9.8.2).
- **The landing point is the same one as the trailing closure's** (§4.3): `f(a, b)` grows
  one argument, `r.m(a)` grows one argument, and a bare name `g` becomes `g(x => ...)`. So
  `with` combined with an `fn` trailing closure is just an ordinary call; there is no third
  rule.
- **`?` passes through transparently**: what the closure hands back is the value of the
  `with` call, and that is the block's value, so an `Err` propagated by `expr?` inside the
  sugared region becomes the return value of the enclosing function — and `bracket`'s
  release still runs (cross-check in `scripts/spike-native/with_sugar.dawn`).
- **`return`/`break`/`continue` are rejected inside the sugared region**, and the diagnostic
  names `with`: what they would have to cross is a closure boundary the author never wrote,
  and "getting out" only means what the reader thinks it means when that block happens to be
  in tail position. A loop **of its own** inside the sugared region is unaffected (a `for`
  after the `with`, with `break` belonging to it).
- Write one name at the binding site, with the same rules as a lambda parameter; there is no
  `_` form (nor do lambda parameters have one).

> Why `bracket` and not `defer`: the protected interval is always exactly one closure call,
> `return`/`break` cannot get out of it at the language level, and so the compiler owes no
> escape-rewriting pass.
> The criteria are in `docs/core-move2-design.md` §2.6 and §6.

---

## 5. Pattern matching

```dawn
match shape {
  Circle(r) if r > 100.0 -> "big circle"
  Circle(r)              -> "circle $r"
  Rect(w, h)             -> "rect ${w}x$h"
  Point                  -> "point"
}
```

### 5.1 Pattern forms

| Pattern | Example | Matches |
|------|-----|------|
| Literal | `0`, `"yes"`, `true` | matches if equal |
| Binding | `x` | always matches, and binds |
| Wildcard | `_` | always matches, binds nothing |
| Constructor | `Some(x)`, `Rect(w, h)`, `Rect(w: w, ..)` | destructures by position or by name, `..` ignores the remaining fields |
| Record | `Point { x, .. }` | field destructuring |
| Tuple | `(a, b)` | |
| List | `[]`, `[x, ..rest]` | empty list / head and rest |
| Or | `0 \| 1 \| 2` | any alternative matches (the bindings of every alternative must agree) |
| Guard | `pat if cond` | the pattern matches and the guard is true |

### 5.2 Exhaustiveness

`match` **must be exhaustive**. The compiler checks exhaustiveness on ADT/Bool/Option/Result/tuple;
a missing arm is an error and the missing constructors are listed. A match on
`Int`/`String`/`Float` must have a `_` or a binding arm as the catch-all.

`let` also accepts irrefutable patterns: `let (a, b) = pair`, `let Point { x, y } = p`.

---

## 6. Effect system

### 6.1 Model

An effect row has two axes.

The **base axis** has only two points: **pure** (the default, written nowhere) and **io**.
`!io` covers every observable side effect: files, network, clock, random numbers, printing,
mutable global state, and all Java interop.

The **label axis** is the finite set of named effects the user declares with `effect` (§6.5).
It is independent of the base axis: `!io` does **not** cover named effects, and io's absorption
reasoning applies to the base axis only. So an `!io` function that performs `!Ask` still has to
write `!Ask` in its signature.

Both axes are trivially decidable: the base axis is a boolean or, the label axis is union and
difference of finite sets.

### 6.2 Rules

1. The effect of a function body = the union of the effects of every call in it.
2. A function whose signature is not marked `!io`, with an io effect appearing in its body →
   compile error (the error points out which call introduced io, and suggests adding `!io` to
   the signature or eliminating that call).
3. Marked `!io` but the body is pure → allowed (room reserved for evolution); a "redundant `!io`"
   lint needs type analysis, and v0.1's `dawn fmt --check` only checks formatting — that hint is
   **not implemented** (left for later).
4. A pure function is **guaranteed**: same arguments return the same value, no observable side
   effects. The compiler may fold it, deduplicate it, and call it at comptime on that basis.
   This guarantee did **not** hold for named effects until #188: a closure built under a handler
   with an io arm could be run from a function whose signature said it was pure. The fix is the
   boundary clause in §6.5 and
   [`docs/effects-soundness-design.md`](effects-soundness-design.md).
5. `panic`/`todo`/`assert` do not count as io — they do not return (divergence is not an effect).

### 6.3 Effect polymorphism

Higher-order functions use effect variables to forward the effects of their arguments:

```dawn
fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2)
```

- An effect variable `!e` needs no declaration; appearing in a signature introduces it, and its
  scope is the whole signature. Also, **only a function signature** can introduce an effect
  variable: a function type inside a type declaration (an `alias` target, a record/variant field)
  introduces no binder, so writing `!e` there is a compile error — write `!io` or leave it pure.
- `!(e1 | e2)` is a union, stored **normalised**: `io` absorbs everything (a union containing `io`
  is `io`), `pure` is the identity (and can be dropped), and a union of a single variable degrades
  to that variable itself (`!(e|e)` is `!e`). The base axis has only two points, so solving is a
  boolean or; the label axis is set union — both are decidable. **Named effects do not take part
  in absorption**: `!(io | Ask)` is exactly `!(io | Ask)`, it does not collapse to `!io`.
- An effect variable spans both axes: `!e` can be instantiated to a row carrying labels. In
  `map(xs, x => ask())` the `!e` of `list.map` instantiates to "pure + {Ask}", so performing a
  named effect inside a `for` body goes through just as well.
- Instantiation at the call site: for `compose(inc, tag)`, if `inc` is pure and `tag` is `!io`,
  the effect union of the result type normalises to `!io`; if both are pure it normalises to pure
  and the result can be called in a pure context.
- Instantiation at the call site: in `map(xs, println)`, `e = io`, so the whole call is io.

### 6.4 Escape hatch: `unsafe_pure` (std only)

`unsafe_pure { <expression> }` is the expression block for **pure FFI**: the author guarantees the
wrapped expression is pure, and on that basis the type system **masks** its effect from `!io` **to
pure**, so one host interop call can support a pure function. For the design see
[`docs/pure-ffi-design.md`](pure-ffi-design.md).

**Not available to user code (narrowed 2026-07-30, LANG-01)**: this stamp unconditionally erases an
effect the checker had proved, and every inference that purity licenses (folding, reordering,
dropping calls) will believe it — that is a soundness hole, and `design.md`'s original verdict was
already "the unsafe escape is not opened to user code". It is legal only inside a bundled std
module (`is_std_module`); appearing in a user module is a compile error. std is the only code that
ships with the compiler, bootstraps with it and is guarded by the same N vs N−1 differential
comparison — the guarantee is only reconciled by someone if it is kept there. If a pure wrapper
really is needed outside std, it should become an std function (no escape valve: giving one would
be the same as not narrowing).

```dawn
use java "java.lang.Math"

pub fn sqrt(x: Float) -> Float = unsafe_pure { Math.sqrt(x) }   # legal only inside an std module
```

> **And std does not use it today either.** The example above used to be real code in `std/str`;
> today std has not one `unsafe_pure` and not one `use java` — those operations have become part of
> the **intrinsic contract** (§11), honoured by the backend instead of vouched for one call site at
> a time. So `unsafe_pure` has **zero use sites** in the whole ecosystem: it is kept as a mechanism
> for future std low-level wrappers, not as language surface.

What is wrapped must be a **static method call**: Dawn's native types (String/List/Bytes/Map/Set)
are not Java types, so an instance call like `s.substring(…)` does not work today
(`pure-ffi-design.md` §9).

- **It changes only the effect, it does not relax typing**: type checking and overload resolution
  inside the block proceed as usual; the only dimension covered is "effect".
- **Masking an effect variable is refused**: if an effect-polymorphic call appears inside the block
  (`!e`, such as higher-order `map`/`fold`), that is an error — masking it to pure is a lie, and
  when `e = io` even the value cannot be pinned down. This guard rail forces higher-order code onto
  the right path, "pure Dawn recursion over first-order pure primitives" (§6.3), so `unsafe_pure`
  only ever appears on the lowest-level first-order wrappers.
- **Redundant is an error**: if the block is already pure (no io) → `redundant unsafe_pure` is
  reported, which guarantees every `unsafe_pure` carries payload and that `grep unsafe_pure` is the
  complete trust list.
- **Unsoundness**: this is a hole you can lie through (the name is barbed as a warning). Mitigation
  is the greppable name + the redundancy lint + a two-layer structure that converges the guarantee
  onto a very small number of first-order primitives; the compiler does not verify Java purity (it
  cannot).
- **Transparent at run time**: codegen emits the inner expression directly, with no run-time marker
  of any kind.
- **Compile-time folding (route C) needs `--comptime-ffi`, off by default**:
  `const A: Int = unsafe_pure { Math.max(3, 7) }` folds to 7, but only when that flag is on. Two
  further restrictions: only **static** methods are reflected, and the boundary types are limited
  to `Int/Float/Bool/String/Unit`.
- **Purity and permission are two things** (split 2026-07-27): `unsafe_pure` once doubled as route
  C's licence, so "I guarantee this call is pure" got read along the way as "the compiler may run
  it inside its own process". The former is the author's assertion about the **program**, the
  latter is a demand on **the machine compiling this source** — different victims, so they should
  not share one notation. None of these three gates is a sandbox: `System.load(String)` is static,
  takes a String, returns void. So the gate is opened by **the person running the compiler**, not
  by **the source being compiled**.

### 6.5 Named effects and `with handle`

`effect` declares a set of operation signatures; the call site calls an operation directly, and the
**lexically nearest** `with handle` answers it. This tier is **tail-resumptive**: a handler arm is
an ordinary closure that is "called in place, its return value is the operation's result", with no
continuation capture. For the design and the verdicts see
[`docs/effects-design.md`](effects-design.md).

#### Declaration

```dawn
effect Ask {
  ## Ask the context for an Int.
  fn ask() -> Int
}

effect State {
  fn get() -> Int
  fn put(v: Int) -> Unit
}
```

- Effect names are UpperCamelCase and share one namespace with types and traits.
- An operation is an ordinary function signature: no body, and it **must not carry an effect
  annotation of its own** (an operation's effect is the effect it belongs to); in v1 it must not
  carry type parameters either.
- Operation names enter the module's function namespace: sharing a name with any top-level
  declaration of this module (an ordinary function / a trait method / another effect's operation)
  is a redefinition error; sharing a name with something **introduced from elsewhere** (including a
  same-named operation brought in by another effect) is an error too. The operations of a
  `pub effect` come in together with `use m.{Ask}`, and `m.ask(…)` can also be written.
- An effect itself carries no type parameters (`effect Yield[T]` is left to a later roadmap).

#### Spelling and propagation

```dawn
fn sum_three() -> Int !Ask = ask() + ask() + ask()

fn logged(x: Int) -> Int !Ask !io = {
  io.println("asking")
  ask() + x
}
```

- A named effect is written in the effect position, alongside `!io` and effect variables; several
  annotations can be stacked (`!Ask !io`), or written as a union (`!(io | Ask)`).
- Deciding what `!name` is, is a **table lookup**: `name` hits an `effect` declaration in scope →
  named effect; otherwise it is an effect variable (the old behaviour). Capitalised but not found →
  "unknown effect" is reported, because effect variables are lowercase by convention.
- Performed but nobody answers (neither declared in the signature nor handled) → the error is
  reported on **the call that performs it**, with two ways out: add the annotation to the
  signature, or `with handle` on the spot.
- On `pub fn main` and on export boundaries the labels must be empty — the "nobody answers" error
  lands on the outermost signature that still owes a label.

#### `with handle`

```dawn
fn demo() -> Unit !io = {
  with handle Ask { ask() => 42 }
  io.println("${sum_three()}")      # 126
}
```

`with handle E { arms… }` is one clause form of the `with` statement (§4.10): **the rest of the
block** lives in that handler's scope, exactly isomorphic to `with x <- f(…)`, and it inherits all
of its discipline — legal only inside a block, the rest is a real closure, `return`/`break`/
`continue` are refused (the diagnostic names `with handle`), `?` passes through transparently.

- An arm has the form `op(args…) => expression`, `=>` being the same notation as in a lambda (an
  arm is a closure to begin with), and arms are separated by newlines. Every declared operation
  gets **exactly one arm**: too few arms, too many arms, and an arm whose name does not belong to
  the effect are all compile errors.
- One `handle`, one effect; handling the same effect again is inner shadowing outer, which is legal.
- Handling an effect the block never actually performs is allowed (harmless dead evidence).
- **Typing rule**: let the rest closure's effect be `(base, L')` and each arm body's effect be
  `(base_i, L_i)`; then the block that installs the handler is recorded as
  `(base ∪ ⋃base_i, L' ∪ ⋃L_i)`.
  That `L'` is already **settled**: the rest is a closure, and a closure's row is settled at its
  **creation point** — the labels this handler answers came off there, replaced by the effects of
  this handler's arms. So this node performs no subtraction of its own. The effects the arm bodies
  perform themselves (including io, including other labels) are all unioned back onto the block —
  an arm runs where the handler is installed, not where the operation is performed.
  **"A row losing a member" happens at the closure creation point and nowhere else**, and it does
  not enter unification. It moved there from `with handle` because the capture happens at the
  lambda: subtraction and capture at one node is what keeps a label from being taken off the wrong
  function ([`docs/effects-soundness-design.md`](effects-soundness-design.md) §4.2).

#### Lexical scope

Evidence (the handler's arms) is resolved **lexically**: an operation call binds to the lexically
nearest `with handle`, and a closure captures the handler in force at its **creation point**.
Consequences:

- **The handler is the creation point's, not the call site's.** A closure built inside a handle
  block that escapes outside the block carrying that handler and is then called is still answered
  by the original handler — in the tail-resumptive tier a handler is just a piece of ordinary code,
  there is no stack magic to invalidate. The escaping closure's **type** does not say `!E`; it says
  what the arms it captured do. `E` has an answer already, and the arms are the code that really
  runs when the closure is called. The type states "what happens when you run this", not "who has
  to supply the handler" — in Dawn the caller never supplies it. So a handler with pure arms yields
  a pure escaping closure, and one with an io arm yields an `!io` one.
- Performing **this same effect** inside an arm body binds to the **outer** handler for that effect
  (it does not answer itself); with no outer one the arm owes the label and the error is reported
  as usual.

#### Boundaries (v1)

The following positions refuse named effects outright, with the same offence and the same
diagnostic as effect variables:

- **trait / impl methods**: a method's row is pure or `!io`.
- **comptime / const initialisers**: compile-time evaluation performs no named effect and cannot
  install a handler either.
- **Written function types**: `fn(…) -> T !E` is illegal in any `TypeRef` position — parameters,
  return types, `let` annotations, `alias` targets, record/variant fields, generic arguments, tuple
  elements. A written label reads as "whoever calls me supplies the handler", and Dawn's evidence is
  only ever captured by a closure at its creation point, so the spelling has no runtime meaning
  behind it. The migration is an **effect variable** (`fn() -> Int !e`), which takes both labelled
  and pure closures. A function's **own signature row** (`fn one() -> Int !Ask`) is not a `TypeRef`
  and stays legal; so does `!io`. A record field can now hold an escaping closure — its row was
  settled at the creation point.
- **Function values**: a labelled function (including an operation itself) cannot be passed
  directly as a value — evidence is a hidden parameter and a function value has nowhere to put it.
  Write it as a lambda (`() => ask()`) and the lambda captures the evidence.
- `unsafe_pure` masks io only, **not labels**: labels are the input to evidence synthesis, and
  masking one breaks the parameter.

#### Implementation (informative)

Each `effect E` makes lowering synthesise an ordinary record type (whose name the user cannot
spell), with one field per operation holding its closure; `with handle` constructs that record and
binds it to a local, and an operation call = read the field + call the closure. Every label written
out in a signature appends one hidden evidence parameter to the function, **placed after the
dictionary parameters**, in ascending effect id order. Labels that flow in through an effect
variable synthesise no parameter — in that case the evidence sits in the closure's capture, so
higher-order library functions (`list.map` and its ilk) need zero changes.
The other half of the evidence flow is its dual: a closure settles its own row at the creation
point, against the evidence it captured. A signature synthesises the parameter, a closure captures
the evidence; only the two together are the whole flow — one decides who supplies, the other who
owns up.

---

## 7. comptime

### 7.1 Form

```dawn
const CRC_TABLE: List[Int] = comptime { crc32_table() }

fn lookup(d: Int) -> Float =
  SIN_TABLE.get(d % 360).expect("table covers 0..360")
```

`comptime { ... }` is an expression: it is evaluated at compile time by the compiler's
built-in interpreter, and the result is embedded in the output as a constant. The
right-hand side of a top-level `const` is implicitly in a comptime context.

### 7.2 Constraints

1. comptime code **must be pure** (it may call any pure function, including those of this
   module and of dependency modules).
2. The result type must be **constant-serialisable** — that is, the compiler can rebuild
   the value at class initialisation time: `Int`/`Float`/`Bool`/`String`/`Unit`, plus
   `List`/tuples/records/ADTs made only of those. Function values are not allowed.
   **An opaque type is as serialisable as its target** (§2.7).
   `Map`/`Set` are not allowed for now: they are HAMTs over `Array`, and the comptime
   interpreter has no `Array` primitive; `List` works because the interpreter carries its
   own list representation, not because it can run `std/pvec`.
3. Evaluation has a step budget (10⁸ steps by default, tunable with `--comptime-fuel`);
   exceeding it is an error — which guarantees compilation always terminates.
4. There is no Java interop and no io inside comptime (constraint 1 guarantees this
   automatically).

### 7.3 Explicitly out of scope

comptime **cannot** generate types, cannot generate declarations, and cannot introspect
the AST. It is only "run a piece of pure Dawn code ahead of time". Metaprogramming is not
a goal for v0.1.

---

## 8. Error handling

### 8.1 Recoverable: Result / Option + `?`

```dawn
fn parse_config(path: String) -> Result[Config, String] !io = {
  let text = read_file(path)?          # on Err, return that Err early
  let json = json.parse(text)?
  Config.from_json(json)
}
```

- The postfix `?` applies to `Result[T, E]`: `Ok(v)` unwraps to `v`, `Err(e)` makes
  **the current function** return `Err(e)` immediately. Likewise for `Option[T]` (`None`
  returns `None` early).
- The return type of the function containing the `?` must be a compatible
  `Result`/`Option` (the `E` types must agree; v0.1 has no automatic error-type
  conversion).
- This is the only non-local control flow in v0.1.

**Across error types: write a local helper, don't wait for the language to give you one.**
`?` requires `E` to agree, so a function returning `Result[_, HttpError]` cannot `?` a
`Result[_, String]` directly. The fix is a 4-line function at the boundary:

```dawn
fn as_http[T](r: Result[T, String], status: Int) -> Result[T, HttpError] =
  match r { Ok(v) -> Ok(v)
            Err(m) -> Err(http_error(status, m)) }
```

After that `let rows = as_http(repo_call(...), 500)?` is all it takes, and `?` handles the
rest.

> A `map_err` was once added to std for this, and reverted on 2026-07-19: of the 102
> cross-layer `match`es in dawnop-site, 94 came apart with "`?` plus the helper above"
> (another 8 already had the same error type and needed no helper at all), and the entire
> effect of `map_err` was to shrink that helper from 4 lines to 1, once per project. What
> actually untangled those 102 sites was `?` and a local helper, not a new library
> function.

`?` inside a lambda returns from that lambda, so bridges inside closures can collapse the
same way.

### 8.2 Unrecoverable: panic

`panic(msg)`: prints the message and a Dawn-level stack trace; the process exits non-zero.
`todo()` is equivalent to `panic("not yet implemented")` and passes any type check (its
return type is the bottom type `Never`).

**Postfix `!`**: `o!` unwraps `Option[T]` into `T`, and panics on `None`. The semantics are
those of `expect(o, msg)`; the only difference is that **the message is generated by the
compiler** — it contains the call that produced the `None` and the source location
(`unwrapped None from URI.create() at src/http.dawn:23`), so there is no need to invent a
placeholder string for it.

```dawn
let uri = URI.create(url)!                      # instead of .expect("uri")
let base = HttpRequest.newBuilder()!.uri(uri)!  # instead of .expect("b") / .expect("b-uri")
```

The reason `!` exists is exactly §9.2: Java **wraps every reference return in `Option`**,
while the vast majority of JDK methods never return null in practice, so unwrapping is the
normal case.

- Applies to `Option` only. For `Result`, propagate with `?` (§8.1) or use `match`.
- Same precedence as `.`/`[]`, left-associative: `a()!.b()!` is `((a()!).b())!`.
- A line may end in `!` — it is not a binary operator, so it does not trigger a line
  continuation (§1.7). In `x! != v`, `!=` is still a single token (longest match wins when
  splitting), and the comparison is on the unwrapped value.
- **When there really is something to say**, still use `expect(o, "reason")` — that is what
  it is there for.

`get`/`map.get` return `Option` (enquiry); the subscript `c[i]` panics on an out-of-range
index or a missing key (assertion, §4.8; the semantics are fixed by that type's `Index`
impl, `List`/`Map` as above); `Int` division by zero (`/` and `%`) panics — being a panic,
`catch_fault` does not intercept it (§4.3, numeric edge semantics).

---

## 9. Java interop

### 9.1 Importing and calling

```dawn compile
use java "java.nio.file.Files"
use java "java.nio.file.Path"
use java "java.lang.StringBuilder"

fn slurp(p: String) -> Option[String] !io =
  Files.readString(Path.of(p).expect("valid path"))

fn build() -> String !io = {
  let sb = StringBuilder.new()      # constructors are always spelled .new
  sb.append("a")
  sb.append("b")
  sb.toString().expect("non-null")
}
```

- `use java "fully.qualified.Name"` imports the class as: one opaque type plus one
  namespace of static methods. **Read-only static fields are accessible**: `Class.FIELD`
  (constants are upper case by convention, e.g. `Integer.MAX_VALUE`, `Math.PI`, the enum
  constant `TimeUnit.SECONDS`; a lower-case field name is just as readable, e.g.
  `System.out`) reads that field — the value is mapped by §9.2 (a reference type is
  wrapped in `Option` and needs `!` to unwrap, primitives such as `int`/`double` are
  widened), and the effect, as for all interop, is `!io`. Read-only (there is no
  `Class.FIELD = v`); instance fields and non-`pub` static fields are not accessible.
- **The member name after `.` may be any "word"**, including names that coincide with
  Dawn keywords (`in`/`type`/`match` and so on): Java has members named those, and after
  a `.` a keyword is unambiguous and is always taken as a member name. So `System.in`
  (the field name `in` is a keyword) and `obj.type()` (the method name `type`) can both
  be written directly, with no detour through reflection.
- Constructors are uniformly `Type.new(args)` and **return `T` itself** (a constructor
  never returns null, so it is not wrapped in Option); instance methods use
  `.method(args)`.
- **Every Java call has effect `!io`**, without exception (the reasoning is in
  design.en.md D5).
- **The return value of a Java call may be discarded** (in statement position, or in the
  tail position of a Unit block) — Java APIs often return `this` or a status code; the
  "must not be silently discarded" rule only protects Dawn values.
- When an **unimported reference class** turns up in a return value (such as the `Path`
  of `Path.of`), the value is still usable (it automatically becomes an opaque type and
  can still be chained on); `use java` is only needed in order to **write the type name**
  in a signature.
- Class resolution happens by **reflection at compile time**: JDK classes are always
  visible; a third-party class must be supplied with `--cp <jars>` (common to
  `dawn run/test/build`, §12.1), and compilation and execution share one classpath. LSP
  v0.1 only resolves JDK classes; a third-party class is reported as not found in the
  editor but compiles on the command line.
- **Nested classes are written with a dot**:
  `use java "java.net.http.HttpResponse.BodyHandlers"` (not `$` — `$` inside a string is
  taken as interpolation). Resolution first reflects on the whole name, and on failure
  retries with `.` replaced by `$` one at a time from right to left, so any nesting depth
  can be written with dots; the bound name is the last segment (`BodyHandlers`). The
  **generic methods** of a nested class still return an opaque `Object` after erasure
  (§9.2) — `HttpResponse.body()` for instance returns `Object`, and a string body is
  bridged back with `String.valueOf(...)`.

### 9.2 Type mapping

| Dawn | Java | Direction |
|------|------|------|
| `Int` | `long` (an incoming `int` is widened automatically) | both ways |
| `Float` | `double` | both ways |
| `Bool` | `boolean` | both ways |
| `String` | `java.lang.String` | both ways |
| `Unit` | `void` | return |
| an imported class `T` | a reference to that class | both ways |

**A Java method returning a reference type is always `Option[T]`** — null is stopped at
the boundary. Unwrap with `!` (§8.2) or handle it with `match`:

```dawn run
use java "java.net.URI"
use java "java.lang.StringBuilder"

pub fn main() -> Unit !io = {
  let uri = URI.create("https://dawn-lang.org/spec")!   # method: wrapped in Option, unwrapped
  let sb = StringBuilder.new()                          # constructor: not wrapped, the object itself
  sb.append(uri.getHost()!)
  println(sb.toString()!)
}
```

```output
dawn-lang.org
```

**Why methods are wrapped and constructors are not** — these are not two arbitrary
rules; each has its basis:

- **Constructors are not wrapped**: the JLS guarantees that a `new` expression **never**
  returns null, so wrapping it in `Option` is pure noise.
- **Methods are wrapped**: a method **can** return null, and the compiler **has no way
  to tell statically**. JDK classes carry no nullability annotation visible at runtime —
  `URI.create` (never null) and `Map.get` (genuinely nullable) both reflect out with
  **nothing**. Since they cannot be told apart, everything is wrapped: better to let `!`
  carry the risk explicitly than to let null into Dawn.

Primitive return values are not wrapped in Option; a `short`/`byte`/`int` return is
widened to `Int` automatically, `float` to `Float`. `char` in argument and return
position is not supported in v0.1; arrays go through as opaque values (§9.5). **Passing
null for an `Option` argument** is deferred likewise (v0.1 cannot pass null from the
Dawn side to Java).

### 9.3 Overload resolution

A unique candidate is picked by scoring on "argument count + static type" (an exact
match on `long`/`double` beats narrowing to `int`/`float`, `String` beats
`CharSequence`/`Object`); a tie for the highest score, and no candidate at all, are both
compile errors (the message lists the candidate signatures). A function-value argument
only matches a functional-interface parameter (§9.4); a Dawn `List` argument can match a
`List`/`Collection`/`Iterable` parameter (§9.6); an exact array match beats widening to
`Object` (§9.5).

**Varargs** follow the JLS in two phases: one round **without packing** first (phase 1),
and only if all of that fails, **packed as varargs** (phase 2); **phase takes precedence
over score** — the score is summed per argument and grows with the argument count, so
without phases a packing candidate would overtake an exact match. The variable part is
spread out inline, as it is written in Java:

```dawn run
use java "java.nio.file.Path"
use java "java.util.List"
use java "java.lang.String"

pub fn main() -> Unit !io = {
  let p = Path.of("a", "b")!                     # one trailing segment: packed into String[1]
  let q = Path.of("a", "b", "c")!                # same phase, String[2]
  let l = List.of("a", "b")!                     # phase 1 wins: of(E, E) is chosen
  let m = List.of("a", "b", "c")!                # phase 2: packed into E[]
  let e = List.of()!                             # no variable part = pack 0 = empty array
  println("${p.toString()!} ${q.toString()!}")
  println("${String.join(",", l)!} ${String.join(",", m)!} ${to_string(e.size())}")
}
```

```output
a/b a/b/c
a,b a,b,c 0
```

The variable part takes Java references too (`BodyPublishers.concat(head, file, tail)!`).
The trailing arguments are scored one by one against the **array component type**, by
the same rules as an ordinary parameter, so SAM conversion (§9.4) and the List bridge
(§9.6) are equally available inside the variable part. Passing a **ready-made array** as
the variable part (a `String[]`, say) goes through phase 1 and is passed as is, not
repacked. Note that scalars are not boxed (§9.2), so `Object...` takes `String` and Java
references but **cannot take `Int`/`Float`/`Bool`**; `char` is unsupported in argument
and return position, and `char...` with it.

### 9.4 SAM conversion: function values across the boundary

```dawn
use java "java.lang.Thread"

fn spawn_hello(msg: String) -> Unit !io = {
  let t = Thread.new(() => println(msg))   # Dawn lambda → java.lang.Runnable
  t.start()
  t.join()
}
```

- When a Java parameter is a **functional interface** (an interface with exactly one
  abstract method; the public methods of `Object` do not count), the argument may be a
  Dawn function value — a lambda, a named function or a constructor value all work.
  Interfaces only; an **abstract class** with a single abstract method is not supported
  (the implementation goes through LambdaMetafactory, expanded at build time, zero
  configuration for native-image).
- **Matching**: the SAM method signature is mapped to a Dawn function type by §9.2 and
  then matched as usual; a lambda's parameter types can be seeded from the parameter (the
  same mechanism as generic argument inference). In overload scoring a function value
  only matches functional-interface parameters. Dawn does not track Java generic
  arguments, so the parameters of a **generic SAM** (`Predicate`/`Function` and the like)
  enter Dawn with their erased types (usually an opaque `Object`, which can only be
  passed along as is); only a SAM with concrete types (`Runnable`, `HttpHandler`) gives
  the full experience.
- **No restriction on effects**: pure functions, `!io` functions and effect-variable
  functions can all be handed out. The effect system does not track when the Java side
  calls — Java may call that function value on any thread at any moment (including after
  this call has returned). This does not break the purity contract: Java code can only
  run underneath a Dawn `!io` call, or on a Java thread with no Dawn stack, and no pure
  function's signature promise is violated.
- **The null boundary for parameters**: a callback's reference-typed parameters are
  **not wrapped in `Option`**, they arrive as `T`; the bridge layer checks each one, and
  a null passed in by Java panics immediately (the message names the callback boundary).
  This is complementary to wrapping return values in `Option` (§9.2): null in return
  position is normal and therefore goes into the type, null in a callback parameter is
  pathological and therefore fails fast.
- **Narrowing return values**: when the SAM method wants an `int` and the Dawn function
  returns `Int`, a **checked narrowing** is done — out of range panics, it is not
  silently truncated; when it wants a `float`, `Float` is narrowed by the IEEE rules
  (precision may be lost, which is floating-point semantics, not overflow).
- A Dawn function that panics inside a callback is handed to the Java caller as
  `dawn.rt.PanicError` (a subclass of `Error`), neither caught nor wrapped.

### 9.5 Arrays: opaque pass-through; `byte[]` = first-class `Bytes`

An array value is treated the same as an unimported reference class (§9.1): it can be
**received, held and passed on** — overload scoring matches the array type exactly, or
widens to `Object`; in return position it is wrapped in `Option` per §9.2. But an array
(except `byte[]`, see below) is **unnameable** (the type cannot be written in a
signature), **cannot be created and cannot be indexed**; for its length use
`Array.getLength(a)` from `use java "java.lang.reflect.Array"`.

**`byte[]` is the one exception: it is the first-class type `Bytes`** (§9.5.1). A
concrete `byte[]` returned by a Java method (`readAllBytes`/`toByteArray`/`Base64.decode`
/`MessageDigest.digest`) lands as `Option[Bytes]` per §9.2; `Bytes` can be written in a
signature, stored in a record, sliced/indexed/concatenated/compared by content; passed
back the other way it matches a Java `byte[]` parameter (`OutputStream.write`,
`MessageDigest.isEqual` and so on) directly.

```dawn
use java "java.nio.file.Files"
use java "java.nio.file.Path"

fn slurp(p: String) -> String !io = {
  let bytes: Bytes = Files.readAllBytes(Path.of(p).expect("path")).expect("readable")
  decode(bytes, "UTF-8")
}
```

#### 9.5.1 `Bytes`: a first-class immutable byte sequence

`Bytes` is an immutable sequence of bytes, at runtime a bare `byte[]`. The library
functions (§11, the "bytes" group): `utf8(s) -> Bytes` (the UTF-8 bytes of a string),
`decode_utf8(b) -> String` / `decode_latin1(b) -> String` (decoding, see §11),
`bytes.len`, `bytes.at(b, i) -> Int` (0..255, out of range panics),
`bytes.slice(b, start, end)` (`[start,end)`, subscripts clamped into range),
`bytes.index_of(b, needle, from) -> Option[Int]`. `Bytes ++ Bytes` concatenates,
`==`/`!=` compare by **content** (`Show` renders a `<N bytes>` summary). The hash of
`Bytes` is a **content** hash (seed `1`, byte by byte `h = 31*h + the signed byte`,
wrapping at 32 bits, see §3.5 — the same shape as the composite rule there), consistent
with `==` on content, so `Bytes` **can** be a Map/Set key. (It was once forbidden because
the JVM `hashCode` of `byte[]` is reference identity; after both ends were changed to
content the ban did not get withdrawn along with them, and was withdrawn on 2026-07-27.)
`Bytes` does not take part in comptime constant folding, and cannot be a bare first-class
function value either (wrap it in a lambda).

**Narrowing an opaque value back to a concrete reference parameter**: the return of an
erased generic (§9.2) lands as an opaque `Object`, but real code often needs to **feed it
straight back** into some Java parameter that wants a concrete reference type — for
example the `Object` that `HttpResponse.body()` yields with `BodyHandlers.ofByteArray()`
is really a `byte[]`, and has to be written into `OutputStream.write(byte[])`. Overload
resolution therefore lets an opaque `Object` argument match a concrete reference
parameter, with one runtime `CHECKCAST` inserted at the bridge (a failure is a
`ClassCastException` passing through, not silence). This is the opposite of, and paired
with, "widening to `Object`" in §9.3: widening throws type information away on the way
out, narrowing claims it back at runtime. An opaque value is still **unnameable and
unindexable** — narrowing only happens in the implicit adaptation where an argument
crosses the boundary, and Dawn code never gets hold of that type's name. This lets a
pipeline like "take the binary body → pass it straight through" avoid reading the bytes
into a Dawn value (one whole copy saved, so a large file does not blow up memory).

If you know for certain that some opaque `Object` from an erased generic is at runtime a
particular concrete reference type (such as `byte[]` when `HttpResponse.body()` is paired
with `BodyHandlers.ofByteArray()`), use the generic builtin
`cast[T](x: Object) -> Result[T, ForeignError]` to **claim** it as that type (T is taken
from the expected type at the call site, e.g.
`let b: Result[Bytes, ForeignError] = cast(...)`) — the claim does one runtime
check, and **a type mismatch is an `Err`, not an exception passing through**; for the
payload see §9.8.1 (on the JVM the `kind` is `java.lang.ClassCastException`). T must be a
reference type (a primitive, or no expected type, is rejected at compile time).

> **A function with a pure signature should not be able to exit through a host
> exception** (LANG-02) — `cast` used to throw `ClassCastException`, which is exactly the
> exit a pure signature is supposed to exclude. Failure is now a value. The three stages
> the migration went through (including a transitional spelling that lived for exactly
> one release) are recorded in `docs/audit/error-model-design.md` §6.10–§6.12, and it is
> closed.

### 9.6 The List bridge: a Dawn `List` reaches a collection parameter directly

When a Java parameter is declared `java.util.List` / `java.util.Collection` /
`java.lang.Iterable`, the argument may be a Dawn `List[T]`. **Zero-copy**: the bridge
wraps it in an unmodifiable view (`Collections.unmodifiableList`), and the mutating
methods on the Java side throw `UnsupportedOperationException` — the same convention as
Scala's `asJava` and Clojure's persistent collections.

- The element type `T` is limited to: `Int` / `Float` / `Bool` / `String` / an imported
  or opaque reference class. An element that is a `List`/`Map`/`Set`/ADT/tuple/record/
  function value is rejected (a compile error) — zero-copy on a nested container would
  leak the inner mutability, and v0.1 does not do deep wrapping.
- Elements arrive in the boxed representation of §9.2 (`Int` → `java.lang.Long`). Generic
  erasure means an API expecting `List<Integer>` will `ClassCastException` when it reads
  them; v0.1 does not rescue that, so pick your APIs with care.
- The direction is Dawn → Java only; a collection returned by Java is still an opaque
  reference plus `Option` (§9.2), and can be chained on. A `Map`/`Set` bridge is not
  provided in v0.1.

### 9.7 Limits

Java classes cannot be inherited from; Java interfaces cannot be implemented as a **named
class** — handing a function value out through SAM conversion (§9.4) is the only path.
Read-only static fields are accessible (`Class.FIELD`, §9.1) — enum constants and static
constants are read directly (`TimeUnit.SECONDS`, `Integer.MAX_VALUE`); writing a static
field, and instance fields, are still unsupported. Arrays cannot be created, indexed or
named (§9.5); `Map`/`Set` are not bridged, and Java collections are not converted back
into Dawn values (§9.6); passing null for an `Option` argument is unsupported (§9.2).

### 9.8 The foreign-failure barrier: `catch_fault`

> Up to v0.30.0 this builtin was called `java_try`; v0.31.0 renamed it. What it
> intercepts is a **fault** — a failure caused by the outside world — and ever since
> native grew failure kinds that classification has been shared by both backends
> (native-backend-plan §14.9) and has nothing to do with Java; the name outlived its
> reason by a while. The old name gets you "`java_try` is not a builtin; renamed to
> `catch_fault`".

Dawn has no exceptions: an exception thrown by a Java call passes through unchanged by
default and terminates the program (panic semantics). But **an expected foreign failure**
(the network drops, a SQL constraint is violated, a parse fails) is expressed in the Java
world as an exception; those are not bugs and belong in a `Result`. The builtin
`catch_fault` is the one conversion point:

```dawn
use java "java.lang.Long"

fn parse(s: String) -> Result[Int, ForeignError] !io =
  catch_fault(() => Long.parseLong(s))
  # Err(ForeignError { kind: "java.lang.NumberFormatException", message: ..., cause: None })
```

- Signature `catch_fault[T](f: fn() -> T !io) -> Result[T, ForeignError] !io`; the
  closure may be pure.
- It only intercepts `java.lang.Exception` and its subclasses; `Error` is not intercepted
  — **a Dawn panic (`dawn.rt.PanicError` is a subclass of `Error`) passes through
  unchanged**, a panic is still a bug and is not recoverable.
- The `Err` payload is a `ForeignError` — a prelude record whose fields and values are in
  §9.8.1. Up to v0.32.0 it was a single **rendered string** (`Throwable.toString()`), and
  this section also used to advise "match the string by prefix when you need to tell
  exception kinds apart"; that advice is withdrawn, and `kind` is its replacement.
- Failures inside the boundary propagate as usual: wrapping `catch_fault` around a whole
  compound call is enough, there is no need to wrap call by call.

The companion `catch_panic[T](f: fn() -> T !io) -> Result[T, ForeignError] !io`
intercepts **two kinds, a Dawn panic (`PanicError`) and `Exception`** — not any
`Throwable`: `VirtualMachineError` (heap exhausted, stack overflow) passes through,
resource exhaustion is not a value. It is for a **supervision boundary** — one request on
a server, one execution of a task runner: a panic in one request should become a 500 and
be logged, rather than take down the whole connection or process. Its division of labour
with `catch_fault` is clear: `catch_fault` handles **expected foreign failure** and lets
panics through; `catch_panic` is an **isolation point**. Ordinary business failures still
go through `Result` — do not use `catch_panic` as routine error handling.

> **This division of labour is backend-independent.** The JVM gets it for free from the
> class hierarchy (`Error` versus `Exception`); native has no exceptions, every failure
> travels the same `longjmp`, so a failure carries a **kind** and a handler remembers
> whether it takes panics. The criterion is one and the same: **a failure the language
> defines itself is a panic** (`panic`, `expect`, an out-of-range subscript, division by
> zero, an illegal code point), **a failure caused by the outside world is not** (the io
> primitives — counted up, that is the only such class). The measured comparison of the
> two backends is in `scripts/spike-native/catch_kinds.dawn`; before it was written,
> native's `catch_fault` intercepted every panic that should have passed through.

#### 9.8.1 The payload `ForeignError`

"Match the string by prefix" used to be this section's advice and is now **withdrawn**:
it builds control flow on one piece of text that can be refactored, localised, or changed
by the next JDK. The payload is a prelude record:

```dawn
type ForeignError = { kind: String, message: String, cause: Option[String] }
```

- `kind` is **the name the backend itself gives to that class of failure**, and it is a
  **name**, not a rendering: on the JVM it is the binary name (`getClass().getName()`,
  e.g. `java.lang.NumberFormatException`, `dawn.rt.PanicError`), on native it is the
  runtime's failure kind (`"panic"` / `"fault"`).
- **Code that dispatches on `kind` is backend-dependent code.** The only portable match
  is the `Ok`/`Err` level. The table of values and the reasoning are in
  `docs/runtime-intrinsics-design.md` §12.4.
- `message` is what the failure says about itself (the JVM's `getMessage()`, the empty
  string if there is none); `cause` is the rendering of the failure underneath, `None` if
  there is none. No stack: rendering a stack costs something at every single barrier.

There is only this one pair of barriers (only this pair **intercepts** failure; the
`bracket` of §9.8.2 intercepts nothing), only the `ForeignError` payload, and **the
String version is not kept**.

> **History**: moving the payload from String to `ForeignError` took three releases,
> because a builtin's **signature** is bound by seed discipline just as its name is, and
> more tightly — a rename can have both tables know two spellings within one stage, a
> payload type cannot: the compiler's own call sites cannot satisfy a
> `Result[T, String]` table and a `Result[T, ForeignError]` table at the same time. So
> the new shape landed first under the transitional spellings
> `catch_fault_e`/`catch_panic_e` with zero call sites (v0.32.0); one release taught the
> previous generation of the compiler about them; the call sites moved and the entries
> under the original names were flipped (v0.33.0); then the call sites moved back to the
> original names and the transitional spellings were deleted (this release). That pair of
> names appeared in `dawn doc --builtins` for v0.32.0/v0.33.0 and does not exist after
> that. The staging is in `docs/audit/error-model-design.md` §6.

#### 9.8.2 Releasing, not intercepting: `bracket`

Dawn has no `try`/`finally`, and does not intend to (the pair of barriers in §9.8
**intercept**, they do not **release**). "Whichever way you leave, hand the resource
back" is carried by a third builtin:

```dawn
fn bracket[A, B](resource: A, release: fn(A) -> Unit !io, use: fn(A) -> B !io) -> B !io
```

```dawn
let f = FileOutputStream.new(path)          # acquire the resource: ordinary code, before the call
bracket(f, s => s.close(), s => write_all(s, bytes))
```

**The resource is a value, not an acquire closure.** Haskell's `bracket` takes a thunk in
order to close the window for asynchronous exceptions — another thread or a timer could
interrupt between "acquired" and "handler installed". Dawn has no such thing: a failure
is only raised from code the program itself calls, and between evaluating the arguments
and this builtin installing its handler none of the caller's code runs, so a thunk closes
no window at all (Koka's `finally` is the same, and likewise takes the resource
directly). **Acquiring the resource is therefore ordinary code before the call** — a
failure there needs no release, because nothing has been acquired yet.

**`use` comes last** to leave the road open for `with` (§4.10, landed 2026-07-31): that
sugar attaches "the rest of the block" as the **last** argument, so a primitive with
`use` in the middle would have to be respelled. Once the resource is acquired up front,
such a site does not need a single lambda:

```dawn
with f <- bracket(open(path), close)
...the rest of the block is the use...
```

Three guarantees:

- **`release` runs exactly once on every path** — `use` returning normally, panicking,
  faulting; all three run it, and run it only once.
- **The original failure keeps propagating unchanged**: `kind`/`message` verbatim, **a
  panic is still a panic and a fault is still a fault**. So `catch_fault` still does not
  intercept a panic that passes through bracket (on native that kind bit is restored by
  re-raising, not re-inferred; the measured comparison of the two backends is in
  `scripts/spike-native/bracket.dawn` and `bracket_fatal.dawn`).
- **`bracket` intercepts nothing**, so it returns `B` and not `Result` — guarding and
  intercepting are two orthogonal things (neither Haskell's `bracket`, Kotlin's `use`,
  Koka's `finally` nor Go's `defer` returns a Result). To take the failure as a value,
  write `catch_fault(() => bracket(...))`; each of the two primitives does one thing.

> It gets no surface syntax like `defer`: the protected region is always **one closure
> call**, so `return`/`?`/`break` cannot cross out of it at the language level, and the
> compiler owes no escape rewriting. The criteria, and the earlier conclusion they
> overturned, are in `docs/core-move2-design.md` §2.6 and §6.

---

## 10. Module system

### 10.1 Files and module paths

One `.dawn` file = one module. The module path = the path relative to the **module root**
with the extension dropped: `<root>/json/lexer.dawn` → module `json/lexer`. Every segment
of the path must match `[a-z_][a-z0-9_]*` (the same as the file name), otherwise it is a
compile error.

**How the module root is determined**:

- **Directory mode** `dawn run|test|build <dir>`: root = `<dir>/src`, entry =
  `<dir>/src/main.dawn` (if it is missing, the compiler reports it and prints the expected
  path).
- **File mode** `dawn run|test|build <file.dawn>`: starting from the file's directory,
  **walk up to the nearest ancestor directory named `src`** and take that as the root; if
  there is none, the root = the file's own directory. The LSP uses the same heuristic, so
  opening a single submodule file on its own still resolves its `use`s relative to the
  root.

**The directory convention is the project definition**: the module root, the entry and the
module paths are all decided by the directory structure; no manifest file is needed.

A project **may optionally** carry a `dawn.toml`, which holds only what the directory
convention cannot express — project identity and dependencies. A project without one works
exactly as described above. The contents of schema 1:

```toml
schema = 1                                      # must be the first key
name = "backend_dawn"                           # project identity ([a-z_][a-z0-9_]*)

[java-deps]                                     # Maven deps, for `use java`
sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"      # exact coordinates; no SNAPSHOT, no ranges

[deps]                                          # Dawn source packages: alias = local dir
web = "../packages/web"

[deps.json]                                     # or a remote archive (zip / tar.gz)
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.7.0.zip"
version = "1.0.0"                               # strict x.y.z; version solving = MVS
hash = "d1:<sha256>"                            # content hash of the unpacked file tree
subdir = "packages/json"                        # package root inside the archive (optional)
```

An alias in `[deps]` is only **how this side's source spells it** (`use <alias>/<module>`);
a package's identity is the `name` in its own manifest — the class-name namespace, version
solving and one-name-one-copy across the whole program all go by the real name, and an
aliased import is normalised to the real name at load time. `dawn add <coordinate|url|path>`
can write these entries for you (fetching the archive and computing the hash, preserving
hand-written formatting).

`dawn run|test|build` fetches `[java-deps]` (including those declared by each dependency
package — the union) and puts them on the classpath (merged with `--cp`); `dawn build`
additionally copies them into a `lib/` next to the jar. The repository address comes from
`$DAWN_MAVEN_MIRROR` and does not go into the manifest.

**A manifest is always data, never code** — there is no executable `build.dawn`. The
reasoning and the full design are in [`package-design.md`](package-design.md).

### 10.2 Imports

```dawn
use json/lexer                 # whole-module import; alias = last segment lexer, qualified access lexer.next(...)
use json/lexer as jl           # explicit alias, qualified access jl.next(...)
use json/value.{Json, render}  # selective import, used unqualified
use java "java.lang.Math"      # Java interop (§9), form unchanged
```

- A module's **whole-module** import and its **selective** import may each appear at most
  once, and the two may coexist — one binds an alias, the other binds names; they are two
  different acts. The same form twice is an error (two selective imports count even when
  the braces name different items).
- `use` may appear anywhere at the top level (the same as `use java`), and `dawn fmt` does
  not reorder them.
- **`as` renaming**: a whole-module import can name its alias explicitly with
  `use a/b/c as name` (the default alias = the last segment). `as` is a **contextual
  keyword** (special only after a whole-module path, not a reserved word, still usable as
  an ordinary identifier); it applies only to whole-module imports, selective imports do
  not need it. If two whole-module imports share a last segment, giving them different
  `as` aliases lets them coexist (otherwise the same last segment → error).

### 10.3 Name resolution (disambiguation rules)

- The alias of a whole-module import lives in **the same namespace** as this module's
  top-level declarations, local bindings and parameters: **declaring any top-level
  fn/type/const, local or parameter with the same name as a module alias is a compile
  error** ("`lexer` shadows the imported module `json/lexer`"). Hence `lexer.next(x)` is
  never ambiguous — `lexer` is either a binding (a UFCS dot call, §4) or a module alias
  (qualified access), and it can never be both.
- Qualified access supports `alias.fn(args)` in **expression position** (calling a pub
  function) and `alias.T[...]` in **type position** (LANG-06, 2026-07-30): a lower-case
  name in type position can only be a module alias, so there is no ambiguity; it may point
  at an exported ADT/record or a `pub alias` (the latter expands according to the declaring
  side's resolution). **Pattern position** likewise supports qualified constructors
  `m.C(..)` / `m.Pt { .. }`: a lower-case name followed by `.Uppercase` in a pattern can
  only be a module alias. **Qualified constants `m.NAME` and qualified constructors
  `m.C(..)` / `m.C` (expression position) are available too** (same day): this module may
  have a constant or a constructor of the same name and the two do not interfere — in Core
  the identity of a constant is (declaring module, name), not the name; a qualified
  constructor goes through the same checks as the unqualified spelling, so field names,
  arity, spread and generic instantiation all behave identically.
- Selectively importing a `type` also imports **all of its constructors** (matching the
  rule that `pub type` exports the constructors and fields).
- A selectively imported name clashing with a top-level declaration in this module or with
  another import → error. **Clashing with a prelude name**: a selective import **may**
  shadow a prelude name (you asked for that name verbatim, the intent is clear),
  **including the method names of prelude traits**; **top-level fns / trait methods /
  effect operations** may likewise shadow builtins, std and **prelude trait methods**
  (Rust-style) — the resolution order is this module's declarations → std → builtins.
  Shadowing applies only to **that one spelling**: the shadowed spelling is unreachable in
  that module, and that is the declarer's own choice. Operators and sugar (`==`, `${...}`,
  `for..in`) find their impl by trait, **not by name**, and are therefore **unaffected by
  shadowing** — shadowing `show` does not change what `${x}` prints, shadowing `iter_next`
  does not change how `for..in` behaves.
  But the **type / trait** names of the builtins and the prelude (`Map`/`Option`/`Ord`…)
  still cannot be redefined.

### 10.4 Visibility

All declarations are module-private by default; `pub` exports `fn`/`type`/`alias`/`const`
(`pub type` brings the constructors and fields with it, see §3.3). Accessing or importing a
non-`pub` item → error (`` `parse` is private to module json/parser ``, with a hint: add
`pub`).

> **Load scope (2026-07-30, LANG-07)**: `dawn run/test/build <dir>` loads **every** module
> under `src/` by default — modules that are never referenced are checked too (bit-rot
> protection, and that is the right default). `--closure` narrows it to "the use closure of
> the entry `src/main.dawn`", for large projects producing an artifact; `dawn check` is
> always whole-repo. Recommended for CI: `dawn check` guards the whole repo and
> `dawn build --closure` produces the artifact. `dawn check` exits 1 on any diagnostic
> (§12.1), so the exit code alone is enough to act on that recommendation.

### 10.5 Compilation units and evaluation order

- **Directory mode loads every `.dawn` file under `src/`** (not just the `use` closure):
  modules that are never referenced must type-check too (bit-rot protection), and their
  test blocks are run by `dawn test` as well.
- The `use` dependency graph **must not contain a cycle**; the error prints the cycle
  (`json/a → json/b → json/a`).
- Type checking and comptime evaluation proceed in **topological order** of dependencies; a
  `const` referenced across modules is already evaluated before the using side is.
- Type identity: one `type` declaration is one type across the whole program (each file is
  parsed/checked exactly once).
- Entry: the main module's `pub fn main() -> Unit !io`.

### 10.6 The bundled standard library and the prelude

The standard library is **Dawn source bundled with the compiler**, organised as real
modules ([`stdlib-naming.md`](stdlib-naming.md)): `std/str`, `std/fmt`, `std/bytes`,
`std/io`, `std/list`, `std/map`, `std/set`, `std/cursor`, `std/char`.
There are two further **internal modules**, `std/hamt` and `std/pvec` — the representations
of `Map`/`Set`/`List` (§11). They are bundled along with std and reference each other
inside std, but **`use std/hamt` / `use std/pvec` outside std is a compile error**: the
representation has to be replaceable wholesale, and being replaceable requires that no
program depends on it.
(`std/fmt` is where number rendering and parsing are implemented — `fmt.dtoa` is
`to_string(Float)` (§4.3); the implementations of the three `parse_*` (the EBNF in §11) are
**not exported**, the builtin spelling is the only way to write them, and
`fmt.atoi`/`fmt.atod`/`fmt.atoi_radix` are not names you can write. The module name exists
because the implementation is a piece of ordinary Dawn source rather than some backend's
host method, not because it is an API layer.)
`use std/x` resolves to a resource inside the compiler jar rather than to disk (the
`src/std/` path on disk is **reserved**; putting a file there is an error); after that it
behaves exactly like an ordinary module import — qualified access `map.insert(m, k, v)`,
selective import `use std/list.{find}` (§10.2/§10.3). The same short name can coexist
across modules (`str.len` / `bytes.len`), disambiguated by qualification or by selective
import.

The **prelude** is the high-traffic core of that, implicitly available without a `use`: the
constructors of `List`/`Option`/`Result`, `println`/`print`, `map`/`filter`/`fold`, the
`sort` family (std/list), and the builtin `len`/`get`/`range`/`to_string`/`join`/`parse_*`/
`panic`/`todo`/`expect`/`unwrap_or`/`cast`/`catch_fault`/`catch_panic`/`bracket`/`args` and
the like — all within one screen (for the full set see the [standard library
reference](https://dawn-lang.dawnop.com/stdlib.html), generated by `dawn doc --stdlib`).

**A top-level declaration may shadow a builtin/std function name** (§10.3, Rust-style): the
resolution order is this module's declarations → std → builtins, and it is exactly this
rule that makes the std module's own `pub fn len` legal. **The method names of prelude
traits get the same treatment**: they enter the function namespace along with the prelude
(for which names, see the "built-in traits" section of the [standard library
reference](https://dawn-lang.dawnop.com/stdlib.html); the normative definition is in §3.5),
and **may be shadowed by a declaration in this module** — it is not an error at declaration
time. Only that spelling is shadowed, the trait itself is unchanged — `impl Show[T]` is
declared and found as usual, and `${...}`, `==`, `for..in` still find their impl by trait
(§10.3).

> **Adding to the prelude is compatible**: adding a name to the prelude cannot make any
> program that already checks fail — the new name is either unused or shadowed by a
> declaration in that module. This is the precondition for the prelude being able to evolve
> ([`prelude-namespace-design.md`](prelude-namespace-design.md)).

> The **flat spellings** from before modularisation (`map_insert`, `str_len` and so on) are
> no longer in the public namespace — only the prelude and module qualification are left;
> write an old spelling and the error tells you which module it moved to.
> The history is in [`stdlib-naming.md`](stdlib-naming.md).

---

## 11. The standard library (semantics and criteria)

> **This section is not a listing.** Which functions there are, what the signatures look
> like, how to use each one — the full set is in the [standard library
> reference](https://dawn-lang.dawnop.com/stdlib.html), generated straight from the
> compiler by `dawn doc --stdlib` and therefore never out of step with the implementation.
> Copying it out by hand into the specification would only rot: what this section keeps is
> the half a listing cannot answer — **what input is accepted, what happens at the
> boundaries, why the trade-off is this one**.
>
> **Where something is implemented is invisible to the user.** These names come from two
> places: the compiler's builtin table, and **the `std/` modules bundled with the compiler
> (Dawn source, §10.6)**. Prelude names are implicitly visible; the rest are imported with
> `use std/x` and called qualified as `x.fn(...)`. Which side implements a name (builtin or
> std wrapper) affects neither its spelling nor its semantics
> ([`docs/builtins-to-stdlib.md`](builtins-to-stdlib.md)).

**The textual form of numbers.** The **language accepted by** `parse_int` / `parse_float` /
`parse_int_radix` **is this EBNF**, enforced by `std/fmt`'s own scanner (the two backends no
longer each delegate the grammar to a host parser; the host only does the decimal→binary
**correct rounding** after `parse_float` has validated, IEEE 754 round-to-nearest-even — on
that subset `strtod` and `Double.parseDouble` are the same function). Leading and trailing
whitespace is trimmed first according to **Dawn's own whitespace table** (the same
`char_is_space` table `str.trim` uses, not the host's):

```
int    = [ "+" | "-" ] digit { digit }                    (* digit is ASCII 0-9 only *)
float  = [ "+" | "-" ] mant [ exp ] | "Infinity" | "-Infinity" | "NaN"
mant   = digit { digit } [ "." { digit } ] | "." digit { digit }
exp    = ( "e" | "E" ) [ "+" | "-" ] digit { digit }
radix  = [ "+" | "-" ] rdigit { rdigit }
```

`parse_int_radix` uses the `radix` production: `rdigit` ∈ `0-9 a-z A-Z` (value = 10..35,
upper and lower case have the same value), and a digit whose value is ≥ radix is rejected;
a radix outside 2..36 answers `None`. An integer outside the 64-bit range is `None`, not
wrap-around. **Deliberately excluded** (things today's host parsers do accept and Dawn
rejects across the board): underscores, the `0x` prefix and hexadecimal floats (`0x1p3`),
the `f/F/d/D` suffixes, lower-case variants such as `inf`/`nan`, a signed `NaN` and
`+Infinity` (the legal special spellings are exactly the three `to_string` can emit, see
the round-trip closure in §4.3), and non-ASCII digits such as the full-width and
Arabic-Indic ones (the host's `Character.digit` accepts them; Dawn's digit set is closed
over ASCII).

**Case mapping.** `str.to_lower`/`str.to_upper` are the **Unicode simple (1:1) case
mappings**: one code point in, one code point out, no locale, no context, so **the code
point count does not change**. That rules out the three kinds of special case in full
mapping — the ones that change length (`ß` → `SS`), the locale-dependent ones (Turkish
`i`) and the context-dependent ones (Greek final sigma). Taking the simple mapping is not
about saving effort: full mapping is not a function a backend can implement from one table,
and Dawn requires a primitive to be the same function on every backend. Cases that need
full mapping belong to a library that can take a locale.

That table belongs to **the compiler** (`selfhost/src/embed/unicode_case.dawn`, a generated file
that records the JDK which generated it), and the two backends each take a copy of their
own: the JVM one is written into `dawn/rt/Strings`, the native one into the emitted C. So
the answer `str.to_upper` gives **does not move with the host JDK's Unicode version** —
upgrading to a new Unicode is the one explicit act of regenerating this table, not a silent
change of answer because you compiled on a different machine. Classification (`char_is_*`)
works the same way; its table is `selfhost/src/embed/unicode_class.dawn`.

**A character is a code point.** `code_points(s) -> List[Char]` splits into characters (a
supplementary-plane surrogate pair merges into a single code point) and
`from_code_points(cs: List[Char])` assembles from characters; `str.len` is the code point
count, `str.at` returns a **`Char`**, and the one that returns `List[String]` is
`str.chars`. Indexing into a string is always by code point index, never by UTF-16 code
unit. `char_is_letter`/`_digit`/`_alnum`/`_upper`/`_lower`/`_space` take a `Char`, and
`std/char`'s `is_*` are their public spellings.

Where the three criteria (§4.8) land on the string family: `str.at(s, i)` out of range
**panics** (criterion 1, `i` is a position the caller claims exists, the same as `xs[i]`
and `bytes.at`); `str.strip_prefix`/`strip_suffix` return `Option` (criterion 2, the test
and the stripping happen in one go, so the caller does not have to compute the offset
itself); `str.slice`/`take`/`drop` and `bytes.slice` **clamp** both ends, and `from > to`
gives the empty string (criterion 3, a range argument selects a stretch, it does not assert
that the endpoints exist). `truncate` is just `take`; there is no separate name for it.

**Bytes and text encodings.** The language promises exactly two charsets, and **the
function name is the domain**: `bytes.decode_utf8` and `bytes.decode_latin1`; there is no
charset registry. With no charset parameter there is no "unknown charset" failure mode, so
they return a bare `String` rather than an `Option` (the history is in
[`stdlib-impl-notes.md`](stdlib-impl-notes.md)).

hex and base64 are pure Dawn byte arithmetic (no `use java`, so both backends share one
definition), and the rules are normative: `to_hex` writes two digits per byte and **lower
case** is the canonical spelling, `from_hex` accepts either case and nothing else;
`to_base64` uses the standard alphabet of RFC 4648 §4 and pads with `=`, `to_base64_url`
uses the url/filename-safe alphabet of §5 and **does not pad with `=`**; the two decoders
each recognise only their own alphabet (guessing the alphabet would turn misspelled input
into wrong bytes), padding is optional, but the spare low bits of the final group must be
zero — otherwise one byte string would have several spellings. The decoders in this family
all fall under criterion 2: text from outside is to be validated, not asserted.

`Bytes` and `Buf` are in §9.5.1; there are also the operator `Bytes ++ Bytes` and
content-wise `==`/`!=`. Binary request bodies (multipart upload, WebDAV PUT),
crypto/signing and HTTP traffic all go through `Bytes` directly, no longer by way of a
latin-1 string.

**Naming families.** Length has exactly one name, `len`, and emptiness exactly one name,
`is_empty` — the same spelling in all five of `str`/`list`/`map`/`set`/`bytes`. **The one
named exception is `bytes.size(b: Buf)`**: `bytes.len` is already the length of a finished
`Bytes`, and the language has no overloading, so the write cursor had no choice but to take
another name (the criteria and the exceptions are under "naming families" in CONTRIBUTING).
A search that returns a position always returns an `Option` and **never emits `-1`**
(`str.index_of` and `list.index_of` are the same currency).

**Sorting and extrema.** The `sort` family requires the element/key type to have `Ord`
(§3.5); all of them are **stable** and a tie takes the first. `list.any`/`list.all`
**short-circuit** (the two faked with `fold` walk the whole thing); on an empty list they
are `false` / `true` respectively. `list.unique` asks for one thing more than the rest, a
`Hash`: deduplication with only `Eq` is quadratic, and `Set`'s insertion order happens to
be exactly the order deduplication wants.

**`Result` has no accompanying library functions** (no `map_err`, no `ok`). `match` and `?`
are enough; for crossing error types see the local helper in §8.1. Turning a `Result` into
an `Option` did not occur once in 40,000 lines of Dawn (not one of the 32 `-> None` arms
faces an `Err`), and throwing the error away runs against this language's grain.

**Positions: `Cursor`.** A function taking a code point index has to count from the start
of the string to that index on every call — O(n) per call, and O(n²) once it is in a loop.
A cursor is a **position**, not a count, so each step costs a constant. A position can only
be obtained from, passed back to and compared by the functions of `std/cursor` (`==` and
`< <= > >=` — the ordering of positions **within one string** is a legal operation on the
position type), and stored in a container/record for backtracking (it is an ordinary value,
and backtracking needs no extra machinery). **Do not do arithmetic on it** — arithmetic is
the only thing that can conjure up an illegal position in the middle of a surrogate pair.

**Both the arithmetic and the conjuring are compile errors**: `Cursor` is declared by
`std/cursor` as `pub opaque type Cursor = Int` (§2.7), and only that module may see it as
an `Int`. To write `Cursor` in type position you need `use std/cursor.{Cursor}` on top of
`use std/cursor` (the first binds a module alias, the second binds a name; two different
things). `cursor.seek` / `cursor.offset` are the bridge between the two position
currencies, one O(n) pass each, meant for the **boundary** (an `Int` index arriving from
outside, a position being reported to the outside); put them in a loop and you are back to
the O(n²) they exist to remove. A single call on a single string with the index version is
fine, but **inside a loop the cursor version is mandatory** — the measurements are in
`docs/seq6-research.md` §5's addendum.

**Container representations.** `Map`/`Set` are represented by the pure-Dawn `std/hamt` (a
persistent HAMT) and `List` by `std/pvec` (a persistent vector); these are **internal
modules**: `use std/hamt` / `use std/pvec` outside std is a compile error, and the
diagnostic points back at `std/map`/`std/set`/`std/list` (§10.6). The representation has to
be replaceable, and being replaceable requires that nobody depends on it — which is why the
[standard library reference](https://dawn-lang.dawnop.com/stdlib.html) does not list these
two modules either. The semantics of the containers (persistent interface, keys must be
`Eq + Hash`, iteration in insertion order, equality independent of order) are in §2.2.

**Where IO stands.** Everything in `std/io` is `!io`, and anything that can fail returns
`Result[T, ForeignError]` (§9.8.1) — a structured payload rather than the sentence a
barrier has already rendered; the reasoning is in
[`audit/error-model-design.md`](audit/error-model-design.md). The further normative
behaviours are:

- `io.write_file(path, content)` **creates missing parent directories automatically**. Its
  `Ok` carries no value
- The entry names of `io.list_dir(path)` are sorted in **code point order**. The sorting is
  done in the std layer (`list.sort` goes through the language's own `Ord[String]`), and
  the `io_list_names` primitive promises no order — the backends no longer each sort their
  own way. When path is not a directory it is an `Err` whose `kind` is
  `"io.not_a_directory"` — that one and `io.run`'s `"io.no_program"` are the two kinds std
  mints itself, all the others come from the backend
- `io.is_dir(path)` treats both "does not exist" and "errored" as `false`
- `io.stdin_ready(timeout_ms)` answers exactly one thing: **whether at least one byte is
  readable right now**. **End of input does not count as ready** — a write end that is
  already closed and "connected but silent" give the same `false`, and the difference
  between them is reported by `io.read_stdin`, which is still the only reader. So **a loop
  driven by it alone will spin once input ends**: when there is nothing to do you must go
  and make that blocking read (the read loop in `selfhost/src/lsp/server.dawn` has this shape).
  `timeout_ms` is an **upper** bound, not a lower one: returning `false` early is always
  legal (a regular file at end of file returns immediately), because the only thing a
  caller holding a `false` can do is stop waiting; `true` is the one that must not be
  guessed. This shape was chosen because it is **the only one both backends can implement
  without starting a thread**: the "a read will not block" reading would have to answer
  `true` at end of input, and the JVM cannot tell that state apart from silence
  (`available()` is 0 in both cases), while starting a background reader thread would eat
  the bytes on behalf of a child process that inherited stdin (measurements in
  [`docs/audit/lsp-robustness-design.md`](audit/lsp-robustness-design.md) §2.2.1)

- **When the bytes read in are not UTF-8**: nothing guarantees that the bytes the operating
  system hands over are UTF-8, so every read primitive that turns bytes into a `String`
  must take a position. There are two classes, and **the two backends agree**:
  - `io.read_file` **fails** (`Err`, i.e. a fault a barrier can catch). Reading text and
    getting back something other than the text on disk is exactly what this rule is there
    to stop; when the input was never text in the first place, use `io.read_file`'s byte
    twin `io.read_bytes`, which does not look at a single byte
  - `io.read_line` / `io.cwd` / `io.getenv` / `io.list_dir` / `io.temp_dir` / `args`
    **replace**: an illegal sequence becomes U+FFFD, following `bytes.decode_utf8` to the
    letter (one U+FFFD per illegal sequence, not one per byte). A file name that is not
    UTF-8 is still a file name, and rejecting it would leave the program unable even to
    list a directory
  - From which follows an invariant: **there is no ill-formed UTF-8 inside a `String`**.
    That is not rhetoric — it stops overlong encodings from flowing downstream and being
    taken for real characters by primitives that walk by code point
    ([`stdlib-impl-notes.md`](stdlib-impl-notes.md))

**Maths** (`abs min max sin cos sqrt pow to_float to_int ...`) is pure — internally it
wraps `java.lang.Math` with `unsafe_pure`.

Implementation strategy: wrap Java thinly wherever a thin wrapper will do (`String` simply
is `java.lang.String`), while the persistent `List`/`Map`/`Set` are **pure Dawn source**
throughout (`List` = the `std/pvec` persistent vector, `Map`/`Set` = the `std/hamt`
persistent HAMT, all with deterministic insertion order), leaving the backends a single
primitive to implement: `Array`.

---

## 12. The compilation model

### 12.1 Outputs

There are **two backends**, each with its own driver. `dawn` is the JVM toolchain (it
emits bytecode); `dawnc` is the C backend (it emits C11 source and then hands it to
`cc`). They are not the same road: `dawn build --native` is still the JVM backend, it
just hands the jar from the previous step to GraalVM `native-image` (§12.3); `dawnc`
produces no bytecode at all.

**The JVM toolchain `dawn`** (wherever the rest of this chapter does not name a driver,
it means this one):

| Command | Output |
|------|------|
| `dawn check <file or dir>...` | Type checking only. Prints `ok` and exits 0 when clean; **renders the diagnostics and exits 1 if there is any**; exits 2 on a usage mistake |
| `dawn run <file.dawn or dir>` | Compiles into memory / a temporary directory, starts a JVM and runs it |
| `dawn build <file or dir> -o app.jar` | An executable jar (`Main-Class: main` is already set) |
| `dawn build ... --native -o app` | The previous step + GraalVM `native-image`, a standalone binary (§12.3) |
| `dawn test <file or dir>` | Compiles the variant that includes the test blocks and runs it (directory mode aggregates the tests of every module) |
| `dawn fmt <file or dir>...` | Formatting (directory mode recurses over every `.dawn`; a directly named file must end in `.dawn`, or it exits 2) |
| `dawn __emitc <file or dir> -o out.c` | A C translation unit. A hidden subcommand: this is the C backend's entry point on the JVM toolchain, and `dawnc`'s selfhost and differential comparison both go through it |

**The C backend driver `dawnc`** (a single-file static executable, shipped with each
release; it needs neither a JVM nor this repository):

| Command | Output |
|------|------|
| `dawnc check <target>` | Type checking only, reports diagnostics |
| `dawnc emitc <target> [-o out.c]` | A C translation unit (compiled together with the runtime in `runtime/c/`) |
| `dawnc build <target> [-o out]` | The previous step + a call to `cc` (`$CC` overrides it), a standalone executable |
| `dawnc run <target>` | The same, and runs it as soon as it is compiled |
| `dawnc test <target>` | Compiles the variant that includes the test blocks and runs it |
| `dawnc fmt` / `doc` / `add` / `lsp` | Output is **byte-for-byte identical** to `dawn`'s subcommands of the same name (`scripts/native-cli-diff.sh` pins these four to the JVM's bytes) |
| `dawnc version` | The version number (it reports `(native)` itself, so it is not literally identical to `dawn --version`) |

The few subcommands `dawnc` lacks are not holes, they are the backend's boundary: **it
refuses `use java`** (Java interop is a JVM backend capability, §9), and `build`-to-jar,
`lock` and `cache` likewise only mean something on the JVM side. Both drivers accept
`--std <dir>` to swap the standard library source.

**The argument may be a single file or a project directory** (§10.1): directory mode
loads every module under `src/`, with `src/main.dawn` as the entry point; single-file
mode walks upwards for a `src` ancestor and takes it as the root. The jar collects every
module class, and `Main-Class` = the entry module's class `main`.

**Third-party jars: `--cp <jars>`** (works for run/test/build; separated by the path
separator, repeatable). Compile-time `use java` resolution and run-time loading share
this one classpath. `build` records each jar in the manifest's `Class-Path` (relative to
the output directory, so moving the jars means moving them together), and the output
still runs directly with `java -jar`; `build --native` instead passes them to
native-image in `-cp` form (whether a third-party library's reflection/JNI survives
native-image is the library's responsibility, see §12.3).

`--cp` itself does no dependency resolution: it mounts exactly what you give it, and you
have to list the transitive dependencies yourself. **A library that needs a dependency
tree goes through `[java-deps]`** (the `dawn.toml` of §10.1) — that path resolves Maven
transitive dependencies via coursier. This section once said "Dawn has no dependency
resolution — it only accepts single-jar, zero-transitive-dependency libraries", which was
the fact before `[java-deps]` existed and directly contradicts §10.1.

**Guaranteed**: the same program behaves identically under all three outputs — the
bytecode running on a JVM, the native-image binary from `--native`, and the executable
from the C backend (apart from startup time and memory footprint). A program with
`use java` only has the first two outputs; that is a boundary it declared itself, not an
inconsistency.

### 12.2 The bytecode mapping

| Dawn construct | JVM implementation |
|-----------|----------|
| Module `json/lexer` | One class, internal name `json/lexer` (package `json`, class `lexer`), functions become static methods |
| ADT/record | Class names carry the module prefix: `json/lexer$Token`, constructor `json/lexer$Token$Num` |
| Cross-module call | `invokestatic` on the other module's class; constructors/fields as usual (the classes are public) |
| ADT | abstract class + final subclasses; a payload-free constructor is a singleton |
| record | final class + fields (does not rely on Java records, so older bytecode targets still work) |
| `match` | An `instanceof` chain + field reads (no indy, no pattern switch) |
| lambda/closure | `LambdaMetafactory` (on native-image's supported list) |
| generics | erasure + boxing |
| structurally equal types | ADTs/records/tuples still get matching `equals` and `hashCode`, but those are **for Java callers** — Dawn's `==`/`hash` are Core functions that lowering expands structurally (§4.3), and `Map`/`Set` reach them through dictionaries. When an `impl Eq`/`impl Hash` exists, these two methods forward to that impl |
| `Int`/`Float`/`Bool` | native `long`/`double`/`boolean`, boxed only in generic positions |
| `Unit` | `Ldawn/rt/Unit;` — a singleton reference; it takes one slot and is no different from any other reference in parameter/field/capture positions |
| `Never` | `V`, and it only appears in return position (an expression that does not return has no parameter or field to occupy) |
| `panic` | Throws `dawn.rt.PanicError` (a subclass of Error, so `catch_fault` does not catch it; only the isolation point `catch_panic` does, see §9.8) |

The runtime support classes (`dawn/rt/Lists`, `Strings`, `Io`, `Show`, `Maps`, `Tuple*`,
`Fn*`, and so on) are generated once per program and shared by all module classes.

### 12.3 Ahead-of-time compilation: the native-image contract and the C backend

Both roads get you an executable that does not depend on a JVM, but **which layer of the
compilation stack** they fork at determines the constraints each one carries.

**`dawn build --native` (GraalVM native-image)**: goes through the whole JVM backend and
takes the jar for closed-world analysis. The language constructs are **guaranteed** not
to produce reflective calls, custom indy bootstraps, dynamic class loading or JNI (Java
interop uses ordinary invokes). A `--native` build therefore needs no reachability
configuration. If a Java library you pull in uses reflection itself, that is the
library's responsibility — the error message will point out that this is beyond what
Dawn guarantees.

**`dawnc` (the C backend)**: forks after Core, never passes through bytecode, so the
contract above means nothing to it — there are no classes to analyse and no native-image
involved. The price is that it **has no Java**: `use java` is refused outright (§12.1).
The output is an ordinary executable compiled by `cc`, and the runtime lives in
`runtime/c/`.

### 12.4 Tail calls

**Self-recursive tail calls are guaranteed** to compile to a loop (the stack does not
grow) — for top-level functions and for **local named functions** (§3.1) alike. Mutually
recursive tail calls are not guaranteed in v0.1. The rule: a call to the function itself
inside its body sits in tail position (return position, the tail position of a match/if
branch, the last expression of a block).

---

## 13. Syntax cheat sheet

```dawn
# ---- declarations ----
use geo/shape.{Shape, area}
use java "java.nio.file.Files"

pub type Color = | Red | Green | Blue derive Show
type Point = { x: Float, y: Float }
alias Distance = Float           # transparent alias (§2.6)
const ORIGIN: Point = Point { x: 0.0, y: 0.0 }

pub fn dist(a: Point, b: Point) -> Float =
  sqrt(pow(a.x - b.x, 2.0) + pow(a.y - b.y, 2.0))

fn double(x: Int) = x * 2        # a private function may omit the return type (§3.1)

# ---- expressions ----
let n = 42                       # immutable binding
var acc = 0                      # mutable binding
acc = acc + 1                    # assignment (var only)
let (a, b) = pair                # destructuring
if x > 0 { "pos" } else { "non-pos" }
match opt { Some(v) -> v, None -> fallback }
xs |> filter(x => x > 0) |> map(x => to_string(x)) |> join(", ")
xs[0]                            # subscript: goes through the Index trait; out of range panics, enquire with get (§4.8)
read_file(path)?                 # Result propagation
if n < 0 { return "negative" }   # early return (§4.9)
xs.each fn(x) => println("$x")   # trailing closure: the last argument (§4.3)
with f <- bracket(open(p), close)  # the rest of the block becomes the use closure (§4.10)
comptime { heavy_pure_calc() }   # compile-time evaluation

# ---- local functions inside a block (recursive, §3.1) ----
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}

# ---- tests ----
test "dist is symmetric" {
  assert dist(p, q) == dist(q, p)
}
```

---

## 14. Future directions (explicitly not in v0.1)

In priority order: trait v2 (conditional impls, generic subjects, supertraits, more
derives), finer-grained effects (`!fs`, `!net`), mutually recursive tail calls, passing
Dawn lambdas to Java, newtype, monomorphisation optimisations, a `Rune` type.
(`break`/`continue` landed in 2026-07, see §4.7.)
(trait v1 — single-parameter typeclasses + dictionary passing — landed in 2026-07, see
§3.5 and trait.md.)
