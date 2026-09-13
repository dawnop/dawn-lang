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

`check/identity` 在枚举声明身份的同一趟里另给出本修订的 `DeclKey` 起止码点视图。
键本身与文本无关，视图专门承载会被编辑挪动的那一半：声明内偏移在渲染或下降时按
视图解析成绝对位置，声明之外的编辑因此不再触及产物。被重复父声明毒化的键在视图中
一并缺席，理由与身份枚举拒绝它们的理由相同，不在两个同键声明之间挑一个。视图随
分析 carry 按解析后的模块路径积累，冷路径与会话路径共用同一条构造路径，命中前缀的
步骤原样带着此前各模块的视图。位置视图不判定语义有效性，那仍归各自的读取台账。

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

The callee lookup that paragraph describes is now index-backed. `callee_index`
makes one pass over the three tables a call site can name, `cx.fns`,
`cx.std_fns` and `cx.module_fn_sigs`, and files every non-builtin, non-trait
signature under the pair `(owner, name)` the call site spells, recording a
conflict when two different signatures land on one key. `callee_signature`
takes that index and answers with one hash lookup; the builtin and trait
branches are unchanged, because their own tables are already keyed by the
question. The linear scan is kept as `scanned_callee_signature` and is the
oracle the index is checked against, not a production entry: the index answers
exactly what the scan answers for the same `cx`, including the conflict
refusal, which the inline tests assert over synthetic duplicate keys and the
typed-projection fixtures assert on every query they make. The index is owned
by `scalar_replay`'s prepared candidate and lives exactly as long as it: it is
built once per candidate revision beside the allocation reservation, from the
header revision's `cx`, so widening admission cannot put a module-sized pass on
the per-body path. Admission of named calls stays closed. `scalar_shape.same`
pairs no call node and `recorded` accepts no read but `AssignableType`, so the
relocation each admitted body receives still refuses every call site; the index
is the prerequisite for widening that class, not the widening.

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

未写下的表读取是这条线的结构性风险，动态门禁看不见它：夹具用哪两个 revision 写的，
body 就在哪两个 revision 上重放正确，换一个没人想到的输入才丢诊断。`cx.alias_shadow`
读 `cx.module_aliases` 报告遮蔽 imported module alias，不留任何 fact，候选 revision
新增 `use dep as y` 时就丢掉了那条诊断（2012333e 在 admission 侧补了守卫）。该类问题
由 `scripts/journal-reads/check.py` 静态兜底：从 `check/checker` 的七个 body 入口
走保守调用图，收集可达代码里每一处 `Cx` 表读取，与 `scripts/journal-reads/ledger.txt`
双向对账，逐条给出 logged/product/write/uncovered 四种判词，uncovered 必须写明理由
并声明 `backlog` 或 `compensated-by=<site>`（被点名的守卫若不再读该字段就红）。
它是词法扫描，不跟随闭包里的 `Cx`，`logged` 只证明同一条调用链上记录过某个 fact，
不证明那个 fact 的答案就是这次读取的答案；限制逐条写在 `scripts/journal-reads/README.md`。
每次扩大 admission 类别（调用、泛型、方法）之前，先看它的 `--uncovered` 清单。

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

### Local value namespace reads (implementation in progress)

Observe local constructor identity and constant type lookups, including misses.
Constant declaration-order visibility is its own Boolean answer; hidden later
constants must not be queried before the original cutoff guard permits them.
Already-resolved qualified constructors skip the local lookup. Constructor ADT
identities project through the nominal domain while slots remain declaration
positions; constant types use the type projection domain. Shape, shadowing,
pattern and SAM-prepass consumers must also be wired before admission.
Constructor-count and field-arity answers are separate facts keyed by nominal
identity (and constructor slot for arity). Both local and qualified refutability
checks retain the count before an early return. SAM deferral and arity prepasses
thread their contexts independently, preserving repeated lookups and syntax
shortcuts before the Java oracle is consulted.
Value resolution, static field/method receivers and inferred-return dependency
scanning also retain constructor-before-constant shadow checks. A constructor
hit skips the constant table; syntactically ineligible static receivers skip
both. These guards use declaration presence, not constant body visibility.
Local pattern resolution retains constructor identity even on recovery paths.
Expected-type probes retain constructor identity, field arity and the existing
nominal shape fact (including generic arity and record syntax), both for bare
constructor values and explicit applications. Constructor field types and
diagnostic suggestion pools remain separate dependencies to cover.
Constructor calls, patterns and function values now read a focused nominal
header (identity, name, record syntax and ordered type binders) plus the selected
constructor's complete ordered fields. Projection translates both query and
answer nominal identities, every binder and field type, while preserving field
names and constructor slots. Consumers receive the focused header rather than
an entire ADT table entry, preventing accidental unobserved access to sibling
constructors or ownership metadata through that answer.
Undefined-constructor diagnostics observe nominal-name resolution before the
ordered constructor-name list, or declared-constant membership before the
ordered suggestion pool. Pattern suggestions exclude constants; value
suggestions concatenate both namespaces without deduplicating or sorting.
These reads occur after argument recovery, matching the original diagnostic
ordering, and later branches are skipped when an earlier diagnostic applies.

