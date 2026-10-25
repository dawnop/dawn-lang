# 效果来源：按观察作用域保留逻辑调用

> 状态：**proposed**（P0，2026-10-25）。本文固定目标契约、语法候选与验收边界；语言设施尚未实现，表面语法待裁定，P1 实现并发布后才做 P2 包迁移。

<!-- 为什么写这篇：设备字节相同不能证明源码归属相同。把客观调用来源交给编译器，
     把展示抽象留给观察器，才能退休散在库签名与用户 helper 中的第二套调用协议。 -->

## 一、问题与证据边界

目前源码来源在「执行 Dawn 宿主代码 → 效果 handler」的边界没有自动传递。
`caller()` 的行号没有算错：它是在调用点展开的静态 `Loc` 常量，不是物理栈回溯。
但一枚起点位置既没有完整调用 span、名字 span，也没有这次执行的父调用身份。
handler 中调用 `loc.here()` 只会得到 handler 那一行。

2026-10-25 对 `45e81c8b` 的源码计数，逐行排除整行 `#` 注释，调用不计函数声明：

| 手工协议 | 数量 |
|---|---:|
| `at: Loc = caller()` | **193**：dev 中 185，prog 的 trace 入口中 8 |
| `called` / `called_bare` / `user_body` 包装调用 | **228**：185 + 29 + 14 |
| `Dev` 来源标记操作 | **四个**：`t_call_enter`、`t_call_exit`、`t_body_enter`、`t_body_exit` |

这些是指定基线的计数，不是永久不变的仓库统计，也不是可直接删除的 LOC。
`dev.dawn` 中 213 个顶层公开函数只有 185 个带该默认参数；运算符与 staged trait
方法不能接默认值，所以不能把问题简写为「每个 pub 函数都有 at」。

永久负控在 [record.py](../site/gpu-map/record.py) 的 `--check-call-origin` 入口：
只在临时副本删除 `fa_exp`、`fa_divide` 共八条标记调用，保留行号、`at` 和数值分支，
清理对应 unused imports。两份程序都必须真实编译并录制，不能靠伪造 rows 通过。

| 判词 | 基线 | 删除标记 |
|---|---:|---:|
| 调用行 | 45 | 42 |
| Tile 操作 | 56 | 56 |
| MLIR 行 / bytecode 字节 | 68 / 1053 | 68 / 1053 |
| 普通 MLIR、bytecode 与入库 golden | 逐字节相同 | 逐字节相同 |
| 严格 gpu-map 来源配对 | 通过，并复现入库 map | 拒绝 |

顶层静态调用期望 `fa_divide`，录制却只有内部 `div`；两个 `fa_exp` 父节点也消失，
其 `exp2` 被提升到同一 `d_range` 父节点下。p 与 alpha 共用定义位置，却对应两个算法步骤。
数值与设备字节没有说明这两条调用边是否还在。负控要求先证明编译/录制成功和设备字节相同，
再核对「source calls / recording ran」的配对拒绝，不能把编译失败或旧摘要失配算作成功负控。
这里测的是 JVM 宿主录制与来源 oracle，没有测 GPU 时间，也没有测来源设施的成本。

## 二、重新裁决与职责

[caller-location-design.md](caller-location-design.md) 第二节选择显式默认值、第九节否决
隐式调用者传播的结论，**对观察型来源在此推翻**。193 个默认参数、228 处包装与完整调用树需求
已经超出「少数库函数替调用者报错」的前提。观察作用域中的来源由编译器隐式携带，
普通函数与用户 helper 的签名不写机械 `at`，也不要求逐函数加属性。

`caller()`、`Loc` 及 `panic(msg, at = at)` 的显式归责继续成立：作者可以选择替用户报告哪一行，
这是诊断政策；客观来源保存实际调用链。两者可并存，观察器不能改写 panic 的显式位置。
`Loc` 不变成调用栈，函数值丢默认参数的既有规则不变。

