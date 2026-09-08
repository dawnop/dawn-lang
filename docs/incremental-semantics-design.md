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

header 状态产物必须覆盖 body 入口实际读取的完整表，而非只保存公开导出面。
先按真实 header 前后边界捕获完整持久化表快照（不是逐声明 delta），将诊断记为
追加后缀、分配记为起点和数量；不保存 Java capability 或整个输入/输出 Cx。
frame、symbols、源码身份和宿主环境必须在 header 内保持不变，否则捕获失败。
header 出口清空的 `ty_spans` 与 `record_ty_spans` 属于显式覆盖，不当作输入不变量。
同 revision 装配要求准确分配起点，保留调用方 capability/源码环境/诊断前缀。
跨 revision 还需要全状态投影、当前顺序装配和依赖有效性；未完成这些之前不接缓存。

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

P4 查询运行时采用会话内不可变 owner，key/value 先参数化，不把 Cx stringify 当作
语义相等。owner 固定结果等价回调；真实接线必须区分语义和源码视图 key。
显式 input 写入推进独立单调结果 stamp，revision 只划分编辑批次，避免同 revision
多次写入或删除重建造成 ABA。查询读取成功时记录 stamp；缺失 memo 表示需要计算，
语言层失败查找则应作为普通结果值缓存，并依赖 scope/candidate input。
反向边使输入变更的读者及其后继失效；读取时逐依赖验证，相等结果保留 stamp，
阻断不必要的后继重算。重新计算替换旧依赖边，不累积历史读取。
显式 begin/read/finish 栈处理嵌套查询，读到活动 key 返回 cycle，不改变语言递归规则。
未完成读取不能提交；输入写入、revision 推进和驱逐在计算栈非空时拒绝，防止读写
交错产生混合结果。异常取消使用 abort 退栈，不发布半成品。
本层先由人工图和成功编译负控验收；真实 scope/header/body 读取仍需后续接线，
不能以图算法通过宣称函数增量已上线。

Actual reads first enter an optional function-name log on Cx, retaining the
Option[Sig] returned at lookup time, including misses. Recording is disabled by
default and adds neither mutable host callbacks nor a new checker effect.
Function values, direct calls, and field/function ambiguity checks thread Cx;
body products capture and project answers, while header capture requires the log
to remain unchanged. This observes only part of the function namespace, not every
dependency. Unqualified decisions in needs_expected/resolves_to_value also thread
Cx, preserving short circuits and two-pass argument order; the old Bool/Option
interfaces remain available to consumers that do not collect dependencies.

FunctionAnswer and FunctionCandidates are distinct read facts in the same optional
log. The four diagnostic consumers record the actual candidate list, including its
order, duplicates, and an empty answer; candidate reads are not disguised as missing
function lookups. Body capture and projection retain both variants.

QualifiedFunction retains the qualifier and its successful or missing signature;
ModuleAlias separately retains the actual module path or absence. Qualified values,
calls, expected-type decisions and partial expected arguments thread these facts.
Local shadowing skips the alias read, and a concrete expected type still bypasses
the partial-expectation helper. Explicit apply retains the module-receiver decision
before delegation. Module export metadata, constructors, constants, traits, impls
and Java queries are not yet fully observed, so this log must not enable a body cache.

