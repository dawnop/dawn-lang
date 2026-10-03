# LSP 同步延迟刀 1：模块步骤按（输入，进入 carry）记忆

> 状态：**current**：2026-09-28 落地，分支 `feat/lsp-module-memo`：七个实现提交加本文档（提交以主题引用，合入后的哈希记在进度记录里）。
> 数据来源是 laziness L0 报告（`agent-handoff/laziness-l0-report-20260927.md`，基线 `b184de6e`）与本文第六节的实测。
> 上一篇是 [incremental-semantics-removal.md](incremental-semantics-removal.md)：拆掉体级重放之后，生产 LSP 只剩 legacy 前缀复用；本文把它换成一条规则。
> 刀 2（2026-09-30，分支 `feat/lsp-memo-by-imports`）：行起点跟着解析复用，复用条件从「进入时整条 carry 相同」收窄为「这一步读到的那部分 carry 相同」，见第十节。

## 一、问题

selfhost 工作区（打开 `main.dawn` 与另外四个文件，`main` 的闭包 76 个模块、4,425,669 字符）里，每次体内编辑的同步延迟
（didChange 到 barrier 回复）中位数是 1.5 到 1.95 s。L0 把它拆成两块：

1. **每次都重新解析全部 76 个文件**：load+parse 约 0.78 到 0.92 s，其中 parse 约 0.63 s，比整个温热检查（约 0.75 s）还大。
2. **前缀复用几乎不起作用**：`max_text_units = 1,048,576` 的字符预算在第 16 个模块（`check/checker`，61 万字符）处耗尽，之后任何编辑都重检 61 个模块；
   预算放开后，第 43 个模块起有 Java 查询，「Java 查询即停止保留」又截在那里。L0 称之为「阶梯」。

另外，L0 的早截断核查发现：`driver/analyze` 体内编辑后，`AnalysisCarry` 四个字段里只有 `decl_spans`（位置视图，预期会变）和 `exports` 变了，
而 `exports` 变的原因只是 `ModExports.aliases` 里 `AliasE` 带绝对源码位置，编辑点之后的 `pub alias AnalysisObserver` 平移了。

## 二、规则

`driver/incremental.analyze` 按拓扑序走模块。对每个模块：

> 若它的**输入**与上一轮相同，且它从进入时的 carry 里**读到的那部分**与上一轮相同，原样复用上一轮的步骤；否则重检。

（刀 1 的原文是「进入时的 carry 相同」；刀 2 按步骤实际读了什么收窄，读了什么、怎么判定、复用后的 carry 怎么拼，见第十节。本节其余部分是刀 1 的推导，2.2 的比较方式已由第十节的逐表跟踪取代。）

- 输入：整个 `LoadedModule`（文本、loader 改写后的 AST、路径、包、入口标记）按结构 `==` 比，外加按当前 `Env` 重算的 std 身份（`incremental.dawn` 的 `same_input` 与 `identity == e.std_identity`）。
- carry：`exports`、`impls`、`identities` 三个字段按结构比，**不比 `decl_spans`**。
- 世界（`StdCtx`、`CtOpts`、`Jsig`）由 owner 固定；lease、std、选项或 plan 任一变化，宿主重建 owner（`Session` 是 opaque，旧步骤接不进新世界）。

一个步骤是 `analyze_module_step(input, carry, world)` 的值，这个函数不读别的东西，所以这条规则就是步骤的定义域，不需要再加特例。

### 2.1 为什么一条规则够

它自然包含两件以前要分开说的事：

- **前缀复用**：编辑点之前的模块，输入相同，进入的 carry 也相同（前面什么都没变），于是复用。以前的「首差即停、绝不接回旧后缀」是这条规则在「编辑改变了导出」时的结论，而且只在那时成立。
- **早截断**（L0 的 L2）：被编辑模块输入变了，重检；若重检后的 carry 与上一轮相等，它之后的模块进入的 carry 就与上一轮相同，全部复用。
  Dawn 的非私有函数必须写返回类型（`front/parser.dawn` 的 `pub functions must declare a return type`），所以体内编辑不改变导出，这正是 rust-analyzer 的
  「函数体内的编辑不使全局派生数据失效」在模块粒度上的等价物。

### 2.2 比较怎么做才不贵

逐模块比整个 carry 不可行：`exports` 含全部 std 与项目模块的导出面，`identities` 在 `main` 处有 4,850 项，76 个模块各比一次是平方量级。实现只在一处做结构比较：