Core 已有 `CSite = CNoSite | CAt(lo, hi, nlo)`、`CFun.origin` 与
`ir/coresites.dawn` 的声明基址恢复；C/JVM `.dawnmap` 也已存在。
[source-span-map-design.md](source-span-map-design.md) 的这些静态信息是底座，
缺的是执行中的调用实例、结束状态及 perform 发起方来源，不能再用「Core 无 span」作前提。

编译器不认识 `Dev`、FlashAttention 或 helper 名字。同一设施必须适用于任意用户效果、
构建器、IO/数据库诊断和 profiler。tileir 负责来源投影、设备 region 与 handle 的归属。
K3 后续切片仍沿用现有正确协议，不等待 P1/P2，也不把语言改动塞进读者迁移。

## 三、最小完整契约

### 3.1 四层数据

| 层 | 必须保存的事实 | 缺失时的反例 |
|---|---|---|
| 静态 `Site` | 模块/文件身份、声明身份、调用 span、callee/name span、合成节点的原语法与角色 | 方法链的两个调用可能同起点；单行列不能区分名字 |
| 逻辑调用上下文 | 观察作用域内的运行实例 ID、父实例、callee 身份、调用点、函数/闭包定义身份 | 同一定义执行两次不能用 `(file,line,col)` 合并 |
| 效果 envelope | operation 身份、perform Site、发起方逻辑上下文的不可变快照 | handler 安装点的环境不是 perform 方的调用链 |
| 作用域生命期 | 调用进入、正常/异常完成、挂起/恢复/放弃，或信息等价的可恢复树 | 只存 op 快照会漏掉零 perform 的被观察调用 |

静态坐标复用声明内相对偏移与展示路径规则，不保存构建机器的绝对路径。
编译器合成节点必须记录可说明的角色与来源；确实未知的来源显式未知。
观察根下的 Dawn 调用保留完成记录，即使该次没有 perform，投影才决定是否展示。
`tile_shape` 执行 `t_shape_of`、`scalar` 执行 `t_scalar`，属于零设备 IR 而非零效果；
必须在 opcode 过滤前观察查询事件。不能只从最终 TileOp 倒推树或丢弃零行 helper。

### 3.2 观察能力与纯性

读取来源属于 **handler/观察作用域能力**。录制器在执行 body、安装 handler 的边界启用它，
handler 臂得到只读 envelope，观察器得到调用完成记录。取出的 `Origin` 是普通不可变值，
可显式传给纯诊断函数并在观察结束后保留；可变观察器、当前上下文读取与日志操作不能伪装成纯值。

不提供任意纯函数都能调用的纯 `provenance()`。同参数函数若能读出不同调用环境，
纯性、公共子表达式消除和缓存的依据就改变了。观察能力的类型/行规则必须随 P1 语法裁定进入 spec，
不能靠标准库函数名暗开读环境的特权。观察期所承诺的调用记录也是编译变换须保留的可观察事实。
计算结果、效果选择和实参求值顺序维持既有语义。

**metadata 与 evidence 分开。** spec 的词法 evidence 仍在 handler 安装处解析，
闭包创建时不捕获 handler；来源 envelope 描述操作发起方，不把 handler 的自由变量改为动态解析。
臂内再次发效果仍按现有外层/安装处规则选择 handler。嵌套观察作用域有各自根与实例空间，
相互引用必须带作用域身份；内层退出后恢复外层，不能用一个全局栈顶猜来源。

### 3.3 来源 ABI 与生命期

P1 在效果操作降低成 evidence 字段读取和普通 `XApply` **之前**保留 operation 身份。
独立 trace token/上下文引用可以复用现有编译器通路传递，但不是 evidence 的动态替代物。
直接调用、Fn 接口、函数值桥、trait 字典、多态效果、跨模块/包调用使用同一个来源 ABI。
不能让动态调用转成定义处位置或静默截链。外部 ABI 不支持的边界显式记为未知，严格映射拒绝。

JVM 要覆盖 Fn 动态桥、异常路径与控制运行时；native C 要覆盖 closure ABI、RC 所有权、
unwind 与 control runtime。静态 Site 表不逐次重建；运行实例与上下文的存储由观察作用域持有，
外传 Origin/continuation 必须持有其所需的稳定身份，不能指向已经释放的 C 栈帧。
comptime/解释器同样定义能力边界，不支持的来源观察必须明确拒绝，不能伪造宿主栈。

