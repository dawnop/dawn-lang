# 三后端对照页（Explorer）：源码在左，产物在右

> 状态：**proposed**（2026-10-07 起草，同日实现于分支 `feat/explorer-page`，待合入）。这是
> `docs/source-span-map-design.md` 的 M7。依赖：M1（GPU 页的 Tile IR 调用对照，
> `site/gpu-map/flash_attn.map`）、M2（Core 调用节点的 site）、M3（`__emitc --map`，第十二节）、
> M4（`__emit --map`，第十三节）。不依赖 M5、M6。

## 一、要什么，不要什么

站点上多一页 `explorer.html`（中文在 `zh/explorer.html`）：左边是 Dawn 源码，右边是同一段源码编出来的产物，
右栏用标签页在 **Tile IR / C / JVM** 之间切换。点源码里的一次调用，三个窗格里它写出的那几行同时高亮；
反过来点产物里的一行，回到写出它的那次调用。形态向 Compiler Explorer 看齐，但单位是「每个调用一个区间，
带嵌套」，比 CE 的「行 + 一个 token」细一档（调研报告 §6.3）。

不要的：

- **不在浏览器里编译。** 页面是建站时生成的静态页，不需要服务器。在线编译（Playground 接 `--map`）是后一步，
  见第九节。
- **不手写任何对照。** 三份产物各自的编译器说哪次调用写了哪几行，页面只读、只查，不猜。
- **不让缺口悄悄存在。** 表里没有某个调用、某个区间越出产物、某个名字不在它的区间里，都是建站失败，
  与 GPU 页和「终端屏不得出现 ANSI」那条检查同一种态度。

## 二、放哪些程序，为什么

**第一个：`flash_attn`。** GPU 页已经只放它（裁决：一个 kernel，一个循环里两次归约）。三栏都有：

- **Tile IR** 栏：M1 的记录，`site/gpu-map/flash_attn.map`，不变。
- **C 栏、JVM 栏**：`scripts/tile-golden/kernels.dawn` 本来就是一份可以被两个宿主后端编译的 Dawn 源码，
  `flash_attn` 是其中一个普通函数（`!Dev` 效果由 `packages/tileir` 的 `Dev` 处理器承接）。
  `jvm-map` 的检查已经按同样的办法把它编成 class。所以「同一份源码、三份产物」对它成立，不必另找宿主例子。
  但要在页面上讲明白：C 与 JVM 栏里是**搭建 Tile IR 的那段宿主代码**（每个 `mma(..)` 是一次对 `dev` 的调用），
  不是 GPU 上跑的东西；Tile IR 栏才是被记录下来的那份程序。这两种读法放在一起，恰是这个效果系统的卖点：
  同一次调用既是宿主里的一次函数调用，也是设备程序里的一条（或几条）op。

**第二个：`attend`**（`site/explorer/attend.dawn`，十几行的宿主程序：点积、归一化、加权和）。
它证明「再加一个程序只是一行表项」，也给没有 GPU 概念的读者一个不带 `!Dev` 的入口，只有 C 与 JVM 两栏
（它不是 kernel，没有 Tile IR）。不在 `attend` 上留 Tile 栏，页面也不画一个灰掉的标签：没有就是没有，
理由写在它的说明里。

页面上的程序是 `site/explorer/record.py` 里的一张表（`PROGRAMS`），一项一个程序：源码、要看的函数、
有没有 Tile 记录。加程序 = 加一项 + 在 `site/pages/explorer.md` 与译本里加两个键。

## 三、数据从哪里来，怎么流到页面

```
kernels.dawn / attend.dawn
   │  bin/dawn __emitc --map      bin/dawn __emit --map     site/gpu-map/flash_attn.map (M1，已入库)
   ▼                              ▼                          │
 .dawnmap (c)                  .dawnmap (jvm) + javap -c -p -s
   └───────────── site/explorer/record.py ───────────────────┘
                         │  只取目标函数；换算坐标；建调用表；校验
                         ▼
        site/build/explorer/<程序>.xmap  +  <程序>.{tile,c,jvm}.txt   （生成物，不入库）
                         │
                         ▼
        site/src/gen/explorer.dawn  读、再校验、写 explorer.html（+ explorer.js）
```

