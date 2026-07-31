# 复审 B 批：八件待裁决契约的一页纸

> 状态：**已裁决（2026-07-31），全部按本文建议**——本文降为过程记录。
> 裁决一览：RP-01 **A**、RP-05 **A**、RP-04 **C**、RP-06 **A**、RP-07 **A**、
> RD-07 **A**、RX-06 **A**、RX-10 **A**（其 B 选项「效果参数」另立项，先有消费者再动）。
> 已回填 [re-audit-2026-07-30.md](re-audit-2026-07-30.md) §六 B。写作时日期 2026-07-30。
>
> **来源**：[re-audit-2026-07-30.md](re-audit-2026-07-30.md) §六 triage 的 **B 批
> 「需要裁决再动的契约件」**——八条的共同点不是工作量，是**先要有人拍板语言承诺什么**，
> 写进 spec 之后实现才有 oracle。本文按 §六 B 的名单逐条给一页：问题一句话、现状（重新验过）、
> 选项与代价、一条建议、以及这条裁决卡着谁。
>
> **每页只需要一个词**：同意 / 改选 B / 改选 C。裁决作出后**回填进 re-audit 那份的对应条目**
> （像 §八 回填 RP-02/RP-03 那样），本文随即降为过程记录。
>
> **证据标记**（沿用复审那份）：**[跑]** = 本轮在 `/tmp` 探针工程上两后端实跑；
> **[读]** = 读码证据（带 file:line）。复审写于 `56d0a99`，此后落地了 A 批五件
> （RX-01、RD-01/02、RP-02/03、RC-04/03、RP-12/RC-09）——**每条的「现状」都是在
> `00755f8` 上重新验的，不是复述复审的断言。**
>
> **八条无一被 A 批消掉**，但 A 批改动了其中两条的地形，各自在「现状」里点明。
>
> 探针环境注记：`dawn run` 走 PATH 上的 java（本机 26，CI 21，Unicode 分类差 18 码点）。
> 只有 RP-05 的 trim 谓词探针触到字符分类，那一条已按此复核（结论是两后端一致，
> 但换 JDK 可能变，见该条）。

| # | 条目 | 严重度 | 建议 | 破坏性 | Emit-Change |
|---|---|---|---|---|---|
| 1 | RP-01 Float dtoa | 高 | 语言自领 dtoa，spec 写全规则，形状钉成今天 JVM 的 | native 变 | 否（JVM 不变） |
| 2 | RP-05 parse 接受语言 | 中 | spec 一段 EBNF，两后端各自实现，不再委托宿主 | 边角输入 | 否 |
| 3 | RP-04 charset 封闭集 | 高 | 取消字符串参数：`decode_utf8` / `decode_latin1` 两个函数 | std API | 否 |
| 4 | RP-06 String 序的货币 | 中 | 码点序；`cmp` 只承诺符号 | 仅非 BMP | 是（排序输出） |
| 5 | RP-07 hash 算法归属 | 中 | 四个叶子算法写进 spec；删两个孤儿原语 | 无 | 否 |
| 6 | RD-07 越界策略统一 | 中 | 三条判据写死；`str.substring` 改钳位 | substring | 否 |
| 7 | RX-06 `<` 与 Ord | 中 | 维持分家，spec 拆成两段并修 §3.5 的过期句 | 无 | 否 |
| 8 | RX-10 效果变量在别名 | 中 | 两处同拒同 hint；效果参数另立项 | 无（树内零用户） | 否 |

---

## 1. RP-01 — Float 的 `to_string` 由谁定义？

**一句话问题**：`to_string(Float)` 的答案是「JVM `Double.toString` 的字节」，还是
**语言自己写下的规则**（最短往返 + 指数形式阈值 + NaN/Inf 拼写），两后端各自实现？

### 现状

**[跑]** 同一个程序，两后端八行里有五行不同：

| 表达式 | JVM | native |
|---|---|---|
| `to_string(0.1)` | `0.1` | `0.10000000000000001` |
| `to_string(1.0e300)` | `1.0E300` | `1.0000000000000001e+300` |
| `to_string(0.0 / 0.0)` | `NaN` | `-nan` |
| `to_string(1.0 / 0.0)` | `Infinity` | `inf` |
| `to_string(3.0e-7)` | `3.0E-7` | `2.9999999999999999e-07` |

`-nan` 是复审没记的一处：C 的 `0.0/0.0` 带符号位，`%.17g` 忠实打印出来，
而语言层面 NaN 没有符号。

**[跑] 常量折叠把两个答案烤进同一个 native 二进制**：

```dawn
const S: String = to_string(0.1)
# native 输出：S 打印 0.1，紧接着的 to_string(0.1) 打印 0.10000000000000001
```

复审说的「与 `dawn_rt.c:1062` 大小写折叠 bug 同一形状」是准的，且比那次更明显——
不需要两台机器，一个二进制内部就自相矛盾。

**[读]** 三处实现：`emit.dawn:2426`（`String.valueOf(D)`，即 `Double.toString`）、
`runtime/c/dawn_rt.c:456`（`%.17g`，注释自陈 `NOT byte-identical`、
「excluded from the differential corpus until the real emitter lands a proper dtoa」）、
`interp.dawn:244` 的 `stringify`（`VFloat(f) -> to_string(f)`，即委托宿主 JVM）。
spec §4.3:535 把语言级答案定义成 JVM 方法名。

