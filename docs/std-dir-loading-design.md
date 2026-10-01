# std 目录加载：谁回答了 `modules.txt`，谁决定整次加载

> 状态：**current**。2026-10-01，issue #206（分支 `fix/std-dir-loading`）；同日 #291（分支 `fix/std-default-no-cwd`）补「缺省来源」一节。
> 调研是 `research-issue-severity-20261001` 的 §#206（严重度 S1，批 B1）；本文记规则、两条复现、测试与不做的。

## 问题

`load_std(dir)` 先问 `modules.txt`：目录里有就用目录的，没有就用编译器内嵌的那份（`embed/stdsrc.dawn`）。
版本检查、报错里的「哪一半 std」（`StdOrigin`）、`StdCtx.dir` 都按这一问的答案走。
但随后逐个模块读源码时调的是 `std_read_from(dir, "<n>.dawn")`，它**每个文件都先读目录、读不到再退内嵌**。
于是一次加载的来源在模块粒度上是混的，而且完全无声。两条复现（v0.79.0 selfhost，修前）：

**复现 1：`--std` 目录缺一个模块（issue 原例）。**

```
$ cp -r std stdx && rm stdx/map.dawn        # VERSION 与 modules.txt 都在
$ dawn run --std stdx usemap.dawn           # use std/map; map.from / map.get
Some(1)
exit=0
```

`std/map` 静默来自内嵌副本，其余模块来自 `stdx`。

**复现 2：cwd 里一个零散的 `std/str.dawn`（调研新发现，比 issue 更坏）。**
`--std` 的缺省是相对 cwd 的 `std`。目录里没有 `modules.txt` 时由内嵌回答，
`origin = StdEmbedded`、`declared = Some(VERSION)`，版本检查必然通过；可模块循环仍先读目录：

```
p206b/std/str.dawn   # 真 std/str.dawn 的拷贝，只把 to_upper 的体改成 str_lower(s)；无 modules.txt、无 VERSION
p206b/up.dawn        # use std/str; println(str.to_upper("Hello"))

$ cd p206b && dawn run up.dawn          -> hello   exit=0
$ cd ..    && dawn run p206b/up.dawn    -> HELLO   exit=0
```

同一个源文件在两个 cwd 下是两个程序，零提示。那个文件还会被登记进 `dir_modules`，
LSP 跳转与 `std_module_of` 也跟着把它认作 std。

## 规则

**谁回答了 `modules.txt`，谁决定整次加载；不再逐文件回退。**

1. `modules.txt` 来自目录：它列出的每个模块都必须来自这个目录。缺的先**收集齐**，
   在解析任何模块之前一次报错（`StdFail` 新变体 `StdModulesMissing(files)`），文案列出全部缺失的文件名，不回退。
   这个错误的 origin 是 `StdFromDir(dir)`，所以 `std_load_is_bug` 答 false，按用户环境报（exit 2），不是编译器 panic。
2. `modules.txt` 来自内嵌：**整套**用内嵌，目录里任何 `.dawn` 都不读；`dir_modules` 为空、`dir = None`，
   LSP 身份（`std_module_of` / `std_file_of` / `is_std_dir`）也不认那个目录。
   既有测试「a std directory with no modules.txt falls back to the embedded copy」语义不变。
   内嵌副本本身缺一个它自己列出的模块只能是编译器 bug（`gen-stdsrc.py` 与「the embedded std matches std/ on disk」测试不让它发生），
   走同一个 `StdModulesMissing` 变体，origin 是 `StdEmbedded`，报成「This is a bug in dawn」。

判据取自 rustc：sysroot 里找不到 `std` 就报 E0463，不会从别处拼一个 std 出来。
目录要么完整，要么不被读；「优先用这个 std、缺的拿我的补」这层意思从来没写进 `--std` 的说明，
而它恰好只在用户正在调试 std 本身时才会出结果差异。

`read_index`（`std_read`）对 `modules.txt` 的「目录优先、退内嵌」保留：那一问本来就是在决定由哪一半回答。
`std_read_from` 只剩这一个用途，模块文本改由 `std_module_text` 按那一问的答案只读一半。

## usage

