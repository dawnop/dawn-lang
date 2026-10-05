# 源码位置：路径规范、panic 位置与 `dbg`

> 状态：**current**（L1、L2、L3、L4 已落地；L4 的设计与落地记录在 [caller-location-design.md](caller-location-design.md)）。2026-10-03：L1 分支 `fix/source-position-paths`，关 #401；
> L2 分支 `feat/panic-call-site`，关 #396（第五节）；L3 分支 `feat/dbg-builtin`（第六节）。
> 依据：裁决 `agent-handoff/ruling-source-location-20261003.md`，调研 `agent-handoff/research-debug-print-report-20261003.md`
> （仓库行号指 `9fb834d0`，外部出处抓取于 2026-10-03）。本文是那份调研 §一至§三的压缩，加上 L1 的落地说明。

## 一、现状

### 1.1 位置今天从哪里来

全语言唯一带源码位置的运行期失败是 `e!`：消息由 checker 写（`unwrapped None from f()`），
位置由 `check/tast_positions.dawn` 在**声明出口**补上（`site`，`XUnwrap` 臂），形如 `at <path>:<line>`。
在声明出口补而不是在 checker 里当场写，是因为 TAST 的 span 在检查期间是相对声明的偏移，
函数体会被跨模块复用，只有声明出口那一刻基址唯一；声明只是移动时，位置跟着移动后的行走。

lower、两个后端、comptime 解释器都只把这条消息当普通字符串：**位置是 Core 里的一个字符串常量**，
后端看不到「位置」这个概念。Core 本身没有 span，这是既有裁决（`docs/native-backend-plan.md`
「保持 Core 无 span 是有意的」；审计文 03 的 Core golden 判据）。

`panic`、`todo`、`assert` 在 L2 之前都**不带位置**（L2 之后见第五节）；std 的 `Cx` 没有 `src_path`，std 里的 `!` 也不带位置。

### 1.2 缺陷：烘进产物的是命令行上的原样路径（#401）

修前，`site` 用的是 `Cx.src_path`，也就是 `driver/analyze.dawn` 从命令行一路传下来的原样路径
（`cx_new(Some(mf.class_name), Some(mf.path))`，`cx.dawn` 自己的测试就写着它未规范化）。实测（修前的 HEAD 工具链）：

| 调用 | 打印 |
|---|---|
| 项目目录里 `dawn run .` | `panic: unwrapped None from f() at ./src/main.dawn:4` |
| 上级目录 `dawn run proj` | `panic: unwrapped None from f() at proj/src/main.dawn:4` |
| `dawn run /abs/.../sub/p.dawn` | `panic: unwrapped None from f() at /abs/.../sub/p.dawn:4` |

三个后果：

1. **不可复现**：同一份源码从两个目录 `dawn build`，jar 逐字节不同（实测 `cmp` 报第 64728 字节起不同）。
2. **绝对路径外泄**进产物（用户名、构建机目录）。
3. **Playground 外泄服务器路径**：`playground/src/play/exec.dawn` 只对编译诊断做 `strip_dir`，运行阶段输出原样返回，
   而源文件在 `${PLAY_WORK_ROOT}/dawn-play-<uuid>/prog.dawn`。本地 runner 实测见第四节。

Swift 把同一件事做成了一个提案（SE-0274，`#file` 改为 `#fileID` = `模块/文件名`），列的三条理由与上面逐条对应：
泄露用户名与构建机路径、二进制体积、不可复现构建。GCC 的 `-ffile-prefix-map` 是 C 世界对同一病的补丁
（「make reproducible builds that are location independent」）。

## 二、他山之石（压缩）

