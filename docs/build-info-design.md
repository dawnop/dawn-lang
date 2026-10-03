# 构建来源：构建清单与 `dawn version -m`

> 状态：**current**（P1、P2、P3 已落地）。2026-10-03，P1 分支 `feat/build-info-planner`，P2 分支 `feat/build-info-jar`，P3 分支 `feat/build-info-native`。
> 依据：裁决 `agent-handoff/ruling-build-provenance-20261003.md`，调研
> `agent-handoff/research-build-provenance-report-20261003.md`（§一现状、§二一名一份、§4.2 摘要与 B==C、§五刀序）。
> 本文是那份调研的压缩，加上 P1、P2、P3 的落地说明。P2 推翻了调研 §4.2 的一处取法（产物的工具链行写什么），见 4.4。

## 一、问题

L1（#401，[source-location-design.md](source-location-design.md)）之后，烘进产物的位置串是
`<真名>/<包内路径>`，不再有检出目录和 `d1-<hash>` 缓存目录。于是一个用户问：机器上有好几个 `dawn`，
项目又混着好几个版本的包，**到底用的是哪个 dawn、哪个版本的包**？

调研的结论（逐 file:line 见调研 §一）：

1. 工具链身份从来不在产物里，L1 前后一样。`dawn --version` 只打 `VERSION` 常量，main 上未发版的构建与上一个
   release 打印的完全相同。
2. L1 真正丢掉的只有两样：url 依赖位置串里的 `d1-<hash>`，和路径依赖的检出目录。版本号本来就不在路径里。
3. **同一个产物里，一个包名只对应一份副本**：MVS 每个真名只选一个版本（`compiler-plan/src/source.dawn` 的
   `select_url_deps`），链接阶段同名来自两个目录直接报错（`resolve_src_deps` 的
   「linked from two different directories」），major 升级靠换名（`web5`/`web6` 是两个包）。
   所以 `<真名>/<路径>` 在产物内没有歧义，缺的只是「这个名字对应哪个版本、哪份内容」的**旁表**。

## 二、裁决与刀序

采「产物内嵌构建清单 + `dawn version -m`」；位置串不带版本，panic 不加构建行（理由见第七节）。

| 刀 | 内容 | 状态 |
|---|---|---|
| P1 | compiler-plan 的 `PkgR` 带声明版本与来源；位置无关的源码摘要；`dawn version -m <project dir>` 不构建，只跑 Planner 打印清单 | 本文落地 |
| P2（含原 P0） | `jarw` 写 `META-INF/dawn/build-info`（另加 MANIFEST 属性 `Dawn-Version`）；`dawn version -m <jar>`；`--version` 打 `VERSION` + 工具链源码摘要短串，读的是自己 jar 里的 build-info；删掉 `--help` 的「and commit」；Playground `/health` 带摘要 | 本文落地（第六节） |
| P3 | dawnc 的 native/wasm 产物同样内嵌（不分配的 ELF 段 `.dawn.build-info` / wasm custom section `dawn.build-info`）；`version -m <bin>`；dawnc 的 `version` 带 `b1:`；native-fixpoint 实跑 | 本文落地（第八节） |

P 线与 L2 至 L4 没有代码依赖。

## 三、清单格式

P1 的输出，也是 P2 写进产物的那张表的行。形状照 `go version -m`：首行 `<参数>: dawn <VERSION>`，
之后每行一个制表符开头、字段以制表符分隔：

```
$ dawn version -m selfhost        # 摘要截短，实际是 64 位十六进制；数值随源码变
selfhost: dawn 0.82.0
	main	selfhost	(devel)	s1:2ff11e60…
	dep	compiler_plan	(devel)	s1:5a027113…
	dep	fspath	1.0.0	s1:344d5ab7…
	dep	inflate3	3.0.0	s1:dd803a17…
	dep	json2	2.0.1	s1:d1f6e54e…
	dep	sha2	2.0.0	s1:d3992400…
	java	io.get-coursier:interface:1.0.28
	java	org.ow2.asm:asm:9.7.1
	build	b1:2bfef5fb…

$ dawn version -m app             # 一个 url 依赖
app: dawn 0.82.0
	main	app	(devel)	s1:a6b8abe3…
	dep	lib	1.1.0	s1:9a0e7ad6…	d1:d68f38e3…
	build	b1:…
```

`inflate3` 与 `json2` 是真名：selfhost 的 manifest 用别名 `inflate`、`json` 引它们，清单不写别名。

