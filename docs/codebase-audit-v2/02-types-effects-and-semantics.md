# Dawn 代码库审查 v2：类型、效果与语言语义

> 状态：**current** —— 当前类型系统、效果系统、trait 与 nominal abstraction 的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- v0.60 的 **P0 候选** `SEM-01` 后来已动态确认并由 #188 修复；当前最高风险只保留
  `SEM-04` 的未验证 Cursor 静态候选，不重算冻结严重度。
- 多数 P2 不是“少一个高级特性”，而是现有核心抽象之间不能组合：associated type 没有 bound、trait 不能带具名效果、Unit 破坏泛型闭合、受约束函数不是函数值。
- 早期语言适合一次性收敛：effect row 只保留一套 substitution；public surface 做 effective visibility；`Never`、`Char`、Cursor 与 barrier 的类型都应表达真实语义。

## SEM-01 — P0 候选 — 逃逸 handler evidence 可能破坏 pure 保证

> **已修（#188，2026-08-08）。** 本条判断成立，且比本文所写更严重——动态复现确认了
> 两个**独立**缺陷：这里描述的 `eff_minus` 减错人（D2），以及标签轴对**函数值调用**
> 完全不设防（D1，本文未识别）。修法是「B 极简」三刀：写出来的函数类型禁具名标签、
> 闭包在创建点结算自己的行、`verify_effects` 核对整行；`eff_minus` 已删除。
> 逐条设计与实测收据见 [effects-soundness-design.md](../effects-soundness-design.md)。
> 本文下面的建议段猜中了修法的一半（「逃逸 closure 的类型必须消掉由捕获 evidence
> 处理的标签，并合入该 evidence 对应 arm 的实际效果」），另一半（禁写出来的标签）
> 是把它做安全所必需的。

- **证据：S；未动态验证。** 规范保证 pure 无可观察副作用：`docs/spec.md:948`；同时规定 closure 在创建点捕获 handler，逃逸后仍使用原 handler，但类型仍写 `!E`：`docs/spec.md:1096`。
- checker 把 evidence 当普通可捕获 local：`selfhost/src/check/checker.dawn:3841`、`selfhost/src/check/checker.dawn:7015`。handler arm 的效果只在安装节点计费：`selfhost/src/check/checker.dawn:3910`；remainder 则用 `eff_minus` 去掉 `E`：`selfhost/src/check/checker.dawn:3957`。
- **静态反例形状：** 函数 A 在 `with handle Leak` 中安装一个 `!io` arm，返回 `fn() -> Unit !Leak`；该 closure 捕获 A 的 evidence。纯函数 B 再安装一个纯 `Leak` handler并调用 closure。B 的类型检查会从 closure row 去掉 `Leak`，但运行时 closure 使用捕获的旧 evidence，执行 A 的 IO arm。
- **影响：** `pure` 可以实际产生 IO；纯性驱动的 comptime、缓存、消重和未来优化前提均不再 sound。
- **为什么只标候选：** 此项是此前要求“不验证最高风险点”的对象；本报告没有运行上述程序。源码与规范的数据流已经足以要求阻断发布前复核，但不能声称动态确认。
- **建议：** 最小安全方案是禁止 handler evidence 随闭包逃逸。若保留词法 handler，逃逸 closure 的类型必须消掉由捕获 evidence 处理的标签，并合入该 evidence 对应 arm 的实际效果；否则改成调用点 evidence/dynamic handler 语义。

## SEM-02 — P1 — effect union 在调用点没有实例化

- **证据：S。** 通用 `subst_eff` 正确递归 `EUnion`：`selfhost/src/check/types.dawn:630`；调用路径却使用另一份 `instantiate_eff`：`selfhost/src/check/checker.dawn:4852`，该函数只有 `EffVar`、`ELabeled` 与 fallback，没有 `EUnion`：`selfhost/src/check/checker.dawn:4888`。
- **边界：** `sequence(f: fn() -> Unit !e1, g: fn() -> Unit !e2) -> Unit !(e1 | e2)` 用两个 pure closure 调用时，参数变量已绑定 pure，返回 union 仍可能保留 callee-local effect vars。
- **影响：** 产生幽灵效果、错误拒绝 pure 调用，并干扰 label discharge；规范在 `docs/spec.md:970` 明确承诺 union 会在调用点规范化。
- **建议：** 删除第二套实现，调用点复用 `subst_eff`，再把仍未绑定的本次调用局部 effect var 统一默认成 pure并 normalize。

## SEM-03 — P1 — `to_string` 绕过 opaque String 的自定义 `Show`

- **证据：S。** opaque 自身 impl 应优先于 target type：`docs/spec.md:324`；lowering 却先 `peel_opaque(t) == TyString` 并原样返回：`selfhost/src/ir/lower.dawn:249`。正常 witness/`Show` 路径在 `selfhost/src/ir/lower.dawn:1789`，`to_string` 调用确实把 resolved witness 传入：`selfhost/src/ir/lower.dawn:2548`。
- **边界：** `opaque type Secret = String` 定义脱敏 `impl Show[Secret]` 后，`to_string(secret)` / interpolation 仍可输出底层明文。
- **影响：** nominal abstraction 被 representation shortcut 绕开；把 `Show` 用作日志脱敏时会泄漏值。
- **建议：** 静态类型精确为 `String` 才走 identity；opaque type 先使用其 witness。长期把“用户显示”与“结构 debug”拆成 `Display`/`Show`，避免 String 特例渗入 lowering。

## SEM-04 — P1 — Cursor 没有绑定所属 String，且表示跨后端不同

<!-- audit-anchor: present std/cursor.dawn | pub opaque type Cursor = Int -->

> **当前静态候选（未验证，不改严重度）：** comptime 把 Cursor 解释为 code-point index，
> JVM/native 分别发射 UTF-16 offset 与 UTF-8 byte offset。如果 comptime 折叠出的 opaque
> Cursor 值进入运行期操作，偏移可能跨执行模型失配。R-AUDIT 只完成静态追踪，未证明可达
> 程序；本项保持 open/P1，等待 owner/value 与 Eq/Ord 契约裁决，不先写 workaround。

- **证据：S。** `Cursor` 只是 opaque `Int`：`std/cursor.dawn:18`，所有操作重新接收任意 String：`std/cursor.dawn:22`、`:28`、`:31`、`:40`。源码甚至承认另一个 String 的 cursor 会“数到某个 end”：`std/cursor.dawn:126`。
- JVM offset 是 UTF-16 unit，native 是 UTF-8 byte，comptime interpreter 是 code-point index：`selfhost/src/jvm/rtclasses.dawn:2290`、`runtime/c/dawn_rt.c:1344`、`selfhost/src/ir/interp.dawn:850`。
- **边界：** 把 `cursor.end("😀")` 传给 `cursor.offset("abcd", c)`，三个执行模型可分别看见 2、4、1；把 `cursor.end("a")` 用于 `"😀"` 可落在 surrogate/continuation byte 中部。
- **影响：** 同一合法 Dawn 程序跨后端不同，`Char` 的 Unicode scalar invariant 也可被错误来源的 cursor 破坏。规范“只有 arithmetic 能制造非法位置”的表述：`docs/spec.md:1819` 不成立。
- **建议：** 破坏性改为 Cursor 自带 source identity/value，操作不再另收 String；或引入 generative `Cursor[S]`。至少在 runtime 验证 owner 与 code-point boundary，并禁止不同 owner 的 Eq/Ord。

