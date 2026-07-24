# Dawn 代码库设计与实现审查

> 审查日期：2026-07-25
> 审查对象：当前仓库 `main` 工作树（工具版本 `dawn 0.11.0 (selfhost)`）
> 审查范围：语法、语言语义、编译器架构、CLI/LSP、包管理、`packages/json`、
> `packages/web`、Playground、自举与发布链、规范及方案文档。
> 本文只记录问题和改进方向，不修改现有语言或实现。

## 1. 总体结论

Dawn 已经不是“只有 happy path 的玩具”：自举固定点成立，编译器、站点、Web 包和
Playground 都有可运行测试，错误恢复、持久集合、效果多态、模块分析和 JVM 互操作也有相当完整的
实现。此次审查运行的现有测试均通过。

但代码库当前有五类系统性问题：

1. **规范、EBNF、README、历史方案和实现不再处于同一版本。** `docs/spec.md` 仍称
   “v0.1 草案”，README 仍停在 M4，而工具已经是 0.11；EBNF 已不能准确描述当前解析器。
2. **“纯函数签名即契约”的核心卖点存在公开逃生门。** `unsafe_pure` 对普通用户开放，并且还是
   comptime 反射执行 Java 静态方法的许可证；这是编译不可信源码时必须单独建立威胁模型的边界。
3. **编译器已超过最初“小而直接”的架构预算。** 7,924 行的 checker、3,531 行的 emitter、
   大型状态记录、直接 TAST→ASM 和二进制运行时续传，使维护成本与文档里的原始论证明显脱节。
4. **几个对外包存在确定的协议错误。** JSON 会丢失大整数精度并能输出非法 JSON；Web body limit
   在完整读入后才检查；query/form、CORS、响应体和错误模型也有明显接口缺陷。
5. **自举证明与供应链可信被混在了一起。** B==C 能证明固定点，不能证明种子、续传 class 或下载
   工件可信；当前种子没有 checksum，关键集合运行时也没有主干源码和直接测试。

建议先处理 P0/P1 的安全与数据正确性问题，再决定是否继续扩语言特性。继续加特性会放大 checker、
TAST、codegen、LSP、spec 和历史文档之间的同步税。

## 2. 审查基线

### 2.1 仓库规模

- Git 跟踪文件：514。
- Dawn 源文件：95；`selfhost/`、`std/`、`packages/`、`playground/`、`site/`
  合计约 35,328 行 Dawn。
- 主要单文件：
  - `selfhost/src/checker.dawn`：7,924 行，约 215 个函数/test。
  - `selfhost/src/emit.dawn`：3,531 行，约 121 个函数/test。
  - `selfhost/src/codegen.dawn`：2,512 行。
  - `selfhost/src/parser.dawn`：1,932 行。
  - `selfhost/src/interp.dawn`：1,699 行。
  - `selfhost/src/lspq.dawn`：1,671 行。
- `docs/` 下当前有 28 篇被跟踪的 Markdown，而 `CLAUDE.md:21` 仍写“14 篇、4000+ 行”。

### 2.2 本次验证

以下现有门禁通过：

- `./bin/dawn test selfhost`：158 项通过。
- `./bin/dawn test packages/json`：1 项通过。
- `./bin/dawn test packages/web`：15 项通过。
- `./bin/dawn test playground`：18 项通过。
- `./bin/dawn test site`：33 项通过。
- `./bin/dawn test examples/m4/json`：3 项通过。
- `./bin/dawn fmt site selfhost packages --check`：通过。
- `./scripts/selfhost-fixpoint.sh`：B==C，通过；standalone emit smoke 通过。
- 手工运行 JSONTestSuite 中必须接受/必须拒绝的 283 个 `y_`/`n_` 用例：0 失败。

最小复现还确认了：

- `中文`、`_hidden` 等不符合规范正则的标识符可编译运行。
- `make()(1)` 不能解析，说明调用不是一般后缀运算。
- JSON 文本 `9007199254740993` 被解析再渲染为 `9007199254740992`。
- JSON 文本 `1e400` 被解析再渲染为 `Infinity`。
- 解析 `"\\b\\f"` 后再渲染会直接写出字节 `08 0c`，不是合法 JSON 转义。

`unsafe_pure` 的编译期宿主副作用风险按要求只做源码级审查，未继续做动态利用验证。

### 2.3 优先级

- **P0**：安全边界、静默数据损坏或供应链根问题，应阻止不可信输入或发版。
- **P1**：确定的协议/语义错误，或很可能造成生产故障的架构问题。
- **P2**：长期维护、扩展性和 API 人体工学问题。
- **P3**：文档、命名、注释或低风险一致性问题。

## 3. 最高优先级摘要

| 编号 | 优先级 | 问题 |
|---|---:|---|
| LANG-01 | P0 | `unsafe_pure` 对用户开放，且 comptime 会在编译器进程内反射执行 Java 静态方法 |
| BOOT-01 | P0 | 关键集合运行时 class 无主干源码和直接测试，并从种子逐代续传 |
| BOOT-02 | P0 | 种子 jar 下载没有 checksum 或签名 |
| JSON-01 | P0 | JSON 整数先转 Float，超过 2^53 静默损坏 |
| JSON-02 | P1 | JSON renderer 可输出 `Infinity` 和未转义控制字符 |
| WEB-01 | P1 | body limit 在 `readAllBytes` 之后执行，无法阻止内存型 DoS |
| PKG-01 | P1 | 包下载/解压无体积、条目数、膨胀率和超时限制 |
| CLI-01 | P1 | `write_class` 吞掉目录创建和文件写入错误 |
| ARCH-01 | P1 | checker/emitter 已形成大型单体和超宽状态对象 |
| ERR-01 | P1 | `catch_panic` 捕获全部 `Throwable`，会吞下 JVM 致命错误 |
| DOC-01 | P1 | 权威 spec、EBNF 和当前实现存在多处可执行语法冲突 |