| 行 | 字段 |
|---|---|
| `main` | 根项目的真名（没有 `dawn.toml` 时写 `(unnamed)`）、声明版本或 `(devel)`、源码摘要 |
| `dep` | 依赖包的**真名**（不是消费者的别名）、版本、源码摘要；url 依赖再加 `d1:<…>`（manifest 的 `hash`），有 `subdir` 时再加 `subdir=<p>` |
| `java` | `[java-deps]` 的坐标 `group:artifact:version`，按 Planner 的最终图收集 |

- **版本**：url 依赖写 MVS 选中的版本（archive 自己的 `dawn.toml` 若写了版本，Planner 已核过二者相等，
  不等就报错）；路径依赖与根项目写自己 `dawn.toml` 的 `version`，没写就是 `(devel)`（裁决 5.4(2)，Go 先例：
  本地 `replace` 的模块版本记 `(devel)`）。路径依赖的声明版本只是声明，内容可能在两次改版之间变了很多次，
  能说明内容的只有摘要。
- **不写任何路径**：不写检出目录、不写缓存根、不写 url。url 不写是因为同一份内容可以有多个镜像（Planner
  按 `(hash, url)` 记镜像失败，换 url 不换内容），写进去就让「同一内容」有了两种清单。
- **排序**：`dep` 行按真名排序，`java` 行按坐标排序；一个真名只出现一次（一名一份）。所以输出只是
  源码与 manifest 的函数，与工作目录、缓存根、`[deps]` 声明顺序都无关。
- 依赖表是**传递闭包**：路径依赖的依赖、url 依赖的依赖都列，与产物里实际链接的包一一对应。

`dawn version -m` 的输出最后还有一行 `\tbuild\tb1:<64 位十六进制>`：上面各行（每行连同换行符）的 SHA-256，
叫**清单摘要**（P2 加，见 6.2）。它是 `dawn --version` 末尾那串短摘要的全长，用来把一个工具链和它的源码、它的 jar 对上。

P2 往产物里写的文件在这些行前面加两行：schema 行 `dawn-build-info 1`（与 package-design「每个文件第一行写 schema 版本」一致）
与工具链行 `toolchain\tdawn <VERSION>`（写这个 jar 的工具链的 `VERSION`）。`build` 行不写进文件，读的时候现算。

## 四、源码摘要（`s1:`）

### 4.1 定义

一个包的源码摘要只看它的 `dawn.toml` 与 `src/` 树：

1. 取条目：`dawn.toml`（存在的话）与 `src/` 下的每个普通文件；`src/` 里有符号链接就报错（与 `d1` 同理：
   链接在归档里不可移植，摘要拒绝它而不是跟随它）。
2. 每个条目以 **`<真名>/<包内路径>`** 命名：`<真名>/dawn.toml`、`<真名>/src/<相对路径>`。包内路径相对的是
   包目录（`src/` 的上一级），不是 `src/`，这样 `dawn.toml` 与 `src/` 里同名的文件不会撞名。
3. 按名字排序后逐条喂给 SHA-256：`名字 \0 字节数 \0 内容`，与 `d1` 的帧完全相同，只是名字不同。
4. 结果写成 `s1:` + 64 位十六进制。

实现：`compiler-plan/src/buildinfo.dawn` 的 `source_digest`。文件列表复用 `pkgfetch.collect_files`（`d1` 用的那份）。

### 4.2 为什么与检出目录、缓存根无关

名字里只有真名与包内相对路径，没有任何一段来自包目录本身的位置。同一棵树放在 `/a/x` 与 `/b/y`，
条目名、排序、内容都一样，摘要就一样（inline test 直接这么测）。现成的 source-input manifest
（`source.dawn` 的 `bootstrap_source_input_manifest`）不能复用：它对项目根之外的路径依赖记 `A\t<绝对路径>`，
selfhost 的 `../compiler-plan` 正属此类。

### 4.3 与 url 依赖的 `hash`（`d1:`）的关系

| | `d1:`（manifest 的 `hash`） | `s1:`（源码摘要） |
|---|---|---|
| 覆盖 | 整个解包后的归档树（去掉唯一顶层目录），包括同一归档里的其他包 | 只有这个包的 `dawn.toml` 与 `src/` |
| 名字 | 归档内相对路径 | `<真名>/<包内路径>` |
| 谁算 | `dawn add` 算一次，写进消费者 manifest；每次取缓存时重算校验 | Planner 之后按需算，不落盘 |
| 回答 | 「下载到的是不是声明的那份归档」 | 「编进来的是不是这份源码」 |

