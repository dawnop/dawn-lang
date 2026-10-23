# staged if：条件协议与共享格子

> 状态：**current**。S0–S4 已落地：StagedCond/StagedResult、共享格子、Tile 值结果、条件访存与循环、token 合流及最终验收。
> 权威条文见 [spec.md](spec.md) §4.6；逐项承诺与覆盖见第 8 节，最终不做清单见文末。

本文记录 2026-10-22 裁决及值形式补裁的最终实现。`if` 和 `for` 一样由检查器调用普通库协议，
不在 TAST、Core 或宿主后端引入设备节点。S1 交付语言协议，S2 接入 Tile 与迁移旧消费者，
S3 接通 token 分支，S4 以最终输入重跑负控、三架构设备台账与完整门禁。本文不作性能断言。

## 1. 表面与条件边界

宿主 `Bool` 始终走既有 `XIf`，求值与产物保持不变。其余非错误、非 bottom 条件若实现
`StagedCond`，改写成一次 `staged_if` 调用；条件先于新开格子恰好求值一次，两臂成为无参闭包。
Unit 语句无 `else` 补空臂，值形式必须有 `else`；`else if` 是 else 内的嵌套条件，后一个条件留在该臂内求值。
两臂具有独立词法作用域，遮蔽按符号身份判断。

语言不理解 Tile、设备或 Dev。tileir 的 S2 实现只接受 `dtype=i1, shape=[]` 的严格 rank-0 条件，
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

包实现没有为此放开具体泛型头特化。`impl StagedCond[Tile[Bool]]` 不合法，应由包级
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

## 6. S2/S3 包接入与 token 合流

S2 增加只给 Bool 的 `TileCondDtype` 资格，让条件 impl 与显式 `d_if` 共用私有
`if_rec`。两者仍有各自的真实组合用途，不增加弃用包装。资格方法返回 `Dtype[D]`，
实现先核实 i1，记录器仍用 `check_rank0` 核实实际条件行。trait 没有 caller 默认值，
沿用 `called_bare` 与 `user_body` 的来源纪律，错误至少指向用户 trace 边界行。

迁移 foldif、foldif_debug 与 carry_extent 后，先通过第 7 节不变性门，再接值形式。
未修改、重录任何既有 MLIR/tilebc/debug golden。Carry 的次序与纯 if 的 token 状态不变。

`StagedResult[Tile[D]]` 的关联 Slot 是独立 `ResultSlot[D]`，不是 Carry 的未初始化哨兵。
记录器保存 `Option[Int]`、ready 和写次数；完整 trial 快照包含这份状态。每臂 trial 只收集
入口已存在、尚未完成而在本臂写过的槽，嵌套 if 不会提前合并父槽。两臂写集合按创建序取并集。
正式 then 结束后收集结果，切 else 前清空这些槽；未赋值即拒绝，不能复用 then 值冒充 else。
用户 carry 的 yields 在前，结果槽在后；`t_if_end` 对两臂实际 dtype/shape 逐项验相等，
不广播、不提升。回填 Carry 后才把结果槽标为 ready，result_get 在这之前拒绝。
七个新增 Dev 操作构成破坏性 handler 协议，外部 handler 必须实现，不保留兼容层。

新增 staged_unit、staged_value（含嵌套结果）、staged_nested、staged_one，分别覆盖双臂 Unit、
值、循环共享格子、单臂写；独立参考使用闭式结果，不复制 recorder 的状态算法。每例四个 block
覆盖不同选择，额外输出尾部保持哨兵。S2 阶段曾拒绝 token 区域；S3 已撤销这项阶段限制，最终边界如下。

S3 已按以下规则落地：

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

S3 在 recorder 的区域帧保存入口 token 与 then 末 token；正式切臂只恢复入口 token，
不回滚句柄分配。已有缓存的 visible 检查拒绝复用兄弟区域的常量、广播、cell/sub view。
用户 carry 与结果槽仍由 if_rec 恢复，完整 trial 继续恢复全部状态。

区域 token 结果另有 recorder 私有映射「结果句柄 → 入口 token」，并纳入 Snap；for、loop
只有保留 token 槽时登记，if 只有任一臂推进时登记。fork 分析据此识别区域 token，
不得把无 token 区域的末数据结果当成 token。If 的写集合取两臂并集；并行 fork 的链之间
若可能写同一参数的重叠区间、未知地址或未知目标则拒绝。互斥 if 两臂写同一地址合法。

lower_if 除数量外还比较两个完整 yield 类型列表，覆盖 token/tile 及 dtype/shape。
新 golden 固定条件 load/store、if 内 for/atomic、不对称访存和嵌套 if，纯分支旧文件不重录。
负控分别破坏合流、以 JoinToks 代替结果、漏掉条件写冲突和泄漏另一臂写；必须成功构建后
由结构、golden 或数值断言证红。设备用独立 tileref 与 tileinterp 对拍，三架构整轮串行。

已新增 staged_load、staged_store、staged_for、staged_atomic、staged_asym、staged_effect_nested。
每个新 cubin 都用上传数据分别命中 true/false，覆盖条件读写、原子旧值、零/一/多轮循环和嵌套条件。
六例在 sm_100、sm_90、本机 sm_86 都与 tileref 逐位一致；解释器明确拒绝原子，其余新例一致，
不将拒绝记作数值通过。完整 tile golden 352 项全通过，470 个旧产物未改。


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

