<!-- doc-check: translation-of docs/design.md @ d5829b55b9a838ec -->

# Dawn Design Notes

*[中文](design.md) — the Chinese text is the original; this is its translation, and `scripts/doc-check.py` watches the two for drift.*

> Status: **historical**. This is the record of the decisions taken during M0–M4, kept
> item by item so that "why was it chosen this way at the time" has evidence behind it.
> **Several of its premises have since been overturned by later milestones**, the three
> that matter most:
>
> - "compiler budget 6–8 thousand lines (Kotlin)" and "implementation language = Kotlin" —
>   the Kotlin implementation has been archived at the `kotlin-final` tag, and main holds
>   only the self-hosted `selfhost/` (some 35,000 lines of Dawn); see
>   [m8-selfhost-only.md](history/m8-selfhost-only.md).
> - "the unsafe escape hatch is not open to user code" — `unsafe_pure` is ordinary syntax
>   now and users can write it; see spec.en.md §6.4 and LANG-01 in codebase-audit.md.
> - "no IR" — the argument held while the compiler was small; checker + emit are past ten
>   thousand lines now, see ARCH-04 in codebase-audit.md.
>
> The authoritative definition of the syntax and semantics is [spec.en.md](spec.en.md)
> (that one is normative). This document is only about the "why".

## 1. Goals

- A language implementation **one person can finish and maintain**: a compiler budget of
  6–8 thousand lines (Kotlin), within a year of spare time reaching the point of
  self-hosting everyday small tools.
- **JVM + native, both targets**, without paying for two backends: the only backend is
  JVM bytecode, and native comes out of GraalVM native-image, AOT from that bytecode.
- **The signature tells you the side effects**: purity is part of the type system, not a
  convention.
- Diagnostics benchmarked against Gleam / Rust: errors point at the source, speak plainly,
  and suggest a fix.

## 2. Non-goals (explicitly out of scope for v0.1)

| Not doing | Reason |
|------|------|
| ~~full algebraic effects (handlers)~~ → **the non-tail-resumptive tier** (multiple resumption / continuation capture) | ~~an engineering black hole~~ → the tail-resumptive tier has landed (`effect` + `with handle`, spec §6.5); what is left of it needs continuation capture, which collides head-on with the C backend's Perceus + single-stack model |
| ~~trait / typeclass~~ | ~~pass functions explicitly for now, add it when it hurts~~ → it hurt; added 2026-07-13 (see D9) |
| async / coroutines | `!io` + JVM virtual threads carry it; no colouring problem introduced into the language |
| macros | comptime covers the main cases, and it does not introduce a second language |
| custom operators | keeps the ecosystem from growing into early Scala |
| Java → Dawn direction of interop | a stable ABI in both directions is a big language's job |
| REPL | conflicts with comptime and the whole-program compilation model; poor value for effort |
| custom GC / memory model | the JVM's GC is our GC |

## 3. Decision record

### D1 The only backend = JVM bytecode (straight out of ASM)

native-image eats bytecode, so `dawn build --native` is just a `native-image` command
tacked onto the end of the jar. The price is accepting the closed-world assumption, so the
language design steers clear of its minefields on purpose:

