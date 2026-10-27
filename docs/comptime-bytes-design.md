# comptime Bytes 与常量冻结边界

> 状态：**current** —— 2026-10-27，依据 G01 裁决的实现设计与分刀记录；下列未完成项不代表当前已支持。

## 问题与语义

`std/bytes` 的纯函数目前不能参与常量计算，连最终返回 `Int` 的字节长度也受阻。
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
不按 std 函数名截获算法，SHA 与 CRC 的运行时和编译期调用同一份 Dawn 实现。

## 两后端表示

JVM 选定 ASCII hex 一种运输编码，原始字节每块至多 16 KiB。runtime 提供单一 literal
decoder，静态字段在初始化时构造一次 byte[]。必要时以 helper/holder 分片，避免每字节
BASTORE、单方法 65,535 字节上限及常量池上限；验收直接检查 classfile。

native 选静态 payload 加 runtime 公共 literal helper 管理的 immortal 描述对象，零长度
使用合法非零长 C 数组声明。对象头初始化留在 runtime，emitter 不复制 RC 魔数。
两后端共享内容而非对象布局。常量的 FFI 行为沿用现有契约。

## 预算提案与验收

待边界测试验证的默认值：单 blob 1 MiB、每模块结果 16 MiB、每 fold 逻辑分配 64 MiB；
另设 LSP 会话总预算与较小 hover 预算。计费用逻辑字节和节点，不依赖宿主对象头、共享或
分配器。分配前检查长度与加乘溢出；扫描、复制、冻结与结果累积都须计费。超限在源位置
给出请求量与限额诊断，不能依靠 OOM 或 classfile 报错。定值与配置方式在 K3 回填。

固定验收包括空、00/7f/80/ff、全 256 字节、非法与非 BMP UTF-8、clamping、嵌套与
opaque Bytes、跨模块引用、Buf 4095/4096/4097 与旧值分叉、整数及浮点端序和特殊值。
SHA256("abc") 的独立预期为
`ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad`；
CRC32("123456789") 为 `0xCBF43926`。另测 SHA padding 55/56/63/64/65、编码块边界、
大于 65,535 字节、多常量聚合、小配置 N−1/N/N+1、低 fuel 与 hover 截断。
禁止 IO、时钟、随机、extern、Cursor 逃逸/渲染、函数逃逸、handler cell、ctl、HAMT 的负例
保留。JVM 与 native 编译器各自折叠并执行产物，避免只验证一个宿主的求值。

## 刀序与当前状态

一个主题、一个 PR，每刀一个提交；K0–K4 完成后才宣称 G01 交付。

| 刀 | 范围 | 状态 |
|---|---|---|
| K0 | 后端无关规则、trait 文档纠正、现状负例 | `f8b4b9f9`；1183 项单元测试及文档、锚点子集通过 |
| K1 | EvalValue/ConstValue 与冻结边界 | `9876ccfb`；1185 项单元测试通过；冻结逐节点计步 |
| K2 | Bytes 与 Array 完整构造路径 | 1186 项单元测试及 builtin 合约通过；原版 SHA、hex、Base64 已可折叠 |
| K3 | 双后端产物、预算、预览边界 | 待做 |
| K4 | 生产 const、契约、文档与干净自举闭环 | 待做 |

## 不做的（理由）

不交付 Map/Set 常量、文件 embed、完整 tile 编码与 Unicode 大表迁移；它们需要独立的
逻辑表示、输入依赖或成本裁决。不会加入 Serialize trait、comptime IO、宿主临时程序、
`is_comptime` 分支、专用 SHA、Bytes 伪装 List/String、旧 CValue 别名或两种 literal codec。
本文不声称性能收益；预算数字是待验证的限制提案，不是性能测量。
