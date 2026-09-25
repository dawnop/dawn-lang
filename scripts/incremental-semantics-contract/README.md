# 增量语义契约夹具

## 探针住在编译器包内

检查器状态（`Cx`、`Frame`、`LambdaCx` 及其签名闭包）对 selfhost 包是 `pub(pkg)`，本目录
这个 `[deps]` 引用 selfhost 的工程看不到它。所以：

- checked-in 的测试模块在 `selfhost/src/contract/`（`cold`、`prefix`、`probe`、
  `session_bodies`、`prepared_sessions`、`cached_module_observer`），由
  `./bin/dawn test selfhost` 执行；基准正文是 `contract/bench.dawn` 的 `run`，本目录的
  `src/main.dawn` 只转发给它。`main.dawn` 与 `nmain.dawn` 都不导入 `contract/`。
- `*.dawn.txt` 模板按包内写法书写（`use check/...`，不带 `compiler/`；除 `main` 外一律
  `pub(pkg)`）。harness 用 `cold.install_probe` 把它们写进私有副本的
  `selfhost/src/contract/<name>.dawn`，夹具工程只剩一个转发 `main` 的入口；
  Java 预言机按 `dawn$pkg$selfhost.contract.<name>` 反射取类。
- 跑 `dawn test` 的 harness 按 `contract/<name> ::` 匹配模块名。


## Raw source equality controls

`source-equality.py` runs the source projection positive and four private
compiling controls for negative ranges, valid empty ranges, equal-width trivia
and unreachable source boundaries. Each control must fail its named assertion;
compile/link errors, panics and timeout are not acceptance. `--self-test` checks
the failure classifier without a compiler. These controls complement the JVM
and native inline range oracles and the existing parse/index invocation counts.
See [the source equality design](../../docs/source-equality-oracle-design.md)
for the exact raw-range cache contract and pending performance acceptance.

## Bounded generic admission and assembly-owned renewal

`function-entry.py` compares canonical entry allocation with its frozen old
loop. `bounded-entry-proof.py` requires ten compiling controls to reach exact
forged-input failures. `generic-trace.py` retains the original bounded `Scale`
workload, and `bounded-replay.py` verifies actual body execution counts, full
cold products, dependency invalidation and recovery through eleven compiling
controls. These run in the bounded-generic CI job alongside `source-equality.py`.

`body-renewal.py` retains six generation/log/count controls and adds five
assembly-boundary controls. Ordinary callback environments remain strict;
successful installation with refused capture must retain its output without
checking the body again. Strict and certified saved products are compared
through three actual renewed generations and both observer modes. These are
correctness contracts, not a production-default or complete G3 performance gate.

## Prepared source proof boundaries

`prepared-proofs.py` compiles one positive subject and two isolated controls.
The consumer control reparses only a missing prepared proof, leaving certified
proofs and the legacy fallback unchanged. Its owning test uses clean, eligible
source with capture disabled, both without and with a previous body cache.
It requires absent counts/cache and cold-equivalent semantic products.
The producer control removes both source path and text guards; its real loader
collision fixture uses distinct equal-width comments to keep ASTs and source
coordinates equal while detecting the borrowed index. Both controls must reach
their exact owning assertion, not merely fail compilation or another test.
This small harness complements loader lifecycle and execution-count coverage;
it does not measure parsing cost or activate prepared loading in production.
The complete local run on 2026-09-22 took 135.52s: positive 41.83s,
missing-proof control 46.91s, and collision control 46.74s. These are local
validation costs, not CI runner observations or a production speedup.

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
- `selfhost/src/contract/` 的六个测试模块（由 `./bin/dawn test selfhost` 执行）：query probe
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

## 重放代价剖面（仅本地）

```sh
python3 scripts/incremental-semantics-contract/bench-replay.py \
  --java-home /path/to/jdk21 --output review/replay-cost
```

`bench-replay.py` 与其 `bench-replay.dawn.txt` 只测量，不改任何 checker / recorder /
executor 语义；它按函数体类别（字面量标量、原语参数算术、具名非泛型调用、带 trait bound
的泛型、含闭包的推断体、impl 方法、trait 默认体、`use java`）分别计冷检查、scheduler
录制与 `check/scalar_replay` 的每阶段代价，并给出打破平衡所需的每体成本表。
**它不进 CI，也不该进**：输出是墙钟毫秒，随机器与并发负载浮动一到三成，门禁没有可比对
的东西；同理它没有 `# budget:` 行。阶段拆分是在夹具里用生产的公开 producer 重新组合的，
每次运行都在同一进程内与生产 `scalar_replay.replay` 的 reused/checked 计数对账。

`parse` 模式把快照的两半分开计价：`snapshot_build`（parse + index）是修订所有者本来就要
付的一次解析，`bind_pair` 是重放自己仍要付的两次语法树比对；`snapshot_of` 是
`source_snapshot.of` 的全部代价，含它为每个函数声明取的 token 事实。`record` 模式另报
`admit`，即 `scalar_replay.admit` 在录制之后一次性定下的准入判定。`memory` 模式不计时，它报
保留一个 `source_projection.Indexed` 与保留一个完整 `Snapshot` 各占多少堆字节（强制 GC
前后取差）；真实所有者里语法树与 header 共用，故索引那一项就是快照的边际内存。

