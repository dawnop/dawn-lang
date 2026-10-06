# 字面量系统设计 —— 无类型数字字面量、`FromInt`/`FromFloat`

> 状态：**current** —— 刀 L1（2026-10-06）落地：两个 prelude trait、字面量按期望定型、二元运算的字面量让步与混合种类规则、
> 调用实参在两轮推断之间检查等待中的字面量、纯 impl 的编译期折叠与它的报错措辞、折叠缓存。权威条文在 [spec.md](spec.md) §1.5、§2.1、§3.5、§4.3。
> 与 [arith-operator-traits-design.md](arith-operator-traits-design.md)（运算符刀 1）同一个 release。
> 未做：L2（LSP 悬停显示字面量的定型与折叠值）、L3（tileir 的 `FromFloat[Tile[D]]`/`FromInt[Idx]`）、N1（`std/narrow` 的 impl）、
> N2（std 定宽整数），见 §8。std 里的 impl 都要等种子推进到本 release 之后（std 在自举 closure 里，种子不认识这两个 trait）。
> 前置阅读：[int-min-literal-design.md](int-min-literal-design.md)、[effect-params-design.md](effect-params-design.md) §9（关联效果默认值）。

## 1. 为什么

1. **数值原语只有 `Int`/`Float` 不是问题；问题是语言之外的数造不出来。** 一个库类型要成为「数」，要两件事：运算符能落到它的方法上
   （运算符刀 1），字面量能落到它的值上。后者此前是检查器里不看期望类型的三行：`2.0` 永远是 `Float`。
2. 真疼的地方：GPU kernel 的常量写法（`scripts/tile-golden/kernels.dawn` 里 `f_const(F64, 0.0)` 一百多处）、`std/narrow` 的前缀算术、
   二进制格式的手写掩码。都不是机器宽度的问题，是「库类型收不了字面量」。
3. **答案的形状**：编译器只拥有 `Int`/`Float`；定宽数是 std 的 opaque 类型，由运算符 trait 与本设计的字面量 trait 变成一等。
   这是 Lean 4（`UInt8` + `OfNat`）、Haskell（`Word8` + `Num`）、Kotlin 无符号（value class）的共同路线；Go/Zig 的无类型字面量规则给出
   「如何单向、无搜索地定型」。

非目标：新的编译器数值原语、字面量后缀、无类型具名常量、任意精度常量算术、字符串与列表字面量重载、`Map`/`Set` 字面量、
异构运算 `Tile * Float`、隐式加宽。理由见 §9。

## 2. 裁决

### D1 数值类型：编译器原语保持两个（N0+）

`Int`（i64，环绕）与 `Float`（double）仍是唯一由编译器拥有的数。定宽类型（`I8..I32`、`U8..U32`、`U64`，以及现有的 `BF16/FP16/F32`）
是 std 的 opaque 类型，回绕语义同 `Int`（刀 N2）。否决一等定宽原语（N1）：两后端逐宽度展开、`Ty` 新变体波及上百处、comptime 值、
装箱、std N×N 转换，而它唯一独有的收益（密集存储）在 Dawn 今天的容器里不存在。重开条件：定宽密集容器进入路线图，或刀 N2 后实测
sha2/inflate 用 std `U32` 比 `Int + MASK` 慢 2 倍以上且 `-flto` 补不回来。

### D2 字面量是无类型的；定型看期望类型

**字面量原子**：整数字面量、浮点字面量、直接跟在一元 `-` 后的二者之一（括号在语法树里不留痕，括住的也算）。`'a'`、`true`、字符串不在内。

| 期望 `E` | 整数原子 `n` | 浮点原子 `x` |
|---|---|---|
| 无 / 未定的类型变量 / 不是字面量目标 | `Int` | `Float` |
| `Int` | `Int` | `Float`（交给随后的核对报错，原文不变） |
| `Float` | `Float`，值 `to_float(n)`，**须精确**（D6） | `Float` |
| 当前模块看不穿的类型 `T`，有 `FromInt[T]` | `from_int(n)` at `T` | 有 `FromFloat[T]` 则 `from_float(x)`，否则默认 |
| 同上，有 `FromFloat[T]` 无 `FromInt[T]` | 默认 `Int`（整数原子不经 `FromFloat`） | `from_float(x)` |
| 刚性类型参数，`[T: FromInt]`/`[T: FromFloat]` | 经字典调用 | 经字典调用 |
| 声明模块里看得穿的 opaque | 按目标类型递归本表 | 同左 |

