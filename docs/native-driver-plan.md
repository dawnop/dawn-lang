# B 线：native 驱动补全 + 把后端契约摆到明面上

> 状态：**七刀已结**（2026-08-03 立项，任务 #128；K-B1–K-B5 与 K-B7 落地，K-B6 明确推迟，
> 刀表见 §2）。本文是 B 线的落地记录 + 刀表。
>
> **为什么在这儿而不在别处**：B 线原来的备忘录只存在于任务 #128 的描述里，仓库中没有
> 任何一份 B 线文档；A 线（[jvm-base-plan.md](jvm-base-plan.md)）的备忘录已经因为一次
> WSL 重启在 `/tmp` 里丢过 623 行，同样的事没理由再发生一次。
>
> 上游：[native-backend-plan.md](native-backend-plan.md)（Phase −1 → 6，Phase 6 native
> 自举已达成）、[runtime-intrinsics-design.md](runtime-intrinsics-design.md)、
> [bootstrap.md](bootstrap.md)。姊妹线：[jvm-base-plan.md](jvm-base-plan.md)（A 线）。

## 0. 这条线要解决什么

native 后端在 2026-07-30 达成自举（`scripts/native-fixpoint.sh` B==C）之后，它
**能编译整个编译器**，但它**装出来的命令行只有五条**：`check` / `build` / `emitc` /
`run` / `version`。JVM 驱动 `selfhost/src/main.dawn` 有十几条。

B 线的驱动是**能力补全，不是纯洁性**：不是「把 java 赶出去」，而是「两个后端的
能力差在哪、哪些差是真的做不到、哪些只是没接线」。第二件事——**把后端契约摆到
明面上**——是同一枚硬币的反面：能力差如果没有门禁看着，它会以「某个后端上某个
命令行为不一样」的形式在用户那边被发现。

## 1. 证据等级约定

沿用 [jvm-base-plan.md](jvm-base-plan.md) §1。本文每条断言标注来源，**不要把估算读成实测**：

- `[实测]` —— 在这台机器上真跑出来的数。
- `[扫描]` —— 自写的扫描器读出来的。
- `[grep]` —— 只读源码得出的。
- `[估算]` —— 未实装，只能推算；标注方法与不确定度。
- `[推论]` —— 从上面几类推出来的**排序/取舍判断**，不是任何人测出来的。

## 2. K-B 刀表

| 刀 | 内容 | 性质 | 状态 |
|---|---|---|---|
| **K-B1** | intrinsic 契约表 + `scripts/intrinsic-parity.py` 构建期门禁 | 只加门禁 | **已做** |
| **K-B2** | 把 `fmt` / `doc` / `add` 接进 native 驱动，并让差分门禁真的覆盖 native | 加能力 + 加门禁 | **已做**（§4–§7） |
| **K-B3** | `lsp`（`lsp.dawn` + `lspq.dawn` + `lspc.dawn`，2,877 行），并让 lsp 差分真的覆盖 native | 加能力 + 加门禁 | **已做**（§11–§15） |
| **K-B4** | `test`（`testrun.dawn`；JVM 侧靠生成一个 test main 类，native 侧要另一条路） | 加能力 + 加门禁 | **已做**（§18–§21） |
| **K-B5** | 结构化 comptime 常量落到 native（`emitc.const_literal` 原来直接 panic） | 加能力 + 加门禁 | **已做**（§17） |
| **K-B6** | `use c` FFI（native 侧的 java FFI 对位物） | 加语法 | **推迟**（裁决 D7=(b)，理由见下） |
| **K-B7** | native 二进制进 release artifact | 加产物 + 加门禁 | **已做**（§22） |

> 刀表的**内容**来自任务 #128 的描述。原始 issue body 在写这份文档时取不到
> （`api.github.com/repos/dawnop/dawn-lang/issues/128` 回 404，本仓 issue 不公开），
> 所以上表是照任务简报转录的，**不是从 issue 原文抄的** `[推论]`。K-B3/K-B4 的行数是
> `wc -l` 实测。

> **这张表以前只有五行，而且五行全是「已做」**——读起来就是「B 线已完成」。K-B6/K-B7
> 两行是 2026-08-04 补的。同一张表还犯过更糟的：某一版写着「K-B4 已完成」并附了一段
> 章节号区间，而那些小节当时**根本不存在**。指向不存在证据的前向引用不会让任何门禁变红，只会让下一个
> 读表的人以为有据可查——所以往这张表里写章节号，写完请点开验它存在。

**裁决 D7（K-B6 的形态）= (b) 明确推迟。** `use c` 是新语法，落地即
`Emit-Change(parse *)`，而签名/语法变更要走种子纪律的三期两发布（`docs/bootstrap.md`）。
今天没有任何真实 native 程序需要它：native 后端**拒绝** `use java`（`jsig_refused`），
但整个编译器闭包与 `packages/` 都不需要 C 侧的外部函数，`pkgfetch` 要下载就 spawn
`curl`（§4）。为一个假想需求预付三期两发布的成本，是把契约面积扩大到没人用的地方。
等到出现第一个真的够不着的 native 程序，再按那时的形状定语法。

裁决 **D4（K-B2 的形态）= (a)**：与 JVM 驱动**等价**——同样的 flag、同样的参数处理、
同样的输出、同样的退出码。不做缩水版。

## 3. K-B1 落地了什么

`scripts/intrinsic-parity.py`：`lower.inline_intrinsics()` 点名的、两个后端各自
写指令的那批 primitive，逐条核对 `emit.gen_cintrinsic` 与 `emitc.emit_intrinsic`
两边的 arm 集合（双向：声明了没 arm、有 arm 没声明）。在它之前，一个 primitive
只在一个后端上有实现，会以**用户那次编译的 panic** 的形式暴露，而且只在某段代码
恰好走到那个名字时。

## 4. K-B2 的前提核对：「5,373 行、零 `use java`」

侦察给的数字是：`fmt/doc/add/lsp/lspq/lspc/dump*` 合计 **5,373 行、零 `use java`**，
所以它们不上 native 驱动**不是因为要移植，而是因为 `nmain.dawn` 从来没给它们接过线**。

**核对结论：数字对，结论也对** `[实测]`+`[grep]`。

```
fmt.dawn 368  doc.dawn 758  add.dawn 242  lsp.dawn 853  lspq.dawn 1736
lspc.dawn 288  dump.dawn 62  astdump.dawn 538  coredump.dawn 455  checkdump.dawn 73
                                                                  ---- 合计 5373
```

`grep -n "use java"` 在这十个文件里只命中两处，**都不是 import**：

- `lspq.dawn:354` —— 补全项的**字符串字面量** `"use java \"" ++ fqcn ++ "\""`
- `lsp.dawn:426` —— 一句**注释**

传递闭包也核过了 `[grep]`：K-B2 真正拉进来的三条链是
`fmt → lexer/token`、`doc → parser/cx/passes/stdlib/tast/interp/types`、
`add → toml/manifestv/diag/pkgfetch → sha2 + inflate + fspath`。这几个包全部零
`use java`（`packages/fspath/src/fspath.dawn:24` 那处是注释）。`pkgfetch` 要下载
就 spawn `curl`，这本来就是 [native-backend-plan.md](native-backend-plan.md) §1
定下的方案，不是绕路。

**编译器里带 `use java` 的是 `maven.dawn`（6 处）与 `vendor.dawn`（10 处）**，
这两个都只在 JVM 驱动的 `build`/`lock`/`--vendor` 路径上，K-B2 不碰。

## 5. 最重要的发现：那两个门禁本来一个 native 字节都没跑过

侦察备忘录里的假设是：

> 接上线之后，`scripts/selfhost-fmt-diff.sh`（以及之后的 `selfhost-lsp-diff.sh`）
> 会**自动**变成第二后端的差分门禁。

**这条是错的** `[grep]`+`[实测]`。两个脚本的「被测方」都是写死的：

```
scripts/selfhost-fmt-diff.sh:  ./bin/dawn fmt "$OUT/d"     # ./bin/dawn = JVM 工具链
scripts/selfhost-run-diff.sh:  SH=(./bin/dawn)
scripts/selfhost-lsp-diff.sh:  SELF=./bin/dawn
```

参照方有 `DAWN_BIN` 可换（换的是 N−1 种子那一侧），**被测方没有任何入口**。
所以：把 `fmt` 接进 `nmain.dawn` 之后跑这些脚本，绿的还是同一个 JVM 二进制，
**一个 native 字节都不会被执行**。

