# Perceus 复用：ADT/记录的 reset/reuse，与借用的模式绑定

> 状态：**current**（已裁决：七个开放问题于 2026-10-07 全部按推荐裁决，见 `agent-handoff/ruling-perceus-reuse-20261007.md` 与 §7.2；设计稿，未动码）。native 性能线刀 3。2026-10-07，基线 `origin/main` = 7d06b29c。
> 依据：`agent-handoff/research-value-repr-report-20261006.md`（update 链每步 5 次分配、复用 0，tree 的 `incr` 每节点一次分配；小对象一整圈约 4.5 到 5 ns）；
> `agent-handoff/native-iter-report-20261007.md` 与 PR #594（分支 `perf/native-iter-rc`，b11342f3，`docs/native-iter-rc-design.md`）：刀 2 把每次元素访问的 dup 从 10.97 降到 5.97，
> 剩下的主体是 `std/pvec.leaf_for` 每层 3 次 dup，需要借用的模式绑定或 dup/drop 融合，且与早 drop、复用必须一起设计；
> [perceus-design.md](perceus-design.md) §6（复用分析，现只覆盖 `dawn_array_with`；§6.6 末写着「需要未来的 ADT reuse/field-steal」）。

## 一、结论

1. **今天 ADT 与记录的每一次构造都是一次新分配，而它们前一行刚把同样大小的旧值放掉。** 生成的 C 里能直接看到：`dup 字段; drop 旧节点; adt_new`（§二）。
   这是 Perceus 的标准用例（reset/reuse），Koka 与 Lean 都做，本仓缺的是这一格。
2. **三件事必须一起设计，因为它们抢同一个东西，即「被匹配的节点什么时候死」：**
   - 早 drop（`rc.sweep`，§6.1 的第一件）让节点在最后一次使用后立刻释放，复用靠它拿到 `rc == 1`；
   - 复用要在那个释放点放一个 `reset`，并把节点的字段「偷」给新构造器（省掉字段的 dup 与随后的递减）；
   - 借用的模式绑定（`leaf_for` 要的）反过来要把节点的死亡**推迟**到绑定的最后一次读之后。
   Lean 的解法是定一个优先序：**参数或它的投影进过 `reset` 就必须是 owned，借用推断从剩下的里找**（§三 3.2）。本稿照这个序。
3. **提案：** 在 `rc.dawn` 的 `sweep` 处，把「被匹配节点的最后一次使用之后的 drop」在后文有同 size class 构造器时换成 `reset`；
   构造器取 `reuse` 令牌；`reset` 展开成唯一/共享两条路（唯一时偷字段，共享时退回今天的 dup+drop）。
   借用侧补三件小事：match 的 scrutinee 别名 `let` 不再把参数判成 owned、只读的模式绑定变成不计数的别名、赋值 `x = f(x)` 之后的读不再钉住 `x`。
   **不需要任何用户可见的标注**（§四；`fip` 类标注Q1 已裁决不做）。
4. **实测基线与手改 C 的投影**（本机，clang-18，§五）：

| 基准 | 现状 | 手改 C 后（投影，不是实现） | 改动内容 |
|---|---|---|---|
| update 链，1e7 步，秒 | 0.472 | **0.159**（−66%） | 5 个同形记录更新都 reset/reuse，稳态 0 次分配 |
| tree `incr`+`sum`，100 万节点×10 轮，秒 | 0.643 | 0.286 → **0.250** | 复用 `incr` 节点；再把 `sum` 的参数与模式绑定借用 |
| listf `for` 求和（含建表 0.317），100 万×20，秒 | 0.990 | **0.529** | `leaf_for` 借用投影，每次元素访问 dup 5.97 → 2.00 |

   **自编译负载上的预期很小**：compiler `check checker.dawn` 里 ADT 分配 2389 万次占全部对象的 36%，其中 73% 能在最近 8 次释放里找到同 size 的，
   但上界只有约 2.5%（§五 5.4）。这条刀的价值在**函数式更新密集的程序**，不是编译器自己。
5. 刀序（§六）：先做两个前置（赋值交接、自尾调用循环交接，没有它们 reuse 在 tree 与 update 基准里根本触发不了），再做借用侧，最后做 reuse 本体，共三个 PR、七把刀。

## 二、现状（带行号）

### 2.1 drop 放在哪里

- `rc.dawn` 的基本规则是 [perceus-design.md](perceus-design.md) §5.2 的保守形：每个消费使用处 dup、每条路径出口 drop 每个绑定；在其上是最后使用分析（§5.8）：
  **最后一次消费使用转移值而不复制**（`rw` 的 `CLocal` 臂，`rc.dawn:1603` 起：`not set.has(after, sym) && transferable(...)` 时 `release`，否则 `CDup`）。
- **早 drop** 是 `sweep`（`rc.dawn:1929`）：`rw_stmts`（`rc.dawn:1942`）从后向前建每条语句的 after 集，每对语句之间调用 `sweep`，
  把「不在 after 集里且 `transferable`」的绑定立刻 `CSDrop`。目的写在 perceus-design §6.1：节点在最后一次被碰之后马上释放，它的子节点才降到 `rc == 1`，
  `array_with` 才能原地写。
- 赋值 `x = e`（`rw_stmt` 的 `CSAssign` 臂，`rc.dawn:1988` 起）先算后放；若 `e` 自己消费了 `x`，那次转移就是旧值的释放（§6.1 第四件）。

### 2.2 Array 的复用怎么工作

