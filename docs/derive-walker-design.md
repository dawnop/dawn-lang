# 派生关系合用一个 walker：Eq / Ord / Hash / Show 的描述记录与结构遍历

> 状态：**current**。2026-10-01，issue #199、#200（分支 `fix/derive-walker`）。
> 调研是 `research-code-debts-20260930` 的 #199、#200 两节与「分批」的批 D；本文记形状、
> 保留下来的四处差异及其理由、证明「什么都没变」的办法。

## 问题

`selfhost/src/ir/lower.dawn` 的 `prim_relation` 把语言自己定义的四个关系分给四个函数
`eq_at`、`cmp_at`、`hash_at`、`show_at`。每个都各写一遍同一套东西：

- 八步派发：Unit → 标量 → 显式 impl → 剥 opaque → ground 展开 → 作用域里的字典 →
  带子目标展开 → 兜底；
- 一个 `X_through_dict`（经字典槽调用，参数装箱）；
- 一个结构体：元组逐分量、ADT 单构造器逐字段、多构造器按构造器链。

四份之间只有叶子操作和「部分怎么合起来」不同。walk 的形状要改（新的类型构造、opaque 或
ADT 字段怎么读）就得改四遍，没有任何东西检查四份一致（#199）。同一处，`show_at` 用一串
`if t == TyInt` 自己判标量，`types.is_show_scalar` 于是只有测试调用者（#200）。

## 形状

### 描述记录 `Rel`

```
type Rel = {
  tid, method, arity, ret,
  unit_answer,        # Unit 处的常量答案，也是结构函数体建好之前的占位体
  is_scalar,          # is_eq_scalar / is_ord_scalar / is_hash_scalar / is_show_scalar
  scalar_op,          # 标量叶子
  peels_opaque,       # Show 为 false
  ground_is_final,    # Show 为 false
  fallback,           # foreign_eq / no_ordering(panic) / foreign_hash / show_erased
  fold,               # 一个 arm 的各部分怎么合起来
  skips_bare,         # Hash 为 true
  union               # 多构造器链的首尾：链的初值、链前链后要不要再包一层
}
```

四个关系各是一个 `fn X_rel() -> Rel`。`eq_at` / `cmp_at` / `hash_at` / `show_at` 保留原签名，
各自是一行 `rel_at(st, X_rel(), [..], t)`：调用点（`==` 运算符、`to_str`、`prim_relation`）
与 `display-layering-contract/mutate.py` 的文本锚 `show_at(st, e, t)` 都不用动。

结构函数的名字由 `method` 拼出（`"struct" ++ method ++ "$"`，正好是原来的
`structeq$`/`structcmp$`/`structhash$`/`structshow$`），所以不另设前缀字段。

### 统一派发 `rel_at`

原来四份的八步照抄成一份，只在两处读 `Rel` 的开关：`peels_opaque` 决定剥不剥 opaque，
`ground_is_final` 决定 ground 但不可展开的类型是否直接兜底。`X_through_dict` 合成
`rel_through_dict`，按参数个数逐个 `adapt_in`。

### 结构遍历 `components` 与 `arm_parts`

`components(st, t)` 把类型的结构读一次：元组是一个 arm（`ci = -1`，分量 `[(i, et)]`），
ADT 每个构造器一个 arm（`(ci, [(idx, ft)])`，`ft` 经 `concrete_field_ty`）。
`arm_parts(st, rel, xs, sc, arm)` 对一个 arm 的每个分量取出各操作数的那一格（元组
`CTupleGet`，字段 `read_field`），递归 `rel_at`，从左到右。**递归只有这一处**，负控就打在这里。

### 四种 fold 与多构造器链

`rel_body` 是结构函数体：只有一个 arm（元组、单构造器）时 `rel.fold(.., None)`；
多个 arm 时交给 `rel.union`，它拿到一个 `chain(st, init)` 回调，回调从最后一个构造器往前，
对每个 arm 先 `arm_parts` 再 `rel.fold(.., Some(init))`，用 `CIf(CIsCtor(x0, aid, ci), 这一臂, 其余)`
接成链，最后的 `else` 是 `init`。

| 关系 | fold（唯一 arm） | fold（链中一臂） | union |
|---|---|---|---|
| Eq | conj（空为 `true`） | 再要求 `b` 同一构造器；无字段时只剩这条 | 初值 `false` |
| Ord | lexicographic | 同左 | 初值 `0`，链外先比 tag（-1/1） |
| Hash | mix 从 1 起，末尾 narrow32 | mix 从 tag 种子起，不 narrow | 先取 tag 局部变量，种子 `mix(1, tag)` 即初值；整链外 narrow32 |
| Show | cat：`(a, b)` 或 `Name`/`Name(..)`/`Name { f: .. }` | 同左 | 初值 `""` |

## 有意保留的差异