> **勘察与部分落地（2026-08-16）：拆成两条腿，第二条已关，第一条仍等裁决。**
>
> 上面的「静态候选（未验证）」现在验证过了，而且验出来的不是一件事，是两件互相独立的：
>
> 1. **跨串误用**：把 A 串的 cursor 用在 B 串上。两个后端答案不同，因为它们数的单位不同。
>    **仍 open**，等货币裁决。
> 2. **comptime 折叠**：`const C: Cursor = cursor.next("😀abc", cursor.start("😀abc"))`
>    ——**全程只有一个字符串，没有任何误用**。JVM 得 56832（孤立低代理项），
>    native 得 1933345（超出 U+10FFFF，根本不是码点）。根因是折出来的常量烘进 **Core，
>    而 Core 是两个后端共读的**，所以解释器不可能跟着后端选货币，只能挑第三种。
>    **已关**：`cx.dawn` 的 `backend_dependent_repr` 让 `Cursor` 不再是常量可序列化类型，
>    诊断另给一条能照做的 hint（持有字符串、在用它的地方走过去）。规格
>    `spec.md §7.2` 同步写下这条例外与它的撤销条件；负控在 `checker.dawn` 的
>    「const-serializability」内联 test（同形状、只差 owner 的 `Cursor` 冒牌货必须仍可序列化）
>    与 `scripts/checker-corpus/cases/const_serial_cursor.dawn`。
>
> **顺带推翻两条：**
>
> - 上面「源码甚至承认另一个 String 的 cursor 会数到某个 end」引的那行文档已经删掉。
>   把错答案写成规格比 UB 更糟，因为它看着像设计过的。现在模块头注明说
>   「货币是后端的事」「跨串是唯一漏的地方，且两个后端漏法不同」。
> - **「给 `char`/`next` 补边界保险丝」这条不用做**：实测两个后端本来就一致——
>   `char`/`next`/`prev` 越界钳位（`char` 回 −1），`slice` 越界 panic
>   （`dawn_rt.c:1491`–`1521` 与 JVM 侧同策略）。保险丝只能抓越界，而真正的缺陷是
>   **落在范围内**的外来 cursor，那种 cursor 和本串的位置在表示上无法区分。
>
> **调研结论（三路 websearch，2026-08-16）：**
>
> - **编译期 brand / generative `Cursor[S]` 出局。** 三十年零交付：没有任何语言把下标绑定
>   容器放进标准库；唯一做过字符串位置的 Rust 库 `indexing-str` 2019 发布、2020-02 被
>   yank（总下载 1456）；技巧唯一藏得住的形态是「整段算法进闭包」（`runST`），而 Dawn 的
>   `Cursor` 要被持有、进结构体、从函数返回，正是那招覆盖不到的形状。依赖类型也不解决：
>   `Fin n` 绑的是长度不是身份。
> - **先例有七档**，其中 Haxe（逐目标编码表 + `target.utf16` define）与 Raku 与 Dawn 同构；
>   Raku 官方文档用 "erroneously" 标注自己 JVM 后端的 `.chars`。**没有一个当事人选择
>   「就这么放着」。**
> - **决定性的外部证据是 `Data.Text`：UTF-16 → UTF-8，公开 API 零破坏，因为它从不暴露位置。**
>   于是原则是：**货币只要不可观察就可以随时换**。反面样本同样清楚：`text-icu` 的文档在
>   货币变更四年后仍是错的，无人发现。
> - 若将来统一货币，**统一到 UTF-8 字节而不是码点**：码点货币会让 native 的快路径只剩 ASCII，
>   而本项目的负载是 CJK。
> - **绝不能用指针身份做 owner 判定**：JLS 会 intern 相同字面量，native 的字面量去重是后端
>   自己的事，于是判定本身会跨后端分歧。JS 里唯一带所有者的位置 `RegExp.lastIndex` 恰恰是
>   bug 工厂——**所有权做成可变状态是灾难，做成不可变值才安全**。
> - Julia 的 Karpinski 在 #9297 里试过胖游标，结论是 "I can't manage it"，但同一句留下了
>   "plausible to have a **StringIndex that is a wrapper around Int disallowing index
>   arithmetic**"。**Dawn 今天就站在这个被点名认可的位置上。**
>
> **仍待维护者裁决的，只剩「要不要把货币焊成不可观察的」**，以及焊完之后货币选哪个
> （那时它已是纯内部决定）。在此之前不实现，也不写 workaround。

