# 在 GitHub 之外跑完整门禁集

> 状态：**current**。第 1 刀（本地后端 + 证据包）、第 2 刀（签名、`refs/notes/gates`、`verify-external.yml` 回写 commit status）、第 3 刀（prefix、离线输入包、隔离证明、crun 后端）、第 3b′ 刀（集群上 `complete = true`：启动器 shim、非 root 与私有 `/tmp`、wasi-sdk 与 npm 离线）、第 4 刀（2026-09-24：release 守卫接受外部证据；`steps.lock.json` 进 tree-policy，关 #167）与第 5 刀（2026-09-24：C 编译器进输入包，本机与集群证据包的 `toolchain` 逐字段相等）已落地；自动触发仍记在「不做的」。首次正向发布已做（14535104）：集群全套 `complete = true`，签名 note 推上 `refs/notes/gates`，`verify-external.yml`（run 35932235187）给该提交写出 `gates/maintainer` = `success`，见「签名、落盘与 GitHub 侧核验」一节的实测。2026-10-04 起 crun 后端按负载把 job 分到集群的多台机器上，见「多机分派」一节。

## 要解决的问题

维护者有时要在 GitHub 之外对某个提交跑一遍完整门禁：托管 runner 排队或宕机、想在推之前先验、或者要在别的机器上复核一次。过去的做法是从 `gates.yml` 里手抄命令逐条跑，跑的是子集，跑完也拿不出东西证明跑了什么。

本刀交付的是 `scripts/gates-external/`：

- `run.sh --sha <sha> --backend local [--jobs N] --out <dir>`：在给定提交的树上执行 `gates.yml` 每个 job 的每一条 `run:` 步骤；
- `bundle.json`：证据包，字段白名单，`complete` 可以由任何人从 git 重新算出来；
- 后端契约：「给一棵树与输入，按命令清单跑，还退出码与输出摘要」。第 1 刀只有 local 一个实现；第 3 刀加了 crun 后端（`backend_crun.py`）。

## 为什么从 gates.yml 派生

门禁集只有一个定义，就是该提交上的 `.github/workflows/gates.yml`（它的文件头解释了为什么只能有一份）。手抄的清单一定会漂：`release.yml` 当年跑的「全套」少了 packages、playground、所有 contract，正是这么来的。`scripts/incremental-semantics-contract/sweep-plan.py` 对 incremental 家族已经这样做过，理由相同：清单每次运行时从 `gates.yml` 解析，手里不存副本。本刀把同一个做法扩到全部 job。

具体做法（`gatesplan.py`）：

1. 用 `git rev-parse <sha>:.github/workflows/gates.yml` 和 `git cat-file` 读**该提交**上的文件，不读工作树。在 X 上计划、在 Y 的检出上跑，这种错位由此排除。
2. 接受的形状是封闭的。顶层键、job 键、step 键、`${{ }}` 表达式都有白名单；job 的 `if:` 只接受下一节列出的三种形状，step 的 `if:` 只接受 `steps.<前面的 id>.outputs.<键> == '<字面量>'`，env 里的表达式只接受 `runner.temp`、`needs.<所需 gate job>.result`、`steps.<前面的 id>.outputs.<键>`。白名单外的东西一律在任何 job 开始前拒绝。原因：不认识的构造在本地怎么执行只能靠猜，猜错了就是静默地跑了另一套门禁。
3. 与 `sweep-plan.py` 一样做一次独立的行扫描交叉核对：YAML 遍历找到的 `run:` 步骤数必须等于逐行数出的 `run:` 键数，plan job 的行不计（d9b10e62 上 39 个 job、169 个 run 步骤；cdeb40ca 上 40 个 job，除去 plan 是 39 个 gate job、173 个 run 步骤）。

### plan job（#168 的 PR 分层）

#168 之后 `gates.yml` 先跑一个 `plan` job，按 PR 的 diff 决定哪些 gate job 要跑；每个 gate job `needs: [plan]`，`if:` 是「plan 说 `all`，或者 plan 的列表里有我」。plan job 不是门禁：它不判断树的任何性质，只负责给 PR 减负。外部运行按定义就是全集，所以：

- plan job 不执行，它的 run 行也不进 `complete` 的多重集；
- 替换表记一行 `plan -> external-all`，读者看得见这一步被换成了「全部都跑」；
- gate job 对 plan 输出的条件视为成立，`needs:` 里的 `plan` 从调度依赖里去掉。

「视为成立」只在条件正是 #168 写下的接线时才诚实。所以条件去掉 `${{ }}`、压缩空白后，必须逐字等于下面之一（`{job}` 代入该 job 自己的 id）：

| 形状 | 条件 | 另外要求 |
|---|---|---|
| plan-selected | `needs.plan.outputs.all == 'true' \|\| contains(fromJSON(needs.plan.outputs.jobs), '{job}')` | `needs` 恰好是 `[plan]` |
| plan-selected-always | `always() && needs.plan.result == 'success' && (…同上…)` | `needs` 含 plan 与至少一个 gate job |
| legacy-always | `always()` | #168 之前的形状，`needs` 里要有 gate job |
| plan-selected-not-cancelled | `!cancelled() && needs.plan.result == 'success' && (…同上…)` | 同 plan-selected-always；2026-10-05 起 mutant-shards-complete 用它，GitHub 上被 cancel-in-progress 取消的 run 里汇总 job 跳过而不是报红；外部运行不存在中途取消，与 plan-selected-always 同义 |

名字写成别的 job、多一个子句、只看 `all`、不 `needs: plan`、plan job 自己有 `needs:` 或 `if:`、plan 的 outputs 不是 `all`/`jobs`，都拒绝，各有自测负控。

`mutant-shards-complete` 在 #168 里还读 `${{ needs.<分片>.result }}`、用 step `id` 与 `GITHUB_OUTPUT` 算出本次跑了哪些分片家族，再用 step `if:` 决定是否汇总。这些按 GitHub 的语义求值：`needs.<id>.result` 是本次运行里那个 job 的真实结果（`success`/`failure`；`--only` 没选中的记 `skipped`，与 GitHub 相同）。step 条件为假时该步跳过，跳过的 run 步骤记 `executed=false`，`complete` 因此为假。外部全量运行里所有分片都跑了，条件为真，汇总照常执行。
4. 不复用 `sweep-plan.py` 的解析函数。它读工作树里的 `gates.yml`、只认 incremental 家族，而且会把含 `&&`、`|` 的块当错误拒掉；全量 job 里这类块很多（`wasm-target` 的 wasi-sdk 步骤就是）。这里的执行单位是整个 `run:` 块，按 GitHub 的方式交给 `bash -e`，不需要把块拆成单条命令。

## 替换表

`uses:` 步骤没法原样在本地执行，每一种都换成一个有名字的替换，名字写进证据包的 `substitutions`，读者看得见每条被换成了什么。表外的 `uses:`（包括已有条目的版本号变化，如 `actions/checkout@v5`）让 `run.sh` 在计划阶段失败，不静默跳过。

| `uses:` | 替换 id | 为什么合理 |
|---|---|---|
| `plan`（job） | `external-all` | 见上一节：外部运行就是全集，plan job 不执行，gate job 对它的条件视为成立。 |
| `actions/checkout@v4` | `tree-worktree` | CI 每个 job 都是新检出。`git worktree add --detach <sha>` 给每个 job 一棵独立的树，内容与检出相同。差别：worktree 带全部历史和 tag，CI 默认 depth 1 无 tag（`fetch-depth: 0` 的三个 job 除外）。依赖「没有历史」的脚本会表现不同；目前没有发现这样的脚本，`seedjar.sh` 在缺 tag 时会自己去取，有 tag 时直接用。 |
| `./.github/actions/dawn-toolchain` | `dawn-toolchain-local` | 这个复合 action 做四件事：装 GraalVM 21、恢复种子缓存、恢复 coursier 缓存、`./bin/dawn --version`。本地对应：`JAVA_HOME`/`PATH` 指向本机 JDK 21；把共享种子缓存里对应 tag 的两个目录拷进 worktree 的 `.dawn/seeds`（等价于 cache restore，`seedjar.sh` 每次命中都会按校验表重验，所以拷来的缓存不需要被信任）；`build: 'false'` 时不构建。整体替换只在复合 action 仍是这个形状时才诚实，所以同一提交上的 `action.yml` 会被取指纹（输入集合与默认值、两次 setup-graalvm、两个缓存的路径、重试提示与构建两个 run 步骤），形状变了就拒绝。 |
| `actions/cache@v4` | `noop` | 保存一侧不需要：本地缓存本来就在。恢复一侧由上一行的种子拷贝承担；coursier 缓存就是用户自己的 `~/.cache/coursier`，与 runner 上一样由同一个 HOME 共享。它在 `gates.yml` 里没有直接出现，只在复合 action 内部，表里仍列出，免得读者以为它被漏掉。 |
| `actions/upload-artifact@v4` | `artifact-store-local` | 拷到 `<out>/artifacts/<name>`。`if-no-files-found: error` 照样生效，重复的制品名照样报错（v4 的行为）。 |
| `actions/download-artifact@v4` | `artifact-fetch-local` | 按 `pattern` 把匹配的制品各自拷到 `<path>/<制品名>`，与 v4 不带 `merge-multiple` 时的布局一致。`mutant-shards-complete` 因此照跑，输入来自本地目录。 |
| `actions/setup-node@v4` | `node-host` | **任务单的表里没有这一行，偏离理由：** `docs` job 用它；按「表外一律失败」，没有这行 `docs` 永远跑不了。本地用 PATH 上的 `node`，版本号写进证据包的 `toolchain.node`，是不是 `lts/*` 由读者对照判断。`cache: npm` 当作无操作。 |
| `actions/setup-java@v4` | `jdk21-host` | **同样是任务单外的一行：** `compiler-weight-contract` 用它装 Temurin 21。本地用同一个 JDK 21（GraalVM CE，不是 Temurin），只接受 `java-version: '21'`，版本字符串写进 `toolchain.java`。 |

除 `uses:` 之外，本地后端还有几处改变了步骤看到的环境。它们不是替换，但同样影响「跑的是什么」，所以也以 `adjust:*` 为主语列进 `substitutions`：

| 调整 | 替换 id | 理由 |
|---|---|---|
| `adjust:runner-temp` | `per-job-directory` | `RUNNER_TEMP` 与 `${{ runner.temp }}` 指向每 job 一个的目录，放在 worktree 外，免得脏了树。 |
| `adjust:tmpdir` | `per-job-directory` | `TMPDIR` 每 job 一个，`mktemp` 类的临时文件互不相见。runner 上没有设它；设了只会更隔离。 |
| `adjust:literal-tmp-paths` | `machine-wide-lock` | 步骤里写死的 `/tmp/<名字>`（今天只有 `contracts-1` 的 `/tmp/gate-emit`）在同一台机器的所有检出之间共享。按字面路径取一把机器级文件锁，两个 `run.sh` 不会同时用它；挡不住别的程序。路径是从命令文本里扫出来的，不是手写的表。 |
| `adjust:github-env-files` | `per-step-files` | `GITHUB_ENV`、`GITHUB_PATH` 等是每步一个文件，`ENV` 与 `PATH` 按 runner 的规则带到后续步骤。`wasm-target` 靠它把 `DAWN_WASM_CC` 与 `DAWNC_BIN` 传给后面的步骤。 |
| `adjust:npm-offline-cache` | `input-pack-npm-cache` | 第 3b′ 刀加的。prefix 模式下 `npm_config_cache` 指向 prefix 的 `cache/npm`（输入包 npm 缓存的副本：npm 离线也往缓存里写日志），`npm_config_offline=true`。`docs` job 的 `site/build.sh` 跑 `npm install`，于是只从缓存取包，拿不到就 `ENOTCACHED` 红，不会悄悄去 registry。步骤本身不改。只在该提交用 `actions/setup-node` 时列出。 |
| `adjust:wasi-sdk-tarball` | `input-pack-tarball` | 第 3b′ 刀加的。prefix 模式下环境里有 `WASI_SDK_TARBALL`，指向输入包里已校验的 wasi-sdk 原件；`wasm-target` 的步骤见到它就拷贝而不下载，sha256 照旧对两条路径都核。只在该提交的 `gates.yml` 读这个变量时才列出（`gatesplan.ADJUSTMENT_WHEN`），否则这一行描述的是不存在的东西。不带 `--prefix` 时不设，步骤照旧下载。 |

另外，宿主环境里的 `GITHUB_*`、`RUNNER_*`、`DAWN_*`、`JAVA_HOME` 等变量在交给步骤前被清掉，再设 `CI=true`。`DAWN_SEED` 之类的变量会悄悄改变工具链的来源，不能从开发者的 shell 漏进来。

## complete 的定义

`complete = true` 当且仅当：

- 该提交上 `gates.yml` 全部 job 的全部 `run:` 步骤，按 (job id, run 原文) 组成的多重集，等于证据包 `steps[]` 中 `executed = true` 的 (job, command) 多重集；
- 并且每个已执行步骤的退出码是 0。

缺一条、多一条、任一步骤未执行、任一非零（超时记 124），都是 `false`，`run.sh` 以 1 退出。跳过不是成功。

几点说明：

- 用多重集而不是集合：同一条命令合法地出现多次（`diagnostic-reads.py --self-test` 在三个 job 里各跑一次），集合会把「三次里只跑了两次」看成相等。
- 元素带 job id：命令从一个 job 挪到另一个 job 算一少一多。CI 上 job 是独立检出与独立环境，挪 job 不是无害的。
- `complete` 永远重算，不信任证据包里的值。`bundle.py verify` 从 git 读该提交的 `gates.yml`，核对 `gates_blob`，重算多重集与 `complete`，与包里的值不一致就判无效。
- 本地因环境跑不了的步骤照实记录：要么执行了且非零，要么（前面失败且没开 `--keep-going`）`executed = false`。两者都让 `complete = false`。没有任何路径能把跑不了的步骤记成成功。
- `--keep-going` 在某步失败后继续跑本 job 余下的步骤，这是 GitHub 不做的。它只用于本地摸清还有哪些步骤会失败，不改变 `complete` 的判定。

## 证据包 schema 与泄露规则