类别生成器与 `equal_bodies` 在 `replay-workloads.dawn.txt`，与下面的编辑矩阵共用；两个
harness 都把它写进私有 selfhost 副本的 `contract/workloads.dawn`。

## 真实编辑矩阵（计数，无计时）

```sh
python3 scripts/incremental-semantics-contract/edit-matrix.py            # 4 类 × 10 编辑，n=1000
python3 scripts/incremental-semantics-contract/edit-matrix.py --self-test
python3 scripts/incremental-semantics-contract/edit-matrix.py --check-anchors
python3 scripts/incremental-semantics-contract/edit-matrix.py --controls
```

`edit-matrix.py` 把十种编辑（identical、shift、body_one、body_one_type_error、
inferred_return、ws_between、ws_inside、insert_decl、delete_decl、reorder）施加到 calls、
primitive_inferred、generic 与含 lambda 的 inferred 四类工作负载上，每格跑 replay、
replay_and_record 与续期后的回程三步，逐格对精确计数预言、逐体对冷检查。预言写在脚本的
`oracle` 里，推导在 [docs/real-edit-matrix-design.md](../../docs/real-edit-matrix-design.md)。
Dawn 侧 `edit-matrix.dawn.txt` 只观察不判定，所以变异体表现为「哪几格变红」而不是一次
panic。`--controls` 在私有 compiler 副本上跑三个能编译的变异体，要求各自拥有的格变红，
再恢复源码要求整张矩阵变绿；`--check-anchors` 只在内存里套变异锚点，不编译。
它目前不进 CI（放置建议另见任务报告）。

## 前缀与工作区

后续函数级演进的私有决策门见[第3期函数体原型](body-probe.md)：
固定header下验证稳定函数key、真实前置编辑、TFun和完整body边界Cx重放；
header来自生产check_module_headers的ModuleHeaders，不再按源码锚点复制header前缀。
它不是已上线的函数缓存，也不代替下列生产前缀门禁。

`relocate.py` 验证生产 `check/evidence_spelling` 还在判断的那件事（脚本名没改，因为
`gates.yml` 按文件名跑它；主语在 K7 从 `check/relocate` 搬了家）。翻译这一层已经不
存在了：类型变量、效果变量和局部符号都是 `identity.pack(声明, 槽位)`，nominal 与
trait 由声明派生，没有被编辑的声明在候选修订里绑定同样的整数，所以 `ty`/`effect_row`/
`witness`/`evidence_key` 全部答以收到的值，K7 连同 `Ids` 一起删掉。剩下的判断是
**evidence key 的 band 从 key 本身读回**（label 名字的前缀、associated 的 trait、
variable 的拼法，以及 `checked_symbol` 对生成名的校验，共六个）：6个成功编译负控
必须命中具名断言。曾经与它并列的「两个签名的 ABI 行是否逐槽对应」在 K6 连同置换
一起删了，见下。

### Controls retired with the read-log projection (K7b)

`semantic_reads.project_with_inference` rebuilt a recorded read log fact by
fact for a caller that installs the log, under nine projection callbacks. Every
one of those callbacks was the identity at both production call sites: a fact
names the declaration that owns it, and a declaration that was not edited binds
the same integers in the candidate revision. The measurement is inline, over
the whole read vocabulary: `check/body_product :: body product read comparison
answers for the projection it replaces` walks one fact of each of the sixty
four `FunctionRead` constructors past the projection and requires sixty three
of them to come back untouched.

The sixty fourth is `LocalAliasSource`. The source node it carries is a span in
the file of the declaration that owns the alias, not in the file of the body
that read it, so only that owner can move it, and a caller without that
provenance has to reject rather than keep a stale span. That arm is all that is
left: `semantic_reads.project(reads, source_value)` carries every other fact
whole. The dispositions below are K4's three.

- **A hundred and twenty five controls are deleted** across thirteen
  harnesses. Each one replaced one projection callback with another domain's
  callback, or edited a field the projection copied out of a fact, and each is
  K4's third disposition: the judgment goes with the production code that made
  it. There is no per-arm rebuild left to confuse a trait id with a nominal id,
  or to drop a constructor's fields, because nothing rebuilds a fact. The
  counts, with the retired names listed at the place each stood in its harness:
  `java-member-reads.py` 23, `witness-revalidation.py` 20 (its whole
  `project-*` family, and with it the `semantic_reads` subject and its positive
  control, 31 controls to 11), `type-reads.py` 14, `java-oracle-reads.py` 14,
  `diagnostic-reads.py` 10, `java-reads.py` 9, `local-value-reads.py` 8,
  `environment-reads.py` 7, `function-reads.py` 5, `java-namespace-reads.py` 5,
  `effect-reads.py` 4, `associated-reads.py` 3, `export-reads.py` 3.

  Fifty one of them were generated rather than written out, in per-field loops
  over a record the projection rebuilt (`JMethod`, `JCtor`, `JField`, `JClass`)
  or per constructor arm. A loop that generates controls hides how many there
  are, and it hid these from a first reading of the harnesses: three of the
  thirteen were found by running them, not by reading them.

