# 未使用的 import 是编译错误

> 状态：**current**。裁决 8（2026-09-24，改一步版）的规则、实现与落地记录。
> 调研报告：`agent-handoff/research-tooling-rulings-20260924.md` 裁决 8 一节；
> 问题来源：`agent-handoff/debt-survey-2026-09-07/03-architecture.md` ARCH-N03。

## 1. 问题

checker 没有任何「这条 import 没人用」的诊断，所以 `use` 只增不减。调研 ARCH-N03
按**整条声明**数出 13 条死 import（`driver/analyze.dawn` 那条 `use check/passes.{...}`
十个名字一个没用，`arch-split-design.md` 10.4 一个月前就记过，至今还在），外加
两条只被 test 用到的反向边 `ir/interp → check/checker`、`jvm/jfold → check/checker`（后者随效果窗口删掉 `jvm/jfold` 而消失，见 §4）。

按**名字**数要多得多：本刀在全仓跑新诊断，selfhost 一处就报出 213 个名字
（第一轮 191，细化类型/效果的可达规则后又 22，见 §3.3），`scripts/` 下的
语料、包与示例另有 238 个（绝大多数是 `use std/io` 而只用了 prelude 的 `println`）。
这就是没有诊断时 import 表的自然状态：写的时候加，删用法的时候不删。
本分支 rebase 到效果窗口、`pub(pkg)`、语法窗口三批之上后，selfhost 又报出 81 个
（三批改过的 import 表在冲突里取了上游，加上它们各自不再用的名字），
单独一个提交删掉；selfhost 之外没有新增。

后果三条（ARCH-N03 原文）：`use` 图不再是架构事实，任何「谁依赖谁」的推理读的都是
被污染的图；gate-map 的依赖推理跟着失真；Dawn 硬禁模块环，一条死 import 就可能让
一次合法的拆分变成「有环，做不了」。

## 2. 规则

写进 spec §10.2（`scripts/doc-check.py` 的 SPEC_CONTRACTS 钉住中英两句）：

1. **一条 import 没有被本模块任何地方引用，是编译错误**：`unused import: <name>`。
   不是 warning——Dawn 只有一种诊断等级（`front/diag.dawn`：Diag 不带 severity；
   LSP 一律 `severity: 1`；`dawn check` 有诊断即退出 1），本刀不新增第二种。
2. **按名字报**：整模块引入按它绑定的别名（`use a/b` 是 `b`，`use a/b as x` 是 `x`），
   选择性引入 `use m.{x, y}` **逐名**报（`y` 没用就只报 `y`），`use java "p.C"` 按
   它绑定的简单名 `C`。三种一视同仁，不留特例。改过名的 `use m.{x as y}` 看本地名
   `y` 有没有被拼写，报告里写作者写下的导出名 `x`（spec §10.2 的改名规则：诊断里
   打印的名字不随改名变）。
3. **test 用到算用到**。test 块与生产代码共享文件头的 `use`，`dawn check` 也检查
   test 体（调研里的探针），所以检查器看到的只有一个视图：含 test 的整个模块。
   在这个视图上算使用，就不会有 Rust #59426 那种「同一个 import 在一个构建里用了、
   在另一个构建里没用」的分裂。
4. **模块有其它任何诊断时不报**。一个检查失败的函数体可能在用到某个 import 的那一处
   之前就停了；在真错误上面再叠一条假「未使用」，是把作者往错的方向推。
   同理，只问**解析成功**的 import：模块找不到、名字是私有的、Java 类找不到，
   这些已经各有一条错误，它们本来就不是「对某个东西的引入」。
5. **没有逃生舱**。Go 需要 `import _ "pkg"` 是因为包初始化有副作用；Haskell 需要
   `import M ()` 是因为 instance 要靠 import 带进作用域。Dawn 两样都没有：模块没有
   初始化副作用，impl 全局生效、不需要 `use`（spec §3.5）。没有「为副作用而引入」的
   正当场景，也就不需要 `_` 或别的豁免写法。

先例（出处都在调研报告的「出处」一节，这里只列结论）：

