# `Array` 契约测试

`Array[T]` 是后端唯一要实现的集合原语（[native-backend-plan](../../docs/native-backend-plan.md) D1）。
它**不是语言表面的一部分**：只有 std 模块能写 `Array`、能调 `array_*`，用户代码里 `Array` 仍然是
一个普通名字。所以这套测试不能放 `examples/`——`run.sh` 把 `array.dawn` 拷进一份 std/ 的副本，
再拿 `probe.dawn` 对着它编译。

```bash
./scripts/array-contract/run.sh
```

## 它验两件事

**一、值语义。** 每个操作都返回新数组，没有一个是可观测破坏性的。最关键的一格是 `fork`：
两次 push 落在同一个版本上，两个结果必须各看到自己的元素——一个赢了 CAS，另一个复制。

**二、`array_push` 在独占时就地延长。** 这一条**故意从 Dawn 里观测不到**（能观测就不是纯值语义了），
所以只能拿时钟量：累积形状有它是 O(n)、没它是 O(n²)。在这里的规模上，就是 10 毫秒对一分钟。
`run.sh` 因此给 20 万次 linear push 设了 3 秒预算——快路径实测 ~14ms，慢路径实测外推 ~67s，
两边各差一到两个数量级，不是在赌竞态。

对照数（本机）：**20 万次 linear 14ms vs 2 万次 forked 666ms**。注意两个 n 差 10 倍还是这个结果，
因为 forked 那条是 O(n²)。

## 为什么这个不对称是设计而不是缺陷

`array_with` 永远复制，`array_push` 才有快路径。因为槽位 `i < len` 已经交给这个版本、也可能交给
了别人，没有任何水位线能判断还有谁在读它；而 `push` 写的是**从没交出去过**的那一格。JVM 上除此
之外没有唯一性信息可用，native 上 Perceus 的 `rc==1` 才能覆盖 `with`。

实测说这个代价付得起：编译器的追加里 99.1% 命中 owned-tail 快路径
（[collections-dejava-research](../../docs/collections-dejava-research.md) §9.5），12 倍差距整个落在 push 这条路上。
