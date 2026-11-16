# 编译器代写调用记录：效果的 `calls` 子句与 Core 变换

> 状态：**current**（R4-f0 设计、R4-f1 钩子声明加 Core 变换、R4-f2 删除手写 marks 均已落地；
> 第十节记 f2）。依据：W3-R 终局调研（Rust `#[track_caller]`、tracing `#[instrument]`、GCC
> `-finstrument-functions`、Scala sourcecode、Swift SE-0274 的一手出处）与补裁七、补裁八。
> 提交哈希见文末「落地进度」。

<!-- 为什么写这篇：tileir 里 228 处 `called`/`called_bare`/`user_body` 是一份必须与代码同步的平行真相。
     把它变成编译器按声明生成的东西，是与 Rust `#[instrument]` 同族的通用机制；这里写清它生成什么、
     在哪一层生成、凭什么不动不含该声明的程序，以及它与手写版本的差在哪里。 -->

## 一、动机与非目标

**动机。** `packages/tileir/src/dev.dawn` 用三个包装函数手写调用记录：`called(name, at, body)` 与
`called_bare(name, body)` 在公共函数体前后各发一个 `Dev` 操作，`user_body(f)` 在收到的闭包前后发两个。
2026-11-15 在 `06b99b28` 上的重数是**228 处使用点：185 个 `called(`、29 个 `called_bare(`、14 个
`user_body(`**（`scripts/call-records-contract/derive_fixture.py --count` 的括号匹配结果，跳过注释与字符串；
设计草稿数到 227 是少数了一处 `called_bare`，补裁的 228 是对的），外加四个定义与四个 `Dev` 钩子操作。
这份协议需要与代码同步，R2 已经暴露过它的腐烂（固定 helper 名单、对 `called(` 的文本扫描）。

编译器按声明生成它，则是与下列系统同族的通用机制，任何以效果为录制器的库都可以声明，不是只给一个包的特例：
GCC 的 `-finstrument-functions`、Rust tracing 的 `#[instrument]`（对照见第六节）。

**非目标。**

1. 不用 observe 视图替代录制器的标记栈：四个钩子操作、录制器的处理臂、`Snap` 的栈式 marks、trial 回滚都保留，
   只是从「手写协议」变成「编译器目标」。没有已知能过 Playground 门的表示（补裁六）。
2. 不给任意用户函数代写，没有逐函数属性。
3. 不碰 `observe` 孪生机制；其去留在 R4-f2 之后另裁。
4. 不改 `caller()`、`Loc` 与 `panic(at =)` 的显式归责（spec §8.4）：`at` 在这里只是被读取。

## 二、语法与语义

### 2.1 拼写

三个候选，约束是命名语义规则（spec §1.3）、上下文关键字只在唯一语法位置有意义（§1.4）、仓库没有属性语法。

| 候选 | 形状 | 取舍 |
|---|---|---|
| S1 操作修饰词 | `call_enter fn t_call_enter(..)` | 四个新上下文关键字；钩子散在九十多个操作之间，读者要扫全表；`fn` 前多一个标识符的位置要 parser 特判 |
| S2 独立声明块 | `calls Dev { enter = .. }` | 钩子与效果分离，要另立「同模块、至多一个」规则，顶层多一类声明，进符号表与 `doc`/LSP |
| **S3 效果头子句（采纳）** | `effect Dev calls(enter = .., exit = .., body_enter = .., body_exit = ..) { .. }` | 一个上下文关键字；钩子与效果同处，「同模块至多一个」由语法结构保证；`role = op` 沿用具名实参外观 |

`calls` 是上下文关键字：只在「效果名（及其可选的 Scope 参数）之后、`{` 之前，且下一个 token 是 `(`」时有意义，
别处仍是普通标识符（`fn calls(calls: Int)` 合法）。词表登记处：parser 的 `is_word` 站点、spec §1.4 表
（十五个变十六个）、编辑器语法 `x-dawn-contextual-keywords` 与一条上下文模式；`doc-check` 与
`editors/vscode/test/scope-contract.js` 从 parser 读，缺一处就红。