一个归档常常装好几个包（dawnop-site 的 `web`/`json`/`sha2` 共用一个 tag 归档，靠 `subdir` 区分），所以 `d1`
说明不了「编进来的是哪个包的哪份内容」，`subdir` 也只是归档内的位置。`s1` 对 url 依赖与路径依赖定义相同：
同一个包无论走路径还是走 url 引入，`s1` 相同，可以直接比。所以 url 行两个都写：`s1` 用来跨来源比较，
`d1` + `subdir` 用来回溯到 manifest。

### 4.4 B==C 推导，与产物的工具链行为什么只有 `VERSION`

记 `S` 为 HEAD 的 selfhost 源码，`R(S)` 为它的清单行（第三节，只是源码与 manifest 的函数），`J(x)` 为编译器 `x` 编出来的 jar。

- 种子编出 A，A 编出 B，B 编出 C。B 与 C 编的都是 `S`，清单行都是 `R(S)`；工具链行都是 `toolchain\tdawn <HEAD 的 VERSION>`
  （A 与 B 都由 `S` 编成，`VERSION` 是 `S` 里的常量）。清单整份是被编源码的函数，B==C 的推导与没有清单时一样成立。
- 工具链自己的身份（`--version` 打的那串）取**自己 jar 里清单行的摘要**，即 `b1(R(S))`。它也只是 `S` 的函数：
  任何由 `S` 编成的工具链，不论谁编的，都报同一个值。
- 若写「构建者 jar 的 sha256」：B 记 `sha(A)`，C 记 `sha(B)`，A≠B，于是 B≠C。P2 的负控就是这么改的，`build-release-jar.sh` 红在 `cmp`（6.5）。
- 时间戳同理不能写（破可复现）。`jarw` 的条目时间已经钉死在 2020-01-01，build-info 条目照用。

**调研 §4.2 原本想在产物的工具链行写构建者的身份**（构建者 jar 里清单行的摘要，即「B 里写 A 的自我身份」），P2 没有这么做，理由是两条：

1. **过渡期 B≠C。** 种子 v0.82.0 早于 P2，它编出的 A 没有清单。A 编 B 时读不到自己的身份，只能写「未知」；B 有清单，B 编 C 时写 `b1(R(S))`。
   于是 B≠C，fixpoint 与 release 在 P2 合入到下一次推进种子之间一直红。`selfhost/src` 不能等种子。
2. **清单格式一改就再红一次。** 即使种子已经会写清单，A 的清单行是**种子的代码**算的，B 的是 **HEAD 的代码**算的。
   B 的工具链行 = `b1(种子算的 R(S))`，C 的 = `b1(HEAD 算的 R(S))`。将来只要改了摘要定义或行的渲染（加一列、改排序），二者就不同，
   B≠C 要等到种子再推进一次才恢复。这等于给清单格式加了一条「改了就要发版过渡」的约束，与 `selfhost/src` 只准用种子已支持的语言特性是同一类负担，没有必要背。

所以产物只写构建者的 `VERSION`（与 MANIFEST 的 `Dawn-Version` 相同），不写构建者的摘要。代价是：一个用户程序的 jar
只能说「由 dawn 0.82.0 编成」，分不出是 release 还是之后某个 main 构建编的。工具链本身仍然可以完全追溯：
`dawn --version` 打它自己的 `b1:` 短串，`dawn version -m <它的 jar>` 打全长与所有行，`dawn version -m selfhost` 对一棵检出算出同一个值。
若将来确实需要产物记构建者摘要，前提是先把「格式一改就红」解决掉（例如让 B==C 的比较排除工具链行，那要改 release 配方的
`cmp`，是另一个裁决）。

std 以 `stdsrc` 的形式嵌在 selfhost 源码树里，已在工具链 `main` 行的 `src/` 之内。

## 五、P1 的落地

