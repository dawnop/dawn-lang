# 源码位置进 Core：调用节点的 site 与按需侧表

> 状态：**proposed**（M2，2026-10-05 起草，待评审，未实现；M3 C 侧表见第十二节，2026-10-05 起草）。源码位置模型一线（M 刀序）的第二刀；
> 依据：裁决 `agent-handoff/ruling-source-span-map-20261003.md`（「位置货币」一条与 M 刀序），
> 调研 `agent-handoff/research-gpumap-call-spans-report-20261003.md` §六、§八。M1（flash 页）已落地：
> `65547d27`（tileir 调用树与体标记）、`3547325f`（GPU 页只放 flash_attn）。仓库行号指 `ecfa0eda`，
> 外部出处抓取于 2026-10-05。

## 一、要什么，不要什么

M1 的 GPU 页靠「运行时调用树 + `dawn parse` 的 span」配对：位置只经过 parser，不经过编译器。
M3（`__emitc --map`）、M4（`__emit --map`）、M7（三后端对照页）要的是**编译器产物**的每个输出单元
回指到源码里的那次调用，而今天位置在 tast→Core 这一步全丢了：`ir/lower.dawn:3728`
`XCallFn(owner, name, args, wits, evid, trait_id, _, _, ty)` 把 `lo, hi` 扔掉，Core 里除了
`CComptime(lo, hi, ty)`（`ir/core.dawn:192`）一个 span 都没有。

本刀只做一件事：**Core 的调用节点带一个 site，Core dump 不打印它，任何产物都不读它。**
读它的是 M3/M4 的侧表写出器，那是后两刀。所以本刀对外可见的输出是零：Core golden、emit 语料、
`__emitc` 输出逐字节不变，这是硬判据（第六节）。

## 二、与「Core 无 span」裁决的关系

既有裁决有两处：

- `docs/native-backend-plan.md:336-338`：保持 Core 无 span 是有意的，等真正需要行号表（调试信息）
  时再一次性加。
- `docs/codebase-audit-v2/03-compiler-and-runtime-architecture.md`（「原建议里 lowered function 保留
  source origin 已判为不做」那段）：Core golden 存在的全部意义是「纯代码移动时它一个字节都不动」，
  那是纯重构「只搬代码没改语义」的唯一可信证据；给 Core 节点普遍加行号，会把今天 3 处行号字面量
  扩散到每个节点，判据就不成立了。

两条保护的都是**dump 的字节**，不是 Core 的类型定义。审计文的论证链是：Core 带位置 → dump 打印位置
→ 纯移动改 dump → 判据失效。本刀切断的是第二环：site 不进 dump。再加一层保险，site 存的是
**相对所属声明的偏移**（第三节），所以即使将来有人把它打印出来，纯移动（声明整体换位置）也不改它，
改的只是声明自己的基址，而基址不在 Core 里。

它确实改变了裁决的**字面**（「Core 无 span」不再成立），所以本文要显式取代那两句：

- native-backend-plan 那句的前提是「真正需要行号表时」。M3/M4 的侧表就是那个需要，只是形状不是行号表：
  三家的标准设施都只给到「行」或「行 + 起点列」（调研 §6.2），给不出调用区间，所以先有 span，后有
  可选的行号表（M6）。「一次性加」也照做：本刀之后 Core 的位置模型就定型，M6 不再改 Core。
- 审计文那条判据原样保留，并且由本刀的硬判据直接验证：本刀的 PR 本身就是一次「Core 类型变了、
  dump 一字节不变」的对照（`selfhost-core-diff.sh` 退出 0）。

落地时这两处加一句指回本文，状态不改（它们是 current 文档里的一段历史判断，不是要删掉的错话）。

## 三、位置货币

裁决定的货币是前端已有的码点 span `(file, lo, hi)`，存成「所属声明 + 相对偏移」。落到类型上：

```dawn
# ir/core.dawn
pub type CSite =
  | CNoSite
  # lo/hi: the written call, nlo: where its callee's name starts; all three
  # are code point offsets from the declaration the enclosing CFun came from
  | CAt(lo: Int, hi: Int, nlo: Int)
```

- **为什么是 ADT 而不是 `Option[(Int, Int, Int)]` 或三个 Int 字段**：每个消费者都得对「这个调用没有
  书写位置」显式表态；三个裸 Int 字段会让每个模式多三个 `_`，而一个 `site` 字段只多一个。`CNoSite`
  是无字段构造器，不分配。
- **被调名起点 `nlo`**：`f(x)` 是 `f` 的起点（等于 `lo`）；`m.f(x)` 是 `f`；方法式 `a.f(x)` 与
  `a.f().g()` 的外层是 `g`；`x |> f` 是 `f`。页面高亮一个调用取 `[nlo, hi)`，方法链因此能分段
  （调研 §3.3）。只记起点不记终点：名字终点在源码里一个标识符扫描就能拿到，存它是第二份真相。
- **所属声明**放在函数上而不是每个 site 上：`CFun` 加 `origin: String`，即 `TFun.decl`
  （`check/tast.dawn:362`，`identity.path_text` 拼出来的声明路径）。被提升的 lambda 继承外层函数的
  `origin`，它体内的 site 仍相对外层声明；合成函数（字典桥、`lift_fn_value` 的包装、派生 impl）
  `origin = ""`，体内全是 `CNoSite`。之所以一个函数一个 origin 就够，是因为 Core 层**没有内联**
  （第五节），一个 `CFun` 的体只来自一棵源码声明树。

