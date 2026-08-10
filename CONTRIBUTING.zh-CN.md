<!-- doc-check: translation-of CONTRIBUTING.md @ 00e3a30c8a0e2189 -->

# 怎么在这个仓库里做事

*[English](CONTRIBUTING.md)：正本是英文，本文是它的译本，`scripts/doc-check.py` 盯着两者不脱节。*

这里只写一件事：**特性是怎么从想法走到代码的**。

提交格式、跑测试、代码风格那些，通用模板里都有，而且 CI 会管
（`./bin/dawn test selfhost`、`./bin/dawn test compiler-plan`、
`./bin/dawn fmt compiler-plan std site selfhost packages examples --check`、金样差分）——
文档写不写它们都一样。真正没被机器管住、又值得写下来的，是下面这套流程。它不是理论，
是 `docs/` 里八篇设计文档跑出来的。

## 一、动码前先写 `docs/<特性>-design.md`

不是仪式，是因为**写下来会杀死一批方案**，而在编辑器里杀死方案比在 4000 行 diff 之后
杀死便宜得多。草案开头要自报状态，别让读者猜：

> 动码前的**调研与方案**，不是设计定稿。

一份草案大致长这样（见 [`docs/unwrap-design.md`](docs/unwrap-design.md)）：

| 节 | 写什么 |
|---|---|
| 问题 | 现在**具体**哪儿疼。给真实的代码片段，不给形容词 |
| 复盘原方案 | 上一版的想法为什么不行——**最好带实测** |
| 方案 | 要做的那个 |
| 为什么不顺手把 X 也改了 | 划边界，防止范围滑坡 |
| 语法与冲突分析 | 新语法跟已有的哪儿打架 |
| 落地点 | 动哪些文件、加哪些测试 |
| **不做的（记录理由）** | 见下，这节最容易省、也最不该省 |

## 二、调研可以推翻前提——那是成功，不是失败

[`docs/seq6-research.md`](docs/seq6-research.md) 是这套流程最值钱的一次输出：它奉命去做
「值类型特化」，实测后发现 **retro 对问题的描述与代码现状有实质出入**——痛的是「物化」
不是「装箱」，而原方案对主要场景一分钱不省。于是序 6 被搁置，省下的是几千行白写的代码。

所以：**草案里的每个数字都要有出处**。「一篇文章正文 = 百万个装箱 Int」听起来很有说服力，
实测是 ASCII 下根本不成立（`Long.valueOf` 缓存 −128..127）。没实测过的性能断言，不要写进
草案，更不要写进 README——`README:99` 曾挂着一句「native 二进制启动约 7ms」，
没有任何 harness 支撑，是 `seq6-research.md` 顺手抓出来的。

## 三、「不做的（记录理由）」

每份草案末尾都有这一节。它的作用是**让三个月后的你不用把同一个方案再想一遍**——
尤其当那个方案看起来很显然、而当初否掉它的理由并不显然的时候。
`unwrap-design.md` 的「为什么保留 Option 包装（不顺手取消）」就是这类。

## 四、实现完，回填

草案不是写完就扔的。落地后：

- 大改动开一份 `docs/history/m<N>-progress.md`，逐条记状态，**回填提交哈希**，
  写明「供中断后接续」（见 [`docs/history/m7-progress.md`](docs/history/m7-progress.md)）。
  跨仓的活儿要注明两边的哈希——语言本体在 `dawn-lang/`，后端在 `dawnop-site/backend-dawn/`。
- 草案里被现实推翻的前提，**回头改掉那份草案**，别留着骗人。
- 里程碑做完写 `docs/history/m<N>-retro.md`：复盘 + 排下一批的修复优先级表
  （[`docs/history/m6-retro.md`](docs/history/m6-retro.md) 那张表直接变成了 M7 的序 1–6）。

> 历史哈希是会失效的：仓库为清理 trailer 重写过一次历史，随后专门发了一个提交回填
> 文档里失效的 11 处引用。回填哈希时留意这件事。

## 五、提交信息

一行英文祈使句，不带 `type(scope):` 前缀——这个仓库的代码、注释、提交信息统一用英文
（`docs/` 用中文）。正文写**读代码看不出来的东西**：根因、被推翻的方案、实测数据、
验证手段。不写「改了什么」——那个 diff 里有。

**改变工具链输出**（发出来的字节码、C 文本、CLI 文本、格式化结果、LSP 响应）时，正文里
**为每一个被改动的检查 label 各加一行** `Emit-Change(<label>): <说明>`。label 是差分脚本
打印的那个检查名——`emit selfhost`、`emit packages/json`、`run calc (args)`、`fmt`、`lsp`——
必须逐字出现在 [`scripts/emit-labels.txt`](scripts/emit-labels.txt) 里。
`selfhost-prev-diff.sh` / `run-diff` / `fmt-diff` / `lsp-diff` 会拿 HEAD 和上一个 tag 对拍，
**没有匹配声明的差异是 CI 红灯**（REL-02，`scripts/emitchange.sh`）。

