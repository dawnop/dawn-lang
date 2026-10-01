# 身份路径解析 symlink：`fs_real_path` 与三步桥

> 状态：**current**。2026-10-01，issue #207 刀 2：R1（分支 `feat/std-memfs`，顺带 #297）、
> R2（分支 `feat/fs-real-path`）与 R3（分支 `fix/canon-identity`，种子 v0.81.0 之后）都已写。
> 调研与裁决见 `research-207-symlink-20261001`（agent-handoff，未入库）与 #207 上 10-01 的裁决评论。

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

### 对账：R2 之前两份不许漂（R2 已随副本一起删除）

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

## R2：换用 `std/memfs`、`fs_real_path`、`io_real_path` 与链接模型

种子 v0.80.0 的 std 带着 `std/memfs`，selfhost 从这一版起可以调用它。四个提交，顺序与裁决略有出入，见下文「提交顺序」。

### 换用，以及对账退役

`driver/fsmem` 只剩 `mem_std` 与 `mem_std_dir`：它们读编译器内嵌的 std（`embed/stdsrc`），是编译器自己的事。
表、handler 与测试辅助一律直接用 `std/memfs`：`memfs.with_fs`、`memfs.empty`、`memfs.put`、`memfs.text`、
`memfs.file_paths`、`memfs.BASE`、`memfs.MemFs`，调用点在 `driver/analyze`、`driver/stdlib`、`driver/clifail`、
`contract/module_memo`、`lsp/server` 的测试段。

**不留旧名的转发函数。** R1 设计时写的是「fsmem 改成 `memfs.with_fs` 的薄包装」；落地时没有包，因为
`fsmem.mem_put` 与 `memfs.put` 两个名字指一张表，正是这一步要消掉的那种孪生，只是从文本孪生换成了名字孪生。
改调用点是机械替换（约 40 处），一次付清。

selfhost 里从此**没有任何 `with handle Fs`**（`grep -rn "with handle" selfhost/src` 不含 `Fs`）。
`scripts/doc-check.py` 的 `check_memfs_twin` 与它的自测随之删除：只剩一份，没有东西可比，留一个空规则只会让人以为它还在守什么。
fsmem 原有的三条 handler 测试随 handler 一起走，`std/memfs` 自己的测试覆盖每一臂。

### `Fs.fs_real_path` 与 `io.real_path`

`Fs` 的第十五个 op 放在声明末尾：`fn fs_real_path(path: String) -> Result[String, ForeignError]`。
std 的公开面是 `io.real_path(path) -> Result[String, ForeignError] !Fs`：

- 先查绝对路径，判据是 `str.starts_with(path, "/")`，与 `fspath.is_absolute` 同一条（std 不能依赖包，见 R1 第 1 条）。
  不是绝对路径就回 `Err(kind: "io.relative_path")`，**不进 handler**，与 `list_dir`、`run` 的先例同形；
  `io.relative_path` 成为 std 自己铸的第四个 kind（spec 的 IO 小节已同步，中英两版）。
- 拒绝而不是替调用者绝对化：绝对化要读工作目录，那是 `Env` 的应答。R3 的 `canon_identity` 自己拿 `io.cwd()`，`!Env` 记在它那里。
- 仓内全部 `with handle Fs` 补臂，共五处：`std/io` 的 `with_fs_real`（调原语）与它测试里的表 handler、
  `std/memfs`、`examples/effects/files.dawn`（表里没有链接，存在的路径就是它自己的解析结果）、
  `scripts/spike-native/effect_fs_seam.dawn`。
- `std/io` 头注释里「fourteen operations and not fifteen」与 `docs/effects-design.md` 的「十四个操作」改成十五。

### 原语 `io_real_path`

