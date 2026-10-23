# parser 恢复：语句同步、就地补逗号、头部记录字面量与未闭合括号

> 状态：**current**。2026-09-30，诊断批 P1，issue #190 #192 #193 #195（第 1 步），分支 `fix/diag-parser-recovery`。
> 2026-10-20 追加 §5′（两段式重解析，#789 残差），分支 `front/two-pass-recovery`。
> 2026-10-20 追加 §6（受损与丢失标记，解析错误线刀 1），分支 `front/damage-marks`。
> 刀 2（检查器按这些标记检查未受损声明的函数体）记在 `docs/lsp-module-memo-design.md` §十四。
> 裁决与其它语言实例见调研报告 `research-diagnostics-issues-20260930.md` §3 §5 §6 §7（不在仓内）；本文记做法、取舍与负控；四刀均已实现（提交见文末）。

只动 `selfhost/src/front/parser.dawn` 与 `scripts/grammar-corpus/`。只改**无效输入**的诊断：
每条新分支都长在今天已经报错的路径上，合法程序的 AST、诊断与输出不变，spec 不改。

## 1. 语句级同步按括号深度（#190 #192 的假顶层错）

**根因**：`sync_stmt` 从**失败点**往前扫到第一个 `NEWLINE`/`}`/EOF。失败点在语句内的花括号里时
（`let p = P { x = 1 y = 2 }`），第一个 `}` 是字面量自己的，`block_body` 把它当成块尾，
函数体的 `}` 于是留给下一行，后面的语句落到顶层，报「only declarations … at module top level」。

**做法**：照 `sync_arm`，从**语句起点**按 `() [] {}` 深度扫：

- 深度为 0 的 `NEWLINE` 停，但只在已经走过失败点之后（语句可能合法地跨过顶层换行，
  例如 lambda 体 `x =>` 后的 `skip_nl`；在失败点之前停会把已读过的 token 再解析一遍）；
- 不配对的 `}` 停（它是外层块的）；
- 扫到 EOF：退回旧的「从失败点扫到换行/`}`」。真没闭合的 `{` 不应让一条语句吞掉全文件。

## 2. 缺逗号就地恢复（#190）

记录字面量、实参表、元组、列表字面量四处：一项之后若**同一行**（没有被跳过的换行）紧跟着
能开始下一项的 token，报软诊断并当作有逗号继续，不再 `Err` 出整个表达式：

| 位置 | 触发 | 诊断 |
|---|---|---|
| `record_lit` | 下一个是 `IDENT` 且其后为 `:` `,` `}`（字段起点） | ``expected `,` or `}`, found `y` ``，hint 点名缺逗号 |
| `call_args` | 下一个能开始表达式（字面量、名字、`true`/`false`/`not`） | ``expected `,` or `)` `` |
| `paren_expr` 元组 | 同上 | ``expected `,` or `)` `` |
| `list_lit` | 同上 | ``expected `,` or `]` `` |

「能开始下一项」刻意比 `starts_expr` 窄：`(` `[` `{` `-` 在一个表达式后面本来就是后缀或二元运算，
走到这里说明别的规则拒绝了它们，猜成缺逗号只会造出第二条错。记录字面量要求同行之外还放宽到跨行，
因为记录字面量里换行不是分隔符，`P {\n x: 1\n y: 2 }` 缺的也是逗号。

## 3. 头部的记录字面量（#192）

`if`/`while`/`for` 头与 `match` 被检查式里（`nb` 开关），`P {` 的花括号属于体（spec §4.3 尾块边条件 2），
规则不动。`ctor_expr` 在 `nb` 为真、`{` 后是 `IDENT :` 或 `..` 时，报软诊断
``a record literal here needs parentheses``，hint 给出 `(P { ... })`，锚在整个字面量，然后**照记录字面量解析**继续。
`{ x }` 简写不判：`if a == B { x }` 是合法的「构造器值 + 体」。措辞与做法以 rustc 的
「struct literals are not allowed here / surround the struct literal with parentheses」为范本。

