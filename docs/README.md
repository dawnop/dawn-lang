# docs/ 索引

> 状态：**current** —— 全目录的分层与生命周期索引。**每篇文档的权威生命周期在它自己的
> 文件头**；本索引只帮助定位材料，不登记设计任务进度。

`docs/` 下现有 99 篇文档 <!-- doc-check: doc-count -->，按时间叠加，混着**规范、调研、
设计方案、落地日志、复盘和运维说明**。读者无从判断哪几段还成立——`design.md` 说实现语言
是 Kotlin，`bootstrap.md` 说 LSP 还在 Kotlin，两者都是当时的事实、现在都不是。
这份索引把它们分层，并标出文档生命周期。**篇数与「每篇都在索引里」这两件事都由
`scripts/doc-check.py` 核对**，所以上面那个数字不会像它的前任（长期停在 43）那样烂掉。

**文档生命周期取值**

| 生命周期 | 含义 |
|---|---|
| **normative** | 权威定义。实现与它冲突就是实现的 bug。只有一篇。 |
| **current** | 描述当前的架构或流程，可以照着做。 |
| **historical** | 当时的决策/调研/落地记录。**读作历史，不是现状**；结论可能已被后续推翻。 |
| **proposed** | 已写成方案、尚未评审通过。范围与决策点可读，**不要照着实现**。 |

---

## 权威规范

| 文档 | 生命周期 | 说明 |
|---|---|---|
| [spec.md](spec.md) | **normative** | 语言的权威定义（词法、类型、效果、comptime、互操作、编译模型）。 |
| [spec.en.md](spec.en.md) | **normative** | 上面那篇的**英文译本**。改规范先改中文，再改这里；两者不脱节由 `doc-check.py` 的 transl 检查盯着。 |
| [grammar.ebnf](grammar.ebnf) | historical | 机器可读语法，**已落后于 parser**（2026-08-04 复核仍成立：缺 `use … as`、要求所有函数写 `-> type`、用未定义的 `UPPER_IDENT`、`. IDENT` 不覆盖 `Class.FIELD`）。以 spec.md 与 `selfhost/src/front/parser.dawn` 为准；可执行的那份期望是 `scripts/grammar-corpus/`（CI 门禁），文法的分叉现在以一个失败用例出现。SYN-02/SYN-03 已从**另一头**关掉——本文件写对了，是实现补上了它，逐条见文件头部。 |

## 当前全仓审查（v2）

| 文档 | 生命周期 | 说明 |
|---|---|---|
| [codebase-audit-v2.md](codebase-audit-v2.md) | current | v0.60 冻结严重度与证据、机器权威的当前四状态分区、冻结 P1 映射和执行顺序。 |
| [codebase-audit-v2/00-methodology-and-retractions.md](codebase-audit-v2/00-methodology-and-retractions.md) | current | 基线、证据等级、严重度、历史快照与处置边界。 |
| [codebase-audit-v2/01-syntax-and-formatting.md](codebase-audit-v2/01-syntax-and-formatting.md) | current | lexer、parser、formatter、pattern 与编辑器语法。 |
| [codebase-audit-v2/02-types-effects-and-semantics.md](codebase-audit-v2/02-types-effects-and-semantics.md) | current | 类型、效果、Cursor/Char 与 nominal abstraction。 |
| [codebase-audit-v2/03-compiler-and-runtime-architecture.md](codebase-audit-v2/03-compiler-and-runtime-architecture.md) | current | checker、Core、comptime 与双后端架构。 |
| [codebase-audit-v2/04-cli-lsp-build-and-release.md](codebase-audit-v2/04-cli-lsp-build-and-release.md) | current | CLI、LSP、依赖、自举与发布链。 |
| [codebase-audit-v2/05-stdlib-and-packages.md](codebase-audit-v2/05-stdlib-and-packages.md) | current | std、inflate、JSON、Web 与 SHA-2。 |
| [codebase-audit-v2/06-docs-tests-and-governance.md](codebase-audit-v2/06-docs-tests-and-governance.md) | current | normative spec、文档状态、examples/packages/contract gates 与仓库治理。 |

## 当前架构与流程

