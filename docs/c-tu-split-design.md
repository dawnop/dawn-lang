# C 翻译单元切分：一个程序切成 K 段并行 cc

> 状态：**current**。刀 1、刀 2 于 2026-10-05 落地（§十），刀 3 等 Proc spawn/wait（裁决 4.f）。设计与原型实测写于同日，分支 `docs/c-tu-split`。
> 依据：裁决 ffi-llvm 4.c（「按模块拆 TU 并行 cc，打 #239 与 prev-diff-native pole；需设计文档」）；
> 同日 LLVM 调研报告 §3（自举约八成墙钟在 cc）；#239 与 #275（native-selfhost-tests 的 cc 占比、
> 「切 TU 等 Proc 有 spawn/wait」）；`scripts/pinned-cc.sh`（CI 与发布已钉 clang 18.1.3）。

## 一、结论

**推荐：emitc 仍然输出一份文本，但这份文本由「共享头 + K 段」组成，段与段之间是机器可切的分界行；
K 由程序大小决定（nmain 取 16），切点按函数体在发射顺序里的累计字节等分；驱动与脚本把它切成 K 个
`.c` 并行 cc。不开 LTO。**

实测（共用多核机器，clang 18.1.3 -O2，nmain 闭包 379k 行 / 22.7 MB C，§四）：

- **4 核**（CI runner 的核数）上编译整个 dawnc：单 TU **69.4 s → 14.7 s**（−79%）；全核 66.6 s → 4.5 s。
- **总 CPU 也降了**：16 段合计 52.9–59.2 s，单 TU 66.6 s。单个巨型 TU 里有超线性的 pass，
  切开以后单核也更快，所以没有「多核换墙钟」的代价。
- **产物运行时间不变**：自举负载（`dawnc emitc selfhost/src/nmain.dawn`）交错成对测十次，
  单 TU 中位 18.9 s，seq K=16 中位 18.7 s（§4.3）。跨段丢掉的内联量不出来；
  RC 原语本体本来就在另一个 TU（`dawn_rt.c`），单 TU 也没内联到它们。
- **字节可复现**：同一切分、不同并行度（16 路与 taskset 4 核）、不同构建目录链出的 dawnc 逐字节相同（§4.4）。
- **ThinLTO 能再快 16%**（运行 18.8 → 15.8 s），但链接是串行段，4 核上整体 25–30 s 对 14.7 s，
  而且**产物字节随目标文件所在的绝对路径变**（不开 LTO 时不随）。LTO 要不要上，交给裁决 4.a（RC 快路径进头文件）实测后再定（结论见 [native-inline-design.md](native-inline-design.md)：不做默认），
  不和本刀绑（§六、§九）。

对 CI 的预期（§七）：prev-diff-native 约 −125 s（537 → ~410 s，仍是 pole 但让出约四分之一），
native-selfhost-tests 约 −60 s（刀 2）再 −85 s（刀 3），wasm-target 约 −45 s；native-diff 基本不变
（语料都是小程序，K=1）。

## 二、现状：一个程序就是一个 TU

`cdriver.c_text` → `emitc.emit_program` → `emit_units`（`selfhost/src/c/emitc.dawn`）一次写出整个
程序，顺序是：

1. `#include "dawn_rt.h"`、`<math.h>`；
2. Unicode 表：`const dawn_case_range dawn_upper_ranges[] = {…}` 等，外部链接，`dawn_rt.h` 里已有
   `extern` 声明（运行时的大小写/分类函数读它们）；
3. 全部函数原型（「C 要先声明后使用，Dawn 不排序」）；
4. 字典：`static dawn_dict dawn_dict_… = { n, { (void*)fn, … }, 0, { 0 } };`，**文件作用域 static**；
5. 常量构造器 `st.cdefs`：`static void* dawn_const_N(void) { static void* c = NULL; … }`，同样 **static**；
6. 全部函数体，按模块顺序（std 在前），**没有一个是 static**；
7. `static void dawn_program_entry(void)` 与 `int main`。

`dawn test` 走 `emit_headless`，少第 7 段，尾巴接 `ctestrun.runner` 生成的测试 main。
字符串字面量、掩码数组都是**块作用域** static，跟着函数体走，切分不碰它们。

驱动侧：`nmain.cc_build_with` 把 `main.c` 和内嵌运行时写进临时目录，**一次** `io.run` 调 `cc`
编译链接（`selfhost/src/nmain.dawn`，`cc_build_with`）。`std/io.run` 是同步的；Proc 族没有
spawn/wait，这正是 #275 记的「切 TU 的前置」。

