<!-- doc-check: translation-of site/pages/gpu.md @ 411078f7472d4f21 -->

# cuTile 后端页文案 —— 中文译本

本文是 `gpu.md` 的译本，`gpu.md` 是正本。**改文案先改英文，再改这里**；
上面那行标记记着正本的摘要。

小节的含义与顺序见 `gpu.md` 的开头，那里也写了哪些东西故意不在这里：所有数字
（覆盖计数、golden kernel 数与设备台账都在建站时从 `scripts/` 读），以及本身就是
代码的词（`!Dev`、`tileiras`、文件名、台账里的结果状态），它们留在生成器里。
句中带数字的地方用 `{n}`、`{total}` 占位，由生成器填入。

## title

Dawn 的 cuTile 后端

## lede

Dawn 里的 GPU kernel 是一个带 `!Dev` 效果的普通函数。运行一次，它发出的每个操作都被记录成 CUDA Tile IR，再由 NVIDIA 的 `tileiras` 汇编成 cubin。

## layers-title

两层，两个效果

## layers-body

宿主持有缓冲区，设备在上面计算；两者只在宿主按名字启动 kernel 的那一处相遇。

## layer-host

宿主

## layer-host-body

`std/gpu` 的 `Gpu` 效果：分配、上传、启动、下载。`with_gpu_real` 驱动 CUDA driver，`with_gpu_fake` 不需要 GPU 也能跑同一个程序。

## layer-device

设备

## layer-device-body

`packages/tileir` 的 `Dev` 效果。kernel 被记录的一次运行，变成 Tile IR 文本，或交给 `tileiras` 的字节码。

## api-title

写一个 kernel

## api-body

kernel 在参数标记上一次说清它读哪里、写哪里，凡是能从操作数读出的形状一概不写。下面每段代码都在建站时从 golden kernel 里切出来。

## api-learn

学着写一个

## api-cells-title

标记就是寻址

## api-cells

`In` 与 `Out` 把每个张量切成格子，`Out` 的格子就是 launch 的网格。函数体读本块的格子、写本块的格子，不写任何偏移。

## api-shapes-title

形状从操作数来

## api-shapes

没有一个操作收形状或格式。常量、以及对一维 tile 的归约，都是 0 秩 tile：遇到更宽的操作数时自己加宽，别处一律不加宽。

## api-out-title

写只经 `Out`

## api-out

`Out` 只接受 `store_cell` 与 `store_sub` 两种写，累加器从它的 `zeros` 起步。`FREE_AXIS` 把一维留给 kernel 自己挑，这里是循环的 `k`。

## api-shared-title

`Shared` 是逃生口

## api-shared

原子操作不是格子写，地址由数据决定的 scatter、一块写两个区域也不是。它们经 `Shared` 写，标记把这件事写在读者找得到的地方。

## api-keepdims-title

保维归约

## api-keepdims

`keepdims: true` 把每一行归约成长度为 1 的一列；这一列和整行同阶，遇到整行时自己展回去。这两行就是下面那个注意力 kernel 的行统计；点进去，看它写出的 Tile IR。

## api-keepdims-go

在图里看 ↓

## show-refused-title

录制时被拒

## show-refused

kernel 在录制时就被检查：函数体只跑一遍，某个运算的形状或角色撑不起来，就是一次 panic，里面写着 kernel 名、运算的编号和照写法显示的运算符。它发生在 `tileiras` 之前、任何设备之前，指出的是运算符，不是你源码里的某一行。

## show-host-title

在宿主上运行，不需要 GPU

## show-host

单用假设备时，一次 launch 只会去调注册在 kernel 名下的宿主参考实现。`with_gpu_interp` 改为按每次 launch 给出的 grid 去运行录下来的 Tile IR，所以同一段宿主程序在没有显卡的机器上也能从 trace 走到结果。结果出自解释器，由 CI 对着宿主参考实现把关，不是由 GPU 把关。

## show-open

在 Playground 中运行

## api-occupancy

