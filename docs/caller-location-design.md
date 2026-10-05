# 调用者位置：`caller()` 默认参数与 `Loc`

> 状态：**current**（L4，2026-10-05 设计并落地，分支 `feat/loc-caller`）。源码位置一线的第四刀；前三刀与刀序见
> [source-location-design.md](source-location-design.md)。依据：裁决 `agent-handoff/ruling-source-location-20261003.md`
> 的 L4 行（`caller()` 默认参数 + `Loc`；`panic`/`todo` 签名加 `at`；不做隐式调用者位置），
> 调研 `agent-handoff/research-debug-print-report-20261003.md` §3.2(b) 与 §四刀 4。仓库行号指 `bc745727`。

## 一、问题

L2 之后，失败消息带的是**写下 `panic` 的那一行**。对程序自己的 `panic` 这正是要的；对库里替调用者报错的函数，
它报的是库的内脏：

- `web` 的 `illegal header …`、`tea_dom/render: …`、tileir 的 kernel 拒绝，L2 之后报 `web6/types.dawn:1062:17` 这类位置，
  用户要找的是自己哪一行传了坏值（L2 报告第十一节）。
- 一个项目自己的测试辅助函数（`fn assert_eq(a, b)`）也一样：失败总指向辅助函数里的 `panic`，每个用例都是同一行。
- std 里的失败（`str.at` 越界之类）L2 干脆不带位置（std 没有展示路径）。

缺的能力只有一个：**函数能拿到「调用我的那个调用点」的位置**，并且能把它交给 `panic`。

## 二、他山之石

| 语言 | 形状 | 要点（出处见文末） |
|---|---|---|
| Swift `#fileID`/`#line`/`#column` | **显式默认参数**：魔法字面量作默认值时在调用点求值 | SE-0274：「magic identifiers only give you the caller's location if they are the only thing in the default argument」；`#fileID` 是 `模块/文件名`，理由是隐私、体积（最多 −5%）、可复现 |
| Rust `#[track_caller]` + `Location::caller()` | **隐式参数**：编译器往 ABI 追加一个不进类型的参数 | 嵌套的 `track_caller` 函数都报最外层未标注调用者的位置；转成函数指针时由 shim 冒充「在定义处被调用」，「losing actual caller information across virtual calls」；「This information is a hint and implementations are not required to preserve it」 |
| Zig `@src()` | 编译期内建，返回 `SourceLocation`（文件、函数名、行、列），「must be called in a function」 | 没有默认参数，库要调用者的位置只能让调用者自己写 `f(@src())` |
| Scala `sourcecode` 库 | **隐式参数 + 宏**：`(implicit line: sourcecode.Line, file: sourcecode.File)` | 编译期填，「does not rely on runtime reflection or stack inspection」；隐式参数沿调用链自动解析，不写在调用处 |
| Haskell `HasCallStack` | 隐式参数（类型约束） | 编译器在调用点求解；没有这个约束的函数截断链 |
| Kotlin | 没有语言机制 | 无宏、无编译器按位置填的参数；日志库靠运行期 `Throwable().stackTrace` |
| Go `runtime.Caller(skip)` | 运行期按帧回溯 | `skip` 数帧；文档提醒内联会吃帧，要用 `CallersFrames` 校正 |

两种编译期形状：**隐式参数**（Rust、Scala、Haskell）与**显式默认参数**（Swift）。运行期回溯（Go、JVM 栈）已在
source-location-design 3.1(c) 否决（Core 无 span、TCO 下栈不可信），这里不再展开。

### 为什么选显式默认参数

1. **在类型里看得见。** `fn expect(o: Option[T], msg: String, at: Loc = caller()) -> T` 的第三个形参写在签名里，
   `doc`、悬停、签名帮助都照常显示。Rust 的隐式参数「不进函数类型」，所以函数指针那一刻只能用 shim 静默丢掉，
   官方文档把结果定性为「a hint」。Dawn 的失败消息是 spec 写死的契约（§8.2），不能是 hint。