- **单向**：字面量从不把自己的类型推给任何东西。没有推断变量、没有 defaulting、没有回溯。「默认」不是推断出来的，是「没有可用期望」那一行。
- 看不穿的 opaque **不回退到目标**：用 `has_impl_at` 判，不用 `resolve_witness` 的 opaque 回退（那段会让每个 opaque-over-Int 都「有」`FromInt`）。
- 否决 Haskell/Lean 形（字面量是受约束的推断变量 + default instance）：这就是 Swift 推断爆炸的放大器之一，Dawn 是局部检查器。
- 否决后缀（`255u8`）：N0+ 下后缀要让词法认识库类型名，且与上下文定型重复。

### D3 不做无类型具名常量与常量算术

`const X: Float = 0.5` 照旧有类型；`s * X`（`s: Tile[F64]`）照旧不成立，写 `s * lit(X)`。字面量原子之上的复合表达式（`2 * 3`）不是无类型常量，
是普通运算，期望怎么进入它们由 D5 决定。否决 Go 的无类型具名常量与任意精度常量算术：`const` 会有第二种语义，编译器要自带大数，而且
`int-min-literal-design.md` 的纪律要求字面量先是 64 位词法值。

### D4 `FromInt` / `FromFloat`：两个 prelude trait，各带同名关联效果

```dawn
trait FromInt[T]   { effect FromInt = !()    fn from_int(n: Int) -> T !T.FromInt }
trait FromFloat[T] { effect FromFloat = !()  fn from_float(x: Float) -> T !T.FromFloat }
```

- id 13、14，接在运算符的 7–12 之后；tvar -29、-30。`injects: false`：用户不能按名调用 `from_int`，字面量是唯一入口。
- **语义定义**：在 `T` 处定型的字面量 `n` **就是** `from_int(n)` 在 `T` 的 impl 下的值。D9 的编译期折叠是这个定义上的实现保证，不是第二种语义。
- 语言提供 `FromInt[Int]`（恒等）、`FromInt[Float]`（精确转换，否则 panic，判据同 D6）、`FromFloat[Float]`（恒等）；**不给** `FromFloat[Int]`。
  它们只在泛型字典路径上出现（`[T: FromInt]` 实例化到 `Int`/`Float`），具体 `Int`/`Float` 期望走 D2 表的前三行，不经 trait。
  `FromInt[Float]` 的槽位降成 `to_float` 加一次核对（低于 2^63 且 `to_int` 回得来），不精确就 panic「an integer literal is not exactly a Float」，
  否则 `seven[Float]()` 一类的泛型路径会对 `2^53 + 1` 静默舍入，而同一个字面量直接写在 `Float` 处是编译错误。
- 两个 trait 而不是一个 `FromNumber`：有的类型只该收整数（`Idx`、`U8`），有的只该收浮点（`BF16`）。整数原子不经 `FromFloat` 回退：一条回退链是一条隐式规则。
- 主体只在返回位：编译器按已知的 `T` 直接 `resolve_witness`，不经实参推断，所以 spec §3.5「类型参数只出现在投影里的方法按名字不可调用」不构成阻碍
  （L0 P1 实测：`[T: FromInt]` 的 `WForward` 在 `Int`/`Float`/用户类型实例化下两后端一致）。
- `make_prim_slot` 只需运算符刀 1 那处证据形参补丁；`prim_param_ty` 给两个 trait 答宿主类型，让 Core 上的类型如实。
- 否决把方法参数做成数字串（Scala `FromDigits`、Lean `OfScientific`）：要编译器把源文本交给库、库再解析；交值即可，代价是 D8 的两次舍入。

### D5 期望类型怎么到达字面量：三处，全部单向

1. **字面量臂**看 `expected`，按 D2（`check_num_lit`）。一元 `-` 直接跟字面量时整个 `-x` 是字面量原子，按 D2 一次定型（值取负后交给 `from_int`/`from_float`），
   不是字面量的 `-e` 照旧走 `check_unary` 与运算符的 `Neg`。
