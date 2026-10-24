# 按参数方向的宿主内存策略

> 状态：current

已实现，验收收据随交付报告保存。基点为 `eb8a6998`，种子为 v0.102.0。

`trace1` 至 `trace6`、`trace_kernel` 和 `trace_calls` 增加可选的
`memory: List[ArgMemory] = []`。`arg_memory(param, read = [], write = [])`
绑定零起始的逻辑参数位置，两个方向各用现有 `ByArch[ViewHints]`。
这不是 cells 几何，也不进入 kernel 的参数或捕获。空列表保留原录制。公开录制函数类型增加实参，tileir 推进到 0.28.0；
直接调用继续可省略默认值，保存函数值的调用方采用新签名。

录制开始前检查参数位置、重复绑定、标量和角色。`In` 只接受读策略，
`Out` 与 `Shared` 接受读写策略。无 marker 的指针参数接受两个方向，
按值参数拒绝。即使策略没有字段，绑定仍须合法且唯一。架构和数值
经 `wire_view` 检查，不复制架构名称或 latency 域规则。

策略只作用于支持 `ViewHints` 的 view 读写，包括 cell、派生 partition、
strided 与 gather view。录制 handler 使用已有 aims 参数来源传播；没有
参数归属的 view 不取任何参数策略。指针 load/store 的 `PtrHints` 接口
保持自身语义，不把 `allow_tma` 转成指针提示。token、所有权与数值不变。

宿主策略与显式 op hints 合并时，先分别按现有规则选择某架构的整个
字典（具体架构替代各自的 default），再逐字段合并。相同字段同值接受，
不同值报错；不同字段合并。输出包含两边架构的并集，字段顺序固定。
空宿主策略直接返回原 hints，避免无策略路径的字节漂移。

`FaPlan` 增加 memory 字段，仅 BF16 的 sm_90/d64 计划把参数 1、2
的读设为 sm_90 latency=3。其余计划为空，算法、64×128 tiles、occupancy2、
第五个运行期 F32 scale 与三维 cells/grid 保持当前实现。研究报告的
1350 MHz 两进程结果约为长单头快 5.4%、长多头快 1.9%；最终收益以
本刀新鲜装配和设备配对为准，不以研究探针作验收。

验收先检查拒绝路径，再检查同形状不同参数、派生 view、loop/if、Out
读写分向和所有 arity 的一致性。空策略与控制架构逐字节比较，目标
只允许 K/V 读 hints 改变。CPU、JVM/native、三卡、独立混合精度参考、
配对时序及完整门禁的结果回填交付报告。

## 不做的（理由）

不改算法、数值、几何、公开 BF16 demo 或 f64 计划；不增加形状阈值、
latency8、自动调优或 IR 事后补丁。N512/heads2 的 S2 增量仍是后续
编译器 lowering 研究项，不能据本刀关闭整个回退 backlog。
