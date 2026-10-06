# 算术运算符 trait 设计 —— `+ - * / %` 与一元 `-` 背后的 `Add`…`Neg`

> 状态：**current** —— 运算符刀 1（2026-10-06）落地：六个 prelude trait、检查器在今天报错的那条分支上改道、
> opaque 不继承算术、诊断、core lint 的槽位证据规则、LSP 配对。权威条文在 [spec.md](spec.md) §2.7、§3.1、§3.5、§4.3。
> 刀 4（`std/narrow` 的 impl，2026-10-06）已落地；刀 2（LSP 运算符悬停显示 impl、goto 跳 impl）、刀 3（tileir 的 `Tile[D]`/`Idx` impl）未做，见 §8。
> 前置阅读：[operator-traits-design.md](operator-traits-design.md)（`Index`，本文同构的先例）、
> [assoc-types-design.md](assoc-types-design.md)、[effect-params-design.md](effect-params-design.md) 刀 5 与 §9（关联效果及默认值）、
> [builtin-privileges-design.md](builtin-privileges-design.md) §4（opaque 不继承 Show）。
> 字面量随期望定型（`t * 0.5`）是另一篇：[literal-system-design.md](literal-system-design.md)（L1，与本刀同一个 release）。

## 1. 为什么

1. **这是运算符体系里最后一块硬编码。** `==`→`Eq`、`<`→`Ord`（非标量）、`for`→`Iter`、`[]`→`Index`、`to_string`/`${}`→`Display`
   都已经是 prelude trait；`+ - * / %` 与一元 `-` 之前只认 `is_numeric`（`Int`/`Float`），封闭名单，用户类型永远进不去。
   这与 `Index` 当年的定性相同：**表达力项目**，不是纯洁性欠账。
2. **仓内已经有绕行物**：`std/narrow` 的 `trait Narrow[T]` 的 `add/sub/mul/div/neg` 是一张手写的算术表；
   `packages/tileir` 里 `addf`/`mul`/`sub`/`div` 合计三百来处，分布在上百个设备函数；`Idx` 的下标算术是 `idx_add`/`idx_mul`。
3. **机制已经齐了**：关联效果 + 默认行（spec §3.5，#369）让「运算符背后的方法带 `!Dev`」有确定意义；`lower_trait_call`
   同时处理去虚化、字典转发与证据。本设计**不引入新机制**，只引入六个 prelude trait 和检查器里一条分支。

非目标：异构运算（`Tile * Float`）、比较族与 `==` 的任何改动、`++`、按位运算、复合赋值（Dawn 没有 `+=`）、新运算符符号、
`Num`/`Zero`/`One`。字面量怎么进入运算见字面量设计。

## 2. 裁决

### D1 形状：六个单参数同质 trait，每运算符一个

```dawn
trait Add[T] { effect Add = !()  fn add(a: T, b: T) -> T !T.Add }   # +
trait Sub[T] { effect Sub = !()  fn sub(a: T, b: T) -> T !T.Sub }   # 二元 -
trait Mul[T] { effect Mul = !()  fn mul(a: T, b: T) -> T !T.Mul }   # *
trait Div[T] { effect Div = !()  fn div(a: T, b: T) -> T !T.Div }   # /
trait Rem[T] { effect Rem = !()  fn rem(a: T, b: T) -> T !T.Rem }   # %
trait Neg[T] { effect Neg = !()  fn neg(a: T) -> T !T.Neg }         # 一元 -
```

- **同质**：两个操作数与结果同一类型。spec §3.5「trait 恰有一个类型参数」与 §4.3「两侧同类型」都原样继承。
- **每运算符一个**，不捆成 `Num`：有 `+` 无 `/` 的类型（`Money`）不必写假实现；`[T: Add + Mul]` 组合即可。
- 否决关联 `Rhs`/`Out`：单参数下一个类型只能有一个 `Rhs`，`Tile*Tile` 与 `Tile*Float` 互斥，买到的表达力约等于零；
  `Out ≠ T` 让 `a + b + c` 的中间类型逐步取决于 impl。否决多参数 `HAdd[A, B]`：要推翻 §3.5 的单参数，孤儿规则、
  `resolve_witness`、字典键全要多一维，且 Lean 的经验是还得配一个 `binop%` 式专用推断器。否决 Haskell `Num`：整类捆绑。
