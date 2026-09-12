# 增量语义契约夹具

## Diagnostic rendering read contracts

### Witness observation and candidate recomputation (acceptance in progress)

`python3 scripts/incremental-semantics-contract/witness-revalidation.py` runs a
private positive checker subject and compiling negative controls for candidate
recomputation, nominal recursion context, scope-sensitive concreteness,
assignment operands, inference outputs and reduction binding inputs. Each
negative must fail its named assertion owner, not merely fail compilation.
The projection controls additionally cover all eleven new fact variants,
separate dictionary/trait/binder domains, inference input/output bindings, and
missing mappings. Each mutation changes one production expression; checker and
projection modules are restored between subjects to prevent combined mutations.
The 31 controls and two positive baselines took 108.71 seconds on 2026-09-09.
CI runs them in `incremental-witness` with a 256-second planning value and a
13-minute timeout, preserving the existing run pole. Complete capture coverage
at all consumers remains pending. Passing this gate
does not admit a body cache entry or establish complete dependency coverage.

### Candidate context queries

`python3 scripts/incremental-semantics-contract/context-revalidation.py` checks
twenty context-owned query dispatches, four acceptance/refusal controls and
three checker-dispatcher controls.
Canonical query capture remains unchanged in each private subject; every mutant
must compile and reach its named assertion owner. Two positives and 27 controls
took 97.56 seconds locally on 2026-09-09. CI uses a 234-second planning value
and twelve-minute timeout. The checker dispatcher combines context and witness
queries, but still refuses unsupported facts. It does not reconstruct body-local
scope, authorize a cache entry, or enable production body reuse.

### Diagnostic queries

`python3 scripts/incremental-semantics-contract/diagnostic-reads.py` checks four
positive modules and 124 compiling negative controls. Each negative must reach
an owning assertion; compilation errors and unrelated failures are rejected.
These contracts cover query inputs, answers, relocation, and context threading
through actual diagnostic consumers. They do not prove production cache reuse.

Use `--shards 3 --shard 0` (then indices 1 and 2) to run disjoint partitions.
Every partition independently runs all four positive modules. All partitions
must pass to accept the suite. `--check-shards --shards 3` validates current
mutation anchors, unique identities, and complete nonempty partitions without
compiling. `--self-test` exercises eight CLI acceptance/refusal cases, including
invalid indices and empty partitions. The default invocation still runs every
negative control.

Set `DAWN_BIN` to a frozen compiler when editing the subject concurrently. The
script snapshots subject sources and checks private copies; never replace that
compiler while a run is active. Final bootstrap, native and full selfhost gates
must still use the current production toolchain.

多文件 LSP 已启用保守前缀缓存；CLI 与 standalone 仍走冷分析。
下列冷路径命令本身不证明缓存命中，命中由前缀/工作区执行计数门禁另行验证。

- `python3 scripts/incremental-semantics-contract/probe.py`：八个 Java hook 与
  refusing guard 的九个可编译负控。
- `./bin/dawn test scripts/incremental-semantics-contract`：query probe 集成、
  冷路径阶段嵌套、错误恢复和 loader 诊断顺序。
- `python3 scripts/incremental-semantics-contract/cold.py`：私有源码副本中注入
  冻结旧循环，对照相同 StdCtx、LoadedModule 和 CtOpts；六个变异体只改新路径。
  需 JDK 21+ 的 `java/javac/jar`。

旧循环来自 `58ebd4a5` 的 `analyze_program`，仅改函数名；它共享未改动的
checker/stdlib helpers，不调用新 transition。13 组结果覆盖模块换序、恢复诊断、
parse/check/comptime 失败、impl/ID 传递和 std 的 impls_before 特例。

比较器由 javac 独立编译，通过反射比较整个 Program（包括 AST/TAST、comptime、
完整 Cx）。只排除 Cx 中同一 refusing oracle 的 jsig 能力；Array 比较逻辑长度内
的内容，不比较 backing capacity/append watermark。未知宿主对象抛错，不算相等。
新增字段自动参与比较，循环引用用对象对去重；浮点按原始位比较。Java 的标量、嵌套数组、
循环引用和未知对象有自检。采用独立比较器是因为直接生成完整 Cx 的 Eq 字典时，
测试程序出现 List_Int 构造器描述符不匹配；此处未修改编译器发射契约。

