# 首页「Horizon」：从定稿落到站点生成器

> 状态：**current**。2026-10-02 由定稿第十一版（设计说明见 agent-handoff 的
> `home-mock-alt-note-20261001.md`）落到 `site/`；本文动码前写成方案，落地后按实测回填。
> 实现在 `site/src/gen/home.dawn`、`site/assets/home.css`、`site/assets/home.js`、
> `scripts/site-figures.sh`。

## 一、问题

旧首页是一个 hero 加三张特性卡，文案长、只有亮色，三张卡里的 parity 卡用三行输出讲双后端。
定稿把整页做成一片天：夜在 hero，日出在安装，亮暗两套主题，加一组克制的动效。
落地要守住站点已有的三条纪律，它们决定了下面大部分取舍：

1. 页上每段程序、每行输出都由机器核对（`site/pages/*.dawn` + `.out`，`doc-check.py` 实跑对拍）；
2. 对外文案英文是正本，中文译本由摘要盯着；
3. 站点零外部请求，JVM 与 native 两个生成器写出逐字节相同的 `site/dist`。

定稿在这三条上各有缺口：数据卡的两行输出从未实跑；kernel 卡的输出条是手写的 Tile IR 片段；
867、18 两个数字没有出处；字体走 Google Fonts；脚本是内联的。下面逐条说怎么补。

## 二、页面结构

自上而下，每节一个太阳俯角标签：

| 节 | 俯角 | 内容 |
|---|---|---|
| 天空（hero） | −18° 天文晨光 | 导航（与全站同一份 `header_html` 标记，外加主题按钮）、字标、一句导语、三个小标签、两个按钮、`hero.dawn` 的编辑器窗与终端 |
| 地平线 | — | 3 px 拂晓渐变线、辉光、日月同轨（太阳里是醒着的猫，月亮里是睡着的猫） |
| 三个概念 | −12° 航海晨光 | effects / comptime / data 三卡，subgrid 五行对齐 |
| 两个后端 | −6° 民用晨光 | 分叉图（SVG，文字全部来自文案）、一句正文、三格数字 |
| GPU | −3° 破晓 | 两泳道流程板、`vadd` 与 `run` 两段源码及各自的一行真实输出、三条事实 |
| 安装 | 0° 日出 | 两张终端卡（dawnc / jar），命令末尾是 `hello.dawn` 的真实输出 |

猫取自 `site/assets/logo.svg` 的偶奇填充路径（生成器读文件现取，不复制一份）：太阳里是整条路径，
眼睛是挖空的洞；月亮里只取第一个子路径，即不带眼洞的轮廓，再画两道闭眼弧线。

壳子：首页不用 `shell`，而是复用拆出来的 `head_html` 与 `header_html`，把页头放进天空里；
其余 107 个页面的输出与改动前逐字节相同（只差资产指纹与页脚版本，实测见第七节）。

## 三、两套主题 token

> 2026-10-02 起 token、字体与主题脚本已全站共用（[site-pages-design.md](site-pages-design.md)）：
> token 在 `style.css`，切换在 `theme.js`，本节下面讲的「只在 `home.css`」是当时的状态；首页专有的
> `data-sky` 编排与日月轮转仍按本节所写。

亮暗两套 token 只在 `home.css` 里，只有首页加载这张表。三态：

- 根元素没有 `data-theme`：跟系统（`prefers-color-scheme`）；
- `data-theme="light"` / `"dark"`：覆盖系统，由按钮写入、存在 `localStorage` 的 `dawn-theme` 键里。

首屏的颜色另有一套 `--h-*` / `--sky-*`，挂在 `data-sky` 上。点按钮时 `data-theme` 立即翻转
（地平线以下的 0.3 s 过渡与夜色 1.2 s 淡入从此刻开始；过渡只挂在自己设了颜色、底色、边框或
`fill`/`stroke` 的元素上，代码窗整块直接切，理由与实测见 `docs/site-pages-design.md` 第四节），`data-sky` 在 420 ms 时才翻转，
首屏文字在夜色淡入的中段换色，深浅两种墨色在天上都还看得清（定稿第六、七版的实测结论）。
没有脚本时 `data-sky` 不存在，首屏直接跟主题走。

为了让共享样式表里的规则（搜索面板、页脚）也跟着主题走，`home.css` 把 `style.css` 的变量名
（`--border`、`--border-soft`、`--output-bg`、`--code-bg-soft`）映射到首页的 token 上；
搜索面板在 `style.css` 里写死了白底，首页另给它 `--surface`，暗色下仍可读。

## 四、动效清单