**相对偏移从哪来。** tast 在检查期是相对偏移，但在声明出口被 `tast_positions` 换回了文件坐标
（`check/tast_positions.dawn` 头注释），降低拿到的是绝对位置。所以 `TFun` 加 `base: Int`：
`tast_positions` 加上去的那个数（`Resolver.base`，无主声明为 0），由 `tast_positions.function` 在换算
同一棵树时写上；参数默认值合成的 `f$default$k` 继承父函数的 `base`，因为它的树是用父函数的 resolver
换算的。降低时 `rel = abs - tf.base`。最初写在调度器填 `decl` 的那几处，但
`scripts/incremental-semantics-contract/body-scheduler.py` 把生产调度器与冻结的参考调度器逐产物对照，
参考那份不会跟着填，于是红了；放进 `function` 后两边共用，冻结副本不用改。

**`nlo` 从哪来。** tast 今天的调用节点只有整个调用的 `lo, hi`。parser 有名字区间（`EMethod` 的
`nlo, nhi`，`front/ast.dawn:319`），检查器在 `check_method_call` 等处拿得到。五个调用节点
`XCallFn`/`XCallDyn`/`XCallBuiltin`/`XApply`/`XJava` 各加一个 `nlo: Int` 字段，紧跟 `hi`；
`tast_positions` 对它做与 `lo`/`hi` 相同的平移（每个 arm 多一个参数，换算函数不变）。
检查器替别的构造写出的调用节点填 `tast.NO_NAME`（-1），平移时原样保留（`tast_positions.name_at`），
降低见到它给 `CNoSite`。被调名起点的取法：具名调用取被调名（`check_call` 的 `clo`），方法式取 `name@`，
应用一个字段 `(r.f)(x)` 取字段名，其余 `XApply` 取被应用表达式的起点，`use java` 调用取成员名。

否决的替代：检查器在 `Cx` 里另记一张「调用 span → 名字起点」的旁表，挂在 `TFun` 上，绕开 tast 节点。
改动少（不碰 tast_positions、lsp），但它是一张靠 `(lo, hi)` 当键的表：`f(x)` 的默认参数展开合成的
调用与书写的调用 span 相同，键会撞；也让「这个调用的名字在哪」变成节点之外的知识，正是 Core 要消灭的
那类「后端要自己再推一遍」。字段是诚实的做法，代价是约 140 处模式多一个 `_`（第八节）。

## 四、哪些节点带 site

| Core 节点 | 带 | 来源 |
|---|---|---|
| `CCall`（五种 callee 全部：`CDirect`/`CDynamic`/`CMethod`/`CImpl`/`CDefault`） | 是 | `XCallFn`、`XCallDyn`、`XApply`，以及降成 std 函数调用的 `XCallBuiltin`（`parser_impl`、`hamt_fn` 那几条重定向） |
| `CIntrinsic` | 是 | `XCallBuiltin` 降成内建的那条路（`ir/lower.dawn` `erased_builtin_sig` 一支） |
| `CForeign` | 是 | `XJava`（`use java` 调用也是用户书写的调用，M4 的 javap 列表需要它） |
| `CCtor`/`CUpdate` | 否 | 构造是分配，不是控制转移；parser 一侧原型（调研 §3.1）也把构造器当透明节点。要的话是 M3/M4 自己的事，届时同一个 `CSite` 类型照用 |
| 其余（运算符、字段、`if`、循环……） | 否 | 不是调用 |

**一条书写调用至多一个带 site 的节点**（单射）。降低把一次书写调用拆成多个 Core 调用时，只有
「实现这次调用」的那个节点带 site，其余为 `CNoSite`：

- 省掉默认实参：`f$default$k(..)` 是合成调用，`CNoSite`；最后那个 `f(..)` 带 site。
- `hamt_call` 等把一个内建拆成多次 std 调用：只有产出结果的那一次带。
- 隐含调用（`a == b` 走 `Eq`、`"${x}"` 走 `Show`、`for` 的迭代器、`?`/`!`、`c[i]` 的 `Index`）：
  **本刀全部 `CNoSite`**。它们没有被调名，parser 一侧也没有可配对的调用节点；它们该不该在侧表里有一行、
  回指到哪段源码（整个运算符表达式？），是 M3/M4 的设计问题，`CSite` 届时可以加一个 `CImplied(lo, hi)`
  构造器，不改本刀已有的东西。

- 检查器替别的构造写出的调用也不是书写调用：`with handle` 把块的余下部分包成闭包再空参应用
  （`checker.check_handle`），省掉默认实参的 `f$default$k`，`caller()` 占位，eta 包装体，`ev_append`
  拼证据包，处理器的 cell 与 one-shot 原语，`use java` 静态字段读。它们的 `nlo` 都是 `tast.NO_NAME`，
  降低据此给 `CNoSite`，不认名字也不认形状。用户手写的 `(() => e)()` 与 `with handle` 的余下块形状相同，
  前者有 site、后者没有，语料里两者都有。（实现分两步落地：第一步 tast 还没有 `nlo`，降低按内建名与
  「lambda 零实参应用」的形状认，第二步换成 `NO_NAME`，两条临时规则删掉。）

