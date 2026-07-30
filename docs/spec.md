# Dawn 语言规范

> 状态：**normative（权威）**。适用版本：0.11.0（`selfhost/src/version.dawn` 的 `VERSION`）。
> 实现与本文冲突时，以本文为准并把实现当 bug——除非本文某条被显式标注为「已被 X 取代」。
>
> 标题曾长期写「v0.1 草案」，而工具链已到 0.11：一份自称草案的文档没法充当裁判，
> 而这是仓库里唯一有资格裁判语义争议的文档。版本号跟 `VERSION` 走，不再单独编号。

本文是语法与语义的权威定义。设计动机见 [design.md](design.md)，
机器可读语法见 [grammar.ebnf](grammar.ebnf)。

规范用词：**必须**（违反即编译错误）、**保证**（实现承诺的行为）、
**未定义**（v0.1 不承诺，勿依赖）。

---

## 1. 源文件与词法

### 1.1 源文件

- 编码 UTF-8，扩展名 `.dawn`。
- 一个文件即一个模块（见 §11）。

### 1.2 注释

```dawn
# 行注释，到行尾
## 文档注释，附着于紧随其后的声明（工具链提取）
```

### 1.3 标识符与命名约定

**强制的部分**——首字符决定语法类别，parser 靠它消歧（模式匹配中 `x` 是绑定、
`X` 是构造器；`TYPEIDENT` 是独立 token）：

- 值、函数、模块名：**首字符是小写字母或 `_`**
- 类型与构造器：**首字符是大写字母**
- 效果变量：`!` 后接一个值标识符（`io` 为保留效果名）

**风格约定**——工具链不强制，但全仓遵守：值用 `lower_snake_case`
（`[a-z][a-z0-9_]*`），类型用 `UpperCamelCase`（`[A-Z][A-Za-z0-9]*`）。

> **关于非 ASCII**：「大写 / 小写」按 Java 的 `Character.isUpperCase`
> 判定，后续字符按 `Character.isLetterOrDigit` 或 `_`。于是 `fn 中文()`、
> `fn _hidden()` 都能编译——汉字既非大写也非小写，走「不是大写」这一支，即值标识符。
>
> 这是**实现定义**的，不是设计过的：Unicode 的 XID_Start/XID_Continue、
> normalization（`é` 的两种写法算不算同一个名字）、同形字符，本规范**全部未定义**，
> 依赖它们的代码不可移植。无大小写文字（汉字、阿拉伯文、假名）因此只能作值名，
> 作类型名没有自然写法。收敛到明确定义的 Unicode 标识符语法是一项未决工作
> （docs/codebase-audit.md 的 SYN-01）。

### 1.4 关键字

```
fn let var type alias const use java pub
match if else for in while
comptime unsafe_pure test assert
trait impl
true false not
```

关键字不可用作标识符。`panic`、`todo` 是预置函数而非关键字；`derive` 是
上下文关键字（只出现在 `type` 声明尾部）。

### 1.5 字面量

| 形式 | 类型 | 说明 |
|------|------|------|
| `42`, `1_000_000`, `0xFF`, `0b1010` | `Int` | 64 位有符号；下划线可作分隔 |
| `3.14`, `1.0e-9` | `Float` | IEEE 754 double |
| `true` / `false` | `Bool` | |
| `"hello"` | `String` | 见 §1.6 |
| `()` | `Unit` | 唯一值 |
| `[1, 2, 3]` | `List[Int]` | 允许尾逗号 |
| `(1, "a")` | `(Int, String)` | 元组，2 至 8 元 |
| `'a'`, `'\n'`, `'世'`, `'\u{1F600}'` | `Int` | 字符字面量 = **码点**（见下） |

**字符字面量走 Go 的 rune 路线**：`'x'` 不是独立类型，而是等于该字符**码点**的 `Int`
字面量（`'a' == 97`）。因此 match 里它就是普通 `Int` 模式，类型系统零改动。单引号内是
单个码点：转义与字符串相同（`\n \t \r \\ \u{...}`）另加 `\'`；空字面量或含多个码点 → 词法错误。
按码点处理字符串的函数见 §11（`code_points`/`from_code_points`/`str.len`/`str.substring`）。
**注意**：运行期存储是 `java.lang.String`（UTF-16 码元下标），故「按码点下标随机访问」需要
O(n) 换算——实测与设计取舍见 [`seq6-research.md`](seq6-research.md) 附录。**逐字符遍历请用
§11 的游标（`std/cursor`）**，它每步恒定开销；下标版留给单次调用。
没有独立字符类型（Go/Rune 模型使其无必要）。

### 1.6 字符串与插值

双引号字符串，支持转义 `\n \t \r \\ \" \$` 与 Unicode `\u{1F600}`。
**花括号 `{` `}` 是普通字符，无需转义**——写 JSON、CSS、代码生成很方便。

插值由 `$` 引导（同 Kotlin/Swift）：`$name` 插入一个简单标识符，`${expr}` 插入
任意表达式；被插值的类型必须有 `Show` 见证——预置标量、写了 `impl Show` 或
`derive Show` 的用户类型、以及元素可渲染的容器与元组（见 §4.3）：

```dawn
let n = 3
println("got $n items, first = ${list.get(0)}")
```

`$` 后不接标识符或 `{` 时就是字面美元号（`"$5"` 无需转义）；要强制字面 `$` 用 `\$`。
插值内的表达式效果并入整个字符串表达式的效果。

多行字符串用三引号 `"""`，首尾换行与公共缩进被剥除；插值规则相同。

**raw string 用反引号**：`` `...` `` 之间的一切都是字面量——无转义、无插值、
可跨行、不剥缩进，所见即值。唯一限制是内容里不能出现反引号本身（也没有逃生舱，
要写反引号就用普通字符串）。三种形式死角互补：含反引号 → `"..."`；
要插值的模板 → `"""`；含引号与 `$` 的原样文本（正则、代码样本、HTML）→ 反引号。

### 1.7 换行与分号

语句由**换行**分隔，没有分号——写了 `;` 会被专门诊断（提示删掉它），并当作换行恢复，
不至于把后文全带崩。行尾是二元运算符、`|>`、逗号、开括号时自动续行；
此外 `|>`、`.` 与**二元运算符**都允许出现在**下一行行首**（竖排管道 / 竖排方法链 /
竖排布尔或算术，惯用写法——Java builder 链 `x\n  .uri(u)!\n  .build()!` 可断行，
长条件 `a\n  && b\n  && c` 也可断行）。**唯一例外是 `+` 与 `-`**：行首 `-` 与一元负号
有歧义（`x\n  - y` 究竟是 `x - y` 还是新语句 `-y`？无法判），故这对算术运算符不作行首续行。
惯例上一行一条语句；`dawn fmt` 负责统一。

### 1.8 `dawn fmt`

`dawn fmt <文件>...` 就地格式化；`dawn fmt --check <文件>...` 只报告未格式化的文件
（有则退出码 1，供 CI）。实现是**基于 token 流的重排器**：逐 token 按原样重印
（字符串与插值按源码区间原样保留，一字不改），只改动 token 间的空白——行内间距、
2 空格缩进、折叠连续空行（保留作者的物理换行）。故格式化**保 token、保注释、幂等**，
且只需词法成功（不需能解析），语法错误的文件也能格式化。要点：缩进 2 空格；
二元运算符/`->`/`=>`/`=`/`|>` 两侧各 1 空格；`,`/`:` 后 1 前 0；`(`/`[` 内侧贴紧；
`.`/`?` 贴紧；不折超长行（作者断的行保留）。

---

## 2. 类型

### 2.1 基础类型

`Int`（64 位）、`Float`（double）、`Bool`、`String`、`Unit`。

`Unit` 是一等值（唯一值 `()`），**可出现在任何值能出现的位置**：形参、局部变量、
闭包捕获、元组元素、返回值，以及实例化类型参数（`Result[Unit, E]`、`List[Unit]`、
`catch_fault(fn() => <void 调用>)`）。运行期它有真实表示——一个单例对象
（`dawn/rt/Unit`，与 `None` 及无字段构造子同一表示），占一个引用槽位，
C 后端给它一个字节。

只有两条例外，都不是表示上的限制：

- **构造子字段不能是 `Unit`**——没有载荷的分支写成裸构造子就是了，这是建模的说法。
- **`Eq`/`Hash`/`Show` 对 `Unit` 无实现**——只有一个值，答案会是常量。

**没有 null。** 所有类型的值都必然有效；可缺失用 `Option[T]` 表达。
**没有隐式转换。** `Int` → `Float` 必须显式 `to_float(n)`。

### 2.2 内建复合类型

- `List[T]` — 不可变持久列表。实现是**32 叉 trie + 尾块的持久向量**（`std/pvec`，纯 Dawn 源，
  建在 `Array` 原语之上）：索引 O(log32 n)——长度 ≤32 时全在尾块、即一次数组读；
  `++` 逐元素追加，尾块未满时只复制尾块（≤32 槽），每 32 次把尾块压进 trie、复制一条
  根到叶的路径，故 `acc = acc ++ [x]` 的累积循环是**线性的、O(1) 摊还**。
  结构共享，已发布的列表永不改变；追加到旧版本不复制整表，只复制它自己的那一小块。
- `Option[T]` — `Some(T) | None`
- `Result[T, E]` — `Ok(T) | Err(E)`
- `Map[K, V]` — 不可变映射（见下）
- `Set[T]` — 不可变集合（见下）
- 元组 `(A, B, ...)`
- 函数类型 `fn(A, B) -> C !e`（`!e` 可省略，表示纯）

`Option` 与 `Result` 就是普通 ADT，在标准库中定义，无特殊地位
（`?` 运算符对它们有语法支持，见 §8.1）。

**`Map[K, V]` / `Set[T]`** 是与 `List` 同级的内建持久容器，无字面量语法，全部经
内建函数操作（清单见 §11）。语义要点：

- **持久（不可变）接口**：`map.insert`/`map.remove` 返回新映射，原值不变。
- **键类型 = 有 `Hash` 的类型**，没有第二条规则。每个会摸到键的操作（`map.insert`/
  `map.get`/`map.has`/`map.remove`/`m[k]` 与 `set` 的同名者）都带 `[K: Eq + Hash]`
  bound，键合法性就是这条 bound 解得开——`Int`/`String`/`Bool`/`Bytes`、元组、ADT、
  record 都可以（没写 impl 的按自身结构合成一份，§4.3），`Float` 不行（NaN/`-0.0`
  给了它两套相等，§4.3 因此没给它 `Hash`），`Array` 不行（按同一性持有，非按内容）。
  报错落在**用到键的那个操作**上，不在类型标注上：`Map[Float, Int]` 这个类型本身
  拼得出来，只是没有任何操作能往里放键。
  > 2026-07-27 之前另有一条独立的结构行走（`invalid_key_part`）走在类型标注与泛型
  > 实例化点上。它与 bound 平行且**打架**：它禁 `Bytes`（理由「哈希是引用同一性」，
  > 而 `Bytes` 早已改成内容哈希），而 bound 放行；它只在键位置拦 `Float`，
  > 于是 `hash(1.5)` 在键位置之外照样能过。删掉的是那条行走，不是规则。
- **迭代顺序 = 插入顺序**，确定且 JVM/native 一致（`map.keys`/`map.entries`/`set.to_list`
  按插入序）。`map.insert` 遇已存在的键**替换值、保留原插入位置**。
- **相等与顺序无关**：两个键值对相同的 `Map` 相等，无论插入次序。
- 实现是**持久 HAMT**（`std/hamt`，纯 Dawn 源，建在 `Array` 原语之上）：`map.insert`/`map.remove`
  O(log32 n)，只复制根到叶的路径，其余结构与原映射共享（插入序由逐键序号维持）。
  键的相等与哈希取自键类型的 `Eq`/`Hash`（以字典传入），不是宿主的对象同一性。

### 2.3 和类型（ADT）

