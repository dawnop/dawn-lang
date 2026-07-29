# 怎么在这个仓库里做事

这里只写一件事：**特性是怎么从想法走到代码的**。

提交格式、跑测试、代码风格那些，通用模板里都有，而且 CI 会管
（`./bin/dawn test selfhost`、`./bin/dawn fmt site selfhost packages --check`、金样差分）——
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

- 大改动开一份 `docs/m<N>-progress.md`，逐条记状态，**回填提交哈希**，
  写明「供中断后接续」（见 [`docs/history/m7-progress.md`](docs/history/m7-progress.md)）。
  跨仓的活儿要注明两边的哈希——语言本体在 `dawn-lang/`，后端在 `dawnop-site/backend-dawn/`。
- 草案里被现实推翻的前提，**回头改掉那份草案**，别留着骗人。
- 里程碑做完写 `docs/m<N>-retro.md`：复盘 + 排下一批的修复优先级表
  （[`docs/history/m6-retro.md`](docs/history/m6-retro.md) 那张表直接变成了 M7 的序 1–6）。

> 历史哈希是会失效的：仓库为清理 trailer 重写过一次历史，随后专门发了一个提交回填
> 文档里失效的 11 处引用。回填哈希时留意这件事。

## 五、提交信息

一行英文祈使句，不带 `type(scope):` 前缀——这个仓库的代码、注释、提交信息统一用英文
（`docs/` 用中文）。正文写**读代码看不出来的东西**：根因、被推翻的方案、实测数据、
验证手段。不写「改了什么」——那个 diff 里有。

**改变工具链输出**（发出来的字节码、C 文本、CLI 文本、格式化结果、LSP 响应）时，正文里加一行
`Emit-Change(<label glob>): <说明>`。label 是差分脚本打印的那个检查名——
`emit selfhost`、`emit packages/json`、`run calc (args)`、`fmt`、`lsp`——glob 支持 `*`。
`selfhost-prev-diff.sh` / `run-diff` / `fmt-diff` / `lsp-diff` 会拿 HEAD 和上一个 tag 对拍，
**没有匹配声明的差异是 CI 红灯**（REL-02，`scripts/emitchange.sh`）。

> 裸 `Emit-Change: <说明>`（不带括号）仍被接受，但语义是**通配**——一行放行所有 target
> 的任意差异，这正是 REL-02 修的洞。新声明请带 scope；两个后端并存之后，
> 不带 scope 的声明说不清改的是谁的输出。
>
> 有个坑没变：脚本查的是**上个 tag 到 HEAD 整段**里的声明，不是逐个提交查。
> 所以同段里一条宽 scope 会替后面的差异挡灯。**先跑门禁、再写这一行**，
> 否则你看到的绿是别人的声明挡出来的。scope 收窄让这个坑小了，但没消失——
> 真正的出口是发版重置窗口。

**绝不加 Claude 署名**（`Co-Authored-By` / `Claude-Session` 一概不要）。本项目以开源为标准。

## 六、契约：别单方面改

后端 [`dawnop-site`](https://github.com/dawnop/dawnop-site) 的生产服务跑在这个编译器
产出的代码上。它按 `.dawn-version` 钉住某个 release，所以：

- 语言的破坏性改动要先发 tag，再由那边提一个 bump `.dawn-version` 的提交；
- 两边一起改的过渡期，那边把 `.dawn-version` 写成 `main` 现编，但**别让它长期留在 main 上**——
  那期间可复现性是没有的。

发布：改 `selfhost/src/version.dawn` 的 `VERSION` → 提交 → `git tag v0.9.0 && git push --tags`，
发布后 bump `scripts/seed-release.txt`（种子推进协议见 docs/bootstrap.md）。
`release.yml` 会校验 tag 与 version 一致、跑全量测试、把 `dawn.jar` 传上 Release。
