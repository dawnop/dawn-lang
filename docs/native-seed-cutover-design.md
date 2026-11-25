# Native 种子链生产切换（D12-2 P）设计

> 状态：**current**（accepted，2026-11-25，协调者补裁一把 §9 的开放问题全部裁定，见 §10；P1 起按此实现）。
>
> (Accepted after the supplementary ruling of 2026-11-25; the open questions in section 9 are settled in section 10.)
>
> 前置：[native-seed-input-contract-design.md](native-seed-input-contract-design.md)（K1-K5，资格工具与隔离原型已交付，生产 no-go）。
> 本页只设计 P0-P5 六刀，P0 即本页。不含 D12-3（站点 prepare 去 JVM），它依赖本页 P 的 builder 合同，在 P4 之后另起设计页。
> 基线 main `6c9614f2`。

## 1. 现状与目标

### 1.1 现状

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
  `registration.metadata=absent`）和 `scripts/native-seed-prototype/`（schema 2 的 producer、聚合、installer
  原型，共 419 行，只写调用者的新目录）。K5 在最终输入 `f68940f4...` 上证明了双 root 冷链 B/C 一致、
  Java exec=0、外网 syscall=0，原型 26 项拒绝控制通过（出处：K5 交付记录与
  [native-seed-input-contract-design.md](native-seed-input-contract-design.md)）。
  `validate_lock` 现在只接受 `candidate`/`sequence 0`，不认已资格的 lock。

### 1.2 目标

| 维度 | 现在 | P4 之后 |
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
   而不是本次 release 的资格包（本次 release 不跑双 JDK 等重链，见 §5.5 和开放问题 2）。

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
**跨托管 runner 的重建是否同字节没有实测**，P1 的验收里要加一条真实重跑实测，见 §2.6 与开放问题 1。

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
| 某件上传中途 | R1。是否会留下半个资产取决于 GitHub 对失败上传的处理，**未验证**（开放问题 1）；若列出了截断资产，比对时因字节不等落入 E2 | 完整的则补齐；截断的落 E2，需维护者手工清理（未封存） |
| 前八件已传、metadata 未传 | R1，未封存 | 比对前八件并补传 metadata；未封存期间消费者看不见可信 metadata |
| metadata 刚传完、最终核对未跑 | R2 | 只验证，通过即成功 |
| 最终核对中失败（如下载损坏） | R2 | 重跑再验证；持续失败即事故，维护者发新 tag |
| 封存后有人删了某资产 | E1 | 红；新 tag |
| advance-seed（native 版）已引用该 tag 后，工作流被手动重跑 | R2 | 只验证，不可能修改字节 |

#### 2.5.5 与现有守卫的冲突与改法

`scripts/bootstrap-guards/run.sh` 现有守卫要求 release.yml 含 `--clobber` 的整行并检查三行相对顺序。
P1 把它改为：断言 `--clobber` **不出现**；断言「create 唯一调用、逐件循环、metadata 最后、最终验证在上传之后」的新顺序；
并新增变异负控：把任一逐件上传改回带覆盖标志、把 metadata 挪到非末位、去掉 R2 的验证步，守卫均须红。
这与「门禁的绿没有信息量」一致：先证明会红，再宣称它是守卫。

### 2.6 P1 验收判据

- 原型 26 项拒绝控制全部搬进生产合同，并在生产路径上仍正确地红或绿（逐项列表对账，不得缩项）。
- `--clobber` 全仓 0 命中（对 `.github/`、`scripts/`、`docs/` 的 grep 负控；注释里引用旧行为的文字改写为不含该串）。
- 状态机 R0 至 R2、E1 至 E4 与七个中断点各有一条用假 `gh`（本地桩）驱动的测试，覆盖「中断后重跑得到相同终态」。
- 在一个**非生产演练仓或演练 tag** 上完整走 producer、聚合、installer 三步，且对同一演练 tag 实际重跑一次，
  记录两次构建的 B、JAR、metadata、proof 是否同字节，作为 2.5.3 逐字节类别的实测出处。
