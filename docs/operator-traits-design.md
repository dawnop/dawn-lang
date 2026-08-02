# 运算符 trait 设计 — `[]` 背后的 `Index`

> 状态：proposed（任务「刀 3 运算符 trait」，#44 关联类型的最终消费者）。
> 三条合同级决策由用户于 2026-08-02 定案（§2 的 D1/D2/D3）；D4–D10 是本文的裁决，
> 可推翻。
>
> 勘察基线 **334ba4d**，文中 file:line 与实测输出均对该提交，已逐条复核——勘察备忘录
> 给的行号有多处漂移，本文用的是复核后的。前置阅读：
> [assoc-types-design.md](assoc-types-design.md)（刀 1/刀 2 已落地，`Index` 用的就是它的
> `type Item` 与 `T.Item`）、[prelude-namespace-design.md](prelude-namespace-design.md)
> §7（它专门为本刀交付了三件接口）、[trait-v2-design.md](trait-v2-design.md) §7.4/§7.5
> （本文回答它留下的两个未答问题）。落地后权威条文进 [spec.md](spec.md)，落点清单见 §5。

## 1. 目标与非目标

**目标**：让 `xs[i]` / `m[k]` 的硬编码特判退休，改由 prelude trait `Index` 求解，
从而**用户自定义类型可以支持 `[]`**。

今天 `index_wanted`（checker.dawn:4314-4325）用两条 arm 穷举 `[]` 的全部合法主体：

```dawn
match tt {
  TyList(elem) -> (cx, Some((TyInt, elem, false)))
  TyMap(k, v) -> (cx, Some((k, v, true)))
  _ -> ... "`[]` indexes a List or Map, got " ...
}
```

这是**表达力**项目，不是纯洁性欠账（trait-v2-design §7.4 的定性）。它同时是 #44 关联类型
唯一还没兑现的那笔收益：`Iter` 已经在刀 2 兑现了 `for..in`，`Index` 兑现 `[]`。

**非目标**：

- **`xs[i] = v`（`IndexSet`）**——判为不做，理由写死在 D8。
- **String / Bytes 的 `[]`**——D3 定的范围之外。
- **比较族与算术族**——`<`/`==` 不碰（D3），算术今天连 trait 都没有，是另一件事。
- **多参数 trait**（`Index[C, I]`）——trait 恰有一个类型参数（spec §3.5:414），本刀不动它；
  代价见 D4。
- **切片 `xs[a..b]`**——需要同一个容器有第二个索引类型，被 D4 的单参数形状永久排除到
  多参数 trait 之后。留档在 §7。

## 2. 裁决记录

### D1 主路线 = prelude 铸 impl、体在编译器里（用户定案 2026-08-02）

trait-v2-design §7.5 摆了两条路，用户选**路 ②（`prim_relation`）**：`Index` 是第六个
prelude trait，`List` 与 `Map` 的 impl 由 prelude 铸出来（`prelude_impls()`，
types.dawn:1177），impl 体不写在 std，而是 `lower.dawn` 的 `prim_relation`
（lower.dawn:842-849）加一条 `INDEX_ID` 臂——与 `Eq`/`Ord`/`Hash`/`Show` 今天的分工完全同构。
**用户自定义类型仍走正常 impl body 路径**，一个字都不特殊。

三条理由，勘察已证：

1. **保住 `CIntrinsic("list_index")` 作为 List 的降级形**，comptime 折叠不退化。
   emit.dawn:2235-2247 把这条写成明写约束：list 原语「stay Core intrinsics rather than
   becoming calls in lowering… Keeping the primitive in Core keeps
   `const B: List[Int] = [A, 4]` working」。走路 ①（`get(xs, i).expect(…)`）会把 `[]`
   变成对 `std/pvec` 的调用，comptime 就得解释 `array_*`，而它拒绝 `array_*`。
2. **不触发 std 模块序死结**。`std/modules.txt` 把 `hamt`/`pvec` 排在最后（「Nothing in
   std imports this module and nothing should」，std/hamt.dawn 头注），而它们正是 `[]` 的
   实现载体，且它们自己也用 `[]`（std/set.dawn:46/59/70/99、std/map.dawn:75/92/106/147）。
3. **JVM 侧不引入每次下标一个 `Option` 分配**。Perceus 只跑 C 后端，而自举、fixpoint、
   core-diff、run-diff 全在 JVM 上。

**代价，必须写死**：trait-v2 §7.4 当初「把两条 arm 挪进 std」的立意**落空**——arm 从
checker 挪到 lower，挪了一个文件，没挪进 std。这句写在这里，免得第三次被同一条推断绊倒
（§7.4 被 §7.5 推翻过一次，§7.5 自己又被这条裁决收编）。收益不是「编译器少两条 arm」，
是「用户类型能写 `[]`」——按后者验收，不按前者。

### D2 opaque 穿透 = 允许（用户定案 2026-08-02）

`opaque type Vec = List[Int]` 自动获得 `[]`，与它今天已经自动获得 `==` / `${}` /
`for..in` 一致。这是**可观测的接受集扩张**，实测见 §3.3。

不需要新机器：`resolve_witness`（checker.dawn:5722-5733）与 `assoc_impl_of`
（checker.dawn:1266-1277）都已经「先查 opaque 自己的 impl，没有就落到 target」。
本刀只要让 `[]` 走 `resolve_witness`，穿透就是白送的。

**但 assoc-types-design.md 的 D9 措辞与落地代码不符**：D9 写着「先查 opaque 自己的
impl，无则**不**穿透到 target……witness 不穿透，投影也不穿透」，而
checker.dawn:1266-1268 的注释写的是「or -- for an opaque subject with no impl of its own
-- its target's, **the order resolve_witness uses**」，代码确实穿透。这是勘误，列进本刀
的收口清单（§6 刀 2）。

### D3 范围 = 只动 List / Map（用户定案 2026-08-02）

