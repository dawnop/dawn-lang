# Dawn 代码库审查 v2：编译器与运行时架构

> 状态：**current** —— checker、Core/comptime、JVM/C 后端与 native runtime 的详细审查。

返回[总纲](../codebase-audit-v2.md)。证据等级见[方法说明](00-methodology-and-retractions.md)。

## 本专题结论

- Core IR、checker split 与两个独立后端都是真实进展；“没有 lowered IR”“大文件就继续拆”应撤回。
- 当前主要风险已经从物理文件大小转为**阶段契约没有类型化**：裸名字构依赖图、平行 List 靠下标对齐、稳定 identity 与临时 ID 共用全局计数器、内部 panic 被用户错误通道吞掉。
- native failure runtime 的三项 P1 已由 #193 收口；`ARC-12` 也已由模块级 `LowerCache`
  收口，`ARC-13` 也已关闭 native RC 错删源码循环目标的问题。当前结构债转为
  `ARC-01/02/11` 的 partial 边界，以及 `ARC-07/08` 的 typed-product / stable-origin 前置。

## ARC-01 — P1 — 返回类型推断把局部名字当顶层依赖

<!-- audit-anchor: present selfhost/src/check/checker.dawn | pub fn name_refs -->

> **后续处置（2026-08-09）：partial。** `RefScope` 现已排除参数、lambda、pattern/local
> binding 与 module alias，原最小参数重名反例关闭；但非 module receiver 的
> `EMethod(target, name, ...)` 仍无条件把裸 `name` 记为本模块函数边：
> `selfhost/src/check/checker.dawn:2326`、`:2330`。真实成员若与待推断顶层函数同名，仍可制造
> 伪循环；只有 symbol-resolution edge 才能完整关闭本项。

- **证据：V。** `name_refs` 记录所有 `EVar` 和 method name，却不维护 lambda 参数、函数参数、pattern/local binding scope：`selfhost/src/check/checker.dawn:2210`、`:2214`、`:2227`、`:2301`。结果只按字符串与待推断顶层函数名相交：`selfhost/src/check/checker.dawn:7330`。
- **最小复现：** `fn a(b: Int) = b` 与 `fn b() = a(1)`。参数 `b` 被当作对顶层 `b` 的边，而顶层 `b` 真依赖 `a`，两者都在 `selfhost/src/check/checker.dawn:7362` 被报 mutually recursive。
- **影响：** 合法、实际无递归的程序被拒；local fn、pattern binding 和同名 method 都能制造伪边。
- **建议：** 依赖遍历维护 lexical binding set；更稳妥的是先做轻量 name resolution，以 symbol ID 构图。不要继续用裸字符串模拟 call graph。

> **二次处置（2026-08-16）：仍是 partial，但残余边界已收窄到一句话可写清。**
> `RefScope` 加第三张集合 `javas`，`EMethod` 臂对**零元 `ECtor` 且名字是 Java 类**的
> receiver 不再记边。判据是照 `check_method_call` 的 Java 静态分派臂**逐条镜像**写的，
> 包括那两个原勘察漏掉的条件：receiver 名字必须不在 `ctors_by_name`、不在 `consts`。
> 这一条是承重的而非形式主义：`use java "java.lang.Integer"` 与本地一个叫 `Integer` 的
> 构造器今天可以共存，而构造器赢分派，所以 `Integer.tag()` 是**真边**，摘掉它才是把这个
> 单边过近似摘向有害的一侧。（`consts` 那半实际不可达，常量强制 SCREAMING_SNAKE_CASE 撞不上
> Java 类名；保留只为镜像分派臂，没有测试声称它。）
>
> **修复前的最小复现确实被误拒**：`fn toHexString(n: Int) = Integer.toHexString(n)!` 报
> `cannot infer the return type of \`toHexString\`: it is recursive`，而同一文件写出
> `-> String !io` 就编过，证明程序合法。三个「别修过头」探针（被本模块顶层函数遮蔽的
> builtin 方法名、模块别名限定调用、真正的相互递归）改前改后行为一致。五个变异体逐个转红，
> 其中两个专钉上面那两个额外条件。
>
> **残余：只剩实例 Java receiver**（`TyJava`）。判它需要表达式的类型，而 `name_refs` 跑在
> pass 5 开头、任何函数体被 check 之前，这一层拿不到类型。**非 Java 模块今天已经触发不了
> 本项**：builtin/std/trait 方法名的边是真边（本模块同名顶层函数会全遮蔽 builtin，UFCS 一定
> 打到它），record 的 fn 类型字段本来就先报 ambiguous。
>
> **原建议的「以 symbol ID 构图」远超小刀，不要当小刀推：** 顶层函数今天根本没有 symbol ID
> （`cx.next_id` 铸的是 type var / ADT / effect / trait / **local** symbol，顶层函数一律以
> `String` 为键），要它就要新增一整个 name-resolution 阶段并在 AST 上回填，直接压在
> `ARC-07/08/09` 那条被 HOLD 的线上。本项余下部分应随那批走。
>
> 顺带留一条实测：本次改动让 `check.checker` 之外另三个模块的 Core 也动了，但**全部是
> `structeq$AdtNNNNN` 的编号后缀统一偏移 14，零指令变化**。在干净基线上给 `checker.dawn`
> 追加一个五行空函数得到逐字节相同的漂移，故这不归因于本设计，是 `ARC-09` 共享计数器本身
> 的性质。`selfhost.norm.sha` 的噪声滤镜正是为分辨这两件事而存在的。

