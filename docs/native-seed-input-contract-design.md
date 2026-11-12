# Native 种子、来源查询、配方与冷链合同（D12-2 K1–K3）

> 状态：**current**。K1 输入合同、K2 来源查询与配方已实现；K3 增加显式冷链执行与审计入口，完整资格仍须逐输入验收。K3 基线为 `8b830d3b`。

## K3：无 Java 冷启动 runner 设计

先以固定的 `v0.104.0` 候选验证当前 Git snapshot 的 A 发射兼容性，再实现完整
执行链。准备阶段核 seed、源码、配对 std/runtime、clang 18.1.3 与工具链闭包的
内容身份；执行阶段使用独立隔离 root，断网、无 Java 可执行文件，不挂宿主 home、
产品检出、缓存或可绕回宿主的 proc。源码、seed 与工具链只读；环境从白名单重建。
每代 output/object/tmp/home 均为空目录，只允许读取已登记输入与本代产物。

S 用 seed std 发射 A，A 用 seed runtime 独立编译链接；A、B 分别用 current std
发射 B、C，B/C 用 current runtime 在各自新对象目录链接。内嵌 stdsrc/rtsrc 始终
来自 current snapshot，继续复用同一 `cc-units.sh`，不复制 flag 表。保留 whole
C/info 比较，加 B/C 文件集合、单元 bytes 与静态 ELF 比较；不要求旧 S 发射的 A
等于 B。两个独立空 root 的 B 也须相等，并从裸目录验证内嵌 std/runtime smoke。

执行审计保存全部 descendant exec 与文件访问，核可执行文件允许清单及摘要、
输入只读边界和网络隔离。receipt 绑定输入 receipt、seed lock、工具链、recipe、
阶段顺序、实际 emitter 与输出身份和跟踪摘要；独立验证重新计算结果，不信任
producer 自填的成功布尔值。至少一项 Java 名称执行或暖缓存 canary 必须使审计
明确拒绝，任意异常不算负控成功。执行耗时只记粗量，不做本机计时。

若旧 native 不能编当前语言、std 或 runtime，立即停止实现并估算桥接发布，不改
源码来迁就旧 seed，不加兼容层。B/C 不同且不能归因也停止，保留原始失败待裁。
不改生产 builder、release/install 协议、默认种子或原 native-fixpoint 义务，因为
资格证明不等于生产切换授权。不新增每 push 重链，不塞入 prev-diff-native；本刀
不改 workflow，新增日常调用预算为 0 s。后续轻结构检查接线须独立记账且合计
不超过 30 s，完整资格与负控仍是显式验收，不能把一次绿灯冒充日常覆盖。

## K2：来源查询与统一配方设计

native 增加隐藏的 `__source-inputs --base <repo> <project-dir>`，只接受项目目录，
与 JVM 入口直接调用同一个 `compiler-plan/source` producer。保留 v1 header、
记录类型、排序、路径作用域、诊断及退出码；查询不加载 std，不启动 Java。
不另造包解析器，不复制 launcher，不改 SourcePlan 的来源图和 Maven/MVS 语义。
查询只描述来源，含 Java 坐标的 manifest 也可查询；这不授予 native 编译 Java 的能力。

旧 portable capture 改为物化保守源码超集，保留 selfhost/compiler-plan/packages 的
相对布局，复用 K1 的 portable manifest 变换与本地路径核验，拒绝 symlink、
外部依赖、漏件及特殊文件。资格 capture 继续只读指定 Git commit；既有 native
测试的 capture 保留读取当前源码的用途，不把它冒称为资格 snapshot。

`cc-units.sh` 增加显式 runtime 目录参数，编译与链接继续使用唯一的 flag 表和
固定对象顺序；旧调用者保留树内 runtime 默认值。资格配方另要求显式 A/B/C、
std/runtime 路径、已核输入 receipt 和 C compiler，核对阶段身份后调用此脚本，
A 配 seed，B/C 配 current，拒绝只换一半。首期只接受 clang 18.1.3 与 x86_64
GNU target，记录 probe 与实际 argv；版本和 triple 预检不是完整 sysroot 身份证明。
完整工具链封闭、只读挂载、执行闭包审计与三代运行归 K3，不能由 probe 推导合格。

