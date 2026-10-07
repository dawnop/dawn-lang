# Playground 在线编译：改过的代码也能对照 C / JVM / Tile IR

> 状态：**proposed**（2026-10-07 起草，同日协调者已裁决八个开放问题，见第八节；K1（`packages/xmap`）与 K2（runner 的 `POST /compile`）已实现，见第七节；前端 K3 起尚无代码）。这是 `docs/explorer-page-design.md`
> 第九节留的「下一步」：把 `--map` 接到 Playground，让浏览器里现改的代码也能和产物对照，形态向
> Compiler Explorer 看齐。依赖：M3/M4（`__emitc --map`、`__emit --map`，`docs/source-span-map-design.md`
> 第十二、十三节，已合）、M7（静态对照页，`site/explorer/record.py`，已合）。优先级：在线展示线 P1，
> 与 GPU API 并列。

## 一、要什么，不要什么

要：Playground 的编辑器旁多一个「产物」窗格，标签页 `Output | C | JVM | Tile IR`。用户改代码，窗格里是这段代码现编出来的
C 文本 / 字节码列表 / Tile IR；点源码里的一次调用，窗格里它写出的行亮起，反过来也行。语义与静态页完全一致
（`.xmap` 第 1 版，`explorer-page-design.md` 第四、五节），区别只有两条：数据是**请求时**现算的，源码是**用户的**。

不要：

- **不在浏览器里编译。** 编译器是 JVM/native 程序，浏览器端没有；产物由 runner 现算（第二节）。
- **不另造一套对照格式。** 请求时的数据就是 `.xmap` 的同一份语义，静态页和在线页读同一种东西。
- **不执行用户程序来得到 C 与 JVM 栏。** 这两栏只编译不运行；只有 Tile IR 栏需要跑用户代码（第四节，沙箱同 `/run`）。
- **不先做 Tile IR 的逐调用对照。** 先做文本，对照要 `packages/tileir` 配合（第四节），单列一刀。

## 二、现状：runner 今天怎么工作（实读）

**接口。** `playground/src/main.dawn:62-66`：`GET /health`、`POST /run`、`POST /check`，同一个 `rpc`
（`main.dawn:33-60`）：先拒绝超过 `MAX_BODY = 65536` 字节的请求体（`main.dawn:16`，按字节不按字符），再解析
`{"code": ...}`（`play/contract.dawn` 的 `parse_request`），然后在一个信号量闸门下执行。闸门 `MAX_CONCURRENT = 2`
（`main.dawn:18`）；`/run` 排队最多 15 s，`/check` 只等 2 s、拿不到就 429（`main.dawn:19-22`，设计意图是编辑器诊断是
建议性的，宁可丢一次也不去挤 `/run`）。

**怎么编译。** 单文件：每个请求在运行器的工作根下建一个 `dawn-play-<uuid>/box/`，把源码写成 `box/prog.dawn`
（`play/exec.dawn:245` `with_request`），然后 `dawn build prog.dawn -o prog.jar`（`exec.dawn:273` `compile_phase`），
`/run` 再 `java -Xmx256m -jar prog.jar`（`exec.dawn:315` `run_phase`，`RUN_HEAP` 在 `exec.dawn:57`）。`/check` 走同一个
`compile_phase`，只是不跑（`exec.dawn:302` `check_staged`）。**所以 `/check` 与 `/run` 的编译成本相同**，没有更便宜的
「只检查」路径。只有标准库，没有包：runner 自己的 `dawn.toml` 依赖 `web`/`json`，但那是 runner 的依赖，用户代码拿不到。

**沙箱。** 每个阶段一个 `systemd-run` 临时单元（`playground/sandbox/run-sandboxed.sh`，`SANDBOX.md`）：断网
（`PrivateNetwork`）、文件系统只读只留 `box/` 可写、`MemoryMax=512M`、`TasksMax=64`、`CPUQuota=200%`、
`LimitFSIZE=32M`、`RuntimeMaxSec=15`，编译器堆 `-Xmx256m`（`SANDBOX_JVM_OPTS`）。runner 的编译超时默认 30 s、运行 10 s
（`play/config.dawn:18-31`）。沙箱默认开，只有 `PLAY_UNSAFE_LOCAL=1` 才关（`config.dawn:43`）。编译阶段也在沙箱里，
因为 `comptime` 会在编译器里跑用户代码（`config.dawn:21-25` 的注释）。

**输出上限。** 每个子进程的输出写进 runner 先打开的文件，只读回 `OUTPUT_LIMIT = 65536` 字节（`exec.dawn:50`），
超出标记截断；诊断里的工作目录路径由 `strip_dir` 抹掉（`exec.dawn:132`）。新端点必须沿用这套读回方式，
否则要重新证明「用户程序不能让 runner 读到别的文件」。

**部署事实（只记与设计有关的，不记服务器身份）。**

- 运行环境只装了 **headless JRE 21**（`playground/deploy/DEPLOY.md` 的一次性设置：`openjdk-21-jre-headless`），
  **没有 `javap`**。这是 JVM 栏的第一个前提（第三节）。
- Python 3 在，但只因为 LSP 网关是 Python 标准库写的（`playground/lsp_gateway.py`）；`/compile` 的请求路径不用它（第八节第 2 条）。
- `packages/` 随 `playground/` 一起同步（`DEPLOY.md`：runner 的 `main.dawn` 靠路径依赖引用 `web`/`json`，
  `redeploy.sh` 同步两者）。所以 `packages/tileir`、`packages/tileref` 在部署树里**已经在**，且在沙箱可读的只读绑定下，
  不需要联网取包（`tileir` 的 `dawn.toml` 没有 `[deps]`，`packages/tileir/dawn.toml`）。
- 反代对三个端点各有限流区（`playground/deploy/nginx-play.conf:9-11`：`/run` 12 次/分、`/check` 60 次/分），
  请求体上限 128k（同文件 24、38 行）。