检查（`passes.resolve_calls_clause`）：四个角色都必须写、各用各的操作、名字必须是本效果自己的操作，
`enter` 的形状是 `fn(String, Option[Loc]) -> Unit`，其余三个是 `fn() -> Unit`；不满足是编译错误，
诊断落在不合规的角色名上。**`ctl effect` 上写 `calls` 是编译错误**（parser 报，落在 `calls` 这个词上）：
续延可以被放弃，放弃后 `enter` 永远等不到 `exit`，静默忽略会让记录悄悄不再闭合。带 Scope 参数的效果同理拒绝：
生成的调用无从提供 scope key。

### 2.2 哪些函数被代写

规则以**效果**为键，不以包为键（补裁八第 2 条）。函数 `f` 被代写，当且仅当：

1. `f` 的**声明的**效果行含某个带 `calls` 的效果 `E`（`eff_labels(sig.eff)`；由效果变量实例化而来的不算，
   所以同一函数不随实例化变形），且
2. `f` 是 `pub fn`，或是 impl 方法。

| 类别 | 是否代写 | 说明 |
|---|---|---|
| 任何模块里行含 `E` 的 `pub fn` | 是 | 作者模块的 `pub fn fa_exp(.. ) !Dev` 同样适用，不要求声明 `E` 的包 |
| impl 方法（运算符、`staged_*` 等），行含 `E` | 是，`at = None` | 方法不接默认参数 |
| 私有 `fn`、`pub(pkg)` | 否 | 它的操作归属于到达它的那次公共调用；与今天 `called` 只包公共面的规则一致 |
| 局部 `fn`、lambda、trait 默认体 | 否 | 没有稳定的声明名 |
| 行不含 `E` 的函数 | 否 | **U0 的结构依据** |

- **`name`：** 声明名（impl 方法取方法名）。今天 17 处手写名与声明名不同，补裁八第 3 条裁定**改展示名为声明名，
  不留映射表**，清单见第四节。
- **`at`：** 取函数唯一的、默认值为 `caller()` 的形参（`Sig.caller_params`）的值；没有则 `None`
  （即今天的 `called_bare`）；多于一个是编译错误。代写**读取**它，不改 `caller()` 的任何规则，Core 里没有新的隐式参数。
  这与 Rust `track_caller`（隐藏实参）形成对照：Dawn 已经有显式的同构物。
- **闭包形参：** 函数每个函数类型形参，若其声明的效果行含 `E`，入口处换成薄包（2.4）。`!e` 效果变量形参**不包**
  （只认地面标号）；tileir 全表没有这种形参（第四节 Q5）。
- **泛型、默认参数、单态：** 与代写无关：Core 传字典不单态化，默认值在调用点求值。

### 2.3 enter 与 exit 的位置

被代写函数在 Core 里的形状：

```
let <bracketed params> = thin closures        # 2.4
enter(name, at)
let r = <body>
exit()
r
```

`<body>` 里每一个 `CReturn`（`return`、`?` 的提前返回）都改成「先求值，再 `exit()`，再返回」。三条出口：

1. 块尾值：尾部 `exit()` 之后返回。
2. `return e` 与 `?`：`let t = e; exit(); return t`。**先求 `e` 再 `exit`**：返回表达式自己可以调被代写函数，它们的记录必须先闭合。
3. `panic`：不 `exit`。与手写一致：`panic` 终止录制运行，被 `catch_panic` 吃掉的情形由录制器的 `Snap` 回滚配平。
   返回类型为 `Never` 的函数不插尾部 `exit`。

实现上不拆内层函数（会让观察孪生多出一个调用帧与 Definition 身份），也不用 `CBreak` 汇聚（Core 的 `CBreak` 不带值）：
`LSt` 多一个字段 `on_return: Option[CExpr]`，降低 `return`/`?` 的两处（`emit_return`）看它：为空就是原来的
`CReturn`，非空就先 perform 出口。`lift_lambda` 把它重置为空并在返回后恢复：闭包里的 `return` 离开闭包，不离开写它的函数。