> **裁决 B1 + 第三条腿（2026-08-16 当日续）：焊，但只焊得到的地方；跨串写明不焊。**
>
> 上面那段写完当天又量了一轮，量出**第三条腿**，而且它比前两条都近：
>
> 3. **渲染**。`to_string(c)` / `"${c}"` 直接印出货币：同一个字符串、同一行代码，
>    JVM 印 `2`，native 印 `4`。**不需要任何误用**，也不报错。它还从第 2 条腿的修补
>    底下钻了过去：`const S: String = to_string(c)` 的类型是 `String`，
>    `is_const_serializable` 当然放行，于是解释器把它折成码点索引 `1`。
>    同一个表达式因求值地点不同有三个答案。#291 的边界画在「常量的类型是不是 Cursor」，
>    而正确的边界是「这次计算碰没碰过货币」。
>
> **已关**：`std/cursor` 显式写 `impl Show[Cursor]` 渲染 `<cursor>`。实测显式 impl 会
> 赢过从目标继承来的那个（`scripts/spike-native/show_opaque.dawn` 钉的就是这条通则），
> 所以这一刀零语言改动，并且同时关掉运行期分歧与常量洗白。想印位置就印
> `cursor.offset(s, c)`，那是走出来的字符数。
>
> **同批量清的、判为不是泄漏的两条**（先量后砍，免得把猜测写成缺陷）：
>
> - `Map[Cursor, V]` 的**迭代序不分歧**。60 个键、跨多层 HAMT 实测，两个后端都按位置序
>   出。原因是位置在任何后端上都随字符单调递增，`Hash[Cursor]` 于是保持同序。
> - `hash` 不是公开函数（std 里 `pub fn hash` 为 0 处），所以哈希值本身没有出口。
>   同一串内的 `==` 与 `cmp` 也一致：`cmp` 只回 −1/0/1。
>
> **裁决（用户 2026-08-16）：B1。** 三条路量过成本：
>
> - **B1 只命名它**：跨串保持未定义，写进规格，靠跨后端对拍守住其余通道。成本 0。
> - **B2 运行期 owner 标签**：标签必须本身与后端无关，否则**判定会在游标分歧的地方
>   跟着分歧**；与后端无关的标签只有码点长度或内容哈希，都要走一趟，还要让 Cursor
>   从一个字变两个字，代价落在全项目最热的循环里。Julia 的 Karpinski 试过这个形状，
>   留下的是 "I can't manage it"。
> - **B3 统一货币**：UTF-8 到底 = JVM 侧不能再用 `java.lang.String`；码点到底 =
>   native 快路径只剩 ASCII，而本项目负载是 CJK。
>
> 取 B1。相应地，**焊完之后可以写下一句以前写不了的话**：货币是纯内部决定，随时可换，
> 不构成破坏性变更（`spec.md` §11 已写）。
>
> **两条新的外部证据**（第一轮调研没覆盖到的角度）：
>
> - **Swift SE-0241** 是同一个错误的官方复盘。`String.Index` 是 opaque 却漏了
>   `encodedOffset`，提案原话：「野外绝大多数用法都不符合原本意图，并且对编码变更敏感」。
>   修法是换成 `utf16Offset(in:)`，**必须把字符串传进去**，因为偏移量是编码相关的。
>   Dawn 的 `cursor.offset(s, c)` 早就是这个形状，只是 `Show` 那条旧路还开着。
> - **`text-2.0` 的 changelog 给出「密闭到什么程度算够」的判据**：UTF-16 换 UTF-8 之后
>   所有破坏项（`Data.Text.Array` 改 `Word8`、`Array`→`ByteArray`、`Data.Text.Foreign`
>   与 `Data.Text.Unsafe` 改名、`unsafeChr`→`unsafeChr16`）**全部落在名字里带 `Array` /
>   `Foreign` / `Unsafe` / `Internal` 的模块，`Data.Text` 本体一条都没有**。标准不是
>   100%，是「只能从一个有名字的接缝漏」。
>
> **本项维持 partial，不改 fixed。** 原文标题说的「Cursor 没有绑定所属 String」按裁决
> 仍然成立，只是从遗漏变成了写明的边界；报 fixed 会高估。
> **重开条件：** 本仓自己的代码里真出现一次跨串误用的缺陷，届时拿那个缺陷当理由重算 B2 的账。
> 门禁：`scripts/spike-native/cursor_currency.dawn`（变异体=删掉 `impl Show[Cursor]`，
> 实测转红 `jvm` / `native` / `diff` 三项，并打印 `[0, 2, 7]` vs `[0, 4, 13]`）。

## SEM-05 — P2 — `cursor.char` 用 `Int/-1` 绕开已经落地的 `Char`

> **后续处置（2026-08-09）：retracted。** 规范把 `cursor.char -> Int`/`-1` 明列为底层
> scanner 例外，`Char` 从未承诺替换这条 primitive currency；实现、双后端与调用约定一致。
> `peek -> Option[Char]` 可以作为增量 convenience API 另行设计，但原项把有意的底层契约当作
> 语义缺陷，不应记为 fixed 或继续进入 TODO。

- **性质：D。** `std/cursor.dawn:30` 返回 code point Int，并用 `-1` 表示 end；规范把它列为唯一例外：`docs/spec.md:104`。
- **问题：** 用户必须在 `done` 与 `char` 之间维持外部前置条件，遍历 primitive 输出的又不是语言的字符类型；`Char` 的类型安全只覆盖上层随机访问 API。
- **影响：** scanner 和 parser 大量继续比较裸整数/`char.code`，早期语言新增 `Char` 的收益被最核心遍历接口抵消。
- **建议：** 分成 `current(c) -> Char`（要求 not done，越界 panic）与 `peek(c) -> Option[Char]`；性能敏感的内部 intrinsic 可保留 sentinel，但不应成为 public std contract。

- **判不做（#196 分诊，2026-08-11 写回）。** 发现属实，建议撞既有裁决。判据是
  **「这个函数的答案是不是永远是一个字符」**：`cursor.char` 不是，它还要表达 end，
  所以它不该拿 `Char` 这个类型。`Char` 面是 `str.at`/`str.chars`/`code_points`，
  `cursor.char` 是那一层**下面**的原语。撞的裁决：
  [`nominal-types-design.md`](../audit/nominal-types-design.md) §7.3（裁决原文与同一句判据）、
  [`re-audit-b-decisions.md`](../audit/re-audit-b-decisions.md) 的 RD-07 **A**（越界策略三判据），
  以及 `docs/spec.md` 把 `-1` 列为唯一具名例外；那条具名正是为了不被顺手改掉。
  **重开条件：** 有人先推翻 RD-07 A 的三判据。

## SEM-06 — P1（已修）— Java `Object` 隐式窄化插入隐藏 `CHECKCAST`

> **后续处置（2026-08-09）：已修。** Java overload scorer 现在只接受 exact match 与
> `is_assignable(parameter, argument)` 为真的引用宽化；静态类型为 `Object` 的实参不再
> 反向匹配具体引用形参。JVM 参数适配器也只保留 `Int → int` 与
> `Float → float` 两个已由 checker 选定的 scalar narrowing，不再拥有引用
> `CHECKCAST` fallback。`cast` 返回 `Result`，成为 Object-to-subtype 的唯一认领路径。
> `scripts/java-narrowing-contract/run.sh` 固定隐式拒绝、显式 cast、合法 widening、
> Bytes、SAM、List bridge 与 overload 行为；恢复 scorer 特例的可执行 mutant 会打红
> checker 单测，恢复后端 fallback 的可编译 mutant 会打红结构门禁。

- **原证据：S。** 规范总体声称没有隐式转换，而旧 interop 规则与 overload scorer
  允许 `Object` 隐式窄化；JVM helper 随后补发隐藏 `CHECKCAST`。
- **影响：** 同一转换显式写是值级错误，编译器自动插入时却是隐藏异常；Java overload 集变化还可能改变被选方法与失败方式。
- **处置：** 删除隐式窄化并要求 checked cast。Java array/parameterized target 当前不可命名时
  不再借不安全转换绕过表面语法；需要时先增加可书写的 target type。

## SEM-07 — P2 — public surface 可泄露 private type/trait/effect（已修）

<!-- audit-anchor: absent selfhost/src/check/checker.dawn | pass_export_surface -->

> **后续处置（2026-08-11 登记，实现更早）：已修。** `6874f64` 给模块检查流程加了
> `pass_export_surface`：public 声明签名触及的 nominal type、trait、effect 与 associated
> type 递归按 World/StdOnly/Module audience 校验，泄漏点给出精确诊断而不是导出后才发现。
> 设计定稿在 `docs/public-surface-design.md`，负控在 `scripts/export-surface-contract/`
> （变异体先编译、再由唯一 owning 断言转红），语料在
> `scripts/checker-corpus/cases/public_surface.dawn`。doc/LSP 过滤是该设计的阶段三，属新增
> 消费面，不重开本项。**本条曾在实现发布后继续写 open**，由 `doc-check.py` 的 evidence
> 检查发现。