- 合约测试 `playground/test/contract.sh` 在 CI 的 `docs` 作业里跑（`.github/workflows/gates.yml` 的
  `playground contract` 步骤，3151 行附近），本机跑要换端口（CLAUDE.md「测试」节）。

**前端。** `site/play-ui/`：TypeScript + Vite + CodeMirror 6，`src/main.ts` 352 行。布局是侧栏（样例）+ 主栏（工具条、
编辑器、底部输出面板 `dp-outpanel`）；`@media (max-width: 44rem)` 一处（`playground.css:430`）。分享用 URL 片段：
`#` + base64(UTF-8 源码)（`main.ts:33-41` 的 `encodeShare`/`decodeShare`，`Run` 与 `Share` 时 `location.replace`，
`main.ts:296`、`340`）；刷新时的草稿走 `localStorage`（`main.ts:6` 注释）。三个服务 URL 都从 `data-endpoint`
（指向 `/run`）派生（`src/endpoints.ts`），新端点同一个办法加第四个。

## 三、静态对照页的流水线，哪些能在请求时跑

静态页的流水线（`explorer-page-design.md` 第三节，`site/explorer/record.py`，648 行 Python）：

```
bin/dawn __emitc --map     bin/dawn __emit --map + javap -c -p -s     flash_attn.map（Tile，入库）
        └─────────────→ record.py：取目标函数、换算坐标、建调用表、严查 ←─────┘
                                     └→ .xmap + 各栏文本 → site/src/gen/explorer.dawn 读、再查、写 HTML
                                                          + site/assets/explorer.js（223 行，点击/键盘/标签页）
```

### 3.1 实测：每个请求的成本

环境：本机 16 核 WSL2，另有其他写者在跑，**数字只作量级**；工具链是本分支（`dawn 0.85.0 (selfhost) b1:61fe80d3fda4`）
与 v0.85.0 release 的 `dawnc`。样例取 `site/play-ui/samples/*.dawn` 全部 11 个（Playground 自带的程序），另有
`site/explorer/attend.dawn`。命令：

```sh
# 每个重复 3 次，/usr/bin/time -f %e
bin/dawn build  hello.dawn -o hello.jar
bin/dawn __emitc hello.dawn -o hello.c --map hello.dawnmap
bin/dawn __emit  hello.dawn -o jo --map hello.jmap
dawnc-linux-x86_64 emitc hello.dawn -o hello.c --map hello.dawnmap      # native，v0.85.0 release 资产
javap -c -p -s -cp jo hello
```

| 操作 | hello | attend（19 行） |
|---|---|---|
| `dawn build`（runner 今天 `/check` 与 `/run` 的编译） | 1.4 至 1.7 s | 1.6 至 2.2 s |
| `dawn __emitc --map`（JVM 上的编译器） | 1.6 至 1.8 s | 1.7 至 1.9 s |
| `dawn __emit --map` | 1.5 至 1.8 s | 1.5 至 1.6 s |
| native `dawnc emitc --map` | 0.86 至 0.88 s | 0.97 至 1.02 s |
| native `dawnc check` | 0.56 至 0.58 s | 0.58 至 0.59 s |
| `javap -c -p -s`（一个 class） | | 0.23 s |

11 个样例在 `__emitc --map` 与 `__emit --map` 下全部成功，各 1.4 至 1.6 s。结论：**一次对照请求的编译成本和一次 `/check`
同量级（约 1.5 s），不是新的数量级**；只算被选中的那一栏（C 或 JVM），不要一个请求两栏都算。native `dawnc`
出 C 约快 0.7 s，但它出不了 JVM 字节码（`nmain.dawn` 没有 `__emit`，ASM 只在 JVM 后端），先不引入第二条路径（第七节 K2 不做、列入第八节）。

### 3.2 输出大小：必须只送用户模块

整份 C 文本很大：hello 1.7 KB、attend 859 KB、`narrow` 样例 872 KB（含 std 的实现）。**不能整份送。**
静态页的办法就是只取目标函数（`explorer-page-design.md` 第三节）；在线页取「`module` 等于用户模块」的所有 `fn` 行
（`prog`），由 `.dawnmap` 的 `fn` 行给出行区间（`scripts/c-map/dawnmap.py` 的 `fns`）。实测 11 个样例，用户模块部分：

| 样例 | C 行 / 字节 | javap 字节 | 记录的调用数 |
|---|---|---|---|
| hello | 11 / 472 | 2,133 | 1 |
| fizzbuzz | 68 / 2,082 | 6,809 | 2 |
| generics | 283 / 14,122 | 21,961 | 25 |
| barriers（最大） | 335 / 16,770 | 23,679 | 22 |

（脚本：对每个样例 `load()` 其 `.dawnmap`，按 `module` 过滤 `fns` 取行，`javap` 取用户类；全部 11 个最大 C 16.8 KB、
最大 javap 23.7 KB。）所以一次响应在 JSON 里是几十 KB，gzip 后更小；仍然要设**每栏硬上限**（第六节）防止长程序。

### 3.3 JVM 栏：javap 怎么办

设计 `source-span-map-design.md` 13.6 已裁：列表由读取方跑 `javap -c -p -s`，编译器不写列表，Dawn 里也不重写反汇编器
（要 200 来个操作码的长度表、`tableswitch` 对齐与 `wide`）。静态页在建站机上有 JDK。**runner 机器只有 JRE**（第二节），所以：

- 方案 A（已裁决，第八节第 1 条）：部署侧装 `openjdk-21-jdk-headless`（同一主版本，与 `bin/dawn` 钉的 JDK 21 一致，13.6 要求列表在钉住的 JDK 上读），
  javap 与对照脚本在**同一个沙箱单元**里跑。代价：一条运维前提，镜像变大（未测，由运维定）。