2. **二元运算的字面量让步**（`check_binary_expr`，适用于 `+ - * / %`、比较、`==`/`!=`；按位与移位只有 `Int`，不适用）：
   - 恰一侧是字面量原子：先检查**另一侧**（无期望），再以它的类型为期望检查字面量侧；两侧仍按书写位置交给 `check_binary_typed` 或运算符的 `arith_call`。
     「右侧以左类型为期望」只在左侧**不是**字面量原子时成立（否则 `2.0 + 1` 合法而 `1 + 2.0` 不合法）。
   - 两侧都是字面量原子：节点自己的期望**只在它是经 impl 收字面量的类型时**给两侧（`let b: U8 = 200 + 100`）；否则若两侧种类不同，**整数原子取 `Float`**（裁决第 3 条的混合规则，
     与 D5.3 的「`Float` 优先」同一条：`3.14159 * 2 * r`、`1 + 2.0` 因此成立；不精确的整数原子按 D6 报错，不舍入）；同种类各取默认（`1 / 2` 仍是 `Int` 的 `0`）。
     反向不成立：浮点字面量永远不进整数类型。
   - **`Float` 期望不穿过运算符**（10-06 裁决）：整数字面量只在两处取 `Float`，一是裸字面量在 `Float` 期望下（`let f: Float = 1`，须精确），
     二是上一条的混合规则或单侧让步挨着一个 `Float` 操作数（`let x: Float = 2 * r`）。所以 `let f: Float = 1 / 2` 里的 `1 / 2` 是 `Int`，
     绑定报「annotated type is Float but the initializer is Int」+ hint「write `1.0 / 2.0`」。理由：同一段文字随注解在 0 与 0.5 之间变，
     就是算术语义依赖上下文；Go（得 0）与 Rust（拒绝）都避开了它。
     **不对称，写死**：库类型的期望照样穿过运算符流到两侧字面量（`let b: U8 = 200 + 100`），因为那里的字面量没有别的种类可退，
     不流就只能报错；`Float` 期望下的整数字面量有自己的默认（`Int`），流过去就改了运算本身的语义（整除变除法）。
   - 都不是字面量：运算符设计 D6 原样（左无期望，右以左为期望当左不是数）。
   - **检查顺序 ≠ 求值顺序**：TAST 节点的左右位置不变，求值仍从左到右（L0 实测：`0.5 * s` 的记录先 `lit` 后 `mul`）。
   - 这是 Go 的二元运算规则，不是运算符设计否决的「右锚回填」：回填是先查左、失败再重查；这里在检查之前从语法认出字面量，一遍完成。`lit(2.0) * t` 仍不成立。
3. **调用实参在两轮之间**（裁决第 3 条修订的 D5.3）：实参是字面量原子、且对应形参（代入已知类型参数后）仍含未定类型参数时，第一轮跳过它；
   第一轮结束、第二轮开始**之前**按书写顺序检查这些字面量，**`Float` 原子先于整数原子**（Go 1.21 的「较大种类」：`g(1, 2.5)` 是 `g` at `Float`）。
   此时形参已定则以之为期望，仍未定则取默认。构造器实参（`infer_ctor_args`）同此。Java 实参不变（`check_java_call` 一律无期望）。
   **不能**推进第二轮：第二轮里靠期望才能定型的实参（`map.empty()`、泛型函数值 `ident`）今天正是靠第一轮的字面量定下类型参数；L0 实测草稿那种写法让
   selfhost 自身四处 `map.insert(map.empty(), 7, ..)` 与 `apply(1, ident)` 编不过。

### D6 可表示性：编译期，按类型分档