## ARC-02 — P1 — JVM classfile 硬边界变成无源码位置的内部异常

<!-- audit-anchor: present selfhost/src/jvm/codegen.dawn | class_bytes(finish: fn() -> Option[Bytes] !io, cls: String) -->

> **后续处置（2026-08-09）：partial。** `ldc_str` 已按 modified UTF-8 精确分块，class
> finalize 也把 ASM failure 转成可读 compiler failure；但 `LMod`/Core finalize 仍没有对应
> source span。超限 method/class 最多指出 class/ASM method 文本，不能定位源码函数，也没有
> outlining/分片，因此原发现的 source-actionable 边界仍开放。

- **证据：S。** Core String 直接进入 `visitLdcInsn`：`selfhost/src/jvm/emit.dawn:1344`；模块函数集中写进单一 class：`selfhost/src/jvm/emit.dawn:1389`、`:1445`；最终 `toByteArray` 结果只经 `expect("bytes")`：`selfhost/src/jvm/emit.dawn:1792`、`selfhost/src/jvm/help.dawn:37`。
- **边界：** 超过 classfile `CONSTANT_Utf8` 65,535 bytes 的 literal、超 64 KiB Code 的 method、常量池过大或模块 class 过大，都可能让 ASM 抛异常。
- **影响：** 语法/类型合法的源程序以 compiler/ASM stack trace 结束，而不是指向 literal/function/module 的诊断。仓库在 `docs/std-audit.md:91` 已知道 String 限制，但未把它变成通用发射边界。
- **建议：** 长字符串分块重建；method/class finalize 捕获并分类 size exception；lowered function 保留 source origin。长期再考虑 outlining 或 module class 分片。

> **二次处置（2026-08-16）：仍是 partial，但 method 超限那一支已经能定位到声明。**
> 做法不是给 Core 加 span，而是**从 ASM 的报错文本反查 AST 的 name-span**：`emit_module` 建一张
> 「实际写进 class 的 JVM method 名 → `(path, nlo, nhi, lifted)`」的表，失败时用
> `front/diag.render` 出带 `--> path:line:col` 和 caret 的标准诊断。表的键由**命名 method 的
> 那几个函数本身**生成（`impl_static_name` / `test_method_name` 等被抽出来共用），所以键与实际
> 发射名不可能格式漂移。覆盖：普通顶层 fn、impl 方法、trait default 体、`f$default$k`
> 合成默认值函数、test 体，以及 lifted lambda（借外层声明的 span 并在 hint 里说明借了）。
>
> **`class_bytes` 的签名刻意没动**，另开 `class_bytes_from` 由前者转发。理由不是迁就 anchor：
> 那些**对自己的方法说不出话**的调用方（dict / closure / SAM / ADT / trait 接口，以及全部 std
> 模块）本来就该继续用原来那个入口，转发让实现只有一份。
>
> **仍无位置的四类，逐条列明**：(a) std 模块整体，驱动层对它们既不留 path 也不留 AST；
> (b) `<clinit>` 超限（模块所有 const 合并进类初始化器，ASM 不点名任何 const，已用 40,000 元素
> 的 `const` 实测确认）；(c) JVM 入口包装 `main([Ljava/lang/String;)V`；(d) 上面那几类非模块 class。
> **另外 class 整体超限（常量池溢出）只打 `--> <path>` 而没有行列**，因为 ASM 的
> `Class too large` 不点名 method。**裸文件路径不算源码位置**：它把搜索范围缩到一个文件，
> 再往下就没有了，指向其中任何一个声明都是猜。本项因此仍是 partial。
>
> **原建议里「lowered function 保留 source origin」（给 `CFun` 加 origin）已判为不做，且不是
> 成本问题而是冲突问题：** `scripts/core-golden/selfhost.norm.sha` 存在的全部意义是「纯代码
> 移动时它一个字节都不动」，那是重构声称「只搬代码没改语义」时唯一可信的证据。今天全仓
> Core dump 里只有 3 处行号字面量（`e!` 展开的 panic 消息烘进去的字符串常量），脚本为这 3 处
> 专门写了一条正则滤镜并附了长篇说明。给 Core 节点普遍加行号就是把 3 处扩散到每个节点，滤镜
> 要么救不了、要么等于把 span 全滤掉。`native-backend-plan.md` 已有裁决：**保持 Core 无 span
> 是有意的**，等真正做调试信息行号表时再一次性加。所以那件事属于「JVM LineNumberTable」的
> 独立项，不该塞进本条。
>
> 顺带订正勘察一处：`codegen.dawn` 里那处「漏网的裸 `cw.toByteArray().expect("bytes")`」
> 不在生产路径上，它在一个 ASM interop 的 `test` 块里，把 spike 测试的 writer 接进错误报告器
> 什么也测不到。真正未接的生产调用在 `jvm/rtclasses.dawn` 与 `jvm/testrun.dawn`，都是尺寸不含
> 用户输入的固定形状运行时类。