## 四、投影政策替换 call/body 协议

编译器保存客观身份，tileir 在 trace body 根下选择展示层级，集中替代 `kernel_side`/`user_body`：

- 展示用户发起的 tileir 表面调用与用户 helper；折叠 tileir 自己的实现调用。
  依据调用点所属声明/模块和闭包词法身份，不按物理栈深，不一概排除依赖包。
  用户 helper 包可展示，tileir 声明自己的实现范围。
- `tile_at` 内部 `idx_mul` 投到最近的用户级祖先；两个 `fa_exp` 内的 `exp2` 各自保留不同 helper 父实例。
- region 实现回调用户 lambda 时，由 lambda 的定义身份重新进入用户层，当前区域调用仍为祖先。
  普通 helper 函数体不再冒充设备 region。
- 在真实设备 region 创建时记 `region → origin`。handle 分配时记 `handle → origin`，
  或保留等价区间索引；当前名为 `spans` 的表是 handle 区间，不能当作源码 span 删除其职责。

`TileProg` 数值/结构与 `OriginTrace` 侧表分离。lower/render 传递 op identity，
降低/编码诊断需要来源时显式接收侧表。普通 MLIR、tilebc、相等性与缓存中的设备语义不包含行号；
可选调试段必须另有显式开关。挪行不应制造设备 golden 差分。
parser 保留文件/声明/span 的独立校验，逐步退出按执行顺序猜调用、硬编码两个 helper、扫描
`called("字面名字"` 来补造来源的职责；来源不完整就拒绝严格映射。

## 五、必须一起定义的边界

| 边界 | 契约与验收方向 |
|---|---|
| staged 语法 | 运算符、字面量、`var`、`for` 的合成 trait 调用携带原始语法 span 与角色，不能全为 `CNoSite` |
| `DRange` 纯值 | P2 删除 `DRange.at` 后区域位置改为实际 staged `for` 使用处。`let r = d_range(...); for ... in r` 指向 `for`，内联写法可另展示 head span；不追踪所有纯值历史来维持构造点 |
| 闭包 | 保留定义身份，调用来源取实际调用处；不把创建时运行栈捕获进每个 closure。区分匿名 wrapper、factory 根与合成 lambda |
| 函数值/trait/多态 | 与直接调用相同的 ABI 与实例规则；跨模块、泛型实例和动态 dispatch 均需测试 |
| trial 回滚 | 通用观察器提供 checkpoint/rewind 或事务 epoch，tileir 决定何时试录。日志、投影索引、handle/region 归属同时回滚，不泄漏试探实例；编译器不理解 `t_trial_begin` |
| `return` / `?` | 每个合法提前出口都完成或中止对应帧并恢复父上下文；仍遵守现有 `with` 真闭包对 return/break/continue 的禁令与 `?` 透明规则 |
| panic/catch | unwind 后无残留当前帧；保存的快照仍有效，panic 的显式 `at` 不变 |
| control effect | suspend 保存发起上下文，resume 重建它，丢弃续延完成放弃事件。Dawn 当前续延一次性；内部 replay 不得多记已提交实例，第二次恢复仍按 spec 拒绝 |
| 尾调用 | 无观察时继续现有 TCO；观察时用 tail-edge/压缩和显式容量上限。无界精确历史不能与常量空间免费兼得；超过上限标记截断，精确 map 必须拒绝，不能猜补 |
| IR 变换 | 一对多继承来源，多对一保留类似 `FusedLoc` 的来源集合；调用归属与 operand 数值来源分别索引，不能只留最后一个行号 |

continuation 即使在安装帧返回后恢复，也不能复用失效 token；嵌套、放弃、异常恢复与日志 rewind
须有双后端正负控。并发若暂不支持共享观察器，必须检查并拒绝跨执行上下文误用，不能默默串树。
试录的实例身份带 epoch，已外传快照可被识别为未提交，不能在 rewind 后与新提交节点重号混淆。
P1 发布前须写死容量、截断标志、tail-edge 解码与日志所有权，本文不杜撰已测得的上限。

