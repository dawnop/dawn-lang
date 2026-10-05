# LSP 补全：未导入的 std 模块成员与自动 `use`

> 状态：**current**：2026-10-05 落地，分支 `feat/lsp-auto-import`（提交以主题引用，合入后的哈希记在进度记录里）。
> 起因是 [play-lsp-client-design.md](play-lsp-client-design.md) §3.4：Playground 的内置补全表改为只在 LSP 不可用时加载之后，
> LSP 在线时打 `tri` 不再给 `str.trim`（附自动 `use std/str`），对未导入的模块打 `str.` 也不列成员。
> 本文把这项能力补在服务端（`selfhost/src/lsp/lspc.dawn`），VS Code 与 Playground 一起受益。

## 1. 改前是什么样

- 旧的静态表（`site/play-ui/src/dawn-lang.ts`，由 `dawn doc --builtins` 生成）在裸词位置给每个 std 模块函数一项
  `str.trim`，选中时若缓冲区没有 `use std/str` 就在**最后一行 `use` 之后**（没有 `use` 时在文件开头）插一行；
  `str.` 之后按别名列该模块的函数，名字不带前缀。它只认函数，不认常量与类型。
- 服务端在 `.` 之后**一律返回空**（`for` 模式头里的限定构造器除外，[for-pattern-design.md](for-pattern-design.md)），
  连已导入的 `str.` 也不列成员；裸词位置也不给 `str.trim` 这样的限定名。所以 §3.4 那句「写了 `use` 之后两者都由服务端给出」
  在改前其实不成立：在线时写了 `use std/str` 也补不出 `str.trim`，此前一直靠合并在下面的静态表兜着。

## 2. 范围：只限 std 的公开成员

自动 `use` 只提供 **std 模块**的名字，不扫 `packages/`、`[deps]` 或工程里其它模块。理由：

1. **std 是每个缓冲区都够得着的唯一一面**。依赖要先写进 `dawn.toml`，单文件缓冲区和 Playground 根本没有依赖；
   提供一个依赖里的名字，等于提供一个下一次构建才知道能不能解析的名字。
2. **std 已经在服务端里检查好了**：`StdCtx.exports` 在 `load_std` 时一次建好，整个会话不变。工程模块的导出面只有被
   导入之后才进入分析（`program_exports`），为补全去加载缓冲区没要求的模块，是把补全的成本变成「整个工程」。
3. **std 的别名不会撞**：std 是平的一层（`std/str` 的别名就是 `str`），每个别名恰好对应一个模块。工程里
   `a/util` 与 `b/util` 同名，裸打 `util.` 该导入哪一个就成了要猜的事；rust-analyzer 在这种情况下给出多项让人挑，
   我们的工程模块数量不值得为此引入歧义。

可见性照抄 `use` 行补全的规矩：`may_name_module` 挡掉 `std/hamt`、`std/pvec`（`pass_imports` 在 std 之外拒绝导入），
导出面经 `module_qcx` 的 `exports_seen_by` 过滤掉别包的 `pub(pkg)` 名字。

**已导入的模块**（任何路径，包括工程模块）在这两种形式里也一并给出，只是不带编辑：既然别名已经绑定，列出成员不需要
猜任何东西。这顺带补上了 §1 说的「已导入的 `str.` 不列成员」。

## 3. 两种形式各怎么答

### 3.1 裸词：`tri` → `str.trim`

在一般代码位置（不是 `use` 行、不是新绑定名、不在字符串或注释里、不在 `for` 模式头里），已有的局部、函数、prelude、
关键字之后，追加 `alias.name`：

- 已导入的模块（不论 std 与否）：别名取缓冲区里 `use` 写的那个（`use std/str as s` 给 `s.trim`），sortText 前缀 `2`，
  与 prelude 同档；不带编辑。
- 未导入的 std 模块：别名取路径末段，sortText 前缀 `4`，排在关键字（`3`）之后；带 `additionalTextEdits`
  与 `labelDetails.description = "use std/str"`。
- 只取函数与常量（`alias.Name` 的类型、构造器在裸词位置几乎不是想要的东西，留给 `alias.` 形式）。

**首字符过滤**：只给成员名或别名以所打词的首字符开头的项。词为空时一项都不给，并把回包标成
`isIncomplete: true`，让客户端在词增长时重问。理由：

- 不过滤的话，每次补全多出约 250 项、数十 KB，而用户真正会停下来的只是一两项。
- 客户端在同一个词里继续打字时**复用**上一次的列表（CM6 的 `validFor`、VS Code 对 `isIncomplete: false` 的列表都是
  本地再过滤），所以服务端的过滤必须保证「对这个词的任何延长，列表仍是完整的」。首字符在词增长时不变，按首字符
  过滤正好满足这一点，因此词非空时回包仍是 `isIncomplete: false`，不需要每键重问。
- 代价：只能靠中间字符匹配到的项（打 `rim` 想要 `str.trim`）不会出现。VS Code 的模糊匹配本来就要求首字符落在词首
  （`trim` 在 `.` 之后算词首），CM6 对这种匹配也打低分；这一点损失我们接受。

