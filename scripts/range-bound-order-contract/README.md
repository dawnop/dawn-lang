# range bound order contract

这个 contract 固定 `for x in a..b` 的两层契约：共享 Core 必须先绑定下界、再绑定
上界；JVM 与 native 必须精确匹配手写 expectation，按同一顺序执行两端副作用。

它对真实编译器和 compiling mutant 运行同一组 assertion：

- `range_bound_order_is_lower_first` 是唯一 owner，同时核对 Core 的 `CSLet` 顺序、
  JVM 输出、native 输出与两后端 stderr/exit。
- `range_bounds_are_once_before_loop` 是不依赖动态输出的 control，只读 Core，要求四个
  bound call 各出现一次，且都在对应 loop 之前。

唯一 mutant `restore-upper-first` 精确恢复旧的 upper-first statement list。它必须完整
build，且 `--version` 输出一行合法的 `dawn ...`，然后才能计入矩阵。`matrix.txt` 的
role、owner、red、control 均由 `matrix_check.py` 严格读取；字段撒谎、重复、缺失和未知
record 都由自测拒绝。

```bash
./scripts/range-bound-order-contract/run.sh
```