- 代价：`Tile * Float`、`Idx * Int` 写不出（字面量那一半见字面量设计）。Mojo 对 SIMD 的规矩（同 dtype、不加宽）与 cutile-rs 的显式广播同此。
- id 7–12，接在 `Display`（6）之后。用户 trait 的 id 是声明路径的派生摘要（`identity.derive`，下限 2^32），与 prelude id 无关，
  所以加六个 prelude trait 不移动任何既有 id（刀 0 P3 实测：`first_minted_id` 7→13 唯一的读者是一条仍成立的断言）。prelude 的 tvar id 用 -23..-28。

### D2 哪些运算符

| 运算符 | 进 trait？ | 理由 |
|---|---|---|
| `+ - * / %`、一元 `-` | **进** | 本设计 |
| `< <= > >=` | 不动 | 仍桥 `Ord`、答 `Bool`。tile 的逐元素比较答 `Tile[I1]`，让 `<` 答 tile 会破 `if a < b`、`sort`、`[T: Ord]` |
| `==` `!=` | 不动 | 答 `Bool`，与 `Map` 键、`match` 字面量深度耦合 |
| `++` | 不动 | 封闭在 `String/Bytes/List`，有 `cat_list` 的单元素改写；没有消费者在等 |
| `& \| ^ << >> >>> ~` | 不动 | 仅 `Int`；按位 trait 另立设计 |
| `&& \|\| not` | 不动 | 短路与 `Bool` |

### D3 原生快路：Int/Float 不解见证、不建字典、字节不变

与 `<` 对标量的分工同一条（spec §4.3「两套机制」）：

- 具体 `Int`/`Float` 操作数：路径一个字不改——`XBinary(op, l, r, None, …)` → `CBinary` → JVM `LADD/DADD/…`、C 的 `+`。
- prelude 给 `Int`/`Float` 铸 12 个无条件 impl，体在 `prim_relation` 的六条臂里降成同一个 `CBinary`/`CUnary`。它们**只**在
  `[T: Add]` 被实例化到 `Int`/`Float` 时以字典槽位出现（`make_prim_slot`）；无条件，所以不触发接口类。
- 判据：检查器只在**今天必然报错**的那条分支上改道（D6），所以今天能编译的程序走逐结点相同的 TAST。
- 刀 0 的负控 M2（强制 `Int`/`Float` 也走 trait）证明了一件不显然的事：**快路不是字节属性**。prelude 见证在 `lower_trait_call`
  折回 `prim_relation` 的同一个 `CBinary`，M2 下 core-diff 只有被改的那个函数变、emit 逐字节相同。它是检查器属性：决定诊断措辞、
  LSP 配对、检查期开销。所以守它的门是 checker-corpus 与一条断言 TAST 形状的内联测试，见 §6。

### D4 opaque 不继承目标的算术（与 `Show` 同一条例外）

`resolve_witness` 对 opaque「先查自己的 impl，无则落到目标」，此前唯一例外是 `Show`。**算术六个 trait 加入这条例外**。

1. **继承会静默算错。** `Tile[D] = Float`、`Idx = Int`、`Cursor = Int` 的表示是句柄号或偏移，`Char = Int` 是码点，`BF16 = Float`
   的不变量是「值可在该格式表示」。继承之后 `tile + tile` 把句柄号相加，`bf16 + bf16` 跳过重新舍入。`Eq`/`Ord` 继承安全，
   是因为关系只答真假或符号、不产出新的该类型值；算术产出新值，新值**必须**满足 opaque 的不变量，只有声明模块知道怎么满足。