一次性验收保留原 JVM manifest 合同和 bootstrap guards，增加同输入 JVM/native
wire bytes 逐字节对照，以及漏件、外链、错 stage/runtime 的明确判词负控。
native 查询执行单独跟踪 descendant exec，Java 计数必须为零。重型验证不接入
push，不改 workflow、steps lock 或 claim，新增日常调用预算为 0 s；既有调用
改为物化目录的额外复制成本如实记录，不能宣称整个 PR 的运行成本为零。

不改生产 builder、release/install 身份协议，不推进默认 seed，因为这些需要后续
资格与独立生产切换授权；不实现 cold runner，因为本刀只准备其来源与配方接口。

## K1 输入合同

本刀为 Linux x86_64 的隔离资格链建立输入合同：严格读取 seed lock 和输入
receipt，一次性登记 `v0.104.0` 候选，从指定 Git commit 捕获源码，并定义
A 使用 seed std/runtime、B/C 使用 current std/runtime 的配对。候选不是合格种子，
输入 receipt 不是冷自举或固定点证明。完整工具链身份、执行审计与资格证明留待 K2–K5。

lock 和 receipt 均使用独立的 schema 2 与明确 kind，拒绝重复键、未知字段、缺字段、
非法摘要、非法路径和错误 target。native 输入只使用显式 `--seed` 或
`DAWN_NATIVE_SEED`，不得读取 `DAWN_SEED`。每次消费重新核实际 bytes、静态
ELF64 little-endian machine 62、版本与完整 `b1:`；不允许忽略验证。

候选登记器只接受固定历史 tag、commit、资产名、大小和已知 SHA-256。先核真实
bytes，再执行版本查询；复核远端 tag，绑定从同一 commit 提取的 std/runtime。
历史发布缺 metadata 在候选中明确记录，只在这个一次性入口处理，不成为日常
reader 的缺字段兼容。输出到调用者的新目录，最后原子写完整 lock；不写产品默认。

## 源码与配对

从 Git 对象捕获完整 tracked tree 的保守超集，保留原相对目录，不读 live checkout。
读取固定禁用 Git replace objects，避免 commit 身份被本地替换视图改写。
拒绝 symlink、gitlink、特殊文件与不安全路径。portable 变换只去掉 selfhost manifest
的 java-deps 表；不解析包闭包，不复制 resolver。保留本地依赖，拒绝绝对路径、
逃逸、远端依赖和缺 manifest。compiler-plan 与 inflate 等传递依赖由完整树保留，
权威 source-inputs producer 已由 K2 接入 native；两端共用原有 v1 producer。

清单按 UTF-8 路径 bytes 排序，使用带域分离与长度 framing 的 SHA-256。每项明确
路径、类型、存在/缺失、长度、摘要及执行位；对项目 dawn.lock 的缺失也建记录。
receipt 记录 commit/tree、原始清单、portable 清单、变换版本与实现摘要、变换前后
manifest、current std/runtime/embed。reader 重新构造指定 commit 的预期输入，
再逐项核捕获目录，拒绝增删改与类型变化。生成器只在临时副本中运行并比较
stdsrc/rtsrc，不修改被捕获输入。捕获目录去写权限，但真正只读挂载及并发隔离
仍属 K3；本刀不把 chmod 和前后摘要宣称为完整竞态防护。

阶段合同显式列 A/B/C 的 std/runtime 身份：A 两者来自 seed commit；B/C 两者来自
current commit。内嵌 stdsrc/rtsrc 始终来自 current source，不为 A 换回 seed。
阶段顺序、漏项、重复、角色交换或只换一半均拒绝，即使实际 ABI 暂时兼容。

## 推进、回滚与不做的理由

