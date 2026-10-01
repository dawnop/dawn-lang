# 站点搜索：正文索引与资产契约

> 状态：**current**。2026-10-02 写于刀 4（生成器侧正文索引）动码前，钉死刀 4 产出、刀 5（reactor 查询侧）消费的
> `search-body-<lang>.json` 资产契约与分词样例表；大小实测在第六节，落地后回填。
> 方案与刀序的调研在 agent-handoff 的 `research-site-search-report-20261002.md`（§3 方案 A、§6）。

## 一、范围

站点搜索到刀 3 为止只搜标题：`search-<lang>.json` 一行一个可跳转的条目（stdlib 条目、规范与教程的节、设计史、
示例与页面），面板在 wasm reactor 里扫这些行。规范、教程和设计史的**正文**搜不到：搜 `handler state` 能找到
教程里那一节的标题，搜正文里才出现的词就是零。

刀 4 只做生成器那一半：把四份文档（规范、教程、时间线、早期设计决定）切成节和段落、分词、建倒排、出摘录，
写成第二份资产 `search-body-<lang>.json`，并让 `gen/links` 像核 items 一样核它的每个 href。查询（二分、交集、
中文候选验证、摘录高亮、懒加载）是刀 5，在 `examples/projects/tea_dom_search` 里。两刀之间只隔这份资产，
所以它的格式写在这里，两边的测试都引用本文的文字。

stdlib 不进正文索引：它的每个条目已经在第一段资产里带着签名和注释首句，`stdlib.html` 上也没有别的正文。

## 二、契约

### 2.1 资产

每种语言一份：`/assets/search-body-en.json` 与 `/assets/search-body-zh.json`，按内容指纹化
（`gen/fingerprint`），页面经属性拿到指纹名（2.4）。

顶层是**位置数组**，不是对象。理由与第一段资产相同（`site/src/gen/search.dawn` 头注）：本仓 JSON 渲染器里
对象的键序是哈希表的事实，`scripts/site-dist-diff.sh` 要求两条后端写出的字节逐一相同；数组只有一种顺序，
就是这里写的顺序。

```
[ version, sections, terms, postings, excerpts ]
```

| 位置 | 字段 | 形状 | 含义 |
|---|---|---|---|
| 0 | `version` | Int | 格式版本，**当前为 1**。格式变了就加一；reactor 不认识的版本就不加载正文，只搜标题。 |
| 1 | `sections` | `[[doc, href, title], …]` | 节表，下标即节号 `sec`（从 0 起）。 |
| 2 | `terms` | `["a", "ab", …]` | 词表，按**码点序**升序（2.3），无重复。 |
| 3 | `postings` | `[[[sec, para], …], …]` | 与 `terms` 等长：`postings[i]` 是第 `i` 个词出现过的全部 `(节号, 段号)` 对，按 `(sec, para)` 升序且无重复。 |
| 4 | `excerpts` | `[[sec, para, text], …]` | 每个被任何 posting 引用的段落恰好一条，按 `(sec, para)` 升序。 |

**`sections` 的三个字段：**

- `doc`：`"spec"`、`"tutorial"`、`"history"`、`"design"` 之一，说明这一节在哪份文档里。`history` 是时间线
  （`history.html`），`design` 是早期设计决定（`design.html`）。第一段资产把后两者都归在面板的 History 组，
  这里分开写，好让面板在摘录下面标出出处。
- `href`：站内、相对**站点根**的路径，不带前导 `/`、`./`、`../`，中文一律在 `zh/` 下。带锚点的节写成
  `spec.html#s6-5`、`tutorial/09.html#s0-2`；每页的「导言节」（2.2）不带锚点，就是页面本身
  （`spec.html`、`tutorial/09.html`）。与第一段资产的 href 同一规则，面板用同一个 `data-search-root` 拼接。
- `title`：节标题的纯文本（`html/render.inline_text`，与 TOC 显示的文字相同）；导言节的标题是页面标题
  （规范、时间线、早期设计决定取文档的 `#` 标题，教程章节取章名）。

**`excerpts` 的 `text`：** 该段落的纯文本，连续空白压成一个空格、去掉首尾空白。超过 240 个码点时截断：
在第 120 到第 240 个码点之间找最后一个空白，在那里截；这段区间里没有空白（中文段落常见）就在第 240 个码点处硬截；
截过的末尾加 `…`（U+2026，一个码点）。所以 `text` 最多 241 个码点，以 `…` 结尾**当且仅当**截过。

### 2.2 节与段落

- **节**：每页一个导言节，加上该页每个**带锚点的 h2–h4**。导言节收的是第一个带锚点标题之前的正文
  （规范页的状态框、教程章节在第一个 `###` 之前的几段）。导言节即使没有正文也占一个节号，所以两种语言的节表
  在标题结构相同时逐条对应。
- 锚点不在这里重新计算：`html/render.render_doc` 在 `Doc.heads` 里按文档顺序交出每个带 id 的标题
  （h2–h4，比 TOC 多了 h4），生成器拿第 k 个顶层 h2–h4 标题配 `heads[k]`。页面写出的 id 与这里的 href
  出自同一次调用的同一个计数器。
