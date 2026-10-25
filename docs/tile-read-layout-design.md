# 只读 cell 布局与有效前缀

> 状态：**current**。K3-G 在固定六参入口上补齐读布局，生产融合 GQA 留给后续任务。

`std/gpu.CellAxis = Axis(Int) | Free | Grouped(Int, Int)` 是 recorder 和 typed
launch 共用的唯一沿轴类型。Axis 保留一对一布局；Free 按 storage 顺序接收显式索引；
Grouped 仅用于 In，坐标为 grid block id 除以组大小。组大小必须为正 i32，容量必须静态，
grid 必须完整分组。Out 仍只接受 Axis 单射。所有可静态判断的错误在 body 前拒绝，实际
grid 确定后 typed launch 再检查。g=3 的多 batch 探针防止误用位移或跨 batch 残组。

`ReadView[D]` 是从 In Grid 创建的只读记录值。`read_prefix` 仅收窄一个 Free storage
维的零起点前缀，`read_at` 继承完整 marker 的 tile、pad、along 和 squeeze，
`read_blocks` 查询有效 index space。容量 marker、原 Param 与物理 strides 不变，
`blocks_of` 和 `extent_of` 仍查询容量。动态 length 必须是 rank-0 i32；
`1 <= length <= capacity` 是调用者的宿主前置条件，Entry6 不理解标量的领域含义。

实现复用现有 tensor/partition view、shape query 和整数除法，不加 TileOp 或 opcode。
新值不缓存，遵守既有 SSA 区域可见性；来源沿原 Param 传播，In 读取使用入口 token。
ReadView 不转 GridView，不提供写 API。PadZero 负责读取尾 lane，算法中的显式 select
在 max/exp/sum 前把无效 score 置为负无穷，两个责任分别用结构与数值 oracle 验证。

验收保留所有继承 MLIR/tilebc 字节，新增布局、动态前缀和 BF16 score-mask 探针；
沿现有 golden、解释器、map 与三卡设备 harness 验证。公开 flash 样例仍为五参 BF16。

## 不做的（理由）

不实现生产融合 GQA、尾 query、M 与 N 不同、任意布局代数、写布局、ragged/paged KV、
动态 head 数或七参入口：这些超出本次读布局接缝。不给 prefix 增加自动 mask，避免隐藏
softmax 的概率语义。不改变数值策略、普通 flash 支持域或历史性能账。
