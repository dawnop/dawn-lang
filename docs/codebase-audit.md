# Dawn 代码库设计与实现审查

> 状态：**current** —— 2026-07-25 全仓审查 + 逐条处置台账，仍在按它推进（见 §0 与 docs/audit/）。
>
> 审查日期：2026-07-25
> 审查对象：当前仓库 `main` 工作树（工具版本 `dawn 0.11.0 (selfhost)`）
> 审查范围：语法、语言语义、编译器架构、CLI/LSP、包管理、`packages/json`、
> `packages/web`、Playground、自举与发布链、规范及方案文档。
>
> **处置日期：2026-07-25**（分支 `audit-fixes`）。本文原本只记录问题；现在每条附
> **【已修】/【驳回】/【待办】** 与理由。驳回不是「不承认」——是承认问题存在但认为
> 当前的做法更优、或代价与收益不成比例，理由写在条目里。

## 0. 处置总览

全文 **76 条**，逐条给了结论：

| 结论 | 条数 | 含义 |
|---|---:|---|
| **已修** | 40 | 代码/配置/文档已改，有测试或可复现验证 |
| **驳回** | 8 | 问题描述成立，但不改：理由逐条写在条目里 |
| **待办** | 27 | 认可且该做，但超出「修 bug」的边界（语言变更 / 架构重构 / 需先写设计文档） |
| **各半** | 1 | JSON-04：错误位置已修，重复 key 拒绝的建议驳回 |

**已修（40）**——`SYN-03` `SYN-04` `LANG-03` `LANG-05` `ERR-01` `ARCH-03`
`CLI-01` `CLI-02` `CLI-03` `CLI-04` `LSP-03` `PKG-01` `BOOT-02` `BOOT-03` `BOOT-04`
`REL-01` `JSON-01` `JSON-02` `JSON-03` `JSON-06` `JSON-07` `WEB-01` `WEB-02` `WEB-05`
`WEB-08` `PLAY-01` `PLAY-02` `PLAY-03` `DOC-01`–`DOC-10` `TEST-01` `TEST-03`
（其中 `SYN-04`/`ARCH-03`/`DOC-10`/`TEST-01`/`BOOT-03` 是部分修，条目里写明修了哪半）。

**上表是 07-25 的定格，不重新计数**（理由见下一节末）。此后有条目改判：
`SYN-02` 已于 2026-07-31 修完（连带把 `SYN-03` 从「以标 historical 的方式已修」
变成产生式为真），见该条目。

**驳回（8）**——`SYN-01`（标识符收窄会破坏现有代码，改的是规范措辞）、
`SYN-05`（`!` 的两处用法位置不重叠，纯风格）、`SYN-06`（报歧义是刻意取舍，
规范已写明理由）、`LANG-07`（禁环那半驳回，加载范围那半待办）、
`LANG-08`（JDK nullability 数据库抄错的方向是危险的）、
`ARCH-07`（拆内联 test 会逼实现细节 `pub` 出来；black-box corpus 那半已做）、
`PKG-03`（第三方 TOML 库是鸡生蛋：dawn.toml 正是解析依赖前要读的文件）、
`JSON-05`（涉及的 fixture 全是 `i_`，且 Dawn `String` 存不下孤立 surrogate）。

**两条 P0 未修，且是刻意的**：`LANG-01`（`unsafe_pure`）与 `BOOT-01`（集合运行时无主干源码）
都是语言/架构层面的变更，按 CONTRIBUTING.md 必须先有 `docs/<特性>-design.md`；
`BOOT-01` 另有一个主 agent 正在做的去 Java 化改造直接覆盖它
（[collections-dejava-research.md](collections-dejava-research.md) 的方案 C，
最近的提交 `2a330dc`/`005d63c`/`7177da9` 就是这条线）。
在那条线落地之前动同一批文件只会制造冲突。剩余项汇总见 §15。

**27 条待办里有 5 条后来让位了**（`ARCH-03` `ARCH-04` `BOOT-01` `TEST-02` `ARCH-05`
前两条）：去 Java 化那条线在 07-25 晚出了
[native-backend-plan.md](native-backend-plan.md)，Phase 0（Core IR）与
Phase 2（集合纯 Dawn 化）就是这几条要的东西。另有 4 条要按它改写或冻结。
逐条见台账 [`docs/audit/native-plan-overlap.md`](audit/native-plan-overlap.md)——
**动这批待办之前先读它**。上表的分类是 07-25 白天的定格，不再重新计数。

### 本次改动的验证

```
./bin/dawn test selfhost          163 项（原 158，+5 来自 packages/json）
./bin/dawn test site               36 项
./bin/dawn test packages/web       24 项（原 15，+9）
./bin/dawn test playground         30 项
./scripts/json-suite.sh            6 + 11 项，JSONTestSuite 283/283 强制用例
./bin/dawn fmt ... --check         通过
./scripts/selfhost-fixpoint.sh     B == C
./playground/test/contract.sh      10/10
```

另外手工验证：篡改缓存的种子 jar → `bin/dawn` 退出码 1 并拒绝运行；
`TZ=UTC` 与 `TZ=Asia/Tokyo` 构建同一 jar → 字节相同。

> **发布须知**：`catch_panic` 的捕获范围（ERR-01）与 jar 条目时间戳（BOOT-04）都改变了
> 工具链输出的字节。提交时需带 `Emit-Change:` 行，否则 `selfhost-prev-diff.sh` 红灯。

## 1. 总体结论

Dawn 已经不是“只有 happy path 的玩具”：自举固定点成立，编译器、站点、Web 包和
Playground 都有可运行测试，错误恢复、持久集合、效果多态、模块分析和 JVM 互操作也有相当完整的
实现。此次审查运行的现有测试均通过。

但代码库当前有五类系统性问题（**处置见每条后的括注**）：

1. **规范、EBNF、README、历史方案和实现不再处于同一版本。** `docs/spec.md` 仍称
   “v0.1 草案”，README 仍停在 M4，而工具已经是 0.11；EBNF 已不能准确描述当前解析器。
   （**已修，EBNF 除外**：spec/README/tutorial/design/bootstrap/trait 与源码注释已对齐，
   新增 `docs/README.md` 索引并给每篇标 normative/current/historical；EBNF 改标
   historical 而非逐条修——理由见 SYN-04。）
2. **“纯函数签名即契约”的核心卖点存在公开逃生门。** `unsafe_pure` 对普通用户开放，并且还是
   comptime 反射执行 Java 静态方法的许可证；这是编译不可信源码时必须单独建立威胁模型的边界。
   （**待办，见 LANG-01**。已做的补偿：Playground 改 fail-closed 沙箱 + 编译阶段独立
   timeout，即「编译不可信源码」这个唯一在跑的场景已经收口。）
3. **编译器已超过最初“小而直接”的架构预算。** 7,924 行的 checker、3,531 行的 emitter、
   大型状态记录、直接 TAST→ASM 和二进制运行时续传，使维护成本与文档里的原始论证明显脱节。
   （**ARCH-01/02 已做**、ARCH-04/05 让位 + 已修文档：`design.md` 已标明
   「6–8 千行 Kotlin 预算」等前提已被推翻，不再读作现状。重构本身不在本次范围。
   **2026-08-03 复测**：checker 已是 **11,308** 行；emitter 反而降到 **2,534** 行——
   lowering 搬进了 Core，那部分不是消失是换了地方。拆分**当日落地**（#88）：
   checker **8,203**、codegen **706**、emit **2,309**，另有 `cx` / `passes` /
   `rtclasses` / `jvmhelp` 四个新模块。见 [arch-split-design.md](arch-split-design.md) §10。
   注意**总行数几乎没变（+220）**——拆分买到的是模块边界与状态收窄，不是代码变少。）
4. **几个对外包存在确定的协议错误。** JSON 会丢失大整数精度并能输出非法 JSON；Web body limit
   在完整读入后才检查；query/form、CORS、响应体和错误模型也有明显接口缺陷。
   （**大部分已修**：JSON-01/02/03、WEB-01/02/05/08 都已修并加了回归测试。响应体与错误
   模型的 ADT 化（WEB-06、ERR-02、WEB-09）是破坏性 API 变更，列为待办。）
5. **自举证明与供应链可信被混在了一起。** B==C 能证明固定点，不能证明种子、续传 class 或下载
   工件可信；当前种子没有 checksum，关键集合运行时也没有主干源码和直接测试。
   （**已修一半**：种子现在有 `scripts/seed-checksums.txt`，每次使用前校验、失败即退出；
   jar 跨时区可复现（BOOT-04）。集合运行时的源码回归归 BOOT-01，见该条。）

建议先处理 P0/P1 的安全与数据正确性问题，再决定是否继续扩语言特性。继续加特性会放大 checker、
TAST、codegen、LSP、spec 和历史文档之间的同步税。

> 本次处置正是按这个顺序做的：安全与数据正确性（JSON 精度、种子校验、body limit、
> URL 解码、CORS、header 注入、`catch_panic` 范围、包解压上限）先修，架构重构一条未动。

## 2. 审查基线

### 2.1 仓库规模

- Git 跟踪文件：514。
- Dawn 源文件：95；`selfhost/`、`std/`、`packages/`、`playground/`、`site/`
  合计约 35,328 行 Dawn。
- 主要单文件：
  - `selfhost/src/check/checker.dawn`：7,924 行，约 215 个函数/test。
  - `selfhost/src/jvm/emit.dawn`：3,531 行，约 121 个函数/test。
  - `selfhost/src/jvm/codegen.dawn`：2,512 行。
  - `selfhost/src/front/parser.dawn`：1,932 行。
  - `selfhost/src/ir/interp.dawn`：1,699 行。
  - `selfhost/src/lsp/lspq.dawn`：1,671 行。
- `docs/` 下当前有 28 篇被跟踪的 Markdown，而 `CLAUDE.md:21` 仍写“14 篇、4000+ 行”。
  （**已修**：`CLAUDE.md` 改为「30 篇、9000+ 行」并指向新的 `docs/README.md` 索引。）

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
  （**已自动化**：`scripts/json-suite.sh` 现在在 CI 每次跑这 283 例，另对每个 `y_`
  加跑 parse→render→parse 往返——JSON-03 正是往返能抓、判定抓不到的那类 bug。）

最小复现还确认了：

- `中文`、`_hidden` 等不符合规范正则的标识符可编译运行。
- `make()(1)` 不能解析，说明调用不是一般后缀运算。
- JSON 文本 `9007199254740993` 被解析再渲染为 `9007199254740992`。
- JSON 文本 `1e400` 被解析再渲染为 `Infinity`。
- 解析 `"\\b\\f"` 后再渲染会直接写出字节 `08 0c`，不是合法 JSON 转义。

`unsafe_pure` 的编译期宿主副作用风险按要求只做源码级审查，未继续做动态利用验证。
本次处置同样没有做动态验证——LANG-01 是待办，不是已修。

**上述最小复现的现状**（同一命令重跑）：

| 复现 | 处置前 | 处置后 |
|---|---|---|
| `中文` / `_hidden` 标识符 | 可编译运行 | 不变（SYN-01 驳回，改的是规范措辞） |
| `make()(1)` | 语法错误 | 可编译运行（SYN-02 已修，2026-07-30/31 两刀） |
| `9007199254740993` 往返 | `9007199254740992` | `9007199254740993` |
| `1e400` 往返 | `Infinity` | `Err("number out of Float range: 1e400 at offset 0")` |
| `"\b\f"` 往返 | 裸字节 `08 0c` | `"\b\f"` |

另外发现审查漏掉的一档：`99999999999999999999`（超 2^63）处置前**饱和成
`Long.MAX_VALUE`** 才输出，比 2^53 那档更糟。

### 2.3 优先级

- **P0**：安全边界、静默数据损坏或供应链根问题，应阻止不可信输入或发版。
- **P1**：确定的协议/语义错误，或很可能造成生产故障的架构问题。
- **P2**：长期维护、扩展性和 API 人体工学问题。
- **P3**：文档、命名、注释或低风险一致性问题。

## 3. 最高优先级摘要

| 编号 | 优先级 | 问题 | 处置 |
|---|---:|---|---|
| LANG-01 | P0 | `unsafe_pure` 对用户开放，且 comptime 会在编译器进程内反射执行 Java 静态方法 | **待办**（需设计文档；Playground 侧已收口） |
| BOOT-01 | P0 | 关键集合运行时 class 无主干源码和直接测试，并从种子逐代续传 | **待办**（去 Java 化改造正在做同一件事） |
| BOOT-02 | P0 | 种子 jar 下载没有 checksum 或签名 | **已修** |
| JSON-01 | P0 | JSON 整数先转 Float，超过 2^53 静默损坏 | **已修** |
| JSON-02 | P1 | JSON renderer 可输出 `Infinity` 和未转义控制字符 | **已修** |
| WEB-01 | P1 | body limit 在 `readAllBytes` 之后执行，无法阻止内存型 DoS | **已修** |
| PKG-01 | P1 | 包下载/解压无体积、条目数、膨胀率和超时限制 | **已修** |
| CLI-01 | P1 | `write_class` 吞掉目录创建和文件写入错误 | **已修** |
| ARCH-01 | P1 | checker/emitter 已形成大型单体和超宽状态对象 | **已处置**（ARCH-01/02 同批，2026-08-03：[arch-split-design.md](arch-split-design.md) 十二刀落地，任务 #88） |
| ERR-01 | P1 | `catch_panic` 捕获全部 `Throwable`，会吞下 JVM 致命错误 | **已修** |
| DOC-01 | P1 | 权威 spec、EBNF 和当前实现存在多处可执行语法冲突 | **已修**（EBNF 除外，见 SYN-04） |

## 4. 语法与语法文档

### SYN-01（P1）标识符规则与 lexer 不一致

> **【驳回 —— 保留 lexer 的行为，改的是规范措辞】**
>
> 两个选项里审查倾向「严格按 ASCII 拒绝」。不选它，因为那会**破坏已经能编译的代码**，
> 而换来的东西很薄：`中文` 作函数名今天合法，收紧就是一次静默的语言收窄，
> 对 dawnop-site 这类按 release 钉版本的下游尤其不友好（CLAUDE.md：破坏性改动要先发 tag）。
>
> 「正式定义 Unicode XID + normalization」是对的方向，但那是一份独立的设计文档
> （XID_Start/XID_Continue 表从哪来、NFC 在哪一步做、同形字符要不要管、
> parser 的大小写消歧对非大小写文字怎么定义），不是一次审查修复能顺手做完的。
>
> 真正**现在就有害**的是「规范说 A、实现做 B」——那条已经修：`docs/spec.md` §1 现在
> 描述实现的实际行为并把 Unicode 收敛标为未定义。规范不再撒谎，收窄与否留给后续 RFC。


**证据**

- `docs/spec.md:27` 和 `docs/grammar.ebnf:3` 将值标识符限定为
  `[a-z][a-z0-9_]*`，类型限定为 ASCII `UpperCamelCase`。
- `selfhost/src/front/lexer.dawn:59` 使用 `Character.isLetter` /
  `Character.isLetterOrDigit`，`selfhost/src/front/lexer.dawn:209` 还允许 `_` 开头。
- 实测 `fn 中文(值: Int)` 和 `fn _hidden(_值: Int)` 可编译运行。

**影响**

- “命名是语义、parser 靠大小写消歧”的规范不再精确。
- 源码标识符、模块路径、包名和 manifest 名称使用不同字符集合。
- 无大小写文字可作值名，却难以自然地作类型名；Unicode 规范化和同形字符也未定义。

**建议**

明确二选一：严格按 ASCII 规则拒绝，或正式定义 Unicode XID、大小写分类和 normalization。
不要继续让 Java `Character` 的实现细节充当语言规范。

### SYN-02（P1）函数值调用不是正交的一般后缀调用

> **【已修 —— 分两刀，设计见 [application-syntax](audit/application-syntax-design.md)】**
>
> 描述准确：`make()(1)` 当时确实不能解析。
>
> - **2026-07-30（加法）**：postfix 循环加同行 `(` 臂，三个验收形态全通，旧程序的
>   AST 与错误文案逐字节不变。
> - **2026-07-31（统一）**：删掉 `ident_or_call` 与构造器调用两处特判，`f(x)`、
>   `Circle(1.0)` 与 `make()(1)` 走同一条后缀路径、落到同一个 `EApply` 节点；
>   `ECall` 从 AST 消失。是哪种调用改由 checker 按 callee 判（`check_apply` 四分支），
>   named argument 随之在**每个调用位置语法合法**、只有构造器接受——这一条结清了
>   SYN-03。AST dump 因此重基线（`Emit-Change(parse …)`），字节码不变
>   （同一棵 typed tree：改前的全部源码在新旧编译器下 `__emit` 逐字节相同）。
>
> 审查给的第二个选项（「在规范里明确承认这是受限的一等函数并删掉错误的 EBNF」）
> 没有走：真正的问题不是文档说错了，是实现少做了一步。现在 spec §4.3 正面写了
> 新规则（含跨行 `(` 不吃、named argument 由类型判定）。


**证据**

- `docs/grammar.ebnf:89` 把 `call_args` 定义为任意 `primary_expr` 的 postfix。
- `selfhost/src/front/parser.dawn:1263` 的 postfix 循环只处理 `?`、`!`、`[]` 和 `.`。
- 普通调用只在 `selfhost/src/front/parser.dawn:1458` 的 `ident_or_call` 特判。
- 构造器调用也在 `selfhost/src/front/parser.dawn:1390` 单独特判。
- 实测 `make()(1)` 在第二个 `(` 报语法错误。（以上均为处置前的行号与行为。）

