# Emit-Change 声明的作用域：窗口之外再加一条范围检查

> 状态：**current**。依据 `agent-handoff/research-prevdiff-scope-report-20261006.md` 与同日裁决：采纳方案 (a) 双基线。
> 实现：`scripts/emitrange.sh`（新）、`scripts/emitchange.sh`、五个差分脚本、`gates.yml` 的 `prev-diff` 作业。

## 问题

四个差分（prev / run / fmt / lsp）加参数名冻结共用 `emit_gate`，声明的作用域是**整个种子窗口**：
`seed-release.txt` 那个 tag 之后任一提交写过 `Emit-Change(<label>)`，该 label 在下一次 release 之前对所有后续提交都是 NOTE。
`fmt`、`lsp` 各只有一个 label，一次声明就让整个格式化器差分或整个 LSP 差分在窗口剩余时间里失明；
上一窗口（`v0.84.0..v0.85.0`，54 个提交）第 12 个提交一次声明了全部 10 个 `emit *`，此后 42 个提交 emit 差分不可能变红。

这是登记过的残差（`emitchange.sh` 的 RESIDUAL），#124 否掉「声明只对声明它的提交生效」的理由是：比的是 N-1 对 HEAD，
被批准的差异在 HEAD 仍在，下一个提交会一路红。理由对单基线成立，对**双基线**不成立。

## 做法

保留窗口检查原样不动（它还承担种子特性纪律与累计账），另加一条**范围检查**：

- 比的是**本次变更的基编译器**与**HEAD 编译器**，在 HEAD 的语料上。两边编同一份语料源码，所以源码改动产生不了差异，只有编译器与 std 的改动能。
- 差异只认**本次变更自己的提交**里的 `Emit-Change`（`EMITCHANGE_RANGE`）。以前的声明不再替后来的变更放行。
- 同一套脚本用 `EMITCHANGE_MODE=range` 再跑一遍：`seed_jar` / `seed_std_dir` 被覆盖成基工具链的 jar 与 std，其余逻辑（语料、会话、`emit_gate`）一行不动。
  `prev-diff` 的「种子能编 HEAD selfhost」一步只属窗口检查，范围检查里跳过。

### 基怎么取

| 事件 | 基 | 声明区间 | 理由 |
|---|---|---|---|
| pull_request（检出的是合并引用） | `HEAD^1` | `HEAD^1..HEAD^2` | 不能用 merge-base：合并引用里有 main 新提交，会把别人的改动算到本 PR 头上 |
| push | 事件的 `before`（从 `$GITHUB_EVENT_PATH` 读） | `before..HEAD` | rebase 合并保留消息，声明随提交走；`before` 为零或不是祖先时退到 `HEAD^`，大声打印 `delta base fell back` |
| 集群证据 / 本地 | `merge-base(origin/main, HEAD)` | `base..HEAD` | HEAD 不含 main 新提交，merge-base 正确；HEAD 已在 main 里时退到 `HEAD^` |
| `EMITCHANGE_BASE_REF=<rev>` | 该 rev | `rev..HEAD` | 覆盖以上三条，供验收与排查 |

`workflow_call` 下 `GITHUB_EVENT_NAME` 仍是调用方（ci.yml）的事件，所以不用把表达式传进 `run:`（外部 runner 不建模 `run:` 里的表达式）。

### 基工具链

基是一个 detached worktree（`git worktree add`），用它自己的 `bin/dawn` 在它自己的源码与种子上构建。种子缓存与 HEAD 共用。
每对（检出，基）只构建一次，五个脚本复用同一个目录。

### 工具链摘要相同则跳过

基与 HEAD 的 `DAWN_PRINT_STAMP` 里 `source` 与 `bootstrap` 两个摘要都相同，则范围检查整段跳过，**并打印两个摘要**：这是「看了且相同」，不是「没看」。
跳过要和 git 对账：摘要相同而 `selfhost/`、`compiler-plan/`、`std/` 在两个提交间有差异，说明摘要或接线是瞎的，**失败而不是跳过**。
种子推进提交里 `bootstrap` 摘要不同，所以会跑（预期全 OK，见 FP-2）。

### 不覆盖的（写在这里，免得以后被当成惊喜）

- 被后一次 push 取消的 push（`ci.yml` 的 `cancel-in-progress`）没人看过它的区间。走 PR 的变更在 PR 期已看过，只有直推 main 且被取消的有缺口。
  二期可用 nightly 逐提交回放补（调研 (d2)，需要「追认」声明，要扩语言），本刀不做。
- 同一个 PR 里先声明、再把同一 label 继续改动，仍是同一个区间，后一次搭前一次的声明。粒度是 PR，不是提交。
- `prev-diff-native` 里以 native 为被测的 fmt / lsp（`native-cli-diff.sh`）只有窗口检查。native fmt 已被钉到 JVM HEAD 字节，等价于传递覆盖；
  **native lsp 仍然窗口失明**，单列为后续「native lsp == JVM HEAD lsp」同 HEAD 比较。
- `Param-Change`（`selfhost-param-diff.sh`）同构，**同刀一起做了**：它读的是同一个 `seed_jar` / `seed_std_dir`，覆盖后只需把声明区间换成 `EMITCHANGE_RANGE`。
- 外部集群证据档：证据 runner 的仓库是 bundle 克隆，原来只带 `gates-tree` 与 tag，没有 main，范围检查解析不出基。
  `backend_crun.py` 的 `_make_bundle` 现在把源仓库的 `origin/main` 作为 `refs/heads/main` 一并打进 bundle（没有 `origin/main` 就不带，范围检查会明确失败并要求 `EMITCHANGE_BASE_REF`，不猜）。
  基随之是证据档写者的 `origin/main` 与 sha 的 merge-base。