2. **丢失规则已经有了。** 函数当值用丢默认值（spec §3.1）。`let g = expect` 的类型是 `fn(Option[T], String, Loc) -> T`，
   调 `g` 必须给一个 `Loc`，类型系统会拦；不存在「静默变成定义处位置」这种第三种行为。
3. **转传是写出来的数据流。** `panic(msg, at: at)` 是普通实参。Rust 那条「沿 `track_caller` 链自动上溯到最外层」的规则
   在 Dawn 里由作者逐跳写 `at: at` 表达；忘了写，报的是库里那一跳的位置，读源码就看得出来，不需要知道某个属性的传染规则。
4. **不加新的语言维度。** 隐式参数是一个新的解析机制（Scala、Haskell 都为它设计了一整套规则）。默认参数 Dawn 已有，
   `caller()` 只是「一种取值在调用点决定的默认值」，与 Swift 的魔法字面量同构，规则也同样只有一条：必须是整个默认值。

代价：每一跳要写 `at: at`。只有「替调用者报错」的函数需要它，这类函数本来就少（本仓 std 公开面里只有三个，见第八节）。

## 三、语言规则

### 3.1 `Loc`

```dawn
# 编译器铸造、std/loc 拥有的不透明类型，目标是 String（与 Char 之于 std/char 同一个先例）
Loc
```

- **名字全局可见**，与 `Char` 一样进内建类型表：`panic` 的签名要提到它，库作者写 `at: Loc = caller()` 时不该先 `use`。
  代价是用户不能再声明叫 `Loc` 的类型（`` `Loc` is a builtin type and cannot be redefined ``）；本仓与 dawnop-site 的 `.dawn` 源里 0 处。
- **不透明，目标是 `String`**，值就是 `<path>:<line>:<col>` 这一串（路径与行列规则同 spec §8.2 的位置后缀）。
  选字符串而不是记录 `{ path, line, col }`：
  - 一个调用点的 `Loc` 是**一个字符串常量**：JVM 上是 `ldc`，native 上是 `emit_str_static` 的静态串，传它不分配；记录每次调用都要构造。
  - `panic(msg)` 省掉 `at` 时，降低把常量直接并进消息字面量，与 L2 的 Core **逐字节相同**（第六节），这是「对现有调用点兼容」的关键。
  - 不透明保证表示可以换：将来真要记录，std/loc 之外一行不改。
- **`Show` 与 `Display`** 都写成那串本身：`"${loc}"`、`show(loc)` 都是 `src/main.dawn:4:3`，与失败消息里 ` at ` 之后的部分逐字相同。
  `==` 与哈希是目标的（同一调用点相等）；`<` 不开放（不透明类型的既有纪律）。
- **std/loc 的函数**：`path(l) -> String`、`line(l) -> Int`、`col(l) -> Int`（从右切两个 `:`，路径里有 `:` 也对），
  以及 `here(at: Loc = caller()) -> Loc = at`（第 3.4 节）。
- **构造**：只有 `caller()`（与它的转传）能造出 `Loc`；std/loc 之外没有从字符串造 `Loc` 的路。
  于是 `Loc` 永远是编译器量出来的位置，不是谁随手写的串。

**「无位置」值**：std 没有展示路径（L1 规则），std 里省掉的 `caller()` 得到空串 `Loc`。`panic` 对它不加后缀，所以 std 内部自己的
`panic(msg)` 与 L2 逐字节相同。它不会流到用户手里：std 的公开函数只在自己的形参里**接收** `Loc`，从不把 std 内部量出的 `Loc` 交还调用者
（`here` 在 std 里被调用时例外，而 std 不这样调）。`path`/`line`/`col` 对它答 `""`/`0`/`0`。

### 3.2 `caller()`

内建 `fn caller() -> Loc`，**只能作为一个顶层函数形参的完整默认值**：

```dawn
pub fn expect_some[T](o: Option[T], what: String, at: Loc = caller()) -> T =
  match o {
    Some(v) -> v
    None -> panic("expected ${what}", at: at)
  }
```

