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

tile-gpu-diff 不持有检出源码的锚点：它的替换文本全部由调用方提供。这条排除是显式的并会打印出来，
不会被默默当作源码覆盖。classfile-verify 改生成字节码的两个变异器叫 `athrow.py` 与 `privatise.py`，
不占 `mutate.py` 这个名字，所以不进清单；它的 `mutate.py` 是源码锚点登记表（见下）。
issue 点名范围之外的内联变异 harness 与文档引文不在本检查覆盖之内。现有的可执行语义契约仍然必须跑：
能落地不等于变异体能编译、也不等于它能检出所针对的缺陷。

`self-once` 的 harness（`scripts/anchor-readers.txt` 里的那一类）只在自己运行时才拒绝失配的锚点，
对构建很重的契约来说，这等于只有有人去跑它时才会发现。issue #249 就是这种情况：#248 改写了
`runtime/c/dawn_rt.c` 里的 `dawn_cpath`，本预飞报 OK，delete 契约在第一次本机运行时才红。
出路是把 harness 的锚点搬进一个 `mutate.py` 登记表，由 harness 与本预飞共同消费，而不是把字面量复制进适配器。
`scripts/delete-contract/mutate.py` 是第一个；在引入它的那棵树上本机实测：应用次数 204 到 213，墙钟 12.9 s 到 13.2 s。
#254 至今迁了八条契约，每条一个提交：

- classfile-verify：17 个变异体、20 条锚点，原先是 `run.sh` 里 `replace_never_once` 的参数；
- syntax-small：5 个变异体、6 条锚点，原先是 `run.sh` 里的 5 段 Python heredoc；
- inflate：6 个变异体、6 条锚点，原先是 `run.sh` 里 `mutate` 的参数；主题是 `packages/inflate/src/gzip.dawn`
  （#254 的表里写的 `dawn_rt.c` 与 `check/types.dawn` 分别是链接输入和语料输入，不是锚点主题）；
- narrow：3 个变异体、3 条锚点，原先是 `patch_std` 的参数，主题 `std/narrow.dawn`；
- java-narrowing：2 个变异体、4 条锚点，原先是 2 段 heredoc，主题 `check/checker.dawn` 与 `jvm/help.dawn`，
  路径相对 selfhost 根（适配器给 `selfhost`）；
- map-reuse：2 个变异体、2 条锚点，原先是 2 段 heredoc，主题 `c/rc.dawn` 与 `std/hamt.dawn`；
- atomic-write：15 个变异、16 条编辑，原先是 12 处 `patch_std`、1 段改 `runtime/c/dawn_rt.c` 的 heredoc、
  1 段改两处编译器调用点的 heredoc，主题 `std/io.dawn`、`dawn_rt.c`、`pkg/add.dawn`、`main.dawn`；
- wasm-dom 的 retained：2 个变异体、3 条锚点，原先是 `apply_exact_mutant` 的参数，主题 `std/reactor.dawn`。

登记表路径一律写仓库相对路径（java-narrowing 除外），harness 把私有树布局成同样的形状（例如 `<tree>/std`），
所以同一登记表既能作用于检出、也能作用于私有拷贝。迁完之后 `scripts/anchor-readers.txt` 是
20 条 `preflight`、5 条 `self-once`。迁移后仍命中读者规则的 harness（例如只为检查形状而读源码的
java-narrowing 形状门与 retained 的 seam 门）不持有变异锚点，记为 `not-anchor` 并写明理由。
其余 5 条 `self-once` harness 在同样迁移之前仍不在覆盖之内。

CI 在 tree-policy 中运行预飞及其负控，不需要 JDK。负控覆盖：纯拼写漂移、重复锚点、次级编辑、
shell 锚点、未知变异器、顺序插桩，以及拒绝启动构建或直接写盘。每个测试之后检出必须保持不变。
