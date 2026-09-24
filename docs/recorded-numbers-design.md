# 树里不复述树已决定的数字：Core golden、文档篇数、覆盖率表头、LSP 闭包测试数

> 状态：**current**。2026-09-25 的裁决批（分支 `ci/recorded-numbers`）。五条裁决的落地提交见文末。

## 原则

门禁不得要求树复述一个树本身已经决定的数字。一个数要么由门禁当场派生，要么由作者在提交信息里声明
（`Emit-Change` 那一套已有的习语），不在树里再记一遍。

树里记一个树自己能算出来的数，结果只有两种：记对了，那它不提供信息；记错了，门禁红，作者照着报错把新数抄回去，
这一步同样不提供信息。它唯一的产出是一个「重录」提交，外加并行分支之间必然的冲突。

## 数据

实测 origin/main `39755841`，自 2026-08-01 起共 2094 个提交：

| 记录物 | 碰它的提交 | 备注 |
|---|---|---|
| `scripts/core-golden/selfhost.sha` | 478（23%） | 其中 109 个提交**只**改它；135 个主题写着 re-record。并行分支每 rebase 一次重录一次 |
| `scripts/core-golden/*.core`（3 个示例 + 16 个 std 模块全量 dump） | 101 | 同上 |
| `docs/README.md` 的 `<!-- doc-check: doc-count -->` 篇数 | 169 | CLAUDE.md 自己写着「篇数不在这里复述」 |
| `docs/spec.en.md` 翻译摘要 | 127 | **保留**，见「不做的」 |
| `scripts/checker-corpus/uncovered.txt` 头部「N sites, M reached, K here」 | 43 | `coverage.py` 只在 `--record` 时写它，**从不校验**；一直有人手改一个没人读的数 |
| `scripts/lsp-workspace-contract/prepared-lifecycle.py` 硬编码 `663 test(s) passed` | 7 | issue #217 |

Core IR golden 那一步在 `contracts-1` job 里的墙钟：run 36033690490（main `39755841`）22 s，
run 36024756336（main `a187368c`）21 s。

## 裁决

### 1. Core golden 降级为按需工具

它的价值是真的：#88 的十二刀、Perceus、`CModule.dicts` 修复都靠它读出「除了声明的模块之外什么都没变」。
但那是**纯重构批次的恒等证明**，是作者在批次结束时读一次 diff 的工具。作为逐提交 CI 门，它退化成了仪式：
每个碰编译器的提交都必须重录，重录的人不看 diff（本批之前四个 PR 的重录提交主题都是「Re-record the Core golden
for the modules X moved」），`.gitattributes` 的强制冲突又让每次 rebase 都要再重录一遍。行号烘进 Core 的噪声
已由 #142 修掉，所以按需对比两个修订时不需要任何归一化。

做法：

- 删 `scripts/core-golden/`、`.gitattributes` 里对应的 `-merge` 行、`gates.yml` `contracts-1` job 的
  「Core IR golden」一步。
- `scripts/selfhost-core-diff.sh` 改成 `--base <rev>`（默认 `origin/main` 与 HEAD 的 merge-base）与 `--head <rev>`（默认 HEAD）。
  两侧**先后**在同一个临时目录路径下各自 `git worktree add --detach`、各自从种子自举，各自 dump 编译器全部模块、
  三个示例程序和它们用到的 std 模块，然后输出「Core 变了的模块集」与可读 diff。同一路径、先后而不是并排，
  是因为 panic 串会烘进编译时的路径（2026-08-04 实测，见脚本内注释），两个并排的目录会让每个模块都「变了」。
  `--record` 删除：没有 golden 可录了。
- gatemap 的规则 C 不再读 golden：编译器模块清单从树里的 `selfhost/src/**/*.dawn` 派生。规则 C 只在一个树的
  workflow 里仍有一步跑 `selfhost-core-diff.sh` 时成立（历史树，fixture 仍在上面重放 98b9896）；今天的树上没有这一步，
  编译器模块因此不再有 `exact` 判定，这就是事实。golden 带来的包名解析那一半（manifest 名字、两个 manifest 同名等）
  只为解析 golden 里的 `dawn$pkg$` 模块名而存在，随 golden 一起删掉，连同它们的断言与变异体。
- CONTRIBUTING 加一段：纯重构批次在 PR 正文贴 `selfhost-core-diff.sh --base` 的输出，作为恒等证明。
  证据贴在 PR 里，不进树。

### 2. docs/README.md 的篇数

删掉开头那句里的数字与 `doc-count` 标记，删掉 `doc-check.py` 的 `check_doc_count`。篇数 doc-check 每次运行都会打印
（`OK: N documents`），那才是不会过期的计数。索引覆盖检查（每篇文档都要被索引链接）不动，它查的是结构，不是数字。

### 3. uncovered.txt 表头的三个数

`coverage.py --record` 不再写「N sites, M reached, K here」，现有文件头改成不带数字的一句。校验逻辑本来就只比站点列表，
不变。三个数照样在每次运行时打印在 `cerr coverage: M/N sites reached` 那一行。

