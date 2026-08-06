# 给标量一个自己的身份：`Char` 与 newtype

> 状态：**步 1–3 驳回（proposed → rejected）；步 4 施工中（2026-08-06 起）** ——
> 见文首 2026-07-30 重判：机制已由 `opaque type` 提供。LANG-04 于 2026-08-06 开工，
> 分两个 release 落地，**落地形状与分期见文末第七节（设计补充）**——那一节补的是
> 本文没答的三件事：Char 由谁铸造、分期的接缝落在哪、`cursor.char` 的哨兵怎么办。
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

---

## 七、2026-08-06 设计补充：步骤 4 的落地形状

> 状态：**步骤 4 施工中**。本节是动码时补的裁决，补的是原文没答的三件事。
> 原文写在 `'a'` 的类型这件事被真正排期之前，所以它给了机制（`opaque type Char = Int`）
> 却没给**分期**——而分期是这件事唯一难的部分。

### 7.1 Char 由编译器铸造，不由 std 声明

原文 §2.4 写的是 `std/char.dawn` 里一行 `pub opaque type Char = Int`。
**不能这么做**，理由是自举而不是品味：

- `'a'` 是**语法**。checker 给字面量定型时必须拿得到 Char 的 `Ty`，而 std 是被编译的
  源码——让字面量的类型依赖某个 std 模块已经检查完毕，是把层次倒过来。
- 更硬的一条：种子那一代必须已经认识 `Char` 这个名字（见 7.2），而认识它的方式
  是 `ty_named`；一旦 `ty_named` 认了，`passes.dawn` 的 `is_builtin_name` 就会把
  std 里的 `type Char = ...` **判成重复声明**。声明式与转发式二选一，不能并存。

所以：`ty_named("Char")` 直接返回一个编译器自己铸的
`TyOpaque(<保留 id>, "Char", "std/char", TyInt)`。**机制仍然是 `opaque type`**
——2026-07-30 那次重判（「`Cursor` 已经把 `Ty` 变体删掉了，别再加一个」）照办：
不新增 `Ty` 变体、不新增 `Head`、不动 eq/hash/ord/show 四张标量表，
`peel_opaque` 那条既有的路径把它送到 `Int` 的实现上。
`std/char` 是它的 owner，所以那个模块（且只有那个模块）能把它看成 `Int`，
`char.of` / `char.code` 因此是两行普通函数，不需要任何新 intrinsic。

代价记在这里：这是仓库里第一个**没有声明点**的 opaque 类型，
`opaque-twin` 门禁的语料要多一行，否则它是唯一一个不被那道门禁看的 opaque。

### 7.2 分期：两个 release，破坏只发生一次

原文只说「一次改完」，没说这在自举链里做不做得到。做得到，但要两期——
而两期的**接缝不能落在 `'a'` 上**，否则就出现了原文警告的那个半途状态。

接缝落在**类型名**上：

| 期 | release | `Char` 是什么 | `'a'` 是什么 | selfhost/std 用不用 `Char` |
|---|---|---|---|---|
| 1 | v0.54.0 | `Int` 的透明拼法（`ty_named` 一行） | `Int` | 不用 |
| 1.5 | v0.56.0 | 同上 | `Int` | 只有 `std/char` 这个模块先落地（7.7） |
| 2 | v0.57.0 | 名义（7.1 的 opaque） | **`Char`** | 全线用 |

> 这张表原本只有两行、期 2 排在 v0.55.0。中间多出来的一行是 2026-08-06 实测出来的：
> 接缝不止「类型名」一件，还有「谁能造出一个 `Char`」那件——**桥所在的模块也必须
> 提前一版进种子**。理由、量法与收口见 7.6/7.7。

**期 2 的种子相容性证明**：种子眼里 `Char ≡ Int`、`'a' : Int`。
期 2 的源码里每一处 `Char` 标注，在种子看来都是 `Int` 标注，每一个 `'a'` 都是
`Int` 字面量，两边都过；HEAD 眼里它们全是 `Char`，也过。**两种定型都成立，
且擦除后是同一份字节**（Char 的表示就是 Int）。语义等价，因为种子给
`Char` 选的字典/见证就是 `Int` 的那一份，而那正是 HEAD 要的实现。

反过来说明为什么不能一期做完：期 1 若直接把 `Char` 做成名义的，
期 2 的 `let c: Char = 'a'` 在种子眼里就是「名义 Char ← Int」，编不过。
透明那一版不是妥协，是**接缝本身**。

### 7.3 `cursor.char` 保持 `Int`，哨兵与类型不能共处

