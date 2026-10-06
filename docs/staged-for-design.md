# staged for 设计：让 `for` + `var` 成为库定义的设备循环

> 状态：**current**。编译器刀 S1（2026-10-06）落地：两个 prelude trait `StagedIter`/`StagedVar`、检查器改写、诊断、LSP 配对、
> spec 条文。权威条文在 [spec.md](spec.md) §3.5、§4.5、§4.7、§4.10。
> 未做：S2（tileir 提供 `StagedIter[DRange]`/`StagedIter[DSpan]` 与 `StagedVar[Tile[D]]`，`kernels.dawn` 迁移，golden 零变化），
> S3（设备条件 `if`，`StagedCond[C]`，另起设计）。见 §8。
> 裁决记录在维护者工作区（ruling-staged-for-20261006，调研 research-staged-for-report-20261006）。

## 1. 目标与非目标

目标：kernel 里写

```dawn
var m = broadcast(f_const(F64, neg_inf()), [BQ, 1])
var l = broadcast(f_const(F64, 0.0), [BQ, 1])
var acc = zeros(o)
for j in d_range(0, n_blocks) {
  let s = mmaf(tq, load_at(k, [j]).permute_tile([1, 0]), lit(0.0)) * lit(scale)
  let m_new = max(m, s.reduce_max(keepdims: true))
  let p = exp(s - m_new)
  let alpha = exp(m - m_new)
  l = l * alpha + p.reduce_sum(keepdims: true)
  acc = mmaf(p, load_at(v, [j]), acc * alpha)
  m = m_new
}
store_cell(o, acc / l)
```

记录出与 tileir 0.9 的 `carry`/`get`/`set` 写法逐字节相同的 Tile IR（S2 验）。

非目标：设备条件 `if`；`break`/`continue`/`return`/`?` 穿出设备循环；`while` 的设备版；改变任何不涉及 `StagedIter` 类型的程序。

## 2. 裁决

### D1 语言只认两个 prelude trait，格子类型由值的类型选

```dawn
trait StagedIter[R] {
  type Item
  effect StagedIter = !()
  fn staged_for(r: R, body: fn(R.Item) -> Unit !R.StagedIter) -> Unit !R.StagedIter
}
trait StagedVar[T] {
  type Cell
  effect StagedVar = !()
  fn var_open(v: T) -> T.Cell !T.StagedVar
  fn var_get(c: T.Cell) -> T !T.StagedVar
  fn var_set(c: T.Cell, v: T) -> Unit !T.StagedVar
}
```

id 15 与 16（7..14 已被算术与字面量 trait 占用；用户 trait 的 id 由声明路径派生、在 2^32 之上，`first_minted_id` 只在
prelude 内部移动，不改任何程序的 id）。两者 `injects: false`，不可 derive，prelude 不铸任何 impl。

关联效果成员按算术 trait 的惯例以 trait 自身命名、默认纯（实现中由维护者裁定，推翻设计稿的 `effect E` 无默认值）：

- **不叫 `E`**：一个类型同时实现两者时，泛型代码里的 `T.E` 指哪个成员说不清。这正是算术 trait 当初否决 `E` 的理由。
  以 trait 命名后 `!T.StagedIter` 与 `!T.StagedVar` 各指各的。
- **默认纯**：纯 impl 什么都不用写，与 `Add`…`Neg`、`FromInt`/`FromFloat` 一致；记录型的库照旧绑定自己的效果
  （tileir：`effect StagedIter = !Dev`）。

否决的替代：
- **一个 trait，格子类型由迭代器选**（`StagedIter` 里 `type Cell[T]`）：需要带参数的关联类型（高阶），Dawn 没有。
- **一个 trait，格子通用**（`fn cell[T](v: T)`）：宿主 `Int` 也能进格子，体被记录一次后静默算错。
- **Lean 式状态元组 + `ForIn`**：库要拆元组，需变长泛型或元组结构 trait。逐变量格子绕开了它。
- **只在 tileir 里做**（K2 现状的组合子）：保留为底层；本设计是它的语法。

### D2 脱糖在 checker 内完成，产出现有 TAST 节点

`for pat in e { B }`，无 `..`，`e: R` 且 `R` 有 `StagedIter` impl（具体类型查 impl 表，类型参数查其 bound，不透明类型先问自己再问目标）：

```text
{ let $staged = e                       # 外层求值一次，先于一切格子
  let m = var_open(m) ...               # 每个被携带的 var 一个格子，按声明序
  staged_for($staged, (j) => { B' })    # 非 PBind 的 pattern：($item) => { let pat = $item; B' }
  m = var_get(m) ... }                  # 写回，同序
```