初始候选 sequence 为 0，parent 与 qualification 为空；不得被读取为 qualified。
将来推进必须绑定上一 lock/receipt 和完整资格 evidence，序号及版本单调增加，
撤销身份必须拒用。回滚另有显式 from/to/reason 审核记录，保留历史 bytes；K1
不实现推进或回滚命令，避免在完整资格验证器出现前提供可以祝圣种子的入口。

不改 JVM 的 seed-release/checksums/std-checksums。K1 没有改旧 portable capture
或 C recipe；K2 将 capture 物化，并为同一 C recipe 增加 runtime 参数。不改 release-native、
installer、release workflow 的身份协议，因生产切换另有授权边界。不执行冷链，
因 K1 只验输入，不能以输入核验替代 K3 的无 Java 与 B/C 证明。不扩平台，不声称 DDC。

## 验证与预算

用小 Git fixture 和 ELF fixture 验 Q1/Q2/Q3/Q6/Q7，逐项要求匹配明确拒因，
不以任意异常当负控成功。真实 v0.104.0 下载核 SHA/size/ELF/version/b1/tag 与
std/runtime，并在真实 capture 副本做一次源码变异。失败不得产生合格状态。
现有 anchor 两项提交前运行，最终 SHA 跑完整门禁及独立验包。

本刀不新增 workflow 或 push 调用：新增 push 成本为 0 s，准备、重复编译、缓存
失效与覆盖控制增量均为 0；轻量合同测试为一次性验收。K5 接入 push 时须单独
显式记账，新增控制合计不超过 30 s。本刀不做本机计时。

## 已实现的接口与身份

K1 入口为 `python3 -B scripts/native-seed.py`，三个输入命令均要求显式路径：

```sh
python3 -B scripts/native-seed.py register-v0.104.0 \
  --repo . --assets /prepared/assets --out /prepared/candidate
python3 -B scripts/native-seed.py capture --repo . --commit FULL_COMMIT \
  --lock scripts/native-seed-candidate-v0.104.0.json --out /prepared/inputs
python3 -B scripts/native-seed.py verify --repo . \
  --lock scripts/native-seed-candidate-v0.104.0.json \
  --receipt /prepared/inputs/inputs.json --source /prepared/inputs/source \
  --seed /prepared/candidate/seed/dawnc --seed-tree /prepared/candidate/seed
```

登记器必须在线复核远端 tag 和固定的六件历史资产；capture 与 verify 只读本地
Git 对象和显式输入，不联网补缺。输出目录必须不存在，不覆盖已有 lock。登记目录
中的 `registration.json` 摘要由 lock 绑定，证据不进入产品树。候选文件是显式登记
记录，没有产品默认调用者。三个命令的成功输出均不授予 qualified 状态。

| 对象 | schema 2 的必需内容 |
|---|---|
| lock | kind、candidate 状态、sequence 0、完整 seed、std/runtime、空 parent/qualification lineage、显式历史 registration 引用 |
| seed | native-elf、tag、完整 commit、固定资产名、SHA-256、size、GNU target、确切版本文本、完整 build ID |
| std/runtime/embed 身份 | 同代 commit、独立算法 ID、规范树 SHA-256；与旧 seed_tree_sha 数值不混用 |
| inputs receipt | 独立 kind、规范化 lock 摘要、source 描述、按顺序恰好 A/B/C 三项配对 |
| source 描述 | commit/tree、原始与变换后清单摘要、完整 portable 清单、变换版本/实现摘要、原始与变换后 manifest 摘要、std/runtime/embed 身份 |

reader 只接受 K1 初始候选，不提供序号、资格状态或撤销策略的宽松分支；K4/K5
接入资格 verifier 后才能增加 qualified 消费。当前 input receipt 没有输出、工具链
probe 或执行成功字段；传入 `complete` 或 proof kind 会被严格拒绝。K2 的独立
compile receipt 记录 C version/triple probe 与固定 recipe；完整 sysroot 身份与
隔离审计归 K3，不能由 seed target 或相同版本推导。每次 verify 重核 bytes 并用私有副本执行两个身份查询，防止改换
原始 seed 路径。副本不是编译缓存。