### 2.4 闭包薄包与原样转发

被代写函数的每个被包形参 `f`，Core 序言里 `f` 的符号绑定到一个**薄闭包**，真正的形参换成新符号 `raw`：

```
薄闭包(args) = { body_enter(); let r = raw(args, pack); body_exit(); r }
```

薄闭包是一个提升出来的普通函数，只捕获 `raw`，转发它自己收到的 evidence pack（它的行就是被包闭包的行，所以 pack 原样给），
`body_enter`/`body_exit` 经这个 pack 里 `E` 的节点取出。函数体里对 `f` 的每次使用读的都是薄闭包，每次调用一对 `body_enter/body_exit`，
循环里的闭包每轮一对，与今天 `user_body(() => body(i))` 一致。

**原样转发不叠包。** 被代写函数把形参**原样**作实参交给另一个被代写函数的同类被包形参时，改传 `raw`，由被调方包一次
（`forward_raw`：按 `prog_fns` 里被调方的 `Sig.calls.bodies` 判，静态可判）。否则 `body_enter` 双层嵌套，
录制器靠嵌套位置分 `KernelBody` 与 `InnerBody`（变异体 `forwarded-closure-bracketed-twice` 专盯它）。

### 2.5 递归、内联、`ctl`、comptime

- **递归：** 每次递归调用都是一条记录。被代写函数**不做自递归尾调用成循环**（spec §12.4）：`plain` 判定里排除，
  `tail` 旗标为假。今天的 marks 同样没有（`called` 的体是闭包，本来不是尾调用）。
- **内联：** Core 没有内联器；JVM 由 JIT 做。GCC 的文档同样要求「被内联的函数仍视为进入/退出」。生成的 enter/exit 是真实 perform，不会被删。
- **`ctl effect`：** 拒绝，见 2.1。
- **comptime：** 带该效果的函数不能在 comptime 求值（§7.2），`lower_fn_only` 的入口不受影响（`sig.calls` 只在 `lower_fn` 读）。

## 三、实现位置与不变量

- **检查器：** `EffectI.calls: Option[EffectCalls]` 把四个角色解析成证据记录里的操作下标；`Sig.calls: Option[CallPlan]`
  （`eid`、四个下标、`name`、`at` 形参下标、被包形参下标）在 `pass_fn_signatures`（`pub fn`）与 impl 方法签名处由
  `call_plan_of` 算出。放在签名上，因为别的模块的调用点要知道被调方是否已经包了闭包形参（转发），而签名是跨模块的东西。
- **降低：** `ir/lower.dawn` 的 `lower_fn`，`lower_expr` 之后、构造 `CFun` 之前。代写与证据调用约定（`ev_env`）、`at` 形参符号、
  `f.sig` 在同一处可得；产物是普通 `CFun`，其后的 reach、尾调用、lint 与两个后端不认识「钩子」。
  操作的 perform 就是源码里一个操作调用降低出来的东西：证据记录的字段读加闭包调用，参数后接记录的 `env`。
- **I1 U0：** `sig.calls == None` 时 `lower_fn` 走原路，同一棵 Core。`emit_return` 在 `on_return` 为空时不取新符号，
  符号编号都不变。含钩子**声明**但没有函数行含该效果的程序同样不变。
- **I2 配平：** 每个被代写函数的每条非 panic 出口恰一对 `enter/exit`；每次薄闭包调用恰一对 `body_enter/body_exit`。
- **I3 后端无关：** 变换发生在 Core 之前，不提 JVM 或 native；两端一致性靠 Core 同构加跨后端合同（第四节）。
- **I4 设备字节：** 钩子只在宿主录制层，tilebc/MLIR 与它们无关。

## 四、f1：并存期的逐字段对拍

（这一节是 f1 当时的状态：手写 marks 与代写并存。f2 之后手写版已删除，下表的“手写”一侧由
`scripts/call-records-contract/run.py --baseline` 指向删除前的检出重现；现状见第十节。）

f1 **不删任何手写 mark**，在分支上提供两份 tileir，同一批 kernel 程序各编一次、各录一次，比较调用表。手写版就是预言，不需要新预言。

