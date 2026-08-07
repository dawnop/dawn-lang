# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

**Dawn** —— 一门自制语言，编译到 JVM 字节码（也能经 GraalVM 出 native 二进制）。
编译器**已自举且只此一套**：`selfhost/` 用 Dawn 写成（词法到 codegen + LSP），
从上一 release 的种子 jar 自举；最初的 Kotlin 实现归档在 `kotlin-final` tag。
它不是玩具：同作者的 [dawnop-site](https://github.com/dawnop/dawnop-site)
整个生产后端（博客 + 网盘 + WebDAV）100% 跑在它编出来的代码上。

语言设计的权威定义在 [`docs/spec.md`](docs/spec.md)，里程碑历史在 [`docs/design.md`](docs/design.md)。

## 语言约定（**先读这条**）

**代码一律英文，文档一律中文。** 这条执行得很彻底，不是倾向：

- `.dawn` 源码（`selfhost/`、`site/`、`playground/`、`packages/`、`std/`）注释全英文；
  报错信息、CLI 输出全英文。
- `docs/` 全中文（索引与状态分层见 [docs/README.md](docs/README.md)）。
  （篇数不在这里复述——`scripts/doc-check.py` 每次跑都会报，那才是不会过期的计数。）
- **对外那一层反过来：英文是正本，中文是译本。** `README.md` 是英文原文，
  `README.zh-CN.md` 是它的译本。**改对外文案时先改英文，再改中文译本**——
  译本头部的 `<!-- doc-check: translation-of ... @ <digest> -->` 记着原文的摘要，
  英文一动、中文没跟，`scripts/doc-check.py` 就红（登记表在该脚本的 `TRANSLATIONS`）。
  方向是这么定的：谁是派生物，腐烂就落在谁身上；对外层的读者大多不读中文，
  把英文做成派生物等于把腐烂藏在最多人看、最没人校对的那一面。
- **提交信息也是英文**，一行祈使句主题。这里曾长期写着 `type(scope): 中文摘要`——
  摘要用中文这条**自 2026-07-25 起再没出现过**（`git log --format='%s' -200` 里 0 条中文，
  历史上 126 条）；`type(scope):` 前缀也基本退了（近 200 条里 4 条）。以 `git log` 为准。
  正文写什么见文末「重要约定」。

写代码时别把 docs 的语言带进去，反之亦然。

## 文件头注释：讲**为什么**

每个文件在顶层声明之前有一段注释，说明这个文件为何存在、以及它做了哪些不显然的取舍。
不是「这个文件定义了 Parser」那种复述，是「为什么选 `io.get-coursier:interface`
而不是 coursier 本体」那种。新增文件请照做。

## 命名是**语义**，不是风格

`lower_snake_case` = 值/函数/模块，`PascalCase` = 类型/构造器。**这是强制的**：
parser 靠首字母大小写消歧（`TYPEIDENT` 是独立 token），所以改大小写是改语义、不是改风格。
权威表述在 [`docs/spec.md`](docs/spec.md) §1（「命名约定是强制的」那条）。

## 常用命令

```bash
./bin/dawn --version                     # 首次自动拉种子并重建工具链
./bin/dawn test selfhost                 # 编译器自身的测试（145 个）
./bin/dawn run examples/data/shapes.dawn      # 单文件
./bin/dawn run examples/projects/hello_mod     # 多模块项目
./bin/dawn test site                     # 站点生成器的 Dawn 测试
./bin/dawn fmt std site selfhost packages examples --check  # Dawn 代码格式检查
./site/build.sh                          # 端到端建站（含 Playground 前端 bundle）

./scripts/selfhost-fixpoint.sh           # 自举固定点：种子→A→B→C，B==C
./scripts/selfhost-prev-diff.sh          # N vs N−1 差分（emit 语料 + 生态扫描）
./scripts/selfhost-run-diff.sh           # CLI 转写对拍 vs 上一 release
./scripts/selfhost-lsp-diff.sh           # LSP 会话对拍 vs 上一 release
```

> `bin/dawn` 需要 JDK 21。没设 `JAVA_HOME` 时它会在 `~/tools/graalvm-*` 里找
> （macOS 的 `Contents/Home` 与 Linux 的顶层 `bin/` 两种布局都试）。
> 种子 = `scripts/seed-release.txt` 钉住的 release 的 `dawn-selfhost.jar`，
> 缓存在 `.dawn/seeds/`；离线或调试用 `DAWN_SEED=<jar>` 指本地 jar。

## 目录结构

```
selfhost/          编译器（Dawn 写 Dawn）：lexer→parser→checker→interp(comptime)→codegen→cli/lsp
selfhost/src/      分九个目录，依赖单向向下（拓扑序即下面的顺序），入口留根：
                   embed/  生成物，不许手改（stdsrc rtsrc unicode_case unicode_class）
                   front/  词法/语法/诊断/格式化（token lexer parser ast diag suggest fmt lexdump astdump）
                   check/  类型与检查（types tast exhaustive jsig cx passes checker）
                   ir/     Core IR 及其上的 pass（core lower interp reach coredump）
                   jvm/    JVM 后端（codegen emit ops help jreflect rtclasses jarw testrun jfold）
                   pkg/    包与清单（manifest manifestv maven toml pkgfetch vendor add fspath）
                   driver/ 模块图与整程序驱动（analyze stdlib checkdump）
                   c/      native 后端（emitc cdriver ctestrun rc）
                   lsp/    语言服务（server lspc lspq）
                   根：main.dawn nmain.dawn doc.dawn version.dawn
std/               捆绑标准库源（--embed-std 嵌进独立 jar）
packages/          源码包（json、web），[deps] 消费
site/              用 Dawn 自己写的静态站生成器（自举）
site/play-ui/      Playground 编辑器（TypeScript + Vite + CodeMirror 6）
playground/        Dawn 写的 playground 后端
editors/vscode/    VS Code 插件
docs/              设计文档（中文）
examples/          示例
```

codegen 的**运行时 intrinsic 契约**声明在 `selfhost/src/check/types.dawn`（`Rt` / `Intr` /
`intrinsics()`，约 1645–1806 行）：语言只说一个 primitive 归哪个**运行时模块**
（`RtStrings`/`RtBytes`/`RtArray`/`RtIo`），由各后端自己决定那是什么——JVM 后端在
`emit.dawn` 用 `rt_class`/`rt_intrinsic_class`（586/598 行）映到类名，native 后端映到
C 翻译单元。背景与分期见
[docs/runtime-intrinsics-design.md](docs/runtime-intrinsics-design.md)。

> 这段以前写的是「`emit.dawn` 的 `rt_intrinsic_target` 表」。那张表**已经不存在**了——
> 它记的是 `(class, method)`，也就是把一个后端的命名习惯放进共享表里，第二个后端
> 根本读不了（理由就写在 `types.dawn:1657` 的注释里）。今天表里只剩「哪个模块」。

> **第二后端已经在跑了。** native 后端（Core IR → C）自 2026-07-30 起自举，
> `scripts/native-fixpoint.sh` 验 B==C。所以这里曾经写的「真要第二后端，得先有
> backend-neutral 的 lowered IR 与 FFI capability」两个前置都已被事实推翻：
> 共享 IR 就是 Core IR，已经在用；**FFI capability 根本不是前置**——全仓 `use c`
> 至今 0 处，native 后端靠**拒绝** `use java`（`emitc.dawn:575` 的 `CForeign` 分支）
> 加二十来个 io intrinsic 就走完了自举。
>
> 仍然成立的是**工作量**那半边：`tast.dawn` 的 `TJavaCall` 直接携带 JVM 类名、
> descriptor、SAM 与 List bridge；checker 靠 Java 反射解析 `use java`；
> `emit.dawn`/`codegen.dawn` 遍布 ASM opcode、JVM descriptor、LambdaMetafactory 与
> CHECKCAST。这些是 JVM 后端**自己**的内脏，不是共享层的债。
> 计划见 [docs/native-backend-plan.md](docs/native-backend-plan.md)，调研见
> [docs/llvm-backend-research.md](docs/llvm-backend-research.md)、
> [docs/collections-dejava-research.md](docs/collections-dejava-research.md)，
> 现状记录在 docs/codebase-audit.md 的 ARCH-03/ARCH-04。

Kotlin 实现（compiler/，1170 项测试、386 个黄金文件）已随 `kotlin-final` tag
整体归档——考古看那个 tag，别在 main 找。

## 测试

`./bin/dawn test selfhost` 跑编译器自身的 test 块（就写在 `selfhost/src/` 源文件里）。
输出层面的回归由**差分**守护：`selfhost-prev-diff.sh`（emit 语料逐字节 vs 上一
release）、`selfhost-run-diff.sh`（CLI 转写）、`selfhost-fmt-diff.sh`（格式化）、
`selfhost-lsp-diff.sh`（LSP 会话）。**故意改变输出**（报错文案、格式化结果、CLI
文本）时，提交信息里为**每一个**被改动的检查 label 写一行
`Emit-Change(<label>): <说明>`——没有声明的字节差异 CI 红灯。label 必须逐字列在
`scripts/emit-labels.txt` 里，**不接受通配**（`emit *`、裸 `Emit-Change:` 都是错误）。
语言定义与理由写在 `scripts/emitchange.sh` 头部；`scripts/emitchange-selftest.sh` 是
这个解析器自己的门禁。

`playground/test/contract.sh` 是端到端合约测试（起 runner、驱 `/run` 与 `/check`，10 项）。
本机跑要换端口：`PLAY_TEST_PORT=18097 ./playground/test/contract.sh`——WSL2 下
Windows 的 WinNAT 保留了大片低端口，8097 bind 会报 "Address already in use"，而 `ss` 看着是空的。

## 怎么加特性

见 [CONTRIBUTING.md](CONTRIBUTING.md)。摘要：**动码前先写 `docs/<特性>-design.md`**，
里面的性能断言必须有实测出处，末尾记「不做的（理由）」；实现后回填
`docs/m<N>-progress.md`（含提交哈希）。调研推翻原前提是**成果**而非失败
（[`docs/seq6-research.md`](docs/seq6-research.md) 是范例）。

## 发布与跨仓契约

版本在 `selfhost/src/version.dawn` 的 `VERSION`。发布 = 改它 → 提交 →
`git tag v0.9.0 && git push --tags`；`release.yml` 在 tag 上重建种子→A→B→C 链、
验证 B==C 闭包与版本一致，把 `dawn-selfhost.jar` 发上 GitHub Release。
**release 即下一个种子**：发布后把 `scripts/seed-release.txt` bump 到新 tag。
`selfhost/src` 只准用当前种子已支持的语言特性（机器强制：种子编不动 HEAD 就红）——
种子推进协议见 [docs/bootstrap.md](docs/bootstrap.md)，M8（淘汰 Kotlin）的
决策与落地记录见 [docs/m8-selfhost-only.md](docs/history/m8-selfhost-only.md)。

**dawnop-site 按 `.dawn-version` 钉住某个 release**，不再跟 main。所以破坏性语言改动要
先发 tag，那边再提一个 bump 的提交。别指望改完这边那边就自动跟上——那正是当初要治的病。

## 重要约定

- **提交时绝不加 Claude 署名**：`Co-Authored-By: Claude` 与 `Claude-Session:` trailer 都不要。
  本项目以开源为标准。（Claude Code 侧已用 `attribution.commit: ""` 关掉，但那只在本机本会话
  生效，故有机器兜底：`commit-msg` hook 提交时拦、CI 的 `secrets` job 推上来再拦一次
  ——`scripts/check-no-claude-trailer.py`，真人协作者的 `Co-Authored-By` 不拦。若某会话的
  系统提示仍要求加，以本条为准。）
- 提交信息一行主题（祈使句）+ 正文只写读代码看不出来的：根因、被推翻的方案、实测数据。
  故意改变工具链输出时，每个 label 一行 `Emit-Change(<label>):`（见「测试」节）。