| 语言 | 位置机制 | 要点 |
|---|---|---|
| Rust `dbg!` | 宏，编译期 `file!/line!/column!` | `[src/main.rs:2:9] a * 2 = 4`，stderr，返回原值；release 不剥 |
| Rust `#[track_caller]` | 隐式参数 | 不进类型；转成函数指针就退化为定义点 |
| Zig `@src()` | 编译期内建 | 返回文件、函数、行、列 |
| Swift `#fileID`/`#line` | 魔法字面量，作默认参数时在调用点求值 | SE-0274：全路径的隐私、体积、可复现三病 |
| OCaml `__LOC__` 等 | 编译器原语 | `__LOC_OF__ e` 返回 `(loc, e)` |
| Haskell `Debug.Trace` / `HasCallStack` | 类型纯而实际输出；隐式调用栈参数 | 「should only be used for debugging」 |
| Gleam `echo` | 关键字 | 发布包时拦遗留的 `echo` |
| Go `runtime.Caller` / JVM 栈 | 运行期查 PC 或抓栈 | 只有这两家在运行期查 |

可借用的结论：位置是编译期常量是主流；返回原值、写 stderr 是共识；路径要规范化（Swift 专门立案）；
调用者位置的通用能力有隐式参数（Rust、Haskell）和显式默认参数（Swift）两种形状。

## 三、方案与刀序

### 3.1 三个候选

- **(a) 编译期按调用点 span 填常量**（采纳）。走 `tast_positions` 现成的缝，lower、后端、解释器零改动。
  代价是带行号的字面量进 Core，Core golden 随位置变化（L2 裁归一）。
- **(b) 调用者位置作默认参数**（采纳为第二阶段，L4）。`at: Loc = caller()`，让 `expect` 一类库函数报**调用者**的行。
  转传显式；丢失规则就是现有的「函数当值用丢默认值」。
- **(c) 运行期栈 + 行号表**（不做）。要给 Core 加 span，推翻既有裁决；emit 语料与 Core golden 从此随行号漂移；
  native 要 unwinder 与符号化，wasm32-wasi 没有平台 unwinder；自尾调用转循环与 cc 内联吃帧，TCO 下的栈不可信。

### 3.2 `dbg` 的形态（L3）

内建 `dbg[T: Show](x: T) -> T`，返回原值，写 stderr，格式 `[<path>:<line>:<col>] <表达式源码> = <show(x)>`。
类型为纯、语义为恒等：stderr 那一行是诊断旁路，不属于程序语义，全语言只此一个特例，spec 点名。
comptime 中恒等、不打印。`[deps]` 加载的模块与 std 里出现 `dbg` 是编译错误；本仓五个目录另由门禁禁止。
表达式源码取自调用点原文；落地时没有用这里原先设想的 parser 边表，理由见 6.2。

### 3.3 刀序

| 刀 | 内容 | spec | 关联 |
|---|---|---|---|
| **L1**（已落地） | 位置路径规范；Playground 运行输出 `strip_dir`；两个 cwd 构建字节相同的负控 | 否 | 关 #401 |
| **L2**（已落地，第五节） | `panic`/`todo`/`assert` 带调用点位置（`site` 加列）；Core golden 对位置后缀归一；两后端各一测 | §8.2 删「Dawn 层栈迹」，改为 `panic: <msg> at <path>:<line>:<col>` | 关 #396 |
| **L3**（已落地，第六节） | `dbg` 内建 + `dbg_line` intrinsic；`[deps]`/std 拒绝；仓内门禁；comptime 恒等 | 新增 §8.3 | |
| **L4**（已落地，[caller-location-design.md](caller-location-design.md)） | `caller()` 默认参数 + `Loc`（std/loc）；`panic`/`todo`/`expect` 签名加 `at` | 新增 §8.4 | |

## 四、L1：位置路径规范

### 4.1 规则

烘进产物的位置串用**展示路径**（`Cx.site_path`），诊断渲染仍用原样的 `src_path`：