- 每页渲染的块与页面生成器渲染的完全相同：规范、时间线、早期设计决定是 `split_head` 之后的正文；教程是
  `split_chapters` 切出的每一章的正文（教程目录页不进正文索引，它只有章节列表）。四份文档每种语言只解析一次
  （`gen/corpus`），页面与两份搜索资产用的是同一份解析结果。
- **段落**（`para`，每节从 0 起编号）：节内按文档顺序，每个 Markdown 段落、每个列表项里的每个段落、
  每个表格行（表头行也算一行，单元格之间用 ` | ` 连接）、引用块里的每个段落各算一段。嵌在列表或引用里的
  标题算一段。代码块（含 `output` 与 `skip-check` 片段）**不进**倒排、不出摘录、**不占段号**。
  纯文本为空的单元不占段号。
- 段落有段号但一个词都切不出时（只有标点），它不出现在任何 posting 里，也就没有摘录。

### 2.3 词

`terms` 里的每个词都是对某段纯文本跑 `body_terms` 得到的；词表按码点序排（Dawn 的 `List[Char]` 比较，即
UTF-8 字节序；与 JavaScript 的 UTF-16 码元序只在 U+FFFF 以外的字符上不同）。

`body_terms(s)` 的规则：

1. 把 `s` 里每个**汉字**换成一个空格，对结果跑第一段资产的分词规则 `tokens`（刀 2 定稿，下面复述）；
2. 再按出现顺序追加 `s` 里的每个汉字，各自成为一个单字词。

汉字指 U+3400–U+4DBF、U+4E00–U+9FFF、U+F900–U+FAFF、U+20000–U+2FA1F。其他非 ASCII 的字母和数字
（`café`、`λ`、假名）仍按 `tokens` 的规则算词内字符，不拆单字。全角标点（`，`、`。`、`「」`）不是汉字，
也不是字母数字，本来就是分隔符。

`tokens(s)`（刀 2，`gen/search.dawn` 与面板共用的规则）：小写；按「不是 ASCII 字母数字、`_`、`!`、`.`、
非 ASCII 字母数字」的字符切成串；去掉串两端的 `.`；串内按 `.`、`_`、`!` 再切成片，空片丢掉；先出每一片，
串本身与唯一的片不同时再出串本身。

第一步为什么先把汉字换成空格：`inline_text` 把行内代码与正文直接拼接，中文正文里随处是 `` `Fs`效果 ``
这样的写法，拼出来是 `Fs效果`。按 `tokens` 原样切，这是一个词，`fs` 就从倒排里消失了。

一段纯文本切出的词在建倒排时去重：同一段里出现十次的词只记一个 `(sec, para)`。

### 2.4 页面怎么找到它

每页面板挂载点带上正文资产的指纹名，路径相对页面本身，与按钮上另外三个 `data-search-*` 同一写法：

```html
<div id="dawn-search" class="search-host" data-search-body="../assets/search-body-en.3f2a9c01.json" hidden></div>
```

`gen/links` 把 `data-search-body` 当作抓取的 URL 检查（存在、指纹化），并解析每份正文资产，逐条核 `sections`
里的 href：文件存在，锚点在目标页上有对应 id。

### 2.5 给刀 5 的约束（不是本刀实现，写在这里是因为它们由格式决定）

- 先读 `version`，不是 1 就不加载正文。
- 查询词按同一个 `body_terms` 切。非最后一个词按全词在 `terms` 上二分，最后一个词按前缀取区间；
  单字词（汉字）只按全词。各词的 posting 求交集得到候选段落。
- 查询里有连续两个以上的汉字时，候选还要做一次子串验证：在该段的 `text` 里找查询原串。`text` 是截断过的，
  所以验证不到时，若 `text` 以 `…` 结尾（截过），候选**保留但降级**（命中可能在被截掉的部分）；没截过的就丢掉。
- 结果落到节：同一节的多个命中段落合成一条结果，跳转到 `sections[sec].href`，摘录取命中段的 `text`。

### 2.6 大小预算

按 gzip 计：`search-body-en.json` ≤ 90 KB，`search-body-zh.json` ≤ 130 KB。超了先缩摘录长度（2.1 的 240），
再议别的。`site/build.sh` 每次构建打印两份的原始字节与 gzip 字节，超预算时在 stderr 上说明。

## 三、分词样例表

两份程序不能共享一行代码，所以规则靠同一张样例表钉住。两张表都按「输入 → 输出」逐条列出，
输出的顺序就是函数返回的顺序。

### 3.1 `tokens`（第一段资产，刀 2）

`site/src/gen/search.dawn` 的测试 `an index's words and a query's words split the same way` 与
`examples/projects/tea_dom_search/src/search.dawn` 的同名测试钉这一张：

| 输入 | 输出 |
|---|---|
| `io.read_file` | `io` `read` `file` `io.read_file` |
| `fn read_file(path: String) -> Unit !Fs` | `fn` `read` `file` `read_file` `path` `string` `unit` `fs` `!fs` |
| `6.5 Named effects` | `6` `5` `6.5` `named` `effects` |
| `Remove surrounding whitespace.` | `remove` `surrounding` `whitespace` |
| `str.` | `str` |
| `` `with handle` 命名效果，处理器 `` | `with` `handle` `命名效果` `处理器` |
| `... ! -> ()` | （空） |

