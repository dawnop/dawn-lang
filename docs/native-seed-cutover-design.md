# Native 种子链生产切换（D12-2 P）设计

> 状态：**current**（已采纳，2026-11-25；补裁一至四与 P1/P2 落地见 §10 至 §13；§13 是 P4 native 链与启动器的合同，pre2 显式缓存见 §15，尚待最终资格）。
>
> 前置：[native-seed-input-contract-design.md](native-seed-input-contract-design.md)（K1-K5，资格工具与隔离原型已交付，生产 no-go）。
> 本页覆盖 P0-P5 及补裁四新增的 P4-pre0/pre1/pre2/pre3；前置开发不授权改默认或发版。不含 D12-3（站点 prepare 去 JVM），它依赖本页 P 的 builder 合同，在 P4 之后另起设计页。
> P0 基线 main `6c9614f2`；P4-pre0 核对基线 `33ee0a6b`。早期方案与后续裁定冲突时，以后续裁定及 §13 为准。

## 1. 现状与目标

### 1.1 P0 时的基线（历史快照）

以下是 P0 的八件/schema 1 旧状态。P1 已实现九件/schema 2 与不可覆盖发布，P2 已实现 lock 消费；
当前尚无真实 qualified lock，release 被机器冻结，源码启动器默认仍 jar，显式 native 两阶段缓存见 §15。

- **发布合同是八件资产，schema 1**。`.github/workflows/release.yml` 的 publish 步把资产分成两张表：
  `INSTALL_ASSETS`（`dawn-selfhost.jar`、`dawn-selfhost.jar.sha256`、`dawnc-linux-x86_64`、
  `dawnc-linux-x86_64.sha256`、`dawn-toolchain.json`、`install-native.py`，README 下载块逐名取用）与
  `REPORT_ASSETS`（`dawn-pub-api.json`、`dawn-pub-api-diff.md`，只描述发布，不被安装步取用）。
  `scripts/doc-check.py` 双向核对两张表与 README。
- **上传仍是 `gh release upload "$GITHUB_REF_NAME" --clobber`**（release.yml 第 324 行）。
  上方的「重跑收敛」注释依赖它：create 只在缺席时做，upload 覆盖全部名字，随后断言每个合同名恰好一次。
  `scripts/bootstrap-guards/run.sh` 第 483、542 行把这一行与「create、clobber-upload、verify」的顺序钉成了守卫，
  所以撤 `--clobber` 同时是改一条守卫的语义。
- **种子链是 JAR 链**：`scripts/seed-release.txt`、`seed-checksums.txt`、`seed-std-checksums.txt` 三文件，
  由 `scripts/advance-seed.sh` 原子推进；`bin/dawn` 以 JDK 21 运行种子 jar，`DAWN_SEED` 只指 jar
  （[bootstrap.md](bootstrap.md)「种子推进协议」）。
- **native 侧只有隔离资格**：`scripts/native_seed/`（K1-K4 资格工具）、
  `scripts/native-seed-candidate-v0.104.0.json`（`state=candidate`、`sequence=0`、lineage 全 null、
  `registration.metadata=absent`）和 P0 的隔离 schema 2 原型（schema 2 的 producer、聚合、installer
  原型，共 419 行，只写调用者的新目录）。K5 在最终输入 `f68940f4...` 上证明了双 root 冷链 B/C 一致、
  Java exec=0、外网 syscall=0，原型 26 项拒绝控制通过（出处：K5 交付记录与
  [native-seed-input-contract-design.md](native-seed-input-contract-design.md)）。
  `validate_lock` 现在只接受 `candidate`/`sequence 0`，不认已资格的 lock。

### 1.2 目标

| 维度 | P0 基线 | P4 之后 |
|---|---|---|
| 发布资产 | 八件，`dawn-toolchain.json` schema 1 | 九件，schema 2，第 9 件 `native-bootstrap.json`（归 `REPORT_ASSETS`） |
| `dawnc-linux-x86_64` 的来源 | 由 JAR 链的产物经 `release-native.sh` 构建 | 由 native builder A（种子 S 编出）发射 B，B==C 验证；JAR 作独立 reference |
| 种子 | JAR 三文件 lock | native ELF lock（单一 lock、lineage、单调序号、撤销名单、回滚记录）；JAR 链按 R7 保留 |
| 上传 | `--clobber` 覆盖 | 种子资产被引用后不得覆盖，错版发新 tag |
| 冷安装 | 需要 JVM 才能自举 | 无 Java 冷安装并自举 |

JAR 链**不删**（R7）：它是显式 JVM 产品、对照与历史重放。删链须另案。

### 1.3 切换门槛原文（裁决第 1 条）

下列是协调者裁决的原文，本页不增不减，也不替用户豁免：

> 不宣称观测合格，不豁免用户的条件。用户授权的是「观测合格后执行切换」；协调者无权放宽。
> 生产切换（P4 首个 schema2 发布）的门槛定为：在最终冻结输入上
> (a) 重链配对 3/3 成功，
> (b) 至少 7 天同形态 main push 样本中 native seed 归因失败 0，
> (c) D 的 pole 观测红灯归 CI 刀 5 处理，不作为 native seed 的观测项
> （它与 native seed 无因果，K5 报告已声明）。

推翻判据（同一裁决）：P3 重新资格中任一配对失败或出现 native seed 归因失败，P4 停，回交；
S3 之后输入仍在变，P3 顺延，不在移动输入上资格。

与门槛相关的现状事实（出处：只读就绪评估，2026-11-24 对托管 Actions 的查询）：K5 合并后 main 有 21 次成功
push run、native seed 归因失败 0；但最后一次 push 在 11-16，同形态样本约 4.4 天；重链不在 push 路径上，
重链配对 0/3，等待不会产生数据。所以 (a)(b) 的数据只能由 P3 在冻结输入上主动产生，见 §5。

## 2. P1：schema 2 协议（producer、聚合、installer、contract 原子同步）

### 2.1 为什么必须原子

八件合同的各端互相核对：`release.yml` 的两张资产表、`scripts/release-native.sh` 的产物检查、
`scripts/install-native.py` 的 `INSTALL_INPUTS`、`scripts/bootstrap-guards/run.sh` 对 release.yml 逐行的守卫、
`scripts/doc-check.py` 对 README 的双向核对、README.md 与它的译本 README.zh-CN.md（`doc-check` 的
`TRANSLATIONS` 摘要）。任何一端单独升到 schema 2，其余端要么红，要么悄悄地仍接受 schema 1。
所以 P1 是**一个 PR 内的一组提交**，合并前不得让任一端处在中间态；合并点之前发布的 tag 仍是八件。
v0.106.0 是旧合同的最后一版（裁决第 2 条），P1 的任何发布文件改动晚于它合并。

R8 的三条不变：schema 2 一次性破坏性升级，不保留 schema 1 自动兼容（不新增兼容分支，也不为
v0.104.0 缺 metadata 保留长期分支）；不把 ELF 伪装成 `dawn-selfhost.jar`；撤掉对受信资产的 `--clobber`。

### 2.2 九件资产，逐件字段与身份校验

资产名沿用现有 `dawn-selfhost.jar` 与 `dawnc-linux-x86_64`，不改名。第 9 件新增。校验由三处共用
同一份 `identity` 模块（由原型 `identity.py` 升格为生产模块，供聚合与 installer 共用，避免两份规则漂移）：

| # | 资产 | 表 | 身份与校验（任一失败即拒绝，无忽略开关） |
|---|---|---|---|
| 1 | `dawn-selfhost.jar` | install | JVM reference。字节摘要 = metadata `jvm_reference.sha256`；`jvm_reference.commit` = `release.commit`；`jdk_equivalence_sha256` 为 64 位十六进制。不得被 native 路径当作 ELF 或种子 |
| 2 | `dawn-selfhost.jar.sha256` | install | 内容恰为 `<sha256>  dawn-selfhost.jar\n` |
| 3 | `dawnc-linux-x86_64` | install | native B。必须是静态 x86_64 ELF（沿用 `verify_elf`）；长度 = `native.size`，摘要 = `native.sha256`；`--version` 恰为 `dawnc <version> (native) <build_id 前 15 字符>`，`version -m` 里的完整 `b1:` build id = `native.build_id` |
| 4 | `dawnc-linux-x86_64.sha256` | install | 内容恰为 `<sha256>  dawnc-linux-x86_64\n` |
| 5 | `dawn-toolchain.json` | install | schema 2（见 §2.3）。规范 JSON，拒绝重复键、bool 冒充整数、未知字段 |
| 6 | `install-native.py` | install | 单文件 installer，仓库坐标在发布时嵌入（现行 `@REPOSITORY@` 机制保留）。只核自己取得的 B、sidecar、metadata，不下载或执行 A、JAR 或编译链，不声称独立证明来源（K5 原型同口径） |
| 7 | `dawn-pub-api.json` | report | 沿用现有生成方式，不属 native 身份 |
| 8 | `dawn-pub-api-diff.md` | report | 同上 |
| 9 | `native-bootstrap.json` | report | 自举证明（见 §2.4），摘要被 `dawn-toolchain.json` 的 `proof.sha256` 引用 |

聚合检查（producer 末尾与 installer 前置都跑）：目录里恰好这九个名字、每名一次；
metadata、payload、sidecar、proof 互相引用的摘要全部对得上；`release.tag`/`version` 与实际 tag 一致；
`bootstrap.seed.tag` 的版本不大于本次 tag。

### 2.3 `dawn-toolchain.json` schema 2

字段集合直接取自已演练的原型，生产只做两处改动（见 2.3.1）：

```
schema                2（整数；1、未知值、true 一律拒绝）
release               {tag, version, commit}
native                {name, kind="native-elf", stage="B", sha256, size, build_id, target}
builder               {name="dawnc-stage-a", kind="native-elf", stage="A", sha256, version, build_id}
bootstrap             {seed, std, runtime, parent_receipt_sha256}
recipe                {inputs_sha256, toolchain_sha256, recipe_sha256}
proof                 {name="native-bootstrap.json", sha256}
jvm_reference         {name="dawn-selfhost.jar", kind="jvm-jar", sha256, commit, jdk_equivalence_sha256}
```

规则：整份 metadata **不含时间戳、run id、主机名**，保证同输入同字节（§2.5 的重跑比对依赖这条）。
`builder.version` 必须等于 `release.version`（旧种子不得把版本改写成当前版本，沿用 K5 的拒绝项）。
`builder.kind` 在生产里只允许 `native-elf`；原型里的 `jvm-jar` 类型臂只存在于「不能当 native 资格」的负控，
生产不保留该臂（不新增死分支）。

#### 2.3.1 与原型的两处差别

1. **A 在生产里是 release job 自己用种子 S 编出的，不是资格包里的 A。** release job 内做一条
   S→A→B→C（B 为 A 编当前 commit，C 为 B 编当前 commit，`cmp B C`），与 `scripts/build-release-jar.sh`
   对 JAR 链所做的同构。`bootstrap.seed` 取自**该 tag 检出里的已资格 lock**，不取自任何外部输入。
2. **proof 去掉 `prototype_only` 与 `kind=native-bootstrap-prototype`**，改 `kind=native-bootstrap`；
   `qualification_sha256` 的含义改为「该 tag 检出里 lock 所引用的、种子自己的资格 receipt 摘要」，
   而不是本次 release 的全套资格包（release 仍跑双 JDK JAR 比对与 native 三阶段，完整资格另跑，见 §10、§11）。

### 2.4 `native-bootstrap.json`

字段：`schema=2`、`kind="native-bootstrap"`、`source_commit`、`lock_sha256`（tag 检出里 lock 文件字节的摘要）、
`qualification_sha256`、`cold_sha256`（release job 内 S→A→B→C 链的规范 receipt 摘要）、`builder_sha256`（A）、
`native_sha256`（B）、`identities_sha256`（metadata 去掉 `proof` 键后的规范摘要）。
metadata 引用 proof 的字节摘要，proof 引用 metadata 去 `proof` 键后的摘要，**无循环**（原型已证）。

### 2.5 撤 `--clobber` 后的发布语义

#### 2.5.1 原则

- **资产的「被引用」分两级。** *已封存*（sealed）：该 release 上 `dawn-toolchain.json` 已存在；
  此后任何消费者（installer、`advance-seed`）都可能已经依据它信任其余资产。*已入锁*：某个 lock 或历史记录
  已按摘要引用这些字节。两级之后任何覆盖都不允许；`--clobber` 全仓 0 命中（grep 负控）。
- **封存标记就是 `dawn-toolchain.json` 本身，并且最后上传。** 之前的任何中间态对消费者都是「metadata 不存在」，
  consumer 一律拒绝，所以未封存阶段的半成品对信任链没有影响。这条是整套语义的支点。
- **工作流永远不删除、不替换已存在的资产。** 发现不一致就红，由维护者决定：新 tag（默认），或者在
  尚未封存且无人引用时手工清理再重跑（事故处理，记录在案，不写进自动路径）。

#### 2.5.2 上传顺序

固定顺序：`dawn-selfhost.jar`、其 sidecar、`dawnc-linux-x86_64`、其 sidecar、`install-native.py`、
`dawn-pub-api.json`、`dawn-pub-api-diff.md`、`native-bootstrap.json`、**最后 `dawn-toolchain.json`**。
逐件上传，不再用单次 `gh release upload` 批量带 `--clobber`；不带任何覆盖标志，因此对已存在名字由 `gh` 自身报错。

#### 2.5.3 每个资产的「已存在」比对类别

| 类别 | 资产 | 已存在时 |
|---|---|---|
| 逐字节 | 1-6、9、5 | 下载已发布字节，与本次本地重建字节逐字节相等才算「已就绪」；不等则红 |
| 采纳 | 7、8 | 下载已发布字节，通过格式校验（JSON 可解析且有快照必需字段；diff 非空）后**用它替换本地副本**，不比较。理由：pub-API 的 diff 取「上一个 release」，两次运行之间若又出了新 release，重生成的 diff 会不同；而 metadata 与 proof 不引用这两件，采纳不影响身份链 |

逐字节比对要求同输入同字节：B 与 JAR 均已有固定点（B==C，K5 两 root 一致），metadata 与 proof 无时间戳（§2.3）。
P1 已实测跨托管 runner 同字节，失败上传也不留截断资产，结果与边界见 §11.1。

