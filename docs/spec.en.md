<!-- doc-check: translation-of docs/spec.md @ 48660121b457be9d -->

# Dawn Language Specification

*[中文](spec.md) — the Chinese text is the original; this is its translation, and `scripts/doc-check.py` watches the two for drift.*

> Status: **normative**. Applies to version: 0.72.0 (the `VERSION` in `selfhost/src/version.dawn`).<!-- doc-check: version -->
> When the implementation conflicts with this document, this document wins and the implementation
> is a bug — unless some clause here is explicitly marked "superseded by X".
>
> The title read "v0.1 draft" for a long time; by the day that was changed the toolchain had<!-- doc-check: historical-v0-1 -->
> already reached 0.11. A document that calls itself a draft cannot act as a judge, and this is
> the only document in the repository qualified to judge disputes about semantics. The version
> number follows `VERSION`; it is no longer numbered separately.

This document is the authoritative definition of the syntax and semantics. For design motivation
see [design.en.md](design.en.md). [grammar.ebnf](grammar.ebnf) is a **historical** machine-readable
grammar and has **fallen behind the parser** (its own header lists the known mismatches) — read it
as a reference, not as a judge. When the grammar is in dispute, this document and
`selfhost/src/front/parser.dawn` win; the executable expectations live in `scripts/grammar-corpus/`.

Wording of this specification: **must** (violating it is a compile error), **guaranteed**
(behaviour the implementation promises), **undefined** (not promised by this specification; do not rely on it).

---

## 1. Source files and lexical structure

### 1.1 Source files

- UTF-8 encoded, extension `.dawn`.
- One file is one module (see §10).

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
There are four further **contextual keywords**, which remain ordinary identifiers elsewhere:
`derive` (only at the tail of a `type` declaration), `as` (only in the renaming position of `use`,
§10.2), `handle` (after `with`, when the next token is not `<-`, §6.5), and `opaque` (only directly
before `type`, where it introduces an opaque type, §2.7).

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
| `[1, 2, 3]` | `List[Int]` | trailing comma allowed; separators and element forms in §4.11 |
| `(1, "a")` | `(Int, String)` | tuple, 2 to 8 elements |
| `'a'`, `'\n'`, `'世'`, `'\u{1F600}'` | `Char` | character literal (see below) |

The non-negative magnitude of an integer token must normally be in
`0..9223372036854775807`. The sole exception is exactly `2^63`, and only when it is the direct
operand of unary `-`: decimal `-9223372036854775808`, hexadecimal `-0x8000000000000000`, and the
corresponding 64-bit binary spelling all denote the minimum `Int`. Expressions and literal
patterns use the same rule. Parentheses around the whole negative value remain valid
(`(-9223372036854775808)`), but parentheses separating the magnitude from the minus do not
(`-(9223372036854775808)`), nor does bare `2^63`. A magnitude greater than `2^63` is a range error;
a digit forbidden by its radix (such as `0b2`) is an invalid literal rather than a range error.

**A character is its own type, `Char`**: one Unicode scalar value (`0..0x10FFFF`, excluding the
surrogate range `D800..DFFF`). It is an **opaque type** (§2.7) over `Int` whose owner is
`std/char` — the representation is the code point, so it is zero-cost, and `==`, `<`, hashing and
literal patterns in `match` all reuse the `Int` ones. The rendering comes in two layers (§4.3), and `std/char`
writes one for each: `impl Display[Char]` is the top level, so `to_string(c)` and `"${c}"` give the
character, while `impl Show[Char]` is the nested one, so a `Char` inside a structure (`[c]`, a
record field, a tuple) renders as the **source literal** `'a'`, escaped with the set above, the way
a nested `String` renders as `"a"`. `str.from_char(c)` asks for that top-level
one-character string by name, without depending on an impl. But it is **not** an `Int`: `'a' + 1` does not
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

A newline doubles as a **separator** in two places: between match arms (§5) and between the
elements of a list literal (§4.11). Both parse the expression by the rules above first, and the
newline left standing afterwards is the separator, so continuation wins and separation follows.

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

The non-generic, compiler-owned basic types users may name directly are `Int` (64-bit), `Char`
(a Unicode scalar value), `Float` (double), `Bool`, `String`, `Bytes` (an immutable byte sequence),
and `Unit`. These seven names, together with the three public generic names in the next section,
are the complete public builtin type surface.

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

### 2.2 Composite types and naming layers

The generic, compiler-owned types users may name directly are exactly `List[T]`, `Map[K, V]`, and
`Set[T]`:

- `List[T]` — an immutable persistent list. The implementation is a **persistent vector: a 32-way
  trie plus a tail block** (`std/pvec`, pure Dawn source, built on the `Array` primitive): indexing
  is O(log32 n) — at length ≤32 everything is in the tail block, i.e. one array read; `++` appends
  element by element, copying only the tail block while it is not full (≤32 slots), and every 32
  appends it pushes the tail block into the trie and copies one root-to-leaf path, so the
  accumulating loop `acc = acc ++ [x]` is **linear, O(1) amortised**. Structure is shared and a
  published list never changes; appending to an old version does not copy the whole table, only its
  own small piece.
- `Map[K, V]` — an immutable map (see below)
- `Set[T]` — an immutable set (see below)

The remaining composite types do not belong to that builtin-name inventory:

- Tuples `(A, B, ...)` and function types `fn(A, B) -> C !e` are **structural types**, with no
  nominal type name; `!e` may be omitted, meaning pure.
- `Option[T]` (`Some(T) | None`), `Result[T, E]` (`Ok(T) | Err(E)`), and `ForeignError` are ordinary
  nominal ADTs injected by the prelude; they are not compiler-owned builtin types.
- `Array[T]` is a compiler-owned representation primitive nameable by the bundled std. A user
  module cannot reach that primitive through this name; an `Array` declared outside std is simply
  the user's own nominal type.
- `Never` is the compiler-owned bottom type and a hard-reserved name. It has no values or
  constructors. It may be written directly only as the return type of a top-level function, local
  function, trait or impl method, effect operation, or any function type. Therefore
  `fn() -> Never` and `alias F = fn() -> Never` are valid. Parameters, fields, const or let
  annotations, generic, collection, tuple, and other storage positions, associated bindings, and
  the direct alias `alias N = Never` are invalid. `type`, `alias`, `trait`, `effect`, constructor
  names, and type parameters cannot shadow `Never`. A function declared to return `Never` must
  itself diverge. LSP completion offers the
  name only in function-return contexts. `dawn doc --builtins` marks it with `"use": "return"`
  rather than presenting it as a globally usable public builtin. `io.exit` still returns `Unit`;
  this rule does not change its existing API.

In type position, `(T)` is **grouping** only: after parsing it is still `T`, with no extra type
node. A tuple still has at least two elements: `(A, B)` is a tuple, `(T,)` is not a one-element
tuple, and empty `()` is not a type either (the unit type is written `Unit`).

Function-type arrows remain right-associative, and a suffix effect belongs to the function layer
it immediately follows. When the return type is itself a function, parentheses separate an outer
effect from that returned function:

```dawn
fn() -> fn() -> Int !io          # pure outer function, !io returned function
fn() -> (fn() -> Int) !io        # !io outer function, pure returned function
fn() -> (fn() -> Int !io) !io    # both layers are !io
```

`Option` and `Result` are ordinary prelude ADTs, with no special status
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

**A record can only be built with braces.** `Point(1.0, 2.0)`, `Point(x: 1.0, y: 2.0)` and
`Point()` are all errors ("record `Point` must be built with braces"), whether the parentheses
were written directly or produced by a pipeline (§4.4). The reason is that spelling and meaning
correspond one to one: fields in the brace form must be named, and filling a record positionally
would turn field order into an ABI; a record's bare name is not a constructor function either
(§2.3, last bullet). `x |> Point { ... }` is not "filling in fields" — it **calls a record value**,
and is reported as not callable.

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
- Implemented as erasure + boxing; monomorphisation is an optional later optimisation and does
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

Restrictions: an alias cannot be recursive (a cycle is an error); an effect variable must be bound
by the parameter list (`alias Mapper[T, U, !e] = fn(T) -> U !e`), and writing an unbound one is an
error, while a named label and `!io` are simply written (§6.3); with `pub` it can be imported across
modules (`use m.{Handler}`).

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

A generic opaque type's **instance identity** is its declaration identity together with its
instantiated arguments; the target answers only questions about runtime representation. Even when a
type parameter does not appear in the target at all, `Phantom[Int]` and `Phantom[String]` are two
types; substitution, equality, unification, display and export-surface validation all carry those
arguments along. "The representation is not public" does not imply "the type parameters are hidden".

> **The criterion for implementers (the alias-substitution test)**: replace `opaque type N = T` in
> place with `alias N = T`; if some function's answer changes, it is either one of the five things
> below, or it is a bug. **Only five things** are allowed to see `TyOpaque`: the assignability and
> unification decision (who can convert), impl selection (`head_of`/`impl_at`), symbol naming
> (`ty_key`/`dict_key`/impl method names), the type name in diagnostics, and export-surface
> visibility (§3.3: it checks the identity and the explicit arguments, **not** the representation).
> Every other function that eats a `Ty` — width, descriptor, slot, boxing, which instruction,
> whether it can be a constant, whether some trait has an answer — takes the target's answer.
> The order is fixed too: **ask about identity before representation**. `impl Eq[UserId]` must come
> before "compare as Int", or declaring it would be pointless.
> The mechanised form is in `scripts/opaque-twin/`: every corpus program is run twice, once as
> written and once with `alias` substituted, and the outputs must agree (a compile error counts as
> output). Doing this by hand once on 2026-07-27 caught 12 places.

An opaque type can be given its own impls (`impl Show[UserId]`, `impl Display[UserId]`), which take
precedence over the target type's; the orphan rule counts an opaque type as a local type of the
module that declares it. "The rendering is the target's too", above, is stated on the premise that
the type wrote none of its own: `Char` wrote both (`impl Display[Char]` and `impl Show[Char]`,
§1.5), so neither of its renderings is the `Int`'s while `==`, `<` and hashing still are.
`scripts/opaque-twin/char.dawn` pins all four, claim by claim, each rendering in both directions:
equal to the string its impl is defined to produce, and not equal to the `Int`'s.

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
`const`, `fn`, `test`, `trait`, `impl`, `effect`. There is no top-level mutable state.

### 3.1 Functions

```dawn
fn add(a: Int, b: Int) -> Int = a + b

fn greet(name: String) -> Unit !io = {
  println("hi, $name")
}
```

- **Parameter types must be written out in full** (for every function); a `pub fn` must write
  the return type as well — a public signature is an API contract.
- **A private function may omit the return type**: `fn double(x: Int) = x * 2`. The body then
  determines the return type; if every effect annotation is omitted too, the base effect is
  determined on that same inference path. Three kinds of function **must** annotate the return type:
  (1) `pub`; (2) recursive / mutually recursive ones (the compiler infers in topological order
  over the call graph, and on a cycle there is nothing to infer from); (3) ones whose body uses
  `return` or `?` (both need a known return type).
- **The base effect is inferred only in the double-omission form**: only a private function that
  **omits both its return type and every effect annotation** has its return type and base effect
  (pure / `!io`) inferred from the body. Writing `-> T` while omitting the effect annotation is a
  `pure` promise, not a request for inference; performing IO in that body is an error. If the return
  type is omitted but an effect row is written, only the return type is inferred and the written row
  stays fixed. Named effects are never inferred and must be declared explicitly; once any named
  effect is written, the whole effect row is a fixed promise and io is not added automatically. For
  example, a function declared `!Ask` that also performs IO must write `!(io | Ask)`; `!Ask` alone
  is an error.
- The function body is the single expression after `=`; a block `{ }` is an expression too (§4.2).
- Default parameter values exist (below); no varargs, no overloading.

