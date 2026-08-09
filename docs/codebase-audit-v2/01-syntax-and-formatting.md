# Dawn 代码库审查 v2：语法、词法与格式化

> 状态：**current** —— 当前 parser/lexer/formatter/编辑器语法的详细审查记录。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- 两项 P1 都会直接损害源码或让规范承诺的合法表达式不可用。
- 主要结构问题不是“语法少”，而是新语法只补进 parser，pipe、formatter、错误恢复、TextMate grammar 与规范清单没有共享同一份结构。
- 建议优先把 formatter 改成“词法失败即不写回”，再统一 member/application/pattern AST；早期版本不应继续为旧 AST 形状加特判。

## SYN-01 — P1 — formatter 在词法错误时静默删源码

- **证据：V。** `format` 丢弃 lexer diagnostics：`selfhost/src/front/fmt.dawn:29`；未知字符不产生 token：`selfhost/src/front/lexer.dawn:777`；token 之间的原始 gap 不会重印：`selfhost/src/front/fmt.dawn:117`；CLI 随后无条件写回：`selfhost/src/main.dawn:1377`；LSP 返回整文件 replacement：`selfhost/src/lsp/server.dawn:942`。
- **边界：** `1 \ 2` 会被格式成 `1 2`；`let a = 1; let b = 2` 会丢掉分号，变成另一份仍可能不合法、但已不可逆改写的文本。
- **冲突：** 规范只在“词法成功”时承诺 token-preserving：`docs/spec.md:150`，实现却没有执行这个前置条件。
- **影响：** `dawn fmt` 与编辑器 format-on-save 可直接破坏用户源码；这不是排版差异。
- **建议：** `fmt.format` 返回 `Result[String, List[Diag]]`；任何词法诊断都让 CLI/LSP 拒绝产生编辑。另给 `fmt --unsafe-recover` 也不应原地写回。

## SYN-02 — P1 — 插值使用第二套、不完整的字符扫描器

- **证据：V。** `${...}` 的边界扫描只专门跳过双引号字符串：`selfhost/src/front/lexer.dawn:391`、`selfhost/src/front/lexer.dawn:421`；Char 与 raw string 分别由另一套逻辑处理：`selfhost/src/front/lexer.dawn:486`、`selfhost/src/front/lexer.dawn:565`。
- **边界：** `"${'}'}"` 会过早把 `}` 当作插值结尾；包含 raw-string delimiter 的合法表达式同样失效。扫描器还在 `selfhost/src/front/lexer.dawn:406` 无条件拒绝跨行。
- **冲突：** 规范称普通与三引号字符串的 `${expr}` 接受表达式：`docs/spec.md:119`、`docs/spec.md:131`，没有列出 Char/raw/multiline 例外。
- **影响：** 词法形式不能正交组合；每加一种 literal/comment 都要再改一份脆弱扫描器。
- **建议：** 以真实 lexer token 驱动 brace depth，统一跳过普通字符串、三引号、raw string、Char 与 comment。若保留单行限制，必须在规范中明确，并让三引号行为一致。

## SYN-03 — P2 — 返回函数的函数无法直接标注外层效果

- **后续处置（2026-08-09）：已修。** 类型 parser 现在用逗号决定 tuple：`(T)` 返回内部
  `TypeRef`，`(A, B)` 保持 tuple，`(T,)` 与 `()` 继续拒绝；没有增加 `TParen`，箭头仍右结合。
  因而 `fn() -> (fn() -> Int) !io` 表示“外层 `!io`、内层纯”，原写法
  `fn() -> fn() -> Int !io` 仍表示“外层纯、内层 `!io`”，双层效果也可逐层书写。
- **渲染闭环：** `ty_show`、`sig_render`、impl mismatch / missing-method 两处诊断，以及局部
  函数补写 `!io` 的迁移 hint 共享 `fn_return_show`：仅当外层非纯且返回类型为函数时加括号，
  不给参数、泛型实参或普通返回类型制造无意义括号。全仓穷举 `->`、`ty_show`、
  `eff_suffix` 与手写 `!io` 的组合后没有同类 renderer 残留；诊断、文档、check dump 与 LSP
  共用的显示结果均可按原语义回读。