真实候选已核：远端 tag commit 为 `8068f0ba3ffaaabfcf10e103e375da678dbb15b6`，
资产为 13,800,672 字节，SHA-256 为
`e1506ef0aee7978a00fa07a0c2eebe565a2a35fc788128590d6106baeaf0186f`，
完整 build ID 为
`b1:158ec8003d1d7a1b9d30943aad1d9f04440d65df96e9481d8ad73b16e8a6ebf1`。
旧发布没有 metadata；这项事实不影响单独授权的历史候选登记，也不产生 schema 1
读取入口。当前整树 capture 的生成物比对已通过，冷启动兼容性仍待 K3 实测。

快验入口为 `python3 -B scripts/native-seed-contract-test.py`。它只创建自己的 Git
和 ELF 夹具，逐项检查负控拒因，不变异编译器源码。日常门尚未接入，未观测表
明确登记此边界；未来不得把这份夹具绿灯当成完整资格。

## K2 已实现的接口与验收

```sh
/prepared/dawnc __source-inputs --base /prepared/source /prepared/source/selfhost
python3 -B scripts/native-seed.py compile-stage \
  --repo . --lock scripts/native-seed-candidate-v0.104.0.json \
  --receipt /prepared/inputs/inputs.json --source /prepared/inputs/source \
  --seed-tree /prepared/candidate/seed --stage A \
  --std /prepared/candidate/seed/std --runtime /prepared/candidate/seed/runtime/c \
  --cc /toolchain/bin/clang --jobs 1 --units /out/A/units \
  --build-info /out/A/info.c --out /out/A/dawnc --recipe-out /out/A/compile.json
```

`compile-stage` 必须显式给出所有路径、阶段和并发数。阶段先核输入 receipt、
当前源码和生成物，并复用 K1 的实际 seed tree verifier，从 seed commit 重建
std/runtime 身份，再核路径及实际树摘要；自洽伪造的 lock/receipt/目录也不能换掉
seed 配对。C 编译前拒绝错配。仅允许
clang 18.1.3、x86_64 GNU Linux 和并发 1 或 2，通过唯一 `cc-units.sh` 传入
`--static --inline-rc --runtime`，清除继承的 C flags、include、cache 与 std 环境。
执行后重核配对、源码、compiler bytes 和静态 ELF，最后写独立 compile receipt，
记录阶段、输入、recipe、argv、compiler probe 与输出摘要。失败不写成功 receipt。
此收据不绑定 emitter 的执行，也不证明 C units 的产生过程、完整工具链闭包或冷链。

一次性入口 `scripts/native-seed-k2-test.py --out <new-dir>` 运行 18 项固定负控
并检查真实 shell 的编译 flag、显式 runtime 和 lexical link order；加
`--dawnc <binary> --java <java> --jvm-jar <jar>` 后运行八组真实双端对照。
四组有效输入的 wire bytes 逐字节一致，四组错误输入的完整诊断、退出码与空 stdout
一致。native 查询的 descendant exec 跟踪中 Java 次数为 0，另有 canary 证明可
观察到后代 Java 名称执行。该检查只证明查询路径，不冒称整个冷链已无 Java。

旧 live capture 现在复制 selfhost/compiler-plan/packages 的源码与 manifest 保守
超集，复用 K1 portable 变换，返回 `<capture>/selfhost/src/nmain.dawn`。没有新增
源码 resolver。原 JVM manifest 合同、bootstrap guards 和生成物义务仍保留。
本刀无新增 push 调用、workflow、claim 或 steps lock 变更，新增日常控制预算 0 s；
物化目录替代外链的复制与既有测试成本由现有调用承担，不记作新增控制免费额度。

## K3 已实现的接口与验收边界

