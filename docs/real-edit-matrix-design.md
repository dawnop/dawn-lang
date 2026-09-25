# 真实编辑矩阵：replay 的计数与命中率

> 状态：current。第 5 期计数刀：十种编辑 × 四类工作负载的精确计数预言已落地，本机 n=1000 全部 40 格与预言逐格相等、与冷检查逐体相等；计时、CI 接入不在本刀。
> 2026-09-26（#165）：体级诊断守卫改为按 body，`body_one_type_error` 正向预言从 R + (n − m) 改为 R+1，见「首次推导错的一格」末尾与 [body-diag-guard-design.md](body-diag-guard-design.md)。

## 为什么要这张矩阵

G3 原文要求「给出真实编辑语料的命中率」（计划 `incremental-engine-goal-and-plan-20260913.md:222-224`）。
到本刀为止仓内能回答这个问题的只有两处，都答不了：

- `bench-replay` 的 Scale1000 只有一种「编辑」：文件头加一行注释（旧 `bench-replay.dawn.txt:125`），
  也就是整体平移。所有被准入的体都挺得过平移，所以它报的命中数（calls n+2、primitive_inferred n+1、
  generic n）只是「准入了多少」，不是「一次普通编辑后还剩多少」。
- `lsp-edit-matrix.py` 有十种修订，但语料只有 scalar 形状 `value_i(x) = x + i`，走 LSP 协议，
  CI 里只跑 20 个函数；calls、generic、推断类都不在里面。

仓内外也没有「命中率」的定义。本刀按任务单的裁定定义它，并把每格的计数钉成精确预言。

## 命中率的两个分母

- **全体分母**：`hit_rate_all = reused / body_count`。`body_count` 是这一修订被访问的全部 body，
  包括永远不准入的 method / default / test / const 角色。
- **可准入分母**：`hit_rate_admissible = reused / (body_count − by_role)`。`by_role` 是上面四种角色的
  body 数，由 Dawn 侧从冷检查的 `ModuleBodies` 直接数出来（`len(constants) + len(impl_methods) +
  len(trait_defaults) + len(tests)`），预言里也独立写了一份（只有 generic 类的 impl 方法，1 个）。

两个都报。`cold_unadmitted` 与 `cold_rejected` 分栏报，不合并：前者量的是准入类有多窄，后者量的是
环境移动了多少，只有后者是更好的校验能缩小的（`scalar_replay.dawn:48-57` 的注释原话）。
注意 lambda 推断类的 member 不是按角色拒绝，而是按形状拒绝，所以它们留在可准入分母里，
该类两个命中率都是 0。

## 编辑语料

每种编辑都是相对前一修订的独立第二修订。被编辑的 member 一律取中间那个（下标 `m = n/2`）。

| 编辑 | 做法 | 它压的是哪条路径 |
|---|---|---|
| `identical` | 字节相同的重提交 | 基线：准入了的全部命中 |
| `shift` | 文件头加一行注释 | 等于现有 Scale1000；声明整体平移 |
| `body_one` | 第 m 个 member 的字面量 `m` 改成 `m+1` | 改一个体，类型不变；`pair` 的拼写比较（`:555`） |
| `body_one_type_error` | 第 m 个 member 的字面量改成 `false`，第三修订恢复 | 体内诊断（header 干净）；错误态与恢复 |
| `inferred_return` | 末尾追加 `edit_probe() = 1` 与两个透传调用方，把 `1` 改成 `true` | 推断签名变化使调用方 Rejected（`:616`） |
| `ws_between` | 第 m 个 member 之前插一个空行 | 声明之间的空白：后半部分平移 |
| `ws_inside` | 第 m 个 member 的 ` = ` 改成 ` =  ` | 声明内部 token 之间的空白：`same_text`（`:565`） |
| `insert_decl` | 在第 m 个 member 前插入新 member（名字用下标 n） | 新声明没有缓存键 |
| `delete_decl` | 删掉第 m 个 member（member 之间互不调用） | 删声明，其余键不动 |
| `reorder` | 交换第 m 与第 m+1 个 member | 键按名字而非位置 |

几条取舍：

- `body_one` 的新字面量与旧的等长（n=1000 时 500 → 501），token 种类也相同。这样只有「拼写」这一道检查
  能拦住它，负控 `identity-blind` 才有意义（见下）。
- primitive_inferred 与 lambda 推断类没有显式签名函数，`body_one` 只能改推断函数的体；返回类型不变
  （仍是 Int），所以没有下游。
