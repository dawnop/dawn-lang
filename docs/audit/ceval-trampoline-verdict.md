# `ceval` trampoline 化：收益重估与裁决

> 状态：**current**（2026-07-31）。这份文档结掉
> [purity-boundary-design.md](purity-boundary-design.md) 步骤 3 的冻结，
> 撞车登记见 [native-plan-overlap.md](native-plan-overlap.md) §3.5。
>
> **裁决：不做。** 理由不是「以后再说」，是实测把这一步的招牌收益打散了——
> 摘 `-Xss512m` 既不靠它、也不能只靠它。第五节写明什么事实会把它翻回「做」。

步骤 3 原本冻在 R6（「interp 吃 Core 还是吃 TAST」）上。R6 已于 2026-07-25 关账
（`../native-backend-plan.md` §7：interp 读 Core），冻结的原因随之消失，剩下的问题是
2026-07-30 表头留的那句：**收益要与栈深实测一起重估**。本文就是那次重估。

## 一、量了什么、怎么量的

宿主：WSL2 / Linux 6.18 / 16 GB，JVM 为 OpenJDK 26.0.1，编译器为
`build/dawn-selfhost.jar`（2026-07-31 构建）。

**每一次编译器调用都跑在 `( ulimit -v 4194304; timeout 120 … )` 里，串行，一次一个进程。**
这不是讲究：2026-07-31 01:43 的上一轮同题调研把一份深合成输入喂给 native 编译器，
`dawnc-A` 涨到 13 GB RSS 触发全局 OOM 冻住了整台虚拟机（§四）。合成输入一律从
nesting 100 起步、每步 ×4、遇到第一次失败就停。

JVM 侧统一压成 `-Xmx700m -XX:CompressedClassSpaceSize=128m -XX:ReservedCodeCacheSize=64m
-XX:MaxMetaspaceSize=256m`——这是 4 GB 地址空间下能跑完整个 selfhost 构建的配置，
不是调优结果。地址空间本身就是第一个测量结果，见 §3.1。

## 二、trampoline 的工作量，按今天的代码数

`ceval`（`selfhost/src/ir/interp.dawn:1030–1236`）对 `CExpr` 的 **33 个构造器有 33 个臂**，
与 `selfhost/src/ir/core.dawn:85–176` 的 33 个构造器一一对上，没有 catch-all。分类：

| 类 | 条数 | 臂 |
|---|---:|---|
| **叶子**（不求值任何子表达式） | 12 | `CInt` `CFloat` `CBool` `CStr` `CUnit` `CLocal`(1038) `CFnRef`(1058) `CConstRef`(1184) `CComptime`(1196) `CBreak`(1209) `CContinue`(1210) `CDictRef`(1215) |
| **单子表达式** | 10 | `CBox`/`CUnbox`/`CDup`(1044–1046，纯透传且在尾位) `CField`(1110) `CIsCtor`(1115) `CTagOf`(1120) `CTupleGet`(1129) `CUnary`(1141) `CDictArg`(1223) `CReturn`(1201) |
| **顺序 n 个子表达式**（走 `eval_all`） | 7 | `CCtor`(1106) `CTuple`(1125) `CListLit`(1136) `CDictApply`(1219) `CIntrinsic`(1102) `CClosure`(1047) `CForeign`(1211→`eval_java:997`) |
| **多点 / 控制流** | 4 | `CIf`(1160) `CBinary`(1140→`eval_binary:1242`) `CBlock`(1171) `CCall`(1060) |

**已经显式化的那一半是真的。** `Ctl`（`interp.dawn:63–70`）有 `KErr`/`KReturn`/`KBreak`/
`KContinue` 四个构造器，`ER`/`SR`（`interp.dawn:88`/`90`）把它们编成返回值：非局部退出
（`?`、`return`、`break`、`continue`）已经是值，不是异常。trampoline 不需要重新发明这一半。