运行时一格 + 分析四件（perceus-design §6.1）：`dawn_array_with`（`runtime/c/dawn_rt.c:3387`）**消费**数组与元素（`types.intr_owned_args`），
头与 buf 都 `dawn_is_unique` 且不在 leak 模式时就地写并原样交回，否则复制并还账；`dawn_array_steal` 在唯一时把槽的引用转出。
计数器 `dawn_array_with_inplace/copied` 打印在 `DAWN_RC_STATS` 行，`scripts/array-contract` 与 `scripts/map-reuse-contract` 用它们立预算（95%）。
这条路径之所以成立，是因为 `array_with` 本身就是原语，它的「旧值死了没有」直接由 `rc == 1` 回答，**不需要分析把一个释放与一个构造配对**。

### 2.3 为什么 ADT 与记录从不复用

`rc.dawn` 里 `CCtor` 的臂（`rc.dawn:1718`）只是 `consume_all` 各个字段然后 `wrap`；`CUpdate` 先 `update_as_ctor` 变成整构造器再走同一臂（`rc.dawn:1727`）。
`emitc.emit_alloc`（`emitc.dawn:1176`）无条件发 `dawn_adt_new(tag, n, mask)`。没有任何一处把「某个绑定在这里死了」和「这里构造同样大小的值」联系起来。实测的生成 C（`tree.dawn` 的 `incr`）：

```
dawn_own[5] = dup(own[2]->fields[0].p);          /* l */
int64_t v13 = own[2]->fields[1].i;               /* v */
dawn_own[6] = dup(own[2]->fields[2].p);          /* r */
dawn_drop(dawn_own[2]);                           /* 旧节点死在这里: free + 两个子节点递减 */
...
dawn_adt* t5 = dawn_adt_new(1, 3, UINT64_C(0x5)); /* 同样大小的新节点 */
```

`update.dawn` 的 `step` 是同一形状的纯标量版：五次「读 5 个字段、`drop` 旧记录、`adt_new(0, 5, 0)`、写 5 个字段」。

### 2.4 两个让复用够不着的现状缺陷（本稿实测）

即使有了 reset/reuse，下面两条会让它在最典型的基准里触发 0 次，所以是前置，不是锦上添花：

- **赋值之后的读钉住目标。** `tree.dawn` 的循环体是 `t = incr(t); tot = tot + sum(t)`。`CSAssign` 臂用 `after`（含 `sum(t)` 读 `t`）改写 `incr(t)`，
  于是 `incr(dup(t))`，根节点 rc 为 2。**一个多出来的 dup 使整棵树一路都是共享的**：根被复制，它的两个子节点各被 dup，旧根还握着它们，子节点也只能复制，如此下去。
  但 `sum(t)` 读的是**赋值之后的新 `t`**，教科书的活性规则是 `live-in(x = e) = (live-out − {x}) ∪ use(e)`，目标不该留在右侧的 after 集里。
  实测印证：把两行换序（`tot = tot + sum(t); t = incr(t)`）后生成 C 变成 `incr(take(own[13]))`，一个 dup 也没有（`tree_v2`）。
- **自尾调用循环的参数多一个 dup。** `update.dawn` 的 `loop(s, i, n)` 是 `loop(step(s), i+1, n)`，生成 C 是 `step(dup(own[1]))` 再 `drop(own[1])`，每步 1 个 dup，
  `step` 里第一个记录更新因此看到 rc 2。同一计算写成 `while` 加 `s = step(s)`（`update_while`）是 0 个 dup（`CSAssign` 的重挂交接生效）。

### 2.5 借用推断今天为什么救不了 `sum` 与 `leaf_for`

`infer.dawn` 的 `dm_expr`（`infer.dawn:345`）对投影的处理是：投影在消费位置，且本函数构造同一 ADT（`proj_demands`，`infer.dawn:270`），才把目标判 owned。
这就是 Lean 的「参数或它的投影进了 `reset` 就是 owned」的雏形。但 `sum` 与 `leaf_for` 都不构造同一 ADT，仍然是 owned。生成的 C 给出原因：
**lower 把 `match t` 的 scrutinee 绑成一个新 `let s = t`**（C 里 `dawn_own[2] = take(&dawn_own[1])`），这是对参数的一次消费使用，`dm_expr` 照 `rc.rw` 的分类把它判 owned。
所以 `sum(t: T)` 的参数是 owned，调用点 `sum(dup(t))`，每个节点 `l`、`r` 各一次 dup。
在 nmain 的生成 C 里（4886 个函数，grep 估计）有 3065 个函数把参数放进自己的 own 槽，其中 352 个紧接着把它 `take` 进另一个槽，即这个别名形状。

## 三、先例

### 3.1 Koka / Perceus

- Reinking, Xie, de Moura, Leijen, *Perceus: Garbage Free Reference Counting with Reuse*, PLDI 2021。<https://www.microsoft.com/en-us/research/publication/perceus-garbage-free-reference-counting-with-reuse/>，
  正文 <https://xnning.github.io/papers/perceus.pdf>。读到的要点：
  - 精确 RC 之上有三个优化：**drop 特化**（§2.3，把 `drop xs` 内联成「唯一则释放壳、字段不动；共享则 dup 字段、递减」，融合掉字段的 dup/drop）、
    **reuse 分析**（§2.4，把被消费的旧值与同大小构造器配对，运行时 `rc == 1` 才原地）、**reuse 特化**（§2.5，复用时只写变了的字段）。
  - 论文的 FBIP 结论：红黑树插入的纯函数式 Koka 实现与 C++ `std::map` 的就地实现差距在 10% 以内（论文 §4 的 rbtree 基准）。
  - **论文明说没有借用**：结论里把「选择性借用」列为未来工作，理由是借用会让程序不再 garbage free，但可能带来进一步的性能改进。
- Lorenzen 的硕士论文 *Optimizing Reference Counting with Borrowing*（2021）：<https://antonlorenzen.de/papers/master_thesis_perceus_borrowing.pdf>。
  读到的两句直接对本稿有用：借用「有可能让程序快约 10%」，但「去掉 drop 之后就不能用 reuse 分析，而 reuse 分析对性能比借用重要得多」，且值不再尽早释放，峰值内存会变。
  这正是 §一第 2 点的冲突，结论也是同一个序：reuse 优先。
