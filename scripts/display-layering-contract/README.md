# display layering contract

这个 contract 固定 `Display` 与 `Show` 的分层，两条规则各配一个 mutant
（实现在 `selfhost/src/ir/lower.dawn` 的 `to_str`）：

- `display_wins_over_show`：有 `Display` impl 时，顶层渲染由它决定，顶掉这个值原本会走的
  那份 `Show`。三种情形都在里面：从 opaque 目标继承来的（`Char` 继承 `Int` 的）、类型自己
  写的（`Tag` 同时有 `Show` 和 `Display`）、以及 `String` 恒等（`Inner` 是 `String` 上的
  opaque type）。
- `display_is_asked_at_every_peel_layer`：opaque 栈是逐层剥的，每层都重新问一次，而不是只
  在「写下来的那个类型」上问一次。探针里的 impl 在两层和三层之下，上面几层都没有自己的
  `Display`。
- `show_stays_the_nested_rendering` 是 control：`Display` 只管顶层，两个 mutant 都不许动它。
  容器/记录/元组里的值仍走 `Show`，`[T: Show]` 约束下的值仍走它的 witness（`${x}` 在
  `render[T: Show]` 里对 `Char` 仍出 `97`，这条不是 `Display` 带来的，见 spec §4.3）。

两个 mutant：

- `drop-display-question` 整段删掉 `to_str` 顶部的 `has_own_display` 问询。
- `ask-display-once` 只在「写下来的那个类型」上问一次：opaque 臂改成递归进一个没有
  `Display` 问询的 `to_str` 副本。这正是设计里被否掉的形状（把问询放进 opaque 臂而不是它
  上面）。它**不碰** `Show` 的逐层剥法，所以 SEM-03 那条不受影响，红的只有本条。

两个 mutant 都必须完整 build、`--version` 输出一行合法的 `dawn ...`，才计入矩阵。
`matrix.txt` 的 role、owner、red、control 由 `matrix_check.py` 严格读取：字段撒谎、重复、
缺失、未知 record、两个 mutant 红集相同、owner 被更窄的 mutant 抢走，都由自测拒绝。
owner 的定义是「把这条 assertion 弄红的 mutant 里红集最小的那个」，所以
`drop-display-question` 把两条都弄红也不会让它冒领第二条。

探针输出是 `<label>\t<渲染>` 每行一条，`probe_check.py` 是唯一说明「哪个 label 归哪条
assertion」的地方。之所以不做整文件 `cmp`：本 harness 的全部意义是两个 mutant 弄红**不同**
的 assertion，而一次整文件比对分不出它们。`probe_check.py --self-test` 逐条扰动每个观察点，
要求它只弄红宣称拥有它的那条 assertion。

**只跑 JVM，是有意的。** 两条规则都在共享 Core 里，两个后端会在同一个错答案上达成一致，
互比在这里什么也不证明；双后端那份判据是 `scripts/spike-native/display_layers.dawn`
（同样的话，不带 label，两个后端各编一遍再各自比手写 expectation）。

```bash
./scripts/display-layering-contract/run.sh
```