- No custom `invokedynamic` bootstrap is generated (method dispatch is all
  `invokevirtual`/`invokestatic`); closures use `LambdaMetafactory` (which is on
  native-image's supported list).
- The language offers no `eval`, no loading code at runtime, no reflection. Those features
  were not in the goals anyway, so native compilation **needs no configuration file at
  all**, by construction.

### D2 The effect system has only two levels: pure and io

A full Flix-style polymorphic effect system is beautiful, but it doubles type inference,
error messages and the cost of teaching all at once. Dawn's lattice has just two points,
{pure, io}, plus effect variables for the most minimal effect polymorphism (the effect of
`map(f)` = the effect of `f`). In the implementation this is one more boolean lattice
threaded through the type checker; the payoff is the big half: pure functions can be
called from comptime, can be optimised aggressively, and need no mocks in tests.

Upgrade path: should finer effects such as `!net` / `!fs` be wanted later, the lattice
grows from two points to a powerset — the syntactic slot (the `!` suffix) is already
reserved.

### D3 comptime rather than macros; comptime does not manipulate types

A compiler must do constant folding → it therefore contains an AST interpreter → exposing
that to the user is comptime. Only pure code is allowed, and the result must be a
constant-serialisable value. Deliberately not doing Zig's "types are first-class comptime
values" — that stirs the type checker and the evaluator into one pot, and is the kind of
complexity a small implementation cannot ride. Generics go through separate, boring
parametric polymorphism (erasure + boxing), uncoupled from comptime.

### D4 Error handling = Result + `?`, with panic as the backstop

Exceptions break "the signature is the contract" (a function that can blow up without
being marked `!io` is a lie about purity). Recoverable errors go through `Result[T, E]` +
`?` propagation; unrecoverable ones go through `panic()` (the process terminates, mapped
to throwing an `Error` on the JVM and to abort on native). `panic` needs no `!io` — it
does not return.

### D5 Java interop: one-way, all `!io`, null wrapped into Option automatically

- **One-way** (Dawn calls Java): avoids promising an ABI.
- **All `!io`**: Java's purity cannot be audited method by method, so be conservative. The
  price is that obviously pure things like `Math.sin` are marked io too — solved by
  wrapping a whitelist in the standard library (which internally uses the `@trusted_pure`
  escape hatch, not open to user code).
- **null does not enter the language**: a Java reference-typed return value is
  automatically an `Option[T]`. Better one more `.expect()` at the call site than null
  polluting the type system.

### D6 No intermediate IR

AST → type/effect checking (annotated on the AST) → bytecode straight out of ASM.
Optimisation is left to the JVM JIT and to native-image. An IR gets introduced when an
optimisation pass or a second backend is really needed — prepaying architectural cost for
an imagined requirement is the most common way small projects die. The one exception is
tail-recursion rewriting (an AST-level transformation).

### D7 Implementation language = Kotlin

Thirty percent less boilerplate than Java (data classes, sealed classes and an embryonic
pattern match are exactly what writing a compiler wants), the artifact is a jar all the
same, and native-image can bootstrap the compiler itself all the same.

### D8 The interop trio: SAM conversion, array pass-through, zero-copy List bridge (settled 2026-07-12)

A prerequisite for M6, accepted against the playground runner first. All four semantic
decisions were checked against precedent in Kotlin/Scala/Clojure:

- **SAM = indy + LambdaMetafactory** (the same road as Kotlin 1.5+/Scala 2.12+; a spike
  proved native-image needs no configuration). Everything goes through a `dawn$sam$N`
  static bridge + LMF capturing the function value; no capture-free specialisation for
  direct references.
- **Reference parameters of a callback are not wrapped in Option; a null check at the
  bridge panics** — the same as Kotlin (`Intrinsics.checkNotNullParameter`, fail-fast).
  The ergonomics of `handle(ex: Option[HttpExchange])` are unacceptable; null in return
  position is normal (so it enters the type), null in a callback parameter is pathological
  (so, fail-fast).
- **No restriction on effects**: `!io` is erased in codegen and the calling convention does
  not change — Kotlin forbids converting a suspend lambda to a SAM because suspend changes
  the calling convention (an extra Continuation parameter); Dawn has no such obstacle. The
  soundness argument: Java code only ever runs underneath a Dawn `!io` call or on a thread
  with no Dawn frames on it, so the pure-function contract cannot be violated.
- **The List bridge is zero-copy + an unmodifiable view** (`Collections.unmodifiableList`) —
  the same as Scala's `asJava` / Clojure's persistent collections; and Dawn's `TList`
  runtime representation already *is* a `java.util.List`, so the bridge costs about one
  INVOKESTATIC. The original "copy through List.copyOf" plan was overturned by the survey
  of precedent. Nested-container elements are rejected (zero-copy would leak the inner
  mutability).
- **Narrowing overflow panics** (the same as Clojure's `RT.intCast`); a panic crossing the
  boundary propagates freely as a RuntimeException (all three precedents agree).
- **Explicitly not doing**: reading static fields (`valueOf`/`forName` are enough of a
  detour), Map/Set bridges, Java→Dawn collection conversion — left until M6 makes one of
  them really hurt.

### D9 trait = single-parameter nominal typeclass + dictionary passing (settled 2026-07-13)

The full design and implementation record is in [trait.md](trait.md); spec §3.5 is the
normative summary. The main points:

- **Rust's coherence model** (exactly one impl per trait × type across the whole program,
  plus the orphan rule), **Haskell's dictionary-passing implementation** — a natural fit
  for an erasing, boxing backend, and every call site at a concrete type is devirtualised
  (`invokestatic`); only constraint forwarding goes through an interface call. No
  monomorphisation (native-image code bloat + compile time do not pay off; it can be
  revisited as an optimisation in v2).
- **Single parameter, no conditional impls, no supertraits, no dyn**: v1 solves only
  "generic constraints + custom ordering". Multiple parameters and associated types each
  double inference and error messages; that cost is not being paid yet.
- **Operators bridge only the comparison family** (`< <= > >=` → the built-in `Ord.cmp`):
  `==` stays structural equality and is not opened up — custom equality would drag in Map/Set
  key semantics and pattern matching with it, high risk for small reward.
- **impls are global, not carried by `use`** — coherence guarantees uniqueness, so whether
  something is imported affects only name visibility, never instance selection; this avoids
  the Scala-implicit class of trap where "the import decides the behaviour".
- **An unexpected gift**: the module DAG + the orphan rule make a duplicate impl across
  modules structurally impossible (the two legal owning modules would have to reference each
  other in a cycle), so coherence only has to catch duplicates within one module.
- `derive Ord` (field lexicographic order) shipped in the same cut as
  `sort`/`sort_by`/`max`/`min`/`max_by`/`min_by`, closing the loop from "the pain" to "the
  cure".

### D10 The pre-selfhost clearing batch (P0.6, settled 2026-07-22) — patching the semantic dark corners, plus three "leave it as it is"

After selfhosting, every semantic change has to be served to two compilers at once, so
while there was still only one parser the debts turned up by a design review (against
orthogonality / explicit-over-implicit / the standard list of language-design mistakes)
were all settled at once. **Fixed** (each with its section in the spec and its commit):
numeric edge semantics nailed down as guarantees (§4.3), `Float`/`Bytes` forbidden as
Map/Set keys (§2.2), `alias` given its own keyword (§2.6), a field call colliding with a
same-named function turned into an error (§2.4), `break`/`continue` (§4.7), a leading `.`
continuing a line (§1.7), `Cursor` as an opaque type (§11). The three items **left as they
were** after the review, with the reasoning recorded so it does not get relitigated:

- **`->` for match arms, `=>` for lambdas**: unifying them Rust-style (`=>` for match too)
  buys nothing but taste, and costs mechanical churn on every match arm in both
  repositories plus a full regeneration of the goldens. `->` reads as "maps to", `=>` reads
  as "produces a closure body"; each is internally consistent. Not migrating.
- **Three spellings of negation** (logical `not` / bitwise `~` / unwrapping postfix `!`):
  the three have different semantics in different positions (keyword prefix / operator
  prefix / suffix), and merging any two of them manufactures a real ambiguity (`!` already
  serves double duty as the `!io` effect marker and as the prefix of `!=`). Kept; `x! != v`
  splits `!=` by longest match, as noted in spec §8.2.
- **Three uses of `..`** (range in a `for` head, rest pattern `..rest`, record spread
  `..base`): the three contexts are mutually exclusive, none can occur where another can,
  and the parser tells them apart with no lookahead; merging or respelling buys nothing.
  Kept.

Also: the review suspected "top-level declarations silently shadow the prelude" — the
reality at P0.6 was that redefining a builtin/std name at the top level was an error.
**P0.7 has, per [`stdlib-naming.md`](stdlib-naming.md), made a top-level fn / trait method
shadowing a builtin/std function name legal, Rust-style** (the resolution order was already
this module's declarations → std → builtins; only the registration-time error was deleted;
std's own `pub fn len` was the first beneficiary). Builtin/prelude **type and trait** names
(`Map`/`Option`/`Ord`…) still cannot be redefined; spec §10.3 is the authoritative wording.

## 4. Acknowledgements for where the features came from

- A restrained feature set and the bar for error messages: Gleam
- Purity/effect marking: Flix (simplified to two levels)
- comptime: Zig (with type-level programming taken out)
- `?` propagation, expression orientation: Rust
- The pipeline `|>` passing the first argument: Gleam / Elixir

## 5. Milestones

- **M0 end to end** (done): `Int`/`String`, functions, `match`, `!io` checking; `dawn run`
  and `dawn build --native` produce the same result.
- **M1 looks like a language** (done, 2026-07-11; the acceptance sample
  `examples/shapes.dawn` passes `dawn run` and `dawn test` unmodified, with JVM/native
  output identical):
  - ADTs (named-field construction, nested constructor patterns, `..`, structural equality)
    + exhaustiveness checking (the usefulness algorithm, listing the missing constructors
    exactly);
  - records (literals, punning, functional update `..base`, field access, record patterns),
    Float literal patterns;
  - generics (type parameters on fn/type, unification-based inference at the call site +
    seeding from the expected type, erasure + boxing), the prelude `Option`/`Result`, the
    builtin `List` (literals, `++`, `len`, `get`, `range`, for-in, structural equality);
  - lambdas (capture by value, capturing a `var` forbidden), the function type
    `fn(A) -> B !e`, top-level functions as values, effect variables (shared within a
    signature, instantiated at the call site), `map`/`filter`/`fold`; LambdaMetafactory
    measured to need no configuration under native-image;
  - `?` propagation (Option/Result, the original Err/None instance returned early), test
    blocks + `assert` (an `==` assertion failure reports both sides; `dawn test` runs them,
    `dawn build` strips them).
  - Left for later: list patterns `[x, ..rest]`, constructors as function values, effect
    union `!(e1|e2)`, let pattern destructuring, `derive Show`.
- **M2 the features it stands on** (done, 2026-07-12; the acceptance sample
  `examples/calc.dawn` passes `dawn run` and `dawn test` unmodified, native agreeing; 176
  tests green):
  - comptime (a pure-subset AST interpreter + a fuel budget + constants embedded /
    non-scalars materialised as static fields) and top-level const (SCREAMING_SNAKE,
    evaluated in declaration order, hence acyclic);
  - `use java` interop (signatures read by compile-time reflection, overloads resolved by
    scoring, null→`Option`, empty varargs, results discardable, everything `!io` — the
    mapping rules are nailed down in spec §9);
  - stdlib core: string functions (chars/split/join/trim/parse_int...),
    `read_file`/`write_file`/`args`/`read_line`, `expect`/`unwrap_or`;
  - triple-quoted multiline strings (interpolation was already complete), list patterns
    `[x, ..rest]`/`[..init, last]` (exhaustiveness decided precisely by length
    constructors);
  - prerequisites added off-plan: tuples + let/var pattern destructuring, the dot-call
    sugar `x.f(a)`, functions/builtins as first-class values (generics instantiated from
    the expected type), `?` inside a lambda (when the return type is known), `==` seeding
    inference for the right side from the left side's type — all forced out line by line by
    calc.dawn.
- **M3 the experience** (done, 2026-07-12; the error golden suite + fmt idempotence/fidelity
  tests green, 366 tests; calc/shapes and the derive-Show/constructor-value/effect-union
  samples produce identical output on JVM and native):
  - polishing diagnostics: `diag/Suggest.kt` (bounded Levenshtein, threshold
    `min(2, len/2)`, no guessing for a single character) wired into unknown
    variable/function/constructor/type/field, five sites; actionable hints filled in; a
    style guide pinned at the top of Diag.kt; `GoldenErrorTest` (`@TestFactory` +
    `-DupdateGolden` to regenerate) locking down the text of every message;
  - `dawn fmt`: a **token-stream re-layout tool** (`fmt/Formatter.kt`) — every token is
    reprinted verbatim from its span (strings and interpolations untouched to the
    character), only the whitespace between tokens changes; indentation uses an opener-line
    stack so blocks nest correctly; the three invariants (tokens preserved, comments
    preserved, idempotent) are checked by `FmtTest` over all of examples and the golden
    sources; `dawn fmt [--check]` + LSP `documentFormattingProvider`;
  - M1's loose ends taken in: **constructors as function values** (`map(xs, Some)`, LMF over
    a `dawn$ctor$` bridge), **effect union `!(e1|e2)`** (`Eff.Union` + normalisation, with
    `effSubsumes` driving both the coverage check and unification), **`derive Show`**
    (generates a toString for every ADT/tuple through `dawn/rt/Show`, rendering into the
    shape of legal Dawn source); let pattern destructuring and list patterns had already
    been finished ahead of time in M2;
  - **the first draft of the tutorial** `docs/tutorial.md` (11 chapters; `TutorialTest`
    extracts every dawn block, compiles it mechanically, and compares the output of the
    blocks that carry one).
  - Prerequisites added off-plan: rendering tuple elements and nesting, and taking type
    parameters as parameter types for a lambda in return position.
- **M4 engineering capability** (done, 2026-07-12; eight cuts `97e6aac..`, 748 tests green;
  the acceptance sample `examples/m4/json` passes all 318 cases of JSONTestSuite, JVM and
  native output identical): from "single-file toy" to "you can write a project in it", with
  the semantics nailed down in spec §10/§11 and §1.5/§2.2 before any code was written.
  - The module system: multi-file projects, `use` (whole module / selective `.{...}`), `pub`
    visibility, the `src/` root convention, cycles forbidden, comptime in topological order
    (the `check/ModuleLoader.kt` loader + `analyzeProgram`). Settled: a module alias with the
    same name as a binding = a compile error (disambiguation); types/constructors/constants
    cross module boundaries only through selective import; no `dawn.toml` (the directory
    convention is the project). In codegen, runtime classes were lifted to program scope and
    ADT class names carry a module prefix.
  - `Map`/`Set`: builtin persistent containers, `LinkedHashMap`/`LinkedHashSet` with
    copy-on-write, insertion order deterministic (JVM/native identical); a flat builtin API;
    matching `hashCode`s generated for ADTs/tuples/records so they can be keys.
  - char: **Go's rune road** — `'a'` is an `Int` literal equal to the code point (handled in
    the lexer, zero change to the type system), together with
    `code_points`/`from_code_points`/`str_len`/`substring`/`char_to_string`. **bytes
    deferred.** (**Since overturned**: from v0.57.0 the type of `'a'` is `Char`, an opaque
    type over `Int`; see spec §1.5 and [audit/nominal-types-design.md](audit/nominal-types-design.md)
    §7. The representation is still the code point, so the "zero cost" half still holds.)
  - `dawn run/test/build/fmt` accept a project directory; LSP multi-file support
    (`analyzeDocument` parses `use` off the disk; cross-file go-to-definition:
    FnSig/AdtInfo/FieldInfo/ConstDecl carry a `srcPath`, so imported
    functions/types/constructors/constants, `alias.fn` calls and the entries on a `use` line
    all jump to the file where they are defined).
  - **Traps**: `\r` is not a Dawn escape (use 13); (the old trap that `{` in a string was
    always interpolation disappeared with the switch to `$` interpolation);
    `assert`/assignment are statements and cannot be a match arm; `map_empty()` relies on
    needsExpected to defer inference until the sibling arguments have taken shape.
