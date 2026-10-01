# std 的迁移提示归 std：`std/moved.txt`、到期与「删 pub 必须表态」

> 状态：**current**。2026-10-01，issue #211（分支 `fix/std-moved-table`）。
> 调研是 `research-issue-severity-20261001` 的 §#211（严重度 S2-3，批 B3）；本文记文件格式、到期规则、门与不做的。

## 问题

编译器里有两张手写的 std 迁移史，都没有到期、也没有和 std 对账：

- `check/checker.dawn` 的 `renamed_std_fn`：六条 `(模块路径, 名字)` → 提示，全是 v0.55.0 的改名
  （`str.substring`、`cursor.at`、`bytes.get`、`fmt.atoi`/`atoi_radix`/`atod`）。只在模块限定调用
  `alias.f(...)` 找不到 `f` 时查。
- `driver/stdlib.dawn` 的 `moved_renames`：约七十条扁平拼写（`map_insert`、`io_read_file`、`java_try` 等）
  → 提示，装进 `cx.moved`，裸名解析失败时经 `moved_or_suggest` 查。

两张表都只会加不会删；std 今天删一个 pub 函数，既没有提示，也没有任何东西提醒谁去写一条。
编译器只和同版本的 std 一起跑（`std/VERSION` 必须等于 `VERSION`），所以「这个名字去哪了」是 std 的
发布史，不是检查器的知识。

## 规则

### 1. 数据归 std：`std/moved.txt`

每行一条，字段以空白分隔，`#` 起到行尾是注释（所以提示文案里不能有 `#`），空行跳过：

```
<scope>  <old>  <new>  <since>  <until>  <hint...>
```

| 字段 | 含义 |
|---|---|
| `scope` | `std/<module>`：模块限定拼写 `alias.old(...)`；`builtin`：扁平拼写 `old(...)` |
| `old` | 不再能写的名字 |
| `new` | 现在的写法，`<module>.<fn>` 或 builtin 名；没有替代写 `-` |
| `since` | 名字离开的那个 release，`X.Y.Z` |
| `until` | 这条提示的到期 release，缺省 `since` 之后 10 个 minor |
| `hint` | 行余下的全部文字，原样作为诊断的 hint；字面量 `no-hint` 表示「有意删除、不给提示」 |

`no-hint` 行是门的显式表态（见 §3），加载器不把它装进提示表。

加载：`load_std` 从**回答了 `modules.txt` 的那一半**读 `moved.txt`（#206 的规则，目录与内嵌不混），
内嵌副本由 `scripts/gen-stdsrc.py` 与模块一起生成进 `embed/stdsrc.dawn`。文件缺席等于没有条目：
测试与合约手拼的一模块 std、只拷 `*.dawn` 与 `modules.txt` 的副本都照常加载；提示缺了只少一句话，
不改变任何程序的接受集。文件在但写坏了（字段不足、版本不是 `X.Y.Z`、`until` 不晚于 `since`、
`scope` 不认识、同一 `(scope, old)` 两次）是加载失败，报 `moved.txt` 的行号。

两类条目进同一张 `cx.moved`（不给 `Cx` 加字段）：

- `builtin` 条目以 `old` 为键，保持原先的读法：`` `old` is not a builtin; <hint> ``。
- `std/<m>` 条目以 `std/<m>.old` 为键。裸名里不会有 `/`，所以两类键不会撞。
  `check_module_call` 在「private」与「did you mean」两个分支之前按**模块路径**（不是别名：
  `use std/str as s` 改的是别名）查它，命中时报 `` module `std/<m>` has no exported function `old` ``
  加这条 hint，与 `renamed_std_fn` 原来的形状一致。

由导出面自动生成的那部分 `cx.moved`（`trim` → `use std/str, then str.trim(...)`）不是历史，照旧。

### 2. 到期

`until` 到了，要么删这一行，要么把 `until` 往后挪；两种都是一次提交里的显式决定。
`dawn test selfhost` 里的「moved.txt 的每条都没到期」读内嵌副本，把每条的 `until` 与 `VERSION` 比：
`VERSION >= until` 即红，并打印那一行。发版改 `VERSION` 的那次提交因此会被逼着处理所有到期条目。

**现有两张表按各自的 `since` 判，全部过期**（今天 `VERSION` 是 0.79.0，未过期要求 `since >= 0.70.0`）。
`since` 取名字离开的 release，由 `git log -S` 找引入提示的提交再 `git describe --contains` 得出：

