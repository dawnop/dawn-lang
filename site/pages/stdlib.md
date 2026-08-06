<!-- The original. Rendered as the intro to /stdlib.html; the translation is
     stdlib.zh.md, which registers a digest of this file. Change this one
     first -- scripts/doc-check.py goes red when the two part company. -->

# Standard library

This page is the complete API reference for the Dawn standard library,
generated straight from the compiler by `dawn doc --stdlib`: every signature
and every paragraph below is the one the compiler holds right now.

The names come from two places — the compiler's builtin table, and the `std/`
modules bundled with it (Dawn source). **Which of the two implements a name is
not something a caller can observe**: it changes neither the spelling nor the
type nor the semantics. So this page is not grouped by builtin/std, but by how
the name is written.

How to read it:

- Names in the **prelude** are in scope implicitly. No `use` — just write
  `println("hi")`, `sort(xs)`.
- The rest come in with `use std/x` and are then called qualified: after
  `use std/str`, write `str.trim(s)`. A single name can be imported on its own
  (`use std/str.{trim}`).
- A function appearing once under "prelude" and once under its module is
  normal: `sort(xs)` and `list.sort(xs)` are two ways of writing the same
  function.
- In a signature, `[T: Ord]` is a type parameter and its bound
  ([spec §3.5](spec.html#s3-5)), `!io` is an effect ([spec §6](spec.html#s6)),
  and `!e` is an effect variable — the function's effects are whatever the
  closure handed to it has.
- What can fail returns `Result`; what may have no answer returns `Option`.
  When to assert, when to ask and when to clamp is decided in
  [spec §4.8](spec.html#s4-8).

The specification those links lead to is **written in Chinese**. This page,
the tutorial and the examples come in both languages.

## Built-in types

These types are part of the language itself. They need no `use` and have no
std source to read; their semantics are defined in the specification, and what
follows is a one-line index.

| Type | In one line |
| --- | --- |
| `Int` | 64-bit signed integer |
| `Float` | double precision; rendering and parsing are pinned by `std/fmt` and do not follow the host ([§4.3](spec.html#s4-3)) |
| `Bool` | `true` / `false` |
| `String` | immutable string, measured in **code points**; there is no ill-formed UTF-8 inside one |
| `Unit` | the single value `()`, first class, allowed wherever a value is |
| `List[T]` | immutable persistent list (32-way trie + tail block); accumulating with `acc ++ [x]` is linear |
| `Option[T]` | `Some(T)` or `None`; the language has no null |
| `Result[T, E]` | `Ok(T)` or `Err(E)`; `?` has syntax for it ([§8.1](spec.html#s8-1)) |
| `ForeignError` | the structured payload of a foreign failure: a `kind` and one human-readable line ([§9.8.1](spec.html#s9-8-1)) |
| `Map[K, V]` | immutable persistent map, iterated in insertion order; keys need `Eq + Hash` ([§2.2](spec.html#s2-2)) |
| `Set[T]` | immutable persistent set, likewise |
| `Bytes` | immutable byte string, equal by content; binary data goes through it instead of borrowing a string ([§9.5.1](spec.html#s9-5-1)) |
| `Buf` | a write cursor onto `Bytes`: `bytes.buf()` opens one, `bytes.freeze()` closes it |
| `Cursor` | a position in a `String`, not an index; declared opaque by `std/cursor` |
| `(A, B, ...)` | tuple |
| `fn(A, B) -> C !e` | function type; `!e` may be left off, which means pure |

The persistent HAMT under `Map` / `Set` and the persistent vector under `List`
are pure Dawn source (`std/hamt`, `std/pvec`). They are **internal modules** —
the representation has to be replaceable, and replaceable means no program
depends on it, so `use`-ing them outside std is a compile error and this page
does not list them.
