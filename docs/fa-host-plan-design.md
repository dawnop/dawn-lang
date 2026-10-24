# FlashAttention 与 matmul 的 host plan 分层

> 状态：current，S1 实现与验收边界；算法几何已由 [S2](flash-attn-slim-s2-design.md) 迁移，本文保留 S1 的逐字节验收边界。

当前 FlashAttention 读者入口统一为 BF16 输入、F32 状态/scale/输出，见
[读者面设计](flash-attn-bf16-front-design.md)与[实际样例](../site/play-ui/samples/flash_attn.dawn)。
本文原有 f64 展示、调用计数、编译时延及测量说明属于所记实施阶段，不能作为
当前展示或性能声明；泛型算法、数值 helper、host plan 与内部 f64 回归能力保留。

S1 以泛型合并后的实现为基线，保留全部有效配置的 MLIR、tilebc、数值策略、初始化、五参 ABI 和展平网格。配置选择在录制侧完成：`FaTiles`、`MmTiles` 只保存块尺寸，`FaPlan`、`MmPlan` 保存 tiles 与 `ByArch[EntryHints]`。算法及闭包只消费 tiles、shape 与数值实例。f64 只有一份 32×16、无 hints 的 plan。

历史 evidence、median、baseline 留在 `scripts/flash-config`。对账门执行 Dawn 的实际 selector，核对输出清单、实际录制的 view/MMA/hints 与证据。P4-b 历史记录用规范化 SHA256 钉住，证明记录未被静默改写，不把它当作测量真实性证明。matmul 继续对照原始网格和胜者；P4-c、A2 的历史输出格式和测量身份保持。

两个 tileiras 13.4.92 实测性能悬崖属于应用录制策略，迁出 tileir 的公开 `check_config`。策略使用通用 `row_tile`，保留调用者位置和允许边界，并从 `wire_entry` 的实际分组解析 default fallback 与架构整组覆盖，空 hint 组按库规则省略。tileir 继续校验 hint 方言范围、dtype 与形状。删除公开函数按 0.x 兼容规则推进 tileir minor，不留 shim。

flash recorder 明确拒绝非正维度、不能被 bq/bk 整除的 n，以及不能用 I32 表示的 tile、存储及元素偏移乘积。输入域仍为 M=N 的整块输入。S1 当时的样例用 f64 和字面 32×16 tiles，精确 pin 共享算法、工厂、数值实例和必要类型，独立 plain attention 与输出验证保持。

验收包含开改前后锚点检查、全部 golden 字节比较、扩展 flash/matmul 配置双录制、真实 selector 与 IR wiring 正负控、三本新 inputs 设备账、完整外部门和精确 PR head 的 tile CI。实测结果在交付报告记录，不从源码整理推断性能提升。

## 不做的（理由）

`fa_kv_index`、`FaShape`、`acc_from_out` 与原初始化保留到 S2，以便将 host 分层与几何、初始化产物变化分开验收。不增加 cells 投影、tile_shape、网格轴变化、GQA、尾键 mask、运行期 autotune 或新数值组合。
