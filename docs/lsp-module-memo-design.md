# LSP 同步延迟刀 1：模块步骤按（输入，进入 carry）记忆

> 状态：**current**：2026-09-28 落地，分支 `feat/lsp-module-memo`：七个实现提交加本文档（提交以主题引用，合入后的哈希记在进度记录里）。
> 数据来源是 laziness L0 报告（`agent-handoff/laziness-l0-report-20260927.md`，基线 `b184de6e`）与本文第六节的实测。
> 上一篇是 [incremental-semantics-removal.md](incremental-semantics-removal.md)：拆掉体级重放之后，生产 LSP 只剩 legacy 前缀复用；本文把它换成一条规则。

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

> 若它的**输入**与上一轮相同，且它**进入时的 carry** 与上一轮相同，原样复用上一轮的步骤；否则重检。

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

definition 与 hover 看不到这个视图：definition 读目标模块的语法树（`lsp/lspq.dawn` 的 `module_ast_by_class`），服务端没有 references 请求。
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

- **L1（关闭文件只跑 header）**：L0 估它端到端只省 0.24 到 0.32 s，还会让关闭文件的体内诊断、未用导入与 comptime 诊断不再推送，改变 LSP 可见行为。
  本刀之后体内编辑只重检 1 个模块，关闭模块本来就全部复用，L1 能省的只剩「被编辑模块改了导出之后」那一段，届时再评。
- **按声明粒度只检被请求的体**：需要 S1/S2 的依赖图、SCC 与跳过体的执行器，是 laziness 的第二步；本刀之后最慢的是 `check/checker` 自身的 0.36 s，
  它才是按声明粒度的动机，但要先有「只检一个体」的正确性论证，不在本刀。
- **独立缓冲区的解析复用**：文本每次都变，没有可复用的东西；增量解析是另一件事。
- **给 `max_modules` 换成内存预算**：6.3 说明记忆不增加可测内存，上限只防病态工作区，128 足够。

## 九、契约与门禁的名字

规则不再是前缀，名字跟着改（提交「Name the module memo contracts after the rule they hold」）：`prefix.py` → `module-memo.py`、
`lsp-prefix.py` → `lsp-module-memo.py`、`contract/prefix` → `contract/module_memo`，job `incremental-prefix-1..3` → `incremental-memo-1..3`，
预算行照搬，`steps.lock.json` 按 `incremental-memo` 族重录，提交里按族写 `Gate-Retire(incremental-prefix)`。记录旧测量的注释保留当时的名字。