### Ordinary record field observations (implementation in progress)

Observe nominal headers at ordinary field-access classification and diagnostics,
then selected constructor fields only when the receiver is a record. Preserve
the existing error-type shortcut, repeated header reads, sum-type refusal,
field ordering and generic substitution. This extends the method-field path;
it does not yet cover recursive diagnostic rendering or exhaustiveness queries.
Handler evidence-record fields use the same selected-constructor observer.
The declared effect's identity is also its evidence record's nominal identity;
the existing projection must retain that relationship. Handler operation
metadata is captured with the full effect declaration (including ordered
operations, control flag, owner and audience), projecting both query and answer
identities. Handler name resolution retains optional effect identity and reads
the ordered suggestion pool only on a miss, before the original recovery path.
Recursive handler dependencies beyond these declaration reads remain.

### Exhaustiveness observation seam (implementation in progress)

The pure usefulness algorithm receives immutable read state containing its
ADT view and optional log, not the full checker context. Generic field
instantiation now returns selected constructor metadata observations alongside
its result; the cold wrapper delegates with logging disabled. Recursive
simplification now threads the state through alternatives, nested constructors,
tuples, list prefixes/suffixes and matrix rows, preserving earlier reads when
a wildcard short-circuits later alternatives. Usefulness recursion now carries
the read state alongside remaining fuel and the optional answer. Constructor
specialization precedes field instantiation, complete-head traversal retains
constructor count and per-slot arity reads, and both early answers and exhausted
budgets return the state reached so far. Missing-list probes thread that state
across lengths while retaining a fresh usefulness budget for each probe.
The public observed entry points share the algorithm with logging-disabled
wrappers. Let, for and match consumers now return these observations to Cx,
including Boolean and list missing-case probes. Missing ADT diagnostics observe
constructor count, each probed arity and selected constructor metadata for names
only when a missing case is reported. Consumer tests require the actual let,
for and match paths to retain their count read and preserve cold diagnostics,
typed modules and allocation. Compiling context-drop controls cover those three
entry paths. Missing-case owners compare exact diagnostic text, count/arity
query order and selected constructor-field slots for guarded-only Option and
list matches. Five additional context-drop controls target diagnostic count,
arity, per-case analysis, constructor names and list probes. Recursive helper
controls additionally corrupt metadata observations, normalization state,
alternative recursion and public/list return state. A surviving query-state
drop exposed a gap in the original helper tests; the public-boundary owner now
requires both normalization logs independently of the final Boolean answer.
The expanded controls and broader acceptance must pass before this batch lands.
This integration does not establish production cache admission on its own.
The 8192-step and 4096-row limits and unknown results must remain unchanged.

### Witness dependency capture (implementation in progress)

