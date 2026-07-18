# 纯 FFI：`unsafe_pure` 与 builtin→stdlib 迁移的地基

> 触发点：[`builtins-to-stdlib.md`](builtins-to-stdlib.md) 想把 71 个 builtin 搬进 `std/*.dawn`，
> 但实测发现它的前提错了——**在现有效果系统下，写不出一个纯的 FFI 包装函数**。本文补上那个
> 缺失的地基（纯 FFI），并给出 `unsafe_pure` 的设计与整条迁移的实施计划。
>
> **状态（2026-07-18）**：**阶段1 已实现并全绿**——`unsafe_pure` 表达式块落地（lexer/AST/parser/
> checker 效果屏蔽 + 拒效果变量 + 多余 lint / codegen 透明 / formatter / 补 7 测），全量
> 1187 测试通过，spec §6.4 已改写。**阶段2（std 打包）、阶段3（comptime route C）、阶段4（71
> builtin 迁移）未动工**——见 §四实施计划的勾选状态。

## 一、结论（TL;DR）

- **迁移的真前提不是「bundle std 源」，而是「纯 FFI」**：`builtins-to-stdlib.md` §6 假设
  `pub fn map = Lists.map(...)` 是纯函数——**不成立**。检查器把**每个** Java 调用判 `!io`
  （`Checker.kt:1421`），而纯函数体含 `!io` 是编译错误（`Checker.kt:2069`）。故 FFI 转发写出来的
  stdlib 函数是 `!io`，会击穿所有纯调用者、也进不了 comptime。
- **今天的纯 builtin 是「编译器钦定纯」**：`FnSig(..., Eff.Pure, isBuiltin=true)` 手写断言，
  Java 调用埋在 Kotlin/ASM codegen 里、效果检查器看不见。**这张 builtin 表就是 Dawn 的
  「纯度认证 FFI 边界」——待在编译器里正是它们能为纯的原因。**
- **纯 FFI = 把盖章权从「闭集、编译器内」下放到「开放、面向用户」**：一个具名的 `unsafe`
  逃生阀，作者担保某个 Java 调用纯、类型系统信之。
- **语法：`unsafe_pure { <expr> }`**，表达式块，形态照抄 `comptime { }`。只改**效果**
  （`Io → Pure`），不放松类型检查；**拒绝屏蔽效果变量**（高阶函数因此写不出 `unsafe_pure` 版，
  被逼走正道）；带刺的命名（`unsafe_pure` 而非 `pure`）让写的人知道自己在盖 unsafe 章。
- **两层结构**：`unsafe_pure` 只出现在**最底层一阶原语**（`String.substring`、`List.get`）；
  高阶函数（`map`/`filter`/`fold`）用**纯 Dawn 递归 over 这些 pure-vouched 原语**重写，效果多态
  自动正确。于是 `grep unsafe_pure` 出来的就是**完整的信任清单**，且都是一眼可判纯的东西。
- **comptime 折叠复活（route C）**：`unsafe_pure` 块同时是「此 Java 调用允许在编译期跑」的许可证。
  解释器对块内 Java 调用**反射执行**，`substring`/`map` 迁走后 comptime 折叠自动恢复，**「纯 ⟺ 可
  comptime」不但没坏、还扩展到了用户 FFI**（今天用户写 `fn hex(n)=Integer.toHexString(n)` 在
  comptime 里根本跑不了）。

## 二、根因（已核实，勿再凭印象）

| 事实 | 位置 | 含义 |
|---|---|---|
| 每个 Java 互操作调用记 `Eff.Io` | `Checker.kt:1421` `recordEffect(Eff.Io, …)` | Java 一律 `!io`，无论实际纯否——保守但可靠 |
| 纯函数体含 `!io` → 编译错误 | `Checker.kt:2069` | 故 `pub fn substring = s.substring(…)`（纯）编不过 |
| 函数效果 = 体内记录效果的 LUB | `Checker.kt:413`/`2110` `usedEffects.fold(Pure){lubEff}` | `unsafe_pure` 要在此处「屏蔽」io |
| Java import 靠编译器 JVM 反射解析 | `Checker.kt:139` | route C 复用这套反射机制去 `invoke` |
| comptime `eval()` 无 Java 分支 → `missing function` | `Comptime.kt:293` | 故 FFI 函数今天进不了 comptime；route C 补这条 |
| 纯 builtin = `FnSig(Eff.Pure, isBuiltin)` + Kotlin 实现 | `Types.kt` builtins 表 / `Comptime.kt:334 callBuiltin` | 钦定纯的闭集，审计面 = 这张表 |

## 三、设计：`unsafe_pure { }`

### 3.1 形态与文法

表达式块，与 `comptime { }` 并列——零新语法范式，Parser 改动≈复制 comptime 那一支。