| 语言 | 未使用的 import | 诊断等级 | 怎么让它在日常里可忍受 |
|---|---|---|---|
| Go | **编译错误** | 只有错误。FAQ：「the Go compiler does not report warnings, only errors that prevent compilation」（<https://go.dev/doc/faq>） | goimports / gopls 保存时自动增删；`import _` 只为包初始化副作用 |
| Elm | 0.19 编译器**没有任何 warning**，0.18 的 `--warn` 被删（<https://github.com/elm/compiler/issues/1752>） | 只有错误 | 交给外部的 elm-review |
| Zig | 未使用的**局部**是错误；未引用的 `@import` 顶层绑定今天不报，原因是惰性分析而不是原则（#22292），#335 已接受把未用的非 pub 全局也做成错误（<https://github.com/ziglang/zig/issues/335>） | 只有错误 | `_ = x;` 与 `zig fmt` 的 autofix |

三家的共同点是不立 warning 档：要么是错误，要么不说；配套工具把「错误」的摩擦
降下来。Dawn 取 Go 的做法，配套工具是 §6 的 code action。反面的 Rust（默认 warn，
CI 上 `-D warnings`）、Gleam（`--warnings-as-errors`）见 §9。

「引用」的精确含义（§3.2 是它的实现）：

- 整模块别名：出现在 `.` 前面——表达式 `m.f(..)`、`m.C`、`m.NAME`，类型 `m.T`，
  模式 `m.C(..)`，效果行与 handler 的 `m.E`。别名不可被局部遮蔽（spec §10.3），
  所以这些位置上的别名拼写只能是它。
- 选择性引入的名字：出现在任何一个名字位置——值、UFCS 方法名（`x.f()` 可以是
  `f(x)`，spec §4.3）、类型、构造器（表达式与模式）、trait（bound、impl 头）、
  效果（行、handler、默认行）。一个**类型**另可经它的构造器被引用（引入类型即引入
  全部构造器，spec §10.3），一个**效果**另可经它的操作被引用（`use m.{Ask}` 使
  `ask()` 可写）——除非那个构造器/操作本身也被同一模块按名引入，那时拼写算在
  按名的那条上（`use m.{Shape, Circle}` 只写了 `Circle`，`Shape` 就是多余的）。
- 被局部 `let`、参数、模式、局部 `fn` 遮蔽的拼写不算。

## 3. 实现

### 3.1 为什么是语法遍历，而不是在每次查表时打「已用」标记

checker 解析一个名字要查十来张表（函数、类型、构造器、trait、效果、常量、别名、
模块别名、Java 类），而且**增量引擎重放一个已保存的函数体时，这些查表一次都不会
发生**（`check/scalar_replay.dawn`、`check/body_execution.dawn`）。查表时写「已用」
位，冷检查对、重放错。语法在两条路径上是同一份，而一个拼写能到达哪条 import，在
`pass_imports` 跑完之后就固定了——所以答案是「模块文本 + import 表」的函数，
放在 `check/import_use.dawn`，是一趟对 AST 的遍历。

这趟遍历**只往一个方向错**：一个恰好与某 import 同名、实际却指向别处的拼写
（例如 UFCS 名其实落在 Java 实例方法上），只会让 import 看起来「用了」；不存在让
一条真正被用的 import 看起来「没用」的情形，因为每个名字能解析经过的位置都被遍历。
漏报的代价是一行死代码，误报的代价是一个正确的程序编不过——所以只接受前一种。
本刀的全仓清账同时是这条性质的实测：删掉诊断报的每一个名字后，全仓每个
`dawn check` 目标都照旧通过，没有一次删错。

### 3.2 在哪里发

`check/checker.dawn` 的 `execute_module_bodies` 末尾，所有函数体、常量、impl、
trait 默认体与 test 都检查完之后。选这里而不是 `check_module`：冷检查、记录
（`body_execution.record`）与重放（`scalar_replay`）三条路径都经过
`execute_module_bodies`，只有这里能让三者走到同一个结尾；`check_module` 只是冷路径。
此时 `cx` 已离开所有声明（`unowned`），诊断的坐标是文件绝对偏移。

诊断的位置：选择性引入是那个名字；整模块引入是 `as` 后的别名，没有 `as` 时是路径；
`use java` 是引号里的全限定名。消息里的名字始终是「本模块会拿来拼写的那个名字」。

### 3.3 类型与效果的可达集

第一版把类型的全部构造器都算作它的可达拼写。selfhost 清账时发现 22 个名字因此
漏报：`use check/types.{Eff, EPure, EIo, ...}` 里 `Eff` 从未被写出，构造器都是按名
另行引入的，删掉 `Eff` 程序照旧成立。于是可达集减去「本模块也按名引入了的」构造器
与操作（§2 的最后一条规则），这 22 个名字随之被报出并删除。