**A 批之后地形有变**：RP-02/RP-03 落地时**特意绕开了这里**——§八 写明新语料
`int_edges.dawn`「只打印 Int 与 Bool，避开 RP-01 的 Float 渲染分叉」。
也就是说 native 语义批**加固了 Float 之外的每一条**，Float 的缺口现在是差分语料里
唯一一处「明知不测」。缺口自我繁殖的链条（RP-01 豁免 RP-05）还在（见第 2 条）。

### 选项

- **A（语言自领 dtoa，形状钉成今天 JVM 的）**：写一份 Dawn 的最短往返 dtoa（Ryū 或
  Schubfach，纯 Int/位运算，无 FFI），两后端共用；spec 把规则写全——最短往返、
  十进制/指数形式的切换阈值、`NaN`/`Infinity`/`-Infinity` 三个字面拼写、`1.0` 保留 `.0`。
  规则**取今天 JVM 的行为**，故 JVM 侧输出逐字节不变（**不是 Emit-Change**），
  native 侧改正。代价：~600–900 行 + 一批边界语料；`interp` 要改成调这份共享实现
  而不是宿主（RP-12 那个形状：解释器是唯一不读共享定义的分发器）。
- **B（钉死「等于 Java」，让 C 复刻到字节）**：spec 继续引用 `Double.toString`，
  C 端实现到字节相同。代价：定义留在仓外，而 Java 自己在 JDK 19 换过一次算法
  （Giulietti 的最短往返取代了旧的 `FloatingDecimal`）——今天 CI 跑 21、本机跑 26，
  这条契约的正确性取决于两台机器的 JDK 大版本。
- **C（声明未指定）**：spec 写「Float 渲染两后端可不同」。代价：零成本，
  但差分语料永久缺一角，且**常量折叠那个「一个二进制两个答案」不会被 C 消掉**——
  它不是跨后端不一致，是同后端内不一致。

### 建议

**A。** B 把语言的规范文本外包给一个已经改过一次答案的 JDK，那正是 RP-07 与 RP-05
同一个病；C 治不了常量折叠那半——`const S = to_string(0.1)` 与紧邻的运行期调用在同一个
native 二进制里给两个答案，无论「跨后端」怎么声明都仍是缺陷。选 A 且把规则取成今天 JVM 的
形状，等于「拿回定义权而不动已发布的字节」，代价最小的那条自领路线。

### 牵连

- **解锁**：Float 进差分语料 → `int_edges.dawn` 的避让可撤、`show`/`to_string` 全族收口。
- **约束**：RP-05（第 2 条）的 `parse_float` 一直拿这条当豁免，A 落地即抽掉它的挡箭牌，
  两条应当同一批做。
- **约束 #78 S5 std 收口**：std 若要补数值格式化族（`fmt`/`round_to`），得先有这份 dtoa 打底。
- 触及 `interp` 的原语分发（RP-12 刚立的门禁测试要加一行覆盖 `str_of_float`）。

---

## 2. RP-05 — `parse_int` / `parse_float` 接受什么？

**一句话问题**：接受语言是**一段写在 spec 里的 EBNF**（两后端各自实现），还是
「宿主的 `Long.parseLong` / `strtod` 各自接受什么就是什么」？

### 现状

**[跑]** 实测分叉三处（复审记了前两处的一半，第三处是新的）：

| 输入 | JVM | native |
|---|---|---|
| `parse_int("١٢٣")`（阿拉伯-印度数字） | `123` | `None` |
| `parse_int("１２３")`（全角） | `123` | `None` |
| `parse_float("1.5f")` / `"1.5d"` | `1.5` | `None` |
| `parse_float("inf")` | `None` | `inf` ← **native 更宽** |
| `parse_float("Infinity")` | `Infinity` | `inf`（值同，渲染是 RP-01） |
| `parse_float("NaN")` | `NaN` | `nan`（同上） |

复审的方向说得对，但**方向标反了一处**：`"inf"` 是 native 接受、JVM 拒绝——分叉不是
单向的「JVM 更宽」，是**双向的**，所以不能靠「让 C 追上 Java」收口。

**[跑] 查过、判为一致的**（免得重查）：`"0x1p3"` 两边都得 `8.0`（Java 的
`Double.parseDouble` 本来就收十六进制浮点，C 源注释里「strtod also takes hex floats」
这半句是**错的**——它以为这是分叉）；`"+5"`、`" 5 "`、`"1_0"`、`"0x10"`、`""`、
20 位溢出，六项全一致。trim 谓词也一致：U+00A0 两边都不算空白、U+001C/U+3000/U+2028
两边都算（JVM 走 `String.strip()` 即 `Character.isWhitespace`，C 走
`dawn_char_is_space` 查内建 Unicode 表）——**但这条一致是本机 JDK 26 下测的，
CI 是 21，两者的字符分类差 18 个码点**，正是这条契约该写进 spec 而不是靠碰的理由。