#### 2.5.4 状态机

对一个 tag 上的 release，运行开始时读取状态：

| 状态 | 判定 | 本次运行做什么 |
|---|---|---|
| R0 无 release | `gh release view` 失败 | 创建 release（只此一处 `gh release create`），转 R1 |
| R1 未封存，资产为合同名的某个子集 | 无 `dawn-toolchain.json` | 按 2.5.2 顺序逐件：缺则上传；在则按 2.5.3 比对；全部就绪后转 R2 |
| R2 全九件到齐且已封存 | 九名各恰一次，metadata 在 | 只做验证：把九件下载到干净目录，跑聚合检查与 installer 的前置核对；通过则成功，**不上传任何东西** |
| E1 已封存但缺件 | metadata 在，有合同名缺失 | 红，不补传。缺的是被引用的字节，补传等于由工作流再造一份受信资产；维护者发新 tag |
| E2 字节不等 | 逐字节类别比对失败 | 红，不覆盖不删除。输出两侧摘要。未封存时维护者可手工清理该资产后重跑；已封存则只能新 tag |
| E3 多余合同名重复或未知同名 | 某合同名出现次数不为 1 | 红（沿用现有「恰好一次」断言） |
| E4 历史额外资产 | 非合同名的资产 | 容忍（沿用现有语义），但不得与合同名冲突 |

中断点与重跑结果：

| 中断位置 | 留下的状态 | 重跑 |
|---|---|---|
| create 之后、首件上传之前 | R1，零资产 | 正常补齐 |
| 某件上传中途 | R1。P1 实测不留截断资产，但中断后完整资产可能延迟出现（§11.1） | 上传失败后重看列表；出现则按已存在比对，不出现则报错，重跑再收敛；字节不等落 E2 |
| 前八件已传、metadata 未传 | R1，未封存 | 比对前八件并补传 metadata；未封存期间消费者看不见可信 metadata |
| metadata 刚传完、最终核对未跑 | R2 | 只验证，通过即成功 |
| 最终核对中失败（如下载损坏） | R2 | 重跑再验证；持续失败即事故，维护者发新 tag |
| 封存后有人删了某资产 | E1 | 红；新 tag |
| advance-seed（native 版）已引用该 tag 后，工作流被手动重跑 | R2 | 只验证，不可能修改字节 |

#### 2.5.5 与现有守卫的冲突与改法

P0 时 `scripts/bootstrap-guards/run.sh` 的守卫要求旧上传整行及顺序；P1 已改为：断言生产路径中 `--clobber` **不出现**；断言「create 唯一调用、逐件循环、metadata 最后、最终验证在上传之后」的新顺序；
并新增变异负控：把任一逐件上传改回带覆盖标志、把 metadata 挪到非末位、去掉 R2 的验证步，守卫均须红。
这与「门禁的绿没有信息量」一致：先证明会红，再宣称它是守卫。

### 2.6 P1 验收判据

- 原型 26 项拒绝控制全部搬进生产合同，并在生产路径上仍正确地红或绿（逐项列表对账，不得缩项）。
- `--clobber` 在 `.github/` 与 `scripts/` 生产路径 0 命中；设计页保留旧行为的历史引用（P1 实测口径，§11.3）。
- 状态机 R0 至 R2、E1 至 E4 与七个中断点各有一条用假 `gh`（本地桩）驱动的测试，覆盖「中断后重跑得到相同终态」。
- 在一个**非生产演练仓或演练 tag** 上完整走 producer、聚合、installer 三步，且对同一演练 tag 实际重跑一次，
  记录两次构建的 B、JAR、metadata、proof 是否同字节，作为 2.5.3 逐字节类别的实测出处。
- `scripts/doc-check.py` 双向核对（INSTALL 6 + REPORT 3）通过；README.md 先改、README.zh-CN.md 译本同步。
- 旧八件 schema 1 的任何分支在生产代码里 0 残留（没有兼容层）。

### 2.7 P1 推翻判据

撤 `--clobber` 后无法设计出可收敛的中断重跑：具体即开放问题 1 的实测显示跨 runner 重建不同字节，
或失败上传会留下无法区分的半资产：停并回交。草稿 release 后备须另裁，不能自行切换（补裁一）；P1 两前提已成立（§11.1）。

## 3. P2：lock 消费、单调晋级、撤销与回滚

### 3.1 文件与记录

| 文件 | 内容 |
|---|---|
| `scripts/native-seed-lock.json` | 当前 lock，schema 2、`kind=native-seed-lock`，状态 `qualified`，含 `sequence`（从资格后的 1 起，严格 +1） |
| `scripts/native-seed-history/<sequence>.json` | 每个旧 lock 的原字节，只增不改（R6「历史 bytes 保留」）；回滚也写一条新记录，不改旧记录 |
| `scripts/native-seed-revoked.txt` | 撤销名单：每行 `<种子 ELF sha256> <原因关键字>`，按摘要排序；只增不减 |

现有 `scripts/native-seed-candidate-v0.104.0.json` 在 P3 初始资格通过后转成 `scripts/native-seed-lock.json`
的第一条（`state=qualified`，`sequence=1`，`lineage.qualification_sha256` 填入，`registration` 保留原样
`historical-v0.104.0`/`metadata=absent`，如实写明历史事实）。`validate_lock` 扩展识别 `qualified`，
候选状态仍只在资格工具内部存在。

### 3.2 启动器如何消费

- 新增**独立**环境变量 **`DAWN_NATIVE_SEED`**，指向一个本地 ELF，语义对应现有 `DAWN_SEED` 之于 jar。
  **`DAWN_SEED` 永不解释 ELF**，反向亦然：值的文件头不符所属变量的类型就拒绝（R6）。
  两个变量同时设置是错误，不择一。
- 默认路径：启动器读 lock，按 `seed.tag` 取缓存目录 `.dawn/native-seeds/<tag>/`，缺失则从该 tag 的 release
  下载 `dawnc-linux-x86_64` 并**严格重算** sha256、size、`--version`、完整 build id，全部等于 lock 才使用；
  任何一项不等直接失败，没有「忽略摘要」的常驻开关（R11）。
- `DAWN_NATIVE_SEED` 覆盖必须同时声明配对 std/runtime 身份，详见 §13.3；覆盖路径仍进入 bootstrap stamp 的「override」帧（对应 `bin/dawn` 里 `dawn-bootstrap-digest-v2`
  对 jar 的做法），所以覆盖产物不会被误当默认缓存复用；release job 里该变量必须未设置，由 release.yml 断言。
- 选择链（native 种子链或 JAR 种子链）由一个显式的启动器选择量决定，**两条链之间没有任何自动回退**：
  选了 native 而种子缺失或不合格就失败，不悄悄改走 JVM。默认值在 P4 才改；P2 到 P4 之间默认仍是 JAR 链。
  P2 已定稿：lock 的 `chain` 是默认的唯一真相，`DAWN_SEED_CHAIN=jar|native` 是唯一显式链覆盖量；全无记录时默认 jar，任一记录存在则必须严格验证整链（§12.2）。

### 3.3 晋级（`advance-native-seed`）

`scripts/advance-native-seed.py promote TAG` 是 native 晋级入口，保持与 JAR 版同样的「指针最后动」纪律：

1. 从 origin 新鲜解析 tag commit，前后复核 tag 未移动，tag 是 HEAD 祖先；
2. 下载九件资产，跑 §2.2 的聚合检查与 installer 前置核对；
3. 检查**单调性**：新 `tag` 的版本严格大于历史上所有种子版本且不得复用旧种子摘要，`sequence = 当前 + 1`，
   `lineage.parent_lock_sha256` = 当前 lock 字节摘要，`parent_receipt_sha256` = 该 tag 的 metadata 所记的
   上一代 receipt；
4. 检查**未被撤销**：新种子 sha256 不在撤销名单；
5. 要求一份对该 ELF 的 `seed-promotion` 资格 receipt（K5 工具的 `native-seed-qualify.py run`，reason
   `seed-promotion`），其摘要写入 `lineage.qualification_sha256`；没有就拒绝，不允许先晋级后补；
6. 先把旧 lock 原字节写入 `native-seed-history/<旧 sequence>.json`，再原子替换 `native-seed-lock.json`。
   中断恢复：历史文件先于 lock 落盘，重跑见到「历史已写、lock 未换」时幂等收敛；见到「lock 已换、历史缺失」不可能
   发生（顺序保证），出现即判污染，拒绝并报错。

回滚：`advance-native-seed.py rollback <seq>`。只允许回到**历史里存在、未被撤销**的种子；生成一条新 lock，
`sequence = 当前 + 1`，`lineage.transition = "rollback"`，`lineage.rolled_back_from = <被放弃的 sequence>`，
`reason` 必填；不改旧历史，不降序号。回滚后重新晋级须选一个版本严格大于被放弃种子的 tag，
避免「回滚后又晋同一个坏版本」。

撤销：向撤销名单追加一行。若当前 lock 的种子被撤销，启动器**失败关闭**（不是回退到别的种子），
维护者须先做一次回滚到未被撤销的历史种子。**撤销再入选拒绝**：晋级与回滚两个入口都查名单，
任何已撤销摘要都不能再成为种子，即使它的 tag 更高、资格 receipt 有效。

### 3.4 P2 验收判据

- 负控各一且先证明会红：单调（同版本重晋、降版本晋级）、序号跳号、parent 摘要错、资格 receipt 缺失、
  回滚到不存在的历史、回滚到已撤销种子、撤销后再入选、`DAWN_SEED` 指 ELF、`DAWN_NATIVE_SEED` 指 jar、
  两变量同设、缓存里字节被篡改、下载的 ELF 版本串不符。
- 晋级与回滚的每个中断点（历史写前、历史写后 lock 换前、换后）重跑得到相同终态。
- 严格失败：没有忽略摘要的开关，grep 负控。
- 对 `scripts/advance-seed.sh` 的 JAR 三文件协议零改动（`git diff` 为空），JAR 链行为不变。

### 3.5 P2 推翻判据

若 lock 的 `sequence`/`lineage` 字段不足以表达回滚后再晋级的完整因果链（例如无法区分两条回滚路径），
须扩 schema 而不是用注释补，回交重裁。

## 4. P3：最终冻结输入上的重新资格与演练

### 4.1 前提

S3/S4、全部 P4-pre 与 P3 机制修补收完后输入冻结（补裁四，详见 §13.7）。0.107.0 的版本准备须先进入冻结候选，
不能在资格之后临时 bump。冻结覆盖 `selfhost/`、`compiler-plan/`、`std/`、`packages/`、统一 C recipe、runtime、
启动器及观测接线；当前资格还绑定完整 Git tree 与 commit，控制记录、合并与原型删除也必须重核。
资格 receipt 的 inputs 摘要绑定整树
（K5 最终输入 3935 项，tree `5cddb9ee...`，inputs `f68940f4...`；这个值在冻结后会换新，旧包失效）。
输入再变则 P3 顺延，不在移动输入上资格。

### 4.2 重新资格

在冻结 commit 上用 K5 入口 `scripts/native-seed-qualify.py run` 做两次：

1. reason `initial-seed`：把 v0.104.0 候选转为已资格 lock（§3.1）；
2. reason `seed-promotion`：对 P4 将要晋级的那份 B（即由 v0.104.0 种子编出的冻结 commit 的 B）。

P3 先实现 `--lock` 并核对 receipt 的 `seed_lock_sha256` 与实际被资格种子 lock；不能继续写死候选。
initial 的种子资格、final-inputs 的最终树资格、B 的 seed-promotion 资格分别留证，非循环绑定见 §13.7。
资格含 K5 定义的整套（捕获、双 root 冷链、固定观察器夹具、Q1-Q10、事务、双 JDK/replay、双链、原
`native-fixpoint`、原 `native-cli-diff`、封包、独立 verify）。重活的计时与租约由写者按现有规矩执行，
本页不展开。

### 4.3 三组配对与归因口径

「配对」沿用补裁六的定义：**同一最终冻结输入上**的两次完整重链，按
event / original run / attempt / image / steps / source / seed / toolchain / recipe / cold 身份分组，
失败、取消、截尾、事故单列保留，不以 job 名拼旧样本，不把 Q 算进 D。
门槛 (a) 要求 **3/3 成功**。任何一组失败，P4 停（裁决推翻判据），不以「再跑一次凑够三组」绕过：
失败组保留为数据，且重新开始计数需要裁决。

### 4.4 七天归因失败 0 的统计口径

门槛 (b)：「至少 7 天同形态 main push 样本中 native seed 归因失败 0」。口径钉死如下，避免到时再解释：

- **同形态**：最终冻结的 native 轻步骤、selector/lock/失败语义、gates.yml job 集合、steps.lock 与实际准备成本一致；任一改变重新起窗（§13.7）。
- **7 天**为至少 7 个有 push 样本的日历日，且至少 10 次成功 main push 经过 native 种子路径；零 push 的日子不计入天数，也不阻断（补裁一第 3 条）。
- **native seed 归因失败**：失败 job 的失败步骤属于 native seed 轻步骤（`scripts/native-seed-light.py`）、
  native lock 消费（P2 之后）、或 native 链 fixpoint 类 job 的种子准备阶段，且不是仅因后继 push 顶替造成的取消。
  取消（被后继 push 顶替）不计失败也不计成功，单列。基础设施事故（runner 掉线、下载超时）单列，须在报告里逐条判定归因，
  不得默认算「非 native seed」。
- **D 的 pole 红灯不属于该观测项**（裁决 1(c)）：它自 K5 之前即存在（出处：K5 交付记录，
  托管观测 D 最大 1157 秒超过 pole 950 秒）。本页不处理它，也不据此阻塞 P4。口径划分在汇报时向用户说明。
- 统计结果是一张逐 run 表（run id、attempt、sha、job 结论、归因判定），不是一个布尔值。

### 4.5 五项演练的判据

全部在 P2 实现完成后，对**真实已发布的 tag**（v0.104.0 与 v0.106.0 的 native 产物，加 P4 之前的演练 tag）
执行，不用原型本地目录代替：

