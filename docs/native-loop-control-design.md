# native 源码循环跳转目标修复

> 状态：**current**。本文记录 native RC pass 对源码循环与 match 一次性循环的区分，
> 以及防止具名 `break`、`continue` 在转换后失去目标的最小修复。

## 1. 问题

Core 用 `CSLoop(loop_id, ...)` 声明循环，用 `CBreak(loop_id)` 和
`CContinue(loop_id)` 指向它。JVM 后端直接消费这份 Core；native 在发 C 之前还会经过
Perceus RC pass。

RC 的 `unloop` 会把 lowering 为一次性循环的 `match` 还原成分支树，让各臂按普通分支
完成所有权协调。旧判定把任何“若干尾部 break 分支，加一个发散终止语句”的循环都当成
该形状。普通 `while` 和 range `for` 恰好也以条件失败的 `break` 开头；用户 body 若是
无条件 `break` 或 `continue`，它们会被误拆成 `CSIf`，用户跳转保留，声明目标的
`CSLoop` 却消失。

C emitter 因而写出 `goto Lx_end` 或 `goto Lx_step`，却没有对应标签。JVM 不经过 RC，
所以同一合法程序在 JVM 正常运行，在 native 的 C 编译阶段失败。

iterable `for` 没有暴露问题，只因为条件与 body 之间还有一个迭代项 `CSLet`，使它没有
匹配旧形状。这是偶然，不是契约。

## 2. 修复

`unloop` 仍要求最后一条语句发散，同时新增一条必要条件：最后一条语句不能含有指向当前
loop id 的 `break` 或 `continue`。实现复用已有 `jumps` walker：

```dawn
CSDiscard(x) -> not yields(x) && not jumps(x, lid, true, true)
```

这条检查会递归进入 block、if 与嵌套 loop。match 的终止语句是 lowering 生成的
`panic("unreachable match")`，不含循环跳转，所以一次性循环优化保持不变。

## 3. 可执行契约

`scripts/spike-native/source_loop_targets.dawn` 同时经过 JVM 与 native，覆盖：

- range `for` 的直接 `break` 与直接 `continue`；
- iterable `for` 的直接 `break`，作为既有安全形状的控制；
- `while` 与 `while true` 的直接 `break`；
- 嵌套 range 与 `while true` 的两层跳转目标；
- 条件 `break`，作为旧语料已有形状的控制。

`scripts/source-loop-label-contract/run.sh` 另编译一个不会执行的 `while true { continue }`
函数，固定 `Lx_step` 目标；并通过 RC 后 Core 固定 match 一次性循环仍被拆成 `CSIf`。

唯一 compiling mutant 删除新加的终止跳转防护。它必须先成功构建，且 `--version` 输出
单行 `dawn ...`，然后运行与真实编译器相同的完整 assertion set。matrix 的 role、owner、
red、control 每个字段都由严格 preflight 读取，并由十个 parser mutant 固定拒绝边界。
其唯一 owner 是 `source_loop_target_is_retained`；`match_unloop_is_retained` 必须保持绿色。

## 4. 不做

- 不在 lowering 中加入虚假绑定。那会把 iterable `for` 的偶然形状变成协议。
- 不关闭 `unloop`。match 的所有权协调与原地更新收益依赖它。
- 不让 C emitter 合成缺失标签。离开循环后，后端没有可靠位置可放目标。
- 不给 `CSLoop` 增加 kind 字段。现有递归 jump walker 已足以区分这两个形状。
- 不修改语言规范。语言的循环语义没有变化，修的是 native pass 破坏 Core 结构的问题。