负控必须成功构建且命中明确的语义差异断言；编译错误、反射错误、timeout 不算通过。
impl 负控清掉 checker 的输入 impl carry，而不是清掉输出 fold 的初值：后者会被
完整 cx.impl_table 重新补齐，是等价变异体，不能用来证明门禁失效。

## 冷路径基准

```sh
python3 scripts/incremental-semantics-contract/bench.py \
  --java-home /path/to/jdk21 \
  --output review/cold-baseline-new \
  examples/projects/hello_mod selfhost
```

输出目录必须不存在。每个目标使用独立 JVM，同一 captured plan/target Java lease
中跑11轮，丢前3轮，cold/observed 交替先后顺序。保存逐轮 TSV、源码 SHA-256、
JDK/OS/参数、构建日志、摘要和进程峰值 RSS；每轮必须无诊断且所有模块执行 check/comptime。
parse replay 不是 loader 内部分段，不能从 load 相减；RSS 包含启动、std 和整个进程，
不是缓存保留内存。八个样本不足以声称稳定的加速倍数；这个入口只测冷分析阶段。

## 重放代价剖面（仅本地）

```sh
python3 scripts/incremental-semantics-contract/bench-replay.py \
  --java-home /path/to/jdk21 --output review/replay-cost
```

`bench-replay.py` 与其 `bench-replay.dawn.txt` 只测量，不改任何 checker / recorder /
executor 语义；它按函数体类别（字面量标量、原语参数算术、具名非泛型调用、带 trait bound
的泛型、含闭包的推断体、impl 方法、trait 默认体、`use java`）分别计冷检查、scheduler
录制与 `check/scalar_replay` 的每阶段代价，并给出打破平衡所需的每体成本表。
**它不进 CI，也不该进**：输出是墙钟毫秒，随机器与并发负载浮动一到三成，门禁没有可比对
的东西；同理它没有 `# budget:` 行。阶段拆分是在夹具里用生产的公开 producer 重新组合的，
每次运行都在同一进程内与生产 `scalar_replay.replay` 的 reused/checked 计数对账。

`parse` 模式把快照的两半分开计价：`snapshot_build`（parse + index）是修订所有者本来就要
付的一次解析，`bind_pair` 是重放自己仍要付的两次语法树比对。`memory` 模式不计时，它报
保留一个 `source_projection.Indexed` 与保留一个完整 `Snapshot` 各占多少堆字节（强制 GC
前后取差）；真实所有者里语法树与 header 共用，故索引那一项就是快照的边际内存。

## 前缀与工作区

后续函数级演进的私有决策门见[第3期函数体原型](body-probe.md)：
固定header下验证稳定函数key、真实前置编辑、TFun和完整body边界Cx重放；
header来自生产check_module_headers的ModuleHeaders，不再按源码锚点复制header前缀。
它不是已上线的函数缓存，也不代替下列生产前缀门禁。

`relocate.py` 验证生产 `check/relocate` 基础层：Ty/Eff、Sig/Sym 和 witness 的引用域
映射、缺失引用冷回退、效果重新规范化、evidence 编码/生成名称及完整角色的ABI顺序。
23个成功编译负控必须命中具名断言。

`body-probe.py --typed --typed-all --java-home <JDK> --output <新目录>` 运行生产树投影
的私有对照：23个真实函数、22次非均匀源码编辑及一次真实effect声明重排，七个树投影编译
负控必须命中独立Java比较器的完整TFun断言。另有六个推断函数/调用者状态（标量、
泛型闭包、效果多态闭包返回），使用生产header台账与body_plan逐函数累计映射，和一个
test block状态的完整冷模块对照，丢封定签名写入、保留错误in_test的两个编译负控
必须分别命中对应的完整Cx断言。header重排进一步比较完整Cx，并增加丢symbol目标
插入排序的负控。另有三个impl入口负控，移除owner、类型参数和签名角色守卫，
必须命中具名的运行时拒绝断言；默认参数另有丢符号写入的完整Cx负控。
另有丢默认值字典符号的编译负控，必须命中泛型默认值的具名字典断言。
另有丢默认参数诊断的编译负控，必须命中默认错误态的具名断言。
Compilation or linking failures do not count as passing negative controls;
typed-all now contains 30 compiling controls. Typed mode also compares assembly
of 23 body products in their original coordinates. The 22 source-edit replays use
production `body_product` capture, projection and assembly, not the old private
write-set replay. Fixed-header allocation/reference views still come from the
fixture, not production query wiring. Target symbol mappings follow header binding
order, not answers reconstructed from cold bodies; complete header/type/trait
coverage and actual cache validity remain unfinished.

