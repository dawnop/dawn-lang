# 发布 API 快照的 native 输入

> 状态：proposed

动码前的调研与方案，不是设计定稿。基线为 0b4ead2f，当前
`scripts/api-snapshot.py:174` 拼接 doc 命令，`:223` 枚举 std 与全部包；
`.github/workflows/release.yml:262` 仍把刚构建的 JAR 作为快照工具。
只换工具会让 web-jvm 缺少显式 Java 数据上下文，不能删包求绿。

## 输入合同

增加可重复的 `--java-signatures TARGET=MANIFEST`。TARGET 是仓库根目录下的
包目录，例如 `packages/web-jvm`；必须精确匹配现场包清单。manifest 路径按
调用者当前目录解释，再转为绝对路径交给 doc。重复目标、空值、未知目标和 std
目标先拒绝，再运行任何 doc。未指定的包沿用普通 doc，std 沿用 `--stdlib`。
接口只传递数据，不提供环境发现、自动回退或跳包选项；原快照 schema、规范化、
API diff 及两个报告资产名保持。

发布步骤用本版 `dawnc-linux-x86_64`。原始数据由既有
`scripts/java-metadata/prepare.py` 从固定 JDK 21 制备，完整 manifest 与受版本
控制的 `jdk21.lock.json` 比较，再显式交给 web-jvm。沿用 D31-1 的来源、身份、
版本、每类摘要和闭包校验，不增加 class parser 或新的身份 schema。

## 验证与预算

固定夹具自检覆盖目标选择、路径解释、错误传播、完整包清单和 metadata 转交，
包含漏传 metadata 与误跳 web-jvm 的负控。发布接线检查要求制备锁定数据、使用
native artifact 并传给 web-jvm，错误工作流夹具必须拒绝。日常 CI 只跑这些轻量
检查，不重复完整发布或十五份 doc。

轻量自检作为 java-target-classpath 的独立步骤，接线负控复用原 bootstrap guards；
新增覆盖显式 planning 5 s，claim 690→695 s，push-total 37178→37183 s，timeout
保持 35 分钟。steps lock 用 record 生成。实测从托管步骤日志/API 回读，区分
新增覆盖和原步骤漂移，不增加本机计时，不占计时租约。

一次性验收使用新构建的发布 artifact：std 加全部十四包的完整规范化快照与同源
JVM oracle 逐字节相同；校验 web-jvm 的七函数、二类型及 InputStream 签名。
隔离 Java 路径并跟踪 native 快照整个 exec 树，Java 执行须为零；JVM doc 仅在
明确的独立 oracle 阶段。真实坏输入分别验证 metadata 缺失、版本错和摘要错，
不得产生部分输出。沿用 metadata、site、API diff 自检及最终完整门禁。
发现两端差异且不能归因时停工，不清洗输出或豁免差异。

## 不做的（理由）

- 不重写 class reader，不扩 JMOD、Maven 或多版本 JAR；本刀只改变快照输入。
- 不改 API diff、JSON schema 与发布资产名；消费者格式没有变化需求。
- 不改 bootstrap 与 native builder；它们有独立的来源和身份合同。
- 不把全包快照或完整发布加入每次 push；现有 doc 语义门已覆盖编译器，本刀新增
  日常责任是输入接口与发布接线，完整生产闭包由本次验收证明。
