# GPU 页按 tileir 0.8.0 重做：页面讲新 API（设计）

任务单 `gpu-page-newapi-20261005.md`（agent-handoff）。基点是 cuTile 批 PR-3 的分支（`feat/tile-batch-migrate-r1`，
`74ea0cf3`）：`tileir` 0.8.0，`kernels.dawn` 全迁，flash_attn 调用图已重录。PR-3 只改了页面两句文案，页面仍然只讲
「flash_attn 的逐调用对照 + 覆盖率 + 三道门 + 台账」，**没有一处告诉读者 0.8.0 的 kernel 怎么写**。本文定这一刀
补什么、从哪里取、放在哪。

依据：`ruling-cutile-rs-borrow-20261003.md`（修订二与补注）、`ruling-tile-read-view-assume-20261004.md`、
`tile-batch-pr3-report-20261005.md`、`ruling-source-span-map-20261003.md`（M1：调用图只放 flash_attn）、
`site-identity-gpu-packages-direction`（GPU 页在主站）；`packages/tileir/README.md`、`CHANGELOG.md`；
[tile-backend-design.md](tile-backend-design.md) §6.22–§6.26。

## 一、读者要看懂的七件事，各配哪段真代码

原则不变：**页上的代码一律从被门禁覆盖的文件里按函数名切出来**（`gen/common.fn_source` 与 `gpu.cut_fn`，切不到
构建就红），不手写演示代码。来源只用 `scripts/tile-golden/kernels.dawn`：它的每个 kernel 都有 `.mlir` / `.tilebc`
golden、过 `tileiras`、大多在 sm_86 台账上，比 `gpu_fake`（只断言 Tile IR 文本与假设备答案）覆盖深一层。

| # | 要点 | 裁决出处 | 取哪段（`kernels.dawn`） | 为什么是它 |
|---|---|---|---|---|
| 1 | kernel 就是 `!Dev` 下的普通函数；参数标记（`In` / `Out` + `cells`）说它读写哪一格，体内不写地址 | C2、D-4 | `vadd`（函数一行体）+ 它的派发臂 `trace3("vadd", In(F64, run_of(128)), …)` | 最短的完整 kernel；`run_of` 是同文件的一行 helper，页上一并切出 |
| 2 | 形状从操作数推出：体内一个形状、一个格式都不写 | C3 | `softmax`（三行） | 两次归约、一次超越、一次除法，全文零形状 |
| 3 | rank-0 tile 与隐式广播：常量与对 rank-1 的归约是 0 秩，遇到更宽的操作数自己加宽，别处不加宽 | C3′ | 同一段 `softmax`：`sub(t, reduce_max(t))`、`div(ex, reduce_sum(ex))` | 第 2、3 点共用一段，不另找 |
| 4 | 写只经 `Out`：`store_cell` / `store_sub`；累加器从 `zeros(o)` / `fill(o, v)` 起步；`FREE_AXIS` 让 kernel 自己挑格子（`load_at`） | D-7、D-4 | `matmul`（`d_range` + `zeros(c)` + `load_at` + `store_cell`）+ 它的派发臂（`along: [0, FREE_AXIS]`） | 教科书形状的 GEMM，标记即几何 |
| 5 | 保维归约：`reduce_max(s, keepdims: true)` 得 `[BQ, 1]`，再显式 `broadcast` 回 `[BQ, BK]` | C4、修订二补注 | **不另切**：就是下面调用图里 `flash_attn` 的 `m_new` 与 `l_new` 两行；本节给两个「在图里看」的链接，点击即选中图里那次调用 | 补注明说 flash_attn 是这项能力的验收样本；重复贴一遍等于两份同一代码 |
| 6 | `Shared` 何时需要：原子、数据决定的 scatter、一块写两区域、维序对不上网格等；它是显式的、可 grep 的逃生口 | D-7 | `batched_matmul` 的派发臂（`In(F64, Whole), In(F64, Whole), Shared(F64)`）与它函数头上那段说明「批在网格第三轴、是矩阵第一维」的注释 | 55 个 `Shared` 里最常见的一类（秩墙 / 维序墙）的代表，注释本身就是理由；不选 histogram（原子那类读者不用解释） |
| 7 | `hint_occupancy`：sm_86 上 128 级 f16 张量核 kernel 一律 `hints: [for_arch("sm_86", [hint_occupancy(2)])]` | §6.26 占用率裁决 | **无 kernel 可切**：`kernels.dawn` 没有 128 级 f16 kernel（`matmul_f16` 是 32 级，注释里写明不要这个 hint）。页上只写一句规则，链到 README「Occupancy」一节（站点的 `packages/tileir.html` 已整篇渲染 README） | 见下 |

