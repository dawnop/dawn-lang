# 按位与移位运算符 trait 设计

> 状态：**current**。刀 0 已证明 Amount 可以复用现有关联类型；刀 1 交付编译器。
> 刀 2 在 v0.97.0 种子后接入 std 定宽整数；刀 3 接入 Tile 的按位与掩码运算；
> 刀 4 接入 Tile 移位并统一计数掩码语义；刀 5 固化跨层 oracle 与负控，完成终态核账。
> 权威条文见 [spec.md](spec.md) §3.5、§4.3、§11；算术先例见
> [arith-operator-traits-design.md](arith-operator-traits-design.md)，投影纪律见
> [assoc-types-design.md](assoc-types-design.md)。

当前 FlashAttention 读者入口统一为 BF16 输入、F32 状态/scale/输出，见
[读者面设计](flash-attn-bf16-front-design.md)与[实际样例](../site/play-ui/samples/flash_attn.dawn)。
本文原有 f64 展示、调用计数、编译时延及测量说明属于所记实施阶段，不能作为
当前展示或性能声明；泛型算法、数值 helper、host plan 与内部 f64 回归能力保留。

## 落地提交

| 刀 | main 提交 | 交付 |
|---|---|---|
| 0/1 | b604ee8b（#842） | Amount 硬闸通过；七 trait、Int 快路、效果与双后端 ABI |
| 种子 | 5db96875 | v0.97.0 种子，先于 std impl |
| 2 | 3e5649ce（#844） | 七个定宽整数、49 个 impl、删除 42 个旧入口 |
| 3 | 806f07fe（#849） | Tile 资格、位运算、mask select 迁移 |
| 4 | 39dcc4a6（#853） | Tile 移位掩码、解释器与参考、三架构逐位核验 |
| 5 | 本提交 | 持久负控、同一组跨层预期、文档终态 |

合入采用 rebase，故表中是 main 的提交，不是各 PR 开发分支的旧 SHA。

## 形状与边界

| 符号 | trait | 方法 | 右参 |
|---|---|---|---|
| `&` | BitAnd | bit_and | 主体类型 |
| `\|` | BitOr | bit_or | 主体类型 |
| `^` | BitXor | bit_xor | 主体类型 |
| `<<` | Shl | shl | T.ShlAmount |
| `>>` | Shr | shr | T.ShrAmount |
| `>>>` | Ushr | ushr | T.UshrAmount |
| `~` | BitNot | bit_not | 无 |

结果固定为主体类型。七个方法不注入顶层命名空间，各带同名关联效果，默认纯。
新 trait id 从 Len 后追加为 18 至 24，旧 id 不变。七个名字占用 trait 和 effect 声明位置；
同名 type 的既有遮蔽规则不变。只有主体声明模块可以给 prelude trait 写 impl。

每个移位 trait 各声明一个 Amount，每主体每 trait 只有一种右参类型。
Int 的三份 impl 均绑定 Int；用户整数可绑定 Int，设备句柄可绑定同型句柄。
泛型转发的形状为 `fn move[T: Shl](a: T, n: T.ShlAmount) -> T !T.Shl = a << n`。
`T.ShlAmount` 与 `T.ShrAmount` 在泛型体中不同，即使某些具体 impl 恰好绑定同一类型。

投影沿用现有签名许可位置与急切归约；绑定 RHS 不增加投影，impl 子目标仍是主体的真子项。
刀 0 的 scratch 探针覆盖 Int 原生槽、Amount 为 Int 的用户整数、带格式资格 bound 与 ground
效果的参数化句柄、泛型转发、闭包、comptime、LSP 和双后端 ABI。它不作为产品代码提交。

## 检查与降级

具体 Int 保留 XBinary/XUnary，不查见证；泛型实例化到 Int 使用原生字典槽。
非 Int 从左参选见证，缺 bound 或 impl 先报。`& | ^` 以左参类型检查右参，移位先经同一
impl 归约 Amount，再检查右参，错误列出所需 Amount。Float 没有 impl。
opaque 的继承白名单仍只有 Eq、Hash、Ord；按位、移位、取反都要求显式实现。

库类型的外层期望可以下传给左参；Int/Float 期望不下传。同型位运算允许整数字面量向
有类型的一侧让步，不混入 Float 的让步规则；移位的右字面量只按 Amount 定型，不从右向左推断。
`~` 先独立检查操作数，不借外层期望定型 `~0`，也不经过 not 或 Neg。
泛型调用的 Amount 字面量在主体尚未确定时等候，先检查能确定主体的非投影字面量，
再检查依赖它的 Amount；具名实参把计数写在前面也适用。沿现有两轮调用推断定序，
每步仍填入一个实参槽，不新增推断变量或延迟目标队列。
opaque 声明模块内字面量先按表示类型定型的规则继续适用。