- **合同：** parser 结构测试固定外纯内效、外效内纯、双 effect 与 `(Int)`；grammar corpus
  固定 grouping 正例及 `(Int,)`、`()` 反例；checker 单测固定解析后的 `Sig` 与显示结果，
  checker corpus 同时覆盖 passes 中两条手写 impl 签名诊断与真实局部函数的 `!io` hint。
- **裁决：** 采用兼容性的 grouping 方案；不迁移到 `fn() !io -> T`。后者会让函数类型与
  具名函数声明重新分叉，或迫使全仓迁移，解决同一消歧问题却引入更大的破坏面。

## SYN-04 — P2 — or-pattern 不是 Pattern，规范承诺也未实现

> **当前静态候选（未验证，不改严重度）：** `lower_match` 在 `for p in arm.pats` 内分别
> lowering 同一 arm 的 guard：`selfhost/src/ir/lower.dawn:2882`、`:2897`。若多个 alternative
> 对同一 scrutinee 同时匹配，前一个 guard 返回 false 后还会尝试后一个 alternative，effectful
> guard 因而可能重复求值。这里只记录 R-AUDIT 的静态候选；没有运行探针，也不把本项从冻结
> P2 提升为 P0/P1。修 `POr` 时必须把“一个 arm 的 guard 最多求值一次”写入 contract。

- **证据：V。** 规范允许 alternatives 绑定同名同类型变量：`docs/spec.md:912`；checker 却拒绝任何带绑定的 alternative：`selfhost/src/check/checker.dawn:6339`。parser 只在 match arm 顶层收集 `|`：`selfhost/src/front/parser.dawn:2252`。
- **边界：** `A(x) | B(x) -> x` 同时得到“不得绑定”和重复绑定诊断；`Some(0 | 1)` 不能作为嵌套模式。
- **影响：** 规范与实现直接冲突，且 AST 让正确实现绑定集合合并更困难。
- **建议：** 增加 `POr(List[Pattern])`；分支各自检查后比较 binding name/type 集合，最后只向 arm scope 引入一次。

## SYN-05 — P2 — pipe 仍绑定旧调用 AST 形状

- **证据：S。** pipe 只接受 `EApply(EVar)`、裸 `EVar` 或 lambda：`selfhost/src/front/parser.dawn:1251`；一般 postfix application 已在 `selfhost/src/front/parser.dawn:1567` 落地。
- **边界：** `x |> Some`、`x |> Some(1)`、`x |> list.fold(...)`、`x |> sink.put()`、`x |> make()(1)` 都不能按普通调用模型工作。
- **影响：** 构造器、模块限定函数、方法和函数值在 `()` 中是一等 callee，在 pipe 中却不是；库无法围绕统一的“首参数数据”API 设计。
- **建议：** pipe 对任意 RHS 形成 application；若 RHS 最外层已经是 call/method call，则插入第一个参数，否则形成 `rhs(left)`，可调用性完全交给 checker。

## SYN-06 — P2 — formatter 仍假设只有标识符可调用

- **证据：V。** 过时假设写在 `selfhost/src/front/fmt.dawn:273`；callee-ending token 枚举遗漏 `BANG`、`RBRACE` 等：`selfhost/src/front/fmt.dawn:275`；`!` 只靠下一 token 判断 effect/unwrap：`selfhost/src/front/fmt.dawn:55`。
- **边界：** 合法的 `o!(x)` 被写成 `o !(x)`，`{ f }(x)` 被写成 `{ f } (x)`。
- **影响：** parser 已一般化，官方 formatter 却把新组合排成旧语法的视觉形状，增加阅读歧义并持续要求枚举补丁。
- **建议：** 让 formatter 消费 parse tree；短期也应抽象“postfix chain”，而不是枚举能结束 callee 的 token。

## SYN-07 — P2 — formatter 丢掉换行后才判断一元负号