Export consumers will record focused query results rather than embedding ModExports
in the read log (Cx already owns that record and imports the log). Qualified constants
retain their declaring module and type; constructors retain their ADT identity and
slot. Presence and diagnostic queries retain only their actual boolean or optional
message/hint result. Diagnostic facts exclude source spans, which belong to the body
view. Type and constructor references must be projected with their own domains;
missing mappings reject replay. Pattern/type/impl consumers still need explicit
wiring before these facts can establish complete dependency validity.

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
跨模块来源沿声明模块台账传递，consumer只新增自己的声明，不能从导入别名重造key。
先通过真实exports_of/导入pass的两模块重排案例验证：合并provider与consumer台账时
仍执行同域ID/owner冲突检查，provider内部顺序变化由provider的稳定key解释。
此合并本身不验证导出面或依赖有效性；生产AnalysisCarry/模块调度的接线另行完成。
首个真实案例使用选择性导入Ask/Tell，完整body/Cx重放与冷检查一致，并拒绝consumer
自造provider身份。当前效果语法不接受!dep.Ask，限定模块名的类型/函数案例另行补齐。
限定函数调用的callee查找必须读取旧header的owner+原函数名，而非只查consumer短名。
relocate_tree.callee_signature将覆盖本地/std/模块导入签名表，重复相同记录允许，
同身份不同签名拒绝；trait/builtin保持独立分支。该线性查找是正确性边界，
查询依赖跟踪与索引成本仍需P4/P7接线和实测，不能称为最终查询引擎。
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
| 3 | 稳定身份、具名产物及重定位 | 声明/树/状态迁移已分批实现，完整生产接线未完成 |
| 4 | query runtime、依赖失效和 header 接线 | 人工查询图运行时实现中，真实 checker 读取未接线 |
| 5 | 函数 body 增量、standalone/Playground | 未开始；验收后报告 |
| 6 | comptime/Java/索引与工具消费者收口 | 未开始 |
| 7 | 长会话内存、完整差分、性能与发布验收 | 未开始；验收后报告 |

常量产物迁移方案：共享检查状态增量采用带类型参数的BodyProduct[T]，函数仍通过
Product别名携带TFun，常量通过ConstantProduct携带真实TConst，不构造虚假函数。
捕获/装配共享同一组Cx字段守卫和增量；投影分别递归TFun/TConst及共同状态。
常量具名视图保存当前声明顺序及此前可见常量集合；候选身份不允许跳过可见性依赖
校验。test保留独立角色、当前语法及顺序。此段是P3正在实现的方案，不是生产缓存
已经启用的声明。

完整header元数据投影方案：独立relocate_header覆盖AdtI/CtorI、AliasE、TraitI/MethodSig、
EffectI、ImplI及ModExports；复用分域ID映射，不将构造器槽/字段槽当ID平移。
源码坐标必须按声明owner和可选source选择映射，尤其导出的AliasE仍带声明模块的
target/nlo/nhi；透明alias的-1不是nominal引用。投影保留owner、audience和词法顺序，
不复制新冷结果作为旧产物内容；跨声明重排后的表顺序装配与依赖有效性另由调度负责。
此段为实现前约束，尚未声称header cache可用。

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

### 模块header生产边界（P3接线中）

将check_module既有header前缀抽为check_module_headers，具名ModuleHeaders保存同一次
检查的语法、Cx、函数签名、impl方法签名及const类型；check_module_bodies消费该产物，
原check_module仍按原顺序委托两段。来源台账读取这一边界的真实impl签名，不从最终
TFun或trait模板重建。语法放在产物里，避免调用者给签名索引配上另一个Module。
现阶段这是同revision阶段产品，不是可直接跨revision复用的cache；完整Cx仍是header
快照，依赖有效性及紧凑具名重定位产品仍须后续实现。测试改读生产边界，不再复制源码
前缀生成第二套header流程；冷行为还需重构前后对拍，不能只比较两个新入口。

body检查与最终模块装配已分离：ModuleBodies保存检查结束的Cx、源码函数、
const、impl方法、trait默认实现与test的有序产物。assemble_module_bodies只生成默认
参数辅助函数、登记其签名，并按既有顺序装配TModule，不重新执行checker。冷入口与
后续重放共用该装配入口；它不承担依赖有效性验证，也不使完整Cx自动可跨revision复用。
具名声明索引与紧凑header产品仍需后续接入。验收须覆盖默认函数的字典与签名登记、
各类产物顺序及重构前后冷结果；不能仅以两个新入口互相相等证明行为不变。

重放对照现在将投影后的产物交给该生产装配入口，独立反射比较完整TModule及最终Cx。
八例包含一例具名函数交换顺序后的完整重放、一例修改前置函数后的六个推断body复用，以及六例显式/推断默认参数（含泛型
字典与错误诊断）。不只比较源码主函数，还比较合成默认函数、签名表及Map插入顺序。
仅破坏重放侧的漏函数/清空签名表负控验证整模块比较器，不改变冷侧公共装配器。
这里仍由私有fixture驱动body重放，header仍重查，未接生产cache或依赖调度。

