# 诊断的次级位置：`Diag.notes`

> 状态：**current**。2026-10-01，批 B6，issue #195（第 2 步），分支 `feat/diag-notes`。
> 前置：第 1 步（主 span 放在嫌疑开括号）已由 #280 合入，见 [parser-recovery-design.md](parser-recovery-design.md) §5。
> 裁决出处：调研报告 `research-diagnostics-issues-20260930.md` §7、`research-issue-severity-20261001.md` §#195（不在仓内）。

## 1. 为什么要

`Diag`（`selfhost/src/front/token.dawn`）只有一个 span 和一条 hint。一条诊断要讲两个位置时只能二选一，
另一个位置降格成 hint 里的「line 7」文字：#280 把未闭合括号的主 span 放到嫌疑开括号上之后，
文件尾和那个缩进不一致的闭括号都只剩 hint 里的行号；编辑器里点不过去，CLI 里也看不到那一行源码。
#198 第 3 点（「行尾运算符把下一行接了过来」，要指着运算符）同样等一个次级位置。

## 2. 数据形状

```dawn
pub type Note = { msg: String, lo: Int, hi: Int }
pub type Diag = { msg: String, lo: Int, hi: Int, hint: String, owner: Option[DiagOwner], notes: List[Note] }
```

- **一条 note 是「一个位置 + 一句话」**，不再嵌套、不带 hint、不带严重度。需要更多层次的诊断（rustc 的
  子诊断树）在本仓还没有第二个用例，不预先付这个复杂度。
- **note 与主诊断同文件**。`LocDiag` 只有一个 `path`，note 不另带路径。跨文件的次级位置（「之前定义在这里」
  落在另一个模块）今天没有使用者，见「不做的」。
- **偏移与主 span 同一套规则**：`owner` 为 `None` 时 `lo`/`hi` 是绝对码点偏移；为 `Some` 时是相对
  owning 声明起点的偏移。`check/identity.absolute` 是唯一把它们换回位置的函数，它把主 span 与每条
  note 用同一个基址一起平移，平移后 `owner` 置 `None`。不允许「主 span 相对、note 绝对」的混合：
  一条诊断只有一个参照系，否则 identity 的那条规则（「除它之外没有读者可以读 `lo`/`hi`」）就要分两种情况讲。
  checker 的唯一构造点 `check/cx.raised` 将来要挂 note 时，必须同样减去 `owner_lo`。
- **构造收口**：`token.dawn` 加 `mk_diag(msg, lo, hi, hint)`（`owner: None`、`notes: []`），全仓字面量改用它，
  再加字段。名字用 `mk_diag` 而不是 `diag`：`main.dawn`、`nmain.dawn`、`driver/clifail.dawn` 把模块
  `front/diag` 以 `diag` 引入，同名函数会与模块限定名撞车；`mk_diag` 是 lexer 里已有的私有名，收口后它消失。
  带 owner 的构造只有 `check/cx.raised` 一处，用记录更新写法 `Diag { ..mk_diag(...), owner: ... }`。
  `compiler-plan` 有自己的 `Diag`（manifest 诊断，无 owner），同样收口到 `compiler-plan/src/diagnostic.dawn`
  的 `diag(msg, lo, hi, hint)`，但**不加 notes**：manifest 诊断没有次级位置的使用者，换成编译器的 `Diag` 时
  （`driver/analyze.dawn`、`main.dawn` 的转换）给空表。

## 3. 渲染（CLI）

格式照 rustc 的**带 span 子诊断**（`note:` 起头、自带 `-->` 与源码行），不用 `= note:`：

