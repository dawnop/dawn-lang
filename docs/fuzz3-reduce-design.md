# fuzz3 刀 2：失败程序的归约与回灌草稿

> 状态：**current**。2026-10-19，分支 `test/fuzz3-reduce`。
> 依据：bug 率调研报告 §7.3 刀 2 与 2026-10-04 裁决；刀 1 是 `scripts/fuzz3/{gen.py,run.py}` 与 nightly 的 `fuzz3` job。
> 本文记归约的单位、谓词、批量求值、nightly 预算与实测判据，以及不做的。

## 问题

刀 1 每找到一个分歧，落盘的是生成器的单例程序（`<out>/s<seed>-c<case>-<kind>/case.dawn`，60 到 200 行）
与 `finding.json`。缺陷通常只要其中几行。#632 那次（10-08 一条、10-09 十三条，签名都是
`emitc-crash: panic: rc: unbalanced in <module>: <fn>: released a binding that was not held: N`）
是人手一行行删到 6 行和 2 行的复现，再写成 spike-native 语料和单测。这一步本来就该是机械的。

判据（裁决原文）：对刀 1 找到的每个失败，归约后不超过 20 行。

## 现在失败如何落盘、三方判据是什么

- `run.py` 把一个 batch（20 个 case 一个文件）跑过 JVM `build`、`__emitc` + cc -O2、同一份 C 的 -O0 ASan/UBSan、
  以及把两后端一致的 case 折成 `const` 的 comptime 程序。
- 比较：jvm 与 native 的 stdout、死掉的 case 的退出码、stderr 首行；san 与 native 的 stdout/状态，且 stderr 无 sanitizer 报告；
  comptime 与 jvm 的 stdout。编译失败按 case 二分归属（`rejected` 是生成器的错，`*-crash` 是编译器的）。
- 每个 finding 有 kind 与 `signature()`（kind 加首条消息，数字、名字、路径抹掉），nightly issue 的 verdict 是签名集合的摘要。

## 设计

### 单位：读回生成器的语句结构

生成器把 case 写成以空行分隔的顶层声明，每条语句占整行，块在行尾开、行首关（`stmt`、`block_expr`、`match_expr`）。
所以「按花括号嵌套的行结构」就是生成器的语句树。`reduce.py` 从文本读回这棵树而不是让 `gen.py` 另存一棵：
旧生成器落盘的 finding（例如下面判据用的 10-08 版本）、人手写的程序都能同样归约。读回要求
`render(parse(x)) == x`；对当前 `gen.py` 种子 1–39 的 780 个 case 逐个验过（平均 89 行）。

树的切法：一行把深度从 0 抬到 d 就开一个块；之后一行若跌破上一条结构行留下的深度，它就是分隔行
（`} else {`、`} - 3), b: f({`）或回到 0 的闭合行，其余是块内行，递归切。

编辑就是层次 delta debugging 在这种树上的那几种：

- 删一个顶层声明、一条语句、一个 match 臂；
- 把 `if`/循环/块换成它的某一个分支体（unwrap）；
- 块的每段都只剩一行时并成一行（join）；match 的臂之间用逗号代替换行（spec §1.7）；
  整体并不成时，把单行的一段并到前后两行上（joinseg）；顶层无花括号的多行声明（和类型）并成一行；
- 返回 `String`/`Int`/`Bool` 的顶层函数整个函数体换成字面量（stub）：缺陷常在 case 函数已不再调用的
  helper 里，而模块里每个函数不论有没有被调用都要编译。

`gen.py` 每个 `while` 写的计数自增 `wN = wN + 1`，在它还处在 `while` 里时不删：删了就是只有运行超时
才能结束的循环。归约时单次运行超时从 30 s 降到 8 s，理由同上。

### 谓词：同一种分歧

候选算复现，当且仅当它产生的 finding 里有一条 `key` 与原 finding 相同：

- `key` = `run.signature()`（kind 即哪一对执行器、以哪种方式不一致，加上首条消息的归一化），
  地址（`0x...`）先抹成 `0xH`，rc 的「a return left a binding behind: 3,7,9」里的编号列表并成一个 `N`
  （留下几个绑定是程序的性质，不是缺陷的；不并的话 v0.75.0 那批里同一个缺陷分成五个 key，最长的一个缩不到 20 行）；
- `exit` 再加两边的状态与退出码（`jvm died 1` 对 `native died 134` 与 `jvm died 1` 对 `native died 1` 是两种分歧）。