- **No harness is deleted and none is left empty.** Every one of the thirteen
  keeps its recording side, which is the half that still decides something:
  which fact the checker observes, what the fact says, and whether a consumer
  reads the context the observation returned. `witness-revalidation.py` keeps
  its eleven checker controls, `type-reads.py` its twenty six `cx` controls,
  `java-member-reads.py` its six `cx` controls and three consumer controls, and
  so on down.
- `state-product.py`'s `function-read-domain` and `type-reads.py`'s
  `alias-source-callback` are **re-anchored, not retired** (K4's first
  disposition): both mutate `body_product.projected_reads`, whose call is now
  `semantic_reads.project(p.function_reads, source_value)`, and both are held
  by the same inline assertion as before.
- `type-reads.py`'s `alias-source-projection` and `alias-source-owner` are
  **untouched**. They mutate the one arm that survives, and they are the only
  two controls the read log's projection still has.
- Thirty one inline assertions in `check/semantic_reads` went with the arms
  they exercised, replaced by two. `semantic reads carry every fact but move an
  alias source with its owner` makes the projection claim, and the
  vocabulary-wide half of it is made by `body_product`'s corpus, extended from
  fifty facts to sixty six so that it names every constructor rather than only
  the arms that used to rebuild a reference.
- The second replacement, `semantic reads append every observation in the order
  it was made`, exists because two of the thirty one were doing two jobs. They
  built a log with `record`/`candidates`/`observe`, asserted something about
  recording, and then asserted something about projecting it; deleting them for
  the second half took the first half too, and `function-reads.py`'s
  `negative-answer`, `candidate-answer` and `candidate-order` and
  `export-reads.py`'s `observation` lost their owner. The sweep caught it.
  Before deleting a test with a production arm, check what fails without it,
  not what it is named. One more thing that check turns up: the deleted
  ordering assertion used `["beta", "alpha", "beta"]`, a palindrome, so it had
  never owned `candidate-order` in the first place.

### Controls retired with the translation layer (K7)

`equal_under` walked a recorded fact beside an observed one under a relocation,
`check/relocate_tree` rebuilt a recorded tree node by node, and
`check/relocate_header` rebuilt a header product's tables. All three were the
identity on every domain they touched, because a reference names the
declaration that owns it and a span is an offset from the declaration that
recorded it. What the two body-side walks were really doing was refusing the
products they could not rebuild, and that is what `check/body_admit` is: the
same 35 arms, answering `Bool`. The header-side one was refusing nothing a
production caller could reach, and it had no production caller at all. The
dispositions are K4's three.

- **`header-metadata.py` is deleted, with all four of its controls and its
  ten-schema field audit.** `impl-owner`, `impl-end`, `alias-sentinel` and
  `alias-target` mutated the positional half of `relocate_header`; the module
  is gone, and so is the classification the audit enforced ("projected" versus
  "retained" fields), because nothing projects a header any more. This is K4's
  third disposition: the judgment goes with the production code that made it.
  The fixture movement those controls were measured against was invented by
  the fixture itself: `metadata_sample` built a `HeaderView` that shifted every
  position by the length of a prefix it had prepended, and production never
  built one.
- **Four `body-probe.py --typed-all` controls are deleted**: `header-alias`,
  `header-impl`, `header-state-bounds` and `header-state-surface`, with the two
  comparisons that owned them (`header metadata: projected exports differ from
  cold headers` and `header state: projected context differs from cold
  headers`). Same disposition, same reason. The third comparison in that
  family, `header state: assembled context differs from cold headers`, is
  **kept**: it is `header_product.capture` followed by `header_product.assemble`
  on a real module's headers, which has nothing to do with projecting them.
- `projection.py`'s `pack-order`, `crossed-evidence-origin` and
  `evidence-arity` are **re-anchored, not retired** (K4's first disposition):
  the three judgments moved to `check/body_admit` with the walk that makes
  them, and each is still held by the same inline assertion, now spelled as a
  refusal rather than as `== None`.
- `projection.py`'s three callee controls (`callee-owner`,
  `callee-module-alias`, `callee-conflict`) are re-anchored to
  `check/callee_index`. Finding a callee in one revision was never a
  translation; the module moved out of the tree visitor in K7 and the controls
  followed it.
- `relocate.py`'s six controls are re-anchored to `check/evidence_spelling`,
  for the same reason.
- `state-product.py`'s `constant-tree` and `function-read-domain`,
  `type-reads.py`'s `alias-source-callback` and `constant-source-callback`,
  `witness-revalidation.py`'s `accept-changed-answer` and
  `accept-missing-trait`, `context-revalidation.py`'s `accept-changed`,
  `discard-context-result` and `accept-unknown-query`, `scalar-replay.py`'s
  `header-only-admission`, and `allocation.py`'s `constant-type`,
  `target-identity`, `entry-pack-not-a-run` and `reserved-signature` are all
  re-anchored: seventeen controls whose judgments did not change and whose
  owning assertions did not move.
- `witness-revalidation.py`'s `project-*` controls were **untouched** by this
  knife. They mutate `semantic_reads.project_with_inference`, which still
  rebuilt a read log for a caller that installs one. Shrinking that was the
  separate knife recorded above as K7b, which retired all twenty of them.

### Controls retired with the ABI permutation (K6)

