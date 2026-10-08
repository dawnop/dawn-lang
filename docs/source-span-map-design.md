# 源码位置进 Core：调用节点的 site 与按需侧表

> 状态：**proposed**（M2，2026-10-05 起草，待评审，未实现；M2 已合入 `b1b25062`；M3 C 侧表见第十二节；M4 JVM 侧表见第十三节）。源码位置模型一线（M 刀序）的第二刀；
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

- 运算符与 staged `for` 是**书写的调用，只是不写成 `Apply`**：`a + b` 在用户类型上是 `Add` 的 impl 调用，
  `-a` 是 `Neg` 的，carried `var` 的 `for` 降成一次 `staged_for`。它们保留整条表达式（语句）的 site，
  名字起点是运算符记号（`for` 关键字）。parser 一侧配对的是 `Binary`/`Unary`/`For` 节点；oracle 只允许
  `impl add/sub/mul/div/rem` 配 `Binary`、`impl neg` 配 `Unary`、`impl staged_for` 配 `For`，别的 site 落在这些节点上
  仍是「is no call the parser sees」。完备性仍只数 `Apply`/`MethodCall`：`+` 与 `for` 在 parse 里通常不是调用，
  只有检查器路由到 trait 方法的才有 site。GPU 页把 tile 运算符与 `d_range` 的整条语句当调用，靠这些行进 C 侧表。
- 同一次降级里检查器**自己加**的是另一回事：`var_open`/`var_get`/`var_set` 没有书写对应物，`nlo = NO_NAME`、
  `CNoSite`。曾把它们的 `nlo` 填成变量或语句起点，oracle 在 flash_attn 上报「is no call the parser sees」，
  那是检查器写错，不是规则错。
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
  1. `absolute`：降低时不减 `base`：check.py 报「is no call the parser sees」或「fall in no function of the file」（翻倍的偏移落在被查 kernel 内报前者，落到所有函数之外报后者，取决于 kernel 的大小，所以两者都算检出）；
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

> 状态：**proposed**（2026-10-05 起草，同日实现于分支 `feat/emitc-map`，待合入）。基于本文 M2（合入为
> `b1b25062`）与 TU 拆分（#530，`docs/c-tu-split-design.md`）。行号指 `65c8e56c` 的
> `selfhost/src/c/emitc.dawn`；12.5、12.7 的实测在 `995e2396` 之上。

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
  `tuNN.c` 里是第 `L - first + 2` 行（没有 TU 标记的文本整份就是 `main.c`，行号不变）；函数体只在 TU 里，
  头文件那段不会有 `fn`/`call` 行。
  每 TU 一份的话，K 由 `tu_count` 按字节数决定，同一程序改一行就可能多一个文件，读取方得先猜有几份；
  一份加一张表没有这个问题。`unit` 表由 `cdriver.unit_lines` 按 `split` 切的同一种标记行重算，
  不另记第二份真相，测试里拿它和 `cdriver.split` 的实际输出对账（12.5）。
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
  前记下 `a = len(st.out)`，返回后交给 `note_call`/`note_intrinsic(st, a, …, site, v)`：
  1. **表达式形**（`v` 含 `(`）：挂进 `st.pend` 待定。之后每次 `line` 先照常拼出这一行，再在行里找每个
     待定串，找到的出列，记 `(first = a 处的块或本行, line = 本行, clo, chi)`。同一行里几个待定串文本相同
     （`g(f(), f())` 这种没被命名的情形）按入列顺序认领从左到右的不重叠出现：游标**按文本**各记一个，
     认领一次就移到该次出现之后，所以同文本的后一个只能落在前一个之后；不同文本之间不共用游标，
     因为内层调用的串就在外层调用的串里面（`f(x)(y)` 的 `f(x)` 恰好打头），外层得从行首找。
     没有 site 的调用（`CNoSite`）也入列，只是不出行：它占住自己那次出现，同文本的有 site 调用才不会
     认领错。实测今天的 emitc 从不把两个同文本调用写在同一行（一行里有两个要跑代码的操作数时，
     `emit_row` 把每个都先命名成临时变量），nmain、kernels 上同行同文本的行对都是 0（12.5）。所以这条
     规则由单元测试与 oracle 的自检钉住，不靠真实程序。
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
  `note_call`/`note_intrinsic` 立即返回原 `st`，`line` 只多一次 `len(st.pend) == 0` 判断。`line` 写出的文本在两种模式下
  是同一个表达式算出来的，侧表只读它、不改它。
- 驱动：`cdriver.c_text` 不变；新加 `c_text_mapped(std, prog) -> Result[(String, String), String]`，
  返回 C 文本与侧表文本，两者都出自 `emitc.program_st`，`emit_program` 与 `emit_program_mapped` 只差
  `mapping` 这一个参数。`base` 表（M2 的 `main.decl_bases`）挪进 `ir/coresites`，`__lower --sites`
  与侧表写出器共用。写出器单独一个模块 `c/cmap.dawn`，emitc 只交出原始行记录。`__emitc` 与
  `dawnc emitc` 都认 `--map`；用法文本没有加这一项（与 `--split` 一样不列），所以 CLI 输出不变。

