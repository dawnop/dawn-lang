# 审查待办：设计文档索引与修复顺序

> 状态：**current**。这是 2026-07-25 那次全仓审查（[../codebase-audit.md](../codebase-audit.md)）
> 剩下的 28 条待办的作业计划。审查本身已经处置了 40 条、驳回 8 条。
>
> **2026-07-30 合并与解冻**：分支于当日选择性合入 main（合并提交 `fa2a85f`，
> 逐条对着已前进 30+ 提交的主线重判——保留仍成立的、按今日形状重实现的、
> 丢弃被取代的，明细见该提交信息）。同日 §二/§三所等的三个信号**全部到期**：
> Phase 0（Core IR）早已落地、R6 已决（interp 吃 Core）、**Phase 6 当日出口**
> （native fixpoint B==C，`../native-backend-plan.md` §14.23）。第 3 批全部解冻；
> 第 0 批第 1 条 REL-02 已做（`scripts/emitchange.sh`，声明格式
> `Emit-Change(<label glob>): ...`，裸声明保持通配兼容）。
> purity-boundary 步骤 2 所修的洞已被缝 2（CtOpts.jcall 默认拒绝 + --comptime-ffi
> 闸）覆盖大半，重判后再动。
>
> 本文回答两个问题：**每条待办的方案在哪份文档里**，以及**按什么顺序做**。
> 每份设计文档都是 proposed 状态——按 CONTRIBUTING.md 第一条，动码前先写下来，
> 因为写下来会杀死一批方案，而在编辑器里杀死方案比在 4000 行 diff 之后便宜。

> **动手前先读 [native-plan-overlap.md](native-plan-overlap.md)。**
> [`../native-backend-plan.md`](../native-backend-plan.md)（07-25 在 main 上定稿）
> 与本目录是**独立写出来的两条线**，有九处撞车。那份台账逐条记了谁让位、
> 谁冻结、谁要改写。本文的排期已经按它调整过：**不重合的先做，重合的冻结。**

> **2026-07-30 第二轮复审**：[re-audit-2026-07-30.md](re-audit-2026-07-30.md) ——
> 结构/语法/纯洁性三维度 53 条新发现（与本目录零重复，6 条标注为已追踪项的新侧面），
> 高危论断已逐条独立复核。含 triage：立即可做的正确性小刀 / 待裁决契约件 /
> 并入已立项任务的侧面 / 独立排期的结构清理 / 等窗口的破坏性变更。

## 一、十份设计文档 + 一份台账

| 文档 | 覆盖 | 破坏性 | 状态 |
|---|---|---|---|
| [re-audit-2026-07-30.md](re-audit-2026-07-30.md) | 第二轮复审：RP/RX/RC/RD 共 53 条 | 分级见其 §六 | **current（发现记录）** |
| [native-plan-overlap.md](native-plan-overlap.md) | 撞车登记（台账，非方案） | — | current |
| [purity-boundary-design.md](purity-boundary-design.md) | **LANG-01(P0)** ARCH-06 | 是（语言收窄） | 步 1–2 已落地／**步 3 不做** |
| [ceval-trampoline-verdict.md](ceval-trampoline-verdict.md) | purity-boundary 步 3 的收益重估（裁决，非方案） | — | **current（不做，07-31）** |
| [lowered-ir-design.md](lowered-ir-design.md) | ARCH-04 ARCH-01 ARCH-02 ARCH-03 | 否（输出必须逐字节不变） | **整篇降级为补充材料**——§3.2/§3.3 的 `Cx`/`Gen` 方案已被 [../arch-split-design.md](../arch-split-design.md) 复测取代 |
| [../arch-split-design.md](../arch-split-design.md) | **ARCH-01 ARCH-02**（任务 #88） | 否（发射字节必须逐字节不变） | **已落地**（2026-08-03，十二刀，`4ae6b61`→`94109b7`，见该文 §10）｜余账 **#126** |
| [error-model-design.md](error-model-design.md) | ERR-02 ERR-03 LANG-02 | 是 | A、B 已落地／**C2 不做**（07-31 关档） |
| [application-syntax-design.md](application-syntax-design.md) | SYN-02 SYN-03 | 否（语法放宽） | **已落地**（2026-07-30 加法 + 07-31 统一） |
| [nominal-types-design.md](nominal-types-design.md) | LANG-04 LANG-05 | 部分 | 步 1–3 可做／**步 4 冻结** |
| [module-access-design.md](module-access-design.md) | LANG-06 LANG-07 | 否 | **可做**（不重合） |
| [lsp-robustness-design.md](lsp-robustness-design.md) | LSP-01 LSP-02 LSP-04 | 否 | **可做**（理由已改，见台账 §3.7） |
| [package-integrity-design.md](package-integrity-design.md) | PKG-02 PKG-04 | 否 | **可做**，PKG-02 优先 |
| [web-api-v2-design.md](web-api-v2-design.md) | WEB-03/04/06/07/09/10 | **是**（packages/web 2.0） | **可做**（native 计划 §7 明确划到范围外） |

