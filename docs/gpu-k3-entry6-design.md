# 固定六参入口与动态长度验证

> 状态：**current**，实现完成，验收记录见任务实施报告。依据 `task-gpu-k3-0-six-param-20261024.md`，以
`638b1ee3` 的 S2 与 BF16 读者面为基线。

## 契约

固定族扩至 `trace6`、`Entry6`、`entry6`、`launch_entry6` 与 Playground
`tap6`。六个位置依次保留 dtype、角色与完整 Cells，复用既有录制与启动检查。
不改变语言、运行期、flat ABI、opcode、字节码或种子。新增公开名字从 tileir
0.27.0 推进到 0.27.1，同一兼容类内追加 API。独立参考新增公开函数使 tileref
从 0.1.4 推进到 0.1.5，依赖仍仅为 std，不导入 tileir。

`scalar_wide` 改用六参类型化录制及启动，保留四 Shared、两个 Scalar 与显式
grid。继承 golden 必须逐字节不变。

独立动态求和探针使用 `x,y,z,out,scale,n`，类型为 F32/F32/F32/F32/F32/I32，
角色为三 In、一 Out、两 Scalar，计算每行有效前缀的加权和。容量 C 与 tile T
静态，逻辑长度来自第六个按值参数，view stride 始终为 C，PadZero 处理尾块。
循环使用动态 view 的 index space，容量 cells 的 blocks_of 不作有效长度。
宿主在转换 I32 和进入 handler 前拒绝非正、超容量与溢出的尺寸。

另用六参非 attention 投影探针验证完整三维 storage、axis 2、squeeze=[0]、
tile_shape 和 storage 维查询。heads=1 与多头共享同一主体，每头输入可区分。
trace6 与携带完整 erase markers 的 trace_calls 必须保持 TileProg 相等，来源
调用及父子树严格配对，零 IR 查询也保留。

## 验收

正常与拒绝路径分别覆盖第六位 In/Out/Shared/Scalar，参数次序、kind、alias、
容量、axis 2 grid、caller、非空 hints 与只读 token。编译类型负例独立验证
Launch[F32] 无法进入第六位 I32。动态样本使用同一模块的小大长度重放、两种
scale、尾区污染和三个输入的末有效元素扰动，宿主参考、解释器与设备对比。
负控登记现有 matrix/coverage，必须命中具名 oracle。

最终输入冻结后按 sm100、sm90、sm86 串行新录三账。完整外部门在最终提交
执行，jobs=39，无定向或排除；独立核验 bundle.complete=true，tree-policy
内部发布自测仍执行。实际 evidence 发布交协调者。

## 不做的（理由）

不扩变长泛型、7+、record ABI 或 dims 缓冲，六参复用现行传输足够。
不实现 attention、Grouped、GQA、尾 score mask 或有效域公开 API，这些由
后续独立任务裁定。普通 flash 保持五参，公开样例、GPU 页面和调用图保持
已合入的 BF16 demo，不混入内部 F64 回归或六参探针。
