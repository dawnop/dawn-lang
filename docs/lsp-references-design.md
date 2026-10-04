# LSP 引用与改名：T0 解析覆盖

> 状态：**current**：T0 于 2026-10-04 落地，分支 `feat/lsp-resolution-coverage`（提交以主题引用，合入后的哈希记在进度记录里）；
> T1（semantic tokens 服务端，§T1）同日落地，分支 `feat/lsp-semantic-tokens`；T2（VS Code 与 Playground 两个消费端，§T2）同日，分支 `feat/lsp-semantic-tokens-clients`；
> R1（单文件 references 与 documentHighlight，§R1）同日落地，分支 `feat/lsp-references-local`；
> R2（工作区 references，§R2）同日落地，分支 `feat/lsp-references-workspace`；R3（prepareRename 与 rename，§R3）同日落地，分支 `feat/lsp-rename`。
> 依据：裁决 `agent-handoff/ruling-lsp-tokens-rename-20261003.md`，调研 `agent-handoff/research-lsp-tokens-rename-report-20261003.md`
> （§1.4 空洞实测表、§2、§3.4、§5.1 刀序）。前六节写 T0，§T1 写 T1，§T2 写 T2，§R1 写 R1，§R2 写 R2，§R3 写 R3。

## 一、为什么 T0 在最前

references 与 rename 的数据源都是 `lsp/lspq.dawn` 的并行遍历：语法树与类型化树一起走，每个节点 `offer` 一个（跨度，悬停，定义位置）。
遍历没有臂的语法位置，definition 回空，hover 退回外层表达式的类型。在这样的遍历上建引用索引，rename 必然漏改：
调研实测 `apply(helper.double, 4)` 的 definition 为空，改名 `double` 会把程序改到编不过。所以 T0 是 R 线的硬前置（裁决第 2 条）。

## 二、§1.4 表按今天的 main 重测

基线 `7a75caa8`（管道刀 #434 已合）。探针是调研的两份程序（`probe.py` 单文件、`probe2.py` 两模块），本机起真 `dawn lsp` 逐位置问 hover 与 definition。

| 语法位置 | 调研时（`eaadaf77`） | 今天的 main | T0 之后 |
|---|---|---|---|
| 限定函数值 `apply(helper.double, 4)`、`5 \|> helper.double` | 无 definition | **已有**（#434 补了 `EFieldAcc` 的 `XFnValue`/`XCallFn` 臂） | 有，夹具守住 |
| 操作调用 `lookup0(name)` | hover 有，无 definition | 同左 | 有：`site_of_sig` 认 `Sig.op_of`，跳到效果里的操作声明 |
| 限定操作调用 `helper.ask()` | hover 只有类型 | 同左 | 有：经别名的 `module_fn_sigs` 取签名 |
| 效果行 `!Env0`、`!helper.Ask` | 无 | 无 | 有 |
| `with handle Env0` / `handle helper.Ask` 的效果名 | 外层类型 | 同左 | 有 |
| handler 臂的操作名 `lookup0(n) =>` | 外层类型 | 同左 | 有，hover 是操作签名 |
| 书写类型 `e: Expr0`、`s: Shape` | 无 | 无 | 有 |
| 改名导入的 UFCS `7.twice()` | 只有类型 | 同左 | 有 |
| 限定访问里的模块别名段 `helper.`、`str.` | 外层类型 | 同左 | 有，跳到模块文件开头，hover 与 `use` 行相同 |
| 记录字面量字段名 `Point0 { x: first }` | 外层类型 | 同左 | 有，跳到字段声明 |
| 具名实参名 `dy: 5` | 外层类型 | 同左 | 有，跳到形参声明 |
| `var acc` 声明处 | 只有类型 | 同左 | 有（`let` 声明处一并补上） |

除第一行外，表里调研列出的空洞在今天的 main 上都还在。夹具另外覆盖了表外、同一类的位置：
函数类型参数里的效果行（`f: fn(Int) -> Int !Env`）、局部 `fn` 的效果行、类型参数（使用处与声明处）、trait bound、
`alias`、限定类型 `helper.Shape`、记录模式的字段名 `Point { x: first, y, label }`、构造器的具名实参 `Num(v: 3)`、
限定构造器模式与限定类型、效果行里的别名段。

## 三、怎么补

### 3.1 书写类型：只读解析

`check/cx.dawn` 的 `resolve_type` 带 `!io`、写诊断、记 `ty_spans`，不能从 LSP 调。`lspq` 照它的顺序另写一个只读版：
硬保留内建（只在返回位置 hover，与以前一样）→ 类型参数 → `alias`/`opaque type` → 内建（不 offer：没有声明可跳）→ ADT。
限定类型 `m.T` 先 offer 别名段，再按别名的导出面查 `aliases`、`types_by_name`。ADT 整数 id 跨模块相等（symbol-id 线的派生 id），
所以导入方查到的 id 直接交给 `site_of_type` 就能找到声明方。

类型参数作用域放在遍历状态 `Q.tps` 里：顶层声明进入时清空，函数取自己的 `tparams`，impl 方法取 impl 的加自己的，
`type`/`trait` 的形参在语法树里只有名字，没有跨度，从声明名后面的 `[...]` 文本读回（`bracket_binders`，跳过 `!e`）。
形参声明处本身也 offer，definition 指向自己，与函数形参的做法一致。trait bound 的名字按 `traits_by_name` 解析到 trait 声明。

### 3.2 效果行：从文本读回跨度

`FnDecl.effs`、`TraitMethod.effs`、`SLocalFn` 的行、`TFn.effs` 都只有原子的名字，没有跨度。改语法树要动 parser、`fmt`、ast dump 和所有构造点，
T0 只读文本：从返回类型之后（没有返回类型就从形参表的 `)` 之后）到函数体之前扫 `!` 开头的原子，`=` 或 `{` 停（`effect_atoms`）。
起点放在返回类型之后，是因为形参的函数类型里也可以有 `!`；`[..., !e]` 的效果形参在形参表之前，不在扫描范围内。
原子按 `cx.resolve_named_effect` 的规则解析：裸名查 `cx.effects`，`m.E` 查别名导出面的 `effects`；`io`、效果变量、`T.E` 投影没有声明，不 offer。

每个由算术得出的跨度（名字起点加长度）都先核对文本拼写（`spelled`），对不上就不 offer，免得旧一轮分析的跨度落到新文本上。

### 3.3 其余位置

- **操作**：`site_of_sig` 先看 `Sig.op_of`，有就在效果声明里找操作名。调用处、臂名、限定调用三处共用这一个查找。
- **handler 臂名**：`EHandle` 的效果名解析出效果 id，再按效果的 owner 取操作签名（`sig_by_owner`）。
- **模块别名段**：别名与模块的其它名字同一命名空间（spec §10.3），所以 `EVar` 没有类型化节点、名字又在 `module_aliases` 里，就是别名。
  `EFieldAcc` 的 `XConstRef`/`XFnValue`/`XCtor` 臂与限定调用臂从不走接收者，在那几处显式 offer。definition 与 `use` 行一致，指向模块文件开头。
- **改名导入的 UFCS**：`EMethod` 的 `XCallFn` 臂原来要求 `fname == name`，现在也接受 `import_renames[name] == fname`。
- **字段名与具名实参**：名字起点就是 `Arg.lo`。`{ x }` 简写时名字同时是局部量，那一处已经按局部量回答，所以表达式起点等于名字起点的不 offer，
  hover 保持不变。具名实参按签名的 `param_names` 找序号，再到声明模块的 `DFn` 里取形参跨度；trait 方法、效果操作、内建没有具名实参（`ast.Param.default` 说明了原因），不找。
- **`let`/`var` 声明处**：名字跨度用已有的 `let_name_end` 从文本读回，definition 与使用处相同（`Sym.dlo/dhi`）。

### 3.4 收集与渲染分开

`Q.found` 是第二种收集器（第一种是 inlay 的 `InlayRun`）：`resolutions(qc, lo, hi)` 走同一遍历，`offer_target` 只记有定义位置的（跨度，定义位置，文件），
不比较光标。T1 要「种类」、R 线要「键」，都是这张表的投影；接口留在这里，T0 不接任何 LSP 方法，只有 `lsp/server.dawn` 的内联测试读它
（每个收集到的名字，在它起点问 definition 得到同一个位置）。

收集模式不调 `render_sig`：`offer_sig`/`offer_sig_at` 先问 `live(q, lo, hi)`（偏移落在跨度内才可能成为答案），否则 hover 文本留空；
每个表达式的兜底类型 offer 也只在 `live` 时打印类型。hover 模式下不含光标的 offer 本来就会被 `offer_target` 丢掉，所以回包不变。

本机交错两轮测过 12k 行合成缓冲区（调研的 `big.dawn`，`bench.py` 每轮 11 次、丢前 3 次）：definition 中位数基线 103 / 74 ms，T0 94 / 96 ms；
hover 基线 113 / 87 ms，T0 122 / 115 ms；inlay_full 基线 132 / 97 ms，T0 124 / 118 ms。两轮之间的波动比两边的差还大（本机同时有别的负载，
基线走的是没有 `-XX:+UseSerialGC` 的 `java -jar`），只能说同量级，**不能**据此说 `live` 剪掉了多少，也不能说新增的 offer 拖慢了多少。
T1 验收时按报告 5.1 的测法（与 inlay_full 交错对比）复测。

## 四、行为变化

- 原来有回答的位置，hover 逐字不变：夹具对其中 15 处断言基线文本（用 `origin/main` 编出的服务端核对过）。
  `selfhost-lsp-diff.sh` 对真父（`origin/main` 编出的 jar）逐消息比对：115 条消息全部相同，会话不含新覆盖的位置，所以**不写** `Emit-Change(lsp)`。
- 一处有意的变化：字段声明 `l: Expr` 的跨度覆盖了类型，以前光标落在 `Expr` 上回答的是字段；现在类型名自己的跨度更小，回答类型。
  函数形参不受影响（形参的 offer 只覆盖名字）。

## 五、门禁

`scripts/lsp-resolution-coverage.py`，接在 `lsp-workspace` job：