| 文档 | 生命周期 | 说明 |
|---|---|---|
| [bootstrap.md](bootstrap.md) | current | 自举链：种子 → A → B → C、固定点、种子推进协议。 |
| [bootstrap-input-manifest-design.md](bootstrap-input-manifest-design.md) | current | TOOL-14 的 project-only Producer 与已落地的完整 v2 launcher generation：framed digests、pre/post re-plan、可恢复 commit-marker。 |
| [package-design.md](package-design.md) | current | 源码包（`[deps]`）与 Maven 依赖（`[java-deps]`）的清单与解析。 |
| [runtime-intrinsics-design.md](runtime-intrinsics-design.md) | current | 运行时 intrinsic 契约——每个 primitive 归哪个运行时模块。**表已从 `emit.dawn` 的 `(class, method)` 收成 `types.dawn` 的 `Rt`/`Intr`（文中的 `rt_intrinsic_target` 是旧名，已不存在）；§8 的三步 Move 表已被 [core-move2-design.md](core-move2-design.md) 更正**。 |
| [core-move2-design.md](core-move2-design.md) | historical | 上面那张表里「Move 2 控制流/match」的**结账盘点**：主体已随 Core IR Phase 0 落地；残余 `CSProtect`（error-model 的 C2）已于 2026-07-31 裁决**关档不做**。`bracket` + `with` + 当时的 `fn` 尾闭包随 v0.39.0/v0.40.0 发布；尾闭包拼写后来由 #206 尾块取代。 |
| [trait.md](trait.md) | current | trait/impl/derive 与 `Ord`。§落地记录里 Float 比较那段已被实现取代（见文内标注）。 |
| [tutorial.md](tutorial.md) | current | 上手教程，**英文正本**。标 `dawn run` 的代码块由 `scripts/doc-check.py` 真编真跑并核对 `output`。 |
| [tutorial.zh-CN.md](tutorial.zh-CN.md) | current | 上面那篇的**中文译本**。改教程先改英文，再改这里；两者不脱节由 `doc-check.py` 的 transl 检查盯着。 |
| [codebase-audit.md](codebase-audit.md) | historical | 2026-07-25 的全仓审查，76 条逐条带当时的处置结论；保留证据与排期，不作当前风险台账。 |
| [audit/README.md](audit/README.md) | historical | 上面那份旧审查遗留待办的历史作业计划：十三份材料的索引、依赖、修复顺序与“不做”理由均保留；当前顺序看审查 v2。 |
| [audit/native-plan-overlap.md](audit/native-plan-overlap.md) | current | 上面那批待办与 native-backend-plan.md 的**撞车登记**：谁让位、谁冻结、谁要改写。动 `audit/` 里任何一份之前先读它。 |
| [native-backend-plan.md](native-backend-plan.md) | current | native 后端的分阶段计划（Phase −1 → 6）与落地日志。**Phase −1…6 全部完成**，Phase 6（native 自举）于 2026-07-30 达成（§14.23，提交 `83def2d`，`scripts/native-fixpoint.sh` 验 B==C + 裸目录 smoke）；重排后的 S0–S4 也已结清。仍开着的只有 `use c` FFI（推迟，见 B 线 K-B6）与 S5「std 收口」（[std-audit.md](std-audit.md)）。 |
| [native-driver-plan.md](native-driver-plan.md) | current | **B 线**：native 驱动补全 + 把后端契约摆到明面上——K-B 刀表、「5,373 行零 `use java`」的核对、以及那条最重要的更正：几条差分脚本的被测方原本写死 `./bin/dawn`，**接上线不会自动覆盖 native**（已由 `native-cli-diff.sh` 修掉）。**七刀已结**：K-B1–K-B5 与 K-B7 落地（逐刀带红演示与阴性对照），K-B6（`use c` FFI）明确推迟。 |
| [jvm-base-plan.md](jvm-base-plan.md) | current | **A 线**：收缩 JVM 后端的可信底座——V49（classfile major 61 → 49）可行性审计的结论与三个代价数、九条被推翻的预设、K-A 刀表。**已 done**：K-A0/K-A0.5/K-A1/K-A3/K-A5/K-A4/K-A6 与 K-A7 期 1/2/3 全部落地，K-A2 取消，`dawn/tool` 已退出 jar 与可信底座（`b66f1d7`）；K-A8.1/K-A8.2 把帧 oracle 装回来并升到 major 52（§5.10、§5.11），K-A8.3 把 52 买回来的接口静态方法登成语料与门禁（§5.12）——K-A 刀表至此全部结清。 |
| [std-pruning-design.md](std-pruning-design.md) | current | 按程序裁剪 std：一次可达性走图，两个后端的 emit 边界上按模块 + 按函数裁；根是用户模块与发射器直呼的十个 `std/pvec` 名字，`--stdlib` 与无 target 两条全留；顺手把字典副本的归属从「先遇到的」改成确定性的最小 owner（issue #69）。check 与 lowering 一字未动，所以 Core golden 不动。 |
| [perceus-design.md](perceus-design.md) | current | native 的内存管理（精确 RC + 复用分析）。五刀已全部落地，关账在其 §8；仍是该子系统的权威说明。 |
| [slab-residency-design.md](slab-residency-design.md) | **current** | #10 的 measurement-first 调研与落地：把 lexer 小活集的 RSS 拆成 eager 64 KiB layout、空 current、每类 empty cache、rounding 与 `madvise` 五份；以 lexer/compiler/持久红黑树矩阵裁定 fresh slab 按 32 KiB 增量 materialize，保留 hot path、empty cache 与退役策略。 |
| [native-loop-control-design.md](native-loop-control-design.md) | current | native RC 的 `unloop` 只拆 match 一次性循环，保留仍被源码 `break`/`continue` 指向的循环与 C 标签。 |
| [range-bound-order-design.md](range-bound-order-design.md) | current | SEM-18 的 range `for` 边界求值顺序、共享 Core 修复与 compiling mutant 契约。 |
| [for-pattern-design.md](for-pattern-design.md) | current | SYN-13 的定稿：`for` 复用完整不可反驳 pattern、隐藏 loop locals、空 alternative 的 token recovery、限定 constructor completion、Core placement 与 28 条独立负控。 |
| [compiler-weight-baseline-design.md](compiler-weight-baseline-design.md) | current | #230 的严格重量基线与 dependency re-exec 堆继承：Phase 1 固定 release 产物、递归进程树 RSS、逐角色堆与 VAS、启动时间和 JSON schema，Phase 2 让子编译器继承父 JVM 的实际最大堆并由真实 `jcmd` 负控固定。 |
| [effects-soundness-design.md](effects-soundness-design.md) | historical | #188 的修法：具名效果的两个 soundness 缺陷（标签轴对函数值不设防、减标签的人不是应答的人）与「B 极简」三刀（注解位禁标签、闭包创建点结算、`verify_effects` 整行核对）。三刀里的前两刀已被 2026-08 的 V1′ 证据包路线翻转，本文是**翻转前**的设计记录；缺陷仍已修好，当前权威在 spec.md §6。 |
| [effect-params-design.md](effect-params-design.md) | current | RX-10-B（效果参数）的范围与决策点，**五刀全部落地**（刀 5 于 2026-08-20 收官）。三件载荷里 `effect Yield[T]` 判为出局（另一根轴，另立任务）；枢纽决策 5「效果参数被实例化时谁供证据」裁为 A0 + A″（规则丙：行里每个关联效果投影恰好一格擦除证据，调用点供给；A0：trait/impl 方法的行可带普通效果变量），拼写按十门语言的跨语言调研从 A′ 的 trait 参数表改为 A″ 的关联效果（trait 体内 `effect E` + impl 体内绑定 `effect E = !X` + 行里投影 `!C.E`），四个机制问题已裁定并各带重开条件。刀 5 的落地记录与三处实测偏离在刀 5 节末尾。 |
| [never-return-design.md](never-return-design.md) | current | SEM-14 已裁决方案的实现记录：return-only `Never` 的语义边界、JVM bottom call 终止 seam 与验证矩阵。 |
| [native-failure-design.md](native-failure-design.md) | current | #193 的修法：native 失败运行时的三个 P1（ARC-03 消息截断 / ARC-04 嵌套覆盖 / ARC-05 恢复泄漏）实测是**两件事**——载荷所有权与「longjmp 不跑清理」。刀 1 载荷对象化 + 路线 A3（`-fexceptions` + cleanup + ForcedUnwind）；路线 B（Result ABI）不做，重开条件写在 §4.3。载荷契约随刀 2 进 spec.md §9.8.1。 |
| [dom-bridge-design.md](dom-bridge-design.md) | current | UI DSL 第 4 层的边界：wasm reactor（`dawnc build --target wasm --reactor`）+ 纯消息传递 + 不用 `externref`，以及 `packages/tea-dom` 作为 `tea_core` 调和器的第二个消费者。记下契约对 DOM 缺的两件事（带 key 的子节点配对、住在终端包里的 `diff_step`）与 wasi-sdk 钉在 34 的实测理由。 |
| [tea-block-children-design.md](tea-block-children-design.md) | **current** | 视图 DSL 的子节点该不该由尾块发出（类 Compose 形状）。三条路线各自的墙：效果发出法卡在收集型 handler 在尾恢复档不可表达、效果不带类型参数、效果变量上装不了 handler（十二个探针的实测答复逐条在册）；块产生列表法过不了语法歧义那道线；停在列表的得失。用户 2026-08-29 逐条终裁（§8）：路线二关档、handler 局部状态立项归效果系统、参数化效果缓裁比价、验收认转写不变为必要条件加直驱腿。 |
| [handler-state-design.md](handler-state-design.md) | current | handler 局部状态：臂如何在两次操作调用之间攒东西。两个客户（lexer 诊断收集、视图 DSL 子节点收集）由用户 2026-08-29 立项，同日五问全裁（§8）。勘察结论 D.0：尾恢复档里两次 raise 之间唯一共享的对象是每次安装的 `ev$E` 记录，而语言今天没有可观察的可变堆对象，所以任何设计都先买同一个格子原语（照 `ev_get` 的内部 intrinsic 体例，不进 builtin 镜像）。**裁的是 handler 域 `var` 加一条强制逃逸禁令**（格子被闭包捕获是编译错误、不能作为值传出词法域），参数化 handler 关档：它在尾恢复档里只剩一个退化形，而那个形制逐字等于 Eff 2015 年删掉的 resource。`?` 早退按 local state interpretation 丢状态，重入按「尾恢复档下臂够不着自己这次安装」条文化。拼写终裁 = 格子写在 handler 花括号内、臂之前（Effekt 的邻接 `var` 形因归属判不出来被否）。刀 A（格子原语，两后端加运行时）、刀 B（语法）、刀 C（检查器语义：作用域、读写改写成 cell intrinsic、逃逸禁令）已落地。动刀前那条证据逃逸疑点已结案（§7.6，evidence 没有第二出口，判决性探针 P-E3 证明证据由调用点供给、不随闭包走）；§7.7 的兜底守卫三选一裁为 (c)（不兜底：证据要第二道网是因为它不可拼写、语料够不着，格子可拼写且已有 golden 诊断加负控）；`cell_take` 的适用条件在 §7.8 收窄成三条（必须在本次安装的臂里、出现恰好一次、不在 lambda 或循环下），三条各有负控。三路跨语言勘察（Koka / Effekt / OCaml 5 / Unison / Eff / Links）在 §10，十条探针在 §9，三处被实测推翻的旧勘察各带补注。 |
| [named-args-design.md](named-args-design.md) | current | #207 的方案：具名实参推广到 `Sig` 支持的 callee + 默认参数（合成 `f$default$k` 零元纯函数）。四条用户终裁在其 §9：实参求值顺序改**写序**（本批唯一 Emit-Change）、单层名、默认值任意纯表达式、std 采用另批。 |
| [tail-block-design.md](tail-block-design.md) | current | #206 的方案：裸 `{ ... }` 尾块（Kotlin 式，含 `{ x => }` 参数头）落到既有 `attach_trailing`，区分机制 = 头部禁记录字面量的开关扩义（`ns`→`nb`）。用户终裁在其 §13：方案乙、guard 位不禁；期 2 的最终口径是 `fn` 不再属于表达式，尾块是唯一 trailing form。 |
| [match-arm-separators-design.md](match-arm-separators-design.md) | current | SYN-10 的定稿：match 臂只由物理换行或逗号分隔，尾逗号合法；删除 FIRST(pattern) 邻接，并以三类 delimiter-aware recovery 与绝对 grammar corpus 固定边界。 |
| [int-min-literal-design.md](int-min-literal-design.md) | current | SYN-08 的定稿：三进制共用无溢出 magnitude parser，仅直接一元负号消费精确 `2^63` marker；双后端与生成 C 契约固定 `INT64_MIN`。 |
| [lsp-framing-design.md](lsp-framing-design.md) | current | TOOL-07 的定稿：共享层在 stdin read 前限制 8 KiB header/64 MiB body，严格解析重复 `Content-Length`，并把不可重同步的 framing failure 固定为一次错误后关读循环。 |
| [source-plan-design.md](source-plan-design.md) | current | TOOL-10 的定稿及 2026-08-09 架构修订：独立无 Java 的 `compiler-plan/` 先形成唯一最终图，再从选中 `PkgR` 收 Java 坐标。 |
| [lsp-workspace-design.md](lsp-workspace-design.md) | current | TOOL-05/06 的已实现设计：canonical `(project, source_root)` workspace、captured `ProjectPlan`、共享 `Program`/诊断与 target-scoped `JsigLease`。 |
| [playground-lsp-design.md](playground-lsp-design.md) | current | #11 的已落地设计：一个 browser buffer 对一个隔离 native LSP process；stdlib Python 窄 gateway、严格 wire/lifecycle/admission 与 fallback；v0.70 WSL2 100-run 开发证据已记录，生产 cgroup 仍须上线前复测。 |
| [public-surface-design.md](public-surface-design.md) | current | SEM-07 的定稿设计：World/StdOnly/Module audience、opaque nominal args、exporter-side surface validator、精确诊断与 doc/LSP 消费边界。阶段一、二已落地（§十五 记实现现状、`EffectRef` 临时 fallback 与两条无见证者的分支），doc/LSP 过滤是阶段三。 |
| [atomic-write-design.md](atomic-write-design.md) | current | TOOL-13 的定稿：manifest/lock 的 same-directory 原子写。宿主能力两件新增（`io_temp_file` 独占创建、`io_copy_permissions` 不跟随链接的权限搬运），算法在 `std/io.atomic_write_file`（stage → read-back → 权限 → 单次 rename，失败一律清理且原文件不动）。symlink fail-closed、hardlink detach，不承诺持久性、不做 CAS。**调用点迁移被种子纪律推到下一轮**，理由在其末节。 |
| [delete-outcome-design.md](delete-outcome-design.md) | current | LIB-07 的定稿：`io.delete` 以 `Deleted` / `NotFound` / `Err` 区分成功、缺失与 host refusal，底层仍保留 Bool intrinsic ABI。 |
| [cli-arity-design.md](cli-arity-design.md) | current | TOOL-04 的定稿契约：`check`/`fmt` 为 1..N，`test`/`doc` 的 selector 互斥，`build`/`emitc` 恰一个 target；两端保留独立 argv parser，由绝对 exit/stdout/stderr oracle 防止共谋假绿。 |
| [run-argv-boundary-design.md](run-argv-boundary-design.md) | current | TOOL-03 的定稿契约：`run` 只在 target 前解析 compiler option，以 `--` 开启逐字透传的 program argv；JVM 一次顺序解析且 dependency re-exec 保留原始 rest，两端独立 parser 由绝对 oracle 约束。 |
| [std-audit.md](std-audit.md) | current | std 的交付方式、优雅性判据与欠账台账（S5）。骨架五条已做掉大半，仍在册的欠账逐条写在它的状态行里。 |
| [stdlib-impl-notes.md](stdlib-impl-notes.md) | current | std 里几个函数**为什么长成这样**：被否掉的写法、实测数字、逼出今天形状的两后端分歧。std 的 `##` 注释只留契约，这些话从那里搬来。 |

