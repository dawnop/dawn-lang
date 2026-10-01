<!-- doc-check: translation-of site/pages/home.md @ 2645ceef329b9f4c -->

# 首页文案 —— 中文译本

本文是 `home.md` 的译本，`home.md` 是正本。**改文案先改英文，再改这里**；
上面那行标记记着正本的摘要，英文动了而这里没跟，`scripts/doc-check.py` 会红。

小节的含义与顺序见 `home.md` 的开头，那里也写了文案为什么从生成器搬进内容文件、
哪些东西故意不在这里（程序与输出、数字、本身就是代码的词）。

## phase-hero

**−18°** 天文晨光

## eyebrow

type · match · effect · !io

## lede

一门小而优雅的函数式语言：不可变数据、代数数据类型与穷尽匹配、写进类型签名的效果。

## fact-selfhost

编译器已自举

## fact-backends

JVM 与 C，同一个答案

## fact-gpu

cuTile 上 NVIDIA GPU

## cta-playground

在 Playground 里试试 →

## cta-primary

开始教程

## theme-to-dark

切换到深色主题

## theme-to-light

切换到浅色主题

## phase-ideas

**−12°** 航海晨光 · 三个概念

## ideas-title

签名告诉你的事。

## ideas-lede

函数碰了什么、提前算了什么、匹配了什么，都由编译器检查。

## idea-effects-title

效果进类型

## idea-effects-body

默认是纯的：碰 IO 要标 `!io`，自己声明的效果由 `with handle` 应答。

## idea-comptime-title

编译期求值

## idea-comptime-body

`comptime { ... }` 在编译期运行普通函数，结果烧进常量池。

## idea-data-title

数据与穷尽匹配

## idea-data-body

不可变的代数数据；漏了一种情况的 `match` 编译不过。

## phase-peers

**−6°** 民用晨光 · 两个后端

## peers-title

两条路，一个答案。

## peers-body

JVM 字节码与 C 是**平级**的两个后端。每次 push，差分语料在两边各跑一遍，输出有一处不同就构建失败。

## fig-native-corpus

差分语料里的程序数，每个都在两个后端上各跑一遍

## fig-push-value

每次 push

## fig-push

stdout、stderr 或退出码有一处不同就是红灯

## fig-selfhost-lines

自举编译器的 Dawn 源码行数

## fork-title

一份源码，两个后端，一个答案

## fork-desc

main.dawn 编译成 JVM 字节码，也另外编译成 C 再交给 cc。两个程序都跑，stdout、stderr 与退出码必须逐字节相同；有差异就是红灯。

## fork-jvm

跑在 JDK 21 上

## fork-c

一个原生二进制

## fork-compare

stdout · stderr · 退出码，逐字节

## fork-red

有差异就是红灯

## phase-gpu

**−3°** 破晓 · GPU

## gpu-title

kernel 也是 Dawn 函数。

## gpu-lede

cuTile kernel 是一个带具名效果的普通 Dawn 函数，降为 CUDA Tile IR。纯的假设备在没有 GPU 的机器上给出同一个答案。

## gpu-pipe

两边各自经历了什么

## lane-device

设备

## lane-host

宿主

## step-kernel

一个 Dawn 函数

## step-record

记下它发起的操作

## step-tileir

文本或字节码

## step-tileiras

汇编成 cubin

## step-launch

由 handler 应答

## step-real

CUDA driver，仅 native

## step-fake

宿主参考实现，纯的

## kernel-title

kernel

## kernel-body

运行它会记下它发起的操作；记录变成 Tile IR，再由 `tileiras` 汇编成 cubin。

## kernel-out

那次加法，取自 `dawn run` 为它打印的 Tile IR

## kernel-fact-title

在真硬件上核对

## kernel-fact-body

`tile-gpu-diff` 把每个 kernel 与宿主参考对拍；台账没覆盖到的改动 CI 会拦下。

## host-title

宿主程序

## host-body

`with_gpu_real` 由 CUDA driver 应答，`with_gpu_fake` 由宿主内存应答。

## host-out

同一次 `dawn run` 在 `with_gpu_fake` 下为它打印的那一行

## host-fact-native-title

只有 native 与 GPU 通话

## host-fact-native-body

只有 native 能到 `libcuda`；JVM 上真设备的 launch 会被拒绝。

## host-fact-pure-title

假设备是纯的

## host-fact-pure-body

所以 `!Gpu` 程序能在测试里跑，也能在 comptime 跑。

## phase-install

**0°** 日出 · 安装

## install-title

挑一条路，跑起来。

## install-lede

每个 release 都带两套工具链，各附 SHA-256。

## road-native

不需要 JVM

## road-native-tags

静态链接 · C 后端 · 内置 std

## road-jvm

用 JDK 21

## road-jvm-tags

任意平台 · JVM 后端 · 内置 std

## install-foot

[最新 release](https://github.com/dawnop/dawn-lang/releases/latest) · [教程第 1 章](zh/tutorial/01.html) · [规范](zh/spec.html) · [示例](zh/examples/index.html)