- **派生**（`scripts/call-records-contract/derive_fixture.py`）：对 `dev.dawn` 按**括号匹配**逐个去掉 228 个包装
  （跳过字符串与注释，不认识的形状直接拒绝，不按行模式），删掉四个定义，把 `pub effect Dev {` 换成带 `calls(..)` 的头。
  派生物只在测试夹具里，不替换正式 tileir。
- **录制**（`run.py`）：两份 tileir 的 `prog.dawn` 同样打补丁：录制器把它看到的调用表和每个调用/body 标记的日志放在返回的
  `TileProg.producer` 里（补丁在测试夹具，产品代码不变），harness 对每个 kernel 打印。
- **语料：** `scripts/tile-golden` 的 256 对 golden（`trace(name)` 的 255 个程序加与 `vadd` 同程序的 `vadd_producer`，含
  `flash_attn`、`flash_attn_bf16`、`flash_attn_bf16_demo`），以及 Playground 的 flash_attn 样例与 `tile_vadd` 样例。
- **字段：** 每行 `name`、`at`、`parent`、`ops_from/ops_to`、`globals_from/globals_to`，加每个 body 标记的 kernel/library 分类。

结果（`06b99b28` 加本分支）：

| 语料 | 程序 | 调用行 | 差 |
|---|---|---:|---|
| 256 对 golden | 255 | 4588 | 展示名（下表）与 `staged_for` 的 `at`（下文）两类，其余字段与 body 分类全等 |
| Playground flash_attn、vadd 样例 | 2 | 49 | 同上 |

**展示名：** 手写名与声明名不同的 17 处站点（`dev.dawn`，行号为 `06b99b28`）：

| 站点 | 手写名 | 代写名（声明名） |
|---|---|---|
| 2816 `staged_for` | `d_range` | `staged_for` |
| 2832 `var_open` | `carry` | `var_open` |
| 2833 `var_get` | `get` | `var_get` |
| 2834 `var_set` | `set` | `var_set` |
| 2840 `staged_if` | `if` | `staged_if` |
| 2892–2899 `tile_add/sub/mul/div/neg` | `add/sub/mul/div/neg` | 私有函数不被代写，行由 impl 方法给出，名同手写（无差） |
| 3022 `from_float` | `lit` | `from_float` |
| 3027–3047 impl `add/sub/mul/div/rem` | `idx_add/idx_sub/idx_mul/idx_div/idx_rem` | `add/sub/mul/div/rem` |
| 3052 `from_int` | `idx_const` | `from_int` |

255 个程序里实际出现的差名共十二对，全部在 `scripts/call-records-contract/declared-names.txt`（只在对拍里用，不进产品代码）：
`d_range→staged_for`、`carry→var_open`、`get→var_get`、`set→var_set`、`if→staged_if`、`lit→from_float`、
`idx_add/idx_sub/idx_mul/idx_div/idx_rem→add/sub/mul/div/rem`、`idx_const→from_int`。f2 删 marks 时，Playground 可见文字随之改成右列
（补裁八第 3 条），并在 PR 里列出这份新旧对照。

**一处不是名字的差：`staged_for` 的 `at`。** 手写 `called("d_range", r.at, ..)` 报的是 `DRange` 创建时存下的位置 `r.at`，
`staged_for` 是 trait 方法，没有 `at: Loc = caller()` 形参，代写给 `None`。对拍里这一类共 59 行（kernel 里每个 `for .. in d_range(..)` 一行），
其余字段全等。这不是机制的不稳，是规则的边界：区域位置的来源是形参之外的字段。f2 要在两条里选：接受 `None`
（`effect-provenance-design` P2 本来就要把区域位置改成 `for` 的使用处），或给 `at` 的来源规则加「形参的 `Loc` 字段」（范围更大，不建议）。
**这一条需要裁决，不在 f1 里自行决定。**