为什么按「串出现在哪一行」而不是在 `line` 处给每个表达式标号：emitc 的表达式是字符串，没有地方挂
标号；给串加不可见标记再在输出前剥掉，等于在默认路径上多一遍扫描，也就不再是「对 C 文本零影响」
的结构性论证。按出现认领只在 `--map` 时花钱，代价是要靠上面那条「恰好写下一次」的不变式，
而这条不变式 oracle 会逐个调用检查（12.5）。

### 12.4 对 C 文本零影响：怎么证明

1. **结构**：上一节的改动里，C 文本只经过 `line` 的同一个拼接表达式与 `emit_units` 的同一段排布；
   新字段只被 `note_call`/`note_intrinsic`、`line` 的认领分支和写出器读写。
2. **同输入有无 `--map`**：同一个编译器对同一输入跑 `__emitc -o a.c` 与 `__emitc -o b.c --map m`，
   `a.c` 与 `b.c` 逐字节相同；加 `--split` 时两个目录逐文件相同。输入：`nmain.dawn`（整个原生编译器，
   16 个 TU 加头文件）、`scripts/tile-golden/kernels.dawn`、`examples/` 里能走 C 后端的程序、
   `scripts/c-map/corpus.dawn`（M2 的语料用了 `use java`，C 后端不收，另写了一份）。脚本
   `scripts/c-map/same.sh`；实测 40 个输入相同，16 个是 C 后端不收或不是独立程序的文件，跳过。
   `check.py` 每晚在它的三个样本上再比一次。
3. **对真父**：不带 `--map` 时本分支与真父对同一输入的 `__emitc` 输出逐字节相同（同 M2 硬判据），
   `native-fixpoint.sh` B==C。
4. **两条入口一致**：`__emitc --map`（JVM 上）与 `dawnc emitc --map`（固定点里编出的原生编译器）对
   `nmain.dawn` 写出的侧表逐字节相同，与两边 C 文本 A==B 是同一条要求。
5. **负控**：变异体 `text-leak` 在 `--map` 时给每行多写一个空格，第 2 条红。
6. **`--map` 关时队列一直是空的**：`note_call`/`note_intrinsic` 第一句就是 `if not st.mapping { st }`，
   队列只有它们会加；单元测试「emitting with --map writes the same C, and without it records nothing」
   对同一棵 Core 关、开各发一次，断言两边 C 相同、关时 `pend` 与 `rows` 都空。开销实测见 12.7。

### 12.5 测试与负控

- **oracle**（`scripts/c-map/check.py`，读取部分放 `scripts/c-map/dawnmap.py`，M7 复用）：同一目标再跑一次
  `__lower --sites`，然后检查：
  - **配对**：每个 `call` 行的 `(module, lo, hi, nlo)` 恰是 `.sites` 里的一行（M2 已证明 `.sites` 与
    parser 调用节点一一对应，所以这里传递到源码）；`fn` 表里的每个函数，它在 `.sites` 里的每一行
    在侧表里恰好出现一次（完整、单射）；被 `reach` 裁掉的函数（不在 `fn` 表里）的行不要求出现。
  - **C 侧位置**：取整份文本第 `line` 行的 `[clo, chi)`，按 `what` 判：`direct m.f` 要包含
    `mangle(m, f)`（oracle 用 Python 独立实现 `escape_part` 那张五行的表，不读编译器）；`impl`/`default`
    要包含被调方法名的转义；`method` 要包含 `->slots[`，`dynamic` 要包含 `->fn)`；`intrinsic` 只要求
    区间非空。语句形的行区间要落在所属 `fn` 的区间里，且其中一行有该符号。另查 `first <= line`。
  - **一处一认**：没有两行认领同一行的同一段列。
  - **同行有序**：同一个 C 函数、同一行上的两行，源码 span 互不包含时，C 里的先后与源码先后一致。
    同文本的两个调用若被认反（后一个拿了前一个的出现），这条红；都认到同一次出现，上一条红。
  - **同行嵌套**：同一 C 函数、同一行上，源码 span 包含的两个调用，C 列区间也包含。跨行不比：实参被
    命名成临时变量后，内层在前几行，外层的列区间里只剩临时名，`[first, line]` 的包含才是对的那一层。
    lambda 体里的调用在另一个 C 函数里，也不比。
  - **自检**（`check.py --self-test`）：在手写的单行侧表上验这几条规则会红：同一行两个同文本调用认反、
    认到同一次出现，以及内层调用的串打头外层调用的串时认到外层之后。真实程序里这两种形状不出现（上面
    12.3 的实测），这是证明规则有牙的唯一办法。
  - **TU**：对每个 `call`，按 `unit` 表换到 `--split` 写出的 `tuNN.c` 里那一行，文本与整份文本那一行相同。
  - 样本：`kernels.dawn`（整个程序，`flash_attn`、`vadd`、`softmax` 在内）、`scripts/c-map/corpus.dawn`
    全部、`nmain.dawn` 整个编译器，全部规则都跑，未落地数必须为 0。实测（`995e2396` 之上）：

    | 样本 | 行 | 语句形 | 函数 | TU | 同函数同行的行对 | 其中同文本 |
    |---|---|---|---|---|---|---|
    | corpus | 23 | 0 | 12 | 1 | 1 | 0 |
    | kernels | 10224 | 86 | 3005 | 8 | 490 | 0 |
    | nmain | 18411 | 201 | 4413 | 16 | 358 | 0 |

    每个样本里被保留函数的 site 全部在表里（kernels 10224 个、nmain 18411 个），没有一个未落地。