- **证据：V。** formatter 的 code-token 列表先过滤所有 NEWLINE：`selfhost/src/front/fmt.dawn:31`；一元/二元判断只看前一个 code token：`selfhost/src/front/fmt.dawn:42`；结果参与缩进：`selfhost/src/front/fmt.dawn:204`。
- **边界：** 块内一条 `let _ = g()` 后的新语句 `-1` 会被排成缩进更深的 `- 1`，看起来像上一行的减法续行。
- **冲突：** 规范明确行首 `-` 不续接上一行：`docs/spec.md:144`。
- **建议：** 在原始 token 流上分类；遇 NEWLINE 重置 prefix context，再做 spacing/indent。

## SYN-08 — P2 — `Int.MIN` 没有直接字面量

- **后续处置（2026-08-09）：已修。** INT token 现在用专用 marker 表示精确 magnitude
  `2^63`，十进制、十六进制与二进制共用先验 digit、再负值累加的无溢出 parser；非法数字、
  精确 marker 和越界分别落到不同结果。表达式与 pattern 只在直接 `MINUS + marker` 时折成
  普通 `EInt(Int.MIN)`，裸 marker 与括号隔开的写法带固定 hint 拒绝，折叠结果仍进入统一
  postfix tail。C emitter 的 `CInt`/`VInt` 共用 `int_lit`，最小值只输出 `INT64_MIN`。
  parser/lexer 单测、绝对 grammar corpus 与 JVM/native/C 专项 contract 固定这些边界；
  放行裸 marker、放宽精确边界、混淆 invalid/overflow、绕过 postfix tail、退回错误 C 宏
  拼写五类负控均已实跑见红后恢复。

- **证据：V。** lexer 先把 magnitude 当正数并限制 64 位：`selfhost/src/front/lexer.dawn:278`；parser 后续才构造 unary minus：`selfhost/src/front/parser.dawn:1489`。
- **边界：** `-9223372036854775808` 与 `-0x8000000000000000` 都在 magnitude 阶段越界，尽管它们是合法 Int 值。
- **影响：** 基础类型有一个值不能直接用于 const、pattern 和边界测试，只能写成 `-9223372036854775807 - 1`。
- **建议：** lexer 保留 unsigned magnitude；unary fold 允许“负号 + MAX+1”这一个特例，其他正 magnitude 仍报越界。

## SYN-09 — P2 — 大写 Java member 被 parser 预判为字段

- **证据：S。** `.` 后 `TYPEIDENT` 无条件生成 `EFieldAcc`：`selfhost/src/front/parser.dawn:1532`；只有小写/keyword 路径形成 `EMethod`：`selfhost/src/front/parser.dawn:1539`；checker 随后按静态字段处理：`selfhost/src/check/checker.dawn:3443`。
- **冲突：** interop 规范称成员名可为任意 word：`docs/spec.md:1252`。Java 允许大写方法名。
- **影响：** Java API 可访问性依赖命名风格；`x.UPPER()` 被解析成“调用字段值”而不是方法调用。
- **建议：** parser 生成统一 member reference；checker 根据 receiver type、是否随后 application 及 Java metadata 决定 field/method。

## SYN-10 — P2 — match arm 可由纯空白分隔

- **后续处置（2026-08-09）：已修。** parser 已删除 `can_start_pattern` 与零宽邻接；相邻臂
  现在只接受物理换行或逗号，逗号后可换行且允许尾逗号。缺分隔符有固定诊断；恢复从坏臂
  起点重扫并分别追踪 `()`、`[]`、`{}`，只在当前 match 顶层边界停止。绝对 grammar
  corpus 同时钉住接受、拒绝与恢复，并以恢复旧邻接、破坏嵌套恢复两项负控证明会红。

- **证据：V。** parser 在没有 newline/comma 时，只要下一个 token 看起来像 pattern，就直接开始下一 arm：`selfhost/src/front/parser.dawn:2183`、`selfhost/src/front/parser.dawn:2229`。
- **边界：** `match x { 0 -> 1 1 -> 2 _ -> 3 }` 可解析；若下一 pattern 以 `[` 或 `(` 开始，它可能被上一 body 吞成 index/application postfix。
- **影响：** 分隔是否成功取决于下一 pattern 的首 token和当前 expression postfix 集；新增 pattern/postfix 还可能改变旧代码 parse。
- **建议：** 破坏性要求 NEWLINE 或 `,` 分隔 arm，并为缺分隔符提供专门诊断。

