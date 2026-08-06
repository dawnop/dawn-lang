# 关联类型设计 — trait 的 `type Item` 与投影 `T.Item`

> 状态：current（刀 1 落地 2026-08-02；刀 2 也已落地 2026-08-02：prelude Iter +
> 五个 std impl + for..in 去特判，决策与偏差记录见 §6）
>
> 任务 #44。勘察备忘录（2026-08-02，基线 6dfc34b）先行，本文所有 file:line 均对该基线；
> 用户裁决三项合同级决策于 2026-08-02（§2）。运算符 trait 的前置。

## 1. 目标与非目标

**目标**：trait 可以声明一个由 impl 指定的类型成员，方法签名可以引用它。
最小闭环 = `trait Iter[C] { type Cur  type Item  fn iter_start(...) ... }` +
`impl[T] Iter[List[T]] { type Cur = Int  type Item = T ... }`
+ 首个消费者（prelude 的 `Iter` trait 与 `for..in` 去特判）。
（§3 的示意曾用短名 `fn next`——那与「存量逐字节不变」自相矛盾：短名会撞掉
std 现有顶层函数。落地形状是 `iter_start/iter_done/iter_next/iter_get` 四方法
双关联类型，镜像 std/list 的游标四件套，见 §6 刀 2 记录。）

**非目标**：
- 关联类型上的 bound（`type Item: Ord`）——bound 表示是现在不存在的机器（勘察缺件 8），
  等真实需求。
- 关联类型默认值（`type Item = 默认`）——无消费者。
- 任意类型上的投影（`List[Int].Item`）——首批投影主体限定为**带该 trait bound 的类型
  参数**；任意主体需要 resolve_type 能查 impl，而它跑在全部 impl 注册之前
  （checker.dawn:9535-9541 的 pass 顺序墙），留作后续。
- 多个关联类型成员一批做完的义务——表示按 List 建，语法天然多成员，但首批语料与
  消费者只用单成员。

## 2. 裁决记录

**用户定案（2026-08-02）**：
- **D1 成员语法 = 裸 `type Item`**。不带 bound、不带默认，与 trait v1「先单文件后跨模块」
  的渐进路线同款。
- **D2 投影拼写 = `T.Item`**。类型位的 `小写.T` 是模块限定（LANG-06，parser.dawn:871-880），
  大写主体后跟 `.` 今天是语法错误——零撞车。首批主体限定 bound 类型参数（见 §1 非目标）。
- **D11 首发带消费者 = Iter + `for..in` 去特判**。checker 现在硬编码 for 只迭代 TyList
  （checker.dawn:6846-6853），lower 靠名字找四个非 pub 的 std/list 函数
  （lower.dawn:2806-2837）；std-audit.md:105-133 早已把退休这个特判记在 #44 名下。
  消费者与特性同一张设计图、分批实施（§6），表达力问题在设计期暴露而非发布后。

**执行侧裁决（本文档定，理由随条）**：
- **D3 归约纪律 = 急切（eager）**。投影在 resolve/subst 时只要主体落到有 impl 的具体头
  就立刻归约；具体类型里**不允许存活未归约投影**。代价最小化：`TyAssoc` 的十处穷尽墙
  （勘察缺件 3）里大多数臂写 `panic("unreduced projection")` 即为正确实现——它们只见
  ground 类型（ty_key_inst/desc_of/c_repr 等全在归约之后）。懒惰归约则要教
  unify/`==`/`Map[Ty,…]` 全部按规范形比较（缺件 9 的全面爆破）。
- **D4 impl 绑定 = 显式 `type Item = X`，不做推断**。X 可用 impl 的类型参数；存进
  `ImplI` 新字段；在 `subst_subject`（lower.dawn:1892）与 impl 方法校验
  （checker.dawn:2577-2604）两处代入。从方法体推断绑定是省一行拼写换一套推断机器，不做。
- **D5 归约的 impl 来源 = 与 witness 同一个 `impl_at`**。绝不另立 assoc 表——两张表就是
  「表的写入者错了而读者没错」的历史故障形状（checker.dawn:1188-1193 注释、
  semantics-closure-design.md）。归约用哪个 impl 与字典选哪个 impl 必须是同一个答案，
  同一扇门。
- **D6 投影的许可位置 = 方法签名内（含返回位与参数位）**。不进 impl 约束、不进 impl
  主体、不进关联类型绑定的 RHS——每向外一步都削弱 types.dawn:695-698 的项大小终止
  论证；方法签名位是 Iter 消费者需要的全部。放宽是显式的后续裁决，不是默认。