在 `sm_86` 上，128×128 的 f16 矩阵乘要带 `entry_hints(occupancy = Some(2))`：每个 SM 放得下两块，而不是一块。

## api-surface

这个包的完整公开面

## api-changes

0.9.0 改了什么

## api-measured

怎么测的。

## kernel-title

一个 kernel，逐行对照

## kernel-body

一个融合注意力 kernel（也就是上面那两行行统计的出处），和它的调用写出的 Tile IR 并排放着。配对来自记录本身和 Dawn 自己的解析器，不来自手写的对照表；调用名和它写出的行是同一种颜色。在 Playground 里还能把同一个函数和它编出来的 C 与 JVM 字节码并排看。

## kernel-open

在 Playground 中打开

## kernel-kind

一个循环，里面两次归约

## kernel-left

Dawn 源码

## kernel-right

它记录下的 Tile IR

## kernel-note

点一个调用名，会标出它的整段源码和它写出的 Tile IR。点一行 Tile IR，可以找到写出它的调用。Escape 取消。

## word-line

行

## word-lines

行

## word-none

没有自己的行

## fact-calls

个调用

## fact-ops

个操作

## fact-lines

行 Tile IR

## fact-bytes

字节

## fact-rows

被 {n} 条覆盖记录引用

## fact-mutants

{n} 个变异体

## coverage-title

后端覆盖了什么

## coverage-body

Tile IR 版本里每个公开 opcode、类型 tag 和属性值都有一行，记着状态和证据。指向卡片可以看到还没实现的那几行。

## fig-opcodes

个公开 opcode 已实现

## fig-types

个类型 tag 已实现

## fig-attrs

个属性值已实现

## fig-golden

个 golden kernel，每个都以文本和字节码两种形式钉住

## gates-title

三道门

## gates-body

每一层都抓得到前一层抓不到的问题，而且每一层都必须让自己的变异体变红。每个点是其中一个，落在它所针对的那一道门。

## gates-caught

个变异体在这里被抓住

## gate-0-title

文本与字节

## gate-0-body

每个 golden kernel 都被 trace 两次，与记录下的文本和字节码逐字节比对。它只说明有没有变化，不说明对不对。

## gate-1-title

汇编器接受

## gate-1-body

`tileiras` 必须把每个字节码 golden 汇编成带有该 kernel 名字的 cubin。它抓编码错误和类型错误，抓不到算错的答案。

## gate-2-title

设备一致

## gate-2-body

在有 GPU 的机器上，每个输出缓冲区都与宿主参考比对，逐位一致或在声明的容差内。每次运行在台账追加一行，CI 拒绝最后一行没测过的源码树。

## ledger-title

在真实硬件上

## ledger-body

每台机器台账的最后一行。CI 读第一行；sm_90 与 sm_100 两本覆盖了 Ampere 卡加载不了的 fp8、fp4 与 block-scaled 那几行。

## ledger-tiers

按档位统计比对过的 kernel 数，对该行涉及的各族求和。

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

块 GPU 有记录


## perf-title

Flash attention 测时

## perf-body

按 `(arch, d)` 离线选配置，在同一进程、同一流内用 CUDA events 交错测五轮。时间为毫秒，中位数 / p90。基线是 64×64、无 entry hint；bf16 用 f32 累加、f64 输出，f64 调优后用 32×16。cuTile 是上游 bf16 attention 样例四个实测配置的最快格；SDPA 采用所在行的 bf16 或 f64 格式。cuTile 输出 bf16，Dawn 输出 f64。f64 行没有对应的 cuTile 样例。[配置台账](https://github.com/dawnop/dawn-lang/blob/main/scripts/flash-config/ledger.json) 保留选表证据，包括未入表的 sm_100 d64 单头候选。配置在录制前固定，不做运行期搜索。

## perf-format

格式

## perf-workload

负载

## perf-tools

tileiras / 优化级别

## perf-config

配置

## perf-before

改前

## perf-after

改后

## perf-cutile

cuTile 1.7.0

## perf-sdpa

torch SDPA
