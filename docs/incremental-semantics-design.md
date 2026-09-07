# 增量语义引擎

> 状态：**current** —— 2026-09-07 实施中的设计与进度，不是已完成能力或性能承诺。
> 用户授权按七期持续实施，第2、5、7期验收后分别产出报告。

## 一、问题与基线

调研基线为 `1ae9edf2`，冷路径前置已合并到 `8c2312bc`。workspace 已复用 std、captured plan、Java lease，并有同步
debounce 和一致 Program；缺的是跨编辑的语义复用。`driver/analyze.analyze_program`
逐模块推进 exports、全局 impls 和 next_id，因此文本不变并不意味着模块结果可复用。
Playground 使用非 file URI，属于 standalone；模块前缀复用不能加速每次都变的单模块。

已运行 hello_mod/selfhost 的探索性冷路径基准；可复现入口是
`scripts/incremental-semantics-contract/bench.py`，原始轮次、源码指纹、环境和进程 RSS
分别归档，cold/observed 交替顺序。parse replay 不冒充 loader 内部分段，进程 RSS
不冒充缓存保留内存。仍需真实编辑首差、query 延迟及保留内存测量，再决定启用范围；
不写未经实测的加速倍数。

## 二、首个交付：保守模块前缀

抽取单模块 transition：`(input, carry, world) -> (checked, diags, carry_after)`。
carry 包含 exports、impls、next_id；world 固定 StdCtx、CtOpts、Jsig 及 captured plan。
input 是 loader 完成 package/alias 改写及 std identity 判定后的完整 AST、文本和身份，
不能只比较原始文本。每次仍执行 loader/parser，从新旧最终模块序列的首差开始重算。

只复用连续 clean、无 Java hook 查询的前缀；loader 错误或 comptime FFI enabled 时
首版冷回退。错误模块仍照旧发布 recovered exports/impls/next_id，不改变诊断顺序。
std 的 impls_before 特例保留。禁止公开签名相同就重新接回旧后缀的隐式优化。

Java 的八个 Jsig hook 都需要观测，包括失败查找及 import 间接带入的 Java 类型。
同一 lease 固定 classpath 并不冻结外部答案。共享层只接受 `!io` 观测 callback，
不直接依赖 JVM 可变对象；具体 host 提供观测状态，refusing host 不触发 hook。
生命周期和计数应与单次 analysis 绑定，不能让后续 tooling 查询污染已提交缓存资格。

归纳证明：固定 world，前缀输入相同，初始 carry 相同，且复用步骤无外界查询，
则每步结果和下一 carry 相同；重算后缀从与 cold 相同的 carry 开始。诊断始终以本轮
loader diagnostics 为首，再按当前模块顺序装配。cold/warm 对拍使用同一捕获输入。

## 三、所有权与事件

首版仅 Ready workspace 持一代缓存；Program、entry map、诊断与缓存事务性替换。
查询前仍先 flush pending；不引入后台 checker 或取消。冲突/unavailable 不返回旧成功
快照；last close 和 lease 释放清缓存。Ready didSave 不刷新 captured plan，是既有契约。
std/plan/lease/options 替换必须新建分析 owner。逐出仅损失速度，保留当前查询 Program。

## 四、函数级演进

ModuleKey/DeclKey 与 body-local 临时 ID 分离，缓存产物中所有引用必须可重定位。
保持既有输出顺序；若做不到，先复核设计并请求发射契约裁决，不扩大 golden 消噪。
query 记录真实语义读取，含 scope/候选集的失败查找、impl、alias、trait/effect metadata。
inferred body 参与 signature，comptime 读取 body/value，不能只跟踪导出函数签名。
语义结果与源码位置视图分别失效，避免空白改动后 definition/diagnostics 使用旧 span。

## 五、七期与报告

| 期 | 交付 | 状态 |
|---|---|---|
| 1 | 冷路径对照、阶段基线、Java 观测 | 进行中 |
| 2 | workspace 前缀缓存、生命周期、基本逐出 | 缓存及workspace接线已实现，验收进行中；验收后报告 |
| 3 | 稳定身份、具名产物及重定位 | 未开始 |
| 4 | query runtime、依赖失效和 header 接线 | 未开始 |
| 5 | 函数 body 增量、standalone/Playground | 未开始；验收后报告 |
| 6 | comptime/Java/索引与工具消费者收口 | 未开始 |
| 7 | 长会话内存、完整差分、性能与发布验收 | 未开始；验收后报告 |