单射是可检的性质：第七节的 oracle 对每个 `CAt` 找唯一的 parser 调用节点，重复即红。唯一允许的重复
是降低**复制**了同一段代码（如果有），此时两份拷贝带同一个 site，与 LLVM 复制指令时保留 `DILocation`
同理；oracle 对这种情形报告复制点，不静默放过。

## 五、各 pass 里 site 怎么走

规则照搬 LLVM 给 pass 作者的三条（*How to Update Debug Info*）：**保留**、**合并**、**丢弃**。

| 位置 | 做什么 | 规则 |
|---|---|---|
| `ir/lower` | 唯一的**产生者**：`XCall*`/`XJava` 入口算出 `CAt(lo - base, hi - base, nlo - base)`，显式作为实参传到造节点的那一处（不放进 `LSt` 当隐式状态：实参里嵌套的调用会把它冲掉） | 产生 |
| `ir/lower` 自尾调用改写成循环（`ir/lower.dawn:3086`） | 调用消失 | 丢弃。M3/M4 要的话由侧表写出器把循环回边记到函数体上，不是 Core 的事 |
| `ir/lower` 内建折成运算符（`CBinary` 等） | 调用消失 | 丢弃（同上，表达式节点不带 site） |
| `ir/lower` lambda 提升 | 体原样搬到顶层 `CFun` | 保留，`origin` 继承 |
| `ir/reach`（std 可达性裁剪） | 只读、只删函数 | 不涉及 |
| `c/infer`（借用推断） | 只读调用形状 | 不涉及；若重建节点则保留 |
| `c/rc`（Perceus） | 重建调用节点（如 `rc.dawn:1276`、`:1671` 的展开实参提升） | 保留：重建的调用带原 site；新造的临时（`LIST_FROM_ARRAY` 等）`CNoSite` |
| `ir/interp`（comptime） | 求值 | 忽略。comptime 失败今天报在被折叠的 const 上（native-backend-plan 那段的「唯一退步」），有了 site 本可报到子调用上，但那是诊断输出变化，不在本刀 |
| `ir/lint` | 结构检查 | 本刀加一条：`CAt` 的 `0 <= lo <= nlo < hi`（不检查不越出声明宽度：Core 不知道宽度） |
| `ir/coredump` | 打印 | **不打印**（硬判据）。另加一个默认关的 `--sites` 开关供测试用，第七节 |
| `jvm/emit`、`jvm/operand`、`c/emitc` | 消费 | 本刀忽略，模式里多一个 `_`。M3/M4 才读 |

**合并**今天没有发生的地方：Core 没有把两次调用合成一次的 pass。将来若有（CSE、调用融合），规则是
合并成两者共同所属的那个调用的 site；没有共同的就丢弃，不选其中一个（LLVM 的 `getMergedLocation`
也是退到公共作用域，选一个会让侧表把另一次调用的产物算到错的一行上）。

**单态化与内联。** Dawn 是字典传递，不单态化（`ir/core.dawn` `CCallee` 头注释），所以没有「一个
site 对多份实例化代码」的问题。Core 层也没有内联 pass。JVM 的 JIT 内联与 cc 的内联在我们的产物之后，
M3 的侧表映射的是 C 文本，M4 映射的是字节码 pc，都在内联之前，不受影响。若将来 Core 加内联，
被内联进来的 site 不再相对调用者的 `origin`，届时 `CAt` 加一个来源字段（LLVM 的 `inlinedAt`、
GHC 的 tick 浮动都是在解决同一件事），本刀不预留。

## 六、硬判据

真父 = 本分支的父提交 `origin/main`（`ecfa0eda` 或 rebase 后的新父），同一台机器、同一份种子。

1. **Core golden**：`./scripts/selfhost-core-diff.sh --base <真父>` 退出 0（所有模块 Core dump 逐字节
   相同，含 `--raw` 不归一的一遍）。
2. **emit 语料**：`./scripts/selfhost-prev-diff.sh` 无差异，提交信息**不带任何** `Emit-Change`。
3. **`__emitc` 输出**：`native-fixpoint.sh`（`CC=/usr/bin/clang-18`）B==C，外加对 `examples/` 与
   `scripts/tile-golden/kernels.dawn` 在真父与本分支各跑一次 `__emitc`，逐字节比较。
4. **LSP 与 CLI**：`selfhost-lsp-diff.sh`、`selfhost-run-diff.sh` 无差异（tast 节点加了字段，LSP 读 tast）。
5. **开销实测**：selfhost 自编译（`__emit selfhost` 与 `__emitc` 各一条路）的墙钟与峰值 RSS
   （`/usr/bin/time -v`），真父与本分支**交错**各 5 次（ABABABABAB），报中位数与极差。
   估算：每个书写调用一个 `CAt`（JVM 上约 40 字节），每个 tast 调用节点多一个 `Int`；selfhost 的调用
   数量级是十万，量级在几 MB，对峰值 RSS 应在 1% 以内。估算不作数，以实测为准；若超过 2% 写进
   报告并给出原因，不靠调整测法过关。

## 七、正确性测试与负控