`dawn`（`main.dawn`）的 usage 原来根本没提 `--std`；`dawnc`（`nmain.dawn`）只在各子命令的语法里写了 `[--std <dir>]`。
两边加同一段说明：目录必须完整；没有 `modules.txt` 的目录被忽略，使用编译器内嵌的 std。
#206 时缺省值仍是相对 cwd 的 `std`，说明里如实写了；#291 改了缺省，说明随之改成下一节的顺序，`dawn` 的 usage 在
「environment」下另列 `DAWN_STD`。

## 缺省来源（#291）

#206 之后剩下的只有一种情形：cwd 下一整套**完整**的 `std/`（有 `modules.txt`、有本 release 的 `VERSION`）。
它什么都不缺、什么都不会被拒，于是在任何带 `std/` 的 checkout 或项目里跑 `dawn run`，编的就是那份 std：
本 release 的戳则静默加载（连同本地改动）；别的 release 的戳则报一个用户没要求的版本不符；没戳则静默加载，
出错时报在一个用户没点名的目录上。「用哪份 std」成了 shell 站在哪儿的属性，而不是工具链或命令行的属性。

**规则：`--std <dir>` → `DAWN_STD`（非空）→ 编进工具链的那份。从不读工作目录。**
两个驱动的每个子命令（check/run/test/build/doc/emit/emitc/`__lower`/`__check`）和 `lsp` 都走同一个函数：
`driver/stdlib.dawn` 的 `std_choice(flag, from_env) -> Option[String]`（`None` 即内嵌），
`cli_std_choice(flag)` 读本进程的 `DAWN_STD` 喂给它，`load_chosen_std(choice)` 按答案加载；
`None` 时**根本不问任何目录**，直接由内嵌回答 `modules.txt`。`dawnc` 没有 launcher，也读 `DAWN_STD`，
两个驱动的契约由 `scripts/native-cli-diff.sh` 的 leg 0c 钉成一份。

先例（`research-issue-severity-20261001` §#206 末段）：rustc 从自身位置（或 `--sysroot`）找 sysroot，
找不到 `std` 报 E0463 而不去别处找；Go 用 `GOROOT`，由工具链位置或环境给出。两者都不看 cwd。
Dawn 的对应物早就有一半：`bin/dawn` 解析自己的真实位置，`$ROOT/std` 存在时导出 `DAWN_STD`（继承来的优先），
`dawn lsp` 此前已按「flag → DAWN_STD → cwd 的 `std`」找；这次把最后一档换成内嵌，并让其余子命令照做。
LSP 也一起改，理由同一：一个从 cwd 找 std 的 server 在编辑器给的随便哪个 cwd 下都可能拿到别人的 std。

**空的 `DAWN_STD` 当作没设。** `DAWN_STD= dawn ...` 是 shell 里「这一条命令不要这个变量」的写法；
把它读成相对路径 `""` 等于把 cwd 请回来。

**仓内开发不变**：`bin/dawn` 照旧导出 `DAWN_STD=$ROOT/std`，所以经 launcher 的一切都还在用 checkout 的 std，
包括 LSP 的「std 文件认得出是 std」。变的只有**直接跑 jar 或 `dawnc` 而又没给 `--std`/`DAWN_STD`** 的调用，
从 cwd 的 `./std` 变成内嵌那份。内嵌那份与树上的 `std/` 逐字相同（`the embedded std matches std/ on disk` 测试与
`gen-stdsrc.py` 保证），所以对 HEAD 构建出的编译器，源码文本等价；差别只在**出处**：目录供给的 std 有文件
（LSP 跳转能落到 `std/x.dawn`、`dawn check std/x.dawn` 认得它是 std），内嵌的没有。逐个调用点的测量见
`agent-handoff/issue-291-report-20261001.md` 第一节；需要出处或需要一份非 HEAD std 的地方都已显式给了
`--std` 或 `DAWN_STD`（差分脚本里种子的包装器、`native-cli-diff.sh` 里的 `dawnc`）。

**负控**：`std_choice` 最后一档改回 `Some("std")`，`driver/stdlib` 两条新测试与 `lsp/server` 的顺序测试一起红
（报告里贴了 FAIL）。

## 测试

`driver/stdlib.dawn`，内存文件系统（`driver/fsmem`），不碰宿主磁盘：

- (a)「a std directory missing modules it lists is refused, naming every one」：`mem_std` 挂整套 std，删掉 `map.dawn` 与 `set.dawn`，
  `load_std` 必须 `Err`，why 是 `StdModulesMissing`，文案里两个文件名都在，`std_load_is_bug` 为 false。
