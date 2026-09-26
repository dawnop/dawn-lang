# 门禁自身的漂移：锚点、预算观测、生态语料 pin

> 状态：**current**。裁决 9 的三条（2026-09-24，`agent-handoff/rulings-20260924.md` 与其改裁记录）：
> 9(a) 锚点恰一次 + 翻面守卫 + 读源码脚本清单，9(b) nightly 预算观测，9(c) 生态语料 pin 推进与陈旧检查。三条都已落地，提交见文末。
> 2026-09-25 追加「总量棘轮」一节（门禁总量调研推荐的 (a1)+(c)，用户同日批准）：push-total / path-total 上限、`Gate-Budget` / `Gate-Retire` 声明、nightly 总量报表。
> 2026-09-26 追加「棘轮第二轮」一节：nightly 点名的五条欠声明里四条贴 pole，按 #166 的先例拆片（#242）。

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

## 总量棘轮（2026-09-25）

依据：`agent-handoff/research-gate-budget-ratchet-20260925.md`（§0 实测、§3 事故、§4 候选），推荐 (a1)+(c)，用户 09-25 批准。

### 为什么单 job 规则管不住总量

`check-gate-budgets.py` 原有的三条规则都是**单 job** 的：timeout ≥ 3 倍声明、声明不超过 pole、nightly 核对声明 ≥ 7 天最坏观测。
2026-08-25 到 09-24 之间 main 的 360 次 ci.yml push，成功运行的中位总量从 7.2k 涨到 21.6k job 秒（2.9 倍），这些规则全程都满足，门禁全绿。
增长全部来自**新加的 job**（09-23 一天就加了 5 个），不是既有 job 变慢；一个本身不大的新 job 过得了任何单 job 规则。
而本仓一次运行的墙钟由排队决定（`span ≥ max(最长 job, 总量/20)`，gates.yml 头注释），所以总量才是墙钟跟着走的那个数。

pole 的算术就是这样过期的：09-11 按投影 17,286 job 秒算出排队下限 864 s、定 pole 950 s，并写明「job 集合一变就重算」。
09-23T19:00Z 到 09-24T21:06Z 的 12 次成功 main push（run 35907509360 到 36056324369）实测：按 job 中位合计 22,601，最新一次 21,669，
排队下限约 1,080 s，已高出 pole 约 130 s；最长 job 876 到 937 s。没人重算，也没有检查会因此变红（调研 §0.5）。
可见性这条路在本仓已经失灵过：tile.yml 挪出 push 路径时依据是「前 30 次 push 一次都没碰」，09-12 以后 80 次里跑了 19 次，同样没人发现（§3 第 3 条）。

### 机制

1. **上限行**（`scripts/check-gate-budgets.py`，tree-policy，离线）。`gates.yml` 一行 `# push-total: 29319s`，`tile.yml` 一行 `# path-total: 5484s`，
   含义是该文件所有 `3x <N>s` 声明之和不得超过它。初值就是当天的和，没有余量。钉在**声明**而不是实测上：声明是最坏值，
   nightly 审计保证声明 ≥ 实测最坏，所以声明之和是实际总量的有效上界，而且不联网也算得出；比值当天是 29,319 / 22,601 = 1.30。
   行缺失、重复、不是 `<N>s`、写错文件、写在没有 `3x` 声明的文件里，都红。求和走 `collect_budgets`，与 `--observed` 读的是同一批声明。
   floor 声明不计入，理由与 pole 相同。editor-grammar.yml 只有 floor，不设上限。
   声明里的 worst observed 指 nightly 审计的 7 天窗口（nightly.yml 传给 `scripts/gate-observations.py` 的 `--since`；
   脚本自身不带 `--since` 时读最近 25 次运行，约两天，不是这个窗口）；planning value 只在该 job 在窗口内还没有运行时使用，
   有了运行就换成观测值。不用 14 天：截至 09-25 的 14 天里，incremental-4/6/8 在 09-13 到 09-14 的运行是 979 / 996 / 1009 s，
   全部超过 pole，而 09-15 以后三者最坏只有 827 / 742 / 937 s；窗口不能比 job 内容的变化活得更久。
   同日上限从 29319 s 降到 26149 s：21 条 planning value 比各自 job 的 7 天最坏高出 50 到 450 s，这些余量可以被新 job 不声明地占掉，
   于是逐条改成最坏观测加一成（取整秒），上限跟着降到新的和。
   09-26 升到 26617 s（#242，四条贴 pole 的 job 拆片，见文末「棘轮第二轮」）。
2. **升上限要声明**（`scripts/check-gate-budget-trailers.py`，ci.yml `secrets` job）。比较 push 区间两端树上的两个上限：
   升了，区间内的提交信息要有 `Gate-Budget(<push-total|path-total>): <旧>s -> <新>s <理由>`，旧/新数字与两端树一致；
   分几次升可以逐次声明，要求的是从起点到终点有一条声明链。
