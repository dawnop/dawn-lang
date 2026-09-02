# Dawn

*[中文版](README.zh-CN.md)*

A **small, elegant functional language**: immutable data, algebraic data types with
exhaustive pattern matching, effects written into the type signature. The language is
small and so is the implementation — a compact standard library with **zero `use java`**;
a compiler that is **self-hosted, and the only one there is** (the original Kotlin
implementation is archived at the `kotlin-final` tag). Two **peer** backends: **JVM
bytecode** and **C** (handed on to `cc`). That the same source gives the same answer on
both is held true by a gate, not by a promise.

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

## Install

Every release publishes four install assets: two artifacts and the SHA-256 of
each. Check the digest. The seed the toolchain bootstraps from is verified on every
single use, and an install step that skipped the same check would be the one
place where that discipline stopped.

**Without a JVM** (linux-x86_64): one static executable, with `std` and the C
runtime inside it.

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawnc-linux-x86_64
curl -fsSLO $base/dawnc-linux-x86_64.sha256
sha256sum -c dawnc-linux-x86_64.sha256
chmod +x dawnc-linux-x86_64 && sudo mv dawnc-linux-x86_64 /usr/local/bin/dawnc

printf 'pub fn main() -> Unit !io = println("hello, dawn")\n' > hello.dawn
dawnc run hello.dawn
```

**With a JVM** (JDK 21 or newer, any platform): the toolchain jar carries `std`,
so the jar on its own is the whole toolchain.

```bash
base=https://github.com/dawnop/dawn-lang/releases/latest/download
curl -fsSLO $base/dawn-selfhost.jar
curl -fsSLO $base/dawn-selfhost.jar.sha256
sha256sum -c dawn-selfhost.jar.sha256      # macOS: shasum -a 256 -c

printf 'pub fn main() -> Unit !io = println("hello, dawn")\n' > hello.dawn
java -jar dawn-selfhost.jar run hello.dawn
```

These two are different compilers, not two downloads of one. `dawnc` is the C
backend and it refuses `use java`; the jar is the JVM toolchain. Which you want,
and what each cannot do, is under [The toolchain](#the-toolchain) below.

A release also carries two files that describe it rather than install it:
`dawn-pub-api.json`, every public signature in `std` and in `packages/` with
its effect row, and `dawn-pub-api-diff.md`, the classified difference from the
previous release. The second is the one to read before upgrading. Effects are
in the types, so a unit that started doing IO cannot do it quietly: the report
names the expansion. It is a report and not a gate, and it compares signatures
rather than behavior.

**From a checkout**, which is what the rest of this file assumes: `./bin/dawn`
downloads the seed on first use, verifies it against
`scripts/seed-checksums.txt`, and builds HEAD with it.

### A project

A project is a directory with `src/main.dawn` in it. There is nothing else to
create, and so there is no `dawn new`:

```text
myapp/
├── dawn.toml     # only once you have dependencies
└── src/
    └── main.dawn # pub fn main() -> Unit !io