`home.css` 末尾有一条总闸：`prefers-reduced-motion: reduce` 下首页所有元素
`transition: none; animation: none`。它也关掉了 `style.css` 给导航链接的 0.15 s 颜色过渡——
没有这一条，减弱动效模式下点主题按钮仍会触发 10 个过渡（playwright 实测，见第七节）。

| 动效 | 正常 | reduced motion | 无脚本时的静止终态 |
|---|---|---|---|
| hero 入场（各行上浮淡入、编辑器随后） | 0.7 s，逐行错开 | 无，直接终态 | 全部不透明度 1（实测） |
| 终端打字 `dawn run main.dawn` 与结果落下 | 1 s 起打字，2.05 s 落下 | 无 | 命令与结果完整显示 |
| 光标闪烁 | 1.1 s | 无 | 静止的方块 |
| 字标渐变漂移 | 9 s 往返 | 无 | 静止渐变 |
| 星星呼吸、地平线辉光 | 4.5 s / 6 s | 无 | 静止 |
| 阅读进度条（`animation-timeline: scroll()`） | 随滚动 | 无 | 不支持时就是满宽渐变线 |
| 分叉图光点（SMIL） | 3.2 s 循环 | `display: none`（CSS 停不了 SMIL） | 有脚本与否都在跑；它是 SVG 自带的 |
| 「=」徽章光晕 | 与光点同周期 | 无 | 静止 |
| GPU 泳道逐个点亮 | 4.8 s 循环 | 无 | 静止 |
| 概念卡悬停上浮、图标轻摆 | 0.2 s / 0.6 s | 无 | 无悬停效果 |
| 安装终端 `hello, dawn` 发光 | 5 s | 无 | 静止 |
| 主题切换：日月轮转、夜色淡入、首屏换色、代码「暗一下」 | 1.4 s / 1.2 s / 0.4 s / 0.46 s | 状态直接跳到位 | 按钮隐藏（`hidden`，脚本才放出来），主题跟系统 |
| 数字计数 | 进入视口后 900 ms | 不计数 | 终值本来就写在标记里 |

分叉图的光点是唯一一个无脚本也会动的东西：它是 SVG 的 `animateMotion`，不经过脚本。
reduced motion 下它被隐藏，其余元素完整。

## 五、数字的来源

页面上出现的每个数字都有一个机器生产者；没有生产者的数字从页面上删掉了。

| 数字 | 生产者 | 注入路径 |
|---|---|---|
| 自举编译器行数（今天 87,586） | `scripts/site-figures.sh` 的 `selfhost_lines`：`find selfhost/src -name '*.dawn' -not -path '*/embed/*'` 拼接后 `wc -l`。与 `docs/design.md` 那句「87,586 行（口径……2026-10-01 实测）」口径一致、今天数值一致，design.md 不改 | `site/build.sh` / `site-dist-diff.sh` 经 `scripts/site-figures-env.sh` 导出 `DAWN_SITE_FIG_SELFHOST_LINES` → `gen/home.site_figures`（`getenv`）→ `fig()` |
| 差分语料程序数（今天 140） | `site-figures.sh` 的 `native_corpus`：`scripts/spike-native/matrix.txt` 去注释、去空行后的行数，过滤式与 `spike-native/run.sh` 读它时的一字不差；run.sh 每次启动都把这份清单与磁盘上的语料双向对齐，然后逐个用两个后端编译、比 stdout / stderr / 退出码 | `DAWN_SITE_FIG_NATIVE_CORPUS`，同上 |
| 版本与提交 | `DAWN_SITE_VERSION` / `DAWN_SITE_COMMIT`（沿用，页脚） | 与其他页面同一条路 |
| 「−18°」等俯角 | 不是度量，是设计里的标签 | 文案 |

为什么走环境变量：`scripts/site-dist-diff.sh` 的快照里没有 `selfhost/` 与 `.git`，两条腿继承同一
环境，所以两个后端看到同一组数字（与 `build_stamp` 同理）。变量缺失、为空、不是正整数时，
`gen/home.read_figure` 让构建失败，不给缺省值；`site-figures.sh` 自己不校验，空值原样导出，
好让负控打到生成器这道闸上。

没有生产者而删掉的：

- **18 条「两后端诊断一致」**：`native-cli-diff.sh` 里没有任何能数出 18 的东西。它的
  `check (diagnostics)` 对拍的是一个故意写错的文件，诊断条数是那个夹具的属性，
  不是「两后端诊断一致」的规模；`pair` 用例的个数要跑完整个脚本（需构建 native 驱动）才数得出，
  不适合放进建站。删。
