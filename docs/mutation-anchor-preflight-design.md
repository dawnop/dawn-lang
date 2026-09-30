# 变异锚点预飞

> 状态：**current**。issue #92 的源码锚点预飞。

`python3 scripts/mutation-anchor-preflight.py` 在任何编译器构建之前检查变异能否落地。
它以内存中的文件写入执行现有的源码变异器，保留它们的恰好一次匹配检查、次级编辑、
插桩与顺序替换，不另外维护一份锚点文本。首次本机运行检查了 198 次变异应用/定位，耗时 5.38 秒。

适配器只描述调用路径。mode 从字面量 `MUTATIONS` 键与显式的 name/mutation 分派比较中发现。
`scripts/**/mutate.py` 的清单必须与适配器和显式排除项一致；新增变异器而没有适配器即失败。
两个 shell 契约适配器抽取其中现有的变异 Python 块，不执行外围的 shell。
Java classpath 的 bracket 变异体先接受其现有插桩。嵌入式标准库损坏探针与具名的标准库变异分开检查，
gate-map 的 record 编辑也保留其源码锚点。

gate-map 的编辑应用在它自己的基线文本上，不逐个运行变异后的覆盖图。其现有的基数契约仍然是权威：
单次替换要求恰好一处匹配；有意的全局替换要求至少一处；文件新增与追加类对照保留各自的前置条件。
bundled-module 表达式按恰好一次检查。builtin-declaration 读取器检查真实的 `comptime_rejects`
循环拼写，不产出编译器制品。

tile-gpu-diff 不持有检出源码的锚点：它的替换文本全部由调用方提供。这条排除是显式的并会打印出来，
不会被默默当作源码覆盖。classfile-verify 改生成字节码的两个变异器叫 `athrow.py` 与 `privatise.py`，
不占 `mutate.py` 这个名字，所以不进清单；它的 `mutate.py` 是源码锚点登记表（见下）。
issue 点名范围之外的内联变异 harness 与文档引文不在本检查覆盖之内。现有的可执行语义契约仍然必须跑：
能落地不等于变异体能编译、也不等于它能检出所针对的缺陷。

`self-once` 的 harness（`scripts/anchor-readers.txt` 里的那一类）只在自己运行时才拒绝失配的锚点，
对构建很重的契约来说，这等于只有有人去跑它时才会发现。issue #249 就是这种情况：#248 改写了
`runtime/c/dawn_rt.c` 里的 `dawn_cpath`，本预飞报 OK，delete 契约在第一次本机运行时才红。
出路是把 harness 的锚点搬进一个 `mutate.py` 登记表，由 harness 与本预飞共同消费，而不是把字面量复制进适配器。
`scripts/delete-contract/mutate.py` 是第一个；在引入它的那棵树上本机实测：应用次数 204 到 213，墙钟 12.9 s 到 13.2 s。
#254 把十一条 `self-once` 契约全部迁完，每条一个提交：

- classfile-verify：17 个变异体、20 条锚点，原先是 `run.sh` 里 `replace_never_once` 的参数；
- syntax-small：5 个变异体、6 条锚点，原先是 `run.sh` 里的 5 段 Python heredoc；
- inflate：6 个变异体、6 条锚点，原先是 `run.sh` 里 `mutate` 的参数；主题是 `packages/inflate/src/gzip.dawn`
  （#254 的表里写的 `dawn_rt.c` 与 `check/types.dawn` 分别是链接输入和语料输入，不是锚点主题）；
- narrow：3 个变异体、3 条锚点，原先是 `patch_std` 的参数，主题 `std/narrow.dawn`；
- java-narrowing：2 个变异体、4 条锚点，原先是 2 段 heredoc，主题 `check/checker.dawn` 与 `jvm/help.dawn`，
  路径相对 selfhost 根（适配器给 `selfhost`）；
- map-reuse：2 个变异体、2 条锚点，原先是 2 段 heredoc，主题 `c/rc.dawn` 与 `std/hamt.dawn`；
- atomic-write：15 个变异、16 条编辑，原先是 12 处 `patch_std`、1 段改 `runtime/c/dawn_rt.c` 的 heredoc、
  1 段改两处编译器调用点的 heredoc，主题 `std/io.dawn`、`dawn_rt.c`、`pkg/add.dawn`、`main.dawn`；
- wasm-dom 的 retained：2 个变异体、3 条锚点，原先是 `apply_exact_mutant` 的参数，主题 `std/reactor.dawn`；
- dict-owner：4 个变异体、4 条锚点，原先在 `shapes.py` 里内联构造，主题 `ir/lower.dawn`；
- incremental 的冷参照 `cold.py`：6 个变异体、6 条锚点，原先写在它的 `main` 里，主题 `driver/analyze.dawn`；
  登记表在 `main` 里按路径加载而不是顶层 import，因为另有七个 harness 从 `cold.py` 导入 `edit` 等函数，
  gate-map 把被导入模块的顶层算作导入者的输入，顶层 import 会让登记表变成三个 incremental-memo 作业全部步骤的输入；