**缺的是续延。** 每一处 `let (st1, env1, v) = ceval(…)?` 都是一个隐式宿主帧，全文件有
31 个这样的调用点。而且——**这才是工作量的真相**——`ceval` 不是一个递归函数，
是一张**十二个函数的互递归网**：

`eval_all`(1012)、`eval_binary`(1242)、`exec_cstmt`(1386，`CStmt` 6 个臂)、
`exec_loop`(1442)、`call_cfun`(505)、`call_named`(571)、`call_default`(545)、
`apply_fn`(559)、`call_builtin`(708，其中 `sort_by` 经 `merge_sort:926` 回调 `apply_fn`)、
`eval_java`(997)、`get_cfun`(474)、`lower_into`(350)。

**只要有一个还在宿主栈上，整张网就还在宿主栈上。** 所以真实 scope 不是「33 个臂」，
是「33 + 6 个臂，外加十二个函数的调用协议改成显式帧」。原方案写的「30 余个构造器」
是对的，但它没数这一层。

## 三、谁需要 `-Xss512m`

`-Xss512m` 在仓库里有 **18 处**，分两个角色：

| 角色 | 落点 | 性质 |
|---|---|---|
| **A. 编译器进程自己的栈** | `bin/dawn:51,130,133,142`；`scripts/` 下 12 处（fixpoint / prev-diff / fmt-diff / lsp-diff / run-diff / bench / replay-bootstrap / native-fixpoint / array-contract） | 步骤 3 想摘的就是这半 |
| **B. 传给被 spawn 的用户程序** | `selfhost/src/main.dawn:748`（`maybe_with_deps` 的 re-exec）、`:781`（`spawn_java`，`dawn run` / `dawn test` 走它） | **不是债，是决策**——`../native-backend-plan.md:29`「一般尾调**不做**，大栈代替」 |

`ceval` 与角色 B 毫无关系。下面全部是角色 A 的测量。

### 3.1 512 MB 在地址空间受限处根本起不来

固定 `-Xmx700m` 等参数，只变 `-Xss`，跑 `java -version`：

| `-Xss` | 512k | 1m | 4m | 16m | 64m | 128m | **256m** | **512m** |
|---|---|---|---|---|---|---|---|---|
| `ulimit -v 4194304` 下 | 起 | 起 | 起 | 起 | 起 | 起 | **VM 起不来** | **VM 起不来** |

`-Xss` 设的是**每个线程**的栈，JVM 启动就要建十来个线程，于是 512 MB × N 直接撑爆 4 GB
地址空间。purity-boundary §1.3 说的「在容器里会撞 `ulimit`/cgroup 的内存核算」是对的，
这是它的数字：**4 GB 地址空间上限下，`-Xss` 不能超过 128m。**

### 3.2 真实语料一个都不需要大栈

| 语料 | `-Xss256k` |
|---|---|
| `build selfhost`（31,175 行，最深文件 `checker.dawn` 9,396 行，含全部 const 折叠 + lower + codegen） | **通过** |
| `__check` packages/json、packages/web、packages/inflate、packages/sha2、site、playground | **全部通过** |

参照量：`-Xss256k` 只能承载 **2,766** 个平凡 Java 帧（512k→8,185，1m→22,338，8m→476,427）。
也就是说**整个仓库的真实代码，编译器在两千多帧之内就跑完了**。角色 A 的 512 MB 全部是
对抗「生成的 / 恶意的深输入」的余量，一行真实代码都用不上。

### 3.3 深输入下，先倒的不是 `ceval`

合成输入，`-Xss1m`，二分到最深可过的层数；栈顶帧按方法归并统计：