`B'` 中对被携带名字的读变 `var_get(cell)`，写 `x = v` 变 `var_set(cell, v)`。用到的节点是 `XBlock`、`TSLet`、`TSLetPat`、
带 `trait_id` 的 `XCallFn`、`XLambda`、`TSAssign`；`lower.dawn`、`interp.dawn` 与两个后端零改动。效果按 `arith_call` 的路子记：
每个 trait 调用把 impl 绑定的效果记在调用点，证据随调用走。

否决的替代：
- **AST 级重写**：读写的重写必须尊重遮蔽，AST 层要再实现一遍作用域；checker 的 `resolve_local` 已经是唯一的作用域答案。
- **新增 `TSStagedFor` 节点交给 lower**：lower 与两后端都要动，没有收益。

### D3 格子集合：体中按作用域解析到外层 `var` 的名字

- 读与写都算（只读也进格子）。
- 体里声明的 `var` 是体自己的；归纳 pattern 的绑定不算；被体内 `let` 遮蔽的同名不算。
- 解析到 `var` 但其类型没有 `StagedVar` impl：错误（D6），不退化为宿主语义。
- 嵌套 staged 循环：内层提到外层 staged 体之外的 `var` 时复用外层格子（穿过，不另开）；外层体内声明的 `var` 由内层自己开。
- 外层 `let` 不是格子，照 §4.5 按值捕获。

**收集方式（偏离设计稿，见 §3 偏离 A）**：不在检查体之前用 `name_refs` 预先遍历，而是在唯一一遍检查体的过程中惰性收集。

否决的替代：
- **只收被赋值的**，只读的按值捕获：`staged_for` 的体交给用户 impl，可能被留存后调用；这正是 §4.10 `with` 糖区拒读 `var` 的理由。
- **同名即算（不看遮蔽）**：对被体内 `let` 遮蔽的外层 `var` 误报。
- **两遍检查（先试查体，记录哪些 `var` 被写）**：诊断重复、检查状态要回滚。

### D4 体内的名字仍解析到原 `var` 的符号

`LambdaCx` 加 `staged_loop: Bool` 与 `staged: Map[Int, StagedCell]`（原 `var` 的符号 id → 格子局部、值类型、`StagedVar` 见证、
首次提及位置）。`resolve_local` 找到一个跨过 staged 帧的 `var` 时：从最外层被跨过的 staged 帧起，staged 帧捕获格子局部（首次时铸格子），
其余闭包报错；返回值仍是原 id。`check_var`/`check_assign` 看到该 id 在某个 staged 帧的表里，就产出 `var_get`/`var_set`。

否决的替代：**像 handler 格子那样让体内名字解析到另一个 Sym**：LSP 会看到两个符号，重命名断开。

### D5 携带序 = `var` 的声明序

格子按 `var` 声明位置的文本序（符号的 `dlo`）打开；tileir 按创建序携带，于是携带序 = 声明序。体检查完之后才排序，
所以体里首次提及的先后不会漏进携带序（偏离 A 带来的风险，由测试守住，见 §6）。

否决的替代：赋值点序（flash_attn 会从 `m, l, acc` 变为 `l, acc, m`，语句重排即改字节）；名字字典序（改名即改字节）；
首次出现序（读写顺序调整就改字节，且与 K2 创建序不一致）。

### D6 诊断

| 情形 | 文案 |
|---|---|
| 体里读/写一个类型没有 `StagedVar` impl 的外层 `var`（在首次提及处报一次） | ``"`n` is a `var` of type Int, which a staged loop cannot carry (no `StagedVar[Int]`)"``；hint ``"the body is recorded rather than run once per iteration; compute it with a `let` before the loop, or declare the `var` inside the body"`` |
| `break`/`continue`/`return`/`?` 在体内 | ``"`break` cannot leave a staged loop: its body is handed to `staged_for` once, as a closure, and recorded rather than run here"``，四个关键字同句；hint 各一：`break` 提库自己的带出口循环（tileir: `d_loop`），`continue` 提用 `if`，`return` 提循环后计算，`?` 提体内 `match` |
| 体内普通 lambda / `with` 糖区 / handler 臂碰格子名 | ``"`m` is carried by the staged loop and a lambda cannot capture it"``（另两种闭包各自点名）；hint ``"bind it to a `let` inside the loop body first"`` |
| `R` 同时有 `Iter` 与 `StagedIter` | ``"`R` implements both `Iter` and `StagedIter`, so `for` cannot tell a host loop from a staged one"``，点在 `e` |
| 体的效果超出 `R.StagedIter` | ``"this staged loop's body performs !io, but `StagedIter[Span]` declares !Rec"``；hint ``"a staged loop body is recorded, so it may only perform what `StagedIter[R]` declares"`` |
| `for x in a..b` | 不变，区间永远是宿主循环 |

