# manifest/lock 原子写：宿主能力与 `io.atomic_write_file`

> 状态：**已落地（两刀齐）**。第一刀是宿主能力与 `io.atomic_write_file`
> 本体；第二刀是调用点迁移，被种子纪律推迟了一个 release，随 v0.63.0 的
> 种子推进解锁后完成。本文记录 TOOL-13 裁决落到代码的形态，末节保留那次
> 推迟的理由——它不是估算失误，是这套自举的机器约束。

## 问题

`selfhost/src/pkg/add.dawn:186` 与 `selfhost/src/main.dawn:1049` 直接覆盖
`dawn.toml` / `dawn.lock`：

```dawn
match io.write_file(mf_path, rendered) { ... }        # pkg/add.dawn
match io.write_file(path, maven.render_lock(fresh)) { ... }   # main.dawn
```

`io.write_file` 是 open + truncate + write。中途失败（磁盘满、进程被杀、
写到一半）留下的是**截断过的 manifest**——不是旧的，也不是新的。对一个
「工程根目录里唯一说明这个包是什么」的文件，这是最糟的一种失败：下一次
`dawn build` 读到的是一份语法都不完整的 toml。

## 裁决（2026-08-10，codex-log）

三个选项里选 **C**：共享的 same-directory atomic-file primitive——独占创建
随机 sibling temp、完整写入并 read-back 验证、保留既有目标的可移植权限、
再以单次 atomic replace 安装；任何步骤失败都清理 temp 且保持原目标不变。
**禁止** B 的 direct-write / delete-then-rename fallback。

裁决同时划死了边界，这些边界在实现里逐条对得上：

| 裁决条款 | 落点 |
|---|---|
| 目标是 symlink 则 fail closed | `atomic_write_file` 的第三个 pre-flight，`io.atomic_write_target_is_symlink` |
| hardlink = detach，不伪装保留 link identity | rename 换目录项；契约脚本 `hardlink other = old` 钉住 |
| POSIX 保留 mode bits | `io_copy_permissions` 走 `getPosixFilePermissions` / `lstat`+`chmod` |
| Windows 至少保留 readonly | JVM 侧 `UnsupportedOperationException` 的 catch 臂走 `File.setWritable` |
| ACL/xattr 不承诺 | 两个后端都只搬 mode bits，doc 注释写明 |
| 新文件权限由安全创建模式 + umask 决定 | `mkstemp` / `createTempFile` 给 0600；契约脚本断言新建文件是 600 |
| 不承诺断电持久性、不加 fsync | 无 `fsync`；std 文档注释里单列一条 |
| 不做 CAS/事务，并发最后一次 replace 获胜 | 无版本号、无锁；文档注释单列一条 |

## 实现前置：四项宿主能力

裁决点名「现有 `std/io.rename` 单独不够」，要先有四项能力且**两个后端行为
合同一致**。盘下来只缺两项，另两项已经在：

| 能力 | 已有 / 新增 |
|---|---|
| atomic replace | **已有** `io_rename`：JVM 是 `Files.move(..., ATOMIC_MOVE)`，native 是 `rename(2)`。两边都是「同一文件系统上原子，否则失败」，没有更弱的降级 |
| no-follow destination inspection | **已有** `io_is_symlink`：JVM `Files.isSymbolicLink`，native `lstat` + `S_ISLNK` |
| exclusive sibling create | **新增** `io_temp_file(parent, prefix)` |
| portable permission copy | **新增** `io_copy_permissions(src, dst)` |

### `io_temp_file`

`io_temp_dir` 的文件版，连「空 parent 表示系统临时目录」的形状都照抄，
以免同一件事有两种调用惯例。

要点是**名字与创建是同一个调用**：`mkstemp(3)` 与 `Files.createTempFile`
都由宿主挑名字并当场创建。自己拼一个名字再 open 会留下两者之间的窗口，
而那个窗口正是 manifest 所在目录（不一定私有）里的 symlink 攻击面。
两个后端都给 0600。

### `io_copy_permissions`

存在的理由只有一句：**rename 发布出去的是一个新文件**，它的 mode 来自
创建它的那个调用与 umask，没有任何东西记得它替换掉的是什么。

`src` 一侧不跟随链接（`lstat` / `NOFOLLOW_LINKS`）：跟随等于让被替换的
那个对象决定「用谁的权限发布」。

JVM 侧的 catch 臂是 Windows 那条裁决的落点，也是本刀唯一一段
**在 POSIX 上跑不到**的代码。写它而不是让它 fault，理由是两种错的代价
不对称：fault 变成「发布不了」，而 `File` 的三个 boolean 表达不了 group /
other 位，拿它当首选会在有这些位的宿主上**静静丢掉** mode bits。所以它是
fallback 而不是实现。契约脚本证明不了它——这一点写在代码注释里，不假装。

