# Dawn 代码库审查 v2：编译器与运行时架构

> 状态：**current** —— checker、Core/comptime、JVM/C 后端与 native runtime 的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- Core IR、checker split 与两个独立后端都是真实进展；“没有 lowered IR”“大文件就继续拆”应撤回。
- 当前主要风险已经从物理文件大小转为**阶段契约没有类型化**：裸名字构依赖图、平行 List 靠下标对齐、稳定 identity 与临时 ID 共用全局计数器、内部 panic 被用户错误通道吞掉。
- native failure runtime 是当前最集中的后端语义债：固定 512 字节全局 payload、nested bracket overwrite 与 longjmp 引用泄漏互相关联，应作为一项 runtime redesign 处理。

## ARC-01 — P1 — 返回类型推断把局部名字当顶层依赖

- **证据：V。** `name_refs` 记录所有 `EVar` 和 method name，却不维护 lambda 参数、函数参数、pattern/local binding scope：`selfhost/src/check/checker.dawn:2210`、`:2214`、`:2227`、`:2301`。结果只按字符串与待推断顶层函数名相交：`selfhost/src/check/checker.dawn:7330`。
- **最小复现：** `fn a(b: Int) = b` 与 `fn b() = a(1)`。参数 `b` 被当作对顶层 `b` 的边，而顶层 `b` 真依赖 `a`，两者都在 `selfhost/src/check/checker.dawn:7362` 被报 mutually recursive。
- **影响：** 合法、实际无递归的程序被拒；local fn、pattern binding 和同名 method 都能制造伪边。
- **建议：** 依赖遍历维护 lexical binding set；更稳妥的是先做轻量 name resolution，以 symbol ID 构图。不要继续用裸字符串模拟 call graph。

## ARC-02 — P1 — JVM classfile 硬边界变成无源码位置的内部异常

- **证据：S。** Core String 直接进入 `visitLdcInsn`：`selfhost/src/jvm/emit.dawn:1344`；模块函数集中写进单一 class：`selfhost/src/jvm/emit.dawn:1389`、`:1445`；最终 `toByteArray` 结果只经 `expect("bytes")`：`selfhost/src/jvm/emit.dawn:1792`、`selfhost/src/jvm/help.dawn:37`。
- **边界：** 超过 classfile `CONSTANT_Utf8` 65,535 bytes 的 literal、超 64 KiB Code 的 method、常量池过大或模块 class 过大，都可能让 ASM 抛异常。
- **影响：** 语法/类型合法的源程序以 compiler/ASM stack trace 结束，而不是指向 literal/function/module 的诊断。仓库在 `docs/std-audit.md:91` 已知道 String 限制，但未把它变成通用发射边界。
- **建议：** 长字符串分块重建；method/class finalize 捕获并分类 size exception；lowered function 保留 source origin。长期再考虑 outlining 或 module class 分片。

## ARC-03 — P1 — native 捕获失败会把消息截成 512 字节

- **证据：K。** `DAWN_FAILURE_MAX` 固定 512，raise 只复制 min(length, 512)：`runtime/c/dawn_rt.c:773`、`:798`；`ForeignError.message` 从该 buffer 构造：`runtime/c/dawn_rt.c:829`。注释明确承认 bracket 后 fatal message 也会截断：`runtime/c/dawn_rt.c:866`。
- **冲突：** 规范称 `ForeignError.message` 是失败自己的 message：`docs/spec.md:1521`，并保证 bracket 的 kind/message 逐字不变：`docs/spec.md:1565`。JVM 保存并重抛原 Throwable：`selfhost/src/jvm/rtclasses.dawn:931`。
- **影响：** 两后端对合法长消息不同；截断点可落在 UTF-8 code point 中部，native 还可能产生不满足 Dawn String invariant 的文本。
- **门禁缺口：** `scripts/native-cli-diff.sh:377` 刻意把测试消息控制在 512 bytes 以下，并把更长输入记为“真实分歧”。
- **建议：** failure payload 动态拥有完整 bytes；不要以全局固定 buffer 作为异常对象替代品。

## ARC-04 — P1 — native 全局 failure payload 会被 nested release 覆盖