## 旧审查设计材料（`docs/audit/`）

2026-07-25 全仓审查衍生的方案、裁决与复审记录。下表只登记路径、覆盖、材料类型和
破坏性边界；设计任务结果读各文档文件头与正文，当前 finding 状态只读
[审查 v2 总纲](codebase-audit-v2.md)。历史依赖见 [audit/README.md](audit/README.md)，
与 native 计划的边界见 [audit/native-plan-overlap.md](audit/native-plan-overlap.md)。

| 文档 | 覆盖 | 材料类型 | 破坏性边界 |
|---|---|---|---|
| [audit/web-api-v2-design.md](audit/web-api-v2-design.md) | WEB-03/04/06/07/09/10 | API 设计 | 是（packages/web 代际迁移） |
| [audit/lsp-robustness-design.md](audit/lsp-robustness-design.md) | LSP-01/02/04 | 鲁棒性设计与负控记录 | 否 |
| [audit/nominal-types-design.md](audit/nominal-types-design.md) | LANG-04/05 | nominal/Char 方案与裁决记录 | 是（字面量与公开类型边界） |
| [audit/module-access-design.md](audit/module-access-design.md) | LANG-06/07 | 模块访问设计 | 否（语法与能力放宽） |
| [audit/package-integrity-design.md](audit/package-integrity-design.md) | PKG-02/04 | cache/lock 完整性设计 | 否 |
| [audit/application-syntax-design.md](audit/application-syntax-design.md) | SYN-02/03 | application 语法设计 | 否（语法放宽） |
| [audit/purity-boundary-design.md](audit/purity-boundary-design.md) | LANG-01 P0 + ARCH-06 | purity boundary 设计 | 是（语言能力收窄） |
| [audit/error-model-design.md](audit/error-model-design.md) | ERR-02/03 + LANG-02 | 错误模型设计 | 是（公开错误与 cast API） |
| [audit/lowered-ir-design.md](audit/lowered-ir-design.md) | ARCH-01/02/03/04 | Core IR 补充材料 | 否（发射输出保持不变） |
| [audit/ceval-trampoline-verdict.md](audit/ceval-trampoline-verdict.md) | purity boundary 的 comptime 栈方案 | 收益重估与裁决记录 | 否 |
| [audit/re-audit-2026-07-30.md](audit/re-audit-2026-07-30.md) | RP/RX/RC/RD 共 53 条 | 第二轮复审记录 | 否（只读审查） |
| [audit/re-audit-b-decisions.md](audit/re-audit-b-decisions.md) | 复审 B 批八条契约件 | 裁决记录 | 依各契约件 |

