# range `for` 边界求值顺序设计

> 状态：**current**。本文记录 SEM-18 的语言契约、共享 Core 修复与可执行负控。

## 1. 问题

range `for` 的 lowering 已经按源码顺序处理 `from` 和 `to`，但旧实现生成的
`CSLet` 列表先绑定上界、再绑定下界。Core statement list 才是运行时顺序，因此
`for x in lower()..upper()` 在 JVM 与 native 上都稳定地先执行 `upper()`。

两个后端共享同一份错误 Core，普通差分只能证明它们同错。规范也只写了右开区间，
没有规定两端何时、按什么顺序求值。

## 2. 语言契约

对 `for x in a..b`：

- 先求值 `a`，再求值 `b`。
- 两端各求值恰好一次。
- 两端都在进入循环前求值，空区间也不例外。

这与函数实参和二元运算符的左到右求值原则一致，不引入 range 专属例外。

## 3. 实现

修复只交换 range lowering 生成的两个 `CSLet`：先把 `lo_v` 绑定到循环变量，
再把 `hi_v` 绑定到隐藏上界符号。下界与上界仍各 lower 一次，归纳变量、循环测试、
body 和 step 的形状都不变。JVM 与 native 继续直接消费同一份 Core，无后端补丁。

## 4. 可执行契约

`scripts/spike-native/eval_order.dawn` 的手写 expectation 覆盖空区间与非空区间：
两端都有可观察副作用，空区间仍打印两端且不执行 body，非空区间打印两端后执行
三轮 body 并累计出 `234`。既有第一行 oracle 保持不变。

`scripts/range-bound-order-contract/` 对真实编译器和 compiling mutant 运行同一组断言：

- owner 同时要求 Core 中下界 `CSLet` 位于上界之前，并要求 JVM/native 精确匹配手写输出。
- control 只读 Core，要求四个 bound call 各出现一次且位于对应 loop 之前，不依赖运行期输出。
- 唯一 mutant 精确恢复 upper-first 的 `CSLet` 列表；它必须完整 build、回答单行
  `dawn --version`，且只能把 hand-owned owner 变红。
- matrix 的 role、owner、red、control 都由严格 parser 读取；字段撒谎、重复、缺失和未知
  record 均由自测拒绝。

## 5. 不做

- 不修改 iterable `for`。它没有第二个 bound，属于 SYN-13 的后续 pattern 工作。
- 不改变 range 的右开、步长或溢出语义。
- 不在 JVM 或 native emitter 重排语句。执行顺序由共享 Core 唯一表达。
- 不依赖两后端互比作为正确性 oracle。绝对 expectation 与 Core 结构分别固定行为和形状。