- **D7 未归约投影的 unify 行为 = 报错**。刚性主体的 `T.Item` 对具体类型：
  「cannot determine `T.Item` — the impl for `T` is not known here」。不做延迟目标队列
  （不存在的机器）；投影只与语法相等的投影合一。这与 D2 的主体限定配套：主体带 bound
  时字典在场，方法体内部的投影总能经字典的 impl 归约或保持刚性一致。
- **D8 命名空间 = 关联类型名只活在 trait 作用域内，无顶层名**。`Item` 不进模块类型
  命名空间（不撞 ADT/alias，checker.dawn:2183-2187 的共享命名空间不扩容）；只有
  `T.Item` 这一种到达方式。导出随 `trait_infos` 走（ModExports 合并，
  checker.dawn:4720-4735）——投影在导出签名里随 Sig 序列化，不需要新导出件。
- **D9 opaque 主体 = 镜像 resolve_witness 的顺序**（checker.dawn:5272-5278）：先查
  opaque 自己的 impl，无则~~**不**穿透到 target~~**穿透到 target**——opaque 的判据是
  「它就是它的目标」用于表示、「先身份」用于语义查找。

  > **勘误（2026-08-02，运算符 trait 刀 2 收口）**：这条的措辞与落地代码相反，删线处
  > 是错的。`resolve_witness`（checker.dawn:5722-5733）与 `assoc_impl_of`
  > （checker.dawn:1266-1277）都是「先查 opaque 自己的 impl，**没有就落到 target**」，
  > 后者的注释还写明了「the order resolve_witness uses」。**witness 穿透，投影也穿透**，
  > 一直如此。opaque 因此自动获得目标类型的 `==`/`${}`/`for..in`，2026-08-02 起也自动
  > 获得 `[]`（`docs/operator-traits-design.md` D2）。所谓「先身份」管的是**类型匹配**
  > （`v == [1,2,4]` 仍被拒，两边必须同为 `Vec`），不是 impl 查找。
- **D10 刀与种子计划**：见 §6。trait-v2 §5 记录过的错误（「刀 1 让语法能 parse 但注册
  报错 = 把种子锁在门外」）在这里的教训是：**刀 1 必须端到端完整**（parse→注册→归约→
  两后端语料），发布后种子才推进；selfhost/std 在刀 2（种子已认识语法）才允许使用。
  预期刀 1 零 Emit-Change（类型全擦除，字典是擦除的 fn-slot 类，勘察 §3），以
  prev-diff 实测为准。

## 3. 表面语法

### 3.1 trait 体里的声明

```dawn
trait Iter[C] {
  type Item
  fn next(c: C) -> Option[(C, C.Item)]
}
```

- `type` 已是关键字（token.dawn:194），trait 体的成员循环（parser.dawn:711-726）加一个
  `TYPE` 分支；仍要求至少一个 `fn`（纯类型成员的 trait 无意义，维持 719-720 的拒绝）。
- 成员名大写（TYPEIDENT）；同名重复声明拒绝。声明顺序无语义。

### 3.2 投影

```dawn
fn sum[C: Iter](c: C) -> Int where ...   # 示意；bound 语法照旧
```

类型位新形：`TYPEIDENT DOT TYPEIDENT`（`T.Item`）。TypeRef 加 `TAssoc(subject, name, spans)`；
`type_ref`（parser.dawn:868-913）在解析出裸大写名后前瞻 DOT。resolve_type
（checker.dawn:597-625）新臂：主体必须解析为类型参数且其 bound 集合里恰有一个 trait
声明了 `name`——零个报「`T` 的 bound 里没有哪个 trait 声明 `Item`」，多个报歧义并
要求换名（首批不提供消歧语法，两个 bound 撞成员名是稀罕事，等真实需求）。

### 3.3 impl 里的绑定

```dawn
impl[T] Iter[List[T]] {
  type Item = T
  fn next(c: List[T]) -> Option[(List[T], T)] = ...
}
```

impl 体（parser.dawn:853-857）同样加 `TYPE` 分支，形式固定 `type 名 = 类型`。
校验（在 impl 方法校验处，checker.dawn:2577-2604 一带）：trait 声明的每个关联类型
恰被绑定一次；多绑、漏绑、绑了 trait 没有的名字，三种各自报错（对照方法覆盖检查的
既有形状）。

## 4. 类型规则

### 4.1 表示

- `TraitI` 加 `assoc: List[String]`（名字即身份；无 bound 无默认，List 留多成员余地）。
- `Ty` 加 `TyAssoc(subject: Ty, trait_id: Int, name: String)`。**规范形不变式：ground
  类型里不出现 `TyAssoc`**——它只能以刚性类型参数为主体存活（D3）。十处穷尽臂
  （勘察备忘录列全）按此不变式实现：位于归约下游的（ty_key_inst、desc_of、jvm_repr、
  hash_of、emit_unerase、unerase、subst_tvar、c_repr）panic 点名不变式；ty_show 与
  subst 是仅有的两处真实实现（渲染 `T.Item`；替换主体后尝试归约）。