```dawn
type Shape =
  | Circle(r: Float)
  | Rect(w: Float, h: Float)
  | Point                       # 无载荷构造器
```

- 构造器字段**必须**带名字；构造调用可按位置或按名：`Rect(2.0, h: 3.0)`。
- 构造器（含字段的）裸名在函数位置是**普通函数值**：`map(xs, Some)` 等价于
  `map(xs, fn(x) => Some(x))`。类型参数从期望的函数类型推导（`Some` 的元素类型来自
  上下文）；仅由字段无法确定的类型参数（如 `Ok` 的错误类型 `E`）需上下文补足，
  否则报「无法推导类型参数」。无载荷构造器（`Point`）本身是值不是函数；记录构造用
  花括号语法，不参与此规则。
- 泛型：`type Tree[T] = | Leaf | Node(left: Tree[T], value: T, right: Tree[T])`

### 2.4 记录（record）

```dawn
type Point = { x: Float, y: Float }

let p = Point { x: 1.0, y: 2.0 }
let q = Point { ..p, x: 3.0 }     # 函数式更新
let d = p.x                        # 字段访问
```

记录是单构造器积类型的糖，同样支持模式匹配。字段不可变——"修改"即函数式更新。

**fn 类型的字段可以直接调用**：`r.f(x)` 调用字段里存的函数值，等价于
`let g = r.f` 后 `g(x)`；字段的效果照常并入调用方。作用域里**同时存在**
名为 `f` 的函数时，`r.f(x)` 是**编译错误**（歧义）——静默优先级会让远处新增
一个同名函数悄悄改变既有调用的含义（§10.3 对模块别名同名早已拒绝同类歧义，
此处同规）。消歧：取字段先绑定 `let g = r.f`；调函数写直呼 `f(r, x)`。

### 2.5 泛型

- 类型参数用 `[T, U]` 声明在名字后：`fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e`
- 单态性：类型参数在每个调用点必须能完全推导，不支持高阶类型（HKT）。
- 实现为擦除 + 装箱（v0.1）；单态化留作后续优化，不影响语义。
- **没有子类型、没有继承、没有变型（variance）**。类型要么相等要么不同。
- 函数体内的局部标注可以引用签名的类型参数（`let acc: List[T] = []`）——
  刚性类型参数在推断里视同已知的具体类型。

### 2.6 类型别名

```dawn
alias Meters = Float                                  # 内建标量
alias Pair = (Int, String)                            # 元组
alias Names = List[String]                            # 泛型应用
alias Handler = fn(Request) -> Result[Response, HttpError] !io   # 函数类型
alias Lookup[T] = fn(String) -> Option[T]             # 可带类型参数
alias Paint = Color                                   # 用户类型（ADT/record）也可别名
```

别名有**自己的关键字 `alias`**；`type` 只声明**名义类型**（ADT 或 record）。
别名是**透明**的（不是 newtype）：解析期展开，与被指的类型完全互换。

> **`alias Meters = Float` 不提供任何单位安全。** 它与 `Float` 完全互换：
> `Meters` 和 `Seconds` 可以相加，函数收 `Meters` 时传裸 `Float` 也照过。
> 上面第一行只是「别名可以指内建标量」的语法示例，别把它读成领域建模的推荐做法——
> 单位类型是 alias **最容易误导**的用法。别名的真实价值在下面几行：给长类型起短名
> （`Handler`、`Lookup[T]`）。
>
> 想要单位安全，用的是**下一节的 `opaque type`**：`pub opaque type Meters = Float`
> 在模块外与 `Float`、与 `Seconds` 都不互换，出入写两个一行函数（§2.7）。
> 这句曾写着「Dawn 目前没有」——那是 §2.7 落地前的话，忘了回来改（LANG-05 的病根
> 正是示例与指路不同步，这句自己也犯了一次）。

> 历史注记：两者曾共用 `type`，靠「右侧形状」启发式区分——同形不同义，且用户类型
> 无法被别名（裸大写名恒被读作构造器）。现在 `type X = <fn 类型/元组/Name[...]/内建标量>`
> 是编译错误，hint 指向 `alias`；`type Color = Red` 维持 ADT 语义不变。

限制：别名不可递归（环报错）；不可携带效果变量（只能 `!io` 或纯）；
`pub` 后可跨模块导入（`use m.{Handler}`）。

### 2.7 不透明类型

```dawn
pub opaque type UserId = Int                # 只有本模块知道它是 Int
pub opaque type Env = Map[String, Int]
pub opaque type Pair[T] = (T, T)            # 可带类型参数
```

`opaque type N[..] = T` 与 `alias` 的语法一样，差别只有一条：**谁被允许看穿它**。
声明它的模块里，`N` 与 `T` 可以互相转换；模块之外，两者是不同的类型。

```dawn
# 在 ids 模块内
pub fn wrap(n: Int) -> UserId = n           # ✅ 本模块可转换
pub fn unwrap(u: UserId) -> Int = u         # ✅

# 在别的模块
let bad: Int = wrap(7)                      # ❌ annotated type is Int but the
                                            #    initializer is UserId
```

**转换发生在赋值、传参与返回位置**（即类型可赋值性判定处），不在表达式内部：
本模块里 `u + 1` 仍是错的，写 `let n: Int = u` 再算，结果回到 `UserId` 位置时自动转回。
这是 newtype 的纪律，也让「不透明」在实现上只是一条判定，而不是散落各处的特判。

**不透明只挡视线，不改语义**：运行期一个不透明类型**就是**它的目标类型——同样的表示、
同样的相等、哈希、序与渲染，两个后端都如此，零开销。`opaque` 是软关键字，
只有 `opaque type` 有意义。

> **给实现者的判据（别名替换法）**：把 `opaque type N = T` 原地换成 `alias N = T`，
> 若某个函数的答案变了，它要么是下面四件事之一，要么就是 bug。**只有四件事**允许看见
> `TyOpaque`：可赋值性判定（谁能转换）、impl 选择（`head_of`/`impl_at`）、
> 符号命名（`ty_key`/`dict_key`/impl 方法名）、以及诊断里的类型名。
> 其余每一个吃 `Ty` 的函数——宽度、描述符、槽位、装箱、哪条指令、能不能当常量、
> 某个 trait 有没有答案——都取目标的答案。
> 次序也是定的：**先问身份再问表示**，`impl Eq[UserId]` 必须先于「按 Int 比较」，
> 否则声明它就没意义了。
> 机器化在 `scripts/opaque-twin/`：每个语料跑两遍，一遍原样一遍换成 `alias`，
> 输出必须一致（编译错误也算输出）。2026-07-27 用手工做这件事一次抓出 12 处。

可以给不透明类型写自己的 impl（`impl Show[UserId]`），它优先于目标类型的；孤儿规则把
不透明类型算作声明模块的本地类型。

> 为什么需要它：在此之前，每要隐藏一次表示就得现搓一套机制——`Cursor` 是编译器铸造的
> 不透明标量，集合纯 Dawn 化的 HAMT 节点会是下一个。这是第三次之前把机制立出来。
>
> `Cursor` 已经迁完（§11）：编译器那一套删干净，由 `std/cursor` 用本节的机制重新
> 立起来，是这个特性的第一个真实用户。
>
> **`Array` 不是同类**——这里原先写着它「随集合纯 Dawn 化一并迁」，实测是错的：
> 本机制要一个**目标类型**，而 `Array` 没有目标，它**就是**表示；且两者方向相反，
> 本机制公开名字、隐藏表示，`Array` 的 `is_std_module` 门控隐藏名字、对 std 公开表示。
> 那道门控留着，理由见 [`trait-v2-design.md`](trait-v2-design.md) §8.3。

---

## 3. 声明

模块顶层只允许：`use`、`type`（含 `opaque type`）、`alias`、`const`、`fn`、`test`、`trait`、`impl`。
没有顶层可变状态。

### 3.1 函数

```dawn
fn add(a: Int, b: Int) -> Int = a + b

fn greet(name: String) -> Unit !io = {
  println("hi, $name")
}
```

- **参数类型必须写全**（所有函数）；`pub fn` 还必须写返回类型——公开签名是 API 契约。
- **私有函数可以省略返回类型**：`fn double(x: Int) = x * 2`。省略时返回类型与效果
  都从函数体推导（想强制效果仍可写 `!io`）。三类函数**必须**标注返回类型：
  ① `pub`；② 递归/互递归（编译器按调用图拓扑序推导，环上无法推导）；
  ③ 体内用了 `return` 或 `?`（二者需要已知的返回类型）。
- 写了 `-> T` 的函数维持原规则：效果省略即纯，**体内出现 io 而签名未标则报错**——签名是承诺。
- 函数体是 `=` 后的单个表达式；块 `{ }` 也是表达式（§4.2）。
- 没有默认参数、没有变长参数、没有重载。

**局部命名函数**：块内可写 `fn name(params) -> T [!io] = body` 语句——本质是
「名字在自身 body 内可见的 lambda」，因此**可递归**（自尾调用编译为循环，§12.4）、
可捕获外围绑定（按值，同 lambda 规则）、可当值传递。参数类型与返回类型必须写全；
效果只能是 `!io` 或纯（效果多态请提升到顶层）；不可声明类型参数（外围函数的类型参数天然在作用域内）。

```dawn
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}
```

### 3.2 常量

```dawn
const MAX_DEPTH: Int = 64
const SIN_TABLE: List[Float] = comptime {
  range(0, 360) |> map(fn(d) => sin(to_radians(d)))
}
```

顶层 `const` 的右侧隐式处于 comptime 上下文（§7），必须是纯的、可常量化的。

### 3.3 可见性

所有声明默认模块私有；`pub` 导出。`pub` 可用于 `fn`、`type`、`alias`、`const`。
`pub type` 同时导出其构造器与字段。

### 3.4 测试块

```dawn
test "precedence" {
  assert eval("2+3*4") == Ok(14)
}
```

- `test` 块只被 `dawn test` 编译执行，`dawn build` 剥除。
- 块内允许 `!io`。
- `assert expr`：`expr` 为 `Bool`；失败时报告源文本与两侧子表达式的值
  （编译器对 `==`、比较运算符做拆解以给出好的失败信息）。

### 3.5 trait 与 impl

单参数、名义式的 typeclass，字典传递实现（完整设计与判定规则见
[trait.md](trait.md)）：

```dawn
trait Ord2[T] {
  fn cmp2(a: T, b: T) -> Int
  fn max_of(a: T, b: T) -> T = if cmp2(a, b) >= 0 { a } else { b }  # 默认体
}

impl Ord2[Point] {
  fn cmp2(a: Point, b: Point) -> Int = a.x - b.x
}

fn sort2[T: Ord2](xs: List[T]) -> List[T] = ...   # 约束：[T: Trait (+ Trait)*]
```

- trait 恰有一个类型参数；方法进入模块函数命名空间（可直呼、可 UFCS、可管道）。
- **预置 trait 四个**：`Ord`（`cmp`，背后是 `<`/`<=` 之外的排序）、`Eq`（`eq`，
  背后是 `==`/`!=`）、`Hash`（`hash`）、`Show`（`show`，背后是 `to_string` 与
  `${...}`）。标量的 impl 随语言提供；`derive Ord` / `derive Show` 铸的是普通
  impl，泛型类型上铸的是条件 impl。元组没有 head，写不出 impl，四者对元组由
  编译器按结构合成。
- **一致性**：全程序每个「trait × 类型」至多一个 impl；**孤儿规则**：impl 只能
  写在 trait 或主体类型的声明模块。impl 全局生效，不需要 `use`。
- **主体形状**：一个类型构造器，作用在**互不相同的类型变量**上，而那些变量恰好是
  这个 impl 自己的参数——`impl Eq[Money]`、`impl[T: Eq] Eq[List[T]]`、
  `impl[K: Eq, V: Eq] Eq[Map[K, V]]` 都合法；`impl Eq[List[Int]]`（具体实参）与
  `impl[T] Eq[Map[T, T]]`（重复变量）不合法。这一条同时决定了「哪个 impl 匹配」
  （head 相等）、「两个 impl 是否重叠」（同上）与「递归求解是否终止」（子目标是
  父目标的真子项）。