## 特性设计与实现理由

| 文档 | 生命周期 | 说明 |
|---|---|---|
| [bytes-design.md](bytes-design.md) | historical | 一等 `Bytes`（M7 序 4）的动码前设计；权威条文在 spec §9.5.1。 |
| [cast-interop.md](cast-interop.md) | historical | 把 `as_XXX` 家族收敛成一个泛型 `cast` 的设计。失败行为已被 LANG-02 改成 `Result[T, ForeignError]`，文中相关各处已就地订正。 |
| [pure-ffi-design.md](pure-ffi-design.md) | historical | `unsafe_pure` 与 builtin→stdlib 迁移的地基，四个阶段于 2026-07-22 关账。 |
| [sourceview-design.md](sourceview-design.md) | historical | 切片器收敛：内部位置货币整体换成码点索引，UTF-16 只在 LSP 出线边界由 `SourceView` 重建。 |
| [streaming-design.md](streaming-design.md) | historical | 流式请求体（WebDAV PUT 恒定内存）的草案。 |
| [streaming-response-design.md](streaming-response-design.md) | historical | 流式响应（GET 代理下载恒定内存）的草案，上一篇 §六留的尾巴。 |
| [unwrap-design.md](unwrap-design.md) | historical | 互操作 Option 解包，后缀 `!`；权威条文在 spec §8.2。 |
| [varargs-design.md](varargs-design.md) | historical | 传可变实参；权威条文在 spec §9.3。 |
| [builtins-to-stdlib.md](builtins-to-stdlib.md) | historical | 「为什么有这么多 builtin」的回答与迁移路线。**文中的 builtin 计数别当现状**，这条曲线此后被 intrinsic 契约掉了头。 |
| [stdlib-naming.md](stdlib-naming.md) | historical | 平铺名破坏性重组为模块限定式（v0.4.0 双拼写、v0.5.0 删平铺名）；§五另记第二批改名的沿革。 |
| [trait-v2-design.md](trait-v2-design.md) | historical | 八刀，`==` 走 `Eq` bound；权威描述在 spec §3.5 与 trait.md。 |
| [semantics-closure-design.md](semantics-closure-design.md) | **current** | S1：把一件事的 N 份定义收成一份。§9 那张表的步 1–5 已落地，**步 6 只做了一半**；§10–§12 是这条线的尾款。 |
| [assoc-types-design.md](assoc-types-design.md) | **current** | `type Item` 与投影 `T.Item`，两刀均于 2026-08-02 落地；运算符 trait 的前置。 |
| [operator-traits-design.md](operator-traits-design.md) | historical | `[]` 背后的 `Index`，第六个 prelude trait；权威条文在 spec §4.8。 |
| [prelude-namespace-design.md](prelude-namespace-design.md) | historical | 函数命名空间的「一道门」与追加兼容性，三刀于 2026-08-02 完成。 |
| [effects-design.md](effects-design.md) | historical | 用户具名效果 + `with handle`，尾恢复档；权威条文在 spec §6.5，教程见 tutorial §17。 |
| [tile-backend-design.md](tile-backend-design.md) | current | 接 CUDA Tile IR 后端的立项设计：用户 2026-09-02 裁决分阶段路线（kernel 体是 `!Dev` 效果函数，宿主运行期记录成 Tile 程序）、第一里程碑 vadd f64 端到端、`std/narrow` 立即做、本机 GPU 对拍走台账门。刀 1 已落地：`std/gpu` 的 `Gpu` 效果、`Dtype`、幻影 `Tensor[D]` 与纯的假设备 `with_gpu_fake`。刀 2 已落地：`packages/tileir` 的 `Dev` 效果、`TileProg`、记录 handler 与 Tile IR 文本渲染器，`scripts/tile-golden` 两后端逐字节钉文本。刀 3 已落地：`lower` 指令表（渲染器与写入器共用）与 `bytecode` 字节码写入器，`scripts/tile-golden` 加字节码 golden 并由钉版本的 `tileiras` 编成 sm_86 cubin（层 1），CI 新 job `tile`。刀 5 已落地：`d_for / d_for2` 与索引算术、记录 handler 的区域栈（token 穿过循环携带值）、`For` 的降低 / 渲染 / 字节码区域编码，第二个 kernel `sum` 与 `std/gpu.sum_ref` 逐位同序；`d_if` 未做。刀 4 管线已落地：`RtGpu` 八个 intrinsic、原生运行时 `dlopen libcuda`、JVM 拒绝类、`with_gpu_real`、`scripts/tile-gpu-diff` 对拍脚本与台账、CI 台账门；GPU 对拍本身待驱动（本机 560.94 在 `cuModuleLoadData` 被 `CUDA_ERROR_INVALID_IMAGE` 拦住，台账第一行如实记录）。刀 6 已落地：`gpu.BF16` 标记与 `Tensor[BF16]`、`std/narrow` 的 bf16 位模式编解码、宿主 `Bytes` 打包（两个 `Bytes` 版 intrinsic）、假设备按缓冲格式舍入并把格式交给参考实现、`vadd_bf16` kernel 的文本 / 字节码 golden 与 cubin、对拍脚本的 bf16 语料；六刀全部落地，层 2 待驱动。**刀 7a 到刀 13 也已落地，正文（尤其 §6.2 三层门、§6.6 两档判词、§7 刀序表）是它们的权威记录**：边界与 mask、归约与超越函数、二维 tile 与 `mmaf`、任意 stride 的指针梯子、整数 tile 与 i32 缓冲、宿主加宽（多输出 / 原地 / f16 / i8 / u8 与 `ftof`、`mmai`）、gather / scatter（数据相关索引，**零新 opcode**：`offset` 的偏移操作数换成一个从缓冲里读出来的 i32 tile）、`scan`（0x5E，前缀扫描，多一个 `reverse` 属性；三条设备实测写在 §6.6：区域的第一个参数是累加器而不是元素、identity 不参与第一个位置的折叠、**浮点前缀和不是顺序左折叠因而只有容差档**）；层 2 已在本机 3080 上跑通，62 个 kernel 与 52 道 leetgpu 题在台账里，层 2 的变异体 20 条。CI 的 `tile` job 按 `scripts/tile-golden/matrix.txt`（62 个 kernel 加 13 个变异体一张表）分成 `tile-golden-1 / tile-golden-2` 两个 round-robin 分片，并集由 `mutant-shards-complete` 兜住，见 §6.5。 |
| [oneshot-design.md](oneshot-design.md) | current | 一次性恢复（one-shot resumption）的**勘察结账**：四路勘察给出本仓第一批实测数字（JVM `Continuation` 70–460 ns、native 影子栈税 15%/5%/2–4%、传染面 1.45%），排除全栈复制/侧栈/wasm 非 CPS 三条路线，路线为 yield 冒泡；2026-08-31 用户立项，§9 六问全裁毕，施工中。 |
| [core-move2-design.md](core-move2-design.md) | historical | Move 2 的结账与 `CSProtect` 关档。 |
| [arch-split-design.md](arch-split-design.md) | historical | ARCH-01 拆 `Cx` + ARCH-02 拆 `Gen`，**取代 lowered-ir-design.md §3.2 的六组件方案**。这一块里唯一仍值得整篇读的，理由见下。 |

