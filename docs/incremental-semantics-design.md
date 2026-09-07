# 增量语义引擎

> 状态：**current** —— 2026-09-08 实施中的设计与进度，不是七期完成或性能承诺。
> 用户授权按七期持续实施，第2、5、7期验收后分别产出报告。

## 一、问题与基线

调研基线为 `1ae9edf2`，冷路径前置已合并到 `8c2312bc`。workspace 已复用 std、captured plan、Java lease，并有同步
debounce 和一致 Program；缺的是跨编辑的语义复用。`driver/analyze.analyze_program`
逐模块推进 exports、全局 impls 和 next_id，因此文本不变并不意味着模块结果可复用。
Playground 使用非 file URI，属于 standalone；模块前缀复用不能加速每次都变的单模块。

已运行 hello_mod/selfhost 的探索性冷路径基准；可复现入口是
`scripts/incremental-semantics-contract/bench.py`，原始轮次、源码指纹、环境和进程 RSS
分别归档，cold/observed 交替顺序。parse replay 不冒充 loader 内部分段，进程 RSS
不冒充缓存保留内存。真实编辑首差与 query 延迟已补测；保留内存留待第7期测量；
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

第3期已完成固定 header 的私有小语料原型，见
[函数体实验说明](../scripts/incremental-semantics-contract/body-probe.md)。
在前置函数增加局部变量并插入非 BMP 注释后，复用侧仅检查改动函数，其余10个函数
的 TFun 和逐 body 边界完整 Cx 经纯数据重放后与冷检查一致。源码位置只支持整个
body 平移；函数 key 只覆盖唯一命名的顶层函数。八个可编译负控覆盖身份歧义、
符号/捕获、主次 span、Cx符号、诊断和符号声明位置遗漏；完整实验本地35.66s。
这是保留原取号方案的初步可行性证据，不是全语言迁移完成：nominal/type/effect
引用、其他声明类别、非均匀位置映射、模块最终装配和双后端/Core仍须后续验证。
默认参数合成仍由原 check_module 收尾，依赖读取/失效也未实现；不接生产缓存。

完整迁移首先区分 nominal（含声明效果的 evidence ADT）、trait、type variable、
effect variable 和本地分配（symbol、handler安装）五个引用域。同一个整数可在不同域表示不同身份；每域映射
须单射，缺少引用映射返回失败以供冷回退，不能默认为旧 ID。类型递归遍历覆盖所有
Ty/Eff 构造器，效果集合在映射后按目标 ID 重新规范化。编码 evidence key 由各域映射
显式生成，不对负数 key 用除法猜测原域。此层暂不启用复用，只为后续 TAST/Cx 迁移提供基础。
handler安装 ID 也来自 fresh，但不一定存在于 syms；不能只从符号表收集本地 ID。
部分内部调用将 prompt/evidence key 编成 XInt 参数，后续 TAST 迁移必须按内部操作的
参数语义处理，不能把它们当普通数字原样保留，也不能将用户数字字面量一起改写。
Sig保留参数/binder的声明顺序，Sym的字典元数据按(trait,typevar)映射，handler安装按
本地ID映射。evidence生成名称也含ID，checker与迁移共用types中的名称编码helper；
无法识别的生成名称拒绝复用。调用点evidence实参的顺序重排仍是后续TAST投影任务，
不能以签名里的效果集合已重新排序为由宣称调用点也完成了迁移。

第3期迁移中的补充约束：`XEvRead` 的编码 key 不能完整表示关联效果来源，
相同 trait 的不同类型参数/成员可能具有相同 key。TAST 必须另存完整
`EvidenceRole`（label、variable、associated 的类型参数/trait/成员），
由 checker 在读取构造点写入，lower 仍消费原 key，保持运行时契约。
重定位按完整角色投影 ABI 顺序；不能用 key 去重或通过源码位置猜来源。
该元数据与树/源码投影已随#111验收合并（`0ec2d6b8`）：630项JVM测试、
native主图与新增模块闭包、Core及B==C通过，PR的51项检查全绿。
这证明该批基础设施的回归门禁通过，不代表全语言冷暖等价或函数缓存上线。

完整树投影原型位于 `check/relocate_tree`：显式位置边界表、旧符号表和旧callee
签名视图共同驱动所有 TExpr/TStmt/TPat 分支及 TFun/default/TModule 投影。
内部 prompt 参数单独映射，用户整数和构造器/字段槽不动；效果包先提取完整来源，
按新规范顺序重建 ground 链和非ground环境连接。人工树 owning 及固定header下
23个真实函数、22次前置函数编辑及body内空白变化的冷对照通过；测试视图使用私有
稠密ID域表和本地callee查询，并非生产声明分配器。另一个真实header案例交换
Ask/Tell声明，从新header绑定顺序推导local映射后，隐式参数及效果包与冷产物一致；
跳过pack排序/保留旧origin均命中该对照断言。正例及7个编译负控整套36.10s。
尚缺全形状及type/trait/generic header变化的真实checker冷对照、source view的语义有效性接线、
依赖有效性以及完整Cx/声明调度装配，不将人工模块投影等同于生产模块缓存。