字段只有：`tree`、`gates_blob`、`substitutions[]`（`subject`、`replacement`）、`steps[]`（`job`、`name`、`command`、`exit_code`、`stdout_sha256`、`stderr_sha256`、`executed`）、`toolchain`（`seed_jar_sha256`、`java`、`cc`、`python`、`node`）、`complete`。任何层级出现其它字段都拒绝出包。

为什么是白名单：证据包是要交给别人的东西，它该证明的是「这棵树上这套门禁跑过、结果如何」，不该顺带公开跑它的机器。黑名单只能列出想到的泄露；白名单让时长、核数、内存、GPU、主机名、用户名、路径、镜像名、环境变量根本没有字段可放。自测对这些名字逐个证明被拒（在顶层、step、toolchain、substitution 四处各试一次）。

白名单挡不住「合法字段里装着路径」，所以每个字符串值还要过泄露过滤：含 `/` 或 `\`、含 `@`、形如主机名（点分标签、以字母结尾）、形如 IPv4 或 IPv6、含本机主机名或用户名，都拒绝，且生成器不写文件。

偏离任务单的一处：命令、步骤名、`uses:` 引用天然含 `/`（`./scripts/...`、`actions/checkout@v4`），按字面规则它们永远出不了包。所以豁免只给这三类字段，且只在值**逐字出现**在该提交的 `gates.yml` 里时成立。那是公开文本，验证者会重读；自由文本字段（`toolchain` 各项）没有豁免。替换 id 是 `gatesplan.py` 里的固定词表，不含 `/`。

`stdout`/`stderr` 只存 sha256。日志本身留在 `<out>/logs`，给跑的人排错用；哈希让事后可以把某份留存的日志对上某一步，但输出里有时间戳与临时路径，同一步两次运行的哈希一般不同，它不是可复现性声明。

## 后端契约

后端是一个 `backend_<name>.py` 模块，暴露 `create(ctx)`，返回的对象实现 `prepare()`、`run_job(job, artifacts)`、`toolchain()`、`cleanup()`。`run_job` 拿到的是 `gatesplan` 给的一个 job（有序的 run 步骤与带替换 id 的 use 步骤）和本次运行的制品目录，还回每个 run 步骤的 `executed`、`exit_code`、两个输出哈希。

分工：`gatesplan.py` 决定跑什么，后端决定在哪跑、每个替换 id 怎么实现，`bundle.py` 决定结果算不算完整，`runner.py` 只管调度（按 `gates.yml` 的定义顺序，即预期时长降序，最多 `--jobs` 个并行；有 `needs:` 的 job 等依赖结束后照跑，对应 `if: always()` 与 `if: !cancelled()`）。crun 后端因此只需新增 `backend_crun.py`，通过 `--backend crun` 选中，不改现有文件。后端专属选项走 `--backend-opt KEY=VALUE`，也不需要改 `run.sh`。

## 签名、落盘与 GitHub 侧核验（第 2 刀）

证据包能被任何人重算，但说不出是谁跑的。任何人都能写一份 `bundle.json`，所以没有签名的证据包只是声明。第 2 刀补上这一半，协议的摘要写在 [bootstrap.md](bootstrap.md)「GitHub 之外执行门禁集的证据协议」，这里记取舍。

新增文件：

- `allowed_signers`：一行，identity `dawn-gates`，`namespaces="dawn-gates"`，后接维护者专用钥 `~/.ssh/dawn-gates-sign` 的公钥。
- `verify_note.py`：读 note、拆信封、验签、核对提交，`--selftest` 在临时仓库里用两把一次性钥演示每条负控先红后绿。
- `publish.py`：本地复核、拒绝不完整的包、签名、本地验签、写 note、推 `refs/notes/gates`、派发工作流。`--dry-run` 停在推之前，`--dry-run-dispatch` 停在派发之前，`--remote` 可以是本地 bare 仓库；`--remote` 不是 `origin` 时拒绝派发，免得把一次演练派发到真仓库。
- `.github/workflows/verify-external.yml`：`workflow_dispatch`，输入 `sha`，一个 job，写 `gates/maintainer` status。

### 签什么

签名对象是 bundle 的规范字节：`json.dumps(bundle, sort_keys=True, separators=(',', ':'))` 加换行。不签信封文本，所以 note 可以缩进排版、便于人读；核验方把解析出的 bundle 重新规范化再验，签名绑定的是内容而不是排版。信封的 JSON 解析拒绝重复键：否则同一段文本在不同解析器下可能得出两个不同的 bundle。

签名用 `ssh-keygen -Y sign/verify`，namespace 固定为 `dawn-gates`。选 SSH 签名而不是 GPG：runner 自带 OpenSSH，不需要装钥匙环；公钥一行即可入库，信任根在仓库里而不在某个钥匙服务器上。

### 核验清单与共用代码

`verify_note.py` 逐项核，每一项都执行并打印，不在第一项失败时停：note、信封、签名、`tree == sha`、`gates_blob == git rev-parse <sha>:.github/workflows/gates.yml`、`bundle.check`、`complete`。其中 `bundle.check` 是从 `bundle.py verify` 里抽出来的函数，`bundle.py verify`、`publish.py`、`verify_note.py` 三处都调它，不存在第二份核验逻辑。替换表的「只含已知行」由它覆盖：`validate` 拒绝未知主语与未知替换 id，另外整张表必须逐行等于该提交 `gates.yml` 推出的那张，已知 id 挂错行也红。

核验方给泄露过滤传空的身份集合。泄露过滤里「本机主机名、用户名」一条保护的是生产者的机器，核验方不知道生产者叫什么；传入 runner 自己的名字只会让结论随运行地点变化。路径、主机名形状、地址形状这些形状规则照常生效。

### 偏离任务单的一处：核验器不取自被测提交

任务单写的是「checkout 该 sha」。实际做法是 `actions/checkout` 取派发所在的 ref（默认分支），再 `git fetch --depth=1 origin <sha> refs/notes/gates` 把被测提交当作对象读进来。理由：如果核验器与 `allowed_signers` 取自被测提交，一个改了 `allowed_signers` 或 `verify_note.py` 的提交就能给自己作保。`gatesplan.py` 本来就只从 git 对象读 `gates.yml` 与复合 action，不需要工作树。工作流的第一步还要求 `GITHUB_REF` 是默认分支，挡住 `gh workflow run --ref <别的分支>` 的误用。

这挡不住有写权限的恶意者：他可以在任何分支上写一个直接打 `success` 的工作流。commit status 的可信度上限就是仓库写权限，这一点写进了 bootstrap.md 的诚实边界。能脱离 GitHub 复核的是 note 里的签名。

### 失败也要写 status

status 步骤 `if: always()`，verify 步骤的 outcome 不是 `success` 就写 `failure`，包括前面的 fetch 失败导致 verify 被跳过的情况。只有输入不是 40 位十六进制时不写，因为那时没有可写的提交。沉默的失败与没跑无法区分。

### 实测

本地 bare 仓库演练（2026-09-23，详细记录在任务报告里）：浅克隆 + 按 sha 取对象与 notes + `verify_note.py`，对一个两步的小 `gates.yml` 合计约 0.6s；对真实 `gates.yml`（173 个 run 步骤）`verify_note.py` 本身不到 1s。托管 runner 上加上排队、起机与 `actions/checkout`，预计整个 job 在 15s 到 30s 之间；这是当时的估计。预算按 floor 记，timeout 5 分钟。

首次正向发布（2026-09-23 UTC，提交 14535104，main）的实测：

| 项 | 结果 |
|---|---|
| 证据包 | 集群全套 `--jobs 16`，墙钟 1722s（准备 26s），39/39 job 绿，175/175 run 步骤执行且退出 0，39 次隔离检查全部 0 条 |
| `publish.py` | 23:10:16Z 起，签名、推 `refs/notes/gates`、派发共约 10s |
| `verify-external.yml` run 35932235187 | 23:10:26Z 创建；verify job 23:10:30Z 起、23:10:37Z 完成，**job 7s**；run 23:10:38Z 结束，**派发到 status 落地 12s**。估计的 15s 到 30s 偏高 |
| `gates/maintainer` status | `success`，23:10:35Z，creator `github-actions[bot]`，描述 "Signed external run of the full gate set verified"，`target_url` 指向该 run |
| `release_evidence.py`（真实 API） | 第 1 条（`ci.yml` run 35929558799 绿）成立，第 2 条（外部 status）accepted，退出 0 |

此前 `verify-external.yml` 在真实 GitHub 上只跑过一次（run 35888113634，输入不是 40 位 sha，按设计失败且不写 status）。

## 第 3 刀：prefix、离线输入包与隔离证明

### 为什么

第 1 刀的本地后端拿宿主环境减去一张黑名单交给步骤，工具链就是机器上碰巧有的那套：本机 `python3` 是 3.14，而 3.14 会让 playground 合约变红（#170）；集群容器的 `JAVA_HOME` 是给 Hadoop 的 Java 8。黑名单只能删掉想到的东西。第 3 刀反过来：步骤看到的环境从空开始构造，每个路径都指进同一个 prefix 目录，prefix 里的工具链和输入由 `inputs.py` 下载并逐件校验。prefix 在哪由参数给，代码里不写死任何路径：本机是 `~/dawn-gates`，集群是持久盘上的一个目录，布局相同。

### 布局

`prefix.py` 的文件头写了完整布局：`toolchain/`（GraalVM CE 21.0.2、node 20.20.2、wasi-sdk 34、python 3.12.3；第 5 刀起还有 C 编译器 `gcc-13.3.0/`）、`inputs/`（下载原件、种子 jar 与 std、coursier 缓存、`MANIFEST.json`）、`jobs/<sha>/`（每 job 的检出与临时目录）、`home/`、`tmp/`、`cache/`、`out/<sha>/`。

### 输入包与锁

`scripts/gates-external/inputs.lock.json` 入库，记每件下载物的名称、版本、URL、sha256；下载物本身不入库。`inputs.py` 只认锁里的摘要，不认与文件同源的校验和（与 `wasm-target` 钉 wasi-sdk 的理由相同）。各件来源：

| 件 | 版本 | 来源与理由 |
|---|---|---|
| GraalVM | CE 21.0.2 | `setup-graalvm@v1` 对 `java-version: 21`、`distribution: graalvm-community` 取 graalvm-ce-builds 最新的 `jdk-21.*` tag，即 `jdk-21.0.2`（该仓库只有 21.0.0/21.0.1/21.0.2 三个）。CI 日志（run 35882535196）打印的正是 `GraalVM CE 21.0.2+13.1 (build 21.0.2+13-jvmci-23.1-b30)` |
| node | 20.20.2 | nodejs.org 官方 tarball，20 LTS 线。`wasm-target` 要 ≥ 20（`node:wasi`） |
| wasi-sdk | 34 | 版本与 sha256 照抄 `gates.yml` 的 `wasm-target` |
| python | 3.12.3 | ubuntu-latest（24.04）的 `python3` 是 3.12.3。用 python-build-standalone 20240415 的可重定位构建，同版本 |
| 种子 jar 与 std | 随 `scripts/seed-release.txt` | 从本机 `.dawn/seeds` 复制，按 `scripts/seed-checksums.txt`、`seed-std-checksums.txt` 校验。不在锁里再抄一份：那会是第二张每次发版都要推进的表，而 `advance-seed.sh` 不知道它 |
| coursier 缓存 | `selfhost/dawn.lock` | 在 prefix 里用 `COURSIER_CACHE` 指向 `inputs/coursier` 跑一次 `./bin/dawn --version` 收集；三个 jar 按 `dawn.lock` 的 artifact 摘要核对 |
| C 编译器 | gcc 13.3.0（运行时 14.2.0） | 第 5 刀加的，十个 conda-forge 包，见「第 5 刀」一节 |
| pip wheel | zstandard 0.23.0 | 第 5 刀加的，只给 `inputs.py` 解 `.conda` 用，门禁步骤看不到它。此外 `gates.yml` 的步骤只用标准库。唯一用 PyYAML 的是 `gatesplan.py` 自己，它只在控制端解析计划；远端执行半边不 import 它（`import yaml` 挪进了解析函数） |

`MANIFEST.json` 在 prefix 里，记每件的相对路径、字节数、文件 sha256 或目录树摘要。`verify` 逐件重算，下载物同时对锁核对，所以改了 MANIFEST 也替改过的原件作不了保。目录树摘要只取文件名、内容、属主可执行位与符号链接目标：普通用户解包受 umask 影响、root 解包保留原模式，同一个包要在两边都核得过。`__pycache__` 也不计入：python-build-standalone 不带字节码，解释器首次 import 标准库时写在旁边，并且自己按源文件校验它。第一次实测就是这一条红的。

### 执行壳

prefix 模式下一个 job 的环境等价于 `env -i` 加白名单：`PATH` = prefix 各工具链 bin + `/usr/bin:/bin`（git、bash、curl、coreutils 仍来自系统；cc 在第 5 刀之前也是，之后是输入包里的，见「第 5 刀」）；`JAVA_HOME`、`GRAALVM_HOME` 指 prefix 的 GraalVM；`HOME`、`TMPDIR`、`RUNNER_TEMP`、`XDG_CACHE_HOME`、`COURSIER_CACHE` 都在 prefix 下；`LANG=C.UTF-8`（ubuntu-latest 的值；没有 locale 时 JVM 的文件名编码退回 ASCII）；`CI=true`；加上本地后端本来就设的每 job `GITHUB_*`。

`XDG_CACHE_HOME` 与 `COURSIER_CACHE` 取的是 runner 上的默认位置（`$HOME/.cache`、`$HOME/.cache/coursier/v1`，`HOME` 在 prefix 里），coursier 缓存从输入包恢复到那里。第 3 刀曾把它们放在 prefix 单独的 `cache/` 下；第 3b′ 刀在当前 main 上跑全套时，`configured-lsp-contract.py` 与 `source-parse-counts.py` 以退出 2 红：它们不看 `COURSIER_CACHE`，直接在 `~/.cache/coursier/v1/https` 下找 ASM 9.7.1，而 CI 的工具链 action 恰好把缓存恢复在 `~/.cache/coursier`。环境与 CI 不同的地方就是会被某个脚本读到的地方，所以改成与 CI 相同，而不是改脚本。

偏离任务单的一处：白名单里**没有** `DAWN_SEED`。CI 不设它；设了会让 `seedjar.sh` 跳过校验并打印一行 CI 不会打印的警告。种子照 cache restore 的方式拷进 `.dawn/seeds`，`seedjar.sh` 照常校验。

另一处：prefix 模式的检出是 `git clone --shared`，不是 `git worktree add`。worktree 会往源仓库的 `.git/worktrees` 写东西，那在 prefix 外面。

不给 `--prefix` 时行为不变，#171 的验收走的那条路径原样保留。

### 隔离证明

`prefix.py check-isolation` 在 prefix 里放一个 marker，跑命令，再对 `/` 与 prefix 所在文件系统各做一次 `find -xdev`（剪掉 `/proc` `/sys` `/dev` `/run`、prefix 本身与 `--exclude` 列出的路径），列出 mtime 或 ctime 新于 marker 的一切。

实测中查出并修掉的一处：HotSpot 把 `hsperfdata_<用户>` 写在写死的 `/tmp`，不看 `TMPDIR`。第 3 刀只在后端探测 JDK 版本的那次 `java -version` 命令行上加了 `-XX:-UsePerfData`，门禁步骤自己起的 JVM 仍然写，集群全套运行后 `/tmp/hsperfdata_root` 的 mtime 落在运行窗口里。

第 3b′ 刀改成 prefix 布局的一部分：`inputs.py` 解包 GraalVM 之后把 `bin/java` 改名 `bin/java.real`，在原位置写一个 shim，`exec` 同目录的 `java.real` 并把 `-XX:-UsePerfData` 放在调用者参数之前。shim 的内容与 prefix 在哪无关（它按自己的位置找 `java.real`），所以工具链的目录树摘要在本机与集群上相同。锁里的 GraalVM 条目不变：原件还是那些字节，shim 是 `build`/`install` 解包后写的；`MANIFEST.json` 记下原件里 `bin/java` 的 sha256，`verify` 核 `java.real` 等于它、shim 逐字节等于 `inputs.py` 里的那份。不用 `JAVA_TOOL_OPTIONS`/`JDK_JAVA_OPTIONS`：它们让每个 JVM 往 stderr 打一行 `Picked up ...`，改变被测输出。第一版只包了 `java`，理由是门禁里起 JVM 的都是它；这个判断错了：incremental 家族的七八个合约脚本直接跑 `javac --release 21` 与 `jar cf`，`configured-lsp-contract.py` 也按 `$JAVA_HOME/bin/javac` 调用。所以现在 `bin/` 里每个普通文件启动器都换成 shim（符号链接如 `native-image` 指向 `lib/`，不动）：`java` 前置 `-XX:-UsePerfData`，其余前置 `-J-XX:-UsePerfData`（JDK 启动器把 `-J` 选项交给自己的 JVM）。`MANIFEST.json` 记原件里每个启动器的 sha256（从原件读，不从解包后的树读）。

shim 还要保住 `argv[0]`。第一版用 `/bin/sh` 直接 `exec .../java.real`，进程的 `argv[0]` 就成了 `java.real`；`scripts/selfhost-bench.py` 按 `argv[0]` 的基名是不是 `java` 认 JVM，于是 `compiler-weight-contract` 与 `dependency-heap-contract` 在集群全套里以「role parent/compiler is missing an actual MaxHeapSize」红。现在 shim 是 bash，`exec -a "$0"` 保留调用者的 `argv[0]`；启动器按 `/proc/self/exe` 找自己的 home，`java.home` 不变。shim 也不再 fork（不用 `dirname`/`readlink`，用 `${0%/*}`）：exec 之前进程还是 bash，而那个 bench 每 2ms 采一次 `/proc`。带 fork 的版本在本机把 `compiler-weight-contract` 的一个变异体对照跑红过一次（`sampling-200ms` 多红了 `bench.vmhwm_reads_proc`），另两次绿；不 fork 的版本在集群上两个 job 各连跑两次全绿，隔离 0 条。

负控（本机，`bwrap` 给命令一个私有 `/tmp`）：在 prefix 里的新检出上跑会触发重建的 `./bin/dawn --version`，没有 shim 时私有 `/tmp` 里出现 `hsperfdata_dawn`，有 shim 时为空。逐个启动器同样：`java.real -version`、`java.real -cp . A`、`javac.real -d`、`jar.real cf` 各留下 `hsperfdata_dawn`，经 shim 的同一命令都为空。把 `java.real` 或 `javac.real` 改一个字节，`inputs.py verify` 红（目录树摘要与「不是原件的启动器」两条），复原后绿。

共享工作站上 `find` 不可能为空：本机同时有别的写者、编辑器、定时任务（零点的 dpkg 备份与 logrotate 就撞进过一次窗口）。所以本机的证明分两层：

- `--readonly-root`：用 bubblewrap 让命令看到的整个文件系统只读、只有 prefix 可写。命令在里面跑绿，说明它不需要往 prefix 外写任何东西；往外写会直接失败，而不是事后被找到。
- 同一次运行里的 `find` 清单只剩被沙箱挡在外面的进程写的东西（`/tmp`、`/var/tmp` 目录的 mtime），`--exclude` 列出的其余写者随结果打印。

集群容器上没有 bubblewrap（也不允许 apt），只用 `find`。

### 实测（2026-09-23，本机）

| 项 | 结果 |
|---|---|
| `inputs.py build`（冷） | 93s；下载 GraalVM 275.3 MiB 23.2s、node 25.0 MiB 4.5s、wasi-sdk 183.5 MiB 12.5s、python 64.2 MiB 7.3s；coursier 预热（`./bin/dawn --version`）33s |
| 解包后 | GraalVM 536.0 MiB、node 152.7 MiB、wasi-sdk 593.1 MiB、python 239.1 MiB；种子 18.9 MiB、std 0.6 MiB、coursier 10.8 MiB |
| `inputs.py verify` | 绿，约 1.8s；改 node 原件一个字节后红（对锁与对 MANIFEST 两条都报），复原后绿 |
| 环境负控 | `prefix.py selftest` 绿；`--break-env-i`（宿主环境垫在下面）红，宿主的 `JAVA_HOME`、PATH 项与只在宿主存在的变量三项全部泄入 |
| 隔离负控 | 在壳里写 `/tmp/<文件>`，`check-isolation` 红，列出该文件 |
| `run.sh --sha 0a0b46e8 --backend local --prefix ~/dawn-gates --only tree-policy` | 5 步全绿，job 107s；`--readonly-root` 下同样 5 步全绿 |
| 工具链字段 | `java` = `21.0.2+13-jvmci-23.1-b30`（与 CI 日志一致），`python` = `3.12.3`，`node` = `v20.20.2`，`cc` = 本机 gcc 13.3 |
| #170 | 在 prefix 里用 python 3.12.3 单跑 `playground/test/contract.sh`：10 passed，20s。同一检出换宿主 3.14.7：`socket closed inside a frame` 红 |
| 离线 | 在 `bwrap --unshare-net` 里对新 clone 跑 `./bin/dawn --version`：成功，coursier 全部命中 prefix 缓存 |

### crun 后端（`backend_crun.py`）

集群容器没有外网，`JAVA_HOME` 是 Hadoop 的 Java 8，python 与 gcc 是镜像自带的。所以 crun 后端自己不在集群上执行任何门禁逻辑：它把输入包与本目录的工具送过去，每个 job 在集群上跑 `prefix.py run-job`，而 `run-job` 就是 prefix 模式的本地后端。两边执行 job 的是同一份代码，证据包的工具链字段因此必须与本机 prefix 运行一致；这个相等就是「后端只换了在哪跑、没换跑什么」的判据。

流程：

1. 本机 staging 目录（在本机 prefix 的 `stage/` 下，不在 worktree 里）放本目录的工具、一个 git bundle（该提交加全部 tag）、每个 job 一份 JSON、一个 `.crun.yaml`。`remote_root` 是 `<集群 prefix>/jobs/<sha>/tree-<工具摘要>`，按提交与工具版本唯一，不会与别的项目互相 `rsync --delete`（第 5 刀之前只按提交区分，见该节「途中查出」）。`.crun.yaml` 不进仓库。
2. 在集群上跑 `inputs.py verify`。缺或红时，用第二个 staging 目录（硬链接到本机 prefix 的 `inputs/`）推到 `<集群 prefix>/inputs`，先用 `tar` 解出 python（此时 prefix 里还没有解释器），再由 `inputs.py install` 解包其余工具链并整体复核。
3. 每个 job 一次 `crun run -n 0 --no-build -- env -i ... prefix.py run-job`，并行度由 `--jobs` 给。crun 从控制端每次都会推一次 staging 目录，未变时 3s 左右，推送由 crun 自己串行化。（2026-09-25 起改为 `-d` 后台运行加轮询，见「集群运行可续」一节。）
4. `run-job` 把结果片段打印成一行、同时存进 `<集群 prefix>/out/<sha>/<run>/fragments`；日志与制品留在集群的 `out/<sha>/<run>/`，不拉回。本机只解析片段，照常由 runner 合成 `bundle.json`。

偏离任务单的三处：

- staging 不是「该 sha 的 detached worktree」。job 要历史（tree-policy 回读到上一个 tag 的 Emit-Change 声明、重放钉住的提交），而且每个 job 本来就要自己的新检出。worktree 的 `.git` 只是指回本机仓库的指针，到了集群上没有意义。所以送的是 git bundle（0a0b46e8 上 12.9 MiB），集群上 `git clone --bare` 一次，各 job 再 `git clone --shared`。
- 集群上的输出按控制端的运行 id 再分一层（`out/<sha>/<run>/`）。同一提交跑第二次时，上一次的制品还在，`upload-artifact` 的重名检查会让它失败。
- 集群上的隔离检查把 marker 放在 prefix 里，而不是 `/`：往 `/` 写 marker 本身就违反「不写 prefix 之外」。`find` 的根仍然是 `/`，另加 prefix 所在文件系统的挂载根（集群上是 `/data0` 下的个人目录，与 `/` 不是同一个文件系统）。

集群侧的 prefix 路径由 `--backend-opt remote-prefix=` 给，代码里没有默认值：共享集群盘上的路径含个人用户名，不该进公开仓库。

另一处范围外改动：`scripts/gate-map/unseen.txt` 加了 `inputs.py`、`inputs.lock.json`、`prefix.py`、`backend_crun.py` 四行。gate map 的棘轮要求每个新文件要么有门禁看着、要么在这里写明为什么没有，不加 tree-policy 就红（本机 prefix 实测过一次红）。

### 实测（2026-09-24，集群 B200 编译机容器，`crun run -n 0`）

| 项 | 结果 |
|---|---|
| 首次推送 staging（工具 + bundle，13.6 MB） | 23s |
| 首次送输入包（578 MiB）并在集群上解包、复核 | 604s；之后每次 `inputs.py verify` 绿，推送加复核约 10s |
| `--only tree-policy`（带 `isolation=1`） | 5 步全绿，job 176s（含隔离检查的两次 `find`）；`check-isolation` 在 `/` 与 prefix 所在文件系统上 0 条 |
| 工具链字段对比本机 prefix | `java`、`node`、`python` 逐字相同（`21.0.2+13-jvmci-23.1-b30`、`v20.20.2`、`3.12.3`）；`cc` 不同（本机 gcc 13.3，集群 gcc 11.4），当时记在「不做的」，第 5 刀已收 |
| 全套 `--jobs 16` | 墙钟 1348s（本机 `--jobs 8` 是 4969s）；35 个 job 里 31 个全绿；131 个 run 步骤执行 114 个，110 个退出码 0；`complete = false`；`bundle.py verify` 复算一致；种子摘要与 `seed-checksums.txt` 一致 |

四个红 job 全部是集群环境造成的，不是替换表或 prefix 的问题，照实记录、没有改仓库源码：

| job | 红的步骤 | 原因 |
|---|---|---|
| `contracts` | `atomic-write-contract/run.sh`（exit 1） | 容器里是 root。脚本自己拒绝：`this contract must not run as root: the unwritable-directory cases cannot fail for root` |
| `java-target-classpath` | `java-target-classpath-contract/run.sh`（exit 1） | 同为 root：`unreadable-lock did not fail closed`，root 读得了 `chmod 000` 的文件 |
| `wasm-target` | 钉住的 wasi-sdk（exit 28，curl 超时） | 容器没有外网。prefix 里有同一个包，但步骤自己下载，见「不做的」 |
| `docs` | `playground/test/contract.sh`（exit 127） | 合约本身 10 passed、0 failed（python 3.12.3 下 #170 同样不复现），收尾的 `fuser -k` 找不到命令：容器没有 psmisc，而本任务不许 apt。其后的 site 构建（`npm install` 要外网）因此没有执行 |

全套运行没有套隔离检查（任务单只要求一次，放在不起 JVM 的 tree-policy 上）。事后只读查看，容器里 `/tmp/hsperfdata_root` 的 mtime 落在全套运行窗口内，目录为空：门禁步骤起的 JVM 在 prefix 外留了痕迹，就是「不做的」里 hsperfdata 那一条。在集群上它违反「不写 prefix 之外」，修法（每 job 一个指进 prefix 的私有 `/tmp`，要容器允许 `unshare -m`）尚未验证。第 3b′ 刀已收掉：启动器 shim 关掉 hsperfdata，私有 `/tmp` 实测可用，全套 39 个 job 都套了隔离检查，见下节。

要在集群上拿到 `complete = true`，还差：以非 root 身份执行 job（例如 `setpriv` 降到一个无特权 uid，prefix 相应 chown，不需要写 prefix 外）；`wasm-target` 能用预置的 wasi-sdk；`fuser` 进输入包或合约不再依赖它；npm 依赖进输入包。前一条是后端的事，后三条要改 `gates.yml` 或被测脚本，都不在本刀。（第 3b′ 刀：非 root、wasi-sdk、npm 三条已做；`fuser` 由 #173 从合约里去掉。）

## 第 3b′ 刀：集群跑到 complete

第 3 刀的集群全套 31/35 绿，四个红 job 全是容器事实，另有 hsperfdata 一条隔离破规。本刀逐条收掉，每条一个提交。

### 非 root 执行

容器里只有 root；CI 的每个 job 是普通用户，`atomic-write-contract` 与 `java-target-classpath-contract` 的 unreadable-lock 都在 root 下必红（root 读得了 `chmod 000`、写得进不可写目录）。做法：`prefix.py run-job --run-as 20000:20000` 以 root 启动，先把 prefix 里 job 该写的部分（`home/`、`tmp/`、`cache/`、`repos/<sha>.git`、`jobs/<sha>`、`out/<sha>`）交给该身份，只改属主不对的条目；再经 `setpriv --reuid --regid --clear-groups --no-new-privs` 以该身份重新执行自己。`toolchain/` 与 `inputs/` 仍归 root，job 改不了量它的工具链。

选 `setpriv` 不选 `unshare -U`：用户命名空间若把 job 的 uid 映射到真 root，prefix 外所有 root 的文件在 job 眼里都成了自己的，照样可写；真实的 uid 切换让它们仍归 root。uid 20000 在容器的 `/etc/passwd` 里没有条目，这是有意的：借镜像里现成的 `nobody`，就与容器里别的以 `nobody` 跑的东西共享 prefix 的写权限。没有条目的代价实测过：JVM 的 `user.name` 是 `?`，`user.home` 回落到 `$HOME`（prefix 的 `home/`），python 的 `~` 同样取 `$HOME`。反倒是以 root 跑时 JVM 的 `user.home` 取自 passwd，是 prefix 外的 `/root`。

uid 切换挡不住 `/tmp`、`/var/tmp`、`/dev/shm`：它们人人可写。第一次非 root 试跑时两个 job 的隔离检查都报了 `/tmp` 的 mtime（目录里没留下东西，是建了又删）。容器是多人共用的，这一条分不清是谁写的；门禁里的 JVM 本来就会写：`java.io.tmpdir` 不看 `TMPDIR`，默认就是 `/tmp`。所以 job 另得一个私有 mount 命名空间（容器允许 `unshare -m`，实测过），里面这三处各是 prefix 里一个每 job 的目录（`jobs/<sha>/<run>-<job>-shared-tmp/`）的 bind mount。这与 CI 一致：每个 job 是一台新 VM，`/tmp` 本来就是它自己的。`run-job` 在 job 结束时记录私有 `/tmp` 有没有被动过，于是「job 自己用了 `/tmp`」与「别的租户写了真 `/tmp`」分得开；后者仍由外面的 `check-isolation` 看见。`run-as=root` 是负控，`private-tmp=0` 保留共享的三处。

实测（2026-09-24，集群，08a5232e，`--only contracts-2,java-target-classpath --jobs 2`，`isolation=1`）：

| 运行 | 结果 |
|---|---|
| uid 20000，共享 `/tmp` | 两个 job 全绿（415s、454s）；隔离检查各报 `OUTSIDE /tmp` 一条 |
| uid 20000，私有 `/tmp`（默认） | 两个 job 全绿（415s、452s，墙钟 501s）；隔离检查各 0 条；两个 job 的私有 `/tmp` 都被动过、结束时 0 个条目，所以上一行的 `/tmp` 是 job 自己写的 |
| `run-as=root`（负控） | `contracts-2` 的 atomic write 退出 1：`this contract must not run as root`；`java-target-classpath` 第一步退出 1：`unreadable-lock did not fail closed on stderr with exit 1` |

负控第一次跑时两个 job 都在检出一步失败：上一次以 uid 20000 建的 `repos/<sha>.git` 归 20000，git 以 root 打开时报 dubious ownership。所以 root 模式下 `run-job` 同样把可写部分交回 root。

### wasi-sdk 步骤离线

`gates.yml` 的 `wasm-target` 里「the pinned wasi-sdk」一步改成：`${WASI_SDK_TARBALL:-}` 指向一个文件就 `cp` 它，否则照旧 `curl`；之后的 `sha256sum -c` 不动，两条路径都执行。钉住的是摘要，字节从哪来不改变它核的是什么。CI 不设这个变量，走 `curl` 分支，行为与墙钟都不变：改动只是一个分支条件，没有新的下载或计算（`check-gate-budgets.py` 照旧绿，不动预算行）。prefix 的白名单环境设它，指向 `inputs/downloads/` 里 `inputs.py` 按锁核过的原件；替换表因此多一行 `adjust:wasi-sdk-tarball`。

负控（本机，直接执行该步骤的 `run:` 原文）：变量指向改了一个字节的原件，`sha256sum` 报 `FAILED`，退出 1；指向输入包原件、在 `bwrap --unshare-net` 里跑，`OK`，退出 0；不设变量、同样无网，`curl` 报 `Could not resolve host`，退出 6；不设变量、有网（CI 的路径），`OK`，13s。

### npm 依赖离线

`inputs.lock.json` 加 `npm_caches` 一项：`site/play-ui/package-lock.json` 的 sha256。`inputs.py build` 在 prefix 里拷出 `package.json` 与这份 lockfile，用 prefix 的 node 跑 `npm ci --ignore-scripts`，缓存落在 `inputs/npm-cache`（26 个包，7.1 MiB，3s），再删掉 npm 自己的 `_logs`。锁钉的是 lockfile 而不是缓存的字节：npm 的索引里带时间，两次填出来的缓存不同；每个 tarball 从缓存取出时 npm 按 lockfile 的 `integrity`（sha512）核，所以钉 lockfile 就钉住了内容。`MANIFEST.json` 记这次填出的缓存的目录树摘要，`verify` 按它核，并核 lockfile 摘要与锁一致（给 `--repo` 时还核仓库里的 lockfile）。某个提交改了 lockfile，锁就得一起改，否则 `build` 拒绝；而旧缓存下那个提交的 `npm install` 会 `ENOTCACHED` 红，不会静默联网。

job 看到的是 `cache/npm`，由后端在 prepare 时从 `inputs/npm-cache` 拷一份（按摘要判断是否需要重拷），因为 npm 离线也会往缓存里写。环境里 `npm_config_cache` 指向它、`npm_config_offline=true`，`gates.yml` 与 `site/build.sh` 都不改。`site/build.sh` 之后没有别的步骤联网（`vite build`、`gen-builtins` 都只读本地）。

负控（本机，`bwrap --unshare-net`，prefix 环境）：完整缓存下 `npm ci --offline` 装上 26 个包，退出 0；删掉缓存里 `@codemirror/state` 的内容文件后 `ENOTCACHED`，退出 1；`site/build.sh` 用的 `npm install --silent`（只靠环境注入的离线）退出 0。端到端：整个 `run.sh --only docs`（08a5232e，本机 prefix）套在 `bwrap --unshare-net` 里跑，6 步全绿，job 268s，`site/build.sh` 的日志里 `vite build` 建出了 `playground.js`（765.56 kB），不是跳过。

一处与 CI 不同，照实记下：prefix 的 node 20.20.2 带 npm 10.8.2，`npm install` 会改写检出里的 `package-lock.json`（去掉 npm 11 写进去的 `libc` 字段）。CI 的 `lts/*` 自带的 npm 版本不同。之后没有步骤检查工作树是否干净；`site-dist-diff.sh` 的快照里带着改写后的文件，但 JVM 与 native 两条腿读的是同一份快照，比较不受影响。这属于「不做的」里「node 版本与 `lts/*`」那一条。

### 途中查出的三处 prefix 与 CI 的差异

跑全套时又红了三处，都是 prefix 的环境与 CI 不同，都改在 `scripts/gates-external/`，没有改被测脚本：

1. **coursier 缓存的位置。** 见「执行壳」一节：两个脚本直接读 `~/.cache/coursier/v1`。
2. **只包了 `java`。** `javac`、`jar` 起的 JVM 照样写 hsperfdata。改成包 `bin/` 里全部启动器，见「隔离证明」。
3. **shim 改了 `argv[0]`。** `selfhost-bench.py` 按 `argv[0]` 认 JVM，两个 heap 合约红。改成 `exec -a`，见「隔离证明」。

### 实测（2026-09-24，第 3b′ 刀，集群 `--jobs 16`，每个 job 套隔离检查）

| 运行 | 墙钟 | 结果 |
|---|---|---|
| main 97af76ce（第 2、3 处修正之前） | 1570s | 39 个 job 里 36 个绿；红：`wasm-target`（main 的 wasi-sdk 步骤还只会 `curl`，exit 28）、`compiler-weight-contract` 与 `dependency-heap-contract`（上面第 3 处）。39 次隔离检查全部 0 条 |
| 5f18182b（main 984d2076 + 本刀） | 1730s | **`complete = true`**，175 个 run 步骤全部执行、全部退出 0，39 个 job 全绿；39 次隔离检查全部 0 条；`bundle.py verify` 复算一致 |

5f18182b 那次各 job 的秒数（含 crun 推送与两次 `find`）：最长的是 `incremental-2` 921s、`test` 884s、`syntax-mutants-1/2` 878/871s、`incremental-4` 867s；`wasm-target` 497s（wasi-sdk 走输入包），`docs` 449s（npm 离线）。工具链字段：`java` `21.0.2+13-jvmci-23.1-b30`、`python` `3.12.3`、`node` `v20.20.2`、种子 `a320e3ee…e679`，`cc` 是集群的 gcc 11.4。

本机 prefix 全套（5f18182b，`--jobs 8`，load 约 28）：墙钟 4893s，39 个 job 里 38 个绿，`complete = false`。红的是 `compiler-weight-contract` 的一个变异体对照：`sampling-200ms` 预期只让「采样间隔」一条断言红，负载下 `bench.vmhwm_reads_proc` 也红了。不是 shim 造成的：同一检出单跑这个合约，用不带 shim 的同一 GraalVM 构建，在 24 个 busy loop（load 约 25）下以逐字相同的断言红过；空闲时带 shim 本机两次绿、集群三次绿。两份证据包的 `toolchain` 里 `java`、`python`、`node`、种子摘要相等，`cc` 不等（集群 gcc 11.4、本机 gcc 13.3，cc 当时不在输入包里；第 5 刀已收，见该节）。

私有 `/tmp` 也说明了它为什么必要：5f18182b 那次有 20 个 job 结束时在自己的 `/tmp` 里留了东西（`dawn-selfhost-stdlib`、`dawn-selfhost-lsp-def`、`dawn-lsp-standalone-close-*.tmp`、`dawn-map-fold-*`、`dawn-spike-io-cli` 等）。这些是门禁脚本与 JVM 直接写 `/tmp` 的产物，CI 上随 VM 消失；没有私有 `/tmp` 时它们会留在共享容器的 `/tmp` 里。没有一个 job 留下 `hsperfdata_*`。

## 第 5 刀：C 编译器进输入包

### 为什么

第 3 刀之后，步骤里只剩 C 编译器还取自 `/usr/bin`：同一个提交，集群的证据包写 `cc` = gcc 11.4，本机写 gcc 13.3。集群的 gcc 11.4 带 ASan，`native-diff` 因此能绿，但它不是 CI 用的编译器，证据包也就说不清跑的是什么。

### 选什么

先看 CI 实际用什么。`gates.yml` 里 C 编译器只有两种来路：`wasm-target` 自己下载钉住的 wasi-sdk，把 `DAWN_WASM_CC` 写进 `GITHUB_ENV`，这一半第 3b′ 刀已在输入包里；其余全部是 ubuntu-latest 的 `cc`。`wasm-target` 的 C driver 一步与 `java-target-classpath-contract` 直接写 `cc`，其余脚本写 `${CC:-cc}`，native driver（`nmain.dawn`）不设 `CC` 时也用 `cc`。ubuntu-latest（24.04）的 `cc` 是 gcc 13.3.0，而它的 `libasan8`、`libgcc-s1`、`libstdc++6` 由 gcc-14 构建（14.2.0-4ubuntu2~24.04，本机与 runner 同一发行版，`dpkg -l libasan8` 可见）。所以要钉的是「gcc 13.3.0 编译器加 gcc 14.2.0 运行时」这一对。

| 候选 | 结论 |
|---|---|
| LLVM 官方预编译 tarball | 否。是 clang，不是 CI 用的编译器；18.1.8 为 1.04 GB，19.1.7 为 1.65 GB，20.1.8 为 2.02 GB（GitHub 返回的 `content-length`），按 0.6 MB/s 推到集群要 30 到 55 分钟 |
| Ubuntu 24.04 的 deb（gcc-13、libasan8 等） | 否。对 glibc 2.39 构建，集群容器是 glibc 2.35，编译器本身与它链出的程序都可能起不来 |
| zig cc | 否。不带 ASan 运行时，`spike-native` 缺 ASan 即失败 |
| conda-forge 的 gcc 13.3.0 | 采用。可重定位；编译器二进制对 glibc 2.17 构建，只依赖 libc、libm、libdl；自带 sysroot，glibc 版本可选 |

包清单（`inputs.lock.json` 的 `conda_toolchains`，十个，共 121 MiB）：`gcc_impl_linux-64` 13.3.0；`gcc` 13.3.0，只含 `bin/cc`、`bin/gcc` 等指向 `x86_64-conda-linux-gnu-gcc` 的符号链接，所以 `cc` 这个名字也来自上游，输入包里没有手写的文件；`libgcc-devel_linux-64` 13.3.0；`binutils_impl_linux-64` 与 `ld_impl_linux-64` 2.42（24.04 的 binutils 也是 2.42）；`sysroot_linux-64` 2.34 与 `kernel-headers_linux-64` 5.14.0；运行时 `libsanitizer`、`libgcc`、`libstdcxx` 14.2.0。

两处取舍：

- **sysroot 选 2.34，不选 CI 的 2.39。** 链出的程序在宿主上用宿主的 `libc.so.6` 运行，要求的符号版本不能新于宿主。集群是 2.35，2.34 是不超过它的最新一版（conda-forge 另有 2.17、2.28、2.39）。头文件因此与 CI 不同；`-std=c11` 下的运行时没有用到 2.34 与 2.39 之间新增的接口，下面的集群全套为证。
- **运行时是 14.2.0，不是与编译器同源的 13.3.0。** 这不只是为了与 CI 一致。conda-forge 的 gcc 13.3.0 自带的 libasan 在本机内核上（高熵 ASLR，mmap 随机化 32 位）随机死于 `AddressSanitizer:DEADLYSIGNAL`：一个最小的 ASan 程序连跑 50 次，9 次卡死；换成 14.2.0 的 libasan，100 次 0 次；宿主的 Ubuntu 组合 50 次 0 次。`scripts/spike-native/run.sh` 在 ASan 不可用时 fail-closed，这种随机失败会直接变成门禁的偶发红。libasan.so.8 的 ABI 在 13 与 14 之间不变，Ubuntu 这样配也是这个道理。

### 解包与重定位

`.conda` 是 zip，里面是 zstd 压缩的 tar。prefix 的 python 3.12 没有 zstd 模块，集群容器有没有 `zstd` 命令不知道，也不许装。所以锁里另钉一个 `zstandard` 0.23.0 的 cp312 wheel，由 prefix 的 python 带着它解包（`inputs.py conda-unpack`，`build` 与 `install` 都调它）：两边是同一个解释器、同一份代码，不依赖宿主工具。解包按每个包自己的 `info/paths.json` 核：只解出其中列出的文件（`gcc` 包 payload 里的 `info/licenses/LICENSE` 这类 conda 留在包缓存、不链进环境的文件跳过），多一个少一个都拒绝，每个普通文件按其中记录的 sha256 核，两个包给出同一路径也拒绝。

这十个包里有 85 个文本文件带着构建前缀的占位符（gcc 的 `specs`、binutils 的链接脚本、sysroot 的 clang 配置等），`conda install` 会把占位符换成安装位置，`inputs.py` 照做。其中 gcc 的 `specs` 给每次非静态链接加 `-rpath <工具链>/lib`，ASan 程序就是靠它找到输入包里的 libasan：不这样，本机会悄悄用上宿主的 libasan8，集群上只有 gcc 11 的 libasan6，程序起不来。代价是这些文件里写着 prefix 的绝对路径，所以目录树摘要对它们先把实际位置换回占位符再算（`MANIFEST.json` 的该行记下是哪些文件、各自的占位符），同一份包解在任何位置摘要都相同。实测：在一个目录 `build`，把 `inputs/` 硬链接到另一个目录再 `install`，摘要一致、`verify` 绿，后者 `specs` 里的 rpath 指向后者。

### 注入：只动 PATH

步骤找编译器只有一种方式，PATH 上的 `cc`（上面三种写法都归结于此）。所以白名单只改了一项：`PATH` 在 `/usr/bin` 之前加上 `toolchain/gcc-13.3.0/bin`。偏离任务单的两处：

- **不设 `CC`。** CI 不设它。设成绝对路径对 `${CC:-cc}` 等价，对直接写 `cc` 的两处无效，PATH 反正要改；多设一个 CI 没有的变量，只是多一处与 CI 的差别。仓库自己也这么看：`scripts/selfhost-bench.py` 把 `CC` 列在 `POLLUTING_ENV` 里，环境里有它就拒绝测量。
- **不设 `DAWN_WASM_CC`。** 它由 `wasm-target` 自己的步骤写进 `GITHUB_ENV`，指向输入包里已有的 wasi-sdk；全局设它，别的 job 就会看到 CI 上没有的变量。

`prefix.py selftest` 多了一条「`cc` 是输入包的」；`--break-env-i`（把宿主环境垫在下面）时它与另三条一起红，报 `/usr/bin/cc`。

### 不进替换表

任务单要求在替换表登记，没有加行，理由是实测出来的。`substitutions` 由提交的 `gates.yml` 推出，核验方（`verify-external.yml` 用默认分支的 `gatesplan.py`）要求证据包里的表逐行等于它推出的表。无条件加一行 `adjust:cc-input-pack`，已发布的 14535104 的证据包（`refs/notes/gates` 上那份，sha256 `f866a2b7…`）立刻核不过：`bundle.py verify` 从 `COMPLETE` 变成 `INVALID substitutions: not the table this tree's gates.yml produces`。也找不到按提交区分的条件：编译器是 runner 的事，不在 `gates.yml` 里。它与 python、node、java 同类，第 3 刀起那三者只记在 `toolchain` 字段，不占替换表的行；`cc` 现在一样，而 `toolchain.cc` 的值 `cc (conda-forge gcc 13.3.0-2) 13.3.0` 本身就写明了来源。

### 与并行使用者兼容

本机 `~/dawn-gates` 与集群 prefix 同时被别的分支的旧 `inputs.py` 使用。旧 `verify` 只读 `MANIFEST.json` 的 `items`，按它自己的锁给每个 download 行取摘要（新包名不在旧锁里，会抛异常），并且不做重定位就算目录树摘要（`cc` 那一行会红）。所以新行放在新键 `conda_items` 下，旧工具看不见。同一理由的两处小改：`build` 写 MANIFEST 改为先写临时文件再改名；npm 缓存在仍然完好时沿用上次的，不再每次重填（重填的字节必然不同，会在别人用着时改掉缓存和摘要）。实测：本机 prefix `build` 前后 `items` 除 `download_seconds` 外逐项相同；改动前的 `inputs.py verify` 在新包上绿（本机与另一目录各一次）。

### 途中查出：staging 只按提交区分

第一次集群全套（b2e19e06，本分支的工具）的证据包 `toolchain.cc` 是 `null`：39 个 job 里 21 个报输入包的 gcc 13.3，18 个报容器的 gcc 11.4，`crun backend: jobs disagree on toolchain.cc`。原因不在编译器：本机 staging 目录是 `stage/jobs/<sha>`，远端树是 `jobs/<sha>/tree`，只按提交区分；而 origin/main 的头正是别的写者会拿来当基线跑的提交。本次 prepare 之后一分钟（10:05:33），另一个分支的控制端用它自己的旧工具重新 stage 了同一个 sha，此后每次 crun 推送都把旧的 `prefix.py` 推到同一个远端树，后启动的 job 跑的就是它（事后本机 staging 里的 `prefix.py` 不含 `conda_toolchains`，mtime 是那个 worktree 的）。一个 job 跑什么，由提交和这套工具共同决定，所以 staging 目录与远端树现在都带上工具摘要（`TOOL_FILES` 的 sha256 前 12 位）：`stage/jobs/<sha>-<摘要>`、`jobs/<sha>/tree-<摘要>`。输入包的 staging 目录同理改成每次运行一个，推完删掉。

### 实测（2026-09-24）

| 项 | 结果 |
|---|---|
| 本机 `inputs.py build`（下载已在，只加编译器） | 19s；十个包解包加重定位 2.3s，85 个文件重定位；`toolchain/gcc-13.3.0` 解开 764.5 MiB |
| 送到集群 | 首次 `inputs.py verify` 红（锁里的编译器不在远端 MANIFEST），`inputs/` 再推一次、远端 `install`、复核共 225s；已有的四套工具链 `already matches`，只解了编译器（2.5s） |
| 本机 prefix `--only native-selfhost-tests,native-diff-1`（62481320，`--jobs 2`） | 5 个 run 步骤全部 exit 0，墙钟 891s |
| 集群同上 | 5 个 run 步骤全部 exit 0，墙钟 997s（含上一行的 225s） |
| 两份证据包的 `toolchain` | 逐字段相等，`diff` 输出为空：`cc` `cc (conda-forge gcc 13.3.0-2) 13.3.0`、`java` `21.0.2+13-jvmci-23.1-b30`、`python` `3.12.3`、`node` `v20.20.2`、`seed_jar_sha256` `a320e3ee…e679`；`substitutions` 也相同 |
| ASan 真的跑了 | 本机 `spike-native` 分片 1 的逐项结果与改动前（宿主 gcc）那次逐字相同：只有 `ctl_vthread`、`effect_sam_snapshot` 两个条目整条 `blocked`（改动前也是），其余条目的 `:asan` 都是 ok。缺 ASan 时每个条目的 `:asan` 都会是 `blocked` |
| 集群全套，origin/main 头 b2e19e06，本分支工具（d3ec809b），`--jobs 16`，每个 job 套隔离检查 | **`complete = true`**：175 个 run 步骤全部执行、全部 exit 0，39 个 job 全绿；`bundle.py verify` `COMPLETE`；39 次隔离检查全部 0 条；证据包 sha256 `62470de4…4526`。墙钟 2892s（上次全套 1722s；这次另有三个写者同时占着集群，最长的 `incremental-2` 1535s，上次 925s） |
| 集群全套的 `toolchain` 对本机 `--only` | 逐字段相等，`diff` 输出为空 |
| 修 staging 之前的那次全套（同一提交，d3ec809b 之前的工具） | `toolchain.cc` 为 `null`（见上一节），另有两处红：`compiler-weight-contract` 的 `selfhost-bench-contract/run.py`（exit 1）与 `docs` 的 `playground/test/contract.sh`（exit 7；脚本在 `set -e` 下把 `$(curl …)` 赋给变量，7 最可能是 curl 的「连不上」，步骤日志留在集群上没有取回）。两者都不调 C 编译器；那次各 job 比上次慢 2 到 3 倍（`list-elems-contract` 1838s，上次 587s）。同一 job 在本机 prefix 单跑绿（370s），修好后的全套里两者也都绿。归为负载下的计时，照实记下，没有改被测脚本 |

### 负控

| 做法 | 结果 |
|---|---|
| 锁住的编译器包（`gcc_impl_linux-64` 的 `.conda`）第 1000000 字节翻一位 | `inputs.py verify` 红：`sha256 5608…3be5 is not the lock's c3e9…f774`；复原后绿 |
| 重定位过的 `specs` 里改 rpath | 红：`toolchain cc … tree digest … differs from MANIFEST`；复原后绿 |
| 解开后的 `lib/libasan.so.8.0.0` 第 4096 字节翻一位 | 红，同上；复原后绿 |
| `zstandard` wheel 第 2000 字节翻一位 | 红，对锁不符；复原后绿 |
| `prefix.py` 第 110 行 `lock["downloads"] + lock.get("conda_toolchains", [])` 用 sed 改回 `lock["downloads"]`（去掉 PATH 注入） | `prefix.py selftest` 红：`FAIL cc is the input pack's: /usr/bin/cc`；`run.sh --only tree-policy` 的证据包 `toolchain.cc` 回到宿主的 `cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`；`git checkout` 复原 |
| `prefix.py selftest --break-env-i` | 红，`cc` 一条报 `/usr/bin/cc`，与 `JAVA_HOME`、PATH、宿主变量三条一起 |
| 在 `gatesplan.ADJUSTMENTS` 加一行无条件的 `adjust:cc-input-pack` | 已发布的 14535104 证据包 `bundle.py verify` 由 `COMPLETE` 变 `INVALID substitutions`（见「不进替换表」） |

前四条改的是临时目录里的一份 prefix 副本，下载物先 `cp` 成独立的 inode 再改，共享 prefix 里的原件未动（事后 sha256 仍是 `c3e9f243…`）。

### 2026-10-05 起 CI 的 C 编译器换成 clang 18，输入包仍是 gcc 13.3

裁决 ffi-llvm 4.b 把 CI 与发布行的 C 编译器钉到 runner 镜像自带的 clang 18.1.3：每个编 C 的 gate job 与 release.yml 的发布 job 开头一步 `scripts/pinned-cc.sh`，按版本核对后把 `CC` 写进 `GITHUB_ENV`。上面「先看 CI 实际用什么」那段描述的是这之前的状态；`wasm-target` 的 C driver 一步与 `java-target-classpath-contract` 也改成了 `${CC:-cc}`。nightly 的 native-asan 暂不钉：clang 的 UBSan 带 `-fsanitize=function`，在每个 native 测试二进制上报同一处真实的未定义行为（`ctestrun` 生成的测试 thunk 签名与 `dawn_run_caught` 的调用类型不符），修它要动 `selfhost/src/c`，见 nightly.yml 该 job 的注释。#502（660fda19）修好后，native-asan 也加了同一步 `pinned-cc.sh`：clang 在那里还是更强的检查器，gcc 的 UBSan 不查间接调用的函数类型，#502 正是这样在 gcc 下漏过去的。

这一步只在 `GITHUB_ACTIONS=true` 时生效，外部运行不设这个变量，所以 prefix 里的 job 照旧用输入包的 gcc 13.3，`toolchain.cc` 也照旧如实记 gcc。这是有意的：给输入包加 conda-forge 的 clang 要动锁与 MANIFEST（共享 prefix 也被别的分支的工具核验），且同「不进替换表」一节的理由，不能靠加替换行表达。代价是外部证据与 GitHub 上的 main push 用的编译器不同：一个只在 clang 下红的改动，PR 证据档看不见，要到 main push 才红。要收这个口子，做法是把 clang 18.1.x 作为第二个 conda 工具链进输入包、`pinned-cc.sh` 在 prefix 里认它，另起一刀。

### 输入包加 clang 18.1.3，外部运行与 CI 同编译器（2026-10-05）

上一节的口子按那里写的做法收了。

- **版本恰好相同。** conda-forge 有 18.1.3 的构建（`clang-18-18.1.3-default_h127d8a8_0` 等，2024-04-08 上传），锁里作为第二个 conda 工具链 `clang`（目录 `clang-18.1.3/`）钉了十九个包：`clang`、`clang-18`、`libclang-cpp18.1`、`libllvm18`、`compiler-rt`（含 `compiler-rt_linux-64` 的 ASan 等运行时）及 libLLVM 的动态库依赖 `libxml2`、`icu`、`libiconv`、`xz`、`libzlib`、`zstd`，再加 gcc 工具链已有的 sysroot、binutils、`libgcc-devel` 与 14.2.0 运行时七个包（同一归档，不必重新下载）。新下载 110 MiB，解开 994.7 MiB。没用 LLVM 官方 tarball：预编译包在 1 到 2 GB（`inputs.py` 文件头已记），送集群按 0.6 MB/s 算要半小时以上。
- **怎么找到 sysroot 与链接器。** conda-forge 的 clang 默认目标是 `x86_64-conda-linux-gnu`，clang 18 按默认目标在自己的 `bin/` 找 `x86_64-conda-linux-gnu-clang.cfg`（以 `clang-18` 调用也读），里面是 `--sysroot <工具链>/x86_64-conda-linux-gnu/sysroot`（文本占位符，照常重定位）；gcc 安装（`crtbegin.o`、`libgcc.a`）与 `x86_64-conda-linux-gnu-ld` 在同一目录里找到。所以这些包必须与 clang 解在同一个目录，不能借 gcc 工具链的目录。实测本机 `env -i` 下编译、链接、`-fsanitize=address` 都通，产物只依赖 `libc`/`libm`。
- **不进 PATH，用 `DAWN_PINNED_CC` 点名。** CI 上裸 `cc` 仍是 gcc，只有 `CC` 是 clang；这个工具链的 `bin/` 还带着 icu、xz、zstd 的命令行工具，进 PATH 会挡住 `/usr/bin`。所以锁里 `bin` 为 null，另记 `pinned_cc: bin/clang-18`，`prefix.job_env` 据此设 `DAWN_PINNED_CC`。`pinned-cc.sh` 见到它就把它当作 runner 上 `command -v clang-18` 的结果，照样核版本（`-dumpversion` 必须是 18.1.3）、照样写 `CC` 进 `GITHUB_ENV`；外部 runner 本来就按步骤给 `GITHUB_ENV` 文件，并带到后续步骤。没有伪造 `GITHUB_ACTIONS`：那是 runner 自己的变量，伪造它等于让所有按它分支的脚本都以为在 GitHub 上。
- **`toolchain.cc`。** 改记 `$DAWN_PINNED_CC --version` 的首行（没有该变量时仍是 `cc --version`）。conda-forge 的首行带 feedstock 的 URL，证据包的泄露过滤见斜杠就拒，所以去掉 URL 的协议与目录，留下 `clang version 18.1.3 (clangdev-feedstock 9d0fad6b23c7f8bf40587b7924996e1cfbdcaffd)`。`bundle.py` 与 `verify_note.py` 对 `toolchain.cc` 只做字符串与泄露检查，不认具体值，所以 main 上的核验器不需要改，已发布的证据包也不受影响；替换表照旧不加行（理由同「不进替换表」）。
- **二进制占位符。** `libxml2.so` 里的默认 catalog 路径与 `xz` 两个命令里的 locale 目录是二进制模式占位符，解包器向来拒绝。锁条目的 `unrelocated` 列出这五个文件，它们按原样解出、保留构建机路径；gate 用不到 libxml2 的 catalog，也不跑这里的 xz。不在列表里的二进制占位符照旧拒绝。
- **与并行使用者兼容。** 同 `conda_items` 当初的理由，clang 的 MANIFEST 行放在新键 `pinned_cc_items`（锁条目的 `manifest_key`）下。main 的 `inputs.py verify` 在新 MANIFEST 上实测仍绿。反过来，别的分支用 main 的工具重新 `build` 会写出没有这个键的 MANIFEST，本分支的 `verify` 随之红（「clang in inputs.lock.json but not in MANIFEST」），要再 `build` 一次；合进 main 之后就没有这个来回。

剩下的差别：CI 的 clang 是 Ubuntu 打包的 `18.1.3-1ubuntu1`，这里是 conda-forge 的构建，上游源码版本相同，下游补丁与构建选项不同；CI 链接的是 runner 的 glibc 2.39 头文件与 gcc 的 crt、libgcc，这里是 glibc 2.34 sysroot 与 gcc 13.3 的 `libgcc-devel`。一个只在 Ubuntu 补丁或新 glibc 头文件下才红的改动，外部证据仍看不见；只在 clang 18 下红的改动现在看得见。

## release 守卫的 ci 证据只认 main 的 push 运行（2026-09-25）

`release_evidence.py` 的第 1 条证据原来是「`ci.yml` 在该 sha 上有任意一次成功运行，不限事件与分支」，理由是 `ci.yml` 在所有分支上调用同一个 `gates.yml`。#168 之后这个前提不成立：`pull_request` 运行只跑 `plan.py` 选的子集，其余 job 跳过、按 success 计；Actions API 把 PR 运行记在 PR 头提交的 sha 下。同一个 sha 先在 PR 上子集绿、再原样快进推到 main 时，`any(success)` 会把子集绿当全集证据，哪怕 main 上那次全集是红的。今天走 `gh pr merge --rebase` 总会产生新 sha，所以还没踩到；快进合入一旦常用就会踩到。

改法：`ci_evidence` 只接受 `event == "push"` 且 `head_branch` 为默认分支、已完成且成功的运行；其它运行照样列出，每行末尾注明拒因（`refused: event pull_request, not push ...` 或 `refused: pushed to <branch>, not main`）。`plan.py` 对非 `pull_request` 事件一律答 `all`，这是「main 的 push 运行就是全集」的依据。事件与分支两个条件缺一不可：fork 从自己的 `main` 开的 PR，运行的 `head_branch` 也是 `main`，只查分支拦不住它。

自测从 11 例增到 14 例：PR 事件的成功运行（`head_branch` 为 `main`）拒；非默认分支的 push 成功运行拒；main 的 push 成功运行与一次失败的 PR 运行并存时收。负控：删掉事件条件，第 1 例红（`pull request run green: exit 0, want 1`）；删掉分支条件，第 2 例红。

墙钟：0。`verified` job 的 API 查询次数不变，只是本地多过滤一步。行为变化：非 main 分支上的 push 运行不再被接受（今天 `ci.yml` 只在 main 上响应 push，`ci.yml:25-26`，所以没有这种运行）。

## 集群运行可续（2026-09-25）

### 为什么

同步的 `crun run` 在整个 job 期间占着一条 SSH 会话，而 crun 自己的断连哨兵会在会话断开时杀掉远端任务（它本来是为了「本地被杀、远端别留着」）。全套跑到二十多分钟时 crun 退出 255 已观测两次，两次都整批作废；原先的重试只覆盖「job 还没开始就失败」。

### 两个前提（先核实，再动码）

| 前提 | 做法 | 结果 |
|---|---|---|
| `-d` 能与 `-n 0` 同用 | 从一个只含 `.crun.yaml` 的临时 staging 目录跑 `crun run -n 0 --no-build -d -- bash -c 'sleep 300; echo alive > <prefix>/tmp/probe-…'` | 成立：11s 返回，退出 0，打印 job id；`crun jobs` 显示 running |
| tmux 会话在 SSH 断开后存活 | 上一行的 crun 返回时它的 SSH 会话就已结束；5 分钟后读 probe 文件 | 成立：文件在启动后 301s 写出，内容 `alive`，`crun jobs -a` 记 `exit:0`；之后 probe 文件与临时 staging 目录已删 |

### 做法

- **后台启动。** 每个 job 是一次 `crun run -n 0 --no-build -d -- bash -c <包装>`。远端命令不变（仍是 `env -i … prefix.py run-job`），包装只多三件事：先 `mkdir <prefix>/out/<sha>/<run>.ctl/<job>.claim` 认领（已存在就什么也不做、退出 0，所以重复启动无害）；把 run-job 的 stdout、stderr 写进同一目录；最后用 rename 写 `<job>.exit`（退出码与远端起止时刻）。控制目录放在 `out/<sha>/<run>` 旁边而不是里面：`<run>` 目录由降权后的 uid 创建，root 先建了它，那个 uid 就写不进 `fragments/`。
- **轮询。** 一个轮询线程，每 `poll=`（默认 30）秒一次短 `crun run -n 0 --no-sync --no-build`，一次问完所有未收回的 job：没认领（absent）、已认领（running）、或已结束（附退出码、片段、stdout、stderr，base64）。轮询断连只丢这一轮。一次轮询或启动超过 300s 按断连处理。
- **启动没确认。** crun 返回非 0 或没打印 job id 时不重试，交给下一轮轮询：已认领就收养，连续两轮没认领才重新启动（至多三次）。
- **判红。** 结束了但没有片段的 job 判红；超过 `timeout-minutes × (timeout-scale + 1)` 还没结束的判红并 `crun kill`。run-job 里本地后端自己的超时是 `timeout-minutes × timeout-scale`，先触发，所以正常情况下超时会以步骤结果的形式回来。
- **续跑。** runner 每次运行写 `<out>/invocation.json`，crun 后端把运行 id 写进 `<out>/crun/run-id`。`run.sh --resume <out>` 复用两者（只许改 `--jobs`），prepare 时轮询全部 job 一次：已结束的由 runner 直接记为完成、不占 worker；还在跑的等它；没认领的启动。本地后端不支持续跑（它的 job 是控制端的子进程，随控制端一起死），runner 直接拒绝。

`--no-sync` 并不省掉推送：从控制端发起的 crun 每次都会先推 staging 目录（它只跳过集群内跨机同步），所以一次轮询约等于一次推送加一条短命令。轮询是一个线程统一发的，不是每个 job 一个，推送次数与 job 数无关。

### 桩自测（`crun_stub_selftest.py`）

桩 crun 在本机执行命令，用一个目录充当集群 prefix；prefix 里的 python3 也是桩，对 `prefix.py run-job` 按 job 文件算出固定的片段。中间的 runner、backend_crun、bundle 都是真代码，计划来自真实提交上的 gates.yml。本机 24s：

| 情形 | 结果 |
|---|---|
| 干净运行 | 参照证据包，`complete = true` |
| 第 2、5 次轮询断在执行前，第 3 次断在执行后 | 与参照逐字节相同 |
| 第 1、7 次启动断在执行前 | 逐字节相同；两个 job 各启动两次 |
| 第 2、9 次启动断在执行后（已在「集群」上跑起来） | 逐字节相同；没有 job 被重复启动 |
| 第 3 次轮询时 SIGKILL 控制端，然后 `--resume` | 逐字节相同；某次是 7 个收回、16 个还在跑并等到、16 个由续跑的控制端启动（三类的比例随调度略有出入，三类都得出现，否则自测判红） |
| 负控：job 结束后删掉 `test` 的远端片段，再 `--resume` | 退出 1，`complete = false`，`test` 的步骤全部记为未执行 |

变异体：把「启动没确认」改回旧行为（直接判失败），两个启动断连的情形变红；让 runner 忽略 `--resume`（每次都新建运行 id），续跑情形与负控都变红。

### 实测（集群）

| 项 | 结果 |
|---|---|
| 小跑 `--only std-version,export-surface`（a95a505d，`poll=45`） | 两个 job 全绿；一次轮询端到端 8s（推送加短命令），11 次轮询 0 次断；控制端比远端多占 27s 与 57s（启动约 10s 加等下一轮轮询）。据此默认改为 30s |
| 全套 368b4a09，`--jobs 16`，`isolation=1`，`--keep-going` | 01:37:10 起跑；569s 时 `kill -9` 控制端（此时 20 个 job 已启动，4 个已收回）；7s 后 `run.sh --resume` |
| 续跑 prepare 的一次轮询 | `4 done, 16 running, 19 absent`：4 个直接收回（不占 worker），16 个等原来的 job 跑完，19 个由续跑的控制端启动；`dispatch.txt` 共 39 行，**没有 job 被启动两次** |
| 结果 | **`complete = true`**：175 个 run 步骤全部执行、全部退出 0；`bundle.py verify` `COMPLETE`；39 次隔离检查全部 0 条；证据包 sha256 `de7e0ba5…` |
| 墙钟 | 续跑段 1657s（45 次轮询，0 次断），两段合计 2233s（含 7s 间隔与续跑的 23s prepare）。同步后端此前两次全套 1722s、1730s；这次另有一个写者的全套同时占着集群（它仍用同步后端），最长的 job `native-selfhost-tests` 远端 869s，所以 2233s 不是干净的对比，只能说明量级 |
| 每 job 控制端额外占用 | 本控制端启动的 23 个 job：最少 28s、中位 52s、最多 113s、平均 53s（含排队等推送锁的启动，启动本身 11–60s、中位 15s，加等下一轮轮询）。它占的是 worker 名额，不在远端的 job 时长里 |

### 不做的（理由）

- **按 `crun logs` 或 `/run/crun/jobs/*.exit` 取结果。** 那是 crun 的内部布局，退出码也只是外层流水线的；认领目录与 `.exit` 在 prefix 里，由本仓的包装写，语义自己定。
- **续跑时重跑没有片段的 job。** 任务单允许「重跑或判红」。重跑要先清掉认领与上次的制品目录，而没有片段通常意味着 job 本身坏了（或有人动了集群上的文件），悄悄重跑会把这件事藏起来；判红后整次再跑一遍即可。
- **每个 job 一个轮询。** 推送由 crun 串行化，16 个 job 各自轮询会把推送排满；一个线程一次问完，轮询开销与 job 数无关。
- **`anchor-readers.txt` 登记。** 新代码不按字面量读源码文本（只读 gates.yml 的计划与集群上的 JSON），不涉及。`steps_lock.py` 也不涉及：没有碰 gates.yml 的 run 行。

## 多机分派（2026-10-04）

### 为什么

不带 `-m` 的零卡 `crun run` 一律落在 crun 的主力机上。10-04 晚六个写者各跑 `--jobs 8`，主力机（256 核）load 在 175–205 之间，另两台 H200（各 224 核）load 2–5。单个 job 从约 10 分钟拉到 20 分钟以上，一轮全套从约 20 分钟拉到约 65 分钟（当时六个控制端的全套墙钟 3358–3727s）；`--jobs 39` 时负载敏感的门禁（compiler-weight-contract 的 `sampling_targets_two_ms` 等）必红。

### 先探清的三件事

| 问题 | 做法 | 结果 |
|---|---|---|
| `-m` 时树推到哪 | 读 crun 源码，再从临时 staging 目录 `crun run -n 0 -m <机器>` | 控制端照旧先推到主力机的 `remote_root`，主力机上的内层 crun 再把同一路径 rsync 到目标机（`--no-sync` 只跳过这一步）；三台机器上路径相同 |
| prefix 是否共享 | 三台各 `df` 一次 prefix 所在目录 | 不共享：各是本机磁盘。输入包、工具链、认领目录与片段都只在 job 所在的机器上 |
| load 从哪读 | 同上 | 每次远端命令前加一行 `nproc` 与 `/proc/loadavg`，不另起探测 |

### 做法

- **机器集合。** `crun status` 列出的、有 GPU 行回来的机器，按出现顺序记为 A、B、C；字母与地址的对应只写在 `<out>/crun/machines.json`（本机），日志、`dispatch.txt`、认领目录里只出现字母。`--backend-opt machines=auto`（默认）用全部；`machines=N` 在 prepare 后留负载最低的 N 台；`machines=primary` 不带 `-m`，即旧行为。
- **每台各自 prepare。** 并行地对每台跑一次「load 探测 → job uid 能否启动 prefix 的 python → `inputs.py verify`」。红了就把输入包送到那台：走 crun 自己的路线（推到主力机，主力机已有同一份所以几乎零字节；再由主力机集群内 rsync 过去），然后 `inputs.py install`。两台空机器各 63–64s（775 MiB），远小于从本机直推的 0.6 MB/s。送包串行，因为每次都推进主力机上同一个 `remote_root`。
- **选机。** 每次启动挑 `(load + job-load × 近 90s 内本控制端在该机启动的 job 数) / 核数` 最小的一台。load 是最近一次轮询或 prepare 读到的 1 分钟均值；第二项补的是 1 分钟均值还没反映出来的新 job。不用轮转：其他控制端不轮转，轮转仍会把三分之一的 job 送到最热的那台。`job-load` 默认 4，来自实测（见下）。
- **记录与轮询。** `dispatch.txt` 每行多一列 `machine <字母>`，认领目录里写一个 `machine` 文件。轮询按机器分组，每轮每台一次短 crun，并行发出，顺带带回该机 load（逐条记在本机 `<out>/crun/loads.txt`）。job 换了机器后，旧机器那一轮的状态按过期丢弃。
- **续跑。** 读回 `machines.json`，在每台机器上把全部 job 轮询一次再合并：done 胜 running 胜 absent，同级取 `dispatch.txt` 最后记的那台；还在跑的就在它那台上等。
- **掉机。** prepare 时不应答、job uid 用不了、或送包后仍验不过的机器，本次运行不用；运行中某台的轮询或启动连续 `dead-after`（默认 6，默认轮询下约 3 分钟）次失败就判掉线，它上面的 job 到别的机器重新启动。原机器上晚跑完的那份留在它自己的盘上，没人读。只有一台都不剩时整轮才失败。
- **证据包不变。** 片段里没有机器信息；`toolchain` 由各 job 自报，跨机器不一致时照旧置 `null` 并记日志，这正是「换了在哪跑、没换跑什么」的核对。

### 途中查出

- **一台机器上 job uid 进不去 prefix。** 第一次多机全套，B 上 13 个 job 全部 `exit 127`：降权到 uid 20000 后加载 prefix python 的 `libpython` 报 Permission denied。原因是 prefix 上面一层目录在那台机器上是 700、属主是别的 uid；那不是我们的目录，不能改。所以 prepare 加了上面那步 uid 检查，B 因此在 prepare 就被摘掉，本节其余实测都是 A 加主力机两台。
- **标记被 crun 的回显命中。** 第一版 uid 检查用 `"GATES-NOREACH" in stdout` 判，而 crun 会把要执行的命令原样回显在同一个 stdout 里，三台机器全被摘掉。改成整行匹配；桩 crun 也照样回显命令，这类错今后在桩自测里就红。

### 实测（同一提交 6c85e112，origin/main，34 个 job、125 个 run 步骤）

| 运行 | 墙钟 | complete | job 分布 | 各机 load 峰值 | 同时在跑的其他控制端 |
|---|---|---|---|---|---|
| 单机基线 `machines=primary --jobs 8` | **2096s** | true | 全在主力机 | 主力机 87 | 起跑 1 个，结束时 0 个 |
| 多机 `--jobs 39`（`job-load=8`） | **949s** | true | A 21、主力机 13 | A 75，主力机 185 | 起跑 2 个，结束时 3 个 |
| 多机 `--jobs 8`（`job-load=4`） | **2076s** | true | A 34、主力机 0 | A 47 | 起跑 3 个，结束时 1 个 |

参照：当晚六个控制端各自单机 `--jobs 8` 的全套是 3358–3727s（不同提交）。

- `--jobs 39` 全绿，包括 compiler-weight-contract（387s）与 docs（848s）。负载敏感门禁的修复不在本刀，这一轮绿是因为 A 只到 75/224；主力机那边同时有别人的 job，到 185/256。
- `job-load` 原来是 8：A 在九次快速启动后就「显得满了」，13 个 job 去了起跑时 load 已 81 的主力机。主力机上的 job 平均 585s，A 上 386s，最长的五个都在主力机上。A 放了 21 个 job、峰值 75，约每 job 3.6，所以改为 4。
- 单机基线与多机 `--jobs 8` 几乎一样（2096s 对 2076s，job 远端平均 378s 对 369s）：这两轮跑时别的控制端已基本收工，主力机只到 87/256，没有可躲的负载；`--jobs 8` 的墙钟由 8 路宽度与最长链决定。多机在 `--jobs 8` 上的收益只在主力机被别人压满时才出现，本节没有在那种条件下测到同一提交的对照，只有开头那组六控制端的 3358–3727s。
- `--jobs 8` 多机时 8 个 job 全落 A：A 起跑 load 2.3，按 4 算要十几个并发 job 才追上主力机的 77/256，`--jobs 8` 到不了。这说明选机在按负载走，而不是在轮转。

### 墙钟影响

push-total 不变：这是外部后端，`gates.yml` 与任何工作流都没动。桩自测本机 24s → 31s（多了四种情形），它不在 CI 里。

### 不做的（理由）

- **改那台机器上 prefix 上层目录的权限。** 不是我们的目录，门禁运行只准写 prefix；摘掉那台机器即可。
- **跨控制端的全局调度。** 其他控制端（旧工具）不带 `-m`，也不报计划；要全局调度就得在集群上放一个常驻协调者，与「集群侧是可丢弃镜像」相悖。按当前 load 选机已经把负载从最热的那台挪开。
- **job 中途迁移。** 掉线机器上的 job 重新启动，不搬运半截结果；半截结果在那台盘上，读不到，也不可信。
- **按 job 历史时长加权选机。** 需要入库或本机的时长台账，台账会过期；`job-load` 一个常数加 1 分钟均值已经够分流。
- **探测机器时用 `crun status` 之外的路径。** 机器清单与可达性以 crun 自己的视图为准，后端不读它的配置文件，代码与日志里也就不会出现地址。

### 依赖产物跨机器（2026-10-05）

多机分派合入后，一个写者的全套 `complete = false`，唯一的红是 `mutant-shards-complete`：`builtin-type-3-3` 跑在另一台机器上，汇总 job 在自己那台的产物目录里找不到它的覆盖记录（分片本身是绿的）。每台机器的 prefix 是它自己的盘，产物只在 job 跑过的那台上。

**依赖有哪些。** 计划里读别的 job 产物的只有一处：`gates.yml` 头部注释写明除 `plan` 外 job 之间不许 `needs:`，唯一例外是 `mutant-shards-complete`，它 `needs` 八个变异分片（`native-diff-1/2`、`syntax-mutants-3-1..3`、`builtin-type-3-1..3`），用 `download-artifact` 按 `mutant-coverage-*` 取它们 `upload-artifact` 上传的覆盖记录。没有别的共享路径：其余 job 只写自己的工作目录与 `RUNNER_TEMP`。

**做法：产物随结果回到控制端，再随启动送到需要它的机器（任务单的 (b)）。** 轮询报告一个 job 结束时，顺带把它上传的产物打成 tar.gz（名字取计划里上传步骤字面的 `name:`；名字是表达式的，prepare 时拒绝，不猜），控制端留着。启动一个带 `needs` 的 job 时，凡它需要的 job 跑在别的机器上，就把那份 tar 放进 staging 目录的 `xfer/<run>/`，随 crun 每次启动本来就有的推送到达目标机；包装在 run-job 之前把它解进本次运行的产物目录，并把新建的目录交给 job 的 uid（那个目录若由 root 先建，job 就写不进片段）。同一台机器上的依赖不搬。`--resume` 时，前一个控制端已收完的 job 的产物在 prepare 那次轮询里一并取回。

**为什么不把依赖闭包钉在一台机器上（(a)）。** 八个分片是全套里最长的一批 job 之一，钉在一起正好重建多机分派要拆掉的集中；而且得在第一个分片启动时就定机器，那时离汇总 job 启动还早，负载早变了。搬产物的代价是每个分片几 KiB 的覆盖记录，走的是已有的轮询与推送，不多一次 crun。

**桩自测。** 桩 python 现在照本地后端的样子上传与下载：上传写 `artifacts/<name>/`，下载时若所需 job 上传的某个产物不在本机，后面的 run 步骤全部退出 1。干净运行另要求至少一个被需要的 job 与汇总 job 不在同一台桩机器上（实测 8 个里 6 个跨了）。用旧后端跑，干净运行在这里就红（汇总 job FAILED）；用新后端全绿。

**不做的。** 把产物放到主力机上一个共享位置再分发：多一跳，也多一个要清理的公共目录；控制端本来就逐个收 job 的结果，顺带收产物最省。按 `download-artifact` 的 pattern 取全部产物：只取所需 job 上传的，避免把别的还在上传中的 job 的半截目录带过去。

## PR 与 main 上的证据档（2026-09-25）

调研见 `agent-handoff` 下的 PR 检查调研报告（方案 (a) 与第 1、2 刀）。一句话：plan job 用 release 守卫的同一份回读核验去读头提交的 `gates/maintainer`，读到就让整次运行全部跳过；不设 required check，不改合并规矩。

### 做法

- `ci.yml` 给 `gates.yml` 多传一个输入 `head: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || '' }}`（只在 PR 上有值），并在调用 job 上授予 `contents/statuses/actions: read`。本仓默认 token 是受限档（`gh api repos/dawnop/dawn-lang/actions/permissions/workflow` 读到 `"read"`），它只带 contents；被调用的工作流只能收窄调用方给的权限，所以必须由 `ci.yml` 给，`plan` job 再声明恰好这三项。
- `plan` job 先跑一步 `evidence`：事件不是 `pull_request` 或 `head` 为空时只打印 `evidence: not a pull request; planning as usual` 并直接走规划；否则 `timeout 20 release_evidence.py --external-only --sha "$HEAD"`。退出码 0 写 `accepted=true` 并把核验行贴进 step summary；1（没有可接受的 status）、2（API 读不了）、124（超时）一律写 `accepted=false`，日志里有 `refused: <why>` 或 `exit 2`。
- 规划那一步开头读 `accepted`：为 true 就写 `all=false`、`jobs=[]` 并 `exit 0`，不调 `plan.py`；否则与之前逐字相同。
- 所以 plan 的输出仍然只有 `all`/`jobs` 两个键，gate job 的 `if:`、`gatesplan.py`、`steps.lock.json` 都不用动（`gatesplan` 整个替换 plan job，不看它的步骤；`--self-test` 与 `--sha` 在本刀上照常通过）。

### 安全边界

接受条件与 release 守卫的第 2 条逐字同一份代码（`external_evidence()`）：最新的 `gates/maintainer` 为 `success`；creator 是 `github-actions[bot]`；`target_url` 恰为本仓的 `actions/runs/<id>`；回读的这次 run 是默认分支上 `workflow_dispatch` 触发、结论 success 的 `verify-external.yml`；status 写入时刻落在 run 的时间窗内。个人账户用 `gh api` 手写的同名 status 在第二条就被拒（`refused: written by <login>, not github-actions[bot]`），把 `target_url` 指向 `ci.yml` 的 run 在回读时被拒（`refused: run <id> is .github/workflows/ci.yml, ...`）。攻击面与 release 守卫相同，没有新的信任根。

PR 上的 plan 跑的是 PR 自己的代码，恶意 PR 改掉这一步就能全跳过；但它今天本来就能把 `ci.yml` 改成什么都不跑。PR 检查对恶意作者从来不是边界，边界在 main 与 release。

### 只在 PR 上生效；release 守卫的第二道

证据档只在 `pull_request` 事件生效（主会话裁决，2026-09-25）。「main 的 push 运行就是全集」要按构造成立，不靠守卫事后拒：`ci.yml` 在 push 上传空的 `head`，证据步骤见空就不查；`plan.py --check-wiring` 要求 `head` 的表达式含 `github.event_name == 'pull_request'`，改成无条件传 `github.sha` 的变异体会红。另一个理由是 nightly 的 gate-totals 把 main 上 success 的 push 运行当全集算中位 job-seconds，一次全跳过的 main 运行会污染报表。代价是快进合入时 main 也拿不到证据档的省时（今天走 `gh pr merge --rebase`，main 的 sha 总是新的，本来就拿不到）。

守卫的收紧保留，作为第二道：假如上面的构造哪天丢了，main 上会出现「push 事件、默认分支、结论 success，但所有 gate job 都 skipped」的运行。守卫的第 1 条原来只看事件与分支，会把它当全集；若之后又有一次 verify 写了 `failure`（最新 status 覆盖旧的），第 2 条不再成立，第 1 条却仍会凭这次全跳过的运行放行。所以第 1 条现在对通过事件与分支检查的成功运行再读一次 `actions/runs/<id>/jobs?filter=latest`，有任何 job 为 `skipped` 就拒（`refused: N of M job(s) skipped ... (an evidence-tier run, not the whole gate set)`），没有 job 也拒。

这条依据实测：main 的全集运行 34484938024 列出 68 个 job 全部 `success`；PR 子集运行 35953200476 列出 41 个 job，38 个 `skipped`、3 个 `success`。也就是说 API 对被 `if:` 跳过的 job 报 `skipped`，而全集运行里没有 job 被跳过（`mutant-shards-complete` 的条件在 `all` 时也为真）。这只让守卫更严，接受集合是原来的子集；自测加了「只有证据档运行」「证据档运行 + status 已被 failure 覆盖」两例，均拒。

### 为什么 rebase 后的 sha 要重跑

证据是签给**一个提交**的：bundle 的 `tree` 是那个 sha，`gates_blob` 是那个 sha 上的 `gates.yml`，tree-policy 还会回读到上一个 tag 为止的提交历史（`Emit-Change`、`Anchor-Change` 声明），所以门禁结论依赖历史，不只依赖树。rebase 之后头提交换了，新 sha 上没有 status，plan 照常走子集或全集。这正是想要的：维护者 PR 的首轮（最贵、最可能红）由集群裁，rebase 之后的最终 sha 在 GitHub 上跑一次；按树认证据不成立，理由同上。「rebase 轮不重跑集群」的规矩不变。

### 为什么 fork PR 不变

维护者不会对 fork 代码跑集群（集群多人共用，任务以维护者身份执行），fork 的头提交永远没有 `gates/maintainer`，plan 读不到证据就照旧规划。fork PR 的只读 token 本来就能读公开仓库的 status 与 run，不需要 `pull_request_target`。`publish.py --rerun-ci` 只重跑 `head_repository` 是本仓的运行。

### 时序：publish 之后自动重跑 ci（第 2 刀）

推送的那一刻 `ci.yml` 就开跑了，那时还没有证据。`publish.py --rerun-ci` 在派发之后：用 `gh run list --workflow verify-external.yml --event workflow_dispatch` 找派发之后创建的那次 run，`gh run watch` 等它结束；结论不是 success 就停；是 success 再用 `external_evidence()` 回读 status，plan 不会接受就停；否则取该 sha 上本仓的 `ci.yml` `pull_request` 运行的最新一次（push 运行不读证据，重跑它只会再跑全集），还在跑的先 `gh run cancel` 并等它落定，再 `gh run rerun`。重跑沿用原来的事件与 `head`，plan 读到证据后全部跳过。没有 ci 运行时只打印提示：下一次推送或开 PR 会自己读到证据。

### 墙钟

- 没有证据时 PR 上的 plan 多一步（push 上证据步骤不调 API，只多一次 shell 判断）：本机桩 `gh`（无网络）整步 0.05 s；本机经代理对真仓库查一次（`--external-only`，e61c2574，无 status）1.67 s；托管 runner 上 release 守卫的同类查询（3–4 次 API）整步 2 s（2026-09-24T19:17Z 那次 release 运行），所以一次查询按不到 1 s 计。plan 的声明从 `3x 8s worst observed`（#232 按观测重述）改为 `3x 10s planning value`：最坏 8 s（run 36042621336），再加这次查询；多出的 2 s 由 `compiler-weight-contract`（508 s → 506 s，最坏观测 461 s）付，push-total 26149 s 不动。timeout 仍是 2 分钟：20 s 查询上限 + 40 s 建图上限 + 3x 声明。
- 有证据时：plan 跳过 `plan.py`，只多两次 API；整次 `ci.yml` 约为 plan（checkout 加两次查询，十来秒）+ `secrets`（约 17 s）+ 起机排队，约 1 分钟。gate job 全部 skipped，不占 runner。
- 本刀自己的 PR 碰了 `.github/`，`plan.py` 的 `forced` 规则让它在 GitHub 上跑全集（约 25 分钟一次）。
- gate-observations 只统计 conclusion 为 success 的 job，skipped 的 job 不进观测，证据档运行不会压低预算审计的观测值。

### 负控（自测里常驻）

- `release_evidence.py --selftest`：`--external-only` 8 例（接受、不查 ci、无 status、个人账户、`target_url` 指向 `ci.yml` 的 run、pending、被 failure 覆盖、API 不可读退出 2）；默认模式加 3 例与一条单独断言（证据档运行不算第 1 条）。
- `plan.py --selftest`：从 `gates.yml` 取出 plan job 的两步 shell，桩 `gh` 下跑 8 例（其中 push 两例：`head` 为空、以及带 `head` 且证据可接受，都必须不调 `gh`、照常规划）；接受时规划步的 `GITHUB_OUTPUT` 必须恰为 `all=false\njobs=[]\n`，其余必须落到规划器并在日志里写出原因。`--check-wiring` 新增 5 个变异体：`ci.yml` 不传 `head`、`ci.yml` 无条件传 `head`、删掉证据步骤、plan job 丢 `statuses: read`、`ci.yml` 的 test job 丢 `actions: read`。
- `publish.py --selftest`（及只跑这一半的 `--selftest-rerun-ci`）：`--rerun-ci` 6 例加一条顺序断言（verify 失败不重跑；status 被拒不重跑；无 ci 运行只提示；只有 push 运行也只提示；在跑的先取消、等落定、再重跑；只重跑本仓最新一次 PR 运行，不碰 fork 与 push 的）。
- `release_evidence.py --selftest` 与 `publish.py --selftest-rerun-ci` 进 tree-policy 的新一步（本地 0.03 s 与 0.13 s），`steps.lock.json` 相应多两条。不放完整的 `publish.py --selftest`：它的签名那一半调 `ssh-keygen`，而外部运行以没有 passwd 条目的 uid 执行（第 3b′ 刀），`ssh-keygen` 在那里报 `No user exists for uid ...` 退出 255；第一次集群全套就是因此 `complete=false`。

### 不做的（理由）

- **(b′) 聚合 required check。** 裁决不做：required 会拒掉未经检查的直推 main，发版流程要改；fork PR 需要 `workflow_run` 写者；消费方做不了 run 回读。等证据档跑满一段时间、确有「靠人看漏掉红灯」的实例再议。
- **按树认证据、让 rebase 后的 sha 沿用。** 门禁结论依赖提交历史（见上），不成立。
- **verify-external 自己触发 ci 重跑。** GITHUB_TOKEN 触发的事件一般不起新工作流，rerun 是否例外未查实；而且 verify-external 只该写 status，重跑用维护者的 token 在 `publish.py` 里做。
- **API 失败时等一等再查。** 读不到就按没有证据走原路，多跑的是 runner 时间，不会少跑；在 plan 里重试只会把 plan 拖进关键路径。
- **按 `head_sha` 以外的键找 ci 运行。** `--rerun-ci` 用 `head_sha` 找运行，这正是 Envoy 守则提醒的攻击者可影响的键；这里无害，因为重跑只是让 plan 再判一次，接受与否仍由 status 回读决定，而且只取本仓自己的分支（`head_repository`）。

## 与 #167 的关系

#167 要的是「分片之后各分片步骤的并集仍等于原 job 的步骤」的核对。本刀的多重集比较（`bundle.multiset_diff`）就是这个并集检查的核心：它逐条点名少了的和多出的命令。

但两者的比较对象不同，需要说清：本刀拿「证据包执行了的」去比「同一提交上 `gates.yml` 写着的」，所以能抓住「跑的时候漏了一条」，抓不住「`gates.yml` 本身删掉了一条」。#167 要抓的正是后者，它要求对照一份入库的期望或拆分时记录的并集。第 2 刀把这条核对接进 CI 时，比较对象换成入库期望（例如上一个提交的多重集，或随拆分一起提交的并集），就能关掉 #167。

第 4 刀（2026-09-24）按这个思路落地：`scripts/gates-external/steps.lock.json` 是入库期望，按 job 家族（job id 去掉一个末尾的 `-<数字>`，`contracts-1`/`contracts-2` 同属 `contracts`）记 `run:` 文本的多重集，解析复用 `gatesplan.parse`，不另写解析器。`steps_lock.py check` 在 tree-policy 里跑（本机 0.1s，self-test 另 0.1s），少一条或多一条都红并点名家族与命令；家族内挪动是重新分片，不红；跨家族挪动两边都红。删步骤、加步骤都必须在同一个提交里 `steps_lock.py record` 重录 lock，并在提交信息里说明理由，lock 的 diff 就是审阅者看到「哪条命令走了」的地方。副作用是 `gatesplan.py` 拒绝的 `gates.yml`（未建模的写法、复合 action 指纹变了）在 push 上就红，那也正是外部 runner 跑不了它的时刻。

负控：从 `contracts-2` 删掉 `./scripts/tea-reconciler-contract/run.sh` 一步，`check` 红并点名 `contracts: missing 1x`；lock 里多写一条不存在的命令，同样红并点名；复原后绿（174 个 run 步骤，27 个家族）。

## 实测

本节数字只作参考，不做性能声明；机器是共享的 16 核 / 15.6 GiB WSL2，运行期间还有其他进程。

2026-09-23，`run.sh --sha d9b10e62 --backend local --jobs 8 --keep-going`，GraalVM CE 21.0.2，Python 3.14.7，node v26.8.2，cc 13.3.0：

| 项 | 结果 |
|---|---|
| 墙钟 | 4969s（1:22:49） |
| 内存占用（MemTotal − MemAvailable） | 起始 2.19 GiB，峰值 10.6 GiB |
| job | 39 个里 37 个全绿，169 个 run 步骤全部执行，167 个退出码 0 |
| 非零 | `lsp-workspace` 的 `./scripts/lsp-liveness.py`（exit 1）；`docs` 的 `./playground/test/contract.sh`（exit 1） |
| 证据包 | `complete = false`，`run.sh` 退出 1；`bundle.py verify` 复算一致 |

两个红步骤都不是替换表的问题，逐个复跑确认了原因：

- `lsp-liveness.py` 的 hangup 检查要求客户端关闭 stdin 后 5s 内退出。全套运行时 load average 在 30 上下，它在 5.00s 时仍存活。机器空闲时单独复跑 `lsp-workspace`，8 步全绿。这是负载下的计时，不是环境缺失。
- `playground/test/contract.sh` 里的 `lsp_contract.py` 在「SIGTERM 优雅回收子进程」一项失败（socket 在帧中途关闭），空闲时复跑仍然失败，所以是确定性的。把 PATH 上的 `python3` 换成系统的 3.12.3（ubuntu-latest 的版本）后单独复跑 `docs`，6 步全绿。网关用 `sys.executable` 启动，在 Python 3.14 下 SIGTERM 路径的行为不同。这是网关对 3.14 的兼容问题，CI 看不到。

本机没有「因为缺工具或断网而根本跑不了」的步骤：wasi-sdk 下载、N−1 种子下载、ASan、clang 都可用。

## 接入前必改

这些是本刀在 `run.sh` 里绕开、但没有在仓库源码里改掉的债：

- `contracts-1` 的 `/tmp/gate-emit` 写死在 `gates.yml`。本地用机器级锁串行化，挡不住其他程序；应改成 `$RUNNER_TEMP/gate-emit`。
- ~~`playground/test/contract.sh` 默认 8097 并在退出时 `fuser -k` 该端口。~~ #173 已改：端口向内核要，收尾只杀自己起的进程组。原先的 `adjust:playground-port`（每次运行挑空闲端口经 `PLAY_TEST_PORT` 传入）随之在第 3b′ 刀删掉；`PLAY_TEST_PORT` 仍在宿主环境的清除名单里，开发者 shell 里钉的值不会漏进来。
- `scripts/spike-native/run.sh` 在编不出 ASan 时只打印一行 note 并把 asan 检查记为 blocked，job 仍然绿。在 CI 上无害（runner 有 ASan），在外部后端上会让「跑过了」少一个维度而证据包看不出来。应让缺 ASan 成为失败，或至少成为可机读的结果。
- 本地后端用宿主 PATH 上的 `python3`、`node`，只把版本写进证据包，不钉版本。上面的 3.14 实例说明这会改变结果；接入前应能钉住与 ubuntu-latest 一致的解释器版本，或者让不一致成为拒绝。
- `lsp-liveness.py` 的 5s 上限在高并行的共享机器上会误红；外部后端要么降低并行度，要么这个检查要按机器负载给出可解释的余量。

## 不做的（理由）

- **release 守卫自己验 note。** 第 4 刀让 `verified` 接受 `gates/maintainer`，但读的是 status，不是 note。status 可被有写权限者伪造，所以 `release_evidence.py` 不只看 state：creator 必须是 `github-actions[bot]`，`target_url` 必须恰为本仓库的 `actions/runs/<id>`，从本仓库 API 读回的那次 run 必须是默认分支上 `workflow_dispatch` 触发、结论 success 的 `verify-external.yml`，且 status 的写入时刻落在该 run 的时间窗内（API 不返回 dispatch 的输入，时间窗是把 status 绑到写它的那次 run 上的办法）。不在守卫里重做签名核验：那需要把 note、公钥与核验器带进 release job，而 `verify-external.yml` 已经在托管 runner 上用默认分支的核验器做过；守卫要确认的只是「读到的正是那次核验的结论」。维护者自证能否替代托管 runner 的独立运行，裁决是能，用于托管 runner 排队或宕机时发版；分量见 bootstrap.md 协议段的诚实边界。
- **自动触发。** `publish.py` 之后派发工作流是手动的一步（脚本替维护者执行 `gh workflow run`）。不做推 `refs/notes/gates` 时自动触发：Actions 的 `push` 触发器按分支与 tag 过滤，推 notes ref 能否可靠地触发工作流没有实测；更要紧的是，自动触发意味着任何能推 notes 的人都能让 runner 替他写 status，而派发是一个需要写权限、留在 Actions 记录里的显式动作。
- **发布红的证据。** `publish.py` 拒绝 `complete` 不为 true 的包。签名的「门禁没过」不能让任何人做任何事，没有绿 status 已经说明了这一点。
- **多钥与轮换过渡期。** `allowed_signers` 只有一行。换钥即改这一行，旧 note 从此核不过；要保留旧证据的可核验性，需要按时间段接受多把钥，等真的换钥时再说。
- **crun 后端占卡。** crun 后端只用零卡运行（`-n 0`）。`gates.yml` 今天没有 GPU 门禁（tile 的 GPU 差分在 `tile.yml`，不在本刀范围）。
- **在集群上建用户。** 非 root 执行（第 3b′ 刀）用的是没有 passwd 条目的 uid；建用户要写 `/etc/passwd`，在 prefix 外。
- **时长字段。** 证据包不记时长。时长是机器画像的一部分（核数、负载、邻居），不是树的性质；它也无法被验证者复核。本地计时写在 `summary.json`，只给跑的人看。
- **把 `/tmp/gate-emit` 改掉。** 任务单明确本刀不改仓库源码，且 #168 正在改 `gates.yml`；列进上一节。（8097 与 `fuser -k` 已由 #173 改掉。）
- **解析复合 action 并逐步替换其内部步骤。** 复合 action 的内部是 GraalVM 下载与缓存，没有门禁；整体替换加指纹更简单，也更早暴露变化。
- **宿主的 glibc 运行时。** 第 5 刀的 sysroot 只管链接；链出的程序运行时仍用宿主的 `libc.so.6`（集群 2.35，本机 2.39），与 git、bash 一样是宿主的。把 glibc 也带进来要连动态加载器一起带，那是容器镜像的事。
- **`clang` 与 binutils 的无前缀名。** 输入包的 `bin/` 上 PATH 的只有 gcc 的名字（`cc`、`gcc`、`cpp`、`gcov*`、`gcc-ar/nm/ranlib`），binutils 只有 `x86_64-conda-linux-gnu-*` 前缀名，gcc 自己按相对路径找 `as`、`ld`。门禁里直接调的 binutils 只有 `release-native.sh` 的 `readelf`（只读检查产物的 ELF 头），用宿主的；`clang` 只在 `DAWN_WASM_CC` 未设时作 wasm 的默认值，而 `wasm-target` 总会设它。
- **node 版本与 `lts/*`。** `docs` job 在 CI 上用 `setup-node` 的 `lts/*`，按任务单这里钉的是 20 LTS；两者不一定相同，证据包如实记录 `node` 字段。
- **覆盖 `tile.yml`、`editor-grammar.yml`、`nightly.yml`。** 任务单的范围是 `gates.yml`。前两个是按路径触发的门禁工作流，`tile.yml` 需要 GPU；把它们纳入是 crun 后端那一刀的事。
