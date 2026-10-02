<!-- doc-check: translation-of site/pages/gpu.md @ 78f4ed84b8d826cd -->

# cuTile 后端页文案 —— 中文译本

本文是 `gpu.md` 的译本，`gpu.md` 是正本。**改文案先改英文，再改这里**；
上面那行标记记着正本的摘要。

小节的含义与顺序见 `gpu.md` 的开头，那里也写了哪些东西故意不在这里：所有数字
（覆盖计数、golden kernel 数与设备台账都在建站时从 `scripts/` 读），以及本身就是
代码的词（`!Dev`、`tileiras`、文件名、台账里的结果状态），它们留在生成器里。

## title

Dawn 的 cuTile 后端

## lede

Dawn 里的 GPU kernel 是一个带 `!Dev` 效果的普通函数。运行它会记下它发出的操作；记录变成 CUDA Tile IR，再由 NVIDIA 的 `tileiras` 汇编成 cubin。本页每个数字都是建站时从仓库里的表读出来的。

## layers-title

两层，两个效果

## layers-body

持有缓冲区的程序与在缓冲区上计算的 kernel，写在两个不同的库之上，各有各的效果。两者只在一处相遇：宿主按名字 launch 一个 kernel。

## layer-host

宿主

## layer-host-body

`std/gpu` 声明 `Gpu` 效果：分配、上传、launch、下载。`with_gpu_real` 由 CUDA driver 应答，仅限 native 后端。`with_gpu_fake` 由宿主内存应答，每个 kernel 配一个参考函数，所以 `!Gpu` 程序能在没有 GPU 的机器上运行，也能在那里测试。

## layer-device

设备

## layer-device-body

`packages/tileir` 声明 `Dev` 效果。记录 handler 把 kernel 的一次运行变成一个 Tile IR 程序，打印成文本或编码成字节码；`tileiras` 再把字节码汇编给某一种 GPU 架构。

## kernel-title

一个 kernel，两面

## kernel-body

左边是 `scripts/tile-golden/kernels.dawn` 定义的 `vadd`。右边是它的 trace 要对上的 golden：记录 handler 为它写出的 Tile IR，逐字符一致。块索引与 lane 偏移、按 token 顺序的两次 load 与一次 store、夹在中间的加法，在右边各占一两行。

## kernel-left

Dawn 源码

## kernel-right

golden Tile IR

## coverage-title

后端覆盖了什么

## coverage-body

三张表为本后端所对的 Tile IR 版本里每个公开 opcode、每个类型标签、每个属性取值各记一行，写明状态与证据。一道门禁把每张表与字节码写出器双向对齐：表里不能声称写出器不会发出的操作，写出器新会发的操作没有对应行也是红灯。

## fig-opcodes

个公开 opcode 已实现

## fig-types

个类型标签已实现

## fig-attrs

个属性取值已实现

## fig-golden

个 golden kernel，文本与字节码各钉一份

## gates-title

三道门禁

## gates-body

每一层都抓下面那层抓不到的东西。每一层也各带一组写出器或 handler 的变异体，与它并排跑，而且必须把它们判红：一层在自己的变异体下还是绿的，和一层坏掉了还是绿的，原因是同一个。

## gate-0-title

文本与字节

## gate-0-body

每个 golden kernel 都 trace 两遍，一遍渲染成 Tile IR 文本，一遍编码成字节码，两者都与记录下来的文件逐字节比对。这一层说得出记录 handler、渲染器或写出器有没有变，说不出它们写的对不对。

## gate-1-title

汇编器接受

## gate-1-body

每次碰到 tile 路径的 push，所有字节码 golden 都过一遍 `tileiras`。判据是退出码为零、标准错误上没有 error 行，且产出的 cubin 符号表里有这个 kernel。这一层抓得住编码错误、类型错误与不支持的操作，抓不住算错的答案。

## gate-2-title

设备点头

## gate-2-body

在有 GPU 的机器上 launch 这些 kernel，每个输出缓冲区都与宿主参考比对：操作精确的 kernel 逐位一致，用到设备近似运算的 kernel 在写明的容差内。每次运行往那台机器的台账追加一行；tile 输入与台账最后一行测过的不同的源码树，CI 不放行。

## ledger-title

在真硬件上

## ledger-body

每台机器台账的最后一行，照运行时的记录原样列出。第一台是仓库自己的机器，也是 CI 读的那一台。另两台是集群机器，它们换来的是 Ampere 卡加载不了的 fp8、fp4 与 block-scaled 那几行。

## ledger-tiers

两列数字是按档比对过的 kernel 数，对该行注释里的各族求和。

## th-gpu

GPU

## th-date

日期

## th-driver

驱动

## th-tileiras

tileiras

## th-result

结果

## th-exact

逐位一致

## th-tolerance

容差内

## th-tree

源码树


## chip-golden

个 golden kernel

## chip-gpus

块 GPU 有台账
