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

> **当前静态候选（未验证，不改严重度）：** comptime 把 Cursor 解释为 code-point index，
> JVM/native 分别发射 UTF-16 offset 与 UTF-8 byte offset。如果 comptime 折叠出的 opaque
> Cursor 值进入运行期操作，偏移可能跨执行模型失配。R-AUDIT 只完成静态追踪，未证明可达
> 程序；本项保持 open/P1，等待 owner/value 与 Eq/Ord 契约裁决，不先写 workaround。

- **证据：S。** `Cursor` 只是 opaque `Int`：`std/cursor.dawn:18`，所有操作重新接收任意 String：`std/cursor.dawn:22`、`:28`、`:31`、`:40`。源码甚至承认另一个 String 的 cursor 会“数到某个 end”：`std/cursor.dawn:126`。
- JVM offset 是 UTF-16 unit，native 是 UTF-8 byte，comptime interpreter 是 code-point index：`selfhost/src/jvm/rtclasses.dawn:2290`、`runtime/c/dawn_rt.c:1344`、`selfhost/src/ir/interp.dawn:850`。
- **边界：** 把 `cursor.end("😀")` 传给 `cursor.offset("abcd", c)`，三个执行模型可分别看见 2、4、1；把 `cursor.end("a")` 用于 `"😀"` 可落在 surrogate/continuation byte 中部。
- **影响：** 同一合法 Dawn 程序跨后端不同，`Char` 的 Unicode scalar invariant 也可被错误来源的 cursor 破坏。规范“只有 arithmetic 能制造非法位置”的表述：`docs/spec.md:1819` 不成立。
- **建议：** 破坏性改为 Cursor 自带 source identity/value，操作不再另收 String；或引入 generative `Cursor[S]`。至少在 runtime 验证 owner 与 code-point boundary，并禁止不同 owner 的 Eq/Ord。

## SEM-05 — P2 — `cursor.char` 用 `Int/-1` 绕开已经落地的 `Char`

> **后续处置（2026-08-09）：retracted。** 规范把 `cursor.char -> Int`/`-1` 明列为底层
> scanner 例外，`Char` 从未承诺替换这条 primitive currency；实现、双后端与调用约定一致。
> `peek -> Option[Char]` 可以作为增量 convenience API 另行设计，但原项把有意的底层契约当作
> 语义缺陷，不应记为 fixed 或继续进入 TODO。

- **性质：D。** `std/cursor.dawn:30` 返回 code point Int，并用 `-1` 表示 end；规范把它列为唯一例外：`docs/spec.md:104`。
- **问题：** 用户必须在 `done` 与 `char` 之间维持外部前置条件，遍历 primitive 输出的又不是语言的字符类型；`Char` 的类型安全只覆盖上层随机访问 API。
- **影响：** scanner 和 parser 大量继续比较裸整数/`char.code`，早期语言新增 `Char` 的收益被最核心遍历接口抵消。
- **建议：** 分成 `current(c) -> Char`（要求 not done，越界 panic）与 `peek(c) -> Option[Char]`；性能敏感的内部 intrinsic 可保留 sentinel，但不应成为 public std contract。

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

## SEM-07 — P2 — public surface 可泄露 private type/trait/effect

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

## SEM-09 — P2 — associated type 不能声明或接收 bound

> **后续处置（2026-08-09）：open，intentional delayed capability。** 现行 v1 明确延期
> projection witness/bound evidence；它限制表达力，但不是当前实现漏做已承诺语义。只有关联
> witness 的表示、dictionary 传播与 `where C.Item: Trait` 语法一起定稿后才重开，不进入自治
> 修 bug 队列。

- **证据：S。** `type Item` 语法没有 bound 位置：`docs/spec.md:472`；checker 说明 bound 无法到达 projection：`selfhost/src/check/checker.dawn:816`，对 projection witness 直接拒绝：`selfhost/src/check/checker.dawn:2752`；方案把它列为延期项：`docs/assoc-types-design.md:221`。
- **影响：** `Iter`/`Index` 的 generic consumer 不能声明 `C.Item: Show/Eq/Hash`，关联类型只能被搬运，难以用于真实算法。
- **建议：** 支持 `type Item: Show` 与 `where C.Item: Show`/projection equality；dictionary 携带选中 impl 导出的关联证据。

## SEM-10 — P2 — trait/impl 与具名 effect 不能组合

> **后续处置（2026-08-09）：open，intentional delayed ABI。** v1 ABI 有意只允许 pure /
> `!io` trait method；放开 named effect 会决定 dictionary 是否携带 evidence、evidence 的捕获
> lifetime 与跨模块签名形状。它保留为语言能力账，但必须先作 ABI 裁决，不进入自治 TODO。

- **证据：S。** v1 规则把 trait/impl method 限为 pure 或 `!io`：`docs/spec.md:1106`；pass 明确拒绝 named effect/effect var：`selfhost/src/check/passes.dawn:1158`。
- **影响：** 无法定义泛型 state、parser、service、transaction trait；用户被迫在 trait API 退回 `Result`/`!io`，形成与语言效果系统并行的第二套抽象。
- **建议：** 先允许 fixed named labels，再引入 trait/method-level effect parameters；dictionary 必须显式携带或捕获 evidence。

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

## SEM-12 — P2 — “私有函数推断效果”实际只推断 base IO（已修）