- 正例：两份程序（单文件、两模块），36 个位置断言 definition 恰好一个且落在对的声明上，1 个断言内建类型没有 definition；
  15 个原有位置断言 hover 原文，6 个新位置断言 hover 原文。
- 变异体 4 个，各从私有 selfhost 副本编译，要求自己的那条断言变红：去掉 `EFieldAcc` 的 `XFnValue` 臂、书写类型不解析、臂名不 offer、别名段不 offer。
  编不过的变异体不算负控，整个脚本失败。
- 本机墙钟：正例约 3 s，含四个变异体约 50 s（每个变异体一次私有 selfhost 构建约 10 s）。

## 六、不做的（理由）

- **改语法树给效果行、`type`/`trait` 形参加跨度**：要动 parser、`fmt`、ast dump 与全部构造点，而读回文本在这几种位置上是精确的（语法只允许名字、`!`、括号和 `|`）。
  若 R3 的 rename 需要在这些位置写回，再按实际需求决定。
- **效果变量（`!e`）与 `io`**：效果变量在第一次出现处隐式引入（spec §6.3），没有一个「声明」可跳；显式的 `[!e]` 形参留给有需求时再做。
- **内建类型的 hover**：`Int`、`List` 没有声明可跳，以前在存储位置也不回答；T1 给它们分类时再看要不要 hover。
- **`test "name"` 的名字**：字符串，不是名字。
- **derive 列表的 trait 名**：与 bound 同一查找，但调研表没有列，T0 不扩；R 线若要把 derive 算作 trait 的引用，再加一行。

## T1：semantic tokens（服务端）

裁决第 3 条：只做 `full` 与 `range`，不做 `delta`；只发标识符；分析不可用回空 `data`；不加开关。消费端（VS Code 的 scope 映射、Playground 网关与 CM6 解码）是 T2。

### T1.1 种类从哪来

种类读的是名字**解析到的声明**，不是遍历时站着的节点。`lspq.walked_resolutions` 就是 T0 的收集器（§3.4），不渲染签名，每个名字带着定义位置；
`lsp/lsptok.dawn` 拿定义位置回到声明所在模块，按「名字起点 → 种类」查一张表。顶层声明的表从语法树现建（一个声明一张，同一请求内缓存），
其它模块的表整模块建一次。这样遍历的几十个 offer 臂一个都不用动，T0 的 hover/definition 也就一个字节都不会变。

局部量没有这样的表：形参、`let` 绑定、模式绑定都只是一个 `Sym`，而 `Sym` 不记自己是不是形参。所以遍历在**局部量的声明处**多记一项
`LocalRole`（`ParamRole`、`FnRole`、`MutableRole`、`LetRole`），使用处按定义位置回查这一项。只在声明处记，是因为一个局部量的全部使用都在
同一个顶层声明里，而 `walked_resolutions` 按声明剪枝、不按范围裁，声明处总在同一份列表里。`let` 也要记，是因为它的定义位置是语句起点（`Sym.dlo`），
名字起点对不上定义位置，不记就判断不了「这是声明」。

为此对遍历的改动只有三处，都在收集模式里生效：`offer_local`（声明处带 role 收集，hover 模式照旧走 `offer`）、`collect_local_call`
（调用局部量 `f(x)`、`local_eval()` 时收一条指向该局部量的解析，见 T1.6）、`walked_resolutions` 的剪枝改用每种声明自己的跨度 `decl_span`。

### T1.2 legend

只用 LSP 标准类型名，客户端不配置就能上色；Dawn 自己的种类映射到最接近的标准类型：

| 下标 | 类型 | Dawn 里是什么 | 理由 |
|---|---|---|---|
| 0 | `namespace` | 模块别名（`helper.`、`str.`）、`use` 路径的每一段 | 定义位置是模块文件开头（0,0），没有别的名字落在那里 |
| 1 | `type` | `alias`、`opaque type` | 别名没有自己的构造器，不是 struct 也不是 enum |
| 2 | `struct` | 记录类型，及与之同名的构造器 | 一个名字，一种颜色；构造器与类型同拼写同位置 |
| 3 | `enum` | 和类型（`type Expr = Num(..) \| ...`） | |
| 4 | `interface` | trait、**效果**、`impl` 里写的 trait 名 | 效果是一组操作签名，由 handler 提供实现，正是 interface 的形状；与 trait 同色是有意的（见 T1.7） |
| 5 | `typeParameter` | 类型形参（声明处与使用处） | |
| 6 | `parameter` | 函数、lambda、局部 `fn`、handler 臂、操作的形参；具名实参的名字 | 具名实参 `dy: 5` 的定义位置是形参声明 |
| 7 | `variable` | `let`/`var`、模式绑定、`for` 绑定、handler 状态格、**常量** | 常量加 `readonly`，与 rust-analyzer、gopls 的做法一致 |
| 8 | `property` | 记录字段与构造器字段（声明、访问、记录字面量与模式里的字段名） | |
| 9 | `enumMember` | 和类型的构造器 | |
| 10 | `function` | 顶层函数、局部 `fn`、函数值、改名导入的本地名 | |
| 11 | `method` | trait 方法、impl 方法、**效果操作**（声明、调用、handler 臂名） | 操作是效果这个 interface 的成员；调用 `lookup(n)` 在语法上像函数调用，语义上是对 interface 成员的调用，臂名是实现 |
| 12 | `class` | `use java` 引入的类 | |

修饰（第 i 位对应第 i 项）：`declaration`（名字就在它自己的声明处）、`readonly`（常量）、`defaultLibrary`（声明在 std 的文件里）、
`mutable`（`var` 与 handler 状态格，声明与使用都带）。`mutable` 是唯一的非标准名，取 rust-analyzer 的拼写；不认识它的客户端忽略这一位，T2 在 VS Code 侧登记。

### T1.3 full 与 range

- `full`：整个文档。`range`：只回**起点**落在 `[start, end)` 内的名字。遍历按顶层声明剪枝：跨度与范围不相交的声明不走。
  T0 的 `resolutions` 原来对类型、效果、`use` 行一律整走（`decl_bounds` 没给它们跨度），12k 行缓冲区上这是视口请求的大头；
  `decl_span` 给每种声明都取了跨度，`resolutions` 的结果不变（名字都在自己声明的跨度里），视口请求从约 8.6 ms 降到约 2 ms（T1.5）。
- 编码：五个整数一组（deltaLine、deltaStart、length、type、modifiers），列与长度是 **UTF-16 码元**。码点到 UTF-16 的换算只经 `server.lsp_position`，
  token 的长度是两端列之差，所以名字前面有 BMP 以外的字符时列也对。名字不跨行，跨行的跨度直接丢掉。
- 一个跨度只发它开头的那个名字（字段声明的跨度是 `l: Expr`，`Expr` 另有自己的 token）；`use std/str` 的路径是例外，每段一个 `namespace`。
  同一起点被 offer 两次（记录简写 `{ x }` 既是字段又是局部量）时取最内层的那个，与 hover 的规则一致；token 互不重叠。
- 没有分析（文档未打开、尚未分析完、所在工作区还在加载）时回 `{"data": []}`，不回错误，也不回 `null`：语法高亮照常，等分析好了客户端下一次请求就有。
- 没有声明可落的名字不发：内建类型（`Int`、`List`）、内建函数（`len`、`show`）、从内嵌副本读出的 std（没有文件）。它们保留语法着色；
  大写开头的内建类型被 TextMate 涂成类型，本来就对。

### T1.4 行为变化与 Emit-Change

`initialize` 的回复多了 `semanticTokensProvider`（legend、`full: true`、`range: true`），其余能力不变。`selfhost-lsp-diff.sh` 的会话在 inlays.dawn 上
加了一次 `full` 与一次 `range`（与那里的 inlayHint 同两行），上一 release 回 `-32601`。用真父编出的服务端逐消息对照：基于 `fe6f6cb2` 时 117 条消息、rebase 到 `ff7a77b2`（C5-2 合入）后 132 条消息，
两次都只有这三条不同，hover、definition、inlayHint 逐字节不变，所以提交里写一行 `Emit-Change(lsp)`。

### T1.5 性能（本机实测）

测法照调研 §2.5：本机 16 核 WSL2，`bin/dawn` 默认 JVM 参数；每轮先体内改一行再改回，然后**交错**发 inlayHint 全文、semanticTokens/full、
inlayHint 60 行视口、semanticTokens/range（奇数轮两两对调先后），每格 11 轮丢前 3 轮取中位数。本机当时另有写者负载，两遍之间的波动约 10%。

| 缓冲区 | 行数 | inlay_full | tokens_full | 比值 | inlay_view | tokens_range | full 的 token 数 / 字节 |
|---|---|---|---|---|---|---|---|
| 合成 `untitled:big`（调研的 `big.dawn`） | 11,993 | 98.0 / 101.7 ms | 139.7 / 130.9 ms | 1.43 / 1.29 | 2.0 / 2.0 ms | 2.2 / 2.5 ms | 28,125 / 432 KB |
| `selfhost/src/check/checker.dawn`，工作区模式 | 15,832 | 104.7 / 95.3 ms | 142.3 / 138.3 ms | 1.36 / 1.45 | 2.7 / 2.7 ms | 2.9 / 2.5 ms | 31,656 / 492 KB |
| 合成 `untitled:mid`（Playground 上限 64 KiB） | 2,678 | 18.2 ms | 29.7 ms | 1.63 | 1.3 ms | 1.8 ms | 6,275 / 96 KB |

调研 §5.1 的验收线是 12k 行 full 中位数不超过同缓冲区 inlay_full 的 1.5 倍、range 不超过 10 ms：两遍都在线内。
多出来的三到四成是 token 本身：分类、按起点排序去重、每个 token 两次码点到 UTF-16 的换算，以及比 inlay 多的 JSON。
小缓冲区上比值高些（1.63），绝对值 30 ms。剪枝改动之前同一测法的 range 是 8.7 / 8.5 ms（视口外的类型、效果头每次都走）。
Playground 尺寸的 full 回复 96 KB，在网关 256 KiB 的单条上限之内；T2 让 Playground 只请求 range。