| 位置 | 改动 |
|---|---|
| `compiler-plan/src/source.dawn` | `PkgR` 加 `version: Option[SemV]` 与 `origin: PkgOrigin`（`FromPath` / `FromUrl(hash, subdir)`）。`select_url_deps` 的结果从「名字 → 根目录」改为「名字 → 选中的版本、hash、subdir、根目录」，`resolve_src_deps` 建 `PkgR` 时用胜出者的版本而不是消费者请求的版本（一个包常被多个消费者以不同版本请求，`PkgR` 按目录缓存，第一个消费者建的那份要写对）。 |
| `compiler-plan/src/buildinfo.dawn`（新） | `source_digest`、`build_rows`（从 `SourcePlan` 收传递闭包，按真名去重排序）、`render_row`/`render`。纯函数加 `!Fs`，可以在 `memfs` 上测。 |
| `compiler-plan/src/pkgfetch.dawn` | `collect_files` 改为 `pub`，供摘要复用同一份「拒绝符号链接、排序」的文件列表。 |
| `selfhost/src/main.dawn` | `version` 子命令加 `-m <project-dir>...`；`dawn version` 不带参数时不变；带了别的参数报用法错误。 |

**摘要不在 `source_plan` 里算**。`source_plan` 每次 `dawn run`/`check`/LSP 重建项目都会走，摘要要读整棵树
（调研实测 `__pkghash selfhost/src` 0.75 s），放进去就是给每次编译加一次全量读。`PkgR` 只带便宜的、
本来就在手边的东西（版本与来源），摘要由 `buildinfo.build_rows` 在需要清单的时候算。

`dawn version` 不带参数时照旧打印版本；带了 `-m` 以外的参数现在是用法错误（修前会忽略参数照打版本）。
`--version`/`-V` 不变。`dawn version -m` 的错误面：目标不是目录报 `not a directory`；Planner 有诊断时照 `dawn lock` 的样子渲染诊断后退出；
项目没有 `src/` 报 `has no src/ folder`；摘要失败（符号链接、读不了）报 `error:` 加原因。
JVM 驱动先做；dawnc 的 `version` 由 P3 补上（第八节）。

## 六、P2 的落地

### 6.1 jar 里的东西

`dawn build` 写的每个 jar 多两样，都在 `jvm/jarw.dawn`：

- MANIFEST 属性 `Dawn-Version: <VERSION>`，放在 `Add-Exports` 之后、`Class-Path` 之前。只为了 `unzip -p x.jar META-INF/MANIFEST.MF`
  不用 dawn 就能看出版本，不是主体。
- 条目 `META-INF/dawn/build-info`，紧跟 MANIFEST，写在所有 class 之前，同一套钉死的时间戳与 STORED 写法。内容由
  `compiler_plan/buildinfo.render_file` 生成。工具链自己的 jar 照录（摘要随源码变）：

```
dawn-build-info 1
toolchain	dawn 0.82.0
	main	selfhost	(devel)	s1:2fb073b9…
	dep	compiler_plan	(devel)	s1:ba541ef8…
	dep	fspath	1.0.0	s1:344d5ab7…
	dep	inflate3	3.0.0	s1:dd803a17…
	dep	json2	2.0.1	s1:d1f6e54e…
	dep	sha2	2.0.0	s1:d3992400…
	java	io.get-coursier:interface:1.0.28
	java	org.ow2.asm:asm:9.7.1
```

清单不经 Core、不经 `__emit` 的 class 目录，所以 emit 语料、Core golden、prev-diff 都看不见它；它只在 jar 里。

### 6.2 清单摘要 `b1:` 与 `--version`

- `b1:` = SHA-256（清单行文本），清单行文本 = 每行 `render_row` 加换行，从 `main` 到最后一行 `java`，不含 schema 行、工具链行、`build` 行。
  `buildinfo.manifest_digest`。P1 备注 2 的定义。
- `dawn --version` 打 `dawn 0.82.0 (selfhost) b1:2bfef5fb3622`：`VERSION`，加上**自己 jar** 的清单摘要前 12 位（`short_digest`）。
  「自己 jar」是装着入口类 `main.class` 的那个 jar（`jarw.own_build_info`，经 jar: URL 读条目），不是 class path 上第一个
  `META-INF/dawn/build-info`：问的是「我是谁」，class path 上可以有别的 dawn 产物。裁决 5.4(1) 选的 (ii)：读，不编进常量。
- 读不到（不是从 jar 跑的、jar 是旧 dawn 写的没有清单、清单读不懂）时只打 `dawn 0.82.0 (selfhost)`：缺省，不报错，也不猜。
- `dawn version` 不带参数与 `--version` 同一行。