An evidence row is ordered by effect id, an id derives from its declaration,
and a declaration that was not edited derives the same id. So the permutation
`check/relocate` computed between a recorded signature's ABI row and the
candidate revision's was the identity in every case a caller could reach, and
`evidence_slots` / `evidence_slot` / `evidence_permutation` / `evidence_order`
went with it. What the computation was really buying was a refusal, and the
refusal survives as a width comparison against `types.nev` at both call sites.
The dispositions are K4's three, as above.

- Four controls in `relocate.py` mutated the deleted code and are gone:
  `missing-parameter-evidence` and `mismatched-row-length` turned off the
  refusal of two signatures whose ABI rows do not correspond;
  `lost-associated-subject` and `lost-associated-member` dropped half of a
  projection slot's identity while building that correspondence. The refusal
  they reached for is now owned by `evidence-arity` in `projection.py`, which
  turns off `relocate_tree.function`'s width check and is held by the same
  inline assertion as before, and by `relocate_tree`'s own
  `function(v, TFun { ..f, ev_syms: [1, 2, 3] }) == None`. The two halves of a
  projection slot's identity are held by `lost-associated-subject`'s surviving
  neighbours in the band family: `associated-band-trait` reads the trait out of
  the key, and `unminted-associated-spelling` refuses a name the subject and
  member did not mint.
- `evidence-arity` in `projection.py` was re-anchored, not retired. It used to
  read a length off the permutation; it now reads it off
  `nev(sig_abi_eff(f.sig))`. Same judgment, same owning assertion.
- "The ABI row's label axis is laid out by effect id" had no owner of its own
  before this knife. The four controls above all ran on a row that was already
  sorted and would have stayed red under any other total order both sides
  agreed on, and the assertions that do notice `types.by_id` being reversed
  (`effect union normalizes`, `a signature's effect variables land in eparams
  once each, in mint order`) are about the variable axis, not the label one.
  It has an inline owner now, `check/types :: a signature's ABI row lays its
  labels out by effect id`, built on three labels whose names are the same
  length and whose alphabetical order is the reverse of their id order, so
  that neither a spelling sort nor a length-prefixed one can be mistaken for
  it.

### Controls retired with packed binders (K5)

A negative control that cannot be told from the production code is not a
control, and packing a binder into its declaration turned a row of them into
exactly that. Every one is accounted for here rather than quietly dropped, in
the three dispositions K4 set: moved to a harness that still has a subject,
deleted because another harness already owns the judgment, or deleted with the
production decision it mutated.

- Six callback controls replaced a relocation with `Some` and are gone:
  `effect-callback` (`type-reads.py`, `effect-reads.py`), `type-callback`
  (`environment-reads.py`), `constant-domain` (`export-reads.py`),
  `constant-type` (`projection.py`) and `product-projection`
  (`write-journal.py`). The journal is still projected and `write_journal`'s
  own inline test still hands it two callbacks that move, which is what
  `symbol-domain` and `bounds-domain` ride on.
- Four consumer-side controls in `provenance.py` went with
  `driver.module_references` and `ModuleStep.references`, deleted this knife.
  `mint-provider-identity` and `collide-same-domain` are `binding-conflict`
  and `owner-conflict` in `allocation.py`; `rename-blind-identity` is
  `spelling-drops-kind` and `spelling-drops-owner` in `identity.py`.
- `stale-source` and `header-only-ids` in `scalar-oracle.py`: on an admitted
  body admission is the whole of the walk, and there is no relocation left
  for either boundary to carry (K7).
  The rebuilt read log is still held by `observer-mode`, and the refusals by
  `header-only-admission` and `changed-declaration-text` in `scalar-replay.py`.
- Two controls moved rather than died. `evidence-origin` in `projection.py`
  became `crossed-evidence-origin`: the origin is carried unchanged now, so
  what is left at that call site is the refusal beside it, that a read's key
  and its origin are two records of one slot. `header-only-admission` in
  `scalar-replay.py` now admits against the recorded header instead of the
  candidate one, which is a real difference: a declaration whose own bytes did
  not change can still have a different signature, because the types it names
  are declared elsewhere.
- Three fixtures had to be taught the declaration seam rather than re-anchored.
  `reference-body-scheduler.dawn.txt` opens each declaration in its own words
  (a loop that checks bodies without opening one numbers the whole module in
  the free pool); `body-probe.dawn.txt` and `typed-projection.dawn.txt` do the
  same, and replay a saved body by resolving it against its declaration's
  position instead of shifting every offset by a constant.