- **配对 oracle**（`scripts/core-sites/check.py`）：`__lower --sites <dir> <target>` 在 rc 之后为每个模块
  写一个 `.sites` 文件（`ir/coresites.dawn`，单独的走查器，coredump 不引用它），列出每个 `CAt` 的绝对位置
  （`base + rel`，base 由驱动从 `TFun.base` 建表）与被调节点；脚本复用 M1 `site/gpu-map/record.py` 读 `dawn parse` 输出的那一半（`parse_tree`），对
  `scripts/tile-golden/kernels.dawn` 里的 `flash_attn`、`softmax`、`vadd` 以及一份覆盖全部调用形状的
  小语料（普通、限定 `m.f`、方法式、方法链、管道、闭包调用、`XApply`、内建、`use java`、省掉默认实参、
  自尾调用）检查：
  - **可靠**：每个 `CAt` 的 `[lo, hi)` 恰是一个 parser 调用节点（`Apply`/`MethodCall`/管道）的区间，
    `nlo` 恰是它的被调名起点；
  - **单射**：没有两个 `CAt` 对到同一个 parser 节点（复制除外，见第四节）；
  - **完整**：parser 里每个调用节点都有 `CAt`，除了列出的几类（构造器、自尾调用、折成运算符的内建、
    comptime 折叠掉的），例外按类别逐条列出，不是一个计数阈值。
  例外按解析树判定，三类：构造器（`ctor`）、以所在函数为名的调用（`self`，尾位置的已变成循环；非尾位置
  的照样有 site，由「可靠」一条检查）、降低改写成非调用的内建（`rewritten`：`to_string`、`char_unchecked`）。
  `nlo` 按 parser 判：方法式调用的 `name@`、被应用字段的 `field@`、其余为被应用表达式的起点。
  实测（`611dd421` 之上）：语料 33 个调用 30 个有 site、3 个按类豁免；flash_attn 34/34、softmax 7/7、
  vadd 4/4（三个 kernel 在 tileir 0.8.0 迁移后调用变少）。
- **单元**：`ir/lower` 的 test 块钉住相对偏移、`origin`、默认实参调用与未登记树的 `CNoSite`；
  `ir/coresites` 的 test 块钉住换算；`ir/lint` 新规则 `site`（`DAWN_CORE_LINT=1` 时检查）。
- **负控**（`scripts/core-sites/mutate.py` 登记、`run.py` 逐个建编译器验红，锚点由
  `mutation-anchor-preflight.py` 每次推送证明恰好一处；`check.py` 与 `run.py` 挂在 nightly 的 core-lint job）：
  1. `absolute`：降低时不减 `base`：check.py 报「is no call the parser sees」；
  2. `nlo`：模块限定调用 `m.f(x)` 的被调名起点写成调用起点：check.py 报「has its name at」；
  3. `rc-drops-site`：`c/rc` 重建调用时丢 site：check.py（列表取自 rc 之后）报「has no site」；
  4. `dump-prints`：`coredump` 打印 site：语料的 Core dump 变了，即 `selfhost-core-diff.sh` 在每次纯移动上都会报的东西。
  实测四个全红，`run.py` 墙钟见报告。

## 八、改动面与在途冲突

- `ir/core.dawn`：`CSite`、`CCall`/`CIntrinsic`/`CForeign` 加 `site`、`CFun` 加 `origin`。
- 模式与构造：`CCall` 约 114 处、`CIntrinsic` 约 80 处、`CForeign` 约 24 处（大头是 `c/rc.dawn` 的
  测试块）；tast 五个节点约 144 处（`checker`、`lspq`、`lspeval`、`interp`、`lower`、`tast_positions`）。
- **冲突面**：
  - L4 `caller()`（`feat/loc-caller`，目前只有设计文档）：会改 `tast_positions` 的 `sited_arity`/
    `split_site` 与 `checker.dawn` 的 `default_call`。本刀在 `tast_positions` 只给五个调用 arm 各加
    一个参数，在 `checker` 加 `nlo` 与 `base`；文本上相邻但不重叠，后落的一方机械 rebase。
    语义上：L4 的 `caller` 占位节点是合成的，降成 `CStr`，不是调用，不带 site。
  - C TU 拆分（`perf/c-tu-split`）：动 `c/emitc.dawn` 与 `c/cdriver.dawn`。本刀只在 `emitc.dawn` 的
    约 7 处模式里加 `_`，不碰 `cdriver.dawn`。
  - cuTile PR-3（#527）：不碰 `packages/tileir`、`site/`，无冲突；它改的 `flash_attn` 源码只影响
    oracle 的输入，oracle 读的是当时的文件。

## 九、给 M3/M4/M7 留的接口

- **查表函数**（本刀提供，测试用的 `--sites` 也走它）：
  `site_abs(base: Int, s: CSite) -> Option[(Int, Int, Int)]`，以及驱动层从 `TModule` 建的
  `(module, decl) -> base` 表。侧表写出器拿 `CFun.owner`（模块）+ `CFun.origin`（声明）查 base，
  再用模块的展示路径（L1）与 `line_starts` 换成 `path:line:col`。
- **M3 `__emitc --map`**：emitc 拼串时遇到带 `CAt` 的节点记下 C 文本的行:列区间，写出
  `<产物>.dawnmap` 每行「输出区间 → (path, lo, hi, nlo)」，嵌套由 span 包含关系还原（不另存父指针：
  同一函数里调用的 span 包含关系就是调用树）。
- **M4 `__emit --map`**：ASM `Label` 在调用节点前后各打一个，`getOffset()` 给 pc 区间，加类 javap 的
  文本列表。