`check/source_projection` 对已经匹配的声明范围按相同token原始拼写生成起点/终点
两张码点映射。`x+1`变成`x + 1`时旧位置1的新起点为2、新终点为1，不能合并成
单张表。字符串token内部只有原始拼写相同时才映射，内部插值编辑仍保守失效。
NEWLINE忽略仅服务位置投影，调用方仍须独立确认AST/依赖一致，不能以token比较
替代语义有效性。assert源文本先校验旧substring，再按两端映射切新源码。
非均匀编辑对照亦修正了私有replay新生成的symbol/diagnostic span；不代表完整Cx
迁移的所有来源字段均已覆盖。源码投影目前持有完整两版文本，内存预算仍需后续收口。

## 五、七期与报告

生产引用映射从声明来源台账派生：每个绑定由DeclKey、引用域和声明内槽定位，
旧/新台账仅连接相同身份，不因整数相等就默认未变。一个域内重复身份对应不同ID、
不同身份占同ID都必须拒绝；不同域允许数字重叠。缺少目标声明时不生成映射，
实际读取该引用的产物随后失败回退。此台账不证明签名/函数体有效，仍需query依赖。
header槽、body临时槽分别标记；标签evidence参数由函数拥有、效果声明标识其角色，
body分配计划将旧产物记录的完整取号区间预留到当前next_id，保留未进入符号表的
临时ID；顶层evidence局部参数按完整ABI角色置换，而非效果名字配对。计划必须在
依赖有效性已验证后使用，不通过冷body反推目标ID。首版拒绝带默认参数的签名，
因为check_param_defaults先于enter_fn取号；默认参数独立产物与嵌套分配覆盖仍需补齐。
默认参数检查已提取为check_param_default入口，原循环仍按参数顺序调用；
显式签名函数的主body另由check_fn_body接收已经检查的defaults。原check_fn保持
先defaults后body的包装顺序。此拆分不改变TFun/TDefault布局、诊断或取号，
只是使调度器可以在两次检查之间捕获真实状态边界。推断函数同样拆出
check_fn_inferred_body，保持签名封定与fns写入原序；默认值重放后仍必须执行或复用
该封定产物，不能只拼回TFun而漏掉后继函数可见的签名更新。
真实正例已分别捕获并投影两个含局部变量的Int默认值，再调用主body入口；
显式与推断签名两类函数的完整Cx/TFun与冷函数及整模块结果一致。
默认值重放的丢符号写入负控要求命中完整Cx断言。泛型默认闭包调用trait方法，
携带字典引用的显式/推断两例也已与冷状态对照；丢默认字典负控要求命中具名字典断言。
默认诊断和全部复杂表达式仍待扩展。
分配计划返回累积的旧/新台账，默认参数按稳定子key登记其区间后传给后继产物。
主body专用body_segment_plan只描述已拆分的检查区间，允许签名仍携带defaults标记；
调用方须已处理defaults并提供其映射。原body_plan仍拒绝未拆分的带默认值整函数，
不能通过取消守卫来假装一个连续区间足以表达所有独立入口。
上述四类默认参数案例已同时重放主body，并与独立冷函数、模块及完整Cx比较；
新版本主body的检查只作为对照，不提供目标分配ID。
不能将同一效果在不同函数中的局部参数合并。真实Ask/Tell重排案例已用生产台账
替代[-1024,next_id)稠密header映射，并扩大到完整Cx对照。对照发现symbol值虽然
都已正确迁移，旧顺序插入仍改变Map的可观察顺序；投影后按目标分配ID恢复插入顺序。
台账收集入口扩展到具名模块的局部类型、alias、trait及方法、效果和函数签名，
要求来源路径与发射owner匹配；导入及整模块装配仍需接线。
impl采集显式接收header pass的逐impl方法签名表：ImplI保留父级类型参数，
方法效果binder却只在该返回表里。源码范围仅用于同版本内关联真实ImplI，
跨版本仍按ImplHead候选key连接；不能用范围相同作为复用有效性判断。
真实header案例已增加两个泛型impl的顺序交换，直接比较映射后的完整方法签名；
入口拒绝缺失/错序签名表和不匹配的owner、类型参数及签名角色，三个移除守卫的
编译负控已命中具名拒绝断言。签名表必须来自同次真实header pass；结构守卫不代替
这个调用方契约，也不验证缓存依赖。导入来源接线仍待完成。
ADT的效果参数原先只保留名字，字段解析时的真实binder ID随临时作用域丢失；
现将已分配的ID按声明顺序保存在AdtI.bound_eparams，不新增取号或改变顺序。
不能扫描字段中的同名变量反推身份，未使用的binder也必须保留。真实header正例已同时
反转ADT、opaque/透明alias、trait和效果，核对类型/效果binder及方法完整签名映射，
然后比较body重放与冷检查的完整Cx。正例不代表生产缓存已接入，入口分支专属负控仍需补齐。

