# Playground 栏宽可拖动与滚动条统一

> 状态：**current**。用户反馈「不同的栏的间距要支持拖动；代码区和 generated code 区域滚动条的样式好像不一样」的方案与落地记录。实现在 `site/play-ui/src/panes.ts`，用例在 `site/play-ui/test/panes-selftest.ts`。

## 边界盘点

页面实际有三条可拖的边界，都在 `site/play-ui/src/main.ts` 搭的 DOM 里：

| 名字 | 两侧 | 宽屏 | 窄屏（≤ 44rem） |
|---|---|---|---|
| `side` | 样例列表 \| 编辑器列 | 竖线，左右拖 | 不显示：样例列表变成编辑器上方的横条，没有可拖的边 |
| `view` | 编辑器 \| Generated Code | 竖线，左右拖 | 横线，上下拖：生成代码堆在编辑器下面 |
| `out` | 编辑区 \| Output 控制台 | 横线，上下拖 | 同左 |

`view` 与 `out` 随各自的面板显示隐藏（`hidden` 属性上挂一个 MutationObserver），面板关着时没有边界。
窄屏的断点就是 `playground.css` 已有的 `@media (max-width: 44rem)`，`main.ts` 用同一个
`matchMedia` 判断，不另立一个数。

## 方案

- **元素**：每条边界是一个 `div.dp-split`，`role="separator"`、`tabindex="0"`、`aria-orientation`、
  `aria-controls`（指向它调的面板）、`aria-valuenow/min/max`（面板占容器的百分比与夹紧范围）。
- **拖动**：Pointer Events 一套同时覆盖鼠标、触摸与笔；`pointerdown` 上 `preventDefault` +
  `setPointerCapture`，分隔条本身 `touch-action: none`，拖动期间根元素挂 `dp-resizing`，
  其下 `user-select: none`，所以拖过编辑器和清单时不会选中文字（Playwright 实测拖完
  `getSelection()` 为空串）。
- **键盘**：沿轴方向键一步 16px，Shift 四倍；Home/End 到最小/最大。方向按屏幕走：
  竖线上 Left 永远把线往左移，不管被调的面板在线的哪一侧。
- **最小尺寸**：样例列表 8rem，编辑器列至少留 24rem；生成代码宽屏 14rem、编辑器留 16rem；
  窄屏生成代码 6rem、编辑器留 7rem（原有的 `min-height: 7rem`）；控制台 4.5rem、上方留工具条 + 7rem。
  夹紧在一个纯函数 `clampSize` 里：容器小到两边都放不下时，被拖的面板保住自己的最小值。
- **记忆**：存比例不存像素（笔记本上拖好的分割换到宽屏还是同一个分割），按布局分键
  （`wide` / `narrow`，同上断点），整体存在 `localStorage['dawn-playground-panes']`。
  读写都包 try/catch，存储不在、抛错、内容是垃圾一律当「没记住」。没拖过就什么也不存，
  布局由样式表决定；**双击边界 = 忘掉比例**，尺寸交回样式表。
- **随窗口变化**：比例在应用时按容器当前尺寸换成像素再夹紧；`ResizeObserver` 盯 `.dp-ide`，
  窗口变了就重算，所以窗口缩小后面板也不会被挤出视野。
- **CodeMirror 重排**：每次改尺寸调 `view.requestMeasure()`。CM6 自己也有 ResizeObserver，
  主动请求是为了让重排和拖动落在同一帧。
- **命中区**：8px（粗指针 20px），用负 margin 叠在原有的边框线上，不占布局宽度；
  并且只向**线后**那个面板伸出，因为线前的面板（编辑器、清单）恰好把滚动条贴在这条边上，
  命中区盖住它会抢走拖滚动条的手势。

不引入依赖：现有依赖（CodeMirror 6 各包、lsp-client）没有分栏组件；需要的只是一个 pointer
处理器加一个夹紧函数，比任何 split-pane 包的配置对象还小。实测 bundle 增量（`vite build`，
gzip -9）：`playground.js` 156,626 → 158,370 字节（+1,744），`playground.css` 3,038 → 3,516（+478）。

## 滚动条：差异来源与统一

| 区域 | 改前来源 | 改前样子（Chromium） |
|---|---|---|
| 编辑器 `.cm-scroller` | 无任何规则，浏览器默认 | 15px 经典滚动条，带箭头和灰色轨道 |
| Generated Code `pre.xp-code`（C / JVM / Tile IR 三个标签共用这一个元素） | `style.css` 的 `pre { scrollbar-width: thin; scrollbar-color: var(--line) transparent }` 与 `.xp pre.xp-code { scrollbar-width: thin }` | 细条、`--line` 色滑块、透明轨道 |
| 控制台 `.dp-console`、样例列表、编译错误框、补全浮层 | 浏览器默认 | 同编辑器 |

统一后由 `playground.css` 一条规则管 `.dp-ide` 里所有会滚动的区域（编辑器、生成代码、控制台、
样例列表、编译错误框、references 面板、补全列表与文档浮层）：

- 颜色取站点 token：滑块 `--faint` 45%、悬停 75%，轨道透明；亮暗两套主题跟着 token 走，
  不另写一份暗色值。
- Firefox 只认 `scrollbar-width: thin` + `scrollbar-color`。
- 有 `::-webkit-scrollbar` 的引擎（Chromium、Safari）里，标准属性一旦设置在 Chromium 上会压过
  伪元素，而 Safari 没有 `scrollbar-color`；所以在 `@supports selector(::-webkit-scrollbar)` 里把标准
  属性复位为 `auto`，由伪元素画 10px 圆角滑块，两种引擎同一条路径。
- 只在 `(pointer: fine)` 下画伪元素：手机浏览器是来去的覆盖式滚动条，画成常驻的条反而盖住代码。
- 没改 `style.css` 的 `.xp` 规则（另一个分支在改那里的选中样式）；这里只是用更高的特异性
  （`.dp-ide .dp-view pre.xp-code`）覆盖滚动条这两个属性。

## 验证

- `npm test --prefix site/play-ui`：`panes-selftest.ts` 覆盖拖动改比例、两端夹紧、键盘步进与
  Home/End、窄屏换轴、双击复位、重载读回、`localStorage` 抛错时回退默认但拖动照常；另有三条
  断言钉住编辑器与清单在同一条滚动条规则里。负控：把 `clampSize` 改成原样返回，8 条用例变红。
- Playwright（Chromium 1440×900 亮/暗、390 手机；WebKit 亮/暗看滚动条）：三条边界拖动前后、
  双击复位、键盘、极端拖动后编辑器宽 256px（= 16rem 下限）。

## 不做的（理由）

- **不让侧栏在窄屏可拖**：那里它是一行横向滚动的文件条，高度由内容决定，拖动没有意义。
- **不做折叠（ARIA window splitter 的 Enter 折叠）**：样例列表与生成代码各自已有开关
  （生成代码有关闭按钮，侧栏在窄屏自动收成横条），再加一种折叠是第二个开关。
- **不按具体像素宽度分桶记忆**：只分宽/窄两种布局；同一种布局里比例已经随视口缩放，
  再按 1280/1440/1920 分桶只会让用户在不同窗口里看到不同的「记住」。
- **不改站点其它页面的滚动条**：问题只在 Playground 两栏并排时显眼；全站统一是另一件事。
