# packages/tileir

纯 Dawn 的 Tile IR 生成器：kernel 体是一个只发 `Dev` 效果的普通 Dawn 函数，
在记录 handler 下跑一遍得到 `TileProg`（SSA 形式的 ADT），降成一张线性指令表，
再渲染成 `cuda_tile` 方言的文本，或编码成 `tileiras` 能汇编的字节码。设计与刀序见
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5 与 §6；
本包是那里的刀 2 与刀 3，不进 std（它不需要 intrinsic，且字节码版本要钉在包常量里）。

宿主侧（缓冲、launch）在 `std/gpu`，它只认 kernel 名与字节码，不认识 `TileProg`；
dtype 标记复用 `std/gpu` 的 `F64` / `F32` / `BF16`，本包不再声明一份。bf16 kernel 的写法与
f64 的相同（`Param[BF16]`、`addf(BF16, ...)`），dtype 名 `"bf16"` 贯穿记录、降低、渲染
（`tile<128xbf16>`）与字节码（类型标签 6）；设备侧 `addf ... rounding<nearest_even>` 对 bf16
的答案按双舍入定理等于 `std/narrow.round_bf16(f64 加)`，`scripts/tile-golden` 的 `vadd_bf16`
钉文本与字节码，`scripts/tile-gpu-diff` 拿设备对假设备。

## 模块

| 模块 | 内容 |
|------|------|
| `dev` | `pub effect Dev`（`t_block_id` / `t_load` / `t_store` / `t_addf`、索引算术 `t_idx_const` / `t_idx_add` / `t_idx_mul`、区域 `t_loop_begin` / `t_loop_end`，句柄级、单态）；三种句柄类型 `Tile[D]`（幻影，`= Int`）、`Param[D]`（幻影，`= (Int, String)`）、`Idx`（`= Int`）；类型化包装 `param` / `block_id` / `load` / `store` / `addf` / `idx_const` / `idx_add` / `idx_mul`，循环 `d_for`（携带一个 tile）/ `d_for2`（两个） |
| `prog` | `TileOp` 变体（`MakeToken` / `BlockId` / `Load` / `Store` / `AddF` / `IdxConst` / `IdxAdd` / `IdxMul` / `For` / `Continue`）、`TileProg` 记录；`trace_kernel(name, params, body)` 记录 handler，带区域栈；`MAX_LOOP_DEPTH` / `MAX_HANDLES` |
| `lower` | `lower(prog) -> Kernel`：指令表 `Instr`（`MakeTok / BlockIds / ConstI32 / MulInt / AddInt / Reshape / Broadcast / Iota / Offset / LoadPtr / StorePtr / AddFloat / ForLoop / Cont / Ret`，`ForLoop` 的体是嵌套的一张表），值从 0 密集编号，操作数 `Arg(pos)` / `Val(id)`，类型 `Ty`（`Token` / `Tile(shape, elem)`）；指针梯子、去重、SSA 重编、区域作用域都在这里 |
| `render` | `render(prog) -> String`，一个 `cuda_tile.module @m` 含一个 `entry @<name>`；一条 `Instr` 一行，`for` 是头一行、体缩两格、右花括号 |
| `bytecode` | `encode(prog) -> Bytes`，`cuda-tile` 字节码，含 `for` / `continue` 的区域编码；`BYTECODE_MAJOR / BYTECODE_MINOR` 钉头里的版本，`bytecode_version()` 给出 `"13.2"` |

## 用法

```dawn
use std/gpu.{F64}
use tileir/dev.{Dev, Param, param, block_id, load, store, addf}
use tileir/prog.{trace_kernel}
use tileir/render.{render}
use tileir/bytecode.{encode}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let i = block_id(0)
  let ta = load(a, i, 128)
  let tb = load(b, i, 128)
  store(out, i, 128, addf(F64, 128, ta, tb))
}

let prog = trace_kernel("vadd", ["f64", "f64", "f64"],
  () => vadd(param(F64, 0), param(F64, 1), param(F64, 2)))
let text = render(prog)     # 给人读、给 golden 钉
let bytes = encode(prog)    # 给 tileiras --gpu-name sm_86 编成 cubin
```

`params` 是每个入口参数的 dtype 名，按位置；体里的 `param(d, pos)` 必须与之一致
（位置在范围内、格式相同），否则 `trace_kernel` 直接 panic：入口签名说一种格式、
load 说另一种，字节码到了 `tileiras` 也是错。tile 宽度必须是 2 的幂。

kernel 内的循环走 `d_for`（设计文档 §5.2）：边界与步长是 `Idx`（宿主常量用 `idx_const`），
携带一个 tile，体在宿主上只跑一次、体内发的操作落进循环区域：

```dawn
# 块 b 把 x 里 chunks 个连续 128 宽 tile 折进 out 的一个 tile
fn sum(x: Param[F64], out: Param[F64], chunks: Int) -> Unit !Dev = {
  let b = block_id(0)
  let n = idx_const(chunks)
  let base = idx_mul(b, n)
  let first = load(x, base, 128)
  let one = idx_const(1)
  let acc = d_for(idx_add(base, one), idx_add(base, n), one, first,
    (k, t) => addf(F64, 128, t, load(x, k, 128)))
  store(out, b, 128, acc)
}
```

`d_for2` 携带两个 tile。循环嵌套深度上限 `MAX_LOOP_DEPTH`（16），一次记录的句柄数上限
`MAX_HANDLES`（65536），超限 panic：递归穿过 `d_for` 的 helper 与不进循环的递归 helper
各在一处停下。没有 `d_if`（归约用不到；加的时候照 `lower_for` 的形状）。

