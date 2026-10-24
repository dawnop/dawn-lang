# FlashAttention 读者面 BF16/F32

> 状态：**current**；基线为 S2 合入的 b1c97abab8f198e6862544986b46a04f043e3772。

## 设计契约

读者当前只见 BF16 输入、F32 状态、scale 和输出。共享 `[D,A]` 主体、
FaNumerics、fa_exp/fa_divide、工厂、typed recorder 与 host plan 保留；
f64 录制及其 reference、golden 和设备负控继续作为内部回归实例。

新增 flash_attn_bf16_demo，M=N=64、D=32、heads=1、bq=32、bk=16，
无 entry hints。三维 cells 保留 S2 的 squeeze=[0]、head axis 2 与完整 grid
[2,1,1]；四个键块验证 online softmax。生产选择器、tiles 和 hints 不变。
继承 golden 逐字节不变，只新增 demo 的文本和字节码。

样例先展示共享算法，再给小布局和运行，支持定义同文件全文 pin。独立
自然底 plain attention 使用原 scale；启动参数仅换底一次并舍入为 F32。
整数/8 输入可精确表示为 BF16。逐元素有限性与误差检查必须真正 panic。
教学容差为 2^-8*max|v|+1e-5、rtol=1e-5。本夹具 atol=0.00245140625，
CPU 解释器和设备的最大绝对误差均约为 0.00045835；漏乘或重复乘
log2(e) 的设备误差分别约为 0.04392 和 0.06501，均超过该界。
现有严格策略容差不变，继续按 BF16 概率收窄参考和结构 oracle 验证。

静态与动态来源读取真实 BF16 constructor，工厂逐参原样转发；未知表达式
仍拒绝。BF16 的 p.to(dt) 必须对应真实 nearest-even F32→BF16 指令，
tile_shape 仍保留零 IR 来源。源码区间覆盖实际 helper 定义与调用。

历史 P4-c 展示表原字节迁至 scripts/flash-config/p4c-display.tsv，
检查器继续核对全部十二项。历史选择、测量、A2 身份及 matmul 资产不改。
页面不把历史时间当成当前布局的性能。

## 验收

新录制实测为 45 个静态调用、56 个操作、68 行 IR 和 1053 字节 bytecode。
正常与具名负控覆盖数值、策略、输出、来源、闭合依赖和答案 key。
doc-check 先构建样例再注入 NaN、Inf 和错误值，要求运行时以具名 panic
失败；只打印检查结果不能满足此门。
真实样例检查 Run/C/JVM/Tile、无答案冷请求、无害注释 miss 和隔离 warm。
最终 inputs 依次录制 sm100、sm90、sm86 三账，只追加真实 source 收据；
完整外部门包含 tree-policy 的 publish 自测，独立验证 complete=true。
不发布 evidence，由协调者接手。生产部署和后续 live-check 另行执行。

## 不做的（理由）

不删除 dtype 表达能力，不扩尾块、M≠N、GQA、六参或公共来源 API。
不调优，不改性能容差，不改 matmul，不重写历史，不部署、不发版。