- 方案 B（已否决）：在 Dawn 里写反汇编，扩展 `selfhost/src/jvm/classread.dawn`（今天 109 行，只读方法的名字、描述符与 `code_length`）。
  需要常量池解析出 `// Method owner.name:desc` 注释、全部操作码的操作数宽度。工作量与出错面都远大于 A，且 13.6 已论证过为何不做。
  只有「运维不允许装 JDK」时才重开。

### 3.4 谁来把侧表变成 `.xmap`：一个 Dawn 模块，站点与 runner 共用（已裁决）

`record.py` 的核心（取函数、换算坐标、建调用表、`c_pane`/`jvm_pane` 的 `out` 行、`check_table` 严查）是 Python，且按 `PROGRAMS`
表里的**固定程序**（`record.py:33-45`）写。要用在请求上，必须是一个函数：给「`.dawnmap` + 产物文本 + 源码」，返回 `.xmap` 同构的数据与缺口列表
（降级规则见 3.5）。**裁决：这个函数是一个 Dawn 模块**，不是 Python 库。理由：生产 runner 是 Dawn 程序，请求路径上不起 Python；
站点生成器本来就是 Dawn（`gen/explorer.dawn` 已经在重复检查 `record.py` 的输出，`explorer-page-design.md` 第六节）。形状：

- 一个只含纯函数的 Dawn 包（名字待 K1 定，暂记 `packages/xmap`，放进 `packages/` 才能让 `site/` 与 `playground/` 都用路径依赖引用，
  与 `web`/`json` 同一个办法）：解析 `.dawnmap`（格式见 `scripts/c-map/dawnmap.py` 与 `source-span-map-design.md` 第十二、十三节）、解析 javap 列表、
  取用户模块的函数、建调用表与各栏 `out` 行，并返回 `gaps`。输入输出都是字符串与记录，没有 IO，所以 inline tests 与对拍都容易写。
- **runner 里的分工：**沙箱单元只产原料（`dawn __emitc --map` 或 `dawn __emit --map`，JVM 栏再在第二个单元里跑 `javap`，
  各自写 `box/` 里的文件），runner 进程只读回**有界**的原料文本（沿用 `exec.dawn` 的有界读回）再调这个模块。解析运行在 runner 进程里，
  输入是有界的文本，不执行任何东西；沙箱单元数从一个变成三个（K2 实测的修正见 6.2：C 与 JVM 两张侧表缺一不可，所以两个编译器各一个单元、再加一个 `javap`），每个单元的 `systemd-run` 开销 K2 已测：0.08 至 0.14 s（见第七节 K2）。
- **过渡期对拍：**`record.py` 保留，对 `flash_attn`、`attend` 与 11 个样例，Dawn 模块产出的 `.xmap` 与 `record.py` **逐字节相同**；
  静态页（`site-dist-diff.sh`）是回归。对拍通过后，`record.py` 只剩「调用编译器、javap、`dawn parse` 取原料」那一层，
  组装与校验都由 Dawn 模块做，`gen/explorer.dawn` 不再重复一份校验。Tile 栏仍读 `flash_attn.map`（T2 不在本批，第四节）。

### 3.5 缺口：静态页要求「全有」，在线页只能「尽量有」

静态页：「表里的每个调用在每一栏都必须有出处，没有就建站失败」（`explorer-page-design.md` 第三、六节）。用户任意代码做不到：
`comptime` 展开、`derive` 生成的代码、单态化实例、被内联或提升的闭包，都可能让某次调用在某一栏没有行。在线页的规则：

- 窗格里**文本总是完整**（用户模块的 C / javap），能对上的行有对照，对不上的行无高亮、点了没反应；
- 响应带一个 `gaps` 计数与前几条原因（`call 7 has no C rows`），前端在窗格底部一句话说明「3 个调用没有对照」，
  服务端打日志（带内容摘要而不是源码），这样缺口既不是静默的、也不会把整个对照拖垮；
- 11 个样例作验收语料：**每个样例 `gaps == 0` 是 K1 的验收**（目前 11 个样例的记录调用数 C 与 JVM 相等，见 3.2 表，是个好信号，但还没有
  跑过严查），出现缺口就当编译器侧表的缺陷开 issue，不在在线页里藏掉。

## 四、Tile IR 栏

「编译到 Tile IR」在 Dawn 里**不是编译**，而是**运行**：`packages/tileir` 的 `Dev` 效果处理器在宿主上跑 kernel 函数，
`trace_kernel`/`traceN` 记录下一个 `TileProg`，`render` 再把它渲成文本（`packages/tileir/src/prog.dawn:1359`、`render.dawn:771`）。
没有设备参与，不需要 GPU，也不是 `std/gpu` 的 `with_gpu_fake`（那是另一个层，`tile-backend-design.md` 4.3）。
所以 Tile IR 栏**会执行用户代码**，安全面等同 `/run`，不是 `/compile` 的「只编译」。

### 4.1 实测：纯文本（T1）可行且不新增安全面

把一个 `vadd` kernel 放进带 `[deps] tileir/tileref`（路径依赖，指向仓库的 `packages/`）的项目，用 `dawn run`：

```sh
bin/dawn run tp            # 项目目录：dawn.toml + src/main.dawn（trace3 + render，打印文本）
bin/dawn check tp
bin/dawn build tp -o tp.jar; java -jar tp.jar
```

实测：`dawn run` 4.4 至 4.6 s（3 次），`dawn check` 3.1 至 3.2 s，生成的 jar 运行 0.2 s、打印 1,804 字节的 Tile IR。
**每个请求都要重新编译 `packages/tileir` 的约 1.9 万行**（`wc -l packages/tileir/src/*.dawn`），比单文件多约 2.7 s。
上限仍在 `/run` 的 30 s 编译 + 10 s 运行预算内。没有缓存编译结果；若 Tile 请求多，缓存按「源码 + 编译器构建」哈希（第六节）
是最直接的杠杆，重编 `tileir` 的缓存是更大的工程，不在本设计。