- `ImplI` 加 `assoc_bindings: List[(String, Ty)]`（RHS 在 impl 类型参数作用域内解析）。

### 4.2 归约

`reduce_assoc(cx, t)`：`TyAssoc(s, tid, n)` 且 `s` 有具体头 → `impl_at(tid, s)`（与
witness 同门，D5）→ 取该 impl 的 `assoc_bindings[n]`，用 impl 的 tparam 代入表实例化。
调用点两处：`subst`（types.dawn:412）代入后、`resolve_type` 解析出 TyAssoc 时（主体
若已具体——首批语法上不可能，防御性保留）。归约结果再走一次 reduce（绑定 RHS 引用
另一投影的情况被 D6 禁止，故实际至多一层；防御性循环带深度上限，超限=内部错误）。

### 4.3 unify 与相等

`unify_into`（checker.dawn:986-1040）：`TyAssoc` 只与结构相等的 `TyAssoc` 合一
（主体、trait_id、名字三同）；对任何其他形状报 D7 的错误。`bound == actual` 的冲突
检测（1016）因规范形不变式无需改动——能到那里的类型已 ground。

### 4.4 与既有机制的交互

- **字典轨零改动**（勘察 §3 的核心红利）：字典是按 `dict_key = ty_key_inst(subject)`
  命名的擦除 fn-slot 类（lower.dawn:568、codegen.dawn:3379-3386），RC 账本外
  （types.dawn:281-286）。投影在进 dict_key 之前必已归约（不变式），否则 panic 臂
  抓住——这就是缺件 10 的守卫。
- **方法签名实例化**：`subst_subject`（lower.dawn:1892）代入主体后跑 reduce_assoc，
  impl 方法的期望签名随之落地成 ground 签名，校验照旧。
- **条件 impl**：`sub_goals`/约束求解不变——投影不进约束（D6）。
- **RX-10-B（效果参数进类型参数表）**：正交；`type Item` 是类型轴成员，效果轴另说。
- **comptime/interp**：类型层特性，interp 无感。
- **doc/fmt/LSP**（勘察 §7）：doc.dawn trait 渲染加 assoc 数组（形状照 #115 的 effects
  先例）；fmt 免费正确（词法级，`type` 行与 `T.Item` 实测幂等，零改动）。LSP：实施时
  发现补全对**任何** `.` 后位置都返回空（lspc.dawn:226，模块成员也不补）——「`T.` 后补
  关联类型名」没有可搭的机制，会是第一套点号补全，超出本刀；投影随既有基线，
  点号补全整体另立项。doc 的输出变化带 `Emit-Change(doc *)` 声明。

## 5. spec 落点

§trait 节（勘察 §6 的坐标）：成员声明文法、impl 绑定义务（恰一次）、投影的许可位置
（方法签名）与主体限定（bound 类型参数）、归约语义（与 witness 同一 impl）、
错误目录（无 bound 声明者/歧义/漏绑多绑错绑/cannot determine）。EBNF 同步
（doc-check 的 blocks 会验 `dawn compile` 标记的示例）。

## 6. 分期（自举力学）

种子 vN 不认识 `type Item` / `T.Item`，一代滞后照旧：

1. **刀 1（端到端完整批）**：lexer 无改动（`type`/DOT 都是现成 token）；parser 两个口
   （trait 体、impl 体）+ TypeRef 新形；TraitI/ImplI/Ty 三处表示；注册/校验/归约/unify；
   十处穷尽臂；doc/fmt/LSP 三件；spec + tutorial；双后端差分语料（Iter 形状的用户侧
   语料，std 不动）。**selfhost/src 与 std 不得使用新语法**。存量语料零 Emit-Change
   （类型擦除，prev-diff 实测确认）；doc 输出变化按标签声明。