**Default parameter values** (2026-08-08, #207): a parameter may be written
`name: Type = expr`; a call that omits the argument evaluates the expression **once per
call** (not Python's evaluate-once-and-share):

```dawn
fn column(kids: List[Int], align: Int = 0, gap: Int = 0) -> Int = align + gap * len(kids)

column(kids)
column(kids, gap: 12)
column(kids, align: 1, gap: 12)
```

- **The default expression must be pure** (neither `!io` nor a named effect): otherwise the
  function's effect row would depend on whether the call site passes the argument — one
  signature, two rows, which a type system cannot have.
- **Evaluated in the declaring scope**: it may refer to this module's private functions and
  `const`s, and it **cannot see the function's other parameters** (the default is checked in
  a scope with no parameters, so referring to one is an ordinary `undefined variable`). That
  restriction can be lifted later without breaking anything.
- **A parameter's type may mention the function's type parameters**
  (`fn join[T](xs: List[T] = []) -> T`): the synthesized `f$default$k` repeats the function's
  type parameters and their bounds verbatim, and a call that omits the argument calls it at
  **that call's own instantiation** — the same type substitution and the same witness
  dictionaries the call site already resolved. A default expression may therefore use the
  trait methods a bound provides (`fn pick[T: Zero](v: T = zero())`), and which
  implementation it gets is decided by the call site's instantiation.
- **A default need not sit at the tail**: `fn f(a: Int = 1, b: Int)` is legal — `a` can only
  be skipped by naming `b` (the positional prefix takes slots left to right and cannot jump).
  A skipped required parameter reports "missing argument(s) for `f`: …"; a count outside the
  range reports "`f` takes 1 to 3 argument(s), got 0".
- **Implementation shape**: each defaulted parameter synthesizes a zero-parameter pure
  function `f$default$k` in the declaring module (`$` is not in the identifier lexicon, so
  source code cannot spell it); a call that omits the argument simply calls it — both
  backends and the comptime interpreter treat it as an ordinary top-level function.
- **Using the function as a value loses the defaults**: after `let g = f`, `g`'s type is the
  full `fn(A, B, C) -> R` — the same discipline as "a bare constructor used as a function
  value loses its field names" (§2.3).
- **Scope**: top-level functions only (private and module functions included). Local `fn`
  (its calls go through the function-value path), lambdas, constructor fields (records
  already have `{ ..base, x: v }`), trait methods (Dawn already has a thing called "default"
  — the default method body; and under dictionary passing an impl could not override a value
  default), effect operations (an operation call reads an evidence field and calls a
  closure; there is no symbol to hang one on) and Java methods take none, each with its own
  refusal.

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
`alias`, `const`, `trait`, `effect`. `pub type` exports its constructors and fields as well.

The **complete resolved export surface** of a `pub` declaration must be nameable outside its module.
Marking only the outermost declaration `pub` does not export the private nominal identities it
refers to:

- A `pub fn` checks its type parameters' bounds, its parameters, its return type and its complete
  effect row; a `pub const` checks its declared type, while the initializer stays an implementation
  detail.
- A `pub type` or record checks every constructor field; a `pub trait` checks every method
  signature, constraint and effect row, while a default body stays a private implementation detail;
  a `pub effect` checks every operation's parameters and return type.
- A transparent alias is fully expanded at this boundary: a private alias whose ultimate target is
  entirely public may appear in a public surface, but reaching a private nominal type after
  expansion is still an error. A `pub opaque type` is the opposite — it stops at its own public
  identity, so the representation may use private types, but every instantiated argument in the
  public spelling must still be publicly nameable, and a private opaque identity may not appear in
  a public surface at all.
- A type projection checks both its trait identity and its subject; a named effect must be a
  `pub effect`.
- An impl has no `pub` spelling: only an impl of a public trait for a subject nameable outside the
  module belongs to the export surface, and then its generic constraints and every associated type
  binding must be publicly nameable too. An impl of a private trait, or for a private subject, is
  not reachable from outside and so is not constrained here — which is also why `dawn doc` does not
  list it.

An ordinary `pub fn` **may** declare a public named effect (§6.5): callers can import it, propagate
it, or install a handler. It is a *private* effect in a public surface that is an error.

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
  built-in traits `Ord`/`Eq`/`Hash`/`Show`/`Iter` inject too; **the two whose method name the
  language consumes on the user's behalf do not**, and their method names appear only in impl
  bodies, in documentation and in error messages: `Index` (consumed by `[]`, §4.8) and `Display`
  (consumed by `to_string` and `${...}`, §4.3).
- **Seven built-in traits**: `Ord` (`cmp`, behind ordering beyond `<`/`<=`), `Eq` (`eq`, behind
  `==`/`!=`), `Hash` (`hash`), `Show` (`show`, the **nested** rendering, and the bound
  `to_string` asks for), `Iter` (behind `for..in`, §4.7), `Index` (behind `[]`, §4.8),
  `Display` (`display`, the **top-level** rendering, behind `to_string` and `${...}`, §4.3).
  The impls for the scalars ship with the language;
  `derive Ord` / `derive Show` cast an ordinary impl, and on a generic type a conditional impl;
  `Display` cannot be derived (the reason is under `Display` below).
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
- **`Display`** declares one method and no associated types:
  `trait Display[T] { fn display(x: T) -> String }`. It is the **top-level rendering** layer:
  `to_string(x)` and `"${x}"` use the impl when there is one, and otherwise render by the
  existing rules of §4.3. The method name `display` does **not** enter the function namespace
  (see the injection rule above). Three boundaries:
  - **`Show[T]` remains the bound `to_string` asks for.** `Display` only refines an answer that
    already exists; nothing becomes renderable that was not.
  - **It cannot be derived.** `derive Show` says "render my structure", while a `Display` is a
    decision about presentation: one per type, hand written.
  - **An opaque type is asked at every peel layer** (§4.3): with no `Display` on
    `opaque type A = B`, `B`'s is used; if `A` writes one, `A`'s wins.
  The one impl that ships with the language is `impl Display[Char]` (in `std/char`, §1.5; the
  same module writes the other layer's `impl Show[Char]`).
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
  from `Eq[T]`. No dyn (for heterogeneous collections see "Heterogeneous collections" at the end
  of this section; the reasoning behind the verdict and the conditions for reopening it are in
  [trait.md](trait.md) §10), no supertraits, no specialisation (no asking "which one is more
  specific"). A trait method's effect row is a full row: pure, `!io`, effect variables, named
  labels and associated-effect projections are all admitted (§6.5 Boundaries); an impl's effect ⊑
  the trait declaration's (after reduction through that impl's bindings), the two sides' effect
  variables are paired by position, and **the labels must match exactly on both sides** — each
  label is one hidden evidence parameter, part of the method's shape.
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
  match first(c) { Some(x) -> x, None -> d }        # head_or([1], 9) is Int
```
- **Associated effects** (design and verdicts in
  [effect-params-design.md](effect-params-design.md), knife 5; defaults ruled 2026-08-26): a
  trait body may declare an `effect E` member (no bound) and may give it a **default row**
  `effect E = !X`; an impl **binds each declaration at most once** with `effect E = !X`, whose
  right side is a **concrete row**: one named effect, `!io`, or the empty row `!()`; effect
  variables and projections cannot be bound, and a default's right side follows the same
  discipline. An impl that omits a defaulted member takes the default; one that writes a
  binding overrides it. Omitting a member **without** a default, multiple bindings, and binding
  a name the trait does not have are each a compile error. Registration materializes the
  default into that impl's binding, after which reduction, evidence and the backends cannot
  tell a defaulted binding from a written one (the five pure tea impls compile to byte-identical
  Core with their bindings deleted, which is that sentence's executable verdict). A method's
  row **projects** it as
  `!T.E` — the subject must be a type parameter carrying that trait bound (exactly one bound
  declares the name; zero and ambiguity are both errors), and the licensed positions are the
  type projection's: inside a method signature, including function-type rows in parameter and
  return positions.
  - **Reduction is eager**, through the same door as the type projection: when instantiation at
    the call site lands the subject on a concrete head, the projection is immediately replaced
    by the bound row via that subject's impl (the same answer as dictionary selection) — an
    unreduced projection **does not exist** in a concrete row.
  - **Evidence settles per parameter, exactly one slot**: each projection written in a row adds
    one **erased** hidden evidence parameter, after the evidence the written labels synthesise.
    A call site whose reduction yields a label hands over that label's evidence; one that lands
    on its own still-rigid projection forwards its own slot; one that reduces to pure or `!io`
    hands over a placeholder. The dictionary itself carries no evidence; a slot's shape depends
    on the trait declaration alone. **v1 boundary**: one associated effect member binds at most
    one label — two effects want two members.
  - **A bound is a check, not a definition**: a projection always reads the impl's actual
    binding (unique per subject); a row written on a consumer's bound is only an upper bound
    (the impl's side ⊑ it), and the two coexist.
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
- **Trait methods and functions with bounds can be used as function values directly**: once the
  expected function type settles the subject, the compiler writes the eta expansion and the
  bound is discharged to a dictionary there. When the bound belongs to the **enclosing**
  function's type parameter, the synthesised closure captures that function's dictionary
  parameter, exactly as a handwritten lambda does. A subject nothing settles (`let f =
  to_string`) still reports "cannot infer the type parameter(s)"; write the expected type, or an
  annotated lambda. A function with an **effect label** can be a value all the same: the label
  enters the value's type and the call site supplies the evidence (§6.5, boundary). An **effect
  operation** cannot; there is no function symbol to take.
- Limits: calls with trait bounds and impl-based sorting are not allowed in comptime.

#### Heterogeneous collections

There is no dyn; the idiom for a heterogeneous collection is **first-class functions plus an
opaque type**: while the type is still concrete, wrap the method call in a closure, put the
closure in a record, declare the record as an opaque type, and give that opaque type an impl.

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
  for x in xs { println("${x}") }
}
```

```output
1
"two"
true
```

Each of the four steps rests on a rule stated in this document:

- The dictionary that discharges `Show[T]` inside `shown` is an ordinary value, captured by the
  lambda by value (this section, "Trait methods and functions with bounds can be used as function
  values directly": exactly as a handwritten lambda does; §4.5: a closure captures bindings by
  value). `T` ends there; it no longer appears in `Shown`.
- `Shown` is an opaque type, so at runtime it **is** `ShownRepr`, at zero cost (§2.7).
- `impl Show[Shown]` is legal and takes precedence over the target type's impl: the orphan rule
  counts an opaque type as a local type of the module that declares it (§2.7).
- `let r: ShownRepr = s` cannot be dropped: an opaque type converts only at assignment, argument
  and return positions, not inside an expression (§2.7), so `s.render()` is a compile error.

Where it applies:

- **A single-method trait**: a complete replacement.
- **A multi-method trait**: one field per method, i.e. a hand-written function table; the
  language does not write it for you.
- **`Eq`/`Ord` cannot be written this way**: a binary method (`fn eq(a: T, b: T)`) requires both
  arguments to have the same type, while two `Shown` values may have different underlying types —
  "the same type" has nowhere to live in the type of `Shown`. Corollary: nothing like
  `Map[Shown, V]` can be built.

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
- **Tail block: a bare `{ ... }` following on the same line is the last argument**
  (2026-08-08, #206). `f(a) { e }` is `f(a, () => e)`; a parameterised block spells its head
  in the braces — `items(xs) { item => e }` is `items(xs, item => e)`, and multiple or
  annotated parameters use the parenthesised list: `fold(xs, 0) { (acc, x) => e }`,
  `{ (x: Int) => e }`, `{ () => e }`. The landing point is exactly the one `(` has (so
  `xs.each { e }` yields a method call and a bare name `column { e }` an application); the
  sugar changes the spelling, not the node.
  The historical ruling — "a bare `{}` cannot be told apart from the body of a
  parenthesis-free `if` header, permanently out of scope" — was overturned (2026-08-08): the
  distinction is the same switch that keeps a record literal out of a header (`nb`, below),
  and the ruling predates it.
  Four side conditions:
  1. **Same line only**, the same discipline as `(`: `let y = g(1)` followed by `{ ... }`
     on the next line is two statements; a free-standing block statement is not swallowed
     by the call on the line above.
  2. **`if`/`while`/`for` headers and a `match` scrutinee open no tail block** (nor does a
     `with` callee, §4.10): in `if f(x) { ... } { ... }` the first braces are the `if`'s own
     body. Parentheses restore it — `if (f(x) { ... }) { ... }`. A match arm's guard is
     **not** restricted: a guard is followed by `->`, not a block, so there is no body to
     swallow.
  3. **Refused when the previous token is `}`**: `if c { 1 } else { 2 } { 3 }`,
     `match x { ... } { ... }`, `P { x: 1 } { ... }` and `f(a) { ... } { ... }` do not mean
     applying a block to a value; and "one call takes at most one tail block" holds without
     a rule of its own. To apply a block to a value, parenthesise it first: `(...) { ... }`.
  4. **An uppercase name's braces belong to the record literal** (§2.3): `Column { ... }` is
     a construction, so a tail block never lands on a bare TYPEIDENT — component functions
     are lowercase. `Column(align: c) { ... }` is not affected: the parentheses come first,
     and the block attaches as usual.
  **In tail position the block binds parameters**: the head of `{ x => ... }` is its own
  production, not a block being reinterpreted (the way `Point { x }` uses braces without
  being a block). To write "a block whose value is a lambda", parenthesise:
  `f(a) { (x => e) }` — the group no longer closes with `=>`, so no head is read.
  **The tail block fills the last declared parameter/field** (Kotlin's rule), whatever named
  arguments came before it — "positional cannot follow named" does not apply to it — and
  defaults fill the remaining holes (#207): in `column(gap: 12) { text("hi") }` the block
  fills `body` and `align` takes its default. If that parameter is already filled the report
  is "the last parameter `body` is already given; the tail block is what fills it".
- **The tail block is the only trailing-argument form (#206 phase 2)**: the transitional
  `f(a) fn(x) => e` has retired, and the current spelling is only `f(a) { x => e }`. `fn` has
  no expression position; it is used only by named function declarations (§3.1) and function
  types (§2.2). The old trailing-closure spelling gets a dedicated migration diagnostic. A bare
  arrow lambda still cannot take the
  tail position: in `f(a) (x) => e` the `(x)` is already the curried call `f(a)(x)`, and the
  two readings cannot be told apart before the `=>` — that argument is about `(`, not
  braces, and it stands.
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
    from what surrounds it". A `Char` is the same with a different delimiter:
    `to_string('a')` is `a` while `['a']` is `['a']` (§1.5), so `List[Char]`, `List[String]`
    and `List[Int]` all render differently.
    The trait method `show` is the **nested** one, so rendering a string through a
    `[T: Show]` bound does carry quotes; `to_string`/`${}` drop them only when the **static
    type is `String`** itself.
    **The rule is directed by the static type and not by the value**: `to_string("hi")` is `hi`,
    while the same call written inside `fn f[T: Show](x: T) = "${x}"` gives `"hi"`, because the
    static type there is `T` and the rendering goes through the `Show` witness. This has nothing
    to do with `Display` below; it has held since the day the two layers were drawn apart.
  - **A type can take over the top-level layer itself, by writing `impl Display` (§3.5).**
    `to_string(x)`/`${x}` first ask whether the **static type** of `x` has a `Display` impl: if
    it does, that is the rendering; only otherwise do the rest of this section's rules apply
    (including the `String` identity above). Two boundaries:
    - **An opaque type is peeled one layer at a time, and the question is asked again at each
      layer.** With no `Display` on `opaque type A = B`, `B`'s is used, and if `B` has none the
      peel continues. Peeling the whole stack before asking would make a rendering written on an
      inner layer stop working at the top level, which is the defect audit SEM-03 recorded.
    - **The `Show` layer does not move.** A type that writes a `Display` still renders through
      `Show` when it is nested inside a structure, and a type variable under a `[T: Show]` bound
      still renders through its witness (see above).
    `Show` is the nested one and `Display` the top-level one, matching Rust's `Debug` and
    `Display`; there used to be a single trait doing both jobs, and these two rules are where
    the seam was cut.

### 4.4 Pipelines

`x |> f(a, b)` is equivalent to `f(x, a, b)` — it puts the left-hand side into the **first
parameter**. `x |> f` is equivalent to `f(x)`. Standard library APIs are all designed around
"the main datum is the first parameter" so that they work with pipelines.

**`|>` is argument insertion into an ordinary call, and nothing else.** The right-hand side is
parsed as one expression by the postfix rules of §4.3; if its outermost form **already is a call**
(`f(a)`, `m.f(a)`, `r.m(a)`, `make()(a)`), the left-hand side goes in front of that call's
**written** arguments; otherwise the whole right-hand side is applied to the left-hand side.

```dawn
x |> f(a)          # f(x, a)
x |> f             # f(x)
x |> m.f(a)        # m.f(x, a)        a module alias is not a receiver
x |> r.m(a)        # r.m(x, a)        the receiver stays put, it is not re-inserted
x |> make()(a)     # make()(x, a)     not make()(a)(x)
x |> One(a)        # One(x, a)        a constructor is just another thing being called
```

The pipeline **introduces no node of its own**, and so:

- **Evaluation order is the order of the call written out: the target first (a dynamic callee or
  a receiver), then each argument in written order**, with the left-hand side being nothing but the
  first argument. `lhs |> make()(arg)` runs `make()`, then `lhs`, then `arg`. This is specified,
  not an accident of the implementation — a static callee has no evaluation effect, which is why a
  common pipeline still *looks* as if the left-hand side runs first. No hidden temporary is
  introduced to make the left-hand side run first visually.
- **Callability, arity, duplicate named arguments and the record restriction are all decided as
  for any call.** `x |> One(1, 2)` reports an arity error, `x |> k` (with `k: Int`) reports "not a
  function", `x |> Point { ... }` reports "not callable", and `x |> Point(1)` reports that a record
  must be built with braces (§2.4).
- **A module's functions are still not bare function values** (§10.3): `x |> m.f` reports that the
  module exports no such value. Only `x |> m.f(a)`, with the `(...)`, is a call; the difference
  between the two has nothing to do with the pipeline.
- A **function-valued field** of a record is called dynamically as usual: `x |> r.callback` is
  `r.callback(x)`.

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
- **The `fn` prefix has fully retired**: `fn(x) => e` no longer parses as a lambda, and the
  former tail-only `f(a) fn(x) => e` retired in #206 phase 2 as well. `fn` now appears only in
  named function declarations and function types; both old expression spellings have dedicated
  migration diagnostics.
- If the body needs several statements, use a block: `(x) => { ... }`.
- Written after a call (on the same line) it is that call's **last argument** — a tail
  block, see §4.3: `f(a) { x => e }` (the brace head binds the parameters); this is the only
  trailing-argument spelling.
  **A bare arrow cannot take the tail position**: in `f(a) (x) => e` the `(x)` is already
  the curried call `f(a)(x)`, and the two readings cannot be told apart before the `=>` is
  reached. The diagnostic names this.
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
for (key, value) in entries { println("$key=$value") }
while queue.non_empty() { ... }
```

- `for`/`while` are statements of type `Unit`, and `var` may be used inside the body to
  accumulate.
- `for pattern in source` and `for pattern in from..to` reuse the complete recursive pattern
  grammar, including tuples, lists, constructors, qualified constructors, or-patterns, and a
  line-leading `|` continuation. The pattern must be **irrefutable** for the item type; a
  refutable pattern is a compile error, not a filter that silently skips non-matching items.
- Pattern bindings are visible only in the loop body. The source and both range bounds are
  checked and evaluated in the outer scope, where those bindings are unavailable; code after
  the loop likewise cannot see pattern bindings or body locals.
- If an iterable source does not return (its type is `Never`), it is still evaluated exactly
  once and remains the statement's bottom path; no iteration witness, loop, pattern binding,
  or body is reached.
- `break` leaves the **innermost** loop and `continue` jumps to its next round. Both are
  expressions of type `Never` (like `return`, they may appear in expression positions such
  as a match arm); they are legal only inside a loop body, and **cannot cross a
  lambda/local-function boundary** to reach a loop outside (a lambda is a function of its
  own; use `return` to leave it). There is no labelled form — to break out of several
  levels, extract a function and use `return`. comptime loops support them equally.
  The statements after a `with` are also the body of a closure (§4.10), so a `break` there
  likewise cannot reach the loop outside — the diagnostic names `with` instead of talking
  about a lambda the author never wrote.
- **`for pattern in e` iterates any type that implements `Iter`** (a built-in trait, §3.5):
  `e` is evaluated exactly once before the loop starts; iteration desugars into ordinary trait
  calls to `iter_start/iter_done/iter_next/iter_get`, and the
  element type is that impl's `Item`. The five std containers
  (`List`/`String`/`Bytes`/`Map`/`Set`) iterate out of the box; a parameter bound by
  `[C: Iter]` in a generic function is equally `for`-able (dictionary forwarding). The
  iteration order is the impl's cursor order (`String` by code point, `Map`/`Set` the same
  as `entries`/`to_list`).
- `for pattern in a..b` supports half-open integer ranges (not via `Iter`, with `Int` items).
  `a` is evaluated before `b`; each bound is evaluated exactly once, and both are evaluated
  before the loop starts.
  These guarantees also hold when the range is empty.

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
- **The landing point is the same one as the tail block's** (§4.3): `f(a, b)` grows
  one argument, `r.m(a)` grows one argument, and a bare name `g` becomes `g(x => ...)`. So
  `with` combined with a tail block is just an ordinary call; there is no third rule.
- **A `with` callee opens no tail block** (#206): `with x <- f(a) { ... }` is refused —
  `with` is about to attach the rest of the block as `f`'s last argument, so the `{` would
  be a second closure on the same call. The diagnostic names this; parenthesise the call to
  attach the block, or drop the `with`.
- **`?` passes through transparently**: what the closure hands back is the value of the
  `with` call, and that is the block's value, so an `Err` propagated by `expr?` inside the
  sugared region becomes the return value of the enclosing function — and `bracket`'s
  release still runs (cross-check in `scripts/spike-native/with_sugar.dawn`).
- **`return`/`break`/`continue` are rejected inside the sugared region**, and the diagnostic
  names `with`: what they would have to cross is a closure boundary the author never wrote,
  and "getting out" only means what the reader thinks it means when that block happens to be
  in tail position. A loop **of its own** inside the sugared region is unaffected (a `for`
  after the `with`, with `break` belonging to it).
- **The sugared region cannot touch a `var` declared before the `with`**, and the diagnostic
  names the closure `with` introduced: the sugared region is that closure's body, and a closure
  captures by value and refuses to capture `var` (§4.5). So every `var` declared **before** the
  `with` can be neither assigned nor read in the rest of the block after it; a `var` declared
  **after** the `with` belongs to the sugared region itself and is unaffected. To carry a value
  from before the sugared region into it, bind a snapshot with `let` first, or pass it in as a
  parameter.

  ```dawn
  var n = 1
  let base = n          # snapshot it first; reading n after this is refused
  with x <- g
  var acc = base + x    # a var declared inside the sugared region is fine
  ```
- Write one name at the binding site, with the same rules as a lambda parameter; there is no
  `_` form (nor do lambda parameters have one).

> Why `bracket` and not `defer`: the protected interval is always exactly one closure call,
> `return`/`break` cannot get out of it at the language level, and so the compiler owes no
> escape-rewriting pass.
> The criteria are in `docs/core-move2-design.md` §2.6 and §6.

### 4.11 List literals and their element forms

```
list_lit  = "[" [ list_elem { list_sep list_elem } [ list_sep ] ] "]"
list_sep  = "," | NL                   (* a newline is the same separator as a comma;
                                          adjacent, the two count as one *)
list_elem = expr                       (* an ordinary element: contributes one *)
          | ".." expr                  (* a spread: contributes 0..n *)
          | if_no_else                 (* a conditional element: contributes 0 or 1 *)
if_no_else = "if" expr block { "else" "if" expr block }   (* no final else *)
```

```dawn
column([
  header,
  ..body,                            # body: List[Widget[Msg]], spliced in whole
  if m.note != "" { text(m.note) },  # a line only when there is something to say
  help,
])
```

**Separators: a newline is a comma.** Inside a multi-line list literal the commas between
elements may be dropped, and one newline is one separator:

```dawn
column([
  header
  ..list.map(m.todos, t => item_row(t))
  if m.note != "" { text(m.note) }
  dim(text("commands"))
])
```

The two separators may be mixed within one literal, a trailing comma or newline is still allowed,
and both `[]` and a `[\n]` spanning lines are still zero elements. This is a **pure syntactic
addition**: `[1, 2, 3]`, a multi-line literal with commas, and a trailing comma all parse to
exactly what they parsed to before. `dawn fmt` does not rewrite either spelling into the other
either; the author's choice of separator is kept, since the formatter only adjusts spacing within
a line and indentation, never the line breaks the author wrote.

**What is dropped is only the comma at a line break.** Two elements on one line still need one:
`[a b]` is a syntax error, and the diagnostic is the same "expected `]`, found `b`" at the same
position.

**Which newline is a separator is decided by §1.7, not by this rule.** An element is parsed by the
ordinary expression rules first, an operator that may lead a continuation line (`|>`, `.`, a binary
operator) is still swallowed by the element above it, and the newline left standing is the
separator:

```dawn
[
  xs
    |> f        # one element: `|>` leads a continuation line, which has nothing to do with lists
  a
  -1            # two elements: `+`/`-` never lead a continuation (§1.7), so `-1` is a prefix
                # minus opening a new element
]
```

`+` has no prefix meaning, so a `+` at the start of a line lands at an element position and is
refused there, with "expected an expression, found `+`". That is what the `+`/`-` exception does at
an element position, not an extra rule of the list literal's own.

**A line-leading `..` always reads as a spread**, never as a range continuing the line above. `..`
is not an expression operator (all four of its meanings are positions, see below) and the range
`a..b` appears only in a `for` header (§4.7), so the left-hand literal below is two elements rather
than one range:

```dawn
[
  a
  ..xs        # a spread element
]
[0..3]        # still refused: `..` between two values, and not at the start of an element, is
              # neither of its meanings
```

The three element forms hold **only inside a list literal**. Tuples, records and constructor
arguments do not know them; the pattern `[x, ..rest]` (§5.1) is a different thing — the rest of
a destructuring, spelled symmetrically with the spread here and meaning the opposite.

**The spread `..xs`**: the operand must be a `List[T]`, and each of its elements is laid out in
place. Anything else is "`..` spreads a list, but this is …". `..` is never legal in expression
position; it appears in exactly these places: the range in a `for` header (§4.7), the record
spread `P { ..p }` (§2.4), the rest pattern (§5.1), and the element spread here.

**The conditional element `if c { x }`**: a true condition contributes one element `x`, a false
one contributes none. `x`'s type joins the element type, and **it need not be `Unit`** — the
rule that an `if` without an `else` must be `Unit` (§4.6) does not apply at this position,
because nothing here needs it to produce a value.

**An `else if` chain is one element form as a whole**: `if a { x } else if b { y }` contributes
0 or 1, taking the arm whose condition is first true, and none if no condition is. However deep
the chain, it is one element form.

**A chain that does end in an `else` is not an element form**; it is an ordinary element, and it
means exactly what it meant before this feature existed: `[a, if c { x } else { y }, b]` is
always three elements. Hence a **deliberate asymmetry** — the else-less form may be omitted, the
form with an `else` may not be expanded:

```dawn
[a, if c { x }]              # 0 or 1: a conditional element
[a, if c { x } else { y }]   # always 1: an ordinary element, one of two
[a, if c { ..xs } else { ..ys }]   # illegal: `..` is not at an element position
```

The reason is to **take the smallest cut**. Letting the form with an `else` expand too means
making both branches of an `if` be *a run of elements* rather than a value — Dart's
collection-if/collection-else, a second `if` grammar that holds only inside a collection
literal, and with it a string of further questions about whether the `else` branch may nest a
`for`, another `if`, and so on. The else-less form needs **none** of that: in ordinary
expression position it could only ever be `Unit`, so moving it to an element position collides
with no existing meaning. The same reasoning rules out a collection-for (`[for x in xs { f(x) }]`):
`list.map` already writes it, and adding `for` immediately raises "why is there no `while`".

**Evaluation order** is left to right, and the element forms do not change that. A conditional
element's body **is evaluated only when its arm is taken**.

**Typing**: every element form's contribution joins one element type `T`, and the literal is a
`List[T]`. An ordinary element contributes its own type, a spread contributes the `T` of its
`List[T]`, a conditional element contributes the common type of its arms' bodies.

**The expected type is pushed down**, which is what the element forms are really for: once `T`
is settled — from the literal's expected type, or from any element already checked — every later
element is checked *at* `T`. A spread's operand receives `List[T]`, and **each body** of a
conditional element receives `T`. So:

```dawn
# text: fn text[M](s: String) -> Widget[M], where M appears only in the return type
[text(s)]                    # error: cannot infer type parameter(s) M
[header, text(s)]            # fine: header settles M as Msg first
[header, if c { text(s) }]   # equally fine: the expectation crosses into the body
```

The third line is why intermediate bindings like `let note: List[Widget[Msg]] = if …`
**disappear**: a standalone `[text(s)]` binding has no sibling to ask and must be annotated,
while the same things written as elements of one literal need no annotation. Elements that
cannot be checked without an expectation (a bare `None`, a nested `[]`) are still checked in a
second round, so they do not depend on source order.

> **Breaking change in meaning (after v0.67.0)**: `[if c { <a Unit expression> }]` used to be
> legal, of type `List[Unit]`, and **always of length 1** — the `if` inside was an ordinary
> element, evaluated as a statement and producing `()`. The same source now has length 0 or 1,
> and the body is not evaluated at all when the condition is false. **Nothing is reported; the
> behaviour changes silently.**
>
> The affected programs are exactly the family "a conditional element whose body has type
> `Unit`", no more and no less: before the element forms, an `if` without an `else` in
> expression position could only be `Unit` (§4.6). Landing this, every `.dawn` file in
> dawn-lang (566) and in the dawnop-site backend (84) was scanned file by file with the new
> parser: **zero existing occurrences**.
>
> No transitional diagnostic was added, because it could only be an error: Dawn's diagnostics
> have no severity — `Diag` carries `msg/lo/hi/hint` and everything is an error. And making "a
> conditional element whose body is `Unit`" an error would carve a permanent hole in the new
> form's typing rule to protect a class of programs measured not to exist; a `List[Unit]` of
> length 0 or 1 is coherent under the new rule. A transition ends; a special case in a typing
> rule does not.

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

Adjacent match arms must be separated by a **physical newline** or `,`. A comma may be
followed by a newline, and a trailing comma after the final arm is allowed. Whitespace alone is
not a separator: `match x { 0 -> 1 1 -> 2 }` reports the missing newline or comma at the second
`1`, rather than treating a token that looks like a pattern as an implicit boundary. This does
not change §1.7 newline continuation: a newline nested inside `()`, `[]`, or `{}` still belongs
to the arm body expression.

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

`|` has the lowest precedence in a pattern. It may occur recursively inside constructor, record,
tuple, and list patterns, and is collected in source order as a flat n-ary or-pattern. `(pat)` is
grouping only; a tuple pattern still requires a comma. The `|` may start a continuation line, as in
`A\n  | B`. A newline followed by a pattern without `|` still starts the next match arm. At run time
the first matching alternative is selected, with no backtracking inside that or-pattern. A match-arm
guard applies to the whole or-pattern and runs at most once. If it is false, matching continues at
the next arm. The body also runs at most once.

Every alternative must bind exactly the same name set, and each shared name must have the same type.
The enclosing `let` or `var` selects mutability once for the whole pattern, so alternatives cannot
differ on it. The first alternative supplies the canonical binding in the shared environment; later
alternatives only provide another path that assigns its value.

### 5.2 Exhaustiveness

`match` **must be exhaustive**. The compiler checks exhaustiveness on ADT/Bool/Option/Result/tuple;
a missing arm is an error and the missing constructors are listed. A match on
`Int`/`String`/`Float` must have a `_` or a binding arm as the catch-all.

`let` also accepts irrefutable patterns: `let (a, b) = pair`, `let Point { x, y } = p`, and
`let m.Only(x) = value` for an imported single-constructor type. Or-patterns use the same usefulness
check, so `let true | false = flag` is valid while `let true = flag` remains refutable and is
rejected.

The compiler normalizes type-known complete alternatives, including `true | false`, before the
usefulness search. The remaining search has a deterministic work budget. If that budget is exhausted,
an otherwise legal `match` or structural `let` is rejected with `pattern analysis exceeded its
complexity budget` instead of guessing about exhaustiveness. The diagnostic advises simplifying
nested alternatives or splitting the pattern into smaller matches.

---

## 6. Effect system

### 6.1 Model

An effect row has two axes.

The base axis's two **ground** points are **pure** (the default, written nowhere) and **io**.
`!io` covers every observable side effect: files, network, clock, random numbers, printing,
mutable global state, and all Java interop. Two kinds of **non-ground** atom live on the base
axis as well, beside io rather than as special cases of it: **effect variables** (§6.3) and
**associated-effect projections** (§6.5).

The **label axis** is the finite set of named effects the user declares with `effect` (§6.5).
It is independent of the base axis: `!io` does **not** cover named effects. So an `!io` function
that performs `!Ask` still has to write `!Ask` in its signature.

**`io` wears two faces and they are read separately**, which is this section's main clause: under
**containment** `io` is an upper bound, so a signature that promises `!io` stands over a purer
implementation (including one that only performs effect variables); under **union** `io` is **not
an absorbing element**, so `!io !e` may not cancel `!e` and both atoms stay in the normal form
(printed `!(e|io)`). The full rules are in §6.6.

Both axes are trivially decidable: union is componentwise union of finite sets plus one boolean or,
containment is set containment per axis.

### 6.2 Rules

1. The effect of a function body = the union of the effects of every call in it.
2. A function whose signature is not marked `!io`, with an io effect appearing in its body →
   compile error (the error points out which call introduced io, and suggests adding `!io` to
   the signature or eliminating that call).
3. Marked `!io` but the body is pure → allowed (room reserved for evolution); a "redundant `!io`"
   lint needs type analysis, and the current `dawn fmt --check` only checks formatting — that hint is
   **not implemented** (left for later).
4. A pure function is **guaranteed**: same arguments return the same value, no observable side
   effects. The compiler may fold it, deduplicate it, and call it at comptime on that basis.
   Named effects are inside that guarantee too: a function value's type carries its full effect
   row, and the only thing that can subtract a label from a row is the `with handle` that really
   answered it (§6.5), so a function whose signature says pure cannot run somebody else's handler
   arm.
5. A function value's effects are answered **at the call**, not where the value was written. A
   closure's row is what its body performs, unrewritten at the creation point; if the row an
   individual call instantiates carries a named effect nobody answers, the error is reported on
   **that call** (§6.5).
6. `panic`/`todo`/`assert` do not count as io — they do not return (divergence is not an effect).
7. **No absorption.** An effect row may not drop a label, an effect variable or an
   associated-effect projection unless a handler answered it. Union drops nothing (§6.6); and when
   a function value goes into a slot, the slot's row must carry its row atom for atom, because a
   dropped atom is a dropped piece of evidence. The one subtraction point is `with handle` (§6.5),
   and it subtracts only the label it answers. A signature promising `!io` over a variable it binds
   is not a drop: that is containment (§6.6), and the variable still has an evidence slot from that
   signature's binder list.

### 6.3 Effect polymorphism

Higher-order functions use effect variables to forward the effects of their arguments:

```dawn
fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2)
```

- An effect variable `!e` needs no declaration; appearing in a signature introduces it, and its
  scope is the whole signature. It may also be given an **explicit binder** in the parameter list:
  `fn map[T, U, !e](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`. The two spellings are
  equivalent. When a signature carries an explicit binder, that name resolves only to it within
  the signature; a name with no binder is still introduced where it appears, and the two may be
  mixed in one signature. A binder carries no bound (`[!e: X]` is an error), its name must be
  lowercase (`!E` is a named effect, not a variable), neither `!io` nor `pure` can be a binder
  name, and the same binder cannot be written twice.
  `pure` is refused in **every** row position, not only as a binder: it reads as "pure only" and
  would behave as "any row at all", which is the opposite. The empty row has its own spelling,
  `!()` (§6.6).
  The binder list is also where the order comes from: it binds in the order written, and names
  with no binder are still introduced in the order they first appear.
- A type declaration can bind effect parameters too: `alias Mapper[T, U, !e] = fn(T) -> U !e`,
  `type Box[!e] = { f: fn(Int) -> Int !e }`. **Only through a binder**: a type declaration is not
  a signature, so "introduced by appearing" does not apply there, and writing a **variable** the
  declaration does not bind is a compile error — put it in the parameter list, write `!io`, or
  leave it pure. Several `!e` in one declaration are one variable; the `!e` of another
  declaration is unrelated.
  **A named effect is not under that restriction**: `alias A = fn() -> Int !Ask` and
  `type Boxed = { f: fn() -> Int !Ask }` are both legal. A label is not a variable and has no
  binder to speak of; it means "whoever calls this function value supplies the handler", which is
  exactly where evidence travels today (§6.5).
- **An effect parameter a nominal type binds carries empty evidence only.** What is restricted is
  **instantiation**, not spelling: the `!e` of `type Box[!e]`, `type Chain[!e]` or
  `opaque type Hidden[!e]` may only solve to a row that owes no evidence, which means pure, `!io`,
  or the variable itself (forwarded unchanged, `fn store(b: Box) -> Box = b`). A row carrying a
  named label, an associated-effect projection, or a variable bound **elsewhere** may not travel
  into a consumer through this channel. The reason is that the channel does not exist: a variable a
  signature binds has a hidden evidence parameter to travel in (§6.5 "Implementation"), one a
  nominal type binds has none, a record is not a frame, and a nominal type's identity keeps only
  its name and its type arguments (two bullets down), with nowhere to remember a row per use site.
  To make a row that really owes evidence travel, bind the variable on the function that runs the
  closure (`fn f(g: fn() -> Int !e) -> Int !e`), or use a transparent `alias` and write the effect
  argument at the use site (next bullet).
- An effect argument may be written at the use site, and **only a transparent `alias` takes one**:
  `Thunk[!io]`, `Thunk[!Ask]`, `Thunk[!e]`, `Mapper[Int, String, !(Ask | e)]`. The position takes
  **everything the inline row position takes**, and nothing less: a transparent alias is its
  expansion, `Thunk[!Ask]` and `fn() -> Int !Ask` are two spellings of one type, and a row that can
  be written inline does not become unwritable by passing through an alias.
  The argument is resolved in the **use site's own scope**, read exactly as the same row written
  inline: `!e` names the variable the consumer's signature binds (introduced by appearing), `!Ask`
  is the named effect visible here, `!T.E` is the projection here. Substitution runs position by
  position in declaration order, the alias's own variable is replaced, and the result joins
  whatever row the expansion already had under set semantics (flattened, deduplicated, and `io`
  absorbs nothing, two bullets down): on `alias IoThunk[!e] = fn() -> Int !io !e`, `IoThunk[!Ask]`
  is `fn() -> Int !(io | Ask)`.
  The argument shares the brackets with the type arguments and is positioned within its own list
  (the declaring side splits `[T, U, !e]` the same way), so writing one between two type arguments
  does not move the type arguments.
  **A record, a variant and an `opaque type` do not take one**: such a type is its name plus its
  type arguments, with nowhere to remember the row, so accepting one would leave two types either
  indistinguishable or distinguishable but printed under one name. A transparent alias has no
  identity to remember it in; it expands in place, and the argument lands in the expansion.
- Omitting the effect argument stays legal and is **not an arity error**: `Mapper[Int, String]`
  gives the type arguments only. The omitted slot is still the declaration's own effect variable,
  solved from context: store a pure closure and it solves to pure there, store an `!io` closure and
  it solves to `!io` there. **A consumer's own row has to cover it**, and an `!e` bound by that
  signature alone does not cover a variable bound elsewhere. An alias's way out is to write the
  argument (`Mapper[Int, String, !e]`, with `!e` bound by this signature); a nominal type has no
  such way out, and a consumer writes `!io` (`!io` covers any row).
- `!(e1 | e2)` is a union, stored **normalised**: union is componentwise (a boolean or on the io
  bit, plain set union on the variables, the projections and the labels), `pure` is the identity
  (and can be dropped), and a row that can take a smaller shape takes it (`!(e|e)` is `!e`).
  **`io` absorbs nothing**: `!(io | Ask)` is exactly `!(io | Ask)` and `!io !e` is exactly
  `!(e|io)`; neither collapses to `!io`. The full rules, and their closure, are in §6.6.
- An effect variable spans both axes: `!e` can be instantiated to a row carrying labels. In
  `map(xs, x => ask())` the `!e` of `list.map` instantiates to "pure + {Ask}", so performing a
  named effect inside a `for` body goes through just as well.
- Instantiation puts **no limit on how many atoms** a variable stands for: one `!e` may solve to a
  single label, to a union of labels (`!e := !(Ask | Tell)`), to another variable, or to a mixture
  of labels and variables (`!e := !Ask !e2`). There is **no** "one variable, at most one label" rule.
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
`with handle` **lexically nearest to the call** answers it.

There are two tiers of arm. A **tail-resumptive** arm is an ordinary closure that is "called in
place, its return value is the operation's result", with no continuation capture. A **control arm**
carries one more clause (`op(args…) resume k => expression`): `k` binds the continuation of that
operation, and the arm's value is the value of the whole `with handle` block. A control arm can be
written only under an effect declared `ctl`, and the rules for it are collected in "Control arms"
below. Whether the binding clause is there is the arm's kind marker. For the design and the verdicts
see [`docs/effects-design.md`](effects-design.md) and
[`docs/oneshot-design.md`](oneshot-design.md).

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

```dawn
ctl effect Fetch {
  fn fetch(url: String) -> String
}
```

- Effect names are UpperCamelCase and share one namespace with types and traits.
- A declaration may carry a `ctl` prefix, which says "an operation of this effect may be suspended
  by a control arm". `ctl` is a **contextual keyword** (as `handle` and `resume` are), never
  reserved, and it is still usable as an identifier, a parameter name and a function name. With a
  visibility the order is `pub ctl effect E`: `ctl` sits where `opaque` sits, between the visibility
  and the keyword it modifies.
- An operation is an ordinary function signature: no body, and it **must not carry an effect
  annotation of its own** (an operation's effect is the effect it belongs to); it currently must not
  carry type parameters either.
- Operation names enter the module's function namespace: sharing a name with any top-level
  declaration of this module (an ordinary function / a trait method / another effect's operation)
  is a redefinition error; sharing a name with something **introduced from elsewhere** (including a
  same-named operation brought in by another effect) is an error too. The operations of a
  `pub effect` come in together with `use m.{Ask}`, and `m.ask(…)` can also be written.
- An effect itself carries no type parameters; `effect Yield[T]` is currently unsupported.

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
  reported on **the call nobody answers**, with two ways out: add the annotation to the
  signature, or `with handle` on the spot. Calling an operation directly, that call is the
  operation call; where the label arrives through a function value or an effect-polymorphic call,
  the report lands on **that call**, not on the callee's definition.
- Only `pub fn main` must have an empty label set — it has no caller to supply evidence, so the
  "nobody answers" error lands on `main`'s own signature. An ordinary `pub fn` may carry the label
  of a `pub effect`, for its caller to propagate or handle; it is a *private* effect in a public
  surface that the export-surface validation refuses (§3.3).

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

- An arm has the form `op(args…) => expression` (a tail-resumptive arm) or
  `op(args…) resume k => expression` (a control arm, see "Control arms" below), `=>` being the same
  notation as in a lambda (an arm is a closure to begin with), and arms are separated by newlines.
  Every declared operation gets **exactly one arm**: too few arms, too many arms, and an arm whose
  name does not belong to the effect are all compile errors. Both kinds of arm may sit in one
  handler.
- One `handle`, one effect; handling the same effect again is inner shadowing outer, which is legal.
- Handling an effect the block never actually performs is allowed (harmless dead evidence).
- **Handler-local state (cells)**: the head of the arm table may declare any number of `var`s, each
  one slot of mutable state private to **this installation**. A cell is reachable from **the arms of
  this installation** and from **the rest of the block after the `with handle`**: an arm reads and
  writes it, the rest of the block reads it. That is the one and only surface by which a stateful
  handler hands what it accumulated back to the installation point; there is no second route such as
  a `return` arm. Three attendant rules: cells **must all come before the arms** (interleaving them
  with arms is a compile error with a diagnostic of its own, so that no reader has to guess whether
  declaration order means anything); **the type annotation is mandatory** (there is no context to
  infer from inside the arm table's braces); and what is declared here is a **position**, not a new
  spelling (`var` and assignment are the same two constructs as in §4.1, and a cell merely adds one
  more legal place to declare one). A cell itself has no spellable type; a user cannot write one down.

  ```dawn
  with handle Emit {
    var acc: List[Int] = []        # the cell: annotated, and ahead of every arm
    emit(n) => { acc = acc ++ [n] }
  }
  body()
  acc                              # the rest of the block reads it: this is the hand-back surface
  ```
- **A `var` declared before the installation point is out of reach after it** (this is §4.10's
  capture-by-value discipline showing up here): every `var` declared **before** the installation
  point can be neither assigned nor read in the rest of the block after the `with handle`; a `var`
  declared **after** the installation point is entirely normal. The diagnostic names the closure
  `with` introduced and offers two ways out: bind a snapshot with `let` first, or pass it in as a
  parameter. An arm is a closure too, and likewise refuses to capture an ordinary outer `var` or to
  assign to one. **The one exception is this installation's own cells**: the `var`s declared by the
  item above are readable and writable from the arms, because they are not outer bindings captured
  into the arm but this installation's own state.

  ```dawn
  var n = 1
  let base = n                    # snapshot it first; reading n after this is refused
  with handle Ask { ask() => 42 }
  var acc = base + ask()          # a var declared after the installation point is normal
  ```
- **Typing rule**: let the rest closure's effect be `(base, L)` and each arm body's effect be
  `(base_i, L_i)`; then the block that installs the handler is recorded as
  `(base ∪ ⋃base_i, (L ∖ {E}) ∪ ⋃L_i)`.
  The subtraction is at this node: the rest is a closure and **this node is what supplies its
  evidence**, so this node is the only thing that can take `E` off the row. **Subtraction follows
  supply, not execution**: under a control arm the rest may be run by a continuation that has
  travelled elsewhere (see "Control arms"), and the evidence it wants is still the pack this node
  built at the installation point and handed over. A handler that never supplied `E` can therefore
  take nothing away. The base axis is not subtracted: `!io` is not something `handle` answers.
  The effects the arm bodies perform themselves (including io, including other labels) are all
  unioned back onto the block — an arm runs where the handler is installed, not where the operation
  is performed.
  **"A row losing a member" happens at `with handle` and nowhere else**, and it does not enter
  unification.
- **`?` leaves early and the state is discarded**: `?` still passes through a `with handle`
  transparently (§4.10), cells or no cells. What an early exit discards is the state of **this
  activation**, whose cells are destroyed with it; the line in the rest of the block that reads a
  cell is one that was never going to run anyway, so there is no hand-back surface that looks
  certain to run and quietly does not. A continuation a control arm stored before the early exit is
  unaffected: it carries the cells of its own activation, and resuming it resumes another lineage of
  state. This reading is not an invention of this language: it is the literature's
  **local state interpretation** (Wu / Schrijvers / Hinze, *Effect Handlers in Scope*, Haskell 2014),
  the standard answer for a state handler installed inside the error boundary.

```dawn run
use std/io

effect Emit {
  fn emit(n: Int) -> Unit
}

fn body() -> Unit !Emit = {
  emit(1)
  emit(2)
}

pub fn main() -> Unit !io = {
  with handle Emit {
    var acc: List[Int] = []
    emit(n) => { acc = acc ++ [n] }
  }
  body()
  io.println("${acc}")
}
```

```output
[1, 2]
```

That is the shape cells exist for: the `emit`s scattered through `body()` accumulate into `acc` in
the order they were performed, while `body`'s signature says only that it performs `!Emit` and says
nothing about where the values end up.

#### Lexical scope and the supply point

Evidence (the handler's arms) is resolved **lexically**: an operation call binds to the lexically
nearest `with handle`. Evidence enters the callee with the call; a closure captures no handler at
its creation point. Consequences:

- **The handler is the call site's, not the creation point's.** A closure built inside a handle
  block that escapes outside the block and is then called does **not** carry the original handler:
  its row still holds `!E`, and the handler in scope at the call answers it, or the error is
  reported there. The type states "who has to supply the handler", and has nothing to do with what
  the arms do; a handler with pure arms yields an escaping closure that is `!E` too.
- **A cell does not escape its lexical region.** A state cell is reachable only from the arms and
  the block remainder of this installation, and being captured by any closure that does **not**
  belong to this installation is a compile error, with a diagnostic for each of the three
  phrasings: a lambda hand-written inside an arm (what is licensed is the arm, not a closure the
  arm builds), the block remainder after a `with x <- f(…)` (`with` introduces another closure, and
  that closure is outside the `with handle` that declares the cell, so the way out is to read the
  cell before the `with`), and the arm of another installation. Nor can a cell itself be passed out
  of the region as a value: it has no spellable type. The contrast is an ordinary `let`: a value
  bound with `let` inside a handler's region may still be captured by an escaping closure, and this
  ban tightened cells and nothing else.
  **A continuation is the one thing that can carry this activation's state out of the block**, and
  what it carries out is not a new name: the block's rest closure is still applied in place exactly
  once, what escapes is that closure part-way through, and the continuation carries the cells of
  **its own activation**. So "no second name reaches this cell" holds at the level of names,
  unchanged.
- Performing **this same effect** inside an arm body binds to the **outer** handler for that effect
  (it does not answer itself); with no outer one the arm owes the label and the error is reported
  as usual.
- **Reentrancy**: an arm gets the evidence environment of the layer **before** the installation
  point, so a cell of one installation is touched only by the arms of that installation. Nested
  installations each have their own cells, and what the inner one accumulates does not leak into
  the outer one.
  The classic lost-update shape "read the cell, call out, write the cell" cannot be built at the
  **tail-resumptive** tier: whatever route the intervening call takes, it never gets back to the
  same cell. **Under a control arm it can be built**: the arm reads the cell, calls `k`, the rest
  performs the same effect again, and the same arm is entered again. The answer is that a cell's
  unit is **one activation**, and the re-entered arm reads the cell of **this** activation; when one
  installation is activated recursively, each activation has its own, and resuming a continuation
  goes back to the one belonging to its own activation. (This used to be promised for the
  tail-resumptive tier only, with an escape hatch saying that once multiple `resume`s were allowed a
  cell would have to be copied along with the continuation. This section is where that hatch is
  used.)
- Performing **another** effect inside an arm body is answered by the handler in scope at the
  **installation point**, not by the one in scope where the operation was performed: the arm runs
  at the installation point.

```dawn run
use std/io

effect Ask {
  fn ask() -> Int
}

fn escaping() -> fn() -> Int !Ask = {
  with handle Ask { ask() => 7 }
  () => ask() + 1
}

pub fn main() -> Unit !io = {
  let f = escaping()
  with handle Ask { ask() => 2 }
  io.println("${f()}")
}
```

```output
3
```

`ask() => 7` answers the operations performed inside its own region, and `f()` happens outside it,
so `f`'s row keeps `!Ask` and the handler here in `main` answers it.

#### Control arms: the `resume` binding and one-shot continuations

A control arm has the form `op(args…) resume k => expression`, with `k` named by the author. It can
be written only under a `ctl` effect; an arm of a non-`ctl` effect that carries the binding clause is
a compile error, and the diagnostic names that arm and asks for the declaration to be changed.
Suspendability is a property of the **declaration**, because a row names effects and that is all the
Java boundary can read. `ctl` is a licence rather than a requirement: a tail-resumptive arm with no
binding clause is legal under a `ctl` effect.

- **The answer type**: let the type of the rest of the `with handle` block be `A`; then **the
  block's type is `A`**, every control arm's body must be `A` too, and `k`'s type is `fn(R) -> A`
  (its row is the next point), where `R` is the return type declared for that operation. `A` is
  not a new type variable, it is the type of the rest of the block; in a handler with no control
  arm this rule says nothing.
- **The arm's value is the block's value**, and has nothing to do with the operation's declared
  return type. Not resuming at all is legal: the arm's value becomes the block's answer directly,
  and the part of the block after the suspension does not run again.
- **`k` is an ordinary function value**, with no type of its own: it goes in an ADT field, in a
  cell, in a list, and it may be called after the frame that installed the handler has returned.
  **Its row is the io bit of the rest of the block's row, on the base axis**: if the rest has io, or
  an effect variable or an associated-effect projection (either may be instantiated with io, so
  they fold in conservatively), `k` is `fn(R) -> A !io`; otherwise it is the pure `fn(R) -> A`.
  Labels never travel. Dropping the labels is not leniency but a consequence of the supply-point
  discipline (see "Implementation" below): the pack the rest of the block wants was built at the
  installation point and handed to the continuation, so whoever calls it neither has to supply one
  nor can. The io bit travels because it occupies no evidence slot and asks the caller for nothing;
  the one thing it forbids is resuming or discarding a rest that does io from a frame whose
  signature says pure. So §9.8.1's "a fault only comes from io" needs no exception for
  continuations.
- **`k` is deep**: calling it reinstalls this installation, so the rest of the block performing the
  same effect again after the resumption is answered by this installation, reading the cells of this
  activation.
- **One-shot is dynamic**: a continuation is spent at most once. The type does not say so and does
  not try to; spending it a second time is a panic (the message is in the table below), not a
  catchable fault.
- **`?` inside a control arm**: it is judged against `A`, and so requires `A` to be an
  `Option`/`Result`. It means **abandon the continuation** and let `None`/`Err` be the answer of the
  whole block. Before the call to `k` it abandons a continuation that was never resumed; after the
  call to `k` it throws away the value the rest of the block already handed back, which is a value
  and not state.
- **It does not cross to Java**: a function value whose row names a `ctl` effect cannot be converted
  to a Java functional interface, and the conversion point is a compile error (§9.4), because there
  is no Dawn frame under a Java frame to suspend into. Only **written** labels are judged
  statically. On the other two axes, an effect variable and an associated-effect projection, the
  conversion point cannot know what the caller will instantiate `!e` with; those are caught at run
  time, and a suspension nothing can catch is a panic rather than a wrong answer.

```dawn run
use std/io

ctl effect Ask {
  fn ask(n: Int) -> Int
}

fn release(tag: String) -> Unit !io = io.println("release ${tag}")

fn resumed() -> Int = {
  with handle Ask { ask(n) resume k => k(n + 1) }
  ask(1) + ask(10)
}

fn bare() -> String !io = {
  with handle Ask { ask(n) resume k => "dropped at ${to_string(n)}" }
  with r <- bracket("bare", release)
  "held ${r}, then ${to_string(ask(1))}"
}

fn explicit() -> String !io = {
  with handle Ask {
    ask(n) resume k => {
      discard(k)
      "discarded at ${to_string(n)}"
    }
  }
  with a <- bracket("outer", release)
  with b <- bracket("inner", release)
  "held ${a} and ${b}, then ${to_string(ask(1))}"
}

pub fn main() -> Unit !io = {
  io.println(to_string(resumed()))
  io.println(bare())
  io.println(explicit())
}
```

```output
13
dropped at 1
release inner
release outer
discarded at 1
```

`resumed` is one round trip: `k(n + 1)` runs the rest of the block with that value as the result of
that `ask`, and what the rest produces is the arm's value, which is the block's. `bare` and
`explicit` are the two halves of the ruling below.

#### Abandoning a continuation

A continuation that was captured and never resumed ends in one of two ways, and the language
recognises only an **explicit** trigger.

- **A bare drop runs nothing.** Drop the last reference and not one `release` of the brackets inside
  the frozen computation runs (`bare` above: there is no `release bare` line, and that is the whole
  assertion). This is a ruling rather than an oversight. Triggering cleanup off reclamation would
  give one source program two observable behaviours on two backends, because the JVM's GC does not
  fire when native's reference counting does; and the destructor route is closed too, since a
  `release` is arbitrary user code with a lexical environment that no runtime can call on its own.
  The **memory** a dropped continuation holds is reclaimed by the implementation, and this
  specification does not promise when.
- **`discard` is the sanctioned path.**

  ```dawn
  fn discard[T, U, !e](k: fn(T) -> U !e) -> Unit !e
  ```

  It resumes the abandoned computation with a poison, so the unwind lands on every `bracket` between
  the suspension and the installation and runs its `release`, **innermost first**, and then answers
  `Unit`. The parameter's type is the continuation's own type and nothing narrower: `k` was ruled an
  ordinary function value above, and this does not take that back. So any function value satisfies
  the type and **whether it is a continuation is decided at run time**. `!e` is the continuation's
  own row: discarding a pure rest's continuation is pure, discarding one that carries io is `!io`,
  and discarding owes the same row resuming does. `discard` spends the same
  ticket a resumption spends: a discarded continuation cannot be resumed, and a resumed one cannot
  be discarded. Comptime refuses it.

Each of the four misuses has a verbatim message, and they are **written once, in the output of the
program below**, in this order: resuming a continuation already spent; discarding one already spent
(discard-then-resume, resume-then-discard and discard-twice are one ticket, so they are one
message); `discard` on a function value that is not a continuation; suspending during a discard's
unwind. (Writing them a second time would be an uncorroborated copy: this document's gate runs the
program and compares the `output` fence, and it does not read a table of prose.)

```dawn run
use std/io

ctl effect Ask {
  fn ask(n: Int) -> Int
}

type Held =
  | Ready(v: Int)
  | Waiting(k: fn(Int) -> Held)

fn plain(n: Int) -> Int = n

fn twice() -> Int = {
  with handle Ask { ask(n) resume k => k(n) + k(n) }
  ask(1)
}

fn escaping() -> Held = {
  with handle Ask { ask(n) resume k => Waiting(k) }
  Ready(ask(1))
}

fn spent() -> String !io =
  match escaping() {
    Ready(v) -> "resumed ${to_string(v)}"
    Waiting(k) -> {
      discard(k)
      match catch_panic(() => discard(k)) {
        Ok(_) -> "discarded twice"
        Err(e) -> e.message
      }
    }
  }

fn suspending() -> String !io = {
  with handle Ask {
    ask(n) resume k => {
      discard(k)
      "unreachable"
    }
  }
  with r <- bracket("r", tag => {
    let _ = ask(99)
    ()
  })
  "unreachable ${r} ${to_string(ask(1))}"
}

pub fn main() -> Unit !io = {
  match catch_panic(() => twice()) {
    Ok(v) -> io.println(to_string(v))
    Err(e) -> io.println(e.message)
  }
  io.println(spent())
  match catch_panic(() => discard(plain)) {
    Ok(_) -> io.println("discarded a plain function")
    Err(e) -> io.println(e.message)
  }
  match catch_panic(() => suspending()) {
    Ok(s) -> io.println(s)
    Err(e) -> io.println(e.message)
  }
}
```

```output
dawn: continuation resumed twice
dawn: continuation discarded after it was already used
dawn: `discard` expects a continuation
dawn: a `ctl` operation was raised while a continuation was being discarded
```

Four more rules:

- **The poison is not a failure**: neither `catch_panic` nor `catch_fault` sees it. This is
  necessary rather than convenient: catching it would mean the abandoned computation can be
  resurrected out of its own cleanup and carry on from the barrier to the end. `bracket` releases as
  it always does, because it guards without catching (§9.8.2).
- **An inner activation inside the frozen span is discarded with it**: an inner handler activation
  that a bubble passed over is inside the abandoned span too, and the `release`s under it run as
  well, innermost first.
- **The unwind may not suspend**: a `release` may do io, may fail, and may open a `bracket` of its
  own, but it may not perform a `ctl` operation. The frames below the walk are already committed to
  going away and nothing can resume into them, so an unwind that suspends is an unwind that may
  never finish.
- **A failure escaping a `release` during the unwind does not follow §9.8.2's replacement rule**:
  the remaining `release`s still run, and the first failure is the one delivered, handed to whoever
  called `discard` after the walk is finished. The reasoning is recorded in §9.8.2.

**The two backends promise observational agreement and nothing more.** The mechanism of freezing and
resuming is **deliberately left out of this specification**: the JVM freezes the stack, native stops
running that stack and switches to another, and that difference is intentional. What is promised is
that one source program produces the same observable behaviour on both: the answers, the number and
order of the `release`s, and the message and the position of a panic. The corpora that compare those
byte for byte are `scripts/spike-native/ctl_resume.dawn`, `ctl_nested.dawn` and `ctl_discard.dawn`.

#### Boundaries (v1)

These are the v1 boundaries. "A written named effect" is no longer the reason for any of them;
each has its own criterion.

- **trait / impl methods**: a method's row is a full row — effect variables, named labels and
  associated-effect projections are all admitted.
  The variable is introduced by this very signature (§6.3's implicit introduction counts as
  *bound* here), synthesises no evidence, and leaves the dictionary slot untouched; a label is
  one exactly-typed evidence parameter on the slot; a projection is one **erased** slot — which
  evidence record fills it is the impl's decision, and the boundary only knows the slot exists.
  In `trait Container[C] { fn wrap(c: C, body: fn() -> Int !e) -> Int !e }` the `!e` is the
  **caller's**: one call of `wrap` takes a pure closure, another takes an `!io`
  one. The impl's and the trait's effect variables are paired **by position** (the order each
  signature introduces them: the row, then the parameters left to right, then the return type);
  the spellings need not agree, and unequal counts are an error. Once paired and reduced through
  this impl's associated-effect bindings, the impl's row must be covered by the trait's: pure
  always is (doing less than the row admits to is not a lie); an unrelated label or `!io` is
  not; **written labels are the exception and must match exactly on both sides** — each label is
  one hidden evidence parameter, the method's shape and not just its promise, and dropping one
  would change the method's arity.
  A trait method's **default body** is checked like any other body: it can forward along the
  variable or the erased evidence slot (call the closure), but cannot install a handler — a
  rigid effect has no name for `with handle` to spell.
- **comptime / const initialisers**: compile-time evaluation performs no named effect and cannot
  install a handler either.
- **Local functions**: a local `fn`'s row is `!io` or pure, and its body may not perform a label
  it does not itself handle; it is lifted to an ordinary function with no evidence parameter, so
  reaching an enclosing handler lexically is not the same as holding that evidence at run time,
  and the ways out are lifting it to the top level to declare the label, or installing a handler
  for it inside its own body.
- **Written function types**: `fn(…) -> T !E` is legal in every `TypeRef` position, including
  parameters, return types, `let` annotations, `alias` targets, record/variant fields, generic
  arguments, tuple elements, and trait / impl method parameter types. A written label reads as
  "whoever calls me supplies the handler", which is exactly its runtime meaning. An effect variable
  (`fn() -> Int !e`) is another spelling rather than a migration: it forwards the row to its own
  caller and takes a closure of any row. `!io` and associated-effect projections
  (`fn() -> Int !C.E`) are equally legal. A record field can hold a labelled closure, and the
  field's row is the row to supply when it is taken out and called.
- **Function values**: a labelled named function can be passed as a value; the row enters the
  value's type and the call site supplies the evidence. An **effect operation itself** cannot: an
  operation call is "read the evidence field + call the closure", so there is no function symbol to
  take, and the diagnostic says so. Write it as a lambda (`() => ask()`).
- `unsafe_pure` masks io only, **not labels**: labels are the input to evidence synthesis, and
  masking one breaks the parameter.
- **Effect-polymorphic code forwards, it does not install handlers**: `with handle E` names one concrete
  effect syntactically, so the point where a handler is installed is always monomorphic. A `!e` in
  a signature can only pass the row along; installing a handler means writing the effect's name.
  The other face of the same wall is that `pub fn main`'s labels must be empty.

#### Implementation (informative)

Each `effect E` makes lowering synthesise an ordinary record type (whose name the user cannot
spell), with one field per operation holding its closure, plus one trailing `env` field: the
evidence environment the arms run in, filled at the **installation point**. `with handle`
constructs that record and binds it to a local; an operation call = read the field + call the
closure, and the arm's evidence slot is taken from `env` rather than from the performing site.

There are two evidence conventions, and exactly one translation point.

**A named call gives one slot per atom of the row.** Every label written out in a signature appends
one exactly-typed hidden evidence parameter to the function, **placed after the dictionary
parameters**, in ascending effect id order; every signature-introduced effect variable appends one
**erased** parameter; every associated-effect projection then appends **exactly one** erased
parameter, after the labels' evidence, ordered by (subject, trait, member name), which the impl
side's bridge restores to the concrete evidence record.

**A function value always has exactly one slot.** Whatever its row says, a function value's runtime
arity is "the parameters written, plus one evidence slot", and a pure function value carries an
empty pack there. A pack is an immutable chain of `(key, evidence, outer)` nodes **addressed by
atom key**: labels, effect variables and associated projections take their keys from separate
bands, so two rows meeting in one slot is a single cons and a query is a walk by key, with no
reordering and no chance of a shifted slot. The rule for building a pack at a call site: every
**ground** atom of the row (a written label, a projection already reduced to a label) conses one
node on top of the non-ground environment the frame already holds; when the row has no ground atom
and exactly one non-ground atom left, the pack **is** that slot, and nothing is allocated. A
superset is harmless: lookup is by key, so a node nobody asks for costs one step. Only a missing
key is an error.

The two conventions change hands in the wrapper `lift_fn_value` synthesises: each slot the named
side wants is read out of the function value's single pack by key. Higher-order library functions
(`list.map` and its ilk) take the "one non-ground atom left" path, forwarding as-is and building
nothing.

**The boundary clause: a value leaving the language carries a creation-point snapshot.** Both
conventions above put the supply point at the call, because the call is the only place a handler
frame is known to be live. Once a function value has been converted to a Java functional interface
(§9.4) there is no such place: the adapter is entered from a Java frame with no Dawn frame under
it, and neither the moment nor the thread of the call is chosen by the language. So here, and only
here, the value carries its own evidence: the conversion point builds **the pack that is in scope
at that point** by the same rule as any other supply point, stores it in a field of the adapter
object, and every entry Java makes hands it to the closure. The row is charged at the conversion
like an ordinary call site, and an atom the scope cannot answer is still an error, so the snapshot
is not a way of losing a label but a way of answering it at the last place an answer exists.
Nothing about the rules inside the language changes: evidence is supplied at call sites, a
snapshot is taken where a value crosses out, and the two meet only at that one step.

> **This is why union has no absorption (§6.6).** Both conventions above read their shape off the
> effect row: the named side reads whether slots exist and how many, the function-value side reads
> which keys the pack should hold. So any row equation that deletes a label, a variable or a
> projection makes the static row and the runtime carrier disagree: a signature opens one slot
> fewer, or a pack is built one key short, while the reading side still looks the key up and finds
> nothing. That is the "effect evidence missing" compiler-invariant panic, on a program that checks
> clean. §6.6's absorption ban is the static half of the same fact.
>
> **One alternative is refused here explicitly**: let the runtime fall back to a dynamic lookup by
> label whenever a slot is missing, so that absorption would cost performance and not correctness.
> Not adopted. It trades the invariant "an atom the row states has a place in the carrier" for a
> fallback path, and a fallback path runs only on the programs that happen to be short a slot, so
> the part nobody tests is exactly the part that is unsound; lookup would also become two semantics
> instead of one walk by key. The invariant stands.

### 6.6 Row equivalence and normal form

An effect row is built from four kinds of **atom**: the base axis's `io`, effect variables (§6.3),
associated-effect projections (§6.5), and the label axis's named effects. `pure` is the row with no
atoms, written **`!()`**; it goes anywhere `!io` goes (a signature's row, a function type's row, an
effect argument, an impl's associated-effect binding), and means what leaving the annotation off
means. `pure` is not a spelling for that row: it is not a keyword, so written into a row it becomes
an ordinary effect variable, and an effect variable is solved by any row at all. `!pure` is
therefore an error (§6.3).

Row equivalence is generated **by and only by** the five rules below.

1. **Union is componentwise**: the union of two rows is a boolean or on the io bit and plain set
   union on each of the three sets (effect variables, associated-effect projections, named labels).
   Hence `|` is commutative, associative and idempotent, and `pure` is the identity. Stacked
   annotations equal one union: `!Ask !io` is `!(io | Ask)`.
2. **The normal form is the smallest shape**: on the base axis, all components empty is `pure`, io
   alone is `!io`, no io and a single base atom left is that atom itself, and anything else is the
   union of those components; an empty label set carries no label layer, and a non-empty one is
   that base row plus those labels.
3. **The normal form has a settled order**: effect variables in introduction order (first
   appearance within the signature, with explicit binders taking the front in the order written),
   associated-effect projections by (subject type parameter, trait, member name), named labels by
   effect id. That order is also the evidence slots' layout order (§6.5 "Implementation").
   Rendering is a separate matter: printed atoms are sorted by name, so `!io !e` prints as
   `!(e|io)`.
4. **Projections reduce through the impl**: once the subject is settled, an associated-effect
   projection is replaced by the row that impl binds, and the result is normalised again by the
   rules above. A ground row contains no projection.
5. Two rows are **equivalent exactly when their normal forms are equal**.

**An equation not written here does not hold.** In particular: **union has no absorption law**.
`!(io | Ask)` and `!(e | io)` are normal forms that do not move, and any reading that equates them
with `!io` is not a consequence of these five rules; it is a sixth rule being added.

**Union does not distinguish effects that occupy an evidence slot from environment effects.** `io`
is an environment effect and occupies no slot of its own (§6.5 "Implementation"). That is **not** a
reason for it to absorb `!e`: `!e` can be instantiated to a named effect that does occupy a slot,
whether a slot exists is known only after instantiation, and union is computed before it. This is
the clause most easily argued away in reverse ("io takes no slot, so what does absorbing cost?"),
so it is written as a clause rather than a comment: what would be absorbed is an atom, not a slot.

**Containment is a separate relation and takes no part in equivalence.** `!io` covers `pure`, `io`
and effect variables (including unions of them); named labels and associated-effect projections are
judged by exact set containment, where `!io` covers neither `!Ask` nor `!C.E`. The division of
labour is sharp:

- **A signature** is judged by containment. A body purer than its signature is allowed (§6.2 rule
  3), and a signature may promise `!io` while standing over a variable it binds, with the evidence
  still arriving, because the slots come from the binder list and not from the row.
- **A function value** is not. It has no binder list, and its row is the whole of what a call site
  reads to build the pack, so on the way into a slot the slot's row must carry its row **atom for
  atom**. Widening upward stays free: a pure closure goes anywhere and the extra keys go unread.
  What is refused is a row with an atom the slot does not have.

**Row subtraction** is the one exception to "atom for atom". When a function value goes into a
parameter of the form `!(e | R)`, where `e` is the **only** effect variable the callee's signature
binds and `R` is the set of concrete atoms in that row (named labels, `io`, associated-effect
projections), then `e` is bound to `S \ R`, where `S` is the argument's row, and the argument is
accepted. A parameter written `!(e | io)` therefore takes a closure that both does io
and raises a named effect; before this rule the only spelling that took one was the bare `!e`.

The step carries a **co-occurrence precondition**: **every** row in the callee's signature that
mentions `e` must also write down every atom of `R`. Every solution of `!(e | R) ~ !S` agrees on
the rows that contain `R`, so which one was chosen can be observed only from a row that mentions
`e` without `R`. Where the signature has no such row, `e := S \ R` is the only observable answer
and choosing it costs no principality. Where it has one, any choice would be a choice made on the
caller's behalf that the caller never wrote, so the argument is still refused, and the diagnostic
names the occurrence that makes the choice observable.

Where one call passes **several** function-value arguments through the same `e`, each argument's
residual `S_i \ R` is **joined** (the least upper bound on this lattice) into `e`'s binding:
neither the first argument nor the last one wins. This is what a bare `!e` parameter has always
done, and two spellings of one parameter row do not answer differently.

The step carries a **companion condition**: `e` is looked for on each parameter's **unsubstituted**
declared row. Once an earlier argument has bound `e`, the substituted row has no variable left to
find.

The argument's row **need not** contain `R`. Where `S` is short of `R`, `S \ R` is `S` with atoms
taken off it that it never had, and `e` is bound to that and the argument accepted. This is safe
for the same reason widening upward is free: the call site builds the pack from the
**instantiated** row rather than from the argument's own row, and the pack is read by a key chain
rather than by index. A closure short of its slot is therefore handed a superset, and the extra
keys go unread.

The other shapes are unchanged. The **other** direction is still refused: an atom in the
argument's row that the slot does not have is the atom-for-atom clause above, which this section
does not touch. A row with two or more effect variables is still refused as well: the remainder
has no principal split between them, and this specification does not invent one.

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
   **An opaque type is as serialisable as its target** (§2.7), with one exception:
   `std/cursor`'s `Cursor` is not. Its `Int` is an offset into **the backend's own
   representation** of the string (UTF-16 code units on the JVM, UTF-8 bytes on native),
   and a constant is folded once and written into the Core both backends read, so a folded
   position holds for at most one of them. To compute a position at compile time, hold the
   string and walk to it where it is used. This exception is a corollary of §11's "the
   measure never becomes an observable value", not the whole of it: rendering is shut off
   too, or `const S: String = to_string(c)` would go around this clause and fold the
   measure into the artefact as a string (and the interpreter counts code points, so that
   would be a third answer again). The exception comes off once cursors have a single
   currency.
   `Map`/`Set` are not allowed for now: they are HAMTs over `Array`, and the comptime
   interpreter has no `Array` primitive; `List` works because the interpreter carries its
   own list representation, not because it can run `std/pvec`.
3. Evaluation has a step budget (10⁸ steps by default, tunable with `--comptime-fuel`);
   exceeding it is an error — which guarantees compilation always terminates.
4. There is no Java interop and no io inside comptime (constraint 1 guarantees this
   automatically).

### 7.3 Explicitly out of scope

comptime **cannot** generate types, cannot generate declarations, and cannot introspect
the AST. It is only "run a piece of pure Dawn code ahead of time". This specification provides
no metaprogramming facility.

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
  `Result`/`Option` (the `E` types must agree; there is no automatic error-type conversion).
- `?` is the **expression-level propagation shorthand** for `Option`/`Result`: it propagates the
  current expression's `None`/`Err` branch as the current function's return. `return`, `break`, and
  `continue` are separate explicit jumps, not part of this shorthand.

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
- **A member name is matched against the JVM declaration exactly; case does not decide
  what kind of member it is.** `Class.member` reads a public static field,
  `Class.member(args)` calls a public static method, and `value.member(args)` calls a
  public instance method — a field and a method of the same name (Java's two namespaces
  may collide) are told apart by **whether there is a `(...)` suffix**. So
  `Math.IEEEremainder(a, b)` is a method call, not a field read. A wrong case is not
  folded (`Math.ieeeremainder(a, b)` reports "no static method"), and staticness is part
  of the match as well: a static method cannot be called through an instance, nor an
  instance method through the class. Dawn's own qualified spellings win over the Java
  lookup: `m.C(args)` is a qualified constructor, and when `m` is a module alias the whole
  thing is resolved by §10.3 (a qualified constant with `(...)` still reports that it is
  not callable).
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
  visible; third-party classes may come from the project's `[java-deps]`
  (`dawn check/doc/run/test/build`), or from `--cp <jars>` (common to
  `dawn run/test/build`, §12.1). Commands that run a program use the same classpath for
  compilation and execution. LSP currently resolves only JDK classes; a third-party class
  is reported as not found in the editor but compiles on the command line.
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
position is currently unsupported; arrays go through as opaque values (§9.5). **Passing
null for an `Option` argument** is unsupported as well (Dawn currently cannot pass null to Java).

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
  Interfaces only; an **abstract class** with a single abstract method is not supported. The
  implementation generates an ordinary adapter class that holds the Dawn `FnN` and writes it
  into the classfile at build time; native-image needs no runtime dynamic-class configuration.
- **Matching**: the SAM method signature is mapped to a Dawn function type by §9.2 and
  then matched as usual; a lambda's parameter types can be seeded from the parameter (the
  same mechanism as generic argument inference). In overload scoring a function value
  only matches functional-interface parameters. Dawn does not track Java generic
  arguments, so the parameters of a **generic SAM** (`Predicate`/`Function` and the like)
  enter Dawn with their erased types (usually an opaque `Object`, which can only be
  passed along as is); only a SAM with concrete types (`Runnable`, `HttpHandler`) gives
  the full experience.
- **Every row but `ctl` crosses, and the evidence comes from the creation point**: a row
  carrying a named effect label, an effect variable or an associated-effect projection can
  be handed out. The conversion point snapshots the evidence pack that is in scope there
  into the adapter object, and Java's call hands it to the closure; this is §6.5's
  boundary clause. The reason is there too: Java enters a callback from somewhere with no
  Dawn frame under it, so there is no call site to supply evidence at, and the creation
  point is the last place any exists.
- **`ctl` is the one exception**: a function value whose row names a `ctl` effect (§6.5)
  **does not cross**, and the conversion point is a compile error, because `ctl` says
  exactly that an arm may suspend this value's caller, and there is no Dawn frame under a
  Java frame to suspend into. The ways out are to move the conversion elsewhere, or to drop
  the `ctl` from the declaration when no arm of it binds a continuation. Only **written**
  labels are judged this way: on the effect-variable and associated-effect-projection axes
  the conversion point cannot know what the caller will instantiate `!e` with, so those are
  caught at run time, where a suspension nothing can take is a panic rather than a wrong
  answer.
- **The row is charged at the conversion point**: a crossing row counts towards this
  function's row like any other call site. A label nothing in scope answers still reports
  "nobody is handling this"; when this function's own signature carries it out instead,
  what the snapshot reads is this frame's hidden evidence parameter. So the boundary
  clause changes where evidence comes from, not whether it has to exist.
- **The snapshot is the handler that was in scope when the value was written**: Java
  calling after the frame that installed the handler has returned still reads that one.
  Writing `with handle E { ... }` inside the function value is a different thing: it
  installs a fresh handler on every run, over the top of the snapshot.

  ```dawn
  with handle Log { log(m) => println(m) }
  Thread.new(() => log("tick"))            # the snapshot carries this handler

  Thread.new(() => {                       # installs one of its own on every run
    with handle Log { log(m) => println(m) }
    log("tick")
  })
  ```

- **When the call happens is still untracked**: the effect system does not care when the
  Java side calls; Java may call that function value on any thread at any moment
  (including after this call has returned). This does not break the purity contract: Java
  code can only run underneath a Dawn `!io` call, or on a Java thread with no Dawn stack,
  and no signature promise of a pure or `!io` function is violated. The snapshot brings a
  labelled row under the same sentence: whenever it is called, what answers it is the
  handler chosen at the conversion.
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
`decode_utf8_lossy(b) -> String` / `decode_latin1(b) -> String` (decoding, see §11),
`decode_utf8_checked(b) -> Result[String, Utf8Error]` (strict decoding, see §11),
`bytes.len`, `bytes.at(b, i) -> Int` (0..255, out of range panics),
`bytes.slice(b, start, end)` (`[start,end)`, subscripts clamped into range),
`bytes.index_of(b, needle, from) -> Option[Int]`. `index_of` clamps a negative `from`
to zero; a non-empty `needle` is searched from that byte offset for its first complete
match. An empty `needle` matches at every valid position in `[0, len(b)]` (so
`from == len(b)` returns `Some(len(b))`), but `from > len(b)` returns `None` even for an
empty `needle`. `Bytes ++ Bytes` concatenates,
`==`/`!=` compare by **content** (`Show` renders a `<N bytes>` summary). The hash of
`Bytes` is a **content** hash (seed `1`, byte by byte `h = 31*h + the signed byte`,
wrapping at 32 bits, see §3.5 — the same shape as the composite rule there), consistent
with `==` on content, so `Bytes` **can** be a Map/Set key. (It was once forbidden because
the JVM `hashCode` of `byte[]` is reference identity; after both ends were changed to
content the ban did not get withdrawn along with them, and was withdrawn on 2026-07-27.)
`Bytes` does not take part in comptime constant folding, and cannot be a bare first-class
function value either (wrap it in a lambda).

**An erased `Object` may be claimed only explicitly.** The return of an erased generic
(§9.2) lands as an opaque `Object`. Overload resolution uses that static type only through
ordinary Java assignability: it can be passed to an `Object` parameter, but it cannot match a
concrete reference parameter such as `Path`, `InputStream`, or `byte[]` in the other
direction. The compiler inserts no hidden `CHECKCAST` at the argument bridge; the same
conversion cannot fail as a value when written explicitly but escape through a host exception
when inserted implicitly.

If you know for certain that some opaque `Object` from an erased generic is at runtime a
particular concrete reference type (such as `byte[]` when `HttpResponse.body()` is paired
with `BodyHandlers.ofByteArray()`), use the generic builtin
`cast[T](x: Object) -> Result[T, ForeignError]` to **claim** it as that type (T is taken
from the expected type at the call site, e.g.
`let b: Result[Bytes, ForeignError] = cast(...)`) — the claim does one runtime
check, and **a type mismatch is an `Err`, not an exception passing through**; for the
payload see §9.8.1 (on the JVM the `kind` is `java.lang.ClassCastException`). T must be a
reference type (a primitive, or no expected type, is rejected at compile time). Java array or
parameterized targets that cannot currently be named in Dawn get no implicit exception either;
when a real use case needs one, the surface must first gain a writable target type.

> **A function with a pure signature should not be able to exit through a host
> exception** (LANG-02) — `cast` used to throw `ClassCastException`, which is exactly the
> exit a pure signature is supposed to exclude. Failure is now a value. The three stages
> the migration went through (including a transitional spelling that lived for exactly
> one release) are recorded in [`error-model-design.md`](audit/error-model-design.md) §6.10–§6.12, and it is
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
  leak the inner mutability; there is currently no deep wrapping.
- Elements arrive in the boxed representation of §9.2 (`Int` → `java.lang.Long`). Generic
  erasure means an API expecting `List<Integer>` will `ClassCastException` when it reads
  them; the current bridge does not repair that, so pick your APIs with care.
- The direction is Dawn → Java only; a collection returned by Java is still an opaque
  reference plus `Option` (§9.2), and can be chained on. A `Map`/`Set` bridge is not
  currently provided.

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
> ([`native-backend-plan.md`](native-backend-plan.md) §14.9) and has nothing to do with Java; the name outlived its
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

- Signature `catch_fault[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !e`. The
  protected closure's row is an **effect parameter** `!e`: the closure may be pure, may be
  `!io`, and may carry a label or an effect variable, as long as those effects have a
  handler answering them outside the barrier. The whole call's row **is** that row — the
  barrier adds nothing of its own to it. It and its companion `catch_panic` are no longer
  the same shape; the reason is at the end of §9.8.1 and in
  [`docs/audit/error-model-design.md`](audit/error-model-design.md) §7.5.
- It only intercepts `java.lang.Exception` and its subclasses; `Error` is not intercepted
  — **a Dawn panic (`dawn.rt.PanicError` is a subclass of `Error`) passes through
  unchanged**, a panic is still a bug and is not recoverable.
- The `Err` payload is a `ForeignError` — a prelude record whose fields and values are in
  §9.8.1. Up to v0.32.0 it was a single **rendered string** (`Throwable.toString()`), and
  this section also used to advise "match the string by prefix when you need to tell
  exception kinds apart"; that advice is withdrawn, and `kind` is its replacement.
- Failures inside the boundary propagate as usual: wrapping `catch_fault` around a whole
  compound call is enough, there is no need to wrap call by call.

The companion `catch_panic[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io` is the
same shape only in its parameter: the protected closure's row is just as free, while this
one's **own row is pinned to `!io`**, because the failure it catches is recorded in no row
anywhere (the end of §9.8.1 puts the two side by side). It intercepts **two kinds, a Dawn
panic (`PanicError`) and `Exception`** — not any `Throwable`: `VirtualMachineError` (heap
exhausted, stack overflow) passes through, resource exhaustion is not a value. It is for a
**supervision boundary** — one request on a server, one execution of a task runner: a
panic in one request should become a 500 and be logged, rather than take down the whole
connection or process. Its division of labour with `catch_fault` is clear: `catch_fault` handles
**expected foreign failure** and lets panics through; `catch_panic` is an **isolation
point**. Ordinary business failures still go through `Result` — do not use `catch_panic`
as routine error handling.

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

**The payload contract** (on every backend):

- `message` has **no length limit** and equals, byte for byte, the String the failure
  was raised with; a failure the language itself raises (`panic(m)`) is byte-identical
  across backends. Setting a limit means picking a number, and any number will one day
  be crossed by a legitimate message; truncation would also have to handle character
  boundaries — so this is "no truncation clause", not "a generous limit".
- `message` is well-formed UTF-8. A direct consequence of the String invariant (§4.8),
  written out separately because it has been violated: a payload cut at a byte count
  landed mid-character.
- A failure's payload belongs to **the barrier that is going to take it**: from the
  raise until that barrier builds the `ForeignError` (or `bracket` hands it to the next
  barrier out), no other barrier can read or write it. A nested catch therefore cannot
  affect a failure in flight (the unfolding of §9.8.2 guarantee 2).
- The panic/fault split is **observable** — by which barrier takes the failure, not by
  the `kind` string (whose values remain the backend's own).

There is only this one pair of barriers (only this pair **intercepts** failure; the
`bracket` of §9.8.2 intercepts nothing), only the `ForeignError` payload, and **the
String version is not kept**.

This pair's effect row is **no longer one row**: `catch_fault` carries the protected
closure's, `catch_panic` is pinned to `!io`. The criterion did not change — whoever
observes a failure is impure — what changed is reading it against **which** failure is
observed:

- **A fault is a failure caused by the outside world**, and every route out there is
  charged before it can raise one (an io primitive and a `use java` call are both
  unconditionally `!io`). So whoever can reach that `Err` is impure already, and a second
  charge from the barrier is one nobody owes.
- **A panic is a failure the language defines itself**, and no row anywhere records that
  one can happen, so the barrier is the only place left to record it. Its observables are
  exactly the ones a pure function may not have: an `assert` message is a function of the
  source text, a failure the runtime raises by itself says different things on the two
  backends (§9.8.1 promises byte-identity for `panic(m)` only), and folding or
  deduplicating pure calls changes how many times the catch happens.

So **the three barriers line up**: the `bracket` of §9.8.2 observes nothing,
`catch_fault` observes a failure `io` has already been charged for, and `catch_panic`
observes one nobody was charged for. The first two carry a variable, the third `!io`.

> **The line rests on an invariant**: **a fault only comes from io.** It used to carry one
> named exception: a continuation's row was once unconditionally pure, so a function with a
> **pure signature** that resumed or discarded one brought the remainder's io, and its
> faults, back into its own frame (both backends were measured doing this). Since
> 2026-09-02 a continuation carries its remainder's io bit (§6.5 "Control arms"): a
> remainder that can fault hands out an `!io` continuation, no pure frame can call it, and
> the exception is gone. `k` is still an ordinary function value with no type of its own;
> what changed is the io bit of its row and nothing else
> ([`docs/oneshot-design.md`](oneshot-design.md) §11.2, postscript). The one shape left is a
> remainder whose only effects are labels, where a label's arm does io at **its own
> installation point**: that is the standing supply-point doctrine (the boundary clause
> under §6.5 "Implementation", the same one the SAM snapshot rests on), the arm's io is
> charged to the frame that installed it, and it is not an exception to this clause.

The full argument, and the condition under which it reopens, is in
[`docs/audit/error-model-design.md`](audit/error-model-design.md) §7.

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
fn bracket[A, B, !e](resource: A, release: fn(A) -> Unit !e, body: fn(A) -> B !e) -> B !e
```

The third parameter is named `body`: `use` is a keyword, so the call
`bracket(r, close, use: f)` cannot be written at all, and that spelling never had a
caller -- it only ever appeared in the rendered signature.

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

**It comes last** to leave the road open for `with` (§4.10, landed 2026-07-31): that
sugar attaches "the rest of the block" as the **last** argument, so a primitive holding
it in the middle would have to be respelled. Once the resource is acquired up front,
such a site does not need a single lambda:

```dawn
with f <- bracket(open(path), close)
...the rest of the block is the body...
```

Three guarantees:

- **`release` runs exactly once on every path** — `body` returning normally, panicking,
  faulting; all three run it, and run it only once.
- **The original failure keeps propagating unchanged**: `kind`/`message` verbatim, **a
  panic is still a panic and a fault is still a fault**. So `catch_fault` still does not
  intercept a panic that passes through bracket (on native that kind bit is restored by
  re-raising, not re-inferred; the measured comparison of the two backends is in
  `scripts/spike-native/bracket.dawn` and `bracket_fatal.dawn`). A failure `release`
  catches for itself **does not affect** the one in flight — raising and swallowing a
  new failure inside a release is legal code, and the crossing failure comes out as it
  went in (`scripts/spike-native/bracket_release_fails.dawn`). A failure that
  **escapes** the release itself (raised and not caught) replaces the original, with no
  suppressed chain: that is what both backends do today, written here so it is a ruling
  rather than a coincidence.

  > **This replacement rule has exactly one exception: the unwind that discards a
  > continuation** (§6.5's `discard`). What is passing through on that path is not a
  > failure but a poison, and a poison is by definition uncatchable; letting a `release`'s
  > failure replace it would turn it into an ordinary failure, so a `catch_panic` inside the
  > frozen span would take it and the abandoned computation would be resurrected out of its
  > own cleanup and run to the end. So a different rule applies there, Lua's `__close` rule:
  > **the walk is not stopped** and the remaining `release`s still run; **the first failure
  > is the one delivered**, handed to whoever called `discard` once the unwind is finished.
  > The corpus is `release_failure` in `scripts/spike-native/ctl_discard.dawn`.
- **`bracket` intercepts nothing**, so it returns `B` and not `Result` — guarding and
  intercepting are two orthogonal things (neither Haskell's `bracket`, Kotlin's `use`,
  Koka's `finally` nor Go's `defer` returns a Result). To take the failure as a value,
  write `catch_fault(() => bracket(...))`; each of the two primitives does one thing.
- **The effect row is a variable `!e`**: `release`, `use` and the call as a whole share
  one row, and `bracket` adds no effect of its own. So a `bracket` over a pure resource is
  pure, an `!io` one is `!io`, and a labelled one passes its label straight through. The
  pair of barriers in §9.8 binds an effect parameter too (`catch_fault[T, !e]`), so a free
  row on the closure being run is common to all three. The real difference left belongs to
  `catch_panic` alone: its own row is pinned to `!io`, while `bracket`'s and
  `catch_fault`'s own rows **are** the variable. The reason is at the end of §9.8.1 and in
  [`docs/audit/error-model-design.md`](audit/error-model-design.md) §7.3, §7.4, §7.5.

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

- **Directory mode** `dawn check|doc|run|test|build <dir>`: root = `<dir>/src`, entry =
  `<dir>/src/main.dawn` (if it is missing, the compiler reports it and prints the expected
  path).
- **File mode** `dawn check|doc|run|test|build <file.dawn>`: starting from the file's directory,
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

`dawn check|doc|run|test|build` fetches `[java-deps]` (including those declared by each
dependency package — the union) for compile-time `use java` resolution. Each target of
`check`/`doc` gets an independent classpath; `run`/`test`/`build` instead merge it with
`--cp` and use the result for both compilation and execution. `dawn build` additionally
copies `[java-deps]` into a `lib/` next to the jar. The repository address comes from
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

All declarations are module-private by default; `pub` exports `fn`/`type`/`alias`/`const`/`trait`/`effect`
(`pub type` brings the constructors and fields with it, see §3.3). Accessing or importing a
non-`pub` item → error (`` `parse` is private to module json/parser ``, with a hint: add
`pub`). An exported declaration must not leak a private type, trait or effect that cannot be named
outside the module either; the full rules for transparent aliases, the opaque boundary, public
traits/effects and reachable impls are in §3.3, and the error is reported at the declaration rather
than at the use site.

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
function name is the domain**: `bytes.decode_utf8_lossy` and `bytes.decode_latin1`; there is no
charset registry. With no charset parameter there is no "unknown charset" failure mode, so
they return a bare `String` rather than an `Option` (the history is in
[`stdlib-impl-notes.md`](stdlib-impl-notes.md)).

UTF-8 decoding comes in a **lossy and a strict** form, told apart by the function name in
the same way. `decode_utf8_lossy` replaces every illegal sequence with U+FFFD (the
replacement rule of the paragraph above); `decode_utf8_checked` rewrites nothing and
answers `Err(Utf8Error { offset })` at the first illegal sequence, where `offset` is the
byte index that sequence begins at, which is also how many leading bytes of the input were
valid UTF-8. The two share one notion of what is illegal: the inputs `decode_utf8_checked`
accepts are **exactly** the inputs `decode_utf8_lossy` returns unchanged, and that is
normative. `decode_latin1` has no strict form, because every byte is a code point and it
cannot fail. `decode_utf8` is the old name of `decode_utf8_lossy`, kept under the
one-generation forwarder discipline of CONTRIBUTING §7 and removed in the next version.

hex and base64 are pure Dawn byte arithmetic (no `use java`, so both backends share one
definition), and the rules are normative: `to_hex` writes two digits per byte and **lower
case** is the canonical spelling, `from_hex` accepts either case and nothing else;
`to_base64` uses the standard alphabet of RFC 4648 section 4 and pads with `=`, `to_base64_url`
uses the url/filename-safe alphabet of section 5 and **does not pad with `=`**; the two decoders
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

**The measure is the backend's, and never becomes an observable value.** A position is an
offset into **the string's representation**, and the execution models do not agree on that
representation: UTF-16 code units on the JVM, UTF-8 bytes on native, and code points in the
comptime interpreter, which has no representation to offset into. So the number does not
leave `std/cursor`: it cannot be read (`opaque`), it cannot be folded into a constant
(§7.2), and it does not render. `Show[Cursor]` renders `<cursor>` rather than the number,
because otherwise a program's output would depend on who compiled it. To report a position,
report `cursor.offset(s, c)`: the count **in characters**, which every backend agrees on.
Which measure is used is therefore an internal decision, changeable at any time, and not a
breaking change.

**Using a cursor on another string is undefined.** A cursor belongs to the string it came
from. An out-of-range position is clamped by `char`/`next`/`prev` and refused by `slice`,
but an in-range one from another string is indistinguishable from a position of this one,
so this specification promises no answer and the backends do in fact differ. Binding a
cursor to its string needs a tag that is itself backend-independent (otherwise the check
diverges exactly where the cursor did), which costs a walk to compute and a second word per
position. That was weighed and declined on 2026-08-16 in favour of writing the boundary
down; every other channel is held shut by `scripts/spike-native/cursor_currency.dawn`,
which compares this module's public answers across both backends.

**Container representations.** `Map`/`Set` are represented by the pure-Dawn `std/hamt` (a
persistent HAMT) and `List` by `std/pvec` (a persistent vector); these are **internal
modules**: `use std/hamt` / `use std/pvec` outside std is a compile error, and the
diagnostic points back at `std/map`/`std/set`/`std/list` (§10.6). The representation has to
be replaceable, and being replaceable requires that nobody depends on it — which is why the
[standard library reference](https://dawn-lang.dawnop.com/stdlib.html) does not list these
two modules either. The semantics of the containers (persistent interface, keys must be
`Eq + Hash`, iteration in insertion order, equality independent of order) are in §2.2.

**Where IO stands.** `std/io`'s console, environment and subprocess functions are `!io`; the
file functions ride the named effect `Fs` (§6.5), whose production handler is `io.with_fs_real`
and which a test answers from a table. Anything that can fail returns
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
  `"io.not_a_directory"` — that one, `io.run`'s `"io.no_program"`, and `io.delete`'s
  `"io.invalid_delete_path"` are the three kinds std mints itself; all the others come from
  the backend
- `io.delete(path)` returns `Result[DeleteOutcome, ForeignError]`: deleting a file or empty
  directory is `Ok(Deleted)`, an absent path is `Ok(NotFound)`, and every other host refusal
  (including a non-empty directory) is an `Err`. It never deletes recursively. The std layer
  rejects the empty string and paths ending in `/` with kind `"io.invalid_delete_path"`
  instead of letting a backend normalize them. A path containing U+0000 is also an `Err` and
  must never name the prefix before the NUL
- `io.exists(path)`, `io.is_dir(path)`, and `io.is_symlink(path)` are Bool queries: an absent
  path, a type mismatch, or an invalid host path returns `false`. In particular, a path
  containing U+0000 must neither fault nor query the prefix before the NUL; all three return
  `false` directly
- `io.getenv(name)` returns `None` when the variable is unset or when the name cannot be
  represented by the host environment API. In particular, a name containing U+0000 must
  neither fault nor query the prefix before the NUL; it returns `None` directly
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
    **replace**: an illegal sequence becomes U+FFFD, following `bytes.decode_utf8_lossy` to the
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
| `dawn run [compiler-options] <file.dawn or dir> [-- <program-args>...]` | Compiles into memory / a temporary directory, starts a JVM and runs it |
| `dawn build <file or dir> -o app.jar` | An executable jar (`Main-Class: main` is already set) |
| `dawn build ... --native -o app` | The previous step + GraalVM `native-image`, a standalone binary (§12.3) |
| `dawn test <file or dir>` | Compiles the variant that includes the test blocks and runs it (directory mode aggregates the tests of every module) |
| `dawn fmt <file or dir>...` | Formatting (directory mode recurses over every `.dawn`; a directly named file must end in `.dawn`, or it exits 2) |
| `dawn __emitc <file or dir> -o out.c` | A C translation unit. A hidden subcommand: this is the C backend's entry point on the JVM toolchain, and `dawnc`'s selfhost and differential comparison both go through it |

**The C backend driver `dawnc`** (a single-file static executable, shipped with each
release; it needs neither a JVM nor this repository):

| Command | Output |
|------|------|
| `dawnc check <target>...` | Type checking only, aggregates diagnostics from every target |
| `dawnc emitc <target> [-o out.c]` | A C translation unit (compiled together with the runtime in `runtime/c/`) |
| `dawnc build <target> [-o out]` | The previous step + a call to `cc` (`$CC` overrides it), a standalone executable |
| `dawnc run [--std <dir>] <target> [-- <program-args>...]` | The same, and runs it as soon as it is compiled |
| `dawnc test <target>` | Compiles the variant that includes the test blocks and runs it |
| `dawnc fmt` / `doc` / `add` / `lsp` | Output is **byte-for-byte identical** to `dawn`'s subcommands of the same name (`scripts/native-cli-diff.sh` pins these four to the JVM's bytes) |
| `dawnc version` | The version number (it reports `(native)` itself, so it is not literally identical to `dawn --version`) |

The two `lsp` subcommands share one stdio-framing implementation. A header, from its
first byte through `CRLF CRLF`, is at most 8192 bytes: a terminator completed exactly on
byte 8192 is valid, while an incomplete header that reaches the limit is rejected
immediately. A body is at most 67108864 bytes. Every nonempty header line must have the
shape `1*tchar ":" field-value`; `tchar` is an
ASCII letter or digit, any of `! # $ % & ' * + - . ^ _ | ~`, or a backtick. A missing
colon, an empty field name, or a space/parenthesis in the field name is therefore a framing
failure, while a syntactically valid unknown header is ignored. The field name
`Content-Length` is compared ASCII-case-insensitively. Its value is one or more ASCII
decimal digits, optionally padded
at either end by SP/HTAB only. Empty values, signs, fractions, exponents, underscores,
Unicode digits, `Int` overflow and values above the body limit are invalid; `0` is valid.
Duplicate fields are valid only when every independently parsed numeric value is equal, so
leading zeroes do not conflict; an invalid occurrence or a numeric conflict rejects the
frame.

The body must be strict UTF-8. If a complete bounded frame has invalid UTF-8 or an invalid
JSON body, the server replies with `-32700`, `id: null`, and continues with the next frame;
a replacement decoder must not repair invalid wire bytes into valid JSON. Every other
framing failure (a malformed or partial header, a partial body, a missing, invalid,
conflicting or oversized length, or an oversized header) produces exactly one copy of the
parse error below and closes the read loop; bytes after the failure are never interpreted
as another frame. Clean EOF with zero header bytes is silent. Header syntax and all length
validation are checked before the underlying stdin-read primitive is called.

```json
{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"Parse error"}}
```

The two drivers parse argv independently, but target cardinality is one shared contract
(TOOL-04):

| Subcommand | Target / selector cardinality |
|---|---|
| `check` | 1..N targets |
| `test` | Exactly one target, or `--stdlib`; the two are exclusive |
| `doc` | Exactly one of one target, `--stdlib`, or `--builtins` |
| `build` | Exactly one target |
| `emitc` | Exactly one target (the JVM entry point is the hidden command `__emitc`) |
| `fmt` | 1..N targets |

A missing target, too many targets, or conflicting selectors is a usage error: it exits 2
before loading a target or producing a backend output, and both drivers use identical
diagnostic bytes for the same error. N has no artificial upper bound for `check` or `fmt`;
testing with two targets demonstrates that they really are batch commands, not that their
maximum is two.

`run` uses two explicit argv namespaces (TOOL-03):

```text
dawn run [compiler-options] <target> [-- <program-args>...]
```

Compiler options are parsed only before the target. The separator may be omitted when the
program has no arguments; both `run target` and `run target --` pass an empty argv. If any
token follows the target, the first one must be `--`; otherwise stdout is empty, stderr is
exactly the following line, and the command exits 2:

```text
error: usage: dawn run [compiler-options] <target> [-- <program-args>...]
```

The separator itself is not forwarded. Every token after it reaches the program's `args()`
verbatim and without further interpretation, including an empty string, `--`,
`--comptime-ffi`, and `-o`. The JVM and native drivers keep independent parsers and are held
to one absolute stdout/stderr/exit contract; see `run-argv-boundary-design.md` for the full
rationale.

The few subcommands `dawnc` lacks are not holes, they are the backend's boundary: **it
refuses `use java`** (Java interop is a JVM backend capability, §9), and `build`-to-jar,
`lock` and `cache` likewise only mean something on the JVM side. Both drivers accept
`--std <dir>` to swap the standard library source.

**The argument may be a single file or a project directory** (§10.1): directory mode
loads every module under `src/`, with `src/main.dawn` as the entry point; single-file
mode walks upwards for a `src` ancestor and takes it as the root. The jar collects every
module class, and `Main-Class` = the entry module's class `main`.

**Third-party jars: `--cp <jars>`** (before run's target, and for test/build; separated by the path
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
| lambda/closure | Each closure is an ordinary generated class implementing `FnN`, with captures in final fields; SAM conversion generates a separate adapter class holding that `FnN` |
| generics | erasure + boxing |
| structurally equal types | ADTs/records/tuples still get matching `equals` and `hashCode`, but those are **for Java callers** — Dawn's `==`/`hash` are Core functions that lowering expands structurally (§4.3), and `Map`/`Set` reach them through dictionaries. When an `impl Eq`/`impl Hash` exists, these two methods forward to that impl |
| `Int`/`Float`/`Bool` | native `long`/`double`/`boolean`, boxed only in generic positions |
| `Unit` | `Ldawn/rt/Unit;` — a singleton reference; it takes one slot and is no different from any other reference in parameter/field/capture positions |
| `Never` | Static Dawn calls use return descriptor `V`. Calls through erased `FnN.apply` return `Object`; the caller discards it with `POP` before terminating. When a SAM adapter calls its bridge, it follows the SAM return descriptor: `void` produces no stack value, a one-slot result is discarded with `POP`, and a two-slot result with `POP2`; the adapter then emits `aconst_null; athrow`. `Never` has no parameter, field, or other storage representation |
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
recursive tail calls are not guaranteed. The rule: a call to the function itself
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
pub opaque type UserId = Int     # opaque outside this module (§2.7)
const ORIGIN: Point = Point { x: 0.0, y: 0.0 }

pub trait Named[T] { fn name(x: T) -> String }
impl Named[Point] { fn name(p: Point) -> String = "point" }
pub effect Ask { fn ask() -> Int }

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
[a, ..xs, if c { b }]            # list elements: spread / conditional; newlines separate too (§4.11)
read_file(path)?                 # Result propagation
if n < 0 { return "negative" }   # early return (§4.9)
xs.each { x => println("$x") }  # tail block: the last argument (§4.3)
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