| 情形 | 规则 | 诊断 |
|---|---|---|
| `let f: Float = 1` | 合法：`|n| ≤ 2^53`，或 `n` 恰为某个 double | — |
| `let f: Float = 9007199254740993` | 编译错误 | `` the integer literal `9007199254740993` is not exactly a Float `` + hint `write it as a Float literal (9.007199254740992E15) if the nearest Float is meant` |
| `let n: Int = 1.5` | 原文不变 | `… declares return type Int but its body is Float` 一类 |
| `let b: U8 = 300`（纯 impl） | 编译错误：D9 折叠时 `from_int` panic | `` the literal `300` cannot be a `U8`: out of range for U8: 300 at src/u8.dawn:7:27 ``，位置在字面量 |
| `let b: U8 = -1` | 同上（`-1` 是字面量原子） | 同上 |
| 带效果的 impl（`Tile`） | 不折叠；运行期 panic 照 impl | — |
| `Int` 字面量越 2^63 | 词法错误，原文不变 | — |

- 判据在**库里**：`U8` 的范围是它的 `from_int` 写的，编译器不知道 255；编译器只提供「纯 impl 的 panic 在编译期浮出」这一个机制。
- 整数字面量进 `Float` 是 Go/Zig/Swift 的选择；精确性要求是 Zig 的，比 Go（静默舍入）严。
- `-0` 在 `Float` 期望下是 `+0.0`（先在整数上取负再转换，Go 同）；负零写 `-0.0`。`-9223372036854775808` 在 `Float` 处精确（-2^63）。

### D7 声明模块内：opaque 照旧按目标定型

看得穿 `T` 的模块里，期望 `T` 先剥到目标再走 D2（`let x: U8 = 300` 在声明模块里仍是 `Int` 300）。理由：一，**字节不变**，这类程序此前就合法、出 `CInt`；
二，**避免递归折叠**，`from_int` 的体里若写 `let z: U8 = 0` 就会去折叠 `from_int(0)` 本身；三，与 spec §2.7 一致，声明模块是建立不变量的地方。
代价写死：同一行 `let x: U8 = 300` 在声明模块内合法、模块外报错，这与 `let x: U8 = some_int` 一直以来的表现相同。

### D8 浮点字面量到窄格式：先成 `Float`，再 `from_float`

`let w: BF16 = 0.1` 的值**定义为** `from_float(0.1)`，`0.1` 是词法给出的 double，所以与 `bf16(0.1)` 逐位相同。十七位以上有效数字、恰落在窄格式中点上的
字面量会与「十进制直接舍入」差一个 ulp。否决保留源文本 + 编译器内十进制直接舍入：要在 AST 加字段、在编译器里做大数，只为十七位以上的字面量。

### D9 纯 impl 编译期折叠；带效果 impl 是运行期调用

- 检查器把落在非内建类型上的字面量产成 `XComptime(XCallFn(None, "from_int", [XInt(n)], [w], [], Some(FROM_INT_ID), …), lo, hi, T)`，
  **当且仅当**见证具体（`WConcrete`/`WApply`）且 impl 的关联效果归约为 `!()`。折叠沿用 const/comptime 的唯一管道（`CComptime`，解释器跑 impl 方法），
  opaque 与记录结果都成常量（L0 实测 `INT64_C(200)`、`ldc2_w 200`）。
- **前置修复（#563，已先行合入）**：解释器按需降级的函数里的 comptime 节点降成其体。否则 const 调到含折叠字面量的函数会报
  「a nested comptime block did not fold」，跨文件同偏移的块还会静默取错值。
- panic 在折叠边界成为诊断，位置取字面量。**不需要来源标记**：`from_int`/`from_float` 不注入，源码写不出对它们的调用，所以「comptime 体恰是 `trait_id`
  为二者之一的 `XCallFn`」就是来源；改写在 `interp.dawn` 的 `eval_block` 出错臂（`lit_fold_diag`），TAST 与 Core 都不加字段。
- **折叠缓存**：按（trait、实例化类型 `ty_key_inst`、值）缓存在 `LowerCache.lits`，失败不缓存（每个越界字面量各报一次）。`Float` 值以其渲染为键，
  它区分 `-0.0` 与 `0.0`，字面量不会是 NaN。L0 实测每个折叠约 65–80 µs（一次降级 + 一次解释），一万个重复值的 `U8` 字面量：不缓存 2.45 s、缓存 1.76 s、
  不折叠 1.65 s（同一机器）。