**词为空的回包形状**：`isIncomplete` 只有 `CompletionList` 对象能表达，所以词为空时，即使客户端没声明
`itemDefaults`，回包也是 `{isIncomplete: true, items: [...]}` 而不是裸数组。两种形状都是 LSP 3.17 合法回包，
VS Code、Playground 都认；仓库里只认数组的测试工具（`builtin-type-contract/probe.py`）同步改为两种都收。

### 3.2 点号：`str.` → `trim`

光标前是 `alias.`（不是 `..`）且不在 `for` 模式头里时：

- `alias` 是光标处的局部（含形参）：这是值的字段或 UFCS，不是模块，**什么也不给**（与改前一致）。
- 缓冲区有一行非选择性 `use` 绑定了 `alias`：列这个模块的导出（函数、类型、别名、构造器、常量、trait、effect，
  与 `use m.{` 补全同一个 `exported_items`），不带编辑。
- 否则若 `std/<alias>` 存在、本文档可以导入、且没有别的 `use` 已经占用这个别名：列它的导出，每项带同一条 `use` 编辑。
  `use std/str as s` 之后打 `str.` 什么也不给：再加一行 `use std/str` 是「模块导入两次」的编译错误。
  只有 `use std/str.{trim}` 这种选择性导入时，再加一行 `use std/str` 是合法的（实测编译通过），照常提供。

两种形式判断「已导入」都读**当前文本**的 `use` 行（`scan_uses`），而不是上一次分析：打到 `str.` 时缓冲区通常解析不了，
分析里的导入表可能是空的，按它判断会对已经写了的 `use` 再插一行。`use` 行在顶层、从行首开始（`dawn fmt` 的输出），
选择性列表可以跨行到 `}`；落在多行字符串或注释里的行不算（`lex_ctx`）。

## 4. 编辑插在哪

`dawn fmt` 不重排 `use` 行（它只读词法，保持书写顺序），所以顺序由我们定、由用户保持。规则（`use_edit`）：

1. 缓冲区已有 std 的 `use`：若它们已按路径排好序，插在排序位置；没排序就插在最后一条 std `use` 之后。
   这样排好序的文件保持有序，没排序的文件不被「整理」。
2. 只有非 std 的 `use`：插在第一条 `use` 之前（仓库惯例是 std 在前）。
3. 没有 `use`：插在第一个声明之前，并越过紧贴在它上面的注释行（它的 `##` 文档），后面空一行。
   用空行隔开的文件头注释因此留在最上面，符合「每个文件先有一段讲为什么的注释」的约定。
   文件头注释直接贴着第一个声明（中间没有空行）时分不清它属于谁，按属于声明处理，`use` 落到注释之上。
4. 缓冲区末尾没有换行时先补一个。

插入的文本就是 `dawn fmt` 的输出形态（`use std/x` 加换行），格式化后不变。旧静态表的规则是「最后一行 `use` 之后」，
在规则 1 的未排序情形下两者一致。

## 5. 与 `completionItem/resolve` 的分工

编辑**随列表一起发**，resolve 只取文档（[lsp-hover-design.md](lsp-hover-design.md) §D7 不变）。

- LSP 3.17 规定 `additionalTextEdits` 只有在客户端的 `resolveSupport.properties` 里列出时才可以推迟到 resolve。
  Playground 的客户端只列 `documentation`，网关的 `resolved_item_value` 也只放行 `label`、`kind`、`detail`、`data`、
  `documentation`；CM6 的 `apply` 是同步的，等不了一次 resolve。随列表发则所有客户端都能用。
- 成本小：一次请求里每个模块只算一次插入位置（`use_edit` 是对文本的一次线性扫描），每项多约 150 字节；
  首字符过滤后一次只有几十项带编辑。
- rust-analyzer 正相反，把导入编辑推迟到 resolve，因为它的候选来自对整个依赖图的模糊搜索、计算贵；我们的候选
  只有 std 的十几个模块，位置在列表时就是现成的。gopls 对未导入包的候选也是在列表时就带上
  `additionalTextEdits`。
- resolve 收到的 `alias.name` 标签由 `lspq.member_name` 剥掉别名，再按 `data.module` 找声明的文档；
  所以 `str.trim` 与 `str.` 之后的 `trim` 取到同一份文档。

Playground 网关不重建补全**列表**（只重建 resolve 的项），列表里的 `additionalTextEdits`、`labelDetails`、`isIncomplete`
原样通过，网关不用改。play-ui（`site/play-ui/src/lsp.ts`）改了三处：读 `isIncomplete` 与 `additionalTextEdits`；
带编辑的项用一个 `apply` 在同一个事务里插名字和 `use` 行，光标落在名字之后；列表不完整时去掉 `validFor`，
让 CM6 在词增长时重问。

## 6. 性能

std 的导出面就是索引：`StdCtx.exports` 在服务端启动加载 std 时一次建成，`module_qcx` 每个请求按可见性过滤一遍
（改前就有）。补全请求新增的工作只有：对文本扫一遍 `use` 行、对每个模块判一次首字符、给命中的项渲染签名。
没有另建缓存：实测增量在预算之内，多一份缓存就多一份要与 `StdCtx` 保持一致的状态。

