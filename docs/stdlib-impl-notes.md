# std 实现札记：几个函数为什么长成这样

> **状态：current** —— 这些实现今天仍是这个形状；文中的实测数字是当时量的，
> 结论不随数字过期。

std 的 `##` 注释是 API 面，只写契约（收什么、越界怎么办、复杂度、和兄弟函数的分工）。
但有几个函数的**实现**不是显而易见的那种，或者它今天的形状是被一次故障逼出来的。
那些话搬到了这里——它们对着实现读有用，对着签名读只是噪声。

被搬空的是这几处的第二、三段：`str.repeat`、`io.list_dir`、`io.run`、`io.write_file`、
`list.unique`、`map`/`set` 的 `Show` impl，以及 spec §11 里同源的几句。

---

## `str.repeat`：两种显而易见的写法都是缺陷

API 面只留一句「倍增，`O(len(s) * n)`，任何 `n` 都不吃栈」。为什么不用这个模块其余
地方那种朴素累加，理由有两半：

**它替下来的是递归**：`s ++ repeat(s, n - 1)`，深度就是 `n`。默认 `-Xss` 下 n 过了
4000 左右爆栈。本仓一直没撞上，是因为**每一条跑 Dawn 程序的路径都传了 `-Xss512m`**，
而对着打好的 jar 直接 `java -jar` 没有。这类「本仓看不见的缺陷」值得单记一笔。

**改成 `while` 里累加 `out = out ++ s` 能修掉栈，但换来一个二次**：`++` 是
`String.concat`，JVM 每轮把答案整个复制一遍。实测 n = 100000 要 0.6s，n = 200000
是它的 4 倍。**这个代价只有 JVM 背**——C 后端的 refcount 让它能原地追加，那边本来
就是线性的，所以这是一处单后端的性能坑，两后端对拍看不出来。

倍增让每个中间答案只被复制一次：两个后端都是 `O(len(s) * n)`，且完全不用栈。

## `io.list_dir`：排序为什么在 std 层，不在后端

`io_list_names` 原语答的是操作系统给的顺序，一趟 `list.sort` 走语言自己的
`Ord[String]` 才让所有后端一致。**在屏障底下排就意味着每个后端各排一份**——JVM 那份
曾经是 `Arrays.sort`，那是 UTF-16 码元序，会把增补平面的文件名排到 U+E000..U+FFFF
之前。这是「一个问题两份定义」在 std 里的一次实例。

## `io.run`：`io.no_program` 是被两后端分歧逼出来的

空 `argv` 的 `kind` 之所以要 std 自己铸一个，是因为两个后端本来不一致：JVM 把空表
原样递给 `ProcessBuilder`，泄出一个 `java.lang.ArrayIndexOutOfBoundsException`——
调用方要 match 的那个 `kind` 上写着 "Index 0 out of bounds for length 0"；而 C 运行时
早就自己查过，说的是 `io_run: argv is empty`。「没有 `argv[0]` 可以点名」是一个关于
**参数**的问题，不是关于宿主的，所以它不该由宿主来措辞。检查提到 std 层做，失败就
永远到不了后端，两边自然同一句话。

## `io.write_file`：`Ok` 为什么不带值

它曾经返回 `String.length()`——UTF-16 码元数，既不是字符数也不是字节数。2026-07-19
去掉，因为**一个调用点都没读过它**。唯一值得返回的计数是落盘的字节数，而那要多走
一趟编码。

## `map` / `set` 的 `Show`：渲染要给出一个能粘回去的名字

`map.from([...])` 是今天的渲染。它曾经渲染成 `map_from([...])`，那是 v0.5.0 退役掉的
平铺名（见 [`stdlib-naming.md`](stdlib-naming.md) §三）：粘回去只会得到
`undefined function`，于是每一行打印 map 的日志都在教一个语言里已经没有的名字。
审计 RD-14（`docs/audit/re-audit-2026-07-30.md`）。

## `list.unique`：为什么直呼 `set_from` 而不 `use std/set`

std 模块按 `std/modules.txt` 的顺序检查，`list` 在 `set` 前面，加一条 `use` 边就得
重排整个捆绑包。`set_from`/`set_to_list` 是 `std/set` 自己转发到的那两个原语，直呼
它们不是绕过 `std/set` 去开第二条通往同一个结构的路。

（`unique` 比这一族其余函数多要一个 `Hash`，那是契约不是实现细节，留在 API 面。）

## `bytes.decode`：带 charset 参数的那个为什么被删

审计 RP-04 裁决 C：语言承诺的字符集只有两个，**函数名即定义域**
（`decode_utf8` / `decode_latin1`），不设字符集注册表。旧的 `bytes.decode(b, charset)`
与它底下的原语一并删除；原语的收窄走了种子三期。契约面上的后果是它们回裸 `String`
而非 `Option`——没有 charset 参数，就没有「不认识的字符集」这个失败面。

后来（LIB-06）UTF-8 这一侧按同一条规则又分成两个名字：`decode_utf8_lossy` 是原来那个
（非法序列换 U+FFFD），`decode_utf8_checked` 在第一个非法序列处回
`Err(Utf8Error { offset })`。这不是把 charset 参数换个形状请回来：定义域仍由函数名给定，
分开的是**遇到非法输入怎么办**，而那正是原来没有答案、调用方也问不出来的那一半。
`decode_utf8` 暂留为 `decode_utf8_lossy` 的一代 forwarder。

## `String` 里没有非良构 UTF-8：这条不变式是量出来的

spec §11 把它写成规范。它不是修辞：`c0 af`（overlong 编码的 `/`）曾经原样进过字符串，
下游那些按码点走的原语会把它当成一个真的 `/`——C 侧的 UTF-8 walker 接受 overlong 与
代理半区，与 JVM 分歧。两处已修（#112 修 walker，#113 修 C 侧 io 读取器对齐 JVM），
严格 walker 逐分支镜像 JDK，147 万条向量对拍定形。