具名函数header入口从同次ModuleHeaders生成：稳定DeclKey关联当前FnDecl与entry Sig，
声明顺序单独保存。构造时验证来源路径、发射owner、无歧义声明定位与签名长度/名称；
不把函数在Module.decls的位置或module_fns序号写进key。body查找使用key取对应header，
不能用旧列表下标配新语法。此入口先覆盖顶层函数；impl/default/test各自的身份类别
仍沿用identity，需后续接线，不将顶层函数索引宣称完整header缓存或依赖验证。

impl方法和trait默认实现已建立独立具名视图：impl的真实注册信息按当前源码
区间定位，方法签名读取ModuleHeaders.impl_sigs；trait默认签名读取同次Cx.traits。
两类key分别为ImplHead/MethodDecl和TraitDecl/MethodDecl，不以同名方法互相替代。
视图保存注册身份，不自行重算或改变现有body输出中的impl_of/default_of；这两个输出
标签仍须沿用checker既有规则，并在后续重放对照中验证。声明级来源不代表依赖有效。
重排header对照已按key匹配两个泛型impl方法及两个效果多态trait默认签名，再用真实
来源表投影签名、注册subject和trait ID；并未因此宣称这四个方法body已经完整重放。

方法body重放保留冷路径的两段边界：check_fn/check_trait_default生成未附角色标签的
TFun，标签在外层补入。impl_body_key从当前Cx与当前impl的trait名/subject计算，按
原顺序在每个impl的方法循环之前执行一次；不以注册ImplI.subject替代。这次解析会
读取当时的current_tparams，旧/新声明重排时标签可能不同，必须在当前上下文重算。
缓存body不携带旧impl标签作为可复用语义输入；默认实现同样在投影后附当前trait ID。
这保留既有冷结果，不改变泛型impl的语言或发射契约。

### 推断函数的entry签名与封定签名

分配计划应校验旧/新header的entry签名，再建立整个body区间的ID映射；封定签名是
body产品的输出，由完整映射投影，不能先假设它的所有引用都属于header。默认参数
分段后的主body同样使用原entry签名。推断函数对照已移除稠密整数映射，改用真实
header台账和逐body的生产分配计划；前置函数已修改的body仍冷算，不伪造它的身份映射。
目前六例覆盖标量与泛型/效果多态闭包返回及各自调用者，显式携带compiler evidence-pack
和内建类型绑定的来源。探测的局部泛型函数被现有语言拒绝，因此不将其当作真实的
body新类型变量案例，也不宣称任意推断类型均已覆盖。另有六个默认参数案例，其中两个
在默认值发生类型错误，全部移动源码位置后比较诊断和完整Cx；丢默认诊断的编译负控
要求命中该错误态的具名断言。

### 来源carry接线（进行中）

AnalysisCarry增加可选HeaderProvenance：保存world标签与各模块的可选分配表。普通冷
入口不记录用户模块来源；opaque Session的内部transition启用，用户表随prefix释放，
std来源baseline随Session释放，
不会从Update导出或跨Session拼接。内部world标签只在该容器内解释，不是全局唯一ID。
用户模块在真实check_module_headers后、body前生成本地header/impl来源；解析/header错误或来源
不确定时记录None。std表来自下面的真实header入口，不拿最终Cx重建丢失的impl注册签名。
后续重放遇到缺失来源必须冷回退；这一步只接来源生成/传递，不启用body缓存，也不
表示依赖有效性和生产函数调度已完成；compiler intrinsic来源使用下述显式生成器。

std接线使用load_std的真实ModuleHeaders，立即生成来源表，不从最终Cx推回impl签名。
std的Cx没有源码路径，ModuleKey.source的空字符串明确表示无路径；Some(path)仍须
逐字匹配，不能把路径缺失解释成通配。StdCtx保存以std局部world标记的表，Session
构造时验证旧world并重绑定到容器内world；拒绝混合world表。Session保存不可变baseline
carry，编辑时直接从baseline起步，不重复扫描std声明构造来源。

compiler来源从prelude ADT/trait/impl与builtin签名的实际元数据生成，而不是为整数区间
批量放行。ADT/trait以声明名、binder槽标识；builtin共享模板按模板名标识，prelude
impl引用已登记的binder时保留原身份，独有的集合模板另登记。擦除后的runtime类型参数
取erased_ev_ty的实际绑定。该baseline仅属于当前编译器实例的会话，不是跨编译器版本
可复用的磁盘缓存。来源缺失仍拒绝投影。