| 输入 | 最深可过 | 爆栈时占满栈的 pass | 每层帧数 | 每层栈字节（≈） |
|---|---:|---|---:|---:|
| 嵌套 `{ let v = 1; … }` | **142** | **parser**（`statement`/`stmt_and_sep`/…） | 18 | 7.2 kB |
| 嵌套 `match` | **148** | **parser** | 16 | 6.9 kB |
| 右嵌套括号 `1 + (1 + (…))` | **153** | **parser** | 16 | 6.7 kB |
| comptime 非尾递归 `rec(n)` | **159** | **interp**（`ceval`/`eval_binary`/`call_named`/`call_cfun`） | ~5 | 6.4 kB |
| 长 `++` 链 | **323** | **checker**（`check_expr`/`check_expr_at`） | 2 | 3.2 kB |

parser 那条链每层烧 16 个帧，一层不落：

```
parser.expression → pipe_expr → or_expr → and_expr → cmp_expr → bor_expr
→ bxor_expr → band_expr → shift_expr → concat_expr → add_expr → mul_expr
→ unary_expr → postfix_expr → primary_expr → paren_expr → (下一层)
```

线性可外推（右嵌套括号，SOE 出现的区间）：512k → (25,100]，1m → (100,400]，
8m → (400,1600]，64m → (6400,25600]。**栈翻 8 倍，能吃的嵌套深度就翻 8 倍。**

**这一格是裁决的核心：**`ceval` 在五类深输入里排第四，parser 比它更早倒，
且没有任何一类深输入是 `ceval` 独占的。把 `ceval` trampoline 掉，
角色 A 的 `-Xss` 下限由 `max(parser, checker)` 接管——只是换了个先崩的 pass。

## 四、comptime 深度的实情

`MAX_CALL_DEPTH = 100000`（`interp.dawn:163`），在 `call_cfun`（`interp.dawn:513–515`）
入口检查，命中给的是**干净诊断**：

```
comptime: call depth limit (100000) exceeded
  hint: deep recursion does not fit comptime; use a loop or fold
```

问题在于**这个界要多大的宿主栈才够得着**。`const DEEP: Int = rec(100100)`：

| `-Xss` | 结果 |
|---|---|
| **64m** | `Exception in thread "main" java.lang.StackOverflowError`（1024 帧全是 `interp.ceval`/`eval_binary`/`call_named`/`call_cfun`）——**未捕获，编译器进程直接死，一条诊断都没有** |
| **128m** | `comptime: call depth limit (100000) exceeded` —— 干净诊断，exit 0 |

**分界线在 64m 与 128m 之间。** 也就是说：`MAX_CALL_DEPTH` 这个常量只有在
`-Xss ≥ 128m` 时才是真正生效的那道界；低于它，宿主栈先赢，而 ERR-01 之后
`StackOverflowError` 不在 `catch_panic` 里，结果是崩溃而不是报错。
**`-Xss512m` 是这个下限的 4 倍**——Kotlin 版 64 MB 那个「无实测出处」的数字，
今天有出处了：**64m 不够，128m 够。**

各栈尺寸下 comptime 能折的最深非尾递归（二分）：

| `-Xss` | 256k | 512k | 1m | 8m | 64m | 128m |
|---|---:|---:|---:|---:|---:|---:|
| 最深 | <100 | <100 | ~159 | ~1,337 | ~40,000 | >100,000（`MAX_CALL_DEPTH` 先命中） |

不是严格线性——长跑会让 JIT 把解释器循环编译掉、帧变小。**这个数本身是 JIT 相关的，
不该被当成常量写进任何地方**，这一点对下面的建议 1 有影响。

**同一段递归，编译执行 vs comptime 解释：**

| `rec(100000)` | 1m | 2m | 3m | 4m | **8m** | 64m | 128m |
|---|---|---|---|---|---|---|---|
| 编译成 jar 跑 | SOE | SOE | SOE | SOE | **通过** | 通过 | 通过 |
| comptime 折叠 | SOE | — | — | — | SOE | SOE | **诊断** |

