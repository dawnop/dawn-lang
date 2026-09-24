# 效果窗口：环境效果、效果限定与改名、`catch_panic` 的行、`unsafe_pure` 删除、`main` 只在入口

> 状态：**current**（已落地于分支 `fix/effects-window`，基线 `b2e19e06`，后 rebase 到 main `15f62267`（#216、#218 合入后）；落地记录在文末）。依据是
> `agent-handoff/rulings-20260924.md` 的裁决 4、5，以及协调者 2026-09-24 对改名范围的追加裁决（通用改名，见 §3）。
> 外部先例调研（带出处）在 `agent-handoff/research-effects-window-20260924.md`，本文只摘结论。
> 调研原文：`agent-handoff/debt-survey-2026-09-07/02-semantics.md` 的 SPC-02/04/05/06/07/14/22，
> `03-architecture.md` 的 ARCH-N02、ARCH-N13。文中 `file:line` 对 `b2e19e06`。

每条裁决一个提交，按下面的节序落地。

## 1. SPC-02 / ARCH-N02：native 除零文案（已在 main），顺带 ARCH-N13

### 现状核实

SPC-02 在调研之后已经修了：`da884438`（2026-09-07）把 `runtime/c/dawn_rt.c:1572/1582` 改成
`Int division by zero` / `Int modulo by zero`，并加了 `scripts/spike-native/divzero_messages.{dawn,expect}`
（进 `matrix.txt` 第 57 行）。那条语料经 `catch_panic(...).message` 两后端打印，`diff` 检查钉住逐字相同。
本节对 SPC-02 不再动码。

### ARCH-N13 一并修

§4 要让 `catch_panic` 变纯，纯函数的值不能是后端的函数。语言自己发出的失败里还剩一处两后端文案不同：
`Array` 越界，JVM 是 `array index <i> out of bounds for length <n>`（`jvm/rtclasses.dawn:2037` 的
`array_bounds_panic`，前缀 `"array index "`），native 三处都是 `Array index out of bounds`
（`dawn_rt.c:3249/3301/3340`）。改 native 与 JVM 同文。

`Array` 今天用户源码拼不出来（只有 std 内部用），所以这条没法写成用户语料，
只能静态闭合：`c/emitc.dawn` 已有「运行时符号与头文件对账」的 test 形状，这里加一条读 `rtsrc`
的 test，断言三处文案都用同一个格式化函数、格式串与 JVM 前缀一致。

- 改动：`runtime/c/dawn_rt.c` 加 `dawn_array_bounds_panic(i, len)`，三处调用；`selfhost/src/embed/rtsrc.dawn` 重生成。
- Emit-Change：无（emit 语料不含越界路径）。Core golden：rtsrc 是编译器源的一部分，`selfhost.sha` 会动，最终树上重录。

## 2. SPC-07：`io` 是唯一的环境效果；分类查表

### 规则前后

| | 之前 | 之后 |
|---|---|---|
| `io` 的地位 | spec §6.1 说它是基轴的已定点，四项特权散在 §6.5「实现」与五处源码字面量 | spec §6.1 新增「环境效果」小节（不新开节号，免得全仓的 §6.x 引用顺延）：不声明、不占证据槽、没有 handler、任何行可写；**`io` 是唯一成员**，用户不能声明环境效果 |
| `pure` | §6.3 一句「`pure` 在任何位置被拒」 | 同一节写明 `pure` 只在效果位保留（SYN-N02）：它不是关键字，出了效果位是普通标识符 |
| 标签还是变量 | `front/effect_name.dawn` 的 `declared(name) = upper(name) \|\| qualified(name)`；`passes.dawn:261/309` 与 `cx.dawn:876`、`passes.dawn:1316`、`checker.dawn:9470` 各写一遍 `a == "io"` | 分类走表：环境效果表 → 作用域内效果（含选择性引入与改名）→ 本模块尚未编号的 `effect` 声明 → 模块别名导出表（限定名）→ 类型参数（投影）→ 本签名的效果变量。查不到时拼写只决定**哪条诊断**：大写报「unknown effect」，小写按「出现即引入」成为变量 |
| 写了一个类型当效果 | `!String`、`!T` 报 `unknown effect` | 报 ``` `String` is a type, not an effect ```（类型参数、内建类型、声明的类型各一条措辞）——这是表能答、拼写答不了的那一类 |

