# 增量语义契约夹具

2026-09-27 起，体级重放引擎（`scalar_replay`、`body_product`、prepared/cached
会话、provenance 表及其 15 个 `check/` 模块）连同守它的契约一起拆了，拆除前的
整棵树归档在 `incremental-slice-final` tag，考古看 tag。本目录留下的是：legacy 前缀
会话与它对照的冷参照（`prefix.py`、`cold.py`、`probe.py`、`lsp-prefix.py`）、声明身份
（`identity.py`）、体调度器与执行器接缝（`body-scheduler.py`、`body-executor.py`）、LSP
对拍与计量工具（`lsp-*.py`、`bench.py`）。同日稍后，读取插桩（`semantic_reads`、
`write_journal` 与 `Cx` 的读取记录层）连同守它的十四个读取族 harness 也拆了。

## 探针住在编译器包内

检查器状态（`Cx`、`Frame`、`LambdaCx` 及其签名闭包）对 selfhost 包是 `pub(pkg)`，本目录
这个 `[deps]` 引用 selfhost 的工程看不到它。所以：

- checked-in 的测试模块在 `selfhost/src/contract/`（`cold`、`prefix`、`probe`），由
  `./bin/dawn test selfhost` 执行；基准正文是 `contract/bench.dawn` 的 `run`，本目录的
  `src/main.dawn` 只转发给它。`main.dawn` 与 `nmain.dawn` 都不导入 `contract/`。
- `*.dawn.txt` 模板按包内写法书写（`use check/...`，不带 `compiler/`；除 `main` 外一律
  `pub(pkg)`）。harness 用 `cold.install_probe` 把它们写进私有副本的
  `selfhost/src/contract/<name>.dawn`，夹具工程只剩一个转发 `main` 的入口；
  Java 预言机按 `dawn$pkg$selfhost.contract.<name>` 反射取类。
- 跑 `dawn test` 的 harness 按 `contract/<name> ::` 匹配模块名。

## Running the whole family locally

`sweep.sh` runs the incremental contract invocations in
`.github/workflows/gates.yml`, including those moved into ordinary jobs,
in parallel on one machine, because every
change under `selfhost/src/check/` has to be put in front of all of them before
it merges: the mutants here are pinned to literal source strings, a harness
whose anchor has drifted still looks like a working harness, and main went red
at ca33cdbe for exactly that. The list is parsed out of gates.yml at run time
rather than written down a second time, so a harness added to an existing job is
swept without anyone remembering to, and `sweep.sh --self-test` compares that
parse against a plain grep of the same file so the sweep cannot quietly run a
subset. Use `sweep-plan.py --raw-count` and `sweep.sh --list` for the current
raw and deduplicated inventories. Harnesses start longest first, since the
sweep is tail-bound rather than throughput-bound: the longest harness is the
whole wall clock if it starts in the last wave. `prefix.py` was that harness at
771s of a 1413s sweep, and the floor the sweep could not go under; on
2026-09-13 its twelve engine mutants were split three ways (`--shards 3 --shard
I`, dealt to three jobs in gates.yml, which is where the sweep reads them
from), so the floor is now its longest shard, about 312s. That is shard 0, the
one that also runs the positive subject; the other two are four mutants each.
The durations that order them are read from the previous run's log, and from a
static table of the longest until there is one; they affect nothing but the
order, and `--self-test` checks the set and the count rather than the
sequence. Measured 2026-09-13 on a 16 core / 15.6 GiB machine with the
toolchain already built, in gates.yml order: 25m30s at 5 jobs (7.7 GiB peak in
use), 24m42s at the default 8 (9.4 GiB) and 23m44s at 12 (12.1 GiB); longest
first at 8 jobs it is 23m33s (9.8 GiB), against roughly 62 minutes of running
them by hand one after another; those four figures are from before the
`prefix.py` split and were not remeasured. Wall clock is nearly flat in the job
count
because a single harness forks `dawn build` per mutant and already takes about
2.8 cores, so the cores saturate at around five harnesses and only the memory
keeps climbing; the default is `nproc`/2 because 12 buys 58 seconds for 2.7 GiB
of the headroom, while ordering bought 70 seconds for none. Progress goes to
`--log` (one PASS/FAIL line per harness as it lands, full output in
`out-<name>.txt` beside it), a failure that is an anchor drift is reported as
one with the string the harness was looking for and the line of its own source
that spells it, and `--only` and `--list` select. Nothing in CI runs this script
and gates.yml does not know it exists.

