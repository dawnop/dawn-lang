# parser 恢复：语句同步、就地补逗号、头部记录字面量与未闭合括号

> 状态：**current**。2026-09-30，诊断批 P1，issue #190 #192 #193 #195（第 1 步），分支 `fix/diag-parser-recovery`。
> 2026-10-20 追加 §5′（两段式重解析，#789 残差），分支 `front/two-pass-recovery`。
> 裁决与其它语言实例见调研报告 `research-diagnostics-issues-20260930.md` §3 §5 §6 §7（不在仓内）；本文记做法、取舍与负控；四刀均已实现（提交见文末）。

只动 `selfhost/src/front/parser.dawn` 与 `scripts/grammar-corpus/`。只改**无效输入**的诊断：
每条新分支都长在今天已经报错的路径上，合法程序的 AST、诊断与输出不变，spec 不改。

## 1. 语句级同步按括号深度（#190 #192 的假顶层错）

**根因**：`sync_stmt` 从**失败点**往前扫到第一个 `NEWLINE`/`}`/EOF。失败点在语句内的花括号里时
（`let p = P { x: 1 y: 2 }`），第一个 `}` 是字面量自己的，`block_body` 把它当成块尾，
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
  给改法（`m = map.insert(m, k, v)`、`r = R { ..r, f: v }`）；
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