不保这个，归约就会从给定的缺陷滑到小程序碰巧有的别的缺陷，或者滑到 checker 拒绝的程序（最常见的小程序）。
每种 kind 只编它要的执行器（`LEGS`：`emitc-crash` 不跑 cc，`stdout`/`exit` 不跑 ASan，`comptime*` 不跑 native），
这要求 `run.Batch` 加了三个钩子：`source()`（程序文本从哪来）、`sub()`（子 batch）、`legs`（跑哪几条腿）。
默认值下 `run.py` 的行为不变：v0.75.0 的 jar、10-05 的生成器、种子 1–60，改前改后两份 `run.py`
的 finding 集合逐条相同（970 条），verdict 摘要相同（`fuzz3-7d6373d5da193745`）。

### 批量求值（§7.3 注意事项）

每次求值是一次 JVM build、一次 emitc、一次带全部 std 的 cc，cc 最贵（#239）。所以一轮把多个候选
改名（`c7` → `c1000`、`c1001`……）后放进一个程序当作不同的 case，正是 `run.py` 自己批 case 的方式：
一轮一次编译，而不是一个候选一次。实测（2026-10-19，集群上钉两核，#632 时期的 jar）：emitc 与 build
对 1、6、12、24 份 case（86 到 1839 行）各要 2.0 到 2.4 s，固定成本是 JVM 与 std，不是候选。

- checker 拒绝一个候选会让整批编不过，所以按诊断里的行号把拒绝记到候选上，剩下的再编一次；
- 编译器崩溃没有行号，但消息里有函数名，候选就在名字里。rc 的平衡检查按源码顺序列出前三个不平衡函数
  （`rc.dawn` 的 `list.take(bad, 3)`；实测把 #632 的 case 复制五份，列出的是文件顺序的前三个，与编号无关）。
  所以：被点名且 key 相同的候选是答案；最后一个名字之前没被点名的候选不复现；之后的未知，不再编译。
  消息里没有候选名就退回 `run.py` 的二分。
- 最初的版本没有上面两条（拒绝一律二分）：一轮 49 个候选要 49 次编译器运行，钉 4 核 6 分钟只够 4 轮，
  #632 那条停在 42 行。按行号与函数名归属后同一条 62 s 缩到 11 行，一轮 4 到 7 次编译器运行。
- `emitc-crash` 每轮不跑 JVM build（emitc 自己也做类型检查，拒绝照样看得见），最后单独验证时补上。
- 每轮取收益最大的 24 个单编辑（每个并行 batch 24 个），再加它们的并集与两半；取复现者里最小的；
  一整遍单编辑都不复现就停（1-minimal）。
- 批量只是优化：结果最后单独再验一次（四行 `main`，只留用到的 `use`，JVM 腿必跑），`reduce.json` 记
  `verified_alone`。这次验证自己读 finding，不走轮次用的判定：负控把轮次判定改成恒真时，正是它变红。

### 回灌草稿（人审后入库）

`<findings>/reduced/<finding>/` 下：

- `reduced.dawn`、`reduce.json`（原行数、归约后行数、轮数、verdict：`minimal`/`budget`/`not reproduced`）；
- `spike-native/fuzz3_s<seed>_c<case>.dawn`：程序本体，`main` 改成 `io.println(cN_case())`，头注释说明来历与入库要做的事；
- `spike-native/fuzz3_s<seed>_c<case>.expect.draft`：JVM 的答案（JVM 侧就是 finding 时写明没有）；
- `spike-native/known-red.draft`：这种 kind 预期让 spike-native 哪些检查变红（`emitc-crash` → `:emitc`，`stdout` → `:native`、`:diff`，
  `sanitizer` → `:asan`……，默认 JVM 是对的一侧）。

只是草稿：spike-native 的规矩是 `.expect` 照程序「应当」打印的内容手写（`run.sh` 头注释），所以由人读草稿、判断哪边对、再入库。
`reduced/summary.md` 是总表，也贴进 nightly issue。

### 接到 nightly

`fuzz3` job 里：

1. `reduce.py --self-test`（无编译器，秒级，绿夜也跑）：树的往返、编辑、替身谓词，含两个常量谓词负控。
2. 刀 1 不变（`--minutes 18 --jobs 4`）。
3. 红了才跑 `reduce.py --findings fuzz3-out --minutes 6 --jobs 4`，step 自带 `timeout-minutes: 8`，自身永不判红。
   同一 key 最多归约两个例子，第一例优先；核数先分给 finding，剩下的给每个 finding 并行编几个 batch。
4. 上传 artifact（含 `reduced/`），issue 正文追加总表；verdict 仍是刀 1 的签名集合，归约得更小不算新评论。

墙钟：toolchain 40 s + 刀 1 的 18 分钟与在途 batch（10-19 nightly 实测该 step 18 分 2 秒）+ 归约至多 8 分钟
= 至多约 27 分钟，在 job 的 30 分钟内。归约的 6 分钟在每轮开始前按上一轮的耗时留余量判断，所以最后一轮
最多超出约一轮（4 核上一轮 10 到 30 s），8 分钟的 step 超时只防失控。绿夜只多一个秒级的自测 step。

