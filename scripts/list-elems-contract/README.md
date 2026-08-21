# list-elems-contract

列表字面量两种元素形式（spec §4.11）的负控：`[a, ..xs]` 与 `[a, if c { b }]`。

```bash
./scripts/list-elems-contract/run.sh                     # 全部
./scripts/list-elems-contract/run.sh --only cond-body-loses-expectation
./scripts/list-elems-contract/run.sh --record            # 重录 matrix.txt 的 red 行
python3 scripts/list-elems-contract/matrix.py --selftest  # 本门禁自己的控制
```

## 为什么需要它

行为本身已经被三份语料钉住：`grammar-corpus/accept/list_elems.dawn` 管解析，
`checker-corpus/cases/list_elems{,_bad}.dawn` 管类型与全部诊断（顺序在内），
`spike-native/list_elems.dawn` 管两个后端的运行结果（含 AddressSanitizer）。

它们钉不住的是**每条规则由实现里恰好一句话负责**，而这条性质会无声地烂掉。
最要命的一条是**期望类型下推**：

```dawn
# text: fn text[M](s: String) -> Widget[M]，M 只出现在返回类型里
[text(s)]                    # 报错：cannot infer type parameter(s) M
[header, if c { text(s) }]   # 可以：header 定下 M，期望穿进条件元素的 body
```

把下推删掉，上面三份语料**一条都不会红**——它们里的程序会继续编译，只是变成
「本来就不需要下推」的那些程序。`cond-body-loses-expectation` 就是让这个差别
可观测的那个变异体，也是本目录存在的理由。

结构抄自 `scripts/pipe-contract`（gate-map 自己的变异体矩阵点名的那份先例），
裁到「每句话一次编译器构建」需要的最小形状。`matrix.py` 是**加载器不是第四份拷贝**：
pipe-contract 的那份里没有一行是关于管道的，而一份没人再跑的 selftest 与一份
不会红的 selftest 输出相同。

## 断言

一个 case 一个文件：一条诊断会带走整个文件，所以两个形状共用一个文件就没法各自
拥有断言（pipe-contract 实测过）。

| 断言 | 形状 | 判据 |
|---|---|---|
| `spread_item_type_joins` | `[1, ..xs]`，`xs: List[String]` | 必须拒绝 |
| `spread_operand_must_be_list` | `[1, ..5]` | 必须拒绝 |
| `cond_condition_is_bool` | `[0, if n { 7 } else if n == 1 { 8 }]` | 必须拒绝 |
| `spread_operand_gets_expectation` | `[x, ..[]]` | 必须接受 |
| `spread_defers_to_second_round` | `[..[], Some(1)]` | 必须接受 |
| `cond_body_gets_expectation` | `[anchor, if c { nameless("x") }]` | 必须接受 |
| `cond_arm_settles_later_arms` | `[if a { anchor } else if b { nameless("y") }]` | 必须接受 |
| `cond_defers_to_second_round` | `[if c { None }, Some(1)]` | 必须接受 |
| `else_if_chain_compiles` | `[0, if n == 1 { 11 } else if n == 2 { 22 }, 9]` | 必须接受 |
| `cond_false_contributes_nothing` | 跑起来 | stdout 逐字节 |
| `else_if_chain_picks_first_true` | 跑起来 | stdout 逐字节 |
| `plain_literal_unmoved` | `[1, 2, 3]` 与带 else 的 if 元素 | stdout 逐字节；**控制** |

**「必须接受」的 case 一律不写标注。** 这是承重的：`let out: List[Tagged[Int]] = ...`
会用另一条路把同一个期望送进去，于是断言就不再是关于元素形式的了。最初四个 case
带着返回类型标注，两个 `needs-expected-*` 变异体因此**全绿**——语料在测一件它
以为在测的事。改掉标注之后它们都红了。

`plain_literal_unmoved` 是控制，由 `run.sh` 手工守（不进矩阵）：一份能长出这一行的
记录仍然与自己相符，所以「这个特性没碰它不该碰的东西」这句话，红集对账说不出来。

## 矩阵就是门禁

