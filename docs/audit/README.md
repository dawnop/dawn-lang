# 审查待办：设计文档索引与修复顺序

> 状态：**current**。这是 2026-07-25 那次全仓审查（[../codebase-audit.md](../codebase-audit.md)）
> 剩下的 28 条待办的作业计划。审查本身已经处置了 40 条、驳回 8 条。
>
> 本文回答两个问题：**每条待办的方案在哪份文档里**，以及**按什么顺序做**。
> 每份设计文档都是 proposed 状态——按 CONTRIBUTING.md 第一条，动码前先写下来，
> 因为写下来会杀死一批方案，而在编辑器里杀死方案比在 4000 行 diff 之后便宜。

## 一、八份设计文档

| 文档 | 覆盖 | 破坏性 | 大小 |
|---|---|---|---|
| [purity-boundary-design.md](purity-boundary-design.md) | **LANG-01(P0)** ARCH-06 | 是（语言收窄） | 大 |
| [lowered-ir-design.md](lowered-ir-design.md) | ARCH-04 ARCH-01 ARCH-02 ARCH-03 | 否（输出必须逐字节不变） | **最大** |
| [error-model-design.md](error-model-design.md) | ERR-02 ERR-03 LANG-02 | 是 | 大 |
| [application-syntax-design.md](application-syntax-design.md) | SYN-02 SYN-03 | 否（语法放宽） | 中 |
| [nominal-types-design.md](nominal-types-design.md) | LANG-04 LANG-05 | 部分（`'a'` 变 `Char` 时） | 中 |
| [module-access-design.md](module-access-design.md) | LANG-06 LANG-07 | 否 | 小 |
| [lsp-robustness-design.md](lsp-robustness-design.md) | LSP-01 LSP-02 LSP-04 | 否 | 小 |
| [package-integrity-design.md](package-integrity-design.md) | PKG-02 PKG-04 | 否 | 中 |
| [web-api-v2-design.md](web-api-v2-design.md) | WEB-03/04/06/07/09/10 | **是**（packages/web 2.0） | 中 |

**不需要设计文档的四条**，直接做（见 §三·第 0 批）：
TEST-01（classfile 过 CheckClassAdapter）、TEST-04（文档 CI）、
DOC-10 剩余（front matter + `docs/history/`）、REL-02（`Emit-Change` 绑定 target）。

**被另一条线覆盖的三条**：BOOT-01(P0)、TEST-02、ARCH-05 的前两条建议——
去 Java 化改造（[../collections-dejava-research.md](../collections-dejava-research.md) 方案 C）
做的就是这件事，碰同一批文件。**不要并行动它们。**

## 二、依赖关系

```
第 0 批（无依赖，随时做）
  TEST-01  TEST-04  DOC-10  REL-02  module-access  lsp-robustness  package-integrity
                                    application-syntax   nominal-types(1-3)

第 1 批（P0，独立）
  purity-boundary 步骤1 ──► 步骤2 ──► 步骤3（trampoline）──► 摘 -Xss512m

第 2 批（长线，是 3 的前提）
  lowered-ir A→B→C→D ──► 拆 Cx(ARCH-01) ──► 拆 Gen(ARCH-02)
                     └──► ARCH-03 第二后端变得可能

第 3 批（依赖 2）
  error-model C2（bracket intrinsic 要发 finally 块，与 emit 改造同区）

独立发布节奏
  web-api-v2（packages/web 2.0，跨仓契约）
```

只有三条真依赖：

- **`lowered-ir` 必须在 `拆 Cx` / `拆 Gen` 之前**。反了要做两遍——
  拆完 checker，emit 仍然直连 TAST，耦合只是换了个地方。
- **`error-model` 的 C2（`bracket` intrinsic）在 `lowered-ir` 阶段 C 之后**。
  A（`JavaError`）与 B（`cast` 返回 Result）不受影响，可以先做。
- **`purity-boundary` 的三步内部有序**，但整条线与其它都无关。

其余全部可以并行。

## 三、建议顺序

### 第 0 批：先把便宜的做掉（1–2 周）

按「收益 ÷ 成本」排，第一条尤其划算：

1. **TEST-01：classfile 过 ASM `CheckClassAdapter`**。emit 时多包一层，
   在**发射阶段**就抓住非法字节码，而不是等 JVM verifier 在运行期拒绝。
   审查列的五个外部 oracle 里最便宜的一个。
2. **WEB-09 的 RouteTable 启动校验**（[web-api-v2](web-api-v2-design.md) §六·步 0）。
   不破坏 API，可以脱离 v2 单独发。把「宽 route 静默遮住后续 route」
   变成启动即失败。
