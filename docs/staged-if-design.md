# staged if：条件协议与共享格子

> 状态：**current**。S0 设计已冻结（`15d5662d`）；S1 实现检查器协议与双后端记录语料；补裁纳入有类型结果槽的值形式。
> S2 包迁移与不变性门、S3 token 分支、S4 设备验收仍待后续刀，权威条文见 [spec.md](spec.md)。

本文冻结 2026-10-22 裁决的 S0/S1 边界。`if` 和 `for` 一样由检查器调用普通库协议，
不在 TAST、Core 或宿主后端引入设备节点。S1 只交付语言协议；tileir 接入、旧消费者迁移和
token 分支分别属于 S2/S3，设备验收属于 S4。本文不作性能断言。

## 1. 表面与条件边界

宿主 `Bool` 始终走既有 `XIf`，求值与产物保持不变。其余非错误、非 bottom 条件若实现
`StagedCond`，改写成一次 `staged_if` 调用；条件先于新开格子恰好求值一次，两臂成为无参闭包。
Unit 语句无 `else` 补空臂，值形式必须有 `else`；`else if` 是 else 内的嵌套条件，后一个条件留在该臂内求值。
两臂具有独立词法作用域，遮蔽按符号身份判断。

语言不理解 Tile、设备或 Dev。未来 tileir 只接受 `dtype=i1, shape=[]` 的严格 rank-0 条件，
不是单元素形状 `[1]`。类型不携带 rank，因此记录期仍须检查。逐 lane 条件继续用 `select`
或访存 `mask:`；不隐式归约、不自动 any/all、不自动 if-conversion。

## 2. 类型与效果

协议形状（声明示意，prelude 由编译器提供）：

```text
trait StagedCond[C] {
  effect StagedCond = !()
  fn staged_if(c: C,
    on_true: fn() -> Unit !C.StagedCond,
    on_false: fn() -> Unit !C.StagedCond) -> Unit !C.StagedCond
}
```

id 从既有表尾追加为 25，不重编号；`injects: false`，方法名不进入函数命名空间，
不可 derive，不提供 Bool impl，不继承 opaque 底层 impl。trait 与 effect 声明位置保留该名字。
泛型 `[C: StagedCond]` 使用现有 witness、字典及关联效果证据。两臂实际效果（包括生成的
get/set）必须包含在 `C.StagedCond` 内；open/writeback 在外层按普通规则计效果。

S2 不得为此放开具体泛型头特化。`impl StagedCond[Tile[Bool]]` 不合法，应由包级
`TileCondDtype[D]` 的非空纯见证方法限定 Bool，再写条件 impl；记录器仍核实 i1 与 rank-0。

## 3. 格子与合流

沿用 staged for 的首次符号解析建格子，不增加自由名 AST 预扫描。一个 if 的两臂共享
`orig -> StagedCell` 注册表；第二臂继承第一臂已建身份并补齐。每臂独立收集捕获、效果和局部名。
外层 var 无论读写都要求 StagedVar。新格子按 var 声明序打开，if 后同序读回；嵌套 if/for
复用最外层负责打开的格子，不重复 open/writeback。普通 lambda、with、handler 臂仍不获授权。

设 V 为两臂读写外层 var 的并集，W 为记录库实际执行两臂时的写集合并集。
检查器负责 V 的资格和身份，库负责 W 的数据结果；不能把静态赋值出现当作实际记录写集合。

| 使用方式 | 格子 | 库协议 |
|---|---|---|
| 不提及 | 不新建 | 无结果 |
| 只读 | open 或复用 | 无写结果，读入口值 |
| 只在一臂写 | 两臂同一身份 | 未写臂 yield 原值 |
| 两臂写 | 两臂同一身份 | 同一槽位分别 yield 末值 |
| 写回原句柄 | 仍记写 | 不按值相同删除携带 |
| 臂内声明的 var | 臂局部 | 不进入外层携带集合 |

每臂从相同入口状态记录；then 的试跑末值不能泄漏到 else。cell 创建序稳定，结果槽遵循
创建序；新 open 按声明序。for 内 if、if 内 for 和 if 内 if 都复用外层身份；包是否支持
这些区域组合由库自己的记录器决定，S1 不宣称 tileir 已支持 if 内循环或访存。