**[读]** JVM 侧：`codegen.dawn:1929-1931` 直接生成 `Long.parseLong` / `Double.parseDouble`
（外加 `String.strip()`），`gen_parse_radix_method`（`codegen.dawn:1832`）同理。C 侧：`dawn_rt.c:1149-1200`，
`dawn_digit_val`（:1149）只认 ASCII、`dawn_parse_float`（:1186）裸调 `strtod`。**互相豁免的注释仍在**
（`dawn_rt.c:1186-1190`）：

```c
/* ... Floats are already out of the differential corpus over dawn_str_of_float;
 * this is the same gap. */
```

spec 对接受语言**一个字都没写**（§11:1242 只给了签名）。

### 选项

- **A（spec 写 EBNF，两后端各自实现）**：约十行 EBNF——可选符号、ASCII 数字、
  无下划线、无后缀、无十六进制整数；浮点另加小数点/指数/`Infinity`/`NaN` 三个字面拼写，
  是否收十六进制浮点一并裁掉；首尾空白按 Dawn 自己的空白表修剪（不是 `Character.isWhitespace`）。
  两后端都**停止裸委托宿主**。代价：JVM 侧要么先自校验再委托、要么手写；破坏面
  = 今天靠 `"١٢٣"` / `"1.5f"` / `"inf"` 通过的调用点，**树内零处**（std/packages/selfhost
  的 `parse_*` 调用全是自产的十进制串）。
- **B（EBNF ≡ Java 接受的，C 追上）**：代价与 RP-01 的 B 同病（定义在仓外、随 JDK 版本走），
  且要把 Java 的十六进制浮点分支和 `f/F/d/D` 后缀复刻进 C——复刻的是没人想要的东西；
  还治不了 `"inf"` 那个反向分叉（得让 C 变**窄**，B 的叙事里没有这一步）。
- **C（收窄到今天两边的交集，不写 spec）**：改动最小。代价：没有规范文本 = 下次再漂，
  而这一条已经漂了两次（复审记一次，本轮实测又多出一处 `"inf"`）。

### 建议

**A，且与 RP-01 同一批做。** 接受语言小到能一屏写完，而它是**唯一**能让 Float 进差分语料的
前提——只要 `parse_float` 还引用 `strtod` 和 `Double.parseDouble` 两份宿主语法，
就永远没有可对拍的 oracle。另外那句「this is the same gap」的注释必须随这批删掉：
一个缺口用另一个缺口给自己开豁免，是复审 §一·3 点名的机制，留着它比留着 bug 更贵。

### 牵连

- **被 RP-01 卡**：`parse_float` 的对拍要能打印结果，就得先有确定的渲染。
- **解锁**：Float 进差分语料的第二半（第一半是 RP-01）。
- **顺带**：`parse_int_radix`（`codegen.dawn:1832` / `dawn_rt.c:1182`）同一条 EBNF 覆盖，
  别漏；C 的 `dawn_digit_val` 收 a–z 而 JVM 的 `parseLong(s, radix)` 也收，这一支今天一致。
- **约束 #86 error-model**：若将来 `parse_*` 从 `Option` 改成 `Result`（带「哪里不合语法」），
  EBNF 就是错误信息的词汇表；先定 EBNF 再谈载荷。

---

## 3. RP-04 — 语言承诺哪些字符集？

**一句话问题**：`bytes.decode(b, charset)` 的**定义域**是一个语言写死的封闭集合，
还是（如今天）JVM 侧 = 宿主 provider 全集、native 侧 = 两个条目？

### 现状

**[跑]** 定义域实测：

| 调用 | JVM | native |
|---|---|---|
| `decode(b, "UTF-8")` / `"utf-8"` | `hi` | `hi` |
| `decode(b, "ISO-8859-1")` | `hi` | `hi` |
| `decode(b, "US-ASCII")` | `hi` | **panic: decode: unsupported charset** |
| `decode(b, "UTF-16")` | `桩`（把 `hi` 当 UTF-16BE 读） | **panic** |

`UTF-16` 那一格特别值得看：JVM **不报错**，它成功返回一个别的字符串。所以这不是
「一边能一边不能」，是**一边给答案、一边崩**——静默错答案在 JVM 那侧。

**[读]** `std/bytes.dawn:67-68` 是纯函数，`.expect("decode: unsupported charset")`；
JVM 实现 `codegen.dawn:900` 转 `new String(b, charset)`；C 实现 `dawn_rt.c:1342-1378`
只有两支（UTF-8/UTF8、ISO-8859-1/latin1），别名比较照 Java 的大小写不敏感规则
（`dawn_charset_is`，`dawn_rt.c:1319`）。spec 对存在哪些 charset **一个字都没写**（§9.5.1:1010、§11:1262
都只说「按字符集解码」）。

**[读] 树内调用点全部是 `"UTF-8"`**：`selfhost/src/lsp.dawn:509`、`main.dawn:1028`、
`pkgfetch.dawn:273,359,365`、`packages/web/src/server.dawn:65,73`、
`packages/inflate/src/zip.dawn:151`——**九处，无一例外**。没有第二个 charset 的真实用户。

### 选项