trait 路径产出 XCallFn，复用 lower_trait_call 的去虚化、字典转发、闭包捕获与证据传递。
make_prim_slot 按参数位置处理擦除与装箱：Int 的 Amount 是 Int，槽位仍擦除为引用；
关联效果在槽位 ABI 中各占一格，纯 impl 也不能删掉这格。Core lint 的 slot-evidence 检查继续适用。
C/JVM 后端继续只接收已有的原生 CBinary/CUnary，不增加后端专用分派。

## 语义、求值与定位

官方有限位宽整数先取 `k = n & (w - 1)`，负数按补码低位处理；左移只留低 w 位。
`>>` 随主体符号性补位，`>>>` 总补零；取反翻转主体位宽内的位。
这些法则约束语言和官方实现，编译器不证明普通用户 impl 的法则。

两侧按书写顺序各求值一次，无短路。效果记入外层签名，泛型写 !T.BitAnd、!T.Shl 等投影。
运算符沿用 called_bare，运行期不携带具名 API 默认 caller 的精确调用位置。
LSP 的符号 span 不受此代价影响；hover、goto、references 与 rename 继续使用已有的
XCallFn 操作数配对。纯具体 impl 的求值先归约其关联效果；带效果或转发字典的表达式仍拒绝折叠。

## 验收

checker 内联断言守住六个 Int 二元原生节点与一元取反、Amount 归约和泛型效果证据。
checker-corpus 覆盖缺 bound、opaque 内与泛型调用、Float、混型、缺效果、Amount 不符、
不同移位投影、反向定型、方法不注入以及名字冲突。

spike-native 的 bitwise_traits 覆盖七种 Int 泛型槽、用户整数、引用形状的 Count、闭包、
资格字典、效果与操作数顺序、comptime，并与独立写下的期望在两后端及 ASan 下比较。
LSP 内联测试覆盖七个操作符跳转、Amount 参数的 hover、操作数引用和 rename、纯值折叠与效果拒绝。
负控分别强迫 Int 走 trait、把 Amount 当主体、让 opaque 继承 BitAnd、漏传 Shl 效果证据。
具体运行结果随提交的验证记录；本设计不作未测量的性能断言，不增加 CI 步骤或预算。

## 刀 2：定宽整数

七个 std/int 模块由 scripts/fixed-ints/gen.py 统一生成七个纯 impl，三个 Amount 均为 Int。
Int 的七个 prelude 原生槽继续复用刀 1，不另造 std 类型或绕开快路。
先在 Int 中读取表示，再计算并重建主体不变量；有符号窄值的逻辑右移先取低 w 位。
左移通过现有 C uint64_t 路径，最后截位；不新增 C 后端原语或改变 Int 发射。
移位计数始终先按 w 掩码，旋转仍借 Int 的低六位掩码，避免零计数时出现移 64 位。

删除每模块的 and/or/xor/complement/shl/shr 六个公开入口，共 42 个；调用改用运算符，
保留 rotl/rotr、checked_*、转换和 DeviceBits，不留兼容包装。
生成器同时维护旧 fixed_ints 语料和独立的按位 oracle：由 Python 任意精度整数计算预期，
覆盖所有标准主体、边界位型、负计数及整周期计数，比较具体调用、泛型字典、comptime 与 LSP。
C 验证使用 gcc/clang 的 O0/O2 和 UBSan；负控分别破坏窄逻辑右移、计数掩码、
U64 右移及 C 截位，确保对应反例实际失败。

定向实测：8 种主体各 7 个位型、11 个计数、7 个运算，共 4312 个逐值预期，
具体调用、泛型字典及两条 comptime 路径一致；56 行 LSP 求值在正常预算内全部通过。
selfhost 1154 项测试和三个定向 spike-native 语料（含 ASan）通过；
bitwise_fixed 与 int_edges 的 gcc/clang-18 × O0/O2 共 8 组 UBSan 输出吻合独立预期。
四项负控均实际判红，std 变异先重生 stdsrc 再构建各自的变异编译器；详见交付报告。

## 刀 3：Tile 位运算与掩码

增加 TileBitsDtype 与 TileShiftDtype 两个格式资格 trait，纯方法 bits_dtype 与 shift_dtype
分别答 Dtype[D]；前者仅 Bool、I8、I16、I32、Int，后者仅四种有符号整数。
沿 ScalarDtype 模式传资格字典，不写 Tile[I32] 等具体泛型头特化。
四个条件 impl 均约束 D: TileBitsDtype，关联效果固定 !Dev，不从元素转发关联效果。
刀 3 仅声明 TileShiftDtype 及资格见证；刀 4 已补齐三个移位 impl 与计数掩码。