脚本侧：`native-fixpoint.sh`、`release-native.sh`（发布物 cc 两次再 `cmp`）、`native-selfhost-tests.sh`
自己调 `"${CC:-cc}" … nmain.c dawn_rt.c`。另有约三十个脚本消费 `__emitc -o x.c` 的单文件输出
（各种 contract、spike-native 语料、doc-check）。

规模（`083cc583`）：nmain 闭包 **379,018 行 / 22.7 MB**，约 4,460 个函数、87 个模块、100 个字典、
1 个常量构造器。最大的模块是 `check/checker`，**3.41 MB，占函数体的 15.3%**；其后 `ir/lower`、
`front/parser`、`check/passes`、`lsp/server`、`lsp/lspq` 各 5% 上下。最大的单个函数是 Unicode
大小写表构建器（约 0.9 MB，4%）。

## 三、原型

原型脚本与原始数据不进仓库，关键数抄进本节与 §四。测量分三批：p2（全部配置一遍）、p3（seq 切法、`-static`、交错成对的运行时间）、p4（ThinLTO 字节与什么有关）。做法是**文本层面**切 emitc 的现有输出，
不改 emitc：

- `prog.h` = include + 全部原型 + 每个字典一行 `extern dawn_dict X;` + 常量构造器原型（去 static）；
- 第 0 段 = Unicode 表 + 字典定义（去 static）+ 常量构造器定义（去 static）+ entry/main + 自己那份函数体；
- 其余各段 = `#include "prog.h"` + 分到的函数体。

三种分组：

| 记号 | 规则 |
|---|---|
| `mod` | 以模块为原子，按字节 LPT 装箱（最大的先放进最空的箱） |
| `fn` | 以函数为原子，按字节 LPT 装箱（同一模块的函数会散到各段） |
| `seq` | 以函数为原子，**保持发射顺序**，按累计字节等分成 K 个连续段 |

编译：`clang-18 -std=c11 -Wno-parentheses-equality -O2 -fwrapv -fexceptions -fno-strict-aliasing -pthread`
（`native-fixpoint.sh` 的行），每段一个 `-c`，`xargs -P J` 按文件大小从大到小并行，`dawn_rt.c` 与
build-info 单元也是其中两项；最后一次链接。LTO 变体在编译与链接上加 `-flto=thin`（或 `-flto`），
链接用 lld 并给 `--thinlto-jobs`。运行：链出的 dawnc 跑 `emitc selfhost/src/nmain.dawn` 三次取 user 秒，
并核对输出与 A.c 逐字节相同（**所有变体都相同**）。

环境：一台与别人共用的多核 Linux 机器（负载约 30），clang 18.1.3（Ubuntu 包）；「4 核」= `taskset` 钉 4 个核，模拟 GitHub runner 的 4 vCPU。
本机 16 核那组见 §4.6，当时负载 8 → 34（别的任务），只能看比例。

## 四、实测

### 4.1 编译墙钟（共用机器，全核，J = K）

单位秒。「编译」= 全部 `-c` 并行段的墙钟，「最长段」= 其中最慢的一个 `-c`，「CPU 合计」= 各段之和，
「运行」= 自举负载 user 秒（三次）。表中取 p2 第一遍；p3 重测的同配置编译时间低 5–10%（节点负载变了），比例不变。

| 配置 | 编译 | 最长段 | CPU 合计 | 链接 | 合计 | 运行 user |
|---|---:|---:|---:|---:|---:|---|
| 单 TU | 66.6 | 65.9 | 66.6 | 0.1 | 66.7 | 20.2 / 20.0 / 19.8 |
| mod K=4 | 15.1 | 15.0 | 57.5 | 0.1 | 15.1 | 19.4 / 19.7 / 19.9 |
| mod K=8 | 8.5 | 8.5 | 55.9 | 0.1 | 8.6 | 19.4 / 19.3 / 19.7 |
| mod K=16 | 8.6 | 8.6 | 55.6 | 0.1 | 8.7 | 20.2 / 19.8 / 19.7 |
| fn K=4 | 15.6 | 15.6 | 57.4 | 0.1 | 15.7 | 20.1 / 20.1 / 19.7 |
| fn K=8 | 7.1 | 7.1 | 53.7 | 0.1 | 7.2 | 19.5 / 19.8 / 19.1 |
| fn K=16 | 4.0 | 3.9 | 52.9 | 0.1 | 4.1 | 20.3 / 20.8 / 21.2 |
| **seq K=16** | **4.4** | 4.4 | 59.2 | 0.1 | **4.5** | 21.0 / 20.1 / 19.9 |
| seq K=8 | 7.9 | 7.8 | 58.2 | 0.1 | 8.0 | 20.8 / 20.9 / 20.8 |