**派生包自带的测试。** tileir 的 309 个 test 块在派生包上跑（`run.py` 默认执行）：303 个通过，6 个失败，且失败集合是固定的：
都是 `d_range`/`staged_for` 这一处，要么断言名字 `d_range`，要么断言区域创建点的行号（含「拒绝信息里的 `inside the body of a d_range at ...`」这类
用户可见的调用栈文字）。其余断言的调用名、父子关系、操作区间，以及拒绝信息里的调用栈，代写版全部成立。这 6 项就是 f2 改展示名时
要同步改的测试。

**手写 mark 与代写并存。** 作者模块里的私有 `fn`（kernel、`fa_exp`、`fa_divide`）不被代写，它们的手写 mark 在 f1 照常工作，对拍证明了这一点。
f2 若要删净作者侧 mark，作者函数须是 `pub`，而一个 `pub` 的 kernel 入口本身会成为一条记录：录制器的 `kernel_side`
只在顶层或 `KernelBody` 里认行，入口之内的调用都成了 `Inner`，Call 表塌成一行。这是规则键控到「作者模块的每个 `pub !Dev` 函数」时必须同时
解决的录制器政策，属 f2 的显式任务。

### 变异体（负控）

作者层与编译器层各一类，全部要求**红在它名下的原因上**（红了但原因不对算控制失败）：

| 层 | 变异体 | 红的原因 |
|---|---|---|
| 作者 | 效果声明去掉 `calls` 子句（函数不再属于被记录的面，等价于旧的删 mark） | 调用行数 N 对 0 |
| 编译器 | 漏函数：`load_cell` 不出计划 | 行数与名字差 |
| 编译器 | 错名：`name ++ "_"` | `name X vs X_` |
| 编译器 | 错父：`exit` 放到函数体之前 | `parent`、`ops_to` 差 |
| 编译器 | 丢闭包薄包：被包形参列表恒空 | body 分类与 `parent` 差 |
| 编译器 | 异常路径不配平：`return`/`?` 不先 `exit` | 转录本（`cases/records.dawn`）在提前返回处差 |
| 编译器 | 转发叠包：`forward_raw` 不换回 `raw` | 转录本与 body 分类差 |
| 编译器 | 缺 `enter` | 「a call mark closes nothing」或行数差 |

（`mutants.py author|compiler`；编译器层每个变异体重建一次工具链。）旧负控 `--check-call-origin`、`entry6-source-controls`、
xmap-samples 在 f1 不动：手写 mark 还在，它们照旧运行。

### Q5：闭包形参带效果变量的情形

补裁八第 5 条要求 f1 核对 tileir 全表。结果：**tileir 没有任何 `!e` 效果变量**（`dev.dawn`、`prog.dawn` 里除 `!Dev`、`!io`、
`!Fs` 等具名标号外没有小写效果原子）。被包形参共有的形状是 `body: fn(..) -> T !Dev ^{c}`：地面标号 `Dev`，加一个能力变量 `^c`。
`^c` 是 capture 多态，与效果变量无关，不影响判定。v1 规则因此只包「声明行含地面 `E` 标号」的形参，`!e` 形参不包：
一个对 `e` 多态的函数收到的闭包可能带 `E` 也可能不带，随实例化改变形状正是 2.2 要避免的。这条在 f1 里无对象可作用，
留作规则的明文边界，等第一个用 `!e` 的录制库出现再裁。

### 全局的计数

`scripts/call-records-contract/derive_fixture.py --count packages/tileir/src/dev.dawn`：**called 185、called_bare 29、user_body 14，合计 228**。

## 五、性能断言与出处

只引已有实测并标条件；未实测项标「待 R4-f3」。

