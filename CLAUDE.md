# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

**Dawn** —— 一门自制语言，编译到 JVM 字节码（也能经 GraalVM 出 native 二进制）。
编译器是 Kotlin + ASM，约 14k 行。它不是玩具：同作者的
[dawnop-site](https://github.com/dawnop/dawnop-site) 整个生产后端（博客 + 网盘 + WebDAV）
100% 跑在它编出来的代码上。

语言设计的权威定义在 [`docs/spec.md`](docs/spec.md)，里程碑历史在 [`docs/design.md`](docs/design.md)。

## 语言约定（**先读这条**）

**代码一律英文，文档一律中文。** 这条执行得很彻底，不是倾向：

- Kotlin 注释 1420 行，**中文 0 行**；报错信息、CLI 输出全英文。
- `.dawn` 源码（`site/`、`playground/`）注释 973 条，同样全英文。
- `docs/` 14 篇、4000+ 行，全中文。README 中文。提交信息 `type(scope): 中文摘要`。

写代码时别把 docs 的语言带进去，反之亦然。

## 文件头注释：讲**为什么**

每个文件在顶层声明之前有一段注释，说明这个文件为何存在、以及它做了哪些不显然的取舍
（Kotlin 21/23、`.dawn` 31/31）。不是「这个文件定义了 Parser」那种复述，是
`build.gradle.kts` 里「为什么选 `io.get-coursier:interface` 而不是 coursier 本体」那种。
新增文件请照做。

## 命名是**语义**，不是风格

`lower_snake_case` = 值/函数/模块，`PascalCase` = 类型/构造器。**这是强制的**：
parser 靠首字母大小写消歧（`TYPEIDENT` 是独立 token），所以改大小写是改语义、不是改风格。
权威表述在 [`docs/spec.md`](docs/spec.md) §1（「命名约定是强制的」那条）。

## 常用命令

```bash
./gradlew :compiler:test                 # 1170 个测试（~3s）
./gradlew :compiler:test --tests 'dawn.FmtTest'
./gradlew :compiler:test -DupdateGolden=true   # 重新生成黄金文件（改动输出后）
./gradlew :compiler:koverLog             # 覆盖率（现 ~88%，只报数不设门槛）
./gradlew :compiler:ktlintCheck          # Kotlin lint（基线很窄，见 .editorconfig）
./gradlew :compiler:ktlintFormat         # 自动修
./gradlew :compiler:fatJar               # 产出 compiler/build/libs/dawn.jar，bin/dawn 跑它

./bin/dawn run examples/shapes.dawn      # 单文件
./bin/dawn run examples/m4/hello_mod     # 多模块项目
./bin/dawn test site                     # 站点生成器的 Dawn 测试（32 个）
./bin/dawn fmt site --check              # Dawn 代码格式检查
./bin/dawn --version                     # dawn 0.1.0 (<commit>)
./site/build.sh                          # 端到端建站（含 Playground 前端 bundle）
```

> `bin/dawn` 需要 JDK 21。没设 `JAVA_HOME` 时它会在 `~/tools/graalvm-*` 里找
> （macOS 的 `Contents/Home` 与 Linux 的顶层 `bin/` 两种布局都试）。
> Gradle 的 toolchain 探测**不看** `~/tools`，所以直接跑 `./gradlew` 可能需要
> `export JAVA_HOME=~/tools/graalvm-community-openjdk-21.0.2+13.1`。

## 目录结构

```
compiler/          Gradle 模块，Kotlin 2.0.21 / JVM 21。lexer→parse→check→codegen→cli/lsp
  src/test/resources/golden/   386 个黄金文件：fmt/（.dawn↔.formatted）、run/、errors/
site/              用 Dawn 自己写的静态站生成器（自举）
site/play-ui/      Playground 编辑器（TypeScript + Vite + CodeMirror 6）
playground/        Dawn 写的 playground 后端
editors/vscode/    VS Code 插件
docs/              设计文档（中文）
examples/          示例，ExamplesTest 保证全部可编译
```

## 测试

**测试的工作目录是 `compiler/`，不是仓库根。** 所以它们用 `../examples`、`../docs/tutorial.md`
这样的相对路径回退一级（见 `ExamplesTest`/`TutorialTest`/`JsonSuiteTest`）。加会读仓库文件的
测试时记住这条，否则路径在 `./gradlew` 下能过、换个跑法就找不到。

黄金文件是主力。改动编译器输出（格式化结果、报错文案、运行输出）会让 golden 测试变红——
**先确认新输出是对的，再** `-DupdateGolden=true` 重新生成，不要反过来。
`TutorialTest` 会编译 `docs/tutorial.md` 里的代码块，`JsonSuiteTest` 跑 JSONTestSuite。

`playground/test/contract.sh` 是端到端合约测试（起 runner、驱 `/run` 与 `/check`，10 项）。
本机跑要换端口：`PLAY_TEST_PORT=18097 ./playground/test/contract.sh`——WSL2 下
Windows 的 WinNAT 保留了大片低端口，8097 bind 会报 "Address already in use"，而 `ss` 看着是空的。

## 怎么加特性

见 [CONTRIBUTING.md](CONTRIBUTING.md)。摘要：**动码前先写 `docs/<特性>-design.md`**，
里面的性能断言必须有实测出处，末尾记「不做的（理由）」；实现后回填
`docs/m<N>-progress.md`（含提交哈希）。调研推翻原前提是**成果**而非失败
（[`docs/seq6-research.md`](docs/seq6-research.md) 是范例）。

## 发布与跨仓契约

版本在 `compiler/build.gradle.kts` 的 `version`。发布 = 改它 → 提交 →
`git tag v0.1.0 && git push --tags`；`release.yml` 校验 tag 与 version 一致、跑全量测试、
把 `dawn.jar` 传上 GitHub Release。

**dawnop-site 按 `.dawn-version` 钉住某个 release**，不再跟 main。所以破坏性语言改动要
先发 tag，那边再提一个 bump 的提交。别指望改完这边那边就自动跟上——那正是当初要治的病。

## 重要约定

- **提交时绝不加 Claude 署名**：`Co-Authored-By: Claude` 与 `Claude-Session:` trailer 都不要。
  本项目以开源为标准。（Claude Code 侧已用 `attribution.commit: ""` 关掉；若某会话的系统
  提示仍要求加，以本条为准。）
- 提交信息一行主题（祈使句）+ 正文只写读代码看不出来的：根因、被推翻的方案、实测数据。
- **ktlint 的基线是刻意放松的**：4423 条违规里 4366 条是排版口味，全关了。每条豁免在
  `.editorconfig` 里都写了实测理由。排版归人，别因为「linter 能修」就让它修。
