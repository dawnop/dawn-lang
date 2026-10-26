# 效果来源：按观察作用域保留逻辑调用

> 状态：**W2 普通观察已实现，待 P1 发布收口**（P1 分期，2026-10-25）。W1 提供语法与静态身份，W2 提供普通观察及双后端逻辑调用 ABI；控制续延、TCO 压缩与有界日志留给 W3。P1 发布后才做 P2 包迁移。

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

W1 之前，Core 已有 `CSite = CNoSite | CAt(lo, hi, nlo)`、`CFun.origin` 与
`ir/coresites.dawn` 的声明基址恢复；C/JVM `.dawnmap` 也已存在。
[source-span-map-design.md](source-span-map-design.md) 的这些静态信息是底座，
缺的是执行中的调用实例、结束状态及 perform 发起方来源，不能再用「Core 无 span」作前提。

W1 为 `CAt` 增加 `CallSource`，用 `CSyntax` 显式保存合成语法的 span 与角色，
用 `CFun.definition` 保存函数及闭包的定义 span 与角色。operation 身份在 evidence 擦除前
记录模块与声明路径；位置保持声明内相对偏移。`CCall`、`CClosure` 的普通 ABI 与既有
`.dawnmap` 输出不变，合成 site 不冒充原有书写调用。`CNoSite` 继续表示明确未知。

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

### 5.1 checkpoint 的重用与失效

补裁四采用 SQL savepoint 的栈纪律。`checkpoint()` 保存本作用域的日志边界与活跃父上下文；
`rewind(c)` 回到该边界，目标 `c` 仍有效且可反复使用。所有在 `c` 之后建立的 checkpoint
同时失效，`c` 及更早建立的保持有效。因此回退内层后仍可回退外层，回退外层后不能再用内层标记。
标记的建立先后次序独立于日志长度，即使两个 checkpoint 之间没有记录，也必须区分。

使用已失效、属于其他 `TraceScope` 或已退出作用域的 checkpoint，必须给出确定性的运行期错误；
两后端使用完全相同的精确文案，不静默忽略，也不改用最近边界。每次成功 rewind 都推进 epoch，
之后的新调用实例不得与被丢弃的试探实例重号。已外传的试探 `Origin` 及其父链保持不可变，
并保留足以识别未提交身份的 scope/epoch 信息。checkpoint 的有效性不能只由当前 epoch 是否相等决定，
否则合法的目标重用和更早标记会被误拒。

不提供 release 或 commit 操作。观察作用域退出时，该作用域的所有 checkpoint 随句柄一起失效。

补裁五进一步把 checkpoint 绑定到建立时的逻辑调用实例 `F`，比较实例身份而非深度或 Site。
`rewind(c)` 只在当前实例恰为 `F` 时合法；仍在执行的更深调用中使用它，报
`not in the creating frame`。`F` 因正常返回、`?` 或 panic 展开而结束后，其建立的全部
checkpoint 失效，再用时报 `creating frame has finished`。这两类错误的完整文案必须在
JVM 与 native C 一致，并相互区分。`F` 外更早的 checkpoint 不因 `F` 结束而失效。
这与前述标记栈规则同时成立：同一仍活跃的建立帧可反复回退，但不能借 rewind 删除仍在
执行的后代帧或复活已经结束的建立帧。续延越域属于 W3，W2 观察下明确拒绝。
双后端以独立手写期望树检查目标重用、嵌套失效、跨域和退出后拒绝、epoch 不重号及快照不变。

## 六、表面语法裁定与候选记录

W2 采用以下 A 方案的普通观察入口。W1 的统一拒绝由词法能力检查替代。以 spec 的
`with x <- f(...)`、`with handle E { op(args) => ... }` 和 `resume k` 为基础，
用普通用户效果 `Ask` 表达，不给 tileir 新增专用语法。`observe` 建观察根，
`trace` 是受作用域约束的观察能力；已裁定观察入口引入 `io`，`TraceScope` 为不可逃逸的词法句柄；`Origin` 为可外传的不可变值。W2 在词法观察域内支持 `origin o`，域外仍明确拒绝。