header重排案例使用`allocation.local_headers`台账连接生产声明索引的局部ADT、
opaque/透明alias、trait及方法、效果和函数签名binder，同时反转成对声明，
直接核对各域ID与方法签名映射，并拒绝来源路径不符的header。另连接
`local_impl_headers`读取生产header pass的泛型impl方法签名，核对顺序交换后的完整签名，
并拒绝缺失、错序和metadata不匹配的签名表；再连接
显式intrinsic保留身份。`body_plan`预留旧产物完整取号区间，按完整ABI角色置换
顶层evidence，不从冷body读取目标ID；默认参数仍拒绝，独立产物接线待完成。
默认参数正例另通过check_param_default分别捕获两个Int默认值，使用纯默认签名
预留各自区间并重放，累积台账再供主body产物投影与重放，两类签名均与完整冷Cx/TFun及模块函数比较；
另覆盖泛型默认闭包调用trait方法、携带字典引用：普通/泛型与显式/推断四例，加上
显式/推断默认值类型错误两例，共六例；全部在源码前增加注释，比较移动后的诊断及位置。
尚未覆盖全部复杂表达式，也未接入生产缓存调度。
已不再生成稠密header identity表。固定header的其他案例暂仍用稠密夹具映射。
`allocation.py`有十七个编译负控，守身份/ID冲突、目标版本选择、负槽与引用域及常量声明类型，
以及body evidence置换、未观察临时ID、分配终点、前序台账保留、world、无路径边界、
compiler nominal和runtime擦除绑定；
CI的incremental-allocation独立运行该脚本，
并运行`provenance.py`的六个生产生成器负控：丢用户/std/compiler来源、丢provider carry、
错误header放行和漏std world重绑定；必须命中真实module transition的具名断言。
native门禁另显式执行allocation模块测试；当前已被生产driver引用，与主图有重叠，计数不相加。
另有两个真实两模块导出/导入案例：provider交换效果或类型声明顺序，consumer分别
选择性导入效果、通过模块别名访问类型和泛型函数，合并原声明模块与consumer台账后
重放完整body/Cx。断言consumer不生成导入声明的本地身份，丢合并内容的编译负控由
allocation owning测试守住。所有typed案例统一使用生产callee_signature入口，以声明
owner和原函数名查找签名，别名不替代声明身份。该案例不覆盖限定效果
拼写（当前语法不接受!dep.Ask）。可选AnalysisCarry已在生产header边界记录用户和std
来源，Session保留固定baseline；内建来源从实际prelude/builtin元数据生成，三个来源
重排案例不再手写evidence-pack映射。尚未启用body缓存调度。

另有十个完整模块重放对照：一例函数交换源码顺序、一例前置函数改动后复用六个推断函数、一例泛型impl与trait默认方法重排、一例常量/test重排，以及上述六个默认
参数案例。将重定位结果送入生产assemble_module_bodies，独立反射比较整个TModule和
最终Cx，包括合成默认函数、签名表和Map顺序。漏装函数/清空最终签名表的两个负控仅
修改重放侧，必须命中整模块断言；这些是fixture装配/比较器负控，不冒充生产调度门禁。

function_product从真实ModuleHeaders构建顶层函数的具名header索引，保持当前语法与entry
签名配对；重排案例按DeclKey读取旧body，再按当前keys顺序装配。function-products.py
十五个编译负控守来源、owner、签名错位、多余签名、重复声明、impl分组/参数/角色与trait默认
元数据。独立Methods视图保留impl/default分组顺序，读取真实注册ImplI和trait MethodSig，
不把同名方法混为一个key。header重排案例已投影两个泛型impl方法及两个效果多态默认
方法的签名/subject/trait ID。新增整模块案例重放四个泛型impl方法和两个trait默认方法的
无标签body，再按当前impl组入口计算发射标签、按当前trait登记默认方法标签。
注册subject不能替代入口上下文的解析结果；每个方法重新计算也不等价于每组一次。
两个fixture负控分别打破这两个约束，必须命中整模块冷路径对照。
空impl组由具名索引owning测试覆盖；这不是生产缓存调度或header依赖有效性证明。

