# 身份路径解析 symlink：`fs_real_path` 与三步桥

> 状态：**current**。2026-10-01，issue #207 刀 2 的第一步 R1（分支 `feat/std-memfs`），顺带 #297。
> 调研与裁决见 `research-207-symlink-20261001`（agent-handoff，未入库）与 #207 上 10-01 的裁决评论；
> 本文先只写 R1，R2、R3 在各自批次补节。

## 问题

`compiler-plan/src/source.dawn` 的 `canon` 是纯词法归一：先拼绝对路径再按文本折叠 `.` 与 `..`，
不问文件系统。经 symlink 进入项目时它会给出错误的身份，调研在 main `9d951982` 上复现了四类：

| 场景 | 结果 |
|---|---|
| 菱形依赖，一条边经链接到同一个包 | 假错误 `package lib is linked from two different directories`，构建中断 |
| 经链接路径进入项目，且有 `../lib` 形式的路径依赖 | `cannot find module lib/util`，整个项目加载失败（CLI 与 LSP 都是） |
| `--std` 经链接 | std 文件被当成用户代码，7 条假错误 |
| LSP 同一文件经链接与实路径各打开一次 | 两个 workspace，静默分裂，重复冲突诊断不触发 |

第二行的机制与 Go #23444 相同：`/h/app` 是链接，`/h/app/../lib` 词法折成 `/h/lib`，
而内核按物理父目录解析出的是另一个目录。

裁决（#207 评论）：`Fs` 新增 `fs_real_path(path) -> Result[String, ForeignError]`，realpath 语义，
路径须存在、须为绝对路径；身份函数 `canon_identity(p)` 取「绝对但未做词法归一的路径」的 realpath，
失败时退回 `canon(p)`。本文不重复 API 形状的理由（调研 §2），只记落地顺序为什么是三步，以及每一步做了什么。

## 为什么不能一个 release 做完

**handler 的臂集必须恰好等于效果声明的 op 集。** `check/checker.dawn` 对 `with handle` 的规则是
「one arm per declared operation: no fewer, no more」。调研的探针在 `examples/effects/files.dawn`
的 handler 里多写一臂，诊断是：

```
error: `fs_real_path` is not an operation of effect `Fs`
```

少写一臂同样红（本批负控，见下文「验证」）。

**selfhost 自己持有一个完整的 `Fs` handler。** `selfhost/src/driver/fsmem.dawn` 的 `with_fs_mem`
是内存表 handler，编译器全部 analyze/LSP 测试都跑在它上面。自举时这份源码被编译两次
（[bootstrap.md](bootstrap.md) 特性纪律 4、`scripts/build-release-jar.sh`）：stage A 用种子**自带的 std**，
之后的 stage 用 HEAD 的 std。给 `Fs` 加一个 op，HEAD std 有 15 个、种子 std 有 14 个，
同一份 `with handle Fs` 不可能同时对上两边。所以只要 selfhost 里写着 `with handle Fs`，`Fs`
就一个 op 都加不了，哪怕新 op 只是 std 的事。

**出路是把 handler 挪进 std。** std 永远只和同版本的编译器一起编（`std/VERSION` 必须等于
`VERSION`），std 里的 handler 与 std 里的 `Fs` 声明总在同一侧。selfhost 改成调用 std 的 handler 之后，
自己不再拼臂集，op 集就不再被 selfhost 冻住。但 selfhost 只能调用种子已有的 std 函数，于是：

| 步 | 内容 | 发版 |
|---|---|---|
| **R1** | 新 std 模块 `std/memfs`：fsmem 的表与 14 臂 handler 原样搬过去；selfhost 不动，只加对账 | 发版，推种子 |
| **R2** | fsmem 改成 `memfs.with_fs` 的薄包装（`mem_std` 留在 selfhost）；同一版给 `Fs` 加 `fs_real_path`、`io_real_path` intrinsic、`std/memfs` 的链接模拟 | 发版，推种子 |
| **R3** | compiler-plan 加 `canon_identity`，改身份点，LSP 合约加 symlink 会话 | 正常合入 |

附带收益：R2 之后 `Fs` 的 op 集不再被 selfhost 冻结，将来加 `fs_stat`、`fs_append` 之类不必再走这一轮桥。