- carry 只增不减（`exports` 按模块路径插入、`impls` 与 `identities` 只加），所以一旦本轮的 carry 与上一轮在某处不同，之后每个模块进入的 carry 都不同。
- 于是用一个变量 `carry_is` 记「本轮当前的 carry 就是上一轮在哪个模块之后的那个 carry，逐对象相同」（`Some(None)` 是 owner 的基线）。每条记忆 `Entry` 记下它进入时的前驱 `pred`。
  「进入的 carry 相同」判为 `carry_is == Some(e.pred)`，不做任何比较（`incremental.dawn` 的 `reusable`）。
- 复用的模块把 `carry_is` 推进到自己；重检的模块只在「进入时 carry 相同」的前提下，拿新的 after-carry 与上一轮它自己的 after-carry 比一次（`same_after`）。
  相等就**换回上一轮的对象**（`cutoff` 分支），后续模块又能按对象同一性判定；不等就置 `None`，本轮不再比较。

所以一次编辑的比较代价是「被编辑模块一次 O(carry 大小)」，其余模块 O(1)。

### 2.3 导出面的比较要看顺序

`Map` 的 `==` 按项比、不看插入顺序（`std/map.dawn` 的 `Eq[Map]`）。carry 自己的三张表只按键查（检查器里没有遍历 `identities` 或 `impl_table` 的地方，
遍历 impl 表的只有冷路径的代码生成），顺序不是输入，所以 `same_after` 对它们只用 `==`。导出面不同：导入方会遍历它的表，
例如「did you mean」提示从 `fns` 等表按顺序建候选池，两个同样近的名字取先出现的那个；ADT、trait、效果的 id 表按这个顺序嫁接进导入方自己的表。
所以被重检模块自己的导出面在 `==` 之外还比各个表的键序（`same_surface`）。`contract/module_memo` 的「module memo compares what a module exports in order」守它：
交换两个 `pub fn`、交换两行 `use`，下游都必须重检；`module-memo.py` 的 `unordered-surface` 变异体（只比 `==`）让它红。
第一版也给 carry 的三张表加了键序比较，它的变异体 `unordered-carry`（去掉那层键序）在本机 sweep 里存活，没有任何用例能区分，与上面「只按键查」的读法一致，于是删掉了。

## 三、为什么删掉两条旧规则

### 3.1 字符预算 `max_text_units`

它的理由是内存。但被复用的步骤与 `Program` 持有的 `CheckedMod` 是同一份不可变数据：会话多留的只是每个模块之后的 carry 快照，
而 carry 是持久化 Map，相邻快照绝大部分结构共享。实测（第六节 6.3）：selfhost 工作区编辑 20 轮、强制一次 full GC 之后，存活堆基线 236.7 MB、本刀 228.7 MB，
RSS 基线 1,169 MB、本刀 1,007 MB。记住全部 76 个模块的步骤没有可测的内存代价，字符预算只剩下「让复用在第 16 个模块停下」这一个效果。
`max_modules`（默认 128）留作唯一的安全上限；`LspAnalysisConfig` 去掉 `max_text_units`，`incremental.Stats` 去掉 `retained_text_units`。

### 3.2 「Java 查询即停止保留」

它的理由是 Java 签名预言机的答案可能变。但 owner 与 lease 同生同灭：`LspLeaseHost.project` 每个工作区给一个 lease，lease 固定 classpath，
工作区在 plan 或 lease 变化时整个重建 owner（`lsp/server.dawn` 的 `activate_workspace`）。会话内预言机是固定的，查过 Java 的模块与没查过的一样是输入的函数。
这条规则一走，查询计数就不再决定任何事：`incremental.new` 与 `LspLeaseHost` 去掉 `probe`，`JsigProbe`、`observe_queries`、`refused_probe`、
`query_probe` 连同 `contract/probe`、`probe.py` 与冷基准里的 `java_queries` 一列整个删掉（提交「Delete the Java query probe」，删 299 行）。

### 3.3 同时去掉的两条

旧实现还有两条保守规则，同样不在新规则里：「模块有诊断即停止保留」与「loader 有诊断即整轮冷检」。诊断是步骤的**输出**，不是输入；
loader 诊断不是任何一个步骤的输入。步骤里诊断的位置按声明相对记录（`front/token.dawn` 的 `Diag` 注释），渲染时才查位置视图，所以复用带诊断的步骤不会带出旧位置（见第四节）。
`contract/module_memo` 的「module memo reuses modules with diagnostics and bounds what it keeps」逐项对照冷分析。

## 四、`decl_spans` 必须重拼

`decl_spans` 是「每个模块的每个声明现在在哪」。它在 carry 上，因为读它的不是产生它的那一步，而是之后渲染诊断的人（`driver/analyze.dawn` 的 `rendered_diags`）。
复用步骤时如果直接拿上一轮的 `after`，它里面的 `decl_spans` 是上一轮的：被编辑的模块若在它前面并且移动了，渲染出来的位置就是旧的。