`--help` 原来写「print the toolchain version and commit」，从 M8 起就没打过 commit。**删掉「commit」，改成「and the digest of the
sources it was built from」**，不兑现，理由：提交号不是源码的函数。tarball、`git archive`、脏树、补丁都没有可信的提交号；
要拿就得在构建时读 git（裁决 5.4 的 (iii)），那是把构建机的状态写进产物，正是第七节不做的事。清单摘要对同一份源码给同一个值，
对 tarball 与检出给同一个值，`dawn version -m selfhost` 能在任何一棵树上复算，这是提交号做不到的。

### 6.3 `dawn version -m <jar>`

`-m` 后的参数是目录就照 P1 跑 Planner，是文件就当 jar 读条目；两者输出同一形状：首行 `<参数>: dawn <VERSION>`，各行，最后 `build` 行。
读 jar 时首行的 `VERSION` 是**写这个 jar 的工具链**的（清单工具链行），各行逐字节取自 jar，不重算，所以两份列表可以直接 diff。
对工具链自己：`dawn version -m build/dawn-selfhost.jar` 与 `dawn version -m selfhost` 除首行外相同，`build` 行的前 12 位就是 `--version` 末尾那串。

错误面：参数不存在 `no such file or directory: <p>`（P1 时是 `not a directory`）；打不开为 jar `cannot read <p> as a jar: <原因>`；
是 jar 但没有条目 `<p> carries no build manifest (META-INF/dawn/build-info): it was not written by \`dawn build\`, or was written by a dawn from before build manifests`；
条目 schema 不认识或形状不对，报 `parse_file` 的原因（不认识的 schema 拒绝，不猜它的行）。

### 6.4 单文件 `dawn build x.dawn`

单文件没有 `dawn.toml`，P1 的 `build_rows` 对它返回 Err。P2 的决定：

- `main` 行写 `(unnamed)`、`(devel)`，摘要取**这次加载实际读进来的根包源文件**：入口文件加上它经 `use` 读到的同目录（或同 `src/`）文件，
  每个以 `(unnamed)/<位置路径>` 命名（位置路径就是 L1 的 `site_path`，已经与 cwd 无关），帧与 `s1` 相同（`buildinfo.file_rows`、`texts_digest`）。
  P1 建议的「只写 main 行」只够没有 `use` 的单文件；只摘要入口文件会漏掉它读到的兄弟文件，等于少说了产物的内容。
- 文件若在某个项目的 `src/` 下，加载会链接那个项目的 `[deps]`，所以 `dep`/`java` 行照 Planner 写（可能是实际用到的超集，
  超集不影响「同摘要即同源码」）。
- 不对整个目录做摘要：单文件的目录可能是 `~` 或 `examples/`，与这次构建无关的文件不该进摘要，也不该被读一遍。

项目目录的 `--closure` 构建仍用 `build_rows`（整棵 `src/`），与 `version -m <dir>` 一致；也是超集。

### 6.5 负控与实测

- **两处、两 cwd、两缓存根字节相同**：`main.dawn` 测试「a jar's build manifest is the same bytes from two places…」，同一项目两份临时检出，
  不同 cwd、不同 `DAWN_PKG_CACHE`，`build_manifest` 输出相同且不含检出路径。CLI 层：带 url 依赖的项目在两个 cwd、两个缓存根下
  各 `dawn build`，`unzip -p … META-INF/dawn/build-info` 逐字节相同（数字在 P2 报告里）。
- **误用构建者 jar 哈希时 B==C 变红**：把工具链行改成写构建者 jar 的 sha256，`scripts/build-release-jar.sh` 在 `cmp stage-b stage-c` 处红；复原后绿。
- **清单被删时报清楚的错**：`jarw` 测试（没有条目是 `Ok(None)`，不是 jar 是 `Err`）与 `main.dawn` 测试（条目不是清单时报 schema 错），
  CLI 层用 `zip -d` 删掉条目后 `version -m` 报上面的「carries no build manifest」。

### 6.6 没有覆盖的

- **`--std`/`DAWN_STD` 指定的 std 目录**不在清单里。bin/dawn 总是把 `DAWN_STD` 设成检出的 `std/`，所以经 bin/dawn 构建的用户程序编进的是
  那个目录的 std，而工具链行只说 `VERSION`。`std/VERSION` 与工具链 `VERSION` 由测试保持相等，内容一般也与 `stdsrc` 同步，但清单不证明这一点。
  要证明需要一行 `std`（std 目录的摘要）。P3 的结论：不加，见 8.5。