诊断不点名 `if`/`while`/`for`/`match`：那要把头部种类随 `nb` 一路传下去，改四个调用点和所有转发 `nb` 的函数签名；
hint 里写全四种即可，信息量相同。

## 4. `=` 与 `..` 落到语句分隔符（#193）

`stmt_and_sep` 在 `want_sep` 失败时看当前 token：

- `=` 且语句是表达式语句：`only a variable can be assigned`，hint 按左侧分三型（下标、字段、其它），
  给改法（`m = map.insert(m, k, v)`、`r = R { ..r, f = v }`）；
- `..`：``` `..` is not an expression operator ```，hint ``a range `a..b` only appears in a `for` header: `for i in a..b { ... }` ``（spec §4.7、§4.11）。

## 5. 未闭合的括号报在开括号（#195 第 1 步）

`parse_module_lexed` 在解析有诊断时（干净的解析不付这趟代价）对 token 流做一遍括号配对预扫。
EOF 处仍有未闭合的开括号、且全程没有错配的闭括号时：

1. 嫌疑开括号用 rustc 的缩进启发（`rustc_parse/lexer/diagnostics.rs` 的 `report_suspicious_mismatch_block`）：
   配对成功但开、闭所在行缩进不同的那些对里，去掉被缩进一致的外层对包住的，取开括号最靠后的一对；
   另加一条 rustc 没有的限制：只看最外层未闭合开括号之后的对（之前的对不可能吞掉它的闭括号）。
2. 没有嫌疑对时取最内层未闭合者。
3. 主 span 放在嫌疑开括号：``unclosed `{` ``，hint 写出 EOF 的行号与配错的那个闭括号的行号。
   （#195 第 2 步之后这两个位置改为 note，hint 只留结论，见 [diag-notes-design.md](diag-notes-design.md) §6。）
4. 原来落在 EOF 的诊断（``expected `}`, found `<eof>` ``）**删除**，新诊断按源码位置插入（排在第一条位于开括号之后的诊断前面）。
5. 没有 EOF 诊断时，说明解析自己恢复了（`sync_decl`）。若开括号所在行已经有诊断（`fn f( = 0`），
   那条讲的是同一个错、作者也已经看着对的行，不加；只有解析越过了开括号所在行、错报在别处时
   （未闭合的 `[` 里换行不算分隔，下一条声明被当元素读）才补这一条。这条限制是实测逼出来的：
   不加它，`declaration_recovery_opaque`、`unterminated_param_list` 两个 reject 例和 parser_test 的三条
   opaque 恢复测试各多一条「unclosed `(`」噪声。

EOF 诊断选择删除而不是叠加：`Diag` 只有一个 span，两条诊断讲同一个原因只是噪声；它唯一的信息
「解析读到了文件尾」已经写进 hint。次级 span（`Diag.notes`、渲染 `note:` 行、LSP `relatedInformation`）
是基础设施改动，另立项（#195 第 2 步，#198 的「续行于此」也等它）。

## 5′. 未闭合的块：两段式重解析（#789 残差，2026-10-20）

§5 只**定位**未闭合的开括号，不改恢复：内层块吃掉函数的 `}` 之后，函数体的 `block_body`
一路读到文件尾，后面每个列 0 的 `pub fn`/`test` 都作为坏语句被 `sync_stmt` 吞掉（各报一条），
私有 `fn name(` 作为局部函数被**合法地**吞掉、一条诊断都没有；最后整个 decl 被 `sync_decl` 丢掉。
LSP 打字回放里，这一类是 #789 在 P3（#799）之后的全部残差：check/types 51 个态、front/ast 21 个态，
被编辑文件每态丢 212/283、50/71 个 decl，导入者跟着报 2928/3068 条诊断（数据见调研
`research-lsp-parse-recovery-20261019.md` §三、P3 报告 §五，均不在仓内；裁决 `ruling-lsp-parse-recovery-20261019.md`）。

