# 编译器重量基线设计

> 状态：**current**。本文是 #230 Phase 1 的定稿，定义可复现的测量口径与机器契约。
> Phase 1 只建立 telemetry 和自举 CPU 比值门槛，不修改编译器堆策略。

## 1. 问题

旧 `scripts/selfhost-bench.sh` 只有一项 `passC_user / passA_user` 比值，而且已经失真：

1. 基线钉在 `v0.29.0`，当前种子已经推进到 `v0.64.0`。
2. 脚本把 A、B、C 三趟都交给当前 `std/`，违反正式发布配方。正式配方要求 A 使用种子
   release 的 std，B 和 C 使用当前 std。
3. `DAWN_SEED` 可以替换真实 JAR，输出却仍把 `seed-release.txt` 写成来源。
4. 参数、baseline 和浮点输入是宽松解析，`NaN`、`Infinity`、零分母、偶数样本等都可能进入
   裁决。
5. 噪声超过阈值后仍继续报告 PASS 或 FAIL。
6. 所谓 `passC_wall_ms` 是一次完整 selfhost build，不是启动时间。
7. RSS 只看到了单个进程，无法描述 `test selfhost` 同时存在三台 JVM 的真实重量。

2026-08-11 的重新勘测给出了当前事实：`test --stdlib` 的完整进程树峰值约 1.61 GiB，
`test selfhost` 约 3.34 GiB；后者包含父编译器、dependency re-exec 和 `TestMain`。
同次勘测还确认 dependency re-exec 没有继承父进程的 `-Xmx2g`。这些数字来自
`~/workspace/agent-handoff/codex-log.md` 的 `2026-08-11 #230 编译器重量重新测量`，
只用来说明为什么要建立正式口径，不直接成为预算。

## 2. Phase 1 的边界

Phase 1 交付以下内容：

- 严格、版本化、可重算的 JSON baseline。
- 正式 release JAR 和 native compiler 的摘要与字节数。
- 四个固定 workload 的完整进程树 RSS、逐角色 VmHWM、VmPeak 和实际最大堆。
- direct JAR、`bin/dawn` 和 native compiler 的 warm version 启动时间。
- A/B/C 自举 CPU 比值，保留历史上的加 15% 比较门槛。
- 不依赖真实编译器构建的 schema、`/proc` 和 source mutant 机器契约。

Phase 1 不修改 `bin/dawn`、`selfhost/src/main.dawn` 或 `TestMain`，也不修改栈、JAR 压缩、
native static link 和 strip 策略。ARC-07、ARC-08 不因获得 telemetry 而关闭。

Phase 2 才处理 dependency re-exec 的堆继承。届时应继承父编译器的实际堆上限，而不是把本次
机器上的临时 768 MiB 探针写成产品常量。`TestMain` 的用户程序堆策略仍是另一项设计。

## 3. 命令与退出状态

入口仍是 `scripts/selfhost-bench.sh`，它只定位仓库并 `exec` Python 核心：

```text
scripts/selfhost-bench.sh [--measure | --record | --check]
  [--weight-samples N] [--startup-samples N] [--max-rounds N]
```

三种模式互斥，省略时是 `--measure`。重量样本默认 3，启动样本默认 11，重试轮数默认 3。
每个参数必须带值。重量与启动样本数必须是达到最低值的正奇数，`--max-rounds` 可以是 1 到 3
之间的任意整数；冲突模式和非法参数退出 2。

- `--measure` 测量并打印结果，不读写 baseline。
- `--record` 只在结论不是 inconclusive 时，用同目录临时文件和原子 rename 写 baseline。
- `--check` 在测量前严格读取 baseline，且只用自举 CPU 比值作 PASS 或 FAIL 裁决。

成功退出 0，预算失败退出 1，使用错误或 preflight 失败退出 2，噪声无法裁决退出 3。

## 4. 构建前 preflight

所有 preflight 都在任何构建和 warm-up 之前完成。正式硬件测量只支持 Linux x86_64。
入口依次确认：

1. 当前目录属于仓库根，HEAD 已提交，tracked 与 untracked 工作树均干净。测量结束后、打印任何
   结果或写 baseline 前，再次验证 HEAD 未变且工作树仍干净。
2. Python、Bash、Git、Java、同一 JDK 的 `jcmd`、C 编译器、`readelf`、`locale` 和 SHA-256
   工具存在；`C.UTF-8` 必须实际解析为 UTF-8，不能用会破坏 Unicode 路径的纯 `C` locale。
3. 样本参数与模式合法，`--check` baseline 严格可读。
4. `seed-release.txt` 只有一个合法 tag，checksum 表只有一个对应 digest。
5. `seedjar.sh` 解析出的实际 seed JAR 摘要与表中 digest 完全一致。
6. 会改变或伪装测量输入的环境变量不存在。