- **A（封闭集合 = {UTF-8, ISO-8859-1}，写进 spec）**：规范名 + 认可别名列表；
  字面量参数时未知 charset 是**编译错误**，非字面量时 panic。JVM 侧不再把用户的串
  交给 `Charset.forName`，改成映射到固定两支。代价：小；破坏面 = 用 `US-ASCII`/`UTF-16` 的人，
  树内零处。留下的问题：一个字符串参数仍然是一个「注册表」形状，只是变小了。
- **B（封闭集合 = StandardCharsets 那六个）**：加 `UTF-16BE`/`UTF-16LE`/`US-ASCII`
  （`UTF-16` 带 BOM 嗅探，建议排除）。代价：C 端 +150 行左右，仍有限、仍可 spec 化。
  但为零个真实用户写三个解码器。
- **C（取消字符串参数）**：`bytes.decode_utf8(b) -> String`、`bytes.decode_latin1(b) -> String`，
  `decode(b, charset)` 删除。代价：std API 破坏（九个调用点逐字替换，机械改动）；
  收益是**「未知 charset」这个失败模式不复存在**——不需要 panic、不需要 `expect`、
  不需要「字面量则编译期」的特例，定义域由类型系统而不是运行期查表兑现。

### 建议

**C。** 用字符串给一族函数命名，就是把一张注册表塞进参数位——本仓「一件事一份定义」
运动杀的正是这个形状，而这里的注册表已经小到只剩两行，改成两个函数是净删代码
（`std/bytes.dawn` 的 `.expect` 走了、`dawn_charset_is` 走了、`codegen.dawn:900` 那支走了）。
将来真要 UTF-16，加一个 `decode_utf16be` 就行，不必重开契约；反过来，留着字符串参数
就得永远回答「这个名字算不算」。

### 牵连

- **约束 #78 S5 std 收口**：`bytes` 族的 API 形状（RD-10 的 hex/base64 补件同一模块），
  应当一次改完而不是分两批动 `std/bytes.dawn`。
- **解锁**：`bytes_decode` 从 intrinsic 表退成两个更窄的 intrinsic，或干脆两个都用
  Dawn 实现（UTF-8 walker 与 latin1 展开都是纯循环）——后者能让 `bytes` 的后端契约
  再少一条，方向与 S3「后端集合契约 = Array 五操作」一致。
- 与 RP-06 相邻但不耦合：decode 的输出是 String，String 的内部货币不由这条决定。

---

## 4. RP-06 — `<` 与 `cmp` 在 String 上比的是什么？

**一句话问题**：`Ord[String]` 定义为**码点序**还是保持今天的 **UTF-16 码元序**？
顺带：`cmp` 承诺**符号**还是也承诺**幅值**？

### 现状

**[跑]** 两后端**一致地**给 UTF-16 序（所以这是概念病，不是错答案）：

```
from_char(0x1F600) < from_char(0xFFFD)  →  true      （两后端）
```

码点序下这该是 `false`（0x1F600 > 0xFFFD）；UTF-16 下高代理 0xD83D < 0xFFFD，故 true。
同一个程序里 `str.len(from_char(0x1F600))` = `1`——**长度是码点，序是码元**。

**[跑] 幅值也一致地泄漏**：`cmp("a","z")` = `-25`、`cmp(emoji, repl)` = `-10176`
（= 0xD83D − 0xFFFD）。这是一个可打印的宿主量。

**[读] 而 std 已经在按「只有符号」写**——`std/list.dawn:138-139`：

> `cmp` contracts sign, not magnitude: scaling its result could overflow.

而 `runtime/c/dawn_rt.c:654` 的 `dawn_cmp_str` 里写着相反的话：

> the magnitude matters, not just the sign: `String.compareTo` hands back the
> difference of the first differing unit, and a program can print it

**两份注释，一份说契约只有符号、一份说幅值是契约的一部分，都在树内。**
spec §3.5:427 只写 `fn cmp(a: T, b: T) -> Int`，没裁。

**[读]** C 端为此专门造了 UTF-16 迭代器复刻（`dawn_rt.c:531` 的 `dawn_utf16_next`，
`dawn_cmp_str` 在 :646、`dawn_hash_str` 在 :609 也用它）。`emitc.dawn:673` 的注释
称这是 code-point order——与 `dawn_cmp_str` 自述矛盾，复审记的这处仍在。
`<` 在 String 上走的就是 `dawn_cmp_str`（`emitc.dawn:672-678`），故 `<` 与 `cmp` 同序，
**String 上没有 RX-06 那种分家**。

### 选项

- **A（码点序 + `cmp` 只承诺符号）**：`Ord[String]` 改码点序，`cmp` 全类型统一返回 −1/0/1。
  代价：**Emit-Change**（含非 BMP 字符的排序输出会变；纯 BMP——含全部 CJK——不变，
  故实际影响面极小）；C 端 `dawn_cmp_str` 简化成 UTF-8 字节序比较（UTF-8 字节序 ≡ 码点序，
  是 UTF-8 的设计属性，可以直接 `memcmp`，反而更快）；JVM 端要放弃 `compareTo`，
  改成 `codePointAt` 循环——**JVM 侧变慢**，这是 A 的真代价。