- **单元**：`c/emitc` 的三个 test 块：同一行两个同文本调用按从左到右认领（含一个无 site 的同文本调用
  占位在前）、内层调用的串打头外层的串时两者都认在原位（列含缩进）、同一棵 Core 开关 `--map` 输出
  相同且关时什么都不记；`c/cmap` 的 test 块钉住排序与 `?`；`c/cdriver` 的 test 块钉住 `unit_lines`
  与 `split` 切出的文件逐行一致。
- **负控**（`scripts/c-map/mutate.py` 登记、`run.py` 逐个建编译器验红，锚点归
  `mutation-anchor-preflight.py`）：
  1. `text-leak`：认领时改了行文本：12.4 第 2 条红；
  2. `no-claim`：`line` 不认领待定串：全部未落地，完整性红；
  3. `head-shift`：`emit_fn` 平移时少算函数头：行号错一到几行，名字核对红；
  4. `col-pad`：列不算缩进：名字核对红；
  5. `unit-off`：`unit` 表的 `first` 差一：TU 对账红；
  6. `same-line-twin`：认领后游标不前移，同一行第二个同文本调用拿到第一个的出现。今天的 emitc 不写这种行，
     所以它对 check.py 是等价变异体；由 `dawn test selfhost` 里的单元测试判红（run.py 对它跑测试而不跑
     check.py），check.py 自己那条规则由 `--self-test` 判红；
  7. `prefix-enclosing`：所有文本共用一个游标：内层认领后，外层只在它之后找，找不到：语料里的 `h(h(x))`
     在 check.py 上「has no place in the C」。
  实测七个全红，`run.py` 本机 488 s（`check.py --self-test` 与正控在前）。
- **接入**：push 预算余量为 0，挂 nightly 的 core-lint job（与 `scripts/core-sites` 并列一步）。本机
  check.py 78 s（负载 4 时）到 194 s（与其他写者并跑），run.py 488 s。

### 12.6 给 M7 的读取方

M7 页面的读取方起初是 Python（M1 的 `site/gpu-map/record.py` 那一层），用 `scripts/c-map/dawnmap.py` 的
`load(path) -> {units, srcs, fns, calls}`；K1 之后是 Dawn 包 `packages/xmap`（`src/dawnmap.dawn` 读同一种表，只取
`fn` 与 `call` 两种行，其余行种按本节的兼容规则跳过）。它需要的全在表里：

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
（同输入、交错、`-Xmx6g -XX:+UseSerialGC`）测 `__emitc nmain.dawn --split`：A = 真父 `995e2396`，
B = 本分支不带 `--map`，C = 本分支带 `--map`，ABC 交错。本机负载约 4。

| 量 | A 真父 | B 不带 `--map` | C 带 `--map` |
|---|---|---|---|
| 墙钟（中位数，7 次） | 6.24 s [5.39–6.38] | 6.19 s [5.09–6.30] | 6.62 s [5.69–6.70] |
| CPU user | 18.75 s | 18.93 s | 19.20 s |
| 峰值 RSS | 924 MB [878–970] | 925 MB [873–1008] | 993 MB [979–1007] |
| 分配量（JFR，5 次） | 10702 / 10707 / 11073 / 11079 / 11085 MB | 10699 / 10708 / 10724 / 11090 / 11096 MB | 11940–11957 MB |

- 分配量用 JFR 的 `jdk.ObjectAllocationInNewTLAB` 的 `tlabSize` 加 `jdk.ObjectAllocationOutsideTLAB` 的
  `allocationSize` 求和（TLAB 粒度，精确到每次 TLAB），不是 M2 用的 GC 日志回收量之和：回收量之和漏掉最后
  一段没回收的 eden，在这里抖动 ±4%，分不出 0.5% 的差别。