所以每个模块之后都重拼：`carry.decl_spans` = 本轮走到这里的视图，插入该模块自己的那一项（取自它的步骤，文本相同所以就是现在的位置；`incremental.dawn` 的 `own`）。
存进记忆的步骤也换成重拼后的 carry，下一轮复用时读到的自己那一项仍然正确。

守它的判据：

- `contract/module_memo` 的「module memo places a reused module's diagnostics and its predecessors' where they are now」：上游模块前插三行、体内有错，下游复用；
  `rendered_diags` 与冷分析相同。`module-memo.py` 的 `stale-spans` 变异体（拼接时用步骤自己的视图代替本轮的）必须让它红。
- `lsp-project-matrix.py` 的 `provider-move-error` 修订：LSP 发布的上游诊断必须落在当前文本里 `missing_value` 所在的行。
  去掉重拼的服务端在这一步报 `provider diagnostic on line 4, text puts it on 5`。

definition 与 hover 看不到这个视图：definition 读目标模块的语法树（`lsp/lspq.dawn` 的 `holder_by_class`，原名 `module_ast_by_class`），服务端没有 references 请求。
所以 LSP 侧唯一的读者是诊断渲染，判据落在诊断上；definition 的位置同样逐修订按当前文本检查，作为「从下游跳到被编辑模块」的正向断言。

## 五、前置小刀：导出面与 carry 不带源码位置

`AliasE.target` 是声明模块里未解析的类型语法（带绝对位置），`nlo`/`nhi` 是名字的位置。两个改法：位置改成相对声明，或导出面不带位置。选后者：

- 导入方从不读 `target`：`bind_import` 导入时就把它换成 `None`（`check/passes.dawn`），限定名 `lib.Pair` 读的是 `alias_resolved`。
- 导入方读 `nlo`/`nhi` 的唯一地方是 `pass_resolve_aliases` 进入声明时给身份撞车诊断定位，而那个位置指向另一个文件，在导入方的文件里本来就没有意义。
- 关于 alias 本身的诊断都在声明模块里、从声明模块自己的表发出，位置不变。

相对位置能让比较相等，但会把「导出面携带源码坐标」这件事留下来，下一个读者还得知道它是相对谁的；导出面本来就不该有坐标。
实现是 `check/checker.dawn` 的 `exported_alias`（`target` 置空、`nlo`/`nhi` 置零），`exports_of` 只导出它。冷输出不变：诊断文案与位置逐字节相同（第七节）。

`ImplI` 是同一类问题：它带 `impl` 或 `derive` 的绝对位置 `lo`/`hi`，并且进 carry 的程序级 impl 表与 `ModExports.impls`，
所以在某个 `impl`/`derive` 之前插一行，carry 就不等，其后模块全部重检。处理同 alias：读 `lo`/`hi` 的只有声明模块自己遍历 `cx.local_impls` 的三处
（公开面检查、`impl_at_span`、`impl_method_trait`），导入方按键找 impl、重复 impl 诊断报的是 `src_path`，从不读别人的位置。
`exported_impl` 在 `exports_of` 与 `analyze_module_step` 的 carry 折叠里把位置置零，声明模块自己的 `local_impls` 不动（提交「Carry and export impls without source positions」）。
观测：tea-core 工作区打开 `tree`、`diff`、`walk`（`tree` 有 `derive Show`，被另两个导入），在 `tree` 前插一行，修前 reused 0 / checked 3，修后 2 / 1。
`contract/module_memo` 的「module memo keeps an importer's step across an edit above an impl or a derive」与 `module-memo.py` 的 `impl-positions` 变异体守它。

## 六、实测

本机 16 核 15 GB，WSL2，GraalVM CE 21.0.2，服务端 `-Xss512m -Xmx2g -XX:+UseSerialGC`，测量期间机器空载（load avg 1.3 到 2.1）。
服务端由 `lsp-configured.py --mode Legacy` 构建（带 `LSP_BODY_STATS` 观察）；基线从 `b184de6e` 的源码快照构建。编辑的工作区是同一份 `b184de6e` 源码快照，两边相同。
方法同 L0 的 `lsp_edit.py`：打开 `main` 与 `front/ast`、`check/checker`、`driver/analyze`、`jvm/emit`、`main` 五个被编辑文件，每轮在每个文件某函数体顶部插一行 `let`，
文件顺序每轮轮转，预热 3 轮、测 7 轮，基线与本分支交错两遍，每格 n = 7。

### 6.1 解析复用（提交「Reuse unchanged parses across LSP workspace loads」）

