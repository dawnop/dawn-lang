# 增量语义契约夹具

2026-09-27 起，体级重放引擎（`scalar_replay`、`body_product`、prepared/cached
会话、provenance 表及其 15 个 `check/` 模块）连同守它的契约一起拆了，拆除前的
整棵树归档在 `incremental-slice-final` tag，考古看 tag。本目录留下的是：legacy 前缀
会话与它对照的冷参照（`prefix.py`、`cold.py`、`probe.py`、`lsp-prefix.py`）、声明身份
（`identity.py`）、体调度器与执行器接缝（`body-scheduler.py`、`body-executor.py`）、LSP
对拍与计量工具（`lsp-*.py`、`bench.py`），以及读取插桩的契约（`*-reads.py`、
`*-revalidation.py`，随下一刀删）。

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
from 79 invocations to the count `sweep.sh --list` prints now; the figures
above are from before that and were not remeasured here (the knife's report
has the new wall clock).


## Diagnostic rendering read contracts

### Witness observation and candidate recomputation (acceptance in progress)

`python3 scripts/incremental-semantics-contract/witness-revalidation.py` runs a
private positive checker subject and compiling negative controls for candidate
recomputation, nominal recursion context, scope-sensitive concreteness,
assignment operands, inference outputs and reduction binding inputs. Each
negative must fail its named assertion owner, not merely fail compilation.
The projection controls additionally cover all eleven new fact variants,
separate dictionary/trait/binder domains, inference input/output bindings, and
missing mappings. Each mutation changes one production expression; checker and
projection modules are restored between subjects to prevent combined mutations.
The 31 controls and two positive baselines took 108.71 seconds on 2026-09-09.
CI runs them in `incremental-witness` with a 256-second planning value and a
13-minute timeout, preserving the existing run pole. Complete capture coverage
at all consumers remains pending. Passing this gate
does not admit a body cache entry or establish complete dependency coverage.

### Candidate context queries

`python3 scripts/incremental-semantics-contract/context-revalidation.py` checks
twenty two context-owned query dispatches, four acceptance/refusal controls and
three checker-dispatcher controls.
Canonical query capture remains unchanged in each private subject; every mutant
must compile and reach its named assertion owner. Two positives and 29 controls
took 131.06 seconds locally on 2026-09-15. CI uses a 234-second planning value
and twelve-minute timeout. The checker dispatcher combines context and witness
queries, but still refuses unsupported facts. It does not reconstruct body-local
scope, authorize a cache entry, or enable production body reuse.

### Diagnostic queries

`python3 scripts/incremental-semantics-contract/diagnostic-reads.py` checks four
positive modules and 124 compiling negative controls. Each negative must reach
an owning assertion; compilation errors and unrelated failures are rejected.
These contracts cover query inputs, answers, relocation, and context threading
through actual diagnostic consumers. They do not prove production cache reuse.

Use `--shards 3 --shard 0` (then indices 1 and 2) to run disjoint partitions.
Every partition independently runs all four positive modules. All partitions
must pass to accept the suite. `--check-shards --shards 3` validates current
mutation anchors, unique identities, and complete nonempty partitions without
compiling. `--self-test` exercises eight CLI acceptance/refusal cases, including
invalid indices and empty partitions. The default invocation still runs every
negative control.

Set `DAWN_BIN` to a frozen compiler when editing the subject concurrently. The
script snapshots subject sources and checks private copies; never replace that
compiler while a run is active. Final bootstrap, native and full selfhost gates
must still use the current production toolchain.

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
分片（约定同 `diagnostic-reads.py`），不带旗标时行为不变：正样本加全部12个负控。
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

## 读取插桩契约（下一刀删）

下列 harness 守 `semantic_reads` 与 `Cx` 的读取记录层。重放引擎走后它们没有读者，
随读取插桩一起删；在那之前照常运行。它们曾把 `body_product`（与 `header_product`）
当正样本或负控主语，那几个负控随模块一起删了，见 K1 报告。

`function-reads.py` runs 33 compiling controls against actual checker reads:
unqualified answers, diagnostic candidate lists, qualified signatures and module
alias paths, including misses. Decisions preserve local shadowing, expected-type
short circuits and argument scheduling. Capture/projection retain all four fact
variants. The typed oracle additionally compares 62 enabled/disabled observation
cases against complete cold Cx and module products; its read-state mutant must hit
the whole-Cx assertion. Recording remains disabled by default and is not complete
namespace coverage or production body-cache admission.

