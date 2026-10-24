# From Dawn function to cuda_tile operation

Every public function of `tileir/dev` and `tileir/prog`, and the `cuda_tile`
operation it records. A kernel is Dawn, the Tile IR the assembler reads is
`cuda_tile`, and the names differ (`add` records `addf`, `reduce_sum` records
a `reduce` whose region holds an `addf`): this table is the dictionary between
them. [README.md](README.md) says how to write a kernel, and
`./bin/dawn doc packages/tileir` prints every signature.

- **Operation** is what the function exists to record: the dialect mnemonics
  (the names of `BytecodeOpcodes.td` in NVIDIA/cuda-tile), as `render` prints
  them. A function that picks among several by format or
  attribute lists them all (`reduce_sum` over floats records `addf`, over
  integers `addi`). `-` means the function records nothing: it builds a
  value, an attribute or a host number.
- **Also** is what a call may write around that operation: the address
  arithmetic of a load, the views a cell is read through, the `yield` of a
  region.
- Any element-wise function may also write a `constant` (a literal operand)
  and a `reshape` and a `broadcast` (widening a rank-0 operand or a length-1
  dimension); those three are not repeated on every row.
- `entry`, `module` and `global` are records of the bytecode and not
  instructions of a kernel body, so they are the functions that write them
  that carry them.

The table is checked, not trusted: `scripts/tileir-docs/check.py` reads this
file and holds it to `dev.dawn` and `prog.dawn` in both directions (a public
function with no row is red, and so is a row for a function that is not
there), and holds every operation named to the opcodes of
`scripts/tileir-features/features.txt` (a misspelled mnemonic is red, and so
is an implemented opcode that no row mentions). It does not check which
operation a function records; the goldens in `scripts/tile-golden` do. The
rows were written against them: the attribution of lines to calls that
`render.line_map` keeps was run over the 191 kernels recorded with `traceN`,
and every operation it saw under a function is on that function's row (the
`constant`, `reshape` and `broadcast` above aside). A function none of those
kernels calls, such as `scan_sum` or `fill`, was read from its recording
handler.

Tile bitwise operators require `D: TileBitsDtype` (Bool, I8, I16, I32,
Int), with ground `!Dev`. Integer `&`, `|`, `^` record `andi`, `ori`,
`xori`; mask `&` and `|` record the existing `select` kernels. `~` records
`xori` with a same-format all-ones constant (1 for i1). The pure witness
method `bits_dtype` returns `Dtype[D]`; `shift_dtype` on `TileShiftDtype`
returns the four signed integer witnesses for the later shift migration.
Both operands must match that witness. Broadcasting accepts rank 0 and
same-rank dimensions of length 1. Operators have no `at` argument and use
the enclosing recording boundary's location, as arithmetic operators do.

The following rows name prelude trait methods on `Tile[D]`, rather than
functions in the top-level namespace.

| Function | Operation | Also |
|---|---|---|
| `bit_and` | `andi`, `select` | `constant` |
| `bit_or` | `ori`, `select` | `constant` |
| `bit_xor` | `xori` | - |
| `bit_not` | `xori` | `constant` |

## Where the block is

Index values (`Idx`) are rank-0 `i32` tiles, so index arithmetic is integer arithmetic.

| Function | Operation | Also |
|---|---|---|
| `block_id` | `get_tile_block_id` | - |
| `num_blocks` | `get_num_tile_blocks` | - |
| `tile_at` | `muli` | `constant` |
| `idx_const` | `constant` | - |
| `idx_add` | `addi` | - |
| `idx_sub` | `subi` | - |
| `idx_mul` | `muli` | - |
| `idx_div` | `divi` | - |
| `idx_rem` | `remi` | - |
| `idx_eq` | `cmpi` | - |
| `idx_ne` | `cmpi` | - |
| `idx_lt` | `cmpi` | - |
| `idx_le` | `cmpi` | - |
| `idx_gt` | `cmpi` | - |
| `idx_ge` | `cmpi` | - |
| `idx_of` | - | - |
| `idx_as_tile` | - | - |
| `extent_of` | `get_num_tile_blocks`, `muli`, `constant` | - |
| `blocks_of` | `get_num_tile_blocks`, `constant` | - |
| `tensor_dim` | `get_tensor_shape` | - |
| `index_space_dim` | `get_index_space_shape` | - |