| 处 | 内容 |
|---|---|
| `check/types.dawn` | `eff1(bsig("io_real_path", [TyString], ["path"], TyString), EIo)`，进 `io_in_rt`（同时决定归 `RtIo` 与 std-only） |
| `ir/interp.dawn` | comptime 拒绝名单加 `real_path` |
| `selfhost/builtins.dawn` | 镜像行 `fn io_real_path(path: String) -> String !io # comptime: rejected` |
| 计数测试 | `types` 的表大小 111→112、`lower` 的分组总数 111→112、`interp` 的拒绝数 68→69 |
| JVM `rtclasses.dawn` | `new File(path).toPath().toRealPath(new LinkOption[0]).toString()`，约 10 行 ASM；NUL 在 `toPath` 抛 `InvalidPathException` |
| C `dawn_rt.c` / `.h` | `dawn_reject_nul` → `realpath(p, NULL)` → `dawn_str_from_os` → `free`；失败 `dawn_fault("io_real_path: cannot resolve the path")`；`embed/rtsrc.dawn` 重生成 |

调研写的「comptime 拒绝名单三处（types、interp、`driver/stdlib.dawn:161`）」在本基线只有两处：
`stdlib.dawn` 里没有这张表，io 原语的全部名单就是 `types.dawn` 的 `io_in_rt` 与 interp 的拒绝表。

**wasm32-wasi。** 调研以为 wasi-libc 带着 musl 的 `realpath`、只是多层 preopen 下会失败。实测不是：
wasi-libc 的 `stdlib.h` 把 `realpath` 包在 `__wasilibc_unmodified_upstream` 里，注释是「WASI has no absolute paths」，
第一版实现在 `scripts/wasm-contract/run.sh` 里编不过（implicit declaration）。所以 `__wasi__` 下这个原语**一律 fault**，
调用者拿到的是与「解析不了的路径」同一种 `Err`；退路是调用者的策略（R3 的 `canon_identity` 退回 `canon`）。不在 wasi 上模拟 realpath。

Windows 不在范围（两个后端的目标平台都没有它）。

两后端对同一棵真实目录树（`home/app -> ../work/app`、自环 `loop -> self`）逐例对拍，结果除 `Err` 的 `kind`
（`kind` 本来就是后端给的：JVM 是异常类名，native 是 `fault`）外逐字相同，见本批报告。
std 的宿主测试也用 `io.run(["ln", "-s", ...])` 造真链接，`native-cli-diff.sh` 的 `test (the bundled std)` 一对
让同一组断言在两个后端各跑一遍。

### `std/memfs` 的链接模型

- `MemFs` 加 `links: Map[String, String]`（链接的绝对路径 → 原样目标）；构造函数 `memfs.link(st, at, target)`，
  `at` 的祖先目录随之记入；`at` 上已有文件或目录则原样返回，与 `put` 遇到目录时同一规则。目标不要求存在（`ln -s` 也不要求）。
- `fs_is_symlink` 答 `map.has(links, key)`。
- `fs_real_path` 逐分量走，同内核的走法：遇到链接，目标替换该分量（绝对目标从根重来，相对目标接着从链接所在目录走）；
  `..` 退到「已走到的目录」的父目录，所以链接之后的 `..` 退出的是目标而不是链接所在目录（场景 B 的根）；
  中间分量必须是目录（文件后面还有分量是 `memfs.not_a_directory`），每个分量必须存在（`memfs.not_found`），
  悬空链接也是 `memfs.not_found`；跳数上限 40（Linux 的 `ELOOP`），超了是 `memfs.loop`。
- **其它臂不跟随链接，也看不见链接**：`fs_exists`、`fs_read_file`、`fs_list_names` 只认文件与目录表。
  这是有意的窄：身份解析只需要 `fs_real_path`，让每一臂都跟随链接等于再维护一套与内核对齐的文件系统语义。
  #297 的遍历测试因此仍在真磁盘上（遍历要求链接作为目录项列出）。

测试四条：链接只被 `is_symlink` 与 `real_path` 看见；链接后的 `..` 按物理父目录退，而词法折叠出的 `/home/lib` 是 `memfs.not_found`；
自环、互环是 `memfs.loop`，恰好 40 跳的链能解析、41 跳是 `memfs.loop`；缺分量、文件当目录、悬空链接各是 `Err`。

### 输出变化

加一个效果 op 是**签名原子的变化**，不是行为变化，但它挪动字节：`std/io` 的 handler 臂 lambda 类重新编号、
`std/memfs$MemFs` 多一个字段、`dawn/rt/Io` 多一个方法。十个 emit 语料全部 MOVED，`doc --builtins` 多一条；
提交信息逐 label 写了 `Emit-Change`。fmt、lsp 差分零差。