`export-reads.py` adds 22 compiling controls for qualified constant and constructor
answers, export presence, and private-name/candidate/type-constructor diagnostics.
The additional fourteen complete-state oracle cases exercise these expression,
call, qualified match and let/for refutability paths without stripping anything except the
intentional observation log. Four controls retain the recursive refutability
context and its let/for consumers, including the original short circuits.
Projection separates constant type references from constructor slots and
diagnostic kinds; the nominal half of that separation retired with the mapper,
because a derived nominal id relocates to itself and no control can tell the two
apart any more. Four further controls retain
qualified pattern presence, constructor and diagnostic answers, including their
kind. Error recovery preserves nested pattern observations. Type resolution,
local constructors, ADT/trait/impl and Java dependencies are still incomplete;
these tests do not authorize cache admission. The incremental-export-reads job
runs the export controls separately, preserving the unchanged 660s planning pole.

`type-reads.py` adds 44 compiling controls for qualified alias headers and resolved
targets, local/qualified nominal name/shape reads, type diagnostics, and local
alias cache/cycle decisions. Eighteen
further whole-state cases cover transparent/opaque aliases, effect substitution,
nominal arity errors, missing types/modules and earlier shadowing branches.
Alias type/effect binders project separately; a
transparent alias has no nominal ID to relocate. The BodyProduct fixture captures
and assembles the four reference-bearing type fact forms plus exact local type
diagnostics, including actual effect-row relocation. One control bypasses only
that callback; two more corrupt the projected diagnostic message or hint. Each
must fail its owning read comparison. Cached alias targets retain the distinction
between no cache entry and a cached error; cycle reads occur only after a cache
miss with a declaration target. Owning tests preserve those short circuits, and
the body-product fixture relocates cached targets while retaining cycle answers.
After a cache miss, declaration source reads retain the alias name, owner and
optional complete target syntax. Source-aware function and constant projection
entry points use an explicit owner-aware callback; source-free entry points
reject present declaration targets. Owning tests map identical original body and
foreign declaration offsets to different destinations using the production
header syntax projector, and reject an incorrect owner. Missing targets do not
require a fabricated source mapping.
The `incremental-type-reads` CI job runs this suite separately. Local alias lookup
records both positive headers and misses after the reserved-builtin/type-parameter
short circuits; uncached expansion records its actual type/effect binder inputs.
Both header forms share extraction and projection, with independent reference
domains. Builtin/current-environment dependencies, source-view runtime wiring, associated types/effects and
Java reflection still need their own observed dependencies and validity boundary.

`associated-reads.py` adds 11 compiling controls for scoped subjects, optional
ordered bounds, and type/effect member lists. Owning cases retain absent versus
empty bounds, duplicate-bound owner deduplication, missing members and ambiguity
on both axes. The four controls that separated the trait axis from the nominal
one retired with derived ids: both mappers are now the identity, so nothing
distinguishes them. Six additional
whole-Cx/module cases compare observed and cold associated resolution, including
error recovery. These observations do not yet establish complete effect or
scope dependencies, runtime query wiring, or production cache admission.
The incremental-effect-reads job runs these controls alongside ordinary effect
and environment suites, with a 554s planning value below the unchanged 660s pole.

`effect-reads.py` covers declared effect rows and scoped effect-variable answers,
including negative answers, metadata labels, lookup precedence and repeated reads
after fresh allocation. Fourteen compiling controls must reach their owning
assertions. Leaf and BodyProduct tests preserve the effect-row domain: declared
label IDs and variable IDs relocate independently, including equal input integers
with different destinations. Six complete Cx/module cases cover ordinary effects,
variables, aliases and error recovery. Runtime query wiring and complete checker
dependency coverage remain outstanding; these facts do not enable caching.
The separate incremental-effect-reads job also runs associated reads,
with a 424s planning value. Environment controls move intact to the type job,
which has a 652s planning value; both preserve the unchanged 660s pole.

`environment-reads.py` adds 15 compiling controls for reserved and ordinary
builtin lookups, current type parameters, and std-module visibility. The checker
owns the complete ordered sequence, including repeated builtin queries and
short-circuited parameters, arguments and visibility reads. Builtin metadata
retains its name, parameter spellings, access policy and build shape; leaf types
project through the actual type callback. Six complete Cx/module cases cover
std-only visibility, reserved return types and nominal shadowing. These facts
do not complete Java/trait/impl dependencies or authorize production caching.