## 4. 语法与语法文档

### SYN-01（P1）标识符规则与 lexer 不一致

**证据**

- `docs/spec.md:27` 和 `docs/grammar.ebnf:3` 将值标识符限定为
  `[a-z][a-z0-9_]*`，类型限定为 ASCII `UpperCamelCase`。
- `selfhost/src/lexer.dawn:59` 使用 `Character.isLetter` /
  `Character.isLetterOrDigit`，`selfhost/src/lexer.dawn:209` 还允许 `_` 开头。
- 实测 `fn 中文(值: Int)` 和 `fn _hidden(_值: Int)` 可编译运行。

**影响**

- “命名是语义、parser 靠大小写消歧”的规范不再精确。
- 源码标识符、模块路径、包名和 manifest 名称使用不同字符集合。
- 无大小写文字可作值名，却难以自然地作类型名；Unicode 规范化和同形字符也未定义。

**建议**

明确二选一：严格按 ASCII 规则拒绝，或正式定义 Unicode XID、大小写分类和 normalization。
不要继续让 Java `Character` 的实现细节充当语言规范。

### SYN-02（P1）函数值调用不是正交的一般后缀调用

**证据**

- `docs/grammar.ebnf:89` 把 `call_args` 定义为任意 `primary_expr` 的 postfix。
- `selfhost/src/parser.dawn:1263` 的 postfix 循环只处理 `?`、`!`、`[]` 和 `.`。
- 普通调用只在 `selfhost/src/parser.dawn:1458` 的 `ident_or_call` 特判。
- 构造器调用也在 `selfhost/src/parser.dawn:1390` 单独特判。
- 实测 `make()(1)` 在第二个 `(` 报语法错误。

**影响**

语言声称函数是一等值，但只有“名字绑定到函数值”时能调用；条件表达式、字段读取结果、
函数返回值等不能直接应用。parser、AST 和 checker 因此同时保留 `ECall`、`EMethod`、
`EApply`/动态调用等多套路径，复杂度高于真正统一的 application。

**建议**

把调用落实成真正的 `Expr(args)` 后缀节点，再由 checker 区分静态函数、动态函数值、
构造器和 Java/UFCS；或在规范里明确承认这是受限的一等函数并删掉错误的 EBNF。

### SYN-03（P2）EBNF 的 named argument 范围错误

`docs/grammar.ebnf:96` 写所有 `arg` 都可为 `IDENT ":" expr`，但
`selfhost/src/parser.dawn:1458` 的普通函数调用只存 `List[Expr]`；只有
`selfhost/src/parser.dawn:1398` 的构造器参数支持名称。这会误导语法高亮器、格式化器、
第三方 parser 和用户。

### SYN-04（P1）EBNF 已落后于当前语言

至少包括：

- `docs/grammar.ebnf:15` 缺少已实现的 `use a/b as c`。
- `docs/grammar.ebnf:49` 要求所有函数写 `-> type`，而 `docs/spec.md:243` 和 parser
  已允许私有函数推导返回类型。
- `docs/grammar.ebnf:45` 使用未定义词法符号 `UPPER_IDENT`。
- `docs/grammar.ebnf:92` 的 `. IDENT` 不覆盖实现允许的 `Class.FIELD`/关键字 Java 成员。
- `type_params` 的产生式允许所有声明带 bound，注释却说只有函数允许；实现再在 parser 中报错。
- 一般调用与 named argument 的产生式与实现不符，见 SYN-02/SYN-03。

**建议**

不要手工维护第二份近似语法。可从 parser 的 token/production 定义生成 EBNF，或至少把
EBNF 纳入可执行 corpus 测试。

### SYN-05（P2）同一 `!` 同时表达效果和强制解包

`fn f() -> T !io` 与 `option!` 在视觉上分别表示“有副作用”和“断言非空”。两者都高频，
特别是在 Java builder 链中会出现连续多个 `!`。这不是语义 bug，但可读性和搜索性较差；
未来扩展更多效果后更明显。建议评估将 unwrap 改为显式方法、`!!` 或独立关键字。

### SYN-06（P2）点调用歧义规则对远处名字不稳定

`docs/spec.md:190` 规定：若作用域内存在同名函数，`r.f(x)` 作为函数字段调用直接报歧义。
新增一个 import 或同名顶层函数就能让原本合法的字段调用失效。它避免了静默改义，却牺牲了
组合性。更稳定的方案是给字段调用和 UFCS 明确优先级，或用不同语法显式区分。

## 5. 语言设计

### LANG-01（P0，源码级风险，未继续动态验证）`unsafe_pure` 破坏核心纯度边界

**证据**

- `docs/spec.md:532` 保证纯函数同参同值、无可观测副作用。
- `docs/spec.md:553` 又把 `unsafe_pure` 作为普通语言语法开放，并在
  `docs/spec.md:576` 承认其不健全。
- `docs/design.md:69` 的原决策却写逃生门“用户代码不开放”，与现状相反。
- `selfhost/src/checker.dawn:4733` 仅屏蔽效果，不限制调用者模块。
- `selfhost/src/interp.dawn:660` 到 `selfhost/src/interp.dawn:706` 会在编译器 JVM 中，
  通过反射执行被担保的静态 Java 方法。
- `docs/pure-ffi-design.md:302` 也承认反射一旦进入无法打断，fuel 只收固定成本。

**风险**

用户可以给有副作用、非确定、阻塞或终止进程的静态 Java 方法盖“pure”章。运行期会破坏
优化和推理前提；comptime 下更把编译源码变成了在编译器进程内执行宿主 Java 的入口。
Playground 的生产 systemd sandbox 能缓解，但语言工具本身没有隔离。

**建议**

1. 普通用户代码禁用 `unsafe_pure`，只允许编译器签名/白名单标记的 std primitive。
2. comptime 禁止反射任意 Java；改为封闭 intrinsic allowlist。
3. 若必须保留，comptime evaluator 放进资源受限子进程，绝不与主编译器同进程。
4. 把“纯度保证”改成精确定义：哪些逃生门使程序退出语言的 sound subset。