整数 &、|、^ 用 BinaryI，分别记录 andi、ori、xori；Bool 的 &、| 保持既有
select 内核及常量顺序，迁移后既有 mlir 与 tilebc 必须逐字节相同。
~ 为同型全一常量与输入 xori，Bool 用 i1 的 1；不对宿主 SSA 句柄取反。
每次记录用资格见证的 dtype 检查实际操作数，trace 仍执行整数格式白名单和左右 dtype 检查。
形状只沿现有 rank-0 与同 rank 长度 1 的广播，不增加不同 rank 广播。

删除 and_i、or_i、xor_i、and_mask、or_mask 五个公开入口并迁移全部消费者，
包括 in_range 的内部组合；不保留转发。转换、pack/unpack、比较保留；当时保留的具名移位已由刀 4 删除。
tileir 从 0.22.0 升到 0.23.0，遵守 0.x minor 的兼容性边界。

运算符无 at 默认参数，沿算术 called_bare 记录。错误包含英文操作名、操作数来源和
记录边界的用户行，不能承诺运算符自身的精确行列；LSP 的符号 span 不受影响。
负控覆盖 Float 缺资格、Bool/I32 混型、资格与记录 dtype 不符，以及把 mask &
改为 andi 后 golden 必须红。验收比较既有全部 golden，并以 tileref、tileinterp 和
三种架构设备台账核对数值；不作性能断言。

定向实测：tileir 273 项、tileref 31 项测试通过。新增五个独立 golden kernel，
每个运算单独输出一段；四种整数与 mask 各比较 512 lane，另以 typed Int 通道
核对 i64 的完整位型，共 12288 个运算结果，不把大整数转成 Float。
tileinterp-diff 的 178 个案例一致、21 个按既有规则拒绝，无数值不一致；
覆盖清单新增这五个 kernel。sm_86、sm_90、sm_100 的六个新按位案例均逐位一致，
包括 typed i64 的完整位型和未写尾部。225 个 golden 的 JVM/native 文本、字节、
固定版本汇编与反汇编全部通过；全矩阵 324 个工作项与独立覆盖汇总通过。
完整设备台账与最终全集门结果见交付报告。

站点 GPU 页从 tile-golden 的 shell 数组读取变异名称。数组允许同一行放多个裸名称，
站点读取器按空格与制表符拆分并跳过空行，保持数组顺序；仍逐个查找真实执行块，
没有对应执行块继续报错。此修正只影响站点证据展示，不改设备测试程序或摘要规则。

## 刀 4：Tile 移位与计数掩码

三个条件 impl 约束 D: TileShiftDtype，分别绑定 ShlAmount、ShrAmount、UshrAmount
为 Tile[D]，关联效果固定 !Dev。每 lane 的动态计数与主体同 dtype，Bool、U8、浮点
没有资格；资格与实际记录 dtype 一致性、形状及广播沿刀 3 的检查。泛型转发与捕获闭包
复用现有字典及关联效果证据，操作数按书写顺序各求值一次。

记录先以 shift_dtype 见证选定宽度 w，再发同 dtype 的常量 w−1 与 andi，最后发
shli、signed shri 或 unsigned shri。常量和动态计数都保留显式掩码，负数按二补码低位
取 k = n & (w−1)。左移截去高位，不增加溢出假设；>> 补符号，>>> 补零，k=0 保留位型。
运算符仍用 called_bare，英文拒绝落在用户记录边界，不承诺符号自身精确位置。

删除 shl_i、shr_i、shr_u、shli、shri 五个公开入口并迁移全部调用，不留兼容层；
tileir 0.23.0 升为 0.24.0。底层 BinaryI 协议与方言 opcode 保留。tileinterp 的三个
整数移位统一先掩码，删除 shift_ub 分支；tileref 独立按有限位宽计算并重建有符号结果。
解释器的原始记录入口也采用该语义，不能靠旧越界拒绝掩盖设备漏发掩码。

四种整数各增加逐 lane 边界 kernel，覆盖 0、w−1、w、w+1、负计数及最小有符号主体，
同时比较三个移位的独立输出段。i64 另经 typed Int 通道比较完整位型，避免 Float 精度损失。
同一数据由 tileref、tileinterp 和三种架构真实设备比较；设备整轮录制严格串行。
负控分别删除设备掩码、把 signed shri 改为 unsigned、恢复解释器越界拒绝，并验证
Float/Bool 等不合格 dtype、混 dtype Amount 和缺 Dev 的精确拒绝。

逐 kernel 审核所有移位 golden 的新增 andi、SSA 变化及签名属性，其他既有 golden 保持
逐字节一致。flash_attn.map 若受源码行移动影响，以规范命令重录并审核字段。
只使用 emit-labels.txt 中存在的精确标签；不发明 tile golden 标签，不用通配豁免。
本刀不作性能断言，不修改 workflow 或门禁预算。