- impl 带效果（tileir 的 `!Dev`）或见证是 `WForward`（刚性 `T`）：普通 `XCallFn`，`reduce_eff` → `named_evidence_args` → `record_effect`，效果记在字面量的 span。
  与运算符同一条界线：效果必出现在外层签名里，不为字面量另设「必须纯」的特例。
- 例外，必须纯的位置：`const` 与 `comptime`（检查器的 isolated 帧）。带效果或未知的 impl 在这里报
  `` a literal at `Traced` needs a pure `FromInt` impl here ``，而不是 const 纯度检查那句提到用户从没写过的 `from_int`。
- 否决「一律运行期调用」（Lean/Swift 形）：那样 `let b: U8 = 300` 是运行期 panic，丢掉 Go/Rust/Swift/Zig 共有的编译期范围检查。
  否决「编译器知道每个定宽类型的范围」：那就是 N1 的一部分。

### D10 模式

字面量模式本刀**不变**（spec §5.1 原样）：被检者是 `Float` 时的整数字面量模式、被检者是看不穿的 opaque 时的折叠模式，都留到有消费者时再做
（见 §8）。理由：模式里的字面量降成目标上的相等测试，只有在 `T` 的相等就是目标相等、impl 纯时才与 `==` 一致，判据要多写一套；而首批消费者
（tileir、`std/narrow`）都不在模式里写字面量。`b == 0`（`b: U8`）与 `0 == b` 已经由 D5.2 定型成常量后走 `Eq`。

### D11 诊断

| 情形 | 此前 | 现在 |
|---|---|---|
| `let s: String = 1` | `… is String but … Int` | **不变**（`String` 不是字面量目标，字面量取默认） |
| `let f: Float = 1`、`r * 2`、`2 * r`（`r: Float`） | 报错 | 合法 |
| `let f: Float = 9007199254740993` | `… Float … Int` | D6 专属 |
| `let b: U8 = 300`（模块外） | `… is U8 but … Int` | D6 专属（折叠 panic） |
| `t * 2`（`Tile` 只有 `FromFloat`） | `both sides must have the same type: Tile[F64] vs Int` | 同句，落在字面量上 + hint ``` `Tile[F64]` takes Float literals: write `2.0` ``` |
| `2 * t` | 同上（span 在运算符） | 同上，span 改落在字面量 |
| `w + 1`、`1 + w`（`W` 有 `Add` 无 `FromInt`） | `both sides must have the same type` | 同句，落在字面量上 + hint「there are no implicit conversions; a literal becomes `W` only through `impl FromInt[W]`, written in the module declaring it」 |
| `1 + 2.0`、`3.14159 * 2 * r` | `Int vs Float` | 合法（混合种类） |
| `fn mixed() -> Int = 1 + 1.5` | `both sides … Int vs Float` | `function `mixed` declares return type Int but its body is Float` |
| `1 / 2 * x`（`x: Float`） | `Int vs Float` | **不变**（`1 / 2` 同种类取 `Int`） |
| `let f: Float = 1 / 2` | `annotated type is Float but the initializer is Int` | 同句 + hint ``a Float expectation does not reach the integer literals inside an operator; write `1.0 / 2.0` ``（`Float` 期望不穿过运算符） |
| `let x: Float = 2 * r`（`r: Float`） | `Int vs Float` | 合法（单侧让步） |
| `g(1, s)`，`fn g[T](a: T, b: T)`，`s: String` | 报在 `s` | 报在 `1`（等待的字面量在 `s` 定下 `T` 之后检查） |
| `g(1, 2.5)` | 报在 `2.5` | 合法，`T = Float` |
| `const K: Traced = 3`（impl 带效果） | `… is Traced but … Int` | D9 那句 |
| `lit(2.0) * t`，节点期望是 `Tile[F64]`（返回类型或注解） | `cannot infer type parameter(s) D for `lit`` | 合法：节点期望是走 trait 的库类型时下传给左操作数（运算符设计 D7，C0 刀）；无期望时同句不变 |
| `from_int(3)` | `undefined function` | 不变（不注入） |

所有变化都是**原本报错**的程序：要么变合法，要么换文字。checker-corpus 新增 `literals`、`literal_folds`、`literal_float_ops` 三例钉住；`arith_ops`、`binary_ops` 两例的 golden 随之重录。