**影响**

语言声称函数是一等值，但只有“名字绑定到函数值”时能调用；条件表达式、字段读取结果、
函数返回值等不能直接应用。parser、AST 和 checker 因此同时保留 `ECall`、`EMethod`、
`EApply`/动态调用等多套路径，复杂度高于真正统一的 application。

**建议**

把调用落实成真正的 `Expr(args)` 后缀节点，再由 checker 区分静态函数、动态函数值、
构造器和 Java/UFCS；或在规范里明确承认这是受限的一等函数并删掉错误的 EBNF。

### SYN-03（P2）EBNF 的 named argument 范围错误

> **【已修 —— 先止血，2026-07-31 真正修完】**
>
> 第一步（止血）：EBNF 整体标为 historical 并指明以 parser 为准，这条具体的错误
> 随之不再误导。
>
> 第二步（SYN-02 的统一刀）：`arg = [ IDENT ":" ] expr` 现在是**真的**——名字在每个
> 调用位置都解析得下来，包括点调用与应用一个函数值。合法性从语法位置变成类型判定：
> 只有构造器接受名字，其余 callee 报的是类型错误（「`f` is a function, not a
> constructor; function calls do not take argument names」）而不再是一句
> 「expected `)`」。EBNF 里这四条产生式因此不再是 historical 的一部分。


`docs/grammar.ebnf:96` 写所有 `arg` 都可为 `IDENT ":" expr`，但
`selfhost/src/front/parser.dawn:1458` 的普通函数调用只存 `List[Expr]`；只有
`selfhost/src/front/parser.dawn:1398` 的构造器参数支持名称。这会误导语法高亮器、格式化器、
第三方 parser 和用户。

### SYN-04（P1）EBNF 已落后于当前语言

> **【已修（标状态），逐条修产生式驳回】**
>
> `docs/README.md` 把 `grammar.ebnf` 标为 **historical**，写明「已落后于 parser，
> 以 spec.md 与 `selfhost/src/front/parser.dawn` 为准」，并点名 SYN-02/03/04。
>
> 不逐条修，因为修完还是**第二份近似语法**——正是审查自己说的「不要手工维护」。
> 手工修一遍只会把它重新伪装成可信，然后在下一个特性时再次悄悄过期。
> 有价值的是审查给的两个方案：从 parser 的 production 生成 EBNF，或把 EBNF 纳入
> accept/reject corpus 测试。两者都是独立工作量（对应 TEST-04），列为待办。
> 在那之前，一份**诚实地标着「过期」**的语法文件比一份刚修过的准确语法更安全。


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

> **【驳回】**
>
> 审查自己写了「这不是语义 bug」。两处 `!` 的**位置不重叠**：效果只出现在签名的返回类型之后
> （`-> T !io`），unwrap 只出现在表达式后缀（`x!`），parser 从不需要在两者间消歧。
> 可读性的抱怨成立，但改语法要动 lexer/parser/formatter/LSP/高亮/全部现存代码与文档，
> 换一个纯风格收益——这个交换比不划算。若将来效果种类真的变多导致签名侧出现
> `!(a|b)!` 这类形态，再单独提。


`fn f() -> T !io` 与 `option!` 在视觉上分别表示“有副作用”和“断言非空”。两者都高频，
特别是在 Java builder 链中会出现连续多个 `!`。这不是语义 bug，但可读性和搜索性较差；
未来扩展更多效果后更明显。建议评估将 unwrap 改为显式方法、`!!` 或独立关键字。

### SYN-06（P2）点调用歧义规则对远处名字不稳定

> **【驳回 —— 这是刻意的取舍，且规范已写明理由】**
>
> `docs/spec.md` §2.4 明确：静默优先级会让远处新增一个同名函数**悄悄改变既有调用的含义**，
> 所以宁可报歧义。审查说这「牺牲了组合性」——对，但代价的方向是对的：
> 新增 import 导致**编译错误**（有消歧办法：`let g = r.f` 或 `f(r, x)`），
> 好过新增 import 导致**行为改变**。§10.3 对模块别名同名早已是同一条规矩。
>
> 「给字段调用和 UFCS 明确优先级」正是被否决的那个方案。


`docs/spec.md:190` 规定：若作用域内存在同名函数，`r.f(x)` 作为函数字段调用直接报歧义。
新增一个 import 或同名顶层函数就能让原本合法的字段调用失效。它避免了静默改义，却牺牲了
组合性。更稳定的方案是给字段调用和 UFCS 明确优先级，或用不同语法显式区分。

## 5. 语言设计

### LANG-01（P0，源码级风险，未继续动态验证）`unsafe_pure` 破坏核心纯度边界

> **【已修 —— 2026-07-30】** 建议 1 落地：`unsafe_pure` 收归 std（用户模块中即编译错误，
> spec §6.4 改判，生态零使用点）。建议 2（allowlist）被缝 1+缝 2+本收窄联合吞并——route C
> 已无合法生产者，表无对象可列（purity-boundary-design 顶部有记）。建议 3（trampoline）
> 维持冻结。P0 的「用户可达的不健全逃生门」自此关闭。
>
> 原判定：**【待办 —— P0 认可，但四条建议全部是语言变更，必须先有设计文档】**
>
> 风险描述准确，不打折扣。不在本次修的理由，逐条对着建议说：
>
> 1. **「普通用户代码禁用 `unsafe_pure`」**——这会让今天能编译的用户代码明天编不过，
>    且 std 自己要靠它（spec §11 的 `core/math` 就是 `unsafe_pure` 包 `java.lang.Math`）。
>    需要先定义「编译器签名/白名单」这个机制本身：白名单住哪、怎么随 std 版本走、
>    第三方包能不能申请。这是一份 `docs/<特性>-design.md`。
> 2. **「comptime 禁止反射任意 Java，改封闭 intrinsic allowlist」**——同上，
>    而且要先确定 allowlist 覆盖到哪，否则 comptime 直接失去大半用处。
> 3. **「comptime evaluator 放进资源受限子进程」**——最有效，也最伤：每次编译多一次
>    进程启动 + 全部 comptime 值的跨进程序列化。要有实测数据才能定（CONTRIBUTING：
>    性能断言必须有实测出处）。
> 4. **「把纯度保证改成精确定义」**——这条**可以现在做**，但它依赖 1–3 的结论：
>    先写「哪些逃生门让程序退出 sound subset」，再改 spec，否则要改两遍。
>
> **本次做了的补偿**：审查点名「编译不可信源码」的唯一实例是 Playground，
> 那条路径已经收口——沙箱改 fail-closed（PLAY-01，只有 `PLAY_UNSAFE_LOCAL=1` 能关），
> 编译阶段有了独立 timeout（PLAY-02，正是针对「反射一旦进入无法打断」）。
> 语言层的边界仍然敞着，这一条保持 P0 未决。


**证据**

- `docs/spec.md:532` 保证纯函数同参同值、无可观测副作用。
- `docs/spec.md:553` 又把 `unsafe_pure` 作为普通语言语法开放，并在
  `docs/spec.md:576` 承认其不健全。
- `docs/design.md:69` 的原决策却写逃生门“用户代码不开放”，与现状相反。
- `selfhost/src/check/checker.dawn:4733` 仅屏蔽效果，不限制调用者模块。
- `selfhost/src/ir/interp.dawn:660` 到 `selfhost/src/ir/interp.dawn:706` 会在编译器 JVM 中，
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

> **【待办 —— 认可，属语言变更】**
>
> 矛盾是真的。三个建议里「`cast` 返回 `Result`/`Option`」最干净，但它改的是一个
> **已在生产使用**的 API（`packages/web` 的流式响应、Playground、dawnop-site 都在用
> `cast`），每个调用点都要改，属破坏性语言改动 → 先发 tag 的流程。
>
> 顺带说清一件本次已经改了的事：审查说「pure 同时表示无副作用和不会以隐藏控制流退出」
> 是混淆——对。README 现在明说「没有异常」是语法而非运行时保证，并列出 `cast` 会抛
> `ClassCastException`（见 LANG-03）。文档不再骗人，签名仍然骗人。


`selfhost/src/check/types.dawn:563` 给 `cast` 纯签名；`docs/cast-interop.md:33` 和
`docs/spec.md:850` 又明确失败抛 `ClassCastException`。这使一个签名为 pure 的函数可抛出
非 Dawn panic 的宿主异常，与 `docs/design.md:60`“异常破坏签名即契约”的论证冲突。

建议让 `cast` 返回 `Result`/`Option`，或把 checked cast 作为显式不安全效果；至少不要用
“pure”同时表示“无副作用”和“不会以隐藏控制流退出”。

### LANG-03（P1）“没有异常”只是表面语法，不是运行时保证

> **【已修（文档部分）】**
>
> README 的「没有异常」已改写：明说 Dawn 没有 `throw`/`catch`、可恢复失败走 `Result`，
> **但 JVM 异常会穿透 Dawn 栈**，并点名 `cast` 与任意 `use java` 方法，
> 指向 `java_try` / `catch_panic` 两个边界工具与 spec §8.2、§9。
>
> 「为 FFI 提供结构化边界」是 ERR-02，见该条（待办）。


`docs/spec.md:886` 规定 Java 异常默认穿透并终止。`cast`、错误泛型集合取值和任意 Java 方法
都能把异常带过 Dawn 栈。因此 README 的“没有异常”会让用户误以为所有失败都在
`Result`/panic 模型内。应改成“Dawn 无 throw/catch 语法，但 JVM 异常可能穿透”，并为 FFI
提供结构化边界。

### ERR-01（P1）`catch_panic` 捕获 `Throwable` 过宽

> **【已修】**
>
> `codegen.dawn` 的 `gen_try_closure` 现在收 `List[String]` 而不是单个类型
> （多条 try-catch 表项指向同一 handler，这是 JVM 拼「catch A 或 B」的写法），
> `catchPanic` 从 `java/lang/Throwable` 改成 **`dawn/rt/PanicError` + `java/lang/Exception`**。
>
> `OutOfMemoryError`、`StackOverflowError`、`LinkageError`、其余 `VirtualMachineError`
> 不再被吞。原来的行为是：把 OOM 变成一个字符串，在仍然耗尽的堆上渲染一个 500，
> 而进程里其它线程正以同样方式失败——那是该死掉的状况，不是该总结的状况。
> `PanicError` 是 `Error` 的子类，所以必须与 `Exception` 分开点名。
>
> **这改变了发射的字节码**：提交需带 `Emit-Change:` 行。固定点已验证仍成立（B == C）。


`selfhost/src/jvm/codegen.dawn:953` 的 `java_try` 捕获 `Exception`，但下一行的
`catch_panic` 捕获 `java/lang/Throwable`。这会把 `OutOfMemoryError`、`StackOverflowError`、
`LinkageError`、`ThreadDeath` 等不应恢复的 JVM 错误变成字符串，服务器可能在不可靠状态继续运行。

建议只捕获 `PanicError` 加一组明确可隔离的异常，而不是全部 `Throwable`。

### ERR-02（P1）异常被降成字符串，跨层接口依赖消息文本

> **【待办 —— 认可】**
>
> 「重构错误文案 / JDK 版本变化 / 本地化都可能改变程序控制流」说得对，
> `packages/web/src/types.dawn` 的 `as_http_with` 就是这个病的临床表现。
>
> 不在本次修：`java_try`/`catch_panic` 的返回类型是 **intrinsic 契约**
> （`Result[T, String]` 直接烧在 `gen_try_closure` 发射的字节码里），
> 改成结构化错误要同时动 codegen、prelude ADT 表、全部 `java_try` 调用点，
> 以及每个把 `Err(String)` 往上传的库。
> 这是一次跨编译器与生态的变更，值得一份设计文档而不是顺手改。
>
> 方案见 [error-model](audit/error-model-design.md)。**建议里的 `JavaError` 已改名
> `ForeignError`**：`class_name` 是 JVM 二进制名，而 native 后端上没有类名——
> 一个跨 FFI 边界的错误类型不该从第一天就假设有 Java 类（台账 §3.3）。
>
> **进度（2026-07-30）**：分期落地的三期都已合并——`catch_fault`/`catch_panic`
> 与 `std/io` 会失败的那 9 个函数都已返回 `Result[T, ForeignError]`，下面那句
> 「只返回 `Result[T, String]`」不再成立；过渡拼法 `_e` 也已随阶段 3 删除，
> 语言里只剩一对屏障。本条仍挂着，是因为 `packages/web/src/types.dawn` 的
> `as_http_with` 还在按文本分类（那半边是 WEB-06）。


- `java_try`/`catch_panic` 只返回 `Result[T, String]`，丢失类型、cause、stack 和结构化字段。
- `docs/spec.md:901` 建议按类名前缀匹配字符串。
- `packages/web/src/types.dawn:93` 的 `as_http_with` 明确因为 repo 只有字符串错误而分类。

这让重构错误文案、JDK 版本变化和本地化都可能改变程序控制流。建议引入最小
`JavaError { class_name, message, cause }` 和业务错误 ADT。

### ERR-03（P1）缺少 `finally`/资源作用域

> **【待办 —— 认可】**
>
> 诊断准确：`catch_panic` 被当 finally 用（`server.dawn` 写 response、
> `gate.dawn` 放许可、`exec.dawn` 删临时目录），既促成 ERR-01 又丢原始上下文。
>
> 两个建议里 **`bracket(acquire, use, release)`** 是标准库函数、不需要动语言，
> 是明显更小的一步；`defer` 要动 parser、checker 与 codegen。
> 但即使是 `bracket`，「编译器/runtime 保证 release」这半句仍要 codegen 参与
> （否则它只是又一个 `catch_panic` 包装）。先写设计文档定这条线画在哪。


语言没有 `try/finally`、`defer`、`using` 或线性资源协议。结果是
`packages/web/src/server.dawn:227`、`playground/src/play/gate.dawn:27` 等处用
`catch_panic` 模拟 finally，再重新 panic。它既促成 ERR-01，又丢失原始异常上下文。

建议提供最小 `defer` 或标准库 `bracket(acquire, use, release)`，并让编译器/runtime 保证 release。

### LANG-04（P2）字符只是 `Int`，类型系统不能保证 Unicode scalar

> **【改判 —— 2026-07-30】** 机制已存在：`pub opaque type Char = Int` + 受检构造
> `char_of` 就是本条要的形状（nominal-types-design §2.4 的 API 对，载体换成现成的
> opaque type，不引入 `new`）。剩余的是 `'a'` 字面量类型切换的**迁移刀**（lexer/json/
> fmt 全部调用点 + 发布窗口），等真实需求再排。
>

> **【待办 —— 认可，属语言变更】**
>
> 「Cursor 已经证明不透明标量可行」是很强的论据：`Cursor` 就是同一招，
> 而且 std 源码造不出它（`std/cursor.dawn` 的文件头写着这份不透明性就是全部意义）。
> 照做需要新增一个 `Char` 不透明类型 + 转换函数 + 迁移全部 `'a'` 字面量的类型，
> 属语言变更。


`docs/spec.md:60` 把字符直接定义为 Int；`docs/spec.md:1066` 又规定非法码点在
`from_code_points`/`str.from_char` 时 panic。任意整数都能冒充字符，API 无法在签名上区分
索引、计数、字节和字符。Cursor 已经证明不透明标量可行，Char/Rune 也应采用同样方案。

### LANG-05（P2）透明 alias 不能提供领域安全

> **【已修 —— 2026-07-30】** spec §2.6 的警示改为直接指路 §2.7 `opaque type`
> （原文写「Dawn 目前没有」——§2.7 落地后没人回来改，答案一直存在）。
> `type X = new T` 第二机制被驳回，理由在 nominal-types-design 顶部。
>

> **【已修（示例部分），newtype 待办】**
>
> 两个建议里第二个（「避免用单位类型作为透明 alias 示例」）是零风险的，
> 且正好治了「容易让用户误以为得到单位安全」这个具体危害——spec §2.6 现在
> 用 `Meters = Float` 时明确标注它与 `Float` **完全互换**、不提供任何单位安全，
> 想要单位安全需要 newtype，而 Dawn 没有。
>
> 真正的 newtype/opaque type 是语言变更，待办。


`docs/spec.md:207` 用 `Meters = Float` 举例，但 `docs/spec.md:217` 明确它与 Float 完全互换。
这类例子反而容易让用户误以为得到单位安全。建议增加真正的 newtype/opaque type，或避免用单位
类型作为透明 alias 示例。

### LANG-06（P2）模块限定访问不完整

> **【待办 —— 认可】**
>
> `m.Type` / `m.Ctor` / `m.CONST` 是 checker 名字解析的扩展，
> 会与 §10.3 的消歧规则交互（`m.Foo` 到底是模块 `m` 的类型 `Foo`，
> 还是值 `m` 的字段 `Foo`？后者按 SYN-06 的规矩本来就要报歧义）。
> 需要设计文档把这层定清楚。


`docs/spec.md:985` 只允许 `alias.fn(args)`；类型、构造器、常量必须选择性导入到本地。
同一个模块 API 被迫使用两套访问风格，类型和常量会污染命名空间，也让自动补全和批量重命名更难。
建议支持 `m.Type`、`m.Ctor`、`m.CONST`。

### LANG-07（P2）目录模式无条件加载全部源码