- 默认值**整个**就是 `caller()` 才算（Swift 同规）。`at: Loc = id(caller())`、函数体里的 `caller()`、const 里的 `caller()`，
  都报 `` `caller()` can only be the whole default value of a parameter ``，hint：
  `` declare `at: Loc = caller()` on the function, and pass `at` on to what reports the failure ``。位置在 `caller` 这个名字上。
- 当值用（`let f = caller`）报 `` `caller` cannot be used as a value ``（与 `dbg` 同理：没有调用点）。
- 形参类型照常检查：`x: String = caller()` 是普通的类型不符（`parameter `x` is String but its default value is Loc`）。
- 用户自己定义的 `fn caller` 照常遮蔽内建（spec §10.6）；遮蔽后 `= caller()` 是普通默认值，与本节无关。
- 默认参数的其它规则不变：只有顶层函数收默认值，局部 fn、lambda、trait 方法、effect operation 照旧报错。
  于是 `c[i]` 的越界（`Index` impl 是 trait 方法）**不在** L4 的覆盖面内，见第九节。

spec §3.1「在声明处的作用域求值」由此多一款**具名例外**：`caller()` 不在声明处求值，它的值由调用点决定。它满足「默认值必须纯」（它是常量）。

### 3.3 调用点展开

省掉一个 `caller()` 默认的实参时，那个实参的值是**这次调用**的位置：

- 位置指向调用表达式的起点，与 L2 同一把尺子：`f(..)` 是 `f` 这个名字，方法式 `o.f(..)` 与管道 `x |> f` 是左边的起点；
  行列从 1 起，列按码点。
- 路径是**调用点所在模块**的展示路径（L1）：项目里 `src/…`，单文件 `p.dawn`，`[deps]` 包的模块里是 `<包名>/<路径>`，std 里是「无位置」。
  跨模块调用不影响：`app/src/main.dawn` 调 `[deps]` 包 `check` 的 `check.positive(n)`，`at` 是 `src/main.dawn:9:3`；
  包内部自己省掉 `at` 调 `panic`，报 `check/rules.dawn:12:5`。
- 写了实参（`f(x, at: l)` 或位置实参）就用写的，与普通默认值一样。

### 3.4 嵌套转发

```dawn
fn assert_eq[T: Eq + Show](a: T, b: T, at: Loc = caller()) -> Unit =
  if a != b { panic("${show(a)} != ${show(b)}", at: at) }

fn assert_sorted(xs: List[Int], at: Loc = caller()) -> Unit =
  assert_eq(xs, sort(xs), at: at)        # 转发：报 assert_sorted 的调用者

fn assert_small(n: Int) -> Unit =
  assert_eq(n < 10, true)                # 不转发：报这一行，assert_small 自己没有 at
```

- 每一跳显式。`assert_sorted([2, 1])` 写在 `src/t.dawn:20:3`，消息是 `[1, 2] != [2, 1] at src/t.dawn:20:3`。
- `assert_small` 没声明 `at`，所以它里面的 `assert_eq` 报的是 `assert_small` 体内那一行。这是**刻意的**：
  一个函数要不要替调用者报错，由它的签名说了算。
- 要一个当前位置的值（测试里比对、经函数值调用时补实参）：`loc.here()`。它本身就是 `at: Loc = caller()` 的函数，
  所以「`caller()` 只在默认值位置合法」不需要第二条例外。

### 3.5 函数值

函数当值用丢默认值（spec §3.1），`caller()` 默认也一样：`let f = panic` 的类型是 `fn(String, Loc) -> Never`，
调用时要给 `Loc`（通常是 `loc.here()` 或手里转发的 `at`）。这取代 L2「经值调用不带位置」那条：现在经值调用**必须**给位置，
所以也一定带位置。本仓与 dawnop-site 把 `panic`/`todo`/`expect` 当函数值的地方：0 处（`git grep` 只命中同名局部变量）。

### 3.6 `panic`、`todo`、`expect` 的新签名

```dawn
fn panic(msg: String, at: Loc = caller()) -> Never
fn todo(at: Loc = caller()) -> Never
fn expect[T](o: Option[T], msg: String, at: Loc = caller()) -> T
```