```

`dawn run myapp` compiles and runs it; `src/` may hold as many modules as you
like, and `examples/projects/hello_mod` is this shape with three of them.
`dawn.toml` starts as two lines, `schema = 1` and `name = "myapp"`, after which
`dawn add <spec> --dir myapp` maintains it for you.

## What is different about it

Each item names, in parentheses, **something you can go and check**: a gate, a
measurement, a section of the spec.

### 1. Effects are in the type

Functions are pure by default; touching IO requires the `!io` label — the signature
tells you whether it reaches outside, so testing a pure function needs no mocks. That
axis carries weight everywhere: almost all of `std` is pure and says so, the compiler
labels the parts of itself that are not, and a function reaching outside from a
signature that stays silent about it is a compile error. (`scripts/doc-check.py`'s
effect-inference probe pins both branches: an explicitly pure signature that calls
`println` is rejected, an unannotated one infers `!io`.)

There is a second axis: **named effects you declare yourself**. `effect` declares the
operations, `with handle` answers them on the spot, the label propagates along
signatures and is subtracted at exactly one syntactic node, the handler.

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

That tier is **tail resumption**: a handler arm is an ordinary closure, no continuation
is captured, and so neither backend needs its own stack magic for it. The price is that
multi-shot and non-tail resumption are not supported. It is specified, implemented on
both backends and held by the differential corpus, and it has
**its first internal consumer**: `std/io` declares `Fs`, the file system as fourteen
operations, with `with_fs_real` as the handler production installs, so a test can answer
a file read from a table. The same module declares `Proc`, running another program as one
operation, with `with_proc_real` for production, so a test can hold a command line without
starting anything. The third is `std/gpu`, which declares `Gpu`, the host side of a
device as six operations, with a pure fake device as the handler a test installs, so a
`!Gpu` program runs on a machine with no GPU. Those are the three declarations, in the two
files under `std/` and `selfhost/src/` that carry any; `doc-check.py` keeps the list
(`NAMED_EFFECT_EXPECTED`) and reds this paragraph when a declaration appears outside it or
one of them goes away. So read it as a working feature
that has carried one real seam and not yet a real program, rather than as the thing that
makes Dawn different. ([docs/spec.md](docs/spec.md) §6.5; differential corpus
`scripts/spike-native/effect_handler.dawn`.)

### 2. Two backends, one answer, machine-enforced

Multi-backend languages usually ship a list of known divergences. There is no such
list here, because a divergence is a red build:

- `scripts/spike-native/run.sh` — the differential corpus is compiled and run on both
  sides, comparing **stdout, stderr and exit code**, plus an AddressSanitizer leg.
- `scripts/intrinsic-parity.py` — walks the primitive table; any primitive implemented
  on only one backend is red.
- `scripts/native-cli-diff.sh` — pins the native binary's `fmt`/`doc`/`add`/`lsp`
  output **byte for byte** to the JVM toolchain's.
- All of the above run on every push, alongside nine contracts:
  `unicode`/`array`/`hamt`/`pvec`/`path`/`inflate`/`error`/`rc`/`narrow`. Too expensive
  for every push is `scripts/native-fixpoint.sh` — **the whole compiler**: the C the JVM
  emits == the C the native binary emits == the C it emits again.

The spec writes this down as a promise ([docs/spec.md](docs/spec.md) §12.1). Its
scope is the programs both backends can compile: the C backend refuses `use java`,
so a program with Java interop in it has one answer rather than two and is outside
the comparison. Where that boundary runs is under
[Two different things are called "native"](#two-different-things-are-called-native).

### 3. On the native side there is neither a GC nor malloc/free

Ownership is inferred by the compiler, via Perceus reference counting plus reuse
analysis (rewrite in place when `rc == 1`). User code contains no memory-management
primitive at all. Measured on the whole compiler front end running `checker.dawn`,
after strings were brought into the accounting too: **peak RSS 1.46 GB → 81 MB
(−94%)**, wall clock 2.77s → 2.10s (−24%), **LSan unreachable-at-exit 246 million
bytes → 0**. On that same run reuse analysis rewrites in place rather than copying
for most of its opportunities (83% of `array_with` calls as this is written; it is a
rate, and the gates below budget it rather than pin it).
([docs/perceus-design.md](docs/perceus-design.md) §5.7, §6.4; gates
`scripts/rc-contract`, `scripts/array-contract`, `scripts/map-reuse-contract` and
spike-native's always-on `detect_leaks=1`.)

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
- **The narrow float formats are arithmetic, not a cast to the host's**
  (`std/narrow.dawn`): bfloat16, binary16 and binary32 are opaque types over
  `Float` whose every operation is that format's correctly rounded one, checked
  against an exact rational oracle on both backends. (`scripts/narrow-contract`,
  every push.)
- **The UTF-8 decoder is our own strict walker** (`runtime/c/dawn_rt.c`): it rejects
  overlong forms, surrogate halves and anything past U+10FFFF, answers U+FFFD on
  malformed input and reports how many bytes it consumed.
- `Ord[String]` is **code-point order**, and `cmp` promises only `-1`/`0`/`1`
  ([docs/spec.md](docs/spec.md) §3.5).

### 5. Traits have conditional impls and associated types; the collections are written in Dawn

Single-parameter, nominal typeclasses with dictionary passing. Conditional impls
(`impl[T: Eq] Eq[List[T]]`) and associated types (`type Item`, with `C.Item`
projections reduced at instantiation) are both in. Five of the seven built-in traits
carry syntax on their back: `Eq`→`==`, `Ord`→`<`, `Show`→`${...}`, `Iter`→`for..in`,
`Index`→`[]` — write an impl for your type and the syntax works. There is no
monomorphization: **a call site at a concrete type does not go through a dictionary,
it is a direct static call**; dictionaries appear only at generic boundaries.

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
./bin/dawn build <target> --native -o app   # that jar, packaged by GraalVM native-image
                                            #   (not the C backend; see below)
./bin/dawn fmt <target>                     # format in place (--check for CI)
./bin/dawn doc <target>                     # export the pub API as JSON; `add` edits dawn.toml format-preservingly
./bin/dawn lsp                              # the LSP server (stdio, for editors)
```