## ARC-03 — P1 — native 捕获失败会把消息截成 512 字节

> **已修**（2026-08-08，#193 刀 1）：失败载荷改为失败自有的堆字符串（`dawn_failure`），
> `DAWN_FAILURE_MAX` 连同全局 buffer 一起删除；载荷契约进 `docs/spec.md` §9.8.1。
> 门禁：`scripts/spike-native/failure_message.dawn`（长度 0–5000 + UTF-8 跨界切点）、
> `native-cli-diff.sh` 的 650 字节消息腿。设计与路线裁决见
> `docs/native-failure-design.md`。以下为审计时的原文。

- **证据：K。** `DAWN_FAILURE_MAX` 固定 512，raise 只复制 min(length, 512)：`runtime/c/dawn_rt.c:773`、`:798`；`ForeignError.message` 从该 buffer 构造：`runtime/c/dawn_rt.c:829`。注释明确承认 bracket 后 fatal message 也会截断：`runtime/c/dawn_rt.c:866`。
- **冲突：** 规范称 `ForeignError.message` 是失败自己的 message：`docs/spec.md:1521`，并保证 bracket 的 kind/message 逐字不变：`docs/spec.md:1565`。JVM 保存并重抛原 Throwable：`selfhost/src/jvm/rtclasses.dawn:931`。
- **影响：** 两后端对合法长消息不同；截断点可落在 UTF-8 code point 中部，native 还可能产生不满足 Dawn String invariant 的文本。
- **门禁缺口：** `scripts/native-cli-diff.sh:377` 刻意把测试消息控制在 512 bytes 以下，并把更长输入记为“真实分歧”。
- **建议：** failure payload 动态拥有完整 bytes；不要以全局固定 buffer 作为异常对象替代品。

## ARC-04 — P1 — native 全局 failure payload 会被 nested release 覆盖

> **已修**（2026-08-08，#193 刀 1）：动态验证后比审计记的更重——kind 位翻转能让
> `catch_fault` 吞 panic、可恢复 fault 变 exit 1。修法：每个屏障落地时把在途载荷
> **搬进自己的帧**再跑任何用户代码，全局槽只在「raise 到下一次 setjmp 返回」这个
> 不跑用户代码的窗口内被占用。门禁：`scripts/spike-native/bracket_release_fails.dawn`
> （2×2 矩阵 + kind 翻转 barrier）、`bracket_release_fatal.dawn`（致命路径）。
> 以下为审计时的原文。

- **证据：S；未动态验证。** `dawn_failure_buf`、length、kind 与 panic bit 都是 process-global：`runtime/c/dawn_rt.c:768`、`:773`、`:780`、`:789`；handler frame 只保存 `jmp_buf/prev/catches_panic`：`runtime/c/dawn_rt.c:762`。
- **边界：** bracket 的 use 产生外层 failure；unwind path 先 pop bracket handler，再执行 release：`runtime/c/dawn_rt.c:913`。若 release 内部用 `catch_panic` 捕获另一个 failure，后者会覆盖全局 payload；release 正常返回后 `dawn_reraise`：`runtime/c/dawn_rt.c:871` 重抛的是内层 payload，而不是原 failure。
- **后端差异：** JVM bracket 把原 Throwable 留在 local，并在 release 后重抛同一个对象：`selfhost/src/jvm/rtclasses.dawn:931`。
- **影响：** kind/message 可被 cleanup 中已处理的错误替换，违反 bracket contract；它与线程安全无关，即使单线程也成立。
- **建议：** 每个 handler/failure 拥有独立、动态大小 payload；bracket 捕获后持有原 payload，release 的 nested handler 不能改写它。

## ARC-05 — P1 — native 被捕获的 failure 会泄漏丢弃帧中的引用

