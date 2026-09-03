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

Effects in the type

## feature-effects-body

Functions are pure by default; touching IO requires `!io` on the signature — the signature tells you whether it reaches outside, so testing a pure function needs no mocks. A second axis is **named effects you declare yourself**: `effect` declares the operations, `with handle` answers them on the spot, and the label propagates along signatures until exactly one syntactic node subtracts it. Arms are tail-resumptive by default, and an effect declared `ctl` may also carry a control arm (`op(x) resume k => ...`) that binds the continuation instead of resuming it, to be resumed once, later; resuming twice is not supported. The tier is specified, implemented on both backends and tested, and **the tier's internal consumers are in this repository**: the standard library's `std/io` declares `Fs`, the file system as a named effect, with `with_fs_real` as the production handler, and `Proc`, running another program, with `with_proc_real`, and `Env`, the working directory and the environment, with `with_env_real`, and two that are declared and not yet spoken for: `Exit`, ending the process as one `ctl` operation whose production arm never resumes, and `Console`, the four print functions; `std/gpu` follows with `Gpu`, the host side of a device, answered in tests by a pure fake device. The compiler itself runs on the tier: its `main` installs `with_fs_real` around the whole dispatch, so every file the toolchain reads or writes goes through `Fs`.

## feature-comptime-title

Compile-time evaluation: comptime

## feature-comptime-body

`comptime { ... }` is executed at compile time by the interpreter and the result is burned into the constant pool. There is no macro system, and none is needed — an ordinary function already runs at compile time.

## feature-parity-title

Two backends, one answer

## feature-parity-body

JVM bytecode and C (handed on to `cc`) are **peer** roads. Wherever divergence would be easiest, the language owns the thing itself: `Float` rendering is Schubfach in pure Dawn, the Unicode case tables belong to the compiler, `Map` iteration order is pinned to insertion. The differential corpus is compiled and run on both sides on every push, comparing stdout, stderr and exit code — a divergence is a red build.

## closing

Start with the [tutorial](tutorial/index.html); the authoritative definition of the language is the [specification](spec.html); every [example](examples/index.html) runs as it stands under `dawn run`; the standard library API reference is [here](stdlib.html); and the "why" behind each design decision is in the [design notes](design.html).

Every page of this site comes in both languages. The specification and the design notes are the one pair written in Chinese first and translated: they are living documents, edited in Chinese by every change to the language, so the Chinese half is the original and the English half is registered against it — `scripts/doc-check.py` goes red when the two drift apart. The rest of `docs/` is design notes and plans whose reader is the author, and it stays monolingual. The code, the compiler's diagnostics and the standard library's doc comments are English throughout — including the entries on the standard library page, which are the compiler's own text.