Implementation existence is a distinct query from selecting an implementation:
`has_impl_at` consumes only presence, while witness construction and associated
type/effect reduction consume the selected implementation's fields. Record
presence queries with the complete trait and subject inputs, including misses;
recompute them against the candidate implementation table before reuse. Relocate
the trait through the trait domain and the subject through the type domain.
Do not promote a presence fact into evidence that a selected implementation or
its associated bindings are unchanged.
The main witness branch consumes the selected implementation's type-parameter
count, not its complete metadata. Its arity query records `None` separately
from `Some(0)` and conditional arities. Conditional bounds are covered by the
separate ordered sub-goal query. Associated bindings and emitted implementation
bodies still need their own dependencies; neither query proves those unchanged.
The general witness resolver also records the trait name at its original eager
lookup, after error absorption and before projection or opaque fallback. This
query observes only the name consumed by diagnostics, not all trait metadata.
Its ID uses the trait relocation domain and its text remains unchanged; a
candidate rename must be detected by recomputing the query, not by projection.
Dictionary lookup records the rigid type binder, required trait and optional
local symbol. These are three independent identity domains. Projection without
binder/local mappings refuses these facts; a missing dictionary remains a miss.
The resolver must retain the read before forwarding and capturing the symbol.
Associated-type reduction may be observed at its pure result boundary: record
the complete input type and resulting type, then recompute the canonical
reducer in the candidate context before reuse. This preserves opaque fallback,
binding selection and recursive unification without a duplicate reducer or an
extra traversal that guesses which implementations were consumed. Both input
and answer require type relocation. This aggregate query validates only the
reduction result, not emitted implementation bodies. Index and iterable item
consumers retain the query before checking subsequent expressions. Inference
and effect-reduction consumers remain required migration work.
Effect reduction additionally records the complete ordered type-binding map as
binder/type pairs, alongside its input and result rows. Binder keys, bound types
and effect rows use their separate relocation domains. The canonical reducer
is recomputed with those bindings in the candidate context; a projected answer
alone does not validate it. Call effects and emitted associated-evidence
arguments retain this observation before their subsequent consumers.
Type-contained effect reduction uses the same complete binding input and a
type-valued input/result query. Function-value instantiation, call argument
expectations, mismatch rendering, return types and synthesized default calls
must thread both associated-type and type-effect queries in their original
order. Internal unification remains a separate pure query boundary to cover.
Unification observations contain declared/actual types, complete ordered input
type/effect bindings, complete output bindings and the match verdict, including
partial bindings on failure. Recompute canonical unification in the candidate
context. Type-binder and effect-binder keys are distinct relocation domains;
never project either through nominal or local symbol IDs. A failed first pass
followed by a retry retains both queries in order.
The candidate revalidator distinguishes an unequal supported query from an
unsupported query. Neither may admit reuse. It invokes canonical query helpers
in an isolated observation context and compares the newly computed complete
fact, including ordered inference outputs. Binding lists must round-trip
through their maps without duplicate loss or reordering. This initial witness
query validator is not body-cache admission: namespace/header queries and
cross-revision candidate construction must also be integrated.
Context-owned namespace and constructor queries are revalidated through the
same canonical observation helpers, not by comparing saved answers to each
other. A candidate may have removed a nominal declaration or constructor slot;
reject such retained queries before calling helpers that assume a valid ID.
Preserve failed lookups, candidate order and scope-sensitive constant visibility.
The supplied context must represent the corresponding body point; this API
does not reconstruct local scopes or authorize body reuse on its own.
Both validators take the relocation onto the candidate revision explicitly, so
a recorded fact is revalidated where it lies rather than rebuilt first. A query
input is still moved, because the recomputation reads the candidate's own
tables; the recorded answer is not, because the comparison walks it beside the
observed answer and maps one reference at a time. The comparison is defined to
answer exactly what projecting the fact and comparing for equality answers, one
arm per projection arm, and a reference the relocation cannot move refuses the
fact the same way projecting it would have. Normalized effect rows are the
exception the definition needs: relocating the atoms of a union or a label
carrier can reorder and collapse them, so those two shapes are compared through
the canonical builder rather than in place. The same-revision entry points
supply the identity relocation and are unchanged by this. This is a cost
statement, not a strength statement: reuse admits and refuses exactly what it
did. What it buys is that a caller which does not install the projected read
log never builds one, so the log costs the size of the facts it validates
instead of the size of the facts it validates plus a relocated copy of them.