跳转文案与设计稿的「runs as the device loop」不同：语言层的 staged 循环不一定是设备循环（§6 的 `Times` 就在宿主上跑 n 遍），
所以句子只说语言知道的事：体是交给 `staged_for` 的闭包。

### D7 范围：第一刀只做 `for`

`if`/`while`/`match` 不做；设备条件 `if` 以并列 trait `StagedCond[C]` 另起设计（S3）。

## 3. 实现中对设计稿的偏离（已获批准）

**偏离 A：格子集合惰性收集，不预先跑 `name_refs`。** 设计稿 D3 说遍历复用 `checker.name_refs` 并补赋值目标名。实测 `name_refs`
是调用图的过近似：`x.f()` 会把方法名 `f` 记成一个引用（它要服务 UFCS 排序，宁多勿漏）。拿它做格子集合，外层恰好有个
`var f` 时就会多开一个没用到的格子，若其类型没有 `StagedVar` 还会多报一条错误。改成在唯一一遍检查体时，由 `resolve_local`
在名字首次跨过 staged 帧时铸格子（`resolve_staged`/`mint_staged_cell`），体检查完后按声明序排出要打开的那些
（`staged_opens`）。作用域规则、读写都算、体内自声明不算、声明序这四条语义与 D3/D5 完全相同；精度更高，且不需要第二套作用域遍历。
风险是首次提及序可能漏进携带序，对策是排序放在体检查之后、只看 `dlo`，并有专门的测试（§6 第 1 条）与变异负控（M1）。

**偏离 B：格子有自己的局部符号，但共享原 `var` 的声明位置。** D2 的 `let x$ = var_open(x)` 本身就需要一个局部符号承载格子，
lowering 读的是它。体内的名字照 D4 解析到原 `var`；格子符号的 `name` 与原 `var` 相同，`dlo`/`dhi` 拷贝原 `var` 的声明位置，
不放进任何作用域（没有拼写能找到它）。LSP 走到 `var_get`/`var_set` 时用格子符号回答，定义、引用、重命名因此落在原 `var` 上，
不出现第二个可见符号，D4 否决的问题不会发生。没有给 `Sym` 加字段（那会改到 `lower.dawn` 与 `jvm/emit.dawn` 的构造点）。

## 4. 一致性陈述

- §4.5「闭包按值捕获、拒绝捕获 `var`」不变。staged 格子是 §6.5 handler 格子之外第二个**以格子身份穿过授权闭包**的名字来源，
  授权闭包是 staged 体（及其内嵌 staged 体）；其他闭包照旧。
- §4.10 `with`：两者都是作者没写出来的闭包；`with` 对之前的 `var` 一律拒，staged for 对能进格子的放行、其余拒。
- §4.7：`e` 恰求值一次、pattern 不可反驳（与宿主 `for` 共用 `check_for_pattern`，文案相同）、绑定只在体内可见，全部原样适用。

## 5. 改动清单

| 文件 | 改动 |
|---|---|
| `selfhost/src/check/types.dawn` | `STAGED_ITER_ID = 15`、`STAGED_VAR_ID = 16`，两个 `TraitI`（效果成员以 trait 命名、默认纯），`prelude_trait_ids` |
| `selfhost/src/check/cx.dawn` | `StagedCell`；`LambdaCx.staged_loop`、`LambdaCx.staged` |
| `selfhost/src/check/checker.dawn` | `check_for` 分派；`check_staged_for`、`check_staged_body`、`staged_opens`、`staged_call`、`staged_read`、`staged_write`；`resolve_local` 的 staged 臂；`check_var`/`check_assign` 的 staged 臂；跳转三处的 staged 文案；`check_for_pattern` 抽出 |
| `selfhost/src/lsp/lspq.dawn` | `SFor` 与改写块配对（悬停、定义、引用、补全里的循环变量）；`var_get`/`var_set` 回答为原 `var` |
| `selfhost/src/doc.dawn` | 两段 prelude trait 文档 |
| `selfhost/src/ir/*`、`jvm/*`、`c/*`、`main.dawn` | 不改（`main.want_iface` 已读 `prelude_trait_ids()`） |

## 6. 测试

- checker 内联：声明 `m, l, acc, unused`，体中首次提及序与赋值序都是 `acc, l, m`，断言打开与写回都是 `m, l, acc`，`unused` 不开，
  体内声明的 `var k` 不开；只读 `var` 进格子、被 `let` 遮蔽的名字不算；嵌套时内层只开外层体内声明的 `t`、外层的 `s` 穿过；
  宿主 `Int` 的 `var` 只在首次提及处报一次。
