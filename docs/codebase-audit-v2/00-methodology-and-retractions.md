# Dawn 代码库审查 v2：方法、边界与旧结论撤回

> 状态：**current** —— `codebase-audit-v2.md` 的审查口径、证据等级与旧结论处置表。

返回[总纲](../codebase-audit-v2.md)。

## 1. 审查基线

- 审查开始时的提交是 `77ae6aebf6cc6c160a88160c0f2d664b06fd62b9`。
- 审查期间主分支前进到 `86f6a0f6396084871b6d663fbf6092af66a3991a`（v0.60.0）。前两次提交只改版本号、双语规范版本标记、seed release 与 checksum；最后一次把 `jvmops/jvmhelp/lsp/lsp/front/dump` 重命名为 `ops/help/lsp/server/front/lexdump` 并更新引用，没有改变本报告评估的行为。
- 最终引用均按 `86f6a0f63960` 复核并迁到新路径。并发代理没有编辑本报告文件；写报告前工作树为空。
- 旧报告 `docs/codebase-audit.md` 的实现基线是 dawn 0.11.0。它继续保留历史价值，但不再作为当前风险台账。
- 后续状态先由 R-AUDIT 在 `bfc358a6116303623a4968f8247689bcd5645793` 对六份明细的
  97 个 ID 逐项重算，再计入后续关闭项；冻结严重度与原始证据不改写。总纲中截至
  `76491bb` 的 54 已修 / 3 部分 / 40 开放三状态分区是明确的历史快照，继续接受完整性
  校验，但绝不是 current registry；97 项的唯一当前状态源是总纲的四状态层。

## 2. 范围与分工

本轮把仓库分成六条只读审查线，再由主审去重和重判：

1. lexer、parser、formatter、语法规范与编辑器语法；
2. 类型、trait、associated type、效果、错误模型与 nominal abstraction；
3. checker、Core IR、comptime、JVM/C 后端与 native runtime；
4. CLI、LSP、构建、包管理、自举与发布；
5. std、JSON、inflate、SHA-2 与 Web；
6. 文档、示例、测试门禁、代码风格与治理。

“文件大”“实现复杂”“不是我偏好的语法”本身都不算发现。每条保留项至少满足一项：

- 规范与实现可直接对照出冲突；
- 有最小边界可让合法输入被拒、错误输入被接受、数据被破坏或后端产生不同结果；
- API 可表示无效状态、静默丢失信息或无法组合已有核心抽象；
- 阶段接口靠位置、字符串或隐式全局不变量连接，已经形成具体错误或高概率失效模式；
- 门禁声称覆盖某契约，但从脚本控制流可证明没有覆盖。

## 3. 证据等级

| 标记 | 含义 |
|---|---|
| **V** | 做过最小、无副作用复现；命令只读仓库，探针放在临时目录。 |
| **S** | 静态证据闭合：调用链、数据流或两个后端实现可以直接推出结果。 |
| **K** | 仓库自己的注释或方案已经承认该差异，但仍未修复；本报告评估的是当前影响。 |
| **D** | 设计缺口或人体工学问题；行为可能是刻意的，但早期语言仍值得破坏性重审。 |

v0.60 冻结基线的最高风险项 `SEM-01` 只给出 **S / P0 候选**。遵照当时要求，没有运行能让“纯函数实际执行 IO”的动态探针，也没有动态测试 `unsafe_pure`。native failure 的嵌套覆盖、长消息截断和 unwind 泄漏同样只依据源码与仓库已有说明，不构造破坏性压力输入。`SEM-01` 后来已由 #188 动态确认并修复；这条后续事实不反写冻结证据。

本轮实际做过的安全探针包括：

- `dawn check` 对确定诊断仍退出 0；
- 返回类型推断把参数名误当顶层函数依赖；
- lexer/parser/formatter 的内存或临时文件探针（非法字符、插值、`Int.MIN`、or-pattern 等）；
- 未执行目标程序、网络服务、包下载或 `unsafe_pure`。

## 4. 严重度

| 等级 | 本报告含义 |
|---|---|
| **P0 候选** | 若静态推导成立，会破坏语言核心 soundness、安全边界或发布信任根；因未做最高风险动态验证，不能写成“已动态确认”。 |
| **P1** | 已确认的语义错误、数据/源码破坏、跨后端分歧、安全限制失效或会让正常工程产生系统性假结果的问题。 |
| **P2** | 语言组合性、API 有效状态、架构耦合、错误恢复、可维护性或覆盖面的实质缺陷。 |
| **P3** | 低风险边界、诊断、命名、编辑器、注释或文档一致性问题。 |

优先级不是修复成本。早期语言应优先做“现在破坏一次，长期少背一层特殊规则”的 P2 设计修正。

## 5. 旧审查中应撤回的高影响结论