The body scheduler must remain the single owner of inferred dependency order,
constant visibility, method tagging, default synthesis and diagnostic order.
An explicit, state-threaded body executor provides the integration boundary:
the cold entry uses canonical body checkers; a session executor may capture or
replay validated products at those same entry points. The executor must receive
the current context, not a saved header context. Introducing this boundary does
not itself enable reuse; candidate admission and cross-revision projection must
be validated before the session supplies any replaying executor.
The explicit recorded module-step entry records body products through that
executor. Each entry holds the actual syntax/signature input and keyed writes;
it does not retain the entry Cx or Java capability. Per-body observation logs
are isolated and then restored to the caller's logging mode. Ambiguous keys or
capture failures omit the entry without changing cold checking or recovery.
No recorded entry is replayed yet; ordinary module steps and prefix sessions
do not enable recording. A local synthetic measurement on 2026-09-12 found
that scanning accumulated maps for each product made 1000 simple bodies take
roughly 900 ms to record versus roughly 3 ms to check without recording.
This is recorder overhead, not a cache speedup. Before enabling recording in
sessions, replace repeated whole-context map scans with verified write tracking
and measure the complete cold/record/replay paths. Module-prefix admission
rules remain intact.
The first write-tracking implementation records symbol, signature, alias and
parameter-bound keys at their actual body mutation owners. Journal capture,
append and projection preserve repeated writes and distinguish local-symbol
IDs from type-binder IDs. The strict extractor remains available independently;
the journaled extractor compares touched keys, checks table cardinalities and
still validates the unchanged environment. Producer coverage remains essential:
equal cardinalities alone cannot prove that an existing-key update was logged.
The same 1000-function fixture then recorded in roughly 280 ms on 2026-09-12,
down from roughly 900 ms, but still far above cold checking. In particular,
immutable environment comparisons still revisit module-wide data per body.
Recording remains opt-in until the remaining cost and admission proof are closed.
Environment membership checks now use a trie fold in the journaled path,
preserving cardinality, key presence and value equality without materializing
and sorting entries. The strict extractor still uses standard Map equality.
Three compiling controls separately break cardinality, membership and value
checks; reordered entries remain equivalent. The same private 1000-function
fixture measured roughly 46–53 ms recording in warm rounds on 2026-09-12,
versus roughly 3–8 ms cold (eight alternating-order rounds, JVM 21, SerialGC).
This removes sorting overhead, not the remaining repeated environment scans;
it does not establish linear scaling or justify enabling session recording.
A lexical inventory pins all production Cx table-constructor owners, while
an independent actual-scheduler fixture compares strict and journaled products
and their replayed tables across all six roles. Six compiling controls bypass
the real symbol, evidence, dictionary, bound, inferred-signature and lazy-alias
writer calls. The lexical inventory is not a type-checked call-graph proof.

The opt-in executor also admits primitive parameters and immutable unannotated
locals. Admission pairs the two parsed bodies over a closed expression and
statement class instead of trusting equal token streams: the token projection
drops newlines, so one token stream can carry two statement boundaries and two
meanings. Every variable reference must belong to a corresponding lexical
binder, the recorded allocation interval is reserved at the current scheduler
entry, and every fresh symbol and journal event is projected. The interval is a
bijection onto the reserved target range, including fresh IDs that never enter
the symbol table. Calls, closures, generic contexts, annotations and unsupported
statements stay cold until their query-context proofs exist.

Binder names carry one dependency the write journal does not record. The
checker reports a local whose name shadows an imported module alias, and reads
the alias table without leaving an observation. The literal-only class never
reached that declaration path, so admitting parameters and locals opened the
gap: a candidate revision that adds the alias lost the diagnostic. Admission now
collects the class's binder names and compares them against the candidate
revision's aliases. The collector fails closed on every node the shape pairing
does not cover, so widening the class without widening the collector refuses
instead of dropping a diagnostic.

Oracle coverage adds shifted prefixes, reordered declarations, changed literals,
changed references, shadowing locals, added annotations and re-parsed statement
boundaries. Seven compiling controls run against the complete-product oracle and
ten against the executor's own refusal tests, including controls that neutralize
the tree pairing, the alias comparison, the reserved interval, the projected
local symbols and the projected journal. This remains an opt-in module executor
with no performance or phase-5 claim.