3. **防删覆盖**。push-total 降了、且 `scripts/gates-external/steps.lock.json` 两端相比某个家族少了 run 步骤，
   每个少了步骤的家族都要有 `Gate-Retire(<family>): <理由>`；点名一个没少步骤的家族也红。步骤都在（纯瘦身）不需要声明。
   对应 GHC 的 `Metric Decrease:` 与 Rust post-merge 报告单列的 `[missing]`（调研 §3 第 6 条）。tile.yml 没有 steps lock，path-total 没有这一条。
4. **nightly 报表**（`scripts/gate-totals.py`，nightly `budget-observations` job）。读 14 天的 ci.yml 与 tile.yml main 运行，
   在 step summary 写一张表：push 次数、成功（全集）次数、每次成功 push 的中位 job 秒、中位 span、按族占比
   （incremental / 变异体 / native 差分 / contracts / 其它）、tile.yml 触发次数与触发率。
   本周中位总量比上周涨超 10%，或 tile.yml 本周触发率超过 20%，就经 `scripts/nightly-issue.sh` 开 issue（标题 `nightly: gate totals over their limits`）。
   这两条是上限行看不见的漂移：实测总量在上限之下爬升，以及按路径触发的门跑得比挪出时预言的勤。

### 声明格式与解析

- 一行一个名字，不收通配，理由必填；以 `Gate-Budget` / `Gate-Retire` 开头、后面紧跟 `(` 或 `:` 却解析不了的行是错误。
  只看关键字不够：说明这条规则的提交信息正文折行时，恰好有一行以这个词开头，实现这一刀时本刀自己的提交就这样红过一次。
- **不进 `scripts/emit-labels.txt`，不走 `scripts/emitchange.sh`。** emitchange 按整个 release 窗口读声明，一个标签声明一次就罩住之后同标签的所有变化
  （builtin-decl-mirror 那次「同标签互吞」）；这里按 push 两端读，用自己的解析器。
- 区间：push 是 `before..HEAD`；PR 是 `origin/<base>...HEAD`，基准取 merge base；force-push 使 `before` 不可达时区间退化为 `HEAD`，
  这时对每个碰过两个 workflow 或 steps lock 的提交，逐个与其父提交比较、只认它自己的提交信息（比 push 严）。
- 起点树上没有上限行（引入它的这次 push，或 2026-09-25 以前的区间）只报告、不判红。
- 上限行的读法复用 `check-gate-budgets.py` 的 `read_total`，steps lock 的读法复用 `steps_lock.py` 的 `from_lock`，各只有一份解析。

### 为何不做路径门控

调研 §0.6 与 §4(b)：359 个 main push 区间里 294 次（82%）碰了 `plan.py` 的 FORCED 路径，这时 plan 本来就答全集；
就算给引擎划一个偏窄的闭包，仍有 62% 的 push 要跑。main 上门控 `incremental-*` 平均每次只省约 1,300 job 秒（6%），省的恰好是本来就便宜的 docs/scripts push。
代价是「main push 就是全集」这条不变量：release 守卫的第 1 条证据、gates-external 的「全集」定义、plan.py 头注释都依赖它；
另外 main 上 21% 的运行被 `cancel-in-progress` 取消，按 `before..after` 算 diff 会漏掉被取消那次 push 的改动（§3 第 4 条），
Mozilla 就出过「子集漏到 central」的事故（§3 第 1 条）。所以本刀不做路径门控，main 的 `cancel-in-progress` 也不动。

### pole 为什么不动

pole 现在低于排队下限，但两个数回答的已经是两个问题：pole 钉单 job 临界路径（最长 job 实测 937 s，总量降回来那天，超过 950 s 的 job 就是墙钟），
总量交给 push-total。把 pole 抬到新的下限只会让每个 job 多出 130 s 余量，墙钟一秒不省，因为下限高是 job 多了，那是 push-total 该管的事。
gates.yml 里那段 09-11 的算术保留为记录，后面补了 09-25 的实测与这条理由。

### 实测

- 负控 1：把 tree-policy 的声明从 432 s 改成 1432 s，三条规则同时红（3 倍 timeout、pole、push-total：`sum to 30319s, 1000s over the 29319s push-total`）。
- 负控 2：把五条 700 s 以下的声明各加 200 s，timeout 同步到 3 倍（每条仍在 pole 之下），**只有** push-total 红。这正是单 job 规则看不见的情形。
- `check-gate-budgets.py` 自测 19 个变异体（新增 7 个）；本机 0.04 s，与改前持平。
- `check-gate-budget-trailers.py --selftest` 15 个临时仓库用例（裁定的五种区间加错数字、两步链、错家族、解析不了、裸关键字、折行正文、path-total、PR 区间、force-push 两向），本机 0.64 s；
  一个 push 区间 0.06 s；force-push 兜底扫 290 个提交 4.3 s。