2. **与此前的语义一致**：spec §2.7「本模块里 `u + 1` 仍是错的」；此前 opaque 上任何算术都报错，本条把这个事实从「`is_numeric` 恰好不认」升格成规则。
3. GHC 同一条切分：GND 复用表示字典，但 `Num` 要显式 `deriving newtype (Num)`。Dawn 的对应物是在声明模块写 impl。

opaque-twin 判据（spec §2.7「只有六件事可以看见 `TyOpaque`」）的「`Show` 见证解析」改为「`Show` 与算术见证解析」。

### D5 效果：每个 trait 一个同名关联效果，默认 `!()`

- `effect Add = !()` 是 #369 的默认行；纯 impl 一个字不写；带效果的 impl 写 `effect Add = !Dev`。具体调用点，`T.Add` 随主体急切归约成
  impl 的绑定（`reduce_eff`），记进外层行（`record_effect`，span 取运算符），交证据（`named_evidence_args`）——与普通调用同一条路。
  泛型代码里 `T.Add` 是刚性投影，证据由外层签名的同名一格转发。
- **成员与 trait 同名**（`!T.Add`，不是 `!T.E`）：`E` 被否，因为 `[T: Add + Mul]` 下两个 bound 都声明 `E`，`T.E` 按 §3.5 报歧义
  （刀 0 实测「`!T.E` is ambiguous」）。注册、投影解析、ABI 都不看成员名是否等于 trait 名（刀 0 P1 实测，用户 trait 与 prelude trait 都成立），
  `AddFx` 退路不需要。`!T.Add` 投影原子与 trait 名所在的类型命名空间不相交。
- 泛型代码的代价，写死：`fn dot[T: Add + Mul](xs: List[T], ys: List[T], z: T) -> T !(T.Add | T.Mul)`。不写行，`a * b` 报现成的
  「the effect `T.Mul` needs evidence here」。以 `Int` 调用时投影归约成 `!()`，调用方仍是纯的。
- **条件 impl 的限制，写死**：impl 的效果绑定只能是 ground 行（`!()`、`!io` 或一个声明的效果），所以「把算术转发给类型参数」的条件 impl
  （`impl[T: Add] Add[Pair[T]]` 体内写 `p.a + q.a`）写不出：方法行不能超出 trait 行，绑定又不能是 `!T.Add`。刀 0 试了三种写法都不行，
  checker-corpus 的 `arith_ops_opaque` 钉住了这条。不转发算术的条件 impl（`impl[D] Add[Tile[D]]`，绑定 `!Dev`）不受影响。
  若六个 trait **不带**效果成员，条件 impl 可写，但 tileir 的 `!Dev` 就没处放；两害取轻。重开条件见 §9 第 9 条。
- 纯洁性：Dawn 的承诺是「看签名即知副作用」（design.md:16），签名级，不是表达式级。运算符带效果之后**每一个效果仍出现在某个签名里**：
  具体类型时在外层函数的行里，泛型时在 `!T.Add` 里，编译器拒绝没出现在签名里的效果。`==`（用户 `Eq`）、`[]`（用户 `Index`）、
  `for`（用户 `Iter`）早就在运算符位调用户代码；新的只是算术 trait 是**第一批**带效果成员的 prelude trait（其余 prelude 方法行写死纯）。
  `!io` 不特判。

### D6 检查器：只在今天报错的分支改道，左锚定，产出 `XCallFn`

`EBinary` 臂移进 `check_binary_expr`（顺带让 `check_expr_at` 离 HotSpot 的 HugeMethodLimit 更远，#241），一元同理 `check_unary_expr`。
左操作数照旧无期望地检查，然后：

```
if op ∈ {+ - * / %} && arith_routed(lt):  check_arith_trait(...)          # 新
else:                                      原路径（check_expr(right) + check_binary_typed）
```

`arith_routed(lt)` = 不是 `is_numeric`、不是 `is_errorish`，且是**有 head 的类型**（ADT、opaque、`List`、`String`、`Bool`…）或
**刚性类型参数**。还在推断的类型变量与元组（无 head，写不出 impl）留在原路径，保持原报错。