> **【驳回（禁环部分）+ 待办（加载范围部分）】**
>
> **禁环不改。** 「排除了常见的 type-only cycle」是事实，但 Dawn 的编译单元是模块、
> 求值顺序按拓扑序定义（spec §10.5），环会让顶层 `const` 的 comptime 求值顺序无定义。
> 要支持 type-only cycle 就得先把「类型引用」与「值依赖」拆成两张图——这是 checker
> 的结构性改动，换来的是一个此仓库尚未遇到的场景。
>
> **「全仓 lint/test」与「构建当前入口闭包」分开**是对的，列为待办：它对大型工程、
> 平台专用模块、生成代码确实是硬阻碍。但那要引入「入口」这个新概念到目录约定里
> （spec §10.1 现在明说「目录约定即工程定义，不需要清单文件」），
> 是对现有模型的正面修改，不是修 bug。


`docs/spec.md:1002` 要求加载 `src/` 下全部 `.dawn`，未引用模块也必须检查，依赖图还完全禁环。
这对小项目能防 bit-rot，但会阻碍大型工程、平台专用模块、生成代码和仅测试依赖，也排除了常见的
type-only cycle。建议把“全仓 lint/test”与“构建当前入口闭包”分开。

### LANG-08（P2）全部 Java 引用返回都包 Option，产生大量无信息解包

> **【驳回】**
>
> 「读取 `@NotNull`/JSpecify 或维护小型 JDK nullability 数据库」——两条都不做：
>
> - **读注解**：JDK 自己基本不带 JSpecify/`@NotNull`（那是第三方库的实践），
>   所以对「绝大多数 JDK 方法」这个抱怨的主体几乎无效。
> - **维护 JDK nullability 数据库**：这是把 JDK 的空值合约抄一份进本仓库并**永久维护**，
>   跨 JDK 版本更新，且抄错的方向是**危险的**（错标 NotNull → null 溜进语言，
>   正是这条保守规则要防的东西）。
>
> 保守规则的性质是：错的时候只是啰嗦，对的时候救命。不对称有利，就保持它。
> `!` 在 builder 链上密集是真的难看，但那是 SYN-05 的可读性范畴。


`docs/spec.md:668` 自承绝大多数 JDK 方法永不返回 null，因此 `!` 成为互操作常态。
统一保守规则简单，但把 Java 注解、已知 JDK 合约和 builder API 的信息全部丢掉。
可以继续默认 nullable，同时读取 `@NotNull`/JSpecify 或维护小型 JDK nullability 数据库。

## 6. 编译器与代码框架

### ARCH-01（P1）checker 是 God module

> **【已处置 —— 认可，2026-08-03 落地】**
>
> 方案与落地结果 = [arch-split-design.md](arch-split-design.md)（任务 #88），
> 十二刀从 `4ae6b61` 到 `94109b7`。checker 侧的结果：
> `checker.dawn` **11,308 → 8,203 行**，拆成 `cx.dawn`(753) → `passes.dawn`(2,492)
> → `checker.dawn` 的三层 DAG；`Cx` **47 字段 → 40 + `Frame`(8)**。
> 12 个注册期 pass 与 body 检查那半边确实是调用图上的一刀干净的割
> （交集 = 19 个共享 helper，已下沉到 `cx.dawn`）。
> 全程**零 `Emit-Change`**，五个外部语料 465 个 class 文件逐字节零差异。
>
> **这条被否决的部分要一起记下来**（否则下一轮审查会重新提一遍）：
> 下面「拆成符号环境 / 类型推断状态 / … 六个组件」的建议**判为不执行**，
> 见该文 §6.1——`check_fn` 家族五个入口的传递可达字段是 41/47，body 检查是一个整体，
> 切成六份不会让任何一个入口少收一个字段；而 `DiagSink` 想要的漏斗
> （诊断只从 `cerr`/`cerr_h`/`cerr_o` 三个写点进）**今天已经存在**。
> 同样判为不做的还有：checker 的 Java 簇（`check_java_call` 在 19 函数 SCC 里面）、
> `Gen` 三分、`mv` 整体移出 `Gen`。
>
> **留了一笔账**：`enter_isolated`/`leave_isolated` 的**恢复集正确性全仓没有任何门禁
> 能验证**——实测把这两个函数改成「什么都不恢复」，诊断语料与 295 个内联 test 仍然
> 全绿（该文 §5.4）。补语料 = **#126**。
>
> ---
>
> **【原裁决：待办 —— 认可】**
>
> 最尖锐的一句是「不可变记录线程化只是把『一个可变大对象』变成『每步复制/更新一个
> 不可变大对象』，没有真正降低耦合」——这条批评成立，不可变性在这里买到的是
> 数据竞争安全，不是模块化。
>
> 拆成六个组件是正确的方向，也正因为正确才不能顺手做：`Cx` 的字段被整个 checker
> 以任意组合读写，拆分要么是一次几千行的机械改写（风险大、评审不可能细看），
> 要么分多次做（每次要能独立验证）。**前提是先有 lowered IR**（ARCH-04）——
> 否则 checker 拆完，emit 仍然直接吃 TAST，耦合只是换了个地方。
> 先做 IR、再拆 checker，顺序反了会做两遍。
>
> **前提已满足（2026-08-03）**：Core IR 随 native 计划 Phase 0 落地，`runtime-intrinsics-design.md`
> §8 记的那三处「漏进 emit 的 lowering」已全部关闭——逐行核对见
> [core-move2-design.md](core-move2-design.md) §1.1（在 `77d7aa4` 上做的核对）。
> emit 残余的 TAST 依赖是「关于**类**的问题」（方法名/描述符），不流经 `Cx`。
> **本条的方案 = [arch-split-design.md](arch-split-design.md)**（任务 #88）；
> 下面那句「拆成符号环境 / 类型推断状态 / … 六个组件」的建议**已被它复测取代**，
> 理由见该文 §6.1：body 检查是一个整体，切成六份不会让任何一个入口少收一个字段；
> 而 `DiagSink` 想要的漏斗（诊断只从 `cerr`/`cerr_h`/`cerr_o` 三个写点进）**今天已经存在**。


`selfhost/src/check/checker.dawn` 有 11,308 行、249 个函数 + 88 个内联 test。
`Cx` 在 `selfhost/src/check/checker.dawn:91` 到 `selfhost/src/check/checker.dawn:164`
包含 47 个字段（以上为 2026-08-03 在 `86b1cec` 上的复测值；审查当日记的是
7,924 行 / `:76-132` / 44 字段——**没修之前只会更大**；#88 落地后是
8,203 行 / `Cx` 40 字段 + `Frame`(8)，定义已移到 `cx.dawn`），混合了：

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

> **【已处置 —— 认可，2026-08-03 落地】**——与 ARCH-01 同批，两条 lane 并行。
>
> 后端侧的结果：`codegen.dawn` **3,425 → 706 行**（`dawn/rt/*` 的字节码写手抬成叶子模块
> `rtclasses.dawn`，2,745 行）；`emit.dawn` **2,534 → 2,309 行**（无状态 helper 抬成
> `jvmhelp.dawn`，279 行）；`Gen` **21 字段 → 12 可变 + `GenCtx`(8 只读)**。
> 落地结果见 [arch-split-design.md](arch-split-design.md) §10。
>
> **被否决的部分**（同样要记，见该文 §2.5/§6.2）：`Gen` **不三分**——只读的那半边不进
> 返回值，元数才不涨；三分会让 `gen_load_const`/`emit_sam_conversion`/`gen_ccall`
> 返回三元组而换不到任何签名收窄。`mv` **不整体移出 `Gen`**（266 处读、39 个函数，
> 收益只是删掉一个 `scratch_mv()`）。`slots`/`syms` **不改成每方法清空**。
> `consts`/`blocks` **不抽跨后端共享模块**。`emit_module` 的位置对齐**不碰**
> （会改方法进 class 的顺序 = 改字节）。
>
> ---
>
> **【原裁决：待办 —— 认可】**——同 ARCH-01。「排在 lowered IR 之后」这个前提也同 ARCH-01
> 已满足（Core IR 的 Phase 0 已落地）。
>
> **本条的方案 = [arch-split-design.md](arch-split-design.md)**（任务 #88）。两件口径要更正：
>
> 1. **ARCH-02 的真实盘子是 `codegen.dawn` 3,425 行 + `emit.dawn` 2,534 行 = 5,959 行**
>    （2026-08-03 复测）。`selfhost/src/embed/unicode_class.dawn`（2,089 行）与 `unicode_case.dawn`
>    （1,384 行）**不是后端模块**——它们是 `scripts/unicode-contract/probe.dawn` 生成的
>    Unicode 数据表（文件头写着「GENERATED … do not edit」），两个后端都读，
>    把它们算进后端盘子是口径错误。
> 2. 那 5,959 行里，**`codegen.dawn` 的 3,425 行一次都没提到 `Gen`**（`grep -c '\bg\.'`
>    为 0，全文唯一的 "Gen" 是注释里的 "CodeGen.kt"）。所以第一刀不是「按子系统给 `Gen`
>    分层」，而是**把本来就不碰 `Gen` 的行搬成叶子模块**。见 arch-split-design.md §2.2。


`selfhost/src/jvm/emit.dawn` 2,534 行；`Gen` 在 `selfhost/src/jvm/emit.dawn:92` 到 `:128`
有 21 个字段（2026-08-03 复测；审查当日记的是 3,531 行 / `:159` / 30 余字段——
`emit.dawn` 变短是因为 lowering 已经搬进 Core；#88 落地后是 2,309 行 /
`Gen` 12 字段 + `GenCtx` 8 字段），
同时管理 JVM 栈槽、闭包、SAM、函数值桥、构造器桥、trait witness、常量字段和控制流 label
（下面这份职责清单也是审查当日的：`pending_lambdas`/`lambda_ctr`/`pending_fnval`/
`pending_bi`/`pending_ctorb`/`emitted_*`/`fn_start` 已随 lowering 一起离开 `Gen`，
`loop_stack` 换成了 `cloops`）。
新增任一语义特性都很容易触碰整个后端。

建议引入 method-local builder、closure lowering、trait lowering、constant materialization 等分层，
而不是继续扩 `Gen`。

### ARCH-03（P1）“第二后端只改 intrinsic 表”不成立

> **【已修（删掉误导性承诺），第二后端待办】**
>
> 审查给了两条路：定义 backend-neutral IR，或**删除误导性承诺**。
> `CLAUDE.md` 的说法已经收窄——不再说「接第二后端只需重指向 `rt_intrinsic_target`」，
> 改为「这是**运行时 intrinsic 那半边**唯一要重指向的地方」，并明说
> `TJavaCall` 携带 JVM 类名/descriptor/SAM/List bridge、checker 依赖 Java 反射、
> emit/codegen 遍布 ASM opcode，真接第二后端要先有 backend-neutral lowered IR。
>
> 顺带说明：仓库里已有 [llvm-backend-research.md](llvm-backend-research.md) 与
> [collections-dejava-research.md](collections-dejava-research.md)，
> 第二后端这条线正在**独立进行中**，本次不动它涉及的文件。
>
> **后续（07-25 晚）**：那条线已出
> [native-backend-plan.md](native-backend-plan.md)——Phase 0 就是本条要的
> backend-neutral IR，Phase 5 就是本条要的 FFI capability。**本条整条让位**，
> 台账 [§二](audit/native-plan-overlap.md)。


`CLAUDE.md:73` 声称接第二后端只需重指向 `rt_intrinsic_target`。实际：

- `selfhost/src/check/tast.dawn:25` 的 `TJavaCall` 直接携带 JVM 类名、descriptor、SAM 和 List bridge。
- checker 直接依赖 Java reflection。
- `emit.dawn`/`codegen.dawn` 大量使用 ASM opcode、JVM descriptor、LMF、CHECKCAST。
- runtime 表示、擦除、装箱和异常也都写死 JVM。

当前架构可以合理地选择“只支持 JVM”，但不能同时宣称后端中立。若真要第二后端，应先定义
backend-neutral lowered IR 和 FFI capability；若不打算做，应删除误导性承诺。

### ARCH-04（P2）“无 IR”的原始论证已过期

> **【已让位 —— 认可，且它确实是 ARCH-01/02/03/05 的共同前提】**
>
> 「不是立刻造大而全 SSA，而是增加一个小型 lowered IR」这个分寸是对的。
> 已做的部分：`design.md` 现在标明「不引入 IR」的论证前提（编译器 6–8 千行）
> 已被推翻，不再读作现状。
>
> **本条让位给 [native-backend-plan.md](native-backend-plan.md) 的 Phase 0。**
> 两边独立写出的方案结论一致（一层 IR、不做 SSA、验收是输出逐字节不变），
> 但那份的节点集更全——本目录列的六样（call / 控制流 / match / closure /
> trait witness / FFI）漏了**装箱擦除**与**所有权（dup/drop）**两样，后者是
> Perceus 决策的直接后果，会改 IR 的形状。[audit/lowered-ir-design.md](audit/lowered-ir-design.md)
> 因此降级为它的补充材料，只保留 ARCH-01/02 的拆分方案——**那部分不在 Phase 0 里**。
> 台账 [§3.1、§3.2](audit/native-plan-overlap.md)。
>
> **后续（2026-08-03）**：Phase 0 已落地，本条作为 ARCH-01/02 前提的那一半随之解除；
> 它给 lowered-ir-design.md 保留的最后一块（§3.2/§3.3 的 `Cx`/`Gen` 拆分方案）也
> **已被 [arch-split-design.md](arch-split-design.md) 复测取代**。那份文档现在整篇是补充材料。


`docs/design.md:73` 在小编译器阶段拒绝 IR 是合理的，但现在 TAST 同时承担类型树、lowered tree、
Java ABI 和 codegen 输入，checker+emit 已超过一万行。没有 IR 使 desugar、优化、后端验证、
调试 dump 和第二后端都只能侵入 checker/emitter。

建议不是立刻造“大而全 SSA”，而是增加一个小型 lowered IR：统一 call、控制流、match、
closure、trait witness 和 FFI，再从该层生成 JVM。

### ARCH-05（P1）运行时支持以 ASM 手写生成，维护和测试成本过高

> **【待办 —— 认可，但与进行中的去 Java 化改造重叠，本次刻意不碰】**
>
> 三条建议里第三条（「opcode、descriptor 和 class builder 统一到一个后端模块」）
> 是可以独立做的整理。前两条（「纯运行时逻辑用可编译的 Java/Dawn 源维护」）
> 恰好是 [collections-dejava-research.md](collections-dejava-research.md) 方案 C
> 正在解决的问题，而且是**同一批文件**（`codegen.dawn` 的 `dawn/rt/*` 生成、
> `vendor.dawn`、`emit.dawn` 的 intrinsic 表）。
>
> 在那条线落地前动这些文件只会产生冲突，且很可能白做。等它落地后再评估还剩什么。
>
> 本次在 `codegen.dawn` 只做了一处**局部**改动（ERR-01 的 `gen_try_closure`），
> 因为那是确定的安全 bug，且改动面是单个函数。


`selfhost/src/jvm/codegen.dawn` 用数千行 opcode 生成 `dawn/rt/*`。opcode 常量还分散在
`codegen.dawn` 与 `emit.dawn`。这让普通运行时逻辑难以做源码级单测、静态分析、调试和安全审计。

建议：

- 纯运行时逻辑用可编译的 Java/Dawn 源维护；
- 只有真正与生成类型相关的薄桥留在 ASM；
- opcode、descriptor 和 class builder 统一到一个后端模块。

### BOOT-01（P0）关键集合运行时只有续传二进制，没有主干源码

> **【待办 —— P0 认可，正在被另一条线解决】**
>
> 每一条都成立，尤其「固定点会忠实复制同一二进制，因此 B==C 不能发现其中的恶意或
> 历史 bug」——这与 BOOT-03 是同一个洞的两面。
>
> 不在本次修，因为**已经有人在修**：`DawnList`/`DawnMap`/`DawnSet` 的去 Java 化
> 正在按 [collections-dejava-research.md](collections-dejava-research.md) 的方案 C
> 进行（最近的提交 `2a330dc`、`005d63c`、`7177da9` 就是这条线），
> 目标正是让这些结构有主干源码。两条改动碰同一批文件，并行只会冲突。
>
> **本次已经拿到的一部分**：审查建议的「跟踪 blob 的 checksum」对种子已经做了
> （BOOT-02，`scripts/seed-checksums.txt` + 每次使用前校验）。续传的 class 本身
> 仍无独立 checksum，等去 Java 化定了最终形态再说——如果它们变回从源码构建，
> 这个需求就自动消失了，那才是正解。
>
> 关联：TEST-02（这些结构没有直接测试）同样待办，且同样应由那条线一并解决。
>
> **2026-08-03 补记 —— 另一件续传二进制 `dawn/tool/AdtClassWriter` 已关闭。**
> 它不是本条正文说的集合运行时，但落在同一句指控里（「续传的 class 本身仍无独立
> checksum」）。K-A0.5 先给它记了哈希（缓解），K-A4 让它的危险那一半不可达
> （**按用户裁决仍记缓解，不记关闭**——不可达是关于当天调用点的论断，不是文件的性质），
> K-A7 期 2+3 才真的拿掉：五个适配器改由 `rtclasses.dawn` 发射成 `dawn/rt/Asm`，
> `dawn/tool` 退出 `--vendor` 与 `vendor_trust`，`unzip -l` 里已经没有它
> （docs/jvm-base-plan.md §5.7）。**剩下的是**：第 N 代 jar 里的 `dawn/rt/Asm` 由第
> N−1 代发射——那是自举常态、DDC 处理得了，与「源码不存在」两回事；
> `org/objectweb/asm` 与 `coursierapi` 一个字节没动。