- **String / Bytes 不给 `[]`**。`s[i]` 的「码点还是字节」语义、以及 O(i) 扫描伪装成
  O(1) 下标的问题（spec §2.1:88-90 已经为此把逐字符遍历引向游标），与 #90 Char 耦合，
  不该顺手定。
- **比较族 `<` / `==` 一律不碰**。`<` 对 Int/Float/String 的 native fast path 是必须保留的
  豁免：`docs/audit/re-audit-b-decisions.md:508-513` 已经把「Float 仍能 `<`、仍不能
  `[T: Ord]`」立为将来那次改造的验收标准。本刀不碰它，但**文档要写明不碰**——那条 audit
  条目点名的正是「若将来 `<` 统一路由到运算符 trait」，读者会以为刀 3 就是那次。它不是。
- **算术族一律不碰**。今天完全硬编码、连 trait 都没有。

顺带一条勘察没提的事实：`Index` 一旦存在，**用户模块也写不出 `impl Index[String]`**——
孤儿规则（checker.dawn:2893-2906）要求 impl 住在 trait 或主体类型的声明模块，而
`Index` 的 `owner` 是 `None`（prelude），`String` 的 head owner 是 `std/str`
（`head_owner`，checker.dawn:2750-2761）。所以对用户，D3 的范围是**机器强制的**；
只有 std 自己（`std/str` / `std/bytes`）能违反它，而那需要一次显式裁决。

### D4 `Index` 的形状 = 两个关联类型 `type Idx` + `type Item`

```dawn
trait Index[C] {
  type Idx
  type Item
  fn index(c: C, i: C.Idx) -> C.Item
}
```

选型理由：

- **单参数 trait 是硬约束**（spec §3.5:414「trait 恰有一个类型参数」）。Rust 的
  `Index<Idx>` 把索引类型放在**类型参数**位，于是 `Vec<T>` 能同时 `Index<usize>` 与
  `Index<Range>`。Dawn 写不出来，所以索引类型只能是第二个**关联类型**。
- **推断没有障碍**。#119 D6 已定：投影在参数位**只参与检查、不参与推断**，类型参数须由
  非投影参数位定下。`fn index(c: C, i: C.Idx) -> C.Item` 的 `C` 在第 0 参，是非投影位——
  这与 `Iter` 的四个方法把 `c: C` 放在第 0 位是同一个理由（prelude-namespace §4.5 已实测）。
- **`C.Idx` 就是今天的「wanted 类型」**。`index_wanted` 今天返回 `(want_idx, result, on_map)`，
  前两项分别是 `C.Idx` 与 `C.Item` 的另一种拼法。形状是 1:1 对上的，不是新发明。
- **与 `Iter` 的 `Cur`/`Item` 同构**，双关联类型的机器在刀 2 已经跑通并被 `assoc_abi.dawn`
  钉住。

命名：`Idx` 而不是 `Index`（成员名与 trait 名同名，错误消息里读作 `C.Index`，费解）；
不用 `Key`（List 的索引不是键）。

**代价，写死**：一个容器**只能有一个索引类型**，直到多参数 trait 出现。这条直接排除了
`xs[a..b]`（切片要第二个索引类型）经由同一个 trait 实现——切片将来要么等多参数 trait，
要么另立方法名。这是 D4 唯一实质的损失，写在这里而不是等它变成惊讶。

### D5 方法名 = `index`，且 `injects: false`

`Index` 建成 `injects: false`（prelude-namespace D1/§4.2 交付的字段），方法名不进任何模块的
函数命名空间。于是 `index` 这个名字只出现在三处：impl 体、`dawn doc`、错误消息
（prelude-namespace §4.4 已论证这三处都不需要全局名）。

**勘察这条说错了，订正在此**：勘察说「`index` 全仓 0 处顶层 fn 占用」。实际有两处——
`std/pvec.dawn:162` 与 `std/hamt.dawn:265` 都声明了 `pub fn index`。但它们**不是隐式可见的**
（`std/hamt`、`std/pvec` 不进 `std_fns`；实测 §3.4），所以裸 `index(...)` 今天报的是
「`index` is not a builtin; use std/pvec, then pvec.index(...)」，而用户写
`fn index(x: Int) -> Int` 完全合法。

结论仍然成立，但理由要改：`injects: false` 之后这个问题**根本不发生**，撞名勘察是多余的
（这正是 prelude-namespace D1 买的东西）。而且名字选得恰好：`prim_relation` 的 Map 臂
最终调的就是 `hamt.index`，`impl Index[Map]` 与 `hamt.index` 同名不是巧合而是同一件事。

**一条副作用要记账**：`injects: false` + prelude trait 方法不进 `dawn doc`（实测：
doc.dawn:434 的 `prelude_traits()` 只当 `sig_render` 的查表用，doc.dawn:186-208 的 trait
渲染按 `owner` 过滤而 prelude trait 的 owner 是 `None`）→ **`Index` 在 `dawn doc` 里一个字
都不会出现**。用户想知道怎么给自己的类型实现 `[]`，只能查 spec §4.8。这与
prelude-namespace §6 记的「prelude trait 方法做 doc 渲染是『标准库发现性』那件事」同一笔账
（`stdlib-discovery-docs` 备忘录），本刀不做，但 spec §4.8 必须自带 impl 示例，见 §5。

### D6 Map 三个 witness 的迁移 = 诊断位置**不变**，只有措辞变

今天 `index_wits`（checker.dawn:4330-4343）在 `[]` 现场解 EQ/HASH/SHOW 三个 witness，
checker.dawn:4327-4329 的注释说「A missing one is reported here, at the `[]`, rather than
surfacing as a gap while lowering」。

