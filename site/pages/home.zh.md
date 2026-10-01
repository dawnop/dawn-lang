<!-- doc-check: translation-of site/pages/home.md @ 94f11ff7f0ed7ff0 -->

# 首页文案 —— 中文译本

本文是 `home.md` 的译本，`home.md` 是正本。**改文案先改英文，再改这里**；
上面那行标记记着正本的摘要，英文动了而这里没跟，`scripts/doc-check.py` 会红。

小节的含义与顺序见 `home.md` 的开头，那里也写了文案为什么从
`site/src/gen/pages.dawn` 搬进内容文件。

## eyebrow

type · match · effect · !io

## lede

一门小而优雅的函数式语言：不可变数据、代数数据类型与穷尽的模式匹配、把效果写进类型签名。编译器已自举，两个平级后端（JVM 字节码与 C）在同一份源码上给出同一个答案；cuTile 设备后端把 kernel 带上 NVIDIA GPU，没有 GPU 的机器上由纯的假设备给出同一个答案。这一点由机器检查，不是一句承诺：每次 push 都让同一批程序在两个后端上各跑一遍，输出有一处不同就构建失败。

## cta-playground

在 Playground 里试试 →

## cta-primary

开始教程 →

## cta-secondary

看示例

## install

安装：从[最新 release](https://github.com/dawnop/dawn-lang/releases/latest) 下载 `dawnc`（一个静态二进制，不需要 JVM）或 `dawn-selfhost.jar`（需要 JDK 21）；[教程第 1 章](zh/tutorial/01.html)有完整步骤。

## features-title

核心特性

## feature-effects-title

效果进类型

## feature-effects-body

函数默认是纯的，碰 IO 必须在签名标 `!io`，看签名即知它碰不碰外界。第二条轴是你自己声明的**具名效果**：`effect` 声明操作，`with handle` 就地应答，标签随签名传播，在 handler 处被减掉。`ctl` 效果还可以带控制臂，它绑定延续而不是恢复延续，最多再恢复一次。两个后端都实现了这一档，而且**内部使用者就在本仓**：`std/io` 声明了 `Fs`、`Proc`、`Env`、`Exit` 与 `Console`，`std/gpu` 声明了 `Gpu`，生产 handler 就在声明旁边，测试里用假实现应答。编译器自己就跑在这一档上：它的 `main` 被 `Fs` 与 `Exit` 的 handler 包着，于是它读的每个文件、结束时的每个退出码都过一层效果。

## feature-comptime-title

编译期求值：comptime

## feature-comptime-body

`comptime { ... }` 在编译期由解释器执行，结果直接烧进常量池。没有宏系统，也不需要——普通函数就能在编译期跑。

## feature-parity-title

两个后端，一个答案

## feature-parity-body

JVM 字节码与 C（再交给 `cc`）是**平级**的两条路。最容易分叉的地方语言自己拥有：`Float` 渲染是纯 Dawn 的 Schubfach、Unicode 大小写表是编译器的、`Map` 迭代顺序按插入定死。整套差分语料每次 push 两边编两边跑，比 stdout、stderr、退出码——分歧会红灯。

## closing

从[教程](zh/tutorial/index.html)开始上手；语言细节的权威定义在[规范](zh/spec.html)；[示例](zh/examples/index.html)都能直接 `dawn run`；标准库 API 参考见[标准库](zh/stdlib.html)；[设计史](zh/design.html)是早期设计决定的历史记录，M7 时冻结。

本站每一页都有中英两版。规范与设计史以中文为正本、英文为译本；其余页面以英文为正本。代码、编译器诊断与标准库文档注释一律英文，标准库页上那些条目正文也在其内，它们是编译器自己的文本。
