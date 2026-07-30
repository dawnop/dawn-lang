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

**当前状态:34 个语料(30 个单文件 + 4 个项目目录),`known-red.txt` 里一条不剩。**
每条曾经的红都在那份文件里留着「当初到底错在哪」,那是它的正文。
下面那张表是**早期的历史**,只列到语料十;此后加的十几个语料各自在文件头写清覆盖什么,
`run.sh` 用通配抓文件,所以表落后不影响执行——要知道现在收了什么,看目录。

## 组成

| 件 | 说明 |
|---|---|
| `selfhost/src/core.dawn` | Core IR 节点集 |
| `selfhost/src/lower.dawn` | TAST → Core(糖在这里死) |
| `selfhost/src/emitc.dawn` | Core → C |
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
| `known-red.txt` | 今天就红的检查清单,带 ratchet |
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
derive 出来的 impl、列表模式、解构 let、`bytes_*` 内建、`use java`。
最后一个不是缺口而是设计——`use java` 正是 FFI 里不可移植的那一半,native 后端**应该**拒绝它。

**在外,但不 panic**:`emitc` 只发**用户模块**。调到 std 的函数会发出一句调用,而那个函数
的定义从不出现——没有前向声明、没有诊断,唯一发现它的是 `cc` 的 `-Werror`(隐式声明)。
故语料一律只用内建,不 `use std/*`;`eq_bytes.dawn` 直接调 `bytes_utf8` 而不是
`bytes.utf8`,就是为了让它红在相等上,而不是红在这条上。

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

## 已知的不对等(有意留下)

- **Float 的 `to_string` 不逐字节等于 Java**。Java 出的是最短往返形式,`%.17g` 不是。语料因此不含
  Float 打印;真发射器要带一个 dtoa。
- **不释放内存**。`dawn_str_concat` 每次 malloc,永不 free。Perceus 是 Phase 4 的事,
  现在猜一个方案只会白猜。
- **`panic` 直接 `exit(1)`**,没有 setjmp/longjmp,所以 `catch_panic` 不存在。Phase 3 补。
- **名字混淆是有损的**:`sanitize` 把非 `[A-Za-z0-9_]` 折成 `_`,不同 Dawn 名字可能撞车。
  真发射器需要一张表。