`selfhost/src/pkg/vendor.dawn:3` 明确 `DawnList/DawnMap/DawnSet` 的源码只在
`kotlin-final` tag，当前编译器从自身 classpath 读取 class，再复制进每个用户程序。

问题包括：

- 当前 checkout 无法独立审查或重编这些关键数据结构。
- `docs/pure-ffi-design.md:403` 提到的并发 CAS 测试不在主干测试中。
- 固定点会忠实复制同一二进制，因此 B==C 不能发现其中的恶意或历史 bug。
- 修复这些 class 需要回到历史 tag 和额外工具链，更新协议未自动化。

建议把 Java 源和直接测试恢复到主干，构建时从源码生成；若坚持 boot blob，也应跟踪 blob、
源码、checksum 和“源码→blob”复现脚本。

### ARCH-06（P1）`-Xss512m` 是架构债，不是“无害”

> **【待办 —— 认可】**
>
> 「用户程序不应继承编译器的 512MB stack 参数」是这条里最容易独立完成的一半：
> `spawn_java` 给用户程序传 `-Xss512m` 确实没有理由。但**不能只改这一半**——
> 用户程序里的深递归今天靠这个参数活着，摘掉它是一次静默的行为收窄
> （原本能跑的程序开始 `StackOverflowError`），而且恰好在 ERR-01 刚把
> `StackOverflowError` 从 `catch_panic` 里移出去之后。
>
> trampoline / 显式 evaluator stack 是根治，属 `interp.dawn` 的重写，需要设计文档。


`selfhost/src/ir/interp.dawn:12` 因 evaluator 使用宿主递归而要求 512MB 线程栈；
`bin/dawn:38`、`selfhost/src/main.dawn:493`、`spawn_java` 等处广泛强制该值。
它会显著增加虚拟地址保留和容器内存压力，还把编译器实现细节泄漏给用户程序。

建议 trampoline/显式 evaluator stack，或把 comptime 放进专用受限线程/进程；用户程序不应继承
编译器的 512MB stack 参数。

### CLI-01（P1）class 文件写入错误被静默吞掉

> **【已修】**
>
> `write_class` 改为 `Result[Unit, String]`，两处 `java_try` 的 `Err` 都带上
> **目标路径与真实异常**往上报；两个调用点（`write_temp_classes`、`run_emit`）
> 在第一次失败时停下并报错，不再继续写剩下的类。
>
> 原来的失败模式正是审查描述的那种：build「成功」但少了几个类，
> 然后在很远的地方以「用户从没写过的类找不到」浮现——或者根本不浮现，
> 直接发一个有洞的 jar 出去。


`selfhost/src/main.dawn:117` 的 `write_class` 对 `createDirectories` 和 `Files.write`
分别调用 `java_try`，随后完全忽略 `Err`。磁盘满、权限错误、路径非法时，build/run/test
可能继续执行并在更远处以“类缺失”失败，甚至产出不完整结果。

建议返回 `Result[Unit, String]` 并在第一次 I/O 失败时报告目标 class 和真实路径。

### ARCH-07（P2）测试与生产实现混在超大源文件

> **【驳回（拆文件）+ 已修一半（black-box corpus）】**
>
> **不拆内联 test**。审查自己也说「内联 test 对小模块很方便」；对大模块，
> 把测试移出去要跨过 `pub` 边界——checker/emit 的测试大量依赖私有函数，
> 移出去要么把实现细节 `pub` 出来（更糟的耦合），要么只能测公开表面（覆盖率下降）。
> 「实现和数千行测试 fixture 绑在同一编译单元」的代价是编译时间和文件长度，
> 那不值得用可测性去换。
>
> **black-box corpus 这一半已经做了**：审查点名的四项里，JSON 现在有
> `scripts/json-suite.sh`（283 个强制 fixture + 全部 `y_` 的往返性质，在 CI）。
> parser/spec corpus 与 LSP framing corpus 仍缺（TEST-04）。


内联 `test` 对小模块很方便，但 checker、parser、emit 等巨型文件把实现和数千行测试 fixture
绑在同一编译单元。建议保留小模块内联测试，同时给大模块增加 `test/` 项目和 black-box corpus，
尤其覆盖 parser/spec、JSON、LSP framing 和 binary runtime。

## 7. CLI、LSP 与工具接口

### CLI-02（P1）classpath 分隔符声称跨平台，实作硬编码 `:`

> **【已修】**
>
> `main.dawn` 新增 `path_sep()`（读 `File.pathSeparator`），替换全部 8 处硬编码 `:`：
> `extract_cp`、`DAWN_SELFHOST_CP` 环境变量的读与写、`run`/`test` 的 classpath 拼接、
> `PATH` 搜索 `native-image`、`build` 的 user classpath。`vendor.dawn` 拆
> `java.class.path` 那处同样改掉。
>
> Windows 上 `C:\lib\a.jar` 原本会在盘符处被切成两个不存在的条目。


- help 在 `selfhost/src/main.dawn:308` 写“platform path separator”。
- `extract_cp` 在 `selfhost/src/main.dawn:368` 按 `:` 分割。
- re-exec、环境变量、run/test classpath 和 `vendor.classpath_package`
  也都硬编码 `:`。

Windows 盘符会被拆坏。建议统一读取 `File.pathSeparator`，环境变量也用平台 separator。

### CLI-03（P2）`bin/dawn` 宣称考虑 macOS，却依赖非 POSIX `readlink -f`

> **【已修】**
>
> `bin/dawn` 改为逐跳解析符号链接（`readlink` 无参 + `cd`/`pwd -P`，处理相对目标），
> 不再用 BSD readlink 没有的 `-f`——失效的恰好是那段 `Contents/Home` 探测所服务的平台。
> `scripts/seedjar.sh` 的非 POSIX `local` 也去掉了，改用前缀命名的变量。


`bin/dawn` 是 `#!/bin/sh`，`bin/dawn:10` 使用 macOS 默认不存在的 `readlink -f`；
它 source 的 `scripts/seedjar.sh:11` 又使用非 POSIX `local`。建议要么明确 bash，
要么保持真正 POSIX 并实现可移植 symlink resolution。

### CLI-04（P2）仅用 mtime 判断编译器是否需要重建

> **【已修】**
>
> `bin/dawn` 不再用 `find -newer`，改为对构建输入（`selfhost/src`、`selfhost/dawn.toml`、
> `std/`、`scripts/seed-release.txt`）的**内容哈希**，存在 `build/dawn-selfhost.stamp`，
> 与当前哈希不一致才重建。stamp 在 jar 就位之后才写，所以中断的构建下次会重来。
>
> 审查列的每一种情况（checkout、解压、时钟偏移、产物复制）都会让旧 jar 看起来比新源码新，
> 而失败是隐形的：工具链能用，只是不是源码描述的那一个。
> 读 ~1.5MB 做哈希是几毫秒，对上一次多秒的构建。
> 没有 `sha256sum`/`shasum` 时回落到旧的 mtime 启发式，而不是拒绝运行。


`bin/dawn:46` 用 `find -newer`。checkout、解压、时钟偏移或产物复制会让旧 jar 看起来比新源码更新，
导致运行过期编译器。建议记录源树 hash、seed tag 和构建参数，而不是依赖时间戳。

### LSP-01（P1）手写 UTF-8 decoder 不校验合法性

> **【待办 —— 认可】**
>
> 建议是「直接使用标准 URI/UTF-8 API」，这是对的，而且与 LSP-02 是同一次改动
> （手写的 percent-decode + UTF-8 decode 整体换成 `java.net.URI` + `Paths`）。
> 不在本次做的原因是 LSP 的输出受 `scripts/selfhost-lsp-diff.sh` 逐字节守护，
> 换 decoder 会改变畸形输入下的行为（这正是目的），需要连着 corpus 一起更新，
> 是一次有测试设计的改动而非替换一个函数。
>
> 对照：`packages/web` 这次的同类问题（WEB-02）就是改用 JDK 的 `URLDecoder` 修的，
> 而不是再写一个 decoder——LSP 该走同一条路。


`selfhost/src/lsp/lsp.dawn:199` 的 decoder 不检查 continuation byte、overlong encoding、
surrogate 和最大码点；不完整序列还会静默跳字节。URI 解码结果可能与 JVM/编辑器不同，
甚至进入 `from_code_points` 的非法范围。

建议直接使用标准 URI/UTF-8 API，或实现严格 decoder 并返回错误。

### LSP-02（P1）file URI 实现不符合跨平台 URI 语义

> **【已修 —— 2026-07-30】** authority / query / fragment / Windows 盘符 / 空 authority
> 输出全部按 RFC 3986 处理，往返测试钉住（含重音与盘符）。**没有换成 `Paths`/`URI`**：
> 缝 1 之后 `lsp.dawn` 是共享前端，一份实现供两个工具链，native 侧没有 JDK——
> 与 LSP-01 同一个理由（台账 §3.7 的改判）。UNC 与远程主机判为「本进程打不开的文件」
> 回 None，而不是拼一个可能指向别处的路径。
>
> 原判定：**【待办 —— 认可，与 LSP-01 同一次改动】**——`Paths`/`URI` 确实已经能正确完成
> authority、Windows drive、UNC、normalization，不该手写。见 LSP-01 的排期理由。


`uri_to_path` 只去掉 `file://`，`path_to_uri` 只拼接该前缀。authority、Windows drive、
UNC、相对路径、`#`/`?` 和 URI normalization 都没有标准处理。`Paths`/`URI` 已能正确完成这些工作，
不应手写。

### LSP-03（P1）一个畸形 frame 会让服务器静默退出

> **【已修】**
>
> `read_message` 从 `Option[Json]` 改为 `Frame = Eof | Message(Json) | Malformed(code, why)`，
> 三种情况不再塌成同一个 `None`：
>
> - **缺 Content-Length** → `Malformed(-32600)`。header 块已读到 CRLFCRLF，
>   流正停在下一帧的开头，所以回一个 JSON-RPC 错误后**继续**。
> - **JSON 解析失败** → `Malformed(-32700)`。恰好消费了 `clen` 字节，同样已重新同步。
> - **body 短读** → `Eof`。声明的字节不会再来了，这是真的流结束。
>
> 原来的行为是：一个畸形帧（崩溃中的客户端写了半个 header、管道里混进一次杂写）
> 让服务器一声不吭地退出，编辑器只看到语言服务器停了。JSON-RPC 2.0 §4.2 要求回错误。


`selfhost/src/lsp/lsp.dawn:338` 的 `read_message` 在缺 Content-Length、body 短读或 JSON 错误时返回 None；
`run_lsp` 把 None 当 EOF，直接停止。JSON-RPC 要求 parse error/invalid request 响应，至少也应记录
错误并尝试恢复下一个 frame。

### LSP-04（P2）每次按键做全项目同步分析，无取消

> **【待办 —— 认可】**
>
> 「先做 debounce + generation cancellation，再逐步缓存 lex/parse/module graph」
> 这个分步是对的。不在本次做：debounce 与取消要改 LSP 主循环的结构
> （目前是单线程 read→handle→respond），引入并发就要重新论证
> 「旧诊断覆盖新状态」这个正是要防的竞态——需要设计文档而不是补丁。


`selfhost/src/lsp/lsp.dawn:5` 明确每次 change 重建完整分析；`textDocumentSync=1` 接收全文，
`update_doc` 调 `analyze_document(..., 100000000)`，主循环单线程且不处理取消。
配合“目录加载全部模块”，项目增长后会出现输入延迟和旧诊断覆盖新状态。

建议先做 debounce + generation cancellation，再逐步缓存 lex/parse/module graph。

## 8. 包管理、自举与发布

### PKG-01（P1）下载与解压缺少资源上限

> **【已修】**
>
> `pkgfetch.dawn` 现在有五道闸：
>
> - HTTP **connect timeout 30s** 与 **request timeout 300s**（此前一个都没有，
>   一个不应答的主机能把编译器挂到天荒地老）；
> - 下载体积上限 **256MB**；
> - zip：**条目数上限 65536**、**单条目上限 64MB**、**展开总量上限 256MB**——
>   在展开过程中累计判断，而不是展开完再看；
> - tar.gz：`GZIPInputStream` 改用 `readNBytes(上限+1)` 而不是 `readAllBytes`，
>   gzip bomb 的要点就是展开后大小无界，多读一个字节就足以判定超限。
>
> 「流式下载到临时文件」没做：那要改 `BodyHandlers` 与全部下游（校验、解压、
> 移进 cache）的接口，而 256MB 的内存上限已经把危害限住了。剩下的是纯粹的
> 内存效率问题，不是安全问题。


- `selfhost/src/pkg/pkgfetch.dawn:170` 通过 `BodyHandlers.ofByteArray` 整体下载到内存。
- HTTP client 未设置 connect/request timeout。
- zip 每个 entry 使用 `readAllBytes`（`pkgfetch.dawn:260`）。
- tar.gz 先把整个解压结果 `readAllBytes` 到内存（`pkgfetch.dawn:337`）。
- 没有 compressed size、expanded size、entry count、单文件大小或压缩比限制。

一个 zip/tar bomb 或慢连接能耗尽编译器内存/时间。建议流式下载到临时文件，设置网络超时、
总量/单项/条目/压缩比限制，并在移动进 cache 前验证。

### PKG-02（P1）cache 命中后不再验证内容

> **【已修 —— 2026-07-30】** 源码包那半也治了：`ensure_cached` 命中即重算 d1 与
> 目录名比对（内容寻址让目录名本身就是声明，无需 marker 文件），配套
> `dawn cache verify` 全量扫描。实测 7MB 树 ~0.9s；篡改单文件被当场检出。
>
> **【更正 —— 2026-08-07】「命中即重算」在构建路径上没生效**：`analyze.url_pkg_root`
> 热命中直接 `return`，压根不进 `ensure_cached`（那行 fast path 比本条修复还老，
> 修复时没回头看它）。于是 `ensure_cached` 的重算只在「条目在、`subdir` 不在」这个
> 角落触发。今天挡住篡改的实际只有 `dawn cache verify` 这条手动全量扫描。
> 把重算铺到每次热构建是另一笔账（每次构建按包体积计价），未做；url/hash 守卫
> 因此挂在解析器一侧而不是只挂在 `ensure_cached` 里。
>
> 原判定：**【待办（源码包）—— 认可；种子那半已修】**
>
> 同一个病在两处：种子 jar 与源码包 cache。**种子那处已经治了**（BOOT-02）——
> 现在每次命中缓存都校验，不只是下载后校验。
>
> 源码包 cache 没做，因为它需要先决定「验证什么」：源码包有 d1 canonical tree hash
> （`dawn __pkghash`），marker 文件里存它是自然做法，但要定 marker 的格式、
> 版本、以及 hash 不匹配时是报错还是重抓——加上审查建议的
> 「只写临时目录 + 原子 rename + 只读权限」与新的 `dawn cache verify` 子命令。
> 这是一个小特性，该有自己的设计文档。


`selfhost/src/pkg/pkgfetch.dawn:482` 明确“fetch 时验证一次，之后信任本地副本”；
目录存在就直接返回。用户、磁盘损坏或并发半成品都能改变 cache 内容而不被发现。
建议至少验证一个带版本的 marker/hash，或使用只写临时目录+原子 rename+只读权限，并提供
`dawn cache verify`。

### PKG-03（P2）自制 TOML 子集却使用 `.toml` 名称

> **【驳回】**
>
> 「使用成熟 TOML parser」在这里是行不通的：`selfhost/` 只能用**当前种子已支持的
> 语言特性**（CLAUDE.md 的机器强制约束），依赖一个第三方 TOML 库意味着给编译器
> 自身加一个 Maven 依赖——而 `dawn.toml` 恰恰是解析 Maven 依赖之前就要读的文件。
> 这是个鸡生蛋。
>
> 「使用不同扩展名」也不选：`dawn.toml` 这个名字已经在 dawnop-site、
> 全部示例、文档和用户项目里，改名的破坏面远大于收益，而收益只是命名洁癖。
>
> **接受的那一半**（「在文件头和错误中明确不是通用 TOML」）是对的，
> `selfhost/src/pkg/toml.dawn` 的文件头已经写明它是子集并列出拒绝的构造。
> 用户碰到的是一条明确的错误信息，不是静默的误解析。


`selfhost/src/pkg/toml.dawn` 807 行，另有 661 行 manifest validator；它明确拒绝标准 TOML 的
literal string、float、inline table、quoted key、dotted key 等。用户会自然使用 TOML 工具和语法，
却得到 Dawn 专用子集。

建议使用成熟 TOML parser；若坚持子集，应使用不同扩展/格式名，并在文件头和错误中明确
“不是通用 TOML”。

### PKG-04（P2）无 lockfile 的可复现论证过强

> **【已修 —— 2026-07-30】** `dawn.lock` 落地：记录整个解析闭包的字节（basename +
> sha256）与直依赖坐标；`dawn run/test/build` 在有 lock 时校验、不符即停；
> `dawn lock` 写、`dawn lock --check` 进 CI。五个反例中 1–4 关闭，第 5（上游删除）
> 明确不解决且写进注释。与设计的偏离（不记 per-artifact coord/url、改「解析后校验」
> 而非「按 lock 装」）与理由记在 package-integrity-design 顶部。

> **【待办 —— 认可】**
>
> 五条反例都成立（传递 POM 的版本区间、mirror 返回不同内容、无 artifact checksum、
> highest-wins 结果未固化、仓库删除）。「源码包的 d1 hash 做得更好」也对——
> 同一个仓库里两套依赖各有一套可复现性论证，弱的那套却没标明自己更弱。
>
> lockfile 是一个特性（格式、生成时机、`--locked` 模式、更新流程），要设计文档。
> 本次至少让 `docs/package-design.md` 不再是死链（DOC-06）。