| 演练 | 通过判据 | 不通过的信号 |
|---|---|---|
| 晋级 | 从已资格 lock 晋到一个更高的已发布 tag，lock 与历史按 §3.3 落盘，`sequence+1`，重算摘要一致；之后用新种子完成一次 S→A→B→C | 任何摘要不一致、历史缺失、序号不对 |
| 回滚 | 回滚到历史种子，生成回滚记录，之后以该种子完成一次冷链且产物与回滚前用同一历史种子编出的字节相同 | 回滚后产物不同或记录缺字段 |
| 撤销再入选拒绝 | 撤销一个摘要后，晋级与回滚两个入口都拒绝它；当前种子被撤销时启动器失败关闭 | 任一入口放行，或启动器回退到别的种子 |
| 无 Java 冷安装 | 干净容器（`PATH` 中无 `java`，无 JDK 目录），仅用九件资产里的 installer 安装，`--version` 与完整 build id 正确，并能在空目录里 `run` 一个 hello；过程审计 Java exec = 0、外网 syscall 只限下载 | 出现任何 Java exec，或 installer 需要 JAR |
| 升级失败保旧 | 安装一个故意损坏的版本（错摘要、错版本串、错 build id、截断）均被拒绝，原 `bin/dawn` 的字节不变 | 旧字节被改动 |

K5 的 P 前 no-go 清单第 4 项（原型与模块 installer 不替代生产验收）由本表闭合。

### 4.6 P3 验收与推翻判据

- 验收：两次资格 receipt 独立 verify rc=0；两 root 的 B/C 一致；Java exec = 0；五项演练各留原始记录；
  (a) 三组配对 3/3 的逐组表；(b) 的逐 run 表在窗口满足时补入。
- 推翻：冷链 B 不等于 C 且无法归因，停工另裁（沿用 native seed 裁决）；v0.104.0 native 冷启动不了冻结源，
  走桥接发布（沿用）；任一配对失败或出现 native seed 归因失败，P4 停，回交。

## 5. P4：首个 schema 2 发布（v0.107.0）与 P5：预算收口

### 5.1 P4

前提：P0 至 P3 全部验收，且门槛 (a)(b) 满足。v0.106.0 已先发（旧八件合同的最后一版）。

1. `VERSION=0.107.0` 已在 P3 冻结前准备；P3 放行后通过 `advance-native-seed.py set-chain native` 生成合法历史，不能手改默认。
   精确 tag commit 的实际输入、lock、合并及原型删除均须重核并满足 §13.7，等 main CI 全绿后只推该 tag（禁止 `git push --tags`）。
2. release.yml 按 §2.5 发九件；失败走状态机，不覆盖。
3. **真实 tag 冷下载与同提交聚合**：在干净环境下载九件，跑聚合与 installer；metadata 的 `release.commit` 等于 tag
   commit，`bootstrap.seed` 等于该 commit 里的 lock。
4. 冷下载发布 B，与 P3 待晋级 B、tag commit、配对 std/runtime 逐项对账；相同才可消费该 B 的 `seed-promotion` receipt，否则重新资格及独立 verify。
   然后用 `advance-native-seed.py promote v0.107.0` 晋级（§3.3），JAR 三文件仍由原入口按发布安排推进。
5. 部署仍按既有规则以 tag 为准：先 Playground 后站点，站点带 `DAWN_WASM_CC`。native 种子只换构建链，
   对同 tag、同配方可比的 C/wasm/site 文件集逐字节对拍并做既有服务/CLI 验收；pre3 必须列明文件集。
   JAR 与 ELF、不同链来源 receipt 分别核身份，不能要求它们互相字节相等，也不能据此豁免可比运行产物。
6. 默认 native 后源码启动器执行当前 B，JAR 链只显式选择（§13）；P4-pre 不提前切默认。

observe 删除的 S 刀已在 P3 前收完，P4 随带的是发布而不是语言改动。

P4 推翻判据：冷下载聚合失败、重跑出现 E2、部署产物与 JVM 链不一致，任一即停并回交；已发布的 tag
不撤改，错版发新 tag（v0.107.1）。

### 5.2 P5：预算收口

P3 已须取得最终输入的配对与观测数据，不能挪到 P4 之后。P5 结合后续托管数据收口长期预算与生产频率：

- 数据：累计三组成功配对，同形态七天，D/W 与 Q/S 同报，残差解释（补裁六的口径）；
- 频率：沿用资格期口径「最终 sha 与种子晋级时」，是否需要周期性（nightly）另列选项，不先预设；
- 结论形式：一份 Gate-Budget 声明（只有总量改变才写）与 steps.lock 记录；
- 验收：数据不足则 P5 不收口，维持未通过，不先改声明使观测转绿。

D12-3（站点 prepare 去 JVM）在 P4 之后另起设计页，不并入 P，P2 之前不得动 site prepare。

## 6. 每刀汇总：验收、推翻、与 CI 预算、冲突面

| 刀 | 范围 | 验收要点 | 推翻判据 | CI 预算 | 冲突面 |
|---|---|---|---|---|---|
| P0 | 本页，docs-only | `doc-check` 0 unknown，每条性能断言有出处，末尾有「不做」 | 评审推翻 §2.5 的上传语义 | 0（docs-only，不碰 workflows） | 只改 docs 与 docs/README.md |
| P1 | schema 2 协议、第 9 件、撤 `--clobber` | §2.6 | §2.7 | 目标 0：release.yml 仅 tag 触发，不入 push 总量；守卫改写与新增变异负控并入现有 `bootstrap-guards` 步骤，不新增 job。若必须新增步骤，须在 PR 里按补裁核算并写 `Gate-Budget` | release.yml、release-native.sh、install-native.py、bootstrap-guards/run.sh、doc-check、README 及译本；与 S1 无文件重叠（裁决） |
| P2 | lock 消费、晋级、撤销、回滚 | §3.4 | §3.5 | 轻结构检查扩到 lock/history/revocation，并入 `native-seed-light`，**不新增步骤**。该轻步骤实测日志跨度 10.363 秒、整体新增控制上限 30 秒（K5），余量约 19.6 秒；P2 目标 ≤ +5 秒，实测超出则按补裁重核 | 与 S2 都可能改 `gates.yml`：**同一时刻只许一方改**，先合者先，后者 rebase（裁决）；steps.lock 须 `steps_lock.py record`；`bin/dawn`、gate-map |
| P3 | 先补 `--lock` 绑定、`check --base` 接 CI，再冻结资格与演练 | §4.6、§13.7 | §4.6 | 机制改动须记预算及 steps_lock，含 P2 的约 +8.5 s；完整资格不入 push 路径 | gates.yml 修改串行；最终资格不得与输入修改并行 |
| P4 | v0.107.0 发布 | §5.1 | §5.1 | tag 触发，不入 push 总量；P1 已实测 native 与 JAR 并行链，输入变化后按 §13.5 复测 | lock、原型删除、seed 文件；最终输入核验与发布部署顺序 |
| P5 | 预算与频率 | §5.2 | 数据不足即不收口 | 长期收口；前置刀新增 W 必须当刀声明，不等 P5；K5 的 38683 秒仅为历史基线，不能当当前余量 | gates.yml、steps.lock、budget-observations |

通用约束：每个 PR 一个主题，每刀一个提交；碰 gates.yml 的刀写 `steps_lock.py record`；改变工具链输出的提交为每个被改动的
检查 label 写 `Emit-Change(<label>): ...`；README 英文先改，译本后改；提交与 PR 全英文，无署名 trailer。

## 7. 外部实例

出处沿用 native seed 调研与 P 评估的链接，本次逐个确认了可达性（HTTP 200）；**可达只说明页面存在，没有逐页重读正文**，
下表「启示」一栏是对既有调研结论的转述，不是本次新读的引文。

| 项目 | 做法 | 对本设计的启示 | 出处 |
|---|---|---|---|
| Rust | stage0 取近期 beta 预编译 rustc，种子身份集中在一个文件，由 `bump-stage0` 工具按发布节奏推进；2025-05 重设计为同时下载预编译 beta std | 身份集中在单一 lock、由工具推进（对应 P2 的 `advance-native-seed`） | https://blog.rust-lang.org/inside-rust/2025/05/29/redesigning-the-initial-bootstrap-sequence ；https://rustc-dev-guide.rust-lang.org/building/bootstrapping/what-bootstrapping-does.html 。`bump-stage0` 源码镜像链接（android.googlesource.com）本次未核可达，不引用 |
| Go | 明文最低引导版本，约每年抬高一次；1.5 起从 Go 1.4 自举的历史切换有专门计划 | 「单调抬高最低种子」与「写明历史事实」是公开政策（对应 lock 的单调序号与 registration 历史记录） | https://go.googlesource.com/proposal/+/master/design/go15bootstrap.md ；https://go.dev/doc/install/source ；https://go.dev/doc/go1.5 ；https://github.com/golang/go/issues/75143 |
| Zig | 以 wasm 种子加 `bootstrap.c` 取代 C++ 实现，种子是仓里受控二进制 | 仅作对照；本项目已否 wasm 种子（R12） | https://ziglang.org/news/goodbye-cpp/ ；https://github.com/ziglang/zig/blob/master/bootstrap.c |
| OCaml | `boot/` 固定字节码种子，改编译器后须按 BOOTSTRAP 流程两次自举并提交新 boot 文件 | 种子晋级是显式提交并有固定点验证（对应 §3.3 的资格 receipt 前置） | https://github.com/ocaml/ocaml/blob/trunk/BOOTSTRAP.adoc ；https://github.com/ocaml/ocaml/blob/trunk/HACKING.adoc ；https://arxiv.org/abs/2202.09231 |
| GHC | make 到 Hadrian 的迁移并行保留旧链再切换 | 旧链并行保留、再切换（对应 R7 保留 JAR 链） | https://ghc.gitlab.haskell.org/homepage/blog/20220805-make-to-hadrian.html |
| Reproducible Builds | 可复现构建的定义与环境范围；Wheeler 的 DDC | metadata 无时间戳以保证同输入同字节；**不宣称完整 DDC**（R12） | https://reproducible-builds.org/docs/definition/ ；https://reproducible-builds.org/docs/perimeter/ ；https://dwheeler.com/trusting-trust/ |
| GitHub | 发布资产的 REST 接口与不可变发布功能 | §2.5 的后备与开放问题 1 需要核对资产状态字段与不可变发布能力 | https://docs.github.com/en/rest/releases/assets ；https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/immutable-releases （两条可达，**功能细节未核**） |

## 8. 不做的（理由）

- **不修改 K5 原型的目录当作生产。** 原型输出只写调用者新目录、含占位 API 报告与 `prototype_only` 标记，
  生产要的是另一套行为（真实上传、真实 lock）；P1 已升格生产模块；补裁一要求 P4 合并时删除原型、不留兼容，删除后的输入仍须资格（§13.7）。
- **不为 schema 1 或 v0.104.0 缺 metadata 保留兼容分支**（R2、R8）：历史事实在 lock 的 `registration` 里如实写明，
  代码里不再多一条路径。
- **不让工作流删除或替换任何已存在的资产。** 删除是「事故处理」，由人做并留记录；自动路径里一旦允许删，
  就等于把 `--clobber` 换了个名字。
- **不把 ELF 伪装成 `dawn-selfhost.jar`，不让 `DAWN_SEED` 兼指 ELF**：两种制品的信任来源、验证方式与消费者都不同（R6、R8）。
- **不设忽略摘要的常驻开关**（R11）：调试用覆盖变量存在，但进 stamp 的 override 帧，且 release 禁用。
- **不删 JAR 链**（R7）：它是 reference、对照与历史重放，删链另案。
- **不把重链塞进 push 路径或 `prev-diff-native`（claim 900 秒）**（R10）：它有独立职责与预算；重链只在最终 sha 与晋级时跑。
- **不为凑 (a)(b) 而放宽或重解释门槛**：D 的 pole 红灯归 CI 刀 5，不属 native seed 观测，但不因此改它的声明；
  数据不足就等数据，不先改声明使观测转绿。
- **不在 P 内做 D12-3**：它依赖 P 的 builder 合同，P4 之后另起设计。
- **不做 wasm 种子、macOS/Windows/aarch64、完整 DDC**（R12）。
- **不发布 A**：A 在 release job 内产生并只以摘要进入 metadata，不作为资产（K5 原型同口径）；
  installer 因此不声称独立证明 bootstrap 来源。
- **不新增 nightly 替代必过门**：重链频率在 P5 依数据再裁。

## 9. P0 开放问题原记录（已由补裁一裁定）

以下保留决策来由，答案见 §10，实测与实现见 §11、§12；不再是当前未决项。

1. **撤 `--clobber` 的收敛前提是否成立。** 需要 P1 实测两件事：失败的上传是否会在 release 里留下可见的半资产
   （`gh`/REST 接口的行为未核）；同一 tag 在不同托管 runner 上重建的 B、JAR、metadata 是否同字节（K5 只证了同
   一资格流程内两 root 一致）。任一不成立，退为草稿 release 后备，须另裁（§2.7）。
2. **release job 是否要带完整资格。** 本页设计为：release job 内只做 S→A→B→C 与 `cmp`，资格 receipt 来自 lock
   引用的种子资格；每次晋级才跑 `seed-promotion` 全套。若要求每个 release 都带全套资格，成本落在 tag 路径而非 push，
   但耗时需实测，未估。
3. **门槛 (b) 的最小 push 样本数。** 「7 天」没有给出最少 push 数，本页只规定「零 push 不算满」。需要裁定一个数，
   或明确以「窗口内每个 push 都有结论」为准。
4. **lock 与历史的落点。** 本页放在 `scripts/` 下的三个路径；若希望并入现有 `scripts/seed-*.txt` 的目录布局，
   或让 `dawn.toml` 一类文件承载，需要裁定。
5. **启动器选择量的形式。** 环境变量、命令行标志、还是 lock 内字段；以及 P4 切默认后 JAR 链的显式入口名。
   不得出现两条链间的自动回退。
6. **release 墙钟。** P4 起 release 内新增一条 native 链并保留 JAR 链并行。是否并行、是否拆 job、timeout 是否上调，
   目前没有实测，P1 在演练 tag 上测。
7. **README 对外文案。** 第 9 件是否在 README 下载块之外只作「报告资产」列出（本页如此设计），README 英文须先改，
   中文译本随后同步。