「大小写与声明表一致」由命名规则在**声明点**保证：效果声明只收大写名（parser），效果参数只收小写名
（parser，`[!e]`），改名必须保持大小写类别（§3）。所以查表与看拼写对合法程序给同一个答案；
区别只在落空时能不能说出落空的原因。这就是 SPC-07 选项 (c) 的内容，spec 条文采用选项 (a)。

### 实现

- `front/effect_name.dawn`：加 `ambient_effects() = ["io"]` 与 `ambient(name)`；`declared` 删除（它是拼写判据本身）。
  parser 的 `[!io]` 绑定者拒绝改读 `ambient`。
- `check/cx.dawn` `resolve_eff_at`：第一分支 `a == "io"` 改 `effect_name.ambient(a)`；
  落空的大写分支先查类型参数、内建类型、声明的类型（都经已有的 `semantic_reads` 读：
  `ScopedTypeParameter`、`BuiltinTypeAnswer`、`NominalTypeName`），命中则报「is a type, not an effect」。
  用已有读是为了增量语义引擎的回放：新诊断依赖的每个答案都已被记账，不新增读种类。
- `check/passes.dawn` `stray_eff_atom`：签名加一个参数 `declared: List[String]`（作用域内效果名 +
  本模块 `effect` 声明名），「已声明」改为查它；带点的原子（限定名、投影）照旧交给后面的解析，
  它们从来不是绑定者。落空且大写的原子不在这里报，留给 `resolve_eff_at` 报一次。
- `resolve_ground_row`、`checker.dawn:9470` 的 `"io"` 字面量改 `ambient`。

局部函数只能写 `!io` 的限制（`checker.dawn:9473`）属于 SPC-19，是语法窗口写者的刀，本刀只换谓词不动规则。

### 负控

`scripts/checker-corpus/cases/effect_atom_table.dawn`：`!String`、`!T`（类型参数）、`!Missing` 三行，
期望三条不同措辞。把 `resolve_eff_at` 的落空分支改回只看拼写（删掉查类型那三读）→ 前两条变成
`unknown effect`，语料红。

### spec 改动

§6.1 末尾新增「环境效果」小节（含 `pure` 只在效果位保留一句）；
§6.5「拼写与传播」里「`!name` 的判别是查表」一条改写成上面的分类序。`spec.en.md` 同步。
doc-check 契约句：「**`io` 是唯一的环境效果**」（中英两句进 `SPEC_CONTRACTS`）。

## 3. SPC-06：效果是普通模块成员——限定名与通用改名

### 限定名（核实）

`use std/io` 之后写 `!io.Fs`：parser 的 `effect_name_token` 把 `io.Fs` 读成一个两段原子
（小写首段 + `.` + 大写），`resolve_eff_at` 走 `qualified` 分支查模块别名 `io` 的导出表。
这是 #145 的路径；首段恰好也叫 `io` 不影响，因为环境效果 `io` 是**不带点**的原子。
本刀只补语料与 spec 句子。

### 改名：`use m.{x as y}` 对所有成员通用（协调者裁决）

先例全是通用改名（Flix `use A.{f => g}`、Rust `use a::B as C`、Unison 命名空间别名），
没有一门语言只让效果改名。只给效果开 `as` 等于让效果成为唯一能逐名改名的成员，与「效果是普通成员」相悖。

**语法**：选择性列表的每一项是 `Name` 或 `Name as Local`。`as` 仍是上下文关键字（只在列表项名字之后特殊）。
`Local` 必须与 `Name` 同一词法类别（`IDENT` 对 `IDENT`、`TYPEIDENT` 对 `TYPEIDENT`）：大小写是语义，
改名不能把函数改成构造器的拼法。常量还要保持全大写。`X as X` 报错（什么也没改，一件事一种写法）。

