# display layering contract

这个 contract 固定 `Display` 与 `Show` 的分层，两条规则各配一个 mutant
（实现在 `selfhost/src/ir/lower.dawn` 的 `to_str`）：

- `display_wins_over_show`：有 `Display` impl 时，顶层渲染由它决定，顶掉这个值原本会走的
  那份 `Show`。`Char`、`Tag`、`Inner` 三个 opaque 类型都同时写了自己的 `Show` 和 `Display`。
- `display_is_not_inherited`：`Display` 是类型自己的，不向下借。2026-09-24 起 opaque 类型
  不继承 target 的任何渲染（[builtin-privileges-design.md](../../docs/builtin-privileges-design.md)
  §4），所以没写 `Display` 的 opaque 类型走**自己的** `Show`，哪怕一层、两层之下有 `Display`。
  探针里 `Outer`/`Deep` 叠在 `Inner` 上，各写了一个标记式的 `Show`。
  这条取代了之前的「每个 peel 层都重新问一次」：那条规则的前提是 opaque 类型继承 target 的
  渲染，前提没了，peel 也就删了。
- `show_stays_the_nested_rendering` 是 control：`Display` 只管顶层，两个 mutant 都不许动它。
  容器/记录/元组里的值仍走 `Show`，`[T: Show]` 约束下的值仍走它的 witness（`${x}` 在
  `render[T: Show]` 里对 `Char` 仍出 `97`，这条不是 `Display` 带来的，见 spec §4.3）。

两个 mutant：

- `drop-display-question` 整段删掉 `to_str` 顶部的 `has_own_display` 问询。
- `inherit-display` 给 `to_str` 加回一条 opaque 臂：没有自己 `Display` 的 opaque 类型去
  下面各层找一个 `Display` 借用。这正是旧的 peel 语义，也是现在最可能写回来的错答案：值照样
  渲染得出来，只是不再是它自己 `Show` 说的那样。

两个 mutant 都必须完整 build、`--version` 输出一行合法的 `dawn ...`，才计入矩阵。
`matrix.txt` 的 role、owner、red、control 由 `matrix_check.py` 严格读取：字段撒谎、重复、
缺失、未知 record、两个 mutant 红集相同、owner 被更窄的 mutant 抢走，都由自测拒绝。
owner 的定义是「把这条 assertion 弄红的 mutant 里红集最小的那个」。两个 mutant 的红集
今天互不相交，各红一条。

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