## 六、表面语法候选与推荐

以下均为**尚未实现的提案片段**，不是当前可编译样例。以 spec 的
`with x <- f(...)`、`with handle E { op(args) => ... }` 和 `resume k` 为基础，
用普通用户效果 `Ask` 表达，不给 tileir 新增专用语法。`observe` 建观察根，
`trace` 是受作用域约束的观察能力；具体类型与效果行是 P1 前的裁定项。

**候选 A（推荐）：在 handler 臂增加来源绑定子句。** 类似现有 `resume k`，
`origin o` 绑定本次 operation 的 envelope；两者同时出现时顺序为 `origin o resume k`。

```text
with trace <- provenance.observe()
with handle Ask {
  ask(n) origin o => {
    trace.note(o)
    n + 1
  }
}
let answer = helper(1)
(answer, trace.completed())
```

`origin` 只在该臂参数表后的上下文识别，不改 operation 的声明参数、函数类型与普通调用写法。
读取需要在场的观察能力，域外绑定/使用由 checker 拒绝；没有子句的既有 handler 保持语义。
臂里的 `o` 是发起方快照，`trace.completed()` 给出包括零 perform 调用在内的完成日志。
这样源码上能直接区分「这次操作的来源」与 handler 当前执行的来源。

**候选 B：不改 handler 语法，由能力参数进入受约束的标准观察入口。**

```text
with trace <- provenance.observe()
with handle Ask {
  ask(n) => provenance.at_operation(trace, o => {
    trace.note(o)
    n + 1
  })
}
let answer = helper(1)
(answer, trace.completed())
```

它复用高阶调用与能力传参，parser 改动较少，但 `at_operation` 必须受 checker 限制在
相应 handler 臂的动态激活内，不能被提到任意纯 helper 后读取环境；它仍是语言设施，
不能假称 std 普通函数就能实现。推荐 A，因为绑定对象与作用域在臂上可见，
也沿用现有控制臂子句的结构。P0 只提出选择，P1 在语法裁定后同步 spec、parser、checker、LSP 与 formatter。

## 七、双后端成本测量计划

**尚未测量自动来源的性能，不承诺零开销、加速或 GPU 收益。** 现有 `caller()` 静态常量、
额外 closure/效果调用、诊断时扫描来源表是三类成本，不能混成一个数字。
不选每次 perform 用 JVM StackWalker/Throwable 或 native unwind，也不让所有函数无条件维护全局隐式栈。

P1 用同一源码、固定种子/工具链、独立进程，在 JVM 和 native C 各测三组：
A 为真父编译器，B 为新编译器但观察关闭，C 为新编译器观察开启。
固定输入与优化参数，预热 JVM 后另记冷启动；交错 A/B/C，至少七次墙钟样本，
记录中位数、范围、CPU、峰值 RSS、环境负载与完整命令。噪声内差异只报告区间。

| 负载 | 要隔离的问题 | 记录 |
|---|---|---|
| 编译器、容器、纯算术热循环 | 无观察路径的判断、ABI、代码体积是否回归 | JVM class/jar 与 native C/二进制体积、墙钟/CPU/RSS；能消除的检查以产物核对 |
| direct/函数值/trait/高阶/跨模块调用 | 来源传参、bridge 与每次 call 的日志成本 | 每调用事件/字节、总分配、吞吐；增加调用深度与重复次数 |
| 全部 tile 录制语料与纯用户效果构建器 | 观察开启的完整树、零 IR 与零 perform 调用 | 录制、投影、lower/render 分项时间与分配；旧 marks 作为额外参照，不能先假定更快 |
| trial、嵌套、panic、continuation、尾递归 | 回滚、恢复、驻留与截断成本 | 最大活帧、保留事件、长尾时间、截断点；native ASAN/RC 与 JVM 栈/堆 |