第二处收紧来自 dawnop-site 的实测：第一版把任何未绑定的裸拼写都当作模块别名的
使用，于是 `use std/map` 加一处 prelude 的 `map(xs, f)` 算作用了 `std/map`。别名在
表达式里只在 `.` 前面出现（`m.f(..)`、`m.C`、`m.NAME`），现在只在那里记。本仓
全量复查没有新增，dawnop-site 因此多报一条（§7）。

## 4. test-only 反向边：兄弟测试模块

裁决原稿要把两条边改成「test 自己的 `use`」。调研探针证明 test 块内不能写 `use`
（parser 只在顶层接受 `USE`），裁决改为兄弟测试模块，先例是
`selfhost/src/front/parser_test.dawn`。落地：

- `ir/interp.dawn` 里调 `check_module`/`exports_of` 的 14 个 test 挪到
  `ir/interp_test.dawn`，`ir/interp` 随之去掉对 `check/checker`、`front/parser` 的引入。
  另一条边 `jvm/jfold → check/checker` 不用再挪：效果窗口（裁决 5）删掉 `unsafe_pure`
  与编译期 Java 路线时，`jvm/jfold` 整个模块连同它的 test 一起删了。
- **发现规则**：目录模式加载 `src/` 下全部模块并执行其全部 test 块（spec §10.5），
  `dawn test selfhost` 因此收得到新模块，与 `front/parser_test` 同一条路。
- **代价，调研没写到的一条**：Go 的 `_test.go` 与被测包同包，看得见私有名；Dawn 的
  兄弟模块是另一个模块，只看得见 `pub`。被挪走的 test 用到 `ir/interp` 的四个私有项
  （`program_sigs`、`eval_module` 及其返回的 `CtRun`/`LowerCache`），它们因此改为
  `pub`，并在声明处注明「只为 `ir/interp_test` 公开」。`pub(pkg)`（裁决 1，已合入 main）要等
  种子能编（v0.78.0）之后才能在 selfhost 里写，这几处应收窄为 `pub(pkg)`——那正是「包内可见」的本义。
  种子推进到 v0.78.0 后已收窄（2026-09-25，分支 `fix/post-seed-cleanup`），声明处的「等种子」注释随之删除。
  `no_impls`、`test_sig`、`test_tfun` 是小夹具，测试模块自己写一份，不为它们开口子；
  帧数上限那条 test 改为直接写出 16，而不读私有常量 `MAX_FAILURE_FRAMES`。

ARCH-N03 的第三档（只被 test 调用的**顶层 helper** 进了 Core 与依赖图，例如
`check/checker.dawn` 的 `msgs_of` 一族、`main.dawn` 的 `cli_read`）不在本刀：
它们引用的都是真实存在的 import，新诊断不会报，本刀也没有让它们消失；
Core golden 因此只随本刀实际改动的模块重录。

## 5. 与 SEM-07 audience 表、`pub(pkg)` 的关系

两者回答的是同一条边的两端，互不替代：

- SEM-07 的 `Audience = World | StdOnly | Module(owner)`（`check/types.dawn`，设计见
  `public-surface-design.md`）决定**谁可以**命名一个声明——导出一侧的问题。
- 本规则问**导入方有没有**命名它——导入一侧的问题。

顺序上本规则在后：可见性不满足的引入（私有名、内部 std 模块）在 `pass_imports`
已经报错，模块有了错误，本规则就不发言（§2 第 4 条）。`pub(pkg)` 落地后，被
选择性引入的 `pub(pkg)` 名字走同一张 `imported_names` 表，本规则不关心目标的
audience 是什么，不需要改动。反方向的「导出了却没人引入」（死 `pub`）不是本规则，
见 §9。

## 6. LSP code action

`dawn fmt` 是词法级的（看 token，不知道使用集），做不了「删掉未使用的 import」；
Go 能把它定成错误，靠的是 goimports/gopls 把日常摩擦降下来。对应物是 LSP 的
`textDocument/codeAction`：对 `unused import: <name>` 诊断给一个 `quickfix`，
「Remove unused import `<name>`」——选择性列表里还有别的名字就只删这个名字和它的
逗号，否则删整条声明（连同行尾换行）。`initialize` 的能力表因此多出
`codeActionProvider`，这是 `lsp` 差分标签上的有意变化。

## 7. dawnop-site 影响估计

dawnop-site 默认分支 `main` @ `dc0a8fb5`（`gh api` 取树与 44 个 `.dawn` 文件，
共 14,492 行、394 行 `use`；未 clone）。两种口径：

