# JVM 差分输出与 perf-data 审查

> 状态：**current**。2026-10-24，issue #839 的启动入口审查。

HotSpot 的 perf-data 文件以 `/tmp/hsperfdata_<user>/<pid>` 命名，和
`TMPDIR` 无关。文件锁冲突时，VM 自己的警告可能进入 stdout，让程序的
JVM/native 差分在程序输出相同时变红。这里的入口都不消费这些计数器，
因此在 JVM 启动参数里禁用，而不是删除或过滤程序 stderr。

## 入口与覆盖

| 入口 | 处理与覆盖范围 |
|---|---|
| `bin/dawn` | 部署和源码两种 exec，以及 producer、seed、stage 1 的构建启动都显式传 `-XX:-UsePerfData`。参数放在 `DAWN_JVM_OPTS` 之后，连显式覆盖也不能重新打开 perf data。由 `check-launcher-jvm-opts.py` 的真实脚本调用和缺旗负控守护。 |
| `selfhost/src/main.dawn` 的 `child_java_cmd` | 已有相同参数，覆盖 run、test 和依赖重启的子 JVM；保留原有断言。 |
| `playground/src/play/exec.dawn` | contract 比较 runner 的 `/run` 输出和 `/compile` 的 javap 视图；两个直接入口分别传 `-XX:-UsePerfData` 与 `-J-XX:-UsePerfData`，包括 unsafe-local 测试路径。配对 HTTP 合约的 PLAY_JAVA/PLAY_JAVAP 指向显式传旗的薄包装，两侧包括历史 runner 都经过同一入口。 |
| `scripts/spike-native/run.sh` | JVM 语料通过 `bin/dawn run`，因此编译器和被比较的程序两层均禁用。stdout、stderr 和退出码的比较原样保留。 |
| `selfhost-{run,lsp,fmt,prev,param}-diff.sh` | 每一个 seed JVM 的直接调用或生成包装都显式禁用；HEAD 侧走 `bin/dawn`。`native-cli-diff.sh` 的独立 std-resolution JVM 也显式禁用。 |
| `selfhost-core-diff.sh`、`std-prune-diff.sh`、`site-dist-diff.sh` | 使用 Dawn 启动器或纯 native 产物，没有独立的裸 JVM 输出入口。 |
| `scripts/*-contract/` | 直接启动的程序、编译器变异体、生成的 shell 包装和 LSP jar 命令都显式传旗；其余入口继承 `bin/dawn`。包括 web 的三个 Python 驱动、sqlite 的生成包装和 classfile 验证器。 |
| `scripts/lsp-*.py` | 接受 jar 的 references、rename、resolution、semantic tokens 驱动在构造 JVM argv 时传旗；接受任意命令的通用会话驱动由调用者提供已加旗的命令或 `bin/dawn`。 |
| `scripts/{c-map,core-sites,jvm-map,core-lint-contract,bitwise-contract,fuzz3}/` | 直接 jar 命令显式禁用。`jvm-map`、`xmap-samples` 和 classfile probe 的 javap 输出被解析或保存，也传 `-J-XX:-UsePerfData`。 |
| `scripts/tileinterp-diff/run.sh`、`spike-sam/run.sh` | 直接运行的 JVM oracle 显式禁用。 |
| `build-release-jar.sh`、`replay-bootstrap.sh`、`native-fixpoint.sh`、`release-native.sh`、`advance-seed.sh` | 直接 JVM 命令显式禁用，保持原有构建和字节比较。 |
| `.github/workflows/release.yml` | 两处版本/构建身份读取和 API snapshot 的 jar 入口显式禁用，避免完整版本串或 JSON 被 VM 文本污染。 |
| `scripts/gates-external/inputs.py` | 已有 java 和 JDK 工具 shim，分别传 `-XX:-UsePerfData` 与 `-J-XX:-UsePerfData`；本次不依赖外部门禁的 shim 来补齐公开脚本。 |

## 不比较 JVM 输出的入口

`selfhost-bench.py` 和 `incremental-semantics-contract/bench.py` 的直接 JVM
是资源/延迟测量，输出日志是观测附件，不是 JVM/native 或版本之间的字节
oracle。`selfhost-bench-contract` 的 Java 进程是 jcmd/进程树采样夹具，不比较
Java 程序的 stdout；记录在测试数据里的 argv 也不是启动点。
`lsp-sync-bench` 会解析真实 LSP 帧，已经在服务器启动处显式禁用。

普通 `javac` 和打包用的 `jar` 调用以退出码及生成文件为判断对象，其 stdout
不进入程序差分。`doc-check.py` 与 bootstrap 自测里故意写出的裸 java 字符串是
负控输入，不是遗漏的被比较 JVM。JDK `-version` 的观测元数据也不参与程序
输出的字节差分。

## 故障注入与运行成本

本地运行 `python3 scripts/bootstrap-guards/perf-data.py`。辅助 Python 进程先
报出自身 PID，等父进程创建并同时持有该 PID 的两种文件锁后才 exec Java，
因此不猜下一 PID。正控必须由 HotSpot 自己打印原警告；禁用后必须逐字保留
应用 stdout 和 stderr。部署形式的 launcher 还覆盖 check、lsp、run，以及
显式设置 `-XX:+UsePerfData` 的环境覆盖。

该探针不进外部门禁，因为 HotSpot 的固定 `/tmp` 路径不属于门禁私有 prefix；
CI 中原有 launcher 参数门禁增加缺旗负控。没有新增 gates.yml 步骤。
重新执行 `steps_lock.py record` 后锁文件不变，171 个步骤、28 个 family 保持。
旗本身没有新增子进程或等待；本地锁故障探针约 3 秒，单独运行，不计入 CI
关键路径。门禁整体实测写在交接报告。