- **M7 页面要的数据**：每个调用 `(path, lo, hi, nlo)` + 三个后端各自的输出区间；页面按 `[nlo, hi)`
  高亮源码，同一 site 在三栏里的输出区间同色。Tile IR 一栏仍由 M1 的运行时调用树提供，M5（L4 进 tileir）
  之后同一种行格式。

## 十、他山之石

| 工具 | 位置在 IR 里的形状 | 打印 | 开销/取舍 |
|---|---|---|---|
| Compiler Explorer | 不在 IR 里：靠编译器发出的 `.loc` 行表（DWARF line program），CE 的 `BaseCompiler.optionsForFilter` 对每次编译默认加 `-g`；解析 `.loc file line [column]` | 无 | 上限是「行 + 起始列」，没有表达式区间与嵌套（调研 §6.3） |
| Rust MIR | 每个 statement/terminator 带 `SourceInfo { span, scope }`，文档说「Intended to be inspected by diagnostics and debuginfo. Most passes can work with it as a whole」；`Span` 记父 HIR owner，增量缓存里按相对父 owner 起点编码与哈希（`-Zincremental-relative-spans`，2023 年起 nightly 默认），为的是缓存不随无关编辑失效 | `-Z mir-include-spans` 才打 | 与本刀同构：节点带、相对所属定义、dump 默认不打 |
| GHC Core | 包装节点 `Tick CoreTickish (Expr b)`，`SourceNote { sourceSpan, sourceName }`，只在 `-g` 时产生；文档：「Source notes are pure annotations: Their presence should neither influence compilation nor execution」 | `-dsuppress-ticks` 可关 | 包装节点让每个变换都要「看穿」tick（`collectArgsTicks` 之类，还有 `TickishScoping` 一整套浮动规则） |
| LLVM IR | 指令上挂 `!dbg` 元数据 `DILocation(line, column, scope, inlinedAt)`，前端 `-g` 才挂 | 打印 IR 时一起打 | pass 作者三条规则：保留、合并（`applyMergedLocation`）、丢弃（`dropLocation`）；本刀第五节照搬 |

**为什么是字段而不是 GHC 式包装节点**：Core 的 pass 大量按节点形状匹配（`c/rc` 的展开实参提升、
`ir/lower` 的 `CCall(CDirect(..))` 识别）。包装节点会让这些匹配静默失配，产物悄悄变；字段让编译器
在每一处模式上报元数不对，漏改不可能编译过。这正是硬判据「产物逐字节不变」能成立的前提。

**为什么不选「默认开调试信息」**（JVM `LineNumberTable` + `SourceFile`、C `#line`、Tile IR `di_loc`）：
1. 给不出调用区间：LNT 只有行（JVMS §4.7.12），`#line` 只有行（C11 6.10.4），`di_loc` 只有起点；
2. 默认开会让每个 class、每份 C 随纯移动漂移，`emit *` 十个 label 全要 Emit-Change，prev-diff 从此
   失去「只动该动的字节」这层证据，正是审计文 03 防的那件事；
3. CE 默认加 `-g` 是因为它**只**展示，不拿产物字节当证据；我们的产物字节是门禁的证据，两边约束不同。
   所以调试信息走 M6，默认关。

出处：
- Rust `SourceInfo`：https://doc.rust-lang.org/nightly/nightly-rustc/rustc_middle/mir/struct.SourceInfo.html
- Rust 相对 span：https://doc.rust-lang.org/nightly/nightly-rustc/rustc_span/struct.Span.html ；
  https://github.com/rust-lang/rust/pull/84373 ；https://github.com/rust-lang/rust/issues/47389
- GHC `Tick`：https://hackage-content.haskell.org/package/ghc-9.14.1/docs/GHC-Core.html ；
  `SourceNote`/`TickishScoping`：https://hackage-content.haskell.org/package/ghc-9.14.1/docs/GHC-Types-Tickish.html ；
  `-dsuppress-ticks`：https://downloads.haskell.org/ghc/latest/docs/users_guide/debugging.html
- LLVM：https://llvm.org/docs/HowToUpdateDebugInfo.html
- Compiler Explorer `optionsForFilter`（默认 `['-g', '-o', …]`）：
  https://github.com/compiler-explorer/compiler-explorer/blob/main/lib/base-compiler.ts
- JVMS §4.7.12：https://docs.oracle.com/javase/specs/jvms/se21/html/jvms-4.html#jvms-4.7.12

## 十一、不做的（理由）

- **dump 打印 site**：那就是审计文 03 否掉的东西。测试要看，用默认关的 `--sites`。
- **构造器、隐含调用带 site**：没有被调名、没有 parser 节点可配对，语义（回指到哪段源码）也该由要用它的
  M3/M4 定。`CSite` 留了加构造器的余地。
- **每个 site 自带所属声明**：Core 没有内联，一个函数一个 `origin` 等价且省内存；有了内联再加。
- **存名字终点**：源码里一次标识符扫描就能得到，存它是第二份真相。
- **改 comptime 诊断报到子调用上**：是诊断输出变化（`run-diff`、`lsp-diff` 会动），另开一刀。
- **site 进 `LSt` 当隐式状态**：嵌套实参里的调用会覆盖它，错位不会在编译期暴露。
- **Core 层「行号表」**：行号只是 span 的投影，写侧表时由 `line_starts` 算；Core 里存行号会让
  纯移动改 Core 的值。