- `inferred_return` 自带探针，因为四类工作负载里**没有**一个推断函数能在不制造调用方类型错误的前提下
  改返回类型：primitive_inferred 唯一有调用方的是 `seed()`，而 `seed() + i` 要求 Int；其余三类根本没有
  被调用的推断函数。探针是 `fn edit_probe() = 1`、`fn edit_probe_a() = edit_probe()`、
  `fn edit_probe_b() = edit_probe()`，k=2 个调用方都是推断的透传，改成 `true` 后仍然良类型。
  探针只在这一种编辑里出现，所以其余编辑的 before 修订逐字节就是 Scale1000。

## 工作负载

四类，各 n=1000，全部来自 `replay-workloads.dawn.txt`（本刀从 `bench-replay.dawn.txt:40-91` 抽出的共享
生成器，bench-replay 现在也用它；抽取前后九类在 n=1、7、1000 下逐字节相同，已核对）：

| 类 | 组成 | body_count | 按角色不准入 |
|---|---|---|---|
| calls | `helper`、`helper2` + n 个显式签名调用者 | n+2 | 0 |
| primitive_inferred | `seed() = 1` + n 个 `ipI() = seed() + I` | n+1 | 0 |
| generic | `trait Scale` + `type Coin` + 一个 impl 方法 + n 个有界泛型函数 | n+1 | 1（impl 方法） |
| inferred | n 个含 lambda 的推断函数 | n | 0 |

inferred（含 lambda）类今天**没有任何准入**，预期命中 0，如实报 0。这就是 G3「inferred 类」的真实状态。

## 三个修订步

每格跑三步，每步都与同一修订的冷检查逐体比较（`equal_bodies`，与 bench-replay 同一份，现在在共享文件里）：

1. `replay`：before 的录制经 `admit` 后，`scalar_replay.replay` 到 after。
2. `renew`：同一份准入经 `replay_and_record` 到 after，得到续期后的缓存。计数必须与第 1 步相等。
3. `back`：用第 2 步续期出的缓存再 `replay_and_record` 回 before，即任务单要求的 before→after→before。

矩阵表里的「正向」一行是第 2 步（它同时带 `visited` 与 `capture_refused`）；第 1 步的计数若与之不同，
算在正向那一格的 `oracle_ok` 里。第 3 步单列一张表。

本刀直接调 `scalar_replay`，与 bench-replay 同一层；没有经过 `driver/incremental.dawn` 的会话。
会话在这层之上多两条规则：header 有诊断时整模块冷（`scalar_replay.dawn:645`、`:664` 的 `valid`，
这一条本层也有），模块有诊断时丢缓存（`analyze.dawn:1192`）。第二条本层看不到，见「不做的」。

## 预言的推导

记 `R` = 按角色不准入的 body 数（generic 为 1，其余 0），`B` = 该类基线 body 数，
「形状拒绝」= lambda 推断类的 member（每个都是 Unadmitted）。所有格的公共部分：

- 按角色不准入的 body 走 `pass_executor` 的四个 cold 分支，一律 `unadmitted`（`scalar_replay.dawn:772-775`）。
- lambda 推断类的 member 在录制时就被 `recorded` 拒绝，不进 `entries`；回放时
  `map.get(prepared.ready.entries, key)?` 取空（`:536`），一律 Unadmitted。所以该类任何编辑都是
  `reused = 0`，只有探针（形状可准入）会贡献 Rejected。
- 缓存键是名字路径 `Named(FunctionDecl, name)`（`identity.dawn:388`），回放按 `d.lo` 找到候选修订里的键
  （`:454`、`:535`）。泛型绑定的 id 是声明键与槽位打包出来的（`allocation.dawn:1-12`、`:106`），
  增删与换序不改动它们，所以 `allocation.between`（`:442`）在本矩阵的每一格都成立。
- `visited` 等于该修订的 body_count（每个 body 恰好走一次，命中或冷算）；`capture_refused` 处处为 0
  （含诊断的体照样被捕获，只是 `recorded` 在 `:306` 拒绝把它准入）。
- `checked = cold_unadmitted + cold_rejected`，`reused = body_count − checked`。

逐编辑（正向 / 回程），非 lambda 类：

