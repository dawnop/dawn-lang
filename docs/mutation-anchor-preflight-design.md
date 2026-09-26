# 变异锚点预飞

> 状态：**current**。issue #92 的源码锚点预飞。

`python3 scripts/mutation-anchor-preflight.py` 在任何编译器构建之前检查变异能否落地。
它以内存中的文件写入执行现有的源码变异器，保留它们的恰好一次匹配检查、次级编辑、
插桩与顺序替换，不另外维护一份锚点文本。首次本机运行检查了 198 次变异应用/定位，耗时 5.38 秒。

适配器只描述调用路径。mode 从字面量 `MUTATIONS` 键与显式的 name/mutation 分派比较中发现。
`scripts/**/mutate.py` 的清单必须与适配器和显式排除项一致；新增变异器而没有适配器即失败。
两个 shell 契约适配器抽取其中现有的变异 Python 块，不执行外围的 shell。
Java classpath 的 bracket 变异体先接受其现有插桩。嵌入式标准库损坏探针与具名的标准库变异分开检查，
gate-map 的 record 编辑也保留其源码锚点。

gate-map 的编辑应用在它自己的基线文本上，不逐个运行变异后的覆盖图。其现有的基数契约仍然是权威：
单次替换要求恰好一处匹配；有意的全局替换要求至少一处；文件新增与追加类对照保留各自的前置条件。
bundled-module 表达式按恰好一次检查。builtin-declaration 读取器检查真实的 `comptime_rejects`
循环拼写，不产出编译器制品。

有两个助手不持有检出源码的锚点：classfile-verify 变异的是生成的字节码，tile-gpu-diff
的替换文本全部由调用方提供。二者的排除是显式的并会打印出来，不会被默默当作源码覆盖。
issue 点名范围之外的内联变异 harness 与文档引文不在本检查覆盖之内。现有的可执行语义契约仍然必须跑：
能落地不等于变异体能编译、也不等于它能检出所针对的缺陷。

`self-once` 的 harness（`scripts/anchor-readers.txt` 里的那一类）只在自己运行时才拒绝失配的锚点，
对构建很重的契约来说，这等于只有有人去跑它时才会发现。issue #249 就是这种情况：#248 改写了
`runtime/c/dawn_rt.c` 里的 `dawn_cpath`，本预飞报 OK，delete 契约在第一次本机运行时才红。
出路是把 harness 的锚点搬进一个 `mutate.py` 登记表，由 harness 与本预飞共同消费，而不是把字面量复制进适配器。
`scripts/delete-contract/mutate.py` 是第一个；其余 `self-once` harness 在同样迁移之前仍不在覆盖之内。
在引入它的那棵树上本机实测：应用次数 204 到 213，墙钟 12.9 s 到 13.2 s。

CI 在 tree-policy 中运行预飞及其负控，不需要 JDK。负控覆盖：纯拼写漂移、重复锚点、次级编辑、
shell 锚点、未知变异器、顺序插桩，以及拒绝启动构建或直接写盘。每个测试之后检出必须保持不变。