**做法**（照 gopls `parsego.Parse` 的 `fixSrc`：有解析错误时改写输入、重解析，原始错误另行保留；
出处 https://go.googlesource.com/tools/+/HEAD/gopls/internal/cache/parsego/parse.go ）：

1. 第一趟照旧。只有它**以 EOF 处仍有未闭合括号结束**时才进第二趟：解析有诊断，其中有一条落在 EOF 的
   ``found `<eof>` ``（与 §5 判「解析读到了文件尾」的条件同一个），括号配对预扫没有游离闭括号，
   且 EOF 处配对栈非空。
2. 恢复点：配对预扫顺带记下每个**列 0** token 处的配对栈。一个 token 是恢复点，当且仅当它是列 0 的
   声明头（`starts_top_decl`：`fn`/`type`/`alias`/`const`/`trait`/`impl`/`effect`/`use`/`test`/`pub …`/`opaque type`/`ctl effect`，
   以 lexer 的列与关键字为准），并且此刻栈里**只有**到 EOF 都没闭合的开括号——跨过它的已配对括号说明
   这一行在某个闭合的块里（未格式化代码），不是恢复点。每个恢复点给栈里还没分到闭括号的开括号补闭括号，
   由内向外，插在声明头这个 token 之前（声明头前面的空行 NEWLINE 不动）。在最后一个恢复点之后才打开的
   开括号不补：那是文件尾在打字，今天本来就不吞别的 decl。
3. 合成闭括号是零宽 token，`lo = hi =` 声明头的起点，所以 token 流的位置仍有序（`note_cut_openers` 的二分查找依赖它）。
   代价是被救回的块的 span 延伸到下一个声明头之前（含其间空行与文档注释），只在坏文件上出现。
   合成括号**不出现在任何输出文本里**：`parse_module_lexed` 返回的 token 流是第一趟的原样（LSP 的语义高亮、
   折叠读它），源码码点不变，`fmt` 只依赖 lex 不读 AST；解析器报「found X」时若 X 是合成括号，
   说成 `the start of the next declaration`，不说 `` `}` ``。
4. 第二趟用补过的 token 流从头重解析一次（不循环：每个开括号最多补一次，补完不会产生新的未闭合者），
   AST 与诊断都取第二趟的。表头保留：被编辑的 `pub fn` 只要体内能被 `sync_stmt` 局部恢复，就留在 AST 里，
   P3 之后它的面与上一轮相同，导入者早截断。

**诊断**：每个恢复点一条 ``unclosed `{` ``，按源码位置插进第二趟的诊断里：

- 主 span 用 §5 的缩进启发在「本组最外层开括号之后、恢复点之前」的配对里选嫌疑开括号；没有嫌疑时取本组最内层的开括号。
  hint 与 §5 相同。
- note：有嫌疑时先是「this `}` closes it but is indented differently …」（同 §5）；最后一条
  ``expected `}` before this declaration``，落在恢复点的声明头上，替代 §5 的「before the end of the file」。
- 被吞的成串 ``expected an expression, found `pub` `` 消失；被当成局部函数吞掉的列 0 私有 `fn` 本身就是恢复点，
  回到顶层，指向未闭合 `{` 的诊断就是上面这条。第二趟自己的诊断（被编辑函数里打字中途的局部错）照常保留。

**为什么必须两段**：Dawn 允许块里的局部 `fn name(...)`（`local_fn_stmt`），`test` 是上下文关键字，
未格式化的合法代码里列 0 的 `fn` 可以在块里。「列 0 声明头即结束块」若做成单趟规则，会改变合法程序的解析，
等于改 spec。两段式下，能被第一趟完整解析的程序没有诊断，按构造不进第二趟，AST、诊断、输出逐字节不变；
第一趟有诊断但没跑到 EOF 的程序（`fn f( = 0` 由 `sync_decl` 自己恢复）也不进。