- Lorenzen, Leijen, *Reference Counting with Frame Limited Reuse*（ICFP 2022）：<https://www.microsoft.com/en-us/research/wp-content/uploads/2021/11/flreuse-tr.pdf>。
  把 reuse 放宽成「帧受限」：借用、延迟 drop 也能保证峰值内存不超过常数倍栈帧。对本稿的意义是：借用的模式绑定把 drop 推迟到绑定的最后一次读，**推迟的上界是当前函数帧**，不会无界，这是 §4.3 的安全论证来源。
- Lorenzen, Leijen, Swierstra, *FP²: Fully in-Place Functional Programming*（ICFP 2023）：<https://www.microsoft.com/en-us/research/wp-content/uploads/2023/07/fip.pdf>。
  `fip`/`fbip` 是**检查**标注，不是启用 reuse 的标注：论文脚注写明实现里「总能推断一个 match 是否需要破坏性」，可以对破坏性与借用的匹配都只写 `match`。
  借用只出现在参数上（`^f` 帽记号）。**所以 reuse 本身不需要用户标注**，这一条被 Koka 的实现验证过。

### 3.2 Lean 4

- Ullrich, de Moura, *Counting Immutable Beans: Reference Counting Optimized for Purely Functional Programming*（IFL 2019）：<https://arxiv.org/abs/1908.05647>。
  三步编译：先插入 reset/reuse（§4，算法 R、D、S：在每个 `case` 里找被匹配变量的第一个死点，向后替换同 arity 的构造器），再推断借用参数（§5.2），最后插 inc/dec（§5.3）。
  **优先序写在 §5.2：「一个参数 x 应当 owned，如果 x 或它的某个投影被用在 reset 里，或被传给 owned 参数。」** 理由是借用「会阻止 reset 与 reuse」。
  实测的消融（论文 §6 的表）：关掉 reuse，rbmap 慢 3.23 倍、const_fold 慢 1.64 倍；关掉借用推断，deriv 慢 1.16 倍。reuse 比借用重要，与 Lorenzen 的判断一致。
- Lean 的 `ExpandResetReuse` 阶段（源码镜像文档：<https://www.cs.rochester.edu/~yzhu104/lean-gccjit/Lean/Compiler/IR/ExpandResetReuse.html>）：
  把 `reset` 展开成**快路径**（唯一：对没被读的字段发释放，把「刚 `inc` 的投影」的 `inc` 抹掉，`reuse` 变成原地设字段）与**慢路径**（共享：`inc` 字段、`dec` 目标、`reuse` 变回 `ctor`），
  对应的函数名是 `mkFastPath`、`mkSlowPath`、`eraseProjIncFor`、`releaseUnreadFields`、`reuseToCtor`。本稿的 §4.2 逐项对应。
  该文档同时说明展开阶段后来被移植到新的 LCNF 并「避免了指数级代码生成」，这是 §4.2 必须限制展开范围的先例。
- Lean 的借用参数标注 `@&` 是用户可写的，但推断是默认路径；**对借用的模式绑定，Lean 没有单独的构造**：投影是普通的 `proj`，是否 `inc` 由借用状态决定（借用变量的投影是借用的）。
  这等价于本稿的 P2。

### 3.3 借用的模式绑定

- Swift SE-0432（Swift 6，2024-09）给不可复制类型加了「borrowing 绑定」：switch 按模式所需的所有权推断是借用还是消费主体，模式里可写 `borrowing x`。
  <https://forums.swift.org/t/se-0432-borrowing-and-consuming-pattern-matching-for-noncopyable-types/71158>。区别：Swift 把它交给程序员（类型系统可见），Dawn 没有所有权语法，只能推断。
- Roc 的 reset/reuse 与借用推断（Utrecht 的毕业论文 *Reference Counting with Reuse in Roc*，检索摘要）：reset 放在 scrutinee 最后一次使用之后，**函数的参数若在函数里被 reset 就标 owned**，
  其余默认借用。与 Lean 同序。
- Morphic（<https://morphic-lang.org/>，检索摘要）用带生命周期的借用类型推断，几乎消掉全部 RC 增减；代价是整程序的别名分析，Dawn 不走这条。

### 3.4 本仓的位置

Dawn 已有：Lean 式的借用参数推断（`infer.dawn`，且已含 `proj_demands` 这一条 reset 判据的雏形）、早 drop、Array 的 `rc == 1` 复用。
缺的是 reset/reuse 本体与 drop 特化，以及「借用的是绑定而不只是参数」。

## 四、提案

### 4.1 分析与它们住在 `rc.dawn` 的哪里

按 Lean 的序（reset/reuse 先于借用推断先于 RC 插入），在本仓里落成五个小分析，文件头注释与门禁各管各的：

| 编号 | 分析 | 住处 | 要点 |
|---|---|---|---|
| P0a | 赋值杀死目标 | `rw_stmt` 的 `CSAssign` 臂（`rc.dawn:1988`） | 改写右侧时用 `set.remove(after, sym)`；跳出右侧的 jump 仍走现成的保守路径 |
| P0b | 自尾调用循环参数交接 | 循环参数重绑定处（`unloop`/tail-call 循环，`rc.dawn:709` 一带） | 把参数重绑定当作赋值，同 P0a 的交接规则 |
| P1 | 别名 `let` 消除 | 新增 Core→Core 小遍，`infer.dawn` 与 `rc.dawn` 之前 | `let s = t`，`s` 从不被重新赋值、`t` 在 `s` 活着时不被重赋 → 用 `t` 替换 `s`；JVM 不受影响（C 路径专用，同 `spread` 提升） |
| P2 | 借用投影 | `rc.dawn` 新增 `alias_of: Map[Int, Int]`，`infer.dawn` 同步 | `let y = proj(x)`，`y` 只出现在借用位置，则 `y` 是不计数的别名，`x` 的释放点推迟到 `y` 的最后一次读之后 |
| P3 | reset/reuse | `sweep` 处发 `CSReset`；`CCtor` 臂认令牌；展开在 `rw` 之后的单独函数；配对的辅助判定函数放新文件 `c/reuse.dawn` | 见 §4.2、§4.3 |