body状态产物先从真实检查前后提取：符号、推断签名、alias解析结果、累积类型参数
约束用逐键变化表示，诊断保存追加后缀，不保留两份完整Cx。
提取必须拒绝声明环境等未声明的写入及诊断前缀改写；Jsig是同owner能力，不能用Eq
比较，owner/lease有效性仍由调用方保证。回放与依赖验证分离，取号、类型/效果/源码
投影及整模块装配接入前不用于生产命中。`current_tparam_bounds`累积旧条目，
不能用上一次body的整表覆盖新模块已经产生的条目。原先将frame.dict_syms也当作
累积表的假设被effectful的完整状态对照推翻：`bind_dicts`在函数入口清空重建，
因此字典表属于body完成后的frame，必须替换而不是合并前序函数的字典。

`body_product.project`复用树投影视图迁移产物中的签名、别名、类型约束、符号、
诊断、frame作用域/字典/效果见证和handler cell。所有fresh分配（包括不在syms中的
安装ID）必须完整映射到目标分配区间；缺ID或源码边界即失败。固定header的22次
非均匀编辑对照已用该生产提取/投影/装配替换旧私有Cx replay，仍与完整冷Cx一致。
夹具仍提供稠密引用域/目标分配映射和旧callee查询，生产分配器、依赖失效和全形状
状态写集尚未验收；不能把这项对照当作生产缓存已接通。

补充真实推断函数及调用者两条状态重放，封定签名必须写回fns并供后续caller读取；
TFun另与原check_module推断调度的产物比较。一个真实test block同时检查in_test
复位、断言源文本和前序test增量取号。alias使用放在正常header路径：
`pass_resolve_aliases`提前解析所有alias，不能清空缓存制造“正常body惰性解析”样本。
Product仍记录alias_resolved变化作为显式写集，不声称正常body必然产生这种写入。

声明候选身份位于`check/identity`，采用调用方提供的已解析模块来源加声明路径：顶层函数/type/trait/effect/const/test
按类别与名字区分，方法/构造器/default以及trait/impl的关联类型和效果成员从其父
声明派生；impl以trait拼写和去位置的subject结构为候选头，泛型绑定按声明槽归一，
包括函数效果行和类型效果实参中的`T.E`投影（保留成员名与槽，模块限定名不折叠）。
重复父声明会连带拒绝全部子身份，
位置与数字分配ID不入key。此key只回答候选配对，不证明header/解析环境/函数体
等价；alias解析和coherence仍由语义依赖检查负责，不能据语法key直接命中缓存。

| 期 | 交付 | 状态 |
|---|---|---|
| 1 | 冷路径对照、阶段基线、Java 观测 | 已验收；证据汇入第2期报告 |
| 2 | workspace 前缀缓存、生命周期、基本逐出 | #107已合并；[验收报告](history/incremental-semantics-p2-report.md) |
| 3 | 稳定身份、具名产物及重定位 | 固定header私有原型通过，完整迁移未实现 |
| 4 | query runtime、依赖失效和 header 接线 | 未开始 |
| 5 | 函数 body 增量、standalone/Playground | 未开始；验收后报告 |
| 6 | comptime/Java/索引与工具消费者收口 | 未开始 |
| 7 | 长会话内存、完整差分、性能与发布验收 | 未开始；验收后报告 |

27个任务包的范围估算为174–281有效人日，不是agent墙钟承诺；原型和测量后滚动修订。
阶段报告必须列准确提交、验收命令/结果、性能样本与环境、已知回退和未达项。
报告位置为 `docs/history/incremental-semantics-p{2,5,7}-report.md`，只在实际完成后创建。

## 六、验收

首刀已实现共享 `observe_queries` callback、host-owned `JsigProbe` 和 JVM
`query_probe`；首刀当时未启用缓存，后续 #107 已接入 Workspace。原型证明无需在共享checker里引入
Java可变对象。共享模块两个测试守八个hook的观察顺序与refusing guard，JVM测试守
计数独立、零查询gate、返回值与参数方向；项目夹具证明经import的Java对象仍触发查询。
`scripts/incremental-semantics-contract/probe.py` 先核验全部锚点，然后实际编译九个
变异体，每个必须命中owning测试，构建错误不算证据；workflow已接线。后续补齐了
真实编辑/query 基线；第7期仍须实测 retained heap，不能用字符预算冒充堆上界。

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