`check_arith_trait` / `arith_call`：

1. 右操作数以 `Some(lt)` 为期望类型检查（单向：左永远无期望，右永远以左为期望）。这一步让 `t * lit(0.5)` 的 `lit[D]` 从期望定下 `D`。
2. 右操作数出错 → 静默（与原路径相同）。
3. **左有 head 且 impl 表查无** → 专属消息，落在运算符上，**先于**两侧类型比较：`true + 1` 说的是 `Bool` 没有 `+`，不是「Bool vs Int」。
   prelude trait 没有声明模块，`resolve_witness` 那句「在声明 `Add` 的模块里写 impl」对它们永远不适用，所以 ground 无 impl 全部走专属消息。
4. 右类型 ≠ 左类型 →「both sides must have the same type: X vs Y」+ hint「there are no implicit conversions」，落在运算符上。
5. `resolve_witness(cx, tid, lt, …, "`+`")`：刚性参数、条件 impl、opaque 例外都在这里。
6. 方法签名以 `T := lt` 实例化，`reduce_eff` 归约 `!T.Add`，`named_evidence_args` 交证据，`record_effect` 记效果。
7. 产出 `XCallFn(None, "add", [lx, rx], [w], evs, Some(ADD_ID), lo, hi, olo, lt)`；一元 `-` 产出 `[ox]`，span 与 `nlo` 取 `-` 本身。

否决直接调 `check_call`（等价于 UFCS `a.add(b)`）：诊断会说「argument type mismatch」「`add`」，而 `add` 不注入、用户从没写过。
否决给 `XBinary` 加证据字段：要改它的全部消费者（interp、lspeval、jfold…），而 `XCallFn`+`trait_id` 已被 `lower_trait_call`、LSP、
comptime 解释器全程支持（刀 0 实测 `const C: V2 = V2 {..} + V2 {..}` 照常折叠）。

为什么不会有 Swift 的推断爆炸：Swift 的三个放大器是「每个运算符一大组按名重载」×「字面量多态」×「双向约束求解」。这里每个运算符恰一个 trait、
左类型在检查运算符前已定、右只做一次期望类型检查；每个运算符结点 O(1) 次 impl 表查找，不随表达式长度组合增长。

**LSP 配对随刀 1 一起改**：`lspq.dawn` 的 `walk_e` 与 `collect_e` 原本把 `EBinary` 只与 `XBinary`、`EUnary` 只与 `XUnary` 配对；
TAST 变成 `XCallFn` 时操作数以 `None` 遍历，操作数里的名字在悬停、语义 token、references、rename 里全部失配。
这是 references/rename 的正确性，不是体验项。两个遍历器各加 `XCallFn(.., [l, r], .., Some(_), ..)` 与 `[o]` 两臂，
`lsp/server` 的内联测试「an operator over a type of its own keeps its operands' references and hover」钉住。

### D7 字面量

本刀单独看时字面量仍是单态的：`2.0` 是 `Float`，`t * 2.0` 报两侧类型不同。字面量随期望定型、向有类型的一侧让步是
[literal-system-design.md](literal-system-design.md) 的 L1，与本刀同一个 release 落地，取代这一条。**左锚定的不对称对非字面量收窄**（C0 刀，2026-10-06 裁决，推翻原判）：原判是「`lit(2.0) * t` 推不出 `D`，不做左推不出时以右回填」，
理由是右回填就是双向求解的第一步。这一条仍然成立，**不做右回填**；改变的是另一个方向：二元算术运算符节点**自己的期望类型**，
当它是走 trait 的库类型（`arith_routed` 为真，即不是 `Int`/`Float`、不是错误类型、有类型头或是刚性类型参数）时，**下传给左操作数**。
于是 `fn f(t: Tile[F64]) -> Tile[F64] = lit(2.0) * t` 的 `D` 由返回类型定下，`let s: Tile[A] = mma(q, k, 0.0) * lit(scale)` 的累加器格式 `C` 由 let 注解定下。
期望只是期望，不是约束：左操作数类型与期望不符时，二元节点上原有的类型不符诊断照旧。