## SYN-11 — P2 — parser 复制 builtin type 表且已经漂移

- **证据：V。** `type`/`alias` 误写提示只硬编码五个 scalar：`selfhost/src/front/parser.dawn:452`；checker 的真实 builtin 表包含 `Char`、`Bytes`：`selfhost/src/check/types.dawn:337`。
- **边界：** `type Letter = Char` 被解析成含 nullary constructor `Char` 的 ADT，最后报 constructor collision，而不是建议 `alias Letter = Char`。
- **影响：** 每加 builtin 都要同步 parser/checker；遗漏改变 AST 和诊断，而不仅是少一个 hint。
- **建议：** 移除 parser 的语义猜测，在 checker 的唯一 type registry 上生成 alias hint；或提供 front/check 共享的 generated inventory。

## SYN-12 — P2 — declaration recovery 遗漏 contextual `opaque`（已由 `38f625a` / `24d5d2f` 处置）

> **后续处置（2026-08-09）：已修。** `classify_top_decl` 以 typed declaration-head
> classifier 同时驱动正常 dispatch 与 recovery，不再维护 hard-token 双表；完整
> `opaque type` / `pub opaque type` 归为 `HOpaqueType` 恢复锚点，使扫描停在 `opaque`，不会
> 跳过它后从内部 `TYPE` 把声明误解为普通 type/alias。非法 contextual 拼法 `HBadOpaque`
> 则明确不是 recovery anchor：扫描会继续，并可在随后真正的 `fn` 等声明头恢复，避免在
> 无效 `opaque` 处额外停一次并产生级联 opaque 诊断。parser tests 覆盖直接与恢复后的
> `pub opaque type`、全部顶层声明头，以及 malformed `opaque` 后继续恢复且只保留原始
> 诊断；grammar corpus 固定坏声明后仍保留 opaque declaration。
> `scripts/syntax-small-contract/run.sh` 还会复制私有 selfhost、删除 `HOpaqueType` recovery
> anchor，先要求 mutant 成功编译，再要求 owning parser test 转红。
> Core 记录中 normalized 变化仅有 `front.parser`；exact 另见 `driver.analyze` 与
> `pkg.manifestv`，二者是全局 ID 漂移，不是本刀新增行为面。

- **证据：V。** `sync_decl` 声称与 `top_decl` anchors 一致，但只认硬 token：`selfhost/src/front/parser.dawn:174`；`opaque type` 实际由 `IDENT("opaque")` 特判：`selfhost/src/front/parser.dawn:199`。
- **边界：** 前一坏声明后跟 `opaque type UserId = Int`，恢复会跳过 `opaque`，从 `type` 重启，并把后续合法声明误报成 alias 误写。
- **影响：** 一个早期错误改变后续声明含义并制造级联诊断。
- **建议：** 抽出 `starts_top_decl`，dispatch 与 recovery 共用；识别 contextual token 序列而非只看 enum。

## SYN-13 — P2 — `for` 不接受不可反驳 pattern

- **证据：S。** parser 在 `for` 后只接受 IDENT：`selfhost/src/front/parser.dawn:1215`；`let` 已支持不可反驳 pattern，规范也已有 refutability 规则：`docs/spec.md:921`。
- **边界：** 遍历 pair/entry 不能写 `for (k, v) in entries`，必须先绑定临时值再解构。
- **影响：** sequence iteration 与同语言的 binding grammar 不正交，尤其伤害 Map/zip API。
- **建议：** `for` 接受不可反驳 pattern；可反驳 pattern 在循环头给针对性错误，避免静默跳过语义。

## SYN-14 — P2 — lambda 有一个只在尾调用位置复活的 `fn` 方言（已由 #206 处置）

- **后续处置（2026-08-09，#206 期 2）：已选择统一 delimiter 方案。** 现行语法以
  `{ x => e }` 尾块作为唯一尾实参形式，`fn` 不再有表达式位置。以下内容保留 v0.60.0
  审查基线的证据与当时建议，不把历史改写成“从未存在”。

