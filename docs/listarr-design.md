# List 与 Array 的 std 可见互转：`list_to_array` / `array_to_list`

> 状态：**current**，已实现（分支 `std/listarr`）。2026-10-10 写成。基线 `origin/main` = 790e9ba1。
> 调研报告与裁决（维护者工作区）：`research-listarr-20261010.md`、`ruling-listarr-20261010.md`，含其它语言的出处，本文只留结论。
> 承接 [bulk-array-bytes-design.md](bulk-array-bytes-design.md) §10 的「与 §2 的偏差」：那里写明端到端的大头是 std 里的两个转换循环，缺一个 std 可见的 List 与 Array 互转。

## 1. 问题

`List` 是 `std/pvec` 的 32 叉 trie，叶子是 `Array`。checker 把 `List[T]` 与 `pvec.Vec[T]` 当两个类型，所以 `pvec.to_array` / `from_array` 只有发射器写出的代码能调；`std/bytes` 在模块顺序上也先于 `std/pvec`。结果 `std/bytes` 的 `pack_*` / `unpack_*` 与 `std/mem` 的 `from_list` / `to_list` 用 Dawn 循环过桥：进去 `array_push` 逐个，出来 `out ++ [array_get(a, i)]` 逐个。

还有另一半：`pvec.from_array` 自己也是逐元素 `push`，每个元素一次 trie 下降。所以即便有了入口，出来方向仍是逐元素。

## 2. 方案

两个 internal 内部原语，只有 std 能拼，进两后端共享的 list primitive 表（`ir/reach.dawn` 的 `list_primitive_table`）：

| 原语 | 等于 | 
|---|---|
| `list_to_array(xs: List[T]) -> Array[T]` | `std/pvec.to_array` |
| `array_to_list(a: Array[T]) -> List[T]` | `std/pvec.from_array` |

没有运行时模块拥有它们。两后端都是对同一个 Dawn 函数的调用（一份定义编译两次），JVM 只多两个描述符，native 的通用 list primitive 路径按被调函数的参数模式表处理所有权，未写新代码。登记面：builtins 表 125 到 127、lowering inline 组 39 到 41、comptime 拒绝名单 81 到 83、`selfhost/builtins.dawn` 镜像、`doc --builtins` 输出。

`pvec.from_array` 改为按块建 trie：不超过 32 个元素时数组本身就是 tail；更多时第一块 32 个做 tail，之后每块一次 `array_slice` 加一次路径拷贝（`push_block`，即 `push` 的两个满 tail 分支，元素换成 1 到 32 的块）。数组是值，tail 与输入共享不可观察。

`std/bytes` 删掉两个私有循环函数，`std/mem.from_list` / `to_list` 各去掉一个 List 方向的循环（`to_list` 先填 `Array` 再过桥一次）。

## 3. 测量

同机同会话，1M 元素，7 轮取最好，`List` 到 `Bytes` 到 `List` 端到端；native 用 clang-20 -O2。「前」是 `origin/main`，「后」是本分支。程序是 `bulk-array-bytes-design.md` §10 那份基准去掉 Array 层探针的版本。

| 项 | JVM 前 | JVM 后 | native 前 | native 后 | 目标线（JVM / native） |
|---|---|---|---|---|---|
| `List` 拷贝基线（`list.map` 恒等） | 16.6 ms | 16.7 ms | 71.1 ms | 72.4 ms | |
| `pack_floats` f64 | 12.2 ms | 2.2 ms | 42.0 ms | 15.0 ms | <= 15 / 30 ms：过 / 过 |
| `unpack_floats` f64 | 27.4 ms | 11.4 ms | 48.8 ms | 27.6 ms | <= 15 / 30 ms：过 / 过 |
| `pack_floats` f32 | 12.3 ms | 9.5 ms | 41.2 ms | 15.0 ms | |
| `pack_ints` i64 | 10.0 ms | 2.3 ms | 38.5 ms | 15.2 ms | |
| `unpack_ints` i64 | 25.5 ms | 3.4 ms | 48.8 ms | 28.8 ms | |

§10 里三条未达目标线（JVM 与 native 的 `unpack_floats`，native 的 `pack_floats`）现在全部达到。JVM 各轮抖动可达数倍（机器有其它任务），只当量级；native 各轮稳定在 1 ms 内。native 的 `unpack` 剩余约 28 ms 里含释放 1M 个浮点箱，装箱表示不变（§10 已述）。

## 4. 验证

- 单元：`std/list` 三条测试覆盖 0、1、2、31、32、33、63 到 65、1023 到 1025、1056、1057、2049 个元素（块边界与二层、三层 trie 边界）的两个方向、读写、越过边界继续 `++`、切片、数组与列表互不影响；`std/bytes`、`std/mem` 各一条在块边界做往返。
- 合约：`bytes-pack-contract`、`mem-contract`、`array-contract` 两后端通过；`intrinsic-parity` 通过（它按文本读表，所以表里的目标名写字面量，由 `reach` 的测试钉到常量）。

## 5. 不做的（理由）

1. **统一 `List[T]` 与 `pvec.Vec[T]` 的类型。** 把表示泄漏进类型层，违背「表示是后端的选择」，并牵动 comptime 与 LSP；OCaml、Kotlin、Scala、Rust 也都是容器类型分离加显式转换函数。
2. **每个 bytes 原语带一个 List 版。** 原语翻倍，且契约层要认识 List。
3. **公开面上的 `Array`。** 只有 std 能命名 `Array`，这对原语保持 internal，不给用户别名。
4. **零拷贝包装（Scala `ArraySeq` 式）。** pvec 的叶子是定长 32 的块，整个 List 不是一个数组，无从包装；拷贝是诚实的成本。
5. **平铺数值数组以消除读箱。** 沿用 `bulk-array-bytes-design.md` §7 的处置，重开条件不变。
6. **兼容层或别名。** 没有外部消费者，私有循环函数直接删除。