> **不接受通配，也不接受裸 `Emit-Change:`**（#124）。`emit *` 会把**将来才新增的
> label** 一起豁免，同一句提交信息随语料增长而放行得越来越多；而裸 `Emit-Change:` 最
> 常见的历史写法是 `Emit-Change: none`——作者想说「什么都没变」，效果却是放行**所有**
> 差分的**所有** label。改动真的动了六个语料就写六行：v0.48.0 那次改 class-file 版本
> 就是这么写的，代价就是六行。解析不了的声明、以及 `emit-labels.txt` 不认识的 label，
> 一律报错而不是变成一条永远匹配不上的规则。完整规则与推翻掉的方案写在
> `scripts/emitchange.sh` 头部，`scripts/emitchange-selftest.sh` 是它自己的门禁。
>
> 有个坑没变：脚本查的是**上个 tag 到 HEAD 整段**里的声明，不是逐个提交查。
> 所以同段里一条声明会替后面同 label 的差异挡灯。**先跑门禁、再写这一行**，
> 否则你看到的绿是别人的声明挡出来的。#124 把「没人看过的 label 也被豁免」这半
> 堵死了，剩下的一半——同一个 label 的差异变大——只有 golden 快照进仓库才能关，
> 记在 `docs/codebase-audit.md` 的 REL-02 里，没做。

**绝不加 Claude 署名**（`Co-Authored-By` / `Claude-Session` 一概不要）。本项目以开源为标准。

## 六、契约：别单方面改

