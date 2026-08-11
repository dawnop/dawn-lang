# Dawn 代码库审查 v2：文档、测试与治理

> 状态：**current** —— normative spec、current docs、CI/contract harness 与仓库风格配置的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- 仓库的门禁数量很多，且多个历史缺口已经修复；问题不是“没有测试”，而是个别独立 oracle 没接 CI、发现式原则没有覆盖 packages、某些 reject harness 只找子串。
- 文档治理已有 status/index/link/version 检查；GOV-04 又把 finding 当前状态收成一个精确分区，并禁止两级索引复制设计任务进度，避免 Web v2、LSP debounce、Char 那类成批漂移重现。
- normative spec 混入过期 roadmap 和不可编译 quick reference，会让“实现与规范冲突时谁是 bug”失去可操作性。

## GOV-01 — P1 — dtoa 独立契约没有接入 CI

- **证据：S。** `std/fmt.dawn:1087` 明确说 dtoa 由 `scripts/dtoa-contract` 逐 byte 固定，因此本模块不重复；contract 默认比较 200,000 random samples并跑两个后端：`scripts/dtoa-contract/run.sh:2`、`:8`。
- 当前 workflows 没有调用它；普通 std gate 位于 `.github/workflows/gates.yml:64`。
- **影响：** 最短 round-trip/canonical output 的唯一 independent oracle 不在持续门禁；两个后端编译同一错误 Dawn 实现时，backend differential 会共同给出错误答案。
- **建议：** push 跑 fixed-seed small sample，release/nightly 跑完整 200k；oracle prerequisite 不满足时 fail，而不是 silently skip。

## GOV-02 — P2 — normative syntax quick reference 含非法 Dawn

> **后续处置（2026-08-11 登记，正文修复更早）：已修。** `d501357` 拆开了速查块里那两条
> 同行 statement，`docs/spec.en.md` 同步。分诊当时把「fence 仍是裸 ```dawn、doc-check 没有
> `parse` mode」记为残留，**该残留现裁为不做**，理由见下。
>
> **§13 速查块的排版裁决（GOV-02 后半，2026-08-11）：不做拆分，也不加 `parse` mode。**
> 提议是把速查块拆成「声明 / 表达式 / 测试」三段，好让门禁能逐段解析。实测这买不到门禁：
> 三段里只有「声明」与「测试」是合法模块，**「表达式」那段是语句**（`let n = 42`、
> `if x > 0 { … }`、`xs[0]`），在顶层根本不解析，要让它过 `parse` 就得把它包进一个 `fn`，
> 而那正好改掉速查表要展示的东西：它列的是**形式**，而形式是与上下文无关地列出来的。
> 于是拆分只剩排版收益，`parse` mode 则会成为一条**在触发它的那个块上恰好用不上的规则**，
> 而 `scripts/doc-check.py` 的模块注释逐字禁止这件事（「a check that matches nothing is
> green for exactly the same reason a working check is green」）。
>
> **那么什么在守着这个块：** §1 到 §12 每一条形式都在上面被规范正文定义过，
> `doc-check.py` 的 `sections` 与 `contracts` 两项检查盯着那些定义；速查块只是它们的目录。
> **重开条件：** 该块里出现第一个能独立成为完整模块的例子，那时它该标 ```dawn compile
> 并进 `blocks` 检查，一个块一条规则，不需要新 mode。

- **证据：S。** `docs/spec.md:1996` 与 `:1997` 把两条 statement 写在同一行且无 separator。parser 要求 statement 后 newline：`selfhost/src/front/parser.dawn:120`，否则报 `expected a newline after this statement`：`:127`。
- 该 fence 只是 `dawn`，doc-check 只执行标成 `run/compile` 的 block：`scripts/doc-check.py:881`、`:886`。
- **影响：** 权威速查直接教给读者不可编译排版，且门禁因 opt-in 没发现。
- **建议：** 修合法换行；为 fragment 增加 `dawn parse` fence mode，允许 semantic placeholder 但必须 parse。