生命周期以每篇自己的文件头为准，上表由 `doc-check.py` 逐篇与它对账。表里 historical
的那些：写作当时的取舍成立，文中的行数、性能数字和「现在是什么样」的描述**不保证仍然
准确**。特性本身的权威描述在 spec.md。

**上表最后一行的「仍值得读」是什么意思**：[arch-split-design.md](arch-split-design.md)
（2026-08-03 十二刀落地）不只是「为什么这么拆」，还是一份**怎么在没有行为门禁的
地方证明重构是恒等变换**的作业记录：归一化全量 Core 不变量、五语料逐字节对拍、
以及 §5.4 那条「我们以为有门禁看着、实测两个都看不见」的自我更正。
下一次动编译器大结构之前读它的 §5 与 §10。

## 调研

| 文档 | 说明 |
|---|---|
| [seq6-research.md](seq6-research.md) | 字符串/序列性能，`Cursor` 的由来。CONTRIBUTING 拿它当「调研推翻原前提也是成果」的范例。 |
| [equality-survey.md](equality-survey.md) | 七门语言怎么设计相等。结论已由 trait v2 兑现（`==` 走 `Eq` bound）。 |
| [collections-dejava-research.md](collections-dejava-research.md) | 集合去 Java 化的 A/B/C 三案，推荐 C。**已落地**（S3，2026-07-27）：三个容器都是纯 Dawn。 |
| [llvm-backend-research.md](llvm-backend-research.md) | 第二后端**的调研**，读作历史——那个后端已经建成并自举了（native，Core IR → C，`scripts/native-fixpoint.sh` 验 B==C）。现状与计划看 [native-backend-plan.md](native-backend-plan.md)。 |