| 编辑文件 | 基线 sync 中位数（两遍） | 解析复用 sync 中位数（两遍） | min（解析复用） |
|---|---|---|---|
| front/ast | 2,156 / 2,201 ms | 948 / 903 ms | 887 / 890 ms |
| check/checker | 1,588 / 2,997 ms | 1,106 / 980 ms | 898 / 929 ms |
| driver/analyze | 1,881 / 2,293 ms | 777 / 805 ms | 745 / 754 ms |
| jvm/emit | 1,517 / 2,256 ms | 816 / 769 ms | 744 / 727 ms |
| main | 1,534 / 1,597 ms | 781 / 774 ms | 729 / 728 ms |

重检模块数不变（61 或 76），差别全在解析：比 L0 估的 0.6 s 多，因为旧会话还要对新解析出来的树做逐节点的 `LoadedModule` 比较，共享同一棵树后按对象同一性立即返回。

### 6.2 模块记忆（提交「Reuse a module's step when its input and entering carry are unchanged」）

| 编辑文件 | 基线 sync 中位数（两遍） | 本刀 sync 中位数（两遍） | 本刀 min | 重检模块（基线 → 本刀） |
|---|---|---|---|---|
| front/ast | 1,722 / 1,965 ms | 49 / 50 ms | 36 / 32 ms | 76 → 1 |
| check/checker | 1,982 / 1,920 ms | 386 / 359 ms | 317 / 322 ms | 61 → 1 |
| driver/analyze | 1,656 / 1,598 ms | 89 / 79 ms | 66 / 60 ms | 61 → 1 |
| jvm/emit | 1,711 / 1,859 ms | 128 / 103 ms | 111 / 97 ms | 61 → 1 |
| main | 1,823 / 1,451 ms | 101 / 99 ms | 92 / 82 ms | 61 → 1 |

`LSP_BODY_STATS` 每格 7 个样本完全一致：本刀 `reused=[75] checked=[1] retained=[76]`，基线 `reused=[15] checked=[61] retained=[15]`（front/ast 为 `reused=[0] checked=[76]`）。
剩下的时间主要是被编辑模块自己的检查：`check/checker` 是全仓最大的模块（61 万字符、453 个体，L0 测得模块区间约 108 ms），加上 load（不含解析）与诊断渲染发布。
首次打开（冷 JVM、std、六次 didOpen 各触发一次重建）基线 12.7 / 13.4 s，本刀 8.0 / 7.6 s。

### 6.3 内存

同样的编辑做 20 轮（100 次编辑），结束时读 `/proc/<pid>/status`，再 `jcmd GC.run` 后读 `GC.heap_info` 的老年代已用：

| 服务端 | VmRSS | VmHWM | full GC 后老年代已用 |
|---|---|---|---|
| 基线 | 1,169,008 kB | 1,219,464 kB | 236,737 kB |
| 解析复用 | 1,089,464 kB | 1,156,384 kB | 235,656 kB |
| 本刀 | 1,007,280 kB | 1,078,900 kB | 228,669 kB |

交错的四次测量里 full GC 后已用在 223 到 233 MB 之间，两边没有可分辨的差别。RSS 是整个进程（含 JIT 与未归还的堆），不是缓存的字节数；这里只能说记住全部步骤没有让它变大。

### 6.4 独立缓冲区

`lsp-bench.py --uri untitled:bench2001`（2,000 个函数加 `main`，11 轮，预热 3 轮，交错两遍）：sync 中位数基线 87.2 / 88.3 ms，本刀 84.3 / 95.9 ms；hover 7.7 到 8.9 ms、completion 56 到 63 ms。
独立缓冲区每次编辑文本都变，只有一个模块，解析复用与模块记忆都用不上，所以不变；这与预期一致，不是「解析复用应可见」。

## 七、冷输出与等价性

- 冷路径（`dawn check`/`build`）不经过 `driver/incremental` 与 `load_entries_reusing`，唯一被冷路径看到的改动是导出面的 alias 位置。
  checker-corpus、四个差分、fixpoint 的结果见报告（`agent-handoff/lsp-module-memo-report-20260927.md`）。
- LSP A/B：`b184de6e` 的服务端（不带观察）对本分支服务端，`lsp-project-matrix.py`（十个修订）与 `lsp-edit-matrix.py --functions 1000`（十个修订）的全部诊断与
  hover/definition/completion 回复逐字相同；本分支带 `--expect-counts`，每次只改上游实现或位置的修订都是「上游重检、下游复用」。
- `contract/module_memo` 的八条测试把每个结果与同一输入的冷分析逐项比较：checkdump、诊断、`decl_spans`（含键序）、渲染后的诊断。