**语义**：

- 本地只绑 `Local`；`Name` 在本模块不可见（与 Rust/Flix 相同）。
- 身份不变：改名只动本模块的名字表，被引入者的 id、导出面、诊断里打印的规范名都不变
  （诊断打印类型与效果时用声明名，与今天打印限定引入的类型一致）。
- 一个类型带进来的构造器、一个效果带进来的操作，**名字不跟着改**；要改它们就把它们单独写进列表改。
- `imported_names` 以本地名为键，冲突检查（与本模块声明、与其它引入、与模块别名）都按本地名做。

**两个提交**（协调者裁决）：

1. **id 身份的成员**：效果、类型（ADT / opaque）、`alias`、trait、构造器。它们按 id 认身份，改名只是名字表多一个键。
   函数与常量写 `as` 暂时报 ``renaming a function or constant in a selective import is not supported yet``（下一提交删掉这条）。
2. **函数与常量**：调用点今天把写下的名字当被调符号（`checker.dawn:10262` 的 `XCallFn(s.owner, callee, …)`，
   默认实参 `callee$default$i`，`:9640`），函数值引用、常量引用同理。拆成「本地名用于查表，`Sig.name` / 导出名用于发射」。
   若这一半出现无法收敛的设计问题，**停下报协调者**，不自行退回「不做改名」。

### 语料

- `scripts/checker-corpus`：两个库导出同名效果 `Log`（操作名不同），消费方 `use a as la` + `use b as lb`，
  行里写 `!la.Log !lb.Log`，两个 `with handle` 各装一个；再用 `use b.{Log as BLog}` 写一遍。
  负控：同一消费方写 `use a.{Log}` + `use b.{Log}` → 冲突诊断（这条今天就红，是回归护栏）。
- `!io.Fs` 与 `use std/io.{Fs as F}` 后 `!F` + `with handle F { ... }` 的运行语料进 spike-native（两后端）。
- 函数/常量改名（提交 2）：`use m.{parse as p, LIMIT as MAX}`，调用、函数值、默认实参三种形状两后端跑。

### spec 改动

§10.2 的 `as` 条改写成通用规则一条（整模块别名 + 选择性改名）；§6.5 的「Module-qualified effect names」
（现为英文段落，混在中文 spec 里）译成中文并补 `!io.Fs`、`{Fs as F}` 两例。`spec.en.md` 同步。

## 4. SPC-22：`catch_panic` 去掉 `!io`

### 规则前后

```dawn
# 之前
fn catch_panic[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io
# 之后
fn catch_panic[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !e
```

三个屏障的行从此是同一个形状：`bracket`、`catch_fault`、`catch_panic` 都是 `!e`。

### 论证（取代 error-model-design §7.2/§7.5 里只咬 `catch_panic` 的那两条）

纯性的承诺是：**同一程序、同一构建里，相同实参得相同值，且无可观测副作用**（spec §6.2 第 4 条）。
逐条对 `catch_panic`：

1. **栈深**：§7.5.1 已证不成立（栈耗尽到不了 `Result`，两后端都不拦 `VirtualMachineError`/SIGSEGV）。
2. **消息是「源码排版 × 后端」的函数**：源码那一半不构成不纯——一个纯函数的值本来就可以是它自己源码的函数
   （字符串字面量就是）。后端那一半是真问题，但它是**跨后端一致性契约**的问题，不是纯性的问题：
   纯性只承诺一个构建内的确定性。本刀把契约写全：**语言自己发出的失败，消息两后端逐字节相同**
   （SPC-02 已修、ARCH-N13 本刀修，`spike-native` 语料钉住），spec §9.8.1 那句「只承诺 `panic(m)`」扩成这一条。