Values视图保持常量/test角色、顺序和常量前序可见集；四个新负控守常量类型、
签名尾部、可见集及test角色。BodyProduct[T]共享Cx增量而保留真实TFun/TConst类型，
常量分配计划检查声明类型、保留完整临时区间，不制造函数签名。真实模块重排两个
nominal类型、三个常量与两个test，比较完整TModule/Cx；两个typed新负控丢常量类型
和源码投影必须命中整模块断言。这是已知可复用语料的产物重放，不证明一般可见集
变化时的缓存有效性，也不跳过后续依赖接线。

relocate_header投影完整导出记录中的类型/构造器、alias、trait方法及关联成员、
效果和impl元数据。真实header案例使用源码前缀与不同起始分配计数，来源表仍从实际
声明生成；独立Java比较整个ModExports，包括Map顺序。四个编译负控分别漏投影
alias/impl/ADT/effect表，必须命中导出记录不一致断言。此例不改变声明顺序；投影
保留旧顺序，不能替代跨声明重排后的当前顺序装配。
header-metadata.py的十二个编译负控守binder、构造字段、trait方法/default、impl关联
类型/效果/owner/位置和alias的哨兵/源码/effect。透明alias的-1不是nominal引用；
另审计十种metadata记录的投影/保留字段，每种均有新增未分类字段的拒绝自测。
源码回调按声明owner和可选路径选择映射。该脚本在incremental-state执行；native另跑
relocate_header及其header_product依赖的55项owning测试，不与其他target相加。

header_product captures complete header scope tables, diagnostic suffixes and
allocation intervals without retaining the entire Cx or a Java capability. Real
header fixtures compare the complete assembled Cx, then project the complete state
into moved ID/source coordinates and compare against cold Cx. Three compiling
controls omit impl-key relocation or retain old bounds/observable impls; these are
part of the 30 typed-all controls.
header-state.py的九个编译负控守环境、分配、诊断前后缀、常量表、类型作用域及
type-span清空状态；完整Cx捕获/装配和HeaderProduct投影字段审计另有五个结构负控。
这些完整表快照仍保留生产顺序，不是逐声明delta，不能合并任意独立声明编辑；
输入环境有效性、当前顺序装配和生产调度仍须接线。没有借此启用header cache。

query_runtime是参数化key/value的不可变查询owner：显式输入、嵌套计算栈、读取stamp、
反向失效和相等结果截断传播。删除重建使用独立单调stamp，不用revision代替结果版本。
负查询结果是普通value，缺失memo才是Needs；未完成读取不能finish。重新计算父查询
先使其旧读者重新验证，避免经旧memo绕过循环检测；abort不发布半成品。
query-runtime.py的17个成功编译负控覆盖传播、相等截断、边替换、读取记录、循环、
提交边界、角色、驱逐、同revision ABA及在计算期间写入/推进revision/驱逐的拒绝。
JVM/native各有6个owning图测试。它尚未接真实checker，不能据此声称scope/impl/body
读取已完整覆盖或函数增量已上线；后续真实消费者必须明确语义相等及源码视图依赖。

`projection.py` 补源码边界分裂、token/断言来源、旧断言文本及checker两条evidence
构造分支的六个成功编译负控，另有callee owner、模块别名表和签名冲突拒绝的三个
owning断言负控，以及ModuleHeaders推断状态/const类型保留的两个负控。
ModuleBodies将body检查与最终装配分离；五个装配负控覆盖impl/default顺序、const、
test、默认辅助函数签名登记及泛型字典保留；另两个负控守impl入口类型参数与trait查找
（合计18个）。这只是同revision生产边界，
不是模块cache有效性证明，也尚未接上跨revision的具名header重组。
源码token相等不证明AST相等，尤其不能忽略换行的语义。
`identity.py` 验证生产声明候选身份及八个成功编译负控：重复父声明及子路径、
类型/关联效果的绑定槽归一、默认参数歧义、模块world隔离。具名owning断言必须失败，
编译或链接失败不算负控。typed模式现在通过适配器调用生产声明索引；legacy模式
保留原型身份实现及原来的八个负控。候选key不证明依赖环境或body有效。