> **已修**（2026-08-08，#193 刀 3，路线 A3）：raise 改为 `_Unwind_ForcedUnwind`，
> 每个函数的 owned 槽位收进**一个**挂 cleanup 的 `dawn_own` 数组（每变量一个
> cleanup 属性是实测过的死路：EH region 按调用点×变量数爆炸，selfhost 驱动的
> cc 从 16s 到 354s；单数组收回到 27s，换来的运行期代价实测 fmt 场景 ~5%、
> emitc 场景 ~15%），RC pass 的每个释放点清槽、转移走 `dawn_take` 同表达式清槽；
> handler 帧以自身 cleanup 的指针身份收网（CFA 比较被 ASan fake stack 实测打破，
> 见设计文档 §4.1 落地注）。验收 = 三个 recover_* 语料 asan 转绿 + 全部
> `.leaks-on-catch` 豁免删除后 spike-native 全绿；负控两枚：去 `-fexceptions`
> 立刻响亮 abort，删一处清槽立刻 heap-use-after-free。以下为审计时的原文。

- **证据：K。** `longjmp` 直接丢弃 C frames：`runtime/c/dawn_rt.c:798`；bracket 注释明确承认 use reference 丢失：`runtime/c/dawn_rt.c:899`。`docs/perceus-design.md:449` 也把 taken barrier leak 作为设计例外。
- harness 对带 `.leaks-on-catch` 标记的程序关闭 LeakSanitizer：`scripts/spike-native/run.sh:45`、`:211`。目前 catch/bracket/io 等多个语料依赖该豁免。
- **影响：** `catch_fault`/`catch_panic` 本来用于服务器 request、runner isolation 等可重复路径；每次恢复都可能永久泄漏该动态范围持有的 String/ADT/closure。
- **建议：** Core lowering 生成 cleanup landing pads/显式 unwind stack，或把可恢复 failure 改为显式 Result ABI。至少不能以全局关闭 LSan 作为长期 contract。

## ARC-06 — P2 — comptime 把 lowering invariant panic 伪装成用户拒绝

> **已修**（2026-08-09）：`lower_into` 与 `fold_expr` 不再用 blanket
> `catch_panic` 包住 lowering；`XError` 等阶段不变量现在穿透为 compiler panic，预期的
> 用户拒绝继续由解释器的 `Result` / `cerr` 返回。修复同时清除了两个会让合法程序先
> 撞进 lowering panic 的邻接根因：用户空 impl 不再因 `provided == []` 被误判为
> primitive，而是生成并执行 `CDefault`；comptime 的 `ICx` 一次构建并携带
> `(owner, fn) -> Sig` 的 **direct-only** 表，传给 `lower_fn_only` /
> `lower_expr_only`。复查所有消费点后确认该表只服务无 `trait_id` 的 `XCallFn`
> （生成 `CDirect`）和 `std/hamt` direct 调用；`CImpl` / `CDefault` 的签名由
> `trait_method_sig` 与 `subst_subject` 从 trait/impl 表取得，函数体则由
> `(trait_id, subject_key, method)` 身份表取得，不能也不需要压进 `(owner, name)`。
> 为避免合法同名产生 last-wins，当前 `TModule` 的签名表、解释器 flat body 表与
> `owner_of` 都过滤 `impl_of` / `default_of`；std loader 的 `fn_decls` 和 `by_owner`
> 也经同一 `note_direct_fn` 入口只收普通 direct function，而每个 impl/default 仍经
> `note_trait_fn` 进入完整身份表。production invariant test 在真实 bundled std 上确认
> `fn_decls` 与每个 `by_owner` 表都不含 `impl_of` / `default_of`，并确认 std/list 确有
> impl bodies，避免空表假绿。补全签名后 Map/Set 本可继续进入 `std/hamt`，因此
> 解释器在执行该 `CDirect` 前固定返回
> `Map and Set operations are not available at comptime`，保持既有能力边界而不伪造
> folded value。门禁覆盖空 impl 默认方法折叠为 42 且 Core 为 `CDefault`、显式必需
> 方法与覆盖仍走 `CImpl`、Map 的表达式 lowering 与 Set helper 的函数 lowering、两条
> `XError` invariant 穿透，以及除零诊断逐字不变。追加的**解释器层身份夹具**由 checker
> 检查三个真实模块，但随后手工把三模块 direct/impl/default body tables 交给
> `eval_comptime`；它验证不同签名的同名函数在该层分别折叠为 42/7/9，Core 分别为
> `CDirect` / `CImpl` / `CDefault`，不代表 production driver 已能提供这些跨模块表。
> 把统一过滤器临时恢复成“所有 `TFun` 均插入”（即原全量 last-wins）后，该夹具立即在
> default 污染 direct owner 表的断言见红；另把 stdlib loader 的两处
> `note_direct_fn` 单独恢复为 `map.insert`，production invariant test 也会在真实 std impl
> 进入 `by_owner` 时见红。
>
> **剩余能力边界（未冒称已修）：**（1）production `driver/analyze` 对每个用户模块调用
> `eval_comptime` 时仍只传 std 的 `fn_decls` / `by_owner` / `impl_fns`，没有提供前序用户
> 模块的跨模块 direct、impl 或 default 函数体。因此真实三模块 const 当前不是 42/7/9：
> trait 路由会得到普通诊断“comptime: missing impl method `same`”；跨模块 direct helper
> 同样没有 body 可执行。（2）prelude primitive 的“编译器拥有”目前以
> `owner == None && src_path == None && provided == []` 代理；生产 checker 生成的用户
> impl 带 owner/path，但测试或未来阶段若合成一个 ownerless、underived、空 impl，仍可能
> 被误判，长期应有显式 provenance。（3）Map/Set 能力栅栏目前按整个 `std/hamt` owner
> 拒绝，而不是按具体操作/capability；若该模块未来加入可安全 comptime 的 direct helper，
> 也会被过度拒绝。这三项均是能力/模型债，不再被 lowering panic 隐藏，但不属于本项的
> invariant 错误通道修复。