3. **折叠与消重**：Dawn 严格求值、求值顺序规定，同一实参的纯闭包 panic 与否、消息是什么都确定，
   所以折叠与消重不改变值；捕获本身没有副作用，捕获几次不可观测。comptime 仍然无条件拒绝 `catch_panic`
   （`ir/interp.dawn:844`），编译器不会把构建机上的消息折进产物。

Haskell 把 `catch` 留在 `IO` 的理由是惰性求值下「抛的是哪个异常」不确定（imprecise exceptions），
这条前提在严格求值的 Dawn 不成立；Koka 的 `try : (() -> <exn|e> a) -> e a` 是纯的（调研报告第四节）。

**Codex 评审的反对**（`05-codex-review.md:105`：「`!io` 里允许观察 build 相关内容，不反证纯函数也可以」）成立，
所以上面不再引用「消息已经在 `!io` 里跨后端分歧」作支撑；支撑换成第 2 条的契约。

**残余已知分歧**：SPC-15 的 Cursor 跨串（B1 已裁不修）在两后端行为不同，但那是**不经 `catch_panic`**
也在纯代码里可观察的分歧（一边返回值、一边 panic），与本条无关。

### 实现

- `check/types.dawn`：`catch_panic` 表项去 `eff1(…, EIo)`，改 `effp1`（与 `catch_fault` 同形）；其 test 改断言。
  `selfhost/builtins.dawn` 镜像同步（`builtin-decl-contract` 双向对账）。
- 调用点收窄：凡是**只因** `catch_panic` 带 `!io` 的函数，行收窄。**`selfhost/src` 不收窄**：种子 v0.77.0 的表
  仍是 `!io`，收窄后种子编不动 HEAD（种子约束）；记入发版后的待办。`std/`、`packages/`、`examples/`、
  `scripts/` 语料按逐个 `dawn check` 实测收窄（报告列出清单）。
- 文档：spec §9.8 / §9.8.1 / §9.8.2 相关段改写，doc-check 契约句「这一对的效果行不再是同一个」「三个屏障排成一条线」
  改成新句子；`docs/audit/error-model-design.md` 加 §7.6 后记；`docs/effects-design.md` 第 48 行屏障族一句加指向。

### 负控

`scripts/checker-corpus/cases/catch_effects.dawn` 加一个纯函数调 `catch_panic` 的 case。把表项改回 `!io` →
该 case 报 `is not declared !io but calls catch_panic`，golden 红。

### Emit-Change

`doc --builtins`（签名渲染变了）。`emit *` 预期不变：`io` 不占证据槽，`!io` 与 `!e` 的 ABI 同是一格 `e` 的包。

## 5. SPC-05：`with_fs_real`、`with_gpu_real` 效果多态

```dawn
pub fn with_fs_real[T, !e](body: fn() -> T !Fs !e) -> T !io
pub fn with_gpu_real[T, !e](kernels: Map[String, Bytes], body: fn() -> T !Gpu !e) -> T !io
```

与同族四个 handler 同形。`std/io.dawn` 在 `with_proc_real` 上方那段注释（「`with_fs_real` keeps the closed row
it has until something needs to sit outside it, because widening it costs a release」）说的重开条件，
是「有东西要坐在它外面」：`!Fs !Log` 语料就是那个东西（dawnop-site 的 `api_monitor` 也同时装两个 handler）。
「costs a release」指的是**调用方**要等种子才能写新形状；签名本身对旧调用点兼容：旧调用点的 body 行是
`!Fs !io`，新签名下 `e := io`，结果行仍是 `!io`。所以 `selfhost/src` 的调用点不用改，种子编得动。

- 语料：`scripts/spike-native/fs_real_polymorphic.dawn`（body 行 `!Fs !Log`，外层装 `Log` handler，两后端跑）。
  `with_gpu_real` 需要 GPU 驱动，只进 checker 语料（类型层面）。
- 注释改写：删掉「keeps the closed row」那句，改成五个 handler 同形的一句。
- `selfhost/src/embed/stdsrc.dawn` 重生成。