P1、P2、P3 与 `proj_demands` 合起来的优先序是：**能 reset 的 scrutinee 一律 owned，借用只给不参与 reset 的绑定与参数**（§4.4）。

### 4.2 reset/reuse 与 drop 特化

**新 Core 节点（仅 rc 之后存在，同 `CDup`/`CSDrop`，JVM 看不到）：** 语句 `CSReset(tok, s)`：`tok` 是新绑定，`s` 是被匹配的节点；构造器臂 `CReuse(tok, adt, ci, args, ty)`。
这两个节点只由 `rc.rw` 生成，所以 `rc_check`（`rc.dawn:2522`，局部 oracle）要新增规则：`tok` 是一个计数绑定，在每条路径上恰好被 `CReuse` 消费一次或被 `CSDrop(tok)` 释放一次。

**配对（placement）。** 在 `sweep` 里，当要为 ADT 类型的绑定 `s` 发 `CSDrop(s)` 时，查看**后续语句与尾表达式**（`rw_stmts` 已经持有 `afters`，再传一份后缀即可）里是否有同 size class 的构造器
（`CCtor`/`CUpdate`/`CTuple`）；有则发 `CSReset(tok, s)` 代替 `CSDrop(s)`，并在每个这样的构造器处用 `CReuse(tok, ...)`（一个令牌一次，后到的用 `adt_new`）。
**选 `sweep` 处配对，不另做一遍带自己活性的分析**，理由是 perceus-design §6.2 的教训：pass 与它的 oracle 对「哪条路径还活着」只能有一份定义，释放点已经是 `sweep` 算好的。
没有匹配构造器的路径上令牌必须释放：展开后的令牌是一个壳（见下），`CSDrop(tok)` 就是普通 `dawn_drop`，不需要新原语。

**运行时（`dawn_rt.h/c`）。** 两个入口，位置照 `dawn_array_with` 的 `DAWN_CONSUMES` 规矩登记：

- `dawn_adt *dawn_adt_reset(dawn_adt *a)`：若 `a->h.rc == 1` 且非 leak 模式（immortal 的 `rc` 是 `INT32_MAX`，field-less 单例自然落在慢路径）：**逐个释放未被偷的指针字段**，
  **把 `ptrmask` 清零**，返回 `a`；否则 `dawn_drop(a)`，返回 `NULL`。
- `dawn_adt *dawn_adt_reuse(dawn_adt *tok, int32_t tag, int32_t n, uint64_t mask)`：`tok != NULL` 则改写 `tag`、`nfields`、`ptrmask` 后返回，否则 `dawn_adt_new`。

**为什么令牌要清掉掩码。** 令牌活在被 reset 与被 reuse 之间，这中间可以有调用（`incr` 先递归再构造）。调用可以 panic 并被 `catch_fault` 接住，`DAWN_OWN_FRAME` 的清理会 drop 令牌所在的槽。
令牌若还带着旧掩码，清理会把已经偷走的字段再释放一遍。清零掩码后令牌是一个合法的、零个指针字段的 ADT，任何时刻 `dawn_drop` 它都只释放壳。
同一个性质让 LSan 在任何时刻看到的都是普通对象，不需要特判。

**size class 而不是 nfields。** slab 的粒度是 16 字节（`dawn_rt.h:562`），ADT 是 24 字节头加 8 字节每字段，所以 nfields 2 与 3 同在 48 字节类，4 与 5 同在 64 字节类。
第一版只配 `nfields` 相等的（更容易证明），同类放宽留作 Q2。宽掩码（超过 64 字段，`dawn_adt_new_wide`）第一版不参与。

**drop 特化 / 偷字段（照 Lean 的 `ExpandResetReuse`）。** 展开发生在 `rw` 之后的一个单独函数里，找「直线前缀」：

```
let l = dup(s.f0)          # 投影加 dup，在 reset 之前的同一基本块
let v = s.f1               # 标量读
let r = dup(s.f2)
reset tok = s
```

展开成：

```
if (rc(s) == 1 && !leak) {      /* 快路径: 偷 */
  l = s.f0; v = s.f1; r = s.f2; /* 没有 dup */
  release_unread_fields(s);     /* 模式里写了 _ 的指针字段 */
  s.ptrmask = 0; tok = s
} else {                         /* 慢路径: 今天的代码 */
  l = dup(s.f0); v = s.f1; r = dup(s.f2); drop(s); tok = NULL
}
```

前缀里不能有对 `s` 的其他消费，也不能有能 panic 的调用（否则快路径里「已偷」状态与清理不一致，规则同令牌的掩码论证，可以放宽但第一版拒绝）。
**展开范围要限制**：Lean 把展开从 IR 移植到 LCNF 的理由是避免指数级代码，所以只展开直线前缀，每个 `reset` 一对分支，不跨 `if` 复制。

**与早 drop 的关系。** `CSReset` 就在原来 `CSDrop(s)` 的位置，没有推迟任何东西；唯一的变化是这一点之后多了一个活的令牌（一个壳），它最晚死在构造器处。

### 4.3 借用的模式绑定（P1、P2）