## 八、不做的（理由）

- **L1（关闭文件只跑 header）**：2026-09-30 复评（`agent-handoff/research-laziness-l1-reeval-20260930.md`）。体内编辑只重检 1 个模块，L1 收益为 0；
  上游 `pub` 签名改动时 `check/types` 之后 75 个模块全部重检，L1 实测省约 0.43 s（sync 1.04 → 0.61 s）。但其中约 0.18 s 是每次重算的 `line_starts_of`，
  约 0.24 s 是不导入被改模块却因 carry 是一条线而重检的模块，两者都能在不改变诊断的前提下拿回（第十节，同批实测两刀合计 773 → 518 ms）；
  L1 还会让这个场景里最有用的诊断（关闭的调用者被改坏）消失，而 Dawn 没有 rust-analyzer 的 flycheck 或 Roslyn 的全解决方案分析那样的全量旁路。
  所以先做行起点记忆与按导入键控的复用，L1 只在「关闭的导入者的体与 comptime」仍超过约 0.15 s 且有用户诉求时，以默认关的开关、配保存或空闲时补跑关闭模块的旁路再评。
- **按声明粒度只检被请求的体（L2）**：产物侧（`TFun.decl`、相对位置）已就绪；输入侧缺体间 `Cx` 的独立性与跨模块读集合（今天的读集合是模块粒度的，第十节），
  体级复用已于 09-27 因证明成本高于重算被拆除（[incremental-semantics-removal.md](incremental-semantics-removal.md)）。
- **独立缓冲区的解析复用**：文本每次都变，没有可复用的东西；增量解析是另一件事。
- **给 `max_modules` 换成内存预算**：6.3 说明记忆不增加可测内存，上限只防病态工作区，128 足够。

## 九、契约与门禁的名字

规则不再是前缀，名字跟着改（提交「Name the module memo contracts after the rule they hold」）：`prefix.py` → `module-memo.py`、
`lsp-prefix.py` → `lsp-module-memo.py`、`contract/prefix` → `contract/module_memo`，job `incremental-prefix-1..3` → `incremental-memo-1..3`，
预算行照搬，`steps.lock.json` 按 `incremental-memo` 族重录，提交里按族写 `Gate-Retire(incremental-prefix)`。记录旧测量的注释保留当时的名字。

## 十、刀 2：行起点记忆与按导入键控的复用（2026-09-30）

数据与动机来自 L1 再评报告（`agent-handoff/research-laziness-l1-reeval-20260930.md` §一）：selfhost 工作区里改 `check/types` 一个 `pub fn` 的签名（场景 (b)），
刀 1 的规则让它之后的 75 个模块全部重检，而其中只有 29 个导入它；75 次重检里 `lexer.line_starts_of` 一项共约 179 ms，而这些文件的文本都没变。
两刀都不改变任何 LSP 可见的输出。

### 10.1 行起点跟着解析走

`LoadedModule` 多一个字段 `line_starts`，由 loader 从解析得来：`ParseMemo` 里的 `Parsed` 带着它，文本相同的文件连同解析一起复用（`driver/analyze.dawn` 的 `fresh_parse`、`parse_reusing`）。
`analyze_module_step` 不再自己算。冷路径是同一个函数在 load 时算一次，值相同；它唯一的读者是 `expr!` 的 `at file:line`（`check/tast_positions.dawn` 的 `site`）。
`incremental.same_input` 比较 `LoadedModule` 时不再逐项比 `line_starts`（它是文本的函数，文本已经比了）：第一版逐项比，(a) 体内编辑的 sync 中位数比同批基线高约 11 ms（69 对 80，交错 4 遍）；改后高约 5 ms（72 对 77），在噪声内。

判据：`driver/analyze`「a reusing load parses only the files whose text changed」（复用加载与冷加载的 `LoadedModule` 相等，行起点在内）；
`contract/module_memo`「module memo checks an unchanged file again with the line starts its reused parse holds」：经真实 loader，文本未变、因导入变了而重检的模块，comptime 报告里仍是 `app.dawn:5`，文本上移三行后是 `app.dawn:8`，并逐项对冷。
变异体 `stale-line-starts`（`lsp-module-memo.py`：未命中时沿用旧解析的行起点）让这两条都红。

### 10.2 一个步骤读 carry 的哪些部分

`analyze_module_step(input, before, world)` 读 `before` 的四个字段，读法各不相同：