The first cross-revision executor admits a closed scalar-literal producer:
explicit Int/Float/Bool/Unit return, no parameters, defaults, binders or effects,
and precisely the successful primitive return-compatibility observation.
It takes one parsed snapshot per revision, pairs unique
declaration identities, derives compiler/local allocation tables, projects
source boundaries and product state, and revalidates the observed return
compatibility before assembly. A missing proof or unsupported role executes
the canonical cold callback. Checked/reused counts describe actual callback
execution, not candidate lookup or successful projection alone.
Pass-through checker fields come from the current scheduling context, and
private logs are adapted to the current observation mode only after validation.
This opt-in module executor is an integration step, not general query-context
admission, a session implementation, or phase-5 acceptance. Declaration indices
and header-ID mappings are prepared once per module replay; the zero-allocation
eligibility guard makes that mapping sufficient without reserving a new body
interval. Performance acceptance remains outstanding.
An independent Java counter instruments canonical checker entries in a private
subject, while a reflection oracle compares every ModuleBodies and Cx field
over thirty-two cold/replay pairs. A compiling disguised-cold mutant recomputes
the body while reporting a hit; the entry counter must reject it even though
the semantic products agree. Separate mutants lose accumulated symbols or
retain stale source coordinates, and must fail the full-product comparison.
The replay API benchmark (100/500/1000 zero-parameter literal functions, eight
alternating-order rounds, JVM 21 SerialGC, headers prepared before timing)
includes source snapshot checks and provenance admission. At 1000 functions,
the initial prepared-index path took roughly 150ms versus roughly 1–4ms cold.
Whole-source code-point slicing still repeatedly sought from the file start.
An opaque source index now binds code points to their snapshot and projects
local declaration slices before translating boundaries back to file positions;
the original unindexed mapper remains the equality oracle. The same benchmark
then took roughly 28–39ms in warm rounds on 2026-09-12. This is still slower
than cold checking these trivial bodies and is not grounds for default enablement.

Replay inputs are versioned snapshots, not source text. `check/source_snapshot`
lexes and parses one revision once and keeps the resulting module beside the
code-point index and the declaration token facts the token projection needs;
all three come out of that one lex, because `parser.parse_module_lexed` hands
back the code points and the token stream its own parse ran over. Its
representation is private and its only constructor parses the text it indexes,
so a snapshot's tree is always the tree of its own text and no caller can pair
one revision's tree with another revision's code points. The owner that checks a revision's headers checks them
from that same tree, and replay proves provenance by comparing the snapshot's
tree with the headers it accompanies. That is the admission evidence the earlier
reparse produced, at the cost of one structural comparison rather than a lexer
and parser run; no admission check was dropped, and the executor no longer
imports the parser at all. Retaining a snapshot beyond the call is what makes
this sound as well as cheaper: the recorded revision's snapshot is kept with its
recorded products, and the candidate revision's snapshot is the one the current
analysis just parsed. This changes no session input shape: no default analysis
path records or replays, and `driver/incremental` is untouched.

Measured 2026-09-12 on the local benchmark (1000 bodies per class, 30 rounds
dropping 12, three campaigns each side, JVM 21 SerialGC, shared machine, medians
of campaign medians). The per-module cost replay paid before reaching its first
body fell from 12.5 to 162.8ms to 3.6 to 15.4ms, and stopped tracking source size: the
195KB inference-heavy module paid 162.8ms of it and now pays 4.8ms, while the
remaining term is `allocation.local_headers` and tracks declaration count
instead. Whole-call replay fell 13% to 80% by class. Snapshot construction, the
parse the revision's owner already owed, is 3.7 to 78.9ms and is not replay's cost;
what replay still pays for provenance is 0.2 to 6.0ms of tree comparison. One
retained snapshot costs 7.2 bytes of heap per source code point for its index
(161KB to 1.4MB across these modules, attributed by forced-collection heap
deltas, not estimated); the tree it also holds is the headers' own tree and is
not new memory.

This does not make replay competitive. With the module-level cost removed, the
per-body admission guard is the whole remaining wall: 51.5µs per reused body for
the literal class and 77.7µs for the primitive-parameter class, flat in module
size, against 1.4µs and 13.5µs to check the same bodies cold. Source projection,
which was 47% of the literal class's replay before the class widened, is now
12.4µs and 89.3µs per body respectively. Replay still loses to cold checking on
every class that it admits, by a factor of 13 to 50, and phase 5 remains
unstarted.

Admission is split by which revision can answer it. `scalar_replay.admit` binds
one recording to the snapshot whose headers produced it and settles everything
the recorded revision decides alone: the product's own field guards, its
observed reads, the local symbols it installs, and the binder names its body
declares. It runs once per recording, not once per replay and never once per
candidate body. Replay then takes that value, and per body it asks only what
the candidate revision can change: the header half of class membership, the
declaration pairing, the recorded header relocated onto the candidate one, the
alias question over the recorded binder names, and the reserved allocation
interval. Class membership of the *recorded* body is not re-asked anywhere: the
pairing proves it, because `scalar_shape.same` succeeds only when both trees
consist of nodes this class supports, and a guard no fixture can distinguish is
not a guard.

