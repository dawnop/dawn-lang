# `dawnc check` 的冷启动：0.85 s 花在哪，拿回了多少

> 状态：**current / F0 已落地**。起因是效果 fiber 与 runner 常驻的调研
> （`~/workspace/agent-handoff/research-fibers-resident-runner-20261011.md`，内部，未入库）
> 量出 `dawnc check` 在任何输入上都要约 0.85 至 0.9 s，空程序、23 KB 程序、语法错误的文件同价；
> 裁决（`ruling-fibers-resident-runner-20261011.md` 第 1 条）要求先剖开它，再动手压。
> 本文是那份剖面、两刀改动与没做的事。

## 1. 病

`dawnc check x.dawn` 在读用户文件之前就把整个 std 加载一遍：`load_chosen_std` 对 `modules.txt`
里的 27 个模块依次 lex、parse、check、跑 comptime（`driver/stdlib.dawn`）。用户文件的那一份
只占个位数到几十毫秒，所以固定成本摊给每一次调用：Playground 的 `/check`、CLI、LSP 冷启，
以及任何拉起 `dawnc` 的脚本。

## 2. 剖面（native，改前）

perf、strace、valgrind 本机都没有。方法：在 `load_chosen_std` 的每个阶段前后读单调钟
（`io.with_clock_real` 包一层 `now_wall_ns`），累加后一次性打到 stderr；`nmain.cmd_check` 再包住
`load_std`、`load_target`、`analyze`。插桩补丁不入库，存在
`~/workspace/agent-handoff/f0-profile-instrumentation-20261011.patch`（对 `3404a9ba` 打）。
gprof（`cc -pg`）只用来排除嫌疑：它给 `dawn_unbox_unit` 的 22% 自身时间是 mcount 的伪影
（该函数全文件只有 42 个调用点），所以下表一律用钟，不用 gprof 的占比。

下表是 `dawnc check`（空程序）改前，三次运行的区间；机器 load average 6 至 10，绝对值偏悲观：

| 阶段 | 用时（ms） | 占比 | 说明 |
|---|---:|---:|---|
| 进程启动、运行时初始化、退出 | 16–20 | 3% | `dawnc --version` 实测 16 ms |
| 取 std 文本（embedded `stdsrc`） | 1–2 | 0% | 字符串常量，不解码 |
| lex + parse，27 个模块、10.3 万个 token | 195–230 | 40% | 其中 lex 约 100 ms（`code_points` 解码约 22 ms），parse 约 100 ms |
| check，27 个模块 | 190–240 | 40% | 头部（注册声明、导入、签名）约 25 ms；函数体与 test 块约 170–210 ms |
| comptime（常量折叠与 `comptime` 块） | 25–35 | 6% | 其中每个模块建一次解释器上下文，合计约 25 ms |
| 合并导出、impl 表、ADT 表 | 6–8 | 1% | |
| 用户文件：读、parse、check | 2–3 | 0.5% | 23 KB 的 300 个函数约 40 ms |
| 合计 | 约 470–540 | | 对得上外部量到的墙钟（本机安静时 520–540 ms） |

说明三点：

- 调研报告里的 0.85 至 0.9 s 是 load 约 10 时的读数；同一个二进制在 load 6 时是 0.52 至 0.54 s。
  下面所有前后对比都在同一时段交错取最小值，比较的是比例。
- 「Core lowering」不在 `check` 里：lowering 在 `emitc`/`build` 里做，check 里只有 comptime 按需
  lower 它要折叠的那几个函数，已经计在 comptime 一行。名字解析不单列，它是 check 头部的一部分。
- 语法错误的文件也付全额，因为 `cmd_check` 先 `load_or_die` 再 `load_target`。

**插桩的负控**（裁决要求先证明剖面会红）：在 parse 阶段每个模块人为空转 10 ms（27 个模块，共
+270 ms），parse 一行从 215/335/256 ms 变到 581/517/489 ms，增量 +365/+182/+233 ms；
机器 load 约 10，别的阶段同时也漂了 ±50%，所以单次增量散得开，但方向与量级对，而且只有被注入的
那一行成倍增长。

## 3. 改了什么

两个提交，各自独立可回滚。

### 3.1 语法错误的文件不加载 std（`d8bb52d7`）

内嵌 std 时，若 `load_target` 出来的每个模块都 parse 失败，就没有任何模块会被 check，最终诊断是
loader 的诊断加各模块的 parse 诊断，与 std 无关。`syntax_failure_diags`（`driver/analyze.dawn`）
就按 `analyze_program` 的同一个顺序和同一个 `rendered_diags` 算出这份列表；只要有一个模块 parse 成功，
就返回 `None`，调用方再加载 std 走原路。`nmain.cmd_check` 按目标逐个这么做，std 第一次需要时才加载，
且只加载一次。

