# 增量语义契约夹具

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
variants. The typed oracle additionally compares 26 enabled/disabled observation
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