### 提交顺序

裁决给的顺序是「切换 → op + 补臂 + 链接模型 → 原语 → 文档」。落地把原语提到 op 之前：
op 一加，`with_fs_real` 就得有一臂，原语不在的话这一臂只能是一个答错的占位（例如恒 `Err`），
而裁决要求每个提交都能过两个 fixpoint 与测试，占位能过却不该进历史。原语先进来没有调用者，本身不改任何行为。

### 验证（命令输出在本批报告）

- 负控 4（桥是必要条件）：fsmem 里重新写一个 14 臂的 `with handle Fs`，`selfhost-fixpoint.sh` 在 stage B 红
  （`handler for Fs does not answer fs_real_path`，stage A 用种子 std 编过）；写成 15 臂，stage A 就红
  （`fs_real_path is not an operation of effect Fs`）。两头都堵死，selfhost 里不能再有 `Fs` handler。
- 负控 5：`MAX_LINK_HOPS` 改成 `Int` 最大值、重生成内嵌 std，`timeout 180 dawn test --stdlib` 到点（exit 124），
  卡在环测试上。
- 负控 6：删掉 `real_path` 的相对路径检查，std 测试两条红（宿主测试与表 handler 测试都断言 `io.relative_path`）。

## R3：`canon_identity` 与身份点

种子 v0.81.0 的 std 带着 `io.real_path`，compiler-plan 从这一版起可以调用它。

### 形状

`compiler-plan/src/source.dawn`，紧挨 `canon`：

```dawn
pub fn canon_identity(p: String) -> String !Fs !Env = {
  let abs = if fspath.is_absolute(p) { p } else { io.cwd() ++ "/" ++ p }
  match io.real_path(abs) {
    Ok(resolved) -> resolved
    Err(_) -> canon(abs)
  }
}
```

- 交给宿主的是**绝对但未做词法归一**的路径。`home/app -> ../work/app` 时 `home/app/../lib`
  是 `work/lib`；先词法折叠成 `home/lib` 再问宿主，宿主答不存在，退路又交回这个错的目录，
  场景 B 原样不修。所以次序就是要点，有一条内联测试与一个负控专门守它（下文）。
- 解析不了（路径不存在、wasi 上原语一律失败）就退回 `canon(abs)`：词法拼写。退路用已经拼好的
  绝对路径，相对路径因此只问一次工作目录（内联测试断言了 `Env` 日志）。
- `canon` 本身不动，仍是纯词法 `!Env`。它的注释改成「路径**写的**是什么」，`canon_identity`
  是「路径**是**什么」。

### 身份点（改成 `canon_identity`）

| 处 | 作用 |
|---|---|
| `source.dawn` `mf_get` 的缓存键 | 同一目录的两个拼写只读一次 manifest |
| `source.dawn` `select_url_deps` 的 `seen` | url 依赖遍历的目录去重 |
| `source.dawn` `resolve_src_deps` 的 `dcanon` | 包缓存与「一名一份」占用键（场景 A 的出处） |
| `source.dawn` `PkgR.root` | 包源根（场景 B 的出处） |
| `analyze.dawn` `entry_file`、`resolve` 的模块键与 overlay 键、`analyze_document_planned` | 入口匹配、模块去重、活文本匹配 |
| `stdlib.dawn` `dir_modules` 的键、`dir`、`std_module_of`、`is_std_dir` | std 来源判定（场景 C） |
| `server.dawn` `workspace_identity`、`Doc.canonical_path`、`add_loc_diag`、`standalone_diagnostics`、`location_of` | workspace 查表、重复冲突、诊断与跳转的比较（E1/E2） |
| `server.dawn` `manifest_path_of`、`slot_manifest_dirs` | 监视的 manifest 目录与通知里的路径两边同一个函数 |

保持词法 `canon` 的：bootstrap source-input manifest（封闭输入契约，`source_input_path_ok` 本就拒绝经过链接的路径）、
`nearest_src_root`（项目根保留用户的拼写）、`index_files`（补全索引是显示用途）、
`resolve_src_deps` 里给消费方看的两条诊断（「has no src/ folder」「has no dawn.toml」仍写消费方写的目录）。

### 与调研和裁决不同的五处，各有理由