| 旧结论 | v2 处置 | 当前证据 |
|---|---|---|
| 用户可用 `unsafe_pure` 伪造纯性 | **撤回旧 P0** | checker 仅允许 bundled std：`selfhost/src/check/checker.dawn:3643`；规范明确用户不可用且当前零使用点：`docs/spec.md:974`。它仍是 std TCB，不再是用户入口。 |
| 集合只有续传 class、没有主干源码 | **撤回旧 P0** | `std/pvec.dawn`、`std/hamt.dawn` 已是纯 Dawn；Core/RC/native 门禁覆盖这些实现。 |
| 调用不是一般 postfix，`make()(1)` 不可用 | **撤回** | parser 的一般 application 路径已落地：`selfhost/src/front/parser.dawn:1567`。v2 只报告 pipe 与 formatter 没有跟上。 |
| 没有 lowered/Core IR，后端各自定义语义 | **撤回** | `selfhost/src/ir/core.dawn` 与 `selfhost/src/ir/lower.dawn` 已成为共享中间层，JVM 与 C 消费同一 lowered module。 |
| JSON 大整数先转 Float、renderer 可写非法控制字符/Infinity | **撤回** | 整数直接按 Int 解析：`packages/json/src/parser.dawn:193`；renderer 拒绝非有限数并转义控制字符：`packages/json/src/render.dawn:57`、`packages/json/src/render.dawn:79`。 |
| Web v2 尚未实施 | **撤回** | 方案头已经标完成：`docs/audit/web-api-v2-design.md:3`。当前问题是新 API 的具体边界，不是“仍未重做”。 |
| LSP debounce 尚未实施 | **撤回** | `selfhost/src/lsp/server.dawn:464` 已使用 readiness/debounce 原语；旧索引没有同步。 |
| `Char` 尚未落地 | **撤回** | `docs/spec.md:88`、`std/char.dawn:34` 与 v0.57 以后实现均已是 opaque `Char`。v2 只重审其显示与 Cursor 组合。 |
| cast 失败不可恢复、缺少结构化 foreign error/catch/bracket | **撤回** | `cast` 返回 `Result`，`ForeignError`、`catch_fault`、`catch_panic`、`bracket` 均已落地；v2 报告的是 native 实现细节和双失败语义。 |
| 模块限定类型、构造器、常量不可访问 | **撤回** | 规范和 checker 已支持模块限定访问：`docs/spec.md:1655`。 |
| seed jar 完全没有 checksum | **撤回原表述** | `scripts/seed-checksums.txt` 与 `scripts/seedjar.sh` 已校验 jar。v2 的 `TOOL-15/16` 是 seed std 未校验和缺条目时 fail-open，范围不同。 |
| release 不复用普通 gates | **撤回** | `.github/workflows/release.yml:33` 调用 reusable gates。v2 的 `DOC-08` 只针对 release jar 构建配方仍复制。 |

## 6. 已复核但不重新立项的争议项

| 项目 | v2 判断 |
|---|---|
| Unicode 标识符不是 ASCII/XID | 规范已明确为实现定义并承认 normalization 未决：`docs/spec.md:47`。没有新的实现/规范冲突，不重复旧 SYN-01。 |
| `!` 同时表示效果与 postfix unwrap | 两处语法位置可区分，旧审查已作风格性驳回。formatter 的具体错误另列 `SYN-06`。 |
| `docs/grammar.ebnf` 落后 parser | 文件已明确降为 historical；当前裁判是 spec、parser 与 grammar corpus。它可以重写，但不能继续算规范违约。 |
| Float 有 `Eq`、无 `Hash`/`Ord` | 已有明确裁决与一致实现，不用个人偏好重开。 |
| JSON 重复 key、孤立 surrogate | 旧审查已基于 JSONTestSuite 与 Dawn String 表示裁决；未发现新的协议违约。 |
| 完整模块 `use m` 与选择性 `use m.{x}` 并存 | 规范已经明确两者用途，不再算冲突。 |
| module alias 与局部变量同命名空间 | 是为保证 `alias.member` 可判定的明确限制；没有新的误解析证据。 |
| 单元素 tuple、控制头 record literal、跨行 `(` 不续接 | 都有明确消歧理由和 corpus；不把“别的语言允许”当缺陷。 |
| native/JVM 两份 CLI 外壳 | 双实现用于差分独立性，本身不定罪；只报告已经出现的可观察漂移 `TOOL-04`。 |
| native 仅支持 Linux/POSIX | 是项目公开目标，不把 Windows 假设列为缺陷。 |
| fspath 在 compiler/package 中各一份 | 自举依赖限制有记录，且当前共享子集未发现漂移。 |
| comptime 必须整体 trampoline 化 | 现有实测裁决合理否决了这一个方案；v2 另报 512 MB 栈策略和诊断/缓存问题，不把旧方案复活。 |
| 文件行数大即应继续拆 | 物理拆分已经发生；v2 只报告位置对齐、全局 ID、错误吞没等具体耦合。 |

## 7. “仓库已承认”不等于“问题已消失”（冻结基线）

