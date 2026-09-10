<p align="center">
  <a href="https://dawn-lang.dawnop.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="site/assets/logo-white.svg">
      <img src="site/assets/logo.svg" width="180" alt="Dawn">
    </picture>
  </a>
</p>

<div align="center">

# Dawn

</div>

<p align="center">
  <em>A small, elegant functional language: immutable data, algebraic data types,
  effects written into the type signature.</em>
</p>

<p align="center">
  <a href="https://github.com/dawnop/dawn-lang/actions/workflows/ci.yml"><img
    src="https://img.shields.io/github/actions/workflow/status/dawnop/dawn-lang/ci.yml?branch=main&amp;label=CI"
    alt="CI"></a>
  <a href="https://github.com/dawnop/dawn-lang/releases"><img
    src="https://img.shields.io/github/v/release/dawnop/dawn-lang" alt="Latest release"></a>
  <a href="LICENSE"><img
    src="https://img.shields.io/github/license/dawnop/dawn-lang" alt="License"></a>
  <a href="https://dawn-lang.dawnop.com"><img
    src="https://img.shields.io/badge/website-dawn--lang.dawnop.com-4F46E5" alt="Website"></a>
  <a href="https://dawn-lang.dawnop.com/playground.html"><img
    src="https://img.shields.io/badge/playground-try%20it-7C3AED" alt="Playground"></a>
  <a href="https://marketplace.visualstudio.com/items?itemName=dawnop.dawn-lang"><img
    src="https://img.shields.io/badge/VS%20Code-marketplace-007ACC"
    alt="VS Code extension"></a>
  <img src="https://img.shields.io/badge/backends-JVM%20%7C%20C%20%7C%20cuTile-DB2777"
    alt="Backends: JVM, C and cuTile">
</p>

*[中文版](README.zh-CN.md)*

A **small, elegant functional language**: immutable data, algebraic data types with
exhaustive pattern matching, effects written into the type signature. The language is
small and so is the implementation — a compact standard library with **zero `use java`**;
a compiler that is **self-hosted, and the only one there is** (the original Kotlin
implementation is archived at the `kotlin-final` tag). Two **peer** backends: **JVM
bytecode** and **C** (handed on to `cc`). That the same source gives the same answer on
both is held true by a gate, not by a promise. For NVIDIA GPUs there is a **cuTile
device backend**: a kernel body is an ordinary Dawn function under a named effect,
lowered to CUDA Tile IR and launched through the CUDA driver, and a pure fake device
runs the same host program, for the same answer, on a machine with no GPU.

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

Every release publishes two artifacts, each with its SHA-256. Check the digest.

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
`dawn-pub-api.json`, every public signature in `std` and in `packages/` with its
effect row, and `dawn-pub-api-diff.md`, the classified difference from the previous
release. Read the second before upgrading: effects are in the types, so a unit that
started doing IO cannot do it quietly, and the report (signatures, not behavior)
names the expansion.

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

Functions are pure by default; touching IO requires the `!io` label, so the signature
tells you whether it reaches outside; reaching outside from a silent signature is a
compile error. (`scripts/doc-check.py`'s effect-inference probe pins both branches: a
pure signature calling `println` is rejected, an unannotated one infers `!io`.)

A second axis is **named effects you declare yourself**: `effect` declares the
operations, `with handle` answers them on the spot, and the label travels along
signatures, subtracted at exactly one syntactic node, the handler.

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

Arms come in two shapes. A **tail-resumptive** arm is an ordinary closure: it runs in
place, its return value is the operation's result, capturing no continuation. An
effect declared `ctl` may also carry a **control arm** (`op(x) resume k => ...`), which
binds the continuation instead of resuming it: `k` is an ordinary function value that
may outlive its handler's frame and may be resumed at most **once**. One that will never
be resumed is abandoned with `discard`.