`java-reads.py` exercises the named Java class lookup and the actual plain-data
class metadata answer. Its 21 compiling controls cover answer keys, answers,
consumer context threading, every JClass field, and BodyProduct read capture.
The five metadata consumers include reference returns, static and instance
dispatch, and SAM/List diagnostics. Projection retains the lookup key separately
from the returned class name. Four complete Cx/module cases cover these class
metadata consumers. Other Java query kinds, classpath/lifetime
validity and production query admission remain required; this is not a complete
Java dependency cache.

`java-member-reads.py` adds 33 compiling controls for ordered method, constructor
and static-field answers. Every metadata field, query key, list order and
consumer context is covered by owning assertions. Lists retain duplicate and
unused candidates before filtering or sorting, and empty results are recorded.
The BodyProduct fixture captures and projects all three facts; six additional
complete Cx/module cases bring the observation oracle to 72 cases. Argument
errors and instance constructor calls must still short-circuit before metadata
queries. Assignability, SAM/component and remaining namespace/import queries
are separate requirements; recording candidates does not authorize cache reuse.
The Java class and member suites run together in incremental-java-reads with a
608s planning value (109.07s and 174.12s local measurements, rounded up, doubled,
plus 38s setup). Adding member controls to the former effect/Java job would
exceed the unchanged 660s pole. All existing suites and controls are retained.

`java-namespace-reads.py` checks Java import gates, find-class answers and ordered
namespace enumeration. Its 22 mutations cover answer keys and values, projection,
body capture and consumer context threading, including value-versus-module-alias
resolution. Owning assertions retain negative answers, repeated reads and the
original declaration, syntax and shadowing short circuits. Nine additional
complete module/Cx cases bring the observation oracle to 81 cases, covering
successful, missing, disabled and duplicate imports, declaration collisions,
inferred functions and named-argument refusal. These observations do not yet
establish classpath lifetime validity or authorize production cache reuse.
The 22 compiling controls took 149.16s locally on 2026-09-08. They run in a
separate incremental-java-namespaces job with a 338s planning value
(2*150+38) and a 17-minute timeout, retaining the 660s pole and existing jobs.
During namespace acceptance, class/member controls took 184.25/226.97s under
concurrent load. Conservatively retaining those larger observations requires
separate class/member jobs: 408s/21min and 492s/25min respectively. No controls
are removed. The typed 81-case run took 239.16s; its job retains the larger
244.70s member-batch observation, yielding 528s/27min.

`java-oracle-reads.py` checks directional assignability, optional SAM metadata
and optional array components. It retains queries from rejected candidates,
fixed-arity attempts and packed arguments, plus repeated finalization queries.
The controls cover query keys/answers, all eight SAM method fields, projection,
body capture, candidate loops and scoring/finalization context propagation.
Only compiled mutations reaching owning assertions count. Eight additional
complete module/Cx cases bring the observation oracle to 89 cases; these cover
static and instance calls, rejected conversions, packed methods/constructors
and deferred SAM arguments. Classpath lifetime and production admission still
require separate validation before these facts can authorize cache reuse.
The 32 compiling controls took 246.67s locally on 2026-09-08. The dedicated
incremental-java-oracles job uses a 532s planning value (2*247+38) and a
27-minute timeout, without removing existing controls or raising the 660s pole.
The class/member/namespace regression controls measured 228.37/281.28/258.25s
under concurrent load. Their separate jobs conservatively retain those larger
observations at 496s/25min, 602s/31min and 556s/28min respectively.

`local-value-reads.py` checks constructor/constant identities, visibility,
constructor counts and field arities, focused headers, selected fields and
ordered diagnostic candidate pools. Its mutations must compile and reach an
owning assertion; bootstrap or parse failures do not count. The observation
oracle now has 101 complete module/Cx cases, covering generic constructors,
patterns, constants, record fields, and diagnostic refusals. Recursive
exhaustiveness controls additionally require normalization and recursive
return state to survive short circuits and diagnostic consumers. Handler
controls retain declaration metadata and selected evidence fields.
These observations do not yet establish complete dependency coverage or
production cache validity. The 49 compiling controls took 222.83s locally on
2026-09-08. Their independent CI job uses a 484s planning value (2*223+38)
and a 25-minute timeout, preserving the existing 660s pole and all other
contracts. Full batch acceptance remains required before publication.
The preceding complete 95-case/30-mutant typed run took 266.72s; its independent job
now uses a 572s planning value (2*267+38) and a 29-minute timeout.
The Java oracle regression took 250.55s, yielding 540s/27min.