- A、B 的分配量都是双峰（约 10.70 GB 与 11.08 GB 两档，同一个 jar 反复跑也会跳档），所以按档比：低档
  A 10702/10707、B 10699/10708/10724，高档 A 11073/11079/11085、B 11090/11096，同档差在 ±0.2% 以内。
  也就是说不带 `--map` 时测不出代价，与 12.4 第 6 条的结构性论证一致：队列一直是空的，`line` 只做一次判空。
- 带 `--map`：分配多约 0.9–1.2 GB（+8%～+12%），墙钟 +7%，RSS +7%。多出来的是每个调用一个待定记录与
  一行记录（nmain 有 18411 行），以及认领时每写一行就对队列里每个串做一次 `str.drop` 加 `index_of`。
  这是按需工具，不设门限；要再省，第一步是 `from == 0` 时不切串。

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

## 十三、M4：JVM 侧表 `__emit --map`

> 状态：**proposed**（2026-10-06 起草，同日实现于分支 `feat/emit-map`，待合入）。基于本文 M2（`b1b25062`）
> 与第十二节 M3（合入为 `5b4452f2`）；格式、读取方、`coresites.decl_bases` 与 `src` 路径规则沿用 M3。
> 行号指 `ee21f5a5` 的 `selfhost/src/jvm/emit.dawn`；实测在 `5b4452f2` 之上。

### 13.1 要什么

`__emit <target> -o <dir> --map <file>` 在写 class 的同时写一份侧表：每个带 `CAt` 的调用，在哪个类的
哪个方法里、占字节码的哪段 pc、实现它的那条 invoke 指令在哪个 pc。不带 `--map` 时什么都不变；带
`--map` 时写出的 class 也逐字节不变（13.4），这一条在本节的方案里是**构造上**成立的，不是靠测出来的。
M7 页面的 JVM 一栏是「类 javap 的反汇编列表 + 本表」，列表不由编译器写（13.6）。

### 13.2 格式：`dawnmap 1 jvm`

与 12.2 同一个格式，第一行的后端字段写 `jvm`。`src` 行逐字相同；`fn`、`call` 两种行的**源码半边
位置与含义与 C 后端相同**，只有输出半边换成 JVM 的坐标：

```
dawnmap 1 jvm
src  <module> <path>                                      同 12.2
fn   <k> <len> <module> <origin> <symbol>                 第 k 个方法：code_length、所属声明、owner.name:desc
call <k> <pclo> <pchi> <ipc> <module> <lo> <hi> <nlo> <what>
```

- `fn` 的输出半边：C 是 `<first> <last>`（函数体的行区间），JVM 是 `<k> <len>`：方法序号与 Code 属性的
  `code_length`（方法的 pc 全域是 `[0, len)`）。`symbol` 是 `类.方法:描述符`，与 javap 注释
  `// Method a.sq:(J)J` 同一种写法，读取方据此在 javap 列表里找到这个方法。`k` 按 `(类, 方法名, 描述符)`
  排序编号，从 0 起。
- `call` 的输出半边：`<k>` 指所在方法；`[pclo, pchi)` 是这次调用的全部字节码（被调表达式、实参、调用
  指令、调用后的拆箱/`Option` 包装），半开、单位字节；`ipc` 是实现这次调用的那条 invoke 指令的 pc。
  内建（`intrinsic`）没有「那一条」指令（可能是一条 `invokestatic`，可能是几条，可能是 `lmul`），
  `ipc` 写 `-`；后面四个源码字段与 12.2 逐位相同。没能落地的调用三个 pc 字段写 `-`：所在类在 13.4 的
  比对里不同、所在方法在 13.3 的展开检查里不过，或者实参不返回、调用指令根本没写出来。
- JVM 的字节码区间天然连续：ASM 只在尾部追加，`gen_cexpr` 递归地把一次调用的全部代码写在一起，没有
  C 那样「实参先命名成临时变量写在前几行」的形状；`operands.prepare` 把带跳转的实参提升成前面的
  `CSLet` 时，被提升的那次调用有它自己的一行，外层调用的区间从它之后开始。所以不需要 12.2 的
  `first`/语句形。
- 只有 `gen_cbody` 写出的方法进 `fn`（顶层函数、impl/default 方法、提升的 lambda、test 块）：只有它们
  有 `CFun`，有 `origin`。test 块与从它提升的 lambda 也在表里（`origin` 是 `Ns..`），它们是 class 里
  真实的字节码；`__lower --sites` 不列 test 块，所以 oracle 对它们只免「反向配对」一条（13.5）。JVM 入口包装 `main([String)`、SAM 桥、闭包类的 `apply`、字典类、常量初始化
  没有书写调用，与 12.8 对适配器的处理一致。
- 稳定排序：`src` 按模块名，`fn` 按 `k`，`call` 按 `(k, pclo, -pchi, module, lo, hi)`（同起点时外层在前），
  未落地的排最后。同输入同字节。