## 6. 裁决 5：删除 `unsafe_pure`

### 零使用点核实

`git grep unsafe_pure -- '*.dawn'` 只命中：编译器自身（关键字、检查、测试）、`std/{list,io,bytes}.dawn` 三行注释（都在说「这里**不**需要」）、
`scripts/checker-corpus/cases/unsafe_pure.dawn`（「用户代码不可用」的语料）、`playground/src/play/exec.dawn:86` 一行注释。
std、packages、examples、site、playground 零个真实使用点。dawnop-site 的钉住版本另行核实（报告附命令）。

### 先例反向，Dawn 仍删的理由

四个有效果系统的语言都**留着**逃生舱：Haskell `unsafePerformIO`、Koka `unsafe-total`、Flix unchecked effect cast、
Effekt extern 的 `{}` capture 标注（出处见调研报告第五节）。Dawn 仍删，因为：

- 那些逃生舱都有真实用户；Dawn 的这一个自 2026-07-30 起只许 std 用，而 std 零使用。
- 它的动机（「一个宿主调用支撑一个纯函数」）已经由 **intrinsic 表**在声明侧承担：一个原语的行由编译器随自身发布、
  随自举与差分一起受守护（spec §11）。这正是 Effekt 的路线（担保写在 FFI 声明上，不写在调用点表达式上）。
  `unsafe_pure` 是这条路走通后剩下的第二种写法。
- 重开条件：出现一个 std 包装真的无法表达成 intrinsic（例如需要表达式级的担保而非声明级），再议；
  即便那时也优先扩 intrinsic 表，而不是恢复表达式戳子。

### 删除面

- 词法与语法：`token.dawn` 的 `UNSAFE_PURE`、`parser.dawn` 的分支、`ast.dawn` 的 `EUnsafePure` 及其 span 访问器、
  `astdump`、`lspq` 的两个遍历分支、`lspc` 的关键字补全表。删除后 `unsafe_pure` 是普通标识符。
- 检查器：`checker.dawn` 的 `check_unsafe_pure` 与三处遍历分支、三个 test；`cx.dawn` 两处注释。
- `--comptime-ffi` 与 route C：没有 `unsafe_pure`，`use java` 调用恒为 `!io`，`const`/comptime 块要求纯，
  route C 从此**不可达**。一个永远不起作用、帮助文本却说它能折叠的开关比没有更糟，同刀删：
  `jvm/jfold.dawn` 整个文件、`CtOpts.ffi`/`jcall`、`interp.dawn` 的反射调用路径与其测试、`main.dawn`/`nmain.dawn` 的开关解析与帮助文本。
  原计划单独一个提交；实际与 `unsafe_pure` 同一提交，因为 route C 的测试夹具本身就用 `unsafe_pure` 写成，
  拆开会留下一个测试红的中间提交。`jreflect.invoke_static` 随之无人调用，一并删除；`driver` 里两处
  「开了 ffi 就不缓存」的分支与两个对应的增量契约变异体（`allow-ffi-cache`、`ignore-ffi`）也删掉。
- 工具与门禁：`editors/vscode/syntaxes/dawn.tmLanguage.json` 两处、`scripts/checker-corpus/cases/unsafe_pure.*`、
  `coverage.py` 与 `uncovered.txt` 相关行、`scripts/journal-reads/ledger.txt` 两行、`doc-check.py:705` 注释。
- 文档：spec §6.4 改成墓碑（保留节号，免得全仓 §6.5/§6.6 的引用顺延），§1 保留字表去掉 `unsafe_pure`；`spec.en.md` 同步；
  `docs/pure-ffi-design.md` 头部状态加一行「`unsafe_pure` 与 route C 已删除（本文）」；`docs/README.md` 索引行同步。
  其余历史文档（审计、计划）里的提及是历史记录，不改。

### 负控