```
PrimaryExpr ::= … | 'comptime' Block | 'unsafe_pure' Block | …
Block       ::= '{' Stmt* Expr? '}'          # 值 = 尾表达式，同普通块 / comptime
```

新增：保留字 `unsafe_pure`、AST 节点 `UnsafePureExpr(body: Expr)`。

```dawn
# 一阶纯包装的迁移惯用法
pub fn substring(s: String, a: Int, b: Int) -> String = unsafe_pure { s.substring(a, b) }
pub fn sqrt(x: Float) -> Float                        = unsafe_pure { Math.sqrt(x) }
```

### 3.2 语义（只改效果）

```
Γ ⊢ e : τ ! ε        ε ⊆ {Pure, Io}          （关键：ε 不含效果变量）
──────────────────────────────────────────────────
Γ ⊢ unsafe_pure { e } : τ ! Pure
```

1. **类型照常检查，只把效果 `Io → Pure`**。重载消解、类型匹配一律不放松；被盖的只有**效果**这一维。
2. **拒绝屏蔽效果变量**（护栏，核心）。
   ```dawn
   pub fn map(xs, f) = unsafe_pure { Lists.map(xs, f) }
   # ❌ error: unsafe_pure cannot mask an effect variable !e — it only certifies concrete effects absent
   ```
   `Lists.map` 会调 `f`，`f` 效果多态 `!e`；盖成纯即撒谎，且 `f` 为 `!io` 时值都定不下来。
   **它只能盖具体 `Io`，盖不了多态** → 高阶函数写不出 `unsafe_pure` 版，被逼走 §3.3 正道。
   这护栏是**免费的正确性**。
3. **盖块内一切具体 io，不分来源**（作者负全责，unsafe 的应有之义）。配 lint：
   **块内本就纯 → 报 `redundant unsafe_pure`**，保证每处 `unsafe_pure` 都是载荷性的，审计才有意义。

### 3.3 两层结构（高阶函数不碰 `unsafe_pure`）

```dawn
# 第 1 层：pure-vouched 原语 —— unsafe_pure 只出现在这里（少、集中、可审）
fn l_get(xs: List[T], i: Int) -> Option[T] = unsafe_pure { … xs.get(i) … }
fn l_size(xs: List[T]) -> Int              = unsafe_pure { xs.size() }

# 第 2 层：高阶函数，纯 Dawn 递归，零 unsafe_pure —— 效果多态自动正确
pub fn map(xs: List[T], f: fn(T) -> U !e) -> List[U] !e =
  … 递归调 f(l_get(xs, i)!) …        # f 的 !e 自然贯穿 → map 就是 !e
```

全仓的「不安全担保」收敛到第 1 层那一小撮原语；`grep -rn unsafe_pure` = 完整信任清单。

### 3.4 comptime 的双重身份（route C）

`unsafe_pure { }` 同时是**「此 Java 调用允许在编译期跑」的许可证**：

- 检查器在块内解析 Java 调用时把解析出的 `java.lang.reflect.Method` **挂到节点上**；
- 解释器遇 `unsafe_pure` 块 → 进去求值，块内 Java 调用**反射 `method.invoke`**（CValue↔JVM 值互转：
  `VString↔String`/`VInt↔Long`/`VList↔ArrayList`/`VBytes↔byte[]` 本就一一对应；其余对象加
  `VJavaOpaque` 兜底，stdlib 的域用不上）；
- 块**外**的 Java 调用永不到 comptime（它们 `!io`，进不了 const/pure 位置）。

> **附带责任**：`unsafe_pure` 只担保**纯**。若还要 comptime 它，等于额外担保**确定性 + 终止**
> ——别 vouch `System.currentTimeMillis` 再烧进常量池。

### 3.5 决策锁定

- **只做表达式块**，不做函数级修饰 `unsafe_pure fn`：块把不安全钉在最小区域、可精确 grep；
  函数级会把整个 body 都盖（混进真 io 也没了），更粗更危险。代价 = 一阶包装多写一层 `= unsafe_pure { … }`，可接受。
- **命名 `unsafe_pure`**（带刺）：招牌值钱，盖章者应当心虚。
- **route C 进 v1**：否则批 B（集合）要么卡住、要么留一堆 route-B 手写加速器 hack，不如一次做对。

## 四、实施计划（依赖排序）