只在内嵌 std 时生效。`--std`/`DAWN_STD` 指向目录时 `std_identity` 会把「恰好是 std 自己的源文件」
改名，哪些文件是 std 的是目录的事实，必须先加载 std 才知道，所以保持原顺序。

测试：`analyze.dawn` 里有一条，两个模块都不能 parse 的项目，断言快路径的列表与
`rendered_diags(analyze_program(...))` 逐项相等；再把其中一个改好，断言返回 `None`。

### 3.2 内嵌 std 不查 test 体与两个只会加诊断的报告（`3404a9ba`）

`Cx.std_trusted`（新字段，frame-triage 里归「模块身份」）打开时，checker 对该模块：

- 不检查 `test` 块的函数体（语法与导入仍然算数：第一版直接把 test 块从 AST 里剪掉，
  `std/list` 立刻报 `unused import: str`，因为那个导入只被 test 用）；
- 不跑 `report_self_recursion` 与 `report_unused_imports`，二者在 `cx.diags` 为空时只可能追加诊断。

`load_chosen_std_lean` 在内嵌 std 时设这个字段；`nmain` 的 `check`、`emitc`、`build`、`run`、
以及非 `--stdlib` 的 `test`，JVM 驱动的 `check`，走它。目录形式的 std（`--std`、`DAWN_STD`）
保持全查：改 std 的人正是靠 `dawn check` 发现 test 里写错了。读 `StdCtx.mods` 里 std 测试的
`test --stdlib`、`doc`、LSP、JVM 的 emit 路径也保持全加载。CI 在每次 push 上用全加载检查内嵌 std
（`test --stdlib` 与 `the embedded std matches std/ on disk`），所以被跳过的检查没有失去守卫，
只是不再让每个用户重复付一遍。

两种加载的差别被一条测试钉住（`driver/stdlib.dawn`）：每个 std 模块的类型化函数、常量、comptime
值，ADT 表、impl 表、导出表、源文本逐项相等；类型化的 `tests` 为空；intern 表只少 test 声明自己的
那些身份（路径首段是 `Named(TestDecl, _)`，已断言），其余逐项相等。身份少了意味着：一个用户声明
若恰好哈希撞上 std 某个 test 声明的身份，不再被报告。身份的摘要含 owner，用户模块的 owner 不是
`std/...`，所以这只在真哈希碰撞时才有观测差别。

## 4. 量

native `dawnc check`，交错取 15 次最小值，CPU 时间（墙钟只差 1–3 ms）：

| 输入 | 改前 | 改后 | load average |
|---|---:|---:|---|
| 空程序（27 B） | 520 / 539 / 593 ms | 411 / 409 / 460 ms | 6.0 / 6.3 / 10.5 |
| 23 KB、300 个函数 | 578 / 621 ms | 455 / 468 ms | 6.5 / 10.6 |
| 语法错误的文件 | 529 / 538 ms | 2 ms | 8.8 / 10.0 |

三组是不同时段各自交错的结果，组内可比，组间只看比例：空程序与 23 KB 程序 −21% 至 −24%，语法错误 −99.6%。

JVM `dawn check`（`java -jar`，最小值 5 次，load 9.5）。embedded std 才有收益；checkout 里的
`bin/dawn` 设了 `DAWN_STD`，走目录形式，不变：

| 输入 | 改前（v0.86.0 jar） | 改后，内嵌 std | 改后，`DAWN_STD=std` |
|---|---:|---:|---:|
| 空程序 | 1224 ms | 1012 ms | 1219 ms |
| 23 KB 程序 | 1260 ms | 1092 ms | 1268 ms |
| 语法错误 | 1225 ms | 1117 ms | 1336 ms |

JVM 的 `check` 走 `project_plan_for_load` 与 `analyze_target_scoped`，没有套语法错误快路径（§5）。

`./bin/dawn test selfhost` 墙钟：改前 92.1 s（load 9.3），改后 85.3 s（load 9.9，多了 3 条测试）。
JVM 测试用 `DAWN_STD`，不走 lean，所以不该变；差在噪声内。

输出对拍：改前改后两个 native 二进制，对 `examples/` 下全部 53 个单文件与项目目录、
`scripts/checker-corpus/cases` 全部 226 个文件，各跑 `check` 与 `emitc`，状态码、stdout/stderr 文本、
`emitc` 产出的 C 全部逐字节相同（279 个输入，0 处差异）。没有 `Emit-Change`。