## 历史：里程碑与自举过程

[design.md](design.md)（M0–M4 的决策记录；**「实现语言 = Kotlin」等条目已过期**，见文首状态标注）·
[design.en.md](design.en.md)（上面那篇的英文译本，中文是正本）·
[selfhost-gaps.md](selfhost-gaps.md) ·
[selfhost-ast.md](selfhost-ast.md) ·
[selfhost-checker.md](selfhost-checker.md) ·
[selfhost-codegen.md](selfhost-codegen.md) ·
[m6.md](history/m6.md) ·
[m6-retro.md](history/m6-retro.md) ·
[m7-progress.md](history/m7-progress.md) ·
[m8-selfhost-only.md](history/m8-selfhost-only.md)（淘汰 Kotlin 实现的决策与落地）

这一层全部 historical。指向 `compiler/` 的链接已改为 `kotlin-final` tag 上的
GitHub URL——那套实现不在 main。

---

## DOC-10 的三件事：都已落地

1. ✅ 分类索引（本文）。
2. ✅ 每篇自带状态——**换了形状落地**：不是 YAML front matter（站点渲染器会把它当正文
   印出来），而是 H1 下面一行 `> 状态：…`，由 `scripts/doc-check.py` 的 status 检查强制。
   「适用版本」只有 spec.md 需要，它带 `<!-- doc-check: version -->` 标记，版本号从
   `selfhost/src/version.dawn` 读，不由人抄。