8. **JAR reference 的 `jdk_equivalence_sha256`** 在生产里由谁产生：资格包（重链）或 release job 内双 JDK 比对
   （现行 `build-release-jar.sh` 在 release 内已比对 JDK21/26 候选，见 bootstrap-guards 对 `cmp "$JDK21_JAR" "$JDK26_JAR"` 的守卫）。
   本页倾向后者，待裁。

## 10. 补裁一（2026-11-25）：§9 开放问题的裁定

依据：本页 PR #992 与 P0 报告；外部实例（Rust stage0 由单一清单文件决定、Go 以显式最低版本政策推进）都是
「单一真相加无隐式回退」。裁定逐条如下，§2 至 §6 中与之冲突的措辞以本节为准。

1. **撤 `--clobber` 的两个前提先测。** P1 第一步在一次性演练 tag（`rehearsal-*` 前缀，prerelease，验完即删
   release 与 tag）上实测：失败上传是否留半个资产；同 tag 在不同托管 runner 上重建 B、JAR、metadata 是否逐字节同。
   任一不成立：停，回交，不自行改走草稿 release 后备。
2. **release job 只做 S→A→B→C 与 `cmp`**，完整资格只在晋级时跑（`seed-promotion`）。资格属于种子而非每次发布，
   每发一次重跑资格是重复付费。
3. **门槛 (b) 的样本量**：至少 7 个日历日且至少 10 次成功的 main push 运行经过 native 种子路径；
   零 push 的日子不计入天数，也不阻断。
4. **lock、history、revoked 落在 `scripts/` 下**，与 `seed-release.txt` 同层（§3.1 的路径不变）。
5. **链的选择只有一个真相**：lock 文件里的字段决定默认链；显式覆盖用一个环境变量（如 `DAWN_SEED_CHAIN=jar|native`，
   与既有 `DAWN_SEED` 同族）；两链之间不自动回退，错链即报错。
6. **P4 起 release 内 native 链的并行与 timeout**：P1 演练实测后按 3 倍实测定，写入 Gate-Budget。
7. **`proof.qualification_sha256`** 取 lock 引用的种子资格 receipt（与第 2 条一致）。
8. **`jdk_equivalence_sha256`** 由 release 内既有 JDK21/26 比对产生。
9. **P0 的隔离 schema 2 原型** 按补裁五第 4 条前移至 pre3 删除，不留兼容。
10. 本页状态由 P1 写者在第一个提交里写回以上裁定并改为 accepted（本节即是）。

## 11. P1 实测与落地记录（2026-11-25）

### 11.1 两个前提的实测（补裁一第 1 条）

在一次性演练 tag（`rehearsal-p1-*`，prerelease，验完已删 release 与远端 tag）上用托管 runner 与本机各测一遍：

| 前提 | 做法 | 结果 |
|---|---|---|
| (a) 失败上传留半个资产 | 托管 runner 上对 400 MB 文件 `gh release upload` 分别 KILL、TERM 中断；本机对 150 MB 文件 KILL 中断，另用 `curl` 限速 5 MB/s 直传 REST 上传端点后 KILL；每次轮询资产列表 30 s | 四次都没有截断资产，`state` 恒为 `uploaded`。托管 runner 的两次中断后 5 s 内列表为空，随后该资产以**完整大小**出现（客户端被杀时请求体已发完，服务端异步落盘）；本机两次 30 s 内始终为空。同名重传（不带覆盖标志）报 `asset under the same name already exists`，rc 1 |
| (b) 同 tag 不同 runner 逐字节同 | 同一提交的 JAR 链（JDK 21）与 release-native 在两台并发 runner 上各建一次；native 链 S→A→B→C 在 6 台 runner 上建（含不同提交的演练 tag） | JAR、B（JAR 链产物）、sidecar、旧 metadata、installer 两台完全一致；native 链 A、B 与 chain 收据摘要在所有 runner 上一致，且跨不同提交保持（`selfhost` 源未变则 B 的 sha256 不变，`13542f15...`） |

两个前提都成立，不退草稿 release 后备。唯一的修正：中断的上传可能**稍后**以完整字节出现，所以 publisher 在上传失败后重看列表，出现则按「已存在」比对，不出现才报错（§2.5.4 的「某件上传中途」一行据此成立，不会遇到截断资产，E2 只会来自真实的字节不同）。

### 11.2 release 内 native 链的墙钟（补裁一第 6 条）

演练里 release 工作流的真实形态（S→A→B→C 与 JAR 链并行，release job 在两者之后）：

| job | 观测（秒） |
|---|---|
| native-chain（独立 job，含 checkout、取种子、链、传 artifact） | 170（最小）、225（最大），共 6 次成功 |
| 链本体（emit 加 cc，三阶段合计） | 169 至 212 |
| release JAR（JDK 21 与 26 各一） | 60 至 75 |
| release（比较 JAR、API 快照、产出九件、发布） | 54 至 66（含 R1、R2 重跑） |
| 全工作流墙钟 | 约 4 分 |

native 链与 JAR 链并行时，关键路径是 native 链，不增加整体墙钟的量级。按 3 倍实测定：native-chain job `timeout-minutes: 12`（3 倍 225 秒，取整分），预算注释 `3x 225s worst observed`。release job 原预算 `3x 137s` 不变（它不再编译 native，只做比较与发布，实测更短）。tag 触发的 release 不入 push 总量，所以没有 Gate-Budget 变化。

### 11.3 落地与分期说明

以下记录 P1 当时的过渡状态；补裁二冻结发版，P2 已拒绝 null 资格且当前缺真实 lock，见 §12.4。

- P1 合并后下一个 tag 即发九件、schema 2。**种子仍是 `scripts/native-seed-candidate-v0.104.0.json`（候选 lock）**：P2 的 qualified lock 不在 P1 内，所以 `native-bootstrap.json` 的 `qualification_sha256` 此时为 `null`（取自候选 lock 的 `lineage.qualification_sha256`），P2 之后由 lock 的资格 receipt 填入，并在 P2 起拒绝 `null`。这是设计 §2.3.1 第 2 点在 P2 之前的如实状态，不是兼容分支。
- `release-native.sh` 仍在每次 push 上跑，但它构建的 B 来自 JAR 链，只用于 native-cli-diff 与协议契约包；release 不再用它的产物。它不再写 `dawn-toolchain.json` 与 `install-native.py`。
- 「全仓 0 命中」的 grep 对 `.github/` 与 `scripts/` 成立；本设计页与 PR 文字里的历史引用保留（它们描述被撤掉的行为）。

## 12. P2 落地记录（2026-11-25）

P2 只做机制，不改默认链，也不创建真实的 `scripts/native-seed-lock.json`：它需要一份对该种子的有效资格 receipt，而资格属于 P3（§3.1）。所以这一刀合并后仓里**没有 lock**，默认链是 JAR 链（与今天一致），release 因「找不到 qualified lock」而拒绝（补裁二第 1 条的发版冻结至此改由机器强制，而不是靠约定）。P3 在冻结输入上资格通过后，用 `advance-native-seed.py initial` 把候选转成第一条 lock。

### 12.1 记录与读取

- `scripts/native_seed/lockchain.py` 是唯一的读与写：`load` 严格读 lock、历史目录、撤销名单并验证整条哈希链；晋级、回滚、改链、初始化全部先把「当前链加提议的新 lock」交给同一个 `verify_chain` 再落盘。读者与写者用同一份规则，所以写者不会写出读者不认的东西，反之亦然。
- qualified lock 的字段：`chain`（`jar`|`native`，默认链的唯一真相，初始为 `jar`）；`lineage` 扩为 `parent_lock_sha256 parent_receipt_sha256 qualification_sha256 transition rolled_back_from rolled_back_to reason`。`rolled_back_to` 是为了让两条回滚路径可区分（§3.5 的推翻判据）：被放弃的序号与被恢复的序号都显式写出。
- 历史：`native-seed-history/<序号>.json` 是旧 lock 的原字节，0 号是候选原字节；新 lock 的 `parent_lock_sha256` 是上一条原字节的摘要，所以改任何一份历史、或删一份，链就断。lock 必须是规范形式（键序、空白），重排版本身就是改动。
- 单调：晋级的 tag 必须大于**历史上出现过的所有种子**（不只是当前），所以回滚后不能再晋级被放弃的版本；也不能复用旧种子摘要。
- 撤销名单：每行 `<种子 sha256> <原因关键字>`，按摘要排序、无重复。**load 时检查**：当前种子被撤销则整条链失败关闭（不改走别的种子）；晋级与回滚的目标被撤销同样拒绝。补救是回滚到未被撤销的历史种子。
- 中断：晋级先写历史、最后换 lock。历史已写、lock 未换时恢复是幂等的（多出的那一条必须恰好等于当前 lock 的字节）；lock 已换而历史缺失在顺序下不会发生，出现即判污染。三个切点（历史写前、历史写后、lock 换后）重跑得到与不中断逐字节相同的终态。
- 只增不改的另一半：`native-seed-chain.py check --base REV` 比较 REV 处的记录：REV 的 lock 必须仍在链里且逐字节相同，REV 的撤销行不得被删改。这是为了抓「原地改最新一条 lock」——那种改动在链内看不出来，因为还没有后继指向它。本刀没有把它接进 CI（接入点与基线选择见开放问题）。

### 12.2 启动器

`bin/dawn` 在 source seedjar.sh 之后、做任何重活之前决定链：

1. `DAWN_SEED_CHAIN` 只能是 `jar` 或 `native`（空串也拒绝）。
2. scripts/ 下 lock、历史、撤销名单**任一存在**就必须经 `native-seed-chain.py default` 验证，不通过一律失败（不分链）；全不存在默认 `jar`。
3. 实际链 = `DAWN_SEED_CHAIN` 或 lock 的 `chain`。JAR 链上设 `DAWN_NATIVE_SEED` 报错，`DAWN_SEED` 指向 ELF 报错；native 链上设 `DAWN_SEED` 报错。两个变量同设因此在任何链上都报错。
4. native 链：`native-seed-chain.py seed` 取 `.dawn/native-seeds/<tag>/dawnc-linux-x86_64`，缺则从 tag 的 release 下载，**每次使用都重算** sha256、size、ELF 形状、`--version` 与完整 build id，全部等于 lock 才用；缓存被改是错误，不是重新下载的理由。`DAWN_NATIVE_SEED` 只接受 ELF（jar 拒绝、符号链接拒绝）。验证失败即退出，**不回退 JAR 链**。
5. 验证通过后 native 链仍然退出：用 native 种子构建本启动器管的工具链是 P4 的事（`nmain` 没有 `build` 到 jar），P2 只保证选择、验证与失败行为。

不存在忽略摘要的开关（测试里对三个脚本的环境变量与「unverified/insecure」字样做了 grep 负控）。

### 12.3 晋级

`scripts/advance-native-seed.py`：`initial`、`promote TAG`、`rollback N`、`revoke SHA`、`set-chain jar|native`。`promote` 复核 tag 在 origin 上的 commit（前后两次）、tag 是 HEAD 祖先、版本大于所有历史种子；下载九件并跑 `native_release.aggregate`（与当前 lock 对账，所以基于旧种子建的包会因 `release-lineage` 被拒）；用 `--version` 与 `version -m` 复核 ELF；std/runtime 身份取自 tag commit。资格证据要求 `native-seed-qualify.py` 的 `run` 与独立 `verify` 都完整通过（十三步与两步全 0、receipt 摘要一致、请求原因是 `seed-promotion`、commit 等于 tag commit）；没有就拒绝，不允许先晋级后补。

### 12.4 release 拒绝 null 资格

`native_release.aggregate`（产出端与消费端共用）拒绝 `proof.qualification_sha256 = null`；`produce`、`chain`、`aggregate --lock` 只接受经 `lockchain.release_lock` 验证的 qualified lock（候选、缺失、断链、被撤销种子都在这里被拒）。release.yml 的 native-chain job 在取种子之前先跑 `native-seed-chain.py check`，并断言三个种子变量未设置；`release-native.sh` 每次 push 跑的协议契约包改用 `contract-fixture` 生成的 qualified 夹具 lock（资格摘要只是标签，不是证据）。

### 12.5 不做

- 不创建真实 lock、不切默认链（P3、P4）。
- 不改 `advance-seed.sh` 与 JAR 三文件协议（`git diff` 为空）。
- 不在 P2 让 native 链真的构建工具链（见 12.2 第 5 点）。

## 13. P4 native 链与启动器合同（补裁四，2026-11-25）

本节采纳方案丙：**源码检出执行 S→A→B，缓存并 exec 当前 B；C 只在 release 与资格中验证固定点。**
直接执行旧 S 会使当前源码不可见，破坏 site 与 HEAD 对拍；执行 A 会使日常工具链与发布 B 的 std/runtime 配对不同。
两者均不作为源码启动器方案。本节来自 P4-pre0 合同；pre1 的独立 builder 已实现（§14），pre2 的启动器缓存见 §15；§12.2 保留 P2 当时行为。

### 13.1 S/A/B/C 角色与证据边界

| 角色 | native 链 | JAR 链 | 职责与最终去向 |
|---|---|---|---|
| S / stage0 | 已资格 ELF 与该 seed commit 配对的 std/runtime | 已锁 JAR 与配对 std，含续传 vendor | 信任根与特性上限；不是源码检出的最终工具链 |
| A / stage1 | S 编 portable 当前 `nmain` closure；发射 std、链接 runtime 均取 seed commit | S 编当前 selfhost closure，配 seed std | 过渡 builder；内嵌 stdsrc/rtsrc 来自当前快照，不因此变成 B；不公开发布 |
| B / stage2 | A 编同份当前源码，使用 current std/runtime | A 编同份当前源码，使用 current std、续传 vendor | 源码日常工具链与 release 发布对象；native 为 ELF，JAR 为独立 JVM 产品 |
| C / stage3 | B 再编同份当前源码与 current std/runtime | B 再编同份当前源码 | release/资格要求 B==C；不在每次源码缓存失效时强制构建 |

`release-native.sh` 的局部 candidate-a/b 是同份 C 的两次独立链接，与本表 A/B 角色无关。
公开资产仍为 §2.2 的九件：B ELF 及 sidecar、JAR reference 及 sidecar、metadata、installer、三件 report；
A/C、C 中间文件与完整 chain receipt 不新增为公开资产。installer 只验证取得的 B，不声称独立重证 S→A→B→C。