```sh
python3 -B scripts/native-seed.py prepare-toolchain \
  --cc /usr/lib/llvm-18/bin/clang --out /prepared/toolchain
python3 -B scripts/native-seed.py cold-run \
  --repo . --lock scripts/native-seed-candidate-v0.104.0.json \
  --receipt /prepared/inputs/inputs.json --source /prepared/inputs/source \
  --seed /prepared/candidate/seed/dawnc --seed-tree /prepared/candidate/seed \
  --toolchain /prepared/toolchain --out /qualification/new-run
python3 -B scripts/native-seed.py verify-cold --repo . --out /qualification/new-run
```

准备器仅接受 Ubuntu 24.04 的 clang 18.1.3/GCC 13 GNU sysroot 布局。它物化
compiler、linker、动态装载依赖、resource-dir、C headers、CRT、静态 libc/libm/
libgcc 及必要 shell 工具，输入链接解引用成普通文件；保存完整清单、摘要与来源。
这份离线快照是重放工具链的输入，不按相同版本字符串替换成另一套系统库。
不挂宿主 `/usr`、`/lib` 或用户目录，不把已登记 CRT 对象误称为自举暖缓存。

runner 私有物化已核源码与 seed，工具链根只读挂载；每次执行独立 user、mount、
PID、network 等 namespace，清除 capability，以白名单环境和空 stdin 启动。
proc 仅显示本次 PID namespace；不提供宿主 proc 或返回宿主 root 的入口。
两个 root 分别创建 A/B/C 输出目录，每个执行步骤有新 home/tmp，C 编译并发固定
为 1。对象只从本步骤的新 tmp 产生；审计检查每个 TU 的实际编译及独立静态 link，
按 lexical TU、runtime、info 的顺序消费对象。B/C 比较 whole、info、完整 units
清单与 bytes、ELF，双 root 复核 B；裸目录 smoke 没有 source/seed 挂载。

每代 current compiler 调同一 source-inputs producer，下一次发射后重查实际
emitter 的计划；旧 S 无需新增入口。所有 descendant 的 exec 与文件系统调用由
外部跟踪器记录，并翻译 PID namespace 编号，缺 trace 或无法解析的进程创建即拒。
核实际 namespace argv、允许执行文件及摘要、成功 open 的边界和网络调用。shell
可能探测不存在的本地 nscd socket；只接受该固定路径的 ENOENT，不构成成功网络
依赖，单独记录次数。Java 名称执行、未知可执行文件、外部成功读取与网络访问均拒。

`receipt.json` 绑定输入、工具链、唯一 C recipe、runner/审计器与隔离工具身份，
记录两 root 的阶段产物、来源计划、逐步骤原始跟踪摘要与 smoke。独立 verifier
重核输入、实际命令、允许清单、编译链接覆盖、跟踪、固定点与 smoke，不消费
`complete=true`。失败保留原始目录且不写成功 receipt；已有输出目录一律拒绝。
这份冷链 receipt 仍不提升 candidate，也不替代 K4 的完整负控、JVM 对照/replay
或 K5 的资格与日常轻门交接，更不改生产 builder 与发布安装协议。

一次性守卫验收入口是 `scripts/native-seed-k3-test.py --out <new-dir>`，固定夹具
覆盖后代追踪、PID 翻译、漏 trace、Java、未知 executable、越界读取、网络、暖目录、
跳过 payload 及四类伪固定点。加 `--toolchain <snapshot> --seed <ELF> --lock <lock>`
后真实启动一个名为 java 的 native 子进程，要求明确 audit-java、计数 1 且无成功
步骤收据。它只证明观察器能抓到后代，不把替身当成实际 JVM。

本刀不改 workflow、steps lock、claim、timeout 或 push 接线；新增日常准备、
重复构建、缓存准备与覆盖控制调用均为 0，push-total 保持 38673 s、pole 950 s。
两 root 的 6 次完整 emit 与 6 次独立 cc/link、跟踪、重核和 canary 为显式资格成本，
不计作每 push 的 0 s；不做本机计时，不预填 Gate-Budget，不借旧 job 的 claim。