The recorded binder list replaces a second walk of the candidate body. It is
sound because the pairing establishes the two bodies have the same block
structure and the same `let` names, and the parameter-name comparison
establishes the same seed; the alias diagnostic `checker.declare` reports leaves
no journal entry, so the question itself must still be asked of the candidate
module's alias table, and it is.

Reserving a body interval no longer rebuilds the module. `allocation.body_plan`
built two extended binding tables and a whole relocation for every body, so a
module's entire header table was walked once per body; that is why the guard was
flat in module size and large. `allocation.reserver` does the pair-dependent work
once (the header relocation, its reverse index, and the IDs each table already
owns in the three domains an interval reserves) and `allocation.reserved_plan`
then costs the interval. It is pinned to the old path by an inline oracle:
for the same inputs it returns exactly `body_plan`'s relocation, or refuses
exactly where `body_plan` refuses. `relocate.extend` is the matching primitive,
equal to rebuilding with `relocate.new` over the merged maps and refusing the
same conflicts, without revisiting the maps it extends.

Token facts are taken once per revision too. `source_projection.between_indexed`
re-lexed both declaration slices on every admitted body and then wrote one map
entry per code point, twice over, and the executor paid that per reused body.
A snapshot now lexes its revision once and keeps, for each function
declaration, its token kinds, its token spellings and its token boundaries;
pairing two declarations is two list comparisons, and the relocation it returns
answers each boundary from the token that covers it by binary search. The map
`between` materialized is gone: `relocate_tree.View` takes two boundary lookups
rather than two tables. The original `between`/`between_indexed` remain, and
remain the equality oracle: an inline test compares the paired form against them
position by position over a declaration range.

Pairing is still two parsed trees, not two token streams. A token comparison
that ignores newlines cannot separate `let b = a` followed by `- x` from
`let b = a - x`: one token sequence, two parses. That pair is an inline test and
a fixture in the product oracle, and it is why `scalar_shape.same` stays on the
replay path rather than being replaced by the token comparison.

Measured 2026-09-12 on the local benchmark (1000 bodies per class, 30 rounds
dropping 12, three campaigns per side interleaved, JVM 21 SerialGC, shared
machine, medians of campaign medians; reused counts unchanged at 1000, 1000, 2
and 0). The per-body admission guard fell from 51.6 to 1.0µs for the literal
class and from 78.0 to 10.9µs for the primitive-parameter class. Source
projection fell from 12.7 to 2.6µs and from 89.9 to 22.2µs. Whole-call replay
fell 90% and 78%, to 6.9ms against 1.2ms cold and 38.0ms against 13.8ms cold.
For the classes replay refuses, what it pays to reuse nothing fell to 1.5 to
15.2µs per body.

Replay still loses, and the margin is now small enough to name what is left. The
marginal cost of reusing one primitive-parameter body is 34.8µs against 13.8µs
to check it cold, and it decomposes as: `body_product.project` 19.8µs,
`allocation.reserved_plan` 6.5µs, `scalar_shape.same` with the binder scan
2.2µs, the token pairing 2.3µs, `body_product.assemble` 1.4µs. Relocating a
typed tree now costs more than type-checking the body that produced it, so the
projection of the product, not admission, is the next thing that has to get
cheaper.

Snapshot construction no longer pays for this three times over. It used to lex
its revision three times: `parser.parse_module` decoded the text and tokenized
it to build the tree and then dropped both, `source_projection.index` decoded it
again, and `tokens_of` lexed it again. `parser.parse_module_lexed` returns the
code points and the token stream beside the tree and the diagnostics, and
`source_projection.index_cps` and `tokens_from` take them instead of recomputing
them, so a snapshot is one lex. `parse_module` is that entry's wrapper and its
behaviour and diagnostics are unchanged; `tokens_of` keeps its own lex and is
the oracle the one-lex path is compared against, field by field, on clean
revisions, on one the lexer rejects and on one recovered by `sync_decl`.