- `scripts/doc-check.py` 双向核对（INSTALL 6 + REPORT 3）通过；README.md 先改、README.zh-CN.md 译本同步。
- 旧八件 schema 1 的任何分支在生产代码里 0 残留（没有兼容层）。

### 2.7 P1 推翻判据

撤 `--clobber` 后无法设计出可收敛的中断重跑：具体即开放问题 1 的实测显示跨 runner 重建不同字节，
或失败上传会留下无法区分的半资产。此时退为裁决中预设的后备：**以草稿 release 承载上传，全部就绪后一次性发布**
（草稿对消费者不可见；中断后丢弃整个草稿重来；发布后只验证）。该后备改变「是否删除任何东西」的口径，
须另裁，P1 不自行切换。

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
- `DAWN_NATIVE_SEED` 覆盖路径仍进入 bootstrap stamp 的「override」帧（对应 `bin/dawn` 里 `dawn-bootstrap-digest-v2`
  对 jar 的做法），所以覆盖产物不会被误当默认缓存复用；release job 里该变量必须未设置，由 release.yml 断言。
- 选择链（native 种子链或 JAR 种子链）由一个显式的启动器选择量决定，**两条链之间没有任何自动回退**：
  选了 native 而种子缺失或不合格就失败，不悄悄改走 JVM。默认值在 P4 才改；P2 到 P4 之间默认仍是 JAR 链。
  选择量的名称与取值在 P2 实现时定稿，设计里只钉「无回退、默认在 P4 切」（开放问题 5）。

### 3.3 晋级（`advance-native-seed`）

在 `scripts/advance-seed.sh` 旁新增 native 版入口，输入一个 tag，保持与 JAR 版同样的「指针最后动」纪律：

1. 从 origin 新鲜解析 tag commit，前后复核 tag 未移动，tag 是 HEAD 祖先；
2. 下载九件资产，跑 §2.2 的聚合检查与 installer 前置核对；
3. 检查**单调性**：新 `tag` 的版本严格大于当前 lock 的 `seed.tag`，`sequence = 当前 + 1`，
   `lineage.parent_lock_sha256` = 当前 lock 字节摘要，`parent_receipt_sha256` = 该 tag 的 metadata 所记的
   上一代 receipt；
4. 检查**未被撤销**：新种子 sha256 不在撤销名单；
5. 要求一份对该 ELF 的 `seed-promotion` 资格 receipt（K5 工具的 `native-seed-qualify.py run`，reason
   `seed-promotion`），其摘要写入 `lineage.qualification_sha256`；没有就拒绝，不允许先晋级后补；
6. 先把旧 lock 原字节写入 `native-seed-history/<旧 sequence>.json`，再原子替换 `native-seed-lock.json`。
   中断恢复：历史文件先于 lock 落盘，重跑见到「历史已写、lock 未换」时幂等收敛；见到「lock 已换、历史缺失」不可能
   发生（顺序保证），出现即判污染，拒绝并报错。

回滚：`advance-native-seed --rollback <seq>`。只允许回到**历史里存在、未被撤销**的种子；生成一条新 lock，
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

S3 之后输入冻结（裁决第 2 条）。冻结的定义：从 `selfhost/`、`compiler-plan/`、`std/`、`packages/`、统一 C recipe、
runtime 的 Git tree 在 P3 开始到 P4 发布的整个窗口内不变；资格 receipt 的 inputs 摘要绑定整树
（K5 最终输入 3935 项，tree `5cddb9ee...`，inputs `f68940f4...`；这个值在冻结后会换新，旧包失效）。
输入再变则 P3 顺延，不在移动输入上资格。

### 4.2 重新资格

在冻结 commit 上用 K5 入口 `scripts/native-seed-qualify.py run` 做两次：

1. reason `initial-seed`：把 v0.104.0 候选转为已资格 lock（§3.1）；
2. reason `seed-promotion`：对 P4 将要晋级的那份 B（即由 v0.104.0 种子编出的冻结 commit 的 B）。

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

- **同形态**：在 P2 合并之后 tree-policy 里 native 轻步骤、gates.yml 的 job 集合与 steps.lock 不变的区间；
  这三者任一改变，窗口重新起算（补裁六）。