删除后在 `std/list.dawn` 末尾临时加一行 `pub fn stamped() -> Int = unsafe_pure { 1 }` 并重生成 stdsrc：
工具链拒绝加载这份 std（`module std/list does not check: undefined function: unsafe_pure`——`unsafe_pure`
成了普通标识符，`{ 1 }` 被读成尾块实参）。记录输出后撤回。

### Emit-Change

`cli error (run)` 等帮助文本类 label（`--comptime-ffi` 从用法里消失），以集群 run-diff 实际报出的为准逐个写。

## 7. SPC-04：`main` 只在入口模块保留

### 规则前后

- 之前：`pass_main_check`（`passes.dawn:2731`）对**每个**模块里名为 `main` 的顶层函数强制 `pub fn main() -> Unit !io`
  与「不带标签」；后端取「依赖序里第一个有 `main` 的模块」当入口（`main.dawn:540`、`c/cdriver.dawn:404`），
  JVM 发射对每个有 `main` 的模块都生成 `main(String[])` 包装（`jvm/emit.dawn:1983`）。
- 之后：入口模块由加载决定——目录模式是 `src/main.dawn`，文件模式是命令行给的那个文件；依赖包的模块永远不是入口。
  `pass_main_check` 只在入口模块跑；其它模块的 `main` 是普通函数，任何签名、任何可见性。
  后端只在入口模块上找 `main`、生成包装。

### 实现

- `driver/analyze.dawn`：`LoadedModule` 加 `entry: Bool`，由 `load_entries_over` 按 plan 的目标算出
  （`SourceFile(f)` → `f`；`ProjectDirectory(d)` → `d/src/main.dawn`，按 canon 路径比）。LSP 单文档分析的那一个是入口。
  `entry` 只影响头部检查（`pass_main_check`），不影响任何函数体，所以 body 缓存的作用域键不变；
  前缀复用比较整个 `LoadedModule`，字段自动算进去。
- `check/cx.dawn`：`Cx.is_entry_module`，`module_step` 从 `LoadedModule.entry` 设。
- `passes.pass_main_check`：非入口直接返回。
- 后端：`main.dawn`、`c/cdriver.dawn` 的入口判定改读 `cm.cx.is_entry_module`；`jvm/emit.dawn` 只给
  `class_name == args_owner`（即入口类）生成 `main(String[])` 包装。
- `Cx.is_entry_module` 与 `is_std_module` 同列进头部产物与 body 产物的「环境不变」判定。

### 语料

`scripts/checker-corpus/cases/main_entry_only.d`：库模块私有 `fn main(x: Int) -> Int`，不报；入口模块
`fn main() -> Int` 仍报两条旧诊断。负控：把入口判断改成 `if false` → 库模块多出同样两条。
`scripts/spike-native/library_main`：库模块定义 `fn main(x: Int) -> Int`，入口调用它，两后端输出一致。

### spec 改动

§10.5「入口」一句补全：「只有入口模块的 `main` 受此约束，其它模块的 `main` 是普通函数」；§6.5「只有 `pub fn main` 的标签必须为空」
一句改成「入口模块的」。`spec.en.md` 同步。

## 8. std 改动后的 `stdsrc` 重生成

每个碰 `std/` 的提交都在同一提交里跑 `scripts/gen-stdsrc.py`，`git diff --stat` 可见 `selfhost/src/embed/stdsrc.dawn`。

## 验证路径

本机只跑单文件 `dawn check`、`fmt --check`、doc-check 与探针；编译与门禁全部经
`scripts/gates-external/run.sh --backend crun`（任务单公共段的命令）。每个提交后跑 gatemap 列出的 coupled 门；
碰 `check/` 的提交跑 `--only incremental-*`；交付前全套 `--jobs 16`。Core golden 在 rebase 到最新 `origin/main`
之后的最终树上重录。

## 不做的（理由）

- **用户可声明的环境效果**（SPC-07 选项 b，`ambient effect Panic {}`）：裁决 4 定的是「`io` 是唯一成员」。
  多一个成员就要回答它与 `io` 的包含关系、它能不能被 handler 减掉，这些问题今天没有消费者。