| 模块从哪来 | 展示路径 | 例 |
|---|---|---|
| 项目模式（源根是 `<项目>/src`；单文件但有 `src` 祖先目录也属此类） | 相对项目根 | `src/main.dawn`、`src/net/http.dawn` |
| 单文件模式（没有 `src` 祖先，源根是入口文件所在目录） | 相对入口文件所在目录 | `p.dawn`，Playground 的 `prog.dawn` |
| `[deps]` 包的模块 | `<包名>/<包内相对路径>` | `json/parse.dawn` |
| 内嵌 std | 无（`None`，与修前相同） | |
| 编辑器单缓冲区（`analyze_standalone`） | 文件名 | `scratch.dawn` |

理由：

- **只取决于源码树本身**。展示路径由模块路径推出（模块路径已经是「相对源根」的规范答案，类名就是它），
  不读 cwd、不读命令行拼法，所以同一棵树从哪里、用什么拼法构建都得到同一个串，产物逐字节相同。
  这就是 SE-0274 的可复现论证：位置串是产物的一部分，产物不应依赖构建机。
- **不外泄**：任何一条规则都不产生绝对路径或 `..`。
- **仍然可点**：项目模式下 `src/main.dawn:4` 在项目根打开的终端与编辑器里就是对的路径；单文件模式下在入口目录里是对的。
- **`[deps]` 用包名而不是缓存路径**：包的缓存目录按内容哈希命名，与用户无关；`<包名>/<路径>` 与模块路径
  （`json/parse`）同形，读者一眼知道是哪个包，Swift `#fileID` 的 `模块/文件` 是同一个思路。
- **诊断不改**：终端里 `--> ./src/main.dawn:3:4` 这样 cwd 相对的路径本来就对（用户就在那个 cwd），而且不进产物。
  `LocDiag.path`、`ModExports.src_path`（「previous impl in ...」）都保持原样。
- **std 维持 None**：L4 之后 std 的失败报调用者位置；std 自己的路径对用户没有价值。

### 4.2 落点

- `driver/analyze.dawn`：`LoadedModule` 加 `site_path`，由加载器在知道源根的地方算（`resolve` 的种子与 `use` 边、
  `analyze_standalone`）；`analyze_module_step` 把它交给 `Cx.site_path`，std 模块给 `None`。
- `check/cx.dawn`：`Cx.site_path`；`cx_new` 让它默认等于 `src_path`，只服务手搭 `Cx` 的测试，生产调用方都覆盖它
  （与 `is_std_module` 的「提议 / 覆盖」同一个模式）。
- `check/checker.dawn`：`tast_positions.owned/unowned` 的 `path` 实参改读 `cx.site_path`。
- lower、两个后端、解释器：零改动。

### 4.3 负控

- `selfhost/src/main.dawn` 的两条测试：同一个项目放进内存文件系统，工作目录分别是项目目录、它的上级和一个无关目录
  （`memfs.empty(cwd)` 与 `envmem.with_env_table(cwd)` 一起换），以 `.`、`proj`、绝对路径为目标跑真正的 `__emit`，
  逐个 class 文件比字节，且含 `at src/main.dawn:4`；单文件以绝对路径和入口目录内的相对路径各跑一次，字节相同，消息是 `at p.dawn:4`，
  不含绝对路径。把 checker 改回读 `src_path` 时这两条红。
- CLI 层：本地两个 cwd 各 `dawn build` 一次，`cmp` 相同（修前第 64728 字节起不同），数字记在 L1 报告里。

### 4.4 Playground

- 编译器修好之后，单文件模式下运行输出本来就是 `prog.dawn:N`。
- `exec.dawn` 对运行阶段输出也套 `strip_dir`，作纵深防御：运行期消息里任何指向暂存目录下文件的路径，或暂存目录本身
  （后者换成 `.`），都不会把 work root 交给浏览器。实测：本分支 runner 配修前的编译器，同一个失败的 `x!` 也答 `at prog.dawn:2`。