> 本节保留 v0.60 当时“已知但未修”的例子。其后 `ARC-03/04/05` 已修；associated bound、
> trait effect 与大栈策略的当前执行状态在下一节订正，不能继续把本节当作 TODO 队列。

以下项目在源码或方案里已有说明，但仍影响当前用户，因此保留：

- native 捕获失败把消息截断到 512 字节：`runtime/c/dawn_rt.c:773`、`docs/native-driver-plan.md:740`；
- `longjmp` 丢弃帧所持引用并由 `.leaks-on-catch` 关闭 LeakSanitizer：`runtime/c/dawn_rt.c:899`、`scripts/spike-native/run.sh:45`；
- associated type bound 被延期：`docs/assoc-types-design.md:221`；
- 具名效果暂不进入 trait/impl：`docs/spec.md:1106`；
- 整个工具链依赖 512 MB 栈策略：`bin/dawn:61`、`runtime/c/dawn_rt.h:373`；
- grammar EBNF、若干历史设计与当前状态不同，但只有仍标 current/normative 的矛盾才在 v2 计问题。

“已知”只能降低发现的新颖性，不能降低语义影响；“明确取舍”只有在规范、实现、工具和错误模型都一致时才可作为驳回理由。

## 8. `18fb3d6` 历史状态快照与撤回边界

本节只记录 `18fb3d6` 验收时点，不是 current registry；后续处置只更新总纲的机器权威
四状态层。严重度回答“v0.60 发现时若成立有多重”，本快照状态回答“到该验收基线如何
处置”。`retracted` 只用于后续复核认定原项不是缺陷，不能拿来包装“尚未实现”或
“修了一半”。该时点逐 ID 结果为 **60 fixed / 5 partial / 30 open / 2 retracted = 97**；
相对 `60e174a`，`TOOL-05`/`TOOL-06` 由 open 转为 fixed，其余 ID 状态不变。

- **`SEM-05` retracted。** `cursor.char -> Int` 与 `-1` sentinel 是规范明确列出的底层扫描
  例外，调用方使用 `done`/`char` 的前置条件也是有意的 scanner contract；`Char` 并未承诺取代
  这条 primitive currency。增加 `Option[Char]` convenience API 可以是新特性，但不能继续把
  现行、双端一致的已裁规则计成缺陷。
- **`SEM-08` retracted。** “构造子字段不能直接写 `Unit`”是声明点的建模规则：无载荷分支
  应写裸构造子，不是表示能力限制。规范同时明确 `Unit` 可作 generic argument；因此
  `Box[Unit]`/`Result[Unit,E]` 合法不是绕过，而是两条规则有意共存。原项把 substitution
  closure 偏好当成规范矛盾，应撤回而非“修复”。
- **`SEM-01` fixed。** 后续动态复现确认其 soundness 风险，#188 删除错误 evidence
  subtraction 并收紧函数值效果边界；它从当前 P0 候选移出，但冻结 P0 行仍保留。
- **`SYN-12` fixed。** 顶层 dispatch 与 recovery 已共用 typed declaration-head classifier；
  完整 contextual `opaque type` 是恢复锚点，防止扫描跳过 `opaque` 后从其内部 `TYPE` 把声明
  误解为普通 type/alias；非法 `opaque` 拼法不是锚点，扫描会继续并可在随后真正的 `fn` 等
  声明头恢复，避免在无效 `opaque` 处额外停一次并产生级联 opaque 诊断。grammar fixture 与
  可编译 mutant 已固定该边界。
- **`SYN-16` fixed。** 裸 `return` 现在只委托给专用 `is_bare_return_boundary`：在原有
  NEWLINE、`}`、`)`、`,`、EOF 集合上精确补入 `]`，没有泛化到 colon、arrow 或通用
  expression terminator。`(return)`、`[return]`、`f(return)`、`(return, 1)`、`{ return }`
  五种形状均由 parser fixture 固定；checker 仍会拒绝 `Int` 返回函数中的裸 `return`。与
  `SYN-12` 共用的组合 contract 里，`drop-rbracket-return-boundary` mutant 先成功编译，再由
  owning parser test 转红；normalized Core 仅 `front.parser` 改变。
- **该快照最高风险只记三项未验证静态候选：** `SYN-04` effectful guard 可能因 alternative
  重复求值、`SEM-04` comptime/runtime Cursor 偏移可能跨模型失配、`LIB-18` streaming clean
  truncation 可能静默成功。三者不新增 ID、不提升冻结严重度，也不冒称动态确认。
- **执行状态不等于 finding 状态。** 该快照中 `SEM-09/10` 是 intentional delayed capability/ABI，
  仍 open 但不进自治修 bug；`ARC-09/10` 与 `SEM-16` 按既有不做/重开条件置于 HOLD；
  `SYN-17` 是 D/P3 的关键字预算设计项。只有条件满足或维护者重开时才进入实现队列。