| 字段 | 谁读、怎么读 | 复用条件 |
|---|---|---|
| `exports` | 只有 `check_module_headers` → `pass_imports`，按每行 `use` 的路径 `map.get`；唯一的例外是 std 路径找不到时，诊断列出表里全部 `std/` 键 | 每行 `use` 找到的面不变；有找不到的 std 路径时另比 `std/` 键列表 |
| `impls` | 整张表是 `impl_table` 的起点：impl 在全程序生效，不由 `use` 打开 | 行相同 |
| `identities` | intern 表的起点，只在 `cx.interned` 里判定撞车；步骤之后的表 = 进入的表 ∪ 本模块自己的声明行 | 见 10.4 |
| `decl_spans` | 不读，只插入自己那一项 | 无（照旧每模块重拼，第四节） |

**「re-export 可达」由导出面自己承担。** Dawn 没有 re-export 语句；间接可达的类型信息是这样流动的：`exports_of` 把模块从自己的导入嫁接来的整张 ADT、trait、效果表放进导出面
（`adt_infos: cx.adts` 等，注释是「extra entries graft harmlessly」）。所以 `use a` 的模块读到的 `b` 的类型，就在 `a` 的导出面里；`b` 的类型一变，`a` 重检，`a` 的导出面（嫁接的那几张表）不等，
`a` 的导入者随之重检。读集合因此只需直接 `use` 的路径，不必展开闭包；代价落在 `same_surface` 必须比较整个导出面（含嫁接表），不能只比模块自己的名字表。
`contract/module_memo`「module memo checks an importer again when a surface changes only in what it imported」守它：`b` 改字段名，`a` 的签名不变，只 `use a` 的 `d` 必须重检并报出与冷检相同的错。
变异体 `reexport-blind`（`same_surface` 不看三张嫁接表）让它红。

### 10.3 判定怎么做才不贵

`Map` 的 `==` 先把一侧的行列出并排序，没有对象同一的捷径（本机实测：两万行的表自比一次约 4.6 ms，记录套着表也一样），所以逐模块逐导入做结构比较不可行。实现只在「被重检的模块」处比较，其余靠记账：

- **导出面**：每条 `Entry` 记它每行 `use` 在哪里找到了面（`NotFound`、`InBaseline`、`InStep`）。本轮维护两个集合：`seen`（本轮已放进 carry 的模块）与 `fresh`（其中本轮重检、且导出面与上一轮它自己的不等的模块）。
  `InStep` 的面不变 ⟺ 该模块本轮已在 `seen` 里且不在 `fresh` 里；`InBaseline` ⟺ 不在 `seen` 里且表里有；`NotFound` ⟺ 表里没有（`reads_hold`，不做任何比较）。
  归纳：一个模块本轮若被复用，放进 carry 的就是上一轮它自己的面对象；若被重检且 `same_surface` 相等，也换回上一轮的对象；否则进 `fresh`。上一轮步骤记下的 `InStep` 读到的正是上一轮该模块的面（记录时它在前面；复用时条件成立），所以「不在 `fresh`」就是「与它读到的相同」。
- **impl 表**：`impls_is` 记当前表是否就是上一轮某模块之后的那个对象（刀 1 的 `carry_is` 拆出来的一张），是则免比；否则 `same_rows` 比一次行（按 trie 顺序遍历，不排序）。
  重检的模块在进入时同步、且新表与上一轮的行相同时换回旧对象，后面的模块继续免比。
- **intern 表**：`ids_is` 同理；不同步时走 10.4 的合并。

比较代价：每个被重检模块一次 `same_surface`，同步时各一次 `same_rows`；复用的模块 O(读的 `use` 行数)。

### 10.4 identities：只影响撞车诊断

裁决要求 identities 不再参与复用判定。论证：

1. `cx.interned` 是唯一读 `identities` 的地方（`check/cx.dawn`），它只做两件事：表里没有这个 id 就插入；有且是别的声明就报撞车诊断、不改表。返回的 id 是 `identity.derive(decl)`，与表无关。所以表只影响**诊断**和**之后的表**。
2. 一个模块只 intern 它自己的声明：`mint` 与 `enter_decl_owner` 都以 `cx.owner_class` 为 owner。所以步骤新增的行（`minted_by`）都属于它自己，别的步骤不会产生这些行。
3. 于是，若当前表不是它上一轮进入时的那张：只要它上一轮**没有诊断**（没有撞车），且它新增的行在当前表里一行也不在，冷检就会无撞车地插入同样的行，诊断相同，之后的表 = 当前表 ∪ 这些行。
   这正是复用时做的（`kept` 的合并分支）；复用步骤的 `CheckedMod.cx.identities` 也换成这张表，与冷检逐项相同。
4. 有诊断的步骤在表变了时重检：它的某条诊断可能是撞车，而撞车的另一方可能已不在当前表里。「撞车诊断在复用步骤的诊断里已经带着」只在表相同时成立，表变了就不一定，这里是裁决原话需要补的一个条件。
   新行已被占（上游新加了一个撞车的声明）同样重检。两种情况在 selfhost 上都不发生（全仓无诊断、无撞车），不影响 (b) 的收益。