- `playground/test/contract.sh` 把 work root 设成测试自己的临时目录，跑一个必然 `x!` 失败的程序，断言输出含
  `prog.dawn:` 且不含 work root。
- 顺带：tooltip 的 `docText` 把未改写的 `` [`x`] ``（std 内嵌、hover 链接没有目标可改写时）也还原成 `` `x` ``。

### 4.5 差分

位置串变了的只有含 `e!` 的非 std 模块。对真父提交的编译器实测：`emit selfhost`（Core 里 4 处字面量）、`emit playground`（它的 `web` 依赖，修前是绝对路径）、
`emit packages/web`、`emit examples/interop/interop.dawn` 变，其余 emit 语料、run-diff 转写与 LSP 会话不变。每个动了的 label 一行 `Emit-Change`。

## 五、L2：失败带调用点位置

### 5.1 规则

| 失败 | 消息 | 位置指向 |
|---|---|---|
| `panic(m)` | `<m> at <path>:<line>:<col>` | `panic` 这个名字 |
| `todo()` | `not yet implemented at <path>:<line>:<col>` | `todo` |
| `expect(o, m)` / `o.expect(m)` | `<m> at …` | 调用表达式的起点：函数式是 `expect`，方法式是 `o` |
| `o!` | `unwrapped None from f() at …`（L1 起已有位置，本刀加列） | `o` 的起点 |
| `assert e`（只在 test 块） | `assertion failed: <e 的源文本> at …` | `assert` 关键字 |

- 未捕获时两后端都打印 `panic: <消息>`，所以是 `panic: boom at src/main.dawn:4:3`。
- 行、列从 1 起，列按**码点**计，与诊断箭头 `--> path:line:col` 是同一把尺子（`front/diag.dawn` 的 `snippet`）。
  实现上与 `line_at` 共用行表：`tast_positions.line_col`。
- 位置是消息的一部分：`catch_panic` 得到的 `ForeignError.message` 带它（调研 §3.5 已裁「拼进消息，不做独立字段」）。
- **std 里的失败不带位置**（std 的 `site_path` 是 None，与 L1 同一条规则），形状与修前逐字节相同：`todo` 仍是 `todo` intrinsic，
  后端给它的固定文案不变。L4 之后 std 的失败报调用者的行。
- 把 `panic`/`todo`/`expect` 当函数值用（`let f = panic`）时，经值调用**不带位置**：位置属于调用点，函数值没有调用点。
  这与「函数当值用丢默认值」是同一个丢失规则。（L4 之后 `at` 是普通形参，经值调用必须给一个 `Loc`，见 caller-location-design 3.5。）
- 编译器自己（selfhost 是普通项目）的 panic 从此也带 `src/<模块>.dawn:L:C`，内部错误报告因此能直接定位。

**`x!` 同刀加列**：一致性是唯一理由，也足够。spec §8.2 给出一个格式 `at <path>:<line>:<col>`，若 `!` 独留
`at path:line`，读者就得记住「哪种失败有列」，而 grep 位置、编辑器点击跳转的工具也得认两种形状。
列的代价为零（同一个行表、同一个 resolver），而 `!` 恰恰是一行里最常连写的（`a()!.b()!`），一行多个调用点时只有列能分清是哪一个。

### 5.2 落点

- `check/tast_positions.dawn`：`site` 加列（`line_col`）；`XCallBuiltin` 臂对 `panic`/`todo`/`expect` 在**作者写的实参之后**
  追加一个 `XStr(site)`（`sited_call`），`TSAssert` 臂把 site 接在断言源文本后面。`split_site` 是把它取下的唯一入口。
  按实参个数判别（`panic` 1、`todo` 0、`expect` 2，多一个才是带位置的），所以同一棵树解析两遍也不会带两次位置。