这正是 `scripts/classfile-verify` 那次的形状（2026-08-03，见
[jvm-base-plan.md](jvm-base-plan.md)）：parent-first 委派让被测目录根本没被读过，
门禁绿了很久，最后是**一个变异体没能变红**才发现它是空跑的。

于是 K-B2 的验收标准不是「native 能跑 `dawn fmt` 了」，而是
**「差分门禁真的覆盖了 native 后端」**。为此做了两件事：

1. `selfhost-fmt-diff.sh` 增加 `DAWN_SELF`（默认 `./bin/dawn`），把「被测方」变成
   可换的。这是让上面那条假设**成立**所需的全部改动。
2. 新增 `scripts/native-cli-diff.sh`：第二后端差分门禁。

### 5.1 `native-cli-diff.sh` 的两条腿、两个 oracle

| 腿 | oracle | 为什么是这个 oracle |
|---|---|---|
| `fmt` | **N−1 发布** | 直接用 `DAWN_SELF=<native 二进制> ./scripts/selfhost-fmt-diff.sh`：同一份语料（327 个被跟踪的 `.dawn` + 打乱缩进的副本）、同一个 oracle、换个后端 |
| `doc` / `add` | **HEAD 的 JVM 驱动**，逐字节 | 没有「N−1 的 native 驱动」可比——这两条子命令在这个后端上以前不存在。而 JVM 那侧由 `selfhost-run-diff.sh` 钉在 N−1 上，所以链条是 native == JVM == N−1 |

`doc`/`add` 两条腿**故意不给 `Emit-Change` 逃生阀**：`Emit-Change` 声明的是「随时间
发生的、被批准的变化」；**同一个 commit 上两个后端不一致，是其中一个的 bug**，不存在
被批准的版本。

语料**刻意不含 `use java`**：native 驱动会拒绝它（`jsig_refused`），所以
`doc site` 报错不是分歧、是它该给的答案。多模块项目那条用 `packages/json`。

### 5.2 门禁覆盖矩阵

| 门禁 | K-B2 之前 | K-B2 之后 |
|---|---|---|
| `selfhost-fmt-diff.sh` | 只 JVM | JVM（默认）+ native（`DAWN_SELF`，由 `native-cli-diff.sh` 调用） |
| `selfhost-run-diff.sh`（含 `doc`/`add`） | 只 JVM | **仍只 JVM**——native 侧由 `native-cli-diff.sh` 单独覆盖 |
| `selfhost-lsp-diff.sh` | 只 JVM | 仍只 JVM（native 还没有 `lsp`；K-B3 已补，见 §12） |
| `native-fixpoint.sh` | native（只 `emitc`/`run`） | native（同前；TU 变大了，见 §7） |
| `spike-native/run.sh` | 两后端（跑用户程序） | 同前 |
| `native-cli-diff.sh` | **不存在** | **两后端**：`fmt`/`doc`/`add`（K-B3 加了 `lsp` 两条腿） |
| `doc-check.py` | —— | **它不测 `dawn doc`**，见下 |

> **`scripts/doc-check.py` 与 `dawn doc` 没有关系** `[实测]`。名字像，实际是
> Markdown 文档的 lint（相对链接、同文件锚点、`> 状态：` 行、以及 info string 标了
> `dawn run` / `dawn compile` 的围栏代码块能不能编译/跑）。它只用 `bin/dawn run|check`。**覆盖 `dawn doc` 输出的门禁
> 是 `selfhost-run-diff.sh`**（`doc --builtins` / `doc site` / `doc examples/traits.dawn` /
> pub effect / 两条错误路径），加上现在的 `native-cli-diff.sh`。这一条值得写下来，
> 因为「doc 有没有门禁」问错脚本会得到一个自信的错答案。

## 6. 红演示与阴性对照

> 全仓规矩（2026-08-03 一天里被踩到四次）：**一个从没被证明能变红的绿，不携带信息**。
> 「从没漏过东西」与「从没看过东西」输出一模一样，只有变异体能把两者分开。

三个变异体全部**只改 `nmain.dawn`**（即只改 native 驱动那一份实现），所以「同一棵树、
同一个脚本、换个后端」就是天然的阴性对照。

### 6.1 `fmt`：三向判别 `[实测]`

变异体：native 的 `cmd_fmt` 里 `fmt.format(original)` → `fmt.format(original) ++ "\n"`。

| 运行 | 结果 |
|---|---|
| 变异 + `DAWN_SELF=<native>` | **RED**，`exit=1` |
| 变异 + 默认（JVM） | GREEN，`exit=0` ← 证明 `DAWN_SELF` 真的换了二进制，且变异只在 native 侧 |
| 还原 + `DAWN_SELF=<native>` | GREEN，`exit=0` |

```
######## STEP 1 (mutant, native under test) -- expect RED
diff -r /tmp/selfhost-fmt-diff.683513/k/1.dawn /tmp/selfhost-fmt-diff.683513/d/1.dawn
136a137
>
diff -r /tmp/selfhost-fmt-diff.683513/k/10.dawn /tmp/selfhost-fmt-diff.683513/d/10.dawn
17a18
>
...
FAIL: formatter output differs vs the seed and no commit declares it
==> exit=1

######## STEP 2 (mutant, JVM under test, default invocation) -- expect GREEN
OK: ./bin/dawn agrees with the previous release over 327 files (plus mangled copies)
==> exit=0

######## STEP 3 (unmutated, native under test) -- expect GREEN
OK: .../nat/dawnc agrees with the previous release over 327 files (plus mangled copies)
==> exit=0
```

### 6.2 `doc`：两个变异体，逐用例判别 `[实测]`

A（正常路径）`print(doc.project_json(prog))` → `println(...)`；
B（错误路径）`fail_doc(...)` → `fail_compile(...)`（多一行计数行）。两个同时下。

```
== fmt vs N-1, native backend ==
OK: .../mutdoc/dawnc agrees with the previous release over 327 files (plus mangled copies)
OK   fmt --check (walk order) (exit 1)
OK   fmt --check (a clean file) (exit 0)
== doc, JVM vs native ==
OK   doc --builtins (exit 0)
OK   doc --stdlib (exit 0)
FAIL: doc (traits example) differs between backends (exits jvm=0 native=0)
24a25
>
FAIL: doc (multi-module project) differs between backends (exits jvm=0 native=0)
163a164
>
FAIL: doc (single-module package) differs between backends (exits jvm=0 native=0)
60a61
>
FAIL: doc (pub effect) differs between backends (exits jvm=0 native=0)
36a37
>
OK   doc (usage) (exit 2)
OK   doc (missing target) (exit 2)
FAIL: doc (compile errors) differs between backends (exits jvm=1 native=1)
10a11
> 2 errors
FAIL: doc (manifest diagnostics) differs between backends (exits jvm=1 native=1)
12a13
> 2 errors
OK   fmt (missing target) (exit 2)
OK   fmt (usage) (exit 2)
== add, JVM vs native ==
OK   add (local path dep) (exit 0)
...
FAIL: the native driver and the JVM driver disagree
==> exit=1
```

**判别力体现在哪**：`--builtins`/`--stdlib`（不走 `project_json`）、`fmt` 三条、
`add` 六条全部保持绿，只有该红的红。JVM 侧同一命令的输出 md5 在变异前后不变
（`94e7a502…`），native 侧变成 `3c1bbe3e…`。

阴性对照（还原后，同一条命令）：全 21 项 OK，`exit=0`。

### 6.3 `add`：`[实测]`

变异体：native dispatch 的 `Ok(s) -> println(s)` → `println(s ++ "!")`。

```
== add, JVM vs native ==
FAIL: add (local path dep) differs between backends (exits jvm=0 native=0)
1c1
< added greeter as `greeter` (path /tmp/native-cli-diff.701222/greeter-src)
---
> added greeter as `greeter` (path /tmp/native-cli-diff.701222/greeter-src)!
FAIL: add (maven coordinate) differs between backends (exits jvm=0 native=0)
FAIL: add (url dep, aliased) differs between backends (exits jvm=0 native=0)
OK   add (bad coordinate) (exit 2)
OK   add (usage) (exit 2)
OK   add (invalid manifest) (exit 2)
FAIL: the native driver and the JVM driver disagree
```

阴性对照（还原后）：六项全 OK，`exit=0`。

### 6.4 「语料里到底有没有那些文件」这一条也核了

项目记忆里的坑：**在一棵新文件没 `git add` 过的树上跑 `fmt-diff`，等于没测它们**
（effects-handler 那批的「代理假绿」）。`selfhost-fmt-diff.sh` 的语料来自
`git ls-files '*.dawn'`。核对 `[实测]`：