- **证据：S；未动态验证。** `dawn_failure_buf`、length、kind 与 panic bit 都是 process-global：`runtime/c/dawn_rt.c:768`、`:773`、`:780`、`:789`；handler frame 只保存 `jmp_buf/prev/catches_panic`：`runtime/c/dawn_rt.c:762`。
- **边界：** bracket 的 use 产生外层 failure；unwind path 先 pop bracket handler，再执行 release：`runtime/c/dawn_rt.c:913`。若 release 内部用 `catch_panic` 捕获另一个 failure，后者会覆盖全局 payload；release 正常返回后 `dawn_reraise`：`runtime/c/dawn_rt.c:871` 重抛的是内层 payload，而不是原 failure。
- **后端差异：** JVM bracket 把原 Throwable 留在 local，并在 release 后重抛同一个对象：`selfhost/src/jvm/rtclasses.dawn:931`。
- **影响：** kind/message 可被 cleanup 中已处理的错误替换，违反 bracket contract；它与线程安全无关，即使单线程也成立。
- **建议：** 每个 handler/failure 拥有独立、动态大小 payload；bracket 捕获后持有原 payload，release 的 nested handler 不能改写它。

## ARC-05 — P1 — native 被捕获的 failure 会泄漏丢弃帧中的引用

- **证据：K。** `longjmp` 直接丢弃 C frames：`runtime/c/dawn_rt.c:798`；bracket 注释明确承认 use reference 丢失：`runtime/c/dawn_rt.c:899`。`docs/perceus-design.md:449` 也把 taken barrier leak 作为设计例外。
- harness 对带 `.leaks-on-catch` 标记的程序关闭 LeakSanitizer：`scripts/spike-native/run.sh:45`、`:211`。目前 catch/bracket/io 等多个语料依赖该豁免。
- **影响：** `catch_fault`/`catch_panic` 本来用于服务器 request、runner isolation 等可重复路径；每次恢复都可能永久泄漏该动态范围持有的 String/ADT/closure。
- **建议：** Core lowering 生成 cleanup landing pads/显式 unwind stack，或把可恢复 failure 改为显式 Result ABI。至少不能以全局关闭 LSan 作为长期 contract。

## ARC-06 — P2 — comptime 把 lowering invariant panic 伪装成用户拒绝

- **证据：S。** comptime 对 `lower_fn_only` / `lower_expr_only` 使用无差别 `catch_panic`：`selfhost/src/ir/interp.dawn:369`、`:379`、`:1563`。lowering 同时包含真正的阶段 invariant panic，例如缺 witness、`XError` 穿透、constructor field 缺失：`selfhost/src/ir/lower.dawn:2072`、`:2430`、`:2760`。
- **影响：** checker→lower regression 会变成“cannot evaluate at compile time”一类用户诊断，隐藏 compiler bug，也可能让只期待某条诊断的负例假绿。
- **建议：** 预期拒绝用 `Result[..., LowerRefusal]`；只转换该 variant。阶段不变量失败继续作为内部错误并保留上下文。

## ARC-07 — P2 — 阶段产物靠平行 List 的位置对齐

- **证据：S。** impl registration 返回与 AST 二维 List 位置对齐的 signatures：`selfhost/src/check/passes.dawn:1382`；checker 直接索引 `impl_sigs[ii]`/`msigs[mi]` 并重新解析 trait/subject：`selfhost/src/check/checker.dawn:7402`、`:7405`、`:7414`。
- JVM emitter 同时接收 `TModule` 与 `LMod`，先按 `fi` 取 `lm.fns[fi]`，之后才比较 name：`selfhost/src/jvm/emit.dawn:1324`、`:1390`、`:1394`。`docs/arch-split-design.md:748` 也记录了该边界。
- **影响：** error recovery、filter、reorder 或独立阶段测试只要造成长度偏差，就先 OOB；API 类型不能表达“这是该 declaration 的产物”。
- **建议：** 使用 `RegisteredImpl`、`CheckedImplMethod`、`LoweredFn { source_meta, core, lifts }` 等具名产品；短期至少先检查长度/name 并报 compiler invariant。

## ARC-08 — P2 — 返回推断调度与回填至少二次复杂度

