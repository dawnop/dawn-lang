# 门禁自身的漂移：锚点、预算观测、生态语料 pin

> 状态：**current**。裁决 9 的三条（2026-09-24，`agent-handoff/rulings-20260924.md` 与其改裁记录）：
> 9(a) 锚点恰一次 + 翻面守卫 + 读源码脚本清单，9(b) nightly 预算观测，9(c) 生态语料 pin 推进与陈旧检查。三条都已落地，提交见文末。

三条要治的是同一种病：门禁判断「这个提交对不对」时依赖一份手写的参照物（源码里的一段字面量、`# budget:` 行里的秒数、一个钉住的外部提交），
参照物自己过期时门禁**仍然是绿的**。每一条都补一个「参照物过期即红」的检查，并且都放在不会误伤 push 的位置。

## 9(a) 按拼写定位代码的门禁

### 现状（b2e19e06）

- `scripts/mutation-anchor-preflight.py` 已经在编译器构建之前把所有 `mutate.py` 的变异、gatemap 的每个 mutant edit 在内存里跑一遍，
  新增的 `mutate.py` 没登记即红（`:142-145`）。这是 #92 的成果，本条不重做。
- doc-check 的审计锚点（`<!-- audit-anchor: present|absent <path> | <literal> -->`，`docs/codebase-audit-v2/*`）用的是 `literal in text`，即「至少一次」。
  实测当天 27 个锚点里有一个 `present` 命中两次：`ARC-10` 的 `-Xss512m` 在 `bin/dawn` 里既是第 80 行注释也是第 107 行默认值。
  删掉默认值、留下注释，这条 open 的 finding 仍然读作「代码还在」。
- `absent` 锚点在 finding 开着时按定义命中 0 次，不能套「恰一次」。它的风险是另一种：修复者把 `present` 改成 `absent`、或把字面量改写到恰好成立，
  doc-check 继续绿（L-02「翻面」）。
- 「读源码文本当锚点」的脚本没有清单。preflight 只覆盖它认识的那几家。

### 做法

1. **present 恰一次**（`scripts/doc-check.py` 的 `audit_anchor_problems`）：`present` 锚点命中 >1 次即红，标签 `anchor_present_once`；
   自测加一个只点亮它的变异体 `a-present-literal-that-matches-twice`。`absent` 不动。
   同一提交把 `ARC-10` 的锚点改成 `DAWN_JVM_OPTS:--Xss512m`（恰一次），这是修锚点文本，不是放宽规则。
2. **翻面守卫**（新脚本 `scripts/anchor-guard.py`）：在基线上已经存在的审计锚点，kind、路径、字面量任何一项变化即红，
   除非窗口内某个提交信息有一行 `Anchor-Change(<ID>): <理由>`。语法与拒绝规则照 `scripts/emitchange.sh`：一行一个 ID、不收通配、
   理由必填、以 `Anchor-Change` 开头却解析不了的行是错误。新记录的锚点不需要声明（锚点在记录 finding 时写一次）。
   **窗口**取 Emit-Change 的窗口：`scripts/seed-release.txt` 那个 tag 之后的提交。任务单写的是「对比 `origin/main`」，
   没照做的理由：维护者常直接推 main，那时 `origin/main` 就是 HEAD，对比是空的；tag 窗口在 PR 与直推两种路径上都有效。
   `--base <rev>` 留给本地想对比 `origin/main` 的时候。
3. **读源码脚本清单 fail closed**（同一脚本，账本 `scripts/anchor-readers.txt`）：`scripts/` 下被跟踪的 `.py`/`.sh`，只要文本里
   既有源码路径（`selfhost/src`、`compiler-plan/src`、`std`、`runtime/c`、`packages/*/src` 下的 `.dawn/.c/.h`）又有按拼写匹配的操作
   （`.count(`、`.replace(`、`grep -F`、`sed -i` 等），就必须在账本里有一行，写明四类之一：
   `preflight`（与 preflight 自己的适配表对账）、`self-once`（文件里必须有恰一次检查）、`unproven`（公开的欠账）、`not-anchor`（写理由）。
   双向：未登记即红，脚本删了或不再命中规则而账本还留着也红（`scripts/gate-map/unseen.txt` 的形状）。
   规则故意宽：多一行账本的代价是一行，漏一个读者就是这条要堵的静默缺口。

### 实测

- 当天清单：95 个脚本命中规则，11 preflight、16 self-once、60 unproven、8 not-anchor。`unproven` 里 incremental-semantics-contract 占大头，
  其中 4 个是「部分」恰一次（例如 `body-probe.py` 13 处替换里 10 处有检查），账本逐条写了。
- `anchor-guard.py` 本机 0.19 s，`--selftest`（20 个变异体与对照）0.05 s；进 tree-policy 现有的「mutation anchors」一步，push 门墙钟 +0（tree-policy 不在关键路径上，预算行 +1 s）。

## 9(b) 预算声明是否仍然为真

`check-gate-budgets.py` 在 push 门里只查自洽（timeout = 3x 声明、声明不超过 pole）。「声明是否还是最坏观测」要读 Actions API，
脚本头部写明「依赖网络的门禁会因网络变红」，所以一直是手跑。2026-09-03 曾有 21 条声明低于实测最坏值而全绿。

做法：`nightly.yml` 加一个 `budget-observations` job，`gate-observations.py --since <7 天前>` 取观测，`check-gate-budgets.py --observed` 判。
job 显式列权限 `actions: read`（读运行记录）、`contents: read`、`issues: write`；红了由 `scripts/nightly-issue.sh` 开一个固定标题的 issue，
正文贴欠声明表；同标题的 issue 已开着就追加评论，不重开（Rust Reference 每日 grammar check 的做法）。不读上次 artifact。