- **证据：S。** public signature 被定义为 API contract：`docs/spec.md:366`；默认 private：`docs/spec.md:1674`。模块检查流程没有 effective-visibility pass：`selfhost/src/check/checker.dawn:7295`；导出时直接复制签名与相关表：`selfhost/src/check/checker.dawn:8095`、`:8206`。
- **边界：** `pub fn` 可返回 private nominal type、要求 private trait bound，或暴露调用方无法命名/处理的 private effect。
- **影响：** 编译器可发布调用方无法实现或书写的 API，绕开 `pub opaque type` 作为抽象边界的设计。
- **建议：** 增加 export-surface pass，递归验证 public signature 触及的 nominal type、trait、effect 与 associated type 均有效公开；诊断给出最短泄漏路径。

## SEM-08 — P2 — Unit 字段禁令可由泛型实例化绕过

> **后续处置（2026-08-09）：retracted。** 规范明确说“构造子字段不能直接写 `Unit`”是
> 声明点的建模规则：无载荷分支应写裸构造子，不是表示限制；同一节也明确允许 `Unit` 作为
> generic argument。因此 `Box[Unit]`/`Result[Unit,E]` 合法不是绕过，原项要求 substitution
> closure 是另一种语言偏好，不构成当前规范/实现冲突。

- **证据：S。** 规范允许 `Unit` 作为 generic argument，却禁止直接 constructor field：`docs/spec.md:164`；checker 只在声明字段时检查：`selfhost/src/check/passes.dawn:741`。`Unit` 又不在结构 `Eq/Hash/Show` scalar 集：`selfhost/src/check/types.dawn:1353`。
- **边界：** `Box[Unit]` 合法，形状等价的 `Direct(value: Unit)` 非法；`Result[Unit,E]` 可以存在，却不能自然参与某些 derived/generic 操作。
- **影响：** generic abstraction 对类型替换不闭合，同一数据形状因为“直接写”或“经 type parameter”得到不同能力。
- **建议：** 允许 Unit 字段，并提供平凡 `Eq/Hash/Show/Ord`。反向禁止所有 `T = Unit` 会破坏 `Result[Unit,E]` 等常用 API，不建议。

- **判不做（#196 分诊，2026-08-11 写回）。** 上面的 retracted 裁定与分诊一致，这里补
  撞车出处：`Box[Unit]` 合法而 `Direct(value: Unit)` 非法是**有意的**。2026-07-27 的 #51
  （[`native-backend-plan.md`](../native-backend-plan.md) §12）把五条 `Unit` 禁令删到只剩
  构造子字段那一条，留下它的理由正是「它讲的是**建模**不是描述符」，`docs/spec.md` §2.1
  也逐字写着「这是建模的说法」。「泛型能绕过」不是漏洞，是这条禁令从一开始就只约束直接
  书写。**残余可议的只有标量集那半**（`selfhost/src/check/types.dawn` 的结构 eq/hash
  scalar 集无 `TyUnit`），补它是 Emit-Change，收益不抵，故一并不做。

## SEM-09 — P2 — associated type 不能声明或接收 bound

<!-- audit-anchor: present selfhost/src/check/checker.dawn | pub fn assoc_witness_err -->

> **后续处置（2026-08-09）：open，intentional delayed capability。** 现行 v1 明确延期
> projection witness/bound evidence；它限制表达力，但不是当前实现漏做已承诺语义。只有关联
> witness 的表示、dictionary 传播与 `where C.Item: Trait` 语法一起定稿后才重开，不进入自治
> 修 bug 队列。

- **证据：S。** `type Item` 语法没有 bound 位置：`docs/spec.md:472`；checker 说明 bound 无法到达 projection：`selfhost/src/check/checker.dawn:816`，对 projection witness 直接拒绝：`selfhost/src/check/checker.dawn:2752`；方案把它列为延期项：`docs/assoc-types-design.md:221`。
- **影响：** `Iter`/`Index` 的 generic consumer 不能声明 `C.Item: Show/Eq/Hash`，关联类型只能被搬运，难以用于真实算法。
- **建议：** 支持 `type Item: Show` 与 `where C.Item: Show`/projection equality；dictionary 携带选中 impl 导出的关联证据。

- **判不做（#196 分诊，2026-08-11 写回）。** 本体已由 #123 裁为搁置、等消费者，见
  [`assoc-types-design.md`](../assoc-types-design.md) §7 开放问题 2。它留下的四处不一致
  已在 #123 缺陷批修平：`C.Item` 上要 `Show`/`Ord`/`Eq`/`Hash` 一律在检查期拒绝、同一句
  措辞、同一条 hint（`assoc_witness_err`）。修之前 `Eq`/`Hash` 是「检查期放行、lower 期
  编译器 panic」，**那才是缺陷；今天的一致拒绝是答案不是症状**。
  **重开条件：** 关联 witness 的表示、dictionary 传播与 `where C.Item: Trait` 语法一起定稿。

- **排期裁决（2026-08-16，用户裁）：维持等，不设期限。** 与 `SEM-10` 不同，本条今天
  **没有任何候选消费者**：`Iter`/`Index` 的泛型算法在全仓是 0 个。硬造一个来触发重开条件
  是自欺。维持原重开条件不变。

## SEM-10 — P2 — trait/impl 与具名 effect 不能组合（已修）

<!-- audit-anchor: absent selfhost/src/check/passes.dawn | trait methods cannot declare the effect -->

> **后续处置（2026-08-20，RX-10-B 刀 5）：已修，关账。** 本条要的 ABI 裁决在
> [`effect-params-design.md`](../effect-params-design.md) 决策 5（规则丙）作出并随刀 5 落地：
> trait/impl 方法的行可以写具名标签与关联效果投影 `!T.E`；每个标签合成一格证据参数，
> 投影合成恰好一格擦除证据（字典槽位边界上 `Object`/`void*`），字典本身仍不携带任何证据、
> `dict_key` 一字未动。「impl 决定效果」那一族（泛型 state / parser / service）由 trait 体内
> `effect E` 成员加 impl 体内 `effect E = !X` 绑定承载。两条「cannot declare the effect」
> 拒绝随刀删除，checker 语料 `trait_method_effects` 第二次重写，`assoc_effects` 系列钉住
> 新机器。下面保留 v0.60.0 审查基线的原始证据与 2026-08-19 的刀 4 更正，行号是当时的。

> **后续处置（2026-08-09）：open，intentional delayed ABI。** v1 ABI 有意只允许 pure /
> `!io` trait method；放开 named effect 会决定 dictionary 是否携带 evidence、evidence 的捕获
> lifetime 与跨模块签名形状。它保留为语言能力账，但必须先作 ABI 裁决，不进入自治 TODO。