理由：左右不对称在字面量裁决之后成了缺陷而不是设计。右操作数早就以左类型为期望，字面量裁决又规定库类型的期望照常流动；
唯独「运算符节点自己的期望」被左操作数丢掉，使得 `mma(..) * lit(s)` 这种最自然的泛型 kernel 写法必须拆成两个 let。
先例是 Zig 的 result type（期望自外向内、单向、无搜索），与 Dawn 的局部检查器同构；Rust 靠推断变量延后解，Swift 靠约束求解，这两条 Dawn 都不走（literal-system-design D2）。
调研与裁决见维护者工作区的 research-generic-kernel-report-20261006.md 与 ruling-generic-kernel-20261006.md 第 2 条。

边界：
- `Int`/`Float` 期望不下传，所以 `let f: Float = 1 / 2` 仍报错（`Float` 期望不穿过运算符，literal-system-design D5.2）；`Int`/`Float` 混合规则不变；
- 比较与 `==` 不下传（结果是 `Bool`，期望与操作数类型无关）；
- 左操作数推不出类型参数、且期望也不是走 trait 的库类型时，原来的 `make() + p` 专属 hint 照旧。

### D8 降级：非原生的运算符在 TAST 就是调用，后端永远只见原生 `CBinary`

- 原生路径 `XBinary` → `CBinary`，不变。trait 路径 `XCallFn(trait_id: Some(..))` → `lower_trait_call`：具体 impl 去虚化成直接调用、
  `WForward` 走 `CMethod` 字典分派、prelude `Int`/`Float` 见证 → `prim_relation` → `CBinary`。
- 不变量：后端见到的 `CBinary(CAdd, …)` 的操作数类型只有 `Int`/`Float`。`emit.dawn`/`codegen.dawn`/`emitc.dawn` 零改动。
- **一处必要补丁**：`make_prim_slot` 原本按 `sg.param_tys` 造槽位形参，不含关联效果证据；算术 trait 是第一批带效果成员的 prelude trait，
  槽位要按 `sig_abi_eff(sg)` 的投影个数补擦除证据形参（同 `make_bridge`）。漏了它，JVM 报 `NoSuchMethodError`，**native 静默通过**
  （C 按调用方签名强转槽位函数指针，多传一个参数在 x86-64 SysV 下恰好无害，是 UB）。所以同时给 core lint 加 **`slot-evidence`** 规则：
  字典每个槽位函数的 `evs` 个数 = 该 trait 方法 `sig_abi_eff` 的标签 + 变量 + 投影个数。它需要 trait 表，所以是 `lint.check_slots(traits, mods)`，
  两个驱动在 `lint_program` 旁边一起调。变异体 `lint-arith-slot`（`scripts/core-lint-contract`）复原这个缺陷，`spike-native/arith_traits.dawn`
  在两后端开 lint 时都报 `[slot-evidence]`。

### D9 一致性、孤儿规则与命名

- 孤儿规则照旧：impl 只能写在主体类型的声明模块（trait 属 prelude）。用户写不出 `impl Add[String]`、`impl Add[List[T]]`；std 自己也不写：`++` 才是拼接。
- `injects: false`：六个方法名不进任何模块的函数命名空间，于是与 tileir 的 `sub/mul/div/neg`、`std/narrow` 的 `Narrow` 方法、
  `packages/tea-dom` 的 `div` 都不冲突。impl 体内写 `fn add(...)` 是 impl 方法，不是顶层函数。
- 名字 `add/sub/mul/div/rem/neg` 与 Rust 同名（`rem` 而非 `mod`：`%` 的符号随被除数，是余数不是模）。
- **trait 名本身占用类型命名空间（破坏性，记入 history）**：从此用户不能声明名为 `Add/Sub/Mul/Div/Rem/Neg` 的 `trait`
  （「`Sub` is a prelude trait and cannot be redefined」）或 `effect`（「effect `Add` collides with a type of the same name」）；
  同名 `type` 仍可声明，且同模块里 `impl Sub[V]` 仍解析到 prelude trait（刀 0 实测，`packages/tea-core` 的 `type Sub[M]` 不受影响）。
  勘察本仓与 dawnop-site：没有一处同名 `trait` 或 `effect`。