**解释同一段递归比编译执行它多吃 16–32 倍宿主栈。** 顺带把角色 B 也量了：
用户程序做 100,000 层非尾递归只要 8m，`-Xss512m` 给的是约 640 万帧的余量。

## 五、native 侧的现状（grep + 事故记录）

> 本节记的是 **2026-07-31 上午**的状态，当天下午两个缺陷都关掉了——**读之前先看 §5.1**。

**今天 native 没有设任何栈。** `runtime/c/dawn_rt.{c,h}`、`selfhost/src/nmain.dawn`、
`selfhost/src/c/cdriver.dawn`、`selfhost/src/c/emitc.dawn`（发的 `int main` 在 `emitc.dawn:1504`）
里 **没有** `pthread_attr_setstacksize`、没有 `setrlimit(RLIMIT_STACK)`、没有任何栈尺寸设置。
`../native-backend-plan.md:166–167` 把「大主线程栈（`pthread_attr_setstacksize`）」列在
Phase 3 的运行时其余项里——**没落地**。native 今天吃的是 OS 默认 8 MB。

运行时里唯一显式化的栈是 `dawn_drop` 的工作表（`runtime/c/dawn_rt.h:295–299`、
`dawn_rt.c:262–265`，`DAWN_WS_INLINE 32`），注释自己写明了理由：
「不这么做的症状是只在大输入上出现的 segfault」。**这句话对整个 native 编译器都成立，
而只有 `dawn_drop` 照做了。**

事故记录（`/var/log/kern.log`，2026-07-31，上一轮同题调研）：

```
01:41:05  dawnc-A[7902]: segfault at 7ffc09e0dff8 ip … sp 00007ffc09e0e000 error 6
          （另有 8 次同形态，01:41:05–01:42:17，pid 7907/7912/7950/7967/8276/8407/8410/8643）
01:43:50  Out of memory: Killed process 8923 (dawnc-A)
          total-vm:15762852kB, anon-rss:13076768kB   ← 13 GB，全局 OOM，冻住整台 VM
```

`sp` 正好落在页边界、`error 6`（用户态写不存在的页）——这是**栈保护页**，
即 native 版的栈溢出：**信号 11，没有任何消息**。JVM 侧至少还给一行
`StackOverflowError`。而 01:43:50 那次换了一类输入，走的不是爆栈而是 13 GB 驻留内存
——正常编译峰值 81 MB（`../native-backend-plan.md` §7 Phase 4），**非线性程度是 160 倍**。

**本次没有复现它**：复现要先 `__emitc nmain.dawn` 出 4.7 MB C 再 `cc -O2`，是分钟级
且 `cc` 自己就是内存大户；而在 4 GB 上限下它只会变成一次干净的 malloc 失败，
换不来比上面这两行更多的信息。按 brief 的界限，记录，不追。

### 5.1 追加（2026-07-31，§6.1 第 2 笔的两个缺陷都关了）

**(a) 大栈已落地。** `dawn_rt_main`（`runtime/c/dawn_rt.h` 「the program's stack」）
把发射程序的入口跑在 512 MB 栈的线程上，与 JVM 的 `-Xss512m` 同一个数字、同一条决策。
定义在运行时而非发射的 `main` 里：`nmain`/`cdriver` 自己也是发射出来的程序，
所以编译器和用户程序共用一份。同一段非尾递归的最深可过深度：**旧 10 万–20 万 → 新 900 万–1280 万**，
正是 512/8 = 64 倍。门禁 `scripts/spike-native/deep_stack.dawn`（换回旧 `main` 形状即 SIGSEGV 无输出）。
「打一行 stack overflow」的 SIGSEGV handler 实测后**不做**，理由在 `dawn_rt.h` 同一段注释。

**(b) 13 GB 是 `emitc.line` 的二次拷贝，不是 native 独有，也不是栈问题。**
按 §3.3 的五个合成家族逐个喂给 native 编译器（`ulimit -v 4 GB` + cgroup `MemoryMax` + 串行），
只有一个家族非线性：**长 `++` 链**。