- **历史证据（修复前基线，S）：** 基线代码曾在 comptime 的 `lower_into` 与
  `fold_expr` 边界用无差别 `catch_panic` 包住 `lower_fn_only` / `lower_expr_only`；同一
  lowering 阶段又包含缺 witness、`XError` 穿透、constructor field 缺失等真正的
  invariant panic。现代码已删除这两处 blanket catch，本段只记录 ARC-06 的发现来源，
  不表示当前实现仍存在该行为。
- **影响：** checker→lower regression 会变成“cannot evaluate at compile time”一类用户诊断，隐藏 compiler bug，也可能让只期待某条诊断的负例假绿。
- **建议：** 预期拒绝用 `Result[..., LowerRefusal]`；只转换该 variant。阶段不变量失败继续作为内部错误并保留上下文。

## ARC-07 — P2 — 阶段产物靠平行 List 的位置对齐

<!-- audit-anchor: present selfhost/src/check/checker.dawn | impl_sigs[ii] -->

- **证据：S。** impl registration 返回与 AST 二维 List 位置对齐的 signatures：`selfhost/src/check/passes.dawn:1382`；checker 直接索引 `impl_sigs[ii]`/`msigs[mi]` 并重新解析 trait/subject：`selfhost/src/check/checker.dawn:7402`、`:7405`、`:7414`。
- JVM emitter 同时接收 `TModule` 与 `LMod`，先按 `fi` 取 `lm.fns[fi]`，之后才比较 name：`selfhost/src/jvm/emit.dawn:1324`、`:1390`、`:1394`。`docs/arch-split-design.md:748` 也记录了该边界。
- **影响：** error recovery、filter、reorder 或独立阶段测试只要造成长度偏差，就先 OOB；API 类型不能表达“这是该 declaration 的产物”。
- **建议：** 使用 `RegisteredImpl`、`CheckedImplMethod`、`LoweredFn { source_meta, core, lifts }` 等具名产品；短期至少先检查长度/name 并报 compiler invariant。

- **订正（#196 分诊，2026-08-11 写回）。** 上面引了
  [`arch-split-design.md`](../arch-split-design.md) 对 `emit_module` 位置对齐的**边界描述**，
  漏引了紧接着的那条否决：该文同一节写着「`emit_module` 的 TModule/LMod 位置对齐不碰……
  非目标」，并顺手记下同一个 OOB「本批不修」，理由是按 Core 遍历会改方法进 class 的顺序，
  即 Emit-Change。所以本项**只有 checker 那半是活账**（`impl_sigs[ii]`/`msigs[mi]`，
  对应 #88 的余账「`pass_register_impls` 可拆块」）；emit 那半判不做，重开要先推翻上述非目标。

## ARC-08 — P2 — 返回推断调度与回填至少二次复杂度（部分修复）

<!-- audit-anchor: present selfhost/src/check/checker.dawn | var remaining: List[Int] = [] -->

- **证据：S。** pending functions 每轮全表扫描：`selfhost/src/check/checker.dawn:7337`；逆拓扑依赖链可每轮只完成一个。每完成一项又用 `take ++ [x] ++ drop` 重建 `sealed` 与 `tfuns`：`selfhost/src/check/checker.dawn:7352`；`take/drop` 会遍历复制：`std/list.dawn:195`、`:201`。
- **影响：** 顶层函数数 F 时，单回填已经 O(F²)；generated code、超大 module 与未来 incremental check 会首先暴露。
- **建议：** indegree queue/SCC 一次调度，按 declaration index 写入 mutable builder/array，最后一次组装 immutable list。

- **订正（#196 分诊，2026-08-11 写回）。** 上面**低估了**复杂度。`std/list.dawn` 的
  `slice_go` 每步 `acc ++ [..]`，而 `take` 与 `drop` 都建在它上面，所以两者各自就是 O(n²)；
  `take ++ [x] ++ drop` 的单次回填因而是 O(F²) 到 O(F³)，不是原文说的 O(F²)。
  另一条落地约束：**必须按 declaration index 写回**，否则取号顺序改变会触发与 `ARC-09`
  同款的全仓 ID 漂移。本项与 `ARC-01` 是同一段代码，同刀改最省。