## GOV-03 — P2 — normative spec 仍混用废弃 v0.1 roadmap（已修）

> **后续处置（2026-08-09）：已修。** 双语 normative spec 已把有效限制改写成当前合同，
> 删除陈旧 future-directions roadmap；仅保留标题曾叫 “v0.1 draft” 的历史说明。
> `doc-check` 拒绝第二个 `v0.1` 活动性标签或恢复 §14 roadmap。

- **证据：S。** spec 声明版本跟工具链：`docs/spec.md:5`、`:8`，仍在 `:17`、`:1973` 使用 v0.1 限定；roadmap `:2023`–`:2027` 把 conditional impl、generic body、SAM conversion、newtype/Rune 列为未来。
- 同文已经定义 conditional impl：`docs/spec.md:468`、SAM conversion：`:1353`、`Char`：`:88`。
- **影响：** 已落地、已否决与真正未实现混在 normative roadmap，后续设计者无法知道哪些是 contract。
- **建议：** normative spec 只保留当前 contract；roadmap 移到单独 current plan，已完成/否决进入 historical log。

## GOV-04 — P2 — current audit indexes 与源码状态成批漂移（已修）

> **后续处置（2026-08-10）：已修。** `docs/codebase-audit-v2.md` 的
> `fixed/partial/open/retracted` 四状态层现由 `scripts/doc-check.py` 对六份明细标题派生的
> 97 个 ID 做精确分区校验，并交叉核对声明计数、专题矩阵和冻结 29 行 P1 映射。旧三状态层
> 只作为历史快照继续校验。`docs/README.md` 与 `docs/audit/README.md` 的设计材料表只保留
> 路径、覆盖、材料类型和破坏性边界，不再复制任务进度；文档生命周期仍由各自文件头表达。
> 同一门禁还用相对路径关系判定 `docs/` 范围，仓库祖先目录名含 `docs` 时不会再误判根文件。
> 错计数、重复/遗漏/未知 ID、P1 映射冲突、索引恢复任务状态列/单元格与路径误判均有
> 定向变异负控。

- **审查时证据：S。** 两级索引曾同时把 Web v2 写成 proposed、LSP debounce 写成未落地、
  Char 写成活账，而三份设计材料的文件头与实现已经给出不同结论；旧 `codebase-audit.md`
  也曾把历史基线标成 current。
- **根因：** finding 处置、设计任务结果和文档生命周期混用一套“状态”概念，并在索引中
  手抄自由文本副本；原门禁只检查状态行存在，审计分区也只读取已明确降为历史的三状态层。
- **裁决：** 不新增 JSON/YAML registry。finding 处置只认总纲四状态精确分区；设计材料的
  生命周期与任务结果只认其文件头和正文；索引只做发现导航，不承担任务状态副本。

## GOV-05 — P2 — examples gate 不执行多数 `main`（已修）

> **后续处置（2026-08-09）：已修。**
> `scripts/example-main-contract/registry.json` 为 gallery 自动发现的 16 个
> 用户入口登记 17 组 `argv/stdin/stdout/stderr/exit` 契约；执行器要求
> gallery unit discovery 与 registry 精确双射、schema 字段闭集，入口
> 合法性只由真实 `dawn run` 判定；每次运行以独立进程组和 120 秒上限
> 逐字节核对 stdout/stderr，正常返回后也清理残留后代。CI 继续分别保留 test-block、
> JSONTestSuite 与 N-vs-N−1 run differential，四者不再互相代替。

- **证据：S。** `scripts/example-tests.sh:2` 明说只跑 test blocks，命令是 `dawn test`：`:40`；test mode 合成 TestMain：`selfhost/src/main.dawn:992`、`:1040`，不调用 example main。
- N-vs-N−1 只选择 calc/interop/handlers/chars/barriers 等少数入口：`scripts/selfhost-run-diff.sh:47`、`:71`；site 却承诺每个 example 可直接运行：`site/src/gen/examples.dawn:23`。
- **边界：** 未进入 run-diff 的 example main 可变成 `panic("broken")`，其独立 test blocks 仍全部通过。
- **影响：** 教程/展示最重要的 executable path 可坏而 CI 绿。
- **建议：** 为每个 runnable example登记 args/stdin/expected output，自动发现所有 `main`；JVM-only/external-env 例外显式标记。