- **性质：D。** 普通 lambda 的 `fn` 前缀已退休：`docs/spec.md:720`；尾闭包却必须写 `f(a) fn(x) => e`：`docs/spec.md:611`，裸 `(x) => e` 在这里被专门拒绝：`selfhost/src/front/parser.dawn:1581`。
- **理由虽存在：** `f(a)(x)` 已是 curried application，所以 `(x) => e` 与第二次调用有冲突。
- **问题：** 同一个 lambda 根据位置改变词法前缀；`fn(x) => e` 在 standalone/argument 位置非法、紧跟 call 时又是唯一合法拼写。教程、formatter、TextMate 与 parser 都要维护例外。
- **建议：** 早期语言应在两案中选一：删除尾闭包糖，统一写 `f(a, x => e)`；或采用不会与 application 冲突、且明确表示 block argument 的统一 delimiter。不要保留“退休关键字只在一个位置复活”。

## SYN-15 — P2 — VS Code TextMate grammar 已落后于语言

- **后续处置（2026-08-09，二审纠偏后）：已修。** 官方 grammar 已覆盖当前 Unicode
  identifier（part 精确到 `Nd`）、raw/普通/三引号字符串、Char、两种插值、十六/二进制/
  指数数字、range、`!Ask`、`!(io)`、`!(Ask)`、effect union，以及完整 operator token 集。
  interpolation 使用不含 comment 的 code pattern，因此 `${x # local }` 中 `#` 不会吞掉
  `}` 与同行后续。contract 从 `selfhost/src/front/token.dawn` 提取当前 29 个 hard keyword，
  从 `TokKind` 与 `selfhost/src/front/lexer.dawn` 的 operator 表提取当前 30 个拼写；二者都与
  grammar 的结构化 inventory 双向精确对账，再逐项交给真实 `vscode-textmate` +
  `vscode-oniguruma` tokenization 验 scope。`java` 继续按硬 token 检查；contextual inventory
  精确固定为 `opaque`、`as`、`derive`、`handle`，并同时固定语法位置、普通标识符位置及
  `bogus` 非关键字。依赖以精确版本写入 package 与 lockfile，CI 使用独立 editor grammar
  job。scope corpus 共 8 组、152 项 scope 断言；另对 15 组 operator prefix-overlap 逐对要求
  长项排在短项之前，总计 167 项。hard 漏项/多项、contextual 漏项/多项、三引号、braced
  interpolation、interpolation comment 边界、括号单 effect、Unicode `Nd` 边界、指数数字、
  operator 漏项，以及 metadata inventory 与 regex 同步把短项前置，共 12 项持久负控均已
  实跑见红后恢复。
- **残余边界：** TextMate 是词法着色器，不承担 parser 合法性判断；除 hard keyword 外的
  token 形状仍由 grammar 表达式维护，但现在由真实引擎语料约束，不再以 grep 代替行为测试。
  仓内历史 `dawn-lang-0.1.0.vsix` 未在本刀重打包；发布扩展时仍须从当前源码重新 package。

- **证据：S。** keyword 缺 `effect` 却全局高亮 contextual `derive`：`editors/vscode/syntaxes/dawn.tmLanguage.json:24`；effect 规则不识别 `!Ask`/union：`:42`；无 Char/triple string：`:52`；number 漏 `2e3`：`:69`；identifier 只认 ASCII：`:77`；operator 漏 `! & | ^ ~ @`：`:94`。
- **影响：** 官方编辑器错误高亮当前有效源码；语言越快演进，手抄 grammar 越不可信。
- **建议：** 从 lexer token/keyword inventory 生成大部分 TextMate 规则；至少增加一份包含每类当前 token 的 snapshot fixture。

## SYN-16 — P3 — 裸 `return` 的终止符遗漏 `]`

- **后续处置（2026-08-09，`79df07f` / `60e174a`）：已修。** parser 新增专用
  `is_bare_return_boundary`，只在既有 NEWLINE、`}`、`)`、`,`、EOF 边界上补入 `]`；没有把
  colon、arrow 纳入，也没有把不同 production 的停止集合泛化成通用 expression terminator。
  parser test 与 grammar fixture 精确覆盖 `(return)`、`[return]`、`f(return)`、
  `(return, 1)`、`{ return }` 五种语法形状；`fn wrong() -> Int = [return]` 仍由 checker 的
  return-type 规则拒绝。与 `SYN-12` 共用的 `syntax-small-contract` 同时固定两项边界；
  `drop-rbracket-return-boundary` mutant 在私有 selfhost 中先成功编译，再由 owning test
  `bare return stops at every delimiter boundary` 转红。normalized Core 仅 `front.parser` 改变。