- **证据：S（v0.60.0 基线的读数，2026-08-19 按刀 4 更正）。** 审查时 v1 规则把 trait/impl
  method 限为 pure 或 `!io`。**这一半已经不成立**：RX-10-B 刀 4（A0）落地后，方法的行
  **可以带效果变量**，只是不能带具名标签——`docs/spec.md:610-611` 与 §6.5「边界（v1）」的
  `docs/spec.md:1451-1459` 都已按此改写。pass 侧的两处拒绝现在只看标签：
  `selfhost/src/check/passes.dawn:1315-1323`（trait 方法自己的行）与 `:1800-1806`（impl）；
  旧稿引的 `:1218-1227`、`:1706-1714` 是那两处拒绝在审查基线上的地址，另有两处 `eparams`
  级的拒绝已随刀 4 删除，代之以两侧效果变量按位对齐的元数检查（`:1905-1911`）。
  **剩下的本条**因此收窄成「具名标签不能进 trait/impl 方法的行」，理由是 ABI：写出来的标签
  要求调用方在调用点交出证据，而字典槽位没有这一格。
- **影响（同批收窄）：** 收内容闭包的容器型 trait（`Container` / `column` 那一族）**已经写得进
  trait 了**，那正是刀 4 买下的东西。仍然写不出来的是让 impl 决定效果的那一族——泛型 state、
  parser、service、transaction——它们要的是关联效果，用户在这些 trait API 上仍被迫退回
  `Result`/`!io`，形成与语言效果系统并行的第二套抽象。
- **建议：** 先允许 fixed named labels，再引入 trait/method-level effect parameters；evidence 只能显式携带，
  「捕获进 dictionary」那一支已经封死：dictionary 是账本外的无头静态表，drop 它会把垃圾读作计数
  （`dictish`，`selfhost/src/c/rc.dawn:528-538`），而 evidence 被刻意定为进 RC 账本的普通记录、不是
  `CDict`（[`effects-design.md`](../effects-design.md) §5.1，`:280-283`）。由此证据只能由调用方在调用点供给，
  见 [`effect-params-design.md`](../effect-params-design.md) 决策 5。

- **判不做（#196 分诊，2026-08-11 写回）。** v1 的边界写在 spec §3.5，且**有明确前置**：
  [`effects-design.md`](../effects-design.md) §4.5 写「trait/impl 方法 labels 必须为空……
  解禁等 RX-10-B」，同文 §7 开放项 5 又把 RX-10-B 列为「trait 方法带效果行」的共同前置。
  RX-10 已于 2026-07-31 裁 A，**效果参数 B 路线另立项**，那才是本条的入口。跳过前置直接
  做，字典形状变更还要 Emit-Change 加一轮种子。**重开条件：** RX-10-B 立项。

- **排期裁决（2026-08-16，用户裁）：挂到 UI DSL 那一项上，不再单独排队。** 「等消费者」
  这条纪律在自用研究项目的姿态下有个尴尬：消费者只能是我们自己。本条的天然消费者是
  UI DSL（Elm 架构那批）——泛型 state 与效果组合正是它要的东西。所以本条的命运绑定在
  那一项上：**它恢复即重开，它继续冻就一起冻**，不必再单独裁一次。前置 RX-10-B 不变。

## SEM-11 — P2 — panic/resource barriers 被硬编码为 `!io`（已分拆处置）

> **后续处置（2026-08-08，`407fb41`、`138adb9`）：已按是否观察失败分拆关闭。**
> `bracket` 不观察失败，现由 `release`、`use` 与调用共享效果变量 `!e`；
> `catch_fault`/`catch_panic` 会把失败变成值，其结果受调用栈、`file:line` 与纯调用折叠影响，
> 因而按裁决继续固定 `!io`。checker 语料同时钉住 pure/labelled `bracket` 与两个 catch
> 在纯签名中的拒绝。以下内容保留 v0.60.0 审查基线的原始证据与建议。

- **证据：S。** `catch_panic` 与 `bracket` 的规范签名固定 `!io`：`docs/spec.md:1484`、`docs/spec.md:1541`；builtin type 同样硬编码：`selfhost/src/check/types.dawn:1605`、`:1670`。
- **边界：** 捕获确定性 pure panic，或对 pure resource 执行 pure release，仍强迫整个调用方变成 `!io`。
- **影响：** effect system 系统性过度近似；pure library 无法用语言提供的唯一 cleanup/barrier primitive。
- **建议：** 改成 effect-polymorphic：barrier 返回 thunk/release/use effect union。`catch_fault` 是否应保持 IO-only可单独由 fault source 决定，不应把 panic 与 cleanup 一并绑死。

- **订正（#196 分诊，2026-08-11 写回）。** 上面冻结证据里的 `selfhost/src/check/types.dawn:1605`
  记成了 `catch_panic`，那一行其实是 `catch_fault`（两者在同一张 builtin 表里相邻登记）。
  冻结证据不改写，这里只标出误记；结论不受影响，本项的分拆处置也不依赖那一行。

- **追记（2026-08-25 裁决，写回本条）。** 两个 catch 屏障**自己的行**仍固定 `!io`，上面的
  分拆处置不变；自本次裁决起放开的是**参数位**，签名可绑定效果变量
  （`fn catch_fault[T, !e](f: fn() -> T !e) -> Result[T, ForeignError] !io`，`Sig.eparams` 形状），
  带具名标签的闭包由此能被护送穿过屏障。固定 `!io` 的三条论证（调用栈、`file:line`、
  纯调用折叠）逐条仍成立，因为它们约束的是屏障自己的行，不是被保护闭包的行；纯签名依旧
  调不动这两个屏障。理由、机制与实测见
  [`error-model-design.md`](../audit/error-model-design.md) §7.4。

- **追记（2026-09-01 裁决，写回本条）。** 上面那三条论证被逐条对着实现复核了一遍，结论是
  它们是 **`catch_panic` 的论证**：论证一（调用栈）在 ERR-01 之后两个后端都不成立
  （栈耗尽不在任一屏障的捕获名单里，到不了 `Result`），论证二、三只咬 panic。于是
  `catch_fault` **自己的行**也放开成 `!e`，`catch_panic` 一个字不动：fault 是外部世界造成的
  失败，通往外部世界的每条路已经记过 `io` 的账，屏障不必再记一笔；panic 没人记账，只剩
  屏障能记。本条原始建议里那句「`catch_fault` 是否应保持 IO-only 可单独由 fault source
  决定，不应把 panic 与 cleanup 一并绑死」到此兑现。三个屏障从此排成一条线，而不是二比一。
  不变式「fault 只从 io 来」带一个具名例外（续延是纯 fn 值，见
  [`oneshot-design.md`](../oneshot-design.md) §11.2），实测确认、本次不修。见
  [`error-model-design.md`](../audit/error-model-design.md) §7.5。