`body-probe.py --typed --typed-all --java-home <JDK> --output <新目录>` 运行生产树投影
的私有对照：23个真实函数、22次非均匀源码编辑及一次真实effect声明重排，七个树投影编译
负控必须命中独立Java比较器的完整TFun断言。另有六个推断函数/调用者状态（标量、
泛型闭包、效果多态闭包返回），使用生产header台账与逐函数的分配区间，和一个
test block状态的完整冷模块对照，丢封定签名写入、保留错误in_test的两个编译负控
必须分别命中对应的完整Cx断言。header重排进一步比较完整Cx，并增加丢symbol目标
插入排序的负控。另有三个impl入口负控，移除owner、类型参数和签名角色守卫，
必须命中具名的运行时拒绝断言；默认参数另有丢符号写入的完整Cx负控。
另有丢默认值字典符号的编译负控，必须命中泛型默认值的具名字典断言。
另有丢默认参数诊断的编译负控，必须命中默认错误态的具名断言。
Compilation or linking failures do not count as passing negative controls;
typed-all now contains 13 compiling controls, down from 17 before the header
projection was deleted (K7: `header-alias`, `header-impl`,
`header-state-bounds` and `header-state-surface` went with `relocate_header`),
from 30 when nominal and trait ids started deriving from their declarations,
and from 21 before binders were packed into their declarations (K5: `local`,
`capture` and `dynamic` turned off the identifier half of the tree projection,
which is the identity now, and `header-adt` turned off a header projection that
relocates nothing else).
`body-probe.py --all` lost `skip-symbol` and `skip-captures` the same way and
keeps six. Six of the nine that left
could no longer be told apart from the production code by the reordered-header
sample, because a declaration reorder does not move a derived id: a ground
label stays put, so an evidence pack cannot be permuted (pack-order,
evidence-origin) and a body's symbols cannot be either (symbol-order); an
impl-table key is a trait id and an ADT head, so rekeying is the identity
(header-state-key); and the value sample's constants are declared at types
with no binders in them (constant-type). pack-order, evidence-origin and
constant-type moved to `projection.py`, which owns inline assertions, and are
held by `check/body_admit` tests that hand the walk products it must refuse;
symbol-order was already held by `state-product.py`.
header-effect went with the production code it mutated: an `EffectI` has
nothing left to relocate, so `relocate_header.effect_info` is deleted rather
than left as an identity. Typed mode also compares assembly
of 23 body products in their original coordinates. The 22 source-edit replays use
production `body_product` capture, projection and assembly, not the old private
write-set replay. Fixed-header allocation/reference views still come from the
fixture, not production query wiring. Target symbol mappings follow header binding
order, not answers reconstructed from cold bodies; complete header/type/trait
coverage and actual cache validity remain unfinished.

header重排案例使用`allocation.local_headers`台账连接生产声明索引的局部ADT、
opaque/透明alias、trait及方法、效果和函数签名binder，同时反转成对声明，
直接核对各域ID与方法签名映射，并拒绝来源路径不符的header。另连接
`local_impl_headers`读取生产header pass的泛型impl方法签名，核对顺序交换后的完整签名，
并拒绝缺失、错序和metadata不匹配的签名表；再连接
显式intrinsic保留身份。`body_relocation`按旧产物记下的区间做平移，按完整ABI角色置换
顶层evidence，不从冷body读取目标ID；默认参数仍拒绝，独立产物接线待完成。
默认参数正例另通过check_param_default分别捕获两个Int默认值，使用纯默认签名
按各自区间重放，这些区间再随重定位一起交给主body产物投影与重放，两类签名均与完整冷Cx/TFun及模块函数比较；
另覆盖泛型默认闭包调用trait方法、携带字典引用：普通/泛型与显式/推断四例，加上
显式/推断默认值类型错误两例，共六例；全部在源码前增加注释，比较移动后的诊断及位置。
尚未覆盖全部复杂表达式，也未接入生产缓存调度。
已不再生成稠密header identity表。固定header的其他案例暂仍用稠密夹具映射。
`allocation.py`有21个编译负控，守身份/ID冲突、目标版本选择、负槽与引用域及常量声明类型，
以及body evidence置换、未观察临时ID、分配终点、前序台账保留、world、无路径边界、
compiler trait binder和runtime擦除绑定；
台账的 nominal/trait 半边已随派生身份删除（消费者不需要映射，两个声明也不可能争同一个号），
继承那两条判词的是 `check/cx.mint` 的 intern 表，五个负控在同一个脚本里守它：
撞车被静默接受、不登记、顺手推进计数器、把机器相关的 src_path 读进派生输入、丢掉声明种类。
CI的incremental-allocation独立运行该脚本，
并运行`provenance.py`的十一个生产生成器负控：丢用户/std/compiler来源、丢provider carry、
错误header放行、漏std world重绑定，三个丢 intern 表跨模块 carry 的控制，
一个消费者侧的（导入效果时不写provider的id、改按导入方作用域自铸一个），
以及一个渲染侧的：程序装配时丢掉 carry 的 `decl_spans`。`identity.absolute` 在视图
缺失时按设计保留诊断自己的偏移，所以丢视图的程序会把声明内偏移当绝对值印出来且不出声；
owning 判词是 `driver/analyze` 里那条「渲染读的程序带着本修订的声明视图」。
四个旧的消费者侧负控随`module_references`退役，理由逐条记在脚本里。
每个负控必须命中它自己owning的具名断言，脚本按变异体记owner而不是共用一条。
native门禁另显式执行allocation模块测试；当前已被生产driver引用，与主图有重叠，计数不相加。
另有两个真实两模块导出/导入案例：provider交换效果或类型声明顺序，consumer分别
选择性导入效果、通过模块别名访问类型和泛型函数，合并原声明模块与consumer台账后
重放完整body/Cx。断言consumer不生成导入声明的本地身份，丢合并内容的编译负控由
allocation owning测试守住。所有typed案例统一使用生产callee_signature入口，以声明
owner和原函数名查找签名，别名不替代声明身份。另有一个跨模块效果案例：provider声明
效果与一个绑定效果参数的泛型函数并在两版本间重排，consumer选择性导入效果名、用模块
别名调用操作与该泛型，断言效果id等于provider声明的派生值、provider的效果参数binder
由provider台账发布而consumer台账只发布自己的。限定效果拼写本身仍不覆盖，因为当前
语法不接受`!dep.Ask`（`!dep`先被读成效果变量）。可选AnalysisCarry已在生产header边界记录用户和std
来源，Session保留固定baseline；内建来源从实际prelude/builtin元数据生成，三个来源
重排案例不再手写evidence-pack映射。尚未启用body缓存调度。