- 被跟踪的 `.dawn` = **327**，`nmain.dawn` 在其中；
- 未跟踪的 `.dawn` = **0**（本刀没有新增 `.dawn` 文件）；
- 脚本对每个路径做的是 `cp "$f"`，读的是**工作树内容**而不是 `git show`——所以
  §6.1 那个**未提交**的 `nmain.dawn` 变异确实被看见了，这也顺带证明了这条。

## 7. 代价：量出来的数

同机、同 flag（`cc -std=c11 -O2 -fwrapv -fno-strict-aliasing -pthread`）`[实测]`：

| | K-B2 前 | K-B2 后 | 差 |
|---|---|---|---|
| `nmain.c` 行数 | 160,260 | 165,993 | +5,733（+3.6%） |
| `dawnc` 二进制 | 2,558,520 B | 2,656,168 B | +97,648 B（+3.8%） |
| `cc -O2` 单次 | 11.29 s | 11.69 s | +0.40 s |
| `__emitc` 单次 | —— | 4.0 s | —— |

**「native 那条链是几分钟级的重活」这条描述已经过时** `[实测]`：一次
`__emitc` + `cc -O2` 是 **~16 s**；`scripts/native-fixpoint.sh` 整条（三代 + 冒烟）
**47.8 s**；`scripts/native-cli-diff.sh` 冷启动（自己编驱动 + 三条腿）**45.9 s**。
所以「构建 native 驱动再跑差分」完全放得进每次 push 的门禁，不需要设成里程碑门禁。

### 7.1 K-B2 落地时跑过的门禁 `[实测]`

`selfhost-fixpoint` (B==C) · `native-fixpoint` (B==C + 冒烟) · `selfhost-prev-diff` ·
`selfhost-fmt-diff` · `selfhost-run-diff` · `selfhost-lsp-diff` · `native-cli-diff` ·
`doc-check.py` (61 篇) · `intrinsic-parity.py` · `classfile-verify` (1947 类) ·
`spike-native` · `dawn test selfhost` (299 项) · `dawn fmt selfhost site packages --check` ·
`dawn lock --check selfhost` —— **全绿**。

`selfhost-core-diff` 一开始红：**只有 `nmain` 一个模块进了 `changed` 桶**，其余 74 个
模块与三份程序 dump 逐字节不变；`selfhost.norm.sha` 里动的也是同一行，说明不是
ADT id 漂移而是真加了指令——一次驱动接线**应该**长这个样子。已 `--record` 重录，
两个文件各动一行。**没有 Emit-Change 声明**：`fmt`/`doc`/`add` 三条子命令的输出
一个字节都没变，`prev-diff` 里 `fmt backend-dawn` 那条也是绿的。

## 8. 顺手挖出来的一处既有分歧

`nmain.dawn` 的 `cli_error` **退出码是 1**，`main.dawn` 的是 **2**——同一类错误
（目标不存在、后缀不对）两个驱动给不同的退出码 `[grep]`。没有任何门禁比较过两个
驱动，所以它一直在那儿。K-B2 按裁决 D4 把 native 侧改成 2，并且现在
`native-cli-diff.sh` 的六条 `exit 2` 用例会一直盯着它。

## 9. 这个门禁不证明什么

写下来免得将来把它读大了。

1. **`doc`/`add` 两条腿是跨后端比较，对「共享代码本身改了」是天然失明的** `[推论]`。
   `fmt.dawn` / `doc.dawn` / `add.dawn` 是两个驱动共用的；改它一行，两侧同样地变，
   跨后端差分照样绿。**接住这种变化的是 N−1 oracle**：`fmt` 那条腿本来就是对
   N−1 比的；`doc`/`add` 靠 `selfhost-run-diff.sh` 把 JVM 侧钉在 N−1 上，再靠这条
   门禁把 native 钉在 JVM 上，两段合起来才闭合。**任何一段被删掉，闭合就没了。**
2. 它证明的是两件事：（a）`main.dawn` 与 `nmain.dawn` 那份**重复的驱动管线**没有
   漂移；（b）那 5,373 行共享前端代码**被 C 后端执行**并且逐字节对得上——这是
   K-B2 之前没有任何门禁做过的事。
3. 驱动的**顶层 usage 横幅**两侧不同，且不打算相同：子命令集不一样。D4 的「同样的
   输出」约束的是 `fmt`/`doc`/`add` 这三条子命令，包括它们内部那些写着
   `usage: dawn fmt …` 的错误串（照抄，不改成 `dawnc`）。

## 10. 下一刀

- **K-B4（`test`）**：不是接线活。JVM 侧靠 `testrun.gen_test_main` 生成一个 test main
  类再在同一个 JVM 里跑；native 侧没有「生成一个类塞进去」这回事，得走另一条路
  （最直白的是把 test 块编进那个 C 翻译单元，由 `nmain` 直接调用）`[推论]`。

---

## 11. K-B3 的前提核对：lsp 这一族也是零 `use java`

侦察给的数字（§4）里 `lsp.dawn 853 + lspq.dawn 1736 + lspc.dawn 288 = 2,877` 行，
零 `use java`。**自己重核了一遍，结论成立** `[实测]`+`[扫描]`：

- 这三个文件里 `use java` 只命中两处，都不是 import：`lspq.dawn:354` 是补全项的
  **字符串字面量**（文档里真写了 `use java "..."` 声明时把它整行提供为补全），
  `lsp.dawn:426` 是一句**注释**。
- **传递闭包也核了**，不是只看这三个文件。自写扫描器从 `lsp` 出发按 `use` 边闭包，
  得到 **45 个模块**（`analyze ast checker core cx diag exhaustive fmt fspath interp
  jsig json/* lexer lower lspc lspq manifest manifestv parser passes pkgfetch sha2/*
  inflate/* std/* stdlib stdsrc suggest tast token toml types` 等），其中 `^use java`
  命中数 = **0**。整个编译器里带真 `use java` 的是 `emit / codegen / jreflect /
  jvmhelp / jarw / jfold / maven / vendor / rtclasses / testrun / main`——**一个都不在
  这个闭包里**。

所以 K-B3 和 K-B2 一样是纯接线：`nmain.dawn` 加一行 `use lsp`、一行 usage、一个
dispatch 分支。JVM 驱动传 `jsig_real()`（编辑器里 `use java` 能解析），native 驱动传
`jsig_refused()`——这与该后端 `check` 给同一份源码的答案一致，是**有意的**唯一差别。

## 12. 让 lsp 差分真的跑到 native

§5 那条发现对 `selfhost-lsp-diff.sh` 同样成立，而且 K-B2 修 `selfhost-fmt-diff.sh`
时**没有一并修它**：

```
scripts/selfhost-lsp-diff.sh:  SELF=./bin/dawn      # K-B3 之前
```

`DAWN_BIN` 换的是**参照方**（N−1 种子），被测方写死。于是「把 `lsp` 接进 `nmain.dawn`
然后看 `selfhost-lsp-diff.sh` 变绿」会**一个 native 字节都不执行**——`classfile-verify`
那次的同一个形状。K-B3 做了两件事：

1. `selfhost-lsp-diff.sh`：`SELF=${DAWN_SELF:-./bin/dawn}`，并在脚本头把两个旋钮
   （`DAWN_BIN` = oracle、`DAWN_SELF` = subject）写清楚；结尾那行也改成打印被测方是谁。
2. `native-cli-diff.sh` 加**第 4 条腿**：`DAWN_SELF=<native> ./scripts/selfhost-lsp-diff.sh`。
   与 `fmt` 那条腿同形——同一份脚本化会话、同一个 N−1 oracle、换个后端。
   `native-cli-diff.sh` 本来就在 CI 的 gates.yml 里，所以这条腿是白拿的 CI 覆盖。

**接上线之后一次就绿** `[实测]`：native 的 `lsp/lspq/lspc` 与 v0.49.0 种子逐条一致，
**50 条消息**（hover 20、definition 9、completion 9、documentSymbol、didChange 后的
hover、独立 buffer 的 hover/definition、formatting、shutdown，以及两条
publishDiagnostics）。

## 13. 红演示与阴性对照 `[实测]`

> 全仓规矩：**一个从没被证明能变红的绿，不携带信息**。而且一个门禁要回答**两个**独立
> 问题——「它会失败吗」和「它看的是不是我以为的那个东西」——每个问题各要一个变异体。