实测（本机，2026-09-24）：`gate-observations.py --since <7 天前> --runs 150` 读到 29 次 ci.yml 运行（09-18 到 09-23），1 分 42 秒
（本机经 WSL2 网络；默认的 `--runs 25` 只覆盖约两天，所以 nightly 把 `--runs` 抬到 150，让 7 天成为真正的窗口），
`check-gate-budgets.py --observed` 0.06 s。把 job 的两步原样抽出来在本机跑（`GITHUB_REPOSITORY` 手设，开 issue 那一行换成 echo），
审计步退出 1、issue 正文生成正确。**今天就会红两条**：`syntax-mutants-2` 声明 882 s、实测 897 s，`builtin-type-2` 声明 794 s、实测 809 s。
这是它该报的东西，本批不改这两行（push 门不在本批范围），留给 nightly 开的 issue。

## 9(c) 生态语料 pin

`selfhost-prev-diff.sh --corpus site` 每天从 dawnop-site 取钉住的提交做 lex/parse/fmt 差分。pin 从来不推进：`a72bfc9` 的 `.dawn-version` 是 v0.59.0，
之后 dawnop-site 升钉三次（`b1ad9b2` v0.68.0、`e58182b` v0.69.0、`932c9c4` v0.72.0）。

做法：

- `ECO_REV` 推进到 dawnop-site 当前 HEAD `dc0a8fb`（`932c9c4` 之后一个提交，把 backend-dawn 迁到 v0.72.0 的 `Fs` 效果）。
- 陈旧判据（改裁后的）：**pin 必须不早于 dawnop-site 默认分支上最近一次改 `.dawn-version` 的提交**。
  `selfhost-prev-diff.sh --check-pin` 用 `gh api` 取那个提交与 `compare/<bump>...<pin>`，状态是 `identical`/`ahead` 才绿；
  另打印 pin 的 `.dawn-version` 与本仓种子，供人看、不判红。不 clone。
- nightly 加 `corpus-pin` job（`contents: read`、`issues: write`），红了开「pin 落后」的 issue，规则同 9(b)。

实测（本机，2026-09-24）：`--check-pin` 5.7 s（三次 `gh api`）；新 pin 下 `--corpus site` 全程 1 分 08 秒，`lex/parse/fmt backend-dawn` 三条都 OK。
负控：把 `scripts/selfhost-prev-diff.sh` 的 `ECO_REV=` 行 sed 回 `a72bfc9f…`，`--check-pin` 退出 1，打印 `STALE … is behind …`；改回后退出 0。

草案的「落后本仓 release 超过一个版本即红」不做：dawnop-site 按跨仓契约只在重大改进时升钉，那条判据第一天就红、并且长期红。

## 墙钟

- push 门：+0。tree-policy 多两条命令共约 0.25 s，预算行从 431 s 记为 432 s，timeout 不变。
- nightly：新增两个并行 job，不需要工具链；`budget-observations` 本机 1 分 42 秒（上界），`corpus-pin` 本机 5.7 s。
  两者与 `ecosystem-corpus` 并行，nightly 的总墙钟不变；多花的是 runner 分钟数，约 2 分钟。`budget-observations` 的 `timeout-minutes: 15` 是失控上限，不是预算声明（nightly 不带 `# budget:` 行，理由见该文件头）。

## 不做的（理由）

- **gatemap 的 31 个字面常量逐个过恰一次**：调研建议之一，本批任务单没列；`BUNDLED_MODULE_EXPRESSION` 已经过了。留给下一刀。
- **把 `unproven` 的 60 个脚本逐个改成恰一次**：账本就是欠账表，逐个修是按脚本的小刀，不在本批。
- **从语法树或编译器产物定位变异点**（cargo-mutants、Stryker、PIT 的方向）：长期方向，恰一次是过渡。
- **翻面守卫覆盖 `mutate.py` 与 gatemap 的锚点**：它们没有 kind，改动本来就会让变异体打不上而红；翻面只存在于有 present/absent 两面的审计锚点。
- **nightly 记录「上次成功观测时间」**：调研的第 4 点。cron 被丢时 Actions 页面本身可见；等真出现连续丢跑再加。
- **vendor dawnop-site**：不治陈旧，且副本会被本仓的破坏性语法窗口一再触碰（调研 9(c)）。

## 提交

分支 `ci/tooling-window`（2026-09-24 rebase 到 `origin/fix/builtin-privileges`，即 PR #216 的树；合入时哈希会变，故按主题列）：

- 9(a)「Hold gate anchors to exactly once, unflipped and enrolled」：present 恰一次、`ARC-10` 锚点重写（带 `Anchor-Change(ARC-10):`）、`scripts/anchor-guard.py` 与 `scripts/anchor-readers.txt`、tree-policy 接线与 steps lock 重录。
- 9(b)「Audit budget claims against a week of observations nightly」：nightly `budget-observations` 与 `scripts/nightly-issue.sh`；随后「Restate two mutant-shard budgets to their seven-day worst runs」把首跑就会点名的两条声明（`syntax-mutants-2` 897 s、`builtin-type-2` 809 s）提前重述。
- 9(c)「Advance the ecosystem pin and red nightly when it falls behind」：`ECO_REV` 推进到 `dc0a8fb`、`--check-pin`、nightly `corpus-pin`。
