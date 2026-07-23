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
- `docs/` 14 篇、4000+ 行，全中文。README 中文。提交信息 `type(scope): 中文摘要`。

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
./bin/dawn run examples/shapes.dawn      # 单文件
./bin/dawn run examples/m4/hello_mod     # 多模块项目
./bin/dawn test site                     # 站点生成器的 Dawn 测试
./bin/dawn fmt site selfhost packages --check   # Dawn 代码格式检查
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
std/               捆绑标准库源（--embed-std 嵌进独立 jar）
packages/          源码包（json、web），[deps] 消费
site/              用 Dawn 自己写的静态站生成器（自举）
site/play-ui/      Playground 编辑器（TypeScript + Vite + CodeMirror 6）
playground/        Dawn 写的 playground 后端
editors/vscode/    VS Code 插件
docs/              设计文档（中文）
examples/          示例
```

Kotlin 实现（compiler/，1170 项测试、386 个黄金文件）已随 `kotlin-final` tag
整体归档——考古看那个 tag，别在 main 找。

## 测试

`./bin/dawn test selfhost` 跑编译器自身的 test 块（就写在 `selfhost/src/` 源文件里）。
输出层面的回归由**差分**守护：`selfhost-prev-diff.sh`（emit 语料逐字节 vs 上一
release）、`selfhost-run-diff.sh`（CLI 转写）、`selfhost-fmt-diff.sh`（格式化）、
`selfhost-lsp-diff.sh`（LSP 会话）。**故意改变输出**（报错文案、格式化结果、CLI
文本）时，提交信息里写一行 `Emit-Change: <说明>`——没有声明的字节差异 CI 红灯。

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
决策与落地记录见 [docs/m8-selfhost-only.md](docs/m8-selfhost-only.md)。

**dawnop-site 按 `.dawn-version` 钉住某个 release**，不再跟 main。所以破坏性语言改动要
先发 tag，那边再提一个 bump 的提交。别指望改完这边那边就自动跟上——那正是当初要治的病。

## 重要约定

- **提交时绝不加 Claude 署名**：`Co-Authored-By: Claude` 与 `Claude-Session:` trailer 都不要。
  本项目以开源为标准。（Claude Code 侧已用 `attribution.commit: ""` 关掉，但那只在本机本会话
  生效，故有机器兜底：`commit-msg` hook 提交时拦、CI 的 `secrets` job 推上来再拦一次
  ——`scripts/check-no-claude-trailer.py`，真人协作者的 `Co-Authored-By` 不拦。若某会话的
  系统提示仍要求加，以本条为准。）
- 提交信息一行主题（祈使句）+ 正文只写读代码看不出来的：根因、被推翻的方案、实测数据。
  故意改变工具链输出时加 `Emit-Change:` 行（见「测试」节）。
