# checker 诊断 golden 语料（#88 刀 0）

`scripts/grammar-corpus/` 把**语法**的期望变成可执行的；这里是它的 checker 版本，
把**类型检查的诊断**变成可执行的期望。两者形状刻意保持一致（`cases/` + `run.sh` +
进 gates.yml），差别都在下面写清楚了。

## 它存在的理由

动工前的勘察结论：**checker 的诊断在全仓没有任何 golden。** `checker.dawn` 里
240 个 `cerr` / `cerr_h` / `cerr_o` 调用点只被 88 个内联 `test` 守着；
`grammar-corpus` 只走 `dawn __parse`（解析器诊断），`spike-native` 只比程序 stdout，
`selfhost-core-diff` 只比 Core IR——**一次改变诊断措辞、位置或顺序的重构，
没有任何门禁会红。**

而 `diags` 是全仓读得最多的字段，`cerr` 是**顺序敏感的追加**（`cx.diags ++ [d]`）。
接下来 checker.dawn（11308 行）要拆文件、拆状态；这份语料先把「改之前它说什么、
按什么顺序说」录下来，重构后逐字节比对。

## 检查什么，不检查什么

**检查**：每个 case 编译出的**全部诊断，按发出顺序，逐条**——span（码点偏移）、
消息、hint 都在内。顺序是首要理由：把一条诊断挪到另一条前面，是这份语料能看见、
而任何「单条消息断言」看不见的变化。

**不检查**：`diag.dawn` 的人类渲染（那由它自己的内联 test 与
`selfhost-prev-diff.sh` 守），也不检查诊断之外的东西——`dawn check` 输出里的
`M` / `F` / `C` 行由 `selfhost-core-diff` 一侧覆盖，这里只留 `D` 行。

**不只是 checker 的**：诊断流是一条，`analyze.dawn` 的模块加载诊断（`imports` case
里的「module `lib` is imported more than once」）与 checker 的混在一起按序发出。
录的是这条流的全貌，因为**顺序也是流的性质**——只挑 checker 那些会把「谁在谁前面」
这件事丢掉。覆盖率那一侧只数 `cerr`。

**只到 checker**：`run.sh` 先用 `dawn __parse` 确认每个 case 解析干净。
一个解析不过的 case 根本到不了 checker（`analyze.dawn` 在模块有解析诊断时跳过
`check_module`），它的 golden 会**悄悄变成解析器的 golden**——所以那是坏 case，
不是新期望。

## 目录与格式

    cases/<name>.dawn        单文件 case
    cases/<name>.expected    它的 golden
    cases/<name>.d/          需要第二个模块的 case（跨模块导入、孤儿 impl）
    cases/<name>.d/entry.dawn  入口；同目录其余 .dawn 是它 `use` 的模块
    cases/<name>.expected    多模块 case 的 golden 也在这一层

golden 的每一行就是 `dawn check` 的 `D` 行，只把路径缩成 basename：

    D	<file>	<lo>	<hi>	<msg>	<hint>

`lo`/`hi` 是**码点偏移**（前端的 span 货币，见 `ast.dawn`）。它对 case 文件的
任何空白改动都敏感，这是**故意的**：位置错是这份语料要抓的缺陷之一，而 case 文件
在重构期间本来就不该动。

## 跑

    ./scripts/checker-corpus/run.sh            # 比对
    ./scripts/checker-corpus/run.sh --record   # 重录（改了 case 或有意改了诊断时）

`--record` 同时重写 `uncovered.txt`（见下），并**保留已写好的理由列**。

## 覆盖率与 `uncovered.txt`

golden 只能钉住「某个程序产生了什么」；它对**没有任何 case 触发的诊断**一无所知，
而那恰恰是重构最容易改错而无人察觉的一条。所以 `coverage.py` 从反方向走：
枚举 `selfhost/src/checker*.dawn` 里每一个 `cerr` 调用点，看录下来的 golden 里
有没有它的消息。

`uncovered.txt` 列出没被触及的调用点，**双向棘轮**（同 `spike-native/known-red.txt`）：
新增一个未覆盖的点会红，一个已列出的点变得可达却没划掉也会红。条目按**消息签名**
索引而不是行号——因为这份语料要守的重构正是「把代码搬到别的文件里」。

覆盖率是**按消息文本匹配**的启发式，不是执行覆盖率，有两个已知的钝处，都是有意接受的：

- **同文异地**：`duplicate type parameter names` 在三个声明位置各写了一份，
  文本匹配分不开它们。语料对三处各写了 case，但计数上它们是一组。
- **同址异支**：一个 case 从某条分支到达某个点，与它本来想走的分支不同，也算到达。
  措辞由 golden 钉，不由这个脚本钉。

匹配方式是「消息表达式里的字面量块，按原顺序用 `.*` 连起来的正则」，而不是
单块子串——后者会让「含有某个词组」的消息误算成覆盖。间接消息
（`let msg = ...`、`named_arg_msg(...)`）会顺着同文件的绑定与函数体展开两层。

## 与宿主 JDK 的耦合（两个 case）

`java_calls` / `java_bridge` / `java_ambiguous` 的 hint 引用宿主自己的反射结果
（候选构造器/重载列表）。类和成员是**挑过的**：`java.lang.Object` 只有一个公共
构造器、`Math.abs` 的四个重载自 1.0 未变、歧义那对只列并列的两个候选。
若某天 JDK 改了这些集合，红的是这两条 case，且诊断信息会直接说出差在哪。

## 录制时撞见的现象

录 golden 只记录当前行为，不修。撞见的可疑点已单独列给 #88 立案，不在这里重复。
