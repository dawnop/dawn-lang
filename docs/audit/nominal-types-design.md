# 给标量一个自己的身份：`Char` 与 newtype

> 状态：**步 1–3 驳回（proposed → rejected）** —— 见文首 2026-07-30 重判：机制已由
> `opaque type` 提供。**但 LANG-04 本身还是活账**：`'a'` 仍是 `Int`，
> `opaque type Char = Int` 与 `char_of` 全仓零命中；它等的 Phase 6 已于 2026-07-30 出口，
> 前提解除、活没干（步 4，见文末）。
>
> 动码前的**调研与方案**，不是设计定稿。
> 覆盖 codebase-audit.md 的 **LANG-04（P2）** 与 **LANG-05（P2）**。
>
> **2026-07-30 重判：步骤 1–3 驳回，机制已存在。** 本文成文时没有对着当时已落地的
> `opaque type`（spec §2.7，S2.3）对账——而它就是这里要发明的东西：
> `pub opaque type Meters = Float` 模块外名义不互换、零开销、可写自有 impl 且优先于
> 目标类型（「先问身份再问表示」）、Map 键合法性经 `[K: Eq+Hash]` bound 自然穿透
> （opaque-over-Float 没有 Hash impl 就当不了键，无后门可开）、`opaque-twin` 门禁
> 机器化守护语义。`new` 相对它只多两件事：**模块内也名义**（opaque 在声明模块内
> 透明）与**自动生成转换函数对**——前者保护的是模块对自己的纪律（模块内代码量小、
> 自我审查成本低），后者是两行手写函数的糖。为这两件边角引入第二个名义包装机制，
> 正是本仓「一件事一份定义」要杀的表面重复。
>
> **各条目的去处**：LANG-05（alias 被当单位安全示例）→ 已修：spec §2.6 现在直接
> 指路 §2.7。LANG-04（Char）→ 机制用现成的 `pub opaque type Char = Int` + 受检构造
> `char_of(n: Int) -> Option[Char]`（§2.4 的 API 形状仍然对），作为独立迁移刀排队
> ——Phase 6 已于当日出口，冻结解除，但 `'a'` 字面量类型切换牵动 lexer/json/fmt
> 全部调用点与一次发布窗口，不与任何东西合并做。步骤 4 的排期理由不变，等待对象
> 从「Phase 6 排期」改为「有人真的需要 Char 而不是 Int 的那一天」。
>
> 原状态：**步骤 1–3（`type X = new T` 的语言机制）proposed 且可做；
> 步骤 4（`'a'` 变 `Char`）冻结，与
> [`../native-backend-plan.md`](../native-backend-plan.md) 的 **Phase 6** 合并做。**
> 那一阶段要把 `java.lang.Character`/`Long.parseLong` 从 lexer/parser 里纯 Dawn 化，
> 碰的是同一批码点算术。撞车登记见
> [native-plan-overlap.md](native-plan-overlap.md) §3.6。

两条放一起，因为解法是同一个机制的两次使用：**一个与底层表示等价、但类型系统上不互换的
名义类型**。`Char` 是 std 用它做的第一件事，newtype 是把这个能力交给用户。

## 一、问题

### 1.1 字符只是 `Int`（LANG-04）

`docs/spec.md` §1.5 把字符字面量定义为码点 `Int`；§11 又规定非法码点在
`from_code_points` / `str.from_char` 时 panic。于是：

- 任意整数都能冒充字符，编译期不拦；
- API 签名区分不了索引、计数、字节和字符——`fn f(a: Int, b: Int, c: Int)` 里
  哪个是码点全靠参数名和注释；
- 「非法码点」这件事只能在运行期发现，而且是 panic，不是 `Result`。

审查那句论据很强：**`Cursor` 已经证明不透明标量在这门语言里可行。**
`std/cursor.dawn` 的文件头写得很直白：

> The underlying operations are compiler intrinsics: their signatures use the
> opaque `Cursor` type, which std source cannot mint from an Int — that opacity
> is the whole point (arithmetic on a position is a type error).

`Char` 该用同一套。

### 1.2 透明 alias 被当成领域安全的示例（LANG-05）

`docs/spec.md` §2.6 第一行就是 `alias Meters = Float`，下面才说它与 `Float`
完全互换。**示例的位置比说明显眼**，读者很容易以为得到了单位安全。