## GOV-06 — P2 — grammar reject 允许额外错误而假绿

> **后续处置（2026-08-11 登记，实现更早）：已修，且是全面而非局部。** `0d752c1` 把
> `scripts/grammar-corpus/run.sh` 从「任一行含子串即过」重写为**整序列钉死**：读开头连续的
> `# expect:` 行，先比条数（多一条少一条都 FAIL），再逐 index 比子串。reject fixture
> **全部**带 expect 行（现 35 个），另加四个变异自测（漏声明 / 顺序调反 / accept 解析不了 /
> 正例）写在同一脚本末尾。原提交标题的单数指的是**发现的那个已腐烂用例**，机制改动是全语料的。

- **证据：S。** README 声称 reject 必须因正确理由失败：`scripts/grammar-corpus/README.md:10`；harness 收集所有 diagnostics 后，只要任一行包含 expected substring 就 pass：`scripts/grammar-corpus/run.sh:39`、`:43`。
- **边界：** 在 fixture 前加一个独立 syntax error，只要 recovery 后仍产原 substring，用例继续绿。
- **影响：** error priority、cascade 与 location regression 看不见；语言演进可能把一个精准诊断变成多条噪声仍过门禁。
- **建议：** 固定 normalize 后的完整 diagnostic sequence；最低要求 first diagnostic match 且无额外 diagnostics，并给 harness 加自测。

## GOV-07 — P2 — package tests 仍是手抄清单

> **后续处置（2026-08-11 登记，实现更早）：已修。** `e708115` 新增
> `scripts/package-tests.sh`（遍历 `packages/*/dawn.toml`，并设下限防树塌），
> `.github/workflows/gates.yml` 的五个硬编码包名换成调用它。无 test block 的 package 会
> **变红而不是被跳过**（`dawn test` 对无断言目标报错），脚本注释逐字写着「forgetting to
> extend a list looks exactly like not having written one」。

- **证据：S。** `.github/workflows/gates.yml:77` 手工列五个 packages；新增 `packages/foo` 不自动进入 gate。同 workflow 在 `:81` 已承认 examples 曾因手抄漏测，并改成 discovery；`scripts/example-tests.sh:4` 也写了该原则。
- **影响：** 当前五包都覆盖，但新增 package 是确定 blind spot。
- **建议：** `scripts/package-tests.sh` 遍历 `packages/*/dawn.toml`；没有 test block 的 package 也应明确失败或登记豁免。playground 可单列。

## GOV-08 — P2 — CONTRIBUTING 的可执行指令已经失真（已修）

> **后续处置（2026-08-09）：已修。** quick fmt scope 已与 gate 对齐为
> `std site selfhost packages examples`，里程碑 progress/retro 路径统一到
> `docs/history/`；release asset 的既有修复继续保留。`doc-check` 固定命令与路径。

- **证据：S。** quick fmt command 漏 `std`、`examples`：`CONTRIBUTING.md:6`，真实 gate 包含：`.github/workflows/gates.yml:305`；文档要求新建根目录 `docs/m<N>-progress.md`/retro：`CONTRIBUTING.md:50`、`:54`，当前层次是 `docs/history/`：`docs/README.md:141`；release 说明上传 `dawn.jar`：`CONTRIBUTING.md:100`，真实 asset 是 `dawn-selfhost.jar`：`.github/workflows/release.yml:119`。
- **影响：** 贡献者照做会漏 formatter scope、把文档放错层、寻找不存在的 release asset。
- **建议：** CONTRIBUTING 只指向唯一 quick-check script 与 release script；关键 path/asset name 加轻量 doc assertion。

## GOV-09 — P2 — bootstrap 手工恢复命令使用已删除的 `--embed-std`

