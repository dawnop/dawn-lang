# Playground 内建补全的原生生成入口

> 状态：**current**。已实现；范围仅为补全表的构建输入。

## 问题与调用链

`npm run build`、`npm run dev`、`npm test` 的 pre hook 都在
`site/play-ui` 执行 `npm run gen-builtins`。整站 `site/build.sh` 先回到仓库根，
再进入该目录运行 npm build，因此最后走同一个 JS 入口。
从仓库根直接执行该 JS 时，入口原先也靠自身位置定位仓库。

原入口优先读取 `site/build/builtins.json`，但当前树没有该文件的生产者，
旧文件也没有来源校验。文件不存在时启动 `bin/dawn doc --builtins`，
独立 npm 与整站构建因而都增加一条 JVM 依赖。

## 方案与落点

生成器从仓库根通过固定的 Bash 文本加载 `site/dawnc.sh`，调用 `site_dawnc`。
返回路径按仓库根解析，再用 argv 执行 `doc --builtins`，用户路径不进入 shell 文本。
`DAWNC_BIN` 优先，否则复用现有 HEAD 构建与缓存规则。
每次生成都读取工具的 JSON，不再消费 `builtins.json`。
工具失败或 JSON 非法直接失败；读取、解析和表转换完成前不写 TS。
补全排序、分组、文档截断、模块限定及 internal 过滤保持原样。

npm test 已加入独立的进程夹具，只检查入口、cwd、空格与 shell 特殊字符路径、
陈旧输入、更新输入及失败行为。内容 oracle 继续由
`scripts/native-cli-diff.sh` 的同树 JVM/native doc 对拍与编辑器 selftest 提供。
验收另将两份真实 JSON 交给实际生成器比较 TS，并恢复旧脚本证明路径断言会红。
不预设性能收益，生成阶段计时与首次构建 dawnc 分开记录。

## 不做的（理由）

不增加 JSON 缓存或另一套编译器缓存，避免重复定义新鲜度。
不改前端、编译器、包版本、workflow 或整站构建顺序。
`packages/web-jvm` 的文档继续走 JVM；首次构建 dawnc 仍可能由 JVM 种子链发 C，
这些路径不属于本次补全生成入口的原生执行断言。