spec §4.8 的「唯一具名例外」是 `cursor.char(s, c)` 到尾回 `-1`
（理由是每步包 `Option` 就是每步一次分配，`packages/json` 的 lexer 靠它）。
`-1` 不是码点，所以它**不能**是 `Char`——否则 `Char` 的定义域立刻有个洞，
而定义域正是这个类型存在的理由。

裁决：`cursor.char` 留在 `Int`，并在文档里把它点名为 Char 层**下面**的原语；
Char 面是 `str.at`、`str.chars`、`code_points`。判据是「这个函数的答案是不是
永远是一个字符」——`cursor.char` 不是，所以它不该拿这个类型。

### 7.4 `"${c}"` 渲染成码点数字

opaque 沿用目标类型的 impl（spec §2.7、§4.8），所以 `Char` 的 `Show` 是 `Int` 的：
`"${c}"` 出 `97` 而不是 `a`。**这是刻意的**，改它要给 Char 单独写一份 `Show`，
而那会让它不再「就是它的目标」，`opaque-twin` 那条判据也就不成立了。
要一个字符的字符串，`str.from_char(c)` 就是那个函数。

### 7.5 谁能造出一个 `Char`：三处约束把桥的位置定死了

期 2 施工时撞出来的，写在这里免得下一个人再推一遍。三条约束同时成立：

1. **`char_is_*` 必须改成收 `Char`。** lexer 手里的 `s.cps[i]` 是 `Char`（`code_points`
   随之变成 `List[Char]`，否则 `s.cps[i] == '\n'` 两边类型对不上）。如果判词还收 `Int`，
   lexer 就得先把 `Char` 拆回 `Int`，而拆的那个函数在 std/char 里——见第 2 条。
2. **`selfhost/src` 在 v0.55.0 里还 `use` 不了 `std/char`。** `bin/dawn` 的 stage 1 用
   **种子自带的那份 std** 编译今天的 selfhost，而 v0.54.0 的 std 里没有 char 这个模块。
   所以 selfhost 只能调**内建**（`char_is_*` 是内建，永远在）；`char.code` / `char.of`
   要等种子推到 v0.55.0 之后、即 v0.56.0 那一轮才轮得到 selfhost 用。
3. **`std/str` 拿不到 `Char`。** 它的 `trim` 走 `cursor.char`（回 `Int` 且带 `-1` 哨兵，
   7.3 定的），却要喂给已经改成收 `Char` 的 `char_is_space`。std/str 不是 `Char` 的 owner，
   看不穿，造不出来。

三条一夹，桥只能是**一个内建**：`char_unchecked(n: Int) -> Char`，internal（只有 std 能写），
lowering 是恒等（`Char` 的表示就是 `Int`，两个后端各加一条直通的 case，同
`cursor_slice` 那种「发射器内联写掉」的先例）。它不必进种子——std 是 stage 2 用**今天的**
编译器编的，所以与它同一个 release 引入即可用。

被否掉的两条替代：
- **让 `cursor.char` 直接回 `Char`**（内建签名一改就成，不需要任何模块去构造）。
  否，理由是 7.3：那样 `-1` 就成了一个 `Char`，而「每个值都是码点」正是这个类型的全部内容。
- **`std/char` 出一个 pub 的无检查构造函数**。否，RD-01 刚把 pvec 的公开无检查读取器拿掉，
  再开一个是往回走；判据一致：无检查的东西不该是 pub 的。

### 7.6 期 2 的第四条约束：selfhost 也造 `Char`，而它够不着 std 的桥

7.5 数了三条约束就收口，桥定成一个 **internal**（只有 std 能写）的 `char_unchecked`。
2026-08-06 复核 `selfhost/src/lexer.dawn` 时发现**第四条**，它推翻那个收口：

**`selfhost/src` 自己就要从 `Int` 造 `Char`，而它不是 std。**
`lex_unicode` 把 `\u{...}` 的十六进制位算成一个码点（`cp = cp * 16 + d`），算完要塞进
`buf: List[Char]`（`code_points` 改签名后 `Src.cps`、`SourceView.cps` 全线是 `List[Char]`）。
7.5 的第 2 条已经证明 selfhost 在 v0.55.0 **不能 `use std/char`**（stage 1 用种子那份 std）；
而 `char_unchecked` 若是 internal builtin，`internal_builtins` 按 `cx.is_std_module` 过滤，
selfhost 同样看不见。两条一夹，**期 2 的 selfhost 无法构造任何 `Char`**——除非桥是一个
对用户代码可见的内建。

三条出路（2026-08-06 裁决：**三条都不选，选第四条**，见 7.7）：