## SEM-12 — P2 — “私有函数推断效果”实际只推断 base IO（已修）

> **后续处置（2026-08-09）：已修。** 双语规范现按 checker 的真实分支写明：私有函数
> 省略返回类型时进入返回类型推断；只有它同时完全省略效果注记，才在同一路径推断 base
> pure / `!io`。显式 `-> T` 而不写效果是 pure 承诺，函数体做 IO 会报错；若省略返回类型
> 但显式写效果行，则只推断返回类型。具名 effect 从不推断；一旦写出 `!Ask`，效果行固定，
> 同时做 IO 必须声明 `!(io | Ask)`。`doc-check` 以双语结构契约和真实 checker 探针固定这些边界。

- **证据：S。** 规范称省略 private signature 时推断 return 与 effect：`docs/spec.md:366`；实现只推断 base effect并拒绝 named label：`selfhost/src/check/checker.dawn:7111`、`:7127`。
- **影响：** `!io` 与用户 effect 的书写纪律不正交；文档让用户期待不写 annotation，实际 named effect 必须手写。
- **建议：** 两阶段收集并封闭 labels；若短期不做，规范必须改成“只推断 return 与 base io”，并给出专门诊断。

## SEM-13 — P2 — 受约束函数与 trait method 不是一等函数值（已修）

<!-- audit-anchor: present selfhost/src/check/checker.dawn | has trait bounds and cannot be used as a value -->

> **后续处置（2026-08-11）：已修。** `check_fn_value` 不再在有 bound 时早退：期望的
> 函数类型定型主体之后，它按建议合成 eta 展开，witness 由 `resolve_witness` 在合成
> 闭包的 lambda 上下文里解析，于是外层函数的字典参数自动进入捕获列表，`WConcrete` /
> `WApply` / `WForward` 三种形状都落到普通调用节点上，lowering 与两个后端不需要认识
> 新形状。主体没有定型时仍然拒绝，但报的是「无法推断类型参数」，不再是「不能作值」。
> 带 effect label 的函数仍不可作值，那是另一条理由（证据在写下 lambda 的位置捕获），
> 规范 §3.5 与 §6.5 已分开陈述。门禁：checker corpus 的 `fn_value_bounds` 记住四条
> 诊断，`scripts/spike-native/fn_value_bounds.dawn` 在两个后端连同 ASan/LSan 跑通三种
> witness 形状，tutorial 的 `dawn run` 围栏跑通外层约束那一例。

- **证据：S。** 规范承认带 bound/effect label/trait method 不能直接作值：`docs/spec.md:548`；checker 要求手工包 lambda：`selfhost/src/check/checker.dawn:2550`。
- **边界：** `map(xs, to_string)` 之类自然写法失败，只能写 `x => to_string(x)`。
- **影响：** 函数 application 已一般化，但重要函数仍非一等；eta wrapper 增加噪声、捕获与可能的 allocation。
- **建议：** 在 expected function type 已知后，实例化 type/effect vars、解析 witness/evidence，自动合成 closure。

## SEM-14：P2：`Never` 是内部类型，却不能由用户命名（已修）

> **后续处置（2026-08-11）：已修。** `Never` 现为 compiler-owned hard-reserved 的
> return-only bottom。顶层/局部函数、trait/impl 方法、effect operation 与嵌套函数类型的
> 返回位可以直接书写；storage、直接 alias 与 associated binding 均拒绝；type、alias、trait、
> effect、constructor 与 type parameter 不能复用该名。JVM 的 direct、dynamic/closure、
> trait/impl/default 与 SAM bottom call 已统一走
> call-result termination seam，擦除为 `Object` 的结果先丢弃，再以 verifier 可见的
> `aconst_null; athrow` 终止。`scripts/checker-corpus`、`builtin-type-contract`、
> `classfile-verify` 与 native differential 分别固定语义、LSP/doc、所有调用形态和双后端一致性。
> `io.exit` 仍是 `Unit`。

- **原证据：S。** checker 当时已有 `TyNever`，分层 builtin inventory 也把 `Never` 明确归为
  compiler-only；public resolver 有意不接受它。规范已经使用该概念，`io.exit`
  因而只能声明 `Unit`。B200-1B 只消除了 inventory 漂移，没有提前执行本项的公开语义裁决。
- **影响：** 用户不能声明发散函数；退出后的代码被视为可达，branch/callback type 不精确。
- **建议：** 把 `Never` 暴露为硬保留的 compiler-owned bottom，但首版只允许在函数返回位
  直接书写；参数、字段、const 与 generic storage 位置继续拒绝。JVM direct/dynamic bottom call
  必须统一发 verifier 可见的终止序列，native 同步固定 non-fallthrough。`io.exit` 维持
  `-> Unit !io`，不随本项改签名。

## SEM-15 — P2 — `bracket` 的双失败语义未定义且文字承诺过强（已修）

> **后续处置（2026-08-09，状态纠偏）：已修。** #193 已把双失败定为 release-wins：
> release 自己逃逸的失败顶掉原失败，且没有 suppressed chain；双语规范、native/JVM
> spike 与 `doc-check` 已共同固定。这里此前只是状态层漏更新，没有新的语义改动。

- **证据：S。** 规范保证 release 后“原失败原样继续”：`docs/spec.md:1565`。JVM 在 catch path 调 release 后才执行原 `ATHROW`：`selfhost/src/jvm/rtclasses.dawn:907`；native 也先调用 release：`runtime/c/dawn_rt.c:913`。release 自己失败时后续 rethrow 不会执行。
- **边界：** use panic `"use"`，release panic `"release"`，最终传播 release failure，原根因丢失。
- **影响：** 最需要诊断的 cleanup 双失败路径没有稳定 contract；当前两后端碰巧都是 release-wins，不等于规范已经定义。
- **建议：** 明确选择并测试：要么文档承认 release-wins；更好的模型是保留 use failure，把 release failure 放入 `cause`/suppressed chain。

## SEM-16 — P2 — `Char` 的默认显示仍是整数码点（已修）

<!-- audit-anchor: absent std/char.dawn | fn show(c: Char) -> String -->