### LANG-02（P1）`cast` 被标为 pure，但失败会抛 JVM 异常

`selfhost/src/types.dawn:563` 给 `cast` 纯签名；`docs/cast-interop.md:33` 和
`docs/spec.md:850` 又明确失败抛 `ClassCastException`。这使一个签名为 pure 的函数可抛出
非 Dawn panic 的宿主异常，与 `docs/design.md:60`“异常破坏签名即契约”的论证冲突。

建议让 `cast` 返回 `Result`/`Option`，或把 checked cast 作为显式不安全效果；至少不要用
“pure”同时表示“无副作用”和“不会以隐藏控制流退出”。

### LANG-03（P1）“没有异常”只是表面语法，不是运行时保证

`docs/spec.md:886` 规定 Java 异常默认穿透并终止。`cast`、错误泛型集合取值和任意 Java 方法
都能把异常带过 Dawn 栈。因此 README 的“没有异常”会让用户误以为所有失败都在
`Result`/panic 模型内。应改成“Dawn 无 throw/catch 语法，但 JVM 异常可能穿透”，并为 FFI
提供结构化边界。

### ERR-01（P1）`catch_panic` 捕获 `Throwable` 过宽

`selfhost/src/codegen.dawn:953` 的 `java_try` 捕获 `Exception`，但下一行的
`catch_panic` 捕获 `java/lang/Throwable`。这会把 `OutOfMemoryError`、`StackOverflowError`、
`LinkageError`、`ThreadDeath` 等不应恢复的 JVM 错误变成字符串，服务器可能在不可靠状态继续运行。

建议只捕获 `PanicError` 加一组明确可隔离的异常，而不是全部 `Throwable`。

### ERR-02（P1）异常被降成字符串，跨层接口依赖消息文本

- `java_try`/`catch_panic` 只返回 `Result[T, String]`，丢失类型、cause、stack 和结构化字段。
- `docs/spec.md:901` 建议按类名前缀匹配字符串。
- `packages/web/src/types.dawn:93` 的 `as_http_with` 明确因为 repo 只有字符串错误而分类。

这让重构错误文案、JDK 版本变化和本地化都可能改变程序控制流。建议引入最小
`JavaError { class_name, message, cause }` 和业务错误 ADT。

### ERR-03（P1）缺少 `finally`/资源作用域

语言没有 `try/finally`、`defer`、`using` 或线性资源协议。结果是
`packages/web/src/server.dawn:227`、`playground/src/play/gate.dawn:27` 等处用
`catch_panic` 模拟 finally，再重新 panic。它既促成 ERR-01，又丢失原始异常上下文。

建议提供最小 `defer` 或标准库 `bracket(acquire, use, release)`，并让编译器/runtime 保证 release。

### LANG-04（P2）字符只是 `Int`，类型系统不能保证 Unicode scalar

`docs/spec.md:60` 把字符直接定义为 Int；`docs/spec.md:1066` 又规定非法码点在
`from_code_points`/`str.from_char` 时 panic。任意整数都能冒充字符，API 无法在签名上区分
索引、计数、字节和字符。Cursor 已经证明不透明标量可行，Char/Rune 也应采用同样方案。

### LANG-05（P2）透明 alias 不能提供领域安全

`docs/spec.md:207` 用 `Meters = Float` 举例，但 `docs/spec.md:217` 明确它与 Float 完全互换。
这类例子反而容易让用户误以为得到单位安全。建议增加真正的 newtype/opaque type，或避免用单位
类型作为透明 alias 示例。

### LANG-06（P2）模块限定访问不完整

`docs/spec.md:985` 只允许 `alias.fn(args)`；类型、构造器、常量必须选择性导入到本地。
同一个模块 API 被迫使用两套访问风格，类型和常量会污染命名空间，也让自动补全和批量重命名更难。
建议支持 `m.Type`、`m.Ctor`、`m.CONST`。

### LANG-07（P2）目录模式无条件加载全部源码

`docs/spec.md:1002` 要求加载 `src/` 下全部 `.dawn`，未引用模块也必须检查，依赖图还完全禁环。
这对小项目能防 bit-rot，但会阻碍大型工程、平台专用模块、生成代码和仅测试依赖，也排除了常见的
type-only cycle。建议把“全仓 lint/test”与“构建当前入口闭包”分开。

### LANG-08（P2）全部 Java 引用返回都包 Option，产生大量无信息解包

`docs/spec.md:668` 自承绝大多数 JDK 方法永不返回 null，因此 `!` 成为互操作常态。
统一保守规则简单，但把 Java 注解、已知 JDK 合约和 builder API 的信息全部丢掉。
可以继续默认 nullable，同时读取 `@NotNull`/JSpecify 或维护小型 JDK nullability 数据库。

## 6. 编译器与代码框架

### ARCH-01（P1）checker 是 God module

`selfhost/src/checker.dawn` 有 7,924 行、约 215 个函数/test。
`Cx` 在 `selfhost/src/checker.dawn:76` 到 `selfhost/src/checker.dawn:132`
包含约 44 个字段，混合了：

- 名字与作用域；
- ADT/alias/trait/impl；
- 类型变量与效果变量；
- Java 反射；
- import/export；
- const/comptime；
- lambda/loop 控制；
- 诊断、源位置和 codegen 所需信息。

不可变记录线程化只是把“一个可变大对象”变成“每步复制/更新一个不可变大对象”，没有真正降低耦合。
建议至少拆成符号环境、类型推断状态、效果状态、trait 环境、Java resolver、诊断 sink 六个组件，
并让 pass 有窄输入/输出。

### ARCH-02（P1）emitter 状态和职责同样过宽

`selfhost/src/emit.dawn` 3,531 行；`Gen` 在 `selfhost/src/emit.dawn:159` 有 30 余字段，
同时管理 JVM 栈槽、闭包、SAM、函数值桥、构造器桥、trait witness、常量字段和控制流 label。
新增任一语义特性都很容易触碰整个后端。