```
error: unclosed `{`
  --> n19.dawn:3:12
  |
3 |   if a > 0 {
  |            ^
note: this `}` closes it, but it is indented like an outer block
  --> n19.dawn:6:1
  |
6 | }
  | ^
note: the file ends here, with this `{` still open
  --> n19.dawn:7:1
  |
7 |
  | ^
  = hint: ...
```

- rustc 里 `= note:` 是**无 span** 的脚注，挂在主 snippet 下面；带 span 的子诊断才是 `note:` + 自己的 `-->`。
  我们的 note 永远带 span，所以用后者。用 `= note:` 再在后面写「(line 7)」等于把位置又降格成文字，正是要治的病。
- **位置在主报错与 hint 之间**：hint 是整条诊断的结论（「该怎么改」），放在最后读；note 是证据，跟着主 span。
- 每条 note 的 snippet 独立计算行号槽宽，与主 snippet 同一个函数（`render_at` 的那段拆成 `snippet`），
  所以码点列、caret 截断规则与主 span 完全一致。
- note 为空的诊断渲染**逐字节不变**。这是收口提交与加字段提交零差的前提，也是「只有带 note 的诊断才动输出」
  这个断言的出处。
- 机器读的 dump（`__lex`/`__parse` 的 `!` 行、checker 的 `D` 行）在行尾为每条 note 追加
  `\tnote\t<lo>\t<hi>\t<msg>` 四个字段；没有 note 时行不变。不另起一行：grammar-corpus 用 `^!` 行数钉诊断序列，
  note 不是诊断，不该改变条数。

## 4. LSP：`relatedInformation`

- client 在 `initialize` 的 `capabilities.textDocument.publishDiagnostics.relatedInformation` 为 `true` 时，
  每条 note 出一个 `DiagnosticRelatedInformation { location: { uri, range }, message }`，`uri` 就是诊断自己的 URI
  （同文件，见 §2），`range` 用与主 range 同一个 `jrange`（UTF-16 列）。VS Code 的 `vscode-languageclient`
  声明此能力，问题面板里 note 可点。
- client 没声明时**不发**该字段（LSP 3.17 把它定义为 client 能力，未声明即不保证能解析），而是把 note 折进
  `message`：`msg`、每条 note 一行 `note: <msg> (line N)`、最后 `hint: <hint>`，与 CLI 同序。
  只出位置不出字段，信息不丢；声明了能力的 client 则 message 里不重复 note。
- 能力在 `initialize` 读一次，存进 `LspState.related_information`，与 `watch_manifests` 同法。
- 诊断 JSON 在 `diagnostics_of_program` 等处生成后缓存于 `Workspace.diag_by_uri`；能力在会话内不变，
  所以缓存的 JSON 不需要随能力失效。

## 5. 缓存与增量

- **没有落盘的序列化**。`Diag` 在 parse memo（`pdiags`）、模块步骤记忆、body product 里都是内存值，
  比较用结构相等（`Program` 的 `==`，incremental-semantics 合约就是比它）。note 作为 `Diag` 的字段，
  随诊断一起被缓存、一起被比较，不需要单独的失效规则。
- **复用时的重定位**：checker 的诊断按 owner 相对记录，复用一个步骤时不改 `lo`/`hi`，渲染时由
  `identity.absolute` 按本版本的声明位置换算（`lsp-module-memo-design.md` 第四节）。note 的偏移在同一参照系里，
  同一次换算一起平移，所以「声明挪了位置、文本没变」时 note 也跟着挪，不会带出旧位置。
- parser 诊断（含本批的首个使用者）`owner: None`、绝对偏移；parse memo 按文本键控，文本不变则偏移不变，
  复用天然正确。

## 6. 首个使用者：未闭合括号（#195）

`front/parser.dawn` 的 `place_unclosed`：

- 主 span 不变（嫌疑开括号或最内层未闭合者）。
- 总有一条 note 落在 EOF token：``the file ends here, with this `{` still open``。
- 缩进启发命中时再加一条 note 落在那个配错的闭括号上：
  ``this `}` closes it, but it is indented like an outer block``，排在 EOF note 之前（按源码顺序）。
- hint 去掉已经变成 note 的行号，只留结论：命中启发时 ``this `{` probably needs its own `}` ``，
  未命中时 ``add the missing `}` ``。

这改变了无效输入的渲染（`run (compile errors render)` 等 label 只在其语料含未闭合括号时才红，以实跑为准），
按红的 label 逐行 `Emit-Change`。#198 第 3 点（续行运算符）不在本批：它要 parser 记下「右运算数跨行」
的事实再传给 checker，规模独立，留给它自己的 issue。

## 7. 验证

- 收口提交：四差分 + native-cli-diff 零差（字面量换成等价构造，note 字段尚不存在）。
- 加字段提交：`front/diag.dawn` 的渲染测试钉 `note:` 块；`check/identity` 的测试钉 note 随 owner 平移；
  LSP 内联测试钉「声明能力 → 出 `relatedInformation`、不声明 → 折进 message」。负控：去掉能力判断，测试红。
- grammar-corpus 的三个 `unclosed_*` 例钉 note 字段；负控：不挂 note，例红。

## 不做的（理由）

- **多主 span**（一条诊断两个同等地位的位置）：没有使用者，且 LSP `Diagnostic` 只有一个 `range`，
  编辑器侧无处安放；需要时拆成两条诊断或一条 note。
- **label 文本着色 / 终端颜色**：渲染器今天不出任何 ANSI 码，四个差分逐字节比对输出；着色是独立的 CLI 改动。
- **span 上的行内 label**（rustc 在 caret 后面写的 `- unclosed delimiter`）：note 已带一句话，行内 label 要求
  一行内多 span 排版，渲染器复杂度翻倍；没有第二个使用者前不做。
- **跨文件 note**：`LocDiag` 一个路径；跨文件要把 note 的路径也走一遍 canon 与 LSP URI 映射，没有使用者。
- **compiler-plan 的 `Diag` 加 notes**：manifest 诊断没有次级位置；加了也只是在转换处传空表。
- **#198 第 3 点**：见 §6。