**代价**：干净的解析一分不付；有诊断但不进第二趟的多一次配对预扫（§5 本来就扫，现在并成一次）。
进第二趟的多一次整文件解析（不重新 lex），实测见文末「落地」。

## 6. 受损与丢失标记（解析错误线刀 1，2026-10-20）

动机：裁决 `ruling-parse-error-bodies-20261020` 采 B，解析出错的模块只检查**未受损**声明的函数体。
判断「哪些声明受损」不能靠位置：§5′ 补的闭括号是零宽 token，`lo = hi =` 下一个声明头的起点，
「声明的 span 触到恢复位置就算受损」会把紧跟其后的那个完好声明误判成受损。所以由解析器在恢复动作发生的那一刻
记到当前声明上，本刀只产出标记，**不改 `analyze` 检查什么**（那是刀 2）。

**定义**

- **受损（damaged）**：声明的范围内发生过恢复，因而它的树是解析器的猜测而不是作者写的。包括
  - 第二趟补的合成闭括号被这个声明消费了（§5′）；
  - 语句级同步（`sync_stmt`）、match 臂同步（`sync_arm`）；
  - 表达式级恢复：就地补的逗号（`missing_comma`）、报错后照记录字面量解析的头部字面量（`header_record_lit`）、
    字符串插值里 lexer 报了错；
  - lexer 丢弃或替换了声明所在行里的字符（stray 字符、坏字面量），token 流里已看不出，只剩它的报告。
- **丢失（lost）**：`sync_decl` 放弃的那段源码里本来有声明头，即树里缺了一个本该有的声明，它引入的名字不在了。
  放弃点自己的头（失败的那个声明）也算；落在顶层的杂散文本（`top_decl_error`，不是声明头）不算。
  `lost` 是模块级一个布尔，丢了的声明没有树，无处可挂声明级标记。

**记在哪里**：`ast.dawn` 的旁表 `ParseMarks = { damaged: List[Bool], lost: Bool }`，`damaged[i]` 对应 `Module.decls[i]`。
旁表不放进 `Module`：`Module { decls }` 在 checker 测试与 `apply_rewrites` 里被构造二十来处，
放进去要动所有消费者，而本刀的要求是合法程序的其它字段一概不变。`parse_module_marked` 返回它，
`parse_module` / `parse_module_lexed` 的签名不变。`astdump` 不输出标记，所以 `__parse` 的字节不变，不需要 `Emit-Change`。

**机制**（都是恢复动作发生时记下的事件，不是事后比对位置）

- 解析状态 `St` 多一个计数 `repairs`：`sync_stmt`、`sync_arm`、`missing_comma`、`header_record_lit` 成功分支、
  插值里 lexer 有报告时各加一。`parse_decls` 读完一个声明后比较它开始前后的计数，不同就受损。
  计数随状态流动，被丢弃的试探分支的状态连同计数一起丢弃。
- 合成闭括号：看这个声明**消费的 token** 里有没有零宽闭括号（`lo == hi` 且是闭括号，源码里没有空 token）。
  它是看 token 的身份，不是看它在哪里，所以紧跟其后的声明头不受牵连。标记取第二趟的，和第二趟的树配套。
- lexer 的恢复：lexer 丢字符，没有 token 可看，只能用它的报告。报告归属于其位置落在声明首 token 到收尾换行之间的那个声明。
  这是唯一用到位置的一条，因为 lexer 报告的 span 是真实源码、边界没有零宽歧义。
- 丢失：`parse_decls` 在 `Err` 分支调用 `sync_decl` 之后，检查放弃的起点是不是声明头（`classify_top_decl`），
  以及被跳过的 token 里有没有 `starts_top_decl`。

**合法程序**：没有诊断就没有恢复动作，计数不动、没有合成 token、lexer 没报告，标记按构造全是不受损、不丢失；
`parse_module_marked` 的测试与全仓扫描（含 grammar-corpus 的 accept）实测印证。

