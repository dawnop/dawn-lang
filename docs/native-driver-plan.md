# B 线：native 驱动补全 + 把后端契约摆到明面上

> 状态：**in progress**（2026-08-03 立项，任务 #128；K-B1/K-B2 已落地，下一刀 K-B3）。
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
| **K-B3** | `lsp`（`lsp.dawn` + `lspq.dawn` + `lspc.dawn`，2,877 行） | 加能力 | 待 |
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
| `selfhost-lsp-diff.sh` | 只 JVM | 仍只 JVM（native 还没有 `lsp`，K-B3） |
| `native-fixpoint.sh` | native（只 `emitc`/`run`） | native（同前；TU 变大了，见 §7） |
| `spike-native/run.sh` | 两后端（跑用户程序） | 同前 |
| `native-cli-diff.sh` | **不存在** | **两后端**：`fmt`/`doc`/`add` |
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

- **K-B3（`lsp`）**：`lsp.dawn` + `lspq.dawn` + `lspc.dawn` = 2,877 行，零 `use java`
  `[实测]`。接线之后 `selfhost-lsp-diff.sh` **同样不会自动覆盖 native**——它的 `SELF`
  也是写死的 `./bin/dawn`（§5）。照 §5.1 的形状给它加 `DAWN_SELF` 即可。
- **K-B4（`test`）**：不是接线活。JVM 侧靠 `testrun.gen_test_main` 生成一个 test main
  类再在同一个 JVM 里跑；native 侧没有「生成一个类塞进去」这回事，得走另一条路
  （最直白的是把 test 块编进那个 C 翻译单元，由 `nmain` 直接调用）`[推论]`。