**裁决：这条注释的**实质**不作废，只是它的机制说法作废。**证据在
checker.dawn:5757-5767：条件 impl 的 `sub_goals` 循环把**同一个 `lo, hi, requirer`**
递归传给每个子目标。所以迁到
`impl[K: Eq + Hash + Show, V] Index[Map[K, V]]` 之后，三条诊断仍然打在 `[]` 的 span 上。
`sub_goals`（types.dawn:737-756）把 `constraints[i]` 对上 `type_args_of(subject)[i]`，
`Map[K,V]` 的 args 是 `[K, V]`，于是子目标恰好是 `(Eq,K) (Hash,K) (Show,K)`——**顺序也与
今天 `index_wits` 的 `for tid in [EQ_ID, HASH_ID, SHOW_ID]` 一致**。

**新措辞**：`resolve_witness` 的 requirer 参数今天是 `"indexing a Map"`。迁移后只有一个
调用点，requirer 不能再按类型分档（那正是本刀要退休的特判），定为 **`"indexing"`**。
可观测变化就是少了「a Map」两个字：

| | 今天 | 改后 |
|---|---|---|
| `fn look[K](m: Map[K,Int], k: K) = m[k]` | `indexing a Map requires \`Eq[K]\`, but \`K\` has no such bound`（三条，hint 各自 `add the bound: [K: Eq]`） | `indexing requires \`Eq[K]\`, …`（三条，hint 不变） |
| `fn f[C](c: C, i: Int) = c[i]` | `\`[]\` indexes a List or Map, got C` | `indexing requires \`Index[C]\`, but \`C\` has no such bound` + hint `add the bound: [C: Index]` |

第二行是白捡的改善——今天那条消息对一个类型参数是纯误导。

checker.dawn:4327-4329 的注释迁到 `prelude_impls()` 里那条 Map impl 旁边，改写成
「Show 只为把缺的键印进 panic 文本，这是三条 bound 里唯一不是为了找到条目的那条」——
`std/hamt.dawn:264-266` 已经有同样的话，两处指同一件事。

### D7 `[]` 用在不可索引类型上的诊断 = 保留专属措辞，不落到通用的 `no impl of`

若照直走 `resolve_witness`，`true[0]` 会得到通用消息 `no impl of \`Index\` for \`Bool\``。
那比今天差：今天的 hint（「when absence is a normal case, use get(xs, i) / map_get(m, k)
instead」）是这条诊断最有用的部分。

**裁决**：EIndex 先用 `impl_at`（含 opaque 穿透，与 `resolve_witness` 同一顺序）探一下，
主体是 ground 且无 impl 时打专属消息，其余情况才交给 `resolve_witness`：

```
error: `[]` needs an `Index` impl for `Bool`
  = hint: List and Map have one; when absence is a normal case, use get(xs, i) / map.get(m, k)
```

hint 的后半段与今天逐字相同（顺手把 `map_get` 改成 `map.get`——`map_get` 不是今天的拼法）。
`checker.dawn:4430` 那条内联 test 断言的 `"indexes a List or Map"` 随之改成
`"needs an `Index` impl"`。

### D8 `IndexSet`（`xs[i] = v`）= 不做

三条理由：

1. **今天不支持，且 spec 明文承诺不支持**：spec §4.8:754「只读——列表与映射是不可变的，
   没有 `xs[i] = v`」。做它是推翻一条已发布的语言承诺，不是收编存量。
2. **它是新增表达力，不是把硬编码换成 trait**。刀 3 的全部收益来自「存量的两条 arm 换成
   一个可扩展的 trait」；`IndexSet` 没有存量可收。
3. **与刀 3 只共用一个方括号，不共用任何机器**：赋值位的 `[]` 要新的 parser 形状
（`EAssign` 的左值今天只认 `EIdent`）、新的 trait、新的 lowering 路径。共用的只有词法。

### D9 `want_iface` 收编成表（顺手做，本刀内）

`main.dawn:105-111` 的 `want_iface` 硬编码四个 trait id：

```dawn
if tid != EQ_ID && tid != HASH_ID && tid != SHOW_ID && tid != ITER_ID { return wants }
```

这是 prelude 集合的**第六份抄件**——#119 §4.3 把四份收成一张表时漏了它（它不在
`prelude_traits()`/`prelude_trait_ids()` 的读者名单里，因为它是个否定式条件）。
漏了它的后果不是编译错误而是**运行期 `NoClassDefFoundError`**：接口类不发，而字典类
`implements` 它。

**裁决**：改成读表——`prelude_trait_ids()` 减去 `ORD_ID`（Ord 的接口在 main.dawn:267
之前无条件发，注释已写明）。这样第七个 prelude trait 来的时候不必再想起这一处。

### D10 分刀 = 两刀，前置一件，**不需要三期两发布**

见 §6。要点：本刀**不引入任何新表面语法**（`impl Index[Grid] { type Idx = … }` 用的是
assoc-types 刀 1 就落地、v0.46.0 种子已认识的语法），**不改 std 源**（impl 由 prelude 铸），
**不改 selfhost/src 的源**（它继续写 `xs[i]`）。于是 N−1 编译 HEAD selfhost 的特性纪律
自动满足，`Emit-Change` 只欠 emit 与 lsp 两项。

## 3. 现状复核（基线 334ba4d）

### 3.1 `[]` 今天走的三段路

| 段 | 位置 | 做什么 |
|---|---|---|
| 检查：主体 | checker.dawn:4314-4325 `index_wanted` | 两条 arm 穷举 `TyList`/`TyMap`，返回 `(want_idx, result, on_map)` |
| 检查：witness | checker.dawn:4330-4343 `index_wits` | 只在 `on_map` 时解 EQ/HASH/SHOW 三个 |
| 检查：调用点 | checker.dawn:6272-6303 `EIndex` arm | 索引表达式按 `want_idx` 检查；不匹配时按 `on_map` 分两种措辞；出 `XIndex(tx, ix, on_map, ws, …)` |
| 降级 | lower.dawn:2399-2415 | `on_map` → `CCall(CDirect("std/hamt","index"), [tv, key] ++ ds, …)`；否则 `CIntrinsic("list_index", [tv, iv], erased)` |