`docs/package-design.md:244` 假设精确直依赖 + Maven Central release 不可变即可复现，但：

- 传递 POM 可以含版本区间或动态 metadata；
- mirror 可返回不同内容；
- 没有 artifact checksum/完整解析图；
- highest-wins 结果没有固化；
- 仓库或依赖删除也会破坏重建。

源码包的 d1 hash 做得更好；Maven 依赖也应生成包含坐标、解析版本、URL/checksum 的 lock。

### BOOT-02（P0）种子下载没有 checksum 或签名

> **【已修】**
>
> 新增 `scripts/seed-checksums.txt`（每行 `<sha256>  <tag>`，跟踪进仓库），
> `scripts/seedjar.sh` 在**每次使用前**校验——不只是下载后，因为 cache 是磁盘上
> 一个可写目录。下载的临时文件在**升格为缓存之前**校验，坏下载不会变成此后被信任的副本。
> 不匹配即 `exit 1`，消息里写明「这是编译其它一切的编译器，拒绝使用」。
> `DAWN_SEED=<本地 jar>` 逃生阀保留，但现在会打印 `(unverified)`。
>
> 已验证：往缓存的 seed.jar 尾部追加几个字节 → `bin/dawn` 退出码 1 并拒绝构建。
>
> release workflow 现在同时发布 `dawn-selfhost.jar.sha256`，并在日志里打出可直接
> 粘进 `seed-checksums.txt` 的那一行。
>
> **这份清单的信任边界要说清楚**（文件头也写了）：值是 2026-07-25 从 GitHub Release
> 重新下载、并与本机 `.dawn/seeds/` 缓存逐一比对一致得到的。它把「以后拿到的种子」
> 钉到「当时 GitHub 上的种子」——是 trust-on-first-use，**不是来源证明**。
> 它挡住此后的篡改、损坏与资产替换；挡不住「当初上传的 jar 是否对应声称的源码」。
> 那需要签名 + 可复现构建，属 BOOT-03。签名没做：需要密钥管理与信任分发的决策，
> 不是脚本改动。


`scripts/seedjar.sh:17` 直接从 GitHub Release 下载并永久缓存 `seed.jar`，没有 checksum、
签名或每次校验。首次下载/CDN/release 资产被替换会改变整个工具链信任根。

建议在仓库跟踪每个 seed 的 SHA-256（最好再有签名），使用前总是校验；release workflow
发布 jar 同时发布 checksum/provenance。

### BOOT-03（P1）固定点证明被表述成了供应链证明

> **【已修（措辞与门禁分离）+ 待办（DDC）】**
>
> 四条「不能证明」全部成立。已做的：
>
> - **artifact integrity** 现在是独立门禁（BOOT-02 的 checksum），不再混在 B==C 里；
> - **reproducibility** 从「同机可复现」提升到「跨时区可复现」（BOOT-04）；
> - `docs/bootstrap.md` 不再把迁移期的阶段快照当现状，明确写出现行 oracle 是什么。
>
> 没做的是 **diverse double compilation** 与 **source correspondence**：
> DDC 要求用一个独立实现（比如 `kotlin-final` 的 Kotlin 编译器）重编一遍并比对，
> 那是一条真正的工作线（要恢复 Kotlin 侧的构建环境、处理两侧已经分叉的语言特性），
> 不是一次审查修复。`docs/m8-selfhost-only.md` 对 trusting-trust 的乐观措辞保留原样——
> 它是历史记录，而 `docs/README.md` 已把该文标为 historical。


B==C 只能证明“这个编译器编译自己达到固定点”。它不能证明：

- seed 与声明的历史源码对应；
- compiler 没有 trusting-trust payload；
- 从 classpath 原样复制的 runtime/ASM/coursier 可信；
- 下载工件未被替换。

`docs/m8-selfhost-only.md:227` 对 trusting-trust 的处置过于乐观。应把
**reproducibility、diverse double compilation、artifact integrity、source correspondence**
分成不同门禁。

### BOOT-04（P2）跨时区并非字节可复现

> **【已修】**
>
> `jarw.dawn` 从 `ZipEntry.setTime(epoch millis)` 改为
> **`setTimeLocal(LocalDateTime.of(2020,1,1,0,0,0))`**（Java 9+）：
> 直接写 DOS 时间字段，路径上没有时区。
>
> 已验证：`TZ=UTC` 与 `TZ=Asia/Tokyo` 分别构建同一个 jar，`cmp` 字节相同。
> `docs/bootstrap.md` 的对应段落改写。
>
> 审查说得对——release 以字节固定点为核心，「只有在我的时区才同字节」撑不起这个说法。
> **这改变了 jar 的字节**（非 UTC 机器上），提交需带 `Emit-Change:` 行。
> 「在至少两个时区/平台重建比较」没进 CI：那要多一个 runner job，
> 而现在时区已经不在代码路径上了，收益小于成本。


`docs/bootstrap.md:112` 承认 ZipEntry 时间经过本地时区，跨时区 jar 不保证相同。
既然 release 以字节固定点为核心，应把时间戳固定为与时区无关的 epoch，并在至少两个时区/平台
重建比较。

### REL-01（P1）release workflow 没有重跑完整 CI

> **【已修】**
>
> 按审查的建议做了——**复用同一个 workflow，而不是维护一份缩小版**：
> 门禁移进新的 `.github/workflows/gates.yml`（`on: workflow_call`），
> `ci.yml` 与 `release.yml` 都 `uses:` 它，`release` job 加 `needs: gates`。
>
> 于是 tag 上现在跑的是**同一张清单**，包括原先漏掉的全部六项：
> `packages/web`、`playground`、Playground contract、site 端到端 build、formatting、
> N vs N-1 差分（run/fmt/lsp 三份转写），加上 identity guard 与本次新增的
> JSONTestSuite 门禁。`release.yml` 里那段手抄的 `test selfhost && test site` 删掉了。
>
> 一处保留在 `ci.yml`：`Co-Authored-By` trailer 检查需要一个提交区间，
> 在 tag 上没有对应语义。tree-only 的 identity guard 则进了 gates。


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

> **【已修 —— 2026-07-30】** 声明改为 `Emit-Change(<label glob>): <说明>`，label 即
> 差分脚本打印的检查名（`emit selfhost`、`run calc (args)`、`fmt`、`lsp`），四个差分
> 脚本经 `scripts/emitchange.sh` 按 scope 匹配后才放行；裸声明保持通配语义以兼容历史。
> 时机正是台账 §3.8 说的那个：第二个后端（native fixpoint）当天出现。
> 「golden 快照进仓库」那半仍如下文所记，先记着。
>
> **【通配这一半的补修 —— 2026-08-04，#124】** 上面留的两个口子都是「任意匹配即放行」：
> glob 与裸声明。实际后果测到过——`1b8ee7f` 带 `Emit-Change(emit *)`，那之后整个种子
> 窗口里 `selfhost-prev-diff.sh` 六项 emit **全打 NOTE、一项 OK 都没有**，脚本照样
> 打印 "undeclared-diff check passed"；而那正是一次大改后端的窗口。
>
> 现在的规则：scope 必须是**一个** label，逐字出现在 `scripts/emit-labels.txt`；
> 不接受 glob、不接受裸 `Emit-Change:`、解析不了或 label 不认识一律报错。
> 三个数据决定了取舍：
>
> - **通配的成本可测**：REL-02 之后共 60 条声明，29 条用了 glob，其中 4 条
>   （`lsp*` ×2、`lsp *`、`doc --builtins*`）指向的本来就只有**一个** label，`*` 纯属噪声；
>   1 条 `core *` 指向**零个** label——没有任何差分脚本打 `core ...`，它从落地那天起
>   就是一条永远匹配不上的规则，而旧解析器一声不吭地收下了。
> - **禁掉通配的成本也可测**：`7de5bd64` 改 class-file 版本、六个 emit 语料全动，
>   就是老老实实写了六行。代价是六行提交信息（`docs/jvm-base-plan.md` K-A4 已记）。
> - **裸声明比 glob 更糟**：它最常见的历史写法是 `Emit-Change: none (docs only)`，
>   作者的意思是「什么都没变」，旧解析器的行为却是放行所有差分的所有 label。
>
> 推翻掉的两条候选，理由记在 `scripts/emitchange.sh` 头部：给通配配「预期变更集」
> （label 粒度上就等于逐条列举；文件粒度上写不出来——改 class-file 版本动的是语料里
> 每一个类，而 `fmt`/`lsp`/`run ...` 根本没有文件集），以及让通配「只对声明它的那个
> commit 生效」（不成立——差分比的是上个 release 与 HEAD，被批准的差异在 HEAD 依然
> 在，这样写会从下一个 commit 起一路红）。
>
> 「label 必须已知」这条的张力（加 label / 改名会不会误红）用**双向校验**解掉：
> `emit_gate` 对**每一次**检查都跑，label 不在注册表里就红并打印该补的那一行，所以
> 注册表不可能落后于脚本，"unknown label" 永远意味着声明写错了。
>
> 解析器自己也有门禁：`scripts/emitchange-selftest.sh`，27 条 accept/refuse/gate 用例，
> 不需要 JVM、不需要种子。门禁的绿只有在能变红时才有信息量，这个解析器的失效方式
> 恰好是静默的（读不懂 → 永不匹配；太宽 → 全都匹配），所以它必须被喂进应当失败的输入。
>
> 原判定：**【待办 —— 认可】**
>
> 「一行 `Emit-Change:` 放行所有 target 的任意差异」确实过宽，而且本次处置正好
> 是它的压力测试：ERR-01 与 BOOT-04 两处刻意的字节变更，声明里没有任何机制
> 说明「只有 catchPanic 的异常表和 jar 条目时间戳该变」。
>
> 建议的两条路里，「把 golden 更新作为可审查文件提交」是更彻底的那条
> （审查者直接看字节差异，而不是看一句自述），但它要求把 emit 语料的快照进仓库，
> 是对差分体系的结构性改动。先记着。


`scripts/selfhost-prev-diff.sh:38` 只要 tag 之后任一 commit 含一行 `Emit-Change:`，
所有 target 的任意差异都会被放行。声明没有绑定文件、阶段、预期 digest 或 corpus。
建议让变更声明列出目标和批准的 snapshot hash，或把 golden 更新作为可审查文件提交。

## 9. JSON 包

### JSON-01（P0）大整数静默丢精度

> **【已修】**
>
> `scan_number` 不再返回 `Float`，而是返回**字面量文本**；`parser.number_of` 拿到文本后
> 决定：无 `.`/`e`/`E` 的走 `parse_int`（精确），否则走 `parse_float`。
> 超出 Int 范围的整数字面量返回 `Err`，不返回一个圆整过的答案。
>
> RFC 8259 §6 明确允许实现对 number 的范围与精度设限，JSONTestSuite 把每个这类用例
> 都归在 `i_`（实现自定）——没有任何 `y_` 需要超过 64 位的整数。**拒绝好过答错。**
>
> 审查漏掉的一档，顺带记下：`99999999999999999999`（超 2^63）此前**饱和成
> `Long.MAX_VALUE`** 才输出，比 2^53 那档更糟。
>
> 「数据模型应保存 decimal lexeme/BigDecimal」没做，理由写在 `value.dawn` 的文件头里：
> 那会让每个消费 `Json` 的 match 分支都多一个非原始的数字构造器，
> 换来的是没有任何强制用例要求的输入。
>
> 回归测试：`parse("9007199254740993") == Ok(JInt(9007199254740993))`、
> 两端的 Int 边界、以及超范围返回 `Err`。


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

> **【已修】**
>
> 两层都做了，正如建议：
>
> - **parser 拒绝非有限结果**——`number_of` 用 `is_finite`（`f - f == 0.0`，
>   对 NaN 与 ±Inf 都为 false，依据 spec §4.3 的 IEEE 比较语义），
>   `1e400` 现在是 `Err("number out of Float range: 1e400 at offset 0")`。
> - **renderer 二次防御**——`render_num` 对非有限值输出 `null`。
>   parser 已经不会造出这种值，但 `render` 是全函数、它唯一的职责就是输出合法 JSON，
>   不能依赖「造它的一定是 parser」。手写 `JNum(1.0 / 0.0)` 仍然存在。
>   `null` 是 JavaScript `JSON.stringify` 出于同样理由做的替换。
>
> 注意 `1e-400` 仍然接受（下溢到 `0.0` 是可表示的），只有溢出被拒。


实测 `1e400` 解析后渲染为 `Infinity`。`packages/json/src/render.dawn:39` 直接
`to_string(Float)`，没有拒绝 NaN/Infinity。RFC 8259 不允许这些 token。

建议 parser 拒绝非有限结果，renderer 也二次防御，不允许构造 `JNum(NaN/Infinity)` 后输出。

### JSON-03（P1）renderer 没有转义全部控制字符

> **【已修】**
>
> `escape_cps` 补上 `\b`(8) 与 `\f`(12) 的短形式，其余 U+0000–001F 输出 `\u00XX`。
>
> 这个 bug 有个尖锐的地方值得记：**这个包的 lexer 自己会把 `\b` 解码成 0x08**，
> 于是 parse→render 之后输出的是裸字节，已经不是能被同一个 parser 读回的 JSON。
> 而 JSONTestSuite 的接受/拒绝判定永远抓不到它——判定只看「收不收」。
> 所以新的 harness 对每个 `y_` 都加跑 **parse→render→parse 并比对值相等**
> （JSON-07），这条性质正是为这类 bug 加的。


`packages/json/src/render.dawn:5` 只处理 quote、backslash、LF、TAB、CR，遗漏
U+0000–001F 中的其他字符。实测解析 `"\\b\\f"` 再渲染得到原始 `0x08 0x0c`，
输出不再是合法 JSON。

建议实现 `\b`、`\f`，其余控制字符输出 `\u00XX`，并加入 round-trip/property test。

### JSON-04（P1）重复 key 静默 last-wins，错误没有位置

> **【错误位置已修；重复 key 驳回】**
>
> **位置已修**：`lexer.err_at` 给每条错误加上码点 offset，parser 与 lexer 的全部
> 十余处 `Err` 都改用它。offset 从不透明的 `Cursor` 反推
> （`str.len(cursor.slice(src, start, i))`，O(n)，只在失败路径付一次——一次解析至多一个错误）。
> 现在是 `Err("unexpected character at offset 6")`，并且计的是**字符**，
> 不是 UTF-16 单元或字节（测试里有 emoji 的用例）。
>
> **重复 key 不改成拒绝**：JSONTestSuite 的 `y_object_duplicated_key.json` 与
> `y_object_duplicated_key_and_value.json` 是**必须接受**的用例。RFC 8259 §4 说 name
> SHOULD unique、重复时行为未定义，last-wins 是绝大多数实现的选择。
> 默认拒绝会让这个包过不了它自己的强制验收。
>
> 「至少可配置」是合理的，但那要引入 parser 选项这个新概念（`parse` 之外再来一个
> `parse_with(opts)`），是 API 扩展而非修 bug——留待有真实需求时再做。


object parser 在 `packages/json/src/parser.dawn:76` 直接 `map.insert`，重复 key 无提示。
所有错误只是 `String`，没有 offset/line/column/path。对配置、签名和 API 验证来说，
重复 key 往往应拒绝或至少可配置；错误应携带位置。

### JSON-05（P2）非法 surrogate 被替换而不是明确策略

> **【驳回】**
>
> 「strict parser 默认报错」这条不采纳：涉及的 11 个 fixture 全部是 `i_`
> （实现自定），接受与拒绝都合规，所以这不是正确性问题而是口味问题。
>
> 更关键的是：**Dawn 的 `String` 是码点序列，根本存不下孤立 surrogate**。
> 所以可选项只有「替换成 U+FFFD」或「报错」，没有「保真」。
> 在两个都合规的选项之间做破坏性切换，需要的理由比「调用者不知道数据被改了」更强。
>
> 而「调用者不知道」这半句，代价已经因为 JSON-07 而降低了：
> 那 22 个被拒 / 13 个被接受的 `i_` 数字现在**每次 CI 都打印**，
> 任何一次策略变化都会以数字变化的形式出现在 diff 里，而不是无人察觉。


`packages/json/src/lexer.dawn:101` 到 `packages/json/src/lexer.dawn:125` 将 lone/错误 surrogate
替换为 U+FFFD。该选择可以存在，但当前 API 没有 strict/lossy 区分，调用者也不知道数据已改变。
建议 strict parser 默认报错，另提供显式 lossy 模式。

### JSON-06（P1）包与 M4 示例重复，测试正典已分叉

> **【已修】**
>
> 按建议的第一条做：**让示例依赖正式 package**。
> `examples/m4/json/src/json/` 四个文件删除，新增 `examples/m4/json/dawn.toml`
> 声明 `[deps] json = "../../../packages/json"`。因为依赖名就叫 `json`，
> `main.dawn` 的 `use json/parser` 一个字都不用改。
>
> 分叉的具体样子值得记下来：package 版后来加了 `JInt` 与精确整数解析，示例版没有，
> 而 README 把示例称作 JSONTestSuite 验收物——也就是说**验收的是生产不用的那一份**。
> `value.dawn` 里那句「parser never produces it」也已经过期（package 版的 parser 会产出
> `JInt`），一并改了。


