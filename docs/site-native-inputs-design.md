# 建站消费输入边界

> 状态：current

建站只消费显式预制备的 native 工具与锁定的原始 class 数据。`site/prepare.sh` 与
`site/build.sh` 分开执行；前者可以从源码自举工具、解包固定 JDK，后者缺少收据即失败，
不调用 JVM stamp、不启动 Java、不接收旧文档 JSON 作为替代。独立 JVM 对照门保留。

工具收据绑定实际二进制、编译器 SourcePlan 输入、嵌入 std、runtime/c 与构建配方。
一个小型 native 输入清单程序直接复用 compiler-plan 的 SourcePlan 序列化函数；它只
提供身份记录，不增加解析器、依赖规划器或 checker，也不扩展 nmain 的命令能力。
输入树同时记录文件名与内容，缺失的可选 lock 也入摘要，新增文件不会绕过身份检查。
共用 `site/dawnc.sh` 的独立 playground 与 C-only 自举合同保持；建站入口验证收据后
显式传递已验证的 DAWNC_BIN，使其所有子消费者走 native 路径。

`site/java-metadata.lock.json` 独立固定上游归档、模块、根集合与完整 manifest SHA。
先核对锁，再检查全部 class 文件、目录清单与每项字节身份。生产包文档均由 native
生成，仅经审阅的 web-jvm 目标显式传入元数据；其他目标仍保留默认拒绝 Java 的边界。
固定的十四包清单与现场 manifest 核对，不用 grep 决定驱动，不提供 JVM 回退。

每次 build 在新 staging 生成 stdlib 和全部包文档。旁置 bundle 收据绑定工具、数据、
SourcePlan 输入、包 manifest 身份、实际 argv 与全部输出；多余、缺失、损坏或陈旧
输入均在生成器运行前拒绝。完整验证后通过一次目录更名晋升，生成器在该 bundle
的固定视图中读取，旧 JSON 不参与本次构建。文档 JSON schema 与 writer 不改。

资格包含清空文档、dist、生成器与 probe 后的真实资产构建。隔离环境禁止所有 Java
执行，清理 JAVA_HOME/CLASSPATH 并跟踪整个消费进程树；真实 npm、C 与 wasm 工具
仍可用。独立 JVM 门比较同 HEAD 文档及完整页面、索引和搜索资产，保留错锁、篡改
后重算自摘要、输入漂移与不完整清单等负控。site 作业增加显式准备步骤，既有 build
步骤承担实际无 Java 消费；不修改 java-target-classpath 或 playground 作业。


## 收官核验设计

收官只回填当前说明、设计状态与落地进度，产品代码和门禁接线保持。以同一最终
候选同时核对原始数据及工具身份、十四包公开面、JVM 原字节、冷暖两次真实无 Java
消费、签名语义、可靠失败和能力隔离。受控变异仅进入隔离源码树，必须由既有断言
拒绝；true-parent 原始对照不使用输出豁免。预算复用既有步骤记录，核对输入和接线
身份后区分既有债、附带增量及刻意新增验证，不增加计时门。

## 落地与资格入口

617cccb4（#940）交付本消费边界。先运行 `site/prepare.sh`，再运行 `site/build.sh`；
准备工具可以使用既有 JVM 自举，原始数据由 Python 解包固定 JDK，消费不运行 Java。
`dawn-doc-tool-v1`、独立准备收据与 `dawn-doc-bundle-v1` 分别绑定工具、数据和本次
全部输出，不把收据加入正常 doc JSON。完整清单和 manifest pin 由
`site/java-metadata.lock.json` 审阅固定，web-jvm 的 `InputStream` 公开签名保留。

`site/inputs-selftest.py` 覆盖身份漂移与不完整 bundle，`scripts/site-dist-diff.sh`
从独立 JVM JSON 生成第二套站点输入并比较全部字节；它保留为独立 oracle。
无 Java 资格要求冷消费和热缓存消费都提供真实 npm、C、wasm 工具，移除旧文档及
生成器缓存后构建正常资产，检查从 build 根进程开始的全部 exec，拒绝绝对路径绕行。
工具或数据变化后的热缓存也须拒绝陈旧身份。语义与 CLI 资格入口见
[元数据设计](java-class-metadata-design.md)，逐刀提交见 [后续进度](history/m7-progress.md)。

## 不做的（理由）

JMOD 运行时读取、通用 Maven、多版本 JAR、Java 执行和其它命令的元数据能力需要
各自的来源、执行及错误合同，继续留在本线之外。工具自举和独立 JVM oracle 可以
使用 Java，建站消费不能借此启动准备或增加 JVM 文档 producer。固定点、发布资格
与 GPU 台账按既有入口保留；本线不发布、不部署、不重录设备数据。