- tile-golden：67 个变异体、67 条锚点，原先是 `mutant_project` 的参数、由一段 `patch_pkg` heredoc 应用，
  主题 `packages/tileir/src/{bytecode,prog,render,dev}.dawn`；harness 把包拷到 `<tree>/packages/tileir`，
  使登记表路径在私有树里与检出里一致。注意 `scripts/tile-golden` 整个目录在 `tile-gpu-diff/inputs.py`
  的输入摘要里，所以这一刀改变了摘要，需要在 GPU 宿主上重跑 `tile-gpu-diff/run.sh` 追加台账行，
  `tile-golden-1` 里的 `run.sh --check` 才会重新变绿。

登记表路径一律写仓库相对路径（java-narrowing 除外），harness 把私有树布局成同样的形状（例如 `<tree>/std`），
所以同一登记表既能作用于检出、也能作用于私有拷贝。迁移后仍命中读者规则、但不持有变异锚点的 harness
（例如只为检查形状而读源码的 java-narrowing 形状门与 retained 的 seam 门，或只把源码当构建输入的 run.sh）
记为 `not-anchor` 并写明理由。

有的 harness 不调用登记表的 `main`，而是自己读出登记表里的锚点、在自己的恰好一次检查下应用：
`dict-owner-contract/shapes.py` 与 `cold.py` 在内存里应用，好在任何构建之前就拒绝漂移的锚点；
`export-surface-contract/run.sh` 的自测从 `EXTRA_EDITS` 取锚点。它们登记在预飞的 `REGISTRY_READERS` 表里。
预飞运行登记表本身，就证明了这些读者用的锚点；它对读者只要求一件事：文件里仍然提到 `mutate.py`，且对应登记表在适配表中，
否则红。`anchor-guard.py` 把这张表里的读者算作 `preflight`。export-surface 的台账行原先保守地记为 `self-once`，
就是因为 `preflight_is_real` 只认适配表；现在它经这张表记为 `preflight`，没有靠写理由绕过。

#254 迁完时 `scripts/anchor-readers.txt` 是 26 条 `preflight`、1 条 `self-once`、34 条 `unproven`、16 条 `not-anchor`；
`unproven` 此后由 #277 清零，见下一节。
`self-once` 没有删除，而是改成必须附理由的种类：台账行里要写 `kept because <理由>`，说明为什么不能由预飞持有，
否则 `anchor-guard.py` 报 `self_once_has_reason`。唯一剩下的是 `tile-gpu-diff/run.sh`：它只在有 GPU 的宿主上跑，
锚点全部是调用方传给通用替换助手（`mutate.py <file> <label> <old> <new>`）的参数，预飞按设计把它排除；
它在宿主上构建每个变异体之前自己检查一次锚点。把这些锚点搬进登记表可以做，但它们的主题分布在
临时拷贝的包、内核源码与 runtime 片段上，且每次改动都要一轮 GPU 重跑才能留证，不在 #254 的范围内。

## #277：`unproven` 清零

#254 迁完时台账里还有 34 条 `unproven`：按拼写读源码、却没有任何东西证明字面量恰好匹配一次的脚本。
#277 分四批把它们全部改判或迁走，每条一个提交：

- #278（6 条）与 #284（15 条）：规则误命中。这些脚本的变异已经来自预飞过的 `mutate.py`，
  或者它们对源码的读取就是断言本身（清单双向比较、`pub fn` 存在性、缺失即红），不定位要改的代码，
  记为 `not-anchor` 并写明理由。#284 顺带给 ctl-live、display-layering、dependency-heap、
  bootstrap-input-manifest 四个已预飞、但没有专项负控的登记表补了漂移测试。
- #286（6 条）：incremental-semantics 的六个 harness（lsp-observe、lsp-configured、lsp-module-memo、
  body-executor、module-memo、identity）改从 #273 为 `cold.py` 建的登记表读锚点。一个目录一个 `mutate.py`，
  所以键带归属前缀（`identity/...`），每个 harness 只取自己那一组；六者进 `REGISTRY_READERS`。
  预飞应用次数 342 到 419。
