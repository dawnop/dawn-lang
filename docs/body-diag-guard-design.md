# 体级诊断守卫：replay 只看本体的诊断（#165）

> 状态：current。2026-09-26 落地于分支 `fix/body-diag-guard`（基线 origin/main `10176d6a`）。
> 计数与负控出处见本文「实测」；矩阵本身的定义在 [real-edit-matrix-design.md](real-edit-matrix-design.md)。

## 问题

session body replay 里，一个函数体内的类型错误会让调度在它之后的每个体都冷算。
`real-edit-matrix` 的 `body_one_type_error` 格在 n=1000 时冷掉约 500 个体而不是 1 个；
issue #165 的复现命令（`edit-matrix.py --classes calls --edits body_one_type_error --functions 20`）
报「reused 12, unadmitted 10」。typed 结果每格都与冷检查相等，所以这是精度损失，不是正确性缺陷。

根因是四处读**整张**诊断表的门：

| 位置（改前，origin/main `10176d6a`） | 写法 | 谁走它 |
|---|---|---|
| `check/scalar_replay.dawn:515`（`relocation` 第一行） | `if cx.diags != [] { return None }` | 所有被准入的函数体 |
| `check/function_entry_proof.dawn:82`（`prove`） | `len(candidate.diags) != 0 \|\| ...` | 有界泛型体（generic 类） |
| `check/function_entry_proof.dawn:111`、`:129` | `len(resolved.diags) != 0`、`len(entry.cx.diags) != 0` | 同上，对派生上下文 |
| `check/bounded_replay.dawn:154` | `len(resolved.diags) != 0` | 同上，每个 witness |

这里的 `cx` / `candidate` 是调度器带着走的上下文，`diags` 是它的**累计**诊断表：前面冷算的体报的错
都留在里面。推断函数先按调用依赖序检查（`checker.dawn:15110` 一带），所以推断体一报错，几乎整个模块冷算。
第二、三、四行在只修第一行时会让 generic 类照旧冷掉后半段（第一行之后 generic 体还要过 `prove`），
所以四处必须一起改。

## 为什么「只看本体」是对的

守卫要回答的问题是「重放这个体的产物，与冷算这个体，结果是否相同」。冷算一个体对诊断表只做一件事：
**追加**。证据：

- 诊断的唯一构造入口是 `cx.dawn` 的 `cerr` / `cerr_h`，都是 `diags: cx.diags ++ [...]`。
- `check/` 非测试代码里读诊断表的地方全部列出来（`awk` 排除 `test` 块后 grep `diags`）：
  `checker.dawn:4180-4193`、`:9495-9498`、`passes.dawn:1588-1590` 都是「进入前记长度、出来比长度」，
  只问这一段自己有没有追加；`import_use.dawn:511` 的 `report_unused_imports` 读整张表，但它在模块
  所有体之后跑，不在任何体的检查里；`body_product.dawn:185`、`header_product.dawn:90` 是捕获时取增量。
  没有一处在检查一个体时读前面的体报了什么。

所以冷算第 k 个体的 typed 结果、符号、写入与它前面的诊断表无关，只有追加的那一段是它自己的。
产物捕获时存的正是这一段（`body_product.dawn:213`，`list.drop(after.diags, len(before.diags))`），
安装时追加回去（`:242`）。本体没报错的产物，增量为空，装到一张非空表上与冷算逐字相同。

「自己这次检查产生了诊断」的体依然不准入：这道按 body 的门早就在录制侧（`scalar_replay.recorded` 里的
`p.diagnostics != []`，有界路径在 `bounded_replay.dawn:92` 与 `function_entry_proof` 的
`len(product.diagnostics) != 0`），本刀把它单独成行并写明它才是诊断守卫。被拒的体冷算，在自己的位置
重新报一遍。

## 改动

- `scalar_replay.relocation`：删掉整上下文门，注释写明为什么这里没有诊断守卫、守卫在哪。
- `scalar_replay.recorded`：`p.diagnostics != []` 从一长串条件里拆成单独一行，作为唯一的按 body 守卫。
- `function_entry_proof.prove`：删 `len(candidate.diags) != 0`；`resolved` 与 `entry.cx` 的两处改成
  「长度等于进入时 `candidate.diags` 的长度」。
- `bounded_replay.expression` 的 witness 检查：`len(resolved.diags) != len(cx.diags)`。
- 测试：「mixed assembly」那条原来断言 reuse 在第一个诊断处停止（reused 1 / checked 3），改成 reused 2 /
  checked 2；新增「does not reuse a body whose own check reported a diagnostic」：`let y` 在同一作用域绑两次，
  报诊断但树里没有错误节点，除了诊断守卫没有别的东西能把它挡在准入类外，而它后面的 `three` 必须照常命中。