### T1.6 收集里的一处补洞

调用局部量（形参 `f(x)`、局部 `fn` 的 `local_eval()`）在遍历里是 `XCallDyn`，原来只按名字查全局签名：没有同名全局函数时什么也不 offer，
有的话还会指错（局部量遮蔽全局函数）。T1 只在收集模式里补一条指向该局部量的解析（`collect_local_call`），排在遍历自己的 offer 之前，
所以 token 读的是局部量。hover 与 definition 在这些位置照旧，留给 R1：references 要的是同一件事，届时连同 hover 一并改，并写自己的 Emit-Change。
（R1 已改，见 §R1.5：遍历在这里直接 offer 局部量，`collect_local_call` 随之删去。）

### T1.7 门禁

`scripts/lsp-semantic-tokens.py`，接在 `lsp-workspace` job（T0 那一步之后）：

- 正例：T0 夹具的两份程序（单文件改了一行，加进一个字符串里有两个 BMP 以外字符、后面跟着名字的 `let`），`full` 回复按 UTF-16 解码成
  （文本，类型，修饰）后与期望序列逐项相等（单文件 133 个，两模块 69 个）；两个 range（`norm` 体内两行；BMP 以外字符那一行的后半段）逐项相等；
  legend 有 `full`、`range`、没有 `delta`；未打开的文档回 `{"data": []}`。
- 变异体 4 个，锚点在 `scripts/lsp-semantic-tokens/mutate.py`，登进 `mutation-anchor-preflight.py` 的登记表，构建前先证明每个锚点恰好命中一次：
  常量退回 `type`（种类映射错）、`var` 丢 `mutable`、range 不裁剪、列按 UTF-8 字节算。各自从私有 selfhost 副本编译，要求自己那条断言变红。
- 本机墙钟：正例约 3 s，含四个变异体约 39 s。`lsp-workspace` 的规划额度 717 → 795 s，timeout 36 → 40 分钟，push-total 16,460 → 16,538 s。
- 2026-10-04 审计第 16 条：第一版解码后只比（文本，类型，修饰），位置丢了，把 `acc = acc + p.x` 右边的 `acc` 挪到左边、重编后续 delta，
  左边两个重叠、右边没有，断言照样绿。现在每个 token 解码出绝对行与 UTF-16 列，另有一条「positions」断言：覆盖一个完整的名字、不与前一个重叠、
  是前一个 token 之后同名文本的第一次出现（于是挪到更早的同名处也红）、range 的 token 起点在 range 内。另加一份非 ASCII 名字的文档
  （`中文`、`café`、`éx`，审计第 4 条：`name_runs` 原来只认 ASCII，`café` 只出 `caf`、`中文` 没有 token）。

### T1.8 不做的（理由）

- **delta**：成本在遍历不在载荷（T1.5 里 full 的大头是遍历），要多一份按 URI 的缓存与 `resultId`；裁决第 3 条。
- **关键字、字面量、注释、运算符的 token**：语法高亮已经做对，再发会撞 Playground 的单条上限，也会让服务端未就绪时颜色闪动；裁决第 3 条。
- **自定义类型 `effect` 与修饰 `effect`**（调研 §2.2 的建议）：要客户端登记才有颜色，VS Code 侧是 T2 的事；先用标准名，效果与 trait 同为 `interface`、
  操作与 trait 方法同为 `method`。T2 若要区分，加一个自定义修饰即可，类型下标不动。
- **`modification` 修饰（赋值目标）**：`acc = acc + 1` 左边的 `acc` 现在只是 `mutable`。标准名有，但要遍历区分读写，留到 R1（documentHighlight 的读/写种类要的正是它）。
- **内建类型、内建函数的 token**：没有声明可落，分类无从读；TextMate 按大小写已经涂对。
- **开关**：token 来自已经算好的分析，请求时只是一次遍历；分析未就绪回空，语法高亮不受影响。裁决第 3 条。

## T2：semantic tokens 消费端（VS Code 与 Playground）

裁决第 1、3 条；调研 §5.1 的 T2 行。服务端一字节不动：两端都只读 T1 的 legend 与 `data`，按 legend 里的**名字**解码，不在客户端另抄一份下标表。
legend 的顺序归服务端，客户端抄一份就等于把 T1.2 那张表复制到第二、第三处，服务端哪天插一个类型，客户端的颜色就整体错位一格。

### T2.1 Playground 走哪条路

任务单的前提是「Playground 后端今天走 `/check`，不是 LSP 会话」。实查不成立：`/check` 只剩 LSP 不可用时的诊断兜底（`site/play-ui/src/lint.ts`），
hover、completion、definition、inlayHint 早已走 #11 的 WebSocket 网关（`playground/lsp_gateway.py`，见 `docs/playground-lsp-design.md`），
网关后面就是一个 native `dawnc lsp` 会话，T1 落地后它本来就答 `semanticTokens/range`。所以两条候选（后端加端点、`/check` 回包带 tokens）都不选：
前者要在 `playground/src/main.dawn` 里再起一个 LSP 会话或另写一遍分类，后者要改 `/check` 的合约，而且 `/check` 是一次性编译，没有 hover 等用的那份分析。
走网关只需三处窄改动，`/check` 与 `contract.sh` 里的 `/run`、`/check` 用例一个字不变：

- **白名单只加 `textDocument/semanticTokens/range`**，`full` 照旧 `method is not allowed`（1008 关连接）。`full` 的回复随整个缓冲区长，
  T1.5 实测 64 KiB 缓冲区 96 KB，离单条 256 KiB 上限不远，而调研 §2.4 的最坏写法到 243 KB；Playground 只看视口，用不着它。
- **initialize 改写**：子进程宣告了 `semanticTokensProvider` 且 legend 是短的纯字母名表（类型不超过 64 个，修饰不超过 16 个）时，网关原样转发子进程的 legend，
  宣告 `{"range": true, "full": false}`；否则不宣告，请求也按未放行处理。生产上网关与 `dawnc` 分开部署，旧 `dawnc` 配新网关时 Playground 就是没有 token，不是报错。
- **范围按字节裁**：网关记着当前文本（didOpen、didChange 本来就过它的手），把请求范围从起点往后数，超过预算的 UTF-8 字节数就把终点截到那里（换成 UTF-16 列）。
  预算从单条上限倒推：range 只回起点落在范围内的名字，每个名字后面至少还有一个字节才轮到下一个名字，所以 n 字节最多 n/2+1 个 token；
  每个 token 五个整数，每个整数编码后不超过 6 字节（行、列、长度都受 64 KiB 源码上限约束在五位数内，类型下标小于 64，修饰位小于 2^16），
  再给信封留 1 KiB。256 KiB 上限下预算是 17,406 字节，大约是 200 行 80 列，比一屏多得多，正常视口碰不到；碰到时浏览器拿到的是截断处之前的 token，后半截保留语法色。
  调研说的「超限回空」改成了「先裁再发」：子进程的回复超过上限在网关里是协议错误，会直接结束会话，等它超了再回空已经来不及，只能在请求这一侧保证它不超。
- 回复只放行 `data`（丢掉 `resultId` 之类），并核对它是长度为 5 的倍数的非负整数数组；不合格按子进程协议错误处理，与 completion resolve 一致。

### T2.2 两端怎么取、何时取

| | VS Code | Playground |
|---|---|---|
| 协商 | `vscode-languageclient` 9 的默认特性集里就有 `SemanticTokensFeature`，服务端宣告 `full` 与 `range`，它就注册两个 provider；扩展代码不用动 | 自己的 `DawnLspClient` 在 initialize 回复里读 legend（`semanticLegendOf`），断线即丢 |
| 请求 | VS Code 自己决定：先对可见区域发 `range` 尽快上色，再发 `full`；没有 delta，编辑后重发 `full` | 只发 `range`，范围是 CM6 的 `view.viewport`（可见区域加一点余量） |
| 时机 | 由编辑器调度 | 编辑与滚动停 300 ms 后（与 inlayHint 同一节奏），且在服务端分析完这一版文本之后（`queryWith` 等诊断回来）；文本又变了就丢掉回复 |
| 等待中 | 编辑器保留旧 token | 已画的 mark 随编辑映射位置，不先清掉，免得每敲一个键闪一次 |
| 空 `data`、无 legend、连接断开 | 只剩 TextMate 着色 | 只剩 stream tokenizer 着色；断开时清掉全部 mark |

Playground 的解码在 `site/play-ui/src/lsp.ts` 的 `decodeSemanticTokens`：JavaScript 字符串下标本来就是 UTF-16 码元，所以只需要逐行走换行；
类型下标不在 legend 里、跨行、落在文本之外的 token 丢弃，不画到别处。

### T2.3 样式映射

VS Code 侧标准名不需要任何配置：主题有 semantic 规则就用主题的；没有的（包括默认的 Dark+/Light+ 对大部分类型），VS Code 按内置表回落到 TextMate scope
（`enumMember` → `variable.other.enummember`，`variable.readonly` → `variable.other.constant`，`function.defaultLibrary` → `support.function` 等）。
唯一的非标准名 `mutable` 在 `package.json` 里登记为 `semanticTokenModifiers`，并在 `semanticTokenScopes` 里把 `*.mutable` 映到 `markup.underline`：
默认主题给它下划线，颜色仍由类型那一层决定，与 rust-analyzer 的做法一致。不登记的话 VS Code 不认识这一位，静默丢掉。效果仍与 trait 同为 `interface`
（T1.8），不另加修饰。

Playground 侧每个 token 一个 `Decoration.mark`，类名 `dp-sem-<类型>` 加每个修饰的 `dp-sem-<修饰>`。只给语法高亮分不出来的几类改色，其余保持语法色：

| token | 颜色 | 理由 |
|---|---|---|
| `function`、`method` | `--f`（原来只给 `fn` 后的定义名） | 调用处与定义处同色，CM6 原来只认得定义处 |
| `enumMember`、带 `readonly` 的（常量） | `--n`（数字色） | 它们是值；按大小写原来都涂成类型色 |
| 带 `mutable` 的 | 下划线 | 同 VS Code |
| 其余（类型、trait、效果、形参、局部量、字段、模块别名） | 不改 | 语法色已经对，或者原来就不上色 |