第 7 点不新增示例 kernel 的理由：新增一个 128×128×32 f16 matmul 带 hint，代价是 `kernels.dawn` 进 TILE_PATHS（全量
tile-golden 约 35 min 重录 + 2 h 验证）、`tile-gpu-diff` 加族条目并在本机 GPU 重跑 sm_86 台账（82 min，且只能一个写者），
sm_90 / sm_100 台账还要所有者重录；而门禁能证明的只是「`tileiras` 收下了这个 hint」，hint 让它快 17% 这件事
**没有任何门禁覆盖**（性能不在三层门里）。花一整轮 tile 台账换一个证明不了规则本身的例子，不值。

点 1 的「`run_of` 一并切出」：`cut_fn` 只切 `fn name(` 开头的函数，`run_of` 正是这种形状，直接复用。派发臂需要一个
新切法（`  "vadd" -> {` 到同缩进的 `  }`），写成 `gpu.cut_arm`，测试持有「臂里 trace 的函数名就是卡片的 kernel 名」。
`batched_matmul` 的注释切法：函数前紧邻的 `#` 块，到上一个空行为止，同样写成纯函数加测试。

## 二、页面结构

现有五节全保留，新增一节「写一个 kernel」（id `api`），放在「两层」之后、调用图之前：先看怎么写，再看一个真
kernel 写成什么。顺序：

1. 头部（标题、lede、chips、背景 Tile IR）：lede 已经说「kernel 是 `!Dev` 下的普通函数」，不动。
2. **两层**（保留）：宿主那一行的步骤 `launch("vadd")` 改成 `launch_entry3`（0.8.0 起 `traceN` 给的是带类型的 entry，
   `std/gpu.launch_entryN` 在任何 handler 跑之前查别名、网格与长度）。纯生成器里的代码词，不动文案。
3. **写一个 kernel**（新）：一句话的节导语，然后四张卡片，每张 = 一句文案 + 切出的源码（`highlight_dawn`）+ 指向
   `kernels.dawn` 行号与该 kernel `.mlir` golden 的链接：
   - 卡 A「标记即地址」：`vadd` + 派发臂 + `run_of`（点 1）；
   - 卡 B「形状从操作数来」：`softmax`（点 2、3）；
   - 卡 C「只经 Out 写」：`matmul` + 派发臂（点 4）；
   - 卡 D「逃生口 Shared」：`batched_matmul` 的注释 + 派发臂（点 6）。
   卡片下一行小字两条：点 5 的「在图里看 `reduce_max(…, keepdims: true)` / `broadcast`」（锚点 `#kernel`，gpu.js 在
   时同时选中该调用；无脚本时只是跳到图），点 7 的占用率规则一句 + README 链接；再一条「完整公开面与迁移表」链到
   `packages/tileir.html` 与 `CHANGELOG.md`。
   版式：桌面两列网格（卡片等高不强求，代码块横向滚动不撑破页面），手机单列；用现有 `gpu-fig` / `km` 的配色 token
   与 `pre code` 样式，不引新字体新颜色。
4. **一个 kernel，逐行**（保留，flash_attn 调用图）：节导语多半句，点明它就是保维归约与 rank-0 广播的那个 kernel。
   图本身、`record.py`、`flash_attn.map` 不动。
5. **覆盖率**、6. **三道门**、7. **真机台账**（保留，不动）。

`prose_sections()` 加 `("api", "api")`，搜索索引自动跟上。

### 「旧 → 新」对照上不上页面：不上

CHANGELOG 的迁移表是给手里有 0.7.0 代码的人用的，页面的读者是第一次看这个后端的人；把表搬上页面要么生成器去解析
CHANGELOG 的 Markdown 表（又一个会因排版变红的读者），要么手抄一份（会腐烂）。页上只给一条链接到 CHANGELOG。
另一种「旧 → 新」是贴 flash_attn 迁移前的写法：旧代码只在 git 历史里，不受任何门禁覆盖，违反「只贴被覆盖的代码」。