- **867 个「差分语料文件」**：任务单要求用 `selfhost-prev-diff.sh` 列语料的那段逻辑来数。
  调研后没有照办，理由是那个数放在这一节会是一句假话：prev-diff 比的是「上一 release 与 HEAD
  在 JVM 上 emit 的字节」，十个目标（目录与单文件），从不运行 C 后端；而这一节、这张分叉图、
  定稿的说明文字讲的都是「同一份源码在 JVM 与 C 上各跑一遍，stdout / stderr / 退出码逐字节相同」。
  867 也不是 prev-diff 的数（那十个目标下共 124 个 `.dawn`），更像 `selfhost-fmt-diff.sh` 的
  「HEAD 与 N−1 共有的已跟踪 `.dawn`」——那是格式化器的语料，同样不是程序输出的对拍，
  而且算它要求本地有种子 tag。真正做「两后端跑同一程序、比三样输出」的是 `spike-native/run.sh`，
  所以这一格换成它的语料数。这是对任务单的偏离，留给协调者复核。

## 六、程序与输出

| 页上的东西 | 程序 | 输出 |
|---|---|---|
| hero 编辑器 | `site/pages/hero.dawn` | `hero.out` 整段 |
| effects 卡 | `feat_effects.dawn`（按定稿压到 34 列以内） | `feat_effects.out` |
| comptime 卡 | `feat_comptime.dawn`（同上） | `feat_comptime.out` |
| data 卡 | `feat_data.dawn`（新增；整个程序，含 `type Shape`） | `feat_data.out`：`circle 1.0` / `a point`，首次实跑，与定稿推断一致 |
| GPU 两段源码 | `site/pages/gpu_fake.project` 指向 `examples/projects/gpu_fake`；生成器从它的 `src/main.dawn` 切出 `fn vadd(` 与 `fn run(` 两个顶层函数（到第一行单独的 `}` 为止） | `gpu_fake.out` 是 `dawn run examples/projects/gpu_fake` 的完整 stdout；kernel 条取其中唯一含 `= addf ` 的一行（`%20 = addf %13, %18 rounding<nearest_even> : tile<128xf64>`），host 条取唯一以 `vadd on the fake device: ` 开头的一行 |
| 安装卡末行 | `site/pages/hello.dawn`；两张卡里的 `printf '…\n'` 由生成器用这个文件的源码拼出 | `hello.out`：`hello, dawn` |

`doc-check.py` 的 `check_site_pages` 扩了两条：`<stem>.project`（一行，指向含 `dawn.toml` 的目录）
与 `<stem>.out` 成对时运行那个项目；一个 `.out` 旁边既没有 `.dawn` 也没有 `.project` 时报红
（它会是站点能展示、却没人运行的输出）。生成器与 doc-check 读的是同一个 `.project` 文件。

定稿 kernel 卡的输出条（`cuda_tile.module @m · entry @vadd · tile<128xf64>`）是三条 test 断言
拼出来的，不是任何一次运行打印的一行；按裁决换成运行打印的那一行 `addf`。
GPU 源码按文件原样显示，不再像定稿那样为卡宽改换行：`run` 的签名 85 列，1280 px 下这一块
仍有约 98 px 的横向滚动（代码栏已从 1.1 : 1 放宽到 1.5 : 1），400 px 下两段都需要横向滚动。
改 `examples/projects/gpu_fake` 的换行会动 emit 语料与 tile golden，不在这一批。

页上代码一律由 `site/src/hl` 高亮；定稿里手工标的 `<span class="k">` 没有搬进来。
安装命令（shell）不经 Dawn 高亮器，只把 `#` 开头的注释行变暗；命令里下载的每个
`$base/<name>` 由 `doc-check.py` 对照 `release.yml` 的 `INSTALL_ASSETS`（`SITE_INSTALL_SOURCES`，与 README 同一条检查）。不放在 site 测试里：读 `.github/` 的测试在上一 release 的工具链下会失败（它从只含源码目录的根跑 `dawn test site`），`selfhost-run-diff.sh` 的 `test site` 一腿因此红过（PR #336）。

## 七、字体与脚本

- JetBrains Mono Regular / Medium 两个 woff2 与 OFL 许可放在 `site/assets/fonts/`，取自官方
  release `JetBrainsMono-2.304.zip`（zip 的 SHA-256 `6f6376c6…7bbf`）。生成器先写字体、拿到带指纹的名字，
  再把 `home.css` 里的 `url("JetBrainsMono-Regular.woff2")` 改写成指纹名（相对路径，解析到
  样式表旁边）；`home.css` 里找不到这个 `url(...)` 时构建失败。首页对 Regular 做 `preload`。
  正文与标题仍是系统 sans 栈。只有首页用这个字体；其他页面的等宽栈不变。