- **M5 the language website**: documentation, the tutorial, the rendered spec, the examples
  gallery, API docs generated by `dawn doc`.
  - The static generator is written in Dawn (dogfooding M4), the output is served by nginx,
    no backend;
  - the online playground is phase two (a compile service + a sandbox with a time limit).
  - Acceptance: the site is live, and the program that generates it is written in Dawn.
- **M6 rewriting the blog backend** (implementation done, 2026-07-14; thirteen cuts,
  backend-dawn about 4000 lines of Dawn, 46 unit tests green; all that is left is the
  operational work of cutting production traffic over + 7 days of observation, see
  `backend-dawn/` in the dawnop-site repository): real production dogfooding, deliberately
  scheduled before selfhosting — a real project forces out every sore spot in the stdlib and
  the diagnostics, and while the language is not yet frozen they are cheap to fix.
  **Acceptance verdict: the whole blog backend (the public site + the full admin content
  management + search + authentication + file management + monitoring) runs on Dawn, agrees
  field by field with the FastAPI reference implementation, and covers 100% of the route
  table (the one gap, `POST /api/fm/upload`, goes into M6.5 together with WebDAV, both
  missing the same thing: a binary request body).**
  - **The language reinforcements the sore spots forced out** (all landed in the spec, none
    of them a syntactic burden): `--cp` third-party classpath (§9.1/§12.1), the `java_try`
    exception barrier + the `catch_panic` supervision boundary (§9.8), `utf8_bytes` and
    narrowing an opaque value back to a concrete reference parameter (§9.5, which makes
    "take a binary body → pass it straight through" zero-copy), dotted imports of nested
    classes (§9.1), `to_lower`/`to_upper` (§11). **D8's "interop trio" was validated as
    sufficient by a real project**: the five foundation libraries (sql/crypto/http/web/json)
    are all `use java` + pure Dawn, and all of them stayed in the application layer (none
    entered the language's stdlib), confirming the judgement that "the language does not add
    async or web; it borrows the JVM ecosystem through interop".
  - **How contract fidelity was established**: the same copy of the SQLite database on both
    sides + the same `SECRET_KEY`, diffing JSON endpoint by endpoint; endpoints with side
    effects such as Qiniu or mail were compared against the official SDK using objects under
    an isolated prefix and then cleaned up, so production data never entered a test database.
    JWT interoperates in both directions with PyJWT (no existing session invalidated), jBCrypt
    accepts Python's `$2b$` hashes (normalised to `$2a$`), and the three kinds of Qiniu
    signature plus Tencent TC3 were all compared byte for byte against the official SDK.
  - The whole web foundation goes through `use java` and the language adds no async: HTTP is
    `com.sun.net.httpserver` + JVM 21 virtual threads (one thread per request, zero colouring
    in the language); JSON is the pure Dawn library from M4; SQLite is a thin JDBC wrapper;
    JWT/bcrypt/Qiniu use off-the-shelf Java libraries;
  - the prerequisite "interop trio" **has landed** (2026-07-12, three cuts 39507df/fdd44c2/
    and successors, 892 tests, spec §9.4–§9.6, decision record in D8): SAM conversion, opaque
    array pass-through, the zero-copy List bridge. The acceptance sample = the **playground
    runner** (the M5 phase-two backend, written in Dawn); the blog rewrite only started once
    that ran. The reason the spec's old §9.4 (now §9.7) blocked SAM (configuration-free
    native-image) was eliminated by a spike (`scripts/spike-sam/`, 2026-07-12):
    ASM-generated invokedynamic + LambdaMetafactory adapted to all three shapes
    (`Runnable`, a capturing `Supplier`, `HttpHandler`), hooked up to `jdk.httpserver` +
    virtual threads calling itself, with JVM and native output identical byte for byte and
    zero reflection configuration — LMF lambdas are expanded at native-image build time, so
    the boundary can be opened up;
  - migration strategy: endpoint by endpoint, with nginx switching traffic per route; WebDAV
    is large and lives on its own subdomain, so it migrates last or stays in Python.
  - Acceptance: the Vue frontend points at the Dawn backend without a single line changed,
    and the existing contract tests + end-to-end tests are green.