- **条件 impl**：`impl[T: Eq] Eq[List[T]]` 的方法是泛型函数，按约束接收字典；
  `Eq[List[Int]]` 这样的具体目标在编译期解成常量字典，`Eq[List[T]]`（`T` 刚性）
  则在运行期由 `Eq[T]` 构造。无 dyn、无 supertrait、无特化（不问「哪个更特化」）。
  trait 方法效果只能是纯或 `!io`，impl 的效果 ⊑ trait 声明。
- 预置 `trait Ord[T] { fn cmp(a: T, b: T) -> Int }` 及 `Int`/`Float`/`String`
  的 impl；`derive Ord` 生成字段字典序比较（和类型先比构造器声明顺序），字段须为
  `Int`/`Float`/`String`、自身具 Ord impl 的类型，或该类型自己的类型参数
  （此时生成的是条件 impl：`type Box[T] = { v: T } derive Ord` 得到
  `impl[T: Ord] Ord[Box[T]]`）。`List[T]` 有 std 写的词典序 impl。
- 预置 `trait Eq[T] { fn eq(a: T, b: T) -> Bool }` 与
  `trait Hash[T] { fn hash(x: T) -> Int }`，`Int`/`Float`/`Bool`/`String`/`Bytes`
  各有 impl。**没有 `derive Eq`**：`==` 本来就对每个类型结构化（§4.3），等于每个类型
  隐式实现 Eq；写 impl 是为了**覆盖**它。
  - 覆盖后 `==` 即该 impl，容器与嵌套比较一并跟随。
  - **`impl Eq` 与 `impl Hash` 必须成对出现**（编译错误）：相等的值必须哈希相同，
    否则该类型作 `Map`/`Set` 键即失效。
  - 覆盖体内不能用 `==` 比较主体类型本身——那就是这个 impl，会无限递归；比字段。
  - `Eq`/`Hash` 约束实例化到**没有 impl 的类型**（ADT、元组）时，编译器按这个类型
    自己的结构**合成**一份实现——等价于一条隐式的条件 impl，主体含类型参数时要求
    该参数有对应 bound。主体静态已知时直接塌缩成原语，不建字典。
  - 合成的哈希是**可观测的数**（`hash(x)` 可以打印），故定义在此：种子 `1`，
    逐部分 `h = 31*h + hash(part)`，32 位环绕算术；元组按元素序，构造器按字段序，
    **有一个以上构造器时构造器序号作为第一个部分先折进去**（一个构造器时没有可分辨的
    标签，与 `==`/`cmp` 同一条规则）。
  - `List` 不在此列：std 写了 `impl[T: Eq] Eq[List[T]]` 与对应的 `Hash`/`Ord`。
    `Map`/`Set`/元组仍走合成。
- 限制：trait 方法与带约束的函数不可用作函数值（提示包 lambda）；comptime 中
  不允许 trait 约束的调用与 impl 排序。

---

## 4. 表达式

Dawn 是表达式导向的：`if`、`match`、块都产生值。

### 4.1 绑定

```dawn
let x = 42              # 不可变绑定，类型推导
let y: Float = 1.0      # 可选标注
var acc = 0             # 可变局部变量
acc = acc + 1           # 赋值，仅对 var 合法
```

- `let` 不可变、不可遮蔽（同一作用域重复绑定同名是错误；嵌套作用域允许遮蔽）。
- `var` 仅限函数体内的局部变量；record 字段、参数、顶层均不可变。
- 赋值是语句（类型 `Unit`），不是表达式——`if (x = 1)` 这类错误不存在。

### 4.2 块

```dawn
let area = {
  let w = 3.0
  let h = 4.0
  w * h                  # 最后一个表达式是块的值
}
```

块引入新作用域；最后一个表达式是块的值，其余语句必须是 `Unit` 类型
（防止悄悄丢弃 `Result`——丢弃非 Unit 值必须显式 `let _ = ...`）。

### 4.3 运算符与优先级

自低到高：

| 优先级 | 运算符 | 结合性 | 说明 |
|--------|--------|--------|------|
| 1 | `\|>` | 左 | 管道，见 §4.4 |
| 2 | `\|\|` | 左 | 逻辑或，短路 |
| 3 | `&&` | 左 | 逻辑与，短路 |
| 4 | `== != < <= > >=` | 不结合 | 比较；链式比较是语法错误 |
| 5 | `\|` | 左 | 按位或；仅 `Int` |
| 6 | `^` | 左 | 按位异或；仅 `Int` |
| 7 | `&` | 左 | 按位与；仅 `Int` |
| 8 | `<< >> >>>` | 左 | 移位；仅 `Int`。`>>` 算术（补符号）、`>>>` 逻辑（补零） |
| 9 | `++` | 右 | `String`/`List` 连接 |
| 10 | `+ -` | 左 | 仅数值，两侧同类型 |
| 11 | `* / %` | 左 | 仅数值；`Int` 除零 panic |
| 12 | `not`、一元 `-`、`~` | 前缀 | `~` 仅 `Int` 按位取反 |
| 13 | `? . () []调用` | 后缀 | `?` 见 §8.1；`()` 自 2026-07-30 起是**一般后缀**（见下） |

- **调用是一般后缀（SYN-02）**：任何后缀表达式后同一行紧跟 `(` 即为应用——
  `make()(1)`、`(if c { f } else { g })(1)`、`get_handler()(req)` 都合法，参数为位置参数
  （函数类型不携带参数名）。**跨行的 `(` 不吃**：换行结束后缀链（只有 `.` 可跨行续链，§1.7），
  故 `let x = f` 换行 `(1 + 2)` 仍是两条语句——与一元 `-` 不续行同一条纪律。
  具名头（`f(x)`、构造器、`x.m(y)`）仍按各自规则解析；构造器仍是唯一接受具名实参的位置。
- 按位 `& ^ \|` 与移位**仅作用于 `Int`**（无 `Float` 位模式）；它们**紧于比较**，
  故 `a & b == c` 是 `(a & b) == c`，无 C 家族那个坑。移位计数取低 6 位（同 JVM `LSHL`）。

**数值边缘语义**（全部为**保证**——自举后两套实现以此对拍，不允许「碰巧一致」）：

- `Int` 溢出**环绕**（二补码，同 JVM）：`MAX + 1 == MIN`。唯一可能溢出的除法
  `MIN / -1` 同样环绕（结果 `MIN`），`MIN % -1 == 0`。
- `/` **向零取整**（`-7 / 2 == -3`，不是 floor）；`%` 的**符号随被除数**
  （`-7 % 2 == -1`、`7 % -2 == 1`），恒满足 `a == (a / b) * b + a % b`。
- `/` 与 `%` 除零是 **panic**（消息 `Int division by zero` / `Int modulo by zero`）——
  panic 而非 Java 异常，故 `catch_fault` 不拦、只有 `catch_panic` 拦（§9.8）。
- `Float` 算术遵循 IEEE 754：除零不 panic（得 `±Inf`/`NaN`）；`==` 与 `< <= > >=`
  是 IEEE 比较——NaN 与任何值（含自身）比较均为 false，`-0.0 == 0.0` 为 true。
- **`Float` 没有 `Ord`**（2026-07-26 改；此前照 Java `Double.compare` 给了一个
  全序）。NaN 与任何值（含自身）都不可比，所以 Float 上没有全序可给，而
  `Ord` 正是 `sort`/`max`/`min`/`max_by`/`min_by`/`derive Ord` 与 `[T: Ord]`
  所依赖的东西。「降成偏序」在 Dawn 里是**少一条 impl**，不是多一个 trait：
  `<`/`<=`/`>`/`>=` 对标量本就不解见证，照旧可用、照旧是 IEEE 语义。
  变的只有一条：`[T: Ord]` 不再收 Float，`cmp(1.5, 2.5)` 不再编译。
  （Rust 的 `total_cmp` 是 `f64` 的固有方法，`f64` 同样没有 `Ord` impl。）
- **`Float` 没有 `Hash`**，因此不能作 Map/Set 的键：`-0.0 == 0.0` 为真而两者
  位模式不同，没有哈希能同时与这个相等和自身一致（同 Rust）。
- **`Float` 有 `Eq`，而它不自反**（`nan == nan` 为 false）。这是 IEEE 的事实，
  不是漏洞，Dawn **不**为此拆出 `PartialEq`/`Eq` 两个 trait（2026-07-26 明确
  裁定不拆）：Dawn 只有一个 `Eq`，拆开会让 `1.5 == 2.5` 这种日常写法多背一层
  概念，代价远大于收益。用到自反性的地方（容器查找）另有 Float 不能作键这条挡着。
- `Float` 的 `to_string`/`Show` 渲染 = JVM `Double.toString`（最短往返表示，
  `NaN`/`Infinity`/`-Infinity` 照字面）。
- **`to_int(x)` 向零截断且饱和**（同 JVM `D2L`）：`to_int(2.7) == 2`、
  `to_int(-2.7) == -2`；`NaN` 得 `0`，超出 `Int` 范围的（含 `±Inf`）得**较近的那一端**
  （`to_int(1.0 / 0.0) == Int` 的最大值）。写下来是因为 C 的强转对这三种输入全是未定义、
  且在 x86-64 上三者都答 `Int` 的最小值——2026-07-30 之前 native 就是这么答的。

- `==`/`!=` 默认是结构相等，对任意类型可用（函数类型除外——比较函数是编译错误）；
  类型可用 `impl Eq` 覆盖这个默认（§3.5）。
- 排序比较 `< <=` 等：`Int`/`Float`/`String` 原生有序；其他类型桥接到预置
  trait `Ord` 的 `cmp`（见 §3.5）——有 impl（手写或 `derive Ord`）即可比较，
  受 `[T: Ord]` 约束的类型参数同理。
- 用户类型的打印：`type` 声明后加 `derive Show` 获得 `to_string` 与字符串插值支持
  （可 derive 的还有 `Ord`，见 §3.5；多个用逗号：`derive Show, Ord`）。
  `Show` 是**预置 trait**，`derive Show` 铸的就是一条 impl，所以也可以手写
  `impl Show[T] { fn show(x: T) -> String }` 自定义渲染，泛型类型则用条件 impl
  （`impl[T: Show] Show[Box[T]]`）。`to_string` 的签名是 `[T: Show]`。
  渲染形如合法 Dawn 源码：
  - 无载荷构造器 → `Red`；带位置字段的构造器 → `Circle(1.5)`；
  - 记录 → `Point { x: 0.0, y: 2.5 }`（带字段名）；
  - `String` 字段带双引号并转义（`"a\nb"`）；`Int`/`Float`/`Bool` 同各自 `to_string`；
  - 容器递归渲染：`List` → `[a, b]`、元组 → `(a, b)`、`Option`/`Result` 随载荷（`Some(Red)`）。
  - 每个字段类型必须可打印（函数字段、未 `derive Show` 的嵌套用户类型 → 声明处报错）；
    泛型类型可打印 **当且仅当** 其类型实参都可打印（`Box[Int]` 可，`Box[fn(...)→...]` 不可）——
    `derive Show` 在泛型类型上铸的是 `impl[T: Show] Show[Box[T]]`，这条就是它的 bound。
  - **顶层的 `String` 不加引号，嵌套的加。** `to_string("a")` 是 `a`，而
    `["a"]` 是 `["a"]`——引号是「这里是一个值，不是周围的标点」的记号。
    trait 方法 `show` 是**嵌套**那一份，所以经 `[T: Show]` 约束渲染一个字符串
    会带引号；`to_string`/`${}` 只在**静态类型就是 `String`** 时去掉它。
    一个 trait 兼二职，这条线就是它的位置（Rust 拆成 Display 与 Debug）。

