# 源码位置：路径规范、panic 位置与 `dbg`

> 状态：**current**（L1 已落地，L2 至 L4 为已裁决、未实现的刀序）。2026-10-03，分支 `fix/source-position-paths`，关 #401。
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

`panic`、`todo`、`assert` 今天都**不带位置**；std 的 `Cx` 没有 `src_path`，std 里的 `!` 也不带位置。

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
表达式源码只在 parser 手里，用模块级边表 `Map[实参 lo, 源码切片]` 交给 checker，不改 `EApply` 的形状。

### 3.3 刀序

| 刀 | 内容 | spec | 关联 |
|---|---|---|---|
| **L1**（本刀） | 位置路径规范；Playground 运行输出 `strip_dir`；两个 cwd 构建字节相同的负控 | 否 | 关 #401 |
| L2 | `panic`/`todo`/`assert` 带调用点位置（`site` 加列）；Core golden 对位置后缀归一；两后端各一测 | §8.2 删「Dawn 层栈迹」，改为 `panic: <msg> at <path>:<line>:<col>` | 关 #396 |
| L3 | `dbg` 内建 + `dbg_line` intrinsic；`[deps]`/std 拒绝；仓内门禁；comptime 恒等 | 新增小节 | |
| L4 | `caller()` 默认参数 + std `Loc`；`panic`/`todo` 签名加 `at` | 独立设计文档 | |

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

## 五、不做的（理由）

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