**不需要设计文档的四条**，直接做（见 §三·第 0 批）：
TEST-01（classfile 过 CheckClassAdapter）、TEST-04（文档 CI）、
DOC-10 剩余（front matter + `docs/history/`）、REL-02（`Emit-Change` 绑定 target）。

**已让位给 native 那条线的五条**：ARCH-03、ARCH-04、BOOT-01(P0)、TEST-02、
ARCH-05 的前两条建议。台账 §二。**不要并行动它们。**

## 二、依赖关系

```
第 0 批（不重合，随时做）
  REL-02*  TEST-01  TEST-04  DOC-10
  module-access   lsp-robustness   package-integrity(PKG-02→PKG-04)
  application-syntax   nominal-types(步1-3)   web-api-v2 步0

第 1 批（P0，不重合的那两步）
  purity-boundary 步骤1（unsafe_pure 收归 std）──► 步骤2（comptime allowlist）
                                                    步骤3 ✗ 不做（07-31 裁决）

第 2 批（破坏性，各自发窗口）
  error-model A（ForeignError）──► B（cast 返回 Result）
                                    C2（LProtect/CSProtect）✗ 不做（07-31 关档）
  web-api-v2 步 1–6（packages/web 2.0，跨仓契约）

第 3 批（等 native 那条线）
  Phase 0 落地 ──┬► ARCH-01（拆 Cx）  ┐ ✓ 已落地 08-03（两条 lane 并行跑完）
                 └► ARCH-02（拆 Gen） ┘   余账 #126（恢复路径的诊断语料）
  R6 决议    ──► purity-boundary 步骤 3 ✗ 不做，-Xss512m 留着（ceval-trampoline-verdict）
  Phase 6    ──► nominal-types 步骤 4（'a' 变 Char，与纯 Dawn 化合并做）

* REL-02 从「可以立刻做」升为**前置**：两后端平权之后，
  `Emit-Change:` 不标 target 就说不清改的是谁的输出（台账 §3.8）。
```

真依赖只剩两条（原来的三条里，「lowered-ir 必须在拆 Cx 之前」这条现在由
native 计划的 Phase 0 承担）：

- **`purity-boundary` 的三步内部有序**；步骤 3 已裁决为不做
  （[ceval-trampoline-verdict.md](ceval-trampoline-verdict.md)），不再是依赖。
- **`error-model` A → B**（B 用 A 的错误类型），C2 额外等 Phase 0。

其余全部可以并行。

## 三、建议顺序

### 第 0 批：不重合的、便宜的，全部先做（1–2 周）

按「收益 ÷ 成本」排：

1. **REL-02：`Emit-Change` 绑定 target 与 digest**。原本排在最后，
   现在提到最前——native 计划 R4 明说「两个后端平权 ⇒ 每次 Emit-Change 要验两套」。
   这行字现在没有 target 字段。**在第二个后端出现之前改，比之后改便宜得多。**