### 3.2 `body_terms`（正文资产，刀 4）

`site/src/gen/search.dawn` 的测试 `a body's words split by the table in docs/site-search-design.md 3.2` 钉这一张；
刀 5 在面板里实现 `body_terms` 时，测试照抄这一张并点名本节：

| 输入 | 输出 |
|---|---|
| `io.read_file` | `io` `read` `file` `io.read_file` |
| `!io 效果` | `io` `!io` `效` `果` |
| `!Fs` | `fs` `!fs` |
| `命名效果，处理器` | `命` `名` `效` `果` `处` `理` `器` |
| `Fs效果的 handler` | `fs` `handler` `效` `果` `的` |
| `str.trim 去掉空白` | `str` `trim` `str.trim` `去` `掉` `空` `白` |
| `6.5 具名效果` | `6` `5` `6.5` `具` `名` `效` `果` |
| `café λx` | `café` `λx` |
| `全角，标点。` | `全` `角` `标` `点` |
| `... ! -> ()` | （空） |

## 四、为什么命中落在节、摘录取段落

- 能跳转的只有带 id 的标题。段落没有 id，跳到段落只能靠 Text Fragment（刀 5 可选），不能当作契约。
- 节太长，不能直接当摘录：调研量过节的中位数约 1950 字节。段落是读者扫一眼能判断「是不是这里」的单位。
- 所以倒排存 `(节号, 段号)`：节号决定跳到哪，段号决定给读者看哪一段。段落级倒排比节级大（调研的 Python 原型
  en 46 KB 对 34 KB gz），换来的是摘录能指到命中的那一段，而不是节的第一段。

## 五、为什么中文用单字

- 中文没有空格，`tokens` 把一整段汉字切成一个词，倒排里全是只出现一次的长串，查询只能做子串扫描；
  在 wasm 里逐段 `contains` 一遍要 9–17 ms（调研 §3 的实测），每次按键都扫就超帧。
- 汉字二元组（bigram）是常见做法，但调研原型里中文 bigram 倒排有 15 316 个词、段落级 118 KB gz，比全文原样
  （116 KB gz）还大，超出预算。
- 单字倒排加候选验证：常用汉字不过两三千个，词表小；查询的每个字各取 posting 求交集，候选通常几十段，
  再对候选做一次子串验证（2.5），成本可以忽略。代价是验证只能对着截断后的摘录做，见 2.5 的降级规则。
- 不引入分词词典：生成器要在 C 后端上跑（`site-dist-diff.sh`），也没有现成的 Dawn 中文分词。

## 六、大小实测

（落地后回填。）

## 七、门禁

- `./bin/dawn test site`：`gen/search_body.dawn` 的测试覆盖倒排往返（抽 20 个词，posting 指向的段落确实
  含该词）、节 href 与 `render_doc` 的锚点同源、代码块不入索引、摘录在空白处截断、版本号为 1、两种语言的节表
  等长；`gen/search.dawn` 的 3.2 样例表测试。
- `scripts/site-dist-diff.sh`：正文资产是生成器产物，两条后端须同字节；生成器不得 `use java`。
- `gen/links`：`data-search-body` 存在且指纹化；正文资产的每个 href 指向写出的页面，锚点存在。
- `gen/assets` 的语言检查只扫 `.css`、`.js`、`.mjs`，JSON 不在内；正文资产里的中文不受它约束。
- `site/build.sh` 在生成之后打印两份正文资产的原始字节与 gzip 字节，并对照 2.6 的预算。

## 八、不做的（理由）

- **Pagefind。** 它在索引期切词、查询期用 `Intl.Segmenter` 切中文查询，结果用它自己的 JS UI 或 API 画；
  引入它等于把搜索的一半交给一个不在本仓、不能在 C 后端上跑的工具，并让 `site/build.sh` 依赖网络下载。
  站点的约束是生成器两条后端同字节、面板是 Dawn reactor，这两条它都满足不了。
- **JS 搜索库（MiniSearch、FlexSearch）。** 查询本身在 JS 里更快（调研实测逐段 `contains` 快约百倍），
  但面板改由 JS 画就丢了「模型携带命中」那一刀的全部收益，搜索也不再是 Dawn 写的。倒排加二分在 wasm 里
  每键已在 1 ms 以内，不需要换。
- **汉字 bigram。** 见第五节：比全文还大。
- **段落 id 与段落级跳转。** 渲染器不给段落发 id；为搜索给每段加 id 会让每页多出上千个属性，还要 `gen/links`
  再核一遍。跳转停在节。
- **在生成器里压缩。** 预算按 gzip 计，gzip 由 nginx 的 `gzip_static`/动态压缩做；生成器没有压缩器，
  两条后端也不该各自再实现一个。gzip 字节数由 `site/build.sh` 用系统 `gzip` 量出并打印。