变异体只改 `nmain.dawn` 的 lsp 分支（native 驱动独有的那几行），JVM 驱动碰不到它：
`lsp.run_lsp(...)` 之前多打一帧 `Content-Length: 2\r\n\r\n{}`。

| 运行 | 结果 |
|---|---|
| 变异 + `DAWN_SELF=<native>` | **RED**，`exit=1` |
| 变异 + 默认（JVM） | GREEN，`exit=0` ← 证明 `DAWN_SELF` 真换了二进制，且变异只在 native 侧 |
| 还原 + `DAWN_SELF=<native>` | GREEN，`exit=0`，50 条 |

```
######## STEP 1 (mutant, native under test) -- expect RED
FAIL lsp differs (1 lines) and no commit since the tag declares it
     (declare it with 'Emit-Change(<label>): why' — this label is 'lsp')
0a1
> {}
==> exit=1

######## STEP 2 (mutant tree, JVM under test, default invocation) -- expect GREEN
OK   lsp
OK: ./bin/dawn agrees with the previous release over 50 lsp messages
==> exit=0

######## STEP 3 (unmutated, native under test) -- expect GREEN
OK   lsp
OK: .../nat/dawnc agrees with the previous release over 50 lsp messages
==> exit=0
```

**缺席探针**（回答第二个问题的另一半：它看的是被测方的 `lsp` 吗）：把 `DAWN_SELF`
指向 **K-B3 之前**那版 native 驱动（`lsp` 没接线，`dawnc lsp` 走 `fail_usage`，stdout 为空），
门禁红，`1,50d0`——50 条全缺。所以「没接线」这件事门禁能看见，不是接了线才恰好绿。

**「语料/被测源是不是真被看见了」也核了**：`selfhost-lsp-diff.sh` 的会话文档是脚本
现写的（不走 `git ls-files`），被测方则由 `bin/dawn __emitc` 从**工作树**编出来。上面
STEP 1 那个变异**从未 `git add`**，门禁照样红了——这就是那条证明。另外本刀没有新增
`.dawn` 文件（被跟踪 327、未跟踪 0），所以 `fmt` 那条腿的语料也没有 effects-handler
那批的「代理假绿」风险。

## 14. 挖出来的分歧：native 的 stdout 永远不 flush

K-B2 挖到 `cli_error` 退出码 1 vs 2。这一刀挖到的更硬：**接上线之后的 `dawnc lsp`
能通过差分门禁，却挂死任何真实编辑器** `[实测]`。

- `dawn_rt_init` 把 stdout 设成 `_IOFBF`（64 KiB 块缓冲），`dawn_io_print` /
  `dawn_io_println` **从不 flush**；只有 `eprint`/panic/退出才会冲。
- JVM 侧 `System.out` 是 autoFlush 的 `PrintStream`：`print` 在写入内容含换行时冲，
  `println` 总是冲。`lsp.send` 写的是 `Content-Length: N\r\n\r\n{...}`，含换行 → JVM 冲，
  native 不冲。
- 实测（发一条 `initialize`、**不关 stdin**，等 20 秒）：

```
JVM   ./bin/dawn lsp: responded after 0.57s -> b'Content-Length: 257\r\n\r\n{"jsonrpc":"2.0",'
native dawnc lsp  : NO BYTES after 20s with stdin still open (client would hang)
```

**差分门禁对这件事是结构性失明的**：它把整个会话一次写完、关掉 stdin、在 EOF 处读
transcript——一个只在退出时冲的服务器产出的字节**逐字节相同**。

裁决 D4 是「与 JVM 驱动等价」，一个只有批处理 harness 用得了的语言服务器不算等价，
所以修了，修的是**运行时**而不是 lsp 那一层：`dawn_io_print` 在写入含 `\n` 时 flush、
`dawn_io_println` 总是 flush——照抄 `PrintStream` 的 autoFlush 规则。选它而不是加一个
`io.flush()` 原语，是因为后者要动语言表面（std API + 两个后端的 intrinsic），而新原语
要走种子纪律的三期两发布；这里要的只是把**后端契约**对齐，不是加 API。
`runtime/c/` 改了就得 `python3 scripts/gen-rtsrc.py` 重生成 `selfhost/src/embed/rtsrc.dawn`
（cdriver 里有 staleness 测试盯着）。

代价实测：20 万次 `println` 打进管道，**0.040 s → 0.11 s**（每行 0.35 µs）。批量输出
不受影响——一次 `print` 打出整个 C 翻译单元仍然只冲一次。这也正是 JVM 后端一直在付的
价钱，这是**契约，不是调优旋钮**。

### 14.1 于是 `native-cli-diff.sh` 加了第 5 条腿

差分看不见的事，得有别的东西看。第 5 条腿：对两个后端各起一个 `lsp`，发一条
`initialize`，**stdin 保持打开**，要求 60 秒内出第一帧。

它自己的红演示 `[实测]`——同一个驱动二进制、链上 **HEAD 那版没有 flush 的运行时**：

```
== lsp vs N-1, native backend ==
OK   lsp
OK: .../noflush/dawnc agrees with the previous release over 50 lsp messages
== lsp responds before end of input, both backends ==
OK   lsp jvm answered in 0.59s with stdin still open
FAIL: lsp native wrote nothing in 60s with stdin still open
FAIL: the native driver and the JVM driver disagree
```

同一次运行里，**差分绿、第 5 条腿红**——这一屏同时证明了两件事：差分确实对 flush
失明，以及新加的那条腿确实补上了它。

### 14.2 其余 CLI 形状：无分歧

逐条对过 `[实测]`：`lsp` / `lsp --stdio` / `lsp bogus extra args`（两边都忽略尾部参数）
/ 空 stdin（EOF 即退，exit 0）/ 一帧坏 JSON（都回 `-32700 Parse error` 且**不退出**）——
stdout 逐字节相同、退出码相同。

## 15. K-B3 的代价与门禁清单

同机、同 flag `[实测]`：

| | K-B3 前 | K-B3 后 | 差 |
|---|---|---|---|
| `nmain.c` 行数 | 166,524 | 181,282 | +14,758（+8.9%） |
| `dawnc` 二进制 | 2,669,936 B | 2,846,104 B | +176,168 B（+6.6%） |
| `cc -O2` 单次 | 11.1 s | 12.2 s | +1.1 s |
| `__emitc` 单次 | —— | 4.1–4.5 s | —— |
| `native-cli-diff.sh` 冷启动（5 条腿） | 45.9 s | 49 s | +3 s |

跑过的门禁：`selfhost-fixpoint` (B==C) · `native-fixpoint` (B==C + 冒烟，52 s) ·
`selfhost-prev-diff` · `selfhost-fmt-diff` · `selfhost-run-diff` · `selfhost-lsp-diff`
（JVM 与 native 各一遍）· `native-cli-diff`（冷启动，5 条腿）· `lsp_smoke.sh` ·
`spike-native` · `classfile-verify`（1948 类 + 语料变异体）· `doc-check.py`（61 篇）·
`intrinsic-parity.py` · `emitchange-selftest.sh`（27 例）· `dawn test selfhost`（300 项）·
`dawn fmt selfhost site packages --check` · `dawn lock --check selfhost` —— **全绿**。

`selfhost-core-diff` 一开始红，`changed` 桶里**恰好两个模块**：`nmain`（接线，真加指令）
与 `rtsrc`（`gen-rtsrc.py` 重生成，嵌入的运行时字符串常量变了）。没有第三个模块漂进来，
`selfhost.norm.sha` 里也是同两行——已 `--record` 重录（两个文件各动两行）。

**没有 Emit-Change 声明**：`lsp` 的 50 条消息一个字节没变，flush 改的是**字节何时离开
进程**、不是哪些字节；`prev-diff` 里那几条 `NOTE` 是 id-counter 那一批留在窗口里的，
不是本刀的。

## 16. 这条 lsp 门禁不证明什么

1. **它对「共享的 lsp 代码本身改了」是失明的吗？不是——但只因为 oracle 是 N−1。**
   `lsp.dawn/lspq.dawn/lspc.dawn` 两个驱动共用，改一行两侧同样地变；如果这条腿是
   「JVM vs native」跨后端比较（像 `doc`/`add` 那样），它就会全绿——**这正是 §9 第 1 条
   记的那个盲点**。这条腿之所以躲开了它，是因为它比的是 **N−1 发布**，而不是另一个
   后端。代价是另一头：**它每次发布都要重新对齐**，而 §9 第 1 条那条链（native == JVM == N−1）
   在这里退化成一段——一旦 `selfhost-lsp-diff.sh` 的默认 JVM 那遍被从 CI 里拿掉，
   native 这遍照样绿，但「JVM 也没变」这半句就没人证了。