- `gate-totals.py --selftest` 6 组夹具周，0.04 s。
- 真数据（本机，2026-09-25 03:07Z 为止的 14 天，只读 API）：`gate-observations.py` 读 80 次 ci.yml 运行 6 分 00 秒、33 次 tile.yml 运行 1 分 00 秒（本机链路慢，同一链路上审计读 25 次要 1 分 52 秒），
  `gate-totals.py` 0.04 s。本周 41 次 push、32 次成功，中位 21,128 job 秒、span 1,606 s；上周 39 次、30 次成功，中位 17,612、span 1,376 s；
  本周 incremental 32.8%、变异体 17.4%、native 10.8%、contracts 4.1%、其它 34.9%。**两条都超限，首跑就会开 issue**：
  中位总量 +20.0%（09-23 新加的 5 个 job），tile.yml 本周 41 次 push 里跑了 10 次（24%）。这是它该报的东西，本刀不处理。

### 墙钟

- push 门：tree-policy +0 s（上限规则并在既有一步里，0.04 s 不变）；`secrets` +约 0.7 s（自测 0.64 s + 区间 0.06 s），仍是秒级 floor job。都不在关键路径上。
- nightly：`budget-observations` 多读一遍 14 天的 ci.yml 与 tile.yml（不加宽审计自己的 7 天窗口，那会改变审计把声明比到的对象）。timeout 从 15 分钟放到 30 分钟，这是失控上限，不是预算声明。

### 不做的（理由）

- **把上限钉在实测总量上**：要联网，只能放 nightly；push 门要离线（调研 §4 拍板点 1）。实测那一面由 nightly 报表看。
- **要求上限等于声明之和**（降了声明必须同步降上限）：裁定是「和 ≤ 上限」。代价是瘦身后留下的余量能被下一个新 job 无声吃掉；
  gates.yml 的注释要求瘦身后随手调低。若这件事真的发生，再把规则收紧成相等。
- **tile.yml 按 24% 触发率折算进 push-total**：触发率会漂（§3 第 3 条），折算系数本身就是一个会过期的参照物；改为单独的 path-total 加 nightly 触发率报表。
- **path-total 的防删覆盖**：tile.yml 没有 steps lock；要做得先给它建 lock。
- **Gate-Budget 声明但上限没升时判红**：只报告不判红。声明多写不造成覆盖损失。
- **路径门控、main 不取消**：见上。

### 提交

分支 `ci/gate-budget-ratchet`（基线 origin/main `882351c2`；合入时哈希会变，按主题列）：

- 「Cap the sum of each gate workflow's budget claims」：`check-gate-budgets.py` 的 push-total / path-total 规则与 7 个变异体；两行上限随之写入（让该提交自己的树过自己加的规则）。
- 「Explain the total lines and restate the stale pole arithmetic」：两个 workflow 里上限行的注释；重写 gates.yml 过期的 pole 算术。
- 「Require a declaration to raise a gate total or retire a gate step」：`check-gate-budget-trailers.py` 与 ci.yml `secrets` 接线。
- 「Report job-seconds per push to main nightly」：`gate-observations.py` 输出逐运行记录、`gate-totals.py`、nightly 两步。
- 「Write down the gate total ratchet」：本节与 CONTRIBUTING 双语。

## 棘轮第二轮（2026-09-26，#242）

nightly 审计（run 36232986458，50 次 main 运行，09-19T11:23Z 到 09-26T07:39Z）点名五条欠声明：`syntax-mutants-1` 914 s、`syntax-mutants-2` 917 s、
`test` 918 s、`incremental-3` 881 s、`builtin-type-2` 814 s。前四条按最坏加一成重述都会越过 950 s pole，重述没有意义；
`builtin-type-2` 加一成是 895 s，虽在 pole 之下，但本轮的目标是**每条声明不超过 850 s**（给 pole 留一成），而 `builtin-type-1` 最坏 822 s 同样贴着，
两片各只有一步，挪不动，所以也拆。拆片照 #166（incremental-7、contracts）的写法：每片 planning value = 搬入部分的最坏观测之和 + 50 s 固定开销
（job 时长减工作步骤），注释写明「三次 main 运行后按自身最坏重述」。