**别人怎么做的**

- rustc：解析器恢复出的块带标记，类型检查不拿恢复出的块的类型去和期望类型比较，不报级联类型错
  （rust-lang/rust#46732 *Do not emit type errors on recovered blocks*，https://github.com/rust-lang/rust/pull/46732 ；
  解析错误可恢复、继续后续阶段见 #56220）。标记来自解析器的恢复动作，粒度是被恢复的那一块，与本节一致；
  Dawn 的粒度放大到声明，因为声明是 checker 的检查单位。
- rust-analyzer：`full_diagnostics` 把语法诊断和语义诊断无条件拼接，推断里用 `TyKind::Error` 吸收，`has_errors` 记一个标记
  （`crates/ide-diagnostics/src/lib.rs`、`crates/hir-ty/src/infer.rs`）。它没有按声明打受损标记，靠缺失节点的错误类型传播压级联；
  Dawn 没有缺失节点那一套，所以采用 rustc 的「标记先行」做法。

### 不做的（理由）

- **按位置判受损**（声明的 span 触到恢复位置就算）：零宽合成闭括号会把下一个声明误判成受损；测试 `the declaration right after a made-up closer is not damaged by it` 与负控锁住这条。
- **把标记放进 `Module` 或 `Decl`**：要改所有构造点与消费者，而本刀不该动其它字段；旁表够用，刀 2 的 `analyze` 按下标取。
- **`astdump` 输出标记**：会改 `__parse` 的输出，要写 `Emit-Change`，而标记已有 `__marks` 和单测观察。
- **在本刀改 `analyze` 的检查范围**：刀 2。
- **记录恢复的种类或位置**：刀 2 只需要布尔；种类留给有人要的时候再加。
- **`lost` 做成按声明**：丢了的声明没有树，无处可挂；刀 2 只需要「模块里丢过声明」这一位。

## 验证

grammar-corpus 每个 issue ≥2 个 reject 用例，钉诊断序列；负控是把对应的恢复分支去掉，用例须红。
已有 reject 期望的变化逐条核对。selfhost、std、packages、examples 的 `dawn check` 诊断零变化。

## 不做的（理由）

- **次级 span**：见 §5，另立项；已由 [diag-notes-design.md](diag-notes-design.md) 落地。
- **头部诊断点名构造**：见 §3。
- **`f(0..3)` 这类实参位的 `..`**：走 `want` 的 ``expected `)` ``，与 #193 的语句位同源但不在验收里，
  且要在 `want` 里加上下文分支；留给真遇到的人。
- **List 的单元素更新 API**：#193 的 hint 只能指向重建或改用 Map；补 API 是 std 的事，另开 issue。
- **单趟规则（块里遇到列 0 声明头就结束块）**：改变「块里列 0 局部 `fn`」这类合法程序的解析，见 §5′。
- **只重解析被编辑 decl 起的尾部**：第二趟从头重解析更简单，且解析产物不必拼接；只有实测第二趟让坏文件的
  sync 超过 #789 的 2× 线才值得做（调研 §六的重开条件），实测没有超。
- **多轮修补（gopls 至多 10 轮）**：每个开括号的闭括号位置在第一趟的配对预扫里就定了，一轮补齐；
  第二趟若仍有未闭合括号，只可能是最后一个恢复点之后打开的，再补也没有恢复点可用。
- **`(`/`[` 内被 lexer 吞掉的换行**：补闭括号后不把换行补回来；第二趟在那段里的诊断可能比格式化后的代码多，
  但仍局限在被编辑的 decl 里。
- **沿用旧面（裁决的「甲」）**：裁决第 2 条否决，「增量 = 冷」不变。

## 落地

