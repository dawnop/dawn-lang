# xmap changelog

## 0.2.0

- `TileCall` 保留录制 id 与 parent。两个具名 FlashAttention 数值 helper
  在 Tile pane 中保留实际调用到定义的边，同一定义的重复调用分别显示。
  普通调用保留词法嵌套，定义边界与名称 span 仍严格检查。

## 0.1.4 (2026-10-23)

Add `explore_c` and `table_from_c` for an independent C call table and pane.
Gaps describe local C mapping; a zero count does not prove agreement with JVM.
The paired entries and strict oracle retain their previous semantics.

## 0.1.3 (2026-10-19)

A call the host maps record whose name span starts at no identifier is named
when the row says how it is written: an operator on a type with an
`Add`..`Neg` impl (`impl mul` with its name at the `*`) is named by its method
with the operator as its name span, and a number literal at a type with a
`FromInt`/`FromFloat` impl (`impl from_float`, its name the literal) by its
method with the literal as its name span. Both maps must say the same `what`.
Before, each was a gap: eight in the Playground's flash attention sample, none
in a program without such calls, whose tables are unchanged.

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