**P1，别名 `let` 消除。** 解决 §2.5：`let s = t` 之后 `t` 与 `s` 同值，把 `s` 替换成 `t`。条件：`s` 不被赋值，`t` 在 `s` 的所有读之间不被赋值（`t` 是参数时自然成立）。
这一步单做就能让 `sum` 的参数不再被别名 `let` 判 owned。

**P2，借用投影。** `let y = CField(x, ...)`（或 `CTupleGet`），`y` 的每个使用都是借用位置（`rc.borrow` 的位置，或借用参数位置，包括递归调用里推断为借用的参数），则：
`y` 不入账本（同 `dict_syms`、`borrowed_syms` 的待遇），不发 dup，不发 drop；在 `fv_expr` 里**把 `y` 的每个使用同时算作对 `x` 的使用**，这样 `sweep` 与 `transferable` 自然把 `x` 的释放点推迟到 `y` 的最后一次读之后，
不需要另一套活性。`x` 若是借用参数，什么都不用做。对 `var node` 这类被重新赋值的局部（`leaf_for` 的循环变量），要加 **P2b**：`var` 的每个赋值都来自借用投影且初值也是，则它是借用别名，别名的根是 `v`（借用参数）。

**为什么这是安全的，推迟是否有界。** 值不可变，单线程严格求值，借用别名的持有者（`x`）在别名活着期间不会被转移（`x` 在 after 集里，`transferable` 拒绝），这与现有借用参数同一论证。
推迟的上界是当前函数帧内的 `y` 最后一次读，符合 frame limited 的条件（Lorenzen & Leijen 2022）。

**与 reuse 的冲突与裁决。** 若 `x` 在作用域里有 reset 候选（§4.2 的配对成功），则 `x` 的释放点不能推迟，此时 `y` 不借用，改成 owned 投影（它会走快路径偷字段）。
判据在 `infer.dawn` 与 `rc.dawn` 里各一处，用同一个函数：`reuse.has_candidate(x)`，和 `proj_demands` 合并成一条。`rbtree` 的 `balance` 这类「读子节点再重建父节点」的函数，
子节点在 reset 点之前读完就仍可借用，否则变 owned，这是逐绑定的判据，不是逐函数。

**dup/drop 融合（任务单里的另一条路）。** 在同一路径上「`dup x` 之后、`x` 的所有者死之前、对 `x` 没有消费」的 `dup`/`drop` 对直接抹掉，是一个 Core 数据流 pass。
它能覆盖 P2 能覆盖的，外加一些 P2 看不见的（别名不是投影）。**不推荐先做**：它是纯局部窥孔，逐函数做，没有跨调用的借用参数收益（`sum` 需要的是参数借用，不是窥孔），
也没有「`x` 的释放点推迟」的统一表述，与 reset 的冲突要靠顺序约定。Q3 已裁决不做。

### 4.4 是否需要用户可见的标注

**不需要。** 依据：Koka 的 `fip`/`fbip` 只检查，不启用（FP²，脚注 2）；Lean 的 `@&` 是可选覆盖，默认靠推断；Roc 全推断。
Dawn 的语言语义不暴露同一性与所有权，`reset`/`reuse` 是 C 路径上的纯优化，运行时 `rc == 1` 不成立就退回今天的代码，输出不变。
可能需要标注的唯一场景是「要求某函数保证原地」（`fip` 式）：那是性能契约的检查，不是机制，Q1 已裁决不做。

## 五、预期收益（实测的基线，投影单列）

方法：clang-18 `-O2 -fwrapv -fexceptions -fno-strict-aliasing`，`dawn_rt.c` 的临时副本里挂 alloc/adt/dup/drop 计数器（不动仓库）；`drop` 计数含传 `NULL` 的调用，与刀 2 报告的口径一致
（实测复现了它的 10.97/12.96、5.97/7.95）。墙钟 5 次中位数，括号里是读数时 `/proc/loadavg`。**本机是共享的，负载 2.2 到 2.8，差在 ±5% 内不读。**
基准源码来自 `agent-handoff/bench-repr-artifacts/dawn/`；`update_while`、`tree_v2` 是本稿为隔离 §2.4 的两条缺陷写的变体（改写写法，不改计算）。

### 5.1 计数（每次迭代，稳态，两个 n 相减）

| 基准 | 分配 | dup | drop | 备注 |
|---|---|---|---|---|
| update（自尾调用 `loop`） | 5.0（全是 ADT） | 1.0 | 6.0 | 那一个 dup 就是 §2.4 的循环参数 dup |
| update_while（`while` 加赋值） | 5.0 | 0.0 | 5.0 | 交接生效，但仍每个记录更新一次分配 |
| update_reuse（手改 C） | **0.0** | 0.0 | 0.0 | 稳态零分配（总分配 30 次，与步数无关） |
| tree（`t = incr(t); tot += sum(t)`） | 1.0 / 节点 | 2.0 | 6.0 | 每节点：`incr` 一次 new，`incr` 与 `sum` 各 dup 一次子节点 |
| tree_v2（换序，根不再 dup） | 1.0 | 2.0 | 6.0 | 计数不变，但根 rc 为 1 了，这是 reuse 的入场券 |
| tree_v2_reuse（手改 `incr`） | **0.0** | 1.0 | 5.0 | `incr` 偷子节点：dup −1，drop −1 |
| tree_v2_reuse_bsum（再改 `sum`） | 0.0 | **0.0** | 3.0 | `sum` 参数与模式绑定借用 |
| listf `for` 求和（刀 2 之后，`perf/native-iter-rc`） | 0 | 5.97 | 7.95 | n=1000，一层 trie |
| listf 同上（手改 `leaf_for`，借用投影） | 0 | **2.00** | 2.00 | 剩下的 2 个是元素 dup 与返回叶子的 owned dup |
| nbody 每步（main 基线） | 124.0（112 个 ADT） | 292.0 | 385.0 | 刀 2 报告写 297/385，复现差 5 |

