# native 差分测试(Phase −1 spike → Phase 5 的第一道验收门)

同一个 Dawn 程序在两个后端各编一遍,两边互相比,再各自比一份**写下来的**期望输出。

```bash
./scripts/spike-native/run.sh                      # 跑全部语料
./scripts/spike-native/run.sh path/to/prog.dawn    # 只跑一个
```

它起初是 Phase −1 的接缝 spike(TAST 直接发 C,平凡子集),现在 `emitc` 已改吃 **Core IR**,
语料已压到 `match`/ADT/闭包/trait 字典/相等/渲染/字典转发/comptime 折叠。

每个语料产出至多七个具名检查:

| 检查 | 含义 |
|---|---|
| `emitc` | `dawn __emitc` 发出了 C |
| `cc` | 那份 C 能编 |
| `jvm` | JVM 的 stdout == `<name>.expect` |
| `native` | native 的 stdout == `<name>.expect` |
| `diff` | 两个后端的 stdout 一致 |
| `stderr` | 两个后端的 stderr 一致 |
| `exit` | 两个后端的退出码一致 |

**`jvm` / `native` 是对 `codebase-audit.md` TEST-01 的回答。** 只做后端互比,等于把 JVM 今天的
行为认证成正确答案;而**两个后端共有的缺陷会让它们在错答案上达成一致**——凡是编译期折叠的东西
都属此类,两边折的是同一份 `interp.dawn`。`<name>.expect` 是唯一一份不是从后端抄来的判据。

**当前状态:114 个语料(107 个单文件 + 7 个项目目录),`known-red.txt` 里一条不剩。**
每条曾经的红都在那份文件里留着「当初到底错在哪」,那是它的正文。
下面那张表是**早期的历史**,只列到语料十;此后加的十几个语料各自在文件头写清覆盖什么,
`run.sh` 用通配抓文件,所以表落后不影响执行——要知道现在收了什么,看目录。

## 组成

| 件 | 说明 |
|---|---|
| `selfhost/src/ir/core.dawn` | Core IR 节点集 |
| `selfhost/src/ir/lower.dawn` | TAST → Core(糖在这里死) |
| `selfhost/src/c/emitc.dawn` | Core → C |
| `runtime/c/dawn_rt.{h,c}` | 运行时:标量、`dawn_str`(UTF-8+字节长度)、`dawn_adt`(tagged union)、装箱槽、stdout、panic |
| `hello.dawn` | 语料一:递归/循环/break/continue/短路/位运算/字符串/Unicode |
| `adt.dawn` | 语料二:match 决策树/守卫/嵌套模式/ADT/`?`/`!`/元组/从 match 臂里 break |
| `closure.dawn` | 语料三:lambda 提升/捕获环境/函数值/组合/命名局部函数 |
| `trait.dawn` | 语料四:trait 字典/去虚化/转发见证/默认方法/双约束 |
| `recurse.dawn` | 语料五:自尾调用(spec §12.4)——无优化的 C 下也要能走 500 万层 |
| `eq_adt.dawn` | 语料六:结构相等——ADT/记录/递归形状/Option/元组 |
| `show_derive.dawn` | 语料七:`derive Show` 与插值——标量/ADT/泛型参数/prelude 容器 |
| `dict_forward.dawn` | 语料八:`[T: Eq/Hash/Ord]` bound 的字典转发,三种见证各一 |
| `const_fold.dawn` | 语料九:comptime 折叠——每个 `const` 都配一行同表达式的运行期输出 |
| `eq_bytes.dawn` | 语料十:`Bytes` 相等——裸的按内容,嵌进 record/ctor/Option/元组就按身份 |
| `<name>.expect` | 该语料的期望输出(**手写,不从后端抄**) |
| `<name>.args` | 可选；逐行写程序参数，JVM 越过 `--`、native 直接收到同一数组 |
| `known-red.txt` | 今天就红的检查清单,带 ratchet |
| `stdext/raw.dawn` | std-only 原语的 std 侧壳(io fault / bytes 哨兵),由 `run.sh` 注进 std 拷贝,见下 |
| `run.sh` | 差分 harness |

入口是隐藏命令 `dawn __emitc <file> -o <out.c>`,与 `__lex`/`__parse`/`__check` 同族。

`-Werror` 是**真门禁**不是洁癖:Core 的类型错到 C 里,先表现为 int-from-pointer 警告,
远早于表现为算错答案——模式绑定的类型 bug 就是这么抓到的。

## 覆盖面(以及为什么就到这)

