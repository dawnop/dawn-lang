# Dawn

*[中文版](README.zh-CN.md)*

A **small, elegant functional language**: immutable data, algebraic data types with
exhaustive pattern matching, effects written into the type signature. The language is
small and so is the implementation — a standard library of 10 modules and 3,300 lines
with **zero `use java`**; a compiler that is **self-hosted, and the only one there is**
(`selfhost/`, 54,000 lines of Dawn; the original Kotlin implementation is archived at
the `kotlin-final` tag). Two **peer** backends: **JVM bytecode** and **C** (handed on
to `cc`). That the same source gives the same answer on both is held true by a gate,
not by a promise.

```dawn run
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)

fn area(s: Shape) -> Float =
  match s {
    Circle(r)  -> 3.14159 * r * r
    Rect(w, h) -> w * h
  }

pub fn main() -> Unit !io =
  [Circle(1.0), Rect(2.0, 3.0)]
    |> map(area)
    |> fold(0.0, (a, x) => a + x)
    |> t => println("total: $t")
```

## What is different about it

Each item names, in parentheses, **something you can go and check**: a gate, a
measurement, a section of the spec.

### 1. Effects are in the type, and there are more than two of them

Functions are pure by default; touching IO requires the `!io` label — the signature
tells you whether it reaches outside, so testing a pure function needs no mocks. That
is the base axis. The other axis is **named effects you declare yourself**: `effect`
declares the operations, `with handle` answers them on the spot, the label propagates
along signatures and is subtracted at exactly one syntactic node — the handler.

```dawn run
effect Ask {
  fn ask() -> Int
}

## Pure. The signature says it asks; it does not say whom.
fn total() -> Int !Ask = ask() + ask()

pub fn main() -> Unit !io = {
  with handle Ask { ask() => 21 }
  println("${total()}")
}
```

This tier is **tail resumption**: a handler arm is an ordinary closure, no continuation
is captured, and so neither backend needs its own stack magic for it. The price is that
multi-shot and non-tail resumption are not supported. Neither `std` nor the compiler
itself uses named effects yet — the feature is purely additive.
([docs/spec.md](docs/spec.md) §6.5; differential corpus
`scripts/spike-native/effect_handler.dawn`.)

### 2. Two backends, one answer, machine-enforced

Multi-backend languages usually ship a list of known divergences. There is no such
list here, because a divergence is a red build:

- `scripts/spike-native/run.sh` — 59 corpus programs compiled and run on both sides,
  comparing **stdout, stderr and exit code**, plus an AddressSanitizer leg.
- `scripts/intrinsic-parity.py` — walks the primitive table; any primitive implemented
  on only one backend is red.
- `scripts/native-cli-diff.sh` — pins the native binary's `fmt`/`doc`/`add`/`lsp`
  output **byte for byte** to the JVM toolchain's.
- All of the above run on every push, alongside eight contracts:
  `unicode`/`array`/`hamt`/`pvec`/`path`/`inflate`/`error`/`rc`. Too expensive for
  every push is `scripts/native-fixpoint.sh` — **the whole compiler**: the C the JVM
  emits == the C the native binary emits == the C it emits again.

The spec writes this down as a promise ([docs/spec.md](docs/spec.md) §12.1).

### 3. On the native side there is neither a GC nor malloc/free