Measured 2026-09-12 on the local benchmark (1000 bodies per class, 30 rounds
dropping 12, three campaigns per side interleaved, JVM 21 SerialGC, shared
machine, medians of campaign medians). `source_snapshot.of` fell from 99.2 to
79.8ms for the primitive-parameter class, from 169.2 to 117.5ms for the 195KB
inference-heavy one and from 7.4 to 4.4ms for the literal one. Replay itself is
unchanged, as it has to be: both snapshots are built outside the timed call, and
the residual spread across five campaigns per side is smaller than the drift of
the machine over the session. The arithmetic is still that a revision's snapshot
has to be replayed against several later revisions before it repays its own
construction, now at 60 to 80% of the price.

Inference branch eligibility is a dependency too: `is_concrete` distinguishes
rigid parameters in the current scope from unbound variables. Record its full
type input and Boolean answer at the actual short-circuit point; candidate
validation requires the corresponding scope, not an arbitrary module header.
Assignment compatibility also depends on the candidate module's opaque-type
visibility. Record source type, target type and the canonical Boolean result
before each actual compatibility decision. This covers successful assignments
as well as diagnostics; checking only rendered refusal text misses successes.

Thread observations through structural-gap recursion in the original order:
implementation presence first, then tuple/container elements or nominal fields,
stopping at the first gap. Preserve the existing visited-name policy and opaque
fallback order; changing either is a separate semantic decision. Subsequent
work must cover selected implementation metadata, ordered conditional sub-goals,
trait metadata and dictionary lookup, and associated type/effect reduction.
Do not enumerate unrelated implementations to compensate for missing consumers.
The private `probe_witness`/`probe_args` pair has no incoming production call:
its only references are internal recursion. It is not a prerequisite for
production dependency capture. The reachable opaque ordering fast path must,
however, retain each implementation-presence miss before peeling to its target,
even when the final primitive comparison bypasses witness construction.
Production body caching remains disabled until these boundaries and candidate
revalidation are complete.

### Diagnostic rendering queries (observation implemented; cache admission pending)

Record type rendering as a pure query from the complete input type to its
rendered diagnostic text. Reuse the existing renderer so nested ADT names,
opaque-type spelling, function grouping and effects retain their exact rules.
The query's type relocates through the type domain; its answer remains text.
Validation must recompute that query against the candidate context before reuse.
This avoids a reverse dependency from types to checker observation machinery
and does not enumerate unrelated ADTs. Record only at actual rendering calls,
threading Cx before emitting the corresponding diagnostic and preserving string
evaluation order. Constructor and function-return rendering require separate
queries with their complete inputs; ordinary type rendering alone is not full
diagnostic coverage. Production caching stays disabled during this migration.

General trait witness refusals retain the rendered subject before querying the
nominal header for an implementation-template hint. The scalar ordering hint
short-circuits that header query; missing generic bounds render only once even
though the resulting text is reused in both the message and hint. Successful
primitive witnesses and error absorption do not acquire diagnostic reads.

Effect argument row subtraction returns its observed context to the call checker.
Its repair rendering is eager in the existing implementation: both successful
subtraction and co-occurrence refusal retain the read, while earlier shape guards
do not. Observation does not change the effect binding or the co-occurrence rule.

Function-typed record fields retain arity hints and expected/actual/field type
rendering in that order. Java finalization records rejected SAM shapes and
non-bridgeable list/element types after class metadata queries. Java overload
resolution retains its eager argument descriptions on successful calls as well
as refusals; these reads precede candidate enumeration, as the renderer does.

Local validation on 2026-09-08: 777 JVM selfhost tests, 64 compiler-plan tests,
the native selfhost gate including its separate foundation closures, and the
release fixed point (B == C) passed. Complete typed-state projection checked
101 comparisons and rejected 30 compiling mutations in 257.69 seconds. The
124 diagnostic mutations passed in three disjoint shards (42/41/41 controls),
with independent positive baselines; the slowest shard took 289.33 seconds.
Each CI shard therefore uses a 618-second planning value (2*290+38), below the
unchanged 660-second pole, and a 31-minute timeout. These are local measurements,
not claims about future CI duration or production cache speed.

The Core audit verified all 100 baseline module hashes. Only the two compiler
hash manifests were refreshed (28 exact and 9 normalized entries); all 17 fixed
text goldens remain unchanged. Typed-subject alignment explains additional
generated identities without rewriting literals. All 49 existing read projection
arms remain unchanged modulo branch-local temporaries and loop labels; the four
new render facts extend projection and equality. None of this enables production
body reuse or completes phases 3–4.