2. **它不证明两个驱动的 `Jsig` 选择是对的。** JVM 传 `jsig_real()`、native 传
   `jsig_refused()`，而会话语料**刻意不含 `use java`**（含了就是 native 该给的拒绝，
   会变成一条永久的假分歧）。所以把 native 侧改成 `jsig_real()`（如果它存在）或把
   JVM 侧改成 `jsig_refused()`，这条门禁**都不会红** `[推论]`。真要盯住它，得有一份
   带 `use java` 的语料和两份不同的期望——那是另一把刀。
3. **它不证明时序、并发或增量性。** 会话是一次写完、顺序读回的；服务器的响应**延迟**、
   didChange 的重算成本、两条请求交错时的行为，都不在比较范围内。§14 那件事就是从这个
   缺口漏出去的——补它的是第 5 条腿，而第 5 条腿只检查**第一帧**是否在 stdin 关闭前
   到达，不检查后续每一帧。
4. **它不覆盖 stderr。** 两个驱动的 `lsp` 都不往 stderr 写东西，但没有任何断言这么说。

## 17. K-B5：结构化 comptime 常量落到 native

`emitc.const_literal` 原来对折叠出来的结构化值直接 panic：

```
emitc: const `B` folded to a structured value (List_Int), which native cannot rebuild yet
```

即 spec 7.2 允许一个 `const` 折成 List / 元组 / 记录 / 构造子（以及它们的嵌套与
opaque 包装），JVM 把它放进 `<clinit>` 填的 `static final` 字段，而 C 没有
`<clinit>` 可填。本刀补的就是这个。

### 17.1 C 侧怎么表示

**一个生成的 builder 函数 + 函数内 static 指针**，每个常量一个：

```c
static void* dawn_const_0(void) {
  static void* c = NULL;
  if (c == NULL) {
    /* 按 emit_const_value 的配方把值建出来 */
    c = (void*)(...);
    dawn_immortal(c);
  }
  return c;
}
```

三个决定各有理由：

1. **是函数不是初始化好的静态数据。** 元组和构造子*可以*写成静态初始化数据——布局是
   emitc 自己的。List 不行：`[1, 2, 3]` 是 `std/pvec.from_array` 作用在一个 Array 上，
   而持久向量的形状属于 std、是用 Dawn 写的。把它抄进后端等于把 std 的内部结构硬编码
   进 C 生成器，std 一动就静默错。既然 List 必须建，而元组能装 List，一套机制覆盖三种。
2. **惰性，不是 `main` 前的 init。** 一个 init 函数得挑一个没人有理由挑的顺序；而这里
   根本没有顺序可言——comptime 求值已经把常量读到的每一个常量都内联了，折出来的值是一棵
   闭合的字面量树，不会引用另一个常量。首次使用时建，比 `<clinit>` 做得还少，且不可观测
   （建它是纯的）。Dawn 程序只跑在一条线程上（运行时里只有一次 `pthread_create`，就是
   程序自己的栈线程），所以惰性 static 没有竞争。
3. **建完离开账本。** `dawn_immortal(c)` 把整张图标成不朽，于是 dup/drop 在它上面是空
   操作、`dawn_is_unique` 在它内部处处为假——和字符串字面量自 2026-07-29 入账以来的待遇
   一样。`rc.dawn` 的 `lit_immortal` 是这个决定的另一半，两边必须同时说同一句话。

值本身的重建走的是**发射器对同一形状的字面量已经在用的那条配方**（List 走
`CListLit` 的 Array + `from_array`，元组和构造子走 `emit_alloc` 的同一套
`dawn_adt_new` + 槽位 + ptrmask），而不是第二套会漂移的布局叙述。构造子的字段按
**声明类型**取槽位——折叠值身上没有 lowering 插的 `CBox`，所以类型变量位上的标量要在
这里装箱，和 JVM 的 `construct_value` 读 `gx.adts` 是同一个理由。

缓存键是 `模块 ++ "|" ++ 常量键`。JVM 不需要模块那一段，因为它的缓存是类上的字段表、
而一个类就是一个模块；C 是一整个翻译单元，`std/pvec` 的 `MASK` 和 `std/hamt` 的 `MASK`
在里面同名。

### 17.2 为什么标整张图而不只标根

`dawn_array_with` 是运行时里唯一一处「问 `dawn_is_unique`，然后原地写」。只标根会把
根以下每个节点留在 rc 1 上——那么「常量会不会被人从它自己的 buffer 里改掉」就取决于
每一个调用点先 dup，而不取决于这个对象本身的任何事实。标整张图把「常量不是唯一的」
从惯例变成事实。

**但今天惯例也成立，这点是量出来的**（2026-08-04）：从 Dawn 走到 `dawn_array_with`
的唯一路径是 `std/pvec.push_tail`，而 RC pass 在那次调用前会 dup 那个 Array，所以两种
标法下 `dawn_is_unique` 都答否。实测：把标法改成只标根，整个 native 语料全绿，包括
专门造的「1100 元素的常量再 append」——那是从 Dawn 够得着 `array_with` 的最小形状。
所以这是一道保险，而**能把两种标法分开的检查只有一个**：
`scripts/rc-contract/rc_test.c` 的 `test_immortal_graph`，它直接调
`dawn_array_with`。语料里没有任何程序看得见这个差别，`const_struct.dawn` 的头注写了
这句话，免得下一个人把语料的绿读成这条性质的证据。

### 17.3 红演示与阴性对照 `[实测]`

| 变异体 | 改哪儿 | 谁红 | 谁不红（阴性对照） |
|---|---|---|---|
| M1 只标根 | `dawn_immortal` 里 `h->rc = DAWN_IMMORTAL;` 后加 `continue` | `rc-contract` 8 条断言 | 整个 native 语料**全绿**——见 §17.2 |
| M2 不标 | `const_builder` 不发 `dawn_immortal(c);` | `const_fold`/`const_struct` 的 `asan`（heap-use-after-free）+ `native` + `diff` + `stderr` + `exit` | —— |
| M3 构造子 tag 恒 0 | `emit_const_adt(st1, ci, …)` → `…, 0, …` | `const_fold` 的 `asan` + `native` + `diff` + `exit` | **`const_fold:jvm` 绿**——同一次运行里同一份 `.expect`，所以被测者确实是 native |
| M4 篡改期望 | `const_struct.expect` 改一行 | `const_struct` 的 `jvm` 与 `native` 两条腿 | —— |

M3 是回答「门禁看得见 native 吗」的那一条：`scripts/spike-native/run.sh` 的
`__emitc`（:194）→ `cc`（:211）→ 跑二进制（:226）→ 和 `.expect` 比（:260），四步都在
native 这一侧，而 `jvm` 那条腿读的是同一个 `.expect` 且没有变红。

### 17.4 语料

`const_fold.dawn` 补了结构化那一半：List（含空、含字符串、含嵌套 List）、二元/三元组、
记录、无字段构造子、带字段构造子、类型变量位上的 Int 与 String、`Option`/`Result`、
opaque 包 List、以及一个 `comptime { … }` 块（走的是同一条发射路径，只是键是 span 不是
名字）。每一条都和**运行期写同一份字面量**的结果并排打印——这才是「常量被建得和字面量
不一样」能被抓住的地方。

`const_struct.dawn` 是新的，问的是另一个问题：常量活多久。读一千次、被 `++`/`sort`/
`reverse`/按值传参消费、装进会死掉的容器、被闭包捕获、从另一个函数读——打印出来的行在
「共享」「每次重建」「被释放」三种实现下长得一模一样，所以它的 oracle 是 `asan`
（开泄漏检测），不是 stdout。

### 17.5 剩下的

- **编译器自己不走这条路。** 全仓（`selfhost/src`、`std`、`packages`）今天没有一个
  结构化 `const`，所以 native 自举、`native-cli-diff` 都不经过 `const_builder`；唯一的
  运动量在语料里。这不是缺陷，是事实，写在这里免得把自举的绿当成这条路径的证据。
- **跨模块不共享。** 同一个常量被两个模块引用会生成两个 builder。JVM 也是这样
  （缓存是类上的字段表），Dawn 又没有引用相等，所以这是等价的、不是缺口。

## 18. K-B4：`dawn test` 落到 native 驱动

JVM 侧的 `dawn test` 是这样做的（`selfhost/src/jvm/testrun.dawn`）：每个 `test` 块被发射成
所属类上的一个 `dawn$test$i` 方法，然后**再生成一个类** `dawn$TestMain`，它的 `main`
逐个 try/catch 调用这些方法、打印报告、有失败就 `System.exit(1)`。