### D12 tileir 的 `lit`：保留，成为 `FromFloat[Tile[D]]` 的体（刀 L3）

非字面量的宿主 `Float`（具名常量、宿主循环变量）进 kernel 仍要 `lit`。刀 L3 加 `impl[D] FromFloat[Tile[D]] { effect FromFloat = !Dev  fn from_float(x) = lit(x) }`
与 `impl FromInt[Idx]`；`FromInt[Tile[D]]` 暂不给，所以 `t * 2` 报上表那句、写 `t * 2.0`。判词：tile-golden 逐字节零变化。

### D13 std 定宽整数（刀 N2）的语义

表示 `pub opaque type U8 = Int` 等，不变量「值在该类型的范围内」（`U64` 无不变量，按位解释）；算术环绕，与 `Int` 一致；`/`、`%` 除零 panic；
无符号的 `<` 必须给自己的 `Ord` impl（否则 `U64` 按有符号比，静默错）；转换 `of`/`wrap`/`to_int`；按位先给具名函数，运算符形式等按位 trait 立项。刀前必测
sha256 用 `U32` 对比 `Int + MASK` 的两后端吞吐。

## 3. 改动位置

| 文件 | 改动 |
|---|---|
| `check/types.dawn` | `FROM_INT_ID`/`FROM_FLOAT_ID`、`lit_trait`、`prelude_trait_ids`、三个 prelude impl、「prelude shapes」测试 |
| `check/checker.dawn` | `check_num_lit`/`lit_target`/`lit_via_trait`/`is_lit_atom`；`check_binary_expr` 的让步与混合规则；`lit_waits`/`first_pending_lit` 与构造器同形；字面量不符的落点与 hint；NL1 内联测试 |
| `ir/lower.dawn` | `prim_relation` 的两条臂与 `exact_to_float`；`prim_param_ty`/`prim_ret_ty` |
| `ir/interp.dawn` | `lit_fold_diag`、`LowerCache.lits` 折叠缓存 |
| `doc.dawn` | 两段 prelude 散文 |
| `scripts/checker-corpus`、`scripts/spike-native/literals` | 语料与两后端对拍 |

## 4. 证据（实测，2026-10-06）

见本刀提交信息与 `agent-handoff/arith-lit-stack-report-20261006.md`。要点：

- 字节不变：`selfhost-core-diff.sh` 对 main 只有改动的编译器模块变；emit 宽语料以 main 自建 jar 为 N−1 逐个相同；run-diff 全同。
- 负控 NL1（具体 `Int`/`Float` 期望也走 trait）：L0 实测折叠形让 core-diff 与 emit 红，但那是折叠的副作用；不折叠形（NL1c）在字节上不可见。所以 NL1 的红门是
  checker 内联测试「a literal at Int or Float is the literal it always was, and elsewhere its impl's call」，断言 `XInt`/`XFloat`/`XUnary(UNeg, XInt)` 的 TAST 形状。
- 预期的 Emit-Change：`lsp`（补全回复多 `FromInt`/`FromFloat`）。

## 5. 测试

- `spike-native/literals`（项目）：模块外的 `U8` 折叠成常量（含 `const` 与 const 调到的函数里的折叠字面量），模块内照旧是 `Int`；`let f: Float = 1`、
  `3.14159 * 2 * r`、`1 + 2.0`、`r * 3`、`3 * r`、`half(3)`、`1 / 2`；`g(1, 2.5)`/`g(2.5, 1)`；`[1.5, 2]`；`-0` 与 `1.0 / ff`；`[T: FromInt]` 下的 `0` 在
  `Int`/`Float`/`U8` 实例化；`sum[T: Add + FromInt]` 用 `fold(xs, 0, …)`；带 `!Log` 的 `FromInt` impl 运行期调用。两后端对 `.expect` 一致。
- checker 内联测试（NL1 红门）；`types` 的「prelude shapes」。
- checker-corpus：D11 的报错行。
- 手测（报告里有）：泛型 `FromInt[Float]` 槽位对 `9007199254740993` 两后端都 panic，对 `9007199254740992` 正常。

## 6. 编译期成本