2. **TEST-01：classfile 过 ASM `CheckClassAdapter`**。emit 时多包一层，
   在**发射阶段**就抓住非法字节码，而不是等 JVM verifier 在运行期拒绝。
   审查列的五个外部 oracle 里最便宜的一个。native 计划 §5 采纳了 TEST-01 的
   **论证**（差分会把旧 bug 固化成正确行为），但没有采纳这个**动作项**。
3. **WEB-09 的 RouteTable 启动校验**（[web-api-v2](web-api-v2-design.md) §六·步 0）。
   不破坏 API，可以脱离 v2 单独发。把「宽 route 静默遮住后续 route」
   变成启动即失败。
4. **[module-access](module-access-design.md)**：`m.T`/`m.C`/`m.CONST` 是纯放宽，
   `--closure` 是新增开关。整份文档零破坏性、零重合。
5. **[lsp-robustness](lsp-robustness-design.md)**：URI/UTF-8 换 JDK + debounce。
   注意先给 `selfhost-lsp-diff.sh` 语料加畸形用例**记录旧行为**，再改。
6. **[package-integrity](package-integrity-design.md) §2.1**：cache 每次校验 +
   `dawn cache verify`。材料（d1 hash）已经有了，且这一半在 native 上
   **是唯一的完整性手段**。§2.2 的 `dawn.lock` 排在它后面（JVM 专属）。
7. **[application-syntax](application-syntax-design.md)** 与
   **[nominal-types](nominal-types-design.md) 步骤 1–3**。两者都改 parser/checker，
   零破坏性。nominal-types 步 1–3 落地后 LANG-05 就有答案可写进 spec §2.6，
   不必等步骤 4。
8. **DOC-10 剩余 + TEST-04**：文档 front matter、`docs/history/`、文档 CI。
   TEST-04 有个直接论据——本次审查处置里，README 首页示例的插值语法是错的、
   tutorial 的安装命令不可执行、EBNF 多处不符，**全部由人读出来，没有任何测试发现**。
   （native 那条线还在往 `docs/` 加文档，DOC-10 越晚做越贵。）

### 第 1 批：P0 的那条，做能做的两步（并行于第 0 批）

9. **[purity-boundary](purity-boundary-design.md) 步骤 1**：`unsafe_pure` 收归 std。
   改动本身很小（`Cx.is_std_module` 已经存在），成本在**跨仓扫描 + 发 tag**。
   先扫 dawnop-site 确认没有用户代码在用。
10. **步骤 2**：comptime 的 Java 调用改 allowlist。纯收窄，不破坏语言表面。
    （这张表在 native 上会自然消失——`use c` 没有反射。落地时在注释里写明。）

> 步骤 1 之后 LANG-01 这条 P0 就不再是「用户可达的不健全逃生门」了。
> 步骤 2 是纵深防御。**步骤 3 冻结**——它是 ARCH-06，不是 LANG-01。

### 第 2 批：破坏性变更，各自找发布窗口

11. **[error-model](error-model-design.md) A（`ForeignError`）+ B（`cast`）**。
    两者都是破坏性变更，与 `purity-boundary` 步骤 1 挤在同一个发布窗口不划算，
    所以排在它之后。**注意 A 的类型定义从第一天就不能带 JVM 类名**（台账 §3.3）。
12. **[web-api-v2](web-api-v2-design.md) 步 1–6**（`packages/web` 2.0）。
    它不与编译器改造争资源，native 计划 §7 也把 web 划到范围外，
    但它是**跨仓契约**（CONTRIBUTING §六）：这边先发 tag，dawnop-site 再 bump。
    找一个那边有空迁移的窗口做。

### 第 3 批：曾经等 native 那条线的三个信号

**三个信号已于 2026-07-30 全部到期，本批解冻**（见本文头部）。下表留着是为了记住
每条当初等的是什么、以及等到之后各自的结局：