| issue | 提交 | 负控（去掉即红的 reject 例） |
|---|---|---|
| #190 | `Resync a broken statement by bracket depth and recover missing commas` | `sync_stmt` 直通旧规则：`stmt_recovery_nested_brace` 红（假顶层错回来）；关掉补逗号：三个新例全红 |
| #192 | `Report a record literal in a header and parse it as one` | `braces_hold_fields` 恒假：两个 `header_record_literal_*` 红（箭头/臂、分隔符/尾块连带回来） |
| #193 | `Name index assignment and a stray range instead of asking for a newline` | 两个新分支加 `false &&`：`assign_index_or_field`、`range_as_expression` 红（回到通用分隔符文案） |
| #195 | `Report an unclosed delimiter at its opener` | 跳过重定位：三个 `unclosed_*` 红（回到 `found <eof>`，或 `[` 那条消失）；关掉缩进启发：两个缩进例红（改点名最内层未闭合者） |
| #789 残差（§5′） | `Close blocks left open before the next declaration and parse again` | 去掉第二趟：parser_test 四条新测试与 `unclosed_brace_earlier_decl`、`unclosed_brace_swallowed_decls`、`unclosed_brace_typing_midway` 红；换成单趟规则（`block_body` 遇列 0 声明头即停）：「块里列 0 局部 `fn`」的合法程序报错，连带四个 reject 例红 |
| 解析错误线刀 1（§6） | `Mark each declaration the parser repaired and whether one was dropped` | 改成按位置判（声明 span 触到恢复位置即受损）：`the declaration right after a made-up closer is not damaged by it` 等红；`repairs` 不再递增：语句、臂、逗号三条红 |

### §5′ 的实测（2026-10-20，本机，loadavg 守卫 ≤ 4）

两把 jar：基线是 `890f9fcb`（含 P3），本刀是同一基点加本刀；工作区与打字态沿用 P3 报告（v0.94.0 源码，
服务端参数 `-Xss512m -Xmx2g -XX:+UseSerialGC`），`replay.py` 逐态 barrier 计时：

| 场景 | 合法态中位 | 解析失败态 中位 / p90 / 最大（基线） | 同（本刀） | 超合法态中位 2× 的态（基线 → 本刀） | 有导入者诊断的态 |
|---|---|---|---|---|---|
| T check/types | 170 / 147 | 326 / 427 / 1980 | **102 / 116 / 135** | 42 → **0** | 51 → 0 |
| C front/ast | 59 / 44 | 48 / 182 / 1035 | **37 / 44 / 49** | 21 → **0** | 21 → 0 |
| A driver/analyze | 81 / 82 | 73 / 81 / 87 | 76 / 82 / 93 | 0 → 0 | 0 |
| L lsp/lspc | 61 / 61 | 56 / 64 / 136 | 55 / 65 / 137 | 1 → 1（同一个态，不是未闭合类） | 0 |

72 个残差态（T 第 39–89、C 第 40–60）在本刀下全部解析出与参照合法态相同的 decl 数（T 283、C 71），
被编辑文件的解析诊断从 212–213 / 104–105 条降到 1–2 条。合法态用 `scripts/lsp-sync-bench/bench.py --baseline`
背靠背交替：四个场景与 150 个函数的采样，本刀相对基线的中位差 −4 到 +1 ms，合法态没有变慢。
全仓 1074 个被跟踪的 `.dawn` 用两把 jar 的 `__parse` 逐字节对比：979 个干净解析的文件 0 差异；
95 个有诊断的文件里只有 3 个 `unclosed_brace_*` reject 例变了（另 92 个逐字节相同）。
`scripts/diag-properties/run.py`（夜跑，一 token 变异）默认范围在本刀下 0 新增、1 条陈旧：
`b near packages/tileir/src/lower.dawn` 是删掉第 552 行的 `}` 后第一条诊断落在第 580 行（被吞的 `type` 处），
第二趟之后诊断回到开括号附近，按棘轮规矩从 `KNOWN_KEYS` 删掉该行（基线 jar 同一命令仍能复现它）。