## 实测与判据

判据：对刀 1 找到的每个失败，归约后不超过 20 行（`reduced.dawn` 全文，含 `use` 与四行 `main`）。
`--check-lines 20` 把它变成退出码：有一条超过 20 行、没单独复现、或没归约到，就退出 1。

**#632（主判据）。** 在 `2c5f1f2f`（#632 两处修复 `38b2fbbc`、`e03e30f5` 之前；集群上构建）的编译器上，
用 10-08 时的 `gen.py`（`3d1c2f11`）重跑 nightly 那两晚的种子（20261008115 与 20261009000–091，93 个 batch），
得到的正是 issue 与 10-10 分诊记录的 14 条（10-08 一条 bug A，10-09 十三条 bug B），签名同一条。
全部归约（`--per-signature 20 --check-lines 20`，集群上钉 4 核、`--jobs 4`，803 s）：

| finding | 原行数 | 归约后 | 单独复现 |
|---|---:|---:|---|
| s20261008115-c7 | 114 | 13 | 是 |
| s20261009000-c8 | 108 | 13 | 是 |
| s20261009009-c10 | 130 | 17 | 是 |
| s20261009010-c11 | 151 | 19 | 是 |
| s20261009019-c11 | 169 | 14 | 是 |
| s20261009020-c14 | 124 | 15 | 是 |
| s20261009035-c6 | 109 | 17 | 是 |
| s20261009043-c14 | 112 | 14 | 是 |
| s20261009044-c15 | 114 | 14 | 是 |
| s20261009049-c1 | 91 | 17 | 是 |
| s20261009054-c17 | 109 | 13 | 是 |
| s20261009055-c14 | 104 | 14 | 是 |
| s20261009066-c7 | 93 | 11 | 是 |
| s20261009088-c7 | 97 | 19 | 是 |

14 条全部 ≤ 19 行，`OK: every finding reduced to 20 lines or fewer and held alone`。归约出来的形状就是分诊时人手缩出的两个：
10-08 那条剩下 `var v3 = [p0]; v3 = v2` 这对普通复制（bug A，`can_fuse_rebind`），10-09 的剩下记录更新里
字段表达式的 `return`（bug B，`reuse` 的 token 次序），例如 s20261009066-c7：

```
fn c7_h0(p0: String, p1: C7R) -> Bool = {
var v1: C7R = C7R { ..p1, b = (if (false) { return (if (false) { true } else { false }) } else { p0 }) }
true
}
fn c7_case() -> String = ""
```

**更多种类（补充）。** v0.75.0 的 jar（刀 1 的正控编译器）、种子 1–60：970 条 finding，七个 key
（`jvm-compile-crash` 两种、`jvm-load-crash`、`emitc-crash` 三种、`sanitizer` 的 LeakSanitizer、`comptime-compile`）。
每个 key 取前三例共 20 条（`comptime-compile` 只有两例），集群上 `--jobs 21`，824 s：全部 ≤ 20 行
（7 到 20，最长的是 `sanitizer` s40-c4），全部单独复现。`sanitizer` 那几条缩出来是 #68 的形状
（列表元素里的 `return` 漏掉先求值的元素）。

**nightly 形状。** 同一批 #632 finding，`--minutes 6 --jobs 4`，钉 4 核：按 key 取两例，247 s 结束，
114 → 13 行与 108 → 13 行，都是 `minimal`。

**负控。**

- 自测（`--self-test`）：轮次的接受改成 `if False`（`reduce.py` 的 `if good:`）、替身谓词改成恒真、
  `exit` 的 key 去掉两边退出码，三处各自变红。
- 真编译器：轮次判定（`evaluate` 里 `res[k] = ...` 那行）改成恒真，归约滑到一个与缺陷无关的程序，
  单独验证不复现，`--check-lines 20` 退出 1；改成恒假，原程序第一轮就「不复现」，同样退出 1；不改则绿。

## 不做的（理由）

- **不自动入库语料与 `known-red.txt`。** 裁决原文：沿用已有纪律，人审后入库。草稿里哪边是对的只有人能定。
- **不做表达式级归约**（把子表达式换成叶子）。判据是行数，生成器的长表达式都在一行内；行内缩短不改变行数，
  却会把每轮候选数翻几倍。
- **不让 gen.py 记录生成树。** 从文本读回已经精确（往返验证），且能归约旧生成器与手写的程序；
  让生成器同时维护文本与树是两份要同步的东西。
- **不归约 batch 级 finding（case = -1）**，例如只在多个 case 同在时才出现的 LSan 报告、整批 cc 失败。
  它们没有单例程序可缩；`summary.md` 记为未归约。
- **不进 push。** 同刀 1：push-total 没有余量，归约只在 nightly 红了之后才有输入。