`XIndex` 的节点形状在 tast.dawn:138-139（`on_map: Bool, wits: List[WitRef]`）。

**两个与 `[]` 无关的 `list_index` 生产者**：lower.dawn:411 与 423——**列表模式**
（`[..init, Num(v)]`）自己发 `list_index`。这是 `calc.core` 判据的根据，见 §6。

### 3.2 Map 的三个 witness，实测

```
$ cat mk2.dawn
pub fn look[K](m: Map[K, Int], k: K) -> Int = m[k]

error: indexing a Map requires `Eq[K]`, but `K` has no such bound
  |   pub fn look[K](m: Map[K, Int], k: K) -> Int = m[k]
  |                                                 ^^^^
  = hint: add the bound: [K: Eq]
error: indexing a Map requires `Hash[K]`, but `K` has no such bound
error: indexing a Map requires `Show[K]`, but `K` has no such bound
3 errors
```

三条、同一个 span（整个 `m[k]`）、顺序 Eq→Hash→Show。D6 的迁移必须保住这三件事，
`sub_goals` 的顺序与 `resolve_witness` 的递归各保一件。

### 3.3 opaque 今天的分道，实测

```dawn
opaque type Vec = List[Int]
pub fn mk() -> Vec = [1, 2, 3]
pub fn main() -> Unit !io = {
  let v = mk()
  println(to_string(v == mk()))   # true
  println("${v}")                 # [1, 2, 3]
  for x in v { println(to_string(x)) }   # 1 2 3
}
```

三样都通。换成 `v[0]`：

```
error: `[]` indexes a List or Map, got Vec
  = hint: when absence is a normal case, use get(xs, i) / map_get(m, k) instead
error: cannot infer type parameter(s) T for `to_string`
2 errors
```

用户自定义 ADT（`type Grid = Grid(cells: List[Int])`）同样两条错误。**D2 与刀 3 的整个
收益就是把这两段实测从「2 errors」变成「跑得出答案」**——这是最直接的验收形式。
（顺带：第二条错误是级联噪音，`XError` 之后 `to_string` 推不出 `T`。修好第一条它自然消失。）

### 3.4 `index` 这个名字今天被谁占着，实测

```
$ println(to_string(index([1,2,3], 1)))
  = hint: `index` is not a builtin; use std/pvec, then pvec.index(...)

$ fn index(x: Int) -> Int = x + 1
  ... 2      # 完全合法
```

`std/pvec.index` 与 `std/hamt.index` 存在但不隐式可见（两个模块不进 `std_fns`）。
订正勘察，见 D5。

### 3.5 两个 id 计数器 —— 前置比勘察说的大

勘察点名了 `checker.dawn:188` 的 `next_id: 4`，说 `INDEX_ID = 5` 会撞上第一个用户 trait。
复核确认，并**发现第二个计数器，它才是生产路径上真正生效的那个**：

| 位置 | 值 | 谁读它 |
|---|---|---|
| checker.dawn:188 | `next_id: 4` | 只有**不加载 std** 的 `Cx`——编译器的内联 test（`test_cx()`，checker.dawn:1085）与 `-e` 一类路径 |
| **stdlib.dawn:174** | **`var nid = 2`** | `load_std` 的整条链，并经 `StdCtx.next_id` 传给用户程序的 `Cx`（stdlib.dawn:184-186、232） |

实测（改一个字、重编、看 `examples/traits.dawn` 的 `Card` 拿到哪个 ADT id）：

| 改动 | `Card` 的 id | 结论 |
|---|---|---|
| 基线 | `Adt1121` | — |
| `checker.dawn:188` 4 → 6 | `Adt1121` | **无影响**；`selfhost-core-diff.sh` 只报 `checker` 一个模块变（变的是那个字面量本身），13 个 flat golden 逐字节不变 |
| `checker.dawn:188` 4 → 40 | `Adt1121` | 同上，确认不是巧合 |
| `stdlib.dawn:174` 2 → 3 | **`Adt1122`** | 每个 ADT id 平移 1，这才是生产计数器 |

两条推论：

1. **`INDEX_ID = 5` 的实际暴露面只有内联 test**。生产路径的 id 从 `nid = 2` 起，而
   **std 与 packages 一个 trait 都没声明**（实测：`grep '^pub trait\|^trait ' std/ packages/`
   零命中），所以第一个被铸出来的 trait id 来自用户代码、在 1100 以上。内联 test 里
   `trait X` 的 id 是 5（`fresh_tvar` 先取 4，`fresh` 再取 5——checker.dawn:2496-2497），
   **正好撞 `INDEX_ID`**，而且是 `map.insert` 的静默覆盖。所以前置仍然是前置，只是理由
   要说准。
2. **`nid = 2` 自己是同族的第二枚雷，且更深**：2 就是 `FOREIGN_ERROR_ID`
   （types.dawn:837）。今天没炸，靠的是 std/cursor 第一个铸的是类型变量而不是 ADT——
   与 `next_id: 4` 一样，安全建立在**铸造顺序**上而不是断言上。
   checker.dawn:1842-1851 那条 test（`assert cx.next_id > SHOW_ID`）在 `Iter` 落地时
   没跟改，今天 `next_id == ITER_ID == 4`，断言看不见。

**裁决**：`fix/next-id-past-prelude` 应当同时覆盖两处，断言改成遍历
`prelude_trait_ids()` 与 prelude ADT id 而不是手抄 `SHOW_ID`。若那条分支只修
checker.dawn:188，**刀 3 不接手 stdlib.dawn:174**——把 `nid` 抬高会平移每个 ADT id、
连带每个生成符号名（`structeq$Adt1121` 之类），那是一次波及全仓的 `Emit-Change`，
不该由刀 3 的账单吸收。单独立案，见 §7。

