# Explorer page copy, English, the original

Everything `explorer.html` says in words, in the order it says it. The
generator reads these sections by name (`site/src/gen/explorer.dawn`), the way
the GPU page reads `gpu.md`, so a section that is missing or renamed fails the
build instead of rendering an empty page. The Chinese translation is
`explorer.zh.md`, with the same keys and a digest of this file.

What is not here, on purpose: every number and every listing. The counts, the
Dawn source and the three outputs are read from the build's recording
(`site/build/explorer/`) and from the source files when the site is built.
Each program on the page needs a `prog-<name>-title` and a `prog-<name>-body`
section here, named as `site/explorer/record.py` names it.

## title

Source and output, call by call

## crumb

Explorer

## lede

A Dawn function on the left, what it compiled to on the right, in Tile IR, C or JVM bytecode. Pick a call and the lines it wrote light up; pick a line and its call does.

## how-title

How to read it

## how-body

Each underlined name in the source is a call. Click one, or move to it with Tab and press Enter, and its whole span is underlined and the lines it wrote itself are marked in every listing, a fainter mark on the lines of the calls inside it. The tabs switch listings and keep what is picked, so the same call can be followed from one backend to the next. Click a line of a listing to find the call it belongs to; in C and in bytecode the code of a nested call sits inside its caller's, and a line that holds both belongs to the inner one. Escape lets go.

## prog-flash_attn-title

flash_attn, three ways

## prog-flash_attn-body

The fused-attention kernel of the cuTile page. A kernel is an ordinary Dawn function under the `!Dev` effect, so the same source compiles for the host too, and that is what the C and JVM tabs show: the host code that runs the kernel and *builds* the Tile IR, where each `mma(..)` is a call into `packages/tileir`. The Tile IR tab is the program that run recorded, the one `tileiras` assembles for the GPU. One call, two readings: a function call on the host, one or more operations on the device. A call that only rebinds a host value, such as `carry`, wrote no Tile IR line of its own.

## prog-attend-title

attend, host only

## prog-attend-body

Attention without the exponential, on lists: dot products, a normalisation and a weighted sum. It is not a kernel, so it has no Tile IR tab. What it does have is the three shapes worth clicking: a call, a call inside a call (`range(0, len(xs))`), and a closure handed to a call, whose body the compiler lifts out into a function of its own.

## built-title

Where the lines come from

## built-body

Nothing here is a hand-written table. Each compiler says which call wrote which lines: `dawn __emitc --map` for C, `dawn __emit --map` for bytecode (listed by `javap -c -p -s`), and the recording behind the cuTile page for Tile IR. `site/explorer/record.py` restricts them to the function shown, and the generator checks them again, so a call without a place in a listing, or a range outside it, stops the build. The listings are made when the site is built and are not checked in, since they change whenever the compiler does. Only the function shown is listed: the rest of a program's C and bytecode is the standard library's and `tileir`'s.

## src-head

Dawn source

## tabs-label

Compiled output

## pane-tile

Tile IR, as recorded

## pane-c

C, from `dawn __emitc`

## pane-jvm

JVM, from `javap -c -p -s`

## shown

{n} of {total} lines

## facts-calls

calls

## note

Click a call's name, or press Enter on it, to mark its span and the lines it wrote in every listing. Click a line to find its call. Escape lets go.

## word-line

line

## word-lines

lines

## word-none

no lines of its own