**多包依赖的实现面（K5）。** runner 今天只写 `prog.dawn` 单文件，直接 `dawn build`。Tile 模式要建一个项目目录：`box/dawn.toml`
（`[deps] tileir = "<部署树>/packages/tileir"`、`tileref` 同理）+ `box/src/main.dawn`，然后 `dawn build <项目目录>`。
依赖只读、`tileir` 无 `[deps]`、不联网，沙箱的 `BindReadOnlyPaths` 已覆盖部署树。**未验证项：**沙箱里 `dawn` 的项目模式是否需要写
`box/` 之外（缓存、`dawn.lock`），要在 `PLAY_UNSAFE_LOCAL` 关闭的真沙箱里实测，列为 K5 的第一步而不是先假设。
为防止用户在 `dawn.toml` 里夹带路径依赖：`dawn.toml` 由 runner 生成，用户只提供 `main.dawn` 的内容；用户源码里的 `use tileir/...`
只能解析到这两个固定的包。

### 4.2 什么时候出现 Tile IR 标签：只对 `use tileir/` 的程序

标签页只在源码文本含 `use tileir/` 时出现（前端按字符串判，服务端按同样的规则**再判**一次，不信任客户端）。
不要求「有 kernel 入口」：判断入口要解析语义，`dawn check` 通过且 `main` 能跑完就行；没有 `use tileir/` 的程序点这一栏得到的是
一句话「这一栏需要 `use tileir/...`」，不是灰掉的空标签，与静态页「没有就是没有」同一态度（`explorer-page-design.md` 第二节）。
这一栏的内容就是**程序运行后的标准输出**（用户自己 `println(render(..))`），文本 T1 到此为止，不新增 runner 概念：
它是「`/run` + 能 import tileir」，响应里把输出放进 Tile IR 窗格。

### 4.3 逐调用对照（T2）：要 `packages/tileir` 配合，单列

静态页的 Tile 栏靠 `site/gpu-map/record.py` 对 `kernels.dawn` 做**源码改写**：把 `traceN` 调用正则换成 `trace_calls(..., markers: [...])`
（`site/gpu-map/record.py:112-137` 的 `harness_source`），再把 `render.line_map` 的结果与 `dawn parse` 的调用区间逐层配对
（该文件 37-47 行的说明：同一层里 kernel 里运行的调用名顺序必须与解析器看到的求值顺序**完全相同**，否则整个脚本失败）。
这对一份固定的、人维护的 kernel 成立，对任意用户代码**不成立**：用户在宿主控制流里调 `d_range`、绑定闭包再调用、辅助函数里有效果，
配对都会失败，而改写是正则。要做在线逐调用对照，需要 `tileir` 提供一个**稳定入口**（例如 `tileir/explore` 里一个带标记表的 `explore_kernel`，
内部调 `trace_calls` + `line_map`，按约定输出一个协议块），并明确「哪些写法不支持、失败时怎么降级」。这会碰
`packages/tileir`，进而触发 tile-golden / GPU diff 台账等一串门禁（`gatemap.py packages/tileir/src/prog.dawn` 报
`tile-golden-1`、`tile-gpu-diff` 的 coupled 与 `site/explorer/record.py names packages/tileir` 等），属于 Tile 线所有者的决定，
所以**本设计的 K1 至 K5 都不包含 T2**；K6 等 `tileir` 给出稳定入口再定（第八节第 4 条）。

## 五、前端

### 5.1 窗格与布局

Playground 现在是「侧栏 + 编辑器 + 底部输出面板」。加一个与输出面板并列的**产物窗格**：宽屏（`> 44rem`，沿用 `playground.css:430`
的同一个断点）在编辑器右侧分栏，窄屏叠在编辑器下、与输出面板共用一个标签条 `Output | C | JVM | Tile IR`（手机上同一时刻只看一个）。
手机 375 px 下行不换行、窗格自己横向滚动、页面不横向滚动（与静态页第七节同一条）。标签页按 ARIA tabs 写，与 `explorer.js` 一致。
显示的是**当前标签**对应的那一栏，且只在该标签可见时才发请求（第六节），所以不看 C 的人不为 C 付费。

### 5.2 与静态页共用多少

`explorer.js` 不是纯逻辑：它读服务端生成的 HTML 里的 `data-c`、`data-p`、`data-o`、`data-i` 等属性（`site/assets/explorer.js:30-45`），
HTML 由 `site/src/gen/explorer.dawn`（677 行 Dawn）生成。Playground 的 bundle 是 TypeScript，响应是 JSON，不生成 HTML 字符串。
三种共用法：

- 甲：前端用 TypeScript 按**同一个 DOM 约定**（同样的 class 与 data 属性）渲染 JSON，把 `explorer.js` 拆成「选择与高亮」的核心
  （`explorer-core`，两边都 import/内联）与「页面接线」两部分，静态页继续用服务端 HTML。CSS 的 `.xp-*` 也共用。推荐：改动只在
  JS/TS 层，Dawn 生成器与 `site-dist-diff.sh` 的字节契约不动，除非拆分改变了发布的 `explorer.js` 字节（那就是一次声明过的站点输出变化）。
- 乙：runner 直接返回渲染好的 HTML 片段（复用 `explorer.dawn` 的 `figure_html`），前端插入。要把站点生成器里的函数搬进 runner 的依赖，
  两个包的耦合方向不对（runner 不应依赖站点），否决。
- 丙：前端重写一份高亮逻辑，不共用。第二份真相，且键盘与无障碍要再做一遍，否决。

### 5.3 URL 状态

现状：`#` + base64(源码)（`main.ts:33-41`）。要多记「当前标签」。base64 的字符集是 `A-Za-z0-9+/=`，不含 `?` 与 `&`，
所以把标签放进查询串：`https://…/play?view=c#<base64>`（`view` 取 `output|c|jvm|tile`），旧链接没有 `view`，行为不变，不需要兼容层。
**选中的调用不入 URL**（静态页第十一节已记「留作后续」，同一理由）。不要把标签塞进片段前缀，那会让所有已分享的链接解析歧义。
编辑后 `Run`/`Share` 才写片段（`main.ts:296`、`340` 的现行为），标签切换只改查询串（`history.replaceState`）。