- **读取方**：`scripts/c-map/dawnmap.py` 的 `load` 改成按第一行的后端字段分派 `fn`/`call` 输出半边的
  字段名（`c`：`first last` / `first line clo chi`；`jvm`：`k len` / `k pclo pchi ipc`），源码半边的键不变，
  不认识的后端拒绝。版本仍是 `1`：没有任何已有字段改含义，`jvm` 是新的后端值；读取方除了 M3 的 checker
  还没有别的使用者，这是不付代价就能统一的时刻。文件留在原处，`scripts/jvm-map/check.py` 从
  `scripts/c-map/` 导入，一种格式只有一个解析器。

### 13.3 在 ASM 里怎么记 pc

**用 `Label`，不包装 `MethodVisitor`。** 包装（ASM 的 `MethodVisitor(api, mv)` 委托子类，数 `visit*` 调用）
在 Dawn 里写不出来：Dawn 不能继承 Java 类（`jvm/classread.dawn` 头注释记过同一堵墙）；改成由编译器发射一个
`dawn/rt/` 计数类，又会把它写进每个程序的运行时，默认产物就变了。`Label` 是已经在用的 API（循环、`if` 的
跳转都靠它），`Label.getOffset()` 在 `visitLabel` 之后立即可读，值是方法 code 数组里的字节偏移。

记的位置：

- `gen_cexpr` 的 `CCall`/`CIntrinsic`/`CForeign` 三个 arm（`emit.dawn:2492`、`:2557`、`:2558`）：site 为
  `CAt` 时，生成前 `visitLabel(lo)`，生成后 `visitLabel(hi)`；
- invoke 之前一个 `Label`：`gen_ccall` 的四条 `visitMethodInsn`（`emit.dawn:2129` 起）、`gen_cdynamic` 的
  `apply`、`gen_java_call`/`gen_java_new` 的那一条。这几个函数加一个 `at: Option[Label]` 参数，`Some` 时
  在 invoke 前 `visitLabel`。
- 记下的 `(site, what, lo, inv, hi)` 进 `Gen` 的新字段 `marks`，`gen_cbody` 关闭方法后把 Label 换成
  偏移，连同方法名与描述符交给模块级的列表。`marks` 只在 `GenCtx` 的新字段 `mapping` 为真时写，
  `mapping` 是模块级只读事实，放 `GenCtx`（它的头注释说的就是这一类）。

**pc 稳不稳。** 偏移在 `visitLabel` 时定下，之后 code 数组只在一种情形下挪动：ASM 写前向跳转先留 16 位
偏移，`Label.resolve` 发现放不下时把指令记成内部伪指令，`ClassWriter.toByteArray` 用
`EXPAND_ASM_INSNS` 重读整个类并改写成 `goto_w`（条件跳转改成反条件加 `goto_w`），此后 pc 平移。
展开只会让方法变长，所以检查是精确的：带标签的那一遍在每个方法体写完时再打一个 `end` 标签，记下当时
的长度（`JFn.end`）；写侧表时与 class 里的 `code_length` 比，不等就是展开过，这个方法的调用一律记成
未落地。最初的设计是「`code_length >= 32768` 一律不给」，实测换成了精确检查：kernels 的
`main.trace`（47761 字节，一个按名字分派的大 `match`）真的被展开了，javap 里有 64 条 `goto_w`，它的
576 行没有 pc；而 selfhost 最长的方法 19783 字节（`embed/` 的 Unicode 表，不受 8000 字节门约束），一个也没有。
其余两件看着可疑的事都不挪 pc：

- **COMPUTE_FRAMES**：帧写在 `StackMapTable` 属性里，不在 code 数组里；不可达代码被换成等长的
  `nop … athrow`，长度不变。
- **方法拆分（8000 字节门）**：编译器不自动拆方法。`docs/method-size-gate-design.md` 的门禁是**源码级**
  拆分加 jar 扫描，拆完的方法就是普通方法，pc 与别的方法一样定。它与本表的唯一交点是 `code_length`：
  `fn` 行的 `len` 与 `scripts/method-size-gate.py` 读的是同一个字段，oracle 用同一种读法核对。

**但 Label 本身可能改字节。** COMPUTE_FRAMES 下 `visitLabel` 会开一个新的基本块。可达代码里多切一刀
不改输出：只给跳转目标写帧，最大栈按块求最大值，切开前后相同。不可达代码里多切一刀会改：ASM 对每个
不可达块各写一段 `nop … athrow` 加一帧，一块变两块就多一帧。今天的发射器会写不可达代码：`gen_cargs`
不看实参是否落空（`f(panic("x"), g(y))` 里 `g(y)` 与 `f` 的 invoke 都在死代码里）。所以「带 Label 的那份
class 与不带的逐字节同」不能当作公理，只能当作每次都核对的事实，见下一节。

### 13.4 对 class 字节零影响：构造上成立