### 为什么不是「一个 intrinsic 干完整件事」

先考虑过把整套动作放进运行时（一个 `io_atomic_write_file`）。否掉的理由是
两条：

1. **算法会有两份。** 一份手写 ASM（`rtclasses.dawn`）、一份 C。两个后端
   行为一致就得靠对拍，而不是靠「只有一份定义」。
2. **步骤会失去缝。** 裁决要求 create/write/close/read-back/permission/
   replace **每一步**都能注入失败。写成 Dawn 之后，前五步各自是一次
   `std/io` 调用，注入就是改一行源码；写进运行时之后，它们是一个函数里的
   连续几行 C，JVM 那边还是 ASM。

现在的形态是：**能力在运行时，算法在 std**。新增的 ASM 是两段直白的静态
方法，算法是 40 行 Dawn，两个后端共用同一份。

## `io.atomic_write_file`

```
pre-flight:  path 非空、不以 "/" 结尾、不是 symlink
stage:       tmp = temp_file(parent_dir(path), ".dawn-atomic-")
             write_file(tmp, content)
             read_bytes(tmp) == bytes_utf8(content)        # read-back
             if exists(path) { copy_permissions(path, tmp) }
install:     rename(tmp, path)
任一步失败:   delete(tmp); 返回该步的 Err
```

三个 std 自铸的 kind：`io.invalid_atomic_write_path`、
`io.atomic_write_target_is_symlink`、`io.atomic_write_verify_failed`。
其余 `Err` 一律是后端自己的说法，跟这个模块里所有别的函数一样。

read-back 比的是**字节**不是字符串：字符串要经过一个「读不懂就换 U+FFFD」
的解码器，而一次「解码后文本相同」的损坏仍然是损坏。

`parent_dir` 是个私有的十行函数，不是路径库。它只回答「往哪儿 stage」，
而 stage 目录只要与目标同一个文件系统、且可达就够。

## 验证

`scripts/atomic-write-contract/run.sh`，四类检查：

- **契约**：`probe.dawn` 在两个后端上跑同一份 fixture，各自与 `expected.txt`
  逐字节比，再互相比。JVM/native 分歧在这里红，而不是留给后面谁碰巧发现。
- **故障注入**（6 步，每步两条断言：目标原样、无 temp 残留）：
  - create —— **真实宿主失败**：目录不可写而文件可写（`chmod 500` 目录 +
    `chmod 666` 文件）。这是唯一一种「staging 失败而直接覆盖会成功」的形状，
    也正是 mutant 1 的照妖镜。
  - write / read-back / permission —— 改 std 源，把那一步换成注入的 `Err`。
  - close —— **改 C 运行时**：`dawn_io_write_file` 里 `fclose` 之后强制
    `bad = true`。Dawn 这一层没有 close 这道缝（`write_file` 是 open+write+
    close 一个宿主调用），所以注入下沉到运行时，只在 native 侧。JVM 上同一
    个失败由 `Files.write` 抛出同一个 IOException，就是 write 那条注入。
  - replace —— **真实宿主失败**：目标是一个目录，`rename` 拒绝。
- **变异（负控）**：7 个，每个必须先编译成功、再由**唯一一条** owning
  assertion 转红。实测的转红行与波及范围：

  | mutant | owning assertion | 变异后 |
  |---|---|---|
  | 恢复 direct fallback | `readonly dir content = old` | `= new`（2 行动） |
  | 固定 temp 名 | `squat content = new` | `= old`（3 行动） |
  | 跳过 read-back 验证 | `result = io.atomic_write_verify_failed` | `= ok`，且发布了损坏字节 |
  | delete-before-rename | `dir target is dir = true` | `= false`（目录被换成文件，2 行动） |
  | 跟随 symlink | `symlink still link = true` | `= false`（2 行动） |
  | 漏清理 temp | `dir target entries = ["target.toml"]` | 多出 `.dawn-atomic-*.tmp`（1 行动） |
  | 漏权限复制 | `stat a/target.toml = 640` | `600`（探针输出**一字不变**） |

  最后一条是刻意的：权限的见证者是脚本外部的 `stat`，不是被测代码自己的
  输出。所以那个 mutant 的判据额外要求探针输出**必须没变**——否则说明抓到
  它的是别的断言，`stat` 那条又成了摆设。

- **并发**：八个 native 进程同时往同一个目录里发布同一份内容，全部成功，
  结束后目录里只剩目标文件。这测的是「staging 名字由宿主挑，一次一个」，
  不是 CAS——裁决明说并发写是最后一次 replace 获胜。