> **后续处置（2026-08-17）：partial。回填那半已关，调度那半没动。**
> `check_module` 不再重建列表：推断出的 `TFun` 进一张按 declaration index 的
> `Map[Int, TFun]`，`tfuns` 由紧随其后的 annotated-body 循环**一次按声明序装配**；
> `sealed` 整个列表随之消失（`check_fn_inferred` 早已把封好的签名写进 `cx.fns`，
> 推断位从不进 `check_fn`，pending 里每个 index 最多完成一次，所以那张列表唯一被读回的
> 项就是未封的 `sigs`）。合成语料实测（F 个带标注顶层函数，`check`，同机交错 5 轮，
> 中位墙钟）：F=400 0.646→0.596s、800 0.744→0.668、1600 0.867→0.732、3200 1.386→0.878；
> 超出地板的增量 0.050/0.076/0.135/0.508，倍率 1.5/1.8/3.8 收敛到 4，即原文的二次项确实
> 存在且已消失。selfhost 自身量不到：最大 module 约 250 个函数，`check selfhost` 上单独
> 测这一刀是 +0.27% 墙钟、−0.06% CPU，都在噪声内（sd 2.7%/4.0%）——它是给生成代码买的保险，
> 不是今天的收益。
>
> **残余：调度仍是每轮全表扫描**（`while progress` 里 `for idx in pending`，逆拓扑链
> 可每轮只完成一项，P 项 pending 最坏 O(P²) 次 ready 判定）。原文建议的 indegree
> queue/SCC 一次调度没做，本项因此不是 fixed。

## ARC-09 — P2 — 一个全局 `next_id` 混合稳定身份与临时身份

<!-- audit-anchor: present selfhost/src/check/cx.dawn | next_id: Int -->

> **后续处置（2026-08-09）：open/HOLD。** 既有裁决不在尚无 incremental cache contract 时
> 为“更稳定的 golden”重排全部 ID；这会制造大面积无语义产物变化，却没有消费者能验证收益。
> 重开条件是增量检查、跨 expression cache 或持久 symbol identity 先提出稳定 key 契约；条件
> 未满足前不进入自治 TODO。

- **证据：S。** `Cx.next_id` 同时分配 type var、ADT、effect、trait、local symbol：`selfhost/src/check/cx.dawn:87`、`:313`，以及 `selfhost/src/check/passes.dawn:44`、`:633`、`:1003`、`:1112`、`selfhost/src/check/checker.dawn:109`。
- 计数器跨模块传递：`selfhost/src/driver/analyze.dawn:1023`、`:1044`、`:1065`；ID 又进入 type key 与 generated symbol：`selfhost/src/ir/core.dawn:349`、`selfhost/src/ir/lower.dawn:735`、`selfhost/src/c/emitc.dawn:1160`。
- **影响：** 前一模块多一个 local/type variable，会让后续 nominal ID 与 C symbol 大面积漂移，扩大 cache invalidation 与无语义 golden diff。
- **建议：** 拆成 `NominalId/TraitId/EffectId/SymId/TyVarId/TempId`；nominal 按 module declaration 稳定分配，temporary 限在 function/module。

- **判不做（#196 分诊，2026-08-11 写回）。** **三处成文否决**，v2 立项时都没有对账：
  `scripts/selfhost-core-diff.sh` 的 NORM 注释逐字写「Splitting the counter would rename
  every generated symbol in the language, a far larger Emit-Change than the noise it
  removes, so the answer is to name the noise rather than to stop making it」；
  [`arch-split-design.md`](../arch-split-design.md) 的 D8/§6.2 判 #122「不进这批」，理由是
  会毁掉 flat dump 那半边唯一完好的证明；[`operator-traits-design.md`](../operator-traits-design.md)
  §3.5 已把它单独立案为 `fix/next-id-past-prelude` 并说明「不该由刀 3 的账单吸收」。
  v2 新增的论据是「扩大 cache invalidation」，**但今天没有增量编译，这个收益是空的**。
  **重开条件：** 增量 check 立项。

## ARC-10 — P2 — 512 MB 栈被当作通用递归策略

<!-- audit-anchor: present bin/dawn | -Xss512m -->

> **后续处置（2026-08-09）：open/HOLD。** `ceval-trampoline-verdict` 已否决“只 trampoline
> comptime 就摘掉大栈”的旧方案；用户程序深递归、parser/checker 对抗输入、JVM/native entry
> 与失败方式必须一起裁。除非先有 measured high-water、默认栈/可配置上限与 recursion policy，
> 不单独下调 `-Xss`/`DAWN_STACK_BYTES`，也不放回自治 TODO。