### 5.2 墙钟

| 变体 | 秒 | 负载 | 读法 |
|---|---|---|---|
| update（自尾调用循环），1e7 步 | 0.479 | 2.25 | 基线 |
| update_while | 0.472 | 2.23 | 单做交接没有收益（分配还在） |
| update_reuse（手改 C） | **0.159** | 2.23 | 投影：−66% |
| tree（原写法），100 万节点×10 轮 | 0.707 | 2.21 | 基线 |
| tree_v2（换序） | 0.643 | 2.21 | 少一个根 dup，−9%，同样没有分配收益 |
| tree_v2_reuse | 0.286 | 2.44 | 投影：相对 tree_v2 −56% |
| tree_v2_reuse_bsum | **0.250** | 2.44 | 投影：再 −13% |
| listf mode0（只建表） | 0.317 | 2.44 | 迭代以外的固定部分 |
| listf mode1（`for` 求和），刀 2 之后 | 0.990 | 2.80 | 基线（迭代部分约 0.67） |
| listf mode1，手改 `leaf_for` | **0.529** | 2.74 | 投影：迭代部分约 0.21 |

读法：update 与 tree 的收益几乎全来自「分配 + 释放 + 字段 dup/递减」的消失，与研究报告里「小对象一整圈 4.5 到 5 ns」一致
（update：(0.472 − 0.159) / 1e7 / 5 = 6.3 ns 每个被消掉的记录更新）。**所有「手改 C」都是投影**：它们手写了设计会发的代码，没有经过 `rc.dawn`，
所以没有覆盖「分析在真实源码里能不能配上对」这一半，那一半是各刀的验收（§六）。

### 5.3 前置缺陷的价值

`tree` 到 `tree_v2` 只差一个根 dup，墙钟 −9%；但**只有 `tree_v2` 那种写法 reuse 才能触发**：手改 `incr` 后在原写法上跑计数不变（reuse 路径 0 次命中，分配仍 1.0 每节点）。
这是 §2.4 为什么是前置的实测依据：没有 P0a，tree 基准里 reuse 是零，且不报错。

### 5.4 编译器自编译负载（真实代码的天花板）

用 `dawn __emitc --split` 生成 `nmain.dawn` 的 C（396,583 行），挂计数器编译，跑 `check selfhost/src/check/checker.dawn`（3.26 s user，加载 ok）：

| 量 | 值 |
|---|---|
| 全部堆对象分配 | 65,583,071 |
| 其中 ADT 分配（也是 ADT 释放数） | 23,892,236（36.4%） |
| dup / drop 调用 | 613,047,712 / 732,836,395 |
| ADT 分配在最近 1 / 8 / 32 次 ADT 释放里有同 nfields 的 | 49.2% / 73.1% / 80.7% |
| 一个 ADT 死亡时被访问的非 immortal 指针字段 | 47,242,643 |
| 其中子节点此刻 `rc > 1`（即「字段先 dup、父再 drop」的一对，偷字段能消掉） | 35,322,689（74.8%），占全部 dup 的 5.8% |

时间邻接的 k1/k8 与 perceus-design §6.6 的 51.4%/74.7% 一致（那是另一份负载与另一天的读数），**是静态配对的上界而不是预期**：配对要在同一作用域里、`sweep` 的释放点之后。
静态规模：nmain 的 C 里有 12,065 行含 `dawn_adt_new(`；含 `dawn_dup(` 的 45,894 行里有 22,424 行（48.9%）带 `->fields[`，即字段投影的 dup（行级 grep，含记录字段读，是上界）。
投影收益上界：17.5M 次 k8 邻接 ×（4.5 到 5 ns，研究报告的整圈数，含 dup/drop，高估了 alloc+free 这一半）≈ 80 ms，约 2.5% 的 3.26 s。
**这是上界，不是承诺；编译器自己不是本刀的目标负载**，所以刀 K3.5 之后要看 `native-fixpoint` 自举的墙钟是否持平而不是下降。

## 六、安全：现有门禁如何覆盖，各刀新增什么

### 6.1 风险

复用把「旧对象内存被新对象占用」变成可能：一个读旧字段的陈旧引用在 ASan 下**不再报错**（块一直活着）。偷字段后掩码清零前若有路径 drop 旧节点，则双释放；少释放未读字段则泄漏；
令牌跨调用时 panic 清理要正确；同 class 复用若 `nfields` 没改写，则 drop 走的是旧 nfields。

### 6.2 现有门禁各自能看见什么

| 门禁 | 对 reuse 的覆盖 |
|---|---|
| `rc_check`（`rc.dawn:2522`，每个 rc 后的函数） | 本地平衡：令牌每条路径恰好消费或释放一次。**要加规则**（K3.4） |
| `scripts/rc-contract`（`rc_test.c`、slab 变异体、poison_probe） | 运行时原语的 ASan 断言与变异体。新增 `dawn_adt_reset/reuse` 的断言与变异体（见下） |
| `scripts/array-contract`、`scripts/map-reuse-contract` | `array_with` 就地率预算（95%）。**P2 推迟 drop 若让它们降就红**，这是借用与 reuse 冲突的实测探针；见 §4.3 的裁决 |
| `scripts/spike-native`（174 项，ASan+LSan） | 泄漏/双释放的主力；reuse 路径会被语料里所有构造器跑到 |
| `scripts/native-fixpoint.sh`（B == C） | 编译器自己用 reuse 编译自己后字节一致；任何值语义错误会让自举崩或分叉 |
| `scripts/rc-mode-contract` | 参数借用表的契约；P1/P2 改变哪些参数 borrowed，翻转要登记 |
| `native-selfhost-tests`、`native-asan-tests` | 全量测试与 ASan+UBSan 单元 |