native 侧没有「再生成一个类」这回事——整个程序是**一个翻译单元**。所以这一刀的形状是：
test 块和其它函数一起编译进那个翻译单元，再把一段生成的 C 接在后面当它的 `main`
（`selfhost/src/c/ctestrun.dawn`）。

### 18.1 三个非平凡的接缝

1. **test 块的符号名。** 一个 test 的 Core 名字**就是它的描述字符串**，没法像函数名那样
   mangle：`"a, b"` 和 `"a; b"` 会 sanitize 成同一个符号。所以在 lowering 之后、发射之前
   把它们改名成 `emitc.test_name(i)`（= `dawn$test$i`，和 JVM 那边**同一个拼写**，写在
   `emitc.dawn` 里，让生成器和发射器不可能各写一份），并把 `is_test` 摘掉——发射器本来就
   跳过 `is_test`，改名之后它一个特例都不需要（`cdriver.named_tests`）。
   索引是**模块内**的序号，这正是 JVM 的 `dawn$test$i` 携带的那个数。

2. **哪些模块带 test。** `cdriver.build_units(std, prog, with_tests)` 多了一个开关：
   `dawn test` 走 `lower.emitted_core(lower_module_full(…, true))`，于是 test 体、以及
   **只有 test 用得到的字典**一起进来。std 永远不带——`collect_program` 那边也是这样
   （它只从 program 的模块里报告 test 块），两边同一个答案。

3. **报告的形状。** `PASS  ` / `FAIL  `（两个空格）、失败消息**每行缩进六个空格**、
   `N test(s) passed` 或 `K of N test(s) failed`、失败退出 1。C 侧的失败捕获走
   `dawn_catch_panic`，它 panic 和 fault 都接——这正是 JVM 那边 `catch (Throwable)` 的
   语义；它交回来的 `Result[_, ForeignError]` 的 `message` 字段就是 `getMessage()`。

`--cp` 按 `main.extract_cp` 的规矩校验（两种拼写、条目必须存在），然后**丢掉**：它只对
`use java` 的程序有意义，而这个后端在 `check` 就拒绝 `use java`。分隔符写死 `:`——
`main.path_sep()` 是 `File.pathSeparator`，一个 java 调用，没有 classpath 的后端无处可问。

## 19. 让差分门禁真的跑到 native 的 `test`

`scripts/native-cli-diff.sh` 加了三条腿（第 6/7/8 条）。被测者和前五条一样是 native 二进制：
`pair()`（:60）第 62 行跑 `./bin/dawn`（神谕），第 63 行跑 `"$DAWNC"`（被测者），比 stdout、
stderr 和退出码。第 7 条腿的两次调用在 :427 与 :429，第 8 条腿在 :492 的 `[("jvm", …),
("native", [dawnc])]`——`dawnc` 是脚本第 44–51 行现编出来的那个 native 二进制。

**和 doc/add 那两条腿不同的是：这里比的两边不是同一份代码。** test 块不是 Dawn 可调用的
函数，所以两个后端都写不出 Dawn 版的 runner——一边 ASM 写字节码，一边写 C 文本。所以第 6
条腿是**对同一份报告的复式记账**，不是「同一个实现被走到了两次」的检查。链条的另一半是
`selfhost-run-diff.sh`，它已经把 JVM 的 `dawn test` 钉在 N-1 上。

### 19.1 为什么这条腿需要另外三种检查

**测试运行器是「绿最没有信息量」这条规律最纯的形式：一个什么都没跑就报成功的 runner，
和一个全部通过的 runner，输出一模一样。** 所以除了逐字节比对，另加三样，每样对应一种
「空转」的形态：

1. **报告要为自己结账**（`pair_report`，:284）。汇总行**不是执行的证据**：`N test(s)
   passed` 两边都是生成期常量（JVM 一条 LDC，C 一个 static `dawn_str`），一个一次都没调
   的 runner 打出来的汇总和全绿的 runner 一模一样。而 `PASS`/`FAIL` 行是每条各花一次调用
   的那部分，于是数它们，并钉死到汇总的数上（失败数钉到 FAIL 行数上）。
   **这个检查跑在两边各自的 transcript 上，不是跑在 diff 上**——两个都只打汇总、什么都不
   报告的 runner，彼此之间是完全一致的。

2. **断言真的被求值**（第 7 条腿，:388）。上面每一条读的都是 runner 自己的报告，而报告
   正是一个空转 runner 最擅长生产的东西。这条腿把证据放到报告之外：每个断言经过 `note`，
   它落一个以 tag 命名的文件；跑完之后**数文件**，两个后端各在自己的目录里跑。
   中间那条 test 在它的**第二个**断言上失败，于是还钉住两件全绿语料钉不住的事：失败的
   test 的第一个断言照样跑，以及一次失败不会终止整个 suite。

3. **报告在进程结束之前就已落盘**（第 8 条腿，:447）。这是第 5 条腿在 `lsp` 上抓到的那个
   坑在这里的形态：C 运行时的 stdout 是 64 KiB 块缓冲（`dawn_rt_init`），而上面每一条检查
   都是等进程没了之后读 transcript——一个只在退出时 flush 的 runner 会和边跑边报的 runner
   **逐字节相同**，同时让一个盯着卡住的 suite 的人什么都看不到。而 suite 卡住或被杀，正是
   报告最要紧的时候。做法：两个 test 报告完之后第三个不返回，两边都 SIGKILL，看那一刻
   stdout 上有什么。窗口从**第一个字节到达**时才开始计时，因为 native 侧要先编译——一个大
   到装得下那次编译的固定超时，会变成一个「靠等」而不是「靠 flush」通过的检查。

## 20. 红演示与阴性对照 `[实测]`（2026-08-04）

| 变异体 | 改哪儿 | 谁红 | 谁不红（阴性对照） |
|---|---|---|---|
| M1 thunk 不调用 test 体 | `ctestrun.one_test` 的 `dawn_box_unit(sym())` → `dawn_box_unit(DAWN_UNIT)` | `test (a failing fixture)` 与 `test (failure message shapes)`（`exits jvm=1 native=0`）、第 7 条腿、第 8 条腿 | **两个全绿包全绿**——`test (multi-module package)` / `(single-module package)` 的逐字节比对**和 `pair_report` 的计数**都没看见它（`n accounts for all 6`） |
| M2 两边都不打 PASS 行 | `ctestrun` 去掉 `dawn_io_println(pass)`；`testrun.gen_pass` 去掉那次 println | `pair_report`：`reported 0 PASS + 0 FAIL lines, summary says 6` | **`pair` 的每一条全绿**——两个后端被同样地改坏，逐字节比对无话可说 |
| M3 退出码被丢掉 | `nmain.cmd_test` 不调 `io.exit(code)` | `test (a failing fixture)`、`test (failure message shapes)`（`exits jvm=1 native=0`）、第 7 条腿 | 全绿包、`pair_report`、第 8 条腿都不红 |
| M4 运行时不再逐行 flush | `runtime/c/dawn_rt.c` 的 `dawn_io_println` 去掉 `fflush`，`gen-rtsrc.py` 重生成 | **只有第 8 条腿**：`test native had 0 reports on stdout when it was killed, want 2` | **上面二十条逐字节比较全绿**，连第 5 条腿（lsp 中途应答）都绿——`dawn_io_print` 的 flush 没被动 |

四个变异体互相是对方的阴性对照，而且各自证明了一件不同的事：

- **M1 是这条腿的立论。** 它精确复现了「绿没有信息量」：全绿语料整条通过，连数得出 6 条
  PASS 行的计数检查也通过——因为 6 条 PASS 行确实被打了，只是没有一条 test 跑过。
  **所以失败语料是这条腿的承重墙**，一份点名了失败和断言原文的报告，不可能在没跑 test 的
  情况下产出。
- **M2 是 `pair_report` 的立论。** 两边同样改坏之后，`pair` 这个门禁**整条腿全绿**，只有
  「报告为自己结账」红。这就是为什么那个检查跑在两份 transcript 各自身上而不是跑在 diff 上。
- **M4 是第 8 条腿的立论**，也是 K-B3 那个教训的复演：批量重放拿到逐字节相同的输出，真实
  使用一个字都拿不到。

## 21. 这条 test 门禁不证明什么