The first consumers are constant initializers, annotated function returns,
trait default returns, parameter defaults and discarded test-body values.
Successful paths do not acquire rendering reads. Owners compare complete
typed modules, diagnostics and allocation against logging-disabled checks,
then assert the exact ordered rendering facts. Compiling negative controls
corrupt query inputs/results, relocation, and each returned consumer context.
Function-return grouping hints now have a separate query carrying the return
type and outer effect in their respective relocation domains. The existing
local-function io hint uses it without changing parentheses or effect suffixes;
its owner requires the exact grouped answer and retained context. Constructor
rendering now carries the complete constructor input, relocating its ADT owner
and field types independently while preserving names and field order. All nine
constructor-rendering calls now retain this query, including suggestion
fallbacks, constructor values, field mismatches and pattern arity errors.
Suggestion hits do not acquire the fallback rendering read. Field mismatch
queries preserve declared-type, actual-type, constructor-hint evaluation order.
Unary refusals and branch-type mismatches also retain rendering queries; valid
unary operations and absorbed Never/error branches do not render or log types.
Binary operator refusals preserve one-sided or left-before-right rendering;
valid operations and error absorption acquire no diagnostic rendering reads.
Ordering refusals retain repeated bound-hint rendering, and inspect a nominal
header through the observed boundary before offering a concrete impl template.
Actual-module owners distinguish generic nominal types (no concrete impl
template) from non-generic ones, retaining header and rendering reads in both
cases. Constructor owners cover value arity, call overflow, pattern overflow,
and unknown-field fallbacks; spelling suggestions skip constructor rendering.
Propagation refusals record incompatible return types, operand/return error-type
mismatches in that order, and non-Option/Result operand rendering. Successful
Option and Result propagation does not acquire diagnostic rendering reads.
Unwrap refusals and non-record field access retain their displayed operand
types. The existing field-access owner still checks the complete ordered read
list, now including rendering after header reads on refusal paths only.
Tuple/list shape mismatches, literal and constructor scrutinee mismatches, and
or-pattern binding type disagreements retain their rendered types. Owners
compare complete cold diagnostics and pattern trees, requiring literal-before-
scrutinee and actual-before-first-alternative rendering order.
List spreads and conditional elements, ordinary if conditions, and non-Unit
branches without else retain their displayed types. Actual-module owners cover
each refusal and successful counterparts without diagnostic rendering reads.
Indexing retains the eagerly rendered operation description even for successful
access, as well as missing-impl and index-type mismatch rendering. Return and
comptime result refusals retain their displayed types. This preserves actual
evaluation rather than assuming every renderer runs only on an error path.
Statement diagnostics retain discarded values, assertion/loop conditions,
discarded loop results and ordered range endpoints. Annotated initializers,
mutable assignments and handler-cell assignments render declared before actual
types while preserving their existing symbol and cell-state transitions.
Local function values and general callable expressions retain non-function,
arity and argument-type diagnostics. Argument mismatches render expected,
actual and complete callable types in order; successful calls do not render.
Handler cell initialization and assignment retain declared/actual rendering.
Ordinary and control arms retain operation-shape hints and return/answer-type
refusals; actual-module owners compare full cold products and cell-take state.
Lambda and with-closure arity hints retain the expected function type. Match
scrutinee/guard refusals and non-enumerable missing-case descriptions retain
their displayed types; exhaustive successful matches skip diagnostic rendering.
Associated-witness hints return their context with the text, so structural-gap
and associated-witness diagnostics retain both message and hint reads. Owners
require repeated projection rendering and nested enclosing-type rendering in
their original order, while fixed-text refusals acquire no rendering query.
Signature hints use a complete Sig-to-text query, recomputed against both ADT
and trait tables and relocated through the signature projector. All five call
diagnostics retain it. Argument mismatches render the fallback signature before
the expected and actual types, matching the original evaluation order.
Other expression and pattern type diagnostics still need migration before this
boundary is complete.

## 七、不做的

不新增语法、改变推断/可见性、扩展comptime语言能力；不做磁盘缓存、跨进程共享、
并行checker、watcher、增量parser或增量机器码发射；CLI共享语义入口但新进程不热启动。
不把pending扫描优化算cache收益，不把第2期称为Playground提速，不发布或部署到生产。