- **证据：S。** pending functions 每轮全表扫描：`selfhost/src/check/checker.dawn:7337`；逆拓扑依赖链可每轮只完成一个。每完成一项又用 `take ++ [x] ++ drop` 重建 `sealed` 与 `tfuns`：`selfhost/src/check/checker.dawn:7352`；`take/drop` 会遍历复制：`std/list.dawn:195`、`:201`。
- **影响：** 顶层函数数 F 时，单回填已经 O(F²)；generated code、超大 module 与未来 incremental check 会首先暴露。
- **建议：** indegree queue/SCC 一次调度，按 declaration index 写入 mutable builder/array，最后一次组装 immutable list。

## ARC-09 — P2 — 一个全局 `next_id` 混合稳定身份与临时身份

- **证据：S。** `Cx.next_id` 同时分配 type var、ADT、effect、trait、local symbol：`selfhost/src/check/cx.dawn:87`、`:313`，以及 `selfhost/src/check/passes.dawn:44`、`:633`、`:1003`、`:1112`、`selfhost/src/check/checker.dawn:109`。
- 计数器跨模块传递：`selfhost/src/driver/analyze.dawn:1023`、`:1044`、`:1065`；ID 又进入 type key 与 generated symbol：`selfhost/src/ir/core.dawn:349`、`selfhost/src/ir/lower.dawn:735`、`selfhost/src/c/emitc.dawn:1160`。
- **影响：** 前一模块多一个 local/type variable，会让后续 nominal ID 与 C symbol 大面积漂移，扩大 cache invalidation 与无语义 golden diff。
- **建议：** 拆成 `NominalId/TraitId/EffectId/SymId/TyVarId/TempId`；nominal 按 module declaration 稳定分配，temporary 限在 function/module。

## ARC-10 — P2 — 512 MB 栈被当作通用递归策略

- **性质：K/D。** launcher 默认 `-Xss512m`：`bin/dawn:61`；编译器 spawn 的用户程序也固定同值：`selfhost/src/main.dawn:949`；native runtime 把每个 Dawn entry 放在 `DAWN_STACK_BYTES` thread：`runtime/c/dawn_rt.h:373`、`runtime/c/dawn_rt.c:69`。
- 现有裁决正确指出“只 trampoline comptime”不能摘掉它：`docs/audit/ceval-trampoline-verdict.md:245`；因此本项不是复活旧方案。
- **影响：** 地址空间受限环境难以启动；native executable 强制 pthread 与大 virtual stack，降低 embedding/容器适配；真正 stack exhaustion 仍可能是 silent crash，只是阈值被推远。
- **建议：** 分阶段削减：parser/checker 对抗性 recursion 先改 iterative，运行期一般 tail call/关键 std recursion 再处理；把 stack size 变为有上限的可配置策略并记录实际 high-water，而非永久 ABI 常量。

## ARC-11 — P3 — comptime 诊断只剩外层 initializer span

- **证据：S。** Core 不保留 source positions：`selfhost/src/ir/interp.dawn:19`；内部 error 先以 `(0,0)` 建立：`selfhost/src/ir/interp.dawn:180`，最终统一覆盖为 const/comptime block span：`selfhost/src/ir/interp.dawn:1588`。
- **影响：** 复杂 const 调用 shared helper 时，用户只知道整个 initializer 失败，没有 callee/callsite trace。“块很小”不是语法约束。
- **建议：** 用紧凑 `OriginId` 边表，不必把 full Span 塞进每个 Core node；interpreter frame 保存 function 与 callsite，输出短 comptime trace。

## ARC-12 — P3 — lowering cache 只活一个 comptime expression

- **证据：S。** `ESt` 持有 lowered function/dictionary cache：`selfhost/src/ir/interp.dawn:75`，但每个 `fold_expr` 都 `fresh_st` 清空：`selfhost/src/ir/interp.dawn:1552`、`:1560`；module const 各自调用：`selfhost/src/ir/interp.dawn:1790`。
- **影响：** 多个 const 调同一 helper 时重复 lowering 与 lambda lifting；comptime 使用增长后形成无必要编译时间。
- **建议：** 拆 module-level `LowerCache` 与 per-evaluation fuel/env/depth；lifted-lambda identity 使用稳定 key。