2026-07-25 已经在 §2.6 加了警示（`Meters` 与 `Seconds` 可以相加，
函数收 `Meters` 时传裸 `Float` 也照过）。那是止血——真正缺的是
「想要单位安全时该用什么」的答案，而 Dawn 目前没有那个东西。

## 二、方案

### 2.1 一个机制：`type N = new T`

```dawn
type Meters = new Float          # 名义类型，表示与 Float 相同
type UserId = new Int
type Char   = new Int            # std 内部就这么定义
```

语义：

- **表示等价**：运行期就是底层类型，零开销，擦除后同一个 JVM 类型；
- **类型不等价**：`Meters` 与 `Float`、`Meters` 与 `Seconds` 都是编译错误；
- **不继承运算**：`Meters + Meters` 默认**不合法**——加法是 `Float` 的，不是 `Meters` 的。
  想要就 `impl` 一个 trait，或者写显式函数。

### 2.2 出入靠一对函数，而不是隐式转换

```dawn
pub fn meters(f: Float) -> Meters        # 构造
pub fn to_float(m: Meters) -> Float      # 拆开
```

编译器为每个 `new` 类型自动生成这两个（名字规则：构造 = 类型名转 snake_case，
拆开 = `to_<底层类型>`）。**不生成隐式转换**——隐式转换会让整件事退化回 alias。

### 2.3 可见性决定它是 newtype 还是 opaque type

这是本方案最省事的一处设计：**不引入第二个关键字**。

```dawn
# 模块内：构造和拆开都可见 → 就是 newtype
type UserId = new Int
pub type UserId = new Int              # 构造/拆开随类型一起 pub → newtype

# 只 pub 类型，不 pub 转换函数 → 对外就是 opaque type
pub type Token = new String
# （编译器生成的 token()/to_string() 默认跟随类型的可见性；
#   要做 opaque 就手写一个 pub 的受检构造函数，把自动生成的那个留在模块内）
```

`Cursor` 正是后者的极端情况——它的构造函数根本不存在于 std 源码里，只有 intrinsic。

### 2.4 `Char` 用它重新定义

```dawn
# std/char.dawn（新增）
pub type Char = new Int

## A code point, or None when `n` is not a Unicode scalar value
## (negative, > U+10FFFF, or in the surrogate range D800–DFFF).
##
## Returns Option rather than panicking: "is this integer a character" is a
## question with a legitimate negative answer — it is exactly what a parser
## reading \u escapes needs to ask. spec §11's panic-on-invalid stays for the
## bulk conversions (from_code_points), which are not asking a question.
pub fn char_of(n: Int) -> Option[Char]
pub fn code(c: Char) -> Int
```

字符字面量 `'a'` 的类型从 `Int` 变成 `Char`。这是**破坏性变更**——
所有把 `'a'` 当 `Int` 用的代码要改。仓库里量不小（`lexer.dawn`、
`packages/json` 的 lexer、`fmt.dawn` 全在做码点算术）。

**过渡**：`code(c)` 拆出 `Int` 之后一切照旧。改动机械，但要一次改完，
因为半途状态下 `'a'` 到底是什么类型会很难讲。

**与 native 计划 Phase 6 合并做。** 那一阶段要把 `java.lang.Character` /
`Long.parseLong` 从 lexer/parser 里纯 Dawn 化（已定 ASCII-only），
碰的是**同一批**码点算术，且同样是「必须一次改完」的机械大改。分两次做，
第二次要把第一次的成果全部重写一遍。

顺序上 **`Char` 要先落**：纯 Dawn 的 `char_is_digit`/`char_is_alpha` 之类
写在 `Char` 上才是对的签名。反过来先写在 `Int` 上，等于把同一批函数签名改两遍——
而那批函数正是这个语言里最不该有类型歧义的地方（lexer 靠它们分辨 token）。

## 三、语法与冲突分析

### 3.1 `new` 作为关键字

`new` 今天不是关键字，但 `use java` 的对象构造用的就是这个词
（`ProcessBuilder.new([...])`）——那是**成员位置**的 `new`，
而这里是 `type X = new T` 的**类型位置**。两者不在同一个语法位置，parser 不需要消歧。

风险是读者的：同一个词两个意思。备选是 `nominal`、`distinct`、`opaque`。
**倾向 `new`**：它是 Haskell/OCaml 的既有词汇，读者的先验是对的；
`ProcessBuilder.new` 那个是 Dawn 自己发明的用法，反而更该让路。
这条留待定稿时再定。