## 4. 值形式、结果槽与跳转

10-22 补裁撤销 Unit 限制。值形式必须有 else，两臂检查成同一 T，外层期望传给两臂；
没有外层期望时先检查自足的臂，再给需要上下文的臂传入 T，最后仍按源码顺序生成闭包。
Unit 语句继续原无结果路径；非 Unit 尾值不能静默丢弃。宿主 Bool 的值形式仍走原 XIf。

| 结果槽形状 | 可表达性与代价 | 选择 |
|---|---|---|
| 新 prelude `StagedResult[T]`，关联 Slot，open/set/get | 三个普通单参数 trait 方法；Slot 只属于结果类型，open 无值实参，由检查器在已知 T 处直接解 witness；可把未赋值槽与已有初始化 carry 区分 | 采用 |
| 给 StagedVar 增加无初值 open | 同样能用已有 Cell 表达，但所有既有 impl 都要处理未初始化状态，普通 var_get/var_set 与结果的确定赋值及合流读混在同一协议 | 不采用；不是兼容性理由，而是状态纪律不同 |

```text
trait StagedResult[T] {
  type Slot
  effect StagedResult = !()
  fn result_open() -> T.Slot !T.StagedResult
  fn result_set(s: T.Slot, v: T) -> Unit !T.StagedResult
  fn result_get(s: T.Slot) -> T !T.StagedResult
}
```

StagedResult 的 id 追加为 26，方法不注入、不可 derive，同名效果默认纯；不提供宿主标量的
内置 impl，不继承 opaque 底层 impl。结果 T 的协议与条件 C 独立，因此同一种条件可在不同
调用处产生不同 T。既不修改 StagedCond 的 Unit 闭包 ABI，也不添加泛型 trait 方法、HKT、
元组 trait、unsafe 或新的 Core 节点。普通 trait 的空 Option 槽声明/impl 探针已通过现有编译器，
新 prelude 的零参数 open 也已在 JVM/native 记录库与 ASan 对拍中通过；硬闸未触发。
泛型结果的效果仍必须包含在条件协议行中；两个独立投影不自动相等，与 staged for 泛型携带的
既有边界相同，不为绕过效果检查添加新机制。

检查器先检查并统一两臂，再创建用户不可命名的空槽，给两个生成闭包的每个正常出口各包一层
result_set。不能先执行任何一臂取得初值；无 else、臂尾 Unit 与 T 不同型都不能提供结果。
slot 只进入这两个生成闭包的 captures，不进用户词法 scope；result_get 只能位于 staged_if
返回之后。因此源码不能在合流前读出或传出这个槽，也不能通过绑定中的变量自引用绕过。
跨臂 return/?/break/continue 仍拒绝，panic 等不返回路径不能到达结果读出。

result_set 的效果必须包含在 C.StagedCond 内；result_open/get 在外层计 T.StagedResult 效果。
记录库须分别保存两臂对同一空槽的写，确认两臂均初始化之后才能将该槽标为 ready；
result_get 对尚未 merge 的槽拒绝。库若保存回调或漏跑一臂，就是违反协议，不能得到合法结果。
S2 中 Tile 结果分别校验 dtype/shape 并作为 if 的 yield 结果，不广播、不提升格式，
宿主 Int/Float 没有默认 StagedResult，不能冒充设备结果。

`break`、`continue`、`return`、`?` 不得越过 staged 条件臂边界，报文点名 staged if。
臂内新建的宿主循环仍可局部 break/continue，局部函数或普通 lambda 自己的 return 不受影响。
不向 loop stack 添加虚假条件循环；授权的 staged 种类与实际跳转目标分别记录。

## 5. 诊断、位置与语言服务