CM6 里 mark 与语法高亮的 span 谁包谁取决于优先级，所以每条规则同时写 `.dp-sem-x` 与 `.dp-sem-x *`，并放在 `tok-*` 规则之后，特异性相同时它赢。

### T2.4 TextMate / stream tokenizer 与 semantic tokens 的分工

语法着色负责关键字、字面量、字符串插值、注释、运算符，以及打开文件后第一帧的全部颜色；semantic tokens 只覆盖**名字**，而且只在服务端分析完之后叠上去。
二者互不替代：服务端没起来、文件还没分析完、或者是旧 `dawnc`，看到的就是今天的着色。所以 `editors/vscode/syntaxes/dawn.tmLanguage.json` 与
`site/play-ui/src/dawn-lang.ts` 都不删任何规则，它们按大小写把构造器、常量涂成类型的那几条也保留：那是没有 token 时最好的猜测。

### T2.5 门禁

- `editors/vscode/test/semantic-contract.js`（接进 `npm test`，`editor-grammar` workflow 已在跑）：从 `lsptok.dawn` 读出 legend，核对非标准类型与修饰都在
  `package.json` 里登记、登记的都还在 legend 里、每个非标准名都有回落 scope、selector 只用 legend 里的名字、`CHANGELOG.md` 首条与版本号一致。
  七个变异体（服务端加修饰、加类型、删 `mutable` 登记、服务端删修饰、selector 拼错、删回落 scope、版本号挪动）各自要红在自己的错误码上；
  对 HEAD 的旧 `package.json` 跑也是红的。本机约 0.1 s。
- `playground/test/lsp_contract.py`（`contract.sh` 先跑的 `lsp-contract.sh`）：假子进程故意用**不是**真服务端顺序的 legend，断言浏览器拿到的就是这份；
  直连会话里发一次 range（多余键被剥掉、回复只剩 `data`）、审计日志里转发的是重建过的范围；`full` 关连接 1008。
  另有不走 socket 的 `semantic_tokens_contract`：无 legend、legend 名不合法、修饰超过 16 个都不宣告且请求被拒；按字节裁范围（含 BMP 以外字符后的 UTF-16 列）、
  didChange 之后按新文本裁；畸形回复是子进程协议错误。三个变异体（网关自写 legend、列按码点算、不裁）跑在网关源码的变异副本上，各自要红在自己的断言上。
  本机整个 `lsp-contract.sh` 约 7 s，新增部分不到 0.5 s。
- `site/play-ui/test/selftest.ts`（`npm test`）：legend 读取、按打乱顺序的 legend 解码、BMP 以外字符后的偏移、类名、mark 位置、客户端请求参数与畸形回复。
  两个变异（解码改用写死的 T1 顺序；列按码点算）手工证红，这个测试不在 CI 里跑，所以没做成常驻变异体。
- 端到端：本机用网关接 JVM 的 `dawn lsp`、再接 `scripts/release-native.sh` 编出的 `dawnc lsp` 各跑一次（initialize、didOpen、range、full 被拒），
  同一段 10 行程序两边都是 legend 原样到达、`full` 被关；token 逐项相同，只差一个：JVM 那边 `println` 有一个 `function`+`defaultLibrary`，
  native 没有。native 的 std 是编进二进制的副本，没有文件可落（T1.3 已写明这类名字不发），所以 Playground 里 std 函数保留语法色，这是预期，不是缺口。

### T2.6 不做的（理由）

- **Playground 请求 `full`、网关放行 `full`**：见 T2.1；视口之外的颜色用户看不见，滚动后再要一次 range 只要 2 ms 量级（T1.5）。
- **超限时回空**：网关读到超限的回复时会话已经要断了；改成请求前裁范围，见 T2.1。
- **Playground 的 `/check` 带 tokens**：`/check` 是没有会话的一次性编译，tokens 要的分析在 LSP 会话里；见 T2.1。
- **自定义类型 `effect`、自定义修饰 `effect`**：同 T1.8；VS Code 侧现在多登记一个名字不难，但服务端不发，登记了也没有颜色。
- **把 CM6 关键字表对齐 `front/token.dawn` 并纳入对账**（调研 §2.1 的旁支发现）：与 semantic tokens 无关，单独一刀。
- **VS Code 扩展发布到 marketplace**：版本号升到 0.1.3、写了 `CHANGELOG.md`；发版由维护者做。

## R1：单文件 references 与 documentHighlight

调研 §5.1 的 R1 行：同一个收集器按键投影，只在当前文档内；documentHighlight 是同一份结果换个形状。跨文件的引用是 R2（工作区索引），改名是 R3。

### R1.1 键：声明，不是名字

键是名字**解析到的声明**的位置：`(def_path, 名字跨度)`，即 `Resolution.def_path` 与 `Resolution.def`。两个声明不会落在同一个位置，
所以位置就是声明的身份；拼写一概不看。这正是 references 与文本搜索的分别：`let n = n + 1` 里左边的 `n` 是新的局部量，
右边的 `n` 是被它遮蔽的形参；形参 `twice: fn(Int) -> Int` 与顶层函数 `twice` 同名；记录简写 `{ x }` 里的 `x` 既是字段又是局部量。
同名而不同声明的，各自是各自的引用集合，夹具对这几种都有负例。

不用 `Sym` 的整数 id：`Sym` 只有本模块的局部量才有，顶层声明、别的模块的声明、std 都没有；而遍历给每个名字的定义位置对局部量就是
`Sym.dlo/dhi`，对其余的是声明的名字跨度，两者已经是同一套坐标（T0 的内联测试逐个核对过「收集到的位置 = definition 的回答」）。

光标处的键取 definition 在那里的回答（`lspq.find_target`），而不是另走一遍收集再找最内层：这样「references 认哪个声明」与
「definition 跳到哪里」由同一条规则决定，不会出现两者对同一个光标说法不一的情况。光标下的名字没有声明（内建类型、内建函数、字面量）时回空列表。

然后把整个文档走一遍收集（`lspq.walked_resolutions`），留下键相同的，按起点排序。每个结果裁到名字本身：字段声明的跨度是 `x: Int`，
引用只要 `x`；模块的路径 `use std/str` 取最后一段 `str`（模块的定义位置是文件开头 (0,0)，见 §T1.2）。同一起点被收集两次的只留一个：
记录类型与它的构造器同名同位置，二者的引用合在一起，这与「一个名字一种颜色」（§T1.2）是同一个取舍。

**只在当前文档内**：声明在别的模块时，本文档里的使用照样找得到，别的文件里的找不到。空结果不证明没人用，这是 R2 要补的。

### R1.2 声明处与 `includeDeclaration`

声明处是「名字就站在它自己的定义位置上」的那个：本文档内（`def_path` 为空），且起点等于定义位置；`let` 的定义位置是整条语句（`Sym.dlo`），
它的名字靠 T1 在声明处打的 `LocalRole` 认出来。`context.includeDeclaration` 为真时它在结果里，为假时去掉；声明在别的模块时本来就不在本文档。
请求没带 `context` 时按假处理（LSP 规定该字段必有，缺了就取保守的一边）。

### R1.3 documentHighlight 的读与写

结果与 `includeDeclaration: true` 的 references 相同，只是每项带种类：**声明处与赋值目标是 Write（3），其余都是 Read（2）**，不用 Text（1）。
声明把值绑到名字上，赋值改写它，二者对读者是同一类事件；函数、类型的声明处也算 Write，是为了规则只有一条，客户端把声明处和使用处分开着色就够了。
赋值目标是遍历在 `SAssign` 处知道、跨度上看不出的事，所以收集时带一个 `UseKind.AssignUse`；handler 状态格的写（检查器把它改写成 `cell_set`）同样算写。

### R1.4 记录简写双向，以及 impl

一个跨度有时要算作两个声明的引用，而 hover、definition、semantic tokens 都只能回答一个。这样的位置在收集时多记一条「只给 references 读」的解析
（`UseKind.PunUse`/`ImplUse`，`lspq.references_only`）：`resolutions` 与 `lsptok` 都跳过它们，所以 T0 的契约与 T1 的 token 不变。

- **记录简写**：`Point { x, y }`（构造）与 `Point { x, y: _ }`（模式）里的 `x`，遍历按局部量回答（T0 §3.3），收集时再记一条指向字段声明的。
  于是字段 `x` 的引用里有这几处简写，局部量 `x` 的引用里也有，两个方向都不漏；R3 改名时这正是要展开成 `x: x` 的地方（裁决第 4 条）。
  光标落在简写上时，definition 说的是局部量，references 也就给局部量的集合。
- **impl**：`impl Area[Point]` 里的 trait 名、impl 里每个方法的名字，遍历按 impl 自己的位置回答（definition 跳到自己），收集时再各记一条
  指向 trait 声明与 trait 方法声明的。于是从 trait 方法出发的引用含 impl 里的同名方法，从 trait 出发的含 impl 头。反方向不做：光标在 impl 方法上，
  definition 说的是 impl 方法自己，references 就只给它自己的集合（见 R1.8）。

### R1.5 遍历上的两处改动与行为变化

**调用局部量**（§T1.6 记下的错指）：`XCallDyn` 的臂原来按名字查全局签名，现在与读局部量的 `EVar` 臂共用 `offer_local_use`，
hover 是 `let f: fn(Int) -> Int`，definition 跳到局部量。T1 为 token 单独补的 `collect_local_call` 不再需要，删去；token 不变（夹具逐项核过）。

**检查器重排过实参的调用**：调用写了具名实参而顺序与形参不同，或省略的默认值要读前面的形参时，检查器把写出的实参先绑到局部量，
类型化节点是「一串 `let` 加末尾的调用」（`checker.arrange_call_args`）；只省略末尾默认值时，类型化实参里又混着补上的默认调用，
个数与写出的不等。遍历原来按下标配对，两种情况都配不上，于是整串实参退回无类型遍历，里面的名字一个都不解析：
`pad_to(tag, width, "-")` 里的 `width` 不是 `width` 的引用，改名时会漏。现在 `arranged` 剥掉那层块，写出的实参取 `let` 的值；
个数仍不等时按跨度找（`typed_at`，原来 handler 臂已经这样找），方法调用的子节点同样处理。