不选「另开一个具名效果（如 `FsLink`）」来绕桥：身份链上每个签名永久多一个原子，
每个程序多一个效果证据类，一个文件系统查询永远住在 `Fs` 外面（调研 §2 末项）。桥只付一次。

## R1：`std/memfs`

### 搬了什么

从 `selfhost/src/driver/fsmem.dawn` 原样搬：

- `MemFs` 记录（`base`、`files: Map[String, Bytes]`、`dirs: Map[String, Bool]`、`seq`）；
- 全部私有函数：`ferr`、`key`、`with_ancestors`、`dir_prefix`、`is_dir_key`、`child_names`、
  `mem_read`、`mem_list`、`mem_mkdirs`、`mem_write`、`mem_delete`、`mem_rename`、`mem_temp`、`mem_present`；
- 14 臂 handler，逐臂同文。

公开面按 std 惯例改名（模块名本身就是限定）：

| fsmem | std/memfs |
|---|---|
| `MEM_BASE` | `memfs.BASE` |
| `mem_empty(base)` | `memfs.empty(base)` |
| `mem_put(st, path, content)` | `memfs.put(st, path, contents)` |
| `mem_content(st, path)` | `memfs.text(st, path)` |
| `mem_files(st)` | `memfs.file_paths(st)` |
| `with_fs_mem(seed, body)` | `memfs.with_fs(seed, body)` |

不搬 `mem_std` / `mem_std_dir`：它们读 `embed/stdsrc`（编译器内嵌的 std 文本），是编译器的事。

### 与 fsmem 不同的四处，各有理由

1. **路径函数是私有副本。** fsmem 用 `fspath` 包的 `absolute` / `parent`；std 不能依赖包，
   而把路径函数放回 std 让每个程序都背着，正是审计 RD-09 撤掉的。memfs 私有地带三个函数
   （`path_normalize`、`path_absolute`、`path_parent`），逐字照 `fspath` 的 `normalize`/`absolute`/`parent`。
2. **`sort` 写成 `list.sort`。** 用户代码里的裸 `sort` 是 prelude 转到 std/list 的同一个函数，std 内部要限定着写。
3. **`with_fs` 的 body 行是 `!e`，不是 fsmem 的 `!Fs !io`。** std 的每个 handler 包装
   （`with_fs_real`、`with_proc_real`、`compiler-plan` 的 `with_env_table`/`with_console_table`）都是 `!e`，
   理由写在 `std/io.dawn` 的 `Proc` 段：闭合行只能当最外层。R2 里 fsmem 以 `e := io` 调它，签名不变。
4. **效果写成限定名 `io.Fs`，不 `use std/io.{Fs}`。** 这不是风格。std 里一旦有模块按名导入效果，
   std 自身的加载就走检查器的「导入效果」路径；`scripts/incremental-semantics-contract/identity.py`
   的 `mint-imported-effect` 变异体正是改坏这条路径的负控，它要求红在自己的断言上。先按选择性导入写，
   实测该负控把 std 本身改坏：26 条 analyze 测试以 `unknown adt id` 失败、到不了它的断言，harness 判红。
   限定名绕开这条路径，还让 14 个 `fs_*` 操作不进 memfs 自己的命名空间。

语义不变：表语义，目录由路径隐含，不跟随链接（`fs_is_symlink` 恒 `false`），相对路径按构造时给的
base 解析，文件存字节，只有文本臂做 UTF-8 编解码，错误的 `kind` 都以 `memfs.` 开头。

### 对账：R2 之前两份不许漂

R1 到 R2 之间同一个 handler 有两份文本。检查器只保证各自的臂集等于**各自编译时那份 std** 的 `Fs`，
不比较臂体与辅助函数。所以 `scripts/doc-check.py` 加 `check_memfs_twin`：

- `std/io.dawn` 的 `pub effect Fs` 的 op 列表，与两个 `with handle Fs` 块的臂名列表，三者逐项相等（含次序）；
- 两个 `with handle Fs` 块逐字相等；`MemFs` 记录逐字相等；
- fsmem 测试段以上的每个私有函数，在 `std/memfs` 里有同名且逐字相同的定义；
- 允许的差异只有 `MEMFS_SPELLINGS` 四条（上文第 1、2、4 条），每条带理由；某条在 fsmem 里不再出现也红，豁免不能比需要活得久。