staged 条件自身的结果类型、效果与跨臂边界诊断保留用户 if 位置，生成调用的名字位置指向 if；
生成 get/set 没有假造的用户调用名。外层 var 无 StagedVar 的诊断包含类型和协议名，只读也拒绝。
不支持的条件仍给 Bool 条件类型错误。普通闭包捕获继续指出实际闭包边界。
LSP 将改写块还原为条件和两个用户臂；cell 符号沿用原 var 声明位置，使 hover、goto、
references、rename 和 semantic tokens 都覆盖两臂，内部绑定不泄漏给用户。

## 6. S3 token 方案（本刀不实现）

if begin 保存入口 token；true 与 false 都从同一入口起链。切到 else 时恢复 token 和
carry 入口状态、过滤不可见缓存，但正式记录不回退句柄计数，两个区域的句柄必须唯一。
完整 trial 才恢复 next、tok、carries、缓存、调用来源等全部快照状态。

仅当某臂推进链时，if 追加一个私有末尾 token 结果，分别 yield then/else 末 token；未推进
臂 yield 入口 token。if 后使用该结果，两臂均未推进则保持旧纯 if 字节，不添槽。
只读 In load 仍挂入口 token 0 而不推进；Shared 读、store、原子等沿用既有串链规则。
token 不装入用户 Carry，需显式结果元数据，不能猜最后一项总是 token。

JoinToks 不能充当 phi：互斥区域中的两个末 token 不会同时存在。写集合保守取两臂并集，
审计 writes_of、tok_step 与 fork 冲突，未知别名保守拒绝；同地址的互斥两臂写本身合法。
访存、循环、join、atomic、print、fence 等所有入口及祖先 reduce/scan 纯区域禁令逐个核对。
lower、可见性、bytecode、解释器同步验型；沿用现有 if 结果与 token 类型，不新添 opcode。

## 7. S2 不变性判据

先冻结已合入按位 3/4 的新基线与工具版本，再把 foldif（含 foldif_debug）与 carry_extent
迁成语法糖；不反转条件、不改常量发射位置或运算顺序。必须同时满足：

1. 操作树的 If 个数、条件生产者、两臂次序、结果数量/顺序、Yield、循环携带、dtype/shape
   及 token 操作数一致。
2. foldif 与 carry_extent 的 MLIR/bytecode 逐字节相等；foldif_debug 的 MLIR/bytecode、
   disasm、lines 同样相等，不以源码移行豁免，不重录旧 golden。
3. JVM/native 记录产物一致，全部旧 tile golden 无差异；调用溯源的合理变化不得改变数值 IR。
4. 循环内 best/total 顺序不变，未写臂 yield 入口值；foldif 两个 grid block 覆盖两臂。
5. 通过后才能进入 S3；新增带效果 if 可添 token 槽，旧纯 if 仍须零差异。

## 8. 验证与交付边界

S1 用不依赖 tileir 的普通记录库实现三个协议，固定双臂入口、读写、开放、合流及写回记录，
JVM/native/ASan 对拍。checker 逐条钉住缺 impl、只读 var、缺 else、不同型结果、跳转、捕获和效果诊断。
负控须先证明红：Bool 强走 trait、两臂独建或交换 cell、重复条件、删只读检查、漏报或超出效果；追加缺臂赋值、提前执行、合流前逃逸、不同型结果和宿主值冒充结果。另以宿主 Bool 的 TAST/Core/emit 基线比较守住原路径。
所有改动逐文件问 gatemap，跑锚点预检、完整门禁、文档与格式检查。S2–S4 的包/设备验收
不记为本刀已通过；种子发布推进之后才允许在 selfhost/std 或包消费者里使用新语法。

## 不做的（理由）

- 逐 lane if、自动 any/all、设备 Bool 转宿主 Bool：不同执行语义，继续显式 select/mask。
- staged while 与隐式非局部退出：需要设备控制流协议，保留显式 d_loop/d_return_if。
- 放开普通 var 闭包捕获：重复记录与逃逸会破坏现有规则。
- 检查器线程化异构元组：格子与库 yield 已有明确分工，不增加变长泛型或 Core 节点。
- 自动纯 if/select 互换、无条件 token 槽：破坏语义或旧 IR 不变性审计点。
- 完整 alias-set 重写与无实测性能承诺：超出本刀正确性范围。