**在内**:顶层函数、`Int`/`Float`/`Bool`/`String`/`Unit`、算术与位运算、比较、短路、
`if`/`while`/`for i in a..b`/`break`/`continue`/`return`、字符串字面量与插值、`panic`、
ADT 构造与字段读、match(含守卫、嵌套模式、字面量模式、元组模式)、`?`、`!`、元组、
**闭包(lambda 提升 + 捕获环境 + 函数值)**、**trait 字典(去虚化/转发/默认方法)**、
**装箱(在类型变量槽的进出)**。

**在外**(碰到就 `panic` 报节点名):集合(List/Map/Set,等 D1–D3)、comptime const、
derive 出来的 impl、列表模式、解构 let、`use java`。
最后一个不是缺口而是设计——`use java` 正是 FFI 里不可移植的那一半,native 后端**应该**拒绝它。

**曾在外,已不在**:`emitc` 一度只发**用户模块**,调到 std 的函数会发出一句调用而定义从不出现
——没有前向声明、没有诊断,唯一发现它的是 `cc` 的 `-Werror`(隐式声明)。故语料一律只用内建、
不 `use std/*`,`eq_bytes.dawn` 直接调 `bytes_utf8` 而不是 `bytes.utf8`。S3 把 std 一起编进
那份 translation unit(集合就是 std),这条限制随之消失,语料现在照常 `use std/*`。

## `stdext/raw.dawn`:语料怎么拿到 std 包起来的那层原语

`io_*` / `bytes_at` / 两个解码原语是 **std-only** 的(`selfhost/src/check/types.dawn` 的 `internal`
集,见 `docs/audit/re-audit-2026-07-30.md` RD-02):io 原语失败时抛的是**fault**,`std/io` 才是
把它变成 `Result` 的地方;`bytes_at` 越界回 `-1`,把这个哨兵变成 panic 正是 `bytes.at` 的全部
内容。用户代码若能直呼原语,这两层就都是建议而非边界。

而这份语料恰是**唯一想要原语本身**的调用者——两个后端必须在原语上一致,`catch_kinds.dawn` 问的
就是「哪个屏障接住 fault」,而 native 拒绝 `use java` 之后,程序再没有别的办法引发一个 fault。

办法照抄 `scripts/array-contract`:`run.sh` 把 `std/` 拷进一个临时目录、丢进 `stdext/raw.dawn`、
往 `modules.txt` 追一行 `raw`,然后全部语料都用 `--std <copy>` 编。它不属于捆绑的 std,任何已发布
的工具链都看不见它。**代价是:语料文件不能脱离 `run.sh` 直接 `dawn run`**——`use std/raw` 会解析
不到。std 那边只是一行别名的(`bytes.utf8`/`bytes.len`/`bytes.slice`/`str.to_upper`/`io.println`
/`io.exists` …),语料直接用 std 拼写,因为那到达的是同一个运行时函数、而名字查得到。

## 准入规则改了(2026-07-25)

这份 harness 原先的规则写在 `run.sh` 的头注释里:

> a program only belongs here once both backends can compile it, so a failure is always a
> regression, never a gap.

**那条规则正是它自己的盲区。** 它只收两个后端已经同意的程序,于是语料只能由实现者随实现增长,
天然覆盖不到实现者没想到的事。结果:五个语料里 `==` 只出现在 `Int` 和 `String` 上,
一处都没比较过两个 ADT 值——而 ADT 相等在两个后端上给的是相反答案,已经这样很久了。

新规则:**语料按语言的语义面收,不按后端的完成度收。** 今天做不到的检查记进 `known-red.txt`,
`run.sh` 据此放行;清单外的失败是红的,而清单内的检查一旦**开始通过**也是红的
——修好一个缺陷,对应那行必须跟着删,清单不会烂在那儿。

于是「native 后端还没做到」与「某个语义压根没人定义」在同一张表里可见,且各自带着理由。
每条红的完整分析——以及每条已修的红留下的那句「是怎么修的」——都在 `known-red.txt` 里。

## 三个结论

**一、接缝成立。** 换后端换的是 `emit_module` 的返回类型,不是它的入参。而 Core IR 落地后更进一步:
`emitc.dawn` 连 `Adts`/`Traits`/`impl_table` 都不需要——构造器布局、判别式、字段类型全部已经烘进 Core。

**二、表达式→语句的下降没有意外。** Dawn 是表达式语言,C 是语句语言。标准的「发进临时变量」手法
足够:`emit_expr(st, e) -> (CSt, String)` 往缓冲区追加语句、返回一个 C 表达式串。唯一需要特殊处理的是
`&&`/`||`——右侧可能要发语句,所以不能用 C 的 `&&`,得降成 `if`。