| 条目 | since | until | 结论 |
|---|---|---|---|
| `renamed_std_fn` 六条 | 0.55.0 | 0.65.0 | 删 |
| 扁平 `str_len` `char_to_string` `reverse_str` `byte_*` `index_of_from`、`map_*` `set_*` `cursor_*` | 0.6.0 | 0.16.0 | 删 |
| `io_list_names` | 0.11.0 | 0.21.0 | 删 |
| `bytes_utf8` 等、`str_*` 的首批 | 0.19.0 | 0.29.0 | 删 |
| `bytes_from_array` | 0.28.0 | 0.38.0 | 删 |
| `str_trim` 等六个搜索 | 0.30.0 | 0.40.0 | 删 |
| `java_try` | 0.31.0 | 0.41.0 | 删 |
| `io_*`（RD-02），`str_lower`/`str_upper` | 0.32.0 | 0.42.0 | 删 |
| `bytes_decode`（RP-04） | 0.38.0 | 0.48.0 | 删 |
| `bytes_decode_utf8` | 0.41.0 | 0.51.0 | 删 |
| `map_size`、`set_size`（RD-06） | 0.42.0 | 0.52.0 | 删 |
| `io_temp_file`、`io_copy_permissions` | 0.63.0 | 0.73.0 | 删 |
| `std/bytes.decode_utf8`（LIB-06，从未有过模块限定提示） | 0.67.0 | 0.77.0 | 不补 |

所以本批交付的 `std/moved.txt` 只有表头与格式说明，没有条目。提示路径本身由一条测试钉住：
它拼一个带 `moved.txt` 的临时 std，确认模块限定与扁平两类条目都产生原来形状的诊断。

v0.79.0 → HEAD 之间没有 pub std 函数消失，门在今天的树上是绿的；v0.78.0 → v0.79.0 那次
`std/hamt`、`std/pvec` 改 `pub(pkg)`（`54e6892b`）若当时有这道门，会要求 26 行 `no-hint`：
这两个模块一直是 StdOnly，用户从没写得到。

### 3. 删 pub 必须表态：`scripts/std-moved-check/`

`check.py --old <上一 release 的 std> --new std`：两边各取 `modules.txt` 列出的模块里**顶格**的
`pub fn <name>`（`pub(pkg) fn` 与缩进的 impl 方法不算），旧有新无的每个 `std/<m>.<name>` 必须在新树的
`moved.txt` 里有 `scope = std/<m>`、`old = <name>` 的一行（提示或 `no-hint` 都算），否则红，列出全部缺口。
`new` 写成 `<module>.<fn>` 时还要求它是新树里真实存在的 pub 函数，免得提示指向一个同样不存在的名字。

基线是种子 release 的 std：`run.sh` 经 `scripts/seedjar.sh` 的 `seed_std_dir` 取得，它按
`seed-std-checksums.txt` 校验过，也正是「上一 release」的定义（发版后种子推进到它）。
CI 放在 `std-version` job 的末尾：那里已经有工具链与缓存的种子 std，这一步只读文本，本机 0.1 s 量级。

为什么不直接扩 `scripts/api-diff.py`：它是 release 时对两个已发布 snapshot 出的**报告**，头部写明
「a report, not a gate」，snapshot 需要跑一遍 `dawn doc`；门需要的是每次 push 在树上可跑、零编译的判定。
两者判「删除」的口径一致（模块 `fns` 集合的差），差别只在输入的来源。

`check.py` 按字面读 std 源文本，在 `scripts/anchor-readers.txt` 登记为 `not-anchor`：它读的是清单
（顶格 `pub fn` 全集，两边比），不定位任何要改的代码。

## 为什么不用属性语法

外部同类做法都把迁移信息挂在库的声明上并给出生命周期：Rust `#[deprecated(since, note)]`
（rustc 不解释 `since`，rustdoc 显示、Clippy 校验），Kotlin `@Deprecated(level, replaceWith)` 的
WARNING → ERROR → HIDDEN，Swift `@available(*, unavailable, renamed:)` 给删掉的 API 留墓碑声明。
Dawn 没有属性语法，而被删的名字恰恰已经没有声明可挂。std 自带的数据文件是离「声明处」最近的形态：
它随 std 发布、随 `VERSION` 一起校验，由 std 的作者在删名字的同一次提交里写。

## 不做的（理由）

- **不做 `level` 分级**（WARNING → ERROR → HIDDEN）。Dawn 删名字就是删，没有「还能用但警告」的中间态；
  一条提示到期即删，一个字段就够。
- **不给 `Cx` 加字段**。模块限定条目用 `std/<m>.old` 作键进现有的 `cx.moved`；`Cx` 的每个新字段都要做
  Frame 分诊（#204），为一张只读的小表不值得。
- **不修私有 std 函数的「add `pub` to its declaration in std/…」**。`fmt.atoi` 这类名字在 std 里仍存在、
  只是不再 pub，删掉 v0.55.0 那条后它会落到这个分支。这句建议对任何私有 std 函数都一直存在，
  与本表无关，另行处理。（2026-10-01 已由 #296 处理：std 的私有名报
  `` `atoi` is not part of std's public API (`std/fmt` declares it privately) ``，无 hint，
  本表有条目时以条目为 hint；限定调用与选择性引入共用 `cx.dawn` 的 `private_name_diagnostic`，
  `moved_module_key` 随之从 checker 挪进 `cx.dawn`。std 模块之间仍给「加 `pub`」，那里它就是修法。）
- **不把门并进 `api-diff.py`**，理由见 §3。
- **不对 `types`、`consts`、`traits` 等其它 pub 种类设门**。issue 与裁决只要求函数；提示路径
  （`check_module_call`、`moved_or_suggest`）也只服务函数调用。