三类 receipt 各有边界：

| 证据 | 证明什么 | 消费与保留要求 |
|---|---|---|
| 种子 qualification receipt | 某一 ELF 与配对树可作 S；initial-seed / seed-promotion，另有 final-inputs 最终树证据 | run 加独立 verify；lock 引用种子资格摘要，不能拿旧 S 的资格冒充 B 的种子资格 |
| 完整 native chain receipt | 本次 S→A→B→C 的逐阶段 whole/info/units/ELF 摘要、来源与实际工具链/recipe 身份 | pre1 跨 job 传递并由 producer 复验；规范摘要进入 `native-bootstrap.json.cold_sha256`；内部 schema 1 与发布 schema 2 不是兼容分支 |
| launcher generation receipt | 当前源码、配对 seed、工具链及 B 字节属于同一缓存代 | pre2 持久化并每次消费复验；不是资格 receipt，也不替代 release 固定点 |

P1 当时的交接 artifact 仅 A/B/cold.sha256，producer 仅接收摘要，组装 runner 探测的 CC 不代表链执行方。
pre1 已改为传递完整 receipt、producer 复验并保留 90 天，见 §14。

### 13.2 三种运行模式、选链与最终 exec

| 模式 | 链选择 | 构建或取用 | 最终 exec 与依赖 |
|---|---|---|---|
| 源码检出 `bin/dawn` | lock 的 `chain` 为默认唯一真相；`DAWN_SEED_CHAIN` 显式选 `jar` 或 `native`；无任何记录时 jar | native 构建/复验 S→A→B generation；jar 复用现有两阶段 JAR generation | native exec 当前 B ELF；jar exec Java 加当前 `build/dawn-selfhost.jar`；源码启动器可要求 Python 3.11+（`tomllib`） |
| 无源码部署的 shell `bin/dawn`（复制 bin/ 与 build/） | 声明为 JVM-only，部署调用者显式设 `DAWN_SEED_CHAIN=jar`；缺失/空值/未知值或请求 native 均报错，种子覆盖也拒绝 | 只用随部署复制且身份已核的 JAR；不下载 seed、不自举、不读另一份默认链配置 | exec Java 加随部署 JAR；需 JDK 21，启动不依赖 Python；不得因缺 ELF 静默走 JVM |
| installer 原生发行安装 | 安装命令本身显式选择 native 产品；安装结果是 B ELF，不是源码 selector | 校验下载的 B、sidecar、metadata，原子安装为 `bin/dawn`；不执行 A/JAR/自举 | 直接运行发布 B；不再构建当前源码，不需要 JVM 或 Python 参与日常启动 |

无源码部署的模式判定和显式选择检查须在 Python/lock reader 之前；现有早期分支直接执行 JAR 的行为由 pre2 修正，
不能静默忽略 `DAWN_SEED_CHAIN=native`。`install-native.py` 安装步骤本身仍用 Python，
不得把源码模式的 Python 3.11+ 最低要求扩散到无源码启动；installer 的 Python 3.10 可用性须在后续实施验收中核实。
原生发行 ELF 不提供隐式 JVM dispatch；需要 JVM 产品时单独运行同 tag 的 `java -jar dawn-selfhost.jar`。

源码链选择必须先于 Java 探测或执行。任一 lock/history/revoked 记录存在就验证整链，显式 jar 也不能绕过损坏或撤销记录。
空/未知选择、错误 seed 类型、两个 seed 覆盖变量同设、native 链设 `DAWN_SEED`、jar 链设 `DAWN_NATIVE_SEED` 均拒绝。
种子缺失、摘要/版本/build id 不符、平台不支持、CC 缺失或构建失败都报错，**两链绝不自动回退**。

### 13.3 显式 JAR、配对覆盖与环境

- JVM 后端、build-to-jar、`use java`、Java deps、`--cp`/`--vendor`、JVM 依赖 lock 和需要 Java 类型解析的 LSP，
  必须在启动器边界使用 `DAWN_SEED_CHAIN=jar bin/dawn <cmd>`；native 明确拒绝并提示此入口。
  不按 import、子命令或 `--target jvm` 自动换链；LSP 不能在会话中途换 server。纯 Dawn LSP 仍可使用 native。
- native `build` 的产品是 ELF，`run/test` 使用 C 工具链；JAR 链的相应产品与执行仍属 JVM。
  release 保留 JAR reference，源码模式本机只有显式选 jar 才为它准备缓存；native 首次启动不顺带构建备用 JAR。
- `DAWN_NATIVE_SEED` 必须同时声明与 ELF 配对的 **seed commit、std 树与 runtime 树的路径及内容身份**，
  并核对 ELF 摘要、大小、版本、完整 build id。不能从任意 ELF 猜配对树，不能拿 HEAD std/runtime 凑 A。
  任意本地种子调试也须完整配对输入，进入独立 override stamp，与默认 qualified S 的缓存隔离；
  不因此宣称该 ELF 已资格。release 禁用全部种子覆盖。配对输入的具体参数/记录接口由 pre1/pre2 定稿并测试，
  不能仅凭 P2 的常规 ELF 文件检查开始构建。
- native 链首版要求 **Linux x86_64 与 C 工具链**，包含静态链接所需头文件、库、链接器与辅助工具；缺失即报错。
  共用 `cc-units.sh --static --inline-rc --runtime ...` 阶段原语，记录实际 CC 字节/版本/target、链接器与库闭包、recipe 身份。
  当前资格配方为 Ubuntu clang 18.1.3/GCC 13 布局；是否扩展其它本机 CC 须明确开发 generation 政策，不能沿用旧资格背书。
  自举清理未声明的 CFLAGS、include、优化等环境，用户程序的 CC 选项不能悄悄改变自举配方。
- 源码物化复用 `native-source-tree.py` / `contract.portable` 与现有 Planner，入口是
  `selfhost/src/nmain.dawn` 的 portable closure，保留 local deps、移除 Java deps；不能直接 native build 原 `selfhost/`
  （目录默认入口是 JVM main），也不再写一套 shell/Python 源码依赖解析器。
  S 与配对树可在准备阶段下载且必须验证；构建阶段不得隐式联网，离线缺对象就失败。

### 13.4 generation 缓存与失效

native B 与 JAR 的 cache 名称、格式、stamp 必须分离。pre2 提供“已验证 B 路径加 generation receipt”的消费边界，
具体路径与查询接口在该刀登记；site 后续迁移不得自己猜缓存路径或重建第三份 compiler。

generation 身份至少绑定：chain 与 stage=B、default/override 帧、有效 lock/历史/撤销身份、S 字节与完整 build id、
seed commit 配对 std/runtime、portable 转换及 `nmain`/Planner/local dependency closure、current std/runtime/embed、
阶段原语与 recipe、实际 CC/链接工具/库闭包，以及输出 B 的摘要和完整 build id。
native `__source-inputs` 是源码清单的权威 producer；旧 S 不必认识新协议，首次清单来自其构建出的 A，最终 B 再复验。

构建前后重新核对输入与 plan；源码、传递依赖、std、runtime、embed、物化器、recipe、seed 配对树、工具链任一变化必须失效，
包括 dirty 源码修改。mtime、VERSION 或 Git HEAD 单独都不足以命中。每次热命中仍验有效 lock/撤销、输入和 B 字节；
被改的 seed/B/receipt 是污染错误，不能通过重下 seed 或执行旧代掩盖。

同一 generation 用构建锁串行化，等待者重新核验；在私有 staging 构建 A/B，成功后原子提交，commit-marker 最后写。
失败保留旧 generation 的字节，但本次命令必须失败，不能执行与当前输入不符的旧 B；中断/并发不得执行半成品。
`DAWN_PRINT_STAMP=1` 返回带 native 类型的 generation 身份，不冒充 JAR stamp。
保持 argv、cwd、信号、退出码与 stdout/stderr 合同，构建日志只写 stderr。

### 13.5 耗时、证据与预算

补裁四接受冷启动约两分钟，但这是**推断**：P1 每阶段 emit 15–18 s、cc 45–52 s（实测），
两阶段约 120–140 s，另加取种子/配对树和准备校验时间；不是本机实测或用户机器时限。
P1 三阶段 native-chain job 实测 170–225 s，双 JDK JAR 各 60–75 s，完整 release 约四分钟（§11.2）。
热启动的完整输入/ELF/工具链校验尚未计时，不能用 P2 约 0.1 s 的 Python 验 lock 成本冒充；pre2 必须实测入报告。

release 继续 native 与双 JDK JAR 并行，墙钟按 `max(Tnative,Tjar21,Tjar26)+Taggregate` 加调度/evidence 算，
不把 job-seconds 相加称墙钟。native timeout 12 分钟源于 3×225 s，输入变化后复测。
push 中 N 个 job 冷建 B 可能新增约 N×两阶段时间的 W，pre3 须逐入口核算。
任何前置刀新增 W 都须 Gate-Budget 声明，改 gates.yml 须 `steps_lock.py record`；
P3 接 `check --base` 时同时补 P2 已确认约 +8.5 s 的实际增量，不悬空到 P5。
完整双 root/C/资格不塞进每次启动或每次 push，轻夹具与真实重链的账分开。

### 13.6 P4-pre3 必须逐个钉链的消费者清单

下表保留 pre0 按 `33ee0a6b` 登记的迁移责任；pre3 实施后的逐文件、逐选择行清单见 §16。间接调用须沿脚本、composite action、子进程和编辑器环境追踪，
逐个记录“所需能力、chain、最终 exec、身份/缓存、验证证据”。不能在整个 workflow 全局设 jar，也不能让 JVM oracle 两边变成同一 native 工具。

| 入口 | 必须显式选择及最终消费 | pre3 验收 |
|---|---|---|
| `site/dawnc.sh` 的 `site_dawnc_stamp`、`site_dawnc` | `DAWN_PRINT_STAMP` 与 `__emitc` 引导固定 jar；其产出的同树 native 工具仍直接执行 ELF | stamp 与 emit 同链；同树生成器对拍；不以下载旧 S 替代当前编译器 |
| `site/inputs.py prepare` 的两个 `bootstrap_plan` 与调用 `site_dawnc` 的子进程 | 引导 SourcePlan 与工具构建显式 jar；已制备 native SourcePlan/工具按既有 receipt 直接运行 | bootstrap/native plan 一致，tool/data 收据不串链；D12-3 再迁 prepare |
| `playground/deploy/redeploy.sh` 工具链构建、`PLAY_TOOLCHAIN_ID`、JAR/bin 复制 | `--version`、JAR 生成及版本解析显式 jar；无源码 shell 启动环境显式 jar；native compiler/runner 分别执行同 tag 已验证 B/runner ELF | 离线 deployment preflight 核 JAR 存在且新鲜、JAR/B/runner 各自完整身份；不用同一个 sed 解释两种版本串 |
| `scripts/release-native.sh` 默认 `DAWN_JVM`、`version -m` 与协议包 JAR reference | 默认启动器调用显式 jar；`--jar` 仍直接执行指定 JAR；产出 ELF 用于 push 对拍/夹具，不当正式 native-chain B | JVM 发射与 native ELF 比 C；局部双链接检查保留，夹具不冒充资格 |
| gates 的 `.github/actions/dawn-toolchain/action.yml` 准备调用及其调用者 | 依赖 JAR 的准备显式 jar；native 覆盖的准备显式 native，不能由 action 隐式替所有 job 猜链 | `build=false` 的 oracle 自建路径也核；缓存类型和实际冷建成本入账 |
| gates `test-compiler` 的 `test compiler-plan`、`test selfhost`、`selfhost-fixpoint.sh`，以及 grammar/comptime/JVM 元数据子脚本 | 原 JVM 测试与固定点显式 jar，最终当前 JAR；native selfhost 测试另有入口 | ASM/Java 依赖仍走 JVM，保留独立 native 覆盖；fmt 步骤按自身能力另行登记 |
| gates `contracts-6` 的 `__emit selfhost` 与 `asm-adapter-contract/run.sh` | 显式 jar，最终 JVM class 输出 | adapter oracle 及 class 常量池检查不被 native emit 替代 |
| gates `java-target-classpath` 的 `lock --check selfhost`、`java-target-classpath-contract/run.sh`、bootstrap guards/input-manifest harness | JVM 能力显式 jar；selector/拒绝夹具各自显式测试 jar/native | 不能由外层 jar 环境屏蔽 native selector 负控，假 java 零调用断言保留 |
| gates `lsp-workspace`、`lsp-workspace-2`、`lsp-references`、`lsp-references-2` 及 incremental LSP 脚本 | 原 JVM oracle/Java 解析样本显式 jar；纯 Dawn native LSP 覆盖显式 native | 每个 server 子进程选链可见，native 性能独立计时，不套用 JVM 旧数据 |
| gates `wasm-target` 的 `__emitc nmain`、`native-selfhost-tests` 的 `--version`/`__emitc` | 现有 JVM 引导显式 jar，生成的 wasm/native 工具分别直接运行 | 原引导 oracle 保留，新增 native 启动覆盖单独声明 |
| gates `docs` 的 `doc-check.py`、`test site`，`test-programs` 的 stdlib/package 测试 | 当前检查含 build-to-jar/Java 依赖的入口显式 jar；纯 Dawn 可迁 native 的步骤逐项登记 | checked blocks 的目标/产物类型不被默认变化偷换 |
| gates `site` 的 cache-keys/prepare/build，以及 `scripts/site-dist-diff.sh` | prepare/stamp 与对拍 JVM leg 显式 jar；已准备的 site native leg 直接 ELF | 同树、同 tag 可比 C/wasm/site 文件集逐字节一致，receipt 身份各自核 |
| gates `prev-diff` 的 selfhost prev/run/fmt/lsp/param 差分（含 range 重跑） | HEAD JVM leg 显式 jar，上一 release JAR leg 保留 | N/N−1 与重跑范围语义不变 |
| gates `prev-diff-native`、`prev-diff-native-2` 的 release-native、native-cli-diff 与 native-fixpoint 下游 | 发射/manifest/stamp/JVM oracle 显式 jar；被测 native ELF 直接执行；新源码启动覆盖显式 native | 两侧来源分离，`__emitc`、JAR build、Java probe、LSP 子进程均逐项钉链 |
| 编辑器需要 Java 类型解析的 LSP 启动环境 | 显式 `DAWN_SEED_CHAIN=jar`，最终 JVM LSP | 纯 Dawn native LSP 入口仍可独立使用 |