### 4.4 管道

`x |> f(a, b)` 等价于 `f(x, a, b)`——把左侧塞进**第一个参数**。
`x |> f` 等价于 `f(x)`。标准库 API 均按"主数据是第一参"设计以配合管道。

### 4.5 Lambda

```dawn
let double = fn(x: Int) => x * 2
let add = fn(a, b) => a + b       # 参数类型可推导时可省略
xs |> map(fn(x) => x * x)
```

- `fn(params) => expr`；body 要多条语句就用块 `fn(x) => { ... }`。
- 闭包按值捕获绑定（捕获 `var` 是编译错误——想共享可变状态请显式传递）。

### 4.6 if

```dawn
let sign = if x > 0 { 1 } else if x < 0 { -1 } else { 0 }
```

- 条件必须是 `Bool`，分支体必须是块。
- 作为值使用时 `else` 必须存在且分支同类型；
  作为语句（值被丢弃）时可省 `else`，此时分支必须是 `Unit`。

### 4.7 循环

```dawn
for x in [1, 2, 3] { println("$x") }
while queue.non_empty() { ... }
```

- `for`/`while` 是 `Unit` 类型的语句，体内可用 `var` 累积。
- `break` 退出**最内层**循环，`continue` 跳到其下一轮。二者是类型 `Never` 的表达式
  （同 `return`，可出现在 match 臂等表达式位置）；只在循环体内合法，且**不可穿越
  lambda/局部函数边界**去够外面的循环（lambda 是独立函数，想退出它用 `return`）。
  无标签形式——需要多层跳出请提取函数用 `return`。comptime 循环同样支持。
- `for x in a..b` 支持右开区间的整数范围。

惯用风格优先 `map`/`filter`/`fold`；循环是给性能敏感处和口味用的。

### 4.8 下标

```dawn
let x = xs[i]        # List[T] -> T；越界 panic（含负数）
let v = m["key"]     # Map[K, V] -> V；缺键 panic（消息含键值）
let c = rows[1][0]   # 可链式、可与 ?/./() 组合
```

- **`[]` 是断言，get 家族是问询**：`xs[i]` 用于「下标必然合法，越界是 bug」的场合
  （panic 语义，同 Rust）；越界/缺键是正常分支时用 `get(xs, i)` / `map.get(m, k)`（返回 `Option`）。
- 下标只作用于 `List`（下标为 `Int`）与 `Map`（下标为键类型），其余类型是编译错误。
- comptime 中支持 `List` 下标（越界为编译错误）。
- 只读——列表与映射是不可变的，没有 `xs[i] = v`。

### 4.9 return

```dawn
fn classify(n: Int) -> String = {
  if n < 0 { return "negative" }   # guard 子句
  if n == 0 { return "zero" }
  "positive"
}
```

- `return expr` / 裸 `return`（仅 `Unit` 函数）从**最内层函数**提前返回——
  在 lambda 内则退出该 lambda（同 `?` 的作用域规则）。
- `return` 是类型为 `Never` 的表达式，可出现在任意表达式位置（如 match 分支）。
- 所在函数（或 lambda 的期望类型）必须已声明返回类型——省略返回类型的推导函数内不可用。

---

## 5. 模式匹配

```dawn
match shape {
  Circle(r) if r > 100.0 -> "big circle"
  Circle(r)              -> "circle $r"
  Rect(w, h)             -> "rect $wx$h"
  Point                  -> "point"
}
```

### 5.1 模式形式

| 模式 | 例 | 匹配 |
|------|-----|------|
| 字面量 | `0`, `"yes"`, `true` | 相等则匹配 |
| 绑定 | `x` | 恒匹配并绑定 |
| 通配 | `_` | 恒匹配不绑定 |
| 构造器 | `Some(x)`, `Rect(w, h)`, `Rect(w: w, ..)` | 按位置或按名解构，`..` 忽略其余字段 |
| 记录 | `Point { x, .. }` | 字段解构 |
| 元组 | `(a, b)` | |
| 列表 | `[]`, `[x, ..rest]` | 空表 / 头与余下 |
| 或 | `0 \| 1 \| 2` | 任一匹配（各分支绑定必须一致） |
| 守卫 | `pat if cond` | 模式匹配且守卫为真 |

### 5.2 穷尽性

`match` **必须穷尽**。编译器对 ADT/Bool/Option/Result/元组做穷尽性检查，
缺分支报错并列出缺失构造器。`Int`/`String`/`Float` 上的 match 必须有
`_` 或绑定兜底分支。

`let` 也接受不可反驳模式：`let (a, b) = pair`、`let Point { x, y } = p`。

---

## 6. 效果系统

### 6.1 模型

效果格子只有两点：**pure**（默认、不写）与 **io**。
`!io` 覆盖一切可观测副作用：文件、网络、时钟、随机数、打印、可变全局态、
以及全部 Java 互操作。

### 6.2 规则

1. 函数体的效果 = 体内所有调用效果的并。
2. 签名未标 `!io` 的函数，体内出现 io 效果 → 编译错误
   （报错指出哪个调用引入了 io，并建议在签名加 `!io` 或消除该调用）。
3. 标了 `!io` 但体是纯的 → 允许（预留演化空间）；「多余 `!io`」的 lint 需要类型分析，
   v0.1 的 `dawn fmt --check` 只做格式检查、**未实现**该提示（留待后续）。
4. 纯函数**保证**：给定相同参数返回相同值、无可观测副作用。
   编译器可据此折叠、消重、在 comptime 调用。
5. `panic`/`todo`/`assert` 不算 io——它们不返回（发散不是效果）。

### 6.3 效果多态

高阶函数用效果变量转发参数的效果：

```dawn
fn map[T, U](xs: List[T], f: fn(T) -> U !e) -> List[U] !e
fn compose[A, B, C](f: fn(A) -> B !e1, g: fn(B) -> C !e2) -> fn(A) -> C !(e1 | e2)
```

- 效果变量 `!e` 无需声明，在签名中出现即引入；作用域是整条签名。
- `!(e1 | e2)` 为并，**规范化**后存储：`io` 吸收一切（含 `io` 的并即 `io`）、`pure`
  是幺元（可省去）、单个变量的并降级为该变量本身（`!(e|e)` 即 `!e`）。因为格子只有
  两点，求解就是布尔或——推导必然可判定。
- 调用点实例化：`compose(inc, tag)` 若 `inc` 纯、`tag` 为 `!io`，则结果类型的效果并
  规范化为 `!io`；两者皆纯则规范化为纯，结果可在纯上下文调用。
- 调用点实例化：`map(xs, println)` 中 `e = io`，故整个调用是 io。

### 6.4 逃生门：`unsafe_pure`（仅限 std）

`unsafe_pure { <表达式> }` 是**纯 FFI** 的表达式块：作者担保被包裹的表达式为纯，
类型系统据此把它的效果由 `!io` **屏蔽为 pure**，于是一个宿主互操作调用可以支撑一个
纯函数。设计见 [`docs/pure-ffi-design.md`](pure-ffi-design.md)。

**用户代码不可用（2026-07-30 收窄，LANG-01）**：这个戳无条件抹掉检查器证明过的效果，
而纯性许可的一切推理（折叠、重排、省略调用）都会相信它——这是健全性的口子，
`design.md` 的原始裁决本就是「unsafe escape 不向用户代码开放」。它只在捆绑 std 模块内
合法（`is_std_module`）；用户模块中出现即编译错误。std 是唯一随编译器一起发布、
一起自举、一起被 N vs N−1 差分守护的代码——担保收在那儿才有人对账。
真有 std 之外的纯包装需求，它应该成为一个 std 函数（不给逃生阀：给了等于没收窄）。

```dawn
use java "java.lang.Math"

pub fn sqrt(x: Float) -> Float = unsafe_pure { Math.sqrt(x) }   # 仅 std 模块内合法
```

> **而 std 今天也不用它。** 上面这个例子曾经是 `std/str` 的真实写法；今天 std 一处
> `unsafe_pure`、一处 `use java` 都没有——那些操作已成为 **intrinsic 契约**的一部分（§11），
> 由后端负责兑现，而不是由调用点逐个作保。所以 `unsafe_pure` 在整个生态里**零使用点**：
> 留着它是给未来 std 底层包装的机制，不是语言表面。

被包裹的必须是**静态方法调用**：Dawn 原生类型（String/List/Bytes/Map/Set）不是 Java 类型，
`s.substring(…)` 这种实例调用今天走不通（`pure-ffi-design.md` §九）。

- **只改效果，不放松类型**：块内类型检查、重载消解一律照常；被盖的只有「效果」这一维。
- **拒绝屏蔽效果变量**：块内若出现效果多态调用（`!e`，如高阶 `map`/`fold`），报错——
  盖成纯即撒谎，且 `e = io` 时值都定不下来。这条护栏把高阶代码逼向「纯 Dawn 递归 over
  一阶 pure 原语」的正道（§6.3），故 `unsafe_pure` 只会出现在最底层一阶包装上。
- **多余即报错**：块内本就纯（无 io）→ 报 `redundant unsafe_pure`，保证每处 `unsafe_pure`
  都是载荷性的、`grep unsafe_pure` 即完整信任清单。
- **不健全性**：这是可撒谎的口子（名字带刺以示警）。缓解靠具名可 grep + 多余 lint +
  两层结构把担保收敛到极少数一阶原语；编译器不验证 Java 纯度（做不到）。
- **运行期透明**：codegen 直接生成内层表达式，无任何运行期标记。
- **编译期折叠（route C）需要 `--comptime-ffi`，默认关**：`const A: Int = unsafe_pure { Math.max(3, 7) }`
  折叠为 7，但只在这个 flag 打开时。限制另有两条：只反射**静态**方法，边界类型限
  `Int/Float/Bool/String/Unit`。
- **纯度与许可是两件事**（2026-07-27 分家）：`unsafe_pure` 曾同时充当 route C 的许可证，
  于是「我担保这个调用是纯的」被顺带读成「编译器可以在自己的进程里跑它」。前者是作者对
  **程序**的断言，后者是对**编译这份源码的那台机器**的索取——受害人不同，就不该同一个记号。
  这三道闸都不是沙箱：`System.load(String)` 就是静态、String 入参、void 返回。故门由
  **运行编译器的人**开，不由**被编译的源码**开。

---

## 7. comptime

### 7.1 形式

```dawn
const CRC_TABLE: List[Int] = comptime { crc32_table() }

fn lookup(d: Int) -> Float =
  SIN_TABLE.get(d % 360).expect("table covers 0..360")
```

`comptime { ... }` 是表达式：编译期由编译器内置解释器求值，
结果作为常量嵌入产物。顶层 `const` 的右侧隐式处于 comptime 上下文。

### 7.2 约束

1. comptime 代码**必须是纯的**（可调用任何纯函数，包括本模块与依赖模块的）。
2. 结果类型必须**常量可序列化**——即编译器能在类初始化时把这个值重新造出来：
   `Int`/`Float`/`Bool`/`String`/`Unit`，以及仅由这些组成的 `List`/元组/record/ADT。
   函数值不行。**不透明类型与它的目标一样可序列化**（§2.7）。
   `Map`/`Set` 暂不可以：它们是 `Array` 之上的 HAMT，而 comptime 解释器没有 `Array`
   原语；`List` 能行是因为解释器自带列表表示，不是因为它跑得动 `std/pvec`。
3. 求值有步数预算（默认 10⁸ 步，`--comptime-fuel` 调整），超限报错——
   保证编译必然终止。
4. comptime 里没有 Java 互操作、没有 io（由约束 1 自动保证）。

### 7.3 明确不做

comptime **不能**生成类型、不能生成声明、不能内省 AST。
它只是"提前跑一段纯 Dawn 代码"。元编程不是 v0.1 的目标。

---

## 8. 错误处理

### 8.1 可恢复：Result / Option + `?`