`selfhost-lsp-diff.sh` 的会话在 inlays.dawn 上加了一次 references（`let width`，含声明）与一次 documentHighlight（模式里的 `n`）。
用真父（`f11a2249` 编出的服务端）逐消息对照，134 条消息里 6 条不同，都是有意的：

| 消息 | 变化 |
|---|---|
| initialize | 多了 `referencesProvider`、`documentHighlightProvider` |
| app.dawn 上 hover `double(n)`（局部 `fn` 的调用） | `Int`（外层调用的类型）变为 `let double: fn(Int) -> Int`，跨度缩到名字 |
| inlays.dawn 的 semanticTokens/full | 多两个 token：`pad_to(tag, width, "-")` 里的 `tag`、`width`（省略了默认值的调用） |
| references、documentHighlight | 新请求；真父回 `-32601` |
| defaults.dawn 的 inlayHint | `each([1]) { n => ... }` 的 `n` 多了 `: Int`（`each` 省略了 `step`，尾随块的形参原来没有类型） |

所以提交里写一行 `Emit-Change(lsp)`。

### R1.6 性能（本机实测）

测法照 §T1.5：调研的合成缓冲区 `untitled:big`（11,993 行），每轮先体内改一行再改回，然后**交错**发 inlayHint 全文（一次整篇遍历的参照）、
definition、references 与 documentHighlight（光标在 `norm74` 里的局部量 `acc`，5 处）、references（光标在 `use std/str` 的 `str`，全篇 149 处），
奇数轮倒序；每格 11 轮丢前 3 轮取中位数，两遍。本机当时另有负载（load average 约 3.6）。

| 请求 | 第一遍 | 第二遍 |
|---|---|---|
| inlayHint 全文 | 83.9 ms | 102.6 ms |
| definition | 64.1 ms | 68.0 ms |
| references（局部量，5 处） | 132.7 ms | 144.3 ms |
| documentHighlight（同上） | 133.2 ms | 148.7 ms |
| references（模块别名，149 处） | 136.6 ms | 150.4 ms |

references 约等于一次 definition 加一次整篇收集，与结果多少几乎无关（5 处与 149 处差 4–6 ms）。
单文件的一百多毫秒对按键触发的 documentHighlight 也够用；R1.8 记了能把局部量的请求再砍一半的裁剪，等有需要再做。

### R1.7 门禁

`scripts/lsp-references.py`，接在 `lsp-workspace` job（semantic tokens 那一步之后）：

- 正例：一份程序一个会话。20 个 references 用例逐项断言 `行:列 文本` 的完整列表：局部量（`var` 及其赋值）、`let`、形参、具名实参（含方法调用里次序打乱的）、
  省略默认值的调用里的实参、记录简写的字段一侧（构造与模式各一）与局部量一侧、trait 方法（含 impl 方法与调用）、操作（含调用与 handler 臂）、构造器、字段；
  负例：遮蔽的 `let` 与被遮蔽的形参各自的集合、与顶层函数同名的形参与那个函数各自的集合；`includeDeclaration: false`；内建类型回空。
  两个 documentHighlight 用例断言读写种类；调用局部量处的 definition 与 hover；未打开的文档两种请求都回空列表。
- 变异体 4 个，锚点在 `scripts/lsp-references/mutate.py`，登进 `mutation-anchor-preflight.py` 的登记表：按名字而非声明匹配（文本搜索）、
  丢掉声明处（无视 `includeDeclaration`）、记录简写只算局部量一侧、调用局部量退回按名字查全局函数。各自从私有 selfhost 副本编译，要求自己那条断言变红。
- 本机墙钟：正例约 1.5 s，含四个变异体约 55 s。`lsp-workspace` 的规划额度 795 → 905 s，timeout 40 → 46 分钟，push-total 16,538 → 16,648 s。

### R1.8 不做的（理由）

- **跨文件**：R2。工作区索引要挂在模块步骤上随记忆复用（调研 §5.1 R2 行），不是在 R1 里顺手能做对的事；R1 的结果对别的文件只字不提。
- **先文本搜索再逐个解析**（rust-analyzer 的做法）：它解决的是没有现成解析结果的问题；本文档的每个名字已经解析过，按键过滤就是全部的搜索（裁决第 5 条）。
- **从 impl 方法反查 trait 方法**：要让 definition 在 impl 方法上改答 trait 方法，或者让 references 不跟 definition 走；两者都改变一个已经有人依赖的回答。
  R3 改名 trait 方法时必须连 impl 一起改，到时按改名的安全条件定。
- **impl 头里 trait 名的 definition**：仍然跳到自己（T0 的现状），R1 只在收集里补了指向 trait 的那一条。改它会动 hover 文本，留给 R3 一并处理。
- **按局部量裁剪遍历范围**：局部量的引用都在它所在的顶层声明里，理论上只走那一个声明就够；但判断「这是局部量」要再引一套规则，
  而整篇遍历在 12k 行上也只是一百多毫秒（R1.6）。等 R2 的索引挂上记忆步骤后再看。
- **Text（1）种类**：每个名字都已解析，没有「只是文字相同」的结果可标。

## R2：工作区 references

调研 §5.1 的 R2 行：工作区装全仓（`project_files`），索引挂在模块步骤上随记忆复用，共享一份导出环境；`includeDeclaration` 照做。
R1 的结果对别的文件只字不提，R2 补的就是这一半。documentHighlight 仍然只在当前文档内（它本来就是「这个文件里哪些地方」），standalone 缓冲区的 references 仍按 R1 答。

### R2.1 两个程序：诊断的与引用的

R1 时一个 workspace 的程序只有打开的文档和它们的导入闭包。没有任何打开文档导入的项目文件（一个还没接进 `main` 的模块、一个只被测试用的模块）
不在程序里，它里面的引用无从谈起，所以 references 要一个装了全仓的程序。

**这个程序不在诊断的路径上。** 第一版把全仓直接装进 workspace 的程序，selfhost 上打开 `check/types.dawn` 到首次诊断从 1.5 s 变成 4 到 4.8 s，
每个编辑会话都替一个还没人问过的 references 付钱，协调者没有接受。现在 workspace 有两个程序：

- `Workspace.prog`：诊断、hover、definition、补全读的那个，照旧只装打开文档的导入闭包，rebuild 一字未改。
- `Workspace.world`（`RefsWorld`）：references 读的那个，装打开文档再加整棵源码树。它在**第一次 workspace references 请求时**才建：
  走一遍 `project_files`（只留模块路径合法的文件，`project_seeds`），用它自己的 `incremental.Session` 检查全部模块，解析记忆从 workspace 的那份起步。
  之后每次 rebuild 只把它标成过期（`current: false`），不碰它；下一次 references 请求先把它带到当前文本（`refs_world`）：同一个 session，
  所以编辑没动到的模块的步骤原样复用，只重查被编辑的模块和导出面变了的导入者。冲突快照与 `prog` 一起丢掉它；manifest refresh 换 workspace 时它随旧 workspace 一起走。

**没打开的文件在磁盘上变了（2026-10-04 审计第 2、3 条）。** 第一版的模块列表取自规划时的 `project_files`，之后不再变，
会话中新建的模块永远不进引用程序；`current` 又只由编辑翻转，一个没打开的文件在磁盘上被改了，引用程序照旧答旧文本的位置，
rename 据此算出的区间落在别的字符上（实测把首行注释里的 `x pad` 换成了 `grow`），自检用的也是同一份旧文本，查不出来。现在三处：

- 每次真正重分析都重走一遍源码树（`project_seeds` 调 `project_files_now`），新建、删除的模块随之进出；
- 注册 `**/*.dawn` 的文件监视，`workspace/didChangeWatchedFiles` 里有落在某 workspace source root 下的 `.dawn` 就把它的引用程序标成过期（`sources_changed`）；
- rename 与 prepareRename 不信通知：`refs_world(.., verify: true)` 先比一遍磁盘（`world_stale`：模块集合是否变了，没有打开文档的每个项目模块的文件文本是否还是分析时那份），
  不一致就重分析。客户端不监视文件时 references 可能仍是旧的，rename 不会：编辑区间就是从这份文本算的。

比一遍磁盘是读全部项目文件，对 references 每次请求都付不划算，所以只有 rename 付。

全仓只对**有 `dawn.toml` 的项目**这样装。没有 manifest 的目录只是散文件碰巧放在一起的地方（R1 的夹具、`~/Downloads` 里打开的一个文件），
它的兄弟文件不是同一个程序；这种 workspace 的引用程序就是导入闭包。装全仓与 CLI 的目录模式一致：spec §10.5 规定「未被引用的模块也检查」，
`load_directory_planned` 装的就是 `project_files`。

诊断只来自 `prog`，所以引用程序里多出来的模块（包括有错的）永远不发诊断，不需要任何过滤。

### R2.2 索引的形状与挂在哪一步

每个模块一条 `lspref.ModRefs`：

```dawn
pub(pkg) type Ref = { lo: Int, hi: Int, path: String, def: (Int, Int), decl: Bool, write: Bool }
pub(pkg) type ModRefs = { path: String, text: String, refs: List[Ref], read: Map[String, String] }
```

`refs` 是这个模块整篇遍历（`walked_resolutions`，R1 读的同一份收集）里每个名字的出现，裁剪与 `decl`/`write` 的判定照 R1（`occurrence`），
外加它指向的声明：`path` 是声明所在文件的 identity（`canon_identity`；本模块的声明与局部量记成本模块自己的 identity，于是同一个键从哪个模块读都一样），
`def` 是声明在那个文件里的位置。std 的文件不在程序里，路径照原样留着，std 在一个分析会话里是固定的。`read` 见 R2.3。

条目放在 `RefsWorld.refs`，以模块路径为键。**它的寿命就是引用程序里那个模块步骤的寿命**：`driver/incremental.analyze` 的 `Update` 多了一个 `reused`
集合（这次原样取用了上一步的那些模块），`refs_world` 把程序带到当前文本时只留下 `reused` 里的模块的条目，其余丢掉。条目是惰性的：
一次请求遇到缺的条目才走那个模块一遍，并把读到或移动过的条目连同程序写回 workspace，下一次请求直接用。