## 三、文案

新增 key（英文正本 `gpu.md` 先写，`gpu.zh.md` 跟，`doc-check` 的 translation-of 摘要重登）：`api-title`、`api-body`、
`api-cells`、`api-shapes`、`api-out`、`api-shared`、`api-keepdims`、`api-occupancy`、`api-more`；改 `kernel-body`
半句。每个一两句；代码词（`Out`、`hint_occupancy(2)`、`sm_86`）留在生成器或用反引号，与现有约定一致。数字只用
`{n}` 占位、由生成器从文件读：本节唯一可能的数字是 `Shared` 的个数，见下。

`Shared` 个数**不上页**：派发臂的文本解析不可靠（`att_qk`、`gpt_mm` 等 helper 把 trace 调用藏进函数，单行臂与块臂
并存，粗扫 179/192 臂），要准就得在 `kernels.dawn` 的 harness 里加一个 `--roles` 输出，那是 TILE_PATHS 改动，
为一个数字不值。README 的「`grep Shared(` finds every one」就是页上那句话的出处。

## 四、要不要给别的 kernel 录调用图：不要

M1 裁决按用户要求只放 flash_attn；`record.py` 每多一个 kernel 就多一份 `.map`、一条严格配对（helper 有效果、调用在宿主
控制流下都会让配对停下，softmax 能配，matmul 的 `d_range` 闭包也能配，但每个都要人看一遍）和一组测试。新节的卡片
只贴源码、链 golden，不画 IR 对照：「这段代码写出什么 IR」由下面的 flash_attn 图回答一次就够。

## 五、性能数字上不上页：不上

matmul 64³ −26.5%、128 级 +45%→−17.7% 这些数只在 §6.26 的 Markdown 表里，没有机读的证据文件，也没有任何门禁会在
它们过期时变红（性能不在三层门里）；它们是一台 3080、一天、一个驱动的读数。页面的体裁是「每个数字由仓里的门禁
记录生成」，手抄性能数破坏这条。若以后要上，前提是先有 `scripts/` 下带复现脚本的样本文件与一条检查它新鲜度的门，
那是另一刀。

## 六、门禁与触及面

- 只改 `site/`（`gen/gpu.dawn`、`pages/gpu.md`、`gpu.zh.md`、`assets/gpu.js`、`assets/style.css`）与本文、`docs/README.md`
  索引一行；**不碰 TILE_PATHS**（`kernels.dawn` 只读）。
- 本机：`dawn test site`、`site/build.sh`（带 `DAWN_SITE_PLAY_ORIGIN`、`DAWN_WASM_CC=clang-20`）、fmt、doc-check、
  gatemap 列出的其余本机项；静态服务下桌面与手机宽度截图。集群全套 `--jobs 8`。
- 新测试：四张卡片的源码等于 `kernels.dawn` 里同名函数 / 派发臂；臂里 trace 的就是卡片的函数；`keepdims` 链接指向的
  调用确实在 `flash_attn.map` 里；两份文案 key 相同。

## 七、顺带发现（不在本刀修）

`kernels.dawn` 里 `flash_attn` 上方的注释仍说「表面没有 reshape……行最大值用前后缀扫描、行和用乘全 1 矩阵」，那是
0.7.0 的写法；0.8.0 的函数体已经是 `reduce_max(s, keepdims: true)` + `broadcast`。页面只切函数体所以不受影响，但
注释过期。改它是 `kernels.dawn` 改动（TILE_PATHS，tile 输入摘要变、台账要重录），交给协调者决定并进哪一刀。

## 不做的（理由）

- 新增示例 kernel（演示 `hint_occupancy` 或「一屏讲完全部要点」的合成 kernel）：要过一整轮 tile 台账，门禁仍证明不了
  性能规则；现有四个 kernel 加 flash_attn 已覆盖七点中的六点。
- 手写演示代码或从 README 贴代码块：README 的例子不受 golden 覆盖（它的 `matmul` 是 256 常量的变体），会和真 kernel
  漂移。
- 「旧 → 新」迁移表上页：见二。
- 别的 kernel 的调用图：见四。
- 性能数字：见五。
- 页上写 `Shared` / `Out` 的计数：见三。
- 另立 GPU 站或拆出 tileir 子页：既有裁决，GPU 页在主站；完整 API 已有 `packages/tileir.html`。