**三、抓到一个真 bug,而且它是给 Core IR 的一条设计输入。**

第一次跑,Unit 返回函数里的**最后一句 `println` 整个消失了**。根因:`emit_expr` 返回的是一个
*C 表达式串*,调用方若不把它写进输出,那次调用就从未发生。函数返回 `Unit` 时我直接写了 `return DAWN_UNIT;`,
把尾表达式的串丢了——**连同它的副作用**。

同样的漏在 `while`/`for` 的循环体、`if` 的 Unit 分支上各有一处。修法是引入 `discard(st, v)`,
所有丢值的地方都必须过它。

> **给 Core IR 的输入(已采纳)**:这个 bug 之所以可能,是因为「表达式的值被丢弃」这件事在 TAST 里
> **没有节点**,全靠每个消费者自觉。Core IR 因此有了 `CSDiscard`,由 lowering 显式产生,
> 后端不可能忘。

## 四、Core IR 落地后又抓到两件

**`CSLoop` 需要一个 `step` 字段。** 最初 `for` 的自增放在循环体末尾——于是 `continue` 会跳过它,
循环永不终止。把 step 做成节点的字段(正好是 C 的 for 第三子句),这件事就不再是每个后端各自的坑。

**`CBreak` 必须点名它要离开哪个循环。** `match` 降级成一个「只走一遍的循环」,而用户写在 match 臂里的
`break` 要离开的是**外层的源码循环**。两个 break 同时存在,所以 break 不能是「最内层」的意思。
C 侧因此用 `goto` 而不是 `break` 实现。语料 `adt.dawn:first_shape_over` 专门压这一条。

**字典槽必须只有一种签名,而桥接该由 lowering 生成。** trait 默认方法体自带字典参数,impl 方法不带、
且吃具体类型——两者填进同一张表就会签名冲突(实测:段错误)。JVM 后端今天是在 impl 单例上生成转发方法
解决的,也就是**每个后端各生成一遍**。改法是让 lowering 合成一个普通顶层函数当桥接(拆箱→调 impl→装箱),
槽只指向它。于是两个后端都不知道这件事存在。

**`ty_key` 必须只有一份。** 它同时被 lowering(给字典命名)和两个后端(给 impl 方法命名)使用,
放在 `core.dawn` 里,不然三个生产者会把同一个 impl 叫成三个名字。

**名字混淆必须是可逆的。** 把非 `[A-Za-z0-9_]` 折成 `_` 会让模块 `a/b` 与 `a_b` 得到同一个 C 符号
(`dawn_a_b__f`),而多段模块路径今天就是合法语法——于是 JVM 跑得好好的程序在 C 侧被 `cc` 判为
`redefinition`。`emitc.escape_part` 改用 JNI 那套编号转义(`_`→`_1`、`/`→`_2`、`$`→`_3`、其余走
定长十六进制),转义后的部件里出不来 `__`,所以 `__` 成了谁也伪造不了的分隔符,符号能拆回部件。
语料 `mod_paths` 压这一条。

## 已知的不对等

一条不剩。这里曾列着三条「有意留下」的,三条都已关账,各自换成了一份压着它的语料——
所以现在写在这儿的是它们**在哪被压着**,而不是它们还欠着什么:

- **Float 的 `to_string`**。曾经 C 侧答 `%.17g`、JVM 答 `Double.toString`,语料因此绕开
  Float 打印。渲染与解析已由语言自领(`std/fmt` 的最短往返 dtoa),两个后端编的是同一份,
  `float_edges` 就是那份差分——连「同一个二进制里编译期折叠与运行期调用要打出同样的字节」
  也在里面。
- **释放内存**。Perceus RC 已落地,`dawn_str` 也是计数对象。`run.sh` 把每个语料再用
  `-fsanitize=address` 编一遍、以 `detect_leaks=1` 跑,所以「不 free」在这里是红的;
  没有任何豁免——取过屏障的语料也对每个字节负责(#193 把 raise 改成跑 cleanup 的
  强制 unwind,`recover_live`/`recover_msg`/`recover_bracket` 压着恢复路径,
  曾经的 `<name>.leaks-on-catch` 豁免连同机制一起删了)。
- **`panic` 与两道屏障**。运行时有 setjmp/longjmp,`catch_panic` 与 `catch_fault` 都在,
  且是**两个**函数——io 屏障不吞 panic。`catch_kinds` 逐条压这个分类。`panic` 仍然以
  退出码 1 结束进程,但两个后端一致,所以那不是不对等。
