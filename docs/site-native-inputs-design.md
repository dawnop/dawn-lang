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