JVM 不经过 rc，`emit` 字节不变，预计无需 `Emit-Change`；C 文本变化由 native-fixpoint 与 `c-map` 门禁约束，提交时要用 `scripts/gate-map/gatemap.py` 核对实际要跑的门禁。

### 6.3 新增契约与负控（每刀各自，写在刀序里）

- **`scripts/adt-reuse-contract`（新，仿 `map-reuse-contract`）：** 运行时计数器 `dawn_adt_reuse_taken/missed` 印在 `DAWN_RC_STATS` 行；工作负载是 update 链、tree `incr`、list `map`；预算 95%。
  **值语义的见证**：保留旧树的第二个引用，`incr` 之后旧树必须不变（reuse 若误在共享节点上原地写，这一条会红，而计数器预算看不见）。
- **ASan 毒化（契约构建专用 `-DDAWN_REUSE_POISON`）：** `reset` 快路径偷完字段后把字段槽写成哨兵，陈旧读立刻露馅，补上「ASan 看不见复用后的陈旧读」这个缺口。
- **变异体（`mutate.py` 风格，每个写进 `matrix.txt` 与负控）：** (a) reuse 不查 `rc == 1`（总是复用），共享值语义见证红；(b) 快路径不清零掩码，ASan 双释放；
  (c) 快路径不释放未读指针字段，LSan 泄漏；(d) `reuse` 不改写 `ptrmask`，类型不同的复用后 drop 走错字段；(e) 把 immortal 的 field-less 单例当令牌（`rc <= 1` 的错判），ASan/断言；
  (f) 去掉 P0a 的 `set.remove`，计数预算红（对应的现状就是 §2.4，所以这个负控是「撤销就回到今天」）。
- **P2 的负控：** 沿用刀 2 的做法，借用别名的持有者提前转移（让 `transferable` 对别名根放行），listf 探针在 ASan 下应是 UAF。

## 七、刀序与已裁决的问题

### 7.1 刀序（每刀一个提交，按主题分 PR）

**PR-A「所有权交接前置」**（独立有价值：少一个 dup，且是 reuse 的入场券）

- **K3.0a**：`CSAssign` 的右侧 after 集去掉目标（P0a）。验收：`tree` 原写法生成 C 里 `incr(take(...))`；`rc_check` 绿；array/map-reuse-contract 的率只升不降。负控：撤销。
- **K3.0b**：自尾调用循环参数重绑定走赋值交接（P0b）。验收：`update` 的 `loop` 每步 dup 1.0 → 0.0。

**PR-B「借用的模式绑定」**（独立有价值：`sum`、`leaf_for`、所有只读遍历）

- **K3.1**：别名 `let` 消除（P1）。验收：`sum` 参数 borrowed；nmain 里「param 紧接着 take」形状从 352 降；rc-mode-contract 登记新增的 borrowed 参数。
- **K3.2**：借用投影，含 `var` 别名（P2、P2b），先不碰 reset 候选判据（此时还没有 reset）。验收：listf 每次元素访问 dup 5.97 → 目标 2.0（§5.1 的手改值）；负控见 §6.3。
- 先做 PR-B 还是 PR-C 都行；**PR-C 之前必须有 K3.1**，否则 `incr` 的 scrutinee 别名使参数 owned 之外还多一个 dup。

**PR-C「ADT reset/reuse」**（本稿主体）

- **K3.3**：运行时 `dawn_adt_reset/reuse`、计数器、`DAWN_CONSUMES` 登记、rc-contract 断言与变异体（a）(b)(c)(d)(e)、毒化构建；此时没有任何编译器路径调用它们。
- **K3.4**：`rc.dawn` 的配对（`sweep` 处）、`CSReset/CReuse`、`rc_check` 规则、快慢路径展开、`scripts/adt-reuse-contract`。验收：update 稳态零分配；tree 复用率 ≥ 95%；spike-native 174 项 ASan+LSan 绿；native-fixpoint B == C。
- **K3.5**：reset 候选判据并入 `infer.dawn` 的 `proj_demands` 与 P2（§4.3 的优先序），把 K3.2 里先放开的借用收紧到「无 reset 候选才借用」；验收：`map-reuse-contract` 与 `array-contract` 率不降，`sum` 仍 borrowed，`incr` 的 `t` 仍 owned。
- **K3.6**（有数再做）：同 size class 放宽（nfields 2 与 3 等）、泛型/擦除位置（元组、`Some(box)`）里的令牌。放不放看 K3.4 之后 adt-reuse 的未命中分布。

总工作量估计：PR-A 小，PR-B 中，PR-C 大（K3.4 是整件事的难点，其中展开与 oracle 各占一半）。这是估计，不是度量。
**每个 PR 的描述里要报 CI 墙钟影响**（新增 `adt-reuse-contract` 与 rc-contract 变异体的耗时），先在本机量。

### 7.2 已裁决的问题（原开放问题）
以下七条在 `agent-handoff/ruling-perceus-reuse-20261007.md` 中全部按原推荐裁决，选项文字保留作理由。另有两条前置（赋值交出旧值、自尾调用循环交出参数）裁决在 PR-A 的 K3.0a/K3.0b 先修。

- **Q1，要不要 `fip` 式标注？** 选项：(a) 不做；(b) 加 `@fip` 之类的检查标注，要求函数的所有构造器都配上令牌，否则编译报错。
  **裁决：(a)。** 机制不需要它（FP² 脚注），Dawn 的语言面不暴露所有权，加一条只检查性能的属性要同时进 spec、格式器与 LSP。等出现真实的「要保证原地」的用户痛点再开。
