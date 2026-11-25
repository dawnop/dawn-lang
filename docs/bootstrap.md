# Bootstrap 链：从种子到自举闭包

> 状态：**current** —— 自举与种子推进协议的现行说明（M8 收口后仍照做）。
>
> 2026-07-22 自举完成（design.md M7、selfhost-gaps.md §七）；2026-07-23 **M8
> 收口：Kotlin 实现归档在 `kotlin-final` tag，main 上只剩 selfhost**
> （[m8-selfhost-only.md](history/m8-selfhost-only.md)）。本文回答一个问题：
> **源码如何从锁定种子构建当前工具链，以及每一步靠什么验收**。JAR 链已交付；
> D12-2 P1/P2 已交付协议与选链机制，native 源码两阶段链按下文 P4 合同实施，默认尚未切换。

## 种子（seed）

**现行默认 JAR 链（M8 后）**：种子 = `scripts/seed-release.txt` 钉住的上一 release 的
`dawn-selfhost.jar`。`bin/dawn` 首次运行自动下载到 `.dawn/seeds/` 并用它编译
HEAD 工具链（`selfhost/` 加独立 `compiler-plan/` 及其 local dependency closure；
`DAWN_SEED=<jar>` 指本地 jar 覆盖，不能指 ELF）。种子 jar 自带一切：编译器类、
由 std 源编译出的 `stdsrc` 模块、vendored 的 ASM / coursier interface；后两样二进制
像 OCaml 的 `boot/` 一样**随种子逐代续传**（vendor 从当前运行 jar 的类路径拷出），
在库没有对应源码。stage A 的类型检查仍配对使用该 release 的 std 源树，
`scripts/seedjar.sh` 会从 tag 提取并校验它；独立 jar 运行时不再携带 std 源资源。

> 曾经是三样：`dawn.tool` 的 `AdtClassWriter` shim 也在里面，源码只在 `kotlin-final`
> tag。**2026-08-03（v0.49.0 之后）它退出了**——那五个 null 适配器改由 `rtclasses.dawn`
> 发射成 `dawn/rt/Asm`，`dawn/tool` 从 `--vendor` 和 `vendor_trust` 里删掉
> （docs/jvm-base-plan.md §5.7 K-A7）。它现在是**由上一代编译器发射**的类，而不是
> 无源逐字节抄的二进制——前者是自举常态、DDC 能处理，后者不能。