- **M6 retrospective → the fix batches** ([`history/m6-retro.md`](history/m6-retro.md) sets
  the priorities, progress in [`history/m7-progress.md`](history/m7-progress.md)): using the
  coding friction of a real production backend to work backwards to language/library/framework
  reinforcements. Item 1 (adding `find/take/drop/reverse` + string `index_of`), item 2 (fetching
  SQL columns by name) and item 3 (an open record for the web framework's Route + tag-aware
  middleware routing) have landed. **Item 4, "first-class `Bytes`" (2026-07-16, root cause 1)**:
  the settled design is in [`bytes-design.md`](bytes-design.md). The decision — `Bytes` at
  runtime is a bare `byte[]` (the same representation as an opaque array, no indirection), a
  new `TBytes` type + the builtins
  `utf8/decode/byte_len/byte_at/byte_slice/byte_index_of/as_bytes` + `++`/`==`/`Show`, and a
  Java `byte[]` return landing as `Bytes`; **`utf8_bytes`/`latin1_bytes` retired**, which kills
  the latin-1 string abuse across the whole stack along with the `Request.raw`/`Response.bin`
  bolt-ons (spec §9.5/§9.5.1/§11). UFCS makes `s.utf8()`/`b.decode(cs)` free, with no method
  mechanism. 1124 tests green.
