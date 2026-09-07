# `Never` 返回位命名与 JVM 终止设计

> 状态：**current**。已裁决方案的实现记录。语义边界来自 2026-08-10 的 SEM-14 裁决，
> 本文不重新裁决。

## 一、当前问题

编译器已经推断 `TyNever`，但用户不能在签名中写 `Never`。更严重的是，现有 JVM
后端把部分 bottom call 当成会继续执行的调用。直接调用和函数值调用出现在分支中时，
ASM 会生成不一致的 stack map，类加载随即报 `VerifyError`。同一程序经 C 后端编译后正常运行。

修复前的两个最小探针分别是直接调用与 `Fn0.apply` 调用。两者都在未选择的分支调用
`panic` 函数，JVM 在运行 `main` 前失败，native 分别输出预期的 `7` 与 `9`。

## 二、两刀边界

第一刀只修已有 inferred `TyNever` 的 JVM 正确性。所有调用形态在一个 call-result seam
收口。调用的静态结果是 bottom 时，发射器必须生成 verifier 可见的终止序列，并返回
`falls = false`。调用描述符没有结果时直接压入 `null` 并 `athrow`。描述符留下结果时先按
槽宽丢弃，再压入 `null` 并 `athrow`。

第二刀开放用户书写，但只开放函数返回位。允许的位置如下：

- 顶层函数与局部函数的返回类型。
- trait 方法、impl 方法与 effect operation 的返回类型。
- 任意函数类型的返回类型，因此 `fn() -> Never` 可以存储、传递并转换为 SAM。

其余直接出现 `Never` 的位置均拒绝，包括参数、字段、局部与常量标注、容器或泛型参数、
associated type binding，以及 alias 的直接目标。`alias F = fn() -> Never` 合法，
`alias N = Never` 非法。

`Never` 是 compiler-owned hard-reserved 名称。类型、alias、trait、effect、constructor 与
type parameter 不能用该名称声明。`io.exit` 保持 `Unit`。

这不是纯放宽：旧有 `type Never = ...` 等声明会从接受变为拒绝，这是有意的
source-breaking reservation。

## 三、类型解析方案

类型解析增加显式的 storage 与 return 两种使用上下文。公共 `resolve_type` 保持 storage
入口，函数签名的返回位使用 `resolve_return_type`。结构函数类型总是以 storage 解析参数，
以 return 解析结果。容器参数、tuple 元素、alias 直接目标和 associated binding 均递归回
storage，因此不会因为外层函数本身处于返回位而放宽内部存储位置。

builtin inventory 增加 return-only access。全局补全与 unknown-type 提示继续只读 public
view。LSP 仅在可以确认光标紧随函数返回箭头时加入 `Never`。`doc --builtins` 列出该名称，
同时输出它只允许用于返回位的机器可读属性。

## 四、JVM 调用结果方案

统一 seam 接收调用实际留下的 JVM 栈宽。bottom call 使用三种结果形态：无结果、单槽、
双槽。直接函数、具体 impl、default、字典方法、动态函数值、closure adapter 与 SAM bridge
都通过该 seam。这样 `falls` 与字节码终止由同一处决定，不再由每种调用自行猜测。

closure 的 erased `apply` 和 SAM bridge 在 verifier 看来返回 `Object`。它们必须先 `pop`，
再生成 `aconst_null; athrow`。普通 Dawn 静态 bottom 方法使用 `V` 描述符，不需要丢弃结果。

## 五、验证

- checker corpus 固定所有允许与拒绝上下文、hard-reserved 名称、body 必须发散及
  `io.exit` 签名。
- builtin type contract 固定 checker、return-context LSP completion 与 doc JSON surface。
- classfile verification 运行各调用形态的独立程序，并用 compiling mutants 逐项删除终止。
- native differential 固定 direct、dynamic、trait、impl 与 default 的 JVM/native 一致性。
- Core golden 只在两刀合并后的树上重录，随后运行自举 fixed point 与 gate-map 指定的差分。

## 六、不做的事

- 不允许 `Never` 作为字段、参数、容器元素或其他可存储值。
- 不给 `Never` 增加 constructor、默认值、Eq、Hash 或 Show。
- 不修改 `io.exit`，也不把宿主的 `System.exit` ABI 变成语言 bottom 契约。
- 不碰 SEM-04，也不顺带修改 Cursor 表示。
- 不用 `Emit-Change(emit selfhost)` 声明。gate-map 已证明该 oracle 对 selfhost 源码改动不可见。

## 七、2026-09-07：语句不落返的传播

复核发现 `let y: Int = stop(); println(y)` 的检查通过，但 JVM 编译器报
`symbol has no slot`；列表元素中的 stop/return 也可触发。`CSLet` 在初始化不落返时
不分配 slot 是正确的，错误是 `gen_cstmt` 丢掉了这个结论，`CBlock` 继续发射后续读 y。

修复使语句发射与表达式一样返回 `(Gen, falls)`。let、assign、discard、if 传播该位，
block 在第一条不落返语句后停止，既不发射后续语句也不发射尾值。if 的条件不落返也须
立即返回。循环仍保守认为可落返：body 不落返可能只是 break/continue，step 仍是
continue 的目标，不能因此删掉 step 或循环后的路径。CSDrop 在 JVM 是可落返的空操作。

回归覆盖直接初始化、列表首/非首元素、两支终止、嵌套块、赋值/discard/if、return、
break/continue 和仍可落返的负控。双后端输出为独立手写期望；编译可通过的 block
传播反转变异体必须使 owning regression 失败。Core 语义不变，只按惯例重录编译器
自身的 Core 哈希；不得用未声明的 emit 差异掩盖已有语料的变化。

本次不改变 Never 的可书写位置，不做通用 CFG/DCE，也不重构所有实参发射入口。

实现后的 613 项 selfhost 测试及 14 个 compiling Never 变异体通过，新增变异体只使
`NEVER_STATEMENT_FLOW` 失败。旧 release emit 差分通过；Core 文本语料不变，自身哈希
变动已重录。native ASan 另发现列表元素跳出/抛错会泄漏内部数组（#94）：本项的
双后端语料跑列表的未取分支（仍要求 JVM 编译其全部代码），classfile 探针另跑取分支；
取分支的 native 内存验收由 #94 补齐，不加 known-red 豁免。
