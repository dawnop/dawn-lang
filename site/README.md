# site/ — Dawn 语言网站（M5）

静态站点，**生成器用 Dawn 写**（dogfood M4 的模块系统 / Map / 字符串 API）。
产物是 HTML + CSS（代码高亮在构建期完成，内容页零 JS）；nginx 托管。唯一的例外是
Playground——它带一份编辑器 bundle，并需要后端的 `/api/run`、`/api/check`。

- 域名：`https://dawn-lang.dawnop.com`（与 GitHub 仓库名一致）
- 验收：站点上线，且生成它的程序是 Dawn 写的；生成器 JVM 与 native 跑出的
  `dist/` **逐字节一致**——由 `scripts/site-dist-diff.sh` 管着（进了 CI）。
  这一条曾经只是一句话：2026-08-05 之前没有任何东西跑它，而人手跑的 `diff -r`
  直接读工作树，分不清「两个后端不一致」和「两次构建之间输入被改了」——2026-08-04
  真把后者报成了前者。现在两个后端都跑在**同一份输入快照**上，工作树怎么动都进不来。
  同期发现：生成器里两行 `use java`（favicon 那次带进来的）让它**根本无法编到 native**，
  于是这条「传统」有一个里程碑是空的；那两行已换成 `io.read_bytes`/`write_bytes`。

## 目录