## 六、提案

### 6.1 端点

`POST /compile`，请求体沿用 `{"code": "..."}`，多一个 `"target": "c" | "jvm" | "tile"`。同样的 `MAX_BODY`、同样的 JSON 外壳：

```
成功 {"ok":true,"phase":"compile-view","target":"c","build":"b1:…","cached":false,"ms":1480,
      "src":{"first":1,"last":19},
      "calls":[{"id":0,"parent":-1,"name":"map","from":[8,13],"to":[8,52],"nfrom":[8,13],"nto":[8,16]}, …],
      "pane":{"kind":"c","total":7594,"shown":134,"text":["…"],"outs":[{"call":0,"lines":[[3,5]],"marks":[[3,4,9]]}, …]},
      "gaps":{"count":0,"first":[]}}
失败 {"ok":false,"phase":"compile","output":"<诊断>"}      与 /run、/check 的 compile 同形（contract.dawn 36-37 行）
忙   429 {"ok":false,"phase":"error","output":"server busy…"}
```

字段与 `.xmap` 第 1 版逐项同义（`call`/`out` 行的区间、`@`、`!` 标记），只是换成 JSON；线上与静态页因此共享校验规则（区间在文本内、
`@` 列在行内、`!` 行是 invoke）。`target:"tile"` 的响应没有 `calls`，只有 `pane`（T1，第四节）。**编译失败时不新增诊断格式**：复用
`phase:"compile"` 的 `output`，前端的诊断显示（`lint.ts`）原样可用，产物窗格保留上一次的内容并标「过期」，不清空。

### 6.2 执行与沙箱

- C / JVM：沙箱单元只产原料：`dawn __emitc --map` 与 `dawn __emit --map`，再一个单元跑 `javap`（3.4），只写 `box/`，只读回有界输出
  （沿用 `exec.dawn` 的「runner 先开文件、读回有界」，`exec.dawn` 文件头注释）。不运行产物。
  **K2 实现时对「一个请求只算被选中的那一栏」的修正：** 调用表是 C 侧表与 JVM 侧表**都有行**的调用的交集（`packages/xmap` 的
  `table_from_maps`，缺一边就是缺口），所以请求任何一栏都要两个编译器的侧表；只剩 `javap` 是 JVM 栏独有，它 0.2 s，不值得省。
  于是一次构建同时产出两栏，缓存里两个 target 各存一份，第二个标签页是一次查表。两个编译器**先后**跑（C 再 JVM，`javap` 跟在后面）：生产机小、还要服务 `/run` 与 `/check`，一个许可下起两个编译器 JVM（两个许可就是四个）不是合适的默认（协调者 2026-10-07 裁决）。
  本机实测先后跑冷请求 3.6 至 4.0 s，并排只要 2.0 至 2.2 s，这笔差价由「同构建的第二个标签页是命中」找回。限制沿用 `run-sandboxed.sh`
  现有的全部属性（`MemoryMax`、`TasksMax`、`LimitFSIZE`、`RuntimeMaxSec`、无网），**不为 `/compile` 放宽任何一条**。
  `comptime` 仍会在编译里跑用户代码，所以编译超时用现有的 30 s（`config.dawn:29`），编译阶段的威胁面与 `/check` 相同，不更大。
- javap 读的是编译器写出的 class，不是用户给的字节，但它仍在同一个单元里跑，不放在 runner 进程里。
- Tile IR：与 `/run` 完全同一个单元与限制（编译 + 运行），因为它执行用户代码；响应里只放它的标准输出。**不**把 Tile 模式的
  执行放宽到「`/compile` 只编译」的口径里，也不单独给它更高的超时。
- 响应硬上限：每栏文本 ≤ 256 KB（超出截断并带 `truncated`，与 `OUTPUT_LIMIT` 同类处理），`calls` ≤ 2,000 条。
  依据：样例用户模块最大 17 KB / 24 KB（3.2 表）；上限给 10 倍余量，是估计，不是实测，上线一周后按观测收紧（第八节第 7 条）。
- 原料读回上限：C 文本、两张侧表、javap 列表各 **8 MiB**（K2 新增，估计值：最大起始样例的整份 C 文本 871 KB，几乎全是标准库；上线一周后按观测收紧）；超出答 422，不映射。

### 6.3 缓存与并发

- 缓存键：`sha256(build ‖ target ‖ code)`，`build` 是 `compiler_id()` 已经算出的构建摘要（`exec.dawn:349`，`/health` 里的 `build`）。
  编译器一换键就全变，不存在「旧编译器的产物」。进程内 LRU，条目数上限（初值 128）× 每条上限 ≈ 0.5 MB，最坏 64 MB 以内；
  典型条目几十 KB。命中时 `cached:true`，不占闸门。**为什么不做反代缓存：**POST，且请求体里是用户代码，键在 runner 里算更简单。
- 并发：与 `/run`、`/check` **共用同一个 2 许可闸门**（`MAX_CONCURRENT`，`main.dawn:18`），否则两倍的并发上限就没人管了。等待时间
  取 `/check` 的口径（2 s，拿不到 429，`main.dawn:22`），因为产物窗格也是建议性的：丢一次，窗格保留旧内容。**未测：**多个浏览器同时
  自动重编时的排队行为；K2 的验收里要测。
- 触发：**手动按钮 + 空闲 1.5 s 自动**，只对当前可见的标签发请求；输入时取消在途请求。CE 是每次按键都编译，那是它有 30 多个实例
  和 CDN；这里单机 2 个许可、每次约 1.5 s，自动编译必须去抖。