建议引入 method-local builder、closure lowering、trait lowering、constant materialization 等分层，
而不是继续扩 `Gen`。

### ARCH-03（P1）“第二后端只改 intrinsic 表”不成立

`CLAUDE.md:73` 声称接第二后端只需重指向 `rt_intrinsic_target`。实际：

- `selfhost/src/tast.dawn:25` 的 `TJavaCall` 直接携带 JVM 类名、descriptor、SAM 和 List bridge。
- checker 直接依赖 Java reflection。
- `emit.dawn`/`codegen.dawn` 大量使用 ASM opcode、JVM descriptor、LMF、CHECKCAST。
- runtime 表示、擦除、装箱和异常也都写死 JVM。

当前架构可以合理地选择“只支持 JVM”，但不能同时宣称后端中立。若真要第二后端，应先定义
backend-neutral lowered IR 和 FFI capability；若不打算做，应删除误导性承诺。

### ARCH-04（P2）“无 IR”的原始论证已过期

`docs/design.md:73` 在小编译器阶段拒绝 IR 是合理的，但现在 TAST 同时承担类型树、lowered tree、
Java ABI 和 codegen 输入，checker+emit 已超过一万行。没有 IR 使 desugar、优化、后端验证、
调试 dump 和第二后端都只能侵入 checker/emitter。

建议不是立刻造“大而全 SSA”，而是增加一个小型 lowered IR：统一 call、控制流、match、
closure、trait witness 和 FFI，再从该层生成 JVM。

### ARCH-05（P1）运行时支持以 ASM 手写生成，维护和测试成本过高

`selfhost/src/codegen.dawn` 用数千行 opcode 生成 `dawn/rt/*`。opcode 常量还分散在
`codegen.dawn` 与 `emit.dawn`。这让普通运行时逻辑难以做源码级单测、静态分析、调试和安全审计。

建议：

- 纯运行时逻辑用可编译的 Java/Dawn 源维护；
- 只有真正与生成类型相关的薄桥留在 ASM；
- opcode、descriptor 和 class builder 统一到一个后端模块。

### BOOT-01（P0）关键集合运行时只有续传二进制，没有主干源码

`selfhost/src/vendor.dawn:3` 明确 `DawnList/DawnMap/DawnSet` 的源码只在
`kotlin-final` tag，当前编译器从自身 classpath 读取 class，再复制进每个用户程序。

问题包括：

- 当前 checkout 无法独立审查或重编这些关键数据结构。
- `docs/pure-ffi-design.md:403` 提到的并发 CAS 测试不在主干测试中。
- 固定点会忠实复制同一二进制，因此 B==C 不能发现其中的恶意或历史 bug。
- 修复这些 class 需要回到历史 tag 和额外工具链，更新协议未自动化。

建议把 Java 源和直接测试恢复到主干，构建时从源码生成；若坚持 boot blob，也应跟踪 blob、
源码、checksum 和“源码→blob”复现脚本。

### ARCH-06（P1）`-Xss512m` 是架构债，不是“无害”

`selfhost/src/interp.dawn:12` 因 evaluator 使用宿主递归而要求 512MB 线程栈；
`bin/dawn:38`、`selfhost/src/main.dawn:493`、`spawn_java` 等处广泛强制该值。
它会显著增加虚拟地址保留和容器内存压力，还把编译器实现细节泄漏给用户程序。

建议 trampoline/显式 evaluator stack，或把 comptime 放进专用受限线程/进程；用户程序不应继承
编译器的 512MB stack 参数。

### CLI-01（P1）class 文件写入错误被静默吞掉

`selfhost/src/main.dawn:117` 的 `write_class` 对 `createDirectories` 和 `Files.write`
分别调用 `java_try`，随后完全忽略 `Err`。磁盘满、权限错误、路径非法时，build/run/test
可能继续执行并在更远处以“类缺失”失败，甚至产出不完整结果。

建议返回 `Result[Unit, String]` 并在第一次 I/O 失败时报告目标 class 和真实路径。

### ARCH-07（P2）测试与生产实现混在超大源文件

内联 `test` 对小模块很方便，但 checker、parser、emit 等巨型文件把实现和数千行测试 fixture
绑在同一编译单元。建议保留小模块内联测试，同时给大模块增加 `test/` 项目和 black-box corpus，
尤其覆盖 parser/spec、JSON、LSP framing 和 binary runtime。

## 7. CLI、LSP 与工具接口

### CLI-02（P1）classpath 分隔符声称跨平台，实作硬编码 `:`

- help 在 `selfhost/src/main.dawn:308` 写“platform path separator”。
- `extract_cp` 在 `selfhost/src/main.dawn:368` 按 `:` 分割。
- re-exec、环境变量、run/test classpath 和 `vendor.classpath_package`
  也都硬编码 `:`。

Windows 盘符会被拆坏。建议统一读取 `File.pathSeparator`，环境变量也用平台 separator。

### CLI-03（P2）`bin/dawn` 宣称考虑 macOS，却依赖非 POSIX `readlink -f`

`bin/dawn` 是 `#!/bin/sh`，`bin/dawn:10` 使用 macOS 默认不存在的 `readlink -f`；
它 source 的 `scripts/seedjar.sh:11` 又使用非 POSIX `local`。建议要么明确 bash，
要么保持真正 POSIX 并实现可移植 symlink resolution。

### CLI-04（P2）仅用 mtime 判断编译器是否需要重建

`bin/dawn:46` 用 `find -newer`。checkout、解压、时钟偏移或产物复制会让旧 jar 看起来比新源码更新，
导致运行过期编译器。建议记录源树 hash、seed tag 和构建参数，而不是依赖时间戳。

### LSP-01（P1）手写 UTF-8 decoder 不校验合法性