- `site/assets/home.js` 是首页唯一的页面脚本（搜索的 `search.js` 照旧）。它放在 `<head>` 里、
  不加 `defer`：第一件事是在首帧之前把上次选的主题写到 `<html>` 上，否则会先闪一下系统主题；
  其余事等 `DOMContentLoaded`。它不含任何文字：按钮的两种 `aria-label` 是生成器按页面语言
  写进 `data-label-dark` / `data-label-light` 的（`gen/assets.dawn` 不许共享脚本里出现中文）。
- 主题按钮在标记里是 `hidden`，脚本运行后才显示：没有脚本它什么也做不了。

实测（playwright-core 1.63，Chromium，本机起 `http.server` 伺服 `site/dist`）：
- 1280 px 与 400 px，中英两页、亮暗两种配色：`documentElement.scrollWidth`（1265 / 385）
  不大于 `clientWidth`（1280 / 400），无横向滚动；页面错误 0，站外请求 0；两个字重都加载。
- 禁用脚本且 reduced motion：`document.getAnimations()` 为 0，首屏各元素不透明度全为 1，
  主题按钮不显示，两个数字是终值。
- 开脚本且 reduced motion：点按钮前后 `getAnimations()` 都是 0（加总闸前点按钮后是 10）。
- 正常模式连点：一次后 `data-theme=dark`、`--phase: 50%`、`localStorage` 存 `dark`、
  `aria-label` 变为「Switch to light theme」；两次后 `--phase: 100%` 回到亮色；刷新后恢复暗色；
  随后打开 `/spec.html`，根元素没有 `data-theme`，页面仍是亮色。
- 其余 107 个页面与改动前（基线 `b484cea1` 的快照用同一个编译器生成）逐字节相同，
  去掉资产指纹与页脚版本后比较，0 个不同。

## 八、不做的（理由）

- **全站暗色。**（已由 [site-pages-design.md](site-pages-design.md) 做掉。）这一批只有首页有暗色 token 与切换；其他页面不读 `dawn-theme` 键、保持亮色。
  全站暗色要给教程、规范、标准库、示例、Playground 编辑器各配一套代码配色，是后续的事。
- **Google Fonts。** 定稿用它；站点承诺零外部请求，且字体文件一旦外链，渲染就依赖第三方的
  可用性与隐私条款。自托管两个字重，约 185 KB，只有首页加载。
- **内联脚本。** 定稿的主题脚本是内联的。不做：内联脚本让「不允许 `unsafe-inline` 的
  Content-Security-Policy」无从谈起，也让同一段程序以文本形式散落在两份 HTML 里、不经指纹。
  代价是一个阻塞的小文件请求，换来首帧前就能恢复主题。
- **资产 CDN 前缀开关（`DAWN_SITE_ASSET_BASE`）。** 曾作为任务单修订加入，随即撤回：整站将
  作为一个源站放在 CDN 后面，资产始终同源，这个开关没有用处。CDN 一侧（nginx 源站、缓存规则）
  是本仓库之外的生产配置，不在这一批。默认构建保持零外链。
- **定稿的 18 与 867。** 见第五节：一个没有生产者，一个的生产者讲的是另一件事。
- **定稿的发布日期（`released 2026-10-01`）。** 唯一现成的生产者是 `DAWN_SITE_VERSION` /
  `DAWN_SITE_COMMIT`；用 tag 日期需要建站时有 tag，而站点是从 main 建的，版本号所指的 release
  未必就是当前提交。页脚沿用全站的「version 0.81.0 (<commit>)」。
- **页脚的 logo 与左右分栏。** 首页沿用全站同一个 `footer_html`，只改样式；定稿里的内联 logo
  会在同一页里再放一份带渐变 id 的 SVG，全站页脚也会因此分叉。
- **导航里的内联 logo SVG。** 用全站同一个 `<img class="brand-logo">`：同一文件、已被缓存，
  也免去定稿为避免重复 id 而改的两个渐变 id。
- **首页文案里的「具名效果的内部使用者」一句。** 新的 effects 卡只有一句，不再讲谁在用这一档；
  `doc-check.py` 的 `NAMED_EFFECT_STATUS` 因此只登记 README 两份，首页移出（该处注释写明，
  卡片若再讲使用者就加回来）。
- **旧首页的 closing 段与 `line_opt`。** 「少文字」版不要 closing；`line_opt` 只为文案与生成器
  分两次提交时过渡用，生成器不再读可选节后删掉，缺节一律构建失败。