- **7 天**按日历天，且窗口内**至少有 push 样本**。现状是 main 零 push 时没有样本，所以窗口必须有真实 push
  才推进；天数满而 push 数为 0 不算满（出处：就绪评估记录 11-17 至 11-24 零 push）。最小 push 样本数是开放问题 3。
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

1. 改 `selfhost/src/version.dawn` 的 `VERSION` 为 0.107.0，提交，push main，等 main CI 绿，打 tag 并按
   仓库发布规则只推该 tag（禁止 `git push --tags`）。
2. release.yml 按 §2.5 发九件；失败走状态机，不覆盖。
3. **真实 tag 冷下载与同提交聚合**：在干净环境下载九件，跑聚合与 installer；metadata 的 `release.commit` 等于 tag
   commit，`bootstrap.seed` 等于该 commit 里的 lock。
4. 用 `advance-native-seed v0.107.0` 晋级（§3.3，需要对 v0.107.0 的 `seed-promotion` 资格 receipt）。
5. 部署仍按既有规则以 tag 为准：先 Playground 后站点，站点带 `DAWN_WASM_CC`。native 种子只换构建链，
   **不应改变运行产物**，所以验收增加一条：部署内容与 JVM 链产物逐字节一致。
6. 启动器选择量的默认值在此刀改为 native，JAR 链改为显式选择（§3.2）。

observe 删除的 S 刀已在 P3 前收完，P4 随带的是发布而不是语言改动。

P4 推翻判据：冷下载聚合失败、重跑出现 E2、部署产物与 JVM 链不一致，任一即停并回交；已发布的 tag
不撤改，错版发新 tag（v0.107.1）。

### 5.2 P5：预算收口

P4 之后托管上才有真实重链 run。此刀把重链托管预算与生产频率定稿：

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
| P3 | 重新资格与演练 | §4.6 | §4.6 | 0（资格是显式入口，重链不入 push 路径；成本是显式资格成本，不藏进日常 cap，不挪用拆片准备额度） | 只产生证据；不得与 S 刀并行（输入冻结） |
| P4 | v0.107.0 发布 | §5.1 | §5.1 | tag 触发，不入 push 总量；release 墙钟新增 S→A→B→C 与 JAR 并行链，须实测报告（开放问题 6） | VERSION、lock、seed 文件；发布与部署顺序 |
| P5 | 预算与频率 | §5.2 | 数据不足即不收口 | 唯一可能写 `Gate-Budget` 的刀；现状基线：K5 把 push-total 由 38673 秒改为 38683 秒，tree-policy claim 650 到 660 秒，pole 950 秒、timeout 33 分钟不变 | gates.yml、steps.lock、budget-observations |

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
  生产要的是另一套行为（真实上传、真实 lock）；P1 把规则升格为生产模块，但原型目录按「原型」保留到 P4 之后再议去留。
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

## 9. 待裁定的开放问题

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
9. **`scripts/native-seed-prototype/`** 在 P4 合并时删除，不留兼容（不做兼容层原则）。
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

- P1 合并后下一个 tag 即发九件、schema 2。**种子仍是 `scripts/native-seed-candidate-v0.104.0.json`（候选 lock）**：P2 的 qualified lock 不在 P1 内，所以 `native-bootstrap.json` 的 `qualification_sha256` 此时为 `null`（取自候选 lock 的 `lineage.qualification_sha256`），P2 之后由 lock 的资格 receipt 填入，并在 P2 起拒绝 `null`。这是设计 §2.3.1 第 2 点在 P2 之前的如实状态，不是兼容分支。
- `release-native.sh` 仍在每次 push 上跑，但它构建的 B 来自 JAR 链，只用于 native-cli-diff 与协议契约包；release 不再用它的产物。它不再写 `dawn-toolchain.json` 与 `install-native.py`。
- 「全仓 0 命中」的 grep 对 `.github/` 与 `scripts/` 成立；本设计页与 PR 文字里的历史引用保留（它们描述被撤掉的行为）。
