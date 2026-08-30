# 2026-08-30 WSL2 slab residency results

本目录保存 #10 裁决使用的原始 TSV，不把性能数字变成 CI 阈值。三轮都来自同一台
Ubuntu 24.04.4 / WSL2 worker、同一份 `78759444` corpus；环境、输入与 build 字节标识见各自
`environment.tsv`、`corpus-files.tsv` 与 `builds.tsv`。

- `primary/`：eager/candidate/glibc/mimalloc 四变体主矩阵，1 warm-up + 5 sample。
  candidate source 与最终版只差三处注释；编译出的 `runtime-candidate.o` 与最终版相同。
- `exact-contended/`：最终源码四变体复跑。compiler 样本出现机器范围的 9.1–23.7 秒抖动，
  glibc 中位数由约 11.5 秒涨到 19.4 秒，因此保留原始证据但不用于 wall 裁决。
- `paired-exact/`：最终源码只比较 eager/candidate，1 warm-up + 8 sample；两个变体在轮内每个
  位置各出现四次，用于解决上一轮的不一致。

三轮 candidate runtime object 的 MD5 都是 `2ea2ecdd5615af85b17874f3706eeedf`。
MD5 在这里仅作字节身份标签，不作真实性声明。所有运行的 workload checksum 分别恒为：
lexer `938400`、rbtree `2422197960096`、compiler `15669348`。

归档入 Git 时仅把 `environment.tsv` 的空 value 规范成 `not-applicable`，避免 TSV 行尾 tab；
各目录的 `runner_md5` 仍记录实际执行的 runner，而不是归档时的当前文件。