| 编辑 | 正向 | 回程 | 理由 |
|---|---|---|---|
| `identical`、`shift`、`ws_between` | 未准入 R | 同左 | 声明整体平移时 `pair` 与 `same_text` 都成立（`:555-566`），全部命中 |
| `reorder` | 未准入 R | 同左 | 键按名字；`pair` 按各自修订的声明下标取 token 切片，换序不影响 |
| `body_one` | 未准入 R+1 | R+1 | 字面量拼写不同，`pair`（`:555`）拒绝；回程时续期缓存里是 after 的冷产物，字节又不同 |
| `ws_inside` | 未准入 R+1 | R+1 | token 相同但声明内偏移变了，`same_text`（`:565`）拒绝；回程同理 |
| `body_one_type_error` | 未准入 R+1 | R+1 | 只有被改的体自己报了诊断；守卫按 body（#165），其后的体照常命中。改前是 R + (n − m)，见下一节 |
| `inferred_return` | 未准入 R+1，拒绝 2 | 同左 | 探针本体字节变了 → Unadmitted；两个调用方字节没变、准入通过，但录制的 `FunctionAnswer(edit_probe)` 与候选修订的签名不等，`call_header_fact`（`:616`）判 Rejected；回程方向相反，同样 1 + 2 |
| `insert_decl` | body B+1，未准入 R+1 | 未准入 R | 新声明没有键；回程时它消失，其余全在续期缓存里 |
| `delete_decl` | body B−1，未准入 R | 未准入 R+1 | 删掉的声明没有调用方，其余键不动；回程时它重新出现，续期缓存里没有它 |

lambda 推断类：各格未准入 = 该修订 member 数（n，插入后 n+1，删除后 n−1），`inferred_return` 再加探针本体 1、
拒绝 2，其余为 0。

### 首次推导错的一格：`body_one_type_error` 正向

最初按「只有被改的体冷算」推导，正向应为未准入 R+1。实测是 R + 500（n=1000）。归因是推导漏了
`relocation` 的第一道门：

```
if cx.diags != [] { return None }      # scalar_replay.dawn:516
```

这里的 `cx` 是调度器带着走的上下文，前面冷算出的诊断留在里面。第 m 个体一报错，此后调度到的
每个体都在这道门前变成 Unadmitted。调度顺序是「推断函数先按调用依赖序，其后显式函数按声明序」
（`checker.dawn:15110`），所以本矩阵里冷掉的恰好是第 m 个及其之后的 `n − m` 个 member。
改后的推导：正向未准入 = R + (n − m)（lambda 类仍是 n）。回程时错误已恢复，续期缓存里除了报错那个体
（有诊断，`:306` 拒绝准入）之外都在，所以回程是 R+1。

这不是正确性缺陷：三步的 typed 结果都与冷检查逐体相等。它是精度上的悬崖：一个体内错误让排在它后面的
整段模块冷算，错误位置越靠前越糟，报错的是推断函数时会连带全部显式函数。它也不是按形状拒绝，
全体分母与可准入分母都降到约 0.50。是否要把这道门收窄到「诊断属于本体」由维护者裁决，本刀不动 `selfhost/`。

**2026-09-26 收窄（#165）。** 裁决是收窄：`relocation` 的整上下文门删掉，诊断守卫只剩按 body 的那一道，
即 `recorded` 拒绝准入「自己这次检查产生了诊断」的产物（`:306`，产物的 `diagnostics` 是本体相对进入时
诊断表的增量，前面的体报了什么都不进它）。泛型类另有两处同样读整张表的门（`function_entry_proof.prove`
的 `len(candidate.diags) != 0` 与 `bounded_replay` 的 witness 检查），一并改成「长度相对进入时」。
正向预言因此回到最初的 R+1（calls 1、primitive_inferred 1、generic 2，lambda 类仍 n），与回程相同；
n=20 的 calls 从「reused 12, unadmitted 10」变成「reused 21, unadmitted 1」。
理由与负控见 [body-diag-guard-design.md](body-diag-guard-design.md)。下面「实测」的表是 09-23 改前的原始记录，
`body_one_type_error` 四行在改后是：

| 类 | body | checked | reused | 未准入 | 拒绝 | 全体 | 可准入 |
|---|---|---|---|---|---|---|---|
| calls | 1002 | 1 | 1001 | 1 | 0 | 0.9990 | 0.9990 |
| primitive_inferred | 1001 | 1 | 1000 | 1 | 0 | 0.9990 | 0.9990 |
| generic | 1001 | 2 | 999 | 2 | 0 | 0.9980 | 0.9990 |
| inferred | 1000 | 1000 | 0 | 1000 | 0 | 0 | 0 |

其余 36 格不变；三步的 typed 结果仍与冷检查逐体相等。

## 实测

命令（worktree 根目录）：

```
python3 scripts/incremental-semantics-contract/edit-matrix.py            # 默认四类 × 十编辑，n=1000
python3 scripts/incremental-semantics-contract/edit-matrix.py --self-test
python3 scripts/incremental-semantics-contract/edit-matrix.py --controls  # 负控，见下
```

