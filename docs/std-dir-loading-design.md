# std 目录加载：谁回答了 `modules.txt`，谁决定整次加载

> 状态：**current**。2026-10-01，issue #206（分支 `fix/std-dir-loading`）。
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
缺省值仍是相对 cwd 的 `std`，说明里如实写出来（见「不做的」）。

## 测试

`driver/stdlib.dawn`，内存文件系统（`driver/fsmem`），不碰宿主磁盘：

- (a)「a std directory missing modules it lists is refused, naming every one」：`mem_std` 挂整套 std，删掉 `map.dawn` 与 `set.dawn`，
  `load_std` 必须 `Err`，why 是 `StdModulesMissing`，文案里两个文件名都在，`std_load_is_bug` 为 false。
- (b)「a std directory with no modules.txt is not read at all」：表里只有 `std/str.dawn`（`to_upper` 体改成 `str_lower`），
  `load_std` 成功，`std_file_of(std, "std/str") == None`，`dir == None`，`std/str` 的源码等于内嵌那份。
- 端到端「a stray std/str.dawn under the working directory changes no program」：同一张表，用 CLI 缺省的相对拼写 `load_std("std")`
  （表的 base 就是 cwd），再 check 并 comptime 求值一个 `use std/str` 的用户模块 `str.to_upper("Hello")`，必须得 `"HELLO"`。
  这条走的是加载、检查、求值的整条链；CLI 层的 `dawn run` 复现另在报告里修前修后各跑一次。

负控：把 `std_module_text` 换回 `std_read_from` 的逐文件回退，三条都红（报告里贴 FAIL）。

## 版本说明

仓库没有 CHANGELOG（`builtin-fn-value-lowering-design.md` 记过同样的情况），版本说明由发版人带上这一句：
`--std` 目录必须完整：带 `modules.txt` 的目录缺模块时报错并列出缺失模块，不再静默用内嵌副本补；
没有 `modules.txt` 的目录（包括 cwd 下零散的 `std/*.dawn`）整个被忽略。
行为收紧只影响残缺目录与零散文件，二者今天都是错结果；dawnop-site 不用 `--std`、仓库根下没有 `std/`，不需要先发 tag。

## 不做的（理由）

- **不改 `--std` 的 cwd 缺省。** 缺省读相对 cwd 的 `std` 本身就是隐患（在别人的 checkout 里跑会加载他们的 std），
  但改它会动仓内开发流程与 LSP 之外的所有子命令的缺省，需要单独量；另开 issue：CLI 缺省改读 `DAWN_STD`
  （`bin/dawn` 已导出）再退内嵌，不读 cwd，先例是 rustc 的 sysroot 与 Go 的 `GOROOT`。
  本批的规则 2 已经让「cwd 下零散文件」不再能改变程序，剩下的只有「cwd 下一整套完整 std」这一种情形。
- **不做「报一次 warning 然后继续」。** issue 的验收允许二选一；选报错，因为 warning 之后的程序仍是两半 std 拼出来的，
  而 CLI 与 LSP 都没有一个 warning 一定会被看到的位置。
- **不给缺 `modules.txt` 的目录报错。** `--std` 指向一个与 std 无关的路径今天是合法且被测试钉住的（std-version 契约的 `ASSERT_FALLBACK`），
  它表示「这里没有 std」，而不是「这里的 std 残缺」。
