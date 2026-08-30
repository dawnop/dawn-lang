# 2026-08-30 WSL2 slab residency results

本目录保存 #10 裁决使用的原始 TSV，不把性能数字变成 CI 阈值。三轮都来自同一台
Ubuntu 24.04.4 / WSL2 worker、同一个 `dawn 0.69.0 (selfhost)` 与 GCC 13.3.0；环境、输入与
build 字节标识见各自 `environment.tsv`、`corpus-files.tsv` 与 `builds.tsv`。三轮之间**不**共享
什么，见下面一节。

- `primary/`：eager/candidate/glibc/mimalloc 四变体主矩阵，1 warm-up + 5 sample。
- `exact-contended/`：四变体复跑。compiler 样本出现机器范围的 9.1–23.7 秒抖动，
  glibc 中位数由约 11.5 秒涨到 19.4 秒，因此保留原始证据但不用于 wall 裁决。
- `paired-exact/`：只比较 eager/candidate，1 warm-up + 8 sample；两个变体在轮内每个
  位置各出现四次，用于解决上一轮的不一致。

## 三轮之间不共享什么

这不是同一份输入的三次重复。差别都能从本目录的 TSV 里直接读出来：

- **candidate 源三轮并不相同，而且都不是仓库里的最终源码。** `builds.tsv` 的
  `runtime_c_md5`：`primary` 是 `814029ab911960b5c4e3cd41ca9da0c2`，`exact-contended` 与
  `paired-exact` 是 `93d224d12db0d2a65f8512f3c14656b0`，落地进仓库的
  `runtime/c/dawn_rt.c` 则是 `853cd7b1352342eec8617b9b0a3f83e3`。所以 `paired-exact`
  不是“最终源码的平衡复测”，三轮都不是最终源码；最终源码只在评审的复测里跑过，那次
  复测没有归档在这里。eager 一侧三轮一致，都是 `9b7f124cb7a6f5470c13de65155d5565`，
  即本刀之前的 `dawn_rt.c`。
- **corpus 三轮也不相同。** `environment.tsv` 的 `corpus_tree_md5` 在 `primary` 是
  `30417bfc7646e976b28dd6b306a2ecb7`，另两轮是 `58a61e96f2d32e3102f74c90a3bee064`。
  按 `corpus-files.tsv` 逐文件比，130 个文件里只有 `selfhost/src/embed/rtsrc.dawn` 不同
  （196,685 与 196,705 bytes）：那是嵌入的 runtime 源，随 candidate 一起变，所以这条与
  上一条是同一件事的两面。lexer 语料本身（`selfhost/src/front/lexer.dawn`，
  `lexer_corpus_md5` 恒为 `80ce0a65946970f2d3ed505db68d626a`）三轮相同。corpus 与两份
  runtime 都是按目录传进 runner 的（`corpus_source_kind = directory`），不是 Git ref，
  所以这里没有可核对的 commit。
- **仓库里这份 `run.py` 没有跑过任何一轮。** `runner_md5` 在 `primary` 是
  `e01260aa10aa4c0d5aee15e3e62e88c0`、另两轮是 `97ffce421c31b0163048819ef1d7fd62`，
  而归档进 Git 的 `scripts/slab-bench/run.py` 是 `764619a4bda649468db8f328bf3ca1b6`。
  `runner_md5` 记录的是当时实际执行的 runner，不是归档时的当前文件；照这份仓库版本重跑，
  得到的会是第四种 runner 身份。

“三轮 candidate runtime object 的 MD5 都是 `2ea2ecdd5615af85b17874f3706eeedf`”这条记录
留在这里，但要标明出处：它来自当时运行的日志，`builds.tsv` 没有 runtime object 这一列，
因此它不能从本目录重新导出。MD5 在这里一律只作字节身份标签，不作真实性声明。

所有运行的 workload checksum 分别恒为：lexer `938400`、rbtree `2422197960096`、
compiler `15669348`。

归档入 Git 时仅把 `environment.tsv` 的空 value 规范成 `not-applicable`，避免 TSV 行尾 tab。