1. **依赖目录解析一次，之后按解析后的拼写读。** 裁决只改 `dcanon` 与 `PkgR.root` 两个键；落地让
   `resolve_src_deps` 从 `dcanon` 起读 manifest、`src/` 并递归。宿主上这只改「读哪个名字」不改「读到什么」
   （内核对两个拼写答同一个目录）；但 `std/memfs` 的读臂不跟随链接，不这样做内存测试根本走不到身份那一步。
   这也是 cargo 维护者在 #17204 说的「在入口归一一次，内部假定干净」。副作用：依赖包自己的 manifest 诊断
   路径从 `app/../lib/dawn.toml` 这类拼写变成 `lib/dawn.toml`。
2. **模块路径保持词法，loader 的模块键是（文件身份，模块路径）二元组。** 只按文件身份去重，
   会让 `src/ali -> sub` 下的 `use ali/x` 被折进 `sub/x`、别名 `ali/x` 不再装载：实测
   `undefined variable or module alias: y`，而种子 v0.81.0 打印 `14`。这是 spec §10 的语义（模块身份是模块路径，
   调研 D 场景已裁不改），身份解析不能顺手改掉它。所以模块路径由 `module_path_at` 先按词法求，
   只在文件拼写根本不在根的拼写之下时（编辑器经另一个拼写打开同一个根里的文件）才按两边的身份求；
   包内模块路径同样按词法（包根已是身份）。负控：键里去掉模块路径，#297 链接树上的新测试红（`queued module`）。
3. **`project_module_path` 也走 `module_path_at`。** 调研把它列为保持词法；但 workspace 成员的路径
   （`Doc.canonical_path`）现在是身份，而 plan 的根是第一个成员打开时的拼写，两边拼写不同时纯词法
   会退化成文件名。它因此多了 `!Fs`；lsp-workspace 合约 `extensionless-project-member` mutant 的替换体同步改写。
4. **manifest 刷新的 key 守卫不再 panic。** `refresh_workspace` 原来断言重新规划后 key 不变（key 只是
   target 路径的算术）。身份解析链接之后，服务运行期间链接被改指或根被删，key 就会变；成员文档按旧 key 登记，
   所以 slot 留在旧 key 下，不迁移，之后新打开的文档拿新答案。lsp-workspace-design §3.2 同步改写。
5. **manifest 通知按目录身份匹配。** 监视集里的包根已是身份，通知里的路径若仍按词法，两边永远对不上。
   解析的是目录不是文件，所以删掉的 `dawn.toml` 仍能指认它所在的目录。

### 效果行

`std_module_of` 与 `is_std_dir` 要问宿主，于是 `analyze_program`、`analyze_observed`、`analyze_module_step`、
`analyze_standalone`、`incremental.analyze` 与 LSP 一侧的十来个函数加了 `!Fs`。调用者全都已持有 `Fs`
（`main`、`nmain` 的命令函数、合约与测试的 memfs 包装），没有一处需要新装 handler。
一次 load 里每个依赖拼写只解析一次（`resolve` 的局部表），不是每条 `use` 边一次。

### 可见的输出变化

- 依赖包（经链接到达时）的诊断路径、LSP 对**未打开文件**的跳转 URI 与诊断 URI 变成物理路径。
  这与 Node 的模块缓存键、TypeScript 的默认 realpath 同款（调研 §6），TypeScript 用户抱怨「跳进
  `node_modules/.pnpm` 的真实路径」，`preserveSymlinks` 就是为此设的；本仓不设这个开关。
- 已打开的文件经 `path_by_uri` 回到编辑器打开时的 URI，不受影响。
- 依赖包自己 manifest 的诊断路径不再带 `../`（上文第 1 条）。
- 仓内差分语料不含链接，四个差分与 `native-cli-diff` 的结果见本批报告。

### 测试与负控（命令输出在本批报告）

- compiler-plan 内联测试三条：菱形依赖一边走链接是一个包（A）、链接后的 `..` 退到目标的父目录（B）、
  `canon_identity` 对存在与不存在路径的逐例答案（含相对路径只问一次工作目录）。
- analyze 内联测试四条：项目经链接进入时 `../lib` 依赖可装载、编辑器经链接打开的 buffer 是项目入口（B、B-LSP）；
  std 经链接目录在两种拼写下都是 std（C）；`src/` 内的文件链接仍是两个模块（第 2 条）。
