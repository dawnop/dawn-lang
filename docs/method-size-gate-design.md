# 方法尺寸门禁：编译器里没有 JIT 不肯编的方法

> 状态：**current**。2026-09-26，issue #241 第 2、3 条（分支 `fix/huge-methods-2`）；第 1 条
> （`execute_module_bodies`）是刀 1，记在 [symbol-id-design.md](symbol-id-design.md) §3.2 末尾。

## 问题

HotSpot 的编译策略对 `code_length` 超过 `HugeMethodLimit`（8000 字节，develop 旗标，产品 JVM 改不了）的方法
一律不编（`compilationPolicy.cpp` 的 `can_be_compiled`，OSR 也走它），C1、C2、作为 JVMCI 编译器的 Graal 都一样。
超限的方法在整个进程生命期里解释执行。`origin/main` 上检查器的三个核心方法都超了：`check_call` 10015、
`check_expr_at` 9334、`check_stmt` 8719，另有 `check/passes.pass_register_impls` 11991 与 LSP 一个测试闭包
`lsp/server.lambda$29` 9177（数字是 jar 里 Code 属性的 `code_length`，比 `javap` 最后一条指令偏移大 1）。
issue 实测 bench-replay 稳态冷检因此慢 20% 到 27%。

## 裁决

拆源码，不改 JVM 默认参数；按规则守，不按名单或计数守。调研与裁决理由见 issue #241 的裁决评论
（改旗标的一次性进程实测无收益、CPU 与 RSS 变差、覆盖不到直调 jar 的脚本与 native-image）。

## 怎么拆

每刀只搬家，不改逻辑：抽出的函数以同一个 `Cx` 进、同一个 `Cx` 出，诊断追加顺序由调用顺序决定，搬家不改顺序。
被搬走的分支里的提前 `return` 变成新函数的 `return`，意义相同（分支的值就是调用的值）。

| 原方法 | 拆出 | 切口理由 |
|---|---|---|
| `check_expr_at` | `check_str_lit` `check_if` `check_list_lit` `check_tuple_lit` `check_index` `check_return` `check_comptime` `check_field_expr` | 八个仍内联的 match 臂整臂搬出，只读本节点字段与期望类型；其余臂本来就是一行委派 |
| `check_stmt` | `check_let` `check_let_pat` `check_assign` `check_while` `check_for` | 语句臂只读自己的字段；循环栈的压入弹出、`for` 的作用域都在臂内成对 |
| `check_call` | `check_local_value_call` `call_arg_slots` `infer_call_args` | 局部函数值分支每条出口本来都是 `return`；参数槽分配只读签名与实参；两轮推断是唯一扩充替换的地方，改动的 `Cx`、`m`、`em`、两张槽表显式返回 |
| `pass_register_impls` | `register_derived_impls` `impl_member_bindings` `impl_method_sigs` `report_missing_methods` | derive 在前、关联类型/效果绑定、逐方法签名核对（最大的一段，也是唯一按方法循环的一段）、缺方法报告；每个 impl 的头部（作用域、主体、孤儿规则、一致性）连同它的 `continue` 留在原处 |
| LSP 测试闭包 | 三个局部函数：库修订循环、失败后重试、激活失败与拆除 | 测试闭包被提升为 `lambda$N`，名字只有位置，门禁分不出它是测试代码（见下「门禁规则」），所以同样拆 |

拆后各方法字节数见分支提交正文；最大的是 `check_call` 5689，全部低于 6000 的目标（C1 在 6568 字节的
`check_ctor_call` 上出现过虚拟寄存器 bailout，所以留余量）。

## 门禁规则

`scripts/method-size-gate.py`：直接用 struct 读 jar 里每个 class 的 Code 属性 `code_length`，不起 JVM、
不调 javap、不用 ASM（与 `constpool-scan.py` 同理：用发射器自己的库检查发射器会在库错的地方失明）。
规则：jar 里每个方法 `code_length` ≤ 8000，例外三类：

- `embed/` 下的类（生成的 Unicode 表，类初始化时跑一次）；改报它们离 JVM 硬限 65535 的距离，因为那条是致命的；
- test 块 `dawn$test$N`，每次 `dawn test` 跑一次；
- 构建时 vendored 进来的 Java 包（ASM、coursier interface）。哪些包从 `bin/dawn` 与
  `scripts/build-release-jar.sh` 的 `--vendor` 参数读，所以豁免就是构建自己对「拷进来了什么」的陈述，不会与之漂移。
  不用 `SourceFile` 属性判断：coursierapi 里 shaded 的 jsoniter 类没有这个属性，和 Dawn 发射的类一样，
  而 `JsonWriter$.<clinit>` 有 16217 字节。

不留名单、不记计数：`lambda$N` 按位置编号，上方任何无关改动都会让名字漂移，按名字记的名单或计数会在不相干的
提交上抖动。本刀把全部超限方法拆完，规则直接成立，树里没有基线文件。

`--selftest` 在内存里造 class 文件逐条覆盖规则（恰好 8000 过、8001 红、提升闭包红、包里的类红、`embed/` 过、
包路径下的 `embed/` 过、test 块过、形似 test 块的名字红、vendored 类过、vendored 包名不是前缀、`.java` 的
`SourceFile` 不豁免、`check/embed` 不算 `embed/`），再对真 jar 做阈值变异：阈值设成最大受检方法减一必须红、
等于它必须过，读不到方法的读取器会在别的用例上全过，这一条会红。另核对两份配方 vendor 的每个包在 jar 里都有类。