- `scripts/spike-native/staged_for.dawn` 两后端对拍（JVM、C、ASan）：`Span` 是记录式迭代器（体只跑一次、格子的开/写打成转写），
  `Times` 是宿主上跑 n 遍的迭代器、格子放在 handler 状态里（`fib(10)` 得 55）；`Num` 同时实现两个 trait，在同一个循环里既被迭代又被携带（`both` 得 75）；含嵌套 staged、staged 里套宿主 `for`、
  宿主 `for` 里套 staged、只读 `var`、遮蔽、泛型 `[R: StagedIter]`。
- `scripts/checker-corpus/cases/staged_for.dawn`：D6 每条文案逐字。
- LSP（`lsp/server.dawn`）：体内读、写、循环后读的引用是同一组，悬停 `var acc: V`，定义落点与普通读相同，循环变量是绑定。

变异负控（每条先证明会红）：

| 变异 | 红的门 |
|---|---|
| M1：格子按首次提及位置排序（在这些用例里与赋值点序相同） | 内联「declaration order」测试；`staged_for.expect` 的 `carry` 顺序 |
| M2：只读不进格子（只有写或已开格子的名字走 staged 臂） | 内联「declaration order」与「read-only」两条；corpus 的宿主只读用例文案变为 `lambdas cannot capture`；spike 编不过 |
| L1：LSP 不认改写块 | LSP 测试的引用列表 |

字节：普通 `for` 与现有程序不变（报告见维护者工作区 staged-for-k1-report-20261006）。

## 7. 一致性之外的开放问题

0. **泛型携带受 D6 限制**：`fn f[T: StagedIter + StagedVar](t: T) { var acc = t; for i in t { acc = .. } }` 被拒。
   体要付 `T.StagedVar`，迭代器的行只声明 `T.StagedIter`，两个不同的投影互不包含（corpus 用例 `generic_carry`）。
   具体类型（tileir 的 `!Dev` 两边相同）不受影响。要放开，得让 `staged_for` 的体行多带一个效果变量，或者允许 impl 声明
   两者等同，留待有真实泛型 kernel 时再议。

1. `lit` 初值：`StagedVar[Tile[D]]` 的 `var_open` 走 `carry`，拒无格式初值；第一刀初值写 `f_const`，等 GPU 格式标签调研再定。
2. `d_for` 名字是否作为 `d_span` 的别名保留（S2 决定）。
3. 悬停是否追加「carried by the staged loop」一行。

## 8. 刀序

| 刀 | 内容 | 状态 |
|---|---|---|
| S1 | 编译器：两个 prelude trait、改写、诊断、LSP、spec、spike 对拍 | 本刀 |
| S2 | tileir：描述符 + 三条 impl + `kernels.dawn` 迁移，golden 零变化（负控：按赋值位置排序使 flash_attn 变红） | 待 S1 合入 |
| S3 | staged `if`（`StagedCond[C]`），另起设计 | 之后 |
| 重开项 | `continue` 映射为体内 `return ()` | 有真实 kernel 需要时 |

## 9. 不做的（理由）

1. 状态元组式线程化：需变长泛型或元组结构 trait；逐变量格子取代之。
2. 全局允许闭包捕获 `var`（Scala/Kotlin 装箱）：改 §4.5 的全局语义。
3. 宿主 `var` 在 staged 体里按宿主语义：体被记录一次，宿主值只在记录时算一次，静默算错。
4. `break`/`return`/`?` 离开 staged 体：设备 `for` 无 break，数据决定的退出由库自己的循环（tileir `d_loop`）覆盖。
5. staged `while`：`d_loop` 体跑到底，store 会多发一次，不能忠实实现 `while`。
6. 赋值点序、首次提及序或字典序携带：语句重排、读写调整或改名就改字节。
7. 编译器把携带集合交给库、省掉试跑：格子类型异构，列表写不出类型。
8. 迭代器选格子类型：需要高阶关联类型。
9. 新 TAST/Core 节点：脱糖只需 checker 信息，lower 与两后端无需知情。
10. 方法名注入：由语言消费的 trait 不注入（`Index`/`Display` 先例）。
11. 第一刀做 staged `if`：值形式、缺省 else、match 都要另答。
12. 用 `name_refs` 预收集格子集合：过近似（方法名算引用），会多开格子、多报错误（偏离 A）。
13. 给 `Sym` 加「格子来源」字段让 LSP 回指：要改 lowering 与 JVM 后端的构造点；共享声明位置已足够（偏离 B）。
14. 效果成员叫 `E` 或无默认值：同时实现两者的类型上 `T.E` 有歧义；纯 impl 被迫写空绑定，与其余由语言消费的 trait 不一致。