| 旧 job | 旧声明 | 新 job | 新声明 | timeout | 依据 |
|---|---|---|---|---|---|
| syntax-mutants-1 | 902 | syntax-mutants-1 | 718 | 36 | 17 个变异体 596 + 夹具 72 + 50 |
| syntax-mutants-2 | 897 | syntax-mutants-2 | 680 | 34 | 16 个变异体 557 + 夹具 72 + 50 |
| | | syntax-mutants-3 | 636 | 32 | 14 个变异体 514 + 夹具 72 + 50 |
| builtin-type-1 | 889 | builtin-type-1 | 600 | 30 | 9 个变异体 506 + probe 等 43 + 50 |
| builtin-type-2 | 809 | builtin-type-2 | 598 | 30 | 9 个变异体 505 + 43 + 50 |
| | | builtin-type-3 | 540 | 27 | 8 个变异体 446 + 43 + 50 |
| test | 908 | test | 545 | 28 | 编译器自身的 9 步最坏之和 495 + 50 |
| | | test-programs | 442 | 23 | 跑 Dawn 程序、核对结果的 6 步最坏之和 392 + 50 |
| incremental-3 | 812 | incremental-3-1 | 521 | 27 | local-value-reads 471 + 50 |
| | | incremental-3-2 | 405 | 21 | identity + header-state 226、state-product 129，+ 50 |

- **变异体分片的估计**：从窗口内 89 份 syntax 分片日志、87 份 builtin 分片日志里，按相邻 `PASS` 行的时间差取每个变异体的最坏值
  （pattern-or 约 26 s、for-pattern 37 到 39 s、syntax-small 16 到 18 s，builtin 54 到 57 s；syntax-small 每片第一个变异体多付一次冷启动，记 72 s），
  按 `position % 3` 求和，再加每片都要跑的夹具（步骤时长减变异体之和的最坏值：syntax 72 s，builtin 43 s）。同一算法套在两片旧分法上得
  933 / 922 s（实测最坏 914 / 917）与 825 / 820 s（实测 822 / 814），高估 3 到 19 s，是上界。分片仍按 harness 各自轮转，三片数量是 17 / 16 / 14 与 9 / 9 / 8。
- **test 的切法**：run 36219628503 的步骤时间戳与窗口内 41 次成功运行的逐步最坏。留在 `test` 的是编译器自己的测试与读源码/文法的门
  （compiler-plan、configured LSP、selfhost tests、comptime trace、fixpoint、grammar corpus、Int.MIN、Emit-Change 解析器、fmt）；
  搬到 `test-programs` 的是跑 Dawn 程序并核对其计算结果的步骤（`dawn test --stdlib`、narrow、package tests、example tests、example main、effect evidence）。
  任务单举例的名字是 `test-std`，但这一半还含 examples 与 effect evidence 语料，叫 std 名不副实，所以用 `test-programs`。
- 两片 `run:` 的并集与拆前逐字相同：`steps_lock.py check` 在 record 之前列出的缺失与多出一一对应（`syntax-mutants` 与 `builtin-type` 只有 `--shard` 参数变化，各多一步）；
  record 后 177 个 run 步骤、29 个家族（拆前 175、27）。`incremental-3-1/2` 与 `test-programs` 按 steps lock 的家族规则是新家族，所以原家族「少了」步骤；
  push-total 是升的，不触发 `Gate-Retire`。
- `mutant-shards-complete` 的 `needs` 与两组结果变量各加第三片；用日志还原的 `position % 3` 三份覆盖记录喂 `scripts/mutant-coverage/check.py`，四个 harness 全覆盖；
  删掉其中一份，按名报出缺的 9 个变异体。

**push-total 26149 → 26617 s（+468）**：四个新 job 的固定开销 4 × 50 = 200 s；其余 268 s 是新声明按逐步、逐变异体最坏之和构造（是上界），
其中 116 s 是 #242 点名的旧声明低于各自最坏运行的部分。

**墙钟**：每次 push 的 job 数 39 → 43（加 plan 是 44）。按 gates.yml 头部的算术，span ≥ max(最长 job, 总 job 秒 / 20)，现在绑定的是后一项
（09-25 的实测排队下限约 1,080 s）。拆片后最长 job 仍是 `incremental-8`（声明 937 s，不在本轮），四个新 job 每个多一次约 44 s 的工具链 setup，
中位总量约 +180 job 秒，排队下限约 +9 s。所以和首轮结论一样：**拆片只买 pole 余量，不买墙钟**；墙钟略增，量级在运行间噪声之内。
集群外部门禁全套的 `--jobs` 相应从 39 改为 43。

### 不做的（理由）

- **改分片的发牌方式**（按成本发牌而不是按位置轮转）：三片 syntax 相差 82 s，在上界估计的误差内；改发牌要动 `shard.sh` 与三个 harness 的覆盖语义，不在本轮。
- **其余高于 850 s 的五条声明**：`incremental-8` 937 s、`native-selfhost-tests` 904 s、`incremental-1` 879 s、`incremental-2` 870 s、`incremental-4` 863 s。
  它们都不低于各自最坏运行，不在 #242 的点名里；本轮把「≤ 850 s」读成对被拆的四组 job 的要求，这五条留给下一轮（incremental-8 距 pole 只剩 13 s）。