`examples/m4/json` 与 `packages/json` 复制了 lexer/parser/render/value。lexer 当前相同，
package 版后来加入 JInt，但注释仍写“parser never produces it”，示例版仍全 Float。

README 把 M4 示例称为 JSONTestSuite 验收物，生产代码却用另一个分叉。应让示例依赖正式 package，
或把 suite/harness 移到 package 测试中，消除双正典。

### JSON-07（P1）318 个 fixture 没有现行自动 harness

> **【已修】**
>
> 新增 `examples/m4/json/src/suite.dawn`（harness 本身用 Dawn 写，
> 单进程读整个 fixture 目录——318 次 JVM 启动是几分钟，那正是一个检查最终没人跑的原因）
> 与 `scripts/json-suite.sh`，接进 CI 的 gates。
>
> 结果：**283 个强制 `y_`/`n_` 全过**，另 35 个 `i_` 13 接受 / 22 拒绝。
> 每个 `y_` 还额外跑 parse→render→parse 往返（见 JSON-03）。
>
> 过程中发现一件审查和 README 都没说清的事：**25 个 fixture 是刻意的非法 UTF-8**
> （孤立 continuation byte、overlong、无 BOM 的 UTF-16、ISO-8859-1）。
> Dawn 的 parser 收 `String`，所以它们根本到不了 parser——`io.read_file` 严格解码先失败。
> 那是**解码边界上的拒绝**，不是 harness 缺陷，而且与 `main` 对这些文件的判定
> （`Err(_) -> "invalid"`）一致。它们全是 `n_` 或 `i_`；没有任何 `y_` 是非法 UTF-8，
> 这正是「先解码再解析」能忠实表达这套 suite 的原因。harness 的注释里写了这一段。


仓库跟踪了 JSONTestSuite 文件，但当前 `dawn test examples/m4/json` 只跑 3 个 test，
CI 也没有逐文件执行 fixture 的脚本。README 的“全部 318 例”是历史结论，不是当前持续门禁。
本次手工跑的 283 个强制 y/n 用例通过，但这应成为仓库脚本和 CI。

## 10. Web 包与 Playground

### WEB-01（P1）body limit 检查发生得太晚，且单位错误

> **【已修】**
>
> 三个问题分两层解决：
>
> - **读之前就设上限**。`read_body` 现在收一个 `limit`：先看 `Content-Length`
>   （客户端的声明，只用来快速拒绝），再用 `readNBytes(limit + 1)` ——
>   多读一个字节足以判定超限，也是单个请求能分配到的最大值。
>   新增 `serve_app_bounded(port, max_body, ...)`；`serve_app` 委托它并带上
>   `DEFAULT_MAX_BODY = 8 MiB`，所以现有调用点一个字不用改。
>   `raw-body` 标签（nginx 兜底的上传路由）与 `stream-body`（本来就落盘）照旧豁免。
> - **单位改对**。`with_body_limit` 改用 `bytes.len(req.raw)`，不再用
>   `str.len(req.body)`（码点数）——消息一直写着 bytes 而检查数的是字符，
>   CJK 或 emoji 的 body 能拿到三到四倍的预算。Playground 里同样的写法一并修了。
>
> 中间件保留，但注释里说清了它现在是什么：**应用级策略**，不是内存防线——
> 中间件运行时 body 已经在内存里了。防线是服务器那道。
>
> 一个代价记在这里：超限的 413 在 `build_request` 阶段返回，此时还没有 `Request`，
> 所以中间件不运行——这个 413 没有 access-log 行、没有 CORS 头。
> 那是「拒绝发生得足够早以至于有意义」的价格。
>
> 「文本 decode 应按需，不要每个请求都保留两份」没做：那要改 `Request` 的形状
> （`body: String` 变成惰性），是破坏性 API 变更。8 MiB 的上限已经把峰值限住了。


`packages/web/src/server.dawn:40` 先 `readAllBytes` 并同时保存 Bytes 与 UTF-8 String；
`packages/web/src/middleware.dawn:37` 才用 `str.len(req.body)` 检查 limit。

因此：

- limit 无法防止大请求先耗尽内存；
- 同一 body 同时保留 byte[] 和 String，峰值更高；
- `str.len` 是码点数，错误消息却写 bytes，多字节 UTF-8 会低估。

建议在读 body 前检查 Content-Length，并以限长流累计真实字节；超限立即停止。文本 decode 应按需，
不要每个请求都保留两份。

### WEB-02（P1）query/form 解码不符合 URL 规范

> **【已修】**
>
> 完全按建议做：`build_request` 改用 **`getRawQuery()`**，`parse_query` 在
> `&`/`=` 切分**之后**才对 key 和 value 分别 percent-decode，
> `parse_form` 直接复用同一条路径（此前只把 `+` 换成空格，percent 转义原样交给 handler）。
>
> 解码顺序不是细节而是安全边界：先解码再切分意味着 `a=1%262` 变成 `a=1&2` 再切成
> **两个参数**——客户端能伪造参数边界。这是参数走私，不是解码瑕疵。
>
> 解码用 JDK 的 `URLDecoder`，不自己写（对照 LSP-01：仓库里已经有一个手写 UTF-8
> decoder 要还债，再写第二个不是解法）。`URLDecoder` 对残缺转义（`%A`）会抛，
> 用 `java_try` 兜住并保留原文——一个畸形 query 不值得让请求失败。
>
> 副作用：`parse_query`/`parse_form` 因此带上了 `!io`。这是记账不是真效果
> （解码字符串是纯的，但唯一能结构化捕获 JDK 异常的 `java_try` 本身是 `!io`），
> 注释里写明了。


- `server.dawn:110` 使用已经解码的 `URI.getQuery()` 再按 `&` 切分，编码后的 `%26`
  可能先变成分隔符。
- `parse_form` 只把 `+` 替换为空格，完全不做 percent decode。
- key 没有相同处理。

建议使用 raw query 后按分隔符切分，再分别 percent decode key/value；form 使用标准
`application/x-www-form-urlencoded` 解码。

### WEB-03（P1）路由使用解码后的 path，encoded slash 语义不明确

> **【待办 —— 认可】**
>
> query 那半（WEB-02）修了，path 这半没修，因为它不是同一种改动：
> 换成 raw path 会改变**每一条路由的匹配行为**（`router.dawn` 的段切分、
> 捕获段的内容、`{*tail}` 尾捕获），并波及 dawnop-site 的 WebDAV 路径处理——
> 那正是审查点名会受影响的地方。
>
> 而且「明确每段 decode」之后还要定义审查列的另外三条策略（重复 slash、dot segment、
> trailing slash），那是一份路由语义的规格，不是一个补丁。
> `packages/web` 是对外包，这种改动该走版本与设计文档。


`build_request` 和 dispatch 使用 `URI.getPath()`。若 `%2F` 被解码为 `/`，客户端数据会改变
路由段边界，影响授权和 WebDAV 路径。应使用 raw path、明确每段 decode，并定义重复 slash、
dot segment 和 trailing slash 策略。

### WEB-04（P2）请求 header 被压成单值

> **【待办 —— 认可】**
>
> `Map[String, List[String]]` + `header_first` 便利函数是对的形状，
> 但 `Request.headers` 的类型是公开 API，改它会让每个读 header 的调用点编不过。
> 破坏性变更，走版本流程。


`packages/web/src/server.dawn:92` 明确只取每个 header 的第一个值。
`Cookie`、`Forwarded`、`Accept`、重复自定义 header 等语义会丢失。建议
`Map[String, List[String]]`，另提供 `header_first` 便利函数。

### WEB-05（P1）CORS 对不允许的 origin 仍发第一个 origin，且缺 `Vary`

> **【已修】**
>
> `pick_origin` 返回 `Option[String]`：不在白名单时返回 `None`，
> **不再回退到第一个配置项**，也就完全不发 `Access-Control-Allow-Origin`。
> `Vary: Origin` 在所有分支都发，包括拒绝分支——「不发 CORS 头」本身就是一个
> 依赖 Origin 的回答。
>
> 审查对危害的判断是准的：浏览器确实会拦，但**共享缓存不会**——
> 它看到某个 URL 被回以 `Allow-Origin: https://a.example`，就可以把这份存储的响应
> 交给来自 `https://b.example` 的请求，而那个请求会通过检查。
>
> 「preflight 校验请求 method/header」没做：那要读
> `Access-Control-Request-Method`/`-Headers` 并与配置比对，等于给 `with_cors`
> 加配置项（当前只有一个 origins 字符串）——是特性扩展，不是修 bug。


`packages/web/src/middleware.dawn:67` 在 origin 不匹配时回退到第一个配置项，然后总是发送
`Access-Control-Allow-Origin`；响应也没有 `Vary: Origin`。浏览器可能拦截，但共享缓存可能把
针对一个 origin 的响应复用给另一个。

建议不匹配时不发 CORS header；动态 echo 时添加 `Vary: Origin`；preflight 校验请求 method/header。

### WEB-06（P2）Response 用三个字段表达一个 sum，非法状态可构造

> **【待办 —— 认可】**
>
> `ResponseBody = Text | Binary | Stream | Empty` 是对的形状，
> 而且顺带能解掉 WEB-07（长度与是否允许 body 由 body 的种类决定）。
> 但 `Response` 是这个包最核心的公开类型，改它等于改每一个 handler 的构造点，
> 且 dawnop-site 全部生产代码都在用。破坏性变更，走版本流程。


`packages/web/src/types.dawn:47` 同时有 `body: String`、`bin: Option[Bytes]`、
`stream: Option[InputStream]`，并靠注释规定 stream 忽略其余字段。任意调用者都能构造冲突状态。

建议 `ResponseBody = Text(String) | Binary(Bytes) | Stream(InputStream) | Empty`。

### WEB-07（P2）全部响应 chunked，缺 HEAD/无体语义

> **【待办 —— 认可，且应与 WEB-06 一起做】**
>
> 「由 ResponseBody 决定长度和是否允许 body」正是 WEB-06 的 ADT 能给的东西。
> 分开做要写两遍。


`packages/web/src/server.dawn:53` 总是 `sendResponseHeaders(status, 0)`。小响应无法给
Content-Length，204/304/HEAD 也会进入 body 路径。建议由 ResponseBody 决定长度和是否允许 body，
并实现 HEAD。

### WEB-08（P1）header 构造器缺少注入与编码防护

> **【已修】**
>
> `types.dawn` 新增两个过滤器，并放在 **`with_header`** 上——框架发出的每个 header
> 都经过它，所以防线在一处而不是每个调用点：
>
> - `header_value`：去掉 CR、LF、其余 C0 控制符与 DEL（保留 SP 与 HTAB，
>   两者都是合法 field-content）。**采取过滤而非拒绝**：对本来就合法的值这是恒等变换，
>   对其余的值也不存在能把它们传输出去的编码。
> - `header_name`：只保留 RFC 9110 §5.1 的 token 字符——否则一个 header 名可以自带 `:`
>   注入一个字段。
>
> `attachment` 改为按 **RFC 6266 §4.1 + RFC 5987** 发两个参数：
> `filename=`（quoted-string，转义 `"` 与 `\`，非 ASCII 丢弃）与
> `filename*=UTF-8''<pct-encoded>`（当代客户端真正读的那个）。
> percent 编码手写而非用 `URLEncoder`——后者是 form-urlencoded，
> 空格写成 `+` 且不编码 `*`，两者都不是 attr-char。
>
> `redirect` 的 Location 自动经 `with_header` 过滤，不需要单独处理。
>
> 回归测试三条：CRLF 注入 payload、filename 里的引号与分号、非 ASCII filename。


`packages/web/src/types.dawn:142` 直接把 filename 插入 `Content-Disposition`，没有引号、
反斜杠、CR/LF 和非 ASCII 处理；redirect 的 Location 也完全接受原字符串。
建议统一 header value 校验，并按 RFC 5987 生成 `filename*`。

### WEB-09（P2）路由和错误接口 stringly typed

> **【已修一半 —— 2026-07-30】** 启动校验落地：`router.validate_routes`
> （pattern 语法 / 重复 capture / 尾捕获须在最后 / shadow 检测，含 tail-覆盖语义），
> `serve_app` 起服务前跑、失败 panic 并点名两条路由。method/status 受限类型那半
> 仍按 web-api-v2-design §四驳回。playground contract 全绿证明现有表通过校验。
>
> 原判定：**【待办 —— 认可】**
>
> 其中「启动时校验 RouteTable」（pattern 语法、重复 capture 名、route shadow 检测）
> 是**唯一不破坏 API** 的那部分——可以在 `serve_app` 里加一次启动期检查，
> 把「宽 route 静默遮住后续 route」变成启动即报错。这条值得单独做。
>
> method/status 换成受限类型、`HttpError` 换成 ADT，与 WEB-06 一样是破坏性变更。


- HTTP method、route pattern、tag 都是任意 String。
- 无启动时 pattern 校验、重复 capture 检查或 route shadow 检测。
- first-match wins，宽 route 可静默遮住后续 route。
- `HttpError` 只有 status/message，没有 code、headers 或结构化 details。

建议构造 server 时编译并校验 RouteTable，method/status 使用受限类型，错误使用 ADT。

### WEB-10（P2）server 生命周期 API 不可组合

> **【待办 —— 认可】**
>
> `start(config) -> ServerHandle` + `join`/`stop` 是对的。
> 本次只往这个方向挪了半步：新增 `serve_app_bounded`（多一个 body 上限参数），
> 没有引入 config record——因为一旦引入就该一次做全（地址、executor、readiness、
> 优雅停止），而那是 API 重设计。现在多加一个参数比先立一个残缺的 config 好。


`packages/web/src/server.dawn:255` 固定绑定 `127.0.0.1`、创建 executor、启动后永久 latch await，
不返回 server handle，不能优雅停止、选择地址、注入 executor、测试生命周期或做 readiness。
建议 `start(config) -> ServerHandle`，由 `join/stop` 分开控制。

### PLAY-01（P1）安全配置不是 fail-closed

> **【已修】**
>
> 完全按建议：`sandbox_enabled()` 从 `PLAY_SANDBOX == "1"`（默认关）改为
> **`PLAY_UNSAFE_LOCAL != "1"`（默认开）**。现在漏配、直接启动、复制部署
> 得到的都是「有沙箱」，而不是「在宿主上编译并运行陌生人的代码」。
>
> 连带改动：`playground/test/contract.sh` 显式设 `PLAY_UNSAFE_LOCAL=1`
> （CI 和开发机上没有 systemd-run wrapper，这个 harness 正是那个该说出口的调用方），
> systemd unit 里的 `Environment=PLAY_SANDBOX=1` 删掉（已无变量可开），
> `SANDBOX.md` 改写。contract 10/10 通过。


`playground/src/play/config.dawn:25` 默认 `PLAY_SANDBOX=0`。生产 unit 确实显式开启，但任何漏配、
直接启动或复制部署都会在宿主上编译和运行不可信代码。既然服务的本质是执行陌生代码，
默认应拒绝启动，只有显式 `PLAY_UNSAFE_LOCAL=1` 才允许无 sandbox。

### PLAY-02（P1）编译阶段本身没有 runner 级 timeout

> **【已修】**
>
> `compile_phase` 从裸 `waitFor()` 改为 `waitFor(compile_timeout_secs(), SECONDS)`，
> 超时 `destroyForcibly()` 并返回结构化的 `Err("compilation timed out after Ns")`。
> 新增 `PLAY_COMPILE_TIMEOUT`（默认 30s），与运行阶段的预算分开——
> 冷启动的编译器本来就比它产出的程序慢。
>
> 审查指出的因果链正是关键：comptime 在**编译器进程内**执行用户代码，
> `unsafe_pure` 的 Java 调用可以在那里阻塞任意久（LANG-01 与
> `pure-ffi-design.md` §302：反射一旦进入无法打断）。此前只有生产的
> `RuntimeMaxSec=15` 兜底，且只对开了沙箱的部署有效；本地模式下一个请求
> 能永久占住一个编译器进程，而且它手里还攥着一个 gate 许可。


`playground/src/play/exec.dawn:87` 对编译器直接 `waitFor()`；运行阶段才用
`waitFor(timeout)`。生产 systemd wrapper 的 `RuntimeMaxSec=15` 是后备，但关闭 sandbox 的本地模式
没有编译 timeout。comptime/Java reflection 又可能在单个调用中长期阻塞。

建议编译和运行都使用显式 timeout，并把 timeout 作为结构化 Outcome。

### PLAY-03（P3）sandbox 文档仍提“known panic leak”

> **【已修】**——`SANDBOX.md` 的那段改成当前保证：`play/gate.with_gate` 取代了
> 旧的 `run_guarded`，在 panic 路径上也释放许可，并有对应回归测试
> （"with_gate releases the permit even when body panics"）。


`playground/sandbox/SANDBOX.md:89` 引用旧 `run_guarded` 的已知 permit leak，但
`playground/src/play/gate.dawn` 已有 `with_gate` 和回归测试。应删掉过期警告或改成当前保证。

## 11. 规范、方案和项目文档

### DOC-01（P1）权威规范版本和内部引用失真

> **【已修】**
>
> `docs/spec.md` 现在带状态头：**normative**、适用版本 0.11.0（跟 `VERSION` 走，
> 不再单独编号）、并写明「实现与本文冲突时以本文为准」。审查这句是对的——
> 一份自称草案的文档没法充当裁判，而这是唯一有资格裁判语义争议的文档。
>
> 六处失真逐条修：`?` 指向 §8.1（原 §9）、block 指向 §4.2（原 §5.2）、
> comptime 指向 §7（原 §8）、`catch_panic` 指向 §8.2（原 §9.8）、
> `@trusted_pure` 改回 `unsafe_pure` 并注明旧名已废、
> §12 的「Dawn 无依赖解析、只接受零传递依赖 jar」改写为「`--cp` 不做解析，
> 需要依赖树走 `[java-deps]`」并指向 §10.1（原文与 §10.1 直接冲突）。
>
> 另外两处趁便改准了：§1.3 的标识符规则（见 SYN-01）、§2.6 的 alias 单位安全
> 警示（见 LANG-05）。


- `docs/spec.md:1` 仍是“v0.1 草案”，当前工具为 0.11。
- `docs/spec.md:249` 把 block 指向 §5.2，实际 §5.2 是穷尽性。
- `docs/spec.md:274` 把 comptime 指向 §8，实际是 §7。
- `docs/spec.md:142`、operator 表等仍把 `?` 指向旧 §9，当前错误处理是 §8。
- `docs/spec.md:1139` 说 Dawn 无依赖解析、只接受零传递依赖 jar；
  `docs/spec.md:956` 却已经说明 Maven/传递依赖解析。
- `docs/spec.md:1104` 仍出现已经废弃的 `@trusted_pure` 名称。

权威规范必须先于普通设计文档修复，否则所有实现争议都没有可靠裁判。

### DOC-02（P1）README 已无法描述当前项目

> **【已修】**——五条全改：
>
> - **「没有 trait」**改为明说 trait/impl/derive/Ord 全部实现，那句是 M1 之前的话；
> - **「没有异常」**改写为「是语法不是运行时保证」，点名 `cast` 与 `use java` 会穿透，
>   并指向 `java_try`/`catch_panic`（这同时是 LANG-03 的处置）；
> - **状态从 M4 推到 M0–M8**，M5–M8 给出简述与各自的设计文档链接；
> - **145 项改 163 项**；
> - **示例最后一行** `"total: {t}"` 改为 `"total: $t"`——当前插值语法要求 `$t`/`${t}`，
>   原样跑出来是字面的 `{t}`。首页第一个代码示例是错的，这条不算小。
>
> JSONTestSuite 那句也改准了：不再说「全部 318 例」，改为「283 个强制用例全过，
> 另 35 个 `i_` 13 接受 / 22 拒绝」，并写明由 `scripts/json-suite.sh` 在 CI 每次执行。


- `README.md:39` 写“没有 trait”，实际 trait 已完整实现。
- `README.md:71` 状态只列到 M4，仓库已经经历 M8 和 selfhost-only。
- `README.md:103` 写 selfhost 145 项，本次实际 158 项。
- README 示例最后一行使用 `"total: {t}"`，而当前插值语法要求 `$t`/`${t}`，
  示例输出不会插值。
- JSONTestSuite 318 例没有现行 CI harness，见 JSON-07。

### DOC-03（P1）教程安装命令已经不可执行

> **【已修】**
>
> `docs/tutorial.md` §1 的 `./gradlew :compiler:fatJar` 换成实际流程：
> `./bin/dawn --version` 自动拉种子（按 `seed-checksums.txt` 校验）并重建工具链，
> 并明说没有 Gradle、Kotlin 实现在 `kotlin-final` tag。
>
> 文首那句「所有代码块由 `TutorialTest` 机械保证」也改了——**不去假装它还成立**：
> 现在写明那套测试已随 Kotlin 实现归档、当前 CI 没有等价门禁、
> 这些代码块是人工维护的、可能落后于语言。恢复门禁列在 TEST-04。
>
> 一句诚实的「没有测试守着」比一句已经不成立的保证有用。


`docs/tutorial.md:16` 仍让用户运行已从 main 删除的
`./gradlew :compiler:fatJar`，同时声称所有代码块由已归档的 `TutorialTest` 机械保证。
当前 CI 没有对应教程抽取/执行门禁。应改为 seed/selfhost 安装流程，并恢复文档测试。

### DOC-04（P2）设计文档把历史决策写成当前事实

> **【已修（design.md）+ 部分待办（全仓 ADR 状态）】**
>
> `docs/design.md` 加了状态头：标 **historical**，并点名三条已被推翻的前提——
> 「编译器预算 6–8 千行（Kotlin）」/「实现语言 = Kotlin」（M8 已淘汰）、
> 「unsafe 逃生门不向用户代码开放」（与现状相反，见 LANG-01）、
> 「不引入 IR」（前提已不成立，见 ARCH-04），各自给出去处。
>
> 「每条 ADR 有 proposed/accepted/superseded 状态和替代链接」没做到条目粒度：
> 那是把 `design.md` 整篇重构成 ADR 格式，属独立工作。目前是**整篇标状态 +
> 点名最危险的三条**，先让读者不至于把过期段落当现状。


`docs/design.md:8` 的 6–8 千行 Kotlin 预算、`docs/design.md:79` 的“实现语言=Kotlin”、
`docs/design.md:69` 的“unsafe escape 不向用户开放”、M7 段的“Kotlin 日常工具链”等都已经过期。

设计记录可以保留历史，但每条 ADR 应有 `proposed/accepted/superseded` 状态和替代链接，不能让
读者猜哪些段落仍有效。

### DOC-05（P2）bootstrap 文档同一页混合多个阶段快照

> **【已修】**
>
> 按建议做：M8 阶段二/三/四的逐阶段快照从 `bootstrap.md` 移走，
> 换成一段明确的说明——那些描述（哪些能力还在 Kotlin 侧、`DAWN_KOTLIN=1` 逃生阀、
> `bin/dawn-kotlin` 作金样 oracle）**都已不是现状**，过程记录见 `history/m8-selfhost-only.md`。
> 正文只留现行链，并把现行 oracle（`selfhost-prev-diff.sh` 及三份转写对拍）写清楚。


`docs/bootstrap.md:3` 开头说 selfhost-only 已完成，`docs/bootstrap.md:37` 又说 LSP 仍在 Kotlin，
`docs/bootstrap.md:39` 还写已经移除的 `DAWN_KOTLIN` 和 `bin/dawn-kotlin`。
应把阶段三历史移入 M8 进展记录，bootstrap 只保留现行链。

### DOC-06（P2）大量死链接指向已归档 `compiler/`

> **【已修】**——7 处 `../compiler/...` 相对链接改为
> `https://github.com/dawnop/dawn-lang/blob/kotlin-final/compiler/...`
> （`package-design.md` 4 处、`selfhost-gaps.md` 3 处），指向固定 tag 而非 main。