`selfhost/src/lsp.dawn:199` 的 decoder 不检查 continuation byte、overlong encoding、
surrogate 和最大码点；不完整序列还会静默跳字节。URI 解码结果可能与 JVM/编辑器不同，
甚至进入 `from_code_points` 的非法范围。

建议直接使用标准 URI/UTF-8 API，或实现严格 decoder 并返回错误。

### LSP-02（P1）file URI 实现不符合跨平台 URI 语义

`uri_to_path` 只去掉 `file://`，`path_to_uri` 只拼接该前缀。authority、Windows drive、
UNC、相对路径、`#`/`?` 和 URI normalization 都没有标准处理。`Paths`/`URI` 已能正确完成这些工作，
不应手写。

### LSP-03（P1）一个畸形 frame 会让服务器静默退出

`selfhost/src/lsp.dawn:338` 的 `read_message` 在缺 Content-Length、body 短读或 JSON 错误时返回 None；
`run_lsp` 把 None 当 EOF，直接停止。JSON-RPC 要求 parse error/invalid request 响应，至少也应记录
错误并尝试恢复下一个 frame。

### LSP-04（P2）每次按键做全项目同步分析，无取消

`selfhost/src/lsp.dawn:5` 明确每次 change 重建完整分析；`textDocumentSync=1` 接收全文，
`update_doc` 调 `analyze_document(..., 100000000)`，主循环单线程且不处理取消。
配合“目录加载全部模块”，项目增长后会出现输入延迟和旧诊断覆盖新状态。

建议先做 debounce + generation cancellation，再逐步缓存 lex/parse/module graph。

## 8. 包管理、自举与发布

### PKG-01（P1）下载与解压缺少资源上限

- `selfhost/src/pkgfetch.dawn:170` 通过 `BodyHandlers.ofByteArray` 整体下载到内存。
- HTTP client 未设置 connect/request timeout。
- zip 每个 entry 使用 `readAllBytes`（`pkgfetch.dawn:260`）。
- tar.gz 先把整个解压结果 `readAllBytes` 到内存（`pkgfetch.dawn:337`）。
- 没有 compressed size、expanded size、entry count、单文件大小或压缩比限制。

一个 zip/tar bomb 或慢连接能耗尽编译器内存/时间。建议流式下载到临时文件，设置网络超时、
总量/单项/条目/压缩比限制，并在移动进 cache 前验证。

### PKG-02（P1）cache 命中后不再验证内容

`selfhost/src/pkgfetch.dawn:482` 明确“fetch 时验证一次，之后信任本地副本”；
目录存在就直接返回。用户、磁盘损坏或并发半成品都能改变 cache 内容而不被发现。
建议至少验证一个带版本的 marker/hash，或使用只写临时目录+原子 rename+只读权限，并提供
`dawn cache verify`。

### PKG-03（P2）自制 TOML 子集却使用 `.toml` 名称

`selfhost/src/toml.dawn` 807 行，另有 661 行 manifest validator；它明确拒绝标准 TOML 的
literal string、float、inline table、quoted key、dotted key 等。用户会自然使用 TOML 工具和语法，
却得到 Dawn 专用子集。

建议使用成熟 TOML parser；若坚持子集，应使用不同扩展/格式名，并在文件头和错误中明确
“不是通用 TOML”。

### PKG-04（P2）无 lockfile 的可复现论证过强

`docs/package-design.md:244` 假设精确直依赖 + Maven Central release 不可变即可复现，但：

- 传递 POM 可以含版本区间或动态 metadata；
- mirror 可返回不同内容；
- 没有 artifact checksum/完整解析图；
- highest-wins 结果没有固化；
- 仓库或依赖删除也会破坏重建。

源码包的 d1 hash 做得更好；Maven 依赖也应生成包含坐标、解析版本、URL/checksum 的 lock。

### BOOT-02（P0）种子下载没有 checksum 或签名

`scripts/seedjar.sh:17` 直接从 GitHub Release 下载并永久缓存 `seed.jar`，没有 checksum、
签名或每次校验。首次下载/CDN/release 资产被替换会改变整个工具链信任根。

建议在仓库跟踪每个 seed 的 SHA-256（最好再有签名），使用前总是校验；release workflow
发布 jar 同时发布 checksum/provenance。

### BOOT-03（P1）固定点证明被表述成了供应链证明

B==C 只能证明“这个编译器编译自己达到固定点”。它不能证明：

- seed 与声明的历史源码对应；
- compiler 没有 trusting-trust payload；
- 从 classpath 原样复制的 runtime/ASM/coursier 可信；
- 下载工件未被替换。

`docs/m8-selfhost-only.md:227` 对 trusting-trust 的处置过于乐观。应把
**reproducibility、diverse double compilation、artifact integrity、source correspondence**
分成不同门禁。

### BOOT-04（P2）跨时区并非字节可复现

`docs/bootstrap.md:112` 承认 ZipEntry 时间经过本地时区，跨时区 jar 不保证相同。
既然 release 以字节固定点为核心，应把时间戳固定为与时区无关的 epoch，并在至少两个时区/平台
重建比较。

### REL-01（P1）release workflow 没有重跑完整 CI

`.github/workflows/release.yml:46` 说 tag 可以指向任何位置，所以要重跑 suite；实际只跑
selfhost 和 site。它没有跑：

- `packages/web`、`playground`；
- Playground contract；
- site 端到端 build；
- formatting；
- secret/attribution guards；
- N vs N-1 transcript/diff。

tag 的确能绕过 main CI，因此 release 应复用同一个 required workflow，而不是维护一份缩小版。

### REL-02（P2）`Emit-Change` 豁免粒度过粗

`scripts/selfhost-prev-diff.sh:38` 只要 tag 之后任一 commit 含一行 `Emit-Change:`，
所有 target 的任意差异都会被放行。声明没有绑定文件、阶段、预期 digest 或 corpus。
建议让变更声明列出目标和批准的 snapshot hash，或把 golden 更新作为可审查文件提交。