**发射两遍。** 带 `--map` 时，`emit_module` 对每个模块跑两遍：第一遍 `mapping = false`，产出的 class 就是
写进 `-o` 的那些；第二遍 `mapping = true`，只取模块类的字节与 `marks`，其余（ADT、字典、闭包类）丢弃。
然后逐类比：第二遍的模块类字节与第一遍**相同**，这个类的 pc 才写进表；不同，这个类的全部调用记成
未落地。

**实测**（`5b4452f2` 之上）：`scripts/jvm-map/dead.dawn` 的 `f(panic("no"), g(x))` 让第二遍的 `dead` 类与
第一遍不同，它的 8 行全部没有 pc，13.3 的推断成立。真实程序里退回的类是 0：selfhost 114 个模块类、
kernels 19 个、site 48 个，第二遍与第一遍逐字节相同；全部未落地的行只有 kernels 那个被展开的方法。
于是：

1. **同输入有无 `--map`**：写进 `-o` 的字节来自 `mapping = false` 的那一遍，与不带 `--map` 时是同一个
   函数、同一组实参。新加的代码在这一遍里只做两件事：`if gx.mapping` 判假，`at` 传 `None`。没有一个
   `visit*` 调用的先后或参数因 `--map` 而不同。这是结构论证；`scripts/jvm-map/same.sh` 再对语料逐文件
   比一次，作为它的回归。
2. **对真父**：不带 `--map` 时本分支的 `__emit` 输出与真父逐字节相同（prev-diff 的 `emit *` 十个 label
   无差异，提交不带 Emit-Change），`selfhost-fixpoint` B==C。
3. **侧表可信**：pc 来自第二遍，只有当第二遍的类字节与第一遍完全相同时才采用。字节相同意味着 code 数组
   相同，pc 的含义也就相同；常量池、帧也相同，所以不用担心多出一帧把后面方法的常量池下标挪了
   （那正是不能逐方法比、只能逐类比的原因）。加上 13.3 的展开检查，写出的每个 pc 都指向
   `-o` 里那份 class 的那条指令。
4. **两遍为什么不并成一遍**：一遍（直接在输出那份上打 Label）的话，`--map` 会改不可达代码所在类的字节，
   要证明「不改」只能靠测试覆盖，而 13.3 已经给出了改的例子；两遍让输出不依赖 `--map`，Label 的副作用
   只会让侧表少几行，不会让产物错。代价是带 `--map` 时多一遍发射（13.7 实测）。
5. **为什么不用一个「临时」ClassWriter 只为单个方法打 Label**：常量池按访问顺序建，临时类的池与真类不同，
   `ldc` 与 `ldc_w` 的选择取决于下标是否小于 256，pc 就可能不同。只有同一个模块、同一顺序重放，池才相同。

**为什么不用 LineNumberTable / SourceDebugExtension**（裁决已否，复述一句）：默认产物字节不变是硬要求，
而 LNT 只到行、SMAP（JSR-45）只是行到行的重映射，都给不出调用区间，写进 class 还会让每个 class 随纯移动
漂移；真调试信息归 M6，默认关。

### 13.5 测试与负控

- **oracle**（`scripts/jvm-map/check.py`，读取用 `scripts/c-map/dawnmap.py`）：对同一目标跑 `__emit -o`、
  `__emit -o --map` 与 `__lower --sites`，用 JDK 的 `javap -c -p -s` 读写出的 class（与写它的工具链无关，
  也正是 M7 页面要展示的列表），用 `scripts/method-size-gate.py` 的 struct 读法读 `code_length`，检查：
  - **相同**：带与不带 `--map` 写出的 class 目录逐文件相同。
  - **配对**（同 12.5）：每个 `call` 行的 `(module, lo, hi, nlo)` 恰是 `.sites` 的一行，没有两行同一处；
    `fn` 表里出现的每个 `(module, origin)`，它在 `.sites` 里的每一行在侧表里都有。test 块（`origin` 为
    `Ns..`）与从它提升的 lambda 不在 `.sites` 里，它们的行免「是 `.sites` 的一行」这一条，其余规则照查。
  - **落地**：没有 pc 的行只许出现在两处：`dead` 一例的 `dead` 类（必须**全部**没有），以及 javap 里有
    `goto_w` 的方法（可以没有；若有 pc，照下面各条查，所以不展开检查却留下的旧 pc 会红）。
  - **方法**：`fn` 行的 `symbol` 在 javap 里恰有一个方法（类、名、`descriptor:` 都对上）；`len` 等于
    Code 属性的 `code_length`。
  - **边界**：`pclo`、`ipc` 是 javap 列出的指令起点，`pchi` 是指令起点或等于 `len`；`pclo <= ipc < pchi`。
  - **指令**：`ipc` 处是 `invoke*`，且按 `what` 判 owner/name：`direct m.f` 要 `invokestatic m.f`
    （javap 对本类省略 owner，按本类补全）；`impl f`/`default f` 要 `invokestatic` 且名字是
    `dawn$impl$..$f`/`dawn$default$..$f`（oracle 独立拼写，不读编译器）；`method f` 要
    `invokeinterface ..f`；`dynamic` 要 `invokeinterface dawn/rt/FnN.apply`；`java m` 要成员名 `m`。
    `intrinsic` 要求没有 `ipc`、区间非空。
  - **一处一认**：没有两行的 `ipc` 是同一条指令。
  - **嵌套**：同一方法里源码 span 包含的两个调用，pc 区间也包含，或内层整个在外层之前（被 `prepare` 提升）。
  - **自检**（`check.py --self-test`）：一份手写的 javap 列表（含 `tableswitch` 与 `static {}`，两者都曾
    或可能让解析器把别的方法的指令算进来）与十几份各坏一处的小表，每条规则都要红。
  - 样本与实测（`5b4452f2` 之上，本机）：

    | 样本 | 行 | 有 pc | 无 pc | 方法 | 类 | test 块里的行 |
    |---|---|---|---|---|---|---|
    | corpus（`scripts/core-sites/corpus.dawn`，含 `use java`） 158 | 158 | 0 | 65 | 6 | 0 |
    | kernels 13266 | 12690 | 576 | 4012 | 19 | 2997 |
    | dead 9 | 1 | 8 | 5 | 2 | 0 |
    | selfhost 35855 | 35855 | 0 | 7819 | 114 | 10023 |

    kernels 的无 pc 行全在被展开的 `main.trace` 里；dead 的无 pc 行全在 `dead` 类里。