pre3 的完成证据须包含扩展后的全量调用表及未迁入口为零的核对；本表不能作为省略间接消费者的理由。
部署仍按 tag，先 Playground 后 site，并保留 `DAWN_WASM_CC`；pre3 做离线预检，不执行生产部署。

### 13.7 刀序、验收与停止判据

每刀一 PR；pre0/pre1/pre2/pre3 全部保持默认 jar。S3/S4 与全部前置实现完成，再冻结 P3 输入，P3 放行后才有真正 P4。

| 刀 | 内容与验收 | 停止判据 |
|---|---|---|
| P4-pre0 合同 | 本节与 bootstrap 同步；三模式 chain/exec 唯一，九件角色/三类 receipt/阶段表一致；doc-check 0 unknown、mutation-anchor-preflight 与 anchor-guard 通过 | 若要求 native 无 JVM 产 JAR，范围改变，回交另案；不以临时 fallback 顶替 |
| P4-pre1 builder 与 receipt | 共用 S→A→B 原语，release 追加 C；准备 seed 配对树与 portable capture；完整 receipt 跨 job 验来源/实际 CC。错 seed/std/runtime/CC、缺 stage、换 A/B/receipt 的负控先红；真实无 Java 候选 B 与同输入 release 路径一致，不复制 C flag 表 | A 起不来、B/C 不等、来源身份不符即停；旧 S 不兼容回交桥接发布，不改用 JAR |
| P4-pre2 启动器 | 两阶段 generation、输入/ELF/toolchain stamp、锁和原子提交；默认 jar，显式 native 可用；三模式行为与 Python 边界明确。验 argv/cwd/退出码、热命中零编译、逐类输入失效、中断/并发/污染拒绝，native Java exec=0；报告冷/热实测 | 自动回退、直接执行旧 S、跨链缓存混用、dirty 源未失效或 native 需要 JVM，任一拒绝合并 |
| P4-pre3 消费者 | §13.6 逐入口钉链并扩展间接调用；双链同树对拍、部署离线预检；README 英文先改与译本同步；原型引用迁移与删除输入安排；所有应执行 gates/ci/tile completed/success，steps_lock/Gate-Budget 完整 | site/Playground 仍猜 JAR、oracle 同源、暗增 N 次冷建或预算无来源，不切默认 |
| P3 机制修补与最终资格 | 先让 qualify 接 `--lock` 并验证实际种子绑定；`check --base` 接 CI 并补 P2 预算；机制可在前置期间单独 PR，但 gates.yml 写者串行。最终冻结后 initial/真实 lock、三组配对、B 自身种子资格与独立 verify、五项演练、七日观测全部齐备 | 输入在变则顺延；任一配对失败或 native seed 归因失败，P4 停并回交；失败样本不得删除再凑 3/3 |
| P4 默认与首个 schema 2 发布 | P3 放行；合法 set-chain 历史、精确 tag commit 证据和完整门禁；v0.107.0 九件封存。冷下载聚合核 B/full build id/commit/lock/proof，无 Java 安装 hello，同 tag 重跑只验证；源码默认执行当前 B，显式 jar 可用 | 资格/观测失格、E2、聚合不符或部署可比产物不符，停并回交；不改已发布资产，错版新 tag |
| P4 后晋级 | 发布 B 与 P3 候选 B、tag commit、配对树完全相同才复用 B 的 seed-promotion receipt，否则重跑资格与独立 verify；advance-native-seed promote，JAR 原协议另推进；新 S 能编当前源且回滚演练可用 | receipt 对象是旧 S 或错 tag 即拒绝；不得以“旧 S 造出 B”替代“B 可作 S” |

最终冻结顺序：S3/S4、全部 P4-pre、P3 机制修补与 0.107.0 版本准备收完 → initial-seed 资格并生成真实 lock（仍 jar）
→ 对实际 lock/commit/tree 重新冻结 → P3 最终输入资格、三组配对、拟晋级 B 的种子资格及独立 verify、演练、七日观测
→ 满足门槛才切默认并发布 → 冷下载对账与晋级 → P5 长期预算收口；D12-3 另起设计。

`initial`、`set-chain`、VERSION、原型删除、merge/rebase 都可能改变当前协议绑定的 commit/tree。
补裁五已把 P0 隔离 schema 2 原型的引用迁移与删除前移到 pre3；
实际发布候选的删除后输入须重核/重跑资格与三组配对。
最终 merge 或 set-chain 后须重核实际编译输入；编译输入不同就重跑资格，控制记录不同则独立复验，不能手改 receipt。
补裁五要求 pre1 实现编译输入与控制记录分离，具体可验证边界见 §14；不再把控制记录写入编译输入摘要。

绑定不得递归：initial receipt 资格 S，再由真实 lock 引用；final-inputs receipt 资格实际最终树，作为外部证据，
不反写正在资格的 lock。B 先有描述 ELF/配对树的待晋级输入 lock，再取得 seed-promotion receipt，
随后正式 lock 引用该摘要；不能要求 receipt 的输入 lock hash 等于含该 receipt 摘要的未来 lock hash。
P3 的 `--lock` 与晋级消费者必须把这条非循环关系落实为可验证规则。

三组配对是同一最终冻结输入的两次完整重链为一组、共三组；P1 六个 runner 成功不等于 P3 3/3。
七日按补裁一为至少七个有样本日、至少十次成功 main push 经过 native 路径、归因失败零。
默认 jar 时可通过显式 native 固定路径观测，但须覆盖最终 selector/lock/失败语义与准备成本；
默认切换若改变 job/steps/实际成本，须先消除差异或重新起窗。K5/P1 旧证据不替代最终 P3。
D 的 pole 红灯仍归 CI 刀 5，不属本项观测；不降低 native 归因审计标准。

### 13.8 尚须定稿的实施边界

补裁四已裁定 B 语义、显式 JAR、完整配对覆盖、环境/Python 边界与刀序。
补裁五明确了开发工具链隔离、非循环绑定、内部 artifact 留存 90 天与 pre3 删除原型；
pre1 定稿 builder 与 qualification 接口，pre2 定稿缓存与查询接口。
这些未决项不得解释成默认切换许可。pre1/pre2 必须以可审查接口和负控定稿，P3 必须以实际最终输入证据放行。

## 14. P4-pre1 实施边界（补裁五，2026-11-25）

共用 builder 负责 portable capture、seed commit 的 std/runtime 物化与 S→A→B，release 在同一原语上追加 C。
入口固定 `selfhost/src/nmain.dawn`；保留 Planner 的本地依赖，不另写 Dawn 依赖解析器，也不复制 C flags。
编译输入摘要使用物化源码的内容清单、配对树、转换器、`cc-units.sh` 与实际 CC/链接器/libc 闭包；
lock/history/revoked、候选及待晋级描述记录属于控制层，不参加该摘要。Git commit/tree 另记为来源证据。
资格 receipt 同时绑定这个摘要、实际输入 lock 的摘要与受测种子 ELF 摘要；正式晋级重新核对 seed/std/runtime，
不要求未来含资格摘要的正式 lock 与待晋级输入 lock 同摘要。

完整 chain receipt 必须记录来源、编译输入、工具链和逐阶段 whole/info/units/ELF 身份，producer 读取完整记录，
拒绝缺 stage、换 A/B/receipt、错配对与错 CC，不从组装 runner 重新猜 CC。receipt 的规范摘要进入公开 proof；
内部 artifact 跨 job 传递并保留 90 天，公开资产仍九件。默认链仍 jar，启动器缓存见 §15。

pre1 的具体接口：

- `native-seed-chain.py build --lock <输入> --seed-elf <ELF> --out <新目录>` 构建 A/B；
  `prepare-pair --lock <输入> --out <新目录>` 离线从 seed commit 物化配对树，缺 Git 对象即失败。
  `--seed-tree` 可指向已准备的完整配对树，构建前后均重验；`--live` 物化当前工作树和新源码文件，仍不提供缓存。
- `describe-seed --seed-elf <ELF> --seed-commit <commit> --out <仓外描述文件>` 生成完整 proposed 输入；
  同时给 `--chain-receipt`、`--origin-lock`、`--origin-builder` 才能登记可资格的 pinned 来源，
  否则只登记 `local-development`。pre2 的覆盖接口使用 `DAWN_NATIVE_SEED` 加 `DAWN_NATIVE_SEED_LOCK`，
  后者指向该完整描述；配对路径使用 builder 的 `--seed-tree`，不能只给 ELF。
- 工具链首版支持 clang 与 GCC 13 静态库布局。默认严格要求资格配方的 clang 18.1.3；
  `--development-cc` 允许其它 clang，但 receipt 使用独立 development recipe，release/资格拒绝引用。
  记录 CC 字节、版本、target、resource、linker、头文件与静态库清单，清空继承的编译环境，前后重验实际闭包。
- `native_release.py chain` 调同一 builder 追加 C，比较 whole/info/units/ELF 与 full build id；
  `verify-chain` 在下载后、执行 B 的 API 快照前核对，`produce --chain-receipt` 再核对后组装九件。
  `recipe.inputs_sha256` 是编译输入摘要，toolchain/recipe 字段取链执行方；不再接受裸 cold 摘要。
- `native-seed-qualify.py run|verify --lock <实际输入>` 不再钉死历史候选。proposed ELF 还须带上述三件来源参数，
  本地开发 generation 不能资格。package 同时携带 `compilation`、`compilation_sha256`、`qualified_seed_sha256`，
  并保留实际 `seed_lock_sha256` 作为控制审计。晋级消费者核对受测 ELF、配对内容与当前编译输入，
  控制记录变更不触发重资格，源码/配对/recipe/工具链变化均拒绝复用。

编译源清单采用物化 Git 树中源码项目、std/runtime、scripts、workflows、bin 的保守上界，
包含原型与构建脚本，因此删除原型仍改变编译输入；docs 与根文档不属于编译输入。
排除 `scripts/native-seed-lock.json`、`native-seed-history/`、`native-seed-revoked.txt`、历史 candidate 与 JAR seed 三文件；
额外待晋级描述写在仓外，不引入新的递归记录。原始 commit/tree 与完整输入 receipt 仍保存，
控制层和编译层的验证各自保留，不能把“摘要不变”解释为绕过撤销或来源验证。

补裁六要求资格配方显式选择 GCC 13。`cc-units.sh --qualification` 在编译和链接的共同参数中加入
`--gcc-install-dir=/usr/lib/gcc/x86_64-linux-gnu/13`，该参数只在此脚本定义。
`--print-qualification-flags` 供身份探测读取同一参数；builder、cold、compile-stage 和资格固定点显式使用资格模式。
通用 C 构建继续按调用者的 CC 配方执行，集群 prefix 与开发 CC 的路径不会被资格目录覆盖。
工具链探测记录实际 libgcc、GCC crt、libc crt 与静态 libc 的解析路径，并要求每一项位于捕获目录且在清单中。
失败时只额外打印解析路径；未知目录继续拒绝。新配方下须重测本机 A/B 与 native-fixpoint，
再在新的 prerelease tag 完成 A/B/C、receipt 交接与 producer 验证；托管仍不满足 GCC 13 闭包则停止回报。