- `ir/lower.dawn`：`XCallBuiltin` 臂最先调 `unsite`，把位置并进消息后按普通调用降低：字面量消息并成**一个** `CStr`
  （Core 里仍是一个常量，热路径上的 `expect("…")` 不多一次拼接），非字面量消息是 `msg ++ " at …"`；带位置的 `todo()`
  降成 `panic("not yet implemented at …")`。
- `lsp/lspq.dawn`：两处把作者实参与类型化实参配对的地方先 `split_site`，悬停、签名帮助看到的仍是作者写的形状。
- **零改动**：Core 结构、两个后端（`jvm/emit.dawn`、`c/emitc.dawn`）、解释器（`ir/interp.dawn`）、运行时。

为什么是「多一个实参」而不是在 `tast_positions` 里直接把消息改写成 `msg ++ site`：类型化树也是 LSP 遍历的对象，它按位置把
AST 实参与 TAST 实参配对（`walk_call_args` 要求个数相等）。消息节点一旦变形，悬停在 `panic("bad ${x}")` 的 `x` 上就拿不到类型。
多一个尾随实参让作者写的每个节点保持原样，只需在两个配对点剥掉。为什么不让后端去拼：违背「语言只说 primitive，后端只管映射」，
而且要在三个地方（两个后端加解释器）各实现一遍。

### 5.3 comptime

位置在降低之前就进了消息，解释器跑的是降低后的 Core，所以 comptime 的失败与运行期逐字相同：
`comptime: panicked: too big at src/m.dawn:1:34`。在源码顺序上**晚于**引用它的常量声明的函数也一样（它的声明出口在被解释之前已经过了）。
钉在 `ir/interp_test.dawn` 的「a comptime failure names its call site」。

### 5.4 Core golden 归一

裁决：「纯移动不应动 golden」。L2 之后，selfhost 每个 panic 调用点的消息都是带行列的 Core 字符串常量，
不归一的话，在一个模块顶上加一行注释就会让该模块的 Core dump 变。`scripts/selfhost-core-diff.sh` 在比较前把两侧 dump 里的
` at <file>.dawn:<n>:<n>` 换成 ` at <file>.dawn:<line>:<col>`（无列的旧形状换成 `:<line>`，以便基线是 L2 之前的版本时也能比）。
**路径保留**：模块换了文件是新闻。`--raw` 关掉归一，`--out` 永远保存原样 dump。负控与实测见 L2 报告。

### 5.5 测试与负控

- 两后端：`scripts/spike-native/panic_site.dawn`（`panic` 字面量 / 插值 / 传入的消息、`todo`、`expect`、`!`、码点列，
  最后一个不捕获）。`.expect` 手写、两后端都对它比；`stderr` 与 `exit` 两后端互比。
- 单元：`tast_positions` 的行列、尾随实参、二次解析不重复、std 不带、`assert` 文本；`interp_test` 的 comptime 文案。
- 负控：`panic_site.expect` 里一个列号加一，两后端的 `jvm`、`native` 检查都红；`sited_arity` 去掉 `todo`，
  `panic_site` 两后端都红（`not yet implemented` 没了位置），`dawn test selfhost` 818 条里红 2 条（尾随实参与 comptime 文案两测）。
- 现有断言消息全文的测试改为断言「消息 + ` at `」前缀（`web`、`tea-core`、`tea-dom`、编译器自己的三处）或写出完整位置
  （单文件的示例与契约探针，位置是固定的）。

### 5.6 差分

消息里多了位置，凡是含非 std 失败调用点的产物都变。以真父提交 `2117a241` 编出的工具链做不被遮的对照（同一份源码、同一份 std）：
十个 `emit *` 语料全变（每个都有 `assert`、`expect`、`!` 或 `panic`，`__emit` 连 test 块一起编），`strings` 比对差异只在消息串；
run-diff 只有 `test playground (with [deps])`（`web` 的测试改为断言带位置的消息，旧编译器编出来会红）与 `test failing fixture`
（失败断言多了 ` at failing.dawn:8:3`）两个转写变；LSP 108 条消息一致。逐 label 的 `Emit-Change` 在提交正文。