| 断言 | 数 | 条件与出处 |
|---|---|---|
| U0 成本 | 0（结构） | 不含该声明的程序，Core 与发射类逐字节等于 main，由对父提交编译器的发射对拍证明，不靠计时（第七节） |
| 去掉 marks 后的探针运行段差 | vadd 121.3→117.2 ms（约 4 ms），FA 367.7→343.7 ms（约 24 ms） | W3-R 终局调研第 4.2 节：本机 WSL2、GraalVM CE 21.0.2、持租约、10 次交错中位；marks 臂还多打印映射输出，故 4/24 ms 是 marks 成本的**上界** |
| enter/exit 每对 | 约 6–12 ns | 同报告：同一编译器 `micro/`，5M 次「闭包加两次 perform」28–63 ms，空处理臂 0–6 ms，热 JIT；冷进程解释执行更贵，探针只有数百到数千次调用 |
| 与手写比的增量 | 约 0 量级（估算） | 推算：代写可省去手写 `called` 捕获 `body` 的闭包分配。**该分配的节省未验证** |
| Playground 门 | 待 R4-f3 | 预注册判据 4：warm 增量 U95 ≤ max(10 ms, 5%×基线 p95)，基线为 `3793ebb3` 的 marks 臂 |
| `dawn build` 编译期增量 | 预期 ≤30 ms | **未实测**，待 R4-f3 |
| 运行增量、tileir jar 体积 | 预期 ≤10 ms、≤+2% | 待 R4-f3；手写到代写会减少源码闭包类，方向未必为正 |

不引用 Go `runtime.Caller` 的成本数字（无官方数据）。tracing PR #1974 的「禁用 span 开销再降 50–70%」来自检索摘要、未读原文，只作启发。

## 六、其它语言对照

| 系统 | 机制 | 与本设计的关系 | 出处 |
|---|---|---|---|
| GCC `-finstrument-functions` | 编译器在每个被插桩函数入口后调 `__cyg_profile_func_enter(this_fn, call_site)`，退出前调 `_exit`；内联函数也视为进入/退出；`no_instrument_function` 属性与 `-finstrument-functions-exclude-*-list` 按名过滤；文档不讲异常与 `longjmp` 的配平 | 最近的先例：编译器代写进出，钩子是用户给的函数。差别：它按全程序开关、靠属性和名单过滤；Dawn 按效果声明键控，没有属性。文档不讲配平，正是 2.3 要写死的 | <https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html> |
| LLVM XRay | 编译期在函数入口/出口放 nop sled，运行时打补丁启停；默认「至少 200 条指令或含循环」才插桩，`xray_always_instrument`/`never` 属性覆盖 | 编译期代写、按需消费。它的阈值启发式不采用：Dawn 要的是完整调用树，不是采样 | <https://llvm.org/docs/XRay.html> |
| Rust `tracing` 的 `#[instrument]` | 属性宏：每次调用创建并进入一个以函数名命名的 span；`name`/`skip`/`fields` 可调；文档对提前返回与 `?` 的退出方式没讲 | 形状同族（代写进出、名取函数名）；不采逐函数属性，不记参数 | <https://docs.rs/tracing/latest/tracing/attr.instrument.html> |
| Rust `#[track_caller]` | 改的是调用约定：给被标函数追加隐藏的 `&'static Location` 实参，调用点由编译器填，不回溯栈；被标函数调被标函数时转发自己收到的；经函数指针时 `ReifyShim` 退回定义位置 | Dawn 的 `at: Loc = caller()` 同构，且更显式（在签名里，函数值丢默认值）。只读 `at`，不造新机制 | <https://rustc-dev-guide.rust-lang.org/backend/implicit-caller-location.html> |
| Swift SE-0274 | `#file`/`#line` 作默认实参时捕获调用方位置，且必须是整个默认值 | 同上，是 `caller()` 规则的出处（`caller-location-design.md`） | <https://github.com/swiftlang/swift-evolution/blob/main/proposals/0274-magic-file.md> |
| Scala `sourcecode` | 隐式参数由宏在调用点编译期展开，不用反射或栈检查 | 静态位置随调用约定带入 | <https://github.com/com-lihaoyi/sourcecode> |

后两行取自 W3-R 终局调研，本文未重新抓取。

小结：编译器代写进出有成熟先例（GCC、XRay、tracing），差异点是 Dawn 把「谁被代写」交给**效果声明**而不是属性或名单，并把「配平」写成规则而不是留白。

## 七、验收