定向实测：tileir 275 项、tileinterp 182 项、tileref 32 项测试通过，完整 dispatcher 的
JVM 与 C Core lint 通过。tileinterp-diff 的 182 个案例一致、22 个按既有规则拒绝，
无数值不一致；四个新增 shift kernel 均参与比较。额外的 typed i64 案例受解释器既有
Float 存储精度边界拒绝，完整位型另由设备与 Int oracle 比较，不记作解释器数值通过。
原始整数解释器测试独立覆盖四种宽度、极端计数、最小有符号主体及两档 UB 检查。

229 个 golden 的 JVM/native 文本、字节、固定版本汇编与反汇编全部通过；全矩阵
330 个工作项与独立覆盖汇总通过。既有 225 对中仅 rainbow、int_ops、dtype_i16、
dtype_i4 四对因显式掩码变化；撤销已逐条核验的掩码与扩展节点并统一 SSA 后，四个
原程序全文相同，其余 442 个既有文件逐字节不变。新增四对分别使用 7、15、31、63。
flash_attn.map 以规范命令重录，38 个调用和 50 个操作不变，仅源码行号统一后移 9。

sm_86、sm_90、sm_100 的五个新移位案例均逐位一致，每架构核对 7680 个结果与
80 个未写尾部元素，含 typed i64 的 INT_MIN、INT_MAX、超过 2^53 的位型和极端计数。
三本台账整轮严格串行并共用 inputs=06ef9587f9ba；漏掩码与算术右移误用补零两项
设备负控在三架构上都令五个案例明确数值失败。完整台账和最终全集门见交付报告。

## 刀 5：收尾契约

逐条核账以 main 的实际实现为准。将刀 0/1 与刀 2 的八个 scratch 负控移入
`scripts/bitwise-contract` 的持久注册表，由 checker-corpus 执行，预检在任何构建前
验证全部锚点恰好匹配一次。变异编译器必须构建成功；诊断变化、具名测试失败或错误数值
才算负控判红。std 变异先重生 stdsrc，再构建对应编译器，不能借旧嵌入源得到假结果。

沿用 fixed-ints 的独立 Python 整数 oracle，四种有符号宽度的同一组输入与逐项预期
同时交给宿主具体/泛型、comptime、LSP、tileinterp 原始整数求值和 tileref。
后两者在临时包副本中追加测试，不改产品包的公开接口或彼此独立的依赖关系。
尤其 i64 直接比较 Int 位型，不以 Float 缓冲拒绝充作数值通过。原有完整记录程序对拍
与三架构设备台账继续独立守住记录、广播、降低与字节码路径。

定向实测：每种宽度 7 个位型 × 11 个计数 × 7 个运算，四种宽度共 2156 个预期；
tileinterp 在开启和关闭 UB 检查时均逐项相等，tileref 同样通过 28 行测试。
宿主原有语料完全不变，继续覆盖 8 种主体的 4312 个预期与 56 行 LSP 求值。
bitwise_fixed、int_edges 的 gcc/clang-18 × O0/O2 共八组 UBSan 结果吻合，stderr 为空。
八个持久负控均先构建成功，再由对应 checker 断言、诊断或数值判红。
Amount 负控使用显式空 std 清单，只检查 prelude 语料，避免已迁移 std 的加载失败冒充诊断变化。

常量计数折叠本刀不做：tile_shift 只持有 Tile 句柄，常量值由记录 handler 管理；
增加常量查询或跨记录层的传播超出本刀的小优化边界。保留刀 4 已验证的显式 andi，
不改变 golden 或设备输入，三本台账数值与输入摘要均保持原样。不作性能断言。

## 不做的（理由）

1. 不做多 RHS、多参数 trait、关联类型相等约束、隐式转换与 impl 特化，单一 Amount 已表达本项消费者。
2. 不做合并 Bits/FiniteBits、位宽成员或专用计数类型，掩码类型不应被迫实现移位。
3. 不做宿主 Bool 按位、Float 位模式运算或复合赋值，没有本刀消费者。
4. 不在 selfhost 源码中消费窄整数新运算符；种子 v0.97.0 已提供 std 所需 trait。
5. 不增加 Tile 与宿主 Int 的混合移位；显式 consti 和同型设备计数已覆盖本刀。
6. 不扩展 C 的可移植性承诺，原有 Int 掩码及无符号左移发射继续服务此刀。
7. 不开放 U8 tile、I4、FromInt[Tile] 或任意 rank 广播；它们需要独立格式与推断裁决。
8. 不加入 Tile 比较运算符、popcount、checked/unsafe 移位或新原子/bitcast 语义；现有接口各有独立契约。
9. 不改写 SHA-256 或 inflate，没有本项的性能或算法验证；不保留旧具名兼容函数，防止两套表面继续分叉。
10. 不折叠记录期常量计数，原因见刀 5；保留已审计的显式掩码和三本原始台账。
