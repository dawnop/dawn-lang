# 按位与移位运算符 trait 设计

> 状态：**current**。刀 0 已证明 Amount 可以复用现有关联类型；刀 1 交付编译器。
> std 定宽整数和设备库 impl 尚未交付，须等待编译器发版、推进种子后分刀迁移。
> 权威条文见 [spec.md](spec.md) §3.5、§4.3、§11；算术先例见
> [arith-operator-traits-design.md](arith-operator-traits-design.md)，投影纪律见
> [assoc-types-design.md](assoc-types-design.md)。

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

## 不做的（理由）

1. 不做多 RHS、多参数 trait、关联类型相等约束、隐式转换与 impl 特化，单一 Amount 已表达本项消费者。
2. 不做合并 Bits/FiniteBits、位宽成员或专用计数类型，掩码类型不应被迫实现移位。
3. 不做宿主 Bool 按位、Float 位模式运算或复合赋值，没有本刀消费者。
4. 不修改 std/int 的 impl 或具名函数，旧种子必须继续编译 bootstrap closure。
5. 不修改 GPU 库、解释器或参考实现，其设备计数掩码和 API 迁移另刀交付。
6. 不扩展 C 的可移植性承诺，原有 Int 掩码及无符号左移发射继续服务此刀。
