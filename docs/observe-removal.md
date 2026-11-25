# 拆除 observe 机制（效果来源的观察孪生）

> 状态：**current** —— 2026-11 分四刀拆除：S1 消费者（`tileir/origin.dawn`）、S2 语言面与契约、S3 后端与运行时、S4 文档收口（本篇）。
> 拆除前的整棵树在 tag `provenance-final`（`b0d34dc5`），考古看那个 tag。
> 留下的是编译器代写调用记录（R4-f，见 [call-records-design.md](call-records-design.md)）：它承担了这套机制原本要承担的目标。
> 原设计文档归档为 [history/effect-provenance-design.md](history/effect-provenance-design.md)。

<!-- 为什么写这篇：删一套已发版、有 295 项契约的机制，不能只留一个 tag。后来的人会问
     「当初为什么做」「为什么又删」「删干净了吗」「哪些东西跟着没了」。这里一次答完，
     并把被推翻的前提写明，免得同样的提案再来一遍。 -->

## 一、结论

observe 机制（handler 臂的 `origin` 子句、`std/provenance`、`observed` 孪生编译、JVM `Provenance` 与 C `dawn_provenance` 两套运行时、
native 的可空观察者 ABI）**正确，但在 R4-f 之后没有任何产品消费者**。留着它每次 push 付近一千秒的 CI，每次改
lower/emit/reach/checker 都要背孪生不变量，所以整体删除。语言面是**已发版特性的删除**（v0.103.0 到 v0.105.0），
按「破坏性变更不做兼容层」直接删，没有弃用别名。

## 二、为什么删

原设计的目标是：把「这次调用来自源码哪里」交给编译器与运行时，tileir 里手写的 `called`/`called_bare`/`user_body` 标记协议
由通用观察设施替代。R4-f 用另一条路到了同一个目标：编译器按效果的 `calls` 子句**代写**调用记录，手写 marks 随之删除。
此后：

- **消费者没有了。** Playground 自 `c193cd17` 起不再观察，改读 `prog.call_table`；gpu-map 与 xmap 读的是录制文件，不读快照；
  `site/gpu-map/record.py` 的观察 harness 因 marks 恒空而空转；`tileir/origin.dawn` 只剩一个旁证脚本在用。
- **常驻成本。** 拆除前 main 上（run 43892969085）观察相关步骤合计 **983 s/push**（contracts-1 69、-3 121、-6 178、-8 372、-9 243），
  占 contracts 九片的约一半。
- **native 运行时多一个可空观察者 ABI。** R1 实测 handler resume 微负载上观察者分支约 +1.0 到 +1.7%（文档估计区间 +1 到 +2.5%），
  `dawn_ctl_apply_arm` 为保尾调用拆成两路，`dawn_prov_site_*` 还要分翻译单元。
- **腐烂已经发生。** R4-f 的实现为观察孪生写了「不拆内层函数」的约束（多一个调用帧与 Definition 身份）；f2 因 `actual-goldens`
  的观察容量要从 1 Mi 提到 4 Mi 多耗一轮；旧影子比较的预言（手写 marks）消失后只能删。
- **别的系统怎么做。** Go `-cover`/`-race`、Rust `-C instrument-coverage`、GHC `-prof` 的插桩都是显式构建请求下的模式，没有谁为取位置
  常驻一份依赖栈的第二编译产物；常开的只有静态元数据（source map、`.dawnmap`）。GHC 的双编译最像 observed 孪生，但它有真实的日常消费者（性能调优），这里没有。

## 三、删了什么

四刀，每刀一个 PR；提交哈希以 main 上的为准。

| 刀 | 范围 | 提交 |
|---|---|---|
| S1 消费者切除 | 删 `packages/tileir/src/origin.dawn`（535 行，含 6 个 test 块）与 `scripts/tile-origin-mutants/`；`tileir` 升 0.34.0（破坏性，无兼容层）；tile inputs 变化后三卡（sm_86 / sm_90 / sm_100）重录账，设备字节逐字节不变 | `381966f3`、`f823da6a` |
| S2 语言面与契约 | parser/AST/checker/LSP 的 `origin` 子句与观察入口、`check/provenance.dawn`、`std/provenance`；`effect-provenance-contract`、`effect-provenance-bench` 两个契约目录与五个 CI 步骤；spec 关键字 16 到 15，§6.5 观察全段；VS Code 语法清单；contracts 九片并为八片 | `af51bd3f`、`684bd3dd`、`4718ab9a`、`037be6b5` |
| S3 后端与运行时 | `provenance_*` 原语声明与两后端的臂（同一提交，`intrinsic-parity` 双向对账）、`observed` 孪生与 reach 掩码、`jvm/outline.dawn`、`ir/provenance.dawn`、`ir/tail.dawn`、`Provenance.java`、`dawn_provenance.{c,h}`、native 可空观察者 ABI（`dawn_ctl_apply_arm` 回到无观察者的尾调用形态） | `363af389`、`0ad628a3`、`6709b1bd` |
| S4 文档收口 | 本篇与原设计的归档、索引与引用文档的措辞 | 本 PR |