```dawn
fn parse_config(path: String) -> Result[Config, String] !io = {
  let text = read_file(path)?          # Err 时提前返回该 Err
  let json = json.parse(text)?
  Config.from_json(json)
}
```

- 后缀 `?` 作用于 `Result[T, E]`：`Ok(v)` 解出 `v`，`Err(e)` 使**当前函数**
  立即返回 `Err(e)`。对 `Option[T]` 同理（`None` 提前返回 `None`）。
- `?` 所在函数的返回类型必须是相容的 `Result`/`Option`（`E` 类型必须一致，
  v0.1 无自动错误类型转换）。
- 这是 v0.1 中唯一的非局部控制流。

**跨错误类型：写个本地 helper，别等语言给。** `?` 要求 `E` 一致，所以返回
`Result[_, HttpError]` 的函数不能直接 `?` 一个 `Result[_, String]`。解法是
在边界处放一个 4 行函数：

```dawn
fn as_http[T](r: Result[T, String], status: Int) -> Result[T, HttpError] =
  match r { Ok(v) -> Ok(v)
            Err(m) -> Err(http_error(status, m)) }
```

之后 `let rows = as_http(repo_call(...), 500)?` 即可，`?` 接管其余部分。

> 曾为此加过一个 std 的 `map_err`，2026-07-19 撤销：dawnop-site 的 102 处跨层
> `match` 里，94 处靠「`?` + 上面这个 helper」就能拆（另有 8 处错误类型本就相同，
> 连 helper 都不需要），而 `map_err` 的全部作用只是把这个 helper 从 4 行缩成 1 行，
> 一个项目一次。真正解开那 102 处的是 `?` 和局部 helper，不是新增的库函数。

`?` 在 lambda 内从该 lambda 返回，故闭包里的桥同样可以塌。

### 8.2 不可恢复：panic

`panic(msg)`：打印消息与 Dawn 层栈迹，进程以非零退出。
`todo()` 等价于 `panic("not yet implemented")` 且能通过任意类型检查
（返回类型为底类型 `Never`）。

**后缀 `!`**：`o!` 把 `Option[T]` 解成 `T`，`None` 则 panic。语义同
`expect(o, msg)`，唯一区别是**消息由编译器生成**——含产生 `None` 的调用与源位置
（`unwrapped None from URI.create() at src/http.dawn:23`），故不必为它编造占位串。

```dawn
let uri = URI.create(url)!                      # 而不是 .expect("uri")
let base = HttpRequest.newBuilder()!.uri(uri)!  # 而不是 .expect("b") / .expect("b-uri")
```

`!` 存在的理由就是 §9.2：Java 把**引用返回一律包成 `Option`**，而绝大多数 JDK 方法
其实永不返回 null，于是解包是常态。

- 只作用于 `Option`。`Result` 用 `?` 传播（§8.1）或 `match`。
- 与 `.`/`[]` 同级、左结合：`a()!.b()!` 即 `((a()!).b())!`。
- 行尾可以是 `!`——它不是二元运算符，故不触发续行（§1.7）。
  `x! != v` 中 `!=` 仍是一个 token（先按最长匹配切分），比较的是解包后的值。
- **确有话要说**时仍用 `expect(o, "原因")`——它就是为此存在。

`get`/`map.get` 返回 `Option`（问询）；下标 `xs[i]`/`m[k]` 越界/缺键 panic（断言，§4.8）；
`Int` 除零（`/` 与 `%`）panic——是 panic 故 `catch_fault` 不拦（§4.3 数值边缘语义）。

---

## 9. Java 互操作

### 9.1 引入与调用

```dawn
use java "java.nio.file.Files"
use java "java.nio.file.Path"
use java "java.lang.StringBuilder"

fn slurp(p: String) -> Option[String] !io =
  Files.readString(Path.of(p).expect("valid path"))

fn build() -> String !io = {
  let sb = StringBuilder.new()      # 构造器统一拼写为 .new
  sb.append("a")
  sb.append("b")
  sb.toString().expect("non-null")
}
```

- `use java "全限定名"` 把类引入为：一个不透明类型 + 一个静态方法命名空间。
  **只读静态字段可访问**：`Class.FIELD`（常量惯例大写，如 `Integer.MAX_VALUE`、
  `Math.PI`、枚举常量 `TimeUnit.SECONDS`；小写字段名同样可读，如 `System.out`）读取该字段——
  值按 §9.2 映射（引用类型包 `Option` 需 `!` 解包，`int`/`double` 等基本类型加宽），
  效果同一切互操作为 `!io`。只读（无 `Class.FIELD = v`）；实例字段与非 `pub` 静态字段不可访问。
- **`.` 后的成员名可以是任意「词」**，包括与 Dawn 关键字同形的名字（`in`/`type`/`match` 等）：
  Java 有名为这些的成员，而 `.` 之后关键字无歧义、一律按成员名收。故 `System.in`（字段名 `in`
  是关键字）与 `obj.type()`（方法名 `type`）都能直接写，无需反射绕道。
- 构造器统一为 `Type.new(args)`，**返回 `T` 本身**（构造器不会返回 null，不包 Option）；
  实例方法用 `.method(args)`。
- **所有 Java 调用的效果都是 `!io`**，无例外（理由见 design.md D5）。
- **Java 调用的返回值允许直接丢弃**（语句位置或 Unit 块的尾位置）——Java API 常返回
  `this` 或状态码；「不得悄悄丢弃」规则只保护 Dawn 值。
- 返回值里出现**未导入的引用类**（如 `Path.of` 的 `Path`）时，值仍可用（自动成为
  不透明类型、可继续链式调用）；只有要在签名里**写出类型名**才需要 `use java` 导入。
- 类解析发生在**编译期反射**：JDK 类恒可见；第三方类须以 `--cp <jars>` 提供
  （`dawn run/test/build` 通用，§12.1），编译与运行共用同一份 classpath。
  LSP v0.1 仅解析 JDK 类，第三方类在编辑器里报未找到但命令行可编译。
- **嵌套类用点号写**：`use java "java.net.http.HttpResponse.BodyHandlers"`
  （不是 `$`——`$` 在字符串里会被当插值）。解析时先整体反射，失败则从右往左把
  `.` 逐个换成 `$` 重试，故任意嵌套深度都能用点号书写；绑定名取最后一段
  （`BodyHandlers`）。嵌套类的**泛型方法**仍按擦除返回不透明 `Object`（§9.2）——
  如 `HttpResponse.body()` 返回 `Object`，取字符串体用 `String.valueOf(...)` 桥回。

### 9.2 类型映射

| Dawn | Java | 方向 |
|------|------|------|
| `Int` | `long`（接收 `int` 自动加宽） | 双向 |
| `Float` | `double` | 双向 |
| `Bool` | `boolean` | 双向 |
| `String` | `java.lang.String` | 双向 |
| `Unit` | `void` | 返回 |
| 引入的类 `T` | 该类引用 | 双向 |

**Java 方法返回引用类型一律为 `Option[T]`**——null 在边界处被拦下。用 `!` 解包（§8.2）
或 `match` 处理：

```dawn
let uri = URI.create(url)!          # 方法：包 Option，解包
let sb = StringBuilder.new()        # 构造子：不包，直接是对象
```

**为什么方法包、构造子不包**——这不是两套随意的规则，而是各有依据：

- **构造子不包**：JLS 保证 `new` 表达式**永不**返回 null，包成 `Option` 是纯噪音。
- **方法包**：方法**可以**返回 null，且编译器**无从静态区分**。JDK 类不携带运行期可见的
  可空性注解——`URI.create`（永不 null）与 `Map.get`（真可空）反射出来的注解**都是空**。
  既然分不出，就只能一律包：宁可让 `!` 显式承担风险，也不把 null 放进 Dawn。

基本类型返回值不包 Option；`short`/`byte`/`int` 返回自动加宽为 `Int`，`float` 加宽为
`Float`。`char` 出入参 v0.1 不支持；数组走不透明直通（§9.5）。**Option 实参传 null**
同样推迟（v0.1 无法从 Dawn 侧传 null 给 Java）。

### 9.3 重载消解

按"实参个数 + 静态类型"打分选唯一候选（精确匹配 `long`/`double` 优于收窄到
`int`/`float`，`String` 优于 `CharSequence`/`Object`）；并列最高分或无候选都是
编译错误（错误信息列出候选签名）。函数值实参只匹配函数式接口形参（§9.4）；
Dawn `List` 实参可匹配 `List`/`Collection`/`Iterable` 形参（§9.6）；数组实参精确匹配
优于宽化到 `Object`（§9.5）。

**变长参数**照 JLS 分两相：**先不打包**试一轮（相位 1），全部失败才**按变参打包**
（相位 2）；**相位优先于分数**——分数是逐参求和、随实参个数增长，不分相位会让打包
候选反超精确匹配。可变部分内联铺开，与 Java 写法一致：

```dawn
let p = Path.of("a", "b", "c")!                  # 打包成 String[]，得 a/b/c
let l = List.of("a", "b")!                       # 相位 1 胜：选 of(E, E)
let e = List.of()!                               # 不传可变部分 = 打包 0 个 = 空数组
let b = BodyPublishers.concat(head, file, tail)! # 可变部分可放 Java 引用
```

尾部实参逐个对**数组分量类型**打分，规则同普通形参，故 SAM 转换（§9.4）与 List 桥
（§9.6）在可变部分内同样可用。传一个**现成数组**当可变部分（如 `String[]`）走相位 1，
原样传入不重新打包。注意标量不装箱（§9.2），故 `Object...` 收 `String` 与 Java 引用，
**收不了 `Int`/`Float`/`Bool`**；`char` 出入参不支持，`char...` 随之不支持。

### 9.4 SAM 转换：函数值跨边界

```dawn
use java "java.lang.Thread"

fn spawn_hello(msg: String) -> Unit !io = {
  let t = Thread.new(fn() => println(msg))   # Dawn lambda → java.lang.Runnable
  t.start()
  t.join()
}
```

- Java 形参是**函数式接口**（interface 且恰有一个抽象方法，`Object` 的公共方法不计）时，
  实参可传 Dawn 函数值——lambda、命名函数、构造器值均可。仅限接口；单抽象方法的
  **抽象类**不支持（实现经 LambdaMetafactory，构建期展开，native-image 零配置）。
- **匹配**：SAM 方法签名按 §9.2 映射成 Dawn 函数类型后做常规匹配；lambda 的参数类型
  可从形参播种（与泛型实参推导同一机制）。重载打分时函数值只匹配函数式接口形参。
  Dawn 不追踪 Java 泛型实参，**泛型 SAM**（`Predicate`/`Function` 这类）的参数按擦除后
  的类型进入 Dawn（通常是不透明 `Object`，只能原样传递）；具体类型的 SAM
  （`Runnable`、`HttpHandler`）才有完整体验。
- **效果不设限**：纯函数、`!io` 函数、效果变量函数都可传出。效果系统不追踪 Java 侧
  何时调用——Java 可能在任意线程、任意时刻（包括本次调用返回之后）调用该函数值。
  这不破坏纯度契约：Java 代码只可能在 Dawn 的 `!io` 调用之下、或无 Dawn 栈的
  Java 线程上运行，任何纯函数的签名承诺都未被违反。
- **参数的 null 边界**：回调的引用类型参数**不包 `Option`**，以 `T` 直达；桥接层逐参
  检查，Java 传入 null 立即 panic（消息指明回调边界）。与返回值包 `Option`（§9.2）
  互补：返回位置的 null 是常态故进类型，回调参数的 null 属病态故 fail-fast。
- **返回值收窄**：SAM 方法要 `int` 而 Dawn 函数返回 `Int` 时做**检查性收窄**，超出
  范围 panic，不静默截断；要 `float` 时按 IEEE 规则收窄 `Float`（可能损失精度，
  这是浮点语义而非溢出）。
- Dawn 函数在回调中 panic，以 `dawn.rt.PanicError`（`Error` 的子类）传给 Java
  调用方，不捕获不包装。