1. **它不证明 native 的 `test` 和 JVM 的 `test` 在编译语义上等价**，只证明这十几条 argv
   下两边打出同样的字节。真正把「编译对不对」钉住的是 `spike-native/run.sh` 和
   `native-fixpoint.sh`，不是这里。
2. **它不覆盖 `--comptime-fuel` / `--comptime-ffi` / `--closure`。** 这个驱动的**任何**
   子命令都不收这几个 flag，所以那是驱动的缺口，不是这个子命令的。
3. **它不覆盖超过 512 字节的失败消息。** native 运行时在 `DAWN_FAILURE_MAX`
   （`dawn_rt.c`）处截断一条被捕获的失败消息，JVM 不截断，所以更长的消息是**真分歧**——
   属于 `catch_fault` 的，不属于这个 runner。语料里每条消息都刻意留在 512 字节以下。
4. **它不覆盖并发。** 两个 runner 都是顺序执行，没有任何断言这么说。
5. **第 8 条腿只看前两条报告。** 它说的是「报告是边跑边落盘的」，不是「每一行都单独
   flush」——后者今天成立（`dawn_io_println` 每行一次 `fflush`），但这条腿分不出「每行
   flush」和「每两行 flush」。

## 22. K-B7：native 二进制进 release artifact

在这一刀之前，一个 tag 只发布一件东西：`dawn-selfhost.jar`，跑它要有 JVM。native 后端
2026-07-30 起就能编译整个编译器（`scripts/native-fixpoint.sh` B==C），驱动的命令行也在
K-B2–K-B5 补齐了，所以有了第二件值得交到使用者手里的东西：**一个自带 std 与运行时的
单文件可执行程序**。

落地物是 `scripts/release-native.sh`（构建 + 四道检查 + sha256），`release.yml` 在 tag 上
调它并把产物挂进 release，`gates.yml` 的 `prev-diff-native` job **每次 push 都调同一个
脚本**（2026-08-07 之前这条腿在 `prev-diff` 里，拆并行时随 native-cli-diff 一起搬走）。

### 22.1 三项裁决

**裁决 A（产哪些平台/架构）= 只产 `linux-x86_64`，静态链接。**

`.github/workflows/` 里今天**只有 `ubuntu-latest` 一种 runner**（`grep runs-on` 实测
八处全是它——`ci.yml`、`release.yml`，与 `gates.yml` 拆并行后的六个 job）。不做交叉编译，
理由不是懒：**验收要求「真跑它并断言输出」（§22.2 检查 3），而交叉编译出来的二进制在同一个
job 里跑不了**——那就等于发一件没人执行过的产物，正是这一刀要防的失效形态本身。
加 `ubuntu-*-arm` / `macos-*` 矩阵要付的不只是一个 runner：每个 runner 得先把 jar 那条
seed→A→B 链重跑一遍，而 macOS 上的 `runtime/c` 从来没有人编过、更没有人跑过。

**缺什么，写在这儿**：`darwin-arm64`、`linux-arm64`、任何 musl/Windows 目标都没有产物。
补它们的门槛是「先让 `runtime/c` 在那个平台上过 `spike-native` 和 `native-fixpoint`」，
不是「加一行 matrix」。

**静态链接（`-static`）**是同一条理由的延续 `[实测]`：动态链接的产物在 runner 的 glibc 上
建、也只在那个 glibc 上验过，换台老一点的机器**起都起不来**——而这个失效在 CI 这一侧
永远看不见，因为 CI 的 glibc 恒等于它编译时用的那个。实测代价：2,888,200 B →
3,654,600 B（+26.6%），链接时间 15.26 s → 15.34 s（无差别），**零链接告警**——运行时不碰
NSS/dlopen（`grep -E "getaddrinfo|getpwnam|dlopen|gethostby|nss" runtime/c/*.c` 零命中）。

> **产物自带 std 与运行时源码，但 `run`/`build` 仍要机器上有 `cc`** `[grep]`：
> `nmain.cc_build` 把嵌入的 `dawn_rt.c/.h` 写到临时目录、然后 spawn `$CC`（默认 `cc`）。
> 所以「自包含」的准确含义是**不需要 Dawn 仓库、不需要 JVM**，不是「不需要 C 工具链」。
> `emitc` / `check` / `fmt` / `doc` / `lsp` / `add` 不碰 `cc`。

**裁决 B（与 jar 种子的关系）= 纯附加，种子纪律零牵动。**

引导种子是且只是 jar：`scripts/seed-release.txt` 点名 tag，`scripts/seedjar.sh` 只下载
`dawn-selfhost.jar`、只拿 `scripts/seed-checksums.txt` 校验它，`bin/dawn` 也只找 jar。
**没有任何东西读这个二进制**，所以 `seed-release.txt` / `seed-checksums.txt` 一个字节都不用动，
也不存在「N 代发射、N+1 代消费」的新链条。产物旁边那份 `.sha256` 是**下载完整性**，
不是种子校验和——`release.yml` 的注释里写死了这句话，免得下一次升种子的人把它填进
`seed-checksums.txt`。

要不要让 native 二进制也成为一种种子？**不。** 那等于开第二条引导血脉：它要有自己的
校验和表、自己的平台矩阵，而 native 今天的引导方式（每次由 JVM 工具链现编，
`native-fixpoint.sh`）既便宜又不需要信任任何历史产物。这条不在 B 线的范围里。

**裁决 C（CI 预算）= 每次 push 净增约 15 秒，不设成里程碑门禁。**

先量 `[实测]`（本机，`cc -std=c11 -O2 -fwrapv -fno-strict-aliasing -pthread -static`）：

| 步骤 | 秒 |
|---|---|
| `bin/dawn __emitc selfhost/src/nmain.dawn`（JVM 发射 182,841 行 C） | 5.85 |
| `cc -O2 -static` | 15.34 |
| 检查 2（`dawnc version`） | ~0 |
| 检查 3（裸目录 `run hello.dawn`，含它自己 spawn 的 `cc`） | 2.40 |
| 检查 4（`dawnc emitc nmain.dawn`，即 A==B） | 12.49 |
| **`release-native.sh` 整条**（jar 已在） | **35.4** |

关键在于**它不是净增 35 秒**：`native-cli-diff.sh` 本来就在 `prev-diff` job 里自己编一个
native 驱动（`:44–51`，同样是 `__emitc` + `cc`）。现在 `gates.yml` 先跑
`release-native.sh`，再用 `DAWNC_BIN=` 把产物交给它，那份构建不再付第二遍。
端到端直接量了两遍 `[实测]`：

| `prev-diff` 里这一段 | 秒 |
|---|---|
| 改之前：`native-cli-diff.sh`（自己编驱动，8 条腿全绿） | 99.5 |
| 改之后：`release-native.sh` 35.4 + `DAWNC_BIN=… native-cli-diff.sh` 70.5（自己不编了，8 条腿全绿） | 105.9 |
| **净增** | **+6.4** |

六秒，落在一个本来就要跑三条 N−1 差分的 job 上。

顺带得到一件比省时间更值钱的事：**八条差分腿从此跑在「真要发布的那个二进制」上**，
而不是一个用同样配方另编的。tag 那侧则是 `release.yml` 多 35 秒，相对它本来就要建三个 jar
的链条可以忽略。

所以**不**把它设成里程碑门禁 —— 恰恰相反，把它放进每次 push 才是重点：
**只在 tag 上跑的步骤是全仓最少被执行的代码，也就最可能在真要用它的那天是坏的。**

### 22.2 `release-native.sh` 的四道检查，以及每道为什么不被上一道蕴含

发布流水线是「绿不携带信息」最纯的形式：下面每一种失效，**流水线都照样报成功**。

| # | 检查 | 它单独拦住的失效 |
|---|---|---|
| 1 | 产物存在、非空、可执行 | 打包步骤静默什么都没做；`\|\| true` 吞掉失败；`-o` 写去了别处 |
| 2 | 跑得起来，且 `dawnc <VERSION> (native)` 与**本棵树的** `version.dawn` 一致（`release.yml` 另传 `--expect ${GITHUB_REF_NAME#v}`，把 tag 也钉进来） | 起不来的二进制（缺共享库、架构不对）与没人试过的二进制在「文件存在」下一模一样；上一次发布留下的产物也是一个普通文件 |
| 3 | 从**只有一个 `.dawn` 文件的裸目录**编译并运行一个程序，输出对**写死的期望** | 检查 1 与 2 一个会 echo 版本号的 shell 脚本全能满足。这一道才是「它是个编译器」 |
| 4 | 它对编译器自己的源码发射出的 C，与**建它的那套工具链**逐字节相同（`native-fixpoint.sh` 的 A==B 腿） | 发布路径上本来没有任何门禁跑 A==B（`native-fixpoint.sh` 不在 `gates.yml` 里） |