| `s ++ s ++ …` 的 n | 400 | 1600 | 3200 | 6400 | 12800 |
|---|---:|---:|---:|---:|---:|
| 修前 native 峰值 | 74 MB | 314 MB | 740 MB | 1949 MB | **4 GB OOM** |
| 修后 native 峰值 | 9.6 MB | 12.0 MB | 17.7 MB | 29.3 MB | 51.6 MB |

外推修前曲线，n≈1.2 万–1.6 万就是 13 GB——事故那一行的量级对得上。
其余四家族（嵌套块 / 嵌套 match / 右嵌套括号 / 深 comptime 递归）内存全平，
只有时间是超线性的；深嵌套的**调用**、`&&` 链、宽 List 字面量、字符串插值也都平——
所以「深」不是判据，`++` 才是。

诊断路径：`dawnc check`（parse+check）全程平（9.6→15 MB），所以在 lower/rc/emitc；
排除了 malloc 碎片（`MALLOC_MMAP_THRESHOLD_`/`ARENA_MAX` 三档 RSS 一字不差）
和 RC 漏（LeakSanitizer 跑整个 native 编译器只报 565 字节）。最后用 `LD_PRELOAD`
的活堆剖析器定位：峰值的 **99% 是 128–256 KB 的对象，全部由 `emitc.line` 里的
`dawn_str_concat` 分配**，调用栈是 `emit_stmt`→`emit_expr`→`emit_stmt`→… 交替。

机制：`line` 曾是 `st.out ++ pad ++ text ++ "\n"`——**每发射一行就整份拷贝一次已发射的全文**。
平时看不见，因为每份拷贝立刻就死；深嵌套下就看得见了：`emit_expr`/`emit_stmt` 是递归下降，
**每一层挂起的帧都握着自己那份 `CSt`**，于是峰值 = 嵌套深度 × 当前输出长度。
`++` 链是唯一会「一个操作数一层嵌套」的输入形状（rc pass 把每个 concat 展成嵌套的
let/drop 块），所以只有它触发。

**这不是 native 独有的**——emitc 是两个后端共用的一份源码，JVM 侧同样中招，只是
GC 把它藏在堆上限后面：修前 `-Xmx200m` 在 n=1600 就 OOM，修后 n=25600 也过。
事故只在 native 上被看见，是因为 native 没有堆上限、直接顶到整机。

修法四行：`CSt.out` 从 `String` 改成 `List[String]`，`line` 追加一块（`push` 是 O(1)
且共享历史），末尾 `join` 一次。发射的 C 逐字节不变（`concat_var(200)` 与
`nmain.dawn` 两份都对过 sha256）。**真实工作量也一起变快**：native 编译器发射
`nmain.dawn`（7.05 MB C）峰值 **489 MB → 125 MB**、耗时 **19.2 s → 7.7 s**。

## 六、裁决：**不做**

把 `ceval` trampoline 化 —— **不做**，把 purity-boundary 步骤 3 就此关账。

四条理由，每条都对应上面一格测量：

1. **不充分。** trampoline 之后，角色 A 的 `-Xss` 下限由 parser（142–153 层/MB）
   和 checker（323 层/MB）接管，两者都不比 `ceval`（159 层/MB）好（§3.3）。
   `-Xss512m` 摘不掉，只是换成 parser 先崩。**招牌收益「`-Xss512m` 从 `bin/dawn`、
   各 diff 脚本里去掉」直接不成立。**
2. **不必要。** 整个仓库的真实语料——包括编译器自己——在 `-Xss256k` 下编译通过（§3.2）。
   角色 A 的 512 MB 从来不是被 comptime 用掉的，是三个 pass 共享的对抗性余量。
   真想调它，今天就可以调，不需要动 `ceval` 一行。