读法：

- **mod 卡在 `check/checker`**：K=8 与 K=16 都是 8.5 s，正是那一个模块自己的编译时间。以模块为原子，
  加速上限约 1 / 15.3% ≈ 6.5 倍，K 再大也没用。所以原子必须是函数。
- **fn 与 seq 差不多**（4.0 对 4.4 s）。seq 不打乱发射顺序（§五为什么要这个），只多 10%。
- **CPU 合计随切分下降**：66.6 → 52.9–59.2 s。不是测量误差：在单核上依次编 16 段也比单 TU 快。

### 4.2 四核（taskset，模拟 CI runner），J = 4

| 配置 | 编译 | 最长段 | 链接 | 合计 | 运行 user |
|---|---:|---:|---:|---:|---|
| 单 TU | 69.4 | 68.7 | 0.1 | 69.5 | 21.3 / 22.0 / 21.5 |
| mod K=4 | 17.3 | 17.2 | 0.1 | 17.4 | 21.6 / 21.9 / 22.0 |
| mod K=8 | 18.2 | 10.2 | 0.1 | 18.3 | 21.9 / 22.9 / 21.6 |
| fn K=8 | 18.0 | 9.9 | 0.1 | 18.1 | 21.3 / 21.3 / 20.7 |
| fn K=16 | 14.4 | 4.0 | 0.1 | 14.5 | 20.5 / 20.5 / 20.3 |
| **seq K=16** | **14.7** | 4.4 | 0.1 | **14.8** | 20.4 / 19.9 / 19.8 |

四核上 K=16 比 K=4 好：段小，装箱的尾巴短。单 TU 在 4 核与全核上几乎一样（69 对 67 s），
说明共用机器的负载对单核编译影响不大，这组数可以和 §4.1 并读。

### 4.3 运行时间：跨模块内联丢了多少

§4.1、§4.2 每行只跑三次，而且行与行之间隔了几分钟，共用节点的负载在变（同一个单 TU 产物在 p2 首尾
测出 20.0 与 24.0 s）。所以单独做了一组**交错的成对测量**：同一次调用里依次构建「单 TU、seq K=16、
seq K=16 + ThinLTO」，各跑五次，再把三者原样重来一遍（p3 末组）：

| 配置 | 第一轮 user（五次） | 第二轮 user（五次） | 中位 | 相对单 TU |
|---|---|---|---:|---:|
| 单 TU | 19.18 18.94 19.26 19.10 19.19 | 18.61 18.74 18.83 18.79 18.70 | 18.9 | 1.00 |
| seq K=16 | 18.75 18.78 18.77 18.86 18.83 | 18.67 18.68 18.61 18.65 18.61 | 18.7 | 0.99 |
| seq K=16 + ThinLTO | 15.95 15.77 15.81 15.80 15.87 | 15.65 15.71 15.68 15.89 16.28 | 15.8 | 0.84 |

**切成 16 段不慢**（反而低 1%，在噪声内）。原因有二：一是单 TU 本来也内联不到最热的那批调用：
`dawn_dup`/`dawn_drop` 的本体在 `dawn_rt.c`（`dawn_take`、`dawn_own_drop` 是 `dawn_rt.h` 里的 `static inline`，
每段都有）；二是 seq 切法
让同一模块的函数大多留在同一段，模块内的小函数照样能内联。跨段丢掉的只是「模块 A 调模块 B 的小函数」
那一类，在这个负载上量不出来。

### 4.4 字节可复现