## 8. 最终承诺与覆盖

下表按最终实现列出正控与负控。`kernels.dawn` 均指 `scripts/tile-golden/kernels.dawn`；
设备对拍由 `scripts/tile-gpu-diff/run.sh` 驱动，参考在 `packages/tileref`，解释器比较在
`scripts/tileinterp-diff/run.sh`。断言失败或解释器拒绝不能记作设备数值通过。

| 承诺 | 覆盖位置与判据 |
|---|---|
| 宿主 Bool 原路径、条件只求值一次 | checker 的 `host Bool if retains XIf`；`scripts/spike-native/staged_if` 手写记录；`bool-trait`、`double-condition` 负控 |
| Bool 格式资格、严格 rank-0 | `staged-if-rejected.dawn` 的 Unit/值条件；`kernels.dawn` 的 `staged_if_checks` 同时拒绝两种形式的 `[1]`，核对用户记录边界；`staged-rank-accepted` |
| 两臂共享身份、声明序、单臂原值、嵌套复用 | checker 的 canonical cells 测试；`staged_unit/value/nested/one` golden、设备与解释器；`separate-cells`、`swap-cells` |
| 无初值结果、两臂赋值、不得提前执行或逃逸 | checker 的 hidden slot 测试与诊断 corpus；`staged_if_checks`；`result-one-arm/eager/escape`、`staged-one-arm-accepted/eager-arm` |
| 同类型、双向期望、同 dtype/shape、拒宿主冒充 | checker corpus、spike 的两种字面量推断；`s2_result_case`；`result-mismatch/host`、`staged-dtype-accepted` |
| 效果、只读 var 资格、闭包边界和非局部跳转 | `scripts/checker-corpus/cases/staged_if` 的有序文案、span、hint；`readonly-capture`、`excess-effect`、`missing-effect`；局部跳转正控 |
| LSP 对回用户条件和两臂、隐藏槽不泄漏 | `selfhost/src/lsp/server.dawn` 的 navigation/references/rename/tokens staged if 测试 |
| 旧纯分支与 debug 零差异、不无条件增 token | `foldif`、`foldif_debug`、`carry_extent` 原 MLIR/tilebc/disasm/lines；`staged-invariance`；prog 的只读分支测试 |
| 两臂从入口起链，经结果合流，不用 JoinToks | prog 的 `both conditional store arms`；`staged-token-checks`；`staged-token-unmerged/join` |
| 条件访存、原子、if 内 for、嵌套与单臂效果 | `staged_load/store/for/atomic/asym/effect_nested` 六对 golden；同一 cubin 的 true/false 上传数据在三架构与独立参考逐位比较 |
| fork 写集合保守并集、未知目标冲突、分离正控 | prog 的 conditional fork 与 unknown target 测试；`staged-fork-accepted`；`staged-write-leaks` 的 golden 与 false 输入参考 |
| 区域 token 显式元数据、trial 全恢复、缓存可见性 | prog 的 `data-only and zero-result regions`、`branch views stay scoped`；嵌套 golden；重复 trace 与三架构对拍 |
| lower 完整 yield 类型、祖先纯区域禁令 | lower 的 `identical complete types`；prog 的 reduction 内条件访存拒绝；既有 reduce/scan 边界测试 |
| 不支持的控制流明确拒绝 | checker corpus 的非 StagedCond 条件与 staged while；Tile fixture 的格式资格与 staged while；rank 检查提示实际类型 |

S1 的十二项有效负控在最终源码上同时取得 JVM/native 判词；原“全部非 Unit 必须拒绝”控制
已被值形式补裁撤销，不再是有效承诺。S2 五项持久变异与宿主值控制、S3 四项持久变异均重跑；
必须先成功构建，再按各自指定断言、文案或产物差异证红，不能以构建失败代替。
完整 tile golden 同时保留旧产物不变性和变异覆盖汇总。

最终验收包括 sm_100 → sm_90 → 本机的整轮串行台账，三本 `inputs=` 相同；
原子由真实设备与 tileref 对拍，tileinterp 明确拒绝 atomic，不列入解释器数值通过。
站点调用图用 `site/gpu-map/record.py` 重新核对，导入列表的缺失、重复及 TileOp 顺序仍受既有自测约束。

S4 只补验收覆盖与文档，不新增 Dev 操作、API 或方言编码，tileir 保持 0.25.1。
0.25.0 的七个 Dev 结果槽操作属于破坏性 minor；0.25.1 已承载 S3 的能力扩展，
本次没有另升 patch 的功能变更。发版与证据发布交由维护者执行。
完整门禁的精确提交、bundle、CI 与全部负控原始输出记录在维护者验收报告；
里程碑 PR 与已合入哈希见 [M7 后续核账](history/m7-progress.md)。

## 不做的（理由）

- 逐 lane if、自动 any/all、设备 Bool 转宿主 Bool：不同执行语义，继续显式 select/mask。
- staged while 与隐式非局部退出：需要设备控制流协议，保留显式 d_loop/d_return_if。
- 放开普通 var 闭包捕获：重复记录与逃逸会破坏现有规则。
- 检查器线程化异构元组：格子与库 yield 已有明确分工，不增加变长泛型或 Core 节点。
- 自动纯 if/select 互换、无条件 token 槽：破坏语义或旧 IR 不变性审计点。
- 完整 alias-set 重写与无实测性能承诺：超出本刀正确性范围。