### D10 泛型数值代码：允许 `[T: Add]`，不给 `Zero`/`One`

`fn sum[T: Add](xs: List[T], zero: T) -> T !T.Add = fold(xs, zero, (a, x) => a + x)` 合法（`fold` 的行多态吃下 `!T.Add`）。
不提供 `Zero`：tile 的零要形状与格式，`Money` 的零是业务值，没有对所有主体都正确的 `zero()`。字面量设计落地后，`[T: FromInt]` 下的 `0` 就是
`from_int(0)`，是另一条路。std 不新增 `sum`/`product`。

### D11 诊断

| 情形 | 此前 | 现在 |
|---|---|---|
| `"a" + "b"` | `arithmetic expects numbers, left side is String` | `` `+` needs an `Add` impl for `String` `` + hint `` `++` concatenates strings `` |
| `xs + ys`（`List`） | 同上 | `` `+` needs an `Add` impl for `List[Int]` `` + hint `` `++` concatenates lists `` |
| `true + false`、`true + 1` | `arithmetic expects numbers, left side is Bool` | `` `+` needs an `Add` impl for `Bool` `` + hint「Int and Float have one; a type of your own gets `+` from `impl Add[T]` in its module」（先于两侧类型比较） |
| `c1 * c2`（`Char`） | 同上 | `` `*` needs a `Mul` impl for `Char` `` + hint「an opaque type does not inherit its target's arithmetic; convert with char.code first」 |
| opaque `u + u`，无 impl | 同上 | `` `+` needs an `Add` impl for `Money` `` + hint「… write `impl Add[Money]` in the module declaring it, or convert to the target there first」；泛型 opaque 写成 `impl[D] Sub[Tile[D]]` 的形状 |
| 用户 ADT 无 impl | 同上 | `` `/` needs a `Div` impl for `V` `` + hint「a type gets `/` from `impl Div[V]`, written in the module declaring it」；泛型 ADT 写成 `impl[T] Rem[Pair[T]]` |
| `fn f[T](a: T, b: T) = a + b` | `arithmetic expects numbers, left side is T` | `` `+` requires `Add[T]`, but `T` has no such bound `` + `add the bound: [T: Add]` |
| `[T: Add]` 但行里没 `!T.Add` | 不可达 | 现成的「the effect `T.Add` needs evidence here」，落在运算符上 |
| `[T: Add]` 实例化到没有 impl 的类型 | — | `no impl of `Add` for `V`` + 上面同一族 hint（不再指向「声明 `Add` 的模块」） |
| `w + 1`（`W` 有 `Add`） | `arithmetic expects numbers, left side is W` | `both sides must have the same type: W vs Int` + `there are no implicit conversions` |
| `make() + p`（左推不出类型参数，节点无库类型期望） | 现成的 cannot infer | 同句 + D7 的专属 hint |
| `1 + w`、`1 + 2.0` | `both sides must have the same type` | **不变**（左是数，原路径） |
| `(1, 2) + (3, 4)`、`-(1, 2)` | 原文 | **不变**（元组无 head） |
| `-"a"` | `negation expects a number, got String`（span 是操作数） | `` `-` needs a `Neg` impl for `String` ``，span 改为 `-` 本身 |
| 带 `!Log` 的 impl 在未声明处 `t + t` | — | 现成的「`f` uses the effect `Log`, but its signature does not declare !Log」，落在运算符上 |

所有变动都是**原本就报错**的程序的文字变化。checker-corpus 新增 `arith_ops`、`arith_ops_opaque` 两例逐条钉住；`binary_ops`、`unary_ops` 两例的 golden 随之重录。