native-selfhost-tests 分别执行tree、source及identity的owning依赖闭包（包含重叠依赖），
因为新模块尚未被nmain导入，不能只跑主图就宣称它们有native覆盖。

`state-product.py` runs 19 compiling controls for capture, assembly and coordinate
projection: signature/alias/bound writes, frames, diagnostics, environment guards,
allocation starts and ghost IDs, type/effect domains, handler cells, symbol order,
constant trees, and read-log suffix capture, assembly and reference relocation.
It also audits every Cx field and rejects an added unclassified field. The constant
tree control must hit the real TConst owning assertion. This remains in the separate
incremental-state job; the native suite also runs body_product's owning dependency
closure, which overlaps other targets and must not be counted as independent tests.

`function-reads.py` runs 33 compiling controls against actual checker reads:
unqualified answers, diagnostic candidate lists, qualified signatures and module
alias paths, including misses. Decisions preserve local shadowing, expected-type
short circuits and argument scheduling. Capture/projection retain all four fact
variants. The typed oracle additionally compares 62 enabled/disabled observation
cases against complete cold Cx and module products; its read-state mutant must hit
the whole-Cx assertion. Recording remains disabled by default and is not complete
namespace coverage or production body-cache admission.

`export-reads.py` adds 26 compiling controls for qualified constant and constructor
answers, export presence, and private-name/candidate/type-constructor diagnostics.
The additional fourteen complete-state oracle cases exercise these expression,
call, qualified match and let/for refutability paths without stripping anything except the
intentional observation log. Four controls retain the recursive refutability
context and its let/for consumers, including the original short circuits.
Projection separates constant type references from constructor nominal IDs and
preserves constructor slots and diagnostic kinds. Four further controls retain
qualified pattern presence, constructor and diagnostic answers, including their
kind. Error recovery preserves nested pattern observations. Type resolution,
local constructors, ADT/trait/impl and Java dependencies are still incomplete;
these tests do not authorize cache admission. The incremental-export-reads job
runs the export controls separately, preserving the unchanged 660s planning pole.

The incremental-reads job runs these read controls and the existing `projection.py`
suite. Moving source projection out of incremental-projection keeps the expanded
typed oracle below the unchanged 660s planning pole without removing any controls.

`type-reads.py` adds 45 compiling controls for qualified alias headers and resolved
targets, local/qualified nominal name/shape reads, type diagnostics, and local
alias cache/cycle decisions. Eighteen
further whole-state cases cover transparent/opaque aliases, effect substitution,
nominal arity errors, missing types/modules and earlier shadowing branches.
Alias type/effect binders project separately; a
transparent alias has no nominal ID to relocate. The BodyProduct fixture captures
and assembles the four reference-bearing type fact forms plus exact local type
diagnostics, including actual effect-row relocation. One control bypasses only
that callback; two more corrupt the projected diagnostic message or hint. Each
must fail its owning read comparison. Cached alias targets retain the distinction
between no cache entry and a cached error; cycle reads occur only after a cache
miss with a declaration target. Owning tests preserve those short circuits, and
the body-product fixture relocates cached targets while retaining cycle answers.
After a cache miss, declaration source reads retain the alias name, owner and
optional complete target syntax. Source-aware function and constant projection
entry points use an explicit owner-aware callback; source-free entry points
reject present declaration targets. Owning tests map identical original body and
foreign declaration offsets to different destinations using the production
header syntax projector, and reject an incorrect owner. Missing targets do not
require a fabricated source mapping.
The `incremental-type-reads` CI job runs this suite separately. Local alias lookup
records both positive headers and misses after the reserved-builtin/type-parameter
short circuits; uncached expansion records its actual type/effect binder inputs.
Both header forms share extraction and projection, with independent reference
domains. Builtin/current-environment dependencies, source-view runtime wiring, associated types/effects and
Java reflection still need their own observed dependencies and validity boundary.