### 3.6 差分脚本管什么、不管什么 —— 订正勘察

勘察说「要声明 `Emit-Change(core*)`」。**没有这回事**：`Emit-Change` 只被四个脚本读
（`scripts/emitchange.sh` 的 `declared_for`，调用点在 `selfhost-prev-diff.sh:49`、
`selfhost-run-diff.sh:38`、`selfhost-fmt-diff.sh:37`、`selfhost-lsp-diff.sh:243`）。
**`selfhost-core-diff.sh` 不读它**——Core golden 变了就是让人读 diff 再
`--record` 重录，没有声明这条路。

四个标签的形状（glob 匹配脚本打印的 check label）：

| 脚本 | label 样例 |
|---|---|
| prev-diff | `emit selfhost`、`emit packages/json`、`emit examples/calc.dawn` |
| run-diff | `run calc (args)`、`run calc (usage)` |
| fmt-diff | `fmt` |
| lsp-diff | `lsp` |

## 4. 设计

### 4.1 `Index` 的表示

types.dawn，紧挨 `Iter`：

```dawn
pub const INDEX_ID: Int = 5

# 在 prelude_traits() 里：
let xv = TyVar("T", -18)
let xidx = TyAssoc(xv, INDEX_ID, "Idx")
let xitem = TyAssoc(xv, INDEX_ID, "Item")
let index = TraitI {
  id: INDEX_ID, name: "Index", tvar: xv,
  is_pub: true, owner: None, src_path: None,
  methods: [("index", MethodSig {
    sig: prelude_method(INDEX_ID, xv, "index", [xv, xidx], ["c", "i"], xitem),
    has_default: false
  })],
  assoc: ["Idx", "Item"],
  injects: false          # D5
}
```

`prelude_trait_ids()`（types.dawn:1065）加 `INDEX_ID`。表示与 `Iter`
（types.dawn:1025-1057）逐行同构，投影用 `TyAssoc` 直接建——「resolving `C.Idx` in a
declared trait would produce exactly this」，刀 2 的注释已经把这条写下了。

### 4.2 prelude 铸的两个 impl

`prelude_impls()`（types.dawn:1177-1199）追加两条。现有的 `prelude_cond_impl` 给每个
tparam 挂**同一个** tid 的 bound（为 `Show[Option[T]]` 写的），`Index` 两条都不是那个形状，
要一个新 helper：

```dawn
# impl[T] Index[List[T]] { type Idx = Int  type Item = T }
ImplI { trait_id: INDEX_ID, subject: TyList(lt), tparams: [lt],
        constraints: [[]], derived: true, provided: [],
        assoc_bindings: [("Idx", TyInt), ("Item", lt)], … }

# impl[K: Eq + Hash + Show, V] Index[Map[K, V]] { type Idx = K  type Item = V }
ImplI { trait_id: INDEX_ID, subject: TyMap(mk, mv), tparams: [mk, mv],
        constraints: [[EQ_ID, HASH_ID, SHOW_ID], []], derived: true, provided: [],
        assoc_bindings: [("Idx", mk), ("Item", mv)], … }
```

`provided: []` 是关键：`primitive_subject`（lower.dawn:1756-1764）据此判定
「no body anywhere」，于是 `lower_trait_call` 走 `prim_relation` 而不是找 impl 方法。
这与 prelude 的标量 `Eq`/`Ord` 是同一条判词，不是新特例。

`constraints` 按 tparam 下标对齐 `type_args_of(subject)`，所以 Map 的三条 bound 落在 `K`、
`V` 无 bound——`sub_goals` 的合同（types.dawn:737-756）。

### 4.3 checker：`EIndex` 怎么改

`index_wanted` / `index_wits` 双双删除，`EIndex` arm（checker.dawn:6272-6303）改成：

1. 检查主体，得 `tt`；`is_errorish` 早退（不变）。
2. **主体是 ground 且 `impl_at`（含 opaque 穿透）无 `Index` impl** → D7 的专属诊断，早退。
3. `resolve_witness(cx, INDEX_ID, tt, lo, hi, "indexing")` → `wr`。
4. `want_idx = reduce_assoc(cx, TyAssoc(tt, INDEX_ID, "Idx"))`，
   `result = reduce_assoc(cx, TyAssoc(tt, INDEX_ID, "Item"))`。
   主体是刚性类型参数时二者保持未归约（D3 的急切归约纪律允许 `TyAssoc` 以刚性主体存活），
   索引表达式按 `C.Idx` 检查——这正是 #119 D6「投影只参与检查」的形状。
5. 索引表达式按 `want_idx` 检查；不匹配的措辞不再按 `on_map` 分档，改成一条：
   `` this index must be `<want_idx>`, got `<it>` ``（今天两条：`this Map has keys of
   type …` / `a List index must be Int, got …`）。
6. 出 `XIndex(tx, ix, wr, lo, hi, result)`——`on_map: Bool` 与 `wits: List[WitRef]` 换成
   单个 `WitRef`（tast.dawn:138-139、291/328/366 的四处投影随之改）。

### 4.4 lowering：`prim_relation` 的第五条关系

```dawn
fn prim_relation(st: LSt, tid: Int, subject: Ty, args: List[CExpr]) -> (LSt, CExpr) = {
  if tid == EQ_ID { … }
  …
  if tid == INDEX_ID { return index_at(st, args[0], args[1], subject) }
  panic(…)
}
```

`index_at` 按 subject 分两条，**每条必须逐字节复刻今天 lower.dawn:2402-2414 发的东西**：

- `TyList(el)` → `adapt_out(CIntrinsic("list_index", [c, i], TyVar("E",0)), TyVar("E",0), el)`。
- `TyMap(k, v)` → `hamt_sig(st, "index")`（lower.dawn:2908）+
  `CCall(CDirect("std/hamt","index"), [c, adapt_in(i, …)] ++ ds, sg.ret)`，
  `ds` 是 Eq/Hash/Show 三个字典。