## 9. JSON 包

### JSON-01（P0）大整数静默丢精度

`packages/json/src/lexer.dawn:195` 把所有 number 解析成 Float；parser 再在
`packages/json/src/parser.dawn:123` 对整数字面量执行 `to_int(f)`。因此 JInt 只保留
“有没有小数点”的外形，不能保留原整数。

实测：

```text
parse/render 9007199254740993 -> 9007199254740992
```

ID、金额最小单位、计数器和时间戳都可能被静默改写。建议对整数字面量直接解析为 Int，并对 Int
溢出返回错误；若要支持任意 JSON number，数据模型应保存 decimal lexeme/BigDecimal。

### JSON-02（P1）Float overflow 会渲染出非法 JSON

实测 `1e400` 解析后渲染为 `Infinity`。`packages/json/src/render.dawn:39` 直接
`to_string(Float)`，没有拒绝 NaN/Infinity。RFC 8259 不允许这些 token。

建议 parser 拒绝非有限结果，renderer 也二次防御，不允许构造 `JNum(NaN/Infinity)` 后输出。

### JSON-03（P1）renderer 没有转义全部控制字符

`packages/json/src/render.dawn:5` 只处理 quote、backslash、LF、TAB、CR，遗漏
U+0000–001F 中的其他字符。实测解析 `"\\b\\f"` 再渲染得到原始 `0x08 0x0c`，
输出不再是合法 JSON。

建议实现 `\b`、`\f`，其余控制字符输出 `\u00XX`，并加入 round-trip/property test。

### JSON-04（P1）重复 key 静默 last-wins，错误没有位置

object parser 在 `packages/json/src/parser.dawn:76` 直接 `map.insert`，重复 key 无提示。
所有错误只是 `String`，没有 offset/line/column/path。对配置、签名和 API 验证来说，
重复 key 往往应拒绝或至少可配置；错误应携带位置。

### JSON-05（P2）非法 surrogate 被替换而不是明确策略

`packages/json/src/lexer.dawn:101` 到 `packages/json/src/lexer.dawn:125` 将 lone/错误 surrogate
替换为 U+FFFD。该选择可以存在，但当前 API 没有 strict/lossy 区分，调用者也不知道数据已改变。
建议 strict parser 默认报错，另提供显式 lossy 模式。

### JSON-06（P1）包与 M4 示例重复，测试正典已分叉

`examples/m4/json` 与 `packages/json` 复制了 lexer/parser/render/value。lexer 当前相同，
package 版后来加入 JInt，但注释仍写“parser never produces it”，示例版仍全 Float。

README 把 M4 示例称为 JSONTestSuite 验收物，生产代码却用另一个分叉。应让示例依赖正式 package，
或把 suite/harness 移到 package 测试中，消除双正典。

### JSON-07（P1）318 个 fixture 没有现行自动 harness

仓库跟踪了 JSONTestSuite 文件，但当前 `dawn test examples/m4/json` 只跑 3 个 test，
CI 也没有逐文件执行 fixture 的脚本。README 的“全部 318 例”是历史结论，不是当前持续门禁。
本次手工跑的 283 个强制 y/n 用例通过，但这应成为仓库脚本和 CI。

## 10. Web 包与 Playground

### WEB-01（P1）body limit 检查发生得太晚，且单位错误

`packages/web/src/server.dawn:40` 先 `readAllBytes` 并同时保存 Bytes 与 UTF-8 String；
`packages/web/src/middleware.dawn:37` 才用 `str.len(req.body)` 检查 limit。

因此：

- limit 无法防止大请求先耗尽内存；
- 同一 body 同时保留 byte[] 和 String，峰值更高；
- `str.len` 是码点数，错误消息却写 bytes，多字节 UTF-8 会低估。

建议在读 body 前检查 Content-Length，并以限长流累计真实字节；超限立即停止。文本 decode 应按需，
不要每个请求都保留两份。

### WEB-02（P1）query/form 解码不符合 URL 规范

- `server.dawn:110` 使用已经解码的 `URI.getQuery()` 再按 `&` 切分，编码后的 `%26`
  可能先变成分隔符。
- `parse_form` 只把 `+` 替换为空格，完全不做 percent decode。
- key 没有相同处理。

建议使用 raw query 后按分隔符切分，再分别 percent decode key/value；form 使用标准
`application/x-www-form-urlencoded` 解码。

### WEB-03（P1）路由使用解码后的 path，encoded slash 语义不明确

`build_request` 和 dispatch 使用 `URI.getPath()`。若 `%2F` 被解码为 `/`，客户端数据会改变
路由段边界，影响授权和 WebDAV 路径。应使用 raw path、明确每段 decode，并定义重复 slash、
dot segment 和 trailing slash 策略。

### WEB-04（P2）请求 header 被压成单值

`packages/web/src/server.dawn:92` 明确只取每个 header 的第一个值。
`Cookie`、`Forwarded`、`Accept`、重复自定义 header 等语义会丢失。建议
`Map[String, List[String]]`，另提供 `header_first` 便利函数。

### WEB-05（P1）CORS 对不允许的 origin 仍发第一个 origin，且缺 `Vary`

`packages/web/src/middleware.dawn:67` 在 origin 不匹配时回退到第一个配置项，然后总是发送
`Access-Control-Allow-Origin`；响应也没有 `Vary: Origin`。浏览器可能拦截，但共享缓存可能把
针对一个 origin 的响应复用给另一个。

建议不匹配时不发 CORS header；动态 echo 时添加 `Vary: Origin`；preflight 校验请求 method/header。

### WEB-06（P2）Response 用三个字段表达一个 sum，非法状态可构造

`packages/web/src/types.dawn:47` 同时有 `body: String`、`bin: Option[Bytes]`、
`stream: Option[InputStream]`，并靠注释规定 stream 忽略其余字段。任意调用者都能构造冲突状态。