2. **发布 + 种子推进**。
3. **刀 2（消费者批）——已落地（2026-08-02）**。原计划「std 提供 `Iter` trait」，
   落地时三项定案 + 两项现场发现：
   - **Iter 是第 5 个 prelude trait**（ITER_ID = 4），不是 std trait：`for` 要它
     的 witness 就像 `==` 要 Eq 的，不能系于 import。方法注入 cx.fns 照旧
     （不注入的长期方案归 #119）。
   - **方法名 `iter_start/iter_done/iter_next/iter_get`**：撞名勘察证明短名
     start/done/next/get 会把 std 编译坏（7 个 std 顶层 fn 声明期报错 + builtin
     get 静默改绑）。四个名字随 prelude 注入成为保留名（spec §10.6/§11）。
   - **五个 impl 全落**：List（Cur = Int，原四件套收进 impl）、String（Cur =
     cursor.Cursor，Item = 单字符 String，对齐 `chars` 的元素形状）、Bytes
     （Cur = Int，Item = Int）、Map/Set（**物化游标**：iter_start 物化
     entries/to_list，Cur = (List, Int)——trie 今天没有公开游标，列表随机访问
     O(1)、count 是存量字段，起步一次分配、每步 O(1)；将来 std/hamt 长出真游标
     只改 Cur 与四个方法体）。head_owner 增补 HString→std/str、HBytes→std/bytes
     （不然两个 impl 是 orphan）；modules.txt 里 list 提到 bytes 之前（bytes 自己
     的 for 现在需要已注册的 impl）。
   - **现场发现 1（刀 1 的 ABI 洞）**：devirtualized 调用与字典桥按 trait 侧签名
     拼 callee 形状，投影一律按擦除槽——绑定是基元时（`Cur = Int`）与 impl 方法
     自己的声明签名（校验钉死的那个形状）分道，JVM 直接 NoSuchMethodError。刀 1
     语料只覆盖了 `Option[C.Item]` 这类恒引用形状所以没暴露。修法 = subst_subject
     （lower 与 emit）跑注册校验用的同一个 reduce_via_bindings（搬进 types.dawn，
     一份定义三处读）；**绑定 RHS 原样代入**——`Item = T` 必须保持擦除槽，实例化
     它与不归约同样是错。语料 assoc_abi.dawn 钉住三条路径。
   - **现场发现 2（自举力学偏差）**：D10/施工单设「种子已认识语法，std 可放心用
     新语法」——对 *prelude* trait 不成立：种子 parse 得了 `impl Iter[...]` 却
     check 不了（它的 prelude 没有 Iter），而它的 lower_for_list 又按名字要那四个
     自由函数。同一份 std 源无法同时满足两代编译器。解法不是过渡垫片而是修自举
     契约：**N−1 侧一律与它发布时的 std 配对**（seedjar.sh 的 seed_std_dir /
     seed_root，bin/dawn stage 1、fixpoint A 段、prev-diff、run/lsp 转写全部收口）。
     种子特性纪律不变——N−1 jar 仍须编译 HEAD selfhost/src（prev-diff 那行从来
     没传过 --std）。
   for 的 lowering 走 lower_trait_call 的合成调用（与源代码级 trait 调用同一扇门），
   `continue` 先跑 step 的语义靠 CSLoop 第三参保持。泛型 `for`（`[C: Iter]` 函数体内
   对 rigid 主体迭代）是新表达力。带 `Emit-Change(emit *)`；存量程序行为逐字节不变
   由 run-diff 验收。
4. **刀 3（可选，另行立项）**：运算符 trait（`xs[i]` 的 index_wanted 特判退休，
   checker.dawn:3874）——等刀 2 落地后按 #110 的立项纪律单开。

## 7. 开放问题（不阻塞 v1，留档）

1. **投影主体放宽到任意类型**（`List[Int].Item`）：需要 resolve_type 之后的第二次
   归约机会或 pass 重排——等消费者。
2. **关联类型 bound**（`type Item: Ord`）：缺件 8 的表示 + impl 校验；运算符 trait
   若需要（如 `Index` 的 `Output: Sized` 类比）再谈。**#123 裁决：本体搁置**，
   但它留下的四处不一致已在 #123 缺陷批修平——`C.Item` 上要 Show / Ord / Eq / Hash
   一律在检查期拒绝、同一句措辞、同一条 hint（`assoc_witness_err`）。修之前
   Eq/Hash 是**检查期放行、lower 期编译器 panic**（`unreduced projection in
   ty_key`），根因是 `structural_gap` 无 TyAssoc 臂、且 `is_ground(TyAssoc)`
   与 §4.1 的规范形不变式相反地答 true。今天的出路只有一条，hint 就指它：
   把投影原样传出，在调用点（已归约成具体类型的地方）做那件事——
   `scripts/spike-native/index_dict.dawn` 的 `both` 是活的例子。
   语料在 `scripts/checker-corpus/cases/projection_witness.dawn`。
3. **多 bound 撞成员名的消歧语法**：首批报错要求换名；真撞了再给全限定形
   （勘察 D2 选项 c 的语法预留着）。
4. **`Map[Ty,…]` 键含投影**：规范形不变式下 ground 键不含投影；若未来放宽 D6，
   缺件 9 的规范形比较问题回来——届时先读效果 D2 的同族分析。