Both are specified, implemented on both backends and held by the differential
corpus, and **the tier's internal consumers are in this repository**: `std/io` declares
`Fs`, `Proc`, `Env`, `Exit` and `Console`, `std/gpu` declares `Gpu`, each with
production's handler beside it and a fake for tests. `doc-check.py` keeps that list
(`NAMED_EFFECT_EXPECTED`) and reds this paragraph if a declaration appears elsewhere
under `std/` or `selfhost/src/`. The compiler runs on the tier itself: its `main` is
wrapped in `Fs` and `Exit` handlers, and the driver's analysis tests run that code over
an in-memory file tree (`selfhost/src/driver/fsmem.dawn`).
([docs/spec.md](docs/spec.md) §6.5;
[docs/oneshot-design.md](docs/oneshot-design.md); differential corpus
`scripts/spike-native/effect_handler.dawn`; gallery `examples/effects/`.)

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
the comparison, while every entry under `scripts/spike-native/` is inside that
intersection by construction ([The toolchain](#the-toolchain)).

The same idea reaches the GPU. A kernel written for the **cuTile device backend** is
compared against a handwritten host reference on real hardware by
`scripts/tile-gpu-diff`, which appends its verdict to a ledger; a CI gate reds any
change to the tile path that the ledger's last run does not cover. The host side still
runs on JVM or native C: only native talks to `libcuda`, and on the JVM a real-device
launch is refused outright.
([docs/tile-backend-design.md](docs/tile-backend-design.md).)

### 3. On the native side there is neither a GC nor malloc/free

Ownership is inferred by the compiler, via Perceus reference counting plus reuse
analysis (rewrite in place when `rc == 1`), and user code contains no
memory-management primitive at all. Measured on the whole compiler front end running
`checker.dawn`, that is **peak RSS down 94%**.
([docs/perceus-design.md](docs/perceus-design.md) §5.7, §6.4; gates
`scripts/rc-contract`, `scripts/array-contract`, `scripts/map-reuse-contract` and
spike-native's always-on `detect_leaks=1`.)

### 4. The semantics do not borrow from the host

An answer should not change with the host's version, so where there is data the
language carries its own:

- **The Unicode case and classification tables belong to the compiler**
  (`selfhost/src/embed/unicode_case.dawn`, `unicode_class.dawn`); both backends are
  handed the same table, one by codegen into `dawn/rt/Strings` and one by `__emitc`
  into the generated C. (`scripts/unicode-contract`, every push.)
- **`Float` rendering is Schubfach in pure Dawn** (`std/fmt.dawn`): the rule is owned
  by the spec, not by the host's algorithm.
- **The narrow float formats are arithmetic, not a cast to the host's**
  (`std/narrow.dawn`): bfloat16, binary16 and binary32 are opaque types over `Float`,
  every operation correctly rounded for that format and checked against an exact
  rational oracle on both backends. (`scripts/narrow-contract`, every push.)
- **The UTF-8 decoder is our own strict walker** (`runtime/c/dawn_rt.c`): overlong
  forms, surrogate halves and anything past U+10FFFF are rejected, malformed input
  answering U+FFFD.
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
recoverable failure goes through `Result` + `?`. An exception thrown by a `use java`
call still **passes through** the Dawn stack and terminates the program (panic
semantics). Two barriers sit at that boundary, both returning
`Result[T, ForeignError]`: `catch_fault` intercepts foreign failure and lets panics
through, `catch_panic` is an isolation point, and `bracket` intercepts nothing at all,
guaranteeing only that release runs exactly once on every exit path.
([docs/spec.md](docs/spec.md) §9.8.)

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
single-version selection by MVS, which impl coherence needs) and `[java-deps]`
(coursier resolves the transitive Maven closure; meaningful on the JVM backend only).
See [docs/package-design.md](docs/package-design.md).

The built-in LSP server exists once per backend with byte-aligned output: live
diagnostics, hover, go-to-definition, document outline. The front end does full error
recovery, so a broken file reports all of its errors at once. The VS Code extension is
on the [marketplace](https://marketplace.visualstudio.com/items?itemName=dawnop.dawn-lang)
(`dawnop.dawn-lang`); Neovim / Helix configuration is in [editors/](editors/).

Two things are called native, and they are different roads. `dawn build --native`
packages the jar the JVM backend just wrote with GraalVM `native-image`, so
`use java` still works; `dawnc`, the static linux-x86_64 executable every release
ships, is the C backend with `std` and the runtime embedded, needs no JVM and
refuses `use java`. The bootstrap seed is still a jar
(`scripts/seed-release.txt`), and the JVM backend is still a first-class target.
The rest is in [docs/native-driver-plan.md](docs/native-driver-plan.md).

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

Current toolchain 0.76.0, M0–M8 implemented. <!-- doc-check: version --> The lines of
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