- 反代：给 `/api/compile` 一个新限流区（起点 30 次/分、burst 6，**估计值，不是实测，上线一周后收紧**（第八节第 7 条）），请求体上限同 128k，`proxy_read_timeout` 与
  `/api/check` 同量级。写进 `playground/deploy/nginx-play.conf` 的示例块与 `DEPLOY.md`。

### 6.4 安全清单

编译不运行；沙箱不放宽；响应只含用户模块的文本；工作目录路径经 `strip_dir`（`exec.dawn:132`）；`target` 白名单三值，
其余 400；Tile 模式的 `dawn.toml` 由 runner 生成，用户只能写 `main.dawn`；`javap` 的参数是固定 argv，类名来自编译器写的文件名而不是
用户输入的原样字符串（要在 K2 里测：类名里带怪字符的源码）。

### 6.5 部署侧的新依赖

- **`openjdk-21-jdk-headless`**（取代 `DEPLOY.md` 一次性设置里的 `openjdk-21-jre-headless`；JDK 包含 JRE，运行 `/run` 的 `java` 不变）：
  JVM 栏要 `javap`，且它必须与 `bin/dawn` 钉的 JDK 同主版本（13.6）。K2 同时改 `playground/deploy/DEPLOY.md` 的第 2 步，
  并让 `redeploy.sh` 在缺 `javap` 时拒绝发布（与它现在对 `dawnc` 版本的核对同一种态度）。包体积与镜像变化**未测**，由运维评估。
- `packages/xmap`（暂名）随 `packages/` 一起同步，沿用 `DEPLOY.md` 里 `packages/` 与 `playground/` 并排的约定，不增加新的目录。
- `/api/compile` 的限流区与请求体上限写进 `nginx-play.conf` 示例块（K4）。

## 七、刀序

每刀一个 PR、一个主题。门禁名取自 `gatemap.py` 的实际输出（`python3 scripts/gate-map/gatemap.py <路径>`）：
**`playground/**` 与 `site/play-ui/**` 在这张表里是「不是已跟踪路径」（`?`）**，也就是除了 CI `docs` 作业里的
`playground contract`、`site builds end-to-end`、`site dist, JVM vs native` 三步外，没有专门的映射门在看它们；这是本设计要补的洞
（每刀的「负控」就是在补它）。`docs` 作业的预算是 605 s 规划值、3 倍超时 31 分钟
（`.github/workflows/gates.yml` 该作业头部注释），新增的合约用例必须在其中吸收并报墙钟。

**K0：已裁决（第八节）。** 八条裁决 2026-10-07 全部给出，可以动码。

**K1：共用的 Dawn 映射模块，对拍 `record.py`，并在 11 个样例上证明「缺口为零」。**
- 内容：新建纯函数 Dawn 包（暂记 `packages/xmap`），做 3.4 所述的全部事；`site/src/gen/explorer.dawn` 改用它；`record.py` 暂留，
  作为对拍的另一端；降级模式（3.5）在模块里，静态页用「有缺口即失败」的严格入口，在线用降级入口。
- 验收：对 `flash_attn`、`attend` 与 11 个样例，模块与 `record.py` 的 `.xmap` 逐字节相同（对拍脚本进 CI）；`site-dist-diff.sh` 绿；
  11 个样例各自 `gaps == 0`，不为零的写进 issue 清单；包的 inline tests 覆盖解析、嵌套、缺口；`./bin/dawn test` 该包与 `site`。
- 负控：对拍里注入一个丢调用的变异（模块少写一个 `out` 行），要求对拍红；注入「严格入口不再失败」的变异，要求静态页建站红
  （严查没被削弱）；`record.py --self-test` 的三个变异（挪一位 `lo`、挪出方法的 `pchi`、改名）仍然逐个打红，并对模块也各打一遍。
- 门禁：`site builds end-to-end`、`site dist, JVM vs native`、`docs`（新包与 `record.py` 名下）；新增 `packages/` 成员会碰包的文档与发布检查
  （`pub-doc-check`、`doc-check`），用 `gatemap.py packages/xmap site/explorer/record.py` 核对，实现时回填。
- 墙钟：对拍多跑一遍 `record.py` 的原料（17 至 20 s，`explorer-page-design.md` 第八节）；**在 PR 里报 CI 实测**，
  必要时把对拍放进已有的 `site builds` 步骤而不是新作业。
- **收尾（同一刀的最后一个提交，或紧随的一刀）：**对拍通过后删去 `record.py` 里的组装与校验，只留取原料那层。

**K2：`/compile`，目标 C 与 JVM。**
- 内容：`playground/src/play/` 加编译视图的执行与 JSON 渲染，`main.dawn` 加路由，同一闸门；部署侧 javap 前提（`openjdk-21-jdk-headless`，已裁决，见第八节与 6.5）；
  `contract.sh` 加用例：C 成功、JVM 成功、编译错误与 `/run` 同形、超限 413、`target` 非法 400、路径不泄漏、第二次同请求 `cached:true`、
  闸门饱和 429、类名带怪字符的源码。
- 验收：`PLAY_TEST_PORT=18097 ./playground/test/contract.sh` 全绿；样例响应的 `gaps` 为 0；对 hello 首次冷请求 ≤ 3 s、
  命中 ≤ 50 ms（**目标，实现后实测回填**，不是已有数字）。
- 负控：把路径抹除（`strip_dir`）去掉，要求「路径不泄漏」用例红；把闸门许可数让给 `/compile` 独立计数，要求「并发」用例红。
- 门禁：`playground contract`（docs 作业）；`emit playground` 标签相关的差分（`playground/` 源码改动，prev-diff 的语料里有 `emit playground`，
  只要不改编译器输出就不需要 `Emit-Change`）；新增 Dawn 的 inline tests 由 `./bin/dawn test playground` 跑。
- 墙钟：合约多约 10 个用例 × 约 1.5 s ≈ 15 s，加在 `docs` 作业里（605 s 规划值内；**CI 上的实测在 PR 里报**）。