- 最后一批（7 条）：七个 shell 契约各建或扩一个 `mutate.py`，harness 按名字调用，输出逐字不变：
  - lsp-lifecycle：5 个变异体、5 条锚点，原先是 `run.sh` 的一段 heredoc，主题 `lsp/server.dawn`；
  - project-plan：2 个变异体、2 条锚点，原先是两段 heredoc，主题 `driver/analyze.dawn` 与 `lsp/server.dawn`。
    原 heredoc 还用两处没有检查的 `.replace` 改写拷贝出去的探针 `dawn.toml`（`../../../selfhost` 改成 `../selfhost`），
    只因为探针被拷到 `<tree>/probe`。现在探针拷到它在检出里的路径 `<tree>/scripts/project-plan-contract/captured-probe`，
    清单原样就指向变异树的 selfhost 与 compiler-plan，这次改写连同它需要的锚点一起消失了，而不是登记；
  - jsig-lease：5 个变异体、5 条编辑（4 条锚点），主题 `jvm/jreflect.dawn` 与本目录的 `probe.dawn`，都写检出路径。
    原先变异的是拼好的用例（`jreflect.dawn` 已接上 `resource-probe.dawn`，`probe.dawn` 已改名 `main.dawn`），
    现在先变异一棵只含这两个文件的树、再从它拼用例。`merge-loaders` 的替换文本要写夹具 jar 的路径，
    这些路径要等 `run.sh` 建好 jar 才有，所以登记表写占位符，由 `mutate.py` 的两个 jar 参数以 JSON 字符串填入；
    适配器给两个替身路径，预飞只证锚点；
  - builtin-type：26 个变异体、32 条编辑，原先是 24 处 `replace_once` 参数与 5 段 heredoc，主题 check/{cx,passes,checker,types}、
    lsp/{lspc,lspq}、`doc.dawn` 与 `embed/stdsrc.dawn`；
  - tea-reconciler：30 个变异体、30 条编辑（28 条锚点），原先是 `mutants.sh` 里的 `sed` 程序，主题 tea-core 的 `diff`/`walk`、
    tea-term 的 `widget`、tea-dom 的 `node`；
  - wasm-dom 的 flags（4 个）与 run.sh（9 个）：并入 retained 已有的 `mutate.py`，主题 tea-dom 的 js 与 src、
    `examples/projects/tea_dom_todo`。

后三者原先的判据是「文件变了」（`sed -i` 之后比 md5 或 `cmp`），不是恰一次：模式若匹配到两行，`sed` 两行都改，照样算应用成功。
改成字面量之后，这是这一批唯一一处语义收紧：第二份拷贝现在是预飞的红，不再是一个更宽的变异体。
转换规则是 sed 模式去掉方括号转义；这些模式里的 `.` 从来只代表它自己，唯一带 `\n` 的替换写成真换行。
wasm-dom 的 F 变异体（`no-catch`）原先按结构定位：以 `match catch_panic(() => turn(` 开头的那行到同缩进的 `}`，取第一处；
现在登记的是这一整块的字面量，包括块内注释。改了注释也会让预飞红，这是有意的：锚点就是被替换的那段文本。

**声明的命中数。** builtin-type 的 `stale-checker-consumer` 要把 `cx.dawn` 里 `public_builtin_type_names()`
的两处调用全部改名。它的登记项写成 `(path, old, new, 2)`：第四项是声明的命中数，`mutate.py` 要求实际命中数
与声明相等，不是放宽成「至少一处」。多出第三处或少了一处都和改拼写一样红
（`test_declared_match_count_is_held_both_ways` 两个方向各证一次）。没有第四项的编辑仍然要求恰好一次。
这是登记表的写法，不是预飞的例外：预飞照常执行登记表的 `main`，检查在登记表自己手里。

本批每条迁移的等价性证据是同一种形状：旧 harness 的变异代码与新登记表分别作用于同一份文件拷贝，结果逐字节相同；
再在本机把新旧 harness 各完整跑一次，日志相同（mktemp 目录名除外）。

迁完之后预飞应用次数 500，台账 76 行：37 条 `preflight`、1 条 `self-once`、38 条 `not-anchor`，`unproven` 为 0。
`unproven` 这个种类随之退役：`anchor-guard.py` 的 `KINDS` 里不再有它，台账里出现 `unproven` 行报 `unproven_retired`，
新出现的未登记读者报 `reader_registered` 时，提示也只给剩下三种。欠账表空了，就不再留一个可以停放新欠账的种类；
新的读者要么进登记表，要么写清楚为什么不是锚点，要么按 `self-once` 写 `kept because`。

CI 在 tree-policy 中运行预飞及其负控，不需要 JDK。负控覆盖：纯拼写漂移、重复锚点、声明命中数的两个方向、次级编辑、
shell 锚点、未知变异器、顺序插桩，以及拒绝启动构建或直接写盘。每个测试之后检出必须保持不变。
