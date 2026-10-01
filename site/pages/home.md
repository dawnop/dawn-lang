# Front-page copy — English, the original

Everything the front page says, in the order it says it. The generator reads
these sections by name (`site/src/gen/copy.dawn`), so a section that is missing
or renamed fails the build instead of rendering an empty page.

Why the copy is here and not in `site/src/gen/pages.dawn`, where it used to
live as string literals: the front page has a second language now, and two
languages of prose interleaved with HTML in a source file is where a
translation quietly stops matching. As content files they get the same
treatment every other translated document gets — `home.zh.md` carries a digest
of this file and `scripts/doc-check.py` goes red when the two part company.

**This file is the original.** Change it first, then `home.zh.md`.

`cta-playground` and `install` are written ahead of the generator change that
places them on the page; until that lands, the generator does not read them.

## eyebrow

type · match · effect · !io

## lede

A small, elegant functional language: immutable data, algebraic data types with exhaustive pattern matching, effects written into the type signature. The compiler is self-hosted, and its two peer backends, JVM bytecode and C, give the same answer on the same source; a cuTile device backend takes kernels to NVIDIA GPUs, and a pure fake device gives that same answer where there is no GPU. That is checked by machine, not promised: on every push the same programs run on both backends, and a difference in their output fails the build.

## cta-playground

Try in Playground →

## cta-primary

Start the tutorial →

## cta-secondary

See examples

## install

Install: download `dawnc` (one static binary, no JVM) or `dawn-selfhost.jar` (JDK 21) from the [latest release](https://github.com/dawnop/dawn-lang/releases/latest); [chapter 1 of the tutorial](tutorial/01.html) walks through it.

## features-title

Core features

## feature-effects-title

Effects in the type

## feature-effects-body

Functions are pure by default; touching IO requires `!io` on the signature, which tells you whether it reaches outside. A second axis is **named effects you declare**: `effect` declares the operations, `with handle` answers them, and the label travels along signatures, subtracted at the handler. A `ctl` effect may also carry a control arm, which binds the continuation instead of resuming it, once at most. Both backends implement it, and **the tier's internal consumers are in this repository**: `std/io` declares `Fs`, `Proc`, `Env`, `Exit` and `Console`, `std/gpu` declares `Gpu`, with production handlers beside the declarations and fakes in the tests. The compiler runs on the tier: its `main` is wrapped in `Fs` and `Exit` handlers, so every file it reads and every exit status goes through an effect.

## feature-comptime-title

Compile-time evaluation: comptime

## feature-comptime-body

`comptime { ... }` is executed at compile time by the interpreter and the result is burned into the constant pool. There is no macro system, and none is needed — an ordinary function already runs at compile time.

## feature-parity-title

Two backends, one answer

## feature-parity-body

JVM bytecode and C (handed on to `cc`) are **peer** roads. Wherever divergence would be easiest, the language owns the thing itself: `Float` rendering is Schubfach in pure Dawn, the Unicode case tables belong to the compiler, `Map` iteration order is pinned to insertion. The differential corpus is compiled and run on both sides on every push, comparing stdout, stderr and exit code — a divergence is a red build.

## closing

Start with the [tutorial](tutorial/index.html); the authoritative definition of the language is the [specification](spec.html); every [example](examples/index.html) runs as it stands under `dawn run`; the standard library API reference is [here](stdlib.html); and the [design history](design.html) is the record of the early design decisions, frozen at M7.

Every page of this site comes in both languages. For the specification and the design history the Chinese text is the original and the English text is its translation; everywhere else English is the original. The code, the compiler's diagnostics and the standard library's doc comments are English throughout, including the entries on the standard library page, which are the compiler's own text.