- **源码兼容**：现有调用都省掉 `at`，含义与 L2 相同，消息逐字相同。
- 裁决只点了 `panic`/`todo`；`expect` 是 L2 的同一族（都在 `sited_arity` 里），也是调研草案的示例本身，一并加，否则 `expect` 会成为
  三个失败内建里唯一不能转发的。`assert` 与后缀 `!` 是语法不是调用，没有形参可加，维持 L2；`dbg` 的行头不是失败，维持 L3。
- 转发时（`at` 不是本调用点的常量）消息是 `<msg> at <at>`；`at` 是「无位置」则不加后缀。`todo(at: l)` 是 `not yet implemented at <l>`。
- builtin 表此前一律无默认（K19 把 `parse_int` 迁 std 就是因为这个）。那条限制的原因是默认值要在**声明模块**合成 `f$default$k`，
  builtin 没有声明模块。`caller()` 默认**不合成函数**（值在调用点决定），所以 builtin 带它不撞那条限制；builtin 的普通默认值仍然不收。

## 四、实现形状

### 4.1 签名

- `Sig` 加一个字段 `caller_params: List[Int]`：取调用者位置的形参下标，空即没有。`param_defaults` 仍是给读者的原文（`Some("caller()")`），
  照旧不从文本里回读语义；判断「这个默认是不是调用者位置」只看新字段。它随 `ModExports` 走，跨模块、`[deps]` 的调用点只看签名就知道。
- **注册期定**：声明的形参默认值的 AST 恰好是无实参的 `caller` 调用，且 `caller` 在本模块不被遮蔽时，记入 `caller_params`。
  这在签名阶段就能答，不必等函数体检查（别的模块的调用点比函数体先到）。
- 这样的形参**不合成** `f$default$k`：`check_param_defaults` 对它给 `None`，`check_param_default` 只做两件事：拒绝它出现在别处、做类型检查。
- builtin 表：`panic`、`todo`、`expect` 的 `bsig` 加 `at` 形参与 `caller_params`；`caller` 本身进表（`fn caller() -> Loc`）。
  内建镜像 `selfhost/builtins.dawn` 跟着写默认值，`builtin-decl-contract` 的渲染与回读要能读 `= caller()`（K19 记下的那件事，只为这一种默认值做）。

### 4.2 检查器

- `default_call`（`checker.dawn:8120`）：省掉的形参在 `caller_params` 里时，不生成 `f$default$k` 调用，而是一个占位节点
  `XCallBuiltin("caller", [], …, lo, hi, Loc)`，`lo`/`hi` 是**这次调用**的跨度。`arrange_call_args` 的三种形状都不用改：
  占位节点是纯的、零元的，后面的默认值读它时照常绑成局部量。
- `check_call`：解析到内建 `caller` 的调用一律报 3.2 的错。注册期认定的那种默认值根本不作为表达式检查（`check_param_defaults`
  只核类型），所以凡是走到 `check_call` 的 `caller()` 都在别处。`check_fn_value` 拒绝 `caller` 当值。
- `arrange_call_args` 判断「省掉的默认值要不要先把实参绑成局部量」（`reads_params`）时不算 `caller()` 默认：它不读任何形参。
  落地时第一版漏了这一条，后果是**每个** `panic(msg)` 都走了绑定路径，消息变成局部量，降低时折不成字面量，
  LSP 也按跨度配不上实参。第六节的逐字节对照就是在这里抓到的。

### 4.3 声明出口（L2 的缝）

`tast_positions` 把占位节点换成**位置常量**：`sited_arity` 加 `caller`（0 个实参），尾随的 `XStr` 是 `<path>:<line>:<col>`（不带 ` at `）；
std 里没有展示路径，不追加，于是降低得到空串。`panic`/`todo`/`expect` 从 `sited_arity` **删掉**：它们的位置改由 `at` 形参带，
L2 那条「按实参个数判别是否带位置」的特判随之消失，`split_site` 只剩 `dbg` 与 `caller`。

位置在声明出口才解析，所以 LSP 会话里声明只是移动时位置跟着走（`tast_positions` 头注释的论证原样适用），与 L2 同源。