建议 `ResponseBody = Text(String) | Binary(Bytes) | Stream(InputStream) | Empty`。

### WEB-07（P2）全部响应 chunked，缺 HEAD/无体语义

`packages/web/src/server.dawn:53` 总是 `sendResponseHeaders(status, 0)`。小响应无法给
Content-Length，204/304/HEAD 也会进入 body 路径。建议由 ResponseBody 决定长度和是否允许 body，
并实现 HEAD。

### WEB-08（P1）header 构造器缺少注入与编码防护

`packages/web/src/types.dawn:142` 直接把 filename 插入 `Content-Disposition`，没有引号、
反斜杠、CR/LF 和非 ASCII 处理；redirect 的 Location 也完全接受原字符串。
建议统一 header value 校验，并按 RFC 5987 生成 `filename*`。

### WEB-09（P2）路由和错误接口 stringly typed

- HTTP method、route pattern、tag 都是任意 String。
- 无启动时 pattern 校验、重复 capture 检查或 route shadow 检测。
- first-match wins，宽 route 可静默遮住后续 route。
- `HttpError` 只有 status/message，没有 code、headers 或结构化 details。

建议构造 server 时编译并校验 RouteTable，method/status 使用受限类型，错误使用 ADT。

### WEB-10（P2）server 生命周期 API 不可组合

`packages/web/src/server.dawn:255` 固定绑定 `127.0.0.1`、创建 executor、启动后永久 latch await，
不返回 server handle，不能优雅停止、选择地址、注入 executor、测试生命周期或做 readiness。
建议 `start(config) -> ServerHandle`，由 `join/stop` 分开控制。

### PLAY-01（P1）安全配置不是 fail-closed

`playground/src/play/config.dawn:25` 默认 `PLAY_SANDBOX=0`。生产 unit 确实显式开启，但任何漏配、
直接启动或复制部署都会在宿主上编译和运行不可信代码。既然服务的本质是执行陌生代码，
默认应拒绝启动，只有显式 `PLAY_UNSAFE_LOCAL=1` 才允许无 sandbox。

### PLAY-02（P1）编译阶段本身没有 runner 级 timeout

`playground/src/play/exec.dawn:87` 对编译器直接 `waitFor()`；运行阶段才用
`waitFor(timeout)`。生产 systemd wrapper 的 `RuntimeMaxSec=15` 是后备，但关闭 sandbox 的本地模式
没有编译 timeout。comptime/Java reflection 又可能在单个调用中长期阻塞。

建议编译和运行都使用显式 timeout，并把 timeout 作为结构化 Outcome。

### PLAY-03（P3）sandbox 文档仍提“known panic leak”

`playground/sandbox/SANDBOX.md:89` 引用旧 `run_guarded` 的已知 permit leak，但
`playground/src/play/gate.dawn` 已有 `with_gate` 和回归测试。应删掉过期警告或改成当前保证。

## 11. 规范、方案和项目文档

### DOC-01（P1）权威规范版本和内部引用失真

- `docs/spec.md:1` 仍是“v0.1 草案”，当前工具为 0.11。
- `docs/spec.md:249` 把 block 指向 §5.2，实际 §5.2 是穷尽性。
- `docs/spec.md:274` 把 comptime 指向 §8，实际是 §7。
- `docs/spec.md:142`、operator 表等仍把 `?` 指向旧 §9，当前错误处理是 §8。
- `docs/spec.md:1139` 说 Dawn 无依赖解析、只接受零传递依赖 jar；
  `docs/spec.md:956` 却已经说明 Maven/传递依赖解析。
- `docs/spec.md:1104` 仍出现已经废弃的 `@trusted_pure` 名称。

权威规范必须先于普通设计文档修复，否则所有实现争议都没有可靠裁判。

### DOC-02（P1）README 已无法描述当前项目

- `README.md:39` 写“没有 trait”，实际 trait 已完整实现。
- `README.md:71` 状态只列到 M4，仓库已经经历 M8 和 selfhost-only。
- `README.md:103` 写 selfhost 145 项，本次实际 158 项。
- README 示例最后一行使用 `"total: {t}"`，而当前插值语法要求 `$t`/`${t}`，
  示例输出不会插值。
- JSONTestSuite 318 例没有现行 CI harness，见 JSON-07。

### DOC-03（P1）教程安装命令已经不可执行

`docs/tutorial.md:16` 仍让用户运行已从 main 删除的
`./gradlew :compiler:fatJar`，同时声称所有代码块由已归档的 `TutorialTest` 机械保证。
当前 CI 没有对应教程抽取/执行门禁。应改为 seed/selfhost 安装流程，并恢复文档测试。

### DOC-04（P2）设计文档把历史决策写成当前事实

`docs/design.md:8` 的 6–8 千行 Kotlin 预算、`docs/design.md:79` 的“实现语言=Kotlin”、
`docs/design.md:69` 的“unsafe escape 不向用户开放”、M7 段的“Kotlin 日常工具链”等都已经过期。

设计记录可以保留历史，但每条 ADR 应有 `proposed/accepted/superseded` 状态和替代链接，不能让
读者猜哪些段落仍有效。

### DOC-05（P2）bootstrap 文档同一页混合多个阶段快照

`docs/bootstrap.md:3` 开头说 selfhost-only 已完成，`docs/bootstrap.md:37` 又说 LSP 仍在 Kotlin，
`docs/bootstrap.md:39` 还写已经移除的 `DAWN_KOTLIN` 和 `bin/dawn-kotlin`。
应把阶段三历史移入 M8 进展记录，bootstrap 只保留现行链。

### DOC-06（P2）大量死链接指向已归档 `compiler/`

`docs/package-design.md`、`docs/selfhost-gaps.md`、`docs/pure-ffi-design.md` 等仍使用
`../compiler/...` 相对链接，在 main 上全部失效。历史引用应链接到固定 tag/commit 的 GitHub URL，
或明确标“历史路径（见 kotlin-final）”。

