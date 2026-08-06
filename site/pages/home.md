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

## eyebrow

type · match · effect · !io

## lede

A small, elegant functional language: immutable data, algebraic data types with exhaustive pattern matching, effects written into the type signature. The compiler is self-hosted, and its two peer backends — JVM bytecode and C — give the same answer on the same source. A gate keeps that true, not a promise.

## cta-primary

Start the tutorial →

## cta-secondary

See examples

## features-title

Core features

## feature-effects-title

Effects in the type, and more than two of them

## feature-effects-body

Functions are pure by default; touching IO requires `!io` on the signature — the signature tells you whether it reaches outside, so testing a pure function needs no mocks. The other axis is **named effects you declare yourself**: `effect` declares the operations, `with handle` answers them on the spot, and the label propagates along signatures until exactly one syntactic node subtracts it.

## feature-comptime-title

Compile-time evaluation: comptime

## feature-comptime-body

`comptime { ... }` is executed at compile time by the interpreter and the result is burned into the constant pool. There is no macro system, and none is needed — an ordinary function already runs at compile time.

## feature-parity-title

Two backends, one answer

## feature-parity-body

JVM bytecode and C (handed on to `cc`) are **peer** roads. Wherever divergence would be easiest, the language owns the thing itself: `Float` rendering is Schubfach in pure Dawn, the Unicode case tables belong to the compiler, `Map` iteration order is pinned to insertion. 59 corpus programs are compiled and run on both sides on every push, comparing stdout, stderr and exit code — a divergence is a red build.

## closing

Start with the [tutorial](tutorial/index.html); the authoritative definition of the language is the [specification](spec.html); every [example](examples/index.html) runs as it stands under `dawn run`; the standard library API reference is [here](stdlib.html); and the "why" behind each design decision is in the [design notes](design.html).

The tutorial and the standard library reference come in both languages. The examples, the specification and the design notes are **written in Chinese**, deliberately: their reader is the author, and prose that has to be translated before it can be written is prose that does not get written. What is translated is this page, the tutorial, the standard library's introduction and the project's [README](https://github.com/dawnop/dawn-lang). The code, the compiler's diagnostics and the standard library's doc comments are English throughout — including the entries on the standard library page, which are the compiler's own text.