- **B（写死 UTF-16 序）**：spec 补一句「`Ord[String]` 是 UTF-16 码元序」，修 `emitc.dawn:673`
  的注释。代价：零。但语言从此有两种字符串位置货币：`len`/`substring`/`chars`/`cursor`
  数码点，`<`/`cmp`/`sort` 数码元，且**只在 emoji 上能观察到差别**——最难发现的那类不一致。
- **C（码点序，保留幅值）**：只改序不改幅值契约。代价：留着一个「可打印的宿主量」，
  而它在码点序下会变成码点差，量纲又换一次。

### 建议

**A。** 语言在**别的每一处**都已经是码点货币（`str.len`、`substring`、`chars`、
整个 `cursor` 模块、`from_char`），UTF-16 是这一处漏出来的表示细节；且
「符号 vs 幅值」今天有两份互相矛盾的树内注释，std 那份（只有符号）已经是**调用方在依赖的**
那份，把它升成 spec 条文只是承认既成事实。Emit-Change 的实际暴露面是「含非 BMP 字符的
有序输出」——CJK 全在 BMP 内不受影响，这一点在 SourceView 收敛那轮已经量过。

### 牵连

- **与 RP-07 耦合但不同题**：`hash(String)` 今天也走 UTF-16（`dawn_rt.c:608`）。
  哈希不必与序同货币，但**若 A 落地而哈希不动，String 就变成「序按码点、哈希按码元」**——
  裁 RP-06 时请连带裁 RP-07 的 String 那一行（见下条选项 A 的清单）。
- **解锁**：`emitc.dawn:673` 的错注释与 `dawn_utf16_next` 在 `cmp` 路径上的复刻一并可删。
- **约束 #44 关联类型 / 运算符 trait**：`<` 将来若统一走 `Ord`（RX-06 的 B 分支），
  这条的货币就是那条的输入；先定货币再谈路由。
- **约束 #90 遗留的 `Char` 迁移刀**（nominal-types 已驳回，但 `opaque type Char = Int`
  仍在队列）：`Char` 是码点，一旦 String 的序也是码点，`Char` 与 String 的序可交换，
  否则不可。

---

## 5. RP-07 — 语言级 `hash` 的算法归谁？

**一句话问题**：`hash(x)` 的四个**标量叶子**算法（Int/Bool/String/Bytes）写进 spec 的
自己的话，还是继续引用 JDK 方法名？

### 现状

**[跑]** 两后端逐位一致：`hash("abc")` = `96354`、`hash(1)` = `1`、`hash(true)` = `1231`、
`hash([1,2,3])` = `30817`。**今天没有错答案**，这条是归属问题不是缺陷问题。

**[读] 复合的那半已经是 Dawn 自己的话**——spec §3.5:443-446 明写：种子 `1`、
逐部分 `h = 31*h + hash(part)`、32 位环绕、元组按元素序、构造器序号先折。
**叶子那半仍是 JDK 引用**：

| 叶子 | 规范文本 | native 实现 |
|---|---|---|
| `Int` | 无（= `Long.hashCode`） | `dawn_rt.c:593`，`v ^ v>>>32` |
| `Bool` | 无（= `Boolean.hashCode`） | `dawn_rt.c:607`，`1231/1237` |
| `String` | 无（= `String.hashCode`，UTF-16 码元） | `dawn_rt.c:609`，走 `dawn_utf16_next` |
| `Bytes` | **spec §9.5.1:1016 写「`Arrays.hashCode`」** | `dawn_rt.c:621`，注释复刻该算法 |

`Bytes` 那行最能说明病灶：规范文本点名一个 JDK 方法，而 C 端从注释里把它**重新实现了一遍**——
定义在仓外，实现在仓内两份，中间靠一条注释对账。

**[读] 两个孤儿原语仍在**：`dawn_hash_float`（`dawn_rt.c:597`）与
`dawn_cmp_float`（`dawn_rt.c:635`），声明在 `dawn_rt.h:493,498`。
今天**不可达**——`types.dawn:1376-1378` 有断言钉着 `Float` 既不在 `ord_scalars`
也不在 `hash_scalars`，`lower.dawn:1419-1421` 的注释也写明了理由。
`dawn_hash_float` 自己的注释承认它复刻的是 spec 拒绝的东西：

> `-0.0` and `0.0` have different bits and therefore different hashes, while
> `-0.0 == 0.0` is true. ... it is why the spec says `Hash[Float]` should not exist.
> Reproduced here rather than repaired.

复审说的「哪天有人把 `Ord[Float]` 加回来，静默拿到 `Double.compare` 全序」——
这条路径今天被 `types.dawn` 的断言挡着，所以是**未来风险**而非现行缺陷，但删掉两个函数
比留着断言便宜。

### 选项

- **A（四行算法写进 spec，删两个孤儿）**：把上表四个叶子写成 spec 自己的话（各一行），
  spec §9.5.1:1016 的「`Arrays.hashCode`」换成算法本身（种子 1、`h = 31*h + (有符号 byte)`），
  顺手记下这恰好与复合规则同形。删 `dawn_hash_float`/`dawn_cmp_float` 及其头声明。
  代价：**两后端零改动、无 Emit-Change、非破坏**——纯文本 + 删死码。
