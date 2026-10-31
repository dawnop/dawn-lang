# E8M0 默认转换保留逻辑源值

> 状态：**current**。G31-1 的合同与实现设计；设备基线和完整验收尚未执行。

## 合同与证据边界

默认和 `TowardZero` 都遵守现有 `std/narrow.round_f8e8m0`：先取源值的绝对值，
取不大于该值的二次幂，再夹到 `2^-127 .. 2^127`。两个零都答最小值，
两个无穷都答最大值，只有 NaN 答 NaN；不承诺 NaN payload。
默认的 `NearestEven` 参数在这个目标上仍表示 `zero`。

直接 f64 转换按源 binary64 值计算。源 bits `0x3fffffffffffffff` 答 1，
用户显式 f64→f32→E8M0 则先就近舍入到 2，再答 2。负的对应邻点也如此。
旧 `dtype_e8m0` 的显式两步 kernel 和参考保持两次舍入。
这是一条数学反例，尚不能据此声称当前直接设备路径失败。

[Tile IR 的转换规范](https://docs.nvidia.com/cuda/tile-ir/latest/sections/types.html#floating-point-conversion-semantics)
没有定义负源（包括负零与负无穷）转无符号格式的结果。因此 Dawn 必须在
lowering 中清除符号；当前某一实现恰好取绝对值不能证明这个合同。

## 完整源格式影响表

| 源格式 | 默认和 TowardZero 到 E8M0 的处理 | 验证范围 |
|---|---|---|
| f64 | 向零缩到 f32，再做下述位适配 | 源阈值两侧、f64 次正规、极值、特殊值 |
| f32 | 直接做位适配 | 正负次正规、幂阈值、零、极值、特殊值 |
| tf32、bf16、f16 | 精确扩到 f32，再做位适配 | CPU 结构与可用格式回归 |
| f8E5M2、f8E4M3FN、f4E2M1FN | 精确扩到 f32，再做位适配 | CPU 结构与可用格式回归 |
| f8E5M3FNU | 精确扩到 f32，再做位适配 | 只核结构，不增加设备消费者或资格 |
| f8E8M0FNU | 不扩展同类型 float_to_float；to 的恒等路径仍不记录操作 | 保持既有 API 边界 |

整数不是 float_to_float 的源。`Up` 不进入这条展开，解释器对它的既有拒绝不变。

## 既有指令的展开

1. f64 用 `ftof_zero` 缩到 f32；其他非 f32 源精确扩到 f32。
2. `bitcast` 到 i32，用 `andi 0x7fffffff` 清除所有符号，包括负零和负 NaN。
3. 在整数域比较并选择：低于 `0x00400000` 答该最小值，超过 `0x7f000000`
   答该最大值；大于无穷位模式 `0x7f800000` 的 NaN 单独答正的 canonical NaN。
4. `bitcast` 回 f32，再发 `ftof` 的 `zero` 到 E8M0。

f64 向零缩窄不会把有限绝对值推过二次幂阈值。目标范围内的所有幂都在 f32
中精确可表示；范围外的 underflow/overflow 最后由夹界处理。这里不能使用
普通 RNE32 中转，也不能照搬其他三种窄格式的 RNE round-to-odd 算法。
整数夹界不依赖浮点次正规比较的执行方式。所有展开指令通过 `temporary/emit`
保留原 Convert 的 owner，只有最终结果绑定原句柄。

## 预先允许的 golden 变化

既有集合只允许 `dtype_e8m0.mlir` 和 `dtype_e8m0.tilebc`：原 f32→E8M0
操作增加显式位适配，前面的 f64→f32 RNE 操作保留，读回路径保留。
新增 `e8m0_source.mlir` 和 `.tilebc` 分别存四段单步与显式两步 probe。
其他已有 golden（包括 N2 三种
窄格式、N6 的 scaled MMA、BF16 样例与来源图）必须逐字节不变。
每条新增指令都对应上述步骤；任何额外变化必须先解释，不能批量重录求绿。

## Oracle、基线与负控

实现前固定源 bits、单步和两步预期。独立 oracle 用整数位算法或精确有理数，
不调用 lowering、std/narrow 或设备答案；同时核对 tileref 和解释器。
覆盖正负幂两侧、上下界、f32/f64 次正规、±0、±Inf、两种符号的 NaN 类别。

基线保存未修改 lowering 的直接 API 与显式两步产物；有界执行保存 assembly、
PTX、SASS 与实际结果。只有实际数值不符才记设备失败。结构检查单独证明
最终无符号转换接收的是 Dawn 已明确处理的源，不把 undefined mutant 的
设备结果用作可移植性证明。

负控分别删除 magnitude、将 RTZ32 改为 RNE32、破坏低界、高界和 NaN 分支。
先有 clean 正控；阈值变异必须合法装配后数值红；magnitude 变异必须结构红，
设备上不要求 undefined 行为必错。锚点失配、语法坏或工具失败均不算负控成立。

四段源值 probe 的覆盖元数据使用独立表的实际源条数和单步/两步答案不同的条数，
不使用旧存储格式 probe 的 `off_grid` 等字段。runner 按具名 kernel 选择字段并逐项
要求非零；字段缺失、零区分度和恢复旧分派都必须在同一份真实 transcript 上拒绝。
这项检查只验证覆盖声明，不改变位模式 oracle 或任一数值判词。

## 完成条件

按实际改动查询 gatemap 并执行全部 coupled 门、锚点预飞与守卫、文档与格式门，
完整 golden 的双 trace、双后端、assembly/disassembly，解释器差分与自测、
参考包及受影响消费者。三种目标架构严格串行完整录制，旧 family 全跑，
不支持项明确拒绝或 SKIP。最后对实际最终提交运行完整外部门并独立核验 bundle。
不改变特殊值答案，不增加 opcode，不升级工具链；遇到这些需要时停止并交裁。