- **方案裁决：** 原建议中的“统一 expression-terminator predicate”未采用；专用 exact
  predicate 既消除 `return` 分支内的散落条件，也不把本 production 的边界误推广到其他语法。
- **证据：V。** parser 只把 NEWLINE、`}`、`)`、`,`、EOF 当裸 return 边界：`selfhost/src/front/parser.dawn:1647`。
- **边界：** `(return)` 可解析，`[return]` 却在 `]` 报 expected expression。
- **冲突：** 规范把 `return` 定义为 `Never` expression，可出现在表达式位置：`docs/spec.md:843`。
- **原建议：** 加入 `RBRACKET`，并用统一的 expression-terminator predicate 避免下一种容器再漏；
  前半已落地，后半因不同 production 的停止集合并不相同而明确拒绝。

## SYN-17 — P3 — `java` 是全局硬关键字

> **后续处置（2026-08-09）：维持 open，但归 D/P3 关键字预算设计项。** 当前 parser、规范与
> TextMate grammar 对 hard keyword 身份一致，没有实现 bug；是否为 `java` 归还普通标识符空间
> 是早期语言可做的破坏性表面设计。它不进入自治小刀；只有在统一 contextual-keyword 方案中
> 裁决，且必须同时迁 lexer/parser/formatter/editor inventory。

- **证据：S。** `java` 在 token 表中全局保留：`selfhost/src/front/token.dawn:200`，特殊含义却只存在于 `use java`。
- **影响：** 用户不能把自然名称 `java` 用作局部、字段或模块 alias；关键字预算被一个上下文语法永久占用。
- **建议：** 降为 `use` 后的 contextual keyword；lexer 产普通 IDENT，parser 在 import position 判别。

## SYN-18 — P3 — range 的官方格式没有单一答案（已由 `cb2c061` 处置）

- **后续处置（2026-08-08，`cb2c061`）：已采用紧凑 `a..b`。** formatter 仅在 `..`
  左侧是 value end 时收紧左空格，spread/rest 前缀仍保留开括号或逗号要求的空格；规范、
  示例与 formatter 内嵌边界测试已同步。以下内容保留 v0.60.0 审查基线的原始证据与建议。

- **证据：V。** formatter 只禁止 `..` 后空格，没有禁止前空格：`selfhost/src/front/fmt.dawn:228`，因此 `0..3` 变成 `0 ..3`；规范和教程普遍写 `a..b`：`docs/spec.md:769`、`docs/tutorial.md:243`。
- **影响：** formatter、文档与 grammar corpus 对 canonical spelling 不一致。
- **建议：** 选择并机器化一条规则。建议使用紧凑 `a..b`；若保留 `a ..b`，规范和教程必须同步。

## SYN-19 — P3 — normative declaration inventory 不完整（已修）

> **后续处置（2026-08-09）：已修。** 双语规范的关键字、顶层声明、两处 visibility 与
> syntax cheat sheet 已统一补入 `opaque type`、`trait`、`impl`、`effect`、`pub trait` 与
> `pub effect`；`doc-check` 对这些稳定 inventory 做防回退检查。

- **证据：S。** 顶层声明清单漏 `effect`：`docs/spec.md:351`；`pub` 清单漏 `trait` 与 `effect`：`docs/spec.md:399`、`docs/spec.md:1674`；contextual keyword 清单漏 `opaque`：`docs/spec.md:68`。parser 实际支持 `pub trait`、`pub effect` 与 `opaque type`：`selfhost/src/front/parser.dawn:199`、`:217`、`:805`。
- **影响：** 规范内部不同章节给出不同语法集合，读者无法从总览推导有效表面语法。
- **建议：** 由 lexer/parser 的 inventory 生成或检查规范表格；不要继续人工同步三份关键字/声明清单。
