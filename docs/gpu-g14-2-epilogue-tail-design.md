# GPU G14-2 第三刀：融合 epilogue 与尾块

> 状态：**current**（进行中）。第二刀（matmul 与 GEMM 工厂放宽整除守卫）已合并。本刀不改库：
> 只验证 G14-1 的三种融合 epilogue（恒等、启动时缩放、偏置加 relu 转 bf16）在 M、N、K 都不整除时是否正确，
> 并为这件事补上原先缺的 golden、设备用例与负控。依据：补裁一第 3 条（与 G14-1 epilogue 交互，bias 沿 N 广播）。

## 1. 要回答的问题

epilogue 是累加器 tile 的函数，跑在寄存器里，之后才是唯一的一次 store。尾块上有三处可能出错：

1. **偏置行**：`[1, N]` 的行与 B 的列同切，N 尾上最后一个列块有一部分越界列。越界列的偏置读到什么，会不会进入有效 lane？
2. **epilogue 作用在越界 lane 上**：越界 lane 的累加器是 0（两操作数都读零）加偏置再 relu，值非零；它们必须被输出 view 屏蔽，不能写出。
3. **K 尾**：操作数读侧不补零时，毒值进累加器，epilogue 把它原样带到输出。

## 2. 结论：不需要改库

- 偏置按列广播，输出 `(i, j)` 只依赖偏置 `j`，不跨 lane 混合。越界列的偏置读（`cells` 缺省 `PadZero`，读零）只会落在输出 view 屏蔽的 lane 上，
  所以**偏置读的越界值不可能进入有效输出**：PadZero 在这里不是正确性条件（和操作数的 K 尾不同，那里是归约，见第二刀的 `mm-tail-no-pad`），
  而是「读侧不读未映射内存」的定义良好性。这条结论带实测：把偏置行读侧改成 `NoPadding`，设备输出整缓冲逐 lane 不变（见 §4，等价变异体）。
  因此「偏置读去掉 PadZero 必红」这条要求在本设计里**无法成立**，不是漏测；能红的偏置故障是 extent 错（§3.3）。
- 缩放是启动时标量，没有尾块；它跑在尾块上的块里，由整缓冲比对覆盖。
- 整除形状的设备字节与既有 golden 不变：本刀不改任何工厂。

## 3. 改什么

### 3.1 golden

新增 `gemm_scale_bf16_tail`（通用计划，M=301、N=203、K=299）。恒等与偏置加 relu 的尾块 golden 第二刀已有。

### 3.2 设备（tile-gpu-diff 的 `mmtail` 家族）

新增第六个 kernel `mmtail_scale`：每卡用自己的 bf16 计划，缩放 3/8（以 f32 位型按值传入），期望在主机侧算整缓冲，
输出后接 320 行哨兵，操作数后接 +inf。`mmtail_bias` 本就在（偏置后接 +inf 毒值，操作数后接 +inf，输出后接哨兵）。

### 3.3 负控（每条都是合法录制，先在 sm_86 证明会红）

| 变异体 | 做法 | 必红的 oracle |
|---|---|---|
| `gemm-tail-no-pad` | 融合 GEMM 的两个操作数读侧改 `NoPadding` | `mmtail_bias`、`mmtail_scale`（K 尾毒值进累加器） |
| `gemm-tail-out-roundup` | 融合 GEMM 的输出 extent 上整到 tile（epilogue 写出越界 lane） | `mmtail_bias`、`mmtail_scale` |
| `gemm-tail-bias-extent-short` | 偏置行 extent 少一列（有效列读零） | 只有 `mmtail_bias`；`mmtail_scale` 与 f16 必须保持绿 |

另外 G14-1 的三个数值变异体（`gemm-scale-dropped`、`gemm-bias-after-convert`、`gemm-relu-before-bias`）也在尾块形状上跑，
对应的 oracle 必须红。每个 oracle 红、同时不相关的 oracle 必须仍绿，由 `tail_mutant` 逐条断言。

## 4. 实测（sm_86，RTX 3080，tileiras 13.5.37，形状 301x203x299）

- 六个 kernel（f64、f16、i8、bf16 恒等、bias+relu、scale）整缓冲都精确：126063 个 lane，其中 64960 个是输出后的哨兵。
- 负控全红，且只红该红的 oracle：

| 变异体 | oracle | 结果 |
|---|---|---|
| `gemm-tail-no-pad` | `mmtail_bias` | 43369 个 lane 不同 |
| `gemm-tail-out-roundup` | `mmtail_bias` | 62873 个 lane 不同，20817 个哨兵 lane 被覆盖 |
| `gemm-tail-bias-extent-short` | `mmtail_bias` | 76 个 lane 不同（最后一列，`mmtail_scale` 与 f16 保持绿） |
| `gemm-scale-dropped` | `mmtail_scale` | 61100 个 lane 不同 |
| `gemm-bias-after-convert` | `mmtail_bias` | 7384 个 lane 不同 |
| `gemm-relu-before-bias` | `mmtail_bias` | 30862 个 lane 不同 |

- **等价实验**：偏置行读侧改 `NoPadding`（一次性，不进账本），sm_86 上六个 kernel 仍整缓冲精确，变异体保持绿。
  录制本身与原版不同（字节变），但差异只落在被屏蔽的 lane。这就是 §2 的结论：偏置读的越界值进不了有效输出。
- sm_90、sm_100 在各自的 128x128x64、256x128x128 加 cga=2 计划上的结果见三份账本与逐 kernel 转写。

## 5. 不做的（理由）

- **偏置读的 PadZero 负控进账本**：它是等价变异体，进账本会让「变异体必红」的断言永远失败；以一次性实验记录代替。
- **FA 尾块**：不在本刀。
- **16 字节行跨距守卫**：第二刀已实测不需要。
- **新计划测量**：沿用既有计划格。