### 9.5 数组：不透明直通；`byte[]` = 一等 `Bytes`

数组值与未导入的引用类同待遇（§9.1）：可**接收、持有、传参**——重载打分按数组类型
精确匹配，或宽化到 `Object`；返回位置照 §9.2 包 `Option`。但数组（除 `byte[]`，见下）
**不可命名**（签名里写不出该类型）、**不可创建、不可索引**；要长度用
`use java "java.lang.reflect.Array"` 的 `Array.getLength(a)`。

**`byte[]` 是唯一例外：它就是一等类型 `Bytes`**（§9.5.1）。Java 方法返回的具体 `byte[]`
（如 `readAllBytes`/`toByteArray`/`Base64.decode`/`MessageDigest.digest`）照 §9.2 落成
`Option[Bytes]`；`Bytes` 可写进签名、存进 record、切片/索引/拼接/按内容比较；反向传给
Java `byte[]` 形参（`OutputStream.write`、`MessageDigest.isEqual` 等）直接匹配。

```dawn
use java "java.nio.file.Files"
use java "java.nio.file.Path"

fn slurp(p: String) -> String !io = {
  let bytes: Bytes = Files.readAllBytes(Path.of(p).expect("path")).expect("readable")
  decode(bytes, "UTF-8")
}
```

#### 9.5.1 `Bytes`：一等不可变字节序列

`Bytes` 是不可变的字节序列，运行期就是裸 `byte[]`。库函数（§11「bytes」组）：
`utf8(s) -> Bytes`（字符串的 UTF-8 字节）、`decode(b, charset) -> String`（按字符集解码）、
`bytes.len`、`bytes.at(b, i) -> Int`（0..255，越界 panic）、`bytes.slice(b, start, end)`
（`[start,end)`，下标 clamp 进范围）、`bytes.index_of(b, needle, from) -> Option[Int]`。
`Bytes ++ Bytes` 拼接、`==`/`!=` 按**内容**比较（`Show` 渲染为 `<N bytes>` 摘要）。
`Bytes` 的哈希是**内容**哈希（`Arrays.hashCode`），与内容 `==` 一致，故 `Bytes` **可以**
作 Map/Set 键。（曾因 `byte[]` 的 JVM `hashCode` 是引用同一性而禁，两头都改成内容之后
禁令没跟着撤，2026-07-27 撤掉。）`Bytes` 不参与 comptime 常量折叠，也不能作 bare 一等函数值
（用 lambda 包一层）。

**不透明值收窄回具体引用形参**：擦除泛型的返回（§9.2）落成不透明 `Object`，但业务
常需把它**原样喂回**某个要具体引用类型的 Java 形参——例如 `HttpResponse.body()`
以 `BodyHandlers.ofByteArray()` 取到的 `Object` 实为 `byte[]`，要写进
`OutputStream.write(byte[])`。此时重载消解允许不透明 `Object` 实参匹配具体引用形参，
桥接处插一次运行期 `CHECKCAST`（失败即 `ClassCastException` 穿透，非静默）。方向与
§9.3 的「宽化到 `Object`」相反、成对：宽化是丢类型信息传出，收窄是运行期认领回来。
不透明值仍**不可命名、不可索引**——收窄只发生在跨边界传参的隐式适配处，Dawn 代码
拿不到该类型的名字。这让「取二进制体 → 透传出去」这类管道无需把字节读进 Dawn 值
（省一次全量拷贝，大文件不顶爆内存）。

若确知某个擦除泛型的不透明 `Object` 运行期是某个具体引用类型（如 `HttpResponse.body()` 配
`BodyHandlers.ofByteArray()` 时是 `byte[]`），用泛型内建 `cast(x) -> T` 把它**认领**成该类型
（T 取自调用点的期望类型，如 `let b: Bytes = cast(...)`；§9.5.1）——桥接处插一次运行期 `CHECKCAST`，
类型不符即 `ClassCastException` 穿透。T 须是引用类型（编译期拒绝 primitive / 无期望类型）。

### 9.6 List 桥接：Dawn `List` 直达集合形参

Java 形参声明为 `java.util.List` / `java.util.Collection` / `java.lang.Iterable` 时，
实参可传 Dawn `List[T]`。**零拷贝**：桥接处套一层不可变视图
（`Collections.unmodifiableList`），Java 侧的变异方法抛
`UnsupportedOperationException`——同 Scala `asJava` / Clojure 持久集合的约定。

- 元素类型 `T` 限：`Int` / `Float` / `Bool` / `String` / 已导入或不透明的引用类。
  元素是 `List`/`Map`/`Set`/ADT/元组/record/函数值时拒绝（编译错误）——嵌套容器
  零拷贝会泄漏内层可变性，v0.1 不做深包装。
- 元素按 §9.2 的装箱表示直达（`Int` → `java.lang.Long`）。泛型擦除意味着期待
  `List<Integer>` 的 API 会在取用时 `ClassCastException`，v0.1 不救，选 API 时留意。
- 方向仅 Dawn → Java；Java 返回的集合仍是不透明引用 + `Option`（§9.2），可链式调用。
  `Map`/`Set` 桥接 v0.1 未提供。

### 9.7 限制

不能继承 Java 类；不能以**命名类**形式实现 Java 接口——函数值经 SAM 转换（§9.4）
传出是唯一路径。只读静态字段可访问（`Class.FIELD`，§9.1）——枚举常量与静态常量直接读
（`TimeUnit.SECONDS`、`Integer.MAX_VALUE`）；写静态字段、实例字段仍不支持。数组不可创建/索引/命名（§9.5）；
`Map`/`Set` 不桥接、Java 集合不反向转换为 Dawn 值（§9.6）。变长参数只支持不传
可变部分（§9.3）；`Option` 实参传 null 不支持（§9.2）。

### 9.8 外部失败屏障：`catch_fault`

> 这个内建到 v0.30.0 为止叫 `java_try`，v0.31.0 改名。它拦的是 **fault**——外部世界
> 造成的失败——而这个分类自 native 有了失败种类之后就是两个后端共用的
> （native-backend-plan §14.9），和 Java 无关了；名字比理由多活了一阵。
> 用旧名字会得到「`java_try` is not a builtin; renamed to `catch_fault`」。

Dawn 无异常：Java 调用抛出的异常默认原样穿透并终止程序（等同 panic 语义）。
但**预期中的外部失败**（网络断开、SQL 约束冲突、解析失败）在 Java 世界以异常表达，
它们不是 bug，应进 `Result`。内建 `catch_fault` 是唯一的转换点：

```dawn
use java "java.lang.Long"

fn parse(s: String) -> Result[Int, ForeignError] !io =
  catch_fault(fn() => Long.parseLong(s))
  # Err(ForeignError { kind: "java.lang.NumberFormatException", message: ..., cause: None })
```

- 签名 `catch_fault[T](f: fn() -> T !io) -> Result[T, ForeignError] !io`；闭包可为纯函数。
- 只拦 `java.lang.Exception` 及其子类；`Error` 不拦——**Dawn 的 panic
  （`dawn.rt.PanicError` 是 `Error` 子类）原样穿透**，panic 仍然是 bug、不可恢复。
- `Err` 载荷是 `ForeignError`——一个 prelude record，字段与取值见 §9.8.1。它到
  v0.32.0 为止是一句**渲染好的字符串**（`Throwable.toString()`），本节也曾建议
  「需要区分异常种类时按前缀匹配字符串」；那条建议已被撤销，`kind` 是它的替代物。
- 边界之内失败照常传播：`catch_fault` 包住整段复合调用即可，无需逐调用包裹。

配套的 `catch_panic[T](f: fn() -> T !io) -> Result[T, ForeignError] !io` 拦的是
**Dawn panic（`PanicError`）与 `Exception` 两类**——不是任意 `Throwable`：
`VirtualMachineError`（堆耗尽、栈溢出）穿透，资源耗尽不是一个值。它用于**监督边界**——
服务器的单个请求、任务 runner 的单次执行：一个请求 panic 应变成 500 并记录，而非掀翻
整条连接或进程。它与 `catch_fault` 分工明确：`catch_fault` 处理**预期外部失败**、放
panic 穿透；`catch_panic` 是**隔离点**。普通业务失败仍走 `Result`，别拿 `catch_panic`
当常规错误处理。

> **这条分工与后端无关。** JVM 从类层次白拿它（`Error` 对 `Exception`）；native
> 没有异常，一切失败走同一条 `longjmp`，所以失败带一个**种类**、handler 记住自己
> 收不收 panic。判据是同一条：**语言自己定义的失败是 panic**（`panic`、`expect`、
> 越界下标、除零、非法码点），**外部世界造成的失败不是**（io 原语——量下来也只有
> 这一类）。两个后端的实测比对在 `scripts/spike-native/catch_kinds.dawn`；
> 在它写出来之前 native 的 `catch_fault` 拦下了本该穿透的每一个 panic。

#### 9.8.1 载荷 `ForeignError`

「按前缀匹配字符串」曾是本节的建议，现已**撤销**：它把控制流建在一句可以被重构、被
本地化、被换一版 JDK 改掉的文本上。载荷是一个 prelude record：

```dawn
type ForeignError = { kind: String, message: String, cause: Option[String] }
```

- `kind` 是**后端自己给这类失败起的名字**，而且是个**名字**不是一句渲染：JVM 上是
  二进制名（`getClass().getName()`，如 `java.lang.NumberFormatException`、
  `dawn.rt.PanicError`），native 上是运行时的失败种类（`"panic"` / `"fault"`）。
- **按 `kind` 分流的代码是后端相关的代码。** 可移植的匹配只有 `Ok`/`Err` 这一层。
  取值表与理由在 `docs/runtime-intrinsics-design.md` §12.4。
- `message` 是失败自己说的话（JVM 的 `getMessage()`，无则空串）；`cause` 是底下那层
  失败的渲染，没有则 `None`。不带栈：渲染栈的代价要付在每一次屏障上。

**还有一对过渡拼法 `catch_fault_e` / `catch_panic_e`。** 它们与上面两个**签名完全
相同**，抓什么、放什么穿透也逐字相同，存在的唯一理由是种子纪律：一个内建的**签名**
和它的名字一样受它约束，而且更紧——改名可以一期内让两张表都认识两个拼法，改载荷
类型不行，编译器自己的调用点没法同时满足两张表。所以新形状先以不被任何人调用的名字
落地（v0.32.0），发一次 release 教会上一代编译器，再迁调用点并把签名交还给
`catch_fault`/`catch_panic`（本版）。**新代码一律写不带 `_e` 的名字**；下一次种子推进
之后 `_e` 这对会被删掉。分期见 `docs/audit/error-model-design.md` §六。终局只有一对
屏障，载荷是 `ForeignError`，不保留 String 版本。

---

## 10. 模块系统

### 10.1 文件与模块路径

一个 `.dawn` 文件 = 一个模块。模块路径 = 相对**模块根**的路径去掉扩展名：
`<root>/json/lexer.dawn` → 模块 `json/lexer`。路径每段须匹配 `[a-z_][a-z0-9_]*`
（与文件名一致），否则编译错误。

**模块根的确定**：

- **目录模式** `dawn run|test|build <dir>`：根 = `<dir>/src`，入口 = `<dir>/src/main.dawn`
  （缺失则报错并给出预期路径）。
- **文件模式** `dawn run|test|build <file.dawn>`：从该文件所在目录**向上找最近的名为
  `src` 的祖先目录**作为根；找不到则根 = 文件所在目录。LSP 用同一条启发式，故单独打开
  一个子模块文件也能解析它相对根的 `use`。

**目录约定即工程定义**：模块根、入口、模块路径全部由目录结构决定，不需要清单文件。

项目**可选**带一个 `dawn.toml`，只承载目录约定表达不了的东西——工程身份与依赖。
没有它的项目按上述规则照常工作。schema 1 的内容：