1. **两个内建**：`char_of(n: Int) -> Option[Char]` 公开且**受检**（故不违反 RD-01——
   被否的是「无检查的 pub」，不是「pub」），加 internal 的 `char_unchecked` 供 std 热路径
   （7.5 第 3 条的 `str.trim` 走 `cursor.char` 那条）。lexer 用受检那个：转义本来就要
   拒绝非法码点，`None` 正好是那条诊断，比现在的写法更严。`std/char.of` 降为一行转发。
2. **只要 `char_of`**（受检，公开），std 热路径吃一次 `Option` 分配。要先量 `str.trim`
   的代价，别凭感觉。
3. **selfhost 的翻转推迟到 v0.56.0**。看着像「再分一期」，实际不成立：`s.cps[i] == '\n'`
   在 `code_points` 改签名的那一刻两边类型就对不上，而 `code_points` 是 selfhost 取码点的
   唯一入口。半翻转的 selfhost 编不过——这正是 7.2 说的那个「说不出 `'a'` 是什么类型」的
   中间状态，只是搬到了别的名字上。

> 顺带记两个期 2 施工前该先量的数：`'x'` 字面量 675 处（std 61 / selfhost 341 /
> packages 164 / site 101 / scripts 8，另 backend-dawn 19），`code_points` 调用点 34 个
> 文件——但真正的工作量不是字面量，是 `List[Int] → List[Char]` 沿 lexer / json / md /
> site 的类型传播，以及每一处对码点做算术的地方（opaque 在 owner 之外不能算术）。

### 7.7 裁决：出路 1 也够不着种子，桥要提前一版进 std

7.6 的三条出路里，出路 1（新增 `char_of` 内建）看着最干净，**它编不过**。
原因和 7.5 第 2 条是同一条，只是那里没推到底：

> `bin/dawn` 的 stage 1 = **种子的编译器** 编今天的 `selfhost/src`，`--std` 指的是
> **种子那一版发布时的 std**（`scripts/seedjar.sh` 的 `seed_std_dir`，从种子的 git tag 里
> `git archive std` 取）。

于是 selfhost 能用的东西，必须**在上一个 release 的产物里就存在**。这对新内建和新 std 模块
一视同仁——内建表 `builtins()` 是编译进种子 jar 的一段代码，不是读今天的 `types.dawn`。

**实测（不是推理）**，v0.55.0 种子 + 今天的 selfhost：

| 变异 | 结果 |
|---|---|
| `types.dawn` 加 `bsig("char_unchecked", ...)`，`lexer.dawn` 调它 | stage 1 红：`error: undefined function: char_unchecked --> selfhost/src/lexer.dawn` |
| `ls .dawn/seeds/std-v0.55.0/` | 11 个模块，**没有 `char.dawn`** |

两行合起来：**期 2 那一版的 selfhost，既调不到新内建，也 `use` 不了新 std 模块。**
出路 1 与出路 2 都假设了「新内建当版可用」，两条一起失效；出路 3（推迟 selfhost）
7.6 已自证不成立。

**出路 4：把桥所在的 std 模块提前一版发出去。** 也就是 7.2 表里新加的期 1.5：

- **v0.56.0**：`Char` 仍然透明，`'a'` 仍然是 `Int`，只多一个 `std/char` 模块
  （`code` / `of` / 六个 `is_*`）。此版里 `code(c: Char) -> Int` 是恒等、
  `of(n) -> Option[Char]` 是一次范围判断，**没有任何现存程序能看出区别**——
  这正是 7.2 给类型名用过的那条论证，原样用在模块上。
- **v0.57.0**：原子翻转。selfhost `use std/char`，`char.code` 供
  `Token.ival` 那一处 Char→Int、`char.of(cp)` 供 `lex_unicode` 那一处 Int→Char
  （顺带把 `\u{...}` 的校验收紧到「代理区也拒」，那是 7.6 说的「比现在更严」）。

**为什么桥是 std 模块而不是内建**：7.5 当初推出内建，是因为它数的三条约束里
第 2 条把 `std/char` 排除了——而排除的理由是「v0.55.0 的 std 里没有 char 模块」。
那不是模块这条路走不通，那是**它没被提前发**。发了就通，且回到 7.1 原本要的形状：
`char.code` / `char.of` 是 owner 模块里的两行普通函数，零内建、零 lowering、
两个后端都不用改。

**仍然要一个 internal 内建**：7.5 第 3 条（`std/str.trim` 走 `cursor.char` 拿 `Int`，
要喂给收 `Char` 的 `char_is_space`）不受影响——**std 由今天的编译器在 stage 2 检查**，
所以 `char_unchecked` 与翻转同版引入即可用。只有 `selfhost/src` 受种子约束，std 不受。

> 一句话记住这条：**种子纪律管的不只是语法，还有名字**——语言特性、内建名、std 模块名，
> 凡是 `selfhost/src` 要拼出来的，都得在上一版的产物里能被解析。