### Qualified-pattern observation (in progress)

Qualified constructor expressions and refutability decisions must share the same
observed constructor query. Refutability carries the updated context through
recursive tuple/constructor patterns, stopping at the same first refutable span
as the cold checker. The let/for diagnostic consumers retain that context.
Direct qualified pattern checking will observe module presence before constructor
lookup, retain explicit missing constructor answers, and observe the resolved
constructor-diagnostic message/hint only on the same failure path as before.
The diagnostic query has its own kind so value/function/constructor answers cannot
alias. Error recovery must keep threading reads from nested argument patterns.
This does not yet observe local constructor tables or ADT constructor counts;
those remain required dependencies before cache admission.

### Type-resolution observations (in progress)

Qualified type resolution reads alias headers, already-resolved alias targets,
nominal name bindings and the nominal arity/effect-parameter metadata that drives
its checks. Observe these at their actual branch boundaries, preserving the
alias-first order and avoiding reads after rejected argument arity. Alias headers
contain only the fields this resolver consumes, not AliasE's unresolved AST or
source spans; this avoids a dependency cycle through Cx. Type and effect binders
project in distinct domains, and only opaque alias IDs are nominal references.
Transparent aliases have no nominal ID to relocate. Builtin/compiler inputs,
local alias resolution, associated projections and Java reflection still require
their own validity boundary before production cache admission.

Local nominal lookup is observed only after the existing type-parameter, alias,
builtin and Java branches decline the name. Missing-name diagnostics retain their
resolved message/hint, including suggestions from the original ordered candidate
pool. This does not substitute for observing earlier alias/Java decisions: a
new shadowing declaration must invalidate those decisions as well.

Local alias resolution must distinguish a cached target (including `TyError`)
from a missing cache entry. A cached result short-circuits declaration expansion
and cycle checks; a missing declaration target also returns before consulting the
in-flight set. Record the cache answer and the actual cycle-membership decision
at those boundaries, without introducing reads on skipped paths. These facts do
not replace the separate dependency on the alias declaration and its owner-scoped
target syntax. Retaining and relocating that syntax remains necessary before
admitting a product that expanded an uncached declaration.

The source fact retains the alias name, declaring owner, and optional complete
`TypeRef`, recorded after a cache miss and before target absence/cycle handling.
`semantic_reads.project_with_source` and the corresponding body/constant product
entry points take an explicit owner-aware syntax projection callback. Existing
source-free entry points reject a present declaration target rather than retain
its old spans. The owner-aware implementation can use `relocate_header.type_source`
with its declaration-scoped `HeaderView`; it must not use the body's local span
map for a foreign declaration. Runtime wiring of these source views remains
separate outstanding work.

Local alias lookup now records its positive or negative header answer after the
reserved-return builtin and current type-parameter short circuits, and before
ordinary builtin/Java/nominal fallback. Local and qualified header answers share
their field extraction and reference-domain projection. Uncached expansion also
records the actual type/effect binder lists after source/cycle checks and before
seeding the declaration environment; skipped paths do not acquire binder reads.
This closes those alias decision inputs, not the remaining builtin/current
environment, associated type/effect, Java, or runtime scheduling boundaries.

### Associated-member read boundary (implementation in progress)

Associated type/effect resolution must retain the scoped subject answer, its
optional ordered trait-bound list, and each queried trait's associated-member
names with the type/effect axis identified. Missing subjects short-circuit bounds
and members; repeated bounds still follow the existing owner deduplication rule.
Subjects project as their actual types, while bound/member trait IDs require a
separate trait-domain callback. Reusing the nominal mapper or fabricating a type
to smuggle an integer into another reference domain is not valid projection.

### Ordinary effect read boundary (implementation in progress)

Effect atoms retain the existing precedence: intrinsic `io`, associated
projections, declared effects, then lowercase scoped variables. A declared
answer records the actual row produced from the name table and effect metadata,
including its ID and display label; a miss is distinct from a pure row. Scoped
variable reads retain both existing rows and misses before fresh allocation.
Repeated atoms must read the updated scope and must not allocate again. Both
answer forms use the complete effect-row projector, which preserves the existing
distinction between nominal label IDs and effect-variable IDs. They cannot use
one raw-ID mapping for both. Observation must preserve complete state, diagnostics and allocation;
these facts alone do not establish runtime query wiring or cache admission.