实测（本机 16 核 WSL2，测量时机器上还有别的写者，load average 约 60，所以只看同一进程里交错请求的差，不看绝对值）：
一个 300 个函数、一行 `use std/list` 的缓冲区，同一服务端进程里五种请求轮流发，各 400 轮、丢掉前 20%，客户端往返中位数：

| 请求 | 中位数 | 回包字节 | 项数 |
|---|---|---|---|
| 词为空（无限定名，`isIncomplete`） | 25.1 ms | 31,639 | 401 |
| `t`（16 个未导入 std 项 + `list.take`） | 26.8 ms | 37,010 | 417 |
| `s`（别名 `str`、`set` 整个模块命中） | 29.3 ms | 49,397 | 455 |
| `str.`（未导入，带编辑） | 23.0 ms | 9,594 | 28 |
| `list.`（已导入） | 17.9 ms | 3,577 | 20 |

裸词形式相对词为空的增量是 1.7 ms（`t`）与 4.2 ms（`s`，最坏情形：两个模块的全部成员命中），都在 5 ms 预算内。
基线的 25 ms 是改前就有的取分析与渲染 400 项。

## 7. 其它语言服务器怎么做

- **rust-analyzer**（flyimport，`crates/ide-completion/src/completions/flyimport.rs` 的模块文档）：对未导入的项做模糊
  匹配（字符按序出现即可），输入短于两个字符时不搜路径导入；导入编辑在 resolve 时才算，客户端不支持时退回列表时全算，
  文档说那「可能很慢」。<https://github.com/rust-lang/rust-analyzer/blob/master/crates/ide-completion/src/completions/flyimport.rs>
- **gopls**（`completeUnimported`，默认开）：`foo.xx` 中 `foo` 是未导入的包名时，把 `xx` 当作成员的匹配模式；
  候选按「当前包的导入、标准库、工作区、模块缓存」的顺序找，标准库用预建的符号索引；每个候选在列表时就带
  `additionalTextEdits`（`unimported.go` 的 `appendNewItem`）。
  <https://github.com/golang/tools/blob/master/gopls/internal/golang/completion/unimported.go>、
  <https://go.googlesource.com/tools/+/refs/heads/gopls-release-branch.0.5/gopls/doc/settings.md>
- **TypeScript**（`includeCompletionsForModuleExports`）：只影响裸标识符补全，不影响 `obj.` 右边；导入编辑在
  `completionEntryDetails`（对应 LSP 的 resolve）里给。
  <https://typestrong.org/typedoc-auto-docs/typedoc/interfaces/TypeScript.GetCompletionsAtPositionOptions.html>

我们取 gopls 的做法（列表时带编辑、标准库用现成索引、`alias.` 形式按包名找），理由见 §5；裸词的过滤比 rust-analyzer
更紧（首字符而非模糊），换来的是词非空时列表完整、客户端不用每键重问（§3.1）。

## 8. 测试与负控

- `lspc.dawn` 单元测试：`scan_uses`（跨行选择性列表、`use java`、多行字符串里的假 `use`），`use_edit` 的四条规则。
- `server.dawn` 测试（真 std）：裸词带编辑与 sortText、首字符过滤、已导入不带编辑、排序位置、词为空时的 `isIncomplete`、
  resolve 取到 std 文档；点号形式的未导入、`as` 改名、改名后原别名不给、局部同名不给、不存在的模块不给。
- `selfhost-lsp-diff.sh` 新增一个 untitled 缓冲区会话：裸词、`list.`、词为空、`str.trim` 的 resolve；
  完成列表的对象形状也按 `(sortText, label)` 归一。与上一 release 的差异以 `Emit-Change(lsp)` 声明。
- 变异负控（每个都先确认测试变红）：裸词项不带编辑、`use_edit` 永远按未排序处理、点号形式忽略同名局部、
  词为空时不标 `isIncomplete`。
- play-ui 自测：带编辑项一个事务插两处且光标位置正确、无编辑项保持原 `apply`、`isIncomplete` 列表去掉 `validFor`、
  `completionList` 读出 `isIncomplete` 与 `additionalTextEdits` 并丢掉畸形的编辑。

## 9. 不做的（理由）

- **不扫 packages 与依赖**：见 §2。
- **不把编辑推迟到 resolve**：见 §5。
- **不做模糊匹配的服务端过滤**：首字符之外的过滤会让列表对词的延长不再完整，就得每键重问（§3.1）。
- **裸词位置不给 `alias.Type` 与构造器**：类型位置与构造器在 `alias.` 形式里给，裸词里列出来只会把函数挤下去。
- **不给值的字段与方法（`x.`）**：那是点号补全的另一半，需要类型信息，另立项（[assoc-types-design.md](assoc-types-design.md) 记过）。
- **不改 `dawn fmt` 去排序 `use`**：fmt 是词法级的，重排导入会动用户的书写顺序；插入规则已经让排好序的文件保持有序。