这不碰记忆的契约（incremental-memo-1..3 守的那些）：诊断那一侧的 `Session` 与 rebuild 都没有变，复用规则一字不改，
`Update.reused` 只是把规则已经做出的判断报出来。`Cold` 配置下引用程序的 session 同样不复用，条目每次都重读，与参照配置的关系和分析本身一样。

**共享一份导出环境。** 原来每次请求 `doc_qcx` 都把程序里每个模块的导出面现算一遍。走 N 个模块时这一步若跟着每个模块算就是 N 倍，
所以拆成 `program_exports`（每个请求一次）与 `module_qcx`（每个模块套上自己包的可见性）。

**请求文档自己不读索引**，照 R1 用活文本在引用程序里走一遍（`occurrences`）：光标处的键本来就要靠 `find_target` 在这份文本上取，
而且这样 R1 的四个变异体在工作区文档上照样咬得住。其余模块从索引读，按键过滤（`refs_to`），同一起点只留一个（R1 的去重规则）。
回复先按文件 identity、再按位置排序；文件若有打开的文档，用那个文档的 URI，否则用 `path_to_uri(identity)`。

### R2.3 失效规则

一个模块的步骤被复用，说明它的文本没变、它读到的导出面也没变，所以它的每个名字仍然指向同一个声明。**变的只有位置**：
它指向别的文件的声明，那个文件改了一行，声明就挪了地方，而条目里记的还是旧位置。

`read` 记的就是这个：条目指向的每个别的文件，读位置时那个文件的文本。请求时逐个对比当前文本（同一个字符串对象时比较是常数时间），
不同就算一次 `Shift`：两份文本的最长公共前缀，再在剩下的部分里取最长公共后缀。落在公共前缀里的位置不动，落在公共后缀里的平移，
**落在改动区里的放弃**，整条条目重读（`refresh` 回 None），因为那个位置上现在可能是另一个声明，或者什么都没有。
连着几次编辑才问一次 references 时，前后缀合成一个更宽的改动区，只会让更多位置落进改动区、走重读，不会把位置移错。
一个请求里同一个文件的 `Shift` 只算一次（导入它的模块记的是同一份旧文本），按文件记在请求里。

被重查的模块条目直接丢，不走这条路：重查可能改变它的名字解析到哪里，那不是平移能修的。被编辑的文件自己当然也被重查。

### R2.4 与 R1 相同的部分

`includeDeclaration`：照 R1，声明处只在为真时给出，缺 `context` 按假；声明在别的模块时，「声明处」由那个模块自己的条目判定（它在那里 `def_path` 为空）。
Playground：网关的白名单里没有 references 与 documentHighlight（`playground/lsp_gateway.py`），与 R1 同样不转发；Playground 的文档是 `untitled:` 缓冲区，
在服务端本来就是 standalone，R2 也不会改变它的回答。

### R2.5 行为变化与 Emit-Change

`selfhost-lsp-diff.sh` 的会话在 inlays.dawn 上加了一次跨文件 references（`pad_to(tag, ...)` 处，含声明）。用真父（rebase 后的父提交 `3e904284` 编出的服务端；rebase 前对 `d091ae69` 结果相同）逐消息对照，
135 条消息里只有这一条不同：真父只给出本文件的两处（导入列表与调用），R2 多出 util.dawn 里的声明。会话里的 hover、definition、诊断等逐字不变。
会话的 proj 没有 `dawn.toml`，所以这一条看到的是「导入闭包内跨文件」；「未被导入的文件」由 R2.7 的夹具守。提交里写一行 `Emit-Change(lsp)`。

**补全的一处 panic。** 第一版把全仓装进诊断程序时，`lsp-use-completion.py` 在集群全套里红了：`use a/b.{` 的补全在模块已在程序里时走 `exported_items`，
用**文档自己的**类型表渲染那个模块的签名，而这条 `use` 还没写完，文档的表里没有那个模块的类型，`adt_of` 当场 panic。诊断程序回到导入闭包后
那个夹具不再触发它，但同一个洞在真父上也够得着：另一个打开的文档导入了那个模块，它就在程序里，而正在写 `use` 的这个文档的表里没有。
所以修法保留：`exported_items` 先取导出面自带的 `adt_infos`/`trait_infos`，再叠上文档自己的（同一个 id 在两边指同一个声明）。

### R2.6 性能（本机实测）

selfhost 工作区，JVM（`./bin/dawn lsp`），打开 `check/types.dawn`（4,727 行；全仓共 79 个模块）。每轮先在 `adt_of` 声明**上方**的一个函数体里改一个字面量
（`+ 1` 与 `+ 10` 交替，声明因此平移一个字符，导入 types.dawn 的模块的条目都要走 R2.3 的平移），等到这个版本的诊断发布，
先发一次 references（`adt_of` 的一次调用处，全仓 21 个文件 130 处：它要先把引用程序带到当前文本），再**交错**发 definition、
同一处的 references、同一文件里局部量 `a` 的 references（4 处），奇数轮倒序；11 轮丢前 3 轮取中位数。真父与 R2 交错各跑两遍，本机 load average 约 2.4。

诊断路径（验收：与真父相差 10% 以内）：

| | 真父 `d091ae69` | R2 |
|---|---|---|
| didOpen 到首次诊断 | 1.61 s、1.44 s | 1.13 s、1.14 s |
| 体内编辑到诊断（中位数） | 234.4 ms、233.0 ms | 228.0 ms、227.7 ms |

两项都不比真父慢（首次诊断那格 R2 反而快，是同机两次 JVM 冷启动之间的抖动，不是 R2 做了什么）。

references：

| 请求 | 第一遍 | 第二遍 |
|---|---|---|
| 第一次 references（建引用程序，检查全仓，建全部条目） | 4.19 s | 4.14 s |
| 编辑后的第一次 references（把程序带到当前文本） | 334.1 ms | 329.5 ms |
| 之后的 references（`adt_of`，130 处） | 198.4 ms | 199.5 ms |
| references（局部量，4 处） | 38.8 ms | 36.8 ms |
| definition | 9.0 ms | 8.6 ms |

目标「体内编辑后 references 中位数 ≤ 0.5 s」达到：编辑后第一次 330 ms，其中约 130 ms 是引用程序重查被编辑的 types.dawn，其余与之后的请求相同，
大头是给 21 个有结果的文件各建一次 UTF-16 视图（`view_of`）好换算区间。保留的 8 轮里编辑后第一次有一轮到 650 到 670 ms，中位数不受它影响。
第一次 references 的 4.1 s 是全仓第一次检查（与 CLI `dawn check selfhost` 同量级）加全部条目，每个 workspace 付一次。

### R2.7 门禁

`scripts/lsp-references-workspace.py`：

- 两模块工程（main 导入 helper）与三模块工程（main 与 lone 各自导入 base，没有任何模块导入 lone；另有一个没人导入、带类型错误的 broken.dawn）。
  每个工程一个会话，先只打开 main：从导入列表、限定调用、限定函数值、管道进限定函数、经导入的调用五处各问一次，结果集合逐项相同；
  再打开声明所在的模块，从声明处问，集合仍相同。三模块工程的集合里有 lone 的三处。两模块工程另有 `includeDeclaration: false` 一例与「声明模块里的使用处」一例。
- 编辑：把 base 里 `scale` 上方的 `pad` 的函数体拆成两行（导出面不变，lone 的步骤复用），从 main 与从声明处各问一次，`scale` 下移一行，lone 的三处仍在。
- 诊断：会话结束前，服务端从未给 broken.dawn 发过非空诊断。引用程序检查了它，诊断程序没有装它。
- 变异体 5 个，锚点在 `scripts/lsp-references-workspace/mutate.py`，登进 `mutation-anchor-preflight.py` 与 `anchor-readers.txt`：
  只搜打开的文档（`open-documents-only`）、导入列表的名字不解析（`import-list-unresolved`）、重查过的模块留下旧条目（`index-outlives-its-step`）、
  诊断程序装全仓（`diagnostics-load-whole-tree`，broken.dawn 收到诊断）、复用的条目不随编辑平移（`sites-not-moved`）。
  各自从私有 selfhost 副本编译，要求自己那条断言变红。本机正例约 3 s，含五个变异体约 48 s。

**CI 的位置。** 这一步若照 T0、T1、R1 接进 `lsp-workspace`，那个 job 的规划额度是 905 + 2 × 48 = 1001 s，越过 950 s 的 pole。所以这份设计的四个逐名夹具
（T0 的 resolution-coverage、T1 的 semantic-tokens、R1 的 references、R2 的 references-workspace）一起挪进新 job `lsp-references`：
规划额度 2 × (56 + 39 + 55 + 48) + 50 = 446 s，timeout 23 分钟；`lsp-workspace` 回到四步进来之前观测到的 605 s，timeout 31 分钟。
push-total 16,648 → 16,794 s（+146 s：R2 本身 96 s，新 job 的固定开销 50 s）。挪动的三步命令一字不改，`steps.lock.json` 已重录。

### R2.8 不做的（理由）

- **rename**：R3。R2 的集合就是 R3 要改的地方，R3 还要加安全条件与结果自检。
- **全仓诊断**：引用程序里有全仓每个模块的诊断，发出去只是多一步，但那是另一个特性，要回答「关掉的文件的诊断何时清」「几百个文件的诊断一次推多少」，
  而且会把引用程序拉回诊断路径，正是 R2.1 拆开的东西。今天发布的范围与 R1 时逐字相同。
- **两个程序共享步骤**：引用程序里导入闭包那部分与诊断程序检查的是同一批模块，编辑后各查一次被编辑的模块。共享要让一个 session
  从另一个 session 的 carry 接着检查，是 `driver/incremental` 的接口改动；编辑后 330 ms 已在目标之内，等需要时再做。
- **局部量不搜别的模块**：局部量的引用只在它自己的文件里，可以省掉整个工作区的条目检查与引用程序的更新。但判断「这是局部量」要再引一套规则，
  与 R1.8「按局部量裁剪遍历范围」一起等需要时再做。