- **B（声明 hash 未指定）**：`hash(x)` 不再是稳定可打印的数。代价：与 spec §3.5:443
  「合成的哈希是**可观测的数**（`hash(x)` 可以打印），故定义在此」的既有裁决**直接冲突**——
  那句话是有意写的，B 等于推翻它。收益（实现自由）今天没有消费者。
- **C（维持 JDK 引用）**：零成本，病留着。

### 建议

**A，建议直接做，无需等窗口。** 复合规则已经是 Dawn 自己的话，叶子只差四行，
而「四行不写」的代价是 spec 里躺着 `Arrays.hashCode` 这样一个规范性 JDK 引用、
C 端靠注释复刻它——这正是 RP-01 与 RP-05 同一个形状，只是这一条**不需要改任何代码**就能治。
两个孤儿原语并入同一刀：它们是「语言已删、运行时仍在」，留着只会等一个未来的静默错答案。

### 牵连

- **被 RP-06 约束**：若 RP-06 判码点序，`hash(String)` 的那一行要同时决定跟不跟走
  （建议：**不跟**，哈希不需与序同货币，但要在 spec 里写明这是有意的，否则下一轮审查会当 bug 报）。
- **解锁**：`dawn_utf16_next` 在删掉 `cmp` 用途后，若哈希也不用，整个 UTF-16 迭代器可删——
  RP-06 + RP-07 一起裁能少一个复刻件。
- 与 #78 / #86 / #90 / #44 无耦合。这是八条里最独立、最便宜的一条。

---

## 6. RD-07 — 越界到底 panic、Option 还是钳位？

**一句话问题**：语言给出**几条**越界策略、判据是什么，以及今天四种实现里哪几种是例外、
哪几种是错？

### 现状

**[跑]** 同一份 std，五种行为并存（`xs = [1,2,3]`，两后端一致）：

| 调用 | 行为 | spec 有没有写 |
|---|---|---|
| `xs[9]` | panic `index 9 out of bounds for length 3` | §4.8:611,616 有，判据「断言」 |
| `list.get(xs, 9)` | `None` | §4.8:617 有，判据「问询」 |
| `list.take(xs, 9)` | `[1,2,3]`（钳位） | **无** |
| `list.drop(xs, 9)` / `take(xs, -1)` | `[]`（钳位） | **无** |
| `list.slice(xs, 1, 99)` | `[2,3]`（钳位） | **无** |
| `bytes.slice(b, 0, 99)` | 长度 3（钳位） | §9.5.1:1013 + §11:1263 **有**，写明「下标 clamp」 |
| `str.substring("abc", 0, 99)` | **panic** | §11:1277 **有**，写明「越界 panic」 |
| `cursor.char("", start)` | `-1` | §11:1281 **有**，写明「到尾返回 -1」 |

最锋利的一格是最后三行的对照：**`bytes.slice` 与 `str.substring` 是同一形状的区间取值
（两个下标、返回子序列），spec 明写了两条相反的策略**，而 `list` 的三个区间函数
**一条都没写**、行为跟 `bytes` 走。

**A 批消掉了四个错误里的一个**：RD-01 已落地——`pvec.nth` 从「无界读、静默返回错元素」
改成走 `index` 的检查版（`std/pvec.dawn:161-172`），`at` 收成私有。所以复审列的
「四处相反」现在是**三处相反 + 一处已修**。

**[读] `-1` 哨兵在 std 内自己打架**：`std/bytes.dawn:76-79` 的 `at` 把原语的 `-1`
当成必须消灭的渗漏（`if v < 0 { panic(...) }`），而 `std/cursor.dawn:28-29` 的 `char`
把同一个 `-1` 当公开 API——且 `packages/json` 已经**把它当契约用**
（`lexer.dawn:10,18` 的 `peek`、`parser.dawn:63,68`），不是可以顺手改掉的。

**[读] `str.substring` 的调用点 94 处**（std/packages/selfhost 合计），改它的策略
是有实际暴露面的破坏性变更，不是纸面调整。

### 选项

- **A（三条策略 + 明写判据）**：
  1. **断言**：位置读（`xs[i]`、`m[k]`、`bytes.at`、`pvec.index/nth`）→ panic。
  2. **问询**：`get` 族 → `Option`。
  3. **钳位**：**区间参数**（`take`/`drop`/`slice` 三族 + `substring`）→ 两端夹进范围，
     `from > to` 得空。
  代价：`str.substring` 从 panic 改钳位（94 处调用点里靠 panic 兜底的需体检，
  但钳位比 panic 更宽，**不会把过去能跑的程序变成不能跑**）；spec 补一段判据。
  `cursor.char` 的 `-1` 作**唯一具名例外**入 spec，理由写清：它是逐步原语，
  包 `Option` 会在每步分配。
- **B（两条策略，钳位取消）**：`take`/`drop`/`slice` 越界 panic。代价：破坏且反直觉——
  `take(xs, 10)` 取一个短列表的前十个是日常写法，让它 panic 等于逼每个调用点先写 `min`。
- **C（三条策略，但 `bytes.slice` 与 `list.*` 改成 panic 向 `substring` 看齐）**：
  与 B 同病，且要改的是**四个**函数而不是一个。

### 建议