3. **另一半本来就动不了。** `spawn_java`（`main.dawn:748,781`）的 `-Xss512m` 是
   「一般尾调不做、大栈代替」这条决策的实现（`../native-backend-plan.md:29`），
   与 `ceval` 无关。实测：用户程序 100,000 层非尾递归要 8m（§四）。摘掉它是语言退步，
   不是清债。原方案已经承认这一点，本文把它量成了数。
4. **唯一那件真收益，有一行代码的替代。** trampoline 能独占解决的只有一件事：
   深 comptime 递归**崩溃**而不是给出 `MAX_CALL_DEPTH` 诊断。而实测这个洞在
   `-Xss ≥ 128m` 时**本来就是关的**（§四），今天生产用的是 512m ——**洞不在打开状态**。
   在它打开的场景（有人把 `-Xss` 调小、或容器把地址空间压到 4 GB 以下），
   改 `MAX_CALL_DEPTH` 一个常量就能关，成本是 33 + 6 个臂加十二个函数调用协议的几百分之一。

一句话：**这一步要花掉全模块最难改的那部分，换来的是把「三个 pass 都会在深输入上崩」
变成「两个 pass 会在深输入上崩」，而没有任何真实语料位于崩溃区。**

### 6.1 顺手记两笔账（都独立于本裁决，不必一起做）

1. **让 `MAX_CALL_DEPTH` 诚实**（`interp.dawn:163`）。这个常量今天承诺的是一道界，
   但那道界只在 `-Xss ≥ 128m` 时够得着，低于它命中的是 `StackOverflowError`。
   最便宜的修法是在常量旁记下实测的 128m 分界，让下一个想调小 `-Xss` 的人知道
   代价是什么。**不要**把它改成「按栈算出来的动态值」——§四量到这个深度是 JIT 相关的，
   拿一个跑起来才知道的数当界限，比现在这个诚实的常量更差。
2. ~~**native 无栈保护另立一笔**（BUG 类，两个缺陷）。(a) Phase 3 的
   `pthread_attr_setstacksize` 没落地，native 深输入 → SIGSEGV 无消息；
   (b) 某类深输入让 native 编译器涨到 13 GB RSS（正常峰值 81 MB）并 OOM 掉整机。
   两件都不属于 comptime，**不要**并进步骤 3；(b) 尤其该单独查——
   160 倍的非线性不像栈问题，更像某个 pass 在深输入上物化了不该物化的东西。~~
   **两件都已关账，见 §5.1。**「不像栈问题」猜对了；「某个 pass 物化了不该物化的东西」
   也猜对了，但物化的是**发射器的输出缓冲**，而且不是 native 独有——JVM 侧一样，
   只是被堆上限挡住了。

## 七、什么事实会把它翻回「做」

不是「以后再说」，是三条可判定的条件，任一成立就重开：

- **parser 与 checker 先改成显式栈 / 迭代。** 那时 `ceval` 变成唯一还吃宿主栈的 pass，
  trampoline 从「三分之一个答案」变成「最后一块」。**要做就在同一批里做**——
  单独摘掉其中一个，`-Xss` 一分不能少。
- **编译器必须跑在拒绝 512 MB 地址空间的地方**（cgroup / `ulimit -v` / 更紧的
  playground 沙箱）。§3.1 量到的是硬约束：4 GB 上限下 `-Xss` 不能超过 128m。
  真出现这个部署形态，三个 pass 的栈问题一起变成真问题——那时它仍然是三分之一，
  但三分之一变成必要条件。
- **comptime 被要求常规折叠深递归。** 今天 `MAX_CALL_DEPTH` 的 hint 写的是
  「use a loop or fold」，即深递归**本来就不在 comptime 的产品承诺内**。
  这条承诺一旦改口，`ESt.depth` 就必须是唯一的界，宿主栈不能再兜底。

第三条最值得盯：它不是工程约束，是产品决定，而做决定的人未必知道它牵着
一场 33 + 6 个臂的重写。
