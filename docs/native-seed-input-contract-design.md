# Native 种子、来源查询与配方合同（D12-2 K1–K2）

> 状态：**current**。K1 输入合同与 K2 来源查询、统一配方已实现，完整冷链资格留待后续刀。K2 基线为 `b2555b46`。

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
当前源码和生成物，再核 std/runtime 路径及树摘要；C 编译前拒绝错配。仅允许
clang 18.1.3、x86_64 GNU Linux 和并发 1 或 2，通过唯一 `cc-units.sh` 传入
`--static --inline-rc --runtime`，清除继承的 C flags、include、cache 与 std 环境。
执行后重核配对、源码、compiler bytes 和静态 ELF，最后写独立 compile receipt，
记录阶段、输入、recipe、argv、compiler probe 与输出摘要。失败不写成功 receipt。
此收据不绑定 emitter 的执行，也不证明 C units 的产生过程、完整工具链闭包或冷链。

一次性入口 `scripts/native-seed-k2-test.py --out <new-dir>` 运行 17 项固定负控
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