- **调用点**（第二刀加的）：上面七个 mutant 改的全是 `std/io.dawn`，所以
  它们**看不见**「有没有人调用这个原语」——一个仍然用 `io.write_file` 写
  manifest 的 `dawn add` 会让七个全绿。这一节因此换一层：mutant 是**私有的
  selfhost jar**（照抄 `java-target-classpath-contract` 的手法，一次构建
  约 5s），把某一个调用点改回 `io.write_file`，再从 CLI 外面观察。

  fixture 用的是 mutant 1 那个形状、理由也一样：**目录不收新条目而里面的
  文件仍可写**，是唯一一种「staging 失败、而直接覆盖会成功」的地形。所以
  「命令失败了，旧字节还在」正是一个退回 `io.write_file` 的调用点造不出来
  的结果。每对场景都配一个可写的另一半，免得「命令坏了」被当成「原子性
  丢了」。Maven 是真解析但离线：`file://` 的 fixture 仓库放一个空 jar，
  因为 `dawn lock` 要先 fetch 才走到写。

  | mutant | owning assertion | 变异后 |
  |---|---|---|
  | `pkg/add.dawn` 改回 `io.write_file` | `add readonly manifest = old` | `= new`（2 行动，`lock ` 各行逐字不变） |
  | `main.dawn` 改回 `io.write_file` | `lock readonly lockfile = old` | `= new`（2 行动，`add ` 各行逐字不变） |

  「另一半逐字不变」是判据的一部分，不是装饰：一条**两个** mutant 都能弄红
  的断言，等于哪个都没被它拥有。

脚本开头拒绝 root：两条权限相关的检查在 root 下**不可能失败**，而一条
不可能失败的检查比没有更糟。

## 不做的（记录理由）

- **`fsync`。** 裁决把持久性划在范围外。它也不是免费的：manifest 写在
  项目目录里，一次 `fsync` 的代价与「读者看不到半份文件」这个真正的需求
  无关。想要断电存活是另一件事，且要连目录一起 fsync。
- **CAS / 并发 manifest 合并。** 裁决点名不许在 TOOL-13 名下暗做。检测
  「我读到之后有人改过」需要另一个签名（读时带上版本，写时校验），
  是独立设计。
- **`atomic_write_bytes`。** 目前唯一的消费者写的是文本。加一个二进制版
  等于把同一段算法抄第二遍或者提一层泛型，等有第二个消费者再说。
- **通用路径库。** `parent_dir` 只服务这一个调用。`packages/fspath` 是
  真正的那一份，而 std 不依赖 packages。
- **`main.dawn` 另外三处 `io.write_file`。** `fmt` 的输出、coredump、
  `-o` 的通用出口。它们不是 manifest/lock，不在 TOOL-13 范围内：前两个的
  目标要么是用户自己指定的产物路径，要么是调试转储，被半写坏了重跑一次
  即可，而 manifest/lock 被半写坏了**别的命令**全部读不了。

## 为什么 `add.dawn` / `main.dawn` 晚了一代

**种子纪律。** `bin/dawn` 的 stage 1 是**种子 jar 用种子自带的那份 std**
编译今天的 `selfhost/src`（`bin/dawn` 的 `build_generation`：
`--std "$(seed_std_dir)"`），`selfhost-prev-diff.sh` 的 feature-discipline
一步也一样。所以：

- 今天的 `std/io.dawn` 用新 intrinsic —— **可以**。stage 1 不编译 HEAD 的
  std；stage 2 用的是 stage 1（已含 HEAD 的 `builtins()`）编 HEAD 的 std。
- 今天的 `selfhost/src` 调用 `io.atomic_write_file` —— **不行**。种子的
  std 里没有这个名字，stage 1 当场红。

这就是 CONTRIBUTING §七「改破坏性的名字走一代转发器」背后的同一台机器。
所以第一刀只落宿主能力与 std 原语（连同全部负控），调用点迁移排在下一个
release 之后的那一轮。实际就是这么走的：

```
第一刀    intrinsic + std/io.atomic_write_file + 契约脚本   00b4393
v0.63.0 发布 + advance-seed                                bfbde90
第二刀    add.dawn 与 main.dawn 换成 io.atomic_write_file + 调用点负控
```

解锁的判据是可以直接看的：种子自带的那份 std 里有没有这个名字
（`.dawn/seeds/std-v0.63.0/io.dawn`）。有了，stage 1 就编得动。

这不是把裁决打了折——裁决自己写的就是「**实现前置**：必须先提供或捕获
……宿主能力」。折在时间上，而不在内容上。