- **视图缓存**：每个有结果的文件建一次 UTF-16 视图。可以随条目缓存，但它与文本同寿命、占内存，而 200 ms 已在目标之内。
- **没有 manifest 的目录装全目录**：见 R2.1。
- **跨 workspace、跨 source root**：每个 workspace 是一个 (project, source_root) 身份（docs/lsp-workspace-design.md §2.3），各自是一个程序；
  另一个 source root 里的使用不在这个程序里，搜它要先让两个程序共享声明身份。
- **std 内部的引用**：std 不在程序里，它的模块没有条目；std 的声明在用户模块里的使用照样找得到。
- **超过 128 个模块的项目**：`max_modules` 只保留前 128 个步骤，之后的模块每次都重查，它们的条目也就每次重读。selfhost 79 个，离上限还远；
  真有更大的项目时该调的是这个上限，不是索引。
- **跨会话持久化索引**：条目是步骤的派生物，步骤本身不跨会话，索引也不该先跨。

## R3：prepareRename 与 rename

调研 §5.1 的 R3 行与 §3.2、§3.3；裁决第 4、5 条：只改本工程包、source root 下的源码，安全条件以调研 §3.3 的 15 条为准，
结束前对改后文本重分析，出新诊断即拒绝，不自动重排格式。服务端声明 `renameProvider: {prepareProvider: true}`，
两个请求在 `lsp/server.dawn`（`rename_start`、`handle_prepare_rename`、`handle_rename`），纯计算在新模块 `lsp/lsprename.dawn`。

### R3.1 可改的名字与拒绝理由

`prepareRename` 与 `rename` 走同一个入口 `rename_start`：取光标处 `find_target` 的声明（R1 的键），在 R2 的引用程序里找到它，
再逐条检查。可改的是光标所在的那一处 occurrence（R1 的裁剪，`use m.{f as h}` 里光标在 `f` 与在 `h` 是两个名字，限定访问只取成员段），
回复 `{range, placeholder}`，`placeholder` 是它现在的拼写。拒绝时回 `RequestFailed`（-32803）带消息，编辑器直接显示：

| 情形 | 消息要点 | 理由 |
|---|---|---|
| 没有分析、`untitled:` 缓冲区 | rename works in the files of a project | standalone 没有工作区、没有 source root，改名的边界无从谈起 |
| 光标处没有名字，或没有声明（字面量、内建 `len`） | no name here / not declared in this project's sources | 同 definition：无处可跳就无处可改 |
| 声明在 std、内建 prelude、`[deps]` 包 | declared outside this project's sources | 声明模块的 `package_of` 不是 `PkgRoot`，或文件不在 source root 下（`path_in_root`）；裁决第 4 条 |
| 模块名（`use geo`、限定访问的 `geo.`） | a module is renamed by moving its file | 模块改名是移文件，裁决第 5 条不做 |
| 顶层 `main` | the program's entry point | 入口按名字找 |
| 请求模块或声明模块有诊断 | has errors; fix them first | 有错的模块解析不全，引用集合不可信（Roc 的「不能构建就不改」） |
| 两个打开的文档对同一文件说法不同 | disagree about one file | 引用程序本身不成立 |

引用程序一旦建起来，拒绝时也留在 workspace 里：第一次建它要检查全仓（R2.6 的 4 s 量级），不能因为光标落在 std 函数上就每次重付。
`use java` 引入的类与成员没有项目内的声明位置，落在第二行；test 名是字符串，不是名字；语法糖合成的名字没有出现在 occurrence 里，
光标拿不到它们。测试与 `[deps]` 包都是被动拒绝：只要声明不在本包，就没有可改的东西。

**改名导入**：光标在 `use m.{f as h}` 的 `h` 上（或 `h` 的使用处），改的是本模块的局部名：只编辑本模块里拼作 `h` 的 occurrence，
声明与别处都不动（`as_name`）。这时声明在哪个包无所谓，`use std/str.{len as slen}` 的 `slen` 也能改，因为只碰本模块的文本。

### R3.2 15 条安全条件落到哪里

| # | 条件 | 实现 | 夹具 |
|---|---|---|---|
| 1 | 大小写即语义 | `lsprename.check_new_name`：新旧名字各过一遍 `front/lexer`，必须都是单个 `IDENT` 或都是 `TYPEIDENT` | `scale` → `Grow` 拒绝（负例） |
| 2 | 不是硬关键字 | 同上，分出关键字 token 就拒绝；上下文关键字（`with` `in` `as` …）分词是 `IDENT`，放行，靠第 15 条兜底 | `scale` → `match` 拒绝；单测里 `with` 放行 |
| 3 | 遮蔽 std/builtin 改变他处解析 | 第 15 条的解析比对：改后每个名字解析到的声明必须与改前一致 | `count_of` → `len`（模块里调用了内建 `len`）拒绝；另有局部捕获：`scale` → `twice`，`helper` 里的 `twice` 是局部 lambda，改后 `twice(n)` 会被它接住，拒绝 |
| 4 | 模块别名同一命名空间 | 第 15 条的诊断比对（编译器报 shadows the imported module） | `helper` → `str` 拒绝（负例） |
| 5 | 选择性导入冲突、`as` | 冲突靠诊断比对；`as`：只改拼写与旧名相同的 occurrence，经 `as` 绑定的名字保留自己的拼写 | `first` → `lead` 只改导入列表的 `first` 不改 `head`；从 `head` 改只动 `head`；`helper` → `scale`（已导入）拒绝 |
| 6 | 导出面与导入者 | 引用程序装全仓（R2），每个模块的条目按键过滤 | `scale` 的九处：声明、导入列表、调用、限定调用、管道、UFCS、两处文档链接，从调用处与声明处各改一次，结果相同 |
| 7 | `[deps]` 与 std 不可改 | `rename_start` 查声明模块的包与 source root；生成编辑后再逐条查一次 `path_in_root` | `triple`（`[deps]`）、`str.len`（std）在 prepareRename 拒绝 |
| 8 | 记录简写双向 | R1 的收集在简写处给两条解析（字段 `PunUse`、局部量 `PlainUse`），`lspref` 把它们标成 `PunField`/`PunLocal`；改字段写成 `col: x`，改局部量写成 `x: v` | 字段 `x` 在构造与模式里各一处简写；`let y` 被构造简写读；模式简写绑定的 `x` |
| 9 | 具名实参与默认参数 | 形参的引用里本来就有调用处的 `name:`（T0）；默认值表达式按函数体同样遍历（`visit_fn_decl` 读 `Param.default` 与 `TFun.defaults`） | `by` → `factor`：声明、函数体、调用处 `by: 3`；另一个工程里 `fn f(n: Int = len([1]))` 配顶层 `len`，`len` → `count` 必须连默认值里的调用一起改 |
| 10 | trait 方法 | R1 的 `ImplUse`：impl 的方法名是 trait 方法的引用 | `area` → `size`：trait、impl、导入列表、调用 |
| 11 | 效果操作 | T0：调用与 handler 臂名都解析到操作声明 | `ask` → `query`：声明、调用、另一模块的 handler 臂 |
| 12 | 管道与 UFCS | 名字跨度在 `EVar`/`EMethod` 上，与普通调用相同 | 并入第 6 条：`3 \|> scale`、`2.scale()` |
| 13 | 文档链接 | 每个模块的 `##` 文档里的 `` [`…`] ``（`front/docs.doc_link_spans`），**每一段**拼作旧名的，把链接截到这一段为止（`lsprename.link_segments`）用 `driver/doclinks.resolve_link` 在该模块作用域解析，落在同一声明（声明模块相同、名字起点相同）就改这一段；第一版只看末段，改 `Point` 时 `[`Point.x`]` 不动（审计第 12 条） | `[`scale`]`、`[`geo.scale`]`、`[`Point.x`]`；另一个工程里 `[`Pair.a`]` 随 `Pair` 改 |
| 14 | 格式 | 不重排；只出名字本身的编辑（简写展开除外）。触发率在 selfhost 上实测（R3.6） | 无（selfhost 抽样） |
| 15 | 结果自检 | R3.3 | 第 3、4、5 条的负例 |

### R3.3 改后重分析自检

`handle_rename` 算出编辑后，不直接交出去，先在内存里把编辑应用到各文件的文本，用引用程序自己的 `incremental.Session` 和解析记忆
把改后的工作区分析一遍（编辑没碰的模块照常复用步骤；返回的新 session 丢掉，编辑还没生效，不能让引用程序记住它）。两道检查：

1. **诊断**：按文件 identity 数诊断条数，改后哪个文件比改前多，就拒绝，消息带编译器的原文与位置。引用程序装着全仓，
   一个本来就坏的模块（夹具的 broken.dawn）改前改后条数相同，不会挡住与它无关的改名。
2. **解析**：这是第 3 条要的东西，诊断给不了：改名到 `len` 之后模块照样能编译，只是 `len(..)` 换了被调用者。
   对每个**被编辑的模块**以及**改后文本里整词拼出新名字的模块**（`lsprename.spells`），拿改前的索引条目（R2 的 `ModRefs`）与改后整篇遍历的结果比：
   改前每个名字的位置与它指向的声明位置都经编辑前移（`forward`/`forward_key`），被改名的声明移到新拼写，简写展开后两半各归各的；
   两边必须是同一个集合。多出来的（内建调用现在解析到新函数）、少掉的、指向变了的（被局部量捕获），都拒绝，消息给出改后文本里第一处不一致的位置。
   一个从来没拼出新名字的模块不会有名字改为指向它，所以不在比较范围内；改名前就指向旧声明的名字都在被编辑的模块里。

这两道检查都只看得见收集到的名字。第一版的收集不进默认值表达式（2026-10-04 审计第 1 条）：`fn f(n: Int = len([1]))` 里的 `len`
既不在改前索引也不在改后遍历里，把顶层 `len` 改成 `count` 后那处调用落到内建 `len`，`RESULT` 从 99 变成 1，两道检查都放行。
所以合约（`scripts/lsp-rename.py`）在两道检查之外再加一道它自己的：每个被接受的改名都应用到工程副本上（编辑区间从起点读到**终点所在的行**），
`dawn run` 的输出必须与改前相同。