拒绝集合包含 `DAWN_SEED`、`DAWN_SEED_CACHE`、`DAWN_SEED_ALLOW_UNVERIFIED`、
`DAWN_JVM_OPTS`、`DAWN_SELFHOST_CP`、`DAWN_PKG_CACHE`、`DAWN_MAVEN_MIRROR`、
`DAWNC_BIN`、`JAVA_TOOL_OPTIONS`、`JDK_JAVA_OPTIONS`、`_JAVA_OPTIONS`、`JAVA_HOME`、`CLASSPATH`、
`COURSIER_CACHE`、`CC`、`CFLAGS` 和 `LDFLAGS`。空值也拒绝，因为存在本身已经使来源含糊。

## 5. 正式产物与 A/B/C

release JAR 必须由 `scripts/build-release-jar.sh` 在测量临时目录生成。benchmark 不再复制三条
build 命令。正式 builder 保持 seed、seed std、current std 和 vendor 的唯一配方，只增加一个
不改变参数与输出的内部计时文件：A、B、C 每趟写 user CPU 与 system CPU。该文件由 benchmark
创建、严格解析并在轮次结束后删除，普通 release 调用不产生它。system CPU 只用于确认每一行
计时完整、有限且非负；Phase 1 baseline 和预算只保存并使用 user CPU。

每轮先做一次不计数 warm-up，再执行 N 个完整 builder 样本。每个样本都必须通过 B 等于 C、
standalone smoke 和最终原子提升。不同样本产出的 release JAR 还必须字节一致。

native compiler 必须由 `scripts/release-native.sh --jar <release-jar>` 在同一个临时目录生成。
记录两个正式产物的 SHA-256 与字节数，不读取或复用仓库中 ignored 的 `build/` 或 native 文件。

## 6. 固定 workload

四个 workload 都从临时正式产物启动，cwd 固定为仓库根：

| 名称 | 命令形状 | 必须观察到的角色 |
|---|---|---|
| `jvm_build_fib` | release JAR build `examples/basics/fib.dawn` | `compiler` |
| `native_build_fib` | native compiler build 同一文件 | `native_compiler` |
| `test_stdlib` | release JAR `test --stdlib` | `compiler`, `test_main` |
| `test_selfhost` | release JAR `test selfhost` | `compiler`, `dependency_reexec`, `test_main` |

每个重量样本都必须看到预期角色同时存在的完整快照。角色缺失、重复、`jcmd` attach 失败、
指标缺失、命令失败或没有完整重叠快照都会使整轮无效，不会留下部分 baseline。

## 7. Linux 进程测量口径

采样周期目标为 2 ms。身份使用 `(pid, /proc/<pid>/stat starttime)`，避免 PID 重用把另一个进程
接进同一棵树。每个时点从当前根递归遍历全部后代：

- 进程树 RSS 是 `max_t(sum(VmRSS_i(t)))`。
- 单角色 RSS 是该角色进程的 `VmHWM`。
- 单角色 VAS 是该角色进程的 `VmPeak`，不跨进程求和。
- Java 角色的最大堆来自同一 JDK 的 `jcmd <pid> VM.flags` 中实际 `MaxHeapSize`。
- native 角色的最大堆字段为 JSON `null`。

RSS 总和只采用所有树内进程都成功读取 `VmRSS` 的时点。任何 sibling 都不属于根的后代，不能
进入总和或角色集合。读取一次 stat 身份后，status 与 cmdline 的读取前后都要重新确认同一个
`(pid,starttime)`；`jcmd` 返回后也要复核。任何采样异常、取消或非零命令退出都会终止并等待整个
被测进程组，正常成功的命令不发送终止信号。

## 8. 启动时间

启动时间分别测 direct release JAR、临时 deployment 形态的 `bin/dawn` 和 native compiler。
三者先各跑一次 warm-up，再保存 11 个 `perf_counter_ns` 原始样本与中位数。
native CLI 的版本子命令实际拼写是 `version`，JAR 与 shell launcher 使用 `--version`。
direct JAR 与 `bin/dawn` 都使用 preflight 解析出的同一 JDK。入口拒绝外部 `JAVA_HOME`，随后只在
测量子进程环境中设置经过路径一致性验证的 `JAVA_HOME`。

临时 deployment launcher 由当前 `bin/dawn` 和正式 release JAR 组成，故不会信任仓库 ignored
的 `build/dawn-selfhost.jar`，也不会触发源码重建。

## 9. JSON baseline

baseline 顶层固定记录 schema、recorded time、source commit、platform/JDK/locale、seed tag 与实际 digest、
参数、产物、自举原始样本、四项 workload 原始样本和三项启动原始样本。reader 执行以下规则：