另有十个完整模块重放对照：一例函数交换源码顺序、一例前置函数改动后复用六个推断函数、一例泛型impl与trait默认方法重排、一例常量/test重排，以及上述六个默认
参数案例。将重定位结果送入生产assemble_module_bodies，独立反射比较整个TModule和
最终Cx，包括合成默认函数、签名表和Map顺序。漏装函数/清空最终签名表的两个负控仅
修改重放侧，必须命中整模块断言；这些是fixture装配/比较器负控，不冒充生产调度门禁。

function_product从真实ModuleHeaders构建顶层函数的具名header索引，保持当前语法与entry
签名配对；重排案例按DeclKey读取旧body，再按当前keys顺序装配。function-products.py
十五个编译负控守来源、owner、签名错位、多余签名、重复声明、impl分组/参数/角色与trait默认
元数据。独立Methods视图保留impl/default分组顺序，读取真实注册ImplI和trait MethodSig，
不把同名方法混为一个key。header重排案例已投影两个泛型impl方法及两个效果多态默认
方法的签名/subject/trait ID。新增整模块案例重放四个泛型impl方法和两个trait默认方法的
无标签body，再按当前impl组入口计算发射标签、按当前trait登记默认方法标签。
注册subject不能替代入口上下文的解析结果；每个方法重新计算也不等价于每组一次。
两个fixture负控分别打破这两个约束，必须命中整模块冷路径对照。
空impl组由具名索引owning测试覆盖；这不是生产缓存调度或header依赖有效性证明。

Values视图保持常量/test角色、顺序和常量前序可见集；四个新负控守常量类型、
签名尾部、可见集及test角色。BodyProduct[T]共享Cx增量而保留真实TFun/TConst类型，
常量分配计划检查声明类型、保留完整临时区间，不制造函数签名。真实模块重排两个
nominal类型、三个常量与两个test，比较完整TModule/Cx；两个typed新负控丢常量类型
和源码投影必须命中整模块断言。这是已知可复用语料的产物重放，不证明一般可见集
变化时的缓存有效性，也不跳过后续依赖接线。

`check/relocate_header`（完整导出记录与 header 表的投影）与 `header-metadata.py`
在 K7 一起删了：header 里的每个引用在两个修订里都是同一个整数，每个位置都是记录它
的那个声明内的偏移，所以它投影不出任何东西，而且从来没有生产读者。夹具自己造的那
段位移（`metadata_sample` 先加前缀再按前缀长度平移每个位置）是它唯一能被测出来的输
入。留下来的是同修订的 `header_product.capture` + `assemble` 往返，由
`body-probe.py --typed` 的 `header-state` 比较和 `header-state.py` 的十二个负控守着。

header_product captures complete header scope tables, diagnostic suffixes and
allocation intervals without retaining the entire Cx or a Java capability. Real
header fixtures compare the complete assembled Cx, then project the complete state
into moved ID/source coordinates and compare against cold Cx. Two compiling
controls retain old bounds or old observable impls; these are part of the 21
typed-all controls. The impl-key control went with derived ids: an impl table
is keyed by a trait id and an ADT head, and neither moves any more.
header-state.py的十一个编译负控守环境、分配、诊断前后缀、intern 表、常量表、类型作用域及
type-span清空状态；完整Cx捕获/装配和HeaderProduct投影字段审计另有五个结构负控。
nominal/trait 的取号在 header pass 里，所以 intern 表是这个边界写的字段之一，
它整张随产物走而不做投影：派生值在候选修订里是同一个整数。
这些完整表快照仍保留生产顺序，不是逐声明delta，不能合并任意独立声明编辑；
输入环境有效性、当前顺序装配和生产调度仍须接线。没有借此启用header cache。

query_runtime是参数化key/value的不可变查询owner：显式输入、嵌套计算栈、读取stamp、
反向失效和相等结果截断传播。删除重建使用独立单调stamp，不用revision代替结果版本。
负查询结果是普通value，缺失memo才是Needs；未完成读取不能finish。重新计算父查询
先使其旧读者重新验证，避免经旧memo绕过循环检测；abort不发布半成品。
query-runtime.py的17个成功编译负控覆盖传播、相等截断、边替换、读取记录、循环、
提交边界、角色、驱逐、同revision ABA及在计算期间写入/推进revision/驱逐的拒绝。
JVM/native各有6个owning图测试。它尚未接真实checker，不能据此声称scope/impl/body
读取已完整覆盖或函数增量已上线；后续真实消费者必须明确语义相等及源码视图依赖。