补裁六后的 native-chain 演练 job 实测 448 s（[run 45685569422](https://github.com/dawnop/dawn-lang/actions/runs/45685569422)，native job 成功，JDK 26 leg 首次遇 Maven 429）。
原 225 s 基线由此重核：加一成并向上取整到 5 s，planning claim 为 495 s，3 倍后向上取整为 25 min timeout。
这是仅 tag 工作流的边界，push-total 仍为补裁六采纳的 40295 s。最终配置再通过新 prerelease tag 验证。


补裁七将工具链身份分为两层。`recipe_identity` 绑定 clang 字节、版本与 target，driver 实际选中的
GCC/crt/libc 路径与各自摘要，`cc-units.sh` 摘要、阶段选项与资格 flags，以及 GNU ld 版本字符串；
这些字段跨主机必须相同。`toolchain` 则如实保留每次运行的完整字节快照（包括 ld/binutils 库、
头文件集合），不归一化，也不要求跨主机同摘要；编译输入摘要仍绑定这份实际快照。
跨主机等价另以验证过的 B ELF 摘要相同判定；配方相同而 B 不同必须停止，回交容器钉工具链方案。

每份 chain receipt 另记 `execution`。源码 builder 的全部本机 generation 都是 `development` stamp，
即使 clang 与资格配方完全相同也不能被资格或发布引用。release chain 只能在托管 release workflow
生成 `hosted-release` receipt，记录 repository、commit、run/attempt、workflow ref 与 runner 类型。
`verify-chain --current-run` 与 producer 同时核对当前运行来源；同一 run 的失败 job 重跑可引用
较早 attempt 已成功的 native artifact，其它 run 的替换拒绝。下载后的历史 hosted receipt 可离线复验，
但不能由本机重组发布。资格入口同样要求托管环境，request 与 package 绑定执行来源；
晋级拒绝本机开发来源，`describe-seed` 只有经过完整验证的托管 release 来源才登记可资格 proposed ELF。
这些来源字段是审计记录，不作为重新写入编译输入的控制记录。

## 15. P4-pre2 启动器缓存（2026-11-25）

源码入口在选择 native 后、任何 Java 探测之前，交给 `native-seed-chain.py launch -- <argv>`。
它调用 §14 的同一 builder，以 live capture 构建 S→A→B，只执行 B。默认仍为 jar，
不创建或修改 lock/history/revoked，也不构建备用 JAR。无源码 shell 在读取 Python 模块之前
要求 `DAWN_SEED_CHAIN=jar`，并拒绝全部种子覆盖；缺失、空值、未知选择和 native 请求均失败。

缓存位于 `build/native-toolchain/generations/<输入摘要>/`，与 JAR generation 隔离。
`generation.json` 描述 stage B、完整 build id、ELF 摘要、输入及 chain receipt 摘要；
`committed.json` 是最后原子写入的提交标记。`build.lock` 从输入准备到最终复验持有独占 flock，
等待者重新读取所有输入。构建使用私有 `.staging-*`，先同步文件、原子重命名目录，再提交 marker。
中断可能留下私有 staging 或缺 marker 的目录；前者不会被选择，后者报污染错误，须显式清理后重试。
失败保留旧代字节，本次调用失败，不执行旧代。缓存暂不自动回收，避免影响正在执行的 B。

输入键绑定 chain/stage、default/override 帧、已验证历史与撤销列表、seed 完整描述、源码来源、
live 内容清单、portable 编译输入及实际工具链快照。live capture 包括受版本控制文件、未忽略的新文件，
并扫描源码项目、std/runtime；使用与 builder 相同的保守上界，dirty 与新增依赖均可见。
完整来源清单使文档或来源 commit 变化也可能新建 generation，这是保守失效，不是只验 HEAD。
A 与 B 的 `__source-inputs` 仍由 builder 交叉核对；每次命中重验输入、实际 CC/链接器/库/头文件、
seed/配对树、chain receipt、A/B 及中间产物和 B 的 source plan，交付前再次复验输入与控制记录。
pre2 每次全量校验的冷/热实测留在该刀交接报告；补裁九允许的开发 stat 摘要缓存见 §15.1，不能只看 mtime。

覆盖接口定稿为三件同时提供：`DAWN_NATIVE_SEED=<ELF>`、
`DAWN_NATIVE_SEED_LOCK=<describe-seed 生成的完整描述>`、
`DAWN_NATIVE_SEED_TREE=<prepare-pair 生成的配对根>`。
配对根包含 `std/` 与 `runtime/c/`，从描述中的 seed commit 重建并核对内容，不能用当前树凑配对。
覆盖独立 stamp，并受当前仓库撤销表约束。`CC` 可选择 clang；默认使用钉定 clang18，
其它 clang 使用 development recipe，仍要求现行 GCC 13 静态库布局。全部源码 generation 都是 development。
继承的 CFLAGS、include 与优化环境不参与自举，builder 继续使用清空后的环境及 `CC_JOBS=1`。

查询接口也先完成相同验证：`DAWN_PRINT_STAMP=1` 输出
`native-v1:development:<default|override>:<输入摘要>:<B ELF 摘要>`；
`DAWN_NATIVE_PRINT_GENERATION=1` 输出一行规范 JSON，字段为 `stamp`、`executable` 与 `receipt`。
后续消费者应使用该边界取得已验证 B 与收据，不猜缓存目录。两种查询都可能在 miss 时构建，
构建日志仅写 stderr，stdout 只包含查询结果。普通调用最终用 `exec` 替换进程，保留 argv、cwd、信号与退出码。

本刀不改默认、不推进种子、不删除原型、不迁移生产消费者、不把 generation 当作资格或发布证明。
消费者逐个显式选链、原型删除与最终资格仍依 §13.7 分刀完成。

### 15.1 P4-pre2b 热路径（补裁九，2026-11-25）

pre2 的五次热启动中位数为 5.565 s（前序验收报告），不能进入默认切换。
本刀目标为同机、持租约、CC_JOBS=1 的五次热启动中位数不超过 0.5 s；冷启动另行报告。
启动内复用 Git 对象读取及已计算的源码、编译输入与工具链快照，并将快照显式传给 receipt verifier。
开发热路径可使用内容摘要代理，键包含绝对 path、dev、inode、size、mtime_ns、ctime_ns 与完整 mode。
缓存记录写入时间，mtime 落在写入时间的文件系统时间粒度内时强制重哈希；保守采用至少一秒窗口。
读前后 stat 必须一致，交付前重新检查观察过的元数据及文件集合；变化即拒绝本次交付。
头文件集合仍枚举，工具链与生成物均绑定内容摘要。S、A/B ELF 仍逐次读取并验摘要与完整身份。

stat 缓存按 generation 保存，自带规范内容的 SHA-256，写入使用同步后的原子替换；
最近 generation 指针只是查找提示，不能代替输入键、marker 或 receipt 验证。缓存损坏直接拒绝。
缓存只通过启动器的显式参数传入；builder 冷构建、资格与 release 不读取此缓存，始终全量。
未跟踪源文件仍枚举。源码、seed 配对、工具链、阶段输出、source plan 与撤销控制的验证边界保留。
文件保持只读，目录保持所有者可写，使 rm -rf 与 worktree remove 无需先 chmod。

负控先红覆盖伪造 mtime、同粒度改写、缓存篡改、工具链头文件与未跟踪源文件变化、
资格/release 禁用缓存，以及两种清理方式；native Java 调用仍须为零。
若只能靠减少身份校验达到目标则停止回报。不做缓存回收或缺 marker 自动恢复，默认链仍 jar。

启动内同一 ELF 摘要对应的 version/full build ID 探测结果可复用；S 及 A/B 的当前字节仍逐次读取并验摘要。
独立的编译器参数查询和 ldd 查询并发执行，完整保留每个查询及其拒绝条件，不启动并行 C 编译。
路径合法性等纯函数可记忆化，receipt 的同一批规范字节只解析一次；冷构建、资格和 release 仍全量读取输入。
性能不足时不得跳过工具链解析或缩小快照集合；最终五次实测与是否达到门槛必须如实记入交接报告。

补裁十允许开发热路径缓存工具链探测结果。键绑定 clang realpath 和完整 stat 元组，driver 解析的
GCC/crt/libc 输入及 ld 的 stat 元组、GCC 安装树和 recipe 摘要；任一变化或 racy 条目回到真实探测。
查询记录与文件摘要共用 generation 缓存和完整性摘要；同次热启动的同一查询只执行一次。
冷构建、资格与 release 不读此探测缓存。负控须证明换 clang inode、改 GCC 安装树、改 recipe
均重新探测。若最终五次热中位数仍超 0.5 s，拆报解释器启动、import、stat、B 摘要、
receipt/source plan 及其余耗时后停线，不继续减少验证项目。

具体缓存的查询为 clang 身份、driver 路径、ld 版本及 qualification flags；ldd 仍每次解析实际依赖。
探测键额外覆盖已解析动态库、辅助程序、加载器配置及目录成员；新解析出的依赖会使查询重新执行。
冷启动收集器只记录真实调用，不消费持久或启动内答案；通过全量构建与验证后才为下一次热启动保存。

补裁十一将开发热路径的头文件失效判据改为编译器 depfile。A/B 构建以 `-MD -MF`
记录实际读取的头文件，依赖清单绑定到 chain receipt；完整工具链环境快照仍在构建时全量记录。
热命中检查实际依赖、include 搜索目录及可能遮蔽嵌套头文件的目录、配方身份，
不遍历未被包含的头文件。依赖或目录变化回到全量捕获与构建，资格、release、cold 仍全量。
负控须分别证明实际包含头文件改动失效、前置目录新增同名头文件失效、未包含头文件改动不失效。
其余开销须细分到函数级；保留原有身份验证，五次热中位数仍以 0.5 s 为门槛。

补裁十二允许去除剩余重复工作：完整 stat 缓存与只含热依赖的紧凑索引放在同一个
原子写入的封套中，分别带完整性摘要并互相绑定摘要。热路径只解析索引，仍验完整缓存
字节摘要；索引被篡改或与完整缓存不一致必须拒绝。构建时记录完整环境，资格/release 不读索引。
清单摘要按规范字节作进程内 memo，启动结束即丢弃；相同字节只核验、计算一次。
receipt 解析可在重新读取且字节相等后复用，S/A/B 每阶段仍至少真实探测一次版本及完整 build ID。
大块内容摘要也仅按当前完整字节复用，文件仍逐次读取；S/A/B 探测按阶段分别记忆，不合并阶段。
开发热路径缺少紧凑索引时直接拒绝，不回退旧缓存格式；显式清理开发缓存后重新全量构建。

## 16. P4-pre3 消费者显式选链（2026-11-25）

默认仍为 jar，不改种子三文件、native lock/history/revoked 或 VERSION。
下表登记每处选择的文件、行号、能力与链；机器清单是 `scripts/seed-consumers.json`，
`scripts/seed-consumers-test.py` 要求选择仍存在，且在模拟 native 默认的能力夹具中逐项移除必红。
脚本内的 export 只约束该 JVM oracle 及其子进程，不设置 workflow/job 的全局 jar。
混合差分继续用当前 JAR 与直接执行的 native ELF；`DAWN_SELF`、`DAWNC_BIN` 与显式 Java 命令仍指定原来的独立对象。
共享 toolchain action 明确只准备 JAR，其外部执行替身只对该构建子进程设 jar，不污染后续 selector 夹具。

### 16.1 已迁入口全表

表中“JVM CLI oracle”表示保留原门的 JVM 运行/输出/黄金或性能口径；纯 Dawn 程序不因此被声明为必须依赖 Java。
同一脚本内的所有 launcher 调用均继承该行的选择，额外独立的空环境必须再次声明。
负控执行真实消费者的初始化前缀或实际环境表达式；注释或字符串中的同名字面量不算选择。
JAR 侧最终执行当前 `build/dawn-selfhost.jar`，JAR generation/stamp 由源码 launcher 复验；native 侧直接执行原被测 ELF。

| 选择文件:行 | 调用或默认命令定义行 | 所需能力 | 选链 |
|---|---|---|---|
| `playground/deploy/redeploy.sh:12` | 87, 117 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `playground/test/c-only-acceptance.sh:9` | 19 | JVM CLI oracle | `jar` |
| `playground/test/contract.sh:25` | 98, 133 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/adt-reuse-contract/run.sh:36` | 182, 198, 215 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/array-contract/run.sh:25` | 36, 107 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/asm-adapter-contract/run.sh:80` | 98 | JVM `__emit`/class 输出 | `jar` |
| `scripts/atomic-write-contract/run.sh:34` | 123, 128, 139, 558, 725 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/bench.sh:26` | 66 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/bootstrap-input-manifest-contract/run.sh:13` | 16 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/builtin-decl-contract/run.sh:26` | 30 | JVM CLI oracle | `jar` |
| `scripts/builtin-type-contract/run.sh:23` | 26 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/bytes-pack-contract/run.sh:27` | 37, 47, 53 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/c-map/same.sh:26` | 28 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/checker-corpus/run.sh:20` | 46, 85, 87, 94 | JVM CLI oracle | `jar` |
| `scripts/classfile-verify/run.sh:69` | 84, 132, 287, 375, 377, 381, 387, 390, 392, 438, 440, 488, 501 | JVM `__emit`/class 输出 | `jar` |
| `scripts/comptime-bytes-contract/run.sh:8` | 24 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/comptime-eval-closed-contract/run.sh:20` | 23 | JVM CLI oracle | `jar` |
| `scripts/comptime-trace-contract/run.sh:10` | 13 | JVM CLI oracle | `jar` |
| `scripts/core-lint-contract/corpus.sh:24` | 35, 49, 54, 68, 71 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/ctl-live-contract/run.sh:56` | 174, 175 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/delete-contract/run.sh:20` | 106, 110, 117, 293, 300 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/dict-owner-contract/run.sh:27` | 58 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/display-layering-contract/run.sh:35` | 41 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/dtoa-contract/run.sh:24` | 49, 61, 64 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/effect-evidence-contract/run.sh:64` | 68 | JVM CLI oracle | `jar` |
| `scripts/emitrange.sh:60` | 65, 192, 195 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/error-contract/run.sh:20` | 24 | JVM CLI oracle | `jar` |
| `scripts/example-tests.sh:22` | 45 | JVM CLI oracle | `jar` |
| `scripts/export-surface-contract/run.sh:22` | 25 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/for-pattern-contract/run.sh:15` | 19 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/frame-contract/run.sh:39` | 73, 75 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/grammar-corpus/run.sh:32` | 36, 54, 74, 124, 131 | JVM CLI oracle | `jar` |
| `scripts/hamt-contract/run.sh:19` | 25, 36 | JVM CLI oracle | `jar` |
| `scripts/imm-contract/run.sh:34` | 139 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/incremental-semantics-contract/sweep.sh:67` | 195, 416 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/inflate-contract/run.sh:12` | 32, 57, 64, 94, 139, 184, 272 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/int-min-contract/run.sh:14` | 22, 24, 30 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/io-prims-contract/run.sh:54` | 65, 96, 102, 124, 125, 211, 216 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/java-member-dispatch-contract/run.sh:25` | 28 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/java-narrowing-contract/run.sh:17` | 20 | JVM CLI oracle | `jar` |
| `scripts/java-target-classpath-contract/run.sh:13` | 17 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/jsig-lease-contract/run.sh:15` | 19 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/json-suite.sh:20` | 23 | JVM CLI oracle | `jar` |
| `scripts/jvm-map/same.sh:23` | 25 | JVM `__emit`/class 输出 | `jar` |
| `scripts/list-elems-contract/run.sh:31` | 36 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/loader-listdir-contract/run.sh:35` | 123 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-lifecycle-contract/run.sh:7` | 53 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-workspace-contract/run.sh:9` | 13 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/map-reuse-contract/run.sh:43` | 197, 198, 214, 215, 234, 256, 257 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/mem-contract/run.sh:36` | 41 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/narrow-contract/run.sh:60` | 88, 103, 108 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/native-asan-tests.sh:39` | 74, 76 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/native-cli-diff.sh:68` | 97, 103, 138, 167, 192, 218, 245, 314, 404, 560, 610, 630, 701, 821, 936, 1014, 1306, 1390 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/native-fixpoint.sh:22` | 93, 94, 122 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/native-selfhost-tests.sh:31` | 42, 45 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/opaque-twin/run.sh:95` | 97 | JVM CLI oracle | `jar` |
| `scripts/package-tests.sh:24` | 46 | JVM CLI oracle | `jar` |
| `scripts/path-contract/run.sh:16` | 20 | JVM CLI oracle | `jar` |
| `scripts/pattern-or-contract/run.sh:15` | 19 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/pipe-contract/run.sh:31` | 34 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/pkg-origin-contract/run.sh:37` | 40 | JVM CLI oracle | `jar` |
| `scripts/project-plan-contract/run.sh:8` | 12 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/pvec-contract/run.sh:20` | 26, 37 | JVM CLI oracle | `jar` |
| `scripts/range-bound-order-contract/run.sh:7` | 13 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/rc-mode-contract/run.sh:62` | 122, 125 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/rc-view-contract/run.sh:31` | 135, 151 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/release-native.sh:57` | 116 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/replay-bootstrap.sh:27` | 126 | JVM `__emit`/class 输出 | `jar` |
| `scripts/scalar-bench/run.sh:18` | 55, 58, 79 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/selfhost-core-diff.sh:94` | 150, 164 | JVM `__emit`/class 输出 | `jar` |
| `scripts/selfhost-fmt-diff.sh:24` | 43, 44 | JVM CLI oracle | `jar` |
| `scripts/selfhost-lsp-diff.sh:25` | 34 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/selfhost-param-diff.sh:41` | 91, 92 | JVM CLI oracle | `jar` |
| `scripts/selfhost-prev-diff.sh:94` | 271, 272 | JVM `__emit`/class 输出 | `jar` |
| `scripts/selfhost-run-diff.sh:10` | 39, 41 | JVM `__emit`/class 输出 | `jar` |
| `scripts/site-dist-diff.sh:66` | 82, 146, 149, 159 | JAR generation stamp | `jar` |
| `scripts/source-loop-label-contract/run.sh:7` | 13 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/source-plan-contract/run.sh:15` | 18 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/spike-native/run.sh:130` | 254, 283, 292, 528 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/std-version-contract/run.sh:43` | 46 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/syntax-small-contract/run.sh:19` | 22 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/table-freight/run.sh:27` | 35, 42, 43 | JVM `__emit`/class 输出 | `jar` |
| `scripts/tea-reconciler-contract/mutants.sh:27` | 73, 74, 75 | JVM CLI oracle | `jar` |
| `scripts/tea-reconciler-contract/run.sh:44` | 51, 55 | JVM CLI oracle | `jar` |
| `scripts/tile-golden/run.sh:505` | 855, 891, 898, 1297, 3266, 3283, 3322, 3528, 3601, 3690 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/tile-gpu-diff/run.sh:509` | 797, 1271, 1300, 1352, 2708, 2725, 2850, 2877, 2915, 2921, 2966, 2985, 3004, 3025, 3052, 3089, 3320, 3445, 3617, 3880, 3989, 4048, 4204, 4580, 4658, 4857, 5765, 5779 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/tileinterp-diff/run.sh:37` | 68, 149, 179, 192, 198, 211, 222, 228 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/unicode-contract/run.sh:34` | 39 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/wasm-contract/run.sh:44` | 81, 86, 180, 264 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/wasm-dom-contract/collect.sh:33` | 40 | JVM CLI oracle | `jar` |
| `scripts/wasm-dom-contract/flags.sh:34` | 45 | JVM CLI oracle | `jar` |
| `scripts/wasm-dom-contract/retained.sh:32` | 50, 53 | JVM CLI oracle | `jar` |
| `scripts/wasm-dom-contract/run.sh:81` | 154 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/web-exchange-contract/run.sh:34` | 46, 49, 113 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/xmap-samples/run.sh:43` | 46 | JVM CLI oracle | `jar` |
| `site/dawnc.sh:44` | 54, 70 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `playground/test/c-only-contract.py:12` | 114 | JVM CLI oracle | `jar` |
| `playground/test/c-only-matrix.py:18` | 110, 148, 151 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `playground/test/lsp_tileir_contract.py:24` | 59 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `playground/test/serve-compare.py:29` | 23, 107, 155 | JVM CLI oracle | `jar` |
| `playground/test/tile-probe-contract.py:13` | 74 | JVM CLI oracle | `jar` |
| `scripts/api-snapshot.py:67` | 455, 456 | JVM CLI oracle | `jar` |
| `scripts/bitwise-contract/check.py:15` | 24 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/c-map/run.py:39` | 50 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/call-records-contract/run.py:39` | 130, 211, 358, 370 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/core-lint-contract/run.py:37` | 49 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/core-sites/run.py:35` | 46 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/dependency-test-contract/run.py:12` | 121, 142 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/diag-properties/run.py:112` | 600 | JVM CLI oracle | `jar` |
| `scripts/dict-owner-contract/shapes.py:17` | 27 | JVM CLI oracle | `jar` |
| `scripts/doc-check.py:256` | 267, 2736, 3324, 3327, 5012 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/example-main-contract/run.py:10` | 220 | JVM CLI oracle | `jar` |
| `scripts/ffi-extern-contract/run.py:13` | 24 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/ffi-sources-contract/run.py:12` | 24 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/flash-config/check.py:24` | 46 | JVM CLI oracle | `jar` |
| `scripts/fmt-properties/run.py:92` | 816 | JVM CLI oracle | `jar` |
| `scripts/incremental-semantics-contract/bench.py:17` | 104 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/incremental-semantics-contract/cold.py:16` | 27 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/java-metadata/run.py:15` | 350 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/jvm-map/run.py:35` | 46 | JVM `__emit`/class 输出 | `jar` |
| `scripts/lex-properties/run.py:69` | 458 | JVM CLI oracle | `jar` |
| `scripts/lsp-decl-pairing.py:43` | 37, 50 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-framing.py:19` | 9, 663 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-lifecycle.py:15` | 8, 292 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-liveness.py:59` | 50, 651 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-references-workspace.py:39` | 26, 372 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-references.py:41` | 28, 366 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-rename.py:67` | 53, 818, 885 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-resolution-coverage.py:34` | 22, 414 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-semantic-tokens.py:52` | 37, 902 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-std-documents.py:14` | 308, 365 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/lsp-std-resolution.py:34` | 18, 28, 41 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-unused-import-action.py:23` | 17, 134 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/lsp-use-completion.py:30` | 24, 176 | JVM LSP 回归与 Java 类型解析 oracle | `jar` |
| `scripts/math-contract/gen.py:16` | 149 | JVM CLI oracle | `jar` |
| `scripts/math-contract/run.py:13` | 50, 56, 78 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `scripts/mem-contract/scope.py:14` | 26, 43 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/native-cli-contract/doc_metadata.py:12` | 36, 79 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/pub-doc-check.py:54` | 4, 103, 211 | JVM CLI oracle | `jar` |
| `scripts/sqlite-contract/run.py:18` | 33 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/tile-golden/entry6-source-controls.py:13` | 21 | JVM CLI oracle | `jar` |
| `scripts/tile-prep/full.py:9` | 182 | build-to-jar、当前 JAR 或 JVM 产物 oracle | `jar` |
| `scripts/trait-capture-contract/run.py:20` | 213, 215, 232, 251, 292, 294, 296, 298, 342, 345, 353 | JVM `__emitc` 引导与独立 native 对拍 | `jar` |
| `site/gpu-map/record.py:64` | 290, 738 | JVM CLI oracle | `jar` |
| `site/inputs.py:229` | 28, 232 | JVM bootstrap SourcePlan and native tool preparation | `jar` |
| `scripts/seedjar.sh:123` | 123 | JDK identity for JAR seed and JVM differential oracles | `jar` |
| `scripts/bootstrap-guards/perf-data.py:81` | 80, 108, 116 | JVM perf-data policy and copied launcher fixture | `jar` |
| `.github/actions/dawn-toolchain/action.yml:146` | 147 | Explicit JAR bootstrap shared by JVM gate consumers | `jar` |
| `scripts/gates-external/backend_local.py:478` | 478, 480 | Exact local substitution of the JAR composite build only | `jar` |
| `scripts/gates-external/inputs.py:636` | 19, 553, 627, 646, 649, 651 | Coursier input-pack priming requires Java dependencies | `jar` |
| `playground/sandbox/run-sandboxed.sh:125` | 选择环境传给显式子进程 | JVM-only deployed launcher in an empty sandbox environment | `jar` |
| `playground/deploy/dawn-play-native@.service:36` | 35 | JVM-only deployed launcher for runner subprocesses | `jar` |
| `playground/deploy/preflight.py:31` | 62 | Current JAR freshness, JVM ELF reader and current-source native manifest oracle | `jar` |
| `.github/workflows/gates.yml:1710` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM test compiler-plan | `jar` |
| `.github/workflows/gates.yml:1714` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM test selfhost | `jar` |
| `.github/workflows/gates.yml:1771` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM fmt compiler-plan std site selfhost packages examples scripts/tile-gpu-diff --check | `jar` |
| `.github/workflows/gates.yml:1831` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM test --stdlib | `jar` |
| `.github/workflows/gates.yml:2718` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM __emit selfhost -o "$RUNNER_TEMP/gate-emit" > /dev/null | `jar` |
| `.github/workflows/gates.yml:2915` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM lock --check selfhost | `jar` |
| `.github/workflows/gates.yml:3373` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM __emitc selfhost/src/nmain.dawn --split "$RUNNER_TEMP/nmain" | `jar` |
| `.github/workflows/gates.yml:3844` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM test site | `jar` |
| `.github/workflows/gates.yml:4260` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM --version > /dev/null | `jar` |
| `.github/workflows/gates.yml:4261` | 1710, 1714, 1771, 1831, 2718, 2915, 3373, 3844, 4260, 4261 | JVM __emitc selfhost/src/nmain.dawn --split "$RUNNER_TEMP/native-selfhost-c" | `jar` |
| `.github/workflows/nightly.yml:135` | 135 | JVM test selfhost | `jar` |
| `scripts/c-map/check.py:60` | 73 | JVM __emitc source-map oracle | `jar` |
| `scripts/core-sites/check.py:43` | 54 | JVM __lower and parse oracle | `jar` |
| `scripts/jvm-map/check.py:69` | 83 | JVM class emitter and javap source-map oracle | `jar` |
| `scripts/fp-contract-contract/run.py:18` | 123, 141 | JVM __emitc and floating point differential oracle | `jar` |
| `scripts/slab-bench/run.py:371` | 936 | JVM __emitc benchmark producer | `jar` |
| `scripts/xmap-samples/record.py:36` | 43 | JVM sample recording and javap metadata | `jar` |
| `site/redeploy.sh:32` | `site/build.sh` 子进程 | 站点部署中的 JAR 引导与 JVM recording oracle | `jar` |

### 16.2 独立对象与无需迁移的入口

| 入口 | 能力与明确对象 | 选择方式 |
|---|---|---|
| `scripts/build-release-jar.sh`、`scripts/selfhost-fixpoint.sh` | 唯一 JAR 固定点配方；S/A/B/C 是各自 JAR | 直接 `java -jar`，不经默认 selector |
| `scripts/native_release.py chain`、`scripts/native-seed-qualify.py` | 原生 S→A→B→C、资格与独立 verify | 显式 ELF 和配对树参数，不自动转 JAR |
| `bin/dawn` 的 native 分支、`scripts/native-launcher-test.py`、`scripts/native-seed-lock-test.py` | native 源码启动及两链拒绝边界 | selector 夹具逐项构造 jar/native 环境，禁止外层 jar 遮蔽 |
| `scripts/bootstrap-guards/launcher-contract.sh`、`scripts/check-launcher-jvm-opts.py`、`scripts/dependency-heap-contract/run.py`、`scripts/example-main-contract/selftest.py` | launcher/JVM 策略及无源码 JAR 夹具 | 各私有 fixture 已显式 jar；非法/native 拒绝在独立空环境验 |
| site 已制备 `dawnc`、SourcePlan、generator/search、TEA reactor | 同树 native 消费与 Java metadata 数据读取 | 直接 ELF；prepare 引导仍 jar，D12-3 另迁 |
| Playground `/check`、C/tile view、native LSP gateway | native compiler/runner 独立身份 | 直接 ELF；`/run`、JVM view 的 shell 子进程在 service 和 sandbox 各选 jar |
| `editors/vscode` 与 `editors/` JVM LSP 配置 | Java 类型解析 | 已有显式 `java -jar <versioned JAR>`；源码 launcher 用户在编辑器启动环境设 `DAWN_SEED_CHAIN=jar`，不按 import 猜链 |
| `scripts/native-install-contract.py`、`scripts/install-native.py` | 原生发行 B 安装与无 Java smoke | installer 明确安装 ELF；日常启动没有 selector、Python 或 JVM |
| `scripts/method-size-gate.py` | 读指定产物/记录或接受明确 compiler 参数 | 不隐式启动默认 launcher；调用方已经选择独立 JAR/ELF |

无源码 shell 保持 JVM-only，缺失/空/未知/native 选择和 seed 覆盖在 Python/Java 前拒绝。
`playground/deploy/redeploy.sh --preflight` 在任何远端连接前比较当前 JAR 与项目清单、
两种 reader 的 native 完整 build id、当前 portable 源码重算的 native manifest，以及 runner 与当前 playground 清单。
JSON 分别记录三个产品的 SHA-256/full build id；它不宣称重新证明 release S→A→B→C 或 B 的种子资格。
部署实际 native B 的 provenance 仍必须由同 tag 的发布 metadata/完整 receipt 核验。

### 16.3 可比文件集、预算与边界

既有独立对拍保留以下文件集：native CLI/fixpoint 的 whole C 与 split C/manifest；
`scripts/site-dist-diff.sh` 的两侧 `site/dist` 完整文件清单、每个文件字节（含可比 wasm/assets）、
`docs-jvm` 与 snapshot `site/build/doc-inputs` 的 API JSON，以及相同输入的 generator 输出。
JAR 与 ELF、自身身份/来源 receipt 不互作字节相等对象；每侧身份另核。
本刀不增加每个 job 的源码 native 冷启动：新增冷建数 N=0，现有 native 题目继续直接运行其独立 ELF。
新增固定选链/部署身份夹具实测约 4.0 秒，java-target-classpath claim 565→575 秒，
push-total 40310→40320 秒，timeout 29 分钟不变；steps lock 随 run 文本更新。
P2 的约 8.5 秒已计入 pre1，未重复计入。本机计时与最终全套证据另在实施报告保留。

P0 原型的所有调用/文档/门禁台账引用已迁至生产协议，并按补裁五第 4 条删除目录。
源码启动器仍可要求 Python 3.11+；installer 的 Python 3.10 独立实测不改变源码依赖。
P3 仍须最终输入资格、真实 qualified lock、拟晋级 B 自身资格/独立 verify、三组配对与七日/十次观测；
本刀的夹具和双链对拍不代替这些条件。热启动 ≤0.1 秒是 P4 后的新债，不并入 pre3。