> **已修，分两步（用户各裁一次）。**
>
> **步 1（2026-08-18）：顶层。** 加了第七个预置 trait `Display`：一个方法
> `display(x: T) -> String`、无关联类型、`injects: false`（只有 `to_string` 与 `${...}`
> 消费它，与 `Index` 同待遇），不可 derive，`Show[T]` 仍是 `to_string` 要的 bound。
> `std/char` 写了 `impl Display[Char]`，于是 `to_string(c)`/`"${c}"` 出字符；当时**没写**
> `impl Show[Char]`，所以嵌套渲染仍是 `Int` 的。落地清单见本条末尾的「落地」。
>
> **步 2（2026-08-19）：嵌套。** `std/char` 补了 `impl Show[Char]`，返回源码字面量
> `'a'`（转义集合对齐 `lex_escape`），于是 `"${[c]}"` 出 `['a']` 而不是 `[97]`，
> `List[Char]`/`List[String]`/`List[Int]` 三者输出互不相同。`==`、`<`、`cmp`、`sort`、
> 哈希仍全是 `Int` 的。**代价是 `Char` 不再是「opaque 就是它的目标」的例子**，
> `scripts/opaque-twin/char.dawn` 因此改成逐条钉：两个渲染各钉两向，身份仍钉等于 `Int`。
> 这不违反语言规则——spec §2.7 一直允许 opaque 写自己的 impl，并把「渲染也是目标的」
> 写成以「自己没写」为前提。裁决依据是跨语言对照（有 `Char` 类型的语言里四比一用字面量形）
> 与「`[97, 98]` 和 `List[Int]` 输出撞脸」，不是需求量（那个是零）。
> 论证与落地清单在 [`nominal-types-design.md`](../audit/nominal-types-design.md) §7.4。
> 那条 audit-anchor 的**字面量**也在此修好，两次。它原本写的是 `impl Show for Char`
> （Rust 语法），在 Dawn 的树里永远匹配不上，所以它对本条从来不可能变红。换成真实拼写
> `impl Show[Char]` 后仍然是空的：这份 impl 的文档注释里也写着同一串字，删掉代码锚点照绿。
> 现在钉的是 `fn show(c: Char) -> String`，只有 impl 体里有；实测把它改掉，doc-check 变红。
> 本条转 fixed 后 `absent` 的条件被反转，所以它要求这份 impl **存在**。

- **性质：D。** 规范明确 `${c}` 沿用 Int rendering：`docs/spec.md:90`；`std/char.dawn:34` 也把它作为 opaque-target 继承规则。
- **问题：** 名为 `Char` 的值在 interpolation、`to_string`、List/record 派生显示中出现 `97` 而非 `a`；用户必须记住 `str.from_char(c)` 才得到字符文本。
- **影响：** 与用户对“字符”的基本预期、错误信息和 REPL/调试显示相悖；opaque representation 细节泄漏到语言 UI。
- **建议：** 让 `Char` 自己实现 user-facing display；若需要 code-point debug，显式使用 `char.code`。如坚持 `Show` 表示结构，可用 `Display[Char]` 处理 interpolation。

- **判不做（#196 分诊，2026-08-11 写回）。** **刻意如此。** opaque 沿用目标类型的 impl
  （spec §2.7、§4.8），所以 `Char` 的 `Show` 就是 `Int` 的。给 `Char` 单独写一份 `Show`
  会让它不再「就是它的目标」，**`opaque-twin` 那条判据也就不成立了**，而 opaque-twin 正是
  [`nominal-types-design.md`](../audit/nominal-types-design.md) §7.4 驳回 LANG-04 步 1-3 的
  地基，门禁 `scripts/opaque-twin` 已在 CI。要一个字符的字符串，`str.from_char(c)` 就是
  那个函数。**重开条件：** 维护者重开 user-facing `Show`/`Display` 边界。

- **排期裁决（2026-08-16，用户裁）：从破坏窗口批里拿出来，单独立项。** 本条此前挂在
  「破坏窗口批」下，与 `LIB-06` 并列当占位者。那个归类是错的：`LIB-06` 只需要一班车
  （改名要一轮破坏性发布），而本条要先**推翻一条设计地基**——opaque 沿用目标类型的 impl，
  `opaque-twin` 判据与 `nominal-types-design.md` §7.4 驳回 LANG-04 都站在它上面。
  把「要不要给 `Char` 单独一份 user-facing 显示」当成发布排期问题处理，会让一个语言设计
  问题混进一批机械改名里。**正确的立项名是「`Show` 与 `Display` 分层」，判据是有没有
  user-facing 显示这一层，而不是 `Char` 显示成什么。** 破坏窗口批因此只剩 `LIB-06`。

- **勘察（2026-08-18，实测）。裁决权仍在维护者，本节只交事实。** 上一条问的「有没有
  user-facing 显示这一层」，答案是**有，而且早就有**，只是不叫这个名字。

  **实测（`bin/dawn run` 探针）：**

  | 表达式 | 结果 |
  |---|---|
  | `show("hi")` | `"hi"`（带引号） |
  | `to_string("hi")` / `${"hi"}` | `hi`（不带） |
  | `show(Box { v: "hi" })` | `Box { v: "hi" }`（字段带引号） |
  | `show('a')` / `${'a'}` / `Box { v: 'a' }` | `97` |

  这条区别不是偶然：spec §4.3 已写下「顶层的 `String` 不加引号，嵌套的加」，
  `selfhost/src/ir/interp.dawn:2747` 有一条单测就叫 `` `show` is the nested rendering
  and `to_string` is not ``，而它承重：`SEM-03` 就是这层的 opaque 剥法出的真缺陷。
  **所以「加一层」这个说法是错的，正确说法是「已有的那层要不要对用户开放」。**

  **那层的全部实现是 `selfhost/src/ir/lower.dawn:261` 的 `to_str`**，内容只有：
  `TyString` 恒等、`TyUnit` 出 `()`、opaque **逐层**剥并在每层问 `has_own_show`
  （一次剥到底就是 `SEM-03`）、其余交给 `Show` 字典。于是今天用户类型的 Display 恒等于
  `Show`，无处可分。`Char` 落在错的一侧的原因很具体：它是 `opaque type Char = Int`
  且没有自己的 `Show`，`to_str` 剥到 `Int` 就交给 `Int` 的 impl 了。

  **一条对 #196「不做」理由的更正。** 那条理由说给 `Char` 写显示会让它不再「就是它的
  目标」、`opaque-twin` 判据随之不成立。这对 `impl Show[Char]` 成立，但对一个**只被
  `to_string`/`${}` 消费的 `Display` trait 不成立**：`Show[Char]` 保持继承 `Int` 的，
  `opaque-twin` 的判据一字不改。而且这样的 trait 有现成先例，`Index` 就是**不注入**
  函数命名空间的预置 trait（spec §3.5，运算符本身在 §4.8），`Display` 可以同样不注入。落地形状小到
  出乎意料：`to_str` 把 `has_own_show` 改成先问 `has_own_display`，加一个 prelude
  trait id（今天六个：`Ord`/`Eq`/`Hash`/`Show`/`Iter`/`Index`）。**没有任何 `Display`
  impl 时字节完全不变**，只有 std 真写了 `impl Display[Char]` 之后、且只在插值到
  `Char` 的地方才有 Emit-Change。

  **反方向的成本也量了一条：** 不走 trait 而在 `to_str` 里给 `Char` 加一条臂，等于把
  2026-07-30 删掉 `Cursor` 的 `Ty` 变体那个决定走回去（`types.dawn:350` 的注释写着
  `CHAR_OPAQUE_ID` 全仓只用于构造类型、不做分派键，共 2 处引用）。这条不推荐。

  **需求侧实测：全仓 28 处 `str.from_char`（不含 `std/str` 自身与嵌入副本），
  其中只有 4 处是「本想显示一个字符」：**
  `examples/text/chars.dawn:59`、`:64`（这个例子存在的目的就是讲这个意外），
  `selfhost/src/front/lexer.dawn:585`（`unknown escape: \x`）、`:935`
  （`unrecognized character: x`）。另外 24 处是正常的 Char→String 构造
  （拼一个 `\r`、百分号解码之类），有了 `Display` 也不会少一处。
  **归因到本条的缺陷数：0。** `selfhost/src/driver/stdlib.dawn:89` 还把
  `str.from_char(...)` 作为 `char_to_string` 的迁移提示写在了 hint 里。

  **待裁决（维护者）：** 上面把成本从「推翻一条设计地基」修正为「一个不注入的预置
  trait + `to_str` 多问一次」，把收益量为「4 个调用点，0 个缺陷，全部已用显式函数写对」。
  在这两个数字之下要不要做，是排期判断而非技术判断。若判不做，建议把重开条件从
  「维护者重开边界」改成可检验的形式，例如「`Display` 出现第二个 `Char` 之外的消费者」。