## 六、L3：`dbg`

### 6.1 规则

`dbg[T: Show](x: T) -> T` 原样返回 `x`，向 stderr 写一行 `[<path>:<line>:<col>] <实参文本> = <show(x)>`（spec §8.3）。

- **类型为纯、语义为恒等**：那一行是诊断旁路，不进效果行。spec §6.2 规则 4（纯函数保证）点名它是唯一例外。
- 位置与 L2 同一把尺子（`tast_positions.line_col`，码点列），指向调用的起点：`dbg(e)` 是 `dbg` 这个名字，
  `e |> dbg` 是 `e` 的起点（管道在 parser 里就是参数插入，调用的起点即左边的起点）。
- 渲染用 `Show` 而不是 `to_string`：字符串带引号，`dbg("a")` 写 `"a" = "a"`，与 Rust `dbg!` 用 `Debug` 同理。
  没有 `Show` 的类型照常报 `no impl of `Show` for `P``。
- **只能调用**：`let f = dbg` 是编译错误（`` `dbg` cannot be used as a value ``，提示包一层 lambda）。
  函数值没有调用点也没有实参文本；若放行，checker 对带约束的 builtin 做的 eta 展开会造出一个以 lambda 为调用点、
  以形参名为文本的 `dbg`，打印出来的是读者没写过的东西。
- 用户自己定义的 `fn dbg` 照常遮蔽内建（spec §10.6），遮蔽后的调用与本节无关，`[deps]` 里也不拒绝。

### 6.2 实参文本

**取法**：在声明出口（`tast_positions`，L2 的同一个缝）按实参的类型化 span 从**当前修订的源码**切片。
`Cx` 为此多一个 `source` 字段（驱动在设 `line_starts` 的同一处设它），`Resolver` 随之带上源码。

为什么不用第三节原先设想的 parser 边表 `Map[实参 lo, 源码切片]`：

- 位置本来就在声明出口才解析，文本与它取自同一修订、同一时刻，不需要第二条从 parser 到 checker 的通道，
  `Module` 也不必多一个字段。
- 边表要 parser 按名字 `dbg` 记录，再由 checker 判断名字是否解析到内建；而 `XCallBuiltin("dbg", ..)` 只有在名字
  **已经**解析到内建时才存在，遮蔽、管道（parser 把 `x |> dbg` 改写成 `dbg(x)`，边表要另认一种形状）都不需要特判。
- LSP 复用类型化树时，声明只是移动的话文本不变、位置跟着移动，与 L2 的位置同一个论证。

**多行实参**：原文照取，只把跨过换行的一段空白折成一个空格，紧挨 `(`/`[` 之后或 `)`/`]` 之前的则去掉。
于是 `twice(\n    a +\n      1)` 写作 `twice(a + 1)`，竖排管道 `xs\n    |> len\n    |> inc` 写作 `xs |> len |> inc`。
一行之内的空白原样保留（`xs |>  len` 不归一），注释也原样保留：这是作者的原文，不是排版器的猜测；
做到 Rust `stringify!` 那样按 token 重排就是反打印，第三节已否。`{`/`}` 内侧不去空格，因为 `P {\n x: 1\n}`
折成 `P { x: 1 }` 才是 Dawn 的写法。

### 6.3 降低与后端

- `tast_positions`：`sited_arity` 加 `dbg`（1 个实参），`sited_call` 对它追加的尾随 `XStr` 是行头
  `"[<path>:<l>:<c>] <文本> = "` 而不是失败后缀；`split_site` 不变，LSP 的两处配对因此不用改。
- `lower`（`lower_dbg`，在 `unsite` 之前处理，因为行头不是要并进消息的后缀）：

  ```
  { let t = x; dbg_line("[src/m.dawn:4:11] x + 1 = " ++ show(t)); t }
  ```

  `show` 对类型变量走调用点解出的 `Show` 见证（泛型函数里 `dbg(v)` 渲染实参的实际类型）。