### 4. #217：prepared-lifecycle 不再硬编码测试总数

正向闭包的判据改为：退出码 0、没有 `FAIL` 行、恰有一行 `N test(s) passed` 且 N > 0。这个 N 就是同一树上
`dawn test` 对 `lsp/server` 闭包实跑出来的数，由脚本自己的无变异基线得到。七个变异控制除了原有的「唯一且精确的
owner 断言」之外，还要求汇总行恰为 `1 of N test(s) failed`，N 取自基线：变异不许让测试集合本身变大变小。
`.md` 里的 663 随之删掉。

### 5. `doc-check.py --fix-translation-digests`

只重算 `translation-of` 标记里的摘要，不动别的字节，不跑其它检查。它不替代「先改译文再重登摘要」这条人的义务：
脚本头部已经写明 transl 检查只防「原文动了没人注意」，不防「摘要重登了但译文没改」，加一个 `--fix` 不改变这一点，
只省掉手抄 16 位十六进制。

## 不做的（理由）

- **`docs/spec.en.md` 等译本的摘要保留。** 那不是复述：译本是另一份文字，原文动了译本是否跟上，树本身决定不了，
  只有人能决定。摘要是这件事唯一的机器可读登记，它是真漂移守卫。本批只给它加一个省手抄的 `--fix`。
- **`selfhost/src/embed/stdsrc.dawn` 等生成物保留。** 它们是构建输入而不是记录：种子编译器从树里读它们，
  不入库就要在自举链里再加一个生成步骤，而种子不一定跑得动 HEAD 的生成器。它们的漂移由生成器重跑对比守着，
  这和「把一个数抄进树里」性质不同。
- **不给 Core diff 保留任何逐提交门。** 考虑过只保留三个示例程序的全量 dump 作 golden：它们 101 次改动里绝大多数
  同样是重录，问题一样。脚本头注释自己写着 JVM 已经从 `CModule.dicts` 建字典，golden 不再是那张表的唯一见证；
  `CParam.mode` 与 `CDup`/`CSDrop` 只有 C 后端读，它们的**行为**由 native 差分与 native 自举固定点看着，
  「这一刀有没有碰到它们」这个问题留给按需的 `--base`。

## 落地（2026-09-25，分支 `ci/recorded-numbers`）

| 裁决 | 提交（主题；PR 以 rebase 合入，哈希会变） | 负控 |
|---|---|---|
| 1 gatemap 模块清单改从树派生 | Derive gatemap's compiler module list from the tree, not the Core golden | `gatemap.py --check` 在该提交单独跑也绿：28 个变异体对 23 条断言，11 个 fixture 全部重放（98b9896 仍给 `exact`） |
| 1 golden 出树、步骤删除、脚本改 `--base` | Turn the Core IR golden into an on-demand diff between two revisions | 只改注释的临时提交（`ir/lower.dawn` 第 1 行注释加字）：`Core unchanged: 0 module(s) differ`，退出 0，71 s。改 lowering 的临时提交（`lower_unwrap` 的 Option 臂 panic 串加后缀）：列出 `ir.lower`、`jvm.jarw`、`main`、`pkg.vendor` 四个模块，退出 1，83 s；只改 Result 臂的那一版只列出 `ir.lower` 自己（编译器与三个示例里没有对 Result 用 `!` 的地方） |
| 1 CONTRIBUTING 与两篇设计文档 | Ask pure refactorings to paste the Core diff into the PR body | 译本摘要由 `--fix-translation-digests` 重登，只动标记行 |
| 2 README 篇数 | Stop restating the document count in docs/README.md | README 写回 `999 documents <!-- doc-check: doc-count -->`，doc-check 仍绿 |
| 3 uncovered.txt 表头 | Stop writing site counts into the uncovered.txt header | `coverage.py` 的 `HEADER` 与文件头逐字节相同，`--record` 不会再改它 |
| 4 prepared-lifecycle（#217） | Hold the prepared LSP controls to the count their own positive reports | 见报告：删一个非 owner 的 lsp 内联测试，shard 1 仍绿；删 standalone owner 测试，shard 1 红在 owner 断言上 |
| 5 `--fix-translation-digests` | Add doc-check.py --fix-translation-digests | 自测 4 例进 doc-check 的负控计数；在 CONTRIBUTING 上真实使用一次 |

墙钟：`contracts-1` 少了 Core IR golden 一步，历史实测 22 s / 21 s；该 job 约 467 s，最慢 job 876 s（`syntax-mutants-1`），run pole 不变。
没做：`packages/tileir/src/lower.dawn`、`scripts/spike-native/index_ok.dawn`、`selfhost/src/check/passes.dawn` 三处注释仍提到 golden。
前两处改了会动 tile 台账的输入摘要或 native 语料，后一处在 selfhost 源码里，本批不碰；它们描述的是当时的事实。