Dependencies come in two kinds: source packages (`url` + `hash`, content-addressed,
version selection by MVS — a single version is not a convenience for Dawn but a
load-bearing wall, since impl coherence is a whole-program unique mapping) and
`[java-deps]` (coursier resolves the transitive Maven closure; meaningful on the JVM
backend only). See [docs/package-design.md](docs/package-design.md).

The built-in LSP server exists once per backend with byte-aligned output: live
diagnostics, hover, go-to-definition, document outline. The front end does full error
recovery, so a broken file reports all of its errors at once. The VS Code extension is
on the [marketplace](https://marketplace.visualstudio.com/items?itemName=dawnop.dawn-lang)
(`dawnop.dawn-lang`); Neovim / Helix configuration is in [editors/](editors/).

### Two different things are called "native"

`dawn build --native` and `dawnc` both hand you an executable that runs without a
JVM installed, and they are not the same road. The word alone will not tell you
which one you are on:

| | `dawn build --native` | `dawnc` |
|---|---|---|
| What it is | GraalVM `native-image` over the jar the JVM backend just wrote | the C backend: Core to C, handed to `cc` |
| Which backend compiled your code | JVM bytecode | C |
| `use java` | works, compiled into the image | **refused**, on purpose |
| `[java-deps]` | resolved and included | not applicable |
| Needs on the machine | GraalVM `native-image` | a `cc` |
| Where you get it | you run it, from a checkout | `dawnc-linux-x86_64`, in every release |
| Targets | wherever GraalVM runs | linux-x86_64 only |

One file settles it. `examples/interop/interop.dawn` uses `use java`:
`dawn build --native` writes an executable that runs, while `dawnc check` on
the same file answers `Java interop needs a JVM host with a class path to
resolve java.lang.String against; this build has none`.

The collision is historical: `--native` predates the C backend, and everything
under `scripts/` spelled `native` (`spike-native`, `native-fixpoint.sh`,
`native-cli-diff.sh`, `release-native.sh`) means the C backend, not the flag.
Read the flag as "package the JVM build ahead of time" and the scripts as "the
second backend".

**This is also the scope of the parity claim above.** "Two backends, one answer"
is a claim about the programs both backends can compile, and every program
containing `use java` is outside it, because on those there is no second answer
to compare against. Every entry under `scripts/spike-native/` is inside that
intersection by construction.

### The road without a JVM

**As of v0.50.0**, every release also carries **`dawnc-linux-x86_64`**: a single-file
static executable produced by the C backend, with `std` and the C runtime embedded.
It needs neither this repository nor a JVM.

Its subcommands are `check|emitc|build|run|test|fmt|doc|add|lsp`; `build`/`run` invoke
the machine's `cc` (overridable with `$CC`) and the rest do not touch a C toolchain at
all. Packaging a jar, `lock` and `cache` need a JVM and are therefore not among its
subcommands. The one target is linux-x86_64; the reasoning is in
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

Current toolchain 0.72.0, M0–M8 implemented. <!-- doc-check: version --> The lines of
work since then — the C backend and native bootstrap, Perceus, trait v2, effect
handlers, package management, and the
[cuTile device backend](docs/tile-backend-design.md) — are recorded in their own
design documents under `docs/`.

## Roadmap and contributing

[ROADMAP.md](ROADMAP.md) says where the work is going and which lines are
closed; concrete starting points are kept as GitHub issues.
[CONTRIBUTING.md](CONTRIBUTING.md) describes how a change travels from an idea
to code here: a design document first, and gates instead of review checklists.

## License

[Apache-2.0](LICENSE). Third-party code packaged into the `dawn` fat jar, and their
respective licenses, are listed in [NOTICE](NOTICE).