- `dbg_line` 是**降低自己的** intrinsic（`lower.internal_intrinsics`），不是 builtin：没有任何源码能写出一个不带效果行、
  直接写 stderr 的调用，除了经过 checker 审过调用点的 `dbg`。它在 `inline_intrinsics` 里：JVM 后端一个臂调
  io 运行时的 `io_eprintln`（经 `rt_intrinsic_ref`，不另造运行时方法），native 后端一个臂调 `dawn_io_eprintln`。
  两个运行时都零改动。
- **wasm**：wasm32-wasi 与 native 用同一个 `emitc` 与同一份 `dawn_rt.c`，stderr 是 WASI 的 fd 2。
  实测 `dawnc build --target wasm` 编 spike-native 的 `dbg_line.dawn`，node WASI 下 stdout 与 stderr 都与两份期望逐字节相同。
- `dbg` 本身进 `lowered_intrinsics`（没有后端看得到它的名字）。

### 6.4 只属于正在调试的程序

- checker（`check_call`）：调用点解析到内建 `dbg` 时，若 `cx.is_std_module` 报 `` `dbg` cannot be used in std ``，
  若 `cx.dep_package` 是 `Some(p)` 报 `` `dbg` cannot be used in package `p`, which is loaded through [deps] ``，
  提示「本地调试用；从包里删掉，或把包当独立项目调试」。位置是 `dbg` 这个名字。
  同一个包 `dawn check` 自己时（它是项目而不是依赖）可以用：调试一个包本来就该这样做。
- 仓内五个目录（`selfhost`、`std`、`packages`、`site`、`playground`）编译器不把它们当依赖看（selfhost 与 site 各自是项目），
  所以由门禁禁止：`scripts/check-no-dbg.py`，挂在 tree-policy（不需要工具链的那个 job），本机 0.49 s，自测 0.02 s。
  不用 `git grep -w dbg`：这些源码里 `dbg` 合法地作为文本出现（编译器自己的 `name == "dbg"`、报错提示、注释，
  tileir 的字符串 `"dbg"`），所以脚本按词法读：跳过 `#` 注释、`"..."`/`"""..."""`/反引号/字符字面量，但
  `${...}` 插值里是代码。`selfhost/builtins.dawn`（内建表的声明式镜像，从不编译）按路径豁免，豁免条目若不再匹配就红。

### 6.5 comptime

降低在解释之前，所以 `const` 里的 `dbg` 也是那个块；解释器给 `dbg_line` 一个臂，什么也不写、答 `Unit`。
这就是「语义为恒等」在编译期的字面实现：常量照常折叠，编译期不打印，也不像其它 io 原语那样被拒绝。
钉在 `ir/interp_test.dawn` 的「dbg is the identity in a const, and writes nothing」。

### 6.6 测试与负控

- 两后端：`scripts/spike-native/dbg_line.dawn`。stdout 进 `.expect`；stderr 进新增的 `<name>.expect-stderr`：
  `run.sh` 的 `stderr` 检查在两后端一致之外，有这个文件时还要求与它逐字节相同（只靠一致，两个后端写同一行错字也是绿）。
  语料覆盖：算术、`String`（带引号）、`derive Show` 的 record、列表、管道（单行与竖排）、纯函数里的 `dbg`、跨三行的实参、
  泛型函数经见证渲染、`ä🎈` 之后的码点列、`dbg(dbg(5) + 1)` 的嵌套顺序。
- checker 语料：`scripts/checker-corpus/cases/dbg_rules.d`，一个带 `[deps]` 的两包项目，钉住依赖里两处拒绝
  （直接调用与管道）与入口里函数值的拒绝；std 的那条拒绝语料够不着，登记在 `uncovered.txt`，由单元测试与仓内门禁兜。