- **落地（2026-08-18）。用户裁「做」，形状按上条勘察，未再改设计。**

  **语言侧。** `DISPLAY_ID = 6`，`prelude_traits()` 多一条 `Display`、`prelude_trait_ids()`
  多一个 id（`selfhost/src/check/types.dawn`）。`to_str`（`selfhost/src/ir/lower.dawn`）在
  **函数最顶上**先问 `has_own_display`，在 `TyString` 恒等之前。问在顶上不是随手放的：
  `to_str` 会递归进 opaque 的目标，问在顶上等于**每剥一层都重问一次**，这正是 SEM-03
  换来的形状；问进 opaque 臂里会让非 opaque 类型的 `Display` 失效。`dawn doc --stdlib`
  的预置 trait 散文多一条（`selfhost/src/doc.dawn`）。

  **std 侧。** `std/char.dawn` 一条 `impl Display[Char] { fn display(c) = str.from_char(c) }`。
  `str.from_char` 原样保留：它是**按名字问**同一个字符串，不依赖 impl 在场，全仓 24 处
  Char→String 的构造用法一处也不该改。

  **判词与负控。**
  - `std/char` 的单测钉「顶层是字符、元组里是码点」；`examples/text/chars.dawn` 同款，
    并把那两行「本来就是为了讲这个意外」的示范改写成讲两层。
  - `scripts/spike-native/display_layers.dawn` + `.expect`：双后端 + 手写期望，覆盖
    「顶掉继承来的 `Show`」「顶掉自己写的 `Show`」「顶掉 `String` 恒等」「两层三层都问到」
    以及反面的「嵌套不动」「`[T: Show]` 下仍走见证」。
  - `scripts/display-layering-contract/`：两个 compiling mutant，一条规则一个。
    `drop-display-question`（整段删掉问询）把 `display_wins_over_show` 与
    `display_is_asked_at_every_peel_layer` 都弄红；`ask-display-once`（只在写下来的那个
    类型上问一次，即被否掉的「问进 opaque 臂」形状）只弄红后者，且**不碰 `Show` 的逐层
    剥法**，所以 SEM-03 不受它影响。control `show_stays_the_nested_rendering` 两个 mutant
    都不许动。

  **一条记下来、不修的后果。** 类型变量仍走它的 `Show` 见证，所以
  `fn f[T: Show](x: T) = "${x}"` 里面拿到的是 `Show` 不是 `Display`。**这不是本批带来的**：
  同样的道理让 `to_string("hi")` 出 `hi` 而 `f("hi")` 出 `"hi"`，spec §4.3 早已把规则写成
  「只在**静态类型就是 `String`** 时去掉引号」。让字典携带 `Display` 不做，规范两侧
  §4.3 各写了一段说明这条按静态类型定。

## SEM-17 — P3（已修）— Java `char` bridge 诊断明确两种字符模型

> **已修（2026-08-09，`3fc1e9e`）。** 原诊断把 bridge 不兼容误报成 Dawn 没有字符类型；当前诊断明确 Java `char` 是一个 UTF-16 code unit，而 Dawn `Char` 是 Unicode scalar，并给出返回解码后 `int` 或 `String` 的 adapter 路径。

- **当前行为：** `map_java_return` 仍有意拒绝把 Java `char` 直接映射为 Dawn `Char`：`selfhost/src/check/checker.dawn:6243`；这保住了 `Char` 的 Unicode scalar invariant，而不是声称 Dawn 缺少该类型。
- **验证：** checker 单元测试钉住主诊断与 hint：`selfhost/src/check/checker.dawn:7482`；checker corpus 同步钉住对外文本：`scripts/checker-corpus/cases/java_bridge.expected:3`。
- **剩余边界：** 若以后增加直接 interop，仍应使用 `U16` 或 checked conversion，不能把 surrogate 直接装进 `Char`。

## SEM-18（P2）：range `for` 的运行时边界求值顺序反源码（已修）

> **已修（2026-08-12）。** `for x in a..b` 现在先求值并绑定 `a`，再求值并绑定 `b`；
> 两端各恰好一次，且都在进入循环前完成。中英文规范 §4.7 已明确该顺序，空区间也不例外。

- **原证据：D。** `lower_expr` 原本先处理 `from`、再处理 `to`，但生成的 `CSLet` 列表先放
  隐藏上界、再放循环变量。Core statement list 才是运行时顺序，因此 JVM/native 共享同一
  个 upper-first 错误，普通后端互比无法发现。
- **修复：** `selfhost/src/ir/lower.dawn` 只交换两个 `CSLet`，保持 bound 各 lower 一次、
  归纳变量、测试、body 与 step 形状不变。修复位于共享 Core，不给任一后端加重排特例。
- **绝对行为 oracle：** `scripts/spike-native/eval_order.dawn` 在既有首行不漂移的前提下，
  增加有副作用的空区间和非空区间。手写 expectation 要求 lower 先于 upper；空区间仍求两端
  且 body 不执行，非空区间在两端之后执行三轮并累计为 `234`。
- **结构与负控：** `scripts/range-bound-order-contract/` 直接读取 Core 固定 lower-first
  `CSLet` 顺序，并以不依赖动态输出的 control 固定四个 bound call 各一次且位于 loop 前。
  唯一 compiling mutant 精确恢复 upper-first 列表，完整 build、回答合法版本后只能把
  hand-owned owner 打红；matrix 的 role、owner、red、control 均由 fail-closed 自测读取。
- **范围：** 本批当时不修改 iterable `for`、for-pattern、步长、右开边界或溢出语义；
  SYN-13 后来已作为独立批次关账。