**信任链根**：学 Go 保留 go1.4，Kotlin 版编译器 v0.6.0 冻结为 bootstrap 根。
v0.6.0–v0.8.0 的 release jar 永久保存；`kotlin-final` tag 保有 Kotlin 全源，
从它 `./gradlew :compiler:fatJar` 可现编根种子。硬义务不变：
**种子必须始终能编译 selfhost/**（现由 CI 机器强制）。

冻结的含义（也记录在 design.md M7 验收结论）：

- bug 修照收，种子失去「能编译 selfhost」的能力算 P0；
- 新语言特性默认不再进 Kotlin 版——要做就得 selfhost 同步实现，双份成本是
  刻意的刹车。

> **迁移过程已经结束。** M8 阶段二/三/四的逐阶段快照（哪些能力还在 Kotlin 侧、
> `DAWN_KOTLIN=1` 逃生阀、`bin/dawn-kotlin` 作为金样 oracle）曾写在这里，读起来
> 像现状——而它们都不是了：Kotlin 实现在 `kotlin-final` tag，`DAWN_KOTLIN` 与
> `bin/dawn-kotlin` 都已删除，LSP 也早已是 selfhost 的。过程记录见
> [m8-selfhost-only.md](history/m8-selfhost-only.md)，本文只留现行链。

**现行的 oracle**：`scripts/selfhost-prev-diff.sh`——上一 release 与 HEAD 编同一
语料 + 生态扫描，未声明的字节差异红灯。提交信息必须为每个实际变化的检查逐项写
`Emit-Change(<label>): <说明>`，其中 label 必须逐字出现在 `scripts/emit-labels.txt`；通配与
裸 `Emit-Change:` 都是错误。同时机器强制种子特性纪律（N−1 的 jar 必须仍能编 HEAD 的
`selfhost/src`）。
配套还有 `selfhost-run-diff.sh`（CLI 转写）、`selfhost-fmt-diff.sh`（格式化）、
`selfhost-lsp-diff.sh`（LSP 会话）。

## 种子推进协议（2026-07-23 立法，M8 阶段一）

1. **种子形态**：v0.8.0 双发 `dawn.jar`（最后一个 Kotlin jar）与
   **`dawn-selfhost.jar`**（首个 selfhost 种子）；自 v0.9.0 起 JAR 种子为
   `dawn-selfhost.jar`。v0.6.0 起的历史 release 永久保留，构成可重放的信任链。
   K-B7（`docs/native-driver-plan.md` §22）给 `release.yml` 加了第二件产物
   `dawnc-linux-x86_64`（native 编译器的静态可执行文件）与它的 `.sha256`，
   但那一步落在 `v0.49.0` 的 tag 之后，所以 **v0.46–v0.49 的 release 页面上没有它；
   v0.50.0 是第一个真的挂上它的 release**（四件产物齐全，下载下来的二进制核过
   `.sha256`、报 0.50.0、并在只有一个 `.dawn` 文件的裸目录里编译运行通过）。
   在当时它**不是种子**：`scripts/seedjar.sh` 只下载、只校验 jar，
   `scripts/seed-checksums.txt` 里也只有 jar 的摘要。D12-2 的 native ELF 种子另走 qualified lock，
   不改 JAR 三文件的类型；详见下文 native 推进协议。
2. **祝圣仪式（机器强制）**：`scripts/build-release-jar.sh -o <jar>` 是唯一 JAR 构建
   配方；`release.yml` 的 JAR job 与日常 `selfhost-fixpoint.sh` 都只能调用它。它在 tag 上重建
   种子→A→B→C（B = HEAD 编 HEAD，即要上传的那份字节），验证 `cmp B C`、独立
   emit、原子提升后的最终路径仍与 C 相同；workflow 再精确核对源码版本、tag 与
   artifact 输出——任一红则 release 不出。push CI（ci.yml）的全金样绿是前置，
自 2026-09-11 起由 `release.yml` 的 `verified` job 机器强制：它查 Actions API 确认
`ci.yml` 在这个 sha 上有一次 push 到默认分支触发的成功运行（2026-09-25 起只认这一种，
PR 运行是子集，见下文协议段），否则拒绝这个 tag（此前的做法是在 tag 上把同一套门禁
再跑一遍）。2026-09-24 起也接受维护者签名的外部证据，条件见下文「GitHub 之外执行门禁集的证据协议」。
   D12-2 P1 后 release 还并行构建 native S→A→B→C 并验 B==C，组装九件/schema 2；
   双 JDK JAR 是独立 reference。v0.106.0 的旧八件合同是历史边界，P2 后缺真实 qualified lock 时禁止发 tag；
   首个正式 schema 2 发布仍须 P3 放行，不能把“producer 已实现”写成“已发布”。
3. **JAR 单一推进入口**：按对应 release 合同完成并校验资产后，只运行
   `./scripts/advance-seed.sh <tag>`。脚本从 `origin` 新鲜解析 tag commit，前后复核 tag
   没有移动，校验 tag 版本、HEAD 祖先关系与版本单调性；再从 GitHub Release 下载
   `dawn-selfhost.jar` 及 sidecar，严格重算摘要并执行 `--version`。std 摘要来自该 tag
   commit 的 `git archive`，**不来自当前 HEAD，也不来自 JAR**。JAR 不携带下一代 stage A
   所需的 std 源树，而 HEAD 的 std 可能已经继续演进，二者都不是这次 release 的另一半。
   脚本调用 `seed_verify` / `seed_std_verify` 做消费者侧复验后，固定按
   `seed-checksums.txt` → `seed-std-checksums.txt` → `seed-release.txt` 提升。提升开始前的
   错误不写文件；提升开始后的普通错误和可捕获信号回滚三者。SIGKILL 最多留下“旧指针 +
   已验证的未来摘要”，重跑会幂等收敛，不会留下“新指针 + 缺摘要”。三文件已完整指向目标
   时，重跑仍复验远端，工作树零 diff。sidecar 只证明下载一致，不是独立签名；提交进 Git
   的摘要仍是 TOFU 信任边界。
   下载用的仓库名（`advance-seed.sh`、`seedjar.sh`、`replay-bootstrap.sh` 共用）只写在
   `scripts/repo.env` 的 `DAWN_GITHUB_REPO` 一行；仓库换组织时改这一行，信任仍由摘要表决定，
   与 URL 无关。
   推进完成后接着部署，同样以这个 tag 为准：在 tag 的检出上先跑
   `DAWN_DEPLOY_COMMIT=$(git rev-parse HEAD) playground/deploy/redeploy.sh`，再跑 `DAWN_DEPLOY_COMMIT=$(git rev-parse HEAD) DAWN_SITE_PLAY_ORIGIN=https://play.dawnop.com DAWN_WASM_CC=clang-20 ./site/redeploy.sh`。
   站点曾因部署与发版脱钩，在 v0.78.0 已拒绝 `$name` 插值后仍教了三周旧写法。
   下面的链条表记的是**种子形态变过的那几环**，不是每一次 bump——每次 bump 的记录
   就是上述三文件和它们的提交，再抄一遍只会过期（这张表一度写着「逐条记」，却停在
   v0.8.0，中间二十一个 release 一个没记）。
4. **特性纪律**：`selfhost/src`、`compiler-plan/src` 及这条编译 closure（连同它引用的
   `std/`）只准用**当前种子已支持**的语言特性。想用新特性：先在 selfhost 实现 → 发 release（过祝圣）→
   用对应链的单一入口推进记录 → 下一轮才能自用。（Rust stage0 的规矩，
   CI 机器强制：种子编不动 HEAD 直接红。）
5. **链条可重放**：`scripts/replay-bootstrap.sh <seed-jar | vX.Y.Z>` 从任一环
   种子重放：种子编 selfhost → 固定点（stage2==stage3）→ standalone 闭包 →
   （本地有 HEAD 编译器时）验证收敛到与 HEAD 逐字节一致。**一代洗净种子**：
   stage2 只由 selfhost/src 决定、与谁编译 boot 无关，所以「老种子 + 新源码」
   也必须对出与 HEAD 相同的字节。第一阶段在没有工作树 `std/` 的隔离目录运行，
   让种子使用自己内嵌的发布 std；后续阶段才显式使用当前 std。发版前手动过一遍，
   不进 CI。CI 用离线假编译器固定这条配对规则，完整固定点仍由发版前手动重放验证。
6. **发版前的 LSP 抽样**（裁决「LSP 增量 sync 的验收线」第 6 条，2026-10-19）：改 `VERSION`
   之前，在本机空闲时跑一次 `python3 scripts/lsp-sync-bench/bench.py --jar build/dawn-selfhost.jar
   --baseline .dawn/seeds/<当前种子 tag>/seed.jar --out <文件>`，把末行摘要贴进 release 提交的正文；
   越线（退出状态 1）不拦发版，但要在 todo 里记一条。负载敏感，不进 CI，口径见
   [lsp-sync-bench-design.md](lsp-sync-bench-design.md)。

### Native 推进与启动合同（D12-2 补裁三、四，2026-11-25）

完整合同、阶段表、消费者清单与各刀停止条件见
[native-seed-cutover-design.md](native-seed-cutover-design.md) §13。这里同步日常入口与推进纪律：

| 角色 | native 配对 | 用途 |
|---|---|---|
| S | 已资格 ELF 与 seed commit 的 std/runtime | 构建当前源码的信任根 |
| A | S 编 portable 当前 `nmain` closure，发射/链接使用 seed std/runtime | 过渡 builder；内嵌 std/runtime 来自当前快照 |
| B | A 编同份当前源码，使用 current std/runtime | 源码工具链与发布对象 |
| C | B 再编同份当前源码与 current std/runtime | release/资格验证 B==C；日常缓存不强制构建 |

1. **链选择唯一**：lock 的 `chain` 是默认的唯一真相，`DAWN_SEED_CHAIN=jar|native` 是显式覆盖；
   空串/未知值拒绝。lock/history/revoked 任一存在即严格验整链，显式 jar 也不能绕过撤销或损坏；
   全无记录时默认 jar。P2 目前只在 native 验 S 后退出，P4-pre1/pre2 才实现构建及 exec B。
   pre0/pre1/pre2/pre3 不改默认，真正 P4 才通过 `advance-native-seed.py set-chain native` 生成合法历史。
2. **三种模式分别确定最终工具**：源码检出 native 执行 S→A→B、缓存并 exec 当前 B，jar exec 当前 JAR；
   源码启动器可要求 Python 3.11+。无源码 bin/ 加 build/ 部署声明为 JVM-only，由调用者显式选 jar，
   直接 exec 随部署 JAR，不自举、不调用 Python；请求 native、缺失/错误选择或种子覆盖均报错。
   installer 则明确安装原生产品 B ELF，安装后直接执行发布 B，不跑源码自举、JVM 或 Python。
   Python installer 的安装步骤与源码 Python 最低要求分开验收，不能给无源码启动引入 Python 3.11+ 依赖。
3. **JAR 显式并存且无回退**：JVM 后端、build-to-jar、`use java`、Java deps 与需 Java 类型解析的 LSP，
   使用 `DAWN_SEED_CHAIN=jar bin/dawn ...`；纯 Dawn native LSP 可继续使用。
   native `build` 产 ELF，`run/test` 经 C 工具链；不按 import、命令、缺 ELF、平台或构建失败自动转 JVM。
   native 首次启动不构建备用 JAR；发行 ELF 的 JVM 需求用独立 `java -jar dawn-selfhost.jar`。
4. **配对与环境**：`DAWN_NATIVE_SEED` 覆盖须同时声明 seed commit 与 std/runtime 路径和内容身份，
   重验 ELF 摘要/大小/版本/完整 build id；任意本地调试同样须完整配对，独立 override stamp，release 禁用。
   `DAWN_SEED` 永不指 ELF，两个覆盖变量同设或错链均拒绝。native 要求 Linux x86_64 与可完成静态链接的 C 工具链，
   缺失即失败；共用阶段原语，记录实际 CC/链接器/库闭包，不让继承环境悄悄改配方。
5. **缓存不是旧种子快捷执行**：native/JAR generation 分离，绑定 S/配对树、portable closure、current std/runtime/embed、
   recipe、实际工具链、lock/撤销与 B 字节；本地未提交修改也必须失效。以 native `__source-inputs` 为权威，
   A/B 构建前后 re-plan，锁内 staging，原子提交且 marker 最后写；等待者复验，热命中仍核身份。
   缓存污染报错；失败保留旧字节却不执行旧代。冷启动约两分钟是由 P1 阶段耗时推断，另有下载与准备成本，
   pre2 必须实测冷/热成本；P2 约 0.1 s 的 Python 校验不是完整热启动数据。
6. **native 单一推进入口**：`scripts/advance-native-seed.py initial/promote/rollback/revoke/set-chain`，
   lock/history/revoked 共用唯一严格读写模块；历史原字节只增、sequence 严格 +1，指针最后换。
   晋级版本大于历史上所有种子且不得复用摘要，验证 tag/祖先/九件/ELF/配对树与该 ELF 的 seed-promotion receipt。
   当前种子被撤销时失败关闭；恢复由维护者显式回滚到未撤销历史，不能自动选别的种子。
   JAR 三文件仍只用 `advance-seed.sh`，不手改、不把 ELF 填进 JAR 摘要表。
7. **先实现、再冻结资格、最后切换**：pre1 builder/完整 chain receipt → pre2 两阶段缓存与三模式 →
   pre3 site/Playground/release-native/gates/编辑器消费者逐个显式选链（不全局 jar）→ 最终 P3 → P4。
   P3 先实现 qualify `--lock`、receipt 绑定实际种子 lock、`check --base` 接 CI，补 P2 约 +8.5 s 预算；
   各前置新增 W 当刀写 Gate-Budget，改 gates.yml 要 record steps_lock，不等 P5。
8. **最终输入与资格对象不可偷换**：S3/S4、前置实现、机制修补与 0.107.0 版本准备都先收完。
   initial 资格 S 后生成真实 lock（仍 jar），再对实际最终 commit/tree/lock 冻结，取得最终输入证据、
   三组重链配对 3/3、至少七个有 push 样本日且十次成功 main push 经过 native 路径、归因失败零，以及五项演练。
   拟晋级 B 自身须 seed-promotion 资格与独立 verify；receipt 输入 lock 不得要求等于含该 receipt 摘要的未来 lock，
   final-inputs 证据不反写正在资格的 lock。VERSION、initial/set-chain、原型删除、merge/rebase 改变绑定身份时重核/重跑，
   不手改 receipt 或复用旧 sha 证明。补裁一要求 P4 合并删除原型，若前移须另裁；删除后的真实发布输入也必须资格。
9. **发布与晋级**：P3 放行后才能真正 P4 默认切换与 v0.107.0 九件封存；tag 的 B、full build id、commit、lock、proof
   冷下载聚合核对，无 Java 安装 hello，同 tag 重跑只验证。发布 B 与已资格候选 B/tag/配对树完全相符才复用其
   seed-promotion receipt，否则重跑；再 promote 与安排 JAR 推进。任一配对失败、native 归因失败、固定点或来源身份不符，
   停并回交，旧 S 不兼容走桥接裁定，不用 JAR fallback。D 的 pole 红灯按裁定归 CI 刀 5，不属本项观测。

三类证据分别是种子 qualification、构建 chain、日常 generation receipt，互不替代；公开资产仍九件，A/C 与完整 chain receipt
不新增为公开下载。pre1 跨 job 留存完整 receipt 90 天，并由 producer 核验实际 builder/CC；pre2 需报告热启动；
pre3 需全量调用表、双链同树对拍与离线部署预检，ci/tile 全部 completed/success；P3 若输入变化即顺延，数据不足不切 P4。
部署仍按 tag 先 Playground 后 site，保留 `DAWN_WASM_CC`；站点 prepare 去 JVM 属 P4 后的 D12-3。

### 链条表（早期 JAR 信任根）

| release | 种子形态 | 备注 |
|---|---|---|
| v0.6.0 | `dawn.jar`（Kotlin） | **信任链根**；Kotlin 冻结为 bootstrap 种子 |
| v0.7.0 | `dawn.jar`（Kotlin） | 包管理线收官版 |
| v0.8.0 | `dawn.jar` + `dawn-selfhost.jar` 双发 | **首个 selfhost 种子**（LSP 移植完成，Kotlin 最后一发）；随后 `kotlin-final` 归档 Kotlin |

## GitHub 之外执行门禁集的证据协议（2026-09-23）

托管 runner 排队或宕机时，维护者可以在自己的机器上按某个提交的 `gates.yml` 跑完整门禁集，
再把结果交给 GitHub 核验。设计与理由见 [gates-external-design.md](gates-external-design.md)，
这里只记协议本身。

1. **跑**：`scripts/gates-external/run.sh --sha <sha> --backend local --out <dir>`，产出
   `<dir>/bundle.json`（字段白名单，`complete` 按多重集重算）。
2. **谁签**：维护者本机上的专用 ed25519 密钥 `~/.ssh/dawn-gates-sign`，只签门禁证据。
   公钥钉在 `scripts/gates-external/allowed_signers`，identity 与签名 namespace 都是
   `dawn-gates`，文件里没有邮箱、主机名或用户名。私钥不进仓库、不进日志。
3. **签什么**：bundle 的规范字节，即 `json.dumps(bundle, sort_keys=True, separators=(',', ':'))`
   加一个换行。信封 `{"bundle": ..., "signature": "<armored SSH 签名>"}` 作为该提交在
   `refs/notes/gates` 上的 note。信封可以任意排版，签名只绑定 bundle 的内容。
4. **发布**：`scripts/gates-external/publish.py <sha> --bundle <dir>/bundle.json`。它先在本地
   复核 bundle，`complete` 不为 true 就拒绝（红的证据不发布），再签名、用本仓库的
   `allowed_signers` 验一遍自己的签名，然后 `git notes --ref=gates add -f`、
   `git push origin refs/notes/gates`、`gh workflow run verify-external.yml -f sha=<sha>`。
   全部连接都由本机发出，GitHub 从不连回来。
5. **GitHub 核什么**：`verify-external.yml` 从默认分支取核验器与公钥，只把被测提交当作对象读，
   依次核：note 存在；信封恰好两个字段、无重复键；签名在 `dawn-gates` namespace 下对上钉住的公钥；
   `bundle.tree` 等于该 sha；`bundle.gates_blob` 等于该 sha 上 `gates.yml` 的 blob；
   `bundle.check`（与 `bundle.py verify` 同一份代码）通过，即字段白名单、替换表恰为该提交
   `gates.yml` 推出的那张、多重集相等、每步退出码 0；`complete` 声称与重算都为 true。
   然后用 `GITHUB_TOKEN` 给该提交写 commit status，context 是 `gates/maintainer`，
   全部通过写 `success`，否则写 `failure`（不是不写），`target_url` 指向这次 run。
6. **外人能核什么**：签名与重算。任何人都可以
   `git fetch origin refs/notes/gates:refs/notes/gates` 后运行
   `python3 scripts/gates-external/verify_note.py --sha <sha>`，得到与 GitHub 相同的结论。
   外人核不了的是「这些步骤真的在那台机器上跑过」：退出码与输出摘要是维护者的陈述。

诚实边界：

- 这是**维护者自证**。签名证明的是「持钥人说这棵树上整套门禁全绿」，不是独立复现。
  它的分量等于对持钥人与那台机器的信任。
- commit status 本身不是签名。有写权限的人都能给任何提交写同名 context；可复核的证据
  在 note 里，status 只是 GitHub 界面上的一个指针。
- **fork 的 PR 不走这条路**。外部贡献者没有签名钥，他们的提交照旧由托管 runner 的
  `ci.yml` 判定。
- **release 守卫已接受它（2026-09-24 起）**。`release.yml` 的 `verified` job 调
  `scripts/gates-external/release_evidence.py`，两条证据任一成立即放行：`ci.yml` 在该 sha 上有一次
  `event == push`、`head_branch` 为默认分支的成功运行；或该 sha 上最新的 `gates/maintainer` status 为 `success`，且满足下列全部条件：creator 是
  `github-actions[bot]`；`target_url` 恰为本仓库的 `actions/runs/<id>`；从本仓库 API 读回的这次 run 是
  默认分支上 `workflow_dispatch` 触发、结论 success 的 `.github/workflows/verify-external.yml`；
  status 写入时刻落在该 run 的时间窗内。只认 state 不够，因为有写权限的人都能写同名 context，
  也能把 `target_url` 指向别的仓库或别的工作流。两条都不成立时拒绝，并打印两条各查到了什么。
  守卫不重做签名核验，它确认的是「读到的正是 `verify-external.yml` 那次核验的结论」。
  第 1 条在 2026-09-25 以前是「任意事件、任意分支上任一次成功」。两层 CI（#168）之后 PR 运行只跑
  `plan.py` 选的子集，其余 job 跳过、按 success 计，而 Actions API 把 PR 运行记在 PR 头提交的 sha 下；
  同一个 sha 若先在 PR 上子集绿、再原样快进推到 main，`any(success)` 会把子集当全集，
  哪怕 main 上那次全集是红的。所以 2026-09-25 起只认 push 到默认分支的运行，其它运行照样列出并注明拒因。
- **PR 与 main 上的证据档（2026-09-25 起）**。`gates.yml` 的 `plan` job 先用
  `release_evidence.py --external-only`（与守卫第 2 条同一份代码）读 PR 头提交的
  `gates/maintainer`；接受就输出 `all=false`、`jobs=[]`，所有 gate job 跳过，按 success 计。
  只在 `pull_request` 事件生效：push 上 `ci.yml` 不传头提交，main 的 push 运行按构造就是全集。
  不接受、API 读不了或超时都照旧规划。证据只对被签的那个 sha 有效：rebase 之后的新 sha 在 GitHub 上照常跑；
  fork 的 PR 没有这个 status，行为不变。推送时 ci 已经开跑，`publish.py --rerun-ci` 在 verify 成功、
  status 可被接受之后取消该 sha 上本仓仍在跑的 `ci.yml` PR 运行并重跑。作为第二道，守卫第 1 条同时收紧：
  读回运行的 job 列表，有 job 被跳过就不算全集。设计见
  [gates-external-design.md](gates-external-design.md)「PR 与 main 上的证据档」。
- 换钥就是改默认分支上的 `allowed_signers`。旧钥签的 note 从那个提交起核不过，没有多钥过渡期。

## JAR 链

```bash
# 0) 种子：seed-release.txt 钉住的 release 的 dawn-selfhost.jar
#    （bin/dawn 自动下载缓存；信任链根 v0.6.0 的 Kotlin jar 也可作种，
#    或从 kotlin-final tag 现编：git checkout kotlin-final && ./gradlew :compiler:fatJar）

# 1) 种子编 HEAD 工具链 closure → A；A 编同一 closure → B（HEAD 编 HEAD，规范产物）；
#    B 编 HEAD → C；cmp B C 逐字节相同 = 固定点 + 闭包一步到位。
#    A 配对 seed release 的 std，B/C 使用当前 std；vendor 逐代续传。
./scripts/selfhost-fixpoint.sh

# 需要保留规范 JAR 时直接指定输出；release.yml 的 JAR job 调用它。
./scripts/build-release-jar.sh -o /tmp/dawn-selfhost.jar
```

`scripts/build-release-jar.sh` 固化此链，且刻意不暴露 seed/std/vendor 等可重组
recipe 的参数；`scripts/selfhost-fixpoint.sh` 只是丢弃产物的兼容 wrapper，**在 CI**
（ci.yml）每次 push 重验；
`scripts/replay-bootstrap.sh <seed|vX.Y.Z>` 从任一环重放（发版前手动过）。

## launcher 的源码输入边界

现行 JAR `bin/dawn` 的 v2 generation 已使用隐藏的 `__source-inputs`，
消费 `compiler-plan/src/source.dawn` 产出的版本化递归清单；
因此 `compiler-plan`、`fspath`、`sha2`、`inflate` 等传递 local package 都是 compiler build input。
首次 clean checkout 的清单由种子构建出的 stage1 生产，不要求旧 S 认识新协议；
stage1 与最终 candidate 各做 pre/post re-plan。v1 的 shell 递归 fallback 已删除，launcher 不再解释 manifest。

`scripts/bootstrap-guards/run.sh` 在无 JVM、无下载的复制根里逐项修改 Planner 与传递依赖，要求
stamp 随之改变；`scripts/bootstrap-input-manifest-contract/run.sh` 则固定 v1 线协议、CLI 边界与
producer mutants。known-vector hasher 缺失时失败关闭、framed digest、持久化 inputs 与可恢复 commit-marker
均已落地，不能再写成未关闭残余；native generation 必须保留同等失效与事务保证，详见
[`bootstrap-input-manifest-design.md`](bootstrap-input-manifest-design.md)。

## 为什么字节级一致做得到

codegen 是确定性的：同一份源经同一实现必出同字节。**帧是算出来的，而且只从树内的表算**——
发射的 class 是版本 52，那以上 `StackMapTable` 是强制的，写入器是 COMPUTE_FRAMES
（docs/jvm-base-plan.md K-A8.2；K-A4 那阵曾降到 49 免帧，K-A8 把这条让了回去）。
那五个静态 null 适配器（ASM 的 `visit*` 要 null，Dawn 源码拼不出）现在是编译器自己发射的
`dawn/rt/Asm`；`dawn.tool.AdtClassWriter` 曾经随种子逐代续传、从不重编，K-A7 之后已退出
（jvm-base-plan.md §5.7）。同一家的第六个类 `dawn/rt/AsmWriter`（K-A8.1）是 `ClassWriter`
子类，帧计算要问的公共超类型由它回答——**只查编译当下那张 `supers_of` 表，不走
`Class.forName`**，正是为了不让发射的字节取决于编译器碰巧跑在哪个 JDK 上（§5.10 的 D4）。
帧回来了，这一条从「备着的性质」变成了字节级一致的**前提**。
历史上的跨实现验收（Kotlin vs selfhost 的 `__lex/__parse/__check/
__emit` 全仓逐字节对拍）已随 `kotlin-final` 完成使命；现行 oracle 是
**N vs N−1**（`selfhost-prev-diff.sh`：上一 release 与 HEAD 编同一语料 +
backend-dawn 生态扫描，未声明的字节差异红灯）加 CLI/格式化/LSP 三条转写差分
（`selfhost-run-diff.sh` / `selfhost-fmt-diff.sh` / `selfhost-lsp-diff.sh`）。
故意改变输出的提交要为每个受影响检查逐项声明 `Emit-Change(<label>): <说明>`；label 是
`scripts/emit-labels.txt` 的闭集，不接受 `emit *` 等通配，也不接受裸 `Emit-Change:`。

## 运行注意

- JAR 链跑 selfhost 要 `-Xss512m`：comptime 解释器递归吃 JVM 宿主栈；不是 native ELF 的运行参数。
- `selfhost build` 产物的确定性由 `jarw.dawn` 保证（manifest 在先、条目顺序不变、
  全部条目显式使用 STORED，并钉死长度、压缩后长度、CRC32 与时间戳）——闭包验收能
  `cmp` 整 jar 靠这个。STORED 不经过宿主 JDK 的 DEFLATE 实现，故 JDK 升级不会只因
  压缩器变化而改变产物字节。
- 条目时间戳走 `ZipEntry.setTimeLocal`（钉死 2020-01-01T00:00:00，无时区参与），
  配合上述 STORED 元数据，故**跨 JDK、跨时区、跨机器**重建同一 jar 得同样的字节。
  此前用的是 `setTime(epoch millis)`，
  它经默认时区换算成 DOS 时间——确定性只按机器成立，而 release 以字节固定点为核心，
  「只有在我的时区才同字节」撑不起这个说法。


P4-pre1 的 builder 与非循环资格接口见 [native-seed-cutover-design.md](native-seed-cutover-design.md) §14。
`native-seed-chain.py build` 只构建 A/B，不接启动器缓存；release 用同一原语追加 C。
`native-seed-qualify.py run|verify` 必须给 `--lock`，proposed B 还须给完整 pinned builder 来源；
资格 package 绑定编译输入摘要与受测 ELF 摘要，实际 lock 摘要单独审计。
晋级核对 ELF、配对树与编译输入，控制记录改变不要求重资格；编译输入变化必须重跑。
本机开发 CC 使用独立 recipe，不能被 release/资格引用。默认仍 jar，显式 native 的启动器构建与缓存留给 pre2。