三个字典从哪来：`lower_trait_call` 在调 `prim_relation` 之前先跑
`enter_wit_env(st, ws[0])`（lower.dawn:1828-1846），它把 `WApply` 的子 witness 按
`dict_key(tid, ty)` 塞进 `st.dict_env`——**与 `eq_at`/`show_at`/`cmp_at`/`hash_at` 读子字典
的路完全相同**（lower.dawn:934、975、1039、1274、1460、1623）。`index_at` 照抄那个查表形状
即可，不需要新机器。这是 D1 路线在实现层最强的一条证据：机器全都已经在那儿了。

**一处必须同时修的既有缺陷**：`make_prim_slot`（lower.dawn:859-880）给字典槽拼形参时写

```dawn
for gt in sg.param_tys {
  ps ++ [CParam { sym, ty: gt, … }]
  args ++ [adapt_out(CLocal(sym, gt), gt, subject)]   # 每个形参都往 subject 适配
}
```

对 Eq/Ord/Hash/Show 是对的（所有形参都是主体类型），对 `Index` **不对**——第 1 个形参是
`C.Idx` 而不是 `C`。必须按该 impl 归约后的签名逐参适配（`subst_subject` /
`reduce_via_bindings`，assoc-types §6「现场发现 1」搬进 types.dawn 的那份）。
**这条只在字典轨上触发**（泛型 `[C: Index]` 的函数），devirtualise 的路碰不到它——
与刀 1 那个 ABI 洞是**同一个形状**，所以语料必须自带字典轨，见 §6。

### 4.5 加第六个 prelude trait 的手工同步清单

固化成一张表，下一个人照着走。左边打勾的是本刀要改的，右边是读表因而白送的。

| # | 位置 | 要做什么 | 漏了会怎样 |
|---|---|---|---|
| 1 | types.dawn:861 附近 | `pub const INDEX_ID: Int = 5` | — |
| 2 | types.dawn:988 `prelude_traits()` | 建 `TraitI`（`injects: false`） | — |
| 3 | types.dawn:1065 `prelude_trait_ids()` | 加 `INDEX_ID` | seed_prelude 不播种、redefinition guard 与 LSP 补全漏它 |
| 4 | types.dawn:1177 `prelude_impls()` | 两条 impl + 新 helper | `[]` 对 List/Map 全线报「no impl」 |
| 5 | types.dawn:1828 的 `assert len(prelude_impls()) == …` | 计数跟改 | 内联 test 红 |
| 6 | checker.dawn:188 `next_id` | ≥ 6（**前置分支**，§3.5） | 内联 test 里的用户 trait 静默覆盖 `Index` |
| 7 | checker.dawn:1842-1851 的 test | 断言遍历 `prelude_trait_ids()` | 下一个 prelude trait 又看不见 |
| 8 | checker.dawn:58 / lower.dawn:29 的 `use` 列表 | 引 `INDEX_ID` | 编译错误（会自己叫） |
| 9 | **main.dawn:105-111 `want_iface`** | 改读 `prelude_trait_ids()` 减 `ORD_ID`（D9） | **运行期 `NoClassDefFoundError`**，不是编译错误 |
| 10 | lower.dawn:842-849 `prim_relation` | `INDEX_ID` 臂 | `panic("lower: no primitive relation …")` |
| 11 | lower.dawn:859-880 `make_prim_slot` | 形参逐个按归约签名适配（§4.4） | 字典轨上 `NoSuchMethodError`（JVM） |
| — | lspc.dawn:261-266 | 白送（已读 `prelude_trait_ids()`） | 补全多出 `Index` 一项 → lsp-diff 红 |
| — | doc.dawn:434 | 白送（只当查表用） | 无输出变化 |
| — | checker.dawn 的 `is_prelude_trait_name` | 白送（从表派生） | 无 |
| — | emitc.dawn:967/972 | 白送（`list_index` 已有 C 实现） | 无 |
| — | interp.dawn:645-655 / 798 | 白送（`list_index` 已有 comptime 臂） | 无 |

第 9 行是勘察点名的那条，D9 把它收编进表，于是这张表从「六份抄件」缩到「三处必改 +
一堆白送」。

### 4.6 表达力兑现后能写什么

```dawn
type Grid = Grid(w: Int, cells: List[Int])

impl Index[Grid] {
  type Idx = (Int, Int)
  type Item = Int
  fn index(g: Grid, p: (Int, Int)) -> Int = {
    let (x, y) = p
    g.cells[y * g.w + x]
  }
}

# 泛型：主体在第 0 参，`C.Idx` / `C.Item` 只参与检查（#119 D6）
fn first[C: Index](c: C, i: C.Idx) -> C.Item = c[i]
```

`impl Index[Grid]` 的注册、孤儿规则、关联类型「恰绑一次」的校验全部由
`pass_register_impls`（checker.dawn:2768 起）现成处理，本刀一行都不加。
`Idx = (Int, Int)` 顺带说明元组做索引是白送的。

## 5. spec 落点

逐条给替换文本。