- **U0（硬）：** 不含钩子效果的程序，Core 与发射类逐字节等于 `main`。**对照的是父提交的编译器，不是种子**：
  种子差分（`selfhost-prev-diff.sh`）里自 v0.105.0 起已声明的标签会遮住这一刀的任何新差，所以另用父提交 `06b99b28` 的工具链
  与本分支工具链各发射一遍。24 个目标的 JVM 发射逐字节相同：`site`、`playground`、`web`、`web-jvm`、`json`、`selfhost`
  （同一份本分支源码，分别由两个编译器发射，4254 个文件）、四个示例程序、`tileir`（2648 个文件）、`tileinterp`、`tileref`、`xmap`、
  `tea-core`、`tea-dom`、`tea-term`、`fspath`、`inflate`、`sha2`、`sqlite`、`compiler-plan`；C 后端发射的 `site`（4313340 字节）、
  `playground` 与一个 handler 示例逐字节相同。无新运行时类。结构依据：`sig.calls == None` 走原路，`emit_return` 在 `on_return` 为空时
  不取新符号，符号编号都不变。变异体「把门控取反」不在这里做：门控是 `Sig` 上的数据，不是 `lower_fn` 里的开关，取反即不再有函数带计划，
  与「不含钩子」等价；U0 的反面由下面带钩子的对拍来证（计划存在时 Core 一定变）。
- **两端：** 256 个 kernel 程序的调用表在 JVM 与 native 上逐字节相同（harness 工程由本树的 `dawnc` 编译，
  `run.py --native`：256 个程序，0 处不一致）；转录本用例在两端同样等于同一份预期文件。变换在 Core 层之前完成，
  两个后端消费的是同一棵 Core。
- **配平检查：** `DAWN_CORE_LINT=1` 下转录本用例通过。

## 八、不做的（理由）

1. **不加逐函数属性**（`#[instrument]`/`no_instrument_function` 式）。仓库没有属性语法；按效果行键控已经够用，且不会出现「忘了标」这种新的腐烂面，那正是手写 marks 的病。
2. **不加 `name` 覆盖语法。** 17 处不一致用「改展示名为声明名」解决（补裁八第 3 条），不为它们造语法，也不留映射表。
3. **不代写私有函数、局部 fn、lambda、trait 默认体。** 没有稳定的声明名；归入包裹它的公共调用，与现行规则一致。
4. **不支持 `ctl effect` 的钩子。** 被放弃的续延使 `enter` 无 `exit`；要支持须先设计「放弃时补 `exit`」，无消费者，不做。
5. **不拆内层函数承载函数体。** 会给观察孪生与影子比较多一个调用帧与 Definition 身份；改写返回路径更小。
6. **不内联、不优化掉钩子。** perform 有可观测的副作用，JIT 与 C 编译器自己处理。
7. **不新增隐藏实参，不改调用约定。** `at` 读现成的 `caller()` 形参；没有就是 `None`。把 Rust 式隐藏实参推广到所有函数是已被判为规模大、风险高的路线。
8. **不包 `!e` 效果变量形参**（Q5）。函数形状不随实例化变。
9. **不让钩子操作对外隐藏。** 它们仍是 `pub effect` 的普通操作（handler 要写臂）；是否禁止用户直调留待有需要时再说。
10. **不删录制器的栈式机制，不做 observe 视图替代。** 见非目标 1。
11. **不在 f1 解决 `staged_for` 的 `at` 与「`pub` 的 kernel 入口」两个边界。** 都要裁决，写在第四节，由 f2 前裁。

## 十、f2：删除手写 marks

删除的东西：`dev.dawn` 里 228 处 `called(`/`called_bare(`/`user_body(` 使用点（185 + 29 + 14）与四个定义
（`called`、`called_bare`、`called_at`、`user_body`），样例与黄金里作者侧的 `t_call_enter`/`t_body_enter` 手写对
（`fa_exp`、`fa_divide`），Playground 与站点里的固定 helper 名单和对 `called(` 的文本扫描，以及与之配套的 helper 展开
（`captured_policy`、`HELPERS`、`def=` 定义范围）。保留的是录制器的栈机制与四个钩子操作，它们现在是编译器的目标。