| 比较 | 结果 |
|---|---|
| 单 TU，两次独立构建（p2 首尾） | 相同（`349a7c25c4a1`） |
| mod K=8，J=8 与 taskset 4 核 J=4 | 相同（`5ffa4a209465`） |
| fn K=16，J=16 与 J=4 | 相同（`da35380d0042`） |
| seq K=16，J=16 与 J=4 | 相同（`d048d72b49c2`） |
| 不同 K（同一 A.c） | 不同（函数在 `.text` 里的排布变了，预期之中） |
| 不开 LTO，seq K=16，在三个不同的临时目录里各构建一次（p3 首组、p3 末组、p4） | 相同（`d048d72b49c2`） |
| 不开 LTO，`-static`，seq K=16，J=16 与 J=4 | 相同（`6eb0f6309648`） |
| ThinLTO seq K=16，同一目录，`--thinlto-jobs=16` 两次、`=4` 一次 | 相同（`cbcfaf00c792`） |
| ThinLTO seq K=16，同名子目录、父目录不同 | **不同**（`cbcfaf00c792` / `be5f9055a081`） |
| ThinLTO seq K=16，目录名也不同 | **不同**（`ed0b137c4ebc`，大小也差 360 字节） |

结论：**不开 LTO 时，产物是「C 文本 + K」的函数，与并行度无关**；K 写在文本里（§五），所以
发布那条「两次独立链接逐字节相同」的检查原样成立，而且在哪个目录里构建都一样。ThinLTO 不同：
它与 `--thinlto-jobs` 无关（p4 单独验过；p2 里一度看起来相关，是因为那组的目录名里带了并行度），
但**与目标文件的绝对路径有关**。`release-native.sh` 两次构建共用一个 `$WORK`，所以那条 `cmp` 还会绿，
可同一个 tag 在 CI 与本机上会链出不同字节。要上 LTO，就得先把路径从 LTO 的模块标识里拿掉（固定的
构建目录，或验证 `-ffile-prefix-map` 是否够用），这一步本文没有测（§九）。

### 4.5 LTO

| 配置（全核） | 编译 | 链接 | 合计 | 运行 user |
|---|---:|---:|---:|---|
| 单 TU，-O2（基线） | 66.6 | 0.1 | 66.7 | 20.2 / 20.0 / 19.8 |
| 单 TU，-flto=thin | 32.0 | 81.5 | 113.5 | 16.9 / 16.5 / 17.0 |
| seq K=16，-flto=thin | 1.8 | 6.4 | 8.2 | 15.8（五次中位，§4.3） |
| 单 TU，-flto（full） | 37.3 | 70.4 | 107.8 | 17.6 / 17.3 / 17.5 |
| mod K=8，-flto=thin | 4.2 | 12.9 | 17.0 | 16.4 / 16.6 / 16.8 |
| fn K=16，-flto=thin | 2.0 | 7.4 | 9.3 | 17.5 / 17.3 / 17.5 |
| fn K=16，-flto=thin，4 核 | 6.5 | 19.4 | 26.0 | 16.5 / 16.9 / 16.7 |
| mod K=8，-flto=thin，4 核 | 7.5 | 20.8 | 28.2 | 16.6 / 16.2 / 16.2 |
| seq K=16，-flto=thin，4 核 | 6.2–8.9 | 19.2–20.7 | 25.4–29.6 | 16.0 / 15.9 / 16.1 |

- 跨 TU 内联（主要是 `dawn_rt.c` 里的 `dawn_dup`/`dawn_drop` 等进到调用点）值约 **16%** 运行时间（§4.3 成对测量 0.84），
  与调研报告 §3.3 的 clang `-flto` −14% 一致。**这份收益与切不切 TU 无关**：单 TU 也拿不到它。
- 切分让 LTO 变得能用：单 TU ThinLTO 113 s，seq K=16 8.2 s（全核）/ 25–30 s（4 核）。
- 但 4 核上 ThinLTO 仍比不开 LTO 慢 11–15 s（25–30 对 14.8 s），因为后端代码生成挪进了链接，而链接只有一个。

### 4.6 本机（16 核，高负载，只看比例）

本机组跑在别的任务占满 CPU 的时段（loadavg 从 8 涨到 34），
同一个单 TU 前后两次是 86.1 s 与 171.2 s，**绝对值不可用**。比例与共用机器同向：mod K=4 26.6 s、fn K=8 16.9 s、
fn K=16 12.7 s；fn K=16 + ThinLTO 6.7 + 21.4 s；单 TU ThinLTO 62.6 + 179.4 s。负载下单 TU 吃亏更多：
它只有一个进程跟别人抢调度。全部本机产物的输出与 A.c 逐字节相同。

## 五、设计

### 5.1 输出形状：一份文本，K 段，拼起来仍是合法的单 TU