| 待办 | 等什么 | 等到之后 |
|---|---|---|
| ~~**ARCH-01 拆 `Cx` / ARCH-02 拆 `Gen`**~~ | ~~Phase 0（Core IR）出口~~ **已到，前提解除** | **已结账 08-03：做完了**（#88，十二刀 `4ae6b61`→`94109b7`）。checker 11,308→8,203、codegen 3,425→706、emit 2,534→2,309，新增 `cx`/`passes`/`rtclasses`/`jvmhelp`；`Cx` 47→40+`Frame`(8)、`Gen` 21→12+`GenCtx`(8)。零 `Emit-Change`、五语料 465 个 class 逐字节零差异。**「两条 lane 并行」（D12）经实测成立**：全程唯一的交界是 `main.dawn` 的两行 `use`。落地结果与被推翻的预测见 [../arch-split-design.md](../arch-split-design.md) §10；**余账 #126** |
| ~~**error-model C2（`LProtect`）**~~ | ~~Phase 0~~ | **已结账 07-31：不做**——`bracket` 改以运行时 intrinsic 落地（v0.39.0），冻结时「codegen intrinsic 会把 bracket 绑死在 JVM 上」的论证在 `catch_fault` 之后不成立。见 [../core-move2-design.md](../core-move2-design.md) §2.6 与该文头部落地记 |
| ~~**purity-boundary 步骤 3（trampoline）**~~ | ~~**R6 决议**~~ | **已结账 07-31：不做**——重估后收益不成立，见 [ceval-trampoline-verdict.md](ceval-trampoline-verdict.md) |
| **nominal-types 步骤 4（`'a'` 变 `Char`）** | Phase 6 排期 | **合并成一次改**，且 `Char` 先落 |

## 四、发布纪律速查

写在这里是因为这批待办里踩到的地方特别多：

| 情况 | 要做什么 |
|---|---|
| 改变工具链输出的字节（报错文案、格式化、CLI 文本、发射的字节码、jar） | 提交信息加 `Emit-Change: <说明>`；REL-02 落地后**还要标 target** |
| 语言收窄 / 破坏性 API | **先发 tag**，dawnop-site 再提 bump `.dawn-version` |
| native 计划的 Phase 0（Core IR） | **不允许** `Emit-Change:`——差异即 bug |
| 写进方案的性能断言 | 必须有实测出处（CONTRIBUTING §二） |
| 落地后 | 回填 `docs/m<N>-progress.md`（含提交哈希）；被现实推翻的前提回头改掉草案 |

## 五、这批文档里被记下来的「不做」

散在各文档的「不做的（记录理由）」一节，挑几条最容易被重新想起来的：

- **comptime 放进子进程**——步骤 1+2 之后威胁模型已经没了，
  而每次编译多一次 JVM 启动 + 全部 comptime 值跨进程序列化的代价没有实测。
- **SSA / 多层 IR**——`design.md` 拒绝 IR 的原论证里「多一层表示就多一层不变量」
  这半仍然成立；一层就够达成分层与可测性。
- **type-only cycle**——要把类型引用与值依赖拆成两张图，
  换来的是这个仓库还没遇到过的场景。
- **method/status 换成受限类型**——WebDAV 用 `PROPFIND`/`MKCOL`，
  status 是开放集合，封闭类型必然要 `Other(String)` 逃生口，等于回到 String。
- **给 `ForeignError.kind` 定跨后端的规范化取值**——那是在**猜**两套错误分类的
  对应关系，而猜错的地方正是调用方会依赖的地方。
- **保留手写 UTF-8 decoder 作为 fallback**——理由已改：native 上会另起一份，
  不是把这个不校验的留着。

## 六、一句话建议

**如果只挑一件继续做，挑第 0 批的第 1 条**（`Emit-Change` 绑定 target），
不是任何一条架构重构，也不再是 TEST-01。

理由变了：原来的第一名是 classfile 过 `CheckClassAdapter`，论据在
[../codebase-audit.md](../codebase-audit.md) §14——这次修的三个 JSON bug
全都是在全绿的差分体系下长期存在的，**差分验证的是「一致」，不是「正确」**。
那条论据仍然成立，TEST-01 仍然排第二。

但 REL-02 现在有一条更硬的时间性论据：native 计划一旦走到 Phase 3，
仓库里就有两套输出，而 `Emit-Change:` 这行字说不清改的是哪一套。
**这类格式改动在只有一个后端的时候是几十行，在有两个之后是一次迁移。**
