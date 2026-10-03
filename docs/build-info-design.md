# 构建来源：构建清单与 `dawn version -m`

> 状态：**current**（P1 已落地；P2、P3 为已裁决、未实现的刀序）。2026-10-03，分支 `feat/build-info-planner`。
> 依据：裁决 `agent-handoff/ruling-build-provenance-20261003.md`，调研
> `agent-handoff/research-build-provenance-report-20261003.md`（§一现状、§二一名一份、§4.2 摘要与 B==C、§五刀序）。
> 本文是那份调研的压缩，加上 P1 的落地说明。

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

采「产物内嵌构建清单 + `dawn version -m`」；位置串不带版本，panic 不加构建行（理由见第六节）。

| 刀 | 内容 | 状态 |
|---|---|---|
| P1 | compiler-plan 的 `PkgR` 带声明版本与来源；位置无关的源码摘要；`dawn version -m <project dir>` 不构建，只跑 Planner 打印清单 | 本文落地 |
| P2（含原 P0） | `jarw` 写 `META-INF/dawn/build-info`（另加 MANIFEST 属性 `Dawn-Version`）；`dawn version -m <jar>`；`--version` 打 `VERSION` + 工具链源码摘要短串，读的是自己 jar 里的 build-info；兑现或删掉 `--help` 的「and commit」；Playground `/health` 带摘要 | 未实现 |
| P3 | dawnc 的 native/wasm 产物同样内嵌（只读数据段 / wasm custom section）；`version -m <bin>`；native-fixpoint 实跑 | 未实现 |

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

$ dawn version -m app             # 一个 url 依赖
app: dawn 0.82.0
	main	app	(devel)	s1:a6b8abe3…
	dep	lib	1.1.0	s1:9a0e7ad6…	d1:d68f38e3…
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

P2 往产物里写时在最前面加一行 schema（`dawn-build-info 1`，与 package-design「每个文件第一行写 schema 版本」一致），
再加一行工具链；P1 不构建产物，没有工具链源码摘要可打，首行只有 `VERSION`。

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

### 4.4 B==C 推导（给 P2）

P2 里工具链的身份取**自身源码摘要**，不取「构建我的那个 jar」的哈希。记 `S` 为 HEAD 的 selfhost 源码，
`id(S)` 为 `(VERSION, s1 摘要)`，`J(x)` 为编译器 `x` 编出来的 jar：

- 种子编出 A，A 的清单写 `id(S)`；A 编出 B，B 的清单写的仍是被编的源码 `S` 的 `id(S)`；B 编出 C，同上。
  清单只是被编源码的函数，B 与 C 的清单逐字节相同，B==C 的推导与没有清单时一样成立。
- 反过来，若写的是「构建者 jar 的 sha256」：B 记 `sha(A)`，C 记 `sha(B)`，A≠B，于是 B≠C。P2 的负控就是把
  取法故意改成这样，fixpoint 应当红。
- 时间戳同理不能写（破可复现）。`jarw` 的条目时间已经钉死在 2020-01-01，build-info 条目照用。

工具链的 `s1` 要覆盖整个工具链源码：selfhost 自己（`main` 行）与它的传递依赖（compiler-plan、fspath、json、
sha2、inflate3 等 `dep` 行）。P2 的工具链摘要短串取「清单行（不含首行）的 SHA-256」即可，具体在 P2 定。
std 以 `stdsrc` 的形式嵌在 selfhost 源码树里，已在 `main` 行的 `src/` 之内。

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
JVM 驱动先做；dawnc 的 `version` 仍只打版本，随 P3 补。

## 六、不做的（理由）

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
- **0.x→1.x 不换名被 MVS 当成同一个包**：调研 §二的顺带观察，裁决另起内部调研，不在本线。