- duplicate key、未知字段、缺字段一律拒绝。
- `NaN`、`Infinity`、bool 冒充整数、零值、负值和零分母一律拒绝。
- workload 名、角色名、样本数必须与 schema 和参数完全一致。
- 所有 median、ratio 和 spread 都从原始样本重算并逐项核对，不能只信 summary。
- 记录使用 UTF-8、稳定 key 顺序、末尾换行，同目录临时文件、文件 fsync、原子 rename 和目录 fsync。

baseline 不记录 hostname、用户名或绝对工作区路径。

## 10. spread 与裁决

bootstrap ratio 的 spread 定义为：

```text
(max(ratio) - min(ratio)) / median(ratio)
```

恰好 15% 已经是 inconclusive。入口最多重试三轮，每轮都完整保存并打印 ratio 原始样本和 spread。
三轮都 inconclusive 时退出 3，不写 baseline，也不报告 PASS 或 FAIL。

`--check` 唯一预算是：当前 bootstrap median ratio 不得超过 baseline ratio 的 115%。
RSS、VAS、产物大小、启动时间和绝对 wall time 在 Phase 1 都只是 telemetry。它们保存 raw sample
与 median，但没有阈值，也不会借用 15% 发明预算。

## 11. 机器契约与负控

`scripts/selfhost-bench-contract/HeapTree.java` 生成 parent 到 child 到 grandchild，并由 Python
harness 另起无关 sibling。parent 和 grandchild 显式使用 64 MiB 堆，child 与 sibling 使用
96 MiB。契约验证递归包含 grandchild、排除 sibling，并通过同 JDK `jcmd` 读取真实堆值。

十一个独立 source mutant 每次都运行完整 assertion 集：

| mutant | 唯一红项 | control |
|---|---|---|
| `descendants-one-hop` | `bench.descendants_recursive` | `bench.heap_exact` |
| `heap-parser-off-by-one` | `bench.heap_exact` | `bench.descendants_recursive` |
| `tree-rss-last-only` | `bench.tree_rss_sums_simultaneous` | `bench.overlap_requires_all_roles` |
| `overlap-any-role` | `bench.overlap_requires_all_roles` | `bench.tree_rss_sums_simultaneous` |
| `sampling-200ms` | `bench.sampling_targets_two_ms` | `bench.starttime_identity_preserved` |
| `starttime-constant` | `bench.starttime_identity_preserved` | `bench.vmhwm_reads_proc` |
| `vmhwm-constant` | `bench.vmhwm_reads_proc` | `bench.sampling_targets_two_ms` |
| `skip-exception-cleanup` | `bench.exception_cleanup` | `bench.descendants_recursive` |
| `skip-post-cmdline-identity` | `bench.identity_rechecks` | `bench.same_jdk` |
| `allow-inherited-java-home` | `bench.same_jdk` | `bench.final_source_snapshot` |
| `snapshot-fail-open` | `bench.final_source_snapshot` | `bench.identity_rechecks` |

mutator 的可执行 key 直接来自 `mutate.py --list`，运行时必须与 matrix membership 完全相等，
不维护第二份 key 注册表。matrix 的 role、owner、red、control 全部由严格 parser 消费。未知、
重复、缺失、改 owner，以及新增 mutator 但遗漏 matrix 都必须 fail closed。schema 的表驱动负例
覆盖 duplicate key、未知字段、缺字段、非有限数、零负数、零分母、冲突模式、缺参数值、偶数
样本和恰好 15% 噪声。

完整 assertion 集还覆盖 status、cmdline 和 `jcmd` 前后的身份变化，伪造 `JAVA_HOME`，采样异常
与非零退出后的子进程清理，以及测量后 tracked、untracked、HEAD 三类 source snapshot 漂移。
snapshot assertion 只构造临时 Git 仓库，不执行正式构建。这三条规则各自有修改生产路径的唯一
source mutant 与 owner，不是只在正常实现上运行的正向 probe。

CI 只运行 schema、synthetic `/proc` probe 与 mutant matrix，不运行 release 构建、硬件 record
或硬件 check。

## 12. 不做的事项

- 不在 CI 比较机器重量。共享 runner 的噪声与硬件差异不适合作为 Phase 1 oracle。
- 不给 telemetry 设置预算。没有历史序列与重测证据时，任何数字都只是猜测。
- 不把临时 768 MiB 当产品上限。它只证明堆策略有显著影响。
- 不把三台 JVM 的总 RSS 归因成编译器单进程泄漏。
- 不改 512 MiB stack。既有勘测已排除它是当前 RSS 主因。
- 不压缩 release JAR，不 strip native，不改 static link。这些是独立的发布与兼容性决策。