### 3.2 与 `alias` 的对照

改完之后规范里是清楚的三分：

| 写法 | 是什么 |
|---|---|
| `alias X = T` | 透明，与 `T` 完全互换，给长类型起短名 |
| `type X = new T` | 名义，表示同 `T`，类型不互换 |
| `type X = \| A \| B` / `type X = { .. }` | 名义，表示是新的 |

`docs/spec.md` §2.6 那句「别名有自己的关键字 `alias`；`type` 只声明名义类型」
在改完之后仍然成立，且更整齐了——`new` 是 `type` 的第三种右侧。

### 3.3 与 trait 的交互

`type Meters = new Float` 之后 `Meters` 能不能 `derive Ord`？
**能**，且应该——`derive` 直接转发到底层类型的实现。
`derive Show` 同理（渲染成 `Meters(1.5)` 而不是 `1.5`，保持
「渲染成合法 Dawn 源码形状」的既有约定）。

`Map` 的键类型限制（spec §2.2：`Float`/`Bytes` 不得作键）要**穿透 newtype 判断**——
`type K = new Float` 不能作键，理由与 `Float` 相同。这是必须记住的一条，
否则会开一个后门。

## 四、为什么不顺手把 X 也改了

- **不做单位运算**（`Meters / Seconds = MetersPerSecond`）。那是依赖类型级别的
  算术，与本文的「零开销名义类型」不是一个量级。想要的人可以用 trait 手写。
- **不给 `Bytes` 改成 newtype**。`Bytes` 已经是一等类型（spec §9.5.1），
  不是 alias。
- **不动 `Cursor`**。它已经是这个方案的手工版本，改成 `new` 表述是纯粹的整理，
  没有收益，且它的 intrinsic 绑定要重做。落地后可以顺手，但不是目标。

## 五、不做的（记录理由）

- **让 newtype 自动继承底层类型的全部运算**。看起来贴心，实际会让
  `Meters + Seconds` 合法——那正是这个特性要防的东西。继承运算就是 alias。
- **给 newtype 加运行期检查**（构造时校验不变量）。`Char` 需要校验，
  但那是 `char_of` 这个**手写**构造函数的事，不是语言机制的事。
  把校验做进语言意味着每个 newtype 构造都要付一次检查的开销。
- **引入第二个关键字区分 newtype 与 opaque**。可见性已经能表达（§2.3）。
  多一个关键字就多一组要解释的组合。
- **在 `Char` 落地前先做 newtype 却不用它**。两者一起做：`Char` 是这个机制的
  第一个真实用户，没有真实用户的机制会设计歪。

## 六、落地点

| 步 | 状态 | 文件 | 测试 |
|---|---|---|---|
| 1 | **可做** | `selfhost/src/parser.dawn`（`type X = new T`）、`ast.dawn` | parser 内联 test |
| 2 | **可做** | `selfhost/src/checker.dawn`（名义等价、自动生成的两个转换、`derive` 转发、Map 键限制穿透） | 「`Meters` 与 `Float` 不互换」「`new Float` 不能作 Map 键」 |
| 3 | **可做** | `selfhost/src/emit.dawn`（擦除到底层类型，零开销） | fixpoint；`new Int` 的算术与裸 `Int` 发射同样的字节码 |
| 4 | **冻结**，与 Phase 6 合并 | `std/char.dawn`；`'a'` 的类型改为 `Char`；`lexer.dawn`/`packages/json`/`fmt.dawn` 全部调用点 | 全量 + JSONTestSuite |
| 5 | 随 4 | `docs/spec.md` §1.5、§2.6、§11 | — |

步骤 1–3 是纯**新增**，不破坏任何现有代码，可以先发；它们也让 LANG-05
（透明 alias 被当成领域安全的示例）**立刻**有答案可写进 spec §2.6，
不必等步骤 4。步骤 4 是破坏性变更 → 先发 tag，dawnop-site 再 bump。

> 步骤 3 会动 `emit.dawn`，而 Core IR（native 计划 Phase 0）也在动它。
> 冲突面很小（新增一条擦除规则 vs 搬走整棵树的遍历），但**排在 Phase 0 之后更省事**——
> 一条擦除规则写进 `lower.dawn` 比写进两个地方便宜。
