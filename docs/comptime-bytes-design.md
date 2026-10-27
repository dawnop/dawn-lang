# comptime Bytes 与常量冻结边界

> 状态：**current** —— 2026-10-27，依据 G01 裁决的实现设计与分刀记录。

## 问题与语义

K0 基线中，`std/bytes` 的纯函数不能参与常量计算，连最终返回 `Int` 的字节长度也受阻。
`Buf` 通过值语义 `Array` 保存块与尾部，所以只支持 UTF-8、索引与切片不能让
`from_hex`、Base64 和 `packages/sha2` 的原有算法组合起来。

comptime 在隔离上下文执行普通纯 Dawn 表达式。结果必须有编译器定义的有限、封闭的
结构化字面量表示，只描述语言值，不携带宿主地址、资源身份、可变外部状态或后端私有度量。
工作域允许 closure、dictionary、cursor 与值语义 Array；结果域仅含标量、Bytes 及其
List、tuple、record、ADT、opaque 递归组合。Bytes 表示长度与 0..255 序列，没有编码前提。
用户 trait 不决定字面量表示。K0 记录原有拒绝边界；K2 支持 Bytes 工作值，K3 打开 Bytes 结果域。

## 求值与冻结

拆除混合的 `CValue`，以 `EvalValue` 承载解释器工作值，以 `ConstValue` 承载后端可见的
封闭树。`freeze_const` 在每个 const/comptime 的边界检查并转换，失败携带字段或元素路径。
常量侧表只保存 `ConstValue`，解释器再次读取时显式还原工作值。两个 emitter 不接受工作值。
冻结逐节点计步并检查深度；K3 增加大小预算，不把错误推迟到 codegen。
递归 ADT 的类型参数在循环捷径之前检查，覆盖非正则递归和 phantom 参数。

Bytes 叶子直接持有紧凑的不可变 Bytes，不将每个字节装箱为 Int。解释器实现十个字节原语、
拼接、比较、渲染与 Array 操作及 List 转换；`array_steal` 按现有值语义契约读取。
旧 Array 与 Buf 分叉后必须仍能读取，不能用宿主可变共享模拟。保持 HAMT 与 IO 防线。
补充核实：`std/cursor.Show` 原本返回固定 `<cursor>`，可安全折叠；拒绝的是位置结果与
直接度量渲染。保留这个既有纯函数行为，不按 std 函数名截获摘要。
不按 std 函数名截获算法，SHA 与 CRC 的运行时和编译期调用同一份 Dawn 实现。

## 两后端表示

JVM 选定 ASCII hex 一种运输编码，原始字节每块至多 16 KiB。runtime 提供单一 literal
decoder，静态字段在初始化时构造一次 byte[]。必要时以 helper/holder 分片，避免每字节
BASTORE、单方法 65,535 字节上限及常量池上限；验收直接检查 classfile。

native 沿用按常量 key 缓存的惰性 builder，从静态 ASCII hex 分块解码一次，调用 runtime
公共 `dawn_bytes_literal`。helper 通过普通 Bytes 构造器取得独占 payload，再经
`dawn_immortal` 脱离 RC；空值也是合法的普通零长 Bytes。不改普通 Bytes 的 owned-payload
契约，也不把静态指针的释放/COW 例外扩散到 FFI。代价是首次使用分配描述对象与 payload，
并作一次线性解码；这里不宣称零分配或零复制。没有第二种运输编码。

JVM 按内容去重 blob，每 64 项一个 holder，单项装载方法只建立固定数量的编码块。
常量字段也按 64 项分 holder；List 每 64 个元素一个 builder，结构 builder 按直接引用量
分配常量池空间，避免很多短 Bytes 把单个类的池或初始化方法撑爆。native 按已有常量 key
复用 builder；不同 key 的相同内容不承诺物理去重。两后端共享内容而非对象布局，FFI
行为沿用现有契约。Float 常量的 native NaN 重建保留原始 bits，保证宽 8 的再打包不丢 payload。

## 预算与验收

K3 定值采用保守逻辑上限，不是性能最优点：

| 上下文 | 单 Bytes | 模块结果 | fold 累计逻辑分配 | 所有模块保留结果 |
|---|---:|---:|---:|---:|
| 编译 | 1 MiB | 16 MiB | 64 MiB | 64 MiB |
| LSP 分析 | 256 KiB | 4 MiB | 8 MiB | 16 MiB |
| hover | 16 KiB | 64 KiB | 1 MiB | 2 MiB |