Ownership is inferred by the compiler, via Perceus reference counting plus reuse
analysis (rewrite in place when `rc == 1`). User code contains no memory-management
primitive at all. Measured on the whole compiler front end running `checker.dawn`,
after strings were brought into the accounting too: **peak RSS 1.46 GB → 81 MB
(−94%)**, wall clock 2.77s → 2.10s (−24%), **LSan unreachable-at-exit 246 million
bytes → 0**. Reuse analysis rewrites in place 73.8% of the time across the whole
compiler. ([docs/perceus-design.md](docs/perceus-design.md) §5.7; gates
`scripts/rc-contract` and spike-native's always-on `detect_leaks=1`.)

### 4. The semantics do not borrow from the host

An answer should not change with the host's version, so wherever there is data the
language carries its own:

- **The Unicode case and classification tables belong to the compiler**
  (`selfhost/src/embed/unicode_case.dawn`, `unicode_class.dawn`); codegen writes them into
  `dawn/rt/Strings` and `__emitc` writes them into the generated C, so both backends
  carry the same table. It used to be `Character.toUpperCase` on one side and a
  generated header on the other — which is "one answer" only while two JDKs happen to
  agree on their Unicode version. (`scripts/unicode-contract`, every push.)
- **`Float` rendering is Schubfach in pure Dawn** (`std/fmt.dawn`): the rule is owned
  by the spec and does not follow the host if the host changes algorithm.
- **The UTF-8 decoder is our own strict walker** (`runtime/c/dawn_rt.c`): it rejects
  overlong forms, surrogate halves and anything past U+10FFFF, answers U+FFFD on
  malformed input and reports how many bytes it consumed.
- `Ord[String]` is **code-point order**, and `cmp` promises only `-1`/`0`/`1`
  ([docs/spec.md](docs/spec.md) §3.5).

### 5. Traits have conditional impls and associated types; the collections are written in Dawn

Single-parameter, nominal typeclasses with dictionary passing. Conditional impls
(`impl[T: Eq] Eq[List[T]]`) and associated types (`type Item`, with `C.Item`
projections reduced at instantiation) are both in. Four of the six built-in traits
carry syntax on their back: `Eq`→`==`, `Show`→`${...}`, `Iter`→`for..in`, `Index`→`[]`
— write an impl for your type and the syntax works. There is no monomorphization:
**a call site at a concrete type does not go through a dictionary, it is a direct
static call**; dictionaries appear only at generic boundaries.

`Map`/`Set` are 32-way HAMTs and the persistent `List` is a pvec, all written in pure
Dawn under `std/`. The only collection primitives a backend owes are five `Array`
operations and a `popcount` — so a new backend gets every container for free.
([docs/spec.md](docs/spec.md) §3.5, §4.8; [docs/trait.md](docs/trait.md); gates
`hamt-contract`/`pvec-contract`/`array-contract`.)

### 6. Self-hosted, with the seed discipline enforced by machine

The chain is seed → A → B → C, and `cmp B C` must be byte-identical; on a tag
`release.yml` re-runs the entire chain, and a red link anywhere means no release.
`selfhost/src` may only use language features **the current seed already supports** —
a seed that cannot compile HEAD is red immediately. The day-to-day oracle is
`scripts/selfhost-prev-diff.sh`: the previous release and HEAD compile the same corpus,
and **an undeclared byte difference is red**. ([docs/bootstrap.md](docs/bootstrap.md).)

## What is just as important: what is absent

No null, no inheritance, no macros (for compile-time computation write
`comptime { ... }` and the result is burned into the constant pool), no async, no
**user-defined** operators (the operator set is fixed; four of them dispatch to your
types through the traits above), no mutable references. The reasoning is in
[docs/design.md](docs/design.md).

**"No exceptions" needs stating precisely**: Dawn has no `throw`/`catch`, and every
recoverable failure goes through `Result` + `?`. But an exception thrown by a
`use java` call still **passes through** the Dawn stack and terminates the program
(panic semantics). There are two barriers at that boundary, both returning
`Result[T, ForeignError]`: `catch_fault` intercepts foreign failure and lets panics
through, and `catch_panic` is an isolation point (one request's panic becomes a 500
instead of taking down the process). `bracket` intercepts nothing; it only guarantees
that release runs exactly once on every exit path. `cast` no longer **throws**: its
signature is pure and failure is a value. This division of labour is
backend-independent — native has no exceptions, and a failure carries a kind along the
same `longjmp`. ([docs/spec.md](docs/spec.md) §9.8.)

## The toolchain

`<target>` may be a single `.dawn` file or a project directory (with `src/main.dawn`
as the entry point).

```bash
# Needs JDK 21. The first run downloads the seed (the previous release's
# dawn-selfhost.jar) automatically and compiles HEAD with it.
./bin/dawn run examples/projects/hello_mod        # compile and run (single file or multi-module project)
./bin/dawn test <target>                    # run the test blocks inlined in the source (stripped at build)
./bin/dawn build <target> -o app.jar        # JVM backend: an executable jar
./bin/dawn build <target> --native -o app   # the above, plus GraalVM native-image
./bin/dawn fmt <target>                     # format in place (--check for CI)
./bin/dawn doc <target>                     # export the pub API as JSON; `add` edits dawn.toml format-preservingly
./bin/dawn lsp                              # the LSP server (stdio, for editors)
```

Dependencies come in two kinds: source packages (`url` + `hash`, content-addressed,
version selection by MVS — a single version is not a convenience for Dawn but a
load-bearing wall, since impl coherence is a whole-program unique mapping) and
`[java-deps]` (coursier resolves the transitive Maven closure; meaningful on the JVM
backend only). See [docs/package-design.md](docs/package-design.md). Note that
`--native` goes through **GraalVM native-image** (compiling the jar from the previous
step), which is a different road from the C backend below.

The built-in LSP server exists once per backend with byte-aligned output: live
diagnostics, hover, go-to-definition, document outline. The front end does full error
recovery, so a broken file reports all of its errors at once. VS Code / Neovim / Helix
configuration is in [editors/](editors/).

### The road without a JVM

**As of v0.50.0**, every release also carries **`dawnc-linux-x86_64`**: a single-file
static executable produced by the C backend (about 3.6 MB), with `std` and the C
runtime embedded. It needs neither this repository nor a JVM.

Its subcommands are `check|emitc|build|run|test|fmt|doc|add|lsp`; `build`/`run` invoke
the machine's `cc` (overridable with `$CC`) and the rest do not touch a C toolchain at
all. It **refuses `use java`** — that is this backend's answer, not a defect. Packaging
a jar, `lock` and `cache` need a JVM and are therefore not among its subcommands.
There is one target, linux-x86_64; the reasoning is in
[docs/native-driver-plan.md](docs/native-driver-plan.md) §22.1.

**Precisely stated**: "you can use Dawn without ever touching a JVM" holds — there is a
complete path from compiler to artifact. But the **bootstrap seed is still a jar**
(`scripts/seed-release.txt`), `bin/dawn` is still the JVM toolchain, and the JVM
backend is still a first-class target.

## Documentation

Everything the website renders comes in both languages: this README (`README.md` is the
original, [README.zh-CN.md](README.zh-CN.md) the translation), the front page, the
tutorial, the standard library reference, the specification and the design notes. The
last two are the pair whose original is the Chinese one — every change to the language
edits them, in Chinese, so that is where the text is written and the English half is
registered against it. The rest of `docs/` is design notes, plans and landing logs and is
**written in Chinese**, deliberately and for the time being: its reader is the author,
and prose that has to be translated before it can be written is prose that does not get
written.

- [docs/tutorial.md](docs/tutorial.md) — the tutorial (also in
  [Chinese](docs/tutorial.zh-CN.md))
- [docs/design.en.md](docs/design.en.md) — design goals and decision records: why this
  and not that (translated from [docs/design.md](docs/design.md))
- [docs/spec.en.md](docs/spec.en.md) — the language specification, the authoritative
  definition (translated from [docs/spec.md](docs/spec.md))
- [docs/bootstrap.md](docs/bootstrap.md) — the bootstrap chain and the seed-advance
  protocol (Chinese)
- [docs/README.md](docs/README.md) — the index of every design document, each with a
  status; examples are in [examples/](examples/)

## Status

Current toolchain 0.59.0, M0–M8 implemented. <!-- doc-check: version --> The lines of
work since then — the C backend and native bootstrap, Perceus, trait v2, effect
handlers, package management — are recorded in their own design documents under
`docs/`.

## License

[Apache-2.0](LICENSE). Third-party code packaged into the `dawn` fat jar, and their
respective licenses, are listed in [NOTICE](NOTICE).