**A。** 五个区间取值函数里四个已经钳位、只有 `substring` 是 panic，多数派就是判据——
而且钳位是**放宽**，唯一能在不破坏任何现存程序的前提下把五个统一到一处的方向。
`cursor.char` 的 `-1` 不该被顺手改掉：json 包已经在依赖它，且它是「原语暴露哨兵 /
std 包装成 panic 或 Option」这条既有分工（`bytes.at` 就是包装的那一侧）的另一半，
把它写成 spec 里的具名例外比消灭它诚实。

### 牵连

- **并入 #78 S5 std 收口**（复审 §六 C 已经这么排了）：RD-07 与 RD-04/05/06/08/09/10
  改的是同一批文件，`str.substring` 的策略改动应与 RD-05 的词缀/位置族补件同一刀。
- **约束 #86 error-model**：若将来引入结构化错误，「断言 = panic」这条决定了
  越界**不进** `Result`——现在裁掉，error-model 就不必为它留一个分类。
- **牵动 RD-01 的落地文本**：`std/pvec.dawn:147-153` 的注释引用了 spec §9.8 作为依据；
  判据段落写好后，那条注释应改指新段。

---

## 7. RX-06 — `<` 与 `[T: Ord]` 分家，认不认？

**一句话问题**：`1.5 < 2.5` 合法而 `smaller[T: Ord](1.5, 2.5)` 不合法——
这是**写进 spec 的两套规则**，还是应当消灭（给 Float 一个 Ord impl）？

### 现状

**[跑]** 分家仍在，且**诊断已经很好**：

```
error: no impl of `Ord` for `Float`
  = hint: orderable scalars are Int and String; Float has no total order (NaN),
          and everything else needs an `impl Ord`
```

hint 已经把设计说清楚了。问题**不在实现，在 spec**。

**[读] spec 自己矛盾，且是本轮新发现**（复审没记这处）：

- §3.5:427：「预置 `trait Ord[T] { fn cmp(a: T, b: T) -> Int }` 及
  **`Int`/`Float`/`String` 的 impl**」← **过期**，Float 的 impl 已于 07-26 撤销。
- §4.3:527：「`[T: Ord]` 不再收 Float，`cmp(1.5, 2.5)` 不再编译」← 现行。
- §4.3:544：「排序比较 `< <=` 等：`Int`/`Float`/`String` 原生有序；其他类型桥接到
  预置 trait `Ord` 的 `cmp`」← 一句话把两套机制并列写，读起来像**同一套**。

所以今天的 spec **既有一句过期陈述、又有一句混写陈述**，而正确的那句藏在 §4.3 里。
实现是对的，规范是乱的。

**[读] String 上两套机制答案相同**：`<` 在 String 上编译成 `dawn_cmp_str`
（`emitc.dawn:672-678`），与 `Ord[String]` 同一条；只有 Float 真分家。
这一点值得连带写进 spec——否则读者会以为每个「原生有序」标量都可能与它的 `Ord` 不一致。

### 选项

- **A（维持分家，spec 拆成两段并修 §3.5:427）**：写清楚——`<`/`<=`/`>`/`>=` 在
  `Int`/`Float`/`String` 上是**不解见证的原生运算**（Float 上是 IEEE 语义，`NaN` 参与的
  比较一律 false）；`[T: Ord]` 是 trait bound，`Float` 没有 impl；两者在 `Int`/`String` 上
  答案相同、在 `Float` 上**有意不同**。代价：**零代码**，纯文本。
- **B（给 Float 一个 Ord impl，NaN 位置写死）**：`<` 一律走 `cmp`。代价：**破坏**，
  且推翻 07-26 的既有裁决（spec §4.3:522-528 花了七行拒绝它，理由列了三条）；
  副作用是 `list.sort` 对 Float 列表会**静默**给 NaN 一个位置——今天它是编译错误，
  这正是那条裁决要买的东西。
- **C（Float 也不给 `<`）**：数值类型不能比大小，荒唐，仅为完整性列出。

### 建议

**A，且顺手修 §3.5:427。** 07-26 的裁决是对的，诊断 hint 也已经写得比 spec 好——
缺陷全在规范文本：一句过期（§3.5:427 还说 Float 有 Ord impl）、一句混写
（§4.3:544 把两套机制并成一句）。这是八条里唯一**零代码、零风险、可以今天就写完**的一条。

### 牵连

- **约束 #44 关联类型 / 运算符 trait**：trait-v2-design §7.4 把关联类型的理由换成了
  「运算符 trait 的前置」。若将来 `<` 统一路由到运算符 trait，**A 这条 spec 段落就是
  那次改造的验收标准**（改造后 Float 必须仍能 `<`、仍不能 `[T: Ord]`）；不先写下来，
  那次改造会顺手把分家抹掉。
- **与 RP-06 相邻**：RP-06 定 `Ord[String]` 的货币，A 这一段要写「String 上 `<` 与 `cmp` 同序」——
  两条应当同一次改 spec，否则第二次改会覆盖第一次的措辞。
- 与 #78 / #86 / #90 无耦合。

---

## 8. RX-10 — 效果变量能不能给类型起名字？

**一句话问题**：`!e` 在 `alias` 硬拒、在 record 字段放行——**两处统一到拒绝**，
还是把效果参数引进类型参数列表让它真能用？