- **为 site 预留内联来源字段**：没有内联 pass，预留的字段没有测试能证明它对。

## 十二、M3：C 侧表 `__emitc --map`

> 状态：**proposed**（2026-10-05 起草，待评审，未实现）。基于本文 M2（`65c8e56c`，`feat/core-site`）与
> TU 拆分（#530，`docs/c-tu-split-design.md`）。行号指 `65c8e56c` 的 `selfhost/src/c/emitc.dawn`。

### 12.1 要什么

`__emitc <target> -o out.c --map out.dawnmap`（`dawnc emitc` 同一组参数）在写 C 的同时写一份侧表：
每个带 `CAt` 的调用，在 C 文本里落在哪几行、末行的哪一段列。不带 `--map` 时什么都不变；带 `--map` 时
C 文本也不变（12.4 的硬判据）。与 `--split`、`--build-info` 可任意组合。

### 12.2 格式：`.dawnmap` 第 1 版

纯文本，按行，字段以制表符分隔，UTF-8。第一行自描述，其余每行第一个字段是行种类：

```
dawnmap 1 c                                  格式名、版本、后端
text <lines>                                 映射的那份 C 文本（`-o` 所写）的总行数
unit <k> <file> <first> <last>               第 k 个 TU：split 后的文件名、在整份文本里的行区间
src <module> <path>                          模块与它的源文件路径
fn <first> <last> <module> <origin> <symbol> 一个 C 函数体占的行区间、所属声明、C 符号
call <first> <line> <clo> <chi> <module> <lo> <hi> <nlo> <what>
```

- **C 一侧坐标**一律指 `-o` 写出的**整份文本**：行从 1 起，列是该行内从 0 起的半开字节区间
  （C 文本除 `c_escape` 写成八进制的部分全是 ASCII，字节即字符）。`call` 的 `line` 是调用表达式所在行，
  `[clo, chi)` 是表达式在该行里的那一段；`first` 是这次调用开始写 C 的那一行（实参被命名成临时变量时，
  那几行在 `line` 之前），所以 `[first, line]` 是这次调用的全部 C。调用以语句形落地（12.3 第二种）时
  `clo`/`chi` 写 `-`，区间是整行。没能落地的调用（12.3 第三种）三个行列字段都写 `-`。
- **源码一侧坐标**是文件坐标的码点偏移 `lo, hi, nlo`（M2 的 `site_abs`：`base + 相对偏移`），与 `.sites`、
  `dawn parse` 同一种货币。不写行列：行列是偏移对源文件 `line_starts` 的投影，读取方手里有源文件。
- **一份，不分 TU。** 整份文本是正本：差分比的是它，`cdriver.split` 是它的纯函数，`--split` 的每个
  文件都由它切出。侧表跟着正本走，只多一张 `unit` 表告诉读取方怎么换到切开的文件：
  `tuNN.c` 第一行是 `#include "dawn_prog.h"`，所以整份文本第 `L` 行（`first <= L <= last`）在
  `tuNN.c` 里是第 `L - first + 2` 行；函数体只在 TU 里，头文件那段不会有 `fn`/`call` 行。
  每 TU 一份的话，K 由 `tu_count` 按字节数决定，同一程序改一行就可能多一个文件，读取方得先猜有几份；
  一份加一张表没有这个问题。`unit` 表由写出器按 `tu_marker` 行重算，不另记第二份真相，
  测试里拿它和 `cdriver.split` 的实际输出对账（12.5）。
- **路径**：项目模块用 `LoadedModule.site_path`（相对项目根，不随工作目录与命令行写法变，
  `docs/source-location-design.md` §四），std 模块用 `std/<模块>.dawn`（嵌入 stdsrc 的名字）。
- **`what`** 与 `.sites` 同词表（`coresites.callee_text`：`direct m.f`、`method f`、`impl f`、
  `intrinsic name`……），供 oracle 与人读，页面不依赖它。
- **稳定排序**：`unit` 按 k，`src` 按模块名，`fn` 按 `first`，`call` 按 `(line, clo, -chi, module, lo, hi)`
  （同行嵌套时外层在前），未落地的排最后按 `(module, lo, hi)`。排序键是全序，所以同输入同字节；
  emitc 本身是确定的（固定点 B==C 依赖于此），侧表只是它的又一个确定函数。
- **版本**：第一行的 `1`。读取方见到不认识的版本拒绝，见到不认识的行种类跳过（加行种类不升版本，
  改已有字段的含义才升）。

`fn` 行是给页面的「整函数」粒度（CE 式按行着色的底色），也是 oracle 判「这个 site 所在函数是否被
`reach` 裁掉」的依据。

### 12.3 emitc 里在哪里记

emitc 把表达式拼成字符串往上交，写行的只有 `line`（`emitc.dawn:148`）一处（`emit_fn` 的函数头与
收尾 `}` 在体外，不含调用）。一个调用交出的 C 表达式串 `v`，会被**原样**嵌进之后某一次 `line`
写的那一行：`T t = v;`、`(void)(v);`、`return v;`、外层调用的实参……emitc 的正确性本来就要求它恰好
写下一次（`emit_fn` 头注释：「a C expression that is never written down is never evaluated」，写两次就是
求值两次）。所以不需要在串里嵌标记，只要记住这个串，等它出现：