- **性质：K/D。** launcher 默认 `-Xss512m`：`bin/dawn:61`；编译器 spawn 的用户程序也固定同值：`selfhost/src/main.dawn:949`；native runtime 把每个 Dawn entry 放在 `DAWN_STACK_BYTES` thread：`runtime/c/dawn_rt.h:373`、`runtime/c/dawn_rt.c:69`。
- 现有裁决正确指出“只 trampoline comptime”不能摘掉它：`docs/audit/ceval-trampoline-verdict.md:245`；因此本项不是复活旧方案。
- **影响：** 地址空间受限环境难以启动；native executable 强制 pthread 与大 virtual stack，降低 embedding/容器适配；真正 stack exhaustion 仍可能是 silent crash，只是阈值被推远。
- **建议：** 分阶段削减：parser/checker 对抗性 recursion 先改 iterative，运行期一般 tail call/关键 std recursion 再处理；把 stack size 变为有上限的可配置策略并记录实际 high-water，而非永久 ABI 常量。

- **判不做（#196 分诊，2026-08-11 写回）。** 事实成立，三条建议里两条撞裁决、一条已是
  事实：① 「分阶段削减，parser/checker 先改 iterative」撞
  [`ceval-trampoline-verdict.md`](../audit/ceval-trampoline-verdict.md) §七「**要做就在同一批里做**，
  单独摘掉其中一个，`-Xss` 一分不能少」，且实测 checker 每 MB 323 层比 ceval 的 159 更差，
  分阶段买不到任何下降；② 「运行期一般尾调」撞
  [`native-backend-plan.md`](../native-backend-plan.md) 的裁决，摘掉它是「语言退步，不是
  清债」；③ 「变为可配置」**已经是事实**（`bin/dawn` 的 `${DAWN_JVM_OPTS:-…}`）。唯一
  不冲突的「记录 high-water」也已在 `selfhost/src/ir/interp.dawn` 关账（写下 128m 实测
  分界并明写「Do not make it dynamic」）。**重开条件：** `ceval-trampoline-verdict.md` §七
  的三条，任一成立。

## ARC-11 — P3 — comptime 诊断只剩外层 initializer span（部分修复）

<!-- audit-anchor: absent selfhost/src/ir/core.dawn | OriginId -->

> **部分修复（2026-08-09，ARC-11A）：** 解释器内部不再过早构造、传递 `Diag`；私有
> `CtFailure` 分离保存 message、原始 actionable hint、调用帧、截断状态与可选粗 origin，
> 只在 `fold_expr` 对外边界一次转换为 `Diag`。`call_named`、`call_cfun`、动态函数值调用、
> `CImpl`、`CDefault` 与字典 default/bridge 的真实路径统一追加结构化 frame；direct/dynamic、
> impl/default 分种类渲染，owner、trait identity、subject 与 method 足以区分同名跨模块 helper。
> 原 hint 保持为第一段，调用链另以“innermost first”追加；空 hint 也能单独显示链。帧最多保留
> 最靠近失败点的 16 个，外层溢出只留下明确截断标记，深递归不会把诊断无界放大。此前 std
> 调用逐层覆盖 hint 的逻辑已删除，因此 fuel 与 `--comptime-ffi` 建议不会再被“raised inside
> standard library”替换。
>
> 门禁包括 selfhost 的 nested std/fuel、nested FFI、dynamic、impl/default、同名不同 owner 与
> 20 层调用链；`scripts/comptime-trace-contract/run.sh` 从真实 CLI 固定用户可见形状，并携带四个
> 活 mutation：恢复 `call_named` 覆盖 hint、分别漏掉 impl/default frame、取消 16 帧上限，均由
> 各自目标测试见红。
>
> **仍开放（ARC-11B）：** Core 仍无精确 source origin，最终主诊断位置仍是外围 const / comptime
> block；当前 frame 只有函数 identity，没有 callsite span，也没有正式的跨文件 related-location
> 协议。紧凑 `OriginId` / 边表与跨模块位置恢复须等 **ARC-07-JVM** 的 lowered-product 身份边界；
> 本切片没有预做。**ARC-12** 已经把跨 expression 的 lowering cache 收口，稳定 key 那一半
> 因此不再欠：同一 `(owner, fn)` 在一个模块里只有一份 lowered body，lifted lambda 也有
> 全模块唯一的名字，边表可以挂在这个身份上。仍然欠的是 `RC-03` 的 `fold_children`/`visit`
> 原语：Core 至今没有通用遍历器，`OriginId` 若现在动手，就是第七份手写全树遍历。

- **历史证据（修复前基线，S）：** Core 不保留 source positions；内部 error 曾直接以 `(0,0)`
  `Diag` 建立，最终统一覆盖为 const/comptime block span。复杂 const 调 shared helper 时，用户只
  能看到外围 initializer；std frame 还会覆盖真正可执行的 hint。
- **剩余影响：** 现在可见 callee identity 与有界调用链，但无法直接跳到失败子表达式或跨模块
  callsite；“块很小”仍不是语法约束。