3. **[module-access](module-access-design.md)**：`m.T`/`m.C`/`m.CONST` 是纯放宽，
   `--closure` 是新增开关。整份文档零破坏性。
4. **[lsp-robustness](lsp-robustness-design.md)**：URI/UTF-8 换 JDK + debounce。
   注意先给 `selfhost-lsp-diff.sh` 语料加畸形用例**记录旧行为**，再改。
5. **[package-integrity](package-integrity-design.md)**：cache 每次校验 + `dawn lock`。
   材料（d1 hash）已经有了。
6. **DOC-10 剩余 + REL-02 + TEST-04**：文档 front matter、`docs/history/`、
   `Emit-Change` 绑定 target 与 digest、文档 CI。
   TEST-04 有个直接论据——本次审查处置里，README 首页示例的插值语法是错的、
   tutorial 的安装命令不可执行、EBNF 多处不符，**全部由人读出来，没有任何测试发现**。

### 第 1 批：P0 的那条（并行于第 0 批）

7. **[purity-boundary](purity-boundary-design.md) 步骤 1**：`unsafe_pure` 收归 std。
   改动本身很小（`Cx.is_std_module` 已经存在），成本在**跨仓扫描 + 发 tag**。
   先扫 dawnop-site 确认没有用户代码在用。
8. **步骤 2**：comptime 的 Java 调用改 allowlist。纯收窄，不破坏语言表面。
9. **步骤 3**：`ceval` trampoline 化，然后摘 `-Xss512m`。
   摘参数单独一个提交、单独一条 release note——它会让用户程序里原本能跑的深递归
   开始 `StackOverflowError`，而 ERR-01 刚把那个从 `catch_panic` 里移出去。

> 步骤 1 之后 LANG-01 这条 P0 就不再是「用户可达的不健全逃生门」了。
> 2、3 是纵深防御，不必急。

### 第 2 批：长线（与 0/1 并行启动，但慢）

10. **[lowered-ir](lowered-ir-design.md) 阶段 A–D**。整个改造的验收是
    **输出逐字节不变**——`selfhost-prev-diff.sh` 零差异，**不接受 `Emit-Change:` 豁免**。
    这次改造的定义就是「结构变、输出不变」，出现差异说明 lower 改了语义，是 bug。
11. **拆 `Cx`（ARCH-01）**，一次一个组件，每次跑全量 + 差分。
12. **拆 `Gen`（ARCH-02）**。

### 第 3 批：依赖前面的

13. **[error-model](error-model-design.md) A（`JavaError`）+ B（`cast`）**——
    其实不依赖 IR，可以提前到第 0 批之后。放这里是因为两者都是破坏性变更，
    与 `purity-boundary` 步骤 1 挤在同一个发布窗口不划算。
14. **error-model C2（`bracket` intrinsic）**——要在 codegen 发 finally 块，
    必须等 lowered-ir 阶段 C 之后。
15. **[application-syntax](application-syntax-design.md)**、
    **[nominal-types](nominal-types-design.md)**。两者都改 parser/checker，
    与拆 `Cx` 撞车，排在 ARCH-01 之后省一次冲突。
    （nominal-types 的步骤 1–3 是纯新增，急的话可以提前。）

### 独立节奏：`packages/web` 2.0

16. **[web-api-v2](web-api-v2-design.md)**。它不与编译器改造争资源，
    但它是**跨仓契约**（CONTRIBUTING §六）：这边先发 tag，dawnop-site 再 bump。
    找一个那边有空迁移的窗口做。

## 四、发布纪律速查

写在这里是因为这批待办里踩到的地方特别多：

| 情况 | 要做什么 |
|---|---|
| 改变工具链输出的字节（报错文案、格式化、CLI 文本、发射的字节码、jar） | 提交信息加 `Emit-Change: <说明>` |
| 语言收窄 / 破坏性 API | **先发 tag**，dawnop-site 再提 bump `.dawn-version` |
| `lowered-ir` 的任何一步 | **不允许** `Emit-Change:`——差异即 bug |
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
- **只改 EBNF 不改实现**——短期止血已做（标 historical），
  但长期选它等于承认「函数是一等值」这句话有星号。
- **保留手写 UTF-8 decoder 作为 fallback**——留着就得维护，
  而它的全部价值是「JDK 不在」，JDK 一定在。

## 六、一句话建议

**如果只挑一件继续做，挑第 0 批的第 1 条**（classfile 过 `CheckClassAdapter`），
不是任何一条架构重构。

理由在 [../codebase-audit.md](../codebase-audit.md) §14：这次修的三个 JSON bug
全都是在全绿的差分体系下长期存在的——**差分验证的是「一致」，不是「正确」**。
唯一抓住它们的是外部 oracle 和性质测试。那一层现在只有 JSON 有。