**为什么侧表与产物文本不入库，而每次建站现生成。** GPU 页的记录入库（`flash_attn.map`），因为它的来源
（`packages/tileir` 与 `kernels.dawn`）极少动。C 与 JVM 的产物是**编译器**的函数：`emitc`、`codegen`、
Perceus 的任何一次改动都会换掉页面上的文本（前几次提交就是例子）。入库就等于每次改编译器都要重录并提交一份
页面快照，漏了就是一页说谎的 C。所以它们走 `site/build/stdlib.json` 的老办法：`site/build.sh` 生成、不入库、
生成器读取并严查；`scripts/site-dist-diff.sh` 在快照里同样重生成，两条腿读同一份文件，
「生成器是磁盘文件的纯函数」这条仍然成立。代价是建站多一次编译（实测见第八节）。

**对照的粒度。** record.py 只取目标函数的产物：C 取 `fn` 行里 `origin` 是它的所有函数（它自己，加上从它提升出来的
lambda，在 C 文本里被放在文件另一处，页面里接在它后面）；JVM 取对应的方法块（javap 的一块）。其余（整份 C 有
七千到十五万行，其中是 std 与 tileir 的实现）一概不放，页面上用一句话和行数说明没放。

**调用的树按源码区间嵌套，不用 Tile 记录的 `parent`。** `flash_attn.map` 的 `parent` 是调用所在的区域
（`d_range` 的闭包里的调用，父是 `d_range`），`mul(mma(..), lit(..))` 里的 `mma` 父是区域而不是 `mul`。
读者说的「调用里的调用」是区间包含，C 与 JVM 里谁的代码在谁之内也由它决定，所以 record.py 把表按源码顺序重新编号、
父取区间最内层的包含者；Tile 栏的每个调用仍只拿它自己写的行，没有变。

**调用表（页面上的按钮）。** 有 Tile 记录的程序，表就是 `flash_attn.map` 的调用（37 个），
也就是「在设备程序里留下记录的调用」；没有 Tile 记录的程序，表是 C 与 JVM 两张侧表里目标函数内的调用的并集。
host 侧表里多出来的调用（`permute(..)`、`neg_inf()` 这类纯宿主值，Tile 记录看穿它们）不做按钮，只数一下写进说明。
**表里的每一个调用在每一栏都必须有出处**，没有就是 record.py 失败。

## 四、`.xmap` 第 1 版

record.py 写的、生成器读的，是同一种纯文本（空格分隔，坐标与 `flash_attn.map` 同一种写法：`行:列`，都从 1 起，
列按码点，区间右开）。三种后端各自的侧表格式只有 record.py 认识，生成器只认这一种：

```
xmap 1
program <名字>
source <路径> <首行> <末行>             页面显示源文件的哪几行（含）
call <id> <父id|-1> <名> <l:c-l:c> <l:c-l:c>   调用的整段，被调名的一段
pane <kind> <文件>                      kind 是 tile / c / jvm；文件在 .xmap 旁
out <kind> <id> <a-b>... [@行:c0-c1] [!行]
```

- `out` 的区间是该栏文本的行区间（从 1 起，右开）。每个调用在**每个栏**恰有一行 `out`。
  `-` 代替区间表示「它自己没写出行」：只有 Tile 栏允许（`carry`、`lit` 这类只改宿主绑定的调用，
  记录里就是空），C 与 JVM 栏里一个调用没有代码是 record.py 的错。
- 语义：`out` 列的是**这个调用自己**的行，不含嵌套调用的。Tile 栏天然如此（M1 的 `lines`）。
  C 栏取侧表的 `[first, line]` 再减去子调用的区间（`line` 始终保留，嵌在同一行的外层调用仍亮那一行）；
  JVM 栏取 `[pclo, pchi)` 内的指令行减去子调用的区间（`ipc` 那一行始终保留）。