每个字面量多一次期望判断；`Int`/`Float` 期望不经 trait。折叠成本与缓存见 D9。

## 7. 与运算符设计相交处

- 运算符设计的 D7（字面量单态）由本文取代：字面量按期望定型，恰一侧是字面量时向另一侧让步，`t * 0.5` 与 `0.5 * t` 在 `Tile` 有 `FromFloat` 时都成立。
  **左锚定的不对称对非字面量只收窄一步**（C0 刀，2026-10-06）：仍不做右回填，但运算符节点自己的期望是走 trait 的库类型时下传给左操作数，
  `lit(2.0) * t` 在期望 `Tile[F64]` 下成立；`Int`/`Float` 期望不下传，`let f: Float = 1 / 2` 照旧报错。理由与边界见运算符设计 D7。
- 运算符设计的 D10（不给 `Zero`）：`[T: FromInt]` 下的 `0` 就是零，`var n: T = 0`、`n = n + 1` 都成立。没有 `FromInt` 的主体照旧显式传单位元。

## 8. 刀序

| 刀 | 内容 | 状态 |
|---|---|---|
| L0 | 探针 | 完成（`chore/literal-probes`，只入报告） |
| L0′ | #563 comptime 块键 | 完成（先行合入） |
| L1 | 本文 | 完成 |
| 1′ | 发 release N（与运算符刀 1 同一个），推进种子 | 待做 |
| L2 | LSP：字面量悬停显示定型结果与折叠值（`lspeval` 读折叠表）；`EUnary(-, 字面量)` 与 `XComptime` 配对 | 待做 |
| L3 | tileir：`FromFloat[Tile[D]]`、`FromInt[Idx]`（与运算符刀 3 同批） | 待种子 |
| N1 | `std/narrow`：`FromFloat[BF16/FP16/F32]` | 待种子 |
| N2 | std 定宽整数（D13） | 待 N1 与实测 |
| N3 | 按位 trait（独立设计） | — |
| — | 模式里的字面量（D10） | 有消费者时 |

## 9. 不做的（理由）

1. **新的编译器数值原语**：D1；重开条件写在 D1。
2. **字面量后缀**（`255u8`、`1.0f32`）：与上下文定型重复，N0+ 下还要让词法认识库类型名。
3. **无类型具名常量**（Go `const x = 0.5` 到使用处定型）：`const` 会有两种语义，且要编译器自带大数。
4. **任意精度常量算术**：同上；`int-min-literal-design.md` 的纪律。
5. **字面量作为推断变量 + defaulting**（Haskell/Lean/Swift）：Dawn 是局部检查器，这一步就是 Swift 的放大器。
6. **一般的右锚回填**（无期望时由右操作数定左操作数类型）：运算符设计 D7 原判，仍不做；本设计只为语法上可识别的字面量让步。有库类型期望时的 `lit(2.0) * t` 已由 C0 刀的左操作数期望解决，不是回填。
7. **整数字面量经 `FromFloat` 回退**：回退链是隐式规则，类型作者自己写 `FromInt`。
8. **浮点字面量进整数类型**（Zig 允许无小数部分的 `2.0` 进整数）：同一个值两种拼写，Dawn 只要一种；混合规则也只让整数原子取 `Float`。
9. **字面量推进第二轮**（草稿原文的 D5.3）：会让今天能编译的程序编不过（L0 §4.1），改为两轮之间。
10. **十进制直接舍入到窄格式**：D8；要源文本与大数，只为十七位以上的字面量。
11. **字符串与列表字面量重载**：没有消费者在等；同形机制留给将来。
12. **`Map`/`Set` 字面量语法**：集合字面量问题，另立项。
13. **编译器内置定宽类型的范围知识**：D9；范围由库陈述。
14. **定宽整数的陷阱语义**：D13；`Int` 已经写死环绕，同族两种溢出语义会让读者每次都要查。检查用 `checked_*`。
15. **`Char` 接收整数字面量**：`'a'` 已是字符字面量，`char.of(n)` 仍是唯一从码点造字符的路。
16. **废弃 tileir `lit`**：非字面量的宿主值仍需要它。
17. **本刀做模式里的字面量**：D10，判据多一套而首批消费者用不到。