后端 [`dawnop-site`](https://github.com/dawnop/dawnop-site) 的生产服务跑在这个编译器
产出的代码上。它按 `.dawn-version` 钉住某个 release，所以：

- 语言的破坏性改动要先发 tag，再由那边提一个 bump `.dawn-version` 的提交；
- 两边一起改的过渡期，那边把 `.dawn-version` 写成 `main` 现编，但**别让它长期留在 main 上**——
  那期间可复现性是没有的。

发布：改 `selfhost/src/version.dawn` 的 `VERSION` **和 `std/VERSION`**（std 目录自己盖的
release 戳，编译器拿它认出「这个 std 不是我发布时那个」，见 `driver/stdlib.load_std`；
两者不一致时 `driver/stdlib` 的 `std/ stamps itself with this toolchain's version`
测试会红）→ 提交 → `git push origin main` 并等
main CI 通过 → `git tag v0.9.0` → `git push origin refs/tags/v0.9.0`。禁止
`git push --tags`，它会把无关 tag 一起发布。`release.yml` 会校验 tag 与 version 一致、
跑全量测试、把 `dawn-selfhost.jar` 与 native 资产传上 Release。四件资产发布完成后只运行
`./scripts/advance-seed.sh v0.9.0`；它会校验 GitHub Release 的 JAR 与远端 tag archive
的 std，并按摘要清单、std 清单、指针的顺序同步推进三份 seed 文件，不得只手改
`seed-release.txt`（完整协议见 docs/bootstrap.md）。
`doc-check.py` 会把文档里声称「当前工具链是几」的那几处也一起校到 `version.dawn`，
所以改完 `VERSION` 那一趟 CI 会点名剩下没跟上的行——README 那句曾经落后 38 个小版本，
靠人读发现的。

## 七、命名族：std 的准入判据

一次审计（`docs/audit/re-audit-2026-07-30.md` RD-06）数出长度四个名字、判空只在一个
零调用者的模块存在、转换五种命名法。下面这几条是那次收口留下的**准入判据**——
新加一个 std 或包的 pub 名字时对着看，不是历史记录。

- **一个概念一个名字。** 长度是 `len`，判空是 `is_empty`，`str`/`list`/`map`/`set`/`bytes`
  五处逐字相同。具名例外只有两个，都出在 `Buf` 上、都是同一个原因（Dawn 无重载，
  而 `Bytes` 那一侧先占住了对的名字）：`bytes.size(b: Buf)` 让开 `bytes.len(b: Bytes)`，
  `bytes.buf_at(b: Buf, i)` 让开 `bytes.at(b: Bytes, i)`。例外要**在代码里写明为什么**，
  否则下一个人会照抄成惯例。让路的方向也是判据的一部分：**把对的名字挪走给错的名字腾地方
  是反的**——`bytes.at` 按下面的三判据已经叫对了，所以改名的是 `Buf` 那一侧。
- **名字要说出越界时会发生什么（spec §4.8 三判据）。** 这是 v0.54.0/v0.55.0 那批改名的
  唯一依据，`at` / `get` / 区间函数各归其一：
  - **判据 1（断言，panic）** 的词是 `at` 与 `[]`：参数是一个**位置**，调用方声称它存在，
    越界是 bug。`str.at`、`bytes.at`、`pvec.index`/`nth`。
  - **判据 2（问询，`Option`/`Bool`）** 的词是 `get`：越界/缺席是调用方要分的正常分支。
    `list.get`、`map.get`、`index_of` 族。
  - **判据 3（钳位，永不 panic）** 是区间函数：`slice`、`take`、`drop`、`seek`。参数是
    一个**区间或落点**，说的是「要这一段里有的部分」，不断言端点存在。
  一个名字**不能同时扛两条政策**。`cursor.at` 曾经是钳位的、`str.at` 是 panic 的，
  同一个词的含义取决于读者当时在哪个模块里——那不是取舍，是缺陷；解法是改名
  （`cursor.at` → `cursor.seek`），不是把两者统一到一条政策上，因为两者各自都是对的。
  `bytes.get(b: Buf, i)` 是同一类缺陷的另一面：它 panic，却用了判据 2 的词。
- **改破坏性的名字走「一代转发器」。** 新名字与旧名字同期上线，旧的降为一行转发器并在
  文档注释里写明「下一版删除」；下一个 release 才删旧名、迁调用点。理由是机器的：
  `bin/dawn` 的 stage 1 用**种子自带的那份 std**编译今天的 `selfhost/src`（见脚本里的
  注释），所以 selfhost 的调用点**必须晚一代**才能改；一期做完的改名会在自举第一步就红。
  先例：RD-06 的 `of_array`、本批的 `str.slice`/`cursor.seek`/`bytes.buf_at`。
- **转换是 `to_X` / `from_X`。** `to_hex`/`from_hex`、`to_base64`/`from_base64`、
  `to_array`/`from_array`、`to_list`。领域动词只在**名字本身承载语义**时留下：
  `bytes.freeze` 是「结束 `Buf` 的扩展契约」，不是「转成 Bytes」；`bytes.utf8` 点名的是
  编码而不是目标类型。判据是「换成 `to_X` 会丢掉一句话吗」——会，就留动词。
- **增删按容器种类分。** 有键的容器是 `insert`/`remove`（`map`、`set`）；
  只往末尾追加的构造器是 `put`/`push`（`bytes.Buf`、`Array`）。同一个模块里不要两套。
- **表示是内部模块。** `std/hamt`、`std/pvec` 持有 `Map`/`Set`/`List` 的表示，
  std 之外 `use` 它们是编译错误（`checker.internal_std_modules`）。判据是
  「换掉这份实现会不会破坏别人的程序」——会，说明它不该是公开的。
  同一条判据在包里更硬：包的 `pub` 有版本号背书（RD-12）。

## 八、对外文案：先改英文

这个仓库的代码、注释、诊断、提交信息一律英文，`docs/` 一律中文——这两条没变。
变的是**对外那一层**：

- **`README.md` 是英文原文**，`README.zh-CN.md` 是它的译本。
- **本文是英文原文**，`CONTRIBUTING.zh-CN.md` 是它的译本。它进对外层进得晚，漏掉的原因值得
  点名：这一层的范围过去是按「站点渲染的那些」划的，而那只是「陌生人会读的文档」的一个近似，
  唯独这一份除外。GitHub 把这份文件渲染给每一个打算来提交的人，它正是近似与被近似者
  分道扬镳的那一份。
- **站点 `/` 出英文**（`site/pages/home.md`），`/zh/` 出中文（`home.zh.md`）。
- **教程与标准库导语**同样以英文为正本，中文是译本。
- **规范与设计笔记反过来**：中文是正本、英文是译本（`spec.en.md` / `design.en.md`）。
  它们是活文档，每次改语言都在中文里改，让英文当正本等于要求每次语言改动先写英文——
  这么贵的规矩会被跳过，而跳过之后腐烂又回到看不见的那一面。
- `docs/` 其余部分（设计方案、计划、落地日志）**只有中文，不翻译**，站点每一版首页都写明。

**改对外文案时先改英文，再改中文译本。** 译本头上带
`<!-- doc-check: translation-of <原文> @ <digest> -->`，`scripts/doc-check.py` 会算原文的
摘要跟它比；英文动了而中文没跟，CI 红。登记表在那个脚本的 `TRANSLATIONS`——**摘要没了
不等于不检查**，删掉标记同样红。

为什么对外层是这个方向：派生的那一份才会腐烂，而对外层的读者大多不读中文。让英文当派生物，
等于把腐烂藏在最多人看、最没人校对的那一面；反过来腐烂落在中文上，而中文的读者是作者本人。
唯一的代价是作者用中文思考，所以这条规矩不靠记性，靠上面那道门禁——**规范与设计笔记正是
代价压过收益的那一对，所以它们的正本留在中文，门禁照样两头盯**。

摘要算什么、不算什么（段落重排不算改、代码块逐行算改、版本号不算——`check_version`
已经独立管着两边）写在 `translation_digest` 的注释里。**不设「译本落后」的豁免**：
一个可以永远开着的豁免等于没有门禁。