3. ✅ 里程碑记录已在 `docs/history/`（m6 / m6-retro / m7-progress / m8-selfhost-only）。

一条经验留在这儿：**状态行会烂，而且是成批地烂**——写文档的人落地后改正文、很少回头
改文件头那一行。2026-08-04 全目录过了一遍，改掉的多数不是「写错了」，是「写对过」。
所以凡是能交给机器的都交出去了（篇数、索引覆盖、状态行的存在、版本号），
剩下「状态行说的是不是真话」没有机器能判，只能靠下一次人工复核。

---

## 这些文档是被检查的（TEST-04）

`scripts/doc-check.py`（CI 门禁「documentation checks」）检查这些：

- **状态**：每篇 `docs/` 下的文档在开头 12 行内有一行 `> 状态：…`（三档 + proposed，见上；
  英文文档写 `> Status: …`）。
  只查这一行**在不在**，查不了它**是不是真的**——假装能查会比这个缺口更糟。
- **链接**：每条相对链接指向真实存在的文件。
- **锚点**：每个 `#片段`（同文件与跨文件都算）对得上目标文档里的某个标题。
- **章节**：每个写明了目标文档的 `§N` 交叉引用，对得上那份文档里一个编号标题。
- **版本**：每处关于**当前工具链版本**的断言等于 `selfhost/src/version.dawn`。
- **篇数与覆盖**：本文开头那个「N 篇文档」等于 `docs/` 的真实篇数，且**每篇都被本文链到**。
  新写一份文档不进索引，门禁就红。
- **代码块**：每个标注为 ```` ```dawn run ```` / ```` ```dawn compile ```` 的块真的编得过、跑得起来。
- **围栏**：教程里每个 ```` ```dawn ```` 块标明自己是三种中的哪一种，每处豁免写明理由。
- **站点程序**：网站发布的每个整程序跑得起来，且输出与旁边记着的那份逐字节相同
  （`site/pages/` 与 `site/play-ui/samples/`，`*.dawn` 对 `*.out`）。
- **译本**：每篇译文登记了它所译原文的摘要，该摘要仍是原文当前的，且两边的代码围栏一一对齐。

块检查是 opt-in 的：规范里多数示例是片段（一个类型声明、三行 match），
逼它们都变成整模块会毁掉行文。**正确性重要的示例请自己标上** `run` 或 `compile`。