撞车以前被认为写不出测试（`check/cx.dawn` 的测试注释「the real thing is not reachable by writing a test module」）。这次用一个 C 程序在 2^25 × 2^26 个函数名里找 47 位碰撞，
约 28 s 找到三对，其中 `p.a20228599` 与 `q.b9013596` 用在 `contract/module_memo`「module memo reports a digest collision with a module it does not import as the cold path does」：
测试先断言两个 id 相等（哈希若变，测试会指出），再覆盖三种情况：上游表变、`p` 复用、`q` 重检仍撞到 `p` 的行（变异体 `drop-identities`：复用不合并新行）；
上游新加撞车声明、不导入它的 `q` 必须重检报出撞车（`skip-collision`：不查新行是否被占）；撞车声明删掉、`q` 必须重检、诊断消失（`keep-diagnosed`：有诊断也复用）。三者都逐项对冷。

### 10.5 复用后的 carry

复用步骤 `e` 之后：`exports` 插入上一轮它自己的面对象；`impls` 取 `e` 之后的那张（条件保证行相同）；`identities` 同步时取 `e` 之后的那张，否则取 10.4 的合并表；
`decl_spans` 照第四节重拼。合并按步骤原来 intern 的顺序插入（`minted_by` 取 `map.entries` 的插入序），不是按 trie 顺序：表不只是它的行，还带插入序号，
按同样顺序插进同一张表才得到冷检那张表本身。第一版按 trie 顺序合并，`checkdump` 与诊断都看不出来，是 `module-memo.py` 的全产品冷参照（`SemanticSnapshot` 逐字段比较）在 `Cx.identities` 的 `NLeaf.seq` 上红出来的。
impl 表在不同步、行相同时取上一轮的对象，与冷检行相同、插入历史可能不同；它只按键查（2.3），LSP 侧没有读者，全产品冷参照在它的样本上相同。上一轮到这一轮，`Entry` 的 `reads` 与 `std_names` 原样沿用（条件成立即仍然正确），`impls_in`、`ids_in`、`pred` 换成本轮进入时的，`minted` 缓存算过一次的新增行。

### 10.6 实测

方法同 L1 再评报告 §一（`lsp_l1.py`，工作区是 `09851075` 的干净快照，打开 `main` 与 `front/ast`、`check/checker`、`check/types`、`driver/analyze`、`jvm/emit`；
每轮三次编辑：(a) `driver/analyze` 体内、(b) `check/types` 的 `pub fn eff_suffix` 在加减一个带默认值的参数之间切换、(c) 第 0 个模块 `front/ast` 体内；预热 3 轮、测 7 轮）。
基线、刀 2 的 M1、M1+M2 三个服务端交错 4 遍（每遍顺序轮换），每格 n = 28，服务端 `-Xss512m -Xmx2g -XX:+UseSerialGC`，测量期间 load avg 1.9 到 2.5。

| 编辑 | 基线 sync 中位数 / min | M1 | M1+M2 | 重检模块（基线 → M1+M2） |
|---|---|---|---|---|
| (a) 体内 | 72 / 48 ms | 77 / 48 ms | 69 / 47 ms | 1 → 1 |
| (b) `check/types` pub 签名 | 773 / 705 ms | 647 / 579 ms | **518 / 490 ms** | 75 → 30（复用 1 → 46） |
| (c) 第 0 模块体内 | 28 / 25 ms | 30 / 27 ms | 32 / 25 ms | 1 → 1 |
| 首次打开（六次 didOpen，四遍） | 5.7 到 6.0 s | 5.4 到 5.7 s | 3.8 到 4.1 s | |

四遍各自的中位数：(b) 基线 778 / 905 / 765 / 747，M1 925 / 620 / 634 / 639，M1+M2 518 / 512 / 531 / 509。
M1 在 (b) 上省约 126 ms（验收线 120）；M2 再省约 129 ms，**未达到验收线 150 ms**：再评报告估的「非导入者的模块区间约 235 ms」里含这些模块各自的 `line_starts_of`（约 46/75 × 179 ≈ 110 ms），这部分已被 M1 拿走。两项估计（179 ms 与 235 ms）重叠约 110 ms，去重后约 300 ms；实测两刀合计省 255 ms（773 → 518）。
重检数 30 = `check/types` 自己 + 工作区里 29 个导入者。首次打开变快是同一件事：六次 didOpen 各一次重建，后几次只重检真正受影响的模块。