- `@行:c0-c1`（只有 C 栏）：该调用在它自己的 C 行里占的列区间（0 起、字节、右开），嵌套的同行调用会画出嵌套的下划线。
- `!行`（只有 JVM 栏）：实现这次调用的那条 invoke 指令所在行，加粗；内建调用没有「那一条」，不写。
- 一个源码调用可以对应多个函数里的代码（lambda 提升后）；`out` 把它们的区间并起来。

## 五、点击怎么高亮，两个方向

约定「所有者」：窗格里的一行属于所有 `out` 区间含它的调用；C 与 JVM 里一行可以有多个所有者（一个嵌套调用的同行），
Tile 栏恰有一个或没有。

- **点源码里的调用名**（`<span role=button>`，虚线下划线）：源码里该调用的整段 `[from, to)` 加实线下划线；
  **每一个窗格**里它的行加强调色左边线与行号（`xp-hit`），其子孙调用的行加淡一档的边线（`xp-in`，
  Tile 栏里区域调用 `d_range` 的体内行就是这样）；C 栏里被 `@` 标出的列区间加下划线；JVM 栏里 `!` 那一行加粗。
  当前可见窗格滚到第一行命中（只滚窗格自己，不滚页面）。
- **点窗格里的一行**：选中它的**最内层所有者**（源码区间最小者）；没有所有者的行（C 的函数头、JVM 的 `descriptor:`、
  Tile IR 的 `module`）点了没反应。
- 再点一次、点别处，或按 Esc，放手。切换标签页保留选中，所以能一眼看出同一次调用在三个后端各写了什么。
- 状态行（`aria-live=polite`）写出结果：`mma · 3:28–3:31 → Tile IR 22–23`。

键盘：源码里的调用名是 Tab 序里的按钮，Enter/空格选中；窗格用 roving tabindex，Tab 进去落在第一条有所有者的行，
上下箭头在有所有者的行之间移动，Enter/空格选中，Home/End 到首尾；标签页按 ARIA tabs 的写法（左右箭头切换）。
没有脚本时：源码与全部窗格上下依次排开，内容完整，只是不能点（与 GPU 页一致）。

## 六、检查：缺口一律是建站失败

record.py（`python3 site/explorer/record.py`，站点 `build.sh` 里跑）：

1. 源码里每个表调用，在 C 侧表与 JVM 侧表里都找得到（按 `lo hi` 对）；找不到、`first`/`pc` 写 `-`、区间落在目标函数之外、
   JVM 的 pc 区间里没有指令，都失败并指名。
2. 被调名的一段：源文本在 `nlo` 起的标识符与记录的名字相同。
3. javap 的方法头与 `fn` 行的 `symbol`（名字加描述符）一一对上。
4. Tile 栏：`flash_attn.map` 的调用与表逐个相同，每个调用的行在黄金文件范围内。

生成器（`gen/explorer.dawn`，每次建站）再查一遍，不信 record.py：名字在名字区间上、区间在函数内与父区间内、
每栏恰一行 `out`、行号在文本内、`@` 的列在行内、Tile 栏每行至多一个所有者，写一个函数的 `Program` 才画。
违例是 `panic`，`dawn run site` 退出码非零。

**负控。** `site/explorer/record.py --self-test` 把一个侧表行的 `lo` 挪一位、把一个 `pchi` 挪出方法、
把一个调用名改掉，逐个要求红并说出原因；生成器的 `test` 块对 `.xmap` 做同样的事。
`./bin/dawn test site` 与 `record.py --self-test` 一起证明「这些检查红过」。

## 七、版式与无障碍

沿用站点的设计系统：配色全部取 `style.css` 里已有的变量（`--accent`、`--line`、`--surface`、`--muted`、`--faint`、
`--mono`），明暗两套；不加底色，用线与下划线（GPU 页同一条规矩）。

- 宽于 `44rem`（按图自己的宽度，容器查询，与 GPU 页同法）：两列，左边源码，右边标签页加窗格；窗格有最大高度，
  自己滚动。