### D12 种子纪律

- 本刀只动编译器，不新增表面语法（`effect X = !()` 是 #369 已发布的语法），`selfhost/src` 自己不用新特性，N−1 纪律自动满足。
- `std/narrow` 的 impl 必须等种子推进到本刀的 release 之后：std 在自举 closure 里，stage A 用种子编，种子不认识 `Add`。
- `packages/tileir` 不在 closure 里，release 一出即可写 impl（刀 3）。

## 3. 改动位置

| 文件 | 改动 |
|---|---|
| `check/types.dawn` | `ADD_ID..NEG_ID`（7–12）、`arith_trait_ids`/`is_arith_trait`/`arith_trait_name`；六个 `TraitI`（`injects: false`、`eff_assoc`/`eff_defaults`、方法行 `EffAssoc` 投影）；`prelude_trait_ids` 加六个；`prelude_impls` 给 `Int`/`Float` 铸 12 个；内联测试「prelude shapes」 |
| `check/checker.dawn` | `check_binary_expr`/`check_unary_expr`/`arith_routed`/`check_arith_trait`/`arith_call`/D11 的 hint 族；`resolve_witness` 里 opaque 的算术例外与无 impl 的算术措辞；内联测试（TAST 形状） |
| `ir/lower.dawn` | `prim_relation` 六条臂、`prim_ret_ty`；`make_prim_slot` 的证据形参 |
| `ir/lint.dawn`、`main.dawn`、`c/cdriver.dawn` | `slot-evidence` 规则 |
| `lsp/lspq.dawn` | `walk_e`/`collect_e` 的配对臂 |
| `doc.dawn` | 六段 prelude 散文（`doc --stdlib` 的 `traits` 多六项） |
| `scripts/checker-corpus`、`scripts/spike-native/arith_traits.*`、`scripts/core-lint-contract` | 语料、两后端对拍、变异体 |

## 4. 证据（实测，2026-10-06）

见本刀提交信息与 `agent-handoff/arith-lit-stack-report-20261006.md`。要点：

- 字节不变：`selfhost-core-diff.sh` 对 main，171 份 dump 里只有改动的编译器模块变，std 与 calc/traits/eqhash 零变化；
  emit 宽语料（examples、projects、spike-native、packages，`__emit` + `__emitc`）以 main 自建 jar 为 N−1 逐个相同。
  （当前窗口 prev-diff 的 `emit *` label 已被 v0.84.0 之后的提交声明，真 prev-diff 的绿在这里不是证据，刀 0 §4。）
- 负控 M2（`arith_routed` 对数值返回真）：checker-corpus 红（`binary_ops` 的 `1 + 1.5` hint 变化等），checker 内联测试红；字节门看不见它，见 D3。
- 负控 M3（`make_prim_slot` 不补证据形参）：`DAWN_CORE_LINT=1` 下两后端报 `[slot-evidence]`。
- 预期的 Emit-Change：`lsp`（补全回复多六个 prelude trait 名）。`doc --builtins` 不变。

## 5. 刀序

| 刀 | 内容 | 状态 |
|---|---|---|
| 0 | 探针 P1–P4、负控 M2/M3 | 完成（`chore/arith-ops-probes`，只入报告） |
| 1 | 本文 | 完成 |
| 1′ | 发 release N（与字面量 L1 同一个 release），`advance-seed.sh` | 待做 |
| 2 | LSP：运算符悬停显示 impl 签名、goto 跳 impl 方法、`lspeval` 折用户 impl 的闭合算术 | 待做 |
| 3 | tileir：`impl[D] Add/Sub/Mul/Div/Rem/Neg[Tile[D]]`（`effect X = !Dev`）、`Idx` 的 impl；判词 tile-golden 逐字节零变化 | 待种子 |
| 4 | `std/narrow`：`BF16/FP16/F32` 的 impl（含 `Rem`：截断余数在任何二进制格式里都精确，不需重新舍入），改写其头注与 `tile-backend-design.md` 的「人体工学降一档」；`narrow-contract` 让运算符与具名成员跑同一批 oracle 用例 | 完成 |
| 5 | 教程 §16（英文先、中文后）、站点 GPU 页示例 | 待 3、4 |