```
阶段0  本文档（草案）✅ ——— 决策全部拍死
阶段1  unsafe_pure 语言特性 ✅ ——— 已实现全绿（1187 测试）
        Lexer/Token: UNSAFE_PURE 关键字 ✅
        Parser: UnsafePureExpr 节点 ✅
        Checker: 效果屏蔽（Io→Pure、拒效果变量、多余 lint）——核心正确性活 ✅
        Codegen: 透明（直接编内层表达式，运行期无标记）✅
        Formatter: token 级自然支持（补 fmt 测锁定）✅
        测试: 掩 io / 拒效果变量 / 纯函数 over vouched java 通过 / redundant / comptime 拒 ✅
        spec §6.4 改写（把计划中的 @trusted_pure 换成落地的 unsafe_pure）✅
阶段2  杠杆2 A/B  ⬜                   std 打进 jar 资源 + 隐式 use std（迁移函数的落脚处）
阶段3  comptime route C  ⬜           节点挂 Method + eval 反射分支 + VJavaOpaque 兜底
        （现状：unsafe_pure 块在 const/comptime 里报「route C 未实现」，不静默误折叠）
阶段4  迁移（一函数一原子：删 builtin FnSig ⟺ 加 std 定义）⬜
        批A  String/Bytes 一阶包装 → std/strings·bytes.dawn   【零 comptime 暴露，先搬】
        批B  list 原语 pure-vouch + map/filter/fold 纯 Dawn 递归 → std/list.dawn 【6 个 comptime 函数在此，需阶段3】
        批C  Map/Set + io 包装(print/read_file/args, !io) + 近核；杠杆1 to_string→Show trait 可并行
        每批: dawn 全测 + backend-dawn 三套契约对拍守回归 → builtin 表逐圈变瘦
收尾   builtin 表降到不可约核（① 4 个 intrinsic + 极少数必留）；更新 spec §11
```

- **阶段1 与阶段2 都是阶段4 的前提**，彼此独立可并行。
- **阶段3 需在批 B 之前**（批 A 零 comptime 暴露，可先于 route C）。
- 每阶段落地即绿、可回滚；任一批出问题停在上一批，编译器仍自洽。

## 五、迁移分类（71 个按机制分三类）

| 类 | 代表 | 迁移形态 | 效果 |
|---|---|---|---|
| **一阶纯包装** | `substring`/`str_len`/`split`/`to_lower`/`byte_at`/`sqrt`/`parse_int` | `pub fn f(…) = unsafe_pure { <java> }` | Pure |
| **高阶 / 效果多态** | `map`/`filter`/`fold`/`find`/`sort_by` | 纯 Dawn 递归 over pure-vouched 原语（**不用** unsafe_pure） | `!e` 多态 |
| **io 包装** | `print`/`println`/`read_line`/`read_file`/`write_file`/`args` | `pub fn f(…) -> … !io = <java>` | Io（不需 unsafe_pure） |
| **trait 化** | `to_string`/`len`/`==` | 杠杆1：Show/Len/Eq trait（与迁移并行） | — |

## 六、comptime 使用面（已审计，2026-07-18）

全仓显式 `comptime {}` 块调到的「将被迁移」函数**总共 6 个**：`map · range · filter · join · get · to_string`
（全是集合 + to_string）。要点：

- **backend-dawn（生产后端）comptime 用量 = 0** —— 迁移对生产无感，契约对拍不受影响。
- **② String 组 comptime 暴露 = 0** —— 批 A + 序6 落点 `std/strings.dawn` **零 comptime 风险**。
- 有暴露的 6 个都在批 B；route C（阶段3）覆盖后折叠自动复活。

## 七、不做 / 风险

- **soundness 洞**：`unsafe_pure` 是可撒谎的口子。缓解 = 具名可 grep + redundant lint + 两层结构把
  担保收敛到极少数一阶原语。不追求编译器验证 Java 纯度（做不到）。
- **性能**：集合迁出后多一层 `INVOKESTATIC`（std→runtime）；先以「正确 + 变薄」为目标，真有热点再
  标 `@inline` 或个别回收成 intrinsic（Rust intrinsic-behind-wrapper）。
- **不做函数级 `unsafe_pure fn`**（见 §3.5）。
- **不引入宏**；trait + prelude + 纯 FFI 已够。

## 八、对 [`seq6`](seq6-research.md) 的影响

序6 的 `char_at`/`char_next` 包 `String.codePointAt`/`Character.charCount`（Java → `!io`），而 JSON
lexer 是纯热路径，会被传染。故序6 的字符访问**必须纯**：本地基落地前它只能是 builtin；落地后 =
往 `std/strings.dawn` 加 `char_at = unsafe_pure { s.codePointAt(cur) }` 三行，顺带白拿 comptime 折叠。
**序6 挂起，等批 A。**

## 参考

- [`builtins-to-stdlib.md`](builtins-to-stdlib.md) —— 75→4 的动机与三层分类（§6 的「纯转发」前提由本文修正）
- [`cast-interop.md`](cast-interop.md) —— 同属 interop 人体工学的前一议题
- [`m6-retro.md`](m6-retro.md) —— 复盘（序6 的源头）
- `Checker.kt`（效果系统）、`Comptime.kt`（编译期解释器）、`Types.kt`（builtin 表）
