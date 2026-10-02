# cuTile backend page copy, English, the original

Everything `gpu.html` says in words, in the order it says it. The generator
reads these sections by name (`site/src/gen/gpu.dawn`), the way the front
page reads `home.md`, so a section that is missing or renamed fails the build
instead of rendering an empty page. The Chinese translation is `gpu.zh.md`,
with the same keys and a digest of this file.

Every section says one or two sentences; the figures, the line map and the
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

## kernel-title

One kernel, line by line

## kernel-body

Each Dawn line sits beside the Tile IR it recorded, paired call by call by the recording itself. Point at a line to light up its share, or replay the recording.

## kernel-left

Dawn source

## kernel-right

the Tile IR it recorded

## kernel-pick

Kernel

## kernel-mapped

{n} of {total} golden kernels map line by line

## kernel-replay

Replay the recording

## kernel-ops

ops recorded

## fact-calls

Dawn calls

## fact-ops

operations recorded

## fact-lines

lines of Tile IR

## fact-bytes

bytes of bytecode

## fact-rows

rows of the coverage tables cite it

## fact-mutants

mutants are run against it

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

Each layer catches what the one before it cannot, and each has to turn its own mutants red. Every dot below is one of them, at the layer it was written against.

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

The last line of each machine's ledger. CI reads the first; the cluster's two reach the fp8, fp4 and block-scaled rows an Ampere card cannot load.

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