### 4.4 降低

- `caller` 占位降成一个类型为 `Loc` 的绑定：`{ let v: Loc = "src/m.dawn:4:3"; v }`（std 里是空串）。`Loc` 不透明，
  运行期就是 `String`，所以后端得到的仍是一个字符串常量；绑定是给读 Core 的人看的：Core 的字面量没有类型，
  一个带类型的绑定是 dump 里分辨「位置」与「程序自己写的长得像位置的字符串」的唯一办法，Core 差分的归一按它认（第六节）。
- `panic`/`todo`/`expect` 的 `unsite` 改为读最后一个实参：
  - 是字面量（省掉 `at` 的常态）：空串不加后缀，否则把 ` at <loc>` 并进消息字面量，**与 L2 的产物同一个 `CStr`**；`todo` 照旧降成
    `panic("not yet implemented at …")`，std 里的 `todo()` 照旧是 `todo` intrinsic。
  - 不是字面量（转发）：`msg ++ loc_suffix(at)`。`loc_suffix` 是降低内部的名字（与 `dbg` 的展开同类，不进 Core），
    展开为「空串答空串，否则 `" at " ++ at`」，只在失败路径上执行。
- 两个后端、解释器、运行时零改动：它们看到的仍是一个 `panic` intrinsic 加一个字符串。

### 4.5 std/loc

新模块 `std/loc.dawn`（`modules.txt` 里排在 `fmt` 之后，读行列用 `fmt.parse_int`）：`impl Show[Loc]`、`impl Display[Loc]`、`path`/`line`/`col`、`here`。`Loc` 由编译器铸造
（`TyOpaque(LOC_OPAQUE_ID, "Loc", "std/loc", [], TyString)`，id 取负数，与 `ev$Pack` 一样不挪 `first_minted_id`），
std/loc 是它的拥有者，所以在 std/loc 里 `Loc` 与 `String` 互相可赋值、别处不行。`stdsrc` 重新生成。

## 五、comptime、LSP、Playground

- **comptime**：占位在降低之前已是常量，解释器看到的就是字符串。`const HERE = loc.here()` 的值是这条 const 声明里那个调用的位置；
  comptime 里 `panic(msg, at: at)` 失败时消息与运行期逐字相同（L2 5.3 的论证）。钉一条 `interp_test`。
- **悬停 / 签名帮助 / 补全**：签名照常渲染 `at: Loc = caller()`；悬停 `caller` 显示 `fn caller() -> Loc` 与文档。
- **内联提示（C4，省掉的默认实参）**：`caller()` 默认**不显示**。它的值就是读者正看着的这个调用的位置，显示出来是噪音；
  不屏蔽的话，仓里每个 `panic(..)`、`.expect(..)` 后面都会多一个 `at: caller()`。`lspinlay` 的 `default_args_hint` 跳过 `caller_params`
  里的形参；`with_default_values` 不对它求值。
- **实参配对**：LSP 的 `walk_call_args` 对「省掉默认值的调用」已按跨度配对，占位节点的跨度是整个调用，不会被当成作者写的实参。
  `lspq` 两处 `split_site`（3050、3152 行）随 `sited_arity` 的收缩只剩 `dbg`。lsp-diff 是验证手段。
- **Playground**：`Loc` 的路径就是展示路径，单文件是 `prog.dawn:L:C`，不含工作目录；`exec.dawn` 对运行输出的 `strip_dir`（L1 的纵深防御）不变。

## 六、差分与 golden

- **现有调用点不动**：省掉 `at` 的 `panic`/`todo`/`expect` 降低后与 L2 是同一个 `CStr`。实测：用本刀的工具链与基线
  （`origin/main` 自举出的工具链）各编**同一份基线源码**，十个 emit 语料（selfhost、site、playground、web、json 与五个示例）
  逐个 `__emit`，除了 std 多出的 `std/loc.class` 之外**逐字节相同**；selfhost 里数以千计的 `panic`/`todo`/`expect` 一个字节没动。