| 条款 | 今天 | 改成 |
|---|---|---|
| §3.5:418-422「预置 trait 五个」 | 「**预置 trait 五个**：`Ord`…、`Eq`…、`Hash`…、`Show`…、`Iter`（背后是 `for..in`，§4.7）。」 | 「**预置 trait 六个**：`Ord`…、`Eq`…、`Hash`…、`Show`…、`Iter`（背后是 `for..in`，§4.7）、**`Index`（背后是 `[]`，§4.8）**。」——其余句子不动 |
| §3.5:415-417「注入是逐 trait 的属性」 | 「……由运算符独占消费的 trait（**如 `[]` 背后的那个**）不注入，其方法名只在 impl 体、文档与错误消息里出现。」 | 把括号里的指代坐实：「（`Index`，§4.8）」 |
| §3.5 新增（紧跟 `Iter` 那条） | — | 「**`Index`** 声明两个关联类型与一个方法：`trait Index[C] { type Idx  type Item  fn index(c: C, i: C.Idx) -> C.Item }`。语言为 `List`（`Idx = Int`）与 `Map`（`Idx = K`）提供 impl；用户类型实现 `Index` 即可用 `[]`。方法名 `index` **不**进入函数命名空间（§3.5 注入条），只在 impl 体、文档与错误消息里出现。一个类型只有一个索引类型——`Index` 是单参数 trait，写不出同一容器的第二种下标。」 |
| §4.8:752 | 「- 下标只作用于 `List`（下标为 `Int`）与 `Map`（下标为键类型），其余类型是编译错误。」 | 「- 下标由预置 trait **`Index`** 求解（§3.5）：`List`（`Idx = Int`）与 `Map`（`Idx = 键类型`）的 impl 随语言提供，**用户类型写一个 `impl Index` 即可支持 `[]`**；没有 impl 的类型是编译错误。`opaque type` 沿用其目标类型的 impl（同 `==`/`${…}`/`for..in`）。」 |
| §4.8 新增（紧跟上条） | — | 一段 `impl Index[Grid]` 的示例，见 §4.6——**这是 `Index` 唯一的文档落点**，因为 `dawn doc` 不渲染 prelude trait（D5 的记账）。 |
| §4.8:753 | 「- comptime 中支持 `List` 下标（越界为编译错误）。」 | 不变（`list_index` 仍是 Core intrinsic，D1 理由 ①） |
| §4.8:754 | 「- 只读——列表与映射是不可变的，没有 `xs[i] = v`。」 | 「- **只读**——没有 `xs[i] = v`，`Index` 也没有对应的写方法。列表与映射不可变；用户类型即使可变也不经 `[]` 写入。」（D8） |
| §4.8:756-763 越界三判据 | 判据 1 列「`xs[i]`、`m[k]`、`bytes.at`、`str.at`、…」 | 不变。`[]` 的 panic 语义由 impl 承担，`std/pvec.index`（pvec.dawn:161-167）与 `std/hamt.index`（hamt.dawn:262-270）的文本不变——这是刀 1 要先钉住的东西 |
| §9:1167 | 「`get`/`map.get` 返回 `Option`（问询）；下标 `xs[i]`/`m[k]` 越界/缺键 panic（断言，§4.8）」 | 「`get`/`map.get` 返回 `Option`（问询）；下标 `c[i]` 越界/缺键 panic（断言，§4.8；语义由该类型的 `Index` impl 定，`List`/`Map` 如上）」 |
| §12 速查表:1933 | `xs[0]                            # 下标：越界 panic；问询用 get（§4.8）` | `xs[0]                            # 下标：走 Index trait；越界 panic，问询用 get（§4.8）` |
| §4.3 / §3.5:427 的 Ord 段 | — | **不动**。`docs/audit/re-audit-b-decisions.md:508-513` 把它立为「将来 `<` 统一路由到运算符 trait」那次改造的验收标准；刀 3 不是那次改造。为免误读，§4.8 新增一句：「比较运算符 `<`/`==` 不经 trait 路由到标量的 native 实现，见 §4.3——`Index` 只管 `[]`。」 |

`docs/trait.md` 提 prelude 交互的那段跟改一句；`docs/tutorial.md` 未涉及下标扩展，不动。
EBNF 不动（`[]` 的文法一个字都不变）。

## 6. 分期与验收

**前置（不属本刀）**：`fix/next-id-past-prelude`。理由与范围见 §3.5——它必须先落地，
`INDEX_ID = 5` 才不会被编译器自己的内联 test 静默覆盖。若那条分支只覆盖
`checker.dawn:188`，那就够了；`stdlib.dawn:174` 单独立案（§7）。

### 刀 1 — 先钉住今天的行为（零编译器改动）

勘察说「全仓没有任何语料钉 `[]` 的越界/缺键 panic 文本」。**半对，要说准**：
两条 panic 的**字符串常量**其实被 Core golden 钉着（`scripts/core-golden/std.pvec.core:519`
的 `str " out of bounds for length "`、`std.hamt.core:1517` 的 `str "key not found: "`）；
没被钉住的是**端到端的运行期行为**——`xs[i]` 越界真的走到那个 panic、两个后端一致、
退出码非零。刀 1 补的正是这一半。

- `scripts/spike-native/index_ok.dawn` + `.expect`：List 下标、嵌套 `rows[1][0]`、
  Map 命中、`Map` 键是 ADT 的情形（走三个 witness）。
- `scripts/spike-native/index_oob.dawn` + `.expect` + `.exits-nonzero`：先打印两行成功的，
  再 `xs[9]`。`.expect` 钉 stdout，harness 的 `stderr` / `exit` 两项钉两个后端一致
  （scripts/spike-native/run.sh 头注）。
- `scripts/spike-native/index_missing_key.dawn` + `.expect` + `.exits-nonzero`：同上，`m["nope"]`。

**验收**：三条语料全绿；`known-red.txt` 不新增条目（它是双向棘轮，加条目会被后续的修复
卡住）；其余差分脚本因为没碰编译器必须**全绿**——红了说明语料本身有问题。

### 刀 2 — `Index` 上线

内容 = §4.5 的清单（1–11 行）+ §4.3 的 checker 改写 + §4.4 的 lowering + §5 的 spec +
D2 那条 assoc-types D9 措辞勘误。

建议内部分两次提交，判据不同：

- **2a 存量零变化**：trait + 两条 prelude impl + checker + `prim_relation` + `want_iface`。
- **2b 新表达力**：`make_prim_slot` 的形参适配 + 三条新语料 + spec。