- **`dawn build --native`**（GraalVM native-image）：中间 jar 里有清单，native-image 默认不收资源，二进制里没有。P3 的结论：记下不做，见 8.5。
- **dawnc 的 `version`**：P3 已补（8.3）。

## 七、不做的（理由）

- **位置串带版本**（`web6@6.0.0/server.dawn`）：路径依赖的版本不可信、没有哈希；改动落在 emit 语料与 Core golden 上，
  web 每次升版都动；`@` 串不是任何文件系统路径；等于重开 L1 刚定的形状。
- **panic 追加构建行**：每个带 `main` 的 emit label、run-diff 的 panic 转写、playground 合约都要改；一行装不下依赖表；
  给最终用户的输出多一行内部信息，与 L1 的「不外泄」相反。
- **把缓存路径或检出目录写回任何地方**：那正是 L1 修掉的病。
- **记构建者 jar 的哈希或构建时间**：前者破 B==C（4.4），后者破可复现。
- **`[deps]` 锁文件**：url 依赖已由 manifest 的 `hash` 钉死，给定 manifest 的 MVS 是确定的；路径依赖锁不住内容。
  要回答的是「产物用了什么」，那是产物的属性，不是项目的属性；package-design §4.6 把 lock 限于 `[java-deps]` 的理由仍成立。
- **SLSA / in-toto 证明**：要签名基础设施与外部存储；若要做，走 gates-external 的签名证据线，对 release jar 出证明，
  不是编译器的事。
- **在 `source_plan` 里算摘要**：见第五节，给每次编译加一次全量读。
- **`version -m <file.dawn>`**：单文件没有 manifest，也就没有依赖表；`main` 行只剩一个摘要，用 `dawn __pkghash` 已能回答。
  （`dawn build x.dawn` 的 jar 有清单，见 6.4，`version -m <那个 jar>` 能读。）
- **产物的工具链行写构建者的清单摘要**：过渡期与清单格式每次改动都破 B==C，见 4.4。
- **`--help` 兑现「commit」**：提交号不是源码的函数，见 6.2。
- **清单进 `__emit` 的 class 目录或 Core**：那会让 emit 语料与 Core golden 随依赖版本动，正是 L1 与本线都在避开的。
- **0.x→1.x 不换名被 MVS 当成同一个包**：调研 §二的顺带观察，裁决另起内部调研，不在本线。
- **native 产物的清单放在带魔数的只读数据里**：要靠搜索找，读者自己（dawnc 读自己）的数据里就有一份魔数；改用段名查表，见 8.1。
- **清单进 `emitc` 的 C 文本**：C 文本受 prev-diff-native、native-cli-diff、native-fixpoint 逐字节比较，工具链行的 `VERSION` 一发版就变，见 8.1。
- **Mach-O（macOS）的清单段**：没有在跑的 macOS native 门禁，读者也要另写一套 Mach-O 解析；那里链出的产物没有清单，`version -m` 报「没有」，不报错的东西。
- **`dawnc version -m <jar>`**：jar 是 JVM 工具链的产物，读它靠 JDK 的 zip；要在 native 里读得再写一个 zip 读者。dawnc 遇到 jar 报错并指向 `dawn version -m`。

## 八、P3 的落地

### 8.1 放在哪里：不分配的 ELF 段，与 wasm custom section

任务给了两条路：ELF 段，或带魔数的只读数据。选段，理由三条（也写在 `selfhost/src/c/binfo.dawn` 文件头）：

1. **不用猜。** 魔数要在整个文件里搜，而 dawnc 读自己（`--version`）时，它的只读数据里就躺着读者代码自己的那份魔数，
   怎么把两者分开都是格式本身没有的规矩。段是在格式定义的表里按名字查。
2. **对程序零成本。** 段的标志是空（与 `.comment` 一样不分配），不映射进内存，也不挪动代码与数据的任何地址；
   `strip` 保留它，`objcopy --remove-section .dawn.build-info` 删掉它后二进制照常运行（8.4）。
3. **不用 dawn 也读得出来**：`readelf -p .dawn.build-info <bin>`。这正是 P2 给 jar 加 `Dawn-Version` 属性的理由，格式自带的工具更好。

