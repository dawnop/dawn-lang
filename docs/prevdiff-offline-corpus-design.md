# 生态语料离线输入：`selfhost-prev-diff.sh --corpus site` 不联网也能整跑

> 状态：**current**。实现：`scripts/selfhost-prev-diff.sh`（`ECO_TREES`、`--pack-corpus`、`DAWN_ECO_CORPUS`）。

## 问题

`--corpus site` 是 nightly 的生态扫描（`lex/parse/fmt backend-dawn` 三个 label 的来源）。
脚本在三处向外要东西：

| 步骤 | 依赖 | 在无外网、无可用 `.git` 的机器上 |
|---|---|---|
| 生态语料 | `git fetch --depth 1` dawnop-site 的 `ECO_REV` | 死：无外网 |
| `emitchange_load` | `git rev-parse --show-toplevel`、`git log <seed tag>..HEAD` | 死：`.git` 是指回原检出的指针文件时 `git` 认不出仓库，`_ec_root` 为空，读到 `/scripts/seed-release.txt` |
| 种子 jar | `seedjar.sh` 从 GitHub Release 下载 | 缓存 `.dawn/seeds/<tag>` 在就不联网（已有） |
| 种子 std | `git archive <seed tag> std`，tag 缺失时 `git fetch` | 缓存 `.dawn/seeds/std-<tag>` 在就不碰 git（已有） |
| `--check-pin` | 三次 `gh api` | 只问 pin 是否陈旧，不在本问题范围 |
| `EMITCHANGE_MODE=range` | `git worktree add` 基提交 | 只有 gates.yml 的范围腿用，不带 `--corpus site` |

种子两项早已是「缓存在就不联网，且每次使用都按摘要校验」。剩下两项：生态语料没有离线形态；
git 元数据是这个门本身的输入（声明扫描就是读提交信息），不该绕开，只能由跑它的一方提供一个真的 git 仓库。

## 做法

与种子同一条规矩：**输入已备好就不联网，备好的输入每次按仓库里钉住的摘要校验。**

1. `ECO_REV` 旁边的 `ECO_TREES` 每行钉一个生产源根与其树摘要，算法是 `seedjar.sh` 的
   `seed_tree_sha`（种子 std 用的同一个：按路径排序，每个文件贡献长度、路径、字节）。
   dawnop-site `94fbd945`（v0.100.0）已删除 `backend-dawn/src`，因此只声明
   `backend-dawn/core/src`、`backend-dawn/app/jvm/src`、`backend-dawn/app/native/src`。
   不兼容旧布局，不加入站点的独立测试根。每个源根都必须存在且包含至少一个普通 `.dawn` 文件。
2. `--pack-corpus FILE`：在联网的机器上取 `ECO_REV`、逐根核对树摘要后，把这三个源根
   打成 tar 写到 `FILE`，然后退出。打包、验证与扫描都从同一份声明派生路径，没有第二份清单。
3. `DAWN_ECO_CORPUS=FILE`：设了就从这个 tar 解出语料、逐根算树摘要，不等于声明的摘要即拒绝；
   全程不碰网络。没设就走原来的 `git fetch`，行为不变。
4. 两条路径都拒绝树里的符号链接与其他非普通文件：`seed_tree_sha` 只摘普通文件，
   而扫描用 `find -name '*.dawn'` 会把链接也交给编译器，摘要看不见的东西不能进语料。
5. `git fetch` 路径在核对提交之后也核对树摘要。提交哈希本身已经够强；多核一次是为了让
   pin 保持诚实：推进 `ECO_REV` 忘了更新源根摘要，nightly 当天就红并印出不匹配源根的新摘要，
   而不是等某次离线运行才发现。成功时不多印一行，nightly 的输出不变。

每个源根直接配一个摘要，沿用现有算法，不引入额外的根清单摘要编码，也不用维护两份按位置配对的数组。
验证错误指出具体源根；格式化只复制声明的源根并保留相对路径，额外解包的文件不会进入扫描。

git 元数据由运行方提供：在本地按提交做一个包含 `<seed tag>..HEAD` 全部提交的浅仓库，
连同 `.dawn/seeds` 里已校验的种子一起送过去，在那个仓库里跑脚本。这一半不进公开仓：
它是运行环境的事，脚本只要求「当前目录是一个 git 仓库，且种子 tag 可达」，这一点 CI 与本地本来就满足。

## 负控

- 改 tar 里任一文件一个字节：`DAWN_ECO_CORPUS` 路径报 `failed verification` 退出 1，扫描不开始。
- tar 里放一个符号链接：报非普通文件退出 1。
- 删除任一个声明源根：报缺少该源根退出 1；清空源根或只留非 Dawn 文件：报无 Dawn 源文件退出 1。
- 改任一声明的树摘要一位、不设 `DAWN_ECO_CORPUS`：`git fetch` 路径报摘要不符退出 1。
- 不设 `DAWN_ECO_CORPUS`、pin 对一致：输出与改动前逐行相同。

## 不做的（理由）

- **把语料放进 gates-external 的输入包。** 输入包服务 gates.yml 的作业，而 gates.yml 的 `prev-diff`
  按设计不带 `--corpus site`（生态语料 2026-09 挪去 nightly，理由见脚本头）。没有作业读它，
  放进去只是让每次 `ECO_REV` 推进多一次重发输入包。
- **按 tar 文件的 sha256 钉。** `git archive` 的字节随 git 版本可能变，树摘要只看内容。
- **整个 `backend-dawn` 一起钉与扫描。** 会把独立测试根、脚本和文档引入生产源码扫描；显式源根保持范围不变。
- **脚本里认「无 `.git`」并改读提交信息文件。** `EMITCHANGE_SOURCE` 是自测钩子；让生产路径读一个
  外部给的声明文件，等于让运行方自己写豁免。真 git 仓库里 `git log` 读到的就是提交本身。
- **GitHub 的 `archive/<rev>.tar.gz`。** 不保证字节稳定，且仍要联网。