On 2026-09-27 the replay engine's contracts left gates.yml, and the sweep went
from 79 invocations to 33: 31m14s at 8 jobs with a 9.4 GiB peak, all passing
(sweep.sh's header has the run). The figures above are from before that.


## 冷路径对照

多文件 LSP 已启用保守前缀缓存；CLI 与 standalone 仍走冷分析。
下列冷路径命令本身不证明缓存命中，命中由前缀/工作区执行计数门禁另行验证。

- `python3 scripts/incremental-semantics-contract/probe.py`：八个 Java hook 与
  refusing guard 的九个可编译负控。
- `selfhost/src/contract/` 的三个测试模块（由 `./bin/dawn test selfhost` 执行）：query probe
  集成、冷路径阶段嵌套、错误恢复和 loader 诊断顺序。
- `python3 scripts/incremental-semantics-contract/cold.py`：私有源码副本中注入
  冻结旧循环，对照相同 StdCtx、LoadedModule 和 CtOpts；六个变异体只改新路径。
  需 JDK 21+ 的 `java/javac/jar`。

旧循环来自 `58ebd4a5` 的 `analyze_program`，仅改函数名；它共享未改动的
checker/stdlib helpers，不调用新 transition。13 组结果覆盖模块换序、恢复诊断、
parse/check/comptime 失败、impl/ID 传递和 std 的 impls_before 特例。

比较器由 javac 独立编译，通过反射比较整个 Program（包括 AST/TAST、comptime、
完整 Cx）。只排除 Cx 中同一 refusing oracle 的 jsig 能力；Array 比较逻辑长度内
的内容，不比较 backing capacity/append watermark。未知宿主对象抛错，不算相等。
新增字段自动参与比较，循环引用用对象对去重；浮点按原始位比较。Java 的标量、嵌套数组、
循环引用和未知对象有自检。采用独立比较器是因为直接生成完整 Cx 的 Eq 字典时，
测试程序出现 List_Int 构造器描述符不匹配；此处未修改编译器发射契约。

负控必须成功构建且命中明确的语义差异断言；编译错误、反射错误、timeout 不算通过。
impl 负控清掉 checker 的输入 impl carry，而不是清掉输出 fold 的初值：后者会被
完整 cx.impl_table 重新补齐，是等价变异体，不能用来证明门禁失效。


## 冷路径基准

```sh
python3 scripts/incremental-semantics-contract/bench.py \
  --java-home /path/to/jdk21 \
  --output review/cold-baseline-new \
  examples/projects/hello_mod selfhost
```

输出目录必须不存在。每个目标使用独立 JVM，同一 captured plan/target Java lease
中跑11轮，丢前3轮，cold/observed 交替先后顺序。保存逐轮 TSV、源码 SHA-256、
JDK/OS/参数、构建日志、摘要和进程峰值 RSS；每轮必须无诊断且所有模块执行 check/comptime。
parse replay 不是 loader 内部分段，不能从 load 相减；RSS 包含启动、std 和整个进程，
不是缓存保留内存。八个样本不足以声称稳定的加速倍数；这个入口只测冷分析阶段。

## 声明身份与体调度器

`identity.py` 验证生产声明候选身份及17个成功编译负控：重复父声明及子路径、
类型/关联效果的绑定槽归一、默认参数歧义、模块world隔离，以及派生身份本身的五个：
拼写丢掉种类字母或模块、跳过终混、派生区间的上下界。具名owning断言必须失败，
编译或链接失败不算负控。
同一脚本另跑四个 `ir/lower.densify` 的负控：打包键在 Core 里没有意义，下降期把它们
和 lowering 自己的临时号一起摊成每模块一串小整数，顺序必须与 `ir/coredump.names_of`
一致（captures → params → dicts → evs → body 首次出现），否则同一个局部量在 Core dump 里
叫 `v3`、在 `emitc` 印的 C 里叫 `v5`。提升体用外层给的 symbol id 引用自己的 captures
（`core.CFun.captures`），所以**漏掉 captures 不是缺号而是错号**：它会在 body 第一次
出现时拿到一个排在参数后面的号。因此这四个负控（跳过 captures、把 captures 排到最后、
符号表留着打包键、符号表捎上模块没提到的键）都是顺序断言而不是崩溃。

2026-09-27 起它还接手了两个随重放引擎删掉的脚本里守冷路径的负控。从
`allocation.py` 来的八个守 `check/cx` 的 mint 与声明槽：intern 撞车被静默接受、不登记、
顺手推进槽计数、进入声明时不换 owner、槽从零重发、全程序共用一个自由池、把机器相关的
src_path 读进派生输入、丢掉声明种类；owning 判词是 `check/cx` 的对应测试。从
`provenance.py` 来的五个守模块之间的 carry：intern 表不随 carry 走（用户模块、std
加载的两处）、程序装配时丢掉 `decl_spans`、导入效果时按导入方作用域自铸一个 id；
owning 判词是 `driver/analyze` 的「module identity carry」、「渲染读的程序带着本修订的
声明视图」与「consumer 不铸 provider 的效果身份」三条测试。

`body-scheduler.py` 用一份冻结的参考调度循环对照生产调度器，比较全部产物与除 `jsig`
外的每个 `Cx` 字段；生产侧经一个只在状态里追加角色名的 `BodyExecutor[List[String]]`
跑（重放引擎在时是录制执行器）。五个能编译的负控必须让 Java 比较器报出差异。
`body-executor.py` 守 `BodyExecutor` 这个接缝本身。

## 前缀与工作区

`prefix.py` 对照完整 warm/frozen-cold 产品，覆盖12个可编译引擎负控，包括预算、
std身份变化及构造器的负预算拒绝。`--shards N --shard I` 按 index 取模把这12个负控
分片，不带旗标时行为不变：正样本加全部12个负控。
正样本只在 shard 0 跑，代价与理由写在 prefix.py 分片处；每个分片仍会先套用全部
锚点，所以锚点漂移在任何一片都是硬失败。`lsp-prefix.py` 覆盖四个 LSP 负控，要求
owning FAIL 后是断言失败，不把 JVM 链接错误算作成功。三个是工作区接线（会话、绕过
缓存、冲突后留缓存），第四个换掉 `tast_positions.symbols` 的 resolver：体内偏移是相对
自己声明量的，加不回声明起点，查询就指向错误的位置。它的 owning 判词原是跨修订
definition 案例，随重放引擎删了，现在是 `lsp/server` 的「handler state cell answers at
every spelling of it」，同一个 resolver 的同修订读者。工作区计数测试在共享server里，
同时由 JVM/native selfhost 套件运行。原有 `scripts/lsp-workspace-contract/run.sh`
另行守18个协议案例和20个资源/工作区负控，不能只靠新计数测试替代它。


`lsp-bench.py` 通过实际 didChange overlay 编辑目标文件，磁盘源不改；
立即跟 barrier 强制 flush，所以 sync 不包括空闲 debounce。随后单独测
hover/definition/completion，并保存原始回复和 RSS。示例参数：
`--entry <path> --edit <path> --needle <reference> --output <new-dir> -- <server-command>`。

Latency summaries retain the existing median fields and also report sync and
query p95 values using the nearest-rank definition, `ceil(0.95 * n)`. Both use
only clean samples after the three warmup rounds. Raw samples, sample count,
and the percentile definition are retained for auditing. With the default
small sample count, p95 is the maximum observed sample, not strong evidence of
a stable tail distribution; formal value-gate runs need an explicit sampling
plan. Percentile reporting does not add body-edit/signature/reorder workloads,
prove cold equivalence, or measure retained semantic-cache memory. Self-tests
also check percentile ordering and reject empty, negative, and nonfinite samples.


`lsp-configured.py --source <configured-worktree> --output <new-dir> --mode
Legacy` builds a private compiler using the real `run_lsp_configured` entry;
`Cold` selects the other immutable policy, which evicts the prefix before
every analysis. Cache budgets are explicit arguments. No production CLI flag
or wire method is added. Exact source fingerprints, policy, budgets, observer
schema, and artifact hash are recorded. Launch the resulting `compiler.jar`
with the ordinary `lsp` command. The builder also accepts `--backend native`,
using fresh normal `__emitc` + C-runtime builds rather than a JVM substitute.

The optional private observer emits the project Session counters on stderr,
and `lsp-bench.py` preserves them per edit as `analysis_counts`. A standalone
buffer is analysed cold and owns no Session, so it reports nothing.
`--uninstrumented` builds the same configured policy without observation;
protocol equivalence and timing runs must distinguish these artifacts. The
builder's `--self-test` checks policy injection and fail-closed anchors, not
compiler semantics.

`lsp-edit-matrix.py --functions 1000 --output <new-dir> -- <server-command>`
exercises ten real untitled-document revisions: initial analysis, whitespace,
body edit, inferred signature change, reorder, deletion, insertion, error,
recovery, and an identical revision. This is synthetic correctness coverage,
not a latency experiment. `--compare <prior-output>` requires identical source
hashes and complete diagnostics/hover/definition/completion responses across
independently selected policies or compilers. Counts are stored separately and
excluded from semantic equality. `--self-test` checks the revision census.

`lsp-project-matrix.py --output <new-dir> -- <server-command>` uses the tracked
two-module `project-edit-fixture` without changing its disk files. Eight overlay
revisions cover provider body/signature edits, consumer and provider error
recovery, moved source, and closing/reopening the provider. It records complete
diagnostic publications with consumer versions and hover/definition/completion
replies; `--compare <prior-output>` checks exact equivalence using the same
fixture paths, hashes, and generated operation/version/overlay history. Both
open document versions are checked; closing the provider must send an
unversioned diagnostic clear. `--self-test` exercises the publication and
version oracles. Edit substitutions require exactly one anchor. Metadata also
records hashes of explicit launch executables, jar arguments, and classpath
files; this is not a transitive runtime-classpath attestation.

单大模块错误恢复使用 `standalone-large.dawn.txt`（500个简单函数及一个入口，
合成语料，不冒充真实大型应用）。在上述参数后加
`--uri untitled:incremental-large --error-round 5`，entry/edit 指向同一份文件，
needle 为 `value_499(1)`。11轮中的第5轮注入类型错误，第6轮恢复；每轮必须发布
当前文档版本，错误必须落在注入声明的位置，恢复后全部诊断必须清空。
错误轮不混入正常编辑中位数；原始 diagnostics 与 query 回复一同保存，用于旧冷路径
对拍。`lsp-bench.py --self-test` 验证诊断判定器及六个负控，并在 CI 执行。

`lsp-observe.py --output <new-dir>` 构建私有服务器，在 stderr 记录最终模块顺序和
实际复用/执行计数，不改变生产协议；`--cold` 只在私有副本里强制每轮先逐出 Session。
两个模式都可用同一源码、JDK和编辑序列对照，回复必须相同。强制cold仍可能保留本轮
输出prefix，不能用这两者的RSS差直接估算缓存大小。baseline JSON明确记录样本与限制。
