# tileir changelog

## 0.28.0

- Replace integer cell axes with the shared std/gpu CellAxis ADT. Grouped
  supports complete read-only groups, including group three.
- Add ReadView and read_prefix/read_at/read_blocks for effective prefixes
  with unchanged capacity strides and explicit algorithm score masks.
- Preserve all inherited Tile IR text and bytecode; no new opcode or ABI.


Newest first. A 0.x minor is its own compatibility class
(`docs/package-design.md` §6.3), and a new `Dev` operation moves the minor:
a handler written outside the package does not compile until it answers it.
Section numbers refer to
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) (in
Chinese).

## 0.27.1 (2026-10-24)

- Add `trace6` and the typed `Entry6` launch family, preserving the existing
  role, cell, hint, caller and flat parameter contracts. This is an additive
  API change within the 0.27 compatibility class, with no Dev or bytecode change.

## 0.27.0

- 新增 `cells(..., squeeze = [])` 与 `Grid` 的第五个字段。投影只从值中删除
  长度为 1 的 tile 轴，storage 几何、grid、边界与所有权保持完整。轴列表按集合
  解释，重复轴拒绝；支持 scalar store、rank-0，`store_sub` 逆投影插入单例
  storage 轴与零 piece 下标。
- 新增类型化记录期查询 `tile_shape(Tile[D])`，保留零指令来源调用；新增内部
  `Dev.t_cell_shape`。外部 handler 必须处理该查询；无新 opcode 或字节码版本变更。

## 0.26.0 (2026-10-23)

- Remove `prog.check_config` without a compatibility wrapper. Measured tileiras row tile performance filters belong to the application recording policy; generic hint range, dtype and shape validation remains in tileir.

## 0.25.1 (2026-10-23)

- Complete the staged if acceptance audit, including value condition refusals, source locations and staged while boundaries. This documentation and test closure keeps 0.25.1: it adds no API, Dev operation or encoding change.

- Support conditional loads, stores, atomics and staged loops in Unit and Tile value branches.
- Merge memory order through an if token result, preserving pure branch bytes and the read-only In fast path.
- Track region token results explicitly through trials and conservatively include both arms in fork conflict checks.
- Validate complete if yield types during lowering and cover uploaded true and false predicates with six new kernels.

## 0.25.0 (2026-10-22)

- Add Bool-only TileCondDtype qualification and StagedCond for pure rank-0 device conditions, sharing the recorder with d_if.
- Add StagedResult for Tile values with separate uninitialized slots. Both arms must assign matching dtype and shape; each result becomes an if yield without broadcasting or promotion.
- Preserve carry creation order, shared staged for cells and the entry value in an unwritten arm. Migrate foldif and carry_extent with byte-identical MLIR and tilebc, including foldif_debug metadata.
- Add seven Dev result-slot operations. External handlers must implement them; no compatibility handler is supplied. Token branches remain rejected with an explicit S3 diagnostic.

## 0.24.0 (2026-10-22)

- Add conditional `<<`, `>>`, `>>>` implementations for `Tile[D]` with `D: TileShiftDtype`, same-type Tile Amounts and ground `!Dev` effects.
- Mask every lane's count with `width - 1` before device shifts, including negative counts. Left shifts wrap, `>>` is arithmetic, and `>>>` is logical.
- Remove `shl_i`, `shr_i`, `shr_u`, `shli` and `shri` without compatibility wrappers. Operators use the user recording boundary location.
- Align tileinterp and tileref with masked counts and cover all four integer widths with boundary kernels.

## 0.23.0 (2026-10-22)

- Add `TileBitsDtype` for Bool, I8, I16, I32 and Int and `TileShiftDtype` for the four signed integer formats, each with a pure dtype witness.
- Add conditional `& | ^ ~` tile implementations with `!Dev`. Integer operations record `andi`, `ori`, `xori`; mask `& |` preserve the existing select kernels. Complement records xor with all ones, or 1 for i1.
- Remove `and_i`, `or_i`, `xor_i`, `and_mask` and `or_mask`. Replace calls with operators; no compatibility wrappers remain. Operators have no `at` parameter and use the recording boundary's user location, as arithmetic does.
- Keep named shifts and their current count semantics for the next migration.

## 0.22.0

- Add `prog.check_config(arch, bq, hints, at:)` to reject measured row-tile performance cliffs before recording.
- Add `div(..., approx: true)` for approximate f32 division, including `ftz: true`.
- Preserve the buffer base alignment before a `tensor_view` element offset so aligned views can use TMA.

## 0.21.0 (2026-10-21)