## Parameters and cells

A cell is this block's piece of a parameter. Reading one builds a tensor view and a partition view of the parameter once, then loads through the view.

| Function | Operation | Also |
|---|---|---|
| `param` | - | - |
| `position` | - | - |
| `param_dtype` | - | - |
| `scalar` | - | - |
| `load_cell` | `load_view_tko` | `make_tensor_view`, `make_partition_view`, `assume`, `get_tile_block_id`, `get_num_tile_blocks`, `muli`, `constant`, `reshape` |
| `load_at` | `load_view_tko` | `make_tensor_view`, `make_partition_view`, `assume`, `get_tile_block_id`, `get_num_tile_blocks`, `muli`, `constant`, `reshape` |
| `store_cell` | `store_view_tko` | `make_tensor_view`, `make_partition_view`, `assume`, `get_tile_block_id`, `get_num_tile_blocks`, `muli`, `constant`, `reshape`, `broadcast` |
| `store_sub` | `store_view_tko` | `make_tensor_view`, `make_partition_view`, `assume`, `get_tile_block_id`, `get_num_tile_blocks`, `muli`, `addi`, `constant`, `reshape` |
| `zeros` | `constant` | - |
| `tile_shape` | - | - |
| `fill` | `constant` | - |
| `retile` | `make_tensor_view`, `make_partition_view` | `assume`, `get_num_tile_blocks`, `muli`, `constant` |

## Views

A view is a typed window onto a parameter. `load_view` and `store_view` move one tile through it.

| Function | Operation | Also |
|---|---|---|
| `tensor_view` | `make_tensor_view` | `offset` |
| `tensor_view_dyn` | `make_tensor_view` | `offset` |
| `partition_view` | `make_partition_view` | - |
| `strided_view` | `make_strided_view` | - |
| `gather_scatter_view` | `make_gather_scatter_view` | - |
| `load_view` | `load_view_tko` | - |
| `store_view` | `store_view_tko` | - |
| `load_gather` | `load_view_tko` | - |
| `store_gather` | `store_view_tko` | - |
| `atomic_red_view` | `atomic_red_view_tko` | - |
| `view_grid` | - | - |
| `strided_grid` | - | - |
| `dim_extent` | - | - |
| `dim_operands` | - | - |

## The pointer path