- **证据：S。** runbook 仍要求该 flag：`docs/bootstrap.md:94`、`:98`；当前 build parser 不识别：`selfhost/src/main.dawn:1254`；源码说明 std 已由 stdsrc module embed：`:1319`；真实 fixpoint 不使用 flag：`scripts/selfhost-fixpoint.sh:18`。
- **影响：** 灾难恢复/手工验证时才使用的命令在最需要时失败。
- **建议：** 删除废弃参数，以当前脚本命令为唯一可执行展开；doc-check 对 runbook command shape 做 smoke。

## GOV-10 — P3 — `.editorconfig` 与 formatter 的缩进相反（已修）

> **后续处置（2026-08-09）：已修。** EditorConfig 现在按扩展名规定 Dawn/YAML 两空格、
> Python/Java 四空格，避免全局四空格与 formatter 冲突；`doc-check` 固定两个配置块。

- **证据：S。** `.editorconfig:3` 对所有文件生效，`:9` 指定四 spaces；Dawn formatter 用两 spaces：`selfhost/src/front/fmt.dawn:5`，CI 强制 formatter：`.github/workflows/gates.yml:305`。
- **影响：** 支持 EditorConfig 的 editor 主动生成会被官方 formatter 改写的 Dawn/YAML。
- **建议：** 按 extension 配置：Dawn/YAML 2，Python/Java 4；不要用全局 indent size 覆盖所有语言。

## GOV-11 — P3 — README 的规模指标已显著失真（已修）

> **后续处置（2026-08-09）：已修。** 双语 README 删除标准库模块数、标准库/编译器行数
> 等无决策价值且快速腐烂的精确规模，保留可验证的架构描述；`doc-check` 拒绝旧指标模式。

- **证据：S。** 英文 README 称 std 10 modules/3300 lines：`README.md:7`；中文同步复制：`README.zh-CN.md:8`。当前 `std/modules.txt:4`–`:20` 登记 11 modules，本轮静态计数约 5,690 Dawn lines。
- **影响：** translation digest 只能证明两份同时，不能证明事实真实；精确数字快速腐烂。
- **建议：** 从 modules.txt/tracked source 生成 metrics，或删除无决策价值的精确行数。

## GOV-12 — P3 — 同文档 `§N` 引用不校验，spec 已有错链（已修）

> **后续处置（2026-08-09）：已修。** module system 错链已由 §11 改为 §10；
> `doc-check` 对双语 normative spec 的 bare `§N` 一律按同文件章节校验，显式 `.md`
> 跨文档引用继续按目标文件校验。RFC 章节改写为 “section N”，避免把外部标准误当本 spec。

- **证据：S。** `docs/spec.md:26` 把 module system 指向 §11；实际 module system 是 `docs/spec.md:1582` 的 §10，§11 是 std：`:1733`。doc-check 只检查显式带目标文件的 `§N`：`scripts/doc-check.py:548`，无法推断目标时跳过：`:577`。
- **影响：** normative spec 的导航错误无法被门禁发现。
- **建议：** 至少对 spec/spec.en 的 bare `§N` 当作同文件引用；跨文档引用要求显式 filename 或 escape marker。

## GOV-13 — P3 — current package design 同时说 lock 已落地和“不做 lock”（已修）

> **后续处置（2026-08-09）：已修。** current design 现描述真实 schema 1：`dawn lock`
> 记录直接坐标及 resolved artifact 的文件名/摘要，`--check` 与 build/run/test 核对，
> 并明确只冻结 Maven/Java 闭包且不能恢复删除的上游 artifact。旧 no-lock 结论被门禁禁止。

- **证据：S。** header 声明 package/Maven 项目已落地：`docs/package-design.md:3`；正文仍把 project lockfile 列为砍掉：`:245`，并说 exact Maven coordinate 不需要 lock：`:247`。实现与仓库已有 lock：`selfhost/src/pkg/maven.dawn:188`、`selfhost/dawn.lock:1`。
- **影响：** 标 current 的单一设计说明给出相反 reproducibility model。
- **建议：** 重写为 schema 1 当前行为与限制；旧论证移入 historical note。