## 6. 测试

- `spike-native/arith_traits.dawn`：`V2` 记录的 `a + b - -a * b`；`sum`（`for` 转发字典）、`sum_fold`（lambda 捕获字典与证据）、
  `dot[T: Add + Mul]`、`negsub[T: Sub + Neg]`、`rem_div[T: Rem + Div]` 各以 `Int`、`Float`、`V2` 实例化；`Traced` 的 impl 绑定 `!Log`，
  泛型与直接两条路。两后端对 `.expect` 一致。
- checker 内联测试：`Int`/`Float` 上的运算符是 `XBinary`（`ord = None`）与 `XUnary`，`V` 上的是 `XCallFn(.., Some(ADD_ID))`
  套 `XCallFn(.., Some(NEG_ID))`。这是 M2 的永远红的门。
- `types` 的「prelude shapes」：六个 trait 不注入、各带一个同名默认纯的效果成员、各一个方法，`prelude_impls` 多 12 个。
- checker-corpus：D11 每一行，外加孤儿 `impl Add[String]`、`derive Add`、impl 方法签名不同质、条件 impl 转发算术（D5 的限制）、未声明效果。
- `lsp/server`：运算符两侧的名字在 references 与悬停里不丢。

## 7. 编译期成本

数值代码每个运算符多一次 `arith_routed` 判断（`is_numeric` 本来就在算）。刀 0 实测 `check selfhost` 三次交替：基线 6.41/5.00/6.11 s，
探针 6.25/6.94/5.84 s，在噪声内。

## 8. 后续

见 §5 的刀 2–5。刀 2 的 LSP 运算符悬停与 goto、`lspeval` 对用户 impl 的闭合算术折叠（hover B 组）不阻塞发版。

## 9. 不做的（理由）

1. **异构运算 `Tile * Float` / `HMul[A, B]`**：要多参数 trait，且 Lean 的经验表明还得配专用 elaborator。重开条件：语言为别的理由引入多参数 trait。
2. **Haskell/Lean 式字面量推断变量 + defaulting**：Swift 推断爆炸的放大器之一。Go 式无类型字面量见字面量设计，不在本文。
3. **右锚回填**（左推不出时以右类型重查左）：双向求解的第一步，诊断会重复一遍。字面量原子的让步不是回填，见字面量设计。
4. **`<` 答 tile、`==` 可重定义返回类型**：`Bool` 是 `if`/`sort`/`Map` 的前提。
5. **`++` 进 trait**：无消费者在等，`cat_list` 改写要保。将来 `Append` 同形另立项。
6. **按位运算进 trait**：仅 `Int`，另立设计。
7. **`Num`/`Zero`/`One`**：D10。
8. **opaque 继承 / `deriving newtype` 式自动继承算术**：D4，句柄与舍入不变量会被静默打破。
9. **条件 impl 把算术转发给类型参数**（`impl[T: Add] Add[Pair[T]]` 用 `p.a + q.a`）：要让 impl 的效果绑定接受 impl 参数的投影
   （`effect Add = !T.Add`）并在实例化时二次归约，是 #369 的扩展。重开条件：出现第一个真实的泛型数值容器需求（复数、向量），且它的元素算术不能写成具体类型。
10. **复合赋值 `+=`**：Dawn 没有，不为本设计引入。
11. **为运算符禁止 `!io`**：特例；签名已说清。
12. **`[]`/`for` 顺手开关联效果**：对称性诱人，但没有消费者，另立项。
13. **新运算符符号、用户定义优先级**：design.md 的非目标仍成立。
14. **删除 `Narrow` 的 `add/sub/...` 与 tileir 的具名算术**：具名形式承载非默认属性（`rounding:`、`ftz:`、`overflow:`），运算符只给默认语义；删除是破坏性，按需另裁。