**根帧政策（补裁九第 4 条）。** 录制器把一次录制重放成调用表（`prog.call_table`，由事件日志重放；处理臂里的栈只用来给
拒绝信息命名）。若录制恰是一帧从头到尾，且这帧自己没有运行闭包（不是 `d_range` 一类区域调用），则它是 kernel 入口：
被丢掉，它内部的调用是顶层 Call。这是录制器的一条规则，编译器里没有为 kernel 开特例。两条边界写在
`render.dawn` 的测试里：两个顶层调用没有单一的帧可当根；整个函数体就是一个区域调用时它是调用，不是根。

**`staged_for` 的位置（补裁九第 2 条）。** `StagedIter` 的方法签名加第三个形参 `at: Loc = caller()`，检查器改写 `for` 时
传入**被遍历表达式**的位置（`for j in d_range(..)` 里 `d_range(` 的起点）；impl 写作不带默认值的 `at: Loc`
（impl 方法本不接默认值，调用经 trait 签名分派）。`call_plan_of` 对 impl 方法读 trait 签名的 `caller_params`，所以
`at` 的来源规则仍只有一条：函数唯一的 `caller()` 形参。`d_range` 与 `DRange` 不再带 `at`：位置是使用处，不是值的创建处。
黄金里 59 行 `staged_for` 的 `at` 与手写版逐字段相同（手写版报 `d_range(` 的调用点，同一位置）。

**展示名。** 一律是声明名，没有映射表。255 个黄金程序里实际出现十二对：`d_range→staged_for`、`carry→var_open`、
`get→var_get`、`set→var_set`、`if→staged_if`、`lit→from_float`、`idx_add/sub/mul/div/rem→add/sub/mul/div/rem`、
`idx_const→from_int`。消费这些名字的地方同步改了：Playground 的 tilemap、`site/gpu-map/record.py`、`packages/xmap`
的 `spelled`、站点 GPU 页的 `ops_for` 与测试。

**一处行集变化：作者 helper 的内部调用。** 手写版里 `fa_exp`、`fa_divide` 写了 `t_body_enter`，所以它们体内的
`exp2`、`div` 是 kernel 的行（`fa_exp` 的子行）。编译器只对**闭包形参**代写 body 标记，helper 没有闭包形参，所以
`fa_exp` 现在是一行，它的 `exp2` 归它自己的操作。黄金里 24 行、flash_attn 样例里 3 行因此消失（对拍把基线的这些行折叠后
逐字段全等）。`fa_exp`/`fa_divide` 在样例与黄金里改为 `pub fn`（补裁九第 3 条：记录的是 API 边界）。

**对拍的现在形式。** 手写版已不存在，常驻的合同是 `run.py` 对 `rows.expected`（255 个黄金 4564 行）与
`rows-samples.expected`（两个样例 46 行）。`--baseline DIR` 对删除前的检出重现一次性的等价证明。负控：作者层
（效果不再声明 `calls`、helper 不再是 `pub fn`）必须红；编译器层变异体不变；`site/gpu-map/record.py
--check-call-origin` 的删除对照改为“helper 变私有”，MLIR 与字节码逐字节不变而严格配对必须拒绝。

**未处理：观察孪生。** `tileir/origin.dawn` 里的 `is_mark` 用 `called`/`called_at`/`called_bare` 的声明名认记录标记，
这些声明已不存在，所以它的 `marked` 恒为假。观察孪生的去留按补裁七第 4 条另裁，这里不动。

## 九、落地进度

| 刀 | 内容 | 状态 | 提交 |
|---|---|---|---|
| R4-f0 | 本设计文档 | 完成 | 见 PR |
| R4-f1 | `calls` 子句（parser、检查、LSP 词表、spec）、`Sig.calls`、`lower_fn` 变换、对拍与负控 | 完成 | 见 PR |
| R4-f2 | 删手写 marks 与名单，作者侧 mark，展示名改为声明名，`staged_for` 的 `at`，根帧政策 | 完成 | 见 PR |
| R4-f3 | 成本实测（判据 4） | 待 f2 合并 | |