- `emit_expr` 的 `CCall`/`CIntrinsic` 两个 arm（`emitc.dawn:841-842`）在调用 `emit_call`/`emit_intrinsic`
  前记下 `a = len(st.out)`，返回后交给 `note_site(st, site, what, a, v)`：
  1. **表达式形**（`v` 含 `(`）：挂进 `st.pend` 待定。之后每次 `line` 先照常拼出这一行，再在行里找每个
     待定串，找到的出列，记 `(first = a 处的块或本行, line = 本行, clo, chi)`。同一行里几个待定串文本相同
     （`g(f(), f())` 这种没被命名的情形）按入列顺序认领从左到右的不重叠出现。
  2. **语句形**（`v` 是 `DAWN_UNIT` 或不含括号的临时名，且期间写过行）：调用本身就在那几行里，
     记 `[a, len(st.out) - 1]`，列为 `-`。临时名不进待定：`t3` 是 `t30` 的子串。
  3. **无痕**（`v` 是原子、期间没写行，例如被折成常量的内建）：记一行未落地。
- `st.pend` 不为空的时间只在一个函数体里：`emit_fn` 结束时剩下的全部记成未落地（oracle 会让它红），
  另起一份转写的地方（常量构建器 `emitc.dawn:707`、`:1204`）以空 `pend` 开始，免得它们的行认领了
  外面的待定串。
- 记下的行号先是块下标，相对当前转写：`emit_fn` 把体拼到函数头之后时整体平移 `len(st.out) + len(head)`，
  `emit_units` 把每个函数体排进最终文本时再平移到它的落点。块下标换成行号由写出器在最后一步做
  （数之前各块里的换行；`line` 写的块恰好一行，若认领的块里有不在末尾的换行，写出器 panic，
  这只在 `--map` 时才会走到）。
- 待定串、行记录都在 `CSt` 新加的三个字段里（`mapping: Bool`、`pend`、`rows`）。`mapping` 为假时
  `note_site` 立即返回原 `st`，`line` 只多一次 `len(st.pend) == 0` 判断。`line` 写出的文本在两种模式下
  是同一个表达式算出来的，侧表只读它、不改它。
- 驱动：`cdriver.c_text` 不变；新加 `c_text_mapped(std, prog) -> Result[(String, String), String]`，
  返回 C 文本与侧表文本。`base` 表（M2 的 `main.decl_bases`）挪进 `ir/coresites`，`__lower --sites`
  与侧表写出器共用。写出器单独一个模块 `c/cmap.dawn`，emitc 只交出原始行记录。

为什么按「串出现在哪一行」而不是在 `line` 处给每个表达式标号：emitc 的表达式是字符串，没有地方挂
标号；给串加不可见标记再在输出前剥掉，等于在默认路径上多一遍扫描，也就不再是「对 C 文本零影响」
的结构性论证。按出现认领只在 `--map` 时花钱，代价是要靠上面那条「恰好写下一次」的不变式，
而这条不变式 oracle 会逐个调用检查（12.5）。

### 12.4 对 C 文本零影响：怎么证明

1. **结构**：上一节的改动里，C 文本只经过 `line` 的同一个拼接表达式与 `emit_units` 的同一段排布；
   新字段只被 `note_site`、`line` 的认领分支和写出器读写。
2. **同输入有无 `--map`**：同一个编译器对同一输入跑 `__emitc -o a.c` 与 `__emitc -o b.c --map m`，
   `a.c` 与 `b.c` 逐字节相同；加 `--split` 时两个目录逐文件相同。输入：`nmain.dawn`（整个原生编译器，
   17 个 TU）、`scripts/tile-golden/kernels.dawn`、`examples/` 里能走 C 后端的程序、`scripts/core-sites/corpus.dawn`。
   脚本 `scripts/c-map/same.sh`。
3. **对真父**：不带 `--map` 时本分支与真父对同一输入的 `__emitc` 输出逐字节相同（同 M2 硬判据），
   `native-fixpoint.sh` B==C。
4. **两条入口一致**：`__emitc --map`（JVM 上）与 `dawnc emitc --map`（固定点里编出的原生编译器）对
   `nmain.dawn` 写出的侧表逐字节相同，与两边 C 文本 A==B 是同一条要求。
5. **负控**：变异体 `text-leak` 在认领时往行尾加一段注释，第 2 条红。

### 12.5 测试与负控