- **会变的**（预期，照实声明 `Emit-Change`）：
  - `doc --builtins`：`panic`/`todo`/`expect` 的签名多 `at`，多一个 `caller`，内建类型多 `Loc`，std 多 `std/loc`。
  - `lsp`：补全与签名里的这几个签名文本。
  - `emit selfhost` 等：std 多一个模块，`stdsrc` 重生成；std 的 jar 是否进 emit 语料以实测为准。
- **Core 差分归一**：`selfhost-core-diff.sh` 原先只归一 ` at <file>.dawn:N:N`。`Loc` 作为值传给函数时，Core dump 里是

  ```text
  let v1 : Loc
    str "src/t.dawn:20:3"
  ```

  第二条规则只认这个形状：**紧跟在 `let <名> : Loc` 之后**的 `str "<file>.dawn:N:N"`，行列归一。不按字符串的样子认：
  程序自己写的 `"x.dawn:1:2"` 是程序计算用的值，照原样比。两条规则搬进 `scripts/core-site-normalise.py`，它的 `--selftest`
  钉住「像位置的用户字符串不归一、`Loc` 绑定归一」，挂在 tree-policy（本机 0.01 s）；负控：去掉「前一行是 `Loc` 绑定」的条件，
  自测红在 `str "x.dawn:1:2"` 那一条。selfhost 自己不调用带 `caller()` 默认的函数，所以 selfhost 的 Core 里没有这种绑定。

## 七、测试与负控

- **两后端**：`scripts/spike-native/caller_loc.dawn`（`matrix.txt` 登记，带 `.exits-nonzero`）：用户函数省掉 `at`；两跳转发与
  「不转发」的对照；`panic` 经函数值、用 `loc.here()` 补实参；`expect` 与 `todo` 的转发；`loc.here()` 的 `Display`/`line`/`col`/`path`；
  `"ä🎈"` 之后的码点列；`const` 里的 `loc.here()`；`show(Loc)`；最后一个不捕获。`.expect` 按手算的行列写，JVM 与 native 各自对它比，
  `stderr`/`exit` 两后端互比。
- **单元**：checker「a caller() default is the call's site, and is legal nowhere else」（注册期的 `caller_params`、遮蔽、四条拒绝、
  `panic` 省掉与写出 `at`）；`tast_positions` 的占位换常量、std 无位置；`interp_test` 的 comptime（`const A: Loc` 折成位置串，
  转发的 `panic` 在 comptime 报调用点）；std/loc 自己的四条测（含路径带 `:` 的 `c:/work/src/main.dawn:12:7` 从右切）；
  LSP：悬停 `panic` 显示 `fn panic(msg: String, at: Loc = caller()) -> Never`、悬停插值消息里的 `40` 仍得 `Int`，
  内联提示对用户函数与内建的 `caller()` 默认都不显示、同一调用里的普通默认照常显示。
- **checker 语料**：`scripts/checker-corpus/cases/caller_rules.d`，带 `[deps]` 的两包项目：五条拒绝按序钉住；入口省掉或转发包函数的 `at`
  无诊断。另外三个既有 golden 只因「内建类型清单多 `Loc`」「std 模块清单多 `std/loc`」两处提示文本而重录。
- **`[deps]` 端到端**（本机 scratch，不进仓）：入口 `src/main.dawn` 调包函数 `check.positive(-1)`，消息是 `not positive at src/main.dawn:10:22`。
- **负控**（各自先红再还原，数字见 L4 报告）：
  1. `default_call` 不认 `caller_params`：工具链自举即红（`codegen: unknown fn std/str.expect$default$2`）；
  2. `caller_loc.expect` 第 8 行列号 40 改 41：`caller_loc:jvm`、`caller_loc:native` 都红，还原后 `differential ok`；
  3. 降低把字面量 `at` 也走 `loc_suffix`：用新工具链编基线的 `examples/errors/barriers.dawn`，`barriers.class` 不再与基线相同；
     编基线 selfhost 有 57 个 class 不同。还原后两者都只多一个 `std/loc.class`（第六节）；
  4. Core 归一：`core-site-normalise.py` 去掉「前一行是 `Loc` 绑定」的条件，`--selftest` 红在用户字符串 `"x.dawn:1:2"`。