For what no cell describes. A memory operation builds a tile of pointers (`offset` over the parameter's pointer) and goes through it; the address arithmetic around it is the `iota`, `muli` and `addi` ladder of the strides.

| Function | Operation | Also |
|---|---|---|
| `load` | `load_ptr_tko` | `constant`, `muli`, `addi`, `iota`, `reshape`, `broadcast`, `offset` |
| `store` | `store_ptr_tko` | `constant`, `muli`, `addi`, `iota`, `reshape`, `broadcast`, `offset` |
| `gather` | `load_ptr_tko` | `offset`, `reshape`, `broadcast`, `constant` |
| `scatter` | `store_ptr_tko` | `offset`, `reshape`, `broadcast` |
| `atomic_rmw` | `atomic_rmw_tko` | `offset`, `reshape`, `broadcast` |
| `atomic_add` | `atomic_rmw_tko` | `offset`, `reshape`, `broadcast`, `constant` |
| `atomic_cas` | `atomic_cas_tko` | `offset`, `reshape`, `broadcast` |
| `lanes` | `iota` | `reshape`, `broadcast`, `muli`, `addi` |
| `lanes_strided` | `iota` | `reshape`, `broadcast`, `muli`, `addi` |
| `coord` | `iota` | `reshape`, `broadcast`, `muli`, `addi`, `constant` |
| `arange` | `iota` | - |
| `ptrs` | - | `reshape`, `broadcast` |
| `ptr_offset` | `offset` | - |
| `ptr_to_int` | `ptr_to_int` | - |
| `int_to_ptr` | `int_to_ptr` | - |
| `ptr_to_ptr` | `ptr_to_ptr` | - |
| `load_ptrs` | `load_ptr_tko` | - |
| `store_ptrs` | `store_ptr_tko` | - |
| `global_ptrs` | `get_global` | `reshape`, `broadcast` |
| `alloca_ptrs` | `alloca` | `reshape`, `broadcast` |
| `d_global` | `global` | - |

## Float arithmetic

The operators `+ - * /` and unary `-` on tiles are `add`, `sub`, `mul`, `div` and `neg`. Over an integer tile they are the integer operations of the next section.

| Function | Operation | Also |
|---|---|---|
| `add` | `addf` | - |
| `sub` | `subf` | - |
| `mul` | `mulf` | - |
| `div` | `divf` | - |
| `max` | `maxf` | - |
| `min` | `minf` | - |
| `neg` | `negf` | - |
| `abs` | `absf` | - |
| `sqrt` | `sqrt` | - |
| `sqrt_approx` | `sqrt` | - |
| `rsqrt` | `rsqrt` | - |
| `exp` | `exp` | - |
| `exp2` | `exp2` | - |
| `log` | `log` | - |
| `log2` | `log2` | - |
| `pow` | `fpowf` | - |
| `powi` | `fpowi` | - |
| `sin` | `sin` | - |
| `cos` | `cos` | - |
| `tan` | `tan` | - |
| `sinh` | `sinh` | - |
| `cosh` | `cosh` | - |
| `tanh` | `tanh` | - |
| `atan2` | `atan2` | - |
| `floor` | `floor` | - |
| `ceil` | `ceil` | - |
| `remf` | `remf` | - |
| `fma` | `fma` | - |
| `erf` | `absf`, `fma`, `divf`, `mulf`, `subf`, `exp`, `negf`, `cmpf`, `select` | `constant` |

## Matrix products

The product `a * b + acc`. `mma` picks the operand and accumulator formats from the dialect's table.

| Function | Operation | Also |
|---|---|---|
| `mma` | `mmaf` | - |
| `mma_scaled` | `mmaf_scaled` | - |
| `mmai` | `mmai` | - |

## Constants

A constant is a rank-0 tile; `full` and `zeros` spread one over a shape.

| Function | Operation | Also |
|---|---|---|
| `f_const` | `constant` | - |
| `lit` | `constant` | - |
| `full` | `constant`, `broadcast` | `reshape` |
| `i_const` | `constant` | - |
| `i8_const` | `constant` | - |
| `i64_const` | `constant` | - |
| `bool_const` | `constant` | - |
| `consti` | `constant` | - |

## Comparisons

Each answers a `Tile[Bool]`. The `_u` forms are the unordered float predicates (true when either side is NaN).

| Function | Operation | Also |
|---|---|---|
| `eq` | `cmpf` | - |
| `ne` | `cmpf` | - |
| `lt` | `cmpf` | - |
| `le` | `cmpf` | - |
| `gt` | `cmpf` | - |
| `ge` | `cmpf` | - |
| `eq_u` | `cmpf` | - |
| `ne_u` | `cmpf` | - |
| `lt_u` | `cmpf` | - |
| `le_u` | `cmpf` | - |
| `gt_u` | `cmpf` | - |
| `ge_u` | `cmpf` | - |
| `eq_i` | `cmpi` | - |
| `ne_i` | `cmpi` | - |
| `lt_i` | `cmpi` | - |
| `le_i` | `cmpi` | - |
| `gt_i` | `cmpi` | - |
| `ge_i` | `cmpi` | - |

## Integer arithmetic

The `_i` forms are `i32` tiles. The unsuffixed `addi`, `subi` and `muli` take any integer width.

The shift operators require `TileShiftDtype`: I8, I16, I32 or Int. Their Amount is the same tile type, with the existing rank-zero and singleton broadcasting. Each lane first masks its count with `width - 1`, including negative counts. Left shifts wrap, `>>` copies the sign bit, and `>>>` fills with zero. Every device shift is preceded by an explicit `andi`; operators carry `!Dev` and use the recording boundary location.

| Function | Operation | Also |
|---|---|---|
| `add_i` | `addi` | - |
| `sub_i` | `subi` | - |
| `mul_i` | `muli` | - |
| `div_i` | `divi` | - |
| `rem_i` | `remi` | - |
| `max_i` | `maxi` | - |
| `min_i` | `mini` | - |
| `mulhi_i` | `mulhii` | - |
| `neg_i` | `negi` | - |
| `abs_i` | `absi` | - |
| `shl` | `shli` | `constant`, `andi` |
| `shr` | `shri` | `constant`, `andi` |
| `ushr` | `shri` | `constant`, `andi` |
| `add_i64` | `addi` | - |
| `addi` | `addi` | - |
| `subi` | `subi` | - |
| `muli` | `muli` | - |

## Conversions

Every conversion is one operation; the format pair and the rounding are its attributes.

| Function | Operation | Also |
|---|---|---|
| `int_to_float` | `itof` | - |
| `float_to_int` | `ftoi` | - |
| `float_to_float` | `ftof` | - |
| `to` | `ftof` | - |
| `mask_to_int` | `exti` | - |
| `int_to_mask` | `trunci` | - |
| `bits_to_float` | `bitcast` | - |
| `bits_to_int` | `bitcast` | - |
| `ext_u8` | `exti` | - |
| `trunc_u8` | `trunci` | - |
| `ext_i4` | `exti` | - |
| `ext_u4` | `exti` | - |
| `trunc_i4` | `trunci` | - |
| `pack_bytes` | `pack` | - |
| `unpack_bytes` | `unpack` | - |

## Masks and selection

A mask is a `Tile[Bool]`; combining two is a `select`, since the dialect has no boolean `and`.

| Function | Operation | Also |
|---|---|---|
| `select` | `select` | - |
| `in_range` | `cmpi`, `select` | `constant` |
| `axis_mask` | `cmpi` | `constant`, `muli`, `addi`, `iota`, `reshape`, `broadcast` |
| `tail_mask` | `cmpi` | `constant`, `muli`, `addi`, `iota`, `reshape`, `broadcast` |

## Loops, branches and folds

A rank-0 device `if` supports memory operations, atomics and nested staged loops in both Unit and Tile value forms. Both arms start from the same entry token. If either advances it, a private token result selects the executed arm's end; pure branches add no token slot. The recorder restores carries and result slots between arms and keeps cached views scoped to their region. Conditional write sets include both arms, so unordered fork chains with overlapping or unknown writes are refused. Mutually exclusive arms may write the same address. Reductions and scans remain pure, including an `if` nested inside them.

Conditions require `Tile[Bool]` with shape `[]`; even `[1]` is refused. Lane predicates use `select` or a memory mask. A value form requires `else` and identical result dtype and shape, with no broadcasting, promotion or implicit host result. Each arm initializes its own result before the merge. Read-only In loads keep the entry token without adding a token result; explicit region metadata distinguishes token results from data.

A refusal points to the user's call or recording boundary. Trait methods have no independent `caller()` argument, so an operator or staged condition may use the enclosing trace location. `while` still requires a host Bool. Nonlocal `break`, `continue`, `return` and `?` cannot cross a staged arm. Device atomic results are checked against tileref; tileinterp explicitly refuses atomics and that refusal is not a numerical pass.

A region function records a region operation; carry and result discovery trials run its closures before the final recording. `carry`, `get` and `set` are the loop-carried values of a region and are no instruction of their own.

| Function | Operation | Also |
|---|---|---|
| `d_range` | `for`, `continue` | `constant` |
| `d_loop` | `loop`, `if`, `break`, `continue` | `yield` |
| `d_if` | `if`, `yield` | - |
| `staged_if` | `if` | `yield` |
| `result_open` | - | - |
| `result_set` | - | - |
| `result_get` | - | - |
| `d_return_if` | `if`, `return` | `yield` |
| `carry` | - | - |
| `get` | - | - |
| `set` | - | - |
| `d_reduce` | `reduce`, `yield` | - |
| `d_reduce2` | `reduce`, `yield` | - |
| `d_scan` | `scan`, `yield` | - |
| `d_scan2` | `scan`, `yield` | - |
| `reduce_sum` | `reduce`, `addf`, `addi`, `yield` | `reshape` |
| `reduce_max` | `reduce`, `maxf`, `maxi`, `yield` | `reshape` |
| `reduce_min` | `reduce`, `minf`, `mini`, `yield` | `reshape` |
| `scan_sum` | `scan`, `addf`, `addi`, `yield` | - |
| `d_fork2` | `join_tokens` | - |

## Shapes

Shape changes inside a block, with no memory traffic.

| Function | Operation | Also |
|---|---|---|
| `extract` | `extract` | - |
| `insert` | `insert` | - |
| `cat` | `cat` | - |
| `permute_tile` | `permute` | - |
| `transpose` | `permute` | - |
| `reshape` | `reshape` | - |
| `broadcast` | `broadcast` | `reshape` |

## Checks, side effects and promises

Operations with a token and no result a kernel reads.

| Function | Operation | Also |
|---|---|---|
| `d_assert` | `assert` | - |
| `d_print` | `print_tko` | - |
| `d_assume` | `assume` | - |
| `assume_div_by` | `assume` | - |
| `assume_same_elements` | `assume` | - |
| `assume_in_range` | `assume` | - |
| `memory_fence_alias` | `memory_fence_alias_tko` | - |
| `gdc_launch_dependents` | `gdc_launch_dependents_tko` | - |
| `gdc_wait` | `gdc_wait_tko` | - |

## Attribute values and host-side helpers

Pure functions with no operation of their own: they build the attribute values the functions above take, or compute with host numbers.

| Function | Operation | Also |
|---|---|---|
| `for_arch` | - | - |
| `entry_hints` | - | - |
| `ptr_hints` | - | - |
| `view_hints` | - | - |
| `wire_entry` | - | - |
| `wire_ptr` | - | - |
| `wire_view` | - | - |
| `hints_note` | - | - |
| `rounding_name` | - | - |
| `overflow_name` | - | - |
| `padding_name` | - | - |
| `padding_is_special` | - | - |
| `padding_present` | - | - |
| `visibility_name` | - | - |
| `inbounds_note` | - | - |
| `is_float_dtype` | - | - |
| `row_major` | - | - |
| `permute` | - | - |
| `axis_strides` | - | - |

## Recorders and queries in `prog`

`traceN` and `trace_kernel` run a kernel body once under the recording handler. Every kernel starts with `make_token`, ends in `return`, and is wrapped in the `entry` and `module` records.

| Function | Operation | Also |
|---|---|---|
| `trace1` | `make_token`, `return` | `module`, `entry` |
| `trace2` | `make_token`, `return` | `module`, `entry` |
| `trace3` | `make_token`, `return` | `module`, `entry` |
| `trace4` | `make_token`, `return` | `module`, `entry` |
| `trace5` | `make_token`, `return` | `module`, `entry` |
| `trace6` | `make_token`, `return` | `module`, `entry` |
| `trace_kernel` | `make_token`, `return` | `module`, `entry` |
| `trace_calls` | `make_token`, `return` | `module`, `entry` |
| `cells` | - | - |
| `erase` | - | - |
| `kparam_dtype` | - | - |
| `ftof_mode` | - | - |
| `ftof_modes` | - | - |
| `mma_accumulators` | - | - |
| `op_count` | - | - |
| `defined` | - | - |
| `defined_inside` | - | - |

单例 cells 投影在 load 后、store 前使用已有 `reshape`；`zeros`/`fill`
直接生成投影后的值形状。`tile_shape` 在记录期读取该形状，不新增 opcode。
storage view 与完整 dim_map 不受投影影响。