`docs/package-design.md`、`docs/selfhost-gaps.md`、`docs/pure-ffi-design.md` 等仍使用
`../compiler/...` 相对链接，在 main 上全部失效。历史引用应链接到固定 tag/commit 的 GitHub URL，
或明确标“历史路径（见 kotlin-final）”。

### DOC-07（P2）关键实现注释仍描述 Kotlin/UTF-16 旧模型

> **【已修】**
>
> 审查说得对——**这类注释是架构契约，错了比普通注释危险**，因为每个消费 span 的地方
> 都依赖它。逐个改：
>
> - **span 单位**：`ast.dawn`、`tast.dawn`、`diag.dawn`、`token.dawn`（两处）、
>   `checker.dawn`、`doc.dawn`、`lexer.dawn` 全部从「UTF-16 offsets」改为
>   **码点索引**，并在 `ast.dawn` 写明 UTF-16 只在 LSP 边界重建、
>   以及为什么错误的陈述比没有陈述更糟。
> - **oracle**：`parser.dawn`、`dump.dawn`、`astdump.dawn`、`add.dawn`、`emit.dawn`、
>   `codegen.dawn`、`main.dawn` 的「mirror Kotlin byte for byte」改为
>   「对**上一 release** 字节稳定（`selfhost-prev-diff.sh`）」，Kotlin 原件注明在
>   `kotlin-final` tag。`parser_test.dawn` 里指向已删除的
>   `scripts/selfhost-parse-diff.sh` 也改了。
> - 顺带：`toml.dawn` 的文件头重写（见 PKG-03）、`selfhost/dawn.toml` 的
>   `compiler/build.gradle.kts` lock-step 注释重写（见 DOC-09）。


- `selfhost/src/front/ast.dawn:3`、`selfhost/src/check/tast.dawn:8`、`selfhost/src/front/diag.dawn:4`、
  `selfhost/src/front/token.dawn:87`、`checker.dawn:124` 仍说前端 span 是 UTF-16。
- `selfhost/src/front/lexer.dawn:249` 和测试已经明确当前 span 是 code-point index，UTF-16 只在 LSP
  边界重建。
- 大量文件头仍以“mirror Kotlin byte for byte”描述职责，即使当前 oracle 已是 N vs N-1。

这类注释是架构契约，错误比普通注释更危险，应集中修正。

### DOC-08（P2）trait 文档与实现冲突

> **【已修】**——`docs/trait.md` 的「Float 的 cmp 与 NaN」一条标为**已被实现取代**：
> 实际是 `Double.compare`（全序，NaN 大于一切、`-0.0` 在 `0.0` 之前），与 spec §4.3 一致。
> 并写清为什么改：`DCMPL` 给不出全序（NaN 参与的比较全为 -1，排序会不自洽），
> 当初落地时改掉了，文档漏了回填。


`docs/trait.md:228` 说 Float Ord 用 `DCMPL`，NaN 偏负；当前
`selfhost/src/jvm/emit.dawn:1727` 调用 `Double.compare`，是 total order。spec 也按 total order
描述。应标记 trait.md 的落地记录已被后续实现替代。

### DOC-09（P3）selfhost manifest 注释引用不存在的 Gradle 文件

> **【已修】**——`selfhost/dawn.toml` 的注释改为：ASM 版本由本清单**单独**声明，
> 旧注释指向的 `compiler/build.gradle.kts` 已随 Kotlin 实现离开 main（在 `kotlin-final`），
> 不存在需要 lock-step 的第二处。


`selfhost/dawn.toml:4` 说 ASM 版本必须与 `compiler/build.gradle.kts` lock-step，
该文件已不在 main。当前 ASM 版本应由 selfhost manifest、seed vendor policy 和更新脚本共同定义。

### DOC-10（P2）文档体系缺少入口、状态和“当前事实”层

> **【已修一半】**
>
> **做了**：新增 `docs/README.md`——分类索引 + 三档状态
> （**normative** 只有 spec.md / **current** 可照做 / **historical** 读作历史），
> 按「权威规范 / 当前架构与流程 / 设计方案 / 调研 / 历史」分层，
> 并在文末列出没做的部分。`CLAUDE.md` 的「14 篇、4000+ 行」同步改为
> 「30 篇、9000+ 行」并指向索引。
>
> **(2) 已做（2026-07-30）**：50 篇文档全部有状态标记，且**进 CI**
> （`scripts/doc-check.py` 的 status 检查）。形式不是 YAML front matter 而是本仓已有的
> `> 状态：…`——前者会被站点的 Markdown 渲染器当正文印出来，而这三篇（spec/design/
> tutorial）正是要渲染的。补的 21 篇逐篇判定：设计草案落地了的写 historical 并指向
> 现状（spec 条款或实现文件），仍在推进的写 current，被驳回的写驳回。
>
> **(3) 也已做（同日）**：四篇里程碑日志（m6 / m6-retro / m7-progress / m8-selfhost-only）
> 移进 `docs/history/`，16 个文件的入链与被移文件自己的出链一并改写——**改写的正确性由
> 刚建成的链接门禁验证**（它是这次移动敢做的前提；站点自己的 fixture 也顺带覆盖了
> 「子目录里的文档」这条分支）。docs/ 顶层现在只剩规范、现行流程与设计/调研。


28 篇文档按时间叠加，计划、调研、落地日志、规范、复盘和当前运维说明混在一起。建议增加：

- `docs/README.md`：分类索引；
- 每篇 front matter：状态、适用版本、是否 normative、superseded-by；
- 只有 `spec`、现行 architecture、package schema、bootstrap/runbook 作为 current docs；
- 里程碑和提交哈希记录移到 `docs/history/`。

## 12. 测试与质量门禁的盲区

### TEST-01（P1）差分测试会把旧 bug 固化成正确行为

> **【再追修 —— 2026-08-04，#129】** 上一条追修写的「强制链接直接堵根源」堵住的
> 只有一半：**链接不等于解析**。`Class.forName(initialize=true)` 逼 JVM 把每个类的
> 方法体过一遍字节码 verifier，但符号引用（Methodref/Fieldref/Class）是**执行到那条
> 指令时**才解析并做访问检查的，所以「A 类的方法体引用 B 类的私有成员」这一整类错误
> 它一个都看不见。这不是假想：K-A3 闭包下沉把提升出来的 lambda 体发成 `ACC_PRIVATE`，
> invokedynamic 时代无所谓（`LambdaMetafactory` 拿到的是 private-access 的 `Lookup`），
> 一旦变成独立类，第一次真跑就死在 `std.io.read_file`——编译器读不了自己的第一个文件；
> 而门禁那时打印的是 `1946 classes, 0 illegal`。**是真编译了一次东西才发现的。**
>
> 本次实测了三条候选路线，只有第三条成立：
>
> - **`-Xverify` 家族**：JDK 21 上 `all` / `none`（已 deprecated 但仍接受）/ `remote`
>   对私有引用变异体**全绿**——校验和解析是两个阶段，加什么 flag 都不会变；
> - **`jdeps`**：历史上的隐藏选项 `-verify:access` 在 JDK 21 已删（`unknown option`），
>   `jdeps -v` 只报出 `pkgB -> pkgA` 这条边、退出码 0，不判可达性；
> - **常量池逐条解析 + JVM 自己的访问检查**（采用）：`AccessCheck.java` 手写常量池
>   读取器（同 `constpool-scan.py` 的理由：用发射器自己的库去查发射器自己的输出，
>   库错在哪就瞎在哪），取出每条 Fieldref/Methodref/InterfaceMethodref/Class，
>   按 JVMS 5.4.3.2/5.4.3.3 沿父类与接口找到成员，再用
>   `MethodHandles.privateLookupIn(引用方, lookup())` 的 `unreflect` / `accessClass`
>   做判定——**不是重写 JVMS 5.4.4，而是让 JVM 自己答**（nest mate、protected 子类、
>   runtime package 这些规则手写必错）。
>
> 代价：8 个语料 1948 个类、43229 条引用，整条门禁 12.3s → 14.3s（+2.1s，17%；
> 其中 pass 2 本身 +0.6s，两个变异体 +1.6s）。
>
> 「实际编译一个真语料」那条路线（K-A3 就是这么冒出来的）没有采用为**主**手段：
> 解析是惰性的，跑一遍只覆盖跑到的调用点，而 8 个语料里只有 selfhost 会被当编译器
> 真跑，其余七个发射完从不执行——覆盖面说不清楚，就不算「已声明的性质」。
>
> **绿本身不是证据**：门禁现在自带变异体（`selftest.sh`，run.sh 发射任何东西之前先跑，
> 1.3s）。四个 fixture 各钉一条主张：合法版必须绿**且引用计数非零**（否则「什么都没找到」
> 和「什么都没看」输出一样）；私有成员变异体必须红，**并且第一趟必须仍然绿**——把盲区
> 本身钉成断言而不是一段回忆；包级类变异体走 CONSTANT_Class 路径；把一条可达指令换成
> `athrow`（`mutate.py`）必须被 verifier 红——这就是旧 header 要求「改了门禁就重跑红演示」
> 的那个演示，现在由 run.sh 每次自动重跑。
>
> fixture 只证明检查器本身能红，**不证明它在真语料上非空**——这正是上次那个 bug
> （parent-first 委派）的形状：它是**语料相关**的，`pkgA`/`pkgB` 这种玩具包名 jar 里
> 没有，无论委派顺序怎么变都只能从被测目录里找到，所以 fixture 全红也照样漏。
> 于是**第二个变异体也进了 run.sh**（`privatise.py`，跑在 8 个语料之后）：把已经发射
> 在盘上的 selfhost 语料里 `dawn/rt/Strings.join` 的 `ACC_PUBLIC` 翻成 `ACC_PRIVATE`
> ——**这个类 jar 里也有一份**，所以它同时验「访问检查会红」和「child-first 还活着、
> 读的确实是被测目录」。门禁要求它必须红，不红就判整条门禁的绿无信息量并退出 1。
> 两个变异体回答两个不同的问题：selftest 问「能不能红」，语料变异体问「看没看」；
> 这道门禁两个问题上各空过一次，所以都不能省。复用已在盘上的语料，代价 +0.3s。
>
> 一次性实测（现已固化成上面那条）：新门禁在被改坏的语料上报 40+ 条 `ACCESS FAIL`、
> 退出 1；同一份被改坏的语料，b66f1d7 那版门禁照样打印
> `1048 classes verified, 0 illegal`、退出 0。未改动的同一语料是负控：
> `27162 references resolved, 0 unknown, 0 inaccessible`。
>
> 仍然没覆盖的（header 里也照实写了——「只说自己强在哪」的覆盖声明正是这道门禁反复栽的跟头）：
> 一切与**指令**有关的判定，因为常量池条目本身不记录是哪条指令引用了它，于是
> IncompatibleClassChangeError 那一族（对实例方法用 invokestatic、对静态字段用 putfield）
> 和 protected 访问的接收者类型子句都在范围外；freight 剪枝剪多了导致的 `NoSuchMethodError`
> （归 `scripts/table-freight`，本门禁把 `dawn/rt/*` 的缺失成员单列为 `freight-pruned`
> 计数而不报错，因为 `reach.dawn` 明确写了「pruned method is absent, not stubbed」
> 并有意依赖惰性解析）；以及合法字节算出错答案。发射出来的类在这里**从不执行**。
>
> **【追修 —— 2026-07-30】** classfile 那项也做了：`scripts/classfile-verify/run.sh`
> 把 8 个语料发射出的全部类（~1386 个）逐个强制链接过 **JVM 自带 verifier**，进 CI
> （gates.yml「classfile verification」）。用 JVM verifier 而非 CheckClassAdapter：
> vendored ASM 只带 core+signature（asm-util 是另一个 artifact），AdtClassWriter 源
> 已随 kotlin-final 归档不宜再动——而 verifier 本尊就在每个 JVM 里，惰性链接才是
> 「没人碰的类从不被校验」这个洞的根源，强制链接直接堵根源。
>
> **【已修一项 —— 这是本次最重要的一条方法论批评】**
>
> 「它们验证的是**一致**，不是**正确**」——JSON 精度、renderer 控制字符、body limit
> 三个 bug 全都能在全绿下长期存在，事实也确实如此。
>
> **做了的外部 oracle**：JSON。`scripts/json-suite.sh` 在 CI 跑 JSONTestSuite
> 的 283 个强制用例，外加对每个 `y_` 的 parse→render→property 往返
> （正是这条性质能抓 JSON-03，而接受/拒绝判定抓不到）。
>
> 审查列的其余四项都认可，都是待办：parser 对照规范语法 corpus（TEST-04）、
> URI/query/header 对照 JDK、classfile 过 ASM `CheckClassAdapter`/JVM verifier、
> package archive 的 fuzz/bomb corpus（PKG-01 加了上限，但没有对应 corpus）。
>
> `CheckClassAdapter` 那条其实最便宜——emit 时多包一层，能在发射阶段就抓住
> 非法字节码而不是等 JVM 拒绝。值得优先做。


