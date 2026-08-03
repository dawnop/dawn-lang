# B 线：native 驱动补全 + 把后端契约摆到明面上

> 状态：**in progress**（2026-08-03 立项，任务 #128；K-B1/K-B2/K-B3 已落地，下一刀 K-B4）。
> 本文是 B 线的落地记录 + 后续刀表。
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
| **K-B4** | `test`（`testrun.dawn`；JVM 侧靠生成一个 test main 类，native 侧要另一条路） | 加能力 | 待 |

> 刀表的**内容**来自任务 #128 的描述。原始 issue body 在写这份文档时取不到
> （`api.github.com/repos/dawnop/dawn-lang/issues/128` 回 404，本仓 issue 不公开），
> 所以上表是照任务简报转录的，**不是从 issue 原文抄的** `[推论]`。K-B3/K-B4 的行数是
> `wc -l` 实测。

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
`runtime/c/` 改了就得 `python3 scripts/gen-rtsrc.py` 重生成 `selfhost/src/rtsrc.dawn`
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
   「JVM vs native」跨后端比较（像 `doc`/`add` 那样），它就会全绿——**这正是 §9.1
   记的那个盲点**。这条腿之所以躲开了它，是因为它比的是 **N−1 发布**，而不是另一个
   后端。代价是另一头：**它每次发布都要重新对齐**，而 §9.1 那条链（native == JVM == N−1）
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