规模：S1 约 −600 行；S2 约 130 个文件、−12.3k/+0.5k 行（大头是契约脚本与数据）；S3 29 个文件、+358/−5039 行（比估计少，因为估计把 S2 已删的契约部分也算了进去）。

### 数据出处

- CI：S2 之后五个观察步骤原合计 911 s/push（run 43970977404 的实测，69/122/258/314/148）；`push-total` 由 41559 降到 40809。
  新的各片 claim 是**建模值**（20000 次抽样，样本为 13 次 main push 与 46 次 PR 运行），不是七日窗口观测，待新布局累积七日后复测。
- 输出：未使用观察的程序，用 S2 之后的编译器与 S3 的编译器各编一遍，22 个目标的 JVM `__emit` 与 16 个目标的 C `__emitc` 逐字节无差。
  JVM 与 native 两个自举固定点 B==C。
- 声明过的输出变化：S2 的 11 个 `emit *`、`doc --builtins`、`lsp`；S3 追加 `doc --builtins`（内置清单少 13 个 provenance 声明）。

## 四、留下了什么

- **R4-f 代写调用记录**：`Sig.calls`、`lower_fn` 与 `emit_return` 的出口钩子、录制器的 `Snap`；`StagedIter` 签名上的 `at: Loc = caller()`。
  tile 的调用表读这条路，Playground 的 tilemap 视图读 `prog.call_table`，与观察无关。
- **静态身份层的非观察读者**：`CDefinition`、`CSyntax`、`CallSource` 仍被 emitc、coresites 与 lint 读；`dawn_ctl_apply_arm` 本身保留。
- **名字相近但无关的东西没动**：`AnalysisObserver`、`observable_impls`、CI 预算观察器（`ci-budget-observer-design.md`）、包来源（`pkg-origin`）。
- **`origin` 回到普通标识符。** grammar 语料里新增一条 reject：`origin` 子句现在报 ``expected `=>` after handler arm clauses``，没有另造诊断。
- 旧设计里 §一的证据（为什么「设备字节相同」不能证明「源码归属相同」）仍然成立，见归档文档。

## 五、如实记账：随删除一并消失的独立改进

这些不是失败，是和孪生绑在一起、没有别的消费者，所以一起走：

1. **R1**（`e6d1cb42`，+6392/−884，120 个文件）：结构化快照/视图/静态表 API、checkpoint/rewind、容量与有界观察、`dawn_ctl_apply_arm` 为保尾调用拆出的两路（S3 恢复为原形态）。
2. **R2 / R2b / R2′**：站点表上限与 8000 字节切分、分翻译单元的 `dawn_prov_site_*`、`jvm/outline.dawn` 的线性化
   （`8454fcd9` 一次算全部后缀的事实，`1003624d` 去掉每层复制余下语句）及孪生「不拆内层函数」的约束。只服务观察孪生，没有孪生就没有消费者。
3. **W1**（`758f0d0a`）静态身份层：保留非观察读者的部分，其余随删。
4. **W2**（`92df11b0`）`origin o` 子句、基本 observe/note/completed：已发版 v0.103.0 到 v0.105.0，S2 删除。
5. 随之退役的还有 Playground warm 门（它量的是观察成本面），VS Code 语法对 `origin` 的特殊规则（随下一次扩展发版生效，S2 未单独发版）。

## 六、被推翻的前提

- **「通用观察设施可以替代手写 marks」**：原提案（2026-10-25）的前提。实际落地的是更小的东西：按声明、逐效果的代写记录。
  调研时已写明这一点：没有被比较的系统会为取位置而常驻第二份产物。
- **「observe 可作代写记录的独立旁证」**：W3-R 期间的理由之一。补裁放弃了用影子比较保住它，正确性改由代写调用流对删除前检出的逐字段对拍与负控承担，旁证角色随之消失。
- **「录制器的 marks 可以被 observe 视图取代」**：`call-records-design.md` 非目标 1 就写了没有已知能过 Playground 门的表示。

## 七、不做的（理由）

- **只删 W3-R 新增，回到 v0.105.0 面（B1）**：约删 10 到 12k 行、省 400 到 600 s/push，但 W1/W2 的契约仍要跑，且仍有一半无消费者的机制；W3-R 修掉的 W2 旧缺陷会回归。
- **只留静态身份层（B2）**：这层新增的数据只服务观察，留下等于一堆无人读的字段。非观察读者用到的那部分已经保留（见第四节）。
- **全保留（C）**：收益是「将来可能有 profiler/诊断消费者」，没有现存需求，也不排期；成本是上面的 983 s/push 与持续腐烂。
- **兼容层或弃用别名**：已发版面没有外部使用者，不做。
- **把 `record.py` 的 harness 改回 native**：与本次拆除无关，不并入。

## 八、考古入口

- 整棵树：tag `provenance-final`（`b0d34dc5`）。
- 原设计与 W1/W2/W3-R 的实施记录：[history/effect-provenance-design.md](history/effect-provenance-design.md)。
- 那一时期的自动来源核账：[history/m7-progress.md](history/m7-progress.md) 的「自动来源 P1 后续核账」一节。
- 代写调用记录：[call-records-design.md](call-records-design.md)。
