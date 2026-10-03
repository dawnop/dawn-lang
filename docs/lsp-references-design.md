# LSP 引用与改名：T0 解析覆盖

> 状态：**current**：T0 于 2026-10-04 落地，分支 `feat/lsp-resolution-coverage`（提交以主题引用，合入后的哈希记在进度记录里）。
> 依据：裁决 `agent-handoff/ruling-lsp-tokens-rename-20261003.md`，调研 `agent-handoff/research-lsp-tokens-rename-report-20261003.md`
> （§1.4 空洞实测表、§3.4、§5.1 刀序）。本文只写 T0；T1（semantic tokens）与 R1–R3（references、rename）各自动码前在此续写。

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