## 5. 不做的（理由）

- **按导入图只 check 可达的 std 模块（std-pruning-design §6 的方案 b）。** 裁决已关（2026-09-06）。
  这次的 lean 加载不改变「哪些模块被加载、被 check」：27 个模块仍然全部 parse、check、comptime，
  变的只是其中 test 体与两个只加诊断的报告。理由仍成立：impl 在整个程序里相干（`stdlib.dawn`
  文件头的相干性规则），ADT id 的顺序计数器会随模块集合漂移，`no bundled std module` 的候选清单
  与 Core golden「三程序 std 同 dump」都依赖全量。该文 §6 写的重开门槛是「check 时间自己变成瓶颈」；
  Playground `/check` 的 0.9 s 加每个 `dawnc` 用户的冷启动，已经是这个门槛。是否重开是一条要另裁的
  决定，本刀不替它裁。剩余 check 时间里被 test 与报告占去的部分已经拿到，(b) 再省的是模块集合本身。
- **把检查过的 std 序列化进二进制，启动时反序列化。** 不干净。AST 与类型化树的布局随编译器自身
  变；种子协议要求 HEAD 的源码只依赖种子支持的语言，而快照必须由同一代编译器生成，等于多出一级
  自举，且 `native-fixpoint` 的 B==C 要把快照算进去。`StdCtx` 里还有闭包（`Cx.jsig`），
  运行时的堆对象带函数指针，不能原样落盘。只缓存 AST（lex+parse，约 200 ms）能绕开类型化树，
  但仍要一个对每个 AST 节点的通用序列化器，Dawn 没有 derive（外部评审吸收裁决：否 derive）。
  需要的话，这是一个独立的设计，不是 F0 的便宜改动。
- **磁盘缓存（`~/.cache` 里放序列化的 std）。** 同上，另加：沙箱里的 `dawnc` 读自己可写的缓存是
  内存不安全的输入面；让输出依赖一个会过期、会被截断的文件；`dawnc` 从无状态变成有状态。
  语言纯洁与架构优雅的判据下不取。
- **并行 parse 27 个模块。** 模块之间 parse 互相独立，是最直的并行点，但仓里没有并行原语
  （10-04 裁决：多线程形态先钉不实施）。
- **跳过没有常量也没有 `comptime` 块的模块的解释器上下文。** 做出来了（先扫一遍体，没有就
  不建上下文），实测只省 4 至 7 ms：std 的大多数模块有常量。撤回，不值得多出来的扫描代码。
- **`text_of` 对 1 至 6 个字符的窗口用字面量列表。** 词法里这一步占 lex 的约四分之一，试了，
  没有快：撤回。lex 与 parse 的耗时是整体的 RC 与持久向量成本，没有单点。
- **`-DDAWN_RT_INLINE_RC`。** 量过：check 只快约 5%（空程序 573→515 ms 与 548→521 ms 两对），
  而 `native-inline-design.md` 记着它让 nmain 的 cc CPU +83%，已裁「默认关」。
- **`MADV_POPULATE_WRITE` 预取 slab 批次。** 想省 sys 时间（缺页约 2.2 万次，sys 约 45 ms）。
  试了：缺页计数没变，耗时没变。撤回。
- **JVM 驱动的语法错误快路径。** JVM 的 `check` 走另一套计划与加载（`project_plan_for_load`、
  `analyze_target_scoped`，按目标分别 plan），要在那里复制同一个「全部 parse 失败」判断，才能让
  Playground 之外的 JVM 路径受益。JVM `check` 不在任何延迟敏感的路径上，没做。
- **JVM 的 emit 路径用 lean。** `collect_program_full` 把 `std.mods` 里 std 模块的类型化树交给
  emit，不能证明 std 的 test 方法不进 class 骨架，且没有收益需要。没碰。

## 6. 之后

改后空程序 `dawnc check` 约 0.41 s（load 6），高于裁决第 3 条设的「~0.3 s 以下就不做 C0」的线。
剩下的构成大致是：lex 约 100 ms，parse 约 100 ms，check 约 100 ms（头部 25，函数体 75），
comptime 约 25 ms，进程与其余约 30 ms。每一项都是平的：没有单个函数占一成以上，剩下的是
RC 与持久向量的整体成本。再往下压只有两条路：(b) 少 check 模块（要另裁），或把 std 的前端成果
缓存起来（上面两条不做的理由要先被推翻）。C0（暖编译 worker）是否上，按裁决第 3 条
仍然悬着，数据在这里。
