# 生产准入裁决（2026-08-30）

`2026-08-30-production.tsv` 是首次生产暴露前在真机上跑的资源矩阵
（`lsp-measure.py --iterations 10`，10 例 × 10 轮全 ok，dawnc 0.70.0，
harness 82b1f65）。按 [playground-lsp-design.md](../../../docs/playground-lsp-design.md)
§7 的公式套生产数：

- 最坏形状 = `source-64k / exact-valid-65536-bytes`，峰值 RSS p95 = 31,720 KiB；
- R = p95 × 1.25 ≈ 38.7 MiB；B = `dawn-play-lsp.slice` 的 512 MiB；
- floor(B / R) = **13**。

**裁决：准入上限维持 2**（`PLAY_LSP_MAX_SESSIONS=2`，2 ≤ 13，余量约 6 倍）。
2 不再是占位符，是有生产测量背书的保守值；要提额时以本文件与 TSV 为基线重算。