- 窄于它（手机 375 px）：上下叠，源码在上，标签页在窗格上；窗格里每行不换行、窗格自己横向滚动，
  **页面不横向滚动**。
- 标签页是 `role=tablist`，按钮最小触控高度 2.5rem。
- 高亮不靠颜色单独承载：下划线、左边线、加粗，三种形状信息；颜色只是强调。
- `prefers-reduced-motion`：本页没有动画，无需特殊处理。

## 八、开销

实测于 2026-10-07，16 核 WSL2，另有其他写者在跑：

- `site/explorer/record.py`：17 至 20 s 墙钟（两个程序各编一次 C、一次 JVM，加 javap；`kernels.dawn` 那一份
  C 与 JVM 各约 6 s，`attend` 各约 2 s）。这是 `site/build.sh` 与 `site-dist-diff.sh` 各多出的时间。
  `--self-test` 3 至 10 s。
- 页面：`explorer.html` 210 KB，gzip 后 30.5 KB（`flash_attn` 的 JVM 栏 992 行占大头）；`explorer.js` 9.4 KB；
  CSS 约 50 行。栏文本全在 HTML 里，不另取数据。
- 两个程序的列表行数（页面上列出的 / 整个程序的）：`flash_attn` Tile IR 61/61、C 166/151,325、JVM 992/70,096；
  `attend` C 142/7,617、JVM 158/190（javap 只列出该 class，不含 std 的类）。
- 没有给编译器、`bin/dawn` 或任何默认产物增加一个字节：`--map` 本来就是按需的。

## 九、不在本刀内

- **M5**（L4：位置直接带进 `tileir` 的 `t_call_enter`）：不碰 `packages/tileir`，Tile 栏继续用 M1 的记录。
  tile 台账正在为 tileir 0.11 重录，这一刀不动任何 `TILE_PATHS`。
- **M6**（真调试信息 LNT / `#line` / `di_loc`）：与本页无关。
- **Playground 在线编译**：把 `--map` 接到 `/run` 与 `/check`、让浏览器里改过的代码也能对照，是下一步；
  本页的 `.xmap` 格式与 `explorer.js` 不依赖「建站时」这件事，将来在线路径写同一种 `.xmap` 即可复用。

## 十、他山之石

- Compiler Explorer：汇编窗格按 `.loc file line [col]` 给每行挂源码行，悬停联动，用颜色分组
  （`lib/parsers/asm-parser.ts`、`static/panes/editor.ts`）；本页反过来记「调用到区间」，嵌套与多对多都在表里。
- Triton 与 MLIR 的 `loc(...)`、Kotlin 的 SMAP 都是行粒度；本页的粒度是调用，不依赖任何产物里的调试节。
- 调研报告 `research-gpumap-call-spans-report-20261003.md` §6.3 与本仓第十二、十三节是出处，这里不重复。

## 十一、不做的（理由）

- **为了页面默认开 `#line` / LNT / `di_loc`**：裁决已否；侧表按需生成，默认产物字节不动。
- **把 `.c.txt` 与 `.xmap` 提交入库**：见第三节，会让每次改编译器都要重录页面快照。
- **整份 C 与整份 javap 都放上页面**：七千到十五万行，几乎全是别人的代码；放了也只是滚动条。
- **每个窗格单独用颜色给每个调用上色（CE 的做法）**：一屏三十几个调用会变成彩虹；
  用「点谁亮谁」把颜色省下来。
- **URL 里记选中的调用（`#flash_attn.mma`）**：有用，但先让点击与键盘是对的；留作后续，不影响格式。
- **搜索索引收录本页**：页面主体是代码，不是可检索的文字，收录会把 C 文本塞进搜索结果。
- **在导航里加第十个入口**：本页挂在 GPU 一节下面（面包屑 GPU / 对照页，GPU 页的 kernel 一节有入口），
  导航已是九项，且每项都有测试钉着。
- **JVM 栏用 ASM Textifier 或自己写反汇编**：第十三节 13.6 已论证，读取方跑 `javap -c -p -s`，
  编译器不写列表。
