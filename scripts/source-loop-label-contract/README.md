# source loop label contract

这个 contract 固定 native RC pass 不得删除仍被源码 `break` 或 `continue` 指向的
`CSLoop`。它对真实编译器和 compiling mutant 运行同一组 assertion：

- `source_loop_target_is_retained`：完整 JVM/native 语料可编译、可运行且符合手写输出，
  另一个 compile-only `while true { continue }` 固定 step 标签；
- `match_unloop_is_retained`：match lowering 的一次性循环在 RC 后仍被拆除。

唯一 mutant `drop-terminal-loop-jump-guard` 删除 `unloop` 终止语句上的 jump 检查。
它必须先构建，且 `--version` 必须输出单行 `dawn ...`，然后才计入矩阵。`matrix.txt`
的 role、owner、red、control 均由 `matrix_check.py` 严格读取；十个 parser mutant 固定
字段撒谎、重复、缺失和未知记录都被拒绝。矩阵要求该 mutant 只把
`source_loop_target_is_retained` 变红，control 必须保持绿色。

```bash
./scripts/source-loop-label-contract/run.sh
```