`associated-reads.py` adds 15 compiling controls for scoped subjects, optional
ordered bounds, and type/effect member lists. Owning cases retain absent versus
empty bounds, duplicate-bound owner deduplication, missing members and ambiguity
on both axes. Projection uses independent type, nominal and trait mappings;
the body-product owner exercises the actual trait callback. Six additional
whole-Cx/module cases compare observed and cold associated resolution, including
error recovery. These observations do not yet establish complete effect or
scope dependencies, runtime query wiring, or production cache admission.
The incremental-effect-reads job runs these controls alongside ordinary effect
and environment suites, with a 554s planning value below the unchanged 660s pole.

`effect-reads.py` covers declared effect rows and scoped effect-variable answers,
including negative answers, metadata labels, lookup precedence and repeated reads
after fresh allocation. Fourteen compiling controls must reach their owning
assertions. Leaf and BodyProduct tests preserve the effect-row domain: declared
label IDs and variable IDs relocate independently, including equal input integers
with different destinations. Six complete Cx/module cases cover ordinary effects,
variables, aliases and error recovery. Runtime query wiring and complete checker
dependency coverage remain outstanding; these facts do not enable caching.
The separate incremental-effect-reads job also runs associated reads,
with a 424s planning value. Environment controls move intact to the type job,
which has a 652s planning value; both preserve the unchanged 660s pole.

`environment-reads.py` adds 16 compiling controls for reserved and ordinary
builtin lookups, current type parameters, and std-module visibility. The checker
owns the complete ordered sequence, including repeated builtin queries and
short-circuited parameters, arguments and visibility reads. Builtin metadata
retains its name, parameter spellings, access policy and build shape; leaf types
project through the actual type callback. Six complete Cx/module cases cover
std-only visibility, reserved return types and nominal shadowing. These facts
do not complete Java/trait/impl dependencies or authorize production caching.

`java-reads.py` exercises the named Java class lookup and the actual plain-data
class metadata answer. Its 21 compiling controls cover answer keys, answers,
consumer context threading, every JClass field, and BodyProduct read capture.
The five metadata consumers include reference returns, static and instance
dispatch, and SAM/List diagnostics. Projection retains the lookup key separately
from the returned class name. Four complete Cx/module cases cover these class
metadata consumers. Other Java query kinds, classpath/lifetime
validity and production query admission remain required; this is not a complete
Java dependency cache.

`java-member-reads.py` adds 33 compiling controls for ordered method, constructor
and static-field answers. Every metadata field, query key, list order and
consumer context is covered by owning assertions. Lists retain duplicate and
unused candidates before filtering or sorting, and empty results are recorded.
The BodyProduct fixture captures and projects all three facts; six additional
complete Cx/module cases bring the observation oracle to 72 cases. Argument
errors and instance constructor calls must still short-circuit before metadata
queries. Assignability, SAM/component and remaining namespace/import queries
are separate requirements; recording candidates does not authorize cache reuse.
The Java class and member suites run together in incremental-java-reads with a
608s planning value (109.07s and 174.12s local measurements, rounded up, doubled,
plus 38s setup). Adding member controls to the former effect/Java job would
exceed the unchanged 660s pole. All existing suites and controls are retained.

`java-namespace-reads.py` checks Java import gates, find-class answers and ordered
namespace enumeration. Its 22 mutations cover answer keys and values, projection,
body capture and consumer context threading, including value-versus-module-alias
resolution. Owning assertions retain negative answers, repeated reads and the
original declaration, syntax and shadowing short circuits. Nine additional
complete module/Cx cases bring the observation oracle to 81 cases, covering
successful, missing, disabled and duplicate imports, declaration collisions,
inferred functions and named-argument refusal. These observations do not yet
establish classpath lifetime validity or authorize production cache reuse.
The 22 compiling controls took 149.16s locally on 2026-09-08. They run in a
separate incremental-java-namespaces job with a 338s planning value
(2*150+38) and a 17-minute timeout, retaining the 660s pole and existing jobs.
During namespace acceptance, class/member controls took 184.25/226.97s under
concurrent load. Conservatively retaining those larger observations requires
separate class/member jobs: 408s/21min and 492s/25min respectively. No controls
are removed. The typed 81-case run took 239.16s; its job retains the larger
244.70s member-batch observation, yielding 528s/27min.

