# xmap changelog

## 0.1.2 (2026-10-08)

A `lit` row is spelled by the bare number it was made from, so a Tile IR
recording of `mma(a, b, 0.0)` (the compiler makes the tile constant itself)
is no gap. Tables for programs written with `lit(..)` are unchanged.

## 0.1.1 (2026-10-07)

A listing's member headers are recognised whatever characters the program's
names are written in. `größe` is a valid Dawn function name and javap prints it
as it is, but the reader allowed only ASCII, so a program with such a name had
that method (and every call in it) reported as a gap. Found by the online
compile view's test with a program of odd names, which the eleven starter
programs do not have. Output for ASCII names is unchanged.

## 0.1.0 (2026-10-07)

First version. It does the job `site/explorer/record.py` did in Python, as a
package, so that the static explorer page and the Playground's online compile
view (`docs/playground-compile-design.md`) share one implementation. The
differential against the Python assembly was byte for byte on both page
programs and the eleven Playground samples.