## 防止这条检查静默失效

范围检查的失效方式是静默的：基被误接成 HEAD，则永远相同、永远绿。所以 `range_enter` 在跑之前拒绝三件事：基提交等于 HEAD；基根目录检出的提交不是命名的基；摘要相同而输入有差异。
区间读空不放行（反而红），方向安全；范围模式缺区间直接失败，**不回退到窗口**。

常驻自测（`scripts/emitchange-selftest.sh`，无 JVM，每次 push 跑）：

- S1 窗口里有声明、区间里没有、label 不同 → 必须红，消息含区间与基。
- S2 区间里有声明 → NOTE；兄弟 label 的声明不算；区间里的通配照样拒绝。
- S3 窗口模式下原有 28 条用例行为不变（原样保留，全绿）。
- S4 `range_decide`（摘要相同且输入相同 → skip 并印两摘要；摘要不同 → run；摘要相同而输入不同 → 失败）与 `range_check_base`（基等于 HEAD、基根检出在别处 → 失败），
  以及在临时历史上的基选择（pull_request / push / 零 before / 显式）与输入对账。

## 一次性验收

NC-1..NC-5（新行为必须红）与 FP-1..FP-3（新行为必须全绿）按调研报告 §3 执行，结果如下（本机，2026-10-06；「旧」指窗口检查，「新」指范围检查）。

| 项 | 做法 | 旧 | 新 |
|---|---|---|---|
| NC-1 emit | c1 空提交声明 10 个 `emit *`，c2 给 `emit.dawn` 的 args 字段加 synthetic 标志且不声明；基 = c1 | exit 0，10 行 NOTE | exit 1，10 行 `FAIL emit ... differs vs base ... and no commit in ... declares it`；把 10 行声明 amend 进 c2 后 10 行 NOTE、exit 0 |
| NC-2 lsp | c1 声明 `lsp`，c2 给 `serverInfo` 加字段 | exit 0（NOTE，窗口里 16 行差异） | exit 1（2 行差异，本次变更自己的）；声明进 c2 后 NOTE、exit 0 |
| NC-3 fmt | c1 声明 `fmt`，c2 把缩进单位改成 3 空格 | exit 0 | exit 1；声明进 c2 后 exit 0 |
| NC-4 `doc --builtins` | c1 声明，c2 改 `builtins_json` 的一个键 | exit 0 | exit 1（只红这一个 label）；声明进 c2 后 exit 0 |
| NC-5 接线变异 | (i) 基设成 HEAD；(ii) 基根目录预先检出在 HEAD 而命名的基是 c1 | | (i) `FAIL range: the base is HEAD`，(ii) `FAIL range: the base toolchain root is at ..., not at the named base`，均 exit 1，不是绿 |
| FP-1 | 只动 `site/` 的提交（b12a2909）为 HEAD，`EMITCHANGE_RANGE_FORCE=1` 关短路，五个脚本 | | 全 exit 0 |
| FP-2 | 种子推进提交 2e55ebe9 为 HEAD、其父为基（`bootstrap` 摘要不同，所以跑） | | 五个脚本全 exit 0 |
| FP-3 | `v0.84.0..v0.85.0` 中 18 个改 selfhost/std/compiler-plan 的提交，各以父为基，五个脚本 | | 见下 |

FP-3 的归类（18 个提交 x 5 个脚本）：

- 14 个提交五个脚本全绿。
- `4a5b4e3d`（Carry a source site on Core call nodes）自己在种子上编不过（`missing field(s) in Sig: caller_params`），历史上的一个中间提交；它作 HEAD 时和作 `7f6c8653` 的基时范围检查都因「工具链构建失败」红。
  这不是误报：窗口检查在那个提交上同样没有可用的编译器。PR 的基是 main 尖、push 的基是上一个尖，都是已通过的提交，不会落在这种中间提交上。
- `31f2a72e`（Point parser errors at a header's missing operand）：`lsp` 在本次变更自己的提交里没有声明，红。**历史上真漏掉的未声明变化**，当时被窗口里 `611dd421` 的 `Emit-Change(lsp)` 盖住。
- `9003a074`（Assemble at --opt-level 0 ...）：改了 `std/gpu.dawn`，`doc --builtins` 变了而没有声明，红。**同样是真漏掉的**，被窗口里更早的声明盖住。
- 其余假阳性：0。

调研报告说「每一个红要么是历史上真漏掉的，要么是要分析的假阳性」：这里 2 个真漏掉，1 个是不可编的历史提交，没有假阳性。

### 墙钟（本机，HEAD 工具链已建，各跑一次）

| 步骤 | 窗口 | 范围 |
|---|---|---|
| prev-diff | 44 s | 38 s |
| run-diff | 93 s | 94 s |
| fmt-diff | 14 s | 15 s |
| lsp-diff | 3 s | 4 s |
| param-diff | 3 s | 4 s |
| 合计 | 156 s | 154 s，外加基工具链构建约 20 s（每对检出一次） |

调研预估 +140 到 230 s，实测本机约 +174 s；run-diff 的 94 s 是大头，预估里低估了它。CI 机器约为本机的 1.9 倍（窗口各步 295 s 的 CI 观测对 156 s 加装配），所以 `prev-diff` 的 claim 取 325 s 加 340 s = 665 s，
`push-total` 17686 s 到 18026 s（claim 之和加 340 s，timeout 仍是 3 倍）。665 s 低于 950 s 的 pole。这是计划值，首个带新步骤的观测窗口之后按实测重述。