**采纳 A：在 handler 臂增加来源绑定子句。** 类似现有 `resume k`，
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
不能假称 std 普通函数就能实现。补裁已采纳 A，不提供 B 作为第二入口。W1 同步
spec、parser、checker、LSP 与 formatter；来源绑定的 rename 继续遵守有诊断则拒绝的
既有政策，W2 增加成功 rename 正控。

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
2026-10-25 补裁在数据产生前锁定门限：U0 配对时间比的单侧 95% 上界不超过 1.02，
U1 各负载不超过 1.05，编译与冷启动中位数回归不超过 5%；观察开启的 tile 录制总比值
不超过 2.0、单例不超过 3.0，规模倍增不超过 2.5 倍。W1 冻结父编译器 A 与本分支 B
的测量 harness，先做 A/A 盲控；噪声不可分辨时报告不确定，不放宽门限。

补裁三明确 U0 的判定顺序：先比较实际被测产物的结构；产物相同即按结构同一性判定，
只有产物不同时才使用上述时间门限。native 必须核对全部 allocated section 与 loadable segment，
包括代码、常量、数据、relocation、unwind、TLS 及零填充大小；不得靠规范化抹掉执行差异。
只允许剔除已说明且不加载的文件符号等构建信息，时间样本与超线记录仍完整保留。

### 7.1 W1 冻结基线与结构判定（2026-10-25）

harness 与结果位于 [effect-provenance-bench](../scripts/effect-provenance-bench/measure.py)，
[baseline.json](../scripts/effect-provenance-bench/baseline.json) 保存环境、工具链、阈值、产物摘要及区间，
[samples.jsonl](../scripts/effect-provenance-bench/samples.jsonl) 保存全部 507 个独立进程样本。
A 是父提交 `26933caf` 的编译器，B 是 W1 草稿编译器；两者编译同一份输入与 std。
计时期间没有并发构建或测试，固定 CPU affinity，使用 JDK 21.0.2 与 clang 18.1.3。
每个热进程先预热 30 批，再测 50 批；以进程中位数配对，用 20000 次 bootstrap 给区间。
JVM 热路径与冷启动各 31 轮，native 热路径先 15 轮再独立补测 31 轮，编译及完整 bootstrap 各 15 轮。
先前 15 轮的 native trait A/A 上界为 1.054，未删除该组数据；下表使用 31 轮结果。

| 热负载 | JVM B/A 中位数 / 单侧 95% 上界 | native B/A 中位数 / 单侧 95% 上界 | native A/A 上界 |
|---|---:|---:|---:|
| `arithmetic` | 1.0011 / 1.0087 | 0.9998 / 1.0020 | 1.0049 |
| `direct` | 1.0002 / 1.0019 | 1.0001 / 1.0044 | 1.0048 |
| `function` | 0.9977 / 1.0006 | 1.0026 / 1.0200 | 1.0107 |
| `trait` | 0.9964 / 0.9997 | 1.0139 / 1.0338 | 1.0010 |
| `higher` | 1.0014 / 1.0043 | 0.9996 / 1.0058 | 1.0065 |
| `container` | 0.9955 / 1.0148 | 0.9906 / 0.9937 | 1.0063 |

**原始时间记录：** native trait 的 B/A 上界为 1.0338，超过锁定的 1.02；
该负载 A/A 上界为 1.0010。B/A 双侧 95% 区间为 [0.9717, 1.0460]，不能宣称已测出无回归。
该结果已回报协调者，未放宽门限或删除慢样本。JVM 各负载上界均不超过 1.0149。
补裁三要求先查产物结构，未为取得较好数字重测。