Breaking, in one place (`docs/tile-backend-design.md` section 6.41, "caller
position", tileir M5): a refusal now ends in the line of your own source that
wrote the call, not in a line of this package. Every public function of
`tileir/dev` gained a last parameter `at: Loc = caller()` (spec 8.4), the
recording keeps the one of each call the kernel wrote, and the panic is raised
with it. The 209 goldens are unchanged byte for byte: a `TileProg` keeps no
position, the side table `trace_calls` answers does.

Public surface:

- About 190 functions of `tileir/dev` take `at: Loc = caller()` as their last
  parameter. A call is unchanged; a caller that stored one of them as a
  first-class function value needs a `Loc` argument. `d_loop` takes it FIRST
  (`d_loop(at, body)`) so that `d_loop { .. }` still hands the block to `body`.
  `store_sub`'s `at: List[Int]` (the piece number) is renamed `piece`.
- `Dev.t_call_enter(name: String)` is now `t_call_enter(name: String, at:
  Option[Loc])`. A handler written outside the package must answer the new
  arity. `at` is `None` for what a kernel writes without a call: `+ - * /`, a
  `var`, a bare float literal, because a trait method takes no `caller()`
  default.
- `Call` gains `at: Option[Loc]`, `DRange` gains `at: Loc` (`for` is a trait
  method, so the range is where the loop's position is still known), and
  `trace_kernel`, `trace_calls` and `trace1` to `trace5` take a last `at: Loc =
  caller()`, the position a refusal falls back to when no call of the kernel
  has one.

What a refusal says (all after the reason, so the goldens' mutants, which
match the text up to the reason, still match):

- It ends in `at <file>:<line>:<col>` of the nearest call the kernel wrote.
- An operand it names says where it was made: `(rhs comes from `mma` at
  src/main.dawn:27:24)`, or `(rhs comes from the `+` operator)`.
- A region it is inside names the call that opened it: `(inside the body of a
  `d_range` at src/main.dawn:26:12)`.

Not done, on purpose: an operator has no line of its own (that needs trait
methods to take `caller()`, which was not done: one consumer, 82 impls to
migrate), and refusals raised while lowering or encoding a finished `TileProg`
still name only `op #k`.

## 0.19.0 (2026-10-21)

Breaking, in one place (`docs/tile-backend-design.md` section 6.39, "hints on
view reads and writes"): the four `hint_*` constructors and the untyped
`Hints` argument are gone, and every `hints:` parameter now takes a typed
record per architecture. `Dev` gained no operation, but `t_load_view` and
`t_store_view` take the operation's hints as a last argument, so a handler
written outside the package must answer the new arity. The 208 goldens are
unchanged byte for byte against 0.18.1; `hint_view` is the 209th.

- View reads and writes take `hints:`: `load_view`, `store_view`,
  `load_cell`, `load_at`, `store_cell`, `store_sub`, `load_gather` and
  `store_gather`, as `view_hints(allow_tma: .., latency: ..)` per
  architecture. They lower to `optimization_hints` on `load_view_tko` and
  `store_view_tko`, between the memory ordering and the `inbounds` array, with
  bit 1 of the flags. `allow_tma` is the dialect's one boolean and is written
  as an `i1` integer.
- Hints are three records by what carries them: `entry_hints(num_cta_in_cga:
  .., num_worker_warps_per_cta: .., occupancy: ..)` for the entry (the
  `hints:` of `trace_kernel` and `trace1` to `trace5`), `ptr_hints(latency:
  ..)` for a pointer `load` and `store`, `view_hints(..)` as above. A pointer
  access has no `allow_tma` and an entry has no `latency`: the type has no
  field for it. `for_arch(arch, record)` is generic over them, and
  `ByArch[H]` is the list a `hints:` takes.
- A value outside the dialect's range is refused when the kernel is recorded,
  in English, naming the key, the value, the architecture and the range
  (`tileiras` checks none of it unless `-Wunsupported-hints` is on, which it
  is not): `latency` 1 to 10, `occupancy` 1 to 32, `num_worker_warps_per_cta`
  4 or 8, `num_cta_in_cga` a power of two to 16 and exactly 1 on sm_80 to
  sm_89; an architecture that is not `default` or `sm_` and a number, or one
  given twice, is refused too. An architecture with no key set is not written.
- `hint_num_cta_in_cga`, `hint_num_worker_warps_per_cta`, `hint_occupancy` and
  `hint_latency` are removed (migrate to the records above). The comment that
  said `num_worker_warps_per_cta` takes powers of two up to 32 was wrong: the
  dialect's range is 4 to 8.

## 0.20.0 (2026-10-21)

`dev.exp2` takes `ftz: Bool = false`, the dialect's `flush_to_zero` unit
attribute (section 6.40, tileir P3): a subnormal input and a subnormal result
become the zero of their sign, and the device answers with the bare
`ex2.approx.ftz` instruction. f32 only; the assembler refuses it on other
widths, as it does for `add` and `mul`. Calls that do not pass `ftz` record
and assemble as before, byte for byte, but the function's type gained a
parameter, so a caller that stored `exp2` as a first-class function value
needs a wrapper. The recording handler accepts the new operation name
`exp2_ftz` (the same opcode, flags word 1). `scripts/tile-golden` gains
`attr_exp2`, and `flash_attn_bf16` now writes `exp2(.., ftz: true)` with
`log2(e)` folded into its launch scale; its golden changes, nothing else
does.

## 0.18.1 (2026-10-20)

No API change; the recorded program changes (section 6.38, tileir P2). A load
through a parameter the kernel declared `In` reads the entry token and leaves
the token chain where it was, and a loop that moved no token no longer carries
one. `Shared` reads and writes, `Out` writes, and everything recorded by
`trace_kernel` (which knows no roles) keep the chain they had. 192 goldens
change; the flash_attn kernels lose the token their loop carried, which is
what let tileiras prefetch across iterations.

## 0.18.0 (2026-10-20)

Breaking, in one place (`docs/tile-backend-design.md` section 6.28, "the
program is a third key"): `asm.tileiras_args` and `asm.assembler_defect` take
the recorded program as a third argument, so a caller outside the package must
pass it (`assemble` and `scripts/tile-gpu-diff` already do). No `Dev`
operation was added and the 205 goldens are unchanged byte for byte.

- `tileiras_args(version, gpu_name, prog)` gives `--opt-level 0` for
  tileiras 13.4.92 on sm_90, sm_100, sm_103, sm_107 and sm_110 only when
  `prog` has a `loop` that `break`s (#558); every other program keeps the
  default `-O3`, as does every other target and version. Before this, every
  program on those targets was assembled at `-O0`, which made the flash_attn
  goldens 35x (bf16, sm_90) to 57x (bf16, sm_100) slower than their `-O3`
  cubins and vadd 3x, for a defect none of them can trigger.
- New `asm.has_break_loop(prog) -> Bool`: a `Loop` operation with a `Break`
  anywhere in its body, at any nesting depth. It is wider than the four
  conditions #558 minimised on purpose: which break loops the optimizer
  breaks is its business, and a `for` never counts.
- `assembler_defect(version, gpu_name, prog)` words the reason for the
  program it is asked about.
- The ledger line's `asm=` field now says what every kernel got, and a new
  `o0=` field lists the kernels that were assembled at `--opt-level 0`.

## 0.17.1 (2026-10-20)

Additive, so a patch in the 0.17 class (`docs/package-design.md` section 6.3,
"0.x and compatibility classes"): nothing a caller or a handler already
compiles against moved, and no `Dev` operation was added. The 205 goldens and
the three ledgers are unchanged byte for byte.

- `asm.assemble(prog, gpu_name, tileiras) -> Result[Bytes, AssembleError]`
  with `!Fs !Proc`: encodes the program, writes a temporary `.tilebc`, asks
  `tileiras --version` which assembler it is, runs it with
  `tileiras_args(version, gpu_name)` and reads the cubin back, removing the
  scratch directory whatever happens. `tileiras` is a path (or a name on
  PATH): installing the assembler is not this package's business. The four
  ways it can fail are four `AssembleError` constructors
  (`AssemblerNotFound`, `AssemblerFailed` with the arguments and stderr,
  `NoCubin`, `UnknownVersion`) plus `Scratch` for the host refusing a
  temporary file, and `asm.explain` words each as one sentence. No cache: an
  assembly is well under a second and a cache would have to be keyed on the
  assembler version, the target and the arguments as well as the bytes.
  `assemble` takes `!Fs` as well as `!Proc`, because
  it writes and reads files through `Fs`; a test answers both.
- A recording refusal names the four float operators the way the kernel
  wrote them (`+`, `-`, `*`, `/`, not `addf`, `subf`, `mulf`, `divf`) and,
  when the refused operation is inside a region, says which regions after the
  reason: ``(inside the body of a `d_range`, inside the then branch of a
  `d_if`)``. The text before the reason is unchanged except for the operator
  spelling, so a fragment match on `kernel`, `op #k` and the reason still
  holds. There is still no source line: nothing reads a Dawn position at
  record time before the `at` default reaches this package.

## Unreleased: no code change, a new reader of `lower`

`packages/tileinterp` 0.1.0 (`docs/tileinterp-design.md`) interprets the
lowered table, and the read-only interface it needs was already public:
`lower.lower(prog) -> Kernel` and the `Kernel`, `Instr`, `Ty`, `Elem` and
`Ref` types with every constructor, plus `dev`'s `RedId`, `AssumePred`,
`Padding` and `DYN_DIM`. Nothing was added or widened, so the version stays
0.17.0 and the layer-2 input digest does not move. What changes is the
contract around them: tileinterp matches `Instr` exhaustively, so a new
variant no longer compiles until the interpreter answers it (or refuses it
by name in `interp.unsupported_in`). A new opcode lands in three places from
now on: `lower`, `bytecode` and the interpreter.

## 0.17.0 (2026-10-11)

Breaking, in one place (`docs/tile-backend-design.md` section 6.36, knife
T14b). `TileProg` and the lowered `Kernel` gain a second field, `debug:
Option[DebugInfo]`, so a record literal written outside the package must name
it (`debug: None` keeps everything it did). No `Dev` operation was added and
the 205 existing `.mlir` and `.tilebc` goldens are unchanged on both backends.

- `encode` writes the bytecode's Debug section (id 3) when `debug` is
  `Some(d)`: a DIFile, a DICompileUnit, a DISubprogram, the function's own
  DILoc and one DILoc per instruction, and the function record's location
  index becomes 1. `DebugInfo` is `{ dir, file, line, col, locs }` with one
  `(line, col)` in `locs` per instruction of the lowered kernel, in the order
  the bytecode lists them. A list of any other length is refused with a panic
  that names both counts. The recording handler never sets `debug`, the text
  renderer does not print it, and the default `-O3` cubin is byte for byte the
  one without the section; with `tileiras --lineinfo` the locations reach the
  cubin's `.debug_line`.
- `render.text_debug(prog, dir, file)` builds a `DebugInfo` whose locations are
  the lines and columns of `prog`'s own `.mlir` text saved as `dir/file`.
  The recording handler had no Dawn source position to offer then (0.21.0
  gives it one, in `Call.at`, but a `TileProg` still keeps none), so a caller
  with a better source (a line from a call map) builds the record itself.
- `lower.instr_count(body)` is the number of instructions a body is, regions
  included.
- Two kernels (`vadd_debug`, `foldif_debug`), two layer 1 mutants
  (`debug-line-off-by-one`, `debug-count-short`), and `debug-check.py` in
  `scripts/tile-golden`, which reads the `tileirdisasm -g` table and the
  cubin's `.debug_line` against the golden's text.

## 0.16.0 (2026-10-11)

Breaking, in one place (`docs/tile-backend-design.md` section 6.35, knife
T14a). `TileProg` and the lowered `Kernel` gain a field, `producer:
Option[String]`, so a record literal written outside the package must name it
(`producer: None` keeps everything it did). No `Dev` operation was added and
the 205 existing `.mlir` and `.tilebc` goldens are unchanged on both backends.

- `encode` writes the bytecode's Producer section (id 7, 13.3 and later) when
  `producer` is `Some(s)`: the string joins the String section and the
  section's one varint is its index. The recording handler never sets it; a
  caller builds `TileProg { ..p, producer: Some(s) }`. The text renderer does
  not print it, and the device never sees it: `tileirdisasm` opens with
  `// Producer: <s>` and the cubin is byte for byte the one without the
  section.
- Asked for under a header older than 13.3, the writer refuses with a panic.
  The C++ writer drops the section without a word below 13.3; this one does
  not, because a caller who set a producer believed it was in the file.
- One kernel (`vadd_producer`) and two layer 1 mutants in `scripts/tile-golden`
  (`producer-index-off-by-one`, `producer-under-13-2-header`), and a
  `tileirdisasm` first-line check in `run.sh`.

## 0.15.1 (2026-10-11)

Additive (`docs/tile-backend-design.md` section 6.34, knife T20). The 203
existing `.mlir` and `.tilebc` goldens are unchanged on both backends, and no
`Dev` operation was added.

- `F8E5M3FNU` (`std/narrow`, bytecode 13.4's `f8E5M3FNU`, type tag 130) is a
  tile format: `float_to_float(x, F8E5M3FNU)` converts into and out of it
  under `nearest_even`, and it is a scale format of `mma_scaled` over
  `F4E2M1FN` operands. The writer puts a type tag down as a varint, which
  matters for the first time here: 130 is two bytes.
- It has no host value. `std/narrow` has no rounding function for it and
  `std/gpu` has no buffer of it, because what `ftof` does at the format's
  edges is a device behaviour and only sm_107 takes the type.
- `tileiras` 13.4.92 takes the type at `--gpu-name sm_107` and refuses it at
  every other architecture tried (sm_80 to sm_121). Two kernels in `scripts/tile-golden`
  (`dtype_e5m3`, `mmaf_scaled_e5m3`) are assembled for sm_107 and run on no
  device, and two layer 1 mutants.

## 0.15.0 (2026-10-11)

Breaking: the last three opcodes bytecode 13.4 added
(`docs/tile-backend-design.md` section 6.33, knife T19). The 202 existing
`.mlir` and `.tilebc` goldens are unchanged on both backends.

- `memory_fence_alias()` (`memory_fence_alias_tko`, 0x7A), `gdc_wait()`
  (`gdc_wait_tko`, 0x78) and `gdc_launch_dependents()`
  (`gdc_launch_dependents_tko`, 0x77) take the ordering token as it stands
  and answer the next, like `d_print`, and answer nothing. Each is refused
  inside a reduce, scan or `if` region, which carry no token.
- The two `gdc_*` are Programmatic Dependent Launch signals. They are no-ops
  below sm_90 and on any target when the kernel was not launched with the
  programmatic stream serialization attribute, which `std/gpu`'s launch does
  not set, so nothing here can observe them on a device yet.
- One new `Dev` effect operation, `t_token_only(op)`, so a handler written
  outside the package must answer it. The operation name is the dialect's own
  and any other is refused when the kernel is recorded.
- The `gdc_*` pair writes a flags word (bit 0, the optional `token` operand)
  and the token with no count. Reading the table generator suggested a count
  of one; `tileiras` 13.4.92 refuses that (`failed to get result type 0 for
  AddFOp`, the reader having lost its place).
- Text: `%t = memory_fence_alias_tko %tok` and
  `%t = gdc_wait_tko token = %tok -> token`, which `tileirdisasm` 13.4.92
  prints back for the bytes.
- One kernel in `scripts/tile-golden` (`token_fences`), one case in
  `scripts/tile-gpu-diff/shape_diff.dawn`, and three layer 1 mutants.

## 0.14.0 (2026-10-10)

Breaking: a view load and store can promise `inbounds`
(`docs/tile-backend-design.md` section 6.32, knife T18). All 199 existing
`.mlir` and `.tilebc` goldens are unchanged on both backends: a call that
promises nothing writes the all-false array it always wrote.

- `load_view(v, indices, inbounds: [..])` and
  `store_view(v, indices, t, inbounds: [..])` take the dialect's `inbounds`
  array, one `Bool` an index. `true` at a dimension promises that no tile the
  access touches is cut by the tensor's edge there, so the assembler may drop
  the bounds handling. `[]`, the default, promises nothing. Any other length
  than the index count is refused when the kernel is lowered.
- A load that promises anything over a view with a padding value is refused
  by name. `tileiras` 13.4.92 answers every such program with the unnamed
  `failed to compile Tile IR program`, for every padding value and whichever
  dimension is promised; a non-dividing shape over a view with no padding
  value assembles. (The 13.4 upgrade notes read the unnamed failures as
  caused by shapes the tile does not divide; the padding was the cause.) A
  store has no padding and takes the promise anywhere.
- The effect operations `t_load_view` and `t_store_view` gain a trailing
  `inbounds: List[Bool]`, so a handler written outside the package must
  answer the new arity. `load_cell`, `store_cell`, `store_sub`, `load_gather`
  and `store_gather` pass `[]`.
- The text rendering prints ` inbounds=[true, false]` after the token when an
  entry is true, and nothing when none is, as the dialect's printer does.
- Three kernels in `scripts/tile-golden` (`view_inbounds`,
  `view_inbounds_off`, `view_inbounds_dim`) and three cases in
  `scripts/tile-gpu-diff/view_diff.dawn`.

## 0.13.0 (2026-10-10)

Breaking: a float constant carries its format's own value
(`docs/dtype-unify-design.md` section 7, knife U4).
Every one of the 199 `.mlir` and `.tilebc` goldens is unchanged on both
backends: none of them holds a narrow constant its format cannot represent.

- `f_const(d, value)` and `full(shape, value)` take a `D` where they took a
  `Float`, and `f_const` is bounded by `FloatDtype` as `full` already was.
  A literal is typed by `FromFloat` and so rounded to the format where it is
  written (`f_const(BF16, 0.1)` is the bfloat16 0.10009765625), and a host
  `Float` is converted in plain sight (`f_const(BF16, bf16(x))`,
  `full([BQ, 1], f32(-INFINITY))`). `F64` constants are spelled as before.
- `FloatDtype` gains `host_float(v: D) -> Float`, the exact `Float` a value
  of the format is, which is how the recording (still a `Float`) receives it.
- What the measurement found (the design's open question): before this the
  recording kept the raw literal and the bytecode writer rounded it, so the
  bytes were already the format's value; the text rendering printed the raw
  literal. Now both agree. `lit` is unchanged: it has no format until an
  operation gives it one, so there is no `D` to round to at the call.

## 0.12.0 (2026-10-07)

Breaking: runtime scalar kernel parameters (`docs/tileir-k4-design.md`,
knives 1 and 2).
Every one of the 195 existing `.mlir` and `.tilebc` goldens is unchanged on
both backends.

- An entry parameter says how it is passed. `TileProg.params` and
  `Kernel.params` are `List[KParam]`, `KParam = ByPtr(dtype) | ByValue(dtype)`,
  where they were `List[String]` and every parameter a pointer. `trace_kernel`
  and `trace_calls` take the list: `["f64", "f64"]` is
  `[ByPtr("f64"), ByPtr("f64")]`. A `ByValue` parameter is a rank-0
  `tile<dtype>` in the entry signature, with no instruction and no value of
  its own: the entry parameter is the tile.
- `scalar(p)` reads a by-value parameter as a rank-0 tile. Arithmetic with it
  follows the rank-0 rule, so `load(x, ..) * scalar(s)` scales a tile by a
  value the launch picks, and `idx_of(scalar(n))` is a runtime extent.
  `scalar` is bounded by `std/gpu`'s new `ScalarDtype` (`I32`, `I64`, `F32`,
  `F64`), its own trait and not `HasDtype` because Dawn has no supertraits.
  An opaque type inherits only `Eq`, `Hash` and `Ord` from its target, so
  `scalar(param(F16, 0))` does not check. What a type cannot say is still
  refused when the kernel records: a `ByValue` of any format but `i32`,
  `i64`, `f32` and `f64`, whether named by a string or by a `Scalar(F16)`
  marker. A new `Dev`
  operation, `t_scalar`: a handler written outside the package must answer
  it. The recording also refuses `scalar` of a buffer or of another format,
  and refuses `load`, `store`, `gather`, `scatter`, atomics, pointers and
  views of a by-value parameter.
- Three kernels in `scripts/tile-golden` (`scalar_scale`, `scalar_len`,
  `scalar_wide`) assemble under `tileiras` 13.4.92 for sm_86 and read the
  right values on the RTX 3080, including the 64-bit formats and an `i32`
  whose argument word has garbage in its high half.
- `Scalar(F32)` is the fourth marker of `trace1` to `trace5`, beside `In`,
  `Out` and `Shared`: the parameter is a `ByValue`, has no cells, and the
  entry the recorder answers takes a scalar at that position
  (`std/gpu`'s `arg_scalar`). `launch_entryN` takes `Launch[A]` arguments,
  `buffer(t)` or `scalar(v)`, and holds each position to the kind the entry
  says (`gpu.bad_entry`). Needs the `std/gpu` of the same release: `launch`
  takes `List[LaunchArg]` (`erase(buffer(t))`, `erase(scalar(v))`) and the
  fake device's `WideRefFn` takes the launch's scalars as a third argument.
- Measured on the device: `scripts/tile-gpu-diff/scalar_diff.dawn` runs the
  four scalar kernels (`scalar_scale`, `scalar_len`, `scalar_loop`,
  `scalar_wide`) bit for bit against the fake device, each cubin on several
  values, with the upper half of the argument word garbage in three cases
  (the device does not read it). A scalar parameter costs about 0.4
  microseconds per launch more than a baked constant and about 0.35 less
  than a one-element buffer on sm_100, and the two compile alike
  (`docs/tileir-k4-design.md` 1.2). `ScalarArg` is the one new operation;
  no opcode, so `scripts/tileir-features` is unchanged.

## 0.11.0 (2026-10-07)

Breaking: a kernel's loops, carried values, arithmetic and formats are
written the way the language writes them, and the format markers are gone.
Needs a compiler whose std has `std/float`, `std/dtype` and the witnesses in
`std/narrow` and `std/int/*` (the release after 0.85.0). Every kernel in
`scripts/tile-golden` records the bytes it did: the 195 `.mlir` and `.tilebc`
goldens are unchanged on both backends.

- A loop is `for j in d_range(lower, upper) { .. }`. `d_range` takes `Int`
  bounds (fixed when the kernel is recorded) or `Idx` bounds (computed on the
  device), `step: One` by default or `By(n)` (`By(nprog)` for a grid-stride
  loop), and `unsigned_cmp`. It replaces both the closure form of `d_range`
  and `d_for`, which is deleted. The body of a `for` carries the `var`s it
  assigns: `var acc = zeros(c)` and `acc = mma(.., acc)` are `carry`, `get`
  and `set`, which stay public for `d_loop`.
- `+ - * /` and unary `-` work on tiles and on `Idx`, a float literal on a
  tile is `lit`, an integer literal on an `Idx` is `idx_const`. Over a float
  tile they record the float operations, over an integer tile the integer
  ones (`addi`, `subi`, `muli`, `divi`, `negi`).
- A float operation (`add`, `neg`, `exp`, ...) over an integer tile is now
  refused when the kernel is recorded. Before, `add` over a `Tile[I32]`
  recorded an `addf` over an i32 tile and nothing refused it (#591).
- A format is a value type with a witness of the same name. `Tile[F64]`,
  `Param[F64]`, `Tensor[F64]` are `Tile[Float]`, `Param[Float]`,
  `Tensor[Float]`; `I64` is `Int` and `I1` is `Bool` in type position. The
  witnesses `F64`, `I64`, `I1` come from `std/dtype`, `BF16`, `F16`, `F32`,
  `TF32`, `F8E4M3FN`, `F8E5M2`, `F8E8M0FNU`, `F4E2M1FN` from `std/narrow`,
  `I8`, `I16`, `I32`, `U8` from `std/int/*`, and `I4` from `std/gpu`. Calls
  that name a format (`param(F64, 0)`, `In(BF16, ..)`, `f_const(F32, 0.5)`,
  `p.to(BF16)`) are spelled as before; only the `use` lines change.
  `std/narrow`'s `FP16` is `F16` (`f16`, `round_f16`, `f16_bits`,
  `f16_of_bits`). The `param`/`f_const`/`to`/`unpack_bytes`/`d_global`
  family takes a `Dtype[T]` instead of a marker with a `Dtype` bound.
- `FloatDtype::float_dtype` answers a `Dtype[D]`, and `float_name` is gone:
  write `dtype_name(float_dtype())`. `I1` is no longer declared here.
- `-INFINITY` and `INFINITY` come from `std/float`; the kernels' and the
  reference's private negative infinity are gone.

## 0.10.0 (2026-10-06)

Breaking: the float matrix product is `mma` and takes an accumulator of
another format, and `Dev`'s `t_mmaf` gains that format: a handler written
outside the package must answer `t_mmaf(dtype, acc, m, k, n, a, b, c)`.
Every kernel in `scripts/tile-golden` records the bytes it did; the new
`flash_attn_bf16` is the one new golden. §6.31.

- `mma[A, C](a: Tile[A], b: Tile[A], acc: Tile[C]) -> Tile[C]` replaces
  `mmaf`. The operands share a format and the accumulator may have another,
  as the dialect's table allows: f8E4M3FN, f8E5M2 and f16 operands into an
  f16 or f32 accumulator, bf16, tf32 and f32 into f32, f64 into f64. The
  recording refuses any other pair and lists these. bf16 operands with an
  f32 accumulator assemble for sm_86's tensor cores.
- `mmaf_scaled` is `mma_scaled`. `mmai` keeps its name: its formats are
  fixed and its tier is exact, as `addi` keeps its `i` beside `add`.
- `full(shape, value)`: a float tile of `shape` in the format it is checked
  against, `let m: Tile[F32] = full([32, 1], 0.0)`. It records what
  `broadcast(f_const(F32, 0.0), [32, 1])` does.
- `t.to(fmt)`: `float_to_float` at nearest even, answering `t` unchanged
  and recording nothing when it is already in `fmt`.
- `t.transpose()`: `permute_tile(t, [1, 0])` for a rank-2 tile.
- New trait `FloatDtype[D]` (`float_dtype()`, `float_name(d)`) for the
  seven arithmetic float formats: how `full` and `mma` learn a format from
  the type alone. A kernel generic in its format bounds it with
  `[D: FloatDtype]` to call either with a `Tile[D]` in hand.
- `prog.MmaF` carries the accumulator's format as `out`, and
  `prog.mma_accumulators(dtype)` answers the table.

| 0.9 | 0.10 |
|---|---|
| `mmaf(a, b, c)` | `mma(a, b, c)` |
| `mmaf_scaled(a, b, c, sa, sb)` | `mma_scaled(a, b, c, sa, sb)` |
| `carry(broadcast(f_const(F64, 0.0), [32, 1]))` | `let c: Carry[F64] = carry(full([32, 1], 0.0))` |
| `float_to_float(p, BF16)` | `p.to(BF16)` |
| `permute_tile(t, [1, 0])` | `t.transpose()` |

A module that defines its own `transpose`, `full` or `to` and imports the
whole of these from `tileir/dev` now has a clash; `scripts/tile-golden`'s
`transpose` kernel function is `transpose_matrix` for that reason.

## 0.9.0 (2026-10-06)

Breaking: loops and `if`s carry device variables instead of tuples, and the
float arithmetic has one naming scheme. `Dev` gains `t_carry_new`,
`t_carry_get`, `t_carry_set`, `t_trial_begin`, `t_trial_end` and
`t_extent_of`; a handler written outside the package must answer them.
Every kernel in `scripts/tile-golden` records the bytes it did, except
three: in `flash_attn` and `loop_bound` one carried value's starting tile is
now recorded before the loop's bounds rather than after them, and
`grid_stride`'s loop no longer carries the constant it handed back unchanged
(0.8's `d_range` had to carry one tile). §6.30.

- `carry(init)` makes a `Carry[D]`, a device variable; `c.get()` reads it
  and `c.set(t)` replaces it, at the same format and shape. `d_range`,
  `d_for`, `d_loop` and `d_if` take bodies that answer `Unit` (`d_loop`'s
  answers its stop mask) and carry the carries their bodies set, in the
  order they were made. The recording finds them by running the body once
  as a trial and discarding what the trial recorded, so a region nested `n`
  deep records its innermost body 2^n times.
- `d_range(lower, upper, step: 1) { j => .. }` and
  `d_for(lower, upper, step, unsigned_cmp: false) { j => .. }`: the body is
  the last parameter, so it is written as a tail block.
- `d_for2`, `d_for3`, `d_for4`, `d_loop2` and the value-answering `d_if` are
  gone.
- Float `addf`, `maxf` and `minf` are `add`, `max` and `min`, beside `sub`,
  `mul`, `div`, `neg` and `abs`. The integer families (`add_i`, `addi`, ...)
  are unchanged. A module that imports `max` or `min` from `tileir/dev`
  shadows the prelude's for host `Int`s too; `list.max` is unaffected.
- `extent_of(p, dim)` and `blocks_of(p, dim)`: the extent of a parameter's
  tensor along `dim` and its number of cells there, as an `Idx`: a constant
  for a static dimension, the grid's blocks along the axis it follows for a
  `DYN_DIM` one.
- New module `asm` (#558): `tileiras_args(version, gpu_name)` answers the
  arguments to assemble with, and `assembler_defect(version, gpu_name)`
  explains them. tileiras 13.4.92 miscompiles a loop exit value on sm_90,
  sm_100, sm_103, sm_107 and sm_110 at `--opt-level` 1 and above
  ([NVIDIA/cuda-tile#25](https://github.com/NVIDIA/cuda-tile/issues/25)), so
  for those targets the answer includes `--opt-level 0`. The table is keyed
  on the exact tileiras version, so a fixed release gets the plain
  arguments. It changes neither `Dev` nor the bytes `encode` writes. §6.28.

| 0.8 | 0.9 |
|---|---|
| `let acc = d_range(0, n, zeros(c), (k, s) => mmaf(a, b, s))` | `let acc = carry(zeros(c))` then `d_range(0, n) { k => acc.set(mmaf(a, b, acc.get())) }` |
| `let (x, y) = d_for2(lo, hi, st, x0, y0, (k, x, y) => (f(x), g(y)))` | `let x = carry(x0)`, `let y = carry(y0)`, then `d_for(lo, hi, st) { k => .. }` whose body sets `x` to `f(x.get())` and `y` to `g(y.get())` |
| `d_loop(v0, v => (done(v), next(v)))` | `let v = carry(v0)` then `d_loop { .. }` whose body computes `done(v.get())`, sets `v` to `next(v.get())` and answers the mask |
| `let r = d_if(c, () => a, () => b)` | `let r = carry(a)` then `d_if(c, () => (), () => r.set(b))` |
| `d_for(.., init, body, unsigned_cmp: true)` | `d_for(.., unsigned_cmp: true) { k => .. }` |
| `addf(a, b)`, `maxf(a, b)`, `minf(a, b)` | `add(a, b)`, `max(a, b)`, `min(a, b)` |

## 0.8.2 (2026-10-06)

Additions only: `Dev` is unchanged, and every program that recorded before
records the same bytes. §6.29.

- `idx_div`, `idx_rem` and `idx_sub`: the quotient (signed, toward zero),
  the remainder and the difference of two `Idx`. They issue the `divi`,
  `remi` and `subi` that `div_i`, `rem_i` and `sub_i` already did, on the
  rank-0 i32 tile an `Idx` is. A grid axis that holds two indices folded
  together (`head * G + group`) is read back out with them.
- Same-rank broadcasting: an operand of an element-wise operation whose
  shape differs from the operation's only in dimensions of length 1 is
  broadcast to it, so `sub(s, reduce_max(s, keepdims: true))` needs no
  `broadcast`. A difference in rank is still refused (rank 0 aside): a
  reduction that dropped the dimension does not line up by trailing
  dimensions. The broadcast is recorded where an explicit `broadcast` in the
  last argument would have been.
- `lit(v)`: a float constant with no format, which takes the format and the
  shape of the element-wise operation it meets: `mul(s, lit(0.5))`. Write it
  after a typed operand (the checker finds `D` from left to right) or under
  an annotation. A place that needs a format of its own (a `broadcast`, a
  reduction, a store, an integer operation) refuses it by name and says to
  write `f_const`.

## 0.8.1 (2026-10-05)

`reshape(t, shape)` regroups a tile's lanes into another shape of as many,
in row-major order, as Tile IR's `reshape` does; the recording refuses a
shape that holds another number of lanes or has a dimension that is not a
power of two. It wraps the `t_reshape` that `keepdims` already issued, so
`Dev` is unchanged and a handler written outside the package compiles as
before. Adds a name only.

An `Out` takes the `along` an `In` already did: dimension `j` follows grid
axis `along[j]`, any injection into the three axes, no `FREE_AXIS`, and an
axis no dimension follows has one block. Before, any `along` but the
identity was refused. Every program that recorded before records the same
bytes. §6.27.

## 0.8.0 (2026-10-05)

Breaking: the one-time migration of the batch's PR-3 (§6.26). A kernel no
longer states a shape or a format it can read off its operands, `Scalar[D]`
is `Tile[D]` at rank 0, and an `Out` is written only through its cells.

- Element-wise operations, comparisons, conversions, selects, `mmaf` /
  `mmai` / `mmaf_scaled`, `extract`, `insert`, `cat`, `permute_tile`, the
  pointer ladder, the views and the debugging operations drop their leading
  format and shape arguments (C3). A conversion takes the tile first and the
  target format second.
- `Scalar[D]` is gone: a rank-0 `Tile[D]` is what a constant, a reduction of
  a rank-1 tile and an index read as a tile are. A rank-0 operand widens on
  its own where it meets a wider one; no other widening is implicit
  (`broadcast`). A place that needs rank 0 (a condition, a loop bound, a
  cell index, `d_return_if`) refuses a wider tile (C3′).
- Constants take no shape: `f_const(d, v)`, `i_const(v)` and the rest record
  nothing until they are used, and are materialised at the shape of the use.
- `store_cell(o, t)` and `store_sub(o, at, t)` are the only writes an `Out`
  takes; a `store`, `scatter`, atomic, `store_ptrs` or `store_view` into one
  is refused while recording, and so is a write through untraceable
  pointers in a kernel that has an `In` or an `Out` (D-7). `zeros(p)` and
  `fill(p, v)` make a cell-shaped tile.
- `d_range(lower, upper, init, body)` is `d_for` over host bounds; a loop's
  carried value and an `if`'s two answers must keep their format and shape.
  `retile(p, extent, tile)` is a second, read-only view of a parameter (C4).
- `Dev` gains `t_sub_view` and `t_retile`.

| 0.7.0 | 0.8.0 |
|---|---|
| `addf(F64, s, a, b)`, `sub`, `mul`, `exp(F64, s, a)`, ... | `addf(a, b)`, `sub(a, b)`, `exp(a)`, ... |
| `eq(F64, s, a, b)`, `eq_i(s, a, b)`, `add_i(s, a, b)` | `eq(a, b)`, `eq_i(a, b)`, `add_i(a, b)` |
| `addi(I16, s, a, b)`, `select(F64, s, c, a, b)` | `addi(a, b)`, `select(c, a, b)` |
| `int_to_float(I32, F64, s, t)`, `float_to_int(..)`, `float_to_float(..)` | `int_to_float(t, F64)`, `float_to_int(t, I32)`, `float_to_float(t, F32)` |
| `mmaf(F64, m, k, n, a, b, c)`, `mmai(m, k, n, a, b, c)`, `mmaf_scaled(..)` | `mmaf(a, b, c)`, `mmai(a, b, c)`, `mmaf_scaled(a, b, c, sa, sb)` |
| `f_const(F64, s, v)`, `consti(I16, s, v)`, `i_const(s, v)` | `f_const(F64, v)`, `consti(I16, v)`, `i_const(v)` |
| `spread(F64, s, x)` | `broadcast(x, s)` |
| `s_addf`, `s_mulf`, `s_maxf`, `s_minf`, `s_fma`, `s_eq`, `s_gt`, `s_select`, `s_const` | `addf`, `mul`, `maxf`, `minf`, `fma`, `eq`, `gt`, `select`, `f_const` |
| `s_addi`, `s_maxi`, `s_le_i`, `s_consti` | `add_i`, `max_i`, `le_i`, `i_const` |
| `idx_as_scalar(i)` | `idx_as_tile(i)` |
| `d_reduce(F64, s, t, id, f)`, `d_reduce_dim(F64, s, k, t, id, f)` | `d_reduce(t, id, f)`, `d_reduce(t, id, f, dim: k)` |
| `d_reduce_i`, `d_reduce_dim_i`, `d_scan_i` | `d_reduce(t, to_float(id), f)`, `d_scan(..)` |
| `d_scan(F64, s, dim, rev, t, id, f)`, `d_scan2(..)` | `d_scan(t, id, f, dim: k, reverse: r)`, `d_scan2(..)` |
| `extract(F64, s, to, t, i)`, `insert(F64, sub, whole, s, t, i)`, `cat(F64, dim, l, r, a, b)`, `permute_tile(F64, s, perm, t)` | `extract(t, to, i)`, `insert(s, t, i)`, `cat(a, b, dim)`, `permute_tile(t, perm)` |
| `load_strided(p, b, s, st)`, `load_masked(p, b, s, m, z)`, `load_strided_masked`, `load_hinted` | `load(p, b, s, strides: Some(st), mask: Some(m), pad: Some(z), hints: h)` |
| `store(p, b, s, t)`, `store_strided`, `store_masked`, `store_strided_masked`, `store_hinted` | `store(p, b, t, strides:, mask:, hints:)` |
| `gather_masked(p, i, s, m, z)`, `scatter_masked`, `atomic_rmw_masked`, `atomic_add_masked`, `atomic_cas_masked` | `gather(p, i, mask: Some(m), pad: Some(z))`, `scatter(.., mask:)`, `atomic_rmw(.., mask:)`, `atomic_add(.., mask:)`, `atomic_cas(.., mask:)` |
| `ptr_offset(F64, s, ps, o)`, `load_ptrs(F64, s, ps)`, ... | `ptr_offset(ps, o)`, `load_ptrs(ps)`, ... |
| `tensor_view(F64, p, ..)`, `load_view(F64, v, ix)`, ... | `tensor_view(p, ..)`, `load_view(v, ix)`, ... |
| `d_assert(s, c, msg)`, `d_print(F64, f, xs)`, `assume_div_by(F64, s, n, t)`, ... | `d_assert(c, msg)`, `d_print(f, xs)`, `assume_div_by(t, n)`, ... |
| `store(o, b, s, t)` into an `Out` | `store_cell(o, t)` or `store_sub(o, at, t)` |
| `d_for(idx_const(0), idx_const(n), idx_const(1), init, f)` | `d_range(0, n, init, f)` (the old spelling still records the same) |

## 0.7.0 (2026-10-04)

- `load` and `store` take the pointer path's options as defaulted named
  arguments (`strides:`, `mask:`, `pad:`, `hints:`), so any combination is one
  call. `load_strided`, `load_masked`, `load_strided_masked`, `load_hinted` and
  the four matching stores remain, each one call of the merged function, and
  record what they recorded in 0.6.0.
- The view an `Out` is written through carries `assume div_by<16>`, as an
  `In`'s already did, so `store_cell` lowers differently. No signature
  changed. §6.25.

## 0.6.0 (2026-10-04)

`load_cell`, `load_at`, `store_cell`, `zeros`, `fill`; `reduce_sum`,
`reduce_max`, `reduce_min` and `scan_sum` with `dim:` and `keepdims:`;
`broadcast`; rank-0 widening. `Dev` gains `t_cell_view`, `t_cell_fill`,
`t_reshape` and `t_broadcast`, which is the only reason this is a minor and
not a patch: every function that existed keeps its signature and records the
same program. §6.25.

## 0.5.1 (2026-10-04)

Parameter markers: `trace1` to `trace5`, `In`, `Out`, `Shared`, `Arg`,
`Cells`, `cells`, `FREE_AXIS`, and typed entries for `std/gpu`'s
`launch_entryN`. Adds names only. §6.24.

## 0.5.0 (2026-10-03)

`Dev` gains `t_body_enter` / `t_body_exit`, and `prog.trace_calls` keeps the
kernel's calls as a tree, each region call over the calls in its closure.
Operations are numbered depth first, a region before its body; before, a
`Call`'s range counted top-level operations and a region's body was one row.
§6.23.

## 0.4.0 (2026-10-03)

`Dev` gains `t_shape_of(h)`. Views and view reads get rows in the handle
table, so a view passed where a tile belongs is refused, as is an `mmaf`,
`mmaf_scaled` or `mmai` whose `k` disagrees with its operands. §6.22.

## 0.3.2 (2026-10-03)

Doc comments. No behaviour change.

## 0.3.1 (2026-10-03)

The recorder refuses element-wise operands that disagree with what the
operation declares, and `d_fork2` writes it cannot show to be disjoint,
naming the operation by its depth-first number. Before, only `tileiras`
refused such a program. §6.21.

## 0.3.0 (2026-10-03)

`Dev` gains `t_call_enter` / `t_call_exit`; `prog.trace_calls` and
`render.line_map` say which public call issued which line.

## 0.2.0 (2026-10-02)

The attribute variants are defaulted named parameters: `addf(F32, s, a, b,
rounding: Down)` for `addf_down`, `float_to_int(..., saturating: true)` for
`float_to_int_sat`, `d_global(..., visibility: Private)` for
`d_global_private`, `trace_kernel(..., hints: hs)` for
`trace_kernel_hinted`, and so on; the 24 suffixed functions are gone. The
recorded IR does not change. Rationale:
[`docs/std-defaults-design.md`](../../docs/std-defaults-design.md) §7.2.

## 0.1.0 (2026-09-02)

The `Dev` effect, the recording handler and the Tile IR text renderer.