27个任务包的范围估算为174–281有效人日，不是agent墙钟承诺；原型和测量后滚动修订。
阶段报告必须列准确提交、验收命令/结果、性能样本与环境、已知回退和未达项。
报告位置为 `docs/history/incremental-semantics-p{2,5,7}-report.md`，只在实际完成后创建。

## 六、验收

首刀已实现共享 `observe_queries` callback、host-owned `JsigProbe` 和 JVM
`query_probe`；尚未接入生产分析，也未启用缓存。原型证明无需在共享checker里引入
Java可变对象。共享模块两个测试守八个hook的观察顺序与refusing guard，JVM测试守
计数独立、零查询gate、返回值与参数方向；项目夹具证明经import的Java对象仍触发查询。
`scripts/incremental-semantics-contract/probe.py` 先核验全部锚点，然后实际编译九个
变异体，每个必须命中owning测试，构建错误不算证据；workflow已接线。第一期仍缺
真实编辑/query/保留内存基线，不能据此宣称第一期完成。

第二刀抽取 `AnalysisCarry/ModuleStep`，`analyze_program` 仍走无 observer 的
cold fold；阶段事件只由显式 `analyze_observed` 请求。私有夹具注入冻结的旧循环，
以相同捕获输入对照完整 Program/Cx，不只比较公开签名。独立 javac 比较器避开测试
程序的泛型 Eq 字典构造器问题，不改变生产发射。六个成功编译的变异体覆盖输入 ID、
impl carry、诊断顺序、check/comptime 跳过和 std baseline；编译/反射错误不算负控。
原始实现与独立循环的13组结果对拍、六个负控及350项夹具测试已在本地通过。

后续实现使用 opaque `incremental.Session` 固定 world，防止旧 prefix 被拼接到新
std/options/lease。Workspace 与 Program、entry map、diagnostics 同时提交新 Session；
冲突快照逐出 replay，最后关闭文档沿既有路径移除整个 Workspace。JVM 提供真正的
query_probe，native 提供 refused_probe。首版每个工作区最多保留128个模块和
1,048,576个源码字符；这是逻辑留存预算，不是堆内存字节上界。只保留一代连续前缀，
工具查询使用原 oracle，不保留本轮计数器。standalone 仍走旧入口。

实测已证明少做工作，而不是仅凭耗时猜测命中：compiler-plan 的13模块编辑序列中，
改最后一个 source 模块复用12、重查1；selfhost 的72模块 entry closure 中，
改 main（位置71）复用26、重查46，Java查询阻断更长前缀；改 parser（位置3）
只复用3、重查69。这里的72是LSP entry closure，不混称目录分析的74模块。

同源码私有观测服务、GraalVM21.0.2、SerialGC、11轮丢前3轮的一组 compiler-plan
对照：强制冷路径刷新中位119.19ms，前缀复用61.18ms。原始逐轮数据与限制在
`scripts/incremental-semantics-contract/baselines/planner-20260908.json`；两边的全部
hover/definition/completion回复一致。执行顺序为先cold进程后warm进程，样本少，
不是通用加速倍数或SLA，RSS也不是缓存独占内存。较早与其他测试并行的hello_mod/selfhost
延迟样本没有稳定提速结论，不能用于性能达标判断。

首刀本地618个selfhost测试、集成套件214个测试、九个可编译负控和完整文档门通过。
native侧484个selfhost测试通过，自举B==C固定点和独立calc发射冒烟通过；重录后Core门通过。
固定17份Core文本不变；selfhost哈希按源修改重录。除jsig/jreflect外，exitmem的两个
handler标识常量随原全局取号一起从29321移到29374，已逐字对照；未扩大归一化规则。

每刀同时守重构前后 cold 和同版本 cold/warm，防止两条新路径一起错。覆盖模块增删、
输入改写、全局ID/impl carry、错误恢复、std provenance、overlay冲突、Java lease及
comptime环境。执行计数证明少做工作，不能只看耗时；总是cold的变异体也必须被抓到。
新增不变量配成功编译且命中 owning assertion 的负控，不把timeout/build failure算红。
私有测试observer不改变LSP协议。golden需要重录时先核对差异，不靠重录宣称等价。

## 七、不做的

不新增语法、改变推断/可见性、扩展comptime语言能力；不做磁盘缓存、跨进程共享、
并行checker、watcher、增量parser或增量机器码发射；CLI共享语义入口但新进程不热启动。
不把pending扫描优化算cache收益，不把第2期称为Playground提速，不发布或部署到生产。
