# 纯 FFI：`unsafe_pure` 与 builtin→stdlib 迁移的地基

> 触发点：[`builtins-to-stdlib.md`](builtins-to-stdlib.md) 想把 71 个 builtin 搬进 `std/*.dawn`，
> 但实测发现它的前提错了——**在现有效果系统下，写不出一个纯的 FFI 包装函数**。本文补上那个
> 缺失的地基（纯 FFI），并给出 `unsafe_pure` 的设计与整条迁移的实施计划。
>
> **状态（2026-07-18）**：**阶段1 + 阶段2 已实现并全绿（1197 测试，含 §9.2 spike）**。
> 阶段1 = `unsafe_pure` 表达式块（效果屏蔽 / 拒效果变量 / 多余 lint / codegen 透明），spec §6.4 已改写；
> 阶段2 = std 打进 jar 资源 + 隐式可见 + 类随 shared 一起出（`dawn run`/`dawn build` 实测链得上）。
> **阶段3 已实现**（route C = 反射执行被担保的 Java 调用 + Comptime 接上 std），**阶段4 已开工**
> （批 A 首枪 `substring`，§十）。于是「纯 ⟺ 可 comptime 折叠」在迁移中得以保持，String 组余下的
> 不再被 comptime 阻塞。

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
阶段2  杠杆2 A/B ✅ ——— 已实现全绿（1195 测试）
        A: std/*.dawn 打进 jar 资源 + StdLib 一次性解析/检查（bootstrap 不递归）✅
        B: 隐式可见（Checker 新增 std 层：local → std → builtin；std 名字不可重定义）✅
        codegen: std 类随 emitShared 一起出，故单文件/多模块/dawn build 都自动链上 ✅
        实测: dawn run、dawn build 产物 jar 内含 std/strings.class 且可运行 ✅
阶段3  comptime route C ✅ ——— 已实现全绿（1202 测试）
        eval 的 MethodCall 分支反射 invoke 被 unsafe_pure 担保的调用（仅静态方法、
        仅 Int/Float/Bool/String/Unit 边界；越界即报错，不静默误折叠）✅
        Comptime 接上 std（此前 std 函数对解释器完全不可见，纯 Dawn 的也不行）✅
        std 体内的报错重定位到调用点（否则 caret 渲染到用户文件的错位置）✅
阶段4  迁移（一函数一原子：删 builtin FnSig ⟺ 加 std 定义）🔶  ← 批 A 首枪 substring 已落地（§十）；
        阶段3 落地后，String 组余下的不再分两拨
        批A  String/Bytes 一阶包装 → std/strings·bytes.dawn   【零 comptime 暴露，先搬】
        批B  list 原语 pure-vouch + map/filter/fold 纯 Dawn 递归 → std/list.dawn 【6 个 comptime 函数在此，需阶段3】
        批C  Map/Set + io 包装(print/read_file/args, !io) + 近核；杠杆1 to_string→Show trait 可并行
        每批: dawn 全测 + backend-dawn 三套契约对拍守回归 → builtin 表逐圈变瘦
收尾   builtin 表降到不可约核（① 4 个 intrinsic + 极少数必留）；更新 spec §11
```

- **阶段1 与阶段2 都是阶段4 的前提**，彼此独立可并行。
- **阶段3 已完成**：批 B 不再被它阻塞，String 组余下的也不必再分两拨。
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

## 九、实测推翻的迁移前提：std 够不着 Java（2026-07-18）

阶段2 落地后实测两条探针,**把 §三/§五 的迁移惯用法和 `builtins-to-stdlib.md` §6.2 D 一起推翻了**
——这是继「FFI 转发写不出纯函数」之后的**第二个错误前提**,同样是凭印象没验证。

| 探针 | 结果 | 含义 |
|---|---|---|
| `let s = "hello"` 后 `s.isEmpty()` | `error: undefined function: isEmpty` | Dawn 原生类型(String/List/Bytes/Map/Set)**不是 `TJava`**,收不了 Java 实例调用;`x.m()` 落回 UFCS |
| `use java "dawn.rt.Strings"` | `error: Java class not found` | `dawn/rt/*` 是 codegen 期 **ASM 现生成**的,不是检查期可反射的真类 |

**后果**:
- `pub fn substring(s, a, b) -> String = unsafe_pure { s.substring(a, b) }`(本文 §三/§五 的
  一阶包装惯用法)**今天根本编不过**——`s.substring` 解析不成 Java 调用。
- `builtins-to-stdlib.md` §6.2 D 说的「std 写 `use java "dawn.rt.Lists"` 转发运行时类、无鸡生蛋」
  **不成立**——那些运行时类检查期不存在。
- 故**批 A/B 按现设计写不出来**。`unsafe_pure` 本身没问题(阶段1 全绿),缺的是让它**够得着**
  Java 的那一步。

**三条出路**:

- **甲(建议) —— 让 Dawn 原生类型能收 Java 实例调用**。`TString` 运行期**就是** `java.lang.String`、
  `List` 就是 `java.util.List`,让 `x.m()` 在无 Dawn 函数匹配时回落成 Java 实例调用即可。最贴合既
  有设计:`unsafe_pure { s.substring(a, b) }` **原样成立**,批 A 立刻可写。需先定清楚:UFCS 与
  Java 实例调用的优先级次序、引用返回的 `Option` 包装如何与 §五 的签名对齐。
- **乙 —— 把 `dawn/rt/*` 从 ASM 生成改写成真 Kotlin 源类**,随编译器 jar 分发、检查期可反射,std
  即可 `use java` 转发。代价大:产物 jar 不再自包含(要么引入运行时依赖 jar,要么把这些类复制进产物)。
- **丙 —— 只迁「纯 Dawn 可表达」的**(本次 `std/strings.dawn` 的 `is_empty`/`repeat` 就是),其余留在
  builtin。能立刻做,但搬不动 String/集合主体,离「75→4」很远。

### 9.1 边界比想的窄(补测,2026-07-18)

再补几条探针后,「std 够不着 Java」这个说法要**收窄**——静态方向其实全通:

| 探针 | 结果 |
|---|---|
| `Integer.parseInt(s)`(Dawn String **传进** Java 静态) | ✅ |
| `String.valueOf(7).expect("v")`(Java 静态**返回** String) | ✅ |
| `Collections.max([3,1,2])`(Dawn List 传进 Java) | ✅ 调用成立(返回擦除为 `Object`) |
| `use java "dawn.check.StdLib"` / `"kotlin.text.StringsKt"` | ✅ **编译器 jar 自带的类可见** |
| `unsafe_pure { Integer.parseInt(s) }` 当纯函数,再被纯函数组合 | ✅ 跑通 |

所以**缺的不是「够不着 Java」,而是「缺一个检查期可反射的实现载体」**——现有实现恰好都在 ASM
现生成的 `dawn.rt` 里。既然编译器 jar 里的类 `use java` 看得见,**出路乙 的排序应提到最前**。

### 9.2 出路乙 已验证可行(spike,2026-07-18)

按「先验证后做」跑了一遍最小闭环:真 Java 类 `dawn.rt.StdStrings` → `std/strings.dawn` 用
`unsafe_pure` 转发 → `pad_start`/`reverse_str` 上线。**结论:乙 成立**,`dawn run` 与
`java -jar` 产物均正确(含 `··héllo` 这种码点级用例)。途中撞出**两个必须记住的坑**:

1. **产物不自包含**。真类住在编译器 jar 里,`dawn run` 因编译器在 classpath 上而正常,
   `java -jar` 直接 `NoClassDefFoundError: dawn/rt/StdStrings`。
   → 解法:codegen 把这些类的字节**从编译器 jar 复制进产物**(`CodeGen.vendorRuntimeClasses`,
   清单 `VENDORED_RT_CLASSES`)。已有测试守住这条不变量。
2. **实现类必须是 Java,不能是 Kotlin**。Kotlin 版一跑就
   `NoClassDefFoundError: kotlin/jvm/internal/Intrinsics`——Kotlin 类要拖 kotlin-stdlib,而这些
   字节会被复制进**每个** Dawn 产物。改写成纯 Java 后产物干净(实测 jar 内无任何 kotlin 类)。

> 故 `dawn.rt` 今后分两类:**ASM 现生成**的(产物免费获得、检查期不可见)与**Java 源编译**的
> (检查期可反射、需 vendoring)。std 只能转发后者。

**甲(原生值收实例调用)降级为可选的人体工学改进**,不再是批 A 的前置。

## 十、批 A 第一枪:`substring`(2026-07-18,已落地)

选它是因为它**在 comptime 里本就不可用**(实测 `const X = substring("hello",0,2)` 报
`builtin substring is not available at comptime`),故迁移不碰未动工的阶段3,回归面为零。
一个原子的完整形状:Java 侧加实现 → std 侧 `unsafe_pure` 转发 → 删 `Types.kt` 的 `FnSig` →
删 codegen 直接调用分支 → 删已成死码的 ASM 发射器 → 删 `Doc.kt` 的 builtin 描述。

沿途撞出**三条约束**,后续每一批都适用:

1. **迁走的函数不能自己 panic**。`dawn.rt.PanicError` 是 ASM 现生成的,真 Java 源类引用不到它。
   → 约定:Java 侧用**返回 `null` 表示失败**(检查器自动包成 `Option`),Dawn 侧
   `.expect("<原 panic 文本>")` 把它还原成同样的 panic。实测消息逐字一致,无需新机制。
2. **迁移会静默丢文档**。`dawn doc --builtins` 原本只读 builtin 表,函数一迁走就从参考里消失
   (`DocCmdTest` 也正是因此转红)。→ `builtinsJson()` 现在把 **std 也作为分组输出**
   (组名即模块名 `std/strings`,描述取 `##` 注释),站点零改动即渲染出来。此后参考面按「用户视角」
   而非「实现位置」组织,再迁多少个都不掉。
3. **codegen 有三个落点,不是一个**:直接调用分支、值形式 bridge(`genBuiltinBridge`,
   `substring` 恰好没有)、以及 `dawn/rt/Strings` 里的 ASM 发射器(删 builtin 后成死码)。
   漏删只会留下无人调用的字节,不报错——每批完事后 grep 一遍函数名确认三处都清了。

**回归证据**:编译器 1197 测试全绿;`backend-dawn`(30+ 处用 `substring`,含 JSON lexer / 路由 /
路径 / 七牛签名)用本编译器重编,63 测试全过、jar 内含 vendored `dawn/rt/StdStrings.class` 且
**零 kotlin 类**;码点语义(`substring("héllo🎈x",4,6)=="o🎈"`)与越界 panic 文本均与迁移前一致;
site 链接检查 408 条、`fmt --check`、ktlint 均绿。

**下一步**:见 §十一(阶段3)与 §十二(批 A 其余部分)。

## 十一、阶段3:route C 与 Comptime 接 std(2026-07-18,已落地)

做这一步的动机不是「route C 本身」,而是**不做就没法继续迁移**:`trim`/`split`/`parse_int` 这批在
comptime 里可用,迁走会让调用方的 `const` 折叠失效——那是实打实的功能倒退。做完之后
「纯 ⟺ 可 comptime 折叠」在迁移中得以保持,**调用方不必知道一个函数今天住在表里还是 std 里**。

实际动了**三处**,而不是计划里以为的一处:

1. **route C 本体**:`eval` 的 `MethodCall` 分支在 `isJava` 时反射 `invoke` 已挂在
   `MethodCall.javaMethod` 上的 `Method`。**故意做窄**——只在 `unsafe_pure` 内可达(块外的 Java 调用
   是 `!io`,本来就到不了 const)、只允许**静态方法**(comptime 造不出 Java 对象)、只跨
   `Int/Float/Bool/String/Unit` 边界,其余一律报错。`fromJava` 必须与 `Checker.mapJavaReturn` 一致
   (引用返回包 `Option`、`null` 即 `None`),否则折叠结果会和运行期不一样——这是本步最容易写错的地方。
2. **Comptime 接上 std**(阶段2 的遗留缺口,与 route C 无关):此前 `const Y = is_empty("")` 报
   `missing function is_empty`,**即便 `is_empty` 是纯 Dawn**——解释器只在用户模块里找函数。
   现在 `evalComptime` 多收一份 std 的 `FnDecl`,顺序同检查器(local 覆盖 std);std 自身受检时传空,
   bootstrap 仍不递归。顺带补了 `str_len` 的 comptime 实现(std 的 `is_empty` 建在它上面)。
3. **std 体内报错的定位**(接通 std 后才暴露):std 的 span 指向 `<std>/strings.dawn`,却被拿去
   渲染**用户的文件**,caret 落在第 9 行第 647 列这种不存在的位置。现在跨 std 调用的报错**重定位到
   调用点**,并加 hint 说明来自哪个 std 函数。于是 `const X = substring("abc", 0, 9)` 在**编译期**
   就报 `panicked: substring: index out of range`,文本与运行期 panic 逐字相同、caret 落在用户的表达式上。

> **附带责任没变**:`unsafe_pure` 只担保「纯」。要它在编译期跑,等于额外担保**确定性 + 终止**。
> 反射 invoke 一旦进去就打断不了,故按固定成本扣 fuel;别 vouch `currentTimeMillis` 再烧进常量池。

## 参考

- [`builtins-to-stdlib.md`](builtins-to-stdlib.md) —— 75→4 的动机与三层分类（§6 的「纯转发」前提由本文修正）
- [`cast-interop.md`](cast-interop.md) —— 同属 interop 人体工学的前一议题
- [`m6-retro.md`](m6-retro.md) —— 复盘（序6 的源头）
- `Checker.kt`（效果系统）、`Comptime.kt`（编译期解释器）、`Types.kt`（builtin 表）

## 十二、批 A 其余部分:String 组 10 个(2026-07-18,已落地)

阶段3 落地后,原先按「comptime 是否可用」划的分水岭消失了,改按**形状**划——这才是 route C 的
真实边界(只跨 `Int/Float/Bool/String/Unit`)。本批迁走 10 个**标量/String 形状**的:

`str_len` `trim` `to_lower` `to_upper` `contains` `starts_with` `ends_with`
`index_of` `last_index_of` `char_to_string`

**测试一条没改、1202 全绿**——迁移是行为保持的,这比新增测试更有说服力。另实测:
`trim`/`contains`/`starts_with`/`ends_with` 的 **const 折叠仍在**(阶段3 的直接兑现);
`str_len("héllo🎈")==6`、`index_of("héllo🎈x","x")==6` 证明码点下标未退化成 UTF-16;
`char_to_string` 的 panic 文本与**截断行为**(`char_to_string(2^32+65)=="A"`)都逐字保持。
回归靶:backend-dawn 这 10 个函数共 **130 处调用点**,重编后 63 测试全过。

**两点值得记的**:

1. **ADT 过不了 FFI 边界,用哨兵值换**。`index_of` 返回 `Option[Int]`,而 Java 侧没法返回 Dawn ADT。
   解法:Java 返回 `-1` 哨兵,std 侧 `if i < 0 { None } else { Some(i) }` 转回来。这层转换是**纯 Dawn**,
   所以照样可折叠。同理 `char_to_string` 用 `null`→`expect` 还原 panic(批 A 第 1 条约束)。
2. **落点其实有四类,不是三类**。批 A 只发现三处,这批又冒出第四处:**值形式的方法句柄**
   (`index_of` 在 `Handle(H_INVOKESTATIC, …)` 表里有一条,供把函数当值传时用)。
   完整清单:①直接调用分支 ②值形式 bridge(`genBuiltinBridge`) ③值形式方法句柄
   ④`dawn/rt/Strings` 的 ASM 发射器。**四处都不删也照样编译通过**——只是留死码,故每批必须 grep 核对。

**剩下没迁的 String 函数,以及为什么**:

| 函数 | 卡在哪 |
|---|---|
| `split` `join` `chars` `code_points` `from_code_points` | **List 形状**。route C 不能 marshal List,直接转发会**丢掉 const 折叠**(`split`/`join`/`chars` 今天可折叠)。正解不是扩 route C,而是按本文 §3.3 的两层结构,用**纯 Dawn 递归 over 已迁走的一阶原语**重写(`split` = `index_of` + `substring` 的循环),折叠自然保住 |
| `parse_int` `parse_float` | 返回 `Option`,且失败信息只有 Java 的异常。哨兵值不够用(任何 Int 都是合法结果),需 `can_parse` + `parse_or` 两个方法配合,或等一个更好的编码 |
| `to_string` | 属杠杆1(Show trait),不在本线 |

## 十三、批 B 的前提被实测推翻:List 累积是 O(n²)(2026-07-18)

按计划,下一步是用**纯 Dawn 递归 over 已迁走的一阶原语**重写 `split`/`join`/`chars`(§3.3 的两层结构),
作为批 B(集合)的预演。**预演失败了,而且失败的是批 B 的核心前提。**

**实测**(n=32000,`dawn build` 产物,`java -jar` 计时):

| | builtin | 纯 Dawn 重写 | 倍数 |
|---|---|---|---|
| `split` | 0.043s | 1.62s | ~38× |
| `map` | 0.034s | 1.49s | ~44× |

且是**超线性**的:纯 Dawn `map` 在 n = 8k/16k/32k/64k 上耗时 0.10 / 0.45 / 1.61 / 3.41 秒,
每翻一倍约 ×3.5–4.5。

**根因不是字符串,是列表累积。** 拆开量:32000 次纯列表累加 1.59s,32000 次字符串截断 0.52s——
前者就是全部开销。因为 `++` 编译成 `new ArrayList(a); addAll(b)`(`CodeGen.kt` 的 `Lists.concat`),
**整表复制、O(n)**,于是「每步 append 一个元素」的累积必然 O(n²)。

**这是个钳形,两边都锁死**:

- `map` **不能**做成 pure-vouched 的 Java 原语——它效果多态(`!e`),而 `unsafe_pure`
  **拒绝屏蔽效果变量**(§3.2 护栏)。那条护栏是对的,不该为性能拆掉。
- `map` 用纯 Dawn 递归写 —— 就是上表的 O(n²)。

故**批 B 不是「照计划写代码」就能推进的,它缺一个前置的数据结构决策**。与 `unsafe_pure`、
捆绑 std、route C 都无关——那三样都已验证可用,批 A 也正是靠它们完成的。

**顺带发现:这个坑今天就在坑用户。** 它不是迁移引入的——任何 Dawn 代码在循环里累积列表
(`acc ++ [x]`)都已经是 O(n²)。所以修它的价值独立于本次迁移。

**出路(推荐甲)**:

- **甲 —— 换掉 List 的底层表示**,给它 O(1) 的 cons/append(持久向量或 cons list)。
  spec §2.2 早已写明「v0.1 实现为 copy-on-write，后续可换持久数据结构而不动接口」,
  **接口不变、语义不变**,是有言在先的演进。修完批 B 的正道自然成立,且顺手修掉上面那个用户侧的坑。
- **乙 —— 集合核心永久留在 builtin 表**。`map`/`filter`/`fold` 本就因效果多态而永远不可能是
  `unsafe_pure` 转发,只有纯 Dawn 递归一条路;这条路慢,那就不搬。诚实,但与「75→4」的目标冲突。
- **丙 —— 加一个一阶的 builder 原语**。绕开效果多态,但本质是把甲的持久结构塞进一个函数背后,
  不如直接做甲。

**在甲拍板前,`split`/`join`/`chars`/`code_points`/`from_code_points` 维持 builtin**——
不为了「表变瘦」去换一个 38× 的回归。

## 十四、甲已落地:List 换表示,累积从 O(n²) 变 O(1) 摊还(2026-07-18)

按 §十三 的推荐做了**甲**。关键是发现它**可以增量做**:代码里到处走的是接口
`java/util/List`(110 处),`ArrayList` 只是实现(57 处)。所以引入一个实现了
`java.util.List` 的新表示,**传递路径一行都不用改**,只改构造点——实际改动就是
`Lists.concat` 一处委派。

**表示**(`compiler/src/main/java/dawn/rt/DawnList.java`,真 Java + vendored,同 §9.2 的两条约束):
一个版本是共享底层数组上的窗口 `a[0, size)`;`used` 记录该数组已发放的槽位。
**当且仅当本版本正好终止于共享水位时**(`size == used`)才能就地延长——这正是累积循环产生的
「线性、同一时刻只有一个所有者」的情形;对**旧版本**追加则复制,不可变性由此保住。
索引仍是数组直取 O(1),不牺牲随机访问。

**并发是真问题,不是理论洁癖。** backend-dawn 每请求一条虚拟线程,两个线程可能同时对同一个
列表追加。所以槽位区间**先 CAS 认领、后写入**:至多一个线程赢,输的走复制。可见性靠
final 字段的 freeze 语义(JLS 17.5)——写入发生在构造完成前,读者经 final 的 `a` 必然看得见。
若没有 CAS,两个线程会都写同一槽位、一方静默读到对方的元素;`DawnListTest` 里 8 线程 × 200 轮
的用例就是守这条的。

**实测(n=32000 起)**:

| | 改前 | 改后 |
|---|---|---|
| 纯 Dawn `map`(8k/16k/32k/64k) | 0.10 / 0.45 / 1.61 / 3.41 s | 0.07 / 0.03 / 0.04 / 0.05 s |
| 纯 Dawn `map` vs builtin | ~44× | ~1.5× |
| 20 万次累积 | 实际上跑不动 | **0.04 s** |

编译器 1208 测试绿;backend-dawn 用新编译器重编,63 测试全过。

**兑现了什么**:
- **用户侧的坑没了**——任何 Dawn 代码在循环里 `acc ++ [x]` 不再是二次的。这是独立于迁移的收益。
- **批 B 的列表那一半解锁了**:`map`/`filter`/`fold` 用纯 Dawn 递归写,现在只比 builtin 慢 ~1.5×,
  是可接受的迁移代价(§七 早就说「先正确+变薄,真有热点再回收成 intrinsic」)。

**没解锁的**:`split`/`chars` 这类**按码点下标扫字符串**的,仍有第二个二次项——
每步 `substring(s, i, str_len(s))` 复制剩余串,而且**码点下标 ↔ UTF-16 偏移的换算本身就是 O(n)**。
这不是列表问题,是「Dawn 的 String 按码点索引、底层却是 UTF-16」的老问题,属**序6** 的范围
(那边早已定位到「真缺口是 String 没有 `char_at`」)。故 `split`/`chars`/`code_points`/
`from_code_points` **继续留在 builtin**,等序6。

## 十五、批 B:高阶列表函数迁进 std(2026-07-18)

`map` `filter` `fold` `find` `take` `drop` `reverse` 七个迁入 `std/list.dawn`,**全部是纯 Dawn 递归**,
没有一处 `unsafe_pure`——也用不了:它们效果多态,而那个印章**拒绝屏蔽效果变量**。当初那条护栏
把高阶函数逼上这条路,现在这条路走通了,护栏的设计意图算是兑现了。

留在 builtin 的:`len`/`get`(直接摸表示,是不可约核)、`range`、`sort`/`sort_by`/`max`/`min`/
`max_by`/`min_by`(依赖 Ord 字典,另说)。**builtin 表 79 → 57,std 22。**

**这批依赖 §十四**:每个 helper 都是 `acc ++ [x]` 累积,旧表示下全部会是 O(n²)。先修表示再迁,顺序不能反。

沿途三件事:

1. **局部函数不能声明效果变量**(spec §3.1),所以累加器 helper 必须提到模块级私有函数。
   这不是绕路,是语言早就定好的规矩(「效果多态请提升到顶层」)。
2. **`StdLib.fnDecls` 漏了私有函数**。comptime 解释器要的是**函数体**不是公开面,而 std 的
   `map` 调私有的 `map_go` → `comptime: missing function map_go`。可见性在检查期已经管过了,
   解释期不该再管一次。
3. **comptime 深度:一个真实回归,已修**。以前 `map` 是 Kotlin 循环,现在是 Dawn 递归,而解释器
   是树遍历、每个 Dawn 调用吃十几个 JVM 栈帧 → **3000 元素的 comptime map 让编译器
   直接 `StackOverflowError` 崩溃**(不是报错,是崩)。修法:comptime 跑在**自带 64MB 栈的线程**上,
   深度上限抬到 100k,并把 `StackOverflowError` 接成带位置的诊断。`fuel` 仍是真正的总量护栏。
   **原则性的修法是解释器做尾调用优化**(codegen 早就做了,`map_go` 本来就是自尾递归),
   但那要把「尾位置」信息贯穿 eval,改动面大,记在这里。

> 顺带确认一个**不是**本次引入的限制:`const T = range(0, 50000)` 会 `MethodTooLargeException`
> ——大常量物化进 `<clinit>` 字节码超限,与 map 在哪无关(纯 builtin `range` 一样炸)。

**回归证据**:编译器 1208 测试绿(**一条测试都没改**);backend-dawn 重编 63 测试全过;
编译器自己的 site 生成器(重度用 map/filter/fold)产出 34 页、408 条链接全解析,3.7 秒。

## 十六、`split`/`chars` 与 Bytes 组:阻塞消失后的两批(2026-07-18)

### `split`/`chars`:§十四 判它们「等序6」的理由已经不存在

§十四 写「码点下标 ↔ UTF-16 换算本身就是 O(n),故留在 builtin,等序6」。**游标(§十五之后加入 std)
消掉的正是这条**。重写后语义与 builtin 逐条一致(含星际码点、空分隔符、空串、相邻分隔符),
**常量折叠保住**(纯 Dawn,解释器能跑),值形式(当函数值传)也通。

实测三组数,结论不是一句话能盖过去的:

| | builtin | 纯 Dawn | 4000 元素 | 真实规模(35 字符路径/6 段) |
|---|---|---|---|---|
| `split` | | | 4.0× | **1.9×**(0.42 µs/次) |
| `chars` | | | 4.5× | 3×(生产调用点 **0** 个) |
| `join` | | | 4.75× | **6.5×** |

**`join` 因此没有迁**,理由值得单独记:纯 Dawn 写它只有两个形状,而两个都坏——
朴素的 `acc ++ sep ++ x` 是二次的(4000 元素 211ms,53×);改成累加 `List[Int]` 再
`from_code_points` 是线性的,但**无论多小都要付两趟全扫**,真实规模下反而比朴素慢 14 倍。
**根因是 Dawn 没有 StringBuilder 这一级的原语**——这正是本文一贯的「标准库缺原语,调用方
只能写更慢的替代品」,只不过这次缺口在语言自己这一层。`join` 留在 builtin,直到那个原语出现。
（另:`join` 是 §六 审计出的 6 个 comptime 暴露之一，`examples/calc.dawn:102` 在用，
所以「转发给 Java 换线性」这条路也走不通——会丢折叠。）

### Bytes 组 6 个:批 A 欠的另一半

`utf8` `decode` `byte_len` `byte_at` `byte_slice` `byte_index_of` → `std/bytes.dawn`,
转发到新的源码编译类 `dawn.rt.StdBytes`。**`Bytes` 本来就能双向过 FFI 边界**
(`md.digest(utf8(s))` 早就在生产里跑),所以参数/返回类型不需要变通;需要变通的仍是结果形状:
`byte_at` 越界回 -1(0..255 让这个哨兵天然可用)、`byte_index_of` 缺席回 -1、`decode` 坏字符集回 null。

**唯一的行为变更(有意为之)**:`decode(b, "no-such-charset")` 以前是裸的
`UnsupportedEncodingException` Java 栈跟踪,现在是 `panic: decode: unsupported charset`。
其余逐条保持,含 `byte_at` 的原 panic 文本、`byte_slice` 的 clamp 语义、`Bytes ++ Bytes`
与结构相等(那两个是运算符,`dawn/rt/Bytes` 只为 `concat` 保留)。

沿途两个坑:
1. **Java 引用类型返回一律映射成 `Option`**,`byte[]` 也不例外——`utf8`/`byte_slice` 得补 `.expect(…)`,
   和 `trim` 同款。这是编译期报错,跑不掉。
2. **新的源码编译类必须进 `VENDORED_RT_CLASSES`**,否则 `dawn run` 好用而 `java -jar` 崩
   (§十二 已把这条立成回归测试,这次照做即过)。

**回归证据**:编译器 1215 测试绿(**一条没改**)、ktlint 绿;backend-dawn 63 测试绿
(36 处 `split` + 全部 Bytes 调用点);site 34 页 408 链接全解析;`java -jar` 产物自洽。
**builtin 表 57 → 49,std 46。**

## 十七、批 C 的 io 半边:7 个迁走,`args` 迁不动(2026-07-18)

`println` `print` `read_line` `is_dir` `read_file` `write_file` `list_dir` → `std/io.dawn`,
转发到新的源码编译类 `dawn.rt.StdIo`。**这批不需要 `unsafe_pure`**——它们本来就是有效果的,
签名照实写 `!io` 即可。`unsafe_pure` 是给相反情况用的:JVM 认为有效果、实际是纯的。

**`Result` 用 `java_try` 桥,不是变通**。`Result` 是 Dawn ADT,过不了 FFI 边界;而 `java_try`
(不可约核之一)正是「Java 抛了 → `Err(消息)`」的内建桥,且它产生的就是 `throwable.toString()`,
与这三个 builtin 原来的错误串**逐字节一致**(实测对拍过)。于是:

```dawn
pub fn read_file(path: String) -> Result[String, String] !io =
  java_try(fn() => StdIo.readFile(path).expect("null only on failure, which throws"))
```

### `args` 迁不动,而且原因是结构性的

`builtins-to-stdlib.md` §五 写「`args` 走 runtime 访问器」一并迁入 std。**做不到**:

argv 通过 `PUTSTATIC <程序自己的入口类>.dawn$args` 到达程序,而 std 函数编译成**另一个类**,
命名不了那个字段。想让 std 够得着,argv 就得挪到一个**可反射的**类上(否则 `use java` 看不见,
见 §九)——而可反射意味着它在编译器 jar 里,于是**同一个 JVM 里所有程序共用它**。

这不是理论顾虑:改完之后 `stdlib_args_is_empty_without_the_jvm_wrapper` 这条 golden 直接红了
(期望 0 得到 1)——它读到了上一个测试设的 argv。**那条 golden 恰好就是为钉住这个语义存在的。**
彻底的解法是让 vendored 的 rt 类改成 child-first 装载(它们本就属于产物而非编译器),
但那要改动四处 ClassLoader、只为省一个 builtin,不划算。**`args` 留在 builtin。**

### 第五种落点:读 `BUILTINS` 的地方,不止 codegen

§十二 总结过四类 codegen 落点。这批又冒出**第五类,而且不在 codegen 里**:
`lsp/Completion.kt`(补全列表)与 `lsp/AstQuery.kt`(悬停签名)都只读 `BUILTINS`,
迁移后 `println` 这些**从补全里消失、悬停没签名**。和批 A 的 `dawn doc --builtins` 掉文档
是同一个病:**凡是把 builtin 表当作「隐式可见函数全集」来读的地方,迁移都会静默削掉一块**。
两处都改成 `local → std → builtin`,与 checker 的解析顺序对齐。

### 抄语义时抓到的两条(都靠测试,不是靠读代码)

1. **`write_file` 会创建缺失的父目录**——我第一版没做,golden 立刻红。
2. **`read_line` 显式用 UTF-8**,不是平台默认字符集。这条测试没覆盖,是删 `dawn/rt/Io` 死码时
   对着旧 ASM 发现的——非 UTF-8 默认 locale 的机器上会静默改变行为。
3. **`list_dir` 的结果是排序的**(`Files.list` 不保证顺序)。也没有测试覆盖,是核对
   `spec.md:990` 时发现的,回查旧 ASM 确认有 `Arrays.sort`。

**三条里两条测试都没覆盖。**「测试全绿」证明不了迁移是行为保持的,只证明了被测到的部分是。
对着旧实现逐条抄,和跑测试同样重要。

**回归证据**:编译器 1215 测试绿、ktlint 绿;backend-dawn 63 测试绿;site 34 页 408 链接全解析;
`java -jar` 产物自洽(print/read/write/list/args 逐条跑过),错误串与旧实现对拍一致。
**builtin 表 49 → 42,std 60。**