- **相同（更广）**：`scripts/jvm-map/same.sh` 对 selfhost、kernels、corpus、dead、site 与 `examples/` 里
  能编的全部程序与项目，同一编译器带与不带 `--map` 各写一次，目录逐文件比。实测 58 个输入全部相同，268 s。
- **单元**：`jvm/emit` 的 test 块对同一棵 Core（嵌套的两个带 site 调用）关、开 `mapping` 各发一次：两份
  class 字节相同，关时 `marks`/`jrows`/`jfns` 全空，开时两行的 pc 与 `ipc`、方法的 `end` 与
  `classread` 读出的 `code_length` 钉死；`jvm/jmap` 的 test 块钉住排序、`-`、未知 base 的 `?`，以及「类不同」
  「方法被展开」两种情形下行保留、pc 去掉。
- **负控**（`scripts/jvm-map/mutate.py` 登记、`run.py` 逐个建编译器验红，锚点归 `mutation-anchor-preflight.py`；
  `run.py` 跑 corpus、kernels、dead 三例）：
  1. `leak`：写出的 class 来自带标签的那一遍：`dead` 的 class 与不带 `--map` 时不同，「相同」红；
  2. `no-compare`：不比对就信带标签的类：`dead` 留下了 pc，「落地」红；
  3. `inv-early`：直接调用的指令标签打在实参之前：`ipc` 处是别的指令，「指令」红；
  4. `hi-is-lo`：结束标签就是开始标签：区间为空，`ipc` 在区间外，「边界」红；
  5. `absolute`：写源码位置时不加 base：「配对」红；
  6. `len-off`：`classread` 把 `code_length` 多读一：「方法」红；
  7. `no-widen-check`：不做展开检查：kernels 的 `main.trace` 留下旧 pc，「指令」「边界」红。
  实测七个全红，`run.py` 本机 202 s（`check.py --self-test` 与正控在前）。`leak` 的红顺带证明了 13.3 的推断：
  在 `dead` 上，带标签的那一遍确实写出了不同的字节。
- **接入**：push 预算余量为 0，挂 nightly 的 core-lint job，与 `scripts/core-sites`、`scripts/c-map`
  并列一步。本机 check.py 四例 45 s，run.py 202 s（负载 8 上下）。

### 13.6 给 M7：类 javap 列表从哪来

- **来源：JDK 的 `javap -c -p -s`，由读取方（M7 的建站脚本）对 `__emit -o` 目录跑，编译器不写列表。**
  列表是 class 字节的纯函数，编译器再写一份就是第二份真相；`javap` 每条指令前就是 pc，这正是本表的坐标，
  对齐不需要任何换算。`-p` 列出 `ACC_SYNTHETIC` 的提升 lambda，`-s` 给出 `descriptor:` 行，与 `symbol`
  里的描述符逐字比。M7 页面与 oracle 读的是同一份 javap 输出，所以 oracle 绿就是页面对得上。