- **Q2，同 size class 放宽（nfields 2 与 3）还是只配 nfields 相等？** 选项：(a) 只等；(b) 同 class。
  **裁决：(a) 先上，K3.6 用 adt-reuse 的未命中分布再裁。** (b) 需要运行时同时改 `nfields` 并保证 `dawn_free` 对 slab 的 size 无依赖（目前按地址定 class，成立），但每个放宽都要补变异体。
- **Q3，dup/drop 融合要不要做，还是只做借用投影（P2）？** 选项：(a) 只做 P2 加 P1；(b) 另做路径级融合；(c) 两个都做。
  **裁决：(a)。** P2 给的是参数与绑定的借用，能让 `sum` 整个无 dup；融合是函数内窥孔，拿不到这一半，还与 reset 的冲突靠顺序。(b) 留到 P2 之后剩余的 dup 有测得的分布再评。
- **Q4，配对放 `sweep` 里还是单独一遍带自己活性的分析？** 选项：(a) `sweep` 内（共用活性）；(b) 新 pass（Lean 的做法，算法 D 自带死点搜索）。
  **裁决：(a)。** 本仓已有「pass 与 oracle 活性只能一份」的教训（perceus-design §6.2），而且释放点已经是 `sweep` 的产物。代价是 `sweep` 需要看到后缀，`rw_stmts` 已经算好了。
- **Q5，P1 放哪一层？** 选项：(a) 在 lower 里不生成别名 `let`；(b) C 路径专用的 Core 小遍；(c) 在 `infer.dawn`/`rc.dawn` 里把别名 `let` 当透明。
  **裁决：(b)。** (a) 会改 JVM 看到的 Core，要过全部 emit 差分与 Core golden（`7ba051d9` 那种重录）；(c) 要两处各自认别名，违反「两侧读同一份」的契约。
- **Q6，令牌跨 `catch_fault` 与控制（`dawn_ctl`）帧的行为。** 选项：(a) 令牌放 own 槽，靠掩码清零保证清理正确（§4.2）；(b) 禁止令牌跨调用，只在构造器紧邻处配对。
  **裁决：(a)，K3.4 的验收里带一条 effect-handler 语料（单次恢复）下的 ASan 运行。** 若语料揭出问题，退到 (b)，代价是 `incr` 这类「先递归再构造」的形状拿不到复用，所以 (b) 是退路不是首选。
- **Q7，`dawn_rc_leak` 模式与 reuse 的关系（裁决：加显式检查与断言）。** `--rc=leak` 下 `dawn_drop` 是空操作，`rc` 只增不减，所以 `rc == 1` 永不成立，reset 自然走慢路径；快路径还要显式检查 `!dawn_rc_leak`（同 `dawn_array_with`）。
  要有一条断言守它（变异体 (a) 的邻居）。

## 八、不做的（理由）

- **用户可见的 `fip`/`borrowing` 标注。** 理由：Koka 实现里 reuse 不靠它（FP² 脚注），Dawn 不暴露所有权；加语法面的代价（spec、格式器、LSP、文档）远大于它保证的那一点性能契约（Q1）。
- **跨 size class 的任意复用（把 2 字段节点当 5 字段用）。** 理由：slab 按 16 字节类分配，只有同类才能保证 `dawn_free` 对得上；放宽也只放到同类（Q2）。
- **宽掩码（超过 64 字段）与装箱标量（`DAWN_K_BOX`）的复用。** 理由：宽掩码的 `ptrmask` 是指向静态数组的指针，复用要同时换指针，收益面只有极少数大记录；
  装箱是另一个 kind 与大小，属于研究报告的「小值按值展开」那条线。第一版都不参与（宽掩码退回 `adt_new_wide`）。
- **Morphic 式带生命周期的借用类型推断。** 理由：要整程序的别名分析，本仓的借用推断是函数边界的保守不动点，P2 在这个框架内补绑定一层就够测出收益。
- **路径级 dup/drop 融合作为独立 pass。** 理由：见 Q3，拿不到借用参数的那一半，且与 reset 的先后要靠约定。
- **把 `std/pvec.leaf_for` 的 `VLeaf` 臂改成 panic 以去掉一个 dup。** 理由：刀 2 已量过（5.97 → 4.98 dup），但它改 JVM `emit` 字节，要给每个 `emit *` 标签声明 `Emit-Change`；P1 之后同一个 dup 自然消失，不需要动源码。
- **用 reuse 去优化编译器自己的编译墙钟。** 理由：自编译负载上界约 2.5%（§5.4），不是目标；验收只要求自举墙钟不回退，不承诺下降。
- **JVM 侧任何改动。** 理由：JVM 有收集器，rc 这一遍本来就只在 C 路径上跑，这是「刀 N 不改 JVM 一个字节」靠构造而非靠检查成立的原因（`rc.dawn` 文件头）。
- **多线程下的原子唯一性判断。** 理由：运行时当前是单线程非原子 RC（`dawn_rt.h` 头注释），多线程形态已裁决先钉不实施（ffi-llvm-concurrency 裁决）；若将来变，`rc == 1` 的判据整体要重审，不是这一刀的事。

## 九、复现

所有计数与墙钟的脚手架在 agent 的 scratch（WSL 重启会清）：`/tmp/claude-1000/-home-dawn-workspace-dawn-lang/41c80d08-ff29-4bdd-bcaf-8aef4fe819ee/scratchpad/reuse/`
（`build.sh` 从 `.dawn` 经 `dawn __emitc --split` 出 C 并用计数器运行时与原运行时各编一份，`cc.sh` 重编手改的 C，`patch_update.py`/`patch_tree.py` 是三处手改，
`walls.sh` 是墙钟，`rt/` 是挂了计数器的运行时副本，`rt3/` 另挂了邻接环与偷字段统计）。摘要同时写进 `agent-handoff/reuse-design-report-20261007.md`。