环境：2026-09-23，WSL2（Linux 6.18），16 核，15 GiB，JDK 为 PATH 上的 OpenJDK 26.0.1（`bin/dawn` 编译用
GraalVM 21），基线 main `1845817b`。机器上同时有另一位写者在跑，**不报任何时间结论**；计数与机器无关。
全部 40 格 `oracle_ok`，三步的 typed 结果都与冷检查相等。

正向（before → after，`replay_and_record`；`replay` 的计数与之逐格相等）：

| 类 | 编辑 | body | checked | reused | 未准入 | 拒绝 | visited | 捕获拒绝 | 全体 | 可准入 |
|---|---|---|---|---|---|---|---|---|---|---|
| calls | identical | 1002 | 0 | 1002 | 0 | 0 | 1002 | 0 | 1.0000 | 1.0000 |
| calls | shift | 1002 | 0 | 1002 | 0 | 0 | 1002 | 0 | 1.0000 | 1.0000 |
| calls | body_one | 1002 | 1 | 1001 | 1 | 0 | 1002 | 0 | 0.9990 | 0.9990 |
| calls | body_one_type_error | 1002 | 500 | 502 | 500 | 0 | 1002 | 0 | 0.5010 | 0.5010 |
| calls | inferred_return | 1005 | 3 | 1002 | 1 | 2 | 1005 | 0 | 0.9970 | 0.9970 |
| calls | ws_between | 1002 | 0 | 1002 | 0 | 0 | 1002 | 0 | 1.0000 | 1.0000 |
| calls | ws_inside | 1002 | 1 | 1001 | 1 | 0 | 1002 | 0 | 0.9990 | 0.9990 |
| calls | insert_decl | 1003 | 1 | 1002 | 1 | 0 | 1003 | 0 | 0.9990 | 0.9990 |
| calls | delete_decl | 1001 | 0 | 1001 | 0 | 0 | 1001 | 0 | 1.0000 | 1.0000 |
| calls | reorder | 1002 | 0 | 1002 | 0 | 0 | 1002 | 0 | 1.0000 | 1.0000 |
| primitive_inferred | identical | 1001 | 0 | 1001 | 0 | 0 | 1001 | 0 | 1.0000 | 1.0000 |
| primitive_inferred | shift | 1001 | 0 | 1001 | 0 | 0 | 1001 | 0 | 1.0000 | 1.0000 |
| primitive_inferred | body_one | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 0.9990 |
| primitive_inferred | body_one_type_error | 1001 | 500 | 501 | 500 | 0 | 1001 | 0 | 0.5005 | 0.5005 |
| primitive_inferred | inferred_return | 1004 | 3 | 1001 | 1 | 2 | 1004 | 0 | 0.9970 | 0.9970 |
| primitive_inferred | ws_between | 1001 | 0 | 1001 | 0 | 0 | 1001 | 0 | 1.0000 | 1.0000 |
| primitive_inferred | ws_inside | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 0.9990 |
| primitive_inferred | insert_decl | 1002 | 1 | 1001 | 1 | 0 | 1002 | 0 | 0.9990 | 0.9990 |
| primitive_inferred | delete_decl | 1000 | 0 | 1000 | 0 | 0 | 1000 | 0 | 1.0000 | 1.0000 |
| primitive_inferred | reorder | 1001 | 0 | 1001 | 0 | 0 | 1001 | 0 | 1.0000 | 1.0000 |
| generic | identical | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 1.0000 |
| generic | shift | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 1.0000 |
| generic | body_one | 1001 | 2 | 999 | 2 | 0 | 1001 | 0 | 0.9980 | 0.9990 |
| generic | body_one_type_error | 1001 | 501 | 500 | 501 | 0 | 1001 | 0 | 0.4995 | 0.5000 |
| generic | inferred_return | 1004 | 4 | 1000 | 2 | 2 | 1004 | 0 | 0.9960 | 0.9970 |
| generic | ws_between | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 1.0000 |
| generic | ws_inside | 1001 | 2 | 999 | 2 | 0 | 1001 | 0 | 0.9980 | 0.9990 |
| generic | insert_decl | 1002 | 2 | 1000 | 2 | 0 | 1002 | 0 | 0.9980 | 0.9990 |
| generic | delete_decl | 1000 | 1 | 999 | 1 | 0 | 1000 | 0 | 0.9990 | 1.0000 |
| generic | reorder | 1001 | 1 | 1000 | 1 | 0 | 1001 | 0 | 0.9990 | 1.0000 |
| inferred | identical | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | shift | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | body_one | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | body_one_type_error | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | inferred_return | 1003 | 1003 | 0 | 1001 | 2 | 1003 | 0 | 0 | 0 |
| inferred | ws_between | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | ws_inside | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |
| inferred | insert_decl | 1001 | 1001 | 0 | 1001 | 0 | 1001 | 0 | 0 | 0 |
| inferred | delete_decl | 999 | 999 | 0 | 999 | 0 | 999 | 0 | 0 | 0 |
| inferred | reorder | 1000 | 1000 | 0 | 1000 | 0 | 1000 | 0 | 0 | 0 |