1. **静态估计**（动码前）：一个名字在 `use` 声明之外的任何标识符 token 里出现就算
   用了（去掉注释，保留字符串，因为 `${...}` 与 `$name` 插值里的名字是真引用）。
   得 7 个名字、6 个文件。
2. **实测**（实现后）：把 `backend-dawn/dawn.toml` 的三个 url 依赖换成本分支
   `packages/` 下的路径依赖，用本分支编译器 `dawn check`。报出 **8 个名字、5 个文件**：

| 文件 | 名字 |
|---|---|
| `src/api/api_articles.dawn` | `std/map` |
| `src/api/api_public.dawn` | `std/map`、`util/jsonx.{detail}`、`repo/repo_article.{by_slug}` |
| `src/qiniu/rs.dawn` | `std/map`（只以裸拼写 `map(..)` 出现，那是 prelude 函数） |
| `src/svc/auth.dawn` | `std/map` |
| `src/svc/monitor.dawn` | `util/http.{Pending}`、`use java "java.net.URI"` |

两种口径的出入正好是 token 口径的两个盲点：`by_slug` 只以 `repo_page.by_slug`
的成员名出现（token 口径把它算作用到），`rs.dawn` 的 `map` 只以 prelude 函数出现。
另有 `src/config.dawn`、`src/main.dawn` 两个模块因 v0.72→v0.77 的 `Env` 效果错误
（裁决 2 补充改裁里记的那两处）本次不报；token 口径在这两个文件里一条也没找到。

**结论：下次升钉会撞 8 条左右，5 个文件，都是删一行或删一个名字**，LSP 的 code
action 可以逐条修。另一个会同时发生的事：升钉会把 `[deps]` 的 tag 一起抬到同一个
release，而那个 release 的 `packages/` 已经被本刀清过（v0.72.0 的 `packages/web`
里就有一条死的 `use java "java.net.URLConnection"`）；如果只升编译器不升依赖，
依赖包自己的死 import 也会报。

## 8. 可执行的负控

- `scripts/checker-corpus/cases/unused_imports.d`：八个应报的名字（没人限定的别名、
  构造器按名另行引入的类型、只被局部遮蔽拼写的函数、常量、改过名却没用的 `half as halve`、
  `use java` 类、std 模块、只以裸拼写出现的 `std/map`），一组不应报的使用（限定访问、记录字面量、构造器、
  效果行、UFCS、Java 静态调用、经本地名使用的改名引入、test 块），以及一个自带真错误的兄弟模块——它自己的
  死 import 不报。
- 变异体（一次性、手工、记录在提交信息与交付报告里）：让 `report_unused_imports`
  直接返回，语料少六行变红；去掉「有其它诊断就不报」的守卫，`broken.dawn` 多出
  `unused import: list` 变红；把非末名的删除范围改成不带逗号，LSP 契约红两项。
- 一个故意留下的死 import 让 `dawn check` 退出 1。

没有把这些变异体登记进 CI 的变异矩阵：每个编译型变异体要一次完整编译（门禁里实测
约 25–30s 一个），而这里的归属断言就是 checker-corpus 的逐字节 golden，任何一条诊断
少了或多了它都红。

## 9. 不做的（理由）

- **warning 档**。先例是负面的：Rust 的 warning 在 CI 上等于错误（`-D warnings`），
  本地忽略，同一份代码两种判定；Gleam 一加 warning 就得再加 `--warnings-as-errors`；
  Go FAQ 的理由是 warning 档会被弱情形填满、把真错误淹掉。为一条规则给 Diag、LSP
  severity、CLI 退出码、`dawn check` 的「有诊断即 1」同时开第二个维度，不值。
- **常驻 CI 的编译型变异体**。见 §8。
- **`_` 或任何逃生舱**。见 §2 第 5 条：没有为副作用而引入的正当场景。
- **test 块内的 `use`**。那是给 test 开一种新的局部 `use` 形式，与「一件事一种写法」
  相违；兄弟测试模块是现成的一种写法（§4）。也不为它开语言 issue。
- **`dawn fmt` 自动删**。fmt 只看 token，算不出使用集；做成 fmt 等于让 fmt 带上
  一个 checker。删除走 LSP code action。
- **未使用的 `pub` 导出、未使用的私有函数**。前者要全程序视图（一个库的 `pub` 本来
  就是给别人用的），后者是另一条规则；都不在裁决 8 的范围。
- **把 spec §6.2 那句「多余 `!io` 的 lint」做成错误**。裁决 8 只要求删掉「lint」
  这个说法（没有 warning 档就没有 lint）；那条规则要不要做成错误是另一个问题。
