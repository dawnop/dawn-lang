# scaled MMA 组合覆盖

> 状态：**current**。设计与实现已有定向证据；完整验收因既有序列家族超时停止，N6 未完成。
> 2026-10-30；基线 `ea72ae9ecc8da23db60de3d8d98d96e3d99f7fc2`。

## 今天的缺口

`scripts/tile-golden/kernels.dawn` 已有 `mmaf_scaled_e4m3`：A/B 为
f8E4M3FN、scale 为 f8E8M0FNU，M=N=32、K=64、V=32。
`arch_diff.dawn` 只运行这一种 scaled MMA。另一个已有 golden
`mmaf_scaled_e5m3` 使用 fp4、e5m3 scale、V=16，仅有 sm107 装配证据。
不能从这两个例子推导其他类型组合、block 大小或架构支持。

本刀补组合与拒绝的正确性覆盖，不新增语言机制或精细计时门。
不声明性能收益。

## 权威、探针与判词

规范使用 [Tile IR 13.4 §9.7.22](https://docs.nvidia.com/cuda/tile-ir/13.4/sections/operations.html#cuda-tile-mmaf-scaled)
和 [§11.4 架构类型表](https://docs.nvidia.com/cuda/tile-ir/13.4/sections/stability.html#feature-availability-emulation)。
同时核对冻结源码
[cuda-tile 7e8e2e68 的 MmaFScaledOp](https://github.com/NVIDIA/cuda-tile/blob/7e8e2e68/include/cuda_tile/Dialect/CudaTile/IR/Ops.td#L1575)。
源码拼写为 `f8E5M3FNU`，13.4 网页与反汇编拼写为 `fnv8E5M3FNU`；
下文简称 e5m3，二者不是两个格式。

实测工具为 `tileiras --version` 返回的 13.4.92，二进制 SHA256 为
`8733d2ef6ae234ba5b415d185c957b8cc37577507a2850313a8c0e5c7c3ac54d`。
2026-10-30 的初始探针没有修改产品代码：临时 Dawn 项目依赖基线 tileir，
五个 f64 buffer 经 `load_cell`、`float_to_float`、`mma_scaled`、
`store_cell` 留住真实输出，再以 `encode` 写 bytecode。
输入不是常量，因此没有用常量折叠代替 MMA。生成器 SHA256 为
`f95654dd5baf03912a6361a596727bbe2ec947b7bafe975d4adf89b65e668194`。

每格执行命令相同，仅换表中的名字和架构：

```text
./bin/dawn run <probe-project> -- <out>
tileiras --gpu-name <sm_100|sm_90|sm_86|sm_107> -o <case>.cubin <case>.tilebc
```

初始集合为 11 个类型对 × V∈{1,2,4,8,16,32,64} × 4 个架构，
固定 M=N=32、K=64，共 308 次装配；12 次接受、296 次拒绝、无超时。
只有退出 0、没有 `error:`、存在非空 cubin 三项同时成立才算接受。
完整收据保存命令、返回码、原文诊断、输入和 cubin SHA256。
这证明装配行为，不证明设备答案。

## 合法组合表

A/B 必须同类型，左右 scale 必须同类型；acc/result 均为 f32。
下表的形状为 A=[M,K]、B=[K,N]、acc=[M,N]、
SA=[M,K/V]、SB=[K/V,N]。Dawn 当前公开入口为二维，
维度为正二次幂，V 必须整除 K。本刀实跑 K=64，包含两个或四个 scale block。
规范还允许三维 batch；本刀不扩当前二维入口。

`P(D,S,V,arch)` 表示上述命令的 `<case>=D_S_vV` 收据。
每格的 P 是实际探针，S 是规范条款；“接受”均仅指装配。

| A/B | SA/SB | V；K=64 时 scale 形状 | sm100 | sm90 | sm86 | 出处 |
|---|---|---|---|---|---|---|
| e4m3/e4m3 | e8m0/e8m0 | 32；[M,2]/[2,N] | 接受 P(e4m3,e8m0,32,100) | 拒绝 e8m0，P(...,90) | 拒绝 e4m3，P(...,86) | S §9.7.22、§11.4；P |
| e5m2/e5m2 | e8m0/e8m0 | 32；[M,2]/[2,N] | 接受 P(e5m2,e8m0,32,100) | 拒绝 e8m0，P(...,90) | 拒绝 e5m2，P(...,86) | S §9.7.22、§11.4；P |
| fp4/fp4 | e8m0/e8m0 | 16；[M,4]/[4,N] | 接受 P(e2m1,e8m0,16,100) | 拒绝 fp4，P(...,90) | 拒绝 fp4，P(...,86) | S §9.7.22、§11.4；P |
| fp4/fp4 | e8m0/e8m0 | 32；[M,2]/[2,N] | 接受 P(e2m1,e8m0,32,100) | 拒绝 fp4，P(...,90) | 拒绝 fp4，P(...,86) | S §9.7.22、§11.4；P |
| fp4/fp4 | e4m3/e4m3 | 16；[M,4]/[4,N] | 接受 P(e2m1,e4m3,16,100) | 拒绝 fp4，P(...,90) | 拒绝 fp4，P(...,86) | S §9.7.22、§11.4；P |
| fp4/fp4 | e5m3/e5m3 | 16；[M,4]/[4,N] | 拒绝 e5m3，P(e2m1,e5m3,16,100) | 拒绝 fp4，P(...,90) | 拒绝 fp4，P(...,86) | S §9.7.22、§11.4；仅 sm107 接受 P(...,107) |
| fp4/fp4 | e5m3/e5m3 | 32；[M,2]/[2,N] | 拒绝 e5m3，P(e2m1,e5m3,32,100) | 拒绝 fp4，P(...,90) | 拒绝 fp4，P(...,86) | S §9.7.22、§11.4；仅 sm107 接受 P(...,107) |

e4m3 scale 的值必须非负（§9.7.22）；负 scale 的结果未定义，
因此不用负 scale 建数值 oracle，也不宣称装配器会拒绝动态负值。

## 非法组合与边界

| 类型或形状 | 三个目标上的实际判词 | 出处 |
|---|---|---|
| e4m3/e4m3 scale；e5m2/e4m3 scale | `unsupported combination of element types`，scale 要求 fp4 操作数 | S §9.7.22；P(e4m3,e4m3,32,arch)、P(e5m2,e4m3,32,arch) |
| e4m3/e5m3 scale；e5m2/e5m3 scale | 相同组合拒绝；在 sm107 也拒绝，排除仅架构不支持的解释 | S §9.7.22；P(e4m3,e5m3,32,arch)、P(e5m2,e5m3,32,arch)，含 sm107 |
| f16/e8m0 scale | operand #0 非法 | S §9.7.22；P(f16,e8m0,32,arch) |
| fp4/f32 scale | operand #3 非法 | S §9.7.22；P(e2m1,f32,32,arch) |
| e4m3 或 e5m2，V≠32 | f8 block scale factor 必须为 32 | P(D,e8m0,V,arch)，六个非法 V 全拒绝 |
| fp4/e8m0 或 fp4/e5m3，V∉{16,32} | block scale factor 必须为 16 或 32 | P(e2m1,S,V,arch)，五个非法 V 全拒绝 |
| fp4/e4m3，V≠16 | block scale factor 必须为 16 | P(e2m1,e4m3,V,arch)，六个非法 V 全拒绝 |
| A/B 类型不相同，或左右 scale 类型不相同 | `mma_scaled[D,S]` 的类型参数约束；raw IR 仍由 assembler 验证 | S §9.7.22 AllElementTypeMatch；后续拒绝控制需钉住两条边 |
| K 不被 V 整除、非正或非二次幂维度 | 现有 record/shape 拒绝；不发射设备请求 | `prog.dawn` 的 t_mmaf_scaled 与 check_shape；后续拒绝控制钉住 |

规范网页及冻结 Ops.td 的组合表没有给 V 的数值列，尽管引言说表包含
vector size；因此上述 V 限制来自真实 verifier，不能写成已在网页找到的规范条款。
类型与架构的接受/拒绝与规范一致。尚未发现规范明确许可而工具明确拒绝的类型对。
K=16/32/128 的补充集合为五个类型对 × 五个 (K,V) × 四架构，
共 100 次装配、29 次接受、71 次拒绝、无超时：
e4m3/e8m0、e5m2/e8m0 在 K=32/128、V=32 接受；
fp4/e8m0 在 (16,16)、(32,16)、(32,32)、(128,16)、(128,32) 接受；
fp4/e4m3 在 K=16/32/128、V=16 接受；fp4/e5m3 的同五点仅 sm107 接受。
这些有限点不证明任意形状都高效。

## 实施与独立判断

保留所有既有 MLIR/tilebc 字节。新增 sm100 四个 golden：e5m2/e8m0 V32、
fp4/e8m0 V16、fp4/e8m0 V32、fp4/e4m3 V16。
另补 fp4/e5m3 V32 的装配与三目标拒绝；没有 sm107 实机时不冒充层 2。
新数值 fixture 采用 M=N=K=64，使 writer 将 lhs/rhs 对调仍合法，
可以用实际错误答案检验写入器，而不是只检验 verifier。

fp4 操作数从 I32 words 解包，沿用已有 nibble 约定，不新增宿主 dtype。
scale 使用已有格式 buffer；e5m3 沿用从 f64 转换的装配路线。
输入只取可精确表示的整数，scale 只取正二次幂。
设备与 tileref 分开计算；再用整数 block dot 与 scale 指数构造独立答案，
保留 guard 尾区。新语料的乘积和任意部分和均在 f32 精确范围内，
使用现有 exact 判词，不改变任何容差。

每个 sm100 组合至少一个可装配的 writer/类型变异，要求具体 kernel、lane、
错误值与正确值。优先同宽类型替换；fp4 用同形状 lhs/rhs writer 对调。
拒绝控制分别覆盖类型对、V、scale 形状与架构；每条都需要 clean 接受控制
和明确英文诊断，不能只看非零退出。缺工具、超时、坏语法不算负控。
sm90/sm86 无合法 scaled MMA 组合，运行装配拒绝与其余完整设备回归，
将 scaled MMA 明确记为 SKIP。e5m3 两行保持无实机证据的事实。

落点：`tile-golden/kernels.dawn`、run/matrix、新 golden，
`tile-gpu-diff/arch_diff.dawn`、run/具名变异与三本只追加 ledger，
`packages/tileref` 的独立参考与必要测试，`tileinterp-diff` 覆盖清单，
`tileir-features` 证据表。必要的库注释纠正只描述组合，不更改记录政策。

## 验收与估时

先提交本文，再动实现。改变 tile inputs 后，按同一 inputs 串行重录
sm100→sm90→sm86；每轮收据与 raw 完整后才开始下一轮。
本机设备运行持有独占租约，用完释放。
完整 golden 包含装配、反汇编、trace twice、JVM/native parity；
解释器差分、参考包、feature/docs 门、受影响 example/map/site 与
gatemap 的全部 coupled 门均适用。最后的完整外部门禁必须绑定最终 SHA，
bundle 校验 complete=true，tile 工作流也通过；不发布证据、不合并。

开工估计 **5 人日**：组合与拒绝复核 1 日，实现和独立参考 1.5 日，
正负控与解释器 1 日，三架构整轮及全部门 1.5 日。
这是工作量估计，不是实测耗时或性能数据；排队不计入可控工时。
与原 4–6 人日一致。若发现真实数值分歧、新公共语义、必须改宿主 GPU
文件或需要工具链升级，则停止扩围，保留证据另行裁定。

## 实施记录与验收边界

设计提交为 `72be14db`，实现提交为 `5ce4ad72`。
实现增加五对 golden：四个 sm100 数值组合及仅 sm107 可装配的
fp4/e5m3 V32。继承的 496 个 MLIR/tilebc 文件逐字节未变。
类型表的 block 限制没有上升为新的 Dawn 语义；持久化探针仍以真实 assembler
判词为准。公开 `mma_scaled` 的不透明 Tile 类型没有新增解包后门：
左右类型不一致的 verifier fixture 修改公开 TileProg 的转换结果类型。

sm100 的四个新组合各有 4096 个结果与八个 guard lane，
均满足现有 exact 判词，并与独立整数 block oracle 相等。
现有 e4m3 组合继续使用原输入和尺寸。
三组合法装配的 writer 负控得到以下首错；其他指定控制组合仍 exact：

| writer 变异 | 目标 | lane 0：设备 / 期望 |
|---|---|---|
| lhs/rhs 对调 | 新 e5m2/e8m0 V32、fp4/e8m0 V32 | 8 / -10 |
| lhs/rhs 对调 | fp4/e8m0 V16、fp4/e4m3 V16 | -49 / -97 |
| e4m3 标签写成 e5m2 | 原 e4m3/e8m0 V32 | -0.25 / -0.375 |
| e5m2 标签写成 e4m3 | 新 e5m2/e8m0 V32 | -9 / -10 |

持久化拒绝门有 62 次装配，要求具体类型、V、shape 或架构诊断；
修复类型/形状后的 counterpart 必须实际装配，接受产物不能冒充拒绝。
K/scale 比例不合法的录制拒绝另有明确消息。
可直接运行 `TILEIRAS=<assembler> scripts/tile-golden/run.sh --only scaled-mma-combinations`
复核该矩阵及其正负判词。
解释器差分已覆盖四个新数值组合，新增 e5m3 V32 仍按不可达处理。
包测试为 tileir 299、tileref 33、tileinterp 205；selfhost 1202。
这些数字是本刀实际执行的正确性计数，不是性能数据。

完整 sm100 回归在既有 `seq.bin` 家族触发 300 秒截止，未追加账行。
最后打印的判词为 `xattn / last-launch-dropped / differ:result`，
后续工作未打印完成信息；无法据此定位具体卡住的操作或判定环境原因。
序列 harness、assembler 参数策略、writer、runtime 与相关继承 golden
均未被本刀修改，这证明改动边界，不能代替因果反证。

失败轮中 architecture 家族十项均 exact；四个新组合的定向数值正负控也已通过。
这些局部事实不能替代整轮完成。失败产物的内容哈希已经逐项复核，
账尾 diff 为空。没有提高时限、修改容差、跳过旧序列、换 oracle 或追跑设备。
本机完整 golden 门随后主动停止；已有通过项保留，完整门不记绿。

原估时包含正常回归，没有包含对未修改序列家族的独立超时诊断。
现在不能继续把 4–6 人日作为有依据的收口预算：诊断范围与根因尚未成立，
本刀停止扩围并交裁。sm90/sm86 完整录制尚未开始，feature 表未追加新组合
的层级证据，最终外部门禁 bundle 与 PR 均未形成。后续须先裁定独立诊断，
再按既定三架构顺序重做完整验收，不重标本轮来源。

## 不做的（理由）

- 不改 `std/gpu.dawn` 与生成的 stdsrc：本刀复用现有格式宿主通路。
- 不接入自动来源路径、不迁移手工来源、不改变录制效果或位置政策：它们有独立边界。
- 不补 e5m3 的真卡层：现有三种验收架构都拒绝该类型，不能用装配或 fake 代签。
- 不扩 batched MMA、新 shape API、任意 dtype 组合或动态负 scale 语义：当前缺口是已有二维组合的覆盖。
- 不重录旧 golden 迁就结果、不放宽容差、不增加性能门或优化形状：本刀只取得正确性证据。