每个变异体都跑**整套**断言，红集与 `matrix.txt` 双向对账。只断言「变异体 X 让断言 A 红」
等于把归属写进散文里、什么也不强制。三条规则见 `matrix.py`：counted 变异体有 owner
且 owner 在自己红集里；没有第二个 counted 变异体让那个 owner 红；观测红集与记录逐条相等。

### 十个变异体

| 变异体 | 删掉的那句话 | owner |
|---|---|---|
| `spread-item-type-not-joined` | 展开贡献的是操作数的**元素**类型 | `spread_item_type_joins` |
| `spread-operand-list-check-dropped` | 而且操作数得先是个列表 | `spread_operand_must_be_list` |
| `spread-operand-loses-expectation` | 元素类型以 `List[T]` 的形状穿过 `..` | `spread_operand_gets_expectation` |
| `cond-body-loses-expectation` | 条件元素的 body 在元素类型上检查（**杠杆**） | `cond_body_gets_expectation` |
| `cond-condition-unchecked` | 每一臂的条件都是 `Bool` | `cond_condition_is_bool` |
| `else-if-chain-truncated` | 没有末尾 else 的链整条是一个元素形式 | `else_if_chain_compiles` |
| `cond-always-contributes` | 只有被选中的那一臂才追加（lower） | `cond_false_contributes_nothing` |
| `cond-arm-does-not-settle-later-arms` | 同一条链里前一臂为后一臂定型 | recorded |
| `needs-expected-blind-to-spread` | 需要期望的展开推迟到第二轮 | recorded |
| `needs-expected-blind-to-cond` | 条件元素同上 | recorded |

owner 是**建出变异体读出来的**，不是预测的；`matrix.txt` 是那次读数被放在 diff 底下。

### 三个重新瞄准

* **`spread-operand-list-check-dropped`** 只瞄拒绝那一臂。设计中的变异体删掉整个
  `match`，那样每个合法展开都改成贡献 `List[T]` 而不是 `T`，于是
  `spread_operand_gets_expectation` 与 `spread_defers_to_second_round` 也会红，
  前者是别人的 owner。
* **`spread-item-type-not-joined`** 同理只改贡献值，把列表检查留着——两句话各一刀。
* **`cond-body-loses-expectation`** 反过来放宽到整行。先前拆成「fallback」与
  「臂间传递」两刀，结果后者的红集是前者的真子集**且**被
  `else-if-chain-truncated` 一并拿走（两臂的链正是它拆掉的东西），于是那个断言
  谁也不拥有。整行一刀之后 owner 是干净的，臂间那半仍以 recorded 变异体在案。

### 三个 recorded

它们各自让一个断言变红——规则**有**守卫——只是拿不到 owner，理由写在 `matrix.txt`
里，结论都一样：红集是另一个变异体的真子集，而且是结构性的，不是碰巧。
`needs-expected-*` 那两个尤其干净：推迟只对「离开期望就没法检查」的元素有意义，
而那恰好就是下推要够到的元素，所以下推总是先断。它们留在列表里是因为
`mutate.py` 会拒绝对不上的锚点：把那句话删掉仍然是一次响亮的失败，不是一次绿。

## 不在这里

* **native 后端上的求值。** `scripts/spike-native/list_elems.dawn` 已经把同一批
  形状在两个后端跑过并对拍（含 asan 与泄漏检测），为一条规则再建一个 native 变异体
  等于把一个后端付两遍钱。
* **格式化。** `dawn fmt` 对这两种形式零改动，而那是 `front/fmt.dawn` 里一个具名
  内联 test 钉住的——包括单行、多行、尾逗号、嵌套与幂等性。
* **`[{ None }, Some(1)]`**（裸块元素）。它今天被拒绝，落地前就被拒绝，理由是
  `needs_expected` 没有 `EBlock` 臂。见 `checker.dawn` 的 `if_body_value`：那里
  只剥了 `if` body 这一处，因为给 `needs_expected` 加一条通用臂会重排全仓每个实参
  与每个 match 臂的两轮顺序。那是另一笔账。