emitc 的输出仍是**一个字符串**（`c_text` 的类型不变），只改排布：

```
/* generated by dawn __emitc -- Core IR -> C */
#include "dawn_rt.h"
#include <math.h>
<全部原型>
<extern dawn_dict 每个字典一行>
<常量构造器原型>
/* dawn:tu 0 of K */
<Unicode 表> <字典定义> <常量构造器定义> <第 0 段函数体> <entry 与 main / 测试 runner>
/* dawn:tu 1 of K */
<第 1 段函数体>
…
```

- 分界行 `/* dawn:tu k of K */` 是固定格式的整行注释，切法只认「整行恰好等于它」。函数体里
  拼不出这样一行：emitc 不往体内发注释；字符串字面量里倒是有 `/*`（内嵌的运行时源码就是），
  但 `c_escape` 把换行转义成 `\n`，字面量永远在一行之内，且行首是缩进与 `static dawn_str`。
- **整份文本依旧是一个能直接 `cc` 的单 TU**：头部的 `extern` 声明后跟同名定义是合法 C。原型实测把
  16 段拼回去 `clang -fsyntax-only` 通过。所以那三十来个只吃 `-o x.c` 的脚本、emit 语料、Playground、
  wasm 行**一行都不用改**，愿意继续单 TU 编译的地方照旧。
- 切法是纯函数 `split(text) -> [(name, text)]`：头 = 第一个分界行之前的全部，写成 `dawn_prog.h`
  （加 include guard）；第 k 段 = `#include "dawn_prog.h"` + 两条分界行之间的内容。它只读分界行，
  所以 A==B==C、prev-diff 这些**对整份文本的逐字节比较自动覆盖了每一段**，不需要新的比较。
- 字典与常量构造器去掉 `static`。符号名已经在 `mangle` 的语法里（`dawn_dict_3…`、`dawn_const_N`），
  与运行时、与用户函数都不撞（`emitc.dawn` 的 `mangle` 注释证明过三族互不相交）；常量构造器的缓存
  `static void* c` 只有一份定义，所以「每个常量只建一次」不变。

### 5.2 切点与 K

- **原子是函数**（§4.1：以模块为原子被 `check/checker` 卡在 6.5 倍）。
- **连续切（seq）**：按发射顺序，第 i 个函数体进第 ⌊(到它为止的累计字节) × K / 总字节⌋ 段。
  函数顺序与今天完全一样，只是中间插了 K−1 条分界行；同一模块的函数大多在同一段，局部性比 LPT 好，
  也最容易读 diff。代价是比 LPT 多约 10% 的最长段（§4.1：4.4 对 4.0 s），不值得为它打乱顺序。
- **K 只取决于程序**：`K = clamp(⌈函数体总字节 / 1.5 MB⌉, 1, 16)`。nmain 22 MB → 16；
  Playground 与 native-diff 语料里的程序（剪枝后几百到几千行）→ 1，输出就是今天的形状加一条分界行。
  K 不能取决于机器核数：那样同一份源码在两台机器上会发出不同的 C，fixpoint 与发布的「两次构建
  逐字节相同」都会失去意义。并行度 J 由构建方按核数自己定，§4.4 证明 J 不影响产物。
- 上限 16：四核 CI 上 K=16 已经比 K=8 快（§4.2），再大段太小、头部重复解析的比例上来；
  `dawn_prog.h` 约 390 KB，16 段各解析一遍本机实测每段约 0.1 s（只含头的空 TU，-O2），16 段合计约 1.6 s，不到 CPU 合计的 3%。

### 5.3 谁来并行

- **脚本**（刀 2）：`native-fixpoint.sh`、`release-native.sh`、`native-selfhost-tests.sh` 的 driver 构建、
  wasm-target 的「the C driver, once」。它们自己调 `cc`，可以直接 `xargs -P "$(nproc)"`；
  需要一个把文本切成文件的入口，见刀 1。
- **dawnc 内部**（刀 3）：`dawnc build/run/test` 走 `cc_build_with`，一次 `io.run`。要并行就要
  Proc 能同时起多个子进程。两个选择：
  - 给 Proc 加 `spawn`/`wait`（裁决 4.f，估 2–3 人日）。这是正路：参数是 argv 列表，失败按子进程
    逐个报，和今天 `io.run` 的错误文案一致；
  - 让 dawnc 生成一段 `sh -c 'cc … & cc … & wait'`。**不推荐**：把 argv 拼回 shell 字符串，引号与
    路径转义成了新的攻击面与 bug 源，`wait` 也拿不到每个子进程的退出码，cc 失败的报错会变差。
  刀 3 依赖 4.f。在那之前 `cc_build_with` 也可以把 K 段放进**同一条** cc 命令（clang 逐个编），
  墙钟不并行，但拿得到 CPU 合计下降的那 10–20%（§4.1）；这一步不需要 spawn，可以并进刀 1。