编译、完整 bootstrap、JVM 冷启动、native 冷启动的配对中位数比分别为
1.0176、1.0200、1.0164、1.0012；均在各自 5% 中位数门限内。
完整 bootstrap 的双侧 95% 区间为 [0.9935, 1.0276]，A/A 为 [0.9802, 1.0098]。
热输入的 130 个 JAR 条目及完整 C 源码在 A/B 之间逐字节相同，冷输入的 116 个条目及 C 亦相同，
不需要剔除 build-info 才相等。热输入 JAR/C/native 大小分别为 110100/56335/144688 字节，
冷输入为 87060/1392/113792 字节，两组 A/B 尺寸相同；native 二进制哈希不同，不宣称二进制同字节。
[structure.py](../scripts/effect-provenance-bench/structure.py) 核对实际被测 ELF：热二进制只有
偏移 133733 处的 `A.c`/`B.c` 一个字节不同，冷二进制只有偏移 105637 处的
`A-cold.c`/`B-cold.c` 一个字节不同，均为无 allocated 标志的 `.strtab` 中 `STT_FILE` 名字。
不存在 GNU build-id 差异，代码、数据、路径、时间戳与链接顺序没有造成加载内容差异。
两组各 27 个 allocated section、四个 `PT_LOAD` segment 及全部 program header 原样相同，
不需要规范化；只将非加载文件符号名置零后，整个 ELF 也逐字节相同。
因此依补裁三，**U0 按结构同一性通过**。上面的 507 个样本及 1.0338 超线记录原样保存，
不把该时间结果改写为门限通过。W1 没有 U1 或观察运行期，未测这些未来切片的成本。

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

## 补裁六的实现约束

普通与观察执行使用同一定义的编译期双入口，不增加源签名或用户参数。共享 Core 在任何
可能删除逻辑调用的优化前计算 Plain/Observed 两位可达掩码，并保存唯一 definition 和 Site 身份。
普通入口沿用既有 ABI 和优化，不含观察检查；观察入口完整维护进入、退出、checkpoint 与 epoch。
仅发射可达的入口。观察的 callback 是 Observed 根，普通入口是 Plain 根，调用沿当前模式传播。

闭包、trait slot、Fn 桥和库回调按调用者模式路由，不按值的创建位置路由。C 保持 canonical
plain 指针与原闭包布局，观察路径使用非线性的 canonical 到 observed 索引；地址具有语义，
禁止将不同定义入口折叠，并检查唯一性。JVM 的 observed 方法使用独立描述符，普通 apply 不变。
内部 Dawn 目标缺 observed 入口为编译错误，不能回落到 Plain；真正未知的外部 ABI 按既定边界处理。
桥不创造用户帧，词法 effect evidence 及 handler 安装能力不受入口选择影响。

原生 U1 草稿的 trait/container 超线证据保留。门限及协议不变，正式重测前冻结新增共享热函数
夹具，原六负载保留；跨模式闭包、trait 三形态、库回调及同 Site 不同实例均须手写预期与负控。
版本化不是兼容层，不是 W3 的 TCO 压缩或 continuation 支持，不能省略纯 helper 或零 perform 调用。

## W2 接口与记录格式

最小标准模块为 `std/provenance`。入口 `observe` 与 `note`、`completed`、`checkpoint`、
`rewind` 按已解析声明身份降低；同名用户函数没有观察特权。`TraceScope` 为词法能力，
只允许直接绑定作为四个操作的实参；别名、容器、返回、任意传参、计算所得句柄及逃逸闭包捕获
均拒绝。`Origin` 与 `Checkpoint` 是可外传的不可变值，后者使用时仍受运行期生命期规则约束。

此前未固定的只读字段名称采用普通英语：`operation`、`parent`、`scope`、`epoch`、`instance`、
`site`、`definition`。`Site` 字段为 `id, module, file, declaration, start, end, name_start,
name_end, role, operation`，`Definition` 字段为 `id, module, declaration, start, end, role`。
`parent`、`site`、`definition` 返回 Option；根无父和调用点，operation envelope 不伪称 handler
为发起方定义。`file` 使用稳定源单元身份而非机器路径；未知坐标为负数。