- **oracle**（`scripts/c-map/check.py`，读取部分放 `scripts/c-map/dawnmap.py`，M7 复用）：同一目标再跑一次
  `__lower --sites`，然后检查：
  - **配对**：每个 `call` 行的 `(module, lo, hi, nlo)` 恰是 `.sites` 里的一行（M2 已证明 `.sites` 与
    parser 调用节点一一对应，所以这里传递到源码）；`fn` 表里的每个函数，它在 `.sites` 里的每一行
    在侧表里恰好出现一次（完整、单射）；被 `reach` 裁掉的函数（不在 `fn` 表里）的行不要求出现。
  - **C 侧位置**：取整份文本第 `line` 行的 `[clo, chi)`，按 `what` 判：`direct m.f` 要包含
    `mangle(m, f)`（oracle 用 Python 独立实现 `escape_part` 那张五行的表，不读编译器）；`impl`/`default`
    要包含被调方法名的转义；`method` 要包含 `->slots[`，`dynamic` 要包含 `->fn)`；`intrinsic` 只要求
    区间非空。语句形的行区间要落在所属 `fn` 的区间里。另查 `first <= line`、同一调用树的嵌套：源码 span
    包含的两个调用，C 区间也包含（同行比列，跨行比行）。
  - **TU**：对每个 `call`，按 `unit` 表换到 `--split` 写出的 `tuNN.c` 里那一行，文本与整份文本那一行相同。
  - 样本：`kernels.dawn` 的 `flash_attn`（及 `vadd`、`softmax`）每个 sited 调用都落地、名字核对通过；
    `corpus.dawn` 全部；`nmain.dawn` 整个编译器只跑统计（未落地数必须为 0，列出例外类别）。
- **单元**：`c/emitc` 的 test 块用手搭的 `CFun` 钉住三种落地形与平移；`c/cmap` 的 test 块钉住排序、
  `unit` 表与 `cdriver.split` 一致。
- **负控**（`scripts/c-map/mutate.py` 登记、`run.py` 逐个建编译器验红，锚点归
  `mutation-anchor-preflight.py`）：
  1. `text-leak`：认领时改了行文本：12.4 第 2 条红；
  2. `no-claim`：`line` 不认领待定串：全部未落地，完整性红；
  3. `head-shift`：`emit_fn` 平移时少算函数头：行号错一到几行，名字核对红；
  4. `col-pad`：列不算缩进：名字核对红；
  5. `unit-off`：`unit` 表的 `first` 差一：TU 对账红。
- **接入**：push 预算余量为 0，先挂 nightly 的 core-lint job（与 `scripts/core-sites` 并列一步）。

### 12.6 给 M7 的读取方

M7 页面的读取方是 Python（M1 的 `site/gpu-map/record.py` 那一层），用 `scripts/c-map/dawnmap.py` 的
`load(path) -> {units, srcs, fns, calls}`，它需要的全在表里：

- 源码栏：`src` 给路径，`call` 给 `[nlo, hi)` 高亮被调名、`[lo, hi)` 是整个调用；嵌套由 span 包含还原。
- C 栏：`[first, line]` 与末行列区间；要逐行着色（CE 的形态）时，每行取覆盖它的最内层调用。
- 切开的文件：用 `unit` 表换算，不必重新切。

与 Compiler Explorer 的对照：CE 的汇编视图靠编译器发出的 `.loc file line` 指令（`lib/parsers/asm-parser.ts`
的 `sourceTag = /^\s*\.loc\s+(\d+)\s+(\d+)\s+(.*)/`），每条汇编行带一个 `{file, line}`，即**输出行到源码行**
的多对一表，颜色按源码行分组。本表反过来是**源码调用到输出区间**，每个调用一行、带列区间与嵌套；CE 那张
表是它的投影（每个输出行取最内层调用的源码行），反之推不出来。

**为什么侧表不用 `#line`**：裁决已否；一句话：`#line` 只到行、给不出调用区间，而默认写进 C 会让每份 C
随纯移动漂移，prev-diff 与固定点拿 C 字节当证据的那层判据就没了（第十节同理，真调试信息归 M6，默认关）。

出处：Compiler Explorer `asm-parser.ts`：https://github.com/compiler-explorer/compiler-explorer/blob/main/lib/parsers/asm-parser.ts
（抓取于 2026-10-05）。

### 12.7 开销

`--map` 关时：`CSt` 多三个字段（每次 `{..st}` 拷贝多三个指针），`line` 多一次判空。按 M2 的测法
（同输入、交错、`-Xmx6g -XX:+UseSerialGC`）报 `__emitc nmain --split` 的墙钟、峰值 RSS 与分配量，
真父对本分支；分配量预期在 +0.5% 以内，超过 2% 写原因。`--map` 开时另报一组，只作记录，不设门限
（它是按需工具）。估算不作数，以实测为准。

### 12.8 不做的（理由）

- **每 TU 一份侧表**：K 随字节数变，读取方得先猜份数；一份加 `unit` 表等价且稳定。
- **侧表里写源码行列**：行列是偏移对 `line_starts` 的投影，第二份真相；读取方有源文件。
- **在 C 串里嵌标记再剥掉**：默认路径多一遍扫描，零影响就只能靠测试而不是靠结构。
- **`#line` / 默认 `-g`**：见 12.6，归 M6，默认关。
- **构造器、隐含调用（`==`、插值、`for`、`?`、`c[i]`）进表**：Core 里它们没有 site（第四节）。要加是
  `CSite` 加构造器，与本刀独立；本刀的落地机制对它们照样适用。
- **自尾调用改成的循环回边、内建折成的运算符进表**：调用在 Core 里已经消失（第五节「丢弃」），C 里没有
  对应的调用可指。
- **适配器（`emit_adapter`）、字典表、常量构建器进 `fn` 表**：没有书写调用，也没有所属声明。
- **映射到 cc 之后的汇编或机器码**：那是 cc 的 DWARF 的事；要看汇编，用 M6 的 `#line` 加 `-g` 走 CE 的路。
- **带 `--map` 时自动建目录、与 `-o` 推导文件名**：侧表路径显式给，与 `--build-info` 同一种约定。