```
site/
├── src/            # 生成器（纯 Dawn，dawn run site 直接跑）
│   ├── main.dawn   # 组装：读 docs/ + examples/ → 写 dist/
│   ├── gen/copy.dawn  # 首页文案（`## key` 分节的 Markdown），不再是 Dawn 里的字符串字面量
│   ├── gen/assets.dawn  # 共用资产的语言检查：CSS `content:` 注入的字，两棵树各一份
│   ├── gen/fingerprint.dawn  # 资产文件名里的内容哈希（sha2），配 /assets/ 的 immutable 头
│   ├── md/         # Markdown 子集解析器
│   ├── hl/         # Dawn 语法高亮 tokenizer（构建期）
│   └── html/       # 转义、模板壳、TOC、slug
├── assets/         # style.css 等文本资产（内容不变，名字带哈希后拷入 dist/assets/）
├── pages/          # 站点专属内容（home.md 正本 / home.zh.md 译本；首页样例与特性卡的 .dawn + 实测输出 .out）
├── play-ui/        # Playground 编辑器（TS + CodeMirror 6，npm 构建）
│   └── samples/    # 侧边栏的起手程序：真 .dawn + 实测 .out，由 samples.ts 用
│                   # Vite `?raw` 内联。以前是 TS 模板字符串里的代码，任何按 .dawn
│                   # 找的工具都看不见它——v0.43.0 退役 fn lambda 时就漏了这里，
│                   # 八个版本里侧边栏一直发着编不过的程序。现在 doc-check 跑它们
├── sample/         # 手写验收样张 —— 渲染以此为准绳（验收样例先行）
└── dist/           # 产物（gitignore）
```

内容单一来源 = 仓库根的 `docs/*.md` 与 `examples/**`，**不复制不搬家**。

## 语言：英文是默认，中文是译本

**站点默认语言是英文**：`/` 出英文，同一路径的中文版在 `/zh/`，两页互挂 `hreflang`
（`x-default` 指英文）、导航条上有互跳入口。**每一页都成对**：首页、教程、示例、标准库、
规范、设计、Playground。

多数对子里英文是正本，方向是刻意反过来的：**派生的那一份才会腐烂**，而对外那一层的读者
大多不读中文。让英文当派生物，等于把腐烂藏在最多人看、最没人校对的那一面。反过来腐烂落在
中文上，而中文的读者是作者本人。**规范与设计笔记是唯一的例外**（2026-08-07）：它们是活
文档，每次改语言都在中文里改，所以中文是正本、`spec.en.md`/`design.en.md` 是译本——摘要
门禁两个方向都一样盯。

配套是机器强制的：首页文案从 `site/src/gen/pages.dawn` 的字符串字面量搬进了
`site/pages/home.md`（正本）与 `home.zh.md`（译本），译本头上带
`<!-- doc-check: translation-of site/pages/home.md @ <digest> -->`；英文一改、中文没跟，
`scripts/doc-check.py` 就红。摘要怎么算（重排不算改、代码块逐行算改、版本号不算）
写在那个脚本的 `translation_digest` 里。**改文案先改英文。**

上面这套只管**经过 `Lang` 的字符串**。`style.css` 两棵树共用、又不经过生成器，所以
`content:` 注入的字曾整整绕开双语化：英文页的输出块角标写着「输出」，从首页翻译那天起
一直到 2026-08-08（读者报的）。现在默认写英文、中文由 `html[lang="zh-CN"]` 覆盖，
`site/src/gen/assets.dawn` 在每次构建里盯三条：未限定的 `content:` 不许带中文；
选择器只能钉站点真发得出的 `lang`；带字的 `content:` 必须每种语言各有一份。

## 资产缓存

`/assets/` 由 nginx 发 `Cache-Control: max-age=31536000, public, immutable`——这句话是对
**URL** 的承诺：这个地址的字节永不改变。而站点一直把它挂在 `style.css` 这种名字上，于是
改样式对老访客等于没改：他们手上那份要到 2027 年才过期。2026-08-07 修的输出块角标就是
这么被卡住的。

改的是名字，不是响应头。`gen_assets` 把每个资产按内容算 sha256、取前 8 位嵌进文件名
（`style.<hash8>.css`），页面只链这个名字；字节一变名字就变，缓存里的旧副本再也不会被
请求，而 `immutable` 从此是真话。哈希只依赖字节，所以 `scripts/site-dist-diff.sh` 的
JVM/native 逐字节对拍照旧成立。

每个资产**同时**再写一份原名（`style.css`）。这是过渡件不是第二份资产：HTML 每次访问都
回源校验，一两次访问后没人再问原名了；但改动上线那一刻，手里还揣着旧 HTML 的访客问的
正是原名，而 `redeploy.sh` 用 `rsync --delete`——少了这份别名他们拿到的是 404 和一张
没有样式的页面。等旧 HTML 不再可能留在任何缓存里，这份别名就可以删。

两道门禁盯着这件事，各盯一个方向：`gen/assets.dawn` 的别名配对（丢了原名 → 老访客 404；
丢了哈希名 → 又回到不带版本的 URL），`gen/links.dawn` 的链接检查（页面链进 `assets/` 的
每个引用都必须带哈希——只查存在与否是查不出来的，两个名字都在盘上）。

demo 页的 wasm 和 DOM 桥走同一条路，但多两笔。一是桥的四个 `.mjs` **相互 import**，
哈希改了名字，所以 `emit_bridge` 按依赖序（wasi ← reactor，dom ← app）把每个
import 说明符改指到目标真正拿到的名字上；改不动就 panic，因为一个指向不存在文件的
import 是这个站点任何检查都看不见的（`gen/links` 只读 `href=`/`src=`）。二是页面
要 fetch 的 wasm 写成元素上的 `data-wasm=`（而不是脚本里的字符串），就为了让链接
检查照常管它。

## 信息架构（URL 映射）

| 路径 | 内容 | 来源 |
|------|------|------|
| `/` | **首页（英文，正本）**：定位一句话 + 高亮样例 + 特性栏 + 各区入口 | `site/pages/home.md` + `hero/feat_*.dawn` 与同名 `.out` |
| `/zh/index.html` | 首页（中文译本）：内容同上 | `site/pages/home.zh.md` + 同一批 `.dawn`/`.out` |
| `/tutorial/{01..17}.html` | 教程 17 章，每章一页，带上一章 / 下一章 | `docs/tutorial.md` 按 `##` 切分 |
| `/tutorial/index.html` | 教程目录页 | 同上（章标题清单） |
| `/spec.html` | 语言规范单页 + 侧栏 TOC | `docs/spec.en.md` |
| `/zh/spec.html` | 同上（中文正本） | `docs/spec.md` |
| `/design.html` | 设计笔记（D1–D7 决策 + 里程碑） | `docs/design.en.md` |
| `/zh/design.html` | 同上（中文正本） | `docs/design.md` |
| `/examples/index.html` | 示例陈列页：按 `examples/<组>/` 分组，每例一句描述（取自文件头注释的第一段） | `examples/**` + `gen/examples.dawn` 的分组表 |
| `/examples/{name}.html` | 每例一页：高亮源码（+ 多文件项目按模块列出） | 同上 |
| `/stdlib.html` | 标准库 API 参考 + 侧栏 TOC：内建类型、prelude、预置 trait、每个 std 模块（函数 / 类型 / impl），文档注释按 Markdown 渲染 | `site/pages/stdlib.md` + `dawn doc --stdlib` |
| `/playground.html` | 在线编辑器：CodeMirror 6 + Dawn 高亮、实时诊断、补全；运行/检查打后端 | `site/play-ui/`（npm 构建，产物由 `gen_assets` 搬进 `dist/assets`） |
| `/tea.html` | **浏览器 demo**：两个 wasm reactor（计数器 + 键控待办）挂在页面上跑 | `examples/projects/tea_dom_{counter,todo_keyed}`（`site/build.sh` 编译成 wasm）+ `packages/tea-dom/js/*.mjs`（桥），二者都由 `gen_assets` 搬进 `dist/assets` |
| `/zh/tea.html` | 同上（中文译本；两个应用本身画的是英文） | 同上 |

## 渲染约定

- **Markdown 子集**（docs 实际用量驱动，遇到解析不了的语法**报错退出**，
  生成器兼任 docs 的 lint）：
  - 块级：`#`/`##`/`###` 标题、段落、围栏代码（带语言标记）、无序列表（嵌套）、
    有序列表、表格、引用、`---` hr。
  - 行内：`` `code` ``、`**bold**`、`*em*`、`[text](url)`。行内码优先于表格分列
    （单元格里的 `|` 在反引号内不作分隔）。
- **围栏语言**：`dawn` → 构建期高亮；`dawn skip-check` → 同 `dawn`（剥掉标记）；
  `output` → 输出块（CSS 加「输出」角标）；其余（`bash`、裸块）→ 只转义不高亮。
- **锚点**：标题用编号 id（`#s2-3` = 第 2 节第 3 小节），不做中文 slug。
- **高亮类名**（GitHub Light 配色）：`k` 关键字、`t` 类型/构造器（大写首字母）、
  `f` 定义名（`fn` 后的标识符）、`s` 字符串、`i` 字符串内 `$` 插值、`n` 数字/布尔、
  `c` 注释。函数**调用**不着色（tokenizer 保持行级简单）。
- **资产搬运**：CSS 等文本用 `read_file`/`write_file`；品牌标记（`logo.svg` 与由它渲染出的
  favicon / 触摸图标 / og:image，见 `scripts/render-brand.py`）用 `io.read_bytes`/`write_bytes`
  逐字节拷——SVG 是文本也照拷，被哈希的必须就是被写出的那串字节（曾经是 `use java` 的
  `FileInputStream`，那让整个生成器编不到 native，见开头的验收条）。
- 生成后扫一遍内部 `href`，断链即失败退出。

## 分刀进度

- [x] 刀 0：验收样张（`sample/tutorial-04.html`、`sample/spec-excerpt.html`）+ 本 README
- [x] 刀 1：stdlib IO 补齐（`list_dir` / `is_dir`；`write_file` 自动建父目录）
- [x] 刀 2：`dawn doc`（`##` 文档注释提取 + `--builtins` JSON）
- [x] 刀 3：Markdown 子集解析器（Dawn）
- [x] 刀 4：Dawn 语法高亮器（Dawn）——中途顺手给语言加了反引号 raw string（0ae0a75）
- [x] 刀 5：HTML 渲染 + 模板 + CSS（Dawn）
- [x] 刀 6：main 组装 + 全量生成 + 断链自检（32 页 / 318 内链）
- [x] 刀 7：验证（31 个 test 块绿；`fmt --check` 干净；**JVM 与 native 产物逐字节一致**——
      当时是人手跑的，2026-08-05 才变成门禁 `scripts/site-dist-diff.sh`）
- [x] 刀 8：部署 `dawn-lang.dawnop.com`（nginx + 通配符证书 + `redeploy.sh`）——
      2026-07 上线，此后一直在跑

## 构建

```bash
site/build.sh          # dawn doc --stdlib → play-ui → tea reactors → 清空 dist → dawn run site
# demo 的两个 wasm 要 clang 20+（带 wasm32 sysroot）。缺了就跳过并 warning，
# 生成器写占位文件，demo 页面自己报错，其余页面不受影响：
DAWN_WASM_CC=/usr/bin/clang-20 site/build.sh
# `--target wasm` 只在原生驱动里（selfhost/src/nmain.dawn），编一次约 37s，
# 按编译器自己的 source stamp + runtime/c 缓存在 site/build/tea/dawnc。
# 或手动：
./bin/dawn doc --stdlib > site/build/stdlib.json
./bin/dawn run site    # 生成 site/dist/（从仓库根运行）
./bin/dawn test site   # 生成器测试

# 首页那四段代码（hero + 三张特性卡）真的编译、真的跑，输出对着同名 .out 比：
./scripts/doc-check.py
# 两个后端的 dist 逐字节对拍（输入先快照，工作树动了也进不来）：
./scripts/site-dist-diff.sh
```

站点的内容源是 `docs/**` 与 `examples/**`：**改了它们的提交一合进 main，就得跑一次
`site/redeploy.sh`**——CI 只重建 `dist/` 用来对拍，不发布。2026-08-07 漏了这一步，
线上的规范页旧了两天。