这比 gopls 那样按作用域种类逐条写冲突规则少很多：遮蔽、捕获、导入丢失都是「某个名字指向的声明变了」，一条比较就覆盖，
而且与 references 用的是同一份解析，不会出现「references 认为是同一个、rename 认为不是」。代价是一次改后分析与几次遍历（R3.7）。

### R3.4 回复的形状

`WorkspaceEdit` 只用 `changes`（URI → `TextEdit[]`），不用 `documentChanges`：编辑都是名字替换，没有建文件、改文件名，
`changes` 每个客户端都支持。URI 照 R2：文件有打开的文档就用那个文档的 URI，否则 `path_to_uri(identity)`。区间按改前文本换算成 UTF-16。
同一起点只出一条编辑（记录类型与它同名的构造器共用一个位置）。新名字与旧名字相同时回空的 `changes`。

服务端不应用编辑、不改磁盘，客户端应用后会照常发 `didChange`，没打开的文件客户端会自己打开或改盘；之后的分析从那里接着走。

### R3.5 Playground

网关不转发 prepareRename 与 rename（`playground/lsp_gateway.py` 的白名单不变），与 R1、R2 一样：Playground 的文档是 `untitled:` 缓冲区，
在服务端是 standalone，R3.1 第一行本来就拒绝。

### R3.6 selfhost 抽样与格式触发率

验收：对 selfhost 随机抽 20 个 `pub fn`（`random.Random(20261004)`，候选是 `selfhost/src` 下除 `embed/`（生成物，不许手改）外所有行首的 `pub fn`，共 513 个，排序后 `sample(…, 20)`），
每个改名为原名加 `_rn`。一个 LSP 会话开在 selfhost 的副本上，逐个在声明处发 rename；每个回复应用到一份新副本，
跑 `dawn check selfhost` 与 `dawn fmt selfhost --check`。

结果：20 个全部被接受，20 个改后 `dawn check` 全部 ok；共 430 处编辑、84 个文件次；**`fmt --check` 触发 0 次**（改前副本 `fmt --check` 也是干净的）。
最多的 `front/ast.e_hi` 一次 124 处、7 个文件，`check/types.prelude_adts` 49 处、11 个文件。名字变长 3 个字符没有碰到任何对齐：
dawn fmt 只规范 token 之间的空白与按括号层次的缩进，保留作者的换行，不按列对齐（`front/fmt.dawn` 文件头），
改一个名字的长度不改变它对任何一行的判断；简写展开写出的 `col: x` 本来就是 fmt 的间距。所以第 14 条在本仓的实际触发率是 0/20，
调研担心的「对齐被改名打破」在今天的 fmt 下不存在，rename 不重排格式没有代价。

### R3.7 性能（本机实测）

selfhost 工作区，JVM（`./bin/dawn lsp`），打开 `check/types.dawn`，第一次 references 建引用程序（约 6 s，同 R2.6 的 4.1 s 量级，本机 load average 约 4）后，
prepareRename、rename、references 交错各 9 轮，丢前 2 轮取中位数：

| 目标 | 编辑 | prepareRename | rename（含自检） | references |
|---|---|---|---|---|
| `adt_of`（`pub fn`，21 个文件 130 处） | 130 处 | 40 ms | 3.6 s | 231 ms |
| `union_has`（私有函数，8 处） | 8 处 | 42 ms | 1.1 s | 44 ms |
| `union_has` 的形参 `vs`（2 处，改名为常见的 `xs`） | 2 处 | 40 ms | 1.3 s | 44 ms |

在一份插了计时的副本上拆开（每轮）：

| 阶段 | `adt_of` | `union_has` |
|---|---|---|
| 全部模块的条目（多数是 R2 的平移） | 120–160 ms | 120–170 ms |
| 改后重分析 | 1.4–2.0 s | 0.8–1.2 s |
| 诊断比较 | ≈ 0 | ≈ 0 |
| 解析比较（改后遍历） | 1.4–1.9 s | 90–140 ms |

大头是改后重分析与改后遍历。`adt_of` 的签名名字变了，导入 types.dawn 的模块的步骤都不能复用，重分析接近整仓重查；
它被 21 个文件引用，这 21 个文件都要整篇遍历一次。私有函数只重查 types.dawn 自己，但重分析里还有一次重新装载全仓的文本与解析（解析记忆命中），
所以下限在 0.8 s 左右。形参改成 `xs` 时，整词拼出 `xs` 的模块多（R3.3 的筛选），解析比较那一段比私有函数多一些。
rename 是一次性的用户操作，3.6 s 对 130 处跨 21 个文件的改名可以接受；prepareRename 只走 `rename_start`，40 ms，不碍事。

**2026-10-04 审计后。** 第 13 条（自检的二次复杂度）：`changed_name` 对每个改前名字都要把它与它指向的声明经编辑前移，
`forward` 每次扫一遍这个文件的全部编辑、`edit_at` 再扫一遍，一个被调用 R 次的函数就是 O(R × E)。现在 `lsprename.edit_index`
对每个文件的编辑建一次索引（按起点的表、按顺序的终点与累计增量），`forward` 二分，`changed_name` 里同一个声明键只前移一次。
一个两声明工程，`main` 里 N 次 `let _ = helper()`，`helper` → `grow`，暖后 7 轮丢前 2 轮取中位数（本机，同一台机器同一时段）：

| N | 修前 | 修后 |
|---|---|---|
| 1,000 | 133 ms | 53 ms |
| 2,000 | 374 ms | 92 ms |
| 4,000 | 1,108 ms | 183 ms |

修前每翻一倍约 ×3，修后约 ×2，剩下的是改后重分析与遍历，本来就与名字数成正比。

### R3.8 行为变化与 Emit-Change

`selfhost-lsp-diff.sh` 的会话在 R2 那条跨文件 references 之后加一次 prepareRename 与一次 rename（`pad_to` → `pad_out`，跨 inlays.dawn 与 util.dawn）。
用真父（`9b3f3e7f` 编出的服务端，`DAWN_STD` 指本仓 std）逐消息对照，137 条消息里三条不同：initialize 多了 `renameProvider`，
两个新请求真父回 MethodNotFound。其余逐字相同。提交里写一行 `Emit-Change(lsp)`。

`lspref` 的 `Occurrence` 与 `Ref` 多了 `pun` 字段，references 与 documentHighlight 的回复不读它，R1、R2 的夹具不变。

### R3.9 门禁

`scripts/lsp-rename.py`（第二版，2026-10-04 审计后）另有四个工程：默认参数（审计第 1 条）、磁盘上的改动（第 2、3 条，通知与不通知各一个会话）、
覆盖面（第 4–12、15 条各一例：非 ASCII 名字、与 `as` 同拼写的限定调用、常量的 `as` 名字、投影的主体、关联效果绑定、以声明命名的测试标题与四反引号围栏里的链接、
trait 默认方法的形参、点后带空白的限定类型、类型形参列表里的注释、文档链接的 owner）。每个被接受的改名都应用到工程副本上 `dawn run`，输出必须与改前相同；
编辑区间从起点读到终点所在的行（第 14 条）。变异体从 7 个加到 22 个，两个编译器并行构建。

第一版：`scripts/lsp-rename.py`：一个带 `[deps]` 路径包的工程（geo、main、一个有类型错误的 broken），一个会话，24 个断言：
initialize 的能力；prepareRename 的区间与 placeholder；R3.2 表里每条条件的正例或负例；R3.1 的拒绝。编辑按 `文件 行:列 旧 -> 新` 逐条比，拒绝按消息全文比。
变异体 7 个，锚点在 `scripts/lsp-rename/mutate.py`，登进 `mutation-anchor-preflight.py` 与 `anchor-readers.txt`：
不查大小写类（`case-class-unchecked`，消息变成编译器的）、解析比对拿改后比改后（`resolutions-unchecked`，`len` 那例放行）、
不看诊断（`diagnostics-unchecked`）、简写不展开（`puns-not-spelled-out`）、`as` 名字跟着改（`as-names-renamed`）、
不改文档链接（`doc-links-skipped`）、不查声明的包（`dependencies-renamed`，`triple` 的 prepareRename 放行）。各自从私有 selfhost 副本编译，要求自己那条断言变红。
本机正例约 1.3 s，含七个变异体约 63 s（load average 约 4；本机另有写者时 load 12 到 15，同一命令 91 到 110 s）。

**CI 的位置**：接进 R2 时新建的 `lsp-references` job（四个逐名夹具已在那里）。规划额度 446 + 2 × 63 = 572 s，timeout 29 分钟，仍在 950 s 的 pole 之下；
push-total 16,794 → 16,920 s（+126 s）。`steps.lock.json` 已重录。

### R3.10 不做的（理由）

- **delta、模块改名、跨包 rename、rename 时重排格式、gopls 式默认关、rust-analyzer 式先文本搜索、codeLens**：裁决第 5 条，理由见调研 §5.2。
- **简写收回**：改名后两半重新同名（`{ x: y }` 把 `y` 改成 `x`）时可以收回成 `{ x }`。收回是格式上的选择，与「不重排格式」同一个理由；`{ x: x }` 照样合法。
- **standalone 缓冲区里改名**：没有 source root，「只改本工程源码」无从判断；Playground 不转发。
- **有错的模块里改名**：R3.1。解析不全时引用集合会漏，漏改比拒绝更糟。
- **改名导入的局部名在别的模块的连锁**：`as` 的局部名只在本模块可见，不存在连锁。
- **上下文关键字的提示**：调研建议放行但在 prepareRename 的消息里提示。prepareRename 不知道新名字，提示只能是泛泛的一句；真出问题时第 15 条会拒绝，并带编译器的原文。
- **改后文档链接再解析一次**：链接只在 `dawn doc` 里读；改的是末段且只在旧链接确实落在被改声明上时才改，改后 `dawn doc` 会照常解析它。
- **自检的结果缓存**：改后分析的 session 不保留。保留它要在客户端真的应用了这份编辑之后才对，服务端不知道客户端何时、是否应用。
