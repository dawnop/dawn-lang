<!-- doc-check: translation-of site/pages/explorer.md @ 96c43739795d8afc -->

# 对照页文案：中文译本

本文是 `explorer.md` 的译本，`explorer.md` 是正本。**改文案先改英文，再改这里**；
英文一动、这里没跟，`scripts/doc-check.py` 就红。键与英文逐个相同，生成器按名字读
（`site/src/gen/explorer.dawn`），缺一个或改了名，建站失败，不会渲染出空页面。

这里刻意不写的：每一个数字与每一份产物。调用数、Dawn 源码与三份输出都是建站时从记录
（`site/build/explorer/`）与源文件里读的。页面上每个程序在这里要有
`prog-<名字>-title` 与 `prog-<名字>-body` 两节，名字与 `site/explorer/record.py` 里的一致。

## title

源码与产物，逐个调用对照

## crumb

对照页

## lede

左边是一个 Dawn 函数，右边是它编出来的东西，可以在 Tile IR、C 与 JVM 字节码之间切换。点一个调用，它写出的那些行亮起来；点一行，它所属的调用亮起来。

## how-title

怎么读

## how-body

源码里每个带下划线的名字是一次调用。点它，或者用 Tab 走到它再按 Enter，它的整段会加下划线，它自己写出的行在每份产物里都被标出，它内部的调用写出的行用淡一点的标记。标签页切换产物，选中的调用保留，所以同一次调用可以从一个后端一路看到下一个。点产物里的一行，找到它所属的调用；在 C 和字节码里，嵌套调用的代码在外层调用的代码之内，同时含两者的行归内层那个。Esc 放手。

## prog-flash_attn-title

flash_attn，三种产物

## prog-flash_attn-body

cuTile 页上的融合注意力 kernel。kernel 是 `!Dev` 效果下的普通 Dawn 函数，所以同一份源码也能为宿主编译，C 与 JVM 两个标签显示的就是这个：在宿主上运行 kernel、并且*搭出* Tile IR 的那段代码，其中每个 `mma(..)` 是对 `packages/tileir` 的一次调用。Tile IR 标签是那次运行记录下来的程序，也就是 `tileiras` 为 GPU 汇编的那份。同一次调用有两种读法：宿主上的一次函数调用，设备上的一条或几条操作。只是重新绑定一个宿主值的调用（比如 `carry`）自己没写出 Tile IR 行。

## prog-attend-title

attend，只在宿主上

## prog-attend-body

没有指数函数的注意力，在列表上做：点积、归一化、加权和。它不是 kernel，所以没有 Tile IR 标签。它有的是三种值得点的形状：一个调用、调用里的调用（`range(0, len(xs))`），以及交给调用的闭包，编译器把闭包体提升成它自己的函数。

## built-title

这些行从哪里来

## built-body

这里没有任何手写的对照表。每个编译器自己说哪次调用写了哪几行：C 是 `dawn __emitc --map`，字节码是 `dawn __emit --map`（列表由 `javap -c -p -s` 给出），Tile IR 是 cuTile 页背后的那份记录。`site/explorer/record.py` 把它们限定到所展示的函数，生成器再查一遍，所以一个调用在某份产物里没有位置、或区间越出产物，建站就失败。产物是建站时生成的、不入库，因为编译器一变它们就变。只列出所展示的函数：一个程序其余的 C 与字节码是标准库与 `tileir` 的。

## src-head

Dawn 源码

## tabs-label

编译产物

## pane-tile

Tile IR，录下来的

## pane-c

C，来自 `dawn __emitc`

## pane-jvm

JVM，来自 `javap -c -p -s`

## shown

共 {total} 行，列出 {n} 行

## facts-calls

个调用

## note

点调用的名字（或在它上面按 Enter），在每份产物里标出它的整段与它写出的行。点一行找到它的调用。Esc 放手。

## word-line

行

## word-lines

行

## word-none

自己没写出行