它有自测（`check_memfs_twin_selftest`）：删 std 侧一臂、给 `Fs` 加一个 op、只改 fsmem 的一个辅助函数、
只改 std 侧一条臂体，四种都必须红，未改的原样必须绿。R2 删掉 fsmem 的副本时，这个检查随之删除。

### 自举纪律

selfhost **本批不调用 `std/memfs`**。种子 v0.79.0 的 std 没有这个模块，stage A 用种子 std 编 selfhost，
`use std/memfs` 会是 `no bundled std module`。std 自己的内联测试（`dawn test --stdlib`）覆盖 14 个 op；
`std/modules.txt` 登记在末尾（依赖 str/list/map/bytes/io，std 里没有谁用它）；
`embed/stdsrc.dawn` 重生成；新模块不声明效果，`NAMED_EFFECT_EXPECTED` 不变。

可见的输出变化：`no bundled std module` 的提示列出全部内嵌模块，多了 `std/memfs`
（`scripts/checker-corpus/cases/imports.expected` 一行）；`dawn doc --stdlib` 多一个模块。

## R2（待补）

fsmem 换用 `memfs.with_fs`；`Fs` 加 `fs_real_path`；两后端 intrinsic；`std/memfs` 的链接模型
（`links` 表、逐分量解析、跳数上限 40）。

## R3（待补）

`canon_identity` 的形状与身份点清单（调研 §3）。

## 附：#297 源码遍历不跟随目录链接

同一次调研发现的独立缺陷：`driver/analyze.dawn` 的 `walk_dawn` 对每个目录项先问 `is_dir`，
而 `is_dir` 跟随链接，所以 `src/loop -> .` 会被一层层走下去。实测一个自环 2.5 s、417 MB
（直到内核的链接层数上限才停，同一模块在每一层各列一次），两个自环 60 s 不结束。

改法：目录项若是指向目录的链接，作为条目访问但不下钻。这是 Go `filepath.WalkDir` 与 Rust `walkdir`
的默认，也是本仓 `pkgfetch.delete_tree` 已有的规则（「a symbolic link is removed rather than followed」）。
只经链接才可达的目录不属于项目；确实想要的外部目录写成路径依赖，由解析器显式处理。指向文件的链接照旧算文件，它不会成环。
不需要新 op，`fs_is_symlink` 本来就有；只对是目录的项多问一次 `is_symlink`。

测试在真磁盘上（fsmem 的 `fs_is_symlink` 恒 `false`，本批也不给它加链接）：临时目录里用 `ln -s`
造 `src/loop -> .`、`src/ext -> ../../outside`、`src/alias.dawn -> sub/util.dawn`，断言 `walk_dawn`
恰好列出三个文件、`project_plan` 的模块索引恰好是 `alias`、`main`、`sub/util`。

## 验证

命令输出贴在本批报告里；这里只记结论与负控的形状。

- `dawn test --stdlib`：`std/memfs` 11 条测试，14 个 op 都有断言。
- 负控 1：删 `std/memfs` 的 `fs_list_names` 臂，编译期报臂集不符。
- 负控 2：`walk_dawn` 恢复跟随链接，#297 的测试红（模块重复列出）；CLI 上同一 fixture 用 `timeout` 包着跑。
- `check_memfs_twin` 与其自测。

## 不做的（理由）

- **R1 不给 `Fs` 加 op。** 加了 stage A 就红，这正是三步的来由。
- **R1 不改 `canon`。** 它保持纯词法 `!Env`；身份语义是 R3 的 `canon_identity`，而且 bootstrap 输入清单那几处必须不解析链接（调研「不做的」第 1 条）。
- **R1 不给 memfs 加链接。** `links` 表与 `fs_real_path` 臂是 R2 的事，和 op 同一版进，才能在 std 里一次测全。
- **selfhost 不调 `std/memfs`。** 种子里没有，要等下个种子（R2）。
- **不把 `fspath` 放回 std。** 见上文「与 fsmem 不同的四处」第 1 条。
- **#297 不改其它遍历。** `stdlib` 的 std 目录只按 `modules.txt` 读，不遍历；`dawn fmt` 的目录模式
  （`main.dawn` 与 `nmain.dawn` 各一份 `dawn_files_under`）有同样的跟随，但它不是项目加载、不进 LSP，
  #297 的验收也没点它；本批不扩范围，交给后续 issue。
