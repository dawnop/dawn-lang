# LSP 引用与改名：T0 解析覆盖

> 状态：**current**：T0 于 2026-10-04 落地，分支 `feat/lsp-resolution-coverage`（提交以主题引用，合入后的哈希记在进度记录里）；
> T1（semantic tokens 服务端，§T1）同日落地，分支 `feat/lsp-semantic-tokens`。
> 依据：裁决 `agent-handoff/ruling-lsp-tokens-rename-20261003.md`，调研 `agent-handoff/research-lsp-tokens-rename-report-20261003.md`
> （§1.4 空洞实测表、§2、§3.4、§5.1 刀序）。前六节写 T0，§T1 写 T1；R1–R3（references、rename）各自动码前在此续写。

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

### T1.7 门禁

`scripts/lsp-semantic-tokens.py`，接在 `lsp-workspace` job（T0 那一步之后）：

- 正例：T0 夹具的两份程序（单文件改了一行，加进一个字符串里有两个 BMP 以外字符、后面跟着名字的 `let`），`full` 回复按 UTF-16 解码成
  （文本，类型，修饰）后与期望序列逐项相等（单文件 133 个，两模块 69 个）；两个 range（`norm` 体内两行；BMP 以外字符那一行的后半段）逐项相等；
  legend 有 `full`、`range`、没有 `delta`；未打开的文档回 `{"data": []}`。
- 变异体 4 个，锚点在 `scripts/lsp-semantic-tokens/mutate.py`，登进 `mutation-anchor-preflight.py` 的登记表，构建前先证明每个锚点恰好命中一次：
  常量退回 `type`（种类映射错）、`var` 丢 `mutable`、range 不裁剪、列按 UTF-8 字节算。各自从私有 selfhost 副本编译，要求自己那条断言变红。
- 本机墙钟：正例约 3 s，含四个变异体约 39 s。`lsp-workspace` 的规划额度 717 → 795 s，timeout 36 → 40 分钟，push-total 16,460 → 16,538 s。

### T1.8 不做的（理由）

- **delta**：成本在遍历不在载荷（T1.5 里 full 的大头是遍历），要多一份按 URI 的缓存与 `resultId`；裁决第 3 条。
- **关键字、字面量、注释、运算符的 token**：语法高亮已经做对，再发会撞 Playground 的单条上限，也会让服务端未就绪时颜色闪动；裁决第 3 条。
- **自定义类型 `effect` 与修饰 `effect`**（调研 §2.2 的建议）：要客户端登记才有颜色，VS Code 侧是 T2 的事；先用标准名，效果与 trait 同为 `interface`、
  操作与 trait 方法同为 `method`。T2 若要区分，加一个自定义修饰即可，类型下标不动。
- **`modification` 修饰（赋值目标）**：`acc = acc + 1` 左边的 `acc` 现在只是 `mutable`。标准名有，但要遍历区分读写，留到 R1（documentHighlight 的读/写种类要的正是它）。
- **内建类型、内建函数的 token**：没有声明可落，分类无从读；TextMate 按大小写已经涂对。
- **开关**：token 来自已经算好的分析，请求时只是一次遍历；分析未就绪回空，语法高亮不受影响。裁决第 3 条。