- **把 panic 升为效果行成员**（Koka `exn` 路线，error-model-design §7.3 的重开条件）：本刀让 `catch_panic` 纯，
  走的是「一致性契约 + 严格求值」，不动 panic 的地位；§7.3 的条件原样保留。
- **`selfhost/src` 里的调用点收窄**：种子约束，下一个 release 之后做。
- **局部 `fn` 的具名效果行**（SPC-19）：语法窗口写者的刀。
- **三段以上的效果限定名**（`!a.b.Ask`）：模块别名只有一段，`use a/b as ab` 已覆盖；spec 维持「只支持两段」。
- **改名构造器之外的「连带成员」改名**（类型改名时把构造器一起改）：一个名字一个 `as`，连带改会让一行 `use`
  引入调用方看不见的新名字。

## 落地记录（2026-09-24）

| 节 | 提交 | 负控（先证明会红） |
|---|---|---|
| 0 设计 | `806d0729` | — |
| 1 ARCH-N13 | `3ca0e35e` | 静态：`rtclasses` 的 test 读 rtsrc，旧文案在即红 |
| 2 SPC-07 | `a33d1ac6` | `resolve_eff_at` 查类型三读改成 `None` → `effect_atom_table` 前三行变成 `unknown effect` |
| 3 SPC-06 id 成员 | `3c0ea304` | `effect_name_clash`：两库同名效果裸引入仍是冲突 |
| 3 SPC-06 函数/常量 | `1b2b997c` | `spike-native/import_rename` 两后端跑通调用、默认实参、函数值、常量 |
| 4 SPC-22 | `c185f351` | 表项放回 `eff: EIo` → `catch_effects` 多出三条诊断 |
| 5 SPC-05 | `2e6995ff` | `spike-native/fs_real_polymorphic`（旧签名下 `!Fs !Log` 被拒） |
| 6 裁决 5 | `50ab34c3` | std 里写 `unsafe_pure { 1 }` → std 不加载 |
| 7 SPC-04 | `7aeb3f22` | 入口判断改 `if false` → `main_entry_only` 的库模块多两条 |
| Core golden | `e37913f8` | — |

实现中的偏离：`ambient_effects()` 是函数而非常量；route C 与 `unsafe_pure` 同一提交（理由见 §6）；
spec §6.4 留墓碑而非删节；§6.1 的「环境效果」是小节而非新节号。`selfhost/src` 里因 `catch_panic` 而带 `!io`
的签名（`lsp/server`、`main`、`ir/interp` 等）按种子约束未收窄，下一个 release 推进种子后再做。

**种子推进到 v0.78.0 之后的回填（2026-09-25，分支 `fix/post-seed-cleanup`）**：`selfhost/src` 里 `catch_panic`
的 14 个调用点逐个去 `!io` 后跑 `dawn check selfhost`。只有两个函数的 `!io` 是 `catch_panic` 给的：
`c/emitc.gaps` 与 `ir/interp.ev_get_panics`，已收窄为纯（调用者都是 test 块，不再往外传）。其余调用点所在函数的
`!io` 都另有来源，编译器逐条报出：`ir/interp.probe_builtin`（`call_builtin`）、`lsp/server.close_lease`
（`JsigLease.close`）、`lsp/server.activate_workspace`（`host.project` 与 `rebuild_workspace`）、`main.run_lower`
（`jsig_real`、`analyze_program`、`load_std` 等）；`check/jsig`、`ir/interp`、`lsp/server` 其余几处在 test 块里，没有签名。

SPC-04 的连带：仓里有依赖「依赖序里第一个有 `main` 的模块」的地方。`scripts/incremental-semantics-contract`
这个包的入口原本是 `src/bench.dawn`，改名为 `src/main.dawn`；十一个增量契约脚本在临时目录里拼项目夹具，
把带 `pub fn main` 的模块写成别的名字，现在各自多写一个两行的 `src/main.dawn` 转发过去（不改原模块名，
因为脚本按模块名解析测试输出）。