**K2 落地记录（2026-10-07）。**
- **实现：** `playground/src/play/exec.dawn`（`view_raw`：三个单元先后跑、有界读回）、`play/view.dawn`（xmap 配对、限额、JSON）、
  `play/cache.dawn`（有界 LRU）、`main.dawn`（路由、闸门）。请求体沿用 `{"code": ..., "target": "c"|"jvm"}`；`target` 取值白名单，
  `"tile"` 在 K5 之前也是 400。响应字段比 6.1 的草图多：`calls_total`、`calls_truncated`、`pane.truncated`、每个 out 带 `key`（JVM 栏的 `!` 行）。
  缓存值分两半：请求无关的「其余」与每次请求自己写的头（`cached`、`ms`），所以命中与新鲜答案只差这两个字段。
- **限额（起始值，估计，上线一周后按实测收紧）：** 每栏文本 256 KB（按行截断，`truncated`），每响应 2,000 个调用（前缀，`calls_truncated`），
  原料每个文件 8 MiB（同为估计，不是实测，上线一周后按观测收紧；超出答 422，不映射；最大的起始样例 871 KB，几乎都是标准库的 C）。缓存 128 条、32M 字符，单条超四分之一不留。
- **实测的单元开销：** 本机（WSL2）带 `run-sandboxed.sh` 全部属性的一个 `systemd-run` 单元跑 `true`：0.08 至 0.14 s。三个单元合计约 0.2 至 0.3 s，
  这个沙箱内的总数是**推算**的，没有用真的 jar 量过（本机没有 `/opt/dawn` 供包装脚本绑定，`$HOME` 下的 JDK 又被 `ProtectHome` 藏起来）。
- **延迟（11 个起始样例，真 runner、沙箱外，编译器先后跑；本机负载 8 至 12，只作量级）：** 冷（C 先请求或 JVM 先请求结果相同）3.85 至 4.89 s，中位约 4.4 s；
  命中 8 至 19 ms。目标「hello 冷 ≤ 3 s」**不达标**：先后跑是协调者的裁决（生产机小），代价就是冷请求约 4 s，由缓存找回第二个标签页；
  并排起（已放弃）负载 5 时是 2.35 至 2.67 s。命中 ≤ 50 ms 达标。十一个样例**全部 `gaps == 0`**（C 与 JVM 两栏，冷与命中都检了）。
- **实测中发现并修了两个只有「带怪字符的源码」才暴露的缺陷：** (1) `packages/xmap` 的 `javap` 成员头只认 ASCII，`größe` 这样的函数名整个方法落成缺口
  （xmap 0.1.1，带负控）；(2) 沙箱单元的环境是空的，JVM 读成 POSIX 区域，`dawn __emit -o` 写不出 `prog$Wéird.class`（「unmappable characters」），
  `javap` 把这些名字印成 `?`。runner 在三个命令前加 `env LC_ALL=C.UTF-8`，包装脚本不动，`/run`、`/check` 的环境不变。合约测试把 runner 自己起在 POSIX 区域里。
- **`javap` 缺失：** runner 启动时探测（`javap -version`），缺则 `POST /compile` 答 503 并说明，其余端点照常；`redeploy.sh` 在同步任何文件之前先问服务器，
  缺 `javap` 则拒绝发布；`DEPLOY.md` 第 2 步改装 `openjdk-21-jdk-headless`；`playground/test/lsp_contract.py` 有对应的门禁与变异体。
- **合约用例（`playground/test/contract.sh`，19 → 40 项）：** C 与 JVM 成功（结构自检：调用 id、out 区间与标记列都在文本内）、同请求命中（只差头）、
  JVM 栏是同一次构建的另一半（命中）、怪字符名字零缺口、编译错误与 `/check` 逐字节相同且不泄漏工作目录、超栏限额截断、超调用限额、
  400（target 非法/缺失/非字符串、无 code、坏 JSON）、413、405、闸门饱和 429、许可归还。
- **负控（均先绿后红再还原）：** 抹掉 `strip_dir` 令「不泄漏路径」与「诊断逐字节同 /check」红；给 `/compile` 独立闸门令「429」红；去掉 UTF-8 区域令怪字符两例红；
  抬高栏限额与调用限额各令对应例红；缓存永不命中令三例红；`javap` 恒可用令 503 单元测试红；探测遇缺失工具崩溃令探测测试红；`redeploy.sh` 的 `javap` 门禁有三个变异体。
- **没做的：** 不做反代限流（K4）；`/compile` 与 `/check` 的并发排队行为只在合约里测了「两个许可被占满则 429」，多个浏览器同时自动重编的行为未测，留给 K3 联调。
**K3：前端窗格，C 与 JVM。**
- 内容：`site/play-ui` 标签条 + 窗格 + 渲染 JSON 到与静态页同一个 DOM 约定；按 5.2 甲拆 `explorer-core`；`?view=` 查询串；窄屏叠放。
- 验收：`npm test`（`site/play-ui/test/selftest.ts`）加用例：选择/反查/Esc/键盘与静态页一致；手机宽度无横向页面滚动（用 Vite 起页后
  在 375 px 视口截图人工核，并把「页面宽度不超过视口」写成一个自测）；刷新与分享链接保持标签。
- 负控：把 `explorer-core` 的「最内层所有者」取成最外层，要求用例红。
- 门禁：`site builds end-to-end`（含 Playground 编辑器 bundle）、`site dist, JVM vs native`；若拆分改变了发布的 `explorer.js` 字节，
  按站点输出变化声明。
- 墙钟：bundle 体积增量在 PR 里报（以 PR 内实测为准，不在此处断言数字）。

**K4：反代限流与部署说明。** `nginx-play.conf` 示例块、`DEPLOY.md`、`SANDBOX.md` 的限制表加 `/compile` 一行；纯文档加配置，无新测试。

