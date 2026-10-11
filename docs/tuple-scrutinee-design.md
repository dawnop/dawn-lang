# tuple 字面量作 match scrutinee：按分量匹配

> 状态：**current**。已实现（`selfhost/src/ir/lower.dawn` 的 `lower_match`）。来源：
> research-koka-gap-20261011 §4.7 与 §6 第 6 项。

## 问题

`match (a, b) { ... }` 在 Core 里是 `CSLet(subj, CTuple([a, b]))`，之后每个分支对
`CTupleGet(subj, i)` 做测试。native 后端因此先 `dup` 两个操作数，`dawn_adt_new`
造一个 2 元组，匹配完再 `drop`；JVM 后端同样 `new` 一个元组对象。

实测（2026-10-11，clang-20 -O2，WSL2，负载 5 左右，交错、7 轮取最小）：

- `tuple_scrut` 微基准（1 亿次 `match (a, b)`，4 个分支）：1.178 s，
  同一函数写成嵌套 match 为 0.040 s。
- `deriv`（`match (n0, m0)` 三处）：2.329 s。`__emitc` 输出里 `adt_new` 出现 36 处。

## 做法

放在 lowering（TAST 到 Core），不另写 Core 上的 pass，所以 JVM 与 native 共用，
两个后端都不再分配元组：

1. scrutinee 是 `XTupleLit`，宽度 n >= 2 且与类型一致；
2. 每个分支的模式要么是同宽的 `TPTuple`，要么是 `TPWild`；
3. 满足则按书写顺序把 n 个分量各绑一个局部变量（求值顺序与原来
   `CTuple` 的参数顺序一致），每个分支对第 i 个分量局部变量测试第 i 个子模式，
   测试合取的顺序、短路与 or 模式的槽位处理沿用 `pat_test`，逐分量调用；
4. 任何一个分支是顶层 `TPBind`（整元组被绑名）、顶层 `TPOr`、宽度不符，
   就整体退回旧路径，元组照旧物化。

穷尽性、分支可达性诊断在 checker 里做，发生在 lowering 之前，不受影响。

## 为什么在 lowering 而不是 Core pass 或只在 native

- Core 上要从 `CSLet(s, CTuple)` 加一串 `CTupleGet(s, i)` 反推「元组没逃逸」，
  要扫整个分支体；lowering 时看的是 TAST 模式，「没有分支绑整元组」是一眼可判的局部事实。
- 放在 native 后端意味着 JVM 后端继续分配，而且 native 要在 C 层重新认这个形状。
- 局部变量交给既有的 Perceus 与槽分配处理：分量的所有权与原来 `CTupleGet`
  借出的语义相同，没有引入新的 Core 形状。

## 测量（改后）

同一台机器、同样交错 7 轮取最小：

| 基准 | 之前 | 之后 | 变化 |
|---|---|---|---|
| tuple_scrut（元组 scrutinee） | 1.178 s | 0.041 s | -96.5% |
| tuple_scrut（嵌套 match，对照） | 0.040 s | 0.041 s | +0.5%（噪声） |
| deriv（参数 10） | 2.329 s | 1.913 s | -17.9% |
| cfold（无元组 scrutinee，对照） | 0.282 s | 0.277 s | -1.9%（噪声） |
| native 编译器自编译（`dawnc emitc nmain`） | 9.105 s | 9.225 s | 噪声内；该源码里没有受影响的 match |

deriv 的 `adt_new` 从 36 处降到 28 处。研究报告估计 deriv 约 10%，实测更高。

## 测试

- `ir/lower` 内联测试：全部分支为元组模式/通配时，前两条语句是两个按序的分量绑定且
  无 `CTuple`；顶层绑名、顶层 or、宽度不符三种分支各自仍物化元组。
- 变异体：把 `tuple_scrut_parts` 的入口条件改成恒退回，上面的测试红
  （`assertion failed: false at src/ir/lower.dawn`）。

## 不做的（理由）

- **不处理顶层 or 模式 `(A, _) | (_, B)`**：要把 or 分发到分量上，或者保留元组；
  本次实测的热点（deriv）都是平铺分支，收益不值得多出的路径。
- **不处理 let 的元组解构、`let (a, b) = (x, y)`**：那条路径本来就走 `TSLetPat`，
  不是本次测到的热点。
- **不处理非字面量 scrutinee（函数返回的元组）**：元组必须存在，要省掉它是多值返回
  （research-value-repr 的 K3），范围不同。
- **不改穷尽性检查**：它在 lowering 之前完成，改了反而要重新证一遍诊断不变。