N vs N-1、byte-for-byte Kotlin mirror 和固定点非常适合防无意变化，但它们验证的是“一致”，不是“正确”。
此次 JSON 精度、renderer 控制字符、body limit 等问题都能在全绿情况下长期存在。

建议为核心协议增加外部 oracle/property test：

- parser 对照规范语法 corpus；
- JSON 对照 RFC/property/其他实现；
- URI/query/header 对照 JDK 或标准测试；
- classfile 用 ASM CheckClassAdapter/JVM verifier；
- package archive 用 fuzz/bomb/timeout corpus。

### TEST-02（P1）关键二进制运行时没有当前直接测试

> **【待办 —— 认可，与 BOOT-01 同一件事】**
>
> 「不能只靠用户程序间接覆盖」是对的，尤其 DawnList 的共享窗口与 CAS 所有权
> 属于并发正确性，间接覆盖基本抓不到。
>
> 与 BOOT-01 同因同解：等去 Java 化那条线把这些结构变回有主干源码，
> 直接测试才有地方可写。先写测试再搬源码等于写两遍。


DawnList 的共享窗口、CAS 所有权、DawnMap/Set 的持久性、equals/hash/order 都是语言语义的一部分，
但当前发布链只从编译器工件取得 class，主干没有对应源码和直接测试。必须恢复并在每次 CI
直接测试，不能只靠用户程序间接覆盖。

### TEST-03（P2）release 与 push CI 覆盖不一致

> **【已修】**——见 REL-01。门禁定义现在**复用**（`gates.yml` + `workflow_call`），
> 不再是两份手抄清单。审查那句「否则两份列表必然漂移」已经应验过一次，这次是从
> 机制上堵掉。


见 REL-01。门禁定义应该复用，不应复制命令列表；否则两份列表必然漂移。

### TEST-04（P2）文档与 EBNF 没有可执行一致性检查

> **【已修大半 —— 2026-07-30】** `scripts/doc-check.py` 进 CI：50 篇文档的
> 相对链接与同文件锚点全检（零假阳性——Dawn 的类型语法与 Markdown 链接同形，
> 靠「剥代码 + 目标必须像路径」两道过滤），加上**标注为 ```dawn run / compile
> 的块真编真跑**（26 个，README 首页示例 + tutorial 全部整程序块）。
> 第一次运行就抓到 README 首页示例调用了不存在的 `sum`——即本条的论据本身。
> 块检查是**opt-in**：spec 里多数示例是片段，逼它们变成整模块会毁掉行文。
> **accept/reject grammar corpus 也已落地（同日）**：`scripts/grammar-corpus/`
> 进 CI，6 accept + 8 reject，后者每篇钉住拒绝理由（否则语料会退化成「只要报错就行」）。
> 仍未做：文档里手写数字的自动生成。
>
> 原判定：**【待办 —— 认可】**
>
> 五条建议全部成立，且本次处置的经历是它们的直接论据：
> README 首页示例的插值语法是错的（DOC-02）、tutorial 的安装命令不可执行（DOC-03）、
> EBNF 与 parser 多处不符（SYN-04）——**全部由人读出来，没有任何测试发现**。
>
> 只做了第五条的一部分：README/CLAUDE.md 里手写的测试数与文档篇数这次改准了，
> 但它们仍然是手写的。抽取 fenced block 分类执行、accept/reject grammar corpus、
> Markdown 锚点与相对链接检查都没做——那是一套文档 CI，值得单独一个提交。


README 示例、tutorial、grammar 和 spec 的错误都没有被测试发现。建议：

- 抽取所有 `dawn` fenced block 分类为 compile/run/illustrative；
- 运行 README/tutorial 的 compile/run block；
- 维护 parser accept/reject grammar corpus；
- 检查 Markdown 内部锚点和仓库相对链接；
- 对文档中的测试数、版本号尽量改成不手写，或由脚本生成。

## 13. 建议的整改顺序

> **处置注**：下面是审查原本给的顺序。第一、二阶段大部分已完成，逐条标注在后；
> 第三、四阶段基本未动。剩余项汇总在 §15。

### 第一阶段：安全与静默数据损坏

1. 限制 `unsafe_pure`，comptime Java 改 allowlist/隔离进程。—— **待办**（LANG-01；
   Playground 侧已 fail-closed + 编译 timeout）
2. 给 seed 和所有续传 binary 加源码、checksum、复现和直接测试。—— **seed 已修**
   （BOOT-02 + BOOT-04 跨时区可复现）；**续传 binary 待办**（BOOT-01，被去 Java 化改造覆盖）
3. 修 JSON integer/finite/control escaping，并把 318 fixture 纳入 CI。—— **已修**
   （JSON-01/02/03/07）
4. Web body limit 移到读取前，修 query/form/path decode。—— **body limit 与 query/form
   已修**（WEB-01/02）；**path decode 待办**（WEB-03，会改每条路由的匹配行为）
5. package fetch 增加 timeout 和解压资源上限。—— **已修**（PKG-01）
6. `write_class` 不得吞 I/O 错误；`catch_panic` 缩窄捕获范围。—— **已修**（CLI-01、ERR-01）

### 第二阶段：收敛对外契约

1. ResponseBody、JavaError、HttpError 改为 ADT。—— **待办**（WEB-06、ERR-02、WEB-09，
   都是破坏性 API 变更。其中 `JavaError` 已按后端中立改名 `ForeignError`——
   `class_name` 是 JVM-ism，见台账 §3.3）
2. LSP 改用标准 URI/UTF-8，并正确处理 JSON-RPC frame 错误。—— **frame 错误已修**
   （LSP-03）；**URI/UTF-8 待办**（LSP-01/02）
3. classpath/path launcher 做真正跨平台。—— **已修**（CLI-02、CLI-03、CLI-04）
4. Maven 解析增加 lock/checksum。—— **待办**（PKG-04）
5. Playground 改 fail-closed，并给 compile phase 独立 timeout。—— **已修**（PLAY-01/02）

### 第三阶段：重构编译器

1. 拆 checker 的环境和 pass。—— **已做**（ARCH-01，2026-08-03。
   [arch-split-design.md](arch-split-design.md) §10：`checker.dawn` 11,308 → 8,203 行，
   `cx.dawn` / `passes.dawn` 两个新模块，`Cx` 47 → 40 + `Frame`(8)）
2. 引入小型 lowered IR，统一所有 call/control-flow/FFI。—— **已让位**（ARCH-04
   → [native-backend-plan.md](native-backend-plan.md) 的 Phase 0。这条判断本身是对的
   ——它确实是 1、3、5 的共同前提——只是那条线的方案更全，见台账 §3.2）
3. 拆 emitter 的 method、closure、trait、constant 子系统。—— **已做，但形状不是这个**
   （ARCH-02，同 1）：`codegen.dawn` 3,425 → 706 行、`emit.dawn` 2,534 → 2,309 行，
   分出的是 `rtclasses.dawn` / `jvmhelp.dawn` 两个叶子模块与 `GenCtx`，
   **不是按 method/closure/trait/constant 四个子系统切**——那样切会让三个函数返回
   三元组而换不到任何签名收窄，理由见 [arch-split-design.md](arch-split-design.md) §2.4
4. 把普通 runtime 逻辑从手写 ASM 移到可测试源码。—— **已让位**（ARCH-05 前两条
   → Phase 2 集合纯 Dawn 化；建议三「opcode/descriptor 收进一个后端模块」仍待办）
5. 去掉 512MB host stack 依赖。—— **待办**（ARCH-06，**且只能去掉一半**：
   native 计划定了「一般尾调不做、大栈代替」，用户程序那半是决策不是债）

### 第四阶段：重建文档可信度

1. 先修 spec 和 EBNF，再修 README/tutorial。—— **spec/README/tutorial 已修**
   （DOC-01/02/03）；**EBNF 标 historical 而非逐条修**（SYN-04）
2. 建文档索引、状态和 superseded 机制。—— **已修**（`docs/README.md` 的索引 +
   每篇文件头的 `> 状态：…` 行，由 `scripts/doc-check.py` 强制；DOC-10 三件事全部落地）
3. 历史 Kotlin 链接固定到 `kotlin-final` tag。—— **已修**（DOC-06）
4. 给文档代码、链接、版本和语法 corpus 加 CI。—— **已修**（TEST-04）：
   `scripts/doc-check.py` 与 `scripts/grammar-corpus/run.sh` 都在 `gates.yml` 里

## 14. 最终判断

Dawn 当前最大的风险不是“功能少”，而是**项目对自己的承诺比实现边界更强**：

- pure 被描述成可用于优化的保证，但有用户可达的 unsound/comptime Java 入口；
- 语法有权威 spec 和 EBNF，但两者不能准确解析当前语言；
- 自举固定点被赋予了超过其证明能力的供应链含义；
- JSON/Web 被当作生产验收，却仍有静默数据损坏和资源限制位置错误；
- “小实现、无 IR、容易维护”的前提已被 3.5 万行 Dawn 和巨型模块改变。

因此下一步不宜继续堆特性。先把**可信边界、协议正确性、当前文档和架构分层**补齐，
才能让自举、dogfooding 和生产使用真正成为质量证据，而不只是“一致地复现当前行为”。

> **处置后的判断**
>
> 这五条里，**第二、三、四条已经不再成立或已大幅收窄**：
>
> - 规范与实现对齐了，EBNF 诚实地标着过期（而不是假装准确）；
> - 供应链有了独立于固定点的门禁（种子 checksum、跨时区可复现），
>   `bootstrap.md` 不再把 B==C 说成它证明不了的东西；
> - JSON 的静默损坏和 Web 的资源限制位置都修了，并且各自有回归测试与 CI 门禁。
>
> **第一条与第五条原样保留，且是本次刻意没碰的两块。** 它们的共同点是：
> 都不是「有个地方写错了」，而是「这个设计需要重新做一次决定」——
> `unsafe_pure` 的边界画在哪、要不要引入 lowered IR。按 CONTRIBUTING.md 的规矩，
> 这两件事该从一份 `docs/<特性>-design.md` 开始，而不是从一次修补开始。
>
> 另外，审查里最有长期价值的一句不在这五条里，而是 TEST-01：
> **差分测试验证的是「一致」，不是「正确」。** 本次修的 JSON 三个 bug 全都是在
> 全绿的差分体系下长期存在的，唯一能抓住它们的是外部 oracle（JSONTestSuite）
> 与性质测试（parse→render→parse 往返）。这次只给 JSON 补上了这一层；
> parser、URI/header、classfile 和 package archive 四处还没有。
> 如果只从本文挑一件事继续做，应该是这个，而不是任何一条架构重构。

## 15. 剩余项（按建议顺序）

> **28 条待办的方案已经写好**，在 [`docs/audit/`](audit/) 下的设计文档里
> （ARCH-01/02 那份例外，落在 [`docs/arch-split-design.md`](arch-split-design.md)），
> 索引与修复顺序见 [`docs/audit/README.md`](audit/README.md)。下表的「设计文档」
> 一列指向对应的那份。
>
> **动手前先读 [`docs/audit/native-plan-overlap.md`](audit/native-plan-overlap.md)。**
> [`docs/native-backend-plan.md`](native-backend-plan.md) 与本文的待办有九处撞车
> （其中五条已被那条线吸收，本文让位）。那份台账逐条记了谁冻结、谁要改写，
> 排期原则是**不重合的先做，重合的冻结**。

**需要先写设计文档**（CONTRIBUTING.md：动码前先写 `docs/<特性>-design.md`）

| 编号 | 题目 | 设计文档 | 排期 |
|---|---|---|---|
| LANG-01（P0）+ ARCH-06 | `unsafe_pure` 的边界、comptime allowlist、trampoline evaluator | [purity-boundary](audit/purity-boundary-design.md) | 步 1–2 做／**步 3 冻结**（等 R6） |
| ~~ARCH-01/02~~（+ARCH-03/04） | 小型 lowered IR，及靠它拆 checker/emitter | [arch-split-design.md](arch-split-design.md)（**取代** [lowered-ir](audit/lowered-ir-design.md) §3.2 的六组件方案，后者已降级为补充材料） | **ARCH-01/02 已落地**（#88，2026-08-03，十二刀，见该文 §10）。余下的账：**#126** 补 `enter/leave_isolated` 恢复路径的诊断语料 |
| ERR-02 / ERR-03 / LANG-02 | `ForeignError`、`bracket`、`cast` 返回 Result | [error-model](audit/error-model-design.md) | A、B **已落地**（v0.32.0–v0.35.0）／**C2 关档不做**（07-31，`bracket` 改走运行时 intrinsic，v0.39.0） |
| LANG-04 / LANG-05 | `Char` 不透明类型、`type X = new T` | [nominal-types](audit/nominal-types-design.md) | 步 1–3 做／**步 4 冻结**（并入 Phase 6） |
| LANG-06 / LANG-07 | `m.T`/`m.C`/`m.CONST`、`--closure` | [module-access](audit/module-access-design.md) | **做**（不重合） |
| LSP-01 / LSP-02 / LSP-04 | URI/UTF-8 交给 JDK、debounce + generation | [lsp-robustness](audit/lsp-robustness-design.md) | **做**（不重合） |
| PKG-02 / PKG-04 | cache 每次校验、`dawn.lock` | [package-integrity](audit/package-integrity-design.md) | **做**，PKG-02 优先 |

**已让位给 native 那条线**（[native-backend-plan.md](native-backend-plan.md)，
见台账 [§二](audit/native-plan-overlap.md)）

ARCH-03、ARCH-04 → Phase 0（Core IR）；BOOT-01（P0）、TEST-02、ARCH-05 前两条
→ Phase 2（集合纯 Dawn 化）。**不要并行动它们。**

**破坏性 API 变更，走版本流程**

WEB-03、WEB-04、WEB-06、WEB-07、WEB-09、WEB-10 —— 一次做完，`packages/web` 2.0，
方案见 [web-api-v2](audit/web-api-v2-design.md)。其中 WEB-09 的
「启动时校验 RouteTable」是唯一不破坏 API 的部分，可以脱离 2.0 单独发。

**可以立刻做，不需要设计文档**

| 编号 | 题目 | 为什么现在没做 |
|---|---|---|
| REL-02 | `Emit-Change` 绑定 target 与 digest | 对差分体系的结构性改动。**现已升为第一优先**——两后端平权之后，不标 target 就说不清改的是谁的输出（台账 §3.8） |
| TEST-01 | classfile 过 `CheckClassAdapter` | 最便宜的一条，emit 时多包一层。native 计划采纳了它的论证，没采纳这个动作项 |
| TEST-04 | 文档 CI（fenced block 执行、链接检查、grammar corpus） | **已做**：`scripts/doc-check.py`（七项检查）+ `scripts/grammar-corpus/run.sh`，都在 `gates.yml` |
| DOC-10 | 每篇 front matter、`docs/history/` | **已做**：`docs/history/` 已建；front matter 换成文件头的 `> 状态：…` 行 + 门禁，理由见 `docs/README.md` |
| ARCH-01/02 | 先把 opcode/descriptor 统一到一个后端模块 | **已做（2026-07-30）**：`selfhost/src/jvm/jvmops.dawn`，116 个常量一处，8 个曾有两份定义的 opcode 收成一份；发射字节逐字节不变。**拆 `Cx`/`Gen` 也已做（#88，2026-08-03）** |

**审查漏掉的一条**（登记在台账 §四）：`==` 硬连线 `BEq`、hash 是自动派生的结构
`hashCode`，于是「任意值能不能比较/哈希」不由 trait 决定。native 计划把它列为
**全线最高风险**（D0），而本文 76 条里没有任何一条提到它——审查检查了类型系统的
表面（`unsafe_pure`、alias、Char），没有检查**内建操作与 trait 系统的关系**。