- lsp-workspace 合约新 case `symlink-identity`（真磁盘链接，Python `os.symlink`）：main 经链接、库经实路径打开，
  main 看到库的活文本、跳转落到库的实 URI（E1）；再经链接以不同文本打开库，两个 URI 都收到重复冲突诊断（E2）。
  mutant `lexical-identity` 把 `canon_identity` 改回 `canon`，红在 `SYMLINK_IDENTITY_SPLIT`。
- 负控：形状变异（交给宿主前先 `canon`）红在 B 的两条测试与 `canon_identity` 的逐例测试；撤回 `dcanon`
  红在 A 与 B；`std_module_of` 改回词法红在 C；模块键去掉模块路径红在第 2 条的测试。

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

R3：

- **不改 `canon`，不改 bootstrap 输入清单、`nearest_src_root`、`index_files`。** 见上文「身份点」末段。
- **不做 case-fold。** 调研「不做的」同一条：两个后端的目标平台都区分大小写，`realpath` 在 macOS 上也不折叠大小写。
- **不对不存在的路径做部分解析（soft canonicalize）。** 只存在于编辑器里的新文件经链接打开时，它的身份退回词法拼写，
  与实路径那一侧不合并；模块路径由 `module_path_at` 按与根相同的拼写求，仍然正确。真要合并，得解析「最长的存在前缀」，
  那是 Rust 社区 `soft_canonicalize` 的做法，等有人碰到再做。
- **不加 `preserveSymlinks` 式的开关。** 依赖与未打开文件显示物理路径是身份解析的代价，Node 与 TypeScript 的开关
  都是为了绕开工具链对链接布局的假设；本仓没有这样的布局需求。
- **不迁移 workspace。** 链接在服务运行中被改指时成员留在旧 key 下（上文第 4 条），重开文档即得新答案；
  自动迁移要定义成员按什么顺序换 key、诊断怎么清，不值得为这个罕见事件写。

R2：

- **不做 `canon_identity`，不改身份点。** 那是 R3，要等 v0.81.0 种子带着 `io.real_path` 才能在 compiler-plan 里调用。
- **不改 `canon`，不加 `fs_read_link`，op 里不做 soft 语义，不做 case-fold。** 理由同调研 §2 与下文 R1 各条。
- **memfs 的其它臂不跟随链接。** 见上文「链接模型」；真要模拟完整的链接语义，等有测试需要它的时候。
- **wasi 上不模拟 realpath。** wasi-libc 明说没有绝对路径；在 preopen 之上自己拼一套，是在替运行时发明语义。
- **不给 fsmem 的旧名留转发函数。** 见上文「换用」。

R1：

- **R1 不给 `Fs` 加 op。** 加了 stage A 就红，这正是三步的来由。
- **R1 不改 `canon`。** 它保持纯词法 `!Env`；身份语义是 R3 的 `canon_identity`，而且 bootstrap 输入清单那几处必须不解析链接（调研「不做的」第 1 条）。
- **R1 不给 memfs 加链接。** `links` 表与 `fs_real_path` 臂是 R2 的事，和 op 同一版进，才能在 std 里一次测全。
- **selfhost 不调 `std/memfs`。** 种子里没有，要等下个种子（R2）。
- **不把 `fspath` 放回 std。** 见上文「与 fsmem 不同的四处」第 1 条。
- **#297 不改其它遍历。** `stdlib` 的 std 目录只按 `modules.txt` 读，不遍历；`dawn fmt` 的目录模式
  （`main.dawn` 与 `nmain.dawn` 各一份 `dawn_files_under`）有同样的跟随，但它不是项目加载、不进 LSP，
  #297 的验收也没点它；本批不扩范围，交给后续 issue。（2026-10-01 由 #302 收掉：两个驱动删掉各自的副本，
  改用 `driver/analyze.dawn` 的 `pub fn dawn_files_under`，它与 `walk_dawn` 共用一个遍历 `walk_sources`；
  唯一的差别是列不出的目录，加载器跳过，格式化器报 `cannot list` 停下，以免 `fmt --check` 漏查一片还判绿。）