```toml
schema = 1                                      # 必须是第一个 key
name = "backend_dawn"                           # 工程身份（[a-z_][a-z0-9_]*）

[java-deps]                                     # Maven 依赖，`use java` 用得到
sqlite = "org.xerial:sqlite-jdbc:3.36.0.3"      # 精确坐标；禁 SNAPSHOT、禁版本区间

[deps]                                          # Dawn 源码包：别名 = 本地目录
web = "../packages/web"

[deps.json]                                     # 或远端归档（zip / tar.gz）
url = "https://github.com/dawnop/dawn-lang/archive/refs/tags/v0.7.0.zip"
version = "1.0.0"                               # 严格 x.y.z；版本求解 = MVS
hash = "d1:<sha256>"                            # 解包文件树的内容哈希，即包身份
subdir = "packages/json"                        # 归档内的包根（可选）
```

`[deps]` 的别名只是**本方源码的拼写**（`use <别名>/<模块>`）；包的身份是它自己
manifest 里的 `name`——类名命名空间、版本求解、全程序一名一份都按真名进行，
别名引入会在装载时规范化为真名。`dawn add <坐标|url|路径>` 可代写这些条目
（抓取并计算 hash，保留手写格式）。

`dawn run|test|build` 会拉取 `[java-deps]`（含各依赖包声明的，取并集）并挂上
classpath（与 `--cp` 合并）；`dawn build` 另把它们复制进 jar 同级的 `lib/`。
仓库地址走 `$DAWN_MAVEN_MIRROR`，不进 manifest。

**manifest 永远是数据，不是代码**——不存在可执行的 `build.dawn`。理由与完整设计见
[`package-design.md`](package-design.md)。

### 10.2 引入

```dawn
use json/lexer                 # 整模块引入；别名 = 末段 lexer，限定访问 lexer.next(...)
use json/lexer as jl           # 显式别名，限定访问 jl.next(...)
use json/value.{Json, render}  # 选择性引入，非限定使用
use java "java.lang.Math"      # Java 互操作（§9），形式不变
```

- 一个模块只能被 `use` 一次（整模块或选择性，二选一）；重复 `use` 是错误。
- `use` 可出现在顶层任意位置（与 `use java` 一致），`dawn fmt` 不重排。
- **`as` 重命名**：整模块引入可用 `use a/b/c as name` 显式指定别名（默认别名 = 末段）。
  `as` 是**上下文关键字**（只在整模块路径之后特殊，不是保留字，仍可作普通标识符）；只用于
  整模块引入，选择性引入不需要。两个整模块引入若末段同名，用不同 `as` 别名即可并存
  （否则末段同名 → 错误）。

### 10.3 名字解析（消歧规则）

- 整模块引入的别名与本模块顶层声明、局部绑定、参数**同一命名空间**：
  **声明任何与模块别名同名的顶层 fn/type/const、局部或参数都是编译错误**
  （"`lexer` shadows the imported module `json/lexer`"）。由此 `lexer.next(x)` 永不歧义——
  `lexer` 要么是一个绑定（走 §4 的 UFCS 点调用），要么是模块别名（限定访问），不可能两者兼是。
- 限定访问支持**表达式位置**的 `alias.fn(args)`（调用一个 pub 函数），以及**类型位置**的
  `alias.T[...]`（LANG-06，2026-07-30）：类型位置的小写名只可能是模块别名，故无歧义；
  可指向导出的 ADT/record 或 `pub alias`（后者按声明方的解析展开）。
  **模式位置**同样支持限定构造器 `m.C(..)` / `m.Pt { .. }`：模式里的小写名后跟 `.大写名`
  只可能是模块别名。**限定常量 `m.NAME` 与限定构造器 `m.C(..)` / `m.C`（表达式位置）
  亦可用**（同日）：本模块可以另有同名的常量或构造器，两者互不干扰——Core 里常量的身份是
  (声明模块, 名字) 而不是名字；限定构造器与不带限定的写法进的是同一段检查，故字段名、
  arity、spread、泛型实例化的行为完全一致。
- 选择性引入一个 `type` 同时引入其**全部构造器**（与 `pub type` 导出构造器+字段的规则一致）。
- 选择性引入的名字与本模块顶层声明或其他引入冲突 → 错误。**与 prelude 名冲突**：
  选择性引入**可以**遮蔽 prelude（你逐字要来的名字，意图明确）；**顶层 fn / trait 方法**
  也可以遮蔽 builtin/std 的**函数**名（Rust 式）——解析序是本模块声明 → std → 内建，
  故遮蔽在本模块内是全量的：被遮蔽的拼写在该模块不可达，这是声明者自己的选择。
  但内建与 prelude 的**类型 / trait** 名（`Map`/`Option`/`Ord`…）仍不可重定义。

### 10.4 可见性

所有声明默认模块私有；`pub` 导出 `fn`/`type`/`alias`/`const`（`pub type` 连带构造器与字段，见 §3.3）。
访问或引入非 `pub` 项 → 错误（`` `parse` is private to module json/parser ``，附 hint：加 `pub`）。

> **加载范围（2026-07-30，LANG-07）**：`dawn run/test/build <dir>` 默认加载 `src/` 下
> **全部**模块——未被引用的模块也检查（bit-rot 防护，这是对的默认）。`--closure`
> 收窄为「入口 `src/main.dawn` 的 use 闭包」，供大工程出产物用；`dawn check` 恒为全仓。
> CI 推荐：`dawn check` 守全仓、`dawn build --closure` 出产物。

### 10.5 编译单元与求值顺序

- **目录模式加载 `src/` 下全部 `.dawn` 文件**（不止 `use` 闭包）：未被引用的模块也要通过
  类型检查（防 bit-rot），其 test 块也被 `dawn test` 执行。
- `use` 依赖图**禁止成环**，报错打印环路（`json/a → json/b → json/a`）。
- 类型检查与 comptime 求值按依赖**拓扑序**进行；跨模块引用的 `const` 值在使用方求值前已就绪。
- 类型同一性：同一 `type` 声明在整个程序中是同一个类型（每个文件只解析/检查一次）。
- 入口：main 模块的 `pub fn main() -> Unit !io`。

### 10.6 捆绑标准库与 prelude

标准库以 **Dawn 源码随编译器捆绑**，组织为真模块（[`stdlib-naming.md`](stdlib-naming.md)）：
`std/str`、`std/bytes`、`std/io`、`std/list`、`std/map`、`std/set`、`std/cursor`。
`use std/x` 命中编译器 jar 内的资源而非磁盘（磁盘上 `src/std/` 路径**保留**，落文件报错）；
之后与普通模块引入完全一致——限定访问 `map.insert(m, k, v)`、选择性引入
`use std/list.{find}`（§10.2/§10.3）。同名短名跨模块共存（`str.len` / `bytes.len`），
由限定或选择性引入消歧。

**prelude** 是其中隐式可用、无需 `use` 的高频核：`List`/`Option`/`Result` 的构造器、
`println`/`print`、`map`/`filter`/`fold`、`sort` 族（std/list）、内建的 `len`/`get`/`range`/
`to_string`/`join`/`parse_*`/`panic`/`todo`/`expect`/`unwrap_or`/`cast`/
`catch_fault`/`catch_panic`/`args` 等一屏以内（全集见 `dawn doc --builtins`）。

**顶层声明可以遮蔽 builtin/std 函数名**（§10.3，Rust 式）：解析序是本模块声明 →
std → 内建，std 模块自己的 `pub fn len` 正是靠这一条合法。

> **历史（v0.4.0 → v0.5.0）**：模块化之前的平铺拼写（`map_insert`、`str_len`、
> `trim` 的隐式可见等）在 v0.4.0 保留了一版并逐处警告，v0.5.0 已从公开命名空间
> 移除——只剩 prelude 与模块限定两条路；旧拼写的报错会提示它搬去了哪个模块。

---

## 11. 标准库草案（v0.1 范围）

> **实现位置对使用者不可见。** 本节的名字有两个来源：编译器内建表，以及**随编译器捆绑的
> `std/` 模块（Dawn 源码，§10.6）**。prelude 名隐式可见；其余以 `use std/x` 引入、
> `x.fn(...)` 限定调用。哪边实现（内建 or std 包装）不影响拼写与语义
> （[`docs/builtins-to-stdlib.md`](builtins-to-stdlib.md)）。`dawn doc --builtins` 输出全集。

- `core/list`：`map filter fold len get range ...`；排序与极值（元素/键类型须具
  `Ord`，见 §3.5；全部稳定、平局取第一个）：
  - `sort[T: Ord](xs) -> List[T]` — 升序稳定排序
  - `sort_by(xs, cmp: fn(T, T) -> Int) -> List[T]` — 自定义比较函数
  - `max/min[T: Ord](xs) -> Option[T]` — 极值；空列表 `None`
  - `max_by/min_by[T, K: Ord](xs, key: fn(T) -> K) -> Option[T]` — 按键取极值
- **字符串**：prelude 里有 `join parse_int parse_float to_string`（字符串转数字是
  `parse_int(s) -> Option[Int]`——没有重载，`to_int`/`to_float` 只做 Int↔Float 转换）；
  其余在 **`std/str`**：`str.len str.is_empty str.trim str.to_lower str.to_upper
  str.contains str.starts_with str.ends_with str.index_of str.last_index_of
  str.repeat str.substring str.pad_start str.reverse str.chars str.split
  str.from_char`。

  `to_lower`/`to_upper` 是 **Unicode 简单(1:1)大小写映射**：一个码点进、一个码点出，
  无 locale、无上下文，故**码点数不变**。这排除了完整映射的三类特例——长度会变的
  （`ß` → `SS`）、locale 相关的（土耳其语的 `i`）、上下文相关的（希腊语词尾 sigma）。
  取简单映射不是为了省事：完整映射不是一个后端能从一张表实现的函数，而 Dawn 要求
  一个原语在每个后端上是同一个函数。需要完整映射的场合属于能接收 locale 的库。

  那张表是**编译器的**（`selfhost/src/case_table.dawn`，生成物，记着生成它的 JDK），
  两个后端各自领走一份：JVM 写进 `dawn/rt/Strings`，native 写进发出来的 C。所以
  `str.to_upper` 的答案**不随宿主 JDK 的 Unicode 版本变**——升级到新 Unicode 是重新生成
  这张表这一件明确的事，而不是换台机器编译就悄悄换了答案。分类（`char_is_*`）同理，
  表在 `selfhost/src/class_table.dawn`。
- **`std/bytes`**（一等 `Bytes`，§9.5.1）：`bytes.utf8(s) -> Bytes`（字符串的 UTF-8 字节）、
  `bytes.decode(b, charset) -> String`（按字符集解码，替代旧 `String.new(bytes, charset)`）、
  `bytes.len(b) -> Int`、`bytes.at(b, i) -> Int`（0..255，越界 panic）、
  `bytes.slice(b, start, end) -> Bytes`（`[start,end)`，下标 clamp）、
  `bytes.index_of(b, needle, from) -> Option[Int]`（字节下标首次出现）。
  prelude 里另有 `cast(x) -> T`（把擦除泛型的不透明 `Object` 认领为具体引用类型 T，
  T 取自期望类型，§9.5）。
  另有操作符 `Bytes ++ Bytes` 与按内容的 `==`/`!=`。二进制请求体（multipart 上传、WebDAV PUT）、
  crypto/签名、HTTP 收发都直接走 `Bytes`，不再借道 latin-1 字符串。
- `Result` **没有**配套的库函数（无 `map_err`、无 `ok`）。`match` 和 `?` 够用，
  跨错误类型见 §8.1 的本地 helper；把 `Result` 转成 `Option` 在 4 万行 Dawn 里
  一次都没出现过（32 个 `-> None` 臂无一对着 `Err`），且丢错误与本语言取向相反