`java-oracle-reads.py` checks directional assignability, optional SAM metadata
and optional array components. It retains queries from rejected candidates,
fixed-arity attempts and packed arguments, plus repeated finalization queries.
The controls cover query keys/answers, all eight SAM method fields, projection,
body capture, candidate loops and scoring/finalization context propagation.
Only compiled mutations reaching owning assertions count. Eight additional
complete module/Cx cases bring the observation oracle to 89 cases; these cover
static and instance calls, rejected conversions, packed methods/constructors
and deferred SAM arguments. Classpath lifetime and production admission still
require separate validation before these facts can authorize cache reuse.
The 32 compiling controls took 246.67s locally on 2026-09-08. The dedicated
incremental-java-oracles job uses a 532s planning value (2*247+38) and a
27-minute timeout, without removing existing controls or raising the 660s pole.
The class/member/namespace regression controls measured 228.37/281.28/258.25s
under concurrent load. Their separate jobs conservatively retain those larger
observations at 496s/25min, 602s/31min and 556s/28min respectively.

`local-value-reads.py` checks constructor/constant identities, visibility,
constructor counts and field arities, focused headers, selected fields and
ordered diagnostic candidate pools. Its mutations must compile and reach an
owning assertion; bootstrap or parse failures do not count. The observation
oracle now has 101 complete module/Cx cases, covering generic constructors,
patterns, constants, record fields, and diagnostic refusals. Recursive
exhaustiveness controls additionally require normalization and recursive
return state to survive short circuits and diagnostic consumers. Handler
controls retain declaration metadata and selected evidence fields.
These observations do not yet establish complete dependency coverage or
production cache validity. The 49 compiling controls took 222.83s locally on
2026-09-08. Their independent CI job uses a 484s planning value (2*223+38)
and a 25-minute timeout, preserving the existing 660s pole and all other
contracts. Full batch acceptance remains required before publication.
The preceding complete 95-case/30-mutant typed run took 266.72s; its independent job
now uses a 572s planning value (2*267+38) and a 29-minute timeout.
The Java oracle regression took 250.55s, yielding 540s/27min. State products
took 155.55s for 19 controls; they now run separately at 350s/18min, retaining
the other state contracts and their existing budget without exceeding the pole.

`prefix.py` 对照完整 warm/frozen-cold 产品，覆盖12个可编译引擎负控，包括预算、
std身份变化及构造器的负预算拒绝。`lsp-prefix.py` 覆盖三个工作区接线负控，要求
owning FAIL 后是断言失败，不把 JVM 链接错误算作成功。工作区计数测试在共享server里，
同时由 JVM/native selfhost 套件运行。原有 `scripts/lsp-workspace-contract/run.sh`
另行守18个协议案例和20个资源/工作区负控，不能只靠新计数测试替代它。

`lsp-bench.py` 通过实际 didChange overlay 编辑目标文件，磁盘源不改；
立即跟 barrier 强制 flush，所以 sync 不包括空闲 debounce。随后单独测
hover/definition/completion，并保存原始回复和 RSS。示例参数：
`--entry <path> --edit <path> --needle <reference> --output <new-dir> -- <server-command>`。

单大模块错误恢复使用 `standalone-large.dawn.txt`（500个简单函数及一个入口，
合成语料，不冒充真实大型应用）。在上述参数后加
`--uri untitled:incremental-large --error-round 5`，entry/edit 指向同一份文件，
needle 为 `value_499(1)`。11轮中的第5轮注入类型错误，第6轮恢复；每轮必须发布
当前文档版本，错误必须落在注入声明的位置，恢复后全部诊断必须清空。
错误轮不混入正常编辑中位数；原始 diagnostics 与 query 回复一同保存，用于旧冷路径
对拍。`lsp-bench.py --self-test` 验证诊断判定器及六个负控，并在 CI 执行。

`lsp-observe.py --output <new-dir>` 构建私有服务器，在 stderr 记录最终模块顺序和
实际复用/执行计数，不改变生产协议；`--cold` 只在私有副本里强制每轮先逐出 Session。
两个模式都可用同一源码、JDK和编辑序列对照，回复必须相同。强制cold仍可能保留本轮
输出prefix，不能用这两者的RSS差直接估算缓存大小。baseline JSON明确记录样本与限制。