- **M7 selfhosting**: Dawn compiles Dawn, the finale — after selfhosting, every change to the
  language has to be served to two compilers at once, so it comes after the language is
  basically frozen.
  - Four cuts (Lexer → Parser → Checker → CodeGen, with ASM through `use java`), each cut
    compared against the Kotlin version on golden output;
  - a three-stage bootstrap chain: stage0 (the Kotlin version) builds stage1 (the compiler
    written in Dawn) → stage1 compiles itself into stage2 → stage2 compiles itself again into
    stage3, and **stage2 and stage3 identical byte for byte** is the fixpoint;
  - the Kotlin version is frozen as the bootstrap seed from then on (following Go, which kept
    go1.4) and stops evolving.
  - Acceptance: the fixpoint + all tests passing under the self-hosted compiler, with JVM and
    native output identical.
  - **Acceptance verdict (done 2026-07-22)**: all four cuts landed (lex/parse/check/emit
    goldens compared byte for byte in CI, the corpus being every .dawn in the repository plus
    site and playground); the fixpoint stage2==stage3 (433 classes,
    `scripts/selfhost-fixpoint.sh`); "all tests pass" is implied by the byte identity — the
    classes emitted on both sides are identical byte for byte, so anything you run is
    identical. One cut was added off-plan: `selfhost build` producing a standalone executable
    jar of its own (vendoring in a dawn.tool shim + ASM), with the single jar re-emitting and
    rebuilding itself byte-identically (`scripts/selfhost-standalone.sh`, in CI).
    **The freeze takes effect from v0.6.0** (the seed jar is preserved permanently by a GitHub
    Release, links in [`bootstrap.md`](bootstrap.md)): the Kotlin version enters maintenance —
    bug fixes are still accepted, the seed must always be able to compile selfhost, but new
    language features are by default no longer done there (doing one means implementing it on
    both sides, and that cost is exactly the intended brake). The everyday toolchain
    (run/test/fmt/doc/LSP) is still the Kotlin version; moving those into selfhost is a later
    story and does not block the freeze.