- (b)「a std directory with no modules.txt is not read at all」：表里只有 `std/str.dawn`（`to_upper` 体改成 `str_lower`），
  `load_std` 成功，`std_file_of(std, "std/str") == None`，`dir == None`，`std/str` 的源码等于内嵌那份。
- 端到端「a stray std/str.dawn under the working directory changes no program」：同一张表，用相对拼写 `load_std("std")`（#206 时它就是 CLI 缺省）
  （表的 base 就是 cwd），再 check 并 comptime 求值一个 `use std/str` 的用户模块 `str.to_upper("Hello")`，必须得 `"HELLO"`。
  这条走的是加载、检查、求值的整条链；CLI 层的 `dawn run` 复现另在报告里修前修后各跑一次。

负控：把 `std_module_text` 换回 `std_read_from` 的逐文件回退，三条都红（报告里贴 FAIL）。

#291 加两条，同在 `driver/stdlib.dawn`：

- 「a command's std is --std, then DAWN_STD, then the embedded copy」：`std_choice` 的四种输入（含空 `DAWN_STD`），
  外加 `cli_std_choice` 在 `envmem` 表下只问 `DAWN_STD` 一个名字、不问 cwd。
- 「a complete std under the working directory is not the default」：内存表的 base（即 cwd）下挂一整套 std，
  `to_upper` 改成小写；无 flag 无 `DAWN_STD` 时 `dir == None` 且折叠出 `"HELLO"`；`DAWN_STD` 指向它时 `dir` 是它且折叠出 `"hello"`。

`lsp/server.dawn` 的顺序测试改成断言同一个 `std_choice`，最后一档从 `"std"` 改为 `None`。

## 版本说明

仓库没有 CHANGELOG（`builtin-fn-value-lowering-design.md` 记过同样的情况），版本说明由发版人带上这两句。#206：
`--std` 目录必须完整：带 `modules.txt` 的目录缺模块时报错并列出缺失模块，不再静默用内嵌副本补；
没有 `modules.txt` 的目录（包括 cwd 下零散的 `std/*.dawn`）整个被忽略。
行为收紧只影响残缺目录与零散文件，二者今天都是错结果；dawnop-site 不用 `--std`、仓库根下没有 `std/`，不需要先发 tag。

#291：不给 `--std` 时，std 来自 `DAWN_STD`（非空），再不然是编进工具链的那份；**不再读工作目录下的 `std/`**。
经 `bin/dawn` 的用法不变（launcher 导出 `DAWN_STD`）；直接 `java -jar dawn-selfhost.jar` 或跑 `dawnc` 而依赖 cwd 下 `std/` 的，
改给 `--std std` 或设 `DAWN_STD`。`dawn lsp` 同此。这是修 bug（同一程序在不同 cwd 下编成不同程序），
不需要先发 tag：dawnop-site 经 launcher，且仓库根下没有 `std/`。

## 不做的（理由）

- **#206 时不改 `--std` 的 cwd 缺省**，单独量过后由 #291 改掉（见「缺省来源」）。
- **#291 不让 `bin/dawn` 之外的东西猜 std 的位置。** 不从 jar 自身路径推 `../std`：发布的 jar 旁边没有 `std/`，
  推出来的只会是一个不存在的目录或一个碰巧在那儿的别人的目录；工具链位置这件事 `bin/dawn` 已经在做（跟随软链找真 checkout），
  编译器只认它给的 `DAWN_STD`。
- **#291 不在 cwd 有 `std/` 时报 warning。** 那等于承认 cwd 仍是候选；而 CLI 与 LSP 都没有一个 warning 一定会被看到的位置（同 #206 的理由）。
- **#291 不动 `contract/` 下几个测量程序与 `doc.dawn`/`lsp/server.dawn` 测试里的 `load_std("std")`。** 那是代码里显式写的相对目录，
  不是 CLI 缺省；它们在仓库根跑，读的就是要测的那棵树。
- **不做「报一次 warning 然后继续」。** issue 的验收允许二选一；选报错，因为 warning 之后的程序仍是两半 std 拼出来的，
  而 CLI 与 LSP 都没有一个 warning 一定会被看到的位置。
- **不给缺 `modules.txt` 的目录报错。** `--std` 指向一个与 std 无关的路径今天是合法且被测试钉住的（std-version 契约的 `ASSERT_FALLBACK`），
  它表示「这里没有 std」，而不是「这里的 std 残缺」。