- **为什么不是 ASM 的 Textifier**：它在 `asm-util` 里，selfhost 只 vendor `org.ow2.asm:asm`
  （`selfhost/dawn.toml:10`）；而且 Textifier 打的是 `L0`、`L1` 这样的标签而不是 pc，对齐还得再造一遍
  偏移。**为什么不在 Dawn 里写反汇编器**（扩展 `jvm/classread.dawn`）：要 200 来个操作码的长度表、
  `tableswitch`/`lookupswitch` 的对齐与 `wide`，换来的只是 javap 已经给的东西；本刀只给 `classread` 加读
  `code_length`（oracle 与单元测试要）。javap 的输出格式不是跨 JDK 版本的契约，但 pc 与
  `// Method owner.name:desc` 注释是稳定的，建站与 oracle 都在 `bin/dawn` 钉的 JDK 21 上跑。
- **对齐**：javap 的方法头 + `descriptor:` → `fn` 的 `symbol`；javap 每条指令的 pc → 落在哪些 `call` 的
  `[pclo, pchi)` 里，取最内层着色（CE 式按指令着色）；`ipc` 那一行加粗，即「这次调用本身」。
  源码一栏与 C 一栏的用法同 12.6。

### 13.7 开销

不带 `--map` 时：`GenCtx` 多一个布尔，`Gen` 多三个空列表字段（每次 `{..g}` 拷贝多三个指针），每个调用多一次
判假，`gen_cbody` 多一次判假。带 `--map` 时：每个模块多发射一遍，每个带 site 的调用两到三个 `Label` 与一条
记录，每个方法多一个 `end` 标签，最后读一遍模块类的方法表。按 12.7 的测法测 `__emit selfhost`（本分支的
selfhost 源码，同一份 std）：A = 真父 `5b4452f2` 的 jar，B = 本分支不带 `--map`，C = 本分支带 `--map`，
`-Xss512m -Xmx6g -XX:+UseSerialGC`，ABC 交错。本机负载 8 上下（别的写者在跑）。

| 量 | A 真父 | B 不带 `--map` | C 带 `--map` |
|---|---|---|---|
| 墙钟（中位数，7 次） | 8.01 s [7.31–9.82] | 7.46 s [7.11–9.44] | 8.78 s [8.09–9.51] |
| CPU user（中位数） | 29.99 s | 26.93 s | 32.12 s |
| 峰值 RSS（中位数） | 926 MB [902–954] | 888 MB [860–947] | 960 MB [930–967] |
| 分配量（JFR，5 次） | 8018 / 8363 / 8365 / 8369 / 8371 MB | 8355 / 8363 / 8364 / 8365 / 8372 MB | 10524 / 10949 / 10949 / 10954 / 10956 MB |

- 分配量与 12.7 同法：JFR 的 `jdk.ObjectAllocationInNewTLAB` 的 `tlabSize` 加 `jdk.ObjectAllocationOutsideTLAB`
  的 `allocationSize` 求和（两个事件默认不开，`-XX:StartFlightRecording=...,jdk.ObjectAllocationInNewTLAB#enabled=true,...`
  显式打开）。A 有一次落在低档（8018），其余四次与 B 的五次都在 8355–8372 之间，同档差在 ±0.1% 以内：
  不带 `--map` 测不出代价，与「多的只是判假」一致。墙钟 B 的中位数比 A 还低 7%，是负载噪声（极差都到 9.4 s
  以上），只说明没有可见的回归。
- 带 `--map`：分配多 2.6 GB（+31%），墙钟比 B 多 1.3 s（+18%），RSS +8%。整个 `__emit` 里发射只占一部分，
  第二遍发射几乎等于把这部分再做一遍，加上每个调用的标签与记录（selfhost 35855 行、7819 个方法）。
  这是按需工具，不设门限。

### 13.8 不做的（理由）

- **LineNumberTable、SourceFile、SourceDebugExtension（SMAP）**：裁决已否；只到行，进 class 改默认字节（13.4）。
- **一遍发射直接在输出上打 Label**：会改不可达代码所在类的字节，`--map` 不再是旁观者（13.4 第 4 条）。
- **包装 `MethodVisitor` 数字节**：Dawn 不能继承 Java 类；由编译器发射一个计数类会改所有程序的运行时。
- **编译器自己写反汇编列表**：列表是 class 字节的纯函数，第二份真相；javap 已经按 pc 列好（13.6）。
- **被展开的方法也给 pc**：要先读回 `goto_w` 展开后的类再重新定位每个 Label，等于自己实现一遍
  ASM 的重写；这类方法在编译器里不存在（最长 19783 字节），kernels 里有一个，如实记成未落地。
- **逐方法比对两遍字节**：一帧之差会挪后面方法的常量池下标，逐方法比会误伤；逐类比是能成立的最小单位。
- **闭包类、SAM 桥、字典类、入口包装进 `fn` 表**：没有书写调用，与 12.8 对适配器的处理相同。
- **`dawn build` 的 jar 也带侧表**：jar 里的类与 `__emit` 同一函数产出，M7 用 `__emit`；要了再加，读取方不变。
- **构造器、隐含调用进表**：Core 没有它们的 site（第四节），同 12.8。