### 5.4 与 release 可复现性

`release-native.sh` 要求两次独立链接逐字节相同。不开 LTO 时：

- 每段 `.o` 只取决于这段 C 和编译器（与并行度无关，§4.4）；
- 链接顺序必须固定：按 `tu00.o … tuNN.o dawn_rt.o build_info.o` 的名字顺序传给链接器，
  不能用 shell 通配的「完成顺序」或 `$(ls -t)`；
- 构建目录不进字节：§4.4 在三个不同的 `mktemp` 目录里各链一次 seq K=16，sha 相同，所以
  不需要 `-ffile-prefix-map` 之类的处理。这条只对不开 LTO 成立。

`-static` 与切分正交：p3 用 `-static` 链了单 TU、seq K=16（J=16 与 J=4，字节相同）和 seq K=16 + ThinLTO，
都能链、都能跑、自举输出都与 A.c 相同。

## 六、刀序

| 刀 | 内容 | 动到 | 门禁与声明 |
|---|---|---|---|
| 1 | emitc 发分界行 + 头部排布（§5.1），字典与常量构造器去 static；`K` 规则（§5.2）；`cc_build_with` 写出 K 段、一条 cc 命令编完；`split` 纯函数放 `c/cdriver.dawn` 并加内联测试（拼回等于原文、K=1 时只多一条分界行、分界行不出现在函数体里）；`dawnc emitc --split DIR` 与 `__emitc --split DIR` 写出各段 | `c/emitc.dawn`、`c/cdriver.dawn`、两个驱动的 CLI | emit 语料一次性 `Emit-Change`（每个受影响 label 一行）；native-fixpoint 与 prev-diff 必跑；**不改任何脚本的构建方式**，所以墙钟不变 |
| 2 | 脚本用 `--split` + `xargs -P` 并行编 dawnc：native-fixpoint、release-native、native-selfhost-tests 的 driver 构建、wasm-target 的 C driver | `scripts/`；`gates.yml` 只动 wasm-target 那一步（它是内联在 workflow 里的 `cc` 行） | 报墙钟（CI 纪律）；release-native 的两次链接 `cmp` 保持；链接行按段号排序 |
| 3 | `cc_build_with` 切段并行编译（刀 1 已经让它一条命令编 K 段） | `nmain.dawn`；前置 4.f（Proc `spawn`/`wait`） | `dawnc test` 的测试 TU 也受益；native-cli-diff 覆盖错误路径（某段编不过时报错的文案） |
| 不排 | LTO | 不在本线 | 等 4.a 的实测：若 RC 快路径进头文件后拿回大部分那 16%，就不需要 LTO（§九） |

刀 1 与刀 2 不依赖 4.f，可以先做；刀 2 是墙钟收益的大头。

## 七、对 CI 墙钟的预期

基线取 main `660fda19` 的 CI（run 37265864599，已钉 clang 18.1.3）。从日志时间戳拆出 cc：

| job | 现在 | 其中 cc | 刀 2 后 | 刀 3 后 |
|---|---:|---|---:|---:|
| prev-diff-native（pole） | 537 s | 发布物两次 cc，各约 80 s（05:06:35 → 05:07:56 为第二次） | ~410 s | ~410 s |
| native-selfhost-tests | 360 s | driver 构建 95 s（emitc + cc 约 80 s）；测试目标从开始到第一条 PASS 134 s（emitc + 测试 TU 的 cc） | ~300 s | ~215 s |
| wasm-target | 246 s | 「the C driver, once」74 s，减去 JVM emitc 约 15 s，cc 约 60 s | ~200 s | ~200 s |
| native-diff-1 / -2 | 281 / 383 s | 每个语料程序一次 emitc、两次 cc，但程序都小，K=1 | 不变 | 不变 |

