<!-- doc-check: translation-of site/pages/home.md @ 9f2e8afda852d89c -->

# 首页文案 —— 中文译本

本文是 `home.md` 的译本，`home.md` 是正本。**改文案先改英文，再改这里**；
上面那行标记记着正本的摘要，英文动了而这里没跟，`scripts/doc-check.py` 会红。

小节的含义与顺序见 `home.md` 的开头，那里也写了文案为什么从
`site/src/gen/pages.dawn` 搬进内容文件。

## eyebrow

type · match · effect · !io

## lede

一门小而优雅的函数式语言：不可变数据、代数数据类型与穷尽的模式匹配、把效果写进类型签名。编译器已自举，两个平级后端——JVM 字节码与 C——在同一份源码上给出同一个答案；这件事由门禁管着，不是一句承诺。

## cta-primary

开始教程 →

## cta-secondary

看示例

## features-title

核心特性

## feature-effects-title

效果进类型

## feature-effects-body

函数默认是纯的，碰 IO 必须在签名标 `!io`——看签名即知它碰不碰外界，纯函数测试零 mock。第二条轴是你自己声明的**具名效果**：`effect` 声明操作、`with handle` 就地应答，标签随签名传播，只在 handle 这一个语法节点上被减掉。臂默认是尾恢复的；声明为 `ctl` 的效果还可以带控制臂（`op(x) resume k => ...`），它绑定延续而不是恢复延续，稍后再恢复一次，恢复两次不支持。这一档有规范、两个后端都实现了、也有测试，而且**内部使用者就在本仓**：标准库的 `std/io` 声明了 `Fs`，把文件系统做成具名效果，生产 handler 是 `with_fs_real`，还声明了 `Proc`，把「跑另一个程序」做成一个操作，生产 handler 是 `with_proc_real`；`std/gpu` 跟着声明了 `Gpu`，设备的宿主侧，测试里由一个纯的假设备应答。编译器自己就跑在这一档上：它的 `main` 把整个 dispatch 包在 `with_fs_real` 里，于是工具链读写的每个文件都过 `Fs`。

## feature-comptime-title

编译期求值：comptime

## feature-comptime-body

`comptime { ... }` 在编译期由解释器执行，结果直接烧进常量池。没有宏系统，也不需要——普通函数就能在编译期跑。

## feature-parity-title

两个后端，一个答案

## feature-parity-body

JVM 字节码与 C（再交给 `cc`）是**平级**的两条路。最容易分叉的地方语言自己拥有：`Float` 渲染是纯 Dawn 的 Schubfach、Unicode 大小写表是编译器的、`Map` 迭代顺序按插入定死。整套差分语料每次 push 两边编两边跑，比 stdout、stderr、退出码——分歧会红灯。

## closing

从[教程](zh/tutorial/index.html)开始上手；语言细节的权威定义在[规范](zh/spec.html)；[示例](zh/examples/index.html)都能直接 `dawn run`；标准库 API 参考见[标准库](zh/stdlib.html)；每个设计取舍的「为什么」写在[设计笔记](zh/design.html)。

本站每一页都有中英两版。规范与设计笔记是其中唯一**先写中文再翻译**的一对：它们是活文档，每次改语言都在中文里改，所以中文是正本、英文按它登记——两者一脱节 `scripts/doc-check.py` 就红。`docs/` 其余部分是设计方案与计划，读者是作者本人，仍然只有一种语言。代码、编译器诊断与标准库文档注释则一律英文——标准库页上那些条目正文也在其内，它们是编译器自己的文本。