### Type environment read boundary (implementation in progress)

Named types query the builtin table before the scoped parameter table, so
return-only reserved names still win over recovery-scope collisions. Alias
resolution precedes the later ordinary builtin lookup. Record each lookup where
it occurs, including negative answers and repeated builtin queries. Visibility
checks record the actual std-module mode only when that argument is consumed.
Builtin metadata retains name, parameter spellings, access policy and build
shape; leaf builds project their actual Ty through the type domain. These facts
do not replace complete Java dependencies or runtime query wiring.

### Java read boundary (implementation in progress)

Named Java types retain the local class-name answer, including misses after
builtin and alias short circuits. Only an accepted zero-argument use queries
class metadata. Record the actual plain-data JClass answer, not a host Class,
classloader or oracle closure. These names and metadata contain no compiler ID
or source span to relocate. Their validity still requires the target classpath
and oracle lifetime; recording answers alone does not authorize cache reuse.
Other Java query kinds and their checker consumers remain separate required work.
The class-info consumers for reference return types, static/instance dispatch and
SAM/List diagnostics share the same observed lookup, retaining their returned Cx.

### Java candidate-list reads (implementation in progress)

Capture the actual ordered methods, constructors and static fields returned by
the metadata oracle before checker filtering, sorting or overload selection.
Empty answers are dependencies too. Preserve every plain-data metadata field,
including descriptors, declaring owners, parameter order and duplicate entries;
projection does not reinterpret these strings as compiler IDs or source spans.
Consumers must retain the observed Cx on success and diagnostic recovery paths.
Constructor queries remain after argument-error and instance-new rejection;
method queries remain after argument-error rejection. This step does not replace
assignability, SAM/component, import-name, namespace or oracle-lifetime reads.

### Java import and namespace reads (implementation in progress)

Observe the Java-enabled gate only when a Java import is visited. Disabled
imports still refuse without querying the oracle; enabled imports retain the
actual find-class answer, including misses, before checking local-name conflicts.
Subsequent imports must observe the namespace after earlier accepted writes.
Record class-name lookups at static dispatch/field targets and declaration
collision checks where the original short-circuit chain actually reaches them.
Do not move lookups ahead of constructor/constant shadowing or syntax guards.
These observations do not replace the other namespace answers in those guards,
nor establish target-classpath or oracle-lifetime validity.
When inferred functions are pending, retain the actual ordered Java namespace
keys before constructing the static-receiver set. Explicit-only modules still
skip this enumeration, and constructor/constant shadowing remains unchanged.
Value-versus-module-alias resolution also retains the Java name answer only
after local variables, functions, constructors and constants have declined.
Owning tests compare the complete ordered read sequence, including repeated
alias queries, rather than filtering unrelated facts from the observation log.
The diagnostic corpus projector follows the exact immutable tuple result slot
now that message helpers also return their observed context. It retains both
the ordinary tail and nested early-return wording, without borrowing another
slot, mutable/written bindings or a shadowed helper. This changes diagnostic
extraction only; existing diagnostic golden texts remain unchanged.

### Java oracle scoring reads (implementation in progress)

Retain assignability's ordered superclass/subclass query and Boolean answer,
SAM lookup's optional complete method metadata, and array component lookup's
optional name. Primitive shortcuts must not query the oracle. Scoring must
thread context through every visited candidate, including rejected candidates
and unsuccessful fixed-arity attempts before varargs fallback. Finalization
must retain repeated queries rather than reuse an unproved answer.
SAM parameter/return conversion also reads class metadata; route these remaining
queries through the existing class-info observer. Preserve argument visitation,
candidate order, diagnostics and emitted conversion metadata. These facts alone
do not establish oracle lifetime validity or production query admission.

## 七、不做的

不新增语法、改变推断/可见性、扩展comptime语言能力；不做磁盘缓存、跨进程共享、
并行checker、watcher、增量parser或增量机器码发射；CLI共享语义入口但新进程不热启动。
不把pending扫描优化算cache收益，不把第2期称为Playground提速，不发布或部署到生产。