> **后续处置（2026-08-09）：已修。** 双语规范现按 checker 的真实分支写明：私有函数
> 省略返回类型时进入返回类型推断；只有它同时完全省略效果注记，才在同一路径推断 base
> pure / `!io`。显式 `-> T` 而不写效果是 pure 承诺，函数体做 IO 会报错；若省略返回类型
> 但显式写效果行，则只推断返回类型。具名 effect 从不推断；一旦写出 `!Ask`，效果行固定，
> 同时做 IO 必须声明 `!(io | Ask)`。`doc-check` 以双语结构契约和真实 checker 探针固定这些边界。

- **证据：S。** 规范称省略 private signature 时推断 return 与 effect：`docs/spec.md:366`；实现只推断 base effect并拒绝 named label：`selfhost/src/check/checker.dawn:7111`、`:7127`。
- **影响：** `!io` 与用户 effect 的书写纪律不正交；文档让用户期待不写 annotation，实际 named effect 必须手写。
- **建议：** 两阶段收集并封闭 labels；若短期不做，规范必须改成“只推断 return 与 base io”，并给出专门诊断。

## SEM-13 — P2 — 受约束函数与 trait method 不是一等函数值

- **证据：S。** 规范承认带 bound/effect label/trait method 不能直接作值：`docs/spec.md:548`；checker 要求手工包 lambda：`selfhost/src/check/checker.dawn:2550`。
- **边界：** `map(xs, to_string)` 之类自然写法失败，只能写 `x => to_string(x)`。
- **影响：** 函数 application 已一般化，但重要函数仍非一等；eta wrapper 增加噪声、捕获与可能的 allocation。
- **建议：** 在 expected function type 已知后，实例化 type/effect vars、解析 witness/evidence，自动合成 closure。

## SEM-14 — P2 — `Never` 是内部类型，却不能由用户命名

- **证据：S。** checker 有 `TyNever`：`selfhost/src/check/types.dawn:210`，builtin name resolver 没有 `Never`：`selfhost/src/check/types.dawn:336`；规范已经使用该概念：`docs/spec.md:1200`。`io.exit` 因而只能声明 `Unit`：`std/io.dawn:47`、`selfhost/src/check/types.dawn:1697`。
- **影响：** 用户不能声明发散函数；退出后的代码被视为可达，branch/callback type 不精确。
- **建议：** 暴露 reserved builtin `Never`，限制 value construction，完善 JVM/C unreachable return lowering，并把 `io.exit` 改为 `-> Never !io`。

## SEM-15 — P2 — `bracket` 的双失败语义未定义且文字承诺过强（已修）

> **后续处置（2026-08-09，状态纠偏）：已修。** #193 已把双失败定为 release-wins：
> release 自己逃逸的失败顶掉原失败，且没有 suppressed chain；双语规范、native/JVM
> spike 与 `doc-check` 已共同固定。这里此前只是状态层漏更新，没有新的语义改动。

- **证据：S。** 规范保证 release 后“原失败原样继续”：`docs/spec.md:1565`。JVM 在 catch path 调 release 后才执行原 `ATHROW`：`selfhost/src/jvm/rtclasses.dawn:907`；native 也先调用 release：`runtime/c/dawn_rt.c:913`。release 自己失败时后续 rethrow 不会执行。
- **边界：** use panic `"use"`，release panic `"release"`，最终传播 release failure，原根因丢失。
- **影响：** 最需要诊断的 cleanup 双失败路径没有稳定 contract；当前两后端碰巧都是 release-wins，不等于规范已经定义。
- **建议：** 明确选择并测试：要么文档承认 release-wins；更好的模型是保留 use failure，把 release failure 放入 `cause`/suppressed chain。

## SEM-16 — P2 — `Char` 的默认显示仍是整数码点

> **后续处置（2026-08-09）：open/HOLD。** 当前规范明确选择码点显示，std 与派生显示一致；
> R-AUDIT 没有发现新的实现分叉。既有“不做”条件继续生效：除非维护者重开 user-facing
> `Show`/`Display` 边界，否则不以 bug 名义迁移输出，也不进入自治 TODO。

- **性质：D。** 规范明确 `${c}` 沿用 Int rendering：`docs/spec.md:90`；`std/char.dawn:34` 也把它作为 opaque-target 继承规则。
- **问题：** 名为 `Char` 的值在 interpolation、`to_string`、List/record 派生显示中出现 `97` 而非 `a`；用户必须记住 `str.from_char(c)` 才得到字符文本。
- **影响：** 与用户对“字符”的基本预期、错误信息和 REPL/调试显示相悖；opaque representation 细节泄漏到语言 UI。
- **建议：** 让 `Char` 自己实现 user-facing display；若需要 code-point debug，显式使用 `char.code`。如坚持 `Show` 表示结构，可用 `Display[Char]` 处理 interpolation。

## SEM-17 — P3（已修）— Java `char` bridge 诊断明确两种字符模型

> **已修（2026-08-09，`3fc1e9e`）。** 原诊断把 bridge 不兼容误报成 Dawn 没有字符类型；当前诊断明确 Java `char` 是一个 UTF-16 code unit，而 Dawn `Char` 是 Unicode scalar，并给出返回解码后 `int` 或 `String` 的 adapter 路径。

- **当前行为：** `map_java_return` 仍有意拒绝把 Java `char` 直接映射为 Dawn `Char`：`selfhost/src/check/checker.dawn:6243`；这保住了 `Char` 的 Unicode scalar invariant，而不是声称 Dawn 缺少该类型。
- **验证：** checker 单元测试钉住主诊断与 hint：`selfhost/src/check/checker.dawn:7482`；checker corpus 同步钉住对外文本：`scripts/checker-corpus/cases/java_bridge.expected:3`。
- **剩余边界：** 若以后增加直接 interop，仍应使用 `U16` 或 checked conversion，不能把 surrogate 直接装进 `Char`。