估算法：cc 部分乘以 §4.2 的四核比例 14.8 / 69.5 = 0.21（runner 也是 4 vCPU），其余不变。这是**估计**，
不是 CI 实测；刀 2 落地时按 CI 纪律报真实墙钟。prev-diff-native 落到约 410 s 后，pole 换成
native-diff-2（383 s）或 test-compiler 一档，push-total 约省 125 + 60 + 45 ≈ 230 job 秒（刀 2），
刀 3 再省约 85。

## 八、风险

- **单个函数很大怎么办**：原子是函数，最大的函数（Unicode 表构建器约 0.9 MB，但全是常量行，编得快）
  决定最长段的下限；现在 seq K=16 的最长段 4.4 s，离这个下限还远。
- **段数多了头部重复解析**：见 §5.2，K=16 时 CPU 合计仍比单 TU 少。
- **调试与 ASan**：nightly 的 native-asan 行仍可以吃单 TU（整份文本合法），不受影响。
- **wasm**：wasm 行编的是 Playground 程序与 DOM 契约里的小程序，K=1，不变；
  wasm-target 里编 dawnc（宿主）那一步属于刀 2。

## 九、不做的（理由）

- **不按模块切**：`check/checker` 占 15.3%，模块为原子时 K 再大也停在约 8.5 s（§4.1）。
  模块边界看起来自然，但它不是 cc 的成本边界。
- **不用 LPT（按大小装箱、打乱顺序）**：只比连续切快约 10%（4.0 对 4.4 s），代价是函数在文本里
  的位置每次加一个函数就整体重排，emit 语料 diff 不可读、段的内容不稳定。
- **不让 K 跟核数走**：同一源码在不同机器发出不同 C，fixpoint 与发布的逐字节比较失去意义（§5.2）。
- **不在本线开 LTO**：ThinLTO 值约 16% 运行时间，但 4 核上整体慢 11–15 s（§4.5），产物字节还随
  构建目录的绝对路径变（§4.4）；测试档与发布档同 flag 是 #239/#275 的既定做法，只给发布开 LTO 会让
  两档分叉。这份运行时收益先交给 4.a（RC 快路径进 `dawn_rt.h` 内联），4.a 拿不回来再立 LTO 的单子，
  届时先解决路径进字节的问题。
- **不跨测试目标复用 `.o`**（#239 的候选之一）：各目标的可达集不同（`ir/reach` 剪枝）、字典选主
  也按程序算（`reach.dict_owners`），同一模块在两个目标里发出的 C 不相同，复用命中率趋近零；
  今天 native-selfhost-tests 也只剩一个测试目标（#275）。
- **不用 `sh -c … & wait` 绕过 spawn/wait**：§5.3。
- **不换编译器档位换墙钟**（-O1/-O0）：#239/#275 已裁测试档保持 -O2；切分在 -O2 下就拿到了 79%。
- **不改 emitc 发出多个字符串**：一份文本加分界行就够，所有逐字节比较与单 TU 消费者不受影响；
  改成多文件输出要改三十来个脚本与 fixpoint 的比较方式，换不来任何东西。

## 十、落地记录

### 10.1 刀 1：emitc 发共享头 + K 段（`e645c965`）

按 §5.1、§5.2 落地，与设计的出入：

- **nmain 的 K 实测是 15，不是 16**。公式没变（`emitc.tu_count`），§5.2 的 16 是按整份文本 22.7 MB 估的，
  公式量的是函数体字节，nmain 的函数体在 21.0 到 22.5 MB 之间。其它程序：site 3、`tea_dom_search` 2，
  native-diff 与 Playground 一类的小程序 1。
- **entry、`main` 与测试 runner 落在最后一段**，不是段 0。它们由 `emit_program` 与 `c_test_text` 接在
  文本末尾，只用到头部已声明的符号，放哪段都合法；接在末尾就不用在段 0 中间插入。wasm reactor 的 shim
  （`reactor_wrapped`）也接在末尾，因而总与 `main` 同段，调用 `main` 不需要另加声明。
- 没有分界行的文本，`cdriver.split` 原样返回为一个 `main.c`：手写的 C、驱动单测里的一行程序都走这条。
  分界行格式不对或序号不连续是错误，不猜。
- `--split <dir>` 要求目录不存在或为空：编译方取目录里全部 `tu*.c`，上一个更大的程序留下的段会被一起链进去。
- `dawnc build/run/test` 把 K 段写进暂存目录、一条 cc 命令编完（段与段之间不并行，等 4.f）。
- `dict-owner-contract` 原来 grep `^static dawn_dict `，字典去 `static` 后会匹配零行、按「检查是空的」报红，改成 `^dawn_dict `。
- **Emit-Change：无。** C 文本不在任何差分 label 的语料里；`emit ...` 十个 label 在 v0.83.0 窗口里已有声明、
  被遮住，所以另做了真父对照：本提交与父提交各建一个 jar，编同一份源码，十个语料逐字节相同。