**K5：Tile IR 文本（T1）。** runner 的项目模式（生成 `dawn.toml`、固定两个路径依赖）+ 标签的显示条件（服务端复判）。先在**真沙箱**里验证
第四节「未验证项」。验收：含 `use tileir/` 的 `vadd` 样例 `/compile {"target":"tile"}` 得到与 `dawn run` 相同的文本；用户在源码里写
`use tileir/` 之外的包（例如伪造路径）解析失败；不含 `use tileir/` 的程序请求 tile 得到一句明确的错误。负控：让 runner 不再生成
`dawn.toml`（改成读用户提供的），要求「夹带路径依赖」用例红。墙钟：每个 Tile 用例约 4.5 s，合约只放 2 个。

**K6（可选，第八节第 4 条：等 `tileir` 稳定入口）：Tile IR 逐调用对照（T2）**，在 `packages/tileir` 的稳定入口落地之后；单独裁决，不在本批。

## 八、已裁决（2026-10-07，协调者）

原先的八个开放问题全部有了裁决；二、三节的方案按它们修订。

1. **`javap`：装 `openjdk-21-jdk-headless`。已裁决。**沿用 `source-span-map-design.md` 13.6 的旧裁决。理由：Dawn 里自写反汇编器是一整条线，
   收益只是少一个系统包。**部署文档要写明这个依赖**（6.5）。
2. **映射转换的核心：Dawn 模块，不要 Python。已裁决（否决了「`record.py` 做成 Python 库给 runner 调」）。**
   理由：生产 runner 是 Dawn 程序，请求路径上不起 Python；站点生成器已经是 Dawn。落地见 3.4 与 K1：模块站点与 runner 共用，过渡期与
   `record.py` 逐字节对拍，对拍通过后 `record.py` 只剩调用编译器取原料的那层。
3. **何时编译：手动按钮 + 输出栏打开时空闲 1.5 s 自动重编。已裁决。**`/run` 出现 429 再退回仅手动。
4. **Tile IR 逐调用高亮：先不做。已裁决。**先出纯文本（K5），K6 等 `tileir` 给出稳定入口再定。
5. **native C 快路径：不开第二条路径。已裁决。**
6. **每个可见标签页一个请求，靠缓存吸收重复。已裁决。**
7. **起始限额：30 次/分钟、每栏 256 KB、每响应 2,000 个调用，作为起始值采纳。已裁决。**这些是**估计**，不是实测：
   上线一周后按实测收紧，那一天再回填本文与 `nginx-play.conf` 的示例值。
8. **缺口处理：静态页遇缺口建站失败，在线视图降级并计数。已裁决。**11 个样例必须零缺口，作为门禁（K1 的验收）。

## 九、他山之石

- **Compiler Explorer（godbolt）。** 编译服务是 Node/TypeScript 的 `BaseCompiler` 子类调用编译器进程，结果过滤后回 JSON；
  每个实例最多 2 个并发编译（与这里的 2 许可同量级），nsjail 做隔离（编译与执行两套配置），缓存三层：浏览器、实例内 LRU、
  S3 内容寻址缓存。出处：Matt Godbolt，*How Compiler Explorer Works in 2025*，<https://xania.org/202506/how-compiler-explorer-works>。
  API：`POST /api/compiler/<id>/compile`，`filters` 控制 `directives`/`labels`/`commentOnly`/`demangle`/`execute` 等，响应的 `asm`
  数组逐行带 `source: {file, line}`；短链 `POST /api/shortener` 存整个状态，URL `/z/<id>`；
  出处：<https://github.com/compiler-explorer/compiler-explorer/blob/main/docs/API.md>。
  取舍：本设计取「编译服务 + 内容寻址缓存 + 2 并发」；**不取**它的 filters（我们的产物只含用户模块，没有 `.cfi` 之类的噪声要过滤）与短链
  服务（URL 片段已够，且没有服务端存储）；**不取**每次按键编译（第六节）。
- **Rust Playground。** React 前端 + Axum 后端，编译器与工具跑在 Docker 容器里，断网、限内存与时间；可选 ASM、LLVM IR、MIR、WASM
  作为「看产物」的模式，而不是另一个页面。出处：<https://github.com/rust-lang/rust-playground>（README）。取舍：同样是「同一个页面里换目标」，
  但它不做逐行对照；本设计的对照是 Explorer 页已有的东西，只是搬过来。
- **Go。** godbolt 支持 Go（`gc` 出的是 Go 汇编而非最终机器码，见其 issue #4735），官方 `go.dev/play` 没有产物窗格；
  可借鉴的只有一点：目标语言自己的「汇编」可以是一个合法产物，不必都是机器码，对应我们的 Tile IR 栏。
- 本仓：`docs/explorer-page-design.md`（静态页，全部语义出处）、`docs/source-span-map-design.md` 第十二、十三节（侧表格式）。

## 十、不做的（理由）

- **不在 runner 里整份返回 C 或 javap**：整份 C 最大 872 KB（3.2），几乎全是 std 的实现。只送用户模块。
- **不让编译器自己写 javap 式列表**：13.6 已裁，第二份真相。
- **不让 `/compile` 执行用户程序（Tile IR 除外）**：C 与 JVM 栏是纯函数，不需要也不该有执行面。
- **不为 `/compile` 放宽任何沙箱属性**：对照是展示功能，不值得扩大攻击面。
- **不做逐按键自动编译**：单机 2 许可，约 1.5 s 一次。
- **不做服务端短链存储**：URL 片段够用，存储意味着新的持久化与滥用面。
- **不把「选中的调用」放进 URL**：同静态页第十一节，先让点击与键盘对。
- **不先做 Tile IR 逐调用对照**：要 `tileir` 的稳定入口，属 Tile 线（4.3）。
- **不引入 native `dawnc` 作为第二条 C 路径**：见第八节第 5 条。
- **不加兼容层**：片段格式不变，旧链接天然可用；标签放查询串，不改旧格式。
- **不在 runner 里依赖站点生成器的代码**：方向反了（5.2 乙）。
