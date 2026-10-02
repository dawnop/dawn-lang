# cuTile backend page copy, English, the original

Everything `gpu.html` says in words, in the order it says it. The generator
reads these sections by name (`site/src/gen/gpu.dawn`), the way the front
page reads `home.md`, so a section that is missing or renamed fails the build
instead of rendering an empty page. A Chinese translation, when there is one,
is `gpu.zh.md` with the same keys and a digest of this file.

What is not here, on purpose: every number. The coverage counts, the golden
kernel count and the device ledgers are read from `scripts/tileir-features/`,
`scripts/tile-golden/` and `scripts/tile-gpu-diff/` when the site is built, so
none of them can go stale in this file. Words that are code (`!Dev`,
`tileiras`, file names, the ledger's statuses) live in the generator.

## title

Dawn's cuTile backend

## lede

A GPU kernel in Dawn is an ordinary function under the `!Dev` effect. Running it records the operations it raises; the record becomes CUDA Tile IR, and NVIDIA's `tileiras` assembles that into a cubin. Every figure on this page is read from a table in the repository when the site is built.

## layers-title

Two layers, two effects

## layers-body

The program that owns the buffers and the kernel that computes over them are written against different libraries, each with an effect of its own. They meet in one place: the host launches a kernel by its name.

## layer-host

the host

## layer-host-body

`std/gpu` declares the `Gpu` effect: allocate, upload, launch, download. `with_gpu_real` answers it from the CUDA driver, on the native backend only. `with_gpu_fake` answers it from host memory with a reference function per kernel, so a `!Gpu` program runs, and is tested, on a machine with no GPU.

## layer-device

the device

## layer-device-body

`packages/tileir` declares the `Dev` effect. A recording handler turns one run of a kernel into a Tile IR program, which is printed as text or encoded as bytecode; `tileiras` assembles the bytecode for one GPU architecture.

## kernel-title

One kernel, both sides

## kernel-body

On the left, `vadd` as `scripts/tile-golden/kernels.dawn` defines it. On the right, the golden its trace is held to: the Tile IR the recording handler writes for it, character for character. The block index and the lane offsets, the two loads and the store in token order, and the add between them are each a line or two of the right-hand side.

## kernel-left

Dawn source

## kernel-right

golden Tile IR

## coverage-title

What the backend covers

## coverage-body

Three tables carry a row for every public opcode, every type tag and every attribute value of the Tile IR release this backend targets, with the status of each and the evidence for it. A gate holds each table to the bytecode writer in both directions: a row cannot claim an operation the writer does not emit, and an operation the writer gains without a row is red.

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

Each layer catches what the one below it cannot. Each also comes with mutants of the writer or the handler that it has to turn red, run beside it: a layer that stays green under its own mutants would be green for the same reason a broken one is.

## gate-0-title

Text and bytes

## gate-0-body

Every golden kernel is traced twice, rendered as Tile IR text and encoded as bytecode, and both are compared with the recorded files byte for byte. This layer says whether the recording handler, the renderer or the writer changed. It cannot say whether what they write is right.

## gate-1-title

The assembler accepts

## gate-1-body

Every bytecode golden goes through `tileiras` on each push that touches the tile paths. The verdict is an exit status of zero with no error line on standard error, and a cubin whose symbol table holds the kernel. This layer catches encoding errors, type errors and unsupported operations, but not a wrong answer.

## gate-2-title

The device agrees

## gate-2-body

On a machine with a GPU, the kernels are launched and every output buffer is compared with a host reference: bit for bit for kernels whose operations are exact, within a stated tolerance for those that use the device's approximations. Each run appends one line to that machine's ledger, and CI refuses a tree whose tile inputs differ from the ones the last line of its ledger tested.

## ledger-title

On real hardware

## ledger-body

The last line of each machine's ledger, as the run recorded it. The first is the repository's own machine and the one CI reads. The other two are cluster machines; what they buy is the fp8, fp4 and block-scaled rows an Ampere card cannot load.

## ledger-tiers

The two counts are kernels compared, by tier, summed over the families in the line's note.

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

## crumb

cuTile backend

## chip-golden

golden kernels

## chip-gpus

GPUs on record