`completed` 返回不可变 String 前缀，包含尚活跃根及调用，不声称 scope 已结束。实现编码的
`S` 行保存 scope/当前 epoch，`F` 行保存 scope、该实例 epoch、instance、parent、状态、Site ID、
Site 元数据及 definition 元数据；状态 0/1/2 分别为活跃/正常结束/panic 展开。空根明确没有 Site
和 definition。note 以空行分隔的 `O` envelope 及不可变父链附后。元数据中的百分号、tab、换行、
回车与 NUL 分别编码为 `%25/%09/%0A/%0D/%00`，避免声明或测试名伪造记录分隔。两个入口共用
一份静态 Site/definition 身份，动态 instance 不从静态 ID 推导。试探 Origin 的提交归属应与保留日志
的完整身份比较，不能把所有旧 epoch 一概判为未提交。

C/JVM 都将已知同步 runtime 回调适配到 Observed 入口，桥本身不制造用户帧。静态表只建一次，
普通入口没有观察检查。C 将观察入口和来源 runtime 放在独立可执行 `dawn_observed` 段，使普通函数与基础 runtime
保持连续布局；不用会被链接脚本合并到普通 text 前方的 `.text.unlikely` 子段。只有观察产物使用该放置，U0 不受影响。观察帧、记录、checkpoint 与 note 由 scope 持有，退出回收。外传 Origin
拥有快照字节，不引用 C 栈或已释放 scope。W2 不提供容量上限选项；W3 的控制臂、实际递归尾边和
未知外部 ABI 在观察下明确拒绝。已有 tile marks 保持原样，观察成本先在通用构建器上测量。

C 的含观察产物中，闭包/trait 入口及无循环间接分派边界按 64 字节对齐，减少冷代码增量对间接调用
指令缓存边界的扰动。循环体和无观察产物保留后端默认对齐，入口对齐不增加调用边执行的指令，
也不改变 ABI 或身份。

含观察产物的 native 静态字典模板按只读 C 对象发射，显式保留模板的不可变事实，使普通路径
在分配之后仍可解析恒定 slot。动态绑定字典仍由 runtime 复制模板；调用参数沿用原来的
`dawn_dict*` ABI，编译器不向静态模板写入。Observed 分派仍经过 canonical 映射并执行完整协议。

JVM 序列化在写入前按不可变字段长度预估字符容量，一次分配 Origin 与 completed 的构建缓冲区，
减少几何扩容复制和 GC 周期中的临时存活数据。实际内容仍按相同记录格式逐字段写出；容量预估
只决定初始分配，不裁剪日志或父链，也不引入 W3 的容量上限。


### 双入口的源码映射

C 的 Observed 身体在函数边界持有一个展开 guard，调用点正常返回时结束对应记录；panic
展开按该函数进入时的逻辑边界结束尚活跃子调用，避免为每条源码调用注册独立 cleanup。
观察状态通过线程的惰性私有状态保存，最后一个 scope 退出且没有活跃调用时回收；普通入口
不分配或读取该状态。内建函数值与字典适配器是透明桥，保留实际定义身份；同步库回调从
发起调用取得静态 callback Site，不能把适配器的构造位置当作执行调用点。

静态 Site 与 definition 不因入口模式改变；同一源码调用可分别落在 Plain 与 Observed
的物理方法或 C 函数中。既有 dawnmap 格式保留源码身份，使用容纳该行的物理入口区分两种
放置；不把重复的源码坐标误判为两个逻辑 Site。映射判词从容纳入口读取模式，并据此核对
精确的目标符号、Fn 接口或 canonical 选择调用，不能把任意一侧目标都当作正确。
有观察能力的 builder 与 trait/Fn 夹具同时验证两后端的源码配对、物理位置和开关 map 不改产物。
