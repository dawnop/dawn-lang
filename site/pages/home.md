# Front-page copy — English, the original

Everything the front page says, in the order it says it. The generator reads
these sections by name (`site/src/gen/home.dawn`), so a section that is missing
or renamed fails the build instead of rendering an empty page.

Why the copy is here and not in the generator, where it used to live as
string literals: the front page has a second language, and two languages of
prose interleaved with HTML in a source file is where a translation quietly
stops matching. As content files they get the same treatment every other
translated document gets — `home.zh.md` carries a digest of this file and
`scripts/doc-check.py` goes red when the two part company.

**This file is the original.** Change it first, then `home.zh.md`.

What is not here, on purpose: the programs and their output (`site/pages/*.dawn`
and `*.out`, run by `doc-check.py`), the figures (`scripts/site-figures.sh`,
injected at build time), and words that are code (`effect`, `comptime`,
`match`, `!Dev`, file names), which read the same in both languages and live
in the generator.

## phase-hero

**−18°** astronomical twilight

## eyebrow

type · match · effect · !io

## lede

A small, elegant functional language: immutable data, algebraic data types with exhaustive matching, effects in the type signature.

## fact-selfhost

self-hosted compiler

## fact-backends

JVM and C, one answer

## fact-gpu

cuTile for NVIDIA GPUs

## cta-playground

Try in Playground →

## cta-primary

Start the tutorial

## theme-to-dark

Switch to dark theme

## theme-to-light

Switch to light theme

## phase-ideas

**−12°** nautical twilight · three ideas

## ideas-title

What the signature tells you.

## ideas-lede

What a function touches, computes ahead of time and matches on, checked by the compiler.

## idea-effects-title

Effects in the type

## idea-effects-body

Pure by default: touching IO needs `!io`, and effects you declare are answered by `with handle`.

## idea-comptime-title

Compile-time evaluation

## idea-comptime-body

`comptime { ... }` runs an ordinary function at compile time and burns the result into the constant pool.

## idea-data-title

Data and exhaustive matching

## idea-data-body

Immutable algebraic data, and a `match` that misses a case does not compile.

## phase-peers

**−6°** civil twilight · two backends

## peers-title

Two roads, one answer.

## peers-body

JVM bytecode and C are **peer** backends. On every push the differential corpus runs on both, and any difference in output fails the build.

## fig-native-corpus

programs in the differential corpus, each run on both backends

## fig-push-value

every push

## fig-push

a difference in stdout, stderr or exit code is a red build

## fig-selfhost-lines

lines of Dawn in the self-hosted compiler

## fork-title

One source, two backends, one answer

## fork-desc

main.dawn is compiled to JVM bytecode and, separately, to C handed on to cc. Both programs run, and their stdout, stderr and exit code must be byte-identical; a difference is a red build.

## fork-jvm

runs on JDK 21

## fork-c

a native binary

## fork-compare

stdout · stderr · exit code, byte for byte

## fork-red

a difference is a red build

## phase-gpu

**−3°** first light · the GPU

## gpu-title

A kernel is a Dawn function too.

## gpu-lede

A cuTile kernel is an ordinary Dawn function under a named effect, lowered to CUDA Tile IR. A pure fake device gives the same answer with no GPU.

## gpu-pipe

What happens to each side

## lane-device

device

## lane-host

host

## step-kernel

a Dawn fn

## step-record

the ops it raises

## step-tileir

text or bytecode

## step-tileiras

assembles a cubin

## step-launch

answered by a handler

## step-real

the CUDA driver, native only

## step-fake

the host reference, pure

## kernel-title

The kernel

## kernel-body

Running it records the operations it raises; the record becomes Tile IR, and `tileiras` assembles a cubin.

## kernel-out

the add, in the Tile IR `dawn run` prints for it

## kernel-fact-title

Checked on real hardware

## kernel-fact-body

`tile-gpu-diff` holds each kernel against a host reference; CI reds what its ledger does not cover.

## host-title

The host program

## host-body

`with_gpu_real` answers from the CUDA driver, `with_gpu_fake` from host memory.

## host-out

what the same `dawn run` prints for it, under `with_gpu_fake`

## host-fact-native-title

Native talks to the GPU

## host-fact-native-body

Only native reaches `libcuda`; on the JVM a real launch is refused.

## host-fact-pure-title

The fake device is pure

## host-fact-pure-body

So a `!Gpu` program runs in its tests and at comptime.

## phase-install

**0°** sunrise · install

## install-title

Pick a road and run it.

## install-lede

Two toolchains on every release, each with its SHA-256.

## road-native

Without a JVM

## road-native-tags

static · C backend · std inside

## road-jvm

With JDK 21

## road-jvm-tags

any platform · JVM backend · std inside

## install-foot

[Latest release](https://github.com/dawnop/dawn-lang/releases/latest) · [Tutorial, chapter 1](tutorial/01.html) · [Specification](spec.html) · [Examples](examples/index.html)