JVM 记录 JFR 分配/GC，native 记录分配/dup/drop、峰值活字节与 sanitizer 结果；
静态 Site 表、运行帧、事件日志分别计量。容量测试须证明 TCO 不因无限历史而无限占空间，
以及截断能使严格 map 红。复用 evidence 通路的独立 token 也有 ABI 成本，必须实际测。
设备隔离以 TileProg/lower/MLIR/tilebc 相同为证据，宿主录制时间不写成 kernel 时间。
性能门限在这套基线测量后裁定；不能填一个没有出处的百分比。

## 八、分期与验收

### 8.1 P0

本设计、索引和三份相关文档指针，以及真实删除标记负控。文档 gate 调用
`python3 site/gpu-map/record.py --check-call-origin`，额外步骤登记 steps lock，
墙钟增量以该步骤实测记录在 PR/交接报告。现有样例、算法、tileir 版本和所有 golden 均不变。

### 8.2 P1：通用语言设施

P0 合入且语法裁定后独立实现，不以 tileir 包名开特权。验收必须同时满足：

1. 四层数据、观察纯性、独立 metadata ABI、投影所需身份在 JVM/native C 一致；
   跨包、函数值、trait、运算符、合成 staged 节点、用户 callback、两次同名 helper、零 IR/零 perform 均有正负控。
2. handler 安装环境与 perform 来源分离，嵌套 handler 的效果选择不变；
   return/`?`、panic/catch、control suspend/resume/discard、trial 无重复或残留实例。
3. 尾调用容量、截断、融合来源、未知边界明确，缺失信息使精确映射拒绝；
   解释器/comptime 不支持路径明确拒绝。前述双后端成本矩阵出实测记录，无观察回归可审。
4. 更新规格与工具支持，审计全部 IR 构造/match、Fn 桥和 runtime 生成物；
   完成固定点与种子兼容检查，先发 tag 进入种子，再允许 P2 源码依赖它。
   实际 N/N-1 输出差分按登记 label 逐条写 `Emit-Change`，不预先虚构差分。

### 8.3 P2：tileir 0.29.0 一次迁移，无 shim

P1 种子可用后，**tileir 0.29.0** 一次删除 193 个机械默认参数对应的存活签名、
`called` 家族、四个 Dev 标记及 mock 臂、`Mark` 协议与 `DRange.at`，不留旧签名 shim，
不导出 `called`/`user_body`，不发布 `kernel_fn`。届时基线新增 helper 也要一起迁移，不能只改旧八行。

迁移 trace 入口、Ctx/handle/region 来源、trial、render 与诊断；设备查询/数值语义保留。
同步 gpu-map、xmap、Playground tilemap、实际样例与 kernels 镜像、定义全文 pin、数值负控、
EN/ZH GPU 页及在线编译窗格，撤掉 helper 白名单和 `called` 字面串扫描。
xmap 若改变公开 Call 类型才升相应 minor，不因内部改动机械升版。

硬判词是旧/新 TileProg、lower、普通 MLIR/tilebc 等价，挪行/注释/无害 helper 重命名不改变设备字节；
p/alpha、后续 K3 boundary/even 的重复执行实例分得清，IR 不能互换。
零行查询、方法链名字 span、回调重入与库内部折叠均有独立断言；region 位置明确接受从 DRange
构造点改为 `for` 使用处。GPU 页/Playground 真正生成与 Run/C/JVM/Tile、doc-check pin、
数值与来源负控一起通过，不放宽拒绝规则来迁就新树。
P0 的删除标记负控在 P2 迁移为「新来源边被删时，设备仍同字节但严格映射拒绝」，
不能删掉来源 oracle，也不能为了保留旧负控重新引入旧协议。

## 九、先例与适用范围

以下官方文档/源码核对于 2026-10-25。主线源码链接会变，后续实现应保存所用版本；
这些机制启发职责边界，不证明 Dawn 的完整契约已经实现或没有成本。