### 现状

**[跑]** `alias` 侧硬拒，信息清楚：

```
error: a type alias cannot carry effect variables
  = hint: write !io, or leave the function type pure
```

**[跑] record 字段侧比复审记的更坏。** `pub type Box = { f: fn(Int) -> Int !e }` 编译通过，
然后：

| 调用方 | 结果 |
|---|---|
| `fn apply(b: Box, x: Int) -> Int !io` | **通过**，正常返回；存进去的 io 闭包副作用真的发生 |
| `fn pure_apply(b: Box, x: Int) -> Int` | 报错「not declared !e but calls ... (!e)」 |
| `fn poly_apply(b: Box, x: Int) -> Int !e` | **同样报错**，hint 说「add !e to the end of the signature」——**签名已经有了** |

也就是说：字段上的 `!e` 实际语义 ≡ `!io`（只有 `!io` 能把它消掉），而**编译器给出的
唯一补救建议是做不到的事**。复审说「退化」，实测是「退化 + 诊断指向一条死路」。

**未发现不健全**：纯函数调不动它（第二行），所以 io 没有逃出纯性边界；这是概念缺陷不是漏洞。

**[读] 根因**（复审判断成立）：spec §6.3:702「效果变量 `!e` 无需声明，
**在签名中出现即引入**；作用域是整条签名」。record 声明不是签名，所以字段上那个 `!e`
**没有绑定者**——它变成一个自由的效果常量，只有 `!io` 这个具体效果能覆盖它。

**[读] 树内零用户**：全仓（排除 `rtsrc.dawn` 的内嵌 C 源）grep 不到任何在
record/variant 字段位写 `!e` 的声明。所以任一裁决都是非破坏的。

### 选项

- **A（两处同拒同 hint）**：record/variant 字段位的 `!e` 按 alias 的同一条信息拒绝。
  代价：十几行 parser/checker 改动，**零破坏**（树内无用户）。语言保持「效果多态只活在
  签名里」，但不再有一处硬错一处静默的不对称。
- **B（效果参数进类型参数列表）**：`alias Mapper[T, U, !e] = fn(T) -> U !e`、
  `type Box[!e] = { f: fn(Int) -> Int !e }`。代价：一项**真功能**——绑定语法、
  使用点的效果推断、与 §6.3:704 的并格（`!(e1|e2)`、`!io` 是顶、纯是幺元）交互、
  以及类型参数列表里混两种参数的解析。这是唯一让效果多态**可命名**的路线，也是唯一
  能让 std 写出 `alias Mapper` 这类别名的路线。
- **C（把字段的裸 `!e` 判为 `!io` 并写进 spec）**：最便宜的诚实做法。代价：`!e` 在两个
  位置意思不同（签名里是变量、字段里是 `!io` 的别名），比今天更难解释。

### 建议

**A 现在做，B 独立立项排队。** 语言今天的效果多态**只在签名里有绑定者**（§6.3:702），
在没有真实需求把它命名之前，正确的动作是让两个位置**一致地拒绝**，而不是留一个
「编译器的 hint 指着一条走不通的路」的位置——那比缺功能更贵，因为它教用户
写出一个永远修不好的签名。B 的规模与 trait v2 同量级，应当按同样纪律走：
先有消费者，再有设计文档，再动码。

**另有一条与裁决无关、建议直接修的**：`poly_apply` 那个 hint（「add !e to the end of
the signature」而签名已经有 `!e`）无论选 A 还是 B 都是错的，选 A 时它随代码一起消失，
选 B 时它必须改。

### 牵连

- **约束 #78 S5 std 收口**：std 今天没有任何 `alias` 是函数类型（因为写不出来）；
  若选 B，`std/list` 的高阶签名可以收成命名别名，RD-06 的命名族统一会想用它。
  选 A 则 S5 不必等。
- **约束 #44 关联类型**：trait 方法若将来带效果参数，B 是前置；A 不影响。
- **不牵动 #86 / #90。**

---

## 附：本轮查过、判为不是问题的（免得重查）

- **`parse_float("0x1p3")` 两后端都得 `8.0`**——`dawn_rt.c:1188` 的注释以为这是分叉
  （「strtod also takes hex floats」暗示 Java 不收），实测 `Double.parseDouble` 也收。
  修 RP-05 时顺手删掉这半句。
- **`parse_*` 的首尾空白修剪两后端一致**（U+00A0 不算空白，U+001C/U+3000/U+2028 算）。
  但 JVM 走 `String.strip()` 即 JDK 的 `Character.isWhitespace`、C 走内建 Unicode 表，
  **本机 JDK 26 与 CI 的 21 相差 18 个码点**，这一致是今天的、不是契约的。
- **`hash` 四个标量两后端逐位一致**（`96354`/`1`/`1231`/`30817`）——RP-07 是归属问题，
  不是缺陷问题。
- **RX-10 的 record 字段不构成纯性漏洞**：纯函数调不动带 `!e` 的字段（实测报错），
  io 没有逃出边界。
- **`pvec.nth` 已不在 RD-07 的问题列表里**：RD-01 于 07-30 落地，`nth` 现在走
  检查版 `index`（`std/pvec.dawn:161-172`）。