- **后续建议：** 在 ARC-07-JVM / ARC-12 的稳定身份基础上增加紧凑 `OriginId` 边表；不要把 full
  Span 塞进每个 Core node，也不要在本项顺手扩一套正式 related-location API。

## ARC-12 — P3 — lowering cache 只活一个 comptime expression（已修）

<!-- audit-anchor: absent selfhost/src/ir/interp.dawn | LowerCache -->

> **已修（2026-08-11）：** `ESt` 拆成两半。module 级的 `LowerCache`（lowered 函数体、
> 字典表、lifted-lambda 计数器）由 `eval_module` 建一次，经 `CtRun` 串过全部 const
> 初始化器、函数体与 test 体里的 comptime block；per-evaluation 的 fuel 与 depth 仍由
> `st_from` 每次归零，所以一个 const 的预算不会被上一个花掉。缓存可以跨表达式复用的
> 依据是 lowering 的输入面：它读的是模块的 trait、impl、adt、签名与符号表，这些在一次
> `eval_comptime` 内固定，const/block 的值不参与 lowering（`CConstRef`/`CComptime` 是
> 解释期才查表的节点），因此同一 `(owner, fn)` 在哪个表达式里被要到都是同一份 Core。
> `next_lam` 一并进缓存并全程贯穿：lifted lambda 以生成名（`lambda$0`、`lambda$1`……）
> 为键存在同一张表里，计数器若按表达式重置，第二个表达式的 `lambda$0` 会盖掉第一个的
> 这正是明细点名的稳定 key 问题。缓存只在模块内活，`eval_comptime` 返回时即丢弃，
> 不进 `CtOut`（driver、emitter 与 `doc` 都会把 `CtOut` 留到整个构建结束，lowered 函数体
> 跟着走没有读者）。
>
> 门禁是 `ir/interp` 的 `one module's lowering cache outlives the expression that
> filled it`：它经私有 `eval_module` 直接读运行结束时的缓存，断言两个 const 共用的
> helper 仍在表里、两个各自 lift 一个 lambda 的 const 拿到了 `lambda$0` 与 `lambda$1`
> 两个名字。两个活变异各红一次：把 `fold_expr` 的入参缓存换回空表，`m.helper` 断言红；
> 把 `lower_expr_only` 的种子换回 `0`，`m.lambda$1` 断言红。
>
> **实测**（80 个函数的调用链 + 300 个 const 全调链首，`dawn check`，三次取范围）：
> 1.49–1.61s → 0.87–0.91s。

- **历史证据（修复前基线，S）：** `ESt` 持有 lowered function/dictionary cache，但每个 `fold_expr` 都 `fresh_st` 清空，module const 各自调用。
- **影响：** 多个 const 调同一 helper 时重复 lowering 与 lambda lifting；comptime 使用增长后形成无必要编译时间。
- **建议：** 拆 module-level `LowerCache` 与 per-evaluation fuel/env/depth；lifted-lambda identity 使用稳定 key。

## ARC-13（P1）：native RC 的 `unloop` 可删除仍被跳转指向的 loop label

> **已修（2026-08-12）：** `unloop` 的最后终止条件现在同时要求表达式不产生值，且不含
> 指向当前 loop id 的 `break` 或 `continue`。源码循环继续保留 `CSLoop`，match lowering
> 的一次性循环仍按原规则还原成分支树。

- **证据：V。** Core 用同一个 loop id 连接 `CSLoop` 与 `CBreak`/`CContinue`。range `for`
  和 `while` 都可能形成“退出测试加发散尾语句”的形状；旧 `unloop` 只检查尾语句
  `not yields(x)`，会把源码 body 的直接跳转误认成 match 的不可达 tail。
- **影响：** native RC pass 删除声明目标的 `CSLoop`，C emitter 却继续发出
  `goto Lx_end` 或 `goto Lx_step`。同一合法程序在 JVM 可运行，在 native 的 C 编译阶段
  因标签不存在而失败。
- **修复：** 复用已有递归 `jumps` walker，把终止判据收紧为
  `not yields(x) && not jumps(x, lid, true, true)`。不增加 loop kind，不关闭 match 的
  unloop 优化，也不让 C emitter 猜测缺失标签的位置。
- **门禁：** `scripts/spike-native/source_loop_targets.dawn` 固定 range、iterable、while、
  嵌套和条件跳转；`scripts/source-loop-label-contract/run.sh` 另有 compile-only continue
  目标与独立 `match_unloop_is_retained` control。删除新 jump 条件的 compiling mutant 必须
  构建，且 `--version` 输出单行 `dawn ...`；严格 matrix preflight 拒绝字段撒谎、重复、
  缺失和未知记录，并要求它只能把 `source_loop_target_is_retained` 变红。
- **设计记录：** [native-loop-control-design.md](../native-loop-control-design.md)。