Two tracks run horizontally through all of it: **the LSP** evolves in step with every feature
(M1 proved the cadence workable; on 2026-07-12 completionProvider was completed — scope
symbols/builtins/constructors/keywords + suppression inside strings and comments + `!`
triggering io, and the three language gaps the web framework knocked out in the same cut, G1
direct field calls / G2 type aliases / G3 rigid type parameters, landed the same day, spec
§2.4/§2.6/§2.5); and **the acceptance sample comes first** — before work starts on a
milestone, the thing it will be accepted against is written and committed.

**trait v1** (2026-07-13, six cuts landed, see D9 and [trait.md](trait.md)):
single-parameter typeclasses + dictionary passing; the `trait`/`impl`/`[T: Ord]` syntax,
coherence + the orphan rule, `< <= > >=` bridged to the built-in `Ord`, `derive Ord`,
`sort`/`sort_by`/`max`/`min`/`max_by`/`min_by`; the acceptance sample
`examples/traits.dawn`, tutorial §15, spec §3.5; 1094+ tests green, JVM/native compared and
identical.

**The ergonomics four-pack** (2026-07-12, settled after surveying the `[]`/inference/local
function conventions of Kotlin/Rust/Scala and others, 973 tests green): ① `[]` subscripting —
assertion semantics for List/Map (out of range / missing key panics), with `get`/`map_get`
kept as the enquiring form returning Option, and List subscripting supported in comptime (spec
§4.8); ② `return` for early exit — an expression of type Never, with the same scoping rule as
`?` (spec §4.9); ③ local named functions — `fn name(...)` inside a block, capturing, recursive,
self-tail-calls compiled into a loop, with recursive calls compiled to a direct invokestatic on
the impl method and self-references as values rebuilding the closure (spec §3.1, §12.4); ④
inferred signatures for private functions — a non-`pub` function may omit its return type and
effect, derived in topological order over the call graph, with recursion/`?`/`return` requiring
an annotation; const checking was split into two passes (register the types first, check the
initialisers second) so that a const can call an inferred function (spec §3.1). The web
framework and the site generator dogfooded `[]` the same day.