### DOC-07（P2）关键实现注释仍描述 Kotlin/UTF-16 旧模型

- `selfhost/src/ast.dawn:3`、`selfhost/src/tast.dawn:8`、`selfhost/src/diag.dawn:4`、
  `selfhost/src/token.dawn:87`、`checker.dawn:124` 仍说前端 span 是 UTF-16。
- `selfhost/src/lexer.dawn:249` 和测试已经明确当前 span 是 code-point index，UTF-16 只在 LSP
  边界重建。
- 大量文件头仍以“mirror Kotlin byte for byte”描述职责，即使当前 oracle 已是 N vs N-1。

这类注释是架构契约，错误比普通注释更危险，应集中修正。

### DOC-08（P2）trait 文档与实现冲突

`docs/trait.md:228` 说 Float Ord 用 `DCMPL`，NaN 偏负；当前
`selfhost/src/emit.dawn:1727` 调用 `Double.compare`，是 total order。spec 也按 total order
描述。应标记 trait.md 的落地记录已被后续实现替代。

### DOC-09（P3）selfhost manifest 注释引用不存在的 Gradle 文件

`selfhost/dawn.toml:4` 说 ASM 版本必须与 `compiler/build.gradle.kts` lock-step，
该文件已不在 main。当前 ASM 版本应由 selfhost manifest、seed vendor policy 和更新脚本共同定义。

### DOC-10（P2）文档体系缺少入口、状态和“当前事实”层

28 篇文档按时间叠加，计划、调研、落地日志、规范、复盘和当前运维说明混在一起。建议增加：

- `docs/README.md`：分类索引；
- 每篇 front matter：状态、适用版本、是否 normative、superseded-by；
- 只有 `spec`、现行 architecture、package schema、bootstrap/runbook 作为 current docs；
- 里程碑和提交哈希记录移到 `docs/history/`。

## 12. 测试与质量门禁的盲区

### TEST-01（P1）差分测试会把旧 bug 固化成正确行为

N vs N-1、byte-for-byte Kotlin mirror 和固定点非常适合防无意变化，但它们验证的是“一致”，不是“正确”。
此次 JSON 精度、renderer 控制字符、body limit 等问题都能在全绿情况下长期存在。

建议为核心协议增加外部 oracle/property test：

- parser 对照规范语法 corpus；
- JSON 对照 RFC/property/其他实现；
- URI/query/header 对照 JDK 或标准测试；
- classfile 用 ASM CheckClassAdapter/JVM verifier；
- package archive 用 fuzz/bomb/timeout corpus。

### TEST-02（P1）关键二进制运行时没有当前直接测试

DawnList 的共享窗口、CAS 所有权、DawnMap/Set 的持久性、equals/hash/order 都是语言语义的一部分，
但当前发布链只从编译器工件取得 class，主干没有对应源码和直接测试。必须恢复并在每次 CI
直接测试，不能只靠用户程序间接覆盖。

### TEST-03（P2）release 与 push CI 覆盖不一致

见 REL-01。门禁定义应该复用，不应复制命令列表；否则两份列表必然漂移。

### TEST-04（P2）文档与 EBNF 没有可执行一致性检查

README 示例、tutorial、grammar 和 spec 的错误都没有被测试发现。建议：

- 抽取所有 `dawn` fenced block 分类为 compile/run/illustrative；
- 运行 README/tutorial 的 compile/run block；
- 维护 parser accept/reject grammar corpus；
- 检查 Markdown 内部锚点和仓库相对链接；
- 对文档中的测试数、版本号尽量改成不手写，或由脚本生成。

## 13. 建议的整改顺序

### 第一阶段：安全与静默数据损坏

1. 限制 `unsafe_pure`，comptime Java 改 allowlist/隔离进程。
2. 给 seed 和所有续传 binary 加源码、checksum、复现和直接测试。
3. 修 JSON integer/finite/control escaping，并把 318 fixture 纳入 CI。
4. Web body limit 移到读取前，修 query/form/path decode。
5. package fetch 增加 timeout 和解压资源上限。
6. `write_class` 不得吞 I/O 错误；`catch_panic` 缩窄捕获范围。

### 第二阶段：收敛对外契约

1. ResponseBody、JavaError、HttpError 改为 ADT。
2. LSP 改用标准 URI/UTF-8，并正确处理 JSON-RPC frame 错误。
3. classpath/path launcher 做真正跨平台。
4. Maven 解析增加 lock/checksum。
5. Playground 改 fail-closed，并给 compile phase 独立 timeout。

### 第三阶段：重构编译器

1. 拆 checker 的环境和 pass。
2. 引入小型 lowered IR，统一所有 call/control-flow/FFI。
3. 拆 emitter 的 method、closure、trait、constant 子系统。
4. 把普通 runtime 逻辑从手写 ASM 移到可测试源码。
5. 去掉 512MB host stack 依赖。

### 第四阶段：重建文档可信度

1. 先修 spec 和 EBNF，再修 README/tutorial。
2. 建文档索引、状态和 superseded 机制。
3. 历史 Kotlin 链接固定到 `kotlin-final` tag。
4. 给文档代码、链接、版本和语法 corpus 加 CI。

## 14. 最终判断

Dawn 当前最大的风险不是“功能少”，而是**项目对自己的承诺比实现边界更强**：

- pure 被描述成可用于优化的保证，但有用户可达的 unsound/comptime Java 入口；
- 语法有权威 spec 和 EBNF，但两者不能准确解析当前语言；
- 自举固定点被赋予了超过其证明能力的供应链含义；
- JSON/Web 被当作生产验收，却仍有静默数据损坏和资源限制位置错误；
- “小实现、无 IR、容易维护”的前提已被 3.5 万行 Dawn 和巨型模块改变。

因此下一步不宜继续堆特性。先把**可信边界、协议正确性、当前文档和架构分层**补齐，
才能让自举、dogfooding 和生产使用真正成为质量证据，而不只是“一致地复现当前行为”。
