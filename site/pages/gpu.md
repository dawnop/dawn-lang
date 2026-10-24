# cuTile backend page copy, English, the original

Everything `gpu.html` says in words, in the order it says it. The generator
reads these sections by name (`site/src/gen/gpu.dawn`), the way the front
page reads `home.md`, so a section that is missing or renamed fails the build
instead of rendering an empty page. The Chinese translation is `gpu.zh.md`,
with the same keys and a digest of this file.

Every section says one or two sentences; the figures, the call map and the
ledgers say the rest. What is not here, on purpose: every number. The
coverage counts, the golden kernel count and the device ledgers are read from
`scripts/tileir-features/`, `scripts/tile-golden/` and
`scripts/tile-gpu-diff/` when the site is built, so none of them can go stale
in this file. Where a sentence carries a number, `{n}` and `{total}` mark
where the generator puts it. Words that are code (`!Dev`, `tileiras`, file
names, the ledger's statuses) live in the generator.

## title

Dawn's cuTile backend

## lede

A GPU kernel in Dawn is an ordinary function under the `!Dev` effect. Run it once and every operation it raises is recorded as CUDA Tile IR, which NVIDIA's `tileiras` assembles into a cubin.

## layers-title

Two layers, two effects

## layers-body

The host owns the buffers and the device computes over them; they meet only where the host launches a kernel by name.

## layer-host

the host

## layer-host-body

`std/gpu`'s `Gpu` effect: allocate, upload, launch, download. `with_gpu_real` drives the CUDA driver, `with_gpu_fake` runs the same program with no GPU.

## layer-device

the device

## layer-device-body

`packages/tileir`'s `Dev` effect. One recorded run of a kernel becomes Tile IR text, or bytecode for `tileiras`.

## api-title

Writing a kernel

## api-body

A kernel says where it reads and writes once, on its parameters' markers, and states no shape it could read off its operands. Each piece of code below is cut from the golden kernels when the site is built.

## api-learn

Learn to write one

## api-cells-title

The markers are the addressing

## api-cells

`In` and `Out` cut each tensor into cells, and the `Out` cells are the launch grid. The body reads its block's cell and writes its block's cell; it names no offset.

## api-shapes-title

Shapes come from the operands

## api-shapes

No operation takes a shape or a format. A constant, and a reduction of a rank-1 tile, are rank-0 tiles: they widen on their own where they meet a wider operand, and nowhere else.

## api-out-title

Writes go through `Out`

## api-out

`store_cell` and `store_sub` are the only writes an `Out` takes, and an accumulator starts from `zeros` of it. `FREE_AXIS` leaves a dimension for the kernel to pick, here the loop's `k`.

## api-shared-title

`Shared` is the escape hatch

## api-shared

An atomic is not a cell write, and neither is a scatter whose addresses are data or a block that writes two regions. Those write through `Shared`, and the marker says so where a reader can find it.

## api-keepdims-title

Reductions that keep their dimension

## api-keepdims

`keepdims: true` reduces each row to a column of length one, and the column widens back where it meets the whole rows, because it kept their rank. These two lines are the row statistics of the attention below; follow one to the Tile IR it wrote.

## api-keepdims-go

see it in the map ↓

## show-refused-title

Refused while recording

## show-refused

A kernel is checked when it is recorded: the body runs once, and an operation its shapes or roles cannot support is a panic that names the kernel, the operation's number and the operator as written. It comes before `tileiras` and before any device, and it names the operator, not a line of your source.

## show-host-title

Run on the host, with no GPU

## show-host

The fake device alone calls a host reference registered under the kernel's name. `with_gpu_interp` runs the recorded Tile IR instead, at the grid each launch names, so one host program goes from trace to numbers on a machine with no card. The numbers are the interpreter's, held to the host references in CI and not to a GPU.

## show-open

Run it in the Playground

## api-occupancy

On `sm_86`, a 128 by 128 f16 matrix product wants `entry_hints(occupancy = Some(2))`, which fits two blocks on each SM instead of one.

## api-surface

The package's whole surface

## api-changes

What changed in 0.9.0

## api-measured

How it was measured.

## kernel-title

One kernel, line by line

## kernel-body

A fused attention, the source of the row statistics above, beside the Tile IR its calls wrote. The pairing comes from the recording and from Dawn's own parser, never from a hand-written table; the colour on a call's name and on the lines it wrote is the same. In the Playground the same function can also be read beside the C and the JVM bytecode it compiles to. The shared `[D, A]` body is recorded here as Float/Float: natural exponentials and exact f64 division. Its BF16/F32 instance keeps base-2 exponentials with FTZ, bf16 probability rounding, and approximate f32 division. Three-dimensional cells place heads on grid axis 2 and project singleton tile axes into matrix values. The algorithm queries tile_shape and blocks_of; its factory captures only the dtype witness and numeric policy. Architecture choices and entry hints stay in the host plan; measurement records stay in the audit ledger. The f64 recording uses one 32×16 plan with no entry hints.

## kernel-open

Open in Playground

## kernel-kind

one loop, two reductions inside it

## kernel-left

Dawn source

## kernel-right

the Tile IR it recorded

## kernel-note

Click a call's name to mark its span and the Tile IR it wrote. Click a line of Tile IR to find its call. Escape lets go.


## word-line

line

## word-lines

lines

## word-none

no lines of its own

## fact-calls

calls

## fact-ops

operations

## fact-lines

lines of Tile IR

## fact-bytes

bytes

## fact-rows

cited by {n} coverage rows

## fact-mutants

{n} mutants

## coverage-title

What the backend covers

## coverage-body

Every public opcode, type tag and attribute value of the Tile IR release has a row, a status and its evidence. Point at a card to see the rows that are not implemented.

## fig-opcodes

public opcodes implemented

## fig-types

type tags implemented

## fig-attrs

attribute values implemented

## fig-golden

golden kernels, each pinned as text and as bytecode

## gates-title

Three gates

## gates-body

Each layer catches what the one before it cannot, and each has to turn its own mutants red. Each dot is one of them, at the gate it was written against.

## gates-caught

mutants caught here

## gate-0-title

Text and bytes

## gate-0-body

Every golden kernel is traced twice and held to its recorded text and bytecode, byte for byte. It says whether anything changed, not whether it is right.

## gate-1-title

The assembler accepts

## gate-1-body

`tileiras` has to assemble every bytecode golden into a cubin that names its kernel. It catches encoding and type errors, not wrong answers.

## gate-2-title

The device agrees

## gate-2-body

On a GPU, every output buffer is held to a host reference, bit for bit or within a stated tolerance. Each run appends a ledger line, and CI refuses a tree the last line did not test.

## ledger-title

On real hardware

## ledger-body

The last line of each machine's ledger. CI reads the first; the sm_90 and sm_100 ledgers reach the fp8, fp4 and block-scaled rows an Ampere card cannot load.

## ledger-tiers

Kernels compared, by tier, summed over the line's families.

## th-gpu

GPU

## th-date

date

## th-driver

driver

## th-tileiras

tileiras

## th-result

result

## th-exact

bit for bit

## th-tolerance

within tolerance

## th-tree

tree

## chip-golden

golden kernels

## chip-gpus

GPUs on record


## perf-title

Flash attention timings

## perf-body

Historical P4-c measurements of the old flattened layout, before the A2 output migration and S2 three-axis layout. These timings do not measure S2, which reuses the launch plans. The current bf16 kernel stores f32; the timings below measured f64 output and have not been relabelled as f32 measurements. Offline configurations selected by `(arch, d)`, measured with CUDA events in one process and stream over five interleaved rounds. Times are median / p90 in milliseconds. The baseline is 64×64 with no entry hints; bf16 uses f32 accumulation and f64 output, and f64 uses 32×16 after tuning. cuTile uses its upstream bf16 attention sample with the fastest of four measured configurations; SDPA uses the row's bf16 or f64 format. cuTile outputs bf16; Dawn outputs f64. The f64 rows have no equivalent cuTile sample. The [configuration ledger](https://github.com/dawnop/dawn-lang/blob/main/scripts/flash-config/ledger.json) retains the selection evidence, including the unselected sm_100 d64 single head candidate. Configurations are fixed before recording; there is no runtime search.

## perf-format

Format

## perf-workload

Workload

## perf-tools

Tileiras / optimization

## perf-config

Configuration

## perf-before

Before

## perf-after

After

## perf-cutile

cuTile 1.7.0

## perf-sdpa

torch SDPA