（`make_prim_slot` 的修复放 2b 是因为 2a 的路碰不到它；但**语料必须跟它同批**——刀 1 的
ABI 洞就是「语料只覆盖了 devirtualise 的形状」漏出来的，assoc-types §6「现场发现 1」。）

新增语料（2b）：

- `index_user.dawn` + `.expect`：`impl Index[Grid]`（`Idx = (Int, Int)`），元组索引。
- `index_dict.dawn` + `.expect`：`fn first[C: Index](c: C, i: C.Idx) -> C.Item = c[i]`，
  在 `List[Int]`、`Map[String,Int]`、`Grid` 三处实例化。**这条是唯一能抓住
  `make_prim_slot` 的**。
- `index_opaque.dawn` + `.expect`：`opaque type Vec = List[Int]`，`v[0]` 与
  `v == mk()` / `${v}` / `for..in` 并排，钉住 D2 的「四样一致」。

**验收判据表**：

| 判据 | 怎么验 | 预期 | 为什么足够 |
|---|---|---|---|
| **Core 逐字节** | `selfhost-core-diff.sh` | **13 个 flat golden（3 个程序 + 10 个 std 模块）与 71 行 `selfhost.sha` 全部不变** | 本刀的整个安全论证：`[]` 在 List/Map 上必须降成与今天**同一个** Core 节点。`std.map.core` 与 `std.set.core` 各 4 个 `list_index`、`std.list.core` 1 个、`std.hamt.core` 的 `hamt.index` 调用——一个都不许动 |
| **`calc.core` 尤其** | 同上 | 它的 2 个 `list_index` 不变 | 它们来自**列表模式** `[..init, Num(v)]`（calc.dawn:47 → lower.dawn:411/423），与 `[]` 无关。`calc.core` 变了 = 碰了不该碰的 |
| 运行输出 | `selfhost-run-diff.sh` | **全绿** | 语义不变。这条红了本刀就是错的，没有可声明的余地 |
| 格式化 | `selfhost-fmt-diff.sh` | 全绿 | 不动 fmt |
| N−1 编译 HEAD | `selfhost-prev-diff.sh` 第一段 | 绿 | HEAD selfhost 不使用任何新语法（D10） |
| 字节码 | `selfhost-prev-diff.sh` 的 `emit *` | **红，声明 `Emit-Change(emit *)`** | 每个 jar 多一个 `Index` 接口类：`main.dawn:286-295` 对**表里每个条件 impl** 调 `want_iface`，而 prelude 的 `Index[Map[K,V]]` 恒在表里（`Show[Option[T]]` 与 `Iter[List[T]]` 今天就是这样）。以实测为准，若 prev-diff 意外全绿则删掉声明 |
| LSP | `selfhost-lsp-diff.sh` | **红，声明 `Emit-Change(lsp)`** | lspc.dawn:261-266 遍历 `prelude_trait_ids()`，补全多出 `Index` 一项 |
| 诊断文本 | 内联 test + 新语料 | 三条变化，逐条列在 D6/D7 | 除这三条外任何诊断变化都是意外 |
| 表达力 | `index_user` / `index_dict` / `index_opaque` | 从「2 errors」变「跑得出答案」 | §3.3 的实测就是它的反面 |

> 验收纪律（引自 #110 与 #119 的同一条教训）：差分脚本在**未 `git add`** 的树上跑等于
> 没跑。两刀的差分一律在 add 之后跑。

**种子**：不需要三期两发布。无新表面语法、std 源不变、`selfhost/src` 源不变，
N−1 的特性纪律自动满足。发布一版即可，`Emit-Change` 两条随提交信息带上。

## 7. 开放问题（不阻塞，留档）

1. **`stdlib.dawn:174` 的 `var nid = 2`**（§3.5）。与 `INDEX_ID` 无因果，但同族且更深：
   2 就是 `FOREIGN_ERROR_ID`。修它要平移每个 ADT id → 每个生成符号名 → 全仓
   `Emit-Change(emit *)` + Core golden 重录。单独立案，判据是「一条断言，不是一个新的
   魔数」。
2. **`want_iface` 的第二个循环过于保守**（main.dawn:286-295）。它按「表里有条件 impl」
   而不是「本程序真会造这个字典」判断，于是 `Show`/`Iter`/`Index` 的接口类进每一个 jar。
   收紧它是可测的净减（每个 jar 少若干个类），但它自己就是一次 `Emit-Change(emit *)`，
   不该和刀 3 混在一起。
3. **切片 `xs[a..b]`**。D4 的单参数形状把它排除在 `Index` 之外。要么等多参数 trait，
   要么给切片自己的 trait/方法名。今天没有消费者。
4. **String / Bytes 的 `[]`**（D3 排除）。技术上 std/str 与 std/bytes **能**合法地写这个
   impl（`head_owner`，checker.dawn:2755-2760 已经为 `Iter` 认领了这两个 head），
   所以这是一次纯语义裁决：`s[i]` 的元素是码点还是字节、O(i) 扫描要不要伪装成下标。
   与 #90 Char 一起谈。
5. **`<` 统一路由到运算符 trait**。`docs/audit/re-audit-b-decisions.md:508-513` 已经把
   验收标准写好了（改造后 Float 必须仍能 `<`、仍不能 `[T: Ord]`）。刀 3 不是那次改造；
   若将来做，`Index` 是它的形状先例。
6. **`dawn doc` 不渲染 prelude trait**（D5 的记账）。`Index` 的用户文档只能落在 spec §4.8。
   归「标准库发现性」那件事，不是本刀的。
7. **`Index` 的 impl 可否带默认体 / 条件 bound**。今天 prelude 的两条是编译器铸的，用户的
   走普通 impl 路径，两边都够用。若将来 `impl[T: Index] Index[Wrapper[T]]` 有真需求，
   条件 impl 的机器已经在（`sub_goals` + `WApply`），只需语料。