Core 步与结构槽计 16 个逻辑字节，Bytes 的 payload 按实际长度计；冻结每节点计 16，
String 再计 UTF-8 字节数、Bytes 再计长度。结果深度上限 256，每构造器字段上限 4096。
工作分配与结果保留是两套账；后者跨模块累加，物理共享或去重不抵扣重复侧表结果。
LSP 会话同时累计独立文档、各工作区诊断程序与引用程序，共享 std 只计一次。
打开 std 源文件产生的新侧表结果另行计费，不能因它沿用 std 的函数世界而漏账。
重建只释放被替换程序的额度，关闭文档或工作区释放相应额度；额度改变即清除该分析
owner 的模块 memo，防止旧的成功折叠绕过新额度。同一块结果侧表项替换也先释放旧值。
模块 memo 还记录进入模块时已保留的结果大小；有折叠结果或诊断的模块在这个输入改变时
重算，避免前置模块增大后复用旧额度下的成功，也允许前置结果缩小后解除旧的拒绝。
读取冻结树也为重建工作节点计费。扫描扣 fuel；长度加乘和额度用减法比较，分配前检查。
大小额度首版固定，`--comptime-fuel` 只调整步数，编译器选项允许测试降限。
超限携带源位置、请求量与限额/余量，不回退为运行时计算。

已用降低的配置测单 blob 3/4/5、模块 39/40/41 字节、分配 31/32/33 字节及跨模块
会话保留边界；1 MiB blob、130 个小常量、5000 个嵌套 Bytes 的两后端产物均已逐值验证，
206 个 classfile 全部链接与访问检查通过，native 的 ASan 检查通过。数字是验收样本，
不是性能数据。K4 再把固定向量与负控接入常驻门禁。

固定验收包括空、00/7f/80/ff、全 256 字节、非法与非 BMP UTF-8、clamping、嵌套与
opaque Bytes、跨模块引用、Buf 4095/4096/4097 与旧值分叉、整数及浮点端序和特殊值。
SHA256("abc") 的独立预期为
`ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`；
CRC32("123456789") 为 `0xCBF43926`。另测 SHA padding 55/56/63/64/65、编码块边界、
大于 65,535 字节、多常量聚合、小配置 N−1/N/N+1、低 fuel 与 hover 截断。
禁止 IO、时钟、随机、extern、Cursor 逃逸/度量渲染、函数逃逸、handler cell、ctl、HAMT 的负例
保留。JVM 与 native 编译器各自折叠并执行产物，避免只验证一个宿主的求值。

## 刀序与当前状态

一个主题、一个 PR，每刀一个提交；K0–K4 完成后才宣称 G01 交付。

| 刀 | 范围 | 状态 |
|---|---|---|
| K0 | 后端无关规则、trait 文档纠正、现状负例 | `f8b4b9f9`；1183 项单元测试及文档、锚点子集通过 |
| K1 | EvalValue/ConstValue 与冻结边界 | `9876ccfb`；1185 项单元测试通过；冻结逐节点计步 |
| K2 | Bytes 与 Array 完整构造路径 | `13356888`；1186 项单元测试及 builtin 合约通过；原版 SHA、hex、Base64 已可折叠 |
| K3 | 双后端产物、预算、预览边界 | `e82116cb`；1191 项单元测试、206 个 classfile 与 native ASan 通过 |
| K4 | 生产 const、契约、文档与干净自举闭环 | 真实 CRC/SHA/协议示例、双宿主合约与会话预算验收已接入既有门禁 |

K4 的公开合约用 Python 的整数/IEEE 向量与 hashlib 生成独立预期，检查 212 个
classfile、native ASan，以及可编译的分配护栏移除与字节载荷置空负控；native 编译器
自行折叠同一批值与拒绝用例。生产示例生成 1024 字节 CRC 表，并直接调用原包的
CRC、SHA 实现。没有修改这些算法或将函数名作为解释器捷径。

常量树没有跨进程的持久序列化缓存。分析 memo 属于固定源码/选项 owner，额度变化
另行失效；工具链 jar 沿用 `bin/dawn` 的 source/input/bootstrap 内容身份，包含编译器
源与生成的 runtime 源。由种子清洁重建和固定点验证覆盖新表示，无旧格式兼容分支。

## 不做的（理由）

不交付 Map/Set 常量、文件 embed、完整 tile 编码与 Unicode 大表迁移；它们需要独立的
逻辑表示、输入依赖或成本裁决。不会加入 Serialize trait、comptime IO、宿主临时程序、
`is_comptime` 分支、专用 SHA、Bytes 伪装 List/String、旧 CValue 别名或两种 literal codec。
本文不声称性能收益；预算是经边界用例验证的保守限制，不是性能测量。
