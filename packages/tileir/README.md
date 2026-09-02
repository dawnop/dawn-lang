# packages/tileir

纯 Dawn 的 Tile IR 生成器：kernel 体是一个只发 `Dev` 效果的普通 Dawn 函数，
在记录 handler 下跑一遍得到 `TileProg`（SSA 形式的 ADT），再渲染成
`cuda_tile` 方言的文本。设计与刀序见
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5；
本包是那里的刀 2，不进 std（它不需要 intrinsic，且字节码版本要钉在包常量里）。

宿主侧（缓冲、launch）在 `std/gpu`，它只认 kernel 名与字节码，不认识 `TileProg`；
dtype 标记复用 `std/gpu` 的 `F64` / `F32`，本包不再声明一份。

## 模块

| 模块 | 内容 |
|------|------|
| `dev` | `pub effect Dev`（`t_block_id` / `t_load` / `t_store` / `t_addf`，句柄级、单态）；三种句柄类型 `Tile[D]`（幻影，`= Int`）、`Param[D]`（幻影，`= (Int, String)`）、`Idx`（`= Int`）；类型化包装 `param` / `block_id` / `load` / `store` / `addf` |
| `prog` | `TileOp` 变体（`MakeToken` / `BlockId` / `Load` / `Store` / `AddF`，加给刀 5 留位的 `For`）、`TileProg` 记录；`trace_kernel(name, params, body)` 记录 handler |
| `render` | `render(prog) -> String`，一个 `cuda_tile.module @m` 含一个 `entry @<name>` |

## 用法

```dawn
use std/gpu.{F64}
use tileir/dev.{Dev, Param, param, block_id, load, store, addf}
use tileir/prog.{trace_kernel}
use tileir/render.{render}

fn vadd(a: Param[F64], b: Param[F64], out: Param[F64]) -> Unit !Dev = {
  let i = block_id(0)
  let ta = load(a, i, 128)
  let tb = load(b, i, 128)
  store(out, i, 128, addf(F64, 128, ta, tb))
}

let prog = trace_kernel("vadd", ["f64", "f64", "f64"],
  () => vadd(param(F64, 0), param(F64, 1), param(F64, 2)))
let text = render(prog)
```

`params` 是每个入口参数的 dtype 名，按位置；体里的 `param(d, pos)` 必须与之一致
（位置在范围内、格式相同），否则 `trace_kernel` 直接 panic：入口签名说一种格式、
load 说另一种，字节码到了 `tileiras` 也是错。tile 宽度必须是 2 的幂。

## 记录的形状

- 句柄是记录时的 SSA 编号，从 1 起（0 是入口 token）。同一个体按同一顺序发同样的操作，
  记录到的 `TileProg` 相等；`scripts/tile-golden/run.sh` 每个 kernel 都记两次比相等。
- 内存操作的顺序只由 **token 链**给出：handler 里一格 `tok`，每个 load / store 消费上一个、
  产生下一个，`MakeToken(0)` 是链头。Tile IR 不给内存操作之间的程序序任何含义。
- 渲染时 SSA 名按出现顺序重编（`%0`, `%1`, …），因为 load / store 之前要先把标量指针
  铺成指针 tile（`reshape` → `broadcast` → `offset`，偏移是 `idx * n + iota`），这些中间名
  在记录里没有。同一 (参数, 索引, 宽度) 的指针梯子只发一次。
- `addf` 显式写 `rounding<nearest_even>`：设计文档 §3.2 的双舍入定理只对这一种模式成立。

拼写以 Tile IR 规范附录的向量加示例与 `cuda-tile` 仓库的 round-trip 测试
（`make_token`、`token=%N`）为准；本机没有 `cuda-tile-translate`，round-trip 推迟到
刀 3 的 `tileiras` 层。

## 门禁

- `dawn test packages/tileir`：内联 test 块（`scripts/package-tests.sh` 自动发现）。
- `scripts/tile-golden/run.sh`：两个 kernel（`vadd` f64 × 128、`vadd_f32` f32 × 64）
  的文本 golden，JVM 与 native 都跑，带两个变异体（渲染器少发 store 的 token 操作数 →
  golden 红；`load` 的 dtype 写死 f64 → f32 kernel 在记录时被拒）。`--record` 重录。
- `scripts/opaque-twin/tileir.dawn`：三种句柄类型的身份就是目标（`# twin-infer-only`）。