- **码点 / 字符**（§1.5、§2.1 的补充；字符即码点 `Int`）：
  - `code_points(s: String) -> List[Int]` — 拆成码点（增补平面的代理对合并为一个码点）
  - `from_code_points(cs: List[Int]) -> String` — 由码点组装（接受增补码点）
  - `str.from_char(c: Int) -> String` — 单码点转字符串（非法码点 panic）
  - `str.len(s: String) -> Int` — 码点数（区别于 `str.chars` 返回的 `List[String]`）
  - `str.substring(s: String, from: Int, to: Int) -> String` — 按**码点下标**切片，越界 panic
- **`std/cursor`**——上面这些**按码点下标**的函数，每次调用都要从串首数到那个下标，
  即单次 O(n)、放进循环就是 O(n²)。游标是**位置**而非计数，故每步恒定开销：
  - `cursor.start(s) / cursor.end(s) -> Cursor` — 串首 / 串尾游标
  - `cursor.done(s, c) -> Bool`、`cursor.char(s, c) -> Int`（到尾返回 -1）
  - `cursor.next(s, c) / cursor.prev(s, c) -> Cursor` — 进 / 退一个字符（宽度非恒定，故不能用加减）
  - `cursor.slice(s, from, to) -> String` — 按游标切，不做下标换算；非法区间 panic
  - `cursor.skip(s, c, sub) -> Cursor` — 越过一处已知出现的 `sub`（它恰是 `sub` 宽）——
    **唯一被认可的「游标前进已知宽度」**，替代 `i + len` 式算术
  - `cursor.find(s, sub, from) -> Option[Cursor]` — 游标进、游标出，故沿串反复查找整体仍线性

  游标是**位置**而非计数：从这些函数取得、传回、比较（`==` 与 `< <= > >=`——**同一
  字符串内**位置的先后是位置类型的合法操作）、存进容器/record 供回溯（它是普通值，
  回溯不需要额外机制）。**不要对它做算术**——只有算术能凭空造出落在代理对中间的非法位置。

  **算术与凭空铸造都是编译错误**：`Cursor` 是 `std/cursor` 用 §2.7 的
  `pub opaque type Cursor = Int` 声明的，只有那个模块能把它看成 `Int`。
  要在类型位置写出 `Cursor`，除 `use std/cursor` 外还要
  `use std/cursor.{Cursor}`（前者绑模块别名、后者绑名字，是两件事）。

  > 它曾是编译器铸造的不透明标量——`Ty` 的一个变体、`Head` 的一支、
  > eq/hash 标量表里各一行、七个文件里各一条 arm。同样的保证，现在没有自己的机制。
  > 顺带修掉一处自相矛盾：从前 `a < b` 编得过而 `list.sort` 报 Cursor 无序，
  > 因为回答这两个问题的是两张表；现在 `impl Ord[Cursor]` 一处回答两个。
  单串一次调用用下标版没问题，**循环里必须用游标版**——`docs/seq6-research.md` §五之补有实测。
- `core/option` / `core/result`：`map unwrap_or expect and_then ...`
- **`Map` / `Set`**（§2.2 的内建持久容器）——操作在 **`std/map`** 与 **`std/set`**：

  ```
  map.empty[K, V]() -> Map[K, V]              set.empty[T]() -> Set[T]
  map.from(entries: List[(K, V)]) -> Map[K, V]   set.from(xs: List[T]) -> Set[T]
  map.insert(m, k, v) -> Map[K, V]            set.insert(s, x) -> Set[T]
  map.remove(m, k) -> Map[K, V]               set.remove(s, x) -> Set[T]
  map.get(m, k) -> Option[V]                  set.has(s, x) -> Bool
  map.has(m, k) -> Bool                        set.size(s) -> Int
  map.size(m) -> Int                           set.to_list(s) -> List[T]
  map.keys(m) -> List[K]
  map.values(m) -> List[V]
  map.entries(m) -> List[(K, V)]
  ```

- `core/math`：`abs min max sin cos sqrt pow to_float to_int ...`（纯——
  内部以 `unsafe_pure` 包装 `java.lang.Math`；`@trusted_pure` 是该逃生门的旧名，已废弃）
- **`std/io`**：`io.read_line io.read_file io.write_file io.list_dir io.is_dir`（全部 `!io`；
  `println`/`print` 同住此模块但由 prelude 直呼，`args`/`catch_fault` 是内建）
  - 会失败的那些一律 `Result[T, ForeignError]`（§9.8.1）——`mkdirs` / `read_file` /
    `write_file` / `read_bytes` / `write_bytes` / `rename` / `temp_dir` / `list_dir` /
    `run`。到 v0.32.0 为止是 `Result[T, String]`，装的是屏障渲染好的那句话；换成
    结构化载荷，是因为「止在 std 门口」等于把这次要消灭的东西留给每一个调用方
  - `io.write_file(path, content) -> Result[Unit, ForeignError]` — **自动创建缺失的父目录**。
    `Ok` 不带值:曾返回 `String.length()`(UTF-16 码元,既不是字符数也不是字节数),
    2026-07-19 去掉——没有调用点读它
  - `io.list_dir(path) -> Result[List[String], ForeignError]` — 排序后的条目名；path 不是
    目录时 `Err`，`kind` 是 `"io.not_a_directory"`——std 自己铸的唯一一个 kind，
    其余都是后端给的
  - `io.is_dir(path) -> Bool` — 不存在或出错都视为 `false`

实现策略：能薄包 Java 就薄包（`String` 直接是 `java.lang.String`），持久 `List`/`Map`/`Set`
全部是**纯 Dawn 源**（`List` = `std/pvec` 持久向量，`Map`/`Set` = `std/hamt` 持久 HAMT，
均保插入序确定），后端只需实现 `Array` 一个原语。

---

## 12. 编译模型

### 12.1 产物

| 命令 | 产物 |
|------|------|
| `dawn run <file.dawn 或 dir>` | 编译到内存/临时目录，起 JVM 执行 |
| `dawn build <file 或 dir> -o app.jar` | 可执行 jar（`Main-Class: main` 已设） |
| `dawn build ... --native -o app` | 前一步 + `native-image`，独立二进制 |
| `dawn test <file 或 dir>` | 编译含 test 块的变体并执行（目录模式聚合全部模块的 test） |
| `dawn fmt <file 或 dir>...` | 格式化（目录模式递归全部 `.dawn`） |

**参数可为单文件或工程目录**（§10.1）：目录模式加载 `src/` 全部模块，入口
`src/main.dawn`；单文件模式向上找 `src` 祖先为根。jar 收全部模块类，`Main-Class` = 入口
模块类 `main`。

**第三方 jar：`--cp <jars>`**（run/test/build 通用；路径分隔符分隔、可重复）。
编译期 `use java` 解析与运行期加载共用这份 classpath。`build` 把各 jar 记入 manifest
的 `Class-Path`（相对产物目录，jar 挪走要一起挪），产物仍 `java -jar` 直接跑；
`build --native` 改以 `-cp` 形式调 native-image（第三方库的反射/JNI 是否过
native-image，责任在库，见 §12.3）。

`--cp` 本身不做依赖解析：它要什么就挂什么，传递依赖得自己列全。**需要依赖树的库走
`[java-deps]`**（§10.1 的 `dawn.toml`）——那条路径经 coursier 解析 Maven 传递依赖。本节曾写「Dawn
无依赖解析——只接受单 jar、零传递依赖的库」，那是 `[java-deps]` 出现之前的事实，
与 §10.1 直接冲突。

**保证**：同一程序在 JVM 与 native 下行为一致（除启动时间与内存占用）。

### 12.2 字节码映射

| Dawn 构造 | JVM 实现 |
|-----------|----------|
| 模块 `json/lexer` | 一个类，内部名 `json/lexer`（包 `json`、类 `lexer`），函数为 static 方法 |
| ADT/record | 类名带模块前缀：`json/lexer$Token`、构造器 `json/lexer$Token$Num` |
| 跨模块调用 | 对方模块类上的 `invokestatic`；构造器/字段照常（类公开） |
| ADT | abstract class + final 子类；无载荷构造器为单例 |
| record | final class + 字段（不依赖 Java record，兼容旧字节码目标） |
| `match` | `instanceof` 链 + 字段读取（不用 indy、不用 pattern switch） |
| lambda/闭包 | `LambdaMetafactory`（native-image 支持名单内） |
| 泛型 | 擦除 + 装箱 |
| 结构相等类型 | ADT/record/元组仍生成配套 `equals` 与 `hashCode`，但那是**给 Java 调用方看的**——Dawn 的 `==`/`hash` 是 lowering 按结构展开的 Core 函数（§4.3），`Map`/`Set` 经字典走它。有 `impl Eq`/`impl Hash` 时这两个方法转发到该 impl |
| `Int`/`Float`/`Bool` | 原生 `long`/`double`/`boolean`，仅泛型位置装箱 |
| `Unit` | `Ldawn/rt/Unit;`——单例引用，占一个槽位，形参/字段/捕获位与别的引用无异 |
| `Never` | `V`，且只出现在返回位（不返回的表达式没有形参或字段可占） |
| `panic` | 抛 `dawn.rt.PanicError`（Error 子类，故 `catch_fault` 不拦；只有隔离点 `catch_panic` 拦，见 §9.8） |

运行时支持类（`dawn/rt/Lists`、`Strings`、`Io`、`Show`、`Maps`、`Tuple*`、`Fn*` 等）
每个程序生成一份，被全部模块类共享。

### 12.3 native-image 契约

语言构造**保证**不产生：反射调用、自定义 indy bootstrap、动态类加载、
JNI（Java 互操作走普通 invoke）。因此 `--native` 构建不需要
reachability 配置。若引入的 Java 库自身用反射，责任在库——错误信息会提示
这超出 Dawn 的保证范围。

### 12.4 尾调用

**自递归尾调用保证**编译为循环（不长栈）——顶层函数与**局部命名函数**（§3.1）皆然。
互递归尾调用 v0.1 不保证。判定规则：函数体内对自身的调用处于尾位置（返回位置、
match/if 分支的尾位置、块的末表达式）。

---

## 13. 语法速查

```dawn
# ---- 声明 ----
use geo/shape.{Shape, area}
use java "java.nio.file.Files"

pub type Color = | Red | Green | Blue derive Show
type Point = { x: Float, y: Float }
alias Distance = Float           # 透明别名（§2.6）
const ORIGIN: Point = Point { x: 0.0, y: 0.0 }

pub fn dist(a: Point, b: Point) -> Float =
  sqrt(pow(a.x - b.x, 2.0) + pow(a.y - b.y, 2.0))

fn double(x: Int) = x * 2        # 私有函数可省返回类型（§3.1）

# ---- 表达式 ----
let n = 42                       var acc = 0
let (a, b) = pair                acc = acc + 1
if x > 0 { "pos" } else { "non-pos" }
match opt { Some(v) -> v, None -> fallback }
xs |> filter(fn(x) => x > 0) |> map(fn(x) => to_string(x)) |> join(", ")
xs[0]                            # 下标：越界 panic；问询用 get（§4.8）
read_file(path)?                 # Result 传播
if n < 0 { return "negative" }   # 提前返回（§4.9）
comptime { heavy_pure_calc() }   # 编译期求值

# ---- 块内局部函数（可递归，§3.1）----
fn sum(xs: List[Int]) -> Int = {
  fn go(i: Int, acc: Int) -> Int =
    if i == len(xs) { acc } else { go(i + 1, acc + xs[i]) }
  go(0, 0)
}

# ---- 测试 ----
test "dist is symmetric" {
  assert dist(p, q) == dist(q, p)
}
```

---

## 14. 未来方向（明确不在 v0.1）

按优先级：trait v2（条件 impl、泛型主体、supertrait、更多 derive）、
细分效果（`!fs`、`!net`）、互递归尾调用、
Dawn lambda 传给 Java、newtype、单态化优化、`Rune` 类型。
（`break`/`continue` 已于 2026-07 落地，见 §4.7。）
（trait v1——单参数 typeclass + 字典传递——已于 2026-07 落地，见 §3.5 与 trait.md。）