## 记录的形状

- 句柄是记录时的 SSA 编号，从 1 起（0 是入口 token）。同一个体按同一顺序发同样的操作，
  记录到的 `TileProg` 相等；`scripts/tile-golden/run.sh` 每个 kernel 都记两次比相等。
- 内存操作的顺序只由 **token 链**给出：handler 里一格 `tok`，每个 load / store 消费上一个、
  产生下一个，`MakeToken(0)` 是链头。Tile IR 不给内存操作之间的程序序任何含义。
- 降低时值按出现顺序重编（0, 1, …），因为 load / store 之前要先把标量指针
  铺成指针 tile（`reshape` → `broadcast` → `offset`，偏移是 `idx * n + iota`），这些中间值
  在记录里没有。同一 (参数, 索引, 宽度) 的指针梯子只发一次。渲染器把 `Val(k)` 拼成 `%k`、
  `Arg(i)` 拼成 `%argi`；写入器把入口参数排在前、值紧随其后，成一个平坦的索引空间。
- `addf` 是 `rounding<nearest_even>`：设计文档 §3.2 的双舍入定理只对这一种模式成立；
  指令表里没有这个字段，因为它没有第二个取值。`scripts/tile-golden` 的 `addf-no-rounding`
  变异体把渲染器的这个属性删掉，`vadd_bf16.mlir` 红；`bf16-tag-as-i16` 把写入器的 bf16
  标签改成 i16，`tileiras` 拒绝。
- **循环**记录成 `For(iv, lower, upper, step, inits, carried, results, body)`，`body` 以
  `Continue(values)` 结尾。handler 维护区域栈：`t_loop_begin` 压栈并清空当前操作表，
  `t_loop_end` 弹栈把体包成 `For` 接回外层。**token 作为最后一个携带值穿过循环**：`inits`
  末尾是循环前的 token，体从区域内的携带 token 起链，`Continue` 末尾是体的最后一个 token，
  循环后 handler 从 `results` 末尾继续，kernel 体看不见它。降低时体内定义的句柄出区域即
  关闭，之后再引用按名拒绝；体内建的指针梯子不在循环后复用。指令表给 `ForLoop` 编号按
  阅读序：结果、归纳变量、携带值、体。

## 字节码

`encode` 写的是 `NVIDIA/cuda-tile` 的 `BytecodeWriter.cpp` 写、`BytecodeReader.cpp` 读的格式
（commit `be0889cd`）：8 字节 magic、`13.2` 版本头、Func / Constant / Type / String 四个
section、结束字节；opcode、类型 tag 来自仓库里冻结的三张 `.td` 表，逐操作布局来自生成它的
tablegen 后端（结果类型 → 可选字段 flags 位域 → 属性 → 操作数）。cuTile.jl 的
`src/bytecode` 是同一格式的另一份实现，写的时候逐项对照过；两处形态差异（它总写 debug
section、预注册 i1 / i32）reader 都接受，本包照 C++ 写入器。

只编码指令表装得下的东西：内存操作 `weak`、无 mask、带 token；`addf` nearest_even、不
flush-to-zero；整数操作 `overflow` none；tile 为 0 或 1 阶；`for` 是一个区域一个块，
`continue` 结尾。**区域的值编号**照 reader 的规则：块参数接着外层计数编、块内结果继续、
块结束时计数回滚到块参数之前、`for` 自己的结果再从那里编；写入器用一张 `index` 表把
指令表的（文本的）编号映射过去。`for` 的 `unsigned` 是 13.2 加的可选字段，写入器只在目标
版本不低于 13.2 时写它的 flags 格，所以含循环的字节码自刀 5 起与版本号相关（无循环的
kernel 在 13.1 / 13.2 / 13.3 下仍逐字节相同）。版本、`tileiras` 的钉法与 wheel 的 sha256 在
`scripts/tile-golden/toolchain.txt`，`run.sh` 拿 `bytecode_version()` 与之对账。

## 门禁

- `dawn test packages/tileir`：内联 test 块（`scripts/package-tests.sh` 自动发现）。
- `scripts/tile-golden/run.sh`：三个 kernel（`vadd` f64 × 128、`vadd_f32` f32 × 64、
  `sum` 带 `d_for` 的块内 tile 求和）的文本 golden（`*.mlir`）与字节码 golden（`*.tilebc`），
  JVM 与 native 都跑；再把每个 `.tilebc` 交给钉版本的 `tileiras --gpu-name sm_86` 编成 cubin
  并查符号表里有 `GLOBAL FUNC <kernel>`（层 1，CI 的 `tile` job；本机
  `scripts/tile-golden/install-tileiras.sh <dir>` 装、`--tileiras <bin>` 或 `TILEIRAS=`
  指给它、`--without-tileiras` 明示跳过）。八个变异体：渲染器少发 store 的 token 操作数 →
  文本 golden 红；`load` 的 dtype 写死 f64 → f32 kernel 记录时被拒；handler 循环后不换 token /
  区域栈弹反 → `sum` 降低时按名拒绝、不出文本；写入器把 make_token 编成 iota 的 opcode /
  store 仍置 token 位却不写操作数 / f64 用 i64 的 tag / 循环块后不回滚值索引 → 文本不动、
  字节红、`tileiras` 各以具名报文拒绝。`--record` 重录两种 golden。
- `scripts/opaque-twin/tileir.dawn`：三种句柄类型的身份就是目标（`# twin-infer-only`）。