- 刀 1 状态下 `native-fixpoint.sh` 仍用旧的单文件配方编新文本，A == B == C 成立；也就是说同一份文本当单 TU 编和
  （刀 2 之后）按 15 段编，链出的编译器发出相同的 C。

### 10.2 刀 2：脚本并行编段（本提交）

- 新增 `scripts/cc-units.sh`：取 `--split` 写出的目录，`xargs -P`（默认全部核，`CC_JOBS` 可改）按文件从大到小
  并行 `-c`，再按固定顺序（段名、运行时、额外的 C 文件）链接。编 nmain 的五处都改用它：`native-fixpoint.sh`、
  `release-native.sh`、`native-selfhost-tests.sh`、`gates.yml` wasm-target 的「the C driver, once」，以及
  `native-cli-diff.sh`、两个 wasm 契约脚本、`site/build.sh` 在没拿到现成 dawnc 时的自建分支，和
  `java-target-classpath-contract` 自建 dawnc 的那一步。
- `bootstrap-guards` 的 TOOL-19 原来逐字钉着 `release-native.sh` 的两条 cc 行；改成钉两条
  `cc-units.sh --static` 构建行，并钉住 `cc-units.sh` 把 `--static` 交给唯一那次链接，另加一个变异体：
  发布脚本仍要 `--static`、构建脚本在链接处丢掉它，守卫必须红。
- `native-fixpoint.sh` 多比一项：A（JVM 上的 `cdriver.split`）与 B（native 上的同一函数）切出的段逐文件相同。
- `gates.yml` 只改 wasm-target 那一步的 `run:`，`steps.lock.json` 随之 `record`。各 job 的 claim 与 push-total
  都没动：还没有 CI 观测，按纪律等 main 上的观测出来再按现有注释格式重述，所以本提交不需要 Gate-Budget 声明。

### 10.3 实测（本机 16 核，clang 18.1.3，-O2；负载来自同机其它任务，括号里是 loadavg）

同一份 nmain C（15 段），只比编译与链接：

| 配置 | 墙钟 | user | 负载 |
|---|---:|---:|---|
| 单 TU，taskset 4 核 | 82.4 s | 81.0 s | 34 → 16 |
| 15 段，taskset 4 核，J=4 | **16.6 s**（−80%） | 60.3 s | 同上，紧接着测 |
| 单 TU，taskset 4 核（高负载那一轮） | 222.0 s | 115.4 s | 62 |
| 15 段，taskset 4 核，J=4（同一轮） | 25.5 s | 81.8 s | 62 |
| 单 TU，不限核 | 136.8 s | 108.0 s | 26 → 31 |
| 15 段，不限核，J=16 | 12.2 s | 83.5 s | 31 |

4 核比例与 §4.2 的集群原型一致（69.5 → 14.8 s）。J=16 与 J=4 链出的 dawnc 逐字节相同。

整脚本，同一棵树、前后紧接着跑（负载 14 → 7）：`native-fixpoint.sh` 旧配方 **167.4 s**，新配方 **52.7 s**。
`release-native.sh` 两次独立的 `--static` 链接逐字节相同（`cmp` 那一项绿）。
`--static` 链接时 `dawn_gpu_open` 的 `dlopen` 警告在改动前的单 TU 链接里同样出现，不是本刀引入的。

CI 墙钟仍按 §七估计（prev-diff-native 约 −125 s、native-selfhost-tests driver 构建约 −60 s、wasm-target 约 −45 s）；
真实数字要合入 main 后从 Actions 观测。

### 10.4 wasm

K 段在 wasm 路径上成立，不需要给 wasm 特判 K=1：`tea_dom_search` 恰好是 K=2，用本刀的 dawnc 以
`DAWN_WASM_CC=clang-20 dawnc build --target wasm --reactor` 构建通过；`dawnc build --target wasm` 与原生行一样
把各段放在同一条 clang 命令里，wasm-ld 链接多个目标文件没有额外条件。wasm-target 里编宿主 dawnc 的那一步按原生
走 `cc-units.sh`。