位置：`test-programs` 末尾（规划值 442 s）。它是已经构建 selfhost jar、且不叫 `incremental*` 的最便宜 job：
更便宜的 `incremental-3-2`（405 s）试过，`sweep.sh` 把 `incremental*` job 的每一步都当语义 harness 跑，
见到别的命令就拒绝整个计划，所以不能放那里。`test-programs` 前面的步骤只读或软链 `build/dawn-selfhost.jar`，不改写它。本机两行合计 2.0 s（真 jar 连 vendored 共 43258 个方法，其中自检 1.2 s；
调研的 0.23 s 是只扫 Dawn 类的探针），在该 job 的余量内，不重述预算。

## 性能

2026-09-26 实测，三个 bench-replay jar（`e7880d1c`、`origin/main` `51c8dfbd` 即刀 1 之后、本分支）由各自树的
`bench-replay.py` 构建，逐轮交错、5 轮，每轮每个 jar 一个新 JVM，`java -Xss64m -Xmx2g -XX:+UseSerialGC -jar X <mode> <class> 1000 30`
去前 12 轮取中位数，再取 5 轮中位数（ms/1000 体）。下表是集群单机（256 核，负载 1 到 3，OpenJDK 21.0.7，顶层 C2）的数；
本机（GraalVM CE 21.0.2，顶层 Graal JIT）同表同协议也跑了，但同时有别的会话，负载 4 到 31，个别轮慢 3 倍，只作方向参考。

| class | mode | e7880d1c | 刀 1 后 | 本刀 | 本刀/刀 1 后 | 本刀/e7880d1c |
|---|---|---:|---:|---:|---:|---:|
| calls | cold | 43.14 | 43.15 | 20.05 | 0.465 | 0.465 |
| calls | record | 164.89 | 162.76 | 130.19 | 0.800 | 0.790 |
| calls | replay | 32.98 | 33.01 | 33.07 | 1.002 | 1.003 |
| calls | renew | 46.18 | 46.45 | 48.45 | 1.043 | 1.049 |
| primitive_inferred | cold | 14.13 | 15.92 | 12.05 | 0.757 | 0.852 |
| primitive_inferred | record | 139.86 | 128.00 | 120.60 | 0.942 | 0.862 |
| primitive_inferred | replay | 17.75 | 20.34 | 20.32 | 0.999 | 1.145 |
| primitive_inferred | renew | 27.47 | 28.33 | 28.60 | 1.009 | 1.041 |
| generic | cold | 66.17 | 66.09 | 29.32 | 0.444 | 0.443 |
| generic | record | 199.59 | 196.25 | 146.97 | 0.749 | 0.736 |
| generic | replay | 64.29 | 66.51 | 65.03 | 0.978 | 1.011 |
| generic | renew | 86.80 | 88.25 | 87.64 | 0.993 | 1.010 |
| inferred | cold | 48.71 | 52.35 | 37.63 | 0.719 | 0.773 |
| inferred | record | 177.86 | 183.31 | 158.16 | 0.863 | 0.889 |
| inferred | replay | 57.18 | 61.34 | 45.79 | 0.747 | 0.801 |
| inferred | renew | 200.99 | 206.65 | 186.89 | 0.904 | 0.930 |

读法：会真正检查函数体的模式（cold、record）全部变快，cold 快 24% 到 56%，record 快 6% 到 25%；
只装回产品的 replay、renew 基本不走这几个方法，在 ±5% 内（inferred replay 快 25% 是例外，原因没有单独测）。
刀 1 报告里 inferred cold 相对 `e7880d1c` 还剩的约 7% 已收回并反超（0.773）。primitive_inferred replay 比 `e7880d1c`
慢 14.5%，刀 1 后已是 1.146，本刀未动它（0.999），来源在刀 1 报告列的 S2/S3 每体簿记，不在本刀范围。

一次性 `dawn check selfhost`（`java -Xss512m -Xmx2g -XX:+UseSerialGC -jar X check selfhost`，6 轮交错去首轮，`os.wait4` 取 CPU）：
集群墙钟 7.01 → 6.73 s（−4%），CPU 17.98 → 18.67 s（+4%，多出来的是 JIT 线程编这些方法的工作），峰值 RSS 1050 → 1100 MB；
本机墙钟 15.69 → 14.21 s、CPU 43.81 → 42.89 s，负载 8 到 10，离散大。调研预测「一次性进程也会受益」，墙钟上看到约 4%，
在离散边缘，不作定论。

## 不做的（理由）

- **不加 `-XX:-DontCompileHugeMethods`**：见裁决；而且即使加了，C1 也在这几个方法上放弃。
- **不在 codegen 里自动拆方法**：这些是人写的源码，自动拆会让字节码与源码结构脱节，`Method too large` 的报错定位变差。
- **不把阈值定成 6000**：C1 的寄存器墙只有一个观测点，没有系统数据；6000 只作拆分目标，不进门禁。
- **不从门禁里豁免测试闭包**：要识别闭包属于哪个 test 块，得解码字节码找调用点，读取器复杂度翻几倍；
  目前只有一个测试闭包超过，拆掉比豁免便宜。若以后测试闭包频繁撞线再议。
- **不拆 6000 到 8000 之间的方法**（`lsp/server.lambda$20` 7171、`lsp/lspq.walk_e` 7051 等 10 个）：规则允许，且没有数据说它们热；留作下一批候选。