wasm 的对应物是 custom section，名字按任务定为 `dawn.build-info`。两种都由**同一个 C 编译单元**写出：文件作用域的 `__asm__`，
`#if defined(__wasm__)` 一支、`#elif defined(__ELF__)` 一支，内容是 `render_file` 的字节逐个 `.byte`。不用 C 的
`__attribute__((section))`，因为它在 ELF 上给的是**要分配**的段，在 wasm 上给的是数据段而不是 custom section（clang 20 实测，
custom section 只有经汇编 `.section ".custom_section.<名>"` 才出得来；名字要加引号，否则汇编器在 `-` 处截断）。
其它目标格式（Mach-O）两支都不进，单元为空，产物没有清单。

**这个单元是单独一个文件，不并进 `emitc` 的 C 文本。** 理由与 P2 不让清单进 `__emit` 相同：C 文本被 prev-diff-native（对上一 release）、
native-cli-diff（JVM 对 native）与 native-fixpoint（A==B==C）逐字节比较；清单的工具链行写 `VERSION`，并进 C 文本就意味着每次发版
所有 C 语料都动。清单在「容器」里，不在「代码」里：jar 是条目，二进制是段，C 是 class 目录的对应物。

### 8.2 谁写

| 路径 | 怎么写 |
|---|---|
| `dawnc build`（native 与 `--target wasm`，含 `--reactor`） | `cc_build_with` 多一个参数：清单单元的文本，暂存为 `dawn_build_info.c`，排在 `dawn_rt.c` 之后进同一条链接命令 |
| `dawnc emitc --build-info <file.c>` / `dawn __emitc --build-info <file.c>` | 另写出这个单元，给自己调 `cc` 的脚本用：`release-native.sh` 与 `native-fixpoint.sh` 都改为带它链接 |
| `dawnc run` / `dawnc test` | 不写：产物跑完即删，不为它规划与摘要 |

内容一律是 `buildinfo.product_file(VERSION, target, root_files)`：P2 的 `build_manifest` 原样搬进 compiler-plan，jar、native、wasm
三种产物与两个驱动走同一个函数，`root_files` 由 `driver/analyze.root_sources` 从这次加载里取。所以同一个程序编成 jar 和编成二进制，
`version -m` 列出的行逐字节相同（8.4 实测）。工具链行仍只写 `VERSION`，4.4 的理由对 native-fixpoint 原样成立：A 由 JVM 写、B 由 dawnc-A 写，
写构建者摘要就会 A≠B。

dawnc 自己是 `selfhost/src/nmain.dawn` 的单文件构建，按 6.4 的规则 `main` 行是 `(unnamed)`、摘要覆盖加载读到的 selfhost 根包文件，
`dep`/`java` 行照 selfhost 的 Planner 写（含 `java` 两行，超集，dawnc 里并没有 Java）。所以 dawnc 的 `b1:` 与 JVM 工具链的 `b1:` 不同：
二者本来就是不同的源码集合。

### 8.3 谁读

- `dawn version -m <file>`：文件开头是 ELF 魔数或 wasm 魔数就走 `c/binfo`，否则照旧当 jar。输出与 jar、目录同形（`binfo.listing`），
  首行的版本取自清单的工具链行，各行不重算。
- `dawnc version -m <project-dir | binary>...`：参数处理照 nmain 的惯例另写一份，活是同一个（目录走 `buildinfo`，文件走 `binfo`）。
  jar 不读，报错指向 `dawn version -m`（见第七节）。
- `dawnc --version` / `dawnc version`：`dawnc 0.82.0 (native) b1:381a846adffa`。读的是 `/proc/self/exe`，即**自己这个文件**里的段，
  不编进常量（裁决 5.4(1) 的 ii，与 `jarw.own_build_info` 同理）。读不到（没有 `/proc` 的系统、没链清单单元的二进制、旧 dawn 编的）时
  只打旧格式，不报错。
- ELF 读者只读小端，两种位宽都读；段数超过 0xff00 的扩展编号不读（没有链接器会给这么大的程序写出它），按「被截断」报。
  任何越界都是 `Err`，不是 panic（单测把文件从四处截断）。

错误面：没有段 `<p> carries no build manifest (section .dawn.build-info): it was not linked by \`dawnc build\`, or was built by a dawn from before build manifests`
（wasm 写 `custom section dawn.build-info`）；段内容不是清单时报 `parse_file` 的原因；既不是 ELF 也不是 wasm 的文件在 dawnc 上报
`not an ELF executable or a wasm module`，在 dawn 上交给 jar 读者。