四份不是纯粹的漂移，有四处是决定。统一后它们都是 `Rel` 的数据，不抹平：

1. **Show 不剥 opaque**（`1307c282`）。一个没有自己 `impl Show` 的 opaque 类型没有渲染：
   继承目标的渲染会把类型要藏的表示打印出来，checker 在 lowering 之前就拒了它。另外三个
   关系答的是真假或符号，不泄露表示，所以仍按目标比较（spec §2.7）。
2. **ground 但不可展开的类型，Show 先问作用域里的字典**（`ground_is_final = false`）。
   另外三个关系在这里直接兜底；Show 自 `637f9c42` 起的写法是「ground 且可展开才走结构，
   否则落到字典查找」。两者只在字典环境里恰有一个 ground 且不可展开的键时（例如一个非 ground ADT
   的某个类型实参是 `TyJava`）才分叉。它是否有意没有记录；本批是纯重构，Core 只证明「没变」，
   不证明「改了也对」，所以原样保留，不在这里顺手统一。
3. **兜底各异。** Eq/Hash 兜底是宿主的关系（`java_eq`/`java_hash`，非 Java 值 panic）；
   Ord 没有兜底，走到尽头是编译器 bug（checker 在没有 impl 与 derive 的地方拒 `Ord`）；
   Show 兜底是擦除后交给运行时的 `CIntrinsic("show")`，理由见 `show_erased` 的注释（JVM 有
   best-effort 答案、native 会拒并说出类型，删掉它会让没预见到的类型在两个后端都 panic）。
4. **Hash 的链跳过无字段构造器并带 tag 种子；Ord 在链外先比 tag。** Hash：无字段构造器的答案
   就是种子，也就是链的 `else`，所以不需要一臂（`Ty`、`Head` 这种全是裸 tag 的联合一次测试都
   不写）；tag 作为前导字段折进去，否则所有无字段构造器落在同一个桶里。Ord：构造器声明序在先，
   tag 不同答 -1/1（spec 3.5 只约定符号），相同再进链。Eq 的链则要求 `b` 与 `a` 同构造器。

## 顺序约束与证明办法

`fresh_sym` 是 `LSt` 里的计数器，结构函数的参数、字典参数、`lexicographic` 的 let、Ord 的两个
tag 变量、Hash 的 tag 变量都从它取号；`st.lifted` 的追加顺序也随递归顺序走。只要调用顺序变一处，
其它模块里合成的 `structeq$..` 等函数的局部编号或顺序就会变。所以**调用顺序逐行对齐原实现**：

- 元组分量、字段从左到右；多构造器从最后一个往前；
- Ord：每一臂先算完各字段再做该臂的 `lexicographic`，全链之后再取 `ta`、`tb`；
- Hash：tag 变量在所有臂之前取；
- 结构函数先取 `arity` 个参数号，再按子目标逐个取字典参数号。

证明分两层：

- **`selfhost-core-diff.sh --base origin/main`**：selfhost 全部模块（含 std 与源码包）与三个程序
  （calc、traits、eqhash）的 Core。判据是只有 `ir.lower` 自己变（它的源码变了），其余逐字节相同。
  （任务单写的 `scripts/core-golden/` 已由 `recorded-numbers-design.md` 降为这条按需脚本，树里没有
  golden 可录，也就谈不上重录。）
- **更宽的语料**：同一个 worktree 里先用 origin/main 的 `lower.dawn` 重建工具链，对
  `examples/` 全部单文件与项目、`packages/*`、`site`、`playground`、`compiler-plan`、`selfhost`
  逐个 `__lower --dump`；再换回本分支重建、再 dump，逐文件比较。同一目录两次，避免两个 worktree
  把绝对路径烘进 panic 串的假差异（arch-split 备忘录第 3 条）。

负控：让 `components` 对元组少给最后一个分量，四个关系的测试都要红，Core 比较也要红。

## 不做的（理由）

- **不改 hash 算法**：种子 1、`31*h + part`、tag 作前导字段、末尾 narrow32 都是既有数字，
  改了就是改所有程序的 Map 分布与 Core，属于另一个决定。
- **不改 Show 渲染**：`Name { f: v }` 等形状逐字保留，任何程序的输出都不该因为这次重构移动。
- **Index 不纳入**：`index_at` 不是结构关系（参数 1 是 `C.Idx`、答案是元素类型，没有「对各部分
  做同一件事再合起来」的形状），塞进 `Rel` 只会多出只对它有意义的字段。
- **不统一差异 2**：见上。要统一先得证明分叉处不可达或给出新答案的理由，那是语义改动，不在纯重构里做。
- **不删 `is_show_scalar`**：它现在是 Show 的 `is_scalar`，删了 Show 会成为四个关系里唯一不经
  `*_scalars` 表判标量的那个（#200）。

## 落地

（实现后回填：提交、净减行数、Core 比较结果、负控输出。）