`projection.py` 补源码边界分裂、token/断言来源、旧断言文本及checker两条evidence
构造分支的六个成功编译负控，另有callee owner、模块别名表和签名冲突拒绝的三个
owning断言负控，以及ModuleHeaders推断状态/const类型保留的两个负控。
ModuleBodies将body检查与最终装配分离；五个装配负控覆盖impl/default顺序、const、
test、默认辅助函数签名登记及泛型字典保留；另两个负控守impl入口类型参数与trait查找
（合计18个）。这只是同revision生产边界，
不是模块cache有效性证明，也尚未接上跨revision的具名header重组。
源码token相等不证明AST相等，尤其不能忽略换行的语义。
`identity.py` 验证生产声明候选身份及17个成功编译负控：重复父声明及子路径、
类型/关联效果的绑定槽归一、默认参数歧义、模块world隔离，以及派生身份本身的五个：
拼写丢掉种类字母或模块、跳过终混、派生区间的上下界。具名owning断言必须失败，
编译或链接失败不算负控。typed模式现在通过适配器调用生产声明索引；legacy模式
保留原型身份实现及原来的八个负控。候选key不证明依赖环境或body有效。
同一脚本另跑四个 `ir/lower.densify` 的负控：打包键在 Core 里没有意义，下降期把它们
和 lowering 自己的临时号一起摊成每模块一串小整数，顺序必须与 `ir/coredump.names_of`
一致（captures → params → dicts → evs → body 首次出现），否则同一个局部量在 Core dump 里
叫 `v3`、在 `emitc` 印的 C 里叫 `v5`。提升体用外层给的 symbol id 引用自己的 captures
（`core.CFun.captures`），所以**漏掉 captures 不是缺号而是错号**：它会在 body 第一次
出现时拿到一个排在参数后面的号。因此这四个负控（跳过 captures、把 captures 排到最后、
符号表留着打包键、符号表捎上模块没提到的键）都是顺序断言而不是崩溃。

native-selfhost-tests 分别执行tree、source及identity的owning依赖闭包（包含重叠依赖），
因为新模块尚未被nmain导入，不能只跑主图就宣称它们有native覆盖。

`state-product.py` runs 17 compiling controls for capture, assembly and coordinate
projection: signature/alias/bound writes, frames, diagnostics, environment guards,
the owner declaration's slot row and its installation, symbol order, constant trees,
the frame's agreement with the symbol table, and read-log suffix capture, assembly
and reference relocation. Six controls that replaced a relocation callback with
`Some` are gone with the decision they turned off: relocating a reference between
revisions is the identity now (K5), and `relocate.local_id` and `relocate.signature`
are deleted outright.
It also audits every Cx field and rejects an added unclassified field. The constant
tree control must hit the real TConst owning assertion. This remains in the separate
incremental-state job; the native suite also runs body_product's owning dependency
closure, which overlaps other targets and must not be counted as independent tests.

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

The incremental-reads job runs these read controls and the existing `projection.py`
suite. Moving source projection out of incremental-projection keeps the expanded
typed oracle below the unchanged 660s planning pole without removing any controls.

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
The Java oracle regression took 250.55s, yielding 540s/27min. State products
took 155.55s for 19 controls; they now run separately at 350s/18min, retaining
the other state contracts and their existing budget without exceeding the pole.

