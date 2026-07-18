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

**下一步**:String 组余下的按同样原子推进。**注意分水岭**——`trim`/`contains`/`starts_with`/
`ends_with`/`split`/`join`/`chars`/`parse_int`/`parse_float` **在 comptime 里可用**,迁走会让
`const` 折叠失效,故这批必须**等阶段3(route C)先落地**。不受此限的下一批:`to_lower`/`to_upper`/
`index_of`/`last_index_of`/`code_points`/`from_code_points`/`char_to_string`/`str_len`。

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