回程（after → before，用正向续期出的缓存）与推导表一致：`body_one_type_error` 回到未准入 R+1
（calls 1、primitive_inferred 1、generic 2），`insert_decl` 回到 R，`delete_decl` 为 R+1，其余与正向同；
逐格数字在 `--output` 目录的 JSON 里。

跨十种编辑的命中率（正向一行；百分位取最近秩，十个值时 p50 是第 5 小，p95 是最大值）：

| 类 | p50 全体 | p95 全体 | p50 可准入 | p95 可准入 |
|---|---|---|---|---|
| calls | 0.9990 | 1.0000 | 0.9990 | 1.0000 |
| primitive_inferred | 0.9990 | 1.0000 | 0.9990 | 1.0000 |
| generic | 0.9980 | 0.9990 | 0.9990 | 1.0000 |
| inferred（lambda） | 0 | 0 | 0 | 0 |

p50/p95 都落在高端，看不见 `body_one_type_error` 那一格的 0.50；读矩阵要看最小值那一格，不能只看百分位。

## 负控

五个能编译的变异体，改的都是私有副本里的 `selfhost/`，锚点必须恰好出现一次（`--check-anchors` 不编译、
只在内存里套一遍，`--self-test` 也会调它）。`--controls` 先逐个跑变异体，要求它拥有的格变红
（计数或 typed 结果与预言/冷检查不符，而不是编译失败或崩溃），最后把源码恢复原样重建，要求整张矩阵变绿。

| 变异体 | 改动 | 拥有的格 |
|---|---|---|
| `same-text-blind` | `same_text` 在长度比较处直接返回相等（`source_projection.dawn:151`） | calls / primitive_inferred / generic × `ws_inside` |
| `identity-blind` | 同上，再让 `pair` 不比拼写（`:135`） | 同三类 × `body_one` |
| `inferred-callers-kept` | 回放循环里跳过 `call_header_fact` 及其后的重验（`scalar_replay.dawn:616`） | 四类 × `inferred_return` |
| `whole-context-diagnostics` | `relocation` 开头加回 `if cx.diags != [] { return None }`（#165 之前的整上下文门） | 三类非 lambda × `body_one_type_error` |
| `entry-proof-whole-context` | `function_entry_proof.prove` 加回 `len(candidate.diags) != 0` | generic × `body_one_type_error` |

任务单写的是「让 `same_text` 对改过的体也返回相等，`body_one` 格必须红」。只改 `same_text` 时 `body_one`
不会红：字面量拼写不同，`pair`（`:555`）在 `same_text` 之前就拒绝了。所以拆成两个：只瞎 `same_text` 的那个
拥有 `ws_inside`（只有它挪字节而不动 token），两道都瞎的那个拥有 `body_one`。`body_one` 选等长同种类
的字面量就是为了这一点。实测红绿见本机报告。

## 不做的（理由）

- **计时**。机器上有别的写者，任何墙钟数字都无效；本刀只产计数，Dawn 侧不启动任何计时器。
  G3 的「每体代价低于冷检查」留给下一刀，届时直接复用本矩阵的修订对。
- **CI 接入**。`.github/workflows/gates.yml` 正由另一位写者拆片，本刀不碰；放置建议只写进报告。
- **per-class 计数器**。`Replayed` / `Renewed` 只有模块级总数（`scalar_replay.dawn:39-46`）。按类拆分要改
  `selfhost/`，而本矩阵每格只有一类工作负载，总数已经就是该类的数。
- **会话层**。本刀不经过 `driver/incremental.dawn`；「模块有诊断丢缓存」（`analyze.dawn:1192`）会让
  `body_one_type_error` 的回程在会话里变成全冷，这一层的计数由 `lsp-edit-matrix.py` 的 error/recovery 修订覆盖。
- **header 诊断编辑**。header 有诊断时 `valid` 为假，整模块冷（`:645`），结论平凡，不占一格。
- **多模块**。跨模块失效由 `lsp-project-matrix.py` 负责；本矩阵是单模块。