`driver/analyze.dawn:1216`（issue 写的 `:1192`，行号已漂）「模块有诊断就丢模块级缓存」**没动**。
它管的是另一件事：有错的修订不作为下一次的录制。会话里的效果是：出错的那次编辑从上一次干净的缓存
回放（本刀让它从 n−m 冷降到 1 冷），修好的那次编辑全冷。要放宽它得另证「从有错修订录下的缓存可安全
准入」，矩阵的回程步在 scalar 层已经给了一半证据（回程 R+1 且逐体相等），但会话层还有 comptime、
跨模块 exports 等本刀没看的东西，见「不做的」。

### 会话层的计数随之移动

`lsp-project-matrix.py`（经 `configured-lsp-contract.py` 的 project 套件跑）钉死了每个跨模块修订的
计数（checked, reused, reused_modules, cold_rejected, unobserved_modules, retained）。三格变了，
都是同一个原因，且诊断、hover/definition 等协议结果不变（cold/prepared 两路逐字相等照旧由该脚本比对）：

| 修订 | 改前 | 改后 | 为什么 |
|---|---|---|---|
| `provider-signature` | (3, 1, 0, 1, 0, 2) | (2, 2, 0, 1, 0, 2) | `main.probe` 因 `exported` 签名变化被拒并报错；排在它后面的 `main.local` 以前跟着冷，现在命中 |
| `provider-error` | (2, 0, 0, 0, 1, 0) | (1, 1, 0, 0, 1, 0) | `lib.exported` 体内报错；`lib.unrelated` 现在命中 |
| `close-provider` | (3, 1, 0, 1, 0, 2) | (2, 2, 0, 1, 0, 2) | 同 `provider-signature` |

`retained` 一列不变：出错模块的缓存照样被 `analyze.dawn:1216` 丢掉，`provider-recovery` 仍是全冷
(4, 0, 0, 0, 0, 4)。这正是上一节「没动」的那条规则在会话里的可见后果。

## 负控

编译期变异体，锚点都恰好出现一次：

| 变异体 | 所在脚本 | 改动 | 必须红的地方 |
|---|---|---|---|
| `own-diagnostic-admitted` | `scalar-replay.py` | `recorded` 的 `if p.diagnostics != [] { return None }` → `if false` | 新测试的 `admitted_count(admitted) == 2` |
| `whole-context-diagnostics` | `scalar-replay.py` | `relocation` 开头加回 `if cx.diags != [] { return None }` | mixed assembly 与新测试的计数断言 |
| `whole-context-diagnostics` | `edit-matrix.py --controls` | 同上 | calls / primitive_inferred / generic × `body_one_type_error` |
| `entry-proof-whole-context` | `edit-matrix.py --controls` | `prove` 加回 `len(candidate.diags) != 0` | generic × `body_one_type_error` |

「去掉按 body 守卫」只能由单元测试看见，矩阵看不见：矩阵里出错的 member（`helper(a) + false` 之类）
树上有错误节点，`scalar_shape` 先于诊断守卫就拒了它，去掉守卫也照样不准入。这正是新测试选
「重复绑定」的原因。

## 实测

2026-09-26，WSL2，16 核，15 GiB；另有写者同机，**不报时间结论**，计数与机器无关。

| 格 | 改前 | 改后 |
|---|---|---|
| calls × body_one_type_error，n=20 正向 | reused 12, unadmitted 10 | reused 21, unadmitted 1 |
| calls，n=1000 正向 | reused 502, unadmitted 500 | reused 1001, unadmitted 1 |
| primitive_inferred，n=1000 正向 | reused 501, unadmitted 500 | reused 1000, unadmitted 1 |
| generic，n=1000 正向 | reused 500, unadmitted 501 | reused 999, unadmitted 2（含 impl 方法） |
| inferred（lambda），n=1000 正向 | unadmitted 1000 | unadmitted 1000（按形状全拒，不变） |

默认矩阵四类 × 十编辑 n=1000 全部 40 格 `oracle_ok`，三步的 typed 结果都与冷检查逐体相等；其余 36 格计数不变。
负控的红绿输出在本机报告 `agent-handoff/body-diag-guard-report-20260926.md`。

## 不做的（理由）

- **放宽会话层的「模块有诊断丢缓存」。** 任务单与 issue 都要求不削弱；放宽要另立证据（comptime 只在
  无诊断时跑、exports 从有错模块导出），不属于这把刀。
- **在 `relocation` 再放一道「产物有诊断就拒」。** 录制侧已拒，重复的一道是死代码，而且会让负控要同时
  删两处才红，等于没有负控。
- **把矩阵的 `body_one_type_error` 换成不带错误节点的诊断。** 那会改掉 09-23 定下的编辑语料，
  按 body 守卫的负控由单元测试承担已经够了。