## 八、本刀范围与后续

本刀（L4）：语言能力（`caller`、`Loc`、`caller_params`、默认值展开、拒绝）、`panic`/`todo`/`expect` 签名、std/loc、spec 小节、两后端测试、LSP。

后续单独开刀（每刀都是公开面变化，按「改 std 公开面必跑 run-diff」与各包版本号走）：

| 候选 | 为什么不在本刀 |
|---|---|
| std 的 `str.at`、`bytes.at`、`bytes.buf_at` 加 `at` 并转发 | 在 inflate、sha2 的热循环里；多一个常量实参的代价要实测再落（CONTRIBUTING：性能断言要有出处） |
| `web` 的 header 拒绝、`tea-dom` 的 render 拒绝、tileir 的 kernel 拒绝 | 各包的公开签名与版本；tileir 在 tile 路径上，要等 tile.yml |
| `c[i]` 越界报调用者位置 | `Index` 是 trait 方法，不收默认值；若要做，是 L2 式的 `XIndex` 带位置，另行设计 |

## 九、不做的（理由）

- **隐式调用者位置**（Rust `track_caller`、Scala 隐式、Haskell `HasCallStack`）：不进类型，经函数值静默丢失（Rust 文档自称 hint）；
  显式默认参数在签名里看得见，丢失规则复用「函数当值丢默认值」。裁决已定，第二节给出处。
- **`caller()` 出现在默认值之外**（Zig `@src()` 那样随处可写）：随处可写的「当前位置」由 `loc.here()` 提供，不必再开一条语法例外；
  把 `caller()` 限在默认值位置，规则就只有一句（Swift 同规）。
- **`Loc` 做成公开记录 `{ path, line, col }`**：每个调用点构造一次记录，`panic(msg)` 也没法与 L2 的常量逐字节相同；用户能伪造位置。
  不透明串加三个访问函数，读得到同样的信息。
- **`Loc` 只在 `use std/loc` 后可见**：`panic` 的签名、库作者的 `at: Loc = caller()` 都要提到它；要么每个写 `at` 的模块多一行 `use`，
  要么内建签名提到一个当前作用域里不存在的名字。全局名的代价（用户不能声明 `type Loc`）在本仓与 dawnop-site 为 0 处。
- **std 用自己的路径（`std/list.dawn:120:5`）代替「无位置」**：L1 已裁 std 无展示路径；std 的行号对用户没有用，且每次 std 改动都会动产物。
- **让 builtin 带普通默认值**：普通默认值要在声明模块合成函数，builtin 没有声明模块；K19 的既定方向是迁 std。本刀只开 `caller()` 这一种不合成函数的默认值。
- **`at` 之外的名字约定**（`loc`、`site`、`caller`）：裁决已用 `at`，读起来是 `panic(msg, at: at)`，与消息里的 ` at ` 同词。不做强制，只是约定。
- **多个层级的位置（调用栈）**：一个 `Loc` 是一个点。要两层就声明两个形参；把栈做进 `Loc` 就是运行期栈迹，第一刀已否。
- **`ForeignError` 带 `Loc` 字段**：位置是消息的一部分（L2 已裁），决定看 `kind`。

## 出处（抓取于 2026-10-05）

- Swift SE-0274：https://github.com/swiftlang/swift-evolution/blob/main/proposals/0274-magic-file.md
- Rust `track_caller`：https://doc.rust-lang.org/reference/attributes/codegen.html
- Zig `@src()`：https://ziglang.org/documentation/master/ （`@src` 一节）
- Scala `sourcecode`：https://github.com/com-lihaoyi/sourcecode
- Haskell `GHC.Stack`：https://hackage-content.haskell.org/package/base-4.22.0.0/docs/GHC-Stack.html （见 2026-10-03 调研）
- Go `runtime.Caller`：https://pkg.go.dev/runtime#Caller
- Kotlin：语言参考里没有调用点位置机制；默认实参在调用点的相关讨论只到 KT-18695（访问默认值，不是位置）：https://youtrack.jetbrains.com/issue/KT-18695