| 系统与来源 | 已有机制 | 对本设计的约束 |
|---|---|---|
| [MLIR Location](https://mlir.llvm.org/docs/Dialects/Builtin/#location-attributes) | operation 的 Location 由前端/变换提供；`CallSiteLoc` 表示 callee/caller，`FusedLoc` 表示多来源，`NameLoc` 附名字，可显式 Unknown | span、调用链与融合来源分开；Location 本身不提供零操作调用的完成树 |
| [JAX source_info](https://github.com/jax-ml/jax/blob/main/jax/_src/source_info_util.py)、[JaxprEqn](https://github.com/jax-ml/jax/blob/main/jax/_src/core.py) | equation 的 SourceInfo 保存 traceback/name_stack，`current()` 按需取 traceback；[named_scope](https://docs.jax.dev/en/latest/_autosummary/jax.named_scope.html) 另外增加语义名字 | 自动来源与显式命名范围不是同一个保证；不要求每个 helper 手写范围 |
| [Triton code_generator](https://github.com/triton-lang/triton/blob/main/python/triton/compiler/code_generator.py) | AST visitor 用节点行列设置/恢复 builder Location，也可加名字 | 前端知道正在降低的节点，不能概括成所有路径都扫描 Python 栈 |
| [cuTile ast2hir](https://github.com/NVIDIA/cutile-python/blob/main/src/cuda/tile/_passes/ast2hir.py)、[hir2ir](https://github.com/NVIDIA/cutile-python/blob/main/src/cuda/tile/_passes/hir2ir.py) | AST 位置进入 HIR；内联 scope 保存 call_site，retarget_loc 接定义与调用链 | 同时保留 helper 定义与具体调用处；cuTile 不与 CuTe DSL 混称 |
| [Julia 1.12 AST/IR](https://docs.julialang.org/en/v1.12/devdocs/ast/) | LineNumberNode 给文件/行，DebugInfo 的 edges/codelocs 编码内联边 | 行号节点不能替代调用实例或内联链 |
| [Koka](https://koka-lang.github.io/koka/doc/book.html) | tail-resumptive 操作可经 evidence 直接调用 handler，不必捕获控制栈 | 有 effects 不自动等于有完整来源；metadata 需单独契约 |
| [Effekt SourcePosition](https://github.com/effekt-lang/effekt/blob/main/libraries/common/effekt.effekt) | 声明 `?sourcePosition` 隐式值实参可得调用点；操作/capability/resume 处理效果控制 | 不能说它完全没有自动位置，也不能把位置参数当完整调用树 |
| [OCaml 5 Effect.Deep](https://ocaml.org/manual/5.3/api/Effect.Deep.html) | effc 得到 effect 与 continuation；get_callstack 可读取续延栈顶部有限条目 | 这是 effects 可观察栈的反例，但有限 backtrace 不等于每个 effect 自动携带精确 AST 来源 |
| [Rust track_caller](https://doc.rust-lang.org/reference/attributes/codegen.html#the-track_caller-attribute) | 隐式位置参数不进函数类型；转函数指针可由 shim 变为定义处调用位置 | Dawn 的完整来源 ABI 不能在函数值/trait 边界静默丢信息；显式 panic 归责仍用 caller() |

## 十、不做的（理由）

- 不直接删 marks、内联 helper 或删失败测试：设备等价的永久负控已经说明来源信息会丢失。
- 不导出 `called`/`user_body` 或发布 `kernel_fn`：局部缩短代码会固化应退休的双重调用协议。
- 不只补 perform-site Loc 或固定跳过 N 帧：得到的是库 primitive 行，重构还会改变深度。
- 不把客观来源变成任意纯环境读取，不改词法 evidence 解析，不捕获 closure 创建时的运行栈。
- 不无条件维护全局调用栈，不从 JVM/native 物理栈承诺精确语法链：内联、TCO 与续延恢复的边界不同。
- 不用通用值来源追踪保住 DRange 构造位置，不把普通函数体当设备 region。
- 不把行号写进普通 TileProg/golden，不声称自动来源零成本，不拿宿主录制时间冒充 GPU 性能。
- 不恢复已退休的 Explorer 页，不把 P1/P2 当作 K3 读者切片的前置条件：当前消费者是 GPU 页与 Playground。