### 8.4 负控与实测（2026-10-03）

- **两处、两 cwd、两缓存根字节相同。** 一个 url 依赖项目（`lib 1.1.0`，`file://` tar.gz），两份检出 `w1/app`、`w2/app`：一次 cwd=`w1`、
  `DAWN_PKG_CACHE=c1`、目标写相对路径；一次 cwd=上级、`c2`、目标写 `w2/app` 的绝对路径。`dawnc build` 的二进制 `cmp` 相同；
  `--target wasm` 的两份 `.wasm` 也相同（前提是 `-o` 的**文件名**相同：wasm-ld 把输出文件名写进 `name` section，这是既有行为，与清单无关）。
  **先证会红**：第三份检出只在 `dawn.toml` 末尾加一行注释，二进制与 `w1` 的差 79 字节；删掉 `.dawn.build-info` 与 `.note.gnu.build-id`
  两段后二者 `cmp` 相同。即清单的变化只落在清单段与 build-id（链接器对整个输出取的哈希）上，程序本身没有一字节动。
- **同一程序两种产物，清单相同**：同一项目 `dawn build` 出的 jar 与 `dawnc build` 出的二进制，`dawn version -m` 除首行参数名外逐字节相同；
  同一二进制 `dawn version -m` 与 `dawnc version -m` 的输出 `cmp` 相同（JVM 读者与 native 读者对拍）。
- **native-fixpoint 实跑**：`A.info.c == B.info.c == C.info.c`，`dawnc-B --version` 的 `b1:381a846adffa` 等于 JVM 读 `dawnc-B` 列出的
  `build` 行前 12 位；本地另编一份 dawnc 也报同一个值。**先证会红**：把 nmain 写清单时的版本改成 `VERSION ++ "-mutant"`，fixpoint 红在
  「the native compiler writes a different build manifest than the JVM toolchain (A != B)」。
- **release-native.sh**：两次独立 `-static` 链接字节相同仍成立（清单单元不含时间与路径）；新检查 2b（产物自报的 `b1:` 等于构建它的工具链
  `version -m` 读出的）绿。**先证会红**：链接行去掉清单单元，2b 红在「the toolchain that built the artifact finds no build manifest in it」。
- **剥掉后照常运行**：`objcopy --remove-section .dawn.build-info` 后 native 程序照常输出，`version -m` 报上面的「carries no build manifest」，exit 2；
  `llvm-objcopy --remove-section dawn.build-info` 后 wasm 在 node WASI 下照常输出，`version -m` 同样报错。`strip` 后段仍在、仍能读。

### 8.5 P2 备注 4 的三项

- **`--std`/`DAWN_STD` 的 std 目录：不加 `std` 行。** 一行 `std` 只能在**构建时**知道（取决于环境变量），`dawn version -m <dir>` 只看源码，
  于是同一棵树的目录清单与产物清单就会因 `DAWN_STD` 是否设置而不同，`version -m selfhost` 对 `--version` 的复算（release.yml 依赖它）也会断：
  bin/dawn 总设 `DAWN_STD`，release 配方的构建也经它。另外 std 目录的 `VERSION` 与工具链不同时加载就报 `std version mismatch`，
  剩下没被证明的只是「同一 VERSION 下改过的 std 目录」。重开条件与形状：确有人需要区分时，只在**所用 std 与工具链内嵌的 stdsrc 内容不同**
  时写一行 `std\t<s1>`，相同时不写，这样经 bin/dawn 的常规构建不受影响；那要每次构建多读一遍 std 目录，属另一刀。
- **`dawn build --native`（GraalVM）：记下不做。** 产物是 native-image 的输出，不经 `cc`，链不进本节的单元；要做只能事后
  `objcopy --add-section`（多一个外部工具依赖，macOS 上还不是 ELF）或让 native-image 收资源（读者要解析 GraalVM 的资源格式）。
  这条路径本身少用，dawnc 才是 native 的正路。中间 jar 的清单仍在，构建者可以先 `version -m` 那个 jar。
- **dawnc 的 `version`：做了**，见 8.3。

### 8.6 CI 墙钟

见 P3 报告（`agent-handoff/build-info-p3-report-20261003.md`）。量级：每次 `dawnc build` 多一次 Planner 与摘要（毫秒到亚秒），
release-native 与 native-fixpoint 各多一个几百字节的 C 单元（`cc` 时间可忽略），native-cli-diff 多两对 `version -m`。
