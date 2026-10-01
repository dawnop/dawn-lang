# packages/tileref

Tile IR kernel 的宿主参考实现：`scripts/tile-golden` 记录的每个 kernel 在这里有一个纯函数，
输入是各参数缓冲区的格式与内容，输出是设备跑完之后输出缓冲区该有的内容。
`scripts/tile-gpu-diff` 的层 2 对拍程序拿真机对它们，`scripts/leetgpu-diff/problems.txt`
每道题的「第二意见」列也指向这里。

## 为什么是包，不是 std

0.82.0 之前这批函数在 `std/gpu`。判据是
[`docs/tile-backend-design.md`](../../docs/tile-backend-design.md) §5.3 那条：
不需要 intrinsic 的不进 std。参考实现全是 `List[Float]` 上的纯函数，一个 intrinsic 也不用；
放在 std 里，每次编译都要多检查约 3000 行没有程序可达的代码，题解语料还要背 std 的
API 纪律（`std/moved.txt`、`Param-Change`、命名统一）。裁决与实测见设计文档 §5.3 的「参考实现迁出」一节。

`std/gpu` 只留设备模型：`Gpu` 效果、格式、两个 handler，以及 `reference_kernels` 的两个表项
`vadd_ref` / `sum_ref`（`dawn test --stdlib` 要有一张能用的假设备表）。

## 不依赖 `tileir`

参考实现是 kernel 的第二意见，不能走 kernel 的代码路径。`dawn.toml` 的 `[deps]` 只有 std，
`scripts/leetgpu-diff/check.py` 读这份清单，出现 `tileir` 就红。

## 用法

```toml
[deps]
tileref = "../../packages/tileref"
```

```dawn
use std/gpu.{with_gpu_fake, last_out}
use tileref/ref.{relu_ref}
```

格式运算（`round_to`、`wrap_*`、`nibble_*`）用的是 `std/gpu` 的，假设备与参考实现对
「一个格式装得下什么」不会有两种答案。