- 单元：`tast_positions` 的行头与多行折叠；checker 的 `[deps]`/std/函数值拒绝（含消息、提示、位置）与遮蔽不拒；
  `Show` 约束的报错文案；`interp_test` 的 comptime 恒等；`doc --builtins` 与内建镜像 `selfhost/builtins.dawn` 各加一行，
  `builtin-decl-contract` 双向对账通过。
- 负控（各已还原，数字见 L3 报告）：`.expect-stderr` 一个列号加一，`stderr` 检查红；去掉 checker 的 `[deps]` 拒绝，
  单元测试红；解释器把 `dbg_line` 当 io 拒绝，comptime 测试红；std 里放一个 `dbg`，`check-no-dbg.py` 红，
  放进注释或字符串则不红。

### 6.7 差分

`dbg` 是新名字，现有源码一个也没有（门禁保证本仓五个目录永远没有），所以 emit 语料与 Core golden 不变。
变的只有工具链对外的内建清单：`dawn doc --builtins` 多一条 `dbg`（run-diff 的对应 label），LSP 的补全表多一个名字。

## 七、不做的（理由）

- **运行期栈迹**（JVM LineNumberTable、native `#line` + unwinder）：见 3.1(c)。将来「调试信息」专项另议，那时的消费者是调试器，不是 panic 消息。
- **JVM 上打印白给的函数级栈**：只有一个后端有，会成为两个后端的行为差异。
- **隐式调用者位置**（`track_caller`、`HasCallStack`）：不进类型，经函数值静默丢失；显式默认参数在类型里可见。
- **`ForeignError` 增加位置字段**：按错误模型，决定看 `kind`，没有人应当按位置做决定。
- **`dbg` 带 `!io`**：一次调试编辑会沿调用图改签名。
- **`--release` 剥离 `dbg`**：语义恒等，剥离只会引入「构建模式」这个新维度。
- **多实参 `dbg(a, b)`、零实参 `dbg()`**：没有变长参数与重载，元组即可。
- **AST 反打印重建表达式文本**：没有 AST 到源码的 printer，fmt 是词法级的。
- **L1 在消费者处剥路径代替编译器规范化**：每个消费者都要记得剥，而且剥不掉「两个 cwd 产物不同」；
  Playground 的 `strip_dir` 只是纵深防御，不是修法。
- **L1 用 `-ffile-prefix-map` 式的命令行重映射**：把可复现交给调用者记得传参，默认值仍然是错的。
- **L2 把位置作为 `ForeignError` 的独立字段**：调研 §3.5 已否，按错误模型决定看 `kind`，没有人应当按位置做决定。
- **L2 给运行期索引越界、除零、`unreachable match` 加位置**：这些失败由 std 或降低生成，没有作者写下的调用点；
  下标 `c[i]` 的失败在 std 的 `Index` impl 里；`Index` 是 trait 方法，不收默认值，所以 L4 的 `caller()` 也够不着它（caller-location-design 第八节）。
- **L2 在 Core golden 里归一路径**：同一个模块换了文件不是纯移动。
- **L3 用 parser 边表传实参文本**：见 6.2，声明出口切片取自同一修订，不要第二条通道，也不要为遮蔽与管道特判。
- **L3 按 token 重排实参文本**（Rust `stringify!` 式）：那是反打印；原文加跨行折叠已经让一行是一行。
- **L3 把 `dbg_line` 做成运行时模块的方法**（`RtIo` 下的新名字）：两个运行时各多一个与 `io_eprintln` 相同的函数，
  JVM 运行时类还会多一个方法，所有产物都变；后端的一个臂就够了。
- **L3 允许 `dbg` 作函数值**：函数值没有调用点与实参文本，见 6.1。
- **L3 的仓内门禁用 `git grep -w`**：五个目录里 `dbg` 合法地作为文本出现，见 6.4。