**检查 4 是 A-vs-B，因此对「两边同样地变」天生失明**——驱动自己的源码改一行，jar 发射的 C
和二进制发射的 C 会同样地变。接住这一类的是**单侧不变式**：检查 2 和 3 的 oracle 写在
脚本里，不从另一侧读。§22.3 的 M4 就是这条的实证。

还有一行不是检查、却是上面全部的前提：**先删后建**（`rm -f "$OUT" "$OUT.sha256"`，在
`cc` 之前）。发布的必须是这一次产出的东西。M1b 量了它的分量。

### 22.3 红演示与阴性对照 `[实测]`（2026-08-04）

> 全仓规矩：**一个从没被证明能变红的绿，不携带信息**。

| 变异体 | 改哪儿 | 谁红 | 谁不红（判别力） |
|---|---|---|---|
| **M1** 产物根本没生成 | `cc … -o "$OUT"` → `-o "$OUT.tmp"`（一处像样的打包笔误） | 检查 1 | —— |
| **M1b** 同一个笔误 + **去掉「先删后建」那一行** | 同上，再删 `rm -f "$OUT" …` | **谁都不红：四道全绿、`exit=0`** | 这一屏证明的是**那行 `rm -f` 才是承重墙**，不是四道检查 |
| **M2** 产物在、也答版本，但不是编译器 | `cc` 之后把 `$OUT` 覆盖成 `#!/bin/sh; echo "dawnc 0.49.0 (native)"` | 检查 3、检查 4 | **检查 1、2 全绿**——「文件存在」和「答得出版本」分不出它 |
| **M3** 产物是陈旧的 | 脚本加一句「`$OUT` 已存在就复用」（一个像样的缓存优化）；盘上是 0.49.0 的构建，树 bump 成 0.49.1 | 检查 2 | **检查 3 绿**——陈旧的二进制仍是个能用的编译器，只有版本断言分得出 |
| **M4** 驱动源码改了：**两侧同样地变** | `nmain.cmd_run` 开头加 `println("dawnc: running")` | 检查 3 | **检查 4（A==B）绿**——跨侧比较对这一类失明，这正是单侧不变式的立论 |

```
######## M1 (cc -o writes a name nothing publishes) -- expect RED
building dawnc-linux-x86_64 (0.49.0) from selfhost/src/nmain.dawn...
FAIL: /tmp/.../art/dawnc-linux-x86_64 was not produced (or is empty / not executable)
==> exit=1

######## M1b (same typo, but without the 'delete first' line) -- expect GREEN, i.e. it would ship yesterday's binary
building dawnc-linux-x86_64 (0.49.0) from selfhost/src/nmain.dawn...
OK   the artifact exists (3654600 bytes)
OK   it runs and reports 0.49.0
OK   it built and ran a program from a bare directory (embedded std + runtime)
OK   it emits the same C as the toolchain that built it (A == B)
77124e48600d575e4a84bcb30866e9f596aab5973310bc61dca90652a68235f4  dawnc-linux-x86_64
OK: dawnc-linux-x86_64 is a 0.49.0 compiler, built and checked here
==> exit=0            ← 这一次什么都没编译。四道检查全在夸奖上一次的产物。

######## M2 (the published file is not the binary: a stub that answers 'version') -- expect checks 1+2 GREEN, 3+4 RED
building dawnc-linux-x86_64 (0.49.0) from selfhost/src/nmain.dawn...
OK   the artifact exists (39 bytes)
OK   it runs and reports 0.49.0
FAIL: the artifact ran the smoke program wrong
1,2c1
< 1,2,3
< RELEASE
---
> dawnc 0.49.0 (native)
FAIL: the artifact emits different C than the toolchain that built it
diff: /tmp/tmp.IjV42Fy2ZB/self.c: No such file or directory
FAIL: the native release artifact did not check out
==> exit=1

######## M3 (a 'reuse the existing artifact' cache; the file on disk is a 0.49.0 build, the tree is 0.49.1) -- expect RED
reusing dawnc-linux-x86_64
OK   the artifact exists (3654600 bytes)
FAIL: the artifact says 'dawnc 0.49.0 (native)', this tree says 'dawnc 0.49.1 (native)'
OK   it built and ran a program from a bare directory (embedded std + runtime)
FAIL: the artifact emits different C than the toolchain that built it
diff: /tmp/tmp.uj5KQV8nge/nmain.c: No such file or directory
FAIL: the native release artifact did not check out
==> exit=1

######## M4 (the driver itself changed: both the jar's C and the binary carry it) -- expect check 4 GREEN, check 3 RED
building dawnc-linux-x86_64 (0.49.0) from selfhost/src/nmain.dawn...
OK   the artifact exists (3654672 bytes)
OK   it runs and reports 0.49.0
FAIL: the artifact ran the smoke program wrong
0a1
> dawnc: running
OK   it emits the same C as the toolchain that built it (A == B)
FAIL: the native release artifact did not check out
==> exit=1
```

阴性对照 `[实测]`：

```
######## 未变异的树 + 未变异的脚本 -- expect GREEN
OK   the artifact exists (3654600 bytes)
OK   it runs and reports 0.49.0
OK   it built and ran a program from a bare directory (embedded std + runtime)
OK   it emits the same C as the toolchain that built it (A == B)
77124e48600d575e4a84bcb30866e9f596aab5973310bc61dca90652a68235f4  dawnc-linux-x86_64
==> exit=0

######## M3 的阴性对照：同一棵 0.49.1 的树、盘上同一个陈旧文件、未变异的脚本
building dawnc-linux-x86_64 (0.49.1) from selfhost/src/nmain.dawn...
OK   it runs and reports 0.49.1
5d8b81151a51ba8a81e1704ec6ac366155255e2e90355698ce0b1f402509db12  dawnc-linux-x86_64
==> exit=0            ← 版本一变，产物跟着变（sha 也变了）

######## --expect 与树不一致（一个不指向这个 VERSION 的 tag）
error: --expect 0.50.0 but selfhost/src/version.dawn says 0.49.1
==> exit=1            ← 在编译任何东西之前就拒绝
```

**M1b 是这一节的立论**，也是全仓那条规律在发布产物上的形态：四行 `OK` 和一个 `exit=0`，
而这次运行**一个字节都没有编译**。检查全对，被检查的东西是上一次留下的。

顺带一件量出来的事：同一棵树连续三次构建，产物 sha256 恒为 `77124e48…`——`cc` 在这台机器上
是**可复现的**。这不是承诺（没有门禁盯着它），只是记下来。

### 22.4 这一刀挖出来的：`set -o pipefail` 会把汇总吃掉

`diff a b | head -20` 在 `set -euo pipefail` 下是**致命的**：`diff` 回 1，`head` 回 0，
管道取 `diff` 的 1，`set -e` 当场杀掉脚本——于是那句「FAIL: 产物没通过检查」的汇总行
**永远不会打印**，而退出码碰巧还是 1，所以看起来一切正常。是 M2 的第一次运行把它照出来的
（输出停在 diff 那几行，第 4 道检查和汇总行都不见了）。修法是两处 `| head -20 || true`。

写下来是因为它是这一刀的教训的一个小号版本：**变异体不只证明门禁能红，它还顺手证明门禁
红得对不对。**

### 22.5 这套东西不证明什么

1. **它不证明产物在别的机器上能跑。** 静态链接把 glibc 版本这一类拿掉了，但没有任何
   门禁在第二台机器上执行过这个二进制 `[推论]`。真要这句话，得有一个 runner 矩阵。
2. **它不覆盖 `linux-x86_64` 以外的任何目标**（裁决 A），也不覆盖没有 `cc` 的机器上的
   `run`/`build`。
3. **它不证明 release 页面上真的挂上了两个文件。** `gh release create` 逐个点名文件
   （不用 glob，所以「glob 没匹配到」这条路被堵死了），文件缺失会让那一步失败——但
   「上传成功」这件事只有 tag 那次真跑才知道，本机复现不了 `[推论]`。
4. **检查 4 不是防陈旧的主力。** 一个从别的树来的二进制，只要它的 codegen 与今天一致，
   A==B 照样绿；防陈旧靠的是「先删后建」加检查 2 的版本断言（M1b 与 M3 分别是这两条的
   证明）。
5. **它不说产物是可复现构建。** §22.3 末尾那个恒定的 sha 是一次观察，不是被断言的性质。