LSP A/B（`09851075` 不带观察的服务端对本刀带观察的服务端）：`lsp-project-matrix.py --expect-counts --compare` 十个修订、`lsp-edit-matrix.py --functions 1000 --compare` 十个修订，全部回复与诊断逐字相同，刀 1 的 `provider-move-error` 位置判据仍过。


### 10.7 本刀不做的（理由）

- **读集合展开成 `use` 闭包**：导出面自带嫁接表（10.2），展开闭包只会让一个上游的无关改动多使一批模块重检。
- **identities 仍按相等比较**：(b) 的签名改动加了一个默认参数，驻留一条 `ParameterDefault` 路径，表就不等；按相等比较会让 `check/types` 之后的模块照旧全部重检，M2 的收益归零。10.4 的两个附加条件代价为零且保持冷检一致。
- **把 impl 表也按读集合键控**：impl 在全程序生效（孤儿规则只限制写在哪里，不限制谁用），`contract/module_memo`「module memo checks a module again when the impl table changes, whatever it imports」就是不导入 `p` 却用 `p` 的 impl 的例子。
- **体级或声明级复用、关闭文件跳过体**：见第八节。

## 十一、comptime 的跨模块读（#416，2026-10-03）

#416 让 comptime 兑现 spec §7.2 第 1 条：`const Q: Int = nums.doubled(21)` 可以调前面模块的函数。`AnalysisCarry` 因此多了第五个字段 `ct_world`（`ir/interp.CtWorld`）：
前面每个干净模块（`cx.diags` 为空、跑过 comptime 的）的直接函数、impl 方法与 trait 默认体、符号表、常量作用域与折叠值，外加 std 的常量作用域与值（`StdCtx.ct_world`）。

**它不能按 `use` 键控。** a 的 const 调 `b.via`，`b.via` 调 `c.plus`，a 只 `use b`；c 的体内编辑不改变任何导出面。所以 10.2 的「每行 `use` 找到的面不变」管不住它。
解释器在运行时记下自己读了哪些别的模块（`lower_into` 下降了谁的体、`CConstRef` 从谁那里取了值），放进 `CtOut.reads`（模块路径集合）；某次跨模块查找落空则置 `CtOut.missed`。复用条件加一条（`comptime_reads_hold`）：

- `reads` 里的每个路径：本轮已放进 carry 的，必须是本轮**复用**的步骤（重检过的模块即使导出面相同，体或常量值也可能变了，按变了算）；不在本轮的，必须是 std（基线 `ct_world` 里有）。
- `missed` 为真的步骤一律重检：它的结果取决于它叫不出名字的模块。落空必然伴随一条 comptime 诊断，这种步骤本来就少。

复用时 `ct_world` 由 `analyze.world_after` 用步骤自己的 `CheckedMod` 重拼，与冷路径同一个函数。

**取舍**：重检过但体没变的模块也让读过它的步骤重检。替代方案是重检后比较 `TModule` 与常量表，可以省掉「上游导出面变了、它被迫重检、体其实没变」这一类，但比较本身要走整棵类型树。被读的模块通常就是正在编辑的那个，这一类不常见，所以先不比较。

**常量按被调方的模块解析。** 别的模块的体里，裸名 `BASE` 指那个模块自己的常量或它选择性导入的常量，不是正在折叠的模块的。解释器记着「当前在跑谁的体」（`ICx.body`，`call_cfun` 跨模块时切换），
按与 `cdriver.merged_consts` 相同的规则逐次查找。以前的 `CConstRef` 只按简单名查折叠模块自己的表：跨模块调用打通后，同名常量会静默折出错误的值，而不是报错。顺带地，`m.MAX` 这种限定常量在 comptime 里也能用了（以前报 `failed to evaluate`）。

**键的选择**：函数体按 owner（类名，Core 的 `CDirect(owner, name)` 带的就是它）进 `by_owner`，不进扁平的 `fns`。扁平表是 std 预导入名的后备，两个模块各有一个 `helper` 时按名合并会互相覆盖；
跨模块调用到 Core 时总是带 owner 的，用不着它。常量按模块路径（`CConstRef` 与 `imported_names` 带的是路径）；包模块的类名（`dawn$pkg$...`）与路径不同，`CtWorld.scopes` 记着两者的对应。

测试：`driver/analyze`「comptime calls the functions of the modules before it」（两层链、impl 与默认体、限定常量、path dep 包含 lambda、被调方的重命名导入与同名常量、comptime 块）、
「comptime still refuses another module's effectful function」；`contract/module_memo`「module memo folds a const again when a module its comptime reached changes」（c 的体、c 的常量、b 的体各改一次，a 重检、z 复用，逐项对冷）。