`prefix.py` 对照完整 warm/frozen-cold 产品，覆盖12个可编译引擎负控，包括预算、
std身份变化及构造器的负预算拒绝。`--shards N --shard I` 按 index 取模把这12个负控
分片（约定同 `diagnostic-reads.py`），不带旗标时行为不变：正样本加全部12个负控。
正样本只在 shard 0 跑，代价与理由写在 prefix.py 分片处；每个分片仍会先套用全部
锚点，所以锚点漂移在任何一片都是硬失败。`lsp-prefix.py` 覆盖四个 LSP 跨修订负控，要求
owning FAIL 后是断言失败，不把 JVM 链接错误算作成功。三个是工作区接线（会话、绕过
缓存、冲突后留缓存），第四个换掉 `checker.left` 的 resolver：复用产物带的是自己声明
量出来的偏移，加不回候选修订的声明起点，definition 就指向声明搬家前的位置。
它的 owning 判词是 `lsp/server` 的跨修订 definition 案例：同一模块两个修订，
第二个只在声明前加空行与注释，复用两个 body 后问 `lspq` 局部的定义位置，
与新修订的位置以及冷检查的答案逐一相等。该负控同时会红两条同修订判词，
理由记在脚本里：resolver 只有一个，跨修订只有这一条判词在问它。工作区计数测试在共享server里，
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
PreparedBodies` builds a private compiler using the real `run_lsp_configured`
entry. `Legacy` and `Cold` select the other immutable policies; cache budgets
are explicit arguments. The source must already contain the configured entry.
No production CLI flag or wire method is added. Exact source fingerprints,
policy, budgets, observer schema, and artifact hash are recorded. Launch the
resulting `compiler.jar` with the ordinary `lsp` command.

`configured-lsp-contract.py --output <new-dir> --suite all` composes fresh
plain/observed Cold and PreparedBodies builds, both edit matrices, and both
compiling legacy-reparse controls. `--suite standalone` and `--suite project`
retain independent positives for future CI placement. Each control must first
pass its complete semantic/body-count matrix, then fail the exact parse-count
assertion; compilation, linkage, timeout, and unrelated failures never count as
success. See [the runner design](configured-lsp-contract.md) for evidence and
scope. `--self-test` validates orchestration and fail-closed classification
without a compiler. This is correctness coverage, not performance evidence.

`playground-session-contract.py --subjects <manifest.json> --output <new-dir>`
drives the unchanged real Playground WebSocket gateway with explicitly selected,
fingerprinted configured JVM children. It compares plain/observed Cold and
PreparedBodies replies, exact standalone body counts, two-client isolation and
close/reconnect cold ownership. Per-PID private stderr logs cannot be borrowed
between clients. See [the contract design](playground-session-contract.md) for
the manifest and evidence boundary. This does not complete native sandbox or
HTTP `/check` acceptance, and does not change deployment or default policy.

The private configured builder also accepts `--backend native`, using fresh
normal `__emitc` + C-runtime builds rather than a JVM substitute. The gateway
contract's explicit `--backend native` checks executable ELF/hash/PID and the
same four-policy protocol/count matrix; `--compare <JVM-output>` keeps complete
cross-backend semantic equality separate and explicit. JVM defaults are
unchanged. Unsandboxed native protocol evidence does not establish production
systemd resource limits or `/check` reuse; see the design's native section.

The optional private observer emits all Session counters on stderr, and
`lsp-bench.py` preserves them per edit as `analysis_counts`. Cold standalone
analysis has no Session counter: it is recorded as unobserved, never as zero
work. `--uninstrumented` builds the same configured policy without observation;
protocol equivalence and timing runs must distinguish these artifacts. Body
reuse counts alone cannot prove parse avoidance: the legacy Session entry can
reparse safely while reusing the same bodies. The builder's `--self-test`
checks policy injection and fail-closed anchors, not compiler semantics.

`lsp-edit-matrix.py --functions 1000 --output <new-dir> -- <server-command>`
exercises ten real untitled-document revisions: initial analysis, whitespace,
body edit, inferred signature change, reorder, deletion, insertion, error,
recovery, and an identical revision. This is synthetic correctness/count
coverage, not a latency experiment or a real-application hit-rate corpus.
`--expect-reuse` requires exact checked/reused/rejected body and prefix-hit
counts on every revision, including full cold recovery after the error and a
whole-module hit on the identical revision. Counts are derived from the actual
preceding revision, not a separate baseline comparison. The count oracle's
`--self-test` rejects absent, duplicated, unobserved, and changed observations.
`--compare <prior-output>` requires identical source hashes and complete
diagnostics/hover/definition/completion responses across independently selected
policies. Counts are stored separately and excluded from semantic equality;
uninstrumented servers can therefore use the same comparison. Generic,
method/default, project dependency, and retained-memory acceptance remain
separate requirements.

The shared `contract.SourceParseCounts` host observer also accepts `--lsp
<compiler.jar>` to count actual parser/index/projection method entries in an
executable compiler. Compile it with ASM 9.7.1; launch it with that observer
directory and ASM on the classpath, not the compiler jar (the observer loads
the compiler privately). Include `--add-exports=java.base/jdk.internal.vm=ALL-UNNAMED`,
matching the compiler manifest's export that `java -jar` normally applies.
Executable modules and imported selfhost fixtures have distinct namespace
prefixes; both variants require the complete exact descriptor set.
`lsp-edit-matrix.py --expect-parse-counts prepared` requires `(1, 1, 1)` per
revision; `cold` requires `(1, 0, 0)`. Startup parsing is outside each edit's
interval. Protocol replies still compare to the uninstrumented reference.
These counts prove invocation behavior for this matrix, not parser latency,
project dependency behavior, or default activation readiness.
The private builder's `--reparse-control standalone` (or `project`) keeps the
prepared loader but calls the safe legacy Session consumer, forcing it to
construct another snapshot. This is a compiling negative control, not an
optimization mode. Semantic equality and body reuse must still be checked;
only the independent method-entry count oracle should reject reparsing.

`lsp-project-matrix.py --output <new-dir> -- <server-command>` uses the tracked
two-module `project-edit-fixture` without changing its disk files. Eight overlay
revisions cover provider body/signature edits, consumer and provider error
recovery, moved source, and closing/reopening the provider. It records complete
diagnostic publications with consumer versions and hover/definition/completion
replies; `--compare <prior-output>` checks exact cross-policy equivalence using
the same fixture paths, hashes, and generated operation/version/overlay history.
`--expect-reuse` requires the exact body/prefix/refusal/retention census on all
eight revisions, including unobserved downstream work after provider errors.
Both open document versions are checked; closing the provider must send an
unversioned diagnostic clear. `--self-test` exercises these publication and
count oracles. `--expect-parse-counts prepared` requires aggregate `(2,2,2)`
project parse/index/projection entries per revision; `cold` requires `(2,0,0)`.
These are project totals, not source-attributed proof that each module is
processed once. This is a
small synthetic cross-module correctness/count fixture, not latency or
real-application hit-rate evidence.
Edit substitutions require exactly one anchor. Metadata also records hashes
of explicit launch executables, jar arguments, and classpath files; this is
not a transitive runtime-classpath attestation. Supply independently configured
cold and prepared artifacts and retain their builder metadata alongside runs.

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
